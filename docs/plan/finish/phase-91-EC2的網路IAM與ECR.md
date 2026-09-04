# Phase 91：EC2 的網路、IAM 與 ECR（人＋CLI；**尚不啟動實例**）

> 🎯 **提醒：這是 side project，不要過度設計。**
> **本 phase 特別不要做的四件事：**
> ① **不要啟動 EC2 實例**（`run-instances` 是 Phase 92 的第一步；一開就開始扣點數）。
> ② 不要建 NAT Gateway、Elastic IP、ALB、ECS／Fargate、Lambda——一個都不准
>    （design6 §0 禁止第 4 條、§1.2 倒數第 4 列）。
> ③ 不要為了「方便除錯」在 security group 開任何 inbound 規則（連 22 都不行）。
> ④ 不要在 policy JSON 裡寫死帳號 ID、bucket 名或佇列 URL——一律用佔位符。

> 📌 **2026-09-02 校準紀錄**（controller ledger：`.superpowers/sdd/phase0902-2/progress.md`）
> 本檔已依 2026-09-02 晚間工作樹（HEAD `bb3921a`）實查校準，十條裁決在本檔的落點：
>
> - **R0 不 commit**：§4.10 的 commit 步驟改成「不 commit——記工作樹快照」；§2／§6 的「只動了該動的檔」改用兩顆 tree SHA 相減（`.superpowers/sdd/phase0902-2/snapshot-tree`）。
> - **R1 識別字一律英文**：本檔的 shell 變數（`ACCOUNT_ID`／`VPC_ID`／`SUBNET_ID`／`RTB_ID`／`SG_ID`／`VPCE_ID`／`ECR_URI`／`ECR_REGISTRY`／`SHA`／`BEFORE_TREE`／`AFTER_TREE`）、JSON 的 `Sid`、systemd unit 的指令與 `worker.env.example` 的變數名**本來就全是英文**，複核後零改名；中文只留在註解與 `echo` 的訊息字串裡。
> - **R2 ★G2 條件式通過**：見下面那個門檻框（已改寫）。
> - **R3 AWS／docker／`.env`／煙霧由 controller 親做**：§2、§4.1〜§4.3、§4.5〜§4.7、§4.9、§4.10 與 §6 每一段會打 `aws`／`docker` 或改 `.env` 的步驟都加了「⚠ 本步驟由 controller 親自執行」。
> - **R4 顆數**：開工基線與收工顆數 **662 → 672**（2026-09-02 實查 `pytest -q` ＝ **644**，再加 Phase 87 +12／88 +5／89 +7／90 +4）。總覽 §9 的絕對值一律寫成「總覽 662（實 672）」雙寫法。
> - **R5**：本檔由校準者 E 單獨改，未動任何實檔、未動總覽、未動其他 phase 計畫檔。
> - **R6**：本 phase 零前端、零鏡頭，不需要產品負責人的手機或真機。
> - **R7**：`CLAUDE.md` 指令區那句過期話（「assume／ec2 要到 Phase 86／89 才接」）由 **Phase 89** 的實作者順手改，**不在本 phase**——本 phase 仍然一個字都不改 `LAUNCH.md`／`CLAUDE.md`／`README.md`。
> - **R8**：容器重建走 dev overlay 是 Phase 90 的事，本 phase 不碰 `docker build`／`compose`（只 `docker tag`／`docker push` 既有的映像）。
> - **R9**：`deploy/ec2/worker.env.example` **刪掉** `VLM_MAX_ATTEMPTS` 那兩行——`config.VLM_MAX_ATTEMPTS = 3` 是**寫死常數、不讀環境變數**，列在範本裡會讓人以為改得動（§4.8 已改，並補一行說明它為什麼不在）。
> - **R10**：與本 phase 無關（那是 Phase 90 的 compose 掃碼測試）。
>
> ⚠️ **另一件實查到的事：這台 Mac 的 `~/.aws` 裡沒有叫 `personaldocai-admin` 的 profile**——
> admin 那把 key 就放在 **default profile**（`aws configure` 設的），所以本檔每一條 `aws` 指令
> **一律不帶 `--profile`**。`docs/plan/aws/` 那五份「新手步驟」（產品負責人寫的）裡的
> `--profile personaldocai-admin` 在這台機器上會直接報 profile 不存在；那幾份只當**名詞對照**，
> 本 phase 不引用、不修改它們。

```text
┌─ ⛔ 開工前檢查（閘門 ★G2）─────────────────────────────────────────
│ ★ **★G2 已依 2026-09-02 controller 裁決 R2「條件式通過」。**
│   G2 ＝「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的那一句話。
│
│ 這一輪的憑據有三項，**缺一不可**：
│   ① 產品負責人的 dev-prompt `docs/plan/dev-prompts/phase0902-2.md`
│      **明示執行到 Phase 91**（總覽 §4 允許「一句明確的話**或** dev-prompt 檔案」當確認）；
│   ② Phase 88 的 **Mac 端到端**（工人直接在 Mac 上跑）由 **controller 親跑並通過**；
│   ③ Phase 90 的 **容器端到端**（arm64 映像在 Mac 上跑得起來）由 **controller 親跑並通過**。
│   ②③ 任一沒過 → **停在 Phase 90**，把 §4.7 的證據補齊再交一次，不要往下做。
│
│ ★ 為什麼這樣裁決算數：本 phase 建的東西**全部免費或極微量**
│   （SG／VPC endpoint／IAM 全免費，ECR 只有約 $0.04／月的儲存費），
│   而且**從頭到尾不 `run-instances`**——G2 真正在擋的「機器一開就扣點數」
│   在這一份裡不會發生。萬一產品負責人事後不認這次 G2，本 phase 建的每一樣都刪得掉、
│   零損失（刪法就寫在 §4.2／§4.3／§4.5／§4.6 各自的「做錯了怎麼退回」）。
│
│ ⛔ 但**下一份（Phase 92）的 `run-instances` 不吃這條**：那是第一個真的花點數的指令，
│   要另外拿到產品負責人對「可以開機器了」的明示。
│   本 phase §6 第 13 條就是在驗「零實例」。
│   ❌ 仍然不得：自行擴大解釋成「順手把機器也開起來看看」、
│               「反正測試都綠了」、「先開一下馬上關」。
└──────────────────────────────────────────────────────────────────
```

**總覽 §4 的 ★G2 表（逐字抄錄，方便對照）：**

| 項目 | 內容 |
|---|---|
| 是什麼 | 「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design6 §0 丁那列：本機模擬工人 jobs→S3→看圖→`result.json`→SendMessage results；本機 Receive 後 GetObject 入庫。**外加**：arm64 映像在 Mac 上跑得起來（Phase 90）。逐條指令見總覽 **§5.5** |
| 沒過會怎樣 | Phase 91〜95 全部停擺。理由很實際：EC2 一開就開始扣**點數**，而點數用完會**關帳**（Free plan 不扣卡，資源直接消失）。工人本身有 bug 的話，你會在一台看不到 shell、只能靠 SSM 的機器上除錯——比在 Mac 上難十倍 |
| 卡住時怎麼辦 | ① 先分清楚是「工人邏輯錯」還是「AWS 權限錯」——`python scripts/aws_check.py s3 sqs` 兩個都 OK 就是邏輯問題；② 工人邏輯錯 → 回 **87**（`process_job_message`）；③ 主迴圈或訊號處理錯 → 回 **88**；④ 映像 build 不出來或跑不動 → 回 **90**。**不要**「上 EC2 再說，反正那邊 log 也看得到」 |

> ⚠️ 上表是總覽 §4 的**原文**（一個字沒改），它寫的「誰確認」是**產品負責人**。
> 2026-09-02 這一輪的實際做法見上面的門檻框：**dev-prompt 明示 ＋ controller 親跑 88／90 的端到端**
> ——那是總覽允許的「dev-prompt 檔案」那一種確認方式，**不是**實作者自行勾掉。

> 🎯 **一句話目標：** 用 AWS CLI 把「那台 EC2 需要的周邊」全部備好——
> 一個 **inbound 完全空白**的 security group、一個**免費**的 S3 Gateway VPC endpoint、
> 一個 EC2 專用的 IAM role ＋ 同名 instance profile、一個 ECR repository，
> 並把 Phase 90 建好的 arm64 工人映像**第一次手動推上去**；
> 同時把三份要放進機器的檔案（開機腳本、systemd 服務、環境變數範本）寫進 `deploy/ec2/`。
> **本 phase 從頭到尾不啟動任何 EC2 實例。**

**為什麼要做這個：**

Phase 92 的 `run-instances` 那一行指令會一次引用**五樣**已經存在的東西：
subnet、security group、instance profile、AMI、user-data 腳本。
其中四樣是本 phase 要建的。

把它們分成兩個 phase 的理由很實際：**這一份裡的東西全部不花錢**
（SG、VPC endpoint、IAM 全免費；ECR 只有儲存費，工人映像約 0.4 GB ≈ $0.04／月，從點數扣），
所以可以慢慢建、建錯了刪掉重來也不心痛。
而 Phase 92 的第一行指令一下去，**碼表就開始跑**——到時候你不會想在
「IAM policy 少寫一個動作」這種事情上邊燒點數邊查。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **VPC（Virtual Private Cloud）** | 你在 AWS 裡的一個**私有網路**。每個帳號在每個區域都有一個「預設 VPC」，本專案直接用它，不自己建 |
| **subnet（子網）** | VPC 裡的一小段網路，綁在某一個可用區（Availability Zone）。**公有子網** ＝ 它的路由表有一條通往 internet gateway 的路，所以裡面的機器連得出去（也可以有公有 IP） |
| **route table（路由表）** | 「要去某個網段，該往哪個出口走」的對照表。每個 subnet 都關聯到一張。**main（主要）路由表**是 subnet 沒有特別指定時預設用的那一張 |
| **security group（SG，安全群組）** | 掛在機器上的**防火牆**。分兩個方向：**inbound（進來）**與 **outbound／egress（出去）**。本專案的 inbound **永遠是空的**——一條規則都沒有 |
| **CIDR** | 表示一段 IP 範圍的寫法，例如 `0.0.0.0/0` ＝「所有 IPv4 位址」。`/0` 是最寬的，`/32` 是單一台機器 |
| **egress 預設全開** | AWS 新建的 security group **自動帶一條 outbound 規則：允許所有協定到 `0.0.0.0/0`**。要收緊就得**先把它撤掉**（`revoke-security-group-egress`）再加自己要的那條——順序反了會變成「兩條並存」，等於沒收緊 |
| **VPC endpoint（Gateway 型）** | 一條「不出公網也能到 S3」的捷徑。做法是在**路由表**加一條路。**Gateway 型（S3／DynamoDB）完全免費**；另一種 Interface 型按小時計費，本專案**不用** |
| **IAM role（角色）** | 「一組權限」，但**沒有密碼**。要用它的人（EC2、GitHub Actions）去跟 AWS 換一組**幾小時就過期的臨時憑證**。比長期 access key 安全得多 |
| **trust policy（信任政策）** | role 的一份 JSON：「**誰**可以來借用我」。EC2 用的 role，它的 trust 要寫 `ec2.amazonaws.com` |
| **inline policy（內嵌政策）** | 直接寫在某個 role／user 身上的權限 JSON，不能給別人共用。指令是 `put-role-policy`。本專案用它（少一個要命名管理的獨立 policy 物件） |
| **managed policy（受管政策）** | AWS 或你自己建的**獨立**權限物件，可以掛給很多個 role。指令是 `attach-role-policy`。本專案只用一個 AWS 官方的：`AmazonSSMManagedInstanceCore` |
| **`AmazonSSMManagedInstanceCore`** | AWS 官方的一份 managed policy，內容是「SSM agent 要能跟 SSM 服務對話所需的最小權限」。**沒有它，Session Manager 進不去那台機器**，而我們又不開 SSH——就變成一台完全碰不到的機器 |
| **instance profile（實例設定檔）** | 把一個 IAM role「掛」到 EC2 上的那層包裝。掛好之後，機器裡的程式**什麼 key 都不必填**，boto3 自己就拿得到臨時憑證 |
| **ARN（Amazon Resource Name）** | AWS 每一個資源的全球唯一名字，長得像 `arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-jobs`（真的用的時候 `<ACCOUNT_ID>` 是你的 12 碼帳號）。policy 的 `Resource` 欄位寫的就是它 |
| **ECR（Elastic Container Registry）** | AWS 版的 Docker Hub（私有）。你把映像 `push` 上去，EC2 從那裡 `pull` 下來 |
| **registry / repository / tag** | `registry` ＝ 整個倉庫服務的網址（`<帳號>.dkr.ecr.<區域>.amazonaws.com`）；`repository` ＝ 裡面的一個專案（`personaldocai-worker`）；`tag` ＝ 那個專案的某一版（`latest`、`a53ab57`） |
| **`docker login --password-stdin`** | 把密碼**從標準輸入餵進去**，而不是寫在指令參數裡。差別很重要：寫在參數裡的密碼會留在 shell 歷史紀錄（`~/.zsh_history`）裡 |
| **user-data（開機腳本）** | 建 EC2 時附上的一段腳本，**只在第一次開機時**以 root 執行一次。本專案用它裝 Docker、建目錄、裝好 systemd 服務 |
| **systemd** | Linux 上管理「開機要跑哪些服務」的系統。一個服務 ＝ 一個 `.service` 檔（叫 **unit**），放在 `/etc/systemd/system/` |
| **`EnvironmentFile=`** | systemd unit 裡的一行：「這個服務跑起來之前，先把這個檔裡的 `KEY=VALUE` 讀成環境變數」。機密就放在那個檔（`chmod 600`），**不寫進 unit 檔** |
| **`ExecStartPre=`** | 「主程式開始之前先跑這些」。可以寫很多行，依序執行；**任何一行失敗，整個服務就啟動失敗**——除非在指令前面加一個 `-`（減號），那代表「這行失敗不算錯，繼續」 |
| **`Restart=always` / `RestartSec=10`** | 「不管怎麼結束的都重開」／「重開之前先等 10 秒」。網路暫時斷掉、ollama.com 掛一下，機器自己會回來 |
| **`WantedBy=multi-user.target`** | 「`systemctl enable` 之後，開機到『多使用者模式』時把我拉起來」。這就是「開機自動啟動」的意思 |
| **AL2023（Amazon Linux 2023）** | AWS 自己的 Linux 發行版。重點是它**預裝 SSM agent 與 AWS CLI v2**（官方文件：SSM Agent 預裝 AMI 清單含 AL2023；「AL2023 ships with AWS CLI version 2」），所以不開 SSH 也管得動 |
| **兩組 AWS 身分（admin／mac）** | Phase 82 定案：`personaldocai-admin`（`AdministratorAccess`）是**人**在終端機打 `aws` 指令用的，key 在 `~/.aws`（`aws configure` 的 default profile）；`personaldocai-mac` 是**程式**用的最小權限身分（S3 `documents/` 前綴＋兩條佇列＋`ec2:DescribeInstances`），key **只在 `.env`**。環境變數裡的 key 優先序比 `~/.aws` 高，所以 `set -a; . ./.env; set +a` 之後要**立刻** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，否則本 phase 每一條建資源指令都會 `AccessDenied`（§7 陷阱 10） |
| **IMDS（instance metadata service）／hop limit** | EC2 機器裡「問自己是誰」的小服務（`169.254.169.254`）；掛了 instance profile 之後，機器上的程式（`aws` CLI、容器裡的 boto3）就是跟它要臨時憑證。**hop limit** ＝它的回應最多能跨幾個網路「跳」：Docker 容器多一跳，所以 Phase 92 開機器時要設 `HttpPutResponseHopLimit=2`（AL2023 AMI 預設就是 2；§7 陷阱 11） |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D11** | 「EC2 只當工人。無公開 HTTP、無網站、無公網 API。**Security group inbound 全關**。出站 TCP 443（S3、SQS、ECR、SSM、ollama.com）」 | §4.2 建 SG：先 `revoke` 掉預設的全開 egress，再只放行 TCP 443；`IpPermissions` 驗證是 `[]` |
| **D15** | 「AWS 帳號 Free plan…目標卡片 **$0**」 | §4.3 的 S3 Gateway endpoint 是**免費**的那一種；ECR 只有儲存費（工人映像 ≈ $0.04／月，從點數扣）；本 phase 零運算費 |
| **D16 ＋ §0 表「己」那列** | 「ECR `personaldocai:<git-sha>`」（D16）＋「不靠 `latest` 當唯一 tag」（§0 表「己」列的驗收欄） | §4.6 建 repo；§4.7 第一次手動推**兩個** tag（`<sha>` 與 `latest`） |
| **§6「IAM 最小權限」那列** | 「EC2 instance role：S3 該 prefix 的 Get（input）／Put（result）；jobs 的 Receive／Delete；results 的 Send；ECR pull、SSM」 | §4.4 的 `deploy/aws/worker-role-policy.json` 逐條落地、§4.5 掛上 role（另加 `ChangeMessageVisibility` 與 bucket 層的 `s3:ListBucket`，理由見 §4.4） |
| **§7「網路」那列** | 「公有子網＋自動公有 IPv4（要連 ollama.com）。**禁止 NAT Gateway**。S3 可用免費 Gateway VPC endpoint」 | §4.1 找預設 VPC 的公有子網；§4.3 建 Gateway endpoint；全程零 NAT |
| **§7「管理」那列** | 「inbound 全關；Session Manager／Run Command」 | §4.5 掛 `AmazonSSMManagedInstanceCore`——沒有它就進不去那台機器 |
| **§11 第 7 列** | 「`LAUNCH.md`、`CLAUDE.md` 指令區｜戊／己」 | **不在本 phase**——文件是 Phase 92 的事（機器真的跑起來之後才寫得出正確的操作步驟） |
| **總覽 §2.8** | AWS 資源名稱表（SG／IAM role／ECR／VPC endpoint／systemd unit 那五列） | §4.2〜§4.8 的名稱**逐字**照抄 |
| **總覽 §10 追認項 e** | 「開機拉 `latest`；CD 同時推 `<sha>` 與 `latest`」 | §4.8 的 systemd unit：`ExecStartPre` 是 `docker pull …:latest` |
| **總覽 §10 追認項 h** | 「EC2 上的機密用 Session Manager 手動建 `/opt/personaldocai/worker.env`，**不用** Parameter Store」 | §4.8 的 `worker.env.example` 只寫變數名；user-data **刻意不 start** 服務（env 檔還沒放） |
| **總覽 §10.2 裁決 O** | 「unit 用 `ExecStop=/usr/bin/docker stop -t 120 cloud-worker` ＋ `TimeoutStopSec=150`：工人收到 SIGTERM 會做完手上那一則再退，多頁 PDF 可能超過 docker 預設的 10 秒寬限（超時＝SIGKILL；資料不會壞——D17 冪等＋jobs 900 秒後重投——但會多跑一次雲端看圖）」 | §4.8 的 unit **兩份**（獨立檔＋user-data 內嵌）逐字同步；說明寫在 unit 的註解與逐行表 |
| **總覽 §10.2 裁決 P** | 「`worker-role-policy.json` 加 `s3:ListBucket`，Resource 是 bucket ARN `arn:aws:s3:::<S3_BUCKET>`（不是 prefix ARN）：沒有 ListBucket 時對不存在的 key 做 GetObject 回 403 而不是 404，工人每則 jobs 開頭的冪等檢查 `get_object(result_key)` 會炸、一張圖都處理不了」 | §4.4 的 policy 多一個獨立 Statement `BucketListSoMissingKeyIs404`＋逐段解釋一列；佔位符計數跟著更新 |

