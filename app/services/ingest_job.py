"""照片入庫的任務本體：一個檔案 ＝ 一次 run_ingest_job（design5.md D11／D15）。

★ 這個模組**不知道 HTTP 是什麼，也不知道 Celery 是什麼。**
  它只吃一個 job_id，其餘全部從參數拿（store／vlm／embeddings／now）。
    - Celery 任務（Phase 65）＝薄薄一層：組好那四個參數，呼叫這裡。
    - pytest（Phase 59）    ＝直接呼叫這裡，不啟動 worker、不連 Redis。
  這條「可替換接縫」（seam）就是 design5 D15 的全部意思。

★ 這裡**沒有 HTTPException**。
  增量五之前 photos.py 的同步上傳流程（Phase 63 已整段刪除）用
  「丟 HTTPException(422)」表達「看不懂」，
  因為那時候整段流程活在一個 HTTP 請求裡，FastAPI 會把它翻譯成回應。
  搬進 worker 之後沒有人會做那個翻譯——所以「看不懂」在這裡改用**回傳值**表達
  （`_understand_and_embed` 回 None），最終結果寫進 JobStore：
  `status="failed"` ＋ 一句給人看的短句（design5 §4.3）。

★ 重試在**函式內部**（design5.md §4.4）。
  同一張圖最多送 VLM `config.VLM_MAX_ATTEMPTS` 次（含第一次）。
  ⛔ **絕對不要**改用 Celery 的 `autoretry_for` 讓整個任務重跑——
     那會把已經 INSERT 的照片再插一次。理由與圖解見計畫文件 phase-59 §5。

分層：本模組會呼叫 repository（寫資料庫）、storage_service（寫檔）、
staging_service（讀／刪暫存檔）、vlm_service／indexing_service（AI）。
它**不寫任何 SQL**（全站鐵律：SQL 只在 photo_repository）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.repositories import photo_repository
from app.services import (
    ai_timing,
    indexing_service,
    pdf_service,
    staging_service,
    storage_service,
    vlm_service,
)
from app.services.ingest_job_store import IngestJob, JobStore

logger = logging.getLogger(__name__)

# 看圖 prompt 要注入幾筆糾錯例子（design3.md D11／§7 的暫定 N＝5）。
# Phase 59〜62 期間 photos.py 曾短暫留著一份同名常數（舊同步流程在用）；
# Phase 63 把鏡頭端點也改走佇列、舊流程整段退役之後，**全站只剩這一份**。
FEW_SHOT_CORRECTIONS = 5

# 失敗時寫進 job["error"] 的句子。**給人看的短句**，不是 traceback（design5.md §4.3）。
# 進度面板一列就這麼寬，寫太長會被截掉，所以刻意都在 20 個字以內。
ERROR_VLM_FAILED = "AI 看不懂這張照片（已試 {attempts} 次）"
ERROR_WRITE_FAILED = "照片存檔失敗，這張沒有留下資料"

# PDF 的每一頁渲染出來都是 PNG，之後就完全是一次普通的單圖入庫
#（原圖存成 .png、讀圖端點零改動，不必為 PDF 另開一條路）
PDF_PAGE_CONTENT_TYPE = "image/png"

ERROR_PDF_UNREADABLE = "這份 PDF 讀不開或沒有內容"
ERROR_PDF_ALL_PAGES_FAILED = "PDF 每一頁 AI 都看不懂"


class _NotUnderstood(Exception):
    """「這一次 VLM 沒看懂」。只在本模組內部從 with 區塊丟到迴圈外。

    為什麼要一個例外而不是 if：計時 log 的「結束行要標 ok=false」是靠
    ai_timing 的 with 區塊捕捉例外做到的（design4.md §5.2）。
    在 with 裡面 raise，結束行才會誠實地標成失敗——這與增量四的舊同步流程
    在 with 裡面 raise HTTPException(422) 是同一個手法。
    """


def run_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """把一個 job 從頭做到尾。不回傳東西——結果全部寫進 JobStore 與資料庫。

    now 是**可呼叫的**（與 dependencies.get_now 同型）：
      - 正式執行傳 `get_now` 本人 → 呼叫得到 None → 上傳時間交給資料庫的 now()
      - 測試傳 FixedClock          → 呼叫得到固定時間
    這裡一定要寫 `now()` 而不是直接把 now 當值用，否則會把函式物件塞進資料庫。

    ★ 任務開頭先把 status 改成 analyzing（design5.md §4.4）：
      崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被刪：安靜結束。這不是錯誤——重送時本來就可能撞到。
        # 這裡沒有 content_type，所以連 staging 都算不出路徑；
        # 真的有殘檔就交給 Phase 58 的 24 小時掃把清（design5.md §4.1）。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    store.update(job_id, status="analyzing")

    if job["content_type"] == config.PDF_CONTENT_TYPE:
        _run_pdf_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    _run_image_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)


