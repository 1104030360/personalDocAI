#!/bin/bash
# PersonalDocAI 雲端工人的 EC2 開機腳本（增量六 Phase 91）。
#
# ★ user-data 的三個事實（AWS 官方行為，記住可以少走很多冤枉路）：
#   ① 它**以 root 執行**——所以裡面**不要**寫 sudo（寫了也能跑，但沒必要）。
#   ② 它**只在「第一次開機」跑一次**。之後 Stop→Start 都不會再跑。
#      要改機器上的東西，是用 SSM Session Manager 進去改，不是改這個檔再重開機。
#   ③ 它的輸出在機器裡的 /var/log/cloud-init-output.log。
#      機器起來卻沒反應時，第一個要看的就是那個檔。
#
# ⛔ **這個檔會原封不動留在機器的 /var/lib/cloud/instances/<id>/ 底下。**
#    所以裡面**一個機密都不准寫**——AWS 金鑰、OLLAMA_API_KEY、bucket 名一律不寫。
#    機密走 /opt/personaldocai/worker.env（人用 Session Manager 手動放，chmod 600）。
#
# set 的四個旗標：
#   -e 任何一行失敗就整個停下（不要帶著半套狀態繼續）
#   -u 用到沒設定的變數就報錯（打錯變數名時馬上發現）
#   -x 把每一行執行前先印出來（log 才看得懂做到哪裡）
#   -o pipefail 管線裡任何一段失敗都算失敗（預設只看最後一段）
set -euxo pipefail

# ---- 0. 這個腳本自己的變數（都不是機密，所以可以寫在這裡）----
# 開機時要先把模型抓下來的那一顆。只在 worker.env 填 WORKER_VLM_BACKEND=local 時
# 才真的會被用到（Phase 92-B 的 GPU 機）——那時**要跟 /opt/personaldocai/worker.env 裡的
# VLM_MODEL 一模一樣**：兩邊不一致的話，工人會去要一顆這台機器上沒有的模型，
# 每張圖 404、看三次、標成「看不懂」（而且不會有任何一行看起來像錯誤）。
# 92-A 的 CPU 機填 cloud，worker.env 的 VLM_MODEL 留空，這顆模型只是先抓好放著。
# ⚠ Linux 上**沒有** Mac 那個 `-mlx` 標籤（那是 Apple Silicon 專用的建置）。
VLM_MODEL=gemma4:e2b

# ---- 1. 裝 Docker ----
# AL2023 的預設套件庫裡就有 docker（不像 AL2 要先開 amazon-linux-extras）。
# ★ 這一份 user-data 兩種機器共用，AMI 依 phase-92 的段落選：
#   92-A（CPU 機 t3.xlarge、WORKER_VLM_BACKEND=cloud）→ **一般 AL2023 x86_64**。
#     沒有 GPU 驅動沒關係：工人打 ollama.com，這台的 Ollama 只是閒著應門讓 unit 的等待過。
#     ⚠ 不要拿 GPU AMI 開 CPU 機——它的根碟快照 75 GB，白付。
#   92-B（GPU 機 g4dn.xlarge、WORKER_VLM_BACKEND=local）→ **Deep Learning Base OSS NVIDIA
#     Driver GPU AMI (Amazon Linux 2023)**：NVIDIA 驅動與 Docker 都已內建，這一行在那顆 AMI 上
#     其實是 no-op（安全、不會壞）。用一般 AL2023 開 GPU 機的話**沒有驅動**——Ollama 會安靜地
#     退回 CPU，看一張圖從幾秒變成好幾分鐘，而且沒有任何錯誤訊息，只有「怎麼這麼慢」。
dnf install -y docker

# --now ＝ enable（開機自動啟動）＋ start（現在就啟動）兩件事一起做
systemctl enable --now docker

# 讓預設的 ec2-user 不必 sudo 也能用 docker（下次登入才生效；本腳本是 root，不受影響）
usermod -aG docker ec2-user

# ---- 2. 建放機密的目錄 ----
# worker.env 還不存在——它由人用 Session Manager 進來手動建（Phase 92 §4.5）。
# 目錄權限收到 700：只有 root 進得去。
mkdir -p /opt/personaldocai
chmod 700 /opt/personaldocai

