# Phase 84：建 S3 寄物櫃

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的四件事：
> ① 不要開版本控制（versioning）——寄物櫃裡的東西處理完就該消失，留版本只是留垃圾；
> ② 不要用 SSE-KMS 的自管金鑰（design6 §1.2 第 10 列**已否決**：要月費，而 SSE-S3 免費且夠用）；
> ③ 不要開跨區複製、不要開 CloudFront、不要開靜態網站託管（這是寄物櫃，不是相簿也不是網站）；
> ④ 不要順手建 SQS 佇列（那是 Phase 85）。

> 🎯 **一句話目標：** 在東京建一個**私有**的 S3 bucket 當「寄物櫃」——
> Block Public Access 四項全開、預設 SSE-S3 加密、`documents/` 前綴 **2 天**自動過期；
> 然後寫一支 host 用的小腳本 `scripts/aws_check.py`，
> 用 **Phase 83 寫好的 `AwsMailbox`** 對真 S3 做一次 put → get → 比對 → delete，印出 OK。

**為什麼要做這個：**

本機要把一張圖交給遠端的工人看，但**工人不收連線**（design6 D11：EC2 的 inbound 全部關掉，
沒有 HTTP、沒有 SSH）。那圖要怎麼過去？

答案是**中間放一個寄物櫃**：本機把檔案放進去，工人自己去拿；工人把結果放進去，本機自己去拿。
**兩邊都不必開門互連。**

⚠ **S3 在這個專案不是檔案櫃、不是相簿、不是備份**（design6 D1／D8）。
正本永遠在這台 Mac 的 Postgres 與 `data/`。S3 只是「東西在路上時暫時放的地方」，
處理完就刪——而且還有一條 Lifecycle 規則當**掃把**，把任何漏掉的殘骸在兩天後清掉。

Bucket 的三個設定一件都不能少：

| 設定 | 為什麼非有不可 |
|---|---|
| **Block Public Access 四項全開** | 一次設定，之後這個 bucket 就**再也不可能**被設成公開。比「每次都記得檢查」可靠得多。非敏感 ≠ 可公開（design6 §6 明文） |
| **預設加密 SSE-S3（AES256）** | AWS 幫你加密、鑰匙也 AWS 管，**免費**。少了它，硬碟上躺的是明文 |
| **Lifecycle：`documents/` 2 天過期** | 正常流程處理完就會自己刪；這條規則是**掃把**，接住「本機當機、工人掛掉、清理失敗」留下的殘骸。沒有它，殘骸會永遠佔著空間（＝一直扣點數） |

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **bucket（桶）** | S3 裡的一個「大容器」。所有物件都放在某個 bucket 裡面 |
| **bucket 名全球唯一** | 不是「你的帳號裡唯一」，是**全世界唯一**——別人用過的名字你就不能用。所以本專案的名字帶帳號後六碼：`personaldocai-mailbox-<後六碼>` |
| **bucket 命名規則** | 3〜63 個字元；**只能小寫字母、數字、`-`、`.`**；要以字母或數字開頭結尾。**大寫字母與底線 `_` 一律不行**（打錯會直接被拒） |
| **key（物件鍵）** | 一個檔案在 bucket 裡的完整名字，例如 `documents/abc123/input.png`。「key」不是密碼的意思，就是「檔名」 |
| **prefix（前綴）** | S3 其實**沒有真的資料夾**，只有「名字開頭一樣」的一群物件。`documents/` 就是本專案用的前綴，看起來像資料夾、實際上只是名字的開頭 |
| **Region（區域）與 `LocationConstraint`** | bucket 建在哪一個機房群。**東京一定要帶 `--create-bucket-configuration LocationConstraint=ap-northeast-1`**，理由見 §4.2 的框 |
| **Block Public Access（BPA）** | bucket 上的一個總開關，**四個小項全部打開**之後，這個 bucket 就再也不可能被設成公開（連「不小心貼錯一條 policy」都會被擋下來） |
| **ACL（存取控制清單）** | S3 很早期的權限機制（`public-read` 之類）。現在一律用 policy，ACL 只剩下「可能被誤用來開放公開」的風險——BPA 的前兩項就是在關掉這條路 |
| **SSE-S3** | Server-Side Encryption with S3-managed keys ＝「AWS 幫你加密，鑰匙也 AWS 管」。**免費**、對程式完全透明（put／get 一個字都不用改） |
| **SSE-KMS** | 另一種加密，鑰匙由你自己在 KMS 裡管。**每把金鑰每月要錢**，而且每次 put／get 都多一次 KMS 請求。design6 §1.2 第 10 列已否決 |
| **Lifecycle（生命週期規則）** | bucket 上的自動清潔規則：「符合這個前綴的物件放超過 N 天就刪掉」。它由 S3 每天在背景跑，**不是**即時的（所以「2 天」實際上可能是 2〜3 天後才消失） |
| **multipart upload（分段上傳）** | 上傳大檔時 SDK 會自動切成很多段分開傳，最後再「合併」。如果傳到一半斷線，那些**已經傳上去的段會留在 bucket 裡佔空間**，而且用 `list-objects` **看不到**它們——所以 Lifecycle 要另外加一條 `AbortIncompleteMultipartUpload` 把它們清掉 |
| **`file://`（AWS CLI 的參數）** | 「這個參數的內容在某個檔案裡」。`--lifecycle-configuration file://deploy/aws/s3-lifecycle.json`。相對路徑是相對**你現在的工作目錄** |
| **`aws s3api` vs `aws s3`** | `s3api` 是「一個指令對一個 API」的低階指令（本專案用它，因為要精確控制參數）；`aws s3` 是高階的檔案操作（`cp`／`sync`／`ls`），本專案只在收尾時偶爾用 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D8**（S3 是寄物櫃） | `documents/{job_id}/input.*`、`result.json`；**private、Block Public Access、SSE-S3（不加 customer KMS key）**；處理成功後刪；**Lifecycle 1〜3 天當掃把** | §4.2 建 bucket、§4.3 BPA、§4.4 加密、§4.5 Lifecycle（取 **2 天**，落在 1〜3 天的區間中間） |
| **D1**（本機仍是正本） | S3 **不是**檔案櫃 | §3「明確不做」表：不開版本控制、不當備份、不放正本 |
| **§2.2 S3 鍵名（契約）** | `documents/{job_id}/input.*`／`result.json`（＋總覽追認的 `context.json`） | Lifecycle 的 `Prefix` 就是 `documents/`；`scripts/aws_check.py` 用 `AwsMailbox.input_key()` 產生鍵名，不自己拼字串 |
| **§6「Bucket 非公開」那一列** | Block Public Access 全開；非敏感 ≠ 可公開 | §4.3 四項全 `true`；§6 驗收清單用 `get-public-access-block` 驗 |
| **§6「用完刪 mailbox」那一列** | D8 | 正常流程由 `CloudRoute.cleanup()` 刪（Phase 79）；本 phase 補上「漏掉時的掃把」 |
| **§1.2 第 10 列**（被否決） | SSE-KMS customer-managed key → 月費；mailbox 用 SSE-S3 | §4.4 用 `AES256`，不帶 `KMSMasterKeyID` |
| **§7 AWS 帳號與費用** | 單區、不做跨區複製 | 全部東京 `ap-northeast-1` |
| **總覽 §2.8** | bucket 名 `personaldocai-mailbox-<帳號後六碼>`；BPA 四項全開、SSE-S3、Lifecycle `documents/` **2 天**、**不開**版本控制 | §4.1〜§4.5 逐字照做 |
| **總覽 §2.7 Phase 84** | 動到 `deploy/aws/s3-lifecycle.json`（新）、`scripts/aws_check.py`（新）、`.env`；**無新 pytest** | §3「做」清單 |

---

## 2. 前置條件

### 2.1 前面的 phase

- **★G1 已由產品負責人明示通過。**
- **Phase 82 完成**：AWS 帳號（Free plan、東京）、Budget、AWS CLI、
  兩個 IAM 身分（`personaldocai-admin` 給人、`personaldocai-mac` 給程式）。
- **Phase 83 完成**：`app/services/aws_mailbox.py` 已存在、`boto3` 已裝在 host 的 `.venv` 與映像裡。

### 2.2 開工基線（實查）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

