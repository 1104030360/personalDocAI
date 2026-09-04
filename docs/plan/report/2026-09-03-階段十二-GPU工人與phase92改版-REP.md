# 2026-09-03 階段十二：工人改成可在 GPU EC2 跑本機 Ollama（design6 D12 作廢）＋ phase-92 計畫改版 — REP

> 產品負責人 2026-09-03 對話指示：「想讓模型跑在 GPU 機上（EC2 自己裝 Ollama）去改動程式碼，相關文件也要改；phase-92 先更新、先不要實作」；隨後拍板「留著開關」。ledger：`.superpowers/sdd/phase0902-2/progress.md`（裁決 R23〜R27）。
> 對應 TODO：`docs/plan/todo/2026-09-03-階段十二-GPU工人與phase92改版-TODO.md`。

## 1. 做了什麼（一句話）

雲端工人的看圖後端從「寫死 Ollama Cloud」改成**開關** `WORKER_VLM_BACKEND`（`cloud` 預設＝ollama.com、`local`＝工人所在機器的 Ollama），部署檔改成「host 跑 Ollama、容器 `--network host`」，phase-92 計畫改成 GPU 版（**尚未實作**），ECR 的 `latest` 改推多架構映像；隱私閘門、S3／SQS 契約、工人六條規則一個字都沒動。

## 2. 實作邏輯

- **為什麼是開關不是改死**：兩條路都有測試守著，`worker.env` 一個變數就能切回純雲端推論（GPU 配額被拒、或 design7 改走 Lambda 時零程式碼）。預設維持 `cloud`：設錯時 `cloud` 缺 key 會**大聲**退出，`local` 缺 Ollama 只會安靜地三次看不懂——預設要選會大聲壞的那個。
- **啟動時把四個看圖設定都檢查掉**：`--env-file` 的「key 在、值空」會蓋掉 config 的預設值（`os.getenv(name, default)` 只在 key 不存在時給預設），所以 `cloud` 要 `OLLAMA_API_KEY`＋`OLLAMA_CLOUD_VLM_MODEL`、`local` 要 `OLLAMA_BASE_URL`＋`VLM_MODEL`，缺一個就 `logger.error`＋`SystemExit(1)`；`WORKER_VLM_BACKEND` 留空視同預設（`os.getenv(...) or "cloud"`），打錯字當場炸。
- **EC2 上怎麼接**：Ollama 用官方腳本裝在 host（`ollama.service`、只聽 127.0.0.1，不改成 0.0.0.0），工人容器 `docker run --network host` 直接打 127.0.0.1:11434；unit 加 `After=/Wants=ollama.service` 與「等 `/api/tags` 活著最多 120 秒」的 `ExecStartPre`（`{1..60}`，零 `$`／`%` 免得 systemd 展開）；user-data **先**裝 unit＋enable、**再**裝 Ollama＋`ollama pull gemma4:e2b`（非致命：拉不到就留 log、第一次看圖時 Ollama 會現抓）——這樣模型下載失敗也不會讓機器沒有 unit。
- **AMI**：Deep Learning Base OSS NVIDIA Driver GPU AMI（AL2023）——驅動、Docker 內建，一般 AL2023 沒驅動、Ollama 會退回 CPU。

## 3. 步驟

1. 實查（唯讀 AWS）：東京 GPU 機型與價格、GPU AMI 的 SSM 參數與根碟大小、G and VT 配額、ECR 現況。
2. 裁決 R23〜R25 入 ledger；總覽 §2.4.1／§2.4.2／§2.8／§3.2 D12／§10.2 T、design6.md D12 兩列註記、phase-91／94 各加一行提醒。
3. Task 6（Opus 實作者，TDD）：程式＋6 顆測試、三個部署檔、LAUNCH §12、CLAUDE 工人段 → review（Needs fixes：3 Important＋3 Minor）→ fix round 1（+3 顆）re-review 6/6 ADDRESSED → round 2（+1 顆）re-review ADDRESSED。
4. Task 7（Opus 校準者，只改文件）：phase-92 改 GPU 版 81 處。
5. controller：Mac 上 `WORKER_VLM_BACKEND=local` 完整回合；多架構映像 build＋push；最終驗證。

