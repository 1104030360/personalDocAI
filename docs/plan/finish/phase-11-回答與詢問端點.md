# Phase 11：generate 節點與 `POST /ask` 端點

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 加上流程圖的最後一個節點 `generate`（LLM 只依撈到的照片內容回答、**回答語言跟隨提問語言**、查無就說查無、不得編造），並把整條流程接成 `api/routers/ask.py` 的 `POST /ask` 端點。

---

## 前置條件

- 需要已完成的 phase：**Phase 10**（流程圖與 route 節點、測試累計 **55**）。
- 開工前基線（2026-08-19 實查）：`pytest -q` = 55 passed；langchain-core **1.5.6**／langchain-ollama 1.1.0／langgraph 1.2.11 已裝；`config.SEARCH_MODE_LABELS`、conftest 的 `client` fixture 與 `wire_fake_ai` 假件安全網、retriever Document 的 `id`／`items` metadata 皆已在，本計畫的程式碼引用全部核對過。
- 環境：測試資料庫可用；本 phase 的測試**不需要 Ollama**（用假件）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

照片撈出來了，還要有人把它變成一句人話。這就是 `generate` 節點：把「問題＋撈到的照片內容」交給 LLM，請它產生回答。

Prompt 有三條鐵律（design.md §8.3）：
1. **只能依據提供的照片內容回答**，不得用外部知識補充。
2. **撈不到照片時要回「查無相關照片」的自然語言，不得虛構**。
3. **回答語言跟隨提問語言**——中文問就用繁體中文答，英文問就用英文答。直接回答，不要說明推理過程。

第 3 條就是**雙語在這裡的落地點**。注意它只約束「回答用什麼語言寫」，不要求翻譯照片內容：如果英文問題撈到的是中文照片，回答會是英文句子裡帶著中文的照片內容——這是對的，因為照片內容是事實，不該被改寫。

還有一個關鍵設計：回應裡的 `search_mode` 與 `retrieved_photo_ids` **不經過 AI**，直接從流程的 state 取出來。可驗證的欄位不給模型改寫的機會——這樣測試才能黑箱驗證「系統選了哪種查法」「回答依據哪些照片」。

---

## ASCII 圖：完整的詢問流程（跨三層）

```
 POST /ask  {"question": "有哪些在 Target 拍的收據？"}   或
            {"question": "What drinks did I buy recently?"}
      │
      ▼
 【api/routers/ask.py】組出 AskDeps(router, answerer, embeddings, today)
      │   四個都來自 app/dependencies.py，測試時整組換成假件
      ▼  services/ask_workflow.run_ask()
   START
     │
     ▼
   route ──────────────── LLM 判斷查法＋條件（失敗 → vector）
     │
   ┌─┴─┐
   ▼   ▼
 條件查詢 語意查詢 ─────── 撈到 list[Document]
 (retrieve_metadata / retrieve_vector 節點，Phase 10 已完成)
   └─┬─┘
     ▼
 **generate**  ★本 phase
   輸入＝問題 ＋ 撈到的照片（id、文字、四欄位）
   LLM 只依這些內容回答；撈不到 → 回「查無相關照片」
   ★ 回答語言跟隨提問語言（中問中答、英問英答）
     │
     ▼
    END
      │
      ▼
 回 200 {
   "answer": "你有一張 8 月 10 日在 Target 購買可樂與洋芋片的收據。",  ← LLM 產生（語言跟提問）
   "search_mode": "metadata search",        ← 直接取自 state，不經 AI
   "retrieved_photo_ids": [1]               ← 直接取自 state，不經 AI
 }
```

---

## 逐步驟操作

