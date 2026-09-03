# Phase 00：增量六總覽（design6.md 的實作路線圖，Phase 74〜95）

> **給實作者：** 本總覽把 `docs/design/design6.md`（2026-08-31 拍板，**2026-09-01 改判閘門為 VLM 短問、不看檔名、跟頁首開關**）拆成
> **22 個 phase（74〜95）**，計畫檔在本目錄 `phase-74`〜`phase-95`，**一次做一項**、全程 TDD。
> 衝突時 design6.md 為準；design6 未提及的行為仍依 design5.md／design4.md／design3.md／
> design2.md／design1.md／design.md v4。

> 🎯 **仍是 side project：不要過度設計。** 只做 design6.md 寫到的事。
> 定案不可逆、人確認才釘實體／建待辦、**embeddings 一律本機**、單一使用者、不做刪除照片、
> openapi 零 DELETE、頁首「AI 模型：本機｜雲端」開關語意不變——全部維持前面五個增量不變。

> ⚠️ **順序是硬的（design6 §0 標題就寫著「不可對調」）：**
>
> ```text
> 甲（74〜81）→ ★G1（人）→ 乙（82〜84）→ 丙（85〜86）→ 丁（87〜88）
>            → 戊前半（89〜90）→ ★G2（人）→ 戊後半（91〜92）→ ★G3（人）
>            → 己（93〜94）→ 95（收尾與驗收包）
> ```
>
> 三個閘門都是**人的動作**，實作者不可以自己勾掉（§4 有完整說明）。
> **★G1 沒過，一行 AWS 指令都不准打**——那是 design6 §0 的第一條禁止。

---

## 1. 這次增量在做什麼（新手白話）

design6 要做的事情用一句話講完是：

> **在照片進入 S3／EC2 之前，先用現有看圖 VLM 問一句短問題「這張敏不敏感」
> （不看檔名；模型跟頁首本機／雲端開關走）；只有「明確不敏感」而且
> 遠端工人真的開著的時候，才把它送去雲端看圖；其他所有情況都走現在這條路，
> 使用者完全不必改操作。**

它一共有**六段**，順序不可以對調。下面三小節把六段各講一次「現在的痛／做完之後」。

### 1.1 階段甲：隱私閘門與 fallback（Phase 74〜81）—— 這次增量的地基

#### 第一段：隱私閘門（Privacy Gate）

**現在的痛：** 現在照片一律在這台 Mac 上看圖。這件事本身沒問題，但只要有一天你想
「把不重要的照片丟到雲端去看，省下這台機器的力氣」，你會立刻撞到一個問題：
**電腦不知道哪些照片不能出門。** 身分證、健保卡、薪資單、病歷、銀行對帳單——
這些東西一旦上傳到別人的機房，就再也收不回來了。

**做完之後：** 每一張進佇列的照片，在**被送到 S3／EC2 之前**，先被分成三類
（本機 Celery worker 觸發；短問題用現有看圖 VLM，跟著頁首開關）：

| 分類 | 意思 | 會怎樣 |
|---|---|---|
| `SENSITIVE`（敏感） | VLM 短問判定有個人敏感資訊 | **不進 S3**，走本機入庫 |
| `NON_SENSITIVE`（非敏感） | VLM 短問判定不敏感而且有把握 | 才**有資格**走雲端管線 |
| `UNCERTAIN`（不確定） | 看不懂、沒把握、或模型失敗 | **當敏感辦**，不進 S3 |

**「不確定＝本機」是這個增量最重要的一條規則。** 它的意思是：閘門判斷失誤時，
代價是「這張照片沒有卸到雲端」（＝跟現在一模一樣），而不是「敏感檔進 AWS」。

閘門**只有一層**：現有看圖 VLM 的短問題（Phase 74 契約＋假件，Phase 75 縮圖／計時／真 Ollama）。
**不看檔名、無關鍵字表。** 頁首開關在「雲端」時，這句短問會去 ollama.com——
產品負責人 2026-09-01 接受（開關本就是開發加速用）。S3／EC2 仍只收 `NON_SENSITIVE`。

#### 第二段：fallback 契約（遠端關掉＝本機原樣）

**現在的痛：** 這不是「現在的痛」，是**未來的坑**。如果先做雲端管線、後做 fallback，
那麼從第一天起整個系統就在賭「AWS 永遠通、EC2 永遠開著」。而事實是 EC2 平常是 **Stop** 的
（產品負責人要 $0，用完就關），所以「遠端關著」才是**常態**，不是例外。

**做完之後：** 有一支新的 `run_gated_ingest_job()` 站在 Celery 任務與既有 `run_ingest_job()`
之間。它問完閘門、探完遠端狀態之後，**任何一個環節不順就直接呼叫既有的 `run_ingest_job()`**——
使用者看到的 202、進度面板、待決定牆，跟增量五**逐字相同**。

「不順」有四種（design6 §2.1）：EC2 不是 `running`、沒有 AWS 憑證或 API 掛了、
送出失敗、送出去了但逾時沒有結果。四種都在 worker 的 log 留下一行
`fallback=local reason=…`，這行字樣是**契約**，測試用 `caplog` 釘住。

甲段做完（Phase 81 之後）就要停下來過 **★G1**。這時系統**還沒碰過任何 AWS**——
`CLOUD_ROUTE` 預設是 `off`，`get_cloud_route()` 回一個「永遠說遠端不可用」的物件，
所以行為與增量五 100% 相同，只是多了一層閘門與一堆測試。

### 1.2 階段乙與丙：寄物櫃（S3）與兩條佇列（SQS）（Phase 82〜86）

#### 第三段：S3 寄物櫃（乙，Phase 82〜84）

**現在的痛：** 本機要把一張圖交給遠端的工人看，但**工人不收連線**（design6 D11：
EC2 的 inbound 全部關掉，沒有 HTTP、沒有 SSH）。那圖要怎麼過去？

**做完之後：** 中間放一個**寄物櫃**——AWS S3 的一個 bucket。本機把檔案放進去，
工人自己去拿；工人把結果放進去，本機自己去拿。**兩邊都不必開門互連。**

S3 在這個專案**不是檔案櫃、不是相簿、不是備份**（design6 D1／D8）：
正本永遠在這台 Mac 的 Postgres 與 `data/`。S3 只是「東西在路上時暫時放的地方」，
處理完就刪，而且還有一條 Lifecycle 規則當掃把（`documents/` 前綴 2 天後自動過期）。

Bucket 設定三件事一件都不能少：**Block Public Access 四項全開**（不會有任何人能公開讀）、
**SSE-S3 預設加密**（AWS 幫你加密、不另外付 KMS 的月費）、**Lifecycle 2 天**。

Phase 82 是**零程式碼**的一份：開 AWS 帳號（Free plan）、**先建 Budget**、
裝 AWS CLI、建一個給這台 Mac 用的 IAM 使用者。這是整個增量第一次花到 AWS 資源，
所以它排在 ★G1 之後。

#### 第四段：兩條佇列（丙，Phase 85〜86）

**現在的痛：** 東西放進寄物櫃了，但**工人不知道有新東西**。難道要工人每三秒去問一次
「有沒有？有沒有？」嗎（那叫輪詢，會一直花錢也一直浪費）。

**做完之後：** 兩條 SQS Standard Queue，一條去、一條回：

| 佇列 | 誰放 | 誰拿 | 訊息內容 |
|---|---|---|---|
| `personaldocai-jobs` | 本機（檔案已放進 S3 之後） | 工人 | `{"job_id": "...", "s3_key": "documents/<id>/input.jpg"}` |
| `personaldocai-results` | 工人（`result.json` 已寫進 S3 之後） | 本機 | `{"job_id": "..."}` |

**訊息裡永遠只有字串，沒有任何影像位元組**（design6 §0 第 2 條禁止；SQS 單則上限
1 MiB——2025 年中前是 256 KB，design6 §1.2 寫的是舊值——一份多頁 PDF 幾十 MB 根本塞不進去）。位元組走 S3，佇列只放「指路的紙條」。

順序鐵律（design6 D9）：**東西先進 S3、才發訊息**。反過來的話，收到訊息的人會去拿
一個還沒寫完的檔案——那是最難查的一種壞法（安靜地拿到半截 JSON）。

Phase 86 把 `CLOUD_ROUTE=assume` 這條路接上真 AWS，然後做一次**故意讓它逾時**的煙霧：
沒有工人在跑 → 30 秒後 fallback 本機 → 照片照樣入庫 → S3 被清乾淨。
**這一步驗的正是「雲端壞掉時使用者無感」**，比「雲端成功」更重要。

### 1.3 階段丁、戊、己：工人、EC2 與自動部署（Phase 87〜95）

#### 第五段：工人 cloud_worker（丁，Phase 87〜88）

**現在的痛：** 寄物櫃有了、佇列有了，但**沒有人在另一頭做事**。

**做完之後：** 一支 `app/workers/cloud_worker.py`。它做的事只有六件：
收 jobs 訊息 → 從 S3 拿檔 → 拿 `context.json`（資料夾／實體／糾錯清單）→
用 **Ollama Cloud** 看圖（最多 3 次）→ 把結果寫成 `result.json` 放回 S3 →
發一則 results 訊息、刪掉 jobs 訊息。

它**不寫資料庫、不算 embedding、不碰 Redis、不碰 Celery**（design6 D11／D13）。
向量一定要跟庫裡既有的 bge-m3 同源，所以 embedding 永遠在本機算。

**丁段先在這台 Mac 上跑工人**（`CLOUD_ROUTE=assume`），不上 EC2。
理由是 design6 §1.2 最後一列已經否決過「第一天同時開六樣東西」——
先把「本機送出 → 工人處理 → 本機收回入庫」這條路在自己機器上跑通，
之後上 EC2 就只剩「換一台機器跑同一支程式」這一件事。

#### 第六段前半：EC2（戊，Phase 89〜92）

**現在的痛：** 工人在自己的 Mac 上跑，等於「左手交給右手」，一點都沒有卸壓。

**做完之後：** 同一支工人裝進一個 `linux/arm64` 的映像，跑在一台 **t4g.small**（ARM 機型）
的 EC2 上。這台機器：**inbound 全關**（沒有 SSH、沒有 HTTP，管理只走 SSM Session Manager）、
**outbound 只開 TCP 443**（要打 S3／SQS／ECR／SSM／ollama.com）、**用完就 Stop**。

本機這邊多一個 `Ec2Probe`：每次要送雲端之前先問一次「那台機器 running 嗎」，
答案快取 60 秒（不然每張圖都打一次 AWS API）。不是 running 就 fallback，
使用者完全無感——**這就是 Demo 2b**。

Phase 90（做 arm64 映像）做完就要停下來過 **★G2**：**G2 之後才開始花點數建 EC2。**
Phase 92 做完（真機 Demo 2／2b 都過了、機器 Stop 了）再停下來過 **★G3**。

#### 第六段後半：CD（己，Phase 93〜94）＋收尾（95）

**現在的痛：** 改工人的程式碼之後，要自己 build 映像、自己 push、自己登進機器重啟。
三步任何一步忘了，跑的就還是舊程式——而且**完全不會報錯**。

**做完之後：** `git push` 到 `main` → CI（既有的 `test` workflow）跑綠 →
CD（新的 `deploy` workflow）用 **OIDC 短憑證**（不放任何長期金鑰在 GitHub）
換到一個只能做三件事的角色 → build `linux/arm64` → push 到 ECR（同時打 `<git-sha>` 與 `latest` 兩個 tag）→
用 SSM Run Command 叫 EC2 重啟工人服務。**EC2 是 Stop 的時候，CD 仍然算成功**
（映像已經推上去了，下次開機自然拉到新的）。

「跑的到底是不是新映像」用工人啟動時印的 `version=<sha>` 驗（`WORKER_VERSION`），
**不靠 `latest` 這個 tag 當唯一依據**（design6 D16）。

Phase 95 是收尾：把 design6 §8 錯誤表 10 列逐列點名、把 §0 六條禁止與 §1.2 十一列
變成掃碼測試、產出驗收包給產品負責人。

### 1.4 全景圖：22 個 phase 與 3 個閘門

```text
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ 階段甲：隱私閘門與 fallback（74〜81）── 全程零 AWS，行為與增量五 100% 相同    │
 │   74  privacy_gate.py：Verdict 三分類、VlmGate（VLM 短問、不看檔名）       │
 │   75  OllamaPrivacyModel 跟頁首開關；縮圖 512；ai_timing kind=privacy     │
 │   76  ingest_job.py 純重構：抽出五個公開積木（對外行為零改變）                │
 │   77  cloud_ingest.py 契約＋CloudRouteOff＋conftest 第五道安全網              │
 │   78  gated_ingest.py：閘門接線、route=local、遠端不可用→fallback            │
 │   79  CloudRoute 本體＋雲端成功路（單圖）：用結果落庫、清 S3                  │
 │   80  wait_result 完整版：逾時、別人的訊息、崩潰重送、D17 冪等                │
 │   81  PDF 走雲端路：逐頁配對、跳頁、pages_done 續跑                           │
 │   何時算過：敏感／不確定零 S3 呼叫；假遠端關閉時非敏感也走 run_ingest_job     │
 └───────────────────────────────────────────────────────────────────────────────┘
                                     │
    ★★★ 閘門 G1（人）：甲的驗收 ＋ 產品負責人明示「可以開始花 AWS 資源」
         沒點頭 ＝ 停在這裡，**一行 AWS 指令都不准打**（design6 §0 第 1 條禁止）
                                     ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ 階段乙：AWS 帳號與 S3 寄物櫃（82〜84）                                        │
 │   82  人做：Free plan 開戶、**先建 Budget**、東京區、AWS CLI、IAM user        │
 │   83  aws_mailbox.py（全系統唯一 import boto3 的地方）＋requirements 加 boto3 │
 │   84  建 bucket：BPA 全開、SSE-S3、Lifecycle 2 天；scripts/aws_check.py s3    │
 │   何時算過：敏感檔 bucket 仍空；非敏感有 documents/{job_id}/input.*           │
 ├───────────────────────────────────────────────────────────────────────────────┤
 │ 階段丙：兩條 SQS 佇列（85〜86）                                               │
 │   85  建 personaldocai-jobs／personaldocai-results；aws_check.py sqs          │
 │   86  get_cloud_route() 補 assume；真 AWS 逾時煙霧（沒工人→30 秒 fallback）  │
 │   何時算過：jobs body 無位元組只有 job_id 與 s3_key；results 佇列尚無訊息     │
 ├───────────────────────────────────────────────────────────────────────────────┤
 │ 階段丁：Mac 上的工人（87〜88）                                                │
 │   87  cloud_worker.process_job_message()＋result.json 組裝＋端到端（假信箱）  │
 │   88  main() 主迴圈、SIGTERM、啟動 log；Mac 上真跑一次端到端                  │
 │   何時算過：本機送出→工人看圖→result.json→results→本機 GetObject 入庫      │
 ├───────────────────────────────────────────────────────────────────────────────┤
 │ 階段戊前半：探測與 arm64 映像（89〜90）                                       │
 │   89  Ec2Probe：DescribeInstances＋60 秒 TTL 快取；get_cloud_route() 補 ec2   │
 │   90  Dockerfile 多階段（base → cloud-worker → app 放最後）；arm64 映像       │
 └───────────────────────────────────────────────────────────────────────────────┘
                                     │
    ★★★ 閘門 G2（人）：丁的驗收 ＋ arm64 映像在 Mac 上跑得起來
         **G2 之後才開始花點數建 EC2**
                                     ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ 階段戊後半：真的 EC2（91〜92）                                                │
 │   91  SG（inbound 空）、S3 Gateway endpoint、IAM role＋instance profile、ECR  │
 │   92  啟動 t4g.small、SSM 放 worker.env、Demo 2／2b、**Stop**、文件三份       │
 │   何時算過：真機 Start→處理一筆→Stop；Stop 後下一筆自動走本機               │
 └───────────────────────────────────────────────────────────────────────────────┘
                                     │
    ★★★ 閘門 G3（人）：戊的驗收（真機 Demo 2／2b 都親眼看過、機器已 Stop）
         **G3 之後才做 OIDC／CD**（不然出問題時分不清是部署壞還是工人壞）
                                     ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ 階段己：CI 之後的 CD（93〜94）                                                │
 │   93  IAM OIDC provider＋deploy role（sub 精確鎖 main，**不准萬用字元**）     │
 │   94  .github/workflows/deploy.yml：workflow_run→OIDC→buildx arm64→ECR→SSM│
 │   何時算過：push 後 ECR 有 <sha>；SSM 更新；不靠 latest 當唯一 tag            │
 ├───────────────────────────────────────────────────────────────────────────────┤
 │ 收尾：95  §8 錯誤表 10 列逐列點名＋六禁與被否決清單掃碼＋三死埠實證＋驗收包    │
 └───────────────────────────────────────────────────────────────────────────────┘
```

### 1.5 前後對照：增量五的入庫流程 vs 增量六

```text
┌─ 增量五（現在）＝一條路走到底 ─────────────────────────────────────────────────────┐
│                                                                                    │
│  POST /photos ──202──► data/staging/{job_id}.jpg ──► Redis ──► Celery worker        │
│                                                                    │               │
│                                                       run_ingest_job(job_id, …)    │
│                                                                    │               │
│               看圖（本機 Ollama 或 ollama.com，看頁首開關）────────┤               │
│               轉向量（永遠本機 bge-m3）────────────────────────────┤               │
│               INSERT photo ＋ 原圖 ＋ 縮圖 ──────────────────────► 待決定牆         │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘

                            v v v   增量六改成   v v v

┌─ 增量六＝進 worker 之後多一個岔路口；岔錯了永遠退回原路 ───────────────────────────┐
│                                                                                    │
│  POST /photos ──202──► data/staging/{job_id}.jpg ──► Redis ──► Celery worker        │
│   （這一段一個字都沒改：202、staging、JobStore、進度面板全部原樣）  │               │
│                                                run_gated_ingest_job(job_id, …)     │
│                                                                    │               │
│   ★ 岔路口①：閘門（VLM 短問，跟頁首開關；不看檔名）            │               │
│        SENSITIVE / UNCERTAIN ──────────────────────────────────────┼──► run_ingest │
│        NON_SENSITIVE                                               │      _job     │
│              │                                                     │    （原路）   │
│              ▼                                                     │               │
│   ★ 岔路口②：遠端可用嗎？（Ec2Probe，60 秒快取）                   │               │
│        不是 running / 沒憑證 / API 掛了 ──── fallback ─────────────┼──► run_ingest │
│        是 running                                                  │      _job     │
│              │                                                     │               │
│              ▼                                                     │               │
│        PutObject context.json → PutObject input.* → SendMessage jobs               │
│              │                                                     │               │
│   ★ 岔路口③：等 results（長輪詢，最多 CLOUD_RESULT_TIMEOUT_SECONDS）│              │
│        送出失敗 / 逾時沒結果 ──── cleanup ＋ fallback ─────────────┼──► run_ingest │
│        收到了                                                      │      _job     │
│              │                                                     │               │
│              ▼                                                     │               │
│        GetObject result.json → 本機 embed → INSERT ＋ 原圖 ＋ 縮圖 ──► 待決定牆     │
│        → 刪 S3 三物件 → 刪 staging → 刪 job（＝成功，與現在同語意）                │
│                                                                                    │
│  ⚠ 三個岔路口不管往哪邊走，使用者看到的東西完全一樣：202、進度面板、待決定牆。      │
│    唯一的差別在 worker 的 log（多一行 route=… 或 fallback=local reason=…）。       │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.6 容器與雲端全圖（Phase 92 之後、EC2 開著的時候）

```text
  這台 Mac（正本住在這裡，一張照片都不會少）
  ┌──────────────────────────────────────────────────────────┐
  │  瀏覽器 / iPhone ──HTTPS:8000──► [app]  只收檔、入列      │
  │                                    │                     │
  │                                    ▼                     │
  │                                 [redis]  排隊 ＋ 進度     │
  │                                    │                     │
  │                                    ▼                     │
  │                                 [worker]  Celery ×2       │
  │                                    │                     │
  │                    ┌───────────────┼───────────────┐     │
  │                    ▼               ▼               ▼     │
  │                  [db]        data/staging     Ollama 在   │
  │                 Postgres      data/photos     Mac 上（本機│
  │                （正本）       data/thumbs      看圖／向量）│
  └────────────────────────────────┬─────────────────────────┘
                                   │  HTTPS(443) boto3
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  ┌───────────┐            ┌──────────────┐           ┌──────────────┐
  │  S3       │            │ SQS jobs     │           │ SQS results  │
  │ 寄物櫃    │            │ 本機 Send    │           │ 工人 Send    │
  │ private   │            │ 工人 Receive │           │ 本機 Receive │
  │ BPA 全開  │            └──────┬───────┘           └──────▲───────┘
  │ SSE-S3    │                   │ HTTPS(443)               │ HTTPS(443)
  │ 2 天過期  │◄──────────────────┼──────────────────────────┤
  └─────▲─────┘  HTTPS(443)       │                          │
        │                         ▼                          │
        │                 ┌───────────────────────────────────────┐
        └─────────────────│  EC2 t4g.small（AL2023 arm64）        │
           GetObject      │  ⛔ inbound 全關（無 SSH、無 HTTP）    │
           PutObject      │  outbound 只開 TCP 443                │
                          │  docker run cloud-worker（systemd）    │
                          └───┬───────────────┬───────────────┬───┘
                              │ HTTPS(443)    │ HTTPS(443)    │ HTTPS(443)
                              ▼               ▼               ▼
                        ollama.com        ECR（拉映像）   SSM（管理／重啟）
                        （雲端看圖）                      Session Manager
                                                          Run Command

  GitHub（程式碼與自動化）
  ┌──────────────────────────────────────────────────────────────────┐
  │  git push main ──► Actions「test」(CI) ──成功──► Actions「deploy」│
  │                                                        │         │
  │                          OIDC 短憑證（無長期金鑰）─────┤         │
  │                          buildx + QEMU → linux/arm64 ──┤         │
  │                          docker push <sha> ＋ latest ──┼──► ECR  │
  │                          aws ssm send-command ─────────┼──► EC2  │
  └──────────────────────────────────────────────────────────────────┘

  ⚠ 圖上每一條線都是**出站**的 HTTPS(443)。沒有任何一條線是「從外面連進來」的：
    EC2 的 security group inbound 是空的，本機也沒有對外開任何埠給 AWS。
