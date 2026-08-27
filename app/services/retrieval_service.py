"""檢索服務：四條查法，全部把結果組裝成同一種 Document 交給回答節點。

  metadata／vector ＝查照片本身（Phase 9），兩者都可套用 30 天時間過濾。
  entity           ＝沿別針列出掛在某個實體上的照片（Phase 34）。
  task             ＝查待辦表（Phase 34）。

SQL 一律寫在 repositories/photo_repository.py，這裡只負責決定
「用哪一條、帶什麼條件」，並把資料庫的一列列資料組裝成 LangChain 的 Document。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import chain

from app.core import config
from app.repositories import photo_repository
from app.services import ai_timing, indexing_service


@dataclass
class QueryFilters:
    """從問題抽出來的過濾條件，每一個都可以是空的。

    值是 route 從問題裡抽出來的原文（中文問題抽中文、英文問題抽英文），
    比對交給 SQL 的 ILIKE；系統不做跨語言翻譯（design.md §8.3 的已知限制）。

    六個欄位分成三組，各自只有對應的那條查法會讀：
      前四個   ＝metadata／vector 路要的（Phase 9）
      entity_name     ＝entity 路要的（Phase 34）
      due_within_days ＝task 路要的（Phase 34）
    刻意全部放同一個容器、不為新的兩路另開類別：AskState 只帶一個 filters，
    多一個容器就得多一組「哪一路該看哪一個」的規則，反而更難讀。
    """

    category: str | None = None
    location: str | None = None
    item: str | None = None
    recent: bool = False  # 問題是否含「最近／recently」這類時間條件
    # 實體路：問句指名的那件東西。名稱由 route 從「現有實體清單」裡挑，
    # 所以這裡拿到的通常已是清單原文；大小寫與空白仍由 find_entity_by_name 兜底。
    entity_name: str | None = None
    # 待辦路：「這週」＝7、「這個月」＝30；None ＝不限期限（全部待辦）
    due_within_days: int | None = None


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
    # 只有這一條路會把問題轉成向量——metadata／entity／task 三路都不必，
    # 所以 log 上「有沒有 kind=embed」就看得出這次走的是哪一種查法（design4.md §5.2）。
    # 只包這一行：底下的 search_by_vector 與組裝是查 SQL 與資料處理，
    # 包進去只會讓 elapsed_s 說謊（把資料庫時間算成模型時間）。
    with ai_timing.log_ai("embed", target=indexing_service.embedding_timing_target(embeddings)):
        question_vector = embeddings.embed_query(question)
    rows = photo_repository.search_by_vector(
        embedding=question_vector,
        recent=filters.recent,
        today=today,
        limit=config.TOP_K,
    )
    return [row_to_document(row) for row in rows]


def entity_search(entity_name: str | None) -> list[Document]:
    """實體路：沿別針列出掛在該實體上的照片（Phase 34）。

    對不到實體（沒給名字、或名字查不到）就回空清單，**不 fallback 去語意查詢**：
    使用者已經指名了某一件具體東西，硬塞幾張猜的照片比誠實說「沒有」更糟。
    空清單交到 generate 節點，由 LLM 依鐵律 2 回「查無相關照片」。

    已知限制（MVP 刻意為之）：這一路不套 filters.recent 的 30 天過濾——
    「跟我 MacBook 有關的**全部**」本來就該回全部；別針通常沒幾張，
    先過濾反而會把使用者指名要的東西默默藏掉。

    ── Ruling-9 修正（真模型煙霧實證）──────────────────────────────
    釘選是**使用者手動宣告**的關聯，不是照片內容自己講出來的——電費單被釘上
    「我的 MacBook」時，電費單的文字裡當然不會出現「MacBook」三個字。
    若原樣把 row_to_document 組出來的 Document（只有照片描述＋metadata）
    交給回答節點，ANSWER_PROMPT 鐵律 1（只依檢索到的照片內容回答）會讓
    LLM **誠實地**判斷「內容沒提到，所以查無」——即使檢索早就沿別針
    撈對了照片（retrieved_photo_ids 正確，answer 卻自相矛盾）。

    修法比照 task_to_document 讓 Document 自述身分的做法：在
    page_content **最前面**加一行釘選事實，讓模型不必靠內容猜、
    直接看得到「這張照片為什麼會出現在這裡」。只在這裡（entity_search）
    包一層、不改 row_to_document 本身——metadata／vector 兩路的照片
    是靠內容或條件比對出來的，不需要也不該被這行影響。
    """
    if not entity_name:
        return []

    entity = photo_repository.find_entity_by_name(entity_name)
    if entity is None:
        return []

    rows = photo_repository.list_photos_with_entity(entity["id"])
    # 釘選事實擺最前面、單獨一行；用的是資料庫裡的**清單原文**（entity["name"]），
    # 不是使用者問句裡的寫法（entity_name 參數可能大小寫或空白不同，
    # find_entity_by_name 已經 lower()＋trim() 兜過一輪，回傳的才是正確名稱）。
    pin_note = f"（這張照片被使用者釘上實體「{entity['name']}」，與問題所指的東西直接相關）\n"
    documents = [row_to_document(row) for row in rows]
    for document in documents:
        document.page_content = pin_note + document.page_content
    return documents


def task_to_document(row: dict[str, Any]) -> Document:
    """把待辦的一列組成 Document。

    metadata["id"] 放的是**來源照片 id** 而不是待辦 id——回應欄位叫
    `retrieved_photo_ids`，契約是「回照片 id」，待辦路不該偷偷換成別的號碼
    （使用者拿這個 id 就能去 /photos/{id}/image 看原圖）。

    page_content 同時帶標題、到期日與來源照片描述：只給標題的話，
    LLM 回答「這週要交什麼」時講得出事情、卻講不出這件事是從哪張照片來的。
    沒有到期日就寫「無」，不要把 None 直接印進去給模型看。
    """
    due = row["due_date"].isoformat() if row["due_date"] else "無"
    return Document(
        page_content=f"待辦：{row['title']}（到期 {due}）\n來源照片：{row['text']}",
        metadata={"id": row["photo_id"]},
    )


def task_search(due_within_days: int | None, today: date) -> list[Document]:
    """待辦路：查待辦表（Phase 34）。

    「這週要交什麼」的天數由 route 抽成 due_within_days，在這裡才換算成日期——
    repository 只認日期（純粹的資料層），「今天是哪天」是注入進來的，
    測試才固定得住（與 30 天過濾把 today 一路傳下去是同一個做法）。

    已知限制（MVP 刻意為之）：這一路不套 filters.recent 的 30 天過濾——
    待辦有自己的時間軸（到期日），「最近」對它的意思由 due_within_days 承擔；
    再疊一層「照片上傳時間 30 天」只會把還沒到期的正事過濾不見。
    """
    # 用 is not None 而不是直接判斷真假值：0 天（＝只問今天到期的）是合法答案，
    # 寫成 if due_within_days 會把它悄悄變成「不限期限，全部都回」——正好相反。
    due_before = today + timedelta(days=due_within_days) if due_within_days is not None else None
    rows = photo_repository.search_tasks(due_before=due_before)
    return [task_to_document(row) for row in rows]


@chain
def photo_retriever(request: dict[str, Any]) -> list[Document]:
    """自訂 retriever（LangChain 官方示範的 @chain 寫法）。

    request 需要五個鍵：
      question   : 使用者的問題（中文或英文）
      mode       : "metadata"／"vector"／"entity"／"task"
      filters    : QueryFilters
      today      : 詢問當下的日期
      embeddings : 產生向量的元件（正式是 Ollama，測試是假件）

    vector 放在最後當 else：路由判不出來時的 fallback 就是它，
    寫成「其餘一律語意查詢」比多列一個 == "vector" 更貼近那條規則。
    """
    filters: QueryFilters = request["filters"]
    today: date = request["today"]
    mode = request["mode"]

    if mode == "metadata":
        return metadata_search(filters, today)
    if mode == "entity":
        return entity_search(filters.entity_name)
    if mode == "task":
        return task_search(filters.due_within_days, today)
    return vector_search(request["question"], request["embeddings"], filters, today)