def _run_image_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一張 JPEG／PNG 的完整入庫（design5.md §2、§4.2）。"""
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 冪等檢查（design5.md §4.4）：已經有照片 id 了＝上一次其實做完了，
    #    只是 ack 沒送回佇列。再插一次會變成兩張，所以直接收尾就好。
    if job.get("photo_ids"):
        logger.info(
            "job %s 已有照片 %s，判定為崩潰重送，直接收尾不重做",
            job_id,
            job["photo_ids"],
        )
        staging_service.remove_staging(job_id, content_type)
        store.delete(job_id)
        return

    # ② 從暫存區把位元組讀回來。影像**從來不進 Redis、也不當 Celery 參數**
    #    （design5.md §4.1、§1.2 被否決項）。
    image_bytes = staging_service.read_staging(job_id, content_type)

    # ③ 清單各讀一次（與增量四舊上傳流程的呼叫端一字不差）：
    #    資料夾、實體、最近的糾錯例子都要注入看圖 prompt。
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
    inbox = next(folder for folder in folders if folder["is_inbox"])

    # ④ 看圖＋轉向量，最多 VLM_MAX_ATTEMPTS 次
    result = _understand_and_embed(
        job_id,
        image_bytes,
        content_type,
        store=store,
        vlm=vlm,
        embeddings=embeddings,
        folders=folders,
        entities=entities,
        corrections=corrections,
        inbox_name=inbox["name"],
    )
    if result is None:
        _fail(
            job_id,
            ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return
    understanding, embedding = result

    # ⑤ 寫資料庫＋寫檔。這一段失敗就是最終失敗（VLM 已經成功了，重看沒有意義）
    try:
        photo_id = _insert_photo_with_files(
            image_bytes,
            content_type,
            understanding,
            embedding,
            inbox_name=inbox["name"],
            folders=folders,
            entities=entities,          # ← Phase 61 新增
            uploaded_at=now(),
        )
    except Exception:
        logger.exception("job %s 入庫寫入失敗，半成品已清乾淨", job_id)
        _fail(job_id, ERROR_WRITE_FAILED, store=store, content_type=content_type)
        return

    # ⑥ 收尾。photo_ids 一定要在刪 staging 之前寫進去——
    #    順序反過來的話，「剛好在這兩步之間被殺掉」的重送會找不到冪等依據。
    store.update(job_id, photo_ids=[photo_id])
    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    logger.info(
        "job %s 入庫完成：photo_id=%d（先進「%s」，等使用者到待決定頁歸類）",
        job_id,
        photo_id,
        inbox["name"],
    )


def _run_pdf_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一份 PDF 的完整入庫：同一個 worker 依序把每一頁看完（design5.md D11、D12）。

    ★ 一個任務 ＝ 一個檔案。**不要**把每一頁再丟成一個 Celery 任務——
      那樣同一份檔會被兩個 worker 拆開跑，進度面板畫不出「一檔一列」（§1.2 已否決）。

    ★ 重試單位是「一頁」，不是整份檔。每一頁各自最多 config.VLM_MAX_ATTEMPTS 次，
      仍失敗就**跳過那一頁**繼續下一頁（沿用 design3 起就有的 skipped_pages 語意）。
      整份 0 頁成功（或檔案根本拆不開）才整筆失敗。

    ★ 冪等（design5.md §4.4）：從 job["pages_done"] 的**下一頁**接著跑。
      pages_done ＝「已處理幾頁」，**含跳過的頁**（§4.3 原文）。
      已經成功的頁不重看、不重 INSERT，它們的 id 留在 photo_ids 裡。

    ★ 「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
      IngestJob 的欄位表是跨文件契約，不為了一個衍生值多開一欄。
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 拆頁。整份讀不開（壞檔、加密、零頁）＝這次上傳什麼都存不了
    pdf_bytes = staging_service.read_staging(job_id, content_type)
    try:
        page_images = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        logger.warning("job %s：PDF 拆頁失敗", job_id, exc_info=True)
        _fail(job_id, ERROR_PDF_UNREADABLE, store=store, content_type=content_type)
        return

    # ② 拆得開才知道幾頁（design5.md §4.3：未拆前 page_count 可為 null）
    store.update(job_id, page_count=len(page_images))

    # ③ 清單在迴圈**外面**讀一次：整份 PDF 的每一頁共用同一份注入 prompt
    #（與現在 photos.py 的 upload_photo 讀一次、傳給每頁的作法一致）
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
    inbox = next(folder for folder in folders if folder["is_inbox"])

    # ④ 從上次做到的地方接著跑
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

    # enumerate 的 start 讓頁碼從「下一頁」開始算，1 起算（與 skipped_pages 同一套）
    for page_number, page_bytes in enumerate(
        page_images[already_done:], start=already_done + 1
    ):
        photo_id: int | None = None
        result = _understand_and_embed(
            job_id,
            page_bytes,
            PDF_PAGE_CONTENT_TYPE,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            folders=folders,
            entities=entities,
            corrections=corrections,
            inbox_name=inbox["name"],
        )
        if result is None:
            logger.warning(
                "job %s：第 %d 頁試了 %d 次仍失敗，跳過這一頁",
                job_id,
                page_number,
                config.VLM_MAX_ATTEMPTS,
            )
        else:
            understanding, embedding = result
            try:
                photo_id = _insert_photo_with_files(
                    page_bytes,
                    PDF_PAGE_CONTENT_TYPE,
                    understanding,
                    embedding,
                    inbox_name=inbox["name"],
                    folders=folders,
                    entities=entities,          # ← Phase 61 新增
                    uploaded_at=now(),
                )
            except Exception:
                # 半成品已由 _insert_photo_with_files 自己清乾淨（檔案＋資料列）。
                # 這一頁當成「跳過」處理，不讓它拖垮已經成功的其他頁——
                # 理由見計畫文件 phase-60 §4 步驟 3 的裁決說明。
                logger.exception(
                    "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁",
                    job_id,
                    page_number,
                )

        if photo_id is not None:
            photo_ids.append(photo_id)
        # ★ 成功或跳過都要記 pages_done，而且要與 photo_ids **同一次**寫進去：
        #   分兩次寫的話，剛好被殺在中間的重送會把同一頁再做一次。
        store.update(job_id, pages_done=page_number, photo_ids=list(photo_ids))

    # ⑤ 收尾：至少一頁成功就算整筆成功（design5.md D12）
    if not photo_ids:
        _fail(
            job_id,
            ERROR_PDF_ALL_PAGES_FAILED,
            store=store,
            content_type=content_type,
        )
        return

    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    logger.info(
        "job %s 入庫完成：%d 頁中 %d 頁成功、%d 頁跳過（photo_ids=%s）",
        job_id,
        len(page_images),
        len(photo_ids),
        len(page_images) - len(photo_ids),
        photo_ids,
    )


def _understand_and_embed(
    job_id: str,
    image_bytes: bytes,
    content_type: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
    inbox_name: str,
) -> tuple[vlm_service.PhotoUnderstanding, list[float]] | None:
    """看圖 ＋ 轉向量，最多試 config.VLM_MAX_ATTEMPTS 次；全部失敗回 None。

    一次 attempt ＝「看一次圖 ＋ 算一次向量」。兩者任一失敗都算這次失敗
    （design5.md §8 第 6 列：embedding 失敗算進 3 次），下一次從看圖重來。

    ★ 為什麼 embedding 失敗要連圖一起重看？
      因為 embedding 吃的是這次看圖的結果。只重算向量不重看圖也可以，
      但那要多一層狀態；而 3 次上限本來就是保守值，重看一次圖的成本可以接受。
      重點是**兩者都還沒 INSERT**，所以重來完全乾淨。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        # 第 1 次是 analyzing，第 2、3 次是 retrying（design5.md §4.3 的四種狀態）
        store.update(
            job_id,
            status="analyzing" if attempt == 1 else "retrying",
            attempt=attempt,
        )

        try:
            # 計時 log 走全站共用的 ai_timing（design4.md §5）。
            # target 從 vlm 物件身上拿：正式的 OllamaVLM／OllamaCloudVLM 建構時
            # 就把 backend 與 model 記在 timing_target 上，所以 worker 只要
            # 「用任務裡的 ai_backend 快照建對客戶端」，log 的 backend= 自然就對
            #（design5.md D14）。假件沒有這個屬性，會退回讀 config，不影響測試。
            with ai_timing.log_ai(
                "vlm", target=vlm_service.vlm_timing_target(vlm)
            ) as 計時:
                understanding = vlm.understand(
                    image_bytes, content_type, folders, entities, corrections
                )
                if not understanding.understood or not understanding.text.strip():
                    計時.note = (
                        f"understood=false text_chars={len(understanding.text)}"
                    )
                    raise _NotUnderstood()
                計時.note = (
                    f"understood=true text_chars={len(understanding.text)} "
                    f"item_count={len(understanding.items)} "
                    f"category_present={'true' if understanding.category else 'false'} "
                    f"entity_present={'true' if understanding.entity else 'false'} "
                    f"task_present={'true' if understanding.task_title else 'false'}"
                )
        except _NotUnderstood:
            logger.warning("job %s：第 %d 次看圖，AI 說看不懂", job_id, attempt)
            continue
        except Exception:
            # Ollama 沒開、雲端 401／404、逾時、結構化輸出驗證不過……全算一次失敗。
            # exc_info=True 讓 traceback 進伺服器 log；它**不會**進 job["error"]。
            logger.warning(
                "job %s：第 %d 次看圖呼叫失敗", job_id, attempt, exc_info=True
            )
            continue

        # 合併與轉向量一律用收件箱名稱——上傳當下的向量就是未分類版本
        #（design1.md §2；歸類後 PATCH 會整條重算）
        content_time = vlm_service.parse_content_time(understanding.content_time)
        document = indexing_service.build_document(
            text=understanding.text,
            category=inbox_name,
            location=understanding.location,
            items=understanding.items,
            content_time=content_time.isoformat() if content_time else None,
        )
        try:
            with ai_timing.log_ai(
                "embed",
                target=indexing_service.embedding_timing_target(embeddings),
            ):
                embedding = indexing_service.embed_document(embeddings, document)
        except Exception:
            logger.warning(
                "job %s：第 %d 次轉向量失敗", job_id, attempt, exc_info=True
            )
            continue

        return understanding, embedding

    return None


