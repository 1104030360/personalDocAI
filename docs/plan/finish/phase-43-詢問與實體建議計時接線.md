# Phase 43：詢問與實體建議的計時接線（階段乙第 3 步，乙完結）

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 實作與真模型自驗已完成。**
> 下方 `379 → 384` 是本 phase 當時的歷史基線，不回改；
> 目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，
> 全量為 **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`），
> `ai_timing.log_ai(...)` 生產呼叫點掃碼恰好 **8 處**。
> 串行真模型證據全部 `ok=true`：最新本機語意題 `route 33.4s`／`embed 0.5s`／`answer 14.0s`；
> metadata 題的 phase-local 實跑為 `route 19.5s`／`answer 11.1s`、沒有 `embed`。
> 最新本機實體建議重跑為 `17.6s`；最新雲端語意題為 `route 4.0s`／本機 `embed 0.5s`／
> `answer 3.2s`，雲端實體建議為 `4.3s`。
> 最新 RED→GREEN 釘住 structured-output failure truth：本機 route／entity 使用
> `method="function_calling"`，回傳 `None`／錯型別或解析失敗時 timing 必須 `ok=false`，既有
> fallback／回 `None` 語意不變。真實 router／answerer／entity client 的 immutable target
> 來自 request 已選定 client，切換全域開關不會重新標示已發出的呼叫。
> 狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 把 `log_ai()` 接到剩下三種 AI 呼叫上——
> 判斷查法（`kind=route`）、產生回答（`kind=answer`）、
> 詢問走語意查詢時的轉向量（`kind=embed`），
> 再加上「再建議一個實體」（`kind=entity_suggest`，本機與雲端各一處）。
> 做完之後，design4 §5.1 那張表**五種 kind 全部有了**。

**一句話問答會打幾次模型：** 走語意查詢是三次（判斷 → 轉向量 → 回答）；
走條件查詢／實體查詢／待辦查詢只有兩次（判斷 → 回答），**沒有轉向量那一組**——
因為那三條路根本不需要把問題轉成向量。log 上看得出差別，就是這個 phase 的價值。

---

## 1. 對應 design4.md 章節

- **§5.1**（`route`／`answer`／`embed`（`embed_query`）／`entity_suggest` 四列）
- **§5.2 最後一句**（詢問走 metadata／entity／task ＝**沒有** `embed` 那一組；走 vector 才有）
- **§5.3 後四個呼叫點**（`ask_workflow.route_node`、`retrieval_service.vector_search`、
  `ask_workflow.generate_node`、`entity_suggestion_service` 本機＋雲端各一處）
- **§5.4 第 3、4、5、7 列**（改 `ask_workflow.py`／`retrieval_service.py`／
  `entity_suggestion_service.py`；續寫 `tests/integration/test_ai_timing_log.py`）
- **D7**（詢問：路由、回答、（走向量時）embedding 各一組）
- **§9 錯誤表第 5 列**（路由失敗仍 fallback 成語意查詢，語意不變，只多一行 `ok=false`）

---

## 2. 前置條件

- **Phase 41 已完成**（`ai_timing.log_ai` 可用）。
- **Phase 42 已完成且全綠**（`pytest -q` ＝ 379 passed ＋ 2 skipped；
  `tests/integration/test_ai_timing_log.py` 已存在，本 phase 在同一個檔案續寫）。

> **顆數基準的但書**（與 Phase 41／42 同一條，總覽 §2 也寫了）：379 這個數字是
> 「照編號順序做」算出來的（358 ＋ Phase 38 的 7 顆 ＋ 41 的 8 顆 ＋ 42 的 6 顆）。
> 你若還沒做階段甲（38〜40）就先做乙，把本檔的全量數字各減 7（379→372、384→377）。
> **要對的是「本 phase 恰好多 5 顆」這個差值，不是那個絕對數字**——
> 而且不准為了湊數字去改測試。

---

## 3. 範圍

### 做

- `app/services/ask_workflow.py`：`route_node` 包 `route`、`generate_node` 包 `answer`。
- `app/services/retrieval_service.py`：`vector_search` 裡 `embeddings.embed_query(question)` 那一行包 `embed`。
- `app/services/entity_suggestion_service.py`：`OllamaEntitySuggester.pick` 與
  `OllamaCloudEntitySuggester.pick` 各包一次 `entity_suggest`。
- 續寫 `tests/integration/test_ai_timing_log.py`（詢問那三顆）。
- 續寫 `tests/unit/test_entity_suggestion_unit.py`（實體建議那兩顆）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改路由 fallback 的行為 | §9 第 5 列：語意**不變**。路由失敗仍然一律 fallback 成語意查詢，`route_node` 既有的 try/except 一個字不動 |
| 改回答失敗的行為 | 仍然 500 不吞錯（`generate_node` 不加 try/except） |
| 改實體建議失敗的行為 | 仍然回 `None`＋留 warning，不 500（`pick()` 既有的 try/except 一個字不動） |
| 為 `metadata_search`／`entity_search`／`task_search` 計時 | 它們只查 SQL，不是模型推論（§5.1 明文不計時） |
| 為端點層撈實體名單（`list_entities()`）計時 | 同上，那是 SQL |
| 把 `route`／`answer` 包進 `OllamaRouter`／`OllamaAnswerer` 類別裡 | 那樣 pytest 的 `FakeRouter`／`FakeAnswerLLM` 就不會打 log，測試看不到東西（design4 §5.3：「pytest 的 Fake 也會打 log」）。包在**流程圖節點**才兩邊都涵蓋 |
| 動 `ROUTE_PROMPT`／`ANSWER_PROMPT`／`ENTITY_PICK_PROMPT` | 本 phase 完全不碰 prompt |

> **📌 為什麼 `entity_suggest` 反而包在類別裡（與上面那條看似矛盾）**
> design4 §5.3／§5.4 明白指定「`entity_suggestion_service` 本機＋雲端各一處」，照做。
> 代價是 `tests/fakes.py` 的 `FakeEntitySuggester` 不會打 log——所以那兩顆測試要用
> **真的類別＋假的內部模型**來測（`tests/integration/test_design3_error_paths.py` 與
> `tests/unit/test_entity_suggestion_unit.py` 都已經有這個現成寫法，照抄即可）。

---

## 4. 實作步驟（先寫測試再實作）

### 4.1 先看懂五處呼叫點（不寫程式，只讀）

（design4 §5.3 的後**四個** bullet；其中「實體建議」那一個 bullet 本身就寫明
「本機＋雲端各一處」，所以真正要動的地方是**五處**。）

| 檔案 | 位置（約） | 那一行 | 要包成 |
|---|---|---|---|
| `app/services/ask_workflow.py` | 306 | `decision = deps.router.route(state["question"], deps.entity_names)` | `kind=route` |
| `app/services/retrieval_service.py` | 85 | `question_vector = embeddings.embed_query(question)` | `kind=embed` |
| `app/services/ask_workflow.py` | 364 | `deps.answerer.answer(state["question"], state["retrieved"])` | `kind=answer` |
| `app/services/entity_suggestion_service.py` | 97 | `result = self._model.invoke([message])` | `kind=entity_suggest`（本機） |
| `app/services/entity_suggestion_service.py` | 130 | `response = self._client.chat(...)` ＋下面那段解析 | `kind=entity_suggest`（雲端） |

- [ ] 特別看清楚 `route_node` 現在的結構（第 303〜315 行，**下面是逐字照抄**，
      中間那三行註解是既有的，等一下改的時候不要順手刪掉）：

```python
    def route_node(state: AskState) -> dict[str, Any]:
        """判斷查法。任何失敗都 fallback 成語意查詢、條件全空。"""
        try:
            decision = deps.router.route(state["question"], deps.entity_names)
        except Exception:
            # fallback 是設計，但一定要留 log：不然「模型名打錯」「Ollama 沒開」
            # 「雲端 404」全都無聲變成「怎麼每一題都走語意查詢」
            # （2026-08-22 雲端煙霧的教訓——路由 404 被吞掉、只有回答那步炸出來）
            logger.warning("路由呼叫失敗，fallback 成語意查詢", exc_info=True)
            decision = None
