# Phase 66：Compose 加 redis 與 worker（＋文件更新＋真容器煙霧）＋ ★ 閘門 G2

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。想「順便加 Flower 監控」「順便給 Redis 設密碼與 TLS」「順便開三個 worker」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 在**既有的** `compose.yaml` 加上 `redis` 與 `worker` 兩個服務（不新開一份 compose）、在 `compose.dev.yaml` 幫 worker 掛上原始碼、把 `LAUNCH.md` 與 `CLAUDE.md` 的指令區改成新的現實，最後跑一次**真容器煙霧**——切到雲端上傳一張照片，在 worker 的 log 裡看到 `backend=cloud`，照片最後出現在待決定。做完就交給產品負責人跑 **★ 閘門 G2**。

> ⚠ **2026-08-26 校準：本檔引用的「契約備忘」是規劃階段的工作文件、未入庫**（與 phase-57／58
> 定稿的註記同一件事）。本 phase 需要的內容已全部逐字內嵌在 §4 各步驟，
> 驗收一律以本檔內嵌內容為準，不依賴那份文件。

**為什麼要做這個：**

Phase 65 已經把程式碼全部寫好了：`POST /photos` 會把 job 丟進 Redis、`ingest_task` 會把它撿起來做。**但現在既沒有 Redis、也沒有 worker。** 用瀏覽器上傳一張照片，`app` 會在入列那一步撞上「連不到 redis:6379」，直接 500。

這個 phase 就是把那兩個容器建起來，並且把「怎麼啟動、怎麼看 log、改了程式碼要重啟哪一個」寫進兩份操作手冊——因為 **Celery 沒有 uvicorn 那種 `--reload`**，開發時最容易踩的坑就是「HTTP 已經是新碼、分析還是舊碼」。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 服務（service） | `compose.yaml` 裡 `services:` 底下的一個項目。一個服務通常對應一個容器。目前有 `db`、`app`，本 phase 加成四個 |
| named volume（具名磁碟區） | Docker 幫你管理的一塊儲存空間，有名字（例如 `personaldocai_pgdata`）。容器砍掉重建，裡面的資料還在。位置由 Docker 決定，你不會用 Finder 去翻它 |
| bind-mount（目錄掛載） | 把 Mac 上的某個資料夾「掛」進容器裡，兩邊看到的是**同一份檔案**。`./data`、`./certs`、`./.env` 都是這種 |
| healthcheck（健康檢查） | Compose 定期對容器跑一個小指令，通過才把它標成 `healthy`。`db` 用 `pg_isready`，`redis` 用 `redis-cli ping` |
| `depends_on: service_healthy` | 「等那個服務變成 healthy 才啟動我」。**注意：只在 `docker compose up` 時生效**，重開機時容器是 Docker daemon 直接拉起來的，不會等 |
| AOF（append-only file，逐筆追加檔） | Redis 的一種存檔方式：把每一個「改到資料」的命令逐筆寫進磁碟，重開時重播一次就還原。不開的話 Redis 只活在記憶體，容器一重開進度就沒了 |
| `restart: unless-stopped` | 「除非你自己 `stop` 過，否則我掛了就自動回來、開機也自動回來」 |
| `restart: "no"` | 「不要自動回來」。開發用的 overlay 一律用它，免得開機把開發版拉起來 |
| overlay（覆寫檔） | 疊在主設定檔上面的第二份 yaml。`docker compose -f A -f B`，**後面那份蓋前面那份** |
| prefork pool | Celery 預設的執行方式：主行程 fork 出 N 個子行程做事。`--concurrency=2` ＝ 2 個子行程 |
| 映像（image） | 「容器的模子」。`worker` 與 `app` 用**同一個模子**，只是啟動指令不同 |

---

## 1. 對應 design5.md 章節

- **§7「Docker 與啟動」整節**：架構圖、`redis`／`worker` 兩個服務的每一條要求、`app` 要加什麼、`compose.dev.yaml` 要加什麼、啟動指令、「測試時用雲端 AI」、「刻意不進 Compose」。
- **D5**（Redis ＋ Celery）、**D6**（最多 2 個 worker、測試手動煙霧先切雲端）。
- **D14／§4.5**（AI 開關快照：worker 吃的是入列快照，不是「切了之後才影響已經在跑的任務」）。
- **§11「會動到的檔」**：`compose.yaml`／`compose.dev.yaml`（加 `redis`、`worker`）、`LAUNCH.md`／`CLAUDE.md` 指令區（啟動／restart worker／雲端煙霧）。
- **§12「階段乙」五條驗收** ＝ 本 phase 結尾的 **★ G2**。
- **§13 風險**：「`--reload` 救不了 worker」「Redis volume 不是正式庫」「host `.venv` 與映像套件分岔」。
- 契約備忘 **§3.5**（worker 啟動指令逐字）、**§10**（★G2 是**人**的閘門）。

---

## 2. 前置條件

**依賴：Phase 65 全部做完。** 開工前實查：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① Phase 65 的東西都在
ls -l app/celery_app.py
grep -n "CELERY_BROKER_URL" app/core/config.py
grep -n "^celery\|^redis" requirements.txt

# ② 測試全綠、而且死埠實證通過（不通過就代表 pytest 會連真 Redis，別往下走）
pytest -q                                              # 2026-08-26 校準：Phase 65 做完應為
                                                       # 507 passed ＋ 0 skipped
                                                       #（Phase 64 收工實測 493 ＋ 65 的 14 顆）
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q      # 顆數要跟上一條一模一樣

# ③ Docker Desktop 開著、現有兩個服務活著
docker version            # Client／Server 兩段都要有輸出，只有 Client ＝ Docker Desktop 沒開
docker compose ps         # db 是 Up (healthy)、app 是 Up

# ④ Ollama 開著（worker 要連它）
curl -s http://localhost:11434/api/tags | head -c 100

# ⑤ 憑證還在（app 用 HTTPS 起，沒憑證會一直重啟）
ls -l certs/cert.pem certs/key.pem

