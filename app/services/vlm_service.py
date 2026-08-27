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
from app.services import ollama_cloud
from app.services.ai_timing import AiTarget

logger = logging.getLogger(__name__)


class PhotoUnderstanding(BaseModel):
    """VLM 看完照片後唯一被允許回傳的九個欄位。

    欄位清單就是「規格允許的資訊」；清單外的東西沒有地方放，自然被捨棄。

    前六欄是**會落庫**的照片內容（text ＋ metadata 四欄），
    後三欄（Phase 30 加入）是**建議**：實體與待辦一律等使用者在彈窗按下去才寫入
    （design3.md D3「人確認才落庫」、D8「仍是同一個 gemma4 看一次」）。
    """

    understood: bool  # 看不懂 → False
    text: str = ""  # 文字描述（照片主要語言）
    category: str | None = None  # 類別，例如「收據」或 "Receipt"
    location: str | None = None  # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)  # 物品清單
    content_time: str | None = None  # ISO 日期字串，推不出來 → None
    entity: str | None = None  # 從「現有實體清單」挑一個最相關的；清單空或都不像 → None
    task_title: str | None = None  # 照片含可辦事項（繳交、繳費、預約…）才填；沒有 → None
    task_due: str | None = None  # 到期日 YYYY-MM-DD；推不出來 → None


# 系統收件箱資料夾的名稱。與 photo_repository.DEFAULT_FOLDERS 的第一筆一致
# （design1.md §5：「未分類」是唯一的系統資料夾，is_inbox=true）。
UNCATEGORIZED = "未分類"

# 糾錯例子裡「照片描述」最多引用幾個字（Phase 35）。
# few-shot 要的是「你猜 A、正確是 B」這個對照，題幹只是讓模型認得出情境；
# 整段描述照抄進去只會稀釋掉真正要學的東西，也把 prompt 撐長、讓看圖更慢。
CORRECTION_TEXT_LIMIT = 60


def _excerpt(text: str) -> str:
    """把糾錯例子的照片描述截短，太長就用「…」收尾。

    純函式，只給 build_vlm_prompt 用（前面加底線＝本模組內部用，別處不要呼叫）。
    """
    # 先摺行：photo_text 可能含換行，原樣塞進 f-string 會把這一條 few-shot
    # 撐成好幾行，模型容易把換行後的內容讀成獨立的一條指令。
    # " ".join(text.split()) 同時處理了去頭尾空白＋把任何空白（含換行、tab、
    # 連續空格）收斂成單一空格，所以不再需要另外呼叫 strip()。
    text = " ".join(text.split())
    if len(text) <= CORRECTION_TEXT_LIMIT:
        return text
    return text[:CORRECTION_TEXT_LIMIT] + "…"


