"""隱私閘門接線之後的整合測試（design6 §2、§2.1；Phase 78 建，79／80 會追加）。

★ 本檔**不打 HTTP**：直接呼叫 run_gated_ingest_job()——與 test_ingest_job.py 同一套玩法
  （design5 D15 的延伸：任務本體是一支函式，測試自己扮演 worker）。

conftest 的五道 autouse 安全網照樣生效（尤其第一道會清空測試庫、第三道把
data/ 指到暫存目錄），但本檔的六個依賴一律**當參數傳**，不靠 dependency_overrides：

    store       每顆測試自己 new 一個 InMemoryJobStore（天生隔離）
    vlm         FakeVLM（雲端路走不到它，本機路才用得到）
    embeddings  FakeEmbeddings
    now         FixedClock（**callable**，呼叫它才拿到 datetime）
    gate        FakePrivacyGate（Phase 74）
    cloud       FakeCloudRoute（Phase 77）——Phase 79 起改用真的 CloudRoute ＋ FakeMailbox
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.core import config
from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, staging_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeCloudRoute,
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    fake_worker_process_one,
    make_jpeg_bytes,
    make_png_bytes,
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
    """成功時 job 會被刪掉，但測試還想看「刪掉之前 privacy／route 是什麼」。

    只多做一件事：delete() 之前先把那一筆抄一份存進 self.deleted。
    完全只用 JobStore 的公開介面（get／delete）——寫法沿用 test_ingest_job_pdf.py
    的 記得最後一筆的Store 類別（那邊也是為了看「刪掉之前」的樣子）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


class StatusPeekingGate:
    """被問的那一刻，順手記下 job 的 status 是什麼。

    用來釘 design6 D5 的「一進門就標 analyzing」：進度面板上那一列不可以停在
    queued 讓人以為沒動靜（沿用 design5 §4.4，雲端路一樣要遵守）。
    """

    def __init__(self, store, job_id: str, verdict: Verdict = Verdict.SENSITIVE) -> None:
        self._store = store
        self._job_id = job_id
        self._verdict = verdict
        self.seen_statuses: list[str] = []

    def classify(self, *, filename: str, content_type: str, load_bytes) -> Verdict:
        job = self._store.get(self._job_id)
        self.seen_statuses.append(job["status"] if job else "沒有這筆")
        return self._verdict


def create_job(
    store: InMemoryJobStore,
    *,
    job_id: str = "job-1",
    filename: str = "a.png",
    content_type: str = "image/png",
) -> str:
    """模擬 HTTP 端點會做的兩件事：落 staging ＋ 建 job（與 test_ingest_job.py 相同）。

    位元組要跟 content_type 對得上：本機路會真的用 Pillow 打開它做縮圖
    （假位元組會炸 UnidentifiedImageError，Phase 19 起的規矩）。

    ★ `filename` 純粹是**記帳**：本檔每一顆測試的 verdict 都由測試自己傳進來的
      `FakePrivacyGate(...)` 決定，跟檔名沒有關係——真閘門 `VlmGate` 也**不看檔名**
      （總覽 §10.1 f）。取名叫「身分證.png」「receipt.png」只是讓測試讀起來像那麼一回事。
    """
    file_bytes = make_jpeg_bytes() if content_type == "image/jpeg" else make_png_bytes()
    staging_service.save_staging(job_id, content_type, file_bytes)
    store.create(
        job_id=job_id,
        filename=filename,
        content_type=content_type,
        ai_backend="local",
        source="upload",
    )
    return job_id


def inbox_id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def run(job_id: str, *, store, gate, cloud, vlm=None, embeddings=None) -> None:
    """把六個零件組好、呼叫本 phase 的主角。"""
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=vlm if vlm is not None else FakeVLM(RECEIPT_UNDERSTANDING),
        embeddings=embeddings if embeddings is not None else FakeEmbeddings(),
        now=NOW,
        gate=gate,
        cloud=cloud,
    )


# ---------------------- ① 敏感與不確定：一個位元組都不出門 ----------------------