> 🧪 **TDD 執行順序（紅→綠）**：先做**步驟 9** 建 `tests/integration/test_ask_endpoint.py` 看紅（該檔 import 的 `get_answerer`／`FakeAnswerLLM` 都還不存在 → 只有這個檔收集失敗，其餘 55 個不受影響；注意 pytest 預設遇收集錯誤會直接中斷（Interrupted）只印 1 error，想看到「55 passed＋1 error」的全貌要加 `--continue-on-collection-errors`）。轉綠依序：**步驟 7**（`FakeAnswerLLM` 只依賴 langchain 的 `Document`，先加不會弄壞任何東西）→ **步驟 1** → **步驟 2 與步驟 8 必須一起做**（⚠️ 順序陷阱：`AskDeps` 加上**必填**欄位 `answerer` 的當下，`tests/integration/test_workflow_route.py` 既有 5 個測試會立刻因缺參數而壞，所以改完 `AskDeps` 馬上補步驟 8）→ 步驟 3〜6 → 全綠。步驟編號維持閱讀順序，不重排。

### 步驟 1：在 `app/services/ask_workflow.py` 加上回答用的元件

在 `RouteDecision` 相關程式碼後面（`AskState` 之前）加入：

```python
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
```

### 步驟 2：把 `generate` 節點接進流程圖

修改 `app/services/ask_workflow.py` 的 `AskDeps` 與 `build_workflow`：

```python
@dataclass
class AskDeps:
    """詢問流程要用到的外部相依，全部從外面注入，測試才好換成假件。"""

    router: RouterClient
    answerer: AnswerClient     # ← 本 phase 新增
    embeddings: Embeddings
    today: date
```

再改 `build_workflow` 的**最後一段（組圖的部分）**：把 Phase 10 暫時寫的兩行 `graph.add_edge("retrieve_metadata", END)`、`graph.add_edge("retrieve_vector", END)` 和上面的 `# TODO(Phase 11)` 註解**刪掉**，換成下面的接法（函式前半的 `route_node`／`pick_branch`／`_retrieve`／兩個 retrieve 節點都維持不變）：

```python
def build_workflow(deps: AskDeps):
    ...（route_node / pick_branch / _retrieve / 兩個 retrieve 節點維持不變）...

    def generate_node(state: AskState) -> dict[str, Any]:
        """只依撈到的照片內容產生回答；撈不到就由 LLM 回覆查無相關照片。"""
        return {"answer": deps.answerer.answer(state["question"], state["retrieved"])}

    graph = StateGraph(AskState)
    graph.add_node("route", route_node)
    graph.add_node("retrieve_metadata", retrieve_metadata_node)
    graph.add_node("retrieve_vector", retrieve_vector_node)
    graph.add_node("generate", generate_node)          # ← 新增

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        pick_branch,
        {"metadata": "retrieve_metadata", "vector": "retrieve_vector"},
    )
    graph.add_edge("retrieve_metadata", "generate")     # ← 改成接到 generate
    graph.add_edge("retrieve_vector", "generate")       # ← 改成接到 generate
    graph.add_edge("generate", END)

    return graph.compile()
```

### 步驟 3：`app/schemas/ask.py` 讓空字串問題也被框架擋下

`AskRequest` 在 Phase 2 就建立了，**不要新增第二個**——把既有的類別改成下面這樣（差別只有 `question` 那行加上 `Field(min_length=1)`＝「至少要有 1 個字」，並在檔案開頭補上 `Field` 的 import）：

```python
"""自然語言詢問的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """POST /ask 的請求內容。問題可以是中文或英文。

    question 缺漏或空字串 → 由框架回既有的 422，不另外發明行為。
    """

    question: str = Field(min_length=1)
```

（`AskResponse` 維持 Phase 2 的樣子不動。`question` 缺漏本來就會被 FastAPI 擋下；加上 `min_length=1` 後，空字串也走同一條框架既有的 422，符合 design.md §6「不另外發明行為」。）

### 步驟 4：在 `app/dependencies.py` 加上詢問流程的三個注入點

**用增量修改，不要整檔重寫**（既有的模組 docstring 與 `get_vlm`／`get_now` 的說明都要原樣保留）。三個動作：

1. 檔頂 import 區補齊（`datetime` 那行加上 `date`；`Depends` 與 `ask_workflow` 是新的）：

