# Phase 83：`aws_mailbox` 模組（全系統唯一碰 boto3 的地方）

> 📌 **2026-09-02 校準紀錄**（本檔已依 `.superpowers/sdd/phase0902-1/progress.md` 的裁決 R0〜R7 重新校準過，
> 對照基準是當天的工作樹 HEAD `a159131`。下面一列一條，寫清楚每條裁決落在本檔哪裡）：
>
> | 裁決 | 這一條在本檔怎麼落地 |
> |---|---|
> | **R0**（不 commit、用工作樹快照相減審） | §4.9 從「commit」改成「**不 commit——記快照**」；§6 最後一條的驗收改成 `.superpowers/sdd/phase0902-1/snapshot-tree` 兩顆 tree 相減 ＋ `git status --short` |
> | **R1**（識別字一律英文） | §4.2 測試碼與 §4.4 實作碼裡的中文函式／變數／參數名全部改英文（`test_…` 的**測試函式名維持中文**；log 字樣、錯誤訊息、註解、docstring 也維持中文）。跨檔共用名見 §4.4 的常數與 §4.2 的 `StubS3`／`StubSqs`／`StubEc2`／`make_mailbox()`／`make_client_error()` |
> | **R2**（顆數以 2026-09-02 實查 624 起算） | 全檔的 616／632 改成 **624／640**。**「+16」這個增量沒有變**——變的只是絕對值：總覽 §2.2／§2.7／§9 的 632 是用 616 基線算的，而總覽 §2.2 的 Phase 81 那列已註記「實 **624**」（Phase 75／79／81 的 review 裁決各多補了幾顆守門測試）。抄顆數時**只對「本 phase 新增幾顆」**，不要對絕對數字 |
> | **R3**（AWS 操作歸 controller） | 本 phase **一條 `aws` 指令都沒有**（測試全部用手寫 stub、一個位元組都不出網），所以 R3 在本檔只影響 §4.1 的**重建映像**：那一步由 controller 親自執行，實作者只做 `uv pip install -r requirements.txt` |
> | **R4**（`scripts/aws_check.py` 不寫自動化測試） | 與本 phase 無關（那支腳本是 Phase 84／85 建的）。本檔 §8 提到它時已註明是下一個 phase 的事 |
> | **R5**（煙霧前開 Ollama、開關撥 cloud） | 與本 phase 無關（本 phase 零煙霧、零模型呼叫）。那是 Phase 86 |
> | **R6**（不需要真機／手機） | 與本 phase 無關（零前端、零鏡頭） |
> | **R7**（四份計畫檔平行校準，只改自己名下那一份） | 本檔是校準者 A 名下；`app/`／`tests/`／總覽／其他計畫檔一個字都沒動 |
>
> 另外校準時實查修正的過期事實（詳見各處的 📌 標記）：
> `tests/integration/test_design5_error_paths.py` 檔頭**已經有** `import re`（實查第 30 行，不必再加）、
> 目標那顆測試就在**第 426 行**（與 §4.6 寫的一致）、
> `deploy/aws/mac-policy.json` 的 `s3:ListBucket` 那條 Sid 實際叫 **`ListMailboxBucket`**（§7 陷阱 10 已改成實檔名字）、
> Phase 82 的計畫檔已歸檔到 `docs/plan/finish/`、
> `ruff format --check` 現在的檔案數是 **105**（本 phase 之後 107）。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的四件事：
> ① 不要建任何真的 bucket／佇列（那是 Phase 84／85，而且本 phase 的測試**一個位元組都不出網**）；
> ② 不要裝 `moto`／`localstack` 之類的 AWS 模擬器（手寫 stub 就夠，多一個相依就多一個要升級的東西）；
> ③ 不要在 `AwsMailbox` 裡加重試、加連線池、加 backoff（重試的語意在 `gated_ingest` 與工人那一層，這裡只是很薄的一層轉譯）；
> ④ 不要順手把 `get_cloud_route()` 的 `assume` 分支補起來（那是 **Phase 86**，而且要先有真的 bucket 與佇列才驗得動）。

> 🎯 **一句話目標：** 寫出 `app/services/aws_mailbox.py`——把「S3 的三個動作 ＋ 兩條 SQS 佇列的六個動作 ＋ 問一台 EC2 現在是什麼狀態」
> 包成十四個好懂的方法，**而且全系統只有這一個檔可以 `import boto3`**；
> 用手寫的 stub client 寫 16 顆單元測試把每一個參數釘死，**完全不連網**；
> 同時把 design5 那顆「不准有 boto3」的掃碼測試改掉（design6 §1.1 第 1 列正式推翻它）。

**為什麼要做這個：**

Phase 77 已經定好了 `CloudMailbox` 這份**契約**（Protocol）：
「一個信箱要會 put／get／delete 物件、會往 jobs 送、會從 results 收、會改可見度、會回三個鍵名、會查實例狀態」。
Phase 78〜81 的流程程式碼（`gated_ingest.py`、`cloud_ingest.py`）從頭到尾只認這份契約，
測試用的是 `tests/fakes.FakeMailbox`——所以到現在為止，**這個專案還完全不知道 AWS 長什麼樣**。

本 phase 就是補上那個「真的會打 AWS 的實作」。它很薄，薄到幾乎沒有邏輯：

```text
   cloud_ingest.CloudRoute           ← 流程：什麼時候送、等多久、逾時怎麼辦（77／79／80）
            │  只認 CloudMailbox 這份契約
            ▼
   ┌────────────────────┬──────────────────────┐
   │ FakeMailbox        │ AwsMailbox           │
   │ （tests/fakes.py） │ （★ 本 phase）        │
   │ 純記憶體、給測試用  │ 真的打 AWS，唯一 boto3│
   └────────────────────┴──────────────────────┘
```

**為什麼一定要拆成兩層（而不是把 boto3 直接寫進 `cloud_ingest.py`）：**
合成一個檔的話，Phase 78〜81 的每一顆流程測試都會被迫載入 boto3、被迫想辦法假裝 AWS，
而第五道安全網 `wire_fake_cloud`（把 `AWS_ENDPOINT_URL` 指到死埠）也就失去意義了。
拆開之後，**流程測試用假信箱、信箱測試用 stub client**，兩邊都跑得飛快而且零外部依賴。
（這是總覽 §10.2 追認項 C 的裁決。）

另外還有一件必須在本 phase 一起做的事：`requirements.txt` 加 `boto3>=1.35` 之後，
增量五留下的一顆掃碼測試會**變紅**——它明文斷言「`boto3` 不可以出現在 requirements」。
那條禁令已經被 design6 §1.1 第 1 列**正式推翻**，所以本 phase 要把它改掉並在註解裡寫明推翻的來源。
**這是增量五留下的 543 顆裡唯一被修改的一顆**（總覽 §10.1 追認項 i）。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **boto3** | AWS 官方的 Python 套件。`boto3.client("s3")` 拿到一個「可以呼叫 S3 的東西」，方法名就是 API 名的小寫底線版（`PutObject` → `put_object`） |
| **botocore** | boto3 底下那一層（真正組 HTTP 請求、簽名、解析回應的部分）。**例外類別住在這裡**：`from botocore.exceptions import ClientError` |
| **client（客戶端）** | 「一個綁好區域與憑證的呼叫器」。`boto3.client("s3", region_name="ap-northeast-1")`。**建立它不會連線**，第一次真的呼叫方法時才會發 HTTP |
| **resource（boto3 的另一種介面）** | `boto3.resource("s3")` 給你「物件導向」的寫法（`bucket.Object(key).get()`）。本專案**一律用 client、不用 resource**：client 的方法名與 AWS API 名一一對應（文件好查、錯誤訊息好對）、參數形狀就是 API 的參數形狀，而且 stub 好寫（三個 class 就頂替得掉）。網路上看到的 resource 寫法不要混進來 |
| **`ClientError`** | AWS 回了一個錯誤時 boto3 丟的例外。錯誤代碼在 `錯誤.response["Error"]["Code"]`，例如 `NoSuchKey`、`AccessDenied` |
| **`NoSuchKey`** | S3 的錯誤代碼：「你要的那個 key 不存在」。本專案把它翻譯成 `None`（不是例外）——因為「還沒寫好」是**正常狀態**，不是壞掉 |
| **stub（樁）vs mock（模擬物件）** | 兩個都是測試裡頂替真東西的假件，差在**誰負責斷言**：stub 只做兩件事——**記下被怎麼呼叫**、**回一個你指定的答案**——斷言寫在測試本體（`assert s3.put_calls[0]["Key"] == ...`）；mock（例如 `unittest.mock.MagicMock`）則把期望寫在假件身上、事後由假件自己驗（`mock.assert_called_with(...)`）。本檔全部用 **stub**：三個很短的 class、每個欄位都看得見，新手讀得懂、也不必學 mock 框架的魔法方法 |
| **`Body`（S3 回應裡的）** | `get_object` 回來的字典裡，`Body` 是一個「像檔案的物件」（streaming body），要 `.read()` 才拿得到位元組 |
| **`Delete={"Objects": [...]}`** | `delete_objects`（一次刪很多個）的參數形狀。每個元素是 `{"Key": "..."}`。一次最多 1000 個，本專案每次最多 3 個 |
| **`ReceiptHandle`（收據把手）** | 從佇列拿走一則訊息時 SQS 給你的**臨時字串**。要刪掉它、或要提早讓它重新出現，都得用它。它**不是** message id，而且**每次拿都不一樣** |
| **`WaitTimeSeconds`（長輪詢）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 N 秒」。**AWS 的上限就是 20**，填超過會被拒絕。好處是少打很多次 API（＝省錢），代價是那 N 秒程式在等 |
| **`MaxNumberOfMessages`** | 一次最多拿幾則。本專案固定 **1**——一次處理一則，邏輯最單純，也不必煩惱「拿了三則但只做完一則」 |
| **`VisibilityTimeout`（可見度逾時）** | 訊息被拿走之後「隱形」多久。改成 **0** ＝「我拿錯了，馬上還回去給別人」——本專案在「收到別人的 results 訊息」時就是這樣做 |
| **壞紙條（poison message）** | 佇列裡一則「格式認不得」的訊息（body 不是 JSON、或沒有 `job_id`）。沒人刪它的話，每次可見度到期就回來一次（jobs 900 秒），直到 4 天保留期滿。本檔在 `_receive` 就把它刪掉並留 warning（總覽 §10.2 追認項 K）；會出現的唯一情況是有人用 `aws sqs send-message` 手動塞東西 |
| **`Reservations`（EC2 回應裡的）** | `describe_instances` 的回應結構有兩層：`Reservations[].Instances[]`。一台機器的狀態在 `Reservations[0].Instances[0].State.Name`（`running`／`stopped`／`pending`／`stopping`…） |
| **`InvalidInstanceID.NotFound`** | EC2 的錯誤代碼：「你問的那台機器不存在」（id 打錯、或 Terminate 超過一小時）。⚠ 它是一個**例外**（`ClientError`），不是空清單——`describe_instances` 只有在「那台機器不是你的」時才會默默回空的 `Reservations`。本專案把它翻譯成 `"unknown"` |
| **`Errors`（DeleteObjects 回應裡的）** | `delete_objects` 是批次 API：某幾個 key 刪不掉時 S3 **不丟例外**，回 HTTP 200、把失敗的列在 `Errors`（每個有 `Key`／`Code`／`Message`）。不看這個清單，權限少一行會安靜地留下殘骸 |
| **`s3:ListBucket` 與 403／404** | S3 的一條隱藏規則：對**不存在的 key** 做 GetObject，呼叫者**有** `s3:ListBucket` 權限時回 404 `NoSuchKey`；**沒有**時回 **403 `AccessDenied`**（S3 不讓沒權限的人靠 404 探測 key 存不存在）。本檔「`NoSuchKey` → `None`」的翻譯**只在 policy 有給 ListBucket 時成立**，見 §7 陷阱 10 |
| **掃碼測試** | 「把原始碼當文字讀進來、用規則檢查有沒有違規」的測試。本專案已經有好幾顆（SQL 只在 repository、前端零 `alert(`…）。本 phase 加一顆「`boto3` 只准出現在 `aws_mailbox.py`」 |
| **死埠（discard port）** | TCP 的 **9 號埠**。本機一定沒有人在聽，所以連它會**立刻** connection refused（而不是卡住等逾時）。本專案拿它當「零外部依賴」的實證工具 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **§1.1 第 1 列** | design5.md §3「不做：雲端物件儲存、S3」**正式推翻** | §4.1 加 `boto3>=1.35`；§4.6 改掉那顆掃碼測試並在 docstring 引用這一列 |
| **D8**（S3 是寄物櫃） | `documents/{job_id}/input.*`、`result.json`；處理成功後刪 | `input_key`／`context_key`／`result_key` 三個鍵名函式 ＋ `delete_objects` |
| **D9**（完成訊號＝results 佇列） | jobs body `{"job_id","s3_key"}`；results body `{"job_id"}`；**不含位元組** | `send_job`／`send_result` 的兩顆 body 測試逐鍵斷言 |
| **§2.2 S3 鍵名（契約）** | 三個鍵的完整路徑 | `test_input_key依content_type給副檔名`、`test_context_key與result_key的路徑` |
| **§2.3 SQS 佇列（契約）** | 兩條 Standard；長輪詢 `WaitTimeSeconds` 最多 20 秒 | `test_receive_job的等待秒數不超過20` |
| **§0 禁止第 2 條** | **把影像位元組塞進 SQS ＝ 禁止** | 兩顆 body 測試都斷言「值全部是字串」 |
| **§8 錯誤表第 4 列** | PutObject／SendMessage 失敗 → fallback，不留半套（**盡力**刪） | `delete_objects` 失敗只 `logger.warning`，不往外丟（清理是盡力，不能因為清不掉就把整筆搞砸） |
| **§9 測試策略** | 假 AWS 客戶端；pytest **不連真 AWS** | 全檔 16 顆用 stub client；§6 驗收清單的三死埠實證 |
| **總覽 §2.4.1** | `AwsMailbox` 的十四個方法簽章 | §4.4 的完整檔逐字實作 |
| **總覽 §7 鐵律 5** | `boto3` 只准出現在 `app/services/aws_mailbox.py` | `test_boto3只在aws_mailbox裡出現`（掃 `app/` 全樹） |
| **總覽 §10.1 追認項 i** | 改 design5 那顆掃碼測試 | §4.6 |
| **總覽 §10.2 追認項 C** | 拆成 `cloud_ingest.py`（流程）＋ `aws_mailbox.py`（唯一 boto3） | 本 phase 只寫後者，前者一個字都不動 |
| **總覽 §10.2 追認項 J** | `get_object` 的**成功路徑**也要有測試（所以是 +16 顆，不是 +15） | `test_get_object拿得回位元組而delete_objects送出鍵清單` |
| **總覽 §10.2 追認項 K（擴寫版）** | 壞紙條（body 不是 JSON、或沒有 `job_id`）在 `_receive` 就 warning＋刪掉＋回 None | `test_receive_job沒訊息時回None` 的 ②③ 段 |

