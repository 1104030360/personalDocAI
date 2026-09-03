"""雲端路的**本機端**：契約、關掉時的替身，以及要寄給工人的那包清單。

【這個模組解決什麼問題】
增量六要讓「明確不敏感」的照片改去雲端看圖（design6 D7）。本機這一側只做四件事：

    ① 問遠端工人開著沒
    ② 把檔案與 context.json 放進 S3 寄物櫃
    ③ 發一則 jobs 訊息（只放 job_id 與 s3_key，**沒有位元組**）
    ④ 等 results 訊息，再把 result.json 拉回來

這個模組就是那四件事的家。

【這個模組刻意不做什麼】
它**不認識 boto3**——全系統只有 app/services/aws_mailbox.py 認識（Phase 83）。
它只認得兩份契約：CloudMailbox（信箱：S3 ＋ 兩條佇列）與 RemoteProbe（遠端開著沒）。
所以 Phase 78〜81 的每一顆流程測試都可以塞一顆假信箱進來跑，
pytest 從頭到尾不連 AWS（design6 §9、總覽 §7 鐵律 2 與第五道安全網）。

它也**不寫資料庫、不寫檔、不看圖**：拉回來的結果要怎麼落庫是
app/services/gated_ingest.py 的事（Phase 78〜81）。
這一層只管「東西怎麼過去、結果怎麼回來」。

【Phase 79／80 補上的部分】
CloudRoute 本體：available／submit／fetch_result／wait_result／cleanup。
wait_result 的**完整五條規則**（含「收到別人的結果訊息怎麼辦」）在 Phase 80 落地，
規格見計畫總覽 §2.5。Ec2Probe（真的去問 EC2 開著沒）在 Phase 89。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.core import config
from app.services.ingest_job_store import JobStore

if TYPE_CHECKING:
    # 只有型別檢查與讀的人需要，執行時不 import。
    # 這一行如果搬到上面去，本模組就會在 import 當下把 ingest_job → photo_repository
    # → 資料庫驅動程式整條拉進來——而 Phase 87 的雲端工人也會 import 到這個模組，
    # 那台 EC2 上根本沒有資料庫可連（design6 D11：工人不寫 Postgres）。
    # ★ 上一行刻意不寫出那個驅動程式套件的名字：design3 的掃碼測試
    #   test_SQL只出現在repository與db層 是對 app/ 底下每個 .py 做**逐字子字串**比對，
    #   註解裡出現那個字也算違規（Phase 77 §7 陷阱 10）。
    from app.services.ingest_job import PromptContext

logger = logging.getLogger(__name__)

# CloudRouteOff 的四個方法被誤呼叫時丟的訊息。抽成常數是為了讓測試 match 得逐字精準。
ROUTE_OFF_MESSAGE = "雲端路未啟用"

# context.json 放進 S3 時標的型別。S3 會把它記在物件的 metadata 上，
# 之後用瀏覽器或 CLI 看的時候才知道那是一份 JSON（工人不靠它判斷，靠鍵名）。
CONTEXT_CONTENT_TYPE = "application/json"

# 一次長輪詢最多讓 SQS 幫我們等幾秒。**20 是 AWS 訂的上限**，不是我們挑的數字。
# 所以「整筆任務最多等 5 分鐘」必須自己在外面數（deadline），不能靠這一個參數。
MAX_WAIT_SECONDS = 20

# 收到別人的訊息、還回佇列之後先歇一下再繼續，避免變成一個全速空轉的迴圈。
RELEASE_BACKOFF_SECONDS = 1


def _now() -> float:
    """現在的時基（秒）。

    用 time.monotonic()（單調時鐘）：它只會往前走，不受使用者調系統時間或 NTP 校時
    影響——算「過了幾秒」最可靠。包成模組層的一支函式是為了讓測試 monkeypatch 它，
    假裝時間過了很久（寫法沿用 app/services/camera_session_service.py 的 _now()）。

    ★ **這一支之後 Phase 89 的 Ec2Probe 也會用**（它的 TTL 快取要算「上次問是幾秒前」）。
      不要再建第二個時鐘接縫：兩個的話，測試就得記得同時 monkeypatch 兩支，
      而漏掉一支的症狀是「快取的測試偶爾紅」——最難查的那一種。
    """
    return time.monotonic()


def _sleep(seconds: float) -> None:
    """等一下下。同樣包成一支，測試才換得掉（否則逾時測試會真的睡）。"""
    time.sleep(seconds)


def _poll_wait_seconds(remaining: float) -> int:
    """這一次長輪詢要跟 SQS 說「幫我等幾秒」。

    上限 20 是 AWS 訂的；下限 1 是為了不要退化成「短輪詢」——短輪詢會一直空手而回，
    把 API 呼叫次數（也就是錢）浪費掉。剩下不到 1 秒時仍然送 1，
    多等的那一點點由外層的 deadline 收掉。
    """
    return max(1, min(MAX_WAIT_SECONDS, int(remaining)))


def _parse_result(raw: bytes, job_id: str) -> dict | None:
    """把 result.json 的位元組變成 dict；壞掉一律回 None（＝當作沒有結果）。

    為什麼要這麼小心：工人與本機是**兩支不同的程式**（EC2 上跑的可能是舊一點的映像），
    半截的 JSON、被截斷的檔、不是物件的 JSON 都有可能。
    回 None 的下場是 fallback 本機——比讓一個奇怪的 dict 流進落庫段安全得多。
    """
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        logger.warning("job %s 的 result.json 解析不了，當作沒有結果", job_id, exc_info=True)
        return None
    if not isinstance(result, dict):
        logger.warning("job %s 的 result.json 不是一個物件，當作沒有結果", job_id)
        return None
    return result


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    """從佇列拿回來的一則訊息。**只有字串，沒有位元組**（design6 §0 禁止第 2 條）。

      job_id         這則訊息在講哪一筆任務
      s3_key         jobs 訊息才有（input 檔在 S3 的名字）；results 訊息一律是 None
      receipt_handle SQS 給的**臨時**把手。要刪掉這則訊息、或要提早把它還回佇列，
                     都得用它。它不是 message id，每次收到同一則訊息時都不一樣。

    ★ 為什麼定義在這裡、而不是在 aws_mailbox.py：它是 CloudMailbox 這份**契約**的
      一部分（receive_result() 的回傳型別）。定義在 boto3 那一側的話，
      「只想用假信箱跑流程」的測試也得先 import boto3——第五道安全網就白做了。
      Phase 83 的 AwsMailbox 直接 `from app.services.cloud_ingest import MailboxMessage`
      用同一個類別，全系統只有這一個定義。
    """

    job_id: str
    s3_key: str | None
    receipt_handle: str


class CloudMailbox(Protocol):
    """寄物櫃（S3）＋兩條佇列（SQS）的契約（design6 §2.2、§2.3）。

    Protocol ＝「只要你有這些方法，你就算是一個信箱」，**不必繼承任何東西**
    （本專案的 JobStore／VLMClient／TaskDispatcher 都是這樣寫的）。
    兩個實作：正式的 AwsMailbox（Phase 83）與測試的 FakeMailbox（tests/fakes.py）。

    ⚠ Protocol 只是給編輯器與人看的規格，**執行時不會幫你檢查**。
      少寫一個方法不會在 import 時爆錯，會在真的呼叫到時才 AttributeError。

    鍵名三支（input_key／context_key／result_key）刻意放在信箱身上，
    不寫成模組層的函式：鍵名是「S3 那一側的事」，兩個實作各自負責，
    呼叫端（CloudRoute）從頭到尾不必知道 `documents/` 這個前綴長什麼樣。

    ★ 這一份契約**同時涵蓋本機端與工人端**（總覽 §2.4.1）：
      本機用 send_job／receive_result／delete_result_message／release_result_message，
      工人用 receive_job／delete_job_message／send_result，
      兩邊共用 put_object／get_object／三支鍵名；instance_state 只有 Phase 89 的
      Ec2Probe 會用到。合成一份的好處是 FakeMailbox 只要一顆，
      Phase 87 才寫得出「本機送出 → 工人處理**同一顆信箱** → 本機收回入庫」的端到端測試。
    """

    def put_object(self, key: str, body: bytes, content_type: str) -> None: ...

    def get_object(self, key: str) -> bytes | None: ...

    def delete_objects(self, keys: list[str]) -> None: ...

    def send_job(self, job_id: str, s3_key: str) -> None: ...

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None: ...

    def delete_job_message(self, receipt_handle: str) -> None: ...

    def send_result(self, job_id: str) -> None: ...

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None: ...

    def delete_result_message(self, receipt_handle: str) -> None: ...

    def release_result_message(self, receipt_handle: str) -> None: ...

    def input_key(self, job_id: str, content_type: str) -> str: ...

    def context_key(self, job_id: str) -> str: ...

    def result_key(self, job_id: str) -> str: ...

    def instance_state(self, instance_id: str) -> str: ...


class RemoteProbe(Protocol):
    """「遠端工人現在開著嗎」的契約。

    實作只有兩個：AlwaysRunning（下面，assume 模式用）與 Ec2Probe（Phase 89）。
    ★ 實作**自己要吞掉例外**：答不出來就回 False。
      「問不到答案」與「沒開機」對這個系統來說是同一件事——都走 fallback 本機
      （design6 §2.1 第 2 條）。
    """

    def is_running(self) -> bool: ...


class AlwaysRunning:
    """永遠回答「開著」的探測（CLOUD_ROUTE=assume 用；總覽 §10 追認項 l）。

    它只給階段丁（工人跑在這台 Mac 上）與除錯用。
    ⚠ 日常一定要用 ec2 模式：assume 不做任何探測，機器關著時它會傻傻地把檔案送出去，
      然後等到逾時（預設 5 分鐘）才 fallback——白白多等 5 分鐘。
    """

    def is_running(self) -> bool:
        return True


class Ec2Probe:
    """問 AWS「那台工人機器現在開著嗎」，答案快取 ttl_seconds 秒。

    為什麼要快取（design6 D10 第 1 條「快取可短 TTL，避免每張圖都打 AWS」）：
    每上傳一張非敏感照片就要探測一次。DescribeInstances 本身不收費，
    但它是一次跨海的網路往返（東京來回約 50〜200 毫秒），而且有 API 速率限制。
    EC2 從 stopped 變成 running 本來就要一分鐘上下，所以 60 秒內問一次就夠了。

    ★ 快取活在**這個物件身上**。要讓它跨照片生效，整個行程必須共用同一個
      Ec2Probe——所以 dependencies._ec2_cloud_route() 加了 lru_cache（見那裡的說明）。

    ★ 任何例外都當成「不可用」（design6 §8 錯誤表第 3 列）：沒有 AWS 憑證、
      API 掛了、instance id 打錯……全部回 False，讓 gated_ingest 走 fallback。
      **絕對不可以往外丟**——那會讓一張照片因為「查不到機器狀態」而入不了庫，
      直接違反 D10「不上傳失敗、不要求使用者重傳」。

    ★ 它**不會**幫你把機器開起來。design6 §1.2 第 9 列已否決「常開 EC2」，
      D15 是「用完就 Stop」；而且開機要一分鐘上下，那張照片還是得等——
      不如直接走本機（本來就比較快）。
    """

    def __init__(self, mailbox: CloudMailbox, instance_id: str, *, ttl_seconds: int) -> None:
        self._mailbox = mailbox
        self._instance_id = instance_id
        self._ttl_seconds = ttl_seconds
        self._cached: bool | None = None  # None ＝ 還沒問過
        self._cached_at = 0.0

    def is_running(self) -> bool:
        """現在能不能把照片送去雲端。只有狀態是 "running" 才回 True。"""
        if not self._instance_id:
            # CLOUD_ROUTE=ec2 卻沒設 EC2_WORKER_INSTANCE_ID：這是設定錯誤，
            # 但不可以讓照片入不了庫。回 False 走 fallback，並且大聲留 log。
            # 拿空字串去打 DescribeInstances 只會換來一個看不懂的 AWS 錯誤，
            # 所以**連問都不要問**。
            logger.warning("沒有設定 EC2_WORKER_INSTANCE_ID，EC2 一律當作不可用")
            return False

        now = _now()
        if self._cached is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached

        try:
            state = self._mailbox.instance_state(self._instance_id)
        except Exception:
            # 憑證過期、權限不足、網路不通……全部當成「不可用」。
            # 失敗的答案**也要進快取**：AWS 壞掉時不該每張照片都再去撞一次牆。
            logger.warning("查不到 EC2 狀態，當作遠端不可用", exc_info=True)
            return self._remember(False, now)

        # ★ 只印**尾 4 碼**（總覽 §7 鐵律 10：這個 repo 是 public，而 log 很常被
        #   整段貼進報告與 issue）。實例 ID 本身不是密碼，但它跟 bucket 名、佇列 URL
        #   同一級——是「這個帳號有哪些資源」的直接線索。尾 4 碼足夠對照
        #   「探測的是不是同一台」，這也是這一行 log 唯一的用途。
        logger.info("EC2 探測：instance=…%s state=%s", self._instance_id[-4:], state)
        return self._remember(state == "running", now)

    def _remember(self, available: bool, now: float) -> bool:
        """把答案存進快取並回傳它（成功與失敗都存，理由見 is_running 的註解）。"""
        self._cached = available
        self._cached_at = now
        return available


class CloudRoute:
    """本機端的雲端路：把一筆任務寄出去、等結果、收尾（design6 §2）。

    三個零件：
      mailbox         寄物櫃與兩條佇列（正式是 AwsMailbox，測試是 FakeMailbox）
      probe           遠端開著沒（assume 模式是 AlwaysRunning、ec2 模式是 Ec2Probe）
      timeout_seconds 送出之後最多等幾秒（config.CLOUD_RESULT_TIMEOUT_SECONDS）

    ★ 它**不碰資料庫、不寫檔、不看圖**：拉回來的 result.json 要怎麼落庫是
      gated_ingest 的事。這一層只管「東西怎麼過去、結果怎麼回來」。
    """

    def __init__(self, mailbox: CloudMailbox, probe: RemoteProbe, *, timeout_seconds: int) -> None:
        self._mailbox = mailbox
        self._probe = probe
        self._timeout_seconds = timeout_seconds

    def available(self) -> bool:
        """遠端現在能用嗎。**問不出來（例外）一律當作不能用**（design6 §2.1 第 2 條）。

        這裡再吞一次例外是刻意的「雙保險」：gated_ingest 那一層也吞
        （`_remote_available`），因為 available() 的實作是可以被抽換的，
        而「探測炸掉 ⇒ 整筆任務失敗」是絕對不能發生的事（§0 禁止第 6 條）。
        """
        try:
            return self._probe.is_running()
        except Exception:
            logger.warning("問遠端狀態時出錯，一律當作不可用", exc_info=True)
            return False

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        """把這一筆寄出去。順序是鐵律：**先 context、再 input、最後才發訊息**。

        為什麼順序不能換（design6 D9）：工人收到 jobs 訊息的下一秒就會去 S3 拿檔。
        訊息先發的話，它會拿到「還沒寫完」或「根本不存在」的東西——
        而且是**安靜地**壞（拿到半截 JSON，看圖看出一堆奇怪的東西）。

        任何一步失敗就把例外往外丟：呼叫端（gated_ingest）接到之後會 cleanup
        盡力刪掉半套的東西，然後 fallback 本機（design6 §2.1 第 3 條）。
        """
        context_bytes = json.dumps(context, ensure_ascii=False, default=str).encode("utf-8")
        self._mailbox.put_object(
            self._mailbox.context_key(job_id), context_bytes, CONTEXT_CONTENT_TYPE
        )

        input_key = self._mailbox.input_key(job_id, content_type)
        self._mailbox.put_object(input_key, file_bytes, content_type)

        self._mailbox.send_job(job_id, input_key)
        logger.info("job %s 已送去雲端：%s", job_id, input_key)

    def fetch_result(self, job_id: str) -> dict | None:
        """直接去 S3 看看結果在不在（**只在崩潰重送時**用；Phase 80 接上呼叫端）。

        ⚠ 這**不是**輪詢：正常流程的完成訊號永遠是 results 佇列的那一則訊息（D9），
          design6 §1.2 已經否決過「本機輪詢 HeadObject 當完成訊號」（方案 A）。
          這一支只在「佇列把同一個任務再送一次」時問**一次**，用來避免叫工人白做。
        """
        raw = self._mailbox.get_object(self._mailbox.result_key(job_id))
        if raw is None:
            return None
        return _parse_result(raw, job_id)

    def wait_result(self, job_id: str, *, store: JobStore) -> dict | None:
        """在 results 佇列上等**這一筆**的完成訊號，最多等 timeout_seconds 秒。

        回傳 result.json 的內容；逾時、或「訊息說好了但檔案不在」→ None
        （呼叫端把 None 當成「這條路走不通」→ fallback 本機）。

        五條規則（總覽 §2.5，Phase 80 完整落地）：

          1. 迴圈到 deadline 為止（deadline ＝ 進迴圈前的 _now() ＋ timeout_seconds，
             而 timeout_seconds 來自 config.CLOUD_RESULT_TIMEOUT_SECONDS，預設 300 秒），
             每次 receive_result(wait_seconds=min(20, 剩餘秒數))——換算在 _poll_wait_seconds() 裡，
             它另有下限 1（剩不到 1 秒仍送 1，免得退化成短輪詢）
          2. 收到的 job_id **是我的**：去 S3 拿 result.json；
             有 → 解析、刪訊息、回傳；沒有 → 刪訊息、回 None（當逾時 → fallback）
          3. 收到的是**別人的**：見 _handle_foreign_message()
          4. deadline 到了仍然沒有 → 回 None
          5. 每則訊息只解析 job_id，**不含任何位元組**（design6 §0 禁止第 2 條）

        ★ store 是規則 3 要用的：它得查「別人那一筆現在還在不在、走的是哪條路」。
        """
        deadline = _now() + self._timeout_seconds
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                # 規則 4：等到期限了。回 None ⇒ 呼叫端 cleanup ＋ fallback 本機（D10）
                logger.warning("job %s 等雲端結果逾時（%d 秒）", job_id, self._timeout_seconds)
                return None

            message = self._mailbox.receive_result(_poll_wait_seconds(remaining))
            if message is None:
                continue  # 長輪詢等滿了還是沒訊息，再等下一輪（deadline 會收掉）

            if message.job_id == job_id:
                return self._collect_own_result(message, job_id)

            self._handle_foreign_message(message, store=store)

    def cleanup(self, job_id: str) -> None:
        """盡力把這一筆在 S3 留下的東西刪光（design6 §2.1「盡力刪物件」、D8）。

        刪三種鍵：input（**三種副檔名都試一次**，因為這裡拿不到 content_type）、
        context.json、result.json。多刪不存在的鍵完全無害（真 S3 的 DeleteObjects 也是）。

        刪不掉只 log、不往外丟：cleanup 永遠是「善後」，
        不可以讓善後失敗蓋掉真正的錯誤（呼叫它的地方通常正在處理另一個失敗）。
        """
        keys = [self._mailbox.input_key(job_id, ct) for ct in sorted(config.ALLOWED_CONTENT_TYPES)]
        keys.append(self._mailbox.context_key(job_id))
        keys.append(self._mailbox.result_key(job_id))
        try:
            self._mailbox.delete_objects(keys)
        except Exception:
            logger.warning("job %s 清 S3 物件時出錯，略過", job_id, exc_info=True)

    def _collect_own_result(self, message: MailboxMessage, job_id: str) -> dict | None:
        """訊息是我的：去 S3 把 result.json 拿回來，然後把訊息刪掉。

        ★ 就算檔案不在也要**先刪訊息**：那則訊息已經沒有用了，留著只會在可見度逾時後
          再冒出來一次、被下一筆任務收到（總覽 §8.9 的殘訊息問題）。
          檔案不在時回 None ＝ 當成逾時處理 ＝ fallback 本機（總覽 §2.5 第 2 條）。
        """
        raw = self._mailbox.get_object(self._mailbox.result_key(job_id))
        self._mailbox.delete_result_message(message.receipt_handle)
        if raw is None:
            logger.warning("job %s：收到完成訊號，但 S3 上找不到 result.json", job_id)
            return None
        return _parse_result(raw, job_id)

    def _handle_foreign_message(self, message: MailboxMessage, *, store: JobStore) -> None:
        """規則 3：results 佇列是**共用的**，兩筆同時在等時一定會收到對方的訊息（總覽 §8.9）。

        兩種情況，處理方式完全相反：

          ① 那一筆**還在雲端路等**（store 裡有它，而且 route 不是 "local"——
             總覽 §2.5 第 3 條的「否則」，逐字對齊）
             → 立刻還回佇列（可見度改 0），讓它的主人收得到。
               ⚠ 絕對不可以順手刪掉：刪了它的主人會等到逾時、白白 fallback 一次。

          ② 那一筆**已經沒有人在等**（store 裡查無 ＝ 早就做完或被 dismiss；
             或 route 已經是 "local" ＝ 那一筆已經 fallback 了）
             → 這是**遲到的殘訊息**：刪掉訊息，順手把它的 S3 物件也清乾淨。
               不清的話那三個檔要躺到 Lifecycle 兩天後才過期，而且下一筆任務
               每次等結果都會撿到同一則沒用的訊息。

        還回去之後 _sleep 一下下（RELEASE_BACKOFF_SECONDS）：不歇的話，
        「只有別人的訊息」那段時間會變成一個全速空轉的迴圈。
        """
        other_job = store.get(message.job_id)
        still_waiting = other_job is not None and other_job.get("route") != "local"
        if still_waiting:
            self._mailbox.release_result_message(message.receipt_handle)
            _sleep(RELEASE_BACKOFF_SECONDS)
            return

        logger.info("收到沒有人在等的結果訊息（job %s），順手清掉", message.job_id)
        self._mailbox.delete_result_message(message.receipt_handle)
        self.cleanup(message.job_id)


class CloudRouteOff:
    """雲端路關掉時的替身（CLOUD_ROUTE=off——pytest 與新 clone 的預設）。

    它就是「增量六在正式路徑上的保險絲」：available() 恆為 False，
    所以 run_gated_ingest_job（Phase 78）永遠走 fallback ＝ 增量五那條路，
    **一個位元組都不會出這台機器**。

    其餘四個方法一律丟 RuntimeError 而不是安靜地回 None：
    走到那裡代表有人接線接錯了（沒有先問 available() 就送）。
    安靜回 None 的症狀會是「照片莫名其妙沒入庫、也沒有任何錯誤訊息」——最難查的一種。
    """

    def available(self) -> bool:
        return False

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def fetch_result(self, job_id: str) -> dict | None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def wait_result(self, job_id: str, *, store: JobStore) -> dict | None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def cleanup(self, job_id: str) -> None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)


def build_context(prompt_context: PromptContext) -> dict:
    """組出 context.json 的內容：資料夾、實體、糾錯三份清單（總覽 §10 追認項 a）。

    工人拿到它才組得出**同一份** build_vlm_prompt(folders, entities, corrections)——
    那三份清單全都住在這台 Mac 的資料庫裡，工人自己生不出來。
    缺了它工人也不會失敗，只是少了資料夾建議與糾錯 few-shot（照樣看得懂圖）。

    為什麼放 S3 不放 SQS：SQS 的 body 契約只有 job_id 與 s3_key（design6 §2.3），
    而且單則上限只有 1 MiB（2025 年中前是 256 KB），資料夾與實體多起來遲早會超過。

    ★ inbox_name **不放進去**：收件箱名稱是本機落庫時才要用的東西（照片一律先進收件箱），
      工人只負責看圖，用不到。契約恰三鍵，多一鍵少一鍵都會讓兩邊對不起來。

    ★ 每一筆都重新 dict() 一次：回的是**乾淨的複本**，呼叫端改它不會動到
      repository 給的那份資料（那份等一下 run_ingest_job fallback 時還要用）。
    """
    return {
        "folders": [dict(folder) for folder in prompt_context.folders],
        "entities": [dict(entity) for entity in prompt_context.entities],
        "corrections": [dict(correction) for correction in prompt_context.corrections],
    }