```

### 1.7 新名詞白話表（第一次看到請先讀這張）

> 這張表的名詞在各 phase 檔第一次出現時還會再解釋一次。
> 沒列在這裡的舊名詞（佇列、Redis、Celery、worker、staging、202、冪等、
> bind-mount、named volume、Protocol／TypedDict…）看增量五總覽 §1.7。
> 無線鏡頭那條路用到的 Bonjour／mDNS 與本增量完全無關，本表略過。

| 名詞 | 白話解釋 |
|---|---|
| **Privacy Gate（隱私閘門）** | 本專案自己寫的判斷器，在照片被送到 S3／EC2 之前先問「這張敏不敏感」。用現有看圖 VLM 問一句短問題，**不看檔名**；模型跟頁首本機／雲端開關走 |
| **三分類（Verdict）** | 閘門只會回三個答案：`SENSITIVE`（敏感）／`NON_SENSITIVE`（非敏感）／`UNCERTAIN`（不確定）。規則是「**敏感→本機；不確定→本機；只有非敏感才允許雲端**」 |
| **fallback（退路）** | 「本來想走 A，A 不行就改走 B」。本專案的 B 永遠是既有的 `run_ingest_job()`——也就是「跟增量五完全一樣的做法」。log 一律寫 `fallback=local reason=…` |
| **S3（Simple Storage Service）** | AWS 的檔案存放服務。你丟一個檔案進去、給它一個名字，之後用那個名字拿回來。本專案只拿它當**寄物櫃**（東西在路上時暫時放），**不是**檔案櫃、不是備份、不是相簿 |
| **bucket（桶）** | S3 裡的一個「大資料夾」，名字**全世界唯一**（所以本專案的名字要帶帳號後六碼）。所有檔案都放在某個 bucket 裡面 |
| **prefix（前綴）** | S3 其實沒有真的資料夾，只有「名字開頭一樣」的一群檔案。`documents/` 就是本專案用的前綴，看起來像資料夾、實際上只是名字的開頭 |
| **key（物件鍵）** | 一個檔案在 bucket 裡的完整名字，例如 `documents/abc123/input.jpg`。「key」不是密碼的意思，就是「檔名」 |
| **Block Public Access（BPA）** | S3 的一個總開關，**四個小項全部打開**之後，這個 bucket 就再也不可能被設成公開。設一次就永遠安全，比逐個檔案檢查可靠 |
| **SSE-S3** | Server-Side Encryption with S3-managed keys ＝「AWS 幫你加密，鑰匙也 AWS 管」。**免費**。另一種 SSE-KMS 要自己管鑰匙、每個月要錢，design6 §1.2 已否決 |
| **Lifecycle（生命週期規則）** | bucket 上的一條自動清潔規則：「`documents/` 底下的東西放超過 2 天就自動刪掉」。它是**掃把**，不是主要的清理手段——正常流程處理完就會自己刪 |
| **SQS（Simple Queue Service）** | AWS 的訊息佇列。一邊放紙條、另一邊拿紙條。本專案用它當「有新工作了」與「工作做完了」的通知 |
| **Standard Queue（標準佇列）** | SQS 的兩種佇列之一。便宜、吞吐大，但**不保證順序**、而且**可能重送**。另一種 FIFO 保證順序但貴且慢，本專案不用 |
| **at-least-once（至少送一次）** | Standard Queue 的保證：同一則訊息**可能被送兩次以上**。所以收訊息的人必須**冪等**——做兩次跟做一次結果一樣（design6 D17） |
| **long polling（長輪詢）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 20 秒」，而不是「沒有就馬上回我空的」。好處是**少打很多次 API**（＝省錢），壞處是那 20 秒程式在等。20 秒是 AWS 的上限 |
| **visibility timeout（可見度逾時）** | 一則訊息被某人拿走之後，它會「隱形」一段時間，別人看不到。這段時間內拿走的人要嘛做完刪掉它、要嘛就會讓它重新出現給別人做。本專案 jobs 設 900 秒（多頁 PDF 要看很久）、results 設 30 秒 |
| **receipt handle（收據把手）** | 拿走一則訊息時 SQS 給你的一串**臨時**字串。要刪掉那則訊息、或要提早讓它重新出現，都得用它。它**不是** message id，而且每次拿都不一樣 |
| **ChangeMessageVisibility（改可見度）** | 用 receipt handle 把「隱形時間」改掉。改成 **0** ＝「我拿錯了，馬上還回去給別人」。本專案在「收到別人的 results 訊息」時就是這樣做的 |
| **purge（清空佇列）** | 把一條佇列裡的訊息全部倒掉。手動煙霧留下的殘訊息用它清（`aws sqs purge-queue`）。⚠ 60 秒內只能做一次 |
| **boto3** | Python 呼叫 AWS 的官方套件。本增量唯一新增的依賴，而且**全系統只有 `app/services/aws_mailbox.py` 可以 import 它**（掃碼測試釘住） |
| **IAM** | AWS 的權限系統（Identity and Access Management）。「誰」可以對「什麼」做「哪些動作」全部在這裡定義 |
| **IAM user（使用者）** | 一組長期的帳號密碼（在程式裡叫 access key ＋ secret key）。本專案只有**這台 Mac** 用它，key 放在 `.env`（不入版控） |
| **IAM policy（政策）** | 一份 JSON，寫著「允許／拒絕 哪些動作 對 哪些資源」。本專案的每一份 policy 都盡量只給該給的（例如本機只能碰 `documents/` 這個前綴） |
| **IAM role（角色）** | 「一組權限」，但**沒有密碼**。要用它的人（EC2、GitHub Actions）去跟 AWS 換一組**幾小時就過期的臨時憑證**。比長期 key 安全得多 |
| **instance profile（實例設定檔）** | 把一個 IAM role「掛」到 EC2 上的那層包裝。掛好之後，EC2 裡面的程式**什麼 key 都不必填**，boto3 自己就拿得到臨時憑證 |
| **trust policy（信任政策）** | role 的另一份 JSON：「**誰**可以來借用我」。CD 的那個 role 的 trust policy 必須把 `sub` 精確鎖成本專案的 `main` 分支，不然別人的 repo 也能借走 |
| **STS（Security Token Service）** | 發放臨時憑證的服務。`aws sts get-caller-identity` 是「我現在是誰」的萬用檢查指令，設定 AWS CLI 之後第一件事就是跑它 |
| **EC2** | AWS 的虛擬機。就是「租一台在別人機房裡的電腦」 |
| **t4g（機型家族）** | AWS 自研 **ARM 架構**（Graviton）的便宜小型機。`t4g.small` ＝ 2 vCPU、2 GB 記憶體。因為是 ARM，映像必須是 `linux/arm64`——這也剛好跟 Apple Silicon 的 Mac 同架構 |
| **AL2023（Amazon Linux 2023）** | AWS 自己的 Linux 發行版，**預裝 SSM agent**（所以不必開 SSH 就管得動），也裝得起 Docker |
| **arm64 / aarch64** | 同一件事的兩個名字：ARM 的 64 位元架構。Apple Silicon 的 Mac 與 t4g 都是它；GitHub 的 runner 是 **amd64**（x86_64），所以 CD 要用 QEMU 模擬才 build 得出 arm64 映像 |
| **Stop vs Terminate** | **Stop ＝ 關機**（硬碟留著，開回來東西還在，只有硬碟繼續小額計費）。**Terminate ＝ 銷毀**（整台連硬碟一起消失，不可逆）。本專案一律 **Stop** |
| **EBS** | EC2 的虛擬硬碟。Stop 之後運算費停了，但 EBS 仍按 GB 從**點數**扣（不是扣信用卡）。本專案用 8 GB gp3 |
| **security group（安全群組）** | EC2 的防火牆。**inbound（進來的連線）本專案永遠是空的**——一條規則都沒有；outbound 只開 TCP 443 |
| **user-data** | 建 EC2 時附上的一段開機腳本，只在**第一次開機**跑。本專案用它裝 Docker、建目錄、裝好 systemd 服務 |
| **SSM Session Manager** | 不開 SSH 也能拿到那台機器 shell 的服務。從 AWS Console 按一下就進去了，權限走 IAM，不必管金鑰 |
| **SSM Run Command** | 從外面對機器下一句指令（本專案用它跑 `systemctl restart personaldocai-worker`）。CD 靠它更新工人 |
| **ECR（Elastic Container Registry）** | AWS 版的 Docker Hub（私有）。CD 把映像推到這裡，EC2 從這裡拉 |
| **OIDC（OpenID Connect）** | 一種「不放長期金鑰也能證明我是誰」的機制。GitHub Actions 每次跑會拿到一張**只對這次執行有效**的短命令牌，AWS 驗過就發臨時憑證。這樣 GitHub 上**一個 AWS 金鑰都不必存** |
| **GitHub Actions workflow_run** | 一種觸發條件：「**另一個** workflow 跑完之後才觸發我」。本專案的 CD 就是綁在 CI（`test`）成功之後 |
| **buildx / QEMU** | `buildx` 是 Docker 的多平台建置外掛；QEMU 讓 amd64 的機器「假裝」成 arm64 去跑指令。兩個搭在一起，GitHub 的 amd64 runner 才 build 得出 arm64 映像（**慢，5〜15 分鐘**） |
| **Free plan（免費方案）／點數** | AWS 2025-07-15 之後的新帳號制度：開戶送 $100 點數（再做活動最多 +$100），**升 Paid 之前不扣信用卡**；6 個月或點數用完先到者**關帳**（資源消失，資料留 90 天）。本專案目標是卡片 **$0** |
| **Budget（預算警報）** | AWS Budgets 服務，設一個金額，實際或預測超過就寄信。**開戶第一天就要建**（本專案設每月 $5、80% 寄信） |
| **寄物櫃 / 信箱（mailbox）** | 本專案對 S3 這個角色的比喻，也是模組名 `aws_mailbox.py` 的由來：東西放進去、對方自己來拿，兩邊不必見面 |
| **WORKER_VERSION** | 工人映像被 build 時烙進去的 git commit 短碼。工人啟動時把它印在 log 裡，Demo 3 靠它證明「EC2 上跑的真的是新映像」 |

---

## 2. Phase 清單與進度

### 2.1 開工基準（2026-08-31 實查，開工前務必自己再驗一次）

| 項目 | 值 | 怎麼驗 |
|---|---|---|
| 測試顆數 | **543 passed ＋ 0 skipped** | `pytest --collect-only -q`（尾巴那行）／`pytest -q` |
| 端點數 | **22**，openapi 零 DELETE，**本增量恆為 22** | `client.get("/openapi.json").json()["paths"]` 展開成 (path, method) 後 `len == 22` |
| 端點清點測試位置 | `tests/integration/test_design5_error_paths.py::test_端點恰好是這22支`、`test_nav_header.py::test_端點數仍為22`、`test_ask_three_paths.py::test_端點數不變` | 本增量**三顆都不改**（design6 §5：不新增端點） |
| git 分支 | **`main`**（不是 `master`） | `git branch --show-current` |
| 上一個 phase 編號 | **73**（pre-commit 與 CI，計畫檔仍在 `unfinish/`，**不要動它**） | `ls docs/plan/unfinish/` |
| 服務 | 四個容器 `db`／`redis`／`app`／`worker` | `docker compose ps --no-trunc` |
| 網址 | **`https://`**localhost:8000（開頭多一個 s） | `curl -k -s https://127.0.0.1:8000/health` |
| 資料庫 | Docker `db`，`127.0.0.1:5433`，帳號 `postgres`；**本增量不改結構** | `psql -d PersonalDocAI -c "\d photo"` |

```bash
# 開工前一次驗完（在專案根目錄）
source .venv/bin/activate
docker compose ps --no-trunc          # db 與 redis 要是 Up (healthy)；app／worker 要是 Up
pytest --collect-only -q | tail -1    # 預期：543 tests collected
pytest -q                             # 預期尾巴：543 passed，且沒有 skipped
curl -k -s https://127.0.0.1:8000/health
git branch --show-current             # 預期：main
```

⚠️ **端點數不要用 `app.routes` 清點**——FastAPI 0.141 有 `_IncludedRouter` 的已知坑，
路由不會被攤平，數出來的數字是錯的（`~/.claude/.../memory/fastapi-routes-not-flattened.md` 有記）。
一律用 `/openapi.json`。WebSocket `/camera/{token}/signal` 依 FastAPI 的行為不進 openapi，不計入。

### 2.2 22 個 phase 一覽

| Phase | 檔名 | 階段 | 一句話 | 依賴 | design6 章節 | +顆 | 累計 | 完成 |
|---|---|---|---|---|---|---|---|---|
| 74 | `phase-74-隱私閘門規則版.md` | 甲 | `privacy_gate.py`：`Verdict`、`VlmGate`（短問、不看檔名）、假件；**不接線** | — | D2、D3、D4、§9 | +11 | 554 | [x] |
| 75 | `phase-75-隱私閘門本機模型備援.md` | 甲 | `OllamaPrivacyModel` 跟 `AI_BACKEND`；縮圖 512；`ai_timing` kind `privacy` | 74 | D4、D6、§1.1 第 3 列 | +10 | 564 | [x] |
| 76 | `phase-76-入庫任務拆成看圖與落庫.md` | 甲 | 純重構 `ingest_job.py`：抽出五個公開積木；**對外行為零改變、既有顆數逐顆綠（本次排在 74／75 之後＝564）** | — | §11 第 2 列（總覽 §2.4 裁決） | +4 | 568 | [x] |
| 77 | `phase-77-雲端路契約與第五道安全網.md` | 甲 | `cloud_ingest.py` 契約＋`CloudRouteOff`＋`AlwaysRunning`＋`build_context`；conftest 第五道 `wire_fake_cloud` | 74、**76**（`build_context` 吃 76 的 `PromptContext`） | §2、§9 前言、D10 | +12 | 580 | [x] |
| 78 | `phase-78-閘門接線與fallback契約.md` | 甲 | `gated_ingest.run_gated_ingest_job()`：閘門、`route=local`、遠端不可用→fallback；`celery_app` 改呼叫它 | 74、75、76、77 | D5、D7、D10、§2.1、§8 第 1／2／3 列 | +9 | 589 | [x] |
| 79 | `phase-79-雲端路本機端單圖.md` | 甲 | `CloudRoute` 本體（available／submit／fetch_result／wait_result 基本版／cleanup）＋雲端成功路（單圖） | 77、78 | D7、D8、D9、D13、§2.2、§2.3、§8 第 4／7 列 | +10 | 599 | [x] |
| 80 | `phase-80-雲端路逾時與冪等.md` | 甲 | `wait_result` 完整版（總覽 §2.5 五條規則）＋崩潰重送 `route=cloud`＋D17 冪等 | 79 | D10、D17、§2.1 第 4 條、§8 第 5／6 列 | +10 | 609 | [x] |
| 81 | `phase-81-雲端路PDF.md` | 甲 | PDF 走雲端路：`result.pages` 逐頁配對本機 `render_pages`；沿用跳頁／`pages_done`／0 頁失敗；**2026-09-02 裁決 R4 順手做 `render_pages(max_pages=)`＋閘門只渲染第一頁** | 79、80 | D7、D17、§2.2、§8 第 7 列 | +7（實 +11） | 616（實 **624**） | [ ] |
| **★G1** | （人的動作，沒有檔案） | — | 甲的驗收 ＋ 產品負責人明示「可以開始花 AWS 資源」 | 81 | §0 甲那列、§0 禁止第 1 條 | — | 616（實 624） | [ ] |
| 82 | `phase-82-AWS帳號與工具.md` | 乙 | **零程式碼、人做**：Free plan 開戶、**先建 Budget**、東京區、AWS CLI、IAM user `personaldocai-mac` | ★G1 | D15、§7 全節、§6 IAM 那列 | +0 | 616 | [ ] |
| 83 | `phase-83-aws_mailbox模組.md` | 乙 | `requirements.txt` 加 `boto3>=1.35`；**改 design5 那顆 boto3 掃碼測試**；`aws_mailbox.py` 全部方法（stub client） | 82 | D8、D9、§1.1 第 1 列、§2.2、§2.3 | +16（實 +17） | 632（實 641） | [ ] |
| 84 | `phase-84-建S3寄物櫃.md` | 乙 | AWS CLI 建 bucket（BPA、SSE-S3、Lifecycle 2 天）；`scripts/aws_check.py s3`；`.env` 填 `S3_BUCKET` | 83 | D8、§6「Bucket 非公開」「用完刪 mailbox」 | +0 | 632（實 641） | [ ] |
| 85 | `phase-85-建SQS兩條佇列.md` | 丙 | 建 `personaldocai-jobs`／`personaldocai-results`；`aws_check.py sqs`；`.env` 填兩個 URL | 84 | D9、§2.3 全節 | +0 | 632（實 641） | [ ] |
| 86 | `phase-86-真AWS雲端路接線.md` | 丙 | `get_cloud_route()` 補 `assume`；**真 AWS 逾時煙霧**（沒工人 → 30 秒 fallback → S3 清空） | 85 | D10、§2.1、§8 第 5 列 | +2（實 +3） | 634（實 **644**） | [ ] |
| 87 | `phase-87-cloud_worker核心.md` | 丁 | `app/workers/cloud_worker.py` 的 `process_job_message()`＋`result.json` 組裝；假信箱端到端（單圖＋PDF） | 86 | D11、D12、D13、D17、§2 下半、§8 第 6／7 列 | +12 | 646 | [ ] |
| 88 | `phase-88-cloud_worker主迴圈與Mac端到端.md` | 丁 | `main()` 迴圈、SIGTERM、啟動 log；**Mac 上真跑一次端到端**（真 S3／真 SQS／真 Ollama Cloud） | 87 | D12、§0 丁那列、§12 Demo 2 的前身 | +5 | 651 | [ ] |
| 89 | `phase-89-EC2探測running.md` | 戊 | `Ec2Probe`：`DescribeInstances` ＋ 60 秒 TTL 快取；任何例外→False；`get_cloud_route()` 補 `ec2` | 88 | D10 第 1 條、§2.1、§8 第 2／3 列 | +7 | 658 | [ ] |
| 90 | `phase-90-worker映像arm64.md` | 戊 | `Dockerfile` 改多階段（base → cloud-worker → **app 放最後**）；Mac 上用容器重跑 88 的端到端 | 88 | D15、D16、§11 第 5 列 | +4 | 662 | [ ] |
| **★G2** | （人的動作，沒有檔案） | — | 丁的驗收 ＋ arm64 映像在 Mac 上跑得起來；**之後才開始花點數建 EC2** | 90 | §0 丁那列、§0 戊那列 | — | 662 | [ ] |
| 91 | `phase-91-EC2的網路IAM與ECR.md` | 戊 | 人＋CLI：SG（inbound 空）、S3 Gateway endpoint、IAM role＋instance profile、ECR repo、第一次手動 push | ★G2 | D11、D15、§6、§7 網路那列 | +0 | 662 | [ ] |
| 92 | `phase-92-EC2真機與文件.md` | 戊 | 啟動 t4g.small、SSM 放 `worker.env`、**Demo 2／2b**、**Stop**；`LAUNCH.md`／`CLAUDE.md`／`README.md` | 91 | D12、D15、§7、§12 Demo 2／2b、§3「Free plan 約束寫進文件」 | +0 | 662 | [ ] |
| **★G3** | （人的動作，沒有檔案） | — | 戊的驗收（真機 Demo 2／2b 親眼看過、機器已 Stop）；**之後才做 OIDC／CD** | 92 | §0 戊那列、§0 己那列 | — | 662 | [ ] |
| 93 | `phase-93-GitHub_OIDC與部署角色.md` | 己 | IAM OIDC provider＋deploy role；trust 的 `sub` **精確鎖 `main`**；GitHub secret `AWS_DEPLOY_ROLE_ARN` | ★G3 | D16、§6 最後一列、§8 第 9 列 | +4 | 666 | [ ] |
| 94 | `phase-94-CD工作流程.md` | 己 | `.github/workflows/deploy.yml`：`workflow_run`→OIDC→buildx `linux/arm64`→ECR→SSM；**Demo 3** | 93 | D16、§12 Demo 3 | +6 | 672 | [ ] |
| 95 | `phase-95-增量六錯誤收尾與驗收包.md` | 收尾 | §8 十列逐列點名＋六禁與被否決清單掃碼＋三死埠實證＋驗收包 | 74〜94 | §0 六禁、§1.2、§3「不做」、§8 全表、§9、§12 | +10 | **682** | [ ] |

### 2.3 依賴順序總結

```text
甲   74 → 75                （75 把 74 的占位模型換成真 OllamaPrivacyModel：跟開關、縮圖、計時）
     76                     （純重構，與 74／75 無關，可先可後；77 的 build_context 吃它的 PromptContext、78 起用它的 run_ingest_job 與五積木；本次排在 75 之後）
     74 ＋ 76 → 77 → 78 → 79 → 80 → 81 → ★G1
     （77 的第五道安全網要先有，78 才接得上；79 的雲端成功路要 77 的 CloudRoute）

乙   ★G1 → 82 → 83 → 84
     （82 是人開帳號；83 的 boto3 沒有帳號也寫得出來，但 84 要用它去建 bucket）

丙   84 → 85 → 86
     （86 的真 AWS 煙霧兩條佇列與 bucket 都要在）

丁   86 → 87 → 88
     （87 用假信箱、88 才碰真 AWS；88 是丁的驗收）

戊   88 → 89 → 90 → ★G2 → 91 → 92 → ★G3
     （89 的 Ec2Probe 沒有 EC2 也測得出來——測試用 stub client）

己   ★G3 → 93 → 94

收尾 74〜94 → 95
```

> ⚠️ **交錯做的話，各 phase 檔內的絕對顆數對不上是正常的。**
> **要對的是「本 phase 新增幾顆」，不是絕對數字**，而且**不准為了湊數字去改或刪測試**。

### 2.4 本增量的公開契約（22 份 phase 檔逐字沿用，自己發明新名字＝錯）

> 📌 這一節就是「同一個名字，22 份文件講的是同一件事」的保證。
> phase writer 與 reviewer 都以本節為準；與各 phase 檔內文衝突時，**本節贏**。

#### 2.4.1 新檔與新函式簽章

> 📌 以下是**簽章草圖**（保證 22 份文件講的是同一個名字），**不要整段貼進檔案**——
> 要貼進檔案的完整內容以各 phase 檔的程式碼區塊為準。

```python
# app/services/privacy_gate.py（Phase 74 建、75 加長）
class Verdict(StrEnum):
    SENSITIVE = "SENSITIVE"
    NON_SENSITIVE = "NON_SENSITIVE"
    UNCERTAIN = "UNCERTAIN"

class PrivacyGate(Protocol):
    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict: ...

class PrivacyJudgement(BaseModel):
    sensitive: bool
    confident: bool

def judgement_to_verdict(judgement: PrivacyJudgement) -> Verdict: ...
    # sensitive → SENSITIVE（即使沒把握也當敏感）
    # 不敏感且有把握 → NON_SENSITIVE
    # 其餘 → UNCERTAIN

class PrivacyModel(Protocol):
    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement: ...

class VlmGate:                        # 唯一真閘門：永遠讀檔、不看檔名
    def __init__(self, model: PrivacyModel) -> None: ...
    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict: ...
    # filename 只給呼叫端／假件記帳；verdict 不得依賴它
    # load_bytes 失敗 → UNCERTAIN
    # Phase 75 才在問模型前 shrink_for_model（長邊 <= 512、PNG）

class OllamaPrivacyModel:             # Phase 75：跟 AI_BACKEND 走，模型同 get_vlm
    def __init__(self, *, backend: str | None = None) -> None: ...
    @property
    def timing_target(self) -> AiTarget: ...
    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement: ...

def shrink_for_model(image_bytes: bytes) -> bytes: ...  # Phase 75；長邊 <= 512、輸出 PNG
```

