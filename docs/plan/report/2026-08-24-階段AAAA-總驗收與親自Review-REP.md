# 階段 AAAA 完成報告：增量四（Phase 45〜51）總驗收與親自 Review

> 日期：2026-08-24
> 範圍：dev-prompt `phase0824.md` 指定的七份計畫檔全部做完之後的收尾
> **結論：七份計畫檔提出的想法全部實現；三項需要產品負責人（兩項要手機、一項是決策）**

---

## 1. 本輪做了什麼（九個階段）

| 階段 | 內容 | 結果 |
|---|---|---|
| SSS | 七份計畫檔校準（顆數、commit 前提、G1、QR 判準、憑證） | 5 處校準 |
| TTT | Phase 45 凍結、快照、雙備份 | 30/30 ✅ |
| UUU | Phase 46 db container 5434、灌庫、**★G2** | 33/33 ✅ G2 零差異 |
| VVV | Phase 47 切埠 5433、停 brew、連線字串帶帳號 | 32/32 ✅ |
| WWW | Phase 48 app 容器化、連線切換 | 28/28 ✅ |
| XXX | Phase 49 開發熱重載 overlay | 23/23 ✅ |
| YYY | Phase 50 開機常駐、鏡頭驗證、文件、十條總驗收 | 45/48（3 項見 §4） |
| ZZZ | Phase 51 規格摘標、詢問三路驗收 | 34/34 ✅ |
| AAAA | 總驗收與 review（本檔） | — |

---

## 2. 最終驗收數字（全部親自跑過）

```text
pytest -q                                     404 passed, 0 skipped   ✅
OLLAMA_BASE_URL=http://localhost:9 pytest -q  404 passed, 0 skipped   ✅（零外部依賴）
三份規格 binder                                27 passed, 0 SKIPPED    ✅
/openapi.json                                 20 運算元、DELETE 0      ✅
git status --short -- app/                    空 ＝ 產品程式碼一行未動  ✅
```

> ⚠️ **中途出現過 38 failed / 50 failed 的假警報，原因值得記下來。**
> 我在派 subagent 做文件稽核時，叫它「跑 `pytest` 驗證顆數」——結果它和我**同時**跑 pytest，
> 而 `tests/conftest.py` 的 autouse `reset_tables` 每個測試都 TRUNCATE **同一個**測試庫。
> 症狀是大量看似隨機的 404「找不到照片」與 `TypeError: 'NoneType' object is not subscriptable`，
> 每次紅的顆數都不一樣。**用 `pg_stat_activity` 當場抓到**：同一瞬間一個 backend 在
> `TRUNCATE photo, folder, entity...`、另一個在 `INSERT INTO task`。
> 等對方跑完再跑就是乾淨的 404。已把這個陷阱寫進 `CLAUDE.md` 的 pytest 段——
> 這是專案測試設計的既有性質（共用測試庫、沒有 per-worker 隔離），不是本次改壞的。

### 架構不變量（沒有因為容器化而走樣）

```text
SQL 只在 repository        ✅（grep 命中的 photos.py:488 是中文註解裡的 "UPDATE " 字樣，非 SQL）
無全域例外捕捉             ✅（main.py 沒有 exception_handler）
沒有 GET /photos 列全部     ✅
沒有 LAN_HOST              ✅（裁決一：本增量明確不做）
compose.yaml 沒有 --reload  ✅（只有警語註解）
dev overlay restart:"no"   ✅
沒有 network_mode: host／replicas／Ollama 進 compose ✅
data/、certs/、.env 沒有打進映像 ✅（`docker run --rm personaldocai-app ls -a /app` 只有 app 與 requirements.txt）
brew @17 沒有 uninstall、資料目錄 90M 還在 ✅
```

### ★ 後悔藥演練（計畫沒要求，我自己加的）

「備份檔存在」跟「備份救得回來」是兩件事。所以我把 Phase 45 的 `.dump` **真的灌進一個
一次性的資料庫**（`restore_drill`，完全不碰正式庫）：

```text
pg_restore → 零 error
灌出來的內容：37|10|2|11|2|1   ← 與 Phase 45 遷移前快照的數字完全相同
vector_dims                 ：1024
演練完 DROP DATABASE，正式庫 40 列不受影響
```

