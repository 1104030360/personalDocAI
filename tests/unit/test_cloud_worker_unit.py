"""雲端看圖工人的單元測試（Phase 87；design6 D9／D11／D12／D13／D17、總覽 §2.6）。

這一層完全不碰網路、不碰資料庫、不碰 Celery：
信箱是 tests/fakes.py 的 FakeMailbox（一顆假件同時扮演 S3 ＋ 兩條佇列），
看圖是 FakeVLM／ScriptedVLM。所以**本檔跑起來是毫秒等級**，而且**永遠不會**
連到真 AWS（就算第五道安全網漏接，AWS SDK 也只會撞死埠）。

刻意的三條規矩：
1. 訊息一律**從假佇列拿**（send_job → receive_job），不自己 new 一個 MailboxMessage。
   這樣 receipt_handle 是假信箱自己發的，delete_job_message 才對得起來——
   與正式路徑（Phase 88 的主迴圈也是 receive_job 拿的）長得一模一樣。
2. 每一顆會看圖的測試都**同時斷言呼叫次數**（vlm.calls == N）。
   只看 result.json 的內容不夠：「多打了一次模型」是這裡最需要抓的錯。
3. 順序斷言用假信箱的呼叫流水帳 calls（Phase 77 定的格式：方法名＋一個空格＋參數，
   例如 "send_result job-1"）。照步驟 1 印出來的樣子寫，不要自己猜格式。
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import config
from app.services import aws_mailbox as aws_mailbox_module
from app.services import vlm_service
from app.services.ai_timing import AiTarget
from app.services.cloud_ingest import MailboxMessage
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.fakes import FakeMailbox, FakeVLM, ScriptedVLM, make_pdf_bytes, make_png_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RECEIPT_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)

NOT_UNDERSTOOD = PhotoUnderstanding(understood=False)


def queue_one_job(
    mailbox: FakeMailbox,
    job_id: str = "job-1",
    *,
    content_type: str = "image/png",
    payload: bytes | None = None,
    s3_key: str | None = None,
):
    """把「本機送出」那一段用假信箱重演一次，回傳工人收到的那則訊息。

    payload 給 None ＝ 這次刻意不放 input 檔（測「input 不在」那條路）。
    s3_key 給值 ＝ 不用 input_key() 算，直接塞一個怪鍵名（測副檔名認不得那條路）。
    """
    key = s3_key if s3_key is not None else mailbox.input_key(job_id, content_type)
    if payload is not None:
        mailbox.put_object(key, payload, content_type)
    mailbox.send_job(job_id, key)
    message = mailbox.receive_job(0)
    assert message is not None, "假信箱應該要收得到剛剛送進去的那一則"
    return message


def read_result(mailbox: FakeMailbox, job_id: str = "job-1") -> dict:
    """把工人寫進假信箱的 result.json 解回 dict。"""
    raw = mailbox.objects[mailbox.result_key(job_id)]
    return json.loads(raw.decode("utf-8"))


# ---------------- 順序鐵律（design6 D9）----------------


def test_result先PutObject才SendMessage():
    """result.json 一定要先落地，才准發 results 訊息，最後才刪 jobs 訊息。

    反過來的話，本機會被叫醒去拿一個還沒寫完（或根本不存在）的檔案——
    那是最難查的一種壞法：安靜地拿到半截 JSON。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())

    cloud_worker.process_job_message(mailbox, message, FakeVLM(RECEIPT_UNDERSTANDING))

    calls = mailbox.calls
    put_at = calls.index(f"put_object {mailbox.result_key('job-1')}")
    send_at = calls.index("send_result job-1")
    delete_at = calls.index("delete_job_message")
    assert put_at < send_at < delete_at, f"順序不對：{calls}"


# ---------------- 看圖與重試 ----------------


