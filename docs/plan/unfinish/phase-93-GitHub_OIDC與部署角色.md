# Phase 93：GitHub OIDC 與部署角色

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別不要做的四件事：
> ① **不要**寫 `.github/workflows/deploy.yml`（那是 Phase 94；本 phase 只準備「鑰匙」）；
> ② **不要**為了方便把 trust 的 `sub` 寫成 `repo:1104030360@92135456/personalDocAI@1349196211:*`（那等於任何分支、
> 任何 PR、任何 tag 都能借走這個角色——design6 §8 錯誤表第 9 列明文「不准合併」）；
> ③ **不要**在 GitHub 上存 AWS 的 access key／secret key（OIDC 的整個重點就是不必存）；
> ④ **不要**順手開 GitHub Environments、branch protection、Dependabot、CodeQL（菜單項目，不是現在的痛）。

> 🎯 **一句話目標：** 在 AWS 建一個「只有這個 repo 的 `main` 分支跑 Actions 時才借得到」的
> IAM 角色 `personaldocai-github-deploy`，權限只有三件事（推映像到 ECR、對那一台 EC2 下
> `systemctl restart`、查那台機器開著沒），把角色的 ARN 放進 GitHub 的 repository secret
> `AWS_DEPLOY_ROLE_ARN`，並用 4 顆掃碼測試把「`sub` 逐字鎖 `main`、沒有萬用字元、
> `aud` 是 `sts.amazonaws.com`、`deploy/aws/*.json` 全部沒寫死帳號 ID」釘死。

---

## ⛔ 開工門檻：★ 閘門 G3 必須已由產品負責人通過

**★G3 沒過，本 phase 一個字都不准開始。** 這不是形式——CD 的失敗與工人的失敗
**長得一模一樣**（都是「EC2 上沒反應」）。手動部署還沒跑通就加自動部署，
除錯時分不清是「新映像沒推上去」還是「工人本來就壞」。

下面這張表逐字抄自總覽 §4 的 ★G3：

| 項目 | 內容 |
|---|---|
| 是什麼 | 「真機已經處理過一筆、Stop 之後也自動 fallback 了，可以做自動部署了」的一句話 |
| 誰確認 | **產品負責人（人）**，而且必須親眼看過 **Demo 2 與 Demo 2b** |
| 憑什麼確認 | design6 §0 戊那列：真機 Start → 處理一筆 → Stop；Stop 後下一筆自動本機。逐條指令見總覽 **§5.2**（Demo 2）與 **§5.3**（Demo 2b） |
| 沒過會怎樣 | Phase 93〜94 停擺。理由：CD 的失敗與工人的失敗**長得一模一樣**（都是「EC2 上沒反應」）。手動部署還沒跑通就加自動部署，除錯時分不清是「新映像沒推上去」還是「工人本來就壞」 |
| 卡住時怎麼辦 | ① 真機起不來 → 看 `deploy/ec2/user-data.sh`（回 **91**）；② 工人起得來但拿不到訊息 → IAM instance role 的 policy（回 **91**）；③ 拿得到訊息但看圖失敗 → `worker.env` 的 `OLLAMA_API_KEY`（回 **92** 的 Session Manager 步驟）；④ 一切正常但本機沒收到 → 本機 `.env` 的 `CLOUD_ROUTE=ec2` 與 `EC2_WORKER_INSTANCE_ID`（回 **92**）。⚠ **每一輪除錯完都要記得 Stop** |

> 🚦 **閘門是「人」的動作，實作者不可以自己勾掉。** 指令只是**證據**，
> 「看過證據、同意往下走」的那個動作必須由產品負責人做出來——
> 一句明確的話（口頭、對話、或 dev-prompt 檔案）。
> 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
> 「先做下一段，之後再回來補確認」。

---

**為什麼要做這個：**

**現在的痛：** Phase 92 做完之後，改工人的程式碼要做三件事：

1. 在 Mac 上 `docker build --target cloud-worker --platform linux/arm64 …`
2. `docker push` 到 ECR
3. 用 Session Manager 登進那台 EC2、`sudo systemctl restart personaldocai-worker`

三步任何一步忘了，EC2 上跑的就還是舊程式——**而且完全不會報錯**。
它照常收訊息、照常看圖、照常寫 `result.json`，只是行為是舊的。
這是最難查的一種壞法：沒有紅字、沒有例外，只有「怎麼改了都沒用」。

**做完之後（Phase 93 ＋ 94 合起來）：** `git push` 到 `main` → CI（既有的 `test` workflow）綠 →
CD 自動 build、自動推、自動重啟。人只要 push。

**那本 phase（93）單獨做了什麼？** 只做一件事：**準備鑰匙**。
GitHub Actions 要動 AWS 的東西，得先能證明「我是誰」。有兩種做法：

| 做法 | 長相 | 問題 |
|---|---|---|
| ❌ 舊做法：長期 access key | 建一個 IAM user，把它的 access key／secret key 存進 GitHub secret | 那組字串**永遠有效**。外洩了（截圖、log、離職、第三方 action）就是別人的。而且沒有人會定期換 |
| ✅ 本專案：OIDC | GitHub 每次跑 workflow 會發一張**只對這一次執行有效**的短命令牌；AWS 驗過就發一組**幾小時就過期**的臨時憑證 | GitHub 上**一個 AWS 金鑰都不必存**。要撤銷就把 IAM role 刪掉 |

OIDC 的安全性**全部押在一句條件上**：「這張令牌的 `sub` 欄位必須**逐字等於**
`repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`」。
寫成 `repo:1104030360@92135456/personalDocAI@1349196211:*` 的話，**這個 repo 裡任何分支、任何 PR、任何 tag 上跑的 workflow**
都能拿到你的 AWS 憑證（PR 的 `sub` 長得像 `repo:…:pull_request`，被 `*` 涵蓋）。
design6 §8 錯誤表第 9 列因此明文寫「**GitHub OIDC 未鎖 `sub` → 不准合併**」。

> 📌 **本 repo 真正的 `sub` 前綴含 GitHub 的數字 ID**：`repo:1104030360@92135456/personalDocAI@1349196211`
> （GitHub 2026-07-15 起新 repo 的正式格式，產品負責人 2026-08-31 裁決採用；查證與比對指令見 §4.3 的框）。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **IAM** | AWS 的權限系統（Identity and Access Management）。「誰」可以對「什麼」做「哪些動作」全部在這裡定義 |
| **IAM user（使用者）** | 一組**長期**的帳號密碼（在程式裡叫 access key ＋ secret key）。本專案有**兩個**（都是 Phase 82 建）：`personaldocai-admin`（掛 `AdministratorAccess`，**人**在終端機打 `aws` 指令用，key 在 `aws configure`）與 `personaldocai-mac`（最小權限，**程式**用，key 只放 `.env`）。本 phase 所有 `aws iam …` 指令都是 **admin** 在跑（§4.1 那一行 `unset` 就是為了確保這件事） |
| **IAM role（角色）** | 「一組權限」，但**沒有密碼**。要用它的人（EC2、GitHub Actions）去跟 AWS 換一組**幾小時就過期的臨時憑證**。比長期 key 安全得多 |
| **IAM policy（政策）** | 一份 JSON，寫著「允許／拒絕 哪些動作 對 哪些資源」。**角色能做什麼**由它決定 |
| **trust policy（信任政策）** | 角色的**另一份** JSON：「**誰**可以來借用我」。跟上面那份是兩份不同的文件，作用完全相反（一份管「能做什麼」、一份管「誰能借」），本 phase 兩份都要寫 |
| **OIDC（OpenID Connect）** | 一種「不放長期金鑰也能證明我是誰」的標準。發證的一方（GitHub）簽一張短命令牌，驗證的一方（AWS）用發證方公開的公鑰去驗簽 |
| **OIDC identity provider（身分提供者）** | 在 IAM 裡登記一筆「我信任 `https://token.actions.githubusercontent.com` 這個發證所」。**整個 AWS 帳號只需要建一次**，之後所有角色共用 |
| **JWT／令牌（token）** | GitHub 簽出來的那張「證件」。它是一段 base64 文字，裡面有幾個欄位（claims），本 phase 只在意三個：`iss`（誰簽的）、`aud`（簽給誰用的）、`sub`（在描述誰） |
| **`aud`（audience）** | 「這張證件是簽給誰用的」。GitHub 的 AWS 用法固定是 `sts.amazonaws.com`。鎖住它，等於擋掉「拿一張本來要給別的服務用的令牌來換 AWS 憑證」 |
| **`sub`（subject）** | 「這張證件在描述誰」。GitHub 把它組成 `repo:<擁有者>/<repo>:ref:refs/heads/<分支>`。**這是本 phase 最重要的一個字串** |
| **`sts:AssumeRoleWithWebIdentity`** | 「拿一張外部發的令牌來換 AWS 臨時憑證」的那個 API 動作。trust policy 的 `Action` 就是它（`iss`／issuer ＝「誰簽的」＝ `https://token.actions.githubusercontent.com`） |
| **STS（Security Token Service）** | 發放臨時憑證的服務。`aws sts get-caller-identity` 是「我現在是誰」的萬用檢查指令 |
| **Federated principal（聯邦主體）** | trust policy 裡 `"Principal": {"Federated": …}` 那一段。意思是「借用者不是 AWS 帳號裡的人，是外面某個發證所認證過的身分」 |
| **thumbprint（憑證指紋）** | 發證所的 TLS 憑證的一段雜湊。**2026 年已經不必自己填**（見 §4.2 的查證結論） |
| **ARN（Amazon Resource Name）** | AWS 每個東西的完整身分證字號，長得像 `arn:aws:iam::123456789012:role/xxx`。中間那串 12 位數字就是**帳號 ID** |
| **帳號 ID（Account ID）** | 你的 AWS 帳號編號，**12 位純數字**。它不是機密（ARN 到處都是它），但**不寫進版控**是本專案的規矩——policy JSON 一律用 `<ACCOUNT_ID>` 佔位（總覽 §7 鐵律 10） |
| **ECR（Elastic Container Registry）** | AWS 版的私有 Docker Hub。CD 把映像推到這裡，EC2 從這裡拉 |
| **SSM（AWS Systems Manager）** | 一組管機器的服務。本專案用兩個功能：**Session Manager**（不開 SSH 也能拿到 shell）與 **Run Command**（從外面對機器下一句指令） |
| **SSM SendCommand** | Run Command 的那個 API 動作。CD 用它跑 `sudo systemctl restart personaldocai-worker` |
| **Run Command document（指令文件）** | Run Command 的「劇本」。本專案用 AWS 官方預設的那一份 `AWS-RunShellScript`（意思就是「跑一段 shell」）。它是 **AWS 自己擁有**的資源，所以 ARN 中間的帳號欄是空的：`arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript`（**兩個冒號**不是打錯） |
| **GitHub secret** | 存在 GitHub repo 裡的**加密**字串。放進去之後**看不回來**（只能覆蓋），workflow 裡用 `${{ secrets.名字 }}` 取用，log 裡會被自動遮成 `***` |
| **GitHub variable** | 同一個地方的**不加密**版本，用 `${{ vars.名字 }}` 取用，可以在網頁上看回來。適合放「不是機密、但會變」的東西（Phase 94 的 EC2 實例 ID 就放這裡） |
| **`gh`** | GitHub 的官方命令列工具。這台 Mac 已經裝好（Phase 73 用它建的 repo） |

---

## 1. 對應 design6.md 章節

