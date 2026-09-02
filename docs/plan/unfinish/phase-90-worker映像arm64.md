# Phase 90：worker 映像（多階段 Dockerfile ＋ arm64）＋ ★ 閘門 G2

> ⚠ **2026-09-01：** 上傳驗雲端路時看圖的**內容**，不要只改檔名成 `receipt-test.png`。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> **本 phase 特別不要做的四件事：**
> ① 不要新開第二份 `Dockerfile`（例如 `Dockerfile.worker`）——多階段就是為了避免兩份會漂移的檔。
> ② 不要動 `compose.yaml` 一個字（`app` stage 放最後就是為了讓 compose 不必改）。
> ③ 不要在 compose 裡新增第五個服務把 cloud_worker 也跑起來（那是 EC2 的事；本機用 `docker run` 手動跑）。
> ④ 不要在這裡建任何 AWS 資源（SG、EC2、ECR 全部是 Phase 91／92 的事）。

> 🎯 **一句話目標：** 把現在單階段的 `Dockerfile` 改成**三個 stage**
> （`base` → `cloud-worker` → `app`，**`app` 放最後**），
> 建出一個 `linux/arm64` 的工人映像 `personaldocai-worker:local`，
> 在這台 Mac 上**用容器**重做一次 Phase 88 的端到端（真 S3／真 SQS／真 Ollama Cloud），
> 再開一個新的測試檔 `tests/integration/test_design6_error_paths.py` 放 4 顆掃碼測試，
> 最後把證據交給產品負責人跑 **★ 閘門 G2**。

**為什麼要做這個：**

Phase 88 已經讓工人在這台 Mac 上跑通了——但那是**用 `python -m app.workers.cloud_worker` 直接跑**，
吃的是 `.venv` 裡的套件。EC2 上沒有你的 `.venv`，也沒有 Python 3.12，
它只會做一件事：**把一個映像拉下來、跑起來**。

所以在花任何 AWS 點數之前，要先確定「同一支程式裝進映像之後仍然跑得動」。
而且那個映像必須是 **`linux/arm64`**——EC2 用的是 `t4g.small`（AWS 自研的 ARM 機型）。
好消息是：這台 Mac 是 Apple Silicon，**它本來就是 arm64**，所以 `docker build` 出來的
預設就是對的架構，不必模擬（要模擬是 Phase 94 的 GitHub runner 才需要，那邊很慢）。

做完這一份，「工人這件事」在本機就完全確定了；接下來上 EC2 只剩「換一台機器跑同一個映像」。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **映像（image）** | 「容器的模子」。裡面有一套完整的檔案系統：作業系統的基本檔、Python、你裝的套件、你的程式碼。跑起來的那一份叫 container |
| **stage（階段）** | 一份 `Dockerfile` 裡可以有好幾個 `FROM …`，每一個 `FROM` 開始一個新的 **stage**。給它取名字的寫法是 `FROM python:3.12-slim AS base` |
| **multi-stage build（多階段建置）** | 一份 Dockerfile、多個 stage。本專案用它的目的很單純：**app 與 cloud-worker 共用同一套套件與程式碼，只有啟動指令不同**，所以讓兩個 stage 都接在同一個 `base` 後面 |
| **`--target`（目標階段）** | `docker build --target cloud-worker .` ＝「只建到 `cloud-worker` 這個 stage 就停」。**不加 `--target` 的話，Docker 會建到檔案裡的最後一個 stage** ——這就是為什麼 `app` 一定要放最後（總覽 §10 追認項 j） |
| **`ARG`（建置期參數）** | 只在 **build 的時候**存在的變數，用 `docker build --build-arg NAME=VALUE` 傳進去。跑起來之後就沒有它了 |
| **`ENV`（執行期環境變數）** | 寫進映像裡的環境變數，容器**跑起來之後**讀得到。本專案用 `ENV WORKER_VERSION=$GIT_SHA` 把建置當下的 git 短碼「烙」進映像 |
| **arm64 / aarch64** | 同一件事的兩個名字：ARM 的 64 位元架構。Apple Silicon 的 Mac（M1／M2／M3…）與 AWS 的 `t4g` 機型都是它 |
| **amd64 / x86_64** | Intel／AMD 那一套架構。GitHub Actions 的免費 runner 是這個，所以 Phase 94 要用 QEMU 模擬才建得出 arm64 |
| **QEMU** | 一套「讓某架構的機器假裝成另一架構」的模擬器。Docker 用它做跨架構 build。**慢**（5〜15 分鐘）。本 phase 在 Mac 上**用不到**，只是先示範指令長什麼樣 |
| **buildx** | Docker 的多平台建置外掛，指令是 `docker buildx build`。它能一次建多個架構、也能明寫 `--platform` |
| **`--env-file`** | `docker run --env-file .env` ＝「把這個檔裡的每一行 `KEY=VALUE` 都變成容器裡的環境變數」。**注意它跟 bind-mount `.env` 不一樣**：bind-mount 是把檔案掛進去讓程式自己讀，`--env-file` 是 Docker 直接幫你設環境變數 |
| **`docker compose config`** | 只解析設定、**不啟動任何東西**，把「合併後的完整設定」印出來。本 phase 拿它當「compose 零改動」的證據 |
| **★ 閘門 G2** | 「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的那句話。**產品負責人講的，實作者不可以自己勾** |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D15** | 「映像 **`linux/arm64`**，機型 **t4g.small**」 | §4.3 建出 arm64 映像並用 `docker image inspect` 驗 `Architecture` 真的是 `arm64` |
| **D16** | 「CD：build `linux/arm64` → ECR `<git-sha>`」 | §4.2 的 `ARG GIT_SHA` ＋ `ENV WORKER_VERSION=$GIT_SHA` 是那條路的**起點**：本 phase 先把「sha 怎麼進映像」做好，Phase 94 的 CD 只是換一個地方傳同一個參數 |
| **§11 第 5 列** | 「Dockerfile／多階段或第二 target｜戊｜worker 映像 `linux/arm64`」 | §4.2 全節 |
| **§0 戊那列** | 「同一支 worker 進 Docker → EC2」 | §4.4 用容器重做 Phase 88 的端到端＝「同一支 worker 進 Docker」那一半 |
| **§13 最後一列** | 「host 與映像套件分岔在 ARM worker 映像上同樣存在」 | §7 陷阱 6 寫進去，並在 §4.4 要求「重建映像之後至少真跑一次端到端」 |
| **總覽 §10 追認項 j** | 「`Dockerfile` 改多階段、`app` stage 放最後，`compose.yaml` 一個字不改」 | §4.2 的 stage 順序 ＋ §4.5 的 `docker compose config` diff 證明 ＋ §4.6 的第 4 顆掃碼測試 |
| **總覽 §10 追認項 B** | 「`tests/integration/test_design6_error_paths.py` 在 Phase 90 就開檔，不等到 95」 | §4.6 開檔並放 4 顆；93／94 追加、95 收尾 |
| **總覽 §10 追認項 e** | 「`WORKER_VERSION` 的 log 是『跑的是不是新映像』的唯一驗證方式」 | §4.4 的容器啟動 log 要看得到 `version=<sha>` |
| **總覽 §7 鐵律 11** | 「`compose.yaml` 本增量零改動」 | §4.5 |

> ⚠️ **這裡引用的三條「追認項」是計畫層的裁決，不是 design6 自己寫的字**（總覽 §10 明文）。
> 產品負責人若不同意「Dockerfile 改多階段」而想要兩份 Dockerfile，
> 就要同時改 `compose.yaml` 的 `build:` 段——回本 phase §4.2 改。

---

## 2. 前置條件

**依賴：Phase 88（工人主迴圈與 Mac 端到端）與 Phase 89（`Ec2Probe`）都已完成。**

- Phase 88 的產出：`app/workers/cloud_worker.py` 有 `main()`、`python -m app.workers.cloud_worker`
  跑得起來、啟動時印一行 `cloud_worker 啟動 version=… region=… bucket=…`。
- Phase 89 的產出：`app/services/cloud_ingest.py` 有 `Ec2Probe`、`get_cloud_route()` 認得 `ec2`。
- `config.WORKER_VERSION` 這個設定在 **Phase 77** 就放進 `app/core/config.py` 了，預設值是 `"dev"`。
- `.env` 裡已經有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`（Phase 82）、
  `S3_BUCKET`（Phase 84）、`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`（Phase 85）、
  `OLLAMA_API_KEY`（更早就有）。
- **`.env` 那把 `personaldocai-mac` 的 key 已經在 Phase 88 跑通過工人**——也就是它拿得到
  jobs 佇列的 `sqs:ReceiveMessage`／`sqs:DeleteMessage` 與 results 佇列的 `sqs:SendMessage`
  （工人端要的動作，跟本機端的「Send jobs／Receive results」剛好相反）。本 phase 的容器用的是**同一把 key**。
  ⚠ Phase 82 的 `deploy/aws/mac-policy.json` 原文只有本機端那一組；若 Phase 88 當時是靠別的身分
  （例如 `~/.aws` 的 admin profile）跑通的，本 phase 會在第一次 `ReceiveMessage` 就 `AccessDenied`
  ——先回 Phase 82／88 把 policy 補齊再做本 phase（§7 陷阱 14），**不要**在本 phase 臨時改 policy 或換 key。
- `.env` 目前是 `CLOUD_ROUTE=off`（Phase 86／88 收工時改回去的，Phase 89 驗過）。§4.4 會暫時切成 `assume`，
  **收工要改回 `off`**。

**開工基線：543 ＋ 74〜89 的累計 ＝ 658 passed ＋ 0 skipped**（總覽 §9 的數字）。

**開工前一次驗完（在專案根目錄 `/Users/linjunting/personalDocAI`）：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 顆數基線（總覽 §9：Phase 89 做完應為 658）
pytest -q
# 預期尾巴：658 passed（沒有任何 skipped）

# ② 三個死埠一起指，顆數要一模一樣（零外部依賴實證）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
# 預期：658 passed，與 ① 逐字相同

# ③ 工人程式在正確的位置（.dockerignore 排除 scripts/，所以一定要在 app/ 底下）
ls -l app/workers/cloud_worker.py app/workers/__init__.py
grep -n "def main" app/workers/cloud_worker.py

# ④ config 有 WORKER_VERSION（Phase 77 放的）
grep -n "WORKER_VERSION" app/core/config.py
# 預期：看得到一行 WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")

# ⑤ Docker Desktop 開著、四個服務活著
docker version              # Client／Server 兩段都要有輸出；只有 Client ＝ Docker Desktop 沒開
docker compose ps           # db 與 redis 要 Up (healthy)，app 與 worker 要 Up

# ⑥ 這台機器是 arm64（Apple Silicon）——決定了 build 出來的預設架構
uname -m
# 預期：arm64
docker info --format '{{.Architecture}}'
# 預期：aarch64（Docker 用的是 Linux 的叫法，跟 arm64 是同一件事）

# ⑦ 分支是 main、工作區乾淨
git branch --show-current   # 預期：main
git status --short          # 除了本增量正在做的檔，不該有其他東西

# ⑧ 開工快照（之後 §6 驗收「有沒有動到不該動的檔」要拿它相減）
git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml > /tmp/p90-before.txt
docker compose config > /tmp/p90-compose-before.yaml
wc -l /tmp/p90-compose-before.yaml
# 預期：印出行數（幾百行都正常）；這份是 §4.5 要 diff 的基準
```

