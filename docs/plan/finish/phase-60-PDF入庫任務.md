# Phase 60：PDF 入庫任務（一個任務處理整份檔、每頁各自 3 次）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 特別是：**不要**把每一頁拆成一個 Celery 任務（design5 §1.2 已否決）、不要做頁數上限、
> 不要做「只重跑失敗的那幾頁」的手動補跑功能、不要為 PDF 另開端點，
> 也**不要動 `app/api/routers/photos.py` 一個字**（`POST /photos` 要到 Phase 62 才改）。

> 🎯 **一句話目標：** 在 Phase 59 建好的 `app/services/ingest_job.py` 裡加上 `_run_pdf_job()`，
> 讓**同一個 worker**把一份 PDF 從第一頁看到最後一頁：每一頁各自最多 3 次，看不懂就跳過那一頁、
> 其他頁照樣入庫；一頁都沒成功（或檔案根本拆不開）才整筆失敗；
> 中途被殺掉時，重送會從 `pages_done` 的**下一頁**接著跑，已經成功的頁不重看、不重插。

**為什麼要做這個：**

PDF 是本專案唯一「一個檔案會變成好幾張照片」的東西。Phase 59 的單圖流程處理不了它——
單圖只需要一次「看圖→轉向量→INSERT」，PDF 需要一個迴圈。

而且 PDF 的失敗規則跟單圖**不一樣**：單圖看不懂就整張沒了；
PDF 某一頁看不懂只該跳過那一頁（現有 `skipped_pages` 的語意），其他頁還是要進待決定。
產品負責人也明確要求「一個檔案在進度面板上就是一列」（D11）——所以不能拆成每頁一個任務，
否則同一份檔會被兩個 worker 拆開跑，進度列根本畫不出來。

還有一個 Phase 59 沒遇到的問題：**PDF 很慢**。三頁就是三次看圖，本機實測一頁 60〜90 秒。
worker 在中間被殺掉的機率遠比單圖高，所以「重送要能接著跑」不是理論問題，是會真的發生的事。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **拆頁／渲染（render）** | 把 PDF 的每一頁「畫」成一張圖片。PDF 是向量格式（線條與文字的描述），沒有現成的像素，要自己畫出來才能給 VLM 看。專案裡由 `app/services/pdf_service.py` 負責 |
| **`pages_done`** | JobStore 裡的一個數字：這份 PDF **已經處理過幾頁**。注意是「處理過」不是「成功幾頁」——**跳過的頁也算處理過**（design5 §4.3 原文：「PDF 已處理頁數（含跳過）」） |
| **續跑（resume）** | 重送時不從第一頁開始，而是從 `pages_done` 的下一頁接著做 |
| **跳過（skip）** | 這一頁 3 次都看不懂，就當它不存在：不入庫、不報錯，繼續看下一頁。這是 design3 就有的 `skipped_pages` 語意 |
| **重試單位** | 「失敗時要重做的最小範圍」。本專案的重試單位是**一頁**，不是整份檔（D12）。整份當單位的話，第 5 頁失敗會害前 4 頁重看一次，雲端費用與時間都乘上頁數 |

---

## 1. 對應 design5.md 章節

| 章節／編號 | 內容 |
|---|---|
| **D11** | PDF 一檔一任務：進度列一個檔一列；**一個 Celery 任務＝一個檔案**；同一份 PDF 的每一頁由**同一個 worker 依序**看完，不拆成每頁一個任務 |
| **D12** | PDF 以頁為重試單位：每一頁各自最多 3 次；仍失敗就跳過（現有 `skipped_pages` 語意）；成功的頁進待決定；**整份 0 頁成功**（或檔壞到無法拆頁）才整筆失敗、不留照片 |
| **§2 流程** | 「PDF：拆頁後依序；每頁 VLM 最多 3 次；失敗跳過；成功頁各自 INSERT；0 頁成功 → 整筆失敗、刪 staging、不留列」 |
| **§4.3** | `page_count`（PDF 才有；拆頁後才填，未拆前可為 null）、`pages_done`（已處理頁數，含跳過） |
| **§4.4 崩潰重送** | 「PDF：依 `pages_done` 從下一頁繼續；已成功的頁不重看、不重 INSERT」 |
| **§6.6 進度面板** | `queued` 顯示「檔名（N 頁）」；`analyzing`／`retrying` 加「第 p／N 頁」 |
| **§8 錯誤表第 4 列** | PDF 某一頁 ×3 → 跳過該頁；其他頁繼續 |
| **§8 錯誤表第 5 列** | PDF 0 頁成功，或檔無法拆頁 → 同第 3 列（刪 staging、無 `photo` 列、job=`failed`） |
| **§9 測試策略** | 「PDF 兩頁、第二頁三次失敗 → 一列照片、job 成功（不在清單）、skipped 語意保留」「PDF 全頁失敗 → 列數 0、failed」 |
| **§1.2 被否決** | 「PDF 每一頁一個 Celery 任務」「整份 PDF 當重試單位（一頁失敗就從頭再跑）」 |