> ⚠️ **「追認項 e」「追認項 h」與「§10.2 裁決 O、P」都是計畫層的裁決，不是 design6 自己寫的字**（總覽 §10 明文）。
> 產品負責人若想改成 Parameter Store，要同時改本 phase §4.4 的 role policy JSON
> （加 `ssm:GetParameter`，再重跑 §4.5 的 `put-role-policy`）與 Phase 92 的放 env 檔那一步。

---

## 2. 前置條件

**依賴：★G2 已依裁決 R2 條件式通過（見本檔最上面的門檻框），Phase 82／84／85／90 都已完成。**

> 📌 **2026-09-02 實查的現況（開工前先對一次）：**
> Phase 74〜86 全部完成，其中 **83〜86 已由產品負責人 commit**（HEAD `bb3921a`）；
> **87〜90 在本輪做完但依指示不 commit**（裁決 R0，驗收用工作樹快照）。
> `deploy/aws/` 目前**恰兩個檔**：`mac-policy.json`（Phase 82）與 `s3-lifecycle.json`（Phase 84），
> 兩個都 commit 過了；**`deploy/ec2/` 還不存在**，本 phase §4.4 才 `mkdir` 出來。
> `.env` 已經有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`（`personaldocai-mac` 那把最小權限 key）／
> `AWS_REGION`／`S3_BUCKET`／`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`／`CLOUD_ROUTE=off`／
> `CLOUD_RESULT_TIMEOUT_SECONDS=300`／`OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL`；
> **還沒有** `EC2_WORKER_INSTANCE_ID`（本 phase §4.9 加一行空的），
> 也**沒有** `AWS_ENDPOINT_URL`（那個只在 pytest 的第五道安全網用，不進 `.env`）。
> `scripts/aws_check.py` 已經在（Phase 84／85 建的），`s3` 與 `sqs` 兩個子指令都實測 OK。

| 來自 | 東西 | 怎麼驗 |
|---|---|---|
| Phase 82 | AWS 帳號（Free plan）、Budget、AWS CLI；**兩組身分**：`personaldocai-admin`（人打指令用，key 在 `~/.aws`＝`aws configure` 的 default profile）與 `personaldocai-mac`（程式用、最小權限，key 只在 `.env`） | `aws sts get-caller-identity --query Arn --output text` 結尾是 `:user/personaldocai-admin` |
| Phase 84 | S3 bucket，`.env` 有 `S3_BUCKET` | `aws s3api get-public-access-block --bucket "$S3_BUCKET"` |
| Phase 85 | 兩條 SQS 佇列，`.env` 有兩個 URL | `python scripts/aws_check.py sqs` |
| Phase 90 | 本機映像 `personaldocai-worker:local`（arm64） | `docker image inspect personaldocai-worker:local --format '{{.Architecture}}'`（⚠ docker 指令由 controller 執行） |

**開工基線：672 passed ＋ 0 skipped**（**2026-09-02 實查**）。
**本 phase 新增 0 顆測試**（做的全是 AWS 資源與部署設定檔），收工時顆數**仍是 672**。

> 📌 **672 這個數字怎麼來的（2026-09-02 實查）：** 本輪開工當下 `pytest -q` ＝ **644 passed／0 skipped**，
> 再加上本輪前四個 phase 的新增——87 **+12** → 656、88 **+5** → 661、89 **+7** → 668、90 **+4** → **672**。
> 總覽 §9 那張表這一列寫的是 **662（實 672）**：它的絕對值比實測**少 10**
> （74〜86 的 review fix wave 一路多補了幾顆），所以**只對「本 phase 新增幾顆」，不要拿絕對值去對**。

**開工前一次驗完：**

> ⚠️ **②〜⑤ 由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**
> （2026-09-02 裁決 R3）。①⑥ 是純本機檢查，誰跑都可以。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 顆數基線（本 phase 不會改變它）
pytest -q
# 預期：672 passed，0 skipped

# ② 把 .env 的變數載進 shell（$AWS_REGION／$S3_BUCKET 等一下要用），
#    先用它跑 Phase 84／85 的小工具（那支工具**刻意**用 .env 裡 personaldocai-mac 那把最小權限 key）
set -a; . ./.env; set +a          # set -a ＝之後每個賦值自動 export；.（點）＝在目前這個 shell 執行
python scripts/aws_check.py s3 sqs # 預期：兩行 OK（真的 put/get/delete 一個小物件、send/receive/delete 一則訊息）

# ③ ★ 馬上把「程式用的最小權限 key」丟掉，讓後面每一條 aws 指令回去用 ~/.aws 的 admin profile
#    （不做這一步，本 phase 每一條 create-* 都會 AccessDenied——本檔 §7 陷阱 10）
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

# ④ AWS CLI 通、而且是對的身分與區域
#    ⚠ 不帶 --profile：admin 那把 key 就在 aws configure 設的 **default profile**，
#      這台 Mac 上**沒有**叫 personaldocai-admin 的具名 profile（帶了會直接報 profile 不存在）
aws sts get-caller-identity --query Arn --output text
```

  預期：`arn:aws:iam::<12碼帳號>:user/personaldocai-admin`（**帳號 ID 不要貼進任何文件或 commit**）。
  結尾必須是 **`user/personaldocai-admin`**（Phase 82 §4.5 建的、掛 `AdministratorAccess`，
  key 放在 `aws configure` 設的 default profile）。
  - 結尾是 `user/personaldocai-mac` → 你漏了上面的 `unset`（`.env` 那兩把 key 蓋掉了 profile）。補跑 `unset` 再查一次。
  - 是別的名字或報錯 → `~/.aws/credentials` 裡放的不是 Phase 82 §4.7 設的那把 admin key，先修好再往下。

```bash
# ⑤ 前面三個 phase 的東西都在
echo "region=$AWS_REGION"                      # 預期：region=ap-northeast-1（來自 .env）
docker image inspect personaldocai-worker:local --format '{{.Architecture}}'   # 預期：arm64

# ⑥ 分支與工作區
git branch --show-current                      # 預期：main
git status --short -- deploy .env              # 預期：沒有輸出
#   （deploy/aws/ 裡已經有 Phase 82 的 mac-policy.json 與 Phase 84 的 s3-lifecycle.json，
#    兩個都 commit 過了；.env 被 .gitignore 擋著。有輸出＝上一個 phase 沒收乾淨，先處理）

# 開工快照：本輪**不 commit**（裁決 R0），改記「整個工作樹」的 git tree SHA，
# §6 最後拿它跟收工的那顆相減。這支小工具只在物件庫多一顆 tree 物件，
# 不碰真正的 index、不建 commit、不動 stash。
BEFORE_TREE=$(.superpowers/sdd/phase0902-2/snapshot-tree)
echo "BEFORE_TREE=$BEFORE_TREE"
```

> ⚠️ **`set -a; . ./.env; set +a` 之後，這個 shell 裡就有 `.env` 的所有值了（`OLLAMA_API_KEY` 等）；
> 緊接著的 `unset` 只丟掉那兩把 AWS key。**
> 不要在這個視窗跑 `env`／`printenv`，也不要把終端機截圖貼到任何地方。
> 要看某一個變數就只 `echo` 那一個（金鑰類的連 `echo` 都不要）。
>
> ⚠️ **兩組 AWS 身分，別搞混（Phase 82 定案）：**
> `personaldocai-admin`（`AdministratorAccess`）＝**人**打 `aws` 指令用，key 在 `~/.aws`（`aws configure`）；
> `personaldocai-mac`＝**程式**用，key 只在 `.env`、給 worker 容器裡的 boto3。
> 它的 policy（`deploy/aws/mac-policy.json`，2026-09-02 實查）是：S3 `documents/` 前綴的
> Put／Get／Delete ＋ **bucket ARN 的 `s3:ListBucket`**（總覽 §10.2 P）、
> jobs 的 Send ＋ **Receive／Delete／ChangeVisibility**、results 的 **Send** ＋ Receive／Delete／ChangeVisibility、
> 兩條佇列的 `GetQueueAttributes`、`ec2:DescribeInstances`
> ——jobs 收訊息與 results 送訊息那兩組是**工人端**要的（總覽 §10.2 N：這台 Mac 在 EC2 出現前
> 同時扮演本機端與工人端兩個角色）。
> 它**沒有** `iam:CreateRole`／`ec2:CreateSecurityGroup`／`ecr:*`／`s3:CreateBucket`／`sqs:PurgeQueue`，
> 所以本 phase 的建資源指令一律要用 admin——這就是為什麼載入 `.env` 之後要立刻 `unset`。
>
> ⚠️ **本 phase 每一個 `aws ec2`／`aws ecr` 指令都帶 `--region "$AWS_REGION"`。**
> 不帶的話 CLI 用 `~/.aws/config` 的預設區域（常是 `us-east-1` 美東），
> 於是 SG 建在美東、EC2 在東京，兩邊看不到對方，錯誤訊息還很難懂（`InvalidGroup.NotFound`）。

---

## 3. 範圍

### 做

1. 查出預設 VPC、一個公有子網、主要路由表的 id，存成 shell 變數。
2. 建 security group `personaldocai-worker-sg`：**inbound 一條都不加**；
   outbound **先撤掉預設的全開**，再只放行 TCP 443 到 `0.0.0.0/0`。
3. 建 S3 Gateway VPC endpoint（免費），掛在主要路由表上。
4. 寫 `deploy/aws/worker-role-trust.json` 與 `deploy/aws/worker-role-policy.json`；
   建 IAM role `personaldocai-worker-role`、掛 inline policy、
   掛 managed policy `AmazonSSMManagedInstanceCore`、
   建**同名**的 instance profile 並把 role 放進去。
5. 建 ECR repository `personaldocai-worker`（private，`scanOnPush=false`）。
6. `docker login` 到 ECR，把 Phase 90 的 arm64 映像打上 `<git-sha>` 與 `latest` 兩個 tag，推上去。
7. 寫三份要放進機器的檔案：`deploy/ec2/user-data.sh`、
   `deploy/ec2/personaldocai-worker.service`、`deploy/ec2/worker.env.example`。
8. `.env` 加一行 `EC2_WORKER_INSTANCE_ID=`（**先留空**，Phase 92 才填；⚠ 由 controller 親自改，裁決 R3）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| **`aws ec2 run-instances`（啟動實例）** | 那是 Phase 92 §4.3。實例一開，運算費與 EBS 就開始從**點數**扣。本 phase 全部是免費資源，慢慢做 |
| 開任何 inbound 規則（連 SSH 的 22 都不行） | design6 D11／§0 禁止第 3 條。要 shell 就用 SSM Session Manager（§4.5 掛的那個 managed policy 就是為了它）。`IpPermissions` 必須是 `[]`，Phase 92 §6 與總覽 §5.5 都會驗 |
| 建 NAT Gateway | design6 §0 禁止第 4 條、§7「網路」那列明文。NAT 是**按小時 ＋ 按流量**計費，會直接把 Free plan 點數打爆。我們的機器在**公有子網**、有公有 IP，本來就連得出去 |
| 配置 Elastic IP（`allocate-address`） | 總覽 §2.8 禁止清單。EIP 在**沒有掛到跑著的機器上時要收費**，而我們的機器常態是 Stop。用自動指派的公有 IP 就好（Stop 之後釋放、Start 之後換一個新的——**我們不需要固定 IP，因為沒有人會主動連進來**） |
| 建 Interface 型的 VPC endpoint（SQS／ECR／SSM 的） | 那種按小時計費。我們的機器有公網出口，這三個服務走公網的 HTTPS 就好。只有 S3 用 Gateway 型是因為它**完全免費** |
| 開 ECR 的 `scanOnPush`（推上去自動掃漏洞） | side project 不需要，而且掃描結果沒人看。明寫 `scanOnPush=false` 讓意圖清楚 |
| 在 policy JSON 裡寫死帳號 ID／bucket 名／佇列 URL | 那些檔案要進 git。一律用 `<ACCOUNT_ID>`／`<AWS_REGION>`／`<S3_BUCKET>` 佔位符，用的時候才 `sed` 展開到 `/tmp`（§4.5）。⚠ Phase 93 的掃碼測試 `test_部署用的policy裡沒有寫死帳號ID` 會掃 `deploy/aws/` **全部** JSON（含本 phase 這兩份），但那顆要到 Phase 93 才存在——在那之前 §4.10 的 `grep -rE "[0-9]{12}" deploy/` 是本 phase 唯一的防線，commit 前一定要跑 |
| 用 `--policy-document` 直接貼 JSON 字串 | 引號會被 shell 吃掉，錯誤訊息又極難懂（`MalformedPolicyDocument`）。一律用 `file://` 讀檔 |
| 建 Parameter Store 參數放機密 | 總覽 §10 追認項 h：用 Session Manager 手動放 env 檔就好，少一個服務、少一組權限 |
| 寫 `deploy/ec2/run-worker.sh` | 總覽 §2.7 把它列成「若採 `ExecStartPre` 寫法可省」。我們採 `ExecStartPre`，所以**不建這個檔**——少一個會跟 systemd unit 漂移的副本 |
| 改 `LAUNCH.md`／`CLAUDE.md`／`README.md` | 那是 Phase 92。機器還沒跑起來，寫出來的操作步驟沒有驗證過。⚠ `CLAUDE.md` 指令區那句過期話（「assume／ec2 要到 Phase 86／89 才接、現在 `get_cloud_route()` 會 `NotImplementedError`」）由 **Phase 89** 的實作者順手改掉（2026-09-02 裁決 R7），**也不是本 phase 的事** |
| 改任何 `app/` 底下的程式碼、`Dockerfile`、`compose.yaml` | 本 phase **零產品程式碼變更**、零測試變更 |