> 📌 **第 ⑧ 步的 `docker compose config` 先跑、存成基準，§4.5 才有東西可以 diff。**
> 老實說：`docker compose config` 只讀 `compose.yaml` 與環境變數、**不讀 Dockerfile**，
> 所以改完 Dockerfile 再跑，輸出其實也一樣（§7 陷阱 7 有解釋）；`compose.yaml` 裡也沒有任何
> `${…}` 變數插值，所以 §4.4 改 `.env` 同樣不影響它。仍然要求「先拍基準」是為了養成習慣——
> 真的有人順手動了 compose 的那一天，只有事先存好的基準救得了你。
> 忘了先跑的話：`git stash` 把改動暫存起來、跑一次存成基準、再 `git stash pop` 拿回來。

> ⚠️ **絕對不要同時跑兩份 pytest。** `tests/conftest.py` 的 autouse `reset_tables`
> 每一顆測試都會 `TRUNCATE` 同一個測試庫，兩份同時跑會互相清掉對方的資料。
> 症狀是**大量看似隨機的** 404 與 `TypeError: 'NoneType' object is not subscriptable`，
> 而且每次紅的顆數都不一樣——看起來像程式壞了，其實只是撞在一起。

---

## 3. 範圍

### 做

1. 把 `Dockerfile` 從單階段改成三個 stage：`base` → `cloud-worker` → `app`（**`app` 放最後**）。
2. 在 `.dockerignore` 加一行 `deploy/`（附註解）——`deploy/` 是 Phase 82／91 放 IAM policy JSON 與
   EC2 設定檔的地方，只給人與 AWS CLI 用，映像用不到（總覽 §10 追認項 k 只講了 `scripts/`；
   `deploy/` 是本 phase 順手收緊，份量見 §4.2 最後一步的說明）。
3. 建出 `personaldocai-worker:local`（arm64），並驗證架構真的是 `arm64`。
4. 在 Mac 上**用容器**跑工人（`docker run --rm --env-file .env …`），重做一次 Phase 88 的端到端，
   **收工把 `.env` 改回 `CLOUD_ROUTE=off`**。
5. 證明 `compose.yaml` 零改動而且行為不變：`docker compose config` 的輸出 diff 為空、
   `docker compose -f compose.yaml up -d --build` 之後四個服務照常。
6. 新開 `tests/integration/test_design6_error_paths.py`，放 **4 顆**掃碼測試（總覽 §2.7 定案的名字）。
7. 交出 **★ 閘門 G2** 的證據給產品負責人。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 新開 `Dockerfile.worker` 之類的第二份 Dockerfile | 兩份檔案會漂移（改了套件只改一邊、然後在 EC2 上才發現）。總覽 §10 追認項 j 明文選了多階段 |
| 把 `app` stage 放在 `cloud-worker` 前面 | 不帶 `--target` 的 `docker build .` 會停在**最後一個** stage。`app` 不在最後的話，`compose.yaml` 的 `build: .` 會安靜地蓋出一個「以為是 app、其實是 worker」的映像——**沒有任何錯誤訊息**，只有 app 容器起來之後一直重啟 |
| 改 `compose.yaml`（哪怕只加一個註解，也不要加 `target:`） | 總覽 §7 鐵律 11：本增量 compose 零改動。§4.5 的 diff 證明 ＋ §4.6 第 4 顆掃碼就是在驗這件事。（AWS 變數名不出現在 compose 由 **Phase 95** 守，本 phase 不重複掃） |
| 在 compose 加第五個服務跑 cloud_worker | 本機跑工人是**除錯／驗收**用的一次性動作，不是常駐服務。常駐的工人在 EC2（Phase 92）。加了服務就會開機自己跑起來，然後默默地把 SQS 訊息都吃光 |
| 幫 worker 映像掛 `./certs` | 工人不聽 HTTPS、不當伺服器，用不到憑證（與 compose 裡 worker 服務不掛 certs 同一個理由） |
| 在 Mac 上用 `--platform linux/amd64` 建 worker 映像 | 總覽 §2.8 禁止清單最後一列。EC2 是 `t4g`＝arm64，amd64 映像在上面會直接 `exec format error` 或走 QEMU 慢到不能用 |
| 建立任何 AWS 資源（SG／IAM／ECR／EC2） | 那是 Phase 91／92，而且 **★G2 還沒過**（總覽 §4：G2 之後才開始花點數建 EC2） |
| 把映像 push 到 ECR | ECR repo 是 Phase 91 建的，本 phase 連 `docker tag` 都不做 |
| 改任何 `app/` 底下的 `.py` | 本 phase **零產品 Python 變更**。真的發現工人有 bug → 回 Phase 87／88 修，不要在這裡順手改 |
| 在 `.dockerignore` 動 `deploy/` 以外的任何一行 | 它已經正確了（排除 `scripts/`、`tests/`、`docs/`、`.env`、`certs/`、`data/`）。工人程式在 `app/` 底下，會跟著 `COPY app ./app` 一起進映像。本 phase 只**加一行** `deploy/`（§4.2 最後一步），不刪、不改既有的行 |

---

## 4. 實作步驟

### 4.1 先想清楚三個 stage 的關係（動手前 30 秒）

現在的 `Dockerfile` 是**一個** stage，做四件事：裝套件 → 複製程式碼 → `EXPOSE 8000` → `CMD uvicorn …`。

改完之後是三個 stage：

- **`base`**：裝套件 ＋ 複製程式碼。**沒有 `CMD`**，因為它不會被直接跑。
- **`cloud-worker`**：`FROM base`，加 `ARG GIT_SHA` ＋ `ENV WORKER_VERSION` ＋ `CMD python -m app.workers.cloud_worker`。
- **`app`**：`FROM base`，加 `EXPOSE 8000` ＋ 現在那條 `CMD uvicorn …`。**放最後。**

`cloud-worker` 與 `app` 都是 `FROM base`，所以**兩者共用同一層套件**——
Docker 只會裝一次 `pip install`，第二個 stage 直接重用那一層，幾乎不花時間。

📌 **`app` 放最後的理由：** `docker build .` 沒指定 `--target` 時，Docker 的規則是
「**建到檔案裡最後一個 stage 為止**」。`compose.yaml` 的 `app` 與 `worker` 兩個服務都寫
`build: .`（沒有 `target:`），所以只要 `app` 是最後一個 stage，compose 拿到的就還是
同一份 app 映像——**compose 一個字都不必改**。

### 4.2 改 `Dockerfile`（完整重貼，直接覆蓋整份檔案）

> ⚠️ **TDD 順序：先做 §4.6 的步驟 1 與步驟 2**（建好測試檔、跑一次**親眼看到 3 顆紅**），
> **再回來做這一節。** 順序反過來的話那三顆會一開始就綠，你永遠不知道它們有沒有在測東西
> ——這正是總覽 §7 鐵律 1 說「跑它確認紅不可以跳過」的理由。
> 為了閱讀順暢，Dockerfile 的內容寫在這裡；**執行順序是 §4.6 步驟 1／2 → §4.2 → §4.6 步驟 3 起。**

- [ ] 用下面這一份**完整取代** `Dockerfile`（不是加在後面）：

```dockerfile
# PersonalDocAI 的映像（design4.md §8.4 建立；增量六 Phase 90 改成多階段）。
#
# 三個 stage，關係是這樣：
#
#     base ────┬──> cloud-worker   （EC2 上跑的工人；CMD 是 python -m app.workers.cloud_worker）
#              │
#              └──> app            （FastAPI／uvicorn；★ 一定要放最後，理由見下）
#
# ★ `app` 為什麼一定要放在檔案的最後：
#   不帶 `--target` 的 `docker build .` 會建到**最後一個 stage** 為止。
#   compose.yaml 的 app 與 worker 兩個服務都寫 `build: .`（沒有 target:），
#   所以只要 app 在最後，compose 蓋出來的就仍然是同一份 app 映像
#   ——compose.yaml 一個字都不必改（增量六總覽 §10 追認項 j）。
#   把順序調換的後果是**安靜的**：compose 會蓋出一個 CMD 是工人的映像，
#   app 容器起來之後開始去 SQS 收訊息、沒有人聽 8000 埠，而且不會有任何錯誤訊息。
#
# 只負責「映像裡有哪些套件、程式碼放哪、預設怎麼啟動」——要不要盯檔案重啟（--reload）
# 是「啟動指令」的事，寫在 compose 那邊（design4.md §8.4.1）。


# ---------- stage 1：base（套件 ＋ 程式碼；兩個下游 stage 共用這一層）----------
FROM python:3.12-slim AS base

# 不要產生 .pyc、log 直接吐出來不緩衝（不然 docker logs 會延遲看到）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只複製 requirements.txt 再安裝：程式碼改了但套件沒改時，
# Docker 會直接重用上一次安裝好的那一層，build 快很多
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再複製程式碼（含 app/static/ 的網頁，以及 app/workers/ 的雲端工人）
# ★ .dockerignore 排除了 scripts/，所以工人程式一定要放 app/ 底下才會進映像
#   （增量六總覽 §10 追認項 k；放錯地方的話 build 會成功、run 時才 ModuleNotFoundError）
COPY app ./app

# ★ base 刻意不寫 CMD：它不會被直接跑，只是給下面兩個 stage 當底。


# ---------- stage 2：cloud-worker（EC2 上跑的工人）----------
FROM base AS cloud-worker

# GIT_SHA ＝ build 當下的 git commit 短碼，由 --build-arg 傳進來。
# ARG 只在 build 期間存在；用 ENV 把它「烙」成執行期的環境變數，
# 工人啟動時才讀得到（app/core/config.py 的 WORKER_VERSION，預設 "dev"）。
# 這是「EC2 上跑的到底是不是新映像」的唯一可靠驗證方式
# ——工人啟動 log 會印 version=<sha>（增量六總覽 §10 追認項 e、design6 D16）。
ARG GIT_SHA=dev
ENV WORKER_VERSION=$GIT_SHA

# 工人不聽任何埠（design6 D11：EC2 inbound 全關），所以沒有 EXPOSE。
# 它只主動往外連 S3／SQS／ollama.com（全部 TCP 443）。
CMD ["python", "-m", "app.workers.cloud_worker"]


# ---------- stage 3：app（FastAPI；★ 必須是檔案裡的最後一個 stage）----------
FROM base AS app

# 對外的埠。實際發佈到 Mac 的哪個埠由 compose 的 ports 決定
EXPOSE 8000

# 常駐用的啟動指令：**沒有 --reload**（design4.md D10）。
# --host 0.0.0.0 ＝也聽容器外面來的連線；HTTPS 憑證由 bind-mount 掛進來。
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "certs/key.pem", "--ssl-certfile", "certs/cert.pem"]
```

