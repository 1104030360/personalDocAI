"""AI 看圖：照片 bytes → 文字描述＋四個 metadata 欄位。"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.core import config

logger = logging.getLogger(__name__)


class PhotoUnderstanding(BaseModel):
    """VLM 看完照片後唯一被允許回傳的九個欄位。

    欄位清單就是「規格允許的資訊」；清單外的東西沒有地方放，自然被捨棄。

    前六欄是**會落庫**的照片內容（text ＋ metadata 四欄），
    後三欄（Phase 30 加入）是**建議**：實體與待辦一律等使用者在彈窗按下去才寫入
    （design3.md D3「人確認才落庫」、D8「仍是同一個 gemma4 看一次」）。
    """

    understood: bool                                 # 看不懂 → False
    text: str = ""                                   # 文字描述（照片主要語言）
    category: str | None = None                      # 類別，例如「收據」或 "Receipt"
    location: str | None = None                      # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)   # 物品清單
    content_time: str | None = None                  # ISO 日期字串，推不出來 → None
    entity: str | None = None       # 從「現有實體清單」挑一個最相關的；清單空或都不像 → None
    task_title: str | None = None   # 照片含可辦事項（繳交、繳費、預約…）才填；沒有 → None
    task_due: str | None = None     # 到期日 YYYY-MM-DD；推不出來 → None


# 系統收件箱資料夾的名稱。與 photo_repository.DEFAULT_FOLDERS 的第一筆一致
# （design1.md §5：「未分類」是唯一的系統資料夾，is_inbox=true）。
UNCATEGORIZED = "未分類"


def build_vlm_prompt(folders: list[dict], entities: list[dict]) -> str:
    """組出看圖用的 prompt，把「現有資料夾清單」與「現有實體清單」當變數注入。

    folders 來自 photo_repository.list_folders()、entities 來自 list_entities()，
    每筆至少要有 name 與 description。清單是變數不是常數——使用者今天自建了
    「專案X」或「我的 MacBook」，下一次上傳時模型就看得到它。

    注意：這裡只是「請模型這樣做」。模型不聽話是常態，真正的保險是後面的
    clamp_category()（清單外一律夾成「未分類」）與 clamp_entity()（清單外一律 None）。

    design1.md §8 是資料夾那一段；design3.md D8／D12／D13 是實體與待辦那兩段——
    仍然只有這一次看圖呼叫，多的只是「建議」欄位，不是第二個分類模型。
    """
    folder_lines = "\n".join(
        f"- {folder['name']}：{folder['description']}" for folder in folders
    )
    # 實體表一開始是空的（不像資料夾有六筆種子），那一段不能留一串空白讓模型自由發揮
    entity_lines = (
        "\n".join(f"- {entity['name']}：{entity['description']}" for entity in entities)
        if entities
        else "（目前沒有任何實體，entity 一律填 null）"
    )
    return f"""你是照片理解助手。請看這張照片，只輸出下列九個欄位：

- understood：你是否看得懂這張照片的內容（看不懂填 false）
- text：用一句話描述照片內容
- category：這張照片應該收進哪一個資料夾（規則見下方「現有資料夾」）
- location：地點或商家名稱，例如「Target」；判斷不出來填 null
- items：照片中出現的物品名稱清單；沒有就填空陣列
- content_time：照片內容本身的日期（例如收據上的消費日期），格式 YYYY-MM-DD；推不出來填 null
- entity：這張照片講的是哪一個「現有實體」（規則見下方「現有實體」）
- task_title、task_due：照片裡有沒有要去做的事（規則見下方「待辦」）

現有資料夾（category 只能從這裡選一個，禁止自創名稱）：
{folder_lines}

category：必須是上面某個資料夾的「名稱」原文。
不確定就填「未分類」。不要翻譯成英文。

現有實體（entity 只能從這裡選一個最相關的，都不符合或清單為空就填 null）：
{entity_lines}

entity：必須是上面某個實體的「名稱」原文，一次只挑一個最相關的。
禁止自創名稱——清單上沒有的東西，就算照片裡真的有，也一律填 null。

