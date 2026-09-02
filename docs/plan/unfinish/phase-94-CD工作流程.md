# Phase 94：CD 工作流程

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別不要做的四件事：
> ① **不要**動 `.github/workflows/test.yml`（design6 D16：「現有 CI 不動契約」，`git diff` 對它必須是空的）；
> ② **不要**讓 CD 去開機或關機（`ec2:StartInstances`／`StopInstances` 這兩個權限 Phase 93 根本沒給——
> 開關機是人做的事，D15「用完就 Stop」是產品負責人的決定，不是自動化該搶的）；
> ③ **不要**加 staging／production 兩套環境、matrix、多架構（`linux/arm64` **一個**就好，
> EC2 是 t4g ＝ ARM）、Slack 通知、release note 產生器；
> ④ **不要**在 workflow 裡放任何 AWS 的長期金鑰——Phase 93 做 OIDC 就是為了不必放。

> 🎯 **一句話目標：** 新增 `.github/workflows/deploy.yml`：既有的 CI（`test`）在 `main` 上跑綠之後
> 自動觸發，用 Phase 93 的 OIDC 角色換一組臨時憑證，用 QEMU ＋ buildx 建出
> **`linux/arm64`** 的 `cloud-worker` 映像、推到 ECR（同時打 `<commit sha>` 與 `latest` 兩個 tag），
> 最後**只在 EC2 是 `running` 的時候**用 SSM Run Command 重啟工人；EC2 是 `stopped` 時
> **這個 job 仍然算成功**（映像已經推上去了，下次開機自然拉到新的）。

---

**為什麼要做這個：**

**現在的痛（Phase 93 做完之後仍然存在）：** 鑰匙配好了，但門還沒裝。
改工人的程式碼還是得手動做三件事：`docker buildx build --platform linux/arm64 --target cloud-worker`
→ `docker push` → Session Manager 進去 `systemctl restart`。
三步任何一步忘了，EC2 上跑的就還是舊程式——**而且完全不會報錯**。

**做完之後：** `git push origin main` → 走開。

```text
git push ──► Actions「test」──綠──► Actions「deploy」──► ECR 有新映像
                                          └──► EC2 開著就順便重啟；沒開著也算成功
```

**為什麼 CD 要綁在 CI 之後，而不是自己也跑一次 push 觸發？**
因為「測試沒過的程式碼不該被部署」。GitHub 有一個專門的觸發條件叫 `workflow_run`：
「**另一個** workflow 跑完之後才觸發我」，而且事件裡帶著那次執行的結論（`success`／`failure`／…）
與**它測的那個 commit 的 SHA**。我們就用這兩樣東西：結論不是 `success` 就整個 job 不跑；
要 build 的程式碼就 checkout 那個 SHA（**不是** `main` 的最新，理由見 §7 陷阱 2）。

**為什麼「EC2 關著也算成功」不是偷懶？**
design6 D16 明文：「**EC2 Stop 時 CD 仍可 push ECR；下次 Start 再拉**」。
產品負責人的常態是 **EC2 關著**（D15：要卡片 $0、用完就 Stop）。
如果「機器沒開 → CD 失敗」，那 GitHub 上會永遠是一片紅 ×，紅到你不再看它——
那才是真的危險（真正的失敗也被淹沒了）。所以：機器沒開時印一行 `::notice::` 然後
`exit 0`，Actions 顯示綠色 ✓ 並在頁面上留一則說明。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **CD（Continuous Deployment）** | 「持續部署」。CI 是「自動驗證」，CD 是「驗過就自動送出去」。本專案的 CI 是 Phase 73 的 `test`，CD 就是本 phase |
| **workflow** | `.github/workflows/` 底下的一個 `.yml` 檔 ＝ 一套自動化流程。本專案做完會有**兩個**：`test`（CI）與 `deploy`（CD） |
| **`workflow_run`** | 一種觸發條件：「**另一個** workflow 跑完之後才觸發我」。事件內容裡有 `conclusion`（成功還是失敗）與 `head_sha`（被觸發的那次跑的是哪個 commit） |
| **`head_sha`** | `workflow_run` 事件帶的那個 commit SHA ＝ **CI 實際測過的那一版**。⚠ 它**不等於** `github.sha`（見 §7 陷阱 2） |
| **預設分支（default branch）** | repo 的主分支，本專案是 `main`。`workflow_run` 有一個關鍵性質：**只有放在預設分支上的 workflow 檔才會被觸發**，而且它**跑在預設分支的上下文**底下 |
| **job** | workflow 裡的一個「工作」，跑在一台乾淨的虛擬機上。本 phase 只有一個 job，叫 `deploy` |
| **step** | job 裡的一步。可以是 `uses:`（用別人寫好的 action）或 `run:`（跑一段 shell） |
| **action** | 別人寫好、可以直接拿來用的一步。寫成 `擁有者/名字@版本`，例如 `actions/checkout@v7` |
| **`permissions`** | 這個 job 拿到的 GitHub 權限。`id-token: write` ＝「**准我跟 GitHub 要一張 OIDC 令牌**」（沒有這一行，Phase 93 的整套 OIDC 都用不了）；`contents: read` ＝ checkout 要用的讀取權 |
| **`concurrency`** | 「同一時間只准跑一個」。給一個 `group` 名字，同 group 的第二次會排隊等（或取消前一次） |
| **`cancel-in-progress`** | 排隊時要不要**取消**前一次。本專案 **`false`**（＝排隊，不取消）。理由見 §7 陷阱 5 |
| **GitHub variable** | repo 設定裡的**不加密**字串，用 `${{ vars.名字 }}` 取。跟 secret 是**兩個不同的命名空間**，寫錯會拿到空字串而且不報錯 |
| **runner** | GitHub 提供的那台跑 job 的虛擬機。`ubuntu-latest` 的 CPU 是 **x86_64**（也叫 amd64），**不是** ARM |
| **QEMU** | 一個模擬器。讓 x86_64 的機器「假裝」成 ARM 去跑指令，這樣才 build 得出 ARM 的映像。**慢**（第一次 5〜15 分鐘） |
| **buildx** | Docker 的多平台建置外掛。`docker build` 只會蓋出「跟你這台一樣的架構」；buildx 才能指定 `--platform` |
| **`--platform` / `platforms:`** | 「這個映像是給哪種 CPU 跑的」。本專案固定 **`linux/arm64`**（EC2 是 t4g ＝ AWS 自研 ARM 晶片） |
| **`target`** | 多階段 Dockerfile 裡「要停在哪一段」。Phase 90 把 Dockerfile 改成 `base` → `cloud-worker` → `app`；CD 要的是中間那段，所以 `target: cloud-worker` |
| **build arg（`build-args`）** | build 當下傳給 Dockerfile 的變數。本專案傳 `GIT_SHA`，Dockerfile 把它變成映像裡的環境變數 `WORKER_VERSION`，工人啟動時印在 log 裡 |
| **ECR registry URI** | 你的私有 registry 的網址，長得像 `<ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com`。`amazon-ecr-login` 這個 action 會把它放進 `steps.<id>.outputs.registry`，所以 workflow 裡**不必寫死帳號 ID** |
| **image tag（映像標籤）** | 同一個 registry 裡分辨版本用的名字，例如 `:abc1234` 與 `:latest`。**同一份映像可以同時掛好幾個 tag** |
| **`latest`** | 一個**會動**的 tag（永遠指向最後推上去的那一份）。本專案照推，但**驗證「跑的是不是新映像」不靠它**——靠工人啟動時印的 `version=<sha>`（design6 D16、總覽 §10 追認項 e） |
| **build cache（`type=gha`）** | 把 build 的中間結果存在 GitHub 的快取空間，下次 build 能重用。QEMU 很慢，有快取差很多 |
| **SSM Run Command** | 從外面對一台 EC2 下一句指令，不必 SSH。送出時會拿到一個 **CommandId**，之後用它查跑完了沒 |
| **`AWS-RunShellScript`** | AWS 官方預設的 Run Command「劇本」，意思就是「跑一段 shell」 |
| **`::notice::`** | GitHub Actions 的一種輸出格式。在 `run:` 裡 `echo "::notice::某句話"`，那句話會以藍色提示框顯示在這次執行的摘要頁上（`::error::` 是紅色） |
| **fork PR** | 別人 fork 你的 repo 之後開的 PR。GitHub **不會**把 secret 給它觸發的 `test`（安全設計）——**但 `workflow_run` 觸發的 `deploy` 跑在預設分支上下文、拿得到 secret**，這是 GitHub 官方文件在 `workflow_run` 那一節特別警告的坑。所以 `deploy` 的 `if` 只認 `event == 'push'`（PR 觸發的 `test` 完成時一律不部署），見 §7 陷阱 8 |

---

## 1. 對應 design6.md 章節

| 出處 | 說的是什麼 | 本 phase 怎麼落地 |
|---|---|---|
| **D16**（CI／CD 分開） | 「現有 GitHub Actions CI **不動契約**。CD：CI 綠 → OIDC 短憑證 → build `linux/arm64` → ECR `personaldocai:<git-sha>` → SSM Run Command 在 EC2 上 pull＋重啟。**EC2 Stop 時 CD 仍可 push ECR；下次 Start 再拉**」 | §4.3 的 `deploy.yml` 逐句落地；`test.yml` 零改動（§4.6 用 `git diff --stat` 證明）；最後一步的 `stopped → notice ＋ exit 0` 就是「Stop 時仍可 push」 |
| **§0 己那列** | 「何時可以開始：戊能手動部署。何時算過：push 後 ECR 有 `<sha>`；SSM 更新；**不靠 `latest` 當唯一 tag**」 | §4.8 的 Demo 3 逐條；tag 打**兩個**（`<sha>` ＋ `latest`），但驗證靠工人 log 的 `version=<sha>` |
| **§12 Demo 3** | 「改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA → Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）」 | §4.8 是這一條的逐步操作手冊 |
| **D15**（Free plan） | 「映像 **`linux/arm64`**，機型 **t4g.small**」 | `platforms: linux/arm64`；§4.5 有一顆測試釘住「只有 arm64」 |
| **總覽 §2.8 裁決** | ECR repository ＝ `personaldocai-worker`；EC2 的 systemd 服務 ＝ `personaldocai-worker.service` | `env.ECR_REPOSITORY` 與 SSM 那句 `systemctl restart personaldocai-worker` 逐字沿用 |
| **總覽 §10 追認項 b／e ＋ §10.2 M 列裁決** | b：分支是 `main`（design6 §6 寫 `master` 是筆誤）；M：trust 的 `sub` 前綴採 GitHub 不可變主體格式 `repo:1104030360@92135456/personalDocAI@1349196211`（Phase 93 鎖的完整字串＝前綴＋`:ref:refs/heads/main`）；e：CD 同時推 `<sha>` 與 `latest`，「跑的是不是新映像」靠 `WORKER_VERSION` 的 log 驗 | `branches: [main]`；`tags:` 兩行；§4.8 第 5 步用 `docker logs` 看 `version=` |
| **§6 安全與隱私**（IAM 最小權限、機密不進文件） | GitHub OIDC role 只做 ECR push／SSM／Describe；trust 鎖 repo＋分支；文件只寫變數名 | workflow **零長期金鑰**（`test_CD沒有寫死任何AWS金鑰`）；job 的 `if` 只認 `push` 事件——PR（含 fork）觸發的 CI 完成時**不准**拿 secret 去部署（GitHub 官方對 `workflow_run` 的安全建議，§7 陷阱 8） |
| **總覽 §7 鐵律 7／11／13** | 端點恆 22；`compose.yaml` 零改動；正式庫零改動 | 本 phase 只新增一個 workflow 檔與 6 顆測試，三件事都不碰 |