D16（建議三欄落庫）是 **Phase 61**，本 phase 不做。

---

## 2. 前置條件

- **Phase 59 已完成**：`app/services/ingest_job.py` 有 `run_ingest_job`／`_run_image_job`／
  `_understand_and_embed`／`_insert_photo_with_files`／`_fail`，且 `tests/integration/test_ingest_job.py` 11 顆全綠。
- **Phase 57／58 已完成**（Phase 59 的前置，這裡一併沿用）。
- `pdf_service.render_pages()` 與 `tests/fakes.py` 的 `make_pdf_bytes()` **早在 Phase 28 就有了**，本 phase 不改它們。

開工前**實際跑一次**確認基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps                      # db 必須是 Up (healthy)
pytest -q
```

把顆數抄下來（＝ Phase 59 結束時的數字）。

確認三個前置真的在：

```bash
python -c "
from app.services import ingest_job, pdf_service
from tests.fakes import make_pdf_bytes
print('run_ingest_job：', callable(ingest_job.run_ingest_job))
print('私有函式：', [n for n in ('_run_image_job','_understand_and_embed','_insert_photo_with_files','_fail') if hasattr(ingest_job, n)])
print('render_pages 三頁 →', len(pdf_service.render_pages(make_pdf_bytes(3))), '張 PNG')
"
```

預期：三行都正常，最後一行印出 `3 張 PNG`。

> ⚠️ **絕對不要同時跑兩份 pytest**（會互相 TRUNCATE 測試庫，症狀是一片看似隨機的 404）。

---

## 3. 範圍

### 做

1. `app/services/ingest_job.py`：
   - 新增兩個錯誤訊息常數 `ERROR_PDF_UNREADABLE`、`ERROR_PDF_ALL_PAGES_FAILED`。
   - `run_ingest_job` 的 PDF 分支：把 Phase 59 留的 `raise NotImplementedError(...)` 換成 `_run_pdf_job(...)`。
   - 新增 `_run_pdf_job(...)`：拆頁 → 填 `page_count` → 從 `pages_done` 續跑 → 逐頁各 3 次 →
     成功就 INSERT 並 append `photo_ids`、失敗就跳過 → 每頁做完更新 `pages_done` →
     至少一頁成功就整筆成功（刪 staging、刪 job），一頁都沒成功就整筆失敗。
2. 新建 `tests/integration/test_ingest_job_pdf.py`（9 顆）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 每頁一個 Celery 任務 | design5 §1.2 已否決：同一份檔會被兩個 worker 拆開跑，進度面板畫不出「一檔一列」 |
| 整份 PDF 當重試單位 | design5 §1.2 已否決：第 5 頁失敗會害前 4 頁重看，雲端費用與時間乘上頁數 |
| 在 `IngestJob` 加一個 `skipped_pages` 欄位 | 契約備忘 §3.1 的欄位表**一個字都不准改**。跳過幾頁是**算得出來的**：`pages_done − len(photo_ids)`（見 §4 步驟 3 的說明） |
| 保留 PDF 原始檔 | design3 D7 起就沒有：照片的「原圖」＝該頁渲染出來的 PNG。成功／失敗都刪 staging |
| 頁數上限、加密 PDF 支援 | design3 Phase 28 就明確不做，本增量不改 |
| 「重跑失敗的那幾頁」按鈕 | design5 §3「不做」：失敗列沒有手動再試一次，要重來就重新選檔 |
| 改 `photos.py` 的 `_ingest_pdf()` | 它還是 `POST /photos` 的正式路徑，Phase 62 才退休 |
| 改 `pdf_service.py` | 它已經夠用了（Phase 28）。本 phase 一個字都不動它 |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：步驟 1 先寫會紅的測試、步驟 2 跑它確認紅、步驟 3 寫實作、
> 步驟 4 轉綠、步驟 5 全量回歸、步驟 6 commit。

### - [ ] 步驟 1：先寫測試（紅）——新增 `tests/integration/test_ingest_job_pdf.py`

```python
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
        self.看得懂的頁碼 = 看得懂的頁碼      # 1 起算
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
    續跑的vlm = 分頁VLM(看得懂的頁碼={1, 2, 3})   # 這個假件自己從第 1 頁數起
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
```

### - [ ] 步驟 2：跑它，確認是**紅的**

```bash
pytest tests/integration/test_ingest_job_pdf.py -q
```

預期：9 顆全紅。大部分會是 `NotImplementedError: PDF 任務在 Phase 60 實作`（Phase 59 留的樁），
`test_壞檔拆不開…` 也是同一個錯誤。**這就是紅**。

### - [ ] 步驟 3：綠——改 `app/services/ingest_job.py`

**3-1. 常數區**：在 `ERROR_WRITE_FAILED = "照片存檔失敗，這張沒有留下資料"` 那一行**後面**，
把下面整段照抄貼上（一個 PDF 頁的 content type ＋ 兩個新錯誤訊息；
`PDF_PAGE_CONTENT_TYPE` 與 `photos.py` 的同名常數**同值**——photos.py 那一份 Phase 62 會刪，這裡是它的接班人）：

```python
# PDF 的每一頁渲染出來都是 PNG，之後就完全是一次普通的單圖入庫
#（原圖存成 .png、讀圖端點零改動，不必為 PDF 另開一條路）
PDF_PAGE_CONTENT_TYPE = "image/png"

