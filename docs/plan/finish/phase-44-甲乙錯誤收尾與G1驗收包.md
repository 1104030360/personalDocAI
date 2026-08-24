# Phase 44：階段甲乙錯誤收尾、全量回歸與 G1 驗收包

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 技術收尾與實作者自驗已完成。**
> 下方 `384 → 387` 是 Phase 44 當時的歷史收尾基線，特意保留；
> 目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，spec binder 為
> **25 passed、2 skipped、1 warning（2.19s）**，全量為
> **402 passed、2 skipped、1 warning（27.73s）**，dead-Ollama 同顆數（26.47s）。
> 唯一 warning 是 `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> OpenAPI **20**、DELETE **0**、沒有 `GET /photos` 列出全部照片；
> `compileall`、Node 語法檢查、diff check 均綠，生產呼叫點恰 **8** 處，
> `docs/spec/` 乾淨，且專案沒有 Docker／Compose 檔案。
> 瀏覽器技術自驗共 **25 張 JPEG**（11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`）；
> 最新兩位獨立 reviewer `final_visual_qa_k`、`final_visual_qa_l` 均為
> **PASS／HIGH confidence／25 of 25／zero blockers**。focus trap／背景 `inert`／Tab 與 Shift+Tab／
> focus restore、stale generation、structured-output failure truth、log 安全與隱私、immutable target、
> 遺失圖片／raw error／長 CJK 均已有最新 hardening 證據。
> 產品負責人 G1 B／C／D／E 仍保留空白；狀態固定為
> **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty，未 commit、
> 未 release、未做 Phase 45、未建 Docker／Compose。
> Phase 38〜44／G1 全程只需 localhost，不需要手機、掃 QR 或熱點；Phase 36 真機驗收是另一件事。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 把 design4 §9 錯誤表的第 1〜5 列逐列確認「有測試釘著」，
> 補上還沒人測的兩三顆，跑完整套回歸，最後**整理出一張給產品負責人的 G1 檢查表**——
> 他照著點一遍、看一遍 log，說出那句「甲乙沒問題，可以做 Docker」，階段丙才准開始。

> **這個 phase 的產出有兩種**：一種是程式碼（少少幾顆測試），
> 另一種是**文件**（§6 那張 G1 檢查表）。後者才是重點——
> 沒有它，產品負責人不知道要看什麼，G1 就變成「感覺可以了」。

---

## 1. 對應 design4.md 章節

- **§6**（階段甲＋乙的測試與前端驗收：自動化／瀏覽器／終端機三份清單）
- **§7**（閘門 G1 的六個條件）
- **§9**（錯誤表第 1〜5 列；第 6 列屬階段丙的 G2，見 phase-46）
- **§3**（範圍的「不做」清單——本 phase 逐項掃一次，確認沒有手滑做進去）
- **§1.2**（被否決方案——同上）

---

## 2. 前置條件

- **Phase 38〜43 全部完成且全綠**（`pytest -q` ＝ 384 passed ＋ 2 skipped）。
- 這是 ★G1 之前的最後一個 phase。做完之後**停下來等人**，不要往 Phase 45 走。
- 本檔所有指令都在**專案根目錄**執行（`ls`／`grep`／`git` 用的都是相對路徑，
  位置跑掉就會查到別的東西、甚至誤判成「通過」）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q      # 先確認基準沒跑掉：384 passed ＋ 2 skipped