---

## 2. 前置條件

- **Phase 93 已完成**：OIDC provider 建好、角色 `personaldocai-github-deploy` 建好、
  GitHub repository secret **`AWS_DEPLOY_ROLE_ARN`** 已設定、4 顆掃碼測試綠。
- **★ 閘門 G3 已由產品負責人通過**（G3 是 Phase 93 的門檻，93 過了 94 就不必再問一次）。
- ECR repository `personaldocai-worker` 存在，而且裡面**已經有一個 Phase 91 手動推上去的
  arm64 映像**（tag 是當時 `git rev-parse --short HEAD` 的**短** sha ＋ `latest`；
  沒有的話 §4.8 的「有沒有變新」就沒有對照組）。
- `Dockerfile` 已經是 Phase 90 的多階段版本（`base` → `cloud-worker` → `app`，
  `cloud-worker` 這一段帶 `ARG GIT_SHA`）。
- `.env` 的 `EC2_WORKER_INSTANCE_ID` 已填、EC2 目前是 **`stopped`**。

### 開工基線（自己再驗一次，不要抄）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ 本機 aws 指令走 personaldocai-admin 的 default profile（Phase 82 定案）；
                                                #   .env 那把 personaldocai-mac 的 key 沒有 ECR／EC2 Start／SSM 權限，不 unset 會 AccessDenied
AWS_REGION=${AWS_REGION:-ap-northeast-1}

pytest -q
# 預期：666 passed ＋ 0 skipped（Phase 93 之後的累計）

git branch --show-current            # 預期：main
gh secret list                       # 預期：看得到 AWS_DEPLOY_ROLE_ARN
ls .github/workflows/                # 預期：只有 test.yml（deploy.yml 還沒有）

grep -n "cloud-worker\|ARG GIT_SHA\|^FROM" Dockerfile
# 預期：看得到三個 FROM（base／cloud-worker／app，而且 app 在最後）
#       以及 cloud-worker 那一段的 ARG GIT_SHA

aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
  --query 'imageDetails[?imageTags].imageTags[]' --output json
# 預期：一個攤平的 tag 陣列，至少含 "latest" 與 Phase 91 手動推的那個短 sha，例如 ["latest", "a53ab57"]
# （[?imageTags] 先濾掉沒有 tag 的映像、[] 再攤平；寫成 imageDetails[].imageTags 會混進 null——Phase 91／92 同款寫法）

aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
# 預期：stopped
```

把數字填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | ＿＿＿ passed ＋ 0 skipped（總覽 §9 校正後為 **666**） |
| 開工時 `test_design6_error_paths.py` 顆數 | ＿＿＿（總覽 §9 寫 **8** ＝ 90 的 4 ＋ 93 的 4） |
| 開工時 ECR 上已有的 tag | ＿＿＿（Demo 3 要拿來對照） |
| EC2 狀態 | ＿＿＿（開工時應是 `stopped`） |

---

## 3. 範圍

### 做

- 新增 **`.github/workflows/deploy.yml`**（`name: deploy`）。
- 設一個 GitHub **variable**（不是 secret）`EC2_WORKER_INSTANCE_ID`。
- 在 `tests/integration/test_design6_error_paths.py` 追加 **6 顆**掃碼測試（名稱見 §4.5）。
- `README.md` §9 "Development and testing" 段加一小段 **"CI/CD"**（**英文**——
  `README.md` 自 2026-08-27 起是英文，總覽 §3.8）。
- 人工 **Demo 3**（design6 §12）：在 `cloud_worker.py` 加一行註解（＝「改 worker 一點點」）→ push
  → CI 綠 → CD 綠 → ECR 有 `<sha>` → Start → SSM 看 `version=<sha>` → **Stop**。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改 `.github/workflows/test.yml` | design6 D16「現有 CI 不動契約」。`git diff --stat` 對它必須是空的 |
| 讓 CD 開機／關機（`ec2:StartInstances`／`StopInstances`） | 開關機是人的決定（D15：用完就 Stop）。而且 Phase 93 的 policy 根本沒給這兩個權限——加了 workflow 也會 AccessDenied |
| build `linux/amd64`（或用 matrix 建兩種架構） | EC2 是 **t4g ＝ ARM**。多建一份 x86 的映像只是讓 QEMU build 時間翻倍、ECR 多存一份沒人拉的東西 |
| 加 staging／production 兩套環境、GitHub Environments、required reviewers | 單人 side project、只有一台機器。加了只會讓自己 push 不上去 |
| 在 CD 裡跑 pytest／ruff | CI（`test`）已經跑過了，而且 CD 是「**它綠了**才觸發」。重跑一次只是多等五分鐘 |
| 在 CD 裡建 `app` 映像、或碰 `compose.yaml` | `app` 跑在這台 Mac 上，不上雲（design6 §1.1 第 2 列：**不**把 FastAPI／Postgres／Redis／Celery／Ollama 搬上雲）。總覽 §7 鐵律 11：compose 本增量零改動 |
| 用 `latest` 當「有沒有更新」的判準 | D16 明文「不靠 `latest` 當唯一 tag」。`latest` 是會動的標籤，看它永遠是「最新」，證明不了任何事。判準是工人啟動 log 的 `version=<sha>` |
| Slack／Email 通知、release note、自動 tag | 菜單項目。GitHub 本來就會在 job 失敗時寄信給你 |
| 把 role ARN／帳號 ID／實例 ID 的**值**寫進 `deploy.yml` | 總覽 §7 鐵律 10。role ARN 走 `secrets`、實例 ID 走 `vars`、registry 位址由 `amazon-ecr-login` 的 output 給 |
| 用 `docker/login-action` ＋ 手動 `docker login` | `aws-actions/amazon-ecr-login` 一步就做完（換 ECR 密碼 ＋ `docker login` ＋ 吐出 registry 位址），少一個要維護的東西 |
| 動 `app/` 底下任何一個 `.py`（Demo 3 加的那一行註解除外） | 本 phase 零產品碼改動。Demo 3 為了產生一個新 commit 會在 `cloud_worker.py` **加一行註解**（不改任何行為、不動啟動 log 的字——理由見 §4.8 步驟 1），那是**刻意的一行**，而且要 commit 進去 |

---

## 4. 實作步驟

### 4.1 先查證：每個 action 的現行大版號是多少（2026-08-31 實查）

**為什麼要先查：** GitHub Action 的大版號**會過期**。舊大版停止維護之後，
runner 會在 log 印警告（`Node.js 16 actions are deprecated`），最後直接不能跑。
網路上 2023〜2025 年的 CD 範例寫的版本，2026 年多半已經落後兩個大版。

實查方法（本機就能跑，不必開瀏覽器）：

```bash
for r in actions/checkout aws-actions/configure-aws-credentials \
         aws-actions/amazon-ecr-login docker/setup-qemu-action \
         docker/setup-buildx-action docker/build-push-action; do
  echo -n "$r : "
  curl -s "https://api.github.com/repos/$r/releases/latest" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tag_name'], d['published_at'])"
done
```

**2026-08-31 的實查結果，以及本檔採用的版本：**

| action | 官方最新 tag（2026-08-31） | 本檔採用 | 總覽／brief 當初寫的 | 說明 |
|---|---|---|---|---|
| `actions/checkout` | `v7.0.1`（2026-07-20） | **`@v7`** | v4 | **本 repo 既有的 `test.yml` 已經在用 `actions/checkout@v7`**——兩個 workflow 用同一個大版，維護時不必記兩套。v7.0.0 另加了一道安全措施：在 `workflow_run`／`pull_request_target` 底下**拒絕 checkout fork PR 的 commit**（§7 陷阱 8 的第三道保險）；`ref` 輸入名不變 |
| `aws-actions/configure-aws-credentials` | `v6.2.4`（2026-08-31） | **`@v6`** | v4 | v6.0.0（2026-02-04）的 breaking change 只有「改用 Node 24 執行環境（runner ≥ v2.327.1）」；本檔用到的 `role-to-assume`／`aws-region` **輸入名一字未變** |
| `aws-actions/amazon-ecr-login` | `v2.1.7`（2026-08-19） | **`@v2`** | v2 | 一致，沒有差異 |
| `docker/setup-qemu-action` | `v4.2.0`（2026-07-01） | **`@v4`** | v3 | v4 的 breaking change 只有 Node 24 執行環境 |
| `docker/setup-buildx-action` | `v4.3.0`（2026-08-19） | **`@v4`** | v3 | 同上（另外移除了幾個早就標 deprecated 的輸入，本檔沒用到） |
| `docker/build-push-action` | `v7.3.0`（2026-07-01） | **`@v7`** | v6 | v7 的 breaking change 是 Node 24 ＋ 移除兩個 deprecated 的環境變數；本檔用到的 `context`／`target`／`platforms`／`push`／`build-args`／`tags`／`cache-from`／`cache-to` **輸入名一字未變** |

> ✅ **brief §3.8 已改為「action 大版號以本表為準」（2026-08-31）**，總覽本身沒有列版號，
> 所以本檔與總覽／brief **沒有差異**。右邊「當初寫的」那一欄只是歷史紀錄（2025 年的版本號），
> 留著說明為什麼不照抄：① 本 repo 的 `test.yml` 已經用 `@v7`（不一致會讓維護的人困惑）；
> ② 每個大版的 breaking change **都只是 Node 執行環境與內部清理**，本檔用到的輸入名稱
> 一個都沒改；③ 舊大版會逐步停止支援，寫進計畫等於埋一顆未來的雷。
>
> **reviewer 2026-08-31 再查證一次**（六個 releases 頁逐一打開，連結在文末「附」）：
> 最新 tag 與上表逐字相同；`configure-aws-credentials` v6.0.0、`setup-qemu-action` v4.0.0、
> `setup-buildx-action` v4.0.0、`build-push-action` v7.0.0 的 breaking change 都是
> 「Node 24 執行環境（runner ≥ v2.327.1）＋ 移除早已 deprecated 的輸入／環境變數」，
> 本檔用到的輸入一個都不在移除清單裡；`actions/checkout` v7.0.0 多的是**安全**措施
> （`workflow_run` 底下拒絕 checkout fork PR），正好是本 phase 要的。
>
> **真的要改版號：** 只要把 §4.3 那份 `deploy.yml` 裡六個 `@vN` 的數字改掉，
> **其餘內容一個字都不必動**（輸入名稱各大版相同）。

**釘大版還是釘完整版號？** 本專案**釘大版**（`@v7` 而不是 `@v7.3.0`）。
理由與 `requirements.txt` 全部用 `>=` 一致：side project 不做 lock，
換來的是「修 bug 的小版自動吃到」。真的要更嚴（供應鏈安全等級）就釘 commit SHA，
但那要自己定期更新，本專案不做。

- [ ] 跑過上面那個 `for` 迴圈，把當天的實查結果填進表格右邊
      （版本比表上更新是正常的；**大版號變了**才要停下來想一下）。

### 4.2 設一個 GitHub variable：`EC2_WORKER_INSTANCE_ID`

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # 習慣：載完 .env 就拿掉兩把 key（這裡只跑 gh、沒有 aws 指令，不 unset 也不會出事）
gh variable set EC2_WORKER_INSTANCE_ID --body "$EC2_WORKER_INSTANCE_ID"
```

**預期輸出：**

```text
✓ Created variable EC2_WORKER_INSTANCE_ID for 1104030360/personalDocAI
```

