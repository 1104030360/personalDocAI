"""上傳照片的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel, Field


class PhotoMetadata(BaseModel):
    """照片的結構化 metadata：固定四個欄位，不多不少。

    欄位值使用照片內容本身的語言（中文收據就是中文、英文收據就是英文），
    系統不做翻譯——跨語言的搜尋交給多語 embedding 處理（design.md §8.3）。
    """

    category: str | None = None       # 類別，例如「收據」或 "Receipt"
    location: str | None = None       # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)  # 物品清單
    content_time: str | None = None   # 內容時間，ISO 日期字串，例如「2026-08-10」


class UploadResponse(BaseModel):
    """POST /photos 成功時的回應（HTTP 201）。"""

    id: int
    text: str
    metadata: PhotoMetadata
