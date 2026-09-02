# Phase 92：EC2 真機、Demo 2／2b、Stop 守則與三份文件 ＋ ★ 閘門 G3

> 🎯 **提醒：這是 side project，不要過度設計。**
> **本 phase 特別不要做的四件事：**
> ① **不要 `terminate-instances`**（那是銷毀、不可逆）。收工一律 `stop-instances`。
> ② 不要為了「除錯方便」開 inbound 22（SSH）——管理只走 SSM Session Manager。
> ③ 不要把機器留著開機過夜（點數整晚在燒；每個 Demo 結尾都有 Stop）。
> ④ 不要為了讓 fallback 快一點就去改 `EC2_PROBE_TTL_SECONDS`／`CLOUD_RESULT_TIMEOUT_SECONDS`
>    ——那兩個值是總覽 §2.4.2 的契約（60／300）。

```text
┌─ ⛔ 開工前檢查 ────────────────────────────────────────────────────
│ ★ **★G2 早在 Phase 91 之前就已由產品負責人明示通過**（見 phase-91 檔頭那個框）。
│   本 phase 不再有新的閘門要等——**★G3 在本 phase「之後」**（文末那張表）。
│ ★ Phase 91 必須已經完成：SG、S3 Gateway endpoint、IAM role ＋ instance profile、
│   ECR repo 與第一次手動 push，以及 deploy/ec2/ 三份檔。缺一個，§4.3 就跑不動。
│ ⛔ 本 phase 的第一行 `run-instances` 是整個增量六**第一個真的花錢**的指令。
│   下去之前先確認 Budget 還在（Phase 82 建的 personaldocai-budget，每月 $5）。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 用 Phase 91 備好的周邊，真的開一台 `t4g.small`（AL2023 arm64）、
> 用 **Session Manager**（不開 SSH）進去放好 `/opt/personaldocai/worker.env`、
> 把工人服務跑起來並看到 `version=<sha>`；然後把本機 `.env` 切成 `CLOUD_ROUTE=ec2`，
> 親手跑一次 **Demo 2**（Start → 非敏感走雲端 → 照片進待決定 → 問得到）與
> **Demo 2b**（Stop → 再傳一張 → 自動走本機、S3 零新物件）；
> 做完 **Stop**，最後把 `LAUNCH.md`（新章節 **13**）／`CLAUDE.md`／`README.md` 三份文件改成誠實的現況。

**為什麼要做這個：**

到目前為止，「雲端這條路」全部是在這台 Mac 上模擬的——Phase 88 用 `python -m` 跑工人、
Phase 90 用容器跑工人，兩次都是**左手交給右手**，一點壓力都沒卸掉，
也還沒證明「工人在一台**看不到螢幕**的機器上也活得下去」。

這一份把工人真的搬到別人的機房，然後做兩件**同等重要**的事：

1. **Demo 2**：機器開著的時候，非敏感照片真的在 EC2 上被看懂，結果回家入庫。
2. **Demo 2b**：機器關掉之後，**什麼設定都不改**，照片照樣進得來——
   只是回到本機看圖。這一條比 Demo 2 更重要，因為 **EC2 平常是關著的**
   （產品負責人要卡片 $0），所以「關著也能用」才是這個系統 99% 的時間裡的樣子。

最後，文件要跟現實一致：`README.md` 現在寫著「No cloud storage — photos never leave
your machine」，做完這個增量之後**那句話不再完全為真**（非敏感檔會短暫經過 S3）。
留著不改就是騙人，所以本 phase 一併改掉。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **AMI（Amazon Machine Image）** | 「一台機器的出廠映像」。開 EC2 時要選一個 AMI，它決定裡面是哪個作業系統。AMI id 長得像 `ami-0123…`，**每個區域的 id 不一樣**、而且會隨著 AWS 更新而變 |
| **SSM 公開參數** | AWS 幫每個 AMI 系列維護的一個「永遠指向最新版」的名字，例如 `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64`。查它就拿得到當下最新的 AMI id，不必自己去 Console 翻 |
| **`t4g.small`** | AWS 自研 ARM（Graviton）架構的小型機：2 vCPU、2 GB 記憶體。因為是 ARM，映像必須是 `linux/arm64`（Phase 90 建的那一個） |
| **block device mapping（磁碟對應）** | 「這台機器要掛哪些硬碟、每顆多大、什麼型別」。本專案只要一顆 8 GB 的 `gp3` 根碟 |
| **gp3** | EBS 的一種硬碟型別（通用 SSD 第 3 代）。比舊的 `gp2` 便宜一點、效能也夠，**是現在的預設選擇** |
| **IMDS / `HttpTokens=required`（IMDSv2）／`HttpPutResponseHopLimit=2`** | 機器內部有一個「問自己是誰」的服務（instance metadata service，位址 `169.254.169.254`），boto3 就是靠它拿 instance profile 的臨時憑證。`HttpTokens=required` ＝**強制用比較安全的第 2 版**（要先換一個 token 才能問）。`HttpPutResponseHopLimit=2` ＝那個 token 的回應**准許多走一個網路節點**：我們的工人跑在 **Docker 容器**裡，容器到宿主機算一跳，預設的 1 跳會讓容器裡的 boto3 **永遠拿不到憑證**（AWS 官方文件明文：容器環境請設 2） |
| **`--associate-public-ip-address`** | 「開機時自動給我一個公有 IP」。機器**沒有公有 IP 就出不了網**（S3／SQS／ECR／SSM／ollama.com 全部不通）。Phase 91 §4.1 挑的子網本來就會自動配（`MapPublicIpOnLaunch=true`），明寫是雙保險。⚠ **2024-02-01 起所有公有 IPv4 都要錢**：$0.005／小時（整月開著約 $3.6）——但這種「自動配」的 IP 只在機器 **running** 時存在，**Stop 之後自動釋放、就不再計費**；Elastic IP 則是配了就每小時扣、不管有沒有掛在跑著的機器上 |
| **SSM Session Manager** | 不開 SSH 也能拿到那台機器 shell 的服務。從 Mac 上 `aws ssm start-session --target <id>` 就進去了，權限走 IAM，不必管金鑰 |
| **`session-manager-plugin`** | `aws ssm start-session` 需要的一個額外外掛（AWS CLI 本身不含）。Mac 上用 Homebrew 裝 |
| **`systemctl status` / `journalctl`** | 看一個 systemd 服務現在好不好（`status`）、以及它從頭到尾印了什麼（`journalctl -u <服務名>`）。服務起不來時這兩個是第一現場 |
| **`/var/log/cloud-init-output.log`** | user-data 開機腳本的輸出都在這個檔裡。機器起來卻「什麼都沒裝」時，第一個要看它 |
| **Stop vs Terminate** | **Stop ＝ 關機**：硬碟（EBS）留著，開回來東西都還在，只有硬碟繼續小額計費，公有 IP 會被收回。**Terminate ＝ 銷毀**：整台連硬碟一起消失，**不可逆**。本專案**一律 Stop** |
| **EBS** | EC2 的虛擬硬碟。Stop 之後運算費停了，但 EBS 仍按 GB 從**點數**扣（8 GB gp3 一個月大約 $0.8，很小但不是零） |
| **探測快取 TTL（`EC2_PROBE_TTL_SECONDS`）** | 本機每次要送雲端之前會問 AWS「那台機器 running 嗎」，答案**快取 60 秒**（不然每張圖都打一次 API）。所以剛 Stop 完的 60 秒內，本機可能還以為它開著——Demo 2b 會遇到，見 §4.8 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D11** | 「EC2 只當工人…Security group inbound 全關。出站 TCP 443」 | §4.3 用 Phase 91 那個 SG；§4.5 只走 SSM 進機器，全程零 SSH |
| **D12** | 「EC2 看圖一律 Ollama Cloud（實例無 GPU）」 | §4.5 的 `worker.env` 只放 `OLLAMA_API_KEY` 與 `OLLAMA_CLOUD_VLM_MODEL`，**不裝 Ollama** |
| **D10** | 「遠端關掉＝fallback 本機」 | §4.8 的 **Demo 2b**：Stop 之後**什麼設定都不改**，照片照樣入庫 |
| **D13** | 「拉回 `result.json` 後，embedding 與 INSERT／原圖／縮圖仍在本機」 | §4.7 Demo 2 的第 5 步：本機 log 要有 `kind=embed backend=local` |
| **D15** | 「Free plan…用完 EC2 就 **Stop**。映像 `linux/arm64`，機型 t4g.small」 | §4.3 的機型與 AMI；§4.9 的 **Stop 守則** |
| **§7 全節** | Free plan 約束、公有子網＋自動公有 IPv4、禁止 NAT、inbound 全關、Budget | §4.3 的旗標；§4.9；§4.10 寫進三份文件 |
| **§3「不做」最後一列前** | 「Free plan 操作約束寫進 `LAUNCH.md`／`CLAUDE.md`」 | §4.10 |
| **§12 Demo 2** | 「EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉；照片進待決定；詢問能問到」 | §4.7（逐條照抄總覽 §5.2） |
| **§12 Demo 2b** | 「EC2 Stop 後上傳非敏感；**不必改任何設定**；進度與入庫與增量五相同；S3 不出現新物件」 | §4.8（逐條照抄總覽 §5.3） |
| **總覽 §10 追認項 h** | 「EC2 上的機密用 **Session Manager 手動**建 `/opt/personaldocai/worker.env`（`chmod 600`），**不用** Parameter Store」 | §4.5 |
| **總覽 §10 追認項 l** | 「`CLOUD_ROUTE=assume` 只給階段丁與除錯；**戊之後日常用 `ec2`**」 | §4.6 把 `.env` 從 `assume` 改成 `ec2` |
| **總覽 §10 追認項 e** | 「『跑的是不是新映像』靠 `WORKER_VERSION` 的 log 驗」 | §4.5 最後一步要看到 `version=<sha>` |
| **總覽 §2.7（Phase 92）、§3.8** | `README.md` 第 11 行與第 635 行「no cloud storage」不再完全為真——「兩句改誠實」 | §4.10 第 3 小節（英文改寫） |

> ⚠️ **「追認項 h」與「追認項 l」是計畫層的裁決，不是 design6 自己寫的字**（總覽 §10 明文）。

---

## 2. 前置條件

**依賴：Phase 91 全部完成（★G2 更早之前已通過）。**

**開工基線：662 passed ＋ 0 skipped**（總覽 §9：Phase 90／91 收工都是這個數字）。
**本 phase 新增 0 顆測試**——它做的是真機操作與文件，收工時顆數**仍是 662**。

**開工前一次驗完：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # ★ .env 那把是程式用的最小權限 key；CLI 要回去用 ~/.aws 的 admin
. /tmp/p91-vars.sh 2>/dev/null || true      # Phase 91 存的 SG_ID／SUBNET_ID… 若還在就載回來
aws sts get-caller-identity --query Arn --output text   # 預期結尾：user/personaldocai-admin

# ① 顆數基線（本 phase 不會改變它）
pytest -q                                    # 預期：662 passed，0 skipped

# ② Phase 91 的四樣東西都在（缺一個 §4.3 就跑不動）
aws ec2 describe-security-groups --region "$AWS_REGION" \
  --filters Name=group-name,Values=personaldocai-worker-sg \
  --query 'SecurityGroups[0].{Id:GroupId,In:IpPermissions}' --output json
# 預期：{"Id":"sg-…","In":[]}   ← inbound 必須是空陣列

aws iam get-instance-profile --instance-profile-name personaldocai-worker-role \
  --query 'InstanceProfile.Roles[].RoleName' --output text     # 預期：personaldocai-worker-role

aws ecr describe-images --region "$AWS_REGION" --repository-name personaldocai-worker \
  --query 'imageDetails[?imageTags].imageTags[]' --output json # 預期：含 "latest" 與某個 <sha>

ls -l deploy/ec2/user-data.sh deploy/ec2/personaldocai-worker.service \
      deploy/ec2/worker.env.example

# ③ 變數（Phase 91 §4.1 那五個 ＋ SG／ECR）
echo "region=$AWS_REGION"                    # 預期：region=ap-northeast-1
echo "subnet=${SUBNET_ID:?請回 phase-91 §4.1 重查} sg=${SG_ID:?同上}"
echo "ecr 尾巴=${ECR_URI##*/}"               # 預期：personaldocai-worker

# ④ 分支與快照
git branch --show-current                    # 預期：main
git status --short > /tmp/p92-before.txt
```

