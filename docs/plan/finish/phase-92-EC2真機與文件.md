# Phase 92：EC2 真機（92-A 先 CPU、92-B 再 GPU）、Demo 2／2b、收工守則與三份文件 ＋ ★ 閘門 G3

> 📌 **2026-09-03 改判紀錄（產品負責人指示；本檔已依此改寫，但 ⛔ 還沒有實作）**
>
> **為什麼分成兩段：** GPU 配額（`L-DB2E81BA`）還在人工審核（狀態 `CASE_OPENED`、帳號上限仍是 0），
> 可能等數天、也可能被拒。而本 phase 真正要驗的那一整條 AWS 流程——instance profile 的臨時憑證、
> SG 只出不進、從 EC2 拉 ECR、SSM 進得去機器、systemd 開機自起、`Ec2Probe` 對**真實例**的
> running／stopped、amd64 映像第一次在**真的 x86** 上跑——**一顆 GPU 都用不到**。
> 所以**不等配額**：先用 CPU 機把流程與兩個 Demo 全部驗掉，GPU 留到配額下來再說。
>
> | | **92-A（現在就做）** | **92-B（配額核准 ≥4 之後）** |
> |---|---|---|
> | 機型 | **`t3.xlarge`**（4 vCPU／16 GiB、x86_64、**沒有 GPU**） | **`g4dn.xlarge`**（4 vCPU／16 GiB、NVIDIA T4、x86_64） |
> | AMI | 一般 **AL2023 x86_64** | **Deep Learning Base OSS NVIDIA Driver GPU AMI** |
> | 根碟 | **30 GB gp3** | **80 GB gp3**（那顆 AMI 的快照本身就 75 GB） |
> | `worker.env` 的 `WORKER_VLM_BACKEND` | **`cloud`**（看圖轉送 `ollama.com`） | **`local`**（看圖打那台機器**自己**的 Ollama） |
> | 東京 On-Demand | **$0.2176／小時** | 約 **$0.71／小時** |
> | 前置配額 | Standard `L-1216C47A`（本帳號實查 **8** vCPU，夠用，**不必申請**） | G and VT `L-DB2E81BA`（現在 **0**，要等核准） |
> | 收工動作 | **Stop**（stopped 只付 30 GB ≈ $2.9／月，留給 Phase 94 的 Demo 3 隨時 Start） | **Terminate**（費用選項 B，已拍板） |
> | 多驗的兩關 | 無 | `nvidia-smi` 看得到 Tesla T4、`ollama ps` 的 PROCESSOR 是 GPU |
>
> **兩段共用、一個字都不動的東西：** `deploy/ec2/` 三份檔（user-data／unit／env 範本）、
> Phase 91 建的 SG／IAM role ＋ instance profile／S3 Gateway endpoint／ECR、S3 bucket 與兩條 SQS、
> Mac 端**全部**程式碼與 `.env` 的切法、隱私閘門（本機、**VLM 短問、不看檔名**）、
> S3／SQS 的契約與順序鐵律、工人的六條處理規則、`result.json` 的形狀、Demo 2／2b 的意義、★G3 的門檻。
> **兩種機都由 user-data 裝地端 Ollama**（92-A 上它只是閒著應門，讓 unit 的 `ExecStartPre`
> 等 `127.0.0.1:11434` 那一關過）——看圖打哪一顆**只看 `WORKER_VLM_BACKEND`，機型不決定後端**。
> **零產品碼變更、零測試變更。**
>
> **★G3 改到「92-A 之後」**：Phase 93／94／95 沒有一件事依賴 GPU。
> 92-B 是獨立的後續步驟，配額核准後任何時間都可以做，**93〜95 不必等它**、也不設新的閘門。
>
> **設計層來源：** design6 **D12 作廢**（2026-09-03 GPU 改判，總覽 §10.2 追認項 **T**）；
> 「先 CPU 再 GPU」這件事本身是總覽 §10.2 追認項 **U**。
> D15 的「機型 `t4g.small`、映像僅 `linux/arm64`」跟著改成「x86_64 機型 ＋ 多架構映像」；
> D15 字面的「一律 Stop」在 92-B 被產品負責人授權例外（Terminate）。
> ⚠️ 配額申請**已由產品負責人自行送出**（`DesiredValue=4`、`CASE_OPENED`、2026-09-03 00:56 太平洋時間）
> ——**不要重送**（同一條配額重送只會被合併，不會加快）。

> 🎯 **提醒：這是 side project，不要過度設計。**
> **本 phase 特別不要做的六件事：**
> ① **不要對「還要再用」的機器 `terminate-instances`**（那是銷毀、不可逆）。
>    92-A 的收工動作一律 `stop-instances`；`terminate` 只用在兩個地方——
>    **開 92-B 之前先把 92-A 那台刪掉**（同時只留一台），以及 **92-B 整段測完**
>    （§4.9 的費用選項 **B**，產品負責人已拍板）。
> ② 不要為了「除錯方便」開 inbound 22（SSH）——管理只走 SSM Session Manager。
> ③ 不要把機器留著開機過夜。**92-A `t3.xlarge` 是 $0.2176／小時**（忘一整天 ≈ **$5.2**）、
>    **92-B `g4dn.xlarge` 是 $0.71／小時**（忘一整天 ≈ **$17**、一個月不關 ≈ **$515**）。
>    每個 Demo 結尾都要收工，看 §4.9。
> ④ 不要為了讓 fallback 快一點就去改 `EC2_PROBE_TTL_SECONDS`／`CLOUD_RESULT_TIMEOUT_SECONDS`
>    ——那兩個值是總覽 §2.4.2 的契約（60／300）。
>    **唯一的例外**是 §4.5 那個「92-A 選配：同一台切 `local` 試 CPU 推論」小節：
>    CPU 看一張圖大概率超過 5 分鐘，所以**那段測試期間**可以把 `CLOUD_RESULT_TIMEOUT_SECONDS`
>    暫時調成 **900**（對齊 jobs 佇列的 Visibility 900），做完**一定要改回 300**。
>    這是測試期的**暫時覆蓋**，日常契約不變。
> ⑤ **（只適用 92-B）不要用一般的 AL2023 AMI 開 GPU 機**——那顆映像沒有 NVIDIA 驅動，
>    Ollama 會**安靜地退回 CPU** 跑：你付了 GPU 的錢卻拿到比 Mac 還慢的速度，**而且不會有任何錯誤訊息**。
>    92-B 一律用 §4.2 那顆 Deep Learning Base GPU AMI。
>    ⚠️ 反過來一樣浪費：**92-A 不要用 GPU AMI**（那顆快照 75 GB，根碟只能開 ≥80 GB，
>    等於白付兩倍多的碟錢，見陷阱 21）。
> ⑥ **不要把 Ollama 裝進容器**。它跑在 host（官方 `ollama.service`、只聽 `127.0.0.1:11434`），
>    工人容器用 `--network host` 去打它。**兩段都一樣**。詳見 §4.5。

```text
┌─ ⛔ 開工前檢查 ────────────────────────────────────────────────────
│ ★ **★G2 早在 Phase 91 之前就已由產品負責人明示通過**（見 phase-91 檔頭那個框）。
│   本 phase 不再有新的閘門要等——**★G3 在 92-A「之後」**（文末那張表）。
│ ★ Phase 91 必須已經完成：SG、S3 Gateway endpoint、IAM role ＋ instance profile、
│   ECR repo 與第一次手動 push（`latest` 必須是**多架構**），以及 deploy/ec2/ 三份檔。
│   缺任何一個，§4.3 就跑不動。
│ ★ **92-A 的配額前置是 Standard On-Demand（`L-1216C47A`）≥ 4 vCPU**——`t3.xlarge` 佔 4 個。
│   2026-09-03 用 admin CLI 實查本帳號是 **8**，夠用：**不必申請、不必等**。
│   （新帳號 Standard 預設常是 5 vCPU，本帳號實查 8。）
│ ★ **GPU 配額（`L-DB2E81BA`）只是 92-B 的前置**：現在是 0、申請中（`CASE_OPENED`）。
│   **92-A 完全不碰它**——查出來是 0 也照做不誤，那不是擋路的東西。
│ ⛔ 本 phase 的第一行 `run-instances` 是整個增量六**第一個真的花錢**的指令
│   （92-A **$0.2176／小時**、92-B **$0.71／小時**）。下去之前先確認 Budget 還在
│   （Phase 82 建的 personaldocai-budget，每月 $5）。帳號已升 **Paid** ＝忘了關會扣卡。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標（92-A，現在做）：** 用 Phase 91 備好的周邊，真的開一台 **`t3.xlarge`**
> （一般 AL2023／x86_64／**30 GB gp3**）、用 **Session Manager**（不開 SSH）進去放好
> `/opt/personaldocai/worker.env`（含 **`WORKER_VLM_BACKEND=cloud`**）、把工人服務跑起來並看到
> `version=<sha> … vlm=cloud model=<雲端模型名>`；然後把本機 `.env` 切成 `CLOUD_ROUTE=ec2`，
> 親手跑一次 **Demo 2**（Start → 非敏感走雲端 → 照片進待決定 → 問得到）與
> **Demo 2b**（Stop → 再傳一張 → 自動走本機、S3 零新物件）；做完 **Stop**，
> 最後把 `LAUNCH.md`（新章節 **13**）／`CLAUDE.md`／`README.md` 三份文件改成誠實的現況，交出 ★G3。

> 🎯 **一句話目標（92-B，配額核准後）：** **先 Terminate 92-A 那台**，再用**同一份**
> user-data／unit／映像開一台 **`g4dn.xlarge`**（Deep Learning Base GPU AMI／**80 GB gp3**），
> `worker.env` 只改一行成 **`WORKER_VLM_BACKEND=local`**、多驗兩關
> （`nvidia-smi` 看得到 Tesla T4、`ollama ps` 的 PROCESSOR 是 `100% GPU`）、
> 重跑一次 Demo 2 看工人 log 變成 `backend=local`，然後 **Terminate**。
> **92-B 沒有新的閘門，也不改任何文件結論**（三份文件在 92-A 就已經寫成兩段式的誠實版本）。

**為什麼要做這個：**

到目前為止，「雲端這條路」全部是在這台 Mac 上模擬的——Phase 88 用 `python -m` 跑工人、
Phase 90 用容器跑工人，兩次都是**左手交給右手**，一點壓力都沒卸掉，
也還沒證明「工人在一台**看不到螢幕**的機器上也活得下去」。

這一份把工人真的搬到別人的機房，然後做兩件**同等重要**的事：

1. **Demo 2**：機器開著的時候，非敏感照片真的在 EC2 上被看懂，結果回家入庫。
   （**92-A** 是那台 CPU 機把圖轉送給 `ollama.com` 看；**92-B** 是那台機器**自己的 GPU** 看。
   兩段的證據形狀**完全一樣**，差別只有工人 log 印的是 `backend=cloud` 還是 `backend=local`。）
2. **Demo 2b**：機器關掉之後，**什麼設定都不改**，照片照樣進得來——
   只是回到本機看圖。這一條比 Demo 2 更重要，因為 **EC2 平常是關著的**
   （產品負責人要卡片 $0），所以「關著也能用」才是這個系統 99% 的時間裡的樣子。

⚠️ **92-A 用 CPU 機不是妥協，是先驗真正會壞的那一半。** 上面兩個 Demo 要證明的每一件事
（instance profile 的臨時憑證到不到得了容器裡、SG 只出不進還能不能拉 ECR、SSM 進不進得去、
systemd 開機會不會自己把工人拉起來、`Ec2Probe` 對**真實例**的 running／stopped 判得準不準、
amd64 映像第一次在**真的 x86** 上跑會不會 `exec format error`）——**一顆 GPU 都用不到**。
GPU 只影響「看圖那一步在哪裡做、要花幾秒」，那是 92-B 的事。

最後，文件要跟現實一致：`README.md` 現在寫著「No cloud storage — photos never leave
your machine」，做完這個增量之後**那句話不再完全為真**（非敏感檔會短暫經過 S3）。
留著不改就是騙人，所以本 phase 一併改掉。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **92-A ／ 92-B** | 本 phase 的兩段。**92-A** ＝現在就做的 CPU 機（`t3.xlarge`、看圖轉送 `ollama.com`）；**92-B** ＝ GPU 配額核准之後才做的 GPU 機（`g4dn.xlarge`、看圖打自己的 Ollama）。兩段跑的是**同一份** user-data、同一份 systemd unit、同一份容器映像，差別只有三個變數（機型／AMI／根碟大小）與 `worker.env` 裡的一行 |
| **AMI（Amazon Machine Image）** | 「一台機器的出廠映像」。開 EC2 時要選一個 AMI，它決定裡面是哪個作業系統。AMI id 長得像 `ami-0123…`，**每個區域的 id 不一樣**、而且會隨著 AWS 更新而變 |
| **SSM 公開參數** | AWS 幫每個 AMI 系列維護的一個「永遠指向最新版」的名字。查它就拿得到當下最新的 AMI id，不必自己去 Console 翻。本 phase 用兩個：**92-A** 用一般 AL2023 的 `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`；**92-B** 用 GPU 版的 `/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id` |
| **`t3.xlarge`**（**92-A** 的機型） | 一般的 CPU 機：**4 vCPU／16 GiB 記憶體、x86_64、沒有 GPU**。東京 on-demand **$0.2176／小時**。選它的三個理由：① 跟 `g4dn.xlarge` **同架構（x86_64）**，所以先驗到的就是 92-B 之後會用的那一份 amd64 映像；② 16 GiB 記憶體夠大，之後想在同一台試 §4.5 那個「切 `local` 用 CPU 推論」的選配步驟時載得動 7.2 GB 的模型；③ 佔 4 個 Standard vCPU，本帳號配額 8，**不必等任何人核准** |
| **`g4dn.xlarge`**（**92-B** 的機型） | 帶一顆 **NVIDIA T4（16 GB VRAM）** 的 GPU 機：4 vCPU／16 GB 記憶體、**x86_64**（不是 ARM）。東京 on-demand 約 **$0.71／小時**。選它的理由：x86 是 Ollama ＋ CUDA 最主流、踩雷最少的一條路 |
| **`g5g.xlarge`**（92-B 的省錢替代，未驗證） | arm64（Graviton2）＋ T4g 16 GB、4 vCPU／8 GB RAM、約 $0.567／小時。便宜兩成，但 **Ollama 在 arm64 上的 CUDA 支援我們沒有驗過**——真的要換再單獨驗一次，不要在真機日當場換 |
| **Deep Learning Base OSS NVIDIA Driver GPU AMI (AL2023)** | AWS 出的「已經裝好 NVIDIA 驅動、Docker、nvidia-container-toolkit」的 AL2023 映像，**92-B 專用**。**一般的 AL2023 AMI 沒有驅動**，Ollama 在上面會安靜地退回 CPU（不報錯，只是慢十倍）。⚠️ 它的根碟快照就 **75 GB**，所以**不要拿它開 92-A 的 CPU 機**——白付兩倍多的碟錢 |
| **服務配額（Service Quotas）** | AWS 對每個帳號「同時能跑幾個 vCPU」設的上限，而且**一般機與 GPU 機各走一條**：一般的 `t3`／`t4g`／`m6i` 走 **`L-1216C47A`（Running On-Demand Standard instances）**，本帳號實查 **8 vCPU**（新帳號 Standard 預設常是 5 vCPU，本帳號實查 8）＝ **92-A 直接可以開**；GPU 機另走 **`L-DB2E81BA`（Running On-Demand G and VT instances）**，本帳號是 **0**、申請中——那是 **92-B** 的前置，`run-instances` 沒核准就回 `VcpuLimitExceeded` |
| **`nvidia-smi`／`ollama ps`**（只有 92-B 有） | 兩個「GPU 真的有在做事嗎」的檢查：`nvidia-smi` 印出顯示卡與驅動版號（以及**正在用 VRAM 的行程**）；`ollama ps` 印出模型是不是放在 GPU 上。⚠️ **Ollama 安裝腳本不安裝 NVIDIA 核心驅動**——`nvidia-smi` 沒了，它會安靜走 CPU。驅動來自 §4.2 那顆 GPU AMI，不是來自 `install.sh`。⚠️ **92-A 的 CPU 機上 `nvidia-smi` 本來就不存在**，那是正常的，不是壞掉 |
| **`WORKER_VLM_BACKEND`** | 工人（`cloud_worker`）看圖要打哪一顆模型：`cloud` ＝ `ollama.com`（**預設**，留空或不填也算；**92-A 填這個**）、`local` ＝ **工人自己那台機器**上的 Ollama（**92-B 填這個**）。⚠️ 它跟頁首那顆「AI 模型：本機｜雲端」開關**完全無關**。⚠️ **改這個是改機器上的 `worker.env`，不是改 `app/core/config.py`**（那支只 `getenv`；容器裡 env 會蓋過檔案預設）。⚠️ **機型不決定後端**：CPU 機也可以設 `local`（只是很慢，見 §4.5 的選配小節），GPU 機也可以設 `cloud`（只是白開 GPU）。現有 systemd 不論 `cloud`／`local` 都會先等本機 `11434`，所以**兩段都要裝 Ollama** |
| **`--network host`** | 讓容器直接用 host 的網路命名空間。EC2 上的 Ollama 只聽 `127.0.0.1:11434`，容器要打得到它就得共用 host 的 loopback。工人不聽任何埠、SG inbound 又是空的，所以這樣不會多暴露什麼 |
| **block device mapping（磁碟對應）** | 「這台機器要掛哪些硬碟、每顆多大、什麼型別」。**92-A 是一顆 30 GB 的 `gp3` 根碟**（OS ＋ docker 映像 ＋ Ollama 約 2 GB ＋ 模型 7.2 GB 綽綽有餘）；**92-B 是 80 GB**（GPU AMI 的快照本身就 75 GB，再留給模型與映像一點空間） |
| **gp3** | EBS 的一種硬碟型別（通用 SSD 第 3 代）。比舊的 `gp2` 便宜一點、效能也夠，**是現在的預設選擇** |
| **IMDS / `HttpTokens=required`（IMDSv2）／`HttpPutResponseHopLimit=2`** | 機器內部有一個「問自己是誰」的服務（instance metadata service，位址 `169.254.169.254`），boto3 就是靠它拿 instance profile 的臨時憑證。`HttpTokens=required` ＝**強制用比較安全的第 2 版**（要先換一個 token 才能問）。`HttpPutResponseHopLimit=2` ＝那個 token 的回應**准許多走一個網路節點**：我們的工人跑在 **Docker 容器**裡，容器到宿主機算一跳，預設的 1 跳會讓容器裡的 boto3 **永遠拿不到憑證**（AWS 官方文件明文：容器環境請設 2）。**兩段都要帶** |
| **`--associate-public-ip-address`** | 「開機時自動給我一個公有 IP」。機器**沒有公有 IP 就出不了網**（S3／SQS／ECR／SSM／ollama.com 全部不通）。Phase 91 §4.1 挑的子網本來就會自動配（`MapPublicIpOnLaunch=true`），明寫是雙保險。⚠️ **2024-02-01 起所有公有 IPv4 都要錢**：$0.005／小時——但這種「自動配」的 IP 只在機器 **running** 時存在，**Stop 之後自動釋放、就不再計費**；Elastic IP 則是配了就每小時扣、不管有沒有掛在跑著的機器上 |
| **SSM Session Manager** | 不開 SSH 也能拿到那台機器 shell 的服務。從 Mac 上 `aws ssm start-session --target <id>` 就進去了，權限走 IAM，不必管金鑰 |
| **`session-manager-plugin`** | `aws ssm start-session` 需要的一個額外外掛（AWS CLI 本身不含）。Mac 上用 Homebrew 裝 |
| **`systemctl status` / `journalctl`** | 看一個 systemd 服務現在好不好（`status`）、以及它從頭到尾印了什麼（`journalctl -u <服務名>`）。服務起不來時這兩個是第一現場 |
| **`/var/log/cloud-init-output.log`** | user-data 開機腳本的輸出都在這個檔裡。機器起來卻「什麼都沒裝」時，第一個要看它 |
| **Stop vs Terminate** | **Stop ＝ 關機**：硬碟（EBS）留著，開回來東西都還在，只有硬碟繼續計費，公有 IP 會被收回。**Terminate ＝ 銷毀**：整台連硬碟一起消失，**不可逆**。本 phase：**92-A 收工 Stop**（留給 Phase 94 的 Demo 3 用）、**開 92-B 之前先 Terminate 92-A**、**92-B 測完 Terminate**。Terminate **只刪那台機器**，SG／IAM／S3／SQS／ECR 留下 |
| **EBS** | EC2 的虛擬硬碟。Stop 之後運算費停了，但 EBS 仍按 GB 計費（東京約 $0.096／GB／月）。**92-A 的 30 GB ≈ $2.9／月**（在 $5 Budget 內，所以 92-A 可以放心 Stop）；**92-B 的 80 GB ≈ $7.7／月**（單獨就超過 Budget，所以 92-B 測完要 Terminate，§4.9） |
| **探測快取 TTL（`EC2_PROBE_TTL_SECONDS`）** | 本機每次要送雲端之前會問 AWS「那台機器 running 嗎」，答案**快取 60 秒**（不然每張圖都打一次 API）。所以剛 Stop 完的 60 秒內，本機可能還以為它開著——Demo 2b 會遇到，見 §4.8 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D11** | 「EC2 只當工人…Security group inbound 全關。出站 TCP 443」 | §4.3 用 Phase 91 那個 SG（92-A／92-B 同一個）；§4.5 只走 SSM 進機器，全程零 SSH |
| ~~**D12**~~ | ~~「EC2 看圖一律 Ollama Cloud（實例無 GPU）」~~ → **2026-09-03 產品負責人改判作廢** | 改成「工人看圖後端由 `WORKER_VLM_BACKEND` 決定」：**92-A 填 `cloud`**（行為剛好與 D12 原文相同，只是現在是設定不是硬規則）、**92-B 填 `local`**（GPU 機自己裝 Ollama 看圖）。仍**與頁首開關無關**（那是 D6 的另一扇門） |
| **D10** | 「遠端關掉＝fallback 本機」 | §4.8 的 **Demo 2b**：Stop 之後**什麼設定都不改**，照片照樣入庫。**92-A 就要驗完**，92-B 不必重驗 |
| **D13** | 「拉回 `result.json` 後，embedding 與 INSERT／原圖／縮圖仍在本機」 | §4.7 Demo 2 的第 5 步：本機 log 要有 `kind=embed backend=local`（兩段都一樣） |
| **D15** | 「Free plan…用完 EC2 就 **Stop**。~~映像 `linux/arm64`，機型 t4g.small~~」 | 機型／映像於 2026-09-03 改成 **x86_64 機型 ＋ 多架構映像**（92-A `t3.xlarge`、92-B `g4dn.xlarge`）。**92-A 收工照 D15 用 Stop**（30 GB ≈ $2.9／月，在 Budget 內）；**92-B 已拍板選 B ＝ Terminate**（字面違反「一律 Stop」，產品負責人授權）。帳號已升 Paid（扣卡，不再是「點數用完關帳」） |
| **總覽 §10.2 追認項 T** | 2026-09-03 的 GPU 改判本身（D12 作廢、D15 機型與映像改、`WORKER_VLM_BACKEND`、GPU 配額成為新前置、費用兩選項） | 檔頭那個「📌 2026-09-03 改判紀錄」框；§4.2〜§4.5 的 **92-B** 變體、§4.9 |
| **總覽 §10.2 追認項 U** | 2026-09-03 再改判：**Phase 92 拆成 92-A（CPU、現在）／92-B（GPU、配額核准後）**，★G3 移到 92-A 之後 | 全檔的 92-A／92-B 兩段式；§2 的兩張前置表、§3 的兩份範圍、§4.2／§4.3 的三個變數、§4.9 的三種收工、§6 的兩張驗收表、文末 ★G3 |
| **§7 全節** | Free plan 約束、公有子網＋自動公有 IPv4、禁止 NAT、inbound 全關、Budget | §4.3 的旗標；§4.9；§4.10 寫進三份文件 |
| **§3「不做」最後一列前** | 「Free plan 操作約束寫進 `LAUNCH.md`／`CLAUDE.md`」 | §4.10 |
| **§12 Demo 2** | 「EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉；照片進待決定；詢問能問到」 | §4.7（逐條照抄總覽 §5.2）。**92-A 就要全過**；92-B 只是換一台機器再看一次 `backend=` 那一行 |
| **§12 Demo 2b** | 「EC2 Stop 後上傳非敏感；**不必改任何設定**；進度與入庫與增量五相同；S3 不出現新物件」 | §4.8（逐條照抄總覽 §5.3）。**92-A 就要全過** |
| **總覽 §10 追認項 h** | 「EC2 上的機密用 **Session Manager 手動**建 `/opt/personaldocai/worker.env`（`chmod 600`），**不用** Parameter Store」 | §4.5（92-A 與 92-B 各放一次） |
| **總覽 §10 追認項 l** | 「`CLOUD_ROUTE=assume` 只給階段丁與除錯；**戊之後日常用 `ec2`**」 | §4.6 把 `.env` 從 `assume` 改成 `ec2`（92-A 就做，92-B 不必再改） |
| **總覽 §10 追認項 e** | 「『跑的是不是新映像』靠 `WORKER_VERSION` 的 log 驗」 | §4.5 最後一步要看到 `version=<sha>` |
| **總覽 §2.7（Phase 92）、§3.8** | `README.md` 第 11 行與第 635 行「no cloud storage」不再完全為真——「兩句改誠實」 | §4.10 第 3 小節（英文改寫；92-A 就寫完） |

> ⚠️ **「追認項 h」與「追認項 l」是計畫層的裁決，不是 design6 自己寫的字**（總覽 §10 明文）。

---

## 2. 前置條件

**依賴：Phase 91 全部完成（★G2 更早之前已通過）。**

**兩段各自的前置：**

| | **92-A（現在做）** | **92-B（配額核准之後）** |
|---|---|---|
| Phase 91 的周邊（SG／instance profile／ECR／`deploy/ec2/` 三檔） | ★ 必須完成 | ★ 同一份，不必重做 |
| ECR 的 `latest` 是**多架構** manifest | ★ 必須（`t3.xlarge` 是 x86_64） | ★ 同上 |
| Standard On-Demand 配額 `L-1216C47A` ≥ 4 vCPU | ★ **本帳號實查 8，已經夠**（不必申請） | 不吃這條 |
| G and VT 配額 `L-DB2E81BA` ≥ 4 | **完全不需要**（查出來是 0 也照做） | ★ 必須 `APPROVED`、`Value` ＝ 4 |
| 92-A 那台機器 | ——  | ★ **必須已經 Terminate**（同時只留一台） |
| ★G3 | 92-A 之後交出 | 不設新閘門 |

**開工基線（雙寫法）：** 總覽 §9 寫的是 **662**，那是規劃當時的估算；
**實測基線是 689**（2026-09-02 實查 679 ＋ 2026-09-03 GPU 改判那批工人測試與兩輪 fix 共 +10）。
兩個數字都不必去改總覽，**以你開工當天 `pytest -q` 的實際輸出為準**——
本 phase 要驗的是「**收工顆數與開工顆數逐字相同**」，不是某個絕對值。
**本 phase 新增 0 顆測試**：它做的是真機操作與文件。

> 📌 **本 phase 的每一件事都是「人 ＋ CLI」**（開機、進機器、跑 Demo、改三份文件），
> **沒有任何一步是寫程式**。工人程式與 `deploy/ec2/` 三份檔在 Phase 87／88／91 就改好了，
> 本檔只負責「把它們真的用起來」。所以這裡沒有 TDD，體例是
> 「指令 → 每個旗標的用途 → 預期輸出 → 做錯了怎麼退回 → 費用影響」。

**開工前一次驗完（92-A）：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ .env 那把是程式用的最小權限 key；CLI 要回去用 ~/.aws 的 admin
. /tmp/p91-vars.sh 2>/dev/null || true      # Phase 91 存的 SG_ID／SUBNET_ID… 若還在就載回來
aws sts get-caller-identity --query Arn --output text   # 預期結尾：user/personaldocai-admin

# ① ★ 92-A 吃的是 **Standard** 配額（不是 GPU 那條）。t3.xlarge 佔 4 個 vCPU
aws service-quotas get-service-quota --region "$AWS_REGION" \
  --service-code ec2 --quota-code L-1216C47A \
  --query '{Name:QuotaName,Value:Value}' --output json
# 預期：{"Name":"Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances","Value":8.0}
# ★ 只要 Value ≥ 4 就可以開 92-A，**不必申請、不必等**。
#   （新帳號 Standard 預設常是 5 vCPU，本帳號 2026-09-03 實查 8。）

# ② GPU 配額 —— **這一條只是 92-B 的前置，92-A 看到 0 也照做不誤**
aws service-quotas get-service-quota --region "$AWS_REGION" \
  --service-code ec2 --quota-code L-DB2E81BA \
  --query '{Name:QuotaName,Value:Value}' --output json
# 現況（2026-09-03）：{"Name":"Running On-Demand G and VT instances","Value":0.0}
# 申請已由產品負責人送出（DesiredValue=4、CASE_OPENED）。**不要重送**——
# 同一條配額重送只會被合併，不會加快。追蹤進度：
aws service-quotas list-requested-service-quota-change-history-by-quota --region "$AWS_REGION" \
  --service-code ec2 --quota-code L-DB2E81BA \
  --query 'RequestedQuotas[].{Status:Status,Value:DesiredValue,Updated:LastUpdated}' --output table
# 看到 APPROVED 且上面那條 get-service-quota 的 Value ＝ 4，才准做 92-B。

# ③ 顆數基線（本 phase 不會改變它；數字以當天實際輸出為準，見上面「雙寫法」）
pytest -q                                    # 預期：689 passed，0 skipped

# ④ Phase 91 的四樣東西都在（缺一個 §4.3 就跑不動）
aws ec2 describe-security-groups --region "$AWS_REGION" \
  --filters Name=group-name,Values=personaldocai-worker-sg \
  --query 'SecurityGroups[0].{Id:GroupId,In:IpPermissions}' --output json
# 預期：{"Id":"sg-…","In":[]}   ← inbound 必須是空陣列

aws iam get-instance-profile --instance-profile-name personaldocai-worker-role \
  --query 'InstanceProfile.Roles[].RoleName' --output text     # 預期：personaldocai-worker-role

aws ecr describe-images --region "$AWS_REGION" --repository-name personaldocai-worker \
  --query 'imageDetails[?imageTags].imageTags[]' --output json
# 預期：含 "latest" 與某個 <sha>（本輪尚未 commit 的話另有一個 <sha>-dirty）

ls -l deploy/ec2/user-data.sh deploy/ec2/personaldocai-worker.service \
      deploy/ec2/worker.env.example
# ⚠ 這三份檔在 2026-09-03 隨 GPU 改判改過（裝 Ollama、等 /api/tags、--network host、
#   worker.env 多三個變數）。**92-A 與 92-B 用的是同一份，一個字都不改。**
#   本檔**不重貼它們的內容**——引用時一律以 deploy/ec2/ 的實檔為準。

# ⑤ ★ ECR 的 latest 必須是**多架構** manifest（t3.xlarge 與 g4dn.xlarge 都是 x86_64，
#    要拉得到 amd64 那一份）
docker manifest inspect "${ECR_URI}:latest" \
  | python3 -c "import json,sys; print(sorted(m['platform']['architecture'] for m in json.load(sys.stdin).get('manifests', [])))"
# 預期：['amd64', 'arm64']
# 印出 KeyError／空清單 ＝ 那是單架構映像（Phase 90 建的 arm64 那一份），
#   在 x86 機器上 docker run 會回 exec format error（陷阱 4）。回 Phase 90／91 用 buildx 重推多架構。
# ⚠ 這條要先 docker login 到 ECR（Phase 91 §4.7 那兩行）；docker manifest 是讀 registry，不是讀本機映像。

# ⑥ 變數（Phase 91 §4.1 那五個 ＋ SG／ECR）
echo "region=$AWS_REGION"                    # 預期：region=ap-northeast-1
echo "subnet=${SUBNET_ID:?請回 phase-91 §4.1 重查} sg=${SG_ID:?同上}"
echo "ecr 尾巴=${ECR_URI##*/}"               # 預期：personaldocai-worker
# ⚠ 92-A 的 worker.env 走 cloud 模式，所以要用到本機 .env 的 OLLAMA_API_KEY 與
#   OLLAMA_CLOUD_VLM_MODEL（§4.5）。這裡**不要 echo 它們的值**。
echo "雲端模型名有沒有填：${OLLAMA_CLOUD_VLM_MODEL:+有}"   # 預期印「有」
echo "雲端金鑰有沒有填：${OLLAMA_API_KEY:+有}"             # 預期印「有」

# ⑦ 目前沒有任何 EC2 在跑（2026-09-03 實查：帳號內 0 台，任何狀態）
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,State:State.Name}' --output table
# 預期：空表格。有東西＝先搞清楚那是誰，不要一次開兩台（兩台會搶同一條 SQS 佇列）。

# ⑧ 分支與快照
git branch --show-current                    # 預期：main
git status --short > /tmp/p92-before.txt
```