- [ ] 存檔後先確認語法（`--check` **不會真的 build**，只讓 Docker 把 Dockerfile 解析一遍並跑內建的檢查；有語法錯會馬上噴）：

```bash
docker build --check .
```

  預期：印出 `Check complete, no warnings found.`（或只有無害的 style 警告）。
  出現 `dockerfile parse error` → 多半是 `\` 換行那幾行被改壞了，回上面重貼一次。

  > 💡 `docker build --check` 是 `--call=check` 的簡寫，**Buildx 0.15.0（2024 年中）以後**才有；
  > `docker buildx version` 看得到你的版本。太舊沒有這個旗標的話，跳過這一步，直接做 §4.3——
  > 真的建一次也一樣會發現語法錯。

- [ ] **順手收緊 `.dockerignore`：在檔尾加兩行**（一行註解、一行 `deploy/`；既有的行一個字都不動）：

```text
# IAM policy JSON 與 EC2 的 user-data／systemd 設定（Phase 82／91）：只給人與 AWS CLI 用，映像用不到
deploy/
```

  存檔後確認：

```bash
grep -n '^deploy/$' .dockerignore     # 預期恰一行
```

  > 📌 **誠實說明這一行的份量：** 現在的 Dockerfile 只 `COPY requirements.txt` 與 `COPY app`，
  > 所以 `deploy/` 本來就**不會**進映像（`.dockerignore` 管的是「送給 Docker 的 build context」，
  > 不是「映像裡有什麼」）。加這一行是①少送幾個檔案給 daemon、②哪天有人寫了 `COPY . .`
  > 也不會把 policy JSON 打進映像（裡面的帳號 ID 都是 `<ACCOUNT_ID>` 佔位，零機密，但也不該進去）。
  > 一行、零風險、順手做掉；**不要**趁機改其他行。

### 4.3 建工人映像並驗證架構是 arm64

- [ ] 建映像（**在專案根目錄**）：

```bash
docker build \
  --target cloud-worker \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t personaldocai-worker:local \
  .
```

  每個旗標的用途：

  | 旗標 | 用途 |
  |---|---|
  | `--target cloud-worker` | 只建到 `cloud-worker` 這個 stage 就停。**不加的話會建到 `app`**（最後一個 stage），你就得到一個 uvicorn 映像卻取名叫 worker——見 §7 陷阱 1 |
  | `--build-arg GIT_SHA=…` | 把值傳進 Dockerfile 裡的 `ARG GIT_SHA`。`git rev-parse --short HEAD` ＝現在這個 commit 的短碼（7 個十六進位字元，例如 `a53ab57`） |
  | `-t personaldocai-worker:local` | 給映像取名字：`personaldocai-worker`，tag 是 `local`。`local` 這個 tag 是**只在這台 Mac 用**的意思，跟 Phase 91 要推到 ECR 的 `<sha>`／`latest` 不同 |
  | `.` | build context ＝「把這個目錄的內容送給 Docker」。`.dockerignore` 決定哪些不送 |

  預期輸出（結尾）：

```text
 => => naming to docker.io/library/personaldocai-worker:local
```

  `base` 的指令跟改版前的 Dockerfile 逐字相同，所以套件那一層多半直接命中既有快取、幾十秒內結束；
  快取沒命中（例如剛清過 `docker system prune`）才會花 1〜3 分鐘裝一整份 `requirements.txt`。
  之後只要 `requirements.txt` 沒改，套件那一層永遠命中快取。

- [ ] **驗證架構真的是 arm64**（這一條是 ★G2 的加碼項目，總覽 §5.5 最後一段）：

```bash
docker image inspect personaldocai-worker:local --format '{{.Architecture}}'
```

  預期：`arm64`

  > 📌 **為什麼會是 arm64 而你什麼都沒做：** Docker build 預設用「跑 Docker 的這台機器的架構」。
  > 這台 Mac 是 Apple Silicon ＝ arm64，所以預設就對了。
  > EC2 的 `t4g.small` 也是 arm64，兩邊剛好同一種——這是本專案選 `t4g` 的附帶好處。
  > 印出 `amd64` 的話代表你在一台 Intel Mac 上，或 Docker Desktop 設了預設平台——
  > 那就要改用下面的 `buildx` 寫法。

- [ ] **（示範／備用）明寫平台的 buildx 寫法**：

```bash
docker buildx build \
  --platform linux/arm64 \
  --target cloud-worker \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t personaldocai-worker:local \
  --load \
  .
```

  多出來的兩個旗標：

  | 旗標 | 用途 |
  |---|---|
  | `--platform linux/arm64` | 明寫要建哪個架構。**在 arm64 的 Mac 上，這跟不寫是一樣的結果**；在 amd64 機器上它會叫 QEMU 出來模擬（很慢，5〜15 分鐘） |
  | `--load` | buildx 預設把結果留在它自己的快取裡、**不會**放進 `docker images` 看得到的地方。`--load` ＝「建完之後載入本機的映像庫」。忘了它的話下一步 `docker run` 會說找不到映像 |

  跑完之後同樣用 `docker image inspect … --format '{{.Architecture}}'` 驗，一樣要看到 `arm64`。

  > 📌 Phase 94 的 CD 用的就是這條路（GitHub 的 runner 是 amd64，非得模擬不可），
  > 所以在這裡先跑一次、確認它在你的環境跑得動，之後 CD 紅的時候就少一個可疑對象。

### 4.4 在 Mac 上用容器跑工人，重做 Phase 88 的端到端

這一步是 ★G2 的**主要證據**：同一支工人裝進映像之後，仍然能「收訊息 → 拿檔 → 看圖 → 寫結果」。

- [ ] **先把本機的 `.env` 切成 `assume` 模式**（本機不做 EC2 探測，直接假設遠端開著）：

  打開 `.env`，確認／改成這兩行（**只寫變數名與值的形狀，不要把真值貼進任何文件**）：

```ini
CLOUD_ROUTE=assume
CLOUD_RESULT_TIMEOUT_SECONDS=300
```

  改完重啟本機 worker（Celery 那個，不是雲端工人）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker   # 開發模式
# 常駐模式就拿掉 -f compose.dev.yaml：docker compose -f compose.yaml restart worker
```

  > ⚠️ `.env` 改了一定要 restart。`app/core/config.py` 只在**行程啟動時**讀一次 `.env`
  > （`load_dotenv()`），改檔不會自動生效。

- [ ] **開一個新的終端機視窗（終端機 A）**，用容器跑雲端工人：

```bash
cd /Users/linjunting/personalDocAI
docker run --rm \
  --env-file .env \
  -e CLOUD_ROUTE=off \
  personaldocai-worker:local
```

  > ⚠ 這個視窗**不要** `set -a; . ./.env`、也**不要** `unset`：容器靠 `--env-file` 直接讀檔，
  > 要的正是 `.env` 那把 `personaldocai-mac` 的 key（規矩與 Phase 88 §4 步驟 6 的終端機 A 相同）。

  每個旗標的用途：

  | 旗標 | 用途 |
  |---|---|
  | `--rm` | 容器停掉之後自動刪掉（不留一堆 exited 的殘骸）。這是一次性的除錯容器，不需要留 |
  | `--env-file .env` | 把 `.env` 裡每一行 `KEY=VALUE` 都設成容器裡的環境變數。工人要用的是：`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_REGION`、`S3_BUCKET`、`SQS_JOBS_QUEUE_URL`、`SQS_RESULTS_QUEUE_URL`、`OLLAMA_API_KEY`、`OLLAMA_CLOUD_VLM_MODEL`、`VLM_MAX_ATTEMPTS` |
  | `-e CLOUD_ROUTE=off` | **蓋掉** `.env` 裡的 `CLOUD_ROUTE=assume`。理由見下面那個框 |

  > 📌 **為什麼要多一個 `-e CLOUD_ROUTE=off`：**
  > `CLOUD_ROUTE` 是**本機端**（`app/dependencies.py` 的 `get_cloud_route()`）用的設定——
  > 它決定「本機要不要把 job 送去雲端」。**工人完全不看它**：工人的工作是
  > 「從 jobs 佇列拿訊息、做事、寫回去」，它不需要知道本機在想什麼。
  >
  > 所以在容器裡把它設成 `off` **對工人的行為一點影響都沒有**，
  > 純粹是「這個容器不是本機端，別讓它讀到會誤導人的值」的衛生習慣。
  > 想省事的話不加也可以，行為完全一樣。

  > ⛔ **容器裡絕對不可以設 `AWS_ENDPOINT_URL`。**
  > 那個變數是 pytest 第五道安全網（`wire_fake_cloud`）用來把 boto3 指到死埠
  > `http://127.0.0.1:9` 的。如果它跑進 `.env`、又被 `--env-file` 帶進容器，
  > 工人會安靜地打不到任何 AWS 服務——而且錯誤訊息長得像網路問題，很難聯想。
  > 先確認一下：
  >
  > ```bash
  > grep -n "AWS_ENDPOINT_URL" .env
  > ```
  >
  > 預期：**沒有輸出**。有輸出就把那一行刪掉（那是測試用的，不該在 `.env` 裡）。

  > ⚠ **`.env` 的值不要加引號。** `docker run --env-file` 對引號**沒有特殊處理**——
  > `OLLAMA_API_KEY="abc"` 進到容器裡就是**連引號一起**的 `"abc"`：打 ollama.com 會 401、
  > 打 AWS 會 `InvalidClientTokenId`。而 app／Celery 容器與 Phase 88 在 host 直跑工人走的是
  > python-dotenv（會把引號剝掉），所以同一份 `.env` 那邊全好、只有這個容器壞（§7 陷阱 13）。先看一眼：
  >
  > ```bash
  > grep -n '="' .env ; grep -n "='" .env
  > ```
  >
  > 預期：**兩個都沒有輸出**。有的話把引號拿掉。

  預期輸出（第一行；格式是 Phase 88 定案的 `cloud_worker 啟動 version=%s region=%s bucket=%s`，
  前面的 `INFO:     ` 是 Phase 88 幫工人 logger 設的格式）：