def test_敏感照片走本機_零submit_job記下privacy與route(caplog):
    """design6 §8 錯誤表第 1 列、§9 必釘第 1 條。

    ★ cloud 刻意用「遠端**開著**」的假件：這樣「零 submit」就只可能是閘門擋下來的，
      不會被「反正遠端也沒開」蒙混過去。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store, filename="身分證.png")
    gate = FakePrivacyGate(Verdict.SENSITIVE)
    mailbox = FakeMailbox()
    probe = FakeProbe(True)  # 遠端「開著」：零 Put 就只可能是閘門擋的，不是遠端關著
    route = cloud_ingest.CloudRoute(mailbox, probe, timeout_seconds=5)

    run(job_id, store=store, gate=gate, cloud=route)

    # 一個位元組都沒有出門
    assert mailbox.put_calls == 0, "design6 §9 必釘第 1 條：敏感檔的 PutObject 次數必須是 0"
    assert mailbox.send_job_calls == 0
    assert mailbox.objects == {}
    assert probe.calls == 0, "敏感就該直接走本機，連問都不必問遠端"
    # 照片照樣入收件箱（使用者完全無感）
    assert photo_repository.count_photos() == 1
    assert len(photo_repository.list_photos_in_folder(inbox_id())) == 1
    # 兩個新欄位都記下來了
    last_job = store.deleted[job_id]
    assert last_job["privacy"] == "SENSITIVE"
    assert last_job["route"] == "local"
    assert gate.calls == 1, "閘門只問一次（一次分類要便宜，design6 D4）"
    assert any("route=local verdict=SENSITIVE" in m for m in caplog.messages), caplog.messages


def test_不確定照片走本機_零submit():
    """design6 D3：**不確定一律當敏感辦**。§9 必釘第 2 條。

    `UNCERTAIN` 在真實世界怎麼來的：模型說「不敏感但我沒把握」、模型丟例外、
    staging 檔讀不到、圖解不開、PDF 拆不開——全部都是（Phase 74／75 的契約）。
    判不出來的代價只能是「沒卸到雲端」，絕不可以是「敏感檔外流」。
    """
    store = RememberDeletedStore()
    job_id = create_job(store, filename="camera.jpg", content_type="image/jpeg")
    gate = FakePrivacyGate(Verdict.UNCERTAIN)
    mailbox = FakeMailbox()
    route = cloud_route(mailbox)

    run(job_id, store=store, gate=gate, cloud=route)

    assert mailbox.put_calls == 0
    assert photo_repository.count_photos() == 1
    last_job = store.deleted[job_id]
    assert last_job["privacy"] == "UNCERTAIN"
    assert last_job["route"] == "local"


# ---------------------- ② 非敏感但遠端不可用：fallback ----------------------


def test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable(caplog):
    """design6 §8 錯誤表第 2 列、§9 必釘第 4 條、§0 禁止第 6 條。

    這是本增量**最重要**的一顆：EC2 平常是 Stop 的，所以這條路才是常態。
    使用者看到的東西必須與增量五**逐字相同**——照片照樣入收件箱，
    唯一的差別是 worker 的 log 多一行。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store, filename="receipt.png")
    gate = FakePrivacyGate(Verdict.NON_SENSITIVE)
    route = FakeCloudRoute(False)  # 遠端關著

    run(job_id, store=store, gate=gate, cloud=route)

    assert route.available_calls == 1, "非敏感才需要問遠端；而且只問一次"
    assert route.submit_calls == 0, "遠端不可用就不可以送出去"
    assert photo_repository.count_photos() == 1, "照片照樣入庫（不准 5xx、不准要人重傳）"
    last_job = store.deleted[job_id]
    assert last_job["privacy"] == "NON_SENSITIVE"
    assert last_job["route"] == "local", (
        "fallback 之後 route 要釘成 local（崩潰重送才不會再送一次）"
    )
    assert any("fallback=local reason=remote_unavailable" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


def test_非敏感但探測丟例外_同樣fallback本機(caplog):
    """design6 §8 錯誤表第 3 列（沒有 AWS 憑證／API 掛了）、§9 必釘第 5 條。

    「問不到答案」與「沒開機」對這個系統來說是同一件事——都走 fallback。
    ⚠ 例外**絕對不可以**往外飛：飛出去的話 Celery 會把整個任務標成失敗，
      使用者就會看到一列莫名其妙的紅字（違反 §0 禁止第 6 條）。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store, filename="menu.png")
    gate = FakePrivacyGate(Verdict.NON_SENSITIVE)
    mailbox = FakeMailbox()
    probe = FakeProbe(RuntimeError("Unable to locate credentials"))
    route = cloud_ingest.CloudRoute(mailbox, probe, timeout_seconds=5)

    run(job_id, store=store, gate=gate, cloud=route)

    assert probe.calls == 1, "非敏感就該真的去問一次遠端（沒問就 fallback 也是錯的）"
    assert mailbox.put_calls == 0
    assert photo_repository.count_photos() == 1
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=remote_unavailable" in m for m in caplog.messages)


def test_雲端路available本身丟例外_閘門層也當作不可用(caplog):
    """`gated_ingest._remote_available` 那一層 try/except 的**專屬**測試（review 裁決 R13）。

    為什麼要單獨一顆：`test_非敏感但探測丟例外_同樣fallback本機` 從 Phase 79 起用的是
    真的 `CloudRoute`，而 `CloudRoute.available()` 自己就會把探測的例外吞掉——
    例外根本飛不到 `_remote_available` 那一層，那段 try/except 整段刪掉也不會有測試變紅。

    但那一層是**刻意的雙保險**（`available()` 的實作是可以被抽換的，例如 Phase 86 之後
    可能換成別的路），而「探測炸掉 ⇒ 整筆任務失敗」是絕對不能發生的事
    （design6 §0 禁止第 6 條）。所以這裡用一顆 `available()` **自己就會丟例外**的假路
    （`FakeCloudRoute`，Phase 77 建、78 原本就這樣測）把那層保險絲釘住。
    """
    caplog.set_level(logging.INFO)
    store = InMemoryJobStore()
    job_id = create_job(store, filename="menu.png")
    route = FakeCloudRoute(RuntimeError("探測炸了"))

    run(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=route)

    assert route.available_calls == 1, "非敏感就該真的問一次"
    assert route.submit_calls == 0, "問不出答案就不可以送出去"
    assert photo_repository.count_photos() == 1, "照片照樣入庫（不准 5xx、不准要人重傳）"
    assert store.get(job_id) is None, "成功＝job 被刪掉（使用者完全無感）"
    assert any("fallback=local reason=remote_unavailable" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


# ---------------------- ③ 崩潰重送與邊界 ----------------------


def test_崩潰重送時route已是local就不再問閘門():
    """design6 §2.1 的禁止：**fallback 時絕不再跑一次 classifier**。

    重現方式：手動把 job 調成「上一趟已經決定走本機」的樣子（route=local），
    再跑一次。閘門必須**一次都沒被呼叫**。

    為什麼這條規則重要：閘門每問一次就是**真的看一次圖**（Phase 75 之後打的是
    本機或 ollama.com 的看圖模型）。每次崩潰重送都重問一次，等於白花一次推論，
    而且答案還可能跟上一趟不一樣（模型不是決定論的）——已經決定的事就別再問。
    """
    store = InMemoryJobStore()
    job_id = create_job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="local")
    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換一個答案，也不該被問到
    route = FakeCloudRoute(True)

    run(job_id, store=store, gate=gate, cloud=route)

    assert gate.calls == 0, "route 已經是 local 了，不可以再問一次閘門"
    assert route.available_calls == 0
    assert photo_repository.count_photos() == 1


def test_job不存在時安靜結束():
    """job 已過期或已被 dismiss：安靜結束，不可以炸掉整個 worker。

    語意與 run_ingest_job 完全相同（那一支也是 log 一行就 return）。
    """
    store = InMemoryJobStore()

    run(
        "根本沒有這筆", store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=FakeCloudRoute()
    )

    assert photo_repository.count_photos() == 0


def test_一進門status就變analyzing():
    """design5 §4.4 的規則，雲端路一樣要遵守：崩潰重送時面板不可以停在 queued。

    ★ 順序很重要：**先** update(status="analyzing")、**才**問閘門。
      反過來寫的話，閘門看圖的那幾十秒裡（本機推估 20〜60 秒），面板上那一列
      會一直是「排隊中」，使用者會以為系統當掉了。
    """
    store = InMemoryJobStore()
    job_id = create_job(store)
    gate = StatusPeekingGate(store, job_id)

    run(job_id, store=store, gate=gate, cloud=FakeCloudRoute())

    assert gate.seen_statuses == ["analyzing"], (
        f"問閘門的時候狀態應該已經是 analyzing：{gate.seen_statuses}"
    )


def test_閘門收到的檔名就是job裡的filename():
    """這一顆測的是**傳遞**，不是判斷。

    真閘門 `VlmGate` **不看檔名**（總覽 §10.1 f、Phase 74 的 `test_檔名完全不影響判斷`），
    所以傳錯檔名不會改變 verdict——但 `filename` 仍在 `classify()` 的簽章裡：
    假件靠它記帳、log 與日後除錯靠它認人。傳成 `job_id` 那種東西不會壞掉、
    也不會有錯誤訊息，只會讓所有紀錄都變成一串看不懂的號碼，所以釘一顆守著。
    """
    store = InMemoryJobStore()
    job_id = create_job(store, filename="身分證正面.jpg", content_type="image/jpeg")
    gate = FakePrivacyGate(Verdict.SENSITIVE)

    run(job_id, store=store, gate=gate, cloud=FakeCloudRoute())

    assert gate.last_filename == "身分證正面.jpg"
    assert gate.calls == 1


# ---------------------- ④ 雲端路：非敏感 ＋ 遠端開著（Phase 79）----------------------


class WorkerMailbox(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了。

    真實世界裡工人是另一台機器上的另一支程式，兩邊是**同時**在跑的；
    測試是單執行緒，所以把「工人動一次」掛在「本機每次去收結果」的那一刻——
    這是最貼近真實時序、又完全可預測的做法。

    worker_on_duty=False ＝「另一頭沒有人」（Phase 80 的逾時測試會用到）。
    刻意寫在本檔而不是 tests/fakes.py：只有雲端路的整合測試用得到它，
    沿用本專案「跨測試檔不共用假件」的慣例（那樣會讓兩份測試綁在一起）。
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


class UndeliverableMailbox(FakeMailbox):
    """PutObject 成功、SendMessage 失敗——最容易留下「半套」的那一種壞法。"""

    def send_job(self, job_id: str, s3_key: str) -> None:
        raise RuntimeError("SQS 拒絕了這則訊息")


class BrokenEmbeddings:
    """每次都炸的向量產生器（沿用 test_ingest_job.py 的 壞掉的Embeddings 假件，本檔自己留一份）。"""

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("bge-m3 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("bge-m3 沒有回應")


def cloud_route(mailbox, *, running: bool = True, timeout_seconds: int = 5):
    """真的 CloudRoute ＋ 假信箱 ＋ 假探測。

    Phase 79 起一律這樣測，**不再用 FakeCloudRoute**——假的路只證明得了
    「分支走對了」，證明不了「送出去的東西長什麼樣」（總覽 §2.4.5）。
    """
    return cloud_ingest.CloudRoute(mailbox, FakeProbe(running), timeout_seconds=timeout_seconds)


def test_非敏感且遠端開著_雲端結果回來後本機入庫(caplog):
    """design6 §9 必釘第 3 條、D7 的一整圈。

    走完之後：照片在收件箱、staging 空了、job 被刪掉（＝成功的唯一寫法）。
    ★ 本機**沒有**看過圖：本機那顆 vlm 假件的 calls 必須是 0——看圖是工人做的。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store, filename="receipt.png")
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)
    local_vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    run(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_route(mailbox),
        vlm=local_vlm,
    )

    assert mailbox.send_job_calls == 1
    assert mailbox.worker_runs == 1
    assert local_vlm.calls == 0, "看圖是工人做的，本機不可以再看一次"
    assert photo_repository.count_photos() == 1
    photos = photo_repository.list_photos_in_folder(inbox_id())
    row = photo_repository.fetch_photo(photos[0]["id"])
    assert row["text"] == RECEIPT_UNDERSTANDING.text
    assert row["category"] == "未分類", "一律先進收件箱（雲端路也一樣）"
    assert row["suggested_category"] == "收據", "建議照樣落庫（design5 D16）"
    assert row["original_path"] and row["thumbnail_path"], "原圖與縮圖仍然在本機（D1／D13）"
    assert store.get(job_id) is None, "成功＝job 被刪掉"
    assert store.deleted[job_id]["route"] == "cloud"
    assert not staging_service.staging_path(job_id, "image/png").exists()
    # Phase 78 留下的契約字樣：真機 Demo 2 靠 `route=cloud` 這一行對帳（總覽 §2.5）
    assert len([m for m in caplog.messages if "route=cloud verdict=NON_SENSITIVE" in m]) == 1, (
        f"送出前那一行契約 log 不見了或印了不只一次：{caplog.messages}"
    )
    # 落庫後那一行也是契約字樣：Phase 88（Mac 端到端）與 92（Demo 2）靠
    # `docker compose logs worker | grep 雲端結果已入庫` 對帳——成功的 job 會被刪掉，
    # 所以「照片真的從雲端回來了」在 log 上只剩這一行證據。
    assert len([m for m in caplog.messages if "雲端結果已入庫：photo_id=" in m]) == 1, (
        f"落庫後那一行契約 log 不見了或印了不只一次：{caplog.messages}"
    )


