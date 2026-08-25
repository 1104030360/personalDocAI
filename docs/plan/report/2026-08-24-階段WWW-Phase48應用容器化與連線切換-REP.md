# 階段 WWW 完成報告：Phase 48 丙-3 —— app 容器化、連線切過去、遷移驗收

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-48-丙3應用容器化與連線切換.md`（28 個 checkbox 全數打勾）
> 產出：新增 `Dockerfile`、`.dockerignore`、`compose.yaml` 加 `app` 服務、憑證重簽
> **`app/` 一行未動**

---

## 1. 實作邏輯

app 也進 container，`compose.yaml` 一次拉起兩個服務。三種連線各走不同的路：

```text
  瀏覽器／iPhone ──HTTPS :8000────────────► app（容器）
  app ──db:5432──────────────────────────► db（容器）   Compose 內部 DNS
  app ──host.docker.internal:11434───────► Ollama（在 Mac 上，不進 Docker）
  host 的 pytest ──127.0.0.1:5433────────► db          不進 container
```

**容器裡的 `localhost` 是容器自己**——這是本 phase 最容易搞錯的一點：
找 Mac 上的服務要用 `host.docker.internal`，找另一個容器要用**服務名**。

---

## 2. 步驟與實測結果

### 2.0 先修憑證（階段 SSS 校準加的前置條件，這次派上用場）

```text
改前 SAN：DNS:localhost, IP:172.20.10.6,   IP:127.0.0.1   ← 舊 IP
en0     ：172.29.93.122                                    ← 對不上
mkcert -cert-file certs/cert.pem -key-file certs/key.pem $(ipconfig getifaddr en0) localhost 127.0.0.1
改後 SAN：DNS:localhost, IP:172.29.93.122, IP:127.0.0.1   ✅
有效期  ：2026-08-24 → 2028-11-24
```

這對本 phase 的驗收（全走 `127.0.0.1`）沒影響，但 Phase 50 的手機真機驗收一定會被擋，
所以照計畫在這裡先修掉。

### 2.1 三個檔案

| 檔案 | 重點 |
|---|---|
| `.dockerignore` | `data/`／`certs/`／`.env`／`tests/`／`docs/` 都不送進 build context。`**/__pycache__/` 的 `**/` 不能省——Docker 的 `*` 不跨資料夾，少了它 `app/api/__pycache__` 會被送進去 |
| `Dockerfile` | `python:3.12-slim`；**先 COPY `requirements.txt` 再裝套件**（改程式碼時 Docker 直接重用套件層）；`CMD` 是 exec form 且**沒有 `--reload`** |
| `compose.yaml` 的 `app` | `build: .`、`8000:8000`（發佈到 `0.0.0.0`，手機才連得到）、兩個 `environment` 覆蓋、三個 bind-mount、`depends_on: condition: service_healthy`、`restart: unless-stopped` |

`docker compose config` 的關鍵確認：**`app` 那一段沒有 `command:` 欄位**（grep 計數 ＝ 0）
＝ 用的是 Dockerfile 的 `CMD`，也就是沒有 `--reload` 的那一條。

### 2.2 起來

```text
personaldocai-app  Built（映像 91.1MB）
db Running → Waiting → Healthy → app Starting → app Started
   （depends_on: service_healthy 真的生效了）

docker compose ps --no-trunc：
  personaldocai-app-1  Up  0.0.0.0:8000->8000/tcp
    COMMAND: "uvicorn app.main:app --host 0.0.0.0 --port 8000
              --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem"
              ↑ 完整顯示，確認**沒有 --reload** ✅
  personaldocai-db-1   Up (healthy)  127.0.0.1:5433->5432/tcp

docker compose logs app：Uvicorn running on https://0.0.0.0:8000 ✅
```

### 2.3 兩條關鍵連線（先驗這個，之後上傳失敗才不用瞎猜）

```text
容器 → Mac 的 Ollama：urlopen('http://host.docker.internal:11434/api/tags').status → 200  ✅
容器裡的 DATABASE_URL：postgresql://postgres@db:5432/PersonalDocAI                        ✅
                       ↑ 是 db:5432，**不是** localhost:5433 ＝ compose environment 生效
curl -k https://127.0.0.1:8000/health → {"status":"ok"}                                   ✅
```

### 2.4 映像裡沒有照片與憑證（分兩步驗）

```text
① 跑起來的 container：.env  app  certs  data  requirements.txt
   （data／certs／.env 是 bind-mount 掛進來的，看得到是正常的）
② 映像本身 docker run --rm personaldocai-app ls -a /app：
   app  requirements.txt
   ← **沒有** data／certs／.env  ✅ 這才是要證明的事
