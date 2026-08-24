# 階段OOO REP：Phase 42 看圖與轉向量的計時接線

> 日期：2026-08-23　狀態：✅ 程式、自動化測試與主 agent 真模型自查完成；**G1 人工確認待辦**
> 對應 TODO：`2026-08-23-階段OOO-Phase42看圖與向量計時接線-TODO.md`
> 計畫：`docs/plan/unfinish/phase-42-看圖與向量計時接線.md`；design：`design4.md` §5.1〜§5.4、D7、§9 第 5 列
> 開工基準（實測）：373 passed ＋ 2 skipped → 收工：**379 passed ＋ 2 skipped**（+6，恰為本 phase 新增）

## 實作邏輯

階段乙第 2 步：把 Phase 41 的 `ai_timing.log_ai()` 接到**上傳這條路**。

三個入口（桌面單圖、桌面 PDF 逐頁、無線鏡頭快門）都收斂到同一個函式
`photos._ingest_image()`，所以看圖與轉向量各在那裡包一次，三條路就全涵蓋了——
`camera.py` 一個字都沒動（它第 297 行就是轉呼叫 `_ingest_image`）。
歸類（`PATCH /photos/{id}/folder`）重算向量是另一個呼叫點，各別包一次。

三個關鍵設計點，全部照計畫落地：

1. **「看不懂 → 422」的 `raise` 寫在 `with` 區塊裡面**（計畫 §4.2 的唯一設計判斷）。
   那一頁對這次呼叫來說就是失敗，結束行要標 `ok=false`（design4 §5.2 的 PDF 規則）。
   `log_ai` 不吞例外，`HTTPException` 原封不動穿過 `with` 往外飛 →
   `_ingest_pdf` 照樣接得住、照樣記進 `skipped_pages`，422 語意一個字未變。
   兩個 `計時.note`（看不懂那條、看得懂那條）都設在區塊**內**且都在 `raise` **之前**，
   寫到外面／後面就永遠不會執行。
2. **舊三行 `logger.info("AI 看圖開始／完成…")` 全部收掉**——design4 §5.2 明文
   「不要舊新兩套並行」。舊格式帶的 `content_type` 與 bytes 數沒有了，
   摘要改帶「字數／建議類別／建議實體／待辦」（§5.2 指定的必要欄位是那五個，
   摘要留給人看的部分）。
3. **只包真的打模型的那幾行**。PDF 渲染、存原圖、產縮圖、寫 SQL 一律不計時；
   `_ingest_pdf` 也**不另外包一層**（那會變成 design4 §1.2 已否決的「整份總時間」）。

`import time` 隨舊 log 一起刪掉——計時改由 helper 內部的 `time.monotonic()` 負責。
刪之前先 grep 確認 `time.monotonic`／`time.time(` 只出現在被刪掉的那兩行。

## 步驟（TDD 鐵序）

1. 寫 TODO。
2. 新建 `tests/integration/test_ai_timing_log.py`，六顆（名稱逐字照計畫 §4.3 的表）。
3. **跑紅**（證據見下）→ 六顆全紅，無一顆意外變綠。
4. `app/api/routers/photos.py` 的 `_ingest_image()` 看圖那段換成 `with ai_timing.log_ai("vlm") as 計時:`。
5. 兩處 `embed_document(...)`（`_ingest_image` 第 205 行、`assign_folder` 第 472 行）
   各包一層 `with ai_timing.log_ai("embed"):`。
6. import 區把 `ai_timing` 按字母序加進 `from app.services import (...)`（超過一行改成括號多行式）；
   刪掉第 5 行 `import time`。
7. 跑綠四連 → 驗收清單逐項核對。

## 測試方式

六顆整合測試，走 `TestClient` 打真端點、連測試庫 `PersonalDocAI_test`
（conftest 三道 autouse 安全網照舊：`reset_tables`／`wire_fake_ai`／`isolated_data_dir`，
所以**完全不打真 Ollama、不寫專案 `data/`、不動正式庫**）。

