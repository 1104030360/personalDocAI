# Phase 90：worker 映像（多階段 Dockerfile ＋ arm64）＋ ★ 閘門 G2

> 📌 **2026-09-02 校準紀錄**（ledger：`.superpowers/sdd/phase0902-2/progress.md`；本檔已依下列裁決改寫）
>
> | 裁決 | 落在本檔哪裡 |
> |---|---|
> | **R0** 不 commit、用 tree 快照相減 | §4.6 步驟 6 從「commit」改成「記快照」；§2 ⑧ 與 §6 的「只動了該動的檔」改用 `.superpowers/sdd/phase0902-2/snapshot-tree` 兩顆 tree 相減／`git status --short`。**本輪禁止 `git add`／`git stash`／`git mv`** |
> | **R1** 識別字一律英文 | §4.6 的測試碼：`PROJECT_ROOT`／`read_dockerfile()`／`read_compose()`／`read_compose_dev()`／`compose_services()`／`stage_names()`／`source`／`names`／`services`（`test_中文` 函式名維持不變；log／錯誤訊息／註解／docstring 仍是繁中） |
> | **R2** ★G2 條件式通過 | §4.7 改成「controller 填證據；dev-prompt 已明示執行到 91 ＋ 88／90 兩段端到端由 controller 親跑通過 ＝ G2 成立」，並保留產品負責人事後否決的權利 |
> | **R3** AWS／docker／`.env`／restart／煙霧一律 controller 親做 | §2 ⑤⑥⑧、§4.2 的 `docker build --check`、§4.3、§4.4、§4.5、§6 帶 `docker`／`aws`／`psql`／`curl` 的每一條都加了「⚠ 本步驟由 controller 親自執行」 |
> | **R4** 顆數以 **2026-09-02 實查 644** 起算 | 開工基線 **668**（644 ＋ 87 的 12 ＋ 88 的 5 ＋ 89 的 7）、收工 **672**；§2／§4.6／§4.7／§6／§8 全部改過。總覽 §9 寫的是「662（實 672）」的雙寫法 |
> | **R5** 五份計畫檔平行校準、各改各的 | 本檔只動 `docs/plan/unfinish/phase-90-worker映像arm64.md` 一個檔 |
> | **R6** 不需要產品負責人的手機 | 本 phase 零前端、零鏡頭，未新增任何真機步驟 |
> | **R7** `CLAUDE.md` 那句過期話由 **Phase 89** 改 | 本 phase **不動** `CLAUDE.md` |
> | **R8** 容器重建走 **dev overlay** | §4.5 第三個證據改成 `docker compose -f compose.yaml -f compose.dev.yaml up -d --build`，另加 `docker image inspect personaldocai-app --format '{{.Config.Cmd}}'` 證明映像預設 CMD 仍是 uvicorn（那一條不分模式都準） |
> | **R9** `VLM_MAX_ATTEMPTS` 是寫死常數 | 本檔 §4.4 的 `--env-file` 變數清單已把它拿掉（列了會讓人以為改得動） |
> | **R10** 第 4 顆掃碼**同時**守「compose 零 AWS 設定」 | §4.6 的 `test_compose_yaml沒有新增服務也沒有AWS設定` 多一組斷言（`compose.yaml` ＋ `compose.dev.yaml` 全文零 `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE`），§4.6 步驟 3 多一個變異 5，§8 的分工說明同步改 |
>
> 另外校正的過期事實：開工基線顆數、`.env` 現況（S3／SQS 已建、`CLOUD_ROUTE=off`、無 `AWS_ENDPOINT_URL`）、
> `deploy/aws/mac-policy.json` **已含**工人端那組佇列權限（§7 陷阱 14 改寫）、`scripts/aws_check.py` 已在、
> `.dockerignore` 那一行的插入位置，以及下面這條「閘門不看檔名」。

> ⚠ **2026-09-01 改判：隱私閘門看的是圖的「內容」，不是檔名**（總覽 §8.10、`VlmGate.classify()`
> 第一行就是 `del filename`）。所以本 phase 的煙霧要準備**兩張合成圖**：
> 一張內容明確非敏感（Pillow 畫的收據，`RECEIPT`／`Target`／`Total`），
> 一張內容是證件（Pillow 畫的假身分證）。**把同一張圖改個檔名是驗不到東西的**
> ——兩段產圖的 Pillow 碼就寫在 §4.4 裡（上傳前、與反面驗證前各一段），
> 與 Phase 86 §4.5 步驟 1／§4.6 逐字相同。

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

**工作樹與 AWS 的現況（2026-09-02 controller 實查，不必再自己查一次）：**

- HEAD ＝ `bb3921a`（`main`）：**Phase 74〜86 都已完成，83〜86 已進 commit**；87〜89 與本 phase 是同一批工作，
  尚未 commit（本輪一律不 commit，見 §4.6 步驟 6）。`docs/plan/unfinish/` 還放著總覽與 83〜95 的計畫檔。
- `.env` 已經有：`AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`（Phase 82 的 `personaldocai-mac` 最小權限 key）、
  `AWS_REGION`、`S3_BUCKET`（Phase 84）、`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`（Phase 85）、
  `CLOUD_ROUTE=off`、`CLOUD_RESULT_TIMEOUT_SECONDS=300`、`OLLAMA_API_KEY`、
  `OLLAMA_CLOUD_VLM_MODEL=gemma4`、`VLM_MODEL=gemma4:e2b`。
  **沒有** `EC2_WORKER_INSTANCE_ID`（Phase 91 才加空值）、**沒有** `AWS_ENDPOINT_URL`（§7 陷阱 5 要的就是這個結果）。
- S3 bucket 與兩條 SQS 佇列都已經建好而且是乾淨的（`documents/` 空、兩條佇列 0／0）；
  `python scripts/aws_check.py s3 sqs` 這支檢查腳本 Phase 84／85 已經放進 `scripts/`，兩項都 OK。
- **`deploy/aws/mac-policy.json` 已經含工人端那一組權限**（實查有 `WorkerReceiveJobs`＝jobs 的
  `ReceiveMessage`／`DeleteMessage`／`ChangeMessageVisibility`，與 `WorkerSendResults`＝results 的
  `SendMessage`，另有 bucket ARN 的 `s3:ListBucket` 與 `ec2:DescribeInstances`；總覽 §10.2 追認項 N／P）。
  本 phase 的容器用的是**同一把 key**，所以不會在第一次 `ReceiveMessage` 就 `AccessDenied`
  ——真的撞到了才看 §7 陷阱 14，**不要**在本 phase 臨時改 policy 或換金鑰。
- `.env` 目前是 `CLOUD_ROUTE=off`。§4.4 會暫時切成 `assume`，**收工要改回 `off`／`300`**。
- 容器現在跑的是 **dev overlay**（`app` 帶 `--reload`、`app` 與 `worker` 都 bind-mount `./app`），
  所以下面每一條 `docker compose` 都要帶**兩個** `-f`（裁決 R8）。

**開工基線：2026-09-02 實查 644 ＋ 87 的 12 ＋ 88 的 5 ＋ 89 的 7 ＝ 668 passed ＋ 0 skipped。**

> 📌 **為什麼不是總覽 §9 寫的 658：** 總覽那一欄的絕對值是規畫當時算的，
> 與 2026-09-02 實查的基線差 **+10**（實查 644）。**只對「本 phase 新增幾顆」**（+4），
> 絕對值一律以實查為準；總覽 §2.7 那一列現在寫的是「662（實 672）」的雙寫法。

**開工前一次驗完（在專案根目錄 `/Users/linjunting/personalDocAI`）：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 顆數基線（2026-09-02 實查 644 起算，Phase 89 做完應為 668）
pytest -q
# 預期尾巴：668 passed（沒有任何 skipped）

# ② 三個死埠一起指，顆數要一模一樣（零外部依賴實證）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
# 預期：668 passed，與 ① 逐字相同

# ③ 工人程式在正確的位置（.dockerignore 排除 scripts/，所以一定要在 app/ 底下）
ls -l app/workers/cloud_worker.py app/workers/__init__.py
grep -n "def main" app/workers/cloud_worker.py

# ④ config 有 WORKER_VERSION（Phase 77 放的）
grep -n "WORKER_VERSION" app/core/config.py
# 預期：看得到一行 WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")

# ⑤⑥ ⚠ 本兩步由 controller 親自執行；實作 subagent 不打 docker／aws 指令、不改 .env
# ⑤ Docker Desktop 開著、四個服務活著（現在是 dev overlay，兩個 -f 都要帶）
docker version              # Client／Server 兩段都要有輸出；只有 Client ＝ Docker Desktop 沒開
docker compose -f compose.yaml -f compose.dev.yaml ps
                            # db 與 redis 要 Up (healthy)，app 與 worker 要 Up

# ⑥ 這台機器是 arm64（Apple Silicon）——決定了 build 出來的預設架構
uname -m
# 預期：arm64
docker info --format '{{.Architecture}}'
# 預期：aarch64（Docker 用的是 Linux 的叫法，跟 arm64 是同一件事）

# ⑦ 分支是 main、工作區只有本輪正在做的東西
git branch --show-current   # 預期：main
git status --short          # 87〜89 這批未 commit 的產出＋計畫檔；不該有別的東西

