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

from datetime import date, datetime
from functools import lru_cache

from fastapi import Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import (
    ask_workflow,
    entity_suggestion_service,
    indexing_service,
    vlm_service,
)


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
