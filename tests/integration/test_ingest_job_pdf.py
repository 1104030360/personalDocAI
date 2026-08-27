"""PDF 入庫任務的整合測試（design5.md D11／D12、§4.4、§8 第 4〜5 列）。

與 test_ingest_job.py 同一套玩法：**不打 HTTP**，直接呼叫 run_ingest_job()。
PDF 的位元組用 Phase 28 就有的 tests/fakes.make_pdf_bytes(pages=N) 現產。

⚠ 這裡的「第幾頁」一律 **1 起算**（與現有 skipped_pages 的頁碼慣例相同）。
   程式裡的 pages_done 是「已處理幾頁」，所以做完第 2 頁時 pages_done == 2。
"""

from __future__ import annotations

from datetime import datetime

from app.repositories import photo_repository
from app.services import ingest_job, staging_service, storage_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FixedClock, make_pdf_bytes

NOW = FixedClock(datetime(2026, 8, 18, 10, 0))

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)
看不懂 = PhotoUnderstanding(understood=False)


class 分頁VLM:
    """指定「哪幾頁看得懂」的假件，用來重現「部分頁看不懂」。

    寫法照 tests/integration/test_ai_timing_log.py 的同名假件，但**在本檔自己定義一份**：
    跨測試檔 import 假件會把兩份測試綁在一起，那邊改一下這邊就跟著紅。

    與那一份的差別：這裡要處理**重試**，所以不能用「第幾次呼叫＝第幾頁」。
    改成自己數頁：看得懂的頁一次就過（頁碼 +1）；看不懂的頁會被連續問 3 次，
    第 3 次之後才換下一頁。
    """

    def __init__(self, 看得懂的頁碼: set[int], *, 每頁上限: int = 3) -> None:
        self.看得懂的頁碼 = 看得懂的頁碼  # 1 起算
        self.每頁上限 = 每頁上限
        self.calls = 0
        self.目前頁 = 1
        self.這一頁問過幾次 = 0
        self.每頁呼叫次數: dict[int, int] = {}

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        self.這一頁問過幾次 += 1
        頁 = self.目前頁
        self.每頁呼叫次數[頁] = self.每頁呼叫次數.get(頁, 0) + 1

        看得懂 = 頁 in self.看得懂的頁碼
        if 看得懂 or self.這一頁問過幾次 >= self.每頁上限:
            # 這一頁到此為止（成功、或用完 3 次要跳過），下一次呼叫算下一頁
            self.目前頁 += 1
            self.這一頁問過幾次 = 0
        return 收據理解 if 看得懂 else 看不懂


class 記得最後一筆的Store(InMemoryJobStore):
    """成功時 job 會被刪掉，但測試還想看「刪掉之前長什麼樣」。

    只多做一件事：delete() 之前先把那一筆抄一份存進 self.deleted。
    完全只用 JobStore 的公開介面（get／delete），不碰 InMemoryJobStore 的內部欄位
    （get() 回的本來就是獨立副本——Phase 57 的 _copy() 設計，連 photo_ids 都另外複製，
    所以存進 self.deleted 的快照不會被之後的動作改到）。
    Phase 57 的 InMemoryJobStore 建構子沒有參數，這裡的 super().__init__() 直接呼叫即可。
    """

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


def 建一個PDFjob(
    store: InMemoryJobStore,
    *,
    job_id: str = "pdf-1",
    pages: int = 2,
    data: bytes | None = None,
) -> str:
    """模擬 Phase 62 的 HTTP 端點會做的兩件事：落 staging ＋ 建 job。"""
    staging_service.save_staging(
        job_id,
        "application/pdf",
        data if data is not None else make_pdf_bytes(pages=pages),
    )
    store.create(
        job_id=job_id,
        filename="scan.pdf",
        content_type="application/pdf",
        ai_backend="local",
        source="upload",
    )
    return job_id


def 收件箱id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def 跑(job_id: str, store, vlm, embeddings=None) -> None:
    ingest_job.run_ingest_job(
        job_id,
        store=store,
        vlm=vlm,
        embeddings=embeddings or FakeEmbeddings(),
        now=NOW,
    )


# ------------------- ① 部分頁失敗：整筆仍然成功 -------------------