## 4. 測試方式與結果

| 檢查 | 結果 |
|---|---|
| 單元（`test_cloud_worker_unit.py` +10：後端分流、留空＝cloud、打錯字炸、啟動行 `vlm=… model=…`（distinctive 值）、`main()` 四個缺設定各一顆＋無效後端一顆） | 30 passed（該檔） |
| 全量 `pytest -q` | **689 passed／0 skipped**（679 → 685 → 688 → 689） |
| 三死埠 | 689 |
| ruff／tokenize／design3 子字串／boto3 位置 | 全過（boto3 只在 `aws_mailbox.py`；工人 import 不變） |
| 部署檔 | unit 與 user-data 內嵌段 diff 空；`bash -n` OK；env 範本零值；deploy/ 零 12 位數字 |
| 機密掃描（追蹤＋未追蹤） | 帳號 ID／bucket 後綴／佇列 URL／真 SG・VPCE・VPC・subnet ID 零命中 |
| Mac `local` 回合（真 S3／SQS；工人打 Mac 自己的 Ollama） | 工人 `vlm=local model=gemma4:e2b` → `AI 結束 kind=vlm backend=local elapsed_s=90.2` → `result.json 已放好` → 本機 `route=cloud` → `雲端結果已入庫：photo_id=73`；S3 空、佇列 0／0；SIGTERM 進來時做完手上那則才退 |
| 多架構映像 | `latest`＝linux/amd64＋linux/arm64（buildx，amd64 走 QEMU，127 秒）、`bb3921a-dirty`；amd64 實跑印出新碼的錯誤訊息、arm64 正常啟動 |
| 零改動區 | `docs/spec`／compose／Dockerfile／db／static／api／repositories／celery_app／gated_ingest／ingest_job／aws_mailbox／cloud_ingest／fakes／conftest／requirements |
| 收工狀態 | `.env` off／300、開關 local、四服務 Up、staging 空、零殘留行程 |

## 5. 遇到的問題與怎麼解決

- **Mac 煙霧第一輪失敗是我自己的 zsh 失誤**：`$DC restart worker` 在 zsh 沒有 word-split，容器逾時仍是 60 秒，而 Mac 本機看圖要 90〜117 秒 → Mac 端先 fallback、工人稍後放好的 `result.json` 成孤兒（S3 一個物件、results 一則訊息，都清掉了）。改用 bash 腳本、逾時 300 重跑就通。那一輪意外證明了「SIGTERM 進來時看圖跑到一半，會做完（116.9 秒）才退」。
- **review 抓到三個只在真 EC2 上咬人的 Important**（空值 `WORKER_VLM_BACKEND=` 變死循環、`local` 不檢查 `VLM_MODEL`、user-data 在 `set -e` 下把 unit 排在 7 GB 下載之後）→ fix round 1；re-review 又指出 `cloud` 路同款陷阱（`OLLAMA_CLOUD_VLM_MODEL=` 空值）→ round 2 一行補上。
- **兩個硬事實寫進 phase-92 等你決定**：帳號的 G and VT 配額是 **0**（`aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-DB2E81BA --desired-value 4`；核准要數小時到數天、Free plan 可能被拒）；GPU AMI 根碟 75 GB → 設 80 GB gp3，**關機也付約 $7.7／月**，超過 $5 Budget（A：維持 Stop＋調高 Budget；B：用完 Terminate、下次從 user-data 重建）。

## 6. 留給產品負責人

1. review 後 commit（本輪零 commit）；計畫檔 83〜92 之後歸檔。
2. 決定：配額要不要申請（與被拒的 Plan B）、費用選 A 或 B。
3. Phase 92 動手時照 GPU 版計畫走；`worker.env` 填 `WORKER_VLM_BACKEND=local`＋`OLLAMA_BASE_URL=http://127.0.0.1:11434`＋`VLM_MODEL=gemma4:e2b`，`OLLAMA_API_KEY` 可留空。
4. 要改回純雲端推論：`worker.env` 的 `WORKER_VLM_BACKEND` 留空即可。