ERROR_PDF_UNREADABLE = "這份 PDF 讀不開或沒有內容"
ERROR_PDF_ALL_PAGES_FAILED = "PDF 每一頁 AI 都看不懂"
```

（`ERROR_VLM_FAILED` 與 `ERROR_WRITE_FAILED` 是 Phase 59 就有的，不動。）

**3-2. `run_ingest_job` 的 PDF 分支**：把 Phase 59 留的樁

```python
    if job["content_type"] == config.PDF_CONTENT_TYPE:
        # Phase 60 才實作。目前不可能走到這裡——沒有任何地方會建出 PDF 任務
        #（POST /photos 要到 Phase 62 才改成入列）。
        raise NotImplementedError("PDF 任務在 Phase 60 實作")

    _run_image_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)
```

改成

```python
    if job["content_type"] == config.PDF_CONTENT_TYPE:
        _run_pdf_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    _run_image_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)
```

**3-3. 在 `_run_image_job` 的正下方**加上 `_run_pdf_job`：

```python
def _run_pdf_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一份 PDF 的完整入庫：同一個 worker 依序把每一頁看完（design5.md D11、D12）。

    ★ 一個任務 ＝ 一個檔案。**不要**把每一頁再丟成一個 Celery 任務——
      那樣同一份檔會被兩個 worker 拆開跑，進度面板畫不出「一檔一列」（§1.2 已否決）。

    ★ 重試單位是「一頁」，不是整份檔。每一頁各自最多 config.VLM_MAX_ATTEMPTS 次，
      仍失敗就**跳過那一頁**繼續下一頁（沿用 design3 起就有的 skipped_pages 語意）。
      整份 0 頁成功（或檔案根本拆不開）才整筆失敗。

    ★ 冪等（design5.md §4.4）：從 job["pages_done"] 的**下一頁**接著跑。
      pages_done ＝「已處理幾頁」，**含跳過的頁**（§4.3 原文）。
      已經成功的頁不重看、不重 INSERT，它們的 id 留在 photo_ids 裡。

    ★ 「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
      IngestJob 的欄位表是跨文件契約，不為了一個衍生值多開一欄。
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 拆頁。整份讀不開（壞檔、加密、零頁）＝這次上傳什麼都存不了
    pdf_bytes = staging_service.read_staging(job_id, content_type)
    try:
        page_images = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        logger.warning("job %s：PDF 拆頁失敗", job_id, exc_info=True)
        _fail(job_id, ERROR_PDF_UNREADABLE, store=store, content_type=content_type)
        return

    # ② 拆得開才知道幾頁（design5.md §4.3：未拆前 page_count 可為 null）
    store.update(job_id, page_count=len(page_images))

    # ③ 清單在迴圈**外面**讀一次：整份 PDF 的每一頁共用同一份注入 prompt
    #（與現在 photos.py 的 upload_photo 讀一次、傳給每頁的作法一致）
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
    inbox = next(folder for folder in folders if folder["is_inbox"])

    # ④ 從上次做到的地方接著跑
    photo_ids: list[int] = list(job.get("photo_ids") or [])
    already_done = job.get("pages_done") or 0
    if already_done:
        logger.info(
            "job %s：崩潰重送，已處理 %d／%d 頁，從第 %d 頁接著跑",
            job_id,
            already_done,
            len(page_images),
            already_done + 1,
        )

    # enumerate 的 start 讓頁碼從「下一頁」開始算，1 起算（與 skipped_pages 同一套）
    for page_number, page_bytes in enumerate(
        page_images[already_done:], start=already_done + 1
    ):
        photo_id: int | None = None
        result = _understand_and_embed(
            job_id,
            page_bytes,
            PDF_PAGE_CONTENT_TYPE,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            folders=folders,
            entities=entities,
            corrections=corrections,
            inbox_name=inbox["name"],
        )
        if result is None:
            logger.warning(
                "job %s：第 %d 頁試了 %d 次仍失敗，跳過這一頁",
                job_id,
                page_number,
                config.VLM_MAX_ATTEMPTS,
            )
        else:
            understanding, embedding = result
            try:
                photo_id = _insert_photo_with_files(
                    page_bytes,
                    PDF_PAGE_CONTENT_TYPE,
                    understanding,
                    embedding,
                    inbox_name=inbox["name"],
                    folders=folders,
                    uploaded_at=now(),
                )
            except Exception:
                # 半成品已由 _insert_photo_with_files 自己清乾淨（檔案＋資料列）。
                # 這一頁當成「跳過」處理，不讓它拖垮已經成功的其他頁——
                # 理由見計畫文件 phase-60 §4 步驟 3 的裁決說明。
                logger.exception(
                    "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁",
                    job_id,
                    page_number,
                )

        if photo_id is not None:
            photo_ids.append(photo_id)
        # ★ 成功或跳過都要記 pages_done，而且要與 photo_ids **同一次**寫進去：
        #   分兩次寫的話，剛好被殺在中間的重送會把同一頁再做一次。
        store.update(job_id, pages_done=page_number, photo_ids=list(photo_ids))

    # ⑤ 收尾：至少一頁成功就算整筆成功（design5.md D12）
    if not photo_ids:
        _fail(
            job_id,
            ERROR_PDF_ALL_PAGES_FAILED,
            store=store,
            content_type=content_type,
        )
        return

    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    logger.info(
        "job %s 入庫完成：%d 頁中 %d 頁成功、%d 頁跳過（photo_ids=%s）",
        job_id,
        len(page_images),
        len(photo_ids),
        len(page_images) - len(photo_ids),
        photo_ids,
    )