def test_看圖三次都失敗_result標understood_false而且attempts是3():
    """看不懂與呼叫失敗都各算一次，共 config.VLM_MAX_ATTEMPTS 次（design5 D10 的規則沿用）。

    工人**不會**因此叫本機重看一次（總覽 §10 追認項 g）：遠端明明活著，
    只是 AI 看不懂，本機再看三次多半一樣。它照樣把 understood=false 寫出去，
    由本機收到之後標 failed、清 S3。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())
    vlm = ScriptedVLM([NOT_UNDERSTOOD, RuntimeError("雲端 401"), NOT_UNDERSTOOD])

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 3, "上限沒守住"
    result = read_result(mailbox)
    assert result["kind"] == "image"
    assert result["understood"] is False
    assert result["attempts"] == 3
    assert result["understanding"] is None
    # 失敗也照樣走完順序鐵律：不刪訊息的話它每 900 秒就回來一次
    assert mailbox.calls.count("delete_job_message") == 1


def test_一次就成功_attempts是1():
    """看得懂就不再看第二次；九個欄位原樣進 result.json，而且**沒有** embedding。"""
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 1
    result = read_result(mailbox)
    assert result["understood"] is True
    assert result["attempts"] == 1
    assert result["understanding"]["text"] == RECEIPT_UNDERSTANDING.text
    assert result["understanding"]["items"] == ["可樂", "洋芋片"]
    assert result["job_id"] == "job-1"
    assert result["worker_version"] == config.WORKER_VERSION
    # D13：向量一律本機算，工人的產出裡不可以有任何向量
    assert "embedding" not in json.dumps(result)


def test_看圖的計時log帶著vlm物件的backend(caplog):
    """kind=vlm 的計時 log 必須說出**這一顆 VLM 物件**真正打去哪裡（總覽 §2.6 第 5 條）。

    ⚠ 這一顆守的是一行「會騙人的 log」：
      工人行程的 config.AI_BACKEND 永遠是預設的 "local"——頁首那顆本機／雲端開關
      撥的是 web 行程記憶體裡的狀態（design6 D6），這個行程根本讀不到。
      所以呼叫端一旦忘記帶 `target=`，ai_timing 就會退回讀 config，
      log 印出 backend=local ＝ 明明每一張都打去 ollama.com，帳單也在漲，
      log 卻一路說「本機」。**沒有任何東西會壞掉**，只有查帳的人被騙。

    做法：給一顆身上帶著 timing_target 的假 VLM（正式的 OllamaCloudVLM 建構時
    就是這樣把 backend=cloud 與模型名記在自己身上的），斷言那兩個值原樣出現在
    開始行裡。把產品碼的 `target=` 拿掉，這一顆會紅。
    """
    caplog.set_level(logging.INFO)

    class CloudLikeVLM(FakeVLM):
        timing_target = AiTarget(backend="cloud", model="m")

    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())

    cloud_worker.process_job_message(mailbox, message, CloudLikeVLM(RECEIPT_UNDERSTANDING))

    assert "AI 開始 kind=vlm backend=cloud model=m" in caplog.messages, (
        f"計時 log 沒有帶上這顆 vlm 物件的 backend／model：{caplog.messages}"
    )


# ---------------- 冪等（design6 D17）----------------


def test_result已存在時不看圖只補送results並刪jobs訊息():
    """至少送一次：同一則 jobs 訊息可能被送兩次。

    第二次要**完全不看圖**（看圖是要花錢的），也不可以蓋掉已經寫好的 result.json
    ——本機可能正在讀它。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())
    existing_result = b'{"job_id": "job-1", "kind": "image", "understood": true}'
    mailbox.put_object(mailbox.result_key("job-1"), existing_result, "application/json")
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 0, "重送不可以再看一次圖"
    assert mailbox.objects[mailbox.result_key("job-1")] == existing_result, (
        "既有的 result.json 被蓋掉了"
    )
    assert mailbox.calls.count("send_result job-1") == 1, "還是要補送一則 results 叫醒本機"
    assert mailbox.calls.count("delete_job_message") == 1


def test_input不在時只刪jobs訊息什麼都不寫():
    """input 不在了 ＝ 本機已經逾時 fallback、自己看完圖入庫、並把 S3 清乾淨了。

    這時候**寫任何東西都是有害的**：多一份 result.json，下一次重送就會以為
    「有結果可用」而去補送 results，把本機叫醒去處理一張早就入庫的照片。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=None)  # 刻意不放 input
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 0
    assert mailbox.result_key("job-1") not in mailbox.objects, "什麼都不該寫"
    assert mailbox.calls.count("send_result job-1") == 0
    assert mailbox.calls.count("delete_job_message") == 1, "訊息一定要刪，不然每 900 秒回來一次"


# ---------------- context.json ----------------


def test_context缺檔時三份清單都當空的():
    """沒有 context.json 不是失敗：少了資料夾清單只是少了「建議收進哪個資料夾」，
    照片內容照樣看得懂。三份清單都當空的，prompt 照樣組得出來。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())  # 沒有放 context.json
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.last_folders == []
    assert vlm.last_entities == []
    assert vlm.last_corrections == []
    # 有 context.json 時三份清單原樣傳進去這件事，由端到端那兩顆負責驗
    # （tests/integration/test_cloud_roundtrip.py，那裡的 context 是真的從資料庫來的）


def test_context解不開時三份清單都當空的(caplog):
    """檔案在、但內容不是合法 JSON（半截的、不是 UTF-8）→ 三份都當空的，**不是失敗**。

    這條路真的會發生：submit 的順序是 context.json → input → jobs 訊息（Phase 79），
    本機若在寫到一半被強制關掉，S3 上就會留下一個殘缺的物件。
    少了三份清單只是 prompt 少三段，照片內容照樣看得懂——為了它整筆失敗才是真的糟糕。

    ⚠ 但**一定要留 warning**：安靜地當空的話，「工人的 prompt 少了資料夾清單」
      會以「AI 最近都建議未分類」的樣子出現，沒有人會聯想到 context.json。
    """
    caplog.set_level(logging.WARNING)
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=make_png_bytes())
    mailbox.put_object(mailbox.context_key("job-1"), b"{not json", "application/json")
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.last_folders == []
    assert vlm.last_entities == []
    assert vlm.last_corrections == []
    assert any("context.json" in line for line in caplog.messages), (
        f"壞掉的 context.json 要留 warning，不可以安靜地當空的：{caplog.messages}"
    )


