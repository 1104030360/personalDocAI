"""自然語言詢問的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """POST /ask 的請求內容。問題可以是中文或英文。

    question 缺漏或空字串 → 由框架回既有的 422，不另外發明行為。
    """

    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    """POST /ask 成功時的回應（HTTP 200）。

    answer 的語言跟隨提問語言（中文問→中文答、英文問→英文答）。
    """

    answer: str
    # 四選一，全名見 config.SEARCH_MODE_LABELS：規格 .feature 認得的
    # "metadata search"／"vector semantic search"，加 Phase 34 的
    # "entity pin search"／"task search"
    search_mode: str
    # 一律是**照片** id。待辦路回的是那筆待辦的來源照片，不是待辦本身的 id——
    # 拿這個 id 就能直接去 /photos/{id}/image 看原圖
    retrieved_photo_ids: list[int]
