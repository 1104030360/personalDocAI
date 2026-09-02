"""entity_suggestion_service 的單元測試（2026-08-22 起：雲端路徑）。

本機路徑的失敗語意由 tests/integration/test_design3_error_paths.py 把關
（會爆炸的模型／回垃圾的模型）；這裡補雲端實作：同一份 prompt、
同樣「只試一次、任何失敗回 None 不往外丟、一定留 log」。
用 FakeCloudChat 練、不碰網路（建構子只組物件，真正連線的是 chat()）。
"""

from __future__ import annotations

import logging

import pytest

from app.core import config
from app.services import entity_suggestion_service
from app.services.entity_suggestion_service import (
    CLOUD_PICK_JSON_INSTRUCTION,
    EntityPick,
    OllamaCloudEntitySuggester,
    OllamaEntitySuggester,
    _build_pick_prompt,
)
from tests.fakes import FakeCloudChat

PHOTO = {
    "text": "MacBook 的維修發票",
    "category": "收據",
    "location": "Apple",
    "items": ["筆電"],
    "content_time": None,
}
CANDIDATES = [{"name": "我的 MacBook", "description": "筆電"}]


@pytest.fixture(autouse=True)
def 雲端假key(monkeypatch):
    """雲端類別建構時拿 config.OLLAMA_API_KEY 組 HTTP header：
    蓋成固定 ASCII 假值，測試不因開發機 .env 有沒有填真 key 而變色。"""
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")


def _雲端建議(content: str | None) -> tuple[OllamaCloudEntitySuggester, FakeCloudChat]:
    suggester = OllamaCloudEntitySuggester(model="gemma4")
    fake = FakeCloudChat(content)
    suggester._client = fake
    return suggester, fake


def test_本機實體建議用function_calling強制結構化輸出(monkeypatch):
    captured = {}

    class 假ChatOllama:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            captured["structured"] = kwargs
            return object()

    monkeypatch.setattr(entity_suggestion_service, "ChatOllama", 假ChatOllama)

    suggester = entity_suggestion_service.OllamaEntitySuggester(
        model="qa-model", base_url="http://qa"
    )

    assert suggester._model is not None
    assert captured["init"] == {
        "model": "qa-model",
        "base_url": "http://qa",
        "temperature": 0,
    }
    assert captured["schema"] is entity_suggestion_service.EntityPick
    assert captured["structured"] == {"method": "function_calling"}
    assert suggester.timing_target == entity_suggestion_service.ai_timing.AiTarget(
        backend="local", model="qa-model"
    )


def test_雲端建議_回覆包著圍欄也挑得出來():
    suggester, fake = _雲端建議('```json\n{"entity": "我的 MacBook"}\n```')

    assert suggester.pick(PHOTO, CANDIDATES) == "我的 MacBook"
    # 送出去的內容＝共用的挑選 prompt＋雲端的「只准回 JSON」指令（共用段逐字不動）
    content = fake.calls[0]["messages"][0]["content"]
    assert content == _build_pick_prompt(PHOTO, CANDIDATES) + CLOUD_PICK_JSON_INSTRUCTION


def test_雲端建議_解析不出時回None並留log(caplog):
    """建議可有可無：雲端回了條列也只是「這次不給建議」，不可以往外炸。"""
    suggester, _ = _雲端建議("- entity：我的 MacBook")

    with caplog.at_level(logging.WARNING):
        assert suggester.pick(PHOTO, CANDIDATES) is None

    assert "實體建議" in caplog.text


# ---------------------- AI 計時 log（Phase 43）----------------------
#
# `entity_suggest` 是六種 kind 裡兩個包在**類別內**的之一（另一個是增量六 Phase 75 的 `privacy`，
# 在 OllamaPrivacyModel.judge() 裡；design4 §5.3／§5.4 明白指定
# 「entity_suggestion_service 本機＋雲端各一處」）。代價是 tests/fakes.py 的
# FakeEntitySuggester 不會打 log，所以這兩顆用「真的類別＋假的內部模型」來測。
#
# 兩個坑（計畫 §4.2 B 表）：
#   1. log 的 backend 欄位讀的是 config.AI_BACKEND，**不是**看物件是哪個類別，
#      所以要驗 cloud 就得 monkeypatch 撥開關（連 local 那半邊也明寫，不靠預設值）。
#   2. model 欄位同樣是 log_ai 從 config 推的，不是建構子那個參數——
#      斷言一律用 f-string 帶 config 符號，寫死 model=gemma4 會變成綁死某台機器的 .env。


class 挑得出來的模型:
    """長得像 with_structured_output(EntityPick) 之後那個東西的最小假件。"""

    def invoke(self, messages):
        return EntityPick(entity="我的 MacBook")


class 回傳None的模型:
    def invoke(self, messages):
        return None


def _計時行(caplog, 前綴: str) -> list[str]:
    """撈出這次呼叫的計時 log。開始行與結束行都含 kind=，所以連開頭一起比對。"""
    開頭 = f"AI {前綴} kind=entity_suggest "
    return [m for m in caplog.messages if m.startswith(開頭)]


def test_本機實體建議會打entity_suggest的log(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    # 建構子只把 ChatOllama 組起來、**不會連線**（真正發出請求的是 invoke），
    # 下一行就把 _model 換掉，所以這顆測試不依賴 Ollama 有沒有在跑
    suggester = OllamaEntitySuggester()
    suggester._model = 挑得出來的模型()

    assert suggester.pick(PHOTO, CANDIDATES) == "我的 MacBook"

    assert len(_計時行(caplog, "開始")) == 1, caplog.messages
    結束 = _計時行(caplog, "結束")
    assert len(結束) == 1, caplog.messages
    assert "ok=true" in 結束[0]
    assert f"backend=local model={config.LLM_MODEL}" in 結束[0]


def test_本機實體建議回傳None時entity_suggest計時標ok為false(caplog, monkeypatch):
    # Given：本機 structured output adapter 靜默回傳 None。
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    suggester = OllamaEntitySuggester()
    suggester._model = 回傳None的模型()

    # When：服務照既有失敗語意處理這次建議。
    result = suggester.pick(PHOTO, CANDIDATES)

    # Then：呼叫端仍拿到 None，但 timing log 不可把無效輸出算成功。
    assert result is None
    結束 = _計時行(caplog, "結束")
    assert len(結束) == 1, caplog.messages
    assert "ok=false" in 結束[0]


def test_雲端實體建議的log是cloud且失敗標ok為false(caplog, monkeypatch):
    """解析不出來對這次呼叫來說就是失敗（與看圖那邊一致），但仍回 None 不往外炸。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")

    # ① 正常回 JSON
    suggester, _ = _雲端建議('{"entity": "我的 MacBook"}')
    assert suggester.pick(PHOTO, CANDIDATES) == "我的 MacBook"
    結束 = _計時行(caplog, "結束")
    assert len(結束) == 1, caplog.messages
    assert "ok=true" in 結束[0]
    assert f"backend=cloud model={config.OLLAMA_CLOUD_LLM_MODEL}" in 結束[0]

    # caplog 是整顆測試累積的：不清掉下面會撈到 2 行
    caplog.clear()

    # ② 回條列＝解析不出來
    suggester, _ = _雲端建議("- entity：我的 MacBook")
    assert suggester.pick(PHOTO, CANDIDATES) is None  # 語意一字未變
    結束 = _計時行(caplog, "結束")
    assert len(結束) == 1, caplog.messages
    assert "ok=false" in 結束[0]
