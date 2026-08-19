"""FastAPI app 組裝：掛上 photos router（ask router 到 Phase 11 才掛）。"""

from fastapi import FastAPI

from app.api.routers import photos

app = FastAPI(title="personalDocAI")

app.include_router(photos.router)
# TODO(Phase 11)：app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}
