# 階段十三：Phase 92 拆兩段（先 CPU、再 GPU）——只改文件

- 日期：2026-09-03
- 產品負責人拍板：**不等 GPU 配額**，Phase 92 拆成 92-A（CPU 機、現在就做）與 92-B（GPU 機、配額核准後）
- 裁決編號：計畫總覽 **§10.2 追認項 U**、工作區 ledger **R28**
- 本階段**零程式碼變更、零測試變更**；`docs/spec/`／`compose*.yaml`／`db/`／`app/`／`deploy/ec2/user-data.sh`／
  `deploy/ec2/personaldocai-worker.service`／`deploy/aws/` 一律未動

---

## 1. 為什麼要拆（一句話）

GPU 配額（`L-DB2E81BA`）還在 AWS 人工審核（狀態 `CASE_OPENED`、帳號上限仍是 **0**），
可能等數天、也可能被拒。但 Phase 92 真正要驗的那一整條 AWS 流程**一顆 GPU 都用不到**：

```text
  92-A（CPU 機就驗得完的）                          92-B（只有 GPU 才驗得到的）
  ─────────────────────────                          ─────────────────────────
  instance profile 的臨時憑證進不進得了容器          nvidia-smi 看得到 Tesla T4
  SG 只出不進還拉不拉得到 ECR                        ollama ps 的 PROCESSOR 是 GPU
  SSM 進不進得去（不開 SSH）                         工人 log 的 backend=local
  systemd 開機會不會自己把工人拉起來                 看一張圖從「約 2 秒」變成「幾秒」
  Ec2Probe 對真實例的 running／stopped 判得準不準
  amd64 映像第一次在真的 x86 上跑（會不會 exec format error）
  Demo 2（走雲端）／Demo 2b（關掉自動 fallback）
```

左邊那一整欄就是 ★G3 要看的東西，所以 **★G3 移到 92-A 之後**，Phase 93／94／95 不必等配額。

---

## 2. 兩段的差別（只有四個地方）

| | **92-A（現在做）** | **92-B（配額核准後）** |
|---|---|---|
| 機型 | `t3.xlarge`（4 vCPU／16 GiB、x86_64、**無 GPU**） | `g4dn.xlarge`（同規格 ＋ NVIDIA T4） |
| AMI | 一般 AL2023 x86_64（SSM 參數 `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`） | Deep Learning Base OSS NVIDIA Driver GPU AMI |
| 根碟 | **30 GB gp3** | **80 GB gp3**（AMI 快照就 75 GB） |
| `worker.env` 的 `WORKER_VLM_BACKEND` | **`cloud`**（轉送 ollama.com） | **`local`**（那台自己的 Ollama） |
| 前置配額 | Standard `L-1216C47A`（本帳號實查 **8**，不必申請） | G and VT `L-DB2E81BA`（**0**、審核中） |
| 每小時 | **$0.2176** | 約 **$0.71** |
| 收工 | **Stop**（30 GB ≈ $2.9／月，在 $5 Budget 內，留給 Phase 94 的 Demo 3） | **Terminate**（80 GB ≈ $7.7／月，超過 Budget） |

**其餘全部共用、一個字都不動：** `deploy/ec2/` 三份檔、Phase 91 的 SG／IAM role ＋ instance profile／
S3 Gateway endpoint／ECR、S3 bucket 與兩條 SQS、Mac 端所有程式碼、隱私閘門、S3／SQS 順序鐵律、
工人六條處理規則、`result.json` 形狀、Demo 2／2b 的意義。
**兩種機都由 user-data 裝地端 Ollama**（92-A 上它只是閒著應門，讓 unit 的 `ExecStartPre` 等 `11434` 那一關過）
——看圖打哪一顆**只看 `WORKER_VLM_BACKEND`，機型不決定後端**。

---

## 3. 實作邏輯／步驟（照這個順序做）

### 3.1 92-A（現在就能做）

1. `pytest -q` 記下開工顆數（實測基線 **689**）。
2. `brew install --cask session-manager-plugin`（每台 Mac 一次）。
3. 查一般 AL2023 x86_64 的 AMI id（phase-92 §4.2 變體 A）。
4. `run-instances`：`t3.xlarge` ＋ 30 GB gp3 ＋ SG ＋ instance profile ＋ 公有 IP ＋
   IMDSv2 hop limit 2 ＋ 同一份 `deploy/ec2/user-data.sh`（phase-92 §4.3）。
