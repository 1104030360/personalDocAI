"""入庫任務的 router：GET /ingest-jobs、POST /ingest-jobs/{job_id}/dismiss。

這兩支是 Phase 67 全站進度面板**唯一**的資料來源：
前端每 2 秒打一次 GET，一次拿回「還在跑的任務」＋「待決定有幾張」，
用來更新右下角的面板與頂欄的「待決定（N）」（design5.md §6.1）。

三件事先講清楚：

1. **零 SQL。** 任務資料在 JobStore（記憶體或 Redis），待決定張數呼叫
   photo_repository.list_folders() 拿——這個檔案一行 SQL 都沒有
   （SQL 只准寫在 repository，全專案唯一例外沒有）。
2. **零 AI。** 這裡只是把已經存在的狀態讀出來，不看圖、不算向量。
3. **關掉失敗列用 POST，不是 DELETE。** design5.md §0 禁止事項第三條：
   Phase 37 釘死的「openapi 零 DELETE」到現在仍然有效。而且 dismiss 語意上
   本來就不是刪除——那筆任務早就結束了、staging 也早就清掉了，
   dismiss 只是「我知道了，別再顯示」。
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.dependencies import get_job_store
from app.repositories import photo_repository
from app.schemas.ingest_job import IngestJobListOut, IngestJobOut
from app.services.ingest_job_store import JobStore

router = APIRouter(tags=["ingest-jobs"])


def _job_out(job: dict) -> IngestJobOut:
    """把 JobStore 那一筆換成回應格式。

    用 .get() 取值而不是 job["…"]：IngestJob 是 total=False 的 TypedDict
    （欄位可以不存在），剛建好的任務就還沒有 error／page_count。
    少一個鍵不該讓整支清單端點 500。
    """
    return IngestJobOut(
        job_id=job["job_id"],
        filename=job["filename"],
        content_type=job["content_type"],
        status=job["status"],
        attempt=job.get("attempt", 0),
        page_count=job.get("page_count"),
        pages_done=job.get("pages_done", 0),
        error=job.get("error"),
    )


def _pending_count() -> int:
    """待決定（＝收件箱）現在有幾張照片。

    走 SQL、不走 Redis（design5.md §4.3 明文）：JobStore 裡沒有
    「已經入庫但還沒歸類」這種資訊——遷移進來的舊照片、上一次開機前就在
    收件箱的照片，都不會有對應的 job。這個數字只有資料庫知道。

    list_folders() 的 LEFT JOIN 已經把 photo_count 算好了（Phase 16），
    所以這裡不必新增任何 SQL；收件箱是 is_inbox 為 true 的唯一一筆
    （folder_one_inbox 這個部分唯一索引保證全系統至多一個）。
    """
    return next(
        folder["photo_count"]
        for folder in photo_repository.list_folders()
        if folder["is_inbox"]
    )


@router.get("/ingest-jobs", response_model=IngestJobListOut)
def list_ingest_jobs(store: JobStore = Depends(get_job_store)) -> IngestJobListOut:
    """還沒結束的任務 ＋ 待決定張數（design5.md §4.3、§6.1）。

    jobs 只會有四種狀態：queued／analyzing／retrying／failed。
    **成功的不會出現**——成功那一刻 worker 就把那筆 job 刪掉了，
    所以前端不必自己過濾 success（契約備忘 §3.1）。

    刻意不分頁、不排序參數、不篩選：單人系統，同時排隊的就那幾個檔案。
    """
    return IngestJobListOut(
        jobs=[_job_out(job) for job in store.list_open()],
        pending_count=_pending_count(),
    )


@router.post("/ingest-jobs/{job_id}/dismiss", status_code=204)
def dismiss_ingest_job(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> Response:
    """把一列**失敗**的任務從清單上關掉（design5.md §4.3、§8 第 9 列）。

    ★ 順序鐵律：**先 404（有沒有這筆）再 409（狀態對不對）**。
      反過來的話，不存在的 job_id 會拿到 409「還在進行中」——
      在講一件根本不存在的事，使用者完全看不懂。
      （這條順序與 PATCH /photos/{id}/folder「先照片後資料夾」是同一個道理。）

    只准關掉 failed：進行中的不准用這個藏起來（藏起來會讓人以為東西不見了，
    而它其實還在跑，之後照片突然冒出來更嚇人）。

    這裡**不刪 staging、也不刪照片**：
      - staging 在最終失敗那一刻就已經被 worker 刪掉了（design5.md §4.3 最後一句）
      - 失敗的任務本來就沒有照片
    dismiss 純粹是「從清單拿掉」，所以回 204（做完了，沒有東西要回給你）。
    """
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到這筆任務")
    if job["status"] != "failed":
        raise HTTPException(status_code=409, detail="這筆任務還在進行中，不能關掉")

    store.delete(job_id)
    # 直接回 Response 物件＝送出一個「沒有內容」的成功回應
    return Response(status_code=204)
