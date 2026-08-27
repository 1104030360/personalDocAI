"""FastAPI app 組裝：掛上八個 router ＋ 極簡網頁介面（靜態檔案）。"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import dependencies
from app.api.routers import (
    ask,
    camera,
    entities,
    folders,
    ingest_jobs,
    photos,
    settings,
    tasks,
)
from app.services import staging_service

# 讓 app.* 的 INFO log 顯示在 uvicorn 終端機。
# uvicorn 只配置它自家的 logger（uvicorn / uvicorn.access），應用程式的 logger
# 沒有 handler 時只有 WARNING 以上會被 Python 的最後防線印出來——
# 「AI 看圖開始／完成」這類追蹤訊息是 INFO，必須自己掛 handler 才看得到。
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    _app_logger.addHandler(_handler)
    _app_logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動／關閉時要做的事（增量五 design5.md §4.1）。

    啟動時掃一次 data/staging，把「超過 24 小時、而且 JobStore 裡沒有對應進行中任務」
    的孤兒檔清掉。這是崩潰後的後悔藥——上傳當下先落 staging 再入列，中間斷電的話
    那個檔就沒人認領了。

    worker 那邊也有一份一樣的（app/celery_app.py 的 worker_ready）。兩邊都掃是刻意的：
    常駐時兩個容器一起起來，誰先掃到都行；只起其中一個時也不會漏。
    sweep_stale_staging 本身冪等，掃兩次沒有副作用。

    整段包在 try 裡：掃把失敗只是少清幾個垃圾檔，**絕不可以讓服務起不來**。
    """
    try:
        清掉幾個 = staging_service.sweep_stale_staging(dependencies.get_job_store())
        _app_logger.info("staging 掃把（app 啟動）：清掉 %d 個過期暫存檔", 清掉幾個)
    except Exception:
        _app_logger.warning("staging 掃把執行失敗，不影響服務啟動", exc_info=True)
    yield
    # 關閉時沒有要做的事：資料庫連線是每個請求現開現關（app/db/session.py）


app = FastAPI(title="PersonalDocAI", lifespan=lifespan)

app.include_router(photos.router)
app.include_router(ask.router)
app.include_router(folders.router)
app.include_router(entities.router)
app.include_router(tasks.router)
# 無線鏡頭（Phase 36）：三支 HTTP 進 /openapi.json，
# 信令用的 WebSocket 依 FastAPI 的行為不會出現在 openapi.json
app.include_router(camera.router)
# AI 後端開關（2026-08-22 產品負責人指示；管看圖＋詢問路由／回答＋實體建議）：
# GET／PUT /settings/ai-backend 兩支（端點一律數 20；清點測試在 test_photo_detail.py）
app.include_router(settings.router)

# 入庫任務清單（增量五 Phase 64）：全站進度面板與頂欄「待決定（N）」的唯一資料來源
# GET /ingest-jobs ＋ POST /ingest-jobs/{job_id}/dismiss（端點 20 → 22）
app.include_router(ingest_jobs.router)


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}


@app.get("/")
def root() -> RedirectResponse:
    """根路徑直接轉到上傳頁（2026-08-20 使用者指示新增；端點數由 3 成 4）。"""
    return RedirectResponse(url="/ui/upload.html")


# 極簡網頁介面【design.md v4】：把 app/static/ 這個資料夾直接當靜態檔案送出。
# 網址會變成 /ui/upload.html 與 /ui/ask.html。
# 這一行不是新增 API 端點，只是「把檔案原封不動送出去」。
# Path(__file__).resolve().parent ＝ app/ 這個資料夾的絕對路徑，
# 這樣不管在哪個目錄啟動 uvicorn 都找得到 static/。
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR), name="ui")
