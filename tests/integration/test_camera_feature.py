"""把 docs/spec/features/無線鏡頭拍攝.feature 當測試跑（Phase 36）。

規格檔唯讀：這裡只負責把 Gherkin 的步驟接到真的 API 上，一個字都不改規格。
目前規格裡有 Example 的只有兩條 Rule（快門入庫、未按快門不存），
其餘四條標 #TODO＝還沒有例子可驗，pytest-bdd 自然不會產生任何 scenario。

「拍下一張照片」在自動化測試裡就是 `POST /camera/{token}/photos`：
真鏡頭與 WebRTC 畫面不進自動化測試（計畫校準 9），
但「快門按下去之後系統做了什麼」完全可以、也必須驗。
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import camera_session_service as sessions
from tests.conftest import _收件箱照片ids, 跑完任務
from tests.fakes import FakeVLM, make_jpeg_bytes, understanding_for_text

# 直接掛上規格原檔——不複製、不改寫（路徑相對於本檔所在資料夾 tests/integration/）
scenarios("../../docs/spec/features/無線鏡頭拍攝.feature")


@pytest.fixture(autouse=True)
def 乾淨的session(monkeypatch):
    """每個例子都從「沒有任何配對」開始（session 是模組層單例）。"""
    monkeypatch.setattr(sessions, "_session", None)


@pytest.fixture
def context() -> dict:
    """一個例子裡各步驟之間傳遞資料的小抽屜（沿用上傳規格 binder 的作法）。"""
    return {"token": None, "response": None, "photo_ids": []}


def _配對(context, client) -> str:
    """桌面開頁 → 建 session。已經配對過就沿用同一個 token。"""
    if context["token"] is None:
        response = client.post("/camera/session")
        assert response.status_code == 201, response.text
        context["token"] = response.json()["token"]
    return context["token"]


# ------------------------------ Given ------------------------------
@given("無線鏡頭已配對")
def 無線鏡頭已配對(context, client):
    _配對(context, client)


# ------------------------------- When ------------------------------
@when(parsers.parse('使用者以無線鏡頭拍下一張照片，VLM 理解其內容為 "{text}"'))
def 以無線鏡頭拍下一張照片(context, client, text):
    """按快門＝把當下那一幀擷成 JPEG 送上來（前端做的事，這裡直接給一張真的 JPEG）。

    增量五之後快門只「受理」（202），照片要等 worker 做完才存在。
    規格檔唯讀（Phase 72 才准改），所以 binder 這一層自己扮演 worker
    把任務跑完——不然每一條 Then 都會變成「照片數量為 0」。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(understanding_for_text(text))
    token = _配對(context, client)
    response = client.post(
        f"/camera/{token}/photos",
        files={"file": ("shot.jpg", make_jpeg_bytes(), "image/jpeg")},
    )
    context["response"] = response
    context["photo_ids"] = []
    assert response.status_code == 202, response.text

    前 = set(_收件箱照片ids())
    跑完任務(response.json()["job_id"])
    context["photo_ids"] = sorted(i for i in _收件箱照片ids() if i not in 前)


@when("畫面穩定且使用者未按快門")
def 畫面穩定但沒按快門(context, client):
    """刻意什麼都不做——這正是規格要驗的事（D5：快門是人按的，不自動拍）。

    即時預覽的畫面走 WebRTC 的視訊軌，一幀都不會經過上傳端點；
    沒有人按快門，資料庫就不該多出任何一列。
    """
    assert context["token"] is not None, "這個例子的 Given 應該已經配對過了"


# ------------------------------- Then ------------------------------
@then(parsers.parse("系統儲存的照片數量為 {count:d}"))
def 照片數量為(count):
    assert photo_repository.count_photos() == count


@then(parsers.parse('照片所屬資料夾為 "{name}"'))
def 照片所屬資料夾為(context, name):
    """驗 folder_id 真的掛到那個資料夾（不是只有 category 字串對）。"""
    folder = photo_repository.get_folder(_已存的照片(context)["folder_id"])
    assert folder is not None, "photo.folder_id 指向一個不存在的資料夾"
    assert folder["name"] == name


@then(parsers.parse('照片的文字描述為 "{text}"'))
def 照片文字描述為(context, text):
    assert _已存的照片(context)["text"] == text


def _已存的照片(context) -> dict:
    assert context["photo_ids"], (
        "任務跑完了卻沒有任何照片進收件箱——檢查 When 步驟有沒有呼叫 跑完任務()"
    )
    row = photo_repository.fetch_photo(context["photo_ids"][0])
    assert row is not None, "資料庫裡找不到剛剛拍的照片"
    return row