pytest -q
# 預期尾巴：632 passed，0 skipped（總覽 §9：Phase 83 收工 632，已含那顆 get_object 成功路徑）
#   以你實查到的數字為準；本 phase 是 +0，收工時這個數字不能變。

# Phase 83 的模組在
python -c "from app.services.aws_mailbox import AwsMailbox; print('AwsMailbox OK')"

# 我是誰（要是 admin，不是 mac）
aws sts get-caller-identity --query Arn --output text
# 預期結尾：:user/personaldocai-admin

aws configure get region        # 預期：ap-northeast-1
```

### 2.3 本 phase 對顆數的影響

**+0 顆**（總覽 §2.7）。本 phase 不新增任何 pytest——
「AWS 上有沒有一個設定對的 bucket」pytest 測不到，而且 **pytest 絕不准連真 AWS**（總覽 §7 鐵律 2）。
驗收改用 **AWS CLI 的輸出** ＋ **`python scripts/aws_check.py s3` 印 OK**。

### 2.4 每次開工都要先做的 shell 準備（本 phase 與 85／86 共用）

```bash
cd /Users/linjunting/personalDocAI

# ① 把 .env 的變數載進 shell（$S3_BUCKET 之類的要用到）
set -a; . ./.env; set +a

# ② ★ 馬上把「程式用的最小權限 key」丟掉，讓 aws 指令回去用 ~/.aws 的 admin profile
#    （不做這一步的話，下面每一條建立資源的指令都會 AccessDenied——Phase 82 §7 陷阱 1）
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

# ③ 確認身分與區域
aws sts get-caller-identity --query Arn --output text   # 結尾要是 :user/personaldocai-admin
echo "region = ${AWS_REGION:-未設定}"                    # 預期：ap-northeast-1
```

> ⚠️ **絕對不要同時跑兩份 pytest。** 兩份會互相 `TRUNCATE` 同一個測試庫，
> 症狀是大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`。

---

## 3. 範圍

### 做

1. 算出 bucket 名 `personaldocai-mailbox-<帳號後六碼>`，建在**東京**。
2. `put-public-access-block`：四項全部 `true`。
3. `put-bucket-encryption`：預設 **SSE-S3（AES256）**。
4. 新增 `deploy/aws/s3-lifecycle.json` 並 `put-bucket-lifecycle-configuration`：
   `documents/` 前綴 **2 天**過期，順便清掉沒完成的分段上傳。
5. 用三個 `get-*` 指令驗證上面三件事真的生效。
6. 新增 `scripts/aws_check.py`（**host 手動用，不進映像、不進 pytest**）：
   - `s3` 子命令：用 `AwsMailbox` put → get → 比對 → delete → 再 get 確認不在了 → 印 OK
   - `sqs` 子命令：先印「Phase 85 才有」（Phase 85 會把它換成真的）
7. `.env` 填 `S3_BUCKET`，restart worker 讓容器重讀。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 開版本控制（`put-bucket-versioning`） | 寄物櫃裡的東西處理完就該消失。開了版本控制之後，「刪掉」只是加一個刪除標記，**舊版本還在**佔空間、還要另外寫 Lifecycle 清——多一層完全用不到的複雜度 |
| 用 SSE-KMS 自管金鑰 | design6 §1.2 第 10 列**已否決**：每把金鑰每月要錢，而且每次 put／get 都多一次 KMS 請求。SSE-S3 免費且對程式完全透明 |
| 開靜態網站託管 / CloudFront / 跨區複製 | 這是寄物櫃，不是網站、不是 CDN、不是備份（D1／D8） |
| 加 bucket policy | BPA 全開 ＋ IAM user 的 policy 已經夠了。多一份 policy 就多一個「兩份規則互相打架」的來源 |
| 加 S3 Event Notification（物件出現就通知） | design6 §1.2 第 4 列與 D9 已明確選了「工人寫完 `result.json` 之後**自己**發 results 訊息」。S3 Event 會在「物件出現但 JSON 還沒寫完」時誤醒 |
| 開 S3 存取記錄（server access logging） | 會產生大量小檔案佔空間（＝扣點數），而本專案的除錯靠 worker 的 log 就夠 |
| 建 SQS 佇列 | 那是 **Phase 85** |
| 把 bucket 名寫進任何文件 | 總覽 §7 鐵律 10：只寫變數名 `$S3_BUCKET`。它含有帳號後六碼 |
| 改任何 `app/` 底下的程式碼 | 本 phase 零產品碼變更。`scripts/` 不進映像，不算產品碼 |
| 改 `compose.yaml` | 本增量零改動。`S3_BUCKET` 走 `.env`（已 bind-mount） |
| 新增 pytest | 顆數維持 632。pytest 絕不連真 AWS |

---

## 4. 實作步驟

> 🧰 **人工＋CLI 型**：每一步都是「指令 → 逐個旗標解釋 → 預期輸出 → 做錯了怎麼退回 → 費用影響」。
> 全部指令都在專案根目錄 `/Users/linjunting/personalDocAI` 執行，
> 而且**先做完 §2.4 的 shell 準備**（尤其是 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`）。

### 4.1 算出 bucket 名字

- [ ] 執行：

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
S3_BUCKET="personaldocai-mailbox-$(printf %s "$ACCOUNT_ID" | tail -c 6)"
echo "$S3_BUCKET"
```

- `aws sts get-caller-identity --query Account --output text`：只把 12 位數字的帳號 ID 印出來
  （`--query` 是 AWS CLI 內建的挑欄位語法，`--output text` 讓它不要包引號與大括號）。
- `printf %s "$ACCOUNT_ID" | tail -c 6`：取**最後六個字元**。
  用 `printf` 而不是 `echo` 是因為 `echo` 會多印一個換行，`tail -c 6` 就會少取一位。

**預期輸出**（後六碼是你的，不要貼進任何文件）：

```text
personaldocai-mailbox-XXXXXX
```

- [ ] 檢查名字合法（S3 的規則比一般檔名嚴）：

```bash
printf %s "$S3_BUCKET" | grep -Eq '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' \
  && echo "名字合法" || echo "⛔ 名字不合法：只能小寫字母、數字、- 與 .，長度 3〜63"
```

**預期輸出：** `名字合法`

**做錯了怎麼退回：** 名字打成大寫或含底線 `_` 的話，`create-bucket` 會直接回
`InvalidBucketName`，**什麼都不會被建立**——改對再跑一次即可。

**費用影響：** $0（還沒建東西）。

---

### 4.2 建 bucket（東京**一定**要帶 `LocationConstraint`）

- [ ] 執行：

```bash
aws s3api create-bucket \
  --bucket "$S3_BUCKET" \
  --region ap-northeast-1 \
  --create-bucket-configuration LocationConstraint=ap-northeast-1
```

**每個旗標在做什麼：**

| 旗標 | 用途 |
|---|---|
| `--bucket "$S3_BUCKET"` | 要建的名字（全球唯一） |
| `--region ap-northeast-1` | **這一條只決定「這次 API 請求送到哪個端點」**，不決定 bucket 建在哪 |
| `--create-bucket-configuration LocationConstraint=ap-northeast-1` | **這一條才決定 bucket 真的建在哪一區** |