**後悔藥是真的能用的**，不是只有檔案躺在那裡。

---

## 3. Code review 的處置（8 項，逐項交代）

我派了一個獨立的 reviewer 看六個設定檔。它找到的每一項都有處置，**沒有一項是「看過就算」**：

### 修了（4 項）

| # | 問題 | 為什麼修 | 改法 |
|---|---|---|---|
| 1 | **`compose.yaml` 沒有寫死專案名** | Compose 拿「資料夾名」當專案名 → volume 叫 `<資料夾名>_pgdata`。資料夾一改名／搬家／重新 clone 成別的名字，`up -d` 會**安靜地建一個新的空 volume**、跑 initdb，app 對著空庫起來。照片其實還在舊 volume，但畫面上跟資料全沒了一樣。**這是唯一一個會讓人半夜以為毀了資料的問題** | 加 `name: personaldocai`（等於現在推導出來的值，所以 volume 名稱不變、資料不動——已驗） |
| 2 | **healthcheck 早 22 秒變綠** | 官方映像第一次啟動會先起一個 `listen_addresses=''` 的暫時伺服器跑 init，只聽 Unix socket；不寫 `-h` 的 `pg_isready` 走的正是 socket。後果：app 的 `depends_on: service_healthy` 在 volume 第一次誕生時**形同虛設**，而 §4.3 那個「剛看到 healthy 卻連線被拒」的坑就是它 | `pg_isready` 補 `-h 127.0.0.1`。**這是與 design4 §8.4 原文的刻意差異**，已在 `compose.yaml` 註解與 `phase-46` 計畫檔寫明理由 |
| 3 | **「不要弄丟正式庫」的清單只寫了 `down -v`** | 漏了三種更常見的：`docker system prune --volumes`／`volume prune -a`（刪掉沒有 container 指著的具名 volume ＝ 任何一次 `down` 之後都危險，Docker Desktop 的 Reset 與 Volumes 分頁同理）、`docker volume rm`、以及**把 tag 從 pg17 換成 pg18**（pg18 的 PGDATA 是 `/var/lib/postgresql/18/docker`，掛載點不再是 PGDATA → 建新空叢集） | `compose.yaml` 檔頭與 `CLAUDE.md` 都擴成四項 |
| 4 | `.dockerignore` 的 `.DS_Store` 只擋根目錄 | 一行的事 | 改成 `**/.DS_Store` |

### 記錄但不改（2 項，理由寫在文件裡）

| # | 問題 | 為什麼不現在改 |
|---|---|---|
| 5 | **host 的 `.venv` 與容器裡的套件版本已經分岔**（實測 `langchain-core` 1.5.6 vs 1.6.0、`uvicorn` 0.52.3 vs 0.52.4）——`requirements.txt` 全是 `>=`，映像在 build 當下才解析。意思是 `pytest` 全綠驗的是 host 那份，**不等於驗過實際跑的映像** | 釘版是有維護成本的取捨（side project 原則），而且**不在七份計畫檔的範圍內**——這種決定應該由產品負責人下，不該我順手改掉。已寫進 `CLAUDE.md`，並訂出折衷做法：**「重建映像」要當成需要手動煙霧一次的動作** |
| 6 | **`data/` 沒有備份路徑**：52 MB 原圖與縮圖（38 張照片指著它），不入版控 ＝ 全世界只有一份，連 `git clean -xdf` 都會清掉。資料庫還原回來但 `data/` 沒了的話，照片列還在、大圖全 404 | 同上，屬於備份策略的決定。已在 `CLAUDE.md` 的「日常備份」段寫明缺口並附上**實際驗過可用**的指令（`tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/`，實測產出 51 MB） |

### 退回，不採納（1 項，說明理由）

| # | 建議 | 為什麼不採納 |
|---|---|---|
| 7 | 把 `compose.dev.yaml` 重複列的三個 mount 刪掉，只留 `./app`（因為 volumes 是逐項合併，不會弄丟；重複反而有「改了 compose.yaml 忘了改 dev」的漂移風險） | **計畫明文禁止**：`phase-49` §4.1 寫「四項全部重列……真的只寫 `./app` 那一行**也不會**弄丟另外三個（合併規則如上），**但不要這樣改**」，理由是照 design4 §8.4.1 原文、而且列全了才能一眼看出開發模式實際掛了哪四個。reviewer 的漂移顧慮是對的，但這是**計畫已經權衡過並明確裁定**的事——我不會為了自己的偏好推翻它。已把這個 tradeoff 記在這裡，日後要改是產品負責人的決定 |