# ⑥ 雲端 key 有填（本 phase 的煙霧一定要切雲端）
grep -c "^OLLAMA_API_KEY=." .env      # 預期印出 1
```

⚠ 所有 `docker compose …` 指令都要在專案根目錄 `/Users/linjunting/personalDocAI` 執行——Compose 是靠「當前目錄有沒有 `compose.yaml`」找設定檔的。

⚠ **絕對不要同時跑兩份 pytest**（會互相 `TRUNCATE` 測試庫，症狀是大量看似隨機的 404 與 `NoneType` 錯誤）。

---

## 3. 範圍

### 做

1. `compose.yaml` 加 `redis` 服務（AOF、named volume、healthcheck、只綁 `127.0.0.1`）。
2. `compose.yaml` 加 `worker` 服務（同一份 app 映像、`--concurrency=2`、無 `--reload`）。
3. `compose.yaml` 的 `app` 加 `CELERY_BROKER_URL` 與 `depends_on: redis healthy`。
4. `compose.dev.yaml` 加 `worker`（bind-mount `./app`、`restart: "no"`）。
5. 重建映像、四個服務一起起來。
6. **真容器煙霧**：切雲端 → 上傳一張 → worker log `backend=cloud` → 照片進待決定。
7. 更新 `LAUNCH.md` 與 `CLAUDE.md` 指令區（完整段落原文見 §4.8／§4.9）。
8. 交出 **★ 閘門 G2** 的五條給產品負責人。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 新開一份 `compose.queue.yaml` 之類的檔案 | design5 §7 第一句明文：「在既有 `compose.yaml`（`db`＋`app`）加上兩個服務。**不要**新開一份 compose 取代常駐檔」 |
| 把 Redis 發佈到 `0.0.0.0` | design5 §3「不做」與 §7 明文。Redis 預設**沒有密碼**，發佈到 `0.0.0.0` 等於把它交給同一個 Wi-Fi 上的所有人 |
| 幫 Redis 設密碼／TLS | 埠只綁 `127.0.0.1`，同一個 Wi-Fi 打不到；side project 不多做（與 `db` 的 `POSTGRES_HOST_AUTH_METHOD: trust` 同一套理由） |
| 給 worker `--reload`，或用 `watchmedo auto-restart` 之類的外掛 | design5 §7 明文「**不要** `--reload`。Celery 不會跟 uvicorn 一樣盯檔」。改碼就 `restart worker`，一行指令的事 |
| 開 3 個以上 worker，或把 `--concurrency` 調大 | design5 D6：產品負責人上限 2。本機 gemma4 看圖 64〜88 秒，並行會把機器壓垮（CLAUDE.md 記載 Phase 48 已踩過） |
| 幫 worker 掛 `./certs` | worker 不聽 HTTPS，用不到憑證（design5 §7 明文「憑證不必」）。少掛一個就少一個 mount 打錯的機會 |
| 為 worker 另寫一份 Dockerfile | design5 §7 明文「**同一份** app 映像」。差別只在啟動指令 |
| 把 `compose.dev.yaml` 設成開機預設，或在它裡面寫 `restart: unless-stopped` | 沿用 design4 §8.10／Phase 49 的既有規則：開機拉起的行程不准帶開發設定 |
| 把 Ollama 或 pytest 搬進 Compose | design5 §7 最後一段「刻意不進 Compose」。pytest 仍在 host 跑、連 `127.0.0.1:5433` |
| `docker compose down`／`down -v` | `down -v` ＝ 刪正式庫 volume。停服務一律 `docker compose stop`（§7 陷阱 9） |
| 改任何 `app/` 底下的程式碼 | 本 phase 零程式碼變更。真的發現 bug 就記下來，回頭改 Phase 65 那幾個檔並重跑 `pytest -q` |

---

## 4. 實作步驟

### 4.1 `compose.yaml` 加 `redis` 服務

- [ ] 在 `services:` 底下、`db:` 那一段**之後**（`app:` 之前）插入：

```yaml
  redis:
    # 官方 Redis 7 映像。alpine ＝ 用 Alpine Linux 當底，映像小很多（幾十 MB）。
    # 它同時扮演兩個角色：① Celery 的 broker（任務排隊的地方）
    #                      ② 我們自己的 JobStore（進度列的資料）
    # 兩者的 key 完全分得開：我們的都有 ingest: 前綴（app/services/ingest_job_store.py）。
    image: redis:7-alpine
    # ★ 覆寫啟動指令，把 AOF 打開。
    #   AOF（append-only file，逐筆追加檔）＝ Redis 把每一個「改到資料」的命令
    #   逐筆寫進磁碟，重開時重播一次就還原。
    #   不開的話 Redis 只活在記憶體：重開 Docker ＝ 進行中的任務與失敗列全部消失
    #   （design5.md §7 明文要求 appendonly yes）。
    #   官方 Redis 持久化說明：https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/
    #  （官方映像頁的持久化範例也是同一招——把設定當參數接在 redis-server 後面，
    #    例如 `redis-server --save 60 1`；我們接的是 --appendonly yes。）
    # ⚠ "yes" 的引號不能拿掉：YAML 1.1 的解析器會把沒引號的 yes 讀成布林值 true，
    #   而 command 清單只能是字串——加引號永遠安全。
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      # ★ 一定要有 127.0.0.1: 前綴（design5.md §7：「不發佈到 0.0.0.0。
      #   若為了 host 除錯要發佈，只綁 127.0.0.1:6379」）。
      #   Redis 預設沒有密碼——發佈到 0.0.0.0 等於把它交給同一個 Wi-Fi 上的所有人。
      #   這一行純粹是為了在 Mac 上用 redis-cli 除錯；app 與 worker 走的是 Compose
      #   內部網路（服務名 redis），不靠這個埠。
      - "127.0.0.1:6379:6379"
    volumes:
      # named volume：AOF 檔住這裡。官方映像的資料目錄就是 /data
      # （Docker Hub 官方說明：「data is stored in the VOLUME /data」）
      - redisdata:/data
    healthcheck:
      # redis-cli ping 回 PONG ＝ 真的可以收命令了。
      # app 與 worker 的 depends_on 就是在等這一格變綠。
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped
```

- [ ] 檔案**最後面**的 `volumes:` 區塊加一行（`pgdata:` 那一行不動）：

```yaml
volumes:
  pgdata:
  # 增量五（design5.md §7）：Redis 的 AOF 檔。實際名字會是 personaldocai_redisdata
  # （前面的 name: personaldocai ＋ 這裡的 redisdata）。
  # ⚠ 它**不是**正式庫：丟了只丟「進度列與失敗列」，照片正本仍在 pgdata ＋ data/。
  #   詳細差別見 CLAUDE.md 指令區的「⛔ 會弄丟資料的操作」。
  redisdata:
```

### 4.2 `compose.yaml` 加 `worker` 服務

- [ ] 在 `app:` 那一段**之後**插入：

```yaml
  worker:
    # ★ 與 app **同一份映像**（design5.md §7：「Dockerfile 不必為 worker 另寫一份」）。
    #   build 與 image 兩行都寫、而且 image 名字與 app 相同，Compose 就會把兩個服務
    #   指向同一個 tag——第二次 build 全部命中快取，幾乎不花時間。
    #   （只寫 image 不寫 build 的話，映像還不存在時 Compose 會跑去 Docker Hub 拉
    #     一個叫 personaldocai-app 的公開映像然後失敗。）
    build: .
    image: personaldocai-app
    # ★ 啟動指令（契約 §3.5 逐字）。用陣列寫法，不會被 shell 拆錯字。
    #   -A app.celery_app.celery_app ＝ 模組路徑 app/celery_app.py ＋ 裡面那個變數名
    #   --concurrency=2 ＝ 同時開 2 個子行程做事（design5.md D6，上限就是 2）
    #   **沒有 --reload**：Celery 不會盯檔案，改了 Python 要 restart（design5.md §7、§13）
    command:
      - celery
      - -A
      - app.celery_app.celery_app
      - worker
      - --loglevel=info
      - --concurrency=2
    environment:
      # 與 app 完全相同的兩條（worker 也要寫資料庫、也要呼叫 Ollama）
      DATABASE_URL: postgresql://postgres@db:5432/PersonalDocAI
      OLLAMA_BASE_URL: http://host.docker.internal:11434
      # ★ 佇列位址。redis 是 Compose 的服務名，6379 是容器內的埠（不是 Mac 上那個）
      CELERY_BROKER_URL: redis://redis:6379/0
    volumes:
      # 要讀 staging、要寫原圖與縮圖，所以 data 一定要掛
      - ./data:/app/data
      # 模型名稱、OLLAMA_API_KEY…（連線字串由上面 environment 覆蓋）
      - ./.env:/app/.env
      # ★ 刻意**不掛** ./certs：worker 不聽 HTTPS，用不到憑證（design5.md §7 明文）
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    # ★ worker 沒有 ports：它不聽任何埠，只主動去 Redis 拿工作
```

### 4.3 `compose.yaml` 的 `app` 加兩樣東西

- [ ] `app` 的 `environment` **加一行**（原本兩行不動）：

```yaml
      # ★ 增量五（design5.md §7）：入列要打到 redis 這個服務。
      #   app 只負責「寫進去」，實際做事的是 worker。
      CELERY_BROKER_URL: redis://redis:6379/0