```

  **`with` 要放在 `try` 裡面**，這樣例外會先穿過 `log_ai`（打 `ok=false`）再被 `except` 接住。
  放在 `try` 外面就會變成「例外被 except 吃掉了，`log_ai` 根本不知道失敗過」。

### 4.2 先寫測試（此時應該是紅的）

> **兩個 pytest 內建工具（前面 phase 用過，這裡再提一次）**
> `caplog`＝把這顆測試期間打出來的 log 收集起來，讓你用 `caplog.messages` 斷言；
> 記得第一行 `caplog.set_level(logging.INFO)`，不然 INFO 訊息會被濾掉、撈到空的。
> `monkeypatch`＝暫時改掉某個變數，**測試結束自動還原**，所以撥 `config.AI_BACKEND`
> 一律用它（直接指派會污染同一個 process 裡後面的測試）。

**A. 續寫 `tests/integration/test_ai_timing_log.py`**（沿用 Phase 42 已寫好的
`開始行(caplog, kind)`／`結束行(caplog, kind)` 兩個小工具）

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 1 | `test_詢問走語意查詢會打route與embed與answer三組` | `POST /ask` 問一句 `FakeRouter` 登記成 `vector` 的問題（例如「我最近買過什麼飲料？」）→ `kind=route`／`kind=embed`／`kind=answer` 的開始行**各 1 條**，三個結束行都 `ok=true` |
| 2 | `test_詢問走條件查詢沒有embed那一組` | 問一句登記成 `metadata` 的問題（例如「有哪些在 Target 拍的收據？」）→ 有 `kind=route`、有 `kind=answer`、**完全沒有** `kind=embed`（design4 §5.2 最後一句） |
| 3 | `test_路由失敗時route標ok為false且仍走語意查詢` | 問一句 `FakeRouter` **沒登記**的問題（它會丟例外）→ `kind=route` 結束行含 `ok=false`；同時**仍然**看得到 `kind=embed`（fallback 成語意查詢，語意不變）；回應 `search_mode` 仍是 `"vector semantic search"` |

**B. 續寫 `tests/unit/test_entity_suggestion_unit.py`**

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 4 | `test_本機實體建議會打entity_suggest的log` | 先 `monkeypatch.setattr(config, "AI_BACKEND", "local")`（**明寫，別靠預設值**，理由見 Phase 41 §4.3）→ 建一個 `OllamaEntitySuggester()`、把 `_model` 換成回 `EntityPick(entity="我的 MacBook")` 的小假件（**建構子不會連線**，這個寫法在 `tests/integration/test_design3_error_paths.py` 第 202 行的 `_建一個不連線的建議器()` 已有先例）→ `pick()` 之後 `caplog` 有 `kind=entity_suggest` 的開始／結束各 1 行、`ok=true`、`backend=local`、`model={config.LLM_MODEL}` |
| 5 | `test_雲端實體建議的log是cloud且失敗標ok為false` | 先 `monkeypatch.setattr(config, "AI_BACKEND", "cloud")`，再用本檔既有的 `_雲端建議(...)` 工具（`FakeCloudChat`＋`雲端假key` fixture）：<br>① 正常回 JSON → `backend=cloud`、`model={config.OLLAMA_CLOUD_LLM_MODEL}`、`ok=true`；<br>② 回 `"- entity：…"`（解析不出來）→ `ok=false` 且 `pick()` 仍回 `None`（**不往外炸**，語意不變） |

> **測試 5 的歷史 phase-local 做法與最終真相**
> 1. 初版測試以 `monkeypatch.setattr(config, "AI_BACKEND", "cloud")` 驗 helper fallback。
> 2. 最終真實 client 的 `backend`／`model` 來自建構時選定的 immutable `timing_target`，
>    不是事後重讀 config。假件沒有 `timing_target` 時才走上述 fallback；不得把兩者混稱。
>    本檔的 `_雲端建議()` 寫的是 `OllamaCloudEntitySuggester(model="gemma4")`，
>    但 log 印的是 `config.OLLAMA_CLOUD_LLM_MODEL`（`.env` 可覆蓋）。
>    所以斷言要寫成 f-string 帶 `config.OLLAMA_CLOUD_LLM_MODEL`，
>    **不要**寫死 `model=gemma4`——那會變成「測試綁死某台開發機的 `.env`」。

- [ ] 跑一次確認**真的是紅的**：

```bash
pytest tests/integration/test_ai_timing_log.py tests/unit/test_entity_suggestion_unit.py -v
```

  預期：**8 passed、5 failed**。這兩個檔都是「續寫」，裡面本來就有既有的測試
  （`test_ai_timing_log.py` 6 顆是 Phase 42 寫的、`test_entity_suggestion_unit.py` 2 顆是
  2026-08-22 雲端那批），它們**必須仍是綠的**；紅的只有你剛加的 5 顆
  （撈不到 `kind=route`／`kind=embed`／`kind=answer`／`kind=entity_suggest` 的行）。
  既有 8 顆有任何一顆變紅，代表你不小心改到別的東西，先回頭處理再往下。

### 4.3 改 `ask_workflow.py`

- [ ] 檔頭 import 加上 `ai_timing`：

```python
from app.services import ai_timing, ollama_cloud, retrieval_service
```

- [ ] `route_node`（**`with` 在 `try` 裡面**）：

```python
        try:
            # 計時包在 try 裡面：例外要先穿過 log_ai（打 ok=false）再被下面接住，
            # 「失敗就 fallback 成語意查詢」的語意一個字都沒變（design4.md §9 第 5 列）
            with ai_timing.log_ai("route"):
                decision = deps.router.route(state["question"], deps.entity_names)
        except Exception:
            # fallback 是設計，但一定要留 log：不然「模型名打錯」「Ollama 沒開」
            # 「雲端 404」全都無聲變成「怎麼每一題都走語意查詢」
            # （2026-08-22 雲端煙霧的教訓——路由 404 被吞掉、只有回答那步炸出來）
            logger.warning("路由呼叫失敗，fallback 成語意查詢", exc_info=True)
            decision = None