> ⚠️ **`${SUBNET_ID:?訊息}` 是 bash 的「沒設就報錯」寫法。** 變數是空的時候
> 它會印出那句訊息並讓指令失敗，比默默用空字串往下跑好得多
> （空字串塞進 `--subnet-id` 會得到一個看不懂的 `InvalidParameterValue`）。

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

### 做

1. 裝 `session-manager-plugin`（Mac 上一次性）。
2. 查最新的 AL2023 **arm64** AMI id。
3. `run-instances` 開一台 `t4g.small`（帶 user-data、instance profile、SG、公有 IP、8 GB gp3、IMDSv2 且 hop limit 2）。
4. 等 `running`、等 **SSM 上線**。
5. Session Manager 進去建 `/opt/personaldocai/worker.env`（`chmod 600`）、
   `systemctl start`、看 `systemctl status` 與 `docker logs cloud-worker` 的 `version=<sha>`。
6. 本機 `.env` 改 `EC2_WORKER_INSTANCE_ID=<id>`、`CLOUD_ROUTE=ec2`、
   `CLOUD_RESULT_TIMEOUT_SECONDS=300`，重啟本機 worker。
7. **Demo 2**（總覽 §5.2 逐條）。
8. **Demo 2b**（總覽 §5.3 逐條）。
9. **Stop**（＋ Stop 守則寫進文件）。
10. 三份文件：`LAUNCH.md` 新章節 **13**（§12 已被 Phase 88 用掉）＋ Appendix 架構圖、`CLAUDE.md` 指令區、
    `README.md` 第 11 行與第 635 行改成誠實版本。
11. 交出 **★ 閘門 G3**（文末那張表）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| `aws ec2 terminate-instances` | **不可逆**：整台連 EBS 一起消失，`worker.env` 要重放、user-data 要重跑。收工一律 `stop-instances`（§4.9） |
| 開 inbound 22（SSH）或裝任何 SSH 金鑰 | design6 §0 禁止第 3 條、D11。`run-instances` 也**不帶 `--key-name`**——沒有金鑰就沒有「偷偷開 SSH」這個選項 |
| 在 EC2 上裝 Ollama、Postgres、Redis、Celery | design6 D11／D12／§3「不做」明文。機器沒有 GPU，看圖固定打 `ollama.com` |
| 配 Elastic IP 讓它有固定 IP | 總覽 §2.8 禁止清單。沒有人會主動連進來（inbound 空），不需要固定 IP；而且 EIP **配了就每小時 $0.005 一直扣、不管機器有沒有在跑**（2024-02-01 起），跟「常態 Stop」的用法正好相反——自動配的公有 IP 則是 Stop 就釋放、就不算錢 |
| 建 NAT Gateway | design6 §0 禁止第 4 條。公有子網 ＋ 公有 IP 本來就出得去 |
| 為了省事把 `CLOUD_ROUTE` 留在 `assume` | 總覽 §10 追認項 l：`assume` 不做探測，機器關著時它會傻傻送出、等到逾時（5 分鐘）才 fallback。日常一定要 `ec2` |
| 改 `EC2_PROBE_TTL_SECONDS`（60）或 `CLOUD_RESULT_TIMEOUT_SECONDS`（300） | 總覽 §2.4.2 的契約值。Demo 2b 那 60 秒「探測還說 running」是**預期行為**，不是 bug（§4.8 有教怎麼處理） |
| 改任何 `app/` 底下的程式碼、測試、`Dockerfile`、`compose.yaml` | 本 phase **零產品程式碼變更、零測試變更**。真的發現工人有 bug → 回 Phase 87／88 修 |
| 改 `docs/spec/` | 總覽 §7 鐵律 16：本增量規格區**一個字都不動** |
| 把 `README.md`／`LAUNCH.md` 改成中文 | 那兩份自 2026-08-27 起是**英文**（總覽 §3.8）。`CLAUDE.md` 與 `docs/` 才是繁體中文 |
| 把實例 id、帳號 id、bucket 名寫進任何要 commit 的檔 | 總覽 §7 鐵律 10。文件只寫**變數名**；實例 id 放不入版控的 `.env` |

