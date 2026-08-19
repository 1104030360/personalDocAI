"""indexing_service 的單元測試：合併與轉向量的純邏輯，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U4「儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生）」
——合併順序固定＝「同輸入同向量」的前提（design.md §9）。
"""

from app.core import config
from app.services.indexing_service import build_document, embed_document
from tests.fakes import FakeEmbeddings


def test_合併內容的順序固定():
    document = build_document(
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    )
    assert document.page_content == (
        "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10\n"
        "類別: 收據\n"
        "地點: Target\n"
        "物品: 可樂、洋芋片\n"
        "時間: 2026-08-10"
    )
    assert document.metadata == {
        "category": "收據",
        "location": "Target",
        "items": ["可樂", "洋芋片"],
        "content_time": "2026-08-10",
    }


def test_空欄位直接省略():
    document = build_document(
        text="海邊的風景照", category="風景", location="海邊", items=[], content_time=None
    )
    assert document.page_content == "海邊的風景照\n類別: 風景\n地點: 海邊"


def test_英文值保持原文而標籤固定中文():
    # design.md §9：標籤是固定格式的一部分不隨語言變，值保持原文，跨語言交給多語 embedding
    document = build_document(
        text="Receipt from Target with Cola and Chips",
        category="Receipt",
        location="Target",
        items=["Cola", "Chips"],
        content_time="2026-08-10",
    )
    assert document.page_content == (
        "Receipt from Target with Cola and Chips\n"
        "類別: Receipt\n"
        "地點: Target\n"
        "物品: Cola、Chips\n"
        "時間: 2026-08-10"
    )


def test_embed_document_長度正確且同輸入同向量():
    document = build_document(
        text="在 Target 購買可樂與洋芋片的收據",
        category="收據",
        location="Target",
        items=["可樂"],
        content_time=None,
    )
    first = embed_document(FakeEmbeddings(), document)
    second = embed_document(FakeEmbeddings(), document)
    assert len(first) == config.EMBEDDING_DIM
    assert first == second  # 決定論：同輸入永遠同向量