```python
# app/services/ingest_job.py（Phase 76 重構；run_ingest_job 簽章一個字都不改）
@dataclass(frozen=True, slots=True)
class PromptContext:
    folders: list[dict]
    entities: list[dict]
    corrections: list[dict]
    inbox_name: str

def load_prompt_context() -> PromptContext: ...

def embed_understanding(
    understanding: vlm_service.PhotoUnderstanding, *, embeddings: Embeddings, inbox_name: str
) -> list[float]: ...

def insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    entities: list[dict],
    uploaded_at: datetime | None,
) -> int: ...

def finish_image_job(job_id: str, photo_id: int, *, store: JobStore, content_type: str) -> None: ...

def fail_job(job_id: str, message: str, *, store: JobStore, content_type: str) -> None: ...
```

```python
# app/services/cloud_ingest.py（Phase 77 建；79／80 補本體；89 加 Ec2Probe）
@dataclass(frozen=True, slots=True)
class MailboxMessage:                 # ★ 定義在這裡（Phase 77），aws_mailbox.py（83）從這裡 import
    job_id: str                       #   ——77 的 FakeMailbox 就要回傳它，那時 boto3 還沒裝
    s3_key: str | None
    receipt_handle: str

class CloudMailbox(Protocol):         # 一份 Protocol 涵蓋本機端＋工人端全部操作（AwsMailbox／FakeMailbox 都實作）
    def put_object(self, key: str, body: bytes, content_type: str) -> None: ...
    def get_object(self, key: str) -> bytes | None: ...
    def delete_objects(self, keys: list[str]) -> None: ...
    def send_job(self, job_id: str, s3_key: str) -> None: ...
    def receive_job(self, wait_seconds: int) -> MailboxMessage | None: ...      # 工人端（87）
    def delete_job_message(self, receipt_handle: str) -> None: ...             # 工人端（87）
    def send_result(self, job_id: str) -> None: ...
    def receive_result(self, wait_seconds: int) -> MailboxMessage | None: ...
    def delete_result_message(self, receipt_handle: str) -> None: ...
    def release_result_message(self, receipt_handle: str) -> None: ...
    def input_key(self, job_id: str, content_type: str) -> str: ...
    def context_key(self, job_id: str) -> str: ...
    def result_key(self, job_id: str) -> str: ...
    def instance_state(self, instance_id: str) -> str: ...   # Phase 89 的 Ec2Probe 用；工人端用不到

class RemoteProbe(Protocol):
    def is_running(self) -> bool: ...

class AlwaysRunning:                  # CLOUD_ROUTE=assume 用
    def is_running(self) -> bool: ...

class Ec2Probe:                       # Phase 89；TTL 快取比照 camera_session_service 的 _now() seam
    def __init__(
        self, mailbox: CloudMailbox, instance_id: str, *, ttl_seconds: int
    ) -> None: ...
    def is_running(self) -> bool: ...

class CloudRoute:
    def __init__(
        self, mailbox: CloudMailbox, probe: RemoteProbe, *, timeout_seconds: int
    ) -> None: ...
    def available(self) -> bool: ...
    def submit(
        self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict
    ) -> None: ...
    def fetch_result(self, job_id: str) -> dict | None: ...
    def wait_result(self, job_id: str, *, store: JobStore) -> dict | None: ...
    def cleanup(self, job_id: str) -> None: ...

# available() 恆 False；其餘方法一律 raise RuntimeError("雲端路未啟用")
class CloudRouteOff:
    def available(self) -> bool: ...

def build_context(prompt_context: PromptContext) -> dict: ...
```

```python
# app/services/gated_ingest.py（Phase 78 建；79／80／81 補分支）
def run_gated_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    gate: PrivacyGate,
    cloud: CloudRoute | CloudRouteOff,
) -> None: ...
```

```python
# app/services/aws_mailbox.py（Phase 83；★ 全系統唯一 import boto3 的地方）
from app.services.cloud_ingest import MailboxMessage   # 定義在 cloud_ingest.py（77），這裡只 import

class AwsMailbox:
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
    ) -> None: ...
    def input_key(self, job_id: str, content_type: str) -> str: ...
    def context_key(self, job_id: str) -> str: ...
    def result_key(self, job_id: str) -> str: ...
    def put_object(self, key: str, body: bytes, content_type: str) -> None: ...
    def get_object(self, key: str) -> bytes | None: ...
    def delete_objects(self, keys: list[str]) -> None: ...
    def send_job(self, job_id: str, s3_key: str) -> None: ...
    def receive_job(self, wait_seconds: int) -> MailboxMessage | None: ...
    def delete_job_message(self, receipt_handle: str) -> None: ...
    def send_result(self, job_id: str) -> None: ...
    def receive_result(self, wait_seconds: int) -> MailboxMessage | None: ...
    def delete_result_message(self, receipt_handle: str) -> None: ...
    def release_result_message(self, receipt_handle: str) -> None: ...
    def instance_state(self, instance_id: str) -> str: ...
```

```python
# app/workers/cloud_worker.py（Phase 87 建、88 加主迴圈）
def process_job_message(
    mailbox: CloudMailbox, message: MailboxMessage, vlm: vlm_service.VLMClient
) -> None: ...

# Phase 88：主迴圈（可注入停止判斷，測試才不會無限等）；receive_job(20) 回 None 就繼續、
# 單則例外 logger.exception 後繼續、should_stop() 為 True 才離開
def run_forever(
    mailbox: CloudMailbox, vlm: vlm_service.VLMClient, *, should_stop: Callable[[], bool]
) -> None: ...

def main() -> None: ...   # 組 AwsMailbox（boto3 import 在函式內）＋ OllamaCloudVLM，接 SIGTERM／SIGINT 後呼叫 run_forever
# 可執行：python -m app.workers.cloud_worker
# ⛔ 本模組不得 import：photo_repository／app.db／資料庫驅動程式（套件名刻意不寫：design3 掃碼對 app/ 全樹做子字串比對）／celery／redis（D11、D13）
```

```python
# app/dependencies.py 新增（74／77／86／89）
def get_privacy_gate() -> privacy_gate.PrivacyGate: ...
# Phase 75（§10.2 追認項 S）：worker 行程的 config.AI_BACKEND 永遠是 "local"，閘門要跟頁首開關走（D6）
# 只能用入列快照 job["ai_backend"]（D14）——寫法比照既有 build_vlm_for_backend；
# get_privacy_gate() ＝ build_privacy_gate_for_backend(config.AI_BACKEND)（web 行程／測試用）
def build_privacy_gate_for_backend(ai_backend: str) -> privacy_gate.PrivacyGate: ...
def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff: ...
# Phase 89：ec2 模式的 CloudRoute 用 @lru_cache(maxsize=1) 的 _ec2_cloud_route() 建一次共用——
# Ec2Probe 的 TTL 快取是物件身上的狀態，每個任務都 new 一顆的話 D10「快取可短 TTL」形同虛設
# （手法比照既有 _ollama_vlm()；代價：改 .env 要 restart worker）。
```

#### 2.4.2 設定（`app/core/config.py`；`.env` 只寫變數名，**永遠不寫值**）

| 變數 | 預設 | 用途 |
|---|---|---|
| `CLOUD_ROUTE` | `off` | `off`＝不走雲端（pytest 與新 clone 的預設）；`assume`＝假設遠端開著（丁）；`ec2`＝用 `DescribeInstances` 判斷（戊之後） |
| `AWS_REGION` | `ap-northeast-1` | 東京。boto3 client 一律**明傳** `region_name=config.AWS_REGION` |
| `AWS_ACCESS_KEY_ID` | （空） | boto3 標準變數名，只放 `.env`；EC2 用 instance role，**不放 key** |
| `AWS_SECRET_ACCESS_KEY` | （空） | 同上。config **不另存副本**（讓 boto3 自己讀環境變數） |
| `AWS_ENDPOINT_URL` | （不設） | boto3 標準變數；只在 pytest 第五道安全網與「零依賴實證」設成死埠 |
| `S3_BUCKET` | （空） | 寄物櫃 bucket 名 |
| `SQS_JOBS_QUEUE_URL` | （空） | jobs 佇列 URL |
| `SQS_RESULTS_QUEUE_URL` | （空） | results 佇列 URL |
| `EC2_WORKER_INSTANCE_ID` | （空） | `CLOUD_ROUTE=ec2` 時探測的實例 |
| `EC2_PROBE_TTL_SECONDS` | `60` | `DescribeInstances` 結果快取秒數（D10 第 1 條「快取可短 TTL」） |
| `CLOUD_RESULT_TIMEOUT_SECONDS` | `300` | 送出後最多等 results 幾秒，到了→D10 fallback |
| `WORKER_VERSION` | `dev` | 只給 cloud_worker：build 時由 `ARG GIT_SHA` 烙進去，啟動 log 印出 |

> **`.env.example` 若不存在就不要新建**（既有做法是在 `CLAUDE.md`／`README.md` 列變數名）。
> 讀環境變數**只在 `app/core/config.py`**；程式碼裡一律 `config.X` 即時讀，
> **不要** `from app.core.config import X`（那樣會在 import 當下定死值，測試改不動）。

#### 2.4.3 S3 鍵名與 SQS 訊息（契約）

```text
S3（bucket private、Block Public Access 四項全開、SSE-S3、Lifecycle documents/ 2 天過期）
  documents/{job_id}/input.jpg | input.png | input.pdf   <- 本機 Put、工人 Get
  documents/{job_id}/context.json                        <- 本機 Put、工人 Get（總覽 §10 追認項 a）
  documents/{job_id}/result.json                         <- 工人 Put、本機 Get

SQS jobs     body = {"job_id": "...", "s3_key": "documents/<id>/input.jpg"}
             本機 Send、工人 Receive/Delete
SQS results  body = {"job_id": "..."}
             工人 Send、本機 Receive/Delete/ChangeMessageVisibility

⛔ 兩條佇列的 body 都**只有字串**，一個位元組都沒有（design6 §0 第 2 條禁止）。
```

`context.json` ＝ `load_prompt_context()` 的三份清單，
用 `json.dumps(..., ensure_ascii=False, default=str)` 序列化：

```json
{"folders": [], "entities": [], "corrections": []}
```

工人靠它組出**同一份** `build_vlm_prompt(folders, entities, corrections)`；
**缺檔時三份都當空清單**（不是失敗——沒有它也看得懂圖，只是少了資料夾建議）。

`result.json`（**不含 embedding**，D13：向量一律本機 bge-m3）：

```json
{"job_id": "...", "worker_version": "...", "kind": "image",
 "understood": true, "attempts": 1,
 "understanding": {"understood": true, "text": "...", "category": null, "location": null,
                   "items": [], "content_time": null, "entity": null,
                   "task_title": null, "task_due": null}}
```

```json
{"job_id": "...", "worker_version": "...", "kind": "pdf",
 "pages": [{"page": 1, "understood": true, "attempts": 1, "understanding": {}},
           {"page": 2, "understood": false, "attempts": 3, "understanding": null}]}
```

PDF 拆不開 → `"pages": []`（本機依既有規則標 failed：`ERROR_PDF_UNREADABLE`）。

#### 2.4.4 `IngestJob` 兩個新欄位（`GET /ingest-jobs` 回應**不變**）

```python
class IngestJob(TypedDict, total=False):
    # ... 既有 11 個欄位一字不改 ...
    privacy: str  # Verdict 的值："SENSITIVE" / "NON_SENSITIVE" / "UNCERTAIN"
    route: str    # "local" / "cloud"
```

`JOB_STATUSES` **仍是四個**（`queued`／`analyzing`／`retrying`／`failed`），
**不新增 `waiting_cloud` 之類的狀態**——等雲端結果時 status 就停在 `analyzing`
（總覽 §10 追認項 D）。`IngestJobOut` 與端點回應形狀完全不變，使用者看不到 `route`。

#### 2.4.5 測試假件（`tests/fakes.py`；名稱是契約，各 phase 逐字沿用）

| 假件 | 誰建 | 長相與用途 |
|---|---|---|
| `FakePrivacyGate(verdict)` | **74** | 固定回一個 `Verdict`；記 `calls`（次數）與 `last_filename`。`wire_fake_ai` 預設掛 `FakePrivacyGate(Verdict.UNCERTAIN)`＝全部走本機，**既有 543 顆行為零改變** |
| `FakePrivacyModel(judgement, *, raise_on_judge=False)` | **74**（75 直接用） | 固定回一個 `PrivacyJudgement`（**不是** `Verdict`）；記 `calls`／`last_image_bytes`／`last_content_type`；`raise_on_judge=True` 讓 `judge()` 丟例外（74 的 `test_模型丟例外回UNCERTAIN`）；`last_image_bytes` 讓 75 的 `test_送進模型的圖長邊不超過512` 用 Pillow 讀回來驗 |
| `FakeMailbox()` | **77** | **一顆假件同時扮演 S3 ＋ 兩條佇列**：`objects: dict[str, bytes]`、`jobs: list`、`results: list`，計數器 `put_calls`／`get_calls`／`send_job_calls`／`send_result_calls`／`delete_calls`；另有 `instance_state_script: list[str]`（`instance_state()` 依序回傳，用完重複最後一個；預設 `["running"]`）與 `instance_state_calls` 計數——Phase 89 的 `Ec2Probe` 測試靠它數 `DescribeInstances` 被叫了幾次；以及 `calls: list[str]` **呼叫流水帳**（每個方法被叫時 append 一行如 `"put_object documents/x/result.json"`），Phase 79 的「submit 順序 context→input→jobs」與 Phase 87 的「result 先 Put 才 Send」都靠它斷言先後。同時給**本機端與工人端**用——Phase 87 的端到端測試就是「本機送出 → `process_job_message` 處理同一顆 `FakeMailbox` → 本機收回入庫」 |
| `FakeProbe(running)` | **77** | `is_running()` 固定回 `True`／`False`；也可設成丟例外（測 fallback） |
| `ScriptedProbe([...])` | **77** | `is_running()` 依序回一串答案（用完重複最後一個），給 `CloudRoute(…, probe)` 的「第一次可用、第二次不可用」這類流程測試用。⚠ **不是**給 `Ec2Probe` 的 TTL 測試用——那組靠 `FakeMailbox.instance_state_script`＋`instance_state_calls` |
| `FakeCloudRoute(available)` | **77** | **只在 Phase 77／78** 需要「`available()` 為 True 但不真的送」時用。**79 起一律改用 `CloudRoute(FakeMailbox(), FakeProbe(True))` 測真實作**——假的路只能證明分支走對，證明不了契約 |
| `fake_worker_process_one(mailbox, understanding)` | **79**（**81** 加 PDF） | 假工人 helper：把 `mailbox.jobs` 裡的第一則訊息變成 `result.json` ＋ 一則 results 訊息。它**不是** `cloud_worker`（那是 87 的事），只是「有人在另一頭做事」的最小替身 |

### 2.5 `run_gated_ingest_job` 的流程與 `wait_result` 的五條規則

**gate／cloud 從哪來（§10.2 S）：** `celery_app.ingest_task` 用 `dependencies.build_privacy_gate_for_backend(job["ai_backend"])` 建閘門（worker 行程的 `config.AI_BACKEND` 永遠是 local，只能用入列快照）、用 `dependencies.get_cloud_route()` 建雲端路；pytest 由 conftest 以 monkeypatch **雙名**（`get_privacy_gate`＋`build_privacy_gate_for_backend`）換成 `FakePrivacyGate`、第五道安全網換成 `CloudRouteOff()`。

```text
job = store.get(job_id)；None -> log 後 return（與 run_ingest_job 同語意）
store.update(job_id, status="analyzing")
route = job.get("route")

  route == "local" -> run_ingest_job(...)          <- 崩潰重送，不再問閘門（§2.1 禁止）
  route == "cloud" -> r = cloud.fetch_result(job_id)
        r 有 -> 走「用結果落庫」
        r 無 -> cleanup、route=local、log "fallback=local reason=redelivered_without_result"
                -> run_ingest_job
  route 沒有（第一次）：
        verdict = gate.classify(filename=…, content_type=…, load_bytes=lambda: read_staging(…))
        store.update(job_id, privacy=verdict.value)
        verdict != NON_SENSITIVE -> route=local、log "route=local verdict=…"、run_ingest_job、return
        not cloud.available()    -> route=local、log "fallback=local reason=remote_unavailable"
                                    -> run_ingest_job、return
        store.update(job_id, route="cloud")；log "route=cloud verdict=NON_SENSITIVE"（Demo 2 靠這一行對帳）
        try: cloud.submit(…)
        except -> cloud.cleanup、route=local、log "fallback=local reason=submit_failed"
                  -> run_ingest_job、return
        result = cloud.wait_result(job_id, store=store)
        result is None -> cloud.cleanup、route=local、log "fallback=local reason=result_timeout"
                          -> run_ingest_job、return
        用結果落庫：
          image: understood False -> fail_job ＋ cleanup
                 understood True  -> embed_understanding（最多 VLM_MAX_ATTEMPTS 次，只重算向量）
                                     -> insert_photo_with_files
                                     -> store.update(photo_ids=[photo_id])   ★ 先寫收據（§10.2 R）
                                     -> cleanup -> finish_image_job
          pdf  : 本機 render_pages 拿每頁 PNG，與 result["pages"] 逐頁配對；
                 沿用 pages_done／photo_ids 續跑、跳頁、0 頁成功＝整筆失敗
```

`fallback=local reason=…` 的 log 字樣是**契約**（design6 §2.1 明文），測試用 `caplog` 釘。
**Fallback 時絕不再跑一次 classifier**（design6 §2.1 的禁止）。

`wait_result(job_id, *, store)` 的五條規則（Phase 80 完整落地）：

1. 迴圈直到 deadline（`CLOUD_RESULT_TIMEOUT_SECONDS`）：`receive_result(wait_seconds=min(20, 剩餘秒數))`。
2. 收到的 `job_id == 我的`：`get_object(result_key)`；
   有 → 解析成 dict、`delete_result_message`、回傳 dict；
   沒有（工人說寫好了卻找不到）→ `delete_result_message`、回 `None`（＝當逾時處理 → fallback）。
3. 收到**別人的** `job_id`：查 `store.get(那個 id)`——
   `None`（早就做完或被 dismiss）**或** `route == "local"`（那筆已 fallback）
   → 這是遲到的殘訊息：`delete_result_message` ＋ 盡力刪它的三個 S3 物件；
   否則（那筆還在雲端路等）→ `release_result_message`（可見度改 0，立刻還給它的主人）＋ `sleep(1)` 再繼續。
4. deadline 到仍無 → 回 `None`。
5. 每則訊息 body 只解析 `job_id`，**不含位元組**（測試釘住）。

### 2.6 工人（`process_job_message`）的處理規則

```text
1. get_object(result_key) 已存在 -> 冪等：send_result、delete_job_message、return（D17）
2. get_object(input) 是 None     -> 本機已 fallback 並清掉：delete_job_message、return（什麼都不寫）
2b. s3_key 是空的、或副檔名不是 .jpg／.png／.pdf -> 壞訊息：log warning、delete_job_message、return（Phase 87 補的防禦規則；總覽 §10.2 K）
3. context = get_object(context_key)（None -> 三份空清單）
4. content_type 由 s3_key 副檔名推（.jpg->image/jpeg、.png->image/png、.pdf->application/pdf）
5. image：OllamaCloudVLM.understand 最多 config.VLM_MAX_ATTEMPTS 次
          （understood=False 或例外都算一次；ai_timing kind=vlm backend=cloud）
   pdf  ：pdf_service.render_pages；拆不開 -> pages=[]；每頁各最多 3 次
6. put_object(result_key, json) -> send_result(job_id) -> delete_job_message
   ★ 順序鐵律：result 先落地才 Send（D9「PutObject 成功後才 Send」）
```

工人只 import `aws_mailbox`、`vlm_service`（`OllamaCloudVLM`）、`pdf_service`、`ai_timing`、`config`。

### 2.7 每個 phase 的契約：動到的檔與逐顆測試名

> 📌 **這一節是 22 份 phase 檔的測試清單來源。** phase writer **逐字沿用**測試名與顆數；
> 真的必須多加一顆時可以加，但要在該 phase 檔的 §8「完成後的專案狀態」明寫
> 「比總覽多 N 顆」。**不准為了湊數字刪測試。**

#### Phase 74 · 階段甲 · +11 顆（累計 554）

**動到的檔：** `app/services/privacy_gate.py`（新）、`app/dependencies.py`、
`tests/fakes.py`、`tests/conftest.py`、`tests/unit/test_privacy_gate_unit.py`（新）

**新增測試（`tests/unit/test_privacy_gate_unit.py`，11 顆）：**

`test_模型說敏感回SENSITIVE`、`test_模型說不敏感而且有把握回NON_SENSITIVE`、`test_模型說不敏感但沒把握回UNCERTAIN`、`test_模型丟例外回UNCERTAIN`、`test_讀檔失敗回UNCERTAIN`、`test_檔名完全不影響判斷`、`test_會呼叫load_bytes`、`test_get_privacy_gate回VlmGate`、`test_FakePrivacyGate固定回傳指定verdict`、`test_sensitive即使沒把握也當SENSITIVE`、`test_wire_fake_ai預設掛UNCERTAIN`

#### Phase 75 · 階段甲 · +10 顆（累計 564）

**動到的檔：** `app/services/privacy_gate.py`、`app/services/ai_timing.py`、`app/dependencies.py`、
`tests/unit/test_privacy_gate_unit.py`、`tests/unit/test_ai_timing_unit.py`（`tests/fakes.py` 的 `FakePrivacyModel` 74 已建，75 不動）

**新增測試（`test_privacy_gate_unit.py` 9 顆 ＋ `test_ai_timing_unit.py` 1 顆）：**

`test_送進模型的圖長邊不超過512`、`test_本機後端用本機VLM模型名`、`test_雲端後端用雲端VLM模型名`、`test_短prompt不含完整understand欄位`、`test_PDF渲染第一頁再問`、`test_PDF渲染失敗回UNCERTAIN`、`test_縮圖失敗回UNCERTAIN`、`test_get_privacy_gate跟AI_BACKEND走`、`test_閘門不准寫入AI_BACKEND`、`test_privacy這個kind也有前後兩行log`（在 `test_ai_timing_unit.py`）

#### Phase 76 · 階段甲 · +4 顆（累計 568）

**動到的檔：** `app/services/ingest_job.py`、`tests/integration/test_ingest_job.py`

**新增測試（`tests/integration/test_ingest_job.py` 追加 4 顆）：**