```

- [ ] `app` 的 `depends_on` **加一段**（`db` 那段不動）：

```yaml
      redis:
        # ★ 沒有 Redis 就沒辦法入列——POST /photos 會在入列那一步炸成 500
        #   （design5.md §8 錯誤表第 8 列）。等它 healthy 再起 app。
        condition: service_healthy
```

- [ ] `app` 的 `build: .` 那一行**下面加一行** `image: personaldocai-app`：

```yaml
    build: .                       # 用同目錄的 Dockerfile 蓋映像
    image: personaldocai-app       # ★ 明寫映像名，worker 才指得到同一份（§4.2）
```

  （這個名字就是 Compose 原本自動取的名字＝專案名 `personaldocai` ＋ 服務名 `app`，
  所以 `docker compose images app` 的 REPOSITORY 欄不會改變，phase-48 §6 那條驗收仍然成立。）

### 4.4 `compose.dev.yaml` 加 `worker`

```text
┌─ ⚠️⚠️ 最重要的一條：改 Python 之後**必須** restart worker ⚠️⚠️ ─────
│
│ uvicorn 的 `--reload` 會盯著檔案、存檔就自己重載。**Celery 沒有這種東西。**
│ design5 §7 明文：「改 Python 後 **必須** `docker compose … restart worker`
│ （Celery 沒有 uvicorn 那種 reload）」；§13 又講了一次：
│ 「`--reload` 救不了 worker。改 app/ 後開發模式記得 restart worker，
│   否則會出現『HTTP 已是新碼、分析還是舊碼』。」
│
│ 這個坑最難查的地方在於**它不報錯**：你改了 run_ingest_job 的某個規則，
│ 上傳測試，HTTP 行為（202、job 建出來）全部是新的，但分析結果還是舊行為。
│ 你會以為是自己改錯了，回去看程式碼——程式碼明明是對的。
│
│ 指令（開發模式下，兩份 yaml 都要帶）：
│     docker compose -f compose.yaml -f compose.dev.yaml restart worker
│
│ **那 bind-mount `./app` 還有什麼用？** 有用：restart 只花 2 秒，
│ 不必重新 build 映像（build 要重裝套件，一分鐘起跳）。
│ 沒有 bind-mount 的話，改一行字就要重建整個映像。
└──────────────────────────────────────────────────────────────────
```

- [ ] 在 `compose.dev.yaml` 的 `app:` 那一段**之後**加：

```yaml
  worker:
    volumes:
      - ./app:/app/app          # 原始碼；沒掛的話 restart 也只會重跑映像裡的舊碼
      - ./data:/app/data        # 與常駐相同
      - ./.env:/app/.env
    restart: "no"               # 開發用 -d 仍不要 unless-stopped，免得開機把開發版拉起來
    # ★ 刻意**不覆寫** command：worker 的啟動指令兩種模式完全一樣
    #   （Celery 沒有 --reload 可加）。改了 Python 要自己 restart worker。
```

> **合併規則提醒（phase-49 §4.1 已經解釋過一次）**：`command`／`restart` 這種**單值**設定，
> 後面那份會把前面整個換掉；`volumes` 這種**清單**設定，是以「容器內的掛載路徑」逐項合併的。
> 官方規則：<https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/>

### 4.5 先檢查 yaml（不啟動任何東西）

- [ ] 常駐那份：

```bash
docker compose config
```

  預期：印出合併後的完整設定、沒有錯誤訊息。（`config` 會把 `command` 展成
  一行一項的清單、鍵照字母排序——長相跟你寫的不同是正常的，內容對得上就好。）逐項確認：
  - 有 `db`、`redis`、`app`、`worker` **四個**服務（`config` 輸出照字母排：app、db、redis、worker）
  - `redis` 的 `ports` 是 `127.0.0.1:6379:6379`（**有** `127.0.0.1:` 前綴）
  - `redis` 的 `command` 是 `redis-server --appendonly yes`（展成三個清單項）
  - `worker` 的 `command` 看得到 `--concurrency=2`，而且**沒有** `--reload`
  - `worker` 的 `volumes` 只有 `data` 與 `.env`（**沒有** `certs`）
  - `app` 與 `worker` 的 `environment` 都有 `CELERY_BROKER_URL: redis://redis:6379/0`
  - 最下面的 `volumes` 有 `pgdata` 與 `redisdata`

- [ ] 開發那份（**`compose.dev.yaml` 一定放後面**）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml config
```

  預期：`app` 的 `command` 有 `--reload`、`restart` 是 `"no"`；
  `worker` 的 `command` **仍然沒有** `--reload`、`restart` 是 `"no"`、`volumes` 多了 `./app`。

### 4.6 建映像並起來

```text
┌─ ⚠️ `up -d` **不會**重建映像 ─────────────────────────────────────
│ Phase 65 改了 requirements.txt（多了 celery 與 redis），而套件是在 build 那一刻
│ 裝進映像的。只打 `up -d` 的話，worker 容器會用**舊映像**啟動，然後立刻死掉：
│     ModuleNotFoundError: No module named 'celery'
│ 而 `restart: unless-stopped` 會讓它一直重試 → `docker compose ps` 看到它在
│ Restarting 之間跳動。**一定要帶 `--build`。**
└──────────────────────────────────────────────────────────────────
```

- [ ] 建映像並啟動四個服務：

```bash
docker compose -f compose.yaml up -d --build
```

  第一次會花一兩分鐘（重裝套件層 ＋ 拉 `redis:7-alpine`）。
  `db` 不會被重來一次（設定沒改），資料住在 `pgdata` volume 裡也不會丟。

- [ ] 看狀態（**`--no-trunc` 不能省**，不加的話 COMMAND 欄只印開頭 20 個字左右，
      `--concurrency=2` 在最後面根本不會顯示）：

```bash
docker compose ps --no-trunc
```

  預期四列：
  - `db` → `Up … (healthy)`，PORTS `127.0.0.1:5433->5432/tcp`
  - `redis` → `Up … (healthy)`，PORTS `127.0.0.1:6379->6379/tcp`，COMMAND 有 `--appendonly yes`
  - `app` → `Up …`，PORTS `0.0.0.0:8000->8000/tcp`，COMMAND **沒有** `--reload`
  - `worker` → `Up …`，PORTS 空的，COMMAND 有 `--concurrency=2`

- [ ] Redis 真的活著：

```bash
docker compose exec redis redis-cli ping
```

  預期：`PONG`

- [ ] **看 worker 的啟動畫面**（這是「worker 到底有沒有正常起來」最直接的證據）：

```bash
docker compose logs worker | head -40
```

  預期看到 Celery 的啟動橫幅，裡面至少有這四樣：

```text
- ** ---------- [config]
- ** ---------- .> transport:   redis://redis:6379/0
- ** ---------- .> concurrency: 2 (prefork)
[tasks]
  . personaldocai.ingest