（同一個指令再跑一次會印 `✓ Updated variable …`——兩種都是成功；`gh` 原始碼裡就只有 Created／Updated 兩個字。）

```bash
gh variable list
```

**預期輸出（variable 看得到值，這是它與 secret 最大的差別）：**

```text
NAME                      VALUE                  UPDATED
EC2_WORKER_INSTANCE_ID    i-0xxxxxxxxxxxxxxxx    less than a minute ago
```

> 💡 **Console 路徑：** GitHub → repo → **Settings** → **Secrets and variables** →
> **Actions** → 切到 **Variables** 分頁 → **New repository variable**。

**為什麼是 variable 不是 secret：**

| | secret | variable |
|---|---|---|
| 加密 | 是（放進去看不回來） | 否（網頁上看得到） |
| log 裡 | 自動遮成 `***` | 原樣印出 |
| 本專案用在 | `AWS_DEPLOY_ROLE_ARN`（Phase 93） | `EC2_WORKER_INSTANCE_ID`（本 phase） |

實例 ID 不是機密（知道了也連不上——SG inbound 全關、要動它得先有 IAM 權限），
而且 CD 的 bash 要拿它組 `aws ssm send-command` 的參數；
**失敗時 log 裡看得到它是什麼**才查得下去（放 secret 的話會被遮成 `***`，
「到底傳了什麼進去」就變成瞎猜）。

> ⚠️ **`vars` 與 `secrets` 是兩個不同的命名空間，寫錯拿到空字串而且不報錯。**
> 這是 §7 陷阱 4。§4.3 的 bash 第一件事就是「值是空的就印 notice 然後 `exit 0`」，
> 就是為了讓這種錯**大聲**一點。

### 4.3 新增 `.github/workflows/deploy.yml`（完整照抄）

```bash
cat > .github/workflows/deploy.yml <<'EOF'
# GitHub Actions：CI（test）在 main 上跑綠之後才跑的 CD（Phase 94、design6.md D16）。
#
# 這個檔跟 test.yml 的關係：
#   test.yml    push 與 PR 都跑；ruff + pytest；**本 phase 一個字都不改**（D16「CI 不動契約」）
#   deploy.yml  只在「test 在 main 上成功」之後跑；build arm64 映像 → 推 ECR → 重啟 EC2 工人
#
# ★ 這裡**沒有任何 AWS 長期金鑰**。憑證是每次執行跟 AWS 現換的（OIDC，Phase 93）：
#   GitHub 簽一張只對這次執行有效的令牌 → AWS 驗過 trust policy 的 sub／aud → 發臨時憑證。
#   角色的 ARN 放在 repo secret AWS_DEPLOY_ROLE_ARN（放 secret 的理由見 phase-93 §4.6）。
#
# 刻意不做（phase-94 §3）：不建 app 映像（app 跑在那台 Mac 上，不上雲）、
# 不跑 pytest／ruff（test 已經跑過了）、不開機也不關機（那是人的決定，D15）、
# 不做 staging／production 兩套環境、不發 Slack 通知、不建 x86 架構的映像。

name: deploy

on:
  # workflow_run ＝「另一個 workflow 跑完之後才觸發我」。
  # ⚠ 三件要知道的事：
  #   1. 這個 workflow 檔**必須存在於預設分支（main）上**才會被觸發（放在別的分支永遠不跑）。
  #      第一次把它推上 main 的那一輪，deploy 可能會跑、也可能不會——GitHub 只保證
  #      「檔案在預設分支上」這個條件。不要拿那一輪當判準，再 push 一次才算數（phase-94 §4.8 步驟 0）。
  #   2. 它**跑在預設分支的上下文**底下——所以 OIDC 令牌的 sub 永遠是
  #      repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main，剛好對上 Phase 93 鎖的那一串。
  #   3. branches: [main] 過濾的是「被觸發的那次 test 跑在哪個分支」。
  #      在別的分支上 push（test 照跑）不會觸發部署。
  #      ⚠ 但 fork 的分支也可以叫 main，而 test 也會被 pull_request 觸發——
  #        所以 job 的 if 還要多認一個 event == 'push'（見下面 jobs.deploy.if）。
  workflow_run:
    workflows: ["test"]
    types: [completed]
    branches: [main]

# 同一時間只准跑一個 deploy。第二次會**排隊等**（不是取消前一次）。
# cancel-in-progress 為什麼是 false：這個 job 有副作用（推映像、重啟遠端服務）。
# 取消在半路的話，可能剛好停在「映像推了一半」或「SSM 送出去了但還沒確認結果」，
# 而下一次執行完全不知道上一次做到哪。排隊等最多多花幾分鐘，但狀態永遠是完整的。
concurrency:
  group: deploy
  cancel-in-progress: false

jobs:
  deploy:
    # 兩個條件缺一不可，任一不符就整個 job 不跑（顯示為 skipped，不是 failed）：
    #   event == 'push'          test 被 pull_request 觸發（含 fork 來的 PR）完成時**不部署**。
    #                            workflow_run 跑在預設分支上下文、拿得到 secret，
    #                            GitHub 官方文件明說要用這個條件擋 fork PR（phase-94 §7 陷阱 8）。
    #   conclusion == 'success'  workflow_run 不管成功失敗都會觸發，test 紅了不准部署。
    if: ${{ github.event.workflow_run.event == 'push' && github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    # QEMU 模擬 arm64 很慢：第一次（沒有快取）5〜15 分鐘。40 分鐘留足餘裕。
    timeout-minutes: 40

    permissions:
      # ★ 沒有這一行，configure-aws-credentials 會拿不到 OIDC 令牌，
      #   錯誤訊息長得像 "Could not assume role ... Unable to get ACTIONS_ID_TOKEN_REQUEST_URL"。
      id-token: write
      # checkout 要用的讀取權。permissions 一旦明寫，沒列到的權限一律變成 none——
      # 所以這一行不能省。
      contents: read

    env:
      AWS_REGION: ap-northeast-1
      ECR_REPOSITORY: personaldocai-worker

    steps:
      # ★ ref 指定成 head_sha，不是預設的「這個分支最新」。
      #   理由：workflow_run 跑在預設分支上下文，不指定的話 checkout 拿到的是
      #   **當下的 main**，可能已經比 CI 測過的那一版新（你在 CI 跑的那幾分鐘裡又 push 了）。
      #   那會變成「部署了一份沒有被測過的程式碼」——CD 綁 CI 的意義就沒了。
      - name: Check out the exact commit that CI tested
        uses: actions/checkout@v7
        with:
          ref: ${{ github.event.workflow_run.head_sha }}

      # 用 OIDC 換一組臨時憑證（最多 1 小時，Phase 93 的 --max-session-duration）。
      # 這一步之後，同一個 job 裡所有的 aws 指令與 ECR 登入都自動帶著那組憑證。
      - name: Configure AWS credentials with OIDC
        uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      # 這一步做三件事：跟 ECR 換一次性密碼、docker login、把 registry 位址
      # 放進 steps.ecr.outputs.registry（長得像 <帳號>.dkr.ecr.ap-northeast-1.amazonaws.com）。
      # ★ 有了這個 output，workflow 裡就**不必寫死帳號 ID**。
      - name: Log in to Amazon ECR
        id: ecr
        uses: aws-actions/amazon-ecr-login@v2

      # runner 的 CPU 是 x86_64；EC2 t4g 是 ARM。QEMU 讓前者模擬後者。
      - name: Set up QEMU (so an x86_64 runner can build for ARM)
        uses: docker/setup-qemu-action@v4

      # buildx ＝ Docker 的多平台建置外掛。沒有它就沒有 platforms 這個選項。
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v4

      - name: Build and push the cloud-worker image
        uses: docker/build-push-action@v7
        with:
          # build context ＝ repo 根目錄（Dockerfile 也在那裡）
          context: .
          # 多階段 Dockerfile 停在中間那一段（Phase 90：base -> cloud-worker -> app）。
          # 不指定 target 的話會蓋出最後一段（app），那是給這台 Mac 用的映像。
          target: cloud-worker
          # EC2 是 t4g（AWS 自研 ARM），所以只建這一種架構。
          platforms: linux/arm64
          push: true
          # 把 commit SHA 烙進映像：Dockerfile 的 ARG GIT_SHA -> ENV WORKER_VERSION，
          # 工人啟動時印在 log 裡。Demo 3 就是靠它證明「跑的是新映像」（D16）。
          build-args: |
            GIT_SHA=${{ github.event.workflow_run.head_sha }}
          # 兩個 tag 指向同一份映像：
          #   <sha>   永遠指向這一版，任何一版都回得去
          #   latest  給 EC2 開機時的 docker pull 用（systemd 的 ExecStartPre）
          # ★ 「跑的是不是新映像」不靠 latest 判斷（D16）——靠工人 log 的 version=<sha>。
          tags: |
            ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPOSITORY }}:${{ github.event.workflow_run.head_sha }}
            ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPOSITORY }}:latest
          # 把 build 的中間層存進 GitHub 的快取空間。QEMU 很慢，有快取差很多
          # （第一次 5〜15 分鐘，之後改一行 Python 大約 2〜4 分鐘）。
          cache-from: type=gha
          cache-to: type=gha,mode=max

      # ★ 這一步是「盡力而為」：EC2 開著就重啟工人，沒開著就印一行提示並成功結束。
      #   design6 D16 明文「EC2 Stop 時 CD 仍可 push ECR；下次 Start 再拉」——
      #   產品負責人的常態是機器關著（D15：卡片 $0、用完就 Stop），
      #   所以「沒開機 = 部署失敗」會讓 Actions 永遠一片紅，紅到沒人看。
      - name: Restart the worker if the instance is running
        env:
          # ⚠ vars 不是 secrets（兩個不同的命名空間）。沒設的話這裡會是空字串而且不報錯，
          #   所以下面第一件事就是檢查它有沒有值。
          EC2_INSTANCE_ID: ${{ vars.EC2_WORKER_INSTANCE_ID }}
        run: |
          set -euo pipefail

          if [ -z "${EC2_INSTANCE_ID:-}" ]; then
            echo "::notice::EC2_WORKER_INSTANCE_ID variable is not set; image pushed, nothing to restart"
            exit 0
          fi

          STATE=$(aws ec2 describe-instances \
            --instance-ids "$EC2_INSTANCE_ID" \
            --query 'Reservations[0].Instances[0].State.Name' \
            --output text)
          echo "instance state: $STATE"

          if [ "$STATE" != "running" ]; then
            echo "::notice::instance not running; image pushed, next Start pulls latest"
            exit 0
          fi

          CMD_ID=$(aws ssm send-command \
            --instance-ids "$EC2_INSTANCE_ID" \
            --document-name AWS-RunShellScript \
            --parameters 'commands=["sudo systemctl restart personaldocai-worker"]' \
            --query Command.CommandId \
            --output text)
          echo "ssm command id: $CMD_ID"

          # 輪詢最多 30 次 x 10 秒 = 5 分鐘。
          # 第一次一定要先 sleep：send-command 剛回來時 invocation 還沒建好，
          # 立刻查會得到 InvocationDoesNotExist（所以下面用 || echo Pending 吞掉）。
          for i in $(seq 1 30); do
            sleep 10
            STATUS=$(aws ssm get-command-invocation \
              --command-id "$CMD_ID" \
              --instance-id "$EC2_INSTANCE_ID" \
              --query Status \
              --output text 2>/dev/null || echo "Pending")
            echo "attempt $i: $STATUS"
            case "$STATUS" in
              Success)
                echo "worker restarted"
                exit 0
                ;;
              Failed|Cancelled|TimedOut)
                echo "::error::SSM command ended as $STATUS"
                aws ssm get-command-invocation \
                  --command-id "$CMD_ID" --instance-id "$EC2_INSTANCE_ID" \
                  --query StandardErrorContent --output text || true
                exit 1
                ;;
            esac
          done

          echo "::error::SSM command did not finish within 5 minutes"
          exit 1
EOF
```