def test_雲端入庫後S3三物件與results訊息都被清掉():
    """D8：S3 是寄物櫃，處理成功就刪；Lifecycle 只是掃把。

    順帶釘住兩件事：
    1. 「results 訊息有被刪掉」——沒刪的話那則訊息會在可見度逾時後重新出現，
       被**下一筆**任務收到（總覽 §8.9 的殘訊息問題）。
    2. **先寫收據、再清 S3**（總覽 §10.2 R、design6 D17）：`photo_ids` 必須在 `cleanup()`
       之前就寫進 store。cleanup 是一次 S3 網路呼叫（S3 不通時 boto3 的重試可拖幾十秒），
       worker 在那段時間被殺的話，沒先寫 photo_ids 的版本會在重送時再 INSERT 一張。
       ★ 併在這一顆裡驗、不另開一顆（顆數不變）：拿 `FakeMailbox.calls` 的長度當時鐘，
         在 store 收到 photo_ids 的那一刻抄下「信箱做到第幾步」，事後檢查那之前沒有 delete_objects。
    """
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)
    mailbox_step_at_photo_ids_write: list[int] = []

    class TimingStore(RememberDeletedStore):
        def update(self, target_job_id, **fields):
            if "photo_ids" in fields:
                mailbox_step_at_photo_ids_write.append(len(mailbox.calls))
            return super().update(target_job_id, **fields)

    store = TimingStore()
    job_id = create_job(store)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert mailbox.objects == {}, f"S3 應該被清空了：{list(mailbox.objects)}"
    assert mailbox.results == [], "results 訊息要被刪掉（不然會變成下一筆的殘訊息）"
    assert mailbox.jobs == [], "jobs 訊息要被工人刪掉"
    # ⚠ 上面兩行**證明不了「刪掉」**：FakeMailbox._receive 在 receive 當下就把訊息從佇列
    #   pop 進 _in_flight 了，所以就算漏掉 delete_*_message，那兩個清單照樣是空的
    #   （真 SQS 的下場才嚴重：可見度逾時之後那則訊息會重新出現，被下一筆任務收到）。
    #   要證明「真的 ack 了」只能看呼叫流水帳（review R13 Finding 1）。
    assert "delete_result_message" in mailbox.calls, (
        f"收下自己的結果之後要把 results 訊息刪掉（總覽 §2.5 第 2 條）：{mailbox.calls}"
    )
    assert "delete_job_message" in mailbox.calls, (
        f"工人處理完要 ack 掉 jobs 訊息（design6 §2.6 第 6 條）：{mailbox.calls}"
    )

    # 先寫收據、再清 S3（第一次寫 photo_ids 的時候，信箱還沒被叫過 delete_objects）
    assert mailbox_step_at_photo_ids_write, "photo_ids 從來沒有寫進 store"
    calls_before_photo_ids = mailbox.calls[: mailbox_step_at_photo_ids_write[0]]
    assert not any(c.startswith("delete_objects") for c in calls_before_photo_ids), (
        f"cleanup 跑在 photo_ids 之前了（總覽 §10.2 R）：{mailbox.calls}"
    )
    assert any(c.startswith("delete_objects") for c in mailbox.calls), "cleanup 真的有跑"


