"""上傳照片的 router：POST /photos。

router 層的職責：收請求、檢查輸入、把失敗翻成 HTTP 狀態碼。
真正的商業邏輯（看圖、轉向量）在 services，資料寫入在 repositories。
"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core import config

# prefix 不設，因為端點路徑就是 /photos；tags 只影響 /docs 的分組顯示
router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201)
def upload_photo(file: UploadFile = File(...)) -> dict:
    """上傳照片。

    第一關：檔案格式必須是 JPEG 或 PNG，否則回 415 且不做任何後續處理。
    （刻意不檢查檔案大小——已釐清的決策是「不設上限」。）
    """
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    image_bytes = file.file.read()

    # TODO(Phase 5)：接上 services/vlm_service.py 看圖
    # TODO(Phase 6)：接上 services/indexing_service.py 轉向量、
    #                repositories/photo_repository.py 寫入，
    #                並把下面的佔位回應換成 schemas/photo.py 的 UploadResponse
    return {
        "accepted": True,
        "content_type": file.content_type,
        "size": len(image_bytes),
    }