| 出處 | 說的是什麼 | 本 phase 怎麼落地 |
|---|---|---|
| **D16**（CI／CD 分開） | 「現有 GitHub Actions CI 不動契約。CD：CI 綠 → **OIDC 短憑證** → build `linux/arm64` → ECR `personaldocai:<git-sha>` → SSM Run Command 在 EC2 上 pull＋重啟」 | 本 phase 只做**「OIDC 短憑證」那一段**：provider ＋ role ＋ 兩份 JSON ＋ GitHub secret。build／push／SSM 的 workflow 是 Phase 94。（ECR repository 名稱依總覽 §2.8 是 `personaldocai-worker`；design6 這裡的 `personaldocai` 是簡寫） |
| **§6 安全與隱私**最後一列 | 「GitHub OIDC role：ECR push、SSM SendCommand、描述該實例。**trust 的 `sub` 鎖 repo＋分支**」 | §4.4 的 `github-deploy-policy.json` 恰好三組動作；§4.3 的 trust JSON 用 `StringEquals` 逐字鎖 |
| **§8 錯誤表第 9 列** | 「GitHub OIDC 未鎖 `sub` → CD → **不准合併**；trust 必須釘 repo＋branch」 | §4.7 的兩顆掃碼測試（`test_OIDC信任文件的sub逐字鎖住main分支`、`test_OIDC信任文件沒有星號萬用字元`）——測試紅了就 commit 不了、CI 也會紅，這就是「不准合併」在本專案的落地方式（§4.7 末有完整說明） |
| **總覽 §2.8 裁決** | IAM role（GitHub OIDC）＝ `personaldocai-github-deploy`，檔案 `deploy/aws/github-oidc-trust.json`／`github-deploy-policy.json` | §4.3〜§4.5 逐字沿用這三個名字 |
| **總覽 §10 追認項 b ＋ §10.2 M 列裁決** | b：分支是 **`main`**，`sub` 尾巴鎖 `:ref:refs/heads/main`（**design6 §6 寫的是 `master`，那是筆誤**）；M（2026-08-31）：`sub` 前綴採 GitHub **不可變主體格式** `repo:1104030360@92135456/personalDocAI@1349196211`（本 repo 建於 2026-07-15 之後，GitHub 只簽這種格式） | §4.3 trust JSON 的 `sub` 值；§4.7 的 `GITHUB_OIDC_SUB` 常數與第一顆測試把它釘死；§4.3 的框有「先比對前綴」步驟 |
| **總覽 §7 鐵律 10** | 「文件裡永遠只寫變數名，不寫值……policy JSON 的帳號 ID 一律 `<ACCOUNT_ID>` 佔位」 | §4.4 的 policy 全部用佔位符；§4.7 的 `test_部署用的policy裡沒有寫死帳號ID` 用 regex 掃 12 位純數字，範圍是 `deploy/aws/*.json` **全部**（含 82 的 `mac-policy.json`、84 的 `s3-lifecycle.json`、91 的 `worker-role-*.json`；總覽 §10.2 追加裁決） |

> 📌 **本 phase 引用的是「總覽 §10 追認項 b ＋ §10.2 M 列」，不是 design6 的原文。**
> design6 §6 寫的分支名是 `master`（實查 `git branch --show-current` ＝ `main`），而且 design6 撰寫時
> GitHub 還沒改 `sub` 格式——它寫的 `repo:OWNER/REPO:ref:…` 是舊格式，對本 repo **永遠不成立**（§4.3 的框有查證）。
> 鎖錯分支或鎖錯格式的後果一樣：**CD 永遠拿不到憑證**（每次都在 `configure-aws-credentials`
> 那一步紅掉，錯誤訊息是 `Not authorized to perform sts:AssumeRoleWithWebIdentity`）。
> 這兩條裁決若產品負責人改變主意，回本 phase 的 §4.3（trust JSON 的 `sub`）與 §4.7（`GITHUB_OIDC_SUB`）、
> 以及 Phase 94 的 `branches:` 條件——三個地方要一起改，只改一部分會變成「CD 觸發得了但換不到憑證」。

---

## 2. 前置條件

- **Phase 74〜92 全部完成**（甲＋乙＋丙＋丁＋戊全段）。
- **★ 閘門 G3 已由產品負責人通過**（本檔最上面那張表；**沒過不准開工**）。
- EC2 實例已經建好而且**現在是 `stopped`**（Phase 92 做完 Demo 2／2b 之後有 Stop）。
  本 phase **不需要**把它開機——建 IAM 東西不碰那台機器。
- ECR repository `personaldocai-worker` 已存在（Phase 91 建的），而且裡面**已經有一個手動推上去的映像**。
- `.env` 裡 `EC2_WORKER_INSTANCE_ID` 已經填好（Phase 92 填的）。
- AWS CLI（`aws configure` 的 default profile）指到 **`personaldocai-admin`**（Phase 82 §4.7 設的；本 phase 要建 IAM 東西，最小權限的 `personaldocai-mac` 做不到——它的 key 只在 `.env`）。
- `gh` 已登入，而且 `origin` 是 `https://github.com/1104030360/personalDocAI.git`。

### 開工基線（自己再驗一次，不要抄）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 把 .env 帶進來（下面要用 $EC2_WORKER_INSTANCE_ID），然後**立刻**把裡面那把「程式用」的 key 丟掉——
# 環境變數會蓋過 ~/.aws 的 profile，不 unset 的話每一條 aws 指令都變成最小權限的 personaldocai-mac 在跑
# （Phase 82 §7 陷阱 1 的規矩；每個要讀 .env 的 phase 都一樣）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

pytest -q
# 預期尾巴：662 passed（Phase 92 之後的累計；92 是人工 phase，+0 顆）
#           而且沒有 skipped

git branch --show-current
# 預期：main   ← 若不是 main，先停下來，§4.3 的 sub 要跟著改

git remote -v
# 預期：origin  https://github.com/1104030360/personalDocAI.git (fetch)
#       origin  https://github.com/1104030360/personalDocAI.git (push)

gh auth status
# 預期：Logged in to github.com account 1104030360 …

aws sts get-caller-identity
# 預期（三個欄位；Arn 尾巴是 user/personaldocai-admin）：
# {
#     "UserId": "AIDA…",
#     "Account": "<你的 12 位帳號 ID>",
#     "Arn": "arn:aws:iam::<ACCOUNT_ID>:user/personaldocai-admin"
# }
# 尾巴是 user/personaldocai-mac → 你漏了上面那行 unset；
# Unable to locate credentials → aws configure 沒設 admin 的 key，回 Phase 82 §4.7
# ⚠ 這一行的輸出**不要貼進任何文件**（總覽 §7 鐵律 10）

aws ecr describe-repositories --repository-names personaldocai-worker \
  --region ap-northeast-1 --query 'repositories[0].repositoryUri' --output text
# 預期：<ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/personaldocai-worker

aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --region ap-northeast-1 --query 'Reservations[0].Instances[0].State.Name' --output text
# 預期：stopped   ← 本 phase 全程都應該是 stopped，不必開機

ls deploy/aws/
# 預期看得到：mac-policy.json（82）、worker-role-trust.json、worker-role-policy.json（91）
#             s3-lifecycle.json（84）
# 本 phase 會在同一個目錄多兩份

ls tests/integration/test_design6_error_paths.py
# 預期：檔案存在（Phase 90 開的檔，目前 4 顆 Dockerfile／compose 掃碼）
```

把數字填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | ＿＿＿ passed ＋ 0 skipped（應為 **662**＝總覽 §9 Phase 92 那列的累計） |
| 開工時 `test_design6_error_paths.py` 顆數 | ＿＿＿（總覽 §9 寫 **4**，Phase 90 放的） |
| EC2 狀態 | ＿＿＿（必須是 `stopped`） |

---

## 3. 範圍

### 做

- 在 AWS 帳號裡建**一個** IAM OIDC identity provider，指向 `https://token.actions.githubusercontent.com`
  （**已經有就跳過**，一個帳號只能有一個同 URL 的 provider）。
- 新建 `deploy/aws/github-oidc-trust.json`：trust policy，`sub` **精確等於**
  `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`（GitHub 不可變主體格式；總覽 §10.2 M 列）、
  `aud` **精確等於** `sts.amazonaws.com`，**整份文件沒有任何 `*`**。
- 新建 `deploy/aws/github-deploy-policy.json`：權限 policy，只有三組動作
  （ECR push、SSM 對那一台實例跑 `AWS-RunShellScript`、`ec2:DescribeInstances`）。
- 用 AWS CLI 建角色 `personaldocai-github-deploy`（`create-role` ＋ `put-role-policy`）。
- 把角色 ARN 放進 GitHub repository secret **`AWS_DEPLOY_ROLE_ARN`**。
- 在 `tests/integration/test_design6_error_paths.py` 追加 **4 顆**掃碼測試（名稱見 §4.7；第 4 顆掃 `deploy/aws/*.json` **全部**）。
- 更新 `CLAUDE.md` 指令區的 AWS 小段（Phase 82 建的那一段）補「部署角色」三行。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 寫 `.github/workflows/deploy.yml` | 那是 **Phase 94**。本 phase 做完之後，GitHub 上還沒有任何 CD——這是刻意的：先確認鑰匙配得起來，再裝門 |
| trust 用 `StringLike` ＋ `repo:1104030360@92135456/personalDocAI@1349196211:*` | 那會讓**任何分支、任何 PR、任何 tag** 都借得到這個角色。design6 §8 第 9 列明文禁止。`StringEquals` ＋ 完整字串是唯一寫法 |
| 在 GitHub 存 access key／secret key | OIDC 的整個重點就是不必存。存了等於白做（而且那組字串永遠有效） |
| 給角色 `AdministratorAccess` 或 `PowerUserAccess` 這種 managed policy | 「先給大一點，之後再收」＝之後不會收。design6 §6「IAM 最小權限」 |
| `iam:PassRole`、`ec2:StartInstances`、`ec2:StopInstances` | CD **不負責開關機**（D16：EC2 Stop 時 CD 仍可 push）。開機是人做的事，多給了就多一個被誤用的面 |
| 建第二個 OIDC provider、或改動既有的 | 一個帳號對同一個 URL 只能有一個 provider。已經有就用現成的（§4.2 有「已存在就跳過」的判斷） |
| 開 GitHub Environments／branch protection／required reviewers | 菜單項目。單人 side project 加了只會讓自己 push 不上去 |
| 動 `.github/workflows/test.yml` | D16「現有 CI 不動契約」。`git diff` 對它必須是空的 |
| 動 `app/` 底下任何一個 `.py` | 本 phase 零產品碼改動。做完 `git status --short -- app/` 應與開工前完全相同 |
| 把帳號 ID／實例 ID／role ARN 的**值**寫進 `docs/`、`deploy/`、`README.md`、commit message | 總覽 §7 鐵律 10。一律 `<ACCOUNT_ID>`／`<INSTANCE_ID>` 佔位 |
| 把 EC2 開機來「順便試一下」 | 本 phase 完全不需要那台機器。開了就在燒點數（D15），而且 Phase 94 的 Demo 3 才是真的要開的時候 |

---

## 4. 實作步驟

> 📌 **順序是有意義的：** 先建 provider（②）→ 寫兩份 JSON（③④）→ 建角色（⑤）→
> 放 secret（⑥）→ 才寫測試（⑦）。
> **測試放在最後不是偷懶**——這 4 顆是「**掃設定檔**」的測試，設定檔還沒寫出來時
> 它們紅得毫無資訊量（只會說「檔案不存在」）。真正的 TDD 節奏在 §4.7：
> **先把 JSON 故意寫錯一個字、跑測試看它紅、再改回來**（那才是「看過紅」）。