> ⚠️ **AWS CLI 不必自己安裝。** `ubuntu-latest` 的 runner 映像預裝了 AWS CLI v2，
> 所以最後那一步的 `aws` 指令直接就能用。**不要**加 `pip install awscli`
> （那會裝到早就停止支援的 v1，`--query` 的行為還不太一樣）。

- [ ] 檔案寫好了。

### 4.4 本機先驗一次（不必等 GitHub）

```bash
# ① YAML 是不是合法、結構對不對
python3 - <<'PY'
import yaml, pathlib
d = yaml.safe_load(pathlib.Path(".github/workflows/deploy.yml").read_text(encoding="utf-8"))
print("name            =", d["name"])
# ⚠ YAML 1.1 會把沒引號的 on 讀成布林 True——所以這裡要用 True 當 key 去取
觸發 = d.get("on") or d.get(True)
print("workflow_run    =", 觸發["workflow_run"])
print("concurrency     =", d["concurrency"])
job = d["jobs"]["deploy"]
print("if              =", job["if"])
print("permissions     =", job["permissions"])
print("env             =", job["env"])
print("steps           =", [s.get("name") or s.get("uses") for s in job["steps"]])
PY
```

**預期輸出：**

```text
name            = deploy
workflow_run    = {'workflows': ['test'], 'types': ['completed'], 'branches': ['main']}
concurrency     = {'group': 'deploy', 'cancel-in-progress': False}
if              = ${{ github.event.workflow_run.event == 'push' && github.event.workflow_run.conclusion == 'success' }}
permissions     = {'id-token': 'write', 'contents': 'read'}
env             = {'AWS_REGION': 'ap-northeast-1', 'ECR_REPOSITORY': 'personaldocai-worker'}
steps           = ['Check out the exact commit that CI tested', 'Configure AWS credentials with OIDC', 'Log in to Amazon ECR', 'Set up QEMU (so an x86_64 runner can build for ARM)', 'Set up Docker Buildx', 'Build and push the cloud-worker image', 'Restart the worker if the instance is running']
```

> ⚠️ **`yaml` 這個套件是間接依賴。** `requirements.txt` 裡**沒有** `PyYAML`——
> 它是 `langchain-core` 帶進來的（本機 `.venv` 實測有 6.0.3）。
> 上面這段只是**人在本機做的一次性檢查**，不是自動化測試。
> **§4.5 的 6 顆掃碼測試一律用 regex 讀文字，不 `import yaml`**——
> 測試不可以依賴一個沒有寫進 `requirements.txt` 的東西
> （哪天 langchain 換掉它，CI 就會在一個「什麼都沒改」的 commit 上突然變紅）。

```bash
# ② 沒有樣板注入面：這份 workflow 不吃任何外部可控的輸入
#    ⚠ -F（固定字串比對）不能省：macOS 的 BSD grep 把開頭的 $ 當「行尾」錨點，
#      沒有 -F 會**什麼都印不出來**，看起來像「一處都沒有」（實測：不加 -F 印 0 行、加了印 8 行）
grep -nF '${{' .github/workflows/deploy.yml
```

**預期輸出：恰好 8 行，而且只有這七種來源**（`secrets.` / `vars.` / `env.` / `steps.ecr.outputs.` /
`github.event.workflow_run.event` / `…workflow_run.conclusion` / `…workflow_run.head_sha`）。
**不可以**出現 `github.event.*.title`、`github.head_ref`、`github.event.*.body`
這類「使用者打得出來的字串」——那些直接插進 `run:` 會變成指令注入。

```bash
# ③ 沒有任何長期金鑰的字樣
grep -niE 'access_key|secret_access|session_token' .github/workflows/deploy.yml
# 預期：完全沒有輸出

# ④ CI 那份真的沒被動到（D16）
git diff --stat -- .github/workflows/test.yml
# 預期：完全沒有輸出
```

- [ ] 四項都符合預期。

### 4.5 TDD：6 顆掃碼測試（先看到紅，再看到綠）

> 📌 這 6 顆追加在 **Phase 90 開的**那個檔 `tests/integration/test_design6_error_paths.py`
> 的最後面（Phase 93 那 4 顆的後面）。**不要新開檔**。
>
> 📌 **一律用 regex 讀文字，不 `import yaml`。** 理由在 §4.4 的警告框：
> `PyYAML` 不在 `requirements.txt` 裡（是 `langchain-core` 帶進來的間接依賴），
> 測試依賴它等於埋一顆「哪天上游換掉就在無關的 commit 上突然紅」的雷。

**① 先跑一次，記下現在幾顆：**

```bash
pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：8 tests collected（Phase 90 的 4 ＋ Phase 93 的 4）
```

**② 把下面這一整段追加到檔案最後面（照抄）：**

```python
# ---------------------------------------------------------------------------
# Phase 94：CD 工作流程（design6 D16、§12 Demo 3）
#
# 這六顆掃的是 .github/workflows/deploy.yml。掃它而不是「跑它」的理由很實際：
# 一次真的 CD 要 5〜15 分鐘、要 AWS 憑證、還會真的推映像到 ECR——
# 那是 §4.8 的 Demo 3（人工做一次）該做的事，不是每次 pytest 都該做的事。
# 這六顆守的是「**設定沒有被改壞**」，而設定改壞了的症狀全部是安靜的：
#   platforms 被改成別的架構 -> 映像推上去了，EC2 卻拉下來跑不動（exec format error）
#   target 掉了              -> 推上去的是 app 映像（uvicorn），工人永遠不會啟動
#   tag 沒有 sha             -> 只剩會動的 latest，永遠回不去上一版、也證明不了跑的是新的
#   workflows 綁錯名字       -> CD 從此不再被觸發，而且**不會有任何錯誤訊息**
#
# ⚠ 一律 regex 讀文字，不 import yaml：PyYAML 不在 requirements.txt 裡
#   （它是 langchain-core 的間接依賴）。測試不可以依賴沒有寫進 requirements 的東西。
# ---------------------------------------------------------------------------

工作流程目錄 = 專案根目錄 / ".github" / "workflows"


def deploy工作流程() -> str:
    """讀 .github/workflows/deploy.yml 的原始文字。"""
    return (工作流程目錄 / "deploy.yml").read_text(encoding="utf-8")


def test_CD綁在test工作流程成功之後():
    """D16：CI 綠了才部署。三件事一起釘（少一件就會出現不同的壞法）。

    1. workflows: ["test"]  -> 綁的是既有 CI 的 name。打錯字的話 CD 從此**永遠不觸發**，
       而且 GitHub **不會**給任何錯誤訊息（它只是找不到符合的事件）。
    2. branches: [main]     -> 只有 main 上跑成功的 CI 才觸發部署。
    3. conclusion == 'success' -> workflow_run 不管 CI 成功失敗都會觸發，
       所以 job 層的 if 是**唯一**的守門。少了它，CI 紅的那一版照樣被部署。
    4. event == 'push'         -> test 也會被 pull_request 觸發（含 fork 來的 PR），而
       workflow_run 跑在預設分支上下文、拿得到 secret；GitHub 官方文件明說要用這個條件擋。
    """
    原文 = deploy工作流程()

    assert re.search(r"^name:\s*deploy\s*$", 原文, re.M), "workflow 的 name 必須是 deploy"
    assert re.search(r'workflows:\s*\[\s*"?test"?\s*\]', 原文), (
        "workflow_run 必須綁既有 CI 的 name（test）——名字打錯的話 CD 會安靜地永遠不觸發"
    )
    assert re.search(r"branches:\s*\[\s*main\s*\]", 原文), (
        "只有 main 上跑成功的 CI 才觸發部署（總覽 §10 追認項 b：分支是 main 不是 master）"
    )
    assert re.search(r"workflow_run\.conclusion\s*==\s*'success'", 原文), (
        "workflow_run 不管成功失敗都會觸發，job 的 if 是唯一的守門"
    )
    assert re.search(r"workflow_run\.event\s*==\s*'push'", 原文), (
        "只有 push 觸發的 test 才部署——PR（含 fork）觸發的 test 完成時不准拿 secret 去推映像"
    )


def test_CD要求id_token寫入權限():
    """沒有 id-token: write 就拿不到 OIDC 令牌，整套 Phase 93 都用不上。

    症狀很難聯想：configure-aws-credentials 會失敗在
    "Unable to get ACTIONS_ID_TOKEN_REQUEST_URL"——看起來像 AWS 的問題，
    其實是 GitHub 這邊沒開權限。

    順便釘 contents: read：permissions 一旦明寫，沒列到的權限**一律變成 none**，
    漏了它 actions/checkout 會拿不到程式碼。
    """
    原文 = deploy工作流程()

    assert re.search(r"id-token:\s*write", 原文), "沒有 id-token: write 就拿不到 OIDC 令牌"
    assert re.search(r"contents:\s*read", 原文), (
        "明寫 permissions 之後，checkout 需要的讀取權要補上"
    )


def test_CD只建linux_arm64的映像():
    """D15：EC2 是 t4g.small（AWS 自研 ARM）。架構錯了的症狀是安靜的。

    推上去的是 x86 映像的話，CD 一路綠燈，EC2 拉下來 docker run 才炸
    "exec format error"——而那個訊息出現在**遠端機器的 systemd log 裡**，
    不在 Actions 頁面上，所以你會以為部署成功了。
    """
    原文 = deploy工作流程()

    平台 = re.findall(r"^\s*platforms:\s*(\S+)\s*$", 原文, re.M)
    assert 平台 == ["linux/arm64"], f"只能建 linux/arm64 這一種架構，現在是 {平台}"
    assert "linux/amd64" not in 原文, (
        "不建 x86 架構的映像：EC2 是 ARM，多建一份只是讓 QEMU build 時間翻倍"
    )


def test_CD打的是cloud_worker這個target():
    """Phase 90 的 Dockerfile 是 base -> cloud-worker -> app（app 刻意放最後）。

    不指定 target 的話，docker build 會停在**最後一段**＝ app 映像（跑 uvicorn 的那個）。
    推上去之後 EC2 會啟動一個 uvicorn，SQS 訊息永遠沒人收——
    而且 systemd 顯示服務「running」，看起來一切正常。
    """
    原文 = deploy工作流程()

    assert re.search(r"^\s*target:\s*cloud-worker\s*$", 原文, re.M), (
        "target 必須是 cloud-worker；不指定會蓋出最後一段（app）的映像"
    )


def test_CD的tag含commit的sha():
    """總覽 §10 追認項 e：同時推 <sha> 與 latest，但驗證不靠 latest（D16）。

    只有 latest 的話：
      - 回不去上一版（latest 永遠指向最後推的那一份）
      - 證明不了「EC2 上跑的是新映像」（拉 latest 永遠「是最新的」）
    所以 <sha> 那個 tag 是必要的，而且它必須是 workflow_run 帶的 head_sha
    （＝ CI 實際測過的那一版），不是 github.sha（見 §7 陷阱 2）。
    """
    原文 = deploy工作流程()

    比對 = re.search(r"^([ ]*)tags:[ ]*\|[ ]*\n((?:\1[ ]+\S.*\n)+)", 原文, re.M)
    assert 比對, "找不到 tags: | 區塊"
    tag行 = [行.strip() for 行 in 比對.group(2).splitlines() if 行.strip()]

    assert len(tag行) == 2, f"應該恰好兩個 tag（<sha> 與 latest），現在是 {tag行}"
    assert any("github.event.workflow_run.head_sha" in 行 for 行 in tag行), (
        "其中一個 tag 必須是 CI 測過的那個 commit 的 sha（head_sha，不是 github.sha）"
    )
    assert any(行.endswith(":latest") for 行 in tag行), (
        "另一個 tag 是 latest，給 EC2 開機時的 docker pull 用（systemd 的 ExecStartPre）"
    )


def test_CD沒有寫死任何AWS金鑰():
    """design6 §6「機密不進文件」＋ Phase 93 的整個 OIDC 就是為了不必放金鑰。

    ⚠ 這一顆會**掃到 deploy.yml 的註解**。所以寫註解解釋「這裡不放金鑰」時，
      不可以把那兩個環境變數的名字打出來——要寫成「長期金鑰」「access key」這種說法。
      （這不是龜毛：一顆會被自己的註解弄紅的測試，遲早會被人改成不掃註解，
        那時它就真的守不住任何東西了。）
    """
    原文 = deploy工作流程()

    for 關鍵字 in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "aws-access-key-id",
        "aws-secret-access-key",
    ):
        assert 關鍵字 not in 原文, f"CD 不可以出現任何長期金鑰的設定：{關鍵字}"

    # 防呆錨點：確認它真的走 OIDC（不是把整段刪光所以「沒有金鑰」）
    assert "secrets.AWS_DEPLOY_ROLE_ARN" in 原文, "CD 必須用 Phase 93 的角色 ARN 換臨時憑證（OIDC）"
    assert re.search(r"aws-actions/configure-aws-credentials@v\d+", 原文)
```