def test_雲端結果說看不懂_job標failed且不留照片():
    """design6 §8 錯誤表第 7 列 ＋ 總覽 §10 追認項 g。

    雲端看圖三次都失敗 ＝ **這一筆失敗**，不是 fallback 本機：
    遠端明明活著，只是 AI 看不懂——本機再看三次多半也一樣，
    而且會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意。
    """
    store = InMemoryJobStore()
    job_id = create_job(store)
    mailbox = WorkerMailbox(None)  # 假工人回「三次都看不懂」
    local_vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    run(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_route(mailbox),
        vlm=local_vlm,
    )

    assert photo_repository.count_photos() == 0, "看不懂就什麼都不存（design5 D10 不變）"
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert "看不懂" in job["error"]
    assert local_vlm.calls == 0, "不可以改用本機再看一次（那不是這一列的規則）"
    assert mailbox.objects == {}, "失敗也要把 S3 清乾淨"
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_本機轉向量三次都失敗_不會再叫工人重看圖():
    """design6 D13：向量在本機算。算不出來是**本機**的問題，重看圖沒有幫助。

    所以重算向量最多 config.VLM_MAX_ATTEMPTS 次，而且**絕不重跑雲端那一圈**
    （worker_runs必須維持 1，送出次數也維持 1）。
    """
    store = InMemoryJobStore()
    job_id = create_job(store)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_route(mailbox),
        embeddings=BrokenEmbeddings(),
    )

    assert mailbox.worker_runs == 1, "不可以為了重算向量再送一次雲端"
    assert mailbox.send_job_calls == 1
    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["attempt"] == config.VLM_MAX_ATTEMPTS, "三次都試過了才放棄"
    assert mailbox.objects == {}