**92-B 開工前多驗兩條（配額核准之後才做）：**

```bash
# ⑨ GPU 配額真的過了
aws service-quotas get-service-quota --region "$AWS_REGION" \
  --service-code ec2 --quota-code L-DB2E81BA --query 'Value' --output text   # 預期：4.0

# ⑩ 92-A 那台已經 Terminate（同時只留一台）
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=tag:Name,Values=personaldocai-worker \
            Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].InstanceId' --output text
# 預期：空。還有東西＝先照 §4.9 把 92-A 那台 terminate 掉再往下。
```

> ⚠️ **`${SUBNET_ID:?訊息}` 是 bash 的「沒設就報錯」寫法。** 變數是空的時候
> 它會印出那句訊息並讓指令失敗，比默默用空字串往下跑好得多
> （空字串塞進 `--subnet-id` 會得到一個看不懂的 `InvalidParameterValue`）。
> 同理 `${VAR:+有}` ＝「有值就印『有』、沒值就印空的」——用來確認機密**有沒有填**，
> 而**不會把值印出來**。

> ⚠️ **`unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 不能省（Phase 82 §4.7 定案的兩把 key 分工）：**
> `.env` 那把是 `personaldocai-mac`（程式用、最小權限——只有 S3 前綴、兩條佇列、`ec2:DescribeInstances`），
> 而環境變數的優先序**高於** `~/.aws` 的 admin profile；不 unset 的話本 phase 除了 `describe-instances`
> 以外的每一條 `aws` 指令（`run-instances`、`start-session`、`stop-instances`、`s3api list-objects-v2`…）
> 都會 `AccessDenied`／`UnauthorizedOperation`。`aws sts get-caller-identity` 的 Arn 結尾必須是
> `user/personaldocai-admin` 才對（陷阱 11）。

> ⚠️ **本 phase 的每一個 `aws ec2`／`aws ssm` 指令都帶 `--region "$AWS_REGION"`。**
> 不帶的話 CLI 用 `~/.aws/config` 的預設區域（常是美東），
> 於是「機器建在美東、SG 在東京」，錯誤訊息卻只寫 `InvalidGroup.NotFound`。

---

## 3. 範圍

### 做（92-A：現在就做的 CPU 機）

1. 裝 `session-manager-plugin`（Mac 上一次性；兩段共用）。
2. 查最新的**一般 AL2023（x86_64）** AMI id（§4.2 的變體 A）。
3. `run-instances` 開一台 **`t3.xlarge`**（帶 user-data、instance profile、SG、公有 IP、
   **30 GB gp3**、IMDSv2 且 hop limit 2）；第一次開機由 user-data 裝好 Docker、systemd 服務、
   Ollama 並 `ollama pull gemma4:e2b`（CPU 機上這顆模型只是閒著，讓 unit 的等待那一關過）。
4. 等 `running`、等 **SSM 上線**、等 **user-data 跑完**。
5. Session Manager 進去建 `/opt/personaldocai/worker.env`（`chmod 600`，含 **`WORKER_VLM_BACKEND=cloud`**
   ＋ `OLLAMA_API_KEY` ＋ `OLLAMA_CLOUD_VLM_MODEL`）、`systemctl start`、
   看 `systemctl status` 與 `docker logs cloud-worker` 第一行的 `version=<sha> … vlm=cloud model=…`。
6. 本機 `.env` 改 `EC2_WORKER_INSTANCE_ID=<id>`、`CLOUD_ROUTE=ec2`、
   `CLOUD_RESULT_TIMEOUT_SECONDS=300`，重啟本機 worker。
7. **Demo 2**（總覽 §5.2 逐條）。
8. **Demo 2b**（總覽 §5.3 逐條）。
9. **收工 Stop**（§4.9）——30 GB ≈ $2.9／月，在 Budget 內，留給 Phase 94 的 Demo 3 隨時 Start。
10. 三份文件：`LAUNCH.md` 新章節 **13**（§12 已被 Phase 88 用掉）＋ Appendix 架構圖、`CLAUDE.md` 指令區、
    `README.md` 第 11 行與第 635 行改成誠實版本。**三份都寫成兩段式的誠實現況**（現在是 CPU 機、
    GPU 機是配額核准後的後續），92-B 做完不必再改。
11. 交出 **★ 閘門 G3**（文末那張表）。

（選配，可做可不做：§4.5 最後那個「同一台切 `local` 試 CPU 推論」小節。
做的話**一定要**先把 Mac `.env` 的 `CLOUD_RESULT_TIMEOUT_SECONDS` 從 300 暫調 900，做完改回。）

### 做（92-B：GPU 配額核准之後的後續步驟）

0. 先確認 GPU 配額已 `APPROVED`（§2 ⑨），並 **Terminate 92-A 那台**（§2 ⑩、§4.9）。
1. 查最新的 **Deep Learning Base OSS NVIDIA Driver GPU AMI（AL2023、x86_64）** id（§4.2 的變體 B）。
2. `run-instances` 開一台 **`g4dn.xlarge`**（**80 GB gp3**，其餘旗標與 92-A 逐字相同）。
3. §4.4 照做（第一次開機一樣要等 user-data 拉 7 GB 模型）。
4. §4.5 照做，但 `worker.env` 的那一行改成 **`WORKER_VLM_BACKEND=local`**（＋`OLLAMA_BASE_URL`／`VLM_MODEL`），
   並**多驗兩關**：`nvidia-smi -L` 看得到 Tesla T4、`ollama ps` 的 PROCESSOR 是 `100% GPU`。
5. 本機 `.env` 只改 `EC2_WORKER_INSTANCE_ID`（新的 id），`restart worker`。
6. **重跑一次 Demo 2**，證據只多看一行：工人 log 從 `backend=cloud` 變成 **`backend=local`**。
   （Demo 2b 在 92-A 已經驗過「關掉就 fallback」，**不必重驗**。）
7. **收工 Terminate**（§4.9 費用選項 B，已拍板）——80 GB 關機仍要 ≈ $7.7／月，超過 Budget。

**92-B 不做的事：不改任何程式、不改 `deploy/ec2/`、不改三份文件的結論、不設新的閘門。**

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 對「還要再用」的機器 `terminate-instances` | **不可逆**：整台連 EBS 一起消失，`worker.env` 要重放、user-data 要重跑（含重裝 Ollama、重拉 7 GB 模型，多等幾分鐘）。**92-A 收工一律 `stop-instances`**；`terminate` 只准用在三處：① 開 92-B 前刪掉 92-A、② 92-B 整段測完（費用選項 B）、③ 重試 `run-instances` 時不小心開出兩台、要刪掉多的那台 |
| 開 inbound 22（SSH）或裝任何 SSH 金鑰 | design6 §0 禁止第 3 條、D11。`run-instances` 也**不帶 `--key-name`**——沒有金鑰就沒有「偷偷開 SSH」這個選項 |
| ~~在 EC2 上裝 Ollama~~ **（2026-09-03 改判：兩段都要裝）**；但 Postgres、Redis、Celery 仍然一個都不裝 | D11／§3「不做」對資料庫與佇列的部分**原封不動**：工人不碰資料庫、不碰 Redis、不跑 Celery。~~D12「不裝 Ollama」~~ 已作廢——user-data 會裝 `ollama.service` 並拉 `gemma4:e2b`。⚠️ **92-A 的 CPU 機上它只是閒著應門**（讓 unit 的 `ExecStartPre` 那一關過），看圖仍然打 `ollama.com` |
| 為了「92-A 反正不用 GPU」就去改 unit、拿掉等 Ollama 那條 `ExecStartPre` | 那就不是「零產品碼、照稿開機」了，而且 92-B 又要改回來（＝過渡產物）。`deploy/ec2/` 三份檔**兩段共用、一個字都不動** |
| 把 Ollama 裝進**容器**、或讓它聽 `0.0.0.0` | Ollama 跑 **host**（官方安裝腳本裝成 `ollama.service`，預設只聽 `127.0.0.1:11434`），工人容器用 `--network host` 去打它。改聽 `0.0.0.0` 等於把模型服務對整個子網路打開，是**擴大**暴露面（雖然 SG inbound 是空的，但沒有理由多開一扇門） |
| **92-A 用 GPU AMI**（Deep Learning Base） | 那顆 AMI 的快照就 **75 GB**，根碟開不到 30 GB（會 `InvalidBlockDeviceMapping`），只能開 ≥80 GB ＝ 白付兩倍多的碟錢，而 CPU 機根本用不到裡面的驅動（陷阱 21） |
| **92-B 用一般的 AL2023 AMI**（沒有 NVIDIA 驅動） | Ollama 會**安靜地**退回 CPU：不報錯、只是一張圖從幾秒變好幾分鐘。付了 GPU 的錢卻沒用到 GPU，而且很難察覺 |
| 在 EC2 上另外裝 CUDA／驅動／nvidia-container-toolkit | 92-B 那顆 AMI **已經內建**。自己再裝一次只會版本打架。92-A 根本不需要 |
| **92-A 用 `t3.small`／`t3.large` 省錢** | `cloud` 模式下它們其實跑得動（Ollama 閒置時不載模型），但只要有人手滑試了 §4.5 的選配步驟切成 `local`，`gemma4:e2b` **7.2 GB** 就載不進去（`t3.small` 2 GiB、`t3.large` 8 GiB 都不夠），而且錯誤訊息看不出是記憶體問題（陷阱 19）。一小時差不到 $0.2，不值得省 |
| 配 Elastic IP 讓它有固定 IP | 總覽 §2.8 禁止清單。沒有人會主動連進來（inbound 空），不需要固定 IP；而且 EIP **配了就每小時 $0.005 一直扣、不管機器有沒有在跑**（2024-02-01 起），跟「常態 Stop」的用法正好相反——自動配的公有 IP 則是 Stop 就釋放、就不算錢 |
| 建 NAT Gateway | design6 §0 禁止第 4 條。公有子網 ＋ 公有 IP 本來就出得去 |
| 為了省事把 `CLOUD_ROUTE` 留在 `assume` | 總覽 §10 追認項 l：`assume` 不做探測，機器關著時它會傻傻送出、等到逾時（5 分鐘）才 fallback。日常一定要 `ec2` |
| 改 `EC2_PROBE_TTL_SECONDS`（60）或 `CLOUD_RESULT_TIMEOUT_SECONDS`（300） | 總覽 §2.4.2 的契約值。Demo 2b 那 60 秒「探測還說 running」是**預期行為**，不是 bug（§4.8 有教怎麼處理）。**唯一例外**是 §4.5 那個選配的 CPU 推論小節（暫調 900、做完改回 300），那是測試期的暫時覆蓋 |
| 改任何 `app/` 底下的程式碼、測試、`Dockerfile`、`compose.yaml` | 本 phase **零產品程式碼變更、零測試變更**。真的發現工人有 bug → 回 Phase 87／88 修 |
| 改 `docs/spec/` | 總覽 §7 鐵律 16：本增量規格區**一個字都不動** |
| 把 `README.md`／`LAUNCH.md` 改成中文 | 那兩份自 2026-08-27 起是**英文**（總覽 §3.8）。`CLAUDE.md` 與 `docs/` 才是繁體中文 |
| 把實例 id、帳號 id、bucket 名寫進任何要 commit 的檔 | 總覽 §7 鐵律 10。文件只寫**變數名**；實例 id 放不入版控的 `.env` |

---

## 4. 實作步驟

> 📌 **本 phase 沒有測試可以先紅**（做的是真機操作與文件）。
> 體例是：**指令 → 每個旗標的用途 → 預期輸出 → 做錯了怎麼退回 → 費用影響。**

> 📌 **底下每一節的結構都是「共用正文 ＋ 92-A／92-B 兩個變體」。**
> 只有三個地方真的不一樣（§4.2 的 AMI、§4.3 的機型與根碟、§4.5 的 `worker.env` 那一行
> 與 92-B 多出來的 GPU 兩關）；其餘**逐字相同**。

> ⏱️ **時間與費用預估：**
>
> | | **92-A（`t3.xlarge`）** | **92-B（`g4dn.xlarge`）** |
> |---|---|---|
> | §4.1〜§4.6 | 約 **30 分鐘**（第一次開機要裝 Ollama 並拉 7 GB 的 `gemma4:e2b`） | 同上 |
> | Demo 2 | 約 5 分鐘（看圖打 `ollama.com`，一張約 2 秒） | 約 5 分鐘（T4 上一張幾秒；**第一張**要先把模型載進 VRAM，久一些） |
> | Demo 2b | 約 5 分鐘（加上等**本機** gemma4 看圖的 64〜88 秒） | 不必重做（92-A 已驗） |
> | 機器總開機時間 | 約 **1 小時** | 約 **1 小時** |
> | 每小時 | **$0.2176** ＋ 公有 IPv4 **$0.005** | 約 **$0.71** ＋ 公有 IPv4 **$0.005** |
> | 這一整段的運算費 | 約 **$0.22** | 約 **$0.72** |
> | 忘了關一整天 | ≈ **$5.2** | ≈ **$17** |
> | 忘了關一個月 | ≈ **$160** | ≈ **$515** |
> | 關機（Stop）之後還在扣的 | **30 GB gp3 ≈ $2.9／月**（在 $5 Budget 內，所以 92-A 可以放心 Stop） | **80 GB gp3 ≈ $7.7／月**（單獨就超過 Budget → §4.9 拍板 Terminate） |
>
> （單價以 AWS 定價頁當天的數字為準，附錄有連結；東京 EBS gp3 約 $0.096／GB／月。）
> 帳號已升 **Paid**＝會扣卡。⚠️ 舊計畫的 `t4g.small` 忘記關一天只要 $0.65，
> 那個「還好啦」的直覺在這裡（尤其 92-B）**會出事**。

### 4.1 裝 `session-manager-plugin`（每台 Mac 一次）

- [ ] 安裝：

```bash
brew install --cask session-manager-plugin
session-manager-plugin --version
```

  預期：印出版本號（例如 `1.2.7xx.0`）。AWS 要求 **1.2.764.0 以上**，Homebrew 上的一定夠新。

  📌 **為什麼要它：** `aws ssm start-session` 不是普通的 API 呼叫——
  它要開一條互動式的雙向通道，AWS CLI 本身做不到，得靠這個外掛。
  沒裝的話錯誤訊息是
  `SessionManagerPlugin is not found. Please refer to SessionManager Documentation here: ...`。

  **做錯了怎麼退回：** `brew uninstall --cask session-manager-plugin`。零風險。
  （這個 cask 是社群維護的；AWS 官方文件只提供 `.pkg` 與 `.zip` 兩種安裝檔，跟 cask 裝出來的是同一個程式，功能一樣。）

### 4.2 查 AMI（92-A 與 92-B 各查各的）

> 📌 **AMI 是本 phase 兩段唯二真正不同的東西之一**（另一個是機型與根碟大小）。
> 兩個都是 AWS 維護的 SSM 公開參數，任何人都讀得到、不必特別權限、純查詢沒有副作用。

- [ ] **92-A：一般 AL2023（x86_64）**

```bash
AMI=$(aws ssm get-parameters --region "$AWS_REGION" \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)
echo "AMI=$AMI"
```

  預期：`AMI=ami-0123456789abcdef0`

  | 部分 | 用途 |
  |---|---|
  | `ami-amazon-linux-latest/al2023-…` | AWS 幫 Amazon Linux 2023 維護的「永遠指向最新版」參數。裡面**沒有** NVIDIA 驅動，也沒有 PyTorch 之類的東西——這正是我們要的：`t3.xlarge` 上沒有顯示卡，裝那些只是白佔空間 |
  | `kernel-default` | 用 AL2023 的預設核心（不是 `kernel-6.1` 那種釘版本的變體）。AWS 2026-08-17 起 default 核心是 6.18 |
  | **`x86_64`** | 要跟機型對上：`t3.xlarge` 是 x86_64。⚠️ 寫成 `arm64` 就得換機型（`t4g.xlarge`），但那樣**驗到的就不是 92-B 之後要用的那份 amd64 映像了**——本 phase 刻意兩段都用 x86 |
  | 根碟大小 | 這顆 AMI 的快照只有 **8 GB**，所以根碟寫多少都行；§4.3 寫 **30**（放得下 Ollama 約 2 GB ＋ 模型 7.2 GB ＋ 容器映像，關機也只 ≈ $2.9／月） |

- [ ] **92-B：Deep Learning Base OSS NVIDIA Driver GPU AMI（AL2023、x86_64）**

```bash
AMI=$(aws ssm get-parameters --region "$AWS_REGION" \
  --names /aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id \
  --query 'Parameters[0].Value' --output text)
