# 2026-09-03 階段十二：工人改成可在 GPU EC2 跑本機 Ollama（design6 D12 作廢）＋ phase-92 計畫改版 — TODO

> 產品負責人 2026-09-03 對話指示：「想讓模型跑在 GPU 機上（EC2 自己裝 Ollama）去改動程式碼，相關文件也要改；phase-92 先更新、先不要實作」。ledger：`.superpowers/sdd/phase0902-2/progress.md`（裁決 R23〜R25）。

## 實作邏輯

- **改什麼**：工人 `main()` 原本寫死 `OllamaCloudVLM()`（design6 D12）。加一個設定 `WORKER_VLM_BACKEND`（`cloud` 預設＝ollama.com、`local`＝工人所在機器的 Ollama），`cloud_worker.build_worker_vlm()` 分流；`local` 不需要 `OLLAMA_API_KEY`；啟動行尾多 `vlm=… model=…`。閘門、S3／SQS 契約、六條規則、result.json **一個字不動**。
- **EC2 怎麼跑**：Ollama 跑在 host（官方 `ollama.service`，只聽 127.0.0.1），工人容器 `--network host` 去打它；unit 加 `After=/Wants=ollama.service` 與「等 `/api/tags` 活著」的 `ExecStartPre`；user-data 裝 Ollama 並 `ollama pull gemma4:e2b`；AMI 用 Deep Learning Base OSS NVIDIA Driver GPU AMI（驅動與 Docker 內建）。
- **實查到的兩個硬事實**（寫進 phase-92）：帳號的 G and VT 配額是 **0**（開機前要申請、可能被拒）；GPU AMI 根碟 75 GB → 關機也付約 $7.7／月，超過 $5 Budget（Stop／Terminate 兩選項待拍板）。
- **映像**：ECR `latest` 改推多架構（amd64＋arm64）manifest，另一個 tag `<sha>-dirty`（未 commit）。

## 步驟

- [x] 實查：東京 GPU 機型與價格、DL Base GPU AMI 參數與根碟、配額、ECR 現況、buildx。
- [x] 裁決 R23〜R25 入 ledger；總覽 §2.4.1／§2.4.2／§2.8／§3.2 D12／§10.2 T；design6.md D12 兩列註記。
- [x] Task 6（Opus 實作者）：`config.WORKER_VLM_BACKEND`、`build_worker_vlm()`、`main()` 缺設定檢查依後端、啟動行、6 顆測試（679 → 685）；`deploy/ec2/` 三檔；LAUNCH §12 與 CLAUDE 工人段。
- [x] Task 6 review（Opus）：Needs fixes——3 Important（空值 `WORKER_VLM_BACKEND=` 死循環、`local` 不檢查 `VLM_MODEL`、user-data 拉模型失敗會沒裝 unit）＋ 3 Minor → fix round 1（685 → 688；裁決 R26）re-review 6/6 ADDRESSED → round 2（cloud 也檢查 `OLLAMA_CLOUD_VLM_MODEL`；688 → 689；裁決 R27）re-review ADDRESSED。
- [x] Task 7（Opus 校準者 F）：phase-92 計畫改 GPU 版（81 處：配額前置、g4dn.xlarge、DL AMI、80 GB、`worker.env` 11 變數、Demo 證據 `vlm=local`、費用兩選項）——**只改計畫，不實作**；總覽／phase-91／phase-94 補改判註記。
- [x] controller：Mac 上 `WORKER_VLM_BACKEND=local` 完整回合 ✅（工人 `vlm=local model=gemma4:e2b`、本機看圖 90 秒、`result.json 已放好` → 本機 `雲端結果已入庫 #73`；SIGTERM 進來時做完手上那則才退）；多架構映像 build＋push ✅（`latest`＝linux/amd64＋linux/arm64、`bb3921a-dirty`；amd64 用 QEMU 實跑證明新碼在映像裡）。
- [x] controller 最終 review：689／三死埠 689／0 skipped／ruff／tokenize／機密掃描零命中／unit==內嵌段／零改動區全零；CLAUDE.md 概述段、記憶已更新；階段十二 REP（`docs/plan/report/2026-09-03-階段十二-GPU工人與phase92改版-REP.md`）。
