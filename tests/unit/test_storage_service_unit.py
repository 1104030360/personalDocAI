"""storage_service 的單元測試：真的寫檔案，但只寫到 tmp_path；不碰資料庫、不碰網路。

design1.md §6：原圖 data/photos/{id}.jpg|png、縮圖 data/thumbs/{id}.jpg|png，
資料庫只存以 data/ 開頭的相對路徑。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core import config
from app.services import storage_service
from tests.fakes import make_jpeg_bytes, make_png_bytes


def _open(path):
    """把寫出去的檔案讀回來、用 Pillow 打開，確認它真的是一張圖。"""
    return Image.open(io.BytesIO(path.read_bytes()))


def test_測試期間DATA_DIR指向暫存目錄(tmp_path):
    """安全網本身也要有測試：pytest 不可以寫進專案的 data/。"""
    assert config.DATA_DIR == tmp_path / "data"


def test_副檔名對照表():
    assert storage_service._ext("image/jpeg") == "jpg"
    assert storage_service._ext("image/png") == "png"


def test_不支援的content_type直接爆錯():
    """router 早就在格式檢查擋掉了；真的走到這裡代表有 bug，不可以默默給預設值。"""
    with pytest.raises(KeyError):
        storage_service._ext("image/gif")


def test_存原圖回相對路徑且檔案內容一模一樣():
    image_bytes = make_png_bytes()

    rel_path = storage_service.save_original(1, image_bytes, "image/png")

    # 回的是「以 data/ 開頭的相對路徑」——這個字串會原封不動存進資料庫
    assert rel_path == "data/photos/1.png"
    saved = storage_service.absolute_path(rel_path)
    assert saved.is_file()
    # 原圖不轉檔、不壓縮：位元組要與上傳的完全相同
    assert saved.read_bytes() == image_bytes


def test_jpeg存成jpg副檔名():
    rel_path = storage_service.save_original(7, make_jpeg_bytes(), "image/jpeg")

    assert rel_path == "data/photos/7.jpg"
    assert storage_service.absolute_path(rel_path).is_file()


def test_縮圖長邊縮到512且維持比例():
    image_bytes = make_png_bytes(1200, 600)

    rel_path = storage_service.make_thumbnail(3, image_bytes, "image/png")

    assert rel_path == "data/thumbs/3.png"
    with _open(storage_service.absolute_path(rel_path)) as thumbnail:
        # 長邊 1200 → 512，短邊按同一個比例 600 → 256（等比，不會被壓扁）
        assert thumbnail.size == (512, 256)


def test_比512小的圖不會被放大():
    """Image.thumbnail 只縮不放——小圖原樣保留，不要浪費空間去補像素。"""
    rel_path = storage_service.make_thumbnail(4, make_png_bytes(100, 50), "image/png")

    with _open(storage_service.absolute_path(rel_path)) as thumbnail:
        assert thumbnail.size == (100, 50)


def test_原圖與縮圖各自一個資料夾不會互相覆蓋():
    image_bytes = make_png_bytes(1200, 600)

    original = storage_service.save_original(9, image_bytes, "image/png")
    thumbnail = storage_service.make_thumbnail(9, image_bytes, "image/png")

    assert original == "data/photos/9.png"
    assert thumbnail == "data/thumbs/9.png"
    # 同一個 id、兩個檔案，內容不同（縮圖被縮小了）
    assert storage_service.absolute_path(original).read_bytes() != \
        storage_service.absolute_path(thumbnail).read_bytes()


def test_absolute_path把開頭的data換成DATA_DIR():
    assert storage_service.absolute_path("data/photos/1.png") == \
        config.DATA_DIR / "photos" / "1.png"
    assert storage_service.absolute_path("data/thumbs/1.png") == \
        config.DATA_DIR / "thumbs" / "1.png"


def test_remove_if_exists刪得掉也吃得下None與不存在的路徑():
    rel_path = storage_service.save_original(5, make_png_bytes(), "image/png")
    assert storage_service.absolute_path(rel_path).is_file()

    storage_service.remove_if_exists(rel_path)
    assert not storage_service.absolute_path(rel_path).exists()

    # 上傳失敗清理時，路徑可能根本還沒產生（None）或檔案已經不在——都不可以爆錯
    storage_service.remove_if_exists(None)
    storage_service.remove_if_exists("")
    storage_service.remove_if_exists(rel_path)
