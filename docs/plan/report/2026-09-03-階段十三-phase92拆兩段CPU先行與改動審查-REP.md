# 2026-09-03 階段十三：Phase 92 拆兩段（先 CPU、再 GPU）與未 commit 改動審查 — REP

> 對應 TODO：`docs/plan/todo/2026-09-03-階段十三-phase92拆兩段CPU先行-TODO.md`
> 裁決：總覽 §10.2 追認項 **U**、`.superpowers/sdd/phase0902-2/progress.md` **R28**
> 本階段**不開任何 EC2**、不動 AWS 資源；只改文件、`deploy/ec2/` 兩檔的註解與一行設定、`config.py` 一行、測試 +1。

## 1. 背景：為什麼要拆

產品負責人今天決定：GPU 配額（`L-DB2E81BA`）還在人工審核（`CASE_OPENED`、上限仍 0），**不等它**。
Phase 92 真正要驗的那條 AWS 流程（instance profile 憑證、SG 只出不進、從 EC2 拉 ECR、SSM 進機器、
systemd 開機自起、`Ec2Probe` 對真實例、amd64 映像第一次在真 x86 跑）一顆 GPU 都用不到，
所以先用 CPU 機把流程與 Demo 2／2b 驗掉，GPU 留到配額下來再做。

## 2. 實作邏輯

```text
  Phase 92（原本一段：g4dn + GPU AMI + 80 GB + local）
        │
        ├── 92-A（現在）  t3.xlarge ＋ 一般 AL2023 x86_64 ＋ 30 GB gp3 ＋ worker.env=cloud
        │                 驗：AWS 流程、Demo 2／2b、amd64 映像真跑；用完 Stop
        │                 選配：同一台改 local 試 CPU 推論（Mac 逾時要暫調 900）
        │                 ★G3 改到這裡之後（93〜95 不依賴 GPU）
        │
        └── 92-B（配額 ≥4 後）Terminate CPU 機 → g4dn.xlarge ＋ DL GPU AMI ＋ 80 GB ＋ local
                          只動三處：Mac .env 的 instance id＋restart、新機器 worker.env
                          新兩關：nvidia-smi、ollama ps 是 GPU；測完 Terminate

  兩段共用、一字不動：deploy/ec2 三檔、SG／IAM role／S3 endpoint／ECR／S3／SQS、Mac 端程式碼
  看圖打哪一顆只看 WORKER_VLM_BACKEND，機型不決定後端
```

先用 admin CLI／pricing API／`ollama list` 把數字核對過（不憑記憶）：

| 事實 | 值 |
|---|---|
| Standard 配額 `L-1216C47A` | 8 vCPU（新帳號預設常 5，本帳號實查 8） |
| GPU 配額 `L-DB2E81BA` | 0；申請 DesiredValue 4，`CASE_OPENED`（不是被拒、不要重送） |
| EC2 實例 | 0 台 |
| 東京 On-Demand | `t3.xlarge` $0.2176／hr；`t3.large` $0.1088；`t3.small` $0.0272 |
| `gemma4:e2b` | 7.2 GB → `local` 模式只有 16 GB 的 `t3.xlarge` 載得動；`cloud` 模式任何機型都行 |
| CPU 機根碟 | 30 GB gp3，stopped ≈ $2.9／月（在 $5 Budget 內） |

## 3. 步驟

1. 寫共同 brief（scratchpad `brief-cpu-first.md`）：裁決、核對過的數字、文件慣例、禁改區。
2. 開兩個 Opus subagent 並行：**writer** 改文件；**reviewer** 唯讀審查所有未 commit 的改動（含跑一次 ruff＋pytest）。
3. reviewer 回報後，controller 套用三條明確的小修正（§5），跑驗證。
4. 產品負責人追加「三段各自手抄／手填什麼」對照表 → 轉給 writer 補進 phase-92 §4.5。
5. 發現 ledger 裡 R24〜R27 已存在 → 裁決編號改 **R28**，通知 writer 並同步記憶檔與 brief。
6. writer 回報後做最終檢查：殘留 R24、GPU-only 敘述、機密掃描、`worker.env.example` 只有變數名、unit 與 user-data 內嵌段逐字相同、ruff、全量 pytest。

## 4. 改了哪些檔

### 文件（writer）

