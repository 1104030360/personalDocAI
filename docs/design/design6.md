# PersonalDocAI — 設計文件（增量六）：本機隱私閘門與可關掉的雲端 worker

> **一句話：本機仍是正本；上傳先進既有 Celery，用現有看圖 VLM 問一句短問題分成敏感、非敏感、不確定（不看檔名；模型與頁首本機／雲端開關同一套）；只有非敏感且 EC2 開著才走 S3→SQS→EC2（Ollama Cloud 看圖）→本機入庫；EC2 關掉、AWS 連不上、或逾時沒結果，一律 fallback 成現在這台電腦的入庫流程，使用者不必改操作。**

> 🎯 **仍是 side project：不要過度設計。** 只做本文件寫到的事。定案不可逆、人確認才釘實體／建待辦、embeddings 一律本機、單一使用者、不做刪除照片、openapi 零 DELETE、頁首 AI 開關語意不變，全部維持 design5.md 以降不變。

| 項目 | 內容 |
|---|---|
| 前提 | 增量五（design5.md，Phase 52〜72）已落地：`POST /photos` 202、Redis＋Celery、staging、`run_ingest_job`；CI 有 ruff＋pytest（Phase 73） |
| 目的 | 作品集可 demo 一條自己控的雲端管線與 CI/CD；非敏感看圖在 EC2 開著時可卸離這台 Mac；**遠端關掉時產品行為與增量五逐字相同** |
| 狀態 | 產品負責人 2026-08-31 對話拍板；**2026-09-01 改判閘門：只用 VLM 短問題、不看檔名、跟著頁首開關**。尚未實作（實作分 phase，一次一項） |
| 衝突時誰贏 | 本文件列出的推翻項以本文件為準；未提及的行為仍以 design5.md、design4.md、design3.md、design2.md、design1.md、design.md v4 為準 |

---

## 0. 實作計劃總序（不可對調）

**先做閘門與 fallback，再碰 AWS。** 沒有「EC2 關掉＝本機原樣」的契約，後面每一層都在賭遠端永遠開著。

```text
階段甲  本機 Privacy Classifier ＋ fallback 契約
        三分類；不確定＝本機
        遠端不可用 → 直接 run_ingest_job（與現在相同）
            │
            ▼
階段乙  非敏感且遠端可用 → 上傳 S3（mailbox）
            │
            ▼
階段丙  S3 成功 → jobs queue SendMessage（只放 pointer）
        兩條 Standard Queue 一起建：jobs（本機→工人）、results（工人→本機）
            │
            ▼
階段丁  本機 cloud_worker.py
        收 jobs、下載 S3、Ollama Cloud 看圖、寫 result.json、SendMessage results
        （還不上 EC2；本機 Celery 收 results 再 GetObject）
            │
            ▼
階段戊  同一支 worker 進 Docker → EC2 t4g.small（ARM）
            │
            ▼
階段己  CI 過後：OIDC → 建映像 linux/arm64 → ECR → SSM 拉新 image
```

| 階段 | 做什麼 | 何時可以開始 | 何時算過 |
|---|---|---|---|
| **甲** | classifier＋「遠端關＝本機路」 | 本文件拍板後即可 | 敏感／不確定零 S3 呼叫；假遠端關閉時非敏感也走 `run_ingest_job`；pytest 不連 AWS |
| **乙** | 僅 NON_SENSITIVE 且遠端可用才 PutObject | 甲綠 | 敏感檔 bucket 仍空；非敏感有 `documents/{job_id}/input.*` |
| **丙** | jobs 佇列 SendMessage pointer；建 results 佇列 | 乙綠 | jobs body 無檔案位元組，只含 `job_id`、`s3_key`；results 佇列已存在、尚無訊息 |
| **丁** | Mac 上的 `cloud_worker.py` | 丙綠 | 本機模擬工人：jobs→S3→看圖→`result.json`→SendMessage results；本機 Receive 後 GetObject 入庫 |
| **戊** | EC2 跑同一映像 | 丁綠 | 真機 Start→處理一筆→Stop；Stop 後下一筆自動本機 |
| **己** | GitHub Actions CD | 戊能手動部署 | push 後 ECR 有 `<sha>`；SSM 更新；**不靠 `latest` 當唯一 tag** |

