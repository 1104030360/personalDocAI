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
from app.services.entity_suggestion_service import (
    CLOUD_PICK_JSON_INSTRUCTION,
    OllamaCloudEntitySuggester,
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
