"""把文字＋四個 metadata 欄位合併成 Document，再轉成向量。"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from app.core import config


def build_document(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: str | None,
) -> Document:
    """把文字與四個欄位合併成一份 Document。

    合併順序固定為「文字 / 類別 / 地點 / 物品 / 時間」，空欄位直接省略。
    順序固定，同樣的輸入才會得到同樣的向量——這是測試可行的前提。

    欄位標籤（類別/地點/物品/時間）一律用中文，**不隨內容語言改變**：
    標籤只是把欄位串起來的固定格式，換來換去反而讓「同輸入同向量」不成立。
    欄位的「值」則保持原文（英文照片就是英文），跨語言比對交給多語 embedding。
    """
    lines = [text]
    if category:
        lines.append(f"類別: {category}")
    if location:
        lines.append(f"地點: {location}")
    if items:
        lines.append("物品: " + "、".join(items))
    if content_time:
        lines.append(f"時間: {content_time}")

    return Document(
        page_content="\n".join(lines),
        metadata={
            "category": category,
            "location": location,
            "items": items,
            "content_time": content_time,
        },
    )


def build_ollama_embeddings() -> OllamaEmbeddings:
    """正式用的向量產生器：本機 Ollama 的 bge-m3（多語模型）。"""
    return OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def embed_document(embeddings: Embeddings, document: Document) -> list[float]:
    """把 Document 的內容轉成向量。

    刻意用 embed_query（一段文字進、一條向量出）：上傳存的內容和之後
    詢問的問題走**同一種轉法**，兩邊的向量才落在同一個空間、才能比較。
    """
    return embeddings.embed_query(document.page_content)