...
celery@<容器 id> ready.
```

  - `transport` 是我們設的 broker
  - `concurrency: 2 (prefork)` ＝ D6 的兩個子行程
  - `[tasks]` 底下**一定要有** `personaldocai.ingest`（沒有的話 `-A` 指錯了，
    或 `app/celery_app.py` 匯入時就炸了——往上捲看有沒有 traceback）
  - `ready.` ＝ 已經在等工作了（`worker_ready` 訊號就是在這前後發的，
    所以同一段啟動輸出裡——不保證在 `ready.` 的哪一邊——還會看到一行
    `staging 掃把（worker 啟動）：清掉 0 個過期暫存檔`。
    **這一行同時是一條驗收**：它證明 Phase 65 在 `app/celery_app.py` 接的
    `worker_ready` 掃把（design5 §4.1「worker／app 啟動時掃 staging」的 worker 那一頭）
    在真容器裡真的有跑。看不到它＝接線沒生效，回 Phase 65 §4.6 查）

- [ ] 服務活著：

```bash
curl -k https://127.0.0.1:8000/health
```

  預期：`{"status":"ok"}`

### 4.7 真容器煙霧（design5 §12「階段乙」）

```text
┌─ ⚠️⚠️ 這一節**一定要切到雲端**再上傳 ⚠️⚠️ ─────────────────────────
│
│ design5 D6 明文：「測試手動煙霧時先把頁首 AI 開關切到**雲端**」。
│ 理由不是偏好，是這台機器的實測數字：
│   本機 gemma4 看一張圖要 **64〜88 秒**（CLAUDE.md 記載），
│   而 worker 是 `--concurrency=2` ＝ **可以同時看兩張**。
│   Phase 48 已經踩過一次：上傳與詢問同時打，把 db container 壓垮，
│   postmaster 花 2 分鐘才殺得掉子行程、WAL 自動復原（資料沒丟，但整台機器停擺）。
│   雲端同一份 prompt 實測 **1.9 秒**。
│
│ 而且切雲端還順便驗到 D14：worker 讀不到頁首那顆開關，
│ 它吃的是**入列當下寫進 job 的快照**。log 印出 backend=cloud 就是快照真的傳到了。
│
│ ★ 順序不能顛倒：**先切雲端，再上傳。** 已經在佇列裡的任務不會因為你中途切回本機
│   而改道（design5 §7 最後一段）——反過來也一樣，先傳再切是沒用的。
└──────────────────────────────────────────────────────────────────
```

- [ ] **① 切到雲端。** 用瀏覽器開 `https://127.0.0.1:8000/ui/upload.html`（**是 https**；
      自簽憑證跳警告就選「繼續前往」），點頁首那顆「AI 模型：本機｜雲端」開關到**雲端**。
      指令列版本（等價）：

```bash
curl -k -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
```

  預期：`{"backend":"cloud","cloud_configured":true}`。
  回 **422** 的話是 `.env` 沒填 `OLLAMA_API_KEY`（回 §2 第 ⑥ 步）。

- [ ] **② 開著 worker 的 log**（另開一個終端機視窗）：

```bash
docker compose logs -f worker
```

  `-f` ＝跟著看；`Ctrl+C` 只離開 log，容器繼續跑。

- [ ] **③ 上傳一張真照片**（瀏覽器上傳頁選一張 JPEG／PNG）。
      預期畫面：**立刻**回來（202），不是等一分鐘。

- [ ] **④ 在 worker 的 log 看到這幾行**（Phase 41〜43 的計時 log 格式）：

```text
AI 開始 kind=vlm backend=cloud model=gemma4
AI 結束 kind=vlm backend=cloud model=gemma4 elapsed_s=2.0 ok=true understood=true text_chars=… …
AI 開始 kind=embed backend=local model=bge-m3
AI 結束 kind=embed backend=local model=bge-m3 elapsed_s=0.4 ok=true
job <32 位 job_id> 入庫完成：photo_id=…（先進「未分類(收件箱)」，等使用者到待決定頁歸類）
```

  （最後那行的格式是 Phase 59 `_run_image_job` 收尾時印的
  `job %s 入庫完成：photo_id=%d（先進「%s」，等使用者到待決定頁歸類）`——
  不是舊同步路徑的「照片已入庫」。）

  三個重點：
  - `kind=vlm` 那一組是 **`backend=cloud`** ← **★G2 的第 5 條就是這一行**
  - `kind=embed` 那一組是 **`backend=local`** ← **這是對的**，向量永遠本機、不歸開關管
  - 這些 log 出現在 **worker**，不在 app（`docker compose logs app` 裡不會有 `kind=vlm`）

  ⚠ 若看到的是 `backend=local`：程式功能其實是好的（照片會入庫），壞的是 log 或快照。
  回 Phase 65 §4.10 用 `grep -n -A3 'log_ai("vlm"' app/services/ingest_job.py`
  確認有帶 `target=vlm_service.vlm_timing_target(vlm)`。改完要 `docker compose up -d --build`
  （常駐模式的程式在映像裡）。

- [ ] **⑤ 照片真的進了待決定：** 開 `https://127.0.0.1:8000/ui/pending.html`，
      看得到剛上傳那張的縮圖；頂欄的「待決定（N）」比上傳前多 1。

- [ ] **⑥ 成功＝job 被刪掉**（驗 design5 §4.3 的核心語意）：

```bash
docker compose exec redis redis-cli smembers ingest:open
```

  預期：`(empty array)`——成功的 job 已經被 `delete()` 掉了，所以進度面板不會留下它。

- [ ] **⑦ staging 也清乾淨了：**

```bash
ls -la data/staging
```

  預期：空的（只有 `.` 與 `..`）。

- [ ] **⑧ 失敗路徑順手看一眼**（不是 G2 必要項，但很值得做一次）：
      上傳一個**內容壞掉但副檔名是 .png** 的檔（例如 `printf 'not an image' > /tmp/壞檔.png`），
      看 worker log 出現三次 `kind=vlm … ok=false`，然後：

```bash
docker compose exec redis redis-cli smembers ingest:open   # 應該看得到那筆失敗的 job_id
ls -la data/staging                                        # 應該是空的（失敗也刪 staging）
```

  進度面板上會留下一列紅色失敗、可以按 × 關掉（Phase 67 才會有面板；
  現在可以用 `curl -k https://127.0.0.1:8000/ingest-jobs` 直接看 JSON）。

- [ ] **⑨ 重開容器，進度列還在**（驗 AOF 真的有開）：

```bash
docker compose restart redis
sleep 5
docker compose exec redis redis-cli smembers ingest:open
```

  預期：⑧ 那筆失敗的 job_id **還在**。空的話代表 `appendonly yes` 沒生效，回 §4.1 檢查 `command`。

- [ ] **⑩ 把開關切回本機**（收工前的禮貌；不切也沒關係，重啟 app 一律回本機）：

```bash
curl -k -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'
```

### 4.8 更新 `LAUNCH.md`

以下四段是**可以直接貼上去的原文**（其餘章節不動）。

> 📌 **2026-08-26 校準（順手一起改，不另立步驟）：** `LAUNCH.md` §6「跑測試」那行註解
> 現在寫的是 `pytest -q  # 預期 405 passed`——**那個數字早就過期**（Phase 64 收工實測 493，
> Phase 65 做完是 507）。既然本 phase 本來就要動 `LAUNCH.md`，把它一併改成當下實查值；
> 這一處不列進下面的 ①〜⑤ 編號，§6 驗收清單仍寫「五處」。

- [ ] **①「§3 啟動與停止」整段換成**（外層是四個反引號，這樣裡面的三反引號才不會提早收尾；
      貼進 `LAUNCH.md` 時只貼**中間的內容**，不要把最外面那兩行四反引號也貼進去）：

````markdown
## 3. 啟動與停止

```bash
cd /Users/linjunting/personalDocAI

# 啟動（常駐模式；一次拉起 db、redis、app、worker 四個服務）
docker compose -f compose.yaml up -d

# 停止
docker compose stop

# 看狀態（四個服務都要在；db 與 redis 要是 healthy）
docker compose ps

# 看 log（app 是網頁與 API，worker 是背景分析照片的那個）
docker compose logs -f app worker   # Ctrl+C 只離開 log，容器繼續跑
docker compose logs -f worker       # 只看分析進度時用這個
```

