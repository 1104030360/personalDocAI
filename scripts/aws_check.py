"""對真 AWS 做一次最小的來回，確認「這台 Mac 的憑證與權限真的能用」。

用法（在專案根目錄執行；⚠ 它會真的打 AWS，不要在 pytest 裡呼叫它）：

    python scripts/aws_check.py s3
    python scripts/aws_check.py sqs
    python scripts/aws_check.py s3 sqs     # 兩個都跑

★ 它刻意用**產品自己的** app/services/aws_mailbox.AwsMailbox，而不是自己寫一段 boto3。
  這樣驗到的就是正式路徑真的會走的那些呼叫（鍵名、參數、憑證來源全部一樣）：
  這支跑得過 ＝ worker 容器裡的程式也跑得過。

★ 它用哪一把 key？資源名稱與憑證都從 .env 讀——app/core/config.py 一被 import 就會
  load_dotenv()，而 load_dotenv() **只補上不存在的環境變數、不覆蓋已存在的**。所以有三種情況：
    ・shell 裡沒有 AWS_ACCESS_KEY_ID（你先 unset 過）→ 用 .env 那把
      （IAM user personaldocai-mac，最小權限）→ 這是預設，也是 s3 子命令要驗的那一把
    ・shell 裡已經有一把（例如你自己 export 過別的 key）→ 用那一把，.env 那把被略過
    ・shell 裡沒有、.env 也沒填 → boto3 會**安靜地**退到 ~/.aws 的 default profile（admin）
      ——你以為在驗最小權限，其實在用管理員
  所以第一行一律印出「金鑰來源」，讓你確認驗到的是哪一把。
  ⚠ 注意：unset **不會**讓這支腳本改用 admin——unset 只影響 aws CLI；
    Python 這邊 load_dotenv() 會馬上把 .env 的 mac key 補回來。

★ sqs 子命令用 .env 那把 mac key 跑就可以（總覽 §10.2 N：personaldocai-mac 的 policy
  兩條佇列的「送／收／刪」都有，因為 Phase 88／90 在 Mac 上跑工人用的就是這把 key）。
  它仍然**沒有** PurgeQueue——清佇列是人做的事，用 aws CLI 以 admin 身分做（Phase 85 §4.8）。

分層：本檔不寫 SQL、不碰資料庫、不碰 HTTP。它只是把 AwsMailbox 的方法照順序呼叫一次。
"""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 用 `python scripts/aws_check.py` 執行時，Python 只會在 scripts/ 資料夾裡找模組，
# 會找不到 app 套件——把專案根目錄加進搜尋路徑就解決了（與 check_embedding_dim.py 同一招）。
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import config  # noqa: E402  （必須在改完搜尋路徑之後 import）
from app.services.aws_mailbox import AwsMailbox  # noqa: E402
from app.services.cloud_ingest import MailboxMessage  # noqa: E402

# 檢查用的假 job_id。用固定值（不是隨機）有兩個好處：
#   ・出事時你知道要去 bucket 的哪個位置找殘骸（documents/aws-check/）
#   ・它一樣落在 documents/ 前綴底下，所以萬一沒刪掉，Lifecycle 兩天後會清掉
CHECK_JOB_ID = "aws-check"

# 收訊息時最多重試幾次（每次長輪詢 20 秒）。
# 為什麼需要重試：SQS Standard 是分散式的，剛送出的訊息偶爾要多問一次才拿得到。
# 長輪詢本身已經會問過所有伺服器，所以三次幾乎一定夠。
RECEIVE_RETRIES = 3


def credential_source() -> str:
    """回報 boto3 這次會用哪一把 key。只比對「是不是 .env 那把」，**不印任何值**。

    一定要在 config 被 import（＝ load_dotenv() 已經跑完）之後呼叫：那時 os.environ 裡的
    AWS_ACCESS_KEY_ID 要嘛是 shell 帶進來的、要嘛是 .env 補上的、要嘛兩邊都沒有。
    """
    env_path = PROJECT_ROOT / ".env"
    env_values = dotenv_values(env_path) if env_path.is_file() else {}
    env_key = env_values.get("AWS_ACCESS_KEY_ID") or ""
    current_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    if not current_key:
        return "沒有任何 key（boto3 會退到 ~/.aws 的 default profile ＝ admin）⚠ 這不是最小權限"
    if current_key == env_key:
        return ".env 那把（personaldocai-mac，最小權限）"
    return "不是 .env 那把（多半是你帶進來的 admin key）"


def build_mailbox() -> AwsMailbox:
    """照 .env 的設定建一個真的信箱。region 一律明傳，不靠環境變數猜。"""
    if not config.S3_BUCKET:
        raise SystemExit("⛔ .env 的 S3_BUCKET 是空的——先做完 Phase 84 §4.7")
    return AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )


def check_s3() -> None:
    """put → get → 比對內容 → delete → 再 get 確認真的不在了。

    最後那個「再 get 一次」不是多餘的：只做 delete 不檢查的話，
    一個「delete 其實被 AccessDenied 但被 delete_objects 的 warning 吞掉」的權限問題
    會完全看不出來（那正是 delete_objects 刻意不往外丟例外的代價）。

    ④ 靠的是「GetObject 缺 key 回 404（NoSuchKey）→ get_object 翻譯成 None」。
    S3 只在呼叫者有 bucket 層級的 s3:ListBucket 時才回 404；沒有的話一律回 403 AccessDenied
    （S3 刻意不讓沒有 list 權限的人分辨「不存在」與「沒權限」）。
    所以 personaldocai-mac-policy 一定要含 s3:ListBucket（總覽 §10.2 P）；
    ④ 炸 AccessDenied ＝ policy 還是舊版。
    """
    mailbox = build_mailbox()
    key = mailbox.input_key(CHECK_JOB_ID, "image/png")
    body = b"personaldocai aws-check"

    print(f"bucket = {config.S3_BUCKET}   region = {config.AWS_REGION}")

    print(f"① PutObject      {key}")
    mailbox.put_object(key, body, "image/png")

    print(f"② GetObject      {key}")
    fetched = mailbox.get_object(key)
    if fetched != body:
        raise SystemExit(f"⛔ 拿回來的位元組跟放進去的不一樣：{fetched!r}")

    print(f"③ DeleteObjects  {key}")
    mailbox.delete_objects([key])

    print("④ 再 GetObject 一次，確認真的不在了")
    if mailbox.get_object(key) is not None:
        raise SystemExit("⛔ 刪掉之後還拿得回東西——delete 沒有真的生效（多半是權限）")

    print("✅ S3 OK：put → get → 內容一致 → delete → 確認不在了")


def receive_own_message(receive, queue_name: str) -> MailboxMessage:
    """長輪詢最多幾次，直到收到 job_id 等於 CHECK_JOB_ID 的那一則。

    receive ＝ 信箱的收信方法（mailbox.receive_job 或 mailbox.receive_result），
    它吃「最多等幾秒」、回一則 MailboxMessage 或 None。

    收到**別人**的訊息時直接停手並提示：那代表佇列裡有殘留（多半是上一次煙霧沒清乾淨），
    先清乾淨再測，不然這支腳本會把別人的訊息刪掉。
    ⚠ 被我們拿過一次的那則會隱形一段時間（jobs 900 秒、results 30 秒）才重新出現；
      purge-queue 會連隱形中的一起清掉，所以「先 purge 再測」永遠是安全的修法。
    """
    for _ in range(RECEIVE_RETRIES):
        message = receive(20)
        if message is None:
            continue
        if message.job_id != CHECK_JOB_ID:
            raise SystemExit(
                f"⛔ {queue_name} 佇列裡有別人的訊息（job_id={message.job_id}）。"
                " 先用 aws sqs purge-queue 清乾淨再測。"
            )
        return message
    raise SystemExit(f"⛔ {queue_name} 佇列送出去之後收不回來（等了 {RECEIVE_RETRIES * 20} 秒）")


def check_sqs() -> None:
    """兩條佇列各做一次來回：send → receive（確認是自己那則）→ delete。

    ⚠ 它會**真的**在佇列裡放訊息。做完之後兩條佇列都必須回到 0 則
    （§4.8 的驗收就是在確認這件事）——殘留的訊息會在 Phase 86 的煙霧裡變成雜訊。
    ⚠ 用 .env 的 mac key 跑就可以（見檔頭）。① 的 ReceiveMessage 回 AccessDenied ＝
      掛在 personaldocai-mac 上的 policy 還是舊版（沒有工人端動作），見 Phase 85 §4.7 的框。
    """
    if not config.SQS_JOBS_QUEUE_URL or not config.SQS_RESULTS_QUEUE_URL:
        raise SystemExit("⛔ .env 的兩個 SQS_*_QUEUE_URL 是空的——先做完 Phase 85 §4.5")
    mailbox = build_mailbox()

    print("① jobs 佇列：SendMessage（本機 → 工人的那條）")
    mailbox.send_job(CHECK_JOB_ID, mailbox.input_key(CHECK_JOB_ID, "image/png"))
    message = receive_own_message(mailbox.receive_job, "jobs")
    print(f"   ReceiveMessage 收到：job_id={message.job_id} s3_key={message.s3_key}")
    mailbox.delete_job_message(message.receipt_handle)
    print("   DeleteMessage 完成")

    print("② results 佇列：SendMessage（工人 → 本機的那條）")
    mailbox.send_result(CHECK_JOB_ID)
    message = receive_own_message(mailbox.receive_result, "results")
    print(f"   ReceiveMessage 收到：job_id={message.job_id}")
    mailbox.delete_result_message(message.receipt_handle)
    print("   DeleteMessage 完成")

    print("✅ SQS OK：兩條佇列都能 send → receive → delete")


def main() -> None:
    commands = sys.argv[1:]
    if not commands:
        raise SystemExit("用法：python scripts/aws_check.py s3 [sqs]")
    print(f"金鑰來源 = {credential_source()}")
    for name in commands:
        if name == "s3":
            check_s3()
        elif name == "sqs":
            check_sqs()
        else:
            raise SystemExit(f"不認得的子命令：{name}（只有 s3 與 sqs）")


if __name__ == "__main__":
    main()
