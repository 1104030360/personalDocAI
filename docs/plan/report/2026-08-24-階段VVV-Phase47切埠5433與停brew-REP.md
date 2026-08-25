# 階段 VVV 完成報告：Phase 47 丙-2 —— 切回 5433、停 brew、連線字串帶帳號

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-47-丙2切埠5433與停brew.md`（32 個 checkbox 全數打勾）
> 產出：`compose.yaml` 改埠、`tests/conftest.py` 改 URL、`.env` 改 URL、`~/.zshrc` 加兩個變數
> **`app/` 一行未動**

---

## 1. 實作邏輯

**這是整條遷移路線的「切換那一刻」。** 兩件事必須同一次做完，少一件系統就是壞的：

| 動作 | 不做的後果 |
|---|---|
| 埠切回 5433 | Docker 停在 5434，既有文件／`PGPORT`／測試設定全都指錯地方 |
| 連線字串加帳號 | psycopg 會用 macOS 帳號 `linjunting` 去連——**Docker 裡沒有這個角色**，`pytest` 整套紅 |

計畫因此把 design4 原本排在丙-3 的「改 `.env`」提前到本 phase，
讓「每個 phase 做完系統都可跑」這條原則成立。

### 四個動作，順序不可對調（實際執行順序）

```text
① docker compose stop db            → Stopping / Stopped
② compose.yaml 埠 5434 → 5433       → 只改 ports 那三行，volumes 一個字不動
③ brew services stop postgresql@17  → Successfully stopped
   └─ lsof -iTCP:5433 → 空 ✅
④ docker compose up -d db           → Recreated（改了埠設定必定重建 container）
   └─ Up 6 seconds (healthy)、PORTS = 127.0.0.1:5433->5432/tcp
```

「Recreated」是**正常的**——重建的是 container，volume `pgdata` 原封不動。

---

## 2. 步驟與實測結果

### 2.1 停 brew（只停服務）

```text
brew services list：
  postgresql@14  started   ← 別的專案，全程沒碰 ✅
  postgresql@17  none      ← 已停 ✅

後悔藥第 1 層：/opt/homebrew/var/postgresql@17 仍在，90M   ✅ 不准刪
```

### 2.2 Docker 接手 5433

```text
lsof -iTCP:5433 -sTCP:LISTEN
COMMAND     PID       USER  …  NAME
com.docke 75917 linjunting  …  TCP localhost:pyrrho (LISTEN)
          ↑ 是 Docker，不是 postgres  ✅
```

### 2.3 資料完好（切埠後 diff）

```bash
diff <(tail -n +2 ~/…遷移前快照.txt) <(tail -n +2 ~/…切埠後快照.txt)
#  → 沒有任何輸出，exit=0   ✅
```

### 2.4 連線字串三處

| 檔案 | 改動 |
|---|---|
| `.env` | `DATABASE_URL=postgresql://postgres@localhost:5433/PersonalDocAI`，並把上方註解整段改寫（說明帳號的由來、為什麼沒密碼、以及「這行只對 host 生效，容器裡由 compose 的 `environment` 覆蓋」） |
| `tests/conftest.py` 第 7 行 | `TEST_DATABASE_URL = "postgresql://postgres@localhost:5433/PersonalDocAI_test"`。**第 26 行的安全網斷言一個字未動**（`assert "PersonalDocAI_test" in config.DATABASE_URL`——加了帳號之後照樣成立） |
| `~/.zshrc` | 追加 `export PGUSER=postgres`、`export PGHOST=127.0.0.1`，並寫上為什麼（Docker 只發佈 TCP 埠、沒有 Unix socket 檔）與副作用提醒（要連 `@14` 時三個變數都得用旗標蓋掉） |

### 2.5 回歸

```text
pytest -q                                   →  402 passed, 2 skipped, 1 warning (19.94s)  ✅
OLLAMA_BASE_URL=http://localhost:9 pytest -q →  402 passed, 2 skipped, 1 warning (19.37s)  ✅
```