⚠️ 用 `docker compose stop` 停掉之後，**重開機不會自己回來**，要手動 `up -d`。

⚠️ **改了 `requirements.txt` 之後要 `--build`**，否則新套件不會進映像：
`docker compose -f compose.yaml up -d --build`
````

- [ ] **②「§4 開發模式（熱重載）」**：先把該節開頭那句
      「改 `app/` 底下的程式碼存檔後自動生效。」改成
      「改 `app/` 底下的程式碼存檔後 **app** 自動生效；**worker 不會**（見下方表格第一列）。」
      ——增量五之後那句話只對一半，不改的話新手第一眼就被騙。
      再把該節的指令區與表格換成（同樣，最外面那兩行四反引號不要貼進去）：

````markdown
```bash
# 常駐 → 開發
docker compose -f compose.yaml stop app worker
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker

# 開發 → 常駐
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d

# 現在是哪一種模式（看 app 的 COMMAND 有沒有 --reload）
docker compose ps --no-trunc
```

`--no-trunc` 不能省，不加的話 COMMAND 會被截斷、看不到結尾的 `--reload`
（worker 的 `--concurrency=2` 同理）。

⚠️ **`--reload` 只救得了 app，救不了 worker。** Celery 不會盯檔案。
改了 `app/` 底下的 Python 之後，分析那一段還是舊碼，而且**不會報錯**——
你會看到「HTTP 行為已經是新的、照片分析結果卻是舊的」。一定要：

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

**存檔沒反應的五種情況：**

| 改了什麼 | 怎麼辦 |
|---|---|
| `app/` 底下的 `.py`，但**分析行為**沒變 | `docker compose -f compose.yaml -f compose.dev.yaml restart worker` |
| `.env` | `docker compose -f compose.yaml -f compose.dev.yaml restart app worker` |
| `requirements.txt` | `docker compose build app` 再 `up -d`（worker 用同一份映像，一起更新） |
| `certs/` | 同 `.env`，`restart app`（worker 不用憑證） |
| 正在配對鏡頭 | reload 會清空 token，重產 QR 重掃 |

⚠️ 真機鏡頭驗收一律用**常駐模式**（開發模式每存一次檔配對就失效）。
````

- [ ] **③「§9 排錯」表格加四列：**

```markdown
| 上傳回 202 但照片永遠不出現 | worker 沒起來／掛了 | `docker compose ps` 看 worker 在不在；`docker compose logs worker --tail 50` 看有沒有 traceback |
| 上傳直接回 500 | redis 沒起來或還沒 healthy | `docker compose ps` 看 redis；`docker compose exec redis redis-cli ping` 要回 PONG |
| 改了程式碼但分析行為沒變 | Celery 沒有 `--reload` | `docker compose -f compose.yaml -f compose.dev.yaml restart worker` |
| worker 一直 Restarting | 映像沒重建（缺 celery 套件） | `docker compose logs worker` 若是 `ModuleNotFoundError: No module named 'celery'` → `docker compose up -d --build` |
```

  同節的「看 log」區塊加三行，並把既有 `docker compose logs app | grep "kind="` 那行的
  註解從「AI 計時」改成「詢問流程的 AI 計時（kind=vlm／入庫的 kind=embed 在 worker 那邊）」
  ——增量五之後看圖搬進 worker，舊註解會讓人在 app 的 log 裡白找：

```bash
docker compose logs worker --tail 50                # 分析在做什麼
docker compose logs worker | grep "kind=vlm"        # 每張圖看多久、走本機還是雲端
docker compose exec redis redis-cli smembers ingest:open   # 現在還有哪些 job 沒結束
```

- [ ] **④「§10 絕對不要做的事」表格加一列，並在表格下方加一段：**

```markdown
| `docker volume rm personaldocai_redisdata` | 丟掉進度列與失敗列（**不是**正式庫，見下） |
```

```markdown
**`pgdata` 與 `redisdata` 差很多，不要搞混：**

| volume | 裡面是什麼 | 丟了會怎樣 |
|---|---|---|
| `personaldocai_pgdata` | **正式庫**：照片列、資料夾、實體、待辦、向量 | 災難。照片全部消失，只能從備份還原 |
| `personaldocai_redisdata` | 進度列、失敗列、還沒做完的任務 | 只丟「還沒分析完的那幾張」。已入庫的照片一張都不會少（正本在 pgdata ＋ `data/photos`）。那幾張要重新上傳；它們留在 `data/staging` 的暫存檔會由 24 小時掃把自動清掉 |

所以 `down -v` 仍然絕對禁止（它會**兩個一起刪**），但如果哪天真的只需要清 Redis，
`docker volume rm personaldocai_redisdata` 是可以接受的損失——**前提是當下沒有任務在跑**。
```

- [ ] **⑤「附錄：目前架構」的圖換成 §5 的那一張**——整個 `text` 區塊都貼
      （含「六條 TCP／HTTPS 線」與「開發模式只差三件事」那兩段）。§5 那張已含
      原附錄的每一條資訊：postgresql@17 後悔藥那行、手機 WebRTC 直連那行都在，
      不會因為換圖而弄丟。

### 4.9 更新 `CLAUDE.md` 指令區

以下三段是**可以直接貼上去的原文**。

- [ ] **①「常駐／開發」那幾條指令換成：**

```bash
# 常駐（開機也是用這一份自動拉起；一次四個服務 db／redis／app／worker，沒有 --reload）
docker compose -f compose.yaml up -d

# ⚠ 改過 requirements.txt 之後一定要帶 --build，否則新套件不會進映像
#   （worker 會噴 ModuleNotFoundError: No module named 'celery' 然後一直重啟）
docker compose -f compose.yaml up -d --build

# 日常開發（熱重載；兩份疊加，compose.dev.yaml 一定放後面）
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
#   logs -f ＝跟著看，Ctrl+C 只離開 log，容器繼續跑
#   worker ＝ 背景分析照片的那個行程；kind=vlm／kind=embed 的計時 log 在它那邊，不在 app

# 現在跑的是哪一種：看 COMMAND 欄（app 有沒有 --reload、worker 有沒有 --concurrency=2）
# --no-trunc 不能省：不加的話 COMMAND 只印開頭 20 個字左右，結尾那些旗標根本不會顯示
docker compose ps --no-trunc

# 切換（切換當下 app 一定重啟一次 → 鏡頭 token 清空、QR 要重產）
docker compose -f compose.yaml stop app worker                # 常駐 → 開發（第一步）
docker compose -f compose.yaml -f compose.dev.yaml up -d      # 常駐 → 開發（第二步）
docker compose -f compose.yaml -f compose.dev.yaml stop       # 開發 → 常駐（第一步）
docker compose -f compose.yaml up -d                          # 開發 → 常駐（第二步）
```

- [ ] **②「改了東西要怎麼生效」那一段整段換成下面這樣**（不是只加一列——
      `.env` 那列的 restart 對象要加上 `worker`、requirements 與 certs 兩列的說明也跟著改；
      原本那段 ⚠「DATABASE_URL 與 OLLAMA_BASE_URL 由 compose 覆蓋」的提醒**必須保留**，
      而且現在多了 `CELERY_BROKER_URL`、多了 worker——照下面的版本更新，不要弄丟）：