### 已經處理過（1 項）

| # | 建議 | 狀態 |
|---|---|---|
| 8 | QR 的 IP 判準不能用「是不是 172 開頭」 | **階段 SSS 就校準了**，本輪還拿到決定性證據（見 §5） |

---

## 4. ⚠️ 沒做完的事（三項，都需要產品負責人）

| # | 項目 | 為什麼我不做 | 要做什麼 |
|---|---|---|---|
| 1 | **iPhone 實機掃 QR**（Phase 50 §4.3 最後一條；同時結掉 Phase 36 一直掛著的真機驗收） | **需要手機**，產品負責人 2026-08-24 明示「要用到我的手機，你要停下來跟我說，我自己手動測試」 | 用 `https://172.29.93.122:8000/ui/camera-desk.html` 開桌面頁（**不要用 localhost**）→ iPhone 同一個 Wi-Fi 掃 QR → 給鏡頭權限 → 桌面看到即時預覽 → 按快門 → 三關彈窗鏈跳出來。憑證已重簽涵蓋這個 IP，iPhone 若沒信任過 rootCA，步驟在 `CLAUDE.md` 指令區 |
| 2 | **真的重開機一次**（Phase 50 §4.2 的「更完整，建議做」） | 產品負責人外出中，**不該替他重開電腦**（會關掉他所有開著的東西） | 順手重開一次，開機後不打任何指令，直接開 `https://127.0.0.1:8000/ui/upload.html`。等價的輕量版我已經驗過（停/開 Docker Desktop，兩個容器 15 秒內自己回來） |
| 3 | **瀏覽器視覺驗收** | Chrome MCP 回報這個帳號連了**兩個瀏覽器**，必須由使用者指定一個才能操作；不適合為此卡住 | 若要補，開 `https://127.0.0.1:8000/ui/browse.html` 點一張照片看詳情窗。**風險很低**：45〜51 沒有一行 UI 程式碼變更，UI 與已驗收過的 commit 逐位元相同；我改用等價的 HTTP 驗證（三頁＋所有前端資源＋所有資料端點＋縮圖／原圖／詳情＋舊照片 404，共 22 條）全數通過 |

**另外兩項是決策，不是驗收**（§3 的第 5、6 項）：要不要釘套件版本、要不要把 `data/` 納入備份。

---

## 5. 本輪最有價值的三個發現

### ① QR 的 IP 判準原本是錯的（而且錯得看不出來）

計畫寫「QR 必須是 `192.168.…`、不可以是 `172.…`」。實測：

```text
用區網 IP 開桌面頁   → QR host = 172.29.93.122   ← 正確（＝ ipconfig getifaddr en0）
用 127.0.0.1 開      → QR host = 172.24.0.3      ← 錯誤（Docker 內部網段）
```

**兩個都是 `172.x`。** 用前綴判斷不但幫不上忙，還會把**正確**的 QR 判成錯的。
唯一可靠的判準是「QR 的 host 逐字等於 `ipconfig getifaddr en0`」——這個判準在任何網段都成立。
已改進 `CLAUDE.md`、`phase-45`、`phase-50`、總覽四處。

### ② 顆數基準本來就是錯的（387 vs 402）

七份計畫檔都寫 `387 passed`，但實際是 402。查證後發現：387 是 Phase 44 **中途**的數字，
同日 hardening 又補了 15 顆，G1 驗收包記的是 **402**。
若不校準，45〜50 每一份的驗收都會「對不上顆數」→ 被誤判成 Docker 搬壞了。

### ③ 真模型不能並行（Phase 48 的 500）

把上傳與詢問同時打，db container 被壓垮（postmaster 花 2 分鐘才殺得掉子行程、WAL 自動復原、
**資料零損失**）。排除了記憶體（11.67 GiB，容器只用 40〜650 MB）、OOM（VM kernel log 沒有）、
pgvector／HNSW（單獨查詢 0.049 秒正常）之後，改成順序執行 100% 正常。
本機真模型的實測延遲：**看圖 64〜88 秒、路由 138 秒、回答 92 秒**——這是使用習慣的限制，
不是容器化的缺陷（同樣的並行負載在 host uvicorn 上也會壓垮同一顆 Postgres）。