```text
INFO:     cloud_worker 啟動 version=<你剛才傳的 sha> region=ap-northeast-1 bucket=<你的 bucket 名>
```

  然後它會停在那裡不動——那是**正常的**：它正在用長輪詢（最多 20 秒）跟 SQS 要訊息，
  沒有訊息就再問一次，安安靜靜地一直等。

  ✅ **`version=` 後面印出來的那串要跟 `git rev-parse --short HEAD` 一樣。**
  印出 `version=dev` 代表 `--build-arg GIT_SHA=…` 沒傳到（見 §7 陷阱 3）。

- [ ] **回到原本的終端機（終端機 B）**，上傳一張**檔名明確非敏感**的圖：

```bash
cd /Users/linjunting/personalDocAI
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/path/to/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

  預期：一段 JSON（恰三鍵 `job_id`／`filename`／`content_type`）＋ 下一行 `202`。

  > 📌 檔名很重要——隱私閘門的規則版**只看檔名**（總覽 §10 追認項 f）。
  > `receipt-test.png` 會命中 `NON_SENSITIVE_KEYWORDS` 裡的 `receipt`，
  > 判成 `NON_SENSITIVE`，才有資格走雲端。
  > 檔名取成 `IMG_1234.png` 會被判 `UNCERTAIN` ＝ 留在本機，那就驗不到這條路了。

- [ ] **回終端機 A 看工人的 log**，應該在幾秒內看到：

```text
INFO:     AI 開始 kind=vlm backend=cloud model=<你的雲端模型名>
INFO:     AI 結束 kind=vlm backend=cloud model=… elapsed_s=… ok=true understood=true text_chars=…
INFO:     job <job_id>：result.json 已放好、results 已送出（worker_version=<sha>）
```

  ✅ 最後那一行的 `worker_version=` 也要是你的 sha——它會一起寫進 `result.json`（Phase 87 定的格式）。

- [ ] **看本機 worker（Celery）的 log**，確認走的是雲端路而不是 fallback：

```bash
docker compose logs --tail=200 worker | grep -E "route=|fallback=|kind=embed"
```

  預期：
  - 看得到 `job <job_id> route=cloud verdict=NON_SENSITIVE`（Phase 79 定的格式，與 Phase 78 的
    `route=local verdict=…` 同款；測試用 caplog 逐字釘住，不會有「等價字樣」）
  - **不該**看到 `fallback=` 那一行
  - 看得到 `AI 開始 kind=embed backend=local`（D13：向量一律本機算）

- [ ] **確認照片真的進了資料庫、S3 已經清乾淨、job 已經消失**：

```bash
# ① 照片列 +1（記下最後一列的 id 與 text）
psql -d PersonalDocAI -c "select id, left(text, 40) as text from photo order by id desc limit 1"

# ② S3 的 documents/ 應該是空的（成功之後本機會刪掉三個物件）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ 不能省：讓 CLI 回到 ~/.aws 的 admin profile。
                                               #   .env 那把 key 有 ListBucket、這條 list 跑得過，但後面
                                               #   purge-queue 這類管理指令沒有（Phase 88 陷阱 12）
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
# 預期：回應裡沒有 Contents（只有一堆 metadata）

# ③ 進度面板應該沒有這一筆了（成功 ＝ job 被刪掉）
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
# 預期：jobs 陣列裡沒有剛才那個 job_id；pending_count 比剛才多 1

# ④ staging 沒有殘檔
ls data/staging/
# 預期：空的
```

- [ ] **反面驗一次：敏感檔零 S3**（Demo 1 的本機版；證明容器化沒有破壞閘門）：

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/path/to/身分證正面.png" \
  https://127.0.0.1:8000/photos       # 預期：202

docker compose logs --tail=100 worker | grep "route=local"
# 預期：route=local verdict=SENSITIVE

aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
# 預期：沒有任何以這個 job_id 開頭的物件
```

  > ⚠️ 這一張會走**本機** gemma4 看圖，需要 64〜88 秒（9 欄 prompt 可到 2〜5 分鐘）。
  > **不要在等它的同時再上傳別的東西**——Phase 48 踩過：兩件事同時打本機模型，
  > db container 被壓垮、postmaster 花 2 分鐘才殺得掉子行程。一次一件事。

- [ ] **收工：回終端機 A 按 `Ctrl+C`**，工人應該優雅停下（Phase 88 做的訊號處理）：
      印一行 **「收到停止訊號」**、把手上那一則訊息做完之後結束，容器因為 `--rm` 自動刪掉。
      （`docker stop` 送的 SIGTERM 走的是同一條路，所以 EC2 上 `systemctl stop` 也是這個行為。）

  確認沒有殘留的容器：

```bash
docker ps -aq --filter ancestor=personaldocai-worker:local
```

  預期：沒有輸出（`-q` 只印容器 ID，一個都沒有＝`--rm` 已經清乾淨；
  不加 `-q` 的話 `docker ps` 就算沒東西也會印一行表頭，看起來像有輸出）。

- [ ] **把 `.env` 改回 `CLOUD_ROUTE=off`，再 restart 一次本機 worker**（Phase 86／88 收工時的同一條規則；
      總覽 §10 追認項 l：`assume` 只給丁段與除錯用）：

```ini
CLOUD_ROUTE=off
```

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker   # 常駐模式就拿掉 -f compose.dev.yaml
grep -n "^CLOUD_ROUTE=" .env      # 預期：CLOUD_ROUTE=off
```

  > ⚠ 忘了改回去的後果：雲端工人已經停了，之後**每一張非敏感照片**都會先送去 S3、
  > 傻等 `CLOUD_RESULT_TIMEOUT_SECONDS`（300 秒）才 fallback 本機——看起來像「上傳忽然變超慢」。
  > Phase 92 真機上線時才把它改成 `ec2`。

### 4.5 證明 `compose.yaml` 零改動而且行為不變

這一步是總覽 §10 追認項 j 的**驗證**：多階段 Dockerfile 沒有把 compose 弄壞。

- [ ] **第一個證據：`docker compose config` 的輸出與改版前逐字相同**

```bash
docker compose config > /tmp/p90-compose-after.yaml
diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml
```

  預期：**沒有任何輸出**（diff 沒輸出 ＝ 兩份完全一樣）。

  > 📌 為什麼這是有效的證據：`docker compose config` 會把 `compose.yaml` ＋ 環境變數
  > 展開成「Compose 實際看到的完整設定」。它一個字都沒變 ＝ compose 這一層完全沒被動到。
  > （這只證明**設定**沒變，不證明**建出來的映像**沒變——那是下一條在驗的。）

- [ ] **第二個證據：`git status` 看不到 `compose.yaml`**

```bash
git status --short -- compose.yaml compose.dev.yaml
```

  預期：**沒有輸出**（兩份 compose 檔一個字都沒改）。

- [ ] **第三個證據：重建 app 映像，四個服務照常起來**（不帶 `--target`，
      所以建到最後一個 stage ＝ `app`）

  > ⚠ **這一條要在常駐模式驗。** `compose.dev.yaml` 會把 `app` 的 `command:` 覆寫成它自己那條 uvicorn，
  > 開發模式下就算 stage 順序放錯，COMMAND 欄也照樣顯示 uvicorn——看不出問題。
  > 現在若是開發模式，先停掉再用常駐那一份拉起來（CLAUDE.md 指令區「開發 → 常駐」兩步）。

```bash
docker compose -f compose.yaml -f compose.dev.yaml stop    # 只有現在是開發模式才需要這一行
docker compose -f compose.yaml up -d --build
docker compose ps --no-trunc
docker compose config --services       # 預期恰四行：db／redis／app／worker
docker image inspect personaldocai-app --format '{{.Config.Cmd}}'
# 預期：[uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem]
#   ↑ 這一條不分模式都有效：它看的是映像本身的預設啟動指令，compose 覆不覆寫 command 都影響不了它
```

  預期：四個服務 `db`／`redis`／`app`／`worker` 都在；
  `db` 與 `redis` 是 `Up (healthy)`；
  **`app` 的 COMMAND 欄是 `uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-*`**
  （不是 `python -m app.workers.cloud_worker`——那就代表 stage 順序放錯了）；
  `worker` 的 COMMAND 欄含 `--concurrency=2`。

  > ⚠️ `--no-trunc` 不能省。不加的話 COMMAND 只印開頭 20 個字左右，
  > 你會看到 `"uvicorn app.main:a…"` 就以為通過了，其實根本沒顯示到後面。
  > 而「stage 順序放錯」正好是要靠這一欄才看得出來的錯。

- [ ] **第四個證據：app 真的還活著**：`curl -k -s https://127.0.0.1:8000/health`
      → `{"status":"ok"}`

- [ ] **第五個證據：映像裡的東西剛剛好**（兩條指令與預期輸出寫在 §6 驗收清單的第 4、5 條，
      在那裡一併驗即可——重點是「工人程式真的進了映像」與「`data`／`certs`／`.env` 沒進去」）。

### 4.6 TDD：新開 `tests/integration/test_design6_error_paths.py`（4 顆掃碼）

> 📌 **這個檔在本 phase 開檔，不等到 Phase 95**（總覽 §10 追認項 B）。
> 理由：90／93／94 各自都有「部署設定檔掃碼」要放，全堆到 95 會讓 95 變成
> 一個要重讀五份設定檔的大 phase。

#### 步驟 1：先寫測試（紅）

- [ ] 建立 `tests/integration/test_design6_error_paths.py`，內容如下（**完整可貼**）：