`test_load_prompt_context讀回三份清單且收件箱名稱正確`、`test_embed_understanding用收件箱名稱組文件`、`test_finish_image_job的順序是先寫photo_ids再刪staging最後刪job`、`test_fail_job標failed但不刪job`

> ⚠️ **本 phase 的核心驗收是「既有顆數（本次排在 74／75 之後＝564）一顆都不能改」**：
> **與開工快照相減後**（鐵律 12：各 phase 不 commit，74／75 的 `fakes.py`／`conftest.py` 改動會一起出現在 `git diff`），
> `tests/` 底下只准多出 `test_ingest_job.py` 的改動、而且**零刪除行**（phase-76 §6 用 `comm -13` 做這個相減）。

#### Phase 77 · 階段甲 · +12 顆（累計 580）

**動到的檔：** `app/services/cloud_ingest.py`（新）、`app/core/config.py`、`app/dependencies.py`、
`app/services/ingest_job_store.py`、`tests/fakes.py`、`tests/conftest.py`、
`tests/unit/test_cloud_ingest_unit.py`（新）、`tests/unit/test_ingest_job_store_unit.py`

**新增測試（`test_cloud_ingest_unit.py` 11 顆 ＋ `test_ingest_job_store_unit.py` 1 顆）：**

`test_CloudRouteOff的available恆為False`、`test_CloudRouteOff其餘方法一律raise`、`test_AlwaysRunning恆為True`、`test_build_context恰三鍵而且可以json序列化`、`test_build_context不含任何位元組`、`test_FakeMailbox的put與get與delete物件行為`、`test_FakeMailbox的jobs佇列send後receive再delete`、`test_FakeMailbox的results佇列release之後可以再收到`、`test_FakeMailbox佇列空的時候receive回None`、`test_get_cloud_route預設off時回CloudRouteOff`、`test_第五道安全網把CLOUD_ROUTE蓋成off且AWS_ENDPOINT_URL是死埠`、`test_job可以存取privacy與route兩個新欄位`（在 `test_ingest_job_store_unit.py`）

> `get_cloud_route()` 此時**只認 `off`**，`assume`／`ec2` 先 `raise NotImplementedError`
> ——這是本增量**唯二**允許的暫時分支（另一處在 Phase 78），86／89 各自換掉它一半。

#### Phase 78 · 階段甲 · +9 顆（累計 589）

**動到的檔：** `app/services/gated_ingest.py`（新）、`app/celery_app.py`、`tests/conftest.py`、
`tests/integration/test_gated_ingest.py`（新）、`tests/unit/test_celery_app_unit.py`

**新增測試（`test_gated_ingest.py` 8 顆 ＋ `test_celery_app_unit.py` 1 顆）：**

`test_敏感照片走本機_零submit_job記下privacy與route`、`test_不確定照片走本機_零submit`、`test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable`、`test_非敏感但探測丟例外_同樣fallback本機`、`test_崩潰重送時route已是local就不再問閘門`、`test_job不存在時安靜結束`、`test_一進門status就變analyzing`、`test_閘門收到的檔名就是job裡的filename`、`test_ingest_task把gate與cloud都傳進去`（在 `test_celery_app_unit.py`）

> 本 phase 只做到「`cloud.available()` 為 False」與「verdict != NON_SENSITIVE」兩條分支；
> 「非敏感 ＋ 遠端可用」那條先 `raise NotImplementedError("Phase 79")`，**79 必須換掉**。
> `celery_app.ingest_task` 建閘門用 `dependencies.build_privacy_gate_for_backend(job["ai_backend"])`（§10.2 S）；`test_ingest_task把gate與cloud都傳進去` 同時斷言這件事（不另加顆）。

#### Phase 79 · 階段甲 · +10 顆（累計 599）

**動到的檔：** `app/services/cloud_ingest.py`、`app/services/gated_ingest.py`、`tests/fakes.py`
（假工人 helper `fake_worker_process_one(mailbox, understanding)`）、
`tests/unit/test_cloud_ingest_unit.py`、`tests/integration/test_gated_ingest.py`

**新增測試（`test_cloud_ingest_unit.py` 4 顆 ＋ `test_gated_ingest.py` 6 顆）：**

`test_submit的順序是先context再input最後jobs`、`test_jobs訊息恰兩鍵而且不含位元組`、`test_input鍵名依content_type決定副檔名`、`test_cleanup會刪掉三個S3物件`、`test_非敏感且遠端開著_雲端結果回來後本機入庫`、`test_雲端入庫後S3三物件與results訊息都被清掉`、`test_雲端結果說看不懂_job標failed且不留照片`、`test_本機轉向量三次都失敗_不會再叫工人重看圖`、`test_雲端路的計時log裡embed是本機`、`test_submit丟例外時fallback本機而且cleanup被呼叫`

#### Phase 80 · 階段甲 · +10 顆（累計 609）

**動到的檔：** `app/services/cloud_ingest.py`、`app/services/gated_ingest.py`、
`tests/unit/test_cloud_ingest_unit.py`、`tests/integration/test_gated_ingest.py`

**新增測試（`test_cloud_ingest_unit.py` 5 顆 ＋ `test_gated_ingest.py` 5 顆）：**

`test_wait_result每次等待的秒數都不超過20`、`test_收到別人的訊息而那筆還在雲端路時把訊息還回去`、`test_收到別人的訊息而那筆已不在store時刪訊息也刪S3`、`test_收到別人的訊息而那筆已改走本機時刪訊息也刪S3`、`test_自己的訊息但result_json不在時回None`、`test_逾時沒有結果_fallback本機且log有reason_result_timeout`、`test_同一個job_id的結果送兩次_照片仍然只有一列`、`test_崩潰重送route是cloud而且S3有結果_直接落庫零submit`、`test_崩潰重送route是cloud但S3沒有結果_fallback本機`、`test_逾時fallback之前會先清掉S3物件`

#### Phase 81 · 階段甲 · +7 顆（累計 616；**2026-09-02 實查：開工基線 613、核心 +7、R4 +2、review 裁決 R11 守門測試 +2、累計 624**）

**動到的檔：** `app/services/gated_ingest.py`、`tests/fakes.py`（假工人支援 PDF）、
`tests/integration/test_gated_ingest_pdf.py`（新）；**2026-09-02 裁決 R4 再加** `app/services/pdf_service.py`（`render_pages(..., max_pages=None)`）、`app/services/privacy_gate.py`（閘門 PDF 分支 `max_pages=1`）與兩顆單元測試 `test_max_pages只渲染前幾頁`／`test_PDF閘門只渲染第一頁`（phase0901 ledger Task 2 parked minor ＋ FINAL review M5 留給 81 的項目）。
> 📌 **2026-09-02 校準紀錄**：識別字一律英文（產品負責人指示；`_用雲端結果落庫`→`_store_cloud_result`、`_PDF用結果落庫`→`_store_pdf_result`、`_落一頁`→`_store_pdf_page`、測試工具 `WorkerMailbox`／`create_pdf_job`／`cloud_route`／`run`…；命名契約在 `.superpowers/sdd/phase0902/brief-common.md` §5）；`test_中文` 測試名維持。
> ⚠ **81 的 `gated_ingest.py` 一律以 Phase 80 落地版（工作樹實檔）為基準只加 PDF 分支，不要照 81 計畫檔的整檔區塊重貼**（81 成稿早於 80 的三處實作裁決）：必須保留 `_resume_cloud_route` 落庫前重讀那一行（`latest_job = store.get(job_id) or job`，D17 最後一道保險；校準 E／F 發現）、`_best_effort_cloud_cleanup`、**R14 的 `cloud.wait_result(...)` try/except（信箱例外 → 視為 result_timeout）**、以及 `_parse_understanding()` 註解的「多餘鍵會被忽略」措辭（函式名為 2026-09-02 英文化後的實檔名）。派 81 前先 diff 81 計畫檔的重貼碼與實檔，把差異搬進計畫檔。

**新增測試（`test_gated_ingest_pdf.py` 7 顆）：**

`test_兩頁都成功_入庫兩列_job被刪_S3清空`、`test_第二頁看不懂_只入庫一列_跳過一頁`、`test_pages是空清單_job標failed且錯誤是PDF讀不開`、`test_全部頁都失敗_job標failed`、`test_崩潰重送從pages_done續跑不重插`、`test_PDF判定敏感時零submit走本機`、`test_submit的input鍵名是input點pdf`

**★G1 在本 phase 之後。**

#### Phase 82 · 階段乙 · +0 顆（累計 616）

**動到的檔：** `deploy/aws/mac-policy.json`（新）、`.env`（本機，不入版控）、`CLAUDE.md`（指令區加「AWS」小段）

**新增測試：** 無（人工操作 phase）。驗收＝指令輸出（§5「費用／安全」前兩條）。

#### Phase 83 · 階段乙 · +16 顆（累計 632；**2026-09-02 實查基線 624 → 640；review fix wave +1 守門測試 → 641**）

**動到的檔：** `requirements.txt`、`app/services/aws_mailbox.py`（新）、
`tests/unit/test_aws_mailbox_unit.py`（新）、`tests/integration/test_design5_error_paths.py`（**改一顆**）

**新增測試（`test_aws_mailbox_unit.py` 16 顆）：**

`test_input_key依content_type給副檔名`、`test_context_key與result_key的路徑`、`test_put_object帶ContentType`、`test_get_object遇到NoSuchKey回None`、`test_get_object遇到其他錯誤照樣往外丟`、`test_delete_objects失敗只記log不往外丟`、`test_send_job的body恰兩鍵`、`test_receive_job的等待秒數不超過20`、`test_receive_job沒訊息時回None`、`test_delete_job_message帶receipt_handle`、`test_release_result_message把可見度改成0`、`test_send_result的body恰一鍵`、`test_get_object拿得回位元組而delete_objects送出鍵清單`（成功路徑；沒有它「get_object 永遠回 None」的實作會 15 顆全綠）、`test_instance_state讀得到狀態名`、`test_instance_state查無回unknown`、`test_boto3只在aws_mailbox裡出現`（掃碼；`app/` 全樹）

**改一顆（不計顆）：** `test_design5_error_paths.py::test_沒有背景任務框架的替代品也沒有雲端儲存`
——把 `boto3` 從禁止清單拿掉、註解引 design6 §1.1 第 1 列，
**`s3fs`／`minio`／`google-cloud-storage`／`flower` 仍然禁止**。

#### Phase 84 · 階段乙 · +0 顆（累計 632；實 641）

**動到的檔：** `deploy/aws/s3-lifecycle.json`（新）、`scripts/aws_check.py`（新）、`.env`

**新增測試：** 無。驗收＝`aws s3api get-public-access-block`／`get-bucket-encryption`／
`get-bucket-lifecycle-configuration` 的輸出 ＋ `python scripts/aws_check.py s3` 印 OK。

#### Phase 85 · 階段丙 · +0 顆（累計 632；實 641）

**動到的檔：** `scripts/aws_check.py`（加 `sqs` 子命令）、`.env`

**新增測試：** 無。驗收＝`aws sqs get-queue-attributes` 兩條 ＋ `python scripts/aws_check.py sqs` 印 OK；
results 佇列 `ApproximateNumberOfMessages` 為 `0`。

#### Phase 86 · 階段丙 · +2 顆（累計 634；**實 644**＝641＋2＋review fix wave 1）

**動到的檔：** `app/dependencies.py`、`tests/unit/test_dependencies_cloud_unit.py`（新）、`tests/unit/test_cloud_ingest_unit.py`（拆掉 Phase 77 鬧鐘測試的 `assume` 半邊，改不計顆）、`LAUNCH.md`

**新增測試（`test_dependencies_cloud_unit.py` 2 顆）：**

`test_assume模式建出CloudRoute而且探測恆為True`、`test_assume模式的逾時秒數讀config`

**人工煙霧（本 phase 的重頭戲）：** `CLOUD_ROUTE=assume` ＋ `CLOUD_RESULT_TIMEOUT_SECONDS=30`
傳一張**內容**非敏感的合成收據 PNG（2026-09-01 改判後閘門看圖不看檔名；檔名只是記帳）→ S3 曾出現 input ＋ context、jobs 佇列 1 則、
results 0 則 → 30 秒後 fallback 本機入庫、S3 清空、worker log 有 `fallback=local reason=result_timeout`；
再傳一張**內容**是身分證的合成圖 → 零 S3；最後 `aws sqs purge-queue` 清 jobs。

#### Phase 87 · 階段丁 · +12 顆（累計 646）

**動到的檔：** `app/workers/__init__.py`（新）、`app/workers/cloud_worker.py`（新）、
`tests/unit/test_cloud_worker_unit.py`（新）、`tests/integration/test_cloud_roundtrip.py`（新）

**新增測試（`test_cloud_worker_unit.py` 10 顆 ＋ `test_cloud_roundtrip.py` 2 顆）：**

`test_result先PutObject才SendMessage`、`test_看圖三次都失敗_result標understood_false而且attempts是3`、`test_一次就成功_attempts是1`、`test_result已存在時不看圖只補送results並刪jobs訊息`、`test_input不在時只刪jobs訊息什麼都不寫`、`test_context缺檔時三份清單都當空的`、`test_content_type由s3_key的副檔名推出來`、`test_PDF拆不開時pages是空清單`、`test_PDF每一頁各自最多三次`、`test_工人不import資料庫與Celery與Redis`（掃碼）、`test_單圖端到端_本機送出_假工人處理_本機入庫`（在 `test_cloud_roundtrip.py`）、`test_PDF端到端_兩頁都回來_入庫兩列`（在 `test_cloud_roundtrip.py`）

#### Phase 88 · 階段丁 · +5 顆（累計 651）

**動到的檔：** `app/workers/cloud_worker.py`、`tests/unit/test_cloud_worker_unit.py`、
`LAUNCH.md`（新增 **§12** "Cloud worker on the Mac"，**英文**）、`CLAUDE.md`

**新增測試（`test_cloud_worker_unit.py` 追加 5 顆）：**

`test_主迴圈收到None時繼續等下一則`、`test_主迴圈收到訊息就呼叫process_job_message`、`test_停止旗標讓主迴圈退出`、`test_單次例外不會讓主迴圈死掉`、`test_啟動時印出version與region與bucket`

**人工端到端（丁的驗收）：** 終端機 A 跑 `python -m app.workers.cloud_worker`（讀 `.env`），
`CLOUD_ROUTE=assume` 上傳非敏感圖 → 真 S3／真 SQS／真 Ollama Cloud → 本機入庫；
敏感 → 本機；Ctrl+C 工人優雅停。

#### Phase 89 · 階段戊 · +7 顆（累計 658）

**動到的檔：** `app/services/cloud_ingest.py`、`app/dependencies.py`、
`tests/unit/test_cloud_ingest_unit.py`、`tests/unit/test_dependencies_cloud_unit.py`

**新增測試（`test_cloud_ingest_unit.py` 6 顆 ＋ `test_dependencies_cloud_unit.py` 1 顆）：**

`test_實例狀態running時探測為True`、`test_實例狀態stopped與stopping與pending都是False`、`test_探測丟例外時回False並留log`、`test_TTL內不會再打一次DescribeInstances`、`test_TTL過了會再打一次`、`test_instance_id是空的時候回False而且零呼叫`、`test_ec2模式建出CloudRoute而且探測是Ec2Probe`（在 `test_dependencies_cloud_unit.py`）

#### Phase 90 · 階段戊 · +4 顆（累計 662）

**動到的檔：** `Dockerfile`、`tests/integration/test_design6_error_paths.py`（**新檔，先放 Dockerfile 掃碼**）

**新增測試（`test_design6_error_paths.py` 4 顆）：**

`test_Dockerfile有cloud_worker這個target`、`test_Dockerfile的app階段在最後`、`test_Dockerfile的cloud_worker帶ARG_GIT_SHA`、`test_compose_yaml沒有新增服務也沒有AWS設定`

**人工：** `docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t personaldocai-worker:local .`
→ 用 `--env-file .env` 以容器跑工人，重做 Phase 88 的端到端；
`docker compose config` 與改版前逐字相同（compose 零改動的證明）。

**★G2 在本 phase 之後、91 之前。**

#### Phase 91 · 階段戊 · +0 顆（累計 662）

**動到的檔：** `deploy/aws/worker-role-trust.json`、`deploy/aws/worker-role-policy.json`、
`deploy/ec2/user-data.sh`、`deploy/ec2/personaldocai-worker.service`、`deploy/ec2/worker.env.example`（只有變數名）、
`.env`（`EC2_WORKER_INSTANCE_ID` 先留空）。**不建 `run-worker.sh`**（systemd 用 `ExecStartPre` 寫法，Phase 91 §3 明列理由）

**新增測試：** 無。驗收＝`aws ec2 describe-security-groups`（`IpPermissions` 為 `[]`）、
`aws iam get-role`、`aws ecr describe-images` 看得到 tag。**本 phase 尚未啟動實例。**

#### Phase 92 · 階段戊 · +0 顆（累計 662）

**動到的檔：** `.env`（填 `EC2_WORKER_INSTANCE_ID`、`CLOUD_ROUTE=ec2`）、
`LAUNCH.md`（新章節 **§13** "Cloud worker (EC2)"，英文；§12 已由 Phase 88 使用）、`CLAUDE.md`（指令區）、`README.md`（兩句改誠實）

**新增測試：** 無。驗收＝**Demo 2 ＋ Demo 2b**（§5.2、§5.3），做完 **Stop**。

**★G3 在本 phase 之後、93 之前。**

#### Phase 93 · 階段己 · +4 顆（累計 666）

**動到的檔：** `deploy/aws/github-oidc-trust.json`、`deploy/aws/github-deploy-policy.json`、
`tests/integration/test_design6_error_paths.py`

**新增測試（4 顆）：**

`test_OIDC信任文件的sub逐字鎖住main分支`、`test_OIDC信任文件沒有星號萬用字元`、`test_OIDC信任文件的aud是sts`、`test_部署用的policy裡沒有寫死帳號ID`

#### Phase 94 · 階段己 · +6 顆（累計 672）

**動到的檔：** `.github/workflows/deploy.yml`（新）、
`tests/integration/test_design6_error_paths.py`、`README.md`（CI/CD 段）

**新增測試（6 顆）：**

`test_CD綁在test工作流程成功之後`、`test_CD要求id_token寫入權限`、`test_CD只建linux_arm64的映像`、`test_CD打的是cloud_worker這個target`、`test_CD的tag含commit的sha`、`test_CD沒有寫死任何AWS金鑰`

**人工：** Demo 3（§5.4）。

> `deploy` job 的 `if` 是 **`github.event.workflow_run.event == 'push' && github.event.workflow_run.conclusion == 'success'`**——只看 conclusion 的話，fork PR 的分支若取名 `main`，`test.yml` 的 `pull_request` 觸發也會讓 `deploy` 在預設分支上下文拿到 secret 與 `id-token`（phase-94 reviewer 抓到，§10.2 M）。

#### Phase 95 · 收尾 · +10 顆（累計 **682**）

**動到的檔：** `tests/integration/test_design6_error_paths.py`、
`docs/plan/report/2026-XX-XX-增量六驗收包-請產品負責人確認.md`（新）、`docs/plan/todo/`
~~另（純註解校正）：`test_ingest_job_pdf.py` 的 `_fail`／`_insert_photo_with_files` 舊名~~ → **已於 2026-09-01 Phase 74〜80 收工的 final fix wave 修完**（連同 `test_ai_timing_log.py`／`test_folder_correction.py` 的「六個注入點」、`test_ingest_job.py` 的「四道」、`test_entity_suggestion_unit.py` 的「五種 kind」、`test_privacy_gate_unit.py` 的 `get_privacy_gate()` docstring），95 不必再處理
另（候選補測，Phase 80 review 發現、顆數留給 95）：① `route=cloud` 崩潰重送時 `cloud` 已是 `CloudRouteOff`（使用者半路把 `CLOUD_ROUTE` 改回 off）——`_繼續雲端路`／`_盡力清雲端` 的兩個 try 撐住整條路，目前零測試；② `_處理別人的訊息` 的 `store.get` 丟例外會被 R14 接成 result_timeout（行為安全但白費一趟）。

**新增測試（10 顆）：**

`test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣`、`test_compose沒有為了雲端新增任何服務`、`test_端點仍是22支而且openapi零DELETE`、`test_兩條佇列的訊息body都不含影像位元組`、`test_工人不寫Postgres也不算embedding`、`test_boto3唯一入口仍是aws_mailbox`（掃 `app/`＋`tests/`＋`scripts/` 三棵樹，只放行 `app/services/aws_mailbox.py`、`tests/unit/test_aws_mailbox_unit.py`、`scripts/aws_check.py`；83 那顆只掃 `app/`，兩顆不重複）、`test_photo表沒有為了雲端新增任何欄位`、`test_隱私閘門不會去碰AI後端開關`、`test_雲端看圖三次失敗是整筆失敗不是fallback本機`（**真缺口補測**）、`test_遠端不可用時上傳仍然回202不會變5xx`（**真缺口補測**）

---

### 2.8 AWS 資源名稱（全部東京 `ap-northeast-1`；名稱統一，phase 檔逐字沿用）