| 檔案 | 改了什麼 |
|---|---|
| `docs/plan/unfinish/phase-92-EC2真機與文件.md` | 全檔改成 92-A／92-B 兩段式（1949 → 2515 行）。檔頭改判框精簡成一段＋對照表；六件不要做／開工前檢查／一句話目標分兩段；名詞表加 `t3.xlarge`、一般 AL2023 SSM 參數、30 GB gp3；§4.2 兩個 AMI 變體；§4.3「一份指令、三個變數不同」；**§4.5 新增三段手抄／手填對照表**＋選配 CPU 推論小節（含 Mac 逾時 900／300）；§4.7 加「上傳前撥雲端」與兩段預期 log；§4.9 收工三種動作；§4.10 LAUNCH §13 兩段誠實版；§6 拆 6.1／6.2；§7 陷阱新增 19〜23；★G3 移到 92-A 之後；§4.11 加 unit／user-data `diff` 檢查指令 |
| `docs/plan/unfinish/phase-00-增量六總覽.md` | §10.2 新增追認項 **U**；T 列落點改 92-B；§1.3、Phase 列表 92／93 列、★G3 列、§2.8 EC2 列、§5.5、§6、§9 同步 |
| `phase-93`／`phase-94`／`phase-95` | 檔頭校準框改兩段式；「真機一定是 g4dn」的敘述改成 92-A `t3.xlarge`／92-B `g4dn.xlarge`（皆 x86_64，多架構 CD 不變）；94 的 Demo 3 改「Start 92-A 留下的 `t3.xlarge`」、步驟 7 改 Stop、費用列補 t3；95 的 E1／E5／已知限制同步。**94 的 `deploy.yml` 與多架構測試碼區一字未動** |
| `docs/design/design6.md` | D12 列既有註記後加一句實作順序（先 CPU 92-A、再 GPU 92-B） |
| `CLAUDE.md` | 概述段 2026-09-03 改判那一段結尾換成兩段式現況；指令區 `WORKER_VLM_BACKEND` 註解補「92-A 的 CPU EC2 也填 cloud」；測試顆數 690 |
| `LAUNCH.md` | §12 提到 GPU instance 那句改成誠實現況（目前無 EC2；先 CPU box，GPU box 等配額） |
| `deploy/ec2/worker.env.example` | 只改註解兩處（cloud 段補 92-A、local 段標 92-B）；變數名與空值未動 |
| `.superpowers/sdd/phase0902-2/progress.md` | 追加 R28（清單一行＋摘要表一列） |
| `docs/plan/todo/2026-09-03-階段十三-phase92拆兩段CPU先行-TODO.md` | 新增 |

### 程式與部署檔（controller，依 reviewer 建議）

| 檔案 | 改了什麼 | 為什麼 |
|---|---|---|
| `deploy/ec2/personaldocai-worker.service`＋`user-data.sh` 內嵌段 | 加 `TimeoutStartSec=600`（含註解） | systemd 預設啟動逾時 90 秒，且三條 `ExecStartPre`（ECR 登入、等 Ollama 最多 120 秒、docker pull）串起來算同一個逾時——原本那個「等 120 秒」永遠等不滿就會被 systemd 殺掉 |
| `deploy/ec2/user-data.sh` | AMI 註解改成 92-A 一般 AL2023／92-B GPU AMI；`VLM_MODEL` 註解說明只在 local 用到；Ollama 段標題對齊兩段；`ollama pull` 前加「根碟剩 <12 GB 就跳過並大聲留 log」 | 原註解命令式叫人選 GPU AMI，照做會在 CPU 機上白付 75 GB；一般 AL2023 預設根碟 8 GiB，7.2 GB 模型拉到一半塞滿磁碟會讓之後的 docker pull 用看不懂的方式失敗 |
| `app/core/config.py` | `AWS_REGION = os.getenv("AWS_REGION") or "ap-northeast-1"` | `worker.env.example` 出貨就是 `AWS_REGION=`（只寫變數名），`getenv` 的第二參數在 key 存在、值為空時不生效 → region=""；與 `WORKER_VLM_BACKEND` 同一招 |
| `tests/unit/test_cloud_worker_unit.py` | +1 `test_AWS_REGION留空等於東京`（`importlib.reload` 驗那一行本身） | 釘住上面那個 `or` |

## 5. 審查結果（Opus reviewer，唯讀）

