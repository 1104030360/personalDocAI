"""把 docs/spec/features/上傳照片.feature 當測試跑（10 條 Rule）。

2026-08-20 規格改版後：上傳當下 category 一律「未分類」，
VLM 給的類別只出現在回應的 suggested_folder，不落庫。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_now, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import first_row, split_items
from tests.fakes import FakeVLM, make_png_bytes, understanding_for_text

# 直接掛上規格原檔——不複製、不改寫（路徑相對於本檔所在資料夾 tests/integration/）
scenarios("../../docs/spec/features/上傳照片.feature")

# 一張真的 PNG（Phase 17 加的工具）。上傳成功會用 Pillow 產縮圖，
# 假位元組會讓縮圖那一步失敗變成 500。
PNG_BYTES = make_png_bytes()

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


def _body(context) -> dict:
    response = context["response"]
    assert response.status_code == 201, response.text
    return response.json()


def _stored_photo(context) -> dict:
    photo_id = _body(context)["id"]
    row = photo_repository.fetch_photo(photo_id)
    assert row is not None, "資料庫裡找不到剛剛上傳的照片"
    return row


def column(datatable: list[list[str]], name: str) -> list[str]:
    """把 Gherkin 表格的某一整欄取出來（第 0 列是欄位名）。

    first_row() 只看第一列資料；資料夾清單那張表有六列，要用這個。
    """
    header, *rows = datatable
    index = header.index(name)
    return [row[index].strip() for row in rows]


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


@when(parsers.parse('使用者上傳一張照片，VLM 推薦的類別為 "{category}"'))
def 上傳照片並指定推薦類別(context, client, category):
    """只關心「VLM 推薦了什麼類別」的例子，文字內容用一句固定的就好。"""
    context["understanding"] = PhotoUnderstanding(
        understood=True,
        text="一張看得懂的照片",
        category=category,
        location=None,
        items=[],
        content_time=None,
    )
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


@then(parsers.parse('照片的 metadata 類別為 "{category}"'))
def 照片metadata類別為(context, category):
    assert _stored_photo(context)["category"] == category


@then(parsers.parse('照片所屬資料夾為 "{name}"'))
def 照片所屬資料夾為(context, name):
    """驗 folder_id 真的掛到那個資料夾（不是只有 category 字串對）。"""
    folder = photo_repository.get_folder(_stored_photo(context)["folder_id"])
    assert folder is not None, "photo.folder_id 指向一個不存在的資料夾"
    assert folder["name"] == name


@then("照片的 embedding 不為空")
def 照片embedding不為空(context):
    embedding = photo_repository.fetch_embedding(_body(context)["id"])
    assert embedding is not None
    assert embedding.startswith("[") and len(embedding) > 2


@then("照片的原圖與縮圖都已儲存")
def 照片原圖與縮圖都已儲存(context):
    row = _stored_photo(context)
    assert row["original_path"], "original_path 是空的"
    assert row["thumbnail_path"], "thumbnail_path 是空的"
    assert row["content_type"] == "image/png"
    # 路徑存的是相對路徑（data/photos/1.png），換算成實際位置後檔案要真的在
    assert storage_service.absolute_path(row["original_path"]).exists()
    assert storage_service.absolute_path(row["thumbnail_path"]).exists()


@then(parsers.parse('照片的上傳時間為 "{moment}"'))
def 照片上傳時間為(context, moment):
    uploaded_at = _stored_photo(context)["uploaded_at"]
    assert uploaded_at.strftime("%Y-%m-%d %H:%M") == moment


@then("回應包含照片識別碼")
def 回應包含識別碼(context):
    body = _body(context)
    assert isinstance(body.get("id"), int) and body["id"] > 0


@then(parsers.parse('回應的文字描述為 "{text}"'))
def 回應文字描述為(context, text):
    assert _body(context)["text"] == text


@then("回應的 metadata 欄位如下")
def 回應metadata為(context, datatable):
    expected = first_row(datatable)
    metadata = _body(context)["metadata"]
    assert metadata["category"] == expected["category"]
    assert metadata["location"] == expected["location"]
    assert metadata["items"] == split_items(expected["items"])
    assert (metadata["content_time"] or "") == expected["content_time"].strip()


@then(parsers.parse('回應的所屬資料夾為 "{name}"'))
def 回應所屬資料夾為(context, name):
    assert _body(context)["folder"]["name"] == name


@then("回應的建議資料夾如下")
def 回應建議資料夾為(context, datatable):
    expected = first_row(datatable)
    suggested = _body(context)["suggested_folder"]
    assert suggested["name"] == expected["name"]
    # 規則：建議一定是清單裡的其中一筆（design1.md §7.1）
    assert suggested["name"] in [f["name"] for f in _body(context)["folders"]]


@then("回應的資料夾清單包含以下名稱")
def 回應資料夾清單包含(context, datatable):
    回應清單 = [f["name"] for f in _body(context)["folders"]]
    for name in column(datatable, "name"):
        assert name in 回應清單, f"回應的資料夾清單少了「{name}」：{回應清單}"


@then("回應包含這張照片的縮圖網址")
def 回應包含縮圖網址(context):
    body = _body(context)
    assert body["thumbnail_url"] == f"/photos/{body['id']}/thumbnail"
