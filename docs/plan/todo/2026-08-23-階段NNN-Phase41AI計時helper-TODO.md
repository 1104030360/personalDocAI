# 階段NNN TODO：Phase 41 AI 計時 helper `services/ai_timing.py`（階段乙第 1 步）

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP）
> 依據：`docs/plan/unfinish/phase-41-AI計時helper.md`（逐條照做）＋`docs/design/design4.md` §5.1〜§5.3、§5.4 第 1／6 列、D7
> 開工基準（已實測）：`pytest -q` ＝ **365 passed ＋ 2 skipped**（Phase 38〜40 完成後的數字）
> 完工目標：**373 passed ＋ 2 skipped**（恰好 +8，本 phase 只新增測試、不動產品行為）

> **後續最終狀態：** 上述 365→373 是歷史 phase-local 紀錄。目前 targeted suite 為
> **112 passed、2 skipped、1 warning（9.42s）**，full suite 為
> **402 passed、2 skipped、1 warning（27.73s）**。唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。最新 hardening 會清理／截斷
> 動態 log 值，且真實 client 傳入 request 已選定的 immutable `AiTarget`；只有 helper／假件未傳
> target 的相容路徑才即時讀 config。狀態為
> **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty；
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

## 實作邏輯

階段乙第一步：做**工具本身**，不接任何呼叫點（接線是 Phase 42／43，別的 agent 做）。
所以本 phase 做完，產品行為**逐位元不變**——沒有任何既有程式碼會呼叫這個 helper。

現況的問題：五種會打 Ollama 的呼叫裡，只有「看圖」有秒數（寫死在
`app/api/routers/photos.py` 第 151〜170 行，`AI 看圖開始`／`AI 看圖完成（%.1f 秒）`），
另外四種（轉向量、判斷查法、產生回答、再建議一個）**成功時一行 log 都沒有**
（只有失敗才留 warning，例如 `ask_workflow.py` 的路由 fallback）。
本機看圖一張 2〜5 分鐘、雲端 2 秒，差兩個數量級卻只有其中一步看得到數字。

解法是把格式收成**一份共用工具**：`with log_ai(kind):` 一行包起來，
自動在前後各打一行、五個必要欄位（`kind`／`backend`／`model`／`elapsed_s`／`ok`）
順序固定，這樣才 grep 得出來（`grep "kind=embed"` 只看轉向量花多久）。

三個設計決定，各有理由：

1. **本 phase 初版的 backend／model 由 helper 從 `config` 推**，當時呼叫端只寫
   `with log_ai("vlm"):`。
   design4 §5.3 的示意是 `with log_ai("vlm", backend=..., model=...)`，`...` 是留給實作填的佔位；
   計畫 §4.2 的 📌 明文決定改由 helper 推。理由：kind→模型是**死的規則**，
   抄到八個呼叫點（Phase 42 三處＋Phase 43 五處）就是八份會各自走鐘的複製品。
   **這是歷史初版；最終真實 client 會傳 immutable target，避免事後切換開關造成 relabeling。**
2. **初版 fallback 的 `config.AI_BACKEND` 在函式裡即時讀**（不是
   `from app.core.config import AI_BACKEND`）。
   它是頁首那顆「本機｜雲端」開關撥動的**執行中狀態**，import 進來會定死成
   伺服器啟動當下的值——`config.py` 第 40 行的註解已經寫明這條規矩。
3. **`_目標(kind)` 算在 `logger.info("AI 開始 …")` 之前**（計畫 §7 陷阱 9）。
   kind 打錯時要在**一行 log 都沒打**的狀態下 `ValueError`；順序對調會留下一個
   永遠等不到結束行的孤兒開始行。測試 8 就是在抓這件事。

不吞例外是本 phase 最重要的一條（計畫 §7 陷阱 3 稱之為「最嚴重的可能錯誤」）：
`except BaseException` 只記一個旗標、然後**必須 `raise`**，結束行由 `finally` 打。

- 抓 `BaseException` 而不是 `Exception`：Ctrl+C（`KeyboardInterrupt`）與 uvicorn 關機
  丟的不是 `Exception` 的子類，用窄的那個會漏掉結束行。這裡不處理例外、只記旗標，
  所以抓最寬的那個最正確。
- 用 `finally` 而不是 `else`：`else` 只有沒例外時才跑，失敗就不會打結束行。

## 步驟（TDD 鐵序：先紅後綠）

- [x] 寫本 TODO。開工前確認基準 `pytest -q` ＝ 365 passed ＋ 2 skipped。
- [x] **先寫測試**：新建 `tests/unit/test_ai_timing_unit.py`，八顆照計畫 §4.3 的表**逐字命名**。
      共同規矩：
      ① 每顆開頭 `caplog.set_level(logging.INFO)`（helper 打的是 INFO，忘了設會看到空的
      `caplog.messages` 而百思不解——計畫 §7 陷阱 7）；
      ② 切後端一律 `monkeypatch.setattr(config, "AI_BACKEND", …)`，**「本機」那半邊也要明寫**
      `"local"`，不靠「預設值剛好是 local」（模組層可變狀態，別人撥過會互相絆倒）；
      ③ 秒數只准斷言 `>= 0`（正規表示式抓 `elapsed_s=([0-9.]+)` 轉 float），
      **不准寫死等於某個數字**（design4 §5.3 明文；假件飛快、真模型幾分鐘，寫死必壞）。
