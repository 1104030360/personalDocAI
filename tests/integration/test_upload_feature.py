"""把 docs/spec/features/上傳照片.feature 當測試跑（15 條有例子的 Rule）。

2026-08-20 規格改版後：上傳當下 category 一律「未分類」，
VLM 給的類別只出現在回應的 suggested_folder，不落庫。
2026-08-21 追加 PDF Rule（design3.md D7）：PDF 一頁存成一張照片。
2026-08-22 追加實體／待辦建議 Rule（design3.md D8／D12／D13）：只出現在回應，不落庫。
2026-08-25 增量五（Phase 62）：上傳改 202、建議改落庫（design5.md D7／D16）。
規格檔唯讀（Phase 72 才准改），所以 binder 的 When 步驟自己把任務跑完，
「回應的…」系列步驟改成對資料庫驗證——規格描述的是使用者看得到的最終結果。
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
from tests.conftest import (
    _收件箱照片ids,
    first_row,
    split_items,
    目前的任務清單,
    跑完任務,
)
from tests.fakes import (
    FakeVLM,
    make_pdf_bytes,
    make_png_bytes,
    understanding_for_text,
)

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
        "photo_ids": [],  # 這次任務跑完之後新進收件箱的照片
        "job": None,  # 跑完之後的任務狀態（成功時是 None＝已被刪掉）
    }


@pytest.fixture(autouse=True)
def wire_feature_clock(wire_fake_ai, context):
    """把「現在時間」改接到 context——Given 步驟改 context["now"] 即時生效。

    顯式依賴 conftest 的 wire_fake_ai（假 AI 已接好、測後統一 clear()），
    保證本 fixture 在它之後執行，get_now 的覆寫以這裡為準。
    """
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield


def _upload(context, client, filename="photo.png", content_type="image/png", payload=PNG_BYTES):
    """When 步驟：收下檔案（202）**並且把那個任務跑完**。

    增量五把上傳拆成兩段：HTTP 只收下（202），worker 才真的入庫。
    規格檔（唯讀，Phase 72 才准改）寫的是「上傳照片後，系統儲存……」——
    描述的是使用者看得到的最終結果，所以 binder 這一層要把兩段接起來，
    Then 才看得到照片。少了「跑完任務」那一步，每一條 Then 都會變成
    「系統儲存的照片數量為 0」（design5.md §9 最後一段）。

    415 那一條 Rule 走另一條路：連 202 都拿不到，自然也沒有任務可跑。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(context["understanding"])

    context["photo_ids"] = []
    context["job"] = None
    照片數_收檔前 = photo_repository.count_photos()
    response = client.post("/photos", files={"file": (filename, payload, content_type)})
    context["response"] = response
    if response.status_code != 202:
        return  # 格式不對（415）：Then「操作失敗」會驗它

    # design5.md §9 的第 2 步：202 只是「收下了」，這一刻 photo 表一列都沒有多
    assert photo_repository.count_photos() == 照片數_收檔前

    job_id = response.json()["job_id"]
    前 = set(_收件箱照片ids())
    跑完任務(job_id)
    context["job"] = 目前的任務清單().get(job_id)
    context["photo_ids"] = sorted(i for i in _收件箱照片ids() if i not in 前)


def _photo_id(context) -> int:
    """這個例子剛剛存進去的那一張照片 id（規格的例子都是單圖或 PDF 的第一頁）。"""
    assert context["response"].status_code == 202, context["response"].text
    assert context["photo_ids"], f"任務跑完了卻沒有任何照片進收件箱——job 狀態：{context['job']}"
    return context["photo_ids"][0]


def _stored_photo(context) -> dict:
    row = photo_repository.fetch_photo(_photo_id(context))
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


@given("系統中有底下實體")
def 建立實體(datatable):
    header, *rows = datatable
    for row in rows:
        data = dict(zip(header, row))
        photo_repository.create_entity(data["name"], data.get("description") or "")


# ------------------------------- When ------------------------------
@when("使用者上傳一個非圖片格式的檔案")
def 上傳非圖片檔(context, client):
    _upload(
        context,
        client,
        filename="note.txt",
        content_type="text/plain",
        payload="這不是圖片".encode(),
    )


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


_TARGET_TEXT = "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"


@when(parsers.parse('使用者上傳一張照片，VLM 建議的實體為 "{name}"'))
def 上傳照片並指定建議實體(context, client, name):
    context["understanding"] = understanding_for_text(_TARGET_TEXT).model_copy(
        update={"entity": name}
    )
    _upload(context, client)


@when(parsers.parse('使用者上傳一張照片，VLM 建議的待辦標題為 "{title}"，到期日為 "{due}"'))
def 上傳照片並指定建議待辦(context, client, title, due):
    context["understanding"] = understanding_for_text(_TARGET_TEXT).model_copy(
        update={"task_title": title, "task_due": due}
    )
    _upload(context, client)


@when("使用者上傳照片")
def 上傳照片(context, client):
    _upload(context, client)


@when(parsers.parse('使用者上傳一份 {pages:d} 頁的 PDF 檔案，VLM 理解每一頁的內容為 "{text}"'))
def 上傳PDF並指定每頁理解內容(context, client, pages, text):
    """PDF 一頁一張照片（design3.md D7）：假 VLM 對每一頁都回同一個理解結果。"""
    context["understanding"] = understanding_for_text(text)
    _upload(
        context,
        client,
        filename="scan.pdf",
        content_type="application/pdf",
        payload=make_pdf_bytes(pages),
    )


