"""入庫任務的岔路口：先問隱私閘門，再決定這一筆走本機還是雲端（design6 §2、§2.1）。

【為什麼不把這一段寫進 ingest_job.py】
run_ingest_job() 是 fallback 的**目的地**。把閘門塞進它裡面的話，
「雲端不行 → 改走本機」就會變成「自己呼叫自己」——遞迴，而且很難讀。
拆成兩個檔之後責任非常乾淨：

    gated_ingest.run_gated_ingest_job()  ＝ 決定走哪一條路（本檔）
    ingest_job.run_ingest_job()          ＝ 純本機路，一個字都沒改（增量五那一條）

【Celery 從此呼叫這裡】
app/celery_app.py 的 ingest_task 改成呼叫本檔，並多傳兩個零件：
gate（隱私閘門）與 cloud（雲端路）。兩個都是注入點，pytest 換得掉。

【三條鐵律】
1. **不確定＝本機**（design6 D3）：只有明確的 NON_SENSITIVE 才有資格走雲端。
   判斷失誤的代價因此是「這張沒卸到雲端」（＝跟現在一模一樣），而不是「敏感檔外流」。
2. **fallback 時絕不再問一次閘門**（design6 §2.1 明文禁止）：已經判定非敏感了，
   遠端沒了就本機看圖，不要卡在「非敏感但不上雲」。
3. **遠端不可用時使用者無感**（design6 §0 禁止第 6 條）：不改 5xx、不要求重傳，
   進度面板的四種狀態一個字都不變。唯一的差別在 worker 的 log。

【雲端路上，哪些事仍然留在本機】（design6 D1／D13）
  * 向量（embedding）：一定要跟庫裡既有的向量同源（本機 bge-m3），所以 result.json 不含向量
  * INSERT ＋ 原圖 ＋ 縮圖：正本永遠在這台 Mac
  * 「這一筆算不算成功」：job 的生死（delete 或標 failed）永遠由本機決定

【本 phase（81）做到哪裡】
雲端路**全部做完**了：單圖與 PDF、順利的一圈與四種不順利
（不是 running／沒憑證（Phase 78）、送出失敗（79）、逾時（79／80）、
崩潰重送但沒有結果（80））。接下來是 ★G1——產品負責人點頭之後才開始碰 AWS。

PDF 的雲端路有一件事與單圖不同（總覽 §10.2 F）：**本機自己再拆一次頁**。
工人拆頁是為了看圖，本機拆頁是為了拿到「要存檔的那幾張 PNG」——
把工人拆好的每頁 PNG 放 S3 會讓物件數隨頁數暴增，而拆頁是純 CPU、幾百毫秒的事。

分層：本模組不寫 SQL、不碰 HTTP、不自己看圖——它只是「決定呼叫誰」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import cloud_ingest, ingest_job, pdf_service, staging_service, vlm_service
from app.services.ingest_job_store import IngestJob, JobStore
from app.services.privacy_gate import PrivacyGate, Verdict

logger = logging.getLogger(__name__)

# fallback 的四個理由（design6 §2.1）。**這四個字串是契約**——
# log 長什麼樣，design6 §2.1 有明文（`fallback=local reason=…`），測試用 caplog 逐字釘。
# 抽成常數是為了讓「產品碼」與「測試」不會各自打錯字。
REASON_REMOTE_UNAVAILABLE = "remote_unavailable"  # 不是 running／沒憑證／API 掛了（Phase 78）
REASON_SUBMIT_FAILED = "submit_failed"  # PutObject 或 SendMessage 失敗（Phase 79）
REASON_RESULT_TIMEOUT = "result_timeout"  # 送出去了但等不到結果（Phase 79 接、80 補測試）
REASON_REDELIVERED_WITHOUT_RESULT = "redelivered_without_result"  # 重送但 S3 沒結果（Phase 80）


def run_gated_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    gate: PrivacyGate,
    cloud: cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff,
) -> None:
    """一筆任務的岔路口。前四個零件原樣往下傳，後兩個在這裡用掉。

    ★ 不回傳任何東西：結果全部寫進 JobStore 與資料庫（與 run_ingest_job 同語意）。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被 dismiss：安靜結束。這不是錯誤——重送時本來就可能撞到。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    # 一進門就標 analyzing（design5 §4.4，雲端路一樣遵守）：
    # 崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    # ★ 要在問閘門**之前**：閘門（VlmGate）一定會把圖送去問 VLM 一句短問題，
    #   本機推估 20〜60 秒、雲端約 2 秒（總覽 §10.2 L）——標晚了那一列會停在 queued 很久。
    store.update(job_id, status="analyzing")

    route = job.get("route")
    if route == "local":
        # 崩潰重送，而且上一趟已經決定走本機了。**不再問一次閘門**（design6 §2.1）。
        logger.info("job %s 崩潰重送：route 已經是 local，直接走本機路", job_id)
        ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    if route == "cloud":
        # 崩潰重送，而且上一趟已經送去雲端了（總覽 §2.5）。同樣**不再問一次閘門**。
        _resume_cloud_route(job, store=store, vlm=vlm, embeddings=embeddings, now=now, cloud=cloud)
        return

    verdict = gate.classify(
        filename=job.get("filename", ""),
        content_type=job["content_type"],
        # 閘門是 VlmGate（Phase 74 建、75 接真模型）：它**一定**會呼叫 load_bytes——
        # 判斷靠**看圖**，不看檔名（2026-09-01 改判；design6 D4、總覽 §8.10、§10.1 追認項 f）。
        # filename 照樣傳，但那只是給呼叫端與假件記帳用，verdict 不准依賴它。
        # 仍然寫成 lambda 而不是先讀好：讀檔什麼時候發生、失敗了算什麼，都由閘門決定
        # （契約在總覽 §2.4.1：load_bytes 失敗 → UNCERTAIN ⇒ 走本機，不是讓這一筆失敗）。
        load_bytes=lambda: staging_service.read_staging(job_id, job["content_type"]),
    )
    store.update(job_id, privacy=verdict.value)

    if verdict != Verdict.NON_SENSITIVE:
        # 敏感 → 本機；不確定 → 也是本機（design6 D3）。**一個位元組都不出門。**
        store.update(job_id, route="local")
        logger.info("job %s route=local verdict=%s", job_id, verdict.value)
        ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    if not _remote_available(cloud, job_id):
        _fallback_to_local(
            job_id,
            REASON_REMOTE_UNAVAILABLE,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    # ---- 非敏感 ＋ 遠端可用 ＝ 唯一有資格走雲端的情況（design6 D7）----
    store.update(job_id, route="cloud")
    logger.info("job %s route=cloud verdict=%s", job_id, verdict.value)

    try:
        cloud.submit(
            job_id,
            content_type=job["content_type"],
            file_bytes=staging_service.read_staging(job_id, job["content_type"]),
            context=cloud_ingest.build_context(ingest_job.load_prompt_context()),
        )
    except Exception:
        # PutObject／SendMessage 失敗（design6 §8 錯誤表第 4 列）。
        # 先盡力刪掉半套的東西，再退回本機——**不留半套**是 §2.1 的明文要求。
        logger.warning("job %s：送去雲端失敗", job_id, exc_info=True)
        _best_effort_cloud_cleanup(cloud, job_id)
        _fallback_to_local(
            job_id,
            REASON_SUBMIT_FAILED,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    try:
        result = cloud.wait_result(job_id, store=store)
    except Exception:
        # 裁決 R14：真的 AwsMailbox 的 receive_result／get_object 在網路抖動時**會丟例外**。
        # 沒有這個 try 的話那個例外會一路飛到 celery_app.ingest_task（那裡沒有 try、
        # 也沒有 autoretry），結果是 job **永遠卡在 analyzing**、staging 與 S3 都留著、
        # 面板連一列失敗都不會出現——最難查的一種安靜壞掉。當成逾時處理才是對的。
        logger.warning("job %s：等雲端結果時信箱出錯，當作逾時", job_id, exc_info=True)
        result = None

    if result is None:
        # 逾時，或「訊息說好了但 S3 上找不到結果」（design6 §8 錯誤表第 5 列）
        _best_effort_cloud_cleanup(cloud, job_id)
        _fallback_to_local(
            job_id,
            REASON_RESULT_TIMEOUT,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    # ★ 這裡傳的是**進門時那份 job 複本**，不像 _resume_cloud_route 那樣重讀一次——刻意的：
    #   複本會過期的唯一情況是「同一個 job_id 被並行撿到、另一邊剛寫進 photo_ids」，
    #   而那條路一定是從 route == "cloud"／"local" 那兩個 if 進來的（route 在送出前
    #   就已經寫進 store 了），走不到這一行。而且 Celery 的 Redis transport
    #   預設 visibility_timeout ＝ 1 小時（本專案沒有覆蓋），遠大於這條路的最長時間
    #   （閘門＋submit＋最多 300 秒等結果），
    #   所以第一趟還在跑的時候佇列不會把同一則訊息再送一次。
    _store_cloud_result(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)


def _remote_available(cloud, job_id: str) -> bool:
    """問雲端路「現在能用嗎」。**問不出來就是不能用**（design6 §2.1 第 2 條）。

    這裡把例外吃掉是刻意的：沒有 AWS 憑證、DescribeInstances 被拒、網路不通——
    對使用者來說全部都是「這次走本機」，不是「上傳失敗」（§0 禁止第 6 條）。
    真正的原因寫進 log（exc_info=True 會帶 traceback），**不寫進 job["error"]**
    ——那一欄是給人看的短句，而且這一筆根本沒有失敗。
    """
    try:
        return cloud.available()
    except Exception:
        logger.warning("job %s：問遠端狀態時出錯，一律當作不可用", job_id, exc_info=True)
        return False


def _fallback_to_local(
    job_id: str,
    reason: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """退回本機路：釘 route、記一行契約字樣的 log，然後跑既有的 run_ingest_job。

    ★ route 釘成 "local" 是給「這一趟又被殺掉、佇列再送一次」用的：
      下一趟一進門就看到 route=local，直接走本機——不會再問閘門，
      也不會再送一次雲端（那會讓工人白做一次、S3 多一份垃圾）。

    ★ 這裡**不再問一次閘門**（design6 §2.1 的禁止）：已經判定是非敏感了，
      遠端沒了就本機看圖。
    """
    store.update(job_id, route="local")
    logger.warning("job %s fallback=local reason=%s", job_id, reason)
    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)


def _best_effort_cloud_cleanup(cloud, job_id: str) -> None:
    """盡力清掉這一筆在 S3 上的殘留。清不掉只 log——善後失敗不可以蓋掉真正的錯誤。

    CloudRoute.cleanup() 自己已經吞過一次例外，為什麼這裡還要再包一層：
    **這裡的 cloud 有可能是 CloudRouteOff**——使用者在任務半路把 CLOUD_ROUTE 改回 off
    （或 .env 的 AWS 設定被清掉、容器重啟），而那一顆的每一支方法都會丟 RuntimeError。
    清不掉也沒關係：S3 還有 Lifecycle（2 天）當掃把。
    """
    try:
        cloud.cleanup(job_id)
    except Exception:
        logger.warning("job %s 清雲端殘留時出錯，略過", job_id, exc_info=True)


def _resume_cloud_route(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """崩潰重送，而且上一趟已經送去雲端了：看結果在不在，決定落庫還是退回本機。

    ⚠ 這裡**絕不重新 submit**：上一趟送出去的東西還在 S3 與 jobs 佇列裡，
      工人可能正在做、也可能已經做完。再送一次只會讓它白做一次、S3 多一份垃圾。

    ⚠ 也**不再問一次閘門**（design6 §2.1 的禁止）：route 已經有值就代表判斷過了。

    fetch_result 用 try 包起來的理由與 _best_effort_cloud_cleanup 相同：cloud 有可能已經是 CloudRouteOff。
    拿不到結果 ＝ 那一趟的結果永遠不會來了（results 訊息多半已經被誰當殘訊息清掉），
    所以不要再等，直接退回本機（reason=redelivered_without_result）。

    ★ 落庫前**重新 store.get 一次**（D17 的最後一道保險）：
      run_gated_ingest_job 開頭那份 job 是**一份複本**（JobStore 的 get 一律回複本），
      拿到之後這條路上還隔著一次 fetch_result（S3 網路呼叫）。
      Celery 是 --concurrency=2（總覽 §8.8），同一個 job_id 被兩個子行程同時撿到時，
      舊複本會看不到「另一邊剛剛寫進去的 photo_ids」——照著它走就會 INSERT 第二張。
      重讀不能把那個窗口關到零（那要資料庫層的唯一鍵，本增量不做），但能把它縮到
      「store.get 到 INSERT」這幾行之內。查無（半路被 dismiss）就沿用手上那份，
      行為與重讀之前完全一樣。
    """
    job_id = job["job_id"]
    try:
        result = cloud.fetch_result(job_id)
    except Exception:
        logger.warning("job %s：崩潰重送時讀不到雲端結果", job_id, exc_info=True)
        result = None

    if result is not None:
        latest_job = store.get(job_id) or job
        logger.info("job %s 崩潰重送：S3 上已經有結果了，直接落庫", job_id)
        _store_cloud_result(
            latest_job, result, store=store, embeddings=embeddings, now=now, cloud=cloud
        )
        return

    _best_effort_cloud_cleanup(cloud, job_id)
    _fallback_to_local(
        job_id,
        REASON_REDELIVERED_WITHOUT_RESULT,
        store=store,
        vlm=vlm,
        embeddings=embeddings,
        now=now,
    )


def _store_cloud_result(
    job: IngestJob,
    result: dict,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """依檔案型別分流：單圖一張、PDF 一頁一張（沿用 design5 D11「一檔一任務」）。

    分流的依據是 job 的 content_type，**不是** result.json 的 kind：
    job 是我們自己寫的（HTTP 收檔時就決定了），kind 是工人寫的。
    兩邊不一致時（例如工人是舊版映像）以本機的為準——落庫是本機的責任。
    """
    if job["content_type"] == config.PDF_CONTENT_TYPE:
        _store_pdf_result(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
        return
    _store_image_result(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)


def _store_image_result(
    job: IngestJob,
    result: dict,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """拿工人看好的結果，在**本機**完成剩下的事（design6 D13）：

        算向量 → INSERT ＋ 存原圖 ＋ 存縮圖 → **立刻寫 photo_ids** → 清 S3 → 收尾（刪 staging、刪 job）

    ★ 用的是 Phase 76 抽出來的積木（embed_understanding／insert_photo_with_files／
      finish_image_job／fail_job），所以本機路與雲端路的落庫行為**逐字相同**——
      建議欄位、收件箱、縮圖長邊、失敗清理，全部不必再寫一次（也就不會漂移）。
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 冪等（design6 D17）：上一次其實已經插進去了，只是收尾被打斷。
    #    再插一次會變成兩張照片——這是 SQS at-least-once 最典型的災難。
    if job.get("photo_ids"):
        logger.info("job %s 已有照片 %s，判定為崩潰重送，直接收尾", job_id, job["photo_ids"])
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.finish_image_job(
            job_id, job["photo_ids"][0], store=store, content_type=content_type
        )
        return

    # ② 工人說看不懂（三次都失敗）＝ **這一筆失敗**，不是 fallback（總覽 §10 追認項 g）
    understanding = (
        _parse_understanding(result.get("understanding")) if result.get("understood") else None
    )
    if understanding is None:
        logger.warning("job %s：雲端看不懂（工人試了 %s 次）", job_id, result.get("attempts"))
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id,
            ingest_job.ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return

    # ③ 向量在**本機**算（D13）。算不出來是本機的問題，重看圖沒有幫助，所以只重算向量。
    prompt_context = ingest_job.load_prompt_context()
    embedding = _embed_with_retries(
        job_id, understanding, store=store, embeddings=embeddings, prompt_context=prompt_context
    )
    if embedding is None:
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id,
            ingest_job.ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return

    # ④ INSERT ＋ 原圖 ＋ 縮圖（失敗時 insert_photo_with_files 自己會清乾淨再往外丟）
    try:
        photo_id = ingest_job.insert_photo_with_files(
            staging_service.read_staging(job_id, content_type),
            content_type,
            understanding,
            embedding,
            inbox_name=prompt_context.inbox_name,
            folders=prompt_context.folders,
            entities=prompt_context.entities,
            uploaded_at=now(),
        )
    except Exception:
        logger.exception("job %s 入庫寫入失敗，半成品已清乾淨", job_id)
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_WRITE_FAILED, store=store, content_type=content_type
        )
        return

    # ⑤ INSERT 一成功就**立刻**把收據寫進 JobStore（總覽 §10.2 R；design6 D17）。
    #    下面的 cleanup 是 S3 網路呼叫（boto3 會自己重試，可拖數十秒）；這段期間 worker 被殺，
    #    佇列會再送一次同一個 job_id → 重送時 result.json 已經被 cleanup 刪掉 → fallback 本機
    #    → run_ingest_job 看到 photo_ids 才會「直接收尾不重做」。沒先寫 photo_ids 的版本
    #    會在這裡再 INSERT 一張——SQS at-least-once 最典型的災難（phase-79 review 抓到的）。
    store.update(job_id, photo_ids=[photo_id])

    # ⑥ 再清 S3、最後收尾。**收尾一定要放最後**：finish_image_job 會把 job 刪掉，
    #    刪掉之後就沒有人記得要清 S3 了（它會再寫一次 photo_ids，與 ⑤ 重複無害）。
    _best_effort_cloud_cleanup(cloud, job_id)
    ingest_job.finish_image_job(job_id, photo_id, store=store, content_type=content_type)
    # ★ 這一行是**契約字樣**：Phase 88（Mac 端到端）與 92（Demo 2）都靠 grep 它對帳
    #   （`docker compose logs worker | grep 雲端結果已入庫`）。成功的 job 會被刪掉，
    #   所以「照片真的從雲端回來了」在 log 上只剩這一行證據。
    logger.info("job %s 雲端結果已入庫：photo_id=%d", job_id, photo_id)


def _store_pdf_result(
    job: IngestJob,
    result: dict,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """PDF 的雲端路落庫：工人逐頁看好的結果 ＋ **本機自己拆的那幾張 PNG**。

    ★ 為什麼本機要再拆一次頁（總覽 §10.2 F）：
      工人拆頁是為了看圖；本機拆頁是為了拿到「要存進 data/photos 的那幾張 PNG」。
      把工人拆好的每頁 PNG 放 S3 會讓物件數隨頁數暴增（一份 30 頁的掃描件就 30 個物件），
      而 pypdfium2 拆頁是純 CPU、幾百毫秒的事。

    ★ 三條規則與本機路（ingest_job._run_pdf_job）**逐字相同**：
      ① 每一頁各自成敗：某一頁看不懂就跳過那一頁，其他頁照樣入庫
      ② 0 頁成功才整筆失敗（ERROR_PDF_ALL_PAGES_FAILED）
      ③ 崩潰重送從 pages_done 的**下一頁**接著跑，已成功的頁不重插
         （pages_done ＝「已處理幾頁」，**含跳過的頁**；每一頁的收據在整份 cleanup() 之前
         就已經寫進 JobStore——總覽 §10.2 R）
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 工人說這份 PDF 拆不開（pages 是空清單）＝ 這次上傳什麼都存不了
    pages = result.get("pages")
    if not isinstance(pages, list) or not pages:
        logger.warning("job %s：雲端回報 PDF 拆不開", job_id)
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_UNREADABLE, store=store, content_type=content_type
        )
        return

    # ② 本機自己拆一次頁，拿到要存檔的 PNG 位元組
    try:
        page_images = pdf_service.render_pages(staging_service.read_staging(job_id, content_type))
    except pdf_service.PdfUnreadableError:
        # 工人拆得開、本機拆不開：多半是 staging 檔在半路壞了（很罕見）
        logger.warning("job %s：本機拆頁失敗", job_id, exc_info=True)
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_UNREADABLE, store=store, content_type=content_type
        )
        return

    store.update(job_id, page_count=len(page_images))
    prompt_context = ingest_job.load_prompt_context()

    # ③ 依頁碼配對（工人回的順序不保證，用 page 這個欄位對，不要用陣列索引）
    page_results = {page.get("page"): page for page in pages if isinstance(page, dict)}
    if len(page_results) != len(page_images):
        # 兩邊拆的是同一份檔、用的是同一支 pdf_service，正常情況頁數一定相同。
        # 對不上＝工人是別的版本、或檔在半路壞了。對不上的頁由下面的 .get() 當「沒有結果」跳過，
        # 這裡先大聲記一行——不然「少了幾頁」會安靜地變成幾個跳頁，事後很難查。
        logger.warning(
            "job %s：工人回了 %d 頁的結果，本機拆出 %d 頁，對不上的頁會被跳過",
            job_id,
            len(page_results),
            len(page_images),
        )

    photo_ids: list[int] = list(job.get("photo_ids") or [])
    already_done = job.get("pages_done") or 0
    if already_done:
        logger.info(
            "job %s：崩潰重送，已處理 %d／%d 頁，從第 %d 頁接著跑",
            job_id,
            already_done,
            len(page_images),
            already_done + 1,
        )

    for page_number, page_bytes in enumerate(page_images[already_done:], start=already_done + 1):
        photo_id = _store_pdf_page(
            job_id,
            page_number,
            page_bytes,
            page_results.get(page_number),
            store=store,
            embeddings=embeddings,
            now=now,
            prompt_context=prompt_context,
        )
        if photo_id is not None:
            photo_ids.append(photo_id)
        # 成功或跳過都要記 pages_done，而且要與 photo_ids **同一次**寫進去：
        # 分兩次寫的話，剛好被殺在中間的重送會把同一頁再做一次（沿用本機路的作法）。
        # ★ 這一行也是 PDF 版的「先寫收據」（總覽 §10.2 R）：每一頁的收據在**這裡**、
        #   在整份的 cleanup()（下面 ④）之前就已經落到 JobStore——cleanup 期間被殺，
        #   重送會從 pages_done 的下一頁接著跑，已入庫的頁不會再插一次。
        store.update(job_id, pages_done=page_number, photo_ids=list(photo_ids))

    # ④ 收尾：至少一頁成功就算整筆成功（design5 D12）。
    #    走到這裡時每一頁的 pages_done／photo_ids 都已經在 JobStore 裡了（③ 的迴圈每頁寫一次），
    #    所以下面的 cleanup（S3 網路呼叫）與刪 job 之間被殺也不會雙 INSERT（總覽 §10.2 R）。
    if not photo_ids:
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_ALL_PAGES_FAILED, store=store, content_type=content_type
        )
        return

    _best_effort_cloud_cleanup(cloud, job_id)
    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    # ★ 契約字樣（與單圖那一行同一個前綴）：Phase 88／92 的 Demo 靠 grep「雲端結果已入庫」對帳。
    #   跳過幾頁算得出來：len(page_images) − len(photo_ids)，不必再印一個欄位。
    logger.info(
        "job %s 雲端結果已入庫：%d 頁中 %d 頁成功（photo_ids=%s）",
        job_id,
        len(page_images),
        len(photo_ids),
        photo_ids,
    )


def _store_pdf_page(
    job_id: str,
    page_number: int,
    page_bytes: bytes,
    page_result: dict | None,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    prompt_context: ingest_job.PromptContext,
) -> int | None:
    """把 PDF 的一頁變成資料庫裡的一列；這一頁不成立就回 None（＝跳過它）。

    三種「跳過」：工人沒回這一頁、工人說看不懂、本機轉向量或寫檔失敗。
    三種都只影響**這一頁**——其他頁照樣入庫（design5 D12 的 skipped_pages 語意）。
    """
    understanding = (
        _parse_understanding(page_result.get("understanding"))
        if page_result and page_result.get("understood")
        else None
    )
    if understanding is None:
        logger.warning("job %s：第 %d 頁雲端看不懂或沒有結果，跳過這一頁", job_id, page_number)
        return None

    embedding = _embed_with_retries(
        job_id, understanding, store=store, embeddings=embeddings, prompt_context=prompt_context
    )
    if embedding is None:
        logger.warning("job %s：第 %d 頁本機轉向量失敗，跳過這一頁", job_id, page_number)
        return None

    try:
        return ingest_job.insert_photo_with_files(
            page_bytes,
            ingest_job.PDF_PAGE_CONTENT_TYPE,
            understanding,
            embedding,
            inbox_name=prompt_context.inbox_name,
            folders=prompt_context.folders,
            entities=prompt_context.entities,
            uploaded_at=now(),
        )
    except Exception:
        # 半成品已由 insert_photo_with_files 自己清乾淨（檔案＋資料列）
        logger.exception(
            "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁", job_id, page_number
        )
        return None


def _embed_with_retries(
    job_id: str,
    understanding: vlm_service.PhotoUnderstanding,
    *,
    store: JobStore,
    embeddings: Embeddings,
    prompt_context: ingest_job.PromptContext,
) -> list[float] | None:
    """在本機把看圖結果轉成向量，最多試 config.VLM_MAX_ATTEMPTS 次；全部失敗回 None。

    ★ 只重算向量、**不重看圖**：圖是工人看的、結果已經拿到了。重看要再跑一整圈雲端
      （再 Put 一次、再等一次），而失敗的是本機的 bge-m3，重看圖一點幫助也沒有。

    ★ status 沿用既有語意：第 1 次 analyzing，第 2、3 次 retrying（design5 §4.3）。
      **雲端看圖試了幾次不回寫**（總覽 §10.2 E）：使用者根本不知道有雲端這回事，
      面板上的「第 N 次」如果從 3 開始跳會非常難懂。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        store.update(
            job_id,
            status="analyzing" if attempt == 1 else "retrying",
            attempt=attempt,
        )
        try:
            return ingest_job.embed_understanding(
                understanding, embeddings=embeddings, inbox_name=prompt_context.inbox_name
            )
        except Exception:
            logger.warning("job %s：第 %d 次轉向量失敗", job_id, attempt, exc_info=True)
    return None


def _parse_understanding(payload: object) -> vlm_service.PhotoUnderstanding | None:
    """把 result.json 裡的 understanding 還原成 PhotoUnderstanding；還原不了回 None。

    為什麼要這麼小心：工人與本機是**兩支不同的程式**（EC2 上跑的可能是舊一點的映像），
    欄位不一定對得上。驗證不過就當作「這張看不懂」——
    寧可少一張照片，也不要讓一筆奇怪的 JSON 變成資料庫裡一列奇怪的資料。

    「看得懂但一個字都沒寫」也算看不懂（`text.strip()`）：與本機路的判準逐字相同。
    """
    if not isinstance(payload, dict):
        return None
    try:
        # model_validate ＝ 交給 Pydantic 驗整個 dict：驗型別與必填欄；
        # 多餘鍵會被忽略（PhotoUnderstanding 沒設 extra="forbid"）。
        # 不用 **payload 拆開傳——那樣遇到不是字串的鍵會炸出另一種例外，訊息也難懂。
        understanding = vlm_service.PhotoUnderstanding.model_validate(payload)
    except Exception:
        logger.warning("result.json 的 understanding 欄位長得不對，當作看不懂", exc_info=True)
        return None
    if not understanding.understood or not understanding.text.strip():
        return None
    return understanding