echo "AMI=$AMI"
```

  預期：`AMI=ami-0123456789abcdef0`（跟 92-A 那顆**不是**同一個）

  | 部分 | 用途 |
  |---|---|
  | `deeplearning/ami/**x86_64**/…` | 架構那一段要跟機型對上：`g4dn.xlarge` 是 **x86_64**。想改用 `g5g.xlarge`（arm64）就把這一段換成 `arm64`（參數名其餘部分相同）——但 **Ollama 在 arm64 上的 CUDA 支援我們沒驗過**，不要在真機日當場換 |
  | `base-oss-nvidia-driver-gpu-…` | 「Base」＝只有驅動與容器工具，**沒有**塞 PyTorch／TensorFlow 那些幾十 GB 的框架（我們用不到）。「OSS driver」＝開源版 NVIDIA 驅動，T4 適用 |
  | `latest/ami-id` | 永遠指向最新版。查到的 id 跟上個月不一樣是**正常的**（AWS 會定期重出映像） |
  | 根碟大小 | ⚠️ **這顆 AMI 的根碟快照是 75 GB（arm64 版 65 GB）**，所以 §4.3 的 `VolumeSize` **不能小於它**——寫 30 會直接 `InvalidBlockDeviceMapping`（陷阱 15）。92-B 固定寫 **80** |

  📌 **為什麼 92-B 不能「只裝 Ollama、驅動會自己來」：**
  Ollama 官方 Linux 安裝是先裝程式，再叫你跑 `nvidia-smi` 確認驅動——**它不裝 NVIDIA kernel driver**。
  空白 Ubuntu／一般 AL2023 上只有硬體有 T4、系統裡還沒有 `nvidia.ko`，這時裝 Ollama 會**默默用 CPU**。
  Deep Learning GPU AMI 已經含驅動，才接近「裝了 Ollama 就用 GPU」。
  不要自己再裝 GRID／Gaming／第二份 CUDA（跟 AMI 打架）。Docker 跑 Ollama 才需要 NVIDIA Container Toolkit；
  本 phase 的 Ollama 跑 **host**，工人容器只是 `--network host` 打 `11434`，不必再裝 toolkit。

  ⚠️ **架構寫錯會怎樣：** 參數寫成 `arm64`、機型卻是 x86 ＝ AMI 與機型不相容，
  `run-instances` 當場報錯（這種算好的，大聲）。反過來機型對、**容器映像**架構不對的話，
  是 `docker run` 回 `exec format error`（陷阱 4）——那個訊息完全看不出跟架構有關。

  **做錯了怎麼退回：** 這兩條都是純查詢，沒有副作用，重跑就好。

### 4.3 開機器（★ 第一個真的花錢的指令）

> ⛔ **跑之前確認：** ① §2 的配額那一條對上了（**92-A 看 Standard `L-1216C47A` ≥ 4，本帳號 8，直接可以開**；
> **92-B 看 G and VT `L-DB2E81BA` 必須是 `APPROVED`、Value ＝ 4**）；
> ② 帳號內**沒有**別的 `personaldocai-worker`（§2 ⑦／⑩，同時只留一台）；
> ③ 92-B 之前已經把 92-A 那台 Terminate 了。
> 這一行下去就開始計費（92-A **$0.2176／小時**、92-B **$0.71／小時**）。

**一份指令，兩段只有三個變數不同：**

| 變數 | 92-A | 92-B |
|---|---|---|
| `INSTANCE_TYPE` | `t3.xlarge` | `g4dn.xlarge` |
| `AMI` | 一般 AL2023 x86_64（§4.2 變體 A） | Deep Learning Base GPU AMI（§4.2 變體 B） |
| `VOLUME_SIZE` | `30` | `80` |

其餘（SG、instance profile、user-data、公有 IP、IMDSv2 hop limit 2、不帶 `--key-name`、Name tag）
**兩段逐字相同**。

- [ ] **先設那三個變數**（照你這次要開的是哪一段選一組）：

```bash
# ── 92-A：CPU 機 ──
INSTANCE_TYPE=t3.xlarge
VOLUME_SIZE=30
# AMI 用 §4.2 變體 A 查到的那個

# ── 92-B：GPU 機（配額核准之後）──
# INSTANCE_TYPE=g4dn.xlarge
# VOLUME_SIZE=80
# AMI 用 §4.2 變體 B 查到的那個

echo "要開的是：$INSTANCE_TYPE，根碟 ${VOLUME_SIZE} GB，AMI=$AMI"
```

- [ ] 跑（**注意 `--user-data file://…` 讀的是 `deploy/ec2/user-data.sh` 的實檔**——
      它會裝 Docker、裝好 systemd 服務並 enable、裝 Ollama 並 `ollama pull gemma4:e2b`；
      **兩段共用同一份，一個字都不改**）：

```bash
INSTANCE_ID=$(aws ec2 run-instances --region "$AWS_REGION" \
  --image-id "$AMI" \
  --instance-type "$INSTANCE_TYPE" \
  --subnet-id "$SUBNET_ID" \
  --security-group-ids "$SG_ID" \
  --iam-instance-profile Name=personaldocai-worker-role \
  --associate-public-ip-address \
  --user-data file://deploy/ec2/user-data.sh \
  --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=${VOLUME_SIZE},VolumeType=gp3}" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]' \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2 \
  --query 'Instances[0].InstanceId' --output text)
echo "INSTANCE_ID=$INSTANCE_ID"
```

  ⚠️ **`--block-device-mappings` 這一行的引號從單引號換成雙引號**（原本是單引號的字面字串）——
  因為裡面要展開 `${VOLUME_SIZE}`。單引號在 shell 裡**不做任何展開**，
  用單引號的話會把 `${VOLUME_SIZE}` 這十四個字元原樣送給 AWS，得到一個看不懂的 `InvalidParameterValue`。
  其他兩個單引號的旗標（`--tag-specifications`）裡面沒有變數，維持單引號是對的。

  **每一個旗標：**

  | 旗標 | 用途 |
  |---|---|
  | `--image-id "$AMI"` | 用哪個出廠映像（§4.2：**92-A** 一般 AL2023、**92-B** Deep Learning Base GPU AMI） |
  | `--instance-type "$INSTANCE_TYPE"` | 機型。**92-A `t3.xlarge`** ＝ 4 vCPU／16 GiB／x86_64／沒有 GPU，吃 Standard 配額（本帳號 8，夠）；**92-B `g4dn.xlarge`** ＝ 帶 NVIDIA **T4**（16 GB VRAM）、4 vCPU／16 GB、x86_64，吃 **G and VT** 配額（`L-DB2E81BA` 必須 ≥4）。⚠️ 兩者**都是 x86_64**，所以拉的都是 ECR 那份 amd64 映像——92-A 驗過的就是 92-B 要用的那一份 |
  | `--subnet-id "$SUBNET_ID"` | 放在哪個子網（Phase 91 §4.1 查到的**公有**子網） |
  | `--security-group-ids "$SG_ID"` | 掛哪個防火牆（Phase 91 §4.2 建的，inbound 空、outbound 只有 443） |
  | `--iam-instance-profile Name=…` | 掛哪個 instance profile。**注意寫法是 `Name=<名字>`**（不是直接接名字），這是 AWS CLI 的 shorthand 語法 |
  | `--associate-public-ip-address` | 開機自動給一個公有 IP。機器**沒有公有 IP 就出不了網**（S3／SQS／ECR／SSM／ollama.com 全部不通）；我們的子網本來就會自動配，明寫是雙保險。⚠️ 公有 IPv4 **$0.005／小時**（2024-02-01 起），但只在 running 時算——Stop 之後自動釋放、不再計費 |
  | `--user-data file://deploy/ec2/user-data.sh` | 第一次開機要跑的腳本（裝 Docker、建 `/opt/personaldocai`、寫好 systemd 服務並 **enable 但不 start**、裝 Ollama 並拉模型）。**兩段共用同一份** |
  | `--block-device-mappings "…VolumeSize=${VOLUME_SIZE},VolumeType=gp3…"` | 根碟：**92-A 30 GB**、**92-B 80 GB**，都是 gp3。`/dev/xvda` 是 AL2023 的根碟裝置名。⚠️ **92-B 不能寫 30**：GPU AMI 的快照本身就 75 GB，比它小會直接 `InvalidBlockDeviceMapping`（陷阱 15）。⚠️ 這一顆**關機也要付**（92-A ≈ $2.9／月、92-B ≈ $7.7／月，§4.9） |
  | `--tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]'` | 給機器貼一個 `Name` 標籤，Console 上才看得懂它是誰。**兩段用同一個名字**，所以「同時只准有一台」那條檢查才管用 |
  | `--metadata-options HttpTokens=required,HttpPutResponseHopLimit=2` | `HttpTokens=required` ＝強制 **IMDSv2**（比較安全的那一版 metadata 服務，boto3 支援得很好）。`HttpPutResponseHopLimit=2` ＝**一定要寫**：工人跑在 Docker 容器裡，容器到宿主機多一跳；hop limit 停在 1 的話容器裡的 boto3 **拿不到 instance profile 的憑證**（症狀：工人 log 一直重複 `NoCredentialsError`／`Unable to locate credentials`，而機器本身的 `aws` 指令卻好好的）。AWS 官方文件明文「容器環境請設 2」；總覽 §10.2 追認項 O 定案（陷阱 12） |
  | `--query 'Instances[0].InstanceId'` | 只取新機器的 id |

  ⚠️ **不需要 `--count 1`**（預設就是 1）。
  ⚠️ **不要加 `--key-name`**：那是 SSH 金鑰，我們**不開 SSH**（design6 D11）。
  ⚠️ **不要加 `--network-interfaces`**：那個旗標一旦出現，`--subnet-id`／`--security-group-ids`／
  `--associate-public-ip-address` 三個就必須改寫到它裡面去，否則會衝突。
  我們用的「三個都在最上層」正是 AWS 官方文件的範例寫法。

  預期：`INSTANCE_ID=i-0123456789abcdef0`

- [ ] **如果失敗了：`VcpuLimitExceeded`**

  訊息長這樣：
  `You have requested more vCPU capacity than your current vCPU limit of 0 allows for the
  instance bucket that the specified instance type belongs to.`

  **這不是打錯字，是配額。先看是哪一條**（兩條完全不同，訊息長得一樣）：

  | 你在開 | 吃哪條配額 | 現況 | 怎麼辦 |
  |---|---|---|---|
  | **92-A `t3.xlarge`** | Standard `L-1216C47A` | 本帳號 **8**，理論上不會撞 | 真的撞到＝帳號裡還有別的機器在跑（§2 ⑦ 那條 `describe-instances` 看一下），或你打錯機型 |
  | **92-B `g4dn.xlarge`** | G and VT `L-DB2E81BA` | 2026-09-03 是 **0**，申請中 | 等 `APPROVED`（§2 ②）。**重試沒有用**——配額不會因為多試幾次就變大。**不要重送申請** |

  ⚠️ **92-B 的申請被拒（`DENIED`）怎麼辦：** 那就沒有 GPU 這條路了。**但 92-A 已經把流程全部驗完、
  ★G3 也已經過了，93〜95 照樣往下走**——這正是拆兩段的意義。
  這時是**產品負責人要裁決**的岔路：① 永久維持 `WORKER_VLM_BACKEND=cloud`（CPU 機 ＋ `ollama.com`，
  也就是 92-A 那個組合，行為完全合格）；或 ② 整條 EC2 路先擱著，維持 `CLOUD_ROUTE=off`。
  **不要**自己去改機型「試試看小一點的 GPU」——G 系列共用同一條配額，`g5g`／`g6` 一樣被擋。

- [ ] **如果失敗了：`InvalidParameterValue … Invalid IAM Instance Profile name`**

  這是 **instance profile 還沒傳播到 EC2** 那一側（Phase 91 §7 陷阱 2 講的那個）。
  **名字完全正確**，只是還沒傳到。等 15 秒再試，最多三次：

```bash
for i in 1 2 3; do
  INSTANCE_ID=$(aws ec2 run-instances --region "$AWS_REGION" \
    --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
    --subnet-id "$SUBNET_ID" --security-group-ids "$SG_ID" \
    --iam-instance-profile Name=personaldocai-worker-role --associate-public-ip-address \
    --user-data file://deploy/ec2/user-data.sh \
    --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=${VOLUME_SIZE},VolumeType=gp3}" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]' \
    --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2 \
    --query 'Instances[0].InstanceId' --output text 2>/tmp/p92-run-instances.err) && break
  echo "第 $i 次失敗：$(head -c 300 /tmp/p92-run-instances.err)"
  grep -q "Invalid IAM Instance Profile" /tmp/p92-run-instances.err || break   # 別種錯誤：不要盲目重試，先看訊息
  echo "（instance profile 還沒傳播到 EC2 那一側，等 15 秒再試…）"; sleep 15
done
echo "INSTANCE_ID=$INSTANCE_ID"
```

  ⚠️ **重試之前先確認上一次真的沒開成機器**（不然會開出兩台，兩台都在收同一條佇列、也都在花錢）：

```bash
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=tag:Name,Values=personaldocai-worker \
            Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].InstanceId' --output text
```

  預期：**恰好一個** id。看到兩個就把多的那台 `terminate`
  （**這是「還要再用的機器不准 terminate」那條規則的第三種例外**：一台剛開出來、什麼都還沒放的多餘機器）：
  `aws ec2 terminate-instances --instance-ids <多的那個> --region "$AWS_REGION"`

  **費用開始計時了。** 從這一刻起 **92-A 約 $0.2176／小時**（**92-B 約 $0.71／小時**），
  ＋公有 IPv4 $0.005／小時；EBS 92-A 30 GB ≈ $2.9／月、92-B 80 GB ≈ $7.7／月
  （Stop 之後運算費停、**EBS 繼續**）。⚠️ 一整天忘了關：92-A ≈ $5.2、92-B ≈ $17。

### 4.4 等機器起來、等 SSM 上線、**等 user-data 跑完**

> 📌 **這一節 92-A 與 92-B 逐字相同**（跑的是同一份 user-data）。

- [ ] 等機器進入 `running`：

```bash
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"
echo "running 了"
```

  這個指令會**卡住不動**直到成功（預設每 15 秒問一次、最多 40 次 ＝ 約 10 分鐘）。
  正常情況 30〜60 秒就回來。

- [ ] **等 SSM agent 上線**（這一步比上一步重要——`running` 只代表「電源開了」，
      不代表「你進得去」）：

```bash
for i in $(seq 1 20); do
  ONLINE=$(aws ssm describe-instance-information --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null)
  echo "第 $i 次：PingStatus=$ONLINE"
  [ "$ONLINE" = "Online" ] && break
  sleep 15
done
```

  預期：前幾次印 `None`（還沒上線），大約 **1〜3 分鐘**後印 `Online` 並跳出迴圈。

  | 部分 | 用途 |
  |---|---|
  | `--filters "Key=InstanceIds,Values=$INSTANCE_ID"` | 只問這一台。⚠️ **整串要用引號包起來**（`Key=…,Values=…` 中間有逗號，不包的話 shell 會拆錯） |
  | `PingStatus` | SSM 服務眼中這台機器的狀態。`Online` ＝ agent 有在跟 SSM 講話 ＝ 你進得去 |

  ⚠️ **超過 5 分鐘還是 `None`**，就是 Phase 91 §7 陷阱 3 那兩個原因之一：
  ① IAM role 沒掛 `AmazonSSMManagedInstanceCore`；② SG 的 outbound 443 沒開對。
  回 Phase 91 §6 的第 2、8 條驗一次。
  ⚠️ **不要因為進不去就跑去開 inbound 22**——那違反 design6 §0 禁止第 3 條，而且也修不好
  （問題在**出站**，不在進站）。真的救不回來就 `terminate` 這台、修好 IAM／SG，再從 §4.3 重開一台。

- [ ] **再等 user-data 跑完**（★ 第一次開機要裝 Ollama 並拉 7 GB 的模型，
      **通常 5〜10 分鐘**，比機器本身開機久得多）。從 Mac 這邊用 SSM 一句話看進度即可，
      不必開 session：

```bash
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["tail -n 5 /var/log/cloud-init-output.log"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
  --query 'StandardOutputContent' --output text
```

  預期最後一行（**逐字以 `deploy/ec2/user-data.sh` 的最後那個 `echo` 為準**）：
  `user-data 完成：personaldocai-worker 已 enable（尚未 start，等 worker.env）；docker 與 ollama 已裝，模型抓沒抓成看上面那一行`

  還在跑的時候會看到 `ollama pull` 的進度（一層一層下載，總共約 7 GB）。
  **還沒看到「user-data 完成」就先不要往下做。**

  📌 **92-A 也要等這一段跑完，即使 CPU 機根本不用那顆模型。** 理由：systemd unit 的
  `ExecStartPre` 會去問 `127.0.0.1:11434/api/tags`，Ollama 沒起來就不讓工人開工（最多等 120 秒、
  失敗就 `Restart=always` 十秒後再試）。所以 **92-A 上 Ollama 是「閒著應門」的角色**——
  它必須活著，但不必真的看圖。
  ⚠️ 那顆 7.2 GB 的模型在 92-A 上只是躺在碟上（`WORKER_VLM_BACKEND=cloud` ＝看圖打 `ollama.com`）。
  這是刻意的：**不改 user-data、不改 unit**，兩段共用同一份，才不會留下「92-A 專用的過渡版本」。
  想在同一台試試看 CPU 推論的話，見 §4.5 最後那個選配小節。

  ⚠️ **看到這一行就是 §4.3 的根碟旗標漏了**：
  `根碟只剩 N GB，放不下 gemma4:e2b（7.2 GB）——跳過 ollama pull；請用 30 GB 根碟重開這台`
  ——user-data 在拉模型前會先看剩多少空間（一般 AL2023 AMI 預設只有 8 GiB，
  忘了帶 `--block-device-mappings` 就會落到這裡）。它**故意只跳過拉模型、不中止腳本**，
  所以機器看起來一切正常。修法是 `terminate` 這台、照 §4.3 帶著 `VolumeSize` 重開一台。

  ⚠️ **超過 20 分鐘還沒完成**：多半是網路慢或 `ollama pull` 卡住。
  進機器 `sudo cat /var/log/cloud-init-output.log` 從頭看（user-data 有 `set -x`，
  每一行都印得出來）。模型沒拉完可以自己補一次：`sudo ollama pull gemma4:e2b`。
  （user-data 裡那條 `ollama pull` 是**非致命**的——失敗只會在 log 留一行，
  unit 檔與 enable 早就在它之前裝好了。）

### 4.5 進機器放 `worker.env`，把工人跑起來

> 📌 **這一節 92-A 與 92-B 只差兩件事**：`worker.env` 裡 `WORKER_VLM_BACKEND` 那一組值，
> 以及 92-B 多出來的「GPU 兩關」。其餘逐字相同。

- [ ] **用 Session Manager 進去**（不是 SSH）：

```bash
aws ssm start-session --target "$INSTANCE_ID" --region "$AWS_REGION"
```

  預期：

```text
Starting session with SessionId: personaldocai-admin-0123456789abcdef0
sh-5.2$
```

  你現在在那台機器裡面了（身分是 `ssm-user`，不是 root，所以下面要用 `sudo`）。
  SessionId 開頭是**你打 `aws` 指令用的 IAM 使用者名**——是 `personaldocai-admin` 才對；
  看到 `personaldocai-mac-…` ＝ 你的 shell 還拿著 `.env` 那把 key（回 §2 的 `unset`）。

- [ ] **先關掉這個 shell 的歷史紀錄**（在機器裡面；等一下要打的 `tee` 指令會帶佇列 URL、bucket 名，
      **92-A 還會帶 `OLLAMA_API_KEY`**——bash 預設會把整段、連 heredoc 的內容
      一起寫進 `~/.bash_history`）：

```bash
unset HISTFILE
```

  這一行之後，本次 session 打的東西**一個字都不會落地**（只對這一次 session 有效，離開就沒了）。

- [ ] **先確認 user-data 真的跑完了**（在機器裡面）：

```bash
sudo tail -5 /var/log/cloud-init-output.log
systemctl is-enabled personaldocai-worker
docker --version
systemctl is-active ollama
curl -s http://127.0.0.1:11434/api/tags | head -c 300
```

  預期：log 最後一行是
  `user-data 完成：personaldocai-worker 已 enable（尚未 start，等 worker.env）；docker 與 ollama 已裝，模型抓沒抓成看上面那一行`；
  `is-enabled` 印 `enabled`；`docker --version` 印版本號；
  `is-active ollama` 印 `active`；最後那條 `curl` 回一段 JSON（`{"models":[…]}`）。

  📌 **最後兩條在 92-A 上也要過**——unit 的 `ExecStartPre` 會等這個埠，Ollama 沒活著工人就不會啟動
  （即使 92-A 根本不用它看圖）。連線被拒 ＝ `sudo systemctl status ollama` 看原因，
  沒裝成功就補一次 `curl -fsSL https://ollama.com/install.sh | sh` ＋ `sudo systemctl enable --now ollama`。

  任何一條不對 → `sudo cat /var/log/cloud-init-output.log` 從頭看
  （user-data 有 `set -x`，每一行都印得出來，很容易找到卡在哪）。

- [ ] **★（只有 92-B 要做）再確認「GPU 與模型都到位」**（**先驗這個再啟動工人**，
      不然錯誤會以「看不懂」的形式安靜出現）：

```bash
nvidia-smi -L                                   # ① 看得到顯示卡
ollama list                                     # ② 模型下載好了
```

  預期：
  ① `GPU 0: Tesla T4 (UUID: GPU-…)`
     ——沒有輸出／`command not found` ＝ **AMI 選錯了**（用到沒有驅動的一般 AL2023）。
     這時 Ollama 會退回 CPU：能跑，但一張圖好幾分鐘，而且**不報錯**。要修只能重開一台（§4.2 變體 B）。
  ② 清單裡有 **`gemma4:e2b`**（Linux 沒有 Mac 的 `-mlx` 標籤）。
     沒有就 `sudo ollama pull gemma4:e2b` 補拉（約 7 GB、幾分鐘）。

  📌 **92-A 上 `nvidia-smi` 印 `command not found` 是正常的**（`t3.xlarge` 沒有顯示卡），
  不要以為機器壞了。92-A 的工人看圖打 `ollama.com`，跟這台機器有沒有 GPU 無關。

- [ ] **建 `/opt/personaldocai/worker.env`**（★ 這是唯一一次要把設定與機密打進機器）：

  在機器裡面執行下面這一段。`sudo tee` 會把接下來輸入的內容寫進那個檔，
  **最後一行單獨打 `EOF` 再按 Enter** 才會結束。**兩段的模板只差最後五行**：

```bash
# ── 92-A（CPU 機，看圖打 ollama.com）──
sudo tee /opt/personaldocai/worker.env > /dev/null <<'EOF'
AWS_REGION=
ECR_REGISTRY=
ECR_IMAGE=
S3_BUCKET=
SQS_JOBS_QUEUE_URL=
SQS_RESULTS_QUEUE_URL=
WORKER_VLM_BACKEND=cloud
OLLAMA_BASE_URL=
VLM_MODEL=
OLLAMA_API_KEY=
OLLAMA_CLOUD_VLM_MODEL=
EOF
sudo chmod 600 /opt/personaldocai/worker.env
sudo ls -l /opt/personaldocai/worker.env
```

```bash
# ── 92-B（GPU 機，看圖打這台機器自己的 Ollama）──
sudo tee /opt/personaldocai/worker.env > /dev/null <<'EOF'
AWS_REGION=
ECR_REGISTRY=
ECR_IMAGE=
S3_BUCKET=
SQS_JOBS_QUEUE_URL=
SQS_RESULTS_QUEUE_URL=
WORKER_VLM_BACKEND=local
OLLAMA_BASE_URL=http://127.0.0.1:11434
VLM_MODEL=gemma4:e2b
OLLAMA_API_KEY=
OLLAMA_CLOUD_VLM_MODEL=
EOF
sudo chmod 600 /opt/personaldocai/worker.env
sudo ls -l /opt/personaldocai/worker.env
```

  ⚠️ **變數名與順序以 `deploy/ec2/worker.env.example` 的實檔為準**（那份檔的註解寫得更細）。
  ⚠️ **上面沒有值的那幾行，等號後面要填上真值**——本文件**只寫變數名，永遠不寫值**
  （總覽 §7 鐵律 10）。值從哪裡來：

  | 變數 | 值從哪裡來 |
  |---|---|
  | `AWS_REGION` | 固定 `ap-northeast-1`（總覽 §2.8：全部東京）。⚠️ **這一行不准留空**：`app/core/config.py` 雖然寫成 `os.getenv("AWS_REGION") or "ap-northeast-1"`（空值也會落到預設，所以工人程式本身不會壞），但 **unit 的 `ExecStartPre` 是由 systemd 代入 `${AWS_REGION}` 去登入 ECR 的**，systemd 那一半**吃不到程式的預設**——留空的話那一行會變成 `aws ecr get-login-password --region `（空字串）而失敗，服務起不來 |
  | `ECR_REGISTRY` | Phase 91 §4.6 的 `$ECR_REGISTRY`（長相 `<12碼帳號>.dkr.ecr.ap-northeast-1.amazonaws.com`） |
  | `ECR_IMAGE` | Phase 91 §4.6 的 `$ECR_URI`（上面那串再接 `/personaldocai-worker`；**不含 `:tag`**——unit 檔自己接 `:latest`） |
  | `S3_BUCKET`／兩個 `SQS_*_QUEUE_URL` | 本機 `.env` 裡的同名變數（Phase 84／85 填的） |
  | **`WORKER_VLM_BACKEND`** | **92-A 填 `cloud`、92-B 填 `local`**。⚠️ 打錯字（例如 `gpu`）工人會**當場 `SystemExit` 退出**，不會安靜地退回某一種；`Restart=always` 會讓它每 10 秒重試一次，journal 上一行大寫的 `ERROR` 說得很清楚 |
  | **`OLLAMA_API_KEY`**／**`OLLAMA_CLOUD_VLM_MODEL`** | **92-A 必填**（從本機 `.env` 抄同名的兩個值過來）。⚠️ `OLLAMA_CLOUD_VLM_MODEL` 留空**不會**退回 `VLM_MODEL`——工人啟動時就會檢查、缺了直接大聲退出。**92-B 可以留空**（不打 `ollama.com`） |
  | **`OLLAMA_BASE_URL`**／**`VLM_MODEL`** | **92-B 必填**：固定 `http://127.0.0.1:11434` 與 `gemma4:e2b`。這裡的 `127.0.0.1` 指的是**那台 EC2 自己**——unit 的 `docker run` 帶 `--network host`，容器與 host 共用網路命名空間。`VLM_MODEL` 要與 `deploy/ec2/user-data.sh` 開頭那個 `VLM_MODEL` 一模一樣，⚠️ **不要**寫成 Mac 上的 `gemma4:e2b-mlx`（Apple Silicon 專用標籤，Linux 上不存在）。**92-A 可以留空**（`cloud` 模式不讀這兩個） |

  💡 **怎麼在 Mac 上先把十一行組好再貼進去**（避免在機器裡一個一個打錯）：
  在**另一個 Mac 終端機視窗**跑下面這段，它會把十一行印在螢幕上，你複製之後貼進 Session Manager：

