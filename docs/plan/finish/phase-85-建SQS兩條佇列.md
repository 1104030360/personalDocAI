# Phase 85：建 SQS 兩條佇列

> 📌 **2026-09-02 校準紀錄**（本檔成稿於 2026-08-31，之後工作樹改過：Phase 81／82 進 commit、
> 73〜82 歸檔、識別字全面英文化、AWS 帳號由產品負責人開好。裁決全文見
> `.superpowers/sdd/phase0902-1/progress.md` 的 R0〜R7，事實與命名契約見同目錄 `brief-common.md`）：
>
> | 裁決 | 本檔怎麼改 |
> |---|---|
> | **R0 不 commit** | §4.9 的 commit 步驟改成「**記工作樹快照**」；commit 節奏由產品負責人決定（總覽 §7 鐵律 12） |
> | **R1 識別字一律英文** | `scripts/aws_check.py` 本 phase 新增的識別字全部英文：`check_sqs()`（照 brief §5 的跨檔契約）、helper `receive_own_message()`、常數 `RECEIVE_RETRIES`、參數 `receive`／`queue_name`、區域變數 `mailbox`／`message`。**`test_中文` 測試函式名、log 字樣、錯誤訊息、註解與 docstring 維持中文** |
> | **R2 顆數（2026-09-02 實查）** | 實查基線 **624**（不是本檔原寫的 632）；Phase 83 收工 **640**、84 ＋0 ＝ 640，所以本 phase **開工基線 640、收工 640**。全檔（§2／§3／§4／§6／§8）的 632 一律改 640 |
> | **R3 AWS 操作歸 controller** | §4.1〜§4.5、§4.7、§4.8 與 §6 裡所有會打 `aws`／真連 AWS 的步驟，逐段標「⚠ 本步驟由 controller 親自執行；實作 subagent 不打 aws」。實作 subagent 在本 phase **只做 §4.6 一件事**（純改 `scripts/aws_check.py`，零 `aws` 指令、零真連線） |
> | **R4 `aws_check.py` 無自動化測試** | 它會真的打 AWS，所以**不寫 pytest**（安全網第五道：pytest 絕不連真 AWS）。驗收＝controller 真跑一次印 OK，本 phase 仍然 **+0 顆** |
> | **只換一支函式**（calib-brief 各人專屬 C） | §4.6 不再「整份覆蓋 `aws_check.py`」——Phase 84 建的那一份是基準，本 phase 只做四件小事：補一行 import、補一個常數、補一支 helper、**把 `check_sqs()` 整支換掉**。`check_s3()`／`main()` 等其餘部分一個字都不動 |
> | **CLI 不帶 `--profile`** | 本檔實查 **0 處** `--profile`（本來就沒有），維持原狀即可。理由：`~/.aws` 只有 `[default]`，而它就是 `personaldocai-admin`（brief §3 實查）。⚠ `docs/plan/aws/2026-09-02-SQS佇列新手步驟.md` 裡的 `--profile personaldocai-admin` 是**對不上的**，以本檔為準 |
> | **`create-policy-version` 修正** | §4.7 的框與 §7 陷阱 2 原本直接 `--policy-document file://deploy/aws/mac-policy.json`——那一份帶 `<ACCOUNT_ID>` 佔位，直接上傳會 `MalformedPolicyDocument`。改成比照 Phase 82 §4.6.2 先 `sed` 產生暫時檔。另註記：2026-09-02 controller 實查，AWS 上掛在 `personaldocai-mac` 的 policy **已經是**含工人端動作的新版（七條 Sid、帳號 ID 是真值），所以那一段是「萬一」的退路，不是預期路徑 |

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的四件事：
> ① 不要建 FIFO 佇列（design6 D9 明文「FIFO 不做」——貴、慢，而本專案根本不在乎順序）；
> ② 不要設 dead-letter queue（死信佇列）——失敗的語意由 `JobStore` 的 `failed` 狀態表達，多一條佇列就多一個要清的地方；
> ③ 不要設 SSE-KMS 自管金鑰（佇列裡只有 `job_id` 這種字串，沒有任何內容需要自管金鑰；同 Phase 84 §1.2 第 10 列的理由）；
> ④ 不要順手把 `get_cloud_route()` 的 `assume` 分支補起來（那是 **Phase 86**）。

> 🎯 **一句話目標：** 在東京建兩條 SQS **Standard** 佇列——
> `personaldocai-jobs`（本機 → 工人，可見度 900 秒）與
> `personaldocai-results`（工人 → 本機，可見度 30 秒），兩條都開 **20 秒長輪詢**；
> 把兩個佇列 URL 填進 `.env`；
> 把 `scripts/aws_check.py` 的 `sqs` 子命令換成真的（各送一則 → 收回來 → 刪掉 → 印 OK）；
> 最後確認 **results 佇列是 0 則訊息**——那是 design6 §0「丙」那一段的「何時算過」。

**為什麼要做這個：**

Phase 84 已經有寄物櫃了：本機可以把圖放進 S3、工人可以自己去拿。
但**工人不知道有新東西**。

難道要工人每三秒去問一次「有沒有？有沒有？」嗎？那叫輪詢，會一直花錢也一直浪費電。
而且更糟的是 design6 §1.2 第 4 列已經明文**否決**了「本機輪詢 `HeadObject` 當完成訊號」——
因為那會在「物件出現但 JSON 還沒寫完」時誤醒，安靜地拿到半截檔案。

所以要有一個「叫醒對方」的機制。本專案用兩條 SQS 佇列，一條去、一條回：

| 佇列 | 誰放（Send） | 誰拿（Receive／Delete） | 訊息內容 |
|---|---|---|---|
| `personaldocai-jobs` | **本機**（檔案已經放進 S3 之後） | **工人** | `{"job_id": "...", "s3_key": "documents/<id>/input.jpg"}` |
| `personaldocai-results` | **工人**（`result.json` 已經寫進 S3 之後） | **本機** | `{"job_id": "..."}` |

**訊息裡永遠只有字串，沒有任何影像位元組**（design6 §0 禁止第 2 條）——
SQS 單則上限**預設 1 MiB**（2025 年中才從 256 KB 放寬），一份多頁 PDF 幾十 MB，根本塞不進去。
位元組走 S3，佇列只放「指路的紙條」。

**順序鐵律**（design6 D9）：**東西先進 S3、才發訊息。**
反過來的話，收到訊息的人會去拿一個還沒寫完的檔案——那是最難查的一種壞法。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **SQS（Simple Queue Service）** | AWS 的訊息佇列服務。一邊放紙條、另一邊拿紙條，兩邊不必同時在線上 |
| **Standard Queue（標準佇列）** | SQS 的兩種佇列之一。便宜、吞吐幾乎無上限，但**不保證順序**、而且**可能重送**同一則 |
| **FIFO Queue** | 另一種：保證順序、保證只送一次，但比較貴、吞吐低、佇列名要以 `.fifo` 結尾。design6 D9 明文「FIFO 不做」——本專案的每一筆 job 彼此獨立，順序完全不重要 |
| **at-least-once（至少送一次）** | Standard Queue 的保證：同一則訊息**可能被送兩次以上**。所以收訊息的人必須**冪等**——做兩次跟做一次結果一樣（design6 D17；工人靠「`result.json` 已存在就跳過」、本機靠 `photo_ids`） |
| **queue URL** | 佇列的網址，長得像 `https://sqs.ap-northeast-1.amazonaws.com/<ACCOUNT_ID>/personaldocai-jobs`。**程式呼叫 API 時用的是它**（不是名字）。它含有你的帳號 ID，所以放 `.env`、不寫進文件 |
| **queue ARN** | 佇列的資源身分證：`arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-jobs`。**IAM policy 裡用的是它**（Phase 82 的 `mac-policy.json` 就是寫 ARN） |
| **visibility timeout（可見度逾時）** | 一則訊息被某人拿走之後，它會「隱形」這麼多秒，別人看不到。這段時間內拿走的人要嘛做完把它刪掉、要嘛時間到它就**重新出現**給別人做。這就是「工人做到一半掛掉，工作不會消失」的機制 |
| **為什麼 jobs 設 900 秒** | 工人拿到一份多頁 PDF，要一頁一頁送 Ollama Cloud 看圖，可能花好幾分鐘。可見度太短的話，它還在做、訊息就重新出現了 → 另一個工人（或它自己下一輪）會**再做一次**。900 秒 ＝ 15 分鐘，留足餘裕 |
| **為什麼 results 設 30 秒** | 本機收到結果之後只做「GetObject ＋ 刪訊息」，幾毫秒的事。而且 results 是**共用**佇列——你常常會收到別人的訊息，這時要**立刻還回去**（可見度改 0）。設短一點，萬一沒還成功，別人也只要等 30 秒 |
| **long polling（長輪詢）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 N 秒」。**上限 20 秒**（AWS 硬規定）。好處是**少打很多次 API**（＝省錢），也不會漏收；`ReceiveMessageWaitTimeSeconds=20` 就是把它設成佇列的預設值 |
| **short polling（短輪詢）** | `WaitTimeSeconds=0` 的行為：立刻回答，而且**只問一部分伺服器**——所以明明有訊息卻回空的情況是**正常的**。本專案一律用長輪詢 |
| **MessageRetentionPeriod（保留期）** | 沒有人來拿的訊息最多留多久，超過就自動丟掉。範圍 60 秒〜14 天，**預設 4 天**（345600 秒）。本專案明寫 4 天 |
| **receipt handle（收據把手）** | 拿走一則訊息時 SQS 給你的**臨時**字串。刪掉它、或提早讓它重新出現，都得用它。它**不是** message id，而且**每次拿都不一樣** |
| **`ApproximateNumberOfMessages`** | 「佇列裡大概有幾則」。名字裡的 Approximate 是認真的：SQS 是分散式的，這個數字**會有延遲**（送出或刪除之後，可能要等幾十秒才反映） |
| **purge（清空佇列）** | 把一條佇列裡的訊息全部倒掉（`aws sqs purge-queue`）。⚠ **60 秒內只能做一次**，而且刪除過程本身要花最多 60 秒 |
| **dead-letter queue（死信佇列）** | 「重試很多次都失敗的訊息，丟到另一條佇列去」。本專案**不做**：失敗的語意由 `JobStore` 的 `failed` 狀態表達（使用者在進度面板上看得到、可以按 × 關掉），多一條佇列就多一個沒有人會去看、卻要記得清的地方 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D9**（完成訊號＝results 佇列，方案 B） | **兩條 Standard Queue，FIFO 不做**；jobs 本機 Send／工人 Receive；results 工人 Send／本機 Receive；**PutObject 成功後才 Send**；禁止本機輪詢 `HeadObject` | §4.2／§4.3 建兩條 Standard；§3「明確不做」列出 FIFO 與 S3 Event |
| **§2.3 SQS 佇列（契約）** | 兩條佇列的 body 內容；`WaitTimeSeconds` 最多 20 秒；整筆 job 另有逾時 | `ReceiveMessageWaitTimeSeconds=20`；逾時在 `CLOUD_RESULT_TIMEOUT_SECONDS`（Phase 86 才會用到） |
| **§0 禁止第 2 條** | 把影像位元組塞進 SQS ＝ 禁止 | `aws_check.py` 送的兩則訊息都只有字串；Phase 83 已有兩顆單元測試釘住 body 形狀 |
| **D17**（at-least-once → 必須冪等） | 工人與本機收結果都要冪等 | 本 phase 只建佇列；冪等的實作在 Phase 80（本機）與 87（工人） |
| **§0「丙」那一列的「何時算過」** | jobs body 無檔案位元組、只含 `job_id` 與 `s3_key`；**results 佇列已存在、尚無訊息** | §4.8 專門驗這一條 |
| **§1.2 第 4 列**（被否決） | 本機輪詢 `HeadObject` 當完成訊號 | §3「明確不做」表 |
| **總覽 §2.8** | `personaldocai-jobs`：Standard、`VisibilityTimeout=900`、`MessageRetentionPeriod` 4 天、`ReceiveMessageWaitTimeSeconds=20`；`personaldocai-results`：`VisibilityTimeout=30`、其餘相同 | §4.2／§4.3 逐字照做 |
| **總覽 §2.7 Phase 85** | 動到 `scripts/aws_check.py`（加 `sqs` 子命令）、`.env`；**無新 pytest** | §3「做」清單 |
| **總覽 §10.1 追認項 d** | results 佇列是**共用**的，收到別人的 `job_id` 要還回去或當殘訊息刪掉 | §4.2 解釋為什麼 results 的可見度只設 30 秒 |

