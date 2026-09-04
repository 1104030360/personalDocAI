# Phase 93：GitHub OIDC 與部署角色

> 📌 **2026-09-03 校準（產品負責人拍板；★G3 已通過，本 phase 可以開工）：**
>
> Phase 92 已拆成兩段（總覽 §10.2 追認項 **U**）：**92-A** ＝ CPU 機 `t3.xlarge`
> ＋ `WORKER_VLM_BACKEND=cloud`，**已建好、Demo 2／2b 通過、收工 Stop**（30 GB ≈ $2.9／月，留給 Phase 94 的 Demo 3）；
> **92-B** ＝ GPU 機 `g4dn.xlarge` ＋ `local`，**等 G and VT 配額（`L-DB2E81BA`，現況 0、`CASE_OPENED`）**，測完 Terminate。
> **★G3 在 92-A 之後**，所以本 phase **不必等 GPU 配額**。帳號已升 Paid。
> 本 phase **仍然零 AWS 運算費**（只建 IAM／OIDC，不開機）。
>
> 對本檔的影響（實作時照這幾條，不要照舊的 t4g／只建 arm64／「真機一定是 g4dn」）：
> 1. **★G3 的 Demo 2b 證據仍是 Stop 後 fallback**（設計契約沒變）。
>    93 開工時那台 EC2 **通常是 92-A 留下的 `t3.xlarge`、狀態 stopped**（也可能已被 Terminate）。
>    本 phase **不需要**它 running——stopped、terminated、查無此實例都算過。
> 2. 手動 build 工人映像是 **多架構**（`linux/amd64,linux/arm64`），不是只 `linux/arm64`。
> 3. 看圖失敗要先看啟動行的 `vlm=`：92-A 是 `cloud`（查 `OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL`）、
>    92-B 是 `local`（查 `nvidia-smi`／`ollama`／`VLM_MODEL`）。**兩者皆 x86_64**，多架構那條不變。
> 4. CD **仍然不准** `StartInstances`／`StopInstances`／`TerminateInstances`。開關機與刪機是人做的。

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

> ✅ **本次：已通過（2026-09-03）。**
> 憑據三項：① commit **`c40a3b3`**「docs: Phase 92-A 三份文件與 EC2 手動測試教學」——92-A（`t3.xlarge`）
> 已建好並留下手動測試教學；② `CLAUDE.md` 專案概述已寫「**92-A**（CPU 機 t3.xlarge）已建、**Demo 2／2b 通過**、日常 Stop」；
> ③ dev-prompt `docs/plan/dev-prompts/phase0903-1.md` 由產品負責人**明示執行 Phase 93〜95**。
> 這三項就是下面那張表要的「人看過 Demo 2 與 Demo 2b、同意往下走」的那句話。
> **下面的規則本身保留**（將來重跑、或有人想跳過閘門時，仍以它為準）。

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
| 卡住時怎麼辦 | ① 真機起不來 → 看 `deploy/ec2/user-data.sh`（回 **91／92**）；② 工人起得來但拿不到訊息 → IAM instance role（回 **91**）；③ 拿得到訊息但看圖失敗 → 先看啟動行 `vlm=`：`cloud`（92-A）查 `OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL`；`local`（92-B）查 GPU／Ollama（回 **92**）。⚠ Demo 當下除錯可 Stop；**92-A 收工 Stop、92-B 測完 Terminate**（已拍板） |
| **本次狀態** | **已通過（2026-09-03，產品負責人）**。憑據見本節開頭那個框的三項 |

> 🚦 **閘門是「人」的動作，實作者不可以自己勾掉。** 指令只是**證據**，
> 「看過證據、同意往下走」的那個動作必須由產品負責人做出來——
> 一句明確的話（口頭、對話、或 dev-prompt 檔案）。
> 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
> 「先做下一段，之後再回來補確認」。

---

**為什麼要做這個：**

**現在的痛：** Phase 92 做完之後，改工人的程式碼要做三件事：

1. 在 Mac 上 `docker buildx build --target cloud-worker --platform linux/amd64,linux/arm64 …`
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
| **D16**（CI／CD 分開） | 「現有 GitHub Actions CI 不動契約。CD：CI 綠 → **OIDC 短憑證** → build 多架構映像 → ECR `personaldocai:<git-sha>` → SSM Run Command 在 EC2 上 pull＋重啟」 | 本 phase 只做**「OIDC 短憑證」那一段**：provider ＋ role ＋ 兩份 JSON ＋ GitHub secret。build／push／SSM 的 workflow 是 Phase 94（`linux/amd64,linux/arm64`）。（ECR repository 名稱依總覽 §2.8 是 `personaldocai-worker`；design6 這裡的 `personaldocai` 是簡寫） |
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

- **Phase 74〜92 全部完成**（甲＋乙＋丙＋丁＋戊全段；92-A 已建、Demo 2／2b 已過，92-B 等 GPU 配額，與本 phase 無關）。
- **★ 閘門 G3 已由產品負責人通過**（本檔最上面那張表；**沒過不准開工**）。**2026-09-03 已通過**，憑據見上面的框。
- EC2 實例：**不需要 running**。通常是 92-A 那台 `t3.xlarge` 停著（stopped），也可能已被 Terminate。
  建 IAM／OIDC 不碰那台機器；`.env` 的 `EC2_WORKER_INSTANCE_ID` 留著或留空都行（stopped／terminated 的 ID 對本 phase 無影響）。
- ECR repository `personaldocai-worker` 已存在（Phase 91 建的），而且裡面**已經有手動推上去的映像**。
  2026-09-03 實查有三個 tag：`bb3921a`（**單架構 arm64**，Phase 90／91 推的）、
  `bb3921a-dirty` 與 `latest`（**多架構 manifest：amd64＋arm64**，Phase 92 改判後重推的）。
  本 phase 不推也不刪任何 tag。
- AWS CLI 的 **default profile** 就是 `personaldocai-admin` 那把 key（Phase 82 §4.7 用 `aws configure` 設的）。
  ⚠ **這台 Mac 上沒有叫 `personaldocai-admin` 的具名 profile**——所有 `aws` 指令一律**不要加 `--profile`**，
  加了會噴 `The config profile (personaldocai-admin) could not be found`。
  （本 phase 要建 IAM 東西，最小權限的 `personaldocai-mac` 做不到——它的 key 只在 `.env`，
  而且會被 §4.1 那行 `unset` 丟掉。）
- `gh` 已登入，而且 `origin` 是 `https://github.com/1104030360/personalDocAI.git`。
  ⚠ **這個 repo 是 PUBLIC**（2026-09-03 實查）——所以「不寫值只寫變數名」那條鐵律在本 phase 是硬性的，不是潔癖。
- `docs/plan/aws/` 底下有產品負責人自己寫的**六份新手步驟檔**（含 `2026-09-03-EC2工人手動測試與監控.md`）。
  本 phase **只當對照、一個字都不改**——它們是產品負責人的筆記，不是計畫檔。

### 開工基線（自己再驗一次，不要抄）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 把 .env 帶進來（下面要用 $EC2_WORKER_INSTANCE_ID），然後**立刻**把裡面那把「程式用」的 key 丟掉——
# 環境變數會蓋過 ~/.aws 的 profile，不 unset 的話每一條 aws 指令都變成最小權限的 personaldocai-mac 在跑
# （Phase 82 §7 陷阱 1 的規矩；每個要讀 .env 的 phase 都一樣）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

pytest -q
# 預期尾巴：692 passed，而且沒有 skipped
# ⚠ 這個數字比總覽 §9 的「累計 662」大 30，兩個都沒錯，只是算法不同：
#   總覽 §9 的絕對值只保證「本 phase 新增幾顆」，不保證累計對得上實查
#   （§9 自己在 Phase 75 那列就註明過「實查 +12、之後各列絕對值一律 +2」）。
#   Phase 92 本身確實是人工 phase（+0 顆），但產品負責人在 commit `f2fc067`
#   補了 2 顆 unit／user-data 掃碼（見下面那條 --collect-only），所以
#   `test_design6_error_paths.py` 現在是 **6 顆**、全量基線是 **692**。
#   本 phase 一律以「692 → 696、檔內 6 → 10」為準。

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

# 本 phase 不需要機器 running（92-A 那台通常是 stopped）：
aws ec2 describe-instances --region ap-northeast-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].InstanceId' --output text
# 預期：空。不准是 running。
# 若 .env 還留著 92-A 的 ID：describe 那一筆應為 stopped（或已 terminate／InvalidInstanceID.NotFound）

ls deploy/aws/
# 預期看得到：mac-policy.json（82）、worker-role-trust.json、worker-role-policy.json（91）
#             s3-lifecycle.json（84）
# 本 phase 會在同一個目錄多兩份

ls docs/plan/aws/
# 預期：看得到產品負責人的六份新手步驟檔（含 2026-09-03-EC2工人手動測試與監控.md）
# 本 phase 只當對照，不改它們

pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：6 tests collected
# 這 6 顆是：Phase 90 放的 4 顆
#   test_Dockerfile有cloud_worker這個target
#   test_Dockerfile的app階段在最後
#   test_Dockerfile的cloud_worker帶ARG_GIT_SHA
#   test_compose_yaml沒有新增服務也沒有AWS設定
# ＋ 產品負責人在 commit f2fc067 補的 2 顆
#   test_unit檔與user_data內嵌段逐字相同
#   test_unit只在local才等本機Ollama
```

把數字填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | ＿＿＿ passed ＋ 0 skipped（應為 **692**；2026-09-03 controller 實查值。總覽 §9 那個「662」是舊的累計推算值，見上面的說明） |
| 開工時 `test_design6_error_paths.py` 顆數 | ＿＿＿（應為 **6**＝Phase 90 的 4 ＋ `f2fc067` 補的 2。總覽 §9 寫的 **4** 是 90 當下的值） |
| EC2 狀態 | ＿＿＿（應為 `stopped`（92-A 留下的 `t3.xlarge`）／`terminated`／查無／空 ID；**不准 running**） |

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
- 更新 `CLAUDE.md` 指令區：在**「雲端工人（EC2）」那一段的最後面**（`# ── 格式與 lint` 之前）
  補一個「部署角色（Phase 93）」小段（§4.8 有逐字內容與插入點）。

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

> ⚠️ **誰做哪一段（2026-09-03 校準；controller 裁決 R3）**
>
> 這個 phase 有兩種工作，**不可以混在一起**：
>
> | 誰 | 做哪幾節 | 為什麼 |
> |---|---|---|
> | **controller（Fable 本人）** | §4.1（載 `.env`／`unset`）、§4.2（建 provider）、§4.3 的 `gh api` 複查、§4.4 的 `sed` 展開、§4.5（建角色）、§4.6（`gh secret set`）、§4.9（全量回歸與 `git status`） | 這些會**真的動到 AWS 與 GitHub 帳號**，而且要用到 `.env` 裡的憑證。實作 subagent 一律**零 `aws`／`gh`／`docker` 指令、零真連線** |
> | **實作 subagent** | §4.3 的**兩份 JSON 內容**、§4.4 的**兩份 JSON 內容**、§4.7（4 顆測試，紅→綠）、§4.8（`CLAUDE.md` 的「部署角色」小段） | 這些只碰 repo 裡的檔案，本機就驗得完（`json.loads` ＋ pytest），不需要任何雲端 |
>
> **執行順序因此是（跟章節編號不同，照這個走）：**
>
> ```text
> ① subagent  §4.3 §4.4  寫出兩份 JSON（只寫檔，不 sed、不打 aws）
> ② subagent  §4.7       追加 4 顆測試 → 故意寫壞 → 看紅 → 還原 → 看綠（10 passed）
> ③ subagent  §4.8       CLAUDE.md 補「部署角色」小段
> ④ controller §4.1 §4.2 載 .env／unset → 建 OIDC provider
> ⑤ controller §4.3 框    gh api 複查 sub 前綴（與 JSON 裡那一串逐字比對）
> ⑥ controller §4.4 §4.5  sed 展開到 $SCRATCH → create-role → put-role-policy
> ⑦ controller §4.6       gh secret set AWS_DEPLOY_ROLE_ARN
> ⑧ controller §4.9       全量回歸、零依賴實證、git status、snapshot-tree 快照相減
> ```
>
> **為什麼倒過來（先測試、後 AWS）：** 這 4 顆掃的是**檔案**不是雲端，
> 所以 JSON 一寫出來就驗得完；而 AWS 那幾步一旦建下去，錯了要 `delete-role` 才回得去。
> 先讓「鑰匙的形狀」被測試釘死，再拿去配鎖，順序反了只是多繞路。
> **測試不是偷懶擺最後**——真正的 TDD 節奏在 §4.7：
> **先把 JSON 故意寫錯一個字、跑測試看它紅、再改回來**（那才是「看過紅」）。

### 4.1 把會用到的值放進這個終端機（不寫進任何檔案）

> 👤 **這一節由 controller 執行**（要載 `.env`，subagent 不碰憑證）。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ★ 展開後的 policy（含真實帳號 ID 與實例 ID）要寫到哪裡：**專案外的暫存目錄**。
#   本輪一律用 agent 的 scratchpad，不用 /tmp——scratchpad 是這個 session 專屬的，
#   而且不需要額外的權限確認。定義一次，下面每一節都用 $SCRATCH：
export SCRATCH=/private/tmp/claude-501/-Users-linjunting-personalDocAI/1f4eca1f-0382-4915-97be-215ebc934bab/scratchpad
mkdir -p "$SCRATCH"
# export 不能省：下面 §4.4 有一句 python3 -c 會讀 os.environ['SCRATCH']，
# 沒 export 的話那是「只有這個 shell 看得到」的變數，子行程拿不到（KeyError）
# ⚠ 這個路徑是**這一次 session 的**。人自己在終端機重做時，換成任何專案外的暫存目錄
#   （例如 /tmp）都可以——唯一的規矩是「展開後的檔案永遠不准落在 repo 裡」。

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
echo "scratch=$SCRATCH"                 # 預期：一個**專案外**的絕對路徑
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

> 👤 **這一節由 controller 執行**（真的會在 AWS 帳號裡建東西）。
> 2026-09-03 實查：**這個帳號目前 OIDC provider ＝ 0 個**，所以底下那個 `if` 一定會走「建立」那條路。

**這是什麼：** 在你的 AWS 帳號裡登記一句話——「我信任
`https://token.actions.githubusercontent.com` 這個發證所簽出來的令牌」。
**整個 AWS 帳號只需要建一次**，之後所有 GitHub 的角色共用同一個 provider。

#### ★ 先查證：2026 年還要不要自己填 thumbprint？

> **結論：不用了。`--thumbprint-list` 是選填的，本專案不填。**
>
> AWS 官方文件（[Create an OIDC identity provider in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)）
> 現在寫著（2026-08-31 以 WebFetch 讀原文，**2026-09-03 校準時再讀一次，原文一字未變**，逐字翻譯）：
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
> 且明文（2026-09-03 複查，原句仍是）：*"This parameter is optional. If it is not included,
> IAM will retrieve and use the top intermediate certificate authority (CA) thumbprint of the
> OpenID Connect identity provider server certificate."*
> ——「**這個參數是選填的。**沒有提供時，IAM 會自己去取得並使用該 OIDC 身分提供者
> 伺服器憑證的**最上層中繼 CA thumbprint**。」
>
> 💡 順帶一提：Console 的「Thumbprints」分頁寫著「一個 IAM OIDC identity provider **至少要有一個**、
> 最多五個 thumbprint」。這跟「不必自己填」**不衝突**——不填的時候是 IAM 自己去抓一個填進去，
> 所以之後在 Console 看到那裡有一筆值是**正常的**，不是有人手動加的。
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

