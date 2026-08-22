"""上傳照片的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel, Field, model_validator

from app.schemas.entity import EntityOut


class PhotoMetadata(BaseModel):
    """照片的結構化 metadata：固定四個欄位，不多不少。

    欄位值使用照片內容本身的語言（中文收據就是中文、英文收據就是英文），
    系統不做翻譯——跨語言的搜尋交給多語 embedding 處理（design.md §8.3）。
    """

    category: str | None = None       # 類別，例如「收據」或 "Receipt"
    location: str | None = None       # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)  # 物品清單
    content_time: str | None = None   # 內容時間，ISO 日期字串，例如「2026-08-10」


class FolderOut(BaseModel):
    """回應裡的資料夾。彈窗只需要這三個欄位，其餘（is_inbox、張數）不外送。"""

    id: int
    name: str
    description: str


class TaskSuggestion(BaseModel):
    """VLM 判斷出來的待辦建議（design3.md D13）。

    只是建議：使用者在待辦彈窗按下「建立」才會真的寫入待辦表（Phase 33），
    上傳當下什麼都不存。title 是必要的——沒有標題就等於「沒有待辦」，
    那時整個 suggested_task 是 None，而不是一個空殼。
    """

    title: str
    due: str | None = None   # ISO 日期字串，例如「2026-09-18」；推不出來 → None


class UploadResponse(BaseModel):
    """POST /photos 成功時的回應（HTTP 201）。

    2026-08-20 起多帶四樣東西，讓前端一收到回應就能把彈窗畫出來，
    不必再多打一次 API（design1.md §7.1）。
    2026-08-21（Phase 30）再多帶三樣：實體與待辦的建議，
    對應彈窗 2【實體】與彈窗 3【待辦】（design3.md §2）——同樣一次帶齊。
    """

    id: int
    text: str
    metadata: PhotoMetadata
    folder: FolderOut            # 照片現在在哪個資料夾——上傳當下一定是「未分類」
    suggested_folder: FolderOut  # VLM 建議去哪個資料夾（保證是 folders 裡的一筆）
    folders: list[FolderOut]     # 完整資料夾清單，給彈窗的下拉選單用
    thumbnail_url: str           # 例如 "/photos/1/thumbnail"
    suggested_entity: EntityOut | None   # 夾回清單後的實體建議；都不像 → None
    entities: list[EntityOut]            # 完整實體清單，給實體彈窗的下拉選單用
    suggested_task: TaskSuggestion | None  # 沒有可辦的事 → None（待辦彈窗就不開）


class PdfUploadResponse(BaseModel):
    """上傳 PDF 成功時的回應（HTTP 201，design3.md D7）。

    PDF 一頁當成一張照片，所以回的是「一串單圖回應」而不是一筆——
    created 裡的每一筆與單圖上傳的回應長得一模一樣，前端可以原樣餵給彈窗。

    不變式：pages ＝ len(created) ＋ len(skipped_pages)，沒有頁會憑空消失。
    """

    pages: int                      # 這份 PDF 總共幾頁
    created: list[UploadResponse]   # 成功入庫的頁（順序即頁序）
    skipped_pages: list[int]        # VLM 看不懂而跳過的頁碼，1 起算


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
