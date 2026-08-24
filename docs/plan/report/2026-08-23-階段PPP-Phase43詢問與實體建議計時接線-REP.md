# 階段PPP REP：Phase 43 詢問與實體建議的計時接線（階段乙完結）

> 日期：2026-08-23　狀態：✅ 程式、自動化測試與主 agent 真模型自查完成；**G1 人工確認待辦**
> 對應 TODO：`2026-08-23-階段PPP-Phase43詢問與實體建議計時接線-TODO.md`
> 計畫：`docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`；design：`design4.md` §5.1〜§5.4、D7、§9 第 5 列
> 開工基準（實測）：379 passed ＋ 2 skipped → 收工：**384 passed ＋ 2 skipped**（+5，恰為本 phase 新增）

## 實作邏輯

階段乙的最後一步：把 `ai_timing.log_ai()` 接到剩下三種 AI 呼叫上——
判斷查法（`route`）、產生回答（`answer`）、詢問走語意查詢時的轉向量（`embed`），
再加上「再建議一個實體」（`entity_suggest`，本機與雲端各一處）。
做完之後 design4 §5.1 那張表**五種 kind 全部有了**，`app/` 底下恰好 8 個呼叫點。

log 上看得出「這一題走哪條路」：走語意查詢是三組（route＋embed＋answer），
走條件／實體／待辦只有兩組（route＋answer）——那三路只查 SQL，
根本不必把問題轉成向量。這正是本 phase 的價值（design4 §5.2 最後一句）。

三個關鍵設計點，全部照計畫落地：

1. **`route_node` 的 `with` 放在 `try` 裡面**（計畫 §7 點名「本 phase 最容易寫錯的一行」）。
   例外先穿過 `log_ai`（打 `ok=false`）再被 `except` 接住；放外面就會變成
   「例外被 except 吃掉、`log_ai` 根本不知道失敗過」，永遠 `ok=true`。
   `except` 底下那三行既有註解與 `logger.warning` 一個字都沒動，
   `if not isinstance(decision, RouteDecision): …` 也完全不動——fallback 語意一字未變。
2. **`generate_node` 不加 try/except**。回答失敗仍然 500 不吞錯；`log_ai` 打完
   `ok=false` 之後例外繼續往外飛。`return` 寫在 `with` 裡面沒問題——
   Python 保證離開區塊時仍會執行結束那一段（測試 1 的 `ok=true` 結束行就是證據）。
3. **`embed` 只包 `vector_search` 裡 `embed_query` 那一行**。不包 `photo_retriever`
   那一層（四條路都會打 `kind=embed`，其中三條根本沒轉向量＝log 說謊），
   也不包底下的 `search_by_vector` 與 Document 組裝（那是 SQL 與資料處理，
   包進去 `elapsed_s` 會把資料庫時間算成模型時間）。

`entity_suggest` 反而**包在類別裡**（design4 §5.3／§5.4 明白指定「本機＋雲端各一處」），
與 route／answer 包在流程圖節點的做法不同。代價是 `tests/fakes.py` 的
`FakeEntitySuggester` 不會打 log——所以那兩顆測試用「真的類別＋假的內部模型」來測，
沿用 `test_design3_error_paths.py` 的 `_建一個不連線的建議器()` 與本檔既有的
`_雲端建議()`（`FakeCloudChat`＋`雲端假key` autouse fixture）。
雲端那邊把 `chat` **與解析一起**包進 `with`：雲端回了解析不出來的東西，
對這次呼叫來說就是失敗（與看圖「看不懂 → `ok=false`」一致），
但 `except` 仍然回 `None` 不往外炸——語意一個字沒變。

## 步驟（TDD 鐵序）

1. 寫 TODO。
2. 續寫 `tests/integration/test_ai_timing_log.py` 三顆（沿用 Phase 42 的
   `開始行()`／`結束行()`）＋續寫 `tests/unit/test_entity_suggestion_unit.py` 兩顆。
