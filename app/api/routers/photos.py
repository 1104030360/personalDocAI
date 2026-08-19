"""上傳照片的 router：POST /photos。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core import config
from app.dependencies import get_vlm
from app.services import vlm_service

router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201)
def upload_photo(
    file: UploadFile = File(...),
    # Depends(get_vlm)＝請框架給一個會看圖的。正式是 OllamaVLM；
    # 只有 pytest 才會覆寫成 FakeVLM。型別寫 VLMClient 只是合約，追程式看 OllamaVLM。
    vlm: vlm_service.VLMClient = Depends(get_vlm),
) -> dict:
    """上傳照片：格式檢查 → 看圖 →（Phase 6）轉向量、寫入、回 201。"""
    # ① 格式檢查
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    # 原始照片只存在這個變數裡，函式結束就消失——絕不寫進磁碟或資料庫
    image_bytes = file.file.read()

    # ② 看圖
    understanding = vlm.understand(image_bytes, file.content_type)
    if not understanding.understood or not understanding.text.strip():
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )

    # TODO(Phase 6)：indexing_service 轉向量 → photo_repository 寫入 → 回 201 正式回應
    return {
        "understood": True,
        "text": understanding.text,
        "category": understanding.category,
        "location": understanding.location,
        "items": understanding.items,
        "content_time": understanding.content_time,
    }