```python
from datetime import date, datetime
from functools import lru_cache

from fastapi import Depends
from langchain_core.embeddings import Embeddings

from app.services import ask_workflow, indexing_service, vlm_service
```

2. 模組 docstring 最後一句的「（Phase 11 補上）」改成「（Phase 11 已補上）」。

3. 檔案最下面加上三組注入點（其餘既有內容一字不動）：

```python
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
```

### 步驟 5：寫 `app/api/routers/ask.py`

```python
"""自然語言詢問的 router：POST /ask。"""

from datetime import date

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_answerer, get_embeddings, get_router, get_today
from app.schemas.ask import AskRequest, AskResponse
from app.services import ask_workflow

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    router_client: ask_workflow.RouterClient = Depends(get_router),
    answerer: ask_workflow.AnswerClient = Depends(get_answerer),
    embeddings: Embeddings = Depends(get_embeddings),
    today: date = Depends(get_today),
) -> AskResponse:
    """自然語言詢問（中英文皆可）：判斷查法 → 查詢 → 依撈到的內容回答。"""
    deps = ask_workflow.AskDeps(
        router=router_client, answerer=answerer, embeddings=embeddings, today=today
    )
    state = ask_workflow.run_ask(payload.question, deps)

    return AskResponse(
        answer=state["answer"],
        # search_mode 與 retrieved_photo_ids 直接取自流程 state，不經過 AI
        search_mode=config.SEARCH_MODE_LABELS[state["mode"]],
        retrieved_photo_ids=[doc.metadata["id"] for doc in state["retrieved"]],
    )
```

### 步驟 6：在 `app/main.py` 掛上第二個 router

把 Phase 4 寫的 `main.py` 改成下面這樣（差別：import 多了 `ask`、多掛一行 `app.include_router(ask.router)`、刪掉 `# TODO(Phase 11)` 那行註解，docstring 也順手更新；`title` 維持現有的 `personalDocAI` 不要動）：

```python
"""FastAPI app 組裝：掛上兩個 router。"""

from fastapi import FastAPI

from app.api.routers import ask, photos

app = FastAPI(title="personalDocAI")

app.include_router(photos.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}
```

### 步驟 7：在 `tests/fakes.py` 加上 `FakeAnswerLLM`

```python
# 接在 tests/fakes.py 既有內容後面
#（`from langchain_core.documents import Document` 放檔頂 import 區、
#  `from app.core import config` 之前——循檔內既有慣例，不放中段）


def _looks_english(text: str) -> bool:
    """粗略判斷一段文字是不是英文：完全沒有中日韓漢字就當英文。

    這只是假件用的簡易規則，用來重現「回答語言跟隨提問語言」的行為；
    產品程式碼裡沒有、也不需要這種判斷（真模型看得懂提問語言）。
    """
    return not any("一" <= ch <= "鿿" for ch in text)


class FakeAnswerLLM:
    """拿檢索結果模板化回答；空結果回查無句式。回答語言跟隨提問語言。

    行為固定，讓「回答提及可樂」「使用者獲得查無相關照片的回覆」
    「英文問題得到英文回答」都可以被驗證。
    """

    def answer(self, question: str, documents: list[Document]) -> str:
        english = _looks_english(question)

        if not documents:
            return "No matching photos found." if english else "查無相關照片。"

        pieces = []
        for document in documents:
            first_line = document.page_content.splitlines()[0]
            items = document.metadata.get("items") or []
            if english:
                item_text = ", ".join(items) if items else "none"
                pieces.append(f"{first_line} (items: {item_text})")
            else:
                item_text = "、".join(items) if items else "無"
                pieces.append(f"{first_line}（物品：{item_text}）")

        if english:
            return "Based on the photos: " + "; ".join(pieces)
        return "依照片內容回答：" + "；".join(pieces)
```

> 注意：照片內容（`first_line`、`items`）**原封不動**放進回答，不論它是中文還是英文——只有假件自己寫的那句框架文字跟著提問語言變。這正是 design.md §8.3 鐵律 3 的行為。

### 步驟 8：把 `AskDeps` 的新欄位補進既有測試