```

**3-4. import 區要補一個 `pdf_service`。** Phase 59 的清單裡**沒有**它（單圖用不到）。
把檔案上方的

```python
from app.services import (
    ai_timing,
    indexing_service,
    staging_service,
    storage_service,
    vlm_service,
)
```

改成

```python
from app.services import (
    ai_timing,
    indexing_service,
    pdf_service,
    staging_service,
    storage_service,
    vlm_service,
)
```

（漏了這一步的話，步驟 4 會直接紅在 `NameError: name 'pdf_service' is not defined`。）

> ⚠️ **一個 design5 沒寫、要自己裁決的情況：PDF 某一頁「寫檔／寫資料庫」失敗怎麼辦？**
>
> design5 §8 只寫了兩件事：第 4 列「某一頁 VLM ×3 → 跳過」、第 7 列「入庫寫檔失敗 → 清掉半成品再標失敗」。
> 但第 7 列講的是單圖。PDF 跑到第 3 頁才寫檔失敗時，前兩頁**已經進資料庫了**，
> 「整筆標失敗、不留照片」就得回頭把它們刪掉——那又和 D12「已成功的頁不重看、不重 INSERT」互相打架。
>
> **本計畫的裁決：把它當成「這一頁跳過」。** 三個理由：
> 1. 半成品清理由 `_insert_photo_with_files` 內部完成（`remove_if_exists` ×2 ＋ `delete_photo`），
>    所以「不留孤兒列、不留孤兒檔」這條硬規則仍然成立——第 7 列的核心要求沒有被違反。
> 2. 對使用者來說結果與「這一頁看不懂」一模一樣：那一頁沒進待決定，其他頁進了。
>    不必為了一個罕見的磁碟錯誤發明第三種 PDF 結局。
> 3. 如果**每一頁**都寫檔失敗（真的磁碟壞了），`photo_ids` 會是空的 → 走 ⑤ 的整筆失敗，
>    使用者照樣在進度面板看得到紅字。壞事不會被吞掉。
>
> 這個裁決由 `test_某頁寫檔失敗_當成跳過該頁_其他頁照樣入庫` 釘住。

### - [ ] 步驟 4：跑新測試，看它轉綠

```bash
pytest tests/integration/test_ingest_job_pdf.py -v
```

預期最後一行：`9 passed`。

Phase 59 的那 11 顆也要一起確認沒被弄壞：

```bash
pytest tests/integration/test_ingest_job.py tests/integration/test_ingest_job_pdf.py -q
```

預期：`20 passed`（11 ＋ 9）。

### - [ ] 步驟 5：全量回歸

```bash
pytest -q
```

預期：**Phase 59 結束時的顆數 ＋ 9**，全綠、0 skipped。

零外部依賴實證：

```bash
OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q
```

預期：顆數相同。

### - [ ] 步驟 6：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/services/ingest_job.py tests/integration/test_ingest_job_pdf.py
git commit -m "feat: Phase 60 PDF 入庫任務——一個任務處理整份檔、每頁各自 3 次、失敗跳頁、0 頁成功才整筆失敗、依 pages_done 續跑擋重送，+9 tests"
```

