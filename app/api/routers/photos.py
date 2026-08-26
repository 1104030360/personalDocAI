"""照片 router：POST /photos（受理入庫任務，202）
＋ GET /photos/{id}/thumbnail、/image（讀圖）＋ GET /photos/{id}（詳情）
＋ PATCH /photos/{id}/folder（歸類）。

增量五之後這個檔案**不看圖、不寫照片**：看圖與入庫全部在
app/services/ingest_job.py 的 run_ingest_job()（由 worker 執行）。
這裡只剩「收下檔案排隊」「把已經存好的東西讀出來」「歸類」三件事。
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import (
    get_embeddings,
    get_job_store,
    get_task_dispatcher,
    TaskDispatcher,
)
from app.repositories import photo_repository
from app.schemas.ingest_job import IngestAcceptedResponse
from app.schemas.photo import (
    AssignFolderRequest,
    AssignFolderResponse,
    FolderOut,
    PhotoDetailOut,
    PhotoMetadata,
)
from app.services import (
    ai_timing,
    indexing_service,
    staging_service,
    storage_service,
)
from app.services.ingest_job_store import JobStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["photos"])


def _folder_out(folder: dict) -> FolderOut:
    """把 repository 回來的資料夾 dict 挑出三個欄位。

    repository 的 dict 還帶 is_inbox 與 photo_count，
    這裡明確只取三個，回應長什麼樣一眼看得出來。
    """
    return FolderOut(
        id=folder["id"], name=folder["name"], description=folder["description"]
    )


@router.post("/photos", status_code=202, response_model=IngestAcceptedResponse)
def upload_photo(
    file: UploadFile = File(...),
    store: JobStore = Depends(get_job_store),
    dispatcher: TaskDispatcher = Depends(get_task_dispatcher),
) -> IngestAcceptedResponse:
    """收下一個檔案並排進佇列（增量五 D7）。**這裡不看圖、不寫資料庫。**

    這一支端點必須**很快**：只做「格式對不對」「把檔案放好」「記一筆任務」三件事。
    真正花時間的看圖與寫入在 worker（app/services/ingest_job.py 的 run_ingest_job）。

    ⚠ 202 不是 201：回應裡沒有照片 id、沒有 text、沒有建議資料夾。
      這一刻 photo 表**一列都沒有多**（design5.md §4.2）。

    圖與 PDF 走同一條路：分流是 worker 依 job 的 content_type 做的，
    這裡不必知道差別（PDF 的頁數要拆開才知道，而拆頁是慢動作）。
    """
    # ① 格式檢查——唯一會讓這支端點失敗的「使用者錯誤」。
    #    排在最前面：不建 job、不寫 staging、連 data/ 都不會被建出來
    #    （design5.md §8 第 1 列）。
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    upload_bytes = file.file.read()
    return _accept_upload(
        upload_bytes,
        filename=file.filename or "未命名",
        content_type=file.content_type,
        store=store,
        dispatcher=dispatcher,
        source="upload",
    )


def _accept_upload(
    upload_bytes: bytes,
    *,
    filename: str,
    content_type: str,
    store: JobStore,
    dispatcher: TaskDispatcher,
    source: str,
) -> IngestAcceptedResponse:
    """把「收下的檔」變成一筆排隊中的任務，回 202 的內容。

    ★★ 順序鐵律（把 ①〜④ 的順序調換 = 製造 bug）★★
      ① 先產 job_id      ── staging 的檔名要用它，所以它得最先決定
      ② 再寫 staging     ── 檔案先落地
      ③ 再建 job         ── 任務清單上才看得到這一筆
      ④ 最後才入列       ── 有人來做的那一刻，前面兩樣一定都準備好了

    反過來做（先入列再寫 staging）會出現「worker 已經開始做、但檔案還沒寫完」
    的競爭——worker 讀到半個檔或根本讀不到檔，看起來像隨機失敗。

    ②③④ 任何一步失敗 → **把 staging 與 job 都清掉**再把原始錯誤往外丟
    （框架會回 500，log 留 traceback）。design5.md §8 第 8 列講的就是這件事：
    Redis 掛掉的時候，不要在磁碟上留一個沒有人會來撿的暫存檔。
    """
    # uuid4().hex ＝ 32 個十六進位字元。為什麼不用資料庫序號（見 §7 陷阱 3）：
    # 這一刻我們**刻意不碰資料庫**，而序號要先 INSERT 才拿得到；
    # 而且 job 住在 Redis／記憶體，本來就沒有序號這種東西。
    job_id = uuid4().hex

    try:
        staging_service.save_staging(job_id, content_type, upload_bytes)
        store.create(
            job_id=job_id,
            filename=filename,
            content_type=content_type,
            # D14：把「現在開關撥在哪」拍成快照存進任務。worker 是另一個行程，
            # 讀不到這個行程記憶體裡的 config.AI_BACKEND；而且使用者中途把開關
            # 撥回本機時，已經排隊的任務不該跟著改道。
            ai_backend=config.AI_BACKEND,
            source=source,
        )
        dispatcher.dispatch(job_id)
    except Exception:
        # 兩個清理動作都必須「本來就不在也不炸」：
        #   remove_staging 比照 storage_service.remove_if_exists
        #     （save_staging 若寫到一半就炸，磁碟上可能有半個檔，也一起清）
        #   store.delete  對不存在的 job_id 要安靜（Phase 57 的 pop(…, None) 語意）
        # 清掉 job 的理由：入列失敗卻留著一筆 queued，進度面板會出現一列
        # 永遠不會動的幽靈任務，而且它連 dismiss 都按不掉（只准 dismiss failed）。
        staging_service.remove_staging(job_id, content_type)
        store.delete(job_id)
        raise

    logger.info(
        "已受理入庫任務：job_id=%s filename=%s content_type=%s source=%s backend=%s",
        job_id, filename, content_type, source, config.AI_BACKEND,
    )
    return IngestAcceptedResponse(
        job_id=job_id, filename=filename, content_type=content_type
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


@router.get("/photos/{photo_id}", response_model=PhotoDetailOut)
def get_photo_detail(photo_id: int) -> PhotoDetailOut:
    """一張照片的完整說明（design4.md §4.4）。唯讀：不看圖、不重算向量、不寫任何東西。

    只要資料庫有這一列就 200——**不管檔案還在不在磁碟上**。
    「路徑 NULL 或檔案不見了就 404」那是 /image 與 /thumbnail 的規則，
    因為那兩支是真的要開檔案；這一支只回 JSON，跟磁碟無關。
    圖載不出來由前端的 <img> onerror 降級成占位，不該讓整個窗變成 404。
    """
    row = photo_repository.fetch_photo(photo_id)
    if row is None:
        raise HTTPException(status_code=404, detail="找不到照片")

    return PhotoDetailOut(
        id=row["id"],
        text=row["text"],
        metadata=PhotoMetadata(
            category=row["category"],
            location=row["location"],
            items=row["items"],
            content_time=(
                row["content_time"].isoformat() if row["content_time"] else None
            ),
        ),
        # 有存過檔才給網址；沒有就是 None → JSON null → 前端畫灰底占位
        thumbnail_url=(
            f"/photos/{photo_id}/thumbnail" if row["thumbnail_path"] else None
        ),
        image_url=f"/photos/{photo_id}/image" if row["original_path"] else None,
        uploaded_at=row["uploaded_at"],
    )


def _record_correction_if_changed(photo: dict, chosen: str) -> None:
    """定案的資料夾與上傳當下的建議不同時，留一筆糾錯素材（design3.md D11）。

    算糾錯（已釐清 D）：②改選現有、③自建，且選定名稱 ≠ 存下來的建議。
    不算：①採用建議（名稱相等，這裡自然就跳過，不必特判），
          以及 suggested_category 是空的——那代表 clamp 失敗＝**根本沒有建議**，
          不是猜錯（上傳時建議若是「未分類」就存 NULL，所以這一個檢查就夠了）。
    比對用 casefold()：使用者自建「project x」而建議是「Project X」時算同一個，
          不該被當成糾錯（與 find_folder_by_name 的大小寫不敏感是同一套規矩）。
          這其實是**防禦性寫法**：正常路徑下 chosen 來自 folder["name"]、
          suggested 來自存進 photo 的建議名稱，兩邊都是資料夾的正規名稱；
          大小寫變體早在 find_folder_by_name 那關就被 409 擋掉了（自建重名時），
          實務上根本走不到「同名不同大小寫」這條分支——casefold() 只是多一層保險，
          就算哪天上游的正規化規則變了，這裡也不會誤記一筆假糾錯。

    糾錯只是**學習素材**，不是使用者交辦的事：寫不進去就記一行 warning 算了，
    絕不可以讓已經成功的歸類變成 500（這是本函式唯一吞例外的理由）。
    """
    suggested = photo["suggested_category"]
    if not suggested or suggested.casefold() == chosen.casefold():
        return
    try:
        photo_repository.record_folder_correction(
            suggested=suggested, chosen=chosen, photo_text=photo["text"]
        )
    except Exception:
        logger.warning("糾錯素材寫入失敗，歸類本身不受影響", exc_info=True)


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

    # ①.5 定案不可逆（design2.md D3）：只有還在收件箱（待決定）的照片可以歸檔。
    #      已進真資料夾的照片＝定案，任何再歸類（含自建路徑）一律 409——
    #      這一步是唯讀檢查，維持「檢查在前、寫入在後」的既有排序。
    current_folder = photo_repository.get_folder(photo["folder_id"])
    if not current_folder["is_inbox"]:
        raise HTTPException(status_code=409, detail="照片已定案，不可再變更資料夾")

    # ②／③ 決定 category 要用的名稱（request 已保證 folder_id 與 name 恰好一個有值）。
    #    這一段只查不寫：自建那條路的 create_folder 刻意排在 embedding 之後（見 ⑤），
    #    embedding 失敗時才不會留下一個沒有照片的空資料夾。
    if payload.folder_id is not None:
        folder = photo_repository.get_folder(payload.folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="找不到資料夾")
        # 定案目標必須是真資料夾（design2.md D3/D7）：「歸」回收件箱不合法
        if folder["is_inbox"]:
            raise HTTPException(status_code=422, detail="不能歸檔到收件箱")
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
    with ai_timing.log_ai(
        "embed", target=indexing_service.embedding_timing_target(embeddings)
    ):
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

    # ⑦ 歸類成功了才輪到糾錯（design3.md D11）：使用者這次選的和上傳當下的建議不一樣，
    #    就留一筆 few-shot 素材給下一次看圖。放在最後一步是刻意的——
    #    409／422／embedding 失敗那幾條路根本走不到這裡，自然不會亂記。
    _record_correction_if_changed(row, folder["name"])

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
