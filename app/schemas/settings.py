"""AI 後端開關的 API 資料格式（2026-08-22 產品負責人指示新增，同日由看圖擴及詢問）。

只給 GET／PUT /settings/ai-backend 用；照片相關的模型在 photo.py，不要混在一起。
"""

from typing import Literal

from pydantic import BaseModel


class AiBackendUpdate(BaseModel):
    """PUT /settings/ai-backend 的 body。

    backend 只有兩個合法值——其餘任何字串都由 Pydantic 擋成 422，
    router 裡不必再自己驗。
    """

    backend: Literal["local", "cloud"]


class AiBackendOut(BaseModel):
    """開關現況（GET 與 PUT 成功時都回這一份）。

    cloud_configured＝.env 有沒有填 OLLAMA_API_KEY。前端拿它決定要不要
    在切換失敗前就先給提示；真正的守門仍在後端（沒 key 的 PUT 一律 422）。
    """

    backend: Literal["local", "cloud"]
    cloud_configured: bool