5. 等 `running` → 等 SSM `Online` → 等 user-data 印「user-data 完成…」（第一次要 5〜10 分鐘，
   它會裝 Docker、裝好 systemd 服務、裝 Ollama 並拉 7 GB 模型）。
6. SSM 進去，`unset HISTFILE`，建 `/opt/personaldocai/worker.env`（`chmod 600`）——
   **`WORKER_VLM_BACKEND=cloud`，並手抄 `OLLAMA_API_KEY` 與 `OLLAMA_CLOUD_VLM_MODEL`**。
7. `systemctl start personaldocai-worker`，`docker logs cloud-worker | head -1` 要看到
   `version=<sha> … vlm=cloud model=<雲端模型名>`。
8. Mac `.env` 填 `EC2_WORKER_INSTANCE_ID`、`CLOUD_ROUTE=ec2`、`CLOUD_RESULT_TIMEOUT_SECONDS=300`，
   `restart worker`（**不重啟不會生效，而且完全不報錯**——`lru_cache`）。
9. **Demo 2**：上傳**之前**先把頁首 AI 開關撥「雲端」（閘門跟它走，本機要 1〜2 分鐘、雲端 0.6 秒）→
   上傳一張內容是收據的圖 → 三邊 log。
10. **Demo 2b**：Stop → 等 60 秒（探測快取）→ 什麼都不改再傳一張 → 要看到
    `fallback=local reason=remote_unavailable`、S3 零新物件。
11. 順手驗 Demo 1（合成證件圖 → `route=local verdict=SENSITIVE`）。
12. **收工 Stop**、頁首開關撥回本機。
13. 改三份文件（`LAUNCH.md` 新章節 §13、`CLAUDE.md` 指令區、`README.md` 兩句）——
    **寫成 CPU／GPU 兩段式的最終版本，92-B 做完不必再改**。
14. 收工檢查（顆數不變、三死埠相同、機密沒外洩、unit 兩處 `diff` 相同）→ 交出 **★G3**。

### 3.2 92-A 選配：同一台切 `local` 硬跑 CPU 推論（可做可不做）

⛔ **要做的話這三步一步都不能省：**

1. **Mac `.env` 的 `CLOUD_RESULT_TIMEOUT_SECONDS` 300 → 900**，`restart worker`。
2. 機器上把 `worker.env` 改成 `local` 那一組（`WORKER_VLM_BACKEND=local`、
   `OLLAMA_BASE_URL=http://127.0.0.1:11434`、`VLM_MODEL=gemma4:e2b`——**不要 `-mlx`**），
   `sudo systemctl restart personaldocai-worker`，啟動行要變成 `vlm=local model=gemma4:e2b`。
   **只傳單圖，不要多頁 PDF**（工人沒有 SQS 心跳，超過 900 秒訊息會重投）。
3. **做完改回去**：機器上改回 `cloud` 那一組並 restart；Mac `.env` 改回 **300** 並 restart。

⚠️ **為什麼一定要調 900：** CPU 看一張圖大概率超過 5 分鐘 → 本機先
`fallback=local reason=result_timeout`、自己看一次圖（結果是對的），
工人稍後放好的 `result.json` **沒有人會來拿**，變成孤兒物件。
900 是對齊 jobs 佇列的 Visibility Timeout。**這是測試期的暫時覆蓋**，
`60`／`300` 對日常仍是總覽 §2.4.2 的契約值。

### 3.3 92-B（G and VT 配額核准 ≥4 之後，任何時間）

1. 確認 `get-service-quota` 的 `Value` ＝ 4。
2. **先 Terminate 92-A 那台**（同時只准有一台，兩台會搶同一條 SQS 佇列）。
3. 查 GPU AMI id → `run-instances`：只換 `--instance-type`、`--image-id`、`VolumeSize`（80），
   其餘旗標**逐字相同**。
4. `worker.env` 整份再貼一次，`WORKER_VLM_BACKEND=local`（`OLLAMA_API_KEY` 可留空）。
5. 多驗兩關：`nvidia-smi -L` 看得到 Tesla T4、`ollama ps` 的 PROCESSOR 是 `100% GPU`。
6. Mac `.env` 換新的 instance id、`restart worker`，重跑一次 **Demo 2**
   （Demo 2b 不必重做）——證據只多看一行：工人 log 從 `backend=cloud` 變 `backend=local`。