---

## 5. ASCII 圖

### 5.1 一份 3 頁 PDF 的處理時間軸（頁 1 成功、頁 2 三次失敗跳過、頁 3 成功）

```text
時間 ──────────────────────────────────────────────────────────────────────▶

run_ingest_job("pdf-7")           ┌── JobStore 那一列長什麼樣 ──────────────┐
│                                 │ status  attempt page_count pages_done   │
├ store.update(status=analyzing)  │ analyzing  0      null        0         │  面板：分析中
│                                 └─────────────────────────────────────────┘
├ read_staging → data/staging/pdf-7.pdf
├ render_pages → [頁1.png, 頁2.png, 頁3.png]
├ store.update(page_count=3)      │ analyzing  0       3          0         │  面板：分析中（0/3）
├ 讀 folders / entities / corrections（**整份只讀這一次**）
│
│ ┌──── 第 1 頁 ────────────────────────────────────────────────────────┐
│ │ attempt 1  update(status=analyzing, attempt=1)                      │  面板：第 1/3 頁 第 1 次
│ │            log_ai(vlm) → 看得懂 ✓   log_ai(embed) → ✓               │
│ │            INSERT photo#51 → 寫 data/photos/51.png ＋ thumbs/51.png │
│ │            update(pages_done=1, photo_ids=[51])                     │  面板：第 1/3 頁 完成
│ └─────────────────────────────────────────────────────────────────────┘
│
│ ┌──── 第 2 頁（這一頁 AI 怎麼看都看不懂）────────────────────────────┐
│ │ attempt 1  update(status=analyzing, attempt=1) → 看不懂 ✗           │  面板：第 2/3 頁 第 1 次
│ │ attempt 2  update(status=retrying,  attempt=2) → 看不懂 ✗           │  面板：第 2/3 頁 第 2 次
│ │ attempt 3  update(status=retrying,  attempt=3) → 看不懂 ✗           │  面板：第 2/3 頁 第 3 次
│ │            _understand_and_embed 回 None → **跳過這一頁**            │
│ │            （不 INSERT、不寫檔、不報錯、不中斷整份）                │
│ │            update(pages_done=2, photo_ids=[51])  ← photo_ids 沒變   │
│ └─────────────────────────────────────────────────────────────────────┘
│                                   ↑
│                    ★ 第 2 頁用掉 3 次，**不影響第 3 頁**——
│                      重試單位是「一頁」，attempt 每頁重新從 1 開始（D12）
│
│ ┌──── 第 3 頁 ────────────────────────────────────────────────────────┐
│ │ attempt 1  update(status=analyzing, attempt=1) → 看得懂 ✓ → embed ✓ │  面板：第 3/3 頁 第 1 次
│ │            INSERT photo#52 → 寫檔                                    │
│ │            update(pages_done=3, photo_ids=[51, 52])                 │
│ └─────────────────────────────────────────────────────────────────────┘
│
├ photo_ids 非空（有 2 個）→ **整筆算成功**（design5 D12）
├ remove_staging("pdf-7")   ← 暫存檔刪掉
└ store.delete("pdf-7")     ← job 刪掉 → 面板那一列消失、待決定（N）+2

最終結果
  photo 表：+2 列（都在收件箱「未分類」）
  跳過幾頁：pages_done(3) − len(photo_ids)(2) = 1 頁     ← 不必另存欄位，算得出來
  staging：不在
  JobStore：這筆不見了（成功＝刪掉）

⚠ 對照組：如果三頁**全部**看不懂
  photo_ids 是空的 → _fail(...) → 刪 staging、status="failed"、job **留著**
  面板：紅字一列「scan.pdf ── PDF 每一頁 AI 都看不懂」，右上 × 可以關掉
  photo 表：0 列
```

### 5.2 worker 被殺在第 3 頁，重送時從第 4 頁開始