**禁止：** 甲還沒綠就開 S3／SQS／EC2。  
**禁止：** 把影像位元組塞進 SQS。  
**禁止：** EC2 開 inbound HTTP／SSH（22）。管理只走 SSM。  
**禁止：** NAT Gateway、ALB、RDS、ElastiCache、ECS、Fargate、Lambda、K8s。  
**禁止：** 用 Privacy Gate 關掉頁首「AI 模型：本機｜雲端」。  
**禁止：** 遠端不可用時上傳改 5xx 或讓使用者重傳——必須 fallback。

---

## 1. 已拍板決策（2026-08-31 對話）

| # | 決策 | 內容 |
|---|---|---|
| D1 | 本機仍是正本 | 照片列、原圖、縮圖、向量、待決定、詢問全部仍在這台 Mac 的 Postgres＋`data/`。S3 **不是**檔案櫃 |
| D2 | Privacy Gate 在進 S3 之前 | 分類由本機 Celery worker 在 **PutObject 之前**觸發。**禁止**分類前把檔案送到 S3／EC2。閘門用現有看圖 VLM 問短問題（敏不敏感），**不看檔名**。頁首開關在「雲端」時，閘門可以把圖送到 **ollama.com** 問這句——與入庫看圖同一扇門（產品負責人 2026-09-01：開關本就是開發加速用）。這**不是**「先送到 AWS 再問敏不敏感」 |
| D3 | 三分類 | `SENSITIVE`／`NON_SENSITIVE`／`UNCERTAIN`。規則：**敏感→本機；不確定→本機；只有非敏感才允許雲端管線** |
| D4 | Classifier ＝ VLM 短問題 | 同一顆看圖模型（本機 `VLM_MODEL`／雲端 `OLLAMA_CLOUD_VLM_MODEL`），**另一份短 prompt**（只答敏不敏感＋有沒有把握），不是完整 9 欄 understand。不看檔名、無關鍵字表。失敗／沒把握 → `UNCERTAIN` → 本機。圖可縮到長邊 ≤512 再問。完整看圖仍是入庫那一次（本機或 EC2）。產品負責人接受這筆推論成本 |
| D5 | 插在 Celery 開頭 | `POST /photos` 仍 202、仍先 staging。classifier 在既有 worker 拿 job 之後、看圖之前。不把分類放進 HTTP 路徑 |
| D6 | 頁首 AI 開關：閘門跟著走、不准關它 | `AI_BACKEND` 本機／雲端維持增量五 D14。Gate **跟著**開關選本機或雲端 VLM；**不**因敏感就把開關撥回本機。那扇門的用途是速度 |
| D7 | 雲端管線只給非敏感 | 僅 `NON_SENSITIVE` **且**遠端可用（D10）才：PutObject → jobs queue → EC2 → result.json → results queue → 本機 GetObject |
| D8 | S3 是寄物櫃 | `documents/{job_id}/input.*`、`documents/{job_id}/result.json`。private、Block Public Access、SSE-S3（不加 customer KMS key）。處理成功後刪；Lifecycle 1〜3 天當掃把 |
| D9 | **完成訊號＝results queue（方案 B）** | 兩條 Standard Queue，FIFO 不做。**jobs**：本機 Send、工人 Receive，body `{"job_id","s3_key"}`（s3_key＝input）。**results**：工人 `PutObject result.json` **成功後**才 Send、本機 Receive，body `{"job_id"}`（不含位元組）；本機再 GetObject `documents/{job_id}/result.json`。S3 Event→SQS 不做（避免「物件出現但 JSON 還沒寫完」誤醒）。**禁止**本機用輪詢 HeadObject 當完成訊號。逾時仍走 D10 |
| D10 | **遠端關掉＝fallback 本機** | EC2 Stop、不是 `running`、AWS 憑證／API 失敗、S3／SQS 不可達、或送出後逾時 results 沒有該 `job_id` → **這筆 job 改走現有 `run_ingest_job`**，行為與增量五相同。不上傳失敗、不要求使用者重傳、進度面板仍是 queued／analyzing／成功消失。見 §2.1 |
| D11 | EC2 只當工人 | Docker cloud worker。無公開 HTTP、無網站、無公網 API。Security group inbound 全關。出站 TCP 443（S3、SQS、ECR、SSM、ollama.com） |
| D12 | EC2 看圖一律 Ollama Cloud | 實例無 GPU、不跑本機 Ollama。與頁首開關無關 |
| D13 | 本機入庫 | 拉回 `result.json` 後，**embedding（bge-m3）與 INSERT／原圖／縮圖仍在本機**。向量必須與庫裡同源 |
| D14 | 作品集為主、順便卸壓 | 成功標準是三條 demo（§12）＋EC2 開著時非敏感不佔這台 GPU／Celery 名額。不是「比頁首雲端開關更快」，也不是改詢問 UX |
| D15 | AWS 帳號 Free plan | 新帳號點數制（最多 $200 點數、Free plan 不扣卡）。目標卡片 **$0**。用完 EC2 就 **Stop**。映像 **`linux/arm64`**，機型 **t4g.small**。見 §7 |
| D16 | CI／CD 分開 | 現有 GitHub Actions CI 不動契約。CD：CI 綠 → OIDC 短憑證 → build `linux/arm64` → ECR `personaldocai:<git-sha>` → SSM Run Command 在 EC2 上 pull＋重啟。EC2 Stop 時 CD 仍可 push ECR；下次 Start 再拉 |
| D17 | SQS at-least-once | worker 與本機收結果都必須冪等（沿用 job 的 `photo_ids`／`pages_done` 思路）。同一 `job_id` 不得 INSERT 兩張 |