```bash
# ── 92-A 版（會印出 OLLAMA_API_KEY，★ 螢幕上有機密）──
cd /Users/linjunting/personalDocAI && set -a; . ./.env; set +a
. /tmp/p91-vars.sh
printf 'AWS_REGION=%s\nECR_REGISTRY=%s\nECR_IMAGE=%s\nS3_BUCKET=%s\nSQS_JOBS_QUEUE_URL=%s\nSQS_RESULTS_QUEUE_URL=%s\nWORKER_VLM_BACKEND=cloud\nOLLAMA_BASE_URL=\nVLM_MODEL=\nOLLAMA_API_KEY=%s\nOLLAMA_CLOUD_VLM_MODEL=%s\n' \
  "$AWS_REGION" "$ECR_REGISTRY" "$ECR_URI" "$S3_BUCKET" \
  "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL" \
  "$OLLAMA_API_KEY" "$OLLAMA_CLOUD_VLM_MODEL"
```

```bash
# ── 92-B 版（後五行是固定值，所以輸出裡沒有任何機密）──
cd /Users/linjunting/personalDocAI && set -a; . ./.env; set +a
. /tmp/p91-vars.sh
printf 'AWS_REGION=%s\nECR_REGISTRY=%s\nECR_IMAGE=%s\nS3_BUCKET=%s\nSQS_JOBS_QUEUE_URL=%s\nSQS_RESULTS_QUEUE_URL=%s\nWORKER_VLM_BACKEND=local\nOLLAMA_BASE_URL=http://127.0.0.1:11434\nVLM_MODEL=gemma4:e2b\nOLLAMA_API_KEY=\nOLLAMA_CLOUD_VLM_MODEL=\n' \
  "$AWS_REGION" "$ECR_REGISTRY" "$ECR_URI" "$S3_BUCKET" \
  "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"
```

  ⚠️ **92-A 那一版的輸出裡有 `OLLAMA_API_KEY`**：貼完把視窗關掉（或 `clear`），
  **不要截圖、不要貼進任何文件或 commit**。
  ⛔ **這個檔裡沒有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`**——EC2 用 instance profile
  （Phase 91 掛的），boto3 自己去機器的 metadata 服務拿臨時憑證；在 EC2 上放長期金鑰
  多此一舉而且更危險。⛔ **也沒有 `AWS_ENDPOINT_URL`**（那只用在 pytest 的死埠安全網）。
  ⛔ **也沒有 `WORKER_VERSION`**（它由映像的 `ENV` 帶進來；填了等於把「跑的是哪一版」這個證據弄假）。

  `sudo ls -l` 預期：`-rw------- 1 root root … /opt/personaldocai/worker.env`
  ——**開頭一定要是 `-rw-------`**（600 ＝ 只有 root 讀得到）。

- [ ] **把服務跑起來**（在機器裡面）：

```bash
sudo systemctl start personaldocai-worker
sleep 20
systemctl status personaldocai-worker --no-pager
```

  預期：`Active: active (running)`，而且上面幾行看得到
  `docker login` 與 `docker pull` 兩個 `ExecStartPre` 都成功了。
  看到 `Active: activating (start-pre)` ＝ **還在做 `ExecStartPre`**，兩種可能：
  ① 在等 Ollama 回應（那條 `curl /api/tags` 迴圈，最多 120 秒）；
  ② 在拉映像（第一次要把整份 **amd64** 映像從 ECR 抓下來，同區域通常十幾秒到一分鐘）。
  再等 30〜60 秒重跑 `systemctl status` 就好。

  出現 `Active: activating (auto-restart)` 或 `failed` → 看完整 log：

```bash
sudo journalctl -u personaldocai-worker -n 50 --no-pager
```

  最常見的幾種：
  ① `EnvironmentFile` 找不到 → `worker.env` 的路徑或檔名打錯，`ls /opt/personaldocai/` 對一次。
  ② `docker login` 失敗（`no basic auth credentials`）→ IAM role 少了 ECR 那三個動作，回 Phase 91 §4.4。
  ③ `docker pull` 失敗（`repository does not exist`）→ `ECR_IMAGE` 打錯（少了 `/personaldocai-worker`，
     或多帶了 `:latest`）。
  ④ `start operation timed out`／`Start-pre operation timed out` → 三條 `ExecStartPre`
     （ECR 登入、等 Ollama 最多 120 秒、`docker pull`）**串起來算同一個啟動逾時**。
     unit 檔已經寫了 `TimeoutStartSec=600`（systemd 預設只有 90 秒，那樣「等 120 秒」永遠等不滿），
     所以撞到 600 秒代表真的很慢。已經拉下來的 layer 不會丟，
     `sudo systemctl start personaldocai-worker` 再跑一次就會接著拉完。
  ⑤ `ollama 120 秒內沒起來`（unit 的 `ExecStartPre` 印的）→ host 上的 Ollama 沒活著。
     `systemctl status ollama` 看它；沒裝成功就自己補一次
     `curl -fsSL https://ollama.com/install.sh | sh` 再 `sudo systemctl enable --now ollama`。
     ⚠️ 這條**刻意讓它失敗**（而不是硬等下去）：`Restart=always` 十秒後會再試一次，
     journal 上看得到「等了幾輪」，比工人啟動成功卻每張圖都看不懂誠實得多。
     ⚠️ **92-A 也會撞到這一條**（CPU 機一樣要讓 Ollama 活著應門）。
  ⑥ `WORKER_VLM_BACKEND 只認 cloud／local，讀到的是：'…'` → 那一行打錯字了，改完 `restart`。
  ⑦ 少了 `OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL`（`cloud` 模式）或 `OLLAMA_BASE_URL`／`VLM_MODEL`
     （`local` 模式）→ 工人啟動時就會大聲退出，訊息直接寫缺哪一個。
  ⑧ `exec format error` → 拉到的是 arm64 那一份映像（兩段的機器都是 x86）。
     回 §2 ⑤ 用 `docker manifest inspect` 看 `latest` 是不是多架構（陷阱 4）。

- [ ] **確認跑的是「你剛才推上去的那一版」，而且看圖後端是你要的那一個**
      （總覽 §10 追認項 e、design6 D16）：

```bash
sudo docker logs cloud-worker 2>&1 | head -n 5
```

  預期第一行：

```text
# 92-A
INFO:     cloud_worker 啟動 version=<7 碼 sha> region=ap-northeast-1 bucket=personaldocai-mailbox-xxxxxx vlm=cloud model=<雲端模型名>
# 92-B
INFO:     cloud_worker 啟動 version=<7 碼 sha> region=ap-northeast-1 bucket=personaldocai-mailbox-xxxxxx vlm=local model=gemma4:e2b
```

  三件事一起看：
  - `version=` 後面那一串必須等於**建那個映像時**用的 `git rev-parse --short HEAD`。
    印出 `version=dev` ＝ 推上去的映像是「沒帶 `--build-arg GIT_SHA`」建的，回 Phase 90 §4.3 重建再重推。
    ⚠️ 本輪的程式改動若還沒 commit，映像會是用 HEAD 的 sha 建的、ECR 另有一個 `<sha>-dirty` tag
    ——那時 `version=` 對得上 HEAD 是正常的，不要以為是拉錯映像。
  - **`vlm=`** ＝ 工人吃到的 `WORKER_VLM_BACKEND`。**92-A 要是 `cloud`、92-B 要是 `local`**。
    92-B 印出 `vlm=cloud` ＝ `worker.env` 那一行漏了或打錯（預設是 `cloud`），**GPU 就白開了**；
    92-A 印出 `vlm=local` ＝ 那台 CPU 機會用自己的 CPU 硬看圖，一張好幾分鐘（見下面的選配小節）。
    改好 `worker.env` → `sudo systemctl restart personaldocai-worker`。
  - **`model=`** ＝ 那顆模型名。92-B 要跟 `ollama list` 裡那顆對得上（對不上例如 `-mlx` ＝ 每張圖 404 三次）；
    92-A 是雲端的模型名（去 ollama.com 確認，**不要照抄本機 `.env` 的 `VLM_MODEL`**）。

- [ ] **（只有 92-B，Demo 2 的時候會再看一次）順手確認 GPU 真的在做事**：工人剛啟動時還沒看過圖，
      所以現在 `nvidia-smi` 的 VRAM 多半是空的——**這是正常的**。
      Ollama 是「有人問才載模型」，所以要等 §4.7 的 Demo 2 送出第一張圖之後，
      `nvidia-smi` 才會看到 `ollama` 行程佔著 VRAM、`ollama ps` 才列得出模型。

- [ ] **離開機器**：在機器裡打 `exit`（回到 Mac 的 shell）。

#### ★ 對照表：三段各自要「手抄」與「手填」什麼

> 📌 **為什麼要有這張表：** 這整個 phase 唯一會出錯的地方，就是「哪些字要用手打進哪一台機器」。
> 值有兩種：**機密**（不准出現在任何文件、任何 commit、任何截圖）與**非機密**（實例 id 之類，
> 也只放不入版控的 `.env`）。下面三段各自要動的東西**只有這些**，其他一律照抄不動。
>
> ⚠️ 本表**只寫變數名，永遠不寫值**（總覽 §7 鐵律 10）。

```text
  兩個檔案，不要搞混：
    /opt/personaldocai/worker.env   ← 在 EC2 上（用 SSM 進去手打，chmod 600）。工人讀它
    <專案根目錄>/.env               ← 在這台 Mac 上。本機的 app 與 Celery worker 讀它
  兩邊沒有任何同步機制，全部靠人。
```

| | **① 92-A（現在做）：CPU 機、先 `cloud`** | **② 92-A 選配：同一台改 `local`** | **③ 92-B：換 GPU 機、仍是 `local`** |
|---|---|---|---|
| **要手抄的機密** | **`OLLAMA_API_KEY`**（從 Mac 的 `.env` 抄 → EC2 的 `worker.env`，用 SSM 進去貼） | **沒有** | **沒有** |
| **EC2 的 `worker.env` 要動哪幾行** | 整份第一次建（十一行，§4.5 的 92-A 模板）：`WORKER_VLM_BACKEND=cloud` ＋ `OLLAMA_API_KEY` ＋ `OLLAMA_CLOUD_VLM_MODEL` | **同一份檔改五行**（SSM 進去改）：`WORKER_VLM_BACKEND=local`、`OLLAMA_BASE_URL=http://127.0.0.1:11434`、`VLM_MODEL=gemma4:e2b`（⚠️ **不要 `-mlx`**）、`OLLAMA_API_KEY=`（留空或維持原值都行，`local` 不會打 `ollama.com`）、`OLLAMA_CLOUD_VLM_MODEL=`（可留空）。⛔ **`AWS_REGION`／`ECR_REGISTRY`／`ECR_IMAGE`／`S3_BUCKET`／兩個 `SQS_*_QUEUE_URL` 一行都不要動** | 新機器上**整份再貼一次**（§4.5 的 92-B 模板）：`WORKER_VLM_BACKEND=local`、`OLLAMA_BASE_URL`／`VLM_MODEL` 同 ②、`OLLAMA_API_KEY` 留空；`AWS_REGION`／`ECR_*`／`S3_BUCKET`／`SQS_*` 那幾行照抄 |
| **Mac `.env` 要手填的非機密** | 開機後拿到的 **instance id → `EC2_WORKER_INSTANCE_ID`**；`CLOUD_ROUTE=ec2`；`CLOUD_RESULT_TIMEOUT_SECONDS=300` | instance id 與 `CLOUD_ROUTE` **都不動**；但 **`CLOUD_RESULT_TIMEOUT_SECONDS` 暫調 `900`**，做完**改回 `300`** | **新的** instance id → `EC2_WORKER_INSTANCE_ID`（舊的那台已 terminate）；`CLOUD_ROUTE` 不動 |
| **要 restart 什麼** | Mac：`restart worker`（§4.6） | **Mac：`restart worker` 兩次**（調 900 一次、改回 300 一次）；**機器上：`sudo systemctl restart personaldocai-worker`** | Mac：`restart worker`；機器上不必（第一次 `systemctl start`） |
| **啟動行要看到** | `vlm=cloud model=<雲端模型名>` | `vlm=local model=gemma4:e2b` | `vlm=local model=gemma4:e2b` |
| **驗完要做的收尾** | Stop 機器（§4.9）、頁首開關撥回本機 | **`worker.env` 改回 `cloud` 那一組並 restart**；Mac `.env` 改回 `300` 並 restart | Terminate 機器（§4.9 選項 B） |

⚠️ **② 那個 `CLOUD_RESULT_TIMEOUT_SECONDS` 暫調 900 是必做的，不是建議**——理由與完整步驟見下面那一小節。

#### 選配（只在 92-A）：同一台切 `local`，試試看 CPU 推論有多慢

> 📌 **可做可不做。** 它不是驗收條件，也不影響 ★G3——做它純粹是想知道
> 「沒有 GPU 的機器自己看圖到底要多久」，以及讓 92-B 之後有個對照數字。
> 不做的話直接跳到 §4.6。

⛔ **要做的話，這三步一步都不能省：**

1. **先把 Mac `.env` 的 `CLOUD_RESULT_TIMEOUT_SECONDS` 從 300 暫時調成 900**，並重啟本機 worker：

```bash
# 在 Mac 上：把 .env 裡那一行改成 CLOUD_RESULT_TIMEOUT_SECONDS=900
docker compose -f compose.yaml -f compose.dev.yaml restart worker
docker compose exec worker python -c "from app.core import config; print(config.CLOUD_RESULT_TIMEOUT_SECONDS)"
# 預期：900
```

2. 在機器裡把 `worker.env` 的那幾行改成 `local` 那一組（`WORKER_VLM_BACKEND=local`、
   `OLLAMA_BASE_URL=http://127.0.0.1:11434`、`VLM_MODEL=gemma4:e2b`——⚠️ **不要 `-mlx`**；
   `OLLAMA_API_KEY` 與 `OLLAMA_CLOUD_VLM_MODEL` 留空或維持原值都行，`local` 不會用到它們；
   ⛔ `AWS_REGION`／`ECR_*`／`S3_BUCKET`／`SQS_*` **一行都不要動**），
   `sudo systemctl restart personaldocai-worker`，確認啟動行變成 `vlm=local model=gemma4:e2b`。
   然後傳**一張**非敏感的圖，看工人 log 的 `AI 結束 kind=vlm backend=local … elapsed_s=`。
   ⚠️ **只用單圖，不要拿多頁 PDF 來試。** 工人**沒有 SQS 心跳**（不會中途延長 visibility），
   一則訊息超過 jobs 佇列的 **900 秒** Visibility Timeout 就會被重投給自己，變成同一份工作做兩次
   ——CPU 逐頁看圖很容易超過。這一步是在驗「`local` 這條路的契約走得通」，**不是在驗速度**。

3. **做完一定要改回去**：機器上的 `worker.env` 改回 `cloud` 那一組並 `restart`；
   Mac 的 `.env` 把 `CLOUD_RESULT_TIMEOUT_SECONDS` **改回 300** 並再 `restart worker` 一次。

⚠️ **為什麼一定要先把逾時調成 900：** 本機送出之後最多只等 `CLOUD_RESULT_TIMEOUT_SECONDS`
（預設 **300 秒**）。`t3.xlarge` 沒有 GPU，`gemma4:e2b` 看一張圖**大概率超過 5 分鐘**，於是會發生：

```text
  本機：等 300 秒 → 逾時 → fallback=local reason=result_timeout → 自己看一次圖 → 照片入庫（結果是對的）
  工人：又過了兩分鐘才看完 → 把 result.json 放回 S3 → **沒有人會來拿** → 變成孤兒物件
```

照片不會不見，但 S3 會留下一份沒人要的 `result.json`（要靠 2 天的 Lifecycle 才清掉），
而且你根本沒驗到「CPU 推論走完全程」這件事。
**900 秒是對齊 jobs 佇列的 Visibility Timeout（900）**——比它更長沒有意義（訊息會回到佇列被重送）。
📌 這個坑 2026-09-03 在 Mac 上實際踩過一次（本機先 fallback、工人稍後放好的 `result.json` 成孤兒）。

⚠️ **這是「六件不要做」④ 的唯一例外**：`60`／`300` 對日常仍然是總覽 §2.4.2 的契約值。
測試期暫時覆蓋、做完**當場改回**，不要留在 `.env` 裡過夜。

### 4.6 本機切到 `ec2` 模式

- [ ] 編輯 `.env`，把這三行改成／加上（**`EC2_WORKER_INSTANCE_ID` 填 §4.3 那個 id**）：

```ini
EC2_WORKER_INSTANCE_ID=i-0123456789abcdef0
CLOUD_ROUTE=ec2
CLOUD_RESULT_TIMEOUT_SECONDS=300
```

  📌 **三個值分別在做什麼：**
  - `EC2_WORKER_INSTANCE_ID`：`Ec2Probe` 要問「哪一台」。空的話探測直接回 `False`（零 API 呼叫）。
  - `CLOUD_ROUTE=ec2`：從「假設遠端開著」（`assume`）改成「**真的去問**」。
    這是總覽 §10 追認項 l：`assume` 只給階段丁與除錯，戊之後日常用 `ec2`。
  - `CLOUD_RESULT_TIMEOUT_SECONDS=300`：送出後最多等 5 分鐘（總覽 §2.4.2 的預設值，不要改）。

- [ ] **重啟本機 worker**（`app` 不必動——它不看這三個變數）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

  ⛔ **這一步不是可選的，有兩個各自獨立的理由：**
  ① `app/core/config.py` 只在**行程啟動時**讀一次 `.env`（`load_dotenv()`），改檔不會自動生效。
  ② Phase 89 把 `ec2` 模式的 `CloudRoute` 做成 `dependencies._ec2_cloud_route()`（`@lru_cache`）
     ——**整個行程共用同一顆物件**（這是刻意的：探測的 60 秒快取要共用才有意義）。
     那顆物件在**第一次被建立時**就把 instance id 與模式吃進去了，之後再怎麼改 `.env`
     都不會換掉它。**只有重啟行程才會清掉那個 `lru_cache`。**

  症狀長什麼樣：`.env` 明明已經是 `ec2`，worker 卻還在用舊的設定
  （例如仍然當作 `assume`、或仍然拿著舊的 instance id 去探測），
  **而且完全不會報錯**——這是典型的安靜壞掉。

  ⚠️ **重啟前先確認手上沒有正在分析的照片**（`curl -sk https://127.0.0.1:8000/ingest-jobs`
  的 `jobs` 是空的）。做到一半被砍掉的任務不會重送，會永遠卡在「分析中」
  ——`LAUNCH.md` §3 有記這件事。

- [ ] 確認容器真的讀到新值：

```bash
docker compose exec worker python -c "from app.core import config; print(config.CLOUD_ROUTE, bool(config.EC2_WORKER_INSTANCE_ID))"
```

  預期：`ec2 True`
  （**刻意只印 `bool()`**——實例 id 不是密碼，但沒有必要出現在終端機捲軸裡。）

### 4.7 Demo 2 —— 非敏感走雲端再回家（總覽 §5.2 逐條）

> design6 §12 原文：**EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉
> （或 Lifecycle 內會刪）；照片進待決定；詢問能問到。**
>
> 📌 **92-A 就要全過。** 92-B 之後只是換一台機器再跑一次同一份步驟，
> 唯一會變的證據是工人 log 那一行的 `backend=`（`cloud` → `local`）與多兩關 GPU 檢查。

- [ ] **第 1 步：確認機器是 `running`**（§4.3 剛開的那台本來就在跑；
      如果中間 Stop 過就先 Start）：

```bash
aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" 2>/dev/null
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
```

  預期：`running`（已經在跑時 `start-instances` 什麼都不做，`2>/dev/null` 是吞掉無害的提示）。

- [ ] **第 2 步：本機 `.env` 是 `CLOUD_ROUTE=ec2`，worker 已重啟**（§4.6 做過了）。

- [ ] **第 2.5 步：把頁首那顆「AI 模型」開關撥到雲端**（★ 上傳**之前**做，做完 Demo 撥回本機）：

```bash
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
```

  📌 **為什麼要撥：** 隱私閘門（本機、VLM 短問）**跟這顆開關走**（design6 D4／D6）——
  撥本機的話那句短問要 **1〜2 分鐘**，照片才會出門；撥雲端只要 **0.6〜1 秒**。
  Demo 2 要驗的是「非敏感照片走不走得出去」，不是「本機模型多慢」，所以先撥雲端讓它快。
  ⚠️ **快照是在上傳當下抄進 job 的**（design5 D14），所以**一定要先撥再上傳**。
  ⚠️ 這扇門與工人的 `WORKER_VLM_BACKEND` **完全是兩件事**：它管的是「本機那條路與閘門」用哪一顆模型，
  工人打哪一顆由機器上的 `worker.env` 決定，不受它影響。
  ⚠️ Demo 做完記得撥回本機：`-d '{"backend":"local"}'`。

- [ ] **第 3 步：上傳一張「內容」明確非敏感的圖**：

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

  `/tmp/receipt-test.png` 是 Phase 86 §4.5 步驟 1 準備的那張合成收據（真收據照片或 Pillow 畫的都行）；
  `/tmp` 被清掉的話照那一段再產一次（Phase 90 §4.4 也有同一份腳本）。

  預期：一段 JSON（恰三鍵 `job_id`／`filename`／`content_type`）＋下一行 `202`。
  **把那個 `job_id` 記下來**，下面幾步要用。

  📌 **重要的是「圖的內容」，不是檔名**（2026-09-01 改判、總覽 §10 追認項 f、§8.10）：
  隱私閘門是拿**縮小後的圖**去問 VLM 一句短問題，程式裡明文 `del filename`——
  **檔名對判斷零影響**。所以要挑一張**看起來就是收據／菜單**的圖；
  拿一張證件圖改名成 `receipt-test.png` 只會得到 `SENSITIVE`、走本機，這一條就驗不到了。
  ⚠️ 舊版計畫寫的「檔名命中 `NON_SENSITIVE_KEYWORDS`」是**規則版閘門**的說法，那一版已經作廢。

- [ ] **第 4 步：送出當下，S3 應該看得到 input 與 context**（動作很快，要**馬上**看）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION" \
  --query 'Contents[].Key' --output text
```

  預期（處理中）：`documents/<job_id>/context.json  documents/<job_id>/input.png`；
  工人寫完之後會多一個 `documents/<job_id>/result.json`。
  **來不及看到是正常的**（92-A 打 `ollama.com` 約 2 秒、92-B 在 T4 上也是幾秒，
  全程可能不到 20 秒就清乾淨了；**92-B 的第一張**因為 Ollama 要先把模型載進 VRAM 會久一些）——
  那就靠第 6 步的「最後是空的」與 EC2 那邊的 log 來證明它真的走過雲端。

- [ ] **第 5 步：三邊的 log 各看一次**（這一步是 Demo 2 的核心證據）：

```bash
# ① 本機 worker：走的是雲端路、向量本機算、結果真的落庫，而且**沒有** fallback
docker compose logs --tail=200 worker | grep -E "route=|fallback=|kind=embed|雲端結果已入庫"
```

  預期（**依這個順序**三行，中間可以夾別的）：

```text
job <job_id> route=cloud verdict=NON_SENSITIVE
AI 開始 kind=embed backend=local model=bge-m3
job <job_id> 雲端結果已入庫：photo_id=<n>
```

  **不該**有 `fallback=` 那一行。⚠️ 雲端路**不會**印本機路的「入庫完成」那一行（那是
  `_run_image_job` 才有的）——雲端路的完成訊號就是最後那行 **`雲端結果已入庫`**（Phase 79 的契約；
  PDF 的長相是 `雲端結果已入庫：N 頁中 M 頁成功（photo_ids=[…]）`）。沒有這一行＝結果沒落庫，
  先看有沒有 `fallback=`，再看 EC2 那邊（下面 ②）。
  📌 這三行**兩段完全一樣**——本機這一側根本不知道遠端那台有沒有 GPU。

```bash
# ② EC2 上的工人：真的收到 job，而且是用你以為的那一顆模型看的
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker logs cloud-worker 2>&1 | tail -n 20"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
  --query 'StandardOutputContent' --output text
