"""cloud_ingest 的單元測試：純記憶體，不碰資料庫、不碰網路、**不碰 AWS**。

本檔測的是 Phase 77 的「契約層」：
  - CloudRouteOff：雲端路關掉時的替身（正式路徑目前拿到的就是它）
  - AlwaysRunning：CLOUD_ROUTE=assume 用的探測
  - build_context：要放進 S3 的 context.json 內容
  - FakeMailbox：一顆假件同時扮演 S3 ＋ 兩條佇列（78〜81、87、89 全靠它）
  - 第五道 autouse 安全網 wire_fake_cloud 本身

Phase 79／80 會在本檔追加 CloudRoute 本體的測試；Phase 89 追加 Ec2Probe 的。
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route
from app.main import app
from app.services import cloud_ingest
from app.services.cloud_ingest import (
    ROUTE_OFF_MESSAGE,
    AlwaysRunning,
    CloudRoute,
    CloudRouteOff,
    build_context,
)
from app.services.ingest_job import PromptContext
from app.services.ingest_job_store import InMemoryJobStore
from tests.fakes import FakeMailbox, FakeProbe


def sample_prompt_context() -> PromptContext:
    """一份長得像真的的 PromptContext（Phase 76 的積木回傳的東西）。

    刻意放中文與 None：中文要驗「序列化之後還是中文」（ensure_ascii=False 有生效），
    None 要驗序列化不會炸。
    """
    return PromptContext(
        folders=[
            {
                "id": 1,
                "name": "未分類",
                "description": "收件箱",
                "is_inbox": True,
                "photo_count": 3,
            },
            {
                "id": 2,
                "name": "收據",
                "description": "買東西的憑證",
                "is_inbox": False,
                "photo_count": 0,
            },
        ],
        entities=[{"id": 7, "name": "我的 MacBook", "description": None}],
        corrections=[
            {"suggested": "飲食", "chosen": "收據", "photo_text": "在 Target 買可樂"},
        ],
        inbox_name="未分類",
    )


# ---------------------------- ① 雲端路關掉時的替身 ----------------------------


def test_CloudRouteOff的available恆為False():
    """CLOUD_ROUTE=off 時正式路徑拿到的就是它：永遠說「遠端不可用」。

    這一顆是整個增量六的保險絲：只要它是綠的，`run_gated_ingest_job` 就永遠
    走 fallback（＝增量五那條路），一個位元組都不會出這台機器。
    """
    route = CloudRouteOff()

    assert route.available() is False
    assert route.available() is False  # 問幾次都一樣，沒有「第一次是 True」這種事


def test_CloudRouteOff其餘方法一律raise():
    """關掉的路被拿去送東西＝有人接線接錯了，要大聲壞掉，不要安靜地什麼都不做。

    安靜回 None 的話，Phase 79 之後若有人忘了檢查 available()，
    症狀會變成「照片莫名其妙沒有入庫、也沒有錯誤訊息」——最難查的一種。
    """
    route = CloudRouteOff()

    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        route.submit("job-1", content_type="image/png", file_bytes=b"", context={})
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        route.fetch_result("job-1")
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        route.wait_result("job-1", store=None)
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        route.cleanup("job-1")


def test_AlwaysRunning恆為True():
    """CLOUD_ROUTE=assume 用的探測：不問 AWS，直接說「開著」（總覽 §10 追認項 l）。

    它只給階段丁（工人跑在這台 Mac 上）與除錯用；戊之後日常一律用 Ec2Probe（Phase 89）。
    """
    probe = AlwaysRunning()

    assert probe.is_running() is True
    assert probe.is_running() is True


# ---------------------------- ② context.json 的內容 ----------------------------


def test_build_context恰三鍵而且可以json序列化():
    """工人靠這包東西組出**同一份** build_vlm_prompt（總覽 §10 追認項 a）。

    三鍵不多不少：多了工人不看、少了工人就少一段 prompt。
    inbox_name **刻意不進去**——收件箱名稱是本機落庫時才要用的東西，工人用不到。
    """
    context = build_context(sample_prompt_context())

    assert set(context) == {"folders", "entities", "corrections"}
    assert context["folders"][0]["name"] == "未分類"
    assert context["entities"][0]["name"] == "我的 MacBook"
    assert context["corrections"][0]["chosen"] == "收據"

    # 這一行就是 CloudRoute.submit 真的會做的事（Phase 79）：中文原樣留著
    # （ensure_ascii=False），日期之類不能直接序列化的東西交給 default=str 處理
    text = json.dumps(context, ensure_ascii=False, default=str)
    assert "我的 MacBook" in text
    assert json.loads(text) == context


def test_build_context不含任何位元組():
    """design6 §0 禁止第 2 條的延伸：要送出去的東西**只有字串**，沒有影像。

    這包東西會被 json.dumps 成字串再 PutObject；夾帶一個 bytes 進去會當場炸，
    但更糟的是有人「順手把縮圖 base64 一下放進來」——那就變成偷偷把影像
    塞進本來只該放清單的地方。這顆測試遞迴地把每個角落都翻過一遍。
    """
    context = build_context(sample_prompt_context())

    def walk(value) -> None:
        assert not isinstance(value, (bytes, bytearray)), f"context 裡不可以有位元組：{value!r}"
        if isinstance(value, dict):
            for key, child in value.items():
                assert not isinstance(key, (bytes, bytearray))
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(context)

    # 順帶驗「回的是複本」：改它不可以動到 repository 給的那份原始清單
    original = sample_prompt_context()
    context2 = build_context(original)
    context2["folders"][0]["name"] = "被改掉了"
    assert original.folders[0]["name"] == "未分類"


# ---------------------------- ③ 假信箱：S3 那一半 ----------------------------


def test_FakeMailbox的put與get與delete物件行為():
    """假信箱的 S3 那一半：放得進去、拿得回來、刪得掉、拿不到時回 None。

    「拿不到回 None（不是丟例外）」是契約的一部分（Phase 83 的 AwsMailbox
    也要把 NoSuchKey 翻成 None）——`fetch_result` 靠它分辨「結果還沒寫好」。
    """
    mailbox = FakeMailbox()
    key = mailbox.input_key("job-1", "image/png")

    assert key == "documents/job-1/input.png"
    assert mailbox.input_key("job-1", "image/jpeg") == "documents/job-1/input.jpg"
    assert mailbox.input_key("job-1", "application/pdf") == "documents/job-1/input.pdf"
    assert mailbox.context_key("job-1") == "documents/job-1/context.json"
    assert mailbox.result_key("job-1") == "documents/job-1/result.json"

    assert mailbox.get_object(key) is None
    mailbox.put_object(key, b"PNG-DATA", "image/png")
    assert mailbox.get_object(key) == b"PNG-DATA"
    assert mailbox.put_calls == 1
    assert mailbox.get_calls == 2

    mailbox.delete_objects([key, "documents/job-1/根本沒有這個"])
    assert mailbox.objects == {}
    assert mailbox.delete_calls == 1


def test_FakeMailbox的jobs佇列send後receive再delete():
    """jobs 佇列：本機 Send、工人 Receive／Delete（design6 §2.3）。

    body 恰兩鍵、而且**沒有位元組**——這是 §0 禁止第 2 條在假件層的第一道把關。
    """
    mailbox = FakeMailbox()
    mailbox.send_job("job-1", "documents/job-1/input.jpg")

    assert mailbox.send_job_calls == 1
    assert mailbox.jobs == [{"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}]

    message = mailbox.receive_job(wait_seconds=20)
    assert message is not None
    assert message.job_id == "job-1"
    assert message.s3_key == "documents/job-1/input.jpg"
    assert message.receipt_handle, "沒有把手就刪不掉這則訊息"
    assert mailbox.jobs == [], "收走之後別人就看不到了（模仿 SQS 的可見度逾時）"

    mailbox.delete_job_message(message.receipt_handle)
    assert mailbox.receive_job(wait_seconds=0) is None
    assert mailbox.wait_seconds_log == [20, 0], "每次 receive 等幾秒都記下來，給 Phase 80 驗"
    assert mailbox.calls == [
        "send_job job-1",
        "receive_job",
        "delete_job_message",
        "receive_job",
    ], "呼叫流水帳要照順序記下來（Phase 79／87 靠它釘 D9 的順序鐵律）"


def test_FakeMailbox的results佇列release之後可以再收到():
    """release ＝ ChangeMessageVisibility 改成 0 ＝「我拿錯了，立刻還回去」。

    Phase 80 的 wait_result 收到**別人的**結果訊息時就是這樣處理的：
    還回佇列，讓它真正的主人收得到（總覽 §2.5 第 3 條）。
    """
    mailbox = FakeMailbox()
    mailbox.send_result("別人的job")

    first = mailbox.receive_result(wait_seconds=20)
    assert first is not None
    assert first.job_id == "別人的job"
    assert first.s3_key is None, "results 的 body 只有 job_id（design6 §2.3）"

    mailbox.release_result_message(first.receipt_handle)
    second = mailbox.receive_result(wait_seconds=20)
    assert second is not None
    assert second.job_id == "別人的job"
    assert second.receipt_handle != first.receipt_handle, "把手每次都不一樣（與真 SQS 同）"

    mailbox.delete_result_message(second.receipt_handle)
    assert mailbox.receive_result(wait_seconds=0) is None


def test_FakeMailbox佇列空的時候receive回None():
    """空佇列回 None，不是丟例外——真 SQS 長輪詢到時間也是回一份空清單。

    順帶驗 instance_state 的劇本（Phase 89 的 Ec2Probe 要用它數 DescribeInstances
    被叫了幾次）：依序回傳，用完之後重複最後一個。
    """
    mailbox = FakeMailbox()

    assert mailbox.receive_job(wait_seconds=20) is None
    assert mailbox.receive_result(wait_seconds=20) is None

    assert mailbox.instance_state("i-0000") == "running", "預設劇本就是 running"
    mailbox.instance_state_script = ["stopped", "running"]
    assert mailbox.instance_state("i-0000") == "stopped"
    assert mailbox.instance_state("i-0000") == "running"
    assert mailbox.instance_state("i-0000") == "running", "劇本演完就重複最後一個"
    assert mailbox.instance_state_calls == 4


# ---------------------------- ④ 注入點與第五道安全網 ----------------------------


def test_get_cloud_route預設off時回CloudRouteOff(monkeypatch):
    """CLOUD_ROUTE=off ＝ 不走雲端。這是 pytest 與新 clone 的預設值。

    ★ 這裡呼叫的是**原本那一支**：檔頭的 `from app.dependencies import get_cloud_route`
      在 pytest 收集階段就把函式物件綁進本檔的名字了，第五道安全網之後對
      `dependencies` 模組屬性做的 monkeypatch 換不掉它——這正是我們要的
      （本顆要測的是真的那一支，不是安全網換上去的替身）。
    """
    assert config.CLOUD_ROUTE == "off", "第五道安全網應該已經把它蓋成 off"
    assert isinstance(get_cloud_route(), CloudRouteOff)

    # 打錯字要當場炸，不要默默當成 off——「我明明開了雲端路怎麼都沒送出去」是最難查的
    monkeypatch.setattr(config, "CLOUD_ROUTE", "cloudy")
    with pytest.raises(ValueError):
        get_cloud_route()


def test_第五道安全網把CLOUD_ROUTE蓋成off且AWS_ENDPOINT_URL是死埠():
    """安全網本身也要有測試（比照第四道的 test_安全網已把注入點換成每測獨立的記憶體store）。

    ★ 這一顆**刻意不把 fixture 寫進參數列**：pytest 對「參數列有請求的 fixture」
      無論 autouse 與否都會啟動它，寫了參數列就驗不到 autouse 本身——
      就算有人把 autouse=True 拿掉，這顆照樣綠，形同沒驗。
    """
    assert config.CLOUD_ROUTE == "off"
    assert os.environ["AWS_ENDPOINT_URL"] == "http://127.0.0.1:9", (
        "死埠是最後一道保險：就算有人漏接假件，boto3 也只會立刻 connection refused"
    )

    # 兩條呼叫路都要被換掉（缺一條就是「單跑綠、整包跑紅」的溫床）
    assert get_cloud_route in app.dependency_overrides  # ① Depends() 那條
    assert dependencies.get_cloud_route is not get_cloud_route  # ② 直接呼叫那條
    route = dependencies.get_cloud_route()
    assert isinstance(route, CloudRouteOff)
    assert app.dependency_overrides[get_cloud_route]() is route, "兩條路要拿到同一顆"


# ---------------------------- ⑤ CloudRoute：送出與清理（Phase 79）----------------------------


def make_route(mailbox) -> CloudRoute:
    """真的 CloudRoute ＋ 假信箱 ＋ 「遠端開著」的假探測。"""
    return CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)


def test_submit的順序是先context再input最後jobs():
    """design6 D9 的順序鐵律：**東西先進 S3、才發訊息**。

    反過來的話，工人收到訊息的下一秒就會去 S3 拿檔，拿到的是「還沒寫完」或
    「根本不存在」——而且是**安靜地**壞（拿到半截 JSON，看圖看出一堆奇怪的東西）。
    context 要排在 input 前面則是為了同一個理由再保險一層：工人拿得到圖的那一刻，
    它要用的清單一定已經在了。

    ★ 用 FakeMailbox 的 **calls 流水帳**（總覽 §2.4.5）來驗，不要用 put_calls 這種
      整數計數器——計數器驗得出「幾次」，驗不出「誰先誰後」，而這一條規則要的正是順序。
    """
    mailbox = FakeMailbox()

    make_route(mailbox).submit(
        "job-1",
        content_type="image/png",
        file_bytes=b"PNG",
        context={"folders": []},
    )

    assert mailbox.calls == [
        "put_object documents/job-1/context.json",
        "put_object documents/job-1/input.png",
        "send_job job-1",
    ]


def test_jobs訊息恰兩鍵而且不含位元組():
    """design6 §0 禁止第 2 條、§2.3 的 body 契約、§9 必釘第 7 條。

    SQS 單則上限 1 MiB（2025 年中前是 256 KB），一份多頁 PDF 幾十 MB——位元組走 S3，佇列只放「指路的紙條」。
    """
    mailbox = FakeMailbox()

    # 位元組刻意給多一點，證明「再多也不會跑進訊息裡」
    # （⚠ bytes 字面值只能放 ASCII，所以這裡不要寫中文）
    make_route(mailbox).submit(
        "job-1",
        content_type="image/png",
        file_bytes=b"PNG-DATA" * 5000,
        context={"folders": [], "entities": [], "corrections": []},
    )

    assert len(mailbox.jobs) == 1
    message = mailbox.jobs[0]
    assert set(message) == {"job_id", "s3_key"}
    assert message == {"job_id": "job-1", "s3_key": "documents/job-1/input.png"}
    for value in message.values():
        assert isinstance(value, str), f"body 只准放字串：{value!r}"
    assert "send_job job-1" in mailbox.calls


def test_input鍵名依content_type決定副檔名():
    """S3 上的 input 檔名要看得出格式——工人是靠副檔名推 content_type 的（總覽 §2.6 第 4 條）。"""
    for content_type, extension in (("image/png", ".png"), ("image/jpeg", ".jpg")):
        mailbox = FakeMailbox()

        make_route(mailbox).submit("job-9", content_type=content_type, file_bytes=b"x", context={})

        assert f"documents/job-9/input{extension}" in mailbox.objects
        assert mailbox.jobs[0]["s3_key"] == f"documents/job-9/input{extension}"


def test_cleanup會刪掉三個S3物件():
    """D8：處理完就刪。Lifecycle（2 天）只是掃把，不是主要的清理手段。

    ★ cleanup 拿不到 content_type（簽章只有 job_id），所以它把**三種副檔名**
      的 input 鍵都試著刪一次。多刪不存在的鍵完全無害（真 S3 的 DeleteObjects 也是）。
    """
    mailbox = FakeMailbox()
    mailbox.put_object("documents/job-1/input.png", b"x", "image/png")
    mailbox.put_object("documents/job-1/context.json", b"{}", "application/json")
    mailbox.put_object("documents/job-1/result.json", b"{}", "application/json")
    mailbox.put_object("documents/別人的/input.png", b"x", "image/png")

    make_route(mailbox).cleanup("job-1")

    assert list(mailbox.objects) == ["documents/別人的/input.png"], "只准刪自己的"
    assert mailbox.delete_calls == 1, "一次刪一批，不要一個一個打 API"


# ------------------- ⑥ wait_result 的五條規則（Phase 80）-------------------
#
# 兩支時鐘 helper，語意**相反**，別拿錯：
#   advance_clock_frozen(monkeypatch, seconds)          凍結時鐘——撥到「現在＋秒數」之後就停在那裡不動。
#                                        給「單點判斷」用：問一次 → 撥 61 秒 → 再問一次（Phase 89 的 TTL 快取）。
#   advance_clock_each_call(monkeypatch, step_seconds)   會走的時鐘——每問一次就再過 step_seconds 秒。
#                                        給 wait_result 這種「迴圈到 deadline」的測試用。
# 本 phase 的五顆都會進 wait_result 的迴圈，所以**全部用 advance_clock_each_call**；
# advance_clock_frozen 從 Phase 89 起才有人用，先放在這裡是為了兩支並排、語意一次講清楚
# （tests/unit/test_camera_session_unit.py 的 假裝過了 helper 就是凍結語意——語意要對得上）。


def advance_clock_frozen(monkeypatch, seconds: float) -> None:
    """把時基往前撥。撥完之後所有 _now() 的呼叫都會看到「未來」——而且**停在那裡不動**（凍結）。

    寫法與 tests/unit/test_camera_session_unit.py 的 假裝過了 helper 一致（凍結語意）。
    Phase 89 的 Ec2Probe TTL 測試就是這樣用：問一次 → advance_clock_frozen(monkeypatch, 61) → 再問一次。
    順手把 _sleep 換成不睡：凍結的世界裡沒有人該真的睡。

    ⚠ **不要**拿它來測 wait_result 的逾時：deadline 是進迴圈前用 _now() + timeout_seconds
      算的，時鐘凍結的話「剩下」永遠等於逾時秒數，那個迴圈會**永遠跑不完**。
      會進迴圈的測試一律用下面的 advance_clock_each_call()。
    """
    clock = cloud_ingest._now()
    monkeypatch.setattr(cloud_ingest, "_now", lambda: clock + seconds)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda sec: None)


def advance_clock_each_call(monkeypatch, step_seconds: float = 2.0) -> None:
    """把 cloud_ingest 的兩個時間接縫換掉：**每問一次時鐘，就再過了 step_seconds 秒**；睡覺完全不睡。

    語意講清楚：_now() 第一次被問回「step_seconds」，第二次回「2×step_seconds」……一直往前走。
    wait_result 進迴圈前問一次（算 deadline）、每一圈再問一次（算剩下），
    所以 step_seconds 給得越大，迴圈跑越少圈就到 deadline。

    ⚠ 不接管的話，逾時測試會**真的**跑滿 timeout_seconds 秒，而且是**全速空轉**：
      FakeMailbox 的 receive 是立刻回 None 的（它不會真的等 20 秒），
      所以那個迴圈會用 100% CPU 空轉到 deadline。

    ⚠ 它從 0 起算、不是接著真時鐘走：給 wait_result 用沒問題（deadline 也是用同一支算的），
      但**不可以**拿去測 Ec2Probe 的 TTL——那個快取記的是「上次問」的真時鐘秒數，
      接管之後「過了幾秒」會變成負數，快取永遠不過期（Phase 89 的 TTL 測試用 advance_clock_frozen）。
    """
    clock = {"秒": 0.0}

    def _fake_now() -> float:
        clock["秒"] += step_seconds
        return clock["秒"]

    monkeypatch.setattr(cloud_ingest, "_now", _fake_now)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda sec: None)


def create_job(store: InMemoryJobStore, job_id: str, **fields) -> None:
    """在 store 裡放一筆長得像真的的 job（wait_result 的第 3 條規則會去查它）。"""
    store.create(
        job_id=job_id,
        filename="a.png",
        content_type="image/png",
        ai_backend="local",
        source="upload",
    )
    if fields:
        store.update(job_id, **fields)


def put_three_objects(mailbox: FakeMailbox, job_id: str) -> None:
    """把一筆任務在 S3 上會留下的三個物件都放好。"""
    mailbox.put_object(mailbox.input_key(job_id, "image/png"), b"PNG", "image/png")
    mailbox.put_object(mailbox.context_key(job_id), b"{}", "application/json")
    mailbox.put_object(mailbox.result_key(job_id), b"{}", "application/json")


def test_wait_result每次等待的秒數都不超過20(monkeypatch):
    """規則 1：`receive_result(wait_seconds=min(20, 剩餘秒數))`。

    20 是 **AWS 訂的上限**（WaitTimeSeconds 最大值），超過會被 API 直接拒絕。
    所以「整筆最多等 300 秒」必須自己在外面數 deadline，不能塞給這個參數。

    時鐘每問一次走 3 秒、整筆最多等 30 秒：「剩下」從 27 秒開始、每圈少 3 秒。
    前幾圈要被壓到 20（上限），剩下不到 20 之後要跟著縮短——
    整串實際會是 [20, 20, 20, 18, 15, 12, 9, 6, 3]（第 10 圈剩下 0 ⇒ 逾時回 None）。
    min() 的**兩半**都要驗到：只驗「≤ 20」的話，一個永遠送 20 的實作也會綠。

    下限 1 是 _poll_wait_seconds() 的另一半（不要退化成短輪詢，Phase 79 定的），所以斷言寫 1 <= 秒 <= 20。
    """
    advance_clock_each_call(monkeypatch, 3.0)
    mailbox = FakeMailbox()
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=30)

    assert route.wait_result("我的", store=InMemoryJobStore()) is None, "沒有結果就是 None"
    assert mailbox.wait_seconds_log, "至少要問過佇列一次"
    assert all(1 <= sec <= 20 for sec in mailbox.wait_seconds_log), mailbox.wait_seconds_log
    assert mailbox.wait_seconds_log[0] == 20, "剩下 27 秒時要被壓到上限 20"
    assert any(sec < 20 for sec in mailbox.wait_seconds_log), "快到期時要跟著剩餘秒數縮短"


def test_收到別人的訊息而那筆還在雲端路時把訊息還回去(monkeypatch):
    """規則 3 的前半：那一筆還在等（store 裡有它、而且 route 不是 local）→ **還回去**。

    ⚠ 絕對不可以順手刪掉：刪了的話它的主人會等到逾時、白白 fallback 一次
      （而且工人明明已經把結果算好了）。
    """
    advance_clock_each_call(monkeypatch, 2.0)
    mailbox = FakeMailbox()
    put_three_objects(mailbox, "別人")
    mailbox.send_result("別人")
    store = InMemoryJobStore()
    create_job(store, "別人", route="cloud")
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    assert route.wait_result("我的", store=store) is None, "我的結果沒來，所以是逾時"

    assert mailbox.results == [{"job_id": "別人"}], "別人的訊息要被還回佇列"
    assert "release_result_message" in mailbox.calls
    assert "delete_result_message" not in mailbox.calls, "還在等的訊息一次都不可以刪"
    assert mailbox.result_key("別人") in mailbox.objects, "更不可以刪別人的 S3 物件"


def test_收到別人的訊息而那筆已不在store時刪訊息也刪S3(monkeypatch):
    """規則 3 的後半（情況一）：store 裡查無 → 那一筆早就做完或被 dismiss 了。

    這是**殘訊息**：沒有人在等它。刪掉訊息，順手把它的三個 S3 物件也清乾淨——
    不然那三個檔要躺到 Lifecycle 兩天後才過期，而且下一筆任務每次等結果都會撿到它。
    """
    advance_clock_each_call(monkeypatch, 2.0)
    mailbox = FakeMailbox()
    put_three_objects(mailbox, "早就做完的")
    mailbox.send_result("早就做完的")
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    assert route.wait_result("我的", store=InMemoryJobStore()) is None

    assert mailbox.results == [], "沒有人在等的殘訊息要刪掉"
    assert mailbox.objects == {}, "順手把它的 S3 物件也清乾淨"
    assert "delete_result_message" in mailbox.calls


def test_收到別人的訊息而那筆已改走本機時刪訊息也刪S3(monkeypatch):
    """規則 3 的後半（情況二）：store 裡有它，但 route 已經是 local。

    意思是「那一筆已經放棄雲端、走本機重做了」——工人這時候才把結果送回來，
    一樣是遲到的殘訊息（它的主人根本不會再來收）。
    """
    advance_clock_each_call(monkeypatch, 2.0)
    mailbox = FakeMailbox()
    put_three_objects(mailbox, "已經改走本機的")
    mailbox.send_result("已經改走本機的")
    store = InMemoryJobStore()
    create_job(store, "已經改走本機的", route="local")
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    assert route.wait_result("我的", store=store) is None

    assert mailbox.results == []
    assert mailbox.objects == {}


class ExplodingStore(InMemoryJobStore):
    """get() 一律丟例外的 JobStore（模擬 Redis 半路連不上）。"""

    def get(self, job_id: str):
        raise RuntimeError("Redis 連不上")


def test_處理別人的訊息時store掛掉_例外往外丟(monkeypatch):
    """規則 3 的邊界：`_handle_foreign_message` 要查 store 才知道「別人那筆還在不在」。

    store.get 丟例外時，`wait_result` **不接**——例外一路往外丟到 gated_ingest，
    那裡的 try（裁決 R14）把它當成逾時：cleanup ＋ fallback=local reason=result_timeout。
    行為是**安全**的（照片照樣入庫），代價是「白白放棄這一趟雲端」：
    我們自己的結果可能下一秒就到了，卻因為別人的訊息把整個等待中斷掉。

    這一顆只**釘住現況**（收尾 phase 不改產品行為）。真的要改成「查不到就當作沒人在等」
    要回 Phase 80 改 `_handle_foreign_message`，那是另一個 phase 的事。

    順帶釘兩件事：那則**別人的**訊息既沒被刪、也沒被還回去（真 SQS 要等可見度逾時才會
    再出現），別人的 S3 物件也一個都沒被動到——例外中斷不可以順手毀掉別人的東西。
    """
    advance_clock_each_call(monkeypatch, 2.0)
    mailbox = FakeMailbox()
    put_three_objects(mailbox, "別人")
    mailbox.send_result("別人")
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    with pytest.raises(RuntimeError):
        route.wait_result("我的", store=ExplodingStore())

    assert "delete_result_message" not in mailbox.calls
    assert "release_result_message" not in mailbox.calls
    assert mailbox.result_key("別人") in mailbox.objects


def test_自己的訊息但result_json不在時回None(monkeypatch):
    """規則 2 的後半：工人說「寫好了」，S3 上卻找不到 result.json。

    這不該發生（D9 的順序鐵律是「先 Put 才 Send」），但真的發生時要有明確行為：
    **刪掉訊息**（留著只會變成下一筆的殘訊息）＋ 回 None（＝當逾時處理 → fallback 本機）。

    第一則就是自己的，理論上第一圈就回來；仍然接管時鐘是保險——
    實作寫錯（沒有 return）時，這一顆才會紅而不是卡死。
    """
    advance_clock_each_call(monkeypatch)
    mailbox = FakeMailbox()
    mailbox.send_result("我的")  # 只有訊息，沒有 result.json
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    assert route.wait_result("我的", store=InMemoryJobStore()) is None

    assert mailbox.results == [], "訊息要刪掉"
    assert "delete_result_message" in mailbox.calls


# ---------------- Ec2Probe：問「那台機器開著嗎」（Phase 89）----------------


class ExplodingMailbox:
    """只有 instance_state()，而且一定丟例外——模擬憑證過期／權限不足／網路斷。

    為什麼不用 FakeMailbox：那顆假件的 instance_state_script 是一串**字串**，
    排不出「這一次丟例外」。而這裡要驗的正是「炸了也要回 False，不可以往外丟」。
    只實作被測程式真的會呼叫的那一個方法，就是 stub 的用法。
    """

    def __init__(self) -> None:
        self.instance_state_calls = 0

    def instance_state(self, instance_id: str) -> str:
        self.instance_state_calls += 1
        raise RuntimeError("AWS 憑證過期")


def make_probe(states: list[str], *, instance_id: str = "i-test", ttl_seconds: int = 60):
    """回 (探測物件, 假信箱)。假信箱的 instance_state 會依序回傳 states。"""
    mailbox = FakeMailbox()
    mailbox.instance_state_script = list(states)
    return cloud_ingest.Ec2Probe(mailbox, instance_id, ttl_seconds=ttl_seconds), mailbox


def test_實例狀態running時探測為True():
    """只有 running 才算可用——這是雲端管線唯一的入場券。"""
    probe, mailbox = make_probe(["running"])

    assert probe.is_running() is True
    assert mailbox.instance_state_calls == 1


def test_實例狀態stopped與stopping與pending都是False():
    """design6 §8 第 2 列：EC2 Stop → 本機 run_ingest_job，202 與進度面板不變。

    這裡把六種狀態裡「不是 running」的五種都走一遍：pending 是**開機中**
    （機器還沒準備好收訊息）、stopping 是**關機中**（拿了訊息也做不完）。
    最後多一個 "unknown"：那是 Phase 83 的 AwsMailbox.instance_state() 在
    「查無這台機器」時回的字串（instance id 打錯／機器被 Terminate 超過一小時）。
    每一種都用一顆全新的探測物件，免得被 TTL 快取蓋住。
    """
    for state in ("pending", "stopping", "stopped", "shutting-down", "terminated", "unknown"):
        probe, mailbox = make_probe([state])

        assert probe.is_running() is False, f"{state} 不是 running，不可以送去雲端"
        assert mailbox.instance_state_calls == 1


def test_探測丟例外時回False並留log(caplog):
    """design6 §8 第 3 列：沒有 AWS 憑證 → fallback 本機。

    ⚠ 這裡**絕對不可以**把例外往外丟：往外丟的話 gated_ingest 那一層會炸，
    一張照片會因為「查不到機器狀態」而入不了庫——完全違反 D10
    「不上傳失敗、不要求使用者重傳」。
    """
    caplog.set_level(logging.WARNING)
    mailbox = ExplodingMailbox()
    probe = cloud_ingest.Ec2Probe(mailbox, "i-test", ttl_seconds=60)

    assert probe.is_running() is False
    assert mailbox.instance_state_calls == 1
    assert any("EC2" in message for message in caplog.messages), (
        f"炸掉要留 log，不可以安靜地當作不可用：{caplog.messages}"
    )


def test_探測丟例外時TTL內不會再問一次():
    """失敗的答案**也要進快取**（is_running 的註解一直這樣寫，但沒有東西守著）。

    AWS 真的壞掉（憑證過期、權限被收回、API 掛了）時，這件事不會只發生一秒鐘。
    不快取的話每上傳一張照片就會再去撞一次同一面牆——每張都多一次跨海往返
    （東京來回 50〜200 毫秒，逾時的話是好幾秒），而答案一定還是 False。

    ExplodingMailbox 每被呼叫一次就 +1，所以「第二次仍然是 1」就是快取生效的證據。
    """
    mailbox = ExplodingMailbox()
    probe = cloud_ingest.Ec2Probe(mailbox, "i-test", ttl_seconds=60)

    assert probe.is_running() is False
    assert probe.is_running() is False, "TTL 內應該直接給上一次（失敗）的答案"
    assert mailbox.instance_state_calls == 1, "失敗的答案也要進快取，不可以每張照片都再撞一次牆"


def test_探測的log不印完整的實例ID(caplog):
    """log 只留實例 ID 的**尾 4 碼**（總覽 §7 鐵律 10：repo 是 public）。

    這一行是「探測到底問到什麼」唯一的線索，所以不能不印；但 log 很常被整段貼進
    報告、issue、REP 檔裡，而完整的實例 ID 與 bucket 名、佇列 URL 同一級——
    它本身不是密碼（光有它做不了任何事），卻是「這個帳號有哪些資源」的直接線索。
    尾 4 碼夠用來對照「是不是同一台」，又不會把完整名字散出去。
    """
    caplog.set_level(logging.INFO)
    instance_id = "i-0abcdef1234567890"
    probe, _ = make_probe(["running"], instance_id=instance_id)

    assert probe.is_running() is True
    assert not any(instance_id in line for line in caplog.messages), (
        f"log 不可以出現完整的實例 ID：{caplog.messages}"
    )
    assert any(instance_id[-4:] in line for line in caplog.messages), (
        f"尾 4 碼要留著，不然對不出「探測的是不是同一台」：{caplog.messages}"
    )


def test_TTL內不會再打一次DescribeInstances():
    """D10 第 1 條：快取可短 TTL，避免每張圖都打 AWS。

    劇本第二格是 stopped——如果快取沒生效，第二次就會拿到 False，測試立刻紅。
    """
    probe, mailbox = make_probe(["running", "stopped"], ttl_seconds=60)

    assert probe.is_running() is True
    assert probe.is_running() is True, "TTL 內應該直接給上一次的答案"
    assert mailbox.instance_state_calls == 1, "TTL 內不可以再打一次 DescribeInstances"


def test_TTL過了會再打一次(monkeypatch):
    """快取不是永久的：機器真的被 Stop 了，最多 60 秒之後就要看得到。"""
    probe, mailbox = make_probe(["running", "stopped"], ttl_seconds=60)

    assert probe.is_running() is True
    advance_clock_frozen(monkeypatch, 61)

    assert probe.is_running() is False, "TTL 過了要重新問一次"
    assert mailbox.instance_state_calls == 2


def test_instance_id是空的時候回False而且零呼叫():
    """CLOUD_ROUTE=ec2 卻沒設 EC2_WORKER_INSTANCE_ID ＝ 設定錯誤。

    這時候拿空字串去打 DescribeInstances 只會換來一個看不懂的 AWS 錯誤，
    所以**連問都不要問**：直接當作不可用、留一行 log，照片走本機照樣入庫。
    """
    probe, mailbox = make_probe(["running"], instance_id="")

    assert probe.is_running() is False
    assert mailbox.instance_state_calls == 0, "沒有 instance id 就不該打 AWS"