def test_雲端路的計時log裡embed是本機(caplog):
    """design6 D13 的證據：整條雲端路上，本機唯一真的打模型的地方是**轉向量**。

    所以 log 裡應該只有 kind=embed（而且 backend=local），一行 kind=vlm 都沒有
    ——那一次看圖發生在工人身上（它有自己的 log，Phase 87 才會出現）。
    """
    caplog.set_level(logging.INFO)
    store = InMemoryJobStore()
    job_id = create_job(store)

    run(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_route(WorkerMailbox(RECEIPT_UNDERSTANDING)),
    )

    start_lines = [m for m in caplog.messages if m.startswith("AI 開始 kind=")]
    embed_lines = [m for m in start_lines if "kind=embed " in m]
    assert len(embed_lines) == 1, f"應該恰好一次轉向量：{start_lines}"
    assert "backend=local" in embed_lines[0], "向量一律本機（design6 D13）"
    assert [m for m in start_lines if "kind=vlm " in m] == [], "本機不看圖"


def test_submit丟例外時fallback本機而且cleanup被呼叫(caplog):
    """design6 §8 錯誤表第 4 列、§2.1 第 3 條：送出失敗 → fallback，而且**不留半套**。"""
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    mailbox = UndeliverableMailbox()

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert mailbox.put_calls == 2, "兩個物件已經放上去了（context 與 input）"
    assert mailbox.objects == {}, "cleanup 要把半套的東西刪乾淨"
    assert mailbox.delete_calls == 1
    assert photo_repository.count_photos() == 1, "照片照樣入庫（走 fallback）"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=submit_failed" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