```

  （`except` 底下那三行註解是**既有的**，一個字都不用改也不要刪——
  它記的是為什麼 fallback 一定要留 warning，和本 phase 的計時是兩回事。
  再下面的 `if not isinstance(decision, RouteDecision): …` 那一段也完全不動。）

- [ ] `generate_node`：

```python
    def generate_node(state: AskState) -> dict[str, Any]:
        """只依撈到的照片內容產生回答；撈不到就由 LLM 回覆查無相關照片。"""
        with ai_timing.log_ai("answer"):
            return {
                "answer": deps.answerer.answer(state["question"], state["retrieved"])
            }
```

  （`return` 寫在 `with` 裡面沒問題：Python 保證離開區塊時仍會執行結束那一段。）

### 4.4 改 `retrieval_service.py`

- [ ] 檔頭 import 加上 `ai_timing`：

```python
from app.services import ai_timing, indexing_service
```

- [ ] `vector_search`：

```python
def vector_search(
    question: str,
    embeddings: Embeddings,
    filters: QueryFilters,
    today: date,
) -> list[Document]:
    """語意查詢：問題轉成向量，找最接近的 TOP_K 張。"""
    # 只有這一條路會把問題轉成向量——metadata／entity／task 三路都不必，
    # 所以 log 上「有沒有 kind=embed」就看得出這次走的是哪一種查法（design4.md §5.2）
    with ai_timing.log_ai("embed"):
        question_vector = embeddings.embed_query(question)
    rows = photo_repository.search_by_vector(…)   # ← 這行以下原封不動
    …
