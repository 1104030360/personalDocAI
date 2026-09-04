"""PDF 走雲端路的整合測試（design6 D7／D17、design5 D11／D12；Phase 81）。

與 test_gated_ingest.py 同一套玩法：**不打 HTTP**，直接呼叫 run_gated_ingest_job()。
PDF 的位元組用 Phase 28 就有的 tests/fakes.make_pdf_bytes(pages=N) 現產。

⚠ 這裡的「第幾頁」一律 **1 起算**（與既有 skipped_pages 的頁碼慣例相同）。
   程式裡的 pages_done 是「已處理幾頁」，所以做完第 2 頁時 pages_done == 2。

本檔的三個小工具（WorkerMailbox／cloud_route／RememberDeletedStore）與
test_gated_ingest.py 的同名工具長得幾乎一樣，但**各留一份**：
跨測試檔 import 假件會把兩份測試綁在一起，那邊改一下這邊就跟著紅
（本專案既有的 分頁VLM 也是這樣各留一份）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.repositories import photo_repository
from app.services import (
    cloud_ingest,
    gated_ingest,
    ingest_job,
    pdf_service,
    staging_service,
    storage_service,
)
from app.services.ingest_job_store import InMemoryJobStore
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    fake_worker_process_one,
    make_pdf_bytes,
)

NOW = FixedClock(datetime(2026, 8, 18, 10, 0))

RECEIPT_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class RememberDeletedStore(InMemoryJobStore):
    """成功時 job 會被刪掉，但測試還想看「刪掉之前 pages_done／photo_ids 是什麼」。"""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


class WorkerMailbox(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了。

    understanding 直接往下傳給假工人，所以可以給「逐頁的清單」
    （例如 [RECEIPT_UNDERSTANDING, None] ＝ 第 1 頁看得懂、第 2 頁看不懂）。
    """

    def __init__(self, understanding=None, *, worker_on_duty: bool = True) -> None:
        super().__init__()
        self.understanding = understanding
        self.worker_on_duty = worker_on_duty
        self.worker_runs = 0

    def receive_result(self, wait_seconds: int):
        if self.worker_on_duty and self.jobs:
            fake_worker_process_one(self, self.understanding)
            self.worker_runs += 1
        return super().receive_result(wait_seconds)


def create_pdf_job(
    store: InMemoryJobStore,
    *,
    job_id: str = "pdf-1",
    pages: int = 2,
    data: bytes | None = None,
) -> str:
    """模擬 HTTP 端點會做的兩件事：落 staging ＋ 建 job。"""
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


def inbox_id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def cloud_route(mailbox, *, running: bool = True, timeout_seconds: int = 5):
    return cloud_ingest.CloudRoute(mailbox, FakeProbe(running), timeout_seconds=timeout_seconds)


def run(job_id: str, *, store, gate, cloud, vlm=None, embeddings=None) -> None:
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=vlm if vlm is not None else FakeVLM(RECEIPT_UNDERSTANDING),
        embeddings=embeddings if embeddings is not None else FakeEmbeddings(),
        now=NOW,
        gate=gate,
        cloud=cloud,
    )


