# LAUNCH.md — 啟動與日常操作

PersonalDocAI 自 2026-08-24 起跑在 Docker 裡，**開機會自動啟動，平常不用下任何指令**。

---

## 目錄

1. [快速開始](#1-快速開始)
2. [網址一覽](#2-網址一覽)
3. [啟動與停止](#3-啟動與停止)
4. [開發模式（熱重載）](#4-開發模式熱重載)
5. [換網路時要做的事](#5-換網路時要做的事)
6. [跑測試](#6-跑測試)
7. [資料庫](#7-資料庫)
8. [備份](#8-備份)
9. [監控與看 log](#9-監控與看-log)
10. [排錯](#10-排錯)
11. [絕對不要做的事](#11-絕對不要做的事)

---

## 1. 快速開始

**什麼都不用做，直接開這個網址：**

```
https://linjuntingdeMacBook-Pro-1071.local:8000/
```

這個網址**永遠不會變**（換 Wi-Fi、IP 變了都一樣）。設成書籤即可。

服務沒起來的話：

```bash
docker compose -f compose.yaml up -d
```

還有一個東西要在：**Mac 上的 Ollama**（選單列要有它的圖示）。它是登入項目、開機會自動帶起，
但被手動結束（Quit）後**不會自己回來**——而且沒開的時候網頁照常能開、照片也照樣收（回 202），
只是**分析全部失敗、問問題回 500**（2026-08-27 真的發生過）。拉起來：

```bash
open -a Ollama    # 約 4 秒就緒；驗證：curl -s http://127.0.0.1:11434/api/version
```

---

## 2. 網址一覽

以 `HOST` 代表 `linjuntingdeMacBook-Pro-1071.local`：

| 頁面 | 網址 |
|---|---|
| 首頁（自動轉上傳頁） | `https://HOST:8000/` |
| 上傳 | `https://HOST:8000/ui/upload.html` |
| 檔案櫃 | `https://HOST:8000/ui/browse.html` |
| 問問題 | `https://HOST:8000/ui/ask.html` |
| 無線鏡頭（桌面） | `https://HOST:8000/ui/camera-desk.html` |
| API 文件 | `https://HOST:8000/docs` |

規則：

- **一定要 `https`** —— `http://` 完全連不上
- **首頁用 `.local` 主機名開**，不要用 `localhost`。其他頁用 `localhost` 沒差，
  但從首頁點到鏡頭頁時，QR 會指向 Docker 內部網段（`172.x`），手機連不到
- 手機不用自己打網址，掃 QR 即可

**為什麼用 `.local` 而不是 IP**：`.local` 是這台 Mac 的 Bonjour 名字，
會自動跟著當下的 IP 走。換 Wi-Fi、DHCP 重新配發 IP 都不影響，
**網址不用改、憑證也不用重簽**。（憑證裡同時簽了 IP，所以 IP 那條路也還能用，當退路。）

---

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

**重啟單一服務（worker 怪怪的、或改了 `.env` 之後）：**

```bash
docker compose -f compose.yaml restart worker        # 只重啟背景分析
docker compose -f compose.yaml restart app worker    # 改 .env 之後兩個都要重啟才會讀到新值
```

⚠️ **重啟 worker 前，先等它手上沒事**——右下角進度面板收起、或
`curl -sk https://127.0.0.1:8000/ingest-jobs` 的 `jobs` 裡沒有 `analyzing`／`retrying`
（只剩 `failed` 沒關係，failed 不佔 worker）。原因：重啟只給 10 秒寬限，
而本機看一張圖要 60〜90 秒——做到一半被砍的那一筆**不會重送**（訊息已被 Celery 認領），
會永遠卡在「分析中」（救法見 §10 排錯）。真的有任務在跑又非重啟不可：

```bash
docker compose stop -t 300 worker      # 給它最多 5 分鐘把手上這張做完再停
docker compose -f compose.yaml up -d   # 再拉回來
```

⚠️ **常駐模式下 restart 救不了程式碼改動**——常駐的程式包在映像裡，
改了 `app/` 要重建映像：`docker compose -f compose.yaml up -d --build`
（app 與 worker 用同一份映像，一次一起換新）。要邊改邊試請切開發模式（§4）。

⚠️ 用 `docker compose stop` 停掉之後，**重開機不會自己回來**，要手動 `up -d`。

⚠️ **改了 `requirements.txt` 之後要 `--build`**，否則新套件不會進映像：
`docker compose -f compose.yaml up -d --build`

---

## 4. 開發模式（熱重載）

改 `app/` 底下的程式碼存檔後 **app** 自動生效；**worker 不會**（見下方表格第一列）。

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

---

## 5. 換網路時要做的事

**用 `.local` 網址的話：不用做任何事。** 名字會自動跟著新 IP 走。

只有這兩種情況要動手：

**① 換了電腦名稱**（系統設定 → 一般 → 關於 → 名稱）

```bash
cd /Users/linjunting/personalDocAI
scutil --get LocalHostName          # 查新名字，書籤換成它
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

**② 網路擋 mDNS，`.local` 不通**（公司／公共 Wi-Fi 比較常見）

退回用 IP，這時才要重簽憑證：

```bash
ipconfig getifaddr en0              # 查 IP，網址換成它
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

檢查憑證涵蓋哪些位址：

```bash
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
```

⚠️ **測鏡頭測到一半不要跑 `restart`** —— 配對 token 存在記憶體，一重啟就失效，QR 要重產。

---

## 6. 跑測試

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                        # 預期 543 passed（2026-08-27 實查；以當下為準）
OLLAMA_BASE_URL=http://localhost:9 pytest -q     # 零外部依賴驗證，顆數要相同
```

前提：`docker compose ps` 的 `db` 要是 `Up (healthy)`（測試庫住在容器裡）。

⚠️ **不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。測試每一顆都會 TRUNCATE 同一個測試庫，兩份同時跑會互相清掉資料，症狀是大量看似隨機的 404 與 `NoneType` 錯誤。

---

## 7. 資料庫

`~/.zshrc` 已設好 `PGPORT=5433`、`PGUSER=postgres`、`PGHOST=127.0.0.1`，所以：

```bash
psql -d PersonalDocAI        # 正式庫
psql -d PersonalDocAI_test   # 測試庫

# 明寫參數版（腳本裡用這個）
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI
```

三個變數缺一不可：

- 少 `PGHOST` → `connection to server on socket "/tmp/.s.PGSQL.5433" failed`
- 少 `PGUSER` → `role "linjunting" does not exist`

⚠️ `postgresql@14`（5432 埠）是**別的專案**的（wanderlove、fse_chat_room），絕不可停用或修改。

---

## 8. 備份

```bash
# 資料庫
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump

# 照片原圖（★ 上面那行不含照片檔，data/ 不入版控，全世界只有一份）
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
```

還原：

```bash
pg_restore -h 127.0.0.1 -p 5433 -U postgres --no-owner --no-acl \
  --dbname=PersonalDocAI ~/PersonalDocAI-backup-YYYY-MM-DD.dump
```

---

## 9. 監控與看 log

**一分鐘健檢（由外到內三層，照順序打）：**

```bash
docker compose ps                                    # ① 四個服務都在？db 與 redis 要 (healthy)
curl -s http://127.0.0.1:11434/api/version           # ② Mac 上的 Ollama 活著？沒回應見 §10 第一列
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
                                                     # ③ 佇列現況：進行中＋失敗的任務、收件箱張數
```

### Docker 層（服務有沒有活著）

```bash
docker compose ps --no-trunc            # 完整啟動指令（分辨常駐／開發模式；--no-trunc 不能省）
docker compose logs -f app worker       # 跟著看兩邊（Ctrl+C 只離開 log，容器繼續跑）
docker compose logs worker --tail 50    # 最近 50 行
docker compose logs worker --since 10m  # 最近 10 分鐘（回頭找剛剛那次失敗用這個）
```

### Celery／worker 層（照片分析在做什麼）

```bash
docker compose logs -f worker                    # 每筆任務全程：收到 → 第 N 次看圖 → 入庫完成／最終失敗
docker compose logs worker | grep "kind=vlm"     # 每張圖看多久、走本機還是雲端（backend=local|cloud）
docker compose logs worker | grep "kind=embed"   # 轉向量（永遠 backend=local）
docker compose logs worker | grep "job "         # 只看 job 生命週期事件

# 直接問 worker 本人（往 Redis 廣播、活著的 worker 會回話；要看到 1 node online）
docker compose exec worker celery -A app.celery_app.celery_app status
docker compose exec worker celery -A app.celery_app.celery_app inspect active     # 正在做的（空＝閒著）
docker compose exec worker celery -A app.celery_app.celery_app inspect reserved   # 已領走、還沒開始的
```

### Redis 層（佇列與進度資料的本體）

```bash
docker compose exec redis redis-cli ping                          # 要回 PONG
docker compose exec redis redis-cli llen celery                   # 排隊中、還沒被領走的任務數（平常 0）
docker compose exec redis redis-cli smembers ingest:open          # 還沒了結的 job_id（成功會整筆刪掉，平常空的）
docker compose exec redis redis-cli get "ingest:<job_id>"         # 單筆 job 的 JSON（status／attempt／error）
docker compose exec redis redis-cli --scan --pattern "ingest:*"   # 所有進度相關的 key
docker compose exec redis redis-cli info persistence | grep aof_enabled   # AOF 有開＝aof_enabled:1
```

兩種 key 的分工：`celery`（list）是 **Celery 的排隊隊伍**；`ingest:*` 是**我們自己的進度列**
（右下角面板與 `GET /ingest-jobs` 讀的就是它）。交叉讀法：
`llen celery` 有數字＝任務在排隊等 worker；`ingest:open` 有東西但 `llen` 是 0
＝ worker 正在做（`inspect active` 應該看得到它；看不到就是卡住了，見 §10）。

### app 層（詢問流程與鏡頭）

```bash
docker compose logs app --tail 50
docker compose logs app | grep "kind="        # 問問題的 route／answer 計時（入庫的 kind=vlm 在 worker 那邊）
docker compose logs app | grep "role=phone"   # 無線鏡頭：手機到底有沒有連上
```

---

## 10. 排錯

| 症狀 | 原因 | 解法 |
|---|---|---|
| 網頁完全開不起來 | 用了 `http://` | 改成 `https://` |
| 憑證警告 | 用區網 IP 開、憑證未涵蓋該 IP | 重簽憑證（§5） |
| **QR 是 `172.x` 開頭** | 桌面頁用 `localhost` 開的 | 關掉分頁，用 `.local` 網址重開 |
| `.local` 網址開不起來 | 這個網路擋 mDNS | 退回用 IP：`ipconfig getifaddr en0`，並重簽憑證（§5）|
| QR 顯示正常但手機掃不到 | 網址太長 → QR 格子太密 | `style.css` 的 `.cd-qr svg` `max-width` 要 ≥ `20rem`（有測試釘住）。網址越長格數越多，格子就越細 |
| 手機掃了打不開 | ① QR 的 IP 不對 ② iPhone 未信任根憑證 ③ 網路擋 | 依序查；`log` 若沒有 `role=phone` 就是手機根本沒連到 |
| 桌面一直顯示「對面不在線」 | 手機沒連上 | 同上 |
| **照片分析全部失敗**：面板紅字「AI 看不懂這張照片（已試 3 次）」，張張都是 | 十之八九是 **Mac 上的 Ollama 沒在跑**。worker log 若見 `ConnectError: [Errno 101] Network is unreachable` 就是它——容器連「host 上沒人聽的埠」會報成這樣，**看起來像 Docker 網路壞掉，其實只是 Ollama 沒開**（2026-08-27 踩過）。切「雲端」也躲不掉：轉向量永遠走本機 bge-m3 | `open -a Ollama`，等 `curl -s http://127.0.0.1:11434/api/version` 有回應即可，**容器全都不用重啟**。失敗列按 × 關掉、照片重新上傳（failed＝庫裡什麼都沒存） |
| 問問題回 500 | Ollama 沒開（上傳**不會** 500——照樣收檔回 202，然後走到上面那列） | 同上 `open -a Ollama` |
| 上傳很慢（1〜2 分鐘） | 本機模型就是這麼慢 | 正常。看圖 60〜90 秒、路由 138 秒、回答 92 秒 |
| 同時上傳＋問問題 → 500 | 主機資源被壓垮 | **一次只做一件事** |
| pytest 大量隨機失敗 | 兩份 pytest 同時跑 | 等另一份跑完 |
| 上傳回 202 但照片永遠不出現 | worker 沒起來／掛了 | `docker compose ps` 看 worker 在不在；`docker compose logs worker --tail 50` 看有沒有 traceback |
| 上傳直接回 500 | redis 沒起來或還沒 healthy | `docker compose ps` 看 redis；`docker compose exec redis redis-cli ping` 要回 PONG |
| 改了程式碼但分析行為沒變 | Celery 沒有 `--reload` | `docker compose -f compose.yaml -f compose.dev.yaml restart worker` |
| worker 一直 Restarting | 映像沒重建（缺 celery 套件） | `docker compose logs worker` 若是 `ModuleNotFoundError: No module named 'celery'` → `docker compose up -d --build` |
| 任務**永遠**卡在「分析中」，× 也按不掉 | worker 做到一半被重啟／被殺（§3 的警告就是在防這個）。那筆訊息已被 Celery 認領、不會重送，而 dismiss 只准關 `failed` | 先用 `inspect active`（§9）確認真的沒人在做它，再手動清掉那一筆：`docker compose exec redis redis-cli del "ingest:<job_id>"` ＋ `docker compose exec redis redis-cli srem ingest:open "<job_id>"`，照片重新上傳。staging 殘檔之後由 24 小時掃把自動清 |

各層的看 log／看佇列指令整理在 [§9 監控](#9-監控與看-log)。

---

## 11. 絕對不要做的事

| 指令 | 後果 |
|---|---|
| `docker compose down -v` | **刪掉正式庫**（`-v` 連 volume 一起刪） |
| `docker volume rm personaldocai_pgdata` | **刪掉正式庫** |
| `docker system prune --volumes` | **刪掉正式庫**（任何一次 `down` 之後都危險） |
| Docker Desktop → Reset to factory defaults | **刪掉正式庫** |
| 把 `compose.yaml` 的 `pg17` 改成 `pg18` | PGDATA 路徑不同 → 建新空叢集，看起來像資料全沒了 |
| 對正式庫跑 `db/schema.sql` | 開頭是 `DROP TABLE` |
| `brew uninstall postgresql@17` | 那是後悔藥第 1 層（資料目錄 `/opt/homebrew/var/postgresql@17` 保留中） |
| 停用／修改 `postgresql@14` | 別的專案在用 |
| `docker volume rm personaldocai_redisdata` | 丟掉進度列與失敗列（**不是**正式庫，見下） |

停服務一律用 `docker compose stop`。

**`pgdata` 與 `redisdata` 差很多，不要搞混：**

| volume | 裡面是什麼 | 丟了會怎樣 |
|---|---|---|
| `personaldocai_pgdata` | **正式庫**：照片列、資料夾、實體、待辦、向量 | 災難。照片全部消失，只能從備份還原 |
| `personaldocai_redisdata` | 進度列、失敗列、還沒做完的任務 | 只丟「還沒分析完的那幾張」。已入庫的照片一張都不會少（正本在 pgdata ＋ `data/photos`）。那幾張要重新上傳；它們留在 `data/staging` 的暫存檔會由 24 小時掃把自動清掉 |

所以 `down -v` 仍然絕對禁止（它會**兩個一起刪**），但如果哪天真的只需要清 Redis，
`docker volume rm personaldocai_redisdata` 是可以接受的損失——**前提是當下沒有任務在跑**。

---

## 附錄：目前架構

```
   Mac（host）
   ├── postgresql@14 (brew) :5432   ← 別的專案 ★ 全程不准碰
   ├── postgresql@17 (brew)  ——     ← 已停用；資料目錄留著當後悔藥（不刪）
   ├── Ollama              :11434   ← 留在 Mac（有 MLX、吃得到 GPU），不進 Docker
   │                                   ★ 登入項目，但被手動 Quit 後不會自己回來（§1）
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

相關文件：`CLAUDE.md`（專案全貌與開發規則）、`docs/design/`（設計決策）、`docs/plan/`（實作紀錄）。