### 1.1 本增量明確推翻的舊決策

| 舊決策 | 本文件改成 |
|---|---|
| design5.md §3「不做：雲端物件儲存、S3」 | 僅 NON_SENSITIVE 且遠端可用時，S3 當 mailbox；正本仍本機 |
| design.md v4「明確不做雲端部署」 | 允許一台可 Stop 的 EC2 worker ＋ ECR／SSM；**不**把 FastAPI／Postgres／Redis／Celery／Ollama 搬上雲 |
| design3.md「不要第二個分類模型」（部分） | 允許 **Privacy Classifier** 這一個用途：同一顆看圖 VLM、另一份短 prompt；完整看圖仍是入庫那一次（雲端管線在 EC2、本機管線在 Celery）。**不是**第二個模型、也**不是**檔名規則 |
| 本文件 2026-08-31 初稿 D2／D4（檔名規則為主、可選本機模型、禁止雲端 AI 當閘門） | 2026-09-01 產品負責人改判：閘門只看圖、短問題、跟著頁首開關；雲端開關時接受圖先去 ollama.com。S3／EC2 仍必須等 `NON_SENSITIVE` |
| design3.md「不做雲端模型」（已於 2026-08-22 為頁首開關作廢） | 本文件不恢復該禁令；EC2 看圖固定 Ollama Cloud |

**未推翻：** 202 受理契約、staging 禁止進 Redis、Celery concurrency=2、embeddings 一律本機、頁首 AI 開關、定案不可逆、單一使用者、不做刪除、openapi 零 DELETE、Ollama 不進本機 Docker、`postgresql@14` 不動、待決定／詢問流程。

### 1.2 被否決（不要重開）

| 方案 | 為什麼否決 |
|---|---|
| 整套 personalDocAI 搬上 EC2 | 太重；本機才是檔案櫃 |
| EC2 開上傳 API，本機直接 POST 檔 | 工人要開門；與 D11 衝突 |
| 把 PDF／JPEG 塞進 SQS | 超過 256 KB 上限 |
| 本機輪詢 HeadObject 當完成訊號（方案 A） | 產品負責人 2026-08-31 選 B：results queue 叫醒再 GetObject |
| 結果永遠只活在 S3、不入本機庫 | 待決定／詢問讀不到 |
| EC2 回呼家裡 Mac 的 HTTP | 無穩定公網 IP；要開 inbound |
| Privacy Gate 管頁首雲端開關 | 產品負責人：開關是為本機太慢；閘門跟著走，不准去關它（D6） |
| 檔名關鍵字當閘門主判斷 | 產品負責人 2026-09-01：真實檔名幾乎沒關鍵字，閘門必須看圖；不看檔名、無敏感字捷徑 |
| 閘門與入庫合成一次完整 9 欄看圖 | 合成後本機（或 ollama.com）已經看完，S3→EC2 卸壓沒了。閘門只問短問題；完整看圖仍是入庫那一次 |
| RDS／ECS／Fargate／Lambda／ALB／NAT Gateway／K8s | 無需求；NAT 會打爆 Free plan 點數 |
| 常開 EC2 換「永遠卸壓」 | 產品負責人要 $0 與用完 Stop；卸壓只在開機時成立（D10、D15） |
| SSE-KMS customer-managed key | 月費；mailbox 用 SSE-S3 |
| 第一天同時開 classifier＋S3＋SQS＋IAM＋EC2＋CD | 壞了不知道哪一層 |