7. **收工 Terminate**，`.env` 的 id 清空、`CLOUD_ROUTE=off`、`restart worker`。

**92-B 不改任何程式、不改 `deploy/ec2/`、不改三份文件、不設新閘門。**

---

## 4. 三段各自要手抄／手填什麼（phase-92 §4.5 有同一張表）

```text
  兩個檔案，不要搞混：
    /opt/personaldocai/worker.env   ← 在 EC2 上（SSM 進去手打，chmod 600）
    <專案根目錄>/.env               ← 在這台 Mac 上
  兩邊沒有任何同步機制，全部靠人。
```

| | ① 92-A（CPU、`cloud`） | ② 92-A 選配（同一台改 `local`） | ③ 92-B（GPU、`local`） |
|---|---|---|---|
| 要手抄的**機密** | `OLLAMA_API_KEY`（Mac `.env` → EC2 `worker.env`） | 沒有 | 沒有 |
| EC2 `worker.env` | 整份第一次建（`WORKER_VLM_BACKEND=cloud` ＋ `OLLAMA_API_KEY` ＋ `OLLAMA_CLOUD_VLM_MODEL`） | 同一份改五行（`local`／`OLLAMA_BASE_URL`／`VLM_MODEL`；`OLLAMA_API_KEY`、`OLLAMA_CLOUD_VLM_MODEL` 可留空）。⛔ `AWS_REGION`／`ECR_*`／`S3_BUCKET`／`SQS_*` 一行都不要動 | 新機器整份再貼一次（`local` ＋ `OLLAMA_BASE_URL`／`VLM_MODEL`；AWS／ECR／S3／SQS 照抄） |
| Mac `.env` 要手填的**非機密** | instance id → `EC2_WORKER_INSTANCE_ID`；`CLOUD_ROUTE=ec2`；`CLOUD_RESULT_TIMEOUT_SECONDS=300` | id 與 `CLOUD_ROUTE` 都不動；**`CLOUD_RESULT_TIMEOUT_SECONDS` 暫調 900、做完改回 300** | **新的** instance id；`CLOUD_ROUTE` 不動 |
| 要 restart 什麼 | Mac `restart worker` | Mac `restart worker` ×2（調 900 一次、改回一次）＋ 機器上 `systemctl restart` | Mac `restart worker` |
| 啟動行要看到 | `vlm=cloud model=<雲端模型名>` | `vlm=local model=gemma4:e2b` | `vlm=local model=gemma4:e2b` |

⛔ **機密只寫變數名，不寫值**（總覽 §7 鐵律 10）。

---

## 5. 本次改了哪些檔（全部只改文件）