> 🤖 **JSON 內容由 subagent 寫**（純檔案）；框裡那條 `gh api` 複查**由 controller 執行**。

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
> [Changelog 2026-04-23](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)；
> **2026-09-03 校準時以 WebFetch 重讀，三句都還在**）：
> *"Repositories created after July 15, 2026 use the immutable default subject format."* …
> 格式寫成 `repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH`，官方例子是
> `repo:octo-org@123456/octo-repo@456789:ref:refs/heads/main` …
> *"Repository renames and transfers after July 15, 2026 also move to the immutable subject format."* …
> *"Update your trust policies to match the format your repository uses."*
>
> 另外 [GitHub OIDC → AWS 的官方指南](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
> **同一頁現在兩種格式都列**（舊的 `repo:octo-org/octo-repo:ref:…` 與新的 `repo:octo-org@123456/octo-repo@456789:ref:…`），
> 並自己說明「2026-07-15 之後建立、或有開這個功能的 repo」用新格式——所以照那一頁抄範例時
> **要挑對版本**，抄到上面那個舊的就是 §7 陷阱 1 的第一種死法。
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
> ✅ **2026-09-03 controller 又跑了一次同一條唯讀指令：三個欄位逐字相同**（`sub_claim_prefix` 沒有變）。
> 也就是說下面 heredoc 裡那一串 `sub` 現在就是對的——但**動手前仍然要自己再跑一次**（理由見這一段最後）。
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

- [x] 檔案寫好了，而且用 Python 檢查它是合法 JSON、`<ACCOUNT_ID>` 佔位還在：

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

> 🤖 **JSON 內容由 subagent 寫**（純檔案）；底下「用 `sed` 展開」那一小節**由 controller 執行**（要用到真值）。

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
| 5 | `DescribeInstancesToSeeIfItIsRunning` | `ec2:DescribeInstances` | `*` | `ec2:DescribeInstances` **不支援資源層級限制**（EC2 的 `Describe*` 幾乎都是如此；這是 AWS 的限制，不是我們偷懶），寫成實例 ARN 會直接 AccessDenied。同樣是唯讀 |

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

> 👤 **這一小節由 controller 執行**（`$ACCOUNT_ID`／`$EC2_WORKER_INSTANCE_ID` 都是真值）。

檔案裡永遠是佔位符（總覽 §7 鐵律 10），**要送給 AWS 的時候才在管線上換掉**：

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" \
    -e "s|<INSTANCE_ID>|$EC2_WORKER_INSTANCE_ID|g" \
    deploy/aws/github-deploy-policy.json > "$SCRATCH/github-deploy-policy.rendered.json"

sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" \
    deploy/aws/github-oidc-trust.json > "$SCRATCH/github-oidc-trust.rendered.json"
```

> ⚠️ **`<INSTANCE_ID>` 綁的是「現在那一台」——92-B 換機之後這份 policy 會失效。**
> 92-A（`t3.xlarge`）測完 GPU 配額下來時，流程是「Terminate 92-A → 開一台新的 `g4dn.xlarge`」，
> **新機器的實例 ID 一定是新的**。那時候要做兩件事，**少做一件 CD 就會安靜地半殘**：
>
> | 要改什麼 | 指令 | 漏了會怎樣 |
> |---|---|---|
> | ① 這份 policy 裡那台實例 | `.env` 的 `EC2_WORKER_INSTANCE_ID` 改新值 → 重跑上面的 `sed` → **重跑 §4.5 ② 的 `put-role-policy`**（同名直接覆蓋，不必刪角色） | CD 的 build／push 全綠，最後一步 `ssm send-command` 回 `AccessDeniedException`——policy 還指著那台已經不存在的機器 |
> | ② Phase 94 的 GitHub variable | `gh variable set EC2_WORKER_INSTANCE_ID --body "<新的 ID>"` | CD 會對**舊 ID** 下指令，回一個「找不到實例」的錯，而 ECR 上其實已經有新映像了 |
>
> 兩處是**不同的東西**（一個在 AWS 的 policy 裡、一個在 GitHub 的變數裡），
> 換機時**一起改**，而且改完跑一次 Phase 94 的 Demo 3 確認。

`sed` 的旗標：

| 部分 | 用途 |
|---|---|
| `-e` | 「接下來是一句編輯指令」。要換兩種佔位符就寫兩個 `-e` |
| `s\|舊\|新\|g` | `s` ＝ substitute（取代）；`g` ＝ global（同一行出現幾次就換幾次） |
| 為什麼用 `\|` 當分隔符而不是 `/` | ARN 裡有 `/`（`instance/i-xxx`、`repository/personaldocai-worker`）。用 `/` 當分隔符就得逐個跳脫，很容易漏。`\|` 在 ARN 裡不會出現，最安全 |
| 為什麼輸出到 `$SCRATCH`（專案外） | **展開後的檔案含真實帳號 ID 與實例 ID，絕對不能進 repo。** 寫在專案外是刻意的：`git add .` 掃不到、`.gitignore` 也不必為它加規則。本輪 `$SCRATCH` ＝ agent 的 scratchpad（§4.1 定義）；人自己做時用 `/tmp` 也一樣 |

- [ ] 檢查展開結果（**這一步的輸出不要貼進任何文件**）：

```bash
python3 -c "
import json, os
d = json.load(open(os.environ['SCRATCH'] + '/github-deploy-policy.rendered.json'))
for s in d['Statement']:
    print(s['Sid'], '->', s['Resource'])
"
grep -c '<' "$SCRATCH/github-deploy-policy.rendered.json"   # 預期：0（佔位符全換掉了）
```

> ⚠️ 上面那句 `python3 -c` 讀的是 `os.environ['SCRATCH']` ——所以 §4.1 那一行是
> `export SCRATCH=…`（沒 export 就會噴 `KeyError: 'SCRATCH'`）。

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

> 👤 **這一節由 controller 執行。**
> 2026-09-03 實查：**IAM 裡目前沒有 `personaldocai-github-deploy` 這個角色**（只有 91 建的
> `personaldocai-worker-role`），所以是全新建立，不會撞 `EntityAlreadyExists`。

```bash
# ① 建角色（trust policy 就是「誰能借」那一份）
aws iam create-role \
  --role-name personaldocai-github-deploy \
  --assume-role-policy-document "file://$SCRATCH/github-oidc-trust.rendered.json" \
  --description "GitHub Actions CD: push image to ECR and restart the EC2 worker" \
  --max-session-duration 3600
```

每個旗標的用途：

| 旗標 | 用途 |
|---|---|
| `--role-name personaldocai-github-deploy` | 角色名字（總覽 §2.8 定的，逐字沿用） |
| `--assume-role-policy-document file://…` | **trust policy**。`file://` 後面接**絕對路徑**，所以展開後是**三條斜線**（`file://` ＋ `/private/tmp/…`）。`$SCRATCH` 是絕對路徑，所以 `"file://$SCRATCH/x.json"` 展開就對了；**外面的雙引號不要拿掉**（路徑裡有 `-`／`/` 沒關係，但少了引號萬一路徑含空白就會斷成兩個參數） |
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
  --policy-document "file://$SCRATCH/github-deploy-policy.rendered.json"
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
| trust JSON 打錯字 / 不是合法 JSON | `MalformedPolicyDocument` 或 `Error parsing parameter` | 改 `deploy/aws/github-oidc-trust.json` → 重跑 §4.4 的 `sed` → **`aws iam update-assume-role-policy --role-name personaldocai-github-deploy --policy-document "file://$SCRATCH/github-oidc-trust.rendered.json"`**（角色已存在時用這個「更新 trust」的指令，不必刪掉重建） |
| 權限 policy 寫錯 | 同上 | 改檔 → 重跑 `sed` → **再跑一次 `put-role-policy`**（同名會直接覆蓋，這是預期行為） |
| 角色名打錯，建了一個多餘的 | — | `aws iam delete-role-policy --role-name <錯的> --policy-name <那個 policy>` 然後 `aws iam delete-role --role-name <錯的>`。**順序不能反**——inline policy 還在的話 `delete-role` 會失敗（`DeleteConflict`） |
| `EntityAlreadyExists` | 角色已經有了 | 不必刪。改用 `update-assume-role-policy` ＋ `put-role-policy` 把兩份文件更新上去 |
| `AccessDenied` | 這個 shell 還拿著 `personaldocai-mac` 的 key（忘了 §4.1 的 `unset`），或 admin 的 key 沒設進 `aws configure` | 與 §4.2 那列相同：`aws sts get-caller-identity --query Arn --output text` 看現在是誰 → `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 回到 admin 再跑。真的想走 Console（用 `personaldocai-admin` 登入）：IAM → Roles → Create role → Web identity → 選 provider 與 audience → 之後在 **Trust relationships** 分頁貼上完整 trust JSON、在 **Permissions** 分頁 → Add permissions → Create inline policy → JSON 分頁貼上權限 JSON。**不要**放寬 `mac-policy.json` |

**費用影響：**
IAM 的 role、policy、OIDC provider **全部免費**，沒有數量計費、沒有月費。
本 phase **不會產生任何 AWS 運算費用**（OIDC／IAM 角色是免費的）——
帳號已升 Paid，但本 phase 不開機。
它一行 EC2、一 byte S3 都沒有碰。

### 4.6 把角色 ARN 放進 GitHub secret

> 👤 **這一節由 controller 執行。**
> 2026-09-03 實查：`gh secret list` 與 `gh variable list` **兩個都是空的**，
> 所以這是這個 repo 的**第一個** secret。

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
   但也沒必要每次 build 都印在公開的 log 裡——**這個 repo 已經是 PUBLIC**
   （2026-09-03 實查），Actions 的 log 任何人都看得到，所以這一條現在是實質保護，
   不是「以後可能有用」。
3. **一致性。** GitHub 官方的 OIDC 範例就是這樣寫（`role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}`），
   照著走，之後查文件對得起來。

> ⚠️ **注意：`vars` 與 `secrets` 是兩個不同的命名空間。**
> Phase 94 會用 `gh variable set EC2_WORKER_INSTANCE_ID`（**variable**，不是 secret），
> 因為那個值在 workflow 的 bash 裡要拿來組指令、失敗時希望 log 看得到它是什麼。
> 兩者在 workflow 裡的寫法不同（`${{ secrets.X }}` vs `${{ vars.X }}`），**寫錯會拿到空字串**，
> 而且**不會報錯**——bash 會拿一個空的變數繼續跑。這是 §7 陷阱 4。

### 4.7 TDD：4 顆掃碼測試（先看到紅，再看到綠）

> 🤖 **這一節由 subagent 執行**（純本機：讀檔 ＋ pytest，零 AWS、零 `gh`）。

> 📌 這 4 顆追加在 **Phase 90 開的**那個檔 `tests/integration/test_design6_error_paths.py`
> 的最後面。**不要新開檔**（總覽 §10 追認項 B 的裁決：90 開檔、93／94 追加、95 收尾）。

**① 先跑一次，記下現在幾顆：**

```bash
pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：6 tests collected
#   ＝ Phase 90 放的 4 顆（Dockerfile／compose 掃碼）
#   ＋ 產品負責人在 commit f2fc067 補的 2 顆（EC2 unit 與 user-data）
# 該檔的模組 docstring 裡有一張「誰在哪個 phase 加了什麼」的表，Phase 93 那一列
# 已經先寫好了（「GitHub OIDC trust JSON 的掃碼（4 顆…）」）——**不必改那張表**。
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