**③ 先看到紅（TDD 的關鍵一步，不可以跳過）：**

```bash
# 故意把架構改錯、target 拿掉，看兩顆會不會紅
python3 - <<'PY'
import pathlib
p = pathlib.Path(".github/workflows/deploy.yml")
t = p.read_text(encoding="utf-8")
t = t.replace("platforms: linux/arm64", "platforms: linux/amd64")
t = t.replace("          target: cloud-worker\n", "")
p.write_text(t, encoding="utf-8")
PY

pytest tests/integration/test_design6_error_paths.py -k "CD只建linux_arm64 or CD打的是cloud_worker" -q
```

（`-k` 的字串要挑本 phase **獨有**的片段：寫 `cloud_worker這個target` 會把 Phase 90 的
`test_Dockerfile有cloud_worker這個target` 一起選進來——那顆是綠的，畫面會變成 `2 failed, 1 passed`，
看起來像少紅了一顆。）

**預期：`2 failed, 4 deselected`**，訊息長相：

```text
FAILED …::test_CD只建linux_arm64的映像 - AssertionError: 只能建 linux/arm64 這一種架構，現在是 ['linux/amd64']
FAILED …::test_CD打的是cloud_worker這個target - AssertionError: target 必須是 cloud-worker；…
```

```bash
# 再故意把 workflows 綁錯名字、拿掉 head_sha 那個 tag
python3 - <<'PY'
import pathlib
p = pathlib.Path(".github/workflows/deploy.yml")
t = p.read_text(encoding="utf-8")
t = t.replace('workflows: ["test"]', 'workflows: ["ci"]')
t = t.replace(
    "            ${{ steps.ecr.outputs.registry }}/${{ env.ECR_REPOSITORY }}:"
    "${{ github.event.workflow_run.head_sha }}\n", "")
p.write_text(t, encoding="utf-8")
PY

pytest tests/integration/test_design6_error_paths.py -k "CD綁在test or CD的tag含commit" -q
```

**預期：`2 failed, 4 deselected`**（一顆說「必須綁既有 CI 的 name」、一顆說「應該恰好兩個 tag…現在是 [...]」）。

- [ ] **四次紅都親眼看過了**（分兩輪，每輪兩顆）。
      **沒看過紅的測試，你不知道它有沒有在測東西。**

```bash
# 全部還原：重跑 §4.3 的整段 heredoc（它是整檔覆寫）
```

**④ 還原之後跑綠：**

```bash
pytest tests/integration/test_design6_error_paths.py -v
# 預期：14 passed（Phase 90 的 4 ＋ Phase 93 的 4 ＋ 本 phase 的 6）
```

### 4.6 全量回歸

```bash
# 1) 全量：預期 672 passed ＋ 0 skipped（開工基線 666 ＋ 6）
pytest -q

# 2) 零依賴實證（三個死埠一起指，顆數必須完全相同）
#    本 phase 的 6 顆只讀本機檔案，本來就不連網
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q

# 3) 端點仍是 22、零 DELETE
python3 - <<'EOPY'
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    paths = c.get("/openapi.json").json()["paths"]
    運算元 = [(p, m) for p, item in paths.items() for m in item]
    print("端點數 =", len(運算元), "/ DELETE 數 =", sum(1 for _, m in 運算元 if m == "delete"))
EOPY
# 預期：端點數 = 22 / DELETE 數 = 0

# 4) 格式與 lint（CI 跑的那兩句）
ruff format --check app tests scripts && ruff check app tests scripts

# 5) 該零改動的：CI 契約（D16）、規格區、產品碼、compose、Dockerfile
git diff --stat -- .github/workflows/test.yml    # 預期：無輸出
git status --short docs/spec/                    # 預期：無輸出
git status --short -- app/ compose.yaml Dockerfile db/ requirements.txt
# 預期：與開工前完全相同（Demo 3 那一行註解是 §4.8 才加的，這裡還不該有）

# 6) 本 phase 到底多了哪些檔
git status --short -- .github/ tests/ README.md
# 預期：?? .github/workflows/deploy.yml
#        M tests/integration/test_design6_error_paths.py
#        M README.md
```

- [ ] 六項全部符合預期。

### 4.7 `README.md` §9 加一小段 "CI/CD"（**英文**）

`README.md` 與 `LAUNCH.md` 自 2026-08-27 起是**英文**（總覽 §3.8）。
在 §9 "Development and testing" 的 **"Code style"** 小節之後、
**"Project layout"** 小節之前，插入下面這一整段：

````markdown
### CI/CD

Two GitHub Actions workflows, deliberately separate:

| Workflow | Trigger | What it does |
|---|---|---|
| `test` (`.github/workflows/test.yml`) | every push and pull request | `ruff format --check` -> `ruff check` -> load `db/schema.sql` -> `pytest -q`, against a throwaway pgvector container. No Redis, no Celery worker, no Ollama, no `.env` — the autouse safety nets in `tests/conftest.py` already remove every external dependency. |
| `deploy` (`.github/workflows/deploy.yml`) | `test` finishing **successfully on `main`** | builds the `cloud-worker` stage of the Dockerfile for `linux/arm64` (QEMU + Buildx), pushes it to ECR under two tags (`<commit sha>` and `latest`), then restarts the EC2 worker over SSM Run Command — **only if that instance happens to be running**. |

The deploy workflow holds **no long-lived AWS credentials**. It asks GitHub for a
short-lived OIDC token and exchanges it for temporary AWS credentials; the IAM role's trust
policy pins the token's subject to exactly
`repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`, so no other branch, tag or pull request
can borrow it, and the deploy job itself only runs for `push`-triggered CI runs, never for pull
requests. Only the role ARN is stored, as the repository secret `AWS_DEPLOY_ROLE_ARN`.

**A stopped instance is not a failed deploy.** The EC2 worker is normally shut down (it is
started only for a demo and stopped straight after), so when the instance is not running the
job logs a notice and finishes green: the image is already in ECR, and the next boot pulls it.
Whether the machine is actually running the new image is verified from the worker's own
startup line — `cloud_worker 啟動 version=<sha> …` — never from the `latest` tag, which by
definition always looks current.

The first build takes 5–15 minutes because an x86_64 runner has to emulate ARM; later builds
reuse the GitHub Actions build cache and take about 2–4 minutes.
````

- [ ] 貼進去了，位置對（在 "Code style" 與 "Project layout" 之間）。
- [ ] **英文**，而且沒有寫出任何帳號 ID、實例 ID、role ARN 的真值。

### 4.8 Demo 3（人工；design6 §12 原文）

> design6 §12 原文：**「改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA →
> Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）。」**

> ⚠️ **這一段會真的開機、真的花點數。** 全程大約 20〜35 分鐘（大部分是等 QEMU build）。
> **做完一定要 Stop**（第 6 步）。忘了就在燒點數（D15）。

#### 步驟 0：先 commit 並 push 一次「沒有改工人」的版本

**為什麼要多這一趟：** `workflow_run` 有一個規定——**這個 workflow 檔必須存在於
預設分支（`main`）上，才會被觸發**。第一次把 `deploy.yml` 推上去的那一輪，deploy
**可能會跑、也可能不會**（GitHub 只保證「檔案在預設分支上」這個條件，沒有保證同一輪就算數）。
所以這一輪**不拿來當判準**：它只負責把 `deploy.yml` 送上 `main`；步驟 2 那一輪才是 Demo。
（要是這一輪 deploy 真的跑了：它 build 的是同一個 commit，推上去的映像沒有壞處，讓它跑完就好。）

```bash
git add .github/workflows/deploy.yml tests/integration/test_design6_error_paths.py README.md
git commit -m "$(cat <<'EOF'
ci: CD 工作流程（test 綠 → OIDC → arm64 → ECR → SSM）

workflow_run 綁既有的 test（branches: main、conclusion==success）；
OIDC 換臨時憑證（零長期金鑰）；QEMU+buildx 建 linux/arm64 的 cloud-worker
階段，推 ECR 的 <head_sha> 與 latest 兩個 tag；只有實例是 running 才
SSM 重啟，stopped 時印 notice 並成功結束（D16）。
test_design6_error_paths.py +6（666 → 672）。
EOF
)"
git push origin main
```

```bash
gh run watch
```

- [ ] **預期：`test` 綠了。** Actions 頁面上這一輪**可能有、也可能沒有** `deploy`——兩種都正常
      （檔案是這一輪才上 `main` 的；有跑的話它 build 的是同一個 commit，等它跑完即可）。

#### 步驟 1：改 worker 一點點——在 `cloud_worker.py` 加一行註解

design6 §12 要的是「改 worker 一點點」。改**什麼**不重要，重要的是產生一個**新的 commit**：
判準是第 5 步 EC2 上印出的 `version=<sha>` **逐字等於**這個新 commit 的完整 sha——
sha 是 build 當下烙進映像的，40 個十六進位字元，造不了假、也撞不了。

**為什麼不改啟動 log 的字**（總覽 §5.4 那句「改工人的啟動 log 一行字」請當作「改一點點」的舉例）：
Phase 88 的 `test_啟動時印出version與region與bucket` 用 `startswith("cloud_worker 啟動 ")` 釘住了那一行，
而 `README.md`／`LAUNCH.md`／phase-92 的手冊都逐字引用 `cloud_worker 啟動 version=…`。
改一個字＝要改測試，還讓三份文件從此對不上程式碼（產品負責人的鐵律：不留過渡產物）。
加一行註解則是零測試改動、零文件漂移。