- [x] 跑 `pytest tests/unit/test_ai_timing_unit.py -v` **確認真的是紅的**。
      預期在**收集階段**就停：畫面是 **1 error**、不是 8 個 F，訊息為
      `ModuleNotFoundError: No module named 'app.services.ai_timing'`。留存證據。
- [x] **再寫實作**：新建 `app/services/ai_timing.py`，照計畫 §4.4 的骨架（含 docstring 與註解）：
      模組 docstring 說明「唯一一種格式」與「不吞例外」；`_目標(kind)` 回 `(backend, model)`；
      `AiCall` dataclass 只有 `note` 一個欄位；`log_ai(kind)` 是 `@contextmanager`。
      `logger = logging.getLogger(__name__)`（→ `app.services.ai_timing`，才在 `main.py`
      掛的那個 `app` handler 底下）、`time.monotonic()`、`%.1f`、`logger.info`。
- [x] 跑綠三連：
      ① `pytest tests/unit/test_ai_timing_unit.py -v` ＝ **8 passed**；
      ② `pytest -q` ＝ **373 passed ＋ 2 skipped**；
      ③ `OLLAMA_BASE_URL=http://localhost:9 pytest -q` **顆數相同**（零外部依賴實證）。
- [x] 計畫 §6 驗收清單逐項核對，含掃碼：檔內沒有 `print(`／`open(`／裸 `except: pass`；
      是 `config.AI_BACKEND` 不是 from-import；測試裡沒有秒數等值斷言；
      `git status --short -- app tests` 恰好只多兩行 `??`、**零 `M`**
      （Phase 38〜40 留下的 M／?? 不是本輪的，要確認的是本輪沒動任何既有檔案）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 八顆測試對照（計畫 §4.3 的表，名稱逐字）

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 1 | `test_成功時打出開始與結束兩行` | `caplog` 恰兩筆，一筆 `AI 開始 ` 開頭、一筆 `AI 結束 ` 開頭 |
| 2 | `test_結束行帶ok為true與非負秒數` | 含 `ok=true`；`elapsed_s=([0-9.]+)` 轉 float **≥ 0** |
| 3 | `test_例外會往外傳且結束行標ok為false` | `pytest.raises(RuntimeError)` 抓得到，且結束行含 `ok=false` |
| 4 | `test_embed的backend永遠是local就算開關撥到雲端` | 撥 cloud 仍 `backend=local`、`model=` 為 `EMBEDDING_MODEL` |
| 5 | `test_vlm跟著開關切換backend與model` | local→`VLM_MODEL`；cloud→`OLLAMA_CLOUD_VLM_MODEL`（兩邊明寫） |
| 6 | `test_三種文字用途都用LLM模型名` | route／answer／entity_suggest：local→`LLM_MODEL`、cloud→`OLLAMA_CLOUD_LLM_MODEL` |
| 7 | `test_備註接在結束行後面且五個欄位仍在` | 結束行 `.endswith("text 3 字")` 且五個欄位都還在 |
| 8 | `test_未知的kind直接炸掉且一行log都沒打` | `ValueError` 且 `caplog.messages` **是空的**（不准有孤兒開始行） |

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 接到任何真的呼叫點（photos／ask_workflow／retrieval／entity_suggestion） | 那是 Phase 42／43，別的 agent 做。本 phase 做完產品行為零改變 |
| 把秒數寫進資料庫、算平均／P95、做儀表板 | design4 只要「log 打得出來」，不要過度設計 |
| 用 `print()` 或自己開檔案寫 log | 全站用 `logging`；`app/main.py` 已把 `app.*` 的 INFO 接到終端機 |
| 把秒數寫死當測試斷言 | design4 §5.3 明文「不要把秒數寫死當驗收」 |
| 在 helper 裡吞例外、把失敗轉成回傳值 | §5.3 明文：例外往外傳（422／500 語意不變），helper 只打結束＋`ok=false` |
| 為 PDF 渲染、存檔、縮圖、SQL、WebRTC、QR、開關 GET／PUT 計時 | §5.1 明文：那些不是模型推論，不計時 |
| 新增第六種 kind、或讓 kind 可自由字串 | 五選一；未知 kind 當場 `ValueError` |
| 動 `docs/spec/`、既有測試、任何既有 `app/` 檔案 | 本 phase 恰好只新建兩個檔 |
| 建任何 Docker 檔 | 階段丙的東西，G1 閘門沒過不准建（design4 §0） |
| 起伺服器 | 埠 8000 有使用者留著的 uvicorn，不動、不自起；本 phase 純單元測試不需要 |
| `git add`／`git commit` | 本增量全程不 commit |

## 執行方式

以 subagent 實作，全程 TDD（**先紅後綠**，紅階段的 `ModuleNotFoundError` 要留存證據）。
驗收以「八顆先紅後綠 ＋ 全量恰好 +8 ＋ 指死埠同顆數 ＋ `git status` 零 `M`」為準。