3. **跑紅**（證據見下）→ **8 passed（既有）＋ 5 failed（新的）**，既有八顆無一變紅。
4. `app/services/ask_workflow.py`：import 加 `ai_timing`；`route_node` 的 `with` 放進 `try`；
   `generate_node` 包 `answer`（docstring 補一句「刻意不加 try/except」）。
5. `app/services/retrieval_service.py`：import 加 `ai_timing`；`vector_search` 只包 `embed_query` 那一行。
6. `app/services/entity_suggestion_service.py`：import 加 `ai_timing`；本機 `pick` 的 `with`
   放進 `try`（後面三行原封不動）；雲端 `pick` 把 `chat`＋解析一起包進 `with`。
7. 跑綠四連 → 驗收清單逐項核對。

## 測試方式

五顆新測試分兩個檔：

**A. `tests/integration/test_ai_timing_log.py`**（走 `TestClient` 打 `POST /ask`，
問句用 `tests/fakes.py` 的 `FakeRouter` 登記過的那幾句）

| # | 測試 | 驗什麼 |
|---|---|---|
| 1 | `test_詢問走語意查詢會打route與embed與answer三組` | 問「我最近買過什麼飲料？」→ 三種 kind 的開始／結束**各 1 條**、三個結束行都 `ok=true`；`search_mode` 仍是 `vector semantic search` |
| 2 | `test_詢問走條件查詢沒有embed那一組` | 問「有哪些在 Target 拍的收據？」→ 有 `route`、有 `answer`、**完全沒有** `embed`；`search_mode` 仍是 `metadata search` |
| 3 | `test_路由失敗時route標ok為false且仍走語意查詢` | 問 `FakeRouter` **沒登記**的「幫我找找之前那個」（它會丟例外）→ `route` 結束行 `ok=false`；**仍然**看得到 `embed` 與 `answer`（fallback 成語意查詢）；`search_mode` 仍是 `vector semantic search` |

**B. `tests/unit/test_entity_suggestion_unit.py`**（不碰網路、不碰資料庫）

| # | 測試 | 驗什麼 |
|---|---|---|
| 4 | `test_本機實體建議會打entity_suggest的log` | `AI_BACKEND="local"`＋真 `OllamaEntitySuggester()`（建構子不連線）換掉 `_model` → 開始／結束各 1 行、`ok=true`、`backend=local model={config.LLM_MODEL}` |
| 5 | `test_雲端實體建議的log是cloud且失敗標ok為false` | `AI_BACKEND="cloud"`：① 正常回 JSON → `backend=cloud model={config.OLLAMA_CLOUD_LLM_MODEL}`、`ok=true`；②（`caplog.clear()` 後）回 `- entity：…` 解析不出來 → `ok=false` 且 `pick()` 仍回 `None` |

兩個坑（計畫 §4.2 B 表）都照當時 phase-local 初版做了：未帶 target 時，`backend`／`model`
由 `log_ai` 從 `config` fallback；最終真實 client 已改為傳建構時選定的 immutable target，
不受後續 config 開關 relabel。上表的 monkeypatch／config 斷言是歷史初版證據；最新 regression
另直接斷言 client 的 `timing_target` 與實際建構 model 一致。
`雲端假key` 是本檔既有的 autouse fixture（固定 ASCII 假值），新測試直接受益、不必重寫。

秒數一律不驗數字（design4 §5.3 明文），只看行數與 `ok=` 真假。
`tests/fakes.py` 一個字都沒改——`FakeRouter`「沒登記就丟例外」正是測試 3 要用的設計。

## 遇到的問題與解法

