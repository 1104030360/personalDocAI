"""AI 看圖：照片 bytes → 文字描述＋四個 metadata 欄位。"""

from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.core import config


class PhotoUnderstanding(BaseModel):
    """VLM 看完照片後唯一被允許回傳的六個欄位。

    欄位清單就是「規格允許的資訊」；清單外的東西沒有地方放，自然被捨棄。
    """

    understood: bool                                 # 看不懂 → False
    text: str = ""                                   # 文字描述（照片主要語言）
    category: str | None = None                      # 類別，例如「收據」或 "Receipt"
    location: str | None = None                      # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)   # 物品清單
    content_time: str | None = None                  # ISO 日期字串，推不出來 → None


VLM_PROMPT = """你是照片理解助手。請看這張照片，只輸出下列六個欄位：

- understood：你是否看得懂這張照片的內容（看不懂填 false）
- text：用一句話描述照片內容
- category：照片類別，例如「收據」「風景」或 "Receipt"、"Landscape"；判斷不出來填 null
- location：地點或商家名稱，例如「Target」；判斷不出來填 null
- items：照片中出現的物品名稱清單；沒有就填空陣列
- content_time：照片內容本身的日期（例如收據上的消費日期），格式 YYYY-MM-DD；推不出來填 null

語言規則（重要）：
- text 與各欄位的值，一律使用**照片內容本身的主要語言**。
  照片上是中文（例如中文收據）就用繁體中文寫；照片上是英文（例如英文收據）就用英文寫。
- 不要翻譯。不要中英混寫。照片上寫 "Cola" 就填 "Cola"，寫「可樂」就填「可樂」。

其他規則：
1. 只准填上面這六個欄位，清單外的任何資訊一律捨棄。
2. 不要編造照片上沒有的資訊。
3. 照片模糊、全黑或看不出任何內容時，understood 填 false。
"""


class VLMClient(Protocol):
    """看圖合約，不是會執行的類別。追正式上傳請直接看下面的 OllamaVLM。

    Protocol＝只要有 understand() 就算數，不必繼承本 class。
    兩個實作都不必寫 class Xxx(VLMClient)：
    - OllamaVLM：正式路徑（uvicorn），真的呼叫本機 gemma4
    - FakeVLM：只在 tests/fakes.py，pytest 的固定答案卡；不是第二套看圖系統
    """

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        ...


class OllamaVLM:
    """正式的看圖實作。使用者上傳照片時，實際跑的就是這一個（本機 gemma4）。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        # temperature=0 ＝要模型盡量穩定、不要每次答不一樣
        self._model = ChatOllama(
            model=model or config.VLM_MODEL,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(PhotoUnderstanding)

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        """看一張照片。任何失敗都回 understood=False，由上層轉成 422。"""
        # HumanMessage＝LangChain 裡「使用者傳給模型的一則訊息」；
        # content 是內容區塊清單，這裡放一塊文字（prompt）＋一塊 base64 圖片
        message = HumanMessage(
            content=[
                {"type": "text", "text": VLM_PROMPT},
                {
                    "type": "image",
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": content_type,
                },
            ]
        )
        # 失敗就再試一次；仍失敗一律視為「看不懂」
        for _ in range(2):
            try:
                result = self._model.invoke([message])
            except Exception:
                continue
            if isinstance(result, PhotoUnderstanding):
                return result
        return PhotoUnderstanding(understood=False)


def parse_content_time(value: str | None) -> date | None:
    """把 VLM 給的日期字串轉成日期。

    解析不出來就回 None——內容時間本來就是可空欄位，
    不可以因為它讓整個上傳失敗。
    """
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