### 4.1 把會用到的值放進這個終端機（不寫進任何檔案）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# set -a ＝接下來的賦值自動 export 成環境變數；set +a ＝關掉這個行為
set -a; . ./.env; set +a
# ★ 載完馬上把 .env 裡「程式用」的那把 key 丟掉，讓 aws 指令回到 aws configure 裡的 admin。
#   環境變數的優先權高於 ~/.aws/credentials——不 unset，下面每一條 aws iam 都會被
#   最小權限的 personaldocai-mac 擋下來（AccessDenied）。（Phase 82 §7 陷阱 1）
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws sts get-caller-identity --query Arn --output text     # 預期結尾：:user/personaldocai-admin

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-ap-northeast-1}
GITHUB_REPO=1104030360/personalDocAI

# 確認三個都讀到了（⚠ 這一行的輸出**不要**貼進任何文件或 commit message）
echo "region=$AWS_REGION  repo=$GITHUB_REPO  instance=$EC2_WORKER_INSTANCE_ID"
echo "account 長度=${#ACCOUNT_ID}"      # 預期：12
```

**預期輸出長相：**

```text
arn:aws:iam::<你的帳號>:user/personaldocai-admin
region=ap-northeast-1  repo=1104030360/personalDocAI  instance=i-0xxxxxxxxxxxxxxxx
account 長度=12
```

- [ ] Arn 結尾是 `user/personaldocai-admin`（是 `personaldocai-mac` → 那行 `unset` 沒跑到）；三個變數都有值；`account 長度` 是 **12**。
      `EC2_WORKER_INSTANCE_ID` 是空的 → 回 Phase 92 把 `.env` 填好（§4.4 的 policy 要用它）。

> ⚠️ **這幾個變數只活在這個終端機視窗。** 關掉視窗、或換一個分頁，就要重跑一次
> 上面這整段（**含那行 `unset`**）。下面每一節的指令都假設它們還在。

### 4.2 建 IAM OIDC identity provider（已存在就跳過）

**這是什麼：** 在你的 AWS 帳號裡登記一句話——「我信任
`https://token.actions.githubusercontent.com` 這個發證所簽出來的令牌」。
**整個 AWS 帳號只需要建一次**，之後所有 GitHub 的角色共用同一個 provider。

#### ★ 先查證：2026 年還要不要自己填 thumbprint？