---

## 4. 實作步驟

> 📌 **本 phase 沒有測試可以先紅**（做的是真機操作與文件）。
> 體例是：**指令 → 每個旗標的用途 → 預期輸出 → 做錯了怎麼退回 → 費用影響。**

> ⏱️ **時間與費用預估：** §4.1〜§4.6 約 20 分鐘、Demo 2 約 5 分鐘、Demo 2b 約 5 分鐘
> （加上等本機 gemma4 看圖的 64〜88 秒）。機器總共開機約 40 分鐘，
> `t4g.small` 在東京約 **$0.022／小時**（on-demand；以 AWS 定價頁當天的數字為準，附錄有連結）
> ＋ 公有 IPv4 **$0.005／小時**（只在 running 時算），也就是這一整份 phase 的運算費約 **$0.02**（兩分）。
> 真正該擔心的不是這個數字，而是**忘記 Stop**——放一整天約 $0.65，一個月不關約 $20。

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

### 4.2 查最新的 AL2023 arm64 AMI

- [ ] 查：

```bash
AMI=$(aws ssm get-parameters --region "$AWS_REGION" \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query 'Parameters[0].Value' --output text)
echo "AMI=$AMI"
```

  預期：`AMI=ami-0123456789abcdef0`

  | 部分 | 用途 |
  |---|---|
  | `aws ssm get-parameters` | 讀 SSM Parameter Store。**這些 `/aws/service/…` 開頭的是 AWS 自己維護的公開參數**，任何人都讀得到、不必特別權限 |
  | `al2023-ami-**kernel-default**-arm64` | 「AL2023、預設核心、ARM 64 位元」。**`arm64` 那一段不能寫錯**——寫成 `x86_64` 的話會開出一台 Intel 機器，然後你的 arm64 映像在上面 `docker run` 會回 `exec format error`（而那個訊息完全看不出跟架構有關） |

  ⚠️ **`kernel-default` 是「隨 AWS 走」的意思。** AWS 在 **2026-08-17** 把 default 從
  6.1 換成了 6.18，所以今天查到的 AMI 跟上個月不一樣是**正常的**。
  真的想釘死某個核心版本就改用 `al2023-ami-kernel-6.1-arm64`——
  本專案不需要（工人只跑一個 Docker 容器，不碰核心）。

  **做錯了怎麼退回：** 這是純查詢，沒有副作用，重跑就好。

### 4.3 開機器（★ 第一個真的花錢的指令）

- [ ] 跑（**注意 `--user-data file://…` 讀的是 Phase 91 寫好的那個腳本**）：

```bash
INSTANCE_ID=$(aws ec2 run-instances --region "$AWS_REGION" \
  --image-id "$AMI" \
  --instance-type t4g.small \
  --subnet-id "$SUBNET_ID" \
  --security-group-ids "$SG_ID" \
  --iam-instance-profile Name=personaldocai-worker-role \
  --associate-public-ip-address \
  --user-data file://deploy/ec2/user-data.sh \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=8,VolumeType=gp3}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]' \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2 \
  --query 'Instances[0].InstanceId' --output text)
echo "INSTANCE_ID=$INSTANCE_ID"
```

  **每一個旗標：**

  | 旗標 | 用途 |
  |---|---|
  | `--image-id "$AMI"` | 用哪個出廠映像（§4.2 查到的 AL2023 arm64） |
  | `--instance-type t4g.small` | 機型（design6 D15 指定）。`t4g` ＝ ARM；`small` ＝ 2 vCPU／2 GB |
  | `--subnet-id "$SUBNET_ID"` | 放在哪個子網（Phase 91 §4.1 查到的**公有**子網） |
  | `--security-group-ids "$SG_ID"` | 掛哪個防火牆（Phase 91 §4.2 建的，inbound 空、outbound 只有 443） |
  | `--iam-instance-profile Name=…` | 掛哪個 instance profile。**注意寫法是 `Name=<名字>`**（不是直接接名字），這是 AWS CLI 的 shorthand 語法 |
  | `--associate-public-ip-address` | 開機自動給一個公有 IP。機器**沒有公有 IP 就出不了網**（S3／SQS／ECR／SSM／ollama.com 全部不通）；我們的子網本來就會自動配，明寫是雙保險。⚠ 公有 IPv4 **$0.005／小時**（2024-02-01 起），但只在 running 時算——Stop 之後自動釋放、不再計費 |
  | `--user-data file://deploy/ec2/user-data.sh` | 第一次開機要跑的腳本（Phase 91 寫的：裝 Docker、建目錄、裝好 systemd 服務但**不 start**） |
  | `--block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=8,VolumeType=gp3}'` | 根碟：8 GB、gp3。`/dev/xvda` 是 AL2023 的根碟裝置名。不寫的話會用 AMI 的預設（通常也是 8 GB，但明寫比較清楚） |
  | `--tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]'` | 給機器貼一個 `Name` 標籤，Console 上才看得懂它是誰 |
  | `--metadata-options HttpTokens=required,HttpPutResponseHopLimit=2` | `HttpTokens=required` ＝強制 **IMDSv2**（比較安全的那一版 metadata 服務，boto3 支援得很好）。`HttpPutResponseHopLimit=2` ＝**一定要寫**：工人跑在 Docker 容器裡，容器到宿主機多一跳；hop limit 停在 1 的話容器裡的 boto3 **拿不到 instance profile 的憑證**（症狀：工人 log 一直重複 `NoCredentialsError`／`Unable to locate credentials`，而機器本身的 `aws` 指令卻好好的）。AWS 官方文件明文「容器環境請設 2」；總覽 §10.2 追認項 O 定案（陷阱 12） |
  | `--query 'Instances[0].InstanceId'` | 只取新機器的 id |

  ⚠️ **不需要 `--count 1`**（預設就是 1）。
  ⚠️ **不要加 `--key-name`**：那是 SSH 金鑰，我們**不開 SSH**（design6 D11）。
  ⚠️ **不要加 `--network-interfaces`**：那個旗標一旦出現，`--subnet-id`／`--security-group-ids`／
  `--associate-public-ip-address` 三個就必須改寫到它裡面去，否則會衝突。
  我們用的「三個都在最上層」正是 AWS 官方文件的範例寫法。

  預期：`INSTANCE_ID=i-0123456789abcdef0`

- [ ] **如果失敗了：`InvalidParameterValue … Invalid IAM Instance Profile name`**

  這是 **instance profile 還沒傳播到 EC2** 那一側（Phase 91 §7 陷阱 2 講的那個）。
  **名字完全正確**，只是還沒傳到。等 15 秒再試，最多三次：

