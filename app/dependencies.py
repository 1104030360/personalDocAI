"""依賴注入點：router 用 Depends(...) 取用；pytest 才用 dependency_overrides 換成假件。

追正式上傳：get_vlm() → OllamaVLM（開關撥到「雲端」時 → OllamaCloudVLM）。
不要在這個檔找 FakeVLM（它在 tests/）。

AI 後端開關（config.AI_BACKEND，2026-08-22）管四個注入點：get_vlm／get_router／
get_answerer／get_entity_suggester——每個都是「本機類別或雲端類別」二選一。
get_embeddings 永遠本機：向量必須跟資料庫裡既有的 bge-m3 向量同源。

design.md §4.2：get_vlm / get_embeddings / get_now 是三個主要注入點；
詢問流程另外需要 get_router / get_answerer / get_today（Phase 11 已補上）；
「再建議一個實體」另有 get_entity_suggester（Phase 30 加入）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache
from typing import Protocol

from fastapi import Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import (
    ask_workflow,
    cloud_ingest,
    entity_suggestion_service,
    indexing_service,
    ingest_job_store,
    privacy_gate,
    vlm_service,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _ollama_vlm() -> vlm_service.OllamaVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線）。"""
    return vlm_service.OllamaVLM()


@lru_cache(maxsize=1)
def _ollama_embeddings() -> Embeddings:
    return indexing_service.build_ollama_embeddings()


@lru_cache(maxsize=1)
def _ollama_cloud_vlm() -> vlm_service.OllamaCloudVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線，與 _ollama_vlm 同理）。"""
    return vlm_service.OllamaCloudVLM()


def build_vlm_for_backend(ai_backend: str) -> vlm_service.VLMClient:
    """依「指定的」後端建看圖物件——**不看** config.AI_BACKEND。

    誰會用它：
    - get_vlm()（下面那個）：web 行程，參數是當下的開關值
    - app/celery_app.py 的 ingest_task：worker 行程，參數是**入列當下寫進 job 的快照**
      （design5.md D14）。worker 讀不到 web 行程的開關，只能靠快照。

    兩條路拿到同兩個物件、同一份 prompt——這一支就是「同一套實作」的保證。
    """
    if ai_backend == "cloud":
        return _ollama_cloud_vlm()
    return _ollama_vlm()


def get_vlm() -> vlm_service.VLMClient:
    """給 router 的看圖物件。跟著頁首的 AI 開關走：本機（預設）或 Ollama Cloud。

    每個請求都當場讀一次 config.AI_BACKEND——開關撥完，下一次上傳立刻生效。

    pytest 若要換成 FakeVLM：app.dependency_overrides[get_vlm] = ...
    那個覆寫只活在測試裡，不影響 uvicorn。
    """
    return build_vlm_for_backend(config.AI_BACKEND)


def get_embeddings() -> Embeddings:
    return _ollama_embeddings()


def get_now() -> datetime | None:
    """『現在時間』。

    正式執行回傳 None，代表上傳時間交給資料庫的 now() 自動記錄。
    測試需要固定時間時，用 dependency_overrides 換成 FixedClock。
    """
    return None


@lru_cache(maxsize=1)
def _ollama_router() -> ask_workflow.OllamaRouter:
    return ask_workflow.OllamaRouter()


@lru_cache(maxsize=1)
def _ollama_answerer() -> ask_workflow.OllamaAnswerer:
    return ask_workflow.OllamaAnswerer()


@lru_cache(maxsize=1)
def _ollama_cloud_router() -> ask_workflow.OllamaCloudRouter:
    return ask_workflow.OllamaCloudRouter()


@lru_cache(maxsize=1)
def _ollama_cloud_answerer() -> ask_workflow.OllamaCloudAnswerer:
    return ask_workflow.OllamaCloudAnswerer()


def get_router() -> ask_workflow.RouterClient:
    """判斷查法的模型。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_router()
    return _ollama_router()


