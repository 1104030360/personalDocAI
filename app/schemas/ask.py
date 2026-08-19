"""自然語言詢問的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel


class AskRequest(BaseModel):
    """POST /ask 的請求內容。問題可以是中文或英文。"""

    question: str


class AskResponse(BaseModel):
    """POST /ask 成功時的回應（HTTP 200）。

    answer 的語言跟隨提問語言（中文問→中文答、英文問→英文答）。
    """

    answer: str
    search_mode: str            # "metadata search" 或 "vector semantic search"
    retrieved_photo_ids: list[int]
