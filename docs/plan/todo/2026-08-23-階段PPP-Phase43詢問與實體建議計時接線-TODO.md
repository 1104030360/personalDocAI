# 階段PPP TODO：Phase 43 詢問與實體建議的計時接線（階段乙完結）

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP；計畫 §4.7 真模型終端機實驗已由主 agent 完成）
> 依據：`docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`（逐條照做）＋`docs/design/design4.md` §5.1〜§5.4、D7、§9 第 5 列
> 開工基準（已實測）：`pytest -q` ＝ 379 passed ＋ 2 skipped（Phase 42 收工數）

> **後續最終狀態：** 上述 379＋2 是歷史 phase-local 基準；目前 targeted suite 為
> **112 passed、2 skipped、1 warning（9.42s）**，full suite 為
> **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`），
> 且 `ai_timing.log_ai(...)` 生產呼叫點恰 **8 處**。
> 真模型串行自驗全部 `ok=true`：最新本機語意題重跑為
> `route 33.4s/embed 0.5s/answer 14.0s`；metadata 題的 phase-local 實跑為
> `route 19.5s/answer 11.1s`、無 `embed`；最新本機實體重跑為 `17.6s`；
> 最新雲端語意題為 `route 4.0s`／本機 `embed 0.5s`／`answer 3.2s`，雲端實體為 `4.3s`。
> 最新 RED→GREEN 釘住本機 structured output 的 `function_calling`、None／錯型別／解析失敗的
> `ok=false` truth，以及真實 client 使用 request 已選定 immutable target、不被後續開關 relabel。
> 狀態為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

## 實作邏輯

階段乙的最後一步：把 `ai_timing.log_ai()` 接到剩下三種 AI 呼叫上——
判斷查法（`kind=route`）、產生回答（`kind=answer`）、詢問走語意查詢時的轉向量
（`kind=embed`），再加上「再建議一個實體」（`kind=entity_suggest`，本機與雲端各一處）。
做完之後 design4 §5.1 那張表**五種 kind 全部有了**。

一句話問答會打幾次模型：走語意查詢是三次（判斷 → 轉向量 → 回答）；
走條件／實體／待辦查詢只有兩次（判斷 → 回答），**沒有轉向量那一組**——
那三條路只查 SQL，根本不必把問題轉成向量。log 上看得出差別，就是本 phase 的價值。

三個關鍵設計點：

- **`route_node` 的 `with` 要放在 `try` 裡面**（本 phase 最容易寫錯的一行）。
  這樣例外會先穿過 `log_ai`（打 `ok=false`）再被 `except` 接住；放外面就變成
  「例外被 except 吃掉了、`log_ai` 根本不知道失敗過」，永遠 `ok=true`。
  fallback 的行為一個字不動（失敗仍一律走語意查詢）。
- **`generate_node` 不加 try/except**。回答失敗必須 500 不吞錯（design.md 錯誤表既有決定）；
  `log_ai` 打完 `ok=false` 之後例外要繼續往外飛。
- **`embed` 只包 `vector_search` 裡 `embed_query` 那一行**，不包 `photo_retriever` 那一層
  （那樣四條路都會打 `kind=embed`，其中三條根本沒轉向量＝log 說謊），
  也不包底下的 `search_by_vector`／組裝（那是 SQL 與資料處理，包進去 `elapsed_s` 會說謊）。

`entity_suggest` 反而**包在類別裡**（design4 §5.3／§5.4 明白指定「本機＋雲端各一處」），
與 route／answer 包在流程節點不同。代價是 `tests/fakes.py` 的 `FakeEntitySuggester`
不會打 log，所以那兩顆測試要用**真的類別＋假的內部模型**來測（既有寫法照抄）。

## 步驟（TDD：先紅再綠）

- [x] **紅**：續寫 `tests/integration/test_ai_timing_log.py` 三顆（沿用 Phase 42 的
      `開始行()`／`結束行()`）：語意題三組／條件題無 embed／路由失敗 `ok=false` 仍 fallback。
- [x] **紅**：續寫 `tests/unit/test_entity_suggestion_unit.py` 兩顆：本機 `entity_suggest`
      log（`backend=local`、`model={config.LLM_MODEL}`）／雲端 `backend=cloud` 且解析失敗
      標 `ok=false` 仍回 `None`。這是 phase-local 初版測試做法；最終真實 client 會傳建構時
      選定的 immutable target，只有假件／helper default 未帶 target 時才依 config fallback。
      `雲端假key` 是既有 autouse fixture，直接受益。
- [x] 跑 `pytest tests/integration/test_ai_timing_log.py tests/unit/test_entity_suggestion_unit.py -v`
      確認 **8 passed（既有）＋ 5 failed（新的）**；既有任何一顆變紅就先停下處理。
- [x] **綠**：`app/services/ask_workflow.py`——`route_node`（`with` 在 `try` 裡面，
      既有三行 fallback 註解與 warning 一字不動）與 `generate_node`（不加 try/except）；
      檔頭 import 加 `ai_timing`。
- [x] **綠**：`app/services/retrieval_service.py`——只包 `embed_query(question)` 那一行；
      檔頭 import 加 `ai_timing`。
- [x] **綠**：`app/services/entity_suggestion_service.py`——本機 `pick`（`with` 在 `try` 裡、
      後面三行原封不動）與雲端 `pick`（`chat` ＋解析一起包進 `with`，`except` 回 `None`
      語意不變）；檔頭 import 加 `ai_timing`。
- [x] 跑綠四連：兩檔合跑 **13 passed（8 既有＋5 新）** → `pytest -q` ＝ **384 ＋ 2 skipped** →
      指死埠同顆數 → 計畫 §4.6 點名的五個詢問既有測試檔逐一跑過。
- [x] 計畫 §6 驗收清單逐項核對（`grep -rn 'ai_timing\.log_ai("' app/` 恰 **8 處**、
      `route_node` 仍 fallback、`generate_node` 仍無 try/except、`pick()` 仍回 `None`、
      prompt 一字未動）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改路由 fallback 的行為 | §9 第 5 列：語意不變。路由失敗仍一律 fallback 成語意查詢，既有 try/except 一字不動 |
| 給 `generate_node` 加 try/except | 回答失敗仍 500 不吞錯 |
| 改實體建議失敗的行為 | 仍回 `None`＋留 warning，不 500 |
| 為 `metadata_search`／`entity_search`／`task_search`／`list_entities()` 計時 | 只查 SQL，不是模型推論（§5.1 明文） |
| 把 `route`／`answer` 包進 `OllamaRouter`／`OllamaAnswerer` 類別裡 | 那樣 pytest 的假件不會打 log；包在**流程圖節點**才兩邊都涵蓋 |
| 動 `ROUTE_PROMPT`／`ANSWER_PROMPT`／`ENTITY_PICK_PROMPT` 與三個 builder | 本 phase 完全不碰 prompt（有測試釘著本機／雲端逐字共用） |
| 測試斷言 `elapsed_s` 等於某個數字 | design4 §5.3 明文：只驗存在性與非負 |
| 為湊顆數改既有測試、改 `tests/fakes.py` 的 `FakeRouter` 行為 | 既有假件「沒登記就丟例外」正是測試 3 要用的設計 |
| 起伺服器做計畫 §4.7 的「終端機實地看一眼」 | 埠 8000 有使用者留著的 uvicorn；真模型煙霧由主 agent 統一做 |
| `git add`／`git commit`、動 `docs/spec/`、建 Docker 檔 | 本增量全程不 commit；G1 閘門沒過不准建 Docker |

## 執行方式

以 subagent 實作（TDD 鐵序：先寫測試 → 確認紅 → 實作 → 跑綠），主 agent 事後 review。