| 問題 | 解法 |
|---|---|
| `generate_node` 的 `return` 要不要挪到 `with` 外面 | 不用。Python 保證離開 `with` 時仍會執行 `__exit__`（helper 的 `finally`），結束行照打；挪出來反而要多一個區域變數。測試 1 的 `answer` 結束行 `ok=true` 就是證據 |
| 雲端 `pick` 的 `with` 要包到哪裡 | 照計畫把 `chat` **與解析一起**包進去：解析不出來對這次呼叫就是失敗。`except` 完全不動，仍回 `None` 不往外炸——`test_雲端建議_解析不出時回None並留log`（既有）保持綠 |
| 「prompt 有沒有被動到」怎麼證 | `git diff -U0 -- app/services` 過濾 prompt 相關符號，唯一命中是 `messages=[{"role": "user", "content": prompt}]` 的**縮排**變動（進了 `with` 區塊），內容逐字相同。釘住「雲端送出去的字串 ＝ 共用 builder 輸出＋雲端 JSON 指令」的既有測試（`test_entity_suggestion_unit.py` 第 53 行、`test_ask_workflow_unit.py`）全綠 |

## 測試結果

**紅（實作前）**——`pytest tests/integration/test_ai_timing_log.py tests/unit/test_entity_suggestion_unit.py -v`：

```text
FAILED tests/integration/test_ai_timing_log.py::test_詢問走語意查詢會打route與embed與answer三組
FAILED tests/integration/test_ai_timing_log.py::test_詢問走條件查詢沒有embed那一組
FAILED tests/integration/test_ai_timing_log.py::test_路由失敗時route標ok為false且仍走語意查詢
FAILED tests/unit/test_entity_suggestion_unit.py::test_本機實體建議會打entity_suggest的log
FAILED tests/unit/test_entity_suggestion_unit.py::test_雲端實體建議的log是cloud且失敗標ok為false
==================== 5 failed, 8 passed, 1 warning in 1.14s ====================
```

＝計畫預期的「8 passed、5 failed」逐字命中：既有八顆（Phase 42 的 6 ＋ 雲端實體既有 2）
無一變紅，紅的只有新加的五顆（撈不到 `kind=route`／`embed`／`answer`／`entity_suggest` 的行）。

**綠（實作後）**：

| 指令 | 結果 |
|---|---|
| `pytest test_ai_timing_log.py test_entity_suggestion_unit.py -q` | **13 passed**（8 既有 ＋ 5 新的） |
| `pytest -q` | **384 passed ＋ 2 skipped**（＝ 379 ＋ 5，與計畫預期一致） |
| `OLLAMA_BASE_URL=http://localhost:9 pytest -q` | **384 passed ＋ 2 skipped**（顆數相同＝零外部依賴實證） |
| `pytest test_ask_endpoint.py test_ask_feature.py test_ask_three_paths.py test_workflow_route.py test_ask_workflow_unit.py -q` | **50 passed ＋ 2 skipped**（2 skipped ＝規格 `@未實作` 兩條，摘標屬產品負責人） |

**驗收掃碼**：

| 檢查 | 結果 |
|---|---|
| `grep -rn 'ai_timing\.log_ai("' app/` | **恰 8 處**，與計畫 §6 的表逐列吻合（見下） |
| `route_node` 仍 fallback | `try` 內 `with`，`except` 三行註解＋`logger.warning`＋`decision = None` 原封不動 |
| `generate_node` 仍無 try/except | 只有一層 `with`，例外照樣往外飛（500 不吞錯） |
| `pick()` 仍回 `None` | 本機／雲端兩個 `except` 都原封不動；本機後三行（`isinstance` 判斷、警告、`return None`）也沒被覆蓋 |
| prompt 一字未動 | 見上表；三個 PROMPT 常數與三個 builder 皆未出現在 diff |

八個呼叫點清單：

| 檔案 | 行 | kind |
|---|---|---|
| `app/api/routers/photos.py` | 161 | `vlm`（`_ingest_image`，Phase 42） |
| `app/api/routers/photos.py` | 205 | `embed`（`_ingest_image` 上傳轉向量，Phase 42） |
| `app/api/routers/photos.py` | 472 | `embed`（`assign_folder` 歸類重算，Phase 42） |
| `app/services/ask_workflow.py` | 308 | `route`（`route_node`） |
| `app/services/ask_workflow.py` | 371 | `answer`（`generate_node`） |
| `app/services/retrieval_service.py` | 89 | `embed`（`vector_search` 的 `embed_query`） |
| `app/services/entity_suggestion_service.py` | 97 | `entity_suggest`（本機 `pick`） |
| `app/services/entity_suggestion_service.py` | 133 | `entity_suggest`（雲端 `pick`） |