```bash
for i in 1 2 3; do
  INSTANCE_ID=$(aws ec2 run-instances --region "$AWS_REGION" \
    --image-id "$AMI" --instance-type t4g.small \
    --subnet-id "$SUBNET_ID" --security-group-ids "$SG_ID" \
    --iam-instance-profile Name=personaldocai-worker-role --associate-public-ip-address \
    --user-data file://deploy/ec2/user-data.sh \
    --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=8,VolumeType=gp3}' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=personaldocai-worker}]' \
    --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2 \
    --query 'Instances[0].InstanceId' --output text 2>/tmp/p92-run-instances.err) && break
  echo "第 $i 次失敗：$(head -c 300 /tmp/p92-run-instances.err)"
  grep -q "Invalid IAM Instance Profile" /tmp/p92-run-instances.err || break   # 別種錯誤：不要盲目重試，先看訊息
  echo "（instance profile 還沒傳播到 EC2 那一側，等 15 秒再試…）"; sleep 15
done
echo "INSTANCE_ID=$INSTANCE_ID"
```

  ⚠️ **重試之前先確認上一次真的沒開成機器**（不然會開出兩台，兩台都在收同一條佇列、也都在燒點數）：

```bash
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=tag:Name,Values=personaldocai-worker \
            Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].InstanceId' --output text
```

  預期：**恰好一個** id。看到兩個就把多的那台 `terminate`
  （**這是唯一一種該用 terminate 的情況**：一台剛開出來、什麼都還沒放的多餘機器）：
  `aws ec2 terminate-instances --instance-ids <多的那個> --region "$AWS_REGION"`

  **費用開始計時了。** 從這一刻起 `t4g.small` 約 **$0.022／小時**（＋公有 IPv4 $0.005／小時）從點數扣，
  EBS 8 GB gp3 約 **$0.8／月**（Stop 之後運算費停、EBS 繼續）。

### 4.4 等機器起來、等 SSM 上線

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

### 4.5 進機器放 `worker.env`，把工人跑起來

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

- [ ] **先關掉這個 shell 的歷史紀錄**（在機器裡面；等一下要打的 `tee` 指令含 `OLLAMA_API_KEY`，
      bash 預設會把整段——連 heredoc 的內容——一起寫進 `~/.bash_history`）：

```bash
unset HISTFILE
```

  這一行之後，本次 session 打的東西**一個字都不會落地**（只對這一次 session 有效，離開就沒了）。

- [ ] **先確認 user-data 真的跑完了**（在機器裡面）：

```bash
sudo tail -5 /var/log/cloud-init-output.log
systemctl is-enabled personaldocai-worker
docker --version
```

  預期：log 最後一行是
  `user-data 完成：docker 已裝、personaldocai-worker 已 enable（尚未 start，等 worker.env）`；
  `is-enabled` 印 `enabled`；`docker --version` 印版本號。
  三個有任何一個不對 → `sudo cat /var/log/cloud-init-output.log` 從頭看
  （user-data 有 `set -x`，每一行都印得出來，很容易找到卡在哪）。

- [ ] **建 `/opt/personaldocai/worker.env`**（★ 這是唯一一次要把機密打進機器）：

  在機器裡面執行下面這一段。`sudo tee` 會把接下來輸入的內容寫進那個檔，
  **最後一行單獨打 `EOF` 再按 Enter** 才會結束：

```bash
sudo tee /opt/personaldocai/worker.env > /dev/null <<'EOF'
AWS_REGION=
ECR_REGISTRY=
ECR_IMAGE=
S3_BUCKET=
SQS_JOBS_QUEUE_URL=
SQS_RESULTS_QUEUE_URL=
OLLAMA_API_KEY=
OLLAMA_CLOUD_VLM_MODEL=
EOF
sudo chmod 600 /opt/personaldocai/worker.env
sudo ls -l /opt/personaldocai/worker.env
```

  ⚠️ **上面每一行的等號後面要填上真值**——本文件**只寫變數名，永遠不寫值**
  （總覽 §7 鐵律 10）。八個值從哪裡來：

  | 變數 | 值從哪裡來 |
  |---|---|
  | `AWS_REGION` | 固定 `ap-northeast-1`（總覽 §2.8：全部東京） |
  | `ECR_REGISTRY` | Phase 91 §4.6 的 `$ECR_REGISTRY`（長相 `<12碼帳號>.dkr.ecr.ap-northeast-1.amazonaws.com`） |
  | `ECR_IMAGE` | Phase 91 §4.6 的 `$ECR_URI`（上面那串再接 `/personaldocai-worker`；**不含 `:tag`**——unit 檔自己接 `:latest`） |
  | `S3_BUCKET`／兩個 `SQS_*_QUEUE_URL` | 本機 `.env` 裡的同名變數（Phase 84／85 填的） |
  | `OLLAMA_API_KEY`／`OLLAMA_CLOUD_VLM_MODEL` | 本機 `.env` 裡的同名變數 |

  💡 **怎麼在 Mac 上先把八行組好再貼進去**（避免在機器裡一個一個打錯）：
  在**另一個 Mac 終端機視窗**跑下面這段，它會把八行印在螢幕上，你複製之後貼進 Session Manager：

```bash
cd /Users/linjunting/personalDocAI && set -a; . ./.env; set +a
. /tmp/p91-vars.sh
printf 'AWS_REGION=%s\nECR_REGISTRY=%s\nECR_IMAGE=%s\nS3_BUCKET=%s\nSQS_JOBS_QUEUE_URL=%s\nSQS_RESULTS_QUEUE_URL=%s\nOLLAMA_API_KEY=%s\nOLLAMA_CLOUD_VLM_MODEL=%s\n' \
  "$AWS_REGION" "$ECR_REGISTRY" "$ECR_URI" "$S3_BUCKET" \
  "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL" "$OLLAMA_API_KEY" "$OLLAMA_CLOUD_VLM_MODEL"
```

  ⚠️ **這一段會把 `OLLAMA_API_KEY` 印在終端機上。** 貼完之後把那個視窗關掉（或 `clear`），
  **不要截圖、不要貼進任何文件或 commit**。
  ⛔ **這個檔裡沒有 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`**——EC2 用 instance profile
  （Phase 91 掛的），boto3 自己去機器的 metadata 服務拿臨時憑證；在 EC2 上放長期金鑰
  多此一舉而且更危險。⛔ **也沒有 `AWS_ENDPOINT_URL`**（那只用在 pytest 的死埠安全網）。

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
  看到 `Active: activating (start-pre)` ＝ **還在拉映像**（第一次要把整份 arm64 映像從 ECR 抓下來，
  同區域通常十幾秒到一分鐘），再等 30 秒重跑 `systemctl status` 就好。

  出現 `Active: activating (auto-restart)` 或 `failed` → 看完整 log：

```bash
sudo journalctl -u personaldocai-worker -n 50 --no-pager
```

  最常見的三種：
  ① `EnvironmentFile` 找不到 → `worker.env` 的路徑或檔名打錯，`ls /opt/personaldocai/` 對一次。
  ② `docker login` 失敗（`no basic auth credentials`）→ IAM role 少了 ECR 那三個動作，回 Phase 91 §4.4。
  ③ `docker pull` 失敗（`repository does not exist`）→ `ECR_IMAGE` 打錯（少了 `/personaldocai-worker`，
     或多帶了 `:latest`）。
  ④ `start operation timed out`／`Start-pre operation timed out` → 第一次 `docker pull` 超過 systemd
     預設的 90 秒啟動上限（網路慢）。已經拉下來的 layer 不會丟，`sudo systemctl start personaldocai-worker`
     再跑一次就會接著拉完。

- [ ] **確認跑的是「你剛才推上去的那一版」**（總覽 §10 追認項 e、design6 D16）：

```bash
sudo docker logs cloud-worker 2>&1 | head -n 5
```

  預期第一行：

```text
INFO:     cloud_worker 啟動 version=<7 碼 sha> region=ap-northeast-1 bucket=personaldocai-mailbox-xxxxxx
```

  `version=` 後面那一串必須等於你在 Mac 上跑 `git rev-parse --short HEAD` 的輸出。
  印出 `version=dev` ＝ Phase 91 §4.7 推上去的映像是「沒帶 `--build-arg GIT_SHA`」建的，
  回 Phase 90 §4.3 重建再重推。

- [ ] **離開機器**：在機器裡打 `exit`（回到 Mac 的 shell）。

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

- [ ] **第 3 步：上傳一張檔名明確非敏感的圖**：

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

  `/tmp/receipt-test.png` 是 Phase 86 §4.5 步驟 1 準備的那張（真收據照片或 Pillow 畫的都行）；
  `/tmp` 被清掉的話照那一段再產一次。

  預期：一段 JSON（恰三鍵 `job_id`／`filename`／`content_type`）＋下一行 `202`。
  **把那個 `job_id` 記下來**，下面幾步要用。

  📌 **檔名很重要**：隱私閘門的規則版**只看檔名**（總覽 §10 追認項 f）。
  `receipt-test.png` 命中 `NON_SENSITIVE_KEYWORDS` 的 `receipt` → 判 `NON_SENSITIVE`
  → 才有資格走雲端。取成 `IMG_1234.png` 會被判 `UNCERTAIN` ＝ 留本機，就驗不到這條路了。

- [ ] **第 4 步：送出當下，S3 應該看得到 input 與 context**（動作很快，要**馬上**看）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION" \
  --query 'Contents[].Key' --output text
```

  預期（處理中）：`documents/<job_id>/context.json  documents/<job_id>/input.png`；
  工人寫完之後會多一個 `documents/<job_id>/result.json`。
  **來不及看到是正常的**（雲端看圖約 2 秒，全程可能不到 10 秒就清乾淨了）——
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

  **不該**有 `fallback=` 那一行。⚠ 雲端路**不會**印本機路的「入庫完成」那一行（那是
  `_run_image_job` 才有的）——雲端路的完成訊號就是最後那行 **`雲端結果已入庫`**（Phase 79 的契約；
  PDF 的長相是 `雲端結果已入庫：N 頁中 M 頁成功（photo_ids=[…]）`）。沒有這一行＝結果沒落庫，
  先看有沒有 `fallback=`，再看 EC2 那邊（下面 ②）。

