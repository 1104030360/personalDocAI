"""檢索服務：條件查詢與語意查詢，兩者都可套用 30 天時間過濾。

SQL 一律寫在 repositories/photo_repository.py，這裡只負責決定
「用哪一條、帶什麼條件」，並把資料庫的一列列資料組裝成 LangChain 的 Document。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import chain

from app.core import config
from app.repositories import photo_repository
from app.services import indexing_service


@dataclass
class QueryFilters:
    """從問題抽出來的過濾條件，四個都可以是空的。

    值是 route 從問題裡抽出來的原文（中文問題抽中文、英文問題抽英文），
    比對交給 SQL 的 ILIKE；系統不做跨語言翻譯（design.md §8.3 的已知限制）。
    """

    category: str | None = None
    location: str | None = None
    item: str | None = None
    recent: bool = False   # 問題是否含「最近／recently」這類時間條件


def row_to_document(row: dict[str, Any]) -> Document:
    """把資料庫的一列照片組成 Document（內容格式與寫入時完全一致）。"""
    content_time = row["content_time"].isoformat() if row["content_time"] else None
    document = indexing_service.build_document(
        text=row["text"],
        category=row["category"],
        location=row["location"],
        items=list(row["items"]),
        content_time=content_time,
    )
    document.metadata["id"] = row["id"]
    return document


def metadata_search(filters: QueryFilters, today: date) -> list[Document]:
    """條件查詢：用固定欄位過濾（ILIKE，不分大小寫）。"""
    rows = photo_repository.search_by_metadata(
        category=filters.category,
        location=filters.location,
        item=filters.item,
        recent=filters.recent,
        today=today,
    )
    return [row_to_document(row) for row in rows]


def vector_search(
    question: str,
    embeddings: Embeddings,
    filters: QueryFilters,
    today: date,
) -> list[Document]:
    """語意查詢：問題轉成向量，找最接近的 TOP_K 張。"""
    question_vector = embeddings.embed_query(question)
    rows = photo_repository.search_by_vector(
        embedding=question_vector,
        recent=filters.recent,
        today=today,
        limit=config.TOP_K,
    )
    return [row_to_document(row) for row in rows]


@chain
def photo_retriever(request: dict[str, Any]) -> list[Document]:
    """自訂 retriever（LangChain 官方示範的 @chain 寫法）。

    request 需要五個鍵：
      question   : 使用者的問題（中文或英文）
      mode       : "metadata" 或 "vector"
      filters    : QueryFilters
      today      : 詢問當下的日期
      embeddings : 產生向量的元件（正式是 Ollama，測試是假件）
    """
    filters: QueryFilters = request["filters"]
    today: date = request["today"]

    if request["mode"] == "metadata":
        return metadata_search(filters, today)
    return vector_search(request["question"], request["embeddings"], filters, today)
