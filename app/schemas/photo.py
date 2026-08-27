"""照片相關的 API 資料格式（Pydantic 模型）。

增量五（Phase 62／63）起，上傳與快門都改回 202：
成功受理的回應在 app/schemas/ingest_job.py 的 IngestAcceptedResponse，
原本 201 的整份照片回應模型（含待辦建議那個小模型）已隨舊同步流程刪除。
本檔剩下的是「讀出來」與「歸類」兩類端點的形狀。
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class PhotoMetadata(BaseModel):
    """照片的結構化 metadata：固定四個欄位，不多不少。

    欄位值使用照片內容本身的語言（中文收據就是中文、英文收據就是英文），
    系統不做翻譯——跨語言的搜尋交給多語 embedding 處理（design.md §8.3）。
    """

    category: str | None = None  # 類別，例如「收據」或 "Receipt"
    location: str | None = None  # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)  # 物品清單
    content_time: str | None = None  # 內容時間，ISO 日期字串，例如「2026-08-10」


class FolderOut(BaseModel):
    """回應裡的資料夾。彈窗只需要這三個欄位，其餘（is_inbox、張數）不外送。"""

    id: int
    name: str
    description: str


class AssignFolderRequest(BaseModel):
    """PATCH /photos/{id}/folder 的請求（design1.md §7.2）。

    兩種長相，擇一：
      採用現有資料夾（彈窗選項①②）：{"folder_id": 2}
      自建新資料夾（彈窗選項③）    ：{"name": "專案X", "description": "…"}
    """

    folder_id: int | None = None
    name: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def 必須恰好給一個(self) -> "AssignFolderRequest":
        """跨欄位檢查：folder_id 與 name 有且只有一個。

        mode="after" ＝各欄位型別都驗完之後才跑這裡。
        在這裡 raise ValueError，FastAPI 會自動變成 422 回應。
        """
        if self.name is not None:
            if not self.name.strip():
                raise ValueError("資料夾名稱不可為空白")
            # 順手把前後空白去掉，"收據 " 與 "收據" 才不會變成兩個資料夾
            self.name = self.name.strip()

        # 兩邊同時是 None（都沒給）或同時不是 None（都給了）→ 都不合法
        if (self.folder_id is None) == (self.name is None):
            raise ValueError("folder_id 與 name 必須恰好提供一個")
        return self


class AssignFolderResponse(BaseModel):
    """PATCH /photos/{id}/folder 成功時的回應（HTTP 200）。

    回這張照片「歸類之後」的狀態：現在在哪個資料夾、四個 metadata 欄位長怎樣
    （其中 category 已經等於資料夾名稱）。
    """

    id: int
    folder: FolderOut
    metadata: PhotoMetadata


class PhotoDetailOut(BaseModel):
    """GET /photos/{photo_id} 的回應（HTTP 200，design4.md §4.4）。

    唯讀詳情彈窗要的東西，不多不少：
      - text ＋ metadata 四欄 ＝ 使用者要看的說明
      - 兩個網址        ＝ 圖要去哪裡拿（不是硬碟路徑）
      - uploaded_at     ＝ 什麼時候進來的

    刻意「不回」：embedding（1024 個數字，前端用不到）、folder 物件、
    suggested_category、釘著的實體清單——那些不是這顆窗要回答的問題。
    """

    id: int
    text: str
    metadata: PhotoMetadata
    thumbnail_url: str | None  # thumbnail_path 有值才給網址，舊照片是 None
    image_url: str | None  # original_path 有值才給網址，舊照片是 None
    uploaded_at: datetime  # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00