---

## 2. 流程

```text
上傳／鏡頭快門（不變）
        │
        ▼
  FastAPI：格式檢查 → staging → JobStore → Celery → 202
        │
        ▼
  本機 Celery worker 拿 job
        │
        ▼
  Privacy Gate（本機 worker 觸發；VLM 短問題，跟頁首開關）
        │
        ├─ SENSITIVE 或 UNCERTAIN
        │      → run_ingest_job（與增量五相同）
        │         看圖跟頁首開關走（本機 Ollama 或 ollama.com）
        │
        └─ NON_SENSITIVE
               │
               ▼
         遠端可用？（D10）
               │
               ├─ 否 → run_ingest_job（fallback，與增量五相同）
               │
               └─ 是
                    → PutObject input
                    → jobs queue { job_id, s3_key }
                    → 本機 ReceiveMessage results（長輪詢；逾時→D10）
                    → GetObject result.json
                    → 本機 embed ＋ INSERT ＋ 原圖／縮圖
                    → 刪 staging、刪 S3 物件、刪 results 訊息
                    → 成功則 JobStore 刪 job（與現在成功語意相同）

EC2（僅在 running）
  收 jobs → GetObject input → Ollama Cloud 看圖
        → PutObject result.json → SendMessage results { job_id }
  不寫 Postgres、不算 embedding
```

### 2.1 Fallback（遠端關掉）——必做契約

「遠端不可用」成立時（任一即成立）：

1. EC2 實例狀態不是 `running`（DescribeInstances；快取可短 TTL，避免每張圖都打 AWS）
2. 沒有 AWS 憑證、或 STS／S3／SQS API 失敗
3. PutObject／SendMessage 失敗
4. 已送出，但在逾時內 results 佇列沒有該 `job_id`（因而也沒有可用的 `result.json`；worker 掛了、Stop 發生在半路）

**則這筆 job：**

- 用 **staging 裡還在的檔** 呼叫既有 `run_ingest_job`
- **不**把失敗顯示成「雲端壞了請重傳」
- 若已寫到 S3／SQS：盡力刪物件、刪訊息，避免下次 Start 重複處理；本機已 INSERT 則雲端重做必須靠 `job_id` 冪等略過
- log 明寫 `fallback=local reason=…`

**禁止：** fallback 時再跑一次 classifier 才決定——已經是 NON_SENSITIVE 了，遠端沒了就本機看圖，不要卡在「非敏感但不上雲」。

使用者觀感：上傳頁、進度面板、待決定，與增量五相同。唯一差在 worker log 與（開機時）較慢或較快的看圖後端。

### 2.2 S3 鍵名（契約）

```text
documents/{job_id}/input.jpg | input.png | input.pdf
documents/{job_id}/result.json
```

`result.json` 只放看圖結果（對齊 `PhotoUnderstanding` 會落庫的欄位）。**不含** embedding 向量。

### 2.3 SQS 佇列（契約）

兩條 Standard Queue，名稱實作時可加環境前綴，語意不可混：

| 佇列 | 誰 Send | 誰 Receive／Delete | body |
|---|---|---|---|
| **jobs** | 本機（送出 input 之後） | 工人（EC2／階段丁腳本） | `{"job_id","s3_key"}`；`s3_key`＝input |
| **results** | 工人（`result.json` 已在 S3 之後） | 本機 | `{"job_id"}` |

本機**不**輪詢 S3 當完成訊號。叫醒之後才 GetObject。Receive 用長輪詢（`WaitTimeSeconds` 最多 20 秒，AWS 上限）；整筆 job 另有逾時，到了仍無訊息→D10。

---

## 3. 範圍

**做：**