| 資源 | 名稱 | 關鍵設定 | 建於 |
|---|---|---|---|
| S3 bucket | `personaldocai-mailbox-<帳號後六碼>`（bucket 名全球唯一，所以帶後綴；文件一律用 `$S3_BUCKET`） | Block Public Access 四項全開、預設加密 SSE-S3（AES256）、Lifecycle：prefix `documents/` **2 天**過期、**不開**版本控制 | **84** |
| SQS jobs | `personaldocai-jobs` | Standard；`VisibilityTimeout=900`（工人看一份多頁 PDF 要時間）、`MessageRetentionPeriod` 4 天、`ReceiveMessageWaitTimeSeconds=20` | **85** |
| SQS results | `personaldocai-results` | Standard；`VisibilityTimeout=30`、其餘同上 | **85** |
| IAM user（CLI 用） | `personaldocai-admin`（掛 AWS 管理的 `AdministratorAccess`） | 只給 Mac 上的 `aws` CLI 建資源用，key 放 `aws configure` 的 default profile；**不進 `.env`、不進容器**。理由：`personaldocai-mac` 是最小權限，連 `s3:CreateBucket` 都沒有，Phase 84 第一條指令就會 AccessDenied（總覽 §10.2 I）。⚠ `.env` 載進 shell 之後要 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，不然環境變數會蓋掉 profile | **82** |
| IAM user（Mac 用） | `personaldocai-mac` ＋ policy `personaldocai-mac-policy`（`deploy/aws/mac-policy.json`） | **本機端**：S3 該 prefix 的 Put／Get／Delete；jobs 的 `SendMessage`；results 的 `Receive`／`Delete`／`ChangeMessageVisibility`；兩條佇列的 `GetQueueAttributes`；`ec2:DescribeInstances`。**＋工人端**（同一把 key 在 Phase 88／90 也要跑工人——這台 Mac 在 EC2 出現前同時扮演兩個角色，§10.2 N）：jobs 的 `ReceiveMessage`／`DeleteMessage`／`ChangeMessageVisibility`；results 的 `SendMessage`。access key 放 `.env`；**還要有 `s3:ListBucket`（Resource＝bucket ARN，不是 prefix）**——沒有它，對不存在的 key 做 `GetObject` 會回 **403 AccessDenied 而不是 404 NoSuchKey**，`get_object`「NoSuchKey→None」的判斷全壞（§10.2 P）；**沒有** `CreateBucket`／`sqs:PurgeQueue`（那些走 admin profile） | **82** |
| IAM role（EC2 用） | `personaldocai-worker-role` ＋ **同名** instance profile（`deploy/aws/worker-role-trust.json`／`worker-role-policy.json`；inline policy 名 `personaldocai-worker-inline`） | S3 該 prefix 的 Get／Put ＋ **bucket ARN 的 `s3:ListBucket`**（同 §10.2 P 的理由：工人的冪等檢查 `get_object(result_key)` 靠 404）；jobs 的 `Receive`／`Delete`／`ChangeMessageVisibility`；results 的 `Send`；ECR pull 三項 ＋ `ecr:GetAuthorizationToken`；managed policy `AmazonSSMManagedInstanceCore` | **91** |
| IAM role（GitHub OIDC） | `personaldocai-github-deploy`（`deploy/aws/github-oidc-trust.json`／`github-deploy-policy.json`；inline policy 名 `personaldocai-github-deploy-policy`） | trust：provider `token.actions.githubusercontent.com`、`aud=sts.amazonaws.com`、**`sub` 精確等於 `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`（不准 `*`；⚠ 這是 GitHub 2026-07-15 起新 repo 的「不可變主體」格式——owner 與 repo 各帶數字 ID，本 repo 2026-08-28 建立、`gh api repos/1104030360/personalDocAI/actions/oidc/customization/sub` 實查 `sub_claim_prefix` 就是它；design6 §6 寫的舊格式 `repo:OWNER/REPO:ref:…` 對這個 repo 永遠對不上，總覽 §10.2 M）**；policy：ECR push（`GetAuthorizationToken` ＋ repo 上的 Put／Initiate／Upload／Complete／BatchCheck／**BatchGetImage**）、`ssm:SendCommand`（資源＝該實例 ＋ document `AWS-RunShellScript`）、`ssm:GetCommandInvocation`、`ec2:DescribeInstances` | **93** |
| ECR repository | `personaldocai-worker`（private） | tag `<git-sha>` ＋ `latest` | **91** |
| EC2 instance | Name tag `personaldocai-worker` | `t4g.small`、AL2023 **arm64**（AMI 由 SSM 公開參數 `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64` 取得）、預設 VPC 公有子網、自動公有 IPv4、根碟 gp3 8 GB。**用完 Stop（不是 Terminate）** | **92** |
| Security group | `personaldocai-worker-sg` | **inbound 空**、outbound 只開 TCP 443 | **91** |
| VPC endpoint | （S3 Gateway，掛在預設路由表） | 免費；讓 S3 流量不出公網 | **91** |
| Budget | `personaldocai-budget` | 每月 $5，**實際與預測各設 80% 寄信** | **82**（開戶第一天） |
| systemd service | `personaldocai-worker.service`（`deploy/ec2/`） | `ExecStartPre` 做 `ecr get-login-password` 接管線給 `docker login` ＋ `docker pull …:latest`；`ExecStart` 前景 `docker run --rm --name cloud-worker --env-file /opt/personaldocai/worker.env`；`Restart=always`；`WantedBy=multi-user.target` | **91**（寫檔）、**92**（真的裝） |
| ⛔ 禁止建立 | NAT Gateway、Elastic IP（`allocate-address`）、ALB、RDS、ElastiCache、ECS、Fargate、Lambda、K8s、Organizations／Control Tower、SSE-KMS customer key、`--platform linux/amd64` 的 worker 映像 | — | **95** 掃碼 ＋ §5.5 的 CLI 檢查 |

> EC2 上的機密（`OLLAMA_API_KEY` 等）：用 **Session Manager** 登入後**手動**建
> `/opt/personaldocai/worker.env`（`chmod 600`），systemd 用 `EnvironmentFile=`／
> `docker run --env-file` 讀。**不用 Parameter Store**（少一個服務；總覽 §10 追認項 h）。

---

## 3. 覆蓋對照表（「一條不漏」的自我檢查證據）

### 3.1 design6.md 各節 → 落地的 phase

| design6 章節 | 內容 | 由誰落地 |
|---|---|---|
| §0 實作計劃總序 | 六段不可對調；六條禁止 | 本總覽 §1.4 全景圖、§4 三個閘門、§3.6 六禁醒目框；各 phase 開頭的門檻框 |
| §1 D1〜D17 | 已拍板決策 17 條 | 見 **§3.2**（17 條逐條） |
| §1.1 本增量推翻的舊決策 | 4 列 ＋ 未推翻清單 | 見 **§3.4** |
| §1.2 被否決（不要重開） | **11 列** | 見 **§3.5**；同時分散寫進各 phase 的「明確不做」表 |
| §2 流程 | 上傳→Celery→Gate→（本機｜雲端）→入庫的全景 | 本總覽 §1.5 對照圖、§2.5 流程規格；**78／79／80／81** 逐段落地 |
| §2.1 Fallback 契約 | 四種「遠端不可用」＋盡力清乾淨＋log 字樣＋禁止重跑 classifier | **78**（前兩種）、**79**（送出失敗）、**80**（逾時）、**89**（探測） |
| §2.2 S3 鍵名 | `documents/{job_id}/input.*`／`result.json` | **77**（`build_context`）、**79**（鍵名與 submit）、**83**（`AwsMailbox` 鍵名函式） |
| §2.3 SQS 佇列 | 兩條 Standard、body 內容、長輪詢 20 秒、整筆另有逾時 | **79**（jobs body）、**80**（results 接收規則）、**83**（實作）、**85**（真的建） |
| §3 範圍「做」 | 7 條 | 74〜95 全部（本表其他列） |
| §3 範圍「不做」 | 6 條（Gate 覆蓋頁首開關、EC2 跑 Postgres/Redis/Celery/GPU、S3 當備份、NAT/ALB/EIP/RDS/Lambda/ECS/Macie、常開 EC2、未核准前改 `.feature`） | **95** 逐條掃碼；各 phase 的「明確不做」表 |
| §4 資料流與冪等 | 影像不進 Redis／SQS／Celery 參數；`job_id` 冪等；兩路不可都 INSERT；`photo` 表不加欄 | **77**（`route`／`privacy` 放 JobStore 不放 `photo`）、**80**（冪等）、**87**（工人冪等）、**95**（掃碼） |
| §5 API 與端點 | **不新增端點**；上傳仍 202；進度仍 `GET /ingest-jobs`；零 DELETE | 全部 phase 都不動端點；**95** 清點 22 支 |
| §6 安全與隱私 | 7 列（敏感不出 S3、不確定當敏感、頁首開關另一扇門、EC2 不收連線、bucket 非公開、IAM 最小權限、機密不進文件） | **74／75**（前兩列）、**78**（零 submit 測試）、**82／91／93**（IAM）、**84**（BPA）、**91**（SG）、全體（文件只寫變數名） |
| §7 AWS 帳號與費用 | Free plan、點數、服務清單、t4g、網路、管理、警報、禁止 Organizations | **82**（開戶＋Budget）、**91**（網路）、**92**（文件寫進 `LAUNCH.md`／`CLAUDE.md`） |
| §8 錯誤表 10 列 | — | 見 **§3.3** |
| §9 測試策略 | 第五道安全網（假 AWS）＋必釘 9 條 | 見 **§3.7** |
| §10 規格檔 | `docs/spec/` 唯讀，本增量**不必**改 Gherkin | **全增量零改動**（§7 鐵律 10） |
| §11 會動到的檔 | 9 列契約 ＋「不改」一段 | 見 **§3.8** |
| §12 驗收清單 | Demo 1／2／2b／3 ＋ 費用／安全 3 條 | 本總覽 **§5**；★G1 取 §5.1、★G2 取 §5.5、★G3 取 §5.2／§5.3；**95** 彙整成驗收包 |
| §13 風險與已知限制 | 7 條 | 本總覽 **§8**；各 phase 的「常見陷阱」節 |
| §14 決策紀錄 | 9 題對話摘要 | 本總覽 §1／§3.2（每條都指回 D 編號） |
| §15 參考來源 | 12 條連結 | 本總覽「附：官方文件連結」 |

### 3.2 D1〜D17 → 落地的 phase（17 條，一條都不能漏）

| # | 決策一句話 | 由誰落地 | 怎麼驗 |
|---|---|---|---|
| **D1** | 本機仍是正本：照片列／原圖／縮圖／向量／待決定／詢問全在這台 Mac；S3 **不是**檔案櫃 | **79**（用結果落庫仍走既有 repository＋storage）、**95**（掃碼） | `psql` 看照片仍在；S3 處理完是空的（`aws s3api list-objects-v2` 無輸出） |
| **D2** | Privacy Gate 在 **PutObject 之前**由本機 worker 觸發；開關雲端時短問可去 ollama.com；**禁止**分類前進 S3 | **74**（VlmGate）、**75**（真模型）、**78**（接在 Celery 開頭） | `test_敏感照片走本機_零submit_job記下privacy與route`：`mailbox.put_calls == 0` |
| **D3** | 三分類；**敏感→本機、不確定→本機、只有非敏感才允許雲端** | **74**（`Verdict`）、**78**（分流） | 74 的 11 顆＋78 的第 1／2 顆 |
| **D4** | Classifier ＝ 現有看圖 VLM 的短問題；不看檔名；失敗→UNCERTAIN；完整看圖仍是入庫那一次 | **74**（VlmGate＋假模型）、**75**（OllamaPrivacyModel 跟開關） | `test_檔名完全不影響判斷`；`test_短prompt不含完整understand欄位` |
| **D5** | 插在 Celery 開頭：`POST /photos` 仍 202、仍先 staging；分類在拿 job 之後、看圖之前 | **78**（`celery_app.ingest_task` 改呼叫 `run_gated_ingest_job`） | `test_ingest_task把gate與cloud都傳進去`；`test_一進門status就變analyzing` |
| **D6** | 頁首 AI 開關閘門**跟著走**、不准去關它 | **75**（`OllamaPrivacyModel` 讀 `AI_BACKEND`）、**95**（掃碼不准寫入） | `test_get_privacy_gate跟AI_BACKEND走`；**95** `test_隱私閘門不會去關AI後端開關`（掃碼無 `AI_BACKEND =`） |
| **D7** | 雲端管線**只給非敏感且遠端可用**：Put → jobs → EC2 → result.json → results → 本機 Get | **78**（守門）、**79**（單圖全程）、**81**（PDF） | 79 的第 5 顆端到端；78 的第 1／2／3 顆零 submit |
| **D8** | S3 是寄物櫃：private、BPA、SSE-S3（不加 KMS）、處理成功後刪、Lifecycle 1〜3 天當掃把 | **79**（`cleanup`）、**84**（bucket 設定 ＋ Lifecycle **2 天**） | `aws s3api get-public-access-block`／`get-bucket-encryption`／`get-bucket-lifecycle-configuration` |
| **D9** | 完成訊號＝results 佇列（方案 B）；工人 **PutObject 成功後才 Send**；本機禁止輪詢 HeadObject | **79**（本機 Receive→GetObject）、**87**（工人的順序鐵律） | `test_result先PutObject才SendMessage`（記錄呼叫順序）；掃碼無 `head_object` |
| **D10** | 遠端關掉＝fallback 本機；不上傳失敗、不要求重傳；進度面板語意不變 | **78**（不可用／探測例外）、**79**（送出失敗）、**80**（逾時、重送無結果）、**89**（`Ec2Probe`） | 四種 `reason=` 各有一顆 `caplog` 測試；**95** `test_遠端不可用時上傳仍然回202不會變5xx` |
| **D11** | EC2 只當工人：無公開 HTTP／網站／API；SG inbound 全關；出站只 TCP 443 | **87**（工人不碰 DB／Celery／Redis）、**91**（SG）、**92**（真機） | `test_工人不import資料庫與Celery與Redis`；`aws ec2 describe-security-groups` 的 `IpPermissions` 為 `[]` |
| **D12** | EC2 看圖一律 Ollama Cloud；與頁首開關無關 | **87**（工人固定用 `OllamaCloudVLM`）、**92**（`worker.env` 放 `OLLAMA_API_KEY`） | 工人原始碼掃碼無 `OllamaVLM`；`ai_timing` log `kind=vlm backend=cloud` |
| **D13** | 本機入庫：拉回 `result.json` 後，**embedding（bge-m3）與 INSERT／原圖／縮圖仍在本機** | **79**（`embed_understanding` 在本機）、**87**（`result.json` 不含 embedding） | `test_雲端路的計時log裡embed是本機`；`result.json` 掃碼無 `embedding` 鍵 |
| **D14** | 作品集為主、順便卸壓：成功標準是三條 demo ＋ EC2 開著時非敏感不佔本機 GPU／Celery 名額 | **92**（Demo 2／2b）、**94**（Demo 3）、**95**（驗收包） | §5 的四個 Demo 逐條 |
| **D15** | Free plan、點數制、目標卡片 $0、用完 **Stop**、映像 `linux/arm64`、機型 t4g.small | **82**（開戶＋Budget）、**90**（arm64）、**92**（Stop） | `aws budgets describe-budgets`；`docker image inspect` 看 `Architecture: arm64`；實例狀態 `stopped` |
| **D16** | CI／CD 分開；CI 契約不動；CD＝OIDC→build arm64→ECR `<git-sha>`→SSM；**EC2 Stop 時 CD 仍可 push** | **93**（OIDC role）、**94**（workflow） | `.github/workflows/test.yml` **零改動**（`git diff` 空）；Demo 3 |
| **D17** | SQS at-least-once：工人與本機收結果都必須冪等；同一 `job_id` 不得 INSERT 兩張 | **80**（本機端）、**87**（工人端） | `test_同一個job_id的結果送兩次_照片仍然只有一列`；`test_result已存在時不看圖只補送results並刪jobs訊息` |

### 3.3 §8 錯誤表 10 列 → 誰實作、誰把關

| # | 情況 | 誰處理 | 預期 | 由誰實作 | 測試把關 |
|---|---|---|---|---|---|
| 1 | 敏感／不確定 | Gate | 本機入庫；零 S3／jobs／results | **78** | `test_敏感照片走本機_零submit_job記下privacy與route`、`test_不確定照片走本機_零submit` |
| 2 | 非敏感、EC2 Stop | D10 | 本機 `run_ingest_job`；202 與進度面板不變 | **78**、**89** | `test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable`、`test_實例狀態stopped與stopping與pending都是False` |
| 3 | 非敏感、無 AWS 憑證 | D10 | 同上 | **78** | `test_非敏感但探測丟例外_同樣fallback本機` |
| 4 | PutObject／jobs SendMessage 失敗 | D10 | fallback 本機；不留半套（盡力刪） | **79** | `test_submit丟例外時fallback本機而且cleanup被呼叫` |
| 5 | 已送雲端、逾時無 results 訊息 | D10 | fallback 本機；冪等避免雙 INSERT | **80** | `test_逾時沒有結果_fallback本機且log有reason_result_timeout`、`test_逾時fallback之前會先清掉S3物件` |
| 6 | SQS 重送（jobs 或 results）、本機已入庫 | D17 | 工人／本機略過 | **80**、**87** | `test_同一個job_id的結果送兩次_照片仍然只有一列`、`test_result已存在時不看圖只補送results並刪jobs訊息`、`test_input不在時只刪jobs訊息什麼都不寫` |
| 7 | VLM 三次失敗（本機或雲端看圖） | 沿用 design5 D10 | 不留 photo 列、清 staging；雲端路還要清 S3 | **79**、**87** | `test_雲端結果說看不懂_job標failed且不留照片`、`test_看圖三次都失敗_result標understood_false而且attempts是3`；★ **95** `test_雲端看圖三次失敗是整筆失敗不是fallback本機` |
| 8 | 格式 415 | HTTP | 不變；不建 job | （不動 `app/api/`） | 既有 `test_photos_upload.py` 的 415 三顆＋`test_design5_error_paths.py`；**95** 只點名 |
| 9 | GitHub OIDC 未鎖 `sub` | CD | 不准合併；trust 必須釘 repo ＋ branch | **93** | `test_OIDC信任文件的sub逐字鎖住main分支`、`test_OIDC信任文件沒有星號萬用字元` |
| 10 | 誤開 NAT／EIP／GPU | 操作 | 本文件禁止；驗收掃 compose／文件／Console | **95** | `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣`；§5.5 的 `describe-nat-gateways`／`describe-addresses` 預期空 |

### 3.4 §1.1「本增量明確推翻的舊決策」→ 哪個 phase 執行推翻（4 列）

| # | 舊決策 | 本增量改成 | 由誰執行推翻 |
|---|---|---|---|
| 1 | `design5.md` §3「不做：雲端物件儲存、S3」 | 僅 `NON_SENSITIVE` 且遠端可用時，S3 當 mailbox；正本仍本機 | **83**（改那顆 `boto3` 掃碼測試）、**84**（真的建 bucket） |
| 2 | `design.md v4`「明確不做雲端部署」 | 允許一台可 Stop 的 EC2 worker ＋ ECR／SSM；**不**把 FastAPI／Postgres／Redis／Celery／Ollama 搬上雲 | **91／92**（EC2）、**93／94**（ECR／SSM）；「不搬上雲」由 **95** 掃碼 |
| 3 | `design3.md`「不要第二個分類模型」（部分） | 只允許 **Privacy Classifier** 這一個用途：規則為主、本機模型為備援；看圖 VLM 仍是原來那一次 | **75**（`OllamaPrivacyModel`；`ai_timing` 新 kind `privacy` 讓它在 log 上與 `vlm` 分得開） |
| 4 | `design3.md`「不做雲端模型」（已於 2026-08-22 為頁首開關作廢） | 本文件不恢復該禁令；EC2 看圖固定 Ollama Cloud | **87**（工人固定 `OllamaCloudVLM`） |

**未推翻（design6 §1.1 末段明列，一條都不准順手改掉）：**
202 受理契約、staging 禁止進 Redis、Celery `concurrency=2`、**embeddings 一律本機**、
頁首 AI 開關、定案不可逆、單一使用者、不做刪除、openapi 零 DELETE、
Ollama 不進本機 Docker、`postgresql@14` 不動、待決定／詢問流程。

### 3.5 §1.2「被否決（不要重開）」11 列 —— 這是擋牆

> 這 11 條是產品負責人**已經考慮過並否決**的方案。實作到一半「靈機一動」想改成其中
> 任何一條的時候，**先回來看這張表**。要重開任何一條需要**產品負責人重新裁決**。

| # | 被否決的方案 | 為什麼否決 | 誰最容易手滑 |
|---|---|---|---|
| 1 | 整套 personalDocAI 搬上 EC2 | 太重；本機才是檔案櫃 | 91、92（「反正機器都開了…」） |
| 2 | EC2 開上傳 API、本機直接 POST 檔 | 工人要開門；與 D11 衝突 | 91（SG 想「先開個 22 方便除錯」） |
| 3 | 把 PDF／JPEG 塞進 SQS | 超過單則上限（現為 1 MiB；design6 寫 256 KB 是舊值，結論不變，§10.2 Q） | 79、83（「一張小圖應該塞得下吧」） |
| 4 | 本機輪詢 HeadObject 當完成訊號（方案 A） | 產品負責人選 B：results queue 叫醒再 GetObject | 80（「輪詢比較好寫」） |
| 5 | 結果永遠只活在 S3、不入本機庫 | 待決定／詢問讀不到 | 79（「S3 上已經有 result 了」） |
| 6 | EC2 回呼家裡 Mac 的 HTTP | 無穩定公網 IP；要開 inbound | 87、92 |
| 7 | Privacy Gate 管頁首雲端開關 | 產品負責人：開關是為了本機太慢；D6 | 74、78（「敏感的乾脆連 ollama.com 也別去」） |
| 8 | RDS／ECS／Fargate／Lambda／ALB／NAT Gateway／K8s | 無需求；NAT 會打爆 Free plan 點數 | 91（子網路設定時最容易誤按 NAT） |
| 9 | 常開 EC2 換「永遠卸壓」 | 產品負責人要 $0 與用完 Stop；卸壓只在開機時成立 | 92（做完 Demo 忘了 Stop） |
| 10 | SSE-KMS customer-managed key | 月費；mailbox 用 SSE-S3 | 84（Console 上 KMS 看起來比較「安全」） |
| 11 | 第一天同時開 classifier ＋ S3 ＋ SQS ＋ IAM ＋ EC2 ＋ CD | 壞了不知道哪一層 | 全體（想跳過閘門一次做完） |

### 3.6 design6 §0 的六條禁止（**單獨列出，因為最容易被順手違反**）

> ## ⛔ 六條禁止（design6 §0 原文，不可協商）
>
> 1. **禁止：** 甲還沒綠就開 S3／SQS／EC2。
>    → 沒有「EC2 關掉＝本機原樣」的契約，後面每一層都在賭遠端永遠開著。
>    ★G1 就是這條的執法點：**Phase 82 之前一行 AWS 指令都不准打。**
> 2. **禁止：** 把影像位元組塞進 SQS。
>    → SQS 單則上限 1 MiB（2025 年中前 256 KB）；一份多頁 PDF 幾十 MB。位元組走 S3，佇列只放 `job_id` 與 `s3_key`。
> 3. **禁止：** EC2 開 inbound HTTP／SSH（22）。管理只走 SSM。
>    → security group 的 `IpPermissions` 必須是 `[]`。「先開 22 方便除錯」＝違規。
> 4. **禁止：** NAT Gateway、ALB、RDS、ElastiCache、ECS、Fargate、Lambda、K8s。
>    → 全部沒有需求，而且 NAT 會直接打爆 Free plan 點數。Phase 95 掃碼。
> 5. **禁止：** 用 Privacy Gate 關掉頁首「AI 模型：本機｜雲端」。
>    → 那扇門的用途是**速度**（D6）。兩件事完全分開，不要合併。
> 6. **禁止：** 遠端不可用時上傳改 5xx 或讓使用者重傳。
>    → 必須 fallback。使用者看到的東西與增量五**逐字相同**。

### 3.7 §9 測試策略「必釘」9 條 → 誰釘的