```bash
# ② EC2 上的工人：真的收到 job、真的用 Ollama Cloud 看了圖
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

  預期：看得到那個 `job_id`，以及
  `AI 開始 kind=vlm backend=cloud model=…` ／ `AI 結束 kind=vlm … ok=true`。

  📌 **`aws ssm send-command` ＝「從外面對機器下一句指令」**，不必開 session。
  `--document-name AWS-RunShellScript` 是 AWS 內建的「跑一段 shell」文件、
  `--parameters 'commands=["…"]'` 是要跑的指令；拿到 `CommandId` 之後用
  `get-command-invocation` 取輸出（**要等幾秒**，所以中間 `sleep 5`）。

```bash
# ③ 本機 worker：向量是**本機**算的（design6 D13）
docker compose logs --tail=200 worker | grep "kind=embed"
```

  預期：`AI 開始 kind=embed backend=local model=bge-m3`（`backend` 一定是 `local`）。

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
  ⚠️ 問問題會走本機 gemma4（路由 138 秒、回答 92 秒），要等。想快一點就先把頁首的
  「AI 模型」開關撥到雲端——那是**另一扇門**（design6 D6），跟 Privacy Gate 無關，
  撥它不影響本 Demo 的結論。

- [ ] **第 9 步：Demo 2 做完，先不要 Stop**——Demo 2b 的第一步就是 Stop，接著做。

### 4.8 Demo 2b —— 遠端關掉自動 fallback（總覽 §5.3 逐條）

> design6 §12 原文：**EC2 Stop 後上傳非敏感；不必改任何設定；
> 進度與入庫與增量五相同；S3 不出現新物件。**
>
> 📌 **這是本增量最重要的一個 Demo。** Demo 2 證明「開著能用」，
> Demo 2b 證明「**關著也能用**」——而機器 99% 的時間是關著的。

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
cp /tmp/receipt-test.png /tmp/menu-test.png   # 同一張圖、換個非敏感檔名（menu 在 NON_SENSITIVE_KEYWORDS 裡）
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@/tmp/menu-test.png" \
  https://127.0.0.1:8000/photos
```

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
cp /tmp/receipt-test.png /tmp/身分證.png                    # 同一張圖、換成敏感檔名（Phase 86 §4.6 同一招）
curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/身分證.png" \
  https://127.0.0.1:8000/photos                              # 預期：202
docker compose logs --tail=100 worker | grep "route=local verdict=SENSITIVE"
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
```

  預期：log 那一行看得到；S3 沒有 `Contents`。

### 4.9 Stop 守則（★ 每一次都要做）

- [ ] **收工：確認機器是 `stopped`**（Demo 2b 第 1 步已經 Stop 了，這裡再確認一次）：

```bash
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].{State:State.Name,Type:InstanceType,Arch:Architecture}' \
  --output json
```

  預期：`{"State": "stopped", "Type": "t4g.small", "Arch": "arm64"}`

**Stop 守則（這三段之後會原文寫進 `LAUNCH.md` 與 `CLAUDE.md`）：**

| 規則 | 說明 |
|---|---|
| **只用 `stop-instances`，永遠不用 `terminate-instances`** | Stop ＝ 關機：硬碟（EBS）留著，`worker.env` 與 Docker 映像都還在，開回來 systemd 會自己把工人拉起來。Terminate ＝ 銷毀：**整台連硬碟一起消失、不可逆**，要重跑 §4.3〜§4.5 全部 |
| **工人會優雅收尾** | `stop-instances` 會先讓機器正常關機 → systemd 跑 `ExecStop=/usr/bin/docker stop -t 120 cloud-worker`（Phase 91 的 unit；總覽 §10.2 追認項 O，另有 `TimeoutStopSec=150`）→ 容器收到 SIGTERM → 工人印一行 **「收到停止訊號」** 之後把手上那一則訊息做完才退出（Phase 88 做的）。**工人會做完手上那一則再退，最多等 120 秒**；極少見地超過才會被 SIGKILL，那時 jobs 訊息會在 VisibilityTimeout（900 秒）後回到佇列，下次 Start 由工人的冪等規則（Phase 87：result 已在→只補 Send；input 已被本機 fallback 清掉→只刪訊息）收拾——**不會留殘局、不會雙 INSERT** |
| **Stop 之後仍然在扣的東西** | 運算費（約 $0.022／小時）與公有 IPv4（$0.005／小時）**都停了**；**EBS 8 GB gp3 繼續**從點數扣，約 **$0.8／月**。這是「保留機器」的價格，很便宜但不是零 |
| **Stop 之後公有 IP 會被釋放** | 下次 Start 會拿到**一個新的**，而且 Stop 期間**不再計費**（公有 IPv4 的 $0.005／小時只在 running 時算）。這對本專案完全沒差——**沒有任何人會主動連進來**（inbound 是空的），我們也不必知道它的 IP |
| **每一次 Demo／除錯結束都要 Stop** | 忘了關一整天 ≈ $0.65；忘了一個月 ≈ $20。Free plan 的點數用完會**關帳**（資源直接消失，不是扣卡） |
| **怎麼快速檢查「我是不是忘了關」** | 下面這一行，養成收工前跑一次的習慣 |

```bash
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table
```

  預期（收工時）：空表格。有東西 ＝ 你忘了關，立刻 `stop-instances`。

### 4.10 三份文件

> 📌 **語言不要搞混：** `README.md` 與 `LAUNCH.md` 自 2026-08-27 起是**英文**；
> `CLAUDE.md` 與 `docs/` 是**繁體中文（台灣用語）**。
> ⛔ 三份都**只寫變數名，不寫值**——實例 id、bucket 名、帳號 id、API key 一個字都不准出現。

#### （1）`LAUNCH.md`：目錄加一列 ＋ 新章節 13 ＋ Appendix 架構圖

> ⚠️ **`## 12. Cloud worker on the Mac` 已經被 Phase 88 用掉了**（那一章講的是
> 「在這台 Mac 上用 `python -m app.workers.cloud_worker` 跑工人」）。
> 本 phase 的 EC2 章節是 **§13**，插在 §12 之後、Appendix 之前。
> **不要重編既有章節的編號或錨點**——那會讓所有既有的 `[section N](#n-…)` 連結全部失效。

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
the instance is actually `running`. Sensitive and uncertain photos never enter the S3 mailbox
and never reach the EC2 worker. (The header "AI model: local | cloud" switch is a *separate*
door: with it set to cloud, any photo's pixels are still sent to Ollama Cloud for inference,
exactly as before — the gate does not touch that switch.)