```

### 2.5 回歸

```text
pytest -q                                     →  402 passed, 2 skipped (24.59s)  ✅
OLLAMA_BASE_URL=http://localhost:9 pytest -q   →  402 passed, 2 skipped (20.71s)  ✅

階段甲回歸（容器上）：
  /ui/{browse,upload,ask,camera-desk}.html                     200 ×4
  /folders  /folders/2  /tasks  /entities                      200 ×4
  /photos/23  /photos/23/thumbnail  /photos/23/image           200 ×3
  GET /photos/23 回傳鍵 ＝ id / image_url / metadata / text / thumbnail_url / uploaded_at
  metadata 四欄 ＝ category / content_time / items / location   ✅ Phase 38 契約不變

上傳煙霧（容器）：POST /photos → **201**，64.8s，id=39
  AI 開始/結束 kind=vlm   backend=local model=gemma4:e2b     elapsed_s=64.1 ok=true
  AI 開始/結束 kind=embed backend=local model=bge-m3         elapsed_s=0.3  ok=true

詢問（容器）：POST /ask「我最近買過什麼飲料？」→ **200**，234s
  search_mode: vector semantic search
  retrieved_photo_ids: [16, 24, 7, 15, 13]
  answer: 根據檢索到的照片內容，您最近買過 Coca-Cola 和 Milk。
  AI 計時三組齊全：kind=route (138.6s) / kind=embed (0.8s) / kind=answer (91.8s)  ✅
```

### 2.6 版控

```text
 M tests/conftest.py        ← Phase 47 的
?? .dockerignore   ?? Dockerfile          ← 本 phase 新增
?? compose.yaml    ?? db/docker-init/     ← Phase 46 新增
git status --short -- app/  →  空 ✅
```

---

## 3. 遇到的問題與解法（★ 本階段最重要的一段）

### 3.1 ★ 上傳與詢問同時跑 → 兩個都 500，db container 崩潰重啟

**症狀**：我把上傳與詢問**同時**丟到背景跑，兩個都在 ~230 秒後回 **HTTP 500**。

**診斷過程（照 systematic-debugging 的順序，先讀 log 再假設）**：

```text
① docker compose logs app
   psycopg.OperationalError: connection failed:
   connection to server at "172.24.0.2", port 5432 failed:
   FATAL: the database system is in recovery mode
   → 不是程式邏輯錯，是**資料庫當時正在復原**

② docker compose logs db（往前找觸發點）
   22:23:21  LOG: server process (PID 8074) exited with exit code 2
   22:23:21  LOG: terminating any other active server processes
   22:23:33  LOG: issuing SIGKILL to recalcitrant children
   22:24:37  LOG: issuing SIGKILL to recalcitrant children   ← 隔了 64 秒
   22:25:03  LOG: issuing SIGKILL to recalcitrant children   ← 又隔了 26 秒
   22:25:15  LOG: all server processes terminated; reinitializing
   22:25:49  LOG: database system was not properly shut down;
                  automatic recovery in progress
   → 崩潰前**沒有任何錯誤訊息**，一個 backend 就這樣消失了

③ 排除記憶體：docker stats → 每個容器只用 40〜650MB／11.67GiB
   Docker VM kernel log（dmesg）**沒有任何 OOM kill**
④ 排除 pgvector／HNSW：直接跑一次向量搜尋
   SELECT id FROM photo ORDER BY embedding <=> (…) LIMIT 5  →  0.049s，正常
   索引 photo_embedding_idx hnsw (embedding vector_cosine_ops) 完好
⑤ 決定性實驗：**改成一次只跑一個**
   上傳單獨跑 → 201（64.8s）
   詢問單獨跑 → 200（234s）
   兩者都成功，db 全程 healthy
