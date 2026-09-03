# Phase 82：AWS 帳號與工具

> 🎯 **提醒：這是 side project，不要過度設計。** 本 phase **一行 Python 都不寫**，只做「把門打開」這件事。
> 本 phase 特別**不要**做的四件事：
> ① 不要順手建 S3 bucket 或 SQS 佇列（那是 Phase 84／85，而且要先有 `boto3` 模組才驗得動）；
> ② 不要開 AWS Organizations／Control Tower（會自動升 Paid 而且點數作廢，design6 §7 明文禁止）；
> ③ 不要按 Console 上任何一顆「Upgrade to Paid plan」「Activate paid support」按鈕；
> ④ 不要開 EC2「先試試看」（EC2 是 Phase 91／92 的事，而且要先過 ★G2）。

```text
┌─ ⛔ 開工前檢查（閘門 ★G1）──────────────────────────────────────────
│ ★G1 是**人**的動作，實作者不可以自己勾掉（總覽 §4 明文）。
│
│ 產品負責人是否已「明示」G1 通過？
│   （原話例：「甲的驗收我看過了，可以開始花 AWS 資源」）
│
│ 沒有這句話 → **停手**，回去把 Phase 74〜81 的驗收證據交出來（總覽 §5.1）。
│
│ ⛔ **★G1 沒過，一行 AWS 指令都不准打**——這是 design6 §0 六條禁止的第 1 條：
│    「甲還沒綠就開 S3／SQS／EC2」。
│    也**不可以**用「先開個帳號放著、之後再說」繞過：
│    **開戶當下就開始算 Free plan 的 6 個月**（總覽 §8.4），甲還沒過就開戶＝白燒時間。
└──────────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 開一個 **Free plan** 的 AWS 帳號（東京區）、**第一天就先建好每月 $5 的預算警報**、
> 在這台 Mac 上裝好 AWS CLI，並且建立兩個身分——一個**人**在用的管理者、一個**程式**在用的最小權限使用者——
> 最後用 `aws sts get-caller-identity` 證明「我真的連得上 AWS，而且知道自己是誰」。

**為什麼要做這個：**

到 Phase 81 為止，整個增量六**一次都沒有碰過 AWS**。程式裡有 `CloudRouteOff`（永遠說「遠端不可用」）、
有隱私閘門、有 fallback，測試 616 顆全綠——但那全部是在這台 Mac 上自己演的。

從本 phase 起要開始接真的東西。而在接之前，有三件事**順序不能顛倒**：

1. **先確定不會被扣款。** AWS 2025-07-15 之後的新帳號是「點數制」的 **Free plan**：
   開戶送點數、**升 Paid 之前不扣信用卡**。但點數用完會**關帳**（資源直接消失），
   所以第一天就要建一個「花超過就寄信給我」的預算警報。
2. **先把工具裝好。** 之後每一個 phase 都要打 `aws ...` 指令，沒有 CLI 就什麼都做不了。
3. **先把權限切乾淨。** design6 §6 明文要求 IAM 最小權限：**程式**只能碰 `documents/` 這個前綴，
   與兩條佇列上的**訊息**動作（本機端的 Send jobs／Receive results，加上這台 Mac 在 Phase 88／90
   自己跑工人時要的 Receive jobs／Send results——總覽 §10.2 N）；建 bucket、建佇列、清佇列一律不行。
   這條規則要在「還沒有任何東西可以碰」的時候先立好，之後就不必回頭收拾。

做完之後，你的 Mac 上會有一把可以打 AWS 的鑰匙，`.env` 裡會有一把**只給程式用的**、
權限被限制得很死的鑰匙，而且 AWS 帳單超過 $4（＝$5 的 80%）就會寄信給你。

**新名詞先解釋：**

> 這一張表裡的名詞，總覽 §1.7 也有一份。這裡是**本 phase 真的會用到**的那幾個，寫得更細。

| 名詞 | 白話解釋 |
|---|---|
| **AWS 帳號（account）** | 一個獨立的帳單與資源空間，有一組 **12 位數字**的 account ID。本專案只需要**一個**帳號 |
| **root user（根帳號）** | 你註冊時用的那個 email。它**權限無限大而且無法限制**，所以只在「開戶第一天」與「非它不可的設定」用，之後一律用底下建的 IAM 使用者 |
| **MFA（多因素驗證）** | 除了密碼之外再加一個「手機上的六位數動態碼」。root 帳號**一定要開**——root 被盜等於整個帳號被盜，而且沒有補救 |
| **Free plan（免費方案）** | 2025-07-15 之後新帳號的制度：開戶送 $100 點數（做完 Explore AWS 活動最多再 +$100；點數在開戶滿 **12 個月**時失效）；**升 Paid 之前完全不扣信用卡**；**6 個月或點數用完先到者關帳**（資源消失、資料保留 90 天）；**升了 Paid 就不能再降回來** |
| **點數（credits）** | Free plan 用來付帳的東西，**不是**現金。EC2 的硬碟、S3 的儲存、SQS 的請求都從這裡扣。用完就關帳，所以要有警報 |
| **Budget（預算警報）** | AWS Budgets 服務的一筆設定：「這個月花超過 X 就寄信給我」。可以看**實際（ACTUAL）**已花掉多少，也可以看**預測（FORECASTED）**照這個速度月底會花多少 |
| **Region（區域）** | AWS 的機房群所在地。本專案固定 **`ap-northeast-1`（東京）**——離台灣最近、Free plan 支援、而且所有資源必須在同一區才連得順 |
| **AWS CLI** | 在終端機打 `aws ...` 指令操作 AWS 的官方工具。`brew install awscli` 裝的是 **v2** |
| **`aws configure`** | 把「金鑰、預設區域、輸出格式」寫進 `~/.aws/credentials` 與 `~/.aws/config` 的互動式指令。寫完之後每一條 `aws` 指令都會自動帶上 |
| **profile（設定檔）** | `~/.aws/` 底下可以放**好幾組**身分，每組有名字。不指定名字時用的那組叫 `default`。本專案**只用 `default`**（見 §4.7 的理由） |
| **IAM** | AWS 的權限系統（Identity and Access Management）：「誰」可以對「什麼」做「哪些動作」全部在這裡定義 |
| **IAM user（使用者）** | 一個長期存在的身分。它可以有 Console 密碼（給人登入用）與 **access key**（給程式用），兩者可以只有其中一種 |
| **access key / secret access key** | 給**程式**用的帳號密碼，一對兩串字。**secret 只在建立當下顯示一次**，關掉視窗就再也看不到（只能刪掉重建） |
| **IAM policy（政策）** | 一份 JSON，寫著「允許／拒絕」「哪些動作」「對哪些資源」。掛在 user 或 role 上才生效 |
| **managed policy（受管政策）** | 一份可以重複掛在很多身分上的獨立 policy。AWS 自己也提供一批，例如 `AdministratorAccess`（什麼都能做） |
| **ARN** | AWS 的資源身分證，長相固定：`arn:aws:<服務>:<區域>:<帳號ID>:<資源>`。例如 `arn:aws:sqs:ap-northeast-1:123456789012:personaldocai-jobs` |
| **最小權限（least privilege）** | 「只給剛好夠用的權限」。本專案的程式連 `s3:CreateBucket` 都沒有——因為它從來不需要建 bucket，建 bucket 是人做的事 |
| **STS（Security Token Service）** | 發臨時憑證的服務。`aws sts get-caller-identity` 是「我現在是誰」的萬用檢查指令，**不需要任何權限就能跑**，所以拿來當「連得上嗎」的第一個測試最準 |
| **`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`** | boto3 與 AWS CLI 都會讀的**標準環境變數名**。本專案把「程式用的那一把」放在 `.env` 裡，讓 worker 容器讀得到 |
| **IAM role（角色）** | 「一組權限」但**沒有長期密碼**：EC2（Phase 91）或 GitHub Actions（Phase 93）拿它跟 AWS 換一組幾小時就過期的臨時憑證。**本 phase 不建任何 role**，但要先知道它跟 IAM user 的差別：user 有一把要藏好的長期 key，role 沒有 |
| **憑證的優先序（環境變數 ＞ profile）** | AWS CLI 與 boto3 找金鑰的順序是**環境變數 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` 先、`~/.aws/credentials` 的 profile 後**。所以 shell 只要載入過 `.env`，CLI 就會默默改用程式那把最小權限 key——§7 陷阱 1 就是這件事，正解是載完馬上 `unset` |
| **Explore AWS（開戶後的活動小方塊）** | Console 首頁的一個小方塊，做完指定活動各拿 $20 點數（最多 +$100）。其中「**AWS Budgets：建一個有警報的預算**」剛好就是 §4.3 要做的事，順手領；**RDS／Lambda／Bedrock 那幾項不要為了 $20 去開**（design6 §1.2 否決的服務） |
| **為什麼容器看不到 `~/.aws`** | `compose.yaml` 只把專案裡的東西掛進容器：`app` 掛 `./data`、`./certs`、`./.env` 三樣，`worker` 掛 `./data`、`./.env` 兩樣（不掛憑證）。你家目錄的 `~/.aws/credentials` **沒有**被掛進去，容器裡根本沒有那個檔——所以程式用的金鑰**一定要**走 `.env` |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D15**（AWS 帳號 Free plan） | 新帳號點數制、目標卡片 $0、用完 Stop、東京、`linux/arm64`、t4g.small | §4.1 開戶選 Free plan、§4.3 建 Budget、§4.5 區域固定東京 |
| **§7 AWS 帳號與費用**（整節） | 方案／點數／服務清單／EC2／網路／管理／警報／**禁止 Organizations** | §4.1（不升 Paid、不開 Organizations）、§4.3（警報）、§7 陷阱 1／2 |
| **§6 安全與隱私「IAM 最小權限」那一列** | 本機：指定 prefix 的 `s3:Put`／`Get`／`Delete`；jobs 的 `SendMessage`；results 的 `ReceiveMessage`／`DeleteMessage`；`ec2:DescribeInstances` | §4.6.1 的 `deploy/aws/mac-policy.json` 就是這一列，外加兩個唯讀動作：results 的 `ChangeMessageVisibility`（總覽 §2.8，本機把別人的訊息還回佇列用）與兩條佇列的 `sqs:GetQueueAttributes`（看佇列長度用）；**再加工人端四個動作**（下一列） |
| **§6「機密不進文件」那一列** | `.env` 不入版控；文件只寫變數名 | 本檔全文只出現變數名與 `<ACCOUNT_ID>` 佔位；§4.9 明寫「不要把輸出貼進任何檔案」 |
| **§0 禁止第 1 條** | 甲還沒綠就開 S3／SQS／EC2 | 檔案最上面的 ★G1 門檻框 |
| **§1.2 被否決第 8 列** | RDS／ECS／Fargate／Lambda／ALB／NAT Gateway／K8s | §3「明確不做」表 |
| **總覽 §10.2 追認項 N**（mac key 兼工人端） | `personaldocai-mac-policy` 兩邊都要有：jobs 的 `ReceiveMessage`／`DeleteMessage`／`ChangeMessageVisibility` 與 results 的 `SendMessage`——Phase 88（Mac 直跑工人）與 90（Mac 上用容器跑工人）用的都是 `.env` 這把 key，少了就第一次 `ReceiveMessage` 就 AccessDenied；EC2 上仍用 instance role；仍不給 `CreateBucket`／`PurgeQueue`（`ListBucket` 見下一列 P） | §4.6.1 JSON 的 `WorkerReceiveJobs`／`WorkerSendResults` 兩條 Sid ＋ 說明框、§5 圖二、§6「七條 Sid」驗收 |
| **總覽 §10.2 追認項 P**（`s3:ListBucket`） | 加 `s3:ListBucket`，Resource 是 **bucket ARN** `arn:aws:s3:::personaldocai-mailbox-*`（不是 `/documents/*` 那條）：S3 官方規則——沒有 ListBucket 時，GetObject 拿不存在的 key 回 403 而不是 404，而工人冪等檢查／`fetch_result`／`aws_check.py` 全靠 404 判「還沒有」 | §4.6.1 JSON 的 `ListMailboxBucket` Sid ＋ 說明列、§6「七條 Sid」驗收 |
| **總覽 §2.8 裁決**（AWS 資源名稱） | IAM user `personaldocai-admin`（`AdministratorAccess`，只給 CLI）＋ IAM user `personaldocai-mac` ＋ policy `personaldocai-mac-policy`；Budget `personaldocai-budget` 每月 $5、實際與預測各 80% | §4.3、§4.5、§4.6 逐字沿用這些名字 |
| **總覽 §10.2 追認項 I**（第二個 IAM user） | 再建一個 `personaldocai-admin` 只給 Mac 上的 `aws` CLI 用；admin 的 key 只在 `aws configure`、mac 的 key 只在 `.env`；`.env` 載進 shell 後要 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` | §4.5／§4.7／§4.8、§4.10 的 CLAUDE.md 段、§7 陷阱 1 |
| **總覽 §7 鐵律 9** | Budget 必須在開戶第一天就建，**不可以挪到後面** | §4 的步驟順序：開戶 → MFA → **Budget** → CLI → IAM user |
| **總覽 §7 鐵律 10** | 文件裡永遠只寫變數名，不寫值 | 全檔遵守 |

---

## 2. 前置條件

### 2.1 前面的 phase

- **Phase 74〜81 全部完成**（階段甲：隱私閘門、fallback 契約、雲端路本機端、PDF）。
- **★G1 已由產品負責人明示通過**（見檔案最上面的門檻框）。**沒過不准開工。**

### 2.2 開工基線（實查，數字要對得上）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

pytest --collect-only -q | tail -1
# 預期：616 tests collected
#       （543 是增量五收工的基線；74〜81 共 +73 顆：11+10+4+12+9+10+10+7）

pytest -q
# 預期尾巴：616 passed，而且 0 skipped

git branch --show-current
# 預期：main（不是 master）

git status --short
# 預期：只有你自己知道的未追蹤檔（例如 dev-prompt）；app/ 與 tests/ 底下不該有未預期的變更
```