`tests/integration/test_workflow_route.py` 裡建立 `AskDeps` 的地方要補上 `answerer`：

```python
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

@pytest.fixture
def deps() -> AskDeps:
    return AskDeps(
        router=FakeRouter(),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=TODAY,
    )
```

（`test_路由回傳格式不對也走語意查詢` 裡自建的 `AskDeps` 也要一起補。）

### 步驟 9：建立 `tests/integration/test_ask_endpoint.py`

```python
"""POST /ask 端點的基本行為＋雙語回答（規格驗收在 Phase 12）。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.dependencies import get_answerer, get_router
from app.main import app
from app.repositories import photo_repository
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

# conftest 的 wire_fake_ai 已把固定時鐘設成同一時間；這個常數拿來組測試資料
NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture(autouse=True)
def wire_ask_fakes(wire_fake_ai):
    """接上詢問用的兩個假件（embeddings 與固定時鐘由 conftest 的 wire_fake_ai 統一接管）。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()——
    沿用 test_upload_feature.py 的既有慣例。
    """
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_answerer] = lambda: FakeAnswerLLM()
    yield


def _一張Target收據() -> int:
    return photo_repository.insert_photo(
        text="在 Target 購買可樂與洋芋片的收據", category="收據", location="Target",
        items=["可樂", "洋芋片"], content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query("在 Target 購買可樂與洋芋片的收據"),
        uploaded_at=NOW,
    )["id"]


def test_條件查詢的回應內容(client):
    photo_id = _一張Target收據()

    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "metadata search"
    assert body["retrieved_photo_ids"] == [photo_id]
    assert "可樂" in body["answer"]


def test_英文提問得到英文回答(client):
    """雙語：回答語言跟隨提問語言；照片內容維持原文（design.md §8.3 鐵律 3）。"""
    photo_id = _一張Target收據()

    response = client.post(
        "/ask", json={"question": "What drinks did I buy recently?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "vector semantic search"
    assert body["retrieved_photo_ids"] == [photo_id]
    # 回答的框架句是英文
    assert body["answer"].startswith("Based on the photos")
    # 但照片內容原文照抄，沒有被翻譯
    assert "可樂" in body["answer"]


def test_沒有照片時回覆查無(client):
    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


def test_模糊問題走語意查詢(client):
    response = client.post("/ask", json={"question": "幫我找找之前那個"})

    assert response.status_code == 200
    assert response.json()["search_mode"] == "vector semantic search"


def test_問題缺漏或空字串回422(client):
    assert client.post("/ask", json={}).status_code == 422
    assert client.post("/ask", json={"question": ""}).status_code == 422
```

---

## 驗收標準