```

  預期：看得到那個 `job_id`，以及一組計時 log——

  | | 預期那一行 | 意思 |
  |---|---|---|
  | **92-A** | `AI 開始 kind=vlm backend=cloud model=<雲端模型名>` ／ `AI 結束 kind=vlm … ok=true` | 那台 CPU 機把圖轉送 `ollama.com` 看。⏱ 一張約 **2 秒**。印成 `backend=local` ＝ `worker.env` 打錯，CPU 機會用自己的 CPU 硬看（好幾分鐘），回 §4.5 |
  | **92-B** | `AI 開始 kind=vlm backend=local model=gemma4:e2b` ／ `AI 結束 kind=vlm … ok=true` | 那台機器**自己的 GPU** 看的。⏱ 第一張比較慢（要把模型載進 VRAM），之後 T4 上大約**幾秒**一張。印成 `backend=cloud` ＝ `worker.env` 的 `WORKER_VLM_BACKEND` 沒吃到，圖被送去 `ollama.com` 了，**GPU 白開**（回 §4.5 改好再重啟服務） |

- [ ] **第 5b 步（★ 只有 92-B）：GPU 真的有在做事**：

```bash
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["nvidia-smi","ollama ps"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
  --query 'StandardOutputContent' --output text
```

  預期兩段輸出：
  - `nvidia-smi`：下半部的 Processes 表格裡看得到 **`ollama`**（或 `ollama_llama_server`）佔著 VRAM。
    ⚠️ 表格是空的、或整台機器 `nvidia-smi` 都不存在 ＝ AMI 選錯（沒有驅動），
    Ollama 其實是用 CPU 在跑（能動、但很慢；§4.2 變體 B）。
  - `ollama ps`：列出 `gemma4:e2b`，`PROCESSOR` 欄應該是 **`100% GPU`**。
    寫 `100% CPU` ＝ 同上，模型沒放進顯示卡。

  📌 **92-A 跳過這一步**（`t3.xlarge` 上 `nvidia-smi` 本來就不存在，那不是失敗）。

  📌 **一句話分辨兩種「雲端」：** ② 那裡的 `backend=` 說的是「**工人**看圖打哪一顆模型」，
  跟本機頁首那顆「AI 模型：本機｜雲端」開關**完全是兩回事**——
  照片在兩段裡都是走雲端路（S3／SQS／EC2）處理的，差別只在看圖那一步在誰家做。

  📌 **`aws ssm send-command` ＝「從外面對機器下一句指令」**，不必開 session。
  `--document-name AWS-RunShellScript` 是 AWS 內建的「跑一段 shell」文件、
  `--parameters 'commands=["…"]'` 是要跑的指令；拿到 `CommandId` 之後用
  `get-command-invocation` 取輸出（**要等幾秒**，所以中間 `sleep 5`）。

```bash
# ③ 本機 worker：向量是**本機**算的（design6 D13）
docker compose logs --tail=200 worker | grep "kind=embed"
```

  預期：`AI 開始 kind=embed backend=local model=bge-m3`（`backend` 一定是 `local`，兩段皆同）。

- [ ] **第 6 步：做完之後 S3 應該是空的**（本機 cleanup 刪掉三個物件）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
```

  預期：回應裡**沒有 `Contents`**（只有一堆 metadata）。
  還有殘骸也不算失敗——Lifecycle 規則會在 2 天內清掉（Phase 84 設的）。

- [ ] **第 7 步：照片真的進了待決定，而且問得到**：

```bash
# 進度面板已經沒有這一筆（成功 ＝ job 被刪掉），待決定數 +1
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool

# 資料庫真的多一列
psql -d PersonalDocAI -c "select id, left(text, 50) as text from photo order by id desc limit 1"

# staging 已清乾淨
ls data/staging/
```

  預期：`jobs` 陣列裡沒有那個 `job_id`、`pending_count` 比上傳前多 1；
  `photo` 最後一列就是剛才那張；`data/staging/` 是空的。

- [ ] **第 8 步（人工，用瀏覽器）：** 開 `https://localhost:8000/ui/pending.html`
  → 新照片在待決定牆上；開 `https://localhost:8000/ui/ask.html` → 問一句跟那張照片有關的話
  （例如「我最近買了什麼」），回答要**引用得到那張照片的內容**。
  📌 頁首開關第 2.5 步已經撥到雲端了，所以問問題也會很快（路由與回答都走 `ollama.com`）。
  撥回本機的話要等很久（路由 138 秒、回答 92 秒）——那是**另一扇門**（design6 D6），
  跟 Privacy Gate 無關，撥它不影響本 Demo 的結論。

- [ ] **第 9 步：Demo 2 做完，先不要 Stop**——Demo 2b 的第一步就是 Stop，接著做。

  📌 **頁首那顆開關也先留在「雲端」**：Demo 2b 要驗的是「走哪條路」，不是「哪一顆模型」，
  留著雲端可以讓 2b 的閘門與 fallback 看圖都快很多（不然要等本機 gemma4 一兩分鐘）。
  **兩個 Demo 都做完之後**（§4.9 的收工清單）再撥回本機：

```bash
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'
```

### 4.8 Demo 2b —— 遠端關掉自動 fallback（總覽 §5.3 逐條）

> design6 §12 原文：**EC2 Stop 後上傳非敏感；不必改任何設定；
> 進度與入庫與增量五相同；S3 不出現新物件。**
>
> 📌 **這是本增量最重要的一個 Demo。** Demo 2 證明「開著能用」，
> Demo 2b 證明「**關著也能用**」——而機器 99% 的時間是關著的。
>
> 📌 **這一節 92-A 就要全過，92-B 不必重做。** 它驗的是本機這一側的探測與 fallback，
> 跟遠端那台有沒有顯示卡完全無關（本機根本不知道那件事）。

- [ ] **第 1 步：Stop**：

```bash
aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
```

  預期：`stopped`（`wait` 會卡住約 30〜90 秒）。

- [ ] **第 2 步：⏳ 等 60 秒**（★ 這一步不能跳過，理由見下）：

```bash
sleep 60
```

  ⚠️ **為什麼要等：`Ec2Probe` 的答案快取 60 秒**（`EC2_PROBE_TTL_SECONDS=60`，總覽 §2.4.2）。
  探測只在「有一張非敏感照片要決定走哪條路」時才會打 AWS，答案記 60 秒。
  如果 Stop 前 60 秒內剛好有一張非敏感照片問過（例如你剛做完 Demo 2 第 3 步就急著 Stop），
  本機會拿著那次「`running`」的舊答案，**照樣把檔案送去 S3**，然後等到 5 分鐘逾時才 fallback。
  照本文件的順序做（Demo 2 第 4〜8 步至少要幾分鐘）快取多半早就過期了——但 `sleep 60` 零成本，當保險。
  那個結果**不算失敗**（照片最後還是入庫，log 寫 `fallback=local reason=result_timeout`），
  但它驗到的是「逾時」那條路，**不是**我們現在要驗的「探測說機器沒開」那條路。

  **兩種做法二選一：**
  - **等 60 秒**（上面那行）——最貼近真實使用情境（人不會 Stop 完 3 秒就傳照片）。
  - **重啟本機 worker**（`docker compose -f compose.yaml -f compose.dev.yaml restart worker`）
    ——快取在行程記憶體裡，重啟就清掉了。趕時間用這個。

- [ ] **第 3 步：什麼設定都不要改，直接再傳一張非敏感的圖**：

```bash
# ⚠️ .env 仍然是 CLOUD_ROUTE=ec2 —— **這正是這個 Demo 要證明的事**
cp /tmp/receipt-test.png /tmp/menu-test.png   # 同一張合成收據，換個檔名只是為了跟上一張分得開
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/menu-test.png" \
  https://127.0.0.1:8000/photos
```

  📌 **這裡改檔名純粹是為了自己好認**（兩張圖在待決定牆上分得出誰是誰）。
  閘門**不看檔名**（§4.7 第 3 步的框），判 `NON_SENSITIVE` 靠的是「圖的內容是收據」。

  預期：`202`（**不是 5xx**）。design6 §0 禁止第 6 條：遠端不可用時上傳**不准**變 5xx、
  也**不准**要使用者重傳。

- [ ] **第 4 步：進度面板的形狀跟增量五完全一樣**：

```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
```

  預期：那筆 job 的 `status` 是 `queued` 或 `analyzing`，
  欄位形狀與增量五**逐字相同**（使用者看不到 `route`／`privacy`——總覽 §2.4.4）。

- [ ] **第 5 步：log 要有 fallback 那一行**（★ 這是 Demo 2b 的核心證據）：

```bash
docker compose logs --tail=200 worker | grep "fallback="
```

  預期：

```text
fallback=local reason=remote_unavailable
```

  ⚠️ **看到 `reason=result_timeout` 而不是 `remote_unavailable`** ＝ 你沒等滿 60 秒
  （或沒重啟 worker），探測還拿著舊快取。照片還是會入庫，但這一條要重做一次：
  等 60 秒 → 再傳一張 → 重看。

- [ ] **第 6 步：S3 全程沒有任何新物件**（探測不通過就根本不會送出）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
```

  預期：**沒有 `Contents`**。

- [ ] **第 7 步：等本機看完圖，照片照樣入庫**：

```bash
# 本機 gemma4 要 64〜88 秒（9 欄 prompt 可到 2〜5 分鐘）。想快就先把頁首開關撥雲端。
# ⚠ 別忘了**閘門那句短問也要跑一次**（本機約 100 秒、雲端約 1 秒，跟頁首開關走），
#   所以整條「fallback 走本機」在開關＝本機時可能要**三分鐘**才看到照片出現。這是預期的。
# ⚠️ 等的時候不要再上傳別的東西——Phase 48 踩過：兩件事同時打本機模型，
#    db container 被壓垮、postmaster 花 2 分鐘才殺得掉子行程。一次一件事。
watch -n 10 'curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool | head -20'
# 看到 jobs 變成空陣列就是好了；按 Ctrl+C 離開 watch

psql -d PersonalDocAI -c "select count(*) from photo"       # 比 Demo 2 之後再 +1
ls data/staging/                                            # 預期：空的
```

- [ ] **第 8 步（人工）：** 開 `https://localhost:8000/ui/pending.html`，兩張照片
      （Demo 2 的與 Demo 2b 的）都在待決定牆上、**看起來完全一樣**——使用者根本分不出
      哪一張走過雲端。**這就是 D10 想要的效果。**

- [ ] **第 9 步：反面再驗一次 Demo 1（敏感留本機）**（順手做，成本很低）：

```bash
# ⛔ **不可以** cp /tmp/receipt-test.png /tmp/身分證.png ——閘門不看檔名（2026-09-01 改判），
#    改名只會再得到一次 NON_SENSITIVE，等於什麼都沒驗到。
#    要用**內容真的畫成證件**的那張合成圖（Phase 86 §4.6／Phase 90 §4.4 的 Pillow 腳本，
#    /tmp 被清掉就照那一段再產一次；裡面全是編造的假資料）。
ls -l /tmp/id-card-test.png                                  # 沒有就回 Phase 86 §4.6 產一張
curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/id-card-test.png" \
  https://127.0.0.1:8000/photos                              # 預期：202
docker compose logs --tail=100 worker | grep "route=local verdict=SENSITIVE"
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
```

  預期：log 那一行看得到；S3 沒有 `Contents`。
  📌 檔名 `id-card-test.png` 是**中性的英文**（沒有「身分證」三個字），所以這一條同時證明了
  **擋下來的是內容、不是檔名**。

### 4.9 收工守則（★ 每一次都要做）

**三種收工動作，分別用在哪裡（不要混）：**

| 什麼時候 | 動作 | 為什麼 |
|---|---|---|
| **92-A 的 Demo 2b 第 1 步** | `stop-instances` | 那正是 Demo 2b 要證明的事（機器關著、什麼都不改，照片照樣入庫）。碟留著，Start 回來 systemd 會自己把工人拉起來 |
| **92-A 兩個 Demo 都做完** | `stop-instances`（**不是 terminate**） | 30 GB gp3 關著約 **$2.9／月**，在 $5 Budget 內；而且 **Phase 94 的 Demo 3 還要用它**（`start-instances` 一分鐘就能收訊息，不必重放 `worker.env`、不必重拉模型） |
| **要開 92-B 的 GPU 機之前** | `terminate-instances`（刪掉 92-A 那台） | 同時只准有一台（兩台會搶同一條 SQS 佇列，訊息被隨機分掉）。而且 92-A 的任務到這裡已經結束了 |
| **92-B 整段測完** | `terminate-instances`（費用選項 **B**，已拍板） | 80 GB gp3 關著約 **$7.7／月**，**單獨就超過 $5 Budget**。⚠️ Demo 2b 當下仍然是 Stop（要證明 fallback），整段結束才 terminate |

- [ ] **收工第一件事：確認機器狀態**：

```bash
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].{State:State.Name,Type:InstanceType,Arch:Architecture}' \
  --output json
```

  預期：**92-A** `{"State": "stopped", "Type": "t3.xlarge", "Arch": "x86_64"}`；
  **92-B** 收工後 `{"State": "terminated", "Type": "g4dn.xlarge", "Arch": "x86_64"}`（或查無此實例）。

- [ ] **收工第二件事：頁首開關撥回本機**（§4.7 第 2.5 步撥去雲端的那顆）：

```bash
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'
```

  （這個值本來就存在記憶體、重啟 app 一律回本機，撥回來只是不要讓下一個人困惑。）

**收工守則（這幾段之後會原文寫進 `LAUNCH.md` 與 `CLAUDE.md`）：**

| 規則 | 說明 |
|---|---|
| **還要再用的機器一律 `stop-instances`** | Stop ＝ 關機：硬碟（EBS）留著，`worker.env`、Docker 映像、**已經拉下來的 7 GB 模型**都還在，開回來 systemd 會自己把工人拉起來。Terminate ＝ 銷毀：**整台連硬碟一起消失、不可逆**，要重跑 §4.3〜§4.5 全部（含重裝 Ollama 與重拉模型）。**92-A 收工＝Stop**；terminate 只用在上面那張表的兩種情況 |
| **工人會優雅收尾** | `stop-instances` 會先讓機器正常關機 → systemd 跑 `ExecStop=/usr/bin/docker stop -t 120 cloud-worker`（Phase 91 的 unit；總覽 §10.2 追認項 O，另有 `TimeoutStopSec=150`）→ 容器收到 SIGTERM → 工人印一行 **「收到停止訊號」** 之後把手上那一則訊息做完才退出（Phase 88 做的）。**最多等 120 秒**；極少見地超過才會被 SIGKILL，那時 jobs 訊息會在 VisibilityTimeout（900 秒）後回到佇列，下次 Start 由工人的冪等規則（Phase 87：result 已在→只補 Send；input 已被本機 fallback 清掉→只刪訊息）收拾——**不會留殘局、不會雙 INSERT** |
| **Stop 之後仍然在扣的東西** | 運算費與公有 IPv4（$0.005／小時）**都停了**；**EBS 繼續**：92-A 的 30 GB ≈ **$2.9／月**（Budget 內，可以放心留著）、92-B 的 80 GB ≈ **$7.7／月**（超過 Budget，所以測完要 terminate） |
| **Stop 之後公有 IP 會被釋放** | 下次 Start 會拿到**一個新的**，而且 Stop 期間**不再計費**（公有 IPv4 的 $0.005／小時只在 running 時算）。這對本專案完全沒差——**沒有任何人會主動連進來**（inbound 是空的），我們也不必知道它的 IP |
| **忘了關的代價** | 92-A：一整天 ≈ **$5.2**、一個月 ≈ **$160**。92-B：一整天 ≈ **$17**、一個月 ≈ **$515**。帳號已升 **Paid**——忘關會**扣卡**，不是關帳 |
| **怎麼快速檢查「我是不是忘了關」** | 下面這一行，養成收工前跑一次的習慣 |

```bash
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table
```

  預期（收工時）：空表格。有東西 ＝ 你忘了關。

#### 92-A 的收工：Stop

```bash
aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

  **留著它**：`.env` 的 `EC2_WORKER_INSTANCE_ID` 與 `CLOUD_ROUTE=ec2` 都不動——
  Phase 94 的 Demo 3 要用（`start-instances` 一分鐘就能收訊息）。
  30 GB gp3 ≈ $2.9／月，在 Budget 內，這是刻意接受的成本。

#### 92-B 的前置：先 Terminate 92-A

```bash
aws ec2 terminate-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-terminated --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

  然後把本機 `.env` 的 `EC2_WORKER_INSTANCE_ID` 換成 92-B 那台的新 id、`restart worker`。
  ⚠️ 根碟預設 `DeleteOnTermination=true`，會跟著走；刪完順手確認沒有孤兒 volume：
  `aws ec2 describe-volumes --region "$AWS_REGION" --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text`（預期空）。

#### 92-B 的收工：Terminate（★ 費用選項已拍板為 B）

GPU 機的根碟是 **80 GB gp3 ≈ $7.7／月**，**關機照付**，而 Budget 是每月 $5。
產品負責人 2026-09-03 已拍板 **選項 B ＝測完 Terminate**（原話：「3.1」「我之後測完就會刪掉」）：

| | 選項 A：**用完 Stop**（D15 字面） | 選項 B：**用完 Terminate、下次重建**（★ 已選） |
|---|---|---|
| 收工動作 | `aws ec2 stop-instances …` | `aws ec2 terminate-instances …` |
| 關著的成本 | **≈ $7.7／月**（EBS） | **$0**（什麼都不留） |
| 下次要用時 | `start-instances` → 約 1〜2 分鐘後就開始收訊息（模型還在碟上，不必重拉） | 重跑 §4.2〜§4.5：`run-instances` → 等 user-data 裝 Ollama ＋ 拉 7 GB 模型（**5〜10 分鐘**）→ 重新用 SSM 放一次 `worker.env` |
| 風險 | 忘了關就是 $17／天 | 每次重建都是一次「會不會這次裝失敗」的賭；`worker.env` 要**重打一次** |
| 要配套改的事 | 把 Budget 從 $5 調到例如 $15 | 無（但 §3「明確不做」與 D15 的「一律 Stop」要記成「92-B 選了 B」） |

  **選 B 的收工清單（92-B）：**
  - `aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"`（不是 `stop-instances`）
  - **只刪那台 EC2**（根碟預設跟著走）。刪完確認沒有孤兒 volume。
  - **留下** Phase 91 的 SG、IAM role／instance profile、S3、兩條 SQS、ECR。
  - 本機 `.env`：`EC2_WORKER_INSTANCE_ID` 清空、`CLOUD_ROUTE=off`，`restart` 本機 worker。
  - 下次再測＝重跑 §4.2〜§4.5（含拉 7 GB 模型、SSM 再放一次 `worker.env`、新的實例 ID）。

> 📌 **注意 92-A 與 92-B 的差別不是「哪個比較省」，是「還要不要再用」。**
> 92-A 留著是因為 Phase 94 的 Demo 3 馬上就要用它，而它的碟便宜到在 Budget 內；
> 92-B 刪掉是因為它的碟貴到超過 Budget，而且 GPU 那件事驗完就沒有下一步了。

### 4.10 三份文件

> 📌 **語言不要搞混：** `README.md` 與 `LAUNCH.md` 自 2026-08-27 起是**英文**；
> `CLAUDE.md` 與 `docs/` 是**繁體中文（台灣用語）**。
> ⛔ 三份都**只寫變數名，不寫值**——實例 id、bucket 名、帳號 id、API key 一個字都不准出現。
>
> 📌 **這一節在 92-A 就寫完，而且要寫成兩段式的誠實現況**（現在跑的是 CPU 機、
> GPU 機是配額核准之後的後續）。**92-B 做完不必再改這三份檔**——
> 這樣才不會留下「先寫一版 CPU 的、之後再改成 GPU 的」那種過渡產物。

#### （1）`LAUNCH.md`：目錄加一列 ＋ 新章節 13 ＋ Appendix 架構圖

> ⚠️ **`## 12. Cloud worker on the Mac` 已經被 Phase 88 用掉了**（那一章講的是
> 「在這台 Mac 上用 `python -m app.workers.cloud_worker` 跑工人」）。
> 本 phase 的 EC2 章節是 **§13**，插在 §12 之後、Appendix 之前。
> **不要重編既有章節的編號或錨點**——那會讓所有既有的 `[section N](#n-…)` 連結全部失效。
>
> 📌 **這一章在 92-A 就要寫完，而且要誠實描述「現在是哪一段」。**
> 92-B 做完**不必改這一章**——下面的英文已經把兩段都寫進去了，讀者一眼看得出
> 目前跑的是 CPU 機、GPU 機是配額核准之後的後續。

- [ ] **目錄**（`## Contents` 那一段，Phase 88 加的 `12. [Cloud worker on the Mac]…` 之後）加一行：

```markdown
13. [Cloud worker (EC2)](#13-cloud-worker-ec2)
```

- [ ] **在 `## 12. Cloud worker on the Mac` 那一節結束之後、`## Appendix: current architecture` 之前**
      插入這一整章（英文）：

````markdown
---

## 13. Cloud worker (EC2)

An **optional** EC2 worker can take the vision step off this Mac.
This is the real remote worker; [section 12](#12-cloud-worker-on-the-mac) covers running the
same program locally on this Mac for development. It is **off by default**:
the instance is normally **stopped**, and with it stopped the system behaves exactly as it
did before — every photo is analysed locally. Nothing needs changing to switch back.

Only photos the **local privacy gate** marks `NON_SENSITIVE` are eligible, and only while
the instance is actually `running`. The gate looks at the *image*, never at the filename.
Sensitive and uncertain photos never enter the S3 mailbox
and never reach the EC2 worker. (The header "AI model: local | cloud" switch is a *separate*
door: with it set to cloud, any photo's pixels are still sent to Ollama Cloud for inference,
exactly as before — the gate does not touch that switch.)

### Which box is out there

The instance comes in two flavours. **Both run the same user-data script, the same systemd
unit and the same container image**; only the instance type, the AMI, the root volume size
and one line of `/opt/personaldocai/worker.env` differ.

| | CPU box (**what is set up today**) | GPU box (waiting on an AWS quota) |
|---|---|---|
| instance type | `t3.xlarge` (4 vCPU, 16 GiB, no GPU) | `g4dn.xlarge` (one NVIDIA T4) |
| AMI | plain Amazon Linux 2023, x86_64 | Deep Learning Base OSS NVIDIA Driver GPU AMI |
| root volume | 30 GB gp3 | 80 GB gp3 |
| `WORKER_VLM_BACKEND` | `cloud` — the box forwards the image to ollama.com | `local` — the box runs its **own** Ollama and uses the T4 |
| on-demand, Tokyo | about **$0.2176 / hour** | about **$0.71 / hour** |
| when idle | **stopped**, 30 GB disk ≈ $2.9 / month | terminated after the demo, so nothing |

**Right now the GPU box does not exist.** The G-and-VT service quota (`L-DB2E81BA`) is still
0 on this account and the increase request is with AWS support, so the cloud path was brought
up and verified on the CPU box first — everything that can actually break (instance-profile
credentials inside the container, an egress-only security group, pulling from ECR, SSM access,
systemd starting the worker at boot, the local probe reading the instance state, the amd64
image running on real x86) is identical on both. The GPU only changes *where the vision step
runs and how many seconds it takes*. If the quota is refused, the CPU box stays as it is and
nothing else changes.

The worker's very first log line always says which one you are looking at:
`… vlm=cloud model=<cloud model>` or `… vlm=local model=gemma4:e2b`. That value comes from
`WORKER_VLM_BACKEND` in `/opt/personaldocai/worker.env` **on the instance** — nothing on this
Mac decides it. Both flavours install Ollama at first boot, because the systemd unit waits for
`127.0.0.1:11434` before it starts the container; on the CPU box that Ollama simply sits there
answering the door.

### Start it

```bash
set -a; . ./.env; set +a          # brings AWS_REGION and EC2_WORKER_INSTANCE_ID into the shell
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # .env holds the app's minimal key; the CLI must use the admin profile in ~/.aws
aws ec2 start-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

The worker service starts by itself (systemd `personaldocai-worker`, enabled at boot). It
waits for the local Ollama to answer, then pulls the `latest` image from ECR on every start,
so a freshly deployed image is picked up automatically. Give it about a minute (the very
first boot of a *newly created* instance takes 5-10 minutes longer, because the machine
installs Ollama and downloads the 7 GB model), then upload a photo whose **contents** are
clearly non-sensitive — a receipt, a menu; the gate reads the image, so renaming a file
changes nothing. The local worker log should show, in this order,
`route=cloud verdict=NON_SENSITIVE`, then `kind=embed backend=local` (vectors are always computed
here), then `雲端結果已入庫：photo_id=…` — and **no** `fallback=` line. Those three lines are
the same on either flavour of the box.

Tip: flip the header "AI model" switch to cloud *before* uploading. The privacy gate follows
that switch, and on the local model a single gate question takes one to two minutes.

### Stop it (do this every time)

```bash
aws ec2 stop-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

Forgot whether you stopped it? This lists anything still running:

```bash
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table
```

An empty table is what you want at the end of the day.

Stopping the instance shuts it down cleanly: systemd runs `docker stop -t 120 cloud-worker`, the
worker gets a SIGTERM, logs 「收到停止訊號」 and finishes the message in its hands before
exiting (the unit runs `docker stop -t 120`, so it has up to 120 s). Should a message ever be cut off, SQS redelivers it
after the visibility timeout and the worker's idempotency rules pick it up on the next Start —
nothing is ever inserted twice.

**Stop the CPU box, never terminate it.** Stop keeps the disk, so `worker.env` and the pulled
image survive and the next Start needs no setup; 30 GB gp3 costs about $2.9 a month, which is
inside the budget alert. Terminate destroys the instance **and its disk**, and it cannot be
undone — you would have to rebuild it from `deploy/ec2/user-data.sh` and re-enter the secrets
by hand. (The GPU box is the exception: its 80 GB disk costs about $7.7 a month, more than the
whole budget alert, so that one gets terminated after its demo rather than left stopped.)

After a Stop the public IPv4 address is released (and stops being billed) and the next Start
gets a new one. That is fine here: nothing ever connects *to* the instance (its security
group has **no inbound rules at all**).

### Check the logs without SSH

There is no SSH on this instance. Use SSM — either an interactive shell:

```bash
aws ssm start-session --target "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
# inside:  systemctl status personaldocai-worker --no-pager
#          sudo docker logs cloud-worker --tail 50
#          sudo journalctl -u personaldocai-worker -n 50 --no-pager
#          systemctl is-active ollama    # must be active on either flavour: the unit waits for it
#          nvidia-smi                    # GPU box only — look for an "ollama" process holding VRAM
#          ollama ps                     # GPU box only — PROCESSOR should say 100% GPU
#          exit
```

…or one-shot from here (no session needed):

```bash
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker logs cloud-worker 2>&1 | tail -n 20"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
  --query 'StandardOutputContent' --output text
```

The first log line tells you which build is running and which model it will use:
`cloud_worker 啟動 version=<git sha> region=… bucket=… vlm=cloud model=…`.
That `version=` is the only reliable way to confirm a deployment landed — do not trust the
`latest` tag alone. On the CPU box `vlm=cloud` is correct; on the GPU box it would mean the
instance is paying for a T4 and not using it — fix `WORKER_VLM_BACKEND` in
`/opt/personaldocai/worker.env` and restart the service.
`aws ssm start-session` needs a plugin the CLI does not bundle:
`brew install --cask session-manager-plugin` (once per machine).

### Cost notes

| Item | Cost |
|---|---|
| `t3.xlarge` (CPU box) while **running** | about **$0.2176 / hour** on-demand in Tokyo. An hour of demoing is about 22 cents; a day you forgot to stop is about **$5.2** |
| `g4dn.xlarge` (GPU box) while **running** | about **$0.71 / hour**. A day you forgot to stop is about **$17**, a month about **$515** |
| public IPv4 while **running** | **$0.005 / hour** — every public IPv4 address is billed since 2024-02-01. Released on Stop, so nothing while stopped |
| 30 GB gp3 root volume while **stopped** (CPU box) | about **$2.9 / month** — inside the $5 budget alert, which is why this box is kept around |
| 80 GB gp3 root volume while **stopped** (GPU box) | about **$7.7 / month** — above the whole budget alert on its own, which is why that box is terminated instead of stopped |
| S3 mailbox | objects are deleted as soon as the result comes home; a lifecycle rule expires anything left under `documents/` after 2 days |
| SQS, ECR, IAM, security group, S3 gateway endpoint | free or negligible at this volume (ECR storage is a few cents a month for one image) |

The account is on the AWS **Paid plan** (upgraded 2026-09-03), so a running instance is billed
to the card. A budget alert exists (`personaldocai-budget`, $5/month, mail at 80% of both actual
and forecast). Paid does **not** grant GPU quota; that is a separate request (`L-DB2E81BA`),
which is why the CPU box came first.

### Never do these

- **Never create a NAT Gateway.** ~$45/month in Tokyo; it would burn the budget in weeks.
  The instance sits in a public subnet with an auto-assigned public IP and gets out fine.
- **Never allocate an Elastic IP.** Since 2024-02-01 an Elastic IP is billed for every hour it
  exists, attached or not — on a machine that is stopped 99% of the time that is pure waste.
  The auto-assigned address costs nothing while stopped, and we do not need a fixed address.
- **Never open an inbound rule** (not even SSH on 22). Management is SSM only.
- **Do not terminate mid-demo.** The fallback demo needs Stop (the disk stays) so that the
  local worker can be shown falling back with nothing reconfigured.
- **Never launch a GPU box from a plain Amazon Linux 2023 AMI.** That image has no NVIDIA driver,
  so Ollama silently falls back to the CPU: it still works, it is just ten times slower, and
  nothing anywhere says why. Use the Deep Learning Base OSS NVIDIA Driver GPU AMI — and,
  conversely, do not launch the *CPU* box from the GPU AMI: its snapshot alone is 75 GB, so you
  would pay for a 80 GB disk you have no use for.
- **Never expose Ollama on `0.0.0.0`.** It listens on loopback only; the worker container
  reaches it with `--network host`.

### `.env` keys this uses

Values live in `.env`, which is not in version control. Names only:

```text
AWS_REGION
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
S3_BUCKET
SQS_JOBS_QUEUE_URL
SQS_RESULTS_QUEUE_URL
EC2_WORKER_INSTANCE_ID
CLOUD_ROUTE                    # off | assume | ec2 — day to day this is "ec2"
EC2_PROBE_TTL_SECONDS          # 60
CLOUD_RESULT_TIMEOUT_SECONDS   # 300
```

`WORKER_VLM_BACKEND` is **not** one of these: it lives in `/opt/personaldocai/worker.env`
**on the instance**, next to `OLLAMA_BASE_URL` and `VLM_MODEL`. Nothing on this Mac reads it.

`CLOUD_ROUTE=off` disables the cloud path entirely — the fastest way to rule it out while
debugging. `assume` skips the running-check and is only for development.

**After changing any of these you must restart the worker container:**
`docker compose -f compose.yaml -f compose.dev.yaml restart worker`. Two independent reasons:
the config module reads `.env` once at process start, and the `ec2` route object is built
behind an `lru_cache` (so the whole process shares one probe cache). Without a restart the
new values are simply ignored — silently, with no error.

A **stopped instance is not an error state**. With `CLOUD_ROUTE=ec2` the local worker checks
the instance before every eligible photo (answer cached 60 s) and simply analyses locally
when it is not running, logging `fallback=local reason=remote_unavailable`. Uploads still
return 202 and the progress panel looks exactly the same.
````

- [ ] **Appendix 架構圖**：在既有那張圖的最後（`Dev mode (layering compose.dev.yaml)…`
      那一段**之前**）插入這一段：

```text
   Optional cloud path (only while the EC2 worker is running, and only for photos the
   local privacy gate marks NON_SENSITIVE -- everything else is analysed locally):

     worker --PutObject--> S3 documents/<job_id>/{context.json,input.*}   (private bucket,
        |                                                                 BPA on, SSE-S3,
        |                                                                 2-day lifecycle)
        +--SendMessage---> SQS personaldocai-jobs   {"job_id","s3_key"}   -- no image bytes
                                    |
                                    v
                     [EC2 x86_64 instance]                        <- normally STOPPED
                       today: t3.xlarge, plain AL2023, 30 GB
                       later: g4dn.xlarge + NVIDIA T4, DL Base GPU AMI, 80 GB
                             systemd personaldocai-worker
                               docker run --network host <ECR>/...:latest
                             ollama.service on the host, 127.0.0.1:11434
                               (on the CPU box it just answers the door;
                                on the GPU box it is what actually looks at the photo)
                             no inbound rules at all; egress TCP 443 only
                             managed via SSM Session Manager (no SSH, no key pair)
                               |  GetObject input + context
                               |  vision runs where WORKER_VLM_BACKEND says:
                               |    cloud -> forwarded to ollama.com   (CPU box today)
                               |    local -> this box's own Ollama     (GPU box later)
                               |  PutObject documents/<job_id>/result.json
                               +--SendMessage--> SQS personaldocai-results  {"job_id"}
                                    |
                                    v
     worker <--ReceiveMessage-- results, then GetObject result.json
        |    embeddings are ALWAYS local bge-m3, never remote
        +--> INSERT photo + original + thumbnail, delete the three S3 objects, delete the job

   With the instance stopped, none of the above happens: the local worker sees the probe
   say "not running" and calls the ordinary local ingest path instead. Same 202, same
   progress panel, same pending wall.
```

#### （2）`CLAUDE.md`：指令區加一段（繁體中文）

- [ ] 在 `## 指令` 那個 bash 區塊裡，**接在 Phase 88 加的「`# ── 雲端看圖工人（增量六 Phase 88；平常不用開）`」那一段之後、「`# 跑測試（Phase 03 起…`」那一段之前**插入（這樣 Phase 82 的 AWS 段、88 的 Mac 工人段、本 phase 的 EC2 段三段相連，讀的人不必在檔案裡跳來跳去）：

```bash
# ── 雲端工人（EC2；增量六 Phase 92 起）──────────────────────────
#
# 這是**可選**的：EC2 平常是 **stopped**，關著的時候整個系統跟增量五完全一樣
# （每一張照片都在這台 Mac 上看圖）。開它只是為了把「非敏感照片的看圖」卸出去。
#
# ⚠ 現在那台是 **CPU 機（t3.xlarge、一般 AL2023、30 GB gp3）**，工人把圖**轉送 ollama.com**
#   看（worker.env 的 WORKER_VLM_BACKEND=cloud）。GPU 機（g4dn.xlarge、T4、自己跑 Ollama、
#   WORKER_VLM_BACKEND=local）是**之後**的事——G and VT 配額（L-DB2E81BA）還在 AWS 人工審核，
#   帳號上限仍是 0。先用 CPU 機把 AWS 那一整條流程驗完（Phase 92-A），GPU 只影響
#   「看圖那一步在哪裡做、要幾秒」（Phase 92-B）。兩段跑的是**同一份** user-data／unit／映像。
# 用哪一顆由**那台機器上**的 /opt/personaldocai/worker.env 裡的 WORKER_VLM_BACKEND 決定
# （本機的 .env **沒有**這個變數，Mac 上跑工人時預設是 cloud）。
# 只有**隱私閘門判為 NON_SENSITIVE** 而且**機器真的 running** 的照片才會走雲端；
# 敏感與不確定的照片**不進 S3、不到 EC2**。⚠ 頁首那顆「AI 模型：本機｜雲端」是另一扇門
# （design6 D6）：撥到雲端時任何照片的影像照樣送 ollama.com 看圖——閘門不管那扇門，
# 所以**不要**把這段講成「敏感資料完全不出雲」（design6 §6 明文禁止這種說法）。
#
# 先把 .env 帶進 shell（下面每一條都要用 $AWS_REGION 與 $EC2_WORKER_INSTANCE_ID），
# 然後**馬上**把 .env 那把程式用的 key 丟掉，讓 CLI 回去用 ~/.aws 的 admin（見上面 AWS 段）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

# 開機（開完等一分鐘，systemd 會自己把工人拉起來、並從 ECR 拉最新的映像）
aws ec2 start-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"

# ⛔ 關機（★ 每一次 demo／除錯結束都要做，忘了就在扣卡）
aws ec2 stop-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"

# 「我是不是忘了關？」——收工前跑這一行，預期是**空表格**
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table

# 看那台機器的狀態與 log（**沒有 SSH**，管理一律走 SSM）
aws ssm start-session --target "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
#   進去之後：systemctl status personaldocai-worker --no-pager
#             sudo docker logs cloud-worker --tail 50      ← 第一行有 version=<git sha>
#                                                            與 vlm=cloud｜local model=…
#             sudo journalctl -u personaldocai-worker -n 50 --no-pager
#             systemctl is-active ollama  ← 兩種機器都要是 active（unit 會等 11434 才啟動容器）
#             nvidia-smi     ← **只有 GPU 機才有**；CPU 機印 command not found 是正常的
#             ollama ps      ← GPU 機上 PROCESSOR 欄要是 100% GPU
#             exit
#   ⚠ 需要外掛：brew install --cask session-manager-plugin（每台 Mac 一次）
#
# 不想開 session，只想跑一句指令：
#   CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
#     --instance-ids "$EC2_WORKER_INSTANCE_ID" --document-name AWS-RunShellScript \
#     --parameters 'commands=["docker logs cloud-worker 2>&1 | tail -n 20"]' \
#     --query 'Command.CommandId' --output text)
#   sleep 5; aws ssm get-command-invocation --region "$AWS_REGION" \
#     --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
#     --query 'StandardOutputContent' --output text
#
# 本機這邊怎麼切（改完要 restart worker，app 不必動）：
#   CLOUD_ROUTE=off     完全不走雲端（除錯時先切這個，一秒排除雲端嫌疑）
#   CLOUD_ROUTE=assume  假設遠端開著、不做探測（只給開發用；機器關著會白等 5 分鐘才 fallback）
#   CLOUD_ROUTE=ec2     ★ 日常就是這個：每次送出前先問一次 DescribeInstances（答案快取 60 秒）
#   走了雲端的證據（本機 worker log 三行，依序）：route=cloud verdict=NON_SENSITIVE →
#   kind=embed backend=local → 雲端結果已入庫：photo_id=…（雲端路**不印**本機路的「入庫完成」）
#   docker compose logs --tail=200 worker | grep -E "route=|fallback=|雲端結果已入庫"
#   docker compose -f compose.yaml -f compose.dev.yaml restart worker
#   ⛔ 那一行 restart **不能省**，有兩個理由：① config 只在行程啟動時讀一次 .env；
#      ② ec2 模式的 CloudRoute 是 dependencies._ec2_cloud_route()（@lru_cache），
#         整個行程共用同一顆物件，第一次建立時就把 instance id 與模式吃進去了。
#         不重啟的話 .env 改了也換不掉它，而且**完全不會報錯**。
#
# 💡 要跑 demo 的話，上傳**之前**先把頁首那顆「AI 模型」開關撥到雲端：隱私閘門跟著它走，
#    撥本機的話那句短問要 1〜2 分鐘照片才會出門，撥雲端不到 1 秒。做完撥回本機。
#    （快照是在上傳當下抄進 job 的，所以順序不能顛倒。）
#
# ⚠ **機器關著不是壞掉**。CLOUD_ROUTE=ec2 時探測發現它不是 running，就直接走本機那條路，
#   log 寫 fallback=local reason=remote_unavailable；上傳仍然回 202、進度面板一模一樣。
# ⚠ **剛 Stop 完的 60 秒內**，探測可能還拿著「running」的快取，於是照片會被送出去、
#   然後等到逾時（CLOUD_RESULT_TIMEOUT_SECONDS=300）才 fallback。這是**預期行為**，
#   不是 bug。要立刻生效就 restart worker（快取在行程記憶體裡）。
#
# ⛔ 這些永遠不准做：
#   1. 對「還要再用」的機器 terminate-instances ← Stop 才留得住碟（worker.env、7 GB 模型、
#      映像都在）。CPU 機收工一律 Stop（30 GB ≈ $2.9／月，在 Budget 內，Demo 3 還要用它）
#   2. 建 NAT Gateway                 ← 東京約 $45／月
#   3. 配 Elastic IP                  ← 2024-02 起配了就每小時扣、不管機器有沒有在跑
#   4. 開任何 inbound 規則（含 SSH 22）← design6 D11；管理只走 SSM
#   5. 用一般的 AL2023 AMI 開**GPU 機** ← 沒有 NVIDIA 驅動，Ollama 會**安靜地**退回 CPU
#      （能跑、但一張圖好幾分鐘，而且不會有任何錯誤訊息）。GPU 機要用 Deep Learning Base GPU AMI。
#      反過來也一樣：**不要用 GPU AMI 開 CPU 機**（那顆快照 75 GB，根碟只能開 ≥80 GB＝白付）
#   6. 讓 Ollama 聽 0.0.0.0 ← 它只該聽 127.0.0.1；容器靠 --network host 打得到
#   （帳號已升 Paid：忘關會扣卡。升 Paid **不會**自動給 GPU 配額。）
#
# ⚠ 配額分兩條，不要搞混：
#   CPU 機（t3.xlarge）吃 Running On-Demand **Standard** instances（L-1216C47A）——本帳號 8，夠用
#   GPU 機（g4dn.xlarge）吃 Running On-Demand **G and VT** instances（L-DB2E81BA）——本帳號 0、
#     申請中（CASE_OPENED）。沒核准就 run-instances 會回 VcpuLimitExceeded，一台都開不出來。
#     **不要重送申請**（同一條重送只會被合併）。
#
# 費用：t3.xlarge 開機約 $0.2176／小時（忘一天 ≈ $5.2）；g4dn.xlarge 約 $0.71／小時
#      （忘一天 ≈ $17、一個月 ≈ $515）。兩者都另加公有 IPv4 $0.005／小時（只在 running 時算）。
#      **關機也會扣碟錢**：30 GB gp3 ≈ $2.9／月（Budget 內，所以 CPU 機留著）、
#      80 GB gp3 ≈ $7.7／月（超過 Budget，所以 GPU 機測完要 terminate）。
#      Budget 警報 personaldocai-budget（每月 $5，實際與預測各 80% 寄信）。
```

#### （3）`README.md`：兩句改成誠實版本（英文）

- [ ] **第 11〜13 行**（`**A single-user, fully local…**` 那一段）整段換成：

```markdown
**A single-user, local-first, genuinely demo-able side project.** No accounts; the photos,
the database and the vectors live on your own machine. Photos stay on your machine by
default — only files the local privacy gate marks non-sensitive may pass briefly through a
private S3 mailbox while an optional EC2 worker is running, and those objects are deleted as
soon as the result comes home. AI inference can also be switched between local Ollama and
Ollama Cloud.
```

- [ ] **第 635 行附近**（`## 12. Explicitly out of scope` 清單裡的 `- No cloud storage …` 那一列）
      換成：

```markdown
- No cloud file storage and no cloud backups. S3 is used only as a short-lived mailbox: a
  photo goes there only when the local privacy gate says non-sensitive **and** the optional
  EC2 worker is running, and the objects are deleted as soon as the result comes back (a
  2-day lifecycle rule sweeps up anything missed). Sensitive and uncertain photos never enter
  that mailbox; the database, the originals and the thumbnails never leave the machine at all.
  (The header AI switch is a separate door: set to cloud, it still sends a photo's pixels to
  Ollama Cloud for inference, exactly as before)
```

- [ ] 檢查沒有改到別的：

```bash
git diff --stat README.md LAUNCH.md CLAUDE.md
```

  預期：三個檔各只有你剛才改的那幾段（`README.md` 兩處、`LAUNCH.md` 三處、`CLAUDE.md` 一處）。

  ⚠️ **`README.md` 的「Tests」那一列（`**543 passed, 0 skipped**`）本 phase 不要動**——
  增量六做完是 682，那是 **Phase 95** 收尾時一起改的事。

### 4.11 收工檢查與 commit

- [ ] 測試沒被影響（本 phase 零 Python 變更）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                   # 預期：689 passed ＋ 0 skipped（＝開工那一次的數字）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q   # 預期：與上一行**逐字相同**
ruff format --check app tests scripts && ruff check app tests scripts   # All checks passed!
```

> 📌 **顆數是雙寫法**：總覽 §9 寫 662（規劃時的估算）、實測基線 689（§2）。
> 要驗的是「**收工 ＝ 開工**」，不是某個絕對值——本 phase 一行 Python 都沒改。

- [ ] **★ unit 檔兩處逐字相同**（`deploy/ec2/personaldocai-worker.service` 與
      `deploy/ec2/user-data.sh` 內嵌的那一段）：

```bash
diff <(awk "/<<'UNIT'/{f=1;next}/^UNIT$/{f=0}f" deploy/ec2/user-data.sh) \
     deploy/ec2/personaldocai-worker.service && echo IDENTICAL
```

  預期：印 `IDENTICAL`（`diff` 沒有輸出）。

  ⚠️ **這一條目前沒有任何自動化測試在守，只靠人工**（reviewer 2026-09-03 確認）。
  兩份不同步的後果是**安靜的**：`run-instances` 用的是 user-data 裡那一份，
  而你在 repo 裡讀到、以為正在跑的是另一份。**改 unit 一定要兩處同改，改完跑這一行。**

- [ ] **★ 機密沒外洩**（commit 前必做）：

```bash
grep -nE "i-[0-9a-f]{8,}" README.md LAUNCH.md CLAUDE.md || echo "沒有實例 id，OK"
grep -nE "[0-9]{12}" README.md LAUNCH.md CLAUDE.md || echo "沒有 12 位帳號 id，OK"
grep -niE "ollama_api_key=.|aws_secret_access_key=." README.md LAUNCH.md CLAUDE.md \
  || echo "沒有金鑰值，OK"
git status --short | grep "\.env" || echo ".env 沒有被 git 追蹤，OK"
```

  預期：四行 `OK`。

- [ ] **機器已經收工**：

```bash
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].{State:State.Name,Type:InstanceType}' --output json
```

  預期：**92-A** `{"State":"stopped","Type":"t3.xlarge"}`；
  **92-B** `{"State":"terminated","Type":"g4dn.xlarge"}`（或查無此實例）。

- [ ] **頁首開關撥回本機**（§4.7 第 2.5 步撥去雲端的那顆）：

```bash
curl -sk https://127.0.0.1:8000/settings/ai-backend    # 預期：{"backend":"local"}
```

- [ ] **`.env` 沒有留下測試期的暫時覆蓋**（做過 §4.5 那個選配小節的話）：

```bash
grep -n "^CLOUD_RESULT_TIMEOUT_SECONDS" .env    # 預期：300（不是 900）
```

- [ ] commit：

```bash
git add LAUNCH.md CLAUDE.md README.md
git status --short          # 確認 staged 的**只有這三個檔**（.env 不該出現）
git commit -m "docs: Phase 92-A EC2 真機驗收（CPU 機 t3.xlarge、worker.env 走 cloud、Demo 2／2b 通過、機器已 Stop）與三份文件——LAUNCH.md 新增 Cloud worker (EC2) 章節（CPU／GPU 兩段誠實描述）與架構圖雲端路、CLAUDE.md 指令區加 Start／Stop／SSM 看 log／兩條配額與費用、README.md 兩句 no cloud storage 改成誠實版本（測試顆數不變、端點仍 22）"
```

> ⚠️ commit 節奏由產品負責人決定（總覽 §7 鐵律 12）。**未指示前不要自己 commit**，
> 也不要把計畫檔搬進 `finish/`。`git add` 一定要明列檔案，不要 `git add -A`。
> 📌 **92-B 做完不必再 commit 文件**——三份文件在 92-A 就已經寫成兩段式的最終版本。

---
## 5. ASCII 圖：Demo 2 的完整時序（機器開著時，一張非敏感照片的一生）

```text
 你（Mac）           app 容器       worker 容器(Celery)    AWS（東京）        EC2（x86_64）
    │                   │                  │                   │        92-A: t3.xlarge（無 GPU）
    │                   │                  │                   │        92-B: g4dn.xlarge＋T4
 ①  │ curl -F file=@receipt-test.png       │                   │                     │
    ├──── POST /photos ►│                  │                   │                     │
    │                   │ 格式檢查 OK      │                   │                     │
    │                   │ 寫 data/staging/{job_id}.png（磁碟，不是 Redis）            │
    │                   │ 建 job → Celery 入列                  │                     │
    │◄── 202 {job_id, filename, content_type} ─┤               │                     │
    │   ★ 202 只代表「檔案收下了」，不代表照片已存好             │                     │
    │                   │                  │                   │                     │
 ②  │                   │                  │ 撿到 job          │                     │
    │                   │                  │ status=analyzing  │                     │
    │                   │                  │ Privacy Gate（本機、VLM 短問、不看檔名） │
    │                   │                  │   跟頁首開關走：雲端 0.6 秒／本機 1〜2 分 │
    │                   │                  │   圖的內容像收據 → NON_SENSITIVE         │
    │                   │                  │ Ec2Probe（快取 60 秒）                   │
    │                   │                  ├── DescribeInstances ►│                   │
    │                   │                  │◄──── running ───────┤                   │
    │                   │                  │ log: route=cloud verdict=NON_SENSITIVE   │
    │                   │                  │                   │                     │
 ③  │                   │                  ├─ PutObject documents/{job}/context.json ►│
    │                   │                  ├─ PutObject documents/{job}/input.png ───►│
    │                   │                  ├─ SendMessage jobs {job_id, s3_key} ─────►│
    │                   │                  │   ★ 順序鐵律：先進 S3 才發訊息（D9）     │
    │                   │                  │   ★ 訊息裡一個位元組都沒有（§0 禁止 2）  │
    │                   │                  │                   │                     │
 ④  │                   │                  │                   │◄─ ReceiveMessage ───┤
    │                   │                  │                   │   (long poll 20 秒) │
    │                   │                  │                   ├─ GetObject input ──►│
    │                   │                  │                   ├─ GetObject context ►│
    │                   │                  │                   │   看圖（最多 3 次），打哪一顆
    │                   │                  │                   │   由 worker.env 的
    │                   │                  │                   │   WORKER_VLM_BACKEND 決定：
    │                   │                  │                   │   92-A cloud → 轉送 ollama.com
    │                   │                  │                   │           kind=vlm backend=cloud
    │                   │                  │                   │           約 2 秒
    │                   │                  │                   │   92-B local → 這台自己的 Ollama
    │                   │                  │                   │           （host ollama.service＋T4）
    │                   │                  │                   │           kind=vlm backend=local
    │                   │                  │                   │           model=gemma4:e2b，幾秒
    │                   │                  │                   │◄─ PutObject result.json ─┤
    │                   │                  │                   │◄─ SendMessage results ───┤
    │                   │                  │                   │◄─ DeleteMessage jobs ────┤
    │                   │                  │                   │                     │
 ⑤  │                   │                  │◄ ReceiveMessage results {job_id} ────────┤
    │                   │                  │  （本機一直在長輪詢，最多等 300 秒）     │
    │                   │                  ├─ GetObject result.json ──────────────────►
    │                   │                  │  embed（★ 一律本機 bge-m3，kind=embed backend=local）
    │                   │                  │  INSERT photo ＋ 存原圖 ＋ 產縮圖         │
    │                   │                  ├─ DeleteObjects ×3（context/input/result）►│
    │                   │                  ├─ DeleteMessage results ──────────────────►
    │                   │                  │  刪 staging 檔 → 刪 job（成功＝job 消失） │
    │                   │                  │  log: job … 雲端結果已入庫：photo_id=N    │
    │                   │                  │                   │                     │
 ⑥  │ 待決定（N）＋1；問問題問得到；S3 documents/ 是空的；兩條佇列都 0 則              │
    │                                                                                 │
 ⛔ 收工：92-A → aws ec2 stop-instances（碟留著，Demo 3 還要用）                       │
          92-B → aws ec2 terminate-instances（80 GB 碟太貴，測完就刪）                 │
    之後的照片全部走本機（Demo 2b），使用者無感                                        │
```

📌 **整張圖只有 ④ 那一格分 92-A／92-B**。①②③⑤⑥ 兩段逐字相同——
本機這一側根本不知道遠端那台有沒有顯示卡。

---

## 6. 驗收清單

> 先載變數：`cd /Users/linjunting/personalDocAI && set -a; . ./.env; set +a; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; . /tmp/p91-vars.sh`
> （第 3 條要用 `$SG_ID`；`.env` 那把 key 一定要 unset，否則除了 `describe-instances` 以外每一條都 `AccessDenied`）

### 6.1 92-A（CPU 機）——★G3 就看這一張

| # | 要驗的事 | 指令 | 預期 |
|---|---|---|---|
| A1 | 機器建對了（機型／架構） | `aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].{T:InstanceType,A:Architecture}' --output json` | `{"T":"t3.xlarge","A":"x86_64"}` |
| A2 | 根碟是 30 GB gp3 | `aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text` 再 `aws ec2 describe-volumes --volume-ids <上一行> --region "$AWS_REGION" --query 'Volumes[0].{S:Size,T:VolumeType}' --output json` | `{"S":30,"T":"gp3"}` |
| A3 | ECR 的 `latest` 是**多架構** | `docker manifest inspect "${ECR_URI}:latest" \| python3 -c "import json,sys; print(sorted(m['platform']['architecture'] for m in json.load(sys.stdin)['manifests']))"` | `['amd64', 'arm64']` |
| A4 | IMDSv2 強制、hop limit 2（容器裡拿得到憑證） | `aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].MetadataOptions.{T:HttpTokens,H:HttpPutResponseHopLimit}' --output json` | `{"T":"required","H":2}` |
| A5 | **收工時是 stopped**（不是 terminated——Demo 3 還要用） | 同上但 `--query '…State.Name' --output text` | `stopped` |
| A6 | **SG inbound 仍是空的** | `aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG_ID" --query 'SecurityGroups[0].IpPermissions' --output json` | `[]` |
| A7 | 沒有 NAT Gateway | ``aws ec2 describe-nat-gateways --region "$AWS_REGION" --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text`` | 空 |
| A8 | 沒有 Elastic IP | `aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text` | 空 |
| A9 | **只有一台**機器（沒開重複） | `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=tag:Name,Values=personaldocai-worker Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text` | 恰一個 id |
| A10 | Budget 還在 | `aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)" --query 'Budgets[].BudgetName' --output text` | `personaldocai-budget` |
| A11 | S3 已清乾淨 | `aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"` | 沒有 `Contents` |
| A12 | 兩條佇列都空 | `aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION" --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json`（results 同理） | 兩條都 `"0"` |
| A13 | 本機切到 `ec2` 模式 | `docker compose exec worker python -c "from app.core import config; print(config.CLOUD_ROUTE, bool(config.EC2_WORKER_INSTANCE_ID))"` | `ec2 True` |
| A14 | `.env` 沒留下測試期的暫時覆蓋 | `grep -n "^CLOUD_RESULT_TIMEOUT_SECONDS" .env` | `300`（不是 900） |
| A15 | unit 兩處逐字相同 | `diff <(awk "/<<'UNIT'/{f=1;next}/^UNIT$/{f=0}f" deploy/ec2/user-data.sh) deploy/ec2/personaldocai-worker.service && echo IDENTICAL` | `IDENTICAL` |
| A16 | 文件三份都改了、而且沒改到別的 | `git diff --stat README.md LAUNCH.md CLAUDE.md` | 三個檔各只有預期的那幾段 |
| A17 | 文件沒有洩漏機密 | `grep -nE -e "i-[0-9a-f]{8,}" -e "[0-9]{12}" README.md LAUNCH.md CLAUDE.md` | 沒有輸出 |

