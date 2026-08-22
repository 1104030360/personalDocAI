"""FastAPI app 組裝：掛上五個 router ＋ 極簡網頁介面（靜態檔案）。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import ask, entities, folders, photos, tasks

app = FastAPI(title="PersonalDocAI")

app.include_router(photos.router)
app.include_router(ask.router)
app.include_router(folders.router)
app.include_router(entities.router)
app.include_router(tasks.router)


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
