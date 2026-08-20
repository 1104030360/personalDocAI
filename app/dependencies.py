"""依賴注入點：router 用 Depends(...) 取用；pytest 才用 dependency_overrides 換成假件。

追正式上傳：get_vlm() → OllamaVLM。不要在這個檔找 FakeVLM（它在 tests/）。

design.md §4.2：get_vlm / get_embeddings / get_now 是三個主要注入點；
詢問流程另外需要 get_router / get_answerer / get_today（Phase 11 已補上）。
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from fastapi import Depends
from langchain_core.embeddings import Embeddings

from app.services import ask_workflow, indexing_service, vlm_service


@lru_cache(maxsize=1)
def _ollama_vlm() -> vlm_service.OllamaVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線）。"""
    return vlm_service.OllamaVLM()


@lru_cache(maxsize=1)
def _ollama_embeddings() -> Embeddings:
    return indexing_service.build_ollama_embeddings()


def get_vlm() -> vlm_service.VLMClient:
    """給 router 的看圖物件。正式執行永遠是 OllamaVLM。

    pytest 若要換成 FakeVLM：app.dependency_overrides[get_vlm] = ...
    那個覆寫只活在測試裡，不影響 uvicorn。
    """
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


def get_router() -> ask_workflow.RouterClient:
    return _ollama_router()


def get_answerer() -> ask_workflow.AnswerClient:
    return _ollama_answerer()


def get_today(now: datetime | None = Depends(get_now)) -> date:
    """詢問當下的日期，供「最近 30 天」使用。

    測試把 get_now 換成固定時間時，這裡也會跟著變成固定日期。
    """
    return now.date() if now is not None else date.today()
