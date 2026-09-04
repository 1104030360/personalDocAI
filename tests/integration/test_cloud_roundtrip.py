"""端到端：本機送出 → 工人處理 → 本機收回入庫（Phase 87；design6 §9 必釘第 3 條）。

⚠ Phase 79〜81 的同款測試裡，「另一頭」是 tests/fakes.py 的 fake_worker_process_one。
   **從本 phase 起它不再是假的**：處理訊息的是真正的
   app/workers/cloud_worker.process_job_message()，
   假的只剩「信箱」（FakeMailbox 同時扮演 S3 ＋ 兩條佇列）與「看圖」（FakeVLM）。
   換句話說，這兩顆測試涵蓋的程式碼路徑，與 EC2 上真的跑起來時**完全相同**，
   差別只在 AWS SDK 那一層被換掉了。

【怎麼安排先後】
run_gated_ingest_job() 是一條龍：送出 → 長輪詢等 results → 用結果落庫。
測試只有一條執行緒，如果不做任何事，wait_result() 會空等到逾時然後 fallback，
根本走不到雲端成功那條路。

做法**沿用既有慣例**（tests/integration/test_gated_ingest.py 的 WorkerMailbox）：
在本檔自己做一顆 FakeMailbox 子類，覆寫 receive_result()——本機每次去收結果的
那一刻，就是「另一台機器上的工人」動手的那一刻。這樣：
  - submit() 是真的（真的 PutObject 兩個物件、真的 SendMessage jobs）
  - process_job_message() 是**真的**（本 phase 的主角）
  - wait_result() 是真的（真的 ReceiveMessage results、真的 GetObject result.json）
  只有「工人在哪一個時間點動手」是我們安排的——而那件事在正式環境本來就是
  另一台機器上非同步發生的，測試沒有辦法、也不需要重現它的時序。

（不用 monkeypatch CloudRoute.wait_result 的理由：那會把產品碼的方法換掉，
 讀測試的人得先確認「換掉之後還有沒有在測原本那支」。子類只多接一個 hook，
 產品碼一個字都沒被動到，而且與既有那份測試長得一樣。）

（也不在 tests/fakes.py 上開 on_send_job 之類的回呼：那會為了這兩顆測試在共用假件上
 多開一個只有這裡用得到的鉤子——本專案的慣例是「跨測試檔不共用只有一處要用的假件」。）
"""

from __future__ import annotations

from datetime import datetime

from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, staging_service
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.conftest import 目前的任務清單
from tests.fakes import (
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    make_pdf_bytes,
    make_png_bytes,
)

RECEIPT_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)

NOW = FixedClock(datetime(2026, 8, 18, 10, 0))


class WorkerMailbox(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了——而且是**真的**工人。

    寫法沿用 tests/integration/test_gated_ingest.py 的同名類別（那邊接的是
    fake_worker_process_one），差別只有一個：這裡呼叫的是 Phase 87 的
    cloud_worker.process_job_message()。

    while 迴圈是為了 PDF：一份 PDF 只有一則 jobs 訊息，但把佇列排空的寫法
    對「將來一次送多則」也不會壞掉，而且空佇列時 receive_job 立刻回 None。
    """

    def __init__(self, vlm) -> None:
        super().__init__()
        self.vlm = vlm
        self.worker_runs = 0

    def receive_result(self, wait_seconds: int):
        message = self.receive_job(0)
        while message is not None:
            cloud_worker.process_job_message(self, message, self.vlm)
            self.worker_runs += 1
            message = self.receive_job(0)
        return super().receive_result(wait_seconds)


def upload_and_get_job_id(client, *, filename: str, payload: bytes, content_type: str) -> str:
    """走真的 HTTP 端點把檔案收下來（202），回傳 job_id。

    刻意不直接呼叫 staging_service／JobStore：入列的順序（先落 staging、
    再建 job、再派工）本身就是增量五的契約，端到端測試要連它一起走一遍。
    """
    response = client.post("/photos", files={"file": (filename, payload, content_type)})
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def inbox_photos() -> list[dict]:
    inbox = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    return photo_repository.list_photos_in_folder(inbox["id"])


def test_單圖端到端_本機送出_假工人處理_本機入庫(client):
    worker_vlm = FakeVLM(RECEIPT_UNDERSTANDING)
    local_vlm = FakeVLM(RECEIPT_UNDERSTANDING)  # 雲端路走通的話，這一顆**一次都不該被呼叫**
    mailbox = WorkerMailbox(worker_vlm)

    job_id = upload_and_get_job_id(
        client, filename="receipt-2026.png", payload=make_png_bytes(), content_type="image/png"
    )

    gated_ingest.run_gated_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=local_vlm,
        embeddings=FakeEmbeddings(),
        now=NOW,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_ingest.CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5),
    )

    # ① 工人看了一次圖；本機一次都沒看（雲端路不重看圖，D13 只把 embedding 留在本機）
    assert mailbox.worker_runs == 1
    assert worker_vlm.calls == 1
    assert local_vlm.calls == 0

    # ② context.json 真的把本機資料庫裡的資料夾清單送到了工人手上
    #    （總覽 §10 追認項 a 的靠山：沒有它，工人組出來的 prompt 會少掉三段）
    assert len(worker_vlm.last_folders) == 6, "reset_tables 種了六筆資料夾，六筆都要送過去"
    assert "收據" in [folder["name"] for folder in worker_vlm.last_folders]
    assert worker_vlm.last_entities == []
    assert worker_vlm.last_corrections == []

    # ③ 照片真的進了收件箱，內容是工人看出來的那一份
    photos = inbox_photos()
    assert len(photos) == 1
    assert photos[0]["text"] == RECEIPT_UNDERSTANDING.text

    # ④ 寄物櫃與兩條佇列都清乾淨了（input／context／result 三個物件都被刪）
    assert mailbox.objects == {}
    assert mailbox.jobs == []
    assert mailbox.results == []

    # ⑤ staging 刪了、job 也刪了（成功＝job 消失，與增量五同語意）
    assert not staging_service.staging_path(job_id, "image/png").exists()
    assert 目前的任務清單().get(job_id) is None


def test_PDF端到端_兩頁都回來_入庫兩列(client):
    worker_vlm = FakeVLM(RECEIPT_UNDERSTANDING)
    local_vlm = FakeVLM(RECEIPT_UNDERSTANDING)  # 雲端路走通的話，這一顆**一次都不該被呼叫**
    mailbox = WorkerMailbox(worker_vlm)

    job_id = upload_and_get_job_id(
        client,
        filename="menu-2026.pdf",
        payload=make_pdf_bytes(pages=2),
        content_type="application/pdf",
    )

    gated_ingest.run_gated_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=local_vlm,
        embeddings=FakeEmbeddings(),
        now=NOW,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_ingest.CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5),
    )

    # 工人逐頁看：兩頁＝兩次呼叫（拆頁在工人那邊做，存檔用的 PNG 由本機自己再拆一次）
    assert worker_vlm.calls == 2
    # 與單圖那一顆對稱：雲端路成功時本機**一頁都不重看**（D13 只把 embedding 留在本機）。
    # 沒有這一條的話，「PDF 悄悄走了 fallback、本機自己看完兩頁」也會讓上面那些斷言全綠
    # ——差別只有帳單與那 2〜5 分鐘，測試看不出來。
    assert local_vlm.calls == 0
    assert len(inbox_photos()) == 2
    assert mailbox.objects == {}
    assert not staging_service.staging_path(job_id, "application/pdf").exists()
    assert 目前的任務清單().get(job_id) is None