```

  **只多包那一行 `embed_query`。** 底下的 `search_by_vector(...)` 與
  `return [row_to_document(row) for row in rows]` 是查 SQL 與組裝資料，
  包進去只會讓 `elapsed_s` 說謊（把資料庫時間算成模型時間）。

### 4.5 改 `entity_suggestion_service.py`

- [ ] 檔頭 import 加上 `ai_timing`：

```python
from app.services import ai_timing, ollama_cloud
```

- [ ] 本機 `OllamaEntitySuggester.pick`：

```python
        message = HumanMessage(content=_build_pick_prompt(photo, candidates))
        try:
            with ai_timing.log_ai("entity_suggest"):
                result = self._model.invoke([message])
        except Exception:
            logger.warning("實體建議呼叫失敗，這次就不給建議", exc_info=True)
            return None
```

  ⚠️ **這段只到 `except` 為止**：函式後面那三行
  （`if isinstance(result, EntityPick): return result.entity`、
  「未回傳有效的結構化結果」的 warning、最後的 `return None`）**原封不動留著**，
  不要跟著上面的程式碼區塊一起被覆蓋掉。

- [ ] 雲端 `OllamaCloudEntitySuggester.pick`（把 `chat` 與**解析**一起包進去——
      雲端回了解析不出來的東西，對這次呼叫來說就是失敗，與看圖那邊的處理一致）：

```python
        prompt = _build_pick_prompt(photo, candidates) + CLOUD_PICK_JSON_INSTRUCTION
        try:
            with ai_timing.log_ai("entity_suggest"):
                response = self._client.chat(…)
                result = EntityPick.model_validate_json(
                    ollama_cloud.extract_json_object(response.message.content or "")
                )
        except Exception:
            logger.warning("實體建議（雲端）呼叫失敗，這次就不給建議", exc_info=True)
            return None
        return result.entity