```bash
# 改了東西要怎麼生效（--reload 救不了的五種情況）
#   改 app/ 的 .py   → **app 會自己 reload，但 worker 不會**（Celery 沒有這種東西）。
#                      症狀：HTTP 行為已是新碼、照片分析卻還是舊行為，而且完全不報錯。
#                      docker compose -f compose.yaml -f compose.dev.yaml restart worker
#   改 .env          → docker compose -f compose.yaml -f compose.dev.yaml restart app worker
#                      ⚠ 但 DATABASE_URL／OLLAMA_BASE_URL／CELERY_BROKER_URL 這三個
#                        由 compose.yaml 的 environment 覆蓋（app 與 worker 都是），
#                        在容器裡改 .env 的這三行怎麼 restart 都不會變（刻意的）
#   改 requirements  → docker compose build app，再 up -d（worker 用同一份映像，一起更新）
#   改 certs/        → restart app（worker 不聽 HTTPS，用不到憑證）
#   正在配對鏡頭     → reload ＝ token 清空，重產 QR 重掃一次
```

- [ ] **③「⛔ 會弄丟正式庫的四種操作」那一段結尾加一段**（原本四條不動）：

```bash
# ── 增量五新增：第二個 volume `personaldocai_redisdata`（Redis 的 AOF）──
#   ⚠ 它**不是**正式庫，兩者差很多：
#     personaldocai_pgdata     ← 正式庫（照片列、資料夾、實體、待辦、向量）。丟了＝災難
#     personaldocai_redisdata  ← 進度列、失敗列、還沒做完的任務。丟了只丟「還沒分析完
#                                的那幾張」，已入庫的照片一張都不會少（正本在 pgdata ＋
#                                data/photos）。那幾張重新上傳即可；它們在 data/staging
#                                的暫存檔會由 24 小時掃把自動清掉
#   所以 `down -v` 仍然絕對禁止（會兩個一起刪）；但真的只需要清 Redis 時，
#   `docker volume rm personaldocai_redisdata` 是可接受的損失——**前提是當下沒有任務在跑**。
#
# 備份不必管 Redis：日常備份（下面那兩種寫法）只倒 Postgres，
# 因為 Redis 裡沒有任何「丟了就再也拿不回來」的東西。
```

- [ ] **④ 現況段**（檔案最前面那一大段）補上一句增量五階段乙的成果：
      Docker 從兩個服務變成**四個**（db／redis／app／worker）、worker 是 `--concurrency=2`、
      `POST /photos` 已是 202、端點 20→22、`pytest -q` 的顆數更新成當下實查值
      （2026-08-26 校準：現況段目前寫的是「405 passed＋0 skipped」，Phase 65 做完應為 **507**）。

### 4.10 ★ 閘門 G2

```text
┌─ ★ 閘門 G2（design5.md §12「階段乙」；契約備忘 §10）──────────────
│
│ 下面五條是 **design5 §12 的原文**，由**產品負責人**逐條確認。
│ **G2 是「人」的動作，不是實作者可以自己勾掉的步驟。**
│
│  [ ] ① `pytest -q` 全綠、0 skipped
│  [ ] ② 單檔上傳 HTTP 202；當下待決定不會多一張；worker／測試跑完任務後才出現
│  [ ] ③ Fake 三次失敗：待決定不出現、磁碟 staging 不留
│  [ ] ④ `docker compose ps` 看得到 `redis` 與 `worker`；worker 為 2 個 concurrency
│  [ ] ⑤ 頁首切雲端後上傳，worker log 的 `backend=cloud`（手動）
│
│ ⛔ **沒有產品負責人明示點頭，不准開始 Phase 67。**
│    理由（design5 §0 的表）：階段丙（多檔選檔、進度面板、鏡頭連拍）
│    整個是**建在乙的 API 契約上面**的前端。契約還在動就去改前端，
│    等於同時改兩條線，出事時分不出是哪一邊。
│
│ 📌 這個閘門是**計畫層的落實**：design5 §0 只寫「只有乙的 API 契約穩定之後」，
│    §12 給了五條驗收。把那兩句合成「一個要人點頭的動作」是計畫做的事，
│    不是 design5 自己寫的字（契約備忘 §10 有同一則說明）。
└──────────────────────────────────────────────────────────────────
```

- [ ] 把 §6 驗收清單的執行結果整理成一份簡短的交付說明（照 Phase 44 交 G1 驗收包的做法），
      放進 `docs/plan/report/`，檔名 `YYYY-MM-DD-G2驗收包-請產品負責人確認.md`。
- [ ] **不要 commit**（沿用既有指示：改完先給產品負責人檢視；`unfinish/` → `finish/` 的歸檔隨 commit 執行）。

---

## 5. ASCII 圖：四個容器，哪條線走 TCP、哪條走磁碟

```text
   Mac（host）
   ├── postgresql@14 (brew) :5432   ← 別的專案 ★ 全程不准碰
   ├── postgresql@17 (brew)  ——     ← 已停用；資料目錄留著當後悔藥（不刪）
   ├── Ollama              :11434   ← 留在 Mac（有 MLX、吃得到 GPU），不進 Docker
   ├── data/  certs/  .env          ← 檔案住這裡，靠 bind-mount 進容器
   ├── .venv/ ＋ pytest             ← 測試仍在 host 跑，連 127.0.0.1:5433
   │
   └── Docker Desktop（開機自動啟動）
        ┌──────── Compose 專案 personaldocai（內部網路：服務名就是主機名）───────┐
        │                                                                        │
        │   [app]  uvicorn --ssl-*  （無 --reload）                              │
        │     容器內 :8000 ──發佈──► Mac 的 0.0.0.0:8000（手機連得到）           │
        │     mount: ./data ./certs ./.env                                       │
        │        │                        │                           │          │
        │        │TCP db:5432             │TCP redis:6379             │磁碟      │
        │        ▼                        ▼                           ▼          │
        │   [db] pgvector:pg17         [redis] redis:7-alpine      data/staging  │
        │     容器內 :5432               容器內 :6379                 │          │
        │     ──發佈──► 127.0.0.1:5433   ──發佈──► 127.0.0.1:6379     │          │
        │     volume: pgdata             volume: redisdata（AOF）     │          │
        │       ★正式庫★                   ★只有進度列★               │          │
        │        ▲                        ▲                           │          │
        │        │TCP db:5432             │TCP redis:6379             │磁碟      │
        │        │                        │                           ▼          │
        │   [worker] celery -A app.celery_app.celery_app worker                  │
        │            --loglevel=info --concurrency=2                             │
        │     沒有 ports（它不聽任何埠，只主動去 Redis 拿工作）                  │
        │     mount: ./data ./.env  （★沒有 certs：不聽 HTTPS）                  │
        │        │                                                               │
        └────────┼───────────────────────────────────────────────────────────────┘
                 │ TCP host.docker.internal:11434
                 ▼
              Ollama（在 Mac 上）── 本機 gemma4 看圖 64〜88 秒／bge-m3 轉向量
                 或
              https://ollama.com ── 雲端 gemma4 看圖約 2 秒（快照是 cloud 時）

   六條 TCP／HTTPS 線
     瀏覽器／iPhone ──HTTPS :8000──► app
     app    ──db:5432───────► db     （查詢、歸類、建資料夾、釘實體、建待辦
                                       仍由 app 寫；**照片 INSERT** 這一條搬去 worker）
     app    ──redis:6379────► redis  （入列、讀進度、dismiss）
     worker ──redis:6379────► redis  （取任務、改 status）
     worker ──db:5432───────► db     （★ INSERT 照片就是這條）
     worker ──host.docker.internal:11434──► Ollama（或直接出網到 ollama.com）
   ＋ 兩條不是 TCP 的：
     app 寫 data/staging、worker 讀它 ── 走的是**磁碟**
        （design5 §4.1：影像位元組**絕不**進 Redis 或 Celery 參數）
     手機 ══WebRTC 直連══ 桌面瀏覽器 ── 鏡頭預覽不經伺服器（增量五不動它）

   開發模式（疊 compose.dev.yaml）只差三件事：
     app 的 command 多 --reload、app 與 worker 都 bind-mount ./app、
     兩者的 restart 都是 "no"。
     ★ worker 的 command 兩種模式**完全一樣**——Celery 沒有 --reload 可加，
       改了 Python 要 `docker compose … restart worker`。
```