def test_兩頁PDF第二頁三次失敗_只入庫一列_job成功_skipped語意保留():
    """design5.md D12 ＋ §9：成功的頁進待決定，失敗的頁被跳過，整筆算成功。"""
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    vlm = 分頁VLM(看得懂的頁碼={1})

    跑(job_id, store, vlm)

    # 第 1 頁 1 次、第 2 頁 3 次 ＝ 共 4 次看圖
    assert vlm.每頁呼叫次數 == {1: 1, 2: 3}, vlm.每頁呼叫次數
    assert photo_repository.count_photos() == 1
    assert len(photo_repository.list_photos_in_folder(收件箱id())) == 1

    # 至少一頁成功 → 整筆成功 → job 被刪、staging 不在
    assert store.get(job_id) is None
    assert store.list_open() == []
    assert not staging_service.staging_path(job_id, "application/pdf").exists()

    # 「跳過幾頁」不需要多一個欄位——算得出來：pages_done − len(photo_ids)
    最後 = store.deleted[job_id]
    assert 最後["page_count"] == 2
    assert 最後["pages_done"] == 2, "跳過的頁也算處理過（design5 §4.3）"
    assert len(最後["photo_ids"]) == 1
    assert 最後["pages_done"] - len(最後["photo_ids"]) == 1, "＝跳過 1 頁"


def test_三頁全部看得懂_三列照片():
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=3)
    vlm = 分頁VLM(看得懂的頁碼={1, 2, 3})

    跑(job_id, store, vlm)

    assert vlm.calls == 3, "每頁一次就過，不該有補考"
    assert photo_repository.count_photos() == 3
    最後 = store.deleted[job_id]
    assert 最後["page_count"] == 3
    assert 最後["pages_done"] == 3
    assert len(最後["photo_ids"]) == 3


def test_每頁的重試次數各自獨立():
    """D12：重試單位是「一頁」。第 2 頁用掉 3 次，不影響第 3 頁還有 3 次可用。"""
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=3)
    vlm = 分頁VLM(看得懂的頁碼={1, 3})

    跑(job_id, store, vlm)

    assert vlm.每頁呼叫次數 == {1: 1, 2: 3, 3: 1}, vlm.每頁呼叫次數
    assert photo_repository.count_photos() == 2
    最後 = store.deleted[job_id]
    assert 最後["pages_done"] - len(最後["photo_ids"]) == 1


# ------------------- ② 整筆失敗的兩種情況 -------------------


def test_每一頁都看不懂_列數0_job標failed():
    """design5.md §8 第 5 列：0 頁成功＝整筆失敗、不留任何 photo 列。"""
    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, pages=2)
    vlm = 分頁VLM(看得懂的頁碼=set())

    跑(job_id, store, vlm)

    assert vlm.每頁呼叫次數 == {1: 3, 2: 3}
    assert photo_repository.count_photos() == 0
    assert not staging_service.staging_path(job_id, "application/pdf").exists()
    job = store.get(job_id)
    assert job is not None, "失敗的 job 要留給進度面板"
    assert job["status"] == "failed"
    assert job["page_count"] == 2
    assert job["pages_done"] == 2
    assert job["photo_ids"] == []


def test_壞檔拆不開_job標failed且不留列():
    """design5.md §8 第 5 列的另一半：檔壞到無法拆頁。

    「零頁 PDF」在 pdf_service.render_pages 裡走的是**同一個** PdfUnreadableError
    （壞檔在開檔時丟、零頁在 `if len(document) == 0` 那兩行丟——對本函式來說
    兩種都是同一個例外、同一條 _fail 路），所以整合層驗 b"not a pdf" 這一條就夠。
    壞檔那一半另有 Phase 28 的單元測試 test_壞檔丟PdfUnreadableError 釘著；
    零頁那一半沒有單元測試，也做不出來——make_pdf_bytes(pages=0) 會直接
    ValueError（見本檔陷阱 10），Pillow 根本寫不出零頁的 PDF 檔。
    """
    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, data=b"this is not a pdf at all")
    vlm = 分頁VLM(看得懂的頁碼={1, 2, 3})

    跑(job_id, store, vlm)

    assert vlm.calls == 0, "拆不開就不該打模型"
    assert photo_repository.count_photos() == 0
    assert not staging_service.staging_path(job_id, "application/pdf").exists()
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["page_count"] is None, "沒拆成頁就沒有頁數（design5 §4.3）"


def test_某頁寫檔失敗_當成跳過該頁_其他頁照樣入庫(monkeypatch):
    """本計畫的裁決（design5 沒明寫）：PDF 某頁寫檔失敗＝跳過那一頁。

    理由見計畫文件 phase-60 §4 步驟 3 的「⚠ 一個 design5 沒寫、要自己裁決的情況」。
    半成品由 _insert_photo_with_files 自己清乾淨，所以不會留孤兒列或孤兒檔。
    """
    真的縮圖 = storage_service.make_thumbnail
    狀態 = {"次數": 0}

    def 第一次成功之後都失敗(photo_id, image_bytes, content_type):
        狀態["次數"] += 1
        if 狀態["次數"] == 1:
            return 真的縮圖(photo_id, image_bytes, content_type)
        raise RuntimeError("磁碟壞了")

    monkeypatch.setattr(storage_service, "make_thumbnail", 第一次成功之後都失敗)

    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    vlm = 分頁VLM(看得懂的頁碼={1, 2})

    跑(job_id, store, vlm)

    assert photo_repository.count_photos() == 1, "第 2 頁沒進去，也不可以留孤兒列"
    最後 = store.deleted[job_id]
    assert 最後["pages_done"] == 2
    assert len(最後["photo_ids"]) == 1


