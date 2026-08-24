"""LangGraph 流程圖：判斷（route）→ 查詢 → 回答（generate，Phase 11 加入）。

查詢那一段自 Phase 34 起是四選一（design3.md D14、§6）：
照片條件查／照片語意查／實體別針查／待辦查。四路都只是「條件邊挑一個節點」，
仍然一次路由呼叫、一次回答呼叫——不做會自己開工具的 agent（design3.md §1.2 已否決）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol, TypedDict

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core import config
from app.services import ai_timing, ollama_cloud, retrieval_service
from app.services.retrieval_service import QueryFilters

logger = logging.getLogger(__name__)


# --------------------------- 路由的輸出格式 ---------------------------
class RouteDecision(BaseModel):
    """一次 LLM 呼叫同時回傳「查法」與「過濾條件」。

    Phase 34 起查法從二選一變四選一（design3.md D14、§6），
    因此多了兩個只服務新查法的欄位（entity_name／due_within_days）。
    仍然只呼叫一次模型：多一次呼叫就多一次失敗機會、也多等一次推論。
    """

    mode: Literal["metadata", "vector", "entity", "task"]
    category: str | None = None   # 例：收據 / Receipt
    location: str | None = None   # 例：Target
    item: str | None = None       # 例：可樂 / Cola
    recent: bool = False          # 問題是否含「最近／recently」這類時間條件
    # entity 路：問句指名的那件東西，必須是「現有實體清單」裡的名稱原文
    entity_name: str | None = None
    # task 路：「這週」＝7、「這個月」＝30；null ＝沒講期限，列出全部待辦。
    # ge/le＝把範圍檢查擋在「模型輸出進系統」的這一關：模型幻覺出負數或
    # 天文數字（10 億天會讓 timedelta 直接 OverflowError → 500）時，
    # 結構化輸出解析失敗＝路由失敗＝走既有的 fallback vector——
    # 比在檢索層默默 clamp 成「十年內」誠實（那是改寫使用者沒說過的話）。
    due_within_days: int | None = Field(default=None, ge=0, le=3650)


class _InvalidRouteDecisionError(TypeError):
    def __init__(self, actual_type: str) -> None:
        super().__init__(f"expected RouteDecision, got {actual_type}")


ROUTE_PROMPT = """你要判斷使用者的問題應該用哪一種方式查資料，並抽出過濾條件。
使用者的問題可能是中文，也可能是英文，兩種都要能處理。

四種查法：
- metadata：問題帶明確的過濾條件（商家、類別、時間等精確值）
- vector  ：問題是語意／內容描述型，沒有明確的精確值條件
- entity  ：問題指名下面「現有實體清單」裡的某一件具體東西（某台筆電、某個專案）
- task    ：問題問的是待辦事項——要交什麼、什麼時候到期、還有哪些事沒做

現有實體清單（entity 查法只能從這裡挑一個名字）：
{entities}

參考例子（中英文各有）：
- 問題「有哪些在 Target 拍的收據？」
  → mode=metadata, category=收據, location=Target, recent=false
- 問題「我最近買過什麼飲料？」
  → mode=vector, recent=true
- 問題 "What drinks did I buy recently?"
  → mode=vector, recent=true
- 問題 "Which receipts were taken at Target?"
  → mode=metadata, location=Target, recent=false
- 問題「跟我 MacBook 有關的全部」（清單裡有「我的 MacBook」）
  → mode=entity, entity_name=我的 MacBook
- 問題 "Show me everything about my MacBook"（清單裡有「我的 MacBook」）
  → mode=entity, entity_name=我的 MacBook
- 問題「這週要交什麼？」
  → mode=task, due_within_days=7
- 問題 "What is due this week?"
  → mode=task, due_within_days=7

其他規則：
- 問題若含「最近」「這幾天」"recently"、"lately"、"in the last few days"
  這類時間說法，recent 填 true，否則 false。
- 抽出的條件值**照問題裡的原文寫**，不要翻譯（問題寫 Target 就填 Target，
  寫「收據」就填「收據」）。**唯一的例外是 entity_name**：它要拿去對資料，
  所以一律照「現有實體清單」裡的名稱原文填，不管問題是用什麼語言問的。
- 清單裡找不到相符的東西時**不可以自創 entity_name**，改用 vector。
- due_within_days 只在 mode=task 時填：「這週」"this week" 填 7、
  「這個月」"this month" 填 30；問題沒講期限就填 null（＝列出全部待辦）。
- 抽不出來的條件一律填 null。
- 你無法判斷時，mode 填 vector。