> ⚠️ **絕對不要同時跑兩份 pytest。** `tests/conftest.py` 的 `reset_tables` 每顆測試都會
> `TRUNCATE` 同一個測試庫，兩份同時跑會互相清掉對方的資料，症狀是**大量看似隨機的 404**
> 與 `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣。

### 2.3 本 phase 對顆數的影響

**+0 顆**（總覽 §2.7）。本 phase 是純人工操作，沒有任何自動化測試可以寫——
「AWS 帳號有沒有開好」不是 pytest 測得出來的事，而且 pytest **絕對不准連真 AWS**（總覽 §7 鐵律 2）。
所以做完之後 `pytest -q` 仍然是 **616 passed**。

### 2.4 你手上要先有的東西

| 東西 | 為什麼 | 備註 |
|---|---|---|
| 一個**沒有註冊過 AWS** 的 email | 註冊要收驗證信 | 用得到的話，Gmail 的 `你的名字+aws@gmail.com` 也算不同 email |
| 一支手機 | 註冊要收簡訊／語音驗證；root 的 MFA 也要用它 | MFA app 建議用內建的「密碼」App 或 Google Authenticator |
| 一張信用卡 | **註冊流程一定會要**（官方 FAQ：用來驗證身分與防濫用）。**Free plan 不會扣它**——FAQ 明文「升 Paid 之前不會向付款方式收費」；有些卡會看到一筆小額（常見 $1）的**暫時授權**做驗證，幾天後自動消失，那不是扣款 | 這一步不能跳過 |
| Homebrew | 裝 AWS CLI 用 | `brew --version` 有輸出就代表有 |

---

## 3. 範圍

### 做

1. 開一個 AWS 帳號，**方案選 Free plan**，主要區域選**東京 `ap-northeast-1`**。
2. 幫 **root** 帳號開 MFA，之後就不再用 root 做日常操作。
3. **第一天就建 Budget** `personaldocai-budget`：每月 $5、**實際**與**預測**各在 80% 寄信。
   （Console 步驟與等價 CLI 指令**兩種都寫**。）
4. `brew install awscli`，`aws configure` 設好東京區。
5. 建**兩個** IAM 身分（理由見下面的 ⚠ 框）：
   - `personaldocai-admin`：掛 AWS 受管政策 `AdministratorAccess`，**人**用它建資源（84／85／91／93 的 `aws` 指令都靠它）。
   - `personaldocai-mac`：掛自己寫的 `personaldocai-mac-policy`（`deploy/aws/mac-policy.json`），**程式**用它跑
     （S3 的 `documents/` 前綴 ＋ 兩條佇列的訊息動作——本機端與「Mac 上跑工人」的工人端都要，總覽 §10.2 N
     ＋ `ec2:DescribeInstances`，就這些；建 bucket／建佇列／清佇列都不行）。
6. 兩把 access key 各放一個地方：admin 的放 `aws configure`（給 CLI）、mac 的放 `.env`（給 worker 容器裡的 boto3）。
7. `aws sts get-caller-identity` 驗證。
8. `CLAUDE.md` 指令區新增一段「AWS（增量六）」。
9. commit（只有 `deploy/aws/mac-policy.json` 與 `CLAUDE.md` 兩個檔進版控）。

```text
┌─ ⚠ 為什麼要建**兩個** IAM user（總覽 §2.8 ＋ §10.2 追認項 I），請先讀完再動手 ─┐
│                                                                              │
│ design6 §6 只寫了「本機：最小權限」那一個身分（＝ `personaldocai-mac`）。    │
│ 但**光有它，Phase 84 的第一條指令就會失敗**：                                │
│                                                                              │
│     aws s3api create-bucket ...                                              │
│     → An error occurred (AccessDenied) ... s3:CreateBucket                   │
│                                                                              │
│ 因為 `personaldocai-mac-policy` 裡**故意沒有** `s3:CreateBucket`——           │
│ 程式從來不需要建 bucket，建 bucket 是**人**做的事。這正是 design6 §6         │
│ 「IAM 最小權限」要的效果，不是 bug。                                         │
│                                                                              │
│ 所以總覽 §2.8 多列了一個**只給人用**的身分 `personaldocai-admin`：           │
│                                                                              │
│     personaldocai-admin  ← 人（你）在終端機打 aws 指令時用；AdministratorAccess │
│     personaldocai-mac    ← 程式（worker 容器裡的 boto3）在跑時用；最小權限   │
│                                                                              │
│ 好處是所有 phase 的 `aws` 指令**一個字都不必改**（不必到處加 --profile），   │
│ 而「程式的權限被切得很死」這個安全性質也完整保留、還驗得出來                 │
│ （§6 驗收清單有一條就是故意用 mac 的 key 去 create-bucket，預期被拒）。      │
│                                                                              │
│ 代價只有一條規矩：shell 載入 .env 之後**一定要**                             │
│     unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY                            │
│ 不然環境變數會蓋掉 profile，CLI 就悄悄變成用 mac 那把 key（§7 陷阱 1）。     │
│                                                                              │
│ AWS 自己的建議也是這樣：不要用 root 做日常操作，先建一個管理者身分給人用。   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 建 S3 bucket | 那是 **Phase 84**。本 phase 建的 policy 已經用萬用字元 `personaldocai-mailbox-*` 把它涵蓋了，bucket 晚一點建也對得上 |
| 建 SQS 佇列 | 那是 **Phase 85** |
| 開 EC2「先試試看」 | 那是 **Phase 91／92**，而且中間還有 **★G2**。EC2 一開就開始扣點數 |
| 寫任何 Python | 本 phase 零程式碼。`boto3` 是 **Phase 83** 才加進 `requirements.txt` |
| 開 AWS Organizations 或 Control Tower | design6 §7 明文禁止：**會自動升 Paid 而且點數作廢** |
| 按任何「Upgrade to Paid plan」 | 升了就開始扣信用卡（D15 的目標是卡片 **$0**） |
| 開 AWS Support 付費方案 | Basic（免費）就夠。Developer 方案每月最少 $29 |
| 開啟第二個區域的資源 | design6 §7「單區；不做跨區複製」。全部東京 `ap-northeast-1` |
| 幫 root 建 access key | root 的 key 一旦外洩沒有任何補救。**永遠不要建** |
| 把 `.env` commit 進版控 | `.gitignore` 已經擋了 `.env`；再確認一次而已 |
| 把 access key 寫進 `docs/`、`README.md`、`CLAUDE.md` 或任何 commit | 總覽 §7 鐵律 10。文件只寫**變數名** |
| 改 `compose.yaml` | 本增量 `compose.yaml` **零改動**（總覽 §7 鐵律 11）。AWS 設定全部走 `.env`，而 `.env` 已經是 bind-mount 了 |
| 改任何既有測試 | 本 phase 一顆測試都不碰。顆數維持 616 |