| # | design6 §9 原文 | 由誰釘 | 測試名 |
|---|---|---|---|
| 1 | 敏感 → 假 S3 的 PutObject 呼叫次數為 0，照片仍入收件箱 | **78** | `test_敏感照片走本機_零submit_job記下privacy與route` |
| 2 | 不確定 → 同上 | **78** | `test_不確定照片走本機_零submit` |
| 3 | 非敏感＋假遠端 running → 有 PutObject＋jobs SendMessage；假工人 Send results 後本機 GetObject 入庫、staging 空 | **79** | `test_非敏感且遠端開著_雲端結果回來後本機入庫`、`test_雲端入庫後S3三物件與results訊息都被清掉` |
| 4 | 非敏感＋假遠端 stopped → PutObject 次數 0，走 `run_ingest_job`，列數 1 | **78**、**89** | `test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable`、`test_實例狀態stopped與stopping與pending都是False` |
| 5 | 非敏感＋DescribeInstances 丟錯 → 同 fallback | **78**、**89** | `test_非敏感但探測丟例外_同樣fallback本機`、`test_探測丟例外時回False並留log` |
| 6 | 已 INSERT 再送一次同 `job_id` result → 列數仍 1 | **80** | `test_同一個job_id的結果送兩次_照片仍然只有一列` |
| 7 | SQS 兩條佇列的訊息 body 都不含 PNG／PDF 位元組 | **79**、**83**、**95** | `test_jobs訊息恰兩鍵而且不含位元組`、`test_send_job的body恰兩鍵`、`test_send_result的body恰一鍵`、`test_get_object拿得回位元組而delete_objects送出鍵清單`（成功路徑；沒有它「get_object 永遠回 None」的實作會 15 顆全綠）、`test_兩條佇列的訊息body都不含影像位元組` |
| 8 | classifier VLM 短問：敏感／不敏感有把握／沒把握／丟例外；同一張圖換檔名答案不變 | **74** | `test_模型說敏感回SENSITIVE`、`test_模型說不敏感而且有把握回NON_SENSITIVE`、`test_模型說不敏感但沒把握回UNCERTAIN`、`test_檔名完全不影響判斷` |
| 9 | 清點：無 DELETE；無 NAT 字樣進本增量產品碼 | **95** | `test_端點仍是22支而且openapi零DELETE`、`test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣` |

> design6 §9 開頭還說「沿用四道 autouse，再加**假 AWS 客戶端**，pytest **不連真 AWS**」——
> 那是 **Phase 77 的第五道安全網 `wire_fake_cloud`**（§7 鐵律 2）。
> 「前端不新增 Playwright」與「真 AWS 煙霧靠人手」也照辦：本增量**前端零改動**。

### 3.8 §11「會動到的檔」→ 我們的實際檔名（差異都註明理由）

| design6 §11 寫的 | 階段 | 我們實際用的 | 差異理由 |
|---|---|---|---|
| `app/services/privacy_gate.py`（名稱可調） | 甲 | **同名**（Phase 74／75） | 無差異 |
| `app/services/ingest_job.py`／Celery 進入點 | 甲 | `ingest_job.py` 只做**純重構**（76）；閘門另開 `app/services/gated_ingest.py`（78）；`celery_app.py` 改呼叫它 | `run_ingest_job` 是 fallback 的目的地，必須保持「乾淨的本機路」。把閘門塞進去會讓 fallback 變成遞迴呼叫自己 |
| `app/services/cloud_route.py` 等 | 乙／丙 | **`app/services/cloud_ingest.py`**（本機端的路）＋ **`app/services/aws_mailbox.py`**（唯一碰 boto3 的地方） | 拆兩層：一層是「流程」（可用假信箱測），一層是「AWS SDK」（可用 stub client 測）。合成一個檔會讓所有流程測試都被迫依賴 boto3 |
| `scripts/cloud_worker.py` **或** `app/workers/cloud_worker.py` | 丁 | **`app/workers/cloud_worker.py`** | `.dockerignore` 排除 `scripts/`——放那裡的話工人程式**不會進映像**，戊段一定壞（總覽 §10 追認項 k） |
| Dockerfile／多階段或第二 target | 戊 | **多階段**：`base` → `cloud-worker` → **`app` 放最後** | 不帶 `--target` 的 `docker build .` 仍然蓋出 app，**`compose.yaml` 一個字都不必改**（追認項 j） |
| `.github/workflows/` | 己 | 新增 **`.github/workflows/deploy.yml`**；`test.yml` **零改動** | D16「現有 CI 不動契約」 |
| `LAUNCH.md`、`CLAUDE.md` 指令區 | 戊／己 | **88**（Mac 上跑工人，英文小節）、**92**（EC2 章節＋`CLAUDE.md`＋`README.md` 兩句改誠實） | `LAUNCH.md`／`README.md` 自 2026-08-27 起是**英文**，改它們要用英文 |
| `tests/…` | 甲起 | 見 §2.7 逐 phase 清單 | 無差異 |
| `docs/plan/unfinish/` | 拍板後 | 本檔 ＋ `phase-74`〜`phase-95` | 無差異 |

**design6 §11「不改」那一段：** 詢問 workflow、定案 `PATCH`、`postgresql@14`、
把 Ollama 打進本機 app 映像——**全部維持**，由 **95** 掃碼。

---

## 4. 三個閘門（誰確認、憑什麼、卡住怎麼辦）

> 🚦 **閘門是「人」的動作，實作者不可以自己勾掉。**
>
> 這三個框框裡沒有任何一件事是靠跑指令就能通過的。指令只是**證據**，
> 「看過證據、同意往下走」的那個動作必須由**產品負責人**做出來——
> 一句明確的話（口頭、對話、或 dev-prompt 檔案）。
>
> 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
> 「先做下一段，之後再回來補確認」。
>
> **計畫層的落實聲明：** design6 §0 的表格只說「甲綠」「乙綠」「丁綠」「戊能手動部署」，
> 並在禁止清單第 1 條寫「甲還沒綠就開 S3／SQS／EC2」。
> ★G1／★G2／★G3 這三個名字與具體的停手範圍，是**本計畫**把那幾句話落成實作者
> 看得懂的動作，**不是 design6 自己寫的字**。

### ★ G1 —— 開始花 AWS 資源的入場券（design6 §0 甲那列、§0 禁止第 1 條）

| 項目 | 內容 |
|---|---|
| 是什麼 | 「閘門與 fallback 做完了、產品負責人親眼看過，可以開 AWS 帳號了」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design6 §0 甲那列三條：① 敏感／不確定**零 S3 呼叫** ② 假遠端關閉時非敏感也走 `run_ingest_job` ③ pytest 不連 AWS。逐條指令見本總覽 **§5.1** |
| 沒過會怎樣 | **Phase 82 起全部停擺，一行 AWS 指令都不准打**（design6 §0 禁止第 1 條）。不能「先開個帳號放著」——開戶就開始算 Free plan 的 6 個月 |
| 卡住時怎麼辦 | 若是測試沒過 → 回 74〜81 對應的 phase 修。若是產品負責人對「短問題把什麼當敏感」有意見 → 回 **Phase 75** 改 `PRIVACY_PROMPT`（那是給 VLM 的短指令，不是檔名表）。**不要**用「先開 S3 試試看」繞過——甲全部是本機的事，修起來很快 |

### ★ G2 —— 開始花點數建 EC2 的入場券（design6 §0 丁／戊那列）

| 項目 | 內容 |
|---|---|
| 是什麼 | 「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design6 §0 丁那列：本機模擬工人 jobs→S3→看圖→`result.json`→SendMessage results；本機 Receive 後 GetObject 入庫。**外加**：arm64 映像在 Mac 上跑得起來（Phase 90）。逐條指令見 **§5.5** |
| 沒過會怎樣 | Phase 91〜95 全部停擺。理由很實際：EC2 一開就開始扣**點數**，而點數用完會**關帳**（Free plan 不扣卡，資源直接消失）。工人本身有 bug 的話，你會在一台看不到 shell、只能靠 SSM 的機器上除錯——比在 Mac 上難十倍 |
| 卡住時怎麼辦 | ① 先分清楚是「工人邏輯錯」還是「AWS 權限錯」——`python scripts/aws_check.py s3 sqs` 兩個都 OK 就是邏輯問題；② 工人邏輯錯 → 回 **87**（`process_job_message`）；③ 主迴圈或訊號處理錯 → 回 **88**；④ 映像 build 不出來或跑不動 → 回 **90**。**不要**「上 EC2 再說，反正那邊 log 也看得到」 |

### ★ G3 —— 開始做 CD 的入場券（design6 §0 戊／己那列）

| 項目 | 內容 |
|---|---|
| 是什麼 | 「真機已經處理過一筆、Stop 之後也自動 fallback 了，可以做自動部署了」的一句話 |
| 誰確認 | **產品負責人（人）**，而且必須親眼看過 **Demo 2 與 Demo 2b** |
| 憑什麼確認 | design6 §0 戊那列：真機 Start → 處理一筆 → Stop；Stop 後下一筆自動本機。逐條指令見 **§5.2**（Demo 2）與 **§5.3**（Demo 2b） |
| 沒過會怎樣 | Phase 93〜94 停擺。理由：CD 的失敗與工人的失敗**長得一模一樣**（都是「EC2 上沒反應」）。手動部署還沒跑通就加自動部署，除錯時分不清是「新映像沒推上去」還是「工人本來就壞」 |
| 卡住時怎麼辦 | ① 真機起不來 → 看 `deploy/ec2/user-data.sh`（回 **91**）；② 工人起得來但拿不到訊息 → IAM instance role 的 policy（回 **91**）；③ 拿得到訊息但看圖失敗 → `worker.env` 的 `OLLAMA_API_KEY`（回 **92** 的 Session Manager 步驟）；④ 一切正常但本機沒收到 → 本機 `.env` 的 `CLOUD_ROUTE=ec2` 與 `EC2_WORKER_INSTANCE_ID`（回 **92**）。⚠ **每一輪除錯完都要記得 Stop** |

---

## 5. 總驗收清單（design6 §12 逐條抄錄 ＋ 每條要跑的指令）

> 這一節是 design6 §12 的**逐條原文**（Demo 1／2／2b／3 各 1 條 ＋ 費用／安全 3 條），
> 下面補上「怎麼驗」。★G1 取 §5.1、★G2 取 §5.5、★G3 取 §5.2 與 §5.3；
> Phase 95 的驗收包五段全取。
>
> 📌 **下面所有 `aws` 指令都用變數，不寫真值。** 先把 `.env` 的值放進 shell：
>
> ```bash
> set -a; . ./.env; set +a          # 讓 .env 的變數進環境（set -a ＝自動 export）
> unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ .env 裡是 personaldocai-mac 的 key，不 unset 會蓋掉 aws configure 的 admin profile（§10.2 I）
> ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
> echo "$AWS_REGION / $S3_BUCKET"   # 確認讀到了；⚠ 不要把這行的輸出貼進任何文件
> ```

### 5.1 階段甲的驗收（★G1 的內容；design6 §0 甲那列）

- [ ] **敏感／不確定零 S3 呼叫；照片仍入收件箱**

  ```bash
  pytest tests/integration/test_gated_ingest.py -v
  # 預期：test_敏感照片走本機_零submit_job記下privacy與route 綠
  #       test_不確定照片走本機_零submit 綠
  #       兩顆的斷言都含「假信箱的 put_calls == 0」與「收件箱多一張」
  ```

- [ ] **假遠端關閉時，非敏感也走 `run_ingest_job`**

  ```bash
  pytest tests/integration/test_gated_ingest.py -k 遠端關閉 -v
  # 預期綠，而且 caplog 斷言含 fallback=local reason=remote_unavailable
  ```

- [ ] **pytest 不連 AWS（三個死埠一起指，顆數不變）**

  ```bash
  pytest -q                          # 預期：616 passed（Phase 81 之後；2026-09-02 實查基線 613 → 624）
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  # 預期：顆數一模一樣 ＝ 零外部依賴實證
  # ⚠ 絕對不要同時跑兩份 pytest（會互相 TRUNCATE 測試庫，症狀是隨機 404）
  ```

### 5.2 Demo 2 —— 非敏感走雲端再回家（design6 §12 原文）

> 原文：**EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉（或 Lifecycle 內會刪）；
> 照片進待決定；詢問能問到。**

- [ ] **Start → 上傳非敏感 → 照片進待決定 → 問得到**

  ```bash
  # 1. 開機（做完一定要 Stop，見 5.5）
  aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].State.Name' --output text
  # 預期：running

  # 2. 本機 .env 要是 CLOUD_ROUTE=ec2，改完重啟 worker（app 不必動）
  docker compose -f compose.yaml -f compose.dev.yaml restart worker

  # 3. 上傳一張**內容**明確非敏感的圖（合成收據；2026-09-01 改判後閘門看圖，檔名只是記帳）
  curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/receipt-test.png" \
    https://127.0.0.1:8000/photos
  # 預期：202，body 恰三鍵 {job_id, filename, content_type}
  # （2026-09-02 校準：閘門已不看檔名——圖的內容要是收據／菜單這類非敏感；Phase 86／88／92 都用同一張合成收據）

  # 4. 送出當下 S3 應該看得到 input 與 context（動作很快，要馬上看）
  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION" \
    --query 'Contents[].Key' --output text
  # 預期（處理中）：documents/<job_id>/context.json  documents/<job_id>/input.png
  #                 之後工人寫完會多一個 result.json

  # 5. 本機 worker 的 log 要看得到走雲端
  docker compose logs --tail=200 worker | grep -E "route=|fallback=|kind=embed|雲端結果已入庫"
  # 預期依序三行（不該有 fallback= 那一行）：
  #   job <job_id> route=cloud verdict=NON_SENSITIVE
  #   AI 結束 kind=embed backend=local …
  #   job <job_id> 雲端結果已入庫：photo_id=<n>      ← 雲端路自己的完成訊號（Phase 79）

  # 6. 做完之後 S3 應該是空的（本機 cleanup 刪掉三個物件）
  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
  # 預期：沒有 Contents（整個回應只有 metadata），或最多剩 Lifecycle 兩天內會清掉的殘骸

  # 7. 照片真的進了待決定，而且問得到
  psql -d PersonalDocAI -c "select id, text from photo order by id desc limit 1"
  open "https://localhost:8000/ui/pending.html"       # 人工：新照片在牆上
  # 人工：到問問題頁問一句跟那張照片有關的話，回答要引用得到
  ```

### 5.3 Demo 2b —— 遠端關掉 fallback（design6 §12 原文，本增量新增）

> 原文：**EC2 Stop 後上傳非敏感；不必改任何設定；進度與入庫與增量五相同；
> S3 不出現新物件。**

- [ ] **Stop → 再傳一張非敏感 → 一切照舊、S3 全程沒有新物件**

  ```bash
  aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"

  # ⚠ 本機**什麼設定都不要改**（CLOUD_ROUTE 仍是 ec2）——這正是這個 Demo 要證明的事
  # ⚠ 探測結果有 60 秒快取（EC2_PROBE_TTL_SECONDS）：Stop 之後 60 秒內探測可能還說 running，
  #   要嘛等 60 秒再傳、要嘛 restart worker（lru_cache 的探測物件跟著重建）
  curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/menu-test.png" \
    https://127.0.0.1:8000/photos          # 預期：202（不是 5xx）
  curl -k -s https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
  # 預期：那筆 job 的 status 是 queued 或 analyzing，形狀與增量五完全一樣

  docker compose logs --tail=200 worker | grep "fallback="
  # 預期：fallback=local reason=remote_unavailable

  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
  # 預期：沒有任何新物件（探測不通過就不會送出）

  # 等 worker 做完（本機 gemma4 要 64〜88 秒；想快一點就先把頁首開關切到雲端）
  psql -d PersonalDocAI -c "select count(*) from photo"     # +1
  ```

### 5.4 Demo 3 —— CD（design6 §12 原文）

> 原文：**改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA →
> Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）。**

- [ ] **改一行 → push → ECR 有 `<sha>` → Start 後 log 印出新的 `version=`**

  ```bash
  # 1. 在 app/workers/cloud_worker.py 檔尾加一行註解（⚠ 不要改啟動 log 那一行字：
  #    Phase 88 的測試用 startswith("cloud_worker 啟動 ") 釘死它、README／LAUNCH 也逐字引用它），
  #    commit、push 到 main
  git add app/workers/cloud_worker.py && git commit -m "chore: Demo 3——cloud_worker 加一行註解觸發 CD"
  git push origin main
  SHA=$(git rev-parse HEAD)          # ⚠ 完整 40 碼：CD 的 tag 與 GIT_SHA 用的是 workflow_run.head_sha（完整），不是 --short

  # 2. 到 GitHub 看兩個 workflow：test 綠了之後 deploy 才會跑
  #    https://github.com/1104030360/personalDocAI/actions
  #    ⚠ deploy 要 5〜15 分鐘：GitHub runner 是 amd64，用 QEMU 模擬 arm64 很慢

  # 3. ECR 上要看得到這個 sha
  aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
    --query 'imageDetails[?imageTags].imageTags[]' --output json
  # 預期：攤平後的清單裡有 "<SHA>"（完整 40 碼）與 "latest"
  aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" \
    --image-ids imageTag=latest --query 'imageDetails[0].imageTags' --output json
  # 預期：latest 這一張映像的 tags 同時含 "<SHA>"（＝latest 就是這次 push 的那張）
  echo "$SHA"                       # 拿來跟上面的輸出比對

  # 4. Start 之後確認跑的是新映像（SSM，不必 SSH）
  aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
    --instance-ids "$EC2_WORKER_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --parameters 'commands=["docker logs cloud-worker 2>&1 | head -n 5"]' \
    --query 'Command.CommandId' --output text)
  aws ssm get-command-invocation --region "$AWS_REGION" \
    --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
    --query 'StandardOutputContent' --output text
  # 預期：cloud_worker 啟動 version=<SHA> region=... bucket=...

  # 5. 做完 Stop（每一次都要）
  aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
  ```

  > EC2 是 Stop 的時候，deploy 這個 job **仍然算成功**（D16），
  > log 會印 `instance stopped; image pushed; next Start pulls latest`。

### 5.5 Demo 1、費用與安全（design6 §12 剩下的四條）

- [ ] **Demo 1 — 敏感留本機：上傳判定敏感的檔；S3 bucket 無該 `job_id`；待決定有照片**

  ```bash
  curl -k -s -w '\n%{http_code}\n' -F "file=@/path/to/身分證正面.jpg" \
    https://127.0.0.1:8000/photos          # 202
  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
  # 預期：沒有任何以那個 job_id 開頭的物件（最好整個 documents/ 都是空的）
  docker compose logs --tail=100 worker | grep "route=local"
  # 預期：route=local verdict=SENSITIVE
  # 等 worker 做完 → 待決定牆上有那張照片（open https://localhost:8000/ui/pending.html）
  ```

- [ ] **Free plan、未升 Paid；Budget 有寄信設定**

  ```bash
  # ⚠ 用 personaldocai-admin 的 profile（mac key 沒有 budgets:ViewBudget），所以前面已 unset 那兩個變數
  aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
    --query 'Budgets[].[BudgetName,BudgetLimit.Amount,BudgetLimit.Unit,TimeUnit]' --output text
  # 預期（扁平一行；Amount 在 AWS 是字串，text 輸出就是 5 或 5.0）：
  #   personaldocai-budget    5    USD    MONTHLY
  aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" \
    --budget-name personaldocai-budget --query 'Notifications[].{Type:NotificationType,Th:Threshold}'
  # 預期：ACTUAL 與 FORECASTED 各一筆、Threshold 80
  # 人工：AWS Console → Billing and Cost Management → 確認方案仍是 Free plan（未升 Paid）
  ```

- [ ] **Security group inbound 空；無 NAT、無 EIP**

  ```bash
  aws ec2 describe-security-groups --region "$AWS_REGION" \
    --filters Name=group-name,Values=personaldocai-worker-sg \
    --query 'SecurityGroups[0].IpPermissions' --output json
  # 預期：[]   ← 一條 inbound 規則都沒有

  aws ec2 describe-security-groups --region "$AWS_REGION" \
    --filters Name=group-name,Values=personaldocai-worker-sg \
    --query 'SecurityGroups[0].IpPermissionsEgress[].{P:IpProtocol,From:FromPort,To:ToPort}'
  # 預期：只有一條 tcp 443 -> 443

  aws ec2 describe-nat-gateways --region "$AWS_REGION" \
    --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text
  # 預期：空（沒有任何輸出）

  aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text
  # 預期：空（沒有配置任何 Elastic IP）

  aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
    --query 'Reservations[0].Instances[0].{Type:InstanceType,Arch:Architecture,State:State.Name}'
  # 預期：t4g.small / arm64 / stopped（demo 做完要是 stopped）
  ```

- [ ] **pytest 全綠且不碰真 AWS**

  ```bash
  pytest -q                                  # 預期：682 passed ＋ 0 skipped（全部做完之後）
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q      # 顆數一模一樣
  git status --short docs/spec/              # 預期：零輸出（規格區全程一字未動）
  ls data/staging/                           # 預期：空的（或只剩正在跑的）
  ```

- [ ] **★G2 的加碼：arm64 映像在 Mac 上跑得起來（Phase 90）**

  ```bash
  docker build --target cloud-worker --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
    -t personaldocai-worker:local .
  docker image inspect personaldocai-worker:local --format '{{.Architecture}}'   # 預期：arm64
  docker run --rm --env-file .env personaldocai-worker:local               # 預期：印啟動 log 後開始等訊息
  docker compose config > /tmp/compose-after.yaml                          # 與開工前的輸出 diff 要是空的
  ```

---

## 6. 進度勾選區