DEPLOY_AWS_DIR = PROJECT_ROOT / "deploy" / "aws"

# 總覽 §10 追認項 b：分支是 main（design6 §6 寫的 master 是筆誤）。
# 這一串是契約——Phase 94 的 workflow 也靠它才換得到憑證。
# 前綴含 GitHub 的擁有者 ID 與 repo ID（2026-07-15 起新 repo 的不可變主體格式；§4.3 的框有查證與比對指令）。
GITHUB_OIDC_SUB = "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"
GITHUB_OIDC_AUD = "sts.amazonaws.com"

# 12 位純數字 ＝ AWS 帳號 ID 的長相。前後加 \b（詞界）才不會把
# 更長的數字串的其中 12 位誤判成帳號。
ACCOUNT_ID_PATTERN = re.compile(r"\b\d{12}\b")


def read_trust_policy() -> dict:
    """讀 deploy/aws/github-oidc-trust.json 並解析成 dict。

    用 json.loads 而不是字串比對：這樣「條件寫在 StringLike 而不是 StringEquals」
    這種**結構**上的錯誤才抓得到——字串比對只看得到有沒有那幾個字。
    """
    return json.loads((DEPLOY_AWS_DIR / "github-oidc-trust.json").read_text(encoding="utf-8"))


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
    statements = read_trust_policy()["Statement"]
    assert len(statements) == 1, f"信任文件應該只有一條 Statement，現在有 {len(statements)} 條"
    condition = statements[0]["Condition"]

    assert "StringLike" not in condition, (
        "sub 必須用 StringEquals 逐字比對。StringLike 會允許萬用字元，"
        "等於任何分支／任何 PR 都借得到這個角色（design6 §8 第 9 列）"
    )
    assert condition["StringEquals"]["token.actions.githubusercontent.com:sub"] == GITHUB_OIDC_SUB


def test_OIDC信任文件沒有星號萬用字元():
    """整份文件連一個 * 都不准出現——不只是 sub 那一格。

    掃**整份原始文字**而不是只看 sub 的理由：萬用字元可以躲在很多地方
    （Principal 的 ARN、Action 寫成 sts:*、多一條 Sid 帶星號的 Statement）。
    trust policy 本來就沒有任何一格「合法地需要星號」——它沒有 Resource，
    Action 只有一個，Principal 是完整 ARN——所以「整份零星號」是可以成立的
    最強斷言，而且改壞了一定會紅。
    """
    source = (DEPLOY_AWS_DIR / "github-oidc-trust.json").read_text(encoding="utf-8")

    assert "*" not in source, (
        "信任文件不可以出現任何萬用字元。要放寬「誰能借這個角色」必須是"
        "產品負責人的決定，不是實作者順手改的（design6 §8 第 9 列：不准合併）"
    )


def test_OIDC信任文件的aud是sts():
    """aud ＝「這張令牌是簽給誰用的」，鎖住它才擋得掉「拿別處的令牌來換 AWS 憑證」。

    順便把另外兩件事一起釘住（它們錯了症狀一樣難查）：
      - Principal 必須是 Federated，而且指向 GitHub 的那個 provider
      - Action 必須是 sts:AssumeRoleWithWebIdentity（寫成 sts:AssumeRole 永遠換不到）
    """
    statement = read_trust_policy()["Statement"][0]

    assert statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:aud"] == (
        GITHUB_OIDC_AUD
    )
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity", (
        "OIDC 換憑證的動作是 AssumeRoleWithWebIdentity；sts:AssumeRole 是給 AWS 內部身分用的"
    )
    assert statement["Principal"]["Federated"].endswith(
        ":oidc-provider/token.actions.githubusercontent.com"
    ), "Principal 必須指向 GitHub Actions 的 OIDC provider"
    assert statement["Effect"] == "Allow"


def test_部署用的policy裡沒有寫死帳號ID():
    """總覽 §7 鐵律 10：policy JSON 的帳號 ID 一律用 <ACCOUNT_ID> 佔位。

    掃的是 deploy/aws/ 底下**全部**的 .json（總覽 §10.2 的追加裁決）：
    82 的 mac-policy.json、84 的 s3-lifecycle.json、91 的 worker-role-*.json、
    本 phase 的兩份——之後再多一份也自動納入，不必回來改測試。

    帳號 ID 本身不算機密（ARN 到處都是它），但把它寫死進版控有兩個實際壞處：
      1. 換帳號／重開帳號時要逐檔搜尋取代
      2. **這個 repo 已經是 public**，寫進去就等於公開，而且會永遠留在 git 歷史裡（改不掉）
    做法是「檔案裡永遠是佔位符，要送給 AWS 的時候才用 sed 展開到專案外的暫存目錄」。
    """
    json_files = sorted(DEPLOY_AWS_DIR.glob("*.json"))
    names = {path.name for path in json_files}
    assert {"github-oidc-trust.json", "github-deploy-policy.json"} <= names, (
        f"deploy/aws/ 應該至少有本 phase 的兩份 JSON，現在只有：{sorted(names)}"
    )

    hits: list[str] = []
    for path in json_files:
        source = path.read_text(encoding="utf-8")
        json.loads(source)  # 順便證明每一份都是合法 JSON（JSON 沒有註解語法，見 §7 陷阱 10）
        hits += [f"{path.name}：{suspect}" for suspect in ACCOUNT_ID_PATTERN.findall(source)]

    assert hits == [], f"deploy/aws/*.json 不可以寫死 12 位數的 AWS 帳號 ID：{hits}"

    # 本 phase 的兩份一定會用到帳號 ID（provider ARN、ECR／實例 ARN），所以佔位符必須在
    for filename in ("github-oidc-trust.json", "github-deploy-policy.json"):
        assert "<ACCOUNT_ID>" in (DEPLOY_AWS_DIR / filename).read_text(encoding="utf-8"), (
            f"{filename} 應該用 <ACCOUNT_ID> 佔位，而不是真的帳號"
        )
```

> 📌 **為什麼沒有 `read_deploy_policy()`：** 這 4 顆裡沒有任何一顆需要「把權限 policy 解析成 dict」——
> 第 4 顆掃的是 `deploy/aws/` 底下**全部** JSON 的**原始文字**（`glob` ＋ regex），
> 所以多寫一個 helper 只會變成沒人呼叫的死碼。要驗權限 policy 的**結構**（五段 Sid）
> 是在 §4.5 與 §6 用 `aws iam get-role-policy` 對**真的掛上去那一份**驗的，比讀本機檔更有意義。

**③ 檔頭只補一行 `import json`——其餘沿用，不要重貼整個檔頭：**

```bash
sed -n '20,32p' tests/integration/test_design6_error_paths.py
```

現況（2026-09-03 實查）長這樣，**已經有** `re`／`Path`／`yaml` 與 `PROJECT_ROOT`：

```python
from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
```

**唯一要動的是加一行 `import json`**，放在 `import re` **前面**
（ruff 的 `I` 規則要求標準函式庫依字母排序，`json` < `re`）：

```python
import json
import re
from pathlib import Path
```

⚠ **不要**再宣告一次 `PROJECT_ROOT`（重複定義 ruff 不會擋，但兩份會漂）。
本 phase 的四個新常數（`DEPLOY_AWS_DIR`／`GITHUB_OIDC_SUB`／`GITHUB_OIDC_AUD`／`ACCOUNT_ID_PATTERN`）
**跟著上面那段一起放在檔案最後面**，就在用到它們的測試旁邊——
這樣一整段（註解框 ＋ 常數 ＋ helper ＋ 4 顆）是可以整塊搬動的，
之後 Phase 94／95 再各自往下追加自己的那一段。

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

- [x] 親眼看過那兩顆紅了。**沒看過紅的測試，你不知道它有沒有在測東西。**

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

- [x] 看過紅了，然後**重跑 §4.4 的 heredoc 把檔案還原**。

**⑤ 全部改回來之後跑綠：**

```bash
pytest tests/integration/test_design6_error_paths.py -v
```

**預期：10 passed** ＝
Phase 90 的 4 顆（`test_Dockerfile有cloud_worker這個target`／
`test_Dockerfile的app階段在最後`／`test_Dockerfile的cloud_worker帶ARG_GIT_SHA`／
`test_compose_yaml沒有新增服務也沒有AWS設定`）
＋ commit `f2fc067` 補的 2 顆（`test_unit檔與user_data內嵌段逐字相同`／`test_unit只在local才等本機Ollama`）
＋ 本 phase 的 4 顆（名字見上面的程式碼）。

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

### 4.8 更新 `CLAUDE.md` 的指令區

> 🤖 **這一節由 subagent 執行**（純改檔）。

**插入點（2026-09-03 實查的現況）：** `CLAUDE.md` 的「指令」區裡，AWS 相關的段落現在是**三段連著**：

```text
# ── AWS（增量六 Phase 82 起）──────────────────      ← Phase 82 建的
# ── 雲端看圖工人（增量六 Phase 88；**平常不用開**）──   ← Phase 88 建的
# ── 雲端工人（EC2；增量六 Phase 92 起）─────────      ← Phase 92 建的（最後一行是 Budget 警報那句）
# ── 格式與 lint：pre-commit（Phase 73，2026-08-27）── ← 下一段（Phase 73 的，不要動）
```

**把下面這一小段放在「雲端工人（EC2）」那一段的最後面、`# ── 格式與 lint` 那一行之前**
（也就是三段 AWS 內容的結尾，不是插在中間）。原因：讀的人是照「先有帳號 → 再有工人 →
再有機器 → 最後才有自動部署」的順序在往下看的。

