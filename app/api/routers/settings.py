"""AI 後端開關：GET／PUT /settings/ai-backend（2026-08-22 產品負責人指示新增）。

上傳頁與問問題頁頁首的「本機｜雲端」開關打的就是這兩支——同一個系統狀態，
在哪一頁撥都一樣。撥到雲端＝**所有 gemma4 呼叫**改走 Ollama Cloud：
看圖（單圖、PDF 逐頁、無線鏡頭共用 get_vlm）、詢問的路由與回答
（get_router／get_answerer）、實體建議（get_entity_suggester）。
embeddings **不在此列、一律本機**——向量必須跟資料庫裡既有的 bge-m3 同源。

狀態存在 config.AI_BACKEND（記憶體，重啟回「本機」）；本檔零 SQL、零 AI 呼叫。
"""

from fastapi import APIRouter, HTTPException

from app.core import config
from app.schemas.settings import AiBackendOut, AiBackendUpdate

router = APIRouter(tags=["settings"])


def _current() -> AiBackendOut:
    return AiBackendOut(
        backend=config.AI_BACKEND,
        cloud_configured=bool(config.OLLAMA_API_KEY),
    )


@router.get("/settings/ai-backend", response_model=AiBackendOut)
def get_ai_backend() -> AiBackendOut:
    """AI 現在走哪個後端。頁面載入時用這支畫出開關的初始位置。"""
    return _current()


@router.put("/settings/ai-backend", response_model=AiBackendOut)
def set_ai_backend(request: AiBackendUpdate) -> AiBackendOut:
    """撥開關。

    切到雲端但 .env 沒填 OLLAMA_API_KEY → 422、開關不動——寧可在這裡把話說清楚，
    也不要讓使用者用到一半才拿到一個 401 偽裝成的失敗。
    """
    if request.backend == "cloud" and not config.OLLAMA_API_KEY:
        raise HTTPException(
            status_code=422,
            detail="尚未設定 OLLAMA_API_KEY，無法切換到雲端（請在 .env 填入後重啟伺服器）",
        )
    config.AI_BACKEND = request.backend
    return _current()