def test_context是合法JSON但不是物件時三份清單也當空的(caplog):
    """`[]`／`null`／`"x"` 都是**合法的 JSON**，但它們沒有 `.get()`。

    ⚠ 這是一個會**毒死佇列**的壞法：json.loads 過得了關（所以那個 except 接不到），
      下一行 payload.get(...) 丟 AttributeError → 一路往外丟到主迴圈 →
      那則 jobs 訊息**沒被刪掉** → 900 秒後回來 → 再炸一次，永遠出不去。
      而 read_context 的 docstring 明明寫著「缺檔或內容壞掉 → 三份都當空清單」。

    三種都走一遍：list、None、str——它們是 json.loads 回傳非 dict 的全部形狀
    （數字與布林也是，但這三種已經涵蓋「有 .get 卻不是我們要的」與「根本沒有 .get」）。
    """
    caplog.set_level(logging.WARNING)
    for raw in (b"[]", b"null", b'"x"'):
        mailbox = FakeMailbox()
        message = queue_one_job(mailbox, payload=make_png_bytes())
        mailbox.put_object(mailbox.context_key("job-1"), raw, "application/json")
        vlm = FakeVLM(RECEIPT_UNDERSTANDING)

        cloud_worker.process_job_message(mailbox, message, vlm)

        assert vlm.last_folders == [], f"{raw!r} 應該被當成空清單"
        assert vlm.last_entities == [], f"{raw!r} 應該被當成空清單"
        assert vlm.last_corrections == [], f"{raw!r} 應該被當成空清單"
        # 順帶確認它照樣走完整條路：不寫 result 的話本機會等到逾時才 fallback
        assert mailbox.calls.count("delete_job_message") == 1

    assert any("context.json" in line for line in caplog.messages), (
        f"不是物件的 context.json 也要留 warning：{caplog.messages}"
    )


def test_context值不是list時當空清單不炸(caplog):
    """三個鍵的**值**型別不對（不是缺檔、也不是壞 JSON）——這是第三種壞法。

    ⚠ 為什麼它是真缺口：`{"folders": 5}` 的 json.loads 過得了關、payload 也真的是 dict，
      所以既有那兩顆（解不開／不是物件）都攔不到它。
      加固之前 `list(5 or [])` 會丟 TypeError，一路衝出 process_job_message ->
      jobs 訊息**沒被刪掉** -> 900 秒後回來再炸一次 = 永遠出不去的毒訊息。
      字串與 dict 更陰險：`list("abc")` 會**安靜地**變成三個假資料夾餵進 prompt。

    三種都走一遍，而且順帶確認它照樣走完整條路（有寫 result、有刪 jobs 訊息）。
    """
    caplog.set_level(logging.WARNING)
    for raw in (b'{"folders": 5}', b'{"entities": "abc"}', b'{"corrections": {"a": 1}}'):
        mailbox = FakeMailbox()
        message = queue_one_job(mailbox, payload=make_png_bytes())
        mailbox.put_object(mailbox.context_key("job-1"), raw, "application/json")
        vlm = FakeVLM(RECEIPT_UNDERSTANDING)

        cloud_worker.process_job_message(mailbox, message, vlm)

        assert vlm.last_folders == [], f"{raw!r} 的 folders 應該被當成空清單"
        assert vlm.last_entities == [], f"{raw!r} 的 entities 應該被當成空清單"
        assert vlm.last_corrections == [], f"{raw!r} 的 corrections 應該被當成空清單"
        assert mailbox.calls.count("delete_job_message") == 1, "訊息要被刪掉，不可以變成毒訊息"

    assert any("不是清單" in line for line in caplog.messages), (
        f"型別不對也要留 warning，不可以安靜地當空的：{caplog.messages}"
    )


# ---------------- 從 s3_key 推 content_type ----------------


def test_content_type由s3_key的副檔名推出來():
    """工人只拿得到一個鍵名字串，必須自己還原「這是 JPEG、PNG 還是 PDF」。

    推不出來時**不要亂猜**：把一份 .txt 當成 JPEG 送去看圖，錯誤會在很後面
    才以「AI 看不懂」的樣子出現。認不得就刪掉訊息（留著它只會每 900 秒回來一次）。
    """
    assert cloud_worker.content_type_from_key("documents/a/input.jpg") == "image/jpeg"
    assert cloud_worker.content_type_from_key("documents/a/input.png") == "image/png"
    assert cloud_worker.content_type_from_key("documents/a/input.pdf") == "application/pdf"
    assert cloud_worker.content_type_from_key("documents/a/input.txt") is None
    assert cloud_worker.content_type_from_key("documents/a/input") is None

    # 認不得的鍵名走到 process_job_message：不看圖、不寫東西、只把訊息刪掉
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, payload=b"x", s3_key="documents/job-1/input.txt")
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 0
    assert mailbox.result_key("job-1") not in mailbox.objects
    assert mailbox.calls.count("delete_job_message") == 1


# ---------------- PDF ----------------