```text
┌─ ⚠ 為什麼東京一定要帶 LocationConstraint（新手最容易踩的一個） ─────────────────┐
│                                                                                 │
│ S3 這個 API 有一段很老的歷史包袱：**預設就是 us-east-1（維吉尼亞）**。          │
│ 官方文件寫得很直白：「If you don't specify a Region, the bucket is created      │
│ in the US East (N. Virginia) Region (us-east-1) by default.」                   │
│ 而且「Regions outside of us-east-1 require the appropriate LocationConstraint   │
│ to be specified」。                                                             │
│                                                                                 │
│ 所以會發生三種情況（例外訊息裡的那一個字告訴你是哪一種）：                      │
│   ① 沒帶 LocationConstraint、請求送到東京端點                                   │
│      （Phase 82 把 CLI 預設區域設成東京，所以有沒有寫 --region 都是這種）       │
│      → AWS 直接擋下來：                                                         │
│        An error occurred (IllegalLocationConstraintException) when calling      │
│        the CreateBucket operation: The unspecified location constraint is       │
│        incompatible for the region specific endpoint this request was sent to.  │
│      （這是好事：它大聲壞掉了。注意訊息寫的是 unspecified。）                   │
│   ② 帶了 LocationConstraint=ap-northeast-1，但請求送到別區的端點                │
│      （例如手滑打成 --region us-east-1）→ 同一個例外，訊息改寫成                │
│      「The ap-northeast-1 location constraint is incompatible …」               │
│   ③ CLI 的區域是 us-east-1（別台電腦、別的 profile）而且沒帶 LocationConstraint │
│      → **不會報錯**，bucket 安靜地建在 us-east-1                                │
│      → 之後每一次 put／get 都跨太平洋來回，慢，而且在東京的 Console 上          │
│        「看不到」它（區域選單切在東京）——你會以為 bucket 沒建成功。             │
│        §4.6 ④ 的 get-bucket-location 回 null 就是這一種。                       │
│                                                                                 │
│ 記法：**--region 是「信寄到哪個郵局」，LocationConstraint 是「房子蓋在哪」。**  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**預期輸出：**

```json
{
    "Location": "http://personaldocai-mailbox-XXXXXX.s3.amazonaws.com/"
}
```

**做錯了怎麼退回：**

| 錯誤訊息 | 意思 | 怎麼修 |
|---|---|---|
| `IllegalLocationConstraintException`（訊息含 `unspecified`） | 漏了 `--create-bucket-configuration` | 照上面那條完整指令重跑（**什麼都沒被建立**） |
| `IllegalLocationConstraintException`（訊息含 `ap-northeast-1`） | LocationConstraint 有給，但 `--region` 不是東京（請求送錯端點） | 把 `--region` 改回 `ap-northeast-1` 重跑 |
| `InvalidBucketName` | 名字有大寫、底線，或太短／太長 | 回 §4.1 重算 |
| `BucketAlreadyExists` | 這個名字**全世界**已經有人用了 | 換一個後綴，例如 `personaldocai-mailbox-<後六碼>-tw` |
| `BucketAlreadyOwnedByYou` | 你自己已經建過了 | **這不是錯**，直接往下做 §4.3 |
| `AccessDenied ... s3:CreateBucket` | shell 裡有 `.env` 的最小權限 key | 回 §2.4 跑 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` |

**建錯區了怎麼救：** 沒有「搬家」這種操作，只能刪掉重建。空 bucket 的刪法：

```bash
aws s3api delete-bucket --bucket "$S3_BUCKET" --region <它實際在的區>
```

（不確定它在哪一區：`aws s3api get-bucket-location --bucket "$S3_BUCKET"`；
回 `null` 就是 `us-east-1`——那也是歷史包袱，`us-east-1` 的代號就是空的。）

**費用影響：** 建 bucket 本身 **$0**。之後按「存了多少 GB × 多久」與「打了幾次 API」計費，
而本專案的物件是「幾百 KB、活幾十秒」，一個月下來遠低於 $0.01（從點數扣）。

---

### 4.3 Block Public Access：四項全開

- [ ] 執行：

```bash
aws s3api put-public-access-block \
  --bucket "$S3_BUCKET" \
  --region ap-northeast-1 \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

**四個小項各自在擋什麼：**

| 小項 | 擋掉的事 |
|---|---|
| `BlockPublicAcls=true` | **不准新增**會讓物件公開的 ACL（例如 `--acl public-read`）——想公開的動作當場被拒 |
| `IgnorePublicAcls=true` | **忽略已經存在**的公開 ACL——就算歷史上有人設過，也一律當作沒有 |
| `BlockPublicPolicy=true` | **不准貼上**會讓 bucket 公開的 bucket policy |
| `RestrictPublicBuckets=true` | 就算 policy 已經是公開的，也**只允許本帳號**的身分存取 |

前兩項管 ACL、後兩項管 policy；「新增」與「既有」各擋一次，所以是四項。
**四項全開 ＝ 這個 bucket 再也不可能被公開**，比「每次都記得檢查」可靠得多。

> 📌 2023 年 4 月起，AWS 對**新建的** bucket 預設就是四項全開，所以這一步多半是「把已經是 `true`
> 的東西再設一次」。還是要做：① 把意圖明寫在指令裡（之後誰翻 shell history 都知道這是刻意的）；
> ② 萬一有人在 Console 上手滑關掉一項，重跑這一條就拉回來——它是整份覆蓋，重跑永遠安全。

**預期輸出：** **完全沒有輸出**（成功的設定類指令回空 body）。

**做錯了怎麼退回：** 打錯（例如少一項、或值寫成 `True` 大寫）就整條重跑一次——
這個 API 是**整份覆蓋**的，不是「加上去」，所以重跑就是修正。

**費用影響：** $0。

---

### 4.4 預設加密：SSE-S3（AES256）

- [ ] 執行：

```bash
aws s3api put-bucket-encryption \
  --bucket "$S3_BUCKET" \
  --region ap-northeast-1 \
  --server-side-encryption-configuration \
    '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'
```

- `ApplyServerSideEncryptionByDefault.SSEAlgorithm = AES256` ＝ **SSE-S3**：
  AWS 幫你加密、鑰匙也 AWS 管、**免費**、對程式完全透明
  （`put_object`／`get_object` 一個字都不用改）。
- **刻意不帶 `KMSMasterKeyID`**：那會變成 SSE-KMS，要月費，
  而 design6 §1.2 第 10 列已經否決過（總覽 §3.5 第 10 列也列在「最容易手滑」的清單裡——
  Console 上 KMS 看起來比較「安全」，很誘人）。

> 📌 同樣地，2023-01-05 起新 bucket 預設就已經是 SSE-S3（所有新物件自動加密、免費）。
> 這一步是把「我們要的是 AES256、不是 KMS」明寫下來——重跑等於沒改，不會有副作用。

**預期輸出：** 完全沒有輸出。

**做錯了怎麼退回：** 不小心設成 KMS 的話，整條重跑上面那一份（同樣是整份覆蓋）；
若已經產生過 KMS 金鑰，記得去 KMS 把那把金鑰**排程刪除**（不刪會一直算月費）。

**費用影響：** SSE-S3 **$0**（AWS 明文不收費）。SSE-KMS 才要錢——這就是為什麼要用前者。

---

### 4.5 Lifecycle：`documents/` 前綴 2 天過期（掃把）

- [ ] 新增 `/Users/linjunting/personalDocAI/deploy/aws/s3-lifecycle.json`，**整份逐字貼上**：

```json
{
  "Rules": [
    {
      "ID": "expire-documents-after-2-days",
      "Filter": {
        "Prefix": "documents/"
      },
      "Status": "Enabled",
      "Expiration": {
        "Days": 2
      },
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 1
      }
    }
  ]
}
```

**每個欄位在做什麼：**

| 欄位 | 意思 |
|---|---|
| `ID` | 這條規則的名字，純粹給人看（之後要改哪一條時認得出來） |
| `Filter.Prefix` | 只管**名字以 `documents/` 開頭**的物件。這正是本專案唯一會用到的前綴（design6 §2.2） |
| `Status: "Enabled"` | 規則生效。設成 `"Disabled"` 就只是留著不跑 |
| `Expiration.Days: 2` | 物件放超過 2 天就自動刪掉。design6 D8 寫「1〜3 天當掃把」，取中間值 |
| `AbortIncompleteMultipartUpload.DaysAfterInitiation: 1` | **沒完成的分段上傳**（傳到一半斷線留下的碎片）放超過 1 天就丟掉。⚠ 這些碎片用 `list-objects` **看不到**，但**會佔空間、會扣點數**——沒有這一條的話它們會永遠留著 |

- [ ] 套用：

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$S3_BUCKET" \
  --region ap-northeast-1 \
  --lifecycle-configuration file://deploy/aws/s3-lifecycle.json
```

- `file://deploy/aws/s3-lifecycle.json`：**兩條斜線 ＋ 相對路徑**（相對你現在的工作目錄，
  所以一定要在專案根目錄執行）。想用絕對路徑就是三條斜線：
  `file:///Users/linjunting/personalDocAI/deploy/aws/s3-lifecycle.json`。

**預期輸出：**

```json
{
    "TransitionDefaultMinimumObjectSize": "all_storage_classes_128K"
}
```

