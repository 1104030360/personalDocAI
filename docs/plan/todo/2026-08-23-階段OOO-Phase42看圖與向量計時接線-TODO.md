# 階段OOO TODO：Phase 42 看圖與轉向量的計時接線

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP；計畫 §4.7 真模型終端機實驗已由主 agent 完成）
> 依據：`docs/plan/unfinish/phase-42-看圖與向量計時接線.md`（逐條照做）＋`docs/design/design4.md` §5.1〜§5.4、D7、§9 第 5 列
> 開工基準（已實測）：`pytest -q` ＝ 373 passed ＋ 2 skipped

> **後續最終狀態：** 上述 373＋2 是歷史 phase-local 基準；目前 targeted suite 為
> **112 passed、2 skipped、1 warning（9.42s）**，full suite 為
> **402 passed、2 skipped、1 warning（27.73s）**。唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> 真模型串行自驗全部 `ok=true`：最新本機 PNG 重跑為 `vlm 33.1s`／`embed 2.4s`；兩頁 PDF
> 第 1 頁 `29.2s/0.1s`、第 2 頁 `26.1s/0.1s`；歸檔只有 `embed 0.1s`；
> 雲端 PNG `vlm gemma4 7.1s`／本機 `embed 0.4s`。
> 最新 hardening 改由真實 VLM／embedding client 傳 request 已選定的 immutable target，
> 並讓看圖 note 只記數量與布林摘要，不記 AI 產生內容；假件無 target 時才走 config fallback。
> 狀態為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

## 實作邏輯

增量四階段乙的第 2 步：把 Phase 41 做好的 `ai_timing.log_ai()` **接到上傳這條路**上。

三個入口（桌面單圖、桌面 PDF 逐頁、無線鏡頭快門）全部走同一個函式
`photos._ingest_image()`，所以看圖與轉向量各在那裡包一次，三條路就都有了；
`camera.py` 一個字都不用改。歸類（`PATCH /photos/{id}/folder`）重算向量是另一個
呼叫點，要各別包一次（design4 §5.3 的前兩個 bullet）。

三個關鍵設計點：

- **「看不懂 → 422」的 `raise` 寫在 `with` 區塊裡面**。那一頁對這次呼叫來說就是失敗，
  結束行要標 `ok=false`（design4 §5.2 的 PDF 規則）。`log_ai` 不吞例外，
  422 原封不動往外飛，`_ingest_pdf` 照樣接得住、照樣記進 `skipped_pages`——語意一字未變。
- **舊的三行 `logger.info("AI 看圖開始／完成…")` 全部收掉**。design4 §5.2 明文
  「不要舊新兩套並行」：兩種格式會讓 grep 出來的結果自相矛盾。
  舊格式帶的 `content_type` 與 bytes 數沒有了，摘要改帶「字數／建議類別／建議實體／待辦」。
- **只包真的打模型的那幾行**。存原圖、產縮圖、寫 SQL、PDF 渲染都不計時
  （design4 §5.1 明文：不是模型推論）；也不為 PDF 打「整份總時間」（§1.2 已否決）。

`import time` 隨舊 log 一起刪掉——計時改由 helper 內部的 `time.monotonic()` 負責，
router 自己不再需要那個模組。

## 步驟（TDD：先紅再綠）

- [x] **紅**：新建 `tests/integration/test_ai_timing_log.py`，照計畫 §4.3 的表寫六顆
      （名稱逐字照抄）。共通做法：每顆第一行 `caplog.set_level(logging.INFO)`；
      `開始行()`／`結束行()` 兩個小工具**連開頭一起比對**（開始行與結束行都含
      `kind=vlm `，只用 kind 過濾會撈到兩種）；預期成功的上傳一律用真圖／真 PDF；
      「一頁看得懂一頁看不懂」在本檔自己定義一份 `分頁VLM`（不跨檔 import）；
      測試 5「先上傳再 PATCH」中間要 `caplog.clear()`；測試 6 用
      `monkeypatch.setattr(config, "AI_BACKEND", "cloud")` 撥開關。
- [x] 跑 `pytest tests/integration/test_ai_timing_log.py -v` 確認**六顆全紅**，輸出留存給 REP。
- [x] **綠**：`app/api/routers/photos.py` 的 `_ingest_image()` 看圖那一段換成
      `with ai_timing.log_ai("vlm") as 計時:`（422 的 raise 在區塊內、兩個 `計時.note`
      都在區塊內、舊三行 `logger.info` 收掉）。
- [x] **綠**：兩處 `embed_document(...)`（`_ingest_image` 與 `assign_folder`）各包一層
      `with ai_timing.log_ai("embed"):`。
- [x] **綠**：import 區把 `ai_timing` 按字母序加進 `from app.services import ...`；
      先 grep 確認沒人用 `time.monotonic`／`time.time(` 之後刪掉第 4 行 `import time`。
- [x] 跑綠四連：新檔 6 passed → `pytest -q` ＝ **379 passed ＋ 2 skipped** →
      `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同 →
      計畫 §4.6 點名的既有錯誤路徑測試檔逐一跑過。
- [x] 計畫 §6 驗收清單逐項核對（`grep -rn "AI 看圖開始\|AI 看圖完成" app/` 無輸出、
      `grep -n "^import time" app/api/routers/photos.py` 無輸出、只動到兩個檔）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 舊的「AI 看圖開始／完成（N.N 秒）」留著並行 | design4 §5.2 明文：「不要舊新兩套並行」 |
| 改任何 HTTP 狀態碼或錯誤訊息 | §9 第 5 列：語意不變。看不懂還是 422、存檔失敗還是 500 |
| 為 PDF 打一筆「整份總時間」 | design4 §1.2 明文否決：要每頁各一組才看得出哪一頁慢 |
| 為 PDF 渲染／存原圖／產縮圖／寫 SQL 計時 | §5.1 明文：不是模型推論，不計時 |
| 把計時包進 `indexing_service.embed_document()` 或 `vlm_service.OllamaVLM` 裡 | §5.3 指定包在**呼叫點**；包進類別裡 pytest 的假件就不會打 log |
| 動 `app/api/routers/camera.py` | 它是轉呼叫 `photos._ingest_image()`，自動涵蓋 |
| 測試斷言 `elapsed_s` 等於某個數字 | design4 §5.3 明文：只驗存在性與非負 |
| 為湊顆數改既有測試 | 既有測試守的是「語意不變」，不准動 |
| 起伺服器做計畫 §4.7 的「終端機實地看一眼」 | 埠 8000 有使用者留著的 uvicorn，不要動；真模型煙霧由主 agent 統一做 |
| `git add`／`git commit`、動 `docs/spec/`、建 Docker 檔 | 本增量全程不 commit；階段丙的東西 G1 沒過不准建 |

## 執行方式

以 subagent 實作（TDD 鐵序：先寫測試 → 確認紅 → 實作 → 跑綠），主 agent 事後 review。