# ---------------------- ⑤ 逾時與崩潰重送（Phase 80）----------------------


def advance_clock_each_call(monkeypatch, step_seconds: float = 2.0) -> None:
    """把 cloud_ingest 的兩個時間接縫換掉（與 test_cloud_ingest_unit.py 的同名工具相同）。

    **每問一次時鐘就再過了 step_seconds 秒**；睡覺完全不睡。詳細語意見那一份的 docstring。
    本檔只需要這一支：這裡會走到逾時迴圈的測試要的都是「時間會走」。
    凍結時鐘的 advance_clock_frozen() 本檔用不到，所以不留（Phase 89 的 TTL 測試在單元測試檔）。

    刻意在本檔自己留一份：跨測試檔 import 小工具會把兩份測試綁在一起，
    那邊改一下這邊就跟著紅（本專案既有的 分頁VLM 也是這樣各留一份）。
    """
    clock = {"秒": 0.0}

    def _fake_now() -> float:
        clock["秒"] += step_seconds
        return clock["秒"]

    monkeypatch.setattr(cloud_ingest, "_now", _fake_now)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda sec: None)


def put_result(mailbox: FakeMailbox, job_id: str, understanding) -> None:
    """直接把一份 result.json 放進 S3（模擬「工人上一趟已經做完了」）。

    格式與 tests/fakes.py 的假工人寫出來的**完全一致**（總覽 §2.4.3）。

    ★ 直接塞進 `objects`、**不走 `put_object()`**：那一支會把 `put_calls` 加一，
      而崩潰重送的測試要斷言「本機這一趟一個 Put 都沒有」——工人上一趟放的東西
      不該算在本機頭上。
    """
    result = {
        "job_id": job_id,
        "worker_version": "fake-worker",
        "kind": "image",
        "understood": understanding is not None,
        "attempts": 1,
        "understanding": understanding.model_dump() if understanding is not None else None,
    }
    mailbox.objects[mailbox.result_key(job_id)] = json.dumps(
        result, ensure_ascii=False, default=str
    ).encode("utf-8")


class LedgerStore(RememberDeletedStore):
    """update(photo_ids=…) 時往**信箱的** calls 流水帳記一行。

    「photo_ids 寫進 job」與「delete_objects 清 S3」分別發生在 store 與信箱兩顆假件上，
    各自的計數器比不出先後；把 store 的這一種寫入也記進同一本流水帳，順序才比得出來
    （總覽 §10.2 R 要的就是先後）。其餘行為與 RememberDeletedStore 完全相同。

    ⚠ 本 phase 有兩顆測試用它，而且要驗的順序**方向相反**，別看錯：
      * 雲端路成功落庫（`test_崩潰重送route是cloud而且S3有結果…`）：
        寫 photo_ids **在** 清 S3 **之前**（§10.2 R——收據先寫，cleanup 才是網路呼叫）
      * 逾時 fallback（`test_逾時fallback之前會先清掉S3物件`）：
        清 S3 **在** 寫 photo_ids **之前**（§2.1——先把半套清掉，才退回本機入庫）
      不衝突：兩處的 photo_ids 是**不同人**寫的（前者是雲端路自己，後者是 fallback 的
      run_ingest_job），中間夾的都是同一次 cleanup。
    """

    def __init__(self, mailbox: FakeMailbox) -> None:
        super().__init__()
        self.mailbox = mailbox

    def update(self, job_id: str, **fields):
        if "photo_ids" in fields:
            self.mailbox.calls.append("store.update photo_ids")
        return super().update(job_id, **fields)