# ⑧ 開工快照（之後 §6 驗收「有沒有動到不該動的檔」要拿它相減）
#    ★ 本輪不 commit（裁決 R0），所以用 snapshot-tree 印出「當下工作樹」的 tree SHA，
#      它只在物件庫多一顆 tree 物件，**不碰 index、不建 commit、不動 stash**
.superpowers/sdd/phase0902-2/snapshot-tree     # 記下這串 SHA，收工時再印一次相減
git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml
#    ↑ 這一份也順手貼進筆記；收工時再跑一次比對（比 tree 相減好讀）

# ⚠ 下面這一條要 docker：由 controller 執行
docker compose -f compose.yaml -f compose.dev.yaml config > /tmp/p90-compose-before.yaml
wc -l /tmp/p90-compose-before.yaml
# 預期：印出行數（幾百行都正常）；這份是 §4.5 要 diff 的基準
```

> 📌 **第 ⑧ 步的 `docker compose config` 先跑、存成基準，§4.5 才有東西可以 diff。**
> 老實說：`docker compose config` 只讀 compose 檔與環境變數、**不讀 Dockerfile**，
> 所以改完 Dockerfile 再跑，輸出其實也一樣（§7 陷阱 7 有解釋）；compose 檔裡也沒有任何
> `${…}` 變數插值，所以 §4.4 改 `.env` 同樣不影響它。仍然要求「先拍基準」是為了養成習慣——
> 真的有人順手動了 compose 的那一天，只有事先存好的基準救得了你。
> ⚠ 兩次都要用**同樣的 `-f` 組合**（現在是 dev overlay ＝兩個 `-f`），不然 diff 一定不是空的。
> ⚠ **本輪禁止 `git stash`**（裁決 R0）。忘了先拍基準也不必慌：本 phase 一個字都不會動 compose，
> 事後補拍與事前拍的結果相同；真的被改到了就先 `git diff -- compose.yaml` 看清楚再手動改回去。

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
3. 建出 `personaldocai-worker:local`（arm64），並驗證架構真的是 `arm64`。（⚠ controller 親做）
4. 在 Mac 上**用容器**跑工人（`docker run --rm --env-file .env …`），重做一次 Phase 88 的端到端，
   **收工把 `.env` 改回 `CLOUD_ROUTE=off`／`CLOUD_RESULT_TIMEOUT_SECONDS=300`、AI 開關撥回 `local`**。（⚠ controller 親做）
5. 證明 compose 零改動而且行為不變：`docker compose config` 的輸出 diff 為空、
   `docker compose -f compose.yaml -f compose.dev.yaml up -d --build`（現況是 dev overlay，裁決 R8）
   之後四個服務照常，且 `docker image inspect personaldocai-app --format '{{.Config.Cmd}}'` 仍是 uvicorn。（⚠ controller 親做）
6. 新開 `tests/integration/test_design6_error_paths.py`，放 **4 顆**掃碼測試（總覽 §2.7 定案的名字）。
   第 4 顆依裁決 **R10** 同時守「compose 兩檔零 AWS 設定」。
7. 交出 **★ 閘門 G2** 的證據（§4.7 的十條表）——**證據由 controller 親跑並填寫**，
   通過與否見 §4.7（裁決 R2）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 新開 `Dockerfile.worker` 之類的第二份 Dockerfile | 兩份檔案會漂移（改了套件只改一邊、然後在 EC2 上才發現）。總覽 §10 追認項 j 明文選了多階段 |
| 把 `app` stage 放在 `cloud-worker` 前面 | 不帶 `--target` 的 `docker build .` 會停在**最後一個** stage。`app` 不在最後的話，`compose.yaml` 的 `build: .` 會安靜地蓋出一個「以為是 app、其實是 worker」的映像——**沒有任何錯誤訊息**，只有 app 容器起來之後一直重啟 |
| 改 `compose.yaml`／`compose.dev.yaml`（哪怕只加一個註解，也不要加 `target:`） | 總覽 §7 鐵律 11：本增量 compose 零改動。§4.5 的 diff 證明 ＋ §4.6 第 4 顆掃碼就是在驗這件事（該顆依裁決 **R10** 一併守「兩份 compose 全文零 `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE`」——Phase 95 可以再加一顆更廣的，不衝突） |
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

- [x] 用下面這一份**完整取代** `Dockerfile`（不是加在後面）：

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

- [x] 存檔後先確認語法（`--check` **不會真的 build**，只讓 Docker 把 Dockerfile 解析一遍並跑內建的檢查；有語法錯會馬上噴）：

> ⚠ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker` 指令、不改 `.env`、不 restart 容器。**

```bash
docker build --check .
```

  預期：印出 `Check complete, no warnings found.`（或只有無害的 style 警告）。
  出現 `dockerfile parse error` → 多半是 `\` 換行那幾行被改壞了，回上面重貼一次。

  > 💡 `docker build --check` 是 `--call=check` 的簡寫，**Buildx 0.15.0（2024 年中）以後**才有；
  > `docker buildx version` 看得到你的版本。太舊沒有這個旗標的話，跳過這一步，直接做 §4.3——
  > 真的建一次也一樣會發現語法錯。

- [x] **順手收緊 `.dockerignore`：加兩行**（一行註解、一行 `deploy/`；既有的行一個字都不動）。

  **位置：** 放在檔尾那個「# 這些在 container 裡用不到」區塊裡、**緊接在 `scripts/` 那一行後面**
  （`deploy/` 跟 `scripts/`／`docs/` 是同一類東西，擺在一起才看得懂；擺檔尾 `**/.DS_Store` 之後會很突兀）。
  改完那個區塊長這樣：

```text
# 這些在 container 裡用不到
docs/
tests/
scripts/
# IAM policy JSON 與 EC2 的 user-data／systemd 設定（Phase 82／91）：只給人與 AWS CLI 用，映像用不到
deploy/
.playwright-mcp/
.superpowers/
.claude/
**/.DS_Store
```

  存檔後確認（**恰 2 行新增、0 行刪除**）：

```bash
grep -n '^deploy/$' .dockerignore     # 預期恰一行
git status --short -- .dockerignore   # 預期： M .dockerignore
```

  > 📌 **誠實說明這一行的份量：** 現在的 Dockerfile 只 `COPY requirements.txt` 與 `COPY app`，
  > 所以 `deploy/` 本來就**不會**進映像（`.dockerignore` 管的是「送給 Docker 的 build context」，
  > 不是「映像裡有什麼」）。加這一行是①少送幾個檔案給 daemon、②哪天有人寫了 `COPY . .`
  > 也不會把 policy JSON 打進映像（裡面的帳號 ID 都是 `<ACCOUNT_ID>` 佔位，零機密，但也不該進去）。
  > 一行、零風險、順手做掉；**不要**趁機改其他行。

### 4.3 建工人映像並驗證架構是 arm64

> ⚠ **§4.3 整節由 controller 親自執行**（裁決 R3）：它會 `docker build`／`docker run`／讀 `.env`。
> **實作 subagent 不打 `aws`／`docker` 指令、不改 `.env`、不 restart 容器。**

- [x] 建映像（**在專案根目錄**）：

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

- [x] **驗證架構真的是 arm64**（這一條是 ★G2 的加碼項目，總覽 §5.5 最後一段）：

```bash
docker image inspect personaldocai-worker:local --format '{{.Architecture}}'
```

  預期：`arm64`

  > 📌 **為什麼會是 arm64 而你什麼都沒做：** Docker build 預設用「跑 Docker 的這台機器的架構」。
  > 這台 Mac 是 Apple Silicon ＝ arm64，所以預設就對了。
  > EC2 的 `t4g.small` 也是 arm64，兩邊剛好同一種——這是本專案選 `t4g` 的附帶好處。
  > 印出 `amd64` 的話代表你在一台 Intel Mac 上，或 Docker Desktop 設了預設平台——
  > 那就要改用下面的 `buildx` 寫法。

- [ ] **（示範／備用）明寫平台的 buildx 寫法**：（2026-09-03 controller：示範用、本輪未執行——這台 Mac 本身是 arm64，`docker build` 預設架構已正確；§4.3 已用 `docker image inspect` 驗過）

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

> ⚠ **§4.4 整節由 controller 親自執行**（裁決 R3）：它會改 `.env`、restart 容器、
> `docker run`、真的把一張照片送上 AWS。**實作 subagent 到 §4.3 為止就收工**：
> 不打任何 `aws`／`docker` 指令、不改 `.env`、不上傳任何東西。

> **做之前先確認三件事**（與 Phase 86 §4.5 同一組前置）：
> ① 四個容器都活著（`docker compose -f compose.yaml -f compose.dev.yaml ps`）
> ② **Ollama 活著**（`open -a Ollama`）——embeddings 一律本機、不歸頁首開關管，沒有它入庫那一段一定失敗
> ③ `python scripts/aws_check.py s3 sqs` 兩個都 ✅

- [x] **把頁首的 AI 開關撥到「雲端」**（省十幾分鐘；`PUT /settings/ai-backend`，body 只有一個鍵）：

```bash
cd /Users/linjunting/personalDocAI
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
```

  預期輸出（恰兩鍵）：`{"backend":"cloud","cloud_configured":true}`

  > 📌 **為什麼要撥：** 隱私閘門的短問與入庫看圖都跟這扇門走。本機是 100 秒＋64〜88 秒，
  > 雲端各約 0.7／0.8 秒（phase0901 實測）——整段煙霧從十幾分鐘縮到兩三分鐘。
  > 這個狀態存在 **app 行程的記憶體**（`config.AI_BACKEND`），**重啟 app 就會回到 `local`**；
  > 重啟 worker 不影響它。worker 行程用的是 `POST /photos` 那一刻抄進 job 的快照
  > `job["ai_backend"]`（總覽 §10.2 追認項 S），所以**撥開關一定要在上傳之前**。
  > 回應 `"cloud_configured":false` ＝ `.env` 沒有 `OLLAMA_API_KEY`，會回 422、開關不動。
  > §4.4 收工要撥回 `local`。

- [x] **先把本機的 `.env` 切成 `assume` 模式**（本機不做 EC2 探測，直接假設遠端開著）：

  打開 `.env`，確認／改成這兩行（**只寫變數名與值的形狀，不要把真值貼進任何文件**）：

```ini
CLOUD_ROUTE=assume
CLOUD_RESULT_TIMEOUT_SECONDS=300
```

  改完重啟本機 worker（Celery 那個，不是雲端工人）：

```bash
# 現況是 dev overlay，兩個 -f 都要帶（少帶一個 Compose 會以為你要換設定，行為不一樣）
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

  > ⚠️ `.env` 改了一定要 restart。`app/core/config.py` 只在**行程啟動時**讀一次 `.env`
  > （`load_dotenv()`），改檔不會自動生效。