def test_兩頁都成功_入庫兩列_job被刪_S3清空():
    """PDF 的雲端路走順的樣子：一份兩頁的 PDF ＝ 兩列照片，全部進收件箱。"""
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 2
    assert len(photo_repository.list_photos_in_folder(inbox_id())) == 2
    last_job = store.deleted[job_id]
    assert last_job["page_count"] == 2
    assert last_job["pages_done"] == 2
    assert len(last_job["photo_ids"]) == 2
    assert last_job["route"] == "cloud"
    assert store.get(job_id) is None, "成功＝job 被刪掉"
    assert mailbox.objects == {}, "S3 要清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_第二頁看不懂_只入庫一列_跳過一頁():
    """design5 D12（未推翻）：某一頁不成立就跳過它，其他頁照樣入庫、整筆仍算成功。

    「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox([RECEIPT_UNDERSTANDING, None])  # 逐頁指定：第 2 頁看不懂

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 1
    last_job = store.deleted[job_id]
    assert last_job["pages_done"] == 2, "跳過的頁也要算進 pages_done"
    assert len(last_job["photo_ids"]) == 1
    assert store.get(job_id) is None, "至少一頁成功就算整筆成功"
    assert mailbox.objects == {}


def test_pages是空清單_job標failed且錯誤是PDF讀不開():
    """工人回報「這份 PDF 拆不開」（pages 是空清單，總覽 §2.4.3）。

    使用者看到的訊息要與本機路**一字不差**——他不知道有雲端這回事。
    """
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, data=b"this-is-not-a-pdf")
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_UNREADABLE
    assert mailbox.objects == {}, "失敗也要把 S3 清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_全部頁都失敗_job標failed():
    """每一頁工人都看不懂（每頁各試了 3 次）＝ 0 頁成功 ＝ 整筆失敗（design5 D12）。"""
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox(None)  # 每一頁都看不懂

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_ALL_PAGES_FAILED
    assert job["pages_done"] == 2, "兩頁都處理過了（只是都跳過）"
    assert mailbox.objects == {}


def test_崩潰重送從pages_done續跑不重插():
    """design6 D17 ＋ design5 §4.4：從 pages_done 的**下一頁**接著跑。

    重現方式：手動做出「上一趟已經做完第 1 頁、而且已經送去雲端」的狀態
    （pages_done=1、photo_ids 帶著那一頁的 id、route=cloud），
    再把工人算好的結果放進 S3，然後重跑一次。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=3)

    # 第 1 頁在上一趟已經入庫了。直接用 repository 插一列就好——本顆要的是那個**狀態**
    first_page = photo_repository.insert_photo(
        text=RECEIPT_UNDERSTANDING.text,
        category="未分類",
        location=RECEIPT_UNDERSTANDING.location,
        items=RECEIPT_UNDERSTANDING.items,
        content_time=None,
        embedding=FakeEmbeddings().embed_query(RECEIPT_UNDERSTANDING.text),
        uploaded_at=NOW(),
    )
    store.update(job_id, page_count=3, pages_done=1, photo_ids=[first_page["id"]], route="cloud")
    assert photo_repository.count_photos() == 1

    # 工人上一趟算好的結果還在 S3（三頁都看懂了）。這裡直接借假工人把 result.json 寫好：
    # 放一份真的 input.pdf ＋ 發一則 jobs 訊息 → 假工人做一次 → 再把 results 訊息清掉
    # （這一趟不是靠 results 訊息叫醒的，是崩潰重送 → 靠 fetch_result 直接去 S3 拿）。
    # ⚠ input.pdf 一定要是**真的 PDF**：假工人用產品碼的 render_pages() 去數頁數，
    #   放 b"x" 的話它會判成「拆不開」，這一顆就會紅在完全無關的地方。
    mailbox = FakeMailbox()
    input_key = mailbox.input_key(job_id, "application/pdf")
    mailbox.put_object(input_key, make_pdf_bytes(pages=3), "application/pdf")
    mailbox.send_job(job_id, input_key)
    fake_worker_process_one(
        mailbox, [RECEIPT_UNDERSTANDING, RECEIPT_UNDERSTANDING, RECEIPT_UNDERSTANDING]
    )
    mailbox.results.clear()

    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換答案也不該被問到
    run(job_id, store=store, gate=gate, cloud=cloud_route(mailbox))

    assert gate.calls == 0, "route 已經有值，不可以再問一次閘門"
    assert photo_repository.count_photos() == 3, "第 1 頁不可以被插第二次"
    last_job = store.deleted[job_id]
    assert last_job["pages_done"] == 3
    assert last_job["photo_ids"][0] == first_page["id"], "原本那一頁的 id 要留著"
    assert len(last_job["photo_ids"]) == 3


