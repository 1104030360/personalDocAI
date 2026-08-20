"""route 節點：判斷查法 ＋ 失敗時 fallback 語意查詢 ＋ 英文問題也能判斷。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.repositories import photo_repository
from app.services.ask_workflow import AskDeps, run_ask
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

TODAY = date(2026, 8, 18)


@pytest.fixture
def deps() -> AskDeps:
    return AskDeps(
        router=FakeRouter(),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=TODAY,
    )


@pytest.fixture
def 一張Target收據():
    return photo_repository.insert_photo(
        text="在 Target 購買可樂與洋芋片的收據",
        category="收據", location="Target", items=["可樂", "洋芋片"],
        content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query("在 Target 購買可樂與洋芋片的收據"),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )["id"]


def test_條件過濾型問題走條件查詢(deps, 一張Target收據):
    state = run_ask("有哪些在 Target 拍的收據？", deps)

    assert state["mode"] == "metadata"
    assert state["filters"].category == "收據"
    assert state["filters"].location == "Target"
    assert [d.metadata["id"] for d in state["retrieved"]] == [一張Target收據]


def test_語意描述型問題走語意查詢(deps, 一張Target收據):
    state = run_ask("我最近買過什麼飲料？", deps)

    assert state["mode"] == "vector"
    assert state["filters"].recent is True


def test_英文語意描述型問題也走語意查詢(deps, 一張Target收據):
    """雙語：英文問題同樣要判斷得出查法與時間條件（design.md §5.2 的 few-shot）。"""
    state = run_ask("What drinks did I buy recently?", deps)

    assert state["mode"] == "vector"
    assert state["filters"].recent is True
    # 多語 embedding 讓英文問題也能召回中文內容的照片
    assert [d.metadata["id"] for d in state["retrieved"]] == [一張Target收據]


def test_無法判斷時走語意查詢(deps, 一張Target收據):
    state = run_ask("幫我找找之前那個", deps)

    assert state["mode"] == "vector"
    assert state["filters"].category is None
    assert state["filters"].location is None
    assert state["filters"].item is None
    assert state["filters"].recent is False


def test_路由回傳格式不對也走語意查詢(一張Target收據):
    class 壞掉的Router:
        def route(self, question):
            return {"mode": "metadata"}      # 不是 RouteDecision，格式不符

    deps = AskDeps(
        router=壞掉的Router(),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=TODAY,
    )
    state = run_ask("有哪些在 Target 拍的收據？", deps)

    assert state["mode"] == "vector"
