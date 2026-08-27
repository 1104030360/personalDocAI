"""入庫任務的 API 資料格式（Pydantic 模型，增量五）。

「任務」是增量五才有的概念：上傳不再當場入庫，而是先變成一筆排隊中的任務，
由 worker 拿去做。這個檔只放**對外送出去**的形狀，任務本身的資料結構
（IngestJob）在 app/services/ingest_job_store.py。
"""

from pydantic import BaseModel


class IngestAcceptedResponse(BaseModel):
    """POST /photos 與 POST /camera/{token}/photos 受理成功時的回應（HTTP 202）。

    ⚠ **202 不是「照片已經存好了」**，是「檔案已經收下、排進佇列了」。
    這一刻資料庫的 photo 表**一列都沒有多**（design5.md §4.2）。
    要知道做完了沒有，得看 GET /ingest-jobs（Phase 64）或直接去看待決定頁。

    刻意只有三個欄位：
      - job_id       ：這次的號碼牌，之後關掉失敗列（dismiss）要用它
      - filename     ：進度面板那一列要顯示的檔名（使用者才認得出是哪一張）
      - content_type ：圖還是 PDF，進度面板用它決定要不要顯示頁數

    刻意「不回」：照片 id（還沒有）、text／metadata（還沒看圖）、
    suggested_folder／folders／entities／suggested_task（那些現在改成
    入庫時寫進 photo 那一列，待決定開窗時再讀——design5.md D16）。
    """

    job_id: str
    filename: str
    content_type: str


class IngestJobOut(BaseModel):
    """GET /ingest-jobs 清單裡的一列（design5.md §4.3、§6.6）。

    這是「進度面板上那一列」要畫的東西，不多不少：

      queued            → 「檔名」（PDF 若已知頁數則「檔名（N 頁）」）
      analyzing/retrying→ 「檔名 第 attempt 次」（PDF 加「第 pages_done／page_count 頁」）
      failed            → 「檔名」＋ error 這句短話，右上角一個 ×

    刻意「不回」JobStore 裡另外三樣：
      photo_ids  ── 崩潰重送用的內部狀態，前端拿去也不知道要幹嘛
      ai_backend ── 使用者不需要在進度列上看到「這張是雲端跑的」
      source     ── 使用者同樣不需要看到（電腦上傳或手機拍的，檔名就看得出來了）
    留在 JobStore 裡不外送，是「回應只回畫得出來的東西」的一貫作法
    （比照 GET /folders/{id} 的瘦契約）。
    """

    job_id: str
    filename: str
    content_type: str
    status: str  # queued / analyzing / retrying / failed
    attempt: int  # 這張／這頁目前第幾次 VLM，1〜3
    page_count: int | None = None  # PDF 才有；還沒拆頁前是 None
    pages_done: int = 0  # PDF 已處理頁數（含跳過的）
    error: str | None = None  # 失敗時給人看的短句（**不要**把 stack 丟給瀏覽器）


class IngestJobListOut(BaseModel):
    """GET /ingest-jobs 的回應（HTTP 200）。

    一次輪詢帶回兩件事，讓前端只要打一支就能同時更新
    右下角的進度面板與頂欄的「待決定（N）」（design5.md §6.1）：

      jobs          ── 還沒結束的任務（queued／analyzing／retrying／failed）。
                       **成功的不會出現**——成功＝那筆 job 被刪掉了，
                       所以前端不必自己過濾（design5.md §4.3）。
      pending_count ── 待決定（＝收件箱）現在有幾張照片。
                       這個數字走 SQL、不走 Redis：JobStore 裡沒有
                       「已入庫但還沒歸類」這種資訊，那是資料庫的事。
    """

    jobs: list[IngestJobOut]
    pending_count: int