---

## 6. 驗收清單

- [ ] `compose.yaml` 有**四個**服務，且 `redis` 的設定全部到位：

```bash
grep -n "^  db:\|^  redis:\|^  app:\|^  worker:" compose.yaml
grep -n "appendonly\|127.0.0.1:6379\|redisdata\|redis-cli ping" compose.yaml
```

- [ ] **Redis 沒有發佈到 `0.0.0.0`**（安全性硬證據）：

```bash
docker compose ps --format '{{.Service}} {{.Ports}}' | grep redis
```

  預期：`127.0.0.1:6379->6379/tcp`。看到 `0.0.0.0:6379` 就是漏了前綴，馬上改。

- [ ] `worker` 的 command 逐字符合契約 §3.5、而且**沒有** `--reload`：

```bash
docker compose ps --no-trunc | grep worker
```

  預期 COMMAND 含 `celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=2`。

- [ ] `worker` **沒有掛 certs**——不要直接 grep `compose.yaml`（§4.2 的「刻意不掛 ./certs」
      **註解本身就含 certs 這個字**，一定誤中）；用 `config` 的輸出查，註解會被剝掉：

```bash
docker compose config | sed -n '/^  worker:/,/^volumes:/p' | grep certs
```

  預期：**沒有任何輸出**（`config` 的服務照字母排，`worker` 是最後一個，
  所以用「從 `  worker:` 到頂層 `volumes:`」這段來框它）。
  想看得更直接：`docker compose exec worker ls /app/certs` → 預期
  `No such file or directory`（app 同一句會列出 cert.pem／key.pem，正好互為對照）。
- [ ] `app` 與 `worker` 都有 `CELERY_BROKER_URL`：`grep -c "CELERY_BROKER_URL" compose.yaml` → 預期 `2`
- [ ] `app` 的 `depends_on` 有 `redis: condition: service_healthy`
- [ ] `compose.dev.yaml` 的 `worker` 有 bind-mount `./app` 與 `restart: "no"`，**沒有** `command`：

```bash
grep -n -A8 "^  worker:" compose.dev.yaml
```

- [ ] `docker compose config` 與 `docker compose -f compose.yaml -f compose.dev.yaml config` 都沒有錯誤（§4.5 的逐項對照）
- [ ] 四個服務都 `Up`，`db` 與 `redis` 都是 `(healthy)`：`docker compose ps`
- [ ] `docker compose exec redis redis-cli ping` → `PONG`
- [ ] `docker compose logs worker | head -40` 看得到 `concurrency: 2 (prefork)`、
      `[tasks]` 底下有 `personaldocai.ingest`、結尾 `celery@… ready.`
- [ ] `curl -k https://127.0.0.1:8000/health` → `{"status":"ok"}`
- [ ] **真容器煙霧全部走完**（§4.7 的 ①〜⑨）：
  - [ ] 切雲端 → `{"backend":"cloud","cloud_configured":true}`
  - [ ] 上傳**立刻**回 202（不是等一分鐘）
  - [ ] worker log 有 `AI 開始 kind=vlm backend=cloud`／`AI 結束 … ok=true`
  - [ ] worker log 有 `kind=embed backend=local`（★ 這是對的，向量永遠本機）
  - [ ] 照片出現在 `/ui/pending.html`，頂欄 N ＋1
  - [ ] `redis-cli smembers ingest:open` 成功後是空的（成功＝delete）
  - [ ] `ls data/staging` 是空的
  - [ ] 壞檔三次失敗後：`ingest:open` 有那筆、`data/staging` 仍是空的
  - [ ] `docker compose restart redis` 之後失敗那筆**還在**（AOF 有效）
- [ ] host 的測試沒有被影響（**Redis 現在真的在跑了，這一條特別重要**）：

```bash
pytest -q
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q
```

  兩次顆數必須相同、全綠。第二條是「pytest 真的沒有連 Redis」的硬證據——
  現在 `127.0.0.1:6379` 是通的，第四道安全網若有漏，第一條會**安靜地**把測試資料寫進正式的 Redis。

  順便確認一下沒被污染：

```bash
docker compose exec redis redis-cli smembers ingest:open   # 跑完測試後不該多出奇怪的 id
```

- [ ] `LAUNCH.md` 五處都改了（§4.8 ①〜⑤）：

```bash
grep -n "worker" LAUNCH.md | head -20
```

- [ ] `CLAUDE.md` 四處都改了（§4.9 ①〜④）：

```bash
grep -n "restart worker\|redisdata\|--concurrency=2" CLAUDE.md
```

- [ ] **零程式碼變更**：`git status --short -- app/ tests/` → **沒有任何輸出**
      （Phase 65 的改動已經在上一個 phase 就存在了；本 phase 不該再動它們。
      若 §4.7 ④ 真的抓到 `target=` 沒帶，那是回頭補 Phase 65 的漏，要在交付說明裡註明）

      （2026-08-26 校準：原文假設 Phase 65 的改動**已經 commit**，這條才會是空輸出。
      實況是本專案的慣例為「一個階段做完才 commit」——`unfinish/` → `finish/` 的歸檔隨 commit 執行，
      而本 phase §4.10 自己也寫「**不要 commit**」。所以 Phase 65 收工時 `app/`／`tests/`
      多半仍是未 commit 的狀態，這條 grep 會印出 65 的那 7〜9 個檔，**不代表本 phase 動了程式碼**。
      實務判準改成：開工前先 `git status --short -- app/ tests/ > /tmp/p66-before.txt`，
      收工再跑一次 `diff` 比對，**沒有新增或變動的行**才算過。
      若 Phase 65 已經先 commit 了，原文那條空輸出的寫法照舊成立。）
- [ ] `git status --short` 只多出／改到：`compose.yaml`、`compose.dev.yaml`、`LAUNCH.md`、`CLAUDE.md`，
      以及 `docs/` 底下的計畫檔與 G2 驗收包
- [ ] G2 驗收包已寫進 `docs/plan/report/`，**沒有 commit**
- [ ] 🙋 **★ G2：五條由產品負責人逐條確認並明示通過**（§4.10；**實作者不自行勾選**）

---

## 7. 常見陷阱

1. **只打 `up -d`，忘了 `--build`。** Phase 65 改了 `requirements.txt`，而套件是 build 時裝進映像的。
   worker 會噴 `ModuleNotFoundError: No module named 'celery'`，然後 `restart: unless-stopped`
   讓它一直重試——`docker compose ps` 會看到它在 `Restarting` 之間跳。
   **修法：`docker compose -f compose.yaml up -d --build`。**
   （這也是 CLAUDE.md 早就記過的一條：`up -d` **不會**重建映像。）

2. **只 `restart app`，忘了 `restart worker`。** 本 phase 最常犯、也最難查的一條。
   症狀：改了分析規則，上傳測試——HTTP 行為（202、job 建出來、進度列）全部是新的，
   **但分析結果還是舊行為**，而且一行錯誤都沒有。你會回去看程式碼，程式碼明明是對的。
   `--reload` 只救 app；Celery 不盯檔案。
   **修法：`docker compose -f compose.yaml -f compose.dev.yaml restart worker`。**