### Start it

```bash
set -a; . ./.env; set +a          # brings AWS_REGION and EC2_WORKER_INSTANCE_ID into the shell
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY   # .env holds the app's minimal key; the CLI must use the admin profile in ~/.aws
aws ec2 start-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

The worker service starts by itself (systemd `personaldocai-worker`, enabled at boot) and
pulls the `latest` image from ECR on every start, so a freshly deployed image is picked up
automatically. Give it about a minute, then upload a photo whose filename is clearly
non-sensitive (say `receipt-2026.png`): the local worker log should show, in this order,
`route=cloud verdict=NON_SENSITIVE`, then `kind=embed backend=local` (vectors are always computed
here), then `雲端結果已入庫：photo_id=…` — and **no** `fallback=` line.

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

**Stop, never terminate.** Stop keeps the disk, so `worker.env` and the pulled image survive
and the next Start needs no setup. Terminate destroys the instance **and its disk**, and it
cannot be undone — you would have to rebuild it from `deploy/ec2/user-data.sh` and re-enter
the secrets by hand.

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

The first log line tells you which build is running:
`cloud_worker 啟動 version=<git sha> region=… bucket=…`. That `version=` is the only reliable
way to confirm a deployment landed — do not trust the `latest` tag alone.
`aws ssm start-session` needs a plugin the CLI does not bundle:
`brew install --cask session-manager-plugin` (once per machine).

### Cost notes

| Item | Cost |
|---|---|
| `t4g.small` while **running** | about **$0.022 / hour** on-demand in Tokyo (check the pricing page for today's number). An hour of demoing is under 3 cents |
| public IPv4 while **running** | **$0.005 / hour** — every public IPv4 address is billed since 2024-02-01. Released on Stop, so nothing while stopped |
| 8 GB gp3 root volume while **stopped** | about **$0.8 / month** — the price of keeping the machine around |
| S3 mailbox | objects are deleted as soon as the result comes home; a lifecycle rule expires anything left under `documents/` after 2 days |
| SQS, ECR, IAM, security group, S3 gateway endpoint | free or negligible at this volume (ECR storage is a few cents a month for one image) |

The account runs on the AWS **Free plan**: nothing is charged to a card until you explicitly
upgrade to Paid — credits are consumed instead, and when they run out (or after six months)
the account is **closed** and its resources disappear. A budget alert exists for that reason
(`personaldocai-budget`, $5/month, mail at 80% of both actual and forecast).
**Do not press "upgrade to Paid".**

### Never do these

- **Never create a NAT Gateway.** ~$45/month in Tokyo; it would burn the credits in weeks.
  The instance sits in a public subnet with an auto-assigned public IP and gets out fine.
- **Never allocate an Elastic IP.** Since 2024-02-01 an Elastic IP is billed for every hour it
  exists, attached or not — on a machine that is stopped 99% of the time that is pure waste.
  The auto-assigned address costs nothing while stopped, and we do not need a fixed address.
- **Never open an inbound rule** (not even SSH on 22). Management is SSM only.
- **Never terminate** — see above.

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
PRIVACY_GATE_LOCAL_MODEL       # off | on
```

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
                          [EC2 t4g.small, arm64, AL2023]   <- normally STOPPED
                             systemd personaldocai-worker
                               docker run <ECR>/personaldocai-worker:latest
                             no inbound rules at all; egress TCP 443 only
                             managed via SSM Session Manager (no SSH, no key pair)
                               |  GetObject input + context
                               |  https://ollama.com  (vision only; no GPU on this box)
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

# ⛔ 關機（★ 每一次 demo／除錯結束都要做，忘了就在燒點數）
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
#             sudo journalctl -u personaldocai-worker -n 50 --no-pager
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
# ⚠ **機器關著不是壞掉**。CLOUD_ROUTE=ec2 時探測發現它不是 running，就直接走本機那條路，
#   log 寫 fallback=local reason=remote_unavailable；上傳仍然回 202、進度面板一模一樣。
# ⚠ **剛 Stop 完的 60 秒內**，探測可能還拿著「running」的快取，於是照片會被送出去、
#   然後等到逾時（CLOUD_RESULT_TIMEOUT_SECONDS=300）才 fallback。這是**預期行為**，
#   不是 bug。要立刻生效就 restart worker（快取在行程記憶體裡）。
#
# ⛔ 這些永遠不准做：
#   1. `aws ec2 terminate-instances`  ← 銷毀、不可逆（連硬碟一起沒）。收工一律 stop
#   2. 建 NAT Gateway                 ← 東京約 $45／月，兩週就把 Free plan 點數燒光
#   3. 配 Elastic IP                  ← 2024-02 起配了就每小時扣、不管機器有沒有在跑；自動配的 IP Stop 就免費
#   4. 開任何 inbound 規則（含 SSH 22）← design6 D11；管理只走 SSM
#   5. 在 AWS Console 按「升級成 Paid」 ← Free plan 不扣卡，升了就會扣
#
# 費用：t4g.small 開機約 $0.022／小時 ＋ 公有 IPv4 $0.005／小時（都只在 running 時算）；
#      8 GB gp3 關機也會扣，約 $0.8／月。
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
pytest -q                                   # 預期：662 passed ＋ 0 skipped
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q   # 預期：662 passed，逐字相同
ruff format --check app tests scripts && ruff check app tests scripts   # All checks passed!
```

- [ ] **★ 機密沒外洩**（commit 前必做）：

```bash
grep -nE "i-[0-9a-f]{8,}" README.md LAUNCH.md CLAUDE.md || echo "沒有實例 id，OK"
grep -nE "[0-9]{12}" README.md LAUNCH.md CLAUDE.md || echo "沒有 12 位帳號 id，OK"
grep -niE "ollama_api_key=.|aws_secret_access_key=." README.md LAUNCH.md CLAUDE.md \
  || echo "沒有金鑰值，OK"