- 本機 Privacy Classifier（現有看圖 VLM 的短問題，跟頁首開關；不看檔名）與三分類測試
- 遠端可用性探測＋fallback 到 `run_ingest_job`
- S3 mailbox、兩條 SQS Standard（jobs＋results）；完成訊號＝results ReceiveMessage，再 GetObject
- `cloud_worker`：收件、看圖（Ollama Cloud）、寫 result；先 Mac 腳本再 Docker
- EC2 t4g.small、AL2023、SSM、inbound 全關
- GitHub OIDC、ECR `<sha>`、SSM 部署
- Free plan 操作約束寫進 `LAUNCH.md`／`CLAUDE.md`（實作階段己附近）
- pytest：假 AWS、假 classifier、假遠端開關；**不連真 AWS、不扣點數**

**不做：**

- 用 Gate 覆蓋頁首 AI 開關
- EC2 跑 Postgres／Redis／Celery／本機 GPU 模型
- 把 S3 當備份或相簿
- NAT、ALB、EIP、RDS、Lambda、ECS、Macie
- 常開 EC2（產品負責人選用完 Stop）
- 規格 `.feature` 在產品負責人核准解禁前改「雲端管線」語句（本輪可只靠測試釘行為）

---

## 4. 資料流與冪等

- 影像仍**不進** Redis／SQS／Celery 參數；本機 staging 契約不變。
- 雲端路：位元組只短暫出現在 S3 mailbox 與 EC2 記憶體／暫存。
- 同一 `job_id`：本機 INSERT 成功後，遲到的 `result.json` 或重送的 SQS 訊息必須略過（對齊增量五 `photo_ids`）。
- Fallback 與雲端路**不可兩路都 INSERT**。狀態建議（實作時放 JobStore，不進 `photo` 表）：例如 `route=local|cloud`、`cloud_attempted`。`photo` 表不加 `job_id`、不加處理狀態欄（design5 禁令仍有效）。

---

## 5. API 與端點

本增量**不要求**為雲端管線新增使用者打的 REST 端點。上傳仍是 202。進度仍走 `GET /ingest-jobs`。

可選（實作若需要再加，須同步清點測試）：內部／除錯用的「遠端是否 running」不進 OpenAPI 也可以，用 log 即可。

openapi 仍零 DELETE。

---

## 6. 安全與隱私

| 原則 | 落地 |
|---|---|
| 敏感不出 S3 | D3；測試釘「敏感檔零 PutObject」 |
| 不確定當敏感 | D3 |
| 頁首開關仍可把影像送到 ollama.com | D6；與 S3 管線分開講，不要寫成「敏感資料完全不出雲」 |
| EC2 不收連線 | D11；SSM 取代 SSH |
| Bucket 非公開 | Block Public Access 全開；非敏感 ≠ 可公開 |
| IAM 最小權限 | 本機：指定 prefix 的 s3:Put／Get／Delete；jobs 的 `SendMessage`；results 的 `ReceiveMessage`／`DeleteMessage`；`ec2:DescribeInstances`。EC2 instance role：S3 該 prefix 的 Get（input）／Put（result）；jobs 的 Receive／Delete；results 的 Send；ECR pull、SSM。GitHub OIDC role：ECR push、SSM SendCommand、描述該實例。**trust 的 `sub` 鎖 repo＋`master`** |
| 用完刪 mailbox | D8 |
| 機密不進文件 | `.env` 不入版控；文件只寫變數名 |

---

## 7. AWS 帳號與費用（Free plan）