# ------------------------------- Then ------------------------------
@then("操作失敗")
def 操作失敗(context):
    """規格的「操作失敗」在增量五有兩種長相（規格檔 Phase 72 才准改）：

    - 非圖片格式：HTTP 當場 415——維持原本的斷言。
    - VLM 看不懂：HTTP 是 202（受理成功），失敗發生在 worker——
      改驗「任務最後是 failed、而且沒有任何照片進收件箱」。

    Phase 72 會把「VLM 無法理解」那條 Example 的 `Then 操作失敗` 從規格裡刪掉
    （202 不是失敗，失敗的是背景分析），到時 202 這個分支自然沒人再走；
    415 那條 Example 仍然用本 step，所以 Phase 72 也**不會**刪這個函式
    （phase-72 §4.3 已對齊這裡的寫法）。
    """
    response = context["response"]
    if response.status_code == 202:
        assert context["job"] is not None and context["job"]["status"] == "failed", (
            f"202 之後規格說的「操作失敗」＝任務失敗，實際 job：{context['job']}"
        )
        assert context["photo_ids"] == [], "失敗的上傳不可以有照片進收件箱"
    else:
        assert response.status_code >= 400, response.text


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
    embedding = photo_repository.fetch_embedding(_photo_id(context))
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
    """規格說「回應包含識別碼」；增量五之後識別碼要等分析完才存在。

    Phase 72 會把這句規格改掉，在那之前 binder 用「存進去的那一張的 id」對應它。
    """
    assert _photo_id(context) > 0


@then(parsers.parse('回應的文字描述為 "{text}"'))
def 回應文字描述為(context, text):
    assert _stored_photo(context)["text"] == text


@then("回應的 metadata 欄位如下")
def 回應metadata為(context, datatable):
    expected = first_row(datatable)
    row = _stored_photo(context)
    assert row["category"] == expected["category"]
    assert row["location"] == expected["location"]
    assert row["items"] == split_items(expected["items"])
    stored_time = row["content_time"].isoformat() if row["content_time"] else ""
    assert stored_time == expected["content_time"].strip()


@then(parsers.parse('回應的所屬資料夾為 "{name}"'))
def 回應所屬資料夾為(context, name):
    folder = photo_repository.get_folder(_stored_photo(context)["folder_id"])
    assert folder is not None, "photo.folder_id 指向一個不存在的資料夾"
    assert folder["name"] == name


@then("回應的建議資料夾如下")
def 回應建議資料夾為(context, datatable):
    expected = first_row(datatable)
    # 建議是收件箱時存 NULL（Phase 35 的規則），規格的例子則寫「未分類」
    assert (_stored_photo(context)["suggested_category"] or "未分類") == expected["name"]


@then("回應的資料夾清單包含以下名稱")
def 回應資料夾清單包含(context, datatable):
    清單 = [f["name"] for f in photo_repository.list_folders()]
    for name in column(datatable, "name"):
        assert name in 清單, f"資料夾清單少了「{name}」：{清單}"


@then("回應包含這張照片的縮圖網址")
def 回應包含縮圖網址(context):
    """縮圖真的存了；網址是 GET /folders/{id} 換算出來的，不再由上傳回應提供。"""
    assert _stored_photo(context)["thumbnail_path"]


@then(parsers.parse("回應包含 {count:d} 筆已儲存的照片"))
def 回應包含幾筆照片(context, count):
    """PDF 一頁一張照片：跑完任務之後新進收件箱的張數就是成功頁數。"""
    assert len(context["photo_ids"]) == count


@then("回應的建議實體如下")
def 回應建議實體為(context, datatable):
    expected = first_row(datatable)
    suggested = _stored_photo(context)["suggested_entity"]
    assert suggested is not None, "照片沒有落庫任何實體建議"
    assert suggested == expected["name"]
    assert suggested in [e["name"] for e in photo_repository.list_entities()]


@then("回應的實體清單包含以下名稱")
def 回應實體清單包含(context, datatable):
    清單 = [e["name"] for e in photo_repository.list_entities()]
    for name in column(datatable, "name"):
        assert name in 清單, f"實體清單少了「{name}」：{清單}"


@then("回應沒有建議實體")
def 回應沒有建議實體(context):
    assert _stored_photo(context)["suggested_entity"] is None


@then(parsers.parse("該照片釘上的實體數量為 {count:d}"))
def 照片釘上的實體數量為(context, count):
    pinned = photo_repository.list_photo_entities(_photo_id(context))
    assert len(pinned) == count


@then("回應的建議待辦如下")
def 回應建議待辦為(context, datatable):
    expected = first_row(datatable)
    row = _stored_photo(context)
    assert row["suggested_task_title"] is not None, "照片沒有落庫任何待辦建議"
    assert row["suggested_task_title"] == expected["title"]
    stored_due = row["suggested_task_due"].isoformat() if row["suggested_task_due"] else ""
    assert stored_due == expected["due"].strip()


@then("回應沒有建議待辦")
def 回應沒有建議待辦(context):
    assert _stored_photo(context)["suggested_task_title"] is None


@then("該照片沒有待辦")
def 該照片沒有待辦(context):
    assert photo_repository.get_task_by_photo(_photo_id(context)) is None
