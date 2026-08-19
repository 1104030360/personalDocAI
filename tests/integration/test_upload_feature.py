"""把 docs/spec/features/上傳照片.feature 當測試跑（7 條 Rule）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_now, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import first_row, split_items
from tests.fakes import FakeVLM, understanding_for_text

# 直接掛上規格原檔——不複製、不改寫（路徑相對於本檔所在資料夾 tests/integration/）
scenarios("../../docs/spec/features/上傳照片.feature")

# 假的照片內容。全程用假件，不會真的被拿去看圖
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"

# 規格沒有指定「現在時間」時的預設值，確保測試結果不隨執行日期改變
DEFAULT_NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture
def context() -> dict:
    """一個測試裡各步驟之間傳遞資料的小抽屜。"""
    return {
        "now": DEFAULT_NOW,
        "understanding": PhotoUnderstanding(understood=False),
        "response": None,
    }


@pytest.fixture(autouse=True)
def wire_feature_clock(wire_fake_ai, context):
    """把「現在時間」改接到 context——Given 步驟改 context["now"] 即時生效。

    顯式依賴 conftest 的 wire_fake_ai（假 AI 已接好、測後統一 clear()），
    保證本 fixture 在它之後執行，get_now 的覆寫以這裡為準。
    """
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield


def _upload(context, client, filename="photo.png", content_type="image/png",
            payload=PNG_BYTES):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(context["understanding"])
    context["response"] = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )


def _stored_photo(context) -> dict:
    photo_id = context["response"].json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    assert row is not None, "資料庫裡找不到剛剛上傳的照片"
    return row


# ------------------------------ Given ------------------------------
@given(parsers.parse('現在時間為 "{moment}"'))
def 設定現在時間(context, moment):
    context["now"] = datetime.strptime(moment, "%Y-%m-%d %H:%M")


@given("VLM 無法理解上傳照片的內容")
def vlm看不懂(context):
    context["understanding"] = PhotoUnderstanding(understood=False)


# ------------------------------- When ------------------------------
@when("使用者上傳一個非圖片格式的檔案")
def 上傳非圖片檔(context, client):
    _upload(context, client, filename="note.txt",
            content_type="text/plain", payload="這不是圖片".encode())


@when(parsers.parse('使用者上傳一張照片，VLM 理解其內容為 "{text}"'))
def 上傳照片並指定理解內容(context, client, text):
    context["understanding"] = understanding_for_text(text)
    _upload(context, client)


@when("使用者上傳照片")
def 上傳照片(context, client):
    _upload(context, client)


# ------------------------------- Then ------------------------------
@then("操作失敗")
def 操作失敗(context):
    assert context["response"].status_code >= 400, context["response"].text


@then(parsers.parse("系統儲存的照片數量為 {count:d}"))
def 照片數量為(count):
    assert photo_repository.count_photos() == count


@then(parsers.parse('照片的文字描述為 "{text}"'))
def 照片文字描述為(context, text):
    assert _stored_photo(context)["text"] == text


@then("照片的 metadata 欄位如下")
def 照片metadata為(context, datatable):
    expected = first_row(datatable)
    row = _stored_photo(context)
    assert row["category"] == expected["category"]
    assert row["location"] == expected["location"]
    assert row["items"] == split_items(expected["items"])
    stored_time = row["content_time"].isoformat() if row["content_time"] else ""
    assert stored_time == expected["content_time"].strip()


@then("照片的 embedding 不為空")
def 照片embedding不為空(context):
    embedding = photo_repository.fetch_embedding(context["response"].json()["id"])
    assert embedding is not None
    assert embedding.startswith("[") and len(embedding) > 2


@then(parsers.parse('照片的上傳時間為 "{moment}"'))
def 照片上傳時間為(context, moment):
    uploaded_at = _stored_photo(context)["uploaded_at"]
    assert uploaded_at.strftime("%Y-%m-%d %H:%M") == moment


@then("回應包含照片識別碼")
def 回應包含識別碼(context):
    body = context["response"].json()
    assert isinstance(body.get("id"), int) and body["id"] > 0


@then(parsers.parse('回應的文字描述為 "{text}"'))
def 回應文字描述為(context, text):
    assert context["response"].json()["text"] == text


@then("回應的 metadata 欄位如下")
def 回應metadata為(context, datatable):
    expected = first_row(datatable)
    metadata = context["response"].json()["metadata"]
    assert metadata["category"] == expected["category"]
    assert metadata["location"] == expected["location"]
    assert metadata["items"] == split_items(expected["items"])
    assert (metadata["content_time"] or "") == expected["content_time"].strip()