- **Must fix：零。** 六規則、順序鐵律、冪等、SIGTERM、`build_worker_vlm()` 三分支、`Ec2Probe` 六種行為逐條對過。
- **已套用的 Should fix**：`TimeoutStartSec`、user-data AMI 註解、根碟保護、`AWS_REGION` 空值（見 §4）。
- **未套用、留給產品負責人決定**：
  1. **乾淨版 unit**：等 Ollama 的 `ExecStartPre` 改成只在 `WORKER_VLM_BACKEND=local` 生效。你先前決定不做；reviewer 補了一個新理由——user-data 裡 `curl | sh` 裝 Ollama 排在最後、`set -e` 會中止腳本，一旦它失敗，`cloud` 模式的工人其實不需要 Ollama 卻會每 10 秒失敗重試、永遠起不來。一行改動，兩檔同改。
  2. **多頁 PDF 可能超過 SQS jobs 佇列 900 秒可見度**：工人沒有 `ChangeMessageVisibility` 心跳、`render_pages` 沒有頁數上限。不會壞資料（單執行緒＋規則①冪等），最多多送一則 results。92-A 煙霧只用單圖與 1〜2 頁 PDF 即可。
  3. Nit：`read_context` 不驗元素型別（壞 context.json 會變毒訊息）；`ast` 掃碼可被 `importlib.import_module` 繞過且只掃 `cloud_worker.py` 一支；`s3:ListBucket` 可再收窄到 `documents/*`；容器以 root 跑（與既有模式一致）。
- **機密掃描**：44 個改動檔零命中（唯一的 `i-0abcdef…` 是測試合成值）。
- **中文識別字**：新 hunk 零違規。
- **沒有任何測試守「unit 與 user-data 內嵌段逐字相同」**，目前只靠人工 `diff`（已寫進 phase-92 §4.11 與陷阱 23）。
- **92-A 判斷**：`t3.xlarge`＋一般 AL2023＋`cloud` 原樣部署**會成功**；「一定會壞」欄空。要實機驗的三件：首次 `systemctl start` 是否逼近逾時（已用 600 秒收掉）、amd64 映像第一次真跑（看啟動行 `vlm=cloud`）、`/usr/bin/aws` 路徑。已確認不是問題的：Ollama `install.sh` 在無 GPU／無 `lspci` 機器上不會卡也不裝驅動、AL2023 repo 走 S3 不被 SG 擋、SG 只開 443 不影響 DNS／NTP／IMDS、`--network host` 讓 IMDS hop limit 不成問題、`cloud` 模式容器完全不碰 11434。

## 6. 遇到的問題與解法

| 問題 | 解法 |
|---|---|
| brief 與 writer prompt 寫「裁決 R24」，但 ledger 的 R24〜R27 在 0903 GPU 改判時已用掉 | 改用 **R28**；SendMessage 通知 writer（它開工時已自行發現）；記憶檔與 brief 同步改；最終 grep 確認無殘留 R24 |
| 原計畫「不改 deploy/ec2」，但 reviewer 抓到 unit 的 120 秒等待在 systemd 預設 90 秒下永遠等不滿 | 判定為真缺陷、一行改動，controller 直接套用，兩檔同改後 `diff` 證明逐字相同；writer 收到通知後把 phase-92 相關敘述（600 秒、根碟 log）對齊 |
| phase-92 舊版引用的 user-data 完成訊息字串與實檔不符 | writer 順手改成實檔逐字（既有錯誤） |

## 7. 測試方式與結果

```text
diff <(awk "/<<'UNIT'/{f=1;next}/^UNIT$/{f=0}f" deploy/ec2/user-data.sh) deploy/ec2/personaldocai-worker.service
  → IDENTICAL
bash -n deploy/ec2/user-data.sh                                → OK
ruff format --check app tests scripts && ruff check app tests scripts
  → 114 files already formatted / All checks passed!
pytest -q                                                        → 690 passed, 0 skipped（689 + 1）
機密掃描（AKIA/ASIA、i-<17hex>、帳號 ARN、bucket 後六碼、ami-）  → 零命中
grep -E "^[A-Z_]+=" deploy/ec2/worker.env.example | grep -v "=$"  → 空（範本仍只有變數名）
grep R24（本次裁決誤植）                                          → 空
```

## 8. writer 發現但未動的跨檔事項

- `phase-94` 的 `deploy.yml` YAML 註解與多架構測試 docstring 仍寫「真機是 g4dn.xlarge」——依「多架構 CD 邏輯一字不動」保留；要對齊需另行指示。
- `phase-93`／`phase-95` 的顆數基線（662／672）與實測 690 有落差——既有的「計畫值 vs 實測值」雙寫法，開工當天以實際輸出為準。

## 9. 下一步

1. 產品負責人 review 這批改動後 **commit**（87〜91 的程式、deploy、文件全在工作樹裡；repo 是 PUBLIC，履歷附連結前要先進去）。
2. 照 phase-92 **92-A** 段開 `t3.xlarge`（用 admin profile；`.env` 那把只有 `DescribeInstances`）。
3. 決定要不要做乾淨版 unit（§5 未套用第 1 項）。
