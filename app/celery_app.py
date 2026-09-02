"""Celery 的進入點（增量五 design5.md D5／D15；契約 §3.5）。

worker 用這一支啟動：

    celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=2

那串 `-A`（＝ `--app`）要怎麼讀：
    app.celery_app          ← Python 模組路徑，也就是這個檔案（app/celery_app.py）
                .celery_app ← 這個模組裡那個變數的名字（下面 celery_app = Celery(...)）
官方文件寫的正式格式是 module.path:attribute（冒號版）；點號版等價、兩種都收。
只寫 `-A app.celery_app`（不指名變數）通常也動得了——官方的搜尋順序是：
屬性 app → 屬性 celery → 「模組裡任何值是 Celery 實例的屬性」，第三步會撈到 celery_app。
但那是靠搜尋：哪天這個檔多出第二個 Celery 物件（或變數改名）就挑不準；
把變數名寫全＝完全不靠搜尋。（搜尋全部落空時的錯誤長相：
Unable to load celery application. Module 'app.celery_app' has no attribute 'app'。）
<https://docs.celeryq.dev/en/stable/getting-started/next-steps.html>
<https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html>

★ 本檔刻意寫得很薄（design5.md D15）：所有規則（VLM 重試 3 次、PDF 逐頁、
  失敗清乾淨、冪等）都在入庫任務裡，這裡只負責「把零件組好、呼叫它」。
  所以測試可以直接呼叫那一支函式，不必啟動 Celery、不必有 Redis。

★ 增量六（Phase 78）起，呼叫的對象換成 app/services/gated_ingest.py 的
  run_gated_ingest_job：它會先問隱私閘門、再問遠端狀態，然後決定這一筆走
  本機（＝既有的 run_ingest_job，行為與增量五逐字相同）還是雲端（design6 D5）。
  本檔仍然只負責「組零件」——多組兩個而已（gate 與 cloud）。
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready

from app import dependencies
from app.core import config
from app.services import gated_ingest, staging_service

logger = logging.getLogger(__name__)

# 第一個參數是「這個 app 的名字」，會出現在 worker 的啟動畫面與 log 裡。
# backend=None ＝**不要 result backend**（design5.md §4.3）：
#   result backend 是 Celery 存「任務回傳值」的地方。我們的任務回傳 None，
#   進度狀態全部走自己的 JobStore（前端 GET /ingest-jobs 讀的就是它），
#   開了它只會為每顆任務多寫一筆永遠沒人看的「墓碑」。
#   官方設定表也寫得很清楚：result_backend 預設就是「沒有」
#  （原文 "Default: No result backend enabled by default."）。
#   <https://docs.celeryq.dev/en/stable/userguide/configuration.html>
# （契約 §3.5 的範例寫 settings.CELERY_BROKER_URL——那是通稱；本專案的設定模組
#   叫 config（app/core/config.py），常數名相同。不要真的去建一個 settings 模組。）
celery_app = Celery("personaldocai", broker=config.CELERY_BROKER_URL, backend=None)

# broker 一時連不上時，啟動階段要不要重試。官方設定表列的預設是 Enabled，
# 但某些 5.x 版本啟動時會為了 6.0 的行為變更印一段提醒——明寫這一行就不會再唸。
celery_app.conf.broker_connection_retry_on_startup = True


@celery_app.task(name="personaldocai.ingest")
def ingest_task(job_id: str) -> None:
    """worker 真正執行的東西——薄薄一層 wrapper（design5.md D15）。

    只做四件事：撈 job、依快照組零件、呼叫 run_gated_ingest_job、結束。

    ★ 為什麼 vlm 用 job["ai_backend"] 而不是 dependencies.get_vlm()：
      頁首開關改的是 **web 行程**記憶體裡的 config.AI_BACKEND；worker 是另一個行程，
      它那份永遠是預設的 "local"。入列當下已經把當時的值抄進 job（D14），用抄本才對。

    ★ 為什麼 embeddings 直接用 get_embeddings()：向量**永遠本機**、不歸開關管
      ——庫裡既有的向量都是本機 bge-m3 算的，換一顆就比不出東西。

    ★ 這裡**沒有** Celery 的 autoretry（design5.md §4.4）：「同一張圖最多送 VLM 3 次」
      是入庫任務**內部**的迴圈。在這一層再加自動重試，會讓「已經 INSERT 成功的
      JPEG 被插第二次」。崩潰重送的冪等靠 job 裡的 photo_ids／pages_done，也在那裡。

    ★ gate 與 cloud 為什麼在這裡才拿（design6 D5、D10）：
      gate  ＝ 隱私閘門。**分類要在檔案出機房之前**，所以它必須由 worker 觸發，
              不能放進 HTTP 路徑（那會讓 202 變慢，而且 D5 明文禁止）。
      cloud ＝ 雲端路。CLOUD_ROUTE 預設 off，此時 get_cloud_route() 回一顆
              「永遠說遠端不可用」的替身，於是每一筆都走 fallback ＝ 增量五那條路。
      兩個都用 dependencies.xxx() **直接呼叫**（不是 Depends）——這裡不是 HTTP 請求，
      所以 pytest 靠 monkeypatch 那一管換掉它們（conftest 第四／五道安全網）。

    ★ 為什麼 gate 用 build_privacy_gate_for_backend(job["ai_backend"])，
      而不是 get_privacy_gate()——**與上面 vlm 那一行同一個理由**（D6、D14）：
      閘門的短問要跟頁首那顆「AI 模型：本機｜雲端」開關走，而 get_privacy_gate()
      讀的是 config.AI_BACKEND；worker 是另一個行程，它那份永遠是預設的 "local"。
      用它建的話，使用者撥到雲端時「看圖走雲端、閘門仍打本機」——**安靜地違反 D6**。
      入列當下已經把開關值抄進 job 了，閘門與看圖用同一份快照才對得起來。
      （AWS 那扇門不受這個影響：不管短問打哪裡，只有 NON_SENSITIVE 才進得了 S3。）
    """
    store = dependencies.get_job_store()
    job = store.get(job_id)
    if job is None:
        # 任務被重送、但這筆 job 已經被 dismiss 或清掉了。什麼都不做就好
        # ——丟例外只會讓 Celery 印出一整片沒有意義的紅字。
        logger.warning("找不到 job，略過這次派工：job_id=%s", job_id)
        return

    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=dependencies.build_vlm_for_backend(job["ai_backend"]),
        embeddings=dependencies.get_embeddings(),
        now=dependencies.get_now,
        gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"]),
        cloud=dependencies.get_cloud_route(),
    )


class CeleryDispatcher:
    """把一筆 job 丟進佇列的入列器——phase-62 §4.2 三實作表的第三個，本 phase 落地。

    router 只呼叫 dispatch(job_id)（Phase 62 的 TaskDispatcher Protocol 就這一個方法）；
    dependencies.get_task_dispatcher() 回的就是這一個。

    dispatch 裡的 .delay(x) ＝ .apply_async(args=[x]) 的簡寫（官方 Calling Tasks 指南）。
    那一行**只是把訊息寫進 Redis**，不等 worker 做完——這就是 202 的由來。
    <https://docs.celeryq.dev/en/stable/userguide/calling.html>
    """

    def dispatch(self, job_id: str) -> None:
        ingest_task.delay(job_id)


@worker_ready.connect
def _sweep_stale_staging_on_worker_ready(sender=None, **kwargs) -> None:
    """worker 準備好接工作的那一刻，順手清掉 data/staging 裡的孤兒檔。

    worker_ready 是 Celery 的訊號（signal），意思是「worker 初始化完成、可以開始拿工作」。
    <https://docs.celeryq.dev/en/stable/userguide/signals.html>

    為什麼要掃：上傳當下先落 staging 再入列。那之間斷電、或 Redis 資料掉了，
    那個檔就變成沒人認領的孤兒。sweep_stale_staging()（Phase 58 寫好的）只清
    「超過 24 小時、而且 JobStore 裡沒有對應進行中任務」的檔——正在跑的絕不會被誤刪。

    整段包在 try 裡：掃把失敗只是少清幾個垃圾檔，**絕不可以讓 worker 起不來**。
    """
    try:
        removed_count = staging_service.sweep_stale_staging(dependencies.get_job_store())
        logger.info("staging 掃把（worker 啟動）：清掉 %d 個過期暫存檔", removed_count)
    except Exception:
        logger.warning("staging 掃把執行失敗，不影響 worker 啟動", exc_info=True)