- [x] **開一個新的終端機視窗（終端機 A）**，用容器跑雲端工人：

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
  | `--env-file .env` | 把 `.env` 裡每一行 `KEY=VALUE` 都設成容器裡的環境變數。工人要用的是：`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_REGION`、`S3_BUCKET`、`SQS_JOBS_QUEUE_URL`、`SQS_RESULTS_QUEUE_URL`、`OLLAMA_API_KEY`、`OLLAMA_CLOUD_VLM_MODEL`。**`VLM_MAX_ATTEMPTS` 不在這張清單裡**——`config.VLM_MAX_ATTEMPTS = 3` 是寫死的常數、不讀環境變數（裁決 R9）。`WORKER_VERSION` 也不必給：它在 build 時就烙進映像了 |
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
  > 預期：**沒有輸出**（2026-09-02 實查確認 `.env` 目前沒有這一行）。
  > 有輸出就把那一行刪掉（那是測試用的，不該在 `.env` 裡）。

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

- [x] **回到原本的終端機（終端機 B）**，先產一張**內容**明確非敏感的合成圖
      （與 Phase 86 §4.5 步驟 1 逐字相同的那段；`/tmp/receipt-test.png` 還在的話可以跳過）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from PIL import Image, ImageDraw, ImageFont


def font(size):
    """macOS 有 Arial；沒有就退回 Pillow 內建的可縮放字型（10.1 起支援 size）。"""
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# 512 是刻意的：閘門會把圖縮到長邊 <= 512（privacy_gate.GATE_IMAGE_MAX_SIDE），
# 一開始就畫這麼大，字才不會在縮圖時糊掉、模型才讀得出來。
image = Image.new("RGB", (512, 384), (250, 248, 240))
draw = ImageDraw.Draw(image)
draw.text((24, 24), "RECEIPT", fill=(20, 20, 20), font=font(44))
draw.text((24, 96), "Target  Store #1842", fill=(40, 40, 40), font=font(30))
for index, line in enumerate(["Cola          45", "Chips         30", "Bread         60"]):
    draw.text((24, 150 + index * 40), line, fill=(40, 40, 40), font=font(28))
draw.text((24, 300), "Total        135", fill=(20, 20, 20), font=font(34))
image.save("/tmp/receipt-test.png")
print("已產生 /tmp/receipt-test.png")
PY
file /tmp/receipt-test.png        # 預期：PNG image data, 512 x 384, ...
open /tmp/receipt-test.png        # 人眼看一下：RECEIPT／Target／Total 三行都要清楚
```

- [x] 上傳它：

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

  預期：一段 JSON（恰三鍵 `job_id`／`filename`／`content_type`）＋ 下一行 `202`。

  > 📌 **決定走哪條路的是圖的「內容」，不是檔名**（2026-09-01 改判；總覽 §8.10——
  > `VlmGate.classify()` 的第一行就是 `del filename`）。所以這裡要的是一張**看起來就是收據**的圖，
  > 閘門看過之後判 `NON_SENSITIVE`，才有資格走雲端。
  > **把任意一張圖 `cp` 成 `receipt-test.png` 是沒有用的**——閘門根本不看那個名字，
  > 內容若是別的東西（尤其證件），會被判 `SENSITIVE`／`UNCERTAIN` 留在本機，這條路就驗不到。
  > 檔名叫 `receipt-test.png` 純粹是為了人好認（它只會出現在 job 的記帳欄位裡）。
  >
  > 📌 用英文字，不要用中文字：`ImageDraw.text()` 的內建字型畫不出中日韓文字（會變空白或方框），
  > macOS 的 Arial 也沒有中文。這張圖只要讓模型看出「這是一張收據」，英文就夠了。
  >
  > ⚠ 副檔名要與內容一致（PNG 存成 `.png`）——`POST /photos` 看的是 `Content-Type`
  > （curl 依副檔名決定），不是檔案內容。**不要**用 `cp` 把 `.jpg` 改名成 `.png`：
  > 那會讓 S3 的鍵名、staging 的副檔名、落地原圖的副檔名全部對不上內容。

- [x] **回終端機 A 看工人的 log**，應該在幾秒內看到：

```text
INFO:     AI 開始 kind=vlm backend=cloud model=<你的雲端模型名>
INFO:     AI 結束 kind=vlm backend=cloud model=… elapsed_s=… ok=true understood=true text_chars=…
INFO:     job <job_id>：result.json 已放好、results 已送出（worker_version=<sha>）
```

  ✅ 最後那一行的 `worker_version=` 也要是你的 sha——它會一起寫進 `result.json`（Phase 87 定的格式）。

- [x] **看本機 worker（Celery）的 log**，確認走的是雲端路而不是 fallback：

```bash
docker compose -f compose.yaml -f compose.dev.yaml logs --tail=200 worker \
  | grep -E "route=|fallback=|kind=embed"
```

  預期：
  - 看得到 `job <job_id> route=cloud verdict=NON_SENSITIVE`（Phase 79 定的格式，與 Phase 78 的
    `route=local verdict=…` 同款；測試用 caplog 逐字釘住，不會有「等價字樣」）
  - **不該**看到 `fallback=` 那一行
  - 看得到 `AI 開始 kind=embed backend=local`（D13：向量一律本機算）

- [x] **確認照片真的進了資料庫、S3 已經清乾淨、job 已經消失**：

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

- [x] **反面驗一次：敏感檔零 S3**（Demo 1 的本機版；證明容器化沒有破壞閘門）。
      先產一張**內容**是證件的合成圖（與 Phase 86 §4.6 逐字相同；
      ⛔ **不可以** `cp /tmp/receipt-test.png /tmp/id-card-test.png`——閘門不看檔名，
      改名只會得到跟上一節一樣的 `NON_SENSITIVE`，等於什麼都沒驗到）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from PIL import Image, ImageDraw, ImageFont


def font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# 全部是**編造的假資料**，不要用任何一個人的真證件。
# 內容要打中 PRIVACY_PROMPT 列的例子（身分證件、健保卡、駕照、護照…）。
image = Image.new("RGB", (512, 324), (238, 244, 250))
draw = ImageDraw.Draw(image)
draw.rectangle((8, 8, 503, 315), outline=(60, 90, 140), width=3)
draw.text((28, 28), "NATIONAL ID CARD", fill=(20, 30, 60), font=font(36))
draw.text((28, 96), "Name: WANG XIAO MING", fill=(30, 30, 30), font=font(26))
draw.text((28, 140), "ID No: A123456789", fill=(30, 30, 30), font=font(26))
draw.text((28, 184), "Date of birth: 1990-01-01", fill=(30, 30, 30), font=font(26))
draw.text((28, 228), "Address: 100 Test Road, Taipei", fill=(30, 30, 30), font=font(24))
image.save("/tmp/id-card-test.png")
print("已產生 /tmp/id-card-test.png")
PY
file /tmp/id-card-test.png        # 預期：PNG image data, 512 x 324, ...
open /tmp/id-card-test.png        # 人眼看一下：五行字都要清楚
```

- [x] 上傳它，確認被擋在本機：

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/id-card-test.png" \
  https://127.0.0.1:8000/photos       # 預期：202

docker compose -f compose.yaml -f compose.dev.yaml logs --tail=100 worker | grep "route=local"
# 預期：route=local verdict=SENSITIVE

aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
# 預期：沒有任何以這個 job_id 開頭的物件
```

  > 📌 檔名故意取成中性的 `id-card-test.png` 而不是 `身分證.png`：這一節要證明的是
  > 「**內容**敏感就擋得下來」，取個中性名字反而順便說明了「檔名不影響判定」這件事。
  >
  > ⚠️ 這一張擋下來之後會走**本機**入庫路線，但因為 §4.4 開頭已經把頁首開關撥到雲端、
  > 而 job 帶的是入列當下的 `ai_backend=cloud` 快照，所以看圖仍是雲端（約 1〜2 秒）。
  > 萬一中途重啟過 app（開關會掉回 `local`），這一張就要等本機 gemma4 的 64〜88 秒
  > （9 欄 prompt 可到 2〜5 分鐘）。
  > **不要在等它的同時再上傳別的東西**——Phase 48 踩過：兩件事同時打本機模型，
  > db container 被壓垮、postmaster 花 2 分鐘才殺得掉子行程。一次一件事。

- [x] **收工：回終端機 A 按 `Ctrl+C`**，工人應該優雅停下（Phase 88 做的訊號處理）：
      印一行 **「收到停止訊號」**、把手上那一則訊息做完之後結束，容器因為 `--rm` 自動刪掉。
      （`docker stop` 送的 SIGTERM 走的是同一條路，所以 EC2 上 `systemctl stop` 也是這個行為。）

  確認沒有殘留的容器：

```bash
docker ps -aq --filter ancestor=personaldocai-worker:local
```

  預期：沒有輸出（`-q` 只印容器 ID，一個都沒有＝`--rm` 已經清乾淨；
  不加 `-q` 的話 `docker ps` 就算沒東西也會印一行表頭，看起來像有輸出）。

- [x] **收工三件事：`.env` 改回 `off`／`300`、restart 本機 worker、AI 開關撥回 `local`**
      （Phase 86／88 收工時的同一條規則；總覽 §10 追認項 l：`assume` 只給丁段與除錯用）：

```ini
CLOUD_ROUTE=off
CLOUD_RESULT_TIMEOUT_SECONDS=300
```

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker
grep -n "^CLOUD_ROUTE=\|^CLOUD_RESULT_TIMEOUT_SECONDS=" .env
# 預期：CLOUD_ROUTE=off 與 CLOUD_RESULT_TIMEOUT_SECONDS=300 兩行

curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'
# 預期：{"backend":"local","cloud_configured":true}
```

  > ⚠ 忘了改回去的後果：雲端工人已經停了，之後**每一張非敏感照片**都會先送去 S3、
  > 傻等 `CLOUD_RESULT_TIMEOUT_SECONDS`（300 秒）才 fallback 本機——看起來像「上傳忽然變超慢」。
  > Phase 92 真機上線時才把它改成 `ec2`。

### 4.5 證明 `compose.yaml` 零改動而且行為不變

這一步是總覽 §10 追認項 j 的**驗證**：多階段 Dockerfile 沒有把 compose 弄壞。

> ⚠ **第一、三、四個證據由 controller 親自執行**（裁決 R3：`docker` 指令）。
> 第二個證據（`git status`）實作 subagent 自己就能跑。

- [x] **第一個證據：`docker compose config` 的輸出與改版前逐字相同**

```bash
# ⚠ -f 的組合要與 §2 ⑧ 拍基準時**完全相同**（現在是 dev overlay ＝兩個 -f），否則 diff 一定不是空的
docker compose -f compose.yaml -f compose.dev.yaml config > /tmp/p90-compose-after.yaml
diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml
```

  預期：**沒有任何輸出**（diff 沒輸出 ＝ 兩份完全一樣）。

  > 📌 為什麼這是有效的證據：`docker compose config` 會把 `compose.yaml` ＋ 環境變數
  > 展開成「Compose 實際看到的完整設定」。它一個字都沒變 ＝ compose 這一層完全沒被動到。
  > （這只證明**設定**沒變，不證明**建出來的映像**沒變——那是下一條在驗的。）

- [x] **第二個證據：`git status` 看不到 `compose.yaml`**

```bash
git status --short -- compose.yaml compose.dev.yaml
```

  預期：**沒有輸出**（兩份 compose 檔一個字都沒改）。

- [x] **第三個證據：重建映像，四個服務照常起來**（不帶 `--target`，所以建到最後一個 stage ＝ `app`）

  > 📌 **裁決 R8：本輪在 dev overlay 上重建**（現況就是 dev overlay，收工也留在 dev）。
  > 代價要講白：`compose.dev.yaml` 會把 `app` 的 `command:` 覆寫成它自己那條 uvicorn，
  > 所以**開發模式下 `docker compose ps` 的 COMMAND 欄看不出 stage 順序有沒有放錯**。
  > 補救的就是下面第三條 `docker image inspect`——它看的是**映像本身**的預設 CMD，
  > compose 覆不覆寫 `command` 都影響不了它，**不分模式都準**。
  > （真的想眼見為憑，之後切回常駐模式時再看一次 `docker compose ps --no-trunc` 即可；
  > 本 phase 不為了看那一欄而切模式。）

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
docker compose -f compose.yaml -f compose.dev.yaml ps --no-trunc
docker compose -f compose.yaml -f compose.dev.yaml config --services
# 預期恰四行：db／redis／app／worker

docker image inspect personaldocai-app --format '{{.Config.Cmd}}'
# 預期：[uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem]
#   ↑ ★ 這一條是「stage 順序沒放錯」的關鍵證據（不分模式都有效）。
#     印出 [python -m app.workers.cloud_worker] ＝ app 不是最後一個 stage，回 §4.2 改。
```

  預期：四個服務 `db`／`redis`／`app`／`worker` 都在；
  `db` 與 `redis` 是 `Up (healthy)`；
  `worker` 的 COMMAND 欄含 `--concurrency=2`；
  `app` 的 COMMAND 欄是 dev overlay 那條 uvicorn（**含 `--reload`**，這是開發模式的正常樣子）。

  > ⚠️ `--no-trunc` 不能省。不加的話 COMMAND 只印開頭 20 個字左右，
  > 你會看到 `"uvicorn app.main:a…"` 就以為通過了，其實根本沒顯示到後面
  > ——`--concurrency=2` 那一欄正好在結尾。

- [x] **第四個證據：app 真的還活著**：`curl -k -s https://127.0.0.1:8000/health`
      → `{"status":"ok"}`

- [x] **第五個證據：映像裡的東西剛剛好**（兩條指令與預期輸出寫在 §6 驗收清單的第 4、5 條，
      在那裡一併驗即可——重點是「工人程式真的進了映像」與「`data`／`certs`／`.env` 沒進去」）。

### 4.6 TDD：新開 `tests/integration/test_design6_error_paths.py`（4 顆掃碼）

> 📌 **這個檔在本 phase 開檔，不等到 Phase 95**（總覽 §10 追認項 B）。
> 理由：90／93／94 各自都有「部署設定檔掃碼」要放，全堆到 95 會讓 95 變成
> 一個要重讀五份設定檔的大 phase。

#### 步驟 1：先寫測試（紅）

- [x] 建立 `tests/integration/test_design6_error_paths.py`，內容如下（**完整可貼**）：