使用者的問題：{question}
"""


def format_entity_names(entity_names: list[str]) -> str:
    """把實體名單排成 prompt 裡的那幾行。

    空清單特別寫一句話而不是留白：留白會讓模型自行想像清單內容、
    然後挑一個根本不存在的名字（同一個教訓見 build_vlm_prompt 的資料夾清單）。
    """
    if not entity_names:
        return "（目前一個實體都還沒有，所以這次不可能用 entity 查法）"
    return "\n".join(f"- {name}" for name in entity_names)


def build_route_prompt(question: str, entity_names: list[str]) -> str:
    """組出路由 prompt 的最終字串（本機與雲端共用，兩邊逐字相同）。"""
    return ROUTE_PROMPT.format(
        entities=format_entity_names(entity_names), question=question
    )


class RouterClient(Protocol):
    """判斷查法的介面。正式用 OllamaRouter，測試用 FakeRouter。

    entity_names 是資料庫現有的實體名稱清單：模型要能把「我的 MacBook」
    這種**使用者自己取的名字**對回資料，就必須先看得到有哪些名字可挑，
    否則它只能亂猜（design3.md §6「不靠碰運氣搜字」）。
    """

    def route(self, question: str, entity_names: list[str]) -> RouteDecision:
        ...


class OllamaRouter:
    """用本機 Ollama 的模型判斷查法。

    失敗不在這裡處理——一律往外丟，由 route 節點統一 fallback，
    這樣「失敗就走語意查詢」只有一個地方負責。
    """

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        model_name = model or config.LLM_MODEL
        self._timing_target = ai_timing.AiTarget(
            backend="local", model=model_name
        )
        self._model = ChatOllama(
            model=model_name,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(RouteDecision, method="function_calling")

    @property
    def timing_target(self) -> ai_timing.AiTarget:
        return self._timing_target

    def route(self, question: str, entity_names: list[str]) -> RouteDecision:
        message = HumanMessage(content=build_route_prompt(question, entity_names))
        return self._model.invoke([message])


# 雲端路由的輸出格式補充指令。ollama.com 對 format= 不強制、要用講的——
# 教訓與三道保險的作法詳見 ollama_cloud 模組 docstring。
CLOUD_ROUTE_JSON_INSTRUCTION = """
輸出格式（最後、也最優先的規則）：
只輸出一個 JSON 物件。不要條列、不要 markdown、不要程式碼圍欄、不要 JSON 以外的任何文字。
長相示意：{"mode": "metadata 或 vector 或 entity 或 task", "category": "…或 null",
"location": "…或 null", "item": "…或 null", "recent": false,
"entity_name": "…或 null", "due_within_days": 7 或 null}
"""


class OllamaCloudRouter:
    """用 Ollama Cloud 判斷查法（AI 後端開關撥到「雲端」時）。

    prompt 與 OllamaRouter 逐字共用（只在尾端多接「只准回 JSON」指令）。
    失敗語意也一樣：不在這裡處理、一律往外丟（雲端回了解析不出的東西
    ＝ValidationError 往外炸），由 route 節點統一 fallback 成語意查詢——
    「失敗就走 vector」仍然只有一個地方負責。
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or config.OLLAMA_CLOUD_LLM_MODEL
        self._timing_target = ai_timing.AiTarget(
            backend="cloud", model=self._model_name
        )
        self._client = ollama_cloud.build_client()

    @property
    def timing_target(self) -> ai_timing.AiTarget:
        return self._timing_target

    def route(self, question: str, entity_names: list[str]) -> RouteDecision:
        response = self._client.chat(
            model=self._model_name,
            messages=[
                {
                    "role": "user",
                    "content": build_route_prompt(question, entity_names)
                    + CLOUD_ROUTE_JSON_INSTRUCTION,
                }
            ],
            format=RouteDecision.model_json_schema(),
            options={"temperature": 0},
        )
        return RouteDecision.model_validate_json(
            ollama_cloud.extract_json_object(response.message.content or "")
        )


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


def build_answer_prompt(question: str, documents: list[Document]) -> str:
    """把問題與檢索結果組成 ANSWER_PROMPT 的最終字串（本機與雲端共用，逐字相同）。"""
    if documents:
        context = "\n\n".join(
            f"[照片 {doc.metadata['id']}]\n{doc.page_content}" for doc in documents
        )
    else:
        context = "（沒有找到任何照片 / no photos found）"
    return ANSWER_PROMPT.format(question=question, context=context)


class AnswerClient(Protocol):
    """產生回答的介面。正式用 OllamaAnswerer，測試用 FakeAnswerLLM。"""

    def answer(self, question: str, documents: list[Document]) -> str:
        ...


class OllamaAnswerer:
    """用本機 Ollama 的模型依照片內容產生回答。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        model_name = model or config.LLM_MODEL
        self._timing_target = ai_timing.AiTarget(
            backend="local", model=model_name
        )
        self._model = ChatOllama(
            model=model_name,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        )

    @property
    def timing_target(self) -> ai_timing.AiTarget:
        return self._timing_target

    def answer(self, question: str, documents: list[Document]) -> str:
        message = HumanMessage(content=build_answer_prompt(question, documents))
        return self._model.invoke([message]).text


class OllamaCloudAnswerer:
    """用 Ollama Cloud 依照片內容產生回答（AI 後端開關撥到「雲端」時）。

    回答是純文字、不需要 JSON，所以不帶 format 也不做抽取；
    prompt 與 OllamaAnswerer 逐字相同，失敗一樣往外丟（500 不吞錯）。
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or config.OLLAMA_CLOUD_LLM_MODEL
        self._timing_target = ai_timing.AiTarget(
            backend="cloud", model=self._model_name
        )
        self._client = ollama_cloud.build_client()

    @property
    def timing_target(self) -> ai_timing.AiTarget:
        return self._timing_target

    def answer(self, question: str, documents: list[Document]) -> str:
        response = self._client.chat(
            model=self._model_name,
            messages=[
                {"role": "user", "content": build_answer_prompt(question, documents)}
            ],
            options={"temperature": 0},
        )
        return response.message.content or ""


