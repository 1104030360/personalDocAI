"""隱私閘門：照片進 S3 之前，用 VLM 短問題分成三類。

不看檔名。filename 只在簽章裡因為呼叫端本來就有、假件要記帳。

同一顆看圖 VLM、另一份短 prompt（design6 §1.1），後端跟著頁首那顆本機／雲端
開關走（D6：只讀不寫）。任何一步失敗都回 UNCERTAIN——閘門錯的方向必須是
「留在本機」，不是「送出去」。
"""

from __future__ import annotations

import base64
import io
import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from PIL import Image
from pydantic import BaseModel

from app.core import config
from app.services import ollama_cloud, pdf_service
from app.services.ai_timing import AiTarget, log_ai

logger = logging.getLogger(__name__)


class Verdict(StrEnum):
    SENSITIVE = "SENSITIVE"
    NON_SENSITIVE = "NON_SENSITIVE"
    UNCERTAIN = "UNCERTAIN"


class PrivacyJudgement(BaseModel):
    sensitive: bool
    confident: bool


def judgement_to_verdict(judgement: PrivacyJudgement) -> Verdict:
    if judgement.sensitive:
        return Verdict.SENSITIVE
    if judgement.confident:
        return Verdict.NON_SENSITIVE
    return Verdict.UNCERTAIN


# 閘門的短問 prompt。**只問一件事、只准回兩個欄位**——這不是入庫那次的
# build_vlm_prompt（那一份要九個欄位、要注入三份清單、本機要跑好幾分鐘）。
# 把入庫欄位摻進來就等於在閘門做了一次完整理解，EC2 卸壓也就沒工作可做了。
PRIVACY_PROMPT = """這張圖裡有沒有個人敏感資訊？

算敏感的例子：身分證件、健保卡、駕照、護照、病歷、處方箋、薪資單、
銀行對帳單、信用卡卡面、報稅資料、含個人地址或電話的信件。

只輸出一個 JSON 物件，恰好兩個欄位：
{"sensitive": true 或 false, "confident": true 或 false}

- sensitive：圖裡有上述任何一種東西就 true，都沒有就 false。
- confident：你對這個判斷有沒有把握。圖太模糊、太暗、看不清楚就填 false。

不要描述這張圖、不要翻譯、不要加上這兩個以外的任何欄位。
"""

# 雲端專用的輸出格式補充（ollama_cloud 模組 docstring 講的第②道保險：
# ollama.com 對 format= 實測不強制，模型會照 prompt 樣式回 markdown 條列）。
#
# ⛔ **絕不可以改接 vlm_service.CLOUD_JSON_INSTRUCTION。** 那一段的「長相示意」
#    逐字列著 understand 的九個鍵（understood／text／category／…／task_due），
#    接上去等於叫模型回**錯的鍵**，PrivacyJudgement 一律驗證失敗 → 雲端永遠
#    UNCERTAIN、一張都卸不出去，而且完全不出聲。這裡的鍵名只有兩個。
_CLOUD_JSON_INSTRUCTION = """
輸出格式（最後、也最優先的規則）：
只輸出一個 JSON 物件。不要條列、不要 markdown、不要程式碼圍欄、不要 JSON 以外的任何文字。
長相示意：{"sensitive": false, "confident": true}
"""

# 送進閘門模型之前先把圖縮到這個長邊。數字與 storage_service.THUMBNAIL_MAX_SIDE
# 一樣是 512，但兩者是不同的東西：那邊是使用者在瀏覽頁看的縮圖、要落地
# data/thumbs；這裡只是「問模型之前少傳一點位元組」，只回位元組、不寫任何檔案。
GATE_IMAGE_MAX_SIDE = 512

# 縮完一律是 PNG，所以問模型時的 content_type 也固定是它
GATE_IMAGE_CONTENT_TYPE = "image/png"