---

## 4. 實作步驟

> 🧰 **本 phase 是「人工操作型」**：沒有 TDD 的紅綠循環，改成
> **指令／畫面步驟 → 預期輸出 → 做錯了怎麼退回 → 費用影響**。
> 每一步做完就把 `- [ ]` 打勾，中途離開也回得來。

### 4.1 開一個 AWS 帳號（Free plan、東京）

- [ ] 用瀏覽器開 <https://aws.amazon.com/free/> → 按 **Create a free account** 註冊。
      過程大約 5〜10 分鐘，會問：email、帳號名稱（隨便取，例如 `personaldocai`）、
      密碼、聯絡地址、信用卡、手機驗證碼。

- [ ] **⚠ 選方案那一頁：一定要選 `Free`，不要選 `Paid`。**
      2025-07-15 之後的新帳號會問你要哪一種：

      | 選項 | 意思 | 本專案 |
      |---|---|---|
      | **Free plan** | 送點數；**升 Paid 之前不扣信用卡**；6 個月或點數用完先到者關帳 | ✅ **選這個** |
      | Paid plan | 一般帳號，用多少扣多少 | ❌ 不要 |

- [ ] 支援方案（Support plan）選 **Basic – Free**。

- [ ] 登入 Console 之後，**右上角的區域切成「Asia Pacific (Tokyo) ap-northeast-1」**。
      這個選單決定「你在 Console 上看到的是哪一區的資源」——切錯區的話，
      之後在 Console 找不到自己建的 bucket／佇列，會以為東西不見了。

**預期看到的：** 登入後右上角顯示你的帳號名稱，區域顯示 `Tokyo`。

**做錯了怎麼退回：**
- 不小心選到 Paid：到 Console 右上角帳號選單 → **Billing and Cost Management** → 看目前方案。
  官方 FAQ 明文：**Paid plan 不能降回 Free plan**。
  最省事的做法是**換一個 email 重開一個帳號**，並把這個帳號的資源刪乾淨。
- 不小心開了 Organizations／Control Tower：**立刻停下來問產品負責人**。
  design6 §7 明文禁止，因為它會把帳號自動升成 Paid 並讓點數作廢。

**費用影響：** 開戶本身 $0。有些卡會出現一筆小額（常見 $1）的**暫時授權**（不是扣款），幾天後自動消失。
⚠ **開戶當天就開始算 Free plan 的 6 個月**——這就是為什麼 ★G1 沒過不准開戶。

---

### 4.2 幫 root 帳號開 MFA，然後就把它收起來

- [ ] Console 右上角帳號選單 → **Security credentials** →
      找到 **Multi-factor authentication (MFA)** → **Assign MFA device**。
      （AWS 從 2024 年起陸續**強制** root 開 MFA——第一次登入就被要求綁的話，照這一節做即可，不是異常。）
- [ ] 選 **Authenticator app**，用手機掃 QR，連續輸入兩組六位數動態碼完成綁定。
- [ ] 綁好之後**登出 root**。從這裡開始，日常操作一律用 §4.5 建的 `personaldocai-admin`。

**預期看到的：** Security credentials 頁的 MFA 區塊列出一台裝置，狀態是已啟用。

**做錯了怎麼退回：** 手機掉了 / app 重灌導致算不出動態碼 → 用 AWS 的
「Sign in using alternative factors」流程（email ＋ 電話驗證）救回，然後刪掉舊裝置重綁。
所以**手機換機前記得先移轉 MFA**。

**費用影響：** $0。

> 🔐 **為什麼 root 一定要開 MFA：** root 的權限**無法用 policy 限制**，
> 它可以關掉帳號、可以改帳單、可以刪光所有東西，而且**沒有任何「上一層」可以救**。
> 密碼外洩 ＝ 整個帳號沒了。MFA 是唯一有效的鎖。

---

### 4.3 **第一天就建 Budget**（總覽 §7 鐵律 9：不可以挪到後面）

> **為什麼是第一天：** Free plan **不扣卡**，所以「刷爆卡」不是風險；
> 真正的風險是**點數安靜地被燒完 → 關帳 → 資源消失**。
> 沒有警報就等於閉著眼睛燒。$5／月是刻意設得很低的門檻——
> 本專案正常用量遠低於它，**一旦寄信來就代表有東西不對**（例如忘了 Stop 的 EC2）。

#### 做法 A：Console（第一天建議用這個——此時 CLI 還沒裝）

- [ ] 用 **root** 登入（這是 root 少數幾個該做的事之一）→ 右上角帳號選單 →
      **Billing and Cost Management** → 左側 **Budgets** → **Create budget**。
- [ ] 選 **Customize (advanced)** → Budget type 選 **Cost budget** → Next。
- [ ] 填：
      - Budget name：`personaldocai-budget`（**逐字**，總覽 §2.8 定的名字）
      - Period：**Monthly**
      - Budget renewal type：**Recurring budget**
      - Budgeting method：**Fixed**
      - Enter your budgeted amount：**5**（幣別 USD）
- [ ] Next → **Add an alert threshold**，加**兩條**：

      | 第幾條 | Threshold | Trigger | 意思 |
      |---|---|---|---|
      | 1 | **80** % of budgeted amount | **Actual** | 這個月**已經**花掉 $4 就寄信 |
      | 2 | **80** % of budgeted amount | **Forecasted** | 照這個速度**預測**月底會花到 $4 就寄信（更早知道） |

      ⚠ **Forecasted 那條前幾週不會叫是正常的**：AWS 官方說要累積約 **5 週**的用量才算得出預測，
      新帳號一開始只有 Actual 那條在工作。建立本身不會失敗。

- [ ] 兩條的 Email recipients 都填你自己的 email → Next → **Create budget**。
- [ ] 順手領點數：回到 Console 首頁找 **Explore AWS** 小方塊，「**AWS Budgets** — Create a budget with cost alerts」
      做完會多 **$20** 點數（官方公告的五個活動之一）。其他四個活動裡 RDS／Lambda／Bedrock 是 design6 禁止或用不到的服務，**不要為了 $20 去開**。

- [ ] **順手把「IAM 使用者可以看帳單」打開**。這個開關管的是 **Console 的帳單頁面**
      （Billing 首頁、Budgets、Bills……）：沒打開的話，之後用 `personaldocai-admin` 登入 Console
      會看不到方案與預算（就算它有 `AdministratorAccess`）。**CLI 的 `aws budgets` 不歸它管**——
      那是 API，靠 IAM policy 就能跑（官方文件明列 Budgets API 不受此開關控制）。步驟：
      root 登入 → 右上角帳號選單 → **Account** → 往下找
      **IAM user and role access to billing information** → **Edit** → 勾 **Activate** → Update。

**預期看到的：** Budgets 清單裡有一列 `personaldocai-budget`，Budgeted amount `$5.00`，
Alerts 欄顯示 2。

#### 做法 B：AWS CLI（§4.4／§4.7 裝好 CLI 之後才跑得動；想改金額或重建時用這個）

先把兩個佔位換成真值——**指令用變數，永遠不要把真的帳號 ID 打進文件**：

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
MY_EMAIL=你的email@example.com          # ← 改成你自己的；這一行不要 commit
```

建預算本體：

```bash
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget '{
    "BudgetName": "personaldocai-budget",
    "BudgetLimit": {"Amount": "5", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }'
```

- `--account-id`：預算掛在哪個帳號底下（12 位數字）。
- `--budget`：預算本體的 JSON。`BudgetLimit.Amount` 是**字串**不是數字（AWS 的規定）；
  `TimeUnit: MONTHLY` ＝ 每月重算；`BudgetType: COST` ＝ 看花掉的錢（另一種是看使用量）。

**預期輸出：** **完全沒有輸出**（成功的建立類指令回空 body）。有錯誤才會印字。

再加兩條通知（**一條指令只能加一條**，所以要跑兩次）：

```bash
aws budgets create-notification \
  --account-id "$ACCOUNT_ID" \
  --budget-name personaldocai-budget \
  --notification NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=80,ThresholdType=PERCENTAGE \
  --subscribers SubscriptionType=EMAIL,Address="$MY_EMAIL"

aws budgets create-notification \
  --account-id "$ACCOUNT_ID" \
  --budget-name personaldocai-budget \
  --notification NotificationType=FORECASTED,ComparisonOperator=GREATER_THAN,Threshold=80,ThresholdType=PERCENTAGE \
  --subscribers SubscriptionType=EMAIL,Address="$MY_EMAIL"
```

- `NotificationType`：`ACTUAL`＝已經花的；`FORECASTED`＝預測會花的。
- `ComparisonOperator=GREATER_THAN` ＋ `Threshold=80` ＋ `ThresholdType=PERCENTAGE`
  ＝「超過預算金額的 80%」＝ $4。
- `--subscribers`：收信的人。`SubscriptionType` 也可以是 `SNS`，本專案用 `EMAIL` 就好。

**預期輸出：** 兩條都是沒有輸出。

驗證（兩條指令）：

```bash
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Amount:BudgetLimit.Amount,Unit:BudgetLimit.Unit}' --output table
```

預期輸出長這樣（Amount 欄是 `5`——AWS 有時會回 `5.0`——單位 `USD`）：

```text
--------------------------------------------------
|                 DescribeBudgets                |
+-------------------------+-----------+----------+
|          Name           |  Amount   |   Unit   |
+-------------------------+-----------+----------+
|  personaldocai-budget   |  5        |  USD     |
+-------------------------+-----------+----------+
```

```bash
aws budgets describe-notifications-for-budget \
  --account-id "$ACCOUNT_ID" --budget-name personaldocai-budget \
  --query 'Notifications[].{Type:NotificationType,Th:Threshold}' --output table