1. **端點測試全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/integration/test_ask_endpoint.py -v
   ```
   預期最後一行：`5 passed`

2. **全部測試一起跑仍然全綠**
   ```bash
   pytest -q
   ```
   預期：`60 passed`（**測試累計數：60**＝ Phase 10 的 55 ＋ 本 phase 的 5）

3. **generate prompt 真的寫了「回答語言跟隨提問語言」鐵律**
   ```bash
   grep -n "回答語言必須跟隨使用者提問的語言" app/services/ask_workflow.py
   ```
   預期：印出一行。

4. **流程圖現在有四個節點**
   ```bash
   python - <<'PY'
   from datetime import date
   from app.services.ask_workflow import AskDeps, build_workflow
   from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

   graph = build_workflow(AskDeps(router=FakeRouter(), answerer=FakeAnswerLLM(),
                                  embeddings=FakeEmbeddings(), today=date(2026, 8, 18)))
   print(list(graph.get_graph().nodes))
   PY
   ```
   預期輸出包含：`route`、`retrieve_metadata`、`retrieve_vector`、`generate`。

5. **兩個 router 都掛上了**
   瀏覽器開 <http://localhost:8000/docs>（需先啟動服務——啟動指令見下一項「視窗 A」），應該看到 `GET /health`、`POST /photos`、`POST /ask` 三個端點。

6. **用真的 HTTP 呼叫一次**（需要 Ollama，先照 Phase 8 上傳過至少一張照片）
   ```bash
   # 視窗 A：啟動服務
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   uvicorn app.main:app --port 8000
   ```
   ```bash
   # 視窗 B：詢問（新視窗一樣要先 cd ＋啟用虛擬環境）
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   curl -s -X POST http://localhost:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question":"有哪些在 Target 拍的收據？"}' | python -m json.tool
   ```
   預期：回傳三個鍵 `answer`／`search_mode`／`retrieved_photo_ids`，`search_mode` 是 `"metadata search"` 或 `"vector semantic search"` 其中之一。（真模型的判斷偶爾會不同，這裡只驗格式，不驗查法；查法的正式驗收在 Phase 12 用假件做。）

7. **英文提問也試一次**（接續第 6 項，服務保持跑著）
   ```bash
   curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
     -d '{"question":"What drinks did I buy recently?"}' | python -m json.tool
   ```
   預期：`answer` 是**英文**句子（真模型有時會不聽話，這是煙霧測試不是驗收）；三個鍵都在。

8. **回應格式完全符合設計文件**
   ```bash
   curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
     -d '{"question":"我最近買過什麼飲料？"}' | python -c "import json,sys; print(sorted(json.load(sys.stdin)))"
   ```
   預期輸出：`['answer', 'retrieved_photo_ids', 'search_mode']`

---

## 常見問題

**Q1：`AttributeError: 'AIMessage' object has no attribute 'text'` 或 `'method' object ...`。**
LangChain 版本差異。1.x 的 `response.text` 是屬性（不加括號）；0.x 是方法 `response.text()`。用 `uv pip show langchain-core` 看版本，照版本寫；或改用最保險的 `str(response.content)`。本專案現裝 **langchain-core 1.5.6**（已實測 `.text` 屬性可用），計畫程式碼照寫即可。

**Q2：`TypeError: AskDeps.__init__() missing 1 required positional argument: 'answerer'`。**
步驟 8 漏做了。所有建立 `AskDeps` 的地方（產品程式碼與測試）都要補上 `answerer`。

**Q3：`search_mode` 回傳 `"metadata"` 而不是 `"metadata search"`。**
內部用短代號、對外用全名，中間靠 `config.SEARCH_MODE_LABELS` 轉換。確認 `ask.py` 是 `config.SEARCH_MODE_LABELS[state["mode"]]` 而不是直接回 `state["mode"]`。

**Q4：`ask.py` 裡的參數為什麼叫 `router_client` 而不是 `router`？**
因為 `router` 這個名字已經被檔案最上面的 `router = APIRouter(...)` 用掉了。同名會互相蓋掉，所以端點參數改叫 `router_client`。

**Q5：可不可以讓 LLM 一起回傳 `retrieved_photo_ids`？**
不行。design.md 明訂這兩個欄位直接取自流程 state、不經過 AI——可驗證的欄位不能給模型改寫的機會。

**Q6：查無資料時，能不能直接寫死一句「查無相關照片」不呼叫 LLM？**
不行。已釐清的決策是「仍交由 LLM 產生查無回覆」。所以空結果也要走 `generate` 節點，只是 prompt 會要求它回覆查無且不得虛構。

**Q7：要不要在產品程式碼裡加一個「偵測提問語言」的函式，然後強制切換 prompt？**
**不要。** prompt 裡一句「回答語言跟隨提問語言」就夠了——LLM 本來就看得出提問是什麼語言。假件裡的 `_looks_english()` 只是為了讓測試結果可預期，那是測試程式碼，不是產品程式碼。

---

## 完成後的專案狀態

兩個 API 都完整了：`POST /photos` 能上傳，`POST /ask` 能判斷查法、檢索照片、產生回答（**語言跟隨提問**），並回傳可被黑箱驗證的 `search_mode` 與 `retrieved_photo_ids`。規則 Q1、Q4、Q5 的行為已實作，只差用 `.feature` 檔正式驗收。測試累計 **60** 個。
