"""實體（別針）的 API 資料格式（Pydantic 模型，design3.md D12）。

資料夾是抽屜（一張照片只能放一個），實體是別針（一張照片可以釘好幾個）——
所以這裡沒有「改成別的實體」，只有「再釘一個」。
"""

from pydantic import BaseModel, model_validator


class EntityOut(BaseModel):
    """回應裡的實體。彈窗只需要這三個欄位（created_at 之類的內部欄位不外送）。

    上傳回應也用它（app/schemas/photo.py 直接 import，不另外複製一份）。
    """

    id: int
    name: str
    description: str


class PinEntityRequest(BaseModel):
    """POST /photos/{id}/entities 的請求。

    兩種長相，擇一（與 AssignFolderRequest 完全一致的分工）：
      釘現有實體（彈窗①②）：{"entity_id": 3}
      自創新實體（彈窗③）  ：{"name": "我的 MacBook", "description": "…"}
    """

    entity_id: int | None = None
    name: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def 必須恰好給一個(self) -> "PinEntityRequest":
        """跨欄位檢查：entity_id 與 name 有且只有一個。

        mode="after" ＝各欄位型別都驗完之後才跑這裡。
        在這裡 raise ValueError，FastAPI 會自動變成 422 回應。
        """
        if self.name is not None:
            if not self.name.strip():
                raise ValueError("實體名稱不可為空白")
            # 順手把前後空白去掉，「 MacBook 」與「MacBook」才不會變成兩件東西
            self.name = self.name.strip()

        # 兩邊同時是 None（都沒給）或同時不是 None（都給了）→ 都不合法
        if (self.entity_id is None) == (self.name is None):
            raise ValueError("entity_id 與 name 必須恰好提供一個")
        return self


class PinEntityResponse(BaseModel):
    """POST /photos/{id}/entities 成功時的回應（HTTP 201）。

    entities 是釘完之後的**完整實體清單**：自創那條路會讓它變長，
    彈窗收到就直接換掉下拉選單，不必再打一次 GET /entities。
    """

    photo_id: int
    entity: EntityOut          # 這次釘上去的那一個
    entities: list[EntityOut]  # 完整實體清單（彈窗②下拉）


class EntitySuggestionRequest(BaseModel):
    """POST /photos/{id}/entity-suggestion 的請求。

    exclude＝已經釘上去的、加上這一輪已經建議過的實體 id。
    由前端記著並帶上來——後端不記「這一輪」是哪一輪（沒有對話記憶）。
    """

    exclude: list[int] = []


class EntitySuggestionResponse(BaseModel):
    """再建議一個的回應（HTTP 200）。沒有適合的就是 null，不是錯誤。"""

    suggested_entity: EntityOut | None