```

### 4.6 跑綠

```bash
pytest tests/integration/test_ai_timing_log.py tests/unit/test_entity_suggestion_unit.py -v
                                                      # 預期 13 passed（8 既有 ＋ 5 新的）
pytest -q                                             # 預期 384 passed ＋ 2 skipped
OLLAMA_BASE_URL=http://localhost:9 pytest -q          # 顆數相同
```

- [ ] **特別確認詢問那幾顆既有測試沒有變紅**（守的是「語意不變」）：

```bash
pytest tests/integration/test_ask_endpoint.py tests/integration/test_ask_feature.py \
       tests/integration/test_ask_three_paths.py tests/integration/test_workflow_route.py \
       tests/unit/test_ask_workflow_unit.py -v
```

### 4.7 終端機實地看一眼（design4 §6「終端機（乙，G1 用）」第三條）

- [x] 起真的伺服器（真 Ollama 要開著）：

```bash
uvicorn app.main:app --reload --port 8000
```

- [x] 開 `http://localhost:8000/ui/ask.html`，問一句語意題
      （例如「我最近買過什麼飲料？」），終端機應該看到**三組**：

```text
INFO:     AI 開始 kind=route backend=local model=gemma4:e2b-mlx
INFO:     AI 結束 kind=route backend=local model=gemma4:e2b-mlx elapsed_s=8.2 ok=true
INFO:     AI 開始 kind=embed backend=local model=bge-m3
INFO:     AI 結束 kind=embed backend=local model=bge-m3 elapsed_s=0.3 ok=true
INFO:     AI 開始 kind=answer backend=local model=gemma4:e2b-mlx
INFO:     AI 結束 kind=answer backend=local model=gemma4:e2b-mlx elapsed_s=11.5 ok=true
```

  （欄位之間就是**一個空格**，不會為了對齊補空白——上面每一行都照真實輸出抄。
  模型名以你 `.env` 的實際設定為準：`route`／`answer` 用 `LLM_MODEL`、
  `embed` 用 `EMBEDDING_MODEL`。）

- [x] 再問一句條件題（例如「有哪些在 Target 拍的收據？」）→ 只有 `route` 與 `answer` **兩組**。
- [x] 開 `http://localhost:8000/ui/browse.html` 的「待決定」分頁點一張照片 →
      抽屜窗按「稍後再說」→ 實體窗按「再建議一個」→
      終端機應該看到**一組 `kind=entity_suggest`**。
      （前提：資料庫裡至少要有一個實體可挑。候選空的時候端點根本不會問模型，
      自然也不會有 log——那是 Phase 30 既有的設計，不是壞掉。）