```text
一份 5 頁的 PDF。worker 做到第 3 頁的時候，你按了 `docker compose restart worker`。

┌────────────────────── 第一次（被殺）──────────────────────────────────┐
│                                                                       │
│  頁1 ✓ INSERT #61  → update(pages_done=1, photo_ids=[61])             │
│  頁2 ✓ INSERT #62  → update(pages_done=2, photo_ids=[61,62])          │
│  頁3   看到一半 💥 worker 被殺                                        │
│                                                                       │
│  JobStore 裡這筆的樣子（Redis 裡，行程死了它還在）：                   │
│     { job_id: "pdf-9", status: "analyzing", attempt: 2,               │
│       page_count: 5, pages_done: 2, photo_ids: [61, 62] }             │
│                                                                       │
│  資料庫：photo#61、#62 已經在收件箱裡了                                │
│  staging：data/staging/pdf-9.pdf 還在（成功或最終失敗才刪）            │
└───────────────────────────────────────────────────────────────────────┘
                              │
          Celery 沒收到「做完了」的回報 → 把同一個任務再發一次
                              ▼
┌────────────────────── 重送（續跑）────────────────────────────────────┐
│                                                                       │
│  run_ingest_job("pdf-9")                                              │
│    store.update(status="analyzing")     ← 面板那一列動起來            │
│    content_type 是 PDF → _run_pdf_job                                 │
│    read_staging  → 檔案還在，讀得到                                    │
│    render_pages  → 又拆成 5 張（拆頁是純計算，重做一次無害）           │
│    store.update(page_count=5)           ← 寫一樣的值，沒差            │
│                                                                       │
│    already_done = job["pages_done"] = 2                               │
│    photo_ids    = job["photo_ids"]   = [61, 62]                       │
│                                                                       │
│    for page_number, page_bytes in enumerate(                          │
│            page_images[2:],  ← 切掉前 2 頁                            │
│            start=3):         ← 頁碼從 3 開始算                        │
│                                                                       │
│      頁3 ✓ INSERT #63 → update(pages_done=3, photo_ids=[61,62,63])    │
│      頁4 ✓ INSERT #64 → update(pages_done=4, photo_ids=[…,64])        │
│      頁5 ✓ INSERT #65 → update(pages_done=5, photo_ids=[…,65])        │
│                                                                       │
│    photo_ids 非空 → remove_staging → store.delete                     │
│                                                                       │
│  結果：照片剛好 5 張（61〜65），頁 1、2 **一次都沒有被重看**。          │
│        以本機 gemma4 一頁 60〜90 秒計算，這省下了 2〜3 分鐘與 2 次雲端費用。│
└───────────────────────────────────────────────────────────────────────┘

⛔ 對照：如果重試單位是「整份檔」（design5 §1.2 已否決的作法）
   重送會從頁 1 開始重看 → 5 頁全部重跑一次
   而且 photo#61、#62 已經在資料庫裡了 → 會再插一次 → 變成 7 張照片
```

---

## 6. 驗收清單

- [ ] `run_ingest_job` 的 PDF 分支不再是樁：
      ```bash
      grep -n "NotImplementedError" app/services/ingest_job.py || echo "OK：樁已經換成 _run_pdf_job"
      ```
      預期印出 `OK：樁已經換成 _run_pdf_job`
- [ ] 續跑真的是從 `pages_done` 切的：
      ```bash
      grep -n "pages_done\|page_images\[" app/services/ingest_job.py
      ```
      預期看到 `already_done = job.get("pages_done") or 0`、`page_images[already_done:]`、
      `start=already_done + 1`，以及迴圈裡的 `store.update(job_id, pages_done=page_number, photo_ids=…)`
- [ ] 清單只在迴圈外讀（不是每頁各讀一次）：
      ```bash
      awk '/def _run_pdf_job/,/^def _understand_and_embed/' app/services/ingest_job.py | grep -n "list_folders\|list_entities\|recent_corrections\|for page_number"
      ```
      預期四行：`list_folders`／`list_entities`／`recent_corrections` 各**一次**，
      而且行號都**小於** `for page_number` 那一行（＝讀清單在迴圈外面）
- [ ] `IngestJob` 沒有被偷偷加欄位（跨文件契約）：
      ```bash
      grep -n "skipped_pages" app/services/ingest_job_store.py || echo "OK：欄位表沒有 skipped_pages"
      grep -n "skipped_pages=" app/services/ingest_job.py || echo "OK：也沒有人往 store 塞這個鍵"
      ```
      預期兩行都印 OK。（第二條**故意帶 `=`**：`_run_pdf_job` 的 docstring 刻意寫著
      「skipped_pages 語意」這幾個字說明沿革，不帶 `=` 會誤中說明文字、永遠印不出 OK；
      帶 `=` 抓的是 `store.update(..., skipped_pages=...)` 這種真的在塞欄位的寫法。）