```bash
# 先看一眼啟動 log 在哪一行（只是找位置，**不改它**）
grep -n "cloud_worker 啟動" app/workers/cloud_worker.py

# 在檔案最後面加一行註解（>> 是「附加到檔尾」，不會動到既有內容）
printf '\n# Demo 3（Phase 94）：這一行只為了產生一個新 commit，證明 CD 會把新映像送上 EC2。\n' \
  >> app/workers/cloud_worker.py

# 讓 formatter 自己把註解前面的空行數對好（def 後面要兩行；這就是 pre-commit hook 會做的事）
ruff format app/workers/cloud_worker.py          # 預期：1 file reformatted 或 1 file left unchanged，都對

git diff --stat app/workers/cloud_worker.py     # 預期：1 file changed, 2 insertions(+)（一行空行＋一行註解；ruff 若多補一行空行就是 3，也對）
ruff format --check app && ruff check app        # 預期：兩句都 exit 0
pytest tests/unit/test_cloud_worker_unit.py -q  # 預期：全綠——註解不改任何行為
```

- [ ] 三個預期都符合。**不要**動 `logger.info("cloud_worker 啟動 version=…")` 那一行。

#### 步驟 2：commit、push、記下 sha

```bash
git add app/workers/cloud_worker.py
git commit -m "chore: cloud_worker 加一行註解（Demo 3 用，產生新 commit）"
git push origin main

SHA=$(git rev-parse HEAD)          # 完整 40 碼——CD 的 tag 用的就是完整 sha
SHORT=$(git rev-parse --short HEAD)
echo "SHA=$SHA"
echo "SHORT=$SHORT"
```

- [ ] 記下 `SHA`（下一步要拿它去 ECR 比對）。

#### 步驟 3：看兩個 workflow 依序跑

```bash
gh run watch
```

**預期：先看到 `test` 跑（1〜3 分鐘）綠了之後**，Actions 頁面上才會出現 `deploy`。
`gh run watch` 只盯**一次**執行，`test` 結束它就退出了；`deploy` 出現後**再打一次** `gh run watch`
（它會列出正在跑的執行讓你選；或 `gh run list --workflow deploy --limit 1` 拿 run id 再 `gh run watch <id>`）。

```text
https://github.com/1104030360/personalDocAI/actions
```

- [ ] `test` ✓
- [ ] `deploy` 出現了，而且七個 step 依序綠：
      checkout → configure AWS credentials → ECR login → QEMU → Buildx →
      build and push → restart the worker

> ⏱ **`Build and push` 那一步第一次要 5〜15 分鐘。**
> 原因：GitHub 的 runner 是 x86_64，要用 QEMU 模擬 ARM 才跑得動 `pip install`
> 那一層裡的每一個指令。**這不是壞掉，是慢。**
> 之後的 build 會吃 `cache-from: type=gha` 的快取，大約 2〜4 分鐘。
> 想確認它真的在動：點進那一步看 log，會一直有 `#N [linux/arm64 …]` 的輸出。

- [ ] 最後一步 `Restart the worker if the instance is running` 的 log：

```text
instance state: stopped
```

  然後 job **綠色結束**，摘要頁上有一則藍色的 notice：

```text
instance not running; image pushed, next Start pulls latest
```

  **這就是 D16「EC2 Stop 時 CD 仍可 push ECR」的那一條**，也是 design6 §12 括號裡
  「（Stop 時至少 ECR 已更新）」的長相。

#### 步驟 4：ECR 上要看得到這個 sha

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ 讓 aws 指令回去用 personaldocai-admin 的 default profile（Phase 82）
AWS_REGION=${AWS_REGION:-ap-northeast-1}

aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
  --query 'imageDetails[?imageTags].imageTags[]' --output json
```

**預期輸出長相**（一個攤平的 tag 陣列：你的完整 `SHA`、`latest`，加上 Phase 91 手動推的那個短 sha）：

```json
[
    "latest",
    "3f9c1ab2c4d5e6f708192a3b4c5d6e7f80912a3b",
    "a53ab57"
]
```

```bash
echo "$SHA"        # 拿來跟上面的輸出逐字比對

# 再確認「latest 指到的就是這一份」：只查 latest 那張映像身上掛的所有 tag
aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
  --image-ids imageTag=latest --query 'imageDetails[0].imageTags' --output json
# 預期：["latest", "<你的 SHA>"]（順序不拘）——latest 與 <sha> 掛在同一份映像上
```

- [ ] **`SHA` 出現在 tag 清單裡，而且 `latest` 那張映像的 tag 清單裡也有它**（＝同一份映像掛兩個 tag）。

```bash
# 順便確認它真的是 arm64（架構錯了 EC2 拉下來會 exec format error）
aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
  --image-ids imageTag=latest \
  --query 'imageDetails[0].imageManifestMediaType' --output text
```

**預期：** `application/vnd.oci.image.index.v1+json`（或 `…docker.distribution.manifest.list.v2+json`）
——buildx 推的是「多平台索引」格式，即使只有一個平台。
真的要看架構：在 EC2 上用 SSM 跑 `docker image inspect --format '{{.Architecture}}' "$(docker ps --filter name=cloud-worker --format '{{.Image}}')"`，預期 `arm64`（其實跑得起來就已經證明是 arm64——架構錯會 `exec format error`）。

#### 步驟 5：Start 之後確認跑的是新映像

```bash
aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

⚠️ **`instance-running` 只代表「機器開了」，不代表「systemd 服務起來了」。**
開機之後 user-data／systemd 要拉 `latest` 映像（幾十秒到兩分鐘），
所以下一步要**等一下再問**。SSM agent 也要幾十秒才上線：`send-command` 若回 `InvalidInstanceId`，
不是 ID 打錯，是 agent 還沒註冊——再等 30 秒重送一次即可（§7 陷阱 11）：

```bash
sleep 90

CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker logs cloud-worker 2>&1 | head -n 5"]' \
  --query 'Command.CommandId' --output text)

sleep 10
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
  --query 'StandardOutputContent' --output text
```

**預期輸出（第一行就是判準）：**

```text
cloud_worker 啟動 version=3f9c1ab2c4d5e6f708192a3b4c5d6e7f80912a3b region=ap-northeast-1 bucket=…
```

- [ ] **`version=` 後面逐字等於你的 `SHA`**（40 碼一個字都不差）——跑的真的是 CD 剛推的那一份。
      這一個判準就夠了：sha 是 build 當下烙進映像的，舊映像不可能印出新 commit 的 sha。

**這一步就是 D16「不靠 `latest` 當唯一 tag」的落地。**
`latest` 永遠「是最新的」，看它證明不了任何事；`version=<sha>` 是映像 build 當下
用 `--build-arg GIT_SHA` 烙進去的，改不掉、也造不了假。

**如果 `version=` 還是舊的：** 多半是 systemd 還沒重啟過（開機時 `ExecStartPre` 才 `docker pull`）。
手動叫它重來一次：

```bash
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl restart personaldocai-worker"]' \
  --query 'Command.CommandId' --output text)
sleep 60
# 再跑一次上面那個 docker logs
```

#### 步驟 6：（可選）機器開著時再 push 一次，看 SSM 那一步真的動

如果想把「CD 自動重啟」也親眼看過（design6 §12 的「Start 後 SSM 跑的是新 image」），
**趁機器還開著**再改一個字 push 一次：

```bash
printf '# Demo 3 第二輪（Phase 94）：機器開著時再推一次，看 CD 的 SSM 重啟那一步真的動。\n' \
  >> app/workers/cloud_worker.py
ruff format app/workers/cloud_worker.py && ruff format --check app && ruff check app   # 預期：exit 0
git add app/workers/cloud_worker.py && git commit -m "chore: cloud_worker 再加一行註解（Demo 3 第二輪）"
git push origin main
gh run watch
```

- [ ] `deploy` 最後一步的 log 這次是：

```text
instance state: running
ssm command id: 12345678-…
attempt 1: InProgress
attempt 2: Success
worker restarted
```

- [ ] 再跑一次步驟 5 的 `docker logs`，`version=` 換成第二輪那個新的 sha（`git rev-parse HEAD`）。

#### 步驟 7：**Stop**（每一次都要）

```bash
aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
```

**預期：`stopped`**

- [ ] **確認是 `stopped` 才算做完這一段。**
      **Stop ＝ 關機**（硬碟留著，開回來東西還在，只有 EBS 繼續小額從點數扣）；
      **Terminate ＝ 銷毀**（整台連硬碟一起消失，不可逆）。**本專案一律 Stop。**

**費用影響（Demo 3 一輪）：**

| 項目 | 大約 |
|---|---|
| EC2 `t4g.small` 開機 30 分鐘 | 點數約 1 美分（東京 on-demand 約 $0.0216／小時）；**忘了 Stop 才是問題**（一整個月約 $16 的量級，會把 $100〜200 的點數啃掉一成上下）。Phase 82 建的 Budget `personaldocai-budget` 在實際／預測花費到 80% 時會寄信，那是最後一道提醒 |
| ECR 儲存 | 兩份小映像（幾百 MB），點數以「GB-月」計，可忽略 |
| GitHub Actions | public repo 免費；private repo 吃免費額度（每月 2000 分鐘），一輪 CD 約 5〜15 分鐘 |
| S3／SQS | **這一段完全沒碰**（Demo 3 不上傳照片） |

**做錯了怎麼退回：**

| 出錯情況 | 怎麼救 |
|---|---|
| push 上去了才發現 `deploy.yml` 寫錯 | 改好再 push 一次就好。CD 沒有「回滾」的概念——**每次 push 都是全新的一輪**，上一輪推的映像還留在 ECR（tag 是它自己的 sha） |
| 推了一個壞掉的映像上去，EC2 拉了跑不動 | 先止血：SSM 跑 `sudo systemctl stop personaldocai-worker` 然後 **Stop 機器**——工人停了，所有上傳自動 fallback 本機（D10），使用者無感。再治本：`git revert <壞掉的 commit>` → push → CD 自動把 revert 後的版本建出來推成 `latest`，下次 Start 就拉到好的。（不要手動在 EC2 上 `docker run` 舊 sha：systemd 的 `ExecStartPre` 只認 `latest`，重開機又會拉回壞的那份） |
| Demo 做到一半 Actions 額度用完 | 等下個月，或把 repo 改成 public（本專案沒有機密進版控，但這是**產品負責人的決定**，實作者不要自己改） |
| 改壞了 `cloud_worker.py` | `git revert <那個 commit>` 再 push；CD 會自動把「revert 後的版本」建出來推上去 |

### 4.9 收尾與 commit

Demo 3 之後 `cloud_worker.py` 會多一兩行註解（步驟 1／6）。
那些是**刻意留下的**（`git log` 裡它們就是 Demo 3 的證據），不必還原。

```bash
git status --short
# 預期：乾淨（步驟 0／2／6 都已經 commit 並 push 過了）

pytest -q
# 預期：672 passed ＋ 0 skipped

git log --oneline -3
# 預期（由新到舊）：
#   chore: cloud_worker 再加一行註解（Demo 3 第二輪）              ← 步驟 6，可選
#   chore: cloud_worker 加一行註解（Demo 3 用，產生新 commit）      ← 步驟 2
#   ci: CD 工作流程（test 綠 → OIDC → arm64 → ECR → SSM）    ← 步驟 0
```

> ⚠️ **不要自己把 `unfinish/` 搬進 `finish/`。** 歸檔隨 commit 執行，
> 時機由產品負責人決定（總覽 §7 鐵律 12；Phase 95 §4.9 才處理整批歸檔）。
>
> ⚠️ **本 phase 是本增量唯一「必須 push」的 phase**——`workflow_run` 沒有本機模擬，
> 不 push 就驗不到。這一點與總覽 §7 鐵律 12「commit 節奏由產品負責人決定」並不衝突：
> 步驟 0／2／6 的 push 是 **Demo 3 的一部分**（design6 §12 明列的驗收動作），
> 產品負責人核准跑 Demo 3 ＝ 核准這幾次 push。**其他 phase 仍然不要自己 commit。**

