"""AI 呼叫的計時 log（design4.md §5）。

「用到 AI」＝會打 Ollama（本機或 Cloud）的那一段。本檔提供唯一的一種格式，
五種呼叫（看圖／轉向量／判斷查法／產生回答／再建議一個）全部走這裡——
格式只有一份，才 grep 得出來（例如 grep "kind=embed" 只看轉向量花多久）。

不計時的東西（design4.md §5.1 明文）：PDF 渲染、存檔、縮圖、SQL、WebRTC、QR、
開關的 GET／PUT——那些不是模型推論。

本檔不吞例外：區塊裡爆炸時照樣打結束行（標 ok=false），然後把原始例外
原封不動往外丟——422／500／fallback 的語意一個字都不變（design4 §5.3）。
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Iterator

from app.core import config

# 名字一定要是 __name__（＝app.services.ai_timing）：main.py 把 handler 掛在
# 「app」這個 logger 上，取成別的名字就不在 app.* 底下，終端機一片安靜
logger = logging.getLogger(__name__)

# model／note 都可能來自部署設定或模型輸出。每個動態值最多保留這麼多字，
# 避免一筆 timing log 被異常內容撐到幾萬字；截斷發生在欄位層，五個必要欄位不受影響。
LOG_VALUE_MAX_CHARS: Final = 256


@dataclass(frozen=True, slots=True)
class AiTarget:
    """一次 AI 呼叫實際選定的後端與模型；建構後不可被開關改寫。"""

    backend: str
    model: str


def _安全log值(value: str) -> str:
    單行 = "".join(字元 if 字元.isprintable() else " " for 字元 in value)
    if len(單行) <= LOG_VALUE_MAX_CHARS:
        return 單行
    return 單行[: LOG_VALUE_MAX_CHARS - 1] + "…"


def _目標(kind: str) -> AiTarget:
    """這一種呼叫會打到哪裡、用哪顆模型（design4.md §5.1 的表）。

    ★ config.AI_BACKEND 一定要在這裡「即時讀」：它是頁首那顆本機／雲端開關
      撥動的執行中狀態，import 進來就會定死成伺服器啟動當下的值。
    """
    if kind == "embed":
        # 向量永遠本機：庫裡既有的向量是本機 bge-m3 算的，換一顆就比不出東西，
        # 所以 embeddings 從來不歸那顆開關管（dependencies.py 的 get_embeddings）。
        return AiTarget(backend="local", model=config.EMBEDDING_MODEL)

    是雲端 = config.AI_BACKEND == "cloud"
    if kind == "vlm":
        return AiTarget(
            backend=config.AI_BACKEND,
            model=config.OLLAMA_CLOUD_VLM_MODEL if 是雲端 else config.VLM_MODEL,
        )
    if kind in ("route", "answer", "entity_suggest"):
        return AiTarget(
            backend=config.AI_BACKEND,
            model=config.OLLAMA_CLOUD_LLM_MODEL if 是雲端 else config.LLM_MODEL,
        )
    # 打錯 kind 的 log 會變成 grep 不到的孤兒，寧可當場炸給實作者看
    raise ValueError(  # noqa: GENERIC_ERR_OK - 維持既有 unknown-kind API
        f"未知的 AI 呼叫種類：{kind}"
    )


@dataclass(slots=True)  # noqa: MUTABLE_OK - with 區塊內由呼叫端填 note
class AiCall:
    """交給 with 區塊的小物件，目前只有一個用途：讓呼叫端補一句人類看的摘要。

    例：with log_ai("vlm") as 計時: … 計時.note = f"text {n} 字"
    摘要會接在結束行的最後面，五個必要欄位仍在它前面（design4.md §5.2）。
    """

    note: str = ""


@contextmanager
def log_ai(kind: str, *, target: AiTarget | None = None) -> Iterator[AiCall]:
    """把一次 AI 呼叫包起來，前後各打一行。

    kind：vlm／embed／route／answer／entity_suggest 五選一。

    ★ 先算 backend／model 再打開始行：kind 打錯時要在「一行 log 都還沒打」的
      狀態下炸掉，不然終端機會留下一個永遠等不到結束行的孤兒開始行。
    """
    # target 有傳進來時仍呼叫一次 _目標：只利用它驗證 kind，維持未知種類在
    # 「一行 log 都還沒打」時就拋錯的既有語意；實際欄位則使用 request 已選定的 target。
    預設目標 = _目標(kind)
    實際目標 = target if target is not None else 預設目標
    抬頭 = (
        f"kind={_安全log值(kind)} "
        f"backend={_安全log值(實際目標.backend)} "
        f"model={_安全log值(實際目標.model)}"
    )
    logger.info("AI 開始 %s", 抬頭)

    這次 = AiCall()
    起點 = time.monotonic()      # 只會往前走的時鐘，量時間差要用它
    成功 = True
    try:
        yield 這次
    except BaseException:  # noqa: BROAD_EXCEPT_OK - 記錄後原樣重拋，含關機訊號
        # 不做任何處理，只記下「這次失敗了」，然後原封不動往外丟。
        # 抓最寬的 BaseException 是因為 Ctrl+C 與 uvicorn 關機丟的不是
        # Exception 的子類，用窄的那個會漏掉結束行。
        成功 = False
        raise
    finally:
        # 一定是 finally 不是 else：else 只有沒例外時才跑，失敗就不會打結束行了
        秒數 = time.monotonic() - 起點
        摘要 = f" {_安全log值(這次.note)}" if 這次.note else ""
        logger.info(
            # %.1f 而不是 str(秒數)：假件跑得極快，秒數可能是 1.9e-05，
            # 印成科學記號就毀了對齊與 grep（格式化之後會是 0.0，正是我們要的）
            "AI 結束 %s elapsed_s=%.1f ok=%s%s",
            抬頭,
            秒數,
            "true" if 成功 else "false",
            摘要,
        )
