"""照片 router：POST /photos（上傳）＋ GET /photos/{id}/thumbnail、/image（讀圖）＋ PATCH /photos/{id}/folder（歸類）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.photo import (
    AssignFolderRequest,
    AssignFolderResponse,
    FolderOut,
    PhotoMetadata,
    UploadResponse,
)
from app.services import indexing_service, storage_service, vlm_service

router = APIRouter(tags=["photos"])


def _folder_out(folder: dict) -> FolderOut:
    """把 repository 回來的資料夾 dict 挑出三個欄位。

    repository 的 dict 還帶 is_inbox 與 photo_count，
    這裡明確只取三個，回應長什麼樣一眼看得出來。
    """
    return FolderOut(
        id=folder["id"], name=folder["name"], description=folder["description"]
    )


@router.post("/photos", status_code=201, response_model=UploadResponse)
def upload_photo(
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse:
    """上傳照片：格式檢查 → 看圖 → 轉向量 → 寫入「未分類」→ 存檔 → 回 201。

    照片一律先掛在「未分類」；VLM 給的類別只是建議（回應的 suggested_folder），
    真正的歸類由使用者在彈窗確認後呼叫 PATCH /photos/{id}/folder（Phase 21）。
    全程在同一個請求內完成；任何一步失敗＝整筆不存在、也不留檔。
    """
    # ① 格式檢查
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    # 讀出整個上傳檔的位元組：看圖、轉向量用它，第 ⑤ 段也用它寫原圖與縮圖
    #（「不儲存原始照片檔」是 v4 的舊決策，design1.md §1.1 已明示推翻）
    image_bytes = file.file.read()

    # ② 看圖（把現有資料夾清單當變數注入 prompt——design1.md §8）
    #    仍然只有這一次看圖呼叫，沒有第二個分類模型。
    folders = photo_repository.list_folders()
    understanding = vlm.understand(image_bytes, file.content_type, folders)
    if not understanding.understood or not understanding.text.strip():
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )

    # ★③ VLM 給的類別只當「建議」：夾回清單內，清單外一律變「未分類」
    #    next(...)＝從清單裡挑出第一個符合條件的元素。
    #    收件箱用 is_inbox 這個欄位找，不用字串比對——資料庫欄位比字串常數可靠。
    #    兩個 next() 都保證找得到（schema 有六筆種子，clamp 只會回清單內的名稱）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    inbox = next(folder for folder in folders if folder["is_inbox"])
    suggested = next(folder for folder in folders if folder["name"] == suggested_name)

    # ★④ 合併與寫入一律用「未分類」——上傳當下的向量就是未分類版本（design1.md §2）
    content_time = vlm_service.parse_content_time(understanding.content_time)
    content_time_text = content_time.isoformat() if content_time else None
    document = indexing_service.build_document(
        text=understanding.text,
        category=inbox["name"],
        location=understanding.location,
        items=understanding.items,
        content_time=content_time_text,
    )
    embedding = indexing_service.embed_document(embeddings, document)

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox["name"],
        location=understanding.location,
        items=understanding.items,
        content_time=content_time,
        embedding=embedding,
        uploaded_at=now,
    )
    photo_id = row["id"]

    # ⑤ 存原圖與縮圖，再把路徑補回那一列（design1.md §6）
    #    這三步不是一條 SQL，所以沒有資料庫交易可以幫忙 rollback：
    #    任何一步失敗就自己把檔案與資料列清乾淨，再把原始錯誤往外丟（不吞錯 → 500）。
    original_path: str | None = None
    thumbnail_path: str | None = None
    try:
        original_path = storage_service.save_original(
            photo_id, image_bytes, file.content_type
        )
        thumbnail_path = storage_service.make_thumbnail(
            photo_id, image_bytes, file.content_type
        )
        photo_repository.update_photo_paths(
            photo_id,
            original_path=original_path,
            thumbnail_path=thumbnail_path,
            content_type=file.content_type,
        )
    except Exception:
        # remove_if_exists 吃得下 None（那一步還沒跑到就失敗了）與「檔案本來就不在」
        storage_service.remove_if_exists(original_path)
        storage_service.remove_if_exists(thumbnail_path)
        photo_repository.delete_photo(photo_id)
        # 原始錯誤原封不動往外丟（re-raise），讓框架回 500 並在 log 留下 traceback
        raise

    # ★⑥ 回 201：把彈窗要用的四樣東西一起帶回去
    return UploadResponse(
        id=photo_id,
        text=row["text"],
        metadata=PhotoMetadata(
            category=row["category"],
            location=row["location"],
            items=row["items"],
            content_time=row["content_time"].isoformat() if row["content_time"] else None,
        ),
        folder=_folder_out(inbox),
        suggested_folder=_folder_out(suggested),
        folders=[_folder_out(folder) for folder in folders],
        thumbnail_url=f"/photos/{photo_id}/thumbnail",
    )


def _send_photo_file(photo_id: int, path_column: str) -> FileResponse:
    """把某一列照片的某個路徑欄位指向的檔案送出去。

    三種情況都回 404（design1.md §7.4、§12）：
      1. 沒有這一列
      2. 有這一列但路徑欄位是 NULL ← 遷移進來的舊照片走這條，前端顯示占位
      3. 有路徑但磁碟上的檔案不見了
    """
    row = photo_repository.fetch_photo(photo_id)
    if row is None or not row[path_column]:
        raise HTTPException(status_code=404, detail="找不到照片檔案")

    file_path = storage_service.absolute_path(row[path_column])
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="找不到照片檔案")

    # FileResponse＝把磁碟上的檔案直接送出去；media_type 告訴瀏覽器這是圖片
    return FileResponse(file_path, media_type=row["content_type"])


@router.get("/photos/{photo_id}/thumbnail")
def get_photo_thumbnail(photo_id: int) -> FileResponse:
    """縮圖（長邊最多 512px）。瀏覽頁的縮圖牆用這個。"""
    return _send_photo_file(photo_id, "thumbnail_path")


@router.get("/photos/{photo_id}/image")
def get_photo_image(photo_id: int) -> FileResponse:
    """原圖。使用者想看大圖時用這個。"""
    return _send_photo_file(photo_id, "original_path")


@router.patch("/photos/{photo_id}/folder", response_model=AssignFolderResponse)
def assign_folder(
    photo_id: int,
    payload: AssignFolderRequest,
    embeddings: Embeddings = Depends(get_embeddings),
) -> AssignFolderResponse:
    """把照片歸到某個資料夾：採用現有的，或當場自建一個（design1.md §7.2）。

    順序是刻意排的：檢查與 embedding 重算全部在前面，寫資料庫的動作全部在最後。
    embedding 算失敗時直接 500，資料庫完全沒動——照片那一列的
    folder_id／category／embedding 三欄原封不動，也不會留下任何空資料夾。
    """
    # ① 這張照片存在嗎（先查照片再查資料夾，錯誤訊息才符合直覺）
    photo = photo_repository.fetch_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="找不到照片")

    # ②／③ 決定 category 要用的名稱（request 已保證 folder_id 與 name 恰好一個有值）。
    #    這一段只查不寫：自建那條路的 create_folder 刻意排在 embedding 之後（見 ⑤），
    #    embedding 失敗時才不會留下一個沒有照片的空資料夾。
    if payload.folder_id is not None:
        folder = photo_repository.get_folder(payload.folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="找不到資料夾")
        category = folder["name"]
    else:
        # 自建：重名交由這裡擋（大小寫不敏感），資料庫的 UNIQUE 是最後防線。
        # category 直接用請求裡的 name——Pydantic 驗證器已去掉前後空白，
        # 跟稍後 create_folder 存進去的名稱一字不差，不必先建資料夾才知道要填什麼。
        if photo_repository.find_folder_by_name(payload.name) is not None:
            raise HTTPException(status_code=409, detail="資料夾名稱已存在")
        category = payload.name

    # ④ 先把向量整條重算（design1.md §7.3）——唯一會呼叫 AI、可能失敗的一步。
    #    text 與另外三個欄位原封不動，只有 category 換掉。
    #    走到這裡為止資料庫一個字都沒寫：這裡炸掉（500）就等於「什麼都沒發生」。
    content_time = photo["content_time"]
    document = indexing_service.build_document(
        text=photo["text"],
        category=category,
        location=photo["location"],
        items=list(photo["items"]),
        content_time=content_time.isoformat() if content_time else None,
    )
    embedding = indexing_service.embed_document(embeddings, document)

    # ⑤ embedding 到手了，才開始動資料庫：自建那條路此時才真的建資料夾
    if payload.folder_id is None:
        folder = photo_repository.create_folder(payload.name, payload.description)

    # ⑥ 一條 UPDATE 同時寫 folder_id、category、embedding
    row = photo_repository.update_photo_folder(
        photo_id,
        folder_id=folder["id"],
        category=folder["name"],
        embedding=embedding,
    )

    return AssignFolderResponse(
        id=row["id"],
        folder=_folder_out(folder),
        metadata=PhotoMetadata(
            category=row["category"],
            location=row["location"],
            items=row["items"],
            content_time=row["content_time"].isoformat() if row["content_time"] else None,
        ),
    )