git status --short | grep "\.env" || echo ".env 沒有被 git 追蹤，OK"
```

  預期：四行 `OK`。

- [ ] **機器是 stopped**（§4.9）：

```bash
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
```

  預期：`stopped`

- [ ] commit：

```bash
git add LAUNCH.md CLAUDE.md README.md
git status --short          # 確認 staged 的**只有這三個檔**（.env 不該出現）
git commit -m "docs: Phase 92 EC2 真機驗收（Demo 2／2b 通過、機器已 Stop）與三份文件——LAUNCH.md 新增 Cloud worker (EC2) 章節與架構圖雲端路、CLAUDE.md 指令區加 Start／Stop／SSM 看 log 與五條禁止、README.md 兩句 no cloud storage 改成誠實版本（662 tests 不變、端點仍 22）"
```

> ⚠️ commit 節奏由產品負責人決定（總覽 §7 鐵律 12）。**未指示前不要自己 commit**，
> 也不要把計畫檔搬進 `finish/`。`git add` 一定要明列檔案，不要 `git add -A`。

---
## 5. ASCII 圖：Demo 2 的完整時序（機器開著時，一張非敏感照片的一生）

```text
 你（Mac）           app 容器       worker 容器(Celery)    AWS（東京）        EC2 t4g.small(arm64)
    │                   │                  │                   │                     │
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
    │                   │                  │ Privacy Gate（本機、只看檔名）           │
    │                   │                  │   "receipt" 命中 → NON_SENSITIVE         │
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
    │                   │                  │                   │       Ollama Cloud 看圖
    │                   │                  │                   │       kind=vlm backend=cloud
    │                   │                  │                   │       （約 2 秒，最多 3 次）
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
 ⛔ 收工：aws ec2 stop-instances  → 之後的照片全部走本機（Demo 2b），使用者無感        │
```

---

## 6. 驗收清單

> 先載變數：`cd /Users/linjunting/personalDocAI && set -a; . ./.env; set +a; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; . /tmp/p91-vars.sh`
> （第 3 條要用 `$SG_ID`；`.env` 那把 key 一定要 unset，否則除了 `describe-instances` 以外每一條都 `AccessDenied`）

| # | 要驗的事 | 指令 | 預期 |
|---|---|---|---|
| 1 | 機器建對了（機型／架構） | `aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].{T:InstanceType,A:Architecture}' --output json` | `{"T":"t4g.small","A":"arm64"}` |
| 1b | IMDSv2 強制、hop limit 2（容器裡拿得到憑證） | `aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].MetadataOptions.{T:HttpTokens,H:HttpPutResponseHopLimit}' --output json` | `{"T":"required","H":2}` |
| 2 | **收工時是 stopped** | 同上但 `--query '…State.Name' --output text` | `stopped` |
| 3 | **SG inbound 仍是空的** | `aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$SG_ID" --query 'SecurityGroups[0].IpPermissions' --output json` | `[]` |
| 4 | 沒有 NAT Gateway | ``aws ec2 describe-nat-gateways --region "$AWS_REGION" --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text`` | 空 |
| 5 | 沒有 Elastic IP | `aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text` | 空 |
| 6 | **只有一台**機器（沒開重複） | `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=tag:Name,Values=personaldocai-worker Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId' --output text` | 恰一個 id |
| 7 | Budget 還在 | `aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)" --query 'Budgets[].BudgetName' --output text` | `personaldocai-budget` |
| 8 | S3 已清乾淨 | `aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"` | 沒有 `Contents` |
| 9 | 兩條佇列都空 | `aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION" --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json`（results 同理） | 兩條都 `"0"` |
| 10 | 本機切到 `ec2` 模式 | `docker compose exec worker python -c "from app.core import config; print(config.CLOUD_ROUTE, bool(config.EC2_WORKER_INSTANCE_ID))"` | `ec2 True` |
| 11 | 文件三份都改了、而且沒改到別的 | `git diff --stat README.md LAUNCH.md CLAUDE.md` | 三個檔各只有預期的那幾段 |
| 12 | 文件沒有洩漏機密 | `grep -nE -e "i-[0-9a-f]{8,}" -e "[0-9]{12}" README.md LAUNCH.md CLAUDE.md` | 沒有輸出 |

再加下面這幾條（要看輸出，單獨列）：

- [ ] **Demo 2 全過**（§4.7 九步全部打勾）：本機 log 依序 `route=cloud verdict=NON_SENSITIVE` →
      `kind=embed backend=local` → `雲端結果已入庫：photo_id=…`、EC2 log 有 `kind=vlm backend=cloud`、
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

  預期：第一段印 `cloud_worker 啟動 version=<sha> …`，`<sha>` 等於下一行的輸出。
  ⚠️ 這一條要在機器 **running** 時做；驗完記得 Stop。

- [ ] **顆數／端點／零依賴／沒弄髒／只動該動的檔**（五條一起跑）

```bash
pytest -q                                    # 預期：662 passed ＋ 0 skipped（開工基線 662 ＋ 0）
pytest -q -k "端點"                          # 預期：三顆清點測試全綠（端點仍 22、openapi 零 DELETE）
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q # 預期：662 passed，與第一條逐字相同
ls data/staging/                             # 預期：空的
git status --short docs/spec/                # 預期：零輸出（規格區全程唯讀）
diff /tmp/p92-before.txt <(git status --short)
#   預期：只多出 README.md／LAUNCH.md／CLAUDE.md 三個 " M"；
#         app/、tests/、deploy/、Dockerfile、compose.yaml 一個都不該出現
ruff format --check app tests scripts && ruff check app tests scripts   # All checks passed!
```

- [ ] **★G3 的證據表已填好交出，並且產品負責人已明示通過**（文末那張表）

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
   **原因：** 映像的架構跟機器對不上——多半是 §4.2 的 AMI 參數寫成 `x86_64`（開出 Intel 機器），
   或 Phase 90 建映像時建成了 `amd64`。
   **正解：** `describe-instances` 的 `Architecture` 要是 `arm64`；
   本機 `docker image inspect "$ECR_URI:latest" --format '{{.Architecture}}'` 也要是 `arm64`。
   兩邊對不上就回 Phase 90 §4.3 重建、Phase 91 §4.7 重推。

5. **Demo 2b 拿到的是 `reason=result_timeout` 而不是 `remote_unavailable`。**
   **症狀：** Stop 完馬上傳，log 寫的是逾時；而且 S3 **真的出現過**新物件。
   **原因：** `Ec2Probe` 的答案**快取 60 秒**（`EC2_PROBE_TTL_SECONDS=60`）。剛 Stop 完的
   那 60 秒內本機還拿著「running」的舊答案，照樣送出，然後等到 300 秒逾時才 fallback。
   **正解：** 這**不是 bug**（照片最後還是入庫了），只是驗到另一條路。等滿 60 秒再傳，
   或 `restart worker` 把快取清掉（它在行程記憶體裡）。
   ⚠️ **不要為了方便就去改那個 60**——它是總覽 §2.4.2 的契約值。

6. **忘記 Stop。**
   **症狀：** 隔天發現點數少了、Budget 寄信來。
   **原因：** Demo 做完就去做別的事了。`t4g.small` ＋ 公有 IPv4 一整天約 $0.65，一個月不關約 $20
   ——Free plan 的 $100 點數五個月就沒了，然後**關帳**（資源直接消失，不是扣卡）。
   **正解：** 養成收工前跑這一行的習慣（§4.9）：
   `aws ec2 describe-instances --region "$AWS_REGION" --filters Name=instance-state-name,Values=running --query 'Reservations[].Instances[].InstanceId' --output text`
   ——預期是**空的**。這一行也已經寫進 `LAUNCH.md` §13 與 `CLAUDE.md` 指令區。

7. **在 AWS Console 看到「升級成 Paid」的提示就按下去。**
   **症狀：** 從此開始扣信用卡。
   **原因：** Free plan 的橫幅寫得很像「你需要升級才能繼續」，其實不必——
   我們用的 EC2／S3／SQS／ECR／IAM／SSM 全部在 Free plan 的可選服務清單裡。
   **正解：** **不要按。** design6 D15／§7 明文：目標是卡片 **$0**。
   點數用完就讓它關帳（資料留 90 天），要救再說。
   同理**不要**開 Organizations／Control Tower（會自動升 Paid 且點數作廢）。

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

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 東西 |
|---|---|
| AWS（東京） | 一台 `t4g.small`（AL2023 arm64、Name tag `personaldocai-worker`、8 GB gp3、IMDSv2 且 hop limit 2），上面裝好 Docker ＋ systemd 服務 `personaldocai-worker`，**現在是 stopped** |
| 那台機器上（不進版控） | `/opt/personaldocai/worker.env`（`chmod 600`，人手動放的八個值） |
| 本機（不進版控） | `.env` 的 `EC2_WORKER_INSTANCE_ID`（填了真 id）、`CLOUD_ROUTE=ec2`、`CLOUD_RESULT_TIMEOUT_SECONDS=300` |
| 本機（進 git） | `LAUNCH.md` 新章節 **13**「Cloud worker (EC2)」（§12 是 Phase 88 的「on the Mac」）＋目錄一列＋Appendix 架構圖的雲端路；`CLAUDE.md` 指令區新增「雲端工人（EC2）」一段；`README.md` 兩句改成誠實版本 |

