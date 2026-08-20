"""LangGraph 流程圖：判斷（route）→ 查詢 → 回答（generate，Phase 11 加入）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.core import config
from app.services import retrieval_service
from app.services.retrieval_service import QueryFilters


# --------------------------- 路由的輸出格式 ---------------------------
class RouteDecision(BaseModel):
    """一次 LLM 呼叫同時回傳「查法」與「過濾條件」。"""

    mode: Literal["metadata", "vector"]
    category: str | None = None   # 例：收據 / Receipt
    location: str | None = None   # 例：Target
    item: str | None = None       # 例：可樂 / Cola
    recent: bool = False          # 問題是否含「最近／recently」這類時間條件


ROUTE_PROMPT = """你要判斷使用者的問題應該用哪一種方式查照片，並抽出過濾條件。
使用者的問題可能是中文，也可能是英文，兩種都要能處理。

兩種查法：
- metadata：問題帶明確的過濾條件（商家、類別、時間等精確值）
- vector  ：問題是語意／內容描述型，沒有明確的精確值條件

參考例子（中英文各有）：
- 問題「有哪些在 Target 拍的收據？」
  → mode=metadata, category=收據, location=Target, recent=false
- 問題「我最近買過什麼飲料？」
  → mode=vector, recent=true
- 問題 "What drinks did I buy recently?"
  → mode=vector, recent=true
- 問題 "Which receipts were taken at Target?"
  → mode=metadata, location=Target, recent=false

其他規則：
- 問題若含「最近」「這幾天」"recently"、"lately"、"in the last few days"
  這類時間說法，recent 填 true，否則 false。
- 抽出的條件值**照問題裡的原文寫**，不要翻譯（問題寫 Target 就填 Target，
  寫「收據」就填「收據」）。
- 抽不出來的條件一律填 null。
- 你無法判斷時，mode 填 vector。

使用者的問題：{question}
"""


class RouterClient(Protocol):
    """判斷查法的介面。正式用 OllamaRouter，測試用 FakeRouter。"""

    def route(self, question: str) -> RouteDecision:
        ...


class OllamaRouter:
    """用本機 Ollama 的模型判斷查法。

    失敗不在這裡處理——一律往外丟，由 route 節點統一 fallback，
    這樣「失敗就走語意查詢」只有一個地方負責。
    """

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model = ChatOllama(
            model=model or config.LLM_MODEL,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(RouteDecision)

    def route(self, question: str) -> RouteDecision:
        message = HumanMessage(content=ROUTE_PROMPT.format(question=question))
        return self._model.invoke([message])


ANSWER_PROMPT = """你要根據「檢索到的照片內容」回答使用者的問題。

三條鐵律：
1. 只能依據下面提供的照片內容回答，不得使用任何外部知識補充。
2. 如果下面沒有任何照片內容，就直接回覆「查無相關照片」的意思，
   絕對不可以虛構任何照片或內容。
3. **回答語言必須跟隨使用者提問的語言**：
   - 使用者用中文問 → 用繁體中文回答。
   - 使用者用英文問（例如 "What drinks did I buy recently?"）→ 用英文回答。
   照片內容本身是什麼語言就照抄什麼語言，不要翻譯照片內容；
   只有你自己寫的句子要跟隨提問語言。
   直接回答，不要說明你的推理過程。

使用者的問題：{question}

檢索到的照片內容：
{context}
"""


class AnswerClient(Protocol):
    """產生回答的介面。正式用 OllamaAnswerer，測試用 FakeAnswerLLM。"""

    def answer(self, question: str, documents: list[Document]) -> str:
        ...


class OllamaAnswerer:
    """用本機 Ollama 的模型依照片內容產生回答。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self._model = ChatOllama(
            model=model or config.LLM_MODEL,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        )

    def answer(self, question: str, documents: list[Document]) -> str:
        if documents:
            context = "\n\n".join(
                f"[照片 {doc.metadata['id']}]\n{doc.page_content}" for doc in documents
            )
        else:
            context = "（沒有找到任何照片 / no photos found）"

        message = HumanMessage(
            content=ANSWER_PROMPT.format(question=question, context=context)
        )
        return self._model.invoke([message]).text


# ------------------------------ 流程狀態 ------------------------------
class AskState(TypedDict):
    """在流程圖裡一路傳下去的資料。"""

    question: str
    mode: str                    # "metadata" | "vector"
    filters: QueryFilters        # category / location / item / recent（皆可空）
    retrieved: list[Document]    # 每份 Document 帶 id（metadata）＋文字與四欄位（內容）
    answer: str


@dataclass
class AskDeps:
    """詢問流程要用到的外部相依，全部從外面注入，測試才好換成假件。"""

    router: RouterClient
    answerer: AnswerClient
    embeddings: Embeddings
    today: date                  # 詢問當下的日期，供 30 天過濾使用


# ------------------------------ 流程圖 -------------------------------
def build_workflow(deps: AskDeps):
    """組出流程圖並編譯成可執行物件。"""

    def route_node(state: AskState) -> dict[str, Any]:
        """判斷查法。任何失敗都 fallback 成語意查詢、條件全空。"""
        try:
            decision = deps.router.route(state["question"])
        except Exception:
            decision = None

        if not isinstance(decision, RouteDecision):
            decision = RouteDecision(mode="vector")

        return {
            "mode": decision.mode,
            "filters": QueryFilters(
                category=decision.category,
                location=decision.location,
                item=decision.item,
                recent=decision.recent,
            ),
        }

    def pick_branch(state: AskState) -> str:
        """條件邊：看 state 裡的 mode 決定走哪一條。"""
        return "metadata" if state["mode"] == "metadata" else "vector"

    def _retrieve(state: AskState, mode: str) -> dict[str, Any]:
        documents = retrieval_service.photo_retriever.invoke(
            {
                "question": state["question"],
                "mode": mode,
                "filters": state["filters"],
                "today": deps.today,
                "embeddings": deps.embeddings,
            }
        )
        return {"retrieved": documents}

    def retrieve_metadata_node(state: AskState) -> dict[str, Any]:
        return _retrieve(state, "metadata")

    def retrieve_vector_node(state: AskState) -> dict[str, Any]:
        return _retrieve(state, "vector")

    def generate_node(state: AskState) -> dict[str, Any]:
        """只依撈到的照片內容產生回答；撈不到就由 LLM 回覆查無相關照片。"""
        return {"answer": deps.answerer.answer(state["question"], state["retrieved"])}

    graph = StateGraph(AskState)
    graph.add_node("route", route_node)
    graph.add_node("retrieve_metadata", retrieve_metadata_node)
    graph.add_node("retrieve_vector", retrieve_vector_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        pick_branch,
        {"metadata": "retrieve_metadata", "vector": "retrieve_vector"},
    )
    graph.add_edge("retrieve_metadata", "generate")
    graph.add_edge("retrieve_vector", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


def run_ask(question: str, deps: AskDeps) -> AskState:
    """跑一次完整流程，回傳最後的 state。"""
    workflow = build_workflow(deps)
    initial: AskState = {
        "question": question,
        "mode": "vector",
        "filters": QueryFilters(),
        "retrieved": [],
        "answer": "",
    }
    return workflow.invoke(initial)
