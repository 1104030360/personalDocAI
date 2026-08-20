"""檢索層測試：兩條查詢 ＋ 30 天時間過濾（含邊界）＋ ILIKE 大小寫不敏感。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.repositories import photo_repository
from app.services.retrieval_service import (
    QueryFilters,
    metadata_search,
    photo_retriever,
    vector_search,
)
from tests.fakes import FakeEmbeddings

NOW = datetime(2026, 8, 18, 10, 0)
TODAY = NOW.date()


def _insert(text, category, location, items, content_time, uploaded_at):
    return photo_repository.insert_photo(
        text=text,
        category=category,
        location=location,
        items=items,
        content_time=content_time,
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=uploaded_at,
    )["id"]


@pytest.fixture
def 三張規格照片():
    """完全照 自然語言詢問.feature 的資料表建立。"""
    id1 = _insert("在 Target 購買可樂的收據", "收據", "Target", ["可樂"],
                  date(2026, 8, 10), datetime(2026, 8, 18, 10, 0))
    id2 = _insert("在 Costco 購買牛奶的收據", "收據", "Costco", ["牛奶"],
                  date(2026, 5, 1), datetime(2026, 8, 17, 9, 0))
    id3 = _insert("在 7-11 購買咖啡的收據", "收據", "7-11", ["咖啡"],
                  None, datetime(2026, 8, 15, 12, 0))
    return id1, id2, id3


@pytest.fixture
def 一張英文收據():
    """欄位值是英文、而且是大寫開頭——用來驗 ILIKE 的大小寫不敏感。"""
    return _insert("Receipt from Target with Cola and Chips", "Receipt", "Target",
                   ["Cola", "Chips"], date(2026, 8, 10), datetime(2026, 8, 18, 10, 0))


def _ids(documents):
    return sorted(doc.metadata["id"] for doc in documents)


def test_時間過濾以內容時間優先缺漏時用上傳時間(三張規格照片):
    id1, id2, id3 = 三張規格照片

    documents = vector_search(
        "我最近買過什麼飲料？", FakeEmbeddings(),
        QueryFilters(recent=True), TODAY,
    )

    # 1 號的內容時間 2026-08-10 在 30 天內 → 保留
    # 2 號的內容時間 2026-05-01 超過 30 天——雖然它的上傳時間 2026-08-17
    #   就在昨天，仍以內容時間為準 → 被排除
    # 3 號沒有內容時間，改看上傳時間 2026-08-15（在 30 天內）→ 保留
    assert _ids(documents) == sorted([id1, id3])

    # 條件查詢也套用同一條時間過濾（兩路共用），結果必須一致
    metadata_documents = metadata_search(
        QueryFilters(category="收據", recent=True), TODAY
    )
    assert _ids(metadata_documents) == sorted([id1, id3])


def test_沒有時間條件時不做時間過濾(三張規格照片):
    id1, id2, id3 = 三張規格照片

    documents = vector_search(
        "買過什麼？", FakeEmbeddings(), QueryFilters(recent=False), TODAY
    )

    assert _ids(documents) == sorted([id1, id2, id3])


# parametrize＝讓同一個測試函式帶多組參數各跑一次（這裡是 29／30／31 天三組），
# pytest 會把它算成 3 個測試
@pytest.mark.parametrize(
    "天數, 應該被找到",
    [(29, True), (30, True), (31, False)],
)
def test_三十天邊界(天數, 應該被找到):
    photo_id = _insert("在 Target 購買可樂的收據", "收據", "Target", ["可樂"],
                       TODAY - timedelta(days=天數), datetime(2026, 8, 18, 10, 0))

    documents = vector_search(
        "我最近買過什麼飲料？", FakeEmbeddings(), QueryFilters(recent=True), TODAY
    )

    assert (photo_id in _ids(documents)) is 應該被找到


def test_條件查詢用欄位過濾(三張規格照片):
    id1, _, _ = 三張規格照片

    documents = metadata_search(
        QueryFilters(category="收據", location="Target"), TODAY
    )

    assert _ids(documents) == [id1]


def test_條件查詢可以過濾物品(三張規格照片):
    _, id2, _ = 三張規格照片

    documents = metadata_search(QueryFilters(item="牛奶"), TODAY)

    assert _ids(documents) == [id2]


def test_地點比對不分大小寫(一張英文收據):
    """雙語：問題寫 target（小寫），也要找到存成 Target 的照片（ILIKE）。"""
    documents = metadata_search(QueryFilters(location="target"), TODAY)

    assert _ids(documents) == [一張英文收據]


def test_物品比對不分大小寫(一張英文收據):
    """雙語：陣列裡的元素也走 ILIKE（unnest + ILIKE）。"""
    documents = metadata_search(QueryFilters(item="cola"), TODAY)

    assert _ids(documents) == [一張英文收據]


def test_自訂retriever兩種模式都能用(三張規格照片):
    id1, _, _ = 三張規格照片

    metadata_result = photo_retriever.invoke({
        "question": "有哪些在 Target 拍的收據？",
        "mode": "metadata",
        "filters": QueryFilters(category="收據", location="Target"),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })
    vector_result = photo_retriever.invoke({
        "question": "我最近買過什麼飲料？",
        "mode": "vector",
        "filters": QueryFilters(recent=True),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })

    assert _ids(metadata_result) == [id1]
    assert len(vector_result) >= 1
    # 回傳的是 LangChain 的 Document，內容格式與寫入時一致
    assert vector_result[0].page_content.startswith("在 ")


def test_條件查詢依category過濾():
    """守住 search_by_metadata 的 category ILIKE——P11/P12 輪變異測試揭露此前無人守護。"""
    收據id = _insert("在 Target 購買可樂的收據", "收據", "Target",
                     ["可樂"], date(2026, 8, 10), NOW)
    _insert("海邊的風景照", "風景", "海邊", [], None, NOW)

    documents = metadata_search(QueryFilters(category="收據"), TODAY)

    assert [doc.metadata["id"] for doc in documents] == [收據id]
