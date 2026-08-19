# Phase 10：ask_workflow.py 的 LangGraph 骨架與 route 節點

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 用 LangGraph 把詢問流程串成一張圖，並做出第一個節點 `route`——由 LLM 判斷「這個問題要走條件查詢還是語意查詢」（中文與英文問題都要能判斷），判斷失敗時一律 fallback 到語意查詢。

---

## 前置條件

- 需要已完成的 phase：**Phase 9**（檢索服務兩條查詢可用、測試累計 21）。
- 環境：測試資料庫可用；本 phase 的測試**不需要 Ollama**（用 `FakeRouter` 與 `FakeEmbeddings`）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

詢問流程有分岔：有時走條件查詢、有時走語意查詢。這種「先判斷再分岔」的流程，用 **LangGraph** 畫成圖最清楚——每個步驟是一個節點，節點之間用箭頭連起來，分岔用條件邊。

判斷的方式（已釐清的決策）：**由 LLM 判斷**，不是寫關鍵字規則。判斷標準是：
- 問題帶明確過濾條件（商家、類別、時間）→ **條件查詢**（metadata search）
- 語意／內容描述型的問題 → **語意查詢**（vector semantic search）

而且一次 LLM 呼叫就同時拿到「查法」與「過濾條件」，不用呼叫兩次。

**雙語在這裡的落地點是 prompt 的 few-shot 例句**（design.md §5.2）：few-shot（少量示範）＝在 prompt 裡先給模型幾個「這樣問就這樣答」的範例，讓它照著做。本專案的錨點例句**必須同時包含中文與英文**：

- 「有哪些在 Target 拍的收據？」→ 條件查詢
- 「我最近買過什麼飲料？」→ 語意查詢
- `"What drinks did I buy recently?"` → 語意查詢

還有一條保險絲（規則 Q3）：**LLM 判斷失敗、格式不對、呼叫出錯——通通改走語意查詢、條件全空**。使用者永遠拿得到回答，不會看到錯誤。

**名詞**：
- **LangGraph 的 state（狀態）**＝一個在流程圖裡一路傳下去的字典，每個節點讀它、也可以往裡面寫東西。
- **節點（node）**＝流程圖上的一個步驟，本質是一個函式。
- **條件邊（conditional edge）**＝依照 state 的內容決定下一步要去哪個節點。
- **fallback（後備方案）**＝主要做法失敗時改用的備案。
- **`TypedDict`**＝Python 的一種型別寫法：規定「這個字典要有哪些鍵、每個鍵的值是什麼型別」。下面的 `AskState` 就是用它宣告 state 長什麼樣子。
- **`Literal["a", "b"]`**＝Python 的一種型別寫法：這個欄位**只能**是列出來的那幾個值之一，填別的就算格式不符。

---

## ASCII 圖：詢問流程圖（★ 標記＝本 phase 要完成的部分）

```
        START
          │
          ▼
    ┌──────────────────────────────────────────────────┐
    │ route 節點  ★本 phase                             │
    │  一次 LLM 結構化輸出 →                             │
    │    mode = "metadata" | "vector"                  │
    │    category / location / item / recent           │
    │  few-shot 錨點（中英各有）：                        │
    │    「有哪些在 Target 拍的收據？」   → metadata      │
    │    「我最近買過什麼飲料？」          → vector       │
    │    "What drinks did I buy recently?" → vector     │
    │  出錯或格式不符 → mode="vector"、條件全空          │
    └──────────────┬───────────────────────────────────┘
                   │ 條件邊：看 state["mode"]
         ┌─────────┴─────────┐
         ▼                   ▼
 retrieve_metadata     retrieve_vector    ★本 phase（呼叫 Phase 9 的檢索服務）
   條件查詢(SQL/ILIKE)    語意查詢(向量 top-5)
         └─────────┬─────────┘
                   ▼
              generate 節點   （Phase 11 才加；本 phase 兩條查詢先直接接到 END）
                   ▼
                  END
```

---

## 逐步驟操作

### 步驟 1：寫 `app/services/ask_workflow.py`

```python
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

    graph = StateGraph(AskState)
    graph.add_node("route", route_node)
    graph.add_node("retrieve_metadata", retrieve_metadata_node)
    graph.add_node("retrieve_vector", retrieve_vector_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        pick_branch,
        {"metadata": "retrieve_metadata", "vector": "retrieve_vector"},
    )
    # TODO(Phase 11)：兩條查詢接到 generate 節點，再進 END
    graph.add_edge("retrieve_metadata", END)
    graph.add_edge("retrieve_vector", END)

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
```

### 步驟 2：在 `tests/fakes.py` 加上 `FakeRouter`