待辦：照片內容含有需要去做的事（作業繳交、帳單繳費、預約時間）時，
task_title 用一句話寫那件事、task_due 填到期日（格式 YYYY-MM-DD，推不出來填 null）；
照片只是紀錄、沒有任何要辦的事，task_title 與 task_due 兩個都填 null。

語言規則（重要）：
- text 與各欄位的值，一律使用**照片內容本身的主要語言**。
  照片上是中文（例如中文收據）就用繁體中文寫；照片上是英文（例如英文收據）就用英文寫。
- 不要翻譯。不要中英混寫。照片上寫 "Cola" 就填 "Cola"，寫「可樂」就填「可樂」。
- 例外：category 與 entity 是清單上的名稱，一律照上面清單的原文，不隨照片語言改變。

其他規則：
1. 只准填上面這九個欄位，清單外的任何資訊一律捨棄。
2. 不要編造照片上沒有的資訊。
3. 照片模糊、全黑或看不出任何內容時，understood 填 false。
"""


def clamp_category(category: str | None, folders: list[dict]) -> str:
    """把 VLM 推薦的 category 夾回資料夾清單內（design1.md §7.1、§12）。

    - 命中（去頭尾空白、大小寫不敏感）→ 回**資料夾清單裡的原文**，
      這樣「  收據 」「RECEIPT」都不會生出新的名稱變體。
    - 沒命中、或模型根本沒填 → 回「未分類」，語意就是「不確定」。

    這是純函式：不碰資料庫、不碰網路，給同樣的輸入永遠回同樣的答案。
    """
    if category:
        wanted = category.strip().casefold()
        for folder in folders:
            if folder["name"].casefold() == wanted:
                return folder["name"]
    return UNCATEGORIZED


def clamp_entity(name: str | None, entities: list[dict]) -> dict | None:
    """把模型給的實體名稱夾回實體清單內（design3.md D12）。

    寫法鏡射 clamp_category，兩處不一樣：
    - 回的是**整筆 dict**（清單原文），因為釘選要用 id，不是只要名字。
    - 沒命中就是 None：實體沒有「未分類」這種保底選項，不像就是不像。
      清單外的名字絕不自動變成新實體——實體清單只在使用者按「③自創」時才變長。

    這是純函式：不碰資料庫、不碰網路，給同樣的輸入永遠回同樣的答案。
    """
    if name:
        wanted = name.strip().casefold()
        for entity in entities:
            if entity["name"].casefold() == wanted:
                return entity
    return None


class VLMClient(Protocol):
    """看圖合約，不是會執行的類別。追正式上傳請直接看下面的 OllamaVLM。

    Protocol＝只要有 understand() 就算數，不必繼承本 class。
    兩個實作都不必寫 class Xxx(VLMClient)：
    - OllamaVLM：正式路徑（uvicorn），真的呼叫本機 gemma4
    - FakeVLM：只在 tests/fakes.py，pytest 的固定答案卡；不是第二套看圖系統
    """

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
    ) -> PhotoUnderstanding:
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

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
    ) -> PhotoUnderstanding:
        """看一張照片。任何失敗都回 understood=False，由上層轉成 422。

        folders＝現有資料夾清單、entities＝現有實體清單，兩份都會被組進 prompt
        （design1.md §8、design3.md D12）；仍然只有這一次看圖呼叫，
        沒有第二個分類模型——實體與待辦只是同一次輸出多出來的建議欄位。
        """
        # HumanMessage＝LangChain 裡「使用者傳給模型的一則訊息」；
        # content 是內容區塊清單，這裡放一塊文字（prompt）＋一塊 base64 圖片
        message = HumanMessage(
            content=[
                {"type": "text", "text": build_vlm_prompt(folders, entities)},
                {
                    "type": "image",
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": content_type,
                },
            ]
        )
        # 失敗就再試一次；仍失敗一律視為「看不懂」——但要留 log，
        # 不然「Ollama 沒開」「模型名打錯」「格式驗證不過」全都無聲變成 422
        for _ in range(2):
            try:
                result = self._model.invoke([message])
            except Exception:
                logger.warning("VLM 呼叫失敗，視為看不懂", exc_info=True)
                continue
            if isinstance(result, PhotoUnderstanding):
                return result
        logger.warning("VLM 未回傳有效的結構化結果，視為看不懂")
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