```

---

## 3. 範圍

### 做

- 新建 `tests/integration/test_design4_error_paths.py`（三顆，鏡射
  `tests/integration/test_design3_error_paths.py` 的收尾模式）。
- 跑完整套回歸（全量、零 Ollama、端點清點、規格檔）。
- 用掃碼確認 design4 §3／§1.2 的「不做」清單一項都沒手滑。
- **整理出 §6 的 G1 檢查表，交給產品負責人。**

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 自己把 G1 勾掉 | design4 §7 明文：「實作者不得自行把 G1 勾過」。這是人的動作 |
| 建 `compose.yaml`／`Dockerfile`／`.dockerignore`／`compose.dev.yaml` | design4 §0 明文：階段丙的檔案也算階段丙，G1 沒過連「先寫好放著」都不行 |
| 跑 `pg_dump`、停 brew、改 `.env` 的連線字串 | 同上 |
| 為了讓某顆測試變綠而改產品行為 | 這個 phase 是**收尾**，不是重寫。發現真缺陷 → 回對應的 phase 修，然後重跑全量 |
| 重複測已經有人測的東西 | 錯誤表每一列先找「誰已經測了」，只補真正的缺口（Phase 37 的作法） |

---

## 4. 實作步驟

### 4.1 錯誤表逐列盤點（先做這件事，再決定要補幾顆）

design4 §9 的六列，逐列查「誰已經測了」。查法：直接翻測試檔或用 `pytest -k` 撈。

| # | 情境 | 預期 | 已測 ✓／缺口 ★ | 在哪 |
|---|---|---|---|---|
| 1 | `GET /photos/{id}` 沒這列 | 404 | ✓ | `test_photo_detail.py::test_照片不存在回404`（Phase 38） |
| 1b | 同上，**不寫檔、不打 AI** | 沒有任何 `kind=` log、`DATA_DIR` 是空的 | ★ **本 phase 補** | 新檔第 1 顆 |
| 2 | 有列、路徑 NULL | 200，`image_url`／`thumbnail_url` 都是 null | ✓ | `test_photo_detail.py::test_舊照片沒有原圖時image_url為null`（Phase 38） |
| 3 | 有列、路徑有值但磁碟檔沒了 | JSON 仍 200 | ✓ | `test_photo_detail.py::test_原圖被刪掉詳情仍回200`（Phase 38） |
| 3b | 同上，前端 `<img>` 失敗 → 窗內占位 | 不是整窗 404 | ✓（瀏覽器） | Phase 39 §4.5 的「檔案被刪掉的降級」那一項；本 phase 的 G1 表再走一次 |
| 4 | 待辦列點下去、詳情 404 | 窗開著、紅字 | ✓（瀏覽器） | Phase 40 §4.5 **倒數第二項**（Console 直接呼叫 99999；最後一項是「Console 乾淨」）；本 phase 的 G1 表再走一次 |
| 5a | 看圖失敗 | 422 語意不變＋`kind=vlm ok=false` | ✓ | `test_ai_timing_log.py::test_看不懂的照片看圖log標ok為false且不打embed`（Phase 42）＋既有 `test_error_paths.py::test_vlm看不懂回422且不寫入` |
| 5b | 歸類重算向量失敗 | 500 不吞錯、資料庫零變動＋`kind=embed ok=false` | ✓ | 既有 `test_folder_error_paths.py::test_PATCH時embedding失敗回500且照片完全沒被改動`／`::test_PATCH自建時embedding失敗回500且不留空資料夾`（500／零變動）＋Phase 42 的 `embed` 計時；**執行時順手確認那幾顆仍綠** |
| 5c | 路由失敗 | fallback vector＋`kind=route ok=false` | ✓ | `test_ai_timing_log.py::test_路由失敗時route標ok為false且仍走語意查詢`（Phase 43） |
| 5d | 實體建議失敗 | 回 null 不 500＋`kind=entity_suggest ok=false` | ✓ | `test_entity_suggestion_unit.py::test_雲端實體建議的log是cloud且失敗標ok為false`（Phase 43 第 5 顆）＋既有 `test_design3_error_paths.py::test_再建議時模型爆炸只回None並留下警告` |
| 6 | Docker G2 對不上快照 | 停在 5434，brew 繼續服務 | — | **屬階段丙**，見 `phase-46` |

- [x] 逐列打勾。若發現某一列其實**沒有**測試（與上表不符），就在新檔補一顆，
      並把上表改成事實——**不要**為了讓表好看而假裝有測。

### 4.2 寫新測試（收尾 phase：首跑就該是綠的）

> ⚠️ **這裡的 TDD 節奏跟 38〜43 不一樣，別被嚇到。**
> 前面幾個 phase 是「先寫紅的測試 → 再寫產品碼 → 變綠」；本 phase 是**收尾**——
> 三顆測試釘的都是「38〜43 已經做出來的行為」，所以**首跑就應該全綠**。
> 首跑有紅的 ＝ 真的揪到缺陷（Phase 37 就是這樣抓出「自創實體＋釘選不是同一個交易」那個 bug），
> 那要回對應的 phase 修**產品程式碼**，不是改測試的斷言（§3「明確不做」第 4 列）。
>
> 但「綠的」不等於「有測到」：三顆裡有兩顆是**斷言某個東西不存在**（沒有 log、沒有 `PATCH`），
> 這種測試天生容易**假綠**（例如 `caplog` 忘了設等級，永遠撈到空的，斷言當然過）。
> 所以每顆寫完都做一次 30 秒的**反向驗證**：把斷言暫時反過來（`not in` 改成 `in`）跑一次，
> 確認它會紅，再改回來。紅得出來，才證明它真的在看東西——這就是收尾 phase 版本的「先紅後綠」。

- [x] 新建 `tests/integration/test_design4_error_paths.py`，檔頭寫一段導言
      （鏡射 `test_design3_error_paths.py` 的寫法：把錯誤表貼上來、標註本檔負責哪幾列）。

| # | 測試名稱 | 驗什麼 | 對應 |
|---|---|---|---|
| 1 | `test_詳情端點不打AI也不寫檔` | `caplog.set_level(logging.INFO)` 之後打 `GET /photos/999` → 404，而且 `"AI 開始" not in caplog.text`、`DATA_DIR` 底下**一個檔案都沒有**（⚠️ 那個暫存目錄在沒人寫過時**根本不會被建出來**，直接 `iterdir()` 會炸 `FileNotFoundError`——照抄 `tests/integration/test_design3_error_paths.py` 第 84 行的 `data_dir底下的檔案()`，它已經先判 `if not config.DATA_DIR.exists(): return []`） | §9 第 1 列的後半 |
| 2 | `test_原始碼裡沒有列出全部照片的路由` | 掃 `app/api/routers/` 底下每個 `.py` 的原始碼，斷言**沒有任何** `@router.get("/photos")`（＝列出全部）。用 `re.search(r'@router\.get\(\s*"/photos"', 原始碼)` 撈：`\s*` 是為了連「裝飾器換行寫」那種也抓得到（`photos.py` 第 73 行的 `@router.post(` 就是換行寫的）；`"/photos"` 的**結尾引號**則自然排除掉 `"/photos/{photo_id}"`，不會誤中詳情端點 | §3「不做」＋§4.4 末句＋D5 |
| 3 | `test_詳情彈窗是唯讀的` | 讀 `app/static/photo_detail_modal.js` 的原始碼，斷言裡面**沒有** `PATCH`、`POST`、`DELETE`、`/folder`——這顆從**原始碼**證明 D2，不必靠人記得 | D2、§1.2 第 1／2 列 |

> **測試 2 為什麼不算「重複測」**（§3 明確禁止重複，這裡先講清楚）：
> 「沒有列出全部照片」這條規則的**對外介面**那一面，Phase 38 的
> `test_openapi有依id讀一張照片的端點且沒有列出全部` 與 `test_ask_three_paths.py::test_端點數不變`
> 已經守住了（所以**不要**在本檔再斷言一次 openapi 或「總數 20」）。
> 測試 2 守的是另一面：**原始碼**裡沒有人掛上這條路由。
> 這就是 Phase 37 對「不做刪除」用的同一手法——一顆掃原始碼（`test_沒有任何刪除端點`）、
> 一顆掃 openapi（`test_openapi裡沒有任何DELETE動詞`），兩顆守同一條規則的兩面。

> 測試 3 的寫法可以照 `test_design3_error_paths.py::test_SQL只出現在repository與db層`：
> 用 `pathlib.Path` 讀檔、`assert "PATCH" not in 內容`。
> 檔案路徑用 `Path(__file__).resolve().parents[2] / "app/static/photo_detail_modal.js"`
> （`parents[2]` ＝ 從 `tests/integration/xxx.py` 往上三層到專案根目錄；
> 該檔第 52 行的 `專案根目錄` 就是同一個寫法，照抄即可）。
> 用 `read_text()` 直接讀、**不要**先 `if 檔案.exists()` 再跳過——路徑打錯時要當場炸
> `FileNotFoundError`，不能默默變成綠的。

- [x] 跑：

```bash
pytest tests/integration/test_design4_error_paths.py -v      # 預期 3 passed（首跑就綠）
```

  紅了先問兩件事：① 是不是我寫錯了？② 還是 38〜43 真的有缺陷？
  綠了也要照上面那段做一次**反向驗證**，確認不是假綠。

### 4.3 全量回歸

- [x] 全量：

```bash
pytest -q
```

  歷史 Phase 44 收尾預期：**387 passed ＋ 2 skipped**（384 ＋ 本 phase 的 3 顆）。
  **2 skipped 必須還是 2**——那是 `自然語言詢問.feature` 的兩條 `@未實作` Rule。
  它們的摘標排在增量四**最後**的 Phase 51（產品負責人 2026-08-23 核准），
  **本 phase 以及整個階段丙都不碰**：design4 §7 的 G1 驗收與 §8.9 的丙驗收都明文要求
  「既有 2 skipped 仍 skip」，提早摘會讓那兩道驗收對不上。

- [x] 零外部依賴實證（顆數必須完全相同）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

- [x] 規格檔 binder 單獨再跑一次（確認 `.feature` 沒被本增量波及）：

```bash
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
       tests/integration/test_camera_feature.py -v
```

  預期：既有 Rule 全綠、兩條 `@未實作` 仍 skip。

- [x] 確認規格檔真的一個字都沒改：

```bash
git status docs/spec/
```

  預期：**乾淨的**（design4 §3「規格 `.feature` 本輪不改」）。

### 4.4 「不做」清單掃碼

「**掃碼**」＝用指令（`grep`／`git`／測試）掃**原始碼**，不是掃 QR code。
逐項用指令證明，不要用眼睛掃。（本增量全程不 commit，所以 38〜43 的改動都還在
工作區裡，`git diff` 看得到；下面兩條「應該沒被動到」的檔案就是靠這個判斷。）

- [x] **沒有列出全部照片的端點**：openapi 那一面由 Phase 38 的
      `test_photo_detail.py::test_openapi有依id讀一張照片的端點且沒有列出全部` ＋
      `test_ask_three_paths.py::test_端點數不變`（總數 20）守著；原始碼那一面由
      §4.2 的測試 2 守著 ✓
- [x] **沒有刪除端點**：既有 `test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞` ✓
- [x] **清單契約沒被改**：

```bash
git diff --stat app/schemas/folder.py app/schemas/task.py \
                app/api/routers/folders.py app/api/routers/tasks.py
```

  預期：**沒有任何變更**（`GET /folders/{id}` 的五鍵摘要、`GET /tasks` 的瘦契約都沒動）。

- [x] **待決定分頁與三關彈窗鏈沒被改**：

```bash
git diff --stat app/static/folder_modal.js app/static/entity_modal.js \
                app/static/task_modal.js app/static/classify_chain.js
```

  預期：**沒有任何變更**。

- [x] **舊的看圖 log 沒有殘留**：

```bash
grep -rn "AI 看圖開始\|AI 看圖完成" app/
```

  預期：**沒有輸出**（design4 §5.2「不要舊新兩套並行」；Phase 42 已把這兩行換成新格式）。

  ⚠️ **不要**只搜「AI 看圖」三個字，那樣一定會有輸出、看起來像 Phase 42 沒做完：
  `app/main.py` 的註解、`app/services/vlm_service.py` 的檔頭、`app/api/routers/camera.py`
  第 291 行的「（AI 看圖見下一行）」、`upload.html` 與 `camera-desk.html` 的等待字樣
  都含這三個字——**它們都不是舊 log，一個字都不要動**（phase-42 §6 已標過同一件事）。

- [x] **SQL 只在 repository**：既有 `test_design3_error_paths.py::test_SQL只出現在repository與db層` ✓
- [x] **沒有任何階段丙的檔案**：

```bash
ls compose.yaml compose.dev.yaml Dockerfile .dockerignore db/docker-init 2>&1
```

  預期：**全部 No such file or directory**（design4 §0：G1 沒過不准建）。

### 4.5 產出 G1 驗收包

- [x] 把下面 §6 那張表複製一份，填上你這次跑出來的實際數字與環境
      （模型名稱、伺服器網址），交給產品負責人。
- [ ] 陪他走一遍（或請他自己走）；他提出的每一個問題都記下來。
- [x] **停在這裡。** 不要因為「看起來都沒問題」就開始做 Phase 45。

---

## 5. ASCII 圖：G1 之前與之後

```text
   Phase 38 ─┐
   Phase 39 ─┼─ 階段甲：詳情端點＋唯讀彈窗＋兩個入口
   Phase 40 ─┘
                        │
   Phase 41 ─┐          │
   Phase 42 ─┼─ 階段乙：五種 kind 的計時 log
   Phase 43 ─┘          │
                        ▼
                ┌───────────────────┐
                │   Phase 44（本檔）│
                │  ・錯誤表逐列盤點 │
                │  ・補 3 顆測試    │
                │  ・全量回歸       │
                │  ・掃「不做」清單 │
                │  ・產出 G1 檢查表 │
                └────────┬──────────┘
                         │ 交出檢查表
                         ▼
        ┌───────────────────────────────────────────┐
        │  ★★★  閘門 G1（人）                       │
        │  產品負責人親自：                         │
        │    ① 點 3 個入口（資料夾／待辦／待決定）  │
        │    ② 看 4 段終端機 log                    │
        │    ③ 說出「甲乙沒問題，可以做 Docker」    │
        └────────────────┬──────────────────────────┘
                         │
              沒說 ──────┴────── 說了
                │                  │
                ▼                  ▼
      回 39/40/42/43 修        Phase 45 開工
      改完重跑本 phase        （階段丙第一步）
```

---

## 6. G1 驗收包（複製這一段交給產品負責人）

> **給產品負責人：** 下面是「照片詳情」與「AI 計時 log」兩件事的驗收清單。
> 全部看過、沒問題的話，請明確說一句「**甲乙沒問題，可以做 Docker**」——
> 有這句話，實作者才會開始動資料庫搬家那件事（那件事有風險，所以要你點頭）。

**準備：** 伺服器已經跑起來（`uvicorn app.main:app --reload --port 8000`），
另一個視窗看著跑 uvicorn 的那個終端機（C 段要看的 log 就印在那裡）。
B 段用瀏覽頁 `http://localhost:8000/ui/browse.html`；
C 段用上傳頁 `http://localhost:8000/ui/upload.html`（「AI 模型：本機｜雲端」那顆開關在它的頁首）。

### A. 自動化（實作者已跑，請看數字）

- [x] `pytest -q` ＝ **402 passed ＋ 2 skipped ＋ 1 warning（27.73s）**
- [x] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` ＝ **402 passed ＋ 2 skipped ＋ 1 warning（26.47s）**
      （同顆數，證明測試沒偷打真模型）
- [x] `/openapi.json` 端點數 ＝ **20**（＝「路徑 × HTTP 動詞」的組合數；
      原本 19，這次加了「讀一張照片」那一支）
- [x] DELETE 動詞 ＝ **0**（系統仍然沒有任何刪除功能）

### B. 瀏覽器（請親自點，五條）

- [ ] **資料夾**分頁 → 進一個資料夾 → 點一張照片：
      跳出彈窗，上面大圖、下面說明、四個欄位（類別／地點／物品／內容日期）都在。
      按 **Esc** 關掉之後，背後**還是那個資料夾的縮圖牆**。
- [ ] 上一條那顆窗裡，**沒有任何「改資料夾」的按鈕**（照片定案了就是定案了）。
      空的欄位顯示「**無**」，不是空白。
- [ ] **待辦**分頁 → 點一列：**沒有跳出新分頁**，原地開同一顆窗，
      窗最上面多一行待辦標題與到期日（沒有到期日的寫「無到期日」）。
- [ ] **待決定**分頁 → 點一張照片：跳出來的是**歸類彈窗**（採用／改選／自建／稍後再說），
      不是詳情窗。（這條是確認舊功能沒被改壞。）
- [ ] 挑一張**很舊的照片**（正式庫最早那兩張沒有原圖）→ 窗仍然開得起來，
      圖的位置是灰底「無原圖」。這是**預期行為**，不是壞掉。

### C. 終端機 log（請看四段）

- [ ] 在**上傳頁**（`/ui/upload.html`）**上傳一張照片**：看到 `kind=vlm` 一組（開始／結束）
      ＋ `kind=embed` 一組。結束行有 `elapsed_s=` 秒數與 `ok=true`。
      （本機模型看一張圖要 **2〜5 分鐘**，頁面沒壞，只是在等。）
- [ ] **把上傳頁頁首的開關撥到「雲端」再上傳一張**：`kind=vlm` 的 `backend` 變成 `cloud`
      （這條路約 2 秒），而 `kind=embed` **仍然是 `local`**
      （向量必須本機算，才跟資料庫裡既有的比得起來）。
- [ ] 到**問問題頁**（`/ui/ask.html`）**問一句語意題**（例如「我最近買過什麼飲料？」）：
      看到 `route`／`embed`／`answer` **三組**。
      再問一句條件題（例如「有哪些在 Target 拍的收據？」）：只有 `route`／`answer` **兩組**
      （那種查法不需要轉向量）。
- [ ] 回上傳頁**上傳一份兩頁 PDF**：看到 **兩組 `vlm` ＋ 兩組 `embed`**（每頁各一組，看得出哪一頁慢）。

### D. 兩個「壞掉時應該怎樣」（可選，想看再看；**兩條都在瀏覽頁 `/ui/browse.html` 做**）

- [ ] 把某張照片的原圖檔案從 `data/photos/` **改個名字**（例如 `7.jpg` → `7.jpg.bak`），
      回瀏覽頁重新整理再點它 → 窗照樣開，圖變成灰底占位，**不是**紅字錯誤。
      ⚠️ **看完請把檔名改回來**（那是正式的照片檔，不是測試資料；改名比刪掉安全，就是為了改得回來）。
- [ ] 在**瀏覽頁**開瀏覽器開發者工具的 Console（詳情窗這支程式只掛在這一頁，
      在上傳頁貼會說 `openPhotoDetailModal is not defined`），貼上
      `openPhotoDetailModal({photoId: 99999, task: {title: "測試", due_date: null}})` →
      窗開著、上面看得到「測試／無到期日」、下面是紅字「找不到這張照片」，
      **不是**空白分頁、**不是**瀏覽器的原生警告框。

### E. 最後

- [ ] 我（產品負責人）確認：**甲乙沒問題，可以做 Docker。** 日期：__________

---

## 7. 驗收清單（實作者自用）

- [x] §4.1 的錯誤表逐列盤點做完，表格反映**事實**（不是抄的）
- [x] 三顆新測試**首跑全綠**（收尾 phase 本來就該綠；紅了＝揪到真缺陷，回原 phase 修產品碼）
- [x] 三顆都做過**反向驗證**（把斷言反過來會紅）＝證明不是假綠
- [x] `pytest -q`：Phase 44 收尾時 **387 passed ＋ 2 skipped**；目前最終全量為
      **402 passed ＋ 2 skipped ＋ 1 warning（27.73s）**
- [x] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 目前同顆數（26.47s）
- [x] `git status docs/spec/` 乾淨（規格檔一字未動）
- [x] §4.4 七項掃碼全部通過，**特別是最後一項**：專案根目錄**沒有** `compose.yaml`／
      `Dockerfile`／`.dockerignore`／`compose.dev.yaml`／`db/docker-init/`
- [x] 本 phase **沒有改到任何產品程式碼**：`git status --short` 與開工前相比，
      只多一行 `?? tests/integration/test_design4_error_paths.py`（38〜43 留下的 `M` 照舊）。
      `app/` 底下若多出新的 `M`，代表你改了不該改的——除非那是「揪到真缺陷、回原 phase 修」
      的結果，那就要在紀錄裡寫清楚修了什麼、並重跑全量
- [x] §6 的 G1 檢查表已填好數字、已交給產品負責人
- [x] **停手等人。** 沒有拿到那句話之前，Phase 45 一行都不准做

---

## 8. 常見陷阱

1. **自己勾 G1**：最嚴重的一條。design4 §7 白紙黑字：「實作者不得自行把 G1 勾過」。
   就算全部測試都綠、你自己點過三遍，也**不算**。

2. **「反正之後要做，先把 compose.yaml 寫好放著」**：design4 §1.2 明列這是被否決的方案，
   §0 也再講一次。理由不是迷信——寫好的檔案會讓人以為可以跑了，
   一個手滑 `docker compose up` 就開始佔埠、建 volume。

3. **為了讓數字好看而刪測試或改斷言**：發現既有測試變紅，代表你在 38〜43 改壞了東西。
   回去修產品程式碼，不是修測試。

4. **skipped 從 2 變成別的數字**：那代表有人動到 `@未實作` 標籤或 `pytest_bdd_apply_tag`。
   摘標確實是本增量要做的事（規格裡「到期 2026-09-18」與「這週」互相矛盾那件事也一起解），
   但那是**最後一個** Phase 51 的工作，**這裡到階段丙結束都不准碰**——
   G1（design4 §7）與丙驗收（§8.9）都要求「既有 2 skipped 仍 skip」，提早摘等於自己弄壞驗收。

5. **把錯誤表當成「要新寫 6 顆測試」**：不是。Phase 37 的作法是「先盤點誰已經測了，
   只補真缺口」。重複的測試是負債，不是資產。

6. **G1 檢查表寫得太技術**：產品負責人是程式新手。B 段每一條都要是「點哪裡、看到什麼」，
   不能寫「驗證 PhotoDetailOut 的序列化行為」。§6 那份已經是這個寫法，照抄別改。

7. **忘了請他看 log 格式**：design4 §7 有一條是「產品負責人看過 §6 終端機 log 樣本，
   格式可接受」。格式是**他的**決定（他要拿去 grep），不是你的。