---

## 5.5 第二份 review（文件稽核）的處置

另一個 subagent 逐條實跑 `CLAUDE.md` 的指令、比對總覽的數字。**指令區全部可用**
（每一條 `psql`／`pg_dump`／`docker compose` 都照抄跑過），顆數 404、端點 20 也都獨立複驗過。
但它在**我沒有改寫到的舊段落**裡找到 5 處過期敘述，全部已修：

| # | 位置 | 過期的說法 | 為什麼危險 | 已改成 |
|---|---|---|---|---|
| 1 | 「重要陷阱」段 | 「本專案用 `postgresql@17` 跑在 5433，互動 shell 由 `PGPORT=5433` 讓 psql 預設連對」 | **最危險的一條**：它就在新人專門讀的「陷阱」段裡，而且描述的是 Docker 之前的世界。照做會撞上 socket 錯誤——正是同一份文件另一段在警告的那個錯誤 | 改成 Docker 現況，並註明「光有 `PGPORT` 不夠，還要 `PGUSER`＋`PGHOST` 三個都到齊」 |
| 2 | 現況段 | 「`@未實作` 摘標仍待產品負責人」 | 與同一份文件另一處（已摘標）自相矛盾 | 改成「已於 2026-08-24 Phase 51 完成」；手機驗收仍標為待產品負責人 |
| 3 | 現況段 | 增量三計畫「在 `docs/plan/unfinish/`」 | 新人去 `unfinish/` 找會找不到（早就歸檔到 `finish/` 了） | 改成 `finish/`，並註明 `unfinish/` 現在只剩增量四 |
| 4 | 專案概述 | 增量總覽在 `docs/plan/unfinish/phase-00-增量總覽.md` | 同上，路徑是壞的 | 改成 `finish/` |
| 5 | 測試設計前提 | 「**兩份** `.feature` 即驗收規格」 | 實際有**七份** | 列出七份，並註明其中三份已有 binder |

另外清掉一個**我自己製造的垃圾**：`docs/plan/unfinish/db/docker-init/`（空目錄）。
成因是我在 Phase 46 跑 `mkdir -p db/docker-init` 時 cwd 漂到了 `docs/plan/unfinish`
——空目錄 git 看不見，不清掉會一直留著。**這是本輪我重複犯了三次的錯**
（相對路徑指令沒有先 `cd` 回專案根目錄），已在各階段 REP 記錄。

還修了總覽一處措辭：驗收清單寫「brew `@17` 為 `stopped`」，但 `brew services list`
實際印的是 **`none`**——照字面 grep 會找不到。已補註兩個字都要試。

---

## 6. 收工狀態

```text
   Mac
   ├── postgresql@14 (brew) :5432   ← 別的專案 ★ 全程沒碰
   ├── postgresql@17 (brew)  :---   ← stopped；資料目錄 90M 留著＝後悔藥第 1 層
   ├── Ollama              :11434   ← 已設開機啟動（登入項目）
   └── Docker Desktop（AutoStart = True）
         ├── app  0.0.0.0:8000   HTTPS，無 --reload
         └── db   127.0.0.1:5433 (healthy)   volume: personaldocai_pgdata

   正式庫  photo 40（37 原始 ＋ P47/P48/P50 各一張煙霧）／folder 10／entity 2／task 2
   pytest  404 passed ＋ 0 skipped        端點 20
   憑證    SAN 含 172.29.93.122（＝現在的 en0），2028-11-24 到期

   後悔藥（第一個穩定週期內不要清）
     /opt/homebrew/var/postgresql@17            brew 資料目錄（第 1 層）
     ~/PersonalDocAI-backup-docker遷移前.{sql,dump}    第 2 層（已演練過真的灌得回來）
     ~/PersonalDocAI-backup-2026-08-24-P48復原後.dump  崩潰復原後補的
     ~/PersonalDocAI-docker{遷移前,灌入後,切埠後}快照.txt  三份對帳證據
```

**沒有 commit**（沿用產品負責人既有指示）；`unfinish/` → `finish/` 的歸檔隨 commit 執行。

**增量四（Phase 38〜51）全部完成。**
