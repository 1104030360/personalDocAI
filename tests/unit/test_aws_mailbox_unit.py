"""AwsMailbox 的單元測試：全部用手寫的 stub client，**一個位元組都不出網**。

不用 moto／localstack 的理由：本專案只用到八個 API，手寫 stub 更好讀，
也更容易斷言「到底帶了哪些參數」（WaitTimeSeconds 有沒有超過 20、VisibilityTimeout
是不是 0、jobs 與 results 兩條佇列有沒有被寫反）——那才是這一層真正會出錯的地方。

⚠ 這一檔連 boto3 的 client 都不會建立：每顆測試都把三個 client 直接注入建構子。
   pytest 全程不連真 AWS（總覽 §7 鐵律 2）。
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.services.aws_mailbox import AwsMailbox

PROJECT_ROOT = Path(__file__).resolve().parents[2]

JOBS_URL = "https://sqs.example.invalid/jobs"
RESULTS_URL = "https://sqs.example.invalid/results"


def make_client_error(code: str, operation: str) -> ClientError:
    """造一個 boto3 會丟的 ClientError。

    真實的 ClientError 是這樣被建出來的：第一個參數是「AWS 回來的錯誤內容」，
    第二個參數是「哪一個 API」。錯誤代碼要放在 response["Error"]["Code"]——
    aws_mailbox.get_object() 就是讀這個位置決定「回 None 還是往外丟」。
    """
    return ClientError({"Error": {"Code": code, "Message": "測試用"}}, operation)


class StubS3:
    """長得像 boto3 S3 client 的最小假件：記下呼叫參數、回可控的結果。"""

    def __init__(
        self,
        *,
        get_body: bytes | None = None,
        get_error=None,
        delete_error=None,
        delete_errors: list[dict] | None = None,
        put_error=None,
    ):
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self._get_body = get_body
        self._get_error = get_error
        self._delete_error = delete_error  # 整個請求炸掉（丟例外）
        self._delete_errors = delete_errors  # 請求成功但某幾個 key 刪不掉（回應裡的 Errors）
        self._put_error = put_error  # 設了就讓 put_object 丟這個例外

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        if self._put_error is not None:
            raise self._put_error
        return {}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        if self._get_error is not None:
            raise self._get_error
        # 真的 S3 回來的 Body 是一個「像檔案的物件」，要 .read() 才拿得到位元組。
        # 這裡用 BytesIO 模擬同一個介面——實作端因此不會寫出「直接把 Body 當 bytes 用」的錯。
        return {"Body": io.BytesIO(self._get_body or b"")}

    def delete_objects(self, **kwargs):
        self.delete_calls.append(kwargs)
        if self._delete_error is not None:
            raise self._delete_error
        # 真 S3 的回應長相：部分失敗也是 HTTP 200，失敗的 key 列在 Errors、成功的列在 Deleted
        if self._delete_errors:
            return {"Errors": list(self._delete_errors)}
        return {"Deleted": [{"Key": obj["Key"]} for obj in kwargs["Delete"]["Objects"]]}


class StubSqs:
    """長得像 boto3 SQS client 的最小假件。

    messages 是一串「還沒被領走的訊息」，每次 receive_message 領走最前面那一則；
    領完了就回一個**沒有 Messages 這個鍵**的字典——這正是真 SQS 的行為
    （不是回空清單，是根本沒有那個鍵），實作端必須用 .get("Messages") 才不會 KeyError。
    """

    def __init__(self, *, messages: list[dict] | None = None, send_error=None):
        self.send_calls: list[dict] = []
        self.receive_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.visibility_calls: list[dict] = []
        self._messages = list(messages or [])
        self._send_error = send_error  # 設了就讓 send_message 丟這個例外

    def send_message(self, **kwargs):
        self.send_calls.append(kwargs)
        if self._send_error is not None:
            raise self._send_error
        return {}

    def receive_message(self, **kwargs):
        self.receive_calls.append(kwargs)
        if not self._messages:
            return {"ResponseMetadata": {}}
        return {"Messages": [self._messages.pop(0)]}

    def delete_message(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}

    def change_message_visibility(self, **kwargs):
        self.visibility_calls.append(kwargs)
        return {}


class StubEc2:
    """長得像 boto3 EC2 client 的最小假件（只有 describe_instances）。"""

    def __init__(self, *, reservations: list[dict] | None = None, error=None):
        self.calls: list[dict] = []
        self._reservations = reservations if reservations is not None else []
        self._error = error  # 設了就一律丟這個例外（模擬 InvalidInstanceID.NotFound 等）

    def describe_instances(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Reservations": self._reservations}


def make_mailbox(*, s3=None, sqs=None, ec2=None) -> AwsMailbox:
    """建一個全部用 stub 的 AwsMailbox。bucket 與兩條佇列都是假的（不會被真的連上）。"""
    return AwsMailbox(
        bucket="test-bucket",
        jobs_queue_url=JOBS_URL,
        results_queue_url=RESULTS_URL,
        region="ap-northeast-1",
        s3=s3 if s3 is not None else StubS3(),
        sqs=sqs if sqs is not None else StubSqs(),
        ec2=ec2 if ec2 is not None else StubEc2(),
    )


# ---------- 三個鍵名（design6 §2.2 的契約）----------


def test_input_key依content_type給副檔名():
    """三種格式各對到一個副檔名。工人那端是**看副檔名**反推 content_type 的
    （總覽 §2.6 第 4 步），所以這張對照表是雙向契約。

    ⚠ 這三對值與 app/services/staging_service.py 的 STAGING_EXTENSIONS 逐字相同
      （tests/fakes.FakeMailbox 的 input_key 用的就是那一份）。兩邊是**不同的契約**、
      刻意各留一份定義；本顆與 test_cloud_ingest_unit.py::test_input鍵名依content_type決定副檔名
      各自把值釘死，所以漂移一定會被抓到。
    """
    mailbox = make_mailbox()

    assert mailbox.input_key("job-1", "image/jpeg") == "documents/job-1/input.jpg"
    assert mailbox.input_key("job-1", "image/png") == "documents/job-1/input.png"
    assert mailbox.input_key("job-1", "application/pdf") == "documents/job-1/input.pdf"


def test_context_key與result_key的路徑():
    """三個物件全部住在 documents/{job_id}/ 底下。這是 Lifecycle 能生效的前提：
    Phase 84 的清潔規則掛在 documents/ 前綴上，鍵名跑掉那把掃把就掃不到。
    """
    mailbox = make_mailbox()

    assert mailbox.context_key("job-1") == "documents/job-1/context.json"
    assert mailbox.result_key("job-1") == "documents/job-1/result.json"


# ---------- S3 ----------


def test_put_object帶ContentType():
    """四個參數都要對。ContentType 不是可有可無：少了它 S3 會存成
    application/octet-stream，用瀏覽器看時變成「下載檔案」而不是「顯示圖片」。
    """
    s3 = StubS3()
    mailbox = make_mailbox(s3=s3)

    mailbox.put_object("documents/job-1/input.png", b"PNGDATA", "image/png")

    assert len(s3.put_calls) == 1
    call = s3.put_calls[0]
    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == "documents/job-1/input.png"
    assert call["Body"] == b"PNGDATA"
    assert call["ContentType"] == "image/png"


def test_get_object拿得回位元組而delete_objects送出鍵清單():
    """S3 的兩條成功路徑：讀得回東西、刪得掉東西。

    ★ 這一顆是總覽 §10.2 追認項 J 特別補進來的成功路徑測試（理由見計畫 §8）。
      沒有它的話，一個「get_object 永遠 return None」的實作會讓其他 15 顆全綠——
      而 get_object 正是「把雲端算好的 result.json 拿回家」的那一步，
      壞掉的話整條雲端路會安靜地每次都逾時 fallback，看起來像 AWS 慢，其實是程式錯。
    """
    s3 = StubS3(get_body=b'{"job_id": "job-1"}')
    mailbox = make_mailbox(s3=s3)

    content = mailbox.get_object("documents/job-1/result.json")

    assert content == b'{"job_id": "job-1"}'
    assert s3.get_calls[0]["Bucket"] == "test-bucket"
    assert s3.get_calls[0]["Key"] == "documents/job-1/result.json"

    mailbox.delete_objects(
        [
            "documents/job-1/input.png",
            "documents/job-1/context.json",
            "documents/job-1/result.json",
        ]
    )

    assert len(s3.delete_calls) == 1
    assert s3.delete_calls[0]["Bucket"] == "test-bucket"
    assert s3.delete_calls[0]["Delete"] == {
        "Objects": [
            {"Key": "documents/job-1/input.png"},
            {"Key": "documents/job-1/context.json"},
            {"Key": "documents/job-1/result.json"},
        ]
    }


def test_get_object遇到NoSuchKey回None():
    """「還沒寫好」是**正常狀態**，翻譯成 None、不是例外。

    誰會踩到：崩潰重送時的 fetch_result()（總覽 §2.5）、工人的冪等檢查
    （總覽 §2.6 第 1 步）——兩處的「不在」都是最常見的情況。
    """
    s3 = StubS3(get_error=make_client_error("NoSuchKey", "GetObject"))
    mailbox = make_mailbox(s3=s3)

    assert mailbox.get_object("documents/job-1/result.json") is None
    assert len(s3.get_calls) == 1


def test_get_object遇到其他錯誤照樣往外丟():
    """AccessDenied 是**真的壞了**，不可以偽裝成「檔案不在」。
    偽裝的後果：權限設錯時每一筆都安靜地逾時 fallback，你會以為是 AWS 慢，
    永遠查不到其實是 IAM policy 少了一行。
    """
    s3 = StubS3(get_error=make_client_error("AccessDenied", "GetObject"))
    mailbox = make_mailbox(s3=s3)

    with pytest.raises(ClientError):
        mailbox.get_object("documents/job-1/result.json")


def test_delete_objects失敗只記log不往外丟(caplog):
    """清理是**盡力**（design6 §2.1 明文）：刪不掉最多留殘骸，而殘骸兩天後會被
    Lifecycle 掃掉。往外丟的話會變成「照片已經入庫卻因為清不掉垃圾而標 failed」。

    S3 的「刪不掉」有**兩種長相**，兩種都要只 warning：
      ① 整個請求被拒（丟 ClientError）——例如 bucket 名打錯、整個 bucket 碰不到；
      ② 請求成功（HTTP 200）但某幾個 key 刪不掉——DeleteObjects 是批次 API，
         它把失敗的 key 列在回應的 Errors 裡、**不丟例外**。這是最容易漏掉的一種：
         IAM 少了 s3:DeleteObject 時看起來就是「沒事」，殘骸卻一直留著。
    """
    # ① 整個請求炸掉
    s3 = StubS3(delete_error=make_client_error("AccessDenied", "DeleteObjects"))
    mailbox = make_mailbox(s3=s3)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        mailbox.delete_objects(["documents/job-1/input.png"])  # 不可以炸

    assert len(s3.delete_calls) == 1
    assert "刪 S3 物件失敗" in caplog.text

    # ② HTTP 200，但 Errors 裡列了刪不掉的 key
    caplog.clear()
    failed_key = {"Key": "documents/job-1/input.png", "Code": "AccessDenied", "Message": "測試用"}
    s3_2 = StubS3(delete_errors=[failed_key])
    mailbox2 = make_mailbox(s3=s3_2)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        mailbox2.delete_objects(["documents/job-1/input.png"])  # 一樣不可以炸

    assert len(s3_2.delete_calls) == 1
    assert "刪 S3 物件失敗" in caplog.text
    assert "documents/job-1/input.png" in caplog.text, "要印出是哪個 key 刪不掉"


# ---------- SQS：jobs（本機 Send、工人 Receive／Delete）----------


def test_send_job的body恰兩鍵():
    """design6 §2.3：jobs 的 body 只有 job_id 與 s3_key。

    最後一條斷言守的是 §0 **禁止第 2 條**：佇列裡永遠只有字串，
    一個影像位元組都沒有。SQS 單則上限是 1 MiB（結論不變：影像仍不進 SQS——
    多頁 PDF 幾十 MB 放不下，而且放得下也不准放）。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.send_job("job-1", "documents/job-1/input.jpg")

    assert len(sqs.send_calls) == 1
    assert sqs.send_calls[0]["QueueUrl"] == JOBS_URL
    body = json.loads(sqs.send_calls[0]["MessageBody"])
    assert body == {"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}
    assert set(body) == {"job_id", "s3_key"}
    assert all(isinstance(value, str) for value in body.values())


def test_receive_job的等待秒數不超過20():
    """長輪詢上限就是 20 秒，填超過 SQS 直接拒絕。呼叫端（Phase 80 的 wait_result）
    傳進來的是「還剩幾秒」，動輒 300，所以夾在這一層最安全。
    """
    sqs = StubSqs(
        messages=[
            {
                "Body": json.dumps({"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}),
                "ReceiptHandle": "rh-jobs-1",
            }
        ]
    )
    mailbox = make_mailbox(sqs=sqs)

    message = mailbox.receive_job(300)

    assert sqs.receive_calls[0]["QueueUrl"] == JOBS_URL
    assert sqs.receive_calls[0]["WaitTimeSeconds"] == 20
    assert sqs.receive_calls[0]["MaxNumberOfMessages"] == 1
    assert message is not None
    assert message.job_id == "job-1"
    assert message.s3_key == "documents/job-1/input.jpg"
    assert message.receipt_handle == "rh-jobs-1"


def test_receive_job沒訊息時回None(caplog):
    """「拿不到一則可用的訊息」有三種長相，全部回 None、都不丟例外：
      ① 佇列是空的（常態）——順便釘住「真 SQS 空的時候回的字典裡根本沒有 Messages
         這個鍵」，寫成 回應["Messages"] 會 KeyError；
      ② 拿到一則 body 不是 JSON 的壞紙條；
      ③ 拿到一則是 JSON、但沒有 job_id 的壞紙條。
    ②③ 除了回 None，還要**用手上的 receipt handle 直接把它刪掉**並留一行 warning：
    呼叫端拿不到 handle 就刪不掉它，留著只會每次可見度到期就回來一次（jobs 900 秒），
    直到 4 天保留期滿——總覽 §10.2 追認項 K 的「壞紙條」在這一層就先擋掉。
    """
    # ① 空佇列
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    assert mailbox.receive_job(20) is None
    assert len(sqs.receive_calls) == 1
    assert sqs.delete_calls == []  # 沒東西可刪

    # ② 不是 JSON、③ 沒有 job_id：各自回 None，而且那一則要被刪掉（用對的佇列＋對的把手）
    sqs2 = StubSqs(
        messages=[
            {"Body": "這不是 JSON", "ReceiptHandle": "rh-bad-1"},
            {"Body": json.dumps({"s3_key": "documents/x/input.jpg"}), "ReceiptHandle": "rh-bad-2"},
        ]
    )
    mailbox2 = make_mailbox(sqs=sqs2)

    with caplog.at_level(logging.WARNING, logger="app.services.aws_mailbox"):
        assert mailbox2.receive_job(20) is None
        assert mailbox2.receive_job(20) is None

    assert sqs2.delete_calls == [
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-bad-1"},
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-bad-2"},
    ]
    assert caplog.text.count("認不得的訊息") == 2
    # log 衛生（2026-09-02 review fix wave）：只准印**佇列名**（URL 的最後一段），
    # 不准把完整的 QueueUrl 印出去——真的 URL 裡有 AWS 帳號 ID，而 worker 的 log
    # 常被逐字貼進報告與 CLAUDE.md（這個 repo 是公開的）。
    assert "queue=jobs" in caplog.text
    assert JOBS_URL not in caplog.text, "完整的佇列 URL 帶著帳號 ID，不可以進 log"


def test_delete_job_message帶receipt_handle():
    """刪訊息要用 receipt handle，而且**兩條佇列不可以寫反**。

    寫反的症狀最惡劣而且不報錯：刪到別人的 results 訊息（那筆只能逾時 fallback），
    自己的 jobs 訊息沒刪掉，可見度到期又冒出來 → 同一張圖被看兩次。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.delete_job_message("rh-jobs")
    mailbox.delete_result_message("rh-results")

    assert sqs.delete_calls == [
        {"QueueUrl": JOBS_URL, "ReceiptHandle": "rh-jobs"},
        {"QueueUrl": RESULTS_URL, "ReceiptHandle": "rh-results"},
    ]


# ---------- SQS：results（工人 Send、本機 Receive／Delete／改可見度）----------


def test_send_result的body恰一鍵():
    """design6 §2.3：results 的 body 只有 job_id。不順便帶 result 的 key，
    是因為本機自己算得出來（result_key(job_id)），多一個欄位就多一種不一致。
    """
    sqs = StubSqs()
    mailbox = make_mailbox(sqs=sqs)

    mailbox.send_result("job-7")

    assert len(sqs.send_calls) == 1
    assert sqs.send_calls[0]["QueueUrl"] == RESULTS_URL
    body = json.loads(sqs.send_calls[0]["MessageBody"])
    assert body == {"job_id": "job-7"}
    assert set(body) == {"job_id"}
    assert all(isinstance(value, str) for value in body.values())


def test_release_result_message把可見度改成0():
    """「這則不是我的，馬上還回去給它的主人」＝ ChangeMessageVisibility 改成 0。

    results 是一條**共用**佇列（總覽 §10.1 追認項 d）：兩筆 job 同時在等的時候，
    你一定會收到別人的訊息。不還回去的話，別人就要等到可見度逾時（30 秒）才拿得到，
    而那 30 秒很可能已經超過它的 deadline → 它會白白 fallback。

    順便釘住 results 佇列的 body 只有 job_id、沒有 s3_key（所以 s3_key 是 None）。
    """
    sqs = StubSqs(messages=[{"Body": json.dumps({"job_id": "job-9"}), "ReceiptHandle": "rh-9"}])
    mailbox = make_mailbox(sqs=sqs)

    message = mailbox.receive_result(5)

    assert message is not None
    assert message.job_id == "job-9"
    assert message.s3_key is None
    assert sqs.receive_calls[0]["QueueUrl"] == RESULTS_URL
    assert sqs.receive_calls[0]["WaitTimeSeconds"] == 5

    mailbox.release_result_message(message.receipt_handle)

    assert len(sqs.visibility_calls) == 1
    assert sqs.visibility_calls[0] == {
        "QueueUrl": RESULTS_URL,
        "ReceiptHandle": "rh-9",
        "VisibilityTimeout": 0,
    }


# ---------- EC2（Phase 89 的 Ec2Probe 會用它）----------


def test_instance_state讀得到狀態名():
    """狀態藏在兩層底下：Reservations[0].Instances[0].State.Name（AWS 的歷史包袱：
    一次 run-instances 可以開好幾台，那一批叫一個 reservation）。本專案只問一台。
    """
    ec2 = StubEc2(reservations=[{"Instances": [{"State": {"Name": "running"}}]}])
    mailbox = make_mailbox(ec2=ec2)

    assert mailbox.instance_state("i-0123456789abcdef0") == "running"
    assert ec2.calls[0]["InstanceIds"] == ["i-0123456789abcdef0"]


def test_instance_state查無回unknown():
    """查不到那台機器時回字串 "unknown"，不回 None、也不丟例外。

    ★ 「查無」在 AWS 是一個**錯誤**、不是空清單：對不存在的 instance id
      （打錯、或 Terminate 超過一小時）DescribeInstances 丟 ClientError，
      代碼 InvalidInstanceID.NotFound——這才是 Phase 92 換機器之後最常見的情況。
      空的 Reservations 只會發生在「那台機器不是你的」（AWS 默默不列出來）。

    回 "unknown" 的好處：Phase 89 的 Ec2Probe 只需要判斷 == "running"，
    任何其他字串都自然變成「不可用 → fallback」，不必再多寫一條 None 的分支。
    """
    # 情況一：AWS 說「沒有這台」（最常見的查無）
    not_found = make_client_error("InvalidInstanceID.NotFound", "DescribeInstances")
    mailbox = make_mailbox(ec2=StubEc2(error=not_found))
    assert mailbox.instance_state("i-0123456789abcdef0") == "unknown"

    # 情況二：回應是空的（那台機器不是你的，AWS 默默不列）
    mailbox2 = make_mailbox(ec2=StubEc2(reservations=[]))
    assert mailbox2.instance_state("i-0123456789abcdef0") == "unknown"

    # 情況三：有 reservation 但裡面沒有 instance（AWS 偶爾會這樣回）
    mailbox3 = make_mailbox(ec2=StubEc2(reservations=[{"Instances": []}]))
    assert mailbox3.instance_state("i-0123456789abcdef0") == "unknown"

    # 反面：「查無」以外的錯誤（例如權限不足）照樣往外丟——
    # Phase 89 的 Ec2Probe 會接住它變成 False，並把真正的原因寫進 log
    unauthorized = make_client_error("UnauthorizedOperation", "DescribeInstances")
    mailbox4 = make_mailbox(ec2=StubEc2(error=unauthorized))
    with pytest.raises(ClientError):
        mailbox4.instance_state("i-0123456789abcdef0")


def test_put_object與send失敗時例外原樣往外丟():
    """★ 守門：這三個方法**絕對不可以**吞例外（design6 §8 錯誤表第 4 列）。

    要的是 fallback，不是「安靜地當作成功」：put_object／send_job／send_result 任何一個
    失敗，gated_ingest 都必須接到例外才知道要走 fallback=local reason=submit_failed。
    吞掉的話，照片會被當成「已經寄出去了」而永遠等不到結果——每一筆都逾時，
    看起來像 AWS 慢，其實是東西根本沒送出去。

    ⚠ 這一顆是**唯一**會在有人「順手」把這三個方法包成 try/except 時變紅的測試
      （其餘 16 顆都只驗成功路徑的參數）。用 `is` 比對例外物件本身，
      連「攔下來再丟一個自己包的新例外」也擋得住——那樣 ClientError 的錯誤代碼會不見。
    """
    put_failure = make_client_error("AccessDenied", "PutObject")
    s3 = StubS3(put_error=put_failure)
    mailbox = make_mailbox(s3=s3)

    with pytest.raises(ClientError) as caught:
        mailbox.put_object("documents/job-1/input.png", b"PNGDATA", "image/png")
    assert caught.value is put_failure
    assert len(s3.put_calls) == 1  # 真的有打出去（不是在前面就擋掉了）

    send_failure = make_client_error("AccessDenied", "SendMessage")
    sqs = StubSqs(send_error=send_failure)
    mailbox2 = make_mailbox(sqs=sqs)

    with pytest.raises(ClientError) as caught_job:
        mailbox2.send_job("job-1", "documents/job-1/input.jpg")
    assert caught_job.value is send_failure

    with pytest.raises(ClientError) as caught_result:
        mailbox2.send_result("job-1")
    assert caught_result.value is send_failure

    assert len(sqs.send_calls) == 2


# ---------- 掃碼：boto3 只准出現在這一個檔 ----------


def test_boto3只在aws_mailbox裡出現():
    """總覽 §7 鐵律 5：全系統只有 app/services/aws_mailbox.py 可以 import boto3／botocore。

    為什麼這條規則值得一顆測試守著：
      ① cloud_ingest.py 只認 CloudMailbox 這個 Protocol，所以它的測試才能用假信箱跑；
         哪天有人「順手」在那裡 import boto3，第五道安全網（AWS_ENDPOINT_URL 指死埠）
         就從「保險」退化成「唯一的防線」。
      ② app/workers/cloud_worker.py（Phase 87）也一樣——它拿到的是別人建好的信箱。

    ★ 用**正規表示式**比對而不是 `"import boto3" in 原始碼`：
      別的檔案的中文註解本來就會提到「不要 import boto3」這幾個字，
      用子字串比對會一直誤中，最後大家只好把註解改成暗語——那比沒有測試還糟。
      這個樣式只認「行首（允許縮排）的 import／from 陳述句」，
      所以連寫在函式裡面的延遲 import 也抓得到。
    """
    import_pattern = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)

    offenders = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        # 比**相對路徑**而不是檔名：只比檔名的話，哪天有人開了
        # app/workers/aws_mailbox.py（Phase 87 就要加 app/workers/），
        # 那個檔會跟著被放行，而它根本不是這條鐵律豁免的那一個。
        if path.relative_to(PROJECT_ROOT).as_posix() == "app/services/aws_mailbox.py":
            continue
        if import_pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == [], (
        f"只有 app/services/aws_mailbox.py 可以 import boto3／botocore：{offenders}"
    )

    # 反過來也釘一次：那個檔**必須**真的 import 了（不然這顆測試會變成永遠綠的裝飾品）
    mailbox_source = (PROJECT_ROOT / "app" / "services" / "aws_mailbox.py").read_text(
        encoding="utf-8"
    )
    assert import_pattern.search(mailbox_source), "aws_mailbox.py 應該要 import boto3"

    # 同一條鐵律的另一半（2026-09-02 review fix wave）：dependencies.py 那行
    # `from app.services.aws_mailbox import AwsMailbox` **必須留在 get_cloud_route() 裡面**。
    # 提到檔頭的話，pytest 一收集就會間接載入 boto3——而上面那個樣式只認直接寫
    # `import boto3` 的檔，抓不到這種「透過別的模組載入」的間接違規。
    dependencies_source = (PROJECT_ROOT / "app" / "dependencies.py").read_text(encoding="utf-8")
    assert not re.search(r"^(?:from|import)\s+.*aws_mailbox", dependencies_source, re.M), (
        "dependencies.py 的 aws_mailbox import 要留在 get_cloud_route() 函式裡，不可以提到檔頭"
    )
    assert re.search(
        r"^\s+from app\.services\.aws_mailbox import AwsMailbox", dependencies_source, re.M
    ), "get_cloud_route() 裡那行延遲 import 不見了？"
