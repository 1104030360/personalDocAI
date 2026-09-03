"""get_cloud_route() 的單元測試：只檢查「建出來的物件對不對」，**一次 AWS API 都不打**。

建立 boto3 的 client 不會連線（第一次真的呼叫方法時才發 HTTP），而 AlwaysRunning
的 is_running() 是純 Python 的 return True——所以這兩顆測試跑起來又快又安全。
第五道安全網另外還把 AWS_ENDPOINT_URL 指到死埠 http://127.0.0.1:9 當第二層保險。

★ 為什麼是 `from app.dependencies import get_cloud_route as real_get_cloud_route`：
  conftest 的 autouse fixture wire_fake_cloud 會用 monkeypatch 把
  dependencies.get_cloud_route 這個**模組屬性**換成回 CloudRouteOff 的假件。
  而這一行 import 發生在 pytest 的**收集階段**（fixture 還沒跑），
  所以它抓住的是**原始的函式物件**——換模組屬性影響不到它。
  ⚠ 這在產品碼裡是要避免的「早綁定」陷阱，這裡是**刻意**用它來取得原版。
    不要「順手改成 dependencies.get_cloud_route()」，那會讓這兩顆測試變成
    永遠在測假件、永遠綠。
"""

from __future__ import annotations

import pytest

from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route as real_get_cloud_route
from app.services import aws_mailbox as aws_mailbox_module
from app.services import cloud_ingest
from app.services.aws_mailbox import AwsMailbox
from tests.fakes import FakeMailbox


def configure_assume_mode(monkeypatch) -> None:
    """把 config 擺成「.env 已經填好、CLOUD_ROUTE=assume」的樣子。

    值都是假的（bucket 與佇列 URL 不存在也沒關係）——本檔不會真的去呼叫它們。
    ⚠ 一定要用 monkeypatch 改 config 的屬性，不要直接指派：
      monkeypatch 會在測試結束時自動還原，直接指派則會污染後面每一顆測試。
    """
    monkeypatch.setattr(config, "CLOUD_ROUTE", "assume")
    monkeypatch.setattr(config, "S3_BUCKET", "test-bucket")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/jobs")
    monkeypatch.setattr(config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/results")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")


def test_assume模式建出CloudRoute而且探測恆為True(monkeypatch):
    """assume ＝「假設遠端開著」：回真的 CloudRoute，而且 available() 永遠是 True。

    available() 之所以測得動而且不出網：assume 模式用的探測是 AlwaysRunning，
    它的 is_running() 就是 `return True`，一次 AWS API 都不打（總覽 §2.4.1）。

    這一顆同時守住兩件事：
      ① 不再是 NotImplementedError（Phase 77 留下的暫時分支已被換掉）
      ② 不是 CloudRouteOff（那樣的話 available() 會是 False，照片永遠出不了門）
    """
    configure_assume_mode(monkeypatch)

    route = real_get_cloud_route()

    assert isinstance(route, cloud_ingest.CloudRoute)
    assert not isinstance(route, cloud_ingest.CloudRouteOff)
    assert route.available() is True


def test_assume模式的逾時秒數讀config(monkeypatch):
    """逾時秒數必須是**呼叫當下**從 config 讀的，不可以寫死。

    作法：把 cloud_ingest.CloudRoute 暫時換成一個只記參數的側錄類別，
    這樣不必知道 CloudRoute 內部把 timeout_seconds 存在哪個私有屬性
    （測私有屬性名 ＝ 之後重新命名就會紅，那是假的把關）。

    順便一次驗完建構子的三個位置：mailbox 是真的 AwsMailbox、
    probe 是 AlwaysRunning、timeout_seconds 來自 config。

    為什麼這件事重要：這個數字寫死的話，Phase 92 之後想把逾時從 300 調成別的值
    就得改程式、重建映像；而它本來只該是 .env 的一行。
    """
    configure_assume_mode(monkeypatch)
    monkeypatch.setattr(config, "CLOUD_RESULT_TIMEOUT_SECONDS", 123)

    captured: dict = {}

    class RecordingCloudRoute:
        def __init__(self, mailbox, probe, *, timeout_seconds):
            captured["mailbox"] = mailbox
            captured["probe"] = probe
            captured["timeout_seconds"] = timeout_seconds

    monkeypatch.setattr(cloud_ingest, "CloudRoute", RecordingCloudRoute)

    real_get_cloud_route()

    assert captured["timeout_seconds"] == 123
    assert isinstance(captured["mailbox"], AwsMailbox)
    assert isinstance(captured["probe"], cloud_ingest.AlwaysRunning)