（2024 年 9 月起 S3 會在回應裡多回這一個欄位：它講的是「小於 128 KB 的物件**預設不做儲存層級轉換**」。
本專案的規則只有「過期刪除」、沒有任何 Transition，所以這個值**跟我們無關**，看到就好；
舊版 CLI 什麼都不印，也正常。）

**做錯了怎麼退回：**

| 錯誤訊息 | 意思 | 怎麼修 |
|---|---|---|
| `Error parsing parameter '--lifecycle-configuration': Unable to load paramfile` | 路徑不對（不在專案根目錄，或 `file://` 少一條斜線） | `pwd` 確認位置，或改用絕對路徑的三斜線寫法 |
| `MalformedXML` | JSON 少了必要欄位（最常見：漏了 `Status`） | 對照上面那份重貼。**規則不會被套用**，改完重跑即可 |
| 想整條拿掉 | — | `aws s3api delete-bucket-lifecycle --bucket "$S3_BUCKET" --region ap-northeast-1` |

> ⏱ **Lifecycle 不是即時的。** S3 每天在背景跑一次，所以「2 天過期」實際上可能是
> 第 2〜3 天之間才真的消失。**這不是壞掉**——它是掃把，不是主要的清理手段
> （正常流程處理完幾秒內就由 `CloudRoute.cleanup()` 刪掉了）。

**費用影響：** Lifecycle 規則本身 $0；它的作用是**省錢**（把殘骸清掉）。

---

### 4.6 三個 `get-*` 指令驗證設定真的生效

- [ ] **① Block Public Access**：

```bash
aws s3api get-public-access-block --bucket "$S3_BUCKET" --region ap-northeast-1
```

**預期輸出**（四個都要是 `true`）：

```json
{
    "PublicAccessBlockConfiguration": {
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }
}
```

- [ ] **② 預設加密**：

```bash
aws s3api get-bucket-encryption --bucket "$S3_BUCKET" --region ap-northeast-1
```

**預期輸出**（`SSEAlgorithm` 要是 `AES256`，而且**不可以**出現 `KMSMasterKeyID`）：

```json
{
    "ServerSideEncryptionConfiguration": {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                },
                "BucketKeyEnabled": false
            }
        ]
    }
}
```

（`BucketKeyEnabled` 只跟 KMS 有關：這裡是 `false`、或根本沒出現，都正常。）

- [ ] **③ Lifecycle**：

```bash
aws s3api get-bucket-lifecycle-configuration --bucket "$S3_BUCKET" --region ap-northeast-1
```

**預期輸出：**

```json
{
    "Rules": [
        {
            "ID": "expire-documents-after-2-days",
            "Filter": {
                "Prefix": "documents/"
            },
            "Status": "Enabled",
            "Expiration": {
                "Days": 2
            },
            "AbortIncompleteMultipartUpload": {
                "DaysAfterInitiation": 1
            }
        }
    ],
    "TransitionDefaultMinimumObjectSize": "all_storage_classes_128K"
}
```

（最後那個欄位是 §4.5 提過的預設值，可能有也可能沒有，都正常；**要對的是 `Rules` 那一段**。）

- [ ] **④ 順手確認它真的在東京**：

```bash
aws s3api get-bucket-location --bucket "$S3_BUCKET"
```

**預期輸出：**

```json
{
    "LocationConstraint": "ap-northeast-1"
}
```

⚠ 回 `{"LocationConstraint": null}` ＝ 它建在 `us-east-1`（見 §4.2 的框）。
那就要刪掉重建——現在還是空的，成本只有 30 秒。

**做錯了怎麼退回：** 任何一條回 `NoSuchPublicAccessBlockConfiguration` /
`ServerSideEncryptionConfigurationNotFoundError` / `NoSuchLifecycleConfiguration`，
代表對應的那一步沒做成功，回去重跑那一步即可（三個設定彼此獨立，不必全部重來）。

**費用影響：** 這四條都是唯讀請求，$0（GET 類請求便宜到可以忽略）。

---

### 4.7 `.env` 填 `S3_BUCKET`，並讓容器重讀

- [ ] 打開 `/Users/linjunting/personalDocAI/.env`，把 Phase 82 留空的那一行填上：

```ini
S3_BUCKET=personaldocai-mailbox-你的帳號後六碼
```

  （⚠ 等號兩邊**不可以有空白**；值不要加引號。）

- [ ] 讓容器重新讀 `.env`：

```bash
cd /Users/linjunting/personalDocAI
docker compose -f compose.yaml -f compose.dev.yaml restart app worker
docker compose exec worker python -c \
  "from app.core import config; print('S3_BUCKET 有值 =', bool(config.S3_BUCKET))"
```

**預期輸出：**

```text
S3_BUCKET 有值 = True
```

**做錯了怎麼退回：** 印出 `False` → ① `.env` 存檔了嗎 ② 有沒有 restart
③ 等號兩邊是不是多了空白 ④ `ls -la .env` 看它是不是變成了**資料夾**
（bind-mount 的來源檔不存在時 Docker 會默默建一個同名資料夾——`CLAUDE.md` 記過這個坑）。

**費用影響：** $0。

---

### 4.8 新增 `scripts/aws_check.py`

> 這支腳本的角色與既有的 `scripts/check_embedding_dim.py` 完全一樣：
> **host 手動跑的煙霧測試**，不進 Docker 映像（`.dockerignore` 排除了 `scripts/`）、
> 也**不在 pytest 裡跑**（pytest 絕不連真 AWS）。

- [ ] 新增 `/Users/linjunting/personalDocAI/scripts/aws_check.py`，**整份逐字貼上**：