def test_PDF拆不開時pages是空清單():
    """壞檔／加密／零頁 → pages 是空清單，**不丟例外**。

    工人照樣把 result.json 寫出去、照樣刪訊息（不然它會一直重送）；
    本機收到空清單之後依既有規則把整筆標成「這份 PDF 讀不開或沒有內容」。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(mailbox, content_type="application/pdf", payload=b"this is not a pdf")
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 0, "拆不開就不該送任何一次模型"
    result = read_result(mailbox)
    assert result["kind"] == "pdf"
    assert result["pages"] == []
    assert mailbox.calls.count("send_result job-1") == 1


def test_PDF每一頁各自最多三次():
    """重試單位是「一頁」，不是整份檔（沿用 design5 D12 的既有語意）。

    第 1 頁一次就過（1 次），第 2 頁三次都失敗（3 次）＝總共 4 次呼叫。
    劇本只寫 4 張卡：多打一次模型就會 AssertionError，這正是我們要抓的錯。
    """
    mailbox = FakeMailbox()
    message = queue_one_job(
        mailbox, content_type="application/pdf", payload=make_pdf_bytes(pages=2)
    )
    vlm = ScriptedVLM(
        [RECEIPT_UNDERSTANDING, NOT_UNDERSTOOD, NOT_UNDERSTOOD, RuntimeError("雲端逾時")]
    )

    cloud_worker.process_job_message(mailbox, message, vlm)

    assert vlm.calls == 4
    result = read_result(mailbox)
    assert result["kind"] == "pdf"
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert result["pages"][0]["understood"] is True
    assert result["pages"][0]["attempts"] == 1
    assert result["pages"][0]["understanding"]["text"] == RECEIPT_UNDERSTANDING.text
    assert result["pages"][1]["understood"] is False
    assert result["pages"][1]["attempts"] == 3
    assert result["pages"][1]["understanding"] is None


# ---------------- 掃碼：工人碰不到的東西 ----------------


def test_工人不import資料庫與Celery與Redis():
    """design6 D11／D13：工人只看圖，不寫 Postgres、不算 embedding、不碰佇列框架。

    用 ast 解析真正的 import 名單，不用 grep——grep 會誤中註解與 docstring。

    ⚠ 黑名單裡**刻意沒有**資料庫驅動程式的套件名：那幾個字母不可以出現在 app/ 底下
      （design3 的 test_SQL只出現在repository與db層 對 app/ 全樹做子字串比對，連註解也算），
      而本檔雖然在 tests/ 掃不到，但寫在這裡遲早會被人抄進工人模組。
      驅動名那一層由那顆既有測試負責，這裡只守「模組層級的相依」。
    """
    source = (PROJECT_ROOT / "app" / "workers" / "cloud_worker.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 記「完整的點分名稱」：from app.services import ai_timing → app.services.ai_timing。
    # 只記 node.module（＝app.services）的話，下面的白名單分不出 ai_timing 與 ingest_job，
    # 而且 app.services 本身不在白名單裡，測試會對著正確的實作一直紅。
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden = (
        "redis",
        "celery",
        "app.db",
        "app.repositories",
        "app.dependencies",  # 它會拉進 JobStore ＝ Redis（工人是獨立行程，沒有那些東西）
        "app.services.ingest_job",  # 本機入庫那一整條（會拉進資料庫層）
        "app.services.staging_service",  # data/staging 是本機的暫存區，EC2 上沒有
    )
    violations = sorted(
        name
        for name in imported
        for prefix in forbidden
        if name == prefix or name.startswith(prefix + ".")
    )
    assert violations == [], f"工人不可以 import 這些：{violations}"

    # 正面表列：工人只准碰這幾個自家模組（總覽 §2.6 最後一行）。
    # 這一段才是真正的防線——黑名單漏列的東西（例如 ingest_job_store）都會被它抓到。
    # cloud_ingest 是型別註記用的（TYPE_CHECKING，執行時不載入）；
    # aws_mailbox 先放進白名單，因為 Phase 88 的 main() 會在函式裡 import 它建真信箱
    # （ast.walk 連函式裡的 import 也看得到，所以現在就要放行）。
    allowed_app_modules = {
        "app.core.config",
        "app.services.ai_timing",
        "app.services.aws_mailbox",
        "app.services.cloud_ingest",
        "app.services.pdf_service",
        "app.services.vlm_service",
    }
    extra = {
        name
        for name in imported
        if name.startswith("app")
        and not any(
            name == allowed or name.startswith(allowed + ".") for allowed in allowed_app_modules
        )
    }
    assert extra == set(), f"工人多 import 了自家模組：{extra}"

    # ★ 相對 import 會**整個繞過**上面兩張表：`from ..services import ingest_job` 的
    #   node.module 是 "services"、node.level 是 2，既對不上黑名單的前綴、
    #   也不以 "app" 開頭——兩個斷言都會微笑放行，而那一行真的會把資料庫層拉進來。
    #   本套件只有一支模組，寫絕對路徑一點都不麻煩，所以直接把這個寫法禁掉，
    #   並且掃**整個 app/workers/**（含 __init__.py，將來多一支工人也自動納入）。
    relative_imports = [
        f"{path.name}:{node.lineno}"
        for path in sorted((PROJECT_ROOT / "app" / "workers").glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.level != 0
    ]
    assert relative_imports == [], (
        f"app/workers/ 底下不准用相對 import（它會繞過上面兩張白／黑名單）：{relative_imports}"
    )


# ---------------- 主迴圈（Phase 88）----------------


class ScriptedMailbox:
    """只提供主迴圈用得到的那一個方法：receive_job()。

    腳本裡每一項可以是三種東西：
      None            → 這一輪長輪詢沒收到東西（佇列空著，這是常態）
      MailboxMessage  → 收到一則
      Exception 的實例 → 這一次 receive 就把它丟出去（模擬憑證過期、網路斷）
    腳本演完之後一律回 None——什麼時候停是 should_stop 決定的，不靠腳本演完。

    為什麼不用 FakeMailbox：那顆假件的 receive_job 是「佇列空了就回 None」，
    排不出「第一次丟例外、第二次才給訊息」這種劇本。而主迴圈要驗的正是那件事。
    """

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.receive_calls = 0
        self.last_wait_seconds: int | None = None

    def receive_job(self, wait_seconds: int):
        self.receive_calls += 1
        self.last_wait_seconds = wait_seconds
        if not self.script:
            return None
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_message(job_id: str = "job-1") -> MailboxMessage:
    """做一則長得跟 SQS 收到的一模一樣的訊息（三個欄位）。"""
    return MailboxMessage(
        job_id=job_id,
        s3_key=f"documents/{job_id}/input.png",
        receipt_handle=f"rh-{job_id}",
    )


def stop_after_rounds(rounds: int):
    """回一個 should_stop：前 N 次**被問到**時回 False（＝再跑一輪），之後永遠 True。

    ⚠ 數的是「被問到幾次」不是「跑了幾圈」：向佇列要訊息失敗那條路會在退避之前
    多問一次（2026-09-03 fix round 1），所以有例外的劇本要多給一次額度。

    正式執行時 should_stop 是訊號旗標；測試用這個，所以整組迴圈測試是毫秒等級，
    不必真的送訊號、也不必等 20 秒的長輪詢。
    """
    remaining = {"rounds": rounds}

    def should_stop() -> bool:
        if remaining["rounds"] <= 0:
            return True
        remaining["rounds"] -= 1
        return False

    return should_stop


def test_主迴圈收到None時繼續等下一則(monkeypatch):
    """佇列空著是**常態**（一天可能只上傳幾張），不可以當成錯誤或直接退出。"""
    processed = []
    monkeypatch.setattr(
        cloud_worker,
        "process_job_message",
        lambda mailbox, message, vlm: processed.append(message),
    )
    mailbox = ScriptedMailbox([None, None, make_message()])

    cloud_worker.run_forever(
        mailbox, FakeVLM(RECEIPT_UNDERSTANDING), should_stop=stop_after_rounds(3)
    )

    assert mailbox.receive_calls == 3, "空手而回時要繼續跑下一圈"
    assert [message.job_id for message in processed] == ["job-1"]
    # 長輪詢：一定要帶 20 秒（AWS 上限）。帶 0 的話會變成短輪詢，一直空轉打 API
    assert mailbox.last_wait_seconds == cloud_worker.LONG_POLL_SECONDS == 20


def test_主迴圈收到訊息就呼叫process_job_message(monkeypatch):
    """迴圈自己不做任何判斷——訊息原封不動、連同信箱與看圖客戶端一起交出去。"""
    received = []
    monkeypatch.setattr(
        cloud_worker,
        "process_job_message",
        lambda mailbox, message, vlm: received.append((mailbox, message, vlm)),
    )
    mailbox = ScriptedMailbox([make_message("job-9")])
    vlm = FakeVLM(RECEIPT_UNDERSTANDING)

    cloud_worker.run_forever(mailbox, vlm, should_stop=stop_after_rounds(1))

    assert len(received) == 1
    passed_mailbox, passed_message, passed_vlm = received[0]
    assert passed_mailbox is mailbox
    assert passed_message.job_id == "job-9"
    assert passed_vlm is vlm, "看圖客戶端要原樣傳進去，不可以在迴圈裡自己建一個"


def test_停止旗標讓主迴圈退出():
    """收到 SIGTERM／Ctrl+C 之後，**下一圈開頭**就要退出——連要訊息都不要再要一次。

    先要了訊息才檢查旗標的話，會多拿一則出來卻沒人做：它會隱形 900 秒才回到佇列，
    看起來就像「有一張照片卡住了十五分鐘」。
    """
    mailbox = ScriptedMailbox([make_message()])

    cloud_worker.run_forever(mailbox, FakeVLM(RECEIPT_UNDERSTANDING), should_stop=lambda: True)

    assert mailbox.receive_calls == 0, "已經被要求停止就不該再去要訊息"


def test_單次例外不會讓主迴圈死掉(monkeypatch, caplog):
    """一則壞掉不可以害死整支工人——那台機器沒有人看著，死了就是整條路默默停擺。

    兩種例外都要活下來：向佇列要訊息時炸掉、處理某一則時炸掉。
    處理失敗的那一則**刻意不刪**，它會在可見度逾時（900 秒）之後自己回來重做。
    """
    caplog.set_level(logging.INFO)
    # backoff 平常是 5 秒，測試裡不要真的睡
    monkeypatch.setattr(cloud_worker, "RECEIVE_ERROR_BACKOFF_SECONDS", 0)
    processed = []

    def exploding_process(mailbox, message, vlm):
        if message.job_id == "job-boom":
            raise RuntimeError("S3 突然不通")
        processed.append(message.job_id)

    monkeypatch.setattr(cloud_worker, "process_job_message", exploding_process)
    mailbox = ScriptedMailbox(
        [RuntimeError("SQS 憑證過期"), make_message("job-boom"), make_message("job-ok")]
    )

    # 4 不是 3：要訊息失敗那條路在退避之前會多問一次 should_stop
    # （2026-09-03 fix round 1），所以三圈的劇本總共會被問四次
    cloud_worker.run_forever(
        mailbox, FakeVLM(RECEIPT_UNDERSTANDING), should_stop=stop_after_rounds(4)
    )

    assert processed == ["job-ok"], "前兩輪都爆了，但迴圈要活著跑到第三輪"
    assert mailbox.receive_calls == 3
    error_records = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(error_records) == 2, "兩次失敗都要留下 log，不可以安靜地吞掉"


def test_啟動時印出version與region與bucket(monkeypatch, caplog):
    """啟動行是**唯一**能證明「EC2 上跑的是哪一版映像」的東西（design6 D16、Demo 3）。

    三個欄位缺一不可：
      version ← WORKER_VERSION（build 時由 ARG GIT_SHA 烙進去，Phase 90）
      region  ← 打錯區的話 S3 與 SQS 會「查無此桶／此佇列」
      bucket  ← 對到別的 bucket 是最難查的一種設定錯
    """
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "WORKER_VERSION", "abc1234")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(config, "S3_BUCKET", "personaldocai-mailbox-test")

    cloud_worker.run_forever(
        ScriptedMailbox([]), FakeVLM(RECEIPT_UNDERSTANDING), should_stop=lambda: True
    )

    startup_lines = [line for line in caplog.messages if line.startswith("cloud_worker 啟動 ")]
    assert len(startup_lines) == 1, f"預期恰好一行啟動 log，實得：{caplog.messages}"
    assert "version=abc1234" in startup_lines[0]
    assert "region=ap-northeast-1" in startup_lines[0]
    assert "bucket=personaldocai-mailbox-test" in startup_lines[0]


class SleepRecorder:
    """替身：把 run_forever 睡了幾秒記下來，而不是真的睡。

    只換掉 cloud_worker 模組裡那個 time 名字（monkeypatch 模組屬性），
    不動真正的 time 模組——所以不會影響到別的測試。
    """

    def __init__(self) -> None:
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_退避期間收到停止旗標就不再要下一則(monkeypatch):
    """向 AWS 要訊息失敗之後會先睡 RECEIVE_ERROR_BACKOFF_SECONDS 秒再試。

    但如果**在睡之前**就已經被要求停止（Ctrl+C 很常正好落在 AWS 不通的這段），
    就不可以還傻傻睡完才退：PEP 475 之後 time.sleep 收到訊號會**續睡**，
    那幾秒是真的會等到的，使用者看到的是「按了 Ctrl+C 卻要多等 5 秒」。
    """
    recorder = SleepRecorder()
    monkeypatch.setattr(cloud_worker, "time", recorder)
    stopping = {"now": False}

    class RaisingMailbox:
        def __init__(self) -> None:
            self.receive_calls = 0

        def receive_job(self, wait_seconds: int):
            self.receive_calls += 1
            # 模擬「向 AWS 要訊息失敗的同一時間，使用者按了 Ctrl+C」
            stopping["now"] = True
            raise RuntimeError("SQS 憑證過期")

    mailbox = RaisingMailbox()

    cloud_worker.run_forever(
        mailbox, FakeVLM(RECEIPT_UNDERSTANDING), should_stop=lambda: stopping["now"]
    )

    assert mailbox.receive_calls == 1, "已經被要求停止就不該再去要下一則"
    assert recorder.slept == [], "已經被要求停止，就不該再睡完整個退避時間"


def test_用python_m跑時啟動失敗訊息帶著app的log前綴():
    """`python -m app.workers.cloud_worker` 的 log 必須真的印得出來。

    這一顆守的是一個安靜到極點的壞法：用 -m 跑時模組的 __name__ 是 "__main__"，
    所以 logging.getLogger(__name__) 拿到的 logger **不在** _configure_logging()
    掛 handler 的 "app" 樹底下——啟動行、「result.json 已放好」、「收到停止訊號」
    全部會被 Python 的 lastResort（只印 WARNING 以上、而且沒有前綴）吞掉，
    工人看起來像整個沒在動（2026-09-02 controller 在真機上實際踩到）。

    驗證方式：真的開一個子行程跑它，但把 S3_BUCKET 設成空字串讓它在
    「檢查設定」那一關就退出（load_dotenv 不覆蓋既有環境變數，所以 .env 進不來）。
    斷言 stderr 有 "ERROR:     " 這個前綴——那是 _configure_logging() 的 Formatter
    才會加的東西，lastResort 印的是裸訊息。兩個死埠只是保險：這條路在任何
    網路呼叫之前就結束了。
    """
    env = {
        **os.environ,
        "S3_BUCKET": "",
        "AWS_ENDPOINT_URL": "http://127.0.0.1:9",
        "OLLAMA_BASE_URL": "http://127.0.0.1:9",
    }

    completed = subprocess.run(
        [sys.executable, "-m", "app.workers.cloud_worker"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 1, (
        f"缺設定應該以退出碼 1 收場；實得 {completed.returncode}\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    assert "ERROR:     cloud_worker 無法啟動" in completed.stderr, (
        "缺設定的訊息要經過 app 那棵 logger 樹（才證明 -m 跑時 handler 真的接得到）；"
        f"實得 stderr={completed.stderr!r}"
    )


# ---------------- 看圖後端 WORKER_VLM_BACKEND（2026-09-03 改判，design6 D12 作廢）----------------
#
# 產品負責人改判：EC2 改成 **GPU 機器自己裝 Ollama** 看圖，所以工人不再寫死 Ollama Cloud。
#   cloud ＝ ollama.com（這台 Mac 手動煙霧的預設）
#   local ＝ **工人所在那台機器**上的 Ollama（GPU EC2 用這個；跟頁首那顆開關無關）
# 這一整組完全不連線：兩個客戶端**建構時都不發請求**（ChatOllama／ollama Client 都是
# 呼叫 chat() 才連），local 那顆再把 base_url 指到死埠當保險。


def configure_worker_aws_settings(monkeypatch) -> None:
    """把 main() 檢查的三個共同設定填上假值（四個值刻意彼此不同）。

    只填 AWS 那三個——看圖那一邊（OLLAMA_*）由每顆測試自己擺，
    因為這一組要驗的正是「哪個後端需要哪一個」。
    """
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-A")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/queue-JOBS")
    monkeypatch.setattr(
        config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/queue-RESULTS"
    )
    monkeypatch.setattr(config, "AWS_REGION", "region-Z")


def test_build_worker_vlm預設是cloud(monkeypatch):
    """預設值（cloud）＝這台 Mac 上手動煙霧走的那條路，行為與 Phase 88 逐字相同。

    假 key 一定要是 **ASCII**：它會被塞進 HTTP 的 Authorization header，
    中文字元會在建 Client 的當下就炸（CLAUDE.md 記過這個坑）。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "cloud")
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")

    vlm = cloud_worker.build_worker_vlm()

    assert isinstance(vlm, vlm_service.OllamaCloudVLM)