```

預期：**兩列**，一列 `ACTUAL / 80.0`、一列 `FORECASTED / 80.0`。

**做錯了怎麼退回：**
- 金額或名字打錯 → `aws budgets delete-budget --account-id "$ACCOUNT_ID" --budget-name <打錯的名字>`，再建一次。
- 通知加錯 →
  `aws budgets delete-notification --account-id "$ACCOUNT_ID" --budget-name personaldocai-budget --notification NotificationType=<ACTUAL 或 FORECASTED>,ComparisonOperator=GREATER_THAN,Threshold=80,ThresholdType=PERCENTAGE`（要跟建立時那一組逐字相同才刪得到）。
- 收不到信 → 檢查垃圾郵件匣；另外 **Budget 的資料至少一天更新一次、不是即時的**，
  剛建好不會馬上有數字是正常的。

**費用影響：** 只寄通知、不掛「budget action」的預算**免費**（AWS Budgets 定價頁：monitor and receive notifications free of charge；帶 action 的前兩個也免費）。本專案只寄信、零 action → **$0**。

---

### 4.4 裝 AWS CLI

- [ ] 在 Mac 上執行：

```bash
brew install awscli
```

- [ ] 確認版本：

```bash
aws --version
```

**預期輸出**（版本號會不一樣，重點是開頭要是 `aws-cli/2.`）：

```text
aws-cli/2.31.11 Python/3.13.7 Darwin/25.5.0 source/arm64
```

**做錯了怎麼退回：**
- 印出 `aws-cli/1.x` → 你裝到舊版了（可能是以前用 `pip install awscli` 裝的）。
  `which aws` 看它在哪，把舊的移掉，或確認 `/opt/homebrew/bin` 在 `PATH` 的前面。
- `command not found: aws` → `brew` 裝完沒有重開終端機，或 `PATH` 沒有 `/opt/homebrew/bin`。

**費用影響：** $0（裝工具不花錢）。

---

### 4.5 建「人用」的管理者身分 `personaldocai-admin`

> 這一步一定要用 **root** 做——此時還沒有任何 IAM 使用者，只有 root 建得出來。

- [ ] root 登入 Console → 搜尋列打 **IAM** → 左側 **Users** → **Create user**。
- [ ] User name：`personaldocai-admin`
- [ ] 勾 **Provide user access to the AWS Management Console**（你之後要用它登入看畫面）
      → 選 **I want to create an IAM user**（**不要**選 Identity Center；
      那是給多人團隊用的，單人 side project 用不上，多一層要學的東西）
      → 密碼自己設。
- [ ] Next → **Attach policies directly** → 搜尋 **`AdministratorAccess`** → 勾起來 → Next → Create user。
- [ ]（建議）順手幫這個 user 也開 MFA：點進 user → **Security credentials** → **Assign MFA device**。
      它有 Console 密碼又是 `AdministratorAccess`，值得多一道鎖；步驟跟 §4.2 一樣。
- [ ] 建好之後點進這個 user → **Security credentials** 分頁 → **Access keys** → **Create access key**
      → Use case 選 **Command Line Interface (CLI)** → 勾下面那個「我了解」→ Next → Create access key。
- [ ] **⚠ 這一頁的 Secret access key 只顯示這一次。** 按 **Download .csv file** 存起來，
      或直接開著這一頁，**先跳去 §4.7 做 `aws configure`**（§4.6.2 的 CLI 指令要靠它），做完再回來 §4.6。

**預期看到的：** 一組 `Access key ID`（`AKIA` 開頭的 20 個字）與 `Secret access key`（40 個字）。

**做錯了怎麼退回：**
- Secret 沒存到、視窗關了 → 回到那個 user 的 Security credentials，**刪掉**那把 key，再建一把新的。
  （secret 沒有任何方法可以重看。）
- 不小心把 key 貼到聊天室／截圖／commit 裡 → **立刻刪掉那把 key**（Delete），再建新的。
  刪掉的當下它就完全失效了。

**費用影響：** IAM 本身 **$0**（不論建幾個 user 與 policy）。

---

### 4.6 建「程式用」的最小權限身分 `personaldocai-mac`

#### 4.6.1 先把 policy 檔寫進 repo

- [ ] 建目錄並新增檔案 `/Users/linjunting/personalDocAI/deploy/aws/mac-policy.json`，**整份逐字貼上**：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MailboxObjects",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::personaldocai-mailbox-*/documents/*"
    },
    {
      "Sid": "ListMailboxBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::personaldocai-mailbox-*"
    },
    {
      "Sid": "SendToJobsQueue",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-jobs"
    },
    {
      "Sid": "ReceiveFromResultsQueue",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-results"
    },
    {
      "Sid": "WorkerReceiveJobs",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-jobs"
    },
    {
      "Sid": "WorkerSendResults",
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-results"
    },
    {
      "Sid": "DescribeWorkerInstance",
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*"
    }
  ]
}
```

**這份 JSON 每一段在做什麼（新手逐段讀）：**

| 欄位 | 意思 |
|---|---|
| `Version` | IAM policy 的語言版本。**永遠是 `2012-10-17`**，不是日期也不是你的版本號 |
| `Statement` | 一串「允許／拒絕」的規則。本檔**七條**，全部是 `Allow`；**沒有寫到的動作預設就是拒絕**。`MailboxObjects`／`ListMailboxBucket`／`SendToJobsQueue`／`ReceiveFromResultsQueue`／`DescribeWorkerInstance` 是**本機端**要的，`WorkerReceiveJobs`／`WorkerSendResults` 兩條是**工人端**要的（理由見下面的框） |
| `Sid` | 這一條的代號，純粹給人看（出問題時 log 裡看得到是哪一條沒中） |
| `Action` | 允許呼叫哪些 API。`s3:PutObject` 就是 boto3 的 `put_object` |
| `Resource` | 允許對哪些資源做。這裡就是 §1 表格「最小權限」的落實 |
| `arn:aws:s3:::personaldocai-mailbox-*/documents/*` | S3 的 ARN **沒有區域也沒有帳號 ID**（bucket 名全球唯一，所以中間那兩段是空的）。`personaldocai-mailbox-*` 讓 bucket 還沒建也對得上；`/documents/*` 表示**只有這個前綴底下的物件**——程式碰不到 bucket 裡其他任何東西 |
| `ListMailboxBucket`（`s3:ListBucket`，Resource 是 **bucket 本身**的 ARN `arn:aws:s3:::personaldocai-mailbox-*`） | 表面上是「列出 bucket 裡有什麼」，實際上是為了 **404**。S3 官方規則：呼叫者**沒有** `s3:ListBucket` 時，對**不存在的 key** 做 GetObject 會回 **403 AccessDenied**，而不是 **404 NoSuchKey**。本增量到處靠 404 判「還沒有」——工人的冪等檢查（`result.json` 在不在）、本機崩潰重送的 `fetch_result`、`aws_check.py` 的刪後再讀。少了它，`get_object` 會把「還沒寫好」誤報成權限錯誤，一張圖都處理不了（總覽 §10.2 P）。⚠ Resource 是 bucket ARN、**沒有** `/documents/*`：ListBucket 是 bucket 層級的動作，寫成物件 ARN 不會生效。它是唯讀的，而且這個 bucket 裡本來就只有 `documents/` |
| `sqs:GetQueueAttributes` | 兩條佇列都加了它。`scripts/aws_check.py` 與人工煙霧要用它看「佇列裡現在有幾則訊息」；它是唯讀的，不影響最小權限的精神 |
| `WorkerReceiveJobs`（jobs 的 `ReceiveMessage`／`DeleteMessage`／`ChangeMessageVisibility`） | **工人端**的動作：從 jobs 佇列拿工作、做完刪掉、做不完把它還回去。本機端的程式碼**不會**呼叫它們（本機對 jobs 只 Send），但 Phase 88／90 在**這台 Mac 上跑工人**時用的是**同一把 `.env` 的 key**——少了這三個，工人第一次 `ReceiveMessage` 就 AccessDenied（總覽 §10.2 N） |
| `WorkerSendResults`（results 的 `SendMessage`） | 同上：工人做完把 `{"job_id"}` 丟進 results 佇列用的。EC2 上的工人**不用**這把 key（Phase 91 給它自己的 instance role），這四個工人端動作只是為了「EC2 出現之前，這台 Mac 同時扮演兩個角色」 |
| `ec2:DescribeInstances` 的 `Resource: "*"` | AWS 的 `DescribeInstances` **不支援限定單一實例**（它是「列出來給你看」型的 API），只能寫 `*`。它是唯讀的，看不到內容也改不了東西 |

**這份 policy 刻意**沒有**的東西（不是漏掉）：

- `s3:CreateBucket`／`s3:PutBucketPolicy`／`s3:DeleteBucket` → 建 bucket 是**人**做的事（Phase 84）
- `sqs:CreateQueue`／`sqs:PurgeQueue`／`sqs:DeleteQueue` → 建佇列與清佇列也是人做的事

```text
┌─ 為什麼這一把 key 同時有「本機端」與「工人端」的 SQS 動作（總覽 §10.2 N） ─┐
│                                                                              │
│ design6 §6 把權限分成兩列寫：本機只 Send jobs／Receive results，             │
│ 工人（EC2 的 instance role）才 Receive jobs／Send results。                  │
│                                                                              │
│ 但 EC2 要到 Phase 92 才出現。在那之前，工人是在**這台 Mac** 上跑的：         │
│   Phase 88  終端機直接跑 python -m app.workers.cloud_worker（它自己讀 .env） │
│   Phase 90  用容器 docker run --env-file .env 跑同一支工人                   │
│ 兩者拿到的都是 .env 裡這一把 personaldocai-mac 的 key——                      │
│ 這台 Mac 在那兩個 phase **同時是本機端、也是工人端**。                       │
│ 少了工人端那四個動作，工人第一次 ReceiveMessage 就 AccessDenied。            │
│                                                                              │
│ EC2 上的工人**仍然**用自己的 instance role（Phase 91），這把 key 絕不上 EC2。 │
│ 而「建 bucket／建佇列／清佇列」仍然不在這把 key 裡——那些走 admin。           │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### 4.6.2 建 IAM user 與 policy（CLI；**先跳去 §4.7 做完 `aws configure` 再回來做這一小節**）

> 📌 **順序小提醒：** 這一小節用 CLI，所以要先做 §4.7（把 admin 的 key 設進 `aws configure`）。
> 你也可以整段改用 Console 做（步驟見下面的「Console 等價作法」），那就不必先做 §4.7。

```bash
cd /Users/linjunting/personalDocAI
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws sts get-caller-identity --query Arn --output text   # 前提：結尾是 user/personaldocai-admin（§4.7 做完了）