```python
"""增量六（design6.md）的錯誤路徑與「明確不做」收尾驗證。

體例沿用 Phase 25／37／44／71 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py、test_design5_error_paths.py）：
**先盤點、只補 ★ 缺口**——大多數行為已經由各 phase 自己的測試檔釘住了，
本檔只放「沒有別人守著」的那些，以及「掃設定檔文字」這種不屬於任何服務模組的斷言。

⚠ 本檔**分三次寫完**（增量六總覽 §10 追認項 B）：

| 何時 | 誰加 | 內容 |
|---|---|---|
| **Phase 90**（本次開檔） | 戊 | `Dockerfile` 多階段與 compose 零改動／零 AWS 設定的掃碼（4 顆） |
| Phase 93 | 己 | GitHub OIDC trust JSON 的掃碼（4 顆：`sub` 鎖 main、無萬用字元、aud、無寫死帳號 ID） |
| Phase 94 | 己 | CD workflow 的掃碼（6 顆：綁 test、id-token、arm64、target、sha tag、無金鑰） |
| Phase 95 | 收尾 | §8 錯誤表逐列補缺口 ＋ §0 六禁與 §1.2 被否決清單的掃碼（10 顆） |

⚠ 本檔**完全不連任何外部服務**：它讀的是磁碟上的設定檔（`Dockerfile`、`compose.yaml`、
   `compose.dev.yaml`），零 AWS、零 Docker daemon、零 Redis、零 Ollama。
   所以三個死埠一起指的時候顆數不會變。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_dockerfile() -> str:
    """讀專案根目錄的 Dockerfile 純文字。

    刻意不解析、不呼叫 docker——本檔在 CI 上也要能跑，而 CI 沒有 Docker daemon
    （.github/workflows/test.yml 只起一個 pgvector 附屬容器）。
    """
    return (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")


def read_compose() -> str:
    """讀 compose.yaml 純文字（與 test_design5_error_paths.py 同一手法）。"""
    return (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")


def read_compose_dev() -> str:
    """讀 compose.dev.yaml 純文字（開發 overlay；AWS 字樣兩份都要掃）。"""
    return (PROJECT_ROOT / "compose.dev.yaml").read_text(encoding="utf-8")


def compose_config() -> dict:
    """把 compose.yaml 解析成 dict。

    用 PyYAML 而不是自己寫正規式：`services:` 底下與檔尾 `volumes:` 底下的名字
    縮排一模一樣（都是兩格＋冒號結尾），正規式很容易把 pgdata／redisdata 一起抓進來
    （寫這份計畫時實測過，斷言會變成 6 個而永遠紅）。

    📌 PyYAML **不必**寫進 requirements.txt：它是 langchain-core（`pyyaml>=5.3`）
       與 pre-commit（`pyyaml>=5.1`）的必要相依，兩者都在 requirements.txt 裡，
       所以本機 .venv 與 CI 都一定裝得到。
    """
    return yaml.safe_load(read_compose())


def compose_services() -> list[str]:
    """`services:` 底下那一層的服務名，依 YAML 裡的出現順序。

    （Python 3.7 起 dict 保留插入順序，PyYAML 也是照檔案順序塞，所以順序斷言有意義。）
    """
    return list(compose_config()["services"])


def stage_names() -> list[str]:
    """把 Dockerfile 裡每一個 `FROM … AS <名字>` 的名字依出現順序抓出來。

    正規式說明：
      ^FROM\\s+       行首的 FROM 加至少一個空白
      \\S+            基底映像或上游 stage 名（不含空白的一串）
      \\s+AS\\s+      中間的 AS（Docker 不分大小寫，這裡用 re.I）
      ([\\w.-]+)      我們要的 stage 名字（英數、底線、點、減號）

    用 re.M 讓 ^ 對每一行生效；用 re.I 讓 `as` 小寫也抓得到。
    """
    return re.findall(r"^FROM\s+\S+\s+AS\s+([\w.-]+)", read_dockerfile(), re.M | re.I)


# ---- Phase 90：Dockerfile 多階段（design6 D15／D16、總覽 §10 追認項 j）----


def test_Dockerfile有cloud_worker這個target():
    """design6 §11 第 5 列：worker 映像走「多階段或第二 target」。

    我們選了多階段（總覽 §10 追認項 j），所以一定要有一個叫 cloud-worker 的 stage
    ——`docker build --target cloud-worker` 靠的就是這個名字。
    名字打錯（例如 cloud_worker、cloudworker）的話 build 會直接失敗，
    但**CD 的 yaml 也是照這個名字寫的**，兩邊要對得起來，所以在這裡釘死。
    """
    names = stage_names()

    assert "cloud-worker" in names, (
        f"Dockerfile 必須有一個 `FROM … AS cloud-worker` 的 stage；目前只有：{names}"
    )
    # 順便釘住共用底座還在：兩個下游 stage 要接在同一個 base 上，
    # 才不會變成「裝兩次套件」或「兩份會漂移的程式碼複製」
    assert "base" in names, f"Dockerfile 應該有共用的 base stage；目前只有：{names}"


def test_Dockerfile的app階段在最後():
    """總覽 §10 追認項 j ＋ §7 鐵律 11：compose 本增量零改動。

    ★ 這一顆守的是一個**安靜的**壞法：
      不帶 --target 的 `docker build .` 會建到**最後一個 stage**。
      compose.yaml 的 app 與 worker 兩個服務都寫 `build: .`（沒有 target:），
      所以 app 一旦不在最後，compose 就會蓋出一個「CMD 是雲端工人」的映像，
      然後 app 容器起來之後跑去 SQS 收訊息、沒有人聽 8000 埠
      ——**build 不會失敗、compose config 也看不出來**，只有服務莫名其妙不通。

    有人把 cloud-worker 搬到檔案最後的那一刻，這一顆會紅。
    """
    names = stage_names()

    assert names, "Dockerfile 裡一個具名 stage 都沒有？（多階段改壞了）"
    assert names[-1] == "app", (
        "app 必須是 Dockerfile 裡的**最後一個** stage，"
        f"否則 compose 的 `build: .` 會蓋出工人映像。目前順序：{names}"
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
    source = read_dockerfile()

    # ★ 三條都用「行首錨定」的正規式（re.M 讓 ^ 對每一行生效），刻意不用 `in`：
    #   `"ENV WORKER_VERSION=$GIT_SHA" in source` 這種寫法連被註解掉的
    #   `# ENV WORKER_VERSION=$GIT_SHA` 都會算命中，測試就假綠了——§4.6 步驟 3 的變異 2 在驗這件事。
    assert re.search(r"^ARG GIT_SHA(=\S*)?\s*$", source, re.M), (
        "cloud-worker stage 必須有 `ARG GIT_SHA`（CD 用 --build-arg 傳）"
    )
    assert re.search(r"^ENV WORKER_VERSION=\$GIT_SHA\s*$", source, re.M), (
        "必須把 ARG 烙成 ENV WORKER_VERSION，工人啟動 log 才印得出 version=<sha>"
    )
    # CMD 用 JSON 陣列寫法（exec form），訊號才收得到——Ctrl+C／SIGTERM 要能停得下來
    assert re.search(r'^CMD \[.*"app\.workers\.cloud_worker".*\]\s*$', source, re.M), (
        "cloud-worker 的 CMD 必須跑 python -m app.workers.cloud_worker"
    )


def test_compose_yaml沒有新增服務也沒有AWS設定():
    """總覽 §7 鐵律 11 ＋ §10 追認項 j：Dockerfile 改多階段之後，compose **不必跟著動**。

    ★ 本顆守四件事（第 ④ 條是 2026-09-02 校準裁決 R10 加的——這顆的名字本來就承諾了
      「也沒有 AWS 設定」，卻把那一半推給 Phase 95，名不副實）：

      ① 兩份 compose 都**沒有 `target:` 字樣**，而 app 與 worker 的 `build:` 仍然只是 `.`。
         這正是「app stage 放最後」換來的東西：不帶 `--target` 的 `docker build .`
         會停在最後一個 stage ＝ app，所以 compose 不必知道 stage 的存在。
         哪天有人在 compose 裡加 `target:`，就代表 Dockerfile 的 stage 順序被動過了
         ——這一顆會在那一刻紅。
      ② `image: personaldocai-app` 兩處都在（app 與 worker 共用同一份映像）。
      ③ 服務**恰好**仍是 db／redis／app／worker 四個
         （手滑加第五個 cloud-worker 服務的話，它開機就會自己跑起來、默默把 SQS
           訊息吃光——而 EC2 上那台也在收同一條佇列）。
      ④ 兩份 compose 全文**零** `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE` 字樣
         （design6 §3：雲端路的設定只走 `.env`，不進版控的 compose；
           寫進 compose 等於把 bucket 名與佇列 URL 推上 public repo）。

    📌 Phase 95 的 `test_compose沒有為了雲端新增任何服務` 仍可以再加一顆更廣的
       （例如連 `.github/workflows/` 一起掃）；兩顆不衝突，本 phase 先把自己的名字守住。
    """
    source = read_compose()
    dev_source = read_compose_dev()

    # ① 沒有任何 target:（先驗這條——它是最直接的訊號）
    assert "target:" not in source, (
        "compose.yaml 不該出現 `target:`——app stage 放在 Dockerfile 最後，"
        "就是為了讓 compose 不必指定 stage（總覽 §10 追認項 j）"
    )
    assert "target:" not in dev_source, "compose.dev.yaml 也不該出現 `target:`（同上）"

    # ①② build 仍是 `.`、而且兩個服務共用同一份映像名
    services = compose_config()["services"]
    for name in ("app", "worker"):
        assert services[name]["build"] == ".", (
            f"{name} 服務應該仍是 `build: .`（用同一份 Dockerfile 的最後一個 stage）；"
            f"目前是：{services[name].get('build')!r}"
        )
        assert services[name]["image"] == "personaldocai-app", (
            f"{name} 必須指向映像名 personaldocai-app（app 與 worker 共用同一份映像）"
        )

    # ③ 服務清單：恰好四個，順序也不變
    names = compose_services()
    assert names == ["db", "redis", "app", "worker"], (
        f"compose.yaml 的服務必須仍是四個（db／redis／app／worker）；目前是：{names}"
    )

    # ④ 兩份 compose 都不准出現雲端路的設定名（design6 §3；repo 是 public）
    for filename, text in (("compose.yaml", source), ("compose.dev.yaml", dev_source)):
        for keyword in ("AWS_", "S3_BUCKET", "SQS_", "CLOUD_ROUTE"):
            assert keyword not in text, (
                f"{filename} 不該出現 `{keyword}`——雲端路的設定只走 .env（design6 §3），"
                "寫進 compose 等於把 bucket 名與佇列 URL 推上 public repo"
            )
```

#### 步驟 2：**在改 Dockerfile 之前**跑它，確認 3 顆紅、1 顆綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：**3 failed, 1 passed**。逐顆的紅字長這樣（現在的 `Dockerfile` 還是單階段、
  一個 `FROM … AS …` 都沒有，所以 `stage_names()` 回的是空清單 `[]`——
  2026-09-02 校準時把這四顆對著現況工作樹實跑過一次，輸出就是下面這樣）：

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
  而現在兩份 compose 本來就沒被改、也本來就零 AWS 字樣（2026-09-02 實查
  `grep -nE "AWS_|S3_BUCKET|SQS_|CLOUD_ROUTE|target:" compose.yaml compose.dev.yaml` 零命中）。
  它的紅色要靠步驟 3 的變異 3／4／5 才看得到。

- [x] **現在回去做 §4.2**（把 `Dockerfile` 換成三階段那一份），做完再跑一次：

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：**4 passed**。

#### 步驟 3：變異測試——證明這四顆真的抓得到 bug

> 📌 掃碼測試最容易變成「假綠」（斷言寫錯、掃錯檔、正規式永遠匹配不到但斷言用的是 `not in`）。
> 唯一可靠的檢查方式是**故意把產品檔改壞、看測試會不會紅**。
> 下面**五個**變異各做一次（第 5 個是裁決 R10 新增的那組斷言），**每一次都要記得改回來**。

- [x] **變異 1：把 `app` stage 搬到不是最後的位置**

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

- [x] **變異 2：把 `ENV WORKER_VERSION=$GIT_SHA` 那一行註解掉**

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

- [x] **變異 3：在 `compose.yaml` 加一個假的第五個服務**

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

- [x] **變異 4：在 `compose.yaml` 的 `app` 加一個 `target:`**（模擬「有人把 stage 順序改了、
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
  訊息含 `compose.yaml 不該出現 \`target:\``
  （就算有人把 `target:` 那一行拿掉、只留 `build: {context: .}`，第二段 `services["app"]["build"] == "."`
  也會紅——那時 `build` 是一個 dict 而不是字串 `"."`）。