---

## 4. 實作步驟

> 📌 **本 phase 沒有測試可以先紅**（它建的是 AWS 資源與部署設定檔，不是 Python）。
> 所以每一步的體例改成：**指令 → 每個旗標的用途 → 預期輸出 → 做錯了怎麼退回 → 費用影響。**
> 掃 `deploy/` 的自動化測試要到 **Phase 93**（OIDC 那 4 顆，其中 `test_部署用的policy裡沒有寫死帳號ID`
> 會掃 `deploy/aws/` **全部** JSON、含本 phase 這兩份）與 **Phase 95**（收尾 10 顆）才追加；
> Phase 90 已經開了 `tests/integration/test_design6_error_paths.py`，但那 4 顆只掃 `Dockerfile`
> 與 `compose*.yaml`，**碰不到** `deploy/` 底下的檔——所以在 93 之前，§4.10 的 `grep` 是唯一的防線。

> ⚠️ **這一整節幾乎全部是 `aws` CLI ＋ `docker` 指令，外加改一行 `.env`。**
> **由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**
> （2026-09-02 裁決 R3）。subagent 拿到這一份時該做的只有「讀懂、確認步驟正確、回報疑慮」。
> 唯二不碰外部服務的是 **§4.4**（寫兩份 IAM JSON）與 **§4.8**（寫三份部署檔）——那兩節是純寫檔。

> ⚠️ **本節所有指令都在同一個終端機視窗裡跑**（因為 §4.1 設的 shell 變數只活在那個視窗裡）。
> 不小心關掉視窗的話，回 §4.1 重跑一次那五行就好——那幾行是純查詢，重跑不會建任何東西。

### 4.1 把要用的 id 查出來，存成 shell 變數

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] 先把 `.env` 帶進這個 shell、丟掉程式用的那兩把 key，並取得帳號 ID：

```bash
cd /Users/linjunting/personalDocAI
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ 讓 aws 指令回去用 ~/.aws 的 admin profile（理由見 §2）
aws sts get-caller-identity --query Arn --output text   # 結尾必須是 :user/personaldocai-admin
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "region=$AWS_REGION  account 長度=${#ACCOUNT_ID}"
```

  預期：先印一行結尾是 `:user/personaldocai-admin` 的 ARN，再印 `region=ap-northeast-1  account 長度=12`
  （**刻意只印長度不印值**——帳號 ID 雖然不是密碼，但也沒有必要出現在你的終端機捲軸裡。）

  `set -a` ＝之後每個賦值都自動 `export`；`.`（點）＝在**目前這個 shell** 執行那個檔
  （不是開子行程，所以變數留得下來）；`set +a` ＝關掉自動 export；
  `unset …` ＝把 `.env` 帶進來的那兩把 **personaldocai-mac** 的 key 丟掉——環境變數的優先序比 `~/.aws` 高，
  不丟的話接下來每一條 `create-*` 都會 `AccessDenied`（mac 那組連 `iam:CreateRole` 都沒有）。
  `--query Account` ＝ AWS CLI 內建的 JMESPath 查詢，只取 JSON 的 `Account` 欄；
  `--output text` ＝不要印成 JSON（會帶引號），直接印純文字才好塞進 shell 變數。

- [x] 查預設 VPC：

```bash
VPC_ID=$(aws ec2 describe-vpcs --region "$AWS_REGION" \
  --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
echo "VPC_ID=$VPC_ID"
```

  預期：`VPC_ID=vpc-0123456789abcdef0`（`vpc-` 開頭的一串）。

  `--filters Name=is-default,Values=true` ＝只要「預設 VPC」那一個
  （每個帳號在每個區域都有一個，開帳號時 AWS 自動建的）；`--query 'Vpcs[0].VpcId'` ＝取第 0 筆的 id。

  印出 `None` → 這個區域的預設 VPC 被刪掉了（少見，但有人手賤刪過）。
  **退路：** `aws ec2 create-default-vpc --region "$AWS_REGION"`
  ——這個指令免費，會把預設 VPC ＋ 每個可用區一個公有子網 ＋ internet gateway 一次建回來。

- [x] 查一個**公有**子網（`MapPublicIpOnLaunch` 是 `true` 的那種）：

```bash
SUBNET_ID=$(aws ec2 describe-subnets --region "$AWS_REGION" \
  --filters Name=vpc-id,Values="$VPC_ID" Name=map-public-ip-on-launch,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
echo "SUBNET_ID=$SUBNET_ID"
```

  預期：`SUBNET_ID=subnet-…`
  （`Name=map-public-ip-on-launch,Values=true` ＝只挑「開機自動給公有 IP」的子網 ＝ 公有子網。）

  📌 **「公有子網」為什麼重要：** 我們的機器要主動連出去（S3、SQS、ECR、SSM、ollama.com），
  而**唯一免費**的出網方式就是「機器在公有子網、有一個公有 IP」。
  放進私有子網的話就非得建 NAT Gateway 不可，那是 design6 §0 明文禁止的
  （NAT 按小時 ＋ 按流量收費，會直接把 Free plan 點數打爆）。

- [x] 查那個 VPC 的**主要路由表**（等一下要把 S3 endpoint 掛上去）：

```bash
RTB_ID=$(aws ec2 describe-route-tables --region "$AWS_REGION" \
  --filters Name=vpc-id,Values="$VPC_ID" Name=association.main,Values=true \
  --query 'RouteTables[0].RouteTableId' --output text)
echo "RTB_ID=$RTB_ID"
```

  預期：`RTB_ID=rtb-…`

  `Name=association.main,Values=true` ＝只要「主要」那一張。預設 VPC 的所有子網都關聯到它，
  所以把 S3 endpoint 掛在它上面 ＝ 整個 VPC 都吃得到。

- [x] **把這五個變數寫進一個暫存檔**，萬一終端機關掉可以一行載回來：

```bash
cat > /tmp/p91-vars.sh <<EOF
export AWS_REGION="$AWS_REGION"
export ACCOUNT_ID="$ACCOUNT_ID"
export VPC_ID="$VPC_ID"
export SUBNET_ID="$SUBNET_ID"
export RTB_ID="$RTB_ID"
EOF
chmod 600 /tmp/p91-vars.sh
sed 's/=.*/=…/' /tmp/p91-vars.sh      # 預期：五行 export XXX=…（只確認在，不印值）
```

  之後在新視窗恢復：`. /tmp/p91-vars.sh` ＋ `set -a; . ./.env; set +a` ＋
  `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`（三段缺一不可，最後那段的理由見 §2）。
  ⚠️ **放 `/tmp`，不要放進專案目錄**——`/tmp` 重開機會清掉，專案目錄裡的東西
  一不小心就會被 `git add -A` 掃進版控。

### 4.2 建 security group（inbound 空、outbound 只開 443）

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] **建 SG**：

```bash
SG_ID=$(aws ec2 create-security-group --region "$AWS_REGION" \
  --group-name personaldocai-worker-sg \
  --description "PersonalDocAI cloud worker: no inbound, egress TCP 443 only" \
  --vpc-id "$VPC_ID" \
  --query 'GroupId' --output text)
echo "SG_ID=$SG_ID"
echo "export SG_ID=\"$SG_ID\"" >> /tmp/p91-vars.sh
```

  旗標：`--group-name` ＝名字（總覽 §2.8 定的，逐字照抄；同一個 VPC 裡不能重名、不能以 `sg-` 開頭）；
  `--description` ＝**必填**（AWS 規定）而且**建完不能改**，寫清楚一點；
  `--vpc-id` ＝建在哪個 VPC；`--query 'GroupId'` ＝只取新建的 id。

  預期：`SG_ID=sg-0123456789abcdef0`

  **做錯了怎麼退回：** `aws ec2 delete-security-group --group-id "$SG_ID" --region "$AWS_REGION"` 再重來。
  **SG 完全免費**，刪掉重建零成本。（只有「已經有機器掛著它」時刪不掉，會回 `DependencyViolation`
  ——本 phase 還沒有機器，不會遇到。）

- [x] **看一眼剛建好的 SG 現在長什麼樣**（這一步是為了看到「預設 egress 全開」這件事）：

```bash
aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].{In:IpPermissions,Out:IpPermissionsEgress}' --output json
```

  預期（`Out` 那一條還有 `Ipv6Ranges`／`PrefixListIds`／`UserIdGroupPairs` 三個空陣列，略）：

```json
{"In": [], "Out": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]}
```

  📌 **看懂這段輸出：** `In: []` ＝ inbound 一條規則都沒有——**這正是我們要的最終狀態**，
  而且是 AWS 的預設，所以「inbound 全關」其實是「什麼都不做」。
  `Out` 那條 `IpProtocol: "-1"` ＝ **所有協定**、所有埠、到全世界，是 AWS 幫新 SG 自動加的
  （官方原文：new security groups have "an outbound rule that allows all outbound traffic"）。
  **要收緊就得先把它撤掉**——直接加一條 443 沒有用，那會變成「全開 ＋ 443」兩條並存。

- [x] **撤掉預設的全開 egress**：

```bash
aws ec2 revoke-security-group-egress --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
```

  `--ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'` ＝要撤掉的那一條規則，
  **必須跟現有的完全一樣**（`-1` ＝所有協定；用了 `-1` 就不能也不必寫埠）。

  預期輸出：`{"Return": true}`

  ⚠️ **最大的陷阱：規則對不起來的話，這個指令會「成功但什麼都沒做」。**
  AWS 只在**完全比對相符**時才撤掉規則；比對不到時它不報錯，`Return` 仍是 `true`
  （新版 CLI 會多一個 `UnknownIpPermissions` 欄位列出沒對到的）。所以下一步的「驗證」不可以跳過。

- [x] **只放行 TCP 443 到 `0.0.0.0/0`**：

```bash
aws ec2 authorize-security-group-egress --region "$AWS_REGION" \
  --group-id "$SG_ID" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0
```

  `--protocol tcp` ＝只有 TCP（不含 UDP／ICMP）；`--port 443` ＝只有 443
  （單一個數字 ＝ From 與 To 都是 443）；`--cidr 0.0.0.0/0` ＝目的地是任何 IPv4
  （**必要**——S3／SQS／ECR／SSM／ollama.com 的 IP 會變，鎖不住）。

  預期：`{"Return": true, "SecurityGroupRules": [...]}`

  📌 **為什麼只要 443 就夠：** 工人往外打的東西全部是 HTTPS——S3／SQS／ECR／SSM
  （AWS API 一律 443）與 `https://ollama.com`。**DNS 查詢（UDP 53）不必開**：
  那是 VPC 內建的 `AmazonProvidedDNS`，走的不是 security group 這一層。

- [x] **驗證最終狀態**（這一步是 ★ 必做，總覽 §5.5 也會再驗一次）：

```bash
aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissions' --output json
```

  預期：`[]` ← **一條 inbound 規則都沒有**（design6 §0 禁止第 3 條）

```bash
aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG_ID" \
  --query 'SecurityGroups[0].IpPermissionsEgress[].{P:IpProtocol,From:FromPort,To:ToPort,Cidr:IpRanges[0].CidrIp}' \
  --output table
```

  預期：表格**只有一行資料** ＝ `Cidr 0.0.0.0/0 ｜ From 443 ｜ P tcp ｜ To 443`。

  **看到兩行（一行 `-1`、一行 `tcp 443`）＝ revoke 那一步沒生效。**
  回上面重跑 revoke，注意 `--ip-permissions` 的字串要一字不差。

  **費用：** security group **完全免費**，數量也不計費。

### 4.3 建 S3 Gateway VPC endpoint（免費）

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] 建立：

```bash
VPCE_ID=$(aws ec2 create-vpc-endpoint --region "$AWS_REGION" \
  --vpc-id "$VPC_ID" \
  --vpc-endpoint-type Gateway \
  --service-name "com.amazonaws.$AWS_REGION.s3" \
  --route-table-ids "$RTB_ID" \
  --query 'VpcEndpoint.VpcEndpointId' --output text)
echo "VPCE_ID=$VPCE_ID"
echo "export VPCE_ID=\"$VPCE_ID\"" >> /tmp/p91-vars.sh
```

  `--vpc-endpoint-type Gateway` ＝ **Gateway 型**（只有 S3 與 DynamoDB 有），
  **完全免費**（AWS 官方原文：「There is no additional charge for using gateway endpoints」）；
  Interface 型是按小時 ＋ 按流量計費的 PrivateLink，本專案**不用**。
  `--service-name "com.amazonaws.$AWS_REGION.s3"` ＝服務名固定長這樣（東京就是 `…ap-northeast-1.s3`）。
  `--route-table-ids "$RTB_ID"` ＝把「去 S3 走這條」的路由加進哪一張路由表。

  預期：`VPCE_ID=vpce-0123456789abcdef0`
  （⚠️ 是 **`vpce-`** 開頭，不是 `vpc-`——差一個字母，複製貼上時很容易看走眼。）

- [x] 驗證它掛上去了：

```bash
aws ec2 describe-vpc-endpoints --region "$AWS_REGION" --vpc-endpoint-ids "$VPCE_ID" \
  --query 'VpcEndpoints[0].{Type:VpcEndpointType,Service:ServiceName,State:State,RTBs:RouteTableIds}' \
  --output json
```

  預期：`{"Type":"Gateway","Service":"com.amazonaws.ap-northeast-1.s3","State":"available","RTBs":["rtb-…"]}`
  （`State` 是 `pending` → 等幾秒再查一次；`available` 才算好。）

  📌 **它做了什麼：** 在路由表加一條「要去 S3 的那些 IP，走這個 endpoint」，
  效果是**去 S3 的流量不出公網**（比較快也比較安全）。對本專案主要是「免費就順手做」，
  不做也能跑（機器有公網出口）。

  **做錯了怎麼退回：** `aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "$VPCE_ID" --region "$AWS_REGION"`
  ——刪掉會自動把路由表那條路移除，零成本、零風險。

  ⚠️ 建立時的**預設 endpoint policy 是「全開」**（`Principal: *`、`Action: *`）。
  這**不是**漏洞：endpoint policy 只管「經過這條路的請求」，能不能存取仍要過 IAM
  與 bucket policy 兩關。side project 不必收緊它。

### 4.4 寫兩份 IAM JSON（完整貼出，佔位符不要換成真值）

> 📌 **本節是純寫檔**（`mkdir` ＋ 兩個 JSON ＋ 一次 `python3 -m json.tool` 語法檢查），零 `aws`／零 `docker`。

- [x] 建立目錄：

