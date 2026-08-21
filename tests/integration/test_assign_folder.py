"""PATCH /photos/{id}/folder 的整合測試（design1.md §7.2、§7.3、§13）。

涵蓋：採用現有資料夾、自建新資料夾、四種錯誤碼（404×2、409、422）。
"""

from __future__ import annotations

import json

import pytest

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.indexing_service import build_document, embed_document
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes

# text 裡刻意不出現任何資料夾名稱：
# 假向量只認得詞表裡的詞，text 若已經含「收據」兩個字，
# 歸類前後算出來的向量會一模一樣，「有沒有重算」就驗不出來了。
超市照片 = PhotoUnderstanding(
    understood=True,
    text="超市購物的照片",
    category="收據",          # VLM 的建議（上傳時不會落庫，只出現在 suggested_folder）
    location="Costco",
    items=["咖啡", "牛奶"],
    content_time=None,
)


@pytest.fixture
def 已上傳的照片(client):
    """先走一次真正的上傳流程，拿到一張躺在「未分類」的照片。

    回傳的是 201 的完整回應內容（含 folders 清單，後面挑 id 要用）。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(超市照片)
    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["metadata"]["category"] == "未分類", "前置條件：上傳後應該在未分類"
    return body


def _folder_id(上傳回應: dict, name: str) -> int:
    """從上傳回應的資料夾清單裡挑出某個資料夾的 id。"""
    return next(f["id"] for f in 上傳回應["folders"] if f["name"] == name)


def _stored_embedding(photo_id: int) -> list[float]:
    return json.loads(photo_repository.fetch_embedding(photo_id))


def _expected_embedding(category: str) -> list[float]:
    """如果向量真的用這個類別重算過，應該長這樣。"""
    document = build_document(
        text="超市購物的照片",
        category=category,
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
    return embed_document(FakeEmbeddings(), document)


def _max_diff(a: list[float], b: list[float]) -> float:
    """兩條向量差最多的那一格差多少。"""
    return max(abs(x - y) for x, y in zip(a, b))


def test_採用現有資料夾後分類與向量都更新(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]
    收據id = _folder_id(已上傳的照片, "收據")
    上傳當下的向量 = _stored_embedding(photo_id)

    response = client.patch(f"/photos/{photo_id}/folder", json={"folder_id": 收據id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == photo_id
    assert body["folder"]["id"] == 收據id
    assert body["folder"]["name"] == "收據"
    assert body["metadata"]["category"] == "收據"
    # 另外三個 metadata 欄位不受歸類影響
    assert body["metadata"]["location"] == "Costco"
    assert body["metadata"]["items"] == ["咖啡", "牛奶"]
    assert body["metadata"]["content_time"] is None

    # 資料庫：category 與 folder_id 一起改（design1.md §6 的雙寫規則）
    row = photo_repository.fetch_photo(photo_id)
    assert row["category"] == "收據"
    assert row["folder_id"] == 收據id

    # 向量真的用新類別重算過（pgvector 以 float4 儲存，取 1e-6 容差）
    重算後的向量 = _stored_embedding(photo_id)
    assert _max_diff(重算後的向量, _expected_embedding("收據")) < 1e-6
    # 而且和上傳當下（未分類版本）的向量不同——沒重算的話這一行會失敗
    assert _max_diff(重算後的向量, 上傳當下的向量) > 1e-3


def test_自建資料夾後照片歸它新資料夾也進入清單(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]

    response = client.patch(
        f"/photos/{photo_id}/folder",
        json={"name": "專案X", "description": "跟課程作業有關的照片"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["folder"]["name"] == "專案X"
    assert body["folder"]["description"] == "跟課程作業有關的照片"
    assert body["metadata"]["category"] == "專案X"
    assert photo_repository.fetch_photo(photo_id)["folder_id"] == body["folder"]["id"]

    # 自建的資料夾和預設六個進同一張表（design1.md §5）
    assert "專案X" in [f["name"] for f in photo_repository.list_folders()]

    # 下次上傳的回應也看得到它——也就是說下一次 VLM 的 prompt 也會看到
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(超市照片)
    第二次上傳 = client.post(
        "/photos", files={"file": ("b.png", make_png_bytes(), "image/png")}
    )
    assert 第二次上傳.status_code == 201
    assert "專案X" in [f["name"] for f in 第二次上傳.json()["folders"]]


def test_照片不存在回404(client, 已上傳的照片):
    """先檢查照片、再檢查資料夾——所以就算 folder_id 是對的也回「找不到照片」。"""
    收據id = _folder_id(已上傳的照片, "收據")

    response = client.patch("/photos/999/folder", json={"folder_id": 收據id})

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"


def test_資料夾不存在回404(client, 已上傳的照片):
    response = client.patch(
        f"/photos/{已上傳的照片['id']}/folder", json={"folder_id": 999}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到資料夾"
    # 沒有偷偷改到照片
    assert photo_repository.fetch_photo(已上傳的照片["id"])["category"] == "未分類"


def test_自建名稱與現有資料夾重複回409(client, 已上傳的照片):
    """「收據」是預設資料夾之一，不可以被自建流程蓋掉（design1.md §12）。

    大小寫不敏感的比對由 Phase 16 的 find_folder_by_name() 負責，
    該函式的大小寫測試在 tests/integration/test_folder_repository.py，這裡不重複。
    """
    原本的資料夾數 = len(photo_repository.list_folders())

    response = client.patch(
        f"/photos/{已上傳的照片['id']}/folder",
        json={"name": "收據", "description": "我自己的收據夾"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "資料夾名稱已存在"
    # 沒有多建一個，也沒有改到原本那個的 description
    assert len(photo_repository.list_folders()) == 原本的資料夾數
    assert photo_repository.find_folder_by_name("收據")["description"] != "我自己的收據夾"


# parametrize：同一個測試跑三組不合法的 body，pytest 會算成 3 個測試
@pytest.mark.parametrize(
    "body",
    [
        {},                                 # 兩個都不給
        {"folder_id": 1, "name": "專案X"},   # 兩個都給
        {"name": "   "},                    # name 只有空白
    ],
)
def test_請求必須恰好給一個folder_id或name(client, 已上傳的照片, body):
    response = client.patch(f"/photos/{已上傳的照片['id']}/folder", json=body)

    assert response.status_code == 422