---

## 5. ASCII 圖

### 5.1 一次 `git push` 的完整時序（誰在什麼時候做什麼）

```text
  你的 Mac                GitHub                        AWS                    EC2 t4g.small
  ────────                ──────                        ───                    ─────────────
  git push origin main
        │
        ├──────────────►  workflow「test」
        │                 ruff format --check
        │                 ruff check
        │                 psql -f db/schema.sql
        │                 pytest -q  (672)
        │                       │
        │                       │ conclusion = success
        │                       │ head_sha   = 3f9c1ab…      ← CI 實際測過的那一版
        │                       ▼
        │                 workflow_run 事件觸發「deploy」
        │                 （跑在**預設分支 main** 的上下文）
        │                       │
        │                       ├─ if event=='push' && conclusion=='success' ?  否 → job skipped
        │                       │
        │                       ├─ checkout  ref = head_sha      ← 不是 main 最新
        │                       │
        │                       ├─ 跟 GitHub 要 OIDC 令牌
        │                       │    需要 permissions: id-token: write
        │                       │    sub = repo:1104030360@92135456/personalDocAI@1349196211
        │                       │          :ref:refs/heads/main
        │                       │         │
        │                       │         └────────────►  STS
        │                       │                         驗 trust 的兩個 StringEquals
        │                       │         ◄────────────   臨時憑證（≤1 小時）
        │                       │
        │                       ├─ amazon-ecr-login ────►  ECR：換一次性密碼、docker login
        │                       │    outputs.registry ＝ <帳號>.dkr.ecr.…amazonaws.com
        │                       │
        │                       ├─ QEMU ＋ Buildx（runner 是 x86_64，要模擬 ARM）
        │                       │
        │                       ├─ build --target cloud-worker --platform linux/arm64
        │                       │    --build-arg GIT_SHA=3f9c1ab…    5〜15 分鐘（第一次）
        │                       │         │
        │                       │         └────────────►  ECR
        │                       │                          tag: 3f9c1ab…
        │                       │                          tag: latest        （同一份映像）
        │                       │
        │                       └─ aws ec2 describe-instances ──►  state?
        │                             │
        │                             ├─ stopped ──► echo ::notice:: ＋ exit 0   ✅ job 綠
        │                             │              （D16：Stop 時 CD 仍可 push）
        │                             │
        │                             └─ running ──► aws ssm send-command ─────────────────►
        │                                             AWS-RunShellScript                  │
        │                                             "systemctl restart …"               ▼
        │                                             │                    systemd 重啟服務
        │                                             │                    ExecStartPre:
        │                                             │                      ecr get-login-password
        │                                             │                      docker pull …:latest
        │                                             │                    ExecStart:
        │                                             │                      docker run cloud-worker
        │                                             │                        │
        │                                             │                        └─ log:
        │                                             │                           cloud_worker 啟動
        │                                             │                           version=3f9c1ab…
        │                                             ├─ 輪詢 get-command-invocation
        │                                             └─ Success → job 綠 ✅

  ★ 全程沒有任何 AWS 長期金鑰經過 GitHub。憑證是每次執行現換的、最多活 1 小時。
  ★ 「跑的是不是新映像」的判準是最下面那行 version=<sha>，不是 latest 這個 tag（D16）。
```

### 5.2 6 顆掃碼測試各自守住哪一種安靜的壞法

```text
  deploy.yml 的哪一格          改壞了會怎樣（全部沒有錯誤訊息）        誰守著
  ───────────────────────      ─────────────────────────────────      ──────────────────────
  workflows: ["test"]          CD 從此**永遠不觸發**，Actions 頁面     test_CD綁在test工作
  branches: [main]             上安安靜靜什麼都沒有                    流程成功之後
  conclusion == 'success'      CI 紅的那一版照樣被部署
  event == 'push'              fork 的 PR 讓 test 跑完 → deploy 拿著 secret 去推映像

  permissions: id-token: write 換憑證那一步失敗，訊息看起來像 AWS 的    test_CD要求id_token
                               問題（其實是 GitHub 沒開權限）           寫入權限

  platforms: linux/arm64       CD 一路綠燈；EC2 拉下來 docker run       test_CD只建linux_
                               才炸 exec format error——而那個訊息      arm64的映像
                               在遠端的 systemd log 裡，不在 Actions

  target: cloud-worker         推上去的是 app 映像（uvicorn）；         test_CD打的是cloud_
                               EC2 起了一個 web server，SQS 訊息        worker這個target
                               永遠沒人收，而 systemd 顯示 running

  tags: <sha> ＋ latest        只剩會動的 latest：回不去上一版，        test_CD的tag含
                               也證明不了「跑的是新映像」                commit的sha

  （沒有長期金鑰）              有人為了「先跑起來再說」貼了一組         test_CD沒有寫死
                               access key 進去，而且它永遠有效           任何AWS金鑰
```

---

## 6. 驗收清單

- [ ] **`deploy.yml` 的結構正確**（§4.4 ① 的 YAML 解析輸出七個欄位都對得上）；
      **沒有樣板注入面、沒有長期金鑰、CI 契約零改動**

  ```bash
  grep -nF '${{' .github/workflows/deploy.yml     # -F 不能省（macOS grep 把開頭的 $ 當錨點）
  # 預期：恰好 8 行，來源只有 secrets. / vars. / env. / steps.ecr.outputs. /
  #       github.event.workflow_run.event / …conclusion / …head_sha 這七種
  grep -niE 'access_key|secret_access|session_token' .github/workflows/deploy.yml
  git diff --stat -- .github/workflows/test.yml     # 兩個都預期：無輸出（D16）
  ```

- [ ] **GitHub 上該有的兩樣東西都在**

  ```bash
  gh secret list      # 預期：AWS_DEPLOY_ROLE_ARN（Phase 93 放的）
  gh variable list    # 預期：EC2_WORKER_INSTANCE_ID（本 phase 放的，值看得到）
  ```

- [ ] **6 顆新測試全綠，而且都看過紅**（§4.5 ③做過兩輪、共四次紅）；
      **全量顆數 ＝ 開工基線 ＋ 6**；三死埠零依賴實證顆數相同；ruff 兩句 exit 0；
      端點仍 22、零 DELETE

  ```bash
  pytest tests/integration/test_design6_error_paths.py -v
  # 預期：14 passed（90 的 4 ＋ 93 的 4 ＋ 本 phase 的 6）
  pytest -q                              # 預期：672 passed ＋ 0 skipped
                                         # （基線 ＿＿＿ → 完成 ＿＿＿，自己填）
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q      # 預期：顆數完全相同
  ruff format --check app tests scripts && ruff check app tests scripts
  ```

- [ ] **該零改動的都零改動、專案 `data/` 沒被弄髒**

  ```bash
  git status --short docs/spec/ -- data/
  git diff --stat -- compose.yaml Dockerfile db/ requirements.txt
  find data/staging -type f -mmin +1440 2>/dev/null | head
  # 預期：三個都沒有輸出
  ```

- [ ] **`README.md` §9 多了英文的 "CI/CD" 小段**，位置在 "Code style" 與 "Project layout" 之間
- [ ] **Demo 3 全部做過**（§4.8 步驟 0〜7）：
  - [ ] 步驟 0：第一次 push 之後 `test` 綠（這一輪 `deploy` 有沒有跑都不算數）
  - [ ] 步驟 3：`test` 綠 → `deploy` 出現 → 七個 step 全綠
  - [ ] 步驟 3：最後一步 log 是 `instance state: stopped` ＋ notice「image pushed, next Start pulls latest」，**而且 job 是綠的**（D16）
  - [ ] 步驟 4：`aws ecr describe-images` 看得到那次 push 的**完整 sha**，而且 `latest` 那張映像的 tag 清單裡也有它
  - [ ] 步驟 5：Start 之後 `docker logs cloud-worker | head` 的第一行 `version=` **逐字等於**那個 sha
  - [ ] 步驟 7：**機器已經 `stopped`**
- [ ] **`git log` 裡沒有任何機密**（帳號 ID、實例 ID、role ARN 的真值）

  ```bash
  git log -5 --format='%H %s%n%b' | grep -nE '\b[0-9]{12}\b|i-0[0-9a-f]{8,}'
  # 預期：無輸出
  ```

- [ ] **沒有把 `unfinish/` 搬進 `finish/`**（Phase 95 才處理整批歸檔）

---

## 7. 常見陷阱

1. **`deploy` 沒有跑，也沒有任何錯誤訊息——以為是寫壞了。**
   **症狀：** `test` 綠了，Actions 頁面上完全沒有 `deploy` 這個 workflow。
   **原因（三種，由常見到少見）：** ① `deploy.yml` 在**別的分支**上——`workflow_run` 規定
   「workflow 檔必須存在於**預設分支**上」，放在 feature branch 做實驗**永遠不會觸發**，
   這不是設定錯，是規格；② 那次 `test` 是被 PR 觸發、或不在 `main` 上跑的——`if` 的
   `event == 'push'` 與 `branches: [main]` 刻意把它擋掉了（job 顯示 skipped，或根本不出現）；
   ③ 第一次把 `deploy.yml` 推上 `main` 的那一輪，GitHub 只保證「之後」會觸發，那一輪本身有沒有跑不一定。
   **正解：** 確認 `git branch --show-current` 是 `main`、`workflows: ["test"]` 與 `test.yml` 的
   `name:` 逐字相同，然後**再 push 一次**（§4.8 的步驟 0 與步驟 2 分成兩趟，原因就在這裡）。

2. **用 `github.sha` 而不是 `github.event.workflow_run.head_sha`。**
   **症狀：** 大部分時候看起來完全正常；偶爾部署到一個「沒有被測過」的版本。
   最詭異的一種：CI 測的是 commit A，部署上去的是 commit B。
   **原因：** `workflow_run` 跑在**預設分支的上下文**，所以 `github.sha` 是
   「觸發當下 `main` 的最新 commit」——你在 CI 跑的那 3 分鐘裡如果又 push 了一次，
   兩者就不一樣了。
   **正解：** checkout 的 `ref` 與 build 的 `GIT_SHA`、`tags` **三處都用
   `github.event.workflow_run.head_sha`**。§4.5 的 `test_CD的tag含commit的sha`
   釘的就是這件事。

3. **`vars` 與 `secrets` 寫反，而且不會報錯。**
   **症狀：** 最後一步的 log 印 `instance state:` 後面是空的，或
   `aws ec2 describe-instances --instance-ids ""` 回一個看不懂的 validation error。
   **原因：** GitHub 對不存在的 secret／variable **回空字串，不報錯**。
   本專案：`AWS_DEPLOY_ROLE_ARN` 是 **secret**、`EC2_WORKER_INSTANCE_ID` 是 **variable**。
   **正解：** §4.3 的 bash 第一件事就是 `if [ -z "${EC2_INSTANCE_ID:-}" ]` → 印 notice → `exit 0`，
   讓這種錯**大聲**一點（而不是拿一個空字串繼續往下跑）。