**只寫變數名，不寫值**（總覽 §7 鐵律 10；**這個 repo 是 public**）：

````text
# ── 部署角色（Phase 93）─────────────────────────────────────────
# GitHub Actions 用 OIDC 換臨時憑證，GitHub 上**沒有**存任何 AWS 金鑰。
# 角色名 personaldocai-github-deploy；它的 ARN 放在 repo secret AWS_DEPLOY_ROLE_ARN。
# 兩份 JSON 在 deploy/aws/（帳號 ID 與實例 ID 用 <ACCOUNT_ID>／<INSTANCE_ID> 佔位，
# 要送 AWS 時才用 sed 展開到**專案外**的暫存目錄，展開檔永遠不進 repo）：
aws iam get-role --role-name personaldocai-github-deploy \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals'
# 預期：aud=sts.amazonaws.com、sub=repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
gh secret list      # 預期看得到 AWS_DEPLOY_ROLE_ARN（看得到名字，看不到值）
````

- [x] 貼進去了，位置在「雲端工人（EC2）」段的結尾、`# ── 格式與 lint` 之前。
- [x] **沒有**把帳號 ID、實例 ID、role ARN 的真值寫進去（`grep -nE '\b[0-9]{12}\b' CLAUDE.md` 預期無輸出）。

### 4.9 全量回歸與 commit

> 👤 **這一節由 controller 執行。**
> ⛔ **絕不同時跑兩份 pytest**（`tests/conftest.py` 的 `reset_tables` 會 TRUNCATE 同一個測試庫）。
> subagent 在 §4.7 只跑**單檔**（`pytest tests/integration/test_design6_error_paths.py`），
> 全量 `pytest -q` 由 controller 在 subagent 收工之後跑。

```bash
# 1) 全量
pytest -q
# 預期：696 passed ＋ 0 skipped（開工基線 692 ＋ 4）

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
    operations = [(path, method) for path, item in paths.items() for method in item]
    print("端點數 =", len(operations))
    print("DELETE 數 =", sum(1 for _, method in operations if method == "delete"))
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

# 7) 確認 $SCRATCH 那兩份展開檔沒有被誤加進來（它們含真實帳號 ID 與實例 ID）
git status --short | grep -i rendered
# 預期：完全沒有輸出（它們在專案外的暫存目錄，本來就不在 repo 裡）

# 8) controller 收工快照：用 snapshot-tree 的 tree SHA 與 BASE_TREE 相減，
#    確認「這一輪到底動了哪些檔」與上面第 6 項列的完全一致（本輪不 commit、不 push）
```

- [ ] 八項全部符合預期。

**Commit（產品負責人指示才做；本專案 commit 節奏由產品負責人決定）：**

> ⚠️ **本輪（phase0903-1）明示「不 commit、不 push」**（controller 裁決 R0）。
> 下面這段留著給產品負責人日後自己下手用——**實作者不要跑它**。
> 另外 push 這件事在 Phase 94 有額外意義：Demo 3 要靠 `git push` 才觸發得了 CI→CD，
> 那一步也是產品負責人做（Phase 94 §4.8）。

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
帳號 ID 一律 <ACCOUNT_ID> 佔位，用時 sed 展開到專案外的暫存目錄。
test_design6_error_paths.py +4（692 → 696；該檔 6 → 10）。
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
             ├─ buildx  linux/amd64,linux/arm64  target=cloud-worker      ← 94
             ├─ push ECR  <sha> ＋ latest                     ← 94
             └─ ssm send-command  systemctl restart           ← 94

   本 phase 做完之後，GitHub 上**還沒有任何 CD**。這是刻意的：
   先確認鑰匙配得起來（4 顆掃碼綠），再裝門（94）。