```text
── 階段甲：隱私閘門與 fallback（全程零 AWS）────────────────────────
[x] Phase 74  privacy_gate.py：Verdict、VlmGate（短問、不看檔名）、假件（不接線）
[x] Phase 75  OllamaPrivacyModel 跟頁首開關；縮圖 512；ai_timing kind=privacy
[x] Phase 76  ingest_job.py 純重構：五個公開積木（既有顆數逐顆綠）
[x] Phase 77  cloud_ingest.py 契約＋CloudRouteOff＋conftest 第五道 wire_fake_cloud
[x] Phase 78  gated_ingest.py：閘門接線、route=local、遠端不可用→fallback
[x] Phase 79  CloudRoute 本體＋雲端成功路（單圖）
[x] Phase 80  wait_result 完整版：逾時、別人的訊息、崩潰重送、D17 冪等
[ ] Phase 81  PDF 走雲端路：逐頁配對、跳頁、pages_done 續跑
[ ] ★★★ G1   產品負責人照 §5.1 三條看過並明示「可以開始花 AWS 資源」

── 階段乙：AWS 帳號與 S3 寄物櫃 ────────────────────────────────────
[ ] Phase 82  Free plan 開戶、**先建 Budget**、東京區、AWS CLI、IAM user（零程式碼）
[ ] Phase 83  requirements 加 boto3；改 design5 那顆掃碼測試；aws_mailbox.py
[ ] Phase 84  建 bucket：BPA 全開、SSE-S3、Lifecycle 2 天；aws_check.py s3

── 階段丙：兩條 SQS 佇列 ───────────────────────────────────────────
[ ] Phase 85  建 personaldocai-jobs／personaldocai-results；aws_check.py sqs
[ ] Phase 86  get_cloud_route() 補 assume；真 AWS 逾時煙霧（30 秒 fallback）

── 階段丁：Mac 上的工人 ────────────────────────────────────────────
[ ] Phase 87  cloud_worker.process_job_message()＋result.json＋假信箱端到端
[ ] Phase 88  main() 主迴圈、SIGTERM、啟動 log；Mac 上真跑一次端到端

── 階段戊前半：探測與 arm64 映像 ───────────────────────────────────
[ ] Phase 89  Ec2Probe：DescribeInstances＋60 秒 TTL；get_cloud_route() 補 ec2
[ ] Phase 90  Dockerfile 多階段（base → cloud-worker → app 最後）；容器跑端到端
[ ] ★★★ G2   產品負責人照 §5.5 最後一條看過並明示「可以開始建 EC2」

── 階段戊後半：真的 EC2 ────────────────────────────────────────────
[ ] Phase 91  SG（inbound 空）、S3 endpoint、IAM role＋instance profile、ECR、手動 push
[ ] Phase 92  啟動 t4g.small、SSM 放 worker.env、Demo 2／2b、**Stop**、文件三份
[ ] ★★★ G3   產品負責人照 §5.2／§5.3 看過並明示「可以做 CD」

── 階段己：CI 之後的 CD ────────────────────────────────────────────
[ ] Phase 93  IAM OIDC provider＋deploy role（sub 精確鎖 main）
[ ] Phase 94  .github/workflows/deploy.yml；Demo 3

── 收尾 ────────────────────────────────────────────────────────────
[ ] Phase 95  §8 十列逐列點名＋六禁與被否決清單掃碼＋三死埠實證＋驗收包
```

> 📌 **commit 節奏由產品負責人決定**（詳見 §7 鐵律 12）。未指示前不要自己 commit、
> 也不要把 `unfinish/` 搬進 `finish/`（歸檔隨 commit 執行）。
> 各 phase 的 git 驗收一律用「**與開工前快照相減**」的寫法，兩種節奏都成立。

---

## 7. 全域鐵律（每個 phase 的計畫檔都隱含這一節，違反等於做錯）

**1. 全程 TDD。** 先寫**會紅**的測試 → **真的跑它、親眼看到紅** → 寫最小實作 → 跑綠 → 收工。
「跑它確認紅」不可以跳過——沒看過紅的測試，你不知道它有沒有在測東西
（Phase 37 就是靠這流程揪出「自創實體＋釘選非原子」的真缺陷）。人工操作 phase（82／84／85／91／92）
沒有測試，改成「指令 → 預期輸出 → 做錯了怎麼退回」。

**2. pytest 的**五道**安全網，一道都不准繞過。**
pytest **絕不打真 Ollama、絕不連真 Redis、絕不啟動 Celery、絕不寫專案 `data/`、絕不清正式庫、
絕不連真 AWS**。

| fixture | 擋掉什麼 | 誰加的 |
|---|---|---|
| `reset_tables` | 每測清空**測試庫**並重播六筆資料夾種子；絕不清正式庫 | 既有 |
| `wire_fake_ai` | 六個 AI 注入點 ＋ 固定時鐘；**Phase 74 起多接 `get_privacy_gate` → `FakePrivacyGate(Verdict.UNCERTAIN)`**（預設全部走本機，既有 543 顆行為零改變）；**Phase 78 起 conftest 另以 monkeypatch 雙名蓋 `dependencies.get_privacy_gate` 與 `dependencies.build_privacy_gate_for_backend`**（`celery_app` 直接呼叫那條路也攔得到，§10.2 S） | 既有＋**74**＋**78** |
| `isolated_data_dir` | `config.DATA_DIR` 指到 `tmp_path` | 既有 |
| `wire_memory_job_store` | JobStore 換記憶體版、派工換記帳假件（`dependency_overrides` ＋ `monkeypatch` 雙管） | 既有 |
| **`wire_fake_cloud`** | `config.CLOUD_ROUTE` 蓋成 `"off"`、`get_cloud_route` 雙管換 `CloudRouteOff()`、`AWS_ENDPOINT_URL` 指死埠 `http://127.0.0.1:9`（漏接假件時 boto3 也只會撞死埠，不會真的出網） | **Phase 77 新加，名字照這個** |

零依賴實證從 Phase 77（第五道安全網落地）起就可以**三個死埠一起指**（83 起一律如此）：
`AWS_ENDPOINT_URL=http://127.0.0.1:9 CELERY_BROKER_URL=redis://127.0.0.1:9/0 OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q`
（埠 9 是保留的 discard 埠，本機一定沒人聽，會立刻 connection refused 而不是卡住等逾時。）

**3. 絕對不要同時跑兩份 pytest。** `reset_tables` 每測都 `TRUNCATE` 同一個測試庫，
兩份同時跑會互相清掉對方的資料。**症狀是大量看似隨機的 404 與
`TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣**——
看起來像程式壞了，其實只是撞在一起。等另一份跑完再跑。

**4. SQL 只准出現在 `app/repositories/photo_repository.py`。**
本增量三個新模組（`privacy_gate.py`／`cloud_ingest.py`／`aws_mailbox.py`）與整個
`app/workers/` **零 SQL、零 `psycopg`**。`test_design3_error_paths.py` 的
`可以碰資料庫的檔案` 白名單掃碼會抓到新檔——**不要把新檔加進白名單**，要讓它本來就乾淨。

**5. `boto3` 只准出現在 `app/services/aws_mailbox.py`。**
`cloud_ingest.py` 只認 `CloudMailbox` 這個 Protocol，所以它的測試用假信箱就跑得動；
`dependencies.get_cloud_route()` 的 boto3 相關 import **寫在函式裡面**（不是檔案最上面），
理由與既有 `get_task_dispatcher()` 相同：pytest 收集階段不必為了一顆字串測試就載入 boto3。
Phase 83 的 `test_boto3只在aws_mailbox裡出現` 與 Phase 95 的掃碼各釘一次。

**6. 影像位元組永遠不進 SQS，也不進 Celery 參數、不進 Redis。**
`data/staging/` 走磁碟、S3 走 `PutObject`；佇列只放 `job_id` 與 `s3_key`
（design6 §0 禁止第 2 條、§4 第 1 條）。任務函式的參數簽章仍然只吃 `job_id`。

**7. `openapi.json` 零 DELETE，而且**端點恆為 22**。**
design6 §5 明文「不新增使用者打的 REST 端點」。「遠端是否 running」用 log，不開端點。
三顆既有的清點測試（`test_端點恰好是這22支`／`test_端點數仍為22`／`test_端點數不變`）
**本增量一顆都不改**。

**8. EC2 的 inbound 永遠是空的；用完一定 Stop。**
`IpPermissions` 必須是 `[]`（design6 §0 禁止第 3 條）。「先開 22 方便除錯」＝違規，
要 shell 就用 SSM Session Manager。每一次 Demo／除錯結束都要
`aws ec2 stop-instances`——忘了就在燒點數（D15）。

**9. Budget 必須在開戶第一天就建。**
Phase 82 的步驟順序是「開戶 → **建 Budget** → 設定 CLI → 建 IAM user」，
**不可以**把 Budget 挪到後面。Free plan 不扣卡，但點數用完會**關帳**（資源消失），
沒有警報就等於閉著眼睛燒。

**10. 文件裡永遠只寫變數名，不寫值。**
`.env` 不入版控；policy JSON 的帳號 ID 一律 `<ACCOUNT_ID>` 佔位；
bucket 名一律 `$S3_BUCKET`；access key、`OLLAMA_API_KEY`、實例 ID 一個字都不准出現在
`docs/`、`README.md`、`LAUNCH.md`、`CLAUDE.md`、`deploy/` 或任何 commit 裡。
**repo 是 PUBLIC**（`github.com/1104030360/personalDocAI`，2026-08-28 建）——寫進版控的每一個字全世界都看得到，這一條沒有「先放著之後再清」的餘地。

**11. `compose.yaml` 本增量零改動。**
AWS 的設定全部走 `.env`（`app` 與 `worker` 已經 bind-mount 了 `.env`）。
Dockerfile 改成多階段時，**`app` stage 放最後**，所以不帶 `--target` 的 `docker build .`
仍然蓋出 app 映像——`docker compose config` 的輸出與改版前逐字相同（Phase 90 驗）。
**不加第五個服務**（本機不跑 cloud_worker 容器，那是 EC2 的事；丁段用 `docker run` 手動跑）。

**12. commit 節奏由產品負責人決定；分支是 `main`（不是 `master`）。**
未指示前不要自己 commit、不要把計畫檔搬進 `finish/`（`git mv` 會直接 stage）。
git 驗收一律用「與開工前快照相減」（開工先 `git status --short -- app tests deploy > /tmp/pNN-before.txt`）。
OIDC trust 的 `sub` 必須逐字鎖 `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`
——**design6 §6 寫的是 `master`，那是筆誤**（本總覽 §10 追認項 b）。

**13. 正式庫本增量零改動。** 不跑任何遷移腳本、`photo` 表不加欄。
`route`／`privacy` 放 **JobStore**（design6 §4 明文），不是 `photo` 表。
design5 的 `test_photo表沒有處理狀態欄也沒有job_id欄` 仍然有效，Phase 95 再掃一次。

**14. `docker compose down -v` 永遠禁止。** `-v` ＝ 連 named volume 一起刪 ＝ **刪掉正式庫**。
停服務一律 `docker compose stop`。同理危險：`docker system prune --volumes`、
`docker volume prune -a`、`docker volume rm personaldocai_pgdata`、Docker Desktop 的
"Reset to factory defaults"。

**15. `postgresql@14`（5432 埠）全程不准碰。** 那是別的專案的資料庫。
本專案一律 `127.0.0.1:5433`、帳號 `postgres`。

**16. `docs/spec/` 唯讀——本增量**一個字都不動**。**
design6 §10 明文：「本增量對外上傳契約仍是 202＋分析成功才有照片；**不必**為了 fallback 改 Gherkin」。
Phase 74〜95 期間 `git status --short docs/spec/` 必須全程乾淨。
要加「敏感不上雲」的 Example 需要**另外核准**——那不在本增量的範圍。

**17. QR 尺寸那顆測試不准改小。** `app/static/style.css` 的 `.cd-qr svg { max-width: 20rem; }`
背後是真機驗收踩到的**安靜壞掉**（QR 畫得出來但 iPhone 掃不到）。
`test_qr的顯示尺寸夠大讓長網址也掃得到` 把值釘死，本增量不准動它。

**18. 這些東西本增量一律不做。** 不新增刪除照片端點、不做多使用者、不做對話記憶、
**embeddings 一律本機**（向量必須跟庫裡既有的 bge-m3 同源，不歸頁首開關管，也不歸雲端工人管）、
**前端零改動**（不加 Playwright、不改 `progress_panel.js`、不在畫面上顯示 `route`）。

---

## 8. 已知限制（MVP 刻意為之；design6 §13 的白話重寫 ＋ 計畫層新增）

### 8.1 EC2 Stop 的時候不卸壓（design6 §13）

**是什麼：** 機器關著就等於沒有雲端管線，每一張非敏感照片都會 fallback 回本機看圖。
**為什麼可以接受：** 這是 D15 用來換「卡片 $0」的代價，產品負責人明確選了它。
要卸壓就先 Start。

### 8.2 頁首撥雲端時，敏感檔的影像仍然可以去 ollama.com（design6 §13）

**是什麼：** Privacy Gate 管的是 **S3／SQS／EC2 這條管線**，不管頁首那顆開關（D6）。
**為什麼可以接受：** 兩扇門的用途不同——開關是為了「本機太慢」。
⚠ **文件與對外說法都不可以寫成「敏感資料完全不出雲」**（design6 §6 明文）。

### 8.3 EC2 ＋ Ollama Cloud 不會比「本機 ＋ 頁首雲端開關」更快（design6 §13）

**是什麼：** 多了 S3 上傳、SQS 來回、S3 下載三段 hop。
**為什麼可以接受：** 開機的價值是**卸掉本機的 Celery／GPU 名額**與**作品集管線**（D14），
不是延遲。真的只想快就撥頁首開關。

### 8.4 Free plan 滿 6 個月或點數用完會關帳（design6 §13）

**是什麼：** 不是扣卡，是**資源消失**（90 天內可升 Paid 救回）。
**為什麼可以接受：** 本專案在雲端沒有正本——S3 上只有處理中的暫存檔、EC2 上只有一支無狀態工人。
關帳最壞的後果是「雲端管線沒了」，照片一張都不會少。

### 8.5 t4g 試用與 Free plan 文件可能不一致（design6 §13）

**是什麼：** 官方另有 t4g 每月 750 小時試用到 2026-12-31，但 Billing 頁寫 Free plan 無 short-term trial。
**為什麼可以接受：** 開機後看帳單就知道——**沒有 $0 那一列就立刻 Stop**，只吃微量點數。
Phase 92 的步驟裡有這一條檢查。

### 8.6 Classifier 一定會漏（design6 §13）

**是什麼：** VLM 短問也會看錯——把薪資單看成收據、把模糊的證件看成一般文件，沒把握（`confident=false`）的答案也不會少。**短問耗時（2026-09-01 Phase 78 煙霧實測，gemma4:e2b／ollama.com gemma4，合成收據圖）：本機 99.6 秒（首次呼叫含模型載入；同機同圖完整看圖 83.1 秒）／雲端 0.7 秒。** 閘門在 worker 裡確實跟著頁首開關走（log `kind=privacy backend=cloud`＝§10.2 S 的 `build_privacy_gate_for_backend(job["ai_backend"])` 生效）。
**為什麼可以接受：** 不確定一律當本機——漏判的代價是「沒卸壓」，不是「外流」。
**這不是合規 DLP**，文件不可以宣稱它是。

### 8.7 host 與映像的套件版本會分岔，ARM worker 映像同樣有（design6 §13）

**是什麼：** `requirements.txt` 全部 `>=`，映像在 build 當下才解析版本。
`pytest -q` 全綠驗的是 host 那份環境，**不等於驗過實際跑的映像**。
**為什麼可以接受：** side project 先不釘版；代價是「重建映像＝要手動煙霧一次」
（Phase 90 與 94 之後都要真的跑一次工人）。

### 8.8 等 results 的時候佔一個 Celery 名額（計畫層新增）

**是什麼：** 本機是在**同一個 Celery 任務裡**同步長輪詢等結果（總覽 §10 追認項 c）。
`--concurrency=2`，所以**最多同時 2 筆在等雲端**，第 3 筆會排隊。
**為什麼可以接受：** 等待期間**不佔 GPU、不佔 CPU**（就是在 socket 上睡覺），
而且這是最貼近 design6 §2 流程圖的做法。真要改成「送出就放手、另一支收件行程」
會多一個行程與一整套狀態機，side project 不值得。手動煙霧時把
`CLOUD_RESULT_TIMEOUT_SECONDS` 調小（Phase 86 用 30 秒）比較不卡。

### 8.9 results 佇列是共用的，會收到別人的訊息（計畫層新增）

**是什麼：** 兩筆 job 同時在等時，A 可能先收到 B 的 results 訊息。
處理規則在 §2.5 第 3 條：那筆還在等 → **還回去**（可見度改 0）；已經不在或已 fallback →
當殘訊息刪掉，順手清它的 S3。
**為什麼可以接受：** 這是 Standard Queue 的本質，不是 bug。
改成「每個 job 一條佇列」會讓佇列數量無上限；改成 FIFO 又貴又慢（§1.2 沒列，但同理）。

### 8.10 閘門不看檔名（2026-09-01 改判，取代「規則版只看檔名」）

**是什麼：** `VlmGate.classify()` **必須**呼叫 `load_bytes`——要看圖，不能靠檔名。
`filename` 仍在簽章裡（呼叫端本來就有、假件要記帳），但 **verdict 不得依賴它**
（`test_檔名完全不影響判斷`：同一假模型，`身分證.jpg` 與 `receipt.jpg` 同一答案）。
無線鏡頭的 `camera.jpg` 與相簿匯出的 `IMG_4821.jpg` 一樣會被送進 VLM 短問。
**為什麼可以接受：** 產品負責人 2026-09-01 明示檔名規則不夠、成本要承擔。
失敗／沒把握仍是 `UNCERTAIN`＝不進 S3。頁首開關在雲端時短問會去 ollama.com（D2／D6）。

### 8.11 開機拉 `latest`，不是拉某個固定 sha（計畫層新增）

**是什麼：** systemd 的 `ExecStartPre` 做 `docker pull <ECR>/personaldocai-worker:latest`。
**為什麼可以接受：** 「跑的是不是新映像」不靠 tag 判斷，靠工人啟動時印的 `version=<sha>`
（`WORKER_VERSION`，D16 的「不靠 `latest` 當唯一 tag」就是這個意思）。
CD 同時推 `<sha>` 與 `latest` 兩個 tag，所以任何一版都回得去（`docker pull …:<舊 sha>` 再 restart）。

### 8.12 GitHub runner 模擬 arm64 很慢（計畫層新增）

**是什麼：** runner 是 amd64，靠 QEMU 模擬 arm64 跑 `pip install`，
實測這類映像要 **5〜15 分鐘**（純 amd64 build 大約 1〜2 分鐘）。
**為什麼可以接受：** CD 一天跑不了幾次，而且它是**非同步**的——push 完就可以去做別的事。
真要快就要租 arm64 runner（要錢）或改用 cross-compile 的 wheel（複雜度不成比例）。

### 8.13 失敗了不能按「再試一次」；待決定沒有「一次勾多張」（沿用增量五）

design5 §3 的兩條限制**本增量不改**：3 次自動重試做完就是做完了；歸類一張一張走三關。

---

## 9. 顆數與端點數的變化軌跡

> ⚠️ **下表的「新增幾顆」是本總覽 §2.7 定案的數字**，22 份 phase 檔逐字沿用。
> 實作時一律以 `pytest -q` 實查為準——**要對的是「本 phase 新增幾顆」，不是絕對數字**。
>
> **不變的規則：顆數只增不減，`skipped` 全程必須是 0。**
> 少了就是有人刪測試或標了 skip，**先查，不要改測試去湊**。

| Phase | 這個 phase 對顆數做了什麼 | 新增 | 累計 | 端點 |
|---|---|---|---|---|
| （開工） | 2026-08-31 實查基準 | — | **543 ＋ 0 skipped** | **22** |
| 74 | 新檔 `tests/unit/test_privacy_gate_unit.py`（11 顆） | **+11** | 554 | 22 |
| 75 | 同檔追加 9 ＋ `test_ai_timing_unit.py` 追加 1；**2026-09-01 實作時依 §10.2 追認項 S 之後的 review 裁決 R10 再補 2 顆**（`test_雲端短問回覆包著圍欄也解析得出來`、`test_本機短問把圖以base64塞進HumanMessage`，因 `judge()` 兩路原本零覆蓋）——**實查 +12、累計 566**；之後各列絕對值一律 +2、只對「本 phase 新增幾顆」 | **+10**（實 +12） | 564（實 566） | 22 |
| 76 | `test_ingest_job.py` 追加 4（積木單元測試）；**既有顆數一顆不改** | **+4** | 568 | 22 |
| 77 | 新檔 `test_cloud_ingest_unit.py`（11）＋ `test_ingest_job_store_unit.py` 追加 1 | **+12** | 580 | 22 |
| 78 | 新檔 `test_gated_ingest.py`（8）＋ `test_celery_app_unit.py` 追加 1 | **+9** | 589 | 22 |
| 79 | `test_cloud_ingest_unit.py` 追加 4 ＋ `test_gated_ingest.py` 追加 6；**2026-09-01 實作 review 裁決 R13 再補 1 顆** `test_雲端路available本身丟例外_閘門層也當作不可用`（`_遠端可用嗎` 的雙保險失去覆蓋）——實查 **+11、累計 602** | **+10**（實 +11） | 599（實 602） | 22 |
| 80 | 同兩檔各追加 5；**裁決 R14 再補 1 顆** `test_等結果時信箱丟例外_fallback本機而且清乾淨`（`wait_result` 例外要收成 result_timeout，否則 job 卡 analyzing）——預期 **+11、累計 613** | **+10**（實 +11） | 609（實 613） | 22 |
| 81 | 新檔 `test_gated_ingest_pdf.py`（7 顆）；**2026-09-02 裁決 R4 再補 2 顆**（`test_pdf_service_unit.py::test_max_pages只渲染前幾頁`、`test_privacy_gate_unit.py::test_PDF閘門只渲染第一頁`）；**review 裁決 R11 再補 2 顆守門測試**（`test_工人回的pages反序_仍依page欄位配對`、`test_工人只回第二頁_第一頁跳過且原圖是第二頁`：用原圖位元組證明配對靠 `page` 欄位不靠陣列索引）——預期 **+11、累計 624** | **+7**（實 +11） | 616（實 624） | 22 |
| 82 | 人工操作（零程式碼） | +0 | 616 | 22 |
| 83 | 新檔 `test_aws_mailbox_unit.py`（16 顆）；另**改** design5 的 boto3 掃碼 1 顆（改不計顆） | **+16**（實 +17：review fix wave 補 `test_put_object與send失敗時例外原樣往外丟`） | 632（實 641） | 22 |
| 84 | 建 bucket（驗收＝AWS CLI 輸出） | +0 | 632（實 641） | 22 |
| 85 | 建兩條佇列（驗收＝AWS CLI 輸出） | +0 | 632（實 641） | 22 |
| 86 | 新檔 `test_dependencies_cloud_unit.py`（2 顆）＋人工真 AWS 逾時煙霧 | **+2**（實 +3：review fix wave 補 `test_assume模式把config的四個值對應到AwsMailbox`） | 634（實 644） | 22 |
| 87 | 新檔 `test_cloud_worker_unit.py`（10）＋新檔 `test_cloud_roundtrip.py`（2） | **+12** | 646 | 22 |
| 88 | `test_cloud_worker_unit.py` 追加 5 ＋人工 Mac 端到端 | **+5** | 651 | 22 |
| 89 | `test_cloud_ingest_unit.py` 追加 6 ＋ `test_dependencies_cloud_unit.py` 追加 1 | **+7** | 658 | 22 |
| 90 | 新檔 `tests/integration/test_design6_error_paths.py`（Dockerfile／compose 掃碼 4 顆） | **+4** | 662 | 22 |
| 91 | 人工＋CLI（SG／IAM／ECR） | +0 | 662 | 22 |
| 92 | 人工（真機 Demo 2／2b）＋文件三份 | +0 | 662 | 22 |
| 93 | `test_design6_error_paths.py` 追加 4（OIDC trust 掃碼） | **+4** | 666 | 22 |
| 94 | 同檔追加 6（CD workflow 掃碼）＋人工 Demo 3 | **+6** | 672 | 22 |
| 95 | 同檔追加 10（8 顆掃碼 ＋ 2 顆真缺口補測） | **+10** | **682** | 22 |
| （收工） | 合計 **+139** | — | **682 ＋ 0 skipped** | **22** |

### 端點數怎麼算（不要用 `app.routes`）

```python
# 正確做法（三顆既有清點測試都是這樣寫的）
paths = client.get("/openapi.json").json()["paths"]
運算元 = [(path, method) for path, item in paths.items() for method in item]
assert len(運算元) == 22
```

⚠️ **不要用 `app.routes` 清點**——FastAPI 0.141 有 `_IncludedRouter` 的已知坑，路由不會被攤平。
⚠️ WebSocket `/camera/{token}/signal` 依 FastAPI 的行為不進 `openapi.json`，不計入；本增量也不加新的。
⚠️ **本增量端點從頭到尾都是 22**（design6 §5）。任何一個 phase 讓這個數字變了，就是做錯了。

### 零依賴實證（每個 phase 的驗收清單都要有這一條）

```bash
pytest -q                                             # 記下顆數
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q          # 顆數相同 ＝ 零 Ollama 依賴
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q     # 顆數相同 ＝ 零 Redis 依賴
AWS_ENDPOINT_URL=http://127.0.0.1:9 pytest -q         # 顆數相同 ＝ 零 AWS 依賴（Phase 83 起）
# Phase 83 之後一律三個一起指（省時間，也證明它們不會互相掩護）：
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