def test_build_worker_vlm設成local時回OllamaVLM而且不需要OLLAMA_API_KEY(monkeypatch):
    """GPU EC2 走的那條路：模型在**工人自己那台機器**上，一個字都不必打去 ollama.com。

    所以 OLLAMA_API_KEY 空著也要建得起來——建不起來的話 EC2 上就得為了一把
    根本用不到的 key 而多放一份機密。base_url 指死埠只是保險：建構不連線。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "local")
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "")
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:9")

    vlm = cloud_worker.build_worker_vlm()

    assert isinstance(vlm, vlm_service.OllamaVLM)
    # 計時 log 會照這個值印 backend=local——工人在 GPU 機器上看圖時，帳單不該長在 ollama.com
    assert vlm_service.vlm_timing_target(vlm).backend == "local"


def test_WORKER_VLM_BACKEND打錯字當場炸(monkeypatch):
    """打錯字要**當場**壞掉，不可以默默退回某一種後端。

    悄悄退回 cloud 的話，GPU EC2 會一直打 ollama.com：帳單在漲、GPU 閒著，
    而 log 只會誠實地印 vlm=cloud——沒有任何東西看起來壞掉，所以沒有人會去看。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "gpu")

    with pytest.raises(ValueError):
        cloud_worker.build_worker_vlm()


