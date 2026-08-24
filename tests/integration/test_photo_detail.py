"""照片詳情端點 `GET /photos/{photo_id}`（Phase 38，design4.md §4.4）。

這支是**唯讀**端點：有這一列就 200，不管檔案還在不在磁碟上。
「路徑 NULL 或檔案不見了就 404」是 `/image` 與 `/thumbnail` 的規則
（那兩支真的要開檔案），跟這支只回 JSON 的端點無關——
圖載不出來由前端的 `<img>` onerror 降級成占位，不該讓整個彈窗變成 404。

對應 design4.md §9 錯誤表：第 1 列（沒這列 → 404）、第 2 列（路徑 NULL → 200 且
`image_url` 為 null）、第 3 列（路徑有值但檔案沒了 → JSON 仍 200）。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_photo_detail_fakes(wire_fake_ai):
    """預設 VLM「看得懂」；其餘假件與固定時鐘由 conftest 的 wire_fake_ai 接管。

    conftest 給 get_vlm 的預設是 FakeVLM()＝understood=False，直接上傳只會拿到 422。
    顯式依賴 wire_fake_ai 保證本 fixture 排在它之後執行、測後由它統一 clear()。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    yield


def 上傳一張(client) -> dict:
    """上傳一張成功的照片，回傳 201 的 JSON body。

    位元組一定要是**真圖**（make_png_bytes）：手打的 b"\\x89PNG…" 會在做縮圖那一步
    被 Pillow 擋下來。
    """
    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---- ① 回應的形狀 ----
def test_取得照片詳情回200且鍵恰好六個(client):
    """六個鍵不多不少：多回 embedding／folder／suggested_category 都會讓這顆紅。"""
    上傳 = 上傳一張(client)

    response = client.get(f"/photos/{上傳['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "text",
        "metadata",
        "thumbnail_url",
        "image_url",
        "uploaded_at",
    }
    assert body["id"] == 上傳["id"]
    assert body["text"] == 上傳["text"]


def test_metadata恰四鍵且值正確(client):
    """metadata 重用既有的 PhotoMetadata，所以必須與上傳 201 回應的那一份逐鍵相同。

    ⚠ 不要手寫 `category == "收據"`：上傳一律先進「未分類」，VLM 的建議不落庫
    （只出現在 201 的 suggested_folder）。拿「同一張照片的另一支端點」當期望值，
    才不會把「建議」誤當成「歸屬」。
    """
    上傳 = 上傳一張(client)

    詳情 = client.get(f"/photos/{上傳['id']}").json()

    assert set(詳情["metadata"]) == {
        "category", "location", "items", "content_time"
    }
    assert 詳情["metadata"] == 上傳["metadata"]
    assert 詳情["metadata"]["content_time"] == "2026-08-10", (
        "content_time 要外送 ISO 日期字串"
    )


# ---- ② design4 §9 第 1 列：沒這列 → 404 ----
def test_照片不存在回404(client):
    """detail 一定要一起驗。

    端點還沒寫之前，FastAPI 對「沒有這條路由」本來就回 404（detail 是 "Not Found"）——
    只驗狀態碼的話這顆從頭到尾都是綠的，等於根本沒測到東西。
    """
    response = client.get("/photos/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"


# ---- ③ design4 §9 第 2 列／D6：有列但路徑 NULL → 200 且網址為 null ----
def test_舊照片沒有原圖時image_url為null(client):
    """遷移進來的舊照片沒有原圖檔。不走上傳端點就沒經過存檔那一步，兩個路徑自然是 NULL。

    embedding 是 insert_photo 的必填參數（資料表 NOT NULL），用假件現算一條。
    """
    photo_id = photo_repository.insert_photo(
        text="遷移進來的舊照片，沒有原圖",
        category="未分類",
        location=None,
        items=[],
        content_time=None,
        embedding=FakeEmbeddings().embed_query("遷移進來的舊照片，沒有原圖"),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )["id"]

    response = client.get(f"/photos/{photo_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["image_url"] is None, "沒有原圖就不該給網址，前端靠 null 畫灰底占位"
    assert body["thumbnail_url"] is None, "縮圖同理"


# ---- ④ design4 §9 第 3 列：路徑有值但磁碟檔沒了 → JSON 仍 200 ----
def test_原圖被刪掉詳情仍回200(client):
    """這支只回 JSON，跟磁碟無關。

    「開圖檔」的 404 是 /photos/{id}/image 的事；把 _send_photo_file 那三個 404 條件
    照抄過來的話這顆會馬上紅——那正是本 phase 最容易寫錯的一條。
    """
    上傳 = 上傳一張(client)
    列 = photo_repository.fetch_photo(上傳["id"])
    storage_service.absolute_path(列["original_path"]).unlink()

    response = client.get(f"/photos/{上傳['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["image_url"] == f"/photos/{上傳['id']}/image", (
        "資料庫有路徑就照給網址；圖載不出來由前端 <img> 降級成占位"
    )


# ---- ⑤ 不外送硬碟路徑、不外送向量 ----
def test_回應不含硬碟路徑也不含向量(client):
    """第一句的 200 不能省。

    端點還沒寫時的 404 body（{"detail":"Not Found"}）也「找不到」下面那四個字串，
    少了 200 這一句整顆就是假綠。
    """
    上傳 = 上傳一張(client)

    response = client.get(f"/photos/{上傳['id']}")

    assert response.status_code == 200, response.text
    for 禁字 in ("data/", "original_path", "thumbnail_path", "embedding"):
        assert 禁字 not in response.text, f"回應不該外送 {禁字}"


# ---- ⑥ design4 §1.1 第 3 列：允許依 id 讀一張，仍不做列出全部 ----
def test_openapi有依id讀一張照片的端點且沒有列出全部(client):
    """design1 的「不做列出全部照片」禁令仍然有效，只是多開一扇「依 id 讀一張」的門。"""
    paths = client.get("/openapi.json").json()["paths"]

    assert "/photos/{photo_id}" in paths
    assert "get" in paths["/photos/{photo_id}"]
    assert "get" not in paths.get("/photos", {}), "不可以新增「列出全部照片」的端點"