> **結論：不用了。`--thumbprint-list` 是選填的，本專案不填。**
>
> AWS 官方文件（[Create an OIDC identity provider in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)）
> 現在寫著（2026-08-31 以 WebFetch 讀原文，逐字翻譯）：
>
> > 「AWS 使用**我們自己的可信根憑證機構（CA）清單**來驗證 OIDC 身分提供者的
> > JSON Web Key Set（JWKS）端點的 TLS 憑證。**只有當**你的 OIDC IdP 用的憑證
> > 不是由這些可信 CA 簽發時，我們才會改用該 IdP 設定裡的 thumbprint 來確保通訊安全。
> > 若我們無法取得 TLS 憑證、或對方要求 TLS v1.3，AWS 會退回用 thumbprint 驗證。」
>
> AWS CLI 參考頁（[`create-open-id-connect-provider`](https://docs.aws.amazon.com/cli/latest/reference/iam/create-open-id-connect-provider.html)）
> 的 synopsis 也把它放在方括號裡（＝選填）：
>
> ```text
> create-open-id-connect-provider
> --url <value>
> [--client-id-list <value>]
> [--thumbprint-list <value>]
> [--tags <value>]
> ```
>
> 且明文：「**這個參數是選填的。**沒有提供時，IAM 會自己去取得並使用該 OIDC 身分提供者
> 伺服器憑證的**最上層中繼 CA thumbprint**。」
>
> `token.actions.githubusercontent.com` 的憑證是由公開可信的 CA 簽的，
> 所以走的是「AWS 自己的可信 CA 清單」那條路——**填不填 thumbprint 都不影響結果**。
>
> **為什麼要特別查這件事：** 網路上 2021〜2023 年的教學幾乎都寫著
> `--thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1`（甚至還有第二個
> `1c58a3a8518e8759bf075b76b750d4f2df264fcd`）。那是**當年必填**時代的產物。
> 照那些教學貼一個寫死的雜湊進去，GitHub 換憑證的那天你會得到一個
> 「憑證驗證失敗」而完全想不到是這裡。**不填最安全，因為 AWS 會自己維護。**

#### 指令

```bash
# ① 先看有沒有（一個帳號對同一個 URL 只能有一個）
aws iam list-open-id-connect-providers --output text
```

**預期輸出（兩種都正常）：**

```text
# 還沒建過 → 完全沒有輸出（空的）
# 已經建過 → 類似這一行：
OPENIDCONNECTPROVIDERLIST   arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com
```

```bash
# ② 沒有才建。下面這段有 if 判斷，重複執行是安全的
if aws iam list-open-id-connect-providers --output text \
     | grep -q "token.actions.githubusercontent.com"; then
  echo "已經有 GitHub 的 OIDC provider 了，跳過建立"
else
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com
fi
```

每個旗標的用途：

| 旗標 | 用途 |
|---|---|
| `--url https://token.actions.githubusercontent.com` | 發證所的網址。**必須逐字這樣寫**（沒有結尾斜線、沒有埠號）。AWS 會去 `<這個網址>/.well-known/openid-configuration` 抓設定 |
| `--client-id-list sts.amazonaws.com` | 允許的 `aud` 值。GitHub 的 AWS 用法固定是這個字串 |
| （不給 `--thumbprint-list`） | 選填；見上面的查證結論。AWS 自己會取 |

**建立成功的預期輸出：**

```json
{
    "OpenIDConnectProviderArn": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
}
```

**已存在時的預期輸出：**

```text
已經有 GitHub 的 OIDC provider 了，跳過建立
```

- [ ] 兩種輸出之一。

```bash
# ③ 驗證：provider 存在、而且 aud 清單裡有 sts.amazonaws.com
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" \
  --query '{Url:Url, Audiences:ClientIDList}'
```

**預期輸出：**

```json
{
    "Url": "token.actions.githubusercontent.com",
    "Audiences": [
        "sts.amazonaws.com"
    ]
}
```

> ⚠️ **注意 `Url` 沒有 `https://`。** AWS 回傳時會把 scheme 拿掉，這是正常的
> （建立時**一定要**帶 `https://`，讀回來時**一定**沒有）。不要因為看起來不一樣就重建一個。

**做錯了怎麼退回：**

| 出錯情況 | 怎麼救 |
|---|---|
| 網址打錯（例如多了結尾斜線）建成了另一個 provider | `aws iam delete-open-id-connect-provider --open-id-connect-provider-arn <那個錯的 ARN>`。刪掉不影響別的東西——只要還沒有角色指著它 |
| `EntityAlreadyExists` | 就是已經有了。跳到 ③ 驗證那一步即可，不必刪掉重建 |
| `AccessDenied`（`iam:CreateOpenIDConnectProvider`） | 十之八九是這個 shell 還拿著 `.env` 裡 `personaldocai-mac` 的 key（環境變數贏過 `~/.aws`）。先跑 `aws sts get-caller-identity --query Arn --output text`：結尾是 `user/personaldocai-mac` → 回 §4.1 跑 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 再來一次；結尾已是 `user/personaldocai-admin` 卻仍被拒 → admin 沒掛到 `AdministratorAccess`，回 Phase 82 §4.5 補掛。**不要**為了這一次去放寬 `mac-policy.json`（那份是「這台 Mac 日常在用」的權限，放寬了就收不回來），也**不要**回頭用 root（Phase 82 之後 root 只留給 MFA 與帳務） |

> 💡 **Console 路徑（不想用 CLI 時走這條；用 `personaldocai-admin` 登入 Console，不是 root）：**
> AWS Console → **IAM** → 左側 **Identity providers** → **Add provider** →
> 選 **OpenID Connect** → Provider URL 填 `https://token.actions.githubusercontent.com` →
> Audience 填 `sts.amazonaws.com` → **Add provider**。
> Console 不會問你 thumbprint（它自己抓）。

### 4.3 寫 trust policy：`deploy/aws/github-oidc-trust.json`

**這是什麼：** 角色的「**誰能借我**」文件。整個 OIDC 的安全性都在這一份。

> ✅ **本 repo 的 `sub` 前綴含 GitHub 的數字 ID——這是正式格式，不是筆誤**
> **（產品負責人 2026-08-31 裁決；總覽 §2.8、§10.2 M 列）**
>
> GitHub 自 **2026-07-15** 起，**新建的 repo 預設改用「不可變主體（immutable subject）」格式**的 `sub`：
>
> ```text
> 舊格式  repo:<擁有者>/<repo>:ref:refs/heads/<分支>                       ← design6 §6 寫的是這種
> 新格式  repo:<擁有者>@<擁有者ID>/<repo>@<repo ID>:ref:refs/heads/<分支>   ← 本 repo 只會拿到這種
> ```
>
> 官方原文（[OIDC reference §Immutable subject claims](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)、
> [Changelog 2026-04-23](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)）：
> *"Repositories created after July 15, 2026 now use an immutable default subject format that includes
> both the owner ID and repository ID."* … *"Repository renames and transfers after July 15, 2026 will
> also adopt the new format."* … *"Update your trust policies to match the format your repository uses."*
>
> 本 repo 建於 **2026-08-28**（Phase 73 的 `gh repo create`），所以 GitHub **只會**簽新格式。
> 前綴是 GitHub 決定的、不是我們選的——2026-08-31 用這條**唯讀**指令實查：
>
> ```bash
> gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub
> ```
>
> ```json
> {"use_default":true,"use_immutable_subject":false,"sub_claim_prefix":"repo:1104030360@92135456/personalDocAI@1349196211"}
> ```
>
> `92135456` 是 GitHub 使用者 `1104030360` 的數字 ID、`1349196211` 是這個 repo 的數字 ID
> （`gh api users/1104030360 --jq .id`、`gh repo view 1104030360/personalDocAI --json id` 都查得到；
> **公開可查、不是機密**，也都不是 12 位數，§4.7 的帳號 ID 掃描不會誤抓）。
> 所以本 phase 鎖的 `sub` ＝ 前綴 ＋ `:ref:refs/heads/main`：
>
> ```text
> repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
> ```
>
> 用舊格式（沒有 `@ID`）的話**永遠對不上**——CD 會在 `configure-aws-credentials` 那一步紅掉，
> 訊息就是 §7 陷阱 1 那句 `Not authorized to perform sts:AssumeRoleWithWebIdentity`。
> 也**不要**用 `PUT …/actions/oidc/customization/sub` 把 repo 切回舊格式（總覽 §10.2 M：那會多一個
> 藏在 GitHub 設定裡、誰按一下 CD 就全紅的開關，還放棄了 GitHub 改格式的安全理由）。
>
> **動手前仍然要比對一次**（repo 改名／轉移都會讓前綴變，GitHub 的設定頁也有人按得到）。

- [ ] 跑下面這條，輸出必須**逐字**等於 `repo:1104030360@92135456/personalDocAI@1349196211`；
      不等 → 停下來回報產品負責人（契約要跟著改：本檔 §4.3／§4.7、總覽 §2.8、Phase 94），**不要** `create-role`：

```bash
gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub --jq .sub_claim_prefix
# 預期：repo:1104030360@92135456/personalDocAI@1349196211
```

```bash
mkdir -p deploy/aws
cat > deploy/aws/github-oidc-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GitHubActionsMainBranchOnly",
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"
        }
      }
    }
  ]
}
EOF
```

逐段解釋（每一行都有理由，不要刪）：

| 欄位 | 值 | 為什麼 |
|---|---|---|
| `Version` | `2012-10-17` | IAM policy 的語法版本。**這是固定字串，不是日期**，不要改成今天 |
| `Sid` | `GitHubActionsMainBranchOnly` | 給人看的標籤（Statement ID）。AWS 不用它做判斷，但翻 Console 時一眼看得出這條在幹嘛 |
| `Effect` | `Allow` | 允許 |
| `Principal.Federated` | `arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com` | 「借用者是**外部發證所**認證的身分」，而且指名是 §4.2 建的那個 provider。**這個 ARN 裡的 `<ACCOUNT_ID>` 是你的帳號**——provider 是建在你自己帳號裡的，不是 GitHub 的 |
| `Action` | `sts:AssumeRoleWithWebIdentity` | 唯一允許的動作：拿外部令牌換臨時憑證。**不要**寫成 `sts:AssumeRole`（那是給 AWS 內部身分用的，OIDC 用不到，寫了會變成「怎麼試都 AccessDenied」） |
| `Condition.StringEquals.…:aud` | `sts.amazonaws.com` | 令牌必須是「簽給 AWS STS 用的」。擋掉「拿別的服務的令牌來換」 |
| `Condition.StringEquals.…:sub` | `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main` | **本 phase 的核心**。只有「這個 repo」的「`main` 分支上的 workflow」才借得到。`@92135456`／`@1349196211` 是 GitHub 給擁有者與 repo 的數字 ID（不可變主體格式，2026-07-15 起新 repo 的預設；上面的框有查證） |

#### 為什麼 `sub` 是 `ref:refs/heads/main`，而不是 PR 或 tag？

GitHub 依「這次執行是什麼觸發的」組出不同的 `sub`：

```text
push 到 main 分支         sub = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
push 到別的分支           sub = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/其他分支名
pull request              sub = repo:1104030360@92135456/personalDocAI@1349196211:pull_request
打 tag                    sub = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/tags/v1.0
GitHub Environment 上跑   sub = repo:1104030360@92135456/personalDocAI@1349196211:environment:production
```

我們只允許第一種。

**那 Phase 94 的 CD 是 `workflow_run` 觸發的，`sub` 會是什麼？**
——**尾巴還是 `:ref:refs/heads/main`**。GitHub 官方的事件表
（[Events that trigger workflows → `workflow_run`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)）
對這個事件寫得很明確：`GITHUB_SHA` ＝ *Last commit on default branch*、**`GITHUB_REF` ＝ *Default branch***，
而且 *"This event will only trigger a workflow run if the workflow file exists on the default branch."*
也就是說：不管被觸發的那次 `test` 跑的是哪個分支，`deploy` 這個 workflow
**永遠是以預設分支（本專案＝`main`）的身分在跑**，`GITHUB_REF` 是
`refs/heads/main`，OIDC 令牌的 `sub` 尾巴因此也是 `:ref:refs/heads/main`
（前綴的格式見上面的框）。同一頁另一句對 Phase 94 也重要：
*"The workflow started by the `workflow_run` event is able to access secrets and write tokens,
even if the previous workflow was not."*——所以 `deploy` 讀得到 `secrets.AWS_DEPLOY_ROLE_ARN`。

這剛好是我們要的：**`sub` 鎖 `main` 不會擋到 CD**。
（Phase 94 另外用 `branches: [main]` 這個過濾條件確保「只有 `main` 上跑成功的 CI 才觸發 CD」——
那是**觸發**層的守門，跟這裡的**憑證**層是兩道獨立的鎖。）

- [ ] 檔案寫好了，而且用 Python 檢查它是合法 JSON、`<ACCOUNT_ID>` 佔位還在：

```bash
python3 -c "
import json, pathlib
d = json.loads(pathlib.Path('deploy/aws/github-oidc-trust.json').read_text())
s = d['Statement'][0]
print('Action  =', s['Action'])
print('sub     =', s['Condition']['StringEquals']['token.actions.githubusercontent.com:sub'])
print('aud     =', s['Condition']['StringEquals']['token.actions.githubusercontent.com:aud'])
print('有 StringLike 嗎 =', 'StringLike' in s['Condition'])
"
grep -c '<ACCOUNT_ID>' deploy/aws/github-oidc-trust.json
```

**預期輸出：**

```text
Action  = sts:AssumeRoleWithWebIdentity
sub     = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
aud     = sts.amazonaws.com
有 StringLike 嗎 = False
1
```

### 4.4 寫權限 policy：`deploy/aws/github-deploy-policy.json`

**這是什麼：** 角色的「**能做什麼**」文件。恰好三件事，多一件都不給。

```bash
cat > deploy/aws/github-deploy-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLoginTokenIsAccountWide",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "EcrPushOnlyToTheWorkerRepository",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-1:<ACCOUNT_ID>:repository/personaldocai-worker"
    },
    {
      "Sid": "SsmRestartOnlyThatOneInstance",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:ap-northeast-1:<ACCOUNT_ID>:instance/<INSTANCE_ID>",
        "arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript"
      ]
    },
    {
      "Sid": "SsmReadTheCommandResult",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    },
    {
      "Sid": "DescribeInstancesToSeeIfItIsRunning",
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*"
    }
  ]
}
EOF
```

五段 Statement 逐段解釋：

| # | Sid | 動作 | Resource | 為什麼是這個 Resource |
|---|---|---|---|---|
| 1 | `EcrLoginTokenIsAccountWide` | `ecr:GetAuthorizationToken` | `*` | 這個動作**不吃資源**（它是「給我一張 registry 的登入票」，票是整個帳號一張）。它沒有資源型別，`Resource` 只能寫 `*`；寫成 repo ARN 這條就永遠對不上（拿票時 AccessDenied）。這是**唯一**一個必須是 `*` 的 ECR 動作 |
| 2 | `EcrPushOnlyToTheWorkerRepository` | 推映像會用到的六個動作（＝AWS 官方「推映像最小權限」範例的那六個） | `…:repository/personaldocai-worker` | 只准推**這一個** repository。以後就算多了別的 repository，這把鑰匙也碰不到 |
| 3 | `SsmRestartOnlyThatOneInstance` | `ssm:SendCommand` | **兩個** ARN：那台實例 ＋ 那份 document | SSM 的 `SendCommand` **同時檢查兩種資源**：「對哪台機器下」與「用哪份劇本」。**兩個都要給，少一個就 AccessDenied**。這是最容易漏的一條 |
| 4 | `SsmReadTheCommandResult` | `ssm:GetCommandInvocation` | `*` | 「查那句指令跑完了沒」（Phase 94 的輪詢迴圈就只用這一個）。這個動作沒有資源型別——執行紀錄的 ID 是送出當下才生出來的，事先寫不出 ARN，所以只能 `*`。它是**唯讀**的，風險極低 |
| 5 | `DescribeInstancesToSeeIfItIsRunning` | `ec2:DescribeInstances` | `*` | AWS 的 `Describe*` 系列**一律不支援資源層級限制**（官方限制，不是我們偷懶）。同樣是唯讀 |

六個 ECR 動作各自的用途（推一次映像真的會全部用到；清單逐字等於 AWS 官方 [image-push-iam](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html) 的範例）：

| 動作 | 什麼時候會用到 |
|---|---|
| `ecr:BatchCheckLayerAvailability` | 「這幾層我已經傳過了嗎？」——沒傳過的才傳，這是 push 快的原因 |
| `ecr:InitiateLayerUpload` | 「我要開始傳一層了」 |
| `ecr:UploadLayerPart` | 真的在傳資料 |
| `ecr:CompleteLayerUpload` | 「這一層傳完了」 |
| `ecr:PutImage` | 最後那一步：登記 manifest 與 tag（`<sha>` 與 `latest` 各一次） |
| `ecr:BatchGetImage` | 推多個 tag／確認既有 manifest 時會讀回映像資料；AWS 官方推映像範例就含它 |

#### `<INSTANCE_ID>` 怎麼帶進去（用 `sed`，不要手改檔案）

檔案裡永遠是佔位符（總覽 §7 鐵律 10），**要送給 AWS 的時候才在管線上換掉**：

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" \
    -e "s|<INSTANCE_ID>|$EC2_WORKER_INSTANCE_ID|g" \
    deploy/aws/github-deploy-policy.json > /tmp/github-deploy-policy.rendered.json

sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" \
    deploy/aws/github-oidc-trust.json > /tmp/github-oidc-trust.rendered.json
```

`sed` 的旗標：

| 部分 | 用途 |
|---|---|
| `-e` | 「接下來是一句編輯指令」。要換兩種佔位符就寫兩個 `-e` |
| `s\|舊\|新\|g` | `s` ＝ substitute（取代）；`g` ＝ global（同一行出現幾次就換幾次） |
| 為什麼用 `\|` 當分隔符而不是 `/` | ARN 裡有 `/`（`instance/i-xxx`、`repository/personaldocai-worker`）。用 `/` 當分隔符就得逐個跳脫，很容易漏。`\|` 在 ARN 裡不會出現，最安全 |
| 為什麼輸出到 `/tmp` | **展開後的檔案含真實帳號 ID 與實例 ID，絕對不能進 repo。** 放 `/tmp` 是刻意的：重開機就沒了，而且 `.gitignore` 管不到專案外的東西 |

- [ ] 檢查展開結果（**這一步的輸出不要貼進任何文件**）：

```bash
python3 -c "
import json
d = json.load(open('/tmp/github-deploy-policy.rendered.json'))
for s in d['Statement']:
    print(s['Sid'], '->', s['Resource'])
"
grep -c '<' /tmp/github-deploy-policy.rendered.json    # 預期：0（佔位符全換掉了）
```

**預期輸出長相（帳號與實例是你的真值）：**

```text
EcrLoginTokenIsAccountWide -> *
EcrPushOnlyToTheWorkerRepository -> arn:aws:ecr:ap-northeast-1:<你的帳號>:repository/personaldocai-worker
SsmRestartOnlyThatOneInstance -> ['arn:aws:ec2:ap-northeast-1:<你的帳號>:instance/i-0xxxx', 'arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript']
SsmReadTheCommandResult -> *
DescribeInstancesToSeeIfItIsRunning -> *
0
```

> ⚠️ `arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript` 那**兩個連續冒號不是打錯**。
> ARN 的格式是 `arn:partition:service:region:account-id:resource`；
> `AWS-RunShellScript` 是 **AWS 自己擁有**的公開 document，所以 account-id 那一格是空的。
> 手癢把自己的帳號填進去的話，`SendCommand` 會回 AccessDenied，而錯誤訊息**不會告訴你是這裡**。

### 4.5 建角色並掛上 policy

```bash
# ① 建角色（trust policy 就是「誰能借」那一份）
aws iam create-role \
  --role-name personaldocai-github-deploy \
  --assume-role-policy-document file:///tmp/github-oidc-trust.rendered.json \
  --description "GitHub Actions CD: push image to ECR and restart the EC2 worker" \
  --max-session-duration 3600
```

每個旗標的用途：

| 旗標 | 用途 |
|---|---|
| `--role-name personaldocai-github-deploy` | 角色名字（總覽 §2.8 定的，逐字沿用） |
| `--assume-role-policy-document file://…` | **trust policy**。`file://` 後面接**絕對路徑**，所以是**三條斜線**（`file://` ＋ `/tmp/…`）。這是 AWS CLI 的通用寫法 |
| `--description` | 給人看的。半年後在 Console 看到這個角色時，一眼知道它是幹嘛的 |
| `--max-session-duration 3600` | 借到的臨時憑證**最多活 1 小時**。CD 跑完大概 10〜20 分鐘，1 小時綽綽有餘。給更長沒有好處 |

**預期輸出（節錄；`Arn` 那一行是本 phase 的產出）：**

```json
{
    "Role": {
        "Path": "/",
        "RoleName": "personaldocai-github-deploy",
        "RoleId": "AROA…",
        "Arn": "arn:aws:iam::<ACCOUNT_ID>:role/personaldocai-github-deploy",
        "CreateDate": "2026-…",
        "AssumeRolePolicyDocument": { … 你剛剛那份 trust … },
        "MaxSessionDuration": 3600
    }
}
```

```bash
# ② 把權限 policy 掛上去（inline policy：跟著角色走，角色刪了它也跟著消失）
aws iam put-role-policy \
  --role-name personaldocai-github-deploy \
  --policy-name personaldocai-github-deploy-policy \
  --policy-document file:///tmp/github-deploy-policy.rendered.json
```

**預期輸出：完全沒有輸出**（AWS CLI 的慣例：成功的 `put-*` 不印東西）。

> 💡 **為什麼用 inline policy（`put-role-policy`）而不是 managed policy
> （`create-policy` ＋ `attach-role-policy`）？**
> inline policy 是「長在角色身上」的，**角色刪掉它就一起消失**，不會留孤兒。
> managed policy 是獨立的物件，可以掛到多個角色上——本專案只有一個角色要用它，
> 用 managed policy 只是多一個要記得清掉的東西。

- [ ] 驗證兩份文件都掛對了：

```bash
# trust：sub 與 aud
aws iam get-role --role-name personaldocai-github-deploy \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals'

# 權限：五段 Statement 的 Sid
aws iam get-role-policy \
  --role-name personaldocai-github-deploy \
  --policy-name personaldocai-github-deploy-policy \
  --query 'PolicyDocument.Statement[].Sid' --output text
```

**預期輸出：**

```json
{
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub": "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"
}
```

```text
EcrLoginTokenIsAccountWide      EcrPushOnlyToTheWorkerRepository SsmRestartOnlyThatOneInstance   SsmReadTheCommandResult DescribeInstancesToSeeIfItIsRunning
```

- [ ] 兩個輸出都對得上。

**做錯了怎麼退回：**

| 出錯情況 | 訊息長相 | 怎麼救 |
|---|---|---|
| trust JSON 打錯字 / 不是合法 JSON | `MalformedPolicyDocument` 或 `Error parsing parameter` | 改 `deploy/aws/github-oidc-trust.json` → 重跑 §4.4 的 `sed` → **`aws iam update-assume-role-policy --role-name personaldocai-github-deploy --policy-document file:///tmp/github-oidc-trust.rendered.json`**（角色已存在時用這個「更新 trust」的指令，不必刪掉重建） |
| 權限 policy 寫錯 | 同上 | 改檔 → 重跑 `sed` → **再跑一次 `put-role-policy`**（同名會直接覆蓋，這是預期行為） |
| 角色名打錯，建了一個多餘的 | — | `aws iam delete-role-policy --role-name <錯的> --policy-name <那個 policy>` 然後 `aws iam delete-role --role-name <錯的>`。**順序不能反**——inline policy 還在的話 `delete-role` 會失敗（`DeleteConflict`） |
| `EntityAlreadyExists` | 角色已經有了 | 不必刪。改用 `update-assume-role-policy` ＋ `put-role-policy` 把兩份文件更新上去 |
| `AccessDenied` | 這個 shell 還拿著 `personaldocai-mac` 的 key（忘了 §4.1 的 `unset`），或 admin 的 key 沒設進 `aws configure` | 與 §4.2 那列相同：`aws sts get-caller-identity --query Arn --output text` 看現在是誰 → `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 回到 admin 再跑。真的想走 Console（用 `personaldocai-admin` 登入）：IAM → Roles → Create role → Web identity → 選 provider 與 audience → 之後在 **Trust relationships** 分頁貼上完整 trust JSON、在 **Permissions** 分頁 → Add permissions → Create inline policy → JSON 分頁貼上權限 JSON。**不要**放寬 `mac-policy.json` |

**費用影響：**
IAM 的 role、policy、OIDC provider **全部免費**，沒有數量計費、沒有月費。
本 phase **不會產生任何 AWS 費用**（也不會扣 Free plan 的點數）——
它一行 EC2、一 byte S3 都沒有碰。

### 4.6 把角色 ARN 放進 GitHub secret

```bash
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/personaldocai-github-deploy"

gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"
```

**預期輸出：**

```text
✓ Set Actions secret AWS_DEPLOY_ROLE_ARN for 1104030360/personalDocAI
```

- [ ] 確認它在（**只看得到名字與更新時間，看不到值——這是刻意的**）：

```bash
gh secret list
```

**預期輸出：**

```text
NAME                   UPDATED
AWS_DEPLOY_ROLE_ARN    less than a minute ago
```

> 💡 **Console 路徑（不用 `gh` 的話）：**
> GitHub → repo `1104030360/personalDocAI` → **Settings** → 左側
> **Secrets and variables** → **Actions** → **New repository secret** →
> Name 填 `AWS_DEPLOY_ROLE_ARN`、Secret 貼上 role ARN → **Add secret**。

#### 為什麼 role ARN 不算機密，卻仍然放 secret？

**它真的不是機密。** ARN 裡只有帳號 ID 與角色名——知道了也借不走，因為
**借得走的唯一條件是「你的 OIDC 令牌的 `sub` 逐字等於我們鎖的那一串」**，
而那需要你能在 `1104030360/personalDocAI` 的 `main` 分支上跑 workflow。

仍然放 secret 的三個理由：

1. **它是設定，不是常數。** 帳號換了、角色改名了，只要改這一格，workflow 一個字都不必動。
2. **Actions 的 log 會自動把 secret 的值遮成 `***`。** 帳號 ID 不是機密，
   但也沒必要每次 build 都印在公開的 log 裡（這個 repo 現在是 private，
   哪天改成 public 就不必回頭補救）。
3. **一致性。** GitHub 官方的 OIDC 範例就是這樣寫（`role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}`），
   照著走，之後查文件對得起來。

> ⚠️ **注意：`vars` 與 `secrets` 是兩個不同的命名空間。**
> Phase 94 會用 `gh variable set EC2_WORKER_INSTANCE_ID`（**variable**，不是 secret），
> 因為那個值在 workflow 的 bash 裡要拿來組指令、失敗時希望 log 看得到它是什麼。
> 兩者在 workflow 裡的寫法不同（`${{ secrets.X }}` vs `${{ vars.X }}`），**寫錯會拿到空字串**，
> 而且**不會報錯**——bash 會拿一個空的變數繼續跑。這是 §7 陷阱 4。

### 4.7 TDD：4 顆掃碼測試（先看到紅，再看到綠）

> 📌 這 4 顆追加在 **Phase 90 開的**那個檔 `tests/integration/test_design6_error_paths.py`
> 的最後面。**不要新開檔**（總覽 §10 追認項 B 的裁決：90 開檔、93／94 追加、95 收尾）。

**① 先跑一次，記下現在幾顆：**

```bash
pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：4 tests collected（Phase 90 放的 Dockerfile／compose 掃碼）
```

**② 把下面這一整段追加到檔案最後面（照抄）：**

```python
# ---------------------------------------------------------------------------
# Phase 93：GitHub OIDC 與部署角色（design6 §6 最後一列、§8 錯誤表第 9 列、D16）
#
# 這四顆掃的是 deploy/aws/ 底下的 JSON（前三顆掃本 phase 那兩份，第四顆掃**全部**）——它們是「鑰匙」的形狀，
# 而鑰匙配錯的後果沒有任何執行期訊號：CD 一樣會跑、一樣會紅在
# configure-aws-credentials 那一步，訊息只說「Not authorized」，
# 不會告訴你是 sub 寫成了萬用字元、還是 aud 打錯字。
#
# ⚠ 這幾顆**不連 AWS**（只讀本機檔案），所以三個死埠一起指也不會變顆數。
# ---------------------------------------------------------------------------