---

## 2. 前置條件

### 2.1 前面的 phase

📌 **2026-09-02 實查：下面四條全部已經滿足**（工作樹 HEAD `a159131`，Phase 74〜82 皆已 commit
並歸檔到 `docs/plan/finish/`；`docs/plan/unfinish/` 只剩總覽與 83〜95）。

- **Phase 74〜81 全部完成**（階段甲）。
- **★G1 已由產品負責人明示通過**（他親自做完 Phase 82，並以 dev-prompt `phase0902-1.md`
  明示執行 83〜86＝總覽 §4 說的「一句明確的話……或 dev-prompt 檔案」）。
- **Phase 82 完成**（計畫檔已歸檔到 `docs/plan/finish/phase-82-AWS帳號與工具.md`）：
  AWS 帳號開好、CLI 2.36.38 裝好、`aws sts get-caller-identity` 的 Arn 結尾是
  `user/personaldocai-admin`、region `ap-northeast-1`、Budget `personaldocai-budget` $5／月已建、
  `deploy/aws/mac-policy.json` 在（七條 Sid，含 §7 陷阱 10 講的 `ListMailboxBucket`）、
  `.env` 已有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`／`AWS_REGION`。

  > 嚴格說，本 phase 的程式碼與測試**完全不需要 AWS 帳號**（一個位元組都不出網）。
  > 但 Phase 84 一開工就要拿這個模組去打真的 S3，順序照總覽 §2.3 排就好。
  >
  > ⚠ **`~/.aws` 裡只有 `[default]`，沒有叫 `personaldocai-admin` 的 profile。**
  > default 就是 admin，所以**所有 `aws` 指令都不必也不可以加 `--profile personaldocai-admin`**
  > （加了會噴 `The config profile (personaldocai-admin) could not be found`）。
  > 本 phase 一條 `aws` 指令都沒有，寫在這裡是給接著做 84／85 的人看的。

- **Phase 77 已經在 `app/services/cloud_ingest.py` 裡定義了 `MailboxMessage`**（實查在第 115 行），
  本 phase 直接 import 它（**不要**在本檔另外定義一份，理由見 §4.4 的 ⚠ 框）。
  同一個檔的 `CloudMailbox` Protocol（第 135 行起）**十四支方法的簽章與 §4.4 逐字相同**
  ——校準時已用 `diff` 對過，實作時照抄 §4.4 就會結構相符（Protocol 是結構型別，不必繼承）。

### 2.2 開工基線（實查）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

pytest -q
# 預期尾巴：624 passed，0 skipped
#（543 增量五基線 ＋ Phase 74〜81 實際落地的 81 顆）
# 📌 2026-09-02 實查：624。總覽 §2.2／§2.7／§9 寫的 616 是「當初規劃的」數字；
#    Phase 75／79／81 實作時各自的 code review 裁決多補了幾顆守門測試
#    （總覽 §2.2 的 Phase 81 那列已註記「實 624」）。
#    ⚠ 對顆數時**只對「本 phase 新增幾顆」**，不要對絕對數字。

# Phase 77 留下的契約要在（本 phase 會 import 它）
grep -n "class MailboxMessage" app/services/cloud_ingest.py
grep -n "class CloudMailbox" app/services/cloud_ingest.py
# 預期：兩行都命中

# 現在還沒有 boto3（本 phase 才加）
grep -c "boto3" requirements.txt        # 預期：0
python -c "import boto3" 2>&1 | tail -1 # 預期：ModuleNotFoundError: No module named 'boto3'
```

> ⚠️ **絕對不要同時跑兩份 pytest。** 兩份會互相 `TRUNCATE` 同一個測試庫，
> 症狀是**大量看似隨機的 404** 與 `TypeError: 'NoneType' object is not subscriptable`，
> 每次紅的顆數還不一樣——看起來像程式壞了，其實只是撞在一起。

### 2.3 本 phase 對顆數的影響

**+16 顆，與總覽 §2.7／§9／§10.2 J 一致（總覽已吸收這一顆）。**
第 16 顆 `test_get_object拿得回位元組而delete_objects送出鍵清單` 是總覽 §10.2 追認項 J
補進來的成功路徑測試（理由見 §8）；**不是**「比總覽多 1 顆」，不要再往上加。
開工基線 **624**（2026-09-02 實查）→ 收工 **640**。

> 📌 **2026-09-02 review fix wave 之後是 +17**（本檔這一顆之外，Phase 86 的 fix 另加一顆，
> 全量到 **644**）：review 裁決補了 `test_put_object與send失敗時例外原樣往外丟`
> ——它是唯一會在有人把 `put_object`／`send_job`／`send_result` 包成 try/except 時變紅的測試。
> 詳見 §8 的 fix wave 那一行。

> 📌 **為什麼不是總覽寫的 616 → 632：** 那兩個數字是規劃階段算的，
> 而 Phase 75／79／81 實作時各自的 code review 裁決多補了幾顆守門測試
> （總覽 §2.2 的 Phase 81 那列已註記「實 **624**」）。
> **本 phase 的 +16 一顆都沒變**，變的只是絕對值。
> Phase 84／85 都是 +0，所以 Phase 86 開工基線是 **640**、收工 **642**。

---

## 3. 範圍

### 做

1. `requirements.txt` 加 `boto3>=1.35`（本增量**唯一**的新套件）。
   實作者只負責 host 的 `.venv`（`uv pip install -r requirements.txt`）；
   **重建映像由 controller 親自執行**（2026-09-02 裁決 R3，見 §4.1）。
2. 新建 `tests/unit/test_aws_mailbox_unit.py`（16 顆，含一顆掃碼），**先寫、先跑紅**。
3. 新建 `app/services/aws_mailbox.py`：`AwsMailbox` 的十四個方法。
4. **改**一顆既有測試：`tests/integration/test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存`
   ——把 `boto3` 從禁止清單移除，並**反過來**釘住「boto3 必須在」；
   `s3fs`／`minio`／`google-cloud-storage`／`flower` **仍然禁止**。
5. 全量回歸 ＋ **三個死埠一起指**的零依賴實證。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在 `AwsMailbox` 裡加重試／backoff／連線池 | 重試的語意屬於上一層：本機端由 `gated_ingest` 的 fallback 處理（D10），工人端由 `config.VLM_MAX_ATTEMPTS` 的迴圈處理。這裡多做一層會讓「到底試了幾次」變成沒有人說得清的事 |
| 在 `AwsMailbox` 裡吞掉 `put_object`／`send_message` 的例外 | design6 §8 第 4 列要的是「**fallback**」，不是「安靜地當作成功」。例外一定要往外丟，`gated_ingest` 才知道要走 `fallback=local reason=submit_failed` |
| 讓 `delete_objects` 失敗時往外丟 | **只有它例外**：清理是「盡力」（design6 §2.1 明文）。清不掉最多留下兩天後會被 Lifecycle 掃掉的殘骸，不該因此把一筆已經成功的入庫搞成失敗 |
| 用 `moto`／`localstack`／`pytest-localstack` | 本專案只用到八個 API，手寫 stub 更好讀、更好斷言，也少一個要裝要升級的相依 |
| 在本檔用 `head_object` 判斷「結果寫好了沒」 | design6 §1.2 第 4 列**已否決**輪詢方案 A。完成訊號一律是 results 佇列的訊息（D9） |
| 一次收多則訊息（`MaxNumberOfMessages > 1`） | 一次一則，邏輯最單純。多則會帶出「拿了三則只做完一則、另外兩則的可見度怎麼辦」的麻煩 |
| 建 bucket／建佇列／刪佇列的方法 | **那些是人做的事**（Phase 84／85 的 CLI 指令，而且 2026-09-02 裁決 R3 明訂由 controller 親自打），而且 `personaldocai-mac-policy` 根本沒給那些權限（`docs/plan/finish/phase-82-AWS帳號與工具.md` §4.6.1；Phase 82 已歸檔） |
| 改 `app/services/cloud_ingest.py` | 那是 Phase 77／79／80 的檔。本 phase 只**用**它的 `MailboxMessage`，一個字都不改。⚠ 它自己也有一個 `MAX_WAIT_SECONDS = 20`（`app/services/cloud_ingest.py:61`，給 `_poll_wait_seconds()` 用）——本檔會**再定義一個同名常數**，那是刻意的：兩層各自夾一次，`aws_mailbox` 不必相信呼叫端有夾過。不要為了「去重複」把其中一個改成 import 另一個（那會讓 `cloud_worker` 那台 EC2 上的模組多一條相依） |
| 改 `app/services/staging_service.py` | 本檔的 `INPUT_EXTENSIONS` 與它的 `STAGING_EXTENSIONS`（`app/services/staging_service.py:51`）三個鍵值**逐字相同**，但兩者是**不同的契約**：那邊是「本機暫存檔叫什麼」，這邊是「S3 物件叫什麼」。不要把其中一邊改成 import 另一邊——理由同上（`cloud_worker` 不該為了副檔名表把 `config`／`DATA_DIR` 那一串拉進 EC2）。§4.2 的 `test_input_key依content_type給副檔名` 把三對值逐字釘死，漂移會當場紅 |
| 改 `app/dependencies.py` | `get_cloud_route()` 的 `assume` 分支是 **Phase 86**。本 phase 做完之後 `AwsMailbox` **還沒有任何人呼叫** |
| 改 `compose.yaml` | 本增量零改動（總覽 §7 鐵律 11）。AWS 設定全部走 `.env` |
| 改端點、改前端、改資料庫 | 端點恆 22、前端零改動、`photo` 表零改動 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 2 先把 16 顆測試寫好、**真的跑它、親眼看到紅**；
> 步驟 4 才寫實作讓它轉綠。「跑它確認紅」不可以跳過——沒看過紅的測試，
> 你不知道它有沒有在測東西。

### 4.1 `requirements.txt` 加 `boto3`，host 裝上（映像由 controller 重建）

- [x] 打開 `/Users/linjunting/personalDocAI/requirements.txt`，在
      「`# --- 佇列（增量五 design5.md D5：非同步入庫）---`」那一段的**後面**、
      「`# --- 設定 ---`」的**前面**插入：

```text
# --- AWS（增量六 design6.md：S3 當寄物櫃、SQS 當兩條佇列）---
boto3>=1.35               # AWS 的官方 Python 套件（S3／SQS／EC2 Describe 三個服務）
                          # ★ 全系統**只有** app/services/aws_mailbox.py 可以 import 它
                          #   （tests/unit/test_aws_mailbox_unit.py 有一顆掃碼測試釘住）
                          # ⚠ 改完這一行之後一定要重建映像，否則 worker 容器裡沒有它：
                          #     docker compose -f compose.yaml up -d --build
                          #   症狀會是走雲端路時 ModuleNotFoundError（容器裡根本沒有這個套件）
```