def test_逾時沒有結果_fallback本機且log有reason_result_timeout(monkeypatch, caplog):
    """design6 §8 錯誤表第 5 列、D10 的第 4 種「遠端不可用」。

    情境：送出去了，但工人掛了／EC2 在半路被 Stop——結果永遠不會來。
    使用者**完全無感**：照片照樣入收件箱，只是慢一點（等了逾時秒數）。
    """
    advance_clock_each_call(monkeypatch)
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING, worker_on_duty=False)  # 另一頭根本沒有人

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert mailbox.send_job_calls == 1, "有送出去（只是沒人做）"
    assert photo_repository.count_photos() == 1, "照片照樣入庫（§0 禁止第 6 條）"
    assert store.deleted[job_id]["route"] == "local", "fallback 之後 route 要改成 local"
    assert any("fallback=local reason=result_timeout" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


def test_逾時fallback之前會先清掉S3物件(monkeypatch):
    """§2.1：「若已寫到 S3／SQS：**盡力刪物件、刪訊息**，避免下次 Start 重複處理」。

    不清的話，下次 EC2 開機時工人會看到一則舊的 jobs 訊息、把那張圖再看一次——
    而本機早就已經用 fallback 入庫了。

    「**之前**」怎麼證明：光看最後的 objects == {} 只證明得了「有清」，證明不了「先清」。
    所以 store 用把 photo_ids 寫入也記進**信箱同一本流水帳**的版本——
    fallback 的 run_ingest_job 入庫成功時會寫一次 photo_ids，
    那一行落在 delete_objects 後面，就等於「清 S3 發生在本機入庫之前」。
    """
    advance_clock_each_call(monkeypatch)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING, worker_on_duty=False)
    store = LedgerStore(mailbox)
    job_id = create_job(store)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert mailbox.objects == {}, f"S3 應該被清乾淨了：{list(mailbox.objects)}"
    assert mailbox.delete_calls >= 1
    assert photo_repository.count_photos() == 1

    first_cleanup_index = next(
        i for i, c in enumerate(mailbox.calls) if c.startswith("delete_objects")
    )
    first_photo_ids_write_index = mailbox.calls.index("store.update photo_ids")
    assert first_cleanup_index < first_photo_ids_write_index, (
        f"清 S3 要在 fallback 真的入庫之前（design6 §2.1）：{mailbox.calls}"
    )


def test_同一個job_id的結果送兩次_照片仍然只有一列(monkeypatch):
    """design6 D17、§9 必釘第 6 條：SQS 是 at-least-once，同一筆可能被處理兩次。

    情境（就是總覽 §10.2 R 講的那條時序）：上一趟其實已經 INSERT 成功了、`photo_ids` 也寫進去了，
    但在那之後、`cleanup` 與「刪 job」之前被殺掉，於是佇列把同一個任務再送一次，
    而且 S3 上的結果還在（cleanup 沒跑完）。
    **必須直接收尾，不可以插出第二張照片**（本專案沒有刪除照片的功能）。

    第二趟靠什麼擋下來：`route == "cloud"` → `_resume_cloud_route` → `fetch_result` 拿到結果 →
    **重讀一次 job**（`store.get`）→ `photo_ids` 有值 → `_store_cloud_result` 第一件事就收尾。
    這一顆用「重新建 job 並先寫好 `photo_ids`」來擺出那個時序，所以它同時涵蓋
    「開頭那次 `store.get` 就看得到 `photo_ids`」與「落庫前重讀」兩條路——
    單執行緒測試分不出這兩者，重讀真正防的是 `--concurrency=2` 的並行窗口（見 §7 陷阱 12）。
    """
    # 綠的時候這一顆根本不會進 wait_result；接管時鐘是為了**紅的那一次**——
    # Phase 79 的碼沒有 route=cloud 分支，第二趟會再 submit 一次然後等到逾時，
    # 不接管的話那一次紅會先空轉 5 秒。
    advance_clock_each_call(monkeypatch)
    store = RememberDeletedStore()
    job_id = create_job(store)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )
    assert photo_repository.count_photos() == 1
    photo_id = store.deleted[job_id]["photo_ids"][0]

    # ---- 佇列把同一個任務再送一次 ----
    create_job(store, job_id=job_id)  # staging 與 job 都重新出現（模擬重送）
    store.update(job_id, route="cloud", photo_ids=[photo_id])
    second_mailbox = FakeMailbox()
    put_result(second_mailbox, job_id, RECEIPT_UNDERSTANDING)

    run(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_route(second_mailbox),
    )

    assert photo_repository.count_photos() == 1, "同一個 job_id 不可以插出第二張照片"
    assert second_mailbox.send_job_calls == 0, "重送時不可以再送一次雲端"
    assert store.get(job_id) is None, "直接收尾（＝job 被刪掉）"
    assert second_mailbox.objects == {}, "S3 也要清乾淨"


