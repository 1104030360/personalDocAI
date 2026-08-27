"""app/celery_app.py 的煙霧測試（Phase 65）。

只驗「組裝對不對」，不驗行為：匯入得起來、broker 指到設定、沒有 result backend、
任務名稱逐字等於契約 §3.5、依快照挑 VLM 且不受 config.AI_BACKEND 影響（D14 守門員）。

全程零網路：建 Celery 實例不會連 broker；建 OllamaVLM／OllamaCloudVLM 也不會連線
（真正發請求的是 invoke()／chat()）。
"""

from app import dependencies
from app.celery_app import celery_app, ingest_task
from app.core import config
from app.services import vlm_service


def test_celery實例的broker等於設定裡那一條():
    assert celery_app.conf.broker_url == config.CELERY_BROKER_URL


def test_沒有設定result_backend():
    # design5 §4.3：狀態走自己的 JobStore。沒設定時 Celery 給 None 或空字串，兩種都算過
    assert not celery_app.conf.result_backend


def test_任務名稱逐字等於契約寫的那一個():
    assert ingest_task.name == "personaldocai.ingest"
    assert "personaldocai.ingest" in celery_app.tasks   # 真的登記進任務表，worker 才找得到


def test_快照決定用哪一種看圖物件(monkeypatch):
    # HTTP header 不吃中文，假 key 一律 ASCII（2026-08-22 踩過）
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    assert isinstance(
        dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM
    )
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
    assert isinstance(
        dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM
    )
