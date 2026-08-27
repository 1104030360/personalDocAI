"""照片檔案的落地：寫原圖、產縮圖、換算路徑、失敗清理。

分層：本模組只做檔案操作，不碰資料庫、不碰 HTTP。
「什麼時候呼叫、失敗了怎麼收拾」由 api/routers/photos.py 決定（Phase 19）。

路徑約定（design1.md §6）：
  資料庫存的一律是「以 data/ 開頭的相對路徑」，例如 data/photos/1.jpg。
  實際落地位置＝把開頭那段 data 換成 config.DATA_DIR。
  這樣資料庫裡的值不隨執行環境改變（正式在專案下、pytest 在暫存目錄）。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.core import config

# 資料庫相對路徑固定的第一段；換算實際位置時由 config.DATA_DIR 取代它
DB_ROOT = "data"
# 兩個子資料夾
ORIGINAL_DIR = "photos"
THUMBNAIL_DIR = "thumbs"

# 縮圖長邊上限（px）。等比縮小、絕不放大——design1.md 沒有多尺寸需求，就這一種
THUMBNAIL_MAX_SIDE = 512

# content_type → 副檔名。只有圖片會走到這裡：PDF 雖然可以上傳，
# 但在 router 就已經被 pdf_service 逐頁換成 image/png（design3.md D7）
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}
# 副檔名 → Pillow 的格式代號（存檔時要指定，不能靠副檔名猜）
PIL_FORMATS = {"jpg": "JPEG", "png": "PNG"}


def _ext(content_type: str) -> str:
    """image/jpeg → "jpg"、image/png → "png"。

    清單外的 content_type 早在 router 的格式檢查（415）就被擋掉了；
    真的走到這裡代表有 bug，讓 KeyError 直接炸出來，不要默默給預設值。
    """
    return EXTENSIONS[content_type]


def absolute_path(rel_path: str) -> Path:
    """把資料庫存的相對路徑換算成實際檔案位置。

    "data/photos/1.jpg" → config.DATA_DIR / "photos" / "1.jpg"

    每次呼叫都重新讀 config.DATA_DIR（不在 import 時定死），
    測試才能用 monkeypatch 把它指到暫存目錄。
    """
    parts = Path(rel_path).parts
    if parts and parts[0] == DB_ROOT:
        parts = parts[1:]
    return Path(config.DATA_DIR).joinpath(*parts)


def _prepare(photo_id: int, content_type: str, sub_dir: str) -> tuple[str, Path]:
    """算出相對路徑與實際位置，並把資料夾先建好。"""
    rel_path = f"{DB_ROOT}/{sub_dir}/{photo_id}.{_ext(content_type)}"
    target = absolute_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return rel_path, target


def save_original(photo_id: int, image_bytes: bytes, content_type: str) -> str:
    """把原圖原封不動寫成檔案，回傳要存進資料庫的相對路徑。

    不轉檔、不壓縮、不改尺寸——使用者上傳什麼就存什麼。
    """
    rel_path, target = _prepare(photo_id, content_type, ORIGINAL_DIR)
    target.write_bytes(image_bytes)
    return rel_path


def make_thumbnail(photo_id: int, image_bytes: bytes, content_type: str) -> str:
    """產生縮圖（長邊最多 512px、等比、不放大），回傳相對路徑。

    Image.thumbnail() 是「就地修改」：它直接把圖改小，不回傳新物件；
    而且本來就小於上限的圖不會被放大，所以小圖原樣保留。
    """
    rel_path, target = _prepare(photo_id, content_type, THUMBNAIL_DIR)

    # BytesIO＝把手上的 bytes 包成「假裝是檔案」的物件，直接餵給 Pillow
    with Image.open(io.BytesIO(image_bytes)) as image:
        thumbnail = image.copy()  # 複製一份，離開 with 之後才還能繼續用

    thumbnail.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE))

    image_format = PIL_FORMATS[_ext(content_type)]
    if image_format == "JPEG" and thumbnail.mode != "RGB":
        # JPEG 不支援透明度：帶 A（透明）或調色盤模式的圖要先轉成 RGB 才存得下去
        thumbnail = thumbnail.convert("RGB")

    thumbnail.save(target, format=image_format)
    return rel_path


def remove_if_exists(rel_path: str | None) -> None:
    """刪掉一個檔案；路徑是 None／空字串／檔案本來就不在，都當作成功。

    上傳流程失敗時要把已經寫出去的檔案清乾淨（Phase 19），
    那個情境下「還沒產生路徑」與「檔案已不在」都是正常狀況，不可以再爆一次錯。
    """
    if not rel_path:
        return
    absolute_path(rel_path).unlink(missing_ok=True)