- [x] 把 `ask.html` 頁首開關撥到「雲端」再問一次 → `route`／`answer` 的 `backend` 變 `cloud`，
      `embed` 仍是 `local`。（要撥得動，`.env` 得有 `OLLAMA_API_KEY`；沒填時開關會回 422
      並停在「本機」——那是 2026-08-22 既有行為，不是本 phase 弄壞的。）

---

## 5. ASCII 圖：一次詢問打幾組 log

```text
   POST /ask  「我最近買過什麼飲料？」
        │
        ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ ask_workflow.route_node                                        │
   │   with log_ai("route"):  router.route(問題, 實體名單)          │
   │     成功 → decision                                            │
   │     失敗 → 例外先穿過 log_ai（打 ok=false）再被 except 接住    │
   │            → fallback 成語意查詢（語意一個字沒變）             │
   └─────────────────────────────┬──────────────────────────────────┘
                                 │ 條件邊挑一條路（四選一）
      ┌───────────┬──────────────┴────────────────┬─────────┐
      ▼           ▼                               ▼         ▼
      metadata    vector                          entity    task
      只查 SQL    ★ with log_ai("embed"):         只查 SQL  只查 SQL
      不打模型        embeddings.embed_query      不打模型  不打模型
      │           │                               │         │
      └───────────┴──────────────┬────────────────┴─────────┘
                                 ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ ask_workflow.generate_node                                     │
   │   with log_ai("answer"):  answerer.answer(問題, 撈到的照片)    │
   └────────────────────────────────────────────────────────────────┘

   ★ 只有 vector 這一路會把問題轉成向量；另外三路只查 SQL，
     所以 log 上「有沒有 kind=embed」就看得出這次走的是哪一種查法。

   走 vector  →  route ＋ embed ＋ answer ＝ 三組
   走其他三路 →  route ＋ answer          ＝ 兩組


   「再建議一個」是另一條完全獨立的路（不看圖、不轉向量、不進上面這張圖）：

   POST /photos/{id}/entity-suggestion
        └─► entity_suggestion_service 的 pick()（本機／雲端各一份實作）
              with log_ai("entity_suggest"):  模型從候選裡挑一個
              失敗 → ok=false，然後回 None（不是 500，語意一個字沒變）
```

---

## 6. 驗收清單

- [ ] 五顆新測試**先紅後綠**
- [ ] `pytest -q` ＝ **384 passed ＋ 2 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] design4 §5.1 那張表**五種 kind 全部接完**：
      `grep -rn 'ai_timing\.log_ai("' app/` 應該恰好 **8 處**——

| 檔案 | 幾處 | 分別是 |
|---|---|---|
| `app/api/routers/photos.py` | 3 | `_ingest_image` 的 `vlm`、`_ingest_image` 的 `embed`、`assign_folder` 的 `embed`（Phase 42） |
| `app/services/ask_workflow.py` | 2 | `route_node` 的 `route`、`generate_node` 的 `answer` |
| `app/services/retrieval_service.py` | 1 | `vector_search` 的 `embed` |
| `app/services/entity_suggestion_service.py` | 2 | 本機 `pick`、雲端 `pick` 的 `entity_suggest` |

> 為什麼要帶 `ai_timing\.` 這個前綴：`app/services/ai_timing.py` 自己的 docstring 裡
> 有一句範例 `with log_ai("vlm") as 計時: …`，只 grep `log_ai("` 會把它也算進去、
> 變成 9 處而白緊張一場。呼叫端一律寫 `ai_timing.log_ai(...)`，加前綴才數得準。
> （反斜線是跳脫小數點，讓它只比對真正的「.」。）

- [ ] 既有詢問測試全綠（`test_ask_endpoint`／`test_ask_feature`／`test_ask_three_paths`／
      `test_workflow_route`／`test_ask_workflow_unit`）
