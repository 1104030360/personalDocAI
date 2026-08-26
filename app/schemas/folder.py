"""資料夾瀏覽的 API 資料格式（Pydantic 模型）。

只給 GET /folders 與 GET /folders/{id} 兩個唯讀端點用；
上傳與歸類的模型在 app/schemas/photo.py，不要混在一起。
"""

from datetime import date, datetime

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

    欄位數的沿革：
      Phase 22 四鍵 → Phase 35 五鍵（+suggested_category）→ **Phase 61 八鍵**。

    後面三個是 design5.md D16 的「建議落庫」：上傳自 Phase 62 起回 202，
    建議不會再出現在任何回應裡，待決定頁只能從這支端點讀。
    三個都是**建議**，不是事實——照片實際釘了哪些實體要看 photo_entity，
    有沒有待辦要看 task 表。人在彈窗按下去，那兩張表才會有資料。
    舊照片三個都是 None，彈窗照舊只有②③④，這是預期行為。
    """

    id: int
    thumbnail_url: str | None
    text: str
    uploaded_at: datetime   # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00
    suggested_category: str | None
    suggested_entity: str | None        # clamp 後的實體**名稱**，清單外＝None
    suggested_task_title: str | None    # 沒有可辦的事＝None（待辦窗就不開）
    suggested_task_due: date | None     # 轉成 JSON 時是 "2026-08-21" 這種字串


class FolderDetailResponse(BaseModel):
    """GET /folders/{id} 的回應：資料夾本身 ＋ 裡面的照片摘要（新的在前）。"""

    folder: FolderWithCount
    photos: list[PhotoSummary]
