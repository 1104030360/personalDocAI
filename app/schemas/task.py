"""待辦（task）的 API 資料格式（Pydantic 模型，design3.md D13）。

和 app/schemas/photo.py 的 TaskSuggestion 刻意分成兩個模型：
那個是 VLM 在上傳當下給的**建議**（可有可無、不落庫）；
這裡是使用者按下「建立」之後，真的存進資料庫的那一筆待辦。
"""

from datetime import date

from pydantic import BaseModel, model_validator


class CreateTaskRequest(BaseModel):
    """POST /photos/{id}/task 的請求（design3.md D13 的彈窗 3）。

    due_date 刻意收「字串」而不是 date：格式不對時，錯誤訊息由我們自己寫成
    中文的「到期日格式須為 YYYY-MM-DD」，不會變成 Pydantic 的預設英文訊息。
    字串轉成 date 是 router 的事（資料層只收 date 物件）。
    """

    title: str
    due_date: str | None = None

    @model_validator(mode="after")
    def 標題與到期日必須可用(self) -> "CreateTaskRequest":
        """跨欄位檢查（寫法鏡射 PinEntityRequest）。

        mode="after" ＝各欄位型別都驗完之後才跑這裡。
        在這裡 raise ValueError，FastAPI 會自動變成 422 回應。
        """
        # 順手把前後空白去掉，「交作業 」與「交作業」才不會變成兩種標題
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("待辦標題不可為空白")

        if self.due_date is not None:
            self.due_date = self.due_date.strip()
            try:
                # 只驗格式，解析結果丟掉——真正要用的 date 由 router 再轉一次，
                # 這樣「驗證」與「轉型」的責任不會混在同一個地方。
                date.fromisoformat(self.due_date)
            except ValueError:
                raise ValueError("到期日格式須為 YYYY-MM-DD")
        return self


class TaskOut(BaseModel):
    """一筆待辦。建立成功的 201 與 GET /tasks 的每一列共用同一個形狀。

    due_date 用 ISO 日期字串外送（鏡射 PhotoMetadata.content_time 的做法）；
    thumbnail_url 是「網址」不是硬碟路徑——來源照片有縮圖才給
    /photos/{photo_id}/thumbnail，沒有就是 None，前端顯示灰底占位。
    不外送 created_at：清單按到期日排，建立時間是內部細節，沒人看。
    """

    id: int
    photo_id: int
    title: str
    due_date: str | None
    thumbnail_url: str | None