# 把檔案裡的 <ACCOUNT_ID> 佔位換成真值，產生一份**暫時的**檔案（不進 repo）
sed "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" deploy/aws/mac-policy.json > /tmp/personaldocai-mac-policy.json

# 檢查一下換過了（應該看到兩行含 12 位數字的 sqs ARN，且沒有 <ACCOUNT_ID> 字樣）
grep -c "<ACCOUNT_ID>" /tmp/personaldocai-mac-policy.json     # 預期：0
```

```bash
# ① 建 policy
aws iam create-policy \
  --policy-name personaldocai-mac-policy \
  --policy-document file:///tmp/personaldocai-mac-policy.json
```

- `--policy-document file://<路徑>`：**三條斜線**。`file://` 是固定前綴，
  後面接的 `/tmp/...` 本身就以 `/` 開頭，所以看起來像三條。少一條的話 CLI 會去找相對路徑。

**預期輸出**（`Arn` 那一行的數字是你的帳號 ID，這裡用佔位表示）：

```json
{
    "Policy": {
        "PolicyName": "personaldocai-mac-policy",
        "PolicyId": "ANPA...",
        "Arn": "arn:aws:iam::<ACCOUNT_ID>:policy/personaldocai-mac-policy",
        "Path": "/",
        "DefaultVersionId": "v1",
        "AttachmentCount": 0,
        "IsAttachable": true,
        "CreateDate": "2026-..."
    }
}
```

```bash
# ② 建 user
aws iam create-user --user-name personaldocai-mac

# ③ 把 policy 掛上去
aws iam attach-user-policy \
  --user-name personaldocai-mac \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/personaldocai-mac-policy"

# ④ 建 access key（★ 輸出含 secret，**不要**貼進任何檔案或聊天室）
aws iam create-access-key --user-name personaldocai-mac
```

**④ 的預期輸出長相**（真值請自己看終端機，不要抄進文件）：

```json
{
    "AccessKey": {
        "UserName": "personaldocai-mac",
        "AccessKeyId": "AKIA................",
        "Status": "Active",
        "SecretAccessKey": "........................................",
        "CreateDate": "2026-..."
    }
}
```

**Console 等價作法**（不想用 CLI 的話）：
IAM → Policies → **Create policy** → 切到 **JSON** 分頁 → 貼上 §4.6.1 那份
（**記得把 `<ACCOUNT_ID>` 換成真的 12 位數字**）→ Next → Policy name 填 `personaldocai-mac-policy` → Create。
再 IAM → Users → **Create user** → name `personaldocai-mac` →
**不要**勾 Console access（程式不需要登入畫面）→ Next → **Attach policies directly** →
搜尋 `personaldocai-mac-policy` 勾起來 → Create user →
點進去 → Security credentials → **Create access key** → use case 選
**Application running outside AWS** → Create。

**做錯了怎麼退回：**
- policy JSON 打錯（例如少一個逗號）→ CLI 會回
  `An error occurred (MalformedPolicyDocument)`。修檔案再跑一次即可，**什麼都不會被建立**。
- policy 已存在（重跑第二次）→ `EntityAlreadyExists`。要改內容的話用
  `aws iam create-policy-version --policy-arn <arn> --policy-document file:///tmp/... --set-as-default`
  （一份 policy 最多留 5 個版本，改超過四次要先用 `aws iam delete-policy-version` 清掉舊版）。
- 整組想重來：
  ```bash
  aws iam delete-access-key --user-name personaldocai-mac --access-key-id <那把 key 的 ID>
  aws iam detach-user-policy --user-name personaldocai-mac \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/personaldocai-mac-policy"
  aws iam delete-user --user-name personaldocai-mac
  aws iam delete-policy --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/personaldocai-mac-policy"
  ```
  （順序不能顛倒：user 身上還掛著 key 或 policy 時刪不掉。）

**費用影響：** $0。

---

### 4.7 `aws configure`：把 **admin** 的 key 設給 CLI

- [ ] 執行（會問四個問題）：

```bash
aws configure
```

依序輸入：

| 問題 | 填什麼 |
|---|---|
| `AWS Access Key ID [None]:` | **`personaldocai-admin`** 的 Access key ID |
| `AWS Secret Access Key [None]:` | 同一個 user 的 Secret（**貼上時終端機不會顯示**，是正常的） |
| `Default region name [None]:` | `ap-northeast-1` |
| `Default output format [None]:` | `json` |

- [ ] 確認寫進去了（**只看變數名與區域，不要 `cat` 那個檔**）：

```bash
aws configure list
```

**預期輸出**（`access_key` 那一列只會露出後四碼，前面是星號——這是 CLI 故意的）：

```text
      Name                    Value             Type    Location
      ----                    -----             ----    --------
   profile                <not set>             None    None
access_key     ****************ABCD shared-credentials-file
secret_key     ****************WXYZ shared-credentials-file
    region           ap-northeast-1      config-file    ~/.aws/config
```

> 📌 **為什麼 admin 的 key 放這裡、mac 的 key 放 `.env`：**
>
> ```text
>   ~/.aws/credentials   ← 只有這台 Mac 的「人」看得到；容器**沒有**掛這個目錄
>          │
>          └── personaldocai-admin（AdministratorAccess）
>              給你在終端機打 aws 指令用：建 bucket、建佇列、看狀態
>
>   .env（bind-mount 進 app 與 worker 容器）
>          │
>          └── personaldocai-mac（最小權限）
>              給程式裡的 boto3 用：Put/Get/Delete documents/、Send jobs、Receive results
>              （Mac 上跑工人的 Phase 88／90 還多用：Receive jobs、Send results）
> ```
>
> 這樣分的好處：**所有 phase 的 `aws` 指令都不必加 `--profile`**，而程式的權限依然被切得很死。

**做錯了怎麼退回：** 打錯就再跑一次 `aws configure` 覆蓋掉即可（它會顯示舊值的後四碼當預設，
直接按 Enter 就是「不改」）。

**費用影響：** $0。

- [ ] ✅ 做完這裡，**回到 §4.6.2** 用 CLI 把 `personaldocai-mac` 建起來（§4.6.1 的檔案這時應該已經寫好了）。

---

### 4.8 把 **mac** 的 key 寫進 `.env`（給容器裡的 boto3）

- [ ] 用編輯器打開 `/Users/linjunting/personalDocAI/.env`，在最後面加上這幾行
      （**等號右邊填你自己的值；本文件永遠不寫值**）：

```ini
# ── AWS（增量六）────────────────────────────────────────────────
# 這一組是 IAM user personaldocai-mac 的 key（最小權限，只給程式用）。
# 容器看不到 ~/.aws，所以一定要放在這裡（compose 已經 bind-mount 了 .env）。
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-northeast-1

# 這三個等 Phase 84／85 建好資源之後才填得出來，先留空
S3_BUCKET=
SQS_JOBS_QUEUE_URL=
SQS_RESULTS_QUEUE_URL=

# 雲端路的開關：off ＝完全不走雲端（現在就先維持 off）
CLOUD_ROUTE=off
```

- [ ] 讓容器重新讀 `.env`（`.env` 是 bind-mount，但**行程只在啟動時讀一次**）：

```bash
cd /Users/linjunting/personalDocAI
# 開發模式（有疊 compose.dev.yaml）：
docker compose -f compose.yaml -f compose.dev.yaml restart app worker
# 常駐模式就把 -f compose.dev.yaml 拿掉；restart 只是重啟、不重建容器，兩種寫法都行
```

- [ ] 確認容器裡真的看得到（**只印變數名有沒有值，不印值**）：

```bash
# ⚠ 一定要先 import app.core.config：.env 是掛成「檔案」，不是注入容器的環境變數，
#   是 config.py 匯入時的 load_dotenv() 把它讀進 os.environ。少了 import 會永遠印 False（不是 .env 壞了）
docker compose exec worker python -c "import os, app.core.config; print('KEY_SET =', bool(os.getenv('AWS_ACCESS_KEY_ID')))"
```

**預期輸出：**

```text
KEY_SET = True
```

**做錯了怎麼退回：**
- 印出 `False` → 四種可能：① `.env` 存檔了嗎 ② 有沒有 restart ③ 是不是把值寫在
  `AWS_ACCESS_KEY_ID = xxx`（**等號兩邊不可以有空白**，`.env` 不是 Python）
  ④ 檢查指令漏了 `import app.core.config`（沒有它 `os.getenv` 永遠是 `None`，因為 `.env` 不是容器環境變數）。
- ⚠ **`.env` 檔不見了**：`compose.yaml` 有一條 `./.env:/app/.env` 的 bind-mount，
  來源檔不存在時 Docker **不會報錯，它會默默建一個叫 `.env` 的「資料夾」**。
  看到 `.env` 變成資料夾就把它刪掉、重建檔案、再 `docker compose up -d`。

**費用影響：** $0。

---

### 4.9 驗證：`aws sts get-caller-identity`

- [ ] 這是「我連得上 AWS 嗎、我現在是誰」的萬用檢查。它**不需要任何權限**，
      所以只要 key 是對的就一定會成功——非常適合當第一個測試。

```bash
aws sts get-caller-identity
```

**預期輸出**（三個欄位；真值不要貼進任何檔案）：

```json
{
    "UserId": "AIDA................",
    "Account": "<ACCOUNT_ID>",
    "Arn": "arn:aws:iam::<ACCOUNT_ID>:user/personaldocai-admin"
}
```

`Arn` 的結尾是 **`user/personaldocai-admin`** 才對——如果是 `personaldocai-mac`，
代表你把兩把 key 放反了（或是 shell 裡有 `AWS_ACCESS_KEY_ID` 環境變數蓋掉了 profile，見 §7 陷阱 1）。