def build_vlm_prompt(folders: list[dict], entities: list[dict], corrections: list[dict]) -> str:
    """組出看圖用的 prompt，把三份清單當變數注入：資料夾、實體、最近的人工糾錯。

    folders 來自 photo_repository.list_folders()、entities 來自 list_entities()，
    每筆至少要有 name 與 description。清單是變數不是常數——使用者今天自建了
    「專案X」或「我的 MacBook」，下一次上傳時模型就看得到它。

    corrections 來自 photo_repository.recent_corrections()（新的在前，最多 N 筆），
    每筆三鍵 suggested／chosen／photo_text。空清單＝這一段整段不出現，
    prompt 與 Phase 35 之前**逐字相同**（沒糾錯過的人不該被多餘的段落干擾）。

    注意：這裡只是「請模型這樣做」。模型不聽話是常態，真正的保險是後面的
    clamp_category()（清單外一律夾成「未分類」）與 clamp_entity()（清單外一律 None）。

    design1.md §8 是資料夾那一段；design3.md D8／D12／D13 是實體與待辦那兩段；
    D11 是糾錯 few-shot——仍然只有這一次看圖呼叫，多的只是「建議」欄位與幾個例子，
    不是第二個分類模型、更不是微調（§1.2 已否決）。
    """
    folder_lines = "\n".join(f"- {folder['name']}：{folder['description']}" for folder in folders)
    # 糾錯那一段：有例子才長出來。開頭的 "\n" 是為了與上一段隔一個空行——
    # 空清單時整個變數是空字串，接縫處剛好還原成原本的「一個空行」。
    correction_section = ""
    if corrections:
        correction_lines = "\n".join(
            f"- 「{_excerpt(correction['photo_text'])}」"
            f"你猜「{correction['suggested']}」、正確是「{correction['chosen']}」"
            for correction in corrections
        )
        correction_section = (
            "\n最近的人工糾正（參考這些修正你的判斷）：\n" + correction_lines + "\n"
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
{correction_section}
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
    三個實作都不必寫 class Xxx(VLMClient)：
    - OllamaVLM：正式路徑（uvicorn），呼叫本機 gemma4（開關預設的「本機」）
    - OllamaCloudVLM：開關撥到「雲端」時的正式路徑，直連 Ollama Cloud（2026-08-22）
    - FakeVLM：只在 tests/fakes.py，pytest 的固定答案卡；不是第二套看圖系統
    """

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding: ...


class OllamaVLM:
    """本機的看圖實作。開關在預設的「本機」時，上傳實際跑的就是這一個（gemma4）。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        model_name = model or config.VLM_MODEL
        self._timing_target = AiTarget(backend="local", model=model_name)
        # temperature=0 ＝要模型盡量穩定、不要每次答不一樣
        self._model = ChatOllama(
            model=model_name,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(PhotoUnderstanding)

    @property
    def timing_target(self) -> AiTarget:
        return self._timing_target

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        """看一張照片。任何失敗都回 understood=False，由上層轉成 422。

        folders＝現有資料夾清單、entities＝現有實體清單、corrections＝最近的人工糾錯，
        三份都會被組進 prompt（design1.md §8、design3.md D12、D11）；
        仍然只有這一次看圖呼叫，沒有第二個分類模型——實體與待辦只是同一次輸出
        多出來的建議欄位，糾錯也只是同一個 prompt 裡多幾個例子。
        """
        # HumanMessage＝LangChain 裡「使用者傳給模型的一則訊息」；
        # content 是內容區塊清單，這裡放一塊文字（prompt）＋一塊 base64 圖片
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": build_vlm_prompt(folders, entities, corrections),
                },
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


# 雲端看圖的輸出格式補充指令（2026-08-22 真雲端煙霧抓到的教訓：ollama.com 對
# format= 不強制，gemma4 照 prompt 樣式回了 markdown 條列——完整說明與三道保險
# 的作法見 ollama_cloud 模組 docstring）。把「只准回 JSON」接在共用 prompt 後面：
# 不動 build_vlm_prompt，本機 prompt 與它的黃金檔測試逐字不變。
CLOUD_JSON_INSTRUCTION = """
輸出格式（最後、也最優先的規則）：
只輸出一個 JSON 物件。不要條列、不要 markdown、不要程式碼圍欄、不要 JSON 以外的任何文字。
長相示意（值的語言仍照上面的語言規則）：
{"understood": true, "text": "…", "category": "…或 null", "location": "…或 null",
"items": ["…"], "content_time": "YYYY-MM-DD 或 null", "entity": "…或 null",
"task_title": "…或 null", "task_due": "YYYY-MM-DD 或 null"}
"""


class OllamaCloudVLM:
    """雲端的看圖實作（Ollama Cloud）。開關撥到「雲端」時，上傳走的是這一個。

    與 OllamaVLM 同一份合約、同一個 prompt、同一套失敗語意（重試一次、
    仍失敗＝understood=False，上層照舊轉 422）；不一樣的只有傳輸層——
    照官方 ollama 套件的雲端用法直連 Ollama Cloud（Client 統一跟
    ollama_cloud.build_client() 拿）。結構化輸出靠三道保險：chat 的 format
    參數塞 JSON schema（雲端實測不強制）、prompt 尾端的 CLOUD_JSON_INSTRUCTION
    明講只准回 JSON、回來再 ollama_cloud.extract_json_object 寬鬆抽取後交 Pydantic 驗證。

    2026-08-22 產品負責人指示新增：design3「無雲端 VLM」的不做項自此作廢；
    同日 AI 開關擴及詢問路由／回答與實體建議（見 dependencies.py）——
    embeddings 仍一律本機。
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or config.OLLAMA_CLOUD_VLM_MODEL
        self._timing_target = AiTarget(backend="cloud", model=self._model_name)
        self._client = ollama_cloud.build_client()

    @property
    def timing_target(self) -> AiTarget:
        return self._timing_target

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        """看一張照片（雲端）。任何失敗都回 understood=False，由上層轉成 422。

        content_type 為了跟 VLMClient 合約一致而收下但用不到——
        官方套件的 images 欄位直接吃 raw bytes、自己判斷圖片格式。
        """
        message = {
            "role": "user",
            # 共用 prompt 之後接雲端專用的「只准回 JSON」指令（理由見常數註解）
            "content": build_vlm_prompt(folders, entities, corrections) + CLOUD_JSON_INSTRUCTION,
            "images": [image_bytes],
        }
        # 失敗就再試一次；仍失敗一律視為「看不懂」（與 OllamaVLM 同一套節奏）
        for _ in range(2):
            try:
                # temperature=0 的理由同 OllamaVLM：要模型盡量穩定、不要每次答不一樣
                response = self._client.chat(
                    model=self._model_name,
                    messages=[message],
                    format=PhotoUnderstanding.model_json_schema(),
                    options={"temperature": 0},
                )
                return PhotoUnderstanding.model_validate_json(
                    ollama_cloud.extract_json_object(response.message.content or "")
                )
            except Exception:
                # 401（key 錯）、404（雲端沒這個模型）、逾時、schema 驗證不過……
                # 全收斂成「看不懂」，但 log 要留原因——不然全都無聲變成 422
                logger.warning("雲端 VLM 呼叫失敗，視為看不懂", exc_info=True)
        return PhotoUnderstanding(understood=False)


def vlm_timing_target(vlm: VLMClient) -> AiTarget:
    target = getattr(vlm, "timing_target", None)
    if isinstance(target, AiTarget):
        return target
    是雲端 = config.AI_BACKEND == "cloud"
    return AiTarget(
        backend=config.AI_BACKEND,
        model=config.OLLAMA_CLOUD_VLM_MODEL if 是雲端 else config.VLM_MODEL,
    )


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
