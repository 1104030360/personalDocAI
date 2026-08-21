"""資料夾瀏覽的 API 資料格式（Pydantic 模型）。

只給 GET /folders 與 GET /folders/{id} 兩個唯讀端點用；
上傳與歸類的模型在 app/schemas/photo.py，不要混在一起。
"""

from datetime import datetime

from pydantic import BaseModel


class FolderWithCount(BaseModel):
    """一個資料夾＋裡面有幾張照片。

    photo_count 由 repository 的 LEFT JOIN 算出來（空資料夾也會是 0，不會消失）。
    """

    id: int
    name: str
    description: str
    is_inbox: bool          # 只有系統收件箱「未分類」是 true
    photo_count: int


class PhotoSummary(BaseModel):
    """縮圖牆上一張照片要顯示的資訊。

    thumbnail_url 是「網址」不是硬碟路徑：資料庫的 thumbnail_path 有值時
    換算成 /photos/{id}/thumbnail（Phase 19 的讀圖端點）；舊資料沒有路徑時
    是 None（JSON 的 null），前端顯示灰底占位（design1.md §10）。
    """

    id: int
    thumbnail_url: str | None
    text: str
    uploaded_at: datetime   # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00


class FolderDetailResponse(BaseModel):
    """GET /folders/{id} 的回應：資料夾本身 ＋ 裡面的照片摘要（新的在前）。"""

    folder: FolderWithCount
    photos: list[PhotoSummary]