3. **worker 掛了，但 HTTP 照樣回 202。** 這是非同步架構的先天特性：
   `POST /photos` 只做「寫 staging ＋ 寫 Redis ＋ 丟訊息」，這三件事跟 worker 活不活著無關。
   所以 worker 死透了，上傳仍然一路綠燈，只是**照片永遠不會出現在待決定**。
   查法（照順序）：

```bash
docker compose ps                                   # worker 那一列還在嗎？是 Up 還是 Restarting？
docker compose logs worker --tail 50                # 有沒有 traceback
docker compose exec redis redis-cli smembers ingest:open   # job 是不是全部卡在 queued
curl -k https://127.0.0.1:8000/ingest-jobs          # 每一筆的 status 是什麼
```

  全部卡在 `queued` ＝ 沒有人在消費，就是 worker 的問題。

4. **`redis` 還沒 healthy 就打上傳 → 500。** 剛 `up -d` 的頭幾秒是正常的（healthcheck 每 5 秒一次）。
   但**重開機／重開 Docker Desktop 時不只是頭幾秒**：`depends_on: service_healthy`
   **只在 `docker compose up` 時生效**，重開機時容器是 Docker daemon 依 `restart: unless-stopped`
   直接拉起來的，不會等任何人。所以開機後那半分鐘上傳會 500，`redis` 一 healthy 就自動好
   ——**不是 bug，不用改設定**（design4 §8.6 對 `db` 已經有一模一樣的說明）。

5. **`.env` 不存在時 Docker 會默默建一個資料夾。** `compose.yaml` 有 `./.env:/app/.env` 這條
   bind-mount；來源檔不存在時 Docker **不報錯**，它會在專案根目錄建一個**叫 `.env` 的資料夾**，
   容器裡讀到空的，`load_dotenv()` 靜靜地什麼都沒載入——模型名、`OLLAMA_API_KEY` 全空。
   症狀：切雲端一直 422、看圖模型名變成預設值。本 phase 幫 worker 也加了同一條 mount，
   **踩到的機率變成兩倍**。重新 clone 之後一定要先 `touch .env` 再填內容。
   （這一條 CLAUDE.md 已記在案，這裡再講一次是因為 worker 讓它更容易發生。）

6. **`-f` 的順序寫反或漏帶。** `compose.dev.yaml` 永遠放**最後**。
   - 漏帶（只打 `docker compose up -d`）＝ Compose 發現設定不同，把 app 與 worker
     **重建成常駐版**，`--reload` 與 `./app` 掛載靜悄悄消失；
   - 順序反了（`-f compose.dev.yaml -f compose.yaml`）更陰險：`restart` 會被覆寫成
     `unless-stopped`，變成「開機自動拉起一個開發版」。
   不確定就先 `config` 一次，看 `restart` 是不是 `"no"`（phase-49 §7 陷阱 3 同一條）。

7. **`docker compose ps` 沒加 `--no-trunc`。** COMMAND 欄預設只印開頭 20 個字左右，
   而 `--concurrency=2`（worker）與 `--reload`（app）都在**最後面**。
   不加的話你會「看不到」，然後誤以為過關或誤以為壞了。

8. **把 Redis 發佈到 `0.0.0.0`**（`ports` 寫成 `"6379:6379"`）。
   Redis 預設**沒有密碼**，這等於把佇列與進度資料交給同一個 Wi-Fi 上的所有人。
   `app` 是刻意發佈到 `0.0.0.0` 的（手機要連得到才做得了無線鏡頭），`redis` 與 `db` 都不是。

9. **想用 `docker compose down` 收工。** 用 `docker compose stop`。
   `down` 會移除 container（資料還在 volume），但手滑打成 `down -v` 就是**同時**刪掉
   `pgdata`（正式庫）與 `redisdata`。

10. **在開發模式停著就去測開機常駐。** `compose.dev.yaml` 的 `restart: "no"` 字面意思就是
    「不要自動回來」。重開 Docker Desktop 之後 `db` 與 `redis` 會回來、`app` 與 `worker` 不會。
    那是刻意的（phase-49 §7 陷阱 2）。收工前記得切回常駐：
    `docker compose -f compose.yaml -f compose.dev.yaml stop && docker compose -f compose.yaml up -d`

11. **用本機模型跑煙霧。** 看圖 64〜88 秒 × `--concurrency=2`，一次傳兩張就是兩個同時燒 CPU。
    Phase 48 已經把 db container 壓垮過一次（postmaster 花 2 分鐘才殺得掉子行程）。
    **煙霧一律先切雲端**（design5 D6）。真的要試本機，一次一張、而且不要同時問問題。

12. **看 `docker compose logs app` 找 `kind=vlm`。** 找不到的。
    增量五之後，看圖與轉向量都搬到 **worker** 行程了，計時 log 也跟著搬過去。
    `app` 那邊現在只剩詢問流程的 `kind=route`／`kind=answer`／`kind=embed`
    與「再建議一個」的 `kind=entity_suggest`。

13. **測完忘了把 AI 開關切回本機。** 影響不大（`config.AI_BACKEND` 存記憶體，
    重啟 app 一律回本機），但雲端是要付費的——養成 §4.7 ⑩ 那個習慣。

---

## 附：本文件引用的官方文件

| 主題 | 連結 |
|---|---|
| Redis 持久化：AOF 是什麼、`appendonly yes`（「You can turn on the AOF in your configuration file: `appendonly yes`」；AOF ＝「logs every write operation received by the server」） | <https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/> |
| Redis 官方 Docker 映像：資料目錄 `VOLUME /data`、alpine tag（含 `7-alpine`） | <https://hub.docker.com/_/redis> |
| Compose 檔案格式：`healthcheck`（`test` 的 `CMD`／`CMD-SHELL` 兩種寫法、`interval`／`timeout`／`retries`）與 `depends_on` 的 `condition: service_healthy` | <https://docs.docker.com/reference/compose-file/services/> |
| Compose 多份檔案的合併規則（單值覆寫 vs 清單逐項合併） | <https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/> |
| Celery 指令列參考（選項清單；`-c/--concurrency`「The default is the number of CPUs available on your system.」；`-l/--loglevel`。⚠ `-A` 這頁只列選項名、不講格式） | <https://docs.celeryq.dev/en/stable/reference/cli.html> |
| Celery `--app` 的正式格式（`module.path:attribute`）與只給模組名時的搜尋順序——§4.2 對 `-A app.celery_app.celery_app` 的解讀依據 | <https://docs.celeryq.dev/en/stable/getting-started/next-steps.html> |
| Celery 第一支任務（`celery -A tasks worker --loglevel=INFO` 的原始範例） | <https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html> |
| Celery 用 Redis 當 broker（URL 格式 `redis://localhost:6379/0`） | <https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html> |
| `host.docker.internal`（容器連回宿主機；Ollama 留在 Mac 上） | <https://docs.docker.com/desktop/features/networking/networking-how-tos/> |

（`~/CLAUDE.md` 的 MCP 規則要求「查最新官方文件優先用 Context7」。撰寫與 2026-08-25 review 覆核時
工作階段都沒有掛載 Context7，依同一條規則的後備做法改用官方站台直查；上表每一條都是實際讀過的頁面。
覆核時補了一列：`-A` 的格式說明在 Next Steps 頁，CLI reference 只列選項名。另實查過官方映像頁的
持久化範例用的是 `redis-server --save 60 1`——「設定當參數接在 redis-server 後面」這一招與
`--appendonly yes` 同一個機制。）