# ---- 3. 裝 systemd 服務 ----
# ★ 下面這一段與 deploy/ec2/personaldocai-worker.service **必須逐字相同**。
#   Phase 91 §6 的驗收有一條專門在 diff 這兩份（用下面這兩行標記抓範圍）。
cat > /etc/systemd/system/personaldocai-worker.service <<'UNIT'
[Unit]
Description=PersonalDocAI cloud worker (Docker, pulls latest from ECR)
After=docker.service
Requires=docker.service
# 「docker 起來了」不等於「網路通了」：開機時 ExecStartPre 第一行就要打去 ECR 換臨時
# 密碼，網路還沒拿到 IP 的話它會失敗，然後 Restart=always 每 10 秒重試一次、把 journal
# 塞滿沒有意義的錯誤（而且 docker pull 的錯誤訊息看起來像「ECR 權限不足」，很難聯想）。
# network-online.target ＝「網路真的通了」那一刻；Wants 是「請幫我把它拉起來」，
# After 是「等它到了我再開始」——**兩行都要**，只寫 After 的話那個 target 可能根本不會被啟動。
After=network-online.target
Wants=network-online.target
# 看圖的模型跑在**這台機器自己**的 Ollama 上（WORKER_VLM_BACKEND=local，2026-09-03 改判）。
# ollama.service 是 Ollama 官方安裝腳本（curl -fsSL https://ollama.com/install.sh | sh）
# 裝好的那個服務名，預設只聽 127.0.0.1:11434。同樣是 After ＋ Wants 兩行都要。
# ⚠ 但「服務啟動了」不等於「模型載得動」，所以下面還有一條 ExecStartPre 真的去問它一聲。
After=ollama.service
Wants=ollama.service

[Service]
Type=simple
EnvironmentFile=/opt/personaldocai/worker.env
# /usr/bin/aws 是 AL2023 **內建**的 AWS CLI v2，user-data 不另外裝（也不要用 pip 裝 v1）。
# 寫絕對路徑是因為 systemd 的 PATH 很窄，跟你登入時的 shell 不一樣。
ExecStartPre=/bin/bash -c '/usr/bin/aws ecr get-login-password --region ${AWS_REGION} | /usr/bin/docker login --username AWS --password-stdin ${ECR_REGISTRY}'
# 等 Ollama 真的活著（最多 120 秒）。開機時 systemd 只保證「服務被啟動了」，
# 但它要載入模型、抓 GPU，慢個十幾秒很正常；沒等就開工的話，第一批照片會全部
# 連線被拒→看三次→標成「看不懂」，而且是一種完全不會報錯的壞法。
# 失敗就讓下面的 Restart=always 十秒後再試一次（比在這裡硬等更誠實）。
ExecStartPre=/bin/bash -c 'for i in {1..60}; do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && exit 0; sleep 2; done; echo "ollama 120 秒內沒起來" >&2; exit 1'
ExecStartPre=/usr/bin/docker pull ${ECR_IMAGE}:latest
ExecStartPre=-/usr/bin/docker rm -f cloud-worker
# --network host ＝容器直接用 host 的網路命名空間，這樣才打得到只聽 127.0.0.1 的 ollama.service。
# ⚠ 不用 host.docker.internal：那在 Linux 上要 Ollama 改聽 0.0.0.0（OLLAMA_HOST），
#   等於把模型服務對整個子網路打開，反而擴大暴露面。
# 工人不聽任何連接埠、SG 的 inbound 是空的，所以共用網路命名空間不會多開任何一扇門。
ExecStart=/usr/bin/docker run --rm --network host --name cloud-worker --env-file /opt/personaldocai/worker.env ${ECR_IMAGE}:latest
# 停止：工人收到 SIGTERM 會把手上那一則訊息做完才退（Phase 88）；多頁 PDF 可能超過 docker 預設的 10 秒寬限，
# 所以給 120 秒。超時＝SIGKILL：資料不會壞（D17 冪等＋jobs 佇列 900 秒後重投），只是多跑一次雲端看圖。
ExecStop=/usr/bin/docker stop -t 120 cloud-worker
# 要比上面的 120 秒長，否則 systemd 會先一步把 docker stop 本身殺掉（總覽 §10.2 裁決 O）
TimeoutStopSec=150
# 上面三條 ExecStartPre（ECR 登入、等 Ollama 最多 120 秒、docker pull）是**串起來算同一個**啟動逾時，
# 而 systemd 預設只給 90 秒——不加這行，「等 120 秒」永遠等不滿就被 systemd 殺掉（journal 會寫
# start operation timed out），第一次冷拉映像也可能逼近 90 秒。600 秒＝三條加起來最壞情況也夠。
TimeoutStartSec=600
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# 讓 systemd 重新讀一次 /etc/systemd/system/ 底下的檔
systemctl daemon-reload