---

## 2. 前置條件

### 2.1 前面的 phase

- **★G1 已由產品負責人明示通過。**
- **Phase 82 完成**（AWS 帳號、CLI、兩個 IAM 身分）。
- **Phase 83 完成**（`app/services/aws_mailbox.py`、`boto3` 已裝）。
- **Phase 84 完成**：bucket 已建好、`.env` 的 `S3_BUCKET` 有值、
  `python scripts/aws_check.py s3` 印得出 OK。

### 2.2 開工基線（實查）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

pytest -q
# 預期尾巴：640 passed，0 skipped。
# （2026-09-02 實查：本輪開工當下的工作樹是 624；Phase 83 ＋16 ＝ 640，Phase 84 ＋0，
#   所以本 phase 的開工基線是 640。總覽 §2.7／§9 寫的 632 是這次實查之前的舊數字。）
```

> ⚠ 下面這一段會真的連 AWS：**由 controller 親自執行；實作 subagent 不打 aws。**

```bash
# Phase 84 的成果還在
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws s3api get-bucket-location --bucket "$S3_BUCKET"   # 預期：ap-northeast-1
python scripts/aws_check.py s3                        # 預期最後一行：✅ S3 OK：…

# 我是誰（要是 admin：建佇列需要 sqs:CreateQueue，最小權限那把沒有）
aws sts get-caller-identity --query Arn --output text  # 預期結尾：:user/personaldocai-admin
```

### 2.3 本 phase 對顆數的影響

**+0 顆**（總覽 §2.7；累計顆數以 2026-09-02 實查為準 ＝ **640**，總覽寫的 632 是舊數字）。
理由與 Phase 84 相同：「AWS 上有沒有兩條設定對的佇列」pytest 測不到，
而且 **pytest 絕不准連真 AWS**（第五道安全網 `wire_fake_cloud`）。
驗收改用 **AWS CLI 的輸出** ＋ **`python scripts/aws_check.py s3 sqs` 印 OK**（裁決 R4）。

> ⚠ `scripts/aws_check.py` 本身**不寫自動化測試**——它的每一行都在真的打 AWS，
> 寫成 pytest 就等於把第五道安全網拆掉。它由 controller 手動跑一次當驗收。

### 2.4 每次開工都要先做的 shell 準備

> ⚠ **本節與 §4 的所有 `aws` 指令由 controller 親自執行；實作 subagent 不打 aws。**

**最單純的做法：不要 source `.env`，直接打 `aws`。**
這台 Mac 的 `~/.aws` 只有一組 `[default]`，而它就是 `personaldocai-admin`
（2026-09-02 實查），所以**所有指令都不必、也不要帶 `--profile`**：

```bash
cd /Users/linjunting/personalDocAI
aws sts get-caller-identity --query Arn --output text   # 結尾要是 :user/personaldocai-admin
```

**只有在需要 `.env` 裡的變數時**（例如 `$S3_BUCKET`）才 source，而且**載完立刻**
把那兩把 key 丟掉：

```bash
set -a; . ./.env; set +a                          # ① 載入 $S3_BUCKET 等變數
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # ② ★ 讓 aws 指令回去用 default（＝admin）
aws sts get-caller-identity --query Arn --output text   # ③ 結尾要是 :user/personaldocai-admin
```

> ⚠ 少了第 ② 步，下面每一條 `aws sqs create-queue` 都會 `AccessDenied`——
> `.env` 裡那把是**程式用的最小權限 key**（`personaldocai-mac`，它只能 Send／Receive／
> 改可見度，不能建佇列），而環境變數的優先序**高於** `~/.aws` 的 profile。
> 詳見 Phase 82 §7 陷阱 1 與 `CLAUDE.md` 指令區的「── AWS」小段。

> ⚠ `docs/plan/aws/2026-09-02-SQS佇列新手步驟.md`（產品負責人在 Phase 82 寫的新手文）
> 每一條指令都帶 `--profile personaldocai-admin`——**那個 profile 名字在這台機器上不存在**，
> 照抄會回 `The config profile (personaldocai-admin) could not be found`。
> 兩邊衝突時**以本檔為準**（不帶 profile）。

> ⚠️ **絕對不要同時跑兩份 pytest。**（理由同前面各 phase。）

---

## 3. 範圍

### 做

1. 建 `personaldocai-jobs`：Standard、`VisibilityTimeout=900`、
   `ReceiveMessageWaitTimeSeconds=20`、`MessageRetentionPeriod=345600`（4 天）。
2. 建 `personaldocai-results`：同上，但 `VisibilityTimeout=30`。
3. 用 `get-queue-url` 取回兩條的 URL、用 `get-queue-attributes --attribute-names All` 驗屬性。
4. `.env` 填 `SQS_JOBS_QUEUE_URL` 與 `SQS_RESULTS_QUEUE_URL`，restart worker。
5. 把 `scripts/aws_check.py` 的 `sqs` 子命令換成真的：
   兩條佇列各做一次 **send → receive（確認是自己那則）→ delete**。
   用 `.env` 的 mac key 跑（總覽 §10.2 N：`personaldocai-mac-policy` 兩條佇列的收發都有）。
6. **確認 results 佇列回到 0 則訊息**（design6 §0「丙」那一段的「何時算過」）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 建 FIFO 佇列（`.fifo` 結尾） | design6 D9 明文「FIFO 不做」。它比較貴、吞吐低，而本專案的每一筆 job 彼此獨立，**順序完全不重要**；重送的問題已經用冪等解決（D17） |
| 設 dead-letter queue | 失敗的語意由 `JobStore` 的 `failed` 狀態表達（使用者在進度面板看得到、可以按 ×）。多一條佇列就多一個沒有人會去看、卻要記得清的地方 |
| 設 SSE-KMS 自管金鑰 | 佇列裡只有 `job_id`／`s3_key` 這種字串，沒有任何內容需要自管金鑰；而 KMS 要月費（同 design6 §1.2 第 10 列的理由） |
| 設 `DelaySeconds`（延遲投遞） | 我們要的是「越快越好」。延遲只會讓每一筆多等 N 秒 |
| 開 S3 Event Notification 直接餵進 jobs 佇列 | design6 §1.2 第 4 列與 D9 已明確選了「**工人自己**在 `result.json` 寫完之後發 results 訊息」。S3 Event 會在「物件出現但 JSON 還沒寫完」時誤醒 |
| 把佇列 URL 寫進任何 `docs/`／`README.md`／`deploy/` | URL 含帳號 ID。總覽 §7 鐵律 10：只寫變數名 `$SQS_JOBS_QUEUE_URL` |
| 幫佇列加 queue policy（誰可以送／收） | IAM user 與（Phase 91 的）instance role 的 policy 已經夠了。多一份 policy 就多一個「兩份規則互相打架」的來源 |
| 建第三條佇列（例如「通知佇列」） | 兩條就是全部（design6 §2.3 的表） |
| 改任何 `app/` 底下的程式碼 | 本 phase 零產品碼變更（`scripts/` 不進映像，不算產品碼） |
| 改 `compose.yaml` | 本增量零改動。兩個 URL 走 `.env`（已 bind-mount） |
| 新增 pytest | 顆數維持 **640**（裁決 R4：`aws_check.py` 打真 AWS，不寫自動化測試） |

---

## 4. 實作步驟

> 🧰 **人工＋CLI 型**：每一步都是「指令 → 逐個旗標解釋 → 預期輸出 → 做錯了怎麼退回 → 費用影響」。
> 全部指令在專案根目錄執行，而且**先做完 §2.4 的 shell 準備**。

> ⚠ **誰做哪一步**（裁決 R3）：
> **§4.6 是實作 subagent 的工作**（純改 `scripts/aws_check.py`，零 `aws` 指令、零真連線）；
> **§4.1〜§4.5、§4.7、§4.8 由 controller 親自執行**（建資源、改 `.env`、restart 容器、
> 真跑腳本、purge 佇列——全都有外部副作用）。§4.9 的格式與回歸兩位都可以跑。

### 4.1 建 `personaldocai-jobs`（本機 → 工人）

> ⚠ 本步驟由 controller 親自執行；實作 subagent 不打 aws。

- [x] 執行：

```bash
aws sqs create-queue \
  --queue-name personaldocai-jobs \
  --region ap-northeast-1 \
  --attributes VisibilityTimeout=900,ReceiveMessageWaitTimeSeconds=20,MessageRetentionPeriod=345600