**動到的檔**：`ask_workflow.py`／`retrieval_service.py`／`entity_suggestion_service.py`（改）
＋ `tests/unit/test_entity_suggestion_unit.py`（續寫）＋ `tests/integration/test_ai_timing_log.py`（Phase 42 新建、本 phase 續寫）。
其餘 `git status` 上的 M／?? 皆為 Phase 38〜41 既有未 commit 的變更，本 phase 未觸碰。

**未做（依主 agent 指示）**：計畫 §4.7 的終端機四條實地看一眼（語意題三組／條件題兩組／
「再建議一個」一組／雲端開關）——埠 8000 有使用者留著的 uvicorn，真模型煙霧由主 agent 統一做。

**下一步不是 Docker**：階段乙三份（41／42／43）已全部打完勾，但閘門 **G1 只有產品負責人能勾**
（design4 §0、§7）——他要親自看過瀏覽器與終端機、明示「甲乙沒問題，可以做 Docker」才算過。
G1 沒過連 `compose.yaml`／`Dockerfile` 都不准建。接下來是 Phase 44（甲乙錯誤收尾與 G1 驗收包）。

## 最終真模型與 runtime 補記（2026-08-24）

主 agent 的 localhost serial QA 得到以下實際 log；全部結束行均為 `ok=true`：

| Backend／路徑 | Route | Embed | Answer／Entity | 契約結果 |
|---|---:|---:|---:|---|
| 本機語意詢問（修正後） | `gemma4:e2b-mlx` 28.9s | `bge-m3` 1.9s | answer 9.1s | `vector semantic search` |
| 本機 metadata 詢問 | 19.5s | **無** | answer 11.1s | `metadata search`，正確省略 embed |
| 本機實體建議 | — | — | entity 12.0s | 回傳建議成功 |
| 雲端語意詢問 | cloud `gemma4` 5.1s | local `bge-m3` 0.1s | cloud answer 5.5s | `vector semantic search` |
| 雲端實體建議 | — | — | cloud entity 3.3s | 回傳建議成功 |

### 真 runtime 揪到並修正的 structured output 問題

本機 `ChatOllama.with_structured_output(...)` 原先使用預設 `json_schema`；真模型在 router／
entity 路徑回了 Markdown，而不是可驗證的結構化物件。以官方 LangChain Docs MCP 與本機已安裝
的 `langchain_ollama` 原始碼交叉核對後，只把這兩個本機 structured-output 呼叫明寫成
`method="function_calling"`，沒有改 prompt、fallback 或雲端路徑。

兩顆 regression 先看到 RED：`with_structured_output` 收到的 kwargs 是 `{}`，預期
`{"method": "function_calling"}`；另以 RED→GREEN 釘住本機 entity 回 `None`／route 回錯型別時
timing 必須 `ok=false`，不得把 structured-output failure 標成成功。修正後納入最終 targeted
**112 passed, 2 skipped, 1 warning in 9.42s** 與 full
**402 passed, 2 skipped, 1 warning in 27.73s**。唯一 warning 是 `StarletteDeprecationWarning`
（`httpx`／`starlette.testclient`）。真模型 serial 重跑亦回到上表的 `ok=true` 結果。

初次實體建議 QA 曾與 `pytest` 並行；測試 fixture 會 truncate 共用的 `PersonalDocAI_test`，
使該次 runtime 讀取碰到 404。那不是產品行為證據，已明確作廢；乾淨 serial 重跑的成功結果
才是本 REP 採用的證據。

狀態：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty，
沒有 commit、沒有 release，也沒有 Docker／compose 檔案。