```bash
cp /tmp/compose.yaml.bak compose.yaml
git status --short -- compose.yaml    # 預期：沒有輸出（真的還原了）
pytest tests/integration/test_design6_error_paths.py -q   # 預期：4 passed
```

- [x] **變異 5：在 `compose.yaml` 的 `worker` 塞一個 AWS 設定**（裁決 R10 新增的那一組斷言；
      模擬「懶得改 `.env`，直接寫進 compose」——那會把 bucket 名推上 public repo）

```bash
cp compose.yaml /tmp/compose.yaml.bak
```

  手動在 `worker:` 的 `environment:` 底下加一行（縮排跟旁邊的 `CELERY_BROKER_URL` 一樣）：

```yaml
      AWS_REGION: ap-northeast-1
```

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

  預期：`test_compose_yaml沒有新增服務也沒有AWS設定` **紅**，
  訊息含 `compose.yaml 不該出現 \`AWS_\``。

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

  預期：**672 passed ＋ 0 skipped**（開工基線 668 ＋ 本 phase 的 4 顆；2026-09-02 實查基線 644 起算，
  總覽 §2.7 寫的是「662（實 672）」的雙寫法）。

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

  預期：**672 passed**，與上一條逐字相同（零外部依賴實證）。

  > 📌 本檔那 4 顆讀的是磁碟上的設定檔、`import yaml` 也只是解析字串，
  > 所以三個死埠對它們完全沒有影響——顆數必然一致。

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

#### 步驟 6：**不 commit——記快照**

> ⛔ **本輪一律不 commit**（2026-09-02 裁決 R0，產品負責人指示）。
> 也**不要** `git add`、`git stash`、`git mv`（把計畫檔搬進 `finish/` 是 commit 時才做的事，
> 總覽 §7 鐵律 12）。收工只做兩件事：印一次工作樹的 tree SHA、確認動到的檔恰好是那三個。

```bash
cd /Users/linjunting/personalDocAI

# ① 印出收工當下的 tree SHA（與 §2 ⑧ 那顆相減就是本 phase 的全部改動）
#    snapshot-tree 只在物件庫多一顆 tree 物件，不碰 index、不建 commit、不動 stash
.superpowers/sdd/phase0902-2/snapshot-tree

# ② 兩顆 tree 相減，看改了什麼（<BEFORE> ＝ §2 ⑧ 記下的那串）
git diff --stat <BEFORE_TREE> <AFTER_TREE>
# 預期恰三個檔：
#   Dockerfile                                          （多階段）
#   .dockerignore                                        （+2 行、-0 行）
#   tests/integration/test_design6_error_paths.py        （新檔）

# ③ 保險起見再看一次工作區
git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml
# 預期：` M Dockerfile`、` M .dockerignore`、`?? tests/integration/test_design6_error_paths.py`
#       **`app/` 底下完全沒有變動**（本 phase 零產品 Python 變更）
```

> 📌 `/tmp` 的備份檔（`Dockerfile.bak`／`compose.yaml.bak`）在步驟 3 最後已經 `rm` 掉了；
> `.env` 本來就有 `.gitignore` 擋著，不會出現在上面任何一條的輸出裡。

### 4.7 ★ 閘門 G2

> 🚦 **G2 是「人」的動作，實作 subagent 不可以自己勾掉。**
>
> **2026-09-02 裁決 R2——G2 條件式通過：** 總覽 §4 寫明 G2 由人以「一句明確的話（口頭、對話、
> 或 **dev-prompt 檔案**）」確認。產品負責人的 dev-prompt `docs/plan/dev-prompts/phase0902-2.md`
> **已明示執行到 Phase 91**，並說明本輪的決策不必逐項徵求同意。因此本輪的 G2 成立條件是：
>
> 1. 下面這張表的每一條證據，**由 controller 親自跑出來**（裁決 R3：`docker`／`aws`／`.env`／煙霧）；
> 2. Phase 88 的 Mac 端到端與**本 phase 的容器端到端兩段都通過**；
> 3. 任一段失敗 → **停在 Phase 90**，回報產品負責人，**不進 91**。
>
> Phase 91 全部是免費資源（SG／S3 Gateway endpoint／IAM role／ECR repo，合計約 $0.04／月）
> 而且**不啟動任何實例**，所以 G2 真正擔心的「開機開始扣點數」在 91 不會發生。
> **產品負責人仍保有事後否決權**：若不認這次的 G2，91 建的東西全部可逆、手動刪掉即可
> （SG／endpoint／role／ECR），一毛點數都不會留下。

- [x] **controller 把下面這張表填好**（每一條都貼上實際跑出來的輸出），連同 §4.4 的煙霧 log
      一起放進本輪的 ledger（`.superpowers/sdd/phase0902-2/progress.md`）：

| # | 要驗的事 | 指令 | 預期 |
|---|---|---|---|
| 1 | 工人在 Mac 上跑通（Phase 88 的丁段驗收） | Phase 88 §4 的端到端 | 本機送出 → 工人看圖 → `result.json` → results → 本機 GetObject 入庫 |
| 2 | **arm64 映像建得出來** | `docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t personaldocai-worker:local .` | 最後一行 `naming to … personaldocai-worker:local` |
| 3 | **架構真的是 arm64** | `docker image inspect personaldocai-worker:local --format '{{.Architecture}}'` | `arm64` |
| 4 | **容器跑得起來、版本號正確** | `docker run --rm --env-file .env -e CLOUD_ROUTE=off personaldocai-worker:local` | 第一行 `INFO:     cloud_worker 啟動 version=<sha> region=… bucket=…`，`<sha>` 等於 `git rev-parse --short HEAD` |
| 5 | **用容器重做端到端成功**（內容非敏感的合成收據） | §4.4 全套 | 照片列 +1、S3 `documents/` 空、job 消失、`kind=vlm backend=cloud` ＋ `kind=embed backend=local` |
| 6 | **內容敏感的圖仍然零 S3**（合成假身分證） | §4.4 最後一組 | `route=local verdict=SENSITIVE`，S3 無該 job_id 的物件 |
| 7 | **compose 零改動** | `diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml`（兩次都要帶同樣的兩個 `-f`） | 沒有輸出 |
| 8 | **四個服務照常** | `docker compose -f compose.yaml -f compose.dev.yaml up -d --build` ＋ `… ps --no-trunc` ＋ `docker image inspect personaldocai-app --format '{{.Config.Cmd}}'` | 四個都 Up；**映像的預設 CMD 是 uvicorn**（不是工人） |
| 9 | **顆數** | `pytest -q` | 672 passed ＋ 0 skipped |
| 10 | **零外部依賴** | 三個死埠一起指 | 672 passed，與第 9 條相同 |

- [x] **controller 依裁決 R2 判定 G2 是否成立**，並把判定寫進 ledger。

  ❌ 實作 subagent **不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
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
 │  終端機 B：curl -F file=@/tmp/receipt-test.png  https://127.0.0.1:8000/photos │
 │            → 202（合成收據；閘門看的是**內容**，不是這個檔名）              │
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

> ⚠ **標了「（controller）」的條目由 controller 親自執行**（裁決 R3：`docker`／`aws`／`psql`／
> 打 `https://127.0.0.1:8000` 的 `curl`）。實作 subagent 只跑不帶這些的條目。

- [x] **`Dockerfile` 是三個 stage，順序正確**

```bash
grep -n "^FROM" Dockerfile
```

  預期恰三行，依序是：
  `FROM python:3.12-slim AS base`／`FROM base AS cloud-worker`／`FROM base AS app`。

- [x] **`.dockerignore` 多了 `deploy/`，其他行沒動**

```bash
grep -n '^deploy/$' .dockerignore     # 預期恰一行，緊接在 scripts/ 那一行後面（中間夾一行註解）
git status --short -- .dockerignore   # 預期： M .dockerignore
# 本輪不 commit，所以不用 git diff --stat <檔>（那要有 index／commit 才準）；
# 想看確切的增減行數，用 §2 ⑧ 與 §4.6 步驟 6 那兩顆 tree 相減：
#   git diff --stat <BEFORE_TREE> <AFTER_TREE> -- .dockerignore
#   預期：1 file changed, 2 insertions(+)（零刪除）
```

- [x] **arm64 工人映像建得出來，架構正確**（controller）

```bash
docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t personaldocai-worker:local .
docker image inspect personaldocai-worker:local --format '{{.Architecture}}'
```

  預期：`arm64`

- [x] **容器跑得起來，版本號等於當下的 commit 短碼**（controller）

```bash
git rev-parse --short HEAD
docker run --rm --env-file .env -e CLOUD_ROUTE=off personaldocai-worker:local
```

  預期：第一行 log 的 `version=` 後面與上一行輸出相同。看完按 `Ctrl+C` 停掉。

