"""ask_workflow 純函式的單元測試（Phase 34）。

format_entity_names 只有正式路徑的 OllamaRouter 會用（假件查表、不組 prompt），
整合測試因此永遠跑不到它——空清單那句「明示話」是設計決策
（留白會讓模型自行想像清單然後挑一個不存在的名字），要有人守著。
"""

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from app.core import config
from app.services.ask_workflow import (
    CLOUD_ROUTE_JSON_INSTRUCTION,
    OllamaCloudAnswerer,
    OllamaCloudRouter,
    build_answer_prompt,
    build_route_prompt,
    format_entity_names,
)
from tests.fakes import FakeCloudChat


def test_有清單時逐行列出():
    text = format_entity_names(["我的 MacBook", "Project 2"])

    assert text == "- 我的 MacBook\n- Project 2"


def test_空清單輸出明示話而不是留白():
    text = format_entity_names([])

    # 措辭可以微調，但兩個重點不能掉：不是空字串、且明講「不可能用 entity 查法」
    assert text != ""
    assert "entity" in text


# ---- 雲端路由與回答（2026-08-22 AI 後端開關擴及詢問）----
#
# ollama.com 對 format= 不見得強制（教訓見 ollama_cloud 模組 docstring），
# 所以雲端路由靠 prompt 尾端指令＋寬鬆抽取。用 FakeCloudChat 練、不碰網路。


@pytest.fixture(autouse=True)
def 雲端假key(monkeypatch):
    """雲端類別建構時拿 config.OLLAMA_API_KEY 組 HTTP header：
    蓋成固定 ASCII 假值，測試不因開發機 .env 有沒有填真 key 而變色。"""
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")


def _雲端路由(content: str | None) -> tuple[OllamaCloudRouter, FakeCloudChat]:
    router = OllamaCloudRouter(model="gemma4")
    fake = FakeCloudChat(content)
    router._client = fake
    return router, fake


def test_雲端路由_回覆包著圍欄也解析得出來():
    router, fake = _雲端路由('```json\n{"mode": "task", "due_within_days": 7}\n```')

    decision = router.route("這週要交什麼？", ["我的 MacBook"])

    assert decision.mode == "task"
    assert decision.due_within_days == 7
    # 送出去的內容＝共用的路由 prompt＋雲端的「只准回 JSON」指令（共用段逐字不動）
    content = fake.calls[0]["messages"][0]["content"]
    assert content == (
        build_route_prompt("這週要交什麼？", ["我的 MacBook"])
        + CLOUD_ROUTE_JSON_INSTRUCTION
    )


def test_雲端路由_解析不出時往外丟給route節點fallback():
    """失敗語意與本機一致：這裡不吞，由 route 節點統一 fallback 成 vector。"""
    router, _ = _雲端路由("- mode：vector")

    with pytest.raises(ValidationError):
        router.route("隨便問", [])


def test_雲端回答_回文字並用共用prompt():
    answerer = OllamaCloudAnswerer(model="gemma4")
    fake = FakeCloudChat("你買過可樂。")
    answerer._client = fake
    documents = [Document(page_content="在 Target 買可樂的收據", metadata={"id": 7})]

    assert answerer.answer("我買過什麼？", documents) == "你買過可樂。"
    # 回答是純文字：prompt 與本機逐字相同、不帶 JSON 指令
    assert fake.calls[0]["messages"][0]["content"] == build_answer_prompt(
        "我買過什麼？", documents
    )


def test_build_answer_prompt_空結果時明講沒找到():
    prompt = build_answer_prompt("我買過什麼？", [])

    assert "沒有找到任何照片" in prompt
