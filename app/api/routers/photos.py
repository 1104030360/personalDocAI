"""上傳照片的 router：POST /photos。"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.photo import PhotoMetadata, UploadResponse
from app.services import indexing_service, vlm_service

router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201, response_model=UploadResponse)
def upload_photo(
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse:
    """上傳照片：格式檢查 → 看圖 → 轉向量 → 寫入 → 回 201。

    全程在同一個請求內完成；任何一步失敗＝整筆不存在。
    """
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

    # ③ 合併成 Document，再轉成向量
    content_time = vlm_service.parse_content_time(understanding.content_time)
    content_time_text = content_time.isoformat() if content_time else None
    document = indexing_service.build_document(
        text=understanding.text,
        category=understanding.category,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time_text,
    )
    embedding = indexing_service.embed_document(embeddings, document)

    # ④ 一條 INSERT 寫入
    row = photo_repository.insert_photo(
        text=understanding.text,
        category=understanding.category,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time,
        embedding=embedding,
        uploaded_at=now,
    )

    # ⑤ 回 201
    return UploadResponse(
        id=row["id"],
        text=row["text"],
        metadata=PhotoMetadata(
            category=row["category"],
            location=row["location"],
            items=row["items"],
            content_time=row["content_time"].isoformat() if row["content_time"] else None,
        ),
    )