查證時點 2026-08-31。新帳號（2025-07-15 後）是**點數**不是舊的 12 個月 t2.micro。[Free Tier](https://aws.amazon.com/free/)／[FAQ](https://aws.amazon.com/free/free-tier-faqs/)

| 約束 | 內容 |
|---|---|
| 方案 | **Free plan**：升 Paid 前不扣卡；6 個月或點數用完先到先**關帳**；資料留 90 天 |
| 點數 | 開戶 $100，Explore AWS 活動最多再 $100；12 個月失效 |
| 本專案服務 | EC2、S3、SQS、ECR、IAM、STS、SSM、Budgets 均在 Free plan 可選清單內（單區；不做跨區複製）[服務清單](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html) |
| EC2 | `t4g.small`（ARM）。官方另有 t4g 每月 750 小時試用至 2026-12-31（[EC2 FAQ](https://aws.amazon.com/ec2/faqs/)）；Billing 寫 Free plan 無 short-term trial——開戶後看帳單有無 $0 列。用完 **Stop** |
| 網路 | 公有子網＋自動公有 IPv4（要連 ollama.com）。**禁止 NAT Gateway**。S3 可用免費 Gateway VPC endpoint |
| 管理 | inbound 全關；Session Manager／Run Command |
| 警報 | 開戶先建 Budget（例如實際／預測 $5 寄信） |
| 禁止 | Organizations／Control Tower（會自動升 Paid 且點數作廢） |

**Stop 之後：** 運算費停；自動公有 IP 釋放；EBS 根碟仍按 GB 從**點數**扣（不是扣卡）。下一筆非敏感上傳走 D10 fallback。

---

## 8. 錯誤表

| # | 情況 | 誰處理 | 預期 |
|---|---|---|---|
| 1 | 敏感／不確定 | Gate | 本機入庫；零 S3／jobs／results |
| 2 | 非敏感、EC2 Stop | D10 | 本機 `run_ingest_job`；202 與進度面板不變 |
| 3 | 非敏感、無 AWS 憑證 | D10 | 同上 |
| 4 | PutObject／jobs SendMessage 失敗 | D10 | fallback 本機；不留半套（盡力刪） |
| 5 | 已送雲端、逾時無 results 訊息 | D10 | fallback 本機；冪等避免雙 INSERT |
| 6 | SQS 重送（jobs 或 results）、本機已入庫 | D17 | 工人／本機略過 |
| 7 | VLM 三次失敗（本機或雲端看圖） | 沿用 design5 D10 | 不留 photo 列、清 staging；雲端路還要清 S3 |
| 8 | 格式 415 | HTTP | 不變；不建 job |
| 9 | GitHub OIDC 未鎖 `sub` | CD | 不准合併；trust 必須釘 repo＋branch |
| 10 | 誤開 NAT／EIP／GPU | 操作 | 本文件禁止；驗收掃 compose／文件／Console |

使用者看得到的失敗仍＝進度列。不要 `alert`。

---

## 9. 測試策略

沿用四道 autouse：`reset_tables`、`wire_fake_ai`、`isolated_data_dir`、`wire_memory_job_store`。  
再加：**假 AWS 客戶端**（S3／SQS／EC2 Describe），pytest **不連真 AWS**。

必釘（名稱實作時可調）：

- 敏感 → 假 S3 的 PutObject 呼叫次數為 0，照片仍入收件箱
- 不確定 → 同上
- 非敏感＋假遠端 `running` → 有 PutObject＋jobs SendMessage；假工人 SendMessage results 後本機 GetObject 入庫、staging 空
- 非敏感＋假遠端 `stopped` → PutObject 次數 0，走 `run_ingest_job`，列數 1
- 非敏感＋DescribeInstances 丟錯 → 同 fallback
- 已 INSERT 再送一次同 `job_id` result → 列數仍 1
- SQS 兩條佇列的訊息 body 都不含 PNG／PDF 位元組
- classifier VLM 短問測：假模型說敏感／不敏感有把握／不敏感沒把握／丟例外；**同一張圖換檔名答案不變**（不看檔名）；失敗→UNCERTAIN
- 清點：無 DELETE；無 NAT 字樣進本增量產品碼

前端不新增 Playwright。真 AWS 煙霧：人手 Start→傳一張非敏感→入待決定→Stop→再傳一張（應本機入庫）。

---

## 10. 規格檔

`docs/spec/` 唯讀，除非產品負責人核准解禁。本增量對外上傳契約仍是 202＋分析成功才有照片；**不必**為了 fallback 改 Gherkin（那是內部路由）。若之後要加「敏感不上雲」Example，另核准。

---

## 11. 會動到的檔（實作時才寫；此處是契約）

| 檔 | 階段 | 動作 |
|---|---|---|
| `app/services/privacy_gate.py`（名稱可調） | 甲 | 三分類；VLM 短問題；不看檔名；可測 |
| `app/services/ingest_job.py`／Celery 進入點 | 甲 | 開頭問 gate＋D10 |
| `app/services/cloud_route.py` 等 | 乙／丙 | S3、jobs Send、results Receive、探測 running |
| `scripts/cloud_worker.py` 或 `app/workers/cloud_worker.py` | 丁 | 先本機 |
| Dockerfile／多階段或第二 target | 戊 | worker 映像 `linux/arm64` |
| `.github/workflows/` | 己 | CI 後 CD：OIDC、ECR、SSM |
| `LAUNCH.md`、`CLAUDE.md` 指令區 | 戊／己 | Free plan、Stop、東京區、禁止 NAT |
| `tests/…` | 甲起 | 假 AWS、fallback、敏感零上傳 |
| `docs/plan/unfinish/` | 拍板後 | phase 總覽另寫，本檔不取代計畫 |

**不改：** 詢問 workflow、定案 PATCH、`postgresql@14`、把 Ollama 打進本機 app 映像。

---

## 12. 驗收清單（給產品負責人）

**Demo 1 — 敏感留本機**

- [ ] 上傳內容是證件／敏感文件的檔（檔名隨意）；S3 bucket 無該 `job_id`；待決定有照片

**Demo 2 — 非敏感走雲端再回家**

- [ ] EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉（或 Lifecycle 內會刪）；照片進待決定；詢問能問到

**Demo 2b — 遠端關掉 fallback（本文件新增）**

- [ ] EC2 Stop 後上傳非敏感；**不必改任何設定**；進度與入庫與增量五相同；S3 不出現新物件

**Demo 3 — CD**

- [ ] 改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA → Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）

**費用／安全**

- [ ] Free plan、未升 Paid；Budget 有寄信設定
- [ ] Security group inbound 空；無 NAT、無 EIP
- [ ] pytest 全綠且不碰真 AWS

---

## 13. 風險與已知限制

- **EC2 Stop 時不卸壓。** 這是 D15 換 $0 的代價。要卸壓就先 Start。
- **頁首撥雲端時，敏感檔影像仍可去 ollama.com**（閘門短問與入庫看圖都是）。與 S3 那扇門不是同一扇（D2、D6）。產品負責人 2026-09-01 接受：開關本就是開發加速用。
- **EC2＋Ollama Cloud 不會比「本機＋頁首雲端開關」更快。** 多 S3／SQS  hop。開機價值是卸 Celery／GPU 名額與作品集管線。
- **Free plan 滿 6 個月或點數用完會關帳。** 不是扣卡，是資源消失；90 天內可升 Paid 救回。[FAQ](https://aws.amazon.com/free/free-tier-faqs/)
- **t4g 試用與 Free plan 文件可能不一致。** 開機後看帳單；沒有 $0 列就立刻 Stop，只吃微量點數。
- **Classifier 會漏。** VLM 短問也會把薪資單看成收據。不確定必須當本機；這不是合規 DLP。不看檔名，所以 `IMG_4821.jpg` 的證件有機會被看見——也有機會被看錯。
- **host 與映像套件分岔**（design4 已知）在 ARM worker 映像上同樣存在。

---

## 14. 決策紀錄（對話摘要）

| 題 | 產品負責人 | 記入 |
|---|---|---|
| Result 怎麼回家 | S3 mailbox；工人寫完後 SendMessage **results**；本機 Receive 再 GetObject 入庫；EC2 不開門。**不**輪詢 HeadObject | D8、D9、D11、D13 |
| 為何用 S3 不直接傳 VM | 工人不收連線；SQS 不能塞整檔 | D9、D11 |
| 主目標 | 作品集／學 AWS；順便 EC2 開著時卸本機看圖壓力 | D14 |
| 頁首 AI 開關 | 不管它、也不准閘門去關它；閘門**跟著**走同一顆看圖模型。本機太慢才有 ollama.com；2026-09-01：閘門短問也跟開關，雲端時接受圖先去 ollama.com | D6、D2、D4 |
| 閘門怎麼分類 | 只用 VLM 短問題，不看檔名、無關鍵字表。失敗＝不確定＝本機。完整看圖仍是入庫那一次 | D4 |
| EC2 看圖 | 無 GPU，只打 Ollama Cloud | D12 |
| 帳號 | Free plan，不想扣卡 | D15 |
| 開機 | 部署／demo 完立刻 Stop | D10、D15 |
| 映像 | 能打 `linux/arm64` | D15、D16 |
| 遠端關掉 | 程式 fallback 成原來這台電腦的入庫 | D10 |

---

## 15. 參考來源（撰寫時查過）

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