---

## 10. 誠實揭露：design6 沒寫清楚、由計畫層裁決的項目

> 📌 **為什麼要有這一節：** 下面每一條都是「design6 沒有寫、但不決定就做不下去」的東西。
> 它們是**計畫層的判斷，不是產品負責人的字**。列在這裡是為了讓產品負責人一眼看出
> 哪些是自己拍的板、哪些是我們補的。
>
> **要推翻其中任何一條，請直接說**——每一列都寫了「要改的話回哪個 phase」。
> 實作者**不得**自行改判，也不得在 phase 檔裡寫成「design6 說……」。

### 10.1 orchestrator 已列的 12 條（a〜l）

| # | 裁決內容 | 為什麼 | 不同意的話回哪個 phase 改 |
|---|---|---|---|
| **a** | S3 多一個鍵 `documents/{job_id}/context.json`（design6 §2.2 只列了 `input.*` 與 `result.json`） | 沒有它工人組不出**同一份** prompt——資料夾清單、實體清單、糾錯 few-shot 都在本機資料庫裡。放 SQS 會違反 §2.3「body 只含 `job_id`、`s3_key`」，所以放 S3 | **77**（`build_context`）、**79**（submit 順序）、**87**（工人讀它） |
| **b** | 分支是 **`main`**，OIDC 的 `sub` 鎖 `…:ref:refs/heads/main`（design6 §6 寫的是 `master`） | 實查 `git branch --show-current` ＝ `main`；remote 是 `https://github.com/1104030360/personalDocAI.git`。鎖錯分支＝CD 永遠拿不到憑證 | **93**（trust JSON）、**94**（workflow 的 branches 條件） |
| **c** | 本機「等 results」是在**同一個 Celery 任務裡同步長輪詢**（佔一個 concurrency 名額，但不佔 GPU） | 最貼近 design6 §2 的流程圖，也最少活動零件。代價寫在 §8.8 | **79／80**（`wait_result` 的呼叫位置）——要改成非同步收件會動到 78〜81 全部 |
| **d** | results 佇列是**共用**的，收到別人的 `job_id` 要「還回去或當殘訊息刪掉」（規則見 §2.5 第 3 條） | Standard Queue 沒有「只給我的訊息」這種東西。不處理的話兩筆同時跑就會互相偷結果 | **80**（`wait_result` 的第 3 條規則） |
| **e** | 開機拉 `latest`；CD **同時**推 `<sha>` 與 `latest`；「跑的是不是新映像」靠 `WORKER_VERSION` 的 log 驗 | D16 說「不靠 `latest` 當唯一 tag」——我們的解讀是「tag 可以有 `latest`，但**驗證**不靠它」。`<sha>` 那個 tag 讓任何一版都回得去 | **91**（systemd unit）、**94**（CD 的 tags）、**90**（`ARG GIT_SHA`） |
| **f** | 隱私閘門**不看檔名**；`camera.jpg`／`IMG_4821.jpg` 一樣送 VLM 短問。失敗→UNCERTAIN＝不進 S3 | 產品負責人 2026-09-01 推翻 2026-08-31 的「只看檔名／可選本機模型」。design6 D4 改判後的契約 | **74**（`VlmGate`）；**75**（真模型跟開關） |
| **g** | **雲端看圖三次都失敗＝這筆 job 失敗**（錯誤表第 7 列），**不是** fallback 本機 | 遠端明明活著，只是 AI 看不懂——本機再看三次多半也一樣，而且會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意 | **79**（`understood=false` → `fail_job`）、**95**（那顆補測） |
| **h** | EC2 上的機密（`OLLAMA_API_KEY` 等）用 **Session Manager 手動**建 `/opt/personaldocai/worker.env`（`chmod 600`），**不用** Parameter Store | 少一個服務、少一組 IAM 權限、少一個要記的名字。side project 的機密只有一把 key，一年動不到一次 | **92**（放 env 檔那一步）；要改成 Parameter Store 要同時改 **91** 的 role policy |
| **i** | 改 design5 那顆掃碼測試 `test_沒有背景任務框架的替代品也沒有雲端儲存`：把 `boto3` 從禁止清單拿掉 | design6 §1.1 第 1 列**正式推翻** design5 §3 的「不做雲端物件儲存」。`s3fs`／`minio`／`google-cloud-storage`／`flower` **仍然禁止** | **83**（改那一顆，並在註解引 design6 §1.1） |
| **j** | `Dockerfile` 改多階段（`base` → `cloud-worker` → **`app` 放最後**），`compose.yaml` 一個字不改 | 不帶 `--target` 的 `docker build .` 會停在**最後一個** stage，所以 compose 的 `build: .` 仍然蓋出 app。省掉「改 compose 又要重測四個容器」 | **90**（Dockerfile）；要改成兩個 Dockerfile 就要動 compose |
| **k** | 工人程式放 **`app/workers/cloud_worker.py`**，不是 `scripts/cloud_worker.py` | `.dockerignore` 排除 `scripts/`——放那裡的話工人程式**不會進映像**，而且是**安靜地**不進去（build 成功、run 時才 `ModuleNotFoundError`） | **87**（建檔位置） |
| **l** | `CLOUD_ROUTE=assume`（假設遠端開著）只給**階段丁**（Mac 上跑工人）與除錯用；戊之後日常用 `ec2` | `assume` 不做任何探測，EC2 關著時它會傻傻送出、然後等到逾時才 fallback（多浪費 5 分鐘）。日常一定要用 `ec2` | **86**（建立它）、**92**（`.env` 改成 `ec2`） |

### 10.2 撰寫本總覽時另外發現、必須裁決的 19 條（A〜S）

| # | design6 怎麼寫的（或沒寫） | 計畫層怎麼裁決 | 落在哪個 phase |
|---|---|---|---|
| **A** | §9 說「必釘（**名稱實作時可調**）」 | **不可調。** 22 份 phase 檔要互相對齊（78 的測試會被 79／80 追加、87 的假件會被 79 用），名字浮動就對不起來。本總覽 **§2.7 逐顆定案**，phase 檔逐字沿用；真的必須多加一顆時可以加，但要在該 phase §8 明寫「比總覽多 N 顆」，**不准為了湊數字刪測試** | 全部 22 份 |
| **B** | §11 沒說錯誤路徑的測試檔什麼時候開 | **`tests/integration/test_design6_error_paths.py` 在 Phase 90 就開檔**，不等到 95。理由：90／93／94 各自都有「部署設定檔掃碼」要放，全堆到 95 會讓 95 變成一個要重讀五份設定檔的大 phase（增量五的 `test_design5_error_paths.py` 到 71 才開，是因為那時沒有設定檔要掃） | **90**（開檔）→ **93**／**94**（追加）→ **95**（收尾） |
| **C** | §11 只寫一個 `app/services/cloud_route.py` 等 | **拆成兩層**：`cloud_ingest.py`（流程，只認 `CloudMailbox` Protocol）＋ `aws_mailbox.py`（唯一碰 boto3）。合成一個檔的話，78〜81 的每一顆流程測試都會被迫依賴 boto3，第五道安全網也就沒意義了 | **77**（`cloud_ingest.py`）、**83**（`aws_mailbox.py`） |
| **D** | §2 的流程圖沒說「等雲端結果時 job 的 status 是什麼」 | **維持 `analyzing`，不新增狀態。** `JOB_STATUSES` 仍是四個。加一個 `waiting_cloud` 會讓 `progress_panel.js` 的四種狀態顯示壞掉，而 design6 §3 明文「前端不新增」 | **79**（用結果落庫那段不動 status） |
| **E** | §2.2 說 `result.json` 對齊 `PhotoUnderstanding`，沒說雲端看圖的次數要不要回寫 job | **不回寫 `job["attempt"]`。** 雲端的 `attempts` 只寫進 `result.json` 與工人的 log。本機只在「用結果落庫」那段的 embedding 重算時寫 `attempt`。回寫的話進度面板的「第 N 次」會忽然跳，而使用者根本不知道有雲端這回事 | **79**（落庫段） |
| **F** | §2 說「本機 GetObject `result.json` → 本機 embed ＋ INSERT ＋ 原圖／縮圖」，但 PDF 的每頁 PNG 從哪來沒寫 | **本機自己再 `render_pages()` 一次**（工人拆頁是為了看圖、本機拆頁是為了拿到要存檔的 PNG 位元組）。**不把工人拆好的每頁 PNG 放 S3**——那會讓 S3 物件數隨頁數暴增，而 PDF 拆頁是純 CPU、幾百毫秒的事 | **81**（PDF 雲端路） |
| **G** | §3.10 把「產品負責人親自完成 Phase 82 的開戶」寫進 G1 的內容，容易被讀成「82 要在 G1 之前做完」 | **★G1 ＝ 甲的驗收（實作者跑得出證據）＋ 產品負責人明示「可以開始花 AWS 資源」。Phase 82 排在 G1 之後**，它就是「開始碰 AWS」的第一步。G1 的憑據**不含** 82 的產出。理由：開戶就開始算 Free plan 的 6 個月，甲還沒過就開戶等於白燒時間 | **★G1** 的定義（§4）、**82** 的前置條件 |
| **H** | design6 完全沒提「重構 `ingest_job.py`」 | **Phase 76 是計畫層加的一份純重構。** 沒有它的話，79 的「用結果落庫」只能複製一份 `_insert_photo_with_files` 與 `_fail`（＝兩份會漂移的同款程式碼，違反產品負責人的「不留過渡產物」）。它的驗收條件很硬：**對外行為零改變、既有顆數（本次排在 74／75 之後＝564）一顆都不能改**（與開工快照相減後 `tests/` 只多 `test_ingest_job.py` 的改動、零刪除行） | **76** |
| **I** | design6 §6 只寫「本機：指定 prefix 的 s3:Put／Get／Delete…」的最小權限 IAM | **再建一個 `personaldocai-admin`（AdministratorAccess）只給 Mac 上的 `aws` CLI 用**：最小權限的 `personaldocai-mac` 連 `s3:CreateBucket` 都沒有，Phase 84／85／91／93 用它建資源會 AccessDenied。admin 的 key 只在 `aws configure`、mac 的 key 只在 `.env`；`.env` 載進 shell 後要 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` | **82**（建）、84／85／91／93（用） |
| **J** | §9「必釘」清單沒有 `get_object` 的成功路徑 | Phase 83 多加 1 顆 `test_get_object拿得回位元組而delete_objects送出鍵清單`（**+16 顆**，不是 +15）：沒有它，「`get_object` 永遠回 None」的實作會讓其餘 15 顆全綠，而那正是「把雲端結果拿回家」那一步。顆數軌跡自 83 起 +1，終值 **682** | **83** |
| **K** | §2.6 工人規則沒說「訊息本身壞掉」怎麼辦 | s3_key 空的、或副檔名不是 .jpg／.png／.pdf → log warning、`delete_job_message`、return（不寫任何東西）。壞訊息留在佇列只會每 900 秒回來一次。同理 `aws_mailbox._receive` 收到 **body 不是 JSON／沒有 `job_id`** 的訊息：log warning、用 receipt handle 直接刪掉、回 None（不然呼叫端拿不到 receipt handle，那則壞訊息會每 900 秒回來、四天不散） | **87**（工人）、**83**（`_receive`） |
| **L** | D4 改成 VLM 短問之後，縮圖在哪一層、模型多久 | 縮圖（長邊 ≤512、轉 PNG）放在 `VlmGate` 呼叫 `model.judge()` **之前**（Phase 75），`FakePrivacyModel.last_image_bytes` 才驗得到。`OllamaPrivacyModel` 跟 `AI_BACKEND` 走，模型名同 `get_vlm`。短問耗時本機推估 20〜60 秒、雲端約 2 秒（**未實測**）——Phase 78 接線後的煙霧回填 §8.6／§8.10 | **75**（實作）、**78**（煙霧回填） |
| **M** | design6 §6 寫「trust 的 `sub` 鎖 repo＋`master`」（格式 `repo:OWNER/REPO:ref:…`） | **`sub` 改用 GitHub 的不可變主體格式** `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`：GitHub 2026-07-15 起新建 repo 預設帶 owner／repo 數字 ID（[Immutable subject claims](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)、[Changelog 2026-04-23](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)），本 repo 2026-08-28 建立、`gh api …/actions/oidc/customization/sub` 實查為此格式；沿用舊格式 CD 會紅在 `configure-aws-credentials`。兩個 ID 公開可查、非機密。**不**用 `PUT …/customization/sub` 切回舊格式（多一個藏在 GitHub 的開關）。同時 `deploy` 的 `if` 加 `workflow_run.event == 'push'`（防 fork PR 分支叫 `main`） | **93**（trust JSON＋掃碼測試）、**94**（`if`） |
| **N** | design6 §6 把「本機」與「EC2 instance role」的權限分兩列寫（本機只有 Send jobs／Receive results） | **`personaldocai-mac` 的 policy 兩邊都要有**：Phase 88（Mac 直跑工人）與 Phase 90（Mac 上用容器跑工人）用的都是 `.env` 這把 key，工人要 jobs `ReceiveMessage`／`DeleteMessage`／`ChangeMessageVisibility` 與 results `SendMessage`，否則第一次 `ReceiveMessage` 就 AccessDenied（phase-90 reviewer 抓到）。EC2 上仍用 instance role（§2.8 那列不變）。仍不給 `CreateBucket`／`PurgeQueue`——建資源與清佇列走 admin profile（`ListBucket` 另見 P） | **82**（policy JSON） |
| **O** | design6 §11 對 systemd 沒著墨 | unit 用 `ExecStop=/usr/bin/docker stop -t 120 cloud-worker` ＋ `TimeoutStopSec=150`：工人收到 SIGTERM 會做完手上那一則再退，多頁 PDF 可能超過 docker 預設的 10 秒寬限（超時＝SIGKILL；資料不會壞——D17 冪等＋jobs 900 秒後重投——但會多跑一次雲端看圖）。`run-instances` 加 `HttpPutResponseHopLimit=2`：容器裡的 boto3 跨 Docker bridge 到 IMDS 多一跳，hop limit 1 拿不到 instance role 憑證（AWS 官方明寫） | **91**（unit）、**92**（run-instances） |
| **P** | design6 §6 只寫「指定 prefix 的 s3:Put／Get／Delete」 | **兩份 policy 都要加 bucket ARN 的 `s3:ListBucket`**（`personaldocai-mac-policy` 與 `personaldocai-worker-role`）：S3 官方規則——呼叫者沒有 `ListBucket` 時，對不存在的 key 做 `GetObject` 回 403 AccessDenied 而非 404 NoSuchKey；本增量三處靠 404 判「還沒有」（工人冪等 `get_object(result_key)`、本機 `fetch_result`、`aws_check.py` 的 get-after-delete），少了它一張圖都處理不了。**不**改成把 AccessDenied 當「不在」（會把真的權限錯誤吞掉） | **82**（mac policy）、**91**（worker role policy）、**83**（陷阱） |
| **Q** | design6 §1.2 寫「把 PDF／JPEG 塞進 SQS 超過 256 KB 上限」 | SQS 標準佇列上限已是 **1 MiB**（boto3 `send_message` 現行文件）；結論不變——影像仍不進 SQS（多頁 PDF 動輒幾十 MB），只是理由的數字要更新 | 文件層 |
| **R** | D17 只說「同一 job_id 不得 INSERT 兩張」，沒說收據要在哪一步寫 | 雲端路落庫的順序固定為 **INSERT → 立刻 `store.update(job_id, photo_ids=[photo_id])` → `cleanup()`（S3 網路呼叫，boto3 重試可拖數十秒）→ `finish_image_job`**。`cleanup` 期間 worker 被殺的話，沒先寫 photo_ids 的版本會在重送時（result.json 已刪 → fallback 本機）再 INSERT 一張（phase-79 reviewer 抓到）。PDF 路每頁本來就同一次寫 `pages_done`／`photo_ids`，只要確保它在該頁的 cleanup 之前 | **79**（單圖）、**80**／**81**（整檔重貼要帶著） |
| **S** | D6 說「閘門跟著頁首開關走」，D4 說用同一顆看圖模型；沒說**閘門跑在哪個行程**。閘門跑在 Celery worker（D5），而 `celery_app.ingest_task` 的 docstring 早就寫明：worker 行程的 `config.AI_BACKEND` **永遠是預設 `local`**，開關值只存在入列當下抄進 job 的 `ai_backend` 快照（design5 D14） | 若 worker 用 `dependencies.get_privacy_gate()` 建閘門，頁首撥到雲端時閘門仍打本機——**違反 D6 而且安靜**（log 會誠實印 `backend=local`，但沒人會去比對）。裁決：Phase 75 在 `dependencies.py` 加 `build_privacy_gate_for_backend(ai_backend)`（比照 `build_vlm_for_backend`），`get_privacy_gate()` ＝ `build_privacy_gate_for_backend(config.AI_BACKEND)`；Phase 78 的 `ingest_task` 傳 `gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"])`，conftest 的 monkeypatch 同時蓋兩支。2026-09-01 開工校準（phase0901）時發現 | **75**（建）、**78**（celery_app＋conftest＋`test_ingest_task把gate與cloud都傳進去` 多斷言快照） |

---

## 11. 開工前的最後檢查

```bash
# 1. 環境
source .venv/bin/activate
docker compose ps --no-trunc          # 四個服務都要 Up；db 與 redis 要 Up (healthy)

# 2. 基準（三個數字都要對得上本總覽 §2.1）
pytest --collect-only -q | tail -1    # 543 tests collected
pytest -q                             # 543 passed，且沒有 skipped
curl -k -s https://127.0.0.1:8000/health
git branch --show-current             # main（不是 master）

# 3. 工作區乾淨（避免把別的東西一起 commit）
git status --short
git status --short docs/spec/         # 必須是零輸出，而且本增量全程保持零輸出

# 4. 備份
#    本增量**不改資料庫結構**，但 74〜95 會跑很多次全量測試與手動煙霧，
#    而且戊段會在真機上動東西。動手前留一份，成本 30 秒。
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-增量六前.dump
tar -czf ~/PersonalDocAI-data-增量六前.tar.gz data/
#    ⚠ 第二行不能省：data/ 裡是原圖與縮圖，不入版控，全世界只有一份。
#      資料庫還原回來但 data/ 沒了的話，照片列還在、縮圖與大圖全變 404。

# 5. 讀完這三份再動手
#    docs/design/design6.md                  ← canonical design，全文
#    docs/plan/unfinish/phase-74-*.md        ← 第一個要做的 phase
#    CLAUDE.md                               ← 專案現況與指令區
```

**開始做吧。一次一個 phase，先寫會紅的測試。★G1 之前一行 AWS 指令都不准打。**

---

## 附：本文件引用的官方文件

**design6 §15 已列（撰寫 design 時查過）**

- [AWS Free Tier](https://aws.amazon.com/free/)
- [AWS Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/)
- [新帳號點數制公告（2025-07-15）](https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits/)
- [Free plan 可選服務清單](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html)
- [SQS Standard／at-least-once](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 大訊息與 S3 pointer](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
- [S3 Block Public Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [ECR 推映像](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push.html)
- [SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [GitHub OIDC → AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [EC2 t4g 試用 FAQ](https://aws.amazon.com/ec2/faqs/)
- [公有 IPv4 收費](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)

**本計畫另外會用到的（各 phase 檔的「附：官方文件」逐份挑用）**

- [boto3 憑證與環境變數](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
- [boto3 設定（含 `AWS_ENDPOINT_URL`）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html)
- [boto3 S3 client：`put_object`／`get_object`／`delete_objects`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [boto3 SQS client：`send_message`／`receive_message`／`delete_message`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs.html)
- [SQS `ChangeMessageVisibility`（把可見度改成 0 ＝ 立刻還回佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html)
- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS `PurgeQueue`（60 秒只能做一次）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
- [S3 預設加密（SSE-S3）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)
- [S3 Lifecycle 設定](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [S3 Gateway VPC endpoint（免費）](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html)
- [EC2 T4g（Graviton／arm64）機型](https://aws.amazon.com/ec2/instance-types/t4/)
- [用 SSM 公開參數取最新 AL2023 AMI（`/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`）](https://docs.aws.amazon.com/linux/al2023/ug/ec2-ssm-agent.html)
- [EC2 user-data（開機腳本）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [EC2 Stop 與 Terminate 的差別](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [Security group 規則](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules.html)
- [SSM Session Manager（不開 SSH 也能進 shell）](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [EC2 instance profile（把 role 掛到機器上）](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_switch-role-ec2_instance-profiles.html)
- [IAM policy 語法](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies.html)
- [AWS Budgets（建預算警報）](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
- [GitHub Actions `workflow_run` 觸發條件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
- [`aws-actions/configure-aws-credentials`](https://github.com/aws-actions/configure-aws-credentials)
- [`aws-actions/amazon-ecr-login`](https://github.com/aws-actions/amazon-ecr-login)
- [`docker/build-push-action`（多平台 build）](https://github.com/docker/build-push-action)
- [`docker/setup-qemu-action`（模擬 arm64）](https://github.com/docker/setup-qemu-action)
- [Docker 多平台建置](https://docs.docker.com/build/building/multi-platform/)
- [Dockerfile 多階段建置與 `--target`](https://docs.docker.com/build/building/multi-stage/)
- [systemd `EnvironmentFile=`](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#EnvironmentFile=)
- [Celery Signals（`worker_ready`）](https://docs.celeryq.dev/en/stable/userguide/signals.html)
- [Pillow `Image.thumbnail`（隱私模型送圖前縮圖用）](https://pillow.readthedocs.io/en/stable/reference/Image.html)