| # | 測試 | 驗什麼 |
|---|---|---|
| 1 | `test_上傳一張圖各打一組看圖與轉向量的log` | `kind=vlm` 開始／結束各 1 行、`kind=embed` 開始／結束各 1 行、兩個結束行 `ok=true` |
| 2 | `test_看不懂的照片看圖log標ok為false且不打embed` | 422；`kind=vlm` 結束行 `ok=false`；**完全沒有** `kind=embed` 的行 |
| 3 | `test_PDF兩頁各打兩組` | `kind=vlm` 開始行 2 條、`kind=embed` 開始行 2 條（D7：每頁各一組，不是整份一組） |
| 4 | `test_PDF跳過的那一頁不打embed` | `分頁VLM(看得懂的頁碼={1})` → `vlm` 結束行 2 條（`ok=true`＋`ok=false`）、`embed` 只有 1 條；`skipped_pages == [2]` |
| 5 | `test_歸類重算向量會打embed的log` | 上傳 →（`caplog.clear()`）→ PATCH 歸「收據」→ `embed` 開始／結束各 1 行、`ok=true`、**沒有** `vlm`（歸類不重看圖） |
| 6 | `test_切到雲端時看圖是cloud而轉向量仍是local` | `AI_BACKEND="cloud"` → `vlm` 兩行是 `backend=cloud model={OLLAMA_CLOUD_VLM_MODEL}`；`embed` 兩行仍 `backend=local model={EMBEDDING_MODEL}` |

三條刻意的規矩（計畫 §7 的陷阱清單）：

- **秒數一律不驗數字**，只看 `ok=` 真假與行數（design4 §5.3 明文；假件跑得飛快，秒數是 0.0）。
- `開始行()`／`結束行()` 兩個小工具**連開頭一起比對**（`f"AI 開始 kind={kind} "`）——
  開始行與結束行都含 `kind=vlm `，只用 `kind=` 過濾會一次撈到兩種、數量全部翻倍。
- 測試 5 中間 `caplog.clear()`——`caplog` 是整顆測試累積的，不清掉 `kind=embed` 會撈到 2 組。

「預期成功」的上傳一律用真圖／真 PDF（`make_png_bytes()`／`make_pdf_bytes(pages=2)`，
Phase 19 起的專案慣例）；只有測試 2「看不懂 → 422」沿用假位元組 `b"\x89PNG"`，
順便證明那條路根本不解碼圖片。`分頁VLM` 照計畫在本檔自己定義一份，不跨檔 import。

## 遇到的問題與解法

| 問題 | 解法 |
|---|---|
| 測試 6 若只用 `for 行 in 看圖: assert ...`，撈不到任何行時迴圈是空的＝**假綠** | 先 `assert len(看圖) == 2`／`len(轉向量) == 2` 再進迴圈；跑紅時這顆確實是死在長度斷言上（見紅色證據） |
| `from app.services import ...` 加了 `ai_timing` 之後超過 79 字元 | 改成括號多行式並維持字母序（`ai_timing, indexing_service, pdf_service, storage_service, vlm_service`） |
| 新測試檔兩行超過 79 字元（本專案 tests/ 慣例守 79） | `_上傳PDF` 先把 bytes 存成區域變數、PATCH 那行拆兩行；重跑 lint 已零錯誤 |
| 驗收清單的 `grep -rn "AI 看圖開始\|AI 看圖完成" app/` **不是**完全無輸出 | 唯一命中是 `app/main.py:15` 的**註解**（「『AI 看圖開始／完成』這類追蹤訊息是 INFO」），不是 log 呼叫。計畫 §6 已明文「`app/main.py` 的註解…都不是舊 log、不用動」，且本次授權動的檔案不含 `main.py`，故保留。改用更精準的 `grep -rn 'logger.info("AI 看圖' app/` 驗證：**無輸出**＝舊格式的 log 呼叫已完全移除，沒有兩套並行 |

## 測試結果

**紅（實作前）**——`pytest tests/integration/test_ai_timing_log.py -v`：

```text
FAILED tests/integration/test_ai_timing_log.py::test_上傳一張圖各打一組看圖與轉向量的log
FAILED tests/integration/test_ai_timing_log.py::test_看不懂的照片看圖log標ok為false且不打embed
FAILED tests/integration/test_ai_timing_log.py::test_PDF兩頁各打兩組
FAILED tests/integration/test_ai_timing_log.py::test_PDF跳過的那一頁不打embed
FAILED tests/integration/test_ai_timing_log.py::test_歸類重算向量會打embed的log
FAILED tests/integration/test_ai_timing_log.py::test_切到雲端時看圖是cloud而轉向量仍是local
========================= 6 failed, 1 warning in 0.86s =========================
```