再加下面這幾條（要看輸出，單獨列）：

- [ ] **Demo 2 全過**（§4.7 九步全部打勾）：本機 log 依序 `route=cloud verdict=NON_SENSITIVE` →
      `kind=embed backend=local` → `雲端結果已入庫：photo_id=…`、
      **EC2 log 有 `kind=vlm backend=cloud model=<雲端模型名>`**（92-A 就是 `cloud`，不是 `local`）、
      照片入待決定、問問題問得到、S3 最後是空的。

- [ ] **Demo 2b 全過**（§4.8 九步全部打勾）：Stop 之後**零設定變更**、上傳仍 **202**、
      log 有 `fallback=local reason=remote_unavailable`、S3 **零新物件**、照片照樣入庫。

- [ ] **Demo 1 也順手驗過**（§4.8 第 9 步）：敏感檔 `route=local verdict=SENSITIVE`、S3 無該 job 的物件。

- [ ] **EC2 上跑的是我們推的那一版**

```bash
CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$EC2_WORKER_INSTANCE_ID" --document-name AWS-RunShellScript \
  --parameters 'commands=["docker logs cloud-worker 2>&1 | head -n 1"]' \
  --query 'Command.CommandId' --output text)
sleep 5
aws ssm get-command-invocation --region "$AWS_REGION" --command-id "$CMD_ID" \
  --instance-id "$EC2_WORKER_INSTANCE_ID" --query 'StandardOutputContent' --output text
git rev-parse --short HEAD
```

  預期：第一段印 `cloud_worker 啟動 version=<sha> region=… bucket=… vlm=cloud model=<雲端模型名>`，
  `<sha>` 等於下一行的輸出（本輪若尚未 commit，映像是用 HEAD 的 sha 建的、ECR 另有 `<sha>-dirty` tag）。
  ⚠️ **`vlm=cloud` 也要一起看**——92-A 印 `vlm=local` ＝ 那台沒有 GPU 的機器會用自己的 CPU 硬看圖。
  ⚠️ 這一條要在機器 **running** 時做；驗完記得 Stop。