# ------------------------------ 流程狀態 ------------------------------
class AskState(TypedDict):
    """在流程圖裡一路傳下去的資料。"""

    question: str
    mode: str                    # "metadata" | "vector" | "entity" | "task"
    filters: QueryFilters        # 六個條件皆可空，哪一路讀哪幾個見 QueryFilters
    retrieved: list[Document]    # 每份 Document 帶 id（metadata）＋內容
    answer: str


@dataclass
class AskDeps:
    """詢問流程要用到的外部相依，全部從外面注入，測試才好換成假件。"""

    router: RouterClient
    answerer: AnswerClient
    embeddings: Embeddings
    today: date                  # 詢問當下的日期，供 30 天過濾使用
    # 現有實體名稱，注入路由 prompt 讓模型對得到名字（Phase 34）。
    # 預設空清單＝「一個實體都還沒建」的自然狀態，也是本專案剛裝好時的樣子；
    # 端點一定會把資料庫裡的真名單傳進來（見 api/routers/ask.py）。
    entity_names: list[str] = field(default_factory=list)


# ------------------------------ 流程圖 -------------------------------
def build_workflow(deps: AskDeps):
    """組出流程圖並編譯成可執行物件。"""

    # mode → 節點名。定義一次，pick_branch 與 add_conditional_edges 共用，
    # 日後再加第五路時不會只改到其中一邊。
    branches = {
        "metadata": "retrieve_metadata",
        "vector": "retrieve_vector",
        "entity": "retrieve_entity",
        "task": "retrieve_task",
    }

    def route_node(state: AskState) -> dict[str, Any]:
        """判斷查法。任何失敗都 fallback 成語意查詢、條件全空。"""
        try:
            # 計時包在 try 裡面：例外要先穿過 log_ai（打 ok=false）再被下面接住，
            # 「失敗就 fallback 成語意查詢」的語意一個字都沒變（design4.md §9 第 5 列）
            with ai_timing.log_ai(
                "route", target=getattr(deps.router, "timing_target", None)
            ):
                decision = deps.router.route(state["question"], deps.entity_names)
                if not isinstance(decision, RouteDecision):
                    raise _InvalidRouteDecisionError(type(decision).__name__)
        except Exception:
            # fallback 是設計，但一定要留 log：不然「模型名打錯」「Ollama 沒開」
            # 「雲端 404」全都無聲變成「怎麼每一題都走語意查詢」
            # （2026-08-22 雲端煙霧的教訓——路由 404 被吞掉、只有回答那步炸出來）
            logger.warning("路由呼叫失敗，fallback 成語意查詢", exc_info=True)
            decision = RouteDecision(mode="vector")

        return {
            "mode": decision.mode,
            "filters": QueryFilters(
                category=decision.category,
                location=decision.location,
                item=decision.item,
                recent=decision.recent,
                entity_name=decision.entity_name,
                due_within_days=decision.due_within_days,
            ),
        }

    def pick_branch(state: AskState) -> str:
        """條件邊：看 state 裡的 mode 決定走哪一條；認不得的一律走語意查詢。

        RouteDecision 的 Literal 已經擋過一輪，這裡是第二道防線：
        萬一日後有人把對照表以外的 mode 塞進 state，讓整張圖找不到邊而炸掉，
        比默默多查一次照片糟得多。
        """
        return state["mode"] if state["mode"] in branches else "vector"

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

    def retrieve_entity_node(state: AskState) -> dict[str, Any]:
        return _retrieve(state, "entity")

    def retrieve_task_node(state: AskState) -> dict[str, Any]:
        return _retrieve(state, "task")

    def generate_node(state: AskState) -> dict[str, Any]:
        """只依撈到的照片內容產生回答；撈不到就由 LLM 回覆查無相關照片。

        刻意**不加** try/except：回答失敗仍然 500 不吞錯（design.md 錯誤處理總表的
        既有決定）。log_ai 打完 ok=false 之後例外要繼續往外飛。
        """
        with ai_timing.log_ai(
            "answer", target=getattr(deps.answerer, "timing_target", None)
        ):
            return {
                "answer": deps.answerer.answer(state["question"], state["retrieved"])
            }

    graph = StateGraph(AskState)
    graph.add_node("route", route_node)
    graph.add_node("retrieve_metadata", retrieve_metadata_node)
    graph.add_node("retrieve_vector", retrieve_vector_node)
    graph.add_node("retrieve_entity", retrieve_entity_node)
    graph.add_node("retrieve_task", retrieve_task_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", pick_branch, branches)
    for node_name in branches.values():
        graph.add_edge(node_name, "generate")
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