```bash
mkdir -p deploy/aws deploy/ec2
```

- [x] 建立 `deploy/aws/worker-role-trust.json`（**完整內容**）：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEc2InstancesToAssumeThisRole",
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

  📌 **這份 JSON 在講：**「**EC2 這個服務**可以來借用我這個 role」。它跟「這個 role 能做什麼」
  無關——那是下一份的事。兩份分開是 IAM 的設計：trust ＝**誰可以借**，policy ＝**借到能做什麼**。
  ⚠️ `"Version": "2012-10-17"` 是 IAM policy **語言的版本號、不是日期**，
  **永遠寫這一串**（AWS 到今天只有這一個有效值），寫別的會被拒絕。

- [x] 建立 `deploy/aws/worker-role-policy.json`（**完整內容**；
      `<ACCOUNT_ID>`／`<AWS_REGION>`／`<S3_BUCKET>` 三個佔位符**保持原樣**）：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MailboxObjectsOnly",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::<S3_BUCKET>/documents/*"
    },
    {
      "Sid": "BucketListSoMissingKeyIs404",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::<S3_BUCKET>"
    },
    {
      "Sid": "JobsQueueConsume",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:<AWS_REGION>:<ACCOUNT_ID>:personaldocai-jobs"
    },
    {
      "Sid": "ResultsQueueProduce",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage"
      ],
      "Resource": "arn:aws:sqs:<AWS_REGION>:<ACCOUNT_ID>:personaldocai-results"
    },
    {
      "Sid": "EcrAuthTokenIsAccountWide",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EcrPullThisRepositoryOnly",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchCheckLayerAvailability"
      ],
      "Resource": "arn:aws:ecr:<AWS_REGION>:<ACCOUNT_ID>:repository/personaldocai-worker"
    }
  ]
}
```

  📌 **逐段解釋（總覽 §2.8「IAM role（EC2 用）」那一列的逐條落地，＋ 總覽 §10.2 裁決 P 的 `s3:ListBucket`）：**

  | Sid | 為什麼要 | 為什麼不能更寬 |
  |---|---|---|
  | `MailboxObjectsOnly` | 工人要 `GetObject` 拿 `input.*` 與 `context.json`、`PutObject` 寫 `result.json` | `Resource` 鎖在 `documents/*` 這個 prefix。**沒有 `s3:DeleteObject`**——刪東西是本機的事（`CloudRoute.cleanup`），工人碰不到。`s3:ListBucket` 在**下一列**（它是 bucket 層的動作，Resource 不一樣） |
  | `BucketListSoMissingKeyIs404` | **總覽 §10.2 裁決 P。** S3 的官方規則：對**不存在的 key** 做 `GetObject`，有 `s3:ListBucket` 才回 **404**（`NoSuchKey`），沒有就回 **403**（`AccessDenied`）。工人每一則 jobs 開頭的冪等檢查 `get_object(result_key)`（Phase 87 規則 1；`aws_mailbox.get_object` 只把 `NoSuchKey` 轉成 `None`，403 會往外丟）靠的就是 404——少了這條，**第一張圖就在這裡炸 403、一張都處理不了**（phase-83 review 抓到） | `Resource` 是 **bucket ARN**（`arn:aws:s3:::<S3_BUCKET>`，**沒有** `/documents/*`）：`ListBucket` 是對 bucket 做的動作，寫在 prefix ARN 上等於沒給。它只讓工人列得出鍵名，看不到任何物件內容；`DeleteObject` 仍然沒有 |
  | `JobsQueueConsume` | 收工作、做完刪訊息 | 只鎖 jobs 那一條。**沒有 `SendMessage`**——工人不准往 jobs 塞東西 |
  | `ResultsQueueProduce` | 做完發一則「好了」 | 只鎖 results 那一條，而且**只有 Send**——工人不准去 results 收訊息（那是本機的事） |
  | `EcrAuthTokenIsAccountWide` | 換取 `docker login` 的密碼 | 這個動作 AWS 規定 **`Resource` 只能是 `*`**（它不是針對某個 repo 的操作）。這是官方文件的要求，不是我們偷懶 |
  | `EcrPullThisRepositoryOnly` | 把映像拉下來（三個動作缺一不可） | `Resource` 鎖死本專案這一個 repo。**沒有任何 `Put`／`Upload`／`Complete`**——工人**不准推**映像，推是 CD 的事（Phase 93 那個 role 才有） |

  📌 **`sqs:ChangeMessageVisibility` 為什麼在清單裡：** design6 §6 原文只寫「jobs 的 Receive／Delete」。
  多這一個是因為**多頁 PDF 可能看很久**——jobs 的 visibility timeout 是 900 秒，
  萬一快到了，工人需要能「延長一下」而不是讓訊息重新出現給第二個人做。
  它是同一條佇列上的同一類操作，不是新開權限面（總覽 §2.8 已列進契約）。

  📌 **這份 policy 沒有 SSM 的任何東西**——那由 §4.5 掛的官方 managed policy
  `AmazonSSMManagedInstanceCore` 提供，不必自己寫。

- [x] **檢查兩份 JSON 語法沒打錯**（格式錯時 `json.tool` 會直接噴 `Expecting ',' delimiter` 之類）：

```bash
python3 -m json.tool deploy/aws/worker-role-trust.json  > /dev/null && echo "trust OK"
python3 -m json.tool deploy/aws/worker-role-policy.json > /dev/null && echo "policy OK"
```

  預期：兩行 `OK`。

- [x] 佔位符有沒有被誤換成真值，在 §4.10 的「機密沒外洩」那一組指令一次驗完
      （那組會檢查 `<ACCOUNT_ID>` 出現 **3** 次——兩條 SQS ARN ＋ 一條 ECR ARN——、`<S3_BUCKET>` 出現 **2** 次——prefix ARN ＋ bucket ARN——且整個 `deploy/` 沒有任何 12 位數字）。

### 4.5 建 IAM role ＋ instance profile

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] **把佔位符展開到 `/tmp`**（真值只出現在 `/tmp`，不進版控）：

```bash
sed -e "s|<ACCOUNT_ID>|$ACCOUNT_ID|g" \
    -e "s|<AWS_REGION>|$AWS_REGION|g" \
    -e "s|<S3_BUCKET>|$S3_BUCKET|g" \
    deploy/aws/worker-role-policy.json > /tmp/worker-role-policy.json

python3 -m json.tool /tmp/worker-role-policy.json > /dev/null && echo "展開後仍是合法 JSON"
grep -c "<" /tmp/worker-role-policy.json    # 預期：0（一個佔位符都不剩）
```

  `sed -e "s|A|B|g"` 用 `|` 當分隔符（bucket 名與 ARN 裡本來就有 `/`）；**雙引號**是必要的
  （shell 只在雙引號裡展開 `$ACCOUNT_ID`）；`> /tmp/…` ＝展開後的版本（含真帳號 ID）**只放 `/tmp`**。

- [x] **建 role**：

```bash
aws iam create-role \
  --role-name personaldocai-worker-role \
  --assume-role-policy-document file://deploy/aws/worker-role-trust.json \
  --description "PersonalDocAI cloud worker on EC2: S3 mailbox, two SQS queues, ECR pull, SSM" \
  --query 'Role.Arn' --output text
```

  `--assume-role-policy-document file://…` ＝ **trust policy**（誰可以借用）；`file://` ＋ 相對路徑
  是兩條斜線，絕對路徑要三條（`file:///tmp/…`）。`--description` 給人看，可事後改。
  ⚠️ **IAM 是全球性服務，指令不帶 `--region`**（帶了不會錯，但沒有意義）。

  預期：`arn:aws:iam::<ACCOUNT_ID>:role/personaldocai-worker-role`

  **做錯了怎麼退回：** IAM 的刪除**有順序**（先把附屬品拆掉才刪得掉 role），五行照這個順序跑：

```bash
aws iam remove-role-from-instance-profile --instance-profile-name personaldocai-worker-role --role-name personaldocai-worker-role
aws iam delete-instance-profile --instance-profile-name personaldocai-worker-role
aws iam detach-role-policy --role-name personaldocai-worker-role --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role-policy --role-name personaldocai-worker-role --policy-name personaldocai-worker-inline
aws iam delete-role --role-name personaldocai-worker-role
```

  （還沒建到那一步的指令會回「找不到」，忽略即可。**IAM 全部免費**，刪掉重建零成本。）

- [x] **掛上自己寫的權限（inline policy）**：

```bash
aws iam put-role-policy \
  --role-name personaldocai-worker-role \
  --policy-name personaldocai-worker-inline \
  --policy-document file:///tmp/worker-role-policy.json
```

  沒有輸出 ＝ 成功（AWS CLI 的慣例）。`--policy-name` ＝ inline policy 的名字；
  **同名再跑一次 ＝ 直接覆蓋**（不報錯、不會變兩份），所以改 policy 的流程就是
  「改 JSON → 重跑 sed → 重跑這一行」。⚠️ `file:///tmp/…` **三條斜線**，只打兩條會找不到檔。

- [x] **掛上 AWS 官方的 SSM 權限（managed policy）**：

```bash
aws iam attach-role-policy \
  --role-name personaldocai-worker-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
```

  沒有輸出 ＝ 成功。

  📌 **漏掉的後果非常慘：** 機器起來了、SSM agent 也在跑，但它**沒有權限跟 SSM 服務對話**，
  於是 `aws ssm start-session` 回 `TargetNotConnected`；而我們**又不開 SSH**（inbound 空）
  ——就變成一台完全碰不到的機器，只能 Terminate 重建。
  ⚠️ 不要用舊的 `AmazonEC2RoleforSSM`（legacy，權限過大）。

- [x] **建 instance profile 並把 role 放進去**：

```bash
aws iam create-instance-profile --instance-profile-name personaldocai-worker-role \
  --query 'InstanceProfile.Arn' --output text

aws iam add-role-to-instance-profile \
  --instance-profile-name personaldocai-worker-role \
  --role-name personaldocai-worker-role
```

  第一條預期 `arn:aws:iam::<ACCOUNT_ID>:instance-profile/personaldocai-worker-role`；第二條無輸出 ＝ 成功。

  📌 **同名純粹是為了少記一個名字。** 兩者是**不同的東西**：role 是權限，
  instance profile 是「把 role 掛到 EC2 上」的那層包裝（Console 建 role 時會自動建同名 profile，
  用 CLI 就得自己建）。⚠️ 一個 instance profile **只能放一個 role**（AWS 硬性限制）。

- [x] **驗證整條鏈接對了**（三條一起跑）：

```bash
aws iam get-instance-profile --instance-profile-name personaldocai-worker-role \
  --query 'InstanceProfile.Roles[].RoleName' --output text     # 預期：personaldocai-worker-role
aws iam list-attached-role-policies --role-name personaldocai-worker-role \
  --query 'AttachedPolicies[].PolicyName' --output text        # 預期：AmazonSSMManagedInstanceCore
aws iam list-role-policies --role-name personaldocai-worker-role \
  --query 'PolicyNames' --output text                          # 預期：personaldocai-worker-inline
```

  第一條印出空白 ＝ `add-role-to-instance-profile` 沒跑或失敗了，補跑一次。

- [x] **等 instance profile 傳播開來**（★ 這一步不能省，理由見下）：

```bash
aws iam wait instance-profile-exists --instance-profile-name personaldocai-worker-role
echo "IAM 那邊看得到了"
```

  ⚠️ **陷阱（很多人第一次都踩）：`create-instance-profile` 回來之後，EC2 那邊還「不知道」有它。**
  IAM 與 EC2 是兩套控制平面，中間有幾秒到幾十秒的傳播延遲。太快就 `run-instances` 會拿到：

```text
An error occurred (InvalidParameterValue) when calling the RunInstances operation:
Value (personaldocai-worker-role) for parameter iamInstanceProfile.name is invalid.
Invalid IAM Instance Profile name
```

  這個訊息**非常誤導**——它說「名字無效」，你會以為打錯字，其實名字完全正確、只是還沒傳到。
  `aws iam wait instance-profile-exists` 只確認 **IAM 那一側**（輪詢到 40 秒），
  **不保證 EC2 那一側**。所以 Phase 92 §4.3 的 `run-instances` 寫成
  「失敗就等 15 秒再試、最多三次」的小迴圈——那不是防禦性過度設計，是真的會遇到。

  **費用：** IAM 的 role、policy、instance profile **全部免費**，不限數量。

### 4.6 建 ECR repository

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] 建立：

```bash
aws ecr create-repository --region "$AWS_REGION" \
  --repository-name personaldocai-worker \
  --image-scanning-configuration scanOnPush=false \
  --query 'repository.repositoryUri' --output text
```

  `--repository-name personaldocai-worker` ＝ repo 名（總覽 §2.8 定的；⚠️ ECR **只接受小寫**）。
  `--image-scanning-configuration scanOnPush=false` ＝推上去**不要**自動掃漏洞
  （side project 不需要、結果也沒人看；預設本來就是 false，但明寫出來下一個人才不會以為「忘了設」）。
  **不要**加 `--image-tag-mutability IMMUTABLE`：預設的 `MUTABLE` 才能讓每次 CD 把 `latest` 重新指到新映像；
  設成 IMMUTABLE 的話第二次 push `latest` 會被拒（`ImageTagAlreadyExistsException`）。

  預期：`<ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com/personaldocai-worker`

  這一串就是等一下要用的 **`$ECR_URI`**。存起來：

```bash
ECR_URI=$(aws ecr describe-repositories --region "$AWS_REGION" \
  --repository-names personaldocai-worker \
  --query 'repositories[0].repositoryUri' --output text)
ECR_REGISTRY="${ECR_URI%%/*}"          # 砍掉最後一個 / 之後的部分 ＝ 只留 registry 網址
echo "export ECR_URI=\"$ECR_URI\"" >> /tmp/p91-vars.sh
echo "export ECR_REGISTRY=\"$ECR_REGISTRY\"" >> /tmp/p91-vars.sh
echo "registry 尾巴＝${ECR_REGISTRY##*.}"     # 預期：com（只是確認變數有值，不印帳號 ID）
```

  `${ECR_URI%%/*}` ＝ bash 字串處理「從右邊砍掉第一個 `/` 起的最長比對」→ 只留 registry 網址；
  `${ECR_REGISTRY##*.}` ＝「從左邊砍到最後一個 `.`」→ 只留 `com`（拿來確認變數不是空的）。

  **做錯了怎麼退回：**
  `aws ecr delete-repository --repository-name personaldocai-worker --force --region "$AWS_REGION"`
  （`--force` ＝連裡面的映像一起刪；沒有它時，有映像的 repo 刪不掉）。

  **費用：** ECR 私有 repo 的儲存費約 **$0.10／GB-月**；工人映像約 300〜400 MB ≈ **$0.04／月**，
  從**點數**扣（AWS 官網寫的「新客戶 500 MB／月免費一年」是舊制 12 個月免費方案，
  **2025-07-15 之後開的點數制帳號不保證適用**——就算不適用也只是幾分錢）。
  推兩個 tag 只算**一份**（同一份 layer 不重複計）。⚠️ 但**每次 CD 推一個新 sha 就多一份**
  ——Phase 94 之後舊 sha 累積到十幾個就是幾 GB，清法：
  `aws ecr batch-delete-image --repository-name personaldocai-worker --image-ids imageTag=<舊sha>`。

### 4.7 第一次手動 push（兩個 tag）

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] **登入 ECR**（拿一個 12 小時有效的臨時密碼餵給 `docker login`）：

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
```

  預期：`Login Succeeded`（前面可能有一行關於憑證存在 keychain 的提示，無害）。

  `aws ecr get-login-password` ＝跟 AWS 換一個**臨時密碼**（12 小時後過期），它不是你的 AWS 金鑰。
  `--username AWS` ＝ ECR 的使用者名稱**固定就是大寫的 `AWS`**，不是你的帳號名。
  `--password-stdin` ＝從標準輸入讀密碼；**這很重要**——寫成 `--password <一串>` 的話，
  那串密碼會留在 `~/.zsh_history` 裡。
  `"$ECR_REGISTRY"` ＝登入哪個 registry；**不要**帶 `/personaldocai-worker`
  （登入是針對整個 registry，不是單一 repo）。

  **做錯了怎麼退回：** `docker logout "$ECR_REGISTRY"`，然後重跑。
  `Login Succeeded` 卻在 push 時被拒 → 多半是 12 小時過期了，重跑這一行就好。

- [x] **打 tag 並推上去**（同一份映像、兩個名字）：

```bash
SHA=$(git rev-parse --short HEAD)
echo "SHA=$SHA"

docker tag personaldocai-worker:local "$ECR_URI:$SHA"
docker tag personaldocai-worker:local "$ECR_URI:latest"

docker push "$ECR_URI:$SHA"
docker push "$ECR_URI:latest"
```

  預期：每條 push 結尾各一行 `<tag>: digest: sha256:… size: …`。
  **兩個 digest 應該一模一樣**（同一份映像的兩個名字）；第二次 push 很快
  （layer 已經在上面，只是多掛一個 tag）。

  📌 **為什麼要兩個 tag（總覽 §10 追認項 e）：** `latest` ＝ EC2 的 systemd unit 每次啟動都
  `docker pull …:latest`，「開機就是最新的」靠它；`<sha>` ＝ **任何一版都回得去**
  （新版壞了就 `docker run … <ECR_URI>:<舊sha>`，不必重 build）。
  design6 D16 說「**不靠 `latest` 當唯一 tag**」——我們的解讀是「tag 可以有 `latest`，
  但**驗證跑的是哪一版**不靠它」，靠的是工人啟動 log 印的 `version=<sha>`
  （`WORKER_VERSION`，Phase 90 烙進去的）。

- [x] **驗證 ECR 上真的有這兩個 tag**：

```bash
aws ecr describe-images --region "$AWS_REGION" \
  --repository-name personaldocai-worker \
  --query 'imageDetails[?imageTags].imageTags[]' --output json
```

  預期：

```json
[
    "latest",
    "a53ab57"
]
```

  （順序不一定；`a53ab57` 換成你剛才的 `$SHA`。）

  ⚠️ **`--query` 的兩個細節：**
  - 結尾的 `[]`（flatten）不能省：`imageDetails[].imageTags` 回的是**陣列的陣列**
    （每個映像一個 tag 陣列），加上 `[]` 才會攤平成一個平的清單。
  - `[?imageTags]` 是過濾條件：只留「有 `imageTags` 這個鍵」的映像（**沒有 tag 的映像根本沒有這個鍵**，
    不是空陣列）。JMESPath 的投影本來就會略過 `null`，所以它是**保險**而不是必要——
    真正不能省的是上面那個 `[]`。

- [x] **確認架構真的是 arm64 上去了**：

```bash
docker image inspect "$ECR_URI:latest" --format '{{.Architecture}}'
```

  預期：**`arm64`**（查的是本機那一份，因為 tag 指的是同一個映像 id）。
  ⚠️ 印出 `amd64` ＝ Phase 90 建錯架構了，**現在停下來**回 Phase 90 §4.3 重建再重推。
  推錯架構的話 EC2 上 `docker run` 會回 `exec format error`，
  而那個訊息完全看不出跟架構有關。

### 4.8 寫三份要放進機器的檔案

> 📌 **本節是純寫檔**（三個檔 ＋ 一次 `awk`／`diff` 自我比對），零 `aws`／零 `docker`。

#### `deploy/ec2/personaldocai-worker.service`（systemd unit）

- [x] 建立這個檔（**完整內容**）：

```ini
[Unit]
Description=PersonalDocAI cloud worker (Docker, pulls latest from ECR)
After=docker.service
Requires=docker.service

[Service]
Type=simple
EnvironmentFile=/opt/personaldocai/worker.env
ExecStartPre=/bin/bash -c '/usr/bin/aws ecr get-login-password --region ${AWS_REGION} | /usr/bin/docker login --username AWS --password-stdin ${ECR_REGISTRY}'
ExecStartPre=/usr/bin/docker pull ${ECR_IMAGE}:latest
ExecStartPre=-/usr/bin/docker rm -f cloud-worker
ExecStart=/usr/bin/docker run --rm --name cloud-worker --env-file /opt/personaldocai/worker.env ${ECR_IMAGE}:latest
# 停止：工人收到 SIGTERM 會把手上那一則訊息做完才退（Phase 88）；多頁 PDF 可能超過 docker 預設的 10 秒寬限，
# 所以給 120 秒。超時＝SIGKILL：資料不會壞（D17 冪等＋jobs 佇列 900 秒後重投），只是多跑一次雲端看圖。
ExecStop=/usr/bin/docker stop -t 120 cloud-worker
# 要比上面的 120 秒長，否則 systemd 會先一步把 docker stop 本身殺掉（總覽 §10.2 裁決 O）
TimeoutStopSec=150
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

  📌 **這份 unit（17 行設定＋3 行註解＋2 行空白）逐行在做什麼**（unit 檔本身只在「停止」那兩行留註解——
  那是總覽 §10.2 裁決 O 要求寫在旁邊的；其餘解釋放在這張表，只寫一次。它會被 `cat` 進機器裡，越短越好對）：

  | 那一行 | 在做什麼 / 為什麼非這樣不可 |
  |---|---|
  | `After=docker.service` ＋ `Requires=docker.service` | `After=` 只管**順序**（我排在它後面）、`Requires=` 只管**相依**（它掛了我也不該跑）。**兩行都要寫**：只寫 `Requires=` 的話 systemd 可能兩個一起啟動，然後 Docker 還沒好就跑 `docker run` |
  | `Type=simple` | 「`ExecStart` 那個行程活著 ＝ 服務活著」。最單純的一種，也是我們要的 |
  | `EnvironmentFile=/opt/personaldocai/worker.env` | 機密（區域、ECR 位址、bucket、佇列 URL、`OLLAMA_API_KEY`）全部在那個檔裡，由人用 Session Manager 手動建、`chmod 600`（總覽 §10 追認項 h）。**這一行讓下面的 `${AWS_REGION}` 有值可以代** |
  | 第一個 `ExecStartPre`（`/bin/bash -c '…'`） | 跟 AWS 換一個 12 小時的臨時密碼餵給 `docker login`。★ **一定要包 `/bin/bash -c`**：systemd 自己**不跑 shell**，管線符號 `\|` 在它眼裡只是普通字元，不會有「把左邊的輸出接到右邊」的效果 |
  | `${AWS_REGION}` 這種**大括號**寫法 | systemd 會把它代成 `EnvironmentFile` 裡的值，而且**可以嵌在字串中間**（例如 `${ECR_IMAGE}:latest`）。⚠ **不要**用沒有大括號的 `$AWS_REGION`：那種寫法在**單獨成一個詞**時會依空白切成多個參數（word splitting），行為不一樣。（第一個 `ExecStartPre` 是 `bash -c`，就算 systemd 不代，bash 也會從環境變數自己代——`EnvironmentFile` 的變數本來就傳給每一個 `Exec*` 行程） |
  | 第二個 `ExecStartPre`（`docker pull …:latest`） | 「開機自動拉最新映像」就是靠這一行（總覽 §10 追認項 e） |
  | 第三個 `ExecStartPre` 前面的 **`-`（減號）** | systemd 的語法：**這一行失敗不算錯，繼續往下**。沒有它的話，第一次啟動（根本沒有這個容器）就會因為 `docker rm` 失敗而整個服務起不來 |
  | `ExecStart=… docker run --rm --name cloud-worker …` | `--rm` ＝結束時自己清掉；`--name` 固定名字，之後 `docker logs cloud-worker` 才找得到。★ **前景執行（不加 `-d`）**：systemd 靠這個行程活著判斷服務在不在。加了 `-d` 的話 `docker run` 立刻返回，systemd 以為服務結束了，然後照 `Restart=always` 每 10 秒重開一次。⚠ 容器走 Docker 預設的 bridge 網路，boto3 去 IMDS 拿 instance-profile 憑證要多過一跳——Phase 92 `run-instances` 的 `--metadata-options` 要帶 `HttpPutResponseHopLimit=2`（§7 陷阱 11） |
  | `ExecStop=… docker stop -t 120 cloud-worker` | `systemctl stop`／`stop-instances` 時好好地叫容器停：`docker stop` 先送 SIGTERM，工人收到會把手上那一則訊息做完才退（Phase 88 做的）。**`-t 120`**：docker 預設只等 **10 秒**就 SIGKILL——一頁 2 秒的單圖沒問題，多頁 PDF 可能超過，所以放寬到 120 秒。真的超時＝SIGKILL：**資料不會壞**（D17 冪等＋jobs 佇列 visibility 900 秒後重投給下一次），代價只是那一則多跑一次雲端看圖（總覽 §10.2 裁決 O） |
  | `TimeoutStopSec=150` | systemd 自己對「停止」的耐心上限（預設 90 秒）。**一定要比 `-t 120` 長**：不然 systemd 會在 90 秒時把 `docker stop` 這個指令本身殺掉、再對整個 cgroup 送 SIGKILL，`-t 120` 就白給了。150 ＝ 120 ＋ 30 秒餘裕 |
  | `Restart=always` ＋ `RestartSec=10` | 不管怎麼結束的都重開、重開前等 10 秒。用途：ollama.com 暫時掛掉、網路抖一下、AWS API 限流——機器自己會回來，不必人管 |
  | `[Install] WantedBy=multi-user.target` | 「`systemctl enable` 之後，開機進入多使用者模式時把我拉起來」＝**開機自動啟動**。沒有它，`enable` 會回 `no installation config` |

#### `deploy/ec2/user-data.sh`（第一次開機的腳本）

- [x] 建立這個檔（**完整內容**）：

```bash
#!/bin/bash
# PersonalDocAI 雲端工人的 EC2 開機腳本（增量六 Phase 91）。
#
# ★ user-data 的三個事實（AWS 官方行為，記住可以少走很多冤枉路）：
#   ① 它**以 root 執行**——所以裡面**不要**寫 sudo（寫了也能跑，但沒必要）。
#   ② 它**只在「第一次開機」跑一次**。之後 Stop→Start 都不會再跑。
#      要改機器上的東西，是用 SSM Session Manager 進去改，不是改這個檔再重開機。
#   ③ 它的輸出在機器裡的 /var/log/cloud-init-output.log。
#      機器起來卻沒反應時，第一個要看的就是那個檔。
#
# ⛔ **這個檔會原封不動留在機器的 /var/lib/cloud/instances/<id>/ 底下。**
#    所以裡面**一個機密都不准寫**——AWS 金鑰、OLLAMA_API_KEY、bucket 名一律不寫。
#    機密走 /opt/personaldocai/worker.env（人用 Session Manager 手動放，chmod 600）。
#
# set 的四個旗標：
#   -e 任何一行失敗就整個停下（不要帶著半套狀態繼續）
#   -u 用到沒設定的變數就報錯（打錯變數名時馬上發現）
#   -x 把每一行執行前先印出來（log 才看得懂做到哪裡）
#   -o pipefail 管線裡任何一段失敗都算失敗（預設只看最後一段）
set -euxo pipefail

# ---- 1. 裝 Docker ----
# AL2023 的預設套件庫裡就有 docker（不像 AL2 要先開 amazon-linux-extras）。
dnf install -y docker

# --now ＝ enable（開機自動啟動）＋ start（現在就啟動）兩件事一起做
systemctl enable --now docker

# 讓預設的 ec2-user 不必 sudo 也能用 docker（下次登入才生效；本腳本是 root，不受影響）
usermod -aG docker ec2-user

# ---- 2. 建放機密的目錄 ----
# worker.env 還不存在——它由人用 Session Manager 進來手動建（Phase 92 §4.5）。
# 目錄權限收到 700：只有 root 進得去。
mkdir -p /opt/personaldocai
chmod 700 /opt/personaldocai

# ---- 3. 裝 systemd 服務 ----
# ★ 下面這一段與 deploy/ec2/personaldocai-worker.service **必須逐字相同**。
#   Phase 91 §6 的驗收有一條專門在 diff 這兩份（用下面這兩行標記抓範圍）。
cat > /etc/systemd/system/personaldocai-worker.service <<'UNIT'
[Unit]
Description=PersonalDocAI cloud worker (Docker, pulls latest from ECR)
After=docker.service
Requires=docker.service

[Service]
Type=simple
EnvironmentFile=/opt/personaldocai/worker.env
ExecStartPre=/bin/bash -c '/usr/bin/aws ecr get-login-password --region ${AWS_REGION} | /usr/bin/docker login --username AWS --password-stdin ${ECR_REGISTRY}'
ExecStartPre=/usr/bin/docker pull ${ECR_IMAGE}:latest
ExecStartPre=-/usr/bin/docker rm -f cloud-worker
ExecStart=/usr/bin/docker run --rm --name cloud-worker --env-file /opt/personaldocai/worker.env ${ECR_IMAGE}:latest
# 停止：工人收到 SIGTERM 會把手上那一則訊息做完才退（Phase 88）；多頁 PDF 可能超過 docker 預設的 10 秒寬限，
# 所以給 120 秒。超時＝SIGKILL：資料不會壞（D17 冪等＋jobs 佇列 900 秒後重投），只是多跑一次雲端看圖。
ExecStop=/usr/bin/docker stop -t 120 cloud-worker
# 要比上面的 120 秒長，否則 systemd 會先一步把 docker stop 本身殺掉（總覽 §10.2 裁決 O）
TimeoutStopSec=150
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# 讓 systemd 重新讀一次 /etc/systemd/system/ 底下的檔
systemctl daemon-reload

# enable ＝「開機時自動啟動」。
# ⛔ **刻意不 start**：/opt/personaldocai/worker.env 還不存在，
#    現在 start 一定會因為 EnvironmentFile 找不到而失敗，然後 Restart=always
#    會讓它每 10 秒重試一次、把 journal 塞滿沒有意義的錯誤。
#    人用 Session Manager 放好 env 檔之後，再手動 systemctl start（Phase 92 §4.5）。
systemctl enable personaldocai-worker

echo "user-data 完成：docker 已裝、personaldocai-worker 已 enable（尚未 start，等 worker.env）"
```

#### `deploy/ec2/worker.env.example`（環境變數範本；**只有變數名**）

- [x] 建立這個檔（**完整內容**）：

```ini
# /opt/personaldocai/worker.env 的範本（增量六 Phase 91）。
#
# ⛔ 這個檔**只寫變數名，永遠不寫值**（增量六總覽 §7 鐵律 10）。真正的檔案由人用
#    SSM Session Manager 進機器手動建、chmod 600（步驟在 Phase 92 §4.5）；
#    它**不進版控、不進映像、不寫進 user-data**。
# ⛔ **沒有** AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY——EC2 用 instance profile
#    （personaldocai-worker-role），boto3 自己去機器的 metadata 服務拿臨時憑證。
# ⛔ **沒有** AWS_ENDPOINT_URL——那只用在 pytest 的第五道安全網（把 boto3 指到死埠）；
#    放進來會讓工人安靜地打不到任何 AWS 服務。

# --- systemd unit 代入用的三個（unit 檔裡的 ${…} 代的就是這三個）---
# ⚠ AWS_REGION 是**兩邊都要**的那一個：unit 的 ExecStartPre 用它去換 ECR 的臨時密碼，
#   而工人程式自己也讀它（config.AWS_REGION → AwsMailbox 的 region 參數）。
#   ECR_REGISTRY 與 ECR_IMAGE 則**只有 unit 用**，工人程式一個字都不讀。
AWS_REGION=
ECR_REGISTRY=
ECR_IMAGE=

# --- 工人程式讀的（app/core/config.py）---
S3_BUCKET=
SQS_JOBS_QUEUE_URL=
SQS_RESULTS_QUEUE_URL=
OLLAMA_API_KEY=
OLLAMA_CLOUD_VLM_MODEL=

# ⛔ **不要**加 VLM_MAX_ATTEMPTS：config.py 裡它是**寫死的常數**（＝3），根本不讀環境變數，
#    列在這裡只會讓下一個人以為改得動（2026-09-02 裁決 R9）。
# ⛔ **不要**加 WORKER_VERSION：它由 Dockerfile 的 ARG GIT_SHA 烙進映像（Phase 90）。
#    docker run --env-file 的值會**蓋掉**映像裡的 ENV，填了等於把「EC2 上跑的是哪一版」
#    這個證據弄假（Demo 3 就是靠工人啟動 log 的 version=<sha>）。
# ⛔ **不要**加 CLOUD_ROUTE／CLOUD_RESULT_TIMEOUT_SECONDS／DATABASE_URL／CELERY_BROKER_URL：
#    那些是**本機那一側**的設定，工人一個都不讀（工人不碰資料庫、不碰 Redis——design6 D11）。
```

  📌 **unit 代入的那三個變數的形狀（Phase 92 填值時會用到，這裡只說形狀、不寫值）：**

  | 變數 | 形狀 | 從哪裡來 |
  |---|---|---|
  | `AWS_REGION` | `ap-northeast-1` | 固定值（總覽 §2.8：全部東京） |
  | `ECR_REGISTRY` | `<帳號12碼>.dkr.ecr.ap-northeast-1.amazonaws.com` | §4.6 的 `$ECR_REGISTRY` |
  | `ECR_IMAGE` | `<帳號12碼>.dkr.ecr.ap-northeast-1.amazonaws.com/personaldocai-worker` | §4.6 的 `$ECR_URI`（**不含** `:tag`——unit 檔自己接 `:latest`） |

- [x] **驗證 user-data 裡的 unit 與獨立那份逐字相同**（防止兩份漂移）：

```bash
awk '/<<.UNIT.$/{f=1;next} /^UNIT$/{f=0} f' deploy/ec2/user-data.sh > /tmp/unit-from-userdata
diff /tmp/unit-from-userdata deploy/ec2/personaldocai-worker.service && echo "兩份 unit 逐字相同"
```

  預期：`兩份 unit 逐字相同`（`diff` 沒有輸出）。

  | 部分 | 意思 |
  |---|---|
  | `awk '/<<.UNIT.$/{f=1;next}'` | 遇到 `<<'UNIT'` 那一行就打開旗標 `f`，並跳過那一行本身（`.` 匹配那個單引號） |
  | `/^UNIT$/{f=0}` | 遇到行首就是 `UNIT` 的那一行就關掉旗標 |
  | `f` | 旗標開著的時候，印出這一行 |

  📌 **為什麼要有兩份：** `user-data.sh` 裡那一份是**真的會裝上機器的**；
  獨立的 `.service` 檔是給人閱讀、也給 Phase 92 之後「要改 unit」時用的
  ——因為 **user-data 只在第一次開機跑一次**，之後改它一點用都沒有，
  真正要改就是用 Session Manager 進去覆蓋 `/etc/systemd/system/personaldocai-worker.service`。
  兩份會漂移是真的風險，所以上面那條 `diff` 放進 §6 的驗收清單，每次改都要跑一次。

### 4.9 `.env` 先放一個空的 `EC2_WORKER_INSTANCE_ID`

> ⚠️ **本步驟由 controller 親自執行；實作 subagent 不打 `aws`／`docker`、不改 `.env`、不跑人工煙霧**（2026-09-02 裁決 R3）。

- [x] 在 `.env` 加一行（**值留空**）：

```ini
EC2_WORKER_INSTANCE_ID=
```

- [x] 確認它在：

```bash
grep -n "^EC2_WORKER_INSTANCE_ID=" .env
```

  預期：印出一行，**等號後面什麼都沒有**。

  📌 **為什麼現在就放：** `config.EC2_WORKER_INSTANCE_ID` 預設就是空字串（Phase 77 放的），
  而 Phase 89 的 `Ec2Probe` 在 instance_id 是空的時候**回 `False` 而且零 API 呼叫**
  （那顆測試叫 `test_instance_id是空的時候回False而且零呼叫`）。所以放一個空的，
  行為完全不變、也不會誤打 AWS；Phase 92 填進真 id，那條路就活了。
  ⚠️ **`.env` 不入版控**（`.gitignore` 擋著），改完**也不會**出現在 §6 的 tree 快照裡；
  本行是空值、行為不變，所以**不必**現在 restart 容器。
  📌 2026-09-02 實查：`.env` 目前**還沒有**這一行（`AWS_*`／`S3_BUCKET`／兩條 `SQS_*`／
  `CLOUD_ROUTE=off`／`CLOUD_RESULT_TIMEOUT_SECONDS=300` 都已經在了），所以這是**新增**一行、不是改值。

### 4.10 收工檢查與快照（**不 commit**）

- [x] 確認測試沒被影響（本 phase 零 Python 變更，顆數應該原封不動）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                   # 預期：672 passed ＋ 0 skipped（與開工基線相同）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q   # 預期：672 passed，逐字相同
ruff format --check app tests scripts && ruff check app tests scripts   # 預期：All checks passed!
```

- [x] **最後一次確認機密沒外洩**（★ **收工前必做**；本輪不 commit，但將來真的要 commit 時要再跑一次）：

```bash
# ① 12 位數字（帳號 ID）不該出現在任何要 commit 的檔案裡
grep -rE "[0-9]{12}" deploy/ || echo "deploy/ 沒有 12 位數字，OK"

# ② 佔位符都還在
grep -c "<ACCOUNT_ID>" deploy/aws/worker-role-policy.json    # 預期：3（兩條 SQS ARN ＋ 一條 ECR ARN 各一行）
grep -c "<S3_BUCKET>"  deploy/aws/worker-role-policy.json    # 預期：2（prefix ARN ＋ bucket ARN 各一行）

# ③ worker.env.example 的每一行等號後面都是空的
grep -E "^[A-Za-z0-9_]+=." deploy/ec2/worker.env.example || echo "範本沒有任何值，OK"

# ④ user-data.sh 裡沒有任何機密字樣
grep -iE "ollama_api_key=|aws_access|aws_secret|amazonaws\.com/" deploy/ec2/user-data.sh \
  || echo "user-data 沒有機密，OK"
```

  預期：①③④ 印出 `OK` 那一行（`grep` 找不到東西），② 印出 `3` 與 `2`。

- [x] **不 commit——記快照**（2026-09-02 裁決 R0：本輪一律不 commit，驗收改用工作樹的 tree SHA 相減）：

```bash
AFTER_TREE=$(.superpowers/sdd/phase0902-2/snapshot-tree)
echo "AFTER_TREE=$AFTER_TREE"
git diff --stat "$BEFORE_TREE" "$AFTER_TREE"    # BEFORE_TREE 是 §2 ⑥ 存的那顆
```

  預期：**恰五個新檔**——`deploy/aws/worker-role-trust.json`、`deploy/aws/worker-role-policy.json`、
  `deploy/ec2/user-data.sh`、`deploy/ec2/personaldocai-worker.service`、`deploy/ec2/worker.env.example`。
  `app/`、`tests/`、`Dockerfile`、`compose.yaml` **一個都不該出現**；
  `.env` 被 `.gitignore` 擋著，**本來就不會**進 tree（所以「看不到 .env」是對的，不是漏了）。

  終端機關掉、`BEFORE_TREE` 不見了的話，改用 `git status --short` 目視也行
  （會多出 `docs/plan/` 底下的計畫檔與 `.superpowers/`，那些是預期的）。

> ⚠️ **不要 `git add`／`git commit`／`git stash`／`git mv`**（2026-09-02 產品負責人指示，裁決 R0；
> 總覽 §7 鐵律 12 本來就是「commit 節奏由產品負責人決定」）。
> 將來產品負責人指示 commit 時，`git add` 一定要**明列檔案**、不要 `git add -A`
> （`/tmp` 的展開檔雖然不在專案裡，但 `docs/plan/` 的計畫檔會被掃進來），訊息可以用：
> `feat: Phase 91 EC2 周邊——SG（inbound 空、egress 只開 443）、S3 Gateway endpoint、IAM role＋instance profile、ECR repo 與第一次手動 push；新增 deploy/aws 兩份 policy JSON 與 deploy/ec2 三份部署檔（尚未啟動實例，672 tests 不變）`

---
## 5. ASCII 圖：本 phase 建的東西各自站在哪裡

```text
 你的 AWS 帳號（<ACCOUNT_ID>）· 東京 ap-northeast-1
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │                                                                              │
 │  ┌── 預設 VPC（$VPC_ID）───────────────────────────────────────────────────┐ │
 │  │                                                                        │ │
 │  │   主要路由表 $RTB_ID                                                    │ │
 │  │     0.0.0.0/0        → internet gateway  （本來就有；機器靠它出網）     │ │
 │  │     pl-xxxx（S3）    → $VPCE_ID          ★ §4.3 加的，Gateway 型、免費 │ │
 │  │                                                                        │ │
 │  │   ┌── 公有子網 $SUBNET_ID（MapPublicIpOnLaunch=true）─────────────────┐ │ │
 │  │   │                                                                  │ │ │
 │  │   │    ┌─ ☁ 這裡將來會放一台 t4g.small（**Phase 92 才建，本 phase 不建**）│ │
 │  │   │    │   掛著：security group $SG_ID   ★ §4.2 建的                 │ │ │
 │  │   │    │            inbound  ＝ []          ← 一條都沒有             │ │ │
 │  │   │    │            outbound ＝ tcp 443 → 0.0.0.0/0  只有這一條      │ │ │
 │  │   │    │   掛著：instance profile personaldocai-worker-role ★ §4.5   │ │ │
 │  │   │    └────────────────────────────────────────────────────────────┘ │ │
 │  │   └──────────────────────────────────────────────────────────────────┘ │ │
 │  └────────────────────────────────────────────────────────────────────────┘ │
 │                                                                              │
 │  ┌── IAM（全球性，不屬於任何區域）★ §4.4／§4.5 ──────────────────────────┐ │
 │  │  role  personaldocai-worker-role                                       │ │
 │  │    ├ trust  ： "誰可以借我" ＝ ec2.amazonaws.com                       │ │
 │  │    │           （deploy/aws/worker-role-trust.json）                   │ │
 │  │    ├ inline ： personaldocai-worker-inline                             │ │
 │  │    │           S3 documents/* Get+Put+bucket List｜jobs Recv/Del/ChgVis│ │
 │  │    │           results Send｜ECR Auth(*) ＋ 本 repo 三個 pull 動作      │ │
 │  │    │           （deploy/aws/worker-role-policy.json，佔位符版進 git）  │ │
 │  │    └ managed： AmazonSSMManagedInstanceCore  ← 沒有它就進不去那台機器  │ │
 │  │  instance profile personaldocai-worker-role（同名，裡面裝著上面那個 role）│
 │  └────────────────────────────────────────────────────────────────────────┘ │
 │                                                                              │
 │  ┌── ECR ★ §4.6／§4.7 ────────────────────────────────────────────────────┐ │
 │  │  registry  <ACCOUNT_ID>.dkr.ecr.ap-northeast-1.amazonaws.com           │ │
 │  │    repository personaldocai-worker（private、scanOnPush=false）        │ │
 │  │      tag  <git-sha>   ← 回得去用的                                     │ │
 │  │      tag  latest      ← systemd 的 ExecStartPre 每次啟動都拉這個        │ │
 │  └────────────────────────────────────────────────────────────────────────┘ │
 │                                                                              │
 │  （Phase 84／85 已經有的：S3 $S3_BUCKET、SQS personaldocai-jobs／-results）  │
 └──────────────────────────────────────────────────────────────────────────────┘
              ▲ docker push（§4.7 手動；Phase 94 之後由 CD 做）
        這台 Mac ── personaldocai-worker:local（arm64，Phase 90 建的）
                  └ deploy/ec2/ 三份檔（user-data.sh／unit／worker.env.example，進 git，92 才用到）
```

---

## 6. 驗收清單

> 先把變數載回來：`cd /Users/linjunting/personalDocAI && . /tmp/p91-vars.sh && set -a; . ./.env; set +a; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`
> （最後那個 `unset` 不能省——不然下面每一條 `aws` 都會用到 `personaldocai-mac` 那把最小權限 key，理由見 §2）
>
> ⚠️ **下表第 1〜13 條與最後的「費用檢查」都是 `aws`／`docker` 指令，
> 由 controller 親自執行；實作 subagent 不打 `aws`／`docker`**（2026-09-02 裁決 R3）。
> 第 14〜16 條與後面的 pytest／ruff／grep／快照那幾條是純本機檢查，誰跑都可以。
>
> ⚠️ 所有 `aws` 指令**一律不帶 `--profile`**——admin 的 key 就在 `aws configure` 設的
> **default profile**，這台 Mac 上沒有叫 `personaldocai-admin` 的具名 profile。

| # | 要驗的事 | 指令 | 預期輸出 |
|---|---|---|---|
| 1 | SG 的 **inbound 是空的** | `aws ec2 describe-security-groups --region "$AWS_REGION" --filters Name=group-name,Values=personaldocai-worker-sg --query 'SecurityGroups[0].IpPermissions' --output json` | `[]` |
| 2 | SG 的 outbound **只有一條 tcp 443** | 同上但 `--query 'SecurityGroups[0].IpPermissionsEgress[].{P:IpProtocol,From:FromPort,To:ToPort}' --output json` | 恰一筆 `{"P":"tcp","From":443,"To":443}` |
| 3 | 沒有建 NAT Gateway | ``aws ec2 describe-nat-gateways --region "$AWS_REGION" --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text`` | 空（沒有輸出） |
| 4 | 沒有配置 Elastic IP | `aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text` | 空（沒有輸出） |
| 5 | S3 Gateway endpoint 掛在主要路由表 | `aws ec2 describe-vpc-endpoints --region "$AWS_REGION" --vpc-endpoint-ids "$VPCE_ID" --query 'VpcEndpoints[0].{T:VpcEndpointType,S:State}' --output json` | `{"T":"Gateway","S":"available"}` |
| 6 | IAM role 存在、trust 是 EC2 | `aws iam get-role --role-name personaldocai-worker-role --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text` | `ec2.amazonaws.com` |
| 7 | inline policy 掛上了 | `aws iam list-role-policies --role-name personaldocai-worker-role --query 'PolicyNames' --output text` | `personaldocai-worker-inline` |
| 8 | SSM managed policy 掛上了 | `aws iam list-attached-role-policies --role-name personaldocai-worker-role --query 'AttachedPolicies[].PolicyName' --output text` | `AmazonSSMManagedInstanceCore` |
| 9 | instance profile 裡面**有那個 role** | `aws iam get-instance-profile --instance-profile-name personaldocai-worker-role --query 'InstanceProfile.Roles[].RoleName' --output text` | `personaldocai-worker-role` |
| 10 | ECR repo 存在且不自動掃描 | `aws ecr describe-repositories --region "$AWS_REGION" --repository-names personaldocai-worker --query 'repositories[0].imageScanningConfiguration.scanOnPush'` | `false` |
| 11 | ECR 上有 `<sha>` 與 `latest` **兩個** tag | `aws ecr describe-images --region "$AWS_REGION" --repository-name personaldocai-worker --query 'imageDetails[?imageTags].imageTags[]' --output json` | 陣列同時含 `"latest"` 與 `git rev-parse --short HEAD` 的值 |
| 12 | 推上去的是 **arm64** | `docker image inspect "$ECR_URI:latest" --format '{{.Architecture}}'` | `arm64` |
| 13 | **沒有啟動任何實例** | `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=tag:Name,Values=personaldocai-worker Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text` | 空（沒有輸出）——本 phase 不建實例 |
| 14 | 五份部署檔都在 | `ls deploy/aws deploy/ec2` | `deploy/aws/`：`mac-policy.json`（82）、`s3-lifecycle.json`（84）＋本 phase 的 `worker-role-trust.json`、`worker-role-policy.json`；`deploy/ec2/`：`personaldocai-worker.service`、`user-data.sh`、`worker.env.example` |
| 15 | 兩份 systemd unit **逐字相同** | `awk '/<<.UNIT.$/{f=1;next} /^UNIT$/{f=0} f' deploy/ec2/user-data.sh > /tmp/u && diff /tmp/u deploy/ec2/personaldocai-worker.service && echo SAME` | `SAME`（diff 無輸出） |
| 16 | `.env` 有空的實例 id | `grep -n "^EC2_WORKER_INSTANCE_ID=$" .env` | 印出一行（等號後面是空的） |

再加下面這幾條（要看輸出，所以單獨列）：

- [x] **全量 pytest 顆數 ＝ 開工基線 672 ＋ 0 ＝ 672**（本 phase 零 Python 變更；672 是 2026-09-02 實查值）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate && pytest -q
```

  預期：`672 passed`，**0 skipped**。

- [x] **端點仍 22、openapi 零 DELETE**

```bash
pytest -q -k "端點恰好是這22支 or 端點數仍為22 or 端點數不變"
```

  預期：`3 passed`（三顆清點測試：`test_端點恰好是這22支`／`test_端點數仍為22`／`test_端點數不變`）。
  ⚠ 不要只寫 `-k "端點"`——名字裡有「端點」兩個字的測試有 15 顆，會多跑一堆不相干的。

- [x] **零依賴實證（三個死埠一起指）**

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

  預期：`672 passed`，與上一條逐字相同。

- [x] **機密沒外洩**（★ 收工前必做，§4.10 那四條；本輪不 commit，將來 commit 前再跑一次）

```bash
grep -rE "[0-9]{12}" deploy/ || echo "deploy/ 沒有 12 位數字，OK"
grep -c "<ACCOUNT_ID>" deploy/aws/worker-role-policy.json          # 預期：3
grep -c "<S3_BUCKET>"  deploy/aws/worker-role-policy.json          # 預期：2
grep -E "^[A-Za-z0-9_]+=." deploy/ec2/worker.env.example || echo "範本沒有任何值，OK"
git status --short | grep -E "^.. \.env$" || echo ".env 沒有被 git 追蹤，OK"
```

  預期：三行 `OK` ＋ 一個 `3` ＋ 一個 `2`（第二、三條印的數字：`<ACCOUNT_ID>` 在兩條 SQS ARN ＋ 一條 ECR ARN；`<S3_BUCKET>` 在 prefix ARN ＋ bucket ARN）。

- [x] **專案 `data/` 沒被弄髒、`docs/spec/` 一字未動**

```bash
ls data/staging/                 # 預期：空的
git status --short docs/spec/    # 預期：零輸出
```

- [x] **只動了該動的檔**（不 commit，用兩顆 tree SHA 相減——裁決 R0）

```bash
AFTER_TREE=$(.superpowers/sdd/phase0902-2/snapshot-tree)
git diff --stat "$BEFORE_TREE" "$AFTER_TREE"     # BEFORE_TREE 是 §2 ⑥ 存的那顆
```

  預期：**恰五個新檔**（`deploy/aws/` 兩份 JSON ＋ `deploy/ec2/` 三份）。
  `app/`、`tests/`、`Dockerfile`、`compose.yaml` **一個都不該出現**；
  `.env` 被 `.gitignore` 擋著，本來就不會進 tree。
  `BEFORE_TREE` 不見了（終端機關掉）就退而用 `git status --short` 目視
  ——那會多出 `docs/plan/` 的計畫檔與 `.superpowers/`，那些是預期的。

- [x] **ruff 過**：`ruff format --check app tests scripts && ruff check app tests scripts` → `All checks passed!`

- [x] **費用檢查**（⚠ controller 執行；本 phase 建的東西全部免費或極微量：（2026-09-03 controller：`describe-budgets` 看到 `personaldocai-budget` 5 USD ✅；Console 的 Free plan 人工確認留給產品負責人）
      SG／Gateway endpoint／IAM 全免費，ECR 只有儲存費，三百多 MB ≈ $0.04／月，從點數扣）

```bash
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit}' --output table
```

  預期：看得到 `personaldocai-budget`、上限 5 USD（Phase 82 建的）。
  **人工：** 順便到 AWS Console → Billing and Cost Management 確認方案仍是 **Free plan（未升 Paid）**。

---

## 7. 常見陷阱

1. **`revoke-security-group-egress` 「成功」了，但規則其實還在。**
   **症狀：** 指令回 `{"Return": true}`，但 `describe-security-groups` 一看，
   `IpPermissionsEgress` 裡有**兩條**（`-1` 全開 ＋ `tcp 443`）。
   **原因：** AWS 只在**完全比對相符**時才撤掉規則；對不上時它**不報錯**（`Return` 仍是 `true`，
   新版 CLI 只多印一個 `UnknownIpPermissions`）。最常見是 `--ip-permissions` 字串打錯
   （少了 `IpRanges=[{...}]` 的方括號、或把 `-1` 寫成 `all`）；AWS 還會**正規化 CIDR**
   （你寫 `10.0.0.18/18`，它存的是 `10.0.0.0/18`），對不上就靜靜地不動。
   **正解：** 每次 revoke 之後**一定**要跑 §4.2 最後那兩條驗證；看到兩條就把字串重貼一次。

2. **instance profile 剛建好就 `run-instances`，被說「名字無效」。**
   **症狀：** `InvalidParameterValue: Value (personaldocai-worker-role) for parameter
   iamInstanceProfile.name is invalid. Invalid IAM Instance Profile name`
   **原因：** IAM 與 EC2 是兩套控制平面，中間有幾秒到幾十秒的傳播延遲。**名字完全正確**，
   只是 EC2 那邊還沒看到——這個訊息極度誤導，很多人在這裡花半小時檢查有沒有打錯字。
   **正解：** §4.5 最後跑 `aws iam wait instance-profile-exists`（輪詢到 40 秒）；
   而且 Phase 92 的 `run-instances` 寫成「失敗就等 15 秒再試、最多三次」的小迴圈
   ——因為 `wait` 只確認 **IAM 那一側**，**不保證 EC2 那一側**。

3. **「SSM 進不去那台機器」的兩個原因（合起來講，因為症狀一模一樣）。**
   **症狀：** Phase 92 建完機器，`aws ssm describe-instance-information` 永遠看不到它；
   `aws ssm start-session` 回 `TargetNotConnected`。而我們的 SG **inbound 是空的**（沒有 SSH），
   所以沒有第二條路進去——真的救不回來時只能 Terminate 重建。
   **原因 A：** 忘了掛 `AmazonSSMManagedInstanceCore`。SSM agent 有在跑，但**沒有權限**
   跟 SSM 服務對話。
   **原因 B：** outbound 443 沒開對（`authorize` 打成 `--port 80`，或 revoke 之後忘了 authorize）。
   SSM agent 是**主動往外連** 443 的——出不了網就 SSM／ECR／S3／SQS 全部不通。
   **正解：** 先看 §6 第 8 條（managed policy 掛上了沒）與第 2 條（outbound 恰一條 tcp 443）；
   再確認機器在**公有子網**且有公有 IP。⚠️ **不要**因為連不上就去開 inbound 22
   ——那違反 design6 §0 禁止第 3 條，而且也修不好（問題在出站，不在進站）。
   **這也是本 phase 排在 Phase 92 前面的理由**：IAM 與 SG 先做對，機器才建得下去。

4. **`file://` 的斜線數量搞錯。**
   **症狀：** `Unable to load paramfile file://tmp/…` 或 `MalformedPolicyDocument`。
   **原因：** `file://` ＋ **相對路徑**是兩條斜線；`file://` ＋ **絕對路徑**是**三條**
   （`file:///tmp/x.json`）。少一條就變成「相對於目前目錄的 `tmp/x.json`」。
   **正解：** 一律用 `file://` 讀檔，**不要**把 JSON 直接貼進參數
   （shell 會把引號吃掉，然後你得到一個完全看不出原因的 `MalformedPolicyDocument`）。
   出錯時先 `python3 -m json.tool <那個檔>` 確認 JSON 本身合法。

5. **policy JSON 裡寫死了真帳號 ID，然後 commit 進 git。**
   **症狀：** `git log -p` 裡永遠留著你的 12 位帳號 ID。
   **原因：** `sed` 展開時手滑寫成 `> deploy/aws/worker-role-policy.json`（覆蓋原檔）
   而不是 `> /tmp/worker-role-policy.json`。
   **正解：** §4.10 的 `grep -rE "[0-9]{12}" deploy/` 就是在守這件事，**收工前（與將來 commit 前）一定要跑**。
   真的寫進去了：改回佔位符再 commit。⚠ Phase 93 的 `test_部署用的policy裡沒有寫死帳號ID`
   會掃 `deploy/aws/` **全部** JSON（含本 phase 這兩份），但它要到 Phase 93 才存在——
   在那之前這條 `grep` 沒有自動化替身，別省。

6. **漏掉 `--region`，資源建在美東。**
   **症狀：** `describe-*` 查不到剛建的東西；或 `run-instances` 說 SG 不存在
   （`InvalidGroup.NotFound`），但你明明看到它建成功了。
   **原因：** 不帶 `--region` 時 CLI 用 `~/.aws/config` 的預設值，那常常是 `us-east-1`。
   SG／VPC endpoint／ECR **都是區域性資源**。（IAM 是全球性的，不受影響
   ——所以會出現「IAM 都對、其他全找不到」的怪現象。）
   **正解：** 每一條 `aws ec2`／`aws ecr` 都帶 `--region "$AWS_REGION"`。
   已經建錯了：到那個區域把東西刪掉（全部免費，零損失）再重跑。

7. **想「順便」建 NAT Gateway 或 Elastic IP。**
   **症狀：** 點數開始每小時扣。NAT Gateway 在東京約 **$0.062／小時 ＋ 每 GB 流量**，
   放著不管一個月就是 $45 上下——Free plan 的 $100 點數兩個月就沒了，然後**關帳**。
   **原因：** 看到「機器要出網」就直覺去建 NAT。但**公有子網 ＋ 公有 IP 本來就出得去**，
   NAT 是給**私有**子網用的。
   **正解：** design6 §0 禁止第 4 條、§7「網路」那列都明文禁止；§6 第 3、4 條在掃這兩樣。
   Elastic IP 同理——它**在沒掛到跑著的機器上時才收費**，而我們的機器常態是 Stop，
   等於買一個「專門在你沒用時收費」的東西。我們**不需要固定 IP**（inbound 是空的，
   沒有任何人會主動連進來）。

8. **user-data 裡寫了機密。**
   **症狀：** 半年後想做 AMI 快照，才發現 `OLLAMA_API_KEY` 明文躺在機器的
   `/var/lib/cloud/instances/<id>/user-data.txt` 裡。
   **原因：** user-data 會**原封不動保留在機器上**，而且 `describe-instance-attribute`
   任何有權限的人都讀得到。
   **正解：** 機密一律走 `/opt/personaldocai/worker.env`（`chmod 600`，人手動放）。
   §4.10 的第 ④ 條 `grep` 就是在守這件事。

9. **在 ★G2 還沒過的時候就跑 `run-instances`。**
   **症狀：** 「反正我都做到這裡了，順手把機器開起來看看」——然後忘了 Stop，點數整晚在燒。
   **原因：** 本 phase 的東西全部免費，很容易產生「再多一步也沒差」的錯覺。
   但 `run-instances` 是**第一個真的花錢**的指令。
   **正解：** §6 第 13 條就是在驗「沒有任何實例」。啟動實例是 Phase 92 §4.3，
   而且那一份的每一個 Demo 結尾都有 `stop-instances`。

10. **載入 `.env` 之後忘了 `unset`，每一條建資源指令都 `AccessDenied`。**
   **症狀：** `aws sts get-caller-identity` 是通的、`aws_check.py` 也 OK，但 `create-security-group`／
   `create-role`／`create-repository` 全部回
   `An error occurred (AccessDenied) when calling the … operation: User: arn:aws:iam::…:user/personaldocai-mac is not authorized to perform: …`。
   **原因：** `.env` 裡的 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` 是 `personaldocai-mac` 那組**最小權限** key
   （S3 前綴＋兩條佇列＋`ec2:DescribeInstances`，就這些），而**環境變數的優先序比 `~/.aws` 高**
   ——`set -a; . ./.env; set +a` 之後 CLI 就改用它了。
   **正解：** 錯誤訊息裡的 `user/personaldocai-mac` 就是線索。`unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`
   之後重查 `aws sts get-caller-identity --query Arn --output text`，看到 `:user/personaldocai-admin` 再重跑失敗那條。
   本檔每一個載入 `.env` 的地方（§2、§4.1、§6）都緊接著 `unset`，不要省。
   ⚠️ **不要想用 `--profile personaldocai-admin` 繞過它**（2026-09-02 實查）：這台 Mac 的 `~/.aws`
   **沒有**這個具名 profile——admin 那把 key 就放在 `aws configure` 設的 **default profile**，
   帶了 `--profile` 只會換一個更難懂的錯（`The config profile (personaldocai-admin) could not be found`）。
   `docs/plan/aws/` 那五份「新手步驟」裡寫的 `--profile personaldocai-admin` 在這台機器上跑不動，
   那幾份只當名詞對照用。**唯一正確的做法就是 `unset` 那兩個環境變數。**

11. **容器裡的工人拿不到憑證（Phase 92 才會發作，但根源在本 phase 寫的 unit 檔）。**
   **症狀：** `systemctl status` 是 active、`docker logs cloud-worker` 卻一直是
   `botocore.exceptions.NoCredentialsError: Unable to locate credentials`，可是機器上直接打
   `aws sts get-caller-identity`（`ExecStartPre` 那條 `ecr get-login-password` 也是）完全正常。
   **原因：** unit 檔的 `docker run` 用的是 Docker 預設的 bridge 網路，容器去 IMDS（`169.254.169.254`）
   拿 instance-profile 憑證要**多跨一跳**；IMDSv2 的 `HttpPutResponseHopLimit` 若是 `1`，回應到不了容器
   （AWS 官方文件明寫「in a container environment, consider increasing the hop limit to 2」）。
   機器本身的 `aws` CLI 不經過容器，所以它好好的——這就是為什麼很難聯想到。
   **正解：** Phase 92 §4.3 `run-instances` 的 `--metadata-options` 要寫成
   `HttpTokens=required,HttpPutResponseHopLimit=2`（AL2023 AMI 的預設就是 2，但帳號層的預設值可以蓋過 AMI，
   寫明白最保險）。已經開起來的機器不必重建：
   `aws ec2 modify-instance-metadata-options --instance-id <id> --http-put-response-hop-limit 2 --region "$AWS_REGION"`。

12. **工人一起來就對每一則 jobs 炸 `AccessDenied`，可是 policy 明明有 `s3:GetObject`。**
   **症狀：** `docker logs cloud-worker` 每一則都是 `An error occurred (403) when calling the HeadObject/GetObject operation: Forbidden`，
   出事的 key 永遠是 `documents/<job_id>/result.json`——也就是**還不存在**的那個檔。
   **原因：** S3 的規則——對不存在的 key 做 `GetObject`，要有 `s3:ListBucket` 才回 404，沒有就回 403。
   工人第一步是拿 `result.json` 做冪等檢查（Phase 87 規則 1），`aws_mailbox.get_object` 只把 404（`NoSuchKey`）當 `None`，
   403 會直接往外丟。多半是有人「幫忙收緊」把 `BucketListSoMissingKeyIs404` 那條刪了，或把它的 Resource 改成 prefix ARN。
   **正解：** §4.4 的 policy 要有獨立的 `s3:ListBucket` Statement，`Resource` 是 **bucket ARN**（`arn:aws:s3:::<S3_BUCKET>`）；
   改完重跑 §4.5 的 `sed` ＋ `put-role-policy`（同名覆蓋，機器不必重開；instance profile 的憑證幾分鐘內會拿到新權限）。

---

## 8. 完成後的專案狀態

> ⚠ 2026-09-03 改判（總覽 §10.2 追認項 T）：EC2 改 GPU 機（x86_64），ECR 的 `latest` 改推**多架構** manifest（amd64＋arm64；tag `<sha>-dirty` 直到 commit）；`deploy/ec2/` 三檔已改成「host 跑 Ollama、容器 `--network host`、`WORKER_VLM_BACKEND=local`」版本，以實檔為準。本 phase 建的 SG／endpoint／role／ECR 不受影響。

**系統多了什麼（全部在 AWS 上，本機只多五個檔）：**

| 在哪裡 | 東西 | 費用 |
|---|---|---|
| AWS（東京） | security group `personaldocai-worker-sg`：inbound `[]`、outbound 只有 tcp 443 | 免費 |
| AWS（東京） | S3 Gateway VPC endpoint，掛在預設 VPC 的主要路由表 | 免費 |
| AWS（全球） | IAM role `personaldocai-worker-role` ＋ 同名 instance profile；一份 inline policy ＋ 一份 AWS managed policy | 免費 |
| AWS（東京） | ECR repository `personaldocai-worker`，裡面有 `<git-sha>` 與 `latest` 兩個 tag 指向同一份 arm64 映像 | 儲存費 ≈ $0.04／月（從點數扣） |
| 本機（進 git） | `deploy/aws/worker-role-trust.json`、`deploy/aws/worker-role-policy.json`（佔位符版）、`deploy/ec2/user-data.sh`、`deploy/ec2/personaldocai-worker.service`、`deploy/ec2/worker.env.example` | — |
| 本機（不進 git） | `.env` 多一行空的 `EC2_WORKER_INSTANCE_ID=` | — |

**對外行為變了沒：** **完全沒有。** 本 phase **零 Python 變更、零測試變更**——
端點仍 **22** 支、`openapi.json` 零 DELETE、`POST /photos` 仍回 202、前端一行沒改、
資料庫零改動、`Dockerfile`／`compose.yaml`／`compose.dev.yaml` 一個字沒動。
`.env` 那一行是**空值**，而 `Ec2Probe` 在 instance_id 為空時回 `False` 且零 API 呼叫
（Phase 89 的 `test_instance_id是空的時候回False而且零呼叫`），所以連行為都沒變。

**顆數：** **672 passed ＋ 0 skipped**（開工基線 672 ＋ **0**；**2026-09-02 實查**）。
與總覽 §2.7／§9 定案的「Phase 91 **＋0 顆**」一致，**零偏離**——
只是累計的絕對值要用雙寫法讀：總覽 §9 寫 **662（實 672）**，
那張表的絕對值比實測少 10（74〜86 的 review fix wave 多補了幾顆），**只對「新增幾顆」**。

**還沒做的事（刻意留給 Phase 92）：**
啟動 EC2 實例、放 `worker.env`、`systemctl start`、Demo 2／2b、
`.env` 填真的 `EC2_WORKER_INSTANCE_ID` 與 `CLOUD_ROUTE=ec2`、
以及 `LAUNCH.md`／`CLAUDE.md`／`README.md` 三份文件。

**下一步：Phase 92（`phase-92-EC2真機與文件.md`）**
——用本 phase 建好的 subnet／SG／instance profile／user-data 啟動一台 `t4g.small`，
用 Session Manager 放好 `worker.env`、把服務 start 起來，
跑 **Demo 2**（Start → 非敏感走雲端 → 照片進待決定 → 問得到）與
**Demo 2b**（Stop → 再傳一張 → 自動走本機、S3 零新物件），
做完 **Stop**，然後寫三份文件。**Phase 92 之後是 ★G3。**

---

## 9. 實作紀錄（2026-09-02，實作 subagent）

**結論：§4.4 與 §4.8 兩節（純寫檔）照計畫做完，五個新檔逐字落地、零差異。**
本 task **零 Python、零測試、零 `aws`／`docker` 指令、零 `.env` 變更、未 commit**（裁決 R0／R3）。
§4.1〜§4.3、§4.5〜§4.7、§4.9、§4.10 的 AWS／Docker／`.env` 步驟與 §6 第 1〜13 條**仍待 controller 親自執行**，
checkbox 一律留白。

### 9.1 交付的五個檔（全部是新檔）

| 檔案 | 行數 | 來源 | 備註 |
|---|---|---|---|
| `deploy/aws/worker-role-trust.json` | 13 | §4.4 第 561〜575 行的 ```json 區塊 | `Principal.Service = ec2.amazonaws.com`、`sts:AssumeRole` |
| `deploy/aws/worker-role-policy.json` | 58 | §4.4 第 585〜644 行的 ```json 區塊 | 六個 `Sid`，佔位符 `<ACCOUNT_ID>`×3／`<S3_BUCKET>`×2／`<AWS_REGION>`×3，零真值 |
| `deploy/ec2/personaldocai-worker.service` | 22 | §4.8 第 944〜967 行的 ```ini 區塊 | `ExecStop=docker stop -t 120` ＋ `TimeoutStopSec=150`（總覽 §10.2 裁決 O） |
| `deploy/ec2/user-data.sh` | 76 | §4.8 第 991〜1068 行的 ```bash 區塊 | 已 `chmod +x`（`-rwxr-xr-x`）；內嵌 `<<'UNIT'` 那段與上一列**逐字相同** |
| `deploy/ec2/worker.env.example` | 32 | §4.8 第 1074〜1107 行的 ```ini 區塊 | 8 個變數名、等號後全空；無 `VLM_MAX_ATTEMPTS`（R9）、無 `WORKER_VERSION`、無金鑰、無 `AWS_ENDPOINT_URL` |

**落地手法：** 不用手打，直接以 `sed -n '<起>,<迄>p' <計畫檔>` 把 §4.4／§4.8 的程式碼區塊**原樣導出成檔**，
再用 `diff <(sed -n …) <檔>` 回頭比對。這樣「逐字相同」不是靠肉眼，是可重跑的證據
（也順帶避開了「Write 工具會把字面跳脫吃成真字元」那個既知陷阱）。五份 diff 全部零輸出。

### 9.2 自驗輸出（全部在本機、零外部服務）

| 檢查 | 指令 | 實際輸出 |
|---|---|---|
| JSON 語法（§4.4） | `python3 -m json.tool deploy/aws/worker-role-*.json` | `trust OK` ／ `policy OK` |
| 兩份 unit 逐字相同（§4.8） | `awk '/<<.UNIT.$/{f=1;next} /^UNIT$/{f=0} f' deploy/ec2/user-data.sh > /tmp/u && diff /tmp/u deploy/ec2/personaldocai-worker.service` | 無輸出 → `兩份 unit 逐字相同` |
| §4.10 ① 無 12 位數字 | `grep -rE "[0-9]{12}" deploy/` | `deploy/ 沒有 12 位數字，OK` |
| §4.10 ② 佔位符還在 | `grep -c "<ACCOUNT_ID>" …` ／ `grep -c "<S3_BUCKET>" …` | `3` ／ `2`（與預期相同） |
| §4.10 ③ 範本零值 | `grep -E "^[A-Za-z0-9_]+=." deploy/ec2/worker.env.example` | `範本沒有任何值，OK`（另跑嚴格版，見 9.3 差異 2） |
| §4.10 ④ user-data 無機密 | `grep -iE "ollama_api_key=\|aws_access\|aws_secret\|amazonaws\.com/" deploy/ec2/user-data.sh` | `user-data 沒有機密，OK` |
| NBSP／換行／CRLF | Python 逐檔掃 `b"\xc2\xa0"` | 五檔皆 `NBSP=0`、以換行結尾、無 CRLF（計畫檔全文也是 0） |
| shell 語法（只檢查不執行） | `bash -n deploy/ec2/user-data.sh` | `user-data.sh 語法 OK` |
| policy 內容對總覽 §2.8 | `python3 -c "json.load(...)"` 列出 Sid→Action→Resource | 六列全中：S3 prefix 的 `GetObject`／`PutObject`（**無 `DeleteObject`**）、bucket ARN 的 `ListBucket`（§10.2 P）、jobs 的 `Receive`／`Delete`／`ChangeMessageVisibility`（**無 `Send`**）、results 的 `SendMessage`（**無 `Receive`**）、`ecr:GetAuthorizationToken`（Resource `*`）、ECR pull 三項鎖 repo（**無任何 Put／Upload／Complete**） |
| env 變數名對得上 | 比對 unit 的 `${…}` × config.py 的 `os.getenv` | unit 用 `AWS_REGION`／`ECR_REGISTRY`／`ECR_IMAGE`；`config.py` 讀 `AWS_REGION`／`S3_BUCKET`／`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`／`OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL`——範本恰好 8 個、無多無少（`cloud_worker.main()` 開機檢查的四個都在） |
| 顆數（本 phase 零 Python 變更） | `pytest --collect-only -q \| tail -1` | `674 tests collected`（與 Phase 90 收工值相同；**未跑全量**，依 task brief 由 controller 統一跑） |
| 只動了該動的檔 | `git diff --stat $(cat .superpowers/sdd/phase0902-2/T91_BASE) $(.superpowers/sdd/phase0902-2/snapshot-tree)` | 恰五個新檔、`5 files changed, 201 insertions(+)`；`app/`／`tests/`／`Dockerfile`／`compose.yaml` 一個都沒有 |

### 9.3 與計畫檔的差異（三條，都不影響交付內容）

1. **顆數：計畫檔 §4.10／§6 寫「672」，實際是 674。** 這不是本 phase 造成的——
   Phase 88 的 review fix 多了 2 顆（phase-90 §9 已記「開工基線 670 不是 668」）。
   本 phase 零 Python 變更，`--collect-only` 前後都是 674。

2. **§4.10 ③ 的正規式漏得掉 `S3_BUCKET=` 這一行。** `grep -E "^[A-Z_]+=."` 的字元集沒有數字，
   > ⚠ 2026-09-03 controller 更正：本檔 §4.10 ③ 已依裁決 R19 改成 `^[A-Za-z0-9_]+=.`（實作者跑的是自己另寫的弱版，不是本檔的）；此條已無事可做。
   而 `S3_BUCKET` 的第二個字元是 `3` → 這條檢查**掃不到那一行**，萬一有人把 bucket 名填進範本，
   它會安靜地放行。已另跑嚴格版 `grep -nE "^[A-Za-z0-9_]+=." deploy/ec2/worker.env.example`
   （同樣零命中＝範本真的沒有任何值），並逐一確認 8 個變數行都在、等號後皆空。
   **建議：** Phase 93／95 若要把這條變成自動化掃碼測試，字元集請用 `[A-Za-z0-9_]`。

3. **`grep -P` 在這台 Mac 上不能用**（BSD grep 無 `-P`），所以 NBSP 檢查改用 Python 掃位元組
   `b"\xc2\xa0"`，結論相同（五檔全 0）。

### 9.4 附帶觀察（不是差異，給 controller 參考）

- `deploy/aws/mac-policy.json`（Phase 82）把區域**寫死**成 `ap-northeast-1`、bucket 用萬用字元
  `personaldocai-mailbox-*`；本 phase 的 `worker-role-policy.json` 依計畫用 `<AWS_REGION>`／`<S3_BUCKET>`
  佔位符（§4.5 再 `sed` 展開）。兩份風格不同是**計畫明訂**的，不是筆誤；Phase 93 那顆
  `test_部署用的policy裡沒有寫死帳號ID` 只掃 12 位數字，兩種風格都會過。
  但若日後想加「不准寫死區域」的掃碼，記得 `mac-policy.json` 會紅。
- `deploy/ec2/` 是新目錄，`.dockerignore` 目前**沒有** `deploy/` 那一行（Phase 90 只加了自己要的）；
   > ⚠ 2026-09-03 controller 更正：`.dockerignore` **已有** `deploy/` 那一行（Phase 90 加的，L21〜23）。
  這五個檔不需要進映像，若要收乾淨可由後續 phase 決定，本 phase 不動。

---

## 附：本文件引用的官方文件

- [`aws ec2 describe-vpcs`（`is-default` 過濾器）](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-vpcs.html)
- [`aws ec2 describe-subnets`](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-subnets.html)
- [`aws ec2 describe-route-tables`（`association.main` 過濾器）](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-route-tables.html)
- [Security group 規則（含「新 SG 預設允許所有 outbound」）](https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html)
- [`aws ec2 create-security-group`](https://docs.aws.amazon.com/cli/latest/reference/ec2/create-security-group.html)
- [`aws ec2 revoke-security-group-egress`](https://docs.aws.amazon.com/cli/latest/reference/ec2/revoke-security-group-egress.html)
- [`aws ec2 authorize-security-group-egress`](https://docs.aws.amazon.com/cli/latest/reference/ec2/authorize-security-group-egress.html)
- [S3 Gateway VPC endpoint（「There is no additional charge for using gateway endpoints」）](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html)
- [`aws ec2 create-vpc-endpoint`](https://docs.aws.amazon.com/cli/latest/reference/ec2/create-vpc-endpoint.html)
- [IAM policy 語法（`Version` 只有 `2012-10-17`）](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies.html)
- [`aws iam create-role`](https://docs.aws.amazon.com/cli/latest/reference/iam/create-role.html)
- [`aws iam wait instance-profile-exists`](https://docs.aws.amazon.com/cli/latest/reference/iam/wait/instance-profile-exists.html)
- [EC2 instance profile（把 role 掛到機器上）](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_switch-role-ec2_instance-profiles.html)
- [`AmazonSSMManagedInstanceCore`（SSM 需要的最小權限）](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonSSMManagedInstanceCore.html)
- [`aws ecr create-repository`](https://docs.aws.amazon.com/cli/latest/reference/ecr/create-repository.html)
- [ECR 私有 registry 認證（`get-login-password` ＋ `--password-stdin`）](https://docs.aws.amazon.com/AmazonECR/latest/userguide/registry_auth.html)
- [ECR 推映像](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push.html)
- [`aws ecr describe-images`](https://docs.aws.amazon.com/cli/latest/reference/ecr/describe-images.html)
- [EC2 user-data（以 root 執行、只跑第一次、log 在 `/var/log/cloud-init-output.log`）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [AL2023 套件管理（`dnf install docker`）](https://docs.aws.amazon.com/linux/al2023/ug/managing-repos-os-updates.html)
- [systemd `systemd.service`（`ExecStartPre=` 的 `-` 前綴、`${VAR}` 代換規則）](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd `EnvironmentFile=`](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#EnvironmentFile=)
- [公有 IPv4 收費說明（為什麼不配 Elastic IP）](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)
- [SSM Agent 預裝的 AMI 清單（含 AL2023）](https://docs.aws.amazon.com/systems-manager/latest/userguide/ami-preinstalled-agent.html)
- [AL2023 內建 AWS CLI v2（「AL2023 ships with AWS CLI version 2」）](https://docs.aws.amazon.com/linux/al2023/ug/awscli2.html)
- [IMDS 存取注意事項（container environment 請把 hop limit 提到 2）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html#imds-considerations)
- [ECR 身分型 policy 範例（pull 需要的動作；`GetAuthorizationToken` 的 Resource 必須是 `*`）](https://docs.aws.amazon.com/AmazonECR/latest/userguide/security_iam_id-based-policy-examples.html)
- [ECR 定價（儲存費；2025-07-15 後新帳號改點數制的說明）](https://aws.amazon.com/ecr/pricing/)
- [S3 `GetObject` API 的 Permissions 段（有 `s3:ListBucket` 才回 404，沒有回 403）](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)
- [`aws iam put-role-policy`／`attach-role-policy`／`create-instance-profile`／`add-role-to-instance-profile`](https://docs.aws.amazon.com/cli/latest/reference/iam/)