def test_啟動時印出vlm後端與模型(monkeypatch, caplog):
    """啟動行要說出「這一版工人到底打去哪一顆模型」。

    有了 WORKER_VLM_BACKEND 之後，光看 version／region／bucket 已經不夠：
    同一個映像在 Mac 上跑是 cloud、在 GPU EC2 上跑是 local，而兩者的
    帳單、延遲、失敗樣子完全不同。設定填錯時，這一行是唯一的線索。
    """
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "WORKER_VERSION", "abc1234")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(config, "S3_BUCKET", "personaldocai-mailbox-test")

    class LocalLikeVLM(FakeVLM):
        # model 刻意用一個**這台機器上不存在**的名字：.env 的 VLM_MODEL 剛好也是
        # gemma4:e2b，用它的話「印成 config 值」的錯誤實作會照樣綠。
        timing_target = AiTarget(backend="local", model="model-Z")

    cloud_worker.run_forever(
        ScriptedMailbox([]), LocalLikeVLM(RECEIPT_UNDERSTANDING), should_stop=lambda: True
    )

    startup_lines = [line for line in caplog.messages if line.startswith("cloud_worker 啟動 ")]
    assert len(startup_lines) == 1, f"預期恰好一行啟動 log，實得：{caplog.messages}"
    assert "vlm=local" in startup_lines[0]
    assert "model=model-Z" in startup_lines[0]
    # 既有三個欄位一個都不能少（Phase 88 的那一顆也在守，這裡一起釘住）
    assert "version=abc1234" in startup_lines[0]
    assert "region=ap-northeast-1" in startup_lines[0]
    assert "bucket=personaldocai-mailbox-test" in startup_lines[0]