- [ ] 順手把區域也確認一次：

```bash
aws configure get region
```

**預期輸出：**

```text
ap-northeast-1
```

**做錯了怎麼退回：**

| 錯誤訊息 | 意思 | 怎麼修 |
|---|---|---|
| `Unable to locate credentials` | CLI 找不到金鑰 | 重跑 `aws configure` |
| `InvalidClientTokenId` | Access key ID 打錯，或那把 key 已被刪 | 重新建一把 key 再 configure |
| `SignatureDoesNotMatch` | Secret 打錯（常見：貼上時多了空白或換行） | 重新 configure，貼的時候小心 |
| `You must specify a region` | 沒設 region | `aws configure set region ap-northeast-1` |

**費用影響：** `sts:GetCallerIdentity` 免費。

---

### 4.10 `CLAUDE.md` 指令區新增「AWS（增量六）」一段

- [ ] 打開 `/Users/linjunting/personalDocAI/CLAUDE.md`，在「## 指令」那個 code block 裡、
      **「跑測試」那一段的前面**插入下面這一整段（繁體中文，與檔案其他段落同體例）：

```bash
# ── AWS（增量六 Phase 82 起）────────────────────────────────────────
# 區域固定東京 ap-northeast-1。帳號是 **Free plan**（點數制，升 Paid 前不扣卡）。
# ⛔ 不要按 Console 上的 "Upgrade to Paid plan"；⛔ 不要開 Organizations／Control Tower
#    （會自動升 Paid 而且點數作廢）。
#
# 這台 Mac 上有**兩個** AWS 身分，用途完全分開，不要弄混：
#   personaldocai-admin  ← 人用的（AdministratorAccess）。key 在 ~/.aws（aws configure）
#                           所有 `aws ...` 指令都用它，不必加 --profile
#   personaldocai-mac    ← 程式用的（最小權限：documents/ 前綴 ＋ 兩條佇列 ＋
#                           ec2:DescribeInstances；建 bucket／建佇列／清佇列都不行）。key 在 .env，
#                           給 worker 容器裡的 boto3；Phase 88／90 在 Mac 上跑工人也是用它（總覽 §10.2 N）
#
# 我是誰／連得上嗎（不需要任何權限，最適合當第一個檢查）
aws sts get-caller-identity          # Arn 結尾要是 user/personaldocai-admin
aws configure get region             # 預期：ap-northeast-1

# 預算警報（每月 $5，實際與預測各 80% 寄信；開戶第一天就建好了）
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Amount:BudgetLimit.Amount,Unit:BudgetLimit.Unit}' --output table

# ⚠ 想在 shell 裡用 .env 的變數（$S3_BUCKET 之類）時，**不要**整份載進來就打 aws 指令：
#   .env 裡的 AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY 是**程式用的最小權限 key**，
#   而環境變數的優先序比 ~/.aws 高 → CLI 會改用它 → 建資源時 AccessDenied。
#   正確寫法（載完馬上把那兩個丟掉，讓 CLI 回去用 admin 的 profile）：
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
echo "$AWS_REGION / $S3_BUCKET"      # 確認讀到了；⚠ 不要把輸出貼進任何文件

# ⛔ 機密永遠只寫變數名，不寫值：access key、OLLAMA_API_KEY、實例 ID 一個字都不准
#    出現在 docs/、README.md、LAUNCH.md、CLAUDE.md、deploy/ 或任何 commit 裡。
#    .env 不入版控（.gitignore 已擋）。deploy/aws/*.json 裡的帳號 ID 一律寫 <ACCOUNT_ID>。
```

**預期結果：** `CLAUDE.md` 多這一段，其他內容一個字都沒動。

**做錯了怎麼退回：** `git diff CLAUDE.md` 看一眼；貼錯地方就 `git checkout -- CLAUDE.md` 重來。

---

### 4.11 commit

> ⚠ **總覽 §7 鐵律 12：commit 節奏由產品負責人決定。** 他沒指示前先不要 commit，
> 指令留在這裡備用；驗收改用「與開工前的 `git status` 快照相減」。

- [ ] **僅在產品負責人指示 commit 時**執行：

```bash
cd /Users/linjunting/personalDocAI
git add deploy/aws/mac-policy.json CLAUDE.md
git commit -m "docs: Phase 82 AWS 帳號與工具——Free plan 開戶（東京、root MFA）、開戶第一天建 Budget personaldocai-budget（每月 \$5、ACTUAL 與 FORECASTED 各 80% 寄信）、brew install awscli、兩個 IAM 身分（personaldocai-admin 給人打指令、personaldocai-mac 最小權限給程式）、deploy/aws/mac-policy.json 落地、access key 分別放 aws configure 與 .env、CLAUDE.md 指令區新增 AWS 段；零程式碼變更、顆數仍 616"
```

- [ ] **確認 `.env` 沒有被 commit 進去**（最重要的一條）：

```bash
git check-ignore -q .env && echo "OK：.env 被 .gitignore 擋住" || echo "⛔ .env 沒被忽略，停手檢查 .gitignore"
git ls-files .env | grep -q . && echo "⛔ .env 已經被 git 追蹤，停手" || echo "OK：.env 不在版控裡"
git log -1 --stat
```

預期：兩行都印 `OK：…`；`git log -1 --stat` 只列到 `deploy/aws/mac-policy.json` 與 `CLAUDE.md` 兩個檔。

---

## 5. ASCII 圖

### 圖一：本 phase 在增量六路線上的位置

```text
  階段甲（74〜81）  全程零 AWS，行為與增量五 100% 相同
  ┌──────────────────────────────────────────────────────────────┐
  │ 74 隱私閘門規則版   75 本機模型備援   76 ingest_job 重構      │
  │ 77 雲端路契約＋第五道安全網   78 閘門接線   79 單圖   80 逾時  │
  │ 81 PDF                                                        │
  │ ★ 此時 CLOUD_ROUTE=off、get_cloud_route() 回 CloudRouteOff     │
  └──────────────────────────────┬───────────────────────────────┘
                                 │
        ★★★ 閘門 G1（人）：產品負責人說「可以開始花 AWS 資源」
             沒點頭 ＝ 停在這裡，一行 aws 指令都不准打
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ ★ Phase 82（本 phase）＝整個增量六第一次碰 AWS               │
  │                                                              │
  │   ① 開戶（Free plan、東京）   ② root MFA                     │
  │   ③ 建 Budget $5／月（★ 第一天，不可以往後挪）               │
  │   ④ brew install awscli ＋ aws configure                     │
  │   ⑤ 兩個 IAM 身分 ＋ deploy/aws/mac-policy.json              │
  │   ⑥ aws sts get-caller-identity 驗證                         │
  │                                                              │
  │   ⛔ 一個 bucket、一條佇列、一台 EC2 都還沒建                 │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
   83 aws_mailbox.py（boto3）→ 84 建 S3 → 85 建 SQS → 86 真 AWS 接線 → …
```

### 圖二：兩個身分、兩把鑰匙、各自能做什麼

```text
                          你的 AWS 帳號（Free plan、東京 ap-northeast-1）
                          Budget personaldocai-budget：$5／月，80% 寄信
                                        │
              ┌─────────────────────────┴──────────────────────────┐
              │                                                    │
   ┌──────────▼───────────┐                          ┌─────────────▼──────────────┐
   │ personaldocai-admin  │                          │ personaldocai-mac          │
   │ （人用；本 phase 建） │                          │ （程式用；本 phase 建）     │
   │ AdministratorAccess  │                          │ personaldocai-mac-policy   │
   └──────────┬───────────┘                          └─────────────┬──────────────┘
              │ access key 存在                                    │ access key 存在
              ▼                                                    ▼
   ~/.aws/credentials                                   .env（bind-mount 進容器）
   （只有這台 Mac 的「人」看得到；                       AWS_ACCESS_KEY_ID
     容器**沒有**掛這個目錄）                            AWS_SECRET_ACCESS_KEY
              │                                                    │
              ▼                                                    ▼
   終端機的 aws 指令                                     app／worker 容器裡的 boto3
   ・aws s3api create-bucket      （84）                 ・put/get/delete documents/*
                                                          （＋ListBucket，只為了 404，見 §4.6.1）
   ・aws sqs create-queue         （85）                 ・SendMessage → jobs 佇列
   ・aws ec2 run-instances        （92）                 ・Receive/Delete/改可見度 ← results
   ・aws iam create-role          （91／93）             ・ec2:DescribeInstances（探測）
   ・aws budgets describe-budgets （驗收）               ・Mac 上跑工人時（88／90）還多用：
                                                          Receive/Delete/改可見度 ← jobs
   ⚠ 這把 key 權限很大，只放在這台 Mac，                    SendMessage → results
     絕不進 .env、絕不進版控、絕不上 EC2
                                                        ⛔ 它**做不到**：建 bucket、建佇列、
                                                          刪佇列、清佇列（那些走 admin）
```

### 圖三：為什麼容器一定要走 `.env`

```text
   這台 Mac                                    Docker 容器（app / worker）
   ┌────────────────────────────┐              ┌──────────────────────────────┐
   │ ~/.aws/credentials         │   ✗ 沒掛     │                              │
   │   personaldocai-admin      │─────╳────────│  （容器裡根本沒有 ~/.aws）    │
   ├────────────────────────────┤              │                              │
   │ /Users/…/personalDocAI/    │              │                              │
   │   ./data     ─────────────────bind-mount──▶  /app/data                   │
   │   ./certs    ─────────────────bind-mount──▶  /app/certs                  │
   │   ./.env     ─────────────────bind-mount──▶  /app/.env                   │
   │     AWS_ACCESS_KEY_ID       │              │    ↑ boto3 靠 config.py 的   │
   │     AWS_SECRET_ACCESS_KEY   │              │      load_dotenv() 讀到它     │
   │     AWS_REGION              │              │                              │
   └────────────────────────────┘              └──────────────────────────────┘

   ⚠ 改 .env 之後**一定要** restart：行程只在啟動時讀一次
       docker compose -f compose.yaml -f compose.dev.yaml restart app worker
```

---

## 6. 驗收清單

> 每一條都附指令與預期輸出。全部打勾之後，Phase 83 才可以開工。