```python
# 接在 tests/fakes.py 既有內容後面
from app.services.ask_workflow import RouteDecision

# 規格例子與雙語測試裡的問題 → 應該得到的判斷結果
DEFAULT_ROUTE_DECISIONS: dict[str, RouteDecision] = {
    # 規格 .feature 的兩個中文例子
    "有哪些在 Target 拍的收據？": RouteDecision(
        mode="metadata", category="收據", location="Target", recent=False
    ),
    "我最近買過什麼飲料？": RouteDecision(mode="vector", recent=True),
    # 雙語測試用的英文問題
    "What drinks did I buy recently?": RouteDecision(mode="vector", recent=True),
    # 英文條件型問題：條件值照原文抽（小寫 target），交給 SQL 的 ILIKE 去比對。
    # 注意這裡刻意沒抽 category="receipt"——抽了也對不到中文的「收據」，
    # 因為系統不做跨語言翻譯對映（design.md §8.3 的已知限制）。
    "Which receipts were taken at target?": RouteDecision(
        mode="metadata", location="target", recent=False
    ),
}


class FakeRouter:
    """照例子指定回查法。

    遇到沒登記過的問題（例如模糊問題「幫我找找之前那個」）就丟例外，
    模擬「LLM 無法判斷」，用來驗證 fallback 一定會走語意查詢。
    """

    def __init__(self, decisions: dict[str, RouteDecision] | None = None) -> None:
        self.decisions = (
            DEFAULT_ROUTE_DECISIONS if decisions is None else decisions
        )

    def route(self, question: str) -> RouteDecision:
        if question not in self.decisions:
            raise RuntimeError(f"無法判斷問題類型：{question}")
        return self.decisions[question]
```

### 步驟 3：建立 `tests/test_workflow_route.py`

```python
"""route 節點：判斷查法 ＋ 失敗時 fallback 語意查詢 ＋ 英文問題也能判斷。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.repositories import photo_repository
from app.services.ask_workflow import AskDeps, run_ask
from tests.fakes import FakeEmbeddings, FakeRouter

TODAY = date(2026, 8, 18)


@pytest.fixture
def deps() -> AskDeps:
    return AskDeps(router=FakeRouter(), embeddings=FakeEmbeddings(), today=TODAY)


@pytest.fixture
def 一張Target收據():
    return photo_repository.insert_photo(
        text="在 Target 購買可樂與洋芋片的收據",
        category="收據", location="Target", items=["可樂", "洋芋片"],
        content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query("在 Target 購買可樂與洋芋片的收據"),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )["id"]


def test_條件過濾型問題走條件查詢(deps, 一張Target收據):
    state = run_ask("有哪些在 Target 拍的收據？", deps)

    assert state["mode"] == "metadata"
    assert state["filters"].category == "收據"
    assert state["filters"].location == "Target"
    assert [d.metadata["id"] for d in state["retrieved"]] == [一張Target收據]


def test_語意描述型問題走語意查詢(deps, 一張Target收據):
    state = run_ask("我最近買過什麼飲料？", deps)

    assert state["mode"] == "vector"
    assert state["filters"].recent is True


def test_英文語意描述型問題也走語意查詢(deps, 一張Target收據):
    """雙語：英文問題同樣要判斷得出查法與時間條件（design.md §5.2 的 few-shot）。"""
    state = run_ask("What drinks did I buy recently?", deps)

    assert state["mode"] == "vector"
    assert state["filters"].recent is True
    # 多語 embedding 讓英文問題也能召回中文內容的照片
    assert [d.metadata["id"] for d in state["retrieved"]] == [一張Target收據]


def test_無法判斷時走語意查詢(deps, 一張Target收據):
    state = run_ask("幫我找找之前那個", deps)

    assert state["mode"] == "vector"
    assert state["filters"].category is None
    assert state["filters"].location is None
    assert state["filters"].item is None
    assert state["filters"].recent is False


def test_路由回傳格式不對也走語意查詢(一張Target收據):
    class 壞掉的Router:
        def route(self, question):
            return {"mode": "metadata"}      # 不是 RouteDecision，格式不符

    deps = AskDeps(router=壞掉的Router(), embeddings=FakeEmbeddings(), today=TODAY)
    state = run_ask("有哪些在 Target 拍的收據？", deps)

    assert state["mode"] == "vector"
```

> 💡 `test_英文語意描述型問題也走語意查詢` 能撈到那張中文照片，是因為 `FakeEmbeddings` 的 `SYNONYMS` 把 `drinks` 對應到「可樂／咖啡／牛奶」（Phase 6 步驟 3）——這是在假件裡**模擬**真 `bge-m3` 的跨語言能力。真模型的行為在 Phase 8／13 用手動煙霧測試確認。