失敗訊息實證舊格式還在（撈不到任何 `kind=` 的行）：

```text
AssertionError: ['AI 看圖開始：image/png，113 bytes',
                 'AI 看圖完成（0.0 秒）：text 34 字、建議類別「收據」、建議實體「None」、待辦「None」', …]
assert 0 == 2
```

**綠（實作後）**：

| 指令 | 結果 |
|---|---|
| `pytest tests/integration/test_ai_timing_log.py -v` | **6 passed** |
| `pytest -q` | **379 passed ＋ 2 skipped**（＝ 373 ＋ 6，與計畫預期一致） |
| `OLLAMA_BASE_URL=http://localhost:9 pytest -q` | **379 passed ＋ 2 skipped**（顆數相同＝零外部依賴實證） |
| `pytest test_pdf_upload.py test_error_paths.py test_photo_files.py test_assign_folder.py test_folder_error_paths.py test_design3_error_paths.py -q` | **66 passed**（六個守「語意不變」的既有檔全綠、一字未改） |

**驗收掃碼**：

| 檢查 | 結果 |
|---|---|
| `grep -rn 'logger.info("AI 看圖' app/` | 無輸出（舊 log 呼叫已移除） |
| `grep -rn "AI 看圖開始\|AI 看圖完成" app/` | 僅 `app/main.py:15` 註解一筆（計畫明文不用動，理由見上表） |
| `grep -n "^import time" app/api/routers/photos.py` | 無輸出（已刪） |
| `grep -rn 'ai_timing\.log_ai("' app/` | 3 處，全在 `photos.py`：`vlm`（161）、`embed`（205，上傳）、`embed`（472，歸類） |
| 動到的檔 | `app/api/routers/photos.py`（改）＋ `tests/integration/test_ai_timing_log.py`（新建）。其餘 `git status` 上的 M／?? 皆為 Phase 38〜41 既有未 commit 的變更，本 phase 未觸碰 |

**未做（依主 agent 指示）**：計畫 §4.7 的終端機四條實地看一眼（本機／雲端／PDF／歸類）——
埠 8000 有使用者留著的 uvicorn，真模型煙霧由主 agent 之後統一做。

## 最終真模型補記（2026-08-24，取代上段「尚未實地看」的暫時狀態）

主 agent 已以 serial localhost runtime 完成 Phase 42 真模型自查；下列均看到對應結束行
`ok=true`，秒數是該次實跑觀察，不是效能承諾：

| 路徑 | VLM | Embed | 結果 |
|---|---:|---:|---|
| 本機單圖上傳 | `gemma4:e2b` 35.1s | `bge-m3` 2.2s | 上傳成功；本機看圖＋本機向量各一組 |
| 本機兩頁 PDF 第 1 頁 | 29.2s | 0.1s | 每頁各自計時 |
| 本機兩頁 PDF 第 2 頁 | 26.1s | 0.1s | 每頁各自計時 |
| 資料夾歸類重算 | 無 VLM | `bge-m3` 0.1s | 只有 embed，沒有重看圖 |
| 雲端單圖上傳 | cloud `gemma4` 7.1s | local `bge-m3` 0.4s | VLM 切雲端，向量仍留本機 |

最終掃碼仍是 `ai_timing.log_ai(...)` **恰 8 個呼叫點**；full suite 為
**402 passed, 2 skipped, 1 warning in 27.73s**，指死 Ollama 埠後仍是同顆數
（26.47s）。唯一 warning 是 `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
最新 hardening 讓真實 VLM／embedding client 傳入 request 已選定的 immutable target，避免
開關切換後 relabel；看圖 note 只記數量與布林摘要，不記 AI 產生內容。這是主 agent 的技術
自證；產品負責人仍須親自看 G1 包 C 段並明示核准。

狀態：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty；
沒有 commit、release、Docker／Compose 或 Phase 45 工作。
