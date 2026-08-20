"""photo_repository 的整合測試：連 PersonalDocAI_test 真測試庫。

BDD 對應（docs/spec/features/上傳照片.feature，本階段可落地的資料層行為）：
- U2/U3：文字與四欄位寫入後可原樣讀回（中英文皆可）
- U4：寫入後 embedding 不為空
- U5：不指定上傳時間時由資料庫自動記錄；測試也可注入固定時間
每個測試依 tests/conftest.py 的 autouse fixture 在乾淨的 photo 表上執行。
"""

from datetime import date, datetime, timezone

from app.core import config
from app.repositories import photo_repository as repo


def _vec(value: float = 0.01) -> list[float]:
    return [value] * config.EMBEDDING_DIM


def _insert_sample(**overrides):
    """Given：一筆標準中文收據資料（可用 overrides 覆寫任一欄位）。"""
    params = dict(
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time=date(2026, 8, 10),
        embedding=_vec(),
    )
    params.update(overrides)
    return repo.insert_photo(**params)


def test_insert_photo_returns_full_row():
    # When 寫入中文收據 Then 回傳列含 id 與全部欄位（U2/U3 資料層）
    row = _insert_sample()
    assert row["id"] == 1
    assert row["text"] == "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
    assert row["category"] == "收據"
    assert row["location"] == "Target"
    assert row["items"] == ["可樂", "洋芋片"]
    assert row["content_time"] == date(2026, 8, 10)


def test_insert_photo_english_row():
    # 雙語資料層基礎：英文內容原樣寫入與讀回
    row = _insert_sample(
        text="Receipt from Target with Cola and Chips, dated 2026-08-10",
        category="Receipt",
        items=["Cola", "Chips"],
    )
    assert row["category"] == "Receipt"
    assert row["items"] == ["Cola", "Chips"]


def test_insert_photo_nullable_fields_can_be_empty():
    # 風景照可能沒有類別/商家/內容時間（design.md §7 允許空）
    row = _insert_sample(category=None, location=None, items=[], content_time=None)
    assert row["category"] is None
    assert row["location"] is None
    assert row["items"] == []
    assert row["content_time"] is None


def test_uploaded_at_recorded_by_db_when_not_given():
    # U5：不傳 uploaded_at 時由資料庫 now() 自動記錄
    row = _insert_sample()
    assert row["uploaded_at"] is not None


def test_uploaded_at_uses_given_value_when_provided():
    # 「現在時間為 …」的時鐘注入點：測試可指定固定上傳時間
    fixed = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    row = _insert_sample(uploaded_at=fixed)
    assert row["uploaded_at"] == fixed


def test_fetch_photo_returns_row():
    inserted = _insert_sample()
    assert repo.fetch_photo(inserted["id"]) == inserted


def test_fetch_photo_returns_none_when_missing():
    assert repo.fetch_photo(999) is None


def test_fetch_embedding_not_empty():
    # U4 資料層：寫入後 embedding 不為空
    row = _insert_sample()
    emb = repo.fetch_embedding(row["id"])
    assert emb is not None and emb.startswith("[")


def test_fetch_embedding_none_when_missing():
    assert repo.fetch_embedding(999) is None


def test_count_and_clear_photos():
    assert repo.count_photos() == 0
    _insert_sample()
    _insert_sample()
    assert repo.count_photos() == 2
    repo.clear_photos()
    assert repo.count_photos() == 0
    assert _insert_sample()["id"] == 1  # RESTART IDENTITY：id 重新從 1 起編
