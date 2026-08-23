"""AI 後端開關（2026-08-22 產品負責人指示新增）：GET／PUT /settings/ai-backend。

design3.md「明確不做」原有「雲端 VLM」一項——本功能是產品負責人 2026-08-22
明示推翻該項後新增的（起初只管看圖，同日擴及詢問路由／回答與實體建議；
embeddings 一律本機——向量必須跟資料庫裡既有的 bge-m3 向量同源）。

真的打 Ollama Cloud 不寫進自動化測試（同「真模型只做手動煙霧」的鐵律，
何況 pytest 不該依賴 .env 有沒有填 OLLAMA_API_KEY）。這裡測的是開關本身：
預設本機、沒 key 切不過去、有 key 切得過去也切得回來、四個注入點跟著開關走。
"""

from __future__ import annotations

import pytest

from app import dependencies
from app.core import config
from app.services import ask_workflow, entity_suggestion_service, vlm_service


@pytest.fixture(autouse=True)
def 開關歸位(monkeypatch):
    """每顆測試都從「本機、沒 key」的乾淨狀態出發，測完把開關撥回本機。

    OLLAMA_API_KEY 一定要用 monkeypatch 蓋掉：開發機的 .env 裡有真 key，
    測試不可以因為那個 key 存在與否而變色（同 wire_fake_ai 的安全網精神）。
    """
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "")
    config.AI_BACKEND = "local"
    yield
    config.AI_BACKEND = "local"


def test_預設是本機(client):
    """伺服器一啟動（或重啟後）開關一律在本機，且回報 key 還沒設。"""
    body = client.get("/settings/ai-backend").json()

    assert body == {"backend": "local", "cloud_configured": False}


def test_沒填key時切雲端回422且開關不動(client):
    """守門在後端：寧可在這裡把話說清楚，也不要用到一半 401 偽裝成失敗。"""
    response = client.put("/settings/ai-backend", json={"backend": "cloud"})

    assert response.status_code == 422
    assert "OLLAMA_API_KEY" in response.json()["detail"]
    assert config.AI_BACKEND == "local"


def test_有key時切得到雲端也切得回來(client, monkeypatch):
    # 假 key 一律用 ASCII：真的 API key 本來就是 ASCII，而 HTTP header 值
    # 不吃非 ASCII——用中文假 key 會在建 Client 時就炸 UnicodeEncodeError
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-fake-key")

    response = client.put("/settings/ai-backend", json={"backend": "cloud"})
    assert response.status_code == 200, response.text
    assert response.json() == {"backend": "cloud", "cloud_configured": True}
    assert client.get("/settings/ai-backend").json()["backend"] == "cloud"

    response = client.put("/settings/ai-backend", json={"backend": "local"})
    assert response.status_code == 200, response.text
    assert config.AI_BACKEND == "local"


def test_不認識的值回422(client):
    """backend 是 Literal["local","cloud"]：其餘字串走框架既有的 422。"""
    response = client.put("/settings/ai-backend", json={"backend": "外太空"})

    assert response.status_code == 422
    assert config.AI_BACKEND == "local"


def test_開關撥到哪_四個AI注入點就給哪個實作(monkeypatch):
    """看圖＋詢問路由／回答＋實體建議全部跟著開關；embeddings 不在此列。

    直接呼叫 dependencies 的函式——conftest 的 wire_fake_ai 蓋的是
    dependency_overrides（HTTP 那一層），不影響直接的函式呼叫。
    八個實作的建構子都不會連線（真正發請求的是 invoke／chat）。
    """
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-fake-key")

    assert isinstance(dependencies.get_vlm(), vlm_service.OllamaVLM)
    assert isinstance(dependencies.get_router(), ask_workflow.OllamaRouter)
    assert isinstance(dependencies.get_answerer(), ask_workflow.OllamaAnswerer)
    assert isinstance(
        dependencies.get_entity_suggester(),
        entity_suggestion_service.OllamaEntitySuggester,
    )

    config.AI_BACKEND = "cloud"
    assert isinstance(dependencies.get_vlm(), vlm_service.OllamaCloudVLM)
    assert isinstance(dependencies.get_router(), ask_workflow.OllamaCloudRouter)
    assert isinstance(dependencies.get_answerer(), ask_workflow.OllamaCloudAnswerer)
    assert isinstance(
        dependencies.get_entity_suggester(),
        entity_suggestion_service.OllamaCloudEntitySuggester,
    )