def shrink_for_model(image_bytes: bytes) -> bytes:
    """把圖等比縮到長邊 <= 512 並輸出 PNG 位元組；本來就小的不放大。

    只在記憶體裡做，不寫檔——閘門的縮圖不是使用者看的縮圖。
    位元組解不開時讓 Pillow 的例外往外丟，由 VlmGate 收成 UNCERTAIN。
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        shrunk = image.copy()  # 複製一份，離開 with 之後才還能繼續用

    # thumbnail() 是「就地修改」而且本來就小於上限的圖不會被放大
    shrunk.thumbnail((GATE_IMAGE_MAX_SIDE, GATE_IMAGE_MAX_SIDE))

    buffer = io.BytesIO()
    shrunk.save(buffer, format="PNG")
    return buffer.getvalue()


class PrivacyGate(Protocol):
    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict: ...


class PrivacyModel(Protocol):
    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement: ...


class OllamaPrivacyModel:
    """閘門的短問實作：同一顆看圖 VLM、另一份短 prompt（design6 §1.1）。

    後端在**建構那一刻**決定，之後 timing_target 是不可變的 AiTarget——
    與 OllamaVLM 同一套：一次呼叫用的後端不會被開關中途改掉。

    backend 明傳時以參數為準、不看頁首開關：worker 行程的 config.AI_BACKEND
    永遠是預設值，只能吃入列當下抄進 job 的快照（總覽 §10.2 S）。
    """

    def __init__(self, *, backend: str | None = None) -> None:
        chosen_backend = backend if backend is not None else config.AI_BACKEND
        self._is_cloud = chosen_backend == "cloud"
        self._model_name = config.OLLAMA_CLOUD_VLM_MODEL if self._is_cloud else config.VLM_MODEL
        self._timing_target = AiTarget(backend=chosen_backend, model=self._model_name)
        # 兩邊建物件都不會連線（ChatOllama 與官方 Client 都是第一次呼叫才撥號）
        if self._is_cloud:
            # 雲端 Client 一律跟 ollama_cloud 拿——全系統唯一建它的地方
            self._client = ollama_cloud.build_client()
        else:
            # temperature=0 ＝要模型盡量穩定、不要每次答不一樣
            self._chat = ChatOllama(
                model=self._model_name,
                base_url=config.OLLAMA_BASE_URL,
                temperature=0,
            ).with_structured_output(PrivacyJudgement)

    @property
    def timing_target(self) -> AiTarget:
        return self._timing_target

    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement:
        """問一次「這張圖敏感嗎」。**只試一次**；例外往外丟。

        不像 OllamaVLM 那樣重試：閘門失敗的方向本來就是「留在本機」，
        重試只是多花幾十秒才得到同一個保守結論。收拾例外的是 VlmGate。
        """
        with log_ai("privacy", target=self._timing_target):
            if self._is_cloud:
                message = {
                    "role": "user",
                    # 只有雲端才接那段「只准回 JSON」（理由見常數上方的註解）
                    "content": PRIVACY_PROMPT + _CLOUD_JSON_INSTRUCTION,
                    # 官方套件的 images 直接吃 raw bytes、自己判圖片格式，
                    # 所以雲端這條路用不到 content_type
                    "images": [image_bytes],
                }
                response = self._client.chat(
                    model=self._model_name,
                    messages=[message],
                    format=PrivacyJudgement.model_json_schema(),
                    options={"temperature": 0},
                )
                return PrivacyJudgement.model_validate_json(
                    ollama_cloud.extract_json_object(response.message.content or "")
                )

            # HumanMessage＝LangChain 裡「使用者傳給模型的一則訊息」；
            # content 是內容區塊清單，一塊文字（短 prompt）＋一塊 base64 圖片
            message = HumanMessage(
                content=[
                    {"type": "text", "text": PRIVACY_PROMPT},
                    {
                        "type": "image",
                        "base64": base64.b64encode(image_bytes).decode("ascii"),
                        "mime_type": content_type,
                    },
                ]
            )
            # with_structured_output 正常會回一顆 PrivacyJudgement；真的回了別的
            # 東西時 judgement_to_verdict 會炸，一樣被 VlmGate 收成 UNCERTAIN 並留 log
            return self._chat.invoke([message])


class VlmGate:
    """唯一真閘門：讀檔 → 縮圖 → 問模型 → 三分類。不看 filename。

    每一種失敗都回 UNCERTAIN，但**一定留一行 warning**：接線之後一個傳錯
    參數的 bug 會讓每張照片都變 UNCERTAIN、一張都卸不出去，安靜的話沒有線索。
    """

    def __init__(self, model: PrivacyModel) -> None:
        self._model = model

    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict:
        del filename  # 契約：verdict 不得依賴檔名

        try:
            image_bytes = load_bytes()
        except Exception:
            logger.warning("隱私閘門判斷失敗，當作 UNCERTAIN：讀不到檔案", exc_info=True)
            return Verdict.UNCERTAIN

        if content_type == config.PDF_CONTENT_TYPE:
            try:
                # 只看第一頁：多頁薪資單只有封面被看過，失敗方向仍是 UNCERTAIN／
                # 可能漏，好過整份不看。完整逐頁理解是入庫那一次的事。
                image_bytes = pdf_service.render_pages(image_bytes)[0]
            except Exception:
                logger.warning(
                    "隱私閘門判斷失敗，當作 UNCERTAIN：PDF 渲染不出第一頁", exc_info=True
                )
                return Verdict.UNCERTAIN

        try:
            shrunk_bytes = shrink_for_model(image_bytes)
        except Exception:
            logger.warning("隱私閘門判斷失敗，當作 UNCERTAIN：縮圖失敗", exc_info=True)
            return Verdict.UNCERTAIN

        try:
            judgement = self._model.judge(shrunk_bytes, GATE_IMAGE_CONTENT_TYPE)
            return judgement_to_verdict(judgement)
        except Exception:
            logger.warning("隱私閘門判斷失敗，當作 UNCERTAIN：模型短問", exc_info=True)
            return Verdict.UNCERTAIN
