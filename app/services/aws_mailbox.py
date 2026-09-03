"""AwsMailbox：把 AWS 的 S3 ＋ 兩條 SQS 佇列 ＋ EC2 狀態查詢包成十四個方法。

★ **全系統唯一 import boto3／botocore 的地方**（總覽 §7 鐵律 5；
  tests/unit/test_aws_mailbox_unit.py::test_boto3只在aws_mailbox裡出現 掃碼釘住）。

【這一層有多薄】
它幾乎沒有邏輯：組鍵名、把參數擺對位置、把 AWS 的回應形狀翻成 Python 好用的東西。
「什麼時候送、等多久、逾時怎麼辦」在 app/services/cloud_ingest.py；
「看幾次圖、失敗怎麼算」在 app/workers/cloud_worker.py 與 app/services/gated_ingest.py。
這裡只做一件事：**忠實地打 API**。

【只有這四種情況不照實往外丟，其餘一律往外丟】
  1. get_object 遇到 NoSuchKey／404 → 回 None（「還沒寫好」是正常狀態，不是壞掉）
     ⚠ 前提是 IAM policy 有給 s3:ListBucket——沒有的話 S3 對不存在的 key 回的是
       403 AccessDenied 而不是 404，這裡就會往外丟（刻意不把 AccessDenied 當「不在」）
  2. delete_objects 失敗 → 只 logger.warning（清理是「盡力」，design6 §2.1 明文；
     清不掉的殘骸兩天後由 S3 Lifecycle 掃掉）。「失敗」有兩種長相：整個請求丟例外、
     或請求成功但回應的 Errors 裡列了刪不掉的 key——兩種都只 warning
  3. instance_state 查無 → 回 "unknown"（讓呼叫端只需要判斷 == "running"）。
     「查無」＝ InvalidInstanceID.NotFound 這個錯誤代碼、或空的 Reservations
  4. receive_job／receive_result 拿到壞紙條（body 不是 JSON、或沒有 job_id）→
     logger.warning ＋ 用 receipt handle 直接刪掉 ＋ 回 None（總覽 §10.2 追認項 K）。
     呼叫端拿不到 handle 就刪不掉它，留著會每次可見度到期就回來一次、回 4 天
其他任何錯誤（AccessDenied、沒有憑證、連不上）都**原樣往外丟**——
上一層要靠它們決定 fallback（design6 D10、§8 錯誤表第 3／4 列）。
安靜地吞掉會變成「每一筆都逾時，你以為 AWS 慢，其實是 IAM 少一行」。

【它不做的事】
不建 bucket、不建佇列、不刪佇列、不列 bucket 內容（那些是人做的事，
personaldocai-mac-policy 也沒給那些權限）；不重試、不做 backoff、不管連線池。
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from app.services.cloud_ingest import MailboxMessage

logger = logging.getLogger(__name__)

# 所有物件都住在這個前綴底下。Phase 84 的 Lifecycle 清潔規則也是掛在它上面，
# 兩邊必須一致——鍵名跑掉的話那把掃把就掃不到殘骸。
KEY_PREFIX = "documents"

# content_type -> input 物件的副檔名。
# ★ 工人那端是**看副檔名**反推 content_type 的（總覽 §2.6 第 4 步），這張表是雙向契約。
# ⚠ 三對值與 app/services/staging_service.py 的 STAGING_EXTENSIONS 逐字相同，
#   但**刻意各留一份**：那邊管的是「本機暫存檔叫什麼」（會拉進 config／DATA_DIR），
#   這邊管的是「S3 物件叫什麼」，而本模組之後要被 EC2 上的 cloud_worker import
#   （Phase 87；那台機器沒有資料庫也沒有 data/）。不要為了去重複改成 import 那一份。
#   漂移的防線是測試：本 phase 的 test_input_key依content_type給副檔名 與
#   既有的 test_cloud_ingest_unit.py::test_input鍵名依content_type決定副檔名 各把值釘死。
INPUT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}

# SQS 長輪詢的硬上限（AWS 規定就是 20 秒，填更大會被拒絕）。
# 夾在這一層而不是要求每個呼叫端自己記得：wait_result 傳進來的是「還剩幾秒」，
# 那個數字動輒 300。
# ⚠ app/services/cloud_ingest.py 也有一個同名同值的常數（它的 _poll_wait_seconds 用）。
#   **兩層各夾一次是刻意的**：這一層不必相信呼叫端夾過（Phase 87 的 cloud_worker
#   直接呼叫 receive_job()，走的根本不是 cloud_ingest 那條路）。不要改成互相 import。
MAX_WAIT_SECONDS = 20

# get_object 遇到這兩個錯誤代碼時翻譯成 None。
# 為什麼有兩個：GetObject 回的是 NoSuchKey，而 HeadObject 之類的 API 回的是 "404"。
# 本專案只用 GetObject，但多認一個字串不花成本，也省掉日後換 API 時的意外。
MISSING_KEY_CODES = ("NoSuchKey", "404")

# instance_state 遇到這個錯誤代碼時翻譯成 "unknown"。
# ★ 「查無這台機器」在 AWS 是一個**錯誤**、不是空清單：DescribeInstances 對不存在
#   （或 Terminate 超過一小時）的 instance id 丟 ClientError，代碼 InvalidInstanceID.NotFound。
#   空的 Reservations 只會發生在「那台機器不是你的」（AWS 默默不列出來）——兩種都算查無。
#   其他代碼（id 格式打錯的 InvalidInstanceID.Malformed、沒權限的 UnauthorizedOperation）
#   照樣往外丟：那些是設定或權限真的錯了，讓 Phase 89 的 Ec2Probe 把原因寫進 log 才好查。
UNKNOWN_INSTANCE_CODES = ("InvalidInstanceID.NotFound",)


class AwsMailbox:
    """本機端與工人端共用的「寄物櫃 ＋ 兩條佇列」實作（design6 D8／D9）。

    三個 client 都可以從外面注入（s3／sqs／ec2 參數）——單元測試就是靠這個塞 stub，
    所以那一整檔測試連一次網路都不會碰。不注入時才自己建，而且
    **region 一律明傳**（不靠環境變數猜；猜錯區的症狀是「東西建好了卻找不到」）。

    ⚠ 建立 boto3 client **不會連線、也不會驗證憑證**——沒有憑證時，
      例外是在第一次真的呼叫 API 時才丟出來（NoCredentialsError）。
      這正是我們要的：get_cloud_route() 才不會在組裝階段就炸掉，
      而是讓錯誤發生在 submit() 裡、被 gated_ingest 接住走 fallback（design6 §8 第 3 列）。
    """

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
    ) -> None:
        self._bucket = bucket
        self._jobs_queue_url = jobs_queue_url
        self._results_queue_url = results_queue_url
        self._region = region
        self._s3 = s3 if s3 is not None else boto3.client("s3", region_name=region)
        self._sqs = sqs if sqs is not None else boto3.client("sqs", region_name=region)
        self._ec2 = ec2 if ec2 is not None else boto3.client("ec2", region_name=region)

    # ---------- 三個鍵名（design6 §2.2 的契約）----------

    def input_key(self, job_id: str, content_type: str) -> str:
        """本機 Put、工人 Get 的原始檔。

        content_type 不在對照表裡會丟 KeyError——**這是刻意的**：
        上傳端只可能收到那三種（config.ALLOWED_CONTENT_TYPES），真的出現第四種
        代表某處的驗證破了，寧可當場炸給 gated_ingest 接住走 fallback，
        也不要安靜地存成一個沒有副檔名的檔（工人拿到之後會猜不出型別）。
        """
        return f"{KEY_PREFIX}/{job_id}/input{INPUT_EXTENSIONS[content_type]}"

    def context_key(self, job_id: str) -> str:
        """本機 Put、工人 Get 的 prompt 材料（資料夾／實體／糾錯三份清單）。"""
        return f"{KEY_PREFIX}/{job_id}/context.json"

    def result_key(self, job_id: str) -> str:
        """工人 Put、本機 Get 的看圖結果。"""
        return f"{KEY_PREFIX}/{job_id}/result.json"

    # ---------- S3 ----------

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        """把位元組放進寄物櫃。失敗直接往外丟（上一層要靠它決定 fallback）。"""
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def get_object(self, key: str) -> bytes | None:
        """從寄物櫃拿位元組；**東西不在就回 None**（不是例外）。

        「不在」是本專案最常見的正常狀態：崩潰重送時先看看結果在不在、
        工人每次先看看 result.json 在不在做冪等——兩處都不該用例外表達。

        其他錯誤（AccessDenied、沒憑證、連不上）一律原樣往外丟。
        """
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in MISSING_KEY_CODES:
                return None
            raise
        # 真 S3 的 Body 是「像檔案的物件」，一定要 .read() 才是位元組
        return response["Body"].read()

    def delete_objects(self, keys: list[str]) -> None:
        """一次刪掉好幾個物件。**盡力就好**：失敗只留一行 warning，不往外丟。

        理由（design6 §2.1「盡力刪物件」）：這一步永遠是「事情已經做完了、
        順手把垃圾收一收」。刪不掉最多留下殘骸，而殘骸兩天後會被 S3 Lifecycle
        掃掉（Phase 84）。反過來如果往外丟，就會出現「照片明明已經入庫，
        卻因為清不掉一個垃圾檔而被標成 failed」——那糟糕一百倍。
        """
        if not keys:
            return
        try:
            response = self._s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in keys]},
            )
        except Exception as error:  # 刻意攔全部：清理失敗不可以害到主流程
            logger.warning("刪 S3 物件失敗（盡力就好，Lifecycle 兩天後會清）：%s", error)
            return
        # ⚠ DeleteObjects 是「一次刪很多個」的批次 API：某幾個 key 刪不掉時 S3 **不會丟例外**，
        #   而是回 HTTP 200、把失敗的那幾個列在 Errors 裡（每個有 Key／Code／Message）。
        #   不看這個清單的話，IAM 少一行 s3:DeleteObject 會安靜地留下殘骸——一樣只 warning，不炸。
        for failure in response.get("Errors") or []:
            logger.warning(
                "刪 S3 物件失敗（盡力就好，Lifecycle 兩天後會清）：key=%s code=%s message=%s",
                failure.get("Key"),
                failure.get("Code"),
                failure.get("Message"),
            )

    # ---------- SQS：jobs（本機 Send、工人 Receive／Delete）----------

    def send_job(self, job_id: str, s3_key: str) -> None:
        """通知工人「有新工作了」。body 只有兩個字串鍵，一個位元組都沒有。"""
        self._sqs.send_message(
            QueueUrl=self._jobs_queue_url,
            MessageBody=json.dumps({"job_id": job_id, "s3_key": s3_key}),
        )

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None:
        """工人端：拿一則工作。沒有就回 None。"""
        return self._receive(self._jobs_queue_url, wait_seconds)

    def delete_job_message(self, receipt_handle: str) -> None:
        """工人端：這則做完了，把它從 jobs 佇列刪掉。"""
        self._sqs.delete_message(
            QueueUrl=self._jobs_queue_url,
            ReceiptHandle=receipt_handle,
        )

    # ---------- SQS：results（工人 Send、本機 Receive／Delete／改可見度）----------

    def send_result(self, job_id: str) -> None:
        """工人端：result.json **已經放進 S3 之後**才發這則（D9 的順序鐵律）。

        順序反過來的話，本機會被叫醒去拿一個還沒寫完的檔——那是最難查的一種壞法
        （安靜地拿到半截 JSON）。順序由 cloud_worker 保證，這裡只負責發。
        """
        self._sqs.send_message(
            QueueUrl=self._results_queue_url,
            MessageBody=json.dumps({"job_id": job_id}),
        )

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None:
        """本機端：等結果通知。沒有就回 None（呼叫端自己決定要不要再等）。"""
        return self._receive(self._results_queue_url, wait_seconds)

    def delete_result_message(self, receipt_handle: str) -> None:
        """本機端：這則處理完了（不論是我的還是別人留下的殘訊息），刪掉。"""
        self._sqs.delete_message(
            QueueUrl=self._results_queue_url,
            ReceiptHandle=receipt_handle,
        )

    def release_result_message(self, receipt_handle: str) -> None:
        """本機端：「這則不是我的」——可見度改成 0，立刻還回去給它的主人。

        results 是一條**共用**佇列：兩筆 job 同時在等的時候一定會收到別人的訊息。
        不還回去的話，別人要等到可見度逾時（30 秒）才拿得到，
        而那 30 秒很可能已經超過它的 deadline → 它會白白 fallback。
        """
        self._sqs.change_message_visibility(
            QueueUrl=self._results_queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=0,
        )

    # ---------- EC2（Phase 89 的 Ec2Probe 會用它）----------

    def instance_state(self, instance_id: str) -> str:
        """那台工人機現在是什麼狀態：running／stopped／pending／stopping…

        查無就回 "unknown"（不回 None、不丟例外）——呼叫端因此只需要判斷
        `== "running"`，其他任何字串都自然變成「不可用 → fallback」。
        「查無」有兩種長相：AWS 丟 InvalidInstanceID.NotFound（id 打錯、機器已 Terminate
        超過一小時——這是最常見的）、或回空的 Reservations（那台機器不是你的）。
        其他錯誤（UnauthorizedOperation、AuthFailure、連不上）照樣往外丟，
        Phase 89 的 Ec2Probe 會接住它們變成 False 並把原因寫進 log。

        回應結構有兩層是 AWS 的歷史包袱：一次 run-instances 可以開好幾台，
        那一批叫一個 reservation。本專案永遠只問一台，所以固定取 [0][0]。
        """
        try:
            response = self._ec2.describe_instances(InstanceIds=[instance_id])
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in UNKNOWN_INSTANCE_CODES:
                return "unknown"
            raise
        reservations = response.get("Reservations") or []
        if not reservations:
            return "unknown"
        instances = reservations[0].get("Instances") or []
        if not instances:
            return "unknown"
        return instances[0].get("State", {}).get("Name", "unknown")

    # ---------- 內部共用 ----------

    def _receive(self, queue_url: str, wait_seconds: int) -> MailboxMessage | None:
        """兩條佇列共用的收信：一次一則、長輪詢最多 20 秒、body 只解析出字串。

        ⚠ 真 SQS 在「沒有訊息」時回的字典裡**根本沒有 Messages 這個鍵**
          （不是回空清單），所以一定要用 .get() 取。

        ⚠ 壞紙條（body 不是 JSON、或沒有 job_id）在**這一層**就處理掉：warning ＋
          用手上的 receipt handle 直接刪掉 ＋ 回 None（總覽 §10.2 追認項 K）。
          理由：呼叫端連 receipt handle 都拿不到，根本刪不掉它；留著只會每次可見度到期
          就回來一次（jobs 900 秒、results 30 秒），直到 4 天保留期滿。
          會出現壞紙條的情況只有一種：有人用 aws sqs send-message 手動塞了東西。
        """
        response = self._sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=max(0, min(wait_seconds, MAX_WAIT_SECONDS)),
        )
        messages = response.get("Messages") or []
        if not messages:
            return None
        message = messages[0]
        try:
            body = json.loads(message["Body"])
            job_id = body["job_id"]
        except (ValueError, KeyError, TypeError):
            # ValueError＝不是 JSON（json.JSONDecodeError 是它的子類）；
            # KeyError＝是字典但沒有 job_id；TypeError＝是 JSON 但不是字典（例如 123 或清單）
            body, job_id = None, None
        if not isinstance(job_id, str) or not job_id:
            # ⚠ 只印**佇列名**（URL 的最後一段）與 body 的前 200 字，兩者都是刻意的：
            #   完整的 QueueUrl 裡有 AWS 帳號 ID，而 worker 的 log 常被逐字貼進報告與
            #   CLAUDE.md（這個 repo 是公開的）；壞紙條本身最大可以到 256 KB，
            #   整包進 log 只會把真正有用的行淹掉。
            logger.warning(
                "佇列裡有一則認不得的訊息（不是 JSON、或沒有 job_id），直接刪掉：queue=%s body=%r",
                queue_url.rsplit("/", 1)[-1],
                (message.get("Body") or "")[:200],
            )
            self._sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            return None
        return MailboxMessage(
            job_id=job_id,
            s3_key=body.get("s3_key"),
            receipt_handle=message["ReceiptHandle"],
        )