---

## 驗收標準

1. **route 測試全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/test_workflow_route.py -v
   ```
   預期最後一行：`5 passed`

2. **全部測試一起跑仍然全綠**
   ```bash
   pytest -q
   ```
   預期：`26 passed`（**測試累計數：26**＝ Phase 9 的 21 ＋ 本 phase 的 5）

3. **route prompt 真的含英文 few-shot 例句**
   ```bash
   grep -n "What drinks did I buy recently?" app/services/ask_workflow.py
   grep -n "不要翻譯" app/services/ask_workflow.py
   ```
   預期：各印出一行。

4. **流程圖的結構正確**（畫出來看看）
   ```bash
   python - <<'PY'
   from datetime import date
   from app.services.ask_workflow import AskDeps, build_workflow
   from tests.fakes import FakeEmbeddings, FakeRouter

   graph = build_workflow(AskDeps(router=FakeRouter(), embeddings=FakeEmbeddings(),
                                  today=date(2026, 8, 18)))
   print(graph.get_graph().draw_ascii())
   PY
   ```
   預期：印出一張 ASCII 流程圖，看得到 `__start__ → route`，route 之後分岔到 `retrieve_metadata` 與 `retrieve_vector`，兩者都連到 `__end__`。

5. **真的路由一次**（可選，需要 Ollama；中英文各試一次）
   ```bash
   python - <<'PY'
   from app.services.ask_workflow import OllamaRouter
   router = OllamaRouter()
   print("中文：", router.route("有哪些在 Target 拍的收據？"))
   print("英文：", router.route("What drinks did I buy recently?"))
   PY
   ```
   預期：中文那筆 `mode='metadata'` 且 `location='Target'`；英文那筆 `mode='vector'` 且 `recent=True`。（小模型偶爾判斷不同，這只是煙霧測試，不進驗收。）

---

## 常見問題

**Q1：`draw_ascii()` 報錯說少了套件。**
畫圖需要額外套件。執行 `uv pip install grandalf` 後再試；這只是視覺化工具，不影響功能，跳過也可以。

**Q2：`add_conditional_edges` 的第三個參數怎麼看？**
它是一張對照表：「判斷函式回傳這個字串 → 就去這個節點」。所以 `pick_branch` 回傳 `"metadata"` 就走到 `retrieve_metadata` 節點。

**Q3：節點回傳的字典會覆蓋整個 state 嗎？**
不會。節點只要回傳「這次要更新的鍵」，LangGraph 會把它合併進 state，其他鍵維持原樣。

**Q4：fallback 應該寫在 `OllamaRouter` 還是 `route` 節點？**
寫在 **`route` 節點**。這樣不管是真模型出錯、假件丟例外、還是回傳格式不對，都由同一段程式碼負責兜底，行為一致也只有一個地方要測。

**Q5：可不可以改成用關鍵字判斷（看到「Target」就走條件查詢）？**
不行。已釐清的決策明訂路由**由 LLM 判斷**，關鍵字規則路由是被否決的方案。

**Q6：要不要在 route 裡加一個「語言偵測」節點，先判斷中文還是英文？**
**不要。** 一個 prompt 同時處理兩種語言就夠了（few-shot 已含中英例句），多一個節點是過度設計。回答語言的處理在 Phase 11 的 generate prompt，也是一句話搞定。

**Q7：英文問題抽出 `category="receipt"` 卻查不到「收據」，要不要修？**
**不要修。** design.md §8.3 明列這是「已知限制（刻意不解）」。實務上這種跨語言問題會被 router 判成語意查詢，那條路本來就跨語言。

**Q8：design.md §5.2 的 state 寫 `retrieved: list[RetrievedPhoto]`，這裡怎麼變成 `list[Document]`？**
是同一件事的落地。Phase 9 的檢索服務把每列照片組裝成 LangChain 的 `Document`：照片 `id` 放在 `document.metadata`，文字描述＋四欄位組成 `page_content`——正好就是設計裡「id + text + 四欄位」的 `RetrievedPhoto`。直接沿用 `Document`，就能原封不動接住檢索服務的回傳值，不必再定義一個內容一模一樣的類別。

---

## 完成後的專案狀態

詢問流程的前半段完成：LangGraph 會先請 LLM 判斷查法與過濾條件（中文與英文問題都能判斷），再分岔到對應的查詢並把照片撈進 state；判斷失敗時一律走語意查詢（規則 Q3 已成立）。但還沒有人把撈到的照片變成一段回答，也還沒有 `POST /ask` 端點。測試累計 **26** 個。