```python
"""對真 AWS 做一次最小的來回，確認「這台 Mac 的憑證與權限真的能用」。

用法（在專案根目錄執行；⚠ 它會真的打 AWS，不要在 pytest 裡呼叫它）：

    python scripts/aws_check.py s3
    python scripts/aws_check.py sqs        # Phase 85 建好兩條佇列之後才有
    python scripts/aws_check.py s3 sqs     # 兩個都跑

★ 它刻意用**產品自己的** app/services/aws_mailbox.AwsMailbox，而不是自己寫一段 boto3。
  這樣驗到的就是正式路徑真的會走的那些呼叫（鍵名、參數、憑證來源全部一樣）：
  這支跑得過 ＝ worker 容器裡的程式也跑得過。

★ 它用哪一把 key？資源名稱與憑證都從 .env 讀——app/core/config.py 一被 import 就會
  load_dotenv()，而 load_dotenv() **只補上不存在的環境變數、不覆蓋已存在的**。所以有三種情況：
    ・shell 裡沒有 AWS_ACCESS_KEY_ID（你先 unset 過）→ 用 .env 那把
      （IAM user personaldocai-mac，最小權限）→ 這是預設，也是 s3 子命令要驗的那一把
    ・shell 裡已經有一把（例如你自己 export 過別的 key）→ 用那一把，.env 那把被略過
    ・shell 裡沒有、.env 也沒填 → boto3 會**安靜地**退到 ~/.aws 的 default profile（admin）
      ——你以為在驗最小權限，其實在用管理員
  所以第一行一律印出「金鑰來源」，讓你確認驗到的是哪一把。
  ⚠ 注意：unset **不會**讓這支腳本改用 admin——unset 只影響 aws CLI；
    Python 這邊 load_dotenv() 會馬上把 .env 的 mac key 補回來。

分層：本檔不寫 SQL、不碰資料庫、不碰 HTTP。它只是把 AwsMailbox 的方法照順序呼叫一次。
"""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

專案根目錄 = Path(__file__).resolve().parent.parent

# 用 `python scripts/aws_check.py` 執行時，Python 只會在 scripts/ 資料夾裡找模組，
# 會找不到 app 套件——把專案根目錄加進搜尋路徑就解決了（與 check_embedding_dim.py 同一招）。
sys.path.insert(0, str(專案根目錄))

from app.core import config  # noqa: E402  （必須在改完搜尋路徑之後 import）
from app.services.aws_mailbox import AwsMailbox  # noqa: E402

# 檢查用的假 job_id。用固定值（不是隨機）有兩個好處：
#   ・出事時你知道要去 bucket 的哪個位置找殘骸（documents/aws-check/）
#   ・它一樣落在 documents/ 前綴底下，所以萬一沒刪掉，Lifecycle 兩天後會清掉
檢查用的JOB_ID = "aws-check"


def 金鑰來源() -> str:
    """回報 boto3 這次會用哪一把 key。只比對「是不是 .env 那把」，**不印任何值**。

    一定要在 config 被 import（＝ load_dotenv() 已經跑完）之後呼叫：那時 os.environ 裡的
    AWS_ACCESS_KEY_ID 要嘛是 shell 帶進來的、要嘛是 .env 補上的、要嘛兩邊都沒有。
    """
    env檔 = 專案根目錄 / ".env"
    env檔那把 = (dotenv_values(env檔) if env檔.is_file() else {}).get("AWS_ACCESS_KEY_ID") or ""
    現在這把 = os.environ.get("AWS_ACCESS_KEY_ID", "")
    if not 現在這把:
        return "沒有任何 key（boto3 會退到 ~/.aws 的 default profile ＝ admin）⚠ 這不是最小權限"
    if 現在這把 == env檔那把:
        return ".env 那把（personaldocai-mac，最小權限）"
    return "不是 .env 那把（多半是你帶進來的 admin key）"


def 建信箱() -> AwsMailbox:
    """照 .env 的設定建一個真的信箱。region 一律明傳，不靠環境變數猜。"""
    if not config.S3_BUCKET:
        raise SystemExit("⛔ .env 的 S3_BUCKET 是空的——先做完 Phase 84 §4.7")
    return AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )


def 檢查S3() -> None:
    """put → get → 比對內容 → delete → 再 get 確認真的不在了。

    最後那個「再 get 一次」不是多餘的：只做 delete 不檢查的話，
    一個「delete 其實被 AccessDenied 但被 delete_objects 的 warning 吞掉」的權限問題
    會完全看不出來（那正是 delete_objects 刻意不往外丟例外的代價）。

    ④ 靠的是「GetObject 缺 key 回 404（NoSuchKey）→ get_object 翻譯成 None」。
    S3 只在呼叫者有 bucket 層級的 s3:ListBucket 時才回 404；沒有的話一律回 403 AccessDenied
    （S3 刻意不讓沒有 list 權限的人分辨「不存在」與「沒權限」）。
    所以 personaldocai-mac-policy 一定要含 s3:ListBucket（總覽 §10.2 P）；
    ④ 炸 AccessDenied ＝ policy 還是舊版。
    """
    信箱 = 建信箱()
    鍵 = 信箱.input_key(檢查用的JOB_ID, "image/png")
    內容 = b"personaldocai aws-check"

    print(f"bucket = {config.S3_BUCKET}   region = {config.AWS_REGION}")

    print(f"① PutObject      {鍵}")
    信箱.put_object(鍵, 內容, "image/png")

    print(f"② GetObject      {鍵}")
    拿回來 = 信箱.get_object(鍵)
    if 拿回來 != 內容:
        raise SystemExit(f"⛔ 拿回來的位元組跟放進去的不一樣：{拿回來!r}")

    print(f"③ DeleteObjects  {鍵}")
    信箱.delete_objects([鍵])

    print("④ 再 GetObject 一次，確認真的不在了")
    if 信箱.get_object(鍵) is not None:
        raise SystemExit("⛔ 刪掉之後還拿得回東西——delete 沒有真的生效（多半是權限）")

    print("✅ S3 OK：put → get → 內容一致 → delete → 確認不在了")


def 檢查SQS() -> None:
    """Phase 85 會把這裡換成真的（送一則 → 收回來 → 刪掉）。"""
    raise SystemExit("這個子命令要等 Phase 85 建好兩條佇列之後才有內容（現在沒有東西可以打）")


def main() -> None:
    子命令 = sys.argv[1:]
    if not 子命令:
        raise SystemExit("用法：python scripts/aws_check.py s3 [sqs]")
    print(f"金鑰來源 = {金鑰來源()}")
    for 名稱 in 子命令:
        if 名稱 == "s3":
            檢查S3()
        elif 名稱 == "sqs":
            檢查SQS()
        else:
            raise SystemExit(f"不認得的子命令：{名稱}（只有 s3 與 sqs）")


if __name__ == "__main__":
    main()
```

---

### 4.9 跑它

- [ ] 執行（⚠ 這一步會真的打 AWS，而且用的是 **`.env` 裡那把最小權限的 key**）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY    # 確保驗到的是 .env 那一把
python scripts/aws_check.py s3
```

- 為什麼 `unset` 之後腳本還是用得到 key：`unset` 只清掉 shell 的環境變數；Python 這邊
  `app/core/config.py` 一被 import 就 `load_dotenv()`，把 `.env` 的 mac key **補回**環境變數
  （它只補不存在的、不覆蓋已存在的）。所以「unset 再跑」＝「用 `.env` 那把跑」——正是要驗的那把。
  腳本第一行會印出**金鑰來源**，讓你不用猜。

**預期輸出：**

```text
金鑰來源 = .env 那把（personaldocai-mac，最小權限）
bucket = personaldocai-mailbox-XXXXXX   region = ap-northeast-1
① PutObject      documents/aws-check/input.png
② GetObject      documents/aws-check/input.png
③ DeleteObjects  documents/aws-check/input.png
④ 再 GetObject 一次，確認真的不在了
✅ S3 OK：put → get → 內容一致 → delete → 確認不在了
```

- [ ] 順手看一眼 bucket 現在是**空的**（`aws-check` 那個物件已經被刪掉）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region ap-northeast-1
```

**預期輸出**（**沒有 `Contents` 這個鍵**，只有幾行 metadata；欄位名稱與順序依 CLI 版本略有不同，
有 `Contents` 才代表還有物件）：

```json
{
    "IsTruncated": false,
    "KeyCount": 0,
    "MaxKeys": 1000,
    "Prefix": "documents/",
    "Name": "personaldocai-mailbox-XXXXXX",
    "EncodingType": "url"
}
```

**做錯了怎麼退回：**