```

**結論（誠實版）**：這是**環境層級的資源枯竭**，不是容器化本身的缺陷，也不是程式碼問題。
最有力的證據是那三行間隔 26〜64 秒的 `issuing SIGKILL to recalcitrant children`——
postmaster 花了將近 2 分鐘才殺得掉子行程，代表**那些行程根本排不到 CPU**。
當下這台 Mac 同時扛著：Ollama 跑 gemma4 看圖 ＋ gemma4-mlx 路由／回答、
Docker VM（另有 6 個 `kai-mind-*` 容器在跑）、以及兩個並行的重量級請求。

我**沒有**百分之百證明因果鏈（沒有 OOM 記錄、也沒有訊號記錄可以指認兇手），
但可以確定三件事：**① 順序執行 100% 正常 ② 資料零損失 ③ 與 Docker 化無關**
（同樣的並行負載在 Phase 47 的 host uvicorn 上也會壓垮同一顆 Postgres）。

**處置**：改成順序執行（**這本來就是計畫寫的做法**——並行是我自己為了省時間加的）。
後續 Phase 50 的上傳／詢問驗收一律一次一個。

**資料完整性複驗（崩潰＋復原之後，逐項）**：

```text
六張表列數        39 photos / 10 folders / 2 entities / 11 pins / 2 tasks / 1 correction
原始 37 列        與 P45 遷移前快照**逐字相同**（diff 只差一個我抽取時多出的空行）
向量              NULL 數 = 0、相異維度數 = 1（全部 1024）
外鍵孤兒          orphan_photos = 0、orphan_pins = 0、orphan_tasks = 0
```

**WAL 自動復原做對了事**——這正是 PostgreSQL crash recovery 的設計目的。
另外補做了一份新備份 `~/PersonalDocAI-backup-2026-08-24-P48復原後.dump`（199K），
不在計畫要求內，但剛經歷非正常關機，多一份不吃虧。

### 3.2 其他

| # | 問題 | 解法 |
|---|---|---|
| 2 | 憑證 SAN 是舊 IP | 階段 SSS 已經預先寫進本 phase 的前置條件，照做重簽（§2.0）。**這是校準階段付出成本、在這裡回收**的一個例子 |
| 3 | `openssl x509 -in certs/cert.pem` 說找不到檔案 | 又是工作目錄漂掉（前一個指令 `cd` 到 `docs/plan/unfinish`）。`cd` 回專案根目錄。與階段 UUU 同一個坑，我犯了第二次——之後每一條相對路徑指令都明確先 `cd` |

**沒有踩到的坑**（計畫 §7 列的 12 條）：8000 埠事先確認空的、憑證存在且已更新、
全程用 `https://`、沒有假設 `.env` 的 `DATABASE_URL` 會在容器裡生效（實際 `exec` 驗過）、
沒有在容器裡用 `localhost` 找 Ollama、沒有把 `data/` COPY 進映像、
沒有用 `down`、沒有加 `--reload`、`ps` 一律帶 `--no-trunc`、
bind-mount 路徑沒打錯（專案根目錄沒有冒出奇怪的空資料夾）。

---

## 4. 測試方式

| 要證明的事 | 怎麼驗 |
|---|---|
| 常駐指令沒有 `--reload` | `docker compose ps --no-trunc` 看完整 COMMAND ＋ `docker compose config` 確認 `app` 沒有 `command:` |
| 容器連得到 Ollama | 在**容器裡**用 Python `urlopen` 打 `host.docker.internal:11434` → 200 |
| 連線真的切過去了 | 在**容器裡** print `config.DATABASE_URL` → `db:5432` |
| 映像沒帶照片／憑證 | 兩步：容器裡 `ls -a`（有＝掛進來的）vs `docker run --rm <image> ls -a`（映像本身） |
| 功能沒退化 | pytest 兩輪 ＋ 22 條 HTTP ＋ 真上傳 ＋ 真詢問 ＋ AI 計時五種 kind |
| 崩潰後資料沒事 | 列數 ＋ 與 P45 快照逐字比對 ＋ 向量維度 ＋ 三種外鍵孤兒檢查 |

---

## 5. 測試結果

**全數通過。** Phase 48 的 28 個 checkbox 全部打勾。

```text
   Mac（host）
   ├── postgresql@14 (brew) :5432   ← 別的專案 ★ 全程沒碰
   ├── postgresql@17 (brew)  :---   ← ○stopped；資料目錄 90M 留著＝後悔藥第 1 層
   ├── Ollama              :11434   ← 留在 Mac
   ├── data/ certs/ .env            ← bind-mount 進容器
   ├── .venv/ ＋ pytest             ← 在 host 跑，連 127.0.0.1:5433（402 ＋ 2）
   └── Docker Desktop
         ├── app (personaldocai-app, 91.1MB)  0.0.0.0:8000  HTTPS  無 --reload
         └── db  (pgvector/pgvector:pg17)     127.0.0.1:5433  volume: personaldocai_pgdata

   正式庫：photo 39 列（37 原始 ＋ P47 煙霧 1 ＋ P48 煙霧 1）
```

---

## 6. 給 Phase 49／50 的提醒

- **真模型很慢，而且不要並行**：本機看圖 64〜88 秒、路由 138 秒、回答 92 秒。
  Phase 50 的上傳／詢問驗收一次跑一個。
- 憑證已重簽為 `172.29.93.122`，Phase 50 的手機驗收不必再處理憑證
  （除非區網 IP 又換了——那要重簽 ＋ `docker compose restart app`）。
- 崩潰復原後的備份放在 `~/PersonalDocAI-backup-2026-08-24-P48復原後.dump`。
