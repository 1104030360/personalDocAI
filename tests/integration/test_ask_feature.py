"""把 docs/spec/features/自然語言詢問.feature 當測試跑（5 條已落地 Rule）。

design3.md 追加的實體別針／待辦兩路（@未實作）等 Phase 34 落地後再摘標驗收。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_now
from app.main import app
from app.repositories import photo_repository
from app.services import indexing_service
from tests.conftest import split_items
from tests.fakes import FakeEmbeddings

# 直接掛上規格原檔——不複製、不改寫（路徑相對於本檔所在資料夾 tests/integration/）
scenarios("../../docs/spec/features/自然語言詢問.feature")

# 規格沒有指定「現在時間」的例子一律用這個固定時間，
# 測試才不會因為今天是哪一天而時好時壞。
DEFAULT_NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture
def context() -> dict:
    return {
        "now": DEFAULT_NOW,
        "id_map": {},        # 規格表格裡的 id → 資料庫實際的 id
        "response": None,
    }


@pytest.fixture(autouse=True)
def wire_ask_fakes(wire_fake_ai, context):
    """把「現在時間」改接到 context——Given 步驟改 context["now"] 即時生效。

    其餘假件（router／answerer／embedding）由 conftest 的 wire_fake_ai 統一接管，
    這裡不重複覆寫；顯式依賴它保證本 fixture 在它之後執行、測後由它統一 clear()。
    完全不需要 Ollama。
    """
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield


def _rows(datatable: list[list[str]]) -> list[dict[str, str]]:
    """把 Gherkin 表格轉成「每列一個字典」（第 0 列是欄位名）。"""
    header, *rows = datatable
    return [dict(zip(header, row)) for row in rows]


def _expected_ids(context, datatable) -> list[int]:
    """把規格表格裡的 id 轉成資料庫實際的 id。"""
    return sorted(context["id_map"][row["id"]] for row in _rows(datatable))


def _actual_ids(context) -> list[int]:
    return sorted(context["response"].json()["retrieved_photo_ids"])


# ------------------------------ Given ------------------------------
@given(parsers.parse('現在時間為 "{moment}"'))
def 設定現在時間(context, moment):
    context["now"] = datetime.strptime(moment, "%Y-%m-%d %H:%M")


@given("系統中有底下照片")
def 建立照片(context, datatable):
    embeddings = FakeEmbeddings()
    for row in _rows(datatable):
        content_time_text = row["content_time"].strip()
        content_time = date.fromisoformat(content_time_text) if content_time_text else None
        items = split_items(row["items"])

        # 向量的產生直接復用上傳路徑的 embed_document，讓一致性由程式保證
        document = indexing_service.build_document(
            text=row["text"],
            category=row["category"].strip() or None,
            location=row["location"].strip() or None,
            items=items,
            content_time=content_time.isoformat() if content_time else None,
        )
        stored = photo_repository.insert_photo(
            text=row["text"],
            category=row["category"].strip() or None,
            location=row["location"].strip() or None,
            items=items,
            content_time=content_time,
            embedding=indexing_service.embed_document(embeddings, document),
            uploaded_at=datetime.strptime(row["uploaded_at"], "%Y-%m-%d %H:%M"),
        )
        context["id_map"][row["id"]] = stored["id"]


@given("系統中沒有任何照片")
def 沒有任何照片():
    assert photo_repository.count_photos() == 0


@given(parsers.parse('照片 {spec_id} 釘上實體 "{name}"'))
def 照片釘上實體(context, spec_id, name):
    entity = photo_repository.find_entity_by_name(name)
    if entity is None:
        entity = photo_repository.create_entity(name, "")
    photo_repository.pin_entity(context["id_map"][spec_id], entity["id"])


@given("系統中有底下待辦")
def 建立待辦(context, datatable):
    for row in _rows(datatable):
        due_text = row["due"].strip()
        photo_repository.create_task(
            context["id_map"][row["photo_id"]],
            title=row["title"],
            due_date=date.fromisoformat(due_text) if due_text else None,
        )


# ------------------------------- When ------------------------------
@when(parsers.parse('使用者詢問 "{question}"'))
def 使用者詢問(context, client, question):
    context["response"] = client.post("/ask", json={"question": question})
    assert context["response"].status_code == 200, context["response"].text


# ------------------------------- Then ------------------------------
@then(parsers.parse('系統選擇的檢索方式為 "{mode}"'))
def 檢索方式為(context, mode):
    assert context["response"].json()["search_mode"] == mode


@then("時間過濾後的照片為底下照片")
def 時間過濾後的照片為(context, datatable):
    assert _actual_ids(context) == _expected_ids(context, datatable)


@then("回答依據的檢索結果為底下照片")
def 回答依據的檢索結果為(context, datatable):
    assert _actual_ids(context) == _expected_ids(context, datatable)


@then("使用者獲得查無相關照片的回覆")
def 獲得查無回覆(context):
    body = context["response"].json()
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


@then("回答提及底下物品")
def 回答提及物品(context, datatable):
    answer = context["response"].json()["answer"]
    for row in _rows(datatable):
        assert row["name"] in answer, f"回答裡沒有提到「{row['name']}」：{answer}"


@then("回答依據的待辦如下")
def 回答依據的待辦為(context, datatable):
    answer = context["response"].json()["answer"]
    for row in _rows(datatable):
        assert row["title"] in answer, f"回答裡沒有提到「{row['title']}」：{answer}"