```python
"""增量六（design6.md）的錯誤路徑與「明確不做」收尾驗證。

體例沿用 Phase 25／37／44／71 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py、test_design5_error_paths.py）：
**先盤點、只補 ★ 缺口**——大多數行為已經由各 phase 自己的測試檔釘住了，
本檔只放「沒有別人守著」的那些，以及「掃設定檔文字」這種不屬於任何服務模組的斷言。

⚠ 本檔**分三次寫完**（增量六總覽 §10 追認項 B）：

| 何時 | 誰加 | 內容 |
|---|---|---|
| **Phase 90**（本次開檔） | 戊 | `Dockerfile` 多階段與 `compose.yaml` 零改動的掃碼（4 顆） |
| Phase 93 | 己 | GitHub OIDC trust JSON 的掃碼（4 顆：`sub` 鎖 main、無萬用字元、aud、無寫死帳號 ID） |
| Phase 94 | 己 | CD workflow 的掃碼（6 顆：綁 test、id-token、arm64、target、sha tag、無金鑰） |
| Phase 95 | 收尾 | §8 錯誤表逐列補缺口 ＋ §0 六禁與 §1.2 被否決清單的掃碼（10 顆） |

⚠ 本檔**完全不連任何外部服務**：它讀的是磁碟上的純文字檔（`Dockerfile`、`compose.yaml`），
   零 AWS、零 Docker daemon、零 Redis、零 Ollama。所以三個死埠一起指的時候顆數不會變。
"""

from __future__ import annotations

import re
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]


def dockerfile原始碼() -> str:
    """讀專案根目錄的 Dockerfile 純文字。

    刻意不解析、不呼叫 docker——本檔在 CI 上也要能跑，而 CI 沒有 Docker daemon
    （.github/workflows/test.yml 只起一個 pgvector 附屬容器）。
    """
    return (專案根目錄 / "Dockerfile").read_text(encoding="utf-8")


def compose原始碼() -> str:
    """讀專案根目錄的 compose.yaml 純文字（與 test_design5_error_paths.py 同一手法）。"""
    return (專案根目錄 / "compose.yaml").read_text(encoding="utf-8")


def compose服務清單() -> list[str]:
    """把 compose.yaml 的 `services:` 底下那一層的服務名依序抓出來。

    ⚠ **一定要先把 services: 區塊切出來再抓**，不可以直接對整份檔跑
      `^  ([a-z][\\w-]*):$`——檔尾的 `volumes:` 底下還有 `  pgdata:` 與 `  redisdata:`
      兩個**同樣是兩格縮排、同樣以冒號結尾**的名字，會被一起抓進來，
      於是斷言變成 6 個而永遠紅（實測過）。

    正規式說明：
      ^services:\\n   從 `services:` 那一行的下一行開始
      (.*?)           非貪婪地吃內容
      (?=^\\w|\\Z)     直到「下一個頂到最左邊的字」（也就是 `volumes:`）或檔尾為止
    """
    區塊 = re.search(r"^services:\n(.*?)(?=^\w|\Z)", compose原始碼(), re.M | re.S)
    assert 區塊, "compose.yaml 裡找不到 services: 區塊"
    return re.findall(r"^  ([a-z][\w-]*):$", 區塊.group(1), re.M)


def stage名稱清單() -> list[str]:
    """把 Dockerfile 裡每一個 `FROM … AS <名字>` 的名字依出現順序抓出來。

    正規式說明：
      ^FROM\\s+       行首的 FROM 加至少一個空白
      \\S+            基底映像或上游 stage 名（不含空白的一串）
      \\s+AS\\s+      中間的 AS（Docker 不分大小寫，這裡用 re.I）
      ([\\w.-]+)      我們要的 stage 名字（英數、底線、點、減號）

    用 re.M 讓 ^ 對每一行生效；用 re.I 讓 `as` 小寫也抓得到。
    """
    return re.findall(r"^FROM\s+\S+\s+AS\s+([\w.-]+)", dockerfile原始碼(), re.M | re.I)


# ---- Phase 90：Dockerfile 多階段（design6 D15／D16、總覽 §10 追認項 j）----


def test_Dockerfile有cloud_worker這個target():
    """design6 §11 第 5 列：worker 映像走「多階段或第二 target」。

    我們選了多階段（總覽 §10 追認項 j），所以一定要有一個叫 cloud-worker 的 stage
    ——`docker build --target cloud-worker` 靠的就是這個名字。
    名字打錯（例如 cloud_worker、cloudworker）的話 build 會直接失敗，
    但**CD 的 yaml 也是照這個名字寫的**，兩邊要對得起來，所以在這裡釘死。
    """
    名字們 = stage名稱清單()

    assert "cloud-worker" in 名字們, (
        f"Dockerfile 必須有一個 `FROM … AS cloud-worker` 的 stage；目前只有：{名字們}"
    )
    # 順便釘住共用底座還在：兩個下游 stage 要接在同一個 base 上，
    # 才不會變成「裝兩次套件」或「兩份會漂移的程式碼複製」
    assert "base" in 名字們, f"Dockerfile 應該有共用的 base stage；目前只有：{名字們}"


def test_Dockerfile的app階段在最後():
    """總覽 §10 追認項 j ＋ §7 鐵律 11：compose.yaml 本增量零改動。

    ★ 這一顆守的是一個**安靜的**壞法：
      不帶 --target 的 `docker build .` 會建到**最後一個 stage**。
      compose.yaml 的 app 與 worker 兩個服務都寫 `build: .`（沒有 target:），
      所以 app 一旦不在最後，compose 就會蓋出一個「CMD 是雲端工人」的映像，
      然後 app 容器起來之後跑去 SQS 收訊息、沒有人聽 8000 埠
      ——**build 不會失敗、compose config 也看不出來**，只有服務莫名其妙不通。

    有人把 cloud-worker 搬到檔案最後的那一刻，這一顆會紅。
    """
    名字們 = stage名稱清單()

    assert 名字們, "Dockerfile 裡一個具名 stage 都沒有？（多階段改壞了）"
    assert 名字們[-1] == "app", (
        "app 必須是 Dockerfile 裡的**最後一個** stage，"
        f"否則 compose 的 `build: .` 會蓋出工人映像。目前順序：{名字們}"
    )


def test_Dockerfile的cloud_worker帶ARG_GIT_SHA():
    """design6 D16 ＋ 總覽 §10 追認項 e：靠 WORKER_VERSION 驗「跑的是不是新映像」。

    三件事一起釘：
      ① 有 `ARG GIT_SHA`（build 時傳得進來）
      ② 有 `ENV WORKER_VERSION=$GIT_SHA`（烙成執行期環境變數，工人啟動 log 印得出來）
      ③ cloud-worker 的 CMD 真的是跑 app.workers.cloud_worker 這個模組

    少了 ① 或 ②，Phase 94 的 CD 推上去的映像啟動時只會印 version=dev，
    Demo 3 就再也分不出「跑的是新的還是舊的」——而那正是 D16 唯一的驗證手段。
    """
    原始碼 = dockerfile原始碼()

    # ★ 三條都用「行首錨定」的正規式（re.M 讓 ^ 對每一行生效），刻意不用 `in`：
    #   `"ENV WORKER_VERSION=$GIT_SHA" in 原始碼` 這種寫法連被註解掉的
    #   `# ENV WORKER_VERSION=$GIT_SHA` 都會算命中，測試就假綠了——§4.6 步驟 3 的變異 2 在驗這件事。
    assert re.search(r"^ARG GIT_SHA(=\S*)?\s*$", 原始碼, re.M), (
        "cloud-worker stage 必須有 `ARG GIT_SHA`（CD 用 --build-arg 傳）"
    )
    assert re.search(r"^ENV WORKER_VERSION=\$GIT_SHA\s*$", 原始碼, re.M), (
        "必須把 ARG 烙成 ENV WORKER_VERSION，工人啟動 log 才印得出 version=<sha>"
    )
    # CMD 用 JSON 陣列寫法（exec form），訊號才收得到——Ctrl+C／SIGTERM 要能停得下來
    assert re.search(r'^CMD \[.*"app\.workers\.cloud_worker".*\]\s*$', 原始碼, re.M), (
        "cloud-worker 的 CMD 必須跑 python -m app.workers.cloud_worker"
    )


def test_compose_yaml沒有新增服務也沒有AWS設定():
    """總覽 §7 鐵律 11 ＋ §10 追認項 j：Dockerfile 改多階段之後，compose **不必跟著動**。

    ★ 本顆的主軸是**「多階段沒有波及 compose」**，所以守的是下面三件事：

      ① `app` 與 `worker` 的 `build:` 仍然只是 `.`，而且整份檔**沒有 `target:` 字樣**。
         這正是「app stage 放最後」換來的東西：不帶 `--target` 的 `docker build .`
         會停在最後一個 stage ＝ app，所以 compose 不必知道 stage 的存在。
         哪天有人在 compose 裡加 `target:`，就代表 Dockerfile 的 stage 順序被動過了
         ——這一顆會在那一刻紅。
      ② `image: personaldocai-app` 兩處都在（app 與 worker 共用同一份映像）。
      ③ 服務**恰好**仍是 db／redis／app／worker 四個
         （手滑加第五個 cloud-worker 服務的話，它開機就會自己跑起來、默默把 SQS
           訊息吃光——而 EC2 上那台也在收同一條佇列）。

    📌 **「AWS 變數名（`AWS_REGION`／`S3_BUCKET`／`SQS_*_QUEUE_URL`…）不出現在
       `compose*.yaml`」不歸這一顆守，那是 Phase 95 的
       `test_compose沒有為了雲端新增任何服務`**——兩顆不重複，各守各的。
    """
    原始碼 = compose原始碼()

    # ① 沒有任何 target:（先驗這條——它是最直接的訊號），而且 build 仍是 `.`
    assert "target:" not in 原始碼, (
        "compose.yaml 不該出現 `target:`——app stage 放在 Dockerfile 最後，"
        "就是為了讓 compose 不必指定 stage（總覽 §10 追認項 j）"
    )
    assert 原始碼.count("build: .") == 2, (
        "app 與 worker 兩個服務都應該仍是 `build: .`（用同一份 Dockerfile 的最後一個 stage）"
    )

    # ② 兩個服務共用同一份映像名
    assert 原始碼.count("image: personaldocai-app") == 2, (
        "app 與 worker 必須指向同一個映像名 personaldocai-app"
    )

    # ③ 服務清單：恰好四個，順序也不變
    服務們 = compose服務清單()
    assert 服務們 == ["db", "redis", "app", "worker"], (
        f"compose.yaml 的服務必須仍是四個（db／redis／app／worker）；目前是：{服務們}"
    )
```

#### 步驟 2：**在改 Dockerfile 之前**跑它，確認 3 顆紅、1 顆綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：**3 failed, 1 passed**。逐顆的紅字長這樣（現在的 `Dockerfile` 還是單階段、
  一個 `FROM … AS …` 都沒有，所以 `stage名稱清單()` 回的是空清單 `[]`）：

```text
FAILED …::test_Dockerfile有cloud_worker這個target
    AssertionError: Dockerfile 必須有一個 `FROM … AS cloud-worker` 的 stage；目前只有：[]
FAILED …::test_Dockerfile的app階段在最後
    AssertionError: Dockerfile 裡一個具名 stage 都沒有？（多階段改壞了）
FAILED …::test_Dockerfile的cloud_worker帶ARG_GIT_SHA
    AssertionError: cloud-worker stage 必須有 `ARG GIT_SHA`（CD 用 --build-arg 傳）