- [ ] `ingest_job.py` 仍然沒有 HTTP／佇列的 import：
      ```bash
      grep -nE "^(import|from) +(fastapi|celery|redis)" app/services/ingest_job.py || echo "OK"
      ```
      預期印出 `OK`（只查 import 行——docstring 裡「沒有 HTTPException」「不連 Redis」
      這些說明文字是刻意寫的，grep 字面會誤中，理由同 phase-59 §6 的同名檢查）
- [ ] SQL 仍只在 repository（跑既有的自動化掃碼那一顆）：
      ```bash
      pytest tests/integration/test_design3_error_paths.py -k "SQL只出現在repository" -v
      ```
      預期 `1 passed`（不要自己 grep 大寫 `UPDATE ` 之類的字面——`ingest_job.py` 與
      `photos.py` 的說明文字裡本來就有這些詞，會誤中；理由詳見 phase-59 §6 同名項）
- [ ] `photos.py`、`camera.py`、`pdf_service.py` **一個字都沒改**：
      ```bash
      git diff --stat app/api/routers/photos.py app/api/routers/camera.py app/services/pdf_service.py
      ```
      預期：**無輸出**
- [ ] `pytest tests/integration/test_ingest_job_pdf.py -v` → `9 passed`
- [ ] 兩個檔一起跑：`pytest tests/integration/test_ingest_job.py tests/integration/test_ingest_job_pdf.py -q` → `20 passed`
- [ ] 「跳過語意」那顆真的在驗：
      ```bash
      pytest tests/integration/test_ingest_job_pdf.py -k "skipped語意" -v
      ```
      預期 `1 passed`
- [ ] 續跑那顆真的在驗：
      ```bash
      pytest tests/integration/test_ingest_job_pdf.py -k "續跑" -v
      ```
      預期 `1 passed`
- [ ] 「寫檔失敗＝跳過該頁」的本計畫裁決（design5 沒明寫的那條）有測試釘著：
      ```bash
      pytest tests/integration/test_ingest_job_pdf.py -k "寫檔失敗" -v
      ```
      預期 `1 passed`
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ Phase 59 結束時 ＋ **9**
- [ ] 零外部依賴：`OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q` 顆數相同
- [ ] 端點數仍是 20：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `20`

---

## 7. 常見陷阱

1. **`enumerate` 的 `start` 忘了加，頁碼全部錯一位。**
   續跑時如果寫成 `enumerate(page_images[already_done:], start=1)`，
   第 3 頁的 log 會說「第 1 頁」，而 `store.update(pages_done=page_number)` 會把 `pages_done` **倒退**成 1。
   **症狀**：重送兩次之後，同一頁被做了三次，照片數量比頁數還多。
   **正解**：`start=already_done + 1`。切片與起始頁碼要一起算，兩個數字必須一致。

2. **把 `pages_done` 與 `photo_ids` 分兩次 `store.update` 寫。**
   兩次寫之間被殺 → 重送時 `pages_done` 已經前進、但 `photo_ids` 少一個 → 那一頁的照片變成「沒人認領」，
   最後結算時 `pages_done − len(photo_ids)` 會多算一頁跳過。更糟的情況是反過來寫（先 photo_ids 後 pages_done），
   重送會把那一頁**再做一次**。
   **正解**：一次 `store.update(job_id, pages_done=…, photo_ids=…)` 寫完。
   （同一個縫的殘餘：每頁「INSERT 成功了、但這次 `store.update` 還沒寫進去」的一瞬間被殺，
   重送仍會把那一頁再插一次——這與單圖相同，是 phase-59 §5.2 已記錄的 side project 取捨；
   能做的就是讓 INSERT 與 update 緊貼、中間不插任何其他動作，本文件的程式碼已經如此。）

3. **`store.update(photo_ids=photo_ids)` 直接傳同一個 list 物件。**
   `InMemoryJobStore` 是行程內的 dict，直接存進去的話，之後 `photo_ids.append(...)`
   會連 store 裡那一份一起改掉——測試看起來會綠，但 Redis 版（Phase 65）不會有這種「順便就改到了」的效果。
   **症狀**：改成 Redis 之後，`photo_ids` 少了最後幾筆，重送重插照片。
   **正解**：`photo_ids=list(photo_ids)` 傳副本。本文件的程式碼已經這樣寫，維持它。

4. **以為「跳過的頁不算 `pages_done`」。**
   design5 §4.3 白紙黑字寫「`pages_done`：PDF 已處理頁數（**含跳過**）」。
   只算成功的頁的話，重送會把跳過的那些頁**再看一次 3 次**——每頁 3〜5 分鐘，
   而且結果注定一樣（同一張圖、同一個模型）。
   **正解**：成功或跳過，一律 `pages_done = page_number`。

