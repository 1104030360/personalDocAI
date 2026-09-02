"""app/celery_app.py 的煙霧測試（Phase 65）。

只驗「組裝對不對」，不驗行為：匯入得起來、broker 指到設定、沒有 result backend、
任務名稱逐字等於契約 §3.5、依快照挑 VLM 且不受 config.AI_BACKEND 影響（D14 守門員）。

全程零網路：建 Celery 實例不會連 broker；建 OllamaVLM／OllamaCloudVLM 也不會連線
（真正發請求的是 invoke()／chat()）。
"""

from app import dependencies
from app.celery_app import celery_app, ingest_task
from app.core import config
from app.services import gated_ingest, vlm_service
from app.services.cloud_ingest import CloudRouteOff
from app.services.privacy_gate import Verdict
from tests.fakes import FakePrivacyGate


def test_celery實例的broker等於設定裡那一條():
    assert celery_app.conf.broker_url == config.CELERY_BROKER_URL


def test_沒有設定result_backend():
    # design5 §4.3：狀態走自己的 JobStore。沒設定時 Celery 給 None 或空字串，兩種都算過
    assert not celery_app.conf.result_backend


def test_任務名稱逐字等於契約寫的那一個():
    assert ingest_task.name == "personaldocai.ingest"
    assert "personaldocai.ingest" in celery_app.tasks  # 真的登記進任務表，worker 才找得到


def test_快照決定用哪一種看圖物件(monkeypatch):
    # HTTP header 不吃中文，假 key 一律 ASCII（2026-08-22 踩過）
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    assert isinstance(dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM)
    assert isinstance(dependencies.build_vlm_for_backend("local"), vlm_service.OllamaVLM)


def test_快照贏過開關(monkeypatch):
    """D14 的守門員：worker 只認快照，不認 config.AI_BACKEND。

    這一顆紅了，代表 worker 會被「使用者中途撥回本機」影響，或更糟——
    worker 行程裡的 AI_BACKEND 永遠是 local，於是快照 cloud 也走本機。
    """
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    assert isinstance(dependencies.build_vlm_for_backend("local"), vlm_service.OllamaVLM)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    assert isinstance(dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM)


def test_ingest_task把gate與cloud都傳進去(monkeypatch):
    """design6 D5／D6：Celery 任務從此呼叫 run_gated_ingest_job，六個零件一個都不能少，
    而且 gate 與 vlm 都要用**同一份快照** job["ai_backend"] 建（裁決 R1）。

    ★ 為什麼 celery_app.py 要寫成 `gated_ingest.run_gated_ingest_job(...)`
      而不是 `from app.services.gated_ingest import run_gated_ingest_job` 再直接呼叫：
      **模組屬性是呼叫當下才解析的**，所以 monkeypatch 換得掉；
      早綁定（from … import）拿到的是換掉前的舊參照，這一顆會什麼都抓不到。
      這與第四／五道安全網攔得住 dependencies.get_job_store()／get_cloud_route()
      是同一個道理（Phase 57 陷阱 7）。

    ★ gate 與 cloud 都要拿到**假件**，這一顆才算數：ingest_task 是**直接呼叫**
      dependencies.build_privacy_gate_for_backend()／get_cloud_route()，而
      dependency_overrides 只在 FastAPI 解析 Depends() 時才被查表——所以兩道安全網
      都必須「雙管」（dependency_overrides ＋ monkeypatch）。少了 monkeypatch 那一管，
      這裡拿到的會是真的那一支：Phase 75 之後那一支會建出 OllamaPrivacyModel，
      pytest 就有機會打到真的看圖模型。

    ★ 這一顆刻意把 job 的快照設成 "cloud"、把 worker 行程的 config.AI_BACKEND
      留在 "local"：兩個值不一樣，才驗得出「閘門跟的是快照、不是行程裡那個變數」。
      寫成 get_privacy_gate() 的話 received_backends 會是 ["local"]，這一顆就紅——
      而正式環境裡那個錯誤是**安靜**的（看圖走雲端、閘門仍打本機，違反 D6）。
    """
    # HTTP header 不吃中文，假 key 一律 ASCII（2026-08-22 踩過）
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(config, "AI_BACKEND", "local")  # worker 行程永遠是這個值

    received: dict = {}
    received_backends: list[str] = []

    def fake_ingest_job(job_id, **kwargs):
        received["job_id"] = job_id
        received.update(kwargs)

    def recording_build_gate(ai_backend):
        received_backends.append(ai_backend)
        return FakePrivacyGate(Verdict.UNCERTAIN)

    monkeypatch.setattr(gated_ingest, "run_gated_ingest_job", fake_ingest_job)
    monkeypatch.setattr(dependencies, "build_privacy_gate_for_backend", recording_build_gate)

    store = dependencies.get_job_store()  # 第四道安全網已經把它換成記憶體版
    store.create(
        job_id="job-1",
        filename="a.png",
        content_type="image/png",
        ai_backend="cloud",  # 入列當下使用者把頁首開關撥在雲端（D14 的快照）
        source="upload",
    )

    ingest_task("job-1")

    assert received["job_id"] == "job-1"
    assert set(received) == {"job_id", "store", "vlm", "embeddings", "now", "gate", "cloud"}
    assert received["store"] is store
    assert isinstance(received["gate"], FakePrivacyGate), (
        "wire_fake_ai 的第二管（monkeypatch）沒接上——ingest_task 是直接呼叫 "
        "dependencies.build_privacy_gate_for_backend()，dependency_overrides 攔不到它"
    )
    assert received_backends == ["cloud"], (
        "閘門必須用 job['ai_backend'] 這份快照建（裁決 R1）。拿到 ['local'] "
        "代表寫成了 get_privacy_gate()——worker 行程的 config.AI_BACKEND 永遠是 local，"
        "頁首撥到雲端時閘門會安靜地繼續打本機，違反 D6"
    )
    assert isinstance(received["cloud"], CloudRouteOff), "第五道安全網把雲端路換成關掉的那一顆"
    assert isinstance(received["vlm"], vlm_service.OllamaCloudVLM), (
        "看圖物件也是同一份快照建的（增量五既有行為，本 phase 一個字都沒改）"
    )