PASSED …::test_compose_yaml沒有新增服務也沒有AWS設定
```

  ✅ **第 4 顆一開始就綠是正確的**：它守的是「Dockerfile 改多階段之後 compose **不必跟著動**」，
  而現在 compose 本來就沒被改。它的紅色要靠步驟 3 的變異 3／4 才看得到。
  （「AWS 變數名不出現在 `compose*.yaml`」**不歸這一顆守**，那是 Phase 95 的
  `test_compose沒有為了雲端新增任何服務`——兩顆刻意不重複。）

- [ ] **現在回去做 §4.2**（把 `Dockerfile` 換成三階段那一份），做完再跑一次：

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：**4 passed**。

#### 步驟 3：變異測試——證明這四顆真的抓得到 bug

> 📌 掃碼測試最容易變成「假綠」（斷言寫錯、掃錯檔、正規式永遠匹配不到但斷言用的是 `not in`）。
> 唯一可靠的檢查方式是**故意把產品檔改壞、看測試會不會紅**。
> 下面四個變異各做一次，**每一次都要記得改回來**。

- [ ] **變異 1：把 `app` stage 搬到不是最後的位置**

```bash
cp Dockerfile /tmp/Dockerfile.bak            # 先備份，等一下要還原
```

  手動編輯 `Dockerfile`，把 `# ---------- stage 3：app …` 那一整段（從 `FROM base AS app`
  到檔尾）剪下、貼到 `# ---------- stage 2：cloud-worker …` 那一段的**前面**。

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：`test_Dockerfile的app階段在最後` **紅**，訊息含
  `app 必須是 Dockerfile 裡的**最後一個** stage`。

```bash
cp /tmp/Dockerfile.bak Dockerfile            # 還原
pytest tests/integration/test_design6_error_paths.py -q   # 預期：4 passed
```

- [ ] **變異 2：把 `ENV WORKER_VERSION=$GIT_SHA` 那一行註解掉**

```bash
cp Dockerfile /tmp/Dockerfile.bak
sed -i '' 's/^ENV WORKER_VERSION=\$GIT_SHA/# ENV WORKER_VERSION=$GIT_SHA/' Dockerfile
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：`test_Dockerfile的cloud_worker帶ARG_GIT_SHA` **紅**，訊息含 `必須把 ARG 烙成 ENV WORKER_VERSION`。

  （這個變異就是測試裡用**行首錨定的正規式**、而不是 `"ENV WORKER_VERSION=$GIT_SHA" in 原始碼` 的理由：
  子字串比對連被註解掉的那一行都會算命中，變異 2 會維持綠——寫這份計畫時實測過。）

```bash
cp /tmp/Dockerfile.bak Dockerfile
pytest tests/integration/test_design6_error_paths.py -q   # 預期：4 passed
```

  > 💡 `sed -i ''`（`-i` 後面接一個空字串）是 **macOS 版 sed** 的寫法：「就地修改、不留備份檔」。
  > Linux 上是 `sed -i`（不接空字串）。這台是 Mac，用上面那一種。

- [ ] **變異 3：在 `compose.yaml` 加一個假的第五個服務**

```bash
cp compose.yaml /tmp/compose.yaml.bak
```

  手動在 `services:` 底下（`worker:` 那一段之後）、`volumes:` 之前加三行：

```yaml
  cloudworker:
    image: personaldocai-worker:local
    restart: "no"
```

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：`test_compose_yaml沒有新增服務也沒有AWS設定` **紅**，訊息會把五個服務名印出來。

```bash
cp /tmp/compose.yaml.bak compose.yaml
git status --short -- compose.yaml    # 預期：沒有輸出（真的還原了）
pytest tests/integration/test_design6_error_paths.py -q   # 預期：4 passed
```

- [ ] **變異 4：在 `compose.yaml` 的 `app` 加一個 `target:`**（模擬「有人把 stage 順序改了、
      只好在 compose 補指定」——這正是本顆要擋的那個未來）

```bash
cp compose.yaml /tmp/compose.yaml.bak
```

  手動把 `app:` 底下的 `build: .` 那一行換成三行：

```yaml
    build:
      context: .
      target: app
```

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：`test_compose_yaml沒有新增服務也沒有AWS設定` **紅**，
  訊息含 `compose.yaml 不該出現 \`target:\``（`build: .` 的數量也會從 2 掉到 1）。

```bash
cp /tmp/compose.yaml.bak compose.yaml
git status --short -- compose.yaml    # 預期：沒有輸出
pytest tests/integration/test_design6_error_paths.py -q   # 預期：4 passed
rm -f /tmp/Dockerfile.bak /tmp/compose.yaml.bak
```

#### 步驟 4：全量回歸

```bash
pytest -q
```

  預期：**662 passed ＋ 0 skipped**（開工基線 658 ＋ 本 phase 的 4 顆）。

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

  預期：**662 passed**，與上一條逐字相同（零外部依賴實證）。

#### 步驟 5：格式與 lint

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

  預期：`… files already formatted` ＋ `All checks passed!`

  沒過的話（`--check` 只檢查不改檔）：

```bash
ruff format app tests scripts && ruff check --fix app tests scripts
```

  改完再跑一次 `--check` 版本確認。

#### 步驟 6：commit

```bash
git add Dockerfile .dockerignore tests/integration/test_design6_error_paths.py
git status --short          # 確認 staged 的**只有這三個檔**
git commit -m "feat: Phase 90 Dockerfile 改多階段（base→cloud-worker→app，app 放最後）＋arm64 工人映像；.dockerignore 排除 deploy/；新開 test_design6_error_paths.py 放 4 顆掃碼（658→662 tests，compose.yaml 零改動）"
```

> ⚠️ `git add` 一定要**明列檔案**，不要 `git add -A`。
> `.env` 有 `.gitignore` 擋著，但 `/tmp` 的備份檔、`docs/plan/` 的計畫檔都不該混進這一筆。
>
> ⚠️ commit 節奏由產品負責人決定。**未指示前不要自己 commit**，也不要把計畫檔搬進 `finish/`
> （`git mv` 會直接 stage）——總覽 §7 鐵律 12。

### 4.7 ★ 閘門 G2：交給產品負責人

> 🚦 **G2 是「人」的動作，實作者不可以自己勾掉。**
> 下面每一條都只是**證據**；「看過證據、同意往下走」的那個動作必須由**產品負責人**做出來
> ——一句明確的話（口頭、對話、或 dev-prompt 檔案）。

- [ ] 把下面這張表填好（每一條都貼上你實際跑出來的輸出），交給產品負責人：

| # | 要驗的事 | 指令 | 預期 |
|---|---|---|---|
| 1 | 工人在 Mac 上跑通（Phase 88 的丁段驗收） | Phase 88 §4 的端到端 | 本機送出 → 工人看圖 → `result.json` → results → 本機 GetObject 入庫 |
| 2 | **arm64 映像建得出來** | `docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t personaldocai-worker:local .` | 最後一行 `naming to … personaldocai-worker:local` |
| 3 | **架構真的是 arm64** | `docker image inspect personaldocai-worker:local --format '{{.Architecture}}'` | `arm64` |
| 4 | **容器跑得起來、版本號正確** | `docker run --rm --env-file .env -e CLOUD_ROUTE=off personaldocai-worker:local` | 第一行 `INFO:     cloud_worker 啟動 version=<sha> region=… bucket=…`，`<sha>` 等於 `git rev-parse --short HEAD` |
| 5 | **用容器重做端到端成功** | §4.4 全套 | 照片列 +1、S3 `documents/` 空、job 消失、`kind=vlm backend=cloud` ＋ `kind=embed backend=local` |
| 6 | **敏感檔仍然零 S3** | §4.4 最後一組 | `route=local verdict=SENSITIVE`，S3 無該 job_id 的物件 |
| 7 | **compose 零改動** | `diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml` | 沒有輸出 |
| 8 | **四個服務照常** | `docker compose -f compose.yaml up -d --build` ＋ `docker compose ps --no-trunc` | 四個都 Up；app 的 COMMAND 是 uvicorn（不是工人） |
| 9 | **顆數** | `pytest -q` | 662 passed ＋ 0 skipped |
| 10 | **零外部依賴** | 三個死埠一起指 | 662 passed，與第 9 條相同 |

- [ ] **等產品負責人明說**（原話例：「工人在容器裡跑通了，可以開 EC2 了」）。

  ❌ 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
  「先做 91，之後再回來補確認」。

  **沒過 G2 的話：** Phase 91〜95 全部停擺。理由很實際：EC2 一開就開始扣**點數**，
  而點數用完會**關帳**（Free plan 不扣卡，資源直接消失）。
  工人本身有 bug 的話，你會在一台**看不到 shell、只能靠 SSM** 的機器上除錯——比在 Mac 上難十倍。

  **卡住時怎麼辦：**
  1. 先分清楚是「工人邏輯錯」還是「AWS 權限錯」——`python scripts/aws_check.py s3 sqs` 兩個都 OK 就是邏輯問題。
  2. 工人邏輯錯 → 回 **Phase 87**（`process_job_message`）。
  3. 主迴圈或訊號處理錯 → 回 **Phase 88**。
  4. 映像 build 不出來或跑不動 → 回**本 phase** §4.2／§4.3。
  ❌ **不要**「上 EC2 再說，反正那邊 log 也看得到」。

---

## 5. ASCII 圖：三個 stage 的關係，以及誰用哪一個