5. **拆頁失敗時忘了刪 staging。**
   `_fail()` 已經包含 `remove_staging`，所以只要走 `_fail()` 就沒事。
   但如果有人「順手」在 `except PdfUnreadableError` 裡直接寫 `store.update(status="failed")` 而不走 `_fail()`，
   壞掉的 PDF 就會永遠留在 `data/staging/`，等 24 小時掃把來收。
   **正解**：所有最終失敗一律走 `_fail()`，不要自己拼。

6. **拿 `test_ai_timing_log.py` 或 `test_pdf_upload.py` 的 `分頁VLM` 來 import 用。**
   那兩份的假件是「第幾次呼叫＝第幾頁」，因為舊流程**沒有重試**。
   本 phase 有重試，同一頁會被問 3 次，用舊假件會算成「第 1、2、3 頁」。
   **症狀**：明明只設定第 1 頁看得懂，結果三頁全部入庫，或是次數對不上。
   **正解**：用本文件步驟 1 裡自己數頁的那一份（`目前頁` ＋ `這一頁問過幾次`）。

7. **一頁失敗就整份標 failed。**
   那是 design5 §1.2 明確否決的行為。使用者掃了一份 10 頁的資料，其中一頁是空白紙，
   結果 10 頁全部沒入庫——那比現在的同步流程還糟（現在至少會 `skipped_pages` 回報）。
   **正解**：只有 `photo_ids` **完全是空的**才 `_fail()`。

8. **在 `_run_pdf_job` 裡自己寫一份 3 次重試迴圈。**
   `_understand_and_embed()` 已經做完這件事了（Phase 59 寫的），而且它同時負責更新
   `status`／`attempt`。自己再寫一份會導致「單圖與 PDF 的重試行為慢慢分岔」。
   **正解**：直接呼叫 `_understand_and_embed(...)`，只把 `content_type` 換成 `PDF_PAGE_CONTENT_TYPE`。

9. **忘了 PDF 的每一頁存成 `image/png`。**
   `storage_service.EXTENSIONS` 只認得 `image/jpeg` 與 `image/png`；傳 `application/pdf` 進去會直接 `KeyError`。
   **症狀**：`_insert_photo_with_files` 丟 `KeyError: 'application/pdf'`，那一頁被當成寫檔失敗跳過，
   而且**每一頁**都會這樣 → 整份失敗，錯誤訊息卻寫「AI 都看不懂」，完全誤導。
   **正解**：迴圈裡一律傳 `PDF_PAGE_CONTENT_TYPE`（＝`"image/png"`），只有讀／刪 staging 才用 `job["content_type"]`。

10. **測試裡用 `make_pdf_bytes(pages=0)` 想做「零頁 PDF」。**
    `make_pdf_bytes` 的實作是 `first, *rest = [...]`，空清單會直接丟 `ValueError`——
    Pillow 根本寫不出零頁的 PDF 檔，所以這個假件做不出那種輸入。
    零頁的擋法在 `pdf_service.render_pages` 的 `if len(document) == 0` 那兩行
    （丟的是**同一個** `PdfUnreadableError`；注意 Phase 28 的單元測試只驗了壞檔那一半，
    零頁那一半沒有專屬測試——正因為做不出輸入），
    整合層用 `b"not a pdf"` 走同一條 `PdfUnreadableError` 就夠了。

11. **`db` 沒起來就跑 pytest。**
    這 9 顆會全紅在連線錯誤，看起來像 PDF 邏輯寫壞了。先 `docker compose ps` 確認 `db` 是 `Up (healthy)`。

---

## 8. 完成後的專案狀態

`app/services/ingest_job.py` 現在**兩條路都通了**：JPEG／PNG 走 `_run_image_job`、PDF 走 `_run_pdf_job`，
兩者共用同一個 3 次重試迴圈（`_understand_and_embed`）與同一套寫入／清理（`_insert_photo_with_files`）。

PDF 的三條規則已經被 9 顆測試釘死：
**一個任務處理整份檔**（不拆成多個任務）、**每一頁各自 3 次**（重試單位是頁不是檔）、
**至少一頁成功就算成功**（0 頁成功或拆不開才整筆失敗）。
崩潰重送會從 `pages_done` 的下一頁接著跑，已成功的頁不會被重看、更不會被重插。

`POST /photos` 仍然是同步的 201——**對外行為到現在為止一個字都沒變**。

接下來 **Phase 61** 讓 worker 在 INSERT 時把實體與待辦的建議也一併寫進 `photo` 列
（否則上傳改 202 之後，待辦彈窗會永遠沒有入口），之後 **Phase 62** 才真的把 `POST /photos` 改成 202。

測試累計 ＝ Phase 59 結束時 ＋ **9**。