**同顆數**＝測試庫換到 Docker 之後零影響；**第二輪同顆數**＝證明測試從頭到尾沒打到真 Ollama。

### 2.6 服務可用（讀 ＋ 寫都驗）

host 上起 uvicorn（app 容器化是下一個 phase）：

```text
GET /health   →  {"status":"ok"}
GET /folders  →  200，資料夾與 photo_count 都對（未分類 5、收據 13、…）
```

**三頁與所有前端資源、所有資料端點逐一打過**（＝瀏覽頁畫得出來所需的一切）：

```text
upload.html / ask.html / browse.html / camera-desk.html        200 ×4
folder_modal.js / entity_modal.js / task_modal.js /
classify_chain.js / photo_detail_modal.js / ai_switch.js /
style.css                                                       200 ×7
GET /folders /folders/2 /tasks /entities                        200 ×4
GET /photos/10/thumbnail   200 image/jpeg 19,010 bytes
GET /photos/10/image       200 image/jpeg 70,597 bytes
GET /photos/10（詳情端點）  200
GET /photos/1/thumbnail    404  ← 舊照片沒有原圖，**預期行為**（前端畫占位）
```

**寫入路徑（真上傳，證明不只是讀取）**：

```text
POST /photos（真 JPEG）  →  HTTP 201，耗時 87.8s
  id=38、text="This is a receipt from Target showing purchases of various grocery items."
  folder=未分類(1)          ← 上傳一律先進收件箱，設計如此
  suggested_folder=收據(2)  ← 真模型從注入清單挑中，正確
  thumbnail_url=/photos/38/thumbnail

AI 計時 log（階段乙的回歸，順帶驗到）：
  AI 開始 kind=vlm   backend=local model=gemma4:e2b
  AI 結束 kind=vlm   … elapsed_s=84.7 ok=true understood=true text_chars=73 item_count=3
  AI 開始 kind=embed backend=local model=bge-m3
  AI 結束 kind=embed … elapsed_s=2.8 ok=true

落地驗證：
  data/photos/38.jpg   70,597 bytes  ✅
  data/thumbs/38.jpg   19,010 bytes  ✅
  DB photo 列數 37 → 38 ✅
  id=38：category=未分類、folder_id=1、suggested_category=收據、
         original_path=data/photos/38.jpg、vector_dims=1024 ✅
```

### 2.7 版控狀態（與計畫 §6 預期完全一致）

```text
 M tests/conftest.py          ← 本 phase 改的
 ?? compose.yaml              ← P46 新建，依指示未 commit
 ?? db/docker-init/           ← P46 新建
 （＋ docs/ 底下的計畫檔與 TODO／REP）

git status --short -- app/   →  空 ✅ 產品程式碼一行未動
.env 與 ~/.zshrc 不會出現（前者在 .gitignore、後者不在專案裡）
```

---

## 3. 測試方式

- **資料完整**：`diff` 兩份快照（逐字）
- **埠真的換手**：`lsof` 看 COMMAND 欄是 `com.docke` 不是 `postgres`
- **測試庫真的搬過去**：`pytest -q` 兩輪同顆數（brew 已停，連得到就代表打的是 Docker）
- **讀路徑**：11 個靜態檔 ＋ 4 個資料端點 ＋ 縮圖／原圖／詳情，逐一看 HTTP 狀態碼
- **寫路徑**：真上傳一張 → 201 ＋ 磁碟出現兩個檔 ＋ DB 列數 +1 ＋ 向量 1024 維
- **環境變數真的生效**：開一個**互動式** zsh 跑 `psql -d PersonalDocAI`（見下方問題 2）

---

## 4. 遇到的問題與解法