def test_崩潰重送route是cloud而且S3有結果_直接落庫零submit():
    """總覽 §2.5：`route == "cloud"` 的重送先去 S3 看結果在不在。

    在 → 直接用它落庫。**不可以再 submit 一次**：上一趟送出去的東西還在，
    工人可能正在做，再送一次只是讓它白做一次、S3 多一份垃圾。

    順便釘住總覽 §10.2 R 的落庫順序：INSERT 之後**先寫 photo_ids、再清 S3**。
    反過來的話，清 S3 清到一半被殺掉，重送時 job 裡沒有 photo_ids → 同一張照片插第二次。
    """
    mailbox = FakeMailbox()
    store = LedgerStore(mailbox)
    job_id = create_job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")  # 上一趟已經送出去了
    put_result(mailbox, job_id, RECEIPT_UNDERSTANDING)
    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換答案也不該被問到

    run(job_id, store=store, gate=gate, cloud=cloud_route(mailbox))

    assert gate.calls == 0, "route 已經有值了，不可以再問一次閘門（design6 §2.1）"
    assert mailbox.send_job_calls == 0, "不可以再送一次"
    assert mailbox.put_calls == 0, "本機這一趟一個 Put 都沒有（結果是工人上一趟放的）"
    assert photo_repository.count_photos() == 1, "用 S3 上那份結果落庫"
    assert store.get(job_id) is None
    assert mailbox.objects == {}, "落庫之後把 S3 清乾淨"

    first_photo_ids_write_index = mailbox.calls.index("store.update photo_ids")
    first_cleanup_index = next(
        i for i, c in enumerate(mailbox.calls) if c.startswith("delete_objects")
    )
    assert first_photo_ids_write_index < first_cleanup_index, (
        f"photo_ids 要在清 S3 **之前**寫進 job（總覽 §10.2 R）：{mailbox.calls}"
    )


def test_崩潰重送route是cloud但S3沒有結果_fallback本機(caplog):
    """另一半：結果不在（工人根本沒做完、或訊息被別人當殘訊息清掉了）。

    那一趟的結果**永遠不會來了**（results 訊息已經被誰收走）——所以不要再等，
    直接退回本機。log 的 reason 是 `redelivered_without_result`。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")
    mailbox = FakeMailbox()  # S3 上什麼都沒有

    run(job_id, store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=cloud_route(mailbox))

    assert mailbox.send_job_calls == 0
    assert photo_repository.count_photos() == 1, "走本機把它做完"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=redelivered_without_result" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


def test_崩潰重送時雲端路已經關掉_照樣fallback本機(caplog):
    """使用者在任務跑到一半把 .env 改回 CLOUD_ROUTE=off 並 restart worker。

    重送回來時 job 的 route 還是 "cloud"，但手上的 cloud 已經換成 CloudRouteOff——
    它的 fetch_result／cleanup **都會丟 RuntimeError**。
    `_resume_cloud_route` 與 `_best_effort_cloud_cleanup` 那兩個 try 就是為了這一刻
    （兩支的 docstring 都寫明了「cloud 有可能已經是 CloudRouteOff」），
    但在本 phase 之前**零測試**——註解說有防護，沒有人證明過。

    正確行為：兩個例外都被吃掉並留 warning -> fallback 本機
    -> reason=redelivered_without_result -> 照片照樣入庫一列。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")
    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 走到就代表「重送又問了一次閘門」＝違規

    run(job_id, store=store, gate=gate, cloud=cloud_ingest.CloudRouteOff())

    assert gate.calls == 0, "route 已經有值就不准再問閘門（design6 §2.1）"
    assert photo_repository.count_photos() == 1, "走本機把它做完（使用者無感）"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=redelivered_without_result" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )
    # 防假綠：RuntimeError 真的發生過才算數（不然「CloudRouteOff 安靜回 None」也會綠）
    assert any("崩潰重送時讀不到雲端結果" in m for m in caplog.messages), (
        f"fetch_result 應該丟 RuntimeError 並被 _resume_cloud_route 記下來：{caplog.messages}"
    )


def test_等結果時信箱丟例外_fallback本機而且清乾淨(monkeypatch, caplog):
    """controller 裁決 R14（Phase 79 review 的 Minor 升級成本 phase 的做項）。

    真的 `AwsMailbox.receive_result`／`get_object` 在網路抖動時**會丟例外**。
    沒有 try 的話那個例外會一路飛到 `celery_app.ingest_task`（那裡沒有 try、也沒有
    autoretry），結果是 job **永遠卡在 analyzing**、staging 與 S3 都留著、
    面板連一列失敗都不會出現——最難查的一種安靜壞掉。

    正確行為：當作逾時（視為 `None`）→ `_best_effort_cloud_cleanup` ＋
    `fallback=local reason=result_timeout` → 走本機把照片做完。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    mailbox = FakeMailbox()

    def flaky_receive(wait_seconds: int):
        raise RuntimeError("SQS 連不上")

    monkeypatch.setattr(mailbox, "receive_result", flaky_receive)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert mailbox.send_job_calls == 1, "有送出去（例外發生在「等結果」那一步）"
    assert photo_repository.count_photos() == 1, "照片照樣入庫一列（§0 禁止第 6 條）"
    assert store.get(job_id) is None, "job 被刪掉＝這一筆成功收尾了"
    assert store.deleted[job_id]["route"] == "local"
    assert mailbox.delete_calls >= 1, "fallback 之前要盡力清掉 S3 上的半套東西（§2.1）"
    assert mailbox.objects == {}
    assert any("fallback=local reason=result_timeout" in m for m in caplog.messages), (
        f"信箱丟例外要當成逾時處理：{caplog.messages}"
    )
