"""POST /ask 端點的基本行為＋雙語回答（規格驗收在 Phase 12）。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.dependencies import get_answerer, get_router
from app.main import app
from app.repositories import photo_repository
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

# conftest 的 wire_fake_ai 已把固定時鐘設成同一時間；這個常數拿來組測試資料
NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture(autouse=True)
def wire_ask_fakes(wire_fake_ai):
    """接上詢問用的兩個假件（embeddings 與固定時鐘由 conftest 的 wire_fake_ai 統一接管）。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()——
    沿用 test_upload_feature.py 的既有慣例。
    """
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_answerer] = lambda: FakeAnswerLLM()
    yield


def _一張Target收據() -> int:
    return photo_repository.insert_photo(
        text="在 Target 購買可樂與洋芋片的收據", category="收據", location="Target",
        items=["可樂", "洋芋片"], content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query("在 Target 購買可樂與洋芋片的收據"),
        uploaded_at=NOW,
    )["id"]


def test_條件查詢的回應內容(client):
    photo_id = _一張Target收據()

    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "metadata search"
    assert body["retrieved_photo_ids"] == [photo_id]
    assert "可樂" in body["answer"]


def test_英文提問得到英文回答(client):
    """雙語：回答語言跟隨提問語言；照片內容維持原文（design.md §8.3 鐵律 3）。"""
    photo_id = _一張Target收據()

    response = client.post(
        "/ask", json={"question": "What drinks did I buy recently?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "vector semantic search"
    assert body["retrieved_photo_ids"] == [photo_id]
    # 回答的框架句是英文
    assert body["answer"].startswith("Based on the photos")
    # 但照片內容原文照抄，沒有被翻譯
    assert "可樂" in body["answer"]


def test_沒有照片時回覆查無(client):
    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


def test_模糊問題走語意查詢(client):
    response = client.post("/ask", json={"question": "幫我找找之前那個"})

    assert response.status_code == 200
    assert response.json()["search_mode"] == "vector semantic search"


def test_問題缺漏或空字串回422(client):
    assert client.post("/ask", json={}).status_code == 422
    assert client.post("/ask", json={"question": ""}).status_code == 422