```

---

## 6. 驗收清單

> 📌 **打 `aws`／`gh` 的那幾項由 controller 勾**（裁決 R3）；`pytest`／`grep`／`git status`
> 那幾項 subagent 自己勾得起來。兩邊都做完才算本 phase 完成。

- [x] **★G3 已由產品負責人明示通過**（本檔最上面的門檻框；實作者不得自行勾選）（controller 2026-09-03 實查）
      ——**2026-09-03 已通過**，憑據見該框
- [x] OIDC provider 存在且 audience 正確（controller 2026-09-03 實查）

  ```bash
  aws iam get-open-id-connect-provider \
    --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" \
    --query '{Url:Url, Audiences:ClientIDList}'
  # 預期：{"Url": "token.actions.githubusercontent.com", "Audiences": ["sts.amazonaws.com"]}
  ```

- [x] 角色的 trust 逐字鎖住 `main`（controller 2026-09-03 實查）

  ```bash
  aws iam get-role --role-name personaldocai-github-deploy \
    --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals'
  # 預期：aud = sts.amazonaws.com
  #       sub = repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main
  ```

- [x] trust 的 `sub` ＝ GitHub 給這個 repo 的前綴 ＋ `:ref:refs/heads/main`（§4.3 的框；前綴變了兩邊要一起改）（controller 2026-09-03 實查）

  ```bash
  gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub --jq .sub_claim_prefix
  python3 -c "import json;print(json.load(open('deploy/aws/github-oidc-trust.json'))['Statement'][0]['Condition']['StringEquals']['token.actions.githubusercontent.com:sub'])"
  # 預期：第二行 ＝ 第一行 ＋ ':ref:refs/heads/main'（不相等＝CD 永遠換不到憑證）
  ```

- [x] 角色的權限恰好五段、沒有多給（controller 2026-09-03 實查）

  ```bash
  aws iam get-role-policy --role-name personaldocai-github-deploy \
    --policy-name personaldocai-github-deploy-policy \
    --query 'PolicyDocument.Statement[].{Sid:Sid,Action:Action}'
  # 預期：五段，Sid 依序 EcrLoginTokenIsAccountWide／EcrPushOnlyToTheWorkerRepository／
  #       SsmRestartOnlyThatOneInstance／SsmReadTheCommandResult／
  #       DescribeInstancesToSeeIfItIsRunning
  ```

- [x] 角色**沒有**掛任何 managed policy（＝沒有人偷偷加 PowerUserAccess）（controller 2026-09-03 實查）

  ```bash
  aws iam list-attached-role-policies --role-name personaldocai-github-deploy \
    --query 'AttachedPolicies' --output json
  # 預期：[]
  ```

- [x] GitHub secret 在（controller 2026-09-03 實查）

  ```bash
  gh secret list
  # 預期：AWS_DEPLOY_ROLE_ARN 那一列（看得到名字，看不到值）
  ```

- [x] 兩份 JSON 都在版控裡，而且**帳號 ID 是佔位符**；**4 顆新測試全綠且每顆都看過紅**
      （§4.7 ④做過兩輪反向驗證）；全量顆數 ＝ 基線 ＋ 4；端點仍 22、零 DELETE；
      三死埠零依賴實證顆數相同；ruff 兩句 exit 0

  ```bash
  grep -c '<ACCOUNT_ID>' deploy/aws/github-oidc-trust.json deploy/aws/github-deploy-policy.json
  # 預期：…trust.json:1   …policy.json:2
  grep -nE '\b[0-9]{12}\b' deploy/aws/*.json          # 預期：完全沒有輸出
  pytest tests/integration/test_design6_error_paths.py -v   # 預期：10 passed（90 的 4 ＋ f2fc067 的 2 ＋ 本 phase 的 4）
  pytest -q                                            # 預期：696 passed ＋ 0 skipped（基線 ＿＿＿ → 完成 ＿＿＿；應為 692 → 696）
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q         # 預期：顆數完全相同
  ruff format --check app tests scripts && ruff check app tests scripts   # 預期：exit 0
  ```

- [x] **該零改動的都零改動**：`test.yml`（D16）、`docs/spec/`、產品碼、專案 `data/`

  ```bash
  git diff --stat -- .github/workflows/test.yml        # 預期：無輸出
  git status --short docs/spec/                        # 預期：無輸出
  git status --short -- app/ compose.yaml Dockerfile db/ requirements.txt data/
  # 預期：與開工前完全相同（本 phase 不該讓它多出任何一行）
  find data/staging -type f -mmin +1440 2>/dev/null | head    # 預期：無輸出
  ```

- [x] **EC2 全程沒有被本 phase 開機**；**沒有產生任何 AWS 運算費用**（IAM／OIDC 全免費）（controller 2026-09-03 實查）

  ```bash
  aws ec2 describe-instances --region "$AWS_REGION" \
    --filters Name=instance-state-name,Values=running \
    --query 'Reservations[].Instances[].InstanceId' --output text
  # 預期：空。有輸出＝有人忘了關 EC2（92-A 的 t3.xlarge 或 92-B 的 g4dn），立刻處理（本 phase 不該開機）
  ```

- [x] **沒有自行 commit、沒有把 `unfinish/` 搬進 `finish/`**（除非產品負責人指示）（controller 2026-09-03 實查）

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

6. **把 `*.rendered.json` 複製回專案、加進 git。**
   **症狀：** `test_部署用的policy裡沒有寫死帳號ID` 不會紅（它只掃 `deploy/aws/`），
   但你的帳號 ID 與實例 ID 就永遠留在 git 歷史裡了——**改不掉，只能重寫歷史**，
   而且**這個 repo 是 public**，等於直接公開。
   **原因：** 展開後的檔案含真值。`.gitignore` 管不到專案外的路徑，
   但如果有人把它們複製回專案裡就會被 `git add .` 掃進去。
   **正解：** 展開結果**只寫 `$SCRATCH`（專案外）**，永遠不要複製回專案。
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
   **原因：** AWS CLI 的 `file://` 後面直接接路徑。**絕對路徑**是 `file:///private/tmp/…/x.json`
   （`file://` ＋ `/private/tmp/…` ＝ **三條斜線**）；相對路徑是 `file://x.json`（兩條）。
   **正解：** 本檔一律寫成 `"file://$SCRATCH/x.json"`——`$SCRATCH` 本身是絕對路徑（開頭就有 `/`），
   展開後自然是三條斜線。**雙引號不要拿掉**，`$SCRATCH` 沒展開時錯誤訊息會變成看不懂的
   `Unable to load paramfile file:///x.json`。

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
    **這個 repo 已經是 public**，所以「有人從 fork 開 PR」是隨時可能發生的事——而他既拿不到 secret，
    `sub` 也是 `…:pull_request` 而被 trust 的 `StringEquals` 擋掉——兩道鎖各擋一次。
    （Phase 94 還會在 `deploy` 的 `if` 多加一條 `workflow_run.event == 'push'`，
    擋「fork 的分支剛好也叫 `main`」那種情況；總覽 §10.2 M。）

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 多了什麼 |
|---|---|
| AWS（IAM） | 一個 OIDC identity provider（指向 GitHub）＋ 一個角色 `personaldocai-github-deploy`（trust ＋ 一份 inline policy）。**全部免費** |
| GitHub | 一個 repository secret `AWS_DEPLOY_ROLE_ARN` |
| repo | `deploy/aws/github-oidc-trust.json`、`deploy/aws/github-deploy-policy.json`（帳號 ID 與實例 ID 用佔位符）；`tests/integration/test_design6_error_paths.py` +4 顆（該檔 **6 → 10**）；`CLAUDE.md` 多一個「部署角色（Phase 93）」小段 |

**對外行為變了沒：完全沒有。**

- 端點仍是 **22**、openapi 仍**零 DELETE**。
- `POST /photos` 仍是 **202**，回應仍是三鍵。
- 前端零改動、`compose.yaml` 零改動、`Dockerfile` 零改動、正式庫零改動。
- **GitHub 上還沒有任何 CD**——push 之後仍然只有 `test` 那一顆 job 在跑。

**顆數：**

| | 顆數 | `test_design6_error_paths.py` 檔內 |
|---|---|---|
| 開工基線（Phase 92 之後，含 `f2fc067` 的 2 顆） | **692** ＋ 0 skipped | **6** |
| 本 phase 新增 | **+4**（全部在 `tests/integration/test_design6_error_paths.py`） | **+4** |
| 完成後 | **696** ＋ 0 skipped | **10** |

與總覽 §2.7／§9 的 Phase 93 那一列**在「新增 +4」這件事上完全一致**，沒有多加也沒有少加。
**絕對值不同是預期的**：總覽 §9 寫的累計是 `662 → 666`，實查基線是 **692**（差 30），
§9 自己在 Phase 75 那列就註明過「絕對值只對『本 phase 新增幾顆』」。本檔一律以 **692 → 696** 為準。

**下一個 phase：** `phase-94-CD工作流程.md`——把 `.github/workflows/deploy.yml` 寫出來
（`workflow_run` 綁 `test` → OIDC → QEMU ＋ buildx → `linux/amd64,linux/arm64` → ECR `<sha>` ＋ `latest`
→ SSM 重啟），追加 6 顆掃碼測試（**696 → 702**；該檔 10 → 16），並就位 **Demo 3**
（Demo 3 本身要 `git push` 才觸發得了 CI→CD，**由產品負責人執行**）。
Phase 94 會用到本 phase 的兩樣東西，名字不要改：

- GitHub repository secret **`AWS_DEPLOY_ROLE_ARN`**（`${{ secrets.AWS_DEPLOY_ROLE_ARN }}`）
- IAM 角色 **`personaldocai-github-deploy`**（它的 policy 決定 Phase 94 能做哪三件事）

> ⚠️ 順帶提醒 Phase 94：本 phase 把角色的 `--max-session-duration` 設成 **3600 秒**。
> `aws-actions/configure-aws-credentials` 預設就是 1 小時，所以**不填**最省事；
> 真要填 `role-duration-seconds`，值**不能超過 3600**，否則會紅在換憑證那一步
> （訊息是 `DurationSeconds exceeds the MaxSessionDuration set for this role`）。

---

## 9. 2026-09-03 校準紀錄

> 這一節是給實作者與 reviewer 看的 **diff 摘要**：本檔在 2026-09-03（工作區
> `.superpowers/sdd/phase0903-1/`）依 controller 實查的現況校準過一次，
> 下面逐條列「改了什麼、為什麼」。**沒列到的部分一字未動。**

### 9.1 ★G3 與開工狀態

| # | 改了什麼 | 為什麼 |
|---|---|---|
| 1 | 檔頭框「本 phase 仍不准開工，要等 ★G3」→「★G3 已通過，可以開工」；92-A 從「現在就做」改成「已建好、Demo 2／2b 通過、收工 Stop」 | ★G3 已於 2026-09-03 由產品負責人通過 |
| 2 | §「開工門檻」加一個 ✅ 框（三項憑據）與表格最後一列「本次狀態：已通過」 | 閘門的**規則**要留著（將來重跑仍以它為準），但「這一次過了沒」必須寫清楚，否則實作者會停在門口 |
| 3 | §2 前置條件補：repo 是 **PUBLIC**、`docs/plan/aws/` 六份 owner 筆記只當對照 | repo public ＝「不寫值」是硬性規定不是潔癖；owner 的筆記不是計畫檔，不准改 |

### 9.2 顆數與基線（controller 裁決 R4）

| # | 舊 | 新 | 為什麼 |
|---|---|---|---|
| 4 | 開工基線 `662 passed` | **`692 passed`** | 2026-09-03 實查值。差 30 的原因寫進 §2 的註解：總覽 §9 的絕對值只保證「本 phase 新增幾顆」 |
| 5 | `test_design6_error_paths.py` 目前 **4** 顆 | **6** 顆（並列出六個測試名） | Phase 92 本身 +0，但產品負責人在 commit `f2fc067` 補了 2 顆（`test_unit檔與user_data內嵌段逐字相同`、`test_unit只在local才等本機Ollama`） |
| 6 | `--collect-only` 預期 `4 tests collected`；§4.7 ⑤ 預期 `8 passed` | **6** ／ **10 passed** | 同上 |
| 7 | 完成後 `666`；§6 與 §8 的表；commit message `662 → 666` | **`696`**；`692 → 696`；檔內 `6 → 10` | 同上 |
| 8 | 「下一個 phase：追加 6 顆（666 → 672）」 | **696 → 702**，並註明 Demo 3 由產品負責人執行 | 與 Phase 94 校準後的數字對齊（裁決 R0） |

### 9.3 分工與執行順序（裁決 R3）

| # | 改了什麼 | 為什麼 |
|---|---|---|
| 9 | §4 開頭那個「順序是有意義的」框整段改寫：加「誰做哪一節」表 ＋ 八步執行順序（先 subagent 寫 JSON／測試／CLAUDE.md，後 controller 建 provider／role／secret／跑全量） | 實作 subagent **零 `aws`／`gh`／`docker` 指令、零真連線**；而且「鑰匙的形狀」先被測試釘死再去配鎖，錯了不必 `delete-role` |
| 10 | §4.1／§4.2／§4.4 後半／§4.5／§4.6／§4.9 各加「👤 由 controller 執行」；§4.3／§4.4 前半／§4.7／§4.8 各加「🤖 由 subagent 執行」 | 同上，逐節標清楚免得混 |
| 11 | §4.9 加警語「絕不同時跑兩份 pytest」，並說明 subagent 只跑單檔、controller 才跑全量 | `reset_tables` 會 TRUNCATE 同一個測試庫，兩份同時跑會出現一堆假紅 |
| 12 | §4.9 加第 8 項「controller 用 `snapshot-tree` 的 tree SHA 相減驗動到哪些檔」；commit 那段加「本輪不 commit／不 push」的框 | 裁決 R0：本輪只就位，不 commit、不 push |

### 9.4 暫存路徑：`/tmp` → `$SCRATCH`

| # | 改了什麼 | 為什麼 |
|---|---|---|
| 13 | §4.1 定義 `export SCRATCH=<scratchpad 絕對路徑>`（含 `mkdir -p` 與「為什麼要 export」） | 本輪展開檔一律寫進 agent 的 scratchpad；`export` 不能省，§4.4 有一句 `python3 -c` 讀 `os.environ['SCRATCH']` |
| 14 | §4.4 的兩條 `sed`、檢查用的 `python3 -c`／`grep`、§4.5 的 `create-role`／`put-role-policy`／`update-assume-role-policy`、§7 陷阱 6／8：`/tmp/...` 全部換成 `"$SCRATCH/..."`／`"file://$SCRATCH/..."` | 同上。並保留「人自己做時用 `/tmp` 也一樣」這句，免得半年後的人以為非 scratchpad 不可 |
| 15 | §4.8 給 `CLAUDE.md` 的三行**不寫** `$SCRATCH` 也不寫 `/tmp`，改成「展開到**專案外**的暫存目錄」 | `CLAUDE.md` 是長期文件，不該被塞進某一次 session 的路徑 |

### 9.5 識別字英文化（裁決 R1；`test_中文` 名保留）

§4.7 的測試碼區與 §4.9 第 3 項的 `python3` 片段，識別字全部改英文：

| 舊（中文） | 新（英文） | 在哪裡 |
|---|---|---|
| `部署目錄` | `DEPLOY_AWS_DIR` | 模組層常數 |
| `專案根目錄` | `PROJECT_ROOT` | **沿用檔頭既有的**，不重新宣告 |
| `帳號ID的長相` | `ACCOUNT_ID_PATTERN` | 模組層常數 |
| `信任文件()` | `read_trust_policy()` | helper |
| `語句` | `statements`（第 1 顆）／`statement`（第 3 顆） | 區域變數 |
| `條件` | `condition` | 區域變數 |
| `原文` | `source` | 區域變數 |
| `檔案們`／`名稱們`／`命中`／`檔`／`疑似`／`檔名` | `json_files`／`names`／`hits`／`path`／`suspect`／`filename` | 區域變數 |
| `運算元` | `operations` | §4.9 第 3 項的端點清點片段 |

- **四個 `test_中文` 測試名一字未動**（總覽 §2.7 的契約）。
- 註解、docstring、斷言訊息**仍然是中文**（規矩只管識別字）。
- **沒有**加 `read_deploy_policy()`：這 4 顆沒有任何一顆需要把權限 policy 解析成 dict
  （第 4 顆掃的是整個目錄的**原始文字**），多寫就是死碼。理由已寫進 §4.7 的框。
- §4.7 ③ 從「重貼三行 import」改成「**只補一行 `import json`**，其餘沿用現況檔頭」，
  並貼出 2026-09-03 實查的檔頭長相（`re`／`Path`／`yaml`／`PROJECT_ROOT` 都已經在）。

### 9.6 外部事實複查（裁決 R11；全部 2026-09-03 以 WebFetch 讀官方原文）

| 查什麼 | 結果 | 出處 |
|---|---|---|
| thumbprint 是不是選填 | **仍然選填**，原句一字未變（AWS 用自己的可信根 CA 清單驗 JWKS 的 TLS 憑證） | [IAM：Create an OIDC identity provider](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html) |
| CLI synopsis 與「參數是選填」那句 | **逐字相同**（`--url` 必填，其餘方括號） | [CLI `create-open-id-connect-provider`](https://docs.aws.amazon.com/cli/latest/reference/iam/create-open-id-connect-provider.html) |
| ECR 推映像的六個動作 ＋ `GetAuthorizationToken` 用 `*` | **完全相同**（`CompleteLayerUpload`／`UploadLayerPart`／`InitiateLayerUpload`／`BatchCheckLayerAvailability`／`PutImage`／`BatchGetImage`） | [ECR image-push-iam](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html) |
| `ssm:SendCommand` 要同時列實例 ARN 與 document ARN | **確認**（Example 3），且同頁明文「`AWS-*` 這種公開 document 的 ARN **不要填帳號 ID**」 | [SSM identity-based policy examples](https://docs.aws.amazon.com/systems-manager/latest/userguide/security_iam_id-based-policy-examples.html) |
| GitHub 不可變主體格式 | **確認**：2026-07-15 之後建的 repo 用 `repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH`；改名／轉移也會換成新格式；「Update your trust policies to match the format your repository uses」 | [OIDC reference §Immutable subject claims](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims) |
| `workflow_run` 的 `GITHUB_REF` 與 secrets | **確認**：`GITHUB_SHA` ＝ Last commit on default branch、`GITHUB_REF` ＝ Default branch；workflow 檔必須在預設分支上才觸發得了；由它啟動的 workflow 拿得到 secrets | [Events that trigger workflows → `workflow_run`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run) |
| GitHub OIDC → AWS 指南的 `sub` 範例 | **已更新**：同一頁現在**兩種格式都列**（舊的 mutable ＋ 新的 immutable）。附錄那一條已改寫，提醒「照那頁抄要挑對版本」 | [oidc-in-aws](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws) |
| `ec2:DescribeInstances` 的資源層級限制 | **未能從官方表格逐字複查**（Service Authorization Reference 的表是 JS 產生的，抓不到）。原文寫「AWS 的 `Describe*` 系列**一律**不支援」過於絕對，已收窄成「`ec2:DescribeInstances` 不支援（EC2 的 `Describe*` 幾乎都如此）」 | — |

另外補了三個實查事實進正文：**OIDC provider 現在 0 個**（§4.2）、
**IAM 沒有 `personaldocai-github-deploy` 這個角色**（§4.5）、
**`gh secret list` 與 `gh variable list` 都是空的**（§4.6）——三處都會走「全新建立」那條路，
不會撞 `EntityAlreadyExists`。

### 9.7 其他修正

| # | 改了什麼 | 為什麼 |
|---|---|---|
| 16 | §4.3 的框加「✅ 2026-09-03 controller 又跑了一次 `gh api …/customization/sub`：三個欄位逐字相同」 | 實作者不必猜那一串還對不對；但**動手前仍要自己再跑一次**（repo 改名／轉移會變） |
| 17 | §4.3 引的 GitHub 原文改成 2026-09-03 讀到的**逐字**版本，並補上官方例子 `repo:octo-org@123456/octo-repo@456789:ref:refs/heads/main` | 原本引的第二句（"will also adopt the new format"）與現行原文措辭不同 |
| 18 | §4.2 補一句：Console 寫「至少一個 thumbprint」與「不必自己填」**不衝突**（不填時 IAM 自己抓一個） | 避免有人在 Console 看到有值就以為被人動過手腳 |
| 19 | §4.4 新增一個框：**92-B 換機之後實例 ID 會變**，要①重跑 `put-role-policy` ②改 Phase 94 的 GitHub variable，並列出各自漏掉的症狀 | 這兩處是不同的東西，只改一邊 CD 會安靜地半殘 |
| 20 | §4.6／§7 陷阱 6／11、第 4 顆測試的 docstring：「repo 現在是 private，哪天轉 public…」→ **「已經是 public」** | 實查：repo `1104030360/personalDocAI` 是 PUBLIC。原文的語氣會讓人低估風險 |
| 21 | §7 陷阱 11 補一句：Phase 94 的 `if` 還會多一條 `workflow_run.event == 'push'`（擋 fork 分支叫 `main`） | 總覽 §10.2 M 的裁決，兩個 phase 要對得上 |
| 22 | §2 前置：ECR 三個 tag 的實況（`bb3921a` 單架構 arm64、`bb3921a-dirty`／`latest` 多架構）；「不要加 `--profile`」 | 原文只寫「已經有一個映像」；而這台 Mac 沒有具名 profile，加了會找不到 |
| 23 | §3 範圍與 §4.8：`CLAUDE.md` 的插入點從「AWS 段的最後面」改成**「雲端工人（EC2）」段的結尾、`# ── 格式與 lint` 之前**，並貼出現況的四段標題 | 實查：AWS 段之後還接了「雲端看圖工人」與「雲端工人（EC2）」兩段，照舊描述會插錯地方 |

### 9.8 本次校準**沒有**動的東西

- 四個 `test_中文` 測試名、兩份 JSON 的內容（`Sid`／`Action`／`Resource` 一字未改）。
- `deploy/aws/*.json`、`tests/`、`app/`、`.env`、`compose*.yaml`、`docs/spec/`——
  校準階段**零程式碼改動**，只改這一份計畫檔。
- §5 的兩張 ASCII 圖、§7 的十一個陷阱標題與結構、§1 的對照表。

---

## 10. 實作紀錄（2026-09-03，實作 subagent）

**結論：🤖 標的四段（§4.3 的 JSON、§4.4 前半的 JSON、§4.7 的 4 顆測試、§4.8 的 `CLAUDE.md` 小段）
照計畫逐字做完，兩份 JSON 逐字落地、4 顆測試紅→綠、全量 692 → 696（0 skipped）。**
本 task **零 `aws`／`gh`／`docker` 指令、零真連線、零 `.env` 變更、零產品碼、未 commit**（裁決 R0／R3）。
👤 標的 §4.1／§4.2／§4.3 的 `gh api` 複查／§4.4 的 `sed` 展開／§4.5／§4.6／§4.9 **仍待 controller 執行**，
§6 那幾條打 `aws`／`gh` 的 checkbox 一律留白。

### 10.1 交付的四個檔

| 檔案 | 狀態 | 來源 | 備註 |
|---|---|---|---|
| `deploy/aws/github-oidc-trust.json` | 新檔（19 行） | §4.3 heredoc（本檔第 577〜595 行） | 一條 Statement；`StringEquals` 逐字鎖 `sub`、`aud`；全檔零 `*`；`<ACCOUNT_ID>`×1 |
| `deploy/aws/github-deploy-policy.json` | 新檔（45 行） | §4.4 heredoc（本檔第 674〜718 行） | 五段 `Sid` 依序 `EcrLoginTokenIsAccountWide`／`EcrPushOnlyToTheWorkerRepository`／`SsmRestartOnlyThatOneInstance`／`SsmReadTheCommandResult`／`DescribeInstancesToSeeIfItIsRunning`；`<ACCOUNT_ID>`×2、`<INSTANCE_ID>`×1 |
| `tests/integration/test_design6_error_paths.py` | 改檔（+127 行、**零刪除**） | §4.7 ② 的 python 區塊（本檔第 990〜1113 行） | 檔頭只補 `import json`（在 `import re` 前）；4 顆＋常數＋`read_trust_policy()` 一整塊追加在**檔尾**；既有 6 顆與既有 helper 一字未動 |
| `CLAUDE.md` | 改檔（+10 行） | §4.8 的 ````text` 區塊（本檔第 1248〜1256 行） | 插在「雲端工人（EC2）」段結尾（Budget 警報那行之後）、`# ── 格式與 lint` 之前 |

**落地手法：** 四段全部用 `sed -n '<起>,<迄>p' <本計畫檔>` 從計畫檔**原樣導出**，不手打
（Phase 91 同一手法）。導出後檢查 `grep -P '\xc2\xa0'`／exotic space／行尾空白皆零命中，
兩份 JSON 是**全 ASCII**、檔尾各有一個換行。

### 10.2 TDD 證據

| 步驟 | 指令 | 結果 |
|---|---|---|
| 追加測試前 | `pytest …test_design6_error_paths.py --collect-only -q` | `6 tests collected`（與 §4.7 ① 預期相同） |
| 追加測試後（**RED**，JSON 還不存在） | `pytest …test_design6_error_paths.py -q` | **4 failed, 6 passed**——三顆 `FileNotFoundError: …/deploy/aws/github-oidc-trust.json`、第四顆 `AssertionError: deploy/aws/ 應該至少有本 phase 的兩份 JSON，現在只有：['mac-policy.json', 's3-lifecycle.json', 'worker-role-policy.json', 'worker-role-trust.json']` |
| 寫完兩份 JSON（**GREEN**） | `pytest …test_design6_error_paths.py -v` | **10 passed** |
| 反向變異 ①（`sub` → `…@1349196211:*`） | `pytest … -k OIDC -q` | **2 failed**（`sub逐字鎖住main分支` 的 `assert '…:*' == '…:ref:refs/heads/main'`＋`沒有星號萬用字元`），1 passed |
| 反向變異 ②（`<ACCOUNT_ID>` → `000000000000`） | `pytest … -k 帳號ID -q` | **1 failed**：`不可以寫死 12 位數的 AWS 帳號 ID：['github-deploy-policy.json：000000000000', …]` |
| 還原後 | `diff` 兩份 JSON 與變異前的備份 | **逐字相同**（零差異）；同檔 **10 passed** |

### 10.3 全量與零依賴

| 檢查 | 結果 |
|---|---|
| `pytest -q` | **696 passed、0 skipped**（開工基線 692 ＋ 4），warning 只有基線那一個 `StarletteDeprecationWarning` |
| 三死埠（`AWS_ENDPOINT_URL`／`CELERY_BROKER_URL`／`OLLAMA_BASE_URL` 全指 `127.0.0.1:9`） | **696 passed**（顆數完全相同＝本 phase 的 4 顆真的不連網） |
| `ruff format app tests scripts && ruff check app tests scripts` | `114 files left unchanged`／`All checks passed!`，exit 0（**format 零改檔**＝計畫檔那段碼本來就合格式） |
| 端點仍 22、openapi 零 DELETE | 由既有的 `test_端點恰好是這22支`／`test_openapi裡沒有任何DELETE動詞` 在全量裡把關，全綠 |
| 非 ASCII 識別字自檢（tokenize） | `[]`（測試檔；`test_中文` 名不計，見裁決 R1） |
| `grep -nE '\b[0-9]{12}\b' deploy/aws/*.json CLAUDE.md` | 無輸出（零真帳號 ID） |
| `git status --short -- app/ compose.yaml Dockerfile db/ requirements.txt data/`、`git diff --stat -- .github/workflows/test.yml`、`git status --short docs/spec/` | 全部無輸出（該零改動的都零改動；D16 的 `test.yml` 一字未動） |
| 工作樹本 phase 動到的檔 | `M CLAUDE.md`、`M tests/integration/test_design6_error_paths.py`、`?? deploy/aws/github-oidc-trust.json`、`?? deploy/aws/github-deploy-policy.json`（＋本計畫檔的勾選與本節）——與 §4.9 第 6 項列的完全一致 |

### 10.4 與計畫檔的差異

**零差異。** 檔名、JSON 內容（`Sid`／`Action`／`Resource`／`Condition` 一字未改）、
四個 `test_中文` 測試名、常數名（`DEPLOY_AWS_DIR`／`GITHUB_OIDC_SUB`／`GITHUB_OIDC_AUD`／`ACCOUNT_ID_PATTERN`）、
helper 名（`read_trust_policy()`）、`CLAUDE.md` 小段的文字與插入點，全部照 §4.3／§4.4／§4.7／§4.8 逐字。
未新增計畫外的檔案、函式或測試；**沒有**加 `read_deploy_policy()`（§4.7 的框已說明那會是死碼）。

兩點供 controller 留意（都不是偏離，只是措辭）：

1. §6 那一條「兩份 JSON 都**在版控裡**」——本輪依裁決 R0 **不 commit、不 `git add`**，
   所以兩份檔目前是工作樹裡的 `??`（未追蹤）。「在 repo 裡、內容是佔位符」這一半已成立，
   真正進版控要等產品負責人 commit。
2. 總覽 §2.7 Phase 93 的「動到的檔」只列兩份 JSON ＋ 測試檔，**沒有列 `CLAUDE.md`**；
   本檔 §3 與 §4.8 則明文要求改 `CLAUDE.md`。兩者不衝突（總覽那欄不列文件檔），
   已照本檔做，並在此註記。

### 10.5 疑慮

- 無阻斷性疑慮。唯一提醒：`deploy/aws/github-deploy-policy.json` 的 `<INSTANCE_ID>` 綁的是
  **92-A 那一台**；92-B 換機時要照 §4.4 那個框做兩件事（重跑 `put-role-policy` ＋ 改 Phase 94 的
  GitHub variable），少做一件 CD 會安靜地半殘。

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
  ——`permissions: id-token: write`（拿 JWT）＋ `contents: read`（給 `actions/checkout`）出自這一頁。
  ⚠ **2026-09-03 複查：這一頁的 trust policy 範例現在同時列出兩種 `sub`**——
  舊的 `repo:octo-org/octo-repo:ref:refs/heads/octo-branch` 與新的
  `repo:octo-org@123456/octo-repo@456789:ref:refs/heads/octo-branch`，並自己說明
  「2026-07-15 之後建立的 repo」用後者。**本 repo 要用後者**（見 §4.3 的框）
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