部署目錄 = 專案根目錄 / "deploy" / "aws"

# 總覽 §10 追認項 b：分支是 main（design6 §6 寫的 master 是筆誤）。
# 這一串是契約——Phase 94 的 workflow 也靠它才換得到憑證。
# 前綴含 GitHub 的擁有者 ID 與 repo ID（2026-07-15 起新 repo 的不可變主體格式；§4.3 的框有查證與比對指令）。
GITHUB_OIDC_SUB = "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"
GITHUB_OIDC_AUD = "sts.amazonaws.com"

# 12 位純數字 ＝ AWS 帳號 ID 的長相。前後加 \b（詞界）才不會把
# 更長的數字串的其中 12 位誤判成帳號。
帳號ID的長相 = re.compile(r"\b\d{12}\b")


def 信任文件() -> dict:
    """讀 deploy/aws/github-oidc-trust.json 並解析成 dict。

    用 json.loads 而不是字串比對：這樣「條件寫在 StringLike 而不是 StringEquals」
    這種**結構**上的錯誤才抓得到——字串比對只看得到有沒有那幾個字。
    """
    return json.loads((部署目錄 / "github-oidc-trust.json").read_text(encoding="utf-8"))


def test_OIDC信任文件的sub逐字鎖住main分支():
    """design6 §8 錯誤表第 9 列：trust 必須釘 repo ＋ branch。

    為什麼一定要 StringEquals：
      StringLike ＋ "repo:1104030360@92135456/personalDocAI@1349196211:*" 會涵蓋
        repo:1104030360@92135456/personalDocAI@1349196211:pull_request        <- 任何人開 PR
        repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/任何分支
        repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/tags/任何 tag
      也就是說，任何能在這個 repo 觸發 workflow 的分支／PR／tag，都能拿到
      可以推 ECR、可以對那台 EC2 下指令的 AWS 憑證。
    """
    語句 = 信任文件()["Statement"]
    assert len(語句) == 1, f"信任文件應該只有一條 Statement，現在有 {len(語句)} 條"
    條件 = 語句[0]["Condition"]

    assert "StringLike" not in 條件, (
        "sub 必須用 StringEquals 逐字比對。StringLike 會允許萬用字元，"
        "等於任何分支／任何 PR 都借得到這個角色（design6 §8 第 9 列）"
    )
    assert 條件["StringEquals"]["token.actions.githubusercontent.com:sub"] == GITHUB_OIDC_SUB


def test_OIDC信任文件沒有星號萬用字元():
    """整份文件連一個 * 都不准出現——不只是 sub 那一格。

    掃**整份原始文字**而不是只看 sub 的理由：萬用字元可以躲在很多地方
    （Principal 的 ARN、Action 寫成 sts:*、多一條 Sid 帶星號的 Statement）。
    trust policy 本來就沒有任何一格「合法地需要星號」——它沒有 Resource，
    Action 只有一個，Principal 是完整 ARN——所以「整份零星號」是可以成立的
    最強斷言，而且改壞了一定會紅。
    """
    原文 = (部署目錄 / "github-oidc-trust.json").read_text(encoding="utf-8")

    assert "*" not in 原文, (
        "信任文件不可以出現任何萬用字元。要放寬「誰能借這個角色」必須是"
        "產品負責人的決定，不是實作者順手改的（design6 §8 第 9 列：不准合併）"
    )