# enable ＝「開機時自動啟動」。
# ⛔ **刻意不 start**：/opt/personaldocai/worker.env 還不存在，
#    現在 start 一定會因為 EnvironmentFile 找不到而失敗，然後 Restart=always
#    會讓它每 10 秒重試一次、把 journal 塞滿沒有意義的錯誤。
#    人用 Session Manager 放好 env 檔之後，再手動 systemctl start（Phase 92 §4.5）。
systemctl enable personaldocai-worker

# ---- 4. 裝 Ollama（2026-09-03 改判：92-B 的 GPU 機在這台自己看圖，design6 D12 作廢；
#         92-A 的 CPU 機也裝，但只是閒著應門——unit 的 ExecStartPre 會等 11434）----
# ★ 這一段**刻意排在最後**：它是整個腳本裡最慢、最容易失敗的一段（要抓 7 GB）。
#   排在寫 unit 之前的話，一次暫時性的網路失誤就會讓 set -e 中止腳本，
#   機器上**連 personaldocai-worker.service 都不存在**——而 user-data 只在第一次開機
#   跑一次，Stop→Start 不會重來，只能整台重開或人進去手動補。
# 官方安裝腳本：偵測到 NVIDIA 驅動就自動用 GPU，並且把服務裝成 ollama.service
# （預設只聽 127.0.0.1:11434 ——**不要**改成 0.0.0.0，那等於把模型服務對整個子網路打開；
#  工人容器是用 --network host 打進來的，見 unit 檔）。
curl -fsSL https://ollama.com/install.sh | sh

systemctl enable --now ollama

# 等它真的回應再往下走（最多 120 秒）。剛裝好的服務要幾秒才聽得到埠，
# 沒等就 ollama pull 會直接失敗。與 unit 檔那條 ExecStartPre 是同一個迴圈。
ollama_ready=""
for i in {1..60}; do
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null && { ollama_ready=1; break; }
  sleep 2
done
if [ -z "$ollama_ready" ]; then
  echo "ollama 120 秒內沒起來" >&2
  exit 1
fi

# 把模型抓下來（約 7 GB，第一次開機要等幾分鐘；進度會進 cloud-init-output.log）。
# 沒有先抓的話，第一批照片會在「工人第一次看圖」時觸發下載，看起來像整台機器卡死。
# ⚠ 失敗**不中止腳本**：模型沒抓到只是「第一張照片會很慢」，而中止腳本會讓上面
#   那些真正要緊的東西（unit 檔、enable）在某些排列下留下半套狀態。
# 根碟太小就不要拉：一般 AL2023 AMI 預設只有 8 GiB，7.2 GB 的模型拉到一半塞滿磁碟，
# 之後 unit 的 docker pull 會用看不懂的方式失敗。phase-92 的 run-instances 開的是 30 GB；
# 忘了帶 --block-device-mappings 就會落到這裡——大聲留一行，然後跳過（不中止腳本）。
avail_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${avail_gb:-0}" -lt 12 ]; then
  echo "根碟只剩 ${avail_gb:-0} GB，放不下 ${VLM_MODEL}（7.2 GB）——跳過 ollama pull；請用 30 GB 根碟重開這台" >&2
else
  ollama pull "$VLM_MODEL" || echo "模型沒抓到（$VLM_MODEL），工人第一次看圖時 Ollama 會現抓；看 journalctl -u ollama" >&2
fi

# 純記錄：這台機器到底有沒有 GPU。沒有的話 Ollama 會安靜地用 CPU 跑，
# 而唯一的症狀是「慢十倍」——把答案留在 log 裡，之後查起來省事。
nvidia-smi -L || echo "沒有 GPU（Ollama 會退回 CPU，看圖會慢很多）"

echo "user-data 完成：personaldocai-worker 已 enable（尚未 start，等 worker.env）；docker 與 ollama 已裝，模型抓沒抓成看上面那一行"