```

**每個旗標／屬性在做什麼：**

| 旗標／屬性 | 值 | 用途 |
|---|---|---|
| `--queue-name` | `personaldocai-jobs` | 佇列名字（同一個帳號＋同一區內唯一，**不必**全球唯一——這一點跟 S3 bucket 不一樣） |
| `--region` | `ap-northeast-1` | 建在東京。SQS 沒有 S3 那種 `LocationConstraint` 的坑，`--region` 就決定一切 |
| `VisibilityTimeout` | **900**（秒＝15 分鐘） | 工人拿走一則之後隱形多久。工人看一份多頁 PDF 可能要好幾分鐘，設太短的話它還在做、訊息就重新出現 → **同一份 PDF 被做兩次** |
| `ReceiveMessageWaitTimeSeconds` | **20** | 佇列預設的長輪詢秒數（AWS 上限就是 20）。工人的主迴圈每次 `receive_job(20)`，沒東西就安靜地等 20 秒，而不是狂打 API |
| `MessageRetentionPeriod` | **345600**（秒＝4 天） | 沒人來拿的訊息最多留 4 天。這也是 AWS 的預設值，這裡**明寫出來**是為了讓「4 天」這件事在指令裡看得見（例如你 Stop 了 EC2 一整個週末，回來時那些訊息還在——但超過 4 天就沒了） |

**預期輸出**（`<ACCOUNT_ID>` 是你的 12 位數字；**不要**把真值貼進任何文件）：

```json
{
    "QueueUrl": "https://sqs.ap-northeast-1.amazonaws.com/<ACCOUNT_ID>/personaldocai-jobs"
}
```

**做錯了怎麼退回：**

| 錯誤訊息 | 意思 | 怎麼修 |
|---|---|---|
| `AccessDenied ... sqs:CreateQueue` | shell 裡有 `.env` 的最小權限 key | 回 §2.4 跑 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` |
| `QueueNameExists`（CLI 也可能顯示舊名 `QueueAlreadyExists`） | 這個名字已經存在，**而且屬性跟你這次給的不一樣**（屬性完全相同時 `create-queue` 是冪等的，會直接回同一個 `QueueUrl`） | 用 §4.4 的 `set-queue-attributes` 改屬性，或先 `delete-queue` 再建（見下面的警告） |
| 指令成功但沒印任何東西 | 不會發生——`create-queue` 一定會回 `QueueUrl` | — |
| 名字打錯了 | — | `aws sqs delete-queue --queue-url <打錯的那條的 URL> --region ap-northeast-1`，再建一次 |

> ⚠️ **刪掉佇列之後，同名的佇列要等 60 秒才建得回來。**
> AWS 的規定：`delete-queue` 之後 60 秒內不可以用同一個名字 `create-queue`
> （會回 `AWS.SimpleQueueService.QueueDeletedRecently`）。手滑刪掉的話，泡杯茶再回來。

**費用影響：** 佇列本身 **$0**（不佔空間就不收費）。SQS 按**請求次數**計費，
而且**每個月前 100 萬次請求免費**。本專案一天最多幾百次請求 → 實質 **$0**。

---

### 4.2 建 `personaldocai-results`（工人 → 本機）

> ⚠ 本步驟由 controller 親自執行；實作 subagent 不打 aws。

- [x] 執行（**只有 `VisibilityTimeout` 不一樣**）：

```bash
aws sqs create-queue \
  --queue-name personaldocai-results \
  --region ap-northeast-1 \
  --attributes VisibilityTimeout=30,ReceiveMessageWaitTimeSeconds=20,MessageRetentionPeriod=345600
```

```text
┌─ 為什麼 results 的可見度是 30 秒，而不是跟 jobs 一樣 900 ─────────────────────┐
│                                                                              │
│ 因為 results 是一條**共用**佇列（總覽 §10.1 追認項 d）：                       │
│ 兩筆 job 同時在等結果的時候，你**一定**會收到別人那則。                        │
│                                                                              │
│   本機 A 在等 job-1 ──┐                                                       │
│                       ├─▶ [results 佇列] ◀── 工人放進來的 job-1 與 job-2      │
│   本機 B 在等 job-2 ──┘                                                       │
│                                                                              │
│ 本機 A 收到 job-2 的訊息時要做的事是「**立刻還回去**」                         │
│ （ChangeMessageVisibility 改成 0，Phase 80 的 wait_result 規則第 3 條）。      │
│                                                                              │
│ 但萬一「還回去」那一步也失敗了呢？那則訊息就會隱形一段時間——                  │
│ 隱形多久，就是 B 白白多等多久。                                               │
│   ・設 900 秒 → B 等 15 分鐘，早就逾時 fallback 了（雲端白算一場）             │
│   ・設 30 秒  → B 最多多等 30 秒，還在 CLOUD_RESULT_TIMEOUT_SECONDS 的預算內   │
│                                                                              │
│ 而本機收到**自己**那則之後只做「GetObject ＋ 刪訊息」，幾毫秒的事，            │
│ 30 秒綽綽有餘。                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

**預期輸出：**

```json
{
    "QueueUrl": "https://sqs.ap-northeast-1.amazonaws.com/<ACCOUNT_ID>/personaldocai-results"
}
```

**做錯了怎麼退回：** 同 §4.1。

**費用影響：** 同 §4.1（實質 $0）。

---

### 4.3 取回兩條的 URL

> ⚠ 本步驟由 controller 親自執行；實作 subagent 不打 aws。
> `$JOBS_URL`／`$RESULTS_URL` 這兩個 shell 變數 §4.4／§4.8／§6 都會用到，
> **同一個終端機視窗裡做完**比較省事（換視窗就要重跑這一步）。

- [x] 執行：

```bash
JOBS_URL=$(aws sqs get-queue-url --queue-name personaldocai-jobs \
  --region ap-northeast-1 --query QueueUrl --output text)
RESULTS_URL=$(aws sqs get-queue-url --queue-name personaldocai-results \
  --region ap-northeast-1 --query QueueUrl --output text)