**對外行為變了沒：**

**使用者看得到的部分完全沒有。** 端點仍 **22** 支、`openapi.json` 零 DELETE、
`POST /photos` 仍回 202 且 body 恰三鍵、`GET /ingest-jobs` 回應形狀不變
（使用者看不到 `route`／`privacy`）、前端一行沒改、資料庫零改動。

**唯一真正改變的是「非敏感照片在 EC2 開著時由誰看圖」**——而那件事在 log 之外
完全不可見，Demo 2b 已經親手證明過：機器關掉、什麼都不改，照片照樣進得來。

**本 phase 零 Python 變更、零測試變更。**
**顆數：662 passed ＋ 0 skipped**（開工基線 662 ＋ **0**）。
與總覽 §2.7／§9 定案的「Phase 92 ＋0 顆、累計 662」一致，**零偏離**。

**下一步：** 先過 **★ 閘門 G3**（下面那張表）。
過了之後是 **Phase 93（`phase-93-GitHub_OIDC與部署角色.md`）**：
建 IAM OIDC provider ＋ 部署用的 role（trust 的 `sub` **精確鎖 `main` 分支、不准萬用字元**）、
把 role ARN 放進 GitHub repo secret `AWS_DEPLOY_ROLE_ARN`，
並在 `tests/integration/test_design6_error_paths.py` 追加 **4 顆**掃碼測試（662 → 666）。

---

## ★ 閘門 G3：交給產品負責人（本 phase 之後、Phase 93 之前）

> 🚦 **G3 是「人」的動作，實作者不可以自己勾掉。**
> 下面每一條都只是**證據**；「看過證據、同意往下走」的那個動作必須由**產品負責人**做出來
> ——一句明確的話（口頭、對話、或 dev-prompt 檔案），而且他**必須親眼看過 Demo 2 與 Demo 2b**。

| 項目 | 內容 |
|---|---|
| **是什麼** | 「真機已經處理過一筆、Stop 之後也自動 fallback 了，可以做自動部署了」的一句話 |
| **誰確認** | **產品負責人（人）**，而且必須**親眼看過 Demo 2 與 Demo 2b** |
| **憑什麼確認** | design6 §0 戊那列：真機 Start → 處理一筆 → Stop；Stop 後下一筆自動本機。逐條指令見總覽 **§5.2**（Demo 2）與 **§5.3**（Demo 2b），本檔 §4.7／§4.8 是同一份的展開版 |
| **沒過會怎樣** | **Phase 93〜94 停擺。** 理由：CD 的失敗與工人的失敗**長得一模一樣**（都是「EC2 上沒反應」）。手動部署還沒跑通就加自動部署，除錯時分不清是「新映像沒推上去」還是「工人本來就壞」 |
| **卡住時怎麼辦** | ① 真機起不來 → 看 `deploy/ec2/user-data.sh`（回 **Phase 91**）；② 工人起得來但拿不到訊息 → IAM instance role 的 policy（回 **Phase 91 §4.4**）；③ 拿得到訊息但看圖失敗 → `worker.env` 的 `OLLAMA_API_KEY`（回本檔 §4.5）；④ 一切正常但本機沒收到 → 本機 `.env` 的 `CLOUD_ROUTE=ec2` 與 `EC2_WORKER_INSTANCE_ID`（回本檔 §4.6）。⚠️ **每一輪除錯完都要記得 Stop** |

**要交給產品負責人的十條證據**（每一條貼上你實際跑出來的輸出）：

| # | 要看的事 | 憑據 |
|---|---|---|
| 1 | 機器建對了 | `describe-instances` → `t4g.small` / `arm64` |
| 2 | **inbound 是空的**（沒有 SSH） | `describe-security-groups … IpPermissions` → `[]` |
| 3 | 只走 SSM 就管得動 | `aws ssm start-session` 真的進得去；`systemctl status` ＝ `active (running)` |
| 4 | **跑的是我們推的那一版** | `docker logs cloud-worker \| head -1` 的 `version=<sha>` ＝ `git rev-parse --short HEAD` |
| 5 | **Demo 2 成功**（雲端路走通） | 本機依序 `route=cloud verdict=NON_SENSITIVE` → `kind=embed backend=local` → `雲端結果已入庫：photo_id=…`、EC2 `kind=vlm backend=cloud`、照片入待決定、問問題問得到 |
| 6 | **Demo 2 收尾乾淨** | S3 `documents/` 無 `Contents`、兩條佇列 `ApproximateNumberOfMessages` 都是 `0`、`data/staging/` 空、job 已消失 |
| 7 | **Demo 2b 成功**（關掉也能用） | Stop 之後**零設定變更**、上傳仍 **202**、log `fallback=local reason=remote_unavailable`、S3 **零新物件**、照片照樣入庫 |
| 8 | **Demo 1 仍然成立** | 敏感檔 `route=local verdict=SENSITIVE`、S3 無該 job 的物件 |
| 9 | **機器已經 Stop、沒有 NAT／EIP、Budget 還在** | §6 表格第 2、4、5、7 條 |
| 10 | **測試與端點沒動** | `pytest -q` ＝ 662 passed ＋ 0 skipped；三死埠顆數相同；`pytest -q -k 端點` 全綠 |

- [ ] **等產品負責人明說**（原話例：「真機兩個 demo 我都看過了，可以做 CD 了」）。

  ❌ 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正兩個 demo 都跑過了」、
  「先做 93，之後再回來補確認」。

---

## 附：本文件引用的官方文件

- [用 SSM 公開參數取最新 AL2023 AMI](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-public-parameters-ami.html)
- [AL2023 核心版本（`kernel-default` 指向哪一版）](https://docs.aws.amazon.com/linux/al2023/ug/kernel-update.html)
- [`aws ec2 run-instances`（每一個旗標）](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html)
- [EC2 T4g（Graviton／arm64）機型](https://aws.amazon.com/ec2/instance-types/t4/)
- [EC2 執行個體生命週期（Stop 與 Terminate 的差別）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [`aws ec2 wait instance-running` / `instance-stopped`](https://docs.aws.amazon.com/cli/latest/reference/ec2/wait/instance-running.html)
- [EC2 instance metadata service v2（`HttpTokens=required`）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html)
- [EC2 instance metadata 存取注意事項（容器環境請把 hop limit 提高到 2）](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html#imds-considerations)
- [`aws ec2 modify-instance-metadata-options`（事後補 hop limit）](https://docs.aws.amazon.com/cli/latest/reference/ec2/modify-instance-metadata-options.html)
- [Session Manager plugin：macOS 安裝方式（官方只提供 .pkg 與 .zip；Homebrew cask 是社群維護）](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html)
- [AL2023 用 SSM 參數啟動（含 2026-08-17 default 核心 6.1→6.18 的公告）](https://docs.aws.amazon.com/linux/al2023/ug/ec2.html#launch-via-aws-cli)
- [EC2 On-Demand 定價（t4g.small 東京單價以此頁當天數字為準）](https://aws.amazon.com/ec2/pricing/on-demand/)
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
