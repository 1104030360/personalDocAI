"""資料夾瀏覽的 router：GET /folders、GET /folders/{folder_id}。

兩個端點都是唯讀、都沒有 AI。SQL 一律在 repository，本檔只做
「呼叫函式 → 換成回應格式」。design1.md §7.4 明訂不做「列出全部照片」的端點。
"""

from fastapi import APIRouter, HTTPException

from app.repositories import photo_repository
from app.schemas.folder import FolderDetailResponse, FolderWithCount, PhotoSummary

router = APIRouter(tags=["folders"])


@router.get("/folders", response_model=list[FolderWithCount])
def list_folders() -> list[FolderWithCount]:
    """全部資料夾（含 description 與照片張數），照 id 排序。"""
    # repository 回的每個 dict 的鍵，剛好就是 FolderWithCount 的五個欄位
    return [FolderWithCount(**row) for row in photo_repository.list_folders()]


@router.get("/folders/{folder_id}", response_model=FolderDetailResponse)
def get_folder(folder_id: int) -> FolderDetailResponse:
    """某個資料夾 ＋ 裡面每張照片的摘要（新的在前）。找不到資料夾回 404。"""
    folder_row = photo_repository.get_folder(folder_id)
    if folder_row is None:
        raise HTTPException(status_code=404, detail="找不到資料夾")

    photos = [
        PhotoSummary(
            id=row["id"],
            # 有存過縮圖檔才給網址；舊資料沒有路徑 → None → JSON null
            thumbnail_url=(
                f"/photos/{row['id']}/thumbnail" if row["thumbnail_path"] else None
            ),
            text=row["text"],
            uploaded_at=row["uploaded_at"],
        )
        for row in photo_repository.list_photos_in_folder(folder_id)
    ]

    return FolderDetailResponse(folder=FolderWithCount(**folder_row), photos=photos)
