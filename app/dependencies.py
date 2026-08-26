"""依賴注入點：router 用 Depends(...) 取用；pytest 才用 dependency_overrides 換成假件。

追正式上傳：get_vlm() → OllamaVLM（開關撥到「雲端」時 → OllamaCloudVLM）。
不要在這個檔找 FakeVLM（它在 tests/）。

AI 後端開關（config.AI_BACKEND，2026-08-22）管四個注入點：get_vlm／get_router／
get_answerer／get_entity_suggester——每個都是「本機類別或雲端類別」二選一。
get_embeddings 永遠本機：向量必須跟資料庫裡既有的 bge-m3 向量同源。

design.md §4.2：get_vlm / get_embeddings / get_now 是三個主要注入點；
詢問流程另外需要 get_router / get_answerer / get_today（Phase 11 已補上）；
「再建議一個實體」另有 get_entity_suggester（Phase 30 加入）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache
from typing import Protocol

from fastapi import Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import (
    ask_workflow,
    entity_suggestion_service,
    indexing_service,
    ingest_job_store,
    vlm_service,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _ollama_vlm() -> vlm_service.OllamaVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線）。"""
    return vlm_service.OllamaVLM()


@lru_cache(maxsize=1)
def _ollama_embeddings() -> Embeddings:
    return indexing_service.build_ollama_embeddings()


@lru_cache(maxsize=1)
def _ollama_cloud_vlm() -> vlm_service.OllamaCloudVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線，與 _ollama_vlm 同理）。"""
    return vlm_service.OllamaCloudVLM()


def get_vlm() -> vlm_service.VLMClient:
    """給 router 的看圖物件。跟著頁首的 AI 開關走：本機（預設）或 Ollama Cloud。

    每個請求都當場讀一次 config.AI_BACKEND——開關撥完，下一次上傳立刻生效。

    pytest 若要換成 FakeVLM：app.dependency_overrides[get_vlm] = ...
    那個覆寫只活在測試裡，不影響 uvicorn。
    """
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_vlm()
    return _ollama_vlm()


def get_embeddings() -> Embeddings:
    return _ollama_embeddings()


def get_now() -> datetime | None:
    """『現在時間』。

    正式執行回傳 None，代表上傳時間交給資料庫的 now() 自動記錄。
    測試需要固定時間時，用 dependency_overrides 換成 FixedClock。
    """
    return None


@lru_cache(maxsize=1)
def _ollama_router() -> ask_workflow.OllamaRouter:
    return ask_workflow.OllamaRouter()


@lru_cache(maxsize=1)
def _ollama_answerer() -> ask_workflow.OllamaAnswerer:
    return ask_workflow.OllamaAnswerer()


@lru_cache(maxsize=1)
def _ollama_cloud_router() -> ask_workflow.OllamaCloudRouter:
    return ask_workflow.OllamaCloudRouter()


@lru_cache(maxsize=1)
def _ollama_cloud_answerer() -> ask_workflow.OllamaCloudAnswerer:
    return ask_workflow.OllamaCloudAnswerer()


def get_router() -> ask_workflow.RouterClient:
    """判斷查法的模型。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_router()
    return _ollama_router()


def get_answerer() -> ask_workflow.AnswerClient:
    """產生回答的模型。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_answerer()
    return _ollama_answerer()


@lru_cache(maxsize=1)
def _ollama_entity_suggester() -> entity_suggestion_service.OllamaEntitySuggester:
    """只建立一次（建立物件本身不會連線，與 _ollama_vlm 同理）。"""
    return entity_suggestion_service.OllamaEntitySuggester()


@lru_cache(maxsize=1)
def _ollama_cloud_entity_suggester() -> (
    entity_suggestion_service.OllamaCloudEntitySuggester
):
    return entity_suggestion_service.OllamaCloudEntitySuggester()


def get_entity_suggester() -> entity_suggestion_service.EntitySuggesterClient:
    """給「再建議一個實體」端點的物件。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_entity_suggester()
    return _ollama_entity_suggester()


def get_today(now: datetime | None = Depends(get_now)) -> date:
    """詢問當下的日期，供「最近 30 天」使用。

    測試把 get_now 換成固定時間時，這裡也會跟著變成固定日期。
    """
    return now.date() if now is not None else date.today()


# ---------- 入庫任務的狀態存放處（Phase 57；design5.md §4.3）----------


@lru_cache(maxsize=1)
def _memory_job_store() -> ingest_job_store.InMemoryJobStore:
    """整個行程共用同一個記憶體 store。

    @lru_cache(maxsize=1) 就是本專案的「只建立一次」寫法（與 _ollama_vlm 同一招）。
    不共用的話，每個 HTTP 請求都會拿到一個全新的空 store，
    上一個請求建的 job 下一個請求就查不到了。
    """
    return ingest_job_store.InMemoryJobStore()