- [x] **host 的 `.venv` 也要裝**（pytest 在 host 跑，而測試檔要 `from botocore.exceptions import ClientError`）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uv pip install -r requirements.txt
python -c "import boto3, botocore; print('boto3', boto3.__version__)"
```

**預期輸出**（版本號一定會不一樣，`1.35` 以上就對；2026-09 實際會裝到 `1.4x`）：

```text
boto3 1.4X.Y
```

> 📌 **下限為什麼還是 `>=1.35`（2026-09-02 重新確認過，保留）：** 本檔只用到八個
> 十年沒變過的 API（`put_object`／`get_object`／`delete_objects`／`send_message`／
> `receive_message`／`delete_message`／`change_message_visibility`／`describe_instances`），
> 下限拉高沒有任何好處，只會讓「裝不起來」多一種可能。
> ⚠ 不要學 `ruff` 那一行加**上限**：ruff 有上限是因為它的 formatter 輸出會隨版本變、CI 會紅；
> boto3 沒有這個問題。

- [x] **重建映像**（app 與 worker 用同一份映像，一次就好）：

> ⚠ **本步驟由 controller 親自執行；實作 subagent 不重建映像**
> （2026-09-02 裁決 R3：容器的建立／重啟這種有外部副作用的動作集中在 controller 眼前做）。
> 實作者做完上面那條 `uv pip install` 就可以直接往下走 §4.2 ——
> 本 phase 的測試全部在 host 跑、而且一個位元組都不出網，映像裡有沒有 boto3 不影響任何一顆。

```bash
docker compose -f compose.yaml up -d --build
docker compose exec worker python -c "import boto3; print('容器裡也有 boto3', boto3.__version__)"
```

**預期輸出：**

```text
容器裡也有 boto3 1.4X.Y
```

> ⚠ **`up -d` 不帶 `--build` 不會重建映像。** 常駐模式的程式在映像裡（不是 bind-mount），
> 少了 `--build` 的話你會看到「host 有 boto3、容器沒有」，
> 而且要等到 Phase 86 真的走雲端路時才爆——那時很難聯想到是這一步漏了。

> 📌 **順手記住 `CLAUDE.md` 已經寫過的落差：** `requirements.txt` 全部是 `>=`（沒有 lock），
> 所以 host 的 `.venv` 與容器裡解析到的版本會慢慢分岔。
> 這代表「重建映像」在本專案要當成**需要手動煙霧一次**的動作
> ——本 phase 的煙霧就是上面那條 `docker compose exec worker python -c ...`。

- [x] **這時候跑一次全量，會看到「一顆紅」——這是預期的**：

```bash
pytest -q
```

**預期輸出**（尾巴）：

```text
FAILED tests/integration/test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存
1 failed, 623 passed
```

錯誤訊息會是：

```text
AssertionError: 不做雲端物件儲存：boto3
assert 'boto3' not in '# --- web 框架 ---\nfastapi>=0.115 ...'
```

**這顆紅是對的、也是必要的**：它證明增量五真的有在守那條禁令。
§4.6 會把它改成新的規則（design6 §1.1 第 1 列已推翻 boto3 那一項）。
**先不要急著改它**——照 TDD 的順序，先把本 phase 的新測試寫完。

---

### 4.2 先寫測試（紅）

- [x] 新建 `/Users/linjunting/personalDocAI/tests/unit/test_aws_mailbox_unit.py`，**整份逐字貼上**：

```python
"""AwsMailbox 的單元測試：全部用手寫的 stub client，**一個位元組都不出網**。

不用 moto／localstack 的理由：本專案只用到八個 API，手寫 stub 更好讀，
也更容易斷言「到底帶了哪些參數」（WaitTimeSeconds 有沒有超過 20、VisibilityTimeout
是不是 0、jobs 與 results 兩條佇列有沒有被寫反）——那才是這一層真正會出錯的地方。

⚠ 這一檔連 boto3 的 client 都不會建立：每顆測試都把三個 client 直接注入建構子。
   pytest 全程不連真 AWS（總覽 §7 鐵律 2）。
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.services.aws_mailbox import AwsMailbox

PROJECT_ROOT = Path(__file__).resolve().parents[2]

JOBS_URL = "https://sqs.example.invalid/jobs"
RESULTS_URL = "https://sqs.example.invalid/results"


def make_client_error(code: str, operation: str) -> ClientError:
    """造一個 boto3 會丟的 ClientError。

    真實的 ClientError 是這樣被建出來的：第一個參數是「AWS 回來的錯誤內容」，
    第二個參數是「哪一個 API」。錯誤代碼要放在 response["Error"]["Code"]——
    aws_mailbox.get_object() 就是讀這個位置決定「回 None 還是往外丟」。
    """
    return ClientError({"Error": {"Code": code, "Message": "測試用"}}, operation)


class StubS3:
    """長得像 boto3 S3 client 的最小假件：記下呼叫參數、回可控的結果。"""

    def __init__(
        self,
        *,
        get_body: bytes | None = None,
        get_error=None,
        delete_error=None,
        delete_errors: list[dict] | None = None,
    ):
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self._get_body = get_body
        self._get_error = get_error
        self._delete_error = delete_error  # 整個請求炸掉（丟例外）
        self._delete_errors = delete_errors  # 請求成功但某幾個 key 刪不掉（回應裡的 Errors）

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        if self._get_error is not None:
            raise self._get_error
        # 真的 S3 回來的 Body 是一個「像檔案的物件」，要 .read() 才拿得到位元組。
        # 這裡用 BytesIO 模擬同一個介面——實作端因此不會寫出「直接把 Body 當 bytes 用」的錯。
        return {"Body": io.BytesIO(self._get_body or b"")}

    def delete_objects(self, **kwargs):
        self.delete_calls.append(kwargs)
        if self._delete_error is not None:
            raise self._delete_error
        # 真 S3 的回應長相：部分失敗也是 HTTP 200，失敗的 key 列在 Errors、成功的列在 Deleted
        if self._delete_errors:
            return {"Errors": list(self._delete_errors)}
        return {"Deleted": [{"Key": obj["Key"]} for obj in kwargs["Delete"]["Objects"]]}


class StubSqs:
    """長得像 boto3 SQS client 的最小假件。

    messages 是一串「還沒被領走的訊息」，每次 receive_message 領走最前面那一則；
    領完了就回一個**沒有 Messages 這個鍵**的字典——這正是真 SQS 的行為
    （不是回空清單，是根本沒有那個鍵），實作端必須用 .get("Messages") 才不會 KeyError。
    """

    def __init__(self, *, messages: list[dict] | None = None):
        self.send_calls: list[dict] = []
        self.receive_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.visibility_calls: list[dict] = []
        self._messages = list(messages or [])

    def send_message(self, **kwargs):
        self.send_calls.append(kwargs)
        return {}

    def receive_message(self, **kwargs):
        self.receive_calls.append(kwargs)
        if not self._messages:
            return {"ResponseMetadata": {}}
        return {"Messages": [self._messages.pop(0)]}

    def delete_message(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}

    def change_message_visibility(self, **kwargs):
        self.visibility_calls.append(kwargs)
        return {}


class StubEc2:
    """長得像 boto3 EC2 client 的最小假件（只有 describe_instances）。"""

    def __init__(self, *, reservations: list[dict] | None = None, error=None):
        self.calls: list[dict] = []
        self._reservations = reservations if reservations is not None else []
        self._error = error  # 設了就一律丟這個例外（模擬 InvalidInstanceID.NotFound 等）

    def describe_instances(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Reservations": self._reservations}


def make_mailbox(*, s3=None, sqs=None, ec2=None) -> AwsMailbox:
    """建一個全部用 stub 的 AwsMailbox。bucket 與兩條佇列都是假的（不會被真的連上）。"""
    return AwsMailbox(
        bucket="test-bucket",
        jobs_queue_url=JOBS_URL,
        results_queue_url=RESULTS_URL,
        region="ap-northeast-1",
        s3=s3 if s3 is not None else StubS3(),
        sqs=sqs if sqs is not None else StubSqs(),
        ec2=ec2 if ec2 is not None else StubEc2(),
    )


# ---------- 三個鍵名（design6 §2.2 的契約）----------


def test_input_key依content_type給副檔名():
    """三種格式各對到一個副檔名。工人那端是**看副檔名**反推 content_type 的
    （總覽 §2.6 第 4 步），所以這張對照表是雙向契約。

    ⚠ 這三對值與 app/services/staging_service.py 的 STAGING_EXTENSIONS 逐字相同
      （tests/fakes.FakeMailbox 的 input_key 用的就是那一份）。兩邊是**不同的契約**、
      刻意各留一份定義；本顆與 test_cloud_ingest_unit.py::test_input鍵名依content_type決定副檔名
      各自把值釘死，所以漂移一定會被抓到。
    """
    mailbox = make_mailbox()

    assert mailbox.input_key("job-1", "image/jpeg") == "documents/job-1/input.jpg"
    assert mailbox.input_key("job-1", "image/png") == "documents/job-1/input.png"
    assert mailbox.input_key("job-1", "application/pdf") == "documents/job-1/input.pdf"


def test_context_key與result_key的路徑():
    """三個物件全部住在 documents/{job_id}/ 底下。這是 Lifecycle 能生效的前提：
    Phase 84 的清潔規則掛在 documents/ 前綴上，鍵名跑掉那把掃把就掃不到。
    """
    mailbox = make_mailbox()

    assert mailbox.context_key("job-1") == "documents/job-1/context.json"
    assert mailbox.result_key("job-1") == "documents/job-1/result.json"


# ---------- S3 ----------


def test_put_object帶ContentType():
    """四個參數都要對。ContentType 不是可有可無：少了它 S3 會存成
    application/octet-stream，用瀏覽器看時變成「下載檔案」而不是「顯示圖片」。
    """
    s3 = StubS3()
    mailbox = make_mailbox(s3=s3)

    mailbox.put_object("documents/job-1/input.png", b"PNGDATA", "image/png")

    assert len(s3.put_calls) == 1
    call = s3.put_calls[0]
    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == "documents/job-1/input.png"
    assert call["Body"] == b"PNGDATA"
    assert call["ContentType"] == "image/png"


def test_get_object拿得回位元組而delete_objects送出鍵清單():
    """S3 的兩條成功路徑：讀得回東西、刪得掉東西。

    ★ 這一顆是總覽 §10.2 追認項 J 特別補進來的成功路徑測試（理由見計畫 §8）。
      沒有它的話，一個「get_object 永遠 return None」的實作會讓其他 15 顆全綠——
      而 get_object 正是「把雲端算好的 result.json 拿回家」的那一步，
      壞掉的話整條雲端路會安靜地每次都逾時 fallback，看起來像 AWS 慢，其實是程式錯。
    """
    s3 = StubS3(get_body=b'{"job_id": "job-1"}')
    mailbox = make_mailbox(s3=s3)

    content = mailbox.get_object("documents/job-1/result.json")

    assert content == b'{"job_id": "job-1"}'
    assert s3.get_calls[0]["Bucket"] == "test-bucket"
    assert s3.get_calls[0]["Key"] == "documents/job-1/result.json"

    mailbox.delete_objects(
        [
            "documents/job-1/input.png",
            "documents/job-1/context.json",
            "documents/job-1/result.json",
        ]
    )

    assert len(s3.delete_calls) == 1
    assert s3.delete_calls[0]["Bucket"] == "test-bucket"
    assert s3.delete_calls[0]["Delete"] == {
        "Objects": [
            {"Key": "documents/job-1/input.png"},
            {"Key": "documents/job-1/context.json"},
            {"Key": "documents/job-1/result.json"},
        ]
    }


def test_get_object遇到NoSuchKey回None():
    """「還沒寫好」是**正常狀態**，翻譯成 None、不是例外。

    誰會踩到：崩潰重送時的 fetch_result()（總覽 §2.5）、工人的冪等檢查
    （總覽 §2.6 第 1 步）——兩處的「不在」都是最常見的情況。
    """
    s3 = StubS3(get_error=make_client_error("NoSuchKey", "GetObject"))
    mailbox = make_mailbox(s3=s3)

    assert mailbox.get_object("documents/job-1/result.json") is None
    assert len(s3.get_calls) == 1


def test_get_object遇到其他錯誤照樣往外丟():
    """AccessDenied 是**真的壞了**，不可以偽裝成「檔案不在」。
    偽裝的後果：權限設錯時每一筆都安靜地逾時 fallback，你會以為是 AWS 慢，
    永遠查不到其實是 IAM policy 少了一行。
    """
    s3 = StubS3(get_error=make_client_error("AccessDenied", "GetObject"))
    mailbox = make_mailbox(s3=s3)

    with pytest.raises(ClientError):
        mailbox.get_object("documents/job-1/result.json")


def test_delete_objects失敗只記log不往外丟(caplog):
    """清理是**盡力**（design6 §2.1 明文）：刪不掉最多留殘骸，而殘骸兩天後會被
    Lifecycle 掃掉。往外丟的話會變成「照片已經入庫卻因為清不掉垃圾而標 failed」。

    S3 的「刪不掉」有**兩種長相**，兩種都要只 warning：
      ① 整個請求被拒（丟 ClientError）——例如 bucket 名打錯、整個 bucket 碰不到；
      ② 請求成功（HTTP 200）但某幾個 key 刪不掉——DeleteObjects 是批次 API，
         它把失敗的 key 列在回應的 Errors 裡、**不丟例外**。這是最容易漏掉的一種：
         IAM 少了 s3:DeleteObject 時看起來就是「沒事」，殘骸卻一直留著。
    """
    # ① 整個請求炸掉
    s3 = StubS3(delete_error=make_client_error("AccessDenied", "DeleteObjects"))
    mailbox = make_mailbox(s3=s3)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        mailbox.delete_objects(["documents/job-1/input.png"])  # 不可以炸

    assert len(s3.delete_calls) == 1
    assert "刪 S3 物件失敗" in caplog.text

    # ② HTTP 200，但 Errors 裡列了刪不掉的 key
    caplog.clear()
    failed_key = {"Key": "documents/job-1/input.png", "Code": "AccessDenied", "Message": "測試用"}
    s3_2 = StubS3(delete_errors=[failed_key])
    mailbox2 = make_mailbox(s3=s3_2)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        mailbox2.delete_objects(["documents/job-1/input.png"])  # 一樣不可以炸

    assert len(s3_2.delete_calls) == 1
    assert "刪 S3 物件失敗" in caplog.text
    assert "documents/job-1/input.png" in caplog.text, "要印出是哪個 key 刪不掉"


# ---------- SQS：jobs（本機 Send、工人 Receive／Delete）----------


def test_send_job的body恰兩鍵():
    """design6 §2.3：jobs 的 body 只有 job_id 與 s3_key。

    最後一條斷言守的是 §0 **禁止第 2 條**：佇列裡永遠只有字串，
    一個影像位元組都沒有。SQS 單則上限是 1 MiB（結論不變：影像仍不進 SQS——
    多頁 PDF 幾十 MB 放不下，而且放得下也不准放）。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.send_job("job-1", "documents/job-1/input.jpg")

    assert len(sqs.send_calls) == 1
    assert sqs.send_calls[0]["QueueUrl"] == JOBS_URL
    body = json.loads(sqs.send_calls[0]["MessageBody"])
    assert body == {"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}
    assert set(body) == {"job_id", "s3_key"}
    assert all(isinstance(value, str) for value in body.values())


def test_receive_job的等待秒數不超過20():
    """長輪詢上限就是 20 秒，填超過 SQS 直接拒絕。呼叫端（Phase 80 的 wait_result）
    傳進來的是「還剩幾秒」，動輒 300，所以夾在這一層最安全。
    """
    sqs = StubSqs(
        messages=[
            {
                "Body": json.dumps({"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}),
                "ReceiptHandle": "rh-jobs-1",
            }
        ]
    )
    mailbox = make_mailbox(sqs=sqs)

    message = mailbox.receive_job(300)

    assert sqs.receive_calls[0]["QueueUrl"] == JOBS_URL
    assert sqs.receive_calls[0]["WaitTimeSeconds"] == 20
    assert sqs.receive_calls[0]["MaxNumberOfMessages"] == 1
    assert message is not None
    assert message.job_id == "job-1"
    assert message.s3_key == "documents/job-1/input.jpg"
    assert message.receipt_handle == "rh-jobs-1"


def test_receive_job沒訊息時回None(caplog):
    """「拿不到一則可用的訊息」有三種長相，全部回 None、都不丟例外：
      ① 佇列是空的（常態）——順便釘住「真 SQS 空的時候回的字典裡根本沒有 Messages
         這個鍵」，寫成 回應["Messages"] 會 KeyError；
      ② 拿到一則 body 不是 JSON 的壞紙條；
      ③ 拿到一則是 JSON、但沒有 job_id 的壞紙條。
    ②③ 除了回 None，還要**用手上的 receipt handle 直接把它刪掉**並留一行 warning：
    呼叫端拿不到 handle 就刪不掉它，留著只會每次可見度到期就回來一次（jobs 900 秒），
    直到 4 天保留期滿——總覽 §10.2 追認項 K 的「壞紙條」在這一層就先擋掉。
    """
    # ① 空佇列
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    assert mailbox.receive_job(20) is None
    assert len(sqs.receive_calls) == 1
    assert sqs.delete_calls == []  # 沒東西可刪

    # ② 不是 JSON、③ 沒有 job_id：各自回 None，而且那一則要被刪掉（用對的佇列＋對的把手）
    sqs2 = StubSqs(
        messages=[
            {"Body": "這不是 JSON", "ReceiptHandle": "rh-bad-1"},
            {"Body": json.dumps({"s3_key": "documents/x/input.jpg"}), "ReceiptHandle": "rh-bad-2"},
        ]
    )
    mailbox2 = make_mailbox(sqs=sqs2)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        assert mailbox2.receive_job(20) is None
        assert mailbox2.receive_job(20) is None

    assert sqs2.delete_calls == [
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-bad-1"},
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-bad-2"},
    ]
    assert caplog.text.count("認不得的訊息") == 2


def test_delete_job_message帶receipt_handle():
    """刪訊息要用 receipt handle，而且**兩條佇列不可以寫反**。

    寫反的症狀最惡劣而且不報錯：刪到別人的 results 訊息（那筆只能逾時 fallback），
    自己的 jobs 訊息沒刪掉，可見度到期又冒出來 → 同一張圖被看兩次。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.delete_job_message("rh-jobs")
    mailbox.delete_result_message("rh-results")

    assert sqs.delete_calls == [
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-jobs"},
        {"QueueUrl": RESULTS_URL, "ReceiptHandle": "rh-results"},
    ]


# ---------- SQS：results（工人 Send、本機 Receive／Delete／改可見度）----------


def test_send_result的body恰一鍵():
    """design6 §2.3：results 的 body 只有 job_id。不順便帶 result 的 key，
    是因為本機自己算得出來（result_key(job_id)），多一個欄位就多一種不一致。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.send_result("job-7")

    assert len(sqs.send_calls) == 1
    assert sqs.send_calls[0]["QueueUrl"] == RESULTS_URL
    body = json.loads(sqs.send_calls[0]["MessageBody"])
    assert body == {"job_id": "job-7"}
    assert set(body) == {"job_id"}
    assert all(isinstance(value, str) for value in body.values())


def test_release_result_message把可見度改成0():
    """「這則不是我的，馬上還回去給它的主人」＝ ChangeMessageVisibility 改成 0。

    results 是一條**共用**佇列（總覽 §10.1 追認項 d）：兩筆 job 同時在等的時候，
    你一定會收到別人的訊息。不還回去的話，別人就要等到可見度逾時（30 秒）才拿得到，
    而那 30 秒很可能已經超過它的 deadline → 它會白白 fallback。

    順便釘住 results 佇列的 body 只有 job_id、沒有 s3_key（所以 s3_key 是 None）。
    """
    sqs = StubSqs(messages=[{"Body": json.dumps({"job_id": "job-9"}), "ReceiptHandle": "rh-9"}])
    mailbox = make_mailbox(sqs=sqs)

    message = mailbox.receive_result(5)

    assert message is not None
    assert message.job_id == "job-9"
    assert message.s3_key is None
    assert sqs.receive_calls[0]["QueueUrl"] == RESULTS_URL
    assert sqs.receive_calls[0]["WaitTimeSeconds"] == 5

    mailbox.release_result_message(message.receipt_handle)

    assert len(sqs.visibility_calls) == 1
    assert sqs.visibility_calls[0] == {
        "QueueUrl": RESULTS_URL,
        "ReceiptHandle": "rh-9",
        "VisibilityTimeout": 0,
    }


# ---------- EC2（Phase 89 的 Ec2Probe 會用它）----------


def test_instance_state讀得到狀態名():
    """狀態藏在兩層底下：Reservations[0].Instances[0].State.Name（AWS 的歷史包袱：
    一次 run-instances 可以開好幾台，那一批叫一個 reservation）。本專案只問一台。
    """
    ec2 = StubEc2(reservations=[{"Instances": [{"State": {"Name": "running"}}]}])
    mailbox = make_mailbox(ec2=ec2)

    assert mailbox.instance_state("i-0123456789abcdef0") == "running"
    assert ec2.calls[0]["InstanceIds"] == ["i-0123456789abcdef0"]


def test_instance_state查無回unknown():
    """查不到那台機器時回字串 "unknown"，不回 None、也不丟例外。

    ★ 「查無」在 AWS 是一個**錯誤**、不是空清單：對不存在的 instance id
      （打錯、或 Terminate 超過一小時）DescribeInstances 丟 ClientError，
      代碼 InvalidInstanceID.NotFound——這才是 Phase 92 換機器之後最常見的情況。
      空的 Reservations 只會發生在「那台機器不是你的」（AWS 默默不列出來）。

    回 "unknown" 的好處：Phase 89 的 Ec2Probe 只需要判斷 == "running"，
    任何其他字串都自然變成「不可用 → fallback」，不必再多寫一條 None 的分支。
    """
    # 情況一：AWS 說「沒有這台」（最常見的查無）
    not_found = make_client_error("InvalidInstanceID.NotFound", "DescribeInstances")
    mailbox = make_mailbox(ec2=StubEc2(error=not_found))
    assert mailbox.instance_state("i-0123456789abcdef0") == "unknown"

    # 情況二：回應是空的（那台機器不是你的，AWS 默默不列）
    mailbox2 = make_mailbox(ec2=StubEc2(reservations=[]))
    assert mailbox2.instance_state("i-0123456789abcdef0") == "unknown"

    # 情況三：有 reservation 但裡面沒有 instance（AWS 偶爾會這樣回）
    mailbox3 = make_mailbox(ec2=StubEc2(reservations=[{"Instances": []}]))
    assert mailbox3.instance_state("i-0123456789abcdef0") == "unknown"

    # 反面：「查無」以外的錯誤（例如權限不足）照樣往外丟——
    # Phase 89 的 Ec2Probe 會接住它變成 False，並把真正的原因寫進 log
    unauthorized = make_client_error("UnauthorizedOperation", "DescribeInstances")
    mailbox4 = make_mailbox(ec2=StubEc2(error=unauthorized))
    with pytest.raises(ClientError):
        mailbox4.instance_state("i-0123456789abcdef0")


# ---------- 掃碼：boto3 只准出現在這一個檔 ----------


def test_boto3只在aws_mailbox裡出現():
    """總覽 §7 鐵律 5：全系統只有 app/services/aws_mailbox.py 可以 import boto3／botocore。

    為什麼這條規則值得一顆測試守著：
      ① cloud_ingest.py 只認 CloudMailbox 這個 Protocol，所以它的測試才能用假信箱跑；
         哪天有人「順手」在那裡 import boto3，第五道安全網（AWS_ENDPOINT_URL 指死埠）
         就從「保險」退化成「唯一的防線」。
      ② app/workers/cloud_worker.py（Phase 87）也一樣——它拿到的是別人建好的信箱。

    ★ 用**正規表示式**比對而不是 `"import boto3" in 原始碼`：
      別的檔案的中文註解本來就會提到「不要 import boto3」這幾個字，
      用子字串比對會一直誤中，最後大家只好把註解改成暗語——那比沒有測試還糟。
      這個樣式只認「行首（允許縮排）的 import／from 陳述句」，
      所以連寫在函式裡面的延遲 import 也抓得到。
    """
    import_pattern = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)

    offenders = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        if path.name == "aws_mailbox.py":
            continue
        if import_pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == [], (
        f"只有 app/services/aws_mailbox.py 可以 import boto3／botocore：{offenders}"
    )

    # 反過來也釘一次：那個檔**必須**真的 import 了（不然這顆測試會變成永遠綠的裝飾品）
    mailbox_source = (PROJECT_ROOT / "app" / "services" / "aws_mailbox.py").read_text(
        encoding="utf-8"
    )
    assert import_pattern.search(mailbox_source), "aws_mailbox.py 應該要 import boto3"
```

---

### 4.3 跑它，確認是紅的

- [x] 執行：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_aws_mailbox_unit.py -q
```

**預期輸出**（收集階段就爆，因為模組還不存在）：

```text
ERROR tests/unit/test_aws_mailbox_unit.py
E   ModuleNotFoundError: No module named 'app.services.aws_mailbox'
```

看到這一行就對了。**看不到紅就不要往下做**——那代表你的檔案沒被 pytest 收集到
（最常見的原因：檔名沒有以 `test_` 開頭，或存錯目錄）。

---

### 4.4 實作（綠）

```text
┌─ ⚠ `MailboxMessage` 定義在哪裡：**不要在本檔另外定義一份** ──────────────────┐
│                                                                              │
│ 它住在 `app/services/cloud_ingest.py`（Phase 77 建的），本檔只是 import 來用。│
│                                                                              │
│ 為什麼是那裡：Phase 77 比本 phase **早**。那時候                              │
│   ・`cloud_ingest.CloudMailbox` 這個 Protocol 的簽章就要寫出這個型別          │
│   ・`tests/fakes.FakeMailbox` 也要回傳這個型別                                │
│ 而那時 `aws_mailbox.py` 還不存在。反過來（定義在本檔、cloud_ingest 來 import）│
│ 會讓所有流程測試都被迫載入 boto3，第五道安全網就沒意義了（總覽 §7 鐵律 5）。   │
│                                                                              │
│ ⛔ **絕對不要**因為「import 不到」就在本檔複製一份 dataclass：                │
│    兩份同名不同源的 dataclass 會讓 `isinstance` 與相等比較全部失效，          │
│    而且**不會報錯**——工人端組出來的訊息本機端認不得，安靜地每次都逾時。      │
│    真的 import 不到，就是 Phase 77 沒做完或名字不同，回去對總覽 §2.4.1。      │
└──────────────────────────────────────────────────────────────────────────────┘
```

- [x] 新建 `/Users/linjunting/personalDocAI/app/services/aws_mailbox.py`，**整份逐字貼上**：

```python
"""AwsMailbox：把 AWS 的 S3 ＋ 兩條 SQS 佇列 ＋ EC2 狀態查詢包成十四個方法。

★ **全系統唯一 import boto3／botocore 的地方**（總覽 §7 鐵律 5；
  tests/unit/test_aws_mailbox_unit.py::test_boto3只在aws_mailbox裡出現 掃碼釘住）。

【這一層有多薄】
它幾乎沒有邏輯：組鍵名、把參數擺對位置、把 AWS 的回應形狀翻成 Python 好用的東西。
「什麼時候送、等多久、逾時怎麼辦」在 app/services/cloud_ingest.py；
「看幾次圖、失敗怎麼算」在 app/workers/cloud_worker.py 與 app/services/gated_ingest.py。
這裡只做一件事：**忠實地打 API**。

【只有這四種情況不照實往外丟，其餘一律往外丟】
  1. get_object 遇到 NoSuchKey／404 → 回 None（「還沒寫好」是正常狀態，不是壞掉）
     ⚠ 前提是 IAM policy 有給 s3:ListBucket——沒有的話 S3 對不存在的 key 回的是
       403 AccessDenied 而不是 404，這裡就會往外丟（刻意不把 AccessDenied 當「不在」）
  2. delete_objects 失敗 → 只 logger.warning（清理是「盡力」，design6 §2.1 明文；
     清不掉的殘骸兩天後由 S3 Lifecycle 掃掉）。「失敗」有兩種長相：整個請求丟例外、
     或請求成功但回應的 Errors 裡列了刪不掉的 key——兩種都只 warning
  3. instance_state 查無 → 回 "unknown"（讓呼叫端只需要判斷 == "running"）。
     「查無」＝ InvalidInstanceID.NotFound 這個錯誤代碼、或空的 Reservations
  4. receive_job／receive_result 拿到壞紙條（body 不是 JSON、或沒有 job_id）→
     logger.warning ＋ 用 receipt handle 直接刪掉 ＋ 回 None（總覽 §10.2 追認項 K）。
     呼叫端拿不到 handle 就刪不掉它，留著會每次可見度到期就回來一次、回 4 天
其他任何錯誤（AccessDenied、沒有憑證、連不上）都**原樣往外丟**——
上一層要靠它們決定 fallback（design6 D10、§8 錯誤表第 3／4 列）。
安靜地吞掉會變成「每一筆都逾時，你以為 AWS 慢，其實是 IAM 少一行」。

【它不做的事】
不建 bucket、不建佇列、不刪佇列、不列 bucket 內容（那些是人做的事，
personaldocai-mac-policy 也沒給那些權限）；不重試、不做 backoff、不管連線池。
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from app.services.cloud_ingest import MailboxMessage

logger = logging.getLogger(__name__)

# 所有物件都住在這個前綴底下。Phase 84 的 Lifecycle 清潔規則也是掛在它上面，
# 兩邊必須一致——鍵名跑掉的話那把掃把就掃不到殘骸。
KEY_PREFIX = "documents"

# content_type -> input 物件的副檔名。
# ★ 工人那端是**看副檔名**反推 content_type 的（總覽 §2.6 第 4 步），這張表是雙向契約。
# ⚠ 三對值與 app/services/staging_service.py 的 STAGING_EXTENSIONS 逐字相同，
#   但**刻意各留一份**：那邊管的是「本機暫存檔叫什麼」（會拉進 config／DATA_DIR），
#   這邊管的是「S3 物件叫什麼」，而本模組之後要被 EC2 上的 cloud_worker import
#   （Phase 87；那台機器沒有資料庫也沒有 data/）。不要為了去重複改成 import 那一份。
#   漂移的防線是測試：本 phase 的 test_input_key依content_type給副檔名 與
#   既有的 test_cloud_ingest_unit.py::test_input鍵名依content_type決定副檔名 各把值釘死。
INPUT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}

# SQS 長輪詢的硬上限（AWS 規定就是 20 秒，填更大會被拒絕）。
# 夾在這一層而不是要求每個呼叫端自己記得：wait_result 傳進來的是「還剩幾秒」，
# 那個數字動輒 300。
# ⚠ app/services/cloud_ingest.py 也有一個同名同值的常數（它的 _poll_wait_seconds 用）。
#   **兩層各夾一次是刻意的**：這一層不必相信呼叫端夾過（Phase 87 的 cloud_worker
#   直接呼叫 receive_job()，走的根本不是 cloud_ingest 那條路）。不要改成互相 import。
MAX_WAIT_SECONDS = 20

# get_object 遇到這兩個錯誤代碼時翻譯成 None。
# 為什麼有兩個：GetObject 回的是 NoSuchKey，而 HeadObject 之類的 API 回的是 "404"。
# 本專案只用 GetObject，但多認一個字串不花成本，也省掉日後換 API 時的意外。
MISSING_KEY_CODES = ("NoSuchKey", "404")

# instance_state 遇到這個錯誤代碼時翻譯成 "unknown"。
# ★ 「查無這台機器」在 AWS 是一個**錯誤**、不是空清單：DescribeInstances 對不存在
#   （或 Terminate 超過一小時）的 instance id 丟 ClientError，代碼 InvalidInstanceID.NotFound。
#   空的 Reservations 只會發生在「那台機器不是你的」（AWS 默默不列出來）——兩種都算查無。
#   其他代碼（id 格式打錯的 InvalidInstanceID.Malformed、沒權限的 UnauthorizedOperation）
#   照樣往外丟：那些是設定或權限真的錯了，讓 Phase 89 的 Ec2Probe 把原因寫進 log 才好查。
UNKNOWN_INSTANCE_CODES = ("InvalidInstanceID.NotFound",)


class AwsMailbox:
    """本機端與工人端共用的「寄物櫃 ＋ 兩條佇列」實作（design6 D8／D9）。

    三個 client 都可以從外面注入（s3／sqs／ec2 參數）——單元測試就是靠這個塞 stub，
    所以那一整檔測試連一次網路都不會碰。不注入時才自己建，而且
    **region 一律明傳**（不靠環境變數猜；猜錯區的症狀是「東西建好了卻找不到」）。

    ⚠ 建立 boto3 client **不會連線、也不會驗證憑證**——沒有憑證時，
      例外是在第一次真的呼叫 API 時才丟出來（NoCredentialsError）。
      這正是我們要的：get_cloud_route() 才不會在組裝階段就炸掉，
      而是讓錯誤發生在 submit() 裡、被 gated_ingest 接住走 fallback（design6 §8 第 3 列）。
    """

    def __init__(
        self,
        *,
        bucket: str,
        jobs_queue_url: str,
        results_queue_url: str,
        region: str,
        s3=None,
        sqs=None,
        ec2=None,
    ) -> None:
        self._bucket = bucket
        self._jobs_queue_url = jobs_queue_url
        self._results_queue_url = results_queue_url
        self._region = region
        self._s3 = s3 if s3 is not None else boto3.client("s3", region_name=region)
        self._sqs = sqs if sqs is not None else boto3.client("sqs", region_name=region)
        self._ec2 = ec2 if ec2 is not None else boto3.client("ec2", region_name=region)

    # ---------- 三個鍵名（design6 §2.2 的契約）----------

    def input_key(self, job_id: str, content_type: str) -> str:
        """本機 Put、工人 Get 的原始檔。

        content_type 不在對照表裡會丟 KeyError——**這是刻意的**：
        上傳端只可能收到那三種（config.ALLOWED_CONTENT_TYPES），真的出現第四種
        代表某處的驗證破了，寧可當場炸給 gated_ingest 接住走 fallback，
        也不要安靜地存成一個沒有副檔名的檔（工人拿到之後會猜不出型別）。
        """
        return f"{KEY_PREFIX}/{job_id}/input{INPUT_EXTENSIONS[content_type]}"

    def context_key(self, job_id: str) -> str:
        """本機 Put、工人 Get 的 prompt 材料（資料夾／實體／糾錯三份清單）。"""
        return f"{KEY_PREFIX}/{job_id}/context.json"

    def result_key(self, job_id: str) -> str:
        """工人 Put、本機 Get 的看圖結果。"""
        return f"{KEY_PREFIX}/{job_id}/result.json"

    # ---------- S3 ----------

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        """把位元組放進寄物櫃。失敗直接往外丟（上一層要靠它決定 fallback）。"""
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def get_object(self, key: str) -> bytes | None:
        """從寄物櫃拿位元組；**東西不在就回 None**（不是例外）。

        「不在」是本專案最常見的正常狀態：崩潰重送時先看看結果在不在、
        工人每次先看看 result.json 在不在做冪等——兩處都不該用例外表達。

        其他錯誤（AccessDenied、沒憑證、連不上）一律原樣往外丟。
        """
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in MISSING_KEY_CODES:
                return None
            raise
        # 真 S3 的 Body 是「像檔案的物件」，一定要 .read() 才是位元組
        return response["Body"].read()

    def delete_objects(self, keys: list[str]) -> None:
        """一次刪掉好幾個物件。**盡力就好**：失敗只留一行 warning，不往外丟。

        理由（design6 §2.1「盡力刪物件」）：這一步永遠是「事情已經做完了、
        順手把垃圾收一收」。刪不掉最多留下殘骸，而殘骸兩天後會被 S3 Lifecycle
        掃掉（Phase 84）。反過來如果往外丟，就會出現「照片明明已經入庫，
        卻因為清不掉一個垃圾檔而被標成 failed」——那糟糕一百倍。
        """
        if not keys:
            return
        try:
            response = self._s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in keys]},
            )
        except Exception as error:  # 刻意攔全部：清理失敗不可以害到主流程
            logger.warning("刪 S3 物件失敗（盡力就好，Lifecycle 兩天後會清）：%s", error)
            return
        # ⚠ DeleteObjects 是「一次刪很多個」的批次 API：某幾個 key 刪不掉時 S3 **不會丟例外**，
        #   而是回 HTTP 200、把失敗的那幾個列在 Errors 裡（每個有 Key／Code／Message）。
        #   不看這個清單的話，IAM 少一行 s3:DeleteObject 會安靜地留下殘骸——一樣只 warning，不炸。
        for failure in response.get("Errors") or []:
            logger.warning(
                "刪 S3 物件失敗（盡力就好，Lifecycle 兩天後會清）：key=%s code=%s message=%s",
                failure.get("Key"),
                failure.get("Code"),
                failure.get("Message"),
            )

    # ---------- SQS：jobs（本機 Send、工人 Receive／Delete）----------

    def send_job(self, job_id: str, s3_key: str) -> None:
        """通知工人「有新工作了」。body 只有兩個字串鍵，一個位元組都沒有。"""
        self._sqs.send_message(
            QueueUrl=self._jobs_queue_url,
            MessageBody=json.dumps({"job_id": job_id, "s3_key": s3_key}),
        )

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None:
        """工人端：拿一則工作。沒有就回 None。"""
        return self._receive(self._jobs_queue_url, wait_seconds)

    def delete_job_message(self, receipt_handle: str) -> None:
        """工人端：這則做完了，把它從 jobs 佇列刪掉。"""
        self._sqs.delete_message(
            QueueUrl=self._jobs_queue_url,
            ReceiptHandle=receipt_handle,
        )

    # ---------- SQS：results（工人 Send、本機 Receive／Delete／改可見度）----------

    def send_result(self, job_id: str) -> None:
        """工人端：result.json **已經放進 S3 之後**才發這則（D9 的順序鐵律）。

        順序反過來的話，本機會被叫醒去拿一個還沒寫完的檔——那是最難查的一種壞法
        （安靜地拿到半截 JSON）。順序由 cloud_worker 保證，這裡只負責發。
        """
        self._sqs.send_message(
            QueueUrl=self._results_queue_url,
            MessageBody=json.dumps({"job_id": job_id}),
        )

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None:
        """本機端：等結果通知。沒有就回 None（呼叫端自己決定要不要再等）。"""
        return self._receive(self._results_queue_url, wait_seconds)

    def delete_result_message(self, receipt_handle: str) -> None:
        """本機端：這則處理完了（不論是我的還是別人留下的殘訊息），刪掉。"""
        self._sqs.delete_message(
            QueueUrl=self._results_queue_url,
            ReceiptHandle=receipt_handle,
        )

    def release_result_message(self, receipt_handle: str) -> None:
        """本機端：「這則不是我的」——可見度改成 0，立刻還回去給它的主人。

        results 是一條**共用**佇列：兩筆 job 同時在等的時候一定會收到別人的訊息。
        不還回去的話，別人要等到可見度逾時（30 秒）才拿得到，
        而那 30 秒很可能已經超過它的 deadline → 它會白白 fallback。
        """
        self._sqs.change_message_visibility(
            QueueUrl=self._results_queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=0,
        )

    # ---------- EC2（Phase 89 的 Ec2Probe 會用它）----------

    def instance_state(self, instance_id: str) -> str:
        """那台工人機現在是什麼狀態：running／stopped／pending／stopping…

        查無就回 "unknown"（不回 None、不丟例外）——呼叫端因此只需要判斷
        `== "running"`，其他任何字串都自然變成「不可用 → fallback」。
        「查無」有兩種長相：AWS 丟 InvalidInstanceID.NotFound（id 打錯、機器已 Terminate
        超過一小時——這是最常見的）、或回空的 Reservations（那台機器不是你的）。
        其他錯誤（UnauthorizedOperation、AuthFailure、連不上）照樣往外丟，
        Phase 89 的 Ec2Probe 會接住它們變成 False 並把原因寫進 log。

        回應結構有兩層是 AWS 的歷史包袱：一次 run-instances 可以開好幾台，
        那一批叫一個 reservation。本專案永遠只問一台，所以固定取 [0][0]。
        """
        try:
            response = self._ec2.describe_instances(InstanceIds=[instance_id])
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in UNKNOWN_INSTANCE_CODES:
                return "unknown"
            raise
        reservations = response.get("Reservations") or []
        if not reservations:
            return "unknown"
        instances = reservations[0].get("Instances") or []
        if not instances:
            return "unknown"
        return instances[0].get("State", {}).get("Name", "unknown")

    # ---------- 內部共用 ----------

    def _receive(self, queue_url: str, wait_seconds: int) -> MailboxMessage | None:
        """兩條佇列共用的收信：一次一則、長輪詢最多 20 秒、body 只解析出字串。

        ⚠ 真 SQS 在「沒有訊息」時回的字典裡**根本沒有 Messages 這個鍵**
          （不是回空清單），所以一定要用 .get() 取。

        ⚠ 壞紙條（body 不是 JSON、或沒有 job_id）在**這一層**就處理掉：warning ＋
          用手上的 receipt handle 直接刪掉 ＋ 回 None（總覽 §10.2 追認項 K）。
          理由：呼叫端連 receipt handle 都拿不到，根本刪不掉它；留著只會每次可見度到期
          就回來一次（jobs 900 秒、results 30 秒），直到 4 天保留期滿。
          會出現壞紙條的情況只有一種：有人用 aws sqs send-message 手動塞了東西。
        """
        response = self._sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=max(0, min(wait_seconds, MAX_WAIT_SECONDS)),
        )
        messages = response.get("Messages") or []
        if not messages:
            return None
        message = messages[0]
        try:
            body = json.loads(message["Body"])
            job_id = body["job_id"]
        except (ValueError, KeyError, TypeError):
            # ValueError＝不是 JSON（json.JSONDecodeError 是它的子類）；
            # KeyError＝是字典但沒有 job_id；TypeError＝是 JSON 但不是字典（例如 123 或清單）
            body, job_id = None, None
        if not isinstance(job_id, str) or not job_id:
            logger.warning(
                "佇列裡有一則認不得的訊息（不是 JSON、或沒有 job_id），直接刪掉：queue=%s body=%r",
                queue_url,
                message.get("Body"),
            )
            self._sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            return None
        return MailboxMessage(
            job_id=job_id,
            s3_key=body.get("s3_key"),
            receipt_handle=message["ReceiptHandle"],
        )
```

---

### 4.5 跑新測試，看它轉綠

- [x] 執行：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_aws_mailbox_unit.py -v
```

**預期輸出**（最後一行）：

```text
16 passed
```

- [x] 確認這 16 顆**真的沒有出網**（把三個死埠一起指上去，顆數要一模一樣）：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest tests/unit/test_aws_mailbox_unit.py -q
```

**預期輸出：** 一樣 `16 passed`（連 boto3 的 client 都沒建立，死埠自然影響不到）。

---

### 4.6 改掉 design5 那顆「不准有 boto3」的掃碼測試

> **這是增量五留下的 543 顆裡唯一被修改的一顆**（總覽 §10.1 追認項 i）。
> 推翻的來源是 **design6 §1.1 第 1 列**：
> 「design5.md §3『不做：雲端物件儲存、S3』→ 僅 NON_SENSITIVE 且遠端可用時，
> S3 當 mailbox；正本仍本機。」
>
> ⚠ **只推翻 `boto3` 那一項。** `s3fs`／`minio`／`google-cloud-storage`／`flower`
> **全部仍然禁止**——design6 沒有推翻它們，而且 D1 明文「S3 **不是**檔案櫃」，
> 那三個套件正好都是「把 S3 當檔案系統或第二個檔案櫃」的用法。

> 📌 **2026-09-02 實查（兩件事，省得你自己找）：**
> ① 那個檔的**檔頭已經有** `import re`（第 30 行，在 `import inspect` 與 `from pathlib import Path` 之間）
>    ——下面這份替換用得到它，**不必再加 import**（加了 ruff 會判重複）。
> ② 目標那顆函式就在**第 426 行**（`def test_沒有背景任務框架的替代品也沒有雲端儲存():`），
>    模組層的 `專案根目錄` 在第 47 行、已經存在。

> ⚠ **這一份替換裡的區域變數刻意維持中文**（`app目錄原始碼`／`需求`／`關鍵字`／`專案根目錄`）。
> 2026-09-02 裁決 R1「識別字一律英文」只套用在**本 phase 新建**的兩個檔
> （`test_aws_mailbox_unit.py`、`aws_mailbox.py`）；`test_design5_error_paths.py` 是增量五留下來的檔，
> 裡面 20 顆測試共用同一套 design5 時代的中文命名。只把這一顆改成英文，
> 會讓同一個檔內兩種命名混在一起——那比全中文更難讀，而且 diff 也會變大。
> **本 phase 對那個檔的改動就只有這一顆函式的函式體，一行都不要多動。**

- [x] 打開 `/Users/linjunting/personalDocAI/tests/integration/test_design5_error_paths.py`，
      找到 `def test_沒有背景任務框架的替代品也沒有雲端儲存():`（**實查在第 426 行**），
      **把整顆函式換成下面這一份**：

```python
def test_沒有背景任務框架的替代品也沒有雲端儲存():
    """§1.2 第 1／2 列＋§3 第 7 列。

    ⚠ 增量六（Phase 83）修改過這一顆：**boto3 從禁止清單移除**。
    來源是 design6.md §1.1 第 1 列，它正式推翻了 design5.md §3 的
    「不做：雲端物件儲存、S3」——改成「僅 NON_SENSITIVE 且遠端可用時，
    S3 當 mailbox（寄物櫃）；正本仍在本機」。

    推翻的**只有 boto3 那一項**，其餘一個字都沒動：
      ・s3fs／minio／google-cloud-storage 仍然禁止——它們是「把 S3 當檔案系統
        或第二個檔案櫃」的用法，而 design6 D1 明文「S3 **不是**檔案櫃、
        不是備份、不是相簿」，正本永遠在這台 Mac 的 Postgres 與 data/。
      ・flower 仍然禁止（design5 §3 第 5 列；design6 沒提到它）。
      ・BackgroundTasks 與「自寫 Redis 消費迴圈」仍然禁止（§1.2 第 1／2 列）。

    另外反過來加一條：boto3 **必須**在 requirements 裡。
    沒有這一條的話，哪天有人「順手清乾淨」把它移掉，整條雲端路會在
    worker 容器裡 ModuleNotFoundError，而 pytest 全綠——那是最難查的落差。
    """
    app目錄原始碼 = "".join(
        檔案.read_text(encoding="utf-8") for 檔案 in sorted((專案根目錄 / "app").rglob("*.py"))
    )
    需求 = (專案根目錄 / "requirements.txt").read_text(encoding="utf-8").lower()

    # §1.2 第 1 列：不用 FastAPI BackgroundTasks（與 uvicorn 同行程，restart 會丟工作）
    assert "BackgroundTasks" not in app目錄原始碼
    assert "background_tasks" not in app目錄原始碼
    # §1.2 第 2 列：用的是 Celery，不是自寫的 Redis list 消費迴圈
    assert "celery" in 需求
    assert (專案根目錄 / "app" / "celery_app.py").exists()
    # §3 第 7 列（design6 §1.1 第 1 列已推翻其中的 boto3 一項，其餘照舊禁止）
    for 關鍵字 in ("s3fs", "minio", "google-cloud-storage"):
        assert 關鍵字 not in 需求, f"S3 只當寄物櫃、不是第二個檔案櫃：{關鍵字}"
    # 增量六起：boto3 是必要的（design6 §1.1 第 1 列）。
    # 用「行首」比對而不是子字串：註解裡提到這個名字不算數，只有真的那一行 requirement 才算
    assert re.search(r"^boto3\b", 需求, re.M), "增量六需要 boto3（design6.md §1.1 第 1 列）"
    # §3 第 5 列：不裝 Flower
    assert "flower" not in 需求
```

- [x] 跑那一顆，確認它轉綠：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest "tests/integration/test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存" -v
```

**預期輸出：** `1 passed`

- [x] **證明它還在測東西**（不是被改成永遠綠）：把 `requirements.txt` 裡
      `boto3>=1.35` 那一行**暫時註解掉**（行首加 `#`；斷言用的是「行首 `^boto3`」的
      正規表示式，註解掉就等於不在，不必真的剪掉），再跑一次那一顆：

```bash
pytest "tests/integration/test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存" -q
# 預期：1 failed，訊息是「增量六需要 boto3（design6.md §1.1 第 1 列）」
```

      看到紅之後把行首的 `#` **拿掉**，再跑一次確認回到 `1 passed`。

---

### 4.7 全量回歸 ＋ 三個死埠的零依賴實證

- [x] 全量：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

**預期輸出：** `640 passed`，**0 skipped**（2026-09-02 實查基線 624 ＋ 16）。

- [x] **三個死埠一起指**（從本 phase 起，零依賴實證都用這一條）：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

**預期輸出：** 顆數與上一條**一模一樣**（`640 passed`；fix wave 後實查 **644**）。

這一條同時證明三件事：pytest 不連真 AWS、不連真 Redis、不打真 Ollama。
**三個一起指也很重要**——分開指的話，它們可能會互相掩護
（例如某個測試其實是被 Redis 那條路擋下來的，你卻以為是 AWS 那條）。

- [x] 端點沒變（本增量恆 22）：

```bash
pytest tests/integration/test_nav_header.py::test_端點數仍為22 -q
```

**預期輸出：** `1 passed`

- [x] SQL 仍然只在 repository（新檔不可以碰資料庫）：

```bash
pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
```

**預期輸出：** `1 passed`

---

### 4.8 格式與 lint

- [x] 執行（與 CI 跑的兩句完全相同）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
ruff format --check app tests scripts && ruff check app tests scripts
```

**預期輸出：**

```text
107 files already formatted
All checks passed!
```

（2026-09-02 實查開工時是 **105** 個檔，本 phase 新增兩個 `.py` → **107**。
檔案數會隨專案成長而不同，重點是**沒有** `Would reformat:` 也沒有 `error:`。）

真的有東西要改時：

```bash
ruff format app tests scripts
ruff check --fix app tests scripts
```

---

### 4.9 收尾：**不 commit——記快照**

> ⛔ **本輪（2026-09-02，裁決 R0）明確不 commit。**
> 總覽 §7 鐵律 12：commit 節奏由產品負責人決定，他沒指示前**不要 commit、不要 `git add`、
> 不要 `git stash`、不要把計畫檔 `git mv` 進 `finish/`**（`git mv` 會直接 stage）。
> 驗收改成「與開工前的工作樹快照相減」。

- [x] **開工前**（做 §4.1 之前）先照一張快照，把 SHA 記在自己的筆記裡：

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0902-1/snapshot-tree
```

**預期輸出：** 一行 40 字元的 tree SHA（這個指令**不碰真正的 index、不建 commit、不動 stash**，
只在物件庫多一顆 tree 物件）。

- [x] **收工後**再照一張，然後兩顆相減，確認**恰好動到四個檔**：

```bash
cd /Users/linjunting/personalDocAI
AFTER=$(.superpowers/sdd/phase0902-1/snapshot-tree)
git diff --stat <開工前那顆SHA> "$AFTER"
```

**預期：** 只列出這四個檔（順序不拘）——

```text
 app/services/aws_mailbox.py               | ... +
 requirements.txt                          | ... +
 tests/integration/test_design5_error_paths.py | ... +-
 tests/unit/test_aws_mailbox_unit.py       | ... +
```

- [x] 沒有快照 SHA 時的替代做法（工作樹本來就乾淨，所以這樣也看得出來）：

```bash
git status --short -- app tests requirements.txt
```

**預期：** 恰好四行——

```text
 M requirements.txt
 M tests/integration/test_design5_error_paths.py
?? app/services/aws_mailbox.py
?? tests/unit/test_aws_mailbox_unit.py
```

> 📌 **給日後真的要 commit 的人**（產品負責人指示之後才做）：訊息可以用這一句——
> `feat: Phase 83 aws_mailbox 模組——requirements 加 boto3>=1.35（本增量唯一新套件）、新增 app/services/aws_mailbox.py（全系統唯一 import boto3 的地方：三個鍵名函式＋S3 put/get/delete＋jobs 與 results 兩條佇列的六個動作＋instance_state），NoSuchKey 翻成 None、delete 失敗只 warning、WaitTimeSeconds 夾在 20；+16 tests（手寫 stub client、零出網、含 boto3 掃碼）；改 design5 那顆掃碼測試（design6 §1.1 第 1 列推翻 boto3 禁令，s3fs／minio／google-cloud-storage／flower 仍禁止）；端點仍 22、對外行為零改變`

---

## 5. ASCII 圖

### 圖一：兩層契約——本 phase 補的是右下角那一塊

```text
   app/services/gated_ingest.py            決定走本機還是雲端（78／79／80／81）
              │
              ▼
   app/services/cloud_ingest.py            流程：送出、等結果、逾時、清理（77／79／80）
              │
              │   只認 CloudMailbox 這個 Protocol（Phase 77 定的契約）
              │   ┌────────────────────────────────────────────────────┐
              │   │ put_object / get_object / delete_objects           │
              │   │ send_job / send_result                             │
              │   │ receive_result / delete_result_message /           │
              │   │ release_result_message                             │
              │   │ input_key / context_key / result_key               │
              │   │ instance_state                                     │
              │   └────────────────────────────────────────────────────┘
              │
     ┌────────┴─────────────────────────────┐
     ▼                                      ▼
┌──────────────────────────┐   ┌──────────────────────────────────────────┐
│ tests/fakes.FakeMailbox  │   │ app/services/aws_mailbox.AwsMailbox      │
│ （Phase 77）             │   │ ★ 本 phase                                │
│                          │   │                                          │
│ 純記憶體 dict ＋ 兩個 list│   │ boto3 → 真的 S3／SQS／EC2                 │
│ 78〜81、87 的測試都用它   │   │ 86 起由 get_cloud_route() 真的建它        │
│ 零網路、零憑證           │   │ 單元測試用手寫 stub client，一樣零網路     │
└──────────────────────────┘   └──────────────────────────────────────────┘

  ⚠ 兩邊都不知道對方存在。呼叫端也不知道自己拿到哪一個——
    這就是「換實作不必改任何呼叫端」的全部意思。
```

### 圖二：一次成功的雲端往返，十四個方法各在哪一步被呼叫

```text
  本機（Celery worker）                    S3 / SQS                  工人（EC2 或 Mac）
  ─────────────────────                ─────────────────           ──────────────────
   ① context_key(job)  ─┐
      put_object(...)   ├─ PutObject ──▶ documents/{id}/context.json
   ② input_key(job,ct) ─┤
      put_object(...)   ├─ PutObject ──▶ documents/{id}/input.jpg
   ③ send_job(id, key) ─┴─ SendMessage ▶ [jobs 佇列]
                                              │
                                              └─ ReceiveMessage ──▶ ④ receive_job(20)
                                                                    ⑤ result_key → get_object
                                                                       （冪等：已存在就跳過）
                                              ◀── GetObject ──────── ⑥ get_object(input)
                                              ◀── GetObject ──────── ⑦ get_object(context)
                                                                       ⋯ Ollama Cloud 看圖 ⋯
                                              ◀── PutObject ──────── ⑧ put_object(result.json)
                                     [results 佇列] ◀── SendMessage ─ ⑨ send_result(id)
                                              ◀── DeleteMessage ──── ⑩ delete_job_message(rh)
   ⑪ receive_result(≤20) ◀─ ReceiveMessage ──┘
      （不是我的 → release_result_message(rh) 可見度改 0，還回去）
   ⑫ get_object(result) ── GetObject ──────▶ documents/{id}/result.json
      delete_result_message(rh)
   ⋯ 本機 embed（bge-m3）＋ INSERT ＋ 原圖 ＋ 縮圖 ⋯
   ⑬ delete_objects([input, context, result])  ── DeleteObjects ──▶ 三個物件一起刪

  ⛔ 兩條佇列的 body 從頭到尾**只有字串**：
       jobs    {"job_id": "...", "s3_key": "documents/.../input.jpg"}
       results {"job_id": "..."}
     位元組全部走 S3（design6 §0 禁止第 2 條）。SQS 單則上限是 1 MiB
     （結論不變：影像仍不進 SQS——多頁 PDF 幾十 MB 一樣放不下）。

  ★ 順序鐵律（D9）：⑧ 一定在 ⑨ 之前。反過來的話本機會被叫醒去拿一個還沒寫完的檔。

  ★ instance_state() 沒有出現在這張圖裡——它是 Phase 89 的 Ec2Probe 在
    「要不要走這條路」之前先問的那一句，不屬於這次往返。
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` ＝ **624** passed ＋ 0 skipped（2026-09-02 實查值；
      總覽 §2.2／§2.7／§9 寫的 616 是規劃值，見 §2.3 的 📌）

- [x] **`boto3` 進了 requirements，而且 host 與容器都裝上了**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  grep -n "^boto3>=1.35" requirements.txt              # 預期：恰一行命中
  python -c "import boto3; print(boto3.__version__)"   # 預期：1.35 以上
  docker compose exec worker python -c "import boto3; print(boto3.__version__)"
  ```
  最後一條預期印出同樣量級的版本號。**印不出來＝忘了 `--build`**（見 §7 陷阱 1）。
  ⚠ **最後那一條（容器）由 controller 執行**（裁決 R3，同 §4.1）；實作者只驗前兩條。

- [x] **新模組的十四個公開方法都在**

  ```bash
  grep -cE "^    def (input_key|context_key|result_key|put_object|get_object|delete_objects|send_job|receive_job|delete_job_message|send_result|receive_result|delete_result_message|release_result_message|instance_state)\(" \
    app/services/aws_mailbox.py
  ```
  預期輸出：`14`（十四個公開方法；另有 `__init__` 與內部的 `_receive` 不在這張清單上）。

  > 清單裡列了 14 個名字，全部都要有。若印出來小於 14，
  > 用 `grep -nE "^    def " app/services/aws_mailbox.py` 看少了哪一個。

- [x] **`MailboxMessage` 是 import 來的，不是本檔自己定義的**（防「兩份 dataclass」）

  ```bash
  grep -n "from app.services.cloud_ingest import MailboxMessage" app/services/aws_mailbox.py
  grep -c "class MailboxMessage" app/services/aws_mailbox.py
  ```
  預期：第一條恰一行命中；第二條印 `0`。

- [x] **`instance_state` 認得「查無」是一個錯誤代碼**（不是只認空清單）

  ```bash
  grep -n "InvalidInstanceID.NotFound" app/services/aws_mailbox.py
  ```
  預期：至少一行命中（常數 `UNKNOWN_INSTANCE_CODES`）。

- [x] **新測試 16 顆全綠**（2026-09-02 review fix wave 之後是 **17 顆**）

  ```bash
  pytest tests/unit/test_aws_mailbox_unit.py -v
  ```
  預期最後一行：`16 passed`（fix wave 之後：`17 passed`）

- [x] **`boto3` 真的只在那一個檔**

  ```bash
  pytest "tests/unit/test_aws_mailbox_unit.py::test_boto3只在aws_mailbox裡出現" -q
  ```
  預期：`1 passed`

  順手用眼睛看一次（測試用的是正規表示式，這一條是給人看的粗略版）：
  ```bash
  grep -rnE "^\s*(import|from)\s+(boto3|botocore)" app/ --include="*.py"
  ```
  預期：只印出 `app/services/aws_mailbox.py` 的那兩行。

- [x] **改過的那顆 design5 掃碼測試是綠的，而且沒有把其他三個禁令一起拿掉**

  ```bash
  pytest "tests/integration/test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存" -q
  grep -n 's3fs' tests/integration/test_design5_error_paths.py
  grep -n 'flower' tests/integration/test_design5_error_paths.py
  ```
  預期：`1 passed`；後兩條各自命中（代表 `s3fs`／`minio`／`google-cloud-storage`／`flower`
  的禁令都還在）。

- [x] **全量測試 ＝ 開工基線 ＋ 16**

  ```bash
  pytest -q
  ```
  預期：`640 passed`，**0 skipped**（624 ＋ 16）。
  📌 2026-09-02 review fix wave 之後：**644**（Phase 86 落地的 +2 與 fix wave 的 +2 都在內）。

- [x] **零外部依賴實證（三個死埠一起指，顆數不變）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```
  預期：`640 passed`（與上一條**一模一樣**）。

- [x] **端點仍是 22 支、openapi 零 DELETE**

  ```bash
  pytest tests/integration/test_nav_header.py::test_端點數仍為22 \
         "tests/integration/test_design5_error_paths.py::test_端點恰好是這22支" -q
  ```
  預期：`2 passed`

- [x] **專案的 `data/` 沒被弄髒**（本 phase 的測試全部是純單元測試，連檔案都沒寫）

  ```bash
  cd /Users/linjunting/personalDocAI
  ls data/staging/ | wc -l     # 預期：0
  git status --short data/     # 預期：零輸出（data/ 已被 .gitignore 擋掉）
  ```

- [x] **格式與 lint 過**

  ```bash
  ruff format --check app tests scripts && ruff check app tests scripts
  ```
  預期：`All checks passed!`

- [x] **規格區一字未動**

  ```bash
  git status --short docs/spec/
  ```
  預期：**零輸出**（本增量全程如此）。

- [x] **git 收尾符合現行節奏＝不 commit、記快照**（2026-09-02 裁決 R0）：

  ```bash
  cd /Users/linjunting/personalDocAI
  AFTER=$(.superpowers/sdd/phase0902-1/snapshot-tree)
  git diff --stat <開工前那顆SHA> "$AFTER"   # 恰四個檔，見 §4.9
  git status --short -- app tests requirements.txt   # 沒有快照時的替代：恰四行
  git log -1 --oneline                       # 預期：HEAD 沒有動（還是開工那一顆）
  ```
  **預期：** 前兩條各自恰為那四個檔（`requirements.txt`、`app/services/aws_mailbox.py`、
  `tests/unit/test_aws_mailbox_unit.py`、`tests/integration/test_design5_error_paths.py`）；
  第三條印出來的 commit 與開工時**逐字相同**（＝真的沒 commit）。

---

## 7. 常見陷阱

1. **症狀：** host 上 `pytest` 全綠，但 Phase 86 走雲端路時 worker 容器噴
   `ModuleNotFoundError: No module named 'boto3'`。
   **原因：** 改了 `requirements.txt` 之後只做了 `up -d`，**沒有 `--build`**。
   常駐模式的程式在**映像裡**（不是 bind-mount），不重建就還是舊的套件清單。
   **正解：**
   ```bash
   docker compose -f compose.yaml up -d --build
   docker compose exec worker python -c "import boto3; print(boto3.__version__)"
   ```
   （這也是 `CLAUDE.md` 早就記過的規則：「改 requirements → `docker compose build app`，再 `up -d`」。）
   ⚠ **上面那兩條由 controller 親自執行**（2026-09-02 裁決 R3，同 §4.1）。
   **同一個坑的另一半：** 只重建映像、忘了 host 的 `.venv`，測試檔會在
   `from botocore.exceptions import ClientError` 那一行爆 `ModuleNotFoundError`
   ——pytest 是在 host 跑的，兩邊都要裝：`uv pip install -r requirements.txt`。

2. **症狀：** 工人明明寫好了 `result.json`、本機也收到 results 訊息，
   但本機就是「認不得」那則訊息，每一筆都逾時 fallback。
   **原因：** 有人在 `aws_mailbox.py` 裡**又定義了一份** `MailboxMessage`
   （因為 import 不到就自己補一個）。兩份同名不同源的 dataclass，
   `isinstance` 與相等比較全部失效，而且**完全不會報錯**。
   **正解：** 本檔**只准** `from app.services.cloud_ingest import MailboxMessage`。
   真的 import 不到，代表 Phase 77 沒做完或名字不同——回去對總覽 §2.4.1，不要自己補。
   §6 驗收清單有一條 `grep -c "class MailboxMessage" app/services/aws_mailbox.py` 預期 `0`，
   就是在守這件事。

3. **症狀：** IAM policy 少了一行權限，結果整個系統的表現是「AWS 好慢，每次都逾時」。
   **原因：** `get_object` 把**所有** `ClientError` 都當成「檔案不在」回 `None`。
   `AccessDenied` 於是被偽裝成「結果還沒好」→ 每筆都等到 deadline → fallback。
   你會查很久才發現不是慢，是權限。
   **正解：** 只有 `NoSuchKey`／`404` 回 `None`，其餘 `raise`。
   `test_get_object遇到其他錯誤照樣往外丟` 就是釘這一條。

4. **症狀：** 佇列空的時候噴 `KeyError: 'Messages'`。
   **原因：** 真 SQS 在沒有訊息時回的字典裡**根本沒有 `Messages` 這個鍵**
   （不是回空清單）。寫成 `response["Messages"]` 就會炸。
   **正解：** `response.get("Messages") or []`。測試的 `StubSqs` 刻意模擬了真 SQS
   的這個行為（回 `{"ResponseMetadata": {}}`），所以這個錯在單元測試就會被抓到。

5. **症狀：** 工人刪到了別人的 results 訊息；或自己那則 jobs 訊息沒被刪掉，
   15 分鐘後（jobs 佇列的 VisibilityTimeout ＝ 900 秒，Phase 85）又冒出來把同一張圖再看一次。
   **原因：** 兩條佇列的 URL 寫反了（`delete_job_message` 用到 `self._results_queue_url`）。
   **兩個現象都不會報錯**——AWS 只會照做。
   **正解：** `test_delete_job_message帶receipt_handle` 一次比對兩則呼叫的
   `QueueUrl`，寫反就紅。實作時把 jobs 與 results 的方法**分開寫**（不要用一個
   帶 `queue` 參數的萬用方法），呼叫端就不可能傳錯。

6. **症狀：** 照片明明已經入庫了，進度面板卻出現一列紅字說失敗。
   **原因：** `delete_objects` 清理失敗時往外丟了例外，被上層當成「這筆壞了」。
   **正解：** 清理是**盡力**（design6 §2.1）。`delete_objects` 是本檔**唯一**攔全部例外
   的方法，只留 `logger.warning`。殘骸兩天後由 Lifecycle 掃掉（Phase 84），
   那比「把成功變成失敗」好一百倍。
   **同一個坑的另一半：** 反過來「什麼都沒印、殘骸卻一直在」——`DeleteObjects` 是批次 API，
   某幾個 key 刪不掉時它**不丟例外**，回 HTTP 200、把失敗的列在回應的 `Errors` 裡。
   所以實作除了 `except`，還要把 `response["Errors"]` 逐筆 warning 出來；
   `test_delete_objects失敗只記log不往外丟` 的第 ② 段就是釘這個。

7. **症狀：** 掃碼測試 `test_boto3只在aws_mailbox裡出現` 莫名其妙紅了，
   而你只是在 `cloud_ingest.py` 的註解裡寫了一句「這裡不 import boto3」。
   **原因：** 用 `"import boto3" in 原始碼` 這種**子字串**比對的話，中文註解會誤中。
   結果大家只好把註解改成暗語，比沒有測試還糟。
   **正解：** 用行首的正規表示式
   `re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)`
   ——只認真正的 import 陳述句，連寫在函式裡的延遲 import 也抓得到（因為允許縮排）。

8. **症狀：** 真的接上 AWS 之後（Phase 86），SQS 回
   `InvalidParameterValue: Value 300 for parameter WaitTimeSeconds is invalid.`
   **原因：** 呼叫端（`wait_result`）把「還剩 300 秒」直接傳進來。
   **正解：** 夾在 `_receive` 裡（`min(wait_seconds, MAX_WAIT_SECONDS)`），
   不要求每個呼叫端自己記得。`test_receive_job的等待秒數不超過20` 傳的就是 300。

9. **症狀：** 改 design5 那顆掃碼測試時，順手把整個 `for 關鍵字 in (...)` 迴圈刪掉了。
    **原因：** 想「反正 boto3 現在可以了」。
    **後果：** `s3fs`／`minio`／`google-cloud-storage` 的禁令一起消失。
    那三個都是「把 S3 當第二個檔案櫃」的用法，而 design6 **D1 明文**「S3 不是檔案櫃、
    不是備份、不是相簿」——禁令沒有被推翻。
    **正解：** 只從那個 tuple 裡拿掉 `"boto3"`，其餘三個留著，
    並且**反過來**加一條「行首 `^boto3`」的斷言。§6 驗收清單有兩條 `grep` 在守這件事。

10. **症狀：** Phase 84 的 `python scripts/aws_check.py s3` 走到「④ 再 GetObject 一次，確認真的不在了」
    就炸 `ClientError: An error occurred (AccessDenied) when calling the GetObject operation`
    ——明明 ①②③ 都成功、物件也真的刪掉了。更糟的在後面：工人每收到一則 jobs 訊息、
    第一步 `get_object(result_key)` 做冪等檢查就炸（那個 key 本來就還不存在），
    一張圖都處理不了；崩潰重送時本機的 `fetch_result` 也炸。
    **原因：** S3 的一條隱藏規則（GetObject 官方文件「Permissions」一節，附錄有連結）：
    對**不存在的 key** 做 GetObject，呼叫者**有** `s3:ListBucket` 權限才回 404 `NoSuchKey`；
    **沒有**就回 **403 `AccessDenied`**（S3 不讓沒權限的人靠 404 探測 key 存不存在）。
    policy 裡**沒給** `s3:ListBucket` 的話，本檔「`NoSuchKey` → `None`」的翻譯在真 AWS 上
    就**永遠不會發生**。
    **正解：** 兩份 policy 各要有一條 `s3:ListBucket`，`Resource` 是 **bucket 本身**
    （不是 `/documents/*`——ListBucket 是掛在 bucket 上的權限）：
    ```json
    {
      "Sid": "ListMailboxBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::personaldocai-mailbox-*"
    }
    ```
    這是唯讀權限，bucket 裡本來就只有我們自己的 `documents/`。
    📌 **2026-09-02 實查：`deploy/aws/mac-policy.json` 裡這條 Sid 已經在了，名字就叫
    `ListMailboxBucket`**（七條 Sid 之一；Phase 91 的 `worker-role-policy.json` 之後也要有，
    總覽 §10.2 追認項 P）。動手做 Phase 84 之前順手打開那個檔看一眼即可——
    不在就是抄漏了，回 `docs/plan/finish/phase-82-AWS帳號與工具.md` §4.6.1 補上
    （IAM policy 改完要重新 `put-user-policy`；⚠ 那是 **controller** 的動作，裁決 R3）。
    **不要**反過來把 `AccessDenied`
    塞進 `MISSING_KEY_CODES`——那會把真正的權限錯誤偽裝成「檔案不在」，正是陷阱 3 在防的事。
    Phase 84 的步驟 ④ 就是這條規則的實測：拿到 `None` ＝ policy 對了；
    拿到 `AccessDenied` ＝ 少了 `s3:ListBucket`。

11. **症狀：** Phase 92 換了一台實例（或把舊的 Terminate 超過一小時）之後，`.env` 的
    `EC2_WORKER_INSTANCE_ID` 還是舊的：worker log 每張圖都印一行 `Ec2Probe` 接到的例外
    `An error occurred (InvalidInstanceID.NotFound) when calling the DescribeInstances operation`，
    而不是乾淨的 `state=unknown`。
    **原因：** 以為「查無」是空的 `Reservations`。AWS 對**不存在**的 instance id 回的是**例外**
    （`ClientError`，代碼 `InvalidInstanceID.NotFound`），空清單只出現在「那台機器不是你的」
    這一種情況（boto3 `describe_instances` 文件：「If you specify an instance ID that is not
    valid, an error is returned. If you specify an instance that you do not own, it is not
    included in the output.」）。
    **正解：** `instance_state` 把 `InvalidInstanceID.NotFound` 翻成 `"unknown"`
    （常數 `UNKNOWN_INSTANCE_CODES`），其他代碼（`InvalidInstanceID.Malformed`＝id 格式打錯、
    `UnauthorizedOperation`＝沒權限）照樣往外丟——那些是設定真的錯了，讓 Phase 89 的
    `Ec2Probe` 把原因寫進 log 比藏成 `unknown` 好查。`test_instance_state查無回unknown`
    把三種「查無」＋一種「不是查無」全部釘住。

12. **症狀：** worker（或 Phase 88 的工人）log 每 15 分鐘出現**同一則**
    `KeyError: 'job_id'` 或 `json.decoder.JSONDecodeError`，連續好幾天。
    **原因：** 有人用 `aws sqs send-message` 手動塞了一則測試訊息（例如 body 是 `hello`），
    而 `_receive` 在 `json.loads`／`body["job_id"]` 就炸了——呼叫端連 receipt handle 都拿不到，
    刪不掉它；於是它每次可見度到期（jobs 900 秒）就回來一次，直到 4 天保留期滿。
    **正解：** `_receive` 自己攔下這兩種壞紙條：`logger.warning`＋用手上的 receipt handle 直接
    `delete_message`＋回 None（總覽 §10.2 追認項 K 擴寫版）。`test_receive_job沒訊息時回None`
    的 ②③ 段釘住「刪對佇列、刪對把手、warning 兩則」。要手動塞測試訊息時，body 請照契約
    `{"job_id": "...", "s3_key": "..."}` 寫，不然它會被當壞紙條刪掉。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- `requirements.txt` 多一行 `boto3>=1.35`（**本增量唯一的新套件**），host 的 `.venv`
  與 Docker 映像都已裝上（映像那一半由 controller 重建，裁決 R3）。
- 新檔 `app/services/aws_mailbox.py`：`AwsMailbox` 十四個公開方法 ＋ `__init__` ＋ 一個內部 `_receive`。
  **全系統只有它 import boto3／botocore**，而且有一顆掃碼測試釘住。
- 新檔 `tests/unit/test_aws_mailbox_unit.py`：16 顆，全部用手寫 stub client，
  **一個位元組都不出網**。
- `tests/integration/test_design5_error_paths.py` 有一顆被改（**增量五留下的 543 顆裡唯一被改的一顆**）：
  `boto3` 的禁令依 design6 §1.1 第 1 列解除，其餘三個雲端儲存套件與 `flower` 照舊禁止，
  並反過來釘住「boto3 必須在」。

**對外行為變了沒：完全沒有。**

`AwsMailbox` **還沒有任何人呼叫**——`get_cloud_route()` 仍然只認 `off`，
`CLOUD_ROUTE` 的預設值也還是 `off`。上傳、待決定、詢問、進度面板一個像素都沒變。
端點仍是 **22** 支、openapi 零 DELETE、`photo` 表零改動、前端零改動、
`compose.yaml` 零改動、`docs/spec/` 一字未動。

**顆數：+16，與總覽 §2.7／§9／§10.2 J 一致（總覽已吸收這一顆）。基線 624 → 640。**

總覽 §2.7 給 Phase 83 的就是 **+16**（§9 軌跡表與 §2.2 一覽表寫的絕對值是 632）；
本 phase **沒有**比總覽多任何一顆。
📌 **絕對值為什麼是 640 不是 632**：總覽那三處是用「616 基線」算的規劃值，
而 Phase 75／79／81 實作時各自的 code review 裁決多補了幾顆守門測試
（總覽 §2.2 的 Phase 81 那列與 §9 軌跡表的 75／79／81 三列都已註記「實 …」，
2026-09-02 實查基線＝**624**）。後面的 phase 抄顆數時**只對「本 phase 新增幾顆」**。
其中第 16 顆 `test_get_object拿得回位元組而delete_objects送出鍵清單` 是總覽 §10.2 追認項 J
特別補進來的：design6 §9 的「必釘」清單裡，`get_object` 只有兩條**失敗路徑**
（`NoSuchKey` 回 None、其他錯誤往外丟），`delete_objects` 也只有失敗路徑那一顆。
也就是說——**一個「`get_object` 永遠 `return None`」的實作可以讓其餘 15 顆全綠**。
而 `get_object` 正是「把雲端算好的 `result.json` 拿回家」的那一步：
它壞掉的話，整條雲端路會**安靜地**每一筆都逾時 fallback，
表現得像「AWS 好慢」，實際上是程式錯——正是最難查的一種壞法。
同一顆順便把 `delete_objects` 的 `Delete={"Objects": [{"Key": ...}]}` 形狀也釘死
（那個形狀打錯的話 boto3 會丟 `ParamValidationError`，但只有真的呼叫過才看得到）。

> 📌 給接下來的 phase：本 phase 之後的累計顆數是 **640**（2026-09-02 實查基線 624 ＋ 16；
> 總覽 §9 寫的 632 是用 616 規劃基線算的，**差的 8 顆是 75／79／81 review 多補的守門測試**）。
> Phase 84／85 都是 +0，所以到 Phase 86 開工時的基線是 **640**，收工 **642**。

**下一個 phase：Phase 84「建 S3 寄物櫃」**——
用 AWS CLI 在東京建 bucket（Block Public Access 四項全開、SSE-S3 預設加密、
`documents/` 前綴 2 天過期的 Lifecycle），把 bucket 名填進 `.env` 的 `S3_BUCKET`，
並寫一支 host 用的小腳本 `scripts/aws_check.py`（函式名是跨檔契約：`check_s3()`／
`check_sqs()`／`main()`／常數 `CHECK_JOB_ID = "aws-check"`；Phase 84 建全檔＋`check_sqs()` 佔位，
Phase 85 只換 `check_sqs()` 的本體）——
它會用**本 phase 寫好的 `AwsMailbox`** 對真 S3 做一次 put → get → 比對 → delete，印 OK。
那是本 phase 這個模組第一次真的打到 AWS（⚠ 那一步與所有 `aws` 指令都由 **controller** 親自執行，
裁決 R3；而且那支腳本走真 AWS，**不寫自動化測試**，裁決 R4）。

**顆數：** 開工基線 **624**（2026-09-02 實查）＋ **16** ＝ **640**（0 skipped）。

**2026-09-02 review fix wave**：+1 顆 `test_put_object與send失敗時例外原樣往外丟`
（`StubS3`／`StubSqs` 各加一個可選的 `put_error`／`send_error` 欄位；三個方法都用
`pytest.raises` 拿到**同一個**例外物件——變異證據＝把 `put_object` 暫時包成
try/except 就會紅）、壞紙條 warning 只印**佇列名**與 body 前 200 字（完整 QueueUrl 帶著
AWS 帳號 ID，而這個 repo 是公開的）、掃碼測試改比**相對路徑**
`app/services/aws_mailbox.py`（日後 `app/workers/aws_mailbox.py` 不會被誤放行）
並加守「`app/dependencies.py` 檔頭不得 import `aws_mailbox`」。
本檔的顆數因此是 **+17**、全量 **644**。

---

## 9. 實作紀錄（2026-09-02，Task 1 實作者）

- 實作四個檔（與 §4.9 預期完全一致）：`requirements.txt`（+8 行 boto3 段）、
  新檔 `app/services/aws_mailbox.py`（324 行、十四個公開方法）、
  新檔 `tests/unit/test_aws_mailbox_unit.py`（522 行、16 顆）、
  `tests/integration/test_design5_error_paths.py`（只換那一顆的函式體，+28/-4）。
  §4.2／§4.4／§4.6 的三段程式碼**逐字沿用**（直接從本計畫檔抽出，零手抄、`\xc2\xa0` 掃描零命中）。
- TDD 紅綠：加完 boto3 後全量 `1 failed, 623 passed`（design5 那顆如預期變紅）→
  新測試檔 `ModuleNotFoundError: No module named 'app.services.aws_mailbox'` →
  實作後 `16 passed` → 改掉 design5 那顆 `1 passed`；
  變異證據：把 `boto3>=1.35` 行首加 `#` → 那顆 `1 failed`（訊息「增量六需要 boto3」）→ 復原 `1 passed`。
- 全量 **640 passed、0 skipped**（基線 624 ＋ 16）；三死埠一起指同為 640；
  `ruff format --check` → `107 files already formatted`、`ruff check` → `All checks passed!`。
- host 裝到 **boto3 1.43.87**（botocore 1.43.87、jmespath、s3transfer 一併裝上）。
- 兩個未打勾的框（§4.1 重建映像、§6 第 2 條的容器驗證）＝ **controller 的動作**（裁決 R3）。
- 未 commit（裁決 R0）：開工前快照 `9fd215d0d03b35651bc3afceb27b398057214418`、
  收工後 `030e97edb6f24e43fb4696e5f6c53461cb25f52a`；`git status --short -- app tests requirements.txt`
  恰四行、`git log -1` 仍是 `a159131`。

## 附：本文件引用的官方文件

**boto3 / botocore**

（boto3 文件的舊網域 `boto3.amazonaws.com/v1/documentation/...` 已 301 轉到 `docs.aws.amazon.com/boto3/...`，下面一律用新網址。）

- [boto3 S3 `put_object`（`Bucket`／`Key`／`Body`／`ContentType`）](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)
- [boto3 S3 `get_object`（回應 `Body` 是 `StreamingBody`；例外 `NoSuchKey`；**有沒有 `s3:ListBucket` 決定 404 或 403**）](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html)
- [boto3 S3 `delete_objects`（`Delete={"Objects": [...]}`、一次最多 1000 個；**失敗的 key 列在回應的 `Errors`、不丟例外**）](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/delete_objects.html)
- [boto3 SQS `send_message`（`QueueUrl`／`MessageBody`）](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/send_message.html)
- [boto3 SQS `receive_message`（`MaxNumberOfMessages` 1〜10、`WaitTimeSeconds` 最多 20；**沒訊息時回應裡沒有 `Messages` 鍵**；receipt handle 每次都不同）](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/receive_message.html)
- [boto3 SQS `delete_message`（`QueueUrl`／`ReceiptHandle`）](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/delete_message.html)
- [boto3 SQS `change_message_visibility`（`VisibilityTimeout` 0〜43200；**0 ＝ 立刻可見**）](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/change_message_visibility.html)
- [boto3 EC2 `describe_instances`（`Reservations[].Instances[].State.Name` 六種值；**id 不存在＝回錯誤、不是你的＝不列出**）](https://docs.aws.amazon.com/boto3/latest/reference/services/ec2/client/describe_instances.html)
- [boto3 的錯誤處理（`ClientError` 與 `response["Error"]["Code"]`）](https://docs.aws.amazon.com/boto3/latest/guide/error-handling.html)
- [boto3 憑證搜尋順序（環境變數優先於 `~/.aws`）](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html)
- [AWS SDKs and Tools Reference：service-specific endpoints（`AWS_ENDPOINT_URL`／`AWS_ENDPOINT_URL_<SERVICE>` 這組標準環境變數，boto3 認得）](https://docs.aws.amazon.com/sdkref/latest/guide/feature-ss-endpoints.html)

**AWS 服務行為**

- [SQS 短輪詢與長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS `ChangeMessageVisibility`（可見度改成 0 ＝立刻還回佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html)
- [SQS Standard Queue 與 at-least-once（可能重送，所以要冪等）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 大訊息與 S3 pointer（為什麼位元組要走 S3）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
- [S3 `DeleteObjects`（一次最多 1000 個鍵）](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html)
- [S3 錯誤代碼一覽（`NoSuchKey`／`AccessDenied`）](https://docs.aws.amazon.com/AmazonS3/latest/API/ErrorResponses.html)
- [S3 `GetObject` API（Permissions 一節：**沒有 `s3:ListBucket` 時，不存在的 key 回 403 而不是 404**——§7 陷阱 10 的出處）](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)
- [EC2 API 錯誤代碼一覽（`InvalidInstanceID.NotFound`／`.Malformed`——§7 陷阱 11 的出處）](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/errors-overview.html)