def test_assume模式把config的四個值對應到AwsMailbox(monkeypatch):
    """★ 守門：四個 config 值有沒有**擺進對的 keyword**（2026-09-02 review fix wave）。

    最想擋的是「兩條佇列 URL 對調」——那是完全不會報錯的一種錯：
    照片會被送進 results 佇列（沒有人在聽），而本機在 jobs 佇列上空等到逾時，
    最後每一筆都 fallback=local reason=result_timeout，看起來像 AWS 慢。
    既有那顆 test_assume模式的逾時秒數讀config 只斷言 mailbox 是不是 AwsMailbox，
    對調了照樣綠。

    作法：把 **aws_mailbox 模組上的 AwsMailbox 屬性**換成側錄類別。
    get_cloud_route() 是在函式裡 `from app.services.aws_mailbox import AwsMailbox`，
    那一行在**呼叫當下**才去讀模組屬性，所以換得掉（改成在檔頭 import 就換不掉了——
    test_aws_mailbox_unit.py 的掃碼測試另外守著那件事）。

    四個假值刻意**彼此不同**：全都一樣的話，對調兩條 URL 這顆測試會照樣綠。
    """
    configure_assume_mode(monkeypatch)
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-A")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/queue-JOBS")
    monkeypatch.setattr(
        config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/queue-RESULTS"
    )
    monkeypatch.setattr(config, "AWS_REGION", "region-Z")

    captured: dict = {}

    class RecordingAwsMailbox:
        def __init__(self, *, bucket, jobs_queue_url, results_queue_url, region):
            captured["bucket"] = bucket
            captured["jobs_queue_url"] = jobs_queue_url
            captured["results_queue_url"] = results_queue_url
            captured["region"] = region

    monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", RecordingAwsMailbox)

    real_get_cloud_route()

    assert captured == {
        "bucket": "bucket-A",
        "jobs_queue_url": "https://sqs.example.invalid/queue-JOBS",
        "results_queue_url": "https://sqs.example.invalid/queue-RESULTS",
        "region": "region-Z",
    }


# ---------------- ec2 模式（Phase 89）----------------


@pytest.fixture(autouse=True)
def clear_ec2_route_cache():
    """_ec2_cloud_route() 是「整個行程只建一次」的（lru_cache），前後都要清。

    不清的話：這一顆測試建的假信箱會被留給後面的測試，或反過來被上一顆的殘留干擾
    ——症狀是「單獨跑綠、整批跑紅」，最難查的那一種。
    """
    dependencies._ec2_cloud_route.cache_clear()
    yield
    dependencies._ec2_cloud_route.cache_clear()


def test_ec2模式建出CloudRoute而且探測是Ec2Probe(monkeypatch):
    """CLOUD_ROUTE=ec2 時要建出「會真的去問機器狀態」的那一條路。

    怎麼證明它是 Ec2Probe 而不是 AlwaysRunning：讓假信箱回 stopped。
    AlwaysRunning 不管三七二十一都回 True、一次 instance_state 都不叫；
    所以 available() 是 False ＋ instance_state 恰被叫一次、而且問的是
    config.EC2_WORKER_INSTANCE_ID 那台，就只可能是 Ec2Probe。

    ★ 這裡把 AwsMailbox 整個換掉，所以**完全不會**碰到 boto3、也不會出網——
      能這樣換是因為 _ec2_cloud_route() 的 import 寫在函式**裡面**
      （`from … import AwsMailbox` 每次呼叫都會重新去模組上取那個名字）。
      換的是 **aws_mailbox_module 這個模組上的屬性**（檔頭那一行
      `from app.services import aws_mailbox as aws_mailbox_module` 就是為了這件事，
      Phase 86 的第 3 顆已經在用同一招）。

    ★ 呼叫的是檔頭早綁定的 real_get_cloud_route（Phase 86 那 3 顆就是用這個名字）：
      第五道安全網每顆測試都會把 dependencies.get_cloud_route 換成「永遠回 CloudRouteOff」
      的替身，寫 dependencies.get_cloud_route() 拿到的會是替身，這顆就永遠紅。

    ★ 四個假值刻意**彼此不同**（沿用 Phase 86 第 3 顆的手法）：全都一樣的話，
      「兩條佇列 URL 對調」這種完全不會報錯的設定錯，這顆測試會照樣綠。
    """
    captured: list[dict] = []
    mailbox = FakeMailbox()
    mailbox.instance_state_script = ["stopped"]

    def fake_aws_mailbox(**kwargs):
        captured.append(kwargs)
        return mailbox

    monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", fake_aws_mailbox)
    monkeypatch.setattr(config, "CLOUD_ROUTE", "ec2")
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-A")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/queue-JOBS")
    monkeypatch.setattr(
        config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/queue-RESULTS"
    )
    monkeypatch.setattr(config, "AWS_REGION", "region-Z")
    monkeypatch.setattr(config, "EC2_WORKER_INSTANCE_ID", "i-test")
    monkeypatch.setattr(config, "EC2_PROBE_TTL_SECONDS", 60)

    route = real_get_cloud_route()

    assert isinstance(route, cloud_ingest.CloudRoute)
    # 四個參數都要從 config 來（打錯區或對到別的 bucket 是最難查的設定錯）
    assert captured == [
        {
            "bucket": "bucket-A",
            "jobs_queue_url": "https://sqs.example.invalid/queue-JOBS",
            "results_queue_url": "https://sqs.example.invalid/queue-RESULTS",
            "region": "region-Z",
        }
    ]
    assert route.available() is False, "機器是 stopped，探測要說不可用"
    assert mailbox.instance_state_calls == 1, "AlwaysRunning 不會問；問了一次就是 Ec2Probe"
    assert mailbox.calls == ["instance_state i-test"], (
        "要問的是 config.EC2_WORKER_INSTANCE_ID 那一台"
    )
    # 整個行程共用同一條路（lru_cache）：再要一次要拿到同一個物件，而且信箱只建過一次
    assert real_get_cloud_route() is route
    assert len(captured) == 1