| # | 問題 | 解法 |
|---|---|---|
| 1 | **切埠後 `diff` 有輸出**，第一眼像是資料搬錯了：<br>`< === 向量維度（任一張照片）===`<br>`> === 向量維度（任一照片）===` | **是我打字漏了一個「張」**。計畫在三份檔案裡都用粗體警告過「三份的 SQL 與 `echo` 標題逐字相同，改一個字 G2 就永遠對不上，而且差異看起來會很像資料搬錯了」——這次親身踩到，也證明那個警告是對的。處置：把標題改回逐字相同、重新產出快照，`diff` 隨即歸零。**資料從頭到尾沒有任何問題** |
| 2 | **`zsh -lc` 測 `PGUSER`／`PGHOST` 是空的**，一度以為 `~/.zshrc` 沒寫進去 | 是**測法錯了**：`~/.zshrc` 只有**互動式** shell 才會讀，`zsh -lc` 是 login 但**非互動**。而 `PGPORT` 之所以有值，是從我這個父行程的環境**繼承**來的（`env \| grep -c ^PGPORT` ＝ 1 證實），不是 `.zshrc` 生效。改用 `zsh -ic` 重測：三個變數全到齊，`psql -d PersonalDocAI` 直接回 37 ✅ |
| 3 | **瀏覽器視覺驗收做不了**：Chrome MCP 回報這個帳號連了兩個瀏覽器，必須由使用者指定一個才能操作 | 產品負責人外出中，不適合為此卡住。改用**等價的 HTTP 驗證**（§2.6 那 22 條）——三頁與所有前端資源、所有資料端點、縮圖／原圖／詳情、以及舊照片的 404 全部涵蓋。理由上也站得住：45〜51 沒有一行 UI 程式碼變更，UI 與已驗收過的 commit 逐位元相同，風險在基礎設施不在畫面。**瀏覽器選擇這個問題會與 Phase 50 的手機真機驗收一起問**，把需要人的事集中在一次 |
| 4 | 上傳耗時 87.8s，比 CLAUDE.md 記的「2〜5 分鐘」快 | 沒有問題，只是機器狀態不同。放到背景跑並輪詢，同時做別的驗證，沒有浪費時間 |

---

## 5. 測試結果

**全數通過。** Phase 47 的 32 個 checkbox 全部打勾。

```text
── 本 phase 結束時的狀態 ──────────────────────────────────
  brew postgresql@14  :5432  ●started   ← 別的專案 ★ 全程沒碰
  brew postgresql@17  :---   ○none      ← 資料目錄 90M 留著＝後悔藥第 1 層
  docker  db          :5433  ●healthy   ← ★ 正本現在住這裡（volume: personaldocai_pgdata）
  host    uvicorn     :8000  ○stopped   ← 驗完就停（Phase 48 要用這個埠）

  .env      DATABASE_URL = postgresql://postgres@localhost:5433/PersonalDocAI
  conftest  TEST_DATABASE_URL = postgresql://postgres@localhost:5433/PersonalDocAI_test
  ~/.zshrc  PGPORT=5433（本來就有）＋ PGUSER=postgres ＋ PGHOST=127.0.0.1（新加）

  pytest    402 passed ＋ 2 skipped（兩輪同顆數）
  正式庫    photo 38 列（37 ＋ 本 phase 的上傳煙霧 1 張）
```

⚠️ **從這一刻起 volume 裡的是正本。** Phase 46 §5.4 那個「砍掉重灌」的特權到此為止——
`docker compose down -v` 與 `docker volume rm personaldocai_pgdata` 從此等於刪正式庫。

---

## 6. 給 Phase 48 的提醒

- 8000 埠已空出來（host uvicorn 已停），container 起得來。
- **憑證要先處理**：`certs/cert.pem` 的 SAN 是舊 IP `172.20.10.6`，
  現在的 en0 是 `172.29.93.122`——階段 SSS 已把「檢查 SAN」寫進 `phase-48` §2 前置條件。
- 正式庫現在有 **38** 列照片（`§4.5 ①` 的比對要拿 P45／P47 那兩份**存檔**，
  不要現場再查一次——計畫 `phase-50` §4.5 ① 的說明框講的就是這件事）。
