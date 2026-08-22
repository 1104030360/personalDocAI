"""「再建議一個實體」的文字 LLM（design3.md D12）。

和 vlm_service 分開的理由：那個是**看圖**（一次上傳只跑一次，同一輪把實體一起建議出來），
這裡是**看文字**——使用者在彈窗按「再建議一個」時，拿已經存下來的照片描述與四個欄位，
從剩下的候選實體裡再挑一個。所以不重新看圖、也不重跑那顆多模態模型的圖片路徑。
"""

from __future__ import annotations

import logging
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app.core import config

logger = logging.getLogger(__name__)


class EntityPick(BaseModel):
    """模型這一次挑了哪一個實體。挑不出來就是 null。"""

    entity: str | None = None


ENTITY_PICK_PROMPT = """你要從「候選實體」裡挑出最能代表這張照片的那一個。

實體＝真實世界的某一件具體東西（例如「我的 MacBook」「Project 2」），
不是類別、不是資料夾。

照片內容：
{photo}

候選實體：
{candidates}

規則：
1. 只能從候選清單裡挑**一個**，entity 填該實體的「名稱」原文。
2. 都不夠相關就填 null——寧可不挑，也不要硬湊。
3. 禁止自創名稱：候選清單以外的任何名字一律不可以填。
"""


class EntitySuggesterClient(Protocol):
    """再建議一個實體的介面。正式用 OllamaEntitySuggester，測試用 FakeEntitySuggester。"""

    def pick(self, photo: dict, candidates: list[dict]) -> str | None:
        ...


def _describe_photo(photo: dict) -> str:
    """把照片那一列整理成給模型看的幾行字（就是 embedding 用的那些欄位）。"""
    items = "、".join(photo["items"] or []) or "（無）"
    content_time = photo["content_time"].isoformat() if photo["content_time"] else "（無）"
    return (
        f"描述：{photo['text']}\n"
        f"類別：{photo['category'] or '（無）'}\n"
        f"地點：{photo['location'] or '（無）'}\n"
        f"物品：{items}\n"
        f"內容時間：{content_time}"
    )


class OllamaEntitySuggester:
    """用本機 Ollama 的文字模型從候選實體裡挑一個。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model = ChatOllama(
            model=model or config.LLM_MODEL,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(EntityPick)

    def pick(self, photo: dict, candidates: list[dict]) -> str | None:
        """挑一個候選實體的名稱；挑不出來或呼叫失敗回 None。

        刻意**只試一次**（OllamaVLM 會重試一次，這裡不）：
        建議本來就可有可無——失敗時使用者還有②改選現有、③自創、④不釘三條路，
        多花一次推論的時間換一個「本來就可以沒有」的建議並不划算。
        但一定要留 log，不然「Ollama 沒開」會無聲變成「AI 覺得都不像」。
        """
        candidate_lines = "\n".join(
            f"- {entity['name']}：{entity['description']}" for entity in candidates
        )
        message = HumanMessage(
            content=ENTITY_PICK_PROMPT.format(
                photo=_describe_photo(photo), candidates=candidate_lines
            )
        )
        try:
            result = self._model.invoke([message])
        except Exception:
            logger.warning("實體建議呼叫失敗，這次就不給建議", exc_info=True)
            return None
        if isinstance(result, EntityPick):
            return result.entity
        logger.warning("實體建議未回傳有效的結構化結果，這次就不給建議")
        return None