```text
                       Dockerfile（一份檔，三個 stage）
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │                                                                              │
 │   FROM python:3.12-slim AS base          ← stage 1：套件 ＋ 程式碼            │
 │     ENV PYTHONDONTWRITEBYTECODE / PYTHONUNBUFFERED                           │
 │     WORKDIR /app                                                             │
 │     COPY requirements.txt ; RUN pip install                                  │
 │     COPY app ./app          （含 app/workers/cloud_worker.py）                │
 │     ★ 沒有 CMD —— 它不會被直接跑                                             │
 │              │                                                               │
 │              ├──────────────────────────┐                                    │
 │              ▼                          ▼                                    │
 │   FROM base AS cloud-worker    FROM base AS app        ← ★ app 必須在最後     │
 │     ARG GIT_SHA=dev              EXPOSE 8000                                 │
 │     ENV WORKER_VERSION=$GIT_SHA  CMD uvicorn … --ssl-*                       │
 │     CMD python -m app.workers.cloud_worker                                   │
 │                                                                              │
 └──────────────────────────────────────────────────────────────────────────────┘
        │                                        │
        │ docker build --target cloud-worker     │ docker build .（不帶 --target
        │   -t personaldocai-worker:local .      │   ＝停在最後一個 stage ＝ app）
        ▼                                        ▼
  personaldocai-worker:local              personaldocai-app
  （arm64；本 phase 在 Mac 上手動          （compose.yaml 的 app 與 worker
    docker run；Phase 91 推 ECR；            兩個服務共用；一個字都沒改）
    Phase 92 在 EC2 上跑）                        │
        │                                        ├── app 服務：CMD uvicorn（映像的預設）
        │                                        └── worker 服務：compose 覆寫成 celery …
        │
        ▼
 ┌────────────────────────── 本 phase §4.4 的端到端（全部在這台 Mac 上）─────────┐
 │                                                                              │
 │  終端機 B：curl -F file=@receipt-test.png  https://127.0.0.1:8000/photos → 202│
 │  容器 app ──> data/staging/{job_id}.png ──> Redis ──> 容器 worker（Celery）   │
 │        Privacy Gate ＝ NON_SENSITIVE；CLOUD_ROUTE=assume ＝ 遠端當作開著      │
 │                     PutObject context.json ＋ input.png                      │
 │                     SendMessage jobs { job_id, s3_key }  │                   │
 │                                            ┌─────────── 真 AWS（東京）───────┐│
 │                                            │  S3  $S3_BUCKET/documents/…    ││
 │                                            │  SQS personaldocai-jobs        ││
 │                                            │  SQS personaldocai-results     ││
 │                                            └────────────────────────────────┘│
 │                                                          ▲       │           │
 │  終端機 A：docker run --rm --env-file .env               │       │           │
 │            personaldocai-worker:local  ──ReceiveMessage──┘       │           │
 │            （arm64 容器；就是等一下要放到 EC2 上的那一個）        │           │
 │              GetObject input ＋ context → Ollama Cloud 看圖       │           │
 │              （kind=vlm backend=cloud）                           │           │
 │              PutObject result.json ─> SendMessage results ───────┘           │
 │  容器 worker（Celery）ReceiveMessage results ──> GetObject result.json       │
 │              本機 embed（kind=embed backend=local，bge-m3）                   │
 │              INSERT photo ＋ 存原圖 ＋ 縮圖 ──> 刪 S3 三物件 ──> 刪 job       │
 └──────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 驗收清單

每一條都附指令與預期輸出；全部打勾才算完成。

- [ ] **`Dockerfile` 是三個 stage，順序正確**

```bash
grep -n "^FROM" Dockerfile
```

  預期恰三行，依序是：
  `FROM python:3.12-slim AS base`／`FROM base AS cloud-worker`／`FROM base AS app`。

- [ ] **`.dockerignore` 多了 `deploy/`，其他行沒動**

```bash
grep -n '^deploy/$' .dockerignore                 # 預期恰一行
git diff --stat -- .dockerignore                   # 預期：1 file changed, 2 insertions(+)（零刪除）
```

- [ ] **arm64 工人映像建得出來，架構正確**

```bash
docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t personaldocai-worker:local .
docker image inspect personaldocai-worker:local --format '{{.Architecture}}'
```

  預期：`arm64`

- [ ] **容器跑得起來，版本號等於當下的 commit 短碼**

```bash
git rev-parse --short HEAD
docker run --rm --env-file .env -e CLOUD_ROUTE=off personaldocai-worker:local
```

  預期：第一行 log 的 `version=` 後面與上一行輸出相同。看完按 `Ctrl+C` 停掉。

- [ ] **工人程式真的在映像裡**

```bash
docker run --rm personaldocai-worker:local ls /app/app/workers
```

  預期：`__init__.py`  `cloud_worker.py`

- [ ] **映像裡沒有 `data`／`certs`／`.env`／`tests`／`scripts`／`docs`**

```bash
docker run --rm personaldocai-worker:local ls -a /app
```

  預期：只有 `.`、`..`、`app`、`requirements.txt`。

- [ ] **§4.4 的容器端到端做過一次，照片真的入庫**

```bash
psql -d PersonalDocAI -c "select id, left(text, 40) from photo order by id desc limit 1"
docker compose logs --tail=200 worker | grep -E "route=cloud|kind=embed backend=local"
```

  預期：看得到剛才那張的文字；兩行 log 都在。

- [ ] **敏感檔零 S3（Demo 1 的本機版）**

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # 讓 CLI 用 admin profile（.env 那把 key 有 ListBucket，這條跑得過；統一用 admin，Phase 88 陷阱 12）
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
docker compose logs --tail=100 worker | grep "route=local verdict=SENSITIVE"
```

  預期：S3 回應沒有 `Contents`；log 那一行看得到。

- [ ] **S3 與兩條佇列在測試結束後是乾淨的**

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION" \
  --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json
aws sqs get-queue-attributes --queue-url "$SQS_RESULTS_QUEUE_URL" --region "$AWS_REGION" \
  --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json
```

  預期：S3 無 `Contents`；兩條佇列的 `ApproximateNumberOfMessages` 都是 `"0"`。

- [ ] **`compose.yaml` 零改動（兩個證據）**

```bash
git status --short -- compose.yaml compose.dev.yaml     # 預期：沒有輸出
docker compose config > /tmp/p90-compose-after.yaml
diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml   # 預期：沒有輸出
```

- [ ] **四個服務照常，app 的 COMMAND 是 uvicorn**

```bash
docker compose -f compose.yaml up -d --build
docker compose ps --no-trunc
curl -k -s https://127.0.0.1:8000/health
```

  預期：四個都 Up、`db`／`redis` healthy；app 的 COMMAND 含 `uvicorn`；health 回 `{"status":"ok"}`。

- [ ] **全量 pytest 顆數 ＝ 開工基線 658 ＋ 4 ＝ 662**

```bash
pytest -q
```

  預期：`662 passed`，且**沒有任何 skipped**。

- [ ] **端點仍 22、openapi 零 DELETE**

```bash
pytest -q -k "端點"
```

  預期：全綠。`-k 端點` 會撈到十幾顆名字含「端點」的測試，三顆清點測試
  （`test_端點恰好是這22支`／`test_端點數仍為22`／`test_端點數不變`）一定在裡面。
  本 phase 沒碰任何 router，數字不該變。

- [ ] **零依賴實證（三個死埠一起指）**

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

  預期：`662 passed`，與上面那條逐字相同。

- [ ] **專案 `data/` 沒被弄髒**

```bash
ls data/staging/            # 預期：空的（或只剩正在跑的那一個）
git status --short -- data/ # 預期：沒有輸出（data/ 在 .gitignore 裡）
```

- [ ] **`.env` 已改回 `CLOUD_ROUTE=off`，而且本機 worker 重啟過**（§4.4 收工那一步）

```bash
grep -n "^CLOUD_ROUTE=" .env      # 預期：CLOUD_ROUTE=off
```

- [ ] **`docs/spec/` 一字未動**

```bash
git status --short docs/spec/
```

  預期：**零輸出**（總覽 §7 鐵律 16：本增量規格區全程唯讀）。

- [ ] **只動了該動的檔**

```bash
git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml
diff /tmp/p90-before.txt <(git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml)
```

  預期：只多出 `Dockerfile` 與 `.dockerignore` 的 ` M`，以及 `tests/integration/test_design6_error_paths.py` 的 `??`
  （或 commit 之後三者都消失）。`app/` 底下應該**完全沒有**變動。

- [ ] **ruff 過**

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

  預期：`All checks passed!`

- [ ] **★G2 的十條證據表已填好交出，並且產品負責人已明示通過**（§4.7）

---

## 7. 常見陷阱

1. **忘了 `--target`，安靜地蓋出 app 映像卻叫它 worker。**
   **症狀：** `docker build --build-arg GIT_SHA=… -t personaldocai-worker:local .`（少打 `--target`）
   **build 完全成功**，但 `docker run --rm personaldocai-worker:local` 之後印的是
   `Uvicorn running on https://0.0.0.0:8000`（或憑證找不到而一直報錯），
   完全看不到 `cloud_worker 啟動 version=…`。
   **原因：** 不帶 `--target` 的 `docker build` 會建到**最後一個 stage**，也就是 `app`。
   **正解：** 一定要帶 `--target cloud-worker`。快速判斷法：
   `docker image inspect personaldocai-worker:local --format '{{.Config.Cmd}}'`
   ——看到 `[uvicorn …]` 就是建錯了，要看到 `[python -m app.workers.cloud_worker]`。

2. **把 `app` stage 放到 `cloud-worker` 前面，然後 compose 整個壞掉。**
   **症狀：** `docker compose up -d --build` 之後，`app` 容器一直重啟；
   `docker compose logs app` 看到的是 `cloud_worker 啟動 …` 或一堆 boto3 的錯；
   `curl https://127.0.0.1:8000/health` 完全連不上。
   **原因：** compose 的 `build: .` 沒有 `target:`，所以它拿到的是**最後一個 stage**。
   **正解：** `app` 一定放最後。`test_Dockerfile的app階段在最後` 這顆測試就是為了在
   「還沒 build 之前」就抓到它。看 `docker compose ps --no-trunc` 的 COMMAND 欄也能立刻分辨
   （**`--no-trunc` 不能省**，不加的話 COMMAND 只印開頭 20 個字）。
   ⚠ 開發模式（`compose.dev.yaml`）會把 `app` 的 `command:` 覆寫掉，這個症狀在開發模式**看不到**
   ——所以 §4.5 第三個證據規定在常駐模式驗，另外再看
   `docker image inspect personaldocai-app --format '{{.Config.Cmd}}'`（不分模式都準）。

3. **`--build-arg GIT_SHA` 沒傳，映像的 `version=dev`。**
   **症狀：** 容器啟動 log 印 `cloud_worker 啟動 version=dev …`。
   **原因：** ① 忘了打 `--build-arg`；② `git rev-parse --short HEAD` 在別的目錄跑（不是 git repo）；
   ③ 用 `docker compose build` 建的（compose 沒有傳這個 build arg，也不該傳——它建的是 app）。
   **正解：** 只有 §4.3 那一條完整指令會把 sha 烙進去。
   `version=dev` **不算壞掉**（預設值就是 `dev`），但 Phase 94 的 Demo 3 靠它分辨新舊映像，
   所以本 phase 就要養成習慣。

4. **`docker run` 之後容器立刻結束，什麼都沒印。**
   **症狀：** `docker run --rm --env-file .env personaldocai-worker:local` 一秒就回到 shell。
   **原因：** 多半是 `.env` 缺了工人必要的變數（`S3_BUCKET`／兩條 `SQS_*_QUEUE_URL`／`AWS_*`）。
   **正解：** 容器的輸出就是錯誤訊息，照著補 `.env`。想確認容器**真的讀到**那些變數：
   `docker run --rm --env-file .env personaldocai-worker:local env | grep -c "^S3_BUCKET="`
   ——預期印 `1`。（⚠ 不要跑 `env` 不加 grep，那會把 AWS 金鑰整串印在螢幕上。）