- [ ] **帳號是 Free plan、未升 Paid**（人工，Console）

  Console 右上角帳號選單 → **Billing and Cost Management** → 首頁看方案。
  預期：顯示 **Free plan**（有點數餘額與到期日）。**不是** Paid。

- [ ] **root 已開 MFA**（人工，Console）

  Console（root 登入）→ Security credentials → Multi-factor authentication。
  預期：列出一台已啟用的裝置。

- [ ] **Budget 存在，而且有兩條 80% 通知**

  ```bash
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
    --query 'Budgets[].BudgetName' --output text
  ```
  預期輸出：`personaldocai-budget`

  ```bash
  aws budgets describe-notifications-for-budget \
    --account-id "$ACCOUNT_ID" --budget-name personaldocai-budget \
    --query 'Notifications[].{Type:NotificationType,Th:Threshold}' --output table
  ```
  預期：**兩列**，`ACTUAL / 80.0` 與 `FORECASTED / 80.0`。

- [ ] **AWS CLI 是 v2，而且預設區域是東京**

  ```bash
  aws --version                 # 預期開頭：aws-cli/2.
  aws configure get region      # 預期：ap-northeast-1
  ```

- [ ] **CLI 的身分是 admin**

  ```bash
  aws sts get-caller-identity --query Arn --output text
  ```
  預期輸出結尾是 `:user/personaldocai-admin`（**不是** `personaldocai-mac`）。

- [ ] **policy 檔在 repo 裡，而且沒有寫死帳號 ID**

  ```bash
  cd /Users/linjunting/personalDocAI
  test -f deploy/aws/mac-policy.json && echo "檔案在"
  python3 -c "import json;json.load(open('deploy/aws/mac-policy.json'));print('JSON 合法')"
  grep -c "<ACCOUNT_ID>" deploy/aws/mac-policy.json          # 預期：4（四條 SQS ARN）
  grep -qE '[0-9]{12}' deploy/aws/mac-policy.json && echo "⛔ 檔案裡有 12 位數帳號 ID，改回 <ACCOUNT_ID>" || echo "OK：沒有寫死 12 位數帳號 ID"
  ```
  預期：印出「檔案在」「JSON 合法」「4」「OK：沒有寫死 12 位數帳號 ID」。

- [ ] **AWS 上真的有那個 policy，而且掛在 mac 這個 user 身上**

  ```bash
  aws iam list-attached-user-policies --user-name personaldocai-mac \
    --query 'AttachedPolicies[].PolicyName' --output text
  ```
  預期輸出：`personaldocai-mac-policy`

- [ ] **AWS 上那份 policy 的內容就是七條 Sid（`ListMailboxBucket` 與工人端兩條都沒漏）**

  ```bash
  POLICY_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/personaldocai-mac-policy"
  aws iam get-policy-version --policy-arn "$POLICY_ARN" \
    --version-id "$(aws iam get-policy --policy-arn "$POLICY_ARN" --query Policy.DefaultVersionId --output text)" \
    --query 'PolicyVersion.Document.Statement[].Sid' --output text
  ```
  預期輸出（`--output text` 把清單用 tab 接成一行）：
  `MailboxObjects  ListMailboxBucket  SendToJobsQueue  ReceiveFromResultsQueue  WorkerReceiveJobs  WorkerSendResults  DescribeWorkerInstance`

- [ ] **`.env` 有三個新變數，而且容器讀得到（只印布林值，不印值）**

  ```bash
  cd /Users/linjunting/personalDocAI
  grep -c '^AWS_ACCESS_KEY_ID=.' .env         # 預期：1
  grep -c '^AWS_SECRET_ACCESS_KEY=.' .env     # 預期：1
  grep -c '^AWS_REGION=ap-northeast-1' .env   # 預期：1
  docker compose exec worker python -c \
    "import os, app.core.config; print('KEY_SET =', bool(os.getenv('AWS_ACCESS_KEY_ID')), '| REGION =', os.getenv('AWS_REGION'))"
  # ↑ import app.core.config 不能省：.env 是掛成檔案、靠 load_dotenv() 才進 os.environ（§4.8）
  ```
  預期最後一行：`KEY_SET = True | REGION = ap-northeast-1`

- [ ] **最小權限真的有效**（★ 這一條是本 phase 最有價值的驗收：**故意做一件該被拒絕的事**）

  ```bash
  cd /Users/linjunting/personalDocAI
  # 用「程式那把 key」去建 bucket——**預期失敗**。
  # 外面那對小括號 ＝ 子 shell：括號裡載入的 .env 變數在右括號之後就自動消失，
  # 不會殘留到你接下來的 aws 指令（不必手動 unset）
  ( set -a; . ./.env; set +a
    aws s3api create-bucket --bucket "personaldocai-should-be-denied-$RANDOM" \
      --region ap-northeast-1 \
      --create-bucket-configuration LocationConstraint=ap-northeast-1 )
  ```
  **預期輸出**（看到 AccessDenied 才是對的。它順便證明了 `.env` 那把 key 是活的——
  key 打錯會回 `InvalidClientTokenId`／`SignatureDoesNotMatch`，不會是 AccessDenied）：
  ```text
  An error occurred (AccessDenied) when calling the CreateBucket operation: ...
  ```
  再確認 CLI 已經回到 admin（子 shell 結束後本來就該是）：
  ```bash
  aws sts get-caller-identity --query Arn --output text   # 結尾要是 :user/personaldocai-admin
  ```
  ⚠ 如果你**沒有**用小括號、直接在目前的 shell 跑了 `set -a; . ./.env; set +a`，
  那就一定要手動 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`（§7 陷阱 1）。

- [ ] **全量測試顆數沒變（616），而且 0 skipped**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```
  預期尾巴：`616 passed`，沒有任何 `skipped`。

- [ ] **端點仍是 22 支**（本增量從頭到尾都是 22，design6 §5）

  ```bash
  pytest tests/integration/test_nav_header.py::test_端點數仍為22 -q
  ```
  預期：`1 passed`

- [ ] **零外部依賴仍然成立**（本 phase 還沒裝 boto3，所以先兩個死埠；
      `AWS_ENDPOINT_URL` 從 **Phase 83** 起加入這一行）

  ```bash
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```
  預期：顆數與上一條**一模一樣**（616 passed）。

- [ ] **專案的 `data/` 沒被弄髒**（本 phase 零程式碼、零上傳，理應原封不動）

  ```bash
  cd /Users/linjunting/personalDocAI
  ls data/staging/ | wc -l          # 預期：0（或只剩正在跑的任務）
  git status --short data/ || true  # data/ 已被 .gitignore 擋掉，預期零輸出
  ```

- [ ] **`.env` 沒有進版控、機密沒有進任何檔案**

  ```bash
  cd /Users/linjunting/personalDocAI
  git check-ignore -q .env && echo "OK：.env 被 .gitignore 擋住" || echo "⛔ .env 沒被忽略，停手"
  git ls-files .env | grep -q . && echo "⛔ .env 已經被 git 追蹤，停手" || echo "OK：.env 不在版控裡"
  grep -rEl 'AKIA[0-9A-Z]{16}' docs/ deploy/ CLAUDE.md README.md LAUNCH.md 2>/dev/null \
    && echo "⛔ 有檔案含 access key，立刻刪掉那把 key 並清掉檔案" \
    || echo "OK：文件裡沒有 access key"
  ```
  預期：三行都印 `OK：…`。

- [ ] **`CLAUDE.md` 的 AWS 段落在**

  ```bash
  grep -n "AWS（增量六 Phase 82 起）" /Users/linjunting/personalDocAI/CLAUDE.md
  ```
  預期：恰一行命中。

- [ ] **git 收尾符合現行節奏**：產品負責人已指示 commit → §4.11 已執行；
      未指示（現行預設）→ 跳過 commit，改核對
      `git status --short -- deploy CLAUDE.md` 的新增項恰為那兩個檔。

---

## 7. 常見陷阱

> 每一條都是「症狀 → 原因 → 正解」。這些不是理論，是這一步真的會踩到的。

1. **症狀：** `aws s3api create-bucket` 回 `An error occurred (AccessDenied) ... s3:CreateBucket`，
   但你明明剛剛才 `aws configure` 過。
   **原因：** shell 裡有 `AWS_ACCESS_KEY_ID` 環境變數。boto3 與 AWS CLI 的憑證搜尋順序是
   **環境變數 → `~/.aws/credentials` → …**，環境變數**贏**。而
   `set -a; . ./.env; set +a`（總覽 §5 的載入寫法）會把 `.env` 裡**程式用的最小權限 key**
   載進環境變數，於是 CLI 改用它，當然建不了 bucket。
   **正解：** 載完 `.env` 之後馬上把那兩個丟掉：
   ```bash
   set -a; . ./.env; set +a
   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
   aws sts get-caller-identity --query Arn --output text   # 確認回到 :user/personaldocai-admin
   ```
   這一招在 Phase 84／85／86／91／92／93 每次要用 `$S3_BUCKET` 之類的變數時都要做。

2. **症狀：** 帳號忽然變成 Paid，點數不見了。
   **原因：** 按了「Upgrade to Paid plan」，或開了 **AWS Organizations／Control Tower**
   （design6 §7 明文禁止，就是因為它會自動升 Paid 並讓點數作廢）。
   **正解：** 這件事**沒有一鍵復原**。降不回 Free plan 的話，唯一乾淨的路是換 email 重開帳號、
   把舊帳號的資源刪光。所以 Console 上任何寫著 Upgrade／Enable Organization／Set up landing zone
   的按鈕，一律**不要按**，先問產品負責人。

3. **症狀：** Secret access key 沒抄到，那一頁關掉了。
   **原因：** AWS **只在建立當下顯示一次** secret，之後任何地方都看不到（設計如此）。
   **正解：** 不要想辦法找回來——**刪掉那把 key，重建一把**：
   ```bash
   aws iam list-access-keys --user-name personaldocai-mac \
     --query 'AccessKeyMetadata[].AccessKeyId' --output text
   aws iam delete-access-key --user-name personaldocai-mac --access-key-id <上面印出來的 ID>
   aws iam create-access-key --user-name personaldocai-mac
   ```
   刪掉的那一刻它就完全失效了，所以**不小心貼到聊天室／截圖／commit 的 key 也用同一招處理**。