def get_job_store() -> ingest_job_store.JobStore:
    """任務狀態存放處的唯一取用入口。

    現在一律回記憶體實作。**Phase 65** 會改成「有設定 CELERY_BROKER_URL 就回
    RedisJobStore」——正式環境的 app 與 worker 是兩個行程，記憶體版彼此看不到。

    ⚠ 它有兩種呼叫端，pytest 攔截的方法**不一樣**（Phase 65 起兩種都會出現）：
      1. router 參數列上的 Depends(get_job_store)——測試用
         app.dependency_overrides[get_job_store] 換（只有 FastAPI 解析 Depends 時才查表）。
      2. 把它當**普通函式直接呼叫**——Phase 65 的 app 啟動掃把（main.py 的 lifespan）
         與 Celery 的 ingest_task（它們不是 HTTP 請求，沒有 Depends 可攔）。
         這種呼叫 dependency_overrides 根本看不到，測試靠 conftest 的
         monkeypatch.setattr 換掉本函式（wire_memory_job_store 安全網的第二管）。
         ★ 因此直接呼叫端一律要寫「from app import dependencies」＋
           「dependencies.get_job_store()」——呼叫當下才解析模組屬性，monkeypatch
           換得掉；寫成「from app.dependencies import get_job_store」再呼叫是早綁定，
           換不掉（見 tests/conftest.py 的說明與本 phase 常見陷阱 7）。
      拿到 store 之後怎麼用：run_ingest_job() 仍是**明寫參數**收它
      （Phase 59 的簽章約定——store 是參數，不是任務本體裡的隱形全域）。
    """
    return _memory_job_store()


# ---------------- 入庫任務的入列器（增量五 Phase 62）----------------
#
# 「入列」＝把一個 job_id 丟出去，讓別人去做。誰接住它，Phase 62〜64 與
# Phase 65 之後是不一樣的：
#   Phase 62〜64：NoopDispatcher（沒有人接住——Celery 還沒建，這是**預期**的）
#   Phase 65 起  ：get_task_dispatcher() 本體換成「回傳 app/celery_app.py 的
#                  CeleryDispatcher」，它的 dispatch() 把 job_id 交給
#                  ingest_task.delay()（丟進 Redis，由 worker 容器接住）
# 換的時候只改 get_task_dispatcher() 這一個函式，router 一個字都不動。


class TaskDispatcher(Protocol):
    """把一筆入庫任務丟出去的入列器。介面只有一個具名方法 dispatch()。

    用法：dispatcher.dispatch(job_id)。**不是**把 dispatcher 本身當函式直接呼叫——
    具名方法讓 router 那一行自己會說話；Phase 65 的正式實作 CeleryDispatcher
    （住在 app/celery_app.py，全系統唯一碰 Celery 的地方）與 Phase 65 測試安全網
    的假派工也都有同一個 dispatch() 方法，三邊同形、換裝時誰都不必動。

    參數**只有 job_id**：檔案內容在 data/staging/、其餘欄位在 JobStore，
    佇列裡只放一個字串（design5.md §4.1 明文禁止把影像位元組當任務參數）。
    """

    def dispatch(self, job_id: str) -> None: ...


class NoopDispatcher:
    """什麼都不做的入列器（Phase 62〜64 的正式實作）。

    ⚠ 這代表**照片不會真的入庫**——Celery 要到 Phase 65 才存在。
    刻意不在這裡「就地跑完」（eager）：那會讓 HTTP 回了 202 卻仍然卡住
    2〜5 分鐘等 VLM，比同步的 201 更難懂，也會把真模型的推論
    塞進 uvicorn 的請求執行緒（Phase 48 已踩過會把資料庫壓垮）。

    log 留 INFO 一行：手動測試時看得到「有收下、但沒有人接手」。
    """

    def dispatch(self, job_id: str) -> None:
        logger.info(
            "任務已建立但尚未入列（Phase 65 接上 Celery 之前這是預期行為）：job_id=%s",
            job_id,
        )


def get_task_dispatcher() -> TaskDispatcher:
    """給 router 的入列器。

    Phase 65 要接上 Celery 時，把這個函式的**本體**換成：
    「函式內 `from app.celery_app import CeleryDispatcher`，
    回傳 `CeleryDispatcher()`」——它的 dispatch() 把 job_id 交給
    `ingest_task.delay()`。完整程式碼在 phase-65 §4.5「改動三」，
    **就改這一個函式**。
    """
    return NoopDispatcher()
