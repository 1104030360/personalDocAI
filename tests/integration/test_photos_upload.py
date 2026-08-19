"""POST /photos 格式檢查的整合測試（TestClient，in-process 不經網路）。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U1「上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗」
  Example「非圖片格式的檔案上傳失敗」：
    When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗 And 系統儲存的照片數量為 0
"""

import base64

from fastapi.testclient import TestClient

from app.main import app
from app.repositories import photo_repository as repo

client = TestClient(app)

# 一張合法的 1×1 PNG（與步驟 3 的 /tmp/sample.png 相同內容，70 bytes）
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_upload_non_image_returns_415_with_message():
    # When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗（415＋規格訊息）
    resp = client.post(
        # 計畫原文寫 b"這不是圖片"，但 Python 的 bytes literal 只允許 ASCII，
        # 會 SyntaxError；改用 .encode() 產生同樣的 UTF-8 位元組，語意不變。
        "/photos",
        files={"file": ("not_image.txt", "這不是圖片".encode(), "text/plain")},
    )
    assert resp.status_code == 415
    assert resp.json() == {"detail": "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"}


def test_upload_non_image_stores_nothing():
    # And 系統儲存的照片數量為 0（U1 第二句：不進行任何後續處理）
    client.post("/photos", files={"file": ("not_image.txt", b"x", "text/plain")})
    assert repo.count_photos() == 0


def test_upload_octet_stream_returns_415():
    # content_type 不在允許清單（未知二進位型別）也一律 415
    resp = client.post(
        "/photos",
        files={"file": ("mystery.bin", b"\x00\x01", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_upload_png_returns_201_placeholder():
    # PNG 通過格式檢查；Phase 6 之前先回佔位回應
    resp = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")})
    assert resp.status_code == 201
    assert resp.json() == {
        "accepted": True,
        "content_type": "image/png",
        "size": len(PNG_BYTES),
    }


def test_upload_jpeg_returns_201():
    # JPEG 也通過（本 phase 只驗 content_type，不驗檔案內容）
    resp = client.post(
        "/photos", files={"file": ("sample.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")}
    )
    assert resp.status_code == 201


def test_upload_missing_file_returns_422():
    # 沒夾帶檔案 → FastAPI 框架既有的 422，不另外發明行為
    resp = client.post("/photos")
    assert resp.status_code == 422


def test_openapi_has_photos_endpoint():
    # router 真的掛上 main.py（等效驗收第 6 項的 /docs 檢查）
    paths = client.get("/openapi.json").json()["paths"]
    assert "/photos" in paths and "post" in paths["/photos"]