- [ ] `app/services/ask_workflow.py` 的 `route_node` 仍然是「失敗 → fallback vector」，
      `generate_node` 仍然**沒有** try/except，`pick()` 仍然回 `None` 不炸
- [x] §4.7 的終端機四條實地看過
- [ ] 只動到五個檔。查法要分兩條指令，因為 `tests/integration/test_ai_timing_log.py`
      是 Phase 42 新建、**還沒 `git add`**，`git diff` 看不到它：

```bash
git diff --stat -- app tests    # 恰好三個檔（ask_workflow／retrieval_service／entity_suggestion_service）
                                # ＋ tests/unit/test_entity_suggestion_unit.py，共 4 行
git status --short -- app tests # 另有 ?? app/services/ai_timing.py（P41）
                                #      ?? tests/integration/test_ai_timing_log.py（P42，本 phase 有續寫）
```

- [ ] **階段乙到此完結**——Phase 41／42／43 三份都打完勾了才往下走
- [ ] **下一步是 Phase 44（甲乙錯誤收尾與 G1 驗收包），不是 Docker。**
      閘門 **G1 只有產品負責人（人）能勾**：他要親自看過瀏覽器與終端機、
      明示「甲乙沒問題，可以做 Docker」才算過（design4 §0、§7）。
      實作者不得自行勾選、不得推論，**G1 沒過連 `compose.yaml`／`Dockerfile` 都不准建**

---

## 7. 常見陷阱

1. **`with` 放到 `try` 外面**（`route_node`）：例外被 `except` 吃掉，`log_ai` 看不到失敗，
   永遠打 `ok=true`。這是本 phase 最容易寫錯的一行。

2. **順手給 `generate_node` 加 try/except**：不要。回答失敗必須 500 不吞錯
   （design.md 錯誤處理總表的既有決定）。`log_ai` 打完 `ok=false` 之後例外要繼續往外飛。

3. **把 `embed` 包在 `photo_retriever` 那一層**：那樣四條路都會打 `kind=embed`，
   而其中三條根本沒有轉向量——log 就說謊了。一定要包在 `vector_search` 裡面那一行。

4. **`FakeRouter` 沒登記的問題會丟例外**：這是它的設計（模擬「模型判斷不出來」），
   測試 3 就是靠它。不要為了讓測試好寫而去改 `tests/fakes.py` 的行為。

5. **雲端測試忘了假 key**：`OllamaCloudEntitySuggester()` 建構時會拿 `config.OLLAMA_API_KEY`
   組 HTTP header（`ollama_cloud.build_client()` 的 `Bearer …`）。**HTTP header 不吃非 ASCII**，
   填中文假 key 會當場炸；填空值雖然建得起來，但測試會隨開發機 `.env` 有沒有填真 key 而變色。
   `tests/unit/test_entity_suggestion_unit.py` 已經有 `雲端假key` 這個 autouse fixture
   （固定 ASCII 假值 `"test-key"`），照用就好——它是 autouse，新測試不必自己再寫一次。

6. **把真實 client 與假件 fallback 混在一起**：真實 client 的 immutable target 會如實標成
   local／cloud，且不受後續全域開關影響；只有沒有 `timing_target` 的假件才由 `log_ai` 讀
   `config.AI_BACKEND` fallback。測試必須先說清楚正在驗哪一條路。

7. **改到 prompt**：`ROUTE_PROMPT`／`ANSWER_PROMPT`／`ENTITY_PICK_PROMPT` 與
   `build_route_prompt`／`build_answer_prompt`／`_build_pick_prompt` 都是本機與雲端**逐字共用**的，
   而且有測試釘著「雲端送出去的字串 ＝ 同一個 builder 的輸出（＋雲端那段 JSON 指令）」
   （`tests/unit/test_ask_workflow_unit.py` 第 67〜70、89〜91 行；
   `tests/unit/test_entity_suggestion_unit.py` 第 53 行）。
   本 phase 只加 `with`，prompt 一個字都不要碰。