- [ ] **顆數／端點／零依賴／沒弄髒／只動該動的檔**（五條一起跑）

```bash
pytest -q                                    # 預期：689 passed ＋ 0 skipped（＝§2 開工那一次的數字 ＋ 0）
pytest -q -k "端點"                          # 預期：三顆清點測試全綠（端點仍 22、openapi 零 DELETE）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q # 預期：與第一條**逐字相同**
ls data/staging/                             # 預期：空的
git status --short docs/spec/                # 預期：零輸出（規格區全程唯讀）
diff /tmp/p92-before.txt <(git status --short)
#   預期：只多出 README.md／LAUNCH.md／CLAUDE.md 三個 " M"；
#         app/、tests/、deploy/、Dockerfile、compose.yaml 一個都不該出現
ruff format --check app tests scripts && ruff check app tests scripts   # All checks passed!
```

- [ ] **★G3 的證據表已填好交出，並且產品負責人已明示通過**（文末那張表）

### 6.2 92-B（GPU 機）——配額核准之後才跑，**不設新閘門**

| # | 要驗的事 | 指令 | 預期 |
|---|---|---|---|
| B1 | 92-A 那台已經 Terminate（同時只留一台） | `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=tag:Name,Values=personaldocai-worker Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table` | 恰一台，而且 Type 是 `g4dn.xlarge` |
| B2 | 機器建對了 | 同 A1 | `{"T":"g4dn.xlarge","A":"x86_64"}` |
| B3 | 根碟是 80 GB gp3 | 同 A2 | `{"S":80,"T":"gp3"}` |
| B4 | IMDSv2 與 hop limit | 同 A4 | `{"T":"required","H":2}` |
| B5 | **GPU 真的在用** | SSM 跑 `nvidia-smi` 與 `ollama ps`（§4.7 第 5b 步） | `nvidia-smi` 的 Processes 有 `ollama` 佔 VRAM；`ollama ps` 的 PROCESSOR ＝ `100% GPU` |
| B6 | **工人打的是自己那顆** | SSM 跑 `docker logs cloud-worker \| head -n 1` | `… vlm=local model=gemma4:e2b`（**不是** `vlm=cloud`） |
| B7 | Demo 2 再過一次 | §4.7（Demo 2b 不必重做，92-A 已驗） | 本機三行照舊；EC2 log 是 `kind=vlm backend=local model=gemma4:e2b` |
| B8 | **收工是 terminated** | 同 A5 | `terminated`（或查無此實例） |
| B9 | 沒有孤兒 volume | `aws ec2 describe-volumes --region "$AWS_REGION" --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text` | 空 |
| B10 | 本機 `.env` 收乾淨 | `grep -nE "^(CLOUD_ROUTE\|EC2_WORKER_INSTANCE_ID)=" .env` | `CLOUD_ROUTE=off`、`EC2_WORKER_INSTANCE_ID=`（空） |
| B11 | 顆數沒變、文件沒再動 | `pytest -q`；`git status --short` | 顆數同 §2；`git status` 不該因為 92-B 多出任何檔案改動 |

---

## 7. 常見陷阱

1. **`run-instances` 說 `Invalid IAM Instance Profile name`。**
   **症狀：** 名字明明跟 Phase 91 建的一模一樣，CLI 卻說無效。
   **原因：** instance profile 還沒從 IAM 傳播到 EC2 那一側（兩套控制平面，延遲幾秒到幾十秒）。
   **正解：** 用 §4.3 那個「失敗就等 15 秒再試、最多三次」的迴圈。
   ⚠️ 重試前**一定**先 `describe-instances` 確認上一次沒有偷偷開成一台
   ——開出兩台的話，兩台都在收同一條 SQS 佇列（訊息會被隨機分掉），而且**兩台都在燒點數**。

2. **機器 `running` 了，但 SSM 永遠進不去（`TargetNotConnected`）。**
   **症狀：** `describe-instance-information` 的 `PingStatus` 一直是 `None`。
   **原因：** ① IAM role 沒掛 `AmazonSSMManagedInstanceCore`；② SG 的 outbound 443 沒開對
   （SSM agent 是**主動往外連** 443）；③ 漏了 `--associate-public-ip-address`（機器沒有公有 IP）。
   **正解：** 回 Phase 91 §6 的第 2、8 條驗一次；`describe-instances` 看 `PublicIpAddress` 有沒有值。
   ⚠️ **不要因為進不去就開 inbound 22**——違反 design6 §0 禁止第 3 條，而且也修不好（問題在出站）。
   真的救不回來就 `terminate` 這台、修好 IAM／SG，再從 §4.3 重開一台
   （這是本 phase 唯一允許 terminate 的情況）。

3. **服務起不來，`systemctl status` 顯示 `activating (auto-restart)` 一直循環。**
   **症狀：** 每 10 秒重試一次，`journalctl` 塞滿同一個錯。
   **原因（依出現頻率）：** ① `worker.env` 路徑或檔名打錯（`EnvironmentFile` 找不到）；
   ② `ECR_IMAGE` 打錯——最常見是**多帶了 `:latest`**（unit 自己會接，變成 `…:latest:latest`）
   或**少了 `/personaldocai-worker`**；③ IAM role 少了 ECR 三個 pull 動作（`no basic auth credentials`）。
   **正解：** `sudo journalctl -u personaldocai-worker -n 50 --no-pager` 看第一個錯，對照上面三種；
   改完 `sudo systemctl restart personaldocai-worker`。

4. **`docker run` 回 `exec format error`。**
   **症狀：** 服務起來了，但容器立刻死掉，log 只有這一行。
   **原因：** 映像的架構跟機器對不上。**2026-09-03 改判後這件事的方向反過來了**：
   **兩段的機器都是 x86_64**（92-A `t3.xlarge`、92-B `g4dn.xlarge`），
   而 Phase 90 在這台 Mac（Apple Silicon）上建的映像是 **arm64**。
   所以 ECR 的 `latest` 必須是**多架構 manifest**（amd64 ＋ arm64），`docker pull` 才會自動挑對那一份。
   （這正是 92-A 值得先做的理由之一：那份 amd64 映像是 QEMU 建的，92-A 是它**第一次在真的 x86 上跑**。）
   **正解：** `describe-instances` 的 `Architecture` 要是 `x86_64`；
   `docker manifest inspect "${ECR_URI}:latest"` 要看得到 **兩個** `platform`（§2 ④）。
   只看到 arm64 ＝ 回 Phase 90／91 用 `docker buildx build --platform linux/amd64,linux/arm64 --push` 重推。
   ⚠️ `docker image inspect`（不帶 manifest）看的是**本機**那一份，在多架構的情況下會誤導你——要看 registry 就用 `docker manifest inspect`。

5. **Demo 2b 拿到的是 `reason=result_timeout` 而不是 `remote_unavailable`。**
   **症狀：** Stop 完馬上傳，log 寫的是逾時；而且 S3 **真的出現過**新物件。
   **原因：** `Ec2Probe` 的答案**快取 60 秒**（`EC2_PROBE_TTL_SECONDS=60`）。剛 Stop 完的
   那 60 秒內本機還拿著「running」的舊答案，照樣送出，然後等到 300 秒逾時才 fallback。
   **正解：** 這**不是 bug**（照片最後還是入庫了），只是驗到另一條路。等滿 60 秒再傳，
   或 `restart worker` 把快取清掉（它在行程記憶體裡）。
   ⚠️ **不要為了方便就去改那個 60**——它是總覽 §2.4.2 的契約值。

6. **忘記關機／刪機。**
   **症狀：** 隔天發現帳單多了、Budget 寄信來。
   **原因：** Demo 做完就去做別的事了。忘關一整天：
   **92-A `t3.xlarge` ≈ $5.2**（一個月 ≈ $160）、**92-B `g4dn.xlarge` ≈ $17**（一個月 ≈ $515），
   兩者都另加公有 IPv4 $0.005／小時。帳號已升 **Paid**——這筆會**扣卡**，不是關帳。
   ⚠️ 舊計畫的 `t4g.small` 忘記關一天只要 $0.65，很多人的直覺還停在那個數字上；這兩台都不是那個量級。
   ⚠️ **關機之後還在扣碟錢**：92-A 的 30 GB ≈ $2.9／月（Budget 內，刻意留著給 Demo 3）、
   92-B 的 80 GB ≈ $7.7／月（超過 Budget，所以整段結束要 **Terminate**，§4.9 選 B）。
   **正解：** 養成收工前跑這一行的習慣（§4.9）：
   `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=instance-state-name,Values=running --query 'Reservations[].Instances[].InstanceId' --output text`
   ——預期是**空的**。這一行也已經寫進 `LAUNCH.md` §13 與 `CLAUDE.md` 指令區。

7. **以為升 Paid 就會自動有 GPU 配額，或再開 Organizations／Control Tower。**
   **症狀：** `run-instances` 仍回 `VcpuLimitExceeded`；或帳號被捲進 Organizations 之後點數作廢、帳單更複雜。
   **原因：** 帳號**已經是 Paid**（2026-09-03）。升 Paid **不會**把 `L-DB2E81BA` 從 0 變成 4。
   Organizations／Control Tower 是另一件事，本專案用不到。
   **正解：** 配額看 §2 ② 那筆申請（狀態 `CASE_OPENED`）；不要重送、不要再開組織。
   ⚠️ 這一條**只擋 92-B**：92-A 的 `t3.xlarge` 走的是 Standard 配額（`L-1216C47A`，本帳號 8），
   完全不受影響——所以不必等它就能開工（陷阱 22）。

8. **把 `CLOUD_ROUTE` 留在 `assume`。**
   **症狀：** 機器明明關著，上傳之後卻要等 5 分鐘照片才入庫。
   **原因：** `assume` **不做任何探測**（「假設遠端開著」），所以它會照樣送出、
   然後等到 `CLOUD_RESULT_TIMEOUT_SECONDS=300` 逾時才 fallback。
   **正解：** 日常一律 `CLOUD_ROUTE=ec2`（總覽 §10 追認項 l）。`assume` 只給階段丁與除錯用。
   改完要 `restart worker`。

9. **改了 `.env` 卻沒重啟 worker（本 phase 最容易踩、而且安靜）。**
   **症狀：** `.env` 明明寫著 `CLOUD_ROUTE=ec2` 與新的 `EC2_WORKER_INSTANCE_ID`，
   worker 的行為卻還是舊的（仍然當作 `assume`、或仍然拿舊 id 去探測），**完全不報錯**。
   **原因（兩個，各自獨立）：**
   ① `app/core/config.py` 只在**行程啟動時**讀一次 `.env`（`load_dotenv()`）。
   ② Phase 89 把 `ec2` 模式的 `CloudRoute` 做成 `dependencies._ec2_cloud_route()`，
      上面有 **`@lru_cache`** ——整個行程共用同一顆物件（刻意的：探測的 60 秒快取要共用
      才有意義）。那顆物件**第一次建立時**就把 instance id 與模式吃進去了，
      之後改 `.env` 換不掉它。**只有重啟行程才會清掉那個 `lru_cache`。**
   **正解：** `docker compose -f compose.yaml -f compose.dev.yaml restart worker`，
   再用 §4.6 最後那條 `docker compose exec worker python -c …` 確認容器真的讀到新值。
   ⚠️ 重啟前先確認手上沒有正在分析的照片——做到一半被砍的任務不會重送，會永遠卡在「分析中」。

10. **把實例 id 或 bucket 名寫進 `README.md`／`LAUNCH.md`／`CLAUDE.md`。**
    **症狀：** commit 之後那些值永遠留在 git 歷史裡。
    **原因：** 寫文件時順手把自己終端機裡的真值貼進去了。
    **正解：** 三份文件**只寫變數名**（總覽 §7 鐵律 10）。
    §4.11 的四條 `grep` 就是在守這件事，**commit 前一定要跑**。

11. **每一條 `aws` 指令都 `AccessDenied`／`UnauthorizedOperation`（連 `start-instances`／`stop-instances` 都不行），只有 `describe-instances` 能動。**
    **症狀：** `An error occurred (UnauthorizedOperation) when calling the StartInstances operation …`，
    而且 `aws sts get-caller-identity` 的 Arn 結尾是 `user/personaldocai-mac`。
    **原因：** 你 `set -a; . ./.env; set +a` 之後**沒有** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`。
    `.env` 那把是**程式用的最小權限 key**（`personaldocai-mac`：S3 前綴＋兩條佇列＋`ec2:DescribeInstances`），
    而環境變數的優先序**高於** `~/.aws` 的 admin profile，CLI 就改用它了（Phase 82 §4.7 定案的兩把 key 分工）。
    **正解：** 打 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，再 `aws sts get-caller-identity`
    確認結尾變成 `user/personaldocai-admin`。本檔每一段 `set -a; . ./.env; set +a` 後面都跟著這一行，不要省。

12. **機器本身的 `aws` 指令都正常（`ExecStartPre` 的 `docker login` 也成功），容器裡的工人卻一直 `Unable to locate credentials`／`NoCredentialsError`。**
    **症狀：** `docker logs cloud-worker` 每 5 秒重複一次憑證錯誤，工人永遠拿不到訊息。
    **原因：** IMDSv2 的 `HttpPutResponseHopLimit` 是 1。容器到宿主機算**一跳**，token 的回應在半路就被丟掉，
    容器裡的 boto3 問不到 instance profile 的臨時憑證（AWS 官方文件：「容器環境請把 hop limit 提高到 2」）。
    §4.3 的 `--metadata-options HttpTokens=required,HttpPutResponseHopLimit=2` 就是在擋這個。
    **正解：** 手滑漏了**不必重建機器**：
    `aws ec2 modify-instance-metadata-options --instance-id "$EC2_WORKER_INSTANCE_ID" --http-tokens required --http-put-response-hop-limit 2 --region "$AWS_REGION"`
    然後在機器裡 `sudo systemctl restart personaldocai-worker`。§6 第 1b 條會驗 `{"T":"required","H":2}`。

13. **改了 `deploy/ec2/user-data.sh`，Stop→Start 之後機器上卻什麼都沒變。**
    **症狀：** git 裡的 unit 或 user-data 改了，重開機器後 `/etc/systemd/system/personaldocai-worker.service` 還是舊的。
    **原因：** user-data **只在第一次開機跑一次**（AWS 官方行為；就算用 `modify-instance-attribute` 換掉 user-data，
    Start 也不會重跑）。
    **正解：** 要改機器上的東西，用 Session Manager 進去改（覆蓋 `/etc/systemd/system/personaldocai-worker.service`
    → `sudo systemctl daemon-reload` → `sudo systemctl restart personaldocai-worker`），git 裡那份同步改，
    並跑 Phase 91 §6 第 15 條的 diff 確認兩份 unit 逐字相同。真的想「重跑 user-data」只有 terminate 重建一途（本 phase 不做）。

14. **以為 EC2 跟這台 Mac 的 `https://<主機名>.local:8000/` 有關係。**
    **症狀：** 想著「機器關掉之後 `.local` 網址會不會連不上」「要不要把 `.local` 加進憑證給 EC2 用」。
    **原因：** 兩件事完全不相干。`.local` 是 Bonjour（mDNS）在**區網內**幫這台 Mac 取的名字，給手機開無線鏡頭頁用的；
    EC2 在東京的機房、**沒有 inbound**、也從不主動連這台 Mac（design6 §1.2：「EC2 回呼家裡 Mac」已被否決）。
    兩邊唯一的交會點是 S3 與 SQS，全部由**本機主動連出去**。
    **正解：** `.local`、憑證、QR、手機拍照流程在本增量**一字未動**；EC2 開或關對它們零影響。

15. **（92-B 才會遇到）`run-instances` 回 `InvalidBlockDeviceMapping`（根碟太小）。**
    **症狀：** `Volume of size 30GB is smaller than snapshot 'snap-…', expect size >= 75GB`。
    **原因：** 開 GPU 機時沿用了 92-A 的 `VolumeSize=30`。GPU AMI 的快照本身就 **75 GB**
    （arm64 版 65 GB），根碟不能比它小。
    **正解：** 92-B 寫 **80**（§4.3 那三個變數要一起換）。
    ⚠️ 這也是為什麼 92-B「關機也要付 $7.7／月」——那 80 GB 是躲不掉的，所以測完 terminate。