def test_OIDC信任文件的aud是sts():
    """aud ＝「這張令牌是簽給誰用的」，鎖住它才擋得掉「拿別處的令牌來換 AWS 憑證」。

    順便把另外兩件事一起釘住（它們錯了症狀一樣難查）：
      - Principal 必須是 Federated，而且指向 GitHub 的那個 provider
      - Action 必須是 sts:AssumeRoleWithWebIdentity（寫成 sts:AssumeRole 永遠換不到）
    """
    語句 = 信任文件()["Statement"][0]

    assert 語句["Condition"]["StringEquals"]["token.actions.githubusercontent.com:aud"] == (
        GITHUB_OIDC_AUD
    )
    assert 語句["Action"] == "sts:AssumeRoleWithWebIdentity", (
        "OIDC 換憑證的動作是 AssumeRoleWithWebIdentity；sts:AssumeRole 是給 AWS 內部身分用的"
    )
    assert 語句["Principal"]["Federated"].endswith(
        ":oidc-provider/token.actions.githubusercontent.com"
    ), "Principal 必須指向 GitHub Actions 的 OIDC provider"
    assert 語句["Effect"] == "Allow"


def test_部署用的policy裡沒有寫死帳號ID():
    """總覽 §7 鐵律 10：policy JSON 的帳號 ID 一律用 <ACCOUNT_ID> 佔位。

    掃的是 deploy/aws/ 底下**全部**的 .json（總覽 §10.2 的追加裁決）：
    82 的 mac-policy.json、84 的 s3-lifecycle.json、91 的 worker-role-*.json、
    本 phase 的兩份——之後再多一份也自動納入，不必回來改測試。

    帳號 ID 本身不算機密（ARN 到處都是它），但把它寫死進版控有兩個實際壞處：
      1. 換帳號／重開帳號（Free plan 滿 6 個月會關帳）時要逐檔搜尋取代
      2. 這個 repo 哪天轉成 public，帳號 ID 就永遠留在 git 歷史裡（改不掉）
    做法是「檔案裡永遠是佔位符，要送給 AWS 的時候才用 sed 展開到 /tmp」。
    """
    檔案們 = sorted(部署目錄.glob("*.json"))
    名稱們 = {檔.name for 檔 in 檔案們}
    assert {"github-oidc-trust.json", "github-deploy-policy.json"} <= 名稱們, (
        f"deploy/aws/ 應該至少有本 phase 的兩份 JSON，現在只有：{sorted(名稱們)}"
    )

    命中: list[str] = []
    for 檔 in 檔案們:
        原文 = 檔.read_text(encoding="utf-8")
        json.loads(原文)  # 順便證明每一份都是合法 JSON（JSON 沒有註解語法，見 §7 陷阱 10）
        命中 += [f"{檔.name}：{疑似}" for 疑似 in 帳號ID的長相.findall(原文)]

    assert 命中 == [], f"deploy/aws/*.json 不可以寫死 12 位數的 AWS 帳號 ID：{命中}"

    # 本 phase 的兩份一定會用到帳號 ID（provider ARN、ECR／實例 ARN），所以佔位符必須在
    for 檔名 in ("github-oidc-trust.json", "github-deploy-policy.json"):
        assert "<ACCOUNT_ID>" in (部署目錄 / 檔名).read_text(encoding="utf-8"), (
            f"{檔名} 應該用 <ACCOUNT_ID> 佔位，而不是真的帳號"
        )
```

**③ 檔頭的 import 要補一行 `json`**（Phase 90 開檔時只用到 `re` 與 `Path`）：

```bash
head -30 tests/integration/test_design6_error_paths.py
```

確認最上面那批 import 裡有這三行；缺 `import json` 就補上去（放在 `import re` 前面，
ruff 的 `I` 規則要求標準函式庫依字母排序）：

```python
import json
import re
from pathlib import Path
```

**④ 先看到紅（TDD 的關鍵一步，不可以跳過）：**

```bash
# 把 sub 故意改成萬用字元版本，看那兩顆會不會紅
python3 - <<'PY'
import pathlib
p = pathlib.Path("deploy/aws/github-oidc-trust.json")
p.write_text(p.read_text().replace(
    '"token.actions.githubusercontent.com:sub": "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"',
    '"token.actions.githubusercontent.com:sub": "repo:1104030360@92135456/personalDocAI@1349196211:*"'))
PY

pytest tests/integration/test_design6_error_paths.py -k OIDC -q
```

**預期：2 顆紅**，訊息長相：

```text
FAILED …::test_OIDC信任文件的sub逐字鎖住main分支 - AssertionError: assert 'repo:1104030360@92135456/personalDocAI@1349196211:*' == 'repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main'
FAILED …::test_OIDC信任文件沒有星號萬用字元 - AssertionError: 信任文件不可以出現任何萬用字元。…
```

```bash
# 改回來（重跑 §4.3 的 heredoc 就好，它是整檔覆寫）
```

- [ ] 親眼看過那兩顆紅了。**沒看過紅的測試，你不知道它有沒有在測東西。**

```bash
# 再驗一次「寫死帳號 ID」那顆也會紅（用一個假的 12 位數字）
python3 - <<'PY'
import pathlib
p = pathlib.Path("deploy/aws/github-deploy-policy.json")
p.write_text(p.read_text().replace("<ACCOUNT_ID>", "000000000000"))
PY