def test_main在local模式下不因缺OLLAMA_API_KEY而退出(monkeypatch):
    """local 後端不打 ollama.com，所以「少了 OLLAMA_API_KEY」不是缺設定。

    照舊擋著不放的話，GPU EC2 的 worker.env 就得為了一把用不到的 key 才啟動得了
    ——多一份沒有用途的機密躺在那台機器上。

    ★ 三件事都要換掉，否則這顆測試會真的動到這個行程：
      _install_stop_signal 會在 pytest 裡掛上 SIGTERM／SIGINT 處理器；
      AwsMailbox 會建 boto3 client（第五道安全網已把它指到死埠，仍不必去碰）；
      run_forever 會進真的主迴圈。換掉之後順便把「拿到哪一顆 vlm」記下來。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "local")
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "")
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:9")
    configure_worker_aws_settings(monkeypatch)
    monkeypatch.setattr(cloud_worker, "_install_stop_signal", lambda: lambda: True)

    captured: dict = {}

    def fake_aws_mailbox(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", fake_aws_mailbox)

    received: dict = {}

    def fake_run_forever(mailbox, vlm, *, should_stop):
        received["mailbox"] = mailbox
        received["vlm"] = vlm

    monkeypatch.setattr(cloud_worker, "run_forever", fake_run_forever)

    cloud_worker.main()

    assert isinstance(received["vlm"], vlm_service.OllamaVLM), (
        f"local 模式要把工人自己那台機器上的 Ollama 交給主迴圈；實得 {received.get('vlm')!r}"
    )
    assert captured["bucket"] == "bucket-A"


def test_main在cloud模式下缺OLLAMA_API_KEY就退出(monkeypatch):
    """對照組：cloud 後端**真的**要那把 key，缺了就早點、大聲地壞掉。

    不擋的話每一張圖都 401、看三次、然後標成「看不懂」——
    從 log 上看起來像「AI 突然變笨了」，是最難查的一種。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "cloud")
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "")
    configure_worker_aws_settings(monkeypatch)

    called: list = []
    monkeypatch.setattr(
        cloud_worker,
        "run_forever",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(SystemExit):
        cloud_worker.main()

    assert called == [], "缺設定就不該進主迴圈"


def test_WORKER_VLM_BACKEND留空等於cloud(monkeypatch):
    """`WORKER_VLM_BACKEND=`（key 在、值是空字串）也要算「沒填」＝cloud。

    ⚠ 這一顆守的是一個會讓 EC2 永遠起不來的坑：`os.getenv(name, "cloud")` 只在
      **key 完全不存在**時才給預設值；key 在、值是空的時候它回的是 ""。
      而 worker.env.example 裡那一行**就是** `WORKER_VLM_BACKEND=`（範本一律只寫變數名），
      文件也寫「留空或不填＝cloud」。"" 會掉進 main() 的「打錯字」分支 → SystemExit(1)
      → systemd 的 Restart=always 每 10 秒重試一次 → 死循環，而且錯誤訊息會說
      「只認 cloud／local，讀到的是：''」，看起來像設定檔壞了。

    ★ 為什麼用 importlib.reload：要驗的正是「環境變數 → config」那一行，
      monkeypatch.setattr(config, …) 只會蓋掉結果，那一行根本沒被執行到。
      reload 是安全且可逆的——config 只是一堆從環境讀出來的常數，**模組物件本身不變**
      （別的模組手上那個 config 參考仍指著同一顆），finally 再 reload 一次還原。
      DATABASE_URL 由 conftest 在 import app.* 之前就寫進 os.environ，所以 reload
      只會讀回同一個測試庫，不可能誤指正式庫。
    """
    monkeypatch.setenv("WORKER_VLM_BACKEND", "")
    try:
        importlib.reload(config)
        assert config.WORKER_VLM_BACKEND == "cloud"
    finally:
        monkeypatch.delenv("WORKER_VLM_BACKEND", raising=False)
        importlib.reload(config)


def test_AWS_REGION留空等於東京(monkeypatch):
    """`AWS_REGION=`（key 在、值是空字串）也要落到預設的 ap-northeast-1。

    同一個坑的第二個入口：worker.env.example 出貨的那一行就是 `AWS_REGION=`，
    `os.getenv("AWS_REGION", "ap-northeast-1")` 在這種情況回的是 ""，
    boto3 會說查無此區域——而 unit 那一半（ECR 登入）也是用同一個變數，
    兩邊一起壞，錯誤訊息卻都在 aws CLI／boto3 那一層，很難聯想到是 env 檔留空。
    做法與 WORKER_VLM_BACKEND 那顆相同：`or` 收掉空字串，reload 驗的是那一行本身。
    """
    monkeypatch.setenv("AWS_REGION", "")
    try:
        importlib.reload(config)
        assert config.AWS_REGION == "ap-northeast-1"
    finally:
        monkeypatch.delenv("AWS_REGION", raising=False)
        importlib.reload(config)


def test_main在local模式下缺VLM_MODEL會退出(monkeypatch, caplog):
    """local 後端沒有模型名 ＝ 不能開工，要在啟動時就講清楚。

    範本裡 `VLM_MODEL=` 是空的，忘了填的話 ChatOllama(model="") 建得起來、
    也連得上 Ollama，只是每一張圖都失敗——看三次、標成「看不懂」。
    從 log 上看就像「AI 突然變笨了」，是最難查的那一種。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "local")
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(config, "VLM_MODEL", "")
    configure_worker_aws_settings(monkeypatch)

    called: list = []
    monkeypatch.setattr(
        cloud_worker,
        "run_forever",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(SystemExit):
        cloud_worker.main()

    assert any("VLM_MODEL" in message for message in caplog.messages), (
        f"缺設定的訊息要指名是哪一個；實得：{caplog.messages}"
    )
    assert called == [], "缺設定就不該進主迴圈"


def test_main在WORKER_VLM_BACKEND打錯字時退出(monkeypatch, caplog):
    """後端打錯字要在**啟動時**就退出，而且訊息要指名是哪一個設定。

    build_worker_vlm() 也會擋（ValueError），但那要等到組零件那一步，
    訊息會夾在一整段 traceback 裡；EC2 上只看得到 docker logs，越早越好。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "gpu")
    configure_worker_aws_settings(monkeypatch)

    called: list = []
    monkeypatch.setattr(
        cloud_worker,
        "run_forever",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(SystemExit):
        cloud_worker.main()

    assert any("WORKER_VLM_BACKEND" in message for message in caplog.messages), (
        f"訊息要指名是 WORKER_VLM_BACKEND 打錯了；實得：{caplog.messages}"
    )
    assert called == [], "設定不合法就不該進主迴圈"


def test_main在cloud模式下缺OLLAMA_CLOUD_VLM_MODEL會退出(monkeypatch, caplog):
    """cloud 後端的模型名也不能漏——這是 VLM_MODEL 那個坑的雲端版。

    範本出貨的是 `OLLAMA_CLOUD_VLM_MODEL=`（空值），而 config 那一行是
    `os.getenv("OLLAMA_CLOUD_VLM_MODEL", VLM_MODEL)`：key 在、值是空的時候拿到的是 ""，
    **不會**退回 VLM_MODEL。空模型名照樣建得出 OllamaCloudVLM、照樣連得上 ollama.com，
    只是每一張圖都失敗——看三次、標成「看不懂」，log 上像「AI 突然變笨了」。
    """
    monkeypatch.setattr(config, "WORKER_VLM_BACKEND", "cloud")
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(config, "OLLAMA_CLOUD_VLM_MODEL", "")
    configure_worker_aws_settings(monkeypatch)
    monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", lambda **kwargs: object())

    called: list = []
    monkeypatch.setattr(
        cloud_worker,
        "run_forever",
        lambda *args, **kwargs: called.append(args),
    )

    with pytest.raises(SystemExit):
        cloud_worker.main()

    assert any("OLLAMA_CLOUD_VLM_MODEL" in message for message in caplog.messages), (
        f"缺設定的訊息要指名是哪一個；實得：{caplog.messages}"
    )
    assert called == [], "缺設定就不該進主迴圈"