4. **`ssm send-command` 對一台 `stopped` 的機器下指令，得到看不懂的錯誤。**
   **症狀：** `An error occurred (InvalidInstanceId) when calling the SendCommand operation`。
   訊息完全沒提到「機器沒開」——`InvalidInstanceId` 聽起來像實例 ID 打錯了。
   **原因：** SSM 只認得「**agent 正在線上**」的機器。機器關著時它在 SSM 眼中根本不存在。
   **正解：** **先 `describe-instances` 判斷狀態，`running` 才 `send-command`**
   （§4.3 那一步就是這樣寫的）。這也順便滿足了 D16「Stop 時 CD 仍算成功」。

5. **`cancel-in-progress: true`（或漏寫 `concurrency`）。**
   **症狀：** 連續 push 兩次，第一次的 deploy 被中途砍掉。
   最壞的情況是砍在「映像推了一半」或「SSM 送出去了但還沒確認結果」——
   ECR 上留一個不完整的 layer，或 EC2 正在重啟而沒有人知道結果。
   **原因：** 這個 job 有**副作用**（推映像、重啟遠端服務），不是那種「取消了也沒差」的檢查型 job。
   **正解：** `cancel-in-progress: false`（排隊等）。多花幾分鐘，但狀態永遠是完整的。
   ⚠ 反過來說，CI（`test.yml`）那種**沒有副作用**的 job 就適合 `true`——
   但那份**本 phase 不准動**（D16）。

6. **在 `deploy.yml` 的註解裡寫出 `AWS_ACCESS_KEY_ID` 這幾個字。**
   **症狀：** `test_CD沒有寫死任何AWS金鑰` 紅，而你「明明只是寫了個註解」。
   **原因：** 那顆測試掃的是**整份檔案的文字**，包含註解。
   **正解：** **這是刻意的。** 一顆會被自己的註解弄紅的測試，遲早會被人放寬成「不掃註解」，
   那時它就真的守不住任何東西了。要解釋就寫成「長期金鑰」「access key」這種說法
   （§4.3 那份 `deploy.yml` 的檔頭註解就是這樣寫的）。
   **同一個道理適用 `linux/amd64`**：註解裡要提 runner 的架構，寫 `x86_64` 就好。

7. **`Build and push` 那一步跑了十分鐘，以為卡住了。**
   **症狀：** 進度條一直在轉，log 好幾分鐘不動一行。
   **原因：** GitHub 的 runner 是 x86_64，QEMU 要**逐指令模擬** ARM 才跑得動
   `pip install` 那一層。這是**慢**，不是壞。
   **正解：** 第一次（沒有快取）5〜15 分鐘是正常的；之後吃 `cache-from: type=gha`
   大約 2〜4 分鐘。`timeout-minutes: 40` 已經留足餘裕。
   真的想確認它在動：點進那一步看 log，會一直有 `#N [linux/arm64 …]` 的輸出。
   **不要**為了加速改成 x86 架構——EC2 是 ARM，那樣推上去的映像根本跑不動。

8. **以為「fork 來的 PR 反正拿不到 secret」，所以 `workflow_run` 不必防。**
   **症狀：** 沒有 `event == 'push'` 那個條件時：別人從 fork 開一個 PR、分支剛好也叫 `main`，
   `test` 跑完（PR 觸發的 `test` 沒有 secret，這一段是安全的）→ `workflow_run` 觸發 `deploy` →
   **`deploy` 跑在預設分支上下文，有 secret、有 `id-token: write`**，OIDC 令牌的 `sub` 一樣是
   `repo:…:ref:refs/heads/main`（**不是** `pull_request`——因為跑的是預設分支那一份 workflow），
   AWS **會**發憑證；接著 checkout `head_sha`（＝那個 fork 的 commit）、build、push 到你的 ECR。
   GitHub 官方文件在 `workflow_run` 那一節直接點名這個坑，建議的擋法就是檢查
   `github.event.workflow_run.event == 'push'`。
   **正解（三道保險，§4.3 已經寫好）：** ① job 的 `if` 多認 `event == 'push'`——PR 觸發的 `test`
   完成時一律不部署（`test_CD綁在test工作流程成功之後` 釘住）；② `branches: [main]` 擋掉別的分支名；
   ③ `actions/checkout` v7.0.0 起在 `workflow_run` 底下**拒絕 checkout fork PR 的 commit**
   （release note 原文：block checking out fork pr for pull_request_target and workflow_run）。
   ⚠ 不要把「fork PR 拿不到 secret」當成保護——那句話只對 PR 觸發的 `test` 成立，對 `workflow_run` 不成立。

9. **在 CD 裡 `pip install awscli`。**
   **症狀：** `--query` 的行為跟你在 Mac 上試的不一樣，或裝了半天什麼都沒改善。
   **原因：** `ubuntu-latest` 的 runner **預裝 AWS CLI v2**；`pip install awscli` 裝的是
   早就停止支援的 **v1**，而且會蓋掉 v2 在 PATH 上的位置。
   **正解：** 直接用 `aws`，什麼都不必裝。

10. **Demo 3 做完忘了 Stop。**
    **症狀：** 一個月後發現點數少了一成，而且完全想不起來是什麼時候開始的。
    **原因：** `t4g.small` 一直開著大約是每月 $16 的量級（從 $100 點數扣）。
    **正解：** §4.8 的步驟 7 是**驗收清單上的一條**，不是「順便」。
    養成習慣：每次 `start-instances` 之後**立刻**在同一個終端機視窗
    把 `stop-instances` 那一行先打好、不要按 Enter，做完直接按。

11. **機器剛 Start 完 1〜2 分鐘內 push，`deploy` 最後一步紅了：`InvalidInstanceId`。**
    **症狀：** log 先印 `instance state: running`，下一行 `send-command` 就炸
    `An error occurred (InvalidInstanceId) when calling the SendCommand operation`，job 紅。
    **原因：** `running` 是 EC2 的狀態；`send-command` 看的是 **SSM agent 有沒有上線**——開機後 agent
    要幾十秒才註冊，這段空窗 SSM 眼中「沒有這台機器」。§4.3 只用 `describe-instances` 判斷
    （Phase 93 刻意沒給 `ssm:DescribeInstanceInformation`，少要一個權限），所以擋不住這個空窗。
    **正解：** 映像**已經推上去了**（那一步在前面），只是重啟沒做成。等一分鐘，到 Actions 頁面按
    **Re-run failed jobs**（或 `gh run rerun <run-id> --failed`）；或什麼都不做——下次 Start 反正會拉 `latest`。
    本機 Demo（§4.8 步驟 5）遇到同一個錯，也是等 30 秒重送就好。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 多了什麼 |
|---|---|
| repo | `.github/workflows/deploy.yml`（第二個 workflow）；`tests/integration/test_design6_error_paths.py` +6 顆；`README.md` §9 多一小段英文的 "CI/CD" |
| GitHub | 一個 repository **variable** `EC2_WORKER_INSTANCE_ID`（Phase 93 放的是 **secret** `AWS_DEPLOY_ROLE_ARN`） |
| ECR | Demo 3 推上去的映像（`<sha>` ＋ `latest` 兩個 tag 指向同一份） |
| 流程 | **`git push origin main` → 走開。** 測試綠了會自動建 arm64 映像、推 ECR；EC2 開著就順便重啟工人 |

**對外行為變了沒：完全沒有。**

- 端點仍是 **22**、openapi 仍**零 DELETE**。
- `POST /photos` 仍是 **202**，回應仍是三鍵；前端零改動。
- `compose.yaml`、`Dockerfile`、正式庫、`docs/spec/` 全部零改動。
- **`.github/workflows/test.yml` 一個字都沒改**（D16）。

**顆數：**

| | 顆數 |
|---|---|
| 開工基線（Phase 93 之後） | **666** ＋ 0 skipped |
| 本 phase 新增 | **+6**（全部在 `tests/integration/test_design6_error_paths.py`） |
| 完成後 | **672** ＋ 0 skipped |

與總覽 §2.7／§9 的 Phase 94 那一列**完全一致（+6）**。

**已知限制（誠實寫出來，不要在驗收時才發現）：**

- **QEMU 很慢。** 第一次 build 5〜15 分鐘（總覽 §8.12 已列）。改一行 Python 也要等 2〜4 分鐘。
- **`latest` 是會動的 tag。** 開機時 systemd 拉的是 `latest`，所以「開機當下 ECR 上最新的那一份」
  就是它會跑的東西。要指定版本得手動改 `worker.env`／systemd unit——本增量不做（總覽 §8.11）。
- **CD 不管開關機。** EC2 是 `stopped` 的時候，映像推上去了但**沒有人在跑它**，
  要等下一次 Start。這是 D15／D16 的刻意設計，不是缺陷。
- **只有一個環境。** 沒有 staging；push 到 `main` ＝ 直接進「正式」的那台工人。
  對一個單人 side project 這是合理的取捨（而且工人壞掉時所有上傳自動 fallback 本機，D10）。

**下一個 phase：** `phase-95-增量六錯誤收尾與驗收包.md`——
把 design6 §8 錯誤表 10 列逐列點名（補 2 個真缺口）、把 §0 六條禁止與 §1.2 十一列
變成 8 顆掃碼測試（672 → **682**），做三死埠零依賴實證與正式庫健檢，
最後產出**增量六驗收包**給產品負責人。

Phase 95 會用到本 phase 的東西，名字不要改：

- `.github/workflows/deploy.yml`（Phase 95 的 `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣`
  會掃它）
- `tests/integration/test_design6_error_paths.py`（Phase 95 在同一個檔追加最後 10 顆）

---

## 附：本文件引用的官方文件

- [GitHub Actions：`workflow_run` 觸發條件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
  ——「workflow 檔必須在預設分支上」「跑在預設分支上下文」出自這一頁
- [GitHub OIDC → AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [GitHub Actions：variables 與 secrets 的差別](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/store-information-in-variables)
- [`gh variable set`](https://cli.github.com/manual/gh_variable_set)
- [GitHub Actions：`workflow_run` 的安全注意事項（用 `event == 'push'` 擋 fork PR）](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
  ——同一頁；「workflow_run 觸發的 workflow 拿得到 secret 與寫入權」與「建議檢查 event == 'push'」出自這裡
- [`gh run rerun`](https://cli.github.com/manual/gh_run_rerun)（§7 陷阱 11 的 `--failed`）
- [`actions/checkout`](https://github.com/actions/checkout)（2026-08-31 實查最新 `v7.0.1`；
  [v7.0.0 release note](https://github.com/actions/checkout/releases/tag/v7.0.0)：workflow_run 底下拒絕 checkout fork PR）
- [`aws-actions/configure-aws-credentials`](https://github.com/aws-actions/configure-aws-credentials)（實查 `v6.2.4`；[v6.0.0](https://github.com/aws-actions/configure-aws-credentials/releases/tag/v6.0.0) 的 breaking change 只有 Node 24 執行環境）
- [`aws-actions/amazon-ecr-login`](https://github.com/aws-actions/amazon-ecr-login)（實查 `v2.1.7`；`outputs.registry` 出自它的 README）
- [`docker/setup-qemu-action`](https://github.com/docker/setup-qemu-action)（實查 `v4.2.0`）
- [`docker/setup-buildx-action`](https://github.com/docker/setup-buildx-action)（實查 `v4.3.0`）
- [`docker/build-push-action`](https://github.com/docker/build-push-action)（實查 `v7.3.0`）
- [Docker 多平台建置](https://docs.docker.com/build/building/multi-platform/)
- [GitHub Actions 的 build cache（`type=gha`）](https://docs.docker.com/build/cache/backends/gha/)
- [ECR 推映像](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push.html)
- [SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [AWS CLI `ssm send-command`](https://docs.aws.amazon.com/cli/latest/reference/ssm/send-command.html)
- [EC2 Stop 與 Terminate 的差別](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