| 訊息 | 意思 | 怎麼修 |
|---|---|---|
| `⛔ .env 的 S3_BUCKET 是空的` | §4.7 沒做，或 `.env` 沒存檔 | 回 §4.7 |
| `botocore.exceptions.NoCredentialsError` | `.env` 裡沒有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` | 回 Phase 82 §4.8 |
| `An error occurred (AccessDenied) ... PutObject` | `personaldocai-mac-policy` 的 S3 ARN 與實際 bucket 名對不上 | 檢查 policy 裡的 `arn:aws:s3:::personaldocai-mailbox-*/documents/*`，bucket 名必須以 `personaldocai-mailbox-` 開頭；鍵必須以 `documents/` 開頭 |
| `⛔ 刪掉之後還拿得回東西` | 有 Put／Get 權限但沒有 `s3:DeleteObject` | 回 Phase 82 §4.6.1 對照 policy |
| `NoSuchBucket` | bucket 名打錯，或 bucket 其實建在別區 | `aws s3api get-bucket-location --bucket "$S3_BUCKET"` |
| 第一行印 `金鑰來源 = 沒有任何 key（…）` | `.env` 的 `AWS_ACCESS_KEY_ID` 沒填——boto3 **安靜地**退到 `~/.aws` 的 admin，後面就算全部 OK，驗到的也不是最小權限 | 回 Phase 82 §4.8 把 mac 的 key 填進 `.env` |
| 第一行印 `金鑰來源 = 不是 .env 那把` | shell 裡有別的 key（多半是你自己 export 過的） | `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 再跑 |
| ①②③ 都過了，④ 那一步炸 `AccessDenied ... GetObject` | 掛在 `personaldocai-mac` 上的 policy 沒有 bucket 層級的 `s3:ListBucket`（總覽 §10.2 P 之前的舊版）。S3 刻意讓「沒有 list 權限」的人分不出「不存在」與「沒權限」：缺 key 時回 403 而不是 404，`get_object` 就不會翻譯成 None | 回 Phase 82 §4.6.1 把 `mac-policy.json` 更新成含 `s3:ListBucket`（Resource ＝ `arn:aws:s3:::personaldocai-mailbox-*`，**bucket 本身**、不是 `/documents/*`）的版本，再 `aws iam create-policy-version --set-as-default` 發布 |

**費用影響：** 一次 PUT ＋ 兩次 GET ＋ 一次 DELETE ＝ **遠低於 $0.0001**（從點數扣）。

---

### 4.10 格式、回歸、收尾

- [ ] 格式與 lint（`scripts/` 也在 CI 的檢查範圍內）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
ruff format --check app tests scripts && ruff check app tests scripts
```

**預期輸出：** `All checks passed!`

- [ ] 全量測試（本 phase **+0 顆**，數字不能變）：

```bash
pytest -q
```

**預期輸出：** `632 passed`，0 skipped。

- [ ] 零外部依賴實證（三個死埠一起指，顆數一模一樣）：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

**預期輸出：** `632 passed`

- [ ] **commit**（⚠ 總覽 §7 鐵律 12：產品負責人沒指示前先不要 commit）：

```bash
cd /Users/linjunting/personalDocAI
git add deploy/aws/s3-lifecycle.json scripts/aws_check.py
git commit -m "feat: Phase 84 建 S3 寄物櫃——東京 bucket（BPA 四項全開、預設 SSE-S3、Lifecycle documents/ 前綴 2 天過期＋清掉未完成的分段上傳）、deploy/aws/s3-lifecycle.json 落地、新增 scripts/aws_check.py（host 手動煙霧：用 AwsMailbox 對真 S3 put→get→比對→delete→確認不在），.env 填 S3_BUCKET；零產品碼變更、顆數仍 632、端點仍 22"
git log -1 --stat
```

**預期：** 只列出 `deploy/aws/s3-lifecycle.json` 與 `scripts/aws_check.py` 兩個檔
（`.env` 不入版控，bucket 名不會進 repo）。

---

## 5. ASCII 圖

### 圖一：寄物櫃長什麼樣（一個 job 在裡面的一生）

```text
   S3 bucket：$S3_BUCKET（東京 ap-northeast-1）
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  Block Public Access ×4 = true      預設加密 SSE-S3(AES256)               │
   │  版本控制：關             Lifecycle：documents/ 前綴 2 天過期              │
   │                                                                          │
   │   documents/                        ← ★ 全專案唯一用到的前綴              │
   │     └── {job_id}/                                                        │
   │           ├── context.json   本機 Put ──▶ 工人 Get   （資料夾／實體／糾錯）│
   │           ├── input.jpg      本機 Put ──▶ 工人 Get   （或 .png / .pdf）    │
   │           └── result.json    工人 Put ──▶ 本機 Get   （看圖結果，無向量）  │
   │                                                                          │
   │   正常結束時這三個一起被刪（CloudRoute.cleanup()，Phase 79）              │
   │   漏掉的殘骸 → 2 天後被 Lifecycle 掃掉（本 phase 建的那把掃把）           │
   └──────────────────────────────────────────────────────────────────────────┘

   ⛔ bucket 裡**不會**有：照片正本、縮圖、資料庫備份、任何長期資料。
      正本永遠在這台 Mac 的 Postgres 與 data/（design6 D1）。
```

### 圖二：本 phase 做的四件事，各自擋掉什麼壞事

```text
   ① create-bucket（帶 LocationConstraint）
        └─ 沒帶 → 安靜地建在 us-east-1 → 每次 put/get 跨太平洋、Console 上看不到

   ② put-public-access-block ×4 = true
        └─ 沒設 → 哪天手滑貼一條公開 policy，或 SDK 帶了 --acl public-read，
                  非敏感照片就真的能被全世界讀（design6 §6：非敏感 ≠ 可公開）

   ③ put-bucket-encryption AES256
        └─ 沒設 → AWS 硬碟上躺的是明文。SSE-S3 免費，沒有不設的理由

   ④ put-bucket-lifecycle-configuration（documents/ 2 天 ＋ 清分段碎片）
        └─ 沒設 → 本機當機／工人掛掉留下的殘骸永遠留著，一直扣點數；
                  傳到一半斷線的分段碎片更糟——list-objects **看不到**它們，
                  你會覺得 bucket 是空的，帳單卻一直有數字

   ⑤ scripts/aws_check.py s3
        └─ 沒有它 → 要等到 Phase 86 的真煙霧才知道權限對不對，
                  而那時同時有閘門、佇列、逾時三件事在跑，很難分辨是哪一層錯
```

### 圖三：本 phase 在整條路線上的位置

```text
   ★G1 ──▶ 82 開戶／CLI／IAM ──▶ 83 aws_mailbox.py（boto3）──▶ ★ 84（本 phase）
                                                                    │
                                                    「東西放得進去、拿得回來、刪得掉」
                                                                    ▼
                                          85 建兩條 SQS 佇列（「有新工作了」的通知）
                                                                    ▼
                                          86 get_cloud_route() 補 assume ＋ 真 AWS 逾時煙霧
                                                                    ▼
                                          87／88 工人 ──▶ ★G2 ──▶ 89〜92 EC2 ──▶ ★G3 ──▶ 93／94 CD
```

---

## 6. 驗收清單

- [ ] **開工基線已實查**：`pytest -q` ＝ 632 passed ＋ 0 skipped

- [ ] **bucket 存在，而且在東京**

  ```bash
  cd /Users/linjunting/personalDocAI
  set -a; . ./.env; set +a
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  aws s3api get-bucket-location --bucket "$S3_BUCKET"
  ```
  預期：`{"LocationConstraint": "ap-northeast-1"}`（回 `null` ＝ 建在 us-east-1，要重來）

- [ ] **Block Public Access 四項全 `true`**

  ```bash
  aws s3api get-public-access-block --bucket "$S3_BUCKET" --region ap-northeast-1 \
    --query 'PublicAccessBlockConfiguration' --output json
  ```
  預期：四個欄位全部是 `true`

- [ ] **預設加密是 SSE-S3，而且沒有 KMS 金鑰**

  ```bash
  aws s3api get-bucket-encryption --bucket "$S3_BUCKET" --region ap-northeast-1 \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault' \
    --output json
  ```
  預期：`{"SSEAlgorithm": "AES256"}`（**不可以**出現 `KMSMasterKeyID`）

- [ ] **Lifecycle 規則在，前綴與天數都對**

  ```bash
  aws s3api get-bucket-lifecycle-configuration --bucket "$S3_BUCKET" --region ap-northeast-1 \
    --query 'Rules[0].{ID:ID,Prefix:Filter.Prefix,Status:Status,Days:Expiration.Days,Abort:AbortIncompleteMultipartUpload.DaysAfterInitiation}' \
    --output json
  ```
  預期：

  ```json
  {
      "ID": "expire-documents-after-2-days",
      "Prefix": "documents/",
      "Status": "Enabled",
      "Days": 2,
      "Abort": 1
  }
  ```

- [ ] **版本控制沒有被打開**（總覽 §2.8：不開）

  ```bash
  aws s3api get-bucket-versioning --bucket "$S3_BUCKET" --region ap-northeast-1
  ```
  預期：**完全沒有輸出**（或 `{}`）——有 `"Status": "Enabled"` 就是被打開了

- [ ] **Lifecycle 的 JSON 檔在 repo 裡，而且是合法 JSON**

  ```bash
  cd /Users/linjunting/personalDocAI
  test -f deploy/aws/s3-lifecycle.json && echo "檔案在"
  python3 -c "import json;json.load(open('deploy/aws/s3-lifecycle.json'));print('JSON 合法')"
  ```
  預期：兩行都印出來

- [ ] **`scripts/aws_check.py s3` 印 OK**（★ 本 phase 最重要的一條）

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  python scripts/aws_check.py s3
  ```
  預期第一行：`金鑰來源 = .env 那把（personaldocai-mac，最小權限）`（印出別的＝驗錯把 key，見 §7 陷阱 11）
  預期最後一行：`✅ S3 OK：put → get → 內容一致 → delete → 確認不在了`

- [ ] **bucket 現在是空的**（檢查用的物件已經被刪掉）

  ```bash
  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region ap-northeast-1 \
    --query 'Contents' --output text
  ```
  預期：`None`（＝回應裡沒有 `Contents` ＝ 一個物件都沒有；還有東西的話會列出每個物件的 Key 等欄位）

- [ ] **`.env` 有 `S3_BUCKET`，容器也讀得到**

  ```bash
  grep -c '^S3_BUCKET=.' /Users/linjunting/personalDocAI/.env      # 預期：1
  docker compose exec worker python -c \
    "from app.core import config; print('S3_BUCKET 有值 =', bool(config.S3_BUCKET))"
  ```
  預期最後一行：`S3_BUCKET 有值 = True`

- [ ] **全量測試 ＝ 開工基線 ＋ 0**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```
  預期：`632 passed`，**0 skipped**（本 phase 沒有新增任何測試）

- [ ] **零外部依賴實證（三個死埠一起指，顆數不變）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```
  預期：`632 passed`（與上一條一模一樣）

- [ ] **端點仍是 22 支**

  ```bash
  pytest tests/integration/test_nav_header.py::test_端點數仍為22 -q
  ```
  預期：`1 passed`

- [ ] **專案的 `data/` 沒被弄髒**

  ```bash
  cd /Users/linjunting/personalDocAI
  ls data/staging/ | wc -l     # 預期：0（本 phase 沒有上傳任何照片）
  git status --short data/     # 預期：零輸出（.gitignore 擋掉了）
  ```

- [ ] **格式與 lint 過**（`scripts/` 也在 CI 的範圍內）

  ```bash
  ruff format --check app tests scripts && ruff check app tests scripts
  ```
  預期：`All checks passed!`

- [ ] **機密沒有進 repo**

  ```bash
  cd /Users/linjunting/personalDocAI
  git status --short | grep -E '(^|/)\.env$' && echo "⛔ 停手" || echo "OK：.env 沒進版控"
  grep -rn "personaldocai-mailbox-[0-9]" docs/ deploy/ scripts/ CLAUDE.md README.md LAUNCH.md \
    2>/dev/null && echo "⛔ 有檔案寫死了 bucket 名（含帳號後六碼）" || echo "OK：沒有寫死 bucket 名"
  ```
  預期：兩行都印 `OK：…`

- [ ] **`docs/spec/` 一字未動**

  ```bash
  git status --short docs/spec/
  ```
  預期：零輸出

- [ ] **git 收尾符合現行節奏**：產品負責人已指示 commit → §4.10 已執行；
      未指示（現行預設）→ 跳過 commit，改核對
      `git status --short -- deploy scripts` 的新增項恰為
      `deploy/aws/s3-lifecycle.json` 與 `scripts/aws_check.py`。

---

## 7. 常見陷阱

1. **症狀：** `aws s3api create-bucket` 回
   `An error occurred (IllegalLocationConstraintException) ... The unspecified location
   constraint is incompatible for the region specific endpoint this request was sent to.`
   **原因：** **沒給** `--create-bucket-configuration`（訊息裡的 unspecified 就是在說這件事），
   而請求送到了東京的端點。
   **正解：** 兩個都要給（§4.2 那條完整指令）。
   **同一個例外的另一種訊息：** `The ap-northeast-1 location constraint is incompatible ...`
   ＝ LocationConstraint 有給，但 `--region` 不是東京（請求送錯端點）——把 `--region` 改回
   `ap-northeast-1` 重跑。
   **更可怕的變體：** CLI 的區域是 `us-east-1`（別台電腦、別的 profile）而且沒帶
   LocationConstraint 的話**不會報錯**——bucket 會安靜地建在 `us-east-1`，
   然後你在東京的 Console 上找不到它、每次 put／get 都跨太平洋。
   用 `aws s3api get-bucket-location` 驗一次，回 `null` 就是 `us-east-1`（那是歷史包袱，
   `us-east-1` 的代號就是空的）。現在還是空 bucket，刪掉重建只要 30 秒。

2. **症狀：** `An error occurred (InvalidBucketName)`。
   **原因：** 名字裡有**大寫字母**或**底線 `_`**。S3 的 bucket 名只准
   小寫字母、數字、`-`、`.`，長度 3〜63，而且要以字母或數字開頭結尾。
   （最常見的來源：想把專案名 `personalDocAI` 直接拿來用。）
   **正解：** 照 §4.1 的公式產生，並跑那條 `grep -Eq` 檢查。

3. **症狀：** 每一條建立／設定類的指令都回 `AccessDenied`，但 `aws sts get-caller-identity` 是通的。
   **原因：** shell 裡有 `.env` 載進來的 `AWS_ACCESS_KEY_ID`（那是 `personaldocai-mac` 的
   **最小權限** key），而環境變數的優先序**高於** `~/.aws` 的 profile。
   **正解：**
   ```bash
   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
   aws sts get-caller-identity --query Arn --output text   # 要回到 :user/personaldocai-admin
   ```
   §2.4 的 shell 準備就是在做這件事，**每次開新終端機都要做一次**。

4. **症狀：** 設好 Lifecycle 之後，故意放一個檔進去等兩天，第三天去看它還在，
   以為 Lifecycle 壞了。
   **原因：** Lifecycle **不是即時的**——S3 每天在背景跑一次過期掃描，
   所以「2 天過期」實際上可能是第 2〜3 天之間才真的消失。
   **正解：** 這是正常行為。Lifecycle 是**掃把**，不是主要清理手段；
   正常流程處理完幾秒內就由 `CloudRoute.cleanup()`（Phase 79）刪掉了。
   真的要驗它有沒有設對，看 `get-bucket-lifecycle-configuration` 的輸出就好，
   不必等兩天。

5. **症狀：** `list-objects-v2` 顯示 bucket 是空的，帳單／用量卻一直有數字。
   **原因：** **沒完成的分段上傳（multipart upload）碎片**。
   傳大檔傳到一半斷線時，已經傳上去的段會留在 bucket 裡佔空間，
   而且 `list-objects` **看不到**它們（要用 `list-multipart-uploads` 才看得到）。
   **正解：** Lifecycle 一定要帶 `AbortIncompleteMultipartUpload`（§4.5 那份 JSON 有）。
   想手動看一眼：
   ```bash
   aws s3api list-multipart-uploads --bucket "$S3_BUCKET" --region ap-northeast-1
   ```
   預期沒有 `Uploads` 這個鍵。

6. **症狀：** 想「再加一條 Lifecycle 規則」，結果原本那條不見了。
   **原因：** `put-bucket-lifecycle-configuration`（以及 `put-public-access-block`、
   `put-bucket-encryption`）都是**整份覆蓋**，不是「附加」。
   **正解：** 要改就把 `deploy/aws/s3-lifecycle.json` 改成**完整的新版本**再 put 一次。
   好消息是：這也代表「打錯了就重跑一次」永遠是安全的修法。

7. **症狀：** `.env` 明明填了 `S3_BUCKET`，容器裡 `config.S3_BUCKET` 卻是空的。
   **原因：** ① 忘了 `docker compose restart app worker`（行程只在啟動時讀 `.env`）；
   ② 等號兩邊有空白（`.env` 不是 Python）；
   ③ `.env` 變成了**資料夾**（bind-mount 的來源檔不存在時 Docker 會默默建一個同名資料夾）。
   **正解：** `ls -la .env` 確認它是檔案（開頭不是 `d`），改完一定 restart。

8. **症狀：** 有人把 `scripts/aws_check.py` 改成 `test_aws_check.py`、或在 `tests/` 裡 import 它，
   於是 CI 開始連真 AWS（然後在沒有憑證的 GitHub runner 上一片紅）。
   **原因：** 沒搞清楚它的角色。
   **正解：** 它是**手動煙霧**，與 `scripts/check_embedding_dim.py` 同一類：
   不進 pytest、不進 Docker 映像（`.dockerignore` 排除了 `scripts/`）、不進 CI。
   **pytest 絕不連真 AWS** 是總覽 §7 鐵律 2。

9. **症狀：** 在 Console 上看到「SSE-KMS」覺得比較安全，就把加密改成 KMS。
   **原因：** 直覺。
   **後果：** design6 §1.2 第 10 列**已否決**——每把 KMS 金鑰每月要錢
   （Free plan 的點數會被慢慢啃），而且每次 put／get 都多一次 KMS 請求（更慢）。
   本專案的物件活不到一分鐘，SSE-S3 完全夠。
   **正解：** 保持 `AES256`。真的手滑改過了：重跑 §4.4，並去 KMS 把那把金鑰**排程刪除**。

10. **症狀：** `Error parsing parameter '--lifecycle-configuration': Unable to load paramfile
    file://deploy/aws/s3-lifecycle.json`。
    **原因：** `file://` 後面的相對路徑是相對**你現在的工作目錄**，而你不在專案根目錄。
    **正解：** `cd /Users/linjunting/personalDocAI` 再跑，或改用絕對路徑的三斜線寫法
    `file:///Users/linjunting/personalDocAI/deploy/aws/s3-lifecycle.json`。

11. **症狀：** `python scripts/aws_check.py s3` 印 OK，但你其實不確定它驗的是哪一把 key；
    或者以為 `unset AWS_ACCESS_KEY_ID …` 之後腳本會改用 admin。
    **原因：** `unset` 只對 `aws` CLI 有效。Python 這邊 `app/core/config.py` 一被 import 就
    `load_dotenv()`，而 `load_dotenv()` **只補上不存在的環境變數、不覆蓋已存在的**——
    所以：unset 之後跑腳本 ＝ `.env` 那把（mac）；shell 裡已經有一把 ＝ 用那一把；
    `.env` 沒填而 shell 也沒有 ＝ boto3 **安靜地**退到 `~/.aws` 的 default profile（admin），
    你以為在驗最小權限，其實在用管理員。
    **正解：** 看腳本印的**第一行** `金鑰來源 = …`。本 phase 要的是
    `.env 那把（personaldocai-mac，最小權限）`；印出 `沒有任何 key` 就回 Phase 82 §4.8 填 `.env`；
    印出 `不是 .env 那把` 就 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 再跑。
    「CLI 用 admin 建資源、程式用 mac key 驗權限」兩者在同一個視窗裡並存，是刻意的分工。

12. **症狀：** `python scripts/aws_check.py s3` 的 ①②③ 都過了，④「再 GetObject 一次」卻炸
    `AccessDenied`——明明物件已經刪掉，S3 回的不是「不存在」。
    **原因：** S3 的一個老規矩：呼叫者對 bucket **沒有 `s3:ListBucket`** 時，GetObject 缺 key
    一律回 **403 AccessDenied**，只有有 list 權限的人才拿得到 **404 NoSuchKey**——它刻意不讓沒有
    list 權限的人分辨「不存在」與「沒權限」。`AwsMailbox.get_object()` 只把 404／NoSuchKey 翻譯成
    None，403 會原樣往外丟，於是 ④ 炸掉。這也是總覽 §10.2 P 把 `s3:ListBucket`（Resource ＝
    bucket 本身 `arn:aws:s3:::personaldocai-mailbox-*`）加進 `personaldocai-mac-policy` 的原因：
    正式流程裡 `fetch_result()`／工人的冪等檢查都靠「缺 key → None」判斷。
    **正解：** 回 Phase 82 §4.6.1 確認 `deploy/aws/mac-policy.json` 有那一條，沒有就補上並
    `aws iam create-policy-version --policy-arn "arn:aws:iam::<ACCOUNT_ID>:policy/personaldocai-mac-policy"
    --policy-document file://deploy/aws/mac-policy.json --set-as-default` 發布新版本，再跑一次 ④。
    （這一步也解釋了為什麼 mac key 現在可以 `list-objects-v2`——但本文件的 `aws` 指令一律仍用 admin，
    載完 `.env` 照樣 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，不必為了 list 切來切去。）

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- AWS 上多一個**私有**的 S3 bucket（東京 `ap-northeast-1`）：
  Block Public Access 四項全開、預設 SSE-S3（AES256）、
  `documents/` 前綴 **2 天**過期 ＋ 未完成分段上傳 1 天丟掉、**沒有**版本控制。
- repo 多兩個檔：
  - `deploy/aws/s3-lifecycle.json`（Lifecycle 規則的來源，零機密）
  - `scripts/aws_check.py`（host 手動煙霧；`s3` 子命令已可用，`sqs` 子命令是 Phase 85 的事；
    第一行印出它用的是哪一把 key，所以「驗到的是不是最小權限」不用猜）
- `.env` 多一個有值的 `S3_BUCKET`，app 與 worker 容器都讀得到。

**對外行為變了沒：完全沒有。**

`CLOUD_ROUTE` 仍然是 `off`、`get_cloud_route()` 仍然回 `CloudRouteOff()`，
所以**沒有任何一張照片會被送進這個 bucket**。上傳、待決定、詢問、進度面板一個像素都沒變。
測試顆數仍是 **632 passed ＋ 0 skipped**（本 phase +0），端點仍是 **22** 支、
`photo` 表零改動、前端零改動、`compose.yaml` 零改動、`docs/spec/` 一字未動、
`app/` 底下**一行都沒改**。

**現在的狀態一句話：** 寄物櫃蓋好了、鎖也上了、掃把也放好了，**但還沒有人知道要來拿東西**。

**下一個 phase：Phase 85「建 SQS 兩條佇列」**——
建 `personaldocai-jobs`（本機 Send、工人 Receive；`VisibilityTimeout=900` 秒，
因為工人看一份多頁 PDF 要很久）與 `personaldocai-results`（工人 Send、本機 Receive；
`VisibilityTimeout=30` 秒），兩條都開 20 秒長輪詢；
把 `aws_check.py` 的 `sqs` 子命令換成真的（送一則 → 收回來 → 刪掉）；
`.env` 填兩個佇列 URL。做完之後「東西怎麼過去」與「怎麼通知對方」就都齊了。

**顆數：** 開工基線 **632** ＋ **0** ＝ **632**（0 skipped）。

---

## 附：本文件引用的官方文件

**S3 設定**

- [`aws s3api create-bucket`（`--create-bucket-configuration LocationConstraint`；
  「Regions outside of us-east-1 require the appropriate LocationConstraint」）](https://docs.aws.amazon.com/cli/latest/reference/s3api/create-bucket.html)
- [S3 bucket 命名規則（小寫、3〜63 字元、不可有底線）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html)
- [`aws s3api put-public-access-block`（四個小項的簡寫語法）](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-public-access-block.html)
- [S3 Block Public Access（四項各自擋什麼）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [`aws s3api put-bucket-encryption`（`AES256` 的 JSON 形狀）](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-bucket-encryption.html)
- [S3 預設加密（SSE-S3 免費、對程式透明）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
- [`aws s3api put-bucket-lifecycle-configuration`（Rules 的 JSON 形狀）](https://docs.aws.amazon.com/cli/latest/reference/s3api/put-bucket-lifecycle-configuration.html)
- [S3 Lifecycle 設定（過期規則、每天背景執行）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [用 Lifecycle 清掉未完成的分段上傳（`AbortIncompleteMultipartUpload`）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html)
- [`aws s3api get-bucket-location`（`us-east-1` 回 `null` 的歷史包袱）](https://docs.aws.amazon.com/cli/latest/reference/s3api/get-bucket-location.html)

**AWS CLI 用法**

- [AWS CLI 的 `file://` 參數載入](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-parameters-file.html)
- [AWS CLI 的 `--query`（JMESPath）與 `--output`](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-output-format.html)
- [CLI 的憑證搜尋順序（環境變數優先於 `~/.aws`）](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-authentication.html)

**boto3**

- [boto3 S3 client：`put_object`／`get_object`／`delete_objects`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [boto3 憑證與環境變數（環境變數優先於 `~/.aws`）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
- [python-dotenv：`load_dotenv()` 預設 `override=False`，不覆蓋既有環境變數](https://pypi.org/project/python-dotenv/)
- [`aws configure get`（只讀 `~/.aws` 設定檔、不看環境變數）](https://docs.aws.amazon.com/cli/latest/reference/configure/get.html)
- [S3 GetObject：缺 key 時，有 `s3:ListBucket` 回 404 NoSuchKey、沒有則回 403 AccessDenied](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)
- [`aws iam create-policy-version`（`--set-as-default`；一個 policy 最多 5 個版本）](https://docs.aws.amazon.com/cli/latest/reference/iam/create-policy-version.html)
- [S3 Lifecycle 的 `TransitionDefaultMinimumObjectSize`（`put`／`get-bucket-lifecycle-configuration` 回應裡的那個欄位）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html)