# ------------------- ③ 崩潰重送：從 pages_done 續跑 -------------------


def test_重送從pages_done續跑_已成功的頁不重看也不重插():
    """design5.md §4.4：PDF 依 pages_done 從下一頁繼續。

    重現方式：手動把 job 調成「第 1 頁已經做完」的樣子（pages_done=1、
    photo_ids 帶著那一頁的 id），再跑一次 → 只會處理第 2、3 頁。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=3)

    # 先做出「被殺之前已經做完第 1 頁」的狀態：資料庫有一列、job 記著 pages_done=1。
    # 這裡直接用 repository 插一列就好——本顆測試要的是那個**狀態**，不必真的跑一次看圖。
    # 也刻意**不呼叫 ingest_job 的私有函式**：它日後多一個參數（Phase 61 就會多一個
    # entities）就會害這顆測試無故變紅，而那跟續跑一點關係都沒有。
    第一頁 = photo_repository.insert_photo(
        text=收據理解.text,
        category="未分類",
        location=收據理解.location,
        items=收據理解.items,
        content_time=None,
        embedding=FakeEmbeddings().embed_query(收據理解.text),
        uploaded_at=NOW(),
    )
    photo_id = 第一頁["id"]
    store.update(job_id, page_count=3, pages_done=1, photo_ids=[photo_id])
    assert photo_repository.count_photos() == 1

    # 佇列把同一個任務再發一次
    續跑的vlm = 分頁VLM(看得懂的頁碼={1, 2, 3})  # 這個假件自己從第 1 頁數起
    跑(job_id, store, 續跑的vlm)

    assert 續跑的vlm.calls == 2, "只該看第 2、3 頁，第 1 頁不重看"
    assert photo_repository.count_photos() == 3, "第 1 頁不可以被插第二次"
    assert store.get(job_id) is None
    最後 = store.deleted[job_id]
    assert 最後["pages_done"] == 3
    assert len(最後["photo_ids"]) == 3
    assert 最後["photo_ids"][0] == photo_id, "原本那一頁的 id 要留著"


def test_重送時全部頁都做完了_直接收尾不重看():
    """極端情況：被殺在「最後一頁做完」與「刪 job」之間。"""
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    vlm = 分頁VLM(看得懂的頁碼={1, 2})
    跑(job_id, store, vlm)
    已入庫 = [p["id"] for p in photo_repository.list_photos_in_folder(收件箱id())]

    # 同一個 job_id 重建，狀態停在「兩頁都做完」
    staging_service.save_staging(job_id, "application/pdf", make_pdf_bytes(pages=2))
    store.create(
        job_id=job_id,
        filename="scan.pdf",
        content_type="application/pdf",
        ai_backend="local",
        source="upload",
    )
    store.update(job_id, page_count=2, pages_done=2, photo_ids=已入庫)
    第二次的vlm = 分頁VLM(看得懂的頁碼={1, 2})

    跑(job_id, store, 第二次的vlm)

    assert 第二次的vlm.calls == 0
    assert photo_repository.count_photos() == 2
    assert store.get(job_id) is None
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


# ------------------- ④ 清單只讀一次 -------------------


def test_整份PDF的資料夾與糾錯清單只讀一次(monkeypatch):
    """與現在 _ingest_pdf 的行為一致：清單在迴圈外讀，不是每頁各讀一次。

    每頁各讀一次不只是浪費，還會讓「同一份 PDF 的每一頁看到不一樣的 prompt」
    變成可能（例如中途有人自建了資料夾），那樣同一份檔的頁與頁之間就不一致了。
    """
    次數 = {"folders": 0, "corrections": 0}
    真的folders = photo_repository.list_folders
    真的corrections = photo_repository.recent_corrections

    def 數folders():
        次數["folders"] += 1
        return 真的folders()

    def 數corrections(limit=5):
        次數["corrections"] += 1
        return 真的corrections(limit)

    monkeypatch.setattr(photo_repository, "list_folders", 數folders)
    monkeypatch.setattr(photo_repository, "recent_corrections", 數corrections)

    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, pages=3)
    跑(job_id, store, 分頁VLM(看得懂的頁碼={1, 2, 3}))

    assert 次數["folders"] == 1, "整份 PDF 只讀一次資料夾清單"
    assert 次數["corrections"] == 1, "整份 PDF 只讀一次糾錯清單"