- [x] **工人程式真的在映像裡**（controller）

```bash
docker run --rm personaldocai-worker:local ls /app/app/workers
```

  預期：`__init__.py`  `cloud_worker.py`

- [x] **映像裡沒有 `data`／`certs`／`.env`／`tests`／`scripts`／`docs`／`deploy`**（controller）

```bash
docker run --rm personaldocai-worker:local ls -a /app
```

  預期：只有 `.`、`..`、`app`、`requirements.txt`。

- [x] **§4.4 的容器端到端做過一次，照片真的入庫**（controller）

```bash
psql -d PersonalDocAI -c "select id, left(text, 40) from photo order by id desc limit 1"
docker compose -f compose.yaml -f compose.dev.yaml logs --tail=200 worker \
  | grep -E "route=cloud|kind=embed backend=local"
```

  預期：看得到剛才那張的文字；兩行 log 都在。

- [x] **內容敏感的合成圖零 S3（Demo 1 的本機版）**（controller）

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # 讓 CLI 用 admin profile（.env 那把 key 有 ListBucket，這條跑得過；統一用 admin，Phase 88 陷阱 12）
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
docker compose -f compose.yaml -f compose.dev.yaml logs --tail=100 worker \
  | grep "route=local verdict=SENSITIVE"
```

  預期：S3 回應沒有 `Contents`；log 那一行看得到。

- [x] **S3 與兩條佇列在測試結束後是乾淨的**（controller）

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION" \
  --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json
aws sqs get-queue-attributes --queue-url "$SQS_RESULTS_QUEUE_URL" --region "$AWS_REGION" \
  --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json
```

  預期：S3 無 `Contents`；兩條佇列的 `ApproximateNumberOfMessages` 都是 `"0"`。

- [x] **compose 兩檔零改動（兩個證據；第二條 controller）**

```bash
git status --short -- compose.yaml compose.dev.yaml     # 預期：沒有輸出

# controller：-f 的組合要與 §2 ⑧ 拍基準時完全相同
docker compose -f compose.yaml -f compose.dev.yaml config > /tmp/p90-compose-after.yaml
diff /tmp/p90-compose-before.yaml /tmp/p90-compose-after.yaml   # 預期：沒有輸出
```

- [x] **四個服務照常，映像的預設 CMD 仍是 uvicorn**（controller；裁決 R8 走 dev overlay）

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
docker compose -f compose.yaml -f compose.dev.yaml ps --no-trunc
docker image inspect personaldocai-app --format '{{.Config.Cmd}}'
curl -k -s https://127.0.0.1:8000/health
```

  預期：四個都 Up、`db`／`redis` healthy；
  `docker image inspect` 印 `[uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile … --ssl-certfile …]`
  （★ 這才是「stage 順序沒放錯」的證據；dev overlay 會覆寫 `command:`，所以 `ps` 那一欄看不出來）；
  `worker` 的 COMMAND 含 `--concurrency=2`；health 回 `{"status":"ok"}`。

- [x] **全量 pytest 顆數 ＝ 開工基線 668 ＋ 4 ＝ 672（2026-09-03 實查：670 ＋ 4 ＝ **674**，88 fix round 多 2 顆）**（2026-09-02 實查 644 起算）

```bash
pytest -q
```

  預期：`672 passed`，且**沒有任何 skipped**。

- [x] **端點仍 22、openapi 零 DELETE**

```bash
pytest -q -k "端點"
```

  預期：全綠。`-k 端點` 會撈到十幾顆名字含「端點」的測試，三顆清點測試
  （`test_端點恰好是這22支`／`test_端點數仍為22`／`test_端點數不變`）一定在裡面。
  本 phase 沒碰任何 router，數字不該變。

- [x] **零依賴實證（三個死埠一起指）**

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

  預期：`672 passed`，與上面那條逐字相同。

- [x] **專案 `data/` 沒被弄髒**

```bash
ls data/staging/            # 預期：空的（或只剩正在跑的那一個）
git status --short -- data/ # 預期：沒有輸出（data/ 在 .gitignore 裡）
```

- [x] **`.env` 已改回 `off`／`300`、本機 worker 重啟過、AI 開關撥回 `local`**（controller；§4.4 收工那三件事）

```bash
grep -n "^CLOUD_ROUTE=\|^CLOUD_RESULT_TIMEOUT_SECONDS=" .env
# 預期：CLOUD_ROUTE=off 與 CLOUD_RESULT_TIMEOUT_SECONDS=300 兩行
curl -sk https://127.0.0.1:8000/settings/ai-backend
# 預期：{"backend":"local","cloud_configured":true}
```

- [x] **`docs/spec/` 一字未動**

```bash
git status --short docs/spec/
```

  預期：**零輸出**（總覽 §7 鐵律 16：本增量規格區全程唯讀）。

- [x] **只動了該動的檔**

```bash
git status --short -- app tests deploy Dockerfile .dockerignore compose.yaml
# 預期恰三行：
#    M Dockerfile
#    M .dockerignore
#   ?? tests/integration/test_design6_error_paths.py

