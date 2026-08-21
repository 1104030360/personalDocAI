"""上傳存檔與讀圖端點的整合測試（design1.md §6、§7.4、§12）。

檔案一律寫在 conftest 的 isolated_data_dir 指定的暫存目錄，不會碰到專案的 data/。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, make_jpeg_bytes, make_png_bytes

TARGET_RECEIPT = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據", location="Target",
    items=["可樂", "洋芋片"], content_time="2026-08-10",
)


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _upload(client, payload=None, content_type="image/png", filename="a.png"):
    """上傳一張看得懂的照片。payload 預設是 Pillow 現產的真 PNG。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)
    if payload is None:
        payload = make_png_bytes(1200, 600)
    return client.post("/photos", files={"file": (filename, payload, content_type)})


def test_上傳後原圖與縮圖都寫進DATA_DIR(client):
    image_bytes = make_png_bytes(1200, 600)

    response = _upload(client, payload=image_bytes)

    assert response.status_code == 201
    photo_id = response.json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    # 資料庫存的是以 data/ 開頭的相對路徑（design1.md §6）
    assert row["original_path"] == f"data/photos/{photo_id}.png"
    assert row["thumbnail_path"] == f"data/thumbs/{photo_id}.png"
    assert row["content_type"] == "image/png"
    # 檔案真的在（換算後的實際位置在暫存目錄底下）
    原圖 = storage_service.absolute_path(row["original_path"])
    縮圖 = storage_service.absolute_path(row["thumbnail_path"])
    assert 原圖.is_file() and 縮圖.is_file()
    # 原圖位元組與上傳的一模一樣；縮圖被縮到長邊 512
    assert 原圖.read_bytes() == image_bytes
    with Image.open(io.BytesIO(縮圖.read_bytes())) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_jpeg上傳的副檔名是jpg(client):
    response = _upload(
        client, payload=make_jpeg_bytes(), content_type="image/jpeg", filename="a.jpg"
    )

    assert response.status_code == 201
    row = photo_repository.fetch_photo(response.json()["id"])
    assert row["original_path"].endswith(".jpg")
    assert row["thumbnail_path"].endswith(".jpg")
    assert row["content_type"] == "image/jpeg"


def test_讀縮圖端點回200且回的真的是圖片(client):
    photo_id = _upload(client).json()["id"]

    response = client.get(f"/photos/{photo_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_讀原圖端點回的位元組與上傳的完全相同(client):
    image_bytes = make_png_bytes(1200, 600)
    photo_id = _upload(client, payload=image_bytes).json()["id"]

    response = client.get(f"/photos/{photo_id}/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == image_bytes


def test_照片不存在讀圖回404(client):
    assert client.get("/photos/9999/thumbnail").status_code == 404
    assert client.get("/photos/9999/image").status_code == 404


def test_舊式資料沒有路徑讀圖回404(client):
    """design1.md §10：遷移進來的舊照片路徑是 NULL，讀圖 404，前端顯示占位。

    這裡直接用 repository 插一列（不走上傳端點），模擬遷移後的舊資料。
    """
    photo_id = photo_repository.insert_photo(
        text="遷移進來的舊照片", category="收據", location="Target",
        items=["可樂"], content_time=None,
        embedding=FakeEmbeddings().embed_query("收據"),
    )["id"]

    row = photo_repository.fetch_photo(photo_id)
    assert row["original_path"] is None
    assert row["thumbnail_path"] is None
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    assert client.get(f"/photos/{photo_id}/image").status_code == 404


def test_檔案被刪掉後讀圖也回404(client):
    photo_id = _upload(client).json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    storage_service.absolute_path(row["thumbnail_path"]).unlink()

    # 資料庫有路徑、磁碟沒檔案 → 一樣 404，不可以回 500
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    # 原圖還在，所以原圖端點仍然 200
    assert client.get(f"/photos/{photo_id}/image").status_code == 200


def test_寫檔失敗時檔案與資料列都不留(不擲出例外的client, monkeypatch):
    """design.md 的不吞錯原則：失敗回 500，而且不可以留下半筆資料或孤兒檔案。"""
    def 一定失敗(photo_id, image_bytes, content_type):
        raise RuntimeError("磁碟壞了")

    monkeypatch.setattr(storage_service, "make_thumbnail", 一定失敗)

    response = _upload(不擲出例外的client)

    assert response.status_code == 500
    assert photo_repository.count_photos() == 0, "失敗時不可以留下半筆資料"
    # 縮圖之前已經寫出去的原圖也要被清掉
    assert not list((config.DATA_DIR / "photos").glob("*")), "不可以留下孤兒檔案"


def test_更新路徑失敗時檔案與資料列都不留(不擲出例外的client, monkeypatch):
    """最後一步（UPDATE）失敗也要清乾淨——兩個檔案都已經寫出去了。"""
    def 一定失敗(photo_id, **kwargs):
        raise RuntimeError("資料庫斷線")

    monkeypatch.setattr(photo_repository, "update_photo_paths", 一定失敗)

    response = _upload(不擲出例外的client)

    assert response.status_code == 500
    assert photo_repository.count_photos() == 0
    assert not list((config.DATA_DIR / "photos").glob("*"))
    assert not list((config.DATA_DIR / "thumbs").glob("*"))


def test_415完全不寫檔(client):
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415
    # 連 data/ 這個資料夾都不該被建出來
    assert not config.DATA_DIR.exists()


def test_422完全不寫檔(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 422
    assert photo_repository.count_photos() == 0
    assert not config.DATA_DIR.exists()