def test_PDF判定敏感時零submit走本機():
    """design6 D3／§9 必釘第 1 條：PDF 走的是同一個岔路口，沒有例外。

    ⚠ 真閘門 `VlmGate` 看的是**圖**不是檔名（2026-09-01 改判；design6 D4、總覽 §10.1 f）——
      PDF 的話它會渲染第一頁再問模型。本檔不測那一段（那是 test_privacy_gate_unit.py 的事），
      直接用 `FakePrivacyGate(Verdict.SENSITIVE)` 指定 verdict，
      驗的是「敏感的 PDF 一個位元組都不會出門」。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = FakeMailbox()

    run(job_id, store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=cloud_route(mailbox))

    assert mailbox.put_calls == 0, "敏感檔的 PutObject 次數必須是 0"
    assert mailbox.send_job_calls == 0
    assert photo_repository.count_photos() == 2, "照樣走本機入庫（兩頁）"
    assert store.deleted[job_id]["privacy"] == "SENSITIVE"
    assert store.deleted[job_id]["route"] == "local"


def test_submit的input鍵名是input點pdf():
    """design6 §2.2：`documents/{job_id}/input.pdf`。

    工人是靠副檔名推 content_type 的（總覽 §2.6 第 4 條），推錯就會拿去當圖片看。
    ★ 用 `mailbox.calls`（呼叫流水帳）驗：`objects` 在成功之後會被 cleanup 清空，
      流水帳則會留著整趟的歷史。
    """
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, pages=1)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert f"put_object documents/{job_id}/input.pdf" in mailbox.calls
    assert f"put_object documents/{job_id}/context.json" in mailbox.calls
    assert photo_repository.count_photos() == 1


# ---------- 守門測試（2026-09-02 fix wave R11）----------
# 上面七顆都用「照順序產生 pages」的假工人，所以分不出「依 page 欄位配對」與
# 「依陣列位置配對」——把 gated_ingest 的 page_results.get(page_number) 改成
# pages[page_number - 1] 仍然全綠，而那正是計畫檔 §7 陷阱 1 點名的安靜壞法。
# 下面兩顆把「順序不保證」真的演出來：一顆反序、一顆少一頁。

PAGE1_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="第一頁：在 Target 購買可樂的收據",
    category="收據",
    location="Target",
    items=["可樂"],
    content_time="2026-08-10",
)

PAGE2_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="第二頁：在 Target 購買洋芋片的收據",
    category="收據",
    location="Target",
    items=["洋芋片"],
    content_time="2026-08-10",
)


def original_bytes(photo_id: int) -> bytes:
    """把那一列的原圖從硬碟讀回來。

    insert_photo_with_files 是把「該頁渲染出來的 PNG 位元組」原樣落地的，
    所以「哪一頁的圖被存成哪一列」可以用位元組相等直接驗——比看寬高可靠得多。
    """
    row = photo_repository.fetch_photo(photo_id)
    return storage_service.absolute_path(row["original_path"]).read_bytes()


class ReversedWorkerMailbox(WorkerMailbox):
    """工人把 pages **反序**寫回來（SQS 不保證順序；工人日後並行看圖也會這樣）。

    依陣列位置配對的實作會把第 1 頁的圖配上第 2 頁的文字——而且是**安靜地**配錯。
    """

    def receive_result(self, wait_seconds: int):
        if self.worker_on_duty and self.jobs:
            result = fake_worker_process_one(self, self.understanding)
            result["pages"].reverse()
            self.objects[self.result_key(result["job_id"])] = json.dumps(
                result, ensure_ascii=False, default=str
            ).encode("utf-8")
            self.worker_runs += 1
        # 刻意跳過 WorkerMailbox.receive_result（它會再跑一次假工人），直接叫基底 FakeMailbox 的版本
        return FakeMailbox.receive_result(self, wait_seconds)


class PartialWorkerMailbox(WorkerMailbox):
    """工人只回了第 2 頁的結果（第 1 頁那一筆根本沒寫進 pages）。

    演的是「工人回的頁數與本機拆出的頁數對不上」——本機要大聲 log 一行，
    並且把沒有結果的那一頁當成跳頁，其他頁照樣入庫。
    """

    def receive_result(self, wait_seconds: int):
        if self.worker_on_duty and self.jobs:
            result = fake_worker_process_one(self, self.understanding)
            result["pages"] = [page for page in result["pages"] if page["page"] == 2]
            self.objects[self.result_key(result["job_id"])] = json.dumps(
                result, ensure_ascii=False, default=str
            ).encode("utf-8")
            self.worker_runs += 1
        # 刻意跳過 WorkerMailbox.receive_result（它會再跑一次假工人），直接叫基底 FakeMailbox 的版本
        return FakeMailbox.receive_result(self, wait_seconds)


def test_工人回的pages反序_仍依page欄位配對():
    """計畫檔 §7 陷阱 1：配對用的是 `page` 這個欄位，不是陣列位置。

    兩頁的文字刻意不一樣，原圖也不一樣，所以配錯的話「第一頁的文字」會配到
    第 2 頁的 PNG——用位元組比對抓得出來。
    """
    store = RememberDeletedStore()
    pdf_bytes = make_pdf_bytes(pages=2)
    job_id = create_pdf_job(store, data=pdf_bytes)
    expected_pages = pdf_service.render_pages(pdf_bytes)
    mailbox = ReversedWorkerMailbox([PAGE1_UNDERSTANDING, PAGE2_UNDERSTANDING])

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 2
    rows = photo_repository.list_photos_in_folder(inbox_id())
    assert len(rows) == 2
    first = next(row for row in rows if row["text"].startswith("第一頁"))
    second = next(row for row in rows if row["text"].startswith("第二頁"))

    assert original_bytes(first["id"]) == expected_pages[0], "第一頁的文字要配第一頁的圖"
    assert original_bytes(second["id"]) == expected_pages[1], "第二頁的文字要配第二頁的圖"


def test_工人只回第二頁_第一頁跳過且原圖是第二頁(caplog):
    """工人回的頁數與本機拆出的頁數對不上：對不上的頁當「沒有結果」跳過，並留一行 warning。

    ★ 這一顆同時守住兩條零覆蓋的分支：_store_pdf_result 的「頁數對不上」warning，
      以及 _store_pdf_page 的 `page_result is None` → 跳過（前七顆走到的都是「有結果但看不懂」）。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    pdf_bytes = make_pdf_bytes(pages=2)
    job_id = create_pdf_job(store, data=pdf_bytes)
    expected_pages = pdf_service.render_pages(pdf_bytes)
    mailbox = PartialWorkerMailbox([PAGE1_UNDERSTANDING, PAGE2_UNDERSTANDING])

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 1
    rows = photo_repository.list_photos_in_folder(inbox_id())
    assert rows[0]["text"].startswith("第二頁"), "留下來的是工人真的有回結果的那一頁"
    assert original_bytes(rows[0]["id"]) == expected_pages[1], "而且原圖是第 2 頁的 PNG"

    last_job = store.deleted[job_id]
    assert last_job["pages_done"] == 2, "跳過的頁也要算進 pages_done"
    assert len(last_job["photo_ids"]) == 1
    assert any("對不上的頁會被跳過" in message for message in caplog.messages)
    assert any("第 1 頁雲端看不懂或沒有結果，跳過這一頁" in message for message in caplog.messages)
    assert mailbox.objects == {}, "S3 要清乾淨"