| 檔案 | 改了什麼 |
|---|---|
| `docs/plan/unfinish/phase-92-EC2真機與文件.md` | **主要工作**。全檔改成 92-A／92-B 兩段式：檔頭改判紀錄框精簡重寫成一張對照表；六件不要做（③金額分兩段、④加「測試期暫時覆蓋」例外、⑤只適用 92-B）；開工前檢查（92-A 只要 Standard 配額）；一句話目標兩段；名詞表新增 `t3.xlarge`／一般 AL2023 SSM 參數／30 GB gp3 並改寫 `WORKER_VLM_BACKEND`、EBS 兩列；§1 新增追認項 U 一列；§2 前置分兩張表；§3 範圍分兩份；§4.2 查 AMI 兩個變體；§4.3 寫成「一份指令、三個變數不同」；§4.4／§4.5 分段（92-A `cloud`、92-B `local`＋GPU 兩關）；**§4.5 新增「三段各自要手抄／手填什麼」對照表**與「選配：切 `local` 試 CPU 推論」小節（含 900／300 暫調步驟）；§4.7 Demo 2 加「上傳前撥雲端」與兩段各自的預期 log；§4.9 收工三種動作；§4.10 LAUNCH §13 改成誠實的兩段描述；§5 ASCII 圖標明兩段；§6 驗收清單拆 6.1／6.2；§7 陷阱新增 19〜23（CPU 機 OOM、沒調逾時的孤兒 `result.json`、CPU 機用 GPU AMI 白付碟、配額不要重送、unit 兩處要同改）並把 15／16 標成 92-B；§8 完成後狀態分兩段；★G3 移到 92-A 之後。1949 → 2515 行 |
| `docs/plan/unfinish/phase-00-增量六總覽.md` | §10.2 **新增追認項 U**（本次七條裁決濃縮，指向 ledger R28）；T 那列的落點改成 92-B；§1.3 改判警語補一句；Phase 列表的 92 那列、★G3 那列（依賴改 92-A）、93 那列；§2.8 的 EC2 instance 列整列重寫成兩段；§5.5 的預期輸出、§6 勾選區、§9 的 Phase 92 標題 |
| `docs/plan/unfinish/phase-93-GitHub_OIDC與部署角色.md` | 檔頭校準框改成兩段式＋「★G3 在 92-A 之後，不必等 GPU 配額」；EC2 前置從「一定已 Terminate」改成「通常是 92-A 留下的 `t3.xlarge` stopped」；驗收表 EC2 狀態欄；「有輸出＝有人忘了關 g4dn」改成泛稱 EC2 |
| `docs/plan/unfinish/phase-94-CD工作流程.md` | 檔頭校準框（兩段、兩者皆 x86_64、**Demo 3 不必等 GPU**）；Demo 3 前置改成「Start 92-A 留下的 `t3.xlarge` 即可」；步驟 7 從 Terminate 改成 **Stop**；費用列補 `t3.xlarge` 數字；陷阱 10 改寫；ASCII 圖標題；D15 對照列與幾處「真機是 g4dn」的散文。**多架構 CD 邏輯（`deploy.yml` 與那顆測試）一字未動** |
| `docs/plan/unfinish/phase-95-增量六錯誤收尾與驗收包.md` | 檔頭校準框；前置「EC2 沒有 running」改成 stopped／terminated 都算過；§4.6 ② 的預期；C9 後的提醒；D6、**E1**、**E5**；已知限制段三條（不卸壓、Paid 扣卡、GPU 那句）；「再開 g4dn 就是在扣卡」補 `t3.xlarge` 數字 |
| `docs/design/design6.md` | D12 那列的既有改判註記後面**加一句**「實作順序：先 CPU `t3.xlarge` 驗流程（92-A），配額核准後再 GPU（92-B）；見總覽 §10.2 U」。其他不動 |
| `CLAUDE.md` | 第 17 行那段結尾的「phase-92 已改成 GPU 版但尚未實作；兩件要產品負責人先決定…」整段換成兩段式現況（含 Standard 配額 8、30 GB ≈ $2.9／月、★G3 移到 92-A 後、配額 `CASE_OPENED` 不要重送、選配要暫調 900）；指令區 `WORKER_VLM_BACKEND` 註解補「92-A 的 CPU EC2 也填 cloud」。**其他段落未動** |
| `LAUNCH.md` | §12 裡「`local` … so this value really exists for the GPU instance」那段補上誠實現況：目前**沒有** EC2 worker，之後會先是 CPU box（`t3.xlarge`、`cloud`），GPU box 要等配額。**§13 尚未存在，本次不新增**（那是 phase-92 §4.10 執行時才寫） |
| `deploy/ec2/worker.env.example` | **只改註解**：`cloud` 段補「92-A 的 CPU EC2 也填這個」、`local` 段的「GPU EC2 填這個」改「92-B 的 GPU EC2 填這個」。變數名與空值一個都沒動 |
| `.superpowers/sdd/phase0902-2/progress.md` | 追加 **Ruling R28**（清單一行 ＋ 摘要表一列，接在 R27 之後。⚠️ 不是 R24——R24〜R27 早已存在） |
| `docs/plan/todo/2026-09-03-階段十三-phase92拆兩段CPU先行-TODO.md` | 本檔 |

**沒有動的：** `docs/spec/`、`compose*.yaml`、`db/`、`app/` 產品碼、`tests/`、
`deploy/ec2/user-data.sh`、`deploy/ec2/personaldocai-worker.service`、`deploy/aws/*.json`、`README.md`。

---

## 6. 下一步

1. 產品負責人 review 本次文件改動。
2. 開工做 **92-A**（照 phase-92 §4.1〜§4.11）。
3. 交出 **★G3** → Phase 93 → 94 → 95。
4. G and VT 配額核准的那一天，再回頭做 **92-B**（獨立步驟，不擋任何人）。

⚠️ **配額若被拒**：92-B 不做，其餘一切照舊——系統永久停在 92-A 那個組合
（CPU 機 ＋ `WORKER_VLM_BACKEND=cloud`），功能完全合格。
`LAUNCH.md` §13 那張「CPU box / GPU box」對照表本來就誠實寫著 GPU 那一欄還在等配額，**不必改字**。