4. **症狀：** `.env` 明明改了，容器裡卻讀不到；或 `KEY_SET = False`。
   **原因：** 四種常見狀況——① 忘了 `docker compose restart app worker`（行程只在啟動時讀 `.env`）；
   ② 寫成 `AWS_ACCESS_KEY_ID = xxx`（**`.env` 的等號兩邊不可以有空白**，它不是 Python）；
   ③ **`.env` 變成了資料夾**——`compose.yaml` 有一條 `./.env:/app/.env` 的 bind-mount，
   來源檔不存在時 Docker **不報錯，直接建一個同名資料夾**，然後容器裡讀到空的、`load_dotenv()`
   靜靜地什麼都沒載入。
   ④ 檢查指令沒有 `import app.core.config`——`.env` 是掛成檔案、不是容器環境變數，
   要靠 `load_dotenv()` 才會進 `os.environ`，光 `import os` 去 `getenv` 永遠是 `None`。
   **正解：** `ls -la .env` 看它是檔案還是資料夾（開頭是 `d` 就是資料夾）→ 是資料夾就
   `rmdir .env`、重建檔案、`docker compose up -d`；是 ④ 就照 §4.8 的檢查指令寫（先 `import app.core.config`）。

5. **症狀：** Console 上找不到自己建的東西（bucket／佇列／實例都「不見了」）。
   **原因：** Console 右上角的**區域選單切到別區**了（常見：預設落在 `us-east-1`）。
   AWS 的資源絕大多數是**分區**的，切錯區就什麼都看不到。
   **正解：** 右上角切回 **Asia Pacific (Tokyo) ap-northeast-1**。
   CLI 那邊同理：`aws configure get region` 必須是 `ap-northeast-1`，
   或每條指令都帶 `--region "$AWS_REGION"`（本專案的文件一律帶，就是為了防這個）。

6. **症狀：** 用 `personaldocai-admin` 登入 Console，Billing 首頁／Budgets 頁是空的或寫著沒有權限，
   但它明明掛了 `AdministratorAccess`；CLI 的 `aws budgets describe-budgets` 卻好好的。
   **原因：** Console 的帳單頁面除了 IAM policy 之外，還受一個**帳號層級的開關**管：
   **「IAM user and role access to billing information」**。它沒打開的話，任何 IAM 身分都看不到那些頁面。
   官方文件同時明列：這個開關**不管** Budgets／Cost Explorer 的 **API**——所以 CLI 正常、Console 被擋，兩件事並不矛盾。
   **正解：** root 登入 → 右上角帳號選單 → **Account** →
   **IAM user and role access to billing information** → **Edit** → 勾 **Activate** → Update
   （§4.3 最後一步就是在做這件事）。反過來說：如果 CLI 的 `aws budgets` 回 `AccessDenied`，
   那是 §7 陷阱 1（shell 裡有 `.env` 的最小權限 key），不是這個開關。

7. **症狀：** 覺得「兩個 IAM user 好麻煩，乾脆給 `personaldocai-mac` 也掛 `AdministratorAccess`」。
   **原因：** 想省事。
   **後果：** design6 §6「IAM 最小權限」直接破功——`.env` 裡那把 key 是**會進容器**的，
   而容器裡跑的是會去讀網路檔案的程式。它一旦有 admin 權限，
   任何一個「讓程式做壞事」的漏洞就等於整個 AWS 帳號被接管。
   **正解：** 忍住。兩個 user 的成本是「多按五下滑鼠」，換到的是「程式最多只能弄髒
   `documents/` 這個前綴」。§6 驗收清單那條「故意被拒絕」的檢查就是在證明這件事有效。

8. **症狀：** 想幫 root 建 access key「這樣就不用建 IAM user 了」。
   **原因：** 看起來比較快。
   **後果：** root 的 key **權限無法限制、外洩沒有補救**，而且 AWS 的每一份安全指引都明文反對。
   **正解：** 永遠不要建 root 的 access key。root 在本專案只做這幾件事，做完就登出：
   開戶（§4.1）、開 MFA（§4.2）、建 Budget（§4.3 做法 A）、打開「IAM 可看帳單」的開關（§4.3）、
   建第一個 IAM user `personaldocai-admin`（§4.5）。之後全部用 admin，root 只留給帳務與救援。

9. **症狀：** `deploy/aws/mac-policy.json` 裡的 `<ACCOUNT_ID>` 被換成真值之後 commit 進去了。
   **原因：** 直接在原檔上 `sed -i` 而不是輸出到 `/tmp`。
   **後果：** 帳號 ID 不算最高機密，但它是「攻擊者要猜 role ARN 時的第一塊拼圖」，
   而且總覽 §7 鐵律 10 明文要求佔位。
   **正解：** `sed` 一律**輸出到 `/tmp`**（§4.6.2 就是這樣寫的），repo 裡那份永遠保持 `<ACCOUNT_ID>`。
   已經 commit 進去的話：把檔案改回佔位、再 commit 一次，並在 §6 驗收清單跑那條 `grep -c "<ACCOUNT_ID>"`。

10. **症狀：** 開戶了但 ★G1 其實還沒過。
    **原因：** 想「先把帳號開著、反正不花錢」。
    **後果：** **Free plan 的 6 個月從開戶當天開始算**（總覽 §8.4）。甲還沒驗收完就開戶，
    等於把最寶貴的免費視窗拿去空轉；而且 design6 §0 的第 1 條禁止寫得很清楚。
    **正解：** 等產品負責人那句話。等待期間可以做的事：把 Phase 74〜81 的驗收證據整理好。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- 一個 **Free plan** 的 AWS 帳號（東京 `ap-northeast-1`），root 已開 MFA。
- 一筆預算警報 `personaldocai-budget`：每月 $5，**實際**與**預測**各在 80% 寄信。
- 這台 Mac 上有 AWS CLI v2，`default` profile 是 **`personaldocai-admin`**（人用，AdministratorAccess）。
- AWS 上有一個最小權限的 IAM user **`personaldocai-mac`** ＋ 一份
  `personaldocai-mac-policy`（本機端＋「Mac 上跑工人」的工人端 SQS 動作都有，總覽 §10.2 N），它的 access key 只放在 `.env`（給容器裡的 boto3）。
- repo 裡多一個檔 `deploy/aws/mac-policy.json`（帳號 ID 用 `<ACCOUNT_ID>` 佔位，零機密）。
- `CLAUDE.md` 指令區多一段「AWS（增量六 Phase 82 起）」。

**對外行為變了沒：完全沒有。**

`CLOUD_ROUTE` 仍然是 `off`，`get_cloud_route()` 仍然回 `CloudRouteOff()`，
所以上傳、待決定、詢問、進度面板**一個像素都沒變**。
測試顆數仍是 **616 passed ＋ 0 skipped**，端點仍是 **22 支**、openapi 零 DELETE。
`app/` 與 `tests/` 底下**一行都沒動**。

**現在還沒有的東西**（刻意的）：

- 沒有 S3 bucket（Phase 84 建）
- 沒有 SQS 佇列（Phase 85 建）
- 沒有 EC2（Phase 91／92，而且要先過 ★G2）
- `requirements.txt` 裡**還沒有 `boto3`**，所以 Python 這邊完全不知道 AWS 存在

**下一個 phase：Phase 83「`aws_mailbox` 模組」**——
把 `boto3>=1.35` 加進 `requirements.txt`（本增量唯一的新套件）、
寫出 `app/services/aws_mailbox.py`（**全系統唯一 import boto3 的地方**）、
用手寫 stub client 寫 16 顆單元測試（**完全不連網**），
並且**改掉 design5 那顆「不准有 boto3」的掃碼測試**（design6 §1.1 第 1 列正式推翻它）。

**顆數：** 開工基線 **616** ＋ **0** ＝ **616**（總覽 §2.7、§9）。

---

## 附：本文件引用的官方文件

**AWS 帳號與費用**

- [AWS Free Tier](https://aws.amazon.com/free/)
- [AWS Free Tier FAQ（Free plan／點數／關帳的規則）](https://aws.amazon.com/free/free-tier-faqs/)
- [新帳號點數制公告（2025-07-15）](https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits/)
- [Free plan 可選服務清單（EC2／S3／SQS／ECR／IAM／STS／SSM／Budgets 都在裡面）](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html)
- [AWS Budgets：建立預算](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
- [`aws budgets create-budget`（CLI 參考；`--budget` 的 JSON 形狀）](https://docs.aws.amazon.com/cli/latest/reference/budgets/create-budget.html)
- [`aws budgets create-notification`（CLI 參考；`--notification` 與 `--subscribers`）](https://docs.aws.amazon.com/cli/latest/reference/budgets/create-notification.html)
- [AWS Budgets 定價（只寄通知的預算免費；帶 action 的前兩個免費）](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)
- [AWS Budgets 最佳實務（資料至少一天更新一次；預測型警報要累積約 5 週用量）](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html)
- [開放 IAM 身分存取帳單資訊](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/control-access-billing.html)

**AWS CLI 與憑證**

- [AWS CLI v2 安裝](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [`aws configure`（設定檔與 profile）](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)
- [CLI 的憑證搜尋順序（環境變數優先於 `~/.aws`）](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-authentication.html)
- [boto3 憑證與環境變數](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)

**IAM**

- [IAM 安全最佳實務（root 開 MFA、不建 root access key、最小權限）](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [IAM policy 語法（`Version`／`Statement`／`Action`／`Resource`）](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies.html)
- [IAM 的 ARN 格式](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference-arns.html)
- [S3 的 policy actions 與資源 ARN](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazons3.html)
- [S3 GetObject 的權限規則（沒有 `s3:ListBucket` 時，不存在的 key 回 403 而不是 404）](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)
- [SQS 的 policy actions 與資源 ARN](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonsqs.html)
- [EC2 的 IAM policy 結構（明文：`Describe*` 動作不支援資源層級權限，`Resource` 只能是 `*`）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-policy-structure.html)
- [EC2 的 policy actions 與資源 ARN（Service Authorization Reference）](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonec2.html)
- [`aws sts get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