def _insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    entities: list[dict],
    uploaded_at: datetime | None,
) -> int:
    """INSERT → 存原圖 → 產縮圖 → UPDATE 補路徑。任何一步失敗就清乾淨再往外丟。

    ★ 這一段是從增量四 photos.py 的舊同步上傳流程第 ★③〜⑤ 段**原封不動搬過來的**
      （對照表見計畫文件 phase-59 §4 步驟 5；該舊流程已於 Phase 63 整段刪除）：
      檔名要用 photo.id，
      而 id 是 INSERT 當下才配發的，所以只能先 INSERT、寫完檔再回來補路徑。
      這三步不是一條 SQL，沒有交易可以 rollback（交易也管不到磁碟上的檔案），
      所以失敗時自己把兩個檔案與那一列刪掉，再把原始錯誤往外丟。
      差別只有一個：往外丟之後，接住它的不再是 FastAPI（500），
      而是 `_run_image_job` 的 except（把 job 標成 failed）。
    """
    # ── 三個「建議」欄位（design5.md D16）──────────────────────────────
    # 這裡寫的是「AI 當下猜了什麼」，不是「這張照片屬於什麼」。
    # 照片的實際歸屬永遠是收件箱（category／folder_id 都是「未分類」）；
    # 實體與待辦更是**一列都不寫**——那三張表要等人在待決定的彈窗按下去才有資料
    #（design5.md §4.2、design3.md D3「人確認才落庫」）。
    #
    # 為什麼非存不可：上傳改 202 之後（Phase 62），建議不會再出現在任何回應裡。
    # 不存下來的話，使用者幾分鐘後到待決定頁點開那張照片時，
    # 實體窗會少了選項①、**待辦窗會永遠不開**（開窗條件就是「有待辦建議」）。

    # ① 資料夾建議：夾回清單內，清單外一律變「未分類」。
    #    建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL（Phase 35 的規則不變）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    suggested_category = None if suggested_name == inbox_name else suggested_name

    # ② 實體建議：同樣夾回清單，但**沒有保底選項**——清單外或都不像就是 None
    #    （clamp_entity 回的是整筆 dict，這一欄只存名稱字串）。
    suggested_entity_row = vlm_service.clamp_entity(understanding.entity, entities)
    suggested_entity = suggested_entity_row["name"] if suggested_entity_row else None

    # ③ 待辦建議：判準與現在 photos.py::_task_suggestion() 逐字相同——
    #    標題是空的（沒填或只有空白）＝這張照片沒有待辦，兩欄都留 NULL。
    #    到期日沿用 parse_content_time 的寬容解析：模型回「下週三」之類推不出來的東西
    #    只是少一個日期，**絕不可以讓整張照片入不了庫**（與 content_time 同一個原則）。
    suggested_task_title: str | None = None
    suggested_task_due = None
    if understanding.task_title and understanding.task_title.strip():
        suggested_task_title = understanding.task_title.strip()
        suggested_task_due = vlm_service.parse_content_time(understanding.task_due)

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=vlm_service.parse_content_time(understanding.content_time),
        embedding=embedding,
        uploaded_at=uploaded_at,
        suggested_category=suggested_category,
        suggested_entity=suggested_entity,
        suggested_task_title=suggested_task_title,
        suggested_task_due=suggested_task_due,
    )
    photo_id = row["id"]

    original_path: str | None = None
    thumbnail_path: str | None = None
    try:
        original_path = storage_service.save_original(
            photo_id, image_bytes, content_type
        )
        thumbnail_path = storage_service.make_thumbnail(
            photo_id, image_bytes, content_type
        )
        photo_repository.update_photo_paths(
            photo_id,
            original_path=original_path,
            thumbnail_path=thumbnail_path,
            content_type=content_type,
        )
    except Exception:
        # remove_if_exists 吃得下 None（那一步還沒跑到就失敗了）與「檔案本來就不在」
        storage_service.remove_if_exists(original_path)
        storage_service.remove_if_exists(thumbnail_path)
        photo_repository.delete_photo(photo_id)
        raise

    return photo_id


def _fail(job_id: str, message: str, *, store: JobStore, content_type: str) -> None:
    """最終失敗的統一收尾：刪 staging ＋ 把 job 標成 failed。

    **不刪 job**——失敗的那一列要留在進度面板上讓人看到，
    由使用者按 × 走 `POST /ingest-jobs/{id}/dismiss` 才消失（design5.md §4.3）。
    """
    staging_service.remove_staging(job_id, content_type)
    store.update(job_id, status="failed", error=message)
    logger.warning("job %s 最終失敗：%s", job_id, message)