pytest tests/integration/test_design6_error_paths.py -k 帳號ID -q
```

**預期：1 顆紅**，訊息裡看得到 `github-deploy-policy.json：000000000000`。
（這顆掃的是 `deploy/aws/*.json` **全部**——把 82 的 `mac-policy.json` 或 91 的 `worker-role-policy.json`
寫死帳號 ID 一樣會紅，所以之後的 phase 不必各自再寫一顆。）

- [ ] 看過紅了，然後**重跑 §4.4 的 heredoc 把檔案還原**。

**⑤ 全部改回來之後跑綠：**

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

**預期：8 passed** ＝ Phase 90 的 4 顆（`test_Dockerfile有cloud_worker這個target`／
`test_Dockerfile的app階段在最後`／`test_Dockerfile的cloud_worker帶ARG_GIT_SHA`／
`test_compose_yaml沒有新增服務也沒有AWS設定`）＋ 本 phase 的 4 顆（名字見上面的程式碼）。

#### 錯誤表第 9 列「不准合併」在本專案是怎麼落地的

design6 §8 第 9 列寫的是「**不准合併**」。本專案是單人 repo、沒有 PR 流程，
所以「不准合併」的等價落地是**三道**：

| 道 | 機制 | 什麼時候擋 |
|---|---|---|
| 1 | 本機 `pytest -q` | 改壞了 trust JSON，全量測試就紅 |
| 2 | pre-commit hook | hook 只跑 ruff（不跑 pytest），**擋不到這個**——所以第 3 道才是真正的守門員 |
| 3 | **CI（`.github/workflows/test.yml`）** | `git push` 之後 GitHub 跑 `pytest -q`，這 4 顆在裡面。紅了 → Actions 顯示紅色 × → 那個 commit 不算通過 → **而且 Phase 94 的 CD 是綁 `test` 成功才跑的，所以 CD 根本不會啟動** |

**第 3 道是關鍵：** trust 被改壞的那次 push，CI 會紅，`workflow_run` 的
`conclusion` 就不是 `success`，deploy 這個 workflow 的 `if` 條件不成立 → **不部署**。
也就是說：**鑰匙被改壞的那一刻，自動部署就自己停了**，不必靠人記得。

### 4.8 更新 `CLAUDE.md` 的 AWS 指令小段

Phase 82 §4.10 在「指令」段建了 `# ── AWS（增量六 Phase 82 起）` 那一段，Phase 92 又在它後面加了「雲端工人（EC2）」的指令。
在 **AWS 這一整段的最後面**追加下面這幾行（**只寫變數名，不寫值**）：

````text
# ── 部署角色（Phase 93）─────────────────────────────────────────
# GitHub Actions 用 OIDC 換臨時憑證，GitHub 上**沒有**存任何 AWS 金鑰。
# 角色名 personaldocai-github-deploy；它的 ARN 放在 repo secret AWS_DEPLOY_ROLE_ARN。
# 兩份 JSON 在 deploy/aws/（帳號 ID 用 <ACCOUNT_ID> 佔位，要用時 sed 展開到 /tmp）：
aws iam get-role --role-name personaldocai-github-deploy \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals'
# 預期：aud=sts.amazonaws.com、sub=repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
gh secret list      # 預期看得到 AWS_DEPLOY_ROLE_ARN（看得到名字，看不到值）
````

- [ ] 貼進去了，而且**沒有**把帳號 ID、實例 ID、role ARN 的真值寫進去。

### 4.9 全量回歸與 commit

```bash
# 1) 全量
pytest -q
# 預期：666 passed ＋ 0 skipped（開工基線 662 ＋ 4）

# 2) 零依賴實證（三個死埠一起指，顆數必須完全相同）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
# 預期：顆數一模一樣（本 phase 的 4 顆只讀本機檔案，本來就不連網）

# 3) 端點仍是 22（本增量恆為 22）、零 DELETE
python3 - <<'EOPY'
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    paths = c.get("/openapi.json").json()["paths"]
    運算元 = [(p, m) for p, item in paths.items() for m in item]
    print("端點數 =", len(運算元))
    print("DELETE 數 =", sum(1 for _, m in 運算元 if m == "delete"))
EOPY
# 預期：端點數 = 22 / DELETE 數 = 0

# 4) 格式與 lint（CI 跑的那兩句）
ruff format --check app tests scripts && ruff check app tests scripts

# 5) 該零改動的：CI 契約（D16）、規格區、產品碼
git diff --stat -- .github/workflows/test.yml    # 預期：無輸出
git status --short docs/spec/                    # 預期：無輸出
git status --short -- app/ compose.yaml Dockerfile db/ requirements.txt
# 預期：與開工前完全相同

# 6) 本 phase 到底多了哪些檔
git status --short -- deploy/ tests/ CLAUDE.md
# 預期：?? deploy/aws/github-oidc-trust.json
#       ?? deploy/aws/github-deploy-policy.json
#        M tests/integration/test_design6_error_paths.py
#        M CLAUDE.md

# 7) 確認 /tmp 那兩份展開檔沒有被誤加進來（它們含真實帳號 ID）
git status --short | grep -i rendered
# 預期：完全沒有輸出（它們在 /tmp，本來就不在 repo 裡）
```

- [ ] 七項全部符合預期。

**Commit（產品負責人指示才做；本專案 commit 節奏由產品負責人決定）：**

```bash
git add deploy/aws/github-oidc-trust.json deploy/aws/github-deploy-policy.json \
        tests/integration/test_design6_error_paths.py CLAUDE.md
git commit -m "$(cat <<'EOF'
feat: GitHub OIDC 部署角色（sub 逐字鎖 main，零長期金鑰）

建 IAM OIDC provider（thumbprint 不填——AWS 現在用自己的可信 CA 清單）
與角色 personaldocai-github-deploy；trust 用 StringEquals 把 sub 鎖成
repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main（GitHub 不可變主體格式）、aud 鎖 sts.amazonaws.com，
整份零萬用字元。權限只有 ECR push、對那一台實例的 ssm:SendCommand
（實例 ARN ＋ AWS-RunShellScript 兩個資源）、ec2:DescribeInstances。
帳號 ID 一律 <ACCOUNT_ID> 佔位，用時 sed 展開到 /tmp。
test_design6_error_paths.py +4（662 → 666）。
EOF
)"
```

> ⚠️ **不要自己把 `unfinish/` 搬進 `finish/`。** 歸檔隨 commit 執行，
> 時機由產品負責人決定（總覽 §7 鐵律 12；Phase 95 §4.9 才處理整批歸檔）。

---

## 5. ASCII 圖

### 5.1 信任鏈：一次 CD 是怎麼證明「我是誰」的

```text
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ GitHub（跑在 GitHub 的一台 Ubuntu 上，**沒有**任何 AWS 金鑰）                  │
 │                                                                                │
 │   workflow 宣告  permissions: id-token: write     ← 沒有這一行就拿不到令牌      │
 │        │                                                                       │
 │        ▼                                                                       │
 │   GitHub 的 OIDC 發證所簽出一張 JWT（只對這一次執行有效，幾分鐘就過期）        │
 │     iss = https://token.actions.githubusercontent.com   誰簽的                 │
 │     aud = sts.amazonaws.com                             簽給誰用的             │
 │     sub = repo:1104030360@92135456/personalDocAI@1349196211                    │
 │           :ref:refs/heads/main                    在描述誰（前綴＋分支）       │
 └───────────────────────────────┬────────────────────────────────────────────────┘
                                 │ ① 把 JWT 交給 AWS
                                 │    sts:AssumeRoleWithWebIdentity
                                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ AWS STS                                                                        │
 │   ② 這張 JWT 是誰簽的？→ 找帳號裡有沒有登記這個 issuer                         │
 │        └─► IAM OIDC identity provider（§4.2 建的，整個帳號一個）               │
 │              url = token.actions.githubusercontent.com                         │
 │              簽章用發證所的公鑰驗（AWS 自己維護可信 CA 清單，不必填 thumbprint）│
 │   ③ 這張 JWT 能借哪個角色？→ 看角色的 trust policy                             │
 │        └─► personaldocai-github-deploy 的 github-oidc-trust.json（§4.3）       │
 │              Principal.Federated  = …:oidc-provider/token.actions.…            │
 │              Action               = sts:AssumeRoleWithWebIdentity              │
 │              StringEquals aud     = sts.amazonaws.com          ← 逐字          │
 │              StringEquals sub     = repo:…:ref:refs/heads/main ← 逐字，零星號   │
 │                                                                                │
 │        ✅ 兩個 StringEquals 都對上 → 發臨時憑證（最多 1 小時）                  │
 │        ❌ 差一個字 → AccessDenied：                                            │
 │           "Not authorized to perform sts:AssumeRoleWithWebIdentity"            │
 └───────────────────────────────┬────────────────────────────────────────────────┘
                                 │ ④ 拿著臨時憑證去做事
                                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ 能做什麼？→ 角色的權限 policy（github-deploy-policy.json，§4.4）恰好五段        │
 │                                                                                │
 │   ecr:GetAuthorizationToken          Resource *          （拿 registry 登入票） │
 │   ecr: 六個推映像動作                 Resource …repository/personaldocai-worker │
 │   ssm:SendCommand                    Resource 那台實例 ＋ AWS-RunShellScript    │
 │   ssm:GetCommandInvocation           Resource *          （查跑完了沒）         │
 │   ec2:DescribeInstances              Resource *          （開著沒）             │
 │                                                                                │
 │   ⛔ 沒有的：ec2:StartInstances／StopInstances（開關機是人做的）                │
 │              iam:*（不准改權限）／s3:*（CD 不碰寄物櫃）                         │
 │              任何 managed policy（不掛 PowerUserAccess 這種）                   │
 └────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 本 phase 在整條 CD 上的位置（94 才把門裝上）

```text
   git push origin main ──► Actions「test」(既有 CI，D16 一字不改) ──綠──►
        Actions「deploy」（★ Phase 94 才寫這個檔）
             ├─ 換憑證  ◄──── ★ 本 phase（93）準備的就是這一格
             │     secrets.AWS_DEPLOY_ROLE_ARN ＋ trust 的兩個 StringEquals
             ├─ buildx  linux/arm64  target=cloud-worker      ← 94
             ├─ push ECR  <sha> ＋ latest                     ← 94
             └─ ssm send-command  systemctl restart           ← 94

   本 phase 做完之後，GitHub 上**還沒有任何 CD**。這是刻意的：
   先確認鑰匙配得起來（4 顆掃碼綠），再裝門（94）。
```

---

## 6. 驗收清單

- [ ] **★G3 已由產品負責人明示通過**（本檔最上面的門檻框；實作者不得自行勾選）
- [ ] OIDC provider 存在且 audience 正確

  ```bash
  aws iam get-open-id-connect-provider \
    --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" \
    --query '{Url:Url, Audiences:ClientIDList}'
  # 預期：{"Url": "token.actions.githubusercontent.com", "Audiences": ["sts.amazonaws.com"]}
  ```

- [ ] 角色的 trust 逐字鎖住 `main`

  ```bash
  aws iam get-role --role-name personaldocai-github-deploy \
    --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals'
  # 預期：aud = sts.amazonaws.com
  #       sub = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
  ```

- [ ] trust 的 `sub` ＝ GitHub 給這個 repo 的前綴 ＋ `:ref:refs/heads/main`（§4.3 的框；前綴變了兩邊要一起改）

  ```bash
  gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub --jq .sub_claim_prefix
  python3 -c "import json;print(json.load(open('deploy/aws/github-oidc-trust.json'))['Statement'][0]['Condition']['StringEquals']['token.actions.githubusercontent.com:sub'])"
  # 預期：第二行 ＝ 第一行 ＋ ':ref:refs/heads/main'（不相等＝CD 永遠換不到憑證）
  ```

- [ ] 角色的權限恰好五段、沒有多給

  ```bash
  aws iam get-role-policy --role-name personaldocai-github-deploy \
    --policy-name personaldocai-github-deploy-policy \
    --query 'PolicyDocument.Statement[].{Sid:Sid,Action:Action}'
  # 預期：五段，Sid 依序 EcrLoginTokenIsAccountWide／EcrPushOnlyToTheWorkerRepository／
  #       SsmRestartOnlyThatOneInstance／SsmReadTheCommandResult／
  #       DescribeInstancesToSeeIfItIsRunning
  ```

- [ ] 角色**沒有**掛任何 managed policy（＝沒有人偷偷加 PowerUserAccess）

  ```bash
  aws iam list-attached-role-policies --role-name personaldocai-github-deploy \
    --query 'AttachedPolicies' --output json
  # 預期：[]
  ```

- [ ] GitHub secret 在

  ```bash
  gh secret list
  # 預期：AWS_DEPLOY_ROLE_ARN 那一列（看得到名字，看不到值）
  ```

- [ ] 兩份 JSON 都在版控裡，而且**帳號 ID 是佔位符**；**4 顆新測試全綠且每顆都看過紅**
      （§4.7 ④做過兩輪反向驗證）；全量顆數 ＝ 基線 ＋ 4；端點仍 22、零 DELETE；
      三死埠零依賴實證顆數相同；ruff 兩句 exit 0

  ```bash
  grep -c '<ACCOUNT_ID>' deploy/aws/github-oidc-trust.json deploy/aws/github-deploy-policy.json
  # 預期：…trust.json:1   …policy.json:2
  grep -nE '\b[0-9]{12}\b' deploy/aws/*.json          # 預期：完全沒有輸出
  pytest tests/integration/test_design6_error_paths.py -v   # 預期：8 passed（90 的 4 ＋ 本 phase 的 4）
  pytest -q                                            # 預期：666 passed ＋ 0 skipped（基線 ＿＿＿ → 完成 ＿＿＿）
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q         # 預期：顆數完全相同
  ruff format --check app tests scripts && ruff check app tests scripts   # 預期：exit 0
  ```

- [ ] **該零改動的都零改動**：`test.yml`（D16）、`docs/spec/`、產品碼、專案 `data/`

  ```bash
  git diff --stat -- .github/workflows/test.yml        # 預期：無輸出
  git status --short docs/spec/                        # 預期：無輸出
  git status --short -- app/ compose.yaml Dockerfile db/ requirements.txt data/
  # 預期：與開工前完全相同（本 phase 不該讓它多出任何一行）
  find data/staging -type f -mmin +1440 2>/dev/null | head    # 預期：無輸出
  ```

- [ ] **EC2 全程沒有被開機**（本 phase 完全不需要它）；**沒有產生任何 AWS 費用**（IAM 全免費）

  ```bash
  aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" \
    --region "$AWS_REGION" --query 'Reservations[0].Instances[0].State.Name' --output text
  # 預期：stopped
  ```

- [ ] **沒有自行 commit、沒有把 `unfinish/` 搬進 `finish/`**（除非產品負責人指示）

---

## 7. 常見陷阱

1. **`sub` 少一段或多一段，症狀完全一樣：`Not authorized to perform sts:AssumeRoleWithWebIdentity`。**
   **症狀：** Phase 94 的 CD 每次都紅在 `configure-aws-credentials` 那一步，訊息只有那一句。
   **原因：** GitHub 組出來的 `sub` 與你鎖的字串差一個字。最常見的三種差法：
   - **前綴用了舊格式**（沒有 `@ID`，也就是 design6 §6 那種 `repo:OWNER/REPO:…` 寫法）：本 repo 是 2026-07-15 之後建的，
     GitHub 簽出來的前綴是 `repo:1104030360@92135456/personalDocAI@1349196211`，少了 ID 就永遠對不上（§4.3 的框）
   - 寫成 `…:refs/heads/main`（**漏了中間的 `ref:`**）
   - 寫成 `…:ref:refs/heads/master`（照抄 design6 §6 的筆誤）
   - 大小寫打錯（`personaldocai` vs `personalDocAI`）——**`sub` 是大小寫敏感的**
   **正解：** 先用 `gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub --jq .sub_claim_prefix`
   拿到前綴（不必跑任何 workflow）。還是對不上時，**讓 GitHub 自己告訴你它送了什麼**：在 Phase 94 的 workflow
   臨時加一步印出來（**驗完就刪掉**；只印 `iss`／`aud`／`sub` 三個欄位，**不要把整張令牌印出來**——它是 5 分鐘內有效的憑證）：

   ```yaml
   - name: debug the OIDC subject (刪掉我)
     run: |
       RESP=$(curl -sS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
         "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com")
       python3 - "$RESP" <<'PY'
       import base64, json, sys
       token = json.loads(sys.argv[1])["value"]
       payload = token.split(".")[1]                    # JWT 的第二段＝claims
       payload += "=" * (-len(payload) % 4)              # base64url 不帶補位的 =，自己補
       claims = json.loads(base64.urlsafe_b64decode(payload))
       print({k: claims.get(k) for k in ("iss", "aud", "sub")})
       PY
   ```

   為什麼不用 `base64 -d`：JWT 用的是 base64**url**（`-`／`_` 取代 `+`／`/`，而且不補 `=`），
   `base64 -d` 會直接回 `invalid input`，什麼都印不出來。
   把印出來的 `sub` 逐字貼進 trust JSON 即可。

2. **`ssm:SendCommand` 只給了實例 ARN，忘了給 document ARN（或反過來）。**
   **症狀：** build 與 push 都成功，最後一步 `aws ssm send-command` 回
   `An error occurred (AccessDeniedException)`，而 policy 看起來「明明有給 SendCommand」。
   **原因：** SSM 的 `SendCommand` 會**同時**檢查兩種資源：對哪台機器下、用哪份劇本。
   **兩個都要在 `Resource` 清單裡。**
   **正解：** §4.4 第 3 段那個兩元素的 `Resource` 陣列，一個都不能少。
   另外 `arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript` 中間**是兩個冒號**
   （AWS 擁有的公開 document，帳號欄是空的）——填自己的帳號進去一樣 AccessDenied。

3. **照 2021〜2023 年的教學填 thumbprint。**
   **症狀：** 一開始好好的，某一天 GitHub 換憑證，所有 CD 同時掛掉，
   訊息是憑證驗證失敗，而你什麼都沒改。
   **原因：** 那些教學寫的 `6938fd4d98…` 是當年**必填**時代的雜湊。
   **正解：** 本專案**不填**。AWS 官方文件（§4.2 引的原文）已經明說：
   AWS 用自己的可信根 CA 清單驗 JWKS 端點的 TLS 憑證，**只有**對方憑證不在清單裡時
   才退回用 thumbprint。GitHub 的憑證是公開可信 CA 簽的，走不到那條路。

4. **`${{ secrets.X }}` 與 `${{ vars.X }}` 寫反，而且不會報錯。**
   **症狀：** workflow 的某個值變成空字串，指令用空的參數繼續跑，錯誤訊息完全對不上題
   （例如 `aws ec2 describe-instances --instance-ids ""` 回一個看不懂的 validation error）。
   **原因：** GitHub 對不存在的 secret／variable **回空字串，不報錯**。
   **正解：** 記住本專案的分工——
   `AWS_DEPLOY_ROLE_ARN` 是 **secret**（`${{ secrets.… }}`，本 phase 放的）；
   `EC2_WORKER_INSTANCE_ID` 是 **variable**（`${{ vars.… }}`，Phase 94 放的）。
   Phase 94 的 bash 第一件事就是「值是空的就印 notice 然後 `exit 0`」，
   就是為了讓這種錯**大聲**一點。

5. **`aws iam …` 回 `AccessDenied`，於是想去放寬 `mac-policy.json`（或回頭用 root）。**
   **症狀：** §4.2／§4.5 的指令回 `AccessDenied`，可是 Phase 82 明明建了掛 `AdministratorAccess` 的 admin。
   **原因：** 十之八九是 `set -a; . ./.env; set +a` 把 `.env` 裡**程式用**的 `personaldocai-mac` key 載進了環境變數，
   而 AWS CLI 的憑證搜尋順序是**環境變數 → `~/.aws/credentials`**，環境變數贏——指令就變成最小權限的 mac 在跑。
   `aws sts get-caller-identity --query Arn --output text` 結尾是 `user/personaldocai-mac` 就是這個。
   **正解：** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`（§4.1 那一行）再重跑。結尾已是 `user/personaldocai-admin`
   卻仍被拒 → 回 Phase 82 §4.5 確認 `AdministratorAccess` 有掛上。**不要**放寬 `mac-policy.json`——
   那份是「這台 Mac 日常在用」的權限，放寬了就收不回來，而且它是 Phase 95 掃碼的對象之一；也**不要**用 root。

6. **把 `/tmp/*.rendered.json` 加進 git。**
   **症狀：** `test_部署用的policy裡沒有寫死帳號ID` 不會紅（它只掃 `deploy/aws/`），
   但你的帳號 ID 與實例 ID 就永遠留在 git 歷史裡了——**改不掉，只能重寫歷史**。
   **原因：** 展開後的檔案含真值。`.gitignore` 管不到專案外的路徑，
   但如果有人把它們複製回專案裡就會被 `git add .` 掃進去。
   **正解：** 展開結果**只寫 `/tmp`**，永遠不要複製回專案。
   §4.9 第 7 項那個 `git status --short | grep -i rendered` 就是在守這件事。

7. **建了角色卻忘了 `put-role-policy`，於是角色「借得到但什麼都不能做」。**
   **症狀：** `configure-aws-credentials` 那一步**綠了**（憑證換到了），
   下一步 `amazon-ecr-login` 才紅，訊息是 `ecr:GetAuthorizationToken` AccessDenied。
   **原因：** `create-role` 只建了「誰能借」，沒有建「能做什麼」——兩份是分開的。
   **正解：** §4.5 的兩個指令要**都跑**。驗收用
   `aws iam get-role-policy … --query 'PolicyDocument.Statement[].Sid'`，
   看得到五個 Sid 才算數。

8. **`file://` 的斜線數錯。**
   **症狀：** `Error parsing parameter '--assume-role-policy-document': Unable to load paramfile`。
   **原因：** AWS CLI 的 `file://` 後面直接接路徑。**絕對路徑**是 `file:///tmp/x.json`
   （`file://` ＋ `/tmp/x.json` ＝ **三條斜線**）；相對路徑是 `file://x.json`（兩條）。
   **正解：** 本檔一律用絕對路徑（三條斜線），因為指令可能在任何目錄執行。

9. **以為「trust 沒有 `Resource` 是寫漏了」，於是加一個 `"Resource": "*"`。**
   **症狀：** `test_OIDC信任文件沒有星號萬用字元` 紅，而且 AWS 也可能回
   `MalformedPolicyDocument`。
   **原因：** trust policy（resource-based policy 的一種）**本來就沒有 `Resource` 欄位**——
   它掛在角色身上，資源就是那個角色自己。
   **正解：** 照 §4.3 的樣子，六個 key 就是全部：`Sid`／`Effect`／`Principal`／
   `Action`／`Condition`（＋最外層的 `Version`）。

10. **在 `deploy/aws/*.json` 裡寫註解。**
    **症狀：** `json.loads` 直接炸 `JSONDecodeError`，四顆測試同時紅。
    **原因：** **JSON 沒有註解語法**（`//` 與 `#` 都不行）。
    **正解：** 要解釋就寫在**本計畫檔**與 `CLAUDE.md`，或用 `Sid` 當標籤——
    §4.4 那五個又長又白話的 `Sid`（`EcrPushOnlyToTheWorkerRepository` 之類）
    就是拿來當註解用的，AWS 不會用它做判斷。

11. **以為「放了 secret，任何 workflow 都讀得到」——fork 來的 PR 讀不到，`workflow_run` 讀得到。**
    **症狀：** 有人從 fork 開 PR，那個 PR 的 workflow 裡 `${{ secrets.AWS_DEPLOY_ROLE_ARN }}` 是空字串。
    **原因：** GitHub 刻意**不把 secrets 交給 fork 來的 `pull_request` 執行**（防止別人用一個 PR 把你的 secret 撈走）。
    反過來，由 `workflow_run` 啟動的 workflow（Phase 94 的 `deploy`）**拿得到** secrets——GitHub 事件表原句：
    *"The workflow started by the `workflow_run` event is able to access secrets and write tokens, even if the previous workflow was not."*
    **正解：** 這是保護，不是 bug，什麼都不用改。本專案的 CD 只在 `main` 上、由 `workflow_run` 啟動，讀得到 secret；
    就算哪天 repo 轉 public 有人從 fork 開 PR，他既拿不到 secret，`sub` 也是 `…:pull_request` 而被 trust 的 `StringEquals` 擋掉——兩道鎖各擋一次。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 多了什麼 |
|---|---|
| AWS（IAM） | 一個 OIDC identity provider（指向 GitHub）＋ 一個角色 `personaldocai-github-deploy`（trust ＋ 一份 inline policy）。**全部免費** |
| GitHub | 一個 repository secret `AWS_DEPLOY_ROLE_ARN` |
| repo | `deploy/aws/github-oidc-trust.json`、`deploy/aws/github-deploy-policy.json`（帳號 ID 用佔位符）；`tests/integration/test_design6_error_paths.py` +4 顆；`CLAUDE.md` 多三行 |

**對外行為變了沒：完全沒有。**

- 端點仍是 **22**、openapi 仍**零 DELETE**。
- `POST /photos` 仍是 **202**，回應仍是三鍵。
- 前端零改動、`compose.yaml` 零改動、`Dockerfile` 零改動、正式庫零改動。
- **GitHub 上還沒有任何 CD**——push 之後仍然只有 `test` 那一顆 job 在跑。

**顆數：**

| | 顆數 |
|---|---|
| 開工基線（Phase 92 之後） | **662** ＋ 0 skipped |
| 本 phase 新增 | **+4**（全部在 `tests/integration/test_design6_error_paths.py`） |
| 完成後 | **666** ＋ 0 skipped |

與總覽 §2.7／§9 的 Phase 93 那一列**完全一致（+4）**，沒有多加也沒有少加。
（累計：**662 → 666**，與總覽 §9 一致。）

**下一個 phase：** `phase-94-CD工作流程.md`——把 `.github/workflows/deploy.yml` 寫出來
（`workflow_run` 綁 `test` → OIDC → QEMU ＋ buildx → `linux/arm64` → ECR `<sha>` ＋ `latest`
→ SSM 重啟），追加 6 顆掃碼測試（666 → 672），並做 **Demo 3**。
Phase 94 會用到本 phase 的兩樣東西，名字不要改：

- GitHub repository secret **`AWS_DEPLOY_ROLE_ARN`**（`${{ secrets.AWS_DEPLOY_ROLE_ARN }}`）
- IAM 角色 **`personaldocai-github-deploy`**（它的 policy 決定 Phase 94 能做哪三件事）

---

## 附：本文件引用的官方文件

- [Create an OpenID Connect (OIDC) identity provider in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
  ——§4.2 的 thumbprint 查證結論出自這一頁的 Note（AWS 用自己的可信根 CA 清單驗 JWKS 端點）
- [AWS CLI `iam create-open-id-connect-provider`](https://docs.aws.amazon.com/cli/latest/reference/iam/create-open-id-connect-provider.html)
  ——synopsis 把 `--thumbprint-list` 放在方括號裡（＝選填），並明文「這個參數是選填的」
- [AWS CLI `iam update-assume-role-policy`](https://docs.aws.amazon.com/cli/latest/reference/iam/update-assume-role-policy.html)（改壞了用它更新 trust，不必刪角色）
- [IAM policy 語法參考](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies.html)
- [IAM JSON policy 的 Condition 元素（`StringEquals` vs `StringLike`）](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html)
- [GitHub OIDC → AWS（官方指南）](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
  ——`sub` 的格式 `repo:octo-org/octo-repo:ref:refs/heads/octo-branch`、
  `permissions: id-token: write` ＋ `contents: read` 都出自這一頁
- [GitHub OIDC 令牌裡有哪些 claim（`sub` 的各種長相）](https://docs.github.com/en/actions/concepts/security/openid-connect)
- [Amazon ECR 需要哪些權限才能推映像](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push.html)
- [SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [SSM 的 IAM 資源與動作參考（`SendCommand` 要同時給實例與 document）](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awssystemsmanager.html)
- [`gh secret set`](https://cli.github.com/manual/gh_secret_set)
- [GitHub OpenID Connect reference（`sub` 各種長相、**Immutable subject claims**）](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)
  ——§4.3 那個框的查證出處：2026-07-15 之後建的 repo 預設用含 ID 的格式，「Update your trust policies to match the format your repository uses」
- [GitHub Changelog 2026-04-23：Immutable subject claims for GitHub Actions OIDC tokens](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)
- [GitHub REST：OIDC subject claim customization（`GET`／`PUT /repos/{owner}/{repo}/actions/oidc/customization/sub`）](https://docs.github.com/en/rest/actions/oidc?apiVersion=2022-11-28)
  ——`sub_claim_prefix`／`use_default`／`include_claim_keys`／`use_immutable_subject` 欄位
- [GitHub：Events that trigger workflows → `workflow_run`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
  ——`GITHUB_REF` ＝ Default branch；`workflow_run` 啟動的 workflow 拿得到 secrets
- [Amazon ECR：推映像需要的 IAM 權限（六個動作 ＋ `GetAuthorizationToken` 用 `*`）](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html)
- [AWS Systems Manager identity-based policy examples（Example 3：`SendCommand` 同時列實例 ARN 與 document ARN；`AWS-*` 公開 document 的 ARN 不填帳號）](https://docs.aws.amazon.com/systems-manager/latest/userguide/security_iam_id-based-policy-examples.html)