def get_answerer() -> ask_workflow.AnswerClient:
    """產生回答的模型。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_answerer()
    return _ollama_answerer()


@lru_cache(maxsize=1)
def _ollama_entity_suggester() -> entity_suggestion_service.OllamaEntitySuggester:
    """只建立一次（建立物件本身不會連線，與 _ollama_vlm 同理）。"""
    return entity_suggestion_service.OllamaEntitySuggester()


@lru_cache(maxsize=1)
def _ollama_cloud_entity_suggester() -> entity_suggestion_service.OllamaCloudEntitySuggester:
    return entity_suggestion_service.OllamaCloudEntitySuggester()


def get_entity_suggester() -> entity_suggestion_service.EntitySuggesterClient:
    """給「再建議一個實體」端點的物件。跟著 AI 開關走（理由與寫法同 get_vlm）。"""
    if config.AI_BACKEND == "cloud":
        return _ollama_cloud_entity_suggester()
    return _ollama_entity_suggester()


def get_today(now: datetime | None = Depends(get_now)) -> date:
    """詢問當下的日期，供「最近 30 天」使用。

    測試把 get_now 換成固定時間時，這裡也會跟著變成固定日期。
    """
    return now.date() if now is not None else date.today()


# ---------- 隱私閘門（增量六 Phase 74 立契約、75 接真模型；design6.md D2〜D4）----------
#
# 「這張照片能不能離開這台 Mac」由它判斷：同一顆看圖 VLM、另一份短 prompt。
# 還沒有人呼叫 classify()（接線是 Phase 78）。


def build_privacy_gate_for_backend(ai_backend: str) -> privacy_gate.PrivacyGate:
    """依「指定的」後端建隱私閘門——**不看** config.AI_BACKEND。

    誰會用它：
    - get_privacy_gate()（下面那個）：web 行程／pytest，參數是當下的開關值
    - Phase 78 的 app/celery_app.py：worker 行程，參數是**入列當下寫進 job 的快照**
      job["ai_backend"]。worker 行程的 config.AI_BACKEND 永遠是預設的 "local"
      （頁首開關撥的是 web 行程的記憶體狀態，兩個行程不共用），所以這裡若改讀
      config 就會變成「頁首撥雲端、閘門仍打本機」——違反 D6 而且完全不出聲。

    理由與寫法同 build_vlm_for_backend()（design5.md D14 的同一個坑）。

    ⚠ 刻意不加 @lru_cache（不像 _ollama_vlm 那種）：後端是建構參數，
      快取一顆會讓第二次呼叫拿到第一次的後端。ChatOllama 與
      ollama_cloud.build_client() 建物件本身不連線，每次建一顆是可接受的成本。
    """
    return privacy_gate.VlmGate(privacy_gate.OllamaPrivacyModel(backend=ai_backend))


def get_privacy_gate() -> privacy_gate.PrivacyGate:
    """給 Depends 的隱私閘門。跟著頁首的 AI 開關走（理由與寫法同 get_vlm）。"""
    return build_privacy_gate_for_backend(config.AI_BACKEND)


# ---------- 入庫任務的狀態存放處（Phase 57；design5.md §4.3）----------


@lru_cache(maxsize=1)
def _redis_client():
    """整個行程共用一個 Redis 客戶端。

    建立它**不會連線**（redis-py 是第一次真的下命令時才撥號），所以 pytest
    就算不小心走到這裡也不會卡在連線逾時。

    decode_responses=True 一定要有：不加的話 Redis 回來的是 bytes，
    smembers() 拿到 b"abc"，組出來的 key 變成 "ingest:b'abc'"——而且是安靜地錯，
    list_open() 只會永遠回空清單。
    from_url 的 URL 格式：<https://redis.readthedocs.io/en/stable/connections.html>
    """
    import redis

    return redis.Redis.from_url(config.CELERY_BROKER_URL, decode_responses=True)


def get_job_store() -> ingest_job_store.JobStore:
    """入庫任務的進度簿。

    正式：Redis（web 與 worker 兩個行程共用同一份資料）。
    測試：tests/conftest.py 的 wire_memory_job_store 會換成 InMemoryJobStore
    ——pytest 絕不連真 Redis（design5 §9、契約 §7 第 2 條）。
    """
    return ingest_job_store.RedisJobStore(_redis_client())


# ---------------- 入庫任務的入列器（增量五 Phase 62）----------------
#
# 「入列」＝把一個 job_id 丟出去，讓別人去做。誰接住它，Phase 62〜64 與
# Phase 65 之後是不一樣的：
#   Phase 62〜64：NoopDispatcher（沒有人接住——Celery 還沒建，這是**預期**的）
#   Phase 65 起  ：get_task_dispatcher() 本體換成「回傳 app/celery_app.py 的
#                  CeleryDispatcher」，它的 dispatch() 把 job_id 交給
#                  ingest_task.delay()（丟進 Redis，由 worker 容器接住）
# 換的時候只改 get_task_dispatcher() 這一個函式，router 一個字都不動。


class TaskDispatcher(Protocol):
    """把一筆入庫任務丟出去的入列器。介面只有一個具名方法 dispatch()。

    用法：dispatcher.dispatch(job_id)。**不是**把 dispatcher 本身當函式直接呼叫——
    具名方法讓 router 那一行自己會說話；Phase 65 的正式實作 CeleryDispatcher
    （住在 app/celery_app.py，全系統唯一碰 Celery 的地方）與 Phase 65 測試安全網
    的假派工也都有同一個 dispatch() 方法，三邊同形、換裝時誰都不必動。

    參數**只有 job_id**：檔案內容在 data/staging/、其餘欄位在 JobStore，
    佇列裡只放一個字串（design5.md §4.1 明文禁止把影像位元組當任務參數）。
    """

    def dispatch(self, job_id: str) -> None: ...


class NoopDispatcher:
    """什麼都不做的入列器（Phase 62〜64 的正式實作）。

    ⚠ 這代表**照片不會真的入庫**——Celery 要到 Phase 65 才存在。
    刻意不在這裡「就地跑完」（eager）：那會讓 HTTP 回了 202 卻仍然卡住
    2〜5 分鐘等 VLM，比同步的 201 更難懂，也會把真模型的推論
    塞進 uvicorn 的請求執行緒（Phase 48 已踩過會把資料庫壓垮）。

    log 留 INFO 一行：手動測試時看得到「有收下、但沒有人接手」。
    """

    def dispatch(self, job_id: str) -> None:
        logger.info(
            "任務已建立但尚未入列（Phase 65 接上 Celery 之前這是預期行為）：job_id=%s",
            job_id,
        )


def get_task_dispatcher() -> TaskDispatcher:
    """給 router 的入列器。**全系統只有這一個地方碰 Celery。**

    Phase 62〜64 這裡回 NoopDispatcher（沒人接住任務是當時的預期行為）；
    Phase 65 起回 CeleryDispatcher（住在 app/celery_app.py），它的 dispatch(job_id)
    會真的把訊息寫進 Redis。router 只呼叫 dispatcher.dispatch(job_id)，
    完全不知道底下是 Celery——這正是 Phase 62 先立好抽象、本 phase 才換得掉的原因。

    ★ import 寫在函式裡面（不是檔案最上面），兩個理由：
      ① app/celery_app.py 會 import 這個模組（它要拿 get_job_store、
         build_vlm_for_backend、get_embeddings）。這裡若在最上面 import 它，就是循環匯入。
      ② pytest 收集階段不必為了跑一顆前端字串測試就把整個 Celery 拉起來
        （測試一律被 §4.8 的假派工蓋掉，這個函式本體在 pytest 裡根本不會執行）。
    """
    from app.celery_app import CeleryDispatcher

    return CeleryDispatcher()


# ---------------- 增量六 Phase 77：雲端路的注入點（design6 D7／D10）----------------


@lru_cache(maxsize=1)
def _ec2_cloud_route() -> cloud_ingest.CloudRoute:
    """ec2 模式的雲端路，**整個行程只建一次**（手法與 _ollama_vlm 相同）。

    ★ 為什麼一定要共用同一個物件：Ec2Probe 的 TTL 快取是**物件身上的狀態**。
      每次呼叫都 new 一個的話，快取永遠是空的——等於每張照片都打一次
      DescribeInstances，design6 D10 第 1 條要的「避免每張圖都打 AWS」就落空了。
      順便也省下每次重建 boto3 client 的成本（那不是免費的）。

    ★ 代價：改了 .env 之後要重啟 worker 才生效。這與本專案既有的規則一致
      （CLAUDE.md 指令區：「改 .env → restart app worker」）。

    ★ AwsMailbox 的 import 寫在函式**裡面**（與 get_task_dispatcher 同一個理由）：
      pytest 收集階段不必為了一顆字串測試就載入 AWS SDK；
      而且測試可以 monkeypatch aws_mailbox.AwsMailbox 把它整個換掉。
    """
    # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox；與 assume 那支同一句）
    from app.services.aws_mailbox import AwsMailbox

    mailbox = AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )
    # 同一顆信箱同時給 CloudRoute（S3／SQS）與 Ec2Probe（DescribeInstances）用
    return cloud_ingest.CloudRoute(
        mailbox,
        cloud_ingest.Ec2Probe(
            mailbox,
            config.EC2_WORKER_INSTANCE_ID,
            ttl_seconds=config.EC2_PROBE_TTL_SECONDS,
        ),
        timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
    )


def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    """這一台現在要不要走雲端路、怎麼走。**全系統只有這一個地方決定。**

    三種模式由 config.CLOUD_ROUTE 決定（總覽 §2.4.2）：
      off    → CloudRouteOff()：available() 恆為 False，gated_ingest 直接 fallback 成
               run_ingest_job——行為與增量五**逐字相同**（pytest 與新 clone 的預設）
      assume → CloudRoute ＋ AwsMailbox ＋ AlwaysRunning：假設遠端開著、**不做探測**
               （階段丁：工人跑在這台 Mac 上時用；機器沒開時它會傻傻送出、等到逾時才
               fallback，所以不要拿來當日常設定——總覽 §10.1 追認項 l）
      ec2    → CloudRoute ＋ AwsMailbox ＋ Ec2Probe：用 DescribeInstances 問那台機器
               現在是不是 running（戊之後的日常；整個行程共用一條，見 _ec2_cloud_route）

    ★ 打錯字要當場炸（ValueError），不要默默當成 off：
      「我明明把 CLOUD_ROUTE 設成 cloud 了，怎麼都沒送出去」是最難查的一種壞法。
      （Phase 77 的 test_get_cloud_route預設off時回CloudRouteOff 用 CLOUD_ROUTE=cloudy 釘住它。）

    ★ boto3 相關的 import 寫在函式**裡面**（不是檔案最上面），理由與既有的
      get_task_dispatcher() 相同：pytest 收集階段不必為了跑一顆字串測試就載入 boto3，
      而且 CLOUD_ROUTE=off 時根本走不到那一行。

    ★ 三個資源名稱與逾時秒數一律 config.X **即時讀**（不要 from … import X）：
      那樣才改得動（tests 用 monkeypatch 換、.env 改完 restart worker 就生效）。

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    mode = config.CLOUD_ROUTE
    if mode == "off":
        return cloud_ingest.CloudRouteOff()
    if mode == "assume":
        # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox）
        from app.services.aws_mailbox import AwsMailbox

        mailbox = AwsMailbox(
            bucket=config.S3_BUCKET,
            jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
            results_queue_url=config.SQS_RESULTS_QUEUE_URL,
            region=config.AWS_REGION,
        )
        return cloud_ingest.CloudRoute(
            mailbox,
            cloud_ingest.AlwaysRunning(),
            timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
        )
    if mode == "ec2":
        # 整個行程共用一條（lru_cache）：Ec2Probe 的 TTL 快取住在物件身上
        return _ec2_cloud_route()
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{mode!r}")