5. **`.env` 裡混進 `AWS_ENDPOINT_URL`，工人安靜地打不到 AWS。**
   **症狀：** 工人啟動 log 正常，但永遠收不到任何訊息；本機 30 秒（或 `CLOUD_RESULT_TIMEOUT_SECONDS`）
   之後 `fallback=local reason=result_timeout`。手動 `aws sqs receive-message` 卻看得到訊息在裡面。
   **原因：** `AWS_ENDPOINT_URL` 是 boto3 的標準變數，本專案只在 **pytest 的第五道安全網**
   把它指到死埠 `http://127.0.0.1:9`。它一旦進了 `.env`，`--env-file` 就會把它帶進容器，
   於是 boto3 每一次呼叫都打到那個沒人聽的埠。
   **正解：** `grep -n "AWS_ENDPOINT_URL" .env` 預期**零輸出**；有的話刪掉那一行。

6. **重建映像之後沒有真跑一次，套件版本悄悄分岔。**
   **症狀：** 本機 `pytest -q` 全綠、但容器裡的工人在某個函式上炸掉（`TypeError`／`AttributeError`）。
   **原因：** `requirements.txt` 全部是 `>=` 沒有 lock，映像是在 build 當下才解析版本的。
   host 的 `.venv` 與容器裡會慢慢分岔（CLAUDE.md 已記：langchain-core host 1.5.6 / container 1.6.0）。
   `pytest -q` 全綠**驗的是 host 那一份環境，不等於驗過實際跑的映像**（design6 §13 最後一列）。
   **正解：** 把「重建映像」當成需要手動煙霧一次的動作——§4.4 的端到端就是那一次。
   每次 `docker build` 之後至少跑一次完整端到端再收工。

7. **`docker compose config` 的基準忘了先存，事後沒得比。**
   **症狀：** 改完之後才想起 §2 第 ⑧ 步的 `/tmp/p90-compose-before.yaml` 沒跑。
   **原因：** `docker compose config` 讀的是**當下磁碟上的檔案**，改過就回不去了。
   **正解：** `git stash` 暫存改動 → 跑一次存成基準 → `git stash pop` 拿回來。
   （`docker compose config` 只讀 `compose.yaml` 與環境變數、**不讀 Dockerfile**，
   所以本 phase 其實 stash 不 stash 都一樣；但養成先拍基準的習慣，
   在真的會被影響的情境——例如有人順手改了 compose——才救得回來。）

8. **`docker buildx build` 忘了 `--load`，`docker run` 說找不到映像。**
   **症狀：** buildx 跑完顯示成功，但 `docker run personaldocai-worker:local` 回
   `Unable to find image 'personaldocai-worker:local' locally` 然後跑去 Docker Hub 拉（然後失敗）。
   **原因：** buildx 預設把結果留在自己的 build cache，**不會**放進 `docker images` 那個清單。
   **正解：** 加 `--load`。（`--push` 是「直接推到 registry」，那是 Phase 91 的事。）

9. **在 compose 加第五個服務把工人也跑起來，然後兩台工人搶同一條佇列。**
   **症狀：** EC2 上的工人明明開著，但有些照片的結果不知道被誰處理掉了；
   本機 `docker compose logs` 看得到 `kind=vlm backend=cloud` 但那不是 EC2 印的。
   **原因：** SQS Standard Queue 是「誰先收到算誰的」。本機與 EC2 同時在收 `personaldocai-jobs`，
   訊息會被隨機分掉。而且 compose 的服務會**開機自己拉起來**，你根本不會發現它在跑。
   **正解：** 本機跑工人一律用 `docker run`（一次性、`--rm`、看得到終端機視窗）。
   `test_compose_yaml沒有新增服務也沒有AWS設定` 這顆測試就是守這件事。

10. **同時跑兩份 pytest。**
    **症狀：** 大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`，
    **每次紅的顆數都不一樣**——看起來像程式壞了。
    **原因：** autouse `reset_tables` 每顆測試都 `TRUNCATE` 同一個測試庫，兩份會互相清掉對方的資料。
    **正解：** 等另一份跑完再跑。變異測試那一段特別容易犯——每個變異都要跑一次 pytest，
    不要為了快就開兩個視窗並行。

11. **變異測試改壞了產品檔卻忘了還原，然後 commit 進去。**
    **症狀：** commit 之後 CI 紅，或更糟——`compose.yaml` 裡留著一個假的 `cloudworker` 服務，
    下次開機它就自己跑起來了。
    **原因：** §4.6 步驟 3 有四個變異，每一個都要 `cp` 還原。
    **正解：** 每次還原之後**立刻**跑 `git status --short -- Dockerfile compose.yaml` 確認乾淨，
    而且 `git add` 一定要明列檔案（不要 `git add -A`）。全部做完再
    `rm -f /tmp/Dockerfile.bak /tmp/compose.yaml.bak`。

12. **在 ★G2 還沒過的時候就開始建 AWS 資源。**
    **症狀：** 「反正 SG 也不用錢，先建起來放著」——然後 EC2 也建了，忘了 Stop，點數開始燒。
    **原因：** G2 是**人**的閘門，不是「測試綠了就算過」。
    **正解：** 本 phase 的產出**一個 AWS 資源都沒有建**（只用了 Phase 84／85 已經建好的 S3 與 SQS）。
    Phase 91 的第一行就會再問一次「★G2 通過了嗎」。

13. **`.env` 的值加了引號，容器裡的工人 401／`InvalidClientTokenId`，但 app 與 Celery 容器都正常。**
    **症狀：** 同一份 `.env`，本機 worker（Celery）走雲端路一切正常、Phase 88 在 host 直跑工人也正常，
    只有 `docker run --env-file .env` 起來的這個容器打 ollama.com 回 401、或 boto3 回
    `InvalidClientTokenId`／`SignatureDoesNotMatch`。
    **原因：** `docker run --env-file` 對引號**沒有特殊處理**——`OLLAMA_API_KEY="abc"` 進到容器就是
    連引號一起的 `"abc"`（官方文件原話：quotation marks are part of the value）。app／Celery 容器
    與 host 直跑走的是 python-dotenv，它會把引號剝掉，所以那邊看不出來。
    **正解：** `.env` 的值一律不加引號。`grep -n '="' .env ; grep -n "='" .env` 預期零輸出。

14. **工人一起來就每 5 秒重複 `AccessDenied ... sqs:ReceiveMessage`。**
    **症狀：** 啟動行印得出來，接著不斷重試 `向 jobs 佇列要訊息失敗`，錯誤裡是 `AccessDenied`
    （不是 `NoCredentialsError`——那是 key 缺了或打錯，見 Phase 88 §4 的對照表）。
    **原因：** `.env` 那把 `personaldocai-mac` 的 key 掛的是 `deploy/aws/mac-policy.json`，Phase 82 那份
    原文只寫了**本機端**要的動作（jobs `SendMessage`、results `Receive`／`Delete`）；工人要的是反過來的
    那一組（jobs `ReceiveMessage`／`DeleteMessage`、results `SendMessage`）。Phase 88 若跑通過，代表 policy
    已經補過；沒補過的話就是在這裡才第一次撞到。
    **正解：** 回 Phase 82／88 把 policy 補齊（EC2 上用的 `personaldocai-worker-role` 本來就有那一組，
    這件事只影響「在 Mac 上跑工人」）。**不要**在本 phase 臨時把 admin 的 key 塞進 `.env` 或
    `--env-file` 進容器。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- `Dockerfile` 從單階段變成三階段（`base` → `cloud-worker` → `app`），
  同一份檔案同時餵得出「網站映像」與「工人映像」。
- 一個可以直接跑的 arm64 工人映像 `personaldocai-worker:local`，
  裡面烙著 build 當下的 git 短碼（`WORKER_VERSION`）。
- `.dockerignore` 多排除 `deploy/`（build context 更小；映像內容不變——它本來就只 COPY `app/` 與
  `requirements.txt`）。
- 一個新的測試檔 `tests/integration/test_design6_error_paths.py`（本 phase 4 顆，
  Phase 93／94／95 會繼續往裡面加）。
  📌 **分工講清楚：** 本 phase 那 4 顆只守「Dockerfile 的三個 stage」與
  「多階段沒有波及 compose」（`build: .` 沒有 `target:`、`image: personaldocai-app` 兩處、
  服務恰四個）。**「AWS 變數名（`AWS_REGION`／`S3_BUCKET`／`SQS_*_QUEUE_URL`…）
  不出現在 `compose*.yaml`」由 Phase 95 的 `test_compose沒有為了雲端新增任何服務` 守**
  ——兩顆刻意不重複。

**對外行為變了沒：**

**完全沒有。** 端點仍是 **22** 支、`openapi.json` 仍零 DELETE、
`POST /photos` 仍回 202 且 body 恰三鍵、`GET /ingest-jobs` 回應形狀不變、
前端一行都沒改、資料庫結構零改動、`compose.yaml` 與 `compose.dev.yaml` 一個字都沒動
（`.dockerignore` 那一行只影響 build context，映像內容與啟動行為都不變）。
`app/` 底下的 Python **零變更**。

**顆數：** 開工基線 **658** ＋ 本 phase **4** ＝ **662 passed ＋ 0 skipped**。
（與總覽 §2.7／§9 定案的數字一致，**零偏離**。）

**下一步：**

★ **閘門 G2**（人）——產品負責人看過 §4.7 的十條證據並明示「可以開 EC2 了」。

過了之後是 **Phase 91（`phase-91-EC2的網路IAM與ECR.md`）**：
用 AWS CLI 建 security group（**inbound 空**、outbound 只開 TCP 443）、
S3 Gateway VPC endpoint（免費）、EC2 用的 IAM role ＋ 同名 instance profile、
ECR repository，並把本 phase 建好的 `personaldocai-worker:local`
第一次手動 `docker tag` ＋ `docker push` 上去。
**Phase 91 尚不啟動任何 EC2 實例**——那是 Phase 92。

---

## 附：本文件引用的官方文件

- [Dockerfile 多階段建置與 `--target`](https://docs.docker.com/build/building/multi-stage/)
- [Docker 多平台建置（`--platform`、buildx、QEMU）](https://docs.docker.com/build/building/multi-platform/)
- [Dockerfile `ARG` 與 `ENV` 的差別](https://docs.docker.com/reference/dockerfile/)
- [`docker build` 指令參考（`--target`／`--build-arg`／`--check`）](https://docs.docker.com/reference/cli/docker/buildx/build/)
- [`docker run --env-file`](https://docs.docker.com/reference/cli/docker/container/run/)
- [`docker image inspect`（`--format` 取欄位）](https://docs.docker.com/reference/cli/docker/image/inspect/)
- [`docker compose config`（只解析、不啟動）](https://docs.docker.com/reference/cli/docker/compose/config/)
- [EC2 T4g（Graviton／arm64）機型](https://aws.amazon.com/ec2/instance-types/t4/)
- [SQS Standard／at-least-once（為什麼兩台工人會搶同一條佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