# 只印出「有沒有拿到」與結尾的佇列名，不印完整 URL（它含帳號 ID）
echo "jobs    → ...${JOBS_URL##*/}"
echo "results → ...${RESULTS_URL##*/}"
```

- `--query QueueUrl --output text`：只把那一個欄位印出來、不要引號與大括號
  （這樣才好塞進 shell 變數）。
- `${JOBS_URL##*/}`：shell 的「砍掉最後一個 `/` 之前的所有東西」——只留佇列名。

**預期輸出：**

```text
jobs    → ...personaldocai-jobs
results → ...personaldocai-results
```

**做錯了怎麼退回：** `AWS.SimpleQueueService.NonExistentQueue` ＝ 名字打錯或建在別區。
用 `aws sqs list-queues --region ap-northeast-1 --query 'QueueUrls[]' --output text`
看看東京到底有哪些佇列。

**費用影響：** 唯讀請求，實質 $0。

---

### 4.4 用 `get-queue-attributes` 驗屬性

> ⚠ 本步驟由 controller 親自執行；實作 subagent 不打 aws。

- [x] **jobs**：

```bash
aws sqs get-queue-attributes --queue-url "$JOBS_URL" \
  --attribute-names All --region ap-northeast-1
```

**預期輸出**（欄位順序可能不同；`VisibilityTimeout`／`ReceiveMessageWaitTimeSeconds`／`MessageRetentionPeriod`
三個是本 phase 設的，其餘是 AWS 給的預設）：

```json
{
    "Attributes": {
        "QueueArn": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:personaldocai-jobs",
        "ApproximateNumberOfMessages": "0",
        "ApproximateNumberOfMessagesNotVisible": "0",
        "ApproximateNumberOfMessagesDelayed": "0",
        "CreatedTimestamp": "1788...",
        "LastModifiedTimestamp": "1788...",
        "VisibilityTimeout": "900",
        "MaximumMessageSize": "1048576",
        "MessageRetentionPeriod": "345600",
        "DelaySeconds": "0",
        "ReceiveMessageWaitTimeSeconds": "20",
        "SqsManagedSseEnabled": "true"
    }
}
```

**要對的四個數字：**

| 欄位 | 預期值 | 怎麼讀 |
|---|---|---|
| `VisibilityTimeout` | `"900"` | 拿走之後隱形 15 分鐘 |
| `ReceiveMessageWaitTimeSeconds` | `"20"` | 長輪詢 20 秒（上限） |
| `MessageRetentionPeriod` | `"345600"` | 4 天 |
| `MaximumMessageSize` | `"1048576"` | 1 MiB。2025 年中 AWS 把上限從 256 KB 放寬到 1 MiB，**新建佇列的預設就是它**（舊文件與 design6 §1.2 寫的 256 KB 是放寬前的數字；看到 `"262144"` 也不算錯，那是舊佇列）。不管哪一個，一份多頁 PDF 幾十 MB 一樣塞不進去——**這就是「影像位元組不准進 SQS」的物理原因**（design6 §0 禁止第 2 條） |

> 📌 `ApproximateNumberOfMessages` 名字裡的 **Approximate 是認真的**：
> SQS 是分散式的，送出或刪掉訊息之後，這個數字可能要等幾十秒才反映。
> 剛做完動作就看它、發現數字不對，**先等一分鐘再看一次**再說。

- [x] **results**（`VisibilityTimeout` 應該是 `"30"`）：

```bash
aws sqs get-queue-attributes --queue-url "$RESULTS_URL" \
  --attribute-names VisibilityTimeout ReceiveMessageWaitTimeSeconds MessageRetentionPeriod \
                    ApproximateNumberOfMessages \
  --region ap-northeast-1
```

**預期輸出：**

```json
{
    "Attributes": {
        "VisibilityTimeout": "30",
        "ReceiveMessageWaitTimeSeconds": "20",
        "MessageRetentionPeriod": "345600",
        "ApproximateNumberOfMessages": "0"
    }
}
```

**做錯了怎麼退回：** 屬性設錯（例如 `VisibilityTimeout` 打成 90 而不是 900），
**不必**刪掉重建，直接改：

```bash
aws sqs set-queue-attributes --queue-url "$JOBS_URL" \
  --attributes VisibilityTimeout=900 --region ap-northeast-1
```

（`set-queue-attributes` 是「只改你列出來的那幾項」，不是整份覆蓋——這一點跟 S3 的
`put-bucket-*` 相反，別搞混。）

**費用影響：** 唯讀請求，實質 $0。

---

### 4.5 `.env` 填兩個 URL，並讓容器重讀

> ⚠ 本步驟由 controller 親自執行（改 `.env` ＋ restart 容器都有外部副作用）；
> 實作 subagent 不碰 `.env`。

- [x] 打開 `/Users/linjunting/personalDocAI/.env`，**新增**這兩行
      （2026-09-02 實查：`.env` 裡目前**沒有**這兩個變數名，Phase 82 沒有預留空行；
      Phase 84 之後若已有留空的那兩行就直接填值。
      值就是 §4.3 印出來的完整 URL；**等號兩邊不可以有空白**）：

```ini
SQS_JOBS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/你的帳號ID/personaldocai-jobs
SQS_RESULTS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/你的帳號ID/personaldocai-results
```

- [x] 讓容器重新讀：

```bash
cd /Users/linjunting/personalDocAI
docker compose -f compose.yaml -f compose.dev.yaml restart app worker
docker compose -f compose.yaml -f compose.dev.yaml exec worker python -c \
  "from app.core import config; print('兩條 URL 都有值 =', bool(config.SQS_JOBS_QUEUE_URL) and bool(config.SQS_RESULTS_QUEUE_URL))"
```

> 📌 兩個 `-f` 不能省：2026-09-02 的工作樹跑的是**開發疊加**（`compose.dev.yaml`，app 帶
> `--reload`、bind-mount `./app`）。少寫 `-f compose.dev.yaml` 會被當成「切回常駐模式」。
> ⚠ `worker` **沒有** `--reload`（Celery 沒這種東西），所以改 `.env` 一定要 restart 它，
> 不然 HTTP 那邊已經是新設定、背景分析卻還是舊的，而且完全不報錯。

**預期輸出：**

```text
兩條 URL 都有值 = True
```

**做錯了怎麼退回：** 印出 `False` → ① 存檔了嗎 ② restart 了嗎
③ 等號兩邊有沒有多空白 ④ `ls -la .env` 確認它是檔案而不是資料夾。

**費用影響：** $0。

---

### 4.6 把 `scripts/aws_check.py` 的 `sqs` 子命令換成真的

> ✍ **這一步是實作 subagent 的工作**：純改一個檔，**零 `aws` 指令、零真連線**。
> 改完只跑 §4.9 的 `ruff` 與 `pytest`；真的執行這支腳本（會打 AWS）是 §4.7，由 controller 做。

**基準 ＝ Phase 84 建好的那一份 `scripts/aws_check.py`。不要整檔覆蓋、不要重貼整份。**
本 phase 只做四件小事，其餘（`check_s3()`／`main()`／`CHECK_JOB_ID`／`sys.path` 那一段／
建信箱與金鑰來源那兩支 helper）**一個字都不動**：

| # | 改什麼 | 位置 |
|---|---|---|
| ① | 檔頭 docstring：用法那一行拿掉「Phase 85 才有」的註記，並在最後補一段「sqs 子命令用哪一把 key」 | docstring |
| ② | 多 import 一個 `MailboxMessage`（只當型別註記用） | import 區 |
| ③ | 新增常數 `RECEIVE_RETRIES` | `CHECK_JOB_ID` 下面 |
| ④ | 新增 helper `receive_own_message()`，並**把 `check_sqs()` 整支換掉**（Phase 84 那一支只是「Phase 85 才有」的佔位，直接 `raise SystemExit`） | `check_s3()` 與 `main()` 之間 |

> ⚠ **名字對齊**（brief §5 的跨檔命名契約）：本 phase 新增的識別字一律英文——
> `check_sqs`／`receive_own_message`／`RECEIVE_RETRIES`／參數 `receive`、`queue_name`／
> 區域變數 `mailbox`、`message`；常數 `CHECK_JOB_ID`（值 `"aws-check"`）沿用 Phase 84 的。
> 下面 ④ 呼叫的 `build_mailbox()` 是 **Phase 84 建的那支「照 `.env` 建 `AwsMailbox`」helper**
> （Phase 84 計畫檔的初稿用中文名，校準後是英文名）——**動手前先打開 `scripts/aws_check.py`
> 看它實際叫什麼，照實檔的名字改這一個呼叫**，不要另外再寫一支一模一樣的。
> `test_中文` 測試名、log 字樣、錯誤訊息、註解與 docstring 維持中文。

- [x] **①** docstring：把「用法」那三行換成下面這樣
      （唯一的差別是中間那行拿掉 Phase 84 留的尾註 `# Phase 85 建好兩條佇列之後才有`）：

```text
    python scripts/aws_check.py s3
    python scripts/aws_check.py sqs
    python scripts/aws_check.py s3 sqs     # 兩個都跑
```

  並在 `分層：…` 那一行**之前**插入這一段：

```text
★ sqs 子命令用 .env 那把 mac key 跑就可以（總覽 §10.2 N：personaldocai-mac 的 policy
  兩條佇列的「送／收／刪」都有，因為 Phase 88／90 在 Mac 上跑工人用的就是這把 key）。
  它仍然**沒有** PurgeQueue——清佇列是人做的事，用 aws CLI 以 admin 身分做（Phase 85 §4.8）。
```

- [x] **②** 在 import 區的 `from app.services.aws_mailbox import AwsMailbox` **下面**加一行
      （isort 的順序剛好就是這樣，不會被 `ruff check` 挑）：

```python
from app.services.cloud_ingest import MailboxMessage  # noqa: E402
```

- [x] **③** 在 `CHECK_JOB_ID = "aws-check"` 底下加一個常數：

```python
# 收訊息時最多重試幾次（每次長輪詢 20 秒）。
# 為什麼需要重試：SQS Standard 是分散式的，剛送出的訊息偶爾要多問一次才拿得到。
# 長輪詢本身已經會問過所有伺服器，所以三次幾乎一定夠。
RECEIVE_RETRIES = 3
```

- [x] **④** 在 `check_s3()` 與 `main()` 之間，加一支 helper、
      並把 `check_sqs()` **整支**換成下面這一份：

```python
def receive_own_message(receive, queue_name: str) -> MailboxMessage:
    """長輪詢最多幾次，直到收到 job_id 等於 CHECK_JOB_ID 的那一則。

    receive ＝ 信箱的收信方法（mailbox.receive_job 或 mailbox.receive_result），
    它吃「最多等幾秒」、回一則 MailboxMessage 或 None。

    收到**別人**的訊息時直接停手並提示：那代表佇列裡有殘留（多半是上一次煙霧沒清乾淨），
    先清乾淨再測，不然這支腳本會把別人的訊息刪掉。
    ⚠ 被我們拿過一次的那則會隱形一段時間（jobs 900 秒、results 30 秒）才重新出現；
      purge-queue 會連隱形中的一起清掉，所以「先 purge 再測」永遠是安全的修法。
    """
    for _ in range(RECEIVE_RETRIES):
        message = receive(20)
        if message is None:
            continue
        if message.job_id != CHECK_JOB_ID:
            raise SystemExit(
                f"⛔ {queue_name} 佇列裡有別人的訊息（job_id={message.job_id}）。"
                " 先用 aws sqs purge-queue 清乾淨再測。"
            )
        return message
    raise SystemExit(f"⛔ {queue_name} 佇列送出去之後收不回來（等了 {RECEIVE_RETRIES * 20} 秒）")


def check_sqs() -> None:
    """兩條佇列各做一次來回：send → receive（確認是自己那則）→ delete。

    ⚠ 它會**真的**在佇列裡放訊息。做完之後兩條佇列都必須回到 0 則
    （§4.8 的驗收就是在確認這件事）——殘留的訊息會在 Phase 86 的煙霧裡變成雜訊。
    ⚠ 用 .env 的 mac key 跑就可以（見檔頭）。① 的 ReceiveMessage 回 AccessDenied ＝
      掛在 personaldocai-mac 上的 policy 還是舊版（沒有工人端動作），見 Phase 85 §4.7 的框。
    """
    if not config.SQS_JOBS_QUEUE_URL or not config.SQS_RESULTS_QUEUE_URL:
        raise SystemExit("⛔ .env 的兩個 SQS_*_QUEUE_URL 是空的——先做完 Phase 85 §4.5")
    mailbox = build_mailbox()

    print("① jobs 佇列：SendMessage（本機 → 工人的那條）")
    mailbox.send_job(CHECK_JOB_ID, mailbox.input_key(CHECK_JOB_ID, "image/png"))
    message = receive_own_message(mailbox.receive_job, "jobs")
    print(f"   ReceiveMessage 收到：job_id={message.job_id} s3_key={message.s3_key}")
    mailbox.delete_job_message(message.receipt_handle)
    print("   DeleteMessage 完成")

    print("② results 佇列：SendMessage（工人 → 本機的那條）")
    mailbox.send_result(CHECK_JOB_ID)
    message = receive_own_message(mailbox.receive_result, "results")
    print(f"   ReceiveMessage 收到：job_id={message.job_id}")
    mailbox.delete_result_message(message.receipt_handle)
    print("   DeleteMessage 完成")

    print("✅ SQS OK：兩條佇列都能 send → receive → delete")
```

- [x] **⑤ 這些地方一個字都不要動**（改到就是做錯）：
  `main()`（Phase 84 已經有 `sqs` 分支指向 `check_sqs()`，換掉函式本體就自動接上了）、
  `check_s3()`、金鑰來源與建信箱那兩支 helper、`CHECK_JOB_ID` 的值、
  `sys.path.insert(...)` 那一段與它上面的註解。

> 📌 ② 多 import 了一個 `MailboxMessage`（只當型別註記用）。
> 它定義在 `app/services/cloud_ingest.py`（Phase 77 建的），所以直接從那裡 import——
> `aws_mailbox.py` 只是把它 import 進來用，不是那個名字的家（總覽 §2.4.1 的契約），
> 全站一律從 `cloud_ingest` 拿，不要繞道。

---

### 4.7 跑它

> ⚠ 本步驟由 controller 親自執行（它會真的連 AWS）；實作 subagent 不跑這支腳本。

- [x] 執行（⚠ 會真的打 AWS，用的是 `.env` 裡那把**最小權限**的 key——這正是要驗的那把）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY    # 確保驗到的是 .env 那一把
python scripts/aws_check.py s3 sqs
```

- `unset` 只清掉 shell 的環境變數（讓後面的 `aws` 指令用 admin）；Python 這邊 `config` 一被 import
  就 `load_dotenv()`，把 `.env` 的 mac key **補回來**。所以腳本用的是 mac key，第一行會印出來。

**預期輸出：**

```text
金鑰來源 = .env 那把（personaldocai-mac，最小權限）
bucket = personaldocai-mailbox-XXXXXX   region = ap-northeast-1
① PutObject      documents/aws-check/input.png
② GetObject      documents/aws-check/input.png
③ DeleteObjects  documents/aws-check/input.png
④ 再 GetObject 一次，確認真的不在了
✅ S3 OK：put → get → 內容一致 → delete → 確認不在了
① jobs 佇列：SendMessage（本機 → 工人的那條）
   ReceiveMessage 收到：job_id=aws-check s3_key=documents/aws-check/input.png
   DeleteMessage 完成
② results 佇列：SendMessage（工人 → 本機的那條）
   ReceiveMessage 收到：job_id=aws-check
   DeleteMessage 完成
✅ SQS OK：兩條佇列都能 send → receive → delete
```

**做錯了怎麼退回：**

| 訊息 | 意思 | 怎麼修 |
|---|---|---|
| `⛔ .env 的兩個 SQS_*_QUEUE_URL 是空的` | §4.5 沒做或沒存檔 | 回 §4.5 |
| 第一行印 `金鑰來源 = 沒有任何 key（…）` | `.env` 的 `AWS_ACCESS_KEY_ID` 沒填，boto3 **安靜地**退到 `~/.aws` 的 admin——後面全部 OK 也不代表程式那把 key 能用 | 回 Phase 82 §4.8 填 `.env` |
| 第一行印 `金鑰來源 = 不是 .env 那把` | shell 裡有別的 key（多半是你自己 export 過的） | `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 再跑 |
| `AccessDenied ... ReceiveMessage`（發生在 ① jobs）或 `AccessDenied ... SendMessage`（發生在 ② results） | 掛在 `personaldocai-mac` 上的 policy 是**舊版**（只有 jobs Send／results Receive，沒有總覽 §10.2 N 加進去的工人端動作） | 見下面的框：更新 `mac-policy.json` 並發布成新版本 |
| `AccessDenied ... SendMessage`（發生在 ① jobs 的第一步） | policy 的佇列 ARN 與實際佇列對不上（最常見：`<ACCOUNT_ID>` 沒換掉，或名字打錯） | 回 Phase 82 §4.6.2，用 `aws iam get-policy-version` 看實際內容 |
| `AWS.SimpleQueueService.NonExistentQueue`（新版 CLI／boto3 也可能顯示 `QueueDoesNotExist`） | `.env` 的 URL 打錯（多半是帳號 ID 或名字） | 回 §4.3 重印 URL、對照 `.env` |
| `⛔ jobs 佇列送出去之後收不回來（等了 60 秒）` | 訊息真的沒進去，或 `.env` 的兩條 URL 對調了 | 用 `get-queue-attributes` 看 `ApproximateNumberOfMessages`／`…NotVisible` |
| `⛔ … 佇列裡有別人的訊息` | 上一次煙霧沒清乾淨 | `aws sqs purge-queue`（見 §4.8） |

```text
┌─ ⚠ 這一輪用的是 .env 的 mac key——而且這正是我們要的 ──────────────────────────────────────┐
│                                                                                           │
│ Phase 82 的 personaldocai-mac-policy（總覽 §10.2 N 之後的版本）給這把 key 的 SQS 權限     │
│ 是**兩邊都有**：                                                                          │
│     jobs    佇列：SendMessage ＋ ReceiveMessage / DeleteMessage / ChangeMessageVisibility │
│     results 佇列：SendMessage ＋ ReceiveMessage / DeleteMessage / ChangeMessageVisibility │
│ 為什麼工人端的動作也給它：Phase 88（Mac 直跑工人）與 Phase 90（Mac 上用容器跑工人）       │
│ 用的都是 .env 這把 key。EC2 上的工人用另一個身分（instance role，Phase 91）。             │
│ 它**沒有**的仍然是 CreateQueue / PurgeQueue / DeleteQueue——清佇列是人做的事，走 admin。   │
│                                                                                           │
│ 所以這支腳本用 mac key 就能把兩條佇列各做完「送 → 收 → 刪」，                             │
│ 驗到的正好是 worker 容器與 Mac 工人真的會走的那把 key、那些呼叫。                         │
│                                                                                           │
│ 那前面的 unset 是在做什麼？它只影響 aws CLI（讓 CLI 回去用 ~/.aws 的 admin）。            │
│ Python 這邊 config 一被 import 就 load_dotenv()，.env 的 mac key 會**馬上被補回**         │
│ 環境變數——所以腳本第一行印「金鑰來源 = .env 那把」。這不是 bug，是刻意的分工：            │
│ CLI 用 admin 建資源、清佇列；程式用 mac key 驗權限；兩者在同一個視窗裡並存。              │
│                                                                                           │
│ 📌 2026-09-02 實查：AWS 上掛在 personaldocai-mac 的 policy **已經是新版**（七條 Sid，   │
│    含 WorkerReceiveJobs／WorkerSendResults，ARN 帶真帳號 ID）。所以下面這段是「萬一」    │
│    的退路，不是預期路徑——真的撞到再做。                                                  │
│                                                                                           │
│ 如果 ① 的 ReceiveMessage 回 AccessDenied：掛在 personaldocai-mac 上的 policy 還是         │
│ 舊版（只有 jobs 的 SendMessage）。回 Phase 82 §4.6.1 確認 mac-policy.json 是含工人端      │
│ 動作的版本，然後發布成新的預設版本（IAM policy 是有版本的）。⚠ repo 裡那一份帶           │
│ <ACCOUNT_ID> 佔位，**直接上傳會 MalformedPolicyDocument**——比照 Phase 82 §4.6.2          │
│ 先 sed 出一份暫時檔（不進 repo）：                                                        │
│   ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)                 │
│   sed "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" deploy/aws/mac-policy.json \                         │
│     > /tmp/personaldocai-mac-policy.json                                                  │
│   grep -c "<ACCOUNT_ID>" /tmp/personaldocai-mac-policy.json     # 預期：0                 │
│   aws iam create-policy-version \                                                         │
│     --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/personaldocai-mac-policy" \           │
│     --policy-document file:///tmp/personaldocai-mac-policy.json --set-as-default          │
│ （一個 policy 最多留 5 個版本，滿了先 aws iam delete-policy-version 刪舊的。）            │
│ 被拒之前 ① 已經送了一則進 jobs——本來腳本會自己刪掉，現在得用 admin purge（§4.8）。        │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

**費用影響：** 這一輪大約 10 次 SQS 請求 ＋ 4 次 S3 請求。
SQS **每月前 100 萬次請求免費**，所以實質 **$0**。

---

### 4.8 ★ 確認 results 佇列是 0 則（design6 §0「丙」的「何時算過」）

> design6 §0 的表格對「丙」這一段的驗收條件寫得很明確：
> **「jobs body 無檔案位元組，只含 `job_id`、`s3_key`；results 佇列已存在、尚無訊息」。**
> 前半由 Phase 83 的兩顆單元測試釘住，後半就是這一步。

> ⚠ 本步驟由 controller 親自執行（含 `purge-queue`——那是不可逆的清空）；
> 實作 subagent 不打 aws。

- [x] 先等一下下（`ApproximateNumberOfMessages` 是**近似值**，刪掉之後要一點時間才反映）：

```bash
sleep 60
```

- [x] 兩條佇列一起看：

```bash
for URL in "$JOBS_URL" "$RESULTS_URL"; do
  echo "── ${URL##*/}"
  aws sqs get-queue-attributes --queue-url "$URL" --region ap-northeast-1 \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
done
```

**預期輸出：**

```text
── personaldocai-jobs
{
    "ApproximateNumberOfMessages": "0",
    "ApproximateNumberOfMessagesNotVisible": "0"
}
── personaldocai-results
{
    "ApproximateNumberOfMessages": "0",
    "ApproximateNumberOfMessagesNotVisible": "0"
}
```

- `ApproximateNumberOfMessages` ＝ 現在**看得到**的訊息數。
- `ApproximateNumberOfMessagesNotVisible` ＝ **正在隱形中**的訊息數
  （被誰拿走還沒刪掉、還在可見度逾時內）。**這個也要是 0**，
  不然代表有一則被拿走但沒刪掉，它會在可見度到期後重新出現。

**不是 0 怎麼辦：** 用 purge 清乾淨：

```bash
aws sqs purge-queue --queue-url "$RESULTS_URL" --region ap-northeast-1
```

- `purge-queue` ＝ 把整條佇列裡的訊息全部倒掉（**看得到的與隱形中的都算**）。
- **預期輸出：** 完全沒有輸出。

```text
┌─ ⚠ purge 的兩個 60 秒 ────────────────────────────────────────────────────────┐
│                                                                              │
│ ① **刪除過程本身要花最多 60 秒。** 官方文件：「The message deletion process   │
│    takes up to 60 seconds. We recommend waiting for 60 seconds regardless of  │
│    your queue's size.」所以 purge 完馬上去看數字，看到不是 0 是正常的。       │
│                                                                              │
│ ② **60 秒內不可以再 purge 同一條佇列。** 第二次會回                           │
│    `AWS.SimpleQueueService.PurgeQueueInProgress`（HTTP 400）。                │
│    看到這個錯誤不要重試，等滿一分鐘再說。                                     │
│                                                                              │
│ 另外：purge 之後**還是有可能收到舊訊息**——官方明說「Messages sent to the     │
│ queue before you call PurgeQueue might be received but are deleted within the │
│ next minute」。所以 purge 完請**等一分鐘**再開始下一輪煙霧。                  │
│                                                                              │
│ ⚠ `personaldocai-mac-policy` **沒有** `sqs:PurgeQueue` 權限（清佇列是人做的   │
│   事，不是程式做的）。所以 purge 一定要用 admin 的身分跑                      │
│   ——先 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`。                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**費用影響：** $0。

---

### 4.9 格式、回歸、收尾

- [x] 格式與 lint（`scripts/` 在 CI 的檢查範圍內）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
ruff format --check app tests scripts && ruff check app tests scripts
```

**預期輸出：** `All checks passed!`

- [x] 全量測試（本 phase **+0 顆**）：

```bash
pytest -q
```

**預期輸出：** `640 passed`，0 skipped。

- [x] 零外部依賴實證（三個死埠一起指）：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

**預期輸出：** `640 passed`（與上一條一模一樣）

- [x] **不 commit——記工作樹快照**（裁決 R0 ＋ 總覽 §7 鐵律 12：
      產品負責人沒指示前不 commit、不 `git mv` 計畫檔到 `finish/`）：

```bash
cd /Users/linjunting/personalDocAI
git status --short
```

**預期：** 相對於開工前的快照，只多出 `M scripts/aws_check.py` 一列
（`.env` 不入版控，佇列 URL 不會進 repo；`docs/plan/unfinish/` 的計畫檔不搬家）。

> 📌 開工前先留一份快照才比得出來：`git status --short > /tmp/p85-before.txt`，
> 收工再 `git status --short | diff /tmp/p85-before.txt -`。

---

## 5. ASCII 圖

### 圖一：兩條佇列的方向（誰放、誰拿）

```text
              本機（這台 Mac 的 Celery worker）                    工人（Phase 87 起）
              ─────────────────────────────                    ──────────────────
                        │                                              │
      ① PutObject context.json ＋ input.jpg  ──▶ [ S3 寄物櫃 ]          │
                        │                          （Phase 84）        │
                        │                                              │
      ② SendMessage ────┼──────▶ ┌───────────────────────┐             │
         {"job_id",     │        │ personaldocai-jobs    │──ReceiveMessage(20)──▶ ③
          "s3_key"}     │        │ Standard              │             │
                        │        │ VisibilityTimeout 900 │◀─DeleteMessage────── ⑦
                        │        │ 長輪詢 20 秒           │             │
                        │        │ 保留 4 天              │             │
                        │        └───────────────────────┘             │
                        │                                    ④ GetObject input
                        │                                    ⑤ Ollama Cloud 看圖
                        │                                    ⑥ PutObject result.json
                        │        ┌───────────────────────┐             │
      ⑨ ReceiveMessage(≤20) ◀────│ personaldocai-results │◀─SendMessage───────── ⑧
         {"job_id"}     │        │ Standard              │   （★ 一定在 ⑥ 之後）  │
      ⑩ DeleteMessage ──┼──────▶ │ VisibilityTimeout 30  │             │
         （不是我的就    │        │ 長輪詢 20 秒           │             │
           改可見度 0）  │        │ 保留 4 天              │             │
                        │        └───────────────────────┘             │
      ⑪ GetObject result.json ◀── [ S3 寄物櫃 ]                        │
      ⑫ 本機 embed ＋ INSERT ＋ 原圖 ＋ 縮圖 ＋ 刪三個 S3 物件            │

   ⛔ 兩條佇列的 body 從頭到尾**只有字串**（design6 §0 禁止第 2 條）。
      單則上限 ＝ MaximumMessageSize（新佇列預設 1 MiB），幾十 MB 的 PDF 塞不進去，物理上的原因。
   ★ 順序鐵律（D9）：⑥ 一定在 ⑧ 之前——先把東西寫好，才通知對方來拿。

   ★ 本 phase 只做「把這兩個框框建出來」。
     ①〜⑫ 那些箭頭要到 Phase 86（本機端接線）與 87／88（工人）才會真的動起來。
```

### 圖二：可見度逾時在做什麼（為什麼 jobs 900、results 30）

```text
   jobs 佇列（工人拿一份 10 頁 PDF，看圖要 6 分鐘）

   t=0    工人 ReceiveMessage          訊息進入「隱形」狀態
          ├──────────────────────────────────────────────┐
          │  工人在看圖…（6 分鐘）                        │  隱形 900 秒
          │                                              │
   t=360  工人做完 → DeleteMessage ──▶ 訊息消失 ✅        │
          └──────────────────────────────────────────────┘

   ⚠ 如果 VisibilityTimeout 設成 300（5 分鐘）：
   t=300  時間到 → 訊息**重新出現** → 另一輪 ReceiveMessage 拿到同一份
          → 同一份 PDF 被看兩次（花兩倍的錢、可能插兩次照片）
          ★ 所以設 900，留足餘裕。

   ⚠ 如果工人在 t=100 當機（沒有 DeleteMessage）：
   t=900  時間到 → 訊息重新出現 → 下一輪有人接手 ✅
          ★ 這就是「工作不會因為工人掛掉而消失」的機制。


   results 佇列（本機拿到的可能是**別人**那則）

   t=0    本機 A ReceiveMessage → 發現 job_id 是別人的 job-2
   t=0.1  A 立刻 ChangeMessageVisibility(0) ──▶ 訊息馬上重新出現 ✅
          → 本機 B 幾乎沒有等待就拿到自己那則

   ⚠ 如果「還回去」那一步失敗（網路抖動）：
          訊息會隱形 VisibilityTimeout 秒
            ・設 900 → B 白等 15 分鐘（早就逾時 fallback 了）
            ・設 30  → B 最多多等 30 秒，還在逾時預算內 ✅
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` ＝ **640** passed ＋ 0 skipped

> ⚠ 下面每一條打 `aws` 或跑 `scripts/aws_check.py` 的驗收，都由 **controller 親自執行**
> （裁決 R3）；實作 subagent 只驗得到 §4.9 那三條（ruff／pytest／死埠）與 `git status`。

- [x] **兩條佇列都存在（而且只有這兩條）**

  ```bash
  cd /Users/linjunting/personalDocAI
  set -a; . ./.env; set +a
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  aws sqs list-queues --region ap-northeast-1 --query 'QueueUrls[]' --output text | tr '\t' '\n' | sed 's#.*/##'
  ```
  預期輸出恰好兩行：
  ```text
  personaldocai-jobs
  personaldocai-results
  ```

- [x] **jobs 的四個屬性都對**

  ```bash
  JOBS_URL=$(aws sqs get-queue-url --queue-name personaldocai-jobs \
    --region ap-northeast-1 --query QueueUrl --output text)
  aws sqs get-queue-attributes --queue-url "$JOBS_URL" --region ap-northeast-1 \
    --attribute-names VisibilityTimeout ReceiveMessageWaitTimeSeconds \
                      MessageRetentionPeriod MaximumMessageSize \
    --query 'Attributes' --output json
  ```
  預期：
  ```json
  {
      "VisibilityTimeout": "900",
      "ReceiveMessageWaitTimeSeconds": "20",
      "MessageRetentionPeriod": "345600",
      "MaximumMessageSize": "1048576"
  }
  ```
  （`MaximumMessageSize` 印 `"262144"` 也可以——那是 2025 年放寬前的預設；**要對的是前三個**。）

- [x] **results 的可見度是 30**

  ```bash
  RESULTS_URL=$(aws sqs get-queue-url --queue-name personaldocai-results \
    --region ap-northeast-1 --query QueueUrl --output text)
  aws sqs get-queue-attributes --queue-url "$RESULTS_URL" --region ap-northeast-1 \
    --attribute-names VisibilityTimeout ReceiveMessageWaitTimeSeconds \
    --query 'Attributes' --output json
  ```
  預期：`{"VisibilityTimeout": "30", "ReceiveMessageWaitTimeSeconds": "20"}`

- [x] **兩條都不是 FIFO**（FIFO 的名字一定以 `.fifo` 結尾，而且會有 `FifoQueue` 屬性）

  ```bash
  aws sqs get-queue-attributes --queue-url "$JOBS_URL" --region ap-northeast-1 \
    --attribute-names All --query 'Attributes.FifoQueue' --output text
  ```
  預期：`None`（＝沒有這個屬性 ＝ Standard）

- [x] **`.env` 有兩個 URL，容器也讀得到**

  ```bash
  grep -c '^SQS_JOBS_QUEUE_URL=.' /Users/linjunting/personalDocAI/.env      # 預期：1
  grep -c '^SQS_RESULTS_QUEUE_URL=.' /Users/linjunting/personalDocAI/.env   # 預期：1
  docker compose exec worker python -c \
    "from app.core import config; print('兩條 URL 都有值 =', bool(config.SQS_JOBS_QUEUE_URL) and bool(config.SQS_RESULTS_QUEUE_URL))"
  ```
  預期最後一行：`兩條 URL 都有值 = True`

- [x] **`python scripts/aws_check.py s3 sqs` 印兩個 OK**（★ 本 phase 的重頭戲）

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  set -a; . ./.env; set +a
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # 只影響 aws CLI；腳本仍會用 .env 的 mac key
  python scripts/aws_check.py s3 sqs
  ```
  預期第一行：`金鑰來源 = .env 那把（personaldocai-mac，最小權限）`
  預期最後兩個 ✅ 行：
  ```text
  ✅ S3 OK：put → get → 內容一致 → delete → 確認不在了
  ✅ SQS OK：兩條佇列都能 send → receive → delete
  ```

- [x] **★ results 佇列是 0 則**（design6 §0「丙」的「何時算過」；`ApproximateNumberOfMessages`
      有延遲，先等一分鐘）

  ```bash
  sleep 60
  aws sqs get-queue-attributes --queue-url "$RESULTS_URL" --region ap-northeast-1 \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
  ```
  預期：
  ```json
  {
      "ApproximateNumberOfMessages": "0",
      "ApproximateNumberOfMessagesNotVisible": "0"
  }
  ```
  不是 0 的話：`aws sqs purge-queue --queue-url "$RESULTS_URL" --region ap-northeast-1`
  （⚠ 60 秒內只能做一次；purge 完再等一分鐘）。

- [x] **jobs 佇列也是 0 則**（同樣的兩個欄位、同樣的做法）

  ```bash
  aws sqs get-queue-attributes --queue-url "$JOBS_URL" --region ap-northeast-1 \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
  ```
  預期：兩個都是 `"0"`

- [x] **全量測試 ＝ 開工基線 ＋ 0**

  ```bash
  pytest -q
  ```
  預期：`640 passed`，**0 skipped**

- [x] **零外部依賴實證（三個死埠一起指，顆數不變）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```
  預期：`640 passed`

- [x] **端點仍是 22 支**

  ```bash
  pytest tests/integration/test_nav_header.py::test_端點數仍為22 -q
  ```
  預期：`1 passed`

- [x] **專案的 `data/` 沒被弄髒**

  ```bash
  cd /Users/linjunting/personalDocAI
  ls data/staging/ | wc -l     # 預期：0（本 phase 沒有上傳任何照片）
  git status --short data/     # 預期：零輸出
  ```

- [x] **格式與 lint 過**

  ```bash
  ruff format --check app tests scripts && ruff check app tests scripts
  ```
  預期：`All checks passed!`

- [x] **機密沒有進 repo**（佇列 URL 含帳號 ID）

  ```bash
  cd /Users/linjunting/personalDocAI
  git status --short | grep -E '(^|/)\.env$' && echo "⛔ 停手" || echo "OK：.env 沒進版控"
  grep -rn "sqs\.ap-northeast-1\.amazonaws\.com/[0-9]" docs/ deploy/ scripts/ \
    CLAUDE.md README.md LAUNCH.md 2>/dev/null \
    && echo "⛔ 有檔案寫死了佇列 URL（含帳號 ID）" || echo "OK：沒有寫死佇列 URL"
  ```
  預期：兩行都印 `OK：…`

- [x] **`docs/spec/` 一字未動**

  ```bash
  git status --short docs/spec/
  ```
  預期：零輸出

- [x] **git 收尾符合現行節奏（裁決 R0：不 commit）**：核對
      `git status --short -- scripts` 的變更**恰為** `M scripts/aws_check.py` 一列，
      而且 `docs/plan/unfinish/` 的計畫檔沒有被 `git mv` 到 `finish/`。

  ```bash
  cd /Users/linjunting/personalDocAI
  git status --short -- scripts    # 預期恰一列： M scripts/aws_check.py
  git status --short -- app tests deploy docs/spec   # 預期：零輸出
  ```

---

## 7. 常見陷阱

1. **症狀：** `aws sqs create-queue` 回 `AccessDenied ... sqs:CreateQueue`，
   但 `aws sts get-caller-identity` 是通的。
   **原因：** shell 裡有 `.env` 載進來的 `AWS_ACCESS_KEY_ID`（`personaldocai-mac` 的
   **最小權限** key，它只能 Send／Receive／改可見度，**不能建佇列**），
   而環境變數的優先序**高於** `~/.aws` 的 profile。
   **正解：** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，
   再用 `aws sts get-caller-identity --query Arn --output text` 確認回到
   `:user/personaldocai-admin`。**每開一個新終端機都要做一次。**

2. **症狀：** `python scripts/aws_check.py sqs` 在 ① jobs 那一段被
   `AccessDenied ... ReceiveMessage` 擋下來。
   **原因：** 掛在 `personaldocai-mac` 上的 policy 是**舊版**——design6 §6 原本把「本機」寫成只有
   jobs 的 `SendMessage` ＋ results 的 `Receive`／`Delete`／`ChangeMessageVisibility`，但總覽 §10.2 N
   已裁決 **mac 的 policy 兩邊都要有**（Phase 88／90 在 Mac 上跑工人用的就是 `.env` 這把 key，
   工人要收 jobs、送 results）。Phase 82 的 `mac-policy.json` 若還是舊版，這裡就會被拒。
   **📌 2026-09-02 實查：AWS 上掛著的那一份已經是新版**（七條 Sid，含 `WorkerReceiveJobs`／
   `WorkerSendResults`），所以這個陷阱**預期不會發生**；下面是萬一撞到時的修法。
   **正解：** 回 Phase 82 §4.6.1 確認 `deploy/aws/mac-policy.json` 是含工人端動作的版本，
   再發布成新的預設版本（IAM policy 是有版本的，`create-policy-version --set-as-default` 就是「換成新版」）。
   ⚠ repo 裡那一份帶 `<ACCOUNT_ID>` 佔位，**直接 `file://` 上傳會 `MalformedPolicyDocument`**——
   比照 Phase 82 §4.6.2 先 `sed` 出一份暫時檔（不進 repo）：
   ```bash
   ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
   sed "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" deploy/aws/mac-policy.json > /tmp/personaldocai-mac-policy.json
   grep -c "<ACCOUNT_ID>" /tmp/personaldocai-mac-policy.json     # 預期：0
   aws iam create-policy-version \
     --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/personaldocai-mac-policy" \
     --policy-document file:///tmp/personaldocai-mac-policy.json --set-as-default
   ```
   （一個 policy 最多留 5 個版本，滿了先 `aws iam delete-policy-version` 刪舊的。）
   被拒之前 ① 已經送了一則進 jobs，記得用 admin 的 `aws sqs purge-queue` 清掉（§4.8）。
   **另一個常見的誤會：** 以為 `unset AWS_ACCESS_KEY_ID …` 之後腳本會改用 admin。不會——
   `unset` 只影響 `aws` CLI；Python 這邊 `load_dotenv()` 會把 `.env` 的 mac key 補回來，
   腳本第一行的「金鑰來源」會老實告訴你。這正是我們要的：驗的是**程式**那把 key。

3. **症狀：** 剛 `purge-queue` 完，`ApproximateNumberOfMessages` 還是 1；
   再 purge 一次卻回 `AWS.SimpleQueueService.PurgeQueueInProgress`。
   **原因：** 兩個 60 秒——① **刪除過程本身要花最多 60 秒**（官方建議不管佇列多大都等滿一分鐘）；
   ② **60 秒內不可以再 purge 同一條佇列**。
   **正解：** purge 完就去泡茶，一分鐘後再看數字。**不要重試**。
   另外官方也明說：purge 之前送進去的訊息**可能還會被收到**，但一分鐘內會被刪掉——
   所以下一輪煙霧也請等滿一分鐘再開始。

4. **症狀：** 手滑 `delete-queue` 之後想立刻用同名重建，回 `AWS.SimpleQueueService.QueueDeletedRecently`。
   **原因：** AWS 規定刪掉佇列之後 **60 秒內**不可以用同一個名字建。
   **正解：** 等一分鐘。（這也是為什麼「屬性設錯」時要用 `set-queue-attributes` 改，
   而不是刪掉重建——見陷阱 5。）

5. **症狀：** 以為 `set-queue-attributes` 會像 S3 的 `put-bucket-*` 一樣**整份覆蓋**，
   於是每次都把三個屬性重打一次；或反過來，以為 S3 的 `put-bucket-lifecycle-configuration`
   會**附加**，結果原本的規則不見了。
   **原因：** 這兩個服務的語意剛好**相反**，很容易搞混。
   **正解：** 記住：
   - **SQS `set-queue-attributes` ＝ 只改你列出來的那幾項**（其餘不動）
   - **S3 `put-bucket-*` ＝ 整份覆蓋**（沒列的就沒了）

6. **症狀：** 同一份 PDF 被工人看了兩次（花兩倍的錢，log 裡出現兩輪 `kind=vlm`）。
   **原因：** jobs 的 `VisibilityTimeout` 設太短（例如照抄預設的 30 秒），
   工人還在看圖、訊息就重新出現了。
   **正解：** jobs 一定要 **900**。真的要驗：
   `aws sqs get-queue-attributes --queue-url "$JOBS_URL" --attribute-names VisibilityTimeout`。
   （順帶一提：就算真的被做了兩次，Phase 87 的冪等——「`result.json` 已存在就跳過」——
   也會擋下第二次的看圖；但**別依賴它**，那是最後一道防線，不是設計。）

7. **症狀：** `receive_message` 明明佇列裡有訊息，卻回空的。
   **原因：** **短輪詢**（`WaitTimeSeconds=0`）只會問一部分伺服器，SQS 是分散式的，
   所以「有訊息卻回空」在短輪詢下是**正常行為**、不是壞掉。
   **正解：** 本專案一律長輪詢：佇列層設 `ReceiveMessageWaitTimeSeconds=20`，
   程式端 `AwsMailbox._receive` 也一定帶 `WaitTimeSeconds`（Phase 83 已釘）。
   `scripts/aws_check.py` 的 `receive_own_message()` 還多重試兩次（`RECEIVE_RETRIES = 3`），
   就是為了容忍這種抖動。

8. **症狀：** 佇列 URL 被 commit 進 repo。
   **原因：** URL 長得像網址，看起來不像機密。但它**含有你的 12 位數帳號 ID**。
   **正解：** URL 只放 `.env`（不入版控）；文件一律寫變數名 `$SQS_JOBS_QUEUE_URL`
   或 `<ACCOUNT_ID>` 佔位（總覽 §7 鐵律 10）。§6 驗收清單有一條 `grep -rn` 在守它。

9. **症狀：** `.env` 填好了，容器裡 `config.SQS_JOBS_QUEUE_URL` 還是空字串。
   **原因：** ① 忘了 `docker compose restart app worker`（行程只在啟動時讀 `.env`）；
   ② 等號兩邊有空白；③ `.env` 變成了資料夾（bind-mount 來源檔不存在時 Docker 會默默建一個）。
   **正解：** `ls -la .env` 確認是檔案，改完一定 restart。

10. **症狀：** 想「順便建一條 dead-letter queue，比較專業」。
    **原因：** 直覺。
    **後果：** 多一條沒有人會去看、卻要記得清的佇列。
    本專案的失敗語意已經有出口了：`JobStore` 的 `failed` 狀態 → 進度面板上的紅字 →
    使用者按 × 關掉（design5 §4.3、D9）。DLQ 只會讓「同一件事有兩個地方記錄」。
    **正解：** 不要。本 phase 的「明確不做」表第 2 列就是這一條。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- AWS 上多兩條 SQS **Standard** 佇列（東京 `ap-northeast-1`）：
  - `personaldocai-jobs`：`VisibilityTimeout=900`、長輪詢 20 秒、保留 4 天
  - `personaldocai-results`：`VisibilityTimeout=30`、其餘相同
  - 兩條都**不是** FIFO、都**沒有** dead-letter queue、都**沒有**自管金鑰
- `.env` 多兩個有值的變數（`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`），
  app 與 worker 容器都讀得到。
- `scripts/aws_check.py` 的 `sqs` 子命令變成真的：`check_sqs()` 從佔位換成真的實作，
  兩條佇列各做一次 send → receive → delete（helper `receive_own_message()` 長輪詢
  最多 `RECEIVE_RETRIES = 3` 次），並在收到別人的訊息時停手提醒。
  **`check_s3()`／`main()` 與檔頭那兩支 helper 一個字都沒動。**
  用 `.env` 的 mac key 跑（總覽 §10.2 N：`personaldocai-mac-policy` 兩條佇列的收發都有），
  第一行印出金鑰來源；purge 仍然是 admin 用 CLI 做的事。

**對外行為變了沒：完全沒有。**

`CLOUD_ROUTE` 仍然是 `off`、`get_cloud_route()` 仍然回 `CloudRouteOff()`——
所以**沒有任何一張照片會被送進 S3，也沒有任何一則訊息會被送進這兩條佇列**。
上傳、待決定、詢問、進度面板一個像素都沒變。
測試顆數仍是 **640 passed ＋ 0 skipped**（本 phase +0；640 ＝ 2026-09-02 實查基線 624
＋ Phase 83 的 +16），端點仍是 **22** 支、
`photo` 表零改動、前端零改動、`compose.yaml` 零改動、`docs/spec/` 一字未動、
`app/` 底下**一行都沒改**。

**現在的狀態一句話：** 寄物櫃有了、兩條通知線也接好了，
**但本機那一端還沒有人拿起電話**——`get_cloud_route()` 到現在為止只認 `off`。

**design6 §0「丙」那一段的「何時算過」已達成：**

| 條件 | 由誰證明 |
|---|---|
| jobs body 無檔案位元組，只含 `job_id` 與 `s3_key` | Phase 83 的 `test_send_job的body恰兩鍵`（斷言鍵恰兩個、值全是字串） |
| **results 佇列已存在、尚無訊息** | 本 phase §4.8 ＋ §6 驗收清單那兩條 `ApproximateNumberOfMessages` ＝ `"0"` |

**下一個 phase：Phase 86「真 AWS 雲端路接線」**——
把 `app/dependencies.py` 的 `get_cloud_route()` 補上 `assume` 分支
（`CloudRoute(AwsMailbox(...), AlwaysRunning(), timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS)`，
`ec2` 那一半仍然留給 Phase 89），加 2 顆單元測試；
然後做一次**故意讓它逾時**的真 AWS 煙霧：
`CLOUD_ROUTE=assume` ＋ `CLOUD_RESULT_TIMEOUT_SECONDS=30`，
上傳一張檔名 `receipt-test.png` 的非敏感圖 →
S3 上真的出現 `input` 與 `context`、jobs 佇列有 1 則、results 佇列 0 則 →
30 秒後**沒有工人**回應 → fallback 本機入庫、S3 被清乾淨、
worker log 出現 `fallback=local reason=result_timeout`。
**那一步驗的正是「雲端壞掉時使用者無感」**——比「雲端成功」更重要。

**顆數：** 開工基線 **640** ＋ **0** ＝ **640**（0 skipped；2026-09-02 實查基線 624 起算）。

---


## 8.1 執行紀錄（2026-09-02，controller 親自執行；值不寫進文件）

- AWS 指令全部以 default profile（`personaldocai-admin`）執行、不 source `.env`；`scripts/aws_check.py` 在 host venv 跑，金鑰來源印出「.env 那把（personaldocai-mac，最小權限）」。
- `personaldocai-jobs`（Visibility 900）／`personaldocai-results`（30）兩條 Standard（`FifoQueue` 屬性不存在＝非 FIFO），Retention 345600、Wait 20；東京恰兩條；`.env` 新增兩條 URL，容器 restart 後 worker 讀到；`python scripts/aws_check.py s3 sqs` 印兩個 ✅；30 秒後兩條佇列 `ApproximateNumberOfMessages`／`NotVisible` 皆 0（未動用 purge）。
- 驗收：全量 640 passed／0 skipped、三死埠 640、端點 22、ruff 綠、追蹤檔零帳號 ID／bucket 後綴／佇列 URL、`docs/spec/` 與 `data/` 乾淨。快照 T85_HEAD 記於 `.superpowers/sdd/phase0902-1/`。

## 附：本文件引用的官方文件

**SQS 概念**

- [SQS Standard Queue（不保證順序、at-least-once）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 短輪詢與長輪詢（`WaitTimeSeconds` 上限 20 秒；短輪詢「有訊息卻回空」是正常的）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS 可見度逾時（visibility timeout）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [SQS 配額（保留期 60 秒〜14 天、長輪詢上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-quotas.html)
- [`CreateQueue` API（`MaximumMessageSize` 1 KiB〜1 MiB、**預設 1 MiB**；`VisibilityTimeout` 0〜43200 預設 30；`QueueDeletedRecently` 60 秒；同名但屬性不同回 `QueueNameExists`）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_CreateQueue.html)
- [SQS 大訊息與 S3 pointer（為什麼位元組要走 S3）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
- [`PurgeQueue`（60 秒內只能一次；刪除過程最多 60 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
- [`ChangeMessageVisibility`（可見度改成 0 ＝立刻還回佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html)
- [SQS 定價（每月前 100 萬次請求免費）](https://aws.amazon.com/sqs/pricing/)

**AWS CLI**

- [`aws sqs create-queue`（`--attributes` 的簡寫語法與各屬性範圍）](https://docs.aws.amazon.com/cli/latest/reference/sqs/create-queue.html)
- [`aws sqs get-queue-url`](https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-url.html)
- [`aws sqs get-queue-attributes`](https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-attributes.html)
- [`aws sqs set-queue-attributes`（只改列出來的那幾項）](https://docs.aws.amazon.com/cli/latest/reference/sqs/set-queue-attributes.html)
- [`aws sqs purge-queue`](https://docs.aws.amazon.com/cli/latest/reference/sqs/purge-queue.html)
- [CLI 的憑證搜尋順序（環境變數優先於 `~/.aws`）](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-authentication.html)
- [`aws iam create-policy-version`（`--set-as-default`；一個 policy 最多 5 個版本）](https://docs.aws.amazon.com/cli/latest/reference/iam/create-policy-version.html)

**boto3**

- [boto3 SQS client：`send_message`／`receive_message`／`delete_message`／`change_message_visibility`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs.html)
- [python-dotenv：`load_dotenv()` 預設 `override=False`，不覆蓋既有環境變數](https://pypi.org/project/python-dotenv/)