# 更硬的證據：§2 ⑧ 與 §4.6 步驟 6 那兩顆 tree 相減（本輪不 commit，裁決 R0）
.superpowers/sdd/phase0902-2/snapshot-tree      # 印出收工的 tree SHA
git diff --stat <BEFORE_TREE> <AFTER_TREE>
```

  預期：只有那三個檔；`app/` 底下應該**完全沒有**變動（本 phase 零產品 Python 變更）。

- [x] **ruff 過**

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

  預期：`All checks passed!`

- [x] **★G2 的十條證據表已由 controller 填好並寫進 ledger，且依裁決 R2 判定成立**（§4.7）

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
   「還沒 build 之前」就抓到它。
   ⚠ **常駐模式**才能靠 `docker compose ps --no-trunc` 的 COMMAND 欄分辨
   （**`--no-trunc` 不能省**，不加的話 COMMAND 只印開頭 20 個字）；
   **開發模式**（`compose.dev.yaml`）會把 `app` 的 `command:` 覆寫成它自己那條 uvicorn，
   所以那一欄**永遠看起來是對的**、症狀藏得住。
   本輪停在 dev overlay（裁決 R8），所以 §4.5 第三個證據靠的是
   `docker image inspect personaldocai-app --format '{{.Config.Cmd}}'`
   ——它看的是**映像本身**的預設 CMD，compose 覆不覆寫 `command` 都影響不了它，**不分模式都準**。

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
   **正解：** `grep -n "AWS_ENDPOINT_URL" .env` 預期**零輸出**
   （2026-09-02 實查：`.env` 目前沒有這一行，這條陷阱現在是「別把它加進去」的提醒）；有的話刪掉。

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
   **正解：** 本 phase 一個字都不會動 compose，而 `docker compose config`
   只讀 compose 檔與環境變數、**不讀 Dockerfile**——所以**事後補拍一次就行**，結果一樣。
   ⛔ **本輪禁止 `git stash`**（裁決 R0：不 commit、不 add、不 stash、不 mv）。
   真的被改到了（`git status --short -- compose.yaml` 有輸出），就先 `git diff -- compose.yaml`
   看清楚改了什麼、手動改回去，再拍基準。
   ⚠ 另一個更常見的坑：兩次 `docker compose config` 用了**不同的 `-f` 組合**
   （一次帶 dev overlay、一次沒帶）——那樣 diff 一定不是空的，而且看起來像 compose 被改過。

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

11. **變異測試改壞了產品檔卻忘了還原。**
    **症狀：** `compose.yaml` 裡留著一個假的 `cloudworker` 服務，下次開機它就自己跑起來了
    ——然後它會默默地把 SQS 訊息吃光（陷阱 9）。
    **原因：** §4.6 步驟 3 有**五個**變異，每一個都要 `cp` 還原。
    **正解：** 每次還原之後**立刻**跑 `git status --short -- Dockerfile compose.yaml` 確認乾淨
    （`compose.yaml` 那一行必須是**沒有輸出**；`Dockerfile` 有 ` M` 是對的——本 phase 就是要改它）。
    全部做完再 `rm -f /tmp/Dockerfile.bak /tmp/compose.yaml.bak`。
    本輪不 commit（裁決 R0），所以最後那道保險是 §4.6 步驟 6 的兩顆 tree 相減
    ——`compose.yaml` 出現在 `git diff --stat` 裡就是忘了還原。

12. **在 ★G2 還沒過的時候就開始建 AWS 資源。**
    **症狀：** 「反正 SG 也不用錢，先建起來放著」——然後 EC2 也建了，忘了 Stop，點數開始燒。
    **原因：** G2 是**人**的閘門，不是「測試綠了就算過」。
    **正解：** 本 phase 的產出**一個 AWS 資源都沒有建**（只用了 Phase 84／85 已經建好的 S3 與 SQS）。
    2026-09-02 裁決 R2 讓 G2 條件式成立（dev-prompt 已明示執行到 91 ＋ 88／90 兩段端到端由
    controller 親跑通過），但那**不等於「可以跳過驗證」**：兩段端到端任一段失敗就停在 90。
    Phase 91 的第一行仍然會再問一次「★G2 通過了嗎」。

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
    **原因：** `.env` 那把 `personaldocai-mac` 的 key 掛的是 `deploy/aws/mac-policy.json`。
    工人要的是與本機端**反過來**的那一組動作（jobs `ReceiveMessage`／`DeleteMessage`／
    `ChangeMessageVisibility`、results `SendMessage`），少了就會在第一次 `ReceiveMessage` 撞 `AccessDenied`。
    📌 **2026-09-02 實查：這份 policy 已經有那一組了**（`WorkerReceiveJobs`／`WorkerSendResults` 兩個 Sid，
    另有 bucket ARN 的 `s3:ListBucket` 與 `ec2:DescribeInstances`；總覽 §10.2 追認項 N／P）。
    所以正常情況下**不會**撞到這一條——真的撞到，代表 AWS 上那份 policy 與 repo 裡的 JSON 不同步。
    **正解：** 回 Phase 82 用 `aws iam get-user-policy`／`list-attached-user-policies` 比對，
    把 AWS 上的版本更新成 `deploy/aws/mac-policy.json` 的內容（controller 執行）。
    **不要**在本 phase 臨時把 admin 的 key 塞進 `.env` 或 `--env-file` 進容器。

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
  📌 **分工講清楚：** 本 phase 那 4 顆守「Dockerfile 的三個 stage」與
  「多階段沒有波及 compose」（`build: .` 沒有 `target:`、`image: personaldocai-app` 兩處、
  服務恰四個），**外加**「兩份 compose 全文零 `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE`」
  ——那半段是 2026-09-02 裁決 **R10** 收回來的：第 4 顆的名字（`…也沒有AWS設定`）本來就承諾了它。
  **Phase 95 的 `test_compose沒有為了雲端新增任何服務` 仍可以再加一顆更廣的**
  （例如連 `.github/workflows/` 一起掃），兩顆不衝突、部分重複是刻意的。

**對外行為變了沒：**

**完全沒有。** 端點仍是 **22** 支、`openapi.json` 仍零 DELETE、
`POST /photos` 仍回 202 且 body 恰三鍵、`GET /ingest-jobs` 回應形狀不變、
前端一行都沒改、資料庫結構零改動、`compose.yaml` 與 `compose.dev.yaml` 一個字都沒動
（`.dockerignore` 那一行只影響 build context，映像內容與啟動行為都不變）。
`app/` 底下的 Python **零變更**。

**顆數：** 開工基線 **668** ＋ 本 phase **4** ＝ **672 passed ＋ 0 skipped**
（2026-09-02 實查基線 644 起算；總覽 §2.7／§9 的絕對值寫的是「662（實 672）」的雙寫法，
**「本 phase 新增 4 顆」與總覽零偏離**）。

**下一步：**

★ **閘門 G2**（人）——依 2026-09-02 裁決 **R2**：產品負責人的 dev-prompt 已明示執行到 91，
controller 把 §4.7 的十條證據親自跑完、且 Phase 88 的 Mac 端到端與本 phase 的容器端到端
**兩段都通過**，G2 即成立（產品負責人保有事後否決權；91 建的全部是免費且可逆的資源）。

過了之後是 **Phase 91（`phase-91-EC2的網路IAM與ECR.md`）**：
用 AWS CLI 建 security group（**inbound 空**、outbound 只開 TCP 443）、
S3 Gateway VPC endpoint（免費）、EC2 用的 IAM role ＋ 同名 instance profile、
ECR repository，並把本 phase 建好的 `personaldocai-worker:local`
第一次手動 `docker tag` ＋ `docker push` 上去。
**Phase 91 尚不啟動任何 EC2 實例**——那是 Phase 92。

---

## 9. 實作紀錄（2026-09-02，實作 subagent）

**結論：照計畫做完，一處手法差異（變異 3／4／5 改成記憶體變異，見下）。**
動到的檔恰三個：`Dockerfile`、`.dockerignore`、`tests/integration/test_design6_error_paths.py`。
**零 `docker`／`aws` 指令、零 `app/` Python 變更、零 compose 變更、未 commit**（裁決 R0／R3）。

| 項目 | 實際值 |
|---|---|
| 開工基線（實查 `pytest -q`） | **670 passed、0 skipped**（89 做完之後的實際值；本檔 §2／§4.6／§6 原寫的 668 是 88 review fix 前的預估） |
| 收工全量 `pytest -q` | **674 passed、0 skipped**（＝670 ＋ 4；本 phase 新增恰 4 顆，與總覽 §2.7 相同） |
| 三死埠（`AWS_ENDPOINT_URL`／`CELERY_BROKER_URL`／`OLLAMA_BASE_URL` 全指 `127.0.0.1:9`） | **674 passed**（顆數逐字相同＝零外部依賴；本檔那 4 顆只讀磁碟設定檔） |
| warning | 只有基線那一個 `StarletteDeprecationWarning`（環境層，非本 phase 造成） |
| `ruff format --check` ／ `ruff check` | `114 files already formatted` ／ `All checks passed!` |
| 端點 | **22**（`pytest -q -k 端點` → `15 passed`；未動任何 router） |
| 識別字掃碼（tokenize，排除 `test_` 開頭） | `[]`（新測試檔零中文識別字，裁決 R1） |
| 工作樹快照 tree SHA（三個檔改完、本檔勾選之前） | `867276c9c4087994a1437ddd8b9c22508d59d2b8`；與 `T90_BASE`（`a242b744…`）相減恰本 phase 三檔（另有一份 controller 自己在更新的 TODO 檔） |
| HEAD | 仍是 `bb3921a`（無 commit／`git add`／`stash`） |

**RED 證據**（§4.6 步驟 2，改 `Dockerfile` **之前**跑
`pytest tests/integration/test_design6_error_paths.py -v`）：
**`3 failed, 1 passed`**，與計畫檔預測逐字相同——三顆紅的訊息分別是
`…目前只有：[]`、`Dockerfile 裡一個具名 stage 都沒有？（多階段改壞了）`、
`cloud-worker stage 必須有 \`ARG GIT_SHA\``；第 4 顆（compose）如計畫所述一開始就綠。

**GREEN 證據**（§4.6 步驟 2 後半，改完 `Dockerfile` 之後同一個指令）：**`4 passed`**。

**變異測試（§4.6 步驟 3）：五個變異全部確認會紅、且訊息正確。**

| 變異 | 手法 | 結果 |
|---|---|---|
| 1 `app` stage 不在最後 | **真的改 `Dockerfile`**（備份→改→跑→還原，同一條指令內完成） | `test_Dockerfile的app階段在最後` 紅（`1 failed, 3 passed`），還原後 `4 passed` |
| 2 `ENV WORKER_VERSION=$GIT_SHA` 註解掉 | 同上（`sed -i ''`） | `test_Dockerfile的cloud_worker帶ARG_GIT_SHA` 紅（訊息含「必須把 ARG 烙成 ENV WORKER_VERSION」），還原後 `4 passed` |
| 3 compose 加第五個服務 | ⚠ **記憶體變異**（見下方差異說明） | 紅，訊息印出 `['db', 'redis', 'app', 'worker', 'cloudworker']` |
| 4 compose 的 `app` 加 `target:` | ⚠ 記憶體變異 | 紅，訊息含 ``不該出現 `target:``` |
| 5 compose 的 `worker` 塞 `AWS_REGION` | ⚠ 記憶體變異 | 紅，訊息含 ``不該出現 `AWS_``` |
| 5b（自行加碼）`compose.dev.yaml` 塞 `CLOUD_ROUTE` | ⚠ 記憶體變異 | 紅，訊息含 `compose.dev.yaml 不該出現 \`CLOUD_ROUTE\``——證明第 ④ 條真的**兩份都掃** |

**與計畫檔的差異（恰兩條，都不影響驗收內容）：**

1. **變異 3／4／5 沒有真的改 `compose.yaml`**，改成用一支拋棄式腳本（scratchpad，不入版控）
   直接指派測試模組的 `read_compose()`／`read_compose_dev()` 兩個模組屬性（等同 `monkeypatch`），
   把改壞的內容餵給**同一顆測試函式** `test_compose_yaml沒有新增服務也沒有AWS設定()`。
   理由：controller 本輪明令「`compose.yaml`／`compose.dev.yaml` 一個字都不准改」，
   而且變異當下有審稿者正在讀工作樹 diff，備份／還原的空窗期會讓他看到一份被改壞的 compose。
   為了補回「掃錯檔也會假綠」這個原本靠真檔案才能擋住的風險，變異前先斷言三個 reader
   各自讀的是不同的真檔案（`read_dockerfile()` 開頭、`read_compose()` 含 `name: personaldocai`、
   `read_compose_dev()` 開頭、且兩份 compose 內容不相等），並多做了變異 5b。
   `git status --short -- compose.yaml compose.dev.yaml` 全程零輸出。
   （變異 1／2 動的是 `Dockerfile`＝本 phase 自己的交付物，仍照計畫真的改檔。）
2. **顆數基線是 670 不是 668**（Phase 88 的 review fix round 多了幾顆），
   所以收工是 **674** 不是 672。「本 phase ＋4」與總覽 §2.7 一致。

**未做（留給 controller，裁決 R3）：** §4.2 的 `docker build --check`、§4.3（建 arm64 映像）、
§4.4（容器端到端）、§4.5（compose 零行為改變的 docker 證據）、§4.7（★G2 十條證據表），
以及 §6 中標「（controller）」的條目與「compose 兩檔零改動」那一條的第二個證據
（第一個證據 `git status --short -- compose.yaml compose.dev.yaml` 已由實作者跑過＝零輸出）。

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