16. **（92-B 才會遇到）`run-instances` 回 `VcpuLimitExceeded`（GPU 配額是 0）。**
    **症狀：** `You have requested more vCPU capacity than your current vCPU limit of 0 allows…`。
    **原因：** GPU 機吃的是**另一條**配額「Running On-Demand **G and VT** instances」
    （`L-DB2E81BA`），新帳號預設 0——跟 92-A 的 `t3.xlarge` 走的那條
    （`L-1216C47A`，Standard，本帳號 8）完全是兩回事。
    **正解：** 等 §2 ② 那筆申請 `APPROVED`。**重試沒有用**，配額不會自己變大，**也不要重送**。
    被拒（`DENIED`）**不影響 92-A 已經驗完的一切**（★G3 早就過了、93〜95 照常）：
    那時是**產品負責人的岔路**——永久維持 92-A 那個組合（CPU 機 ＋ `WORKER_VLM_BACKEND=cloud`），
    或整條 EC2 路先擱著（`CLOUD_ROUTE=off`）。

17. **工人服務一直 `activating (start-pre)` 然後失敗重試，journal 印 `ollama 120 秒內沒起來`。**
    **症狀：** 每 10 秒一輪，`docker logs cloud-worker` 根本沒東西（容器還沒被啟動）。
    **原因：** host 上的 `ollama.service` 沒活著——多半是 user-data 裝到一半失敗，
    或有人手動 `systemctl stop ollama` 過。
    ⚠️ **92-A 也會撞到這一條**：CPU 機雖然看圖打 `ollama.com`，unit 那條 `ExecStartPre`
    仍然會等 `127.0.0.1:11434`（兩段共用同一份 unit，刻意不為 92-A 開特例）。
    **正解：** `systemctl status ollama`；沒裝成功就補一次
    `curl -fsSL https://ollama.com/install.sh | sh` ＋ `sudo systemctl enable --now ollama`，
    然後 `curl -s http://127.0.0.1:11434/api/tags` 確認它會回答。
    📌 這是**故意設計成大聲壞掉**的：unit 的那條 `ExecStartPre` 寧可失敗重試，
    也不讓工人在 Ollama 還沒好的時候開工。
    📌 unit 有 `TimeoutStartSec=600`（systemd 預設只有 90 秒），所以「等 120 秒」那條真的等得滿；
    看到 `start operation timed out` 代表三條 `ExecStartPre` 加起來真的超過 600 秒。

18. **工人活著、也收得到訊息，但每一張圖都「看不懂」（`understood=false`），而且沒有任何錯誤 log。**
    **症狀：** 本機那邊看到的是照片入庫失敗或 fallback，EC2 這邊 `AI 結束 kind=vlm … ok=false` ×3。
    **原因（依 `WORKER_VLM_BACKEND` 分兩組）：**
    - **`cloud`（92-A）：** ① `OLLAMA_CLOUD_VLM_MODEL` 填錯——雲端**沒有** `:e2b`／`-mlx` 這些 tag，
      名字要去 `ollama.com` 確認，**不要照抄本機 `.env` 的 `VLM_MODEL`**；② `OLLAMA_API_KEY` 是舊的／被撤銷。
      （⚠️ 這兩個**留空**的話工人啟動時就會大聲退出，不會走到「看不懂」——會走到這裡的是「填了但填錯」。）
    - **`local`（92-B）：** ① `VLM_MODEL` 與機器上實際有的模型不一致——最常見是**照抄了 Mac 的
      `gemma4:e2b-mlx`**（Apple Silicon 專用標籤，Linux 上不存在）；② user-data 的 `ollama pull`
      還沒跑完（模型正在下載）或被根碟保護跳過了（§4.4）；③ `OLLAMA_BASE_URL` 寫錯，
      或 unit 少了 `--network host`（容器打不到 host 的 loopback）。
    **正解：** 先看 `docker logs cloud-worker | head -1` 的 `vlm=` 與 `model=` 是不是你要的那一組；
    `local` 的話在機器上 `ollama list` 對一次名字、`curl -s http://127.0.0.1:11434/api/tags` 確認服務；
    改完 `worker.env` 之後 `sudo systemctl restart personaldocai-worker`。

19. **（92-A）為了省錢開了 `t3.small`／`t3.large`，後來試 `local` 模式時整台卡死。**
    **症狀：** 切成 `WORKER_VLM_BACKEND=local` 之後每張圖都失敗，或 Ollama 直接被系統殺掉；
    `journalctl -u ollama` 看得到 OOM，錯誤訊息完全看不出是記憶體不夠。
    **原因：** `gemma4:e2b` 是 **7.2 GB**（`ollama list` 實查）。`cloud` 模式看不出來
    ——Ollama 閒置時**不載模型**，所以小機器上「一切正常」；一改成 `local`，
    第一次看圖就要把 7.2 GB 讀進記憶體。`t3.small`（2 GiB）與 `t3.large`（8 GiB，扣掉 OS 就不夠）都撐不住。
    **正解：** 92-A 固定 **`t3.xlarge`（16 GiB）**。一小時只差不到 $0.2，不值得為這個省。
    ⚠️ 這條也是為什麼 §4.5 那個「切 `local` 試 CPU 推論」的選配步驟寫在 `t3.xlarge` 上才成立。

20. **（92-A 選配）切了 `local` 卻沒調 Mac 的逾時，S3 留下沒人要的 `result.json`。**
    **症狀：** 本機 log 寫 `fallback=local reason=result_timeout`、照片照樣入庫（結果是對的），
    但過幾分鐘 `aws s3api list-objects-v2` 還看得到一個 `documents/<job_id>/result.json`。
    **原因：** 本機送出後最多只等 `CLOUD_RESULT_TIMEOUT_SECONDS`（預設 **300 秒**），
    而 `t3.xlarge` 沒有 GPU、`gemma4:e2b` 看一張圖**大概率超過 5 分鐘**。
    於是本機先逾時 fallback、自己看了一次圖；工人稍後才把 `result.json` 放回 S3，
    **已經沒有人會來拿**——變成孤兒物件（要等 2 天的 Lifecycle 才清掉）。
    **正解：** 做那個選配步驟**之前**把 Mac `.env` 的 `CLOUD_RESULT_TIMEOUT_SECONDS` 暫調 **900**
    （對齊 jobs 佇列的 Visibility 900）並 `restart worker`，**做完改回 300 再 restart**（§4.5）。
    已經留下的孤兒：`aws s3api delete-object --bucket "$S3_BUCKET" --key documents/<job_id>/result.json --region "$AWS_REGION"`。
    📌 這個坑 2026-09-03 在這台 Mac 上實際踩過一次，不是假想的。

21. **（92-A）用了 Deep Learning GPU AMI 開 CPU 機，白付 75 GB 的碟。**
    **症狀：** 機器跑得好好的，但 `describe-volumes` 顯示根碟 80 GB，
    月底發現關機也在扣 $7.7；而 `nvidia-smi` 印 `command not found`（`t3.xlarge` 本來就沒顯示卡）。
    **原因：** §4.2 兩個變體看混了——GPU AMI 的快照就 **75 GB**，
    所以根碟**開不到 30**（會 `InvalidBlockDeviceMapping`），只能開 ≥80。
    那顆映像裡的 NVIDIA 驅動在 `t3.xlarge` 上**一點用都沒有**。
    **正解：** 92-A 用一般 AL2023（§4.2 變體 A）＋ 30 GB。已經開錯的話最省事的是
    `terminate` 重開一台（機器上還沒有任何不可重建的東西——`worker.env` 重貼一次就好）。

22. **配額還在審，就以為「什麼都不能做」，或每天重送一次申請。**
    **症狀：** 卡在「等 AWS」，Phase 93〜95 停擺；或 `list-requested-service-quota-change-history-by-quota`
    出現好幾筆一樣的申請。
    **原因：** 把 GPU 當成整個 phase 的前置。**它只是 92-B 的前置。**
    **正解：** ① 照 92-A 用 `t3.xlarge` 把流程與兩個 Demo 全部驗完、交出 ★G3，93〜95 照常往下；
    ② 配額申請**只送一次**（同一條重送只會被合併，不會加快；官方沒有 SLA，
    從 0 要 GPU 常進人工審核〔`CASE_OPENED`〕，數小時到數天都有）；
    ③ 只用 `list-requested-service-quota-change-history-by-quota` 看狀態（§2 ②），
    看到 `APPROVED` 且 `get-service-quota` 的 `Value` ＝ 4 再回來做 92-B。
    ⚠️ **升 Paid 不會自動給 GPU 配額**（那是兩件事）；申請本身 **$0**，不是先租機器。

23. **改了 unit 檔，只改了一份。**
    **症狀：** repo 裡的 `deploy/ec2/personaldocai-worker.service` 是新的，
    但新開出來的機器上 `/etc/systemd/system/personaldocai-worker.service` 還是舊的（或反過來）。
    **原因：** unit 的內容**存在兩個地方**——獨立的 `.service` 檔（給人讀、給 diff 比）
    與 `deploy/ec2/user-data.sh` 裡那段 `<<'UNIT' … UNIT` 內嵌文字（**開機時真正被寫進機器的那一份**）。
    ⚠️ **目前沒有任何自動化測試在守這件事，只靠人工**（reviewer 2026-09-03 確認）。
    **正解：** 改 unit **一定兩處同改**，改完跑這一行（§4.11 也有）：
    `diff <(awk "/<<'UNIT'/{f=1;next}/^UNIT$/{f=0}f" deploy/ec2/user-data.sh) deploy/ec2/personaldocai-worker.service && echo IDENTICAL`
    ——預期印 `IDENTICAL`。

---

## 8. 完成後的專案狀態

### 8.1 92-A 做完之後（★G3 的當下）

**系統多了什麼：**

| 在哪裡 | 東西 |
|---|---|
| AWS（東京） | 一台 **`t3.xlarge`**（一般 AL2023／x86_64／Name tag `personaldocai-worker`／**30 GB gp3**／IMDSv2 且 hop limit 2），上面裝好 Docker ＋ host 的 `ollama.service`（`gemma4:e2b` 已拉好、閒著應門）＋ systemd 服務 `personaldocai-worker`，**現在是 stopped**（30 GB ≈ $2.9／月，留給 Phase 94 的 Demo 3） |
| 那台機器上（不進版控） | `/opt/personaldocai/worker.env`（`chmod 600`，人手動放的十一個值，含 **`WORKER_VLM_BACKEND=cloud`** ＋ `OLLAMA_API_KEY` ＋ `OLLAMA_CLOUD_VLM_MODEL`） |
| 本機（不進版控） | `.env` 的 `EC2_WORKER_INSTANCE_ID`（填了真 id）、`CLOUD_ROUTE=ec2`、`CLOUD_RESULT_TIMEOUT_SECONDS=300` |
| 本機（進 git） | `LAUNCH.md` 新章節 **13**「Cloud worker (EC2)」（§12 是 Phase 88 的「on the Mac」）＋目錄一列＋Appendix 架構圖的雲端路；`CLAUDE.md` 指令區新增「雲端工人（EC2）」一段；`README.md` 兩句改成誠實版本。**三份都寫成 CPU／GPU 兩段式的最終版本** |
| AWS 帳號設定 | 沒有變動。GPU 配額 `L-DB2E81BA` 仍是 0、申請中——**92-A 不需要它** |

**對外行為變了沒：**

**使用者看得到的部分完全沒有。** 端點仍 **22** 支、`openapi.json` 零 DELETE、
`POST /photos` 仍回 202 且 body 恰三鍵、`GET /ingest-jobs` 回應形狀不變
（使用者看不到 `route`／`privacy`）、前端一行沒改、資料庫零改動。

**唯一真正改變的是「非敏感照片在 EC2 開著時由誰看圖」**——而那件事在 log 之外
完全不可見，Demo 2b 已經親手證明過：機器關掉、什麼都不改，照片照樣進得來。

**本 phase 零 Python 變更、零測試變更。**
**顆數：開工幾顆、收工就是幾顆**（雙寫法：總覽 §9 寫 662，實測基線 689；**＋0**）。
與總覽 §2.7／§9 定案的「Phase 92 ＋0 顆」一致，**零偏離**。

**⚠️ 設計層的兩個變更都在計畫層追認過：** 2026-09-03 的 GPU 改判
（design6 **D12 作廢**、D15 的機型與映像改；總覽 §10.2 追認項 **T**）與
本次的「拆 92-A／92-B、★G3 移到 92-A 後」（總覽 §10.2 追認項 **U**）。
它們動到的是 Phase 87／88 的工人程式與 Phase 91 的 `deploy/ec2/` 三份檔，
**本 phase 只是照著用**——這裡仍然一行 Python 都沒改。

**下一步：** 先過 **★ 閘門 G3**（下面那張表）。
過了之後是 **Phase 93（`phase-93-GitHub_OIDC與部署角色.md`）**：
建 IAM OIDC provider ＋ 部署用的 role（trust 的 `sub` **精確鎖 `main` 分支、不准萬用字元**）、
把 role ARN 放進 GitHub repo secret `AWS_DEPLOY_ROLE_ARN`，
並在 `tests/integration/test_design6_error_paths.py` 追加 **4 顆**掃碼測試（總覽寫 662 → 666；
實測是「開工顆數 ＋4」）。
**93〜95 一件都不依賴 GPU**，所以不必等配額。

### 8.2 92-B 做完之後（配額核准後的某一天）

| 在哪裡 | 東西 |
|---|---|
| AWS（東京） | **沒有任何 EC2**：92-A 那台在開 92-B 之前已 Terminate，92-B 那台測完也 Terminate（費用選項 B）。SG／IAM role ＋ instance profile／S3 Gateway endpoint／ECR／S3 bucket／兩條 SQS **全部留下**（幾乎不花錢） |
| AWS 帳號設定 | GPU 配額 `L-DB2E81BA` 從 0 提高到 4（核准後永久有效，不用也不花錢） |
| 本機（不進版控） | `.env`：`EC2_WORKER_INSTANCE_ID` 清空、`CLOUD_ROUTE=off` |
| 本機（進 git） | **零改動**——三份文件在 92-A 就寫成最終版本了 |

**證明了什麼：** 同一份 user-data／unit／映像，只換機型、AMI、根碟與 `worker.env` 的一行，
看圖就從「轉送 `ollama.com`」變成「在那台機器自己的 T4 上做」，
而**本機這一側一行設定都不必改**（除了新的 instance id）。
**顆數仍然 ＋0、文件仍然零改動、沒有新的閘門。**

⚠️ **配額若被拒**：92-B 不做，其餘一切照舊——這正是拆兩段的意義。
那時 `LAUNCH.md` §13 那張「CPU box / GPU box」對照表裡的 GPU 那一欄
就永遠停在「waiting on an AWS quota」，**不必改字**（它本來就是誠實這麼寫的）。

---

## ★ 閘門 G3：交給產品負責人（**92-A 之後**、Phase 93 之前）

> 🚦 **G3 是「人」的動作，實作者不可以自己勾掉。**
> 下面每一條都只是**證據**；「看過證據、同意往下走」的那個動作必須由**產品負責人**做出來
> ——一句明確的話（口頭、對話、或 dev-prompt 檔案），而且他**必須親眼看過 Demo 2 與 Demo 2b**。
>
> 📌 **G3 在 92-A 之後，不等 GPU**（總覽 §10.2 追認項 **U**）。
> Phase 93／94／95 沒有一件事依賴 GPU：93 建 OIDC role、94 做 CD（推 ECR ＋ SSM 重啟）、
> 95 收尾與驗收包——它們要的是「真機那條路走得通」，而 92-A 已經完整證明了這件事。
> **92-B 不設新的閘門**，配額核准後任何時間做都行。

| 項目 | 內容 |
|---|---|
| **是什麼** | 「真機已經處理過一筆、Stop 之後也自動 fallback 了，可以做自動部署了」的一句話 |
| **誰確認** | **產品負責人（人）**，而且必須**親眼看過 Demo 2 與 Demo 2b** |
| **憑什麼確認** | design6 §0 戊那列：真機 Start → 處理一筆 → Stop；Stop 後下一筆自動本機。逐條指令見總覽 **§5.2**（Demo 2）與 **§5.3**（Demo 2b），本檔 §4.7／§4.8 是同一份的展開版 |
| **沒過會怎樣** | **Phase 93〜94 停擺。** 理由：CD 的失敗與工人的失敗**長得一模一樣**（都是「EC2 上沒反應」）。手動部署還沒跑通就加自動部署，除錯時分不清是「新映像沒推上去」還是「工人本來就壞」 |
| **GPU 沒過會怎樣** | **不會怎樣。** G3 不看 GPU；配額被拒的話 92-B 不做，系統永久停在 92-A 那個組合（CPU 機 ＋ `WORKER_VLM_BACKEND=cloud`），一切照常 |
| **卡住時怎麼辦** | ① 機器根本開不出來 → 先確認你在開的是 **`t3.xlarge`**（Standard 配額，本帳號 8）而不是不小心打成 GPU 機型；② 真機起不來 → 看 `deploy/ec2/user-data.sh`（回 **Phase 91**）；③ 工人起得來但拿不到訊息 → IAM instance role 的 policy（回 **Phase 91 §4.4**）；④ 拿得到訊息但看圖失敗 → 先看 `docker logs` 第一行的 `vlm=`／`model=`：92-A 應該是 `vlm=cloud`，看不懂多半是 `OLLAMA_CLOUD_VLM_MODEL` 填成本機的 tag（陷阱 18）；⑤ 一切正常但本機沒收到 → 本機 `.env` 的 `CLOUD_ROUTE=ec2` 與 `EC2_WORKER_INSTANCE_ID`（回本檔 §4.6）。⚠️ **每一輪除錯完都要記得 Stop** |

**要交給產品負責人的十二條證據**（每一條貼上你實際跑出來的輸出）：

| # | 要看的事 | 憑據 |
|---|---|---|
| 1 | 機器建對了 | `describe-instances` → **`t3.xlarge`** / `x86_64`；根碟 **30 GB** gp3 |
| 2 | **inbound 是空的**（沒有 SSH） | `describe-security-groups … IpPermissions` → `[]` |
| 3 | 只走 SSM 就管得動 | `aws ssm start-session` 真的進得去；`systemctl status` ＝ `active (running)` |
| 4 | **跑的是我們推的那一版** | `docker logs cloud-worker \| head -1` 的 `version=<sha>` ＝ `git rev-parse --short HEAD`；同一行的 `vlm=cloud model=<雲端模型名>` |
| 5 | **Demo 2 成功**（雲端路走通） | 本機依序 `route=cloud verdict=NON_SENSITIVE` → `kind=embed backend=local` → `雲端結果已入庫：photo_id=…`、**EC2 `kind=vlm backend=cloud`**、照片入待決定、問問題問得到 |
| 6 | **Demo 2 收尾乾淨** | S3 `documents/` 無 `Contents`、兩條佇列 `ApproximateNumberOfMessages` 都是 `0`、`data/staging/` 空、job 已消失 |
| 7 | **Demo 2b 成功**（關掉也能用） | Stop 之後**零設定變更**、上傳仍 **202**、log `fallback=local reason=remote_unavailable`、S3 **零新物件**、照片照樣入庫 |
| 8 | **Demo 1 仍然成立** | 敏感檔 `route=local verdict=SENSITIVE`、S3 無該 job 的物件 |
| 9 | **機器已經收工、沒有 NAT／EIP、Budget 還在** | 92-A 收工是 **Stop**（30 GB ≈ $2.9／月，在 Budget 內；Phase 94 的 Demo 3 還要用它）。§6.1 的 A5、A7、A8、A10。帳號已升 Paid |
| 10 | **測試與端點沒動** | `pytest -q` 收工顆數 ＝ 開工顆數（總覽 662／實測 689）＋ 0 skipped；三死埠顆數相同；`pytest -q -k 端點` 全綠 |
| 11 | **amd64 映像第一次在真 x86 上跑起來了** | `describe-instances` 的 `Architecture` ＝ `x86_64`；`docker manifest inspect "${ECR_URI}:latest"` 兩個平台；容器沒有 `exec format error` |
| 12 | **兩段的分工已拍板並寫進文件** | 92-A ＝ CPU 機 ＋ `WORKER_VLM_BACKEND=cloud`（**已完成**）；92-B ＝ GPU 機 ＋ `local`（**等 G and VT 配額**，`L-DB2E81BA` 目前 0、`CASE_OPENED`）。`LAUNCH.md` §13 的「CPU box / GPU box」對照表已誠實寫明現況 |

- [ ] **等產品負責人明說**（原話例：「真機兩個 demo 我都看過了，可以做 CD 了」）。

  ❌ 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正兩個 demo 都跑過了」、
  「先做 93，之後再回來補確認」。
  ❌ 也**不得**因為「GPU 還沒下來」就把 G3 往後押——G3 不看 GPU（追認項 U）。

---

## 附：本文件引用的官方文件

- [用 SSM 公開參數取最新 AMI](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-public-parameters-ami.html)
- [一般 AL2023 的 SSM 公開參數（**92-A** 用）](https://docs.aws.amazon.com/linux/al2023/ug/ec2.html#launch-via-aws-cli)
- [Deep Learning Base OSS NVIDIA Driver GPU AMI（AL2023）與它的 SSM 參數（**92-B** 用）](https://docs.aws.amazon.com/dlami/latest/devguide/gpu-ami.html)
- [`aws ec2 run-instances`（每一個旗標）](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html)
- [EC2 T3（`t3.xlarge`，**92-A** 的 CPU 機）機型](https://aws.amazon.com/ec2/instance-types/t3/)
- [EC2 G4（`g4dn`，NVIDIA T4；**92-B** 的 GPU 機）機型](https://aws.amazon.com/ec2/instance-types/g4/)
- [EC2 G5g（`g5g`，Graviton2 ＋ T4g；92-B 的省錢替代方案，未驗證）](https://aws.amazon.com/ec2/instance-types/g5g/)
- [Service Quotas：申請提高配額（Standard 走 `L-1216C47A`、G and VT 走 `L-DB2E81BA`）](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html)
- [`aws service-quotas request-service-quota-increase`](https://docs.aws.amazon.com/cli/latest/reference/service-quotas/request-service-quota-increase.html)
- [EC2 On-Demand vCPU 配額（G 系列走 `L-DB2E81BA` 那一條）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html#ec2-on-demand-instances-limits)
- [Ollama on Linux（官方安裝腳本、`nvidia-smi` 驗證驅動；**不安裝** NVIDIA kernel driver）](https://docs.ollama.com/linux)
- [Ollama GPU（Nvidia 驅動 ≥550）](https://docs.ollama.com/gpu)
- [在 EC2 Linux 安裝 NVIDIA 驅動（Tesla／AMI 選項）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html)
- [Ollama on Linux GitHub 鏡像](https://github.com/ollama/ollama/blob/main/docs/linux.md)
- [`docker run --network host`（Linux 上共用 host 網路命名空間）](https://docs.docker.com/engine/network/drivers/host/)
- [`docker manifest inspect`（看 registry 上的多架構 manifest）](https://docs.docker.com/reference/cli/docker/manifest/)
- [EC2 執行個體生命週期（Stop 與 Terminate 的差別）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [`aws ec2 wait instance-running` / `instance-stopped`](https://docs.aws.amazon.com/cli/latest/reference/ec2/wait/instance-running.html)
- [EC2 instance metadata service v2（`HttpTokens=required`）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html)
- [EC2 instance metadata 存取注意事項（容器環境請把 hop limit 提高到 2）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html#imds-considerations)
- [`aws ec2 modify-instance-metadata-options`（事後補 hop limit）](https://docs.aws.amazon.com/cli/latest/reference/ec2/modify-instance-metadata-options.html)
- [Session Manager plugin：macOS 安裝方式（官方只提供 .pkg 與 .zip；Homebrew cask 是社群維護）](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html)
- [AL2023 用 SSM 參數啟動（含 2026-08-17 default 核心 6.1→6.18 的公告）](https://docs.aws.amazon.com/linux/al2023/ug/ec2.html#launch-via-aws-cli)
- [EC2 On-Demand 定價（`t3.xlarge`／`g4dn.xlarge` 東京單價以此頁當天數字為準）](https://aws.amazon.com/ec2/pricing/on-demand/)
- [EBS gp3 磁碟區](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html)
- [SSM Session Manager（不開 SSH 也能進 shell）](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
- [安裝 `session-manager-plugin`](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
- [`aws ssm describe-instance-information`（`Key=InstanceIds` 過濾器）](https://docs.aws.amazon.com/cli/latest/reference/ssm/describe-instance-information.html)
- [SSM Run Command（`AWS-RunShellScript`）](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [SSM Agent 預裝的 AMI 清單（AL2023 在內）](https://docs.aws.amazon.com/systems-manager/latest/userguide/ami-preinstalled-agent.html)
- [EC2 user-data（以 root 執行、只跑第一次、log 在 `/var/log/cloud-init-output.log`）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [公有 IPv4 收費說明（為什麼不配 Elastic IP）](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)
- [AWS Free Tier FAQ（Free plan、點數、關帳）](https://aws.amazon.com/free/free-tier-faqs/)
- [AWS Budgets（建預算警報）](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
- [S3 Lifecycle 設定（`documents/` 2 天過期）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
