"""照片 router：POST /photos（上傳）＋ GET /photos/{id}/thumbnail、/image（讀圖）＋ PATCH /photos/{id}/folder（歸類）。"""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.entity import EntityOut
from app.schemas.photo import (
    AssignFolderRequest,
    AssignFolderResponse,
    FolderOut,
    PdfUploadResponse,
    PhotoMetadata,
    TaskSuggestion,
    UploadResponse,
)
from app.services import indexing_service, pdf_service, storage_service, vlm_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["photos"])

# PDF 的每一頁渲染出來都是 PNG，之後就完全是一次普通的單圖上傳
#（原圖存成 .png、讀圖端點照舊，不必為 PDF 另開一條路）
PDF_PAGE_CONTENT_TYPE = "image/png"

# 看圖 prompt 要注入幾筆「建議被你改掉」的糾錯例子（design3.md D11／§7 的暫定 N＝5）。
# 刻意寫在這裡而不是 config：它是產品的暫定值，不是部署時要調的環境設定。
FEW_SHOT_CORRECTIONS = 5


def _folder_out(folder: dict) -> FolderOut:
    """把 repository 回來的資料夾 dict 挑出三個欄位。

    repository 的 dict 還帶 is_inbox 與 photo_count，
    這裡明確只取三個，回應長什麼樣一眼看得出來。
    """
    return FolderOut(
        id=folder["id"], name=folder["name"], description=folder["description"]
    )


def _entity_out(entity: dict) -> EntityOut:
    """repository 回來的實體 dict 剛好就是三個欄位，直接展開。"""
    return EntityOut(**entity)


def _task_suggestion(
    understanding: vlm_service.PhotoUnderstanding,
) -> TaskSuggestion | None:
    """把 VLM 的待辦欄位整理成建議；沒有可辦的事就回 None（design3.md D13）。

    標題是空的（沒填或只有空白）＝這張照片沒有待辦，前端的待辦彈窗就不開。
    到期日沿用 parse_content_time 的寬容解析：模型回「下週三」之類推不出來的東西
    只是少了一個日期，**絕不可以讓整個上傳失敗**（與 content_time 同一個原則）。
    """
    if not understanding.task_title or not understanding.task_title.strip():
        return None
    due = vlm_service.parse_content_time(understanding.task_due)
    return TaskSuggestion(
        title=understanding.task_title.strip(),
        due=due.isoformat() if due else None,
    )


@router.post(
    "/photos", status_code=201, response_model=UploadResponse | PdfUploadResponse
)
def upload_photo(
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse | PdfUploadResponse:
    """上傳一張照片，或一份 PDF（一頁當成一張照片，design3.md D7）。

    只有這一層知道「使用者傳的是圖還是 PDF」：PDF 先被拆成一頁一張 PNG，
    之後每一頁走的都是與單圖完全相同的入庫流程（_ingest_image），
    所以單圖的行為與回應一字不變。

    回應有兩種長相：單圖回 UploadResponse，PDF 回 PdfUploadResponse。
    """
    # ① 格式檢查
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    # 讀出整個上傳檔的位元組：圖就直接拿去看圖與存檔，PDF 則先拿去拆頁
    #（「不儲存原始照片檔」是 v4 的舊決策，design1.md §1.1 已明示推翻）
    upload_bytes = file.file.read()

    # 資料夾、實體與糾錯例子在這裡各讀一次就好：PDF 每一頁都要用同一份注入 prompt，
    # 而上傳過程中不會有人新增資料夾或實體（自創都是彈窗的事，發生在這之後），
    # 也不會多出糾錯（糾錯是 PATCH 定案時才記的）。
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)

    if file.content_type == config.PDF_CONTENT_TYPE:
        return _ingest_pdf(
            upload_bytes, vlm, embeddings, now, folders, entities, corrections
        )

    return _ingest_image(
        upload_bytes,
        file.content_type,
        vlm,
        embeddings,
        now,
        folders,
        entities,
        corrections,
    )


def _ingest_image(
    image_bytes: bytes,
    content_type: str,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: datetime | None,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
) -> UploadResponse:
    """一張圖的完整入庫：看圖 → 轉向量 → 寫入「未分類」→ 存檔 → 回應。

    照片一律先掛在「未分類」；VLM 給的類別只是建議（回應的 suggested_folder），
    真正的歸類由使用者在彈窗確認後呼叫 PATCH /photos/{id}/folder（Phase 21）。
    實體與待辦同理：只出現在回應（suggested_entity／suggested_task），
    要等使用者在彈窗 2／3 按下去才落庫（design3.md D3「人確認才落庫」）。
    全程在同一個請求內完成；任何一步失敗＝整筆不存在、也不留檔。

    PDF 的每一頁也是呼叫這裡（Phase 28），所以「看不懂＝422」的語意兩邊共用：
    單圖的 422 直接回給使用者，PDF 則由 _ingest_pdf 接住、記成跳過的頁。
    """
    # ② 看圖（把現有資料夾、實體清單與最近的糾錯例子注入 prompt——
    #    design1.md §8、design3.md D12、D11）
    #    仍然只有這一次看圖呼叫，沒有第二個分類模型：實體與待辦是同一次輸出多出來的欄位。
    #    起訖各記一筆 log：真模型一張圖要看數分鐘，終端機沒有動靜時分不出
    #    「還在算」與「卡死」，這兩行就是給人盯進度用的。
    logger.info("AI 看圖開始：%s，%d bytes", content_type, len(image_bytes))
    看圖起點 = time.monotonic()
    understanding = vlm.understand(
        image_bytes, content_type, folders, entities, corrections
    )
    看圖秒數 = time.monotonic() - 看圖起點
    if not understanding.understood or not understanding.text.strip():
        logger.info("AI 看圖完成（%.1f 秒）：看不懂 → 422 不儲存", 看圖秒數)
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )
    logger.info(
        "AI 看圖完成（%.1f 秒）：text %d 字、建議類別「%s」、建議實體「%s」、待辦「%s」",
        看圖秒數,
        len(understanding.text),
        understanding.category,
        understanding.entity,
        understanding.task_title,
    )

    # ★③ VLM 給的類別只當「建議」：夾回清單內，清單外一律變「未分類」
    #    next(...)＝從清單裡挑出第一個符合條件的元素。
    #    收件箱用 is_inbox 這個欄位找，不用字串比對——資料庫欄位比字串常數可靠。
    #    兩個 next() 都保證找得到（schema 有六筆種子，clamp 只會回清單內的名稱）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    inbox = next(folder for folder in folders if folder["is_inbox"])
    suggested = next(folder for folder in folders if folder["name"] == suggested_name)

    #    建議要**存進照片**（Phase 35 已釐清 B）：定案時才有東西可以比對「猜的 vs 選的」，
    #    待決定分頁也才畫得出選項①。建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL，
    #    這種照片之後一律不算糾錯（沒建議不是猜錯）。
    suggested_category = None if suggested["is_inbox"] else suggested_name

    #    實體的建議同樣要夾，但沒有「未分類」這種保底：清單外或都不像 → None，
    #    實體彈窗那時就只剩②改選現有／③自創／④不釘（design3.md §2、D12）。
    suggested_entity = vlm_service.clamp_entity(understanding.entity, entities)

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
        suggested_category=suggested_category,
    )
    photo_id = row["id"]

    # ⑤ 存原圖與縮圖，再把路徑補回那一列（design1.md §6）
    #    這三步不是一條 SQL，所以沒有資料庫交易可以幫忙 rollback：
    #    任何一步失敗就自己把檔案與資料列清乾淨，再把原始錯誤往外丟（不吞錯 → 500）。
    original_path: str | None = None
    thumbnail_path: str | None = None
    try:
        original_path = storage_service.save_original(
            photo_id, image_bytes, content_type
        )
        thumbnail_path = storage_service.make_thumbnail(
            photo_id, image_bytes, content_type
        )
        photo_repository.update_photo_paths(
            photo_id,
            original_path=original_path,
            thumbnail_path=thumbnail_path,
            content_type=content_type,
        )
    except Exception:
        # remove_if_exists 吃得下 None（那一步還沒跑到就失敗了）與「檔案本來就不在」
        storage_service.remove_if_exists(original_path)
        storage_service.remove_if_exists(thumbnail_path)
        photo_repository.delete_photo(photo_id)
        # 原始錯誤原封不動往外丟（re-raise），讓框架回 500 並在 log 留下 traceback
        raise

    logger.info("照片已入庫：photo_id=%d（先進「未分類」，等使用者歸類）", photo_id)

    # ★⑥ 回 201：把三個彈窗要用的東西一次帶齊（抽屜、實體、待辦）
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
        suggested_entity=(
            _entity_out(suggested_entity) if suggested_entity else None
        ),
        entities=[_entity_out(entity) for entity in entities],
        suggested_task=_task_suggestion(understanding),
    )


def _ingest_pdf(
    pdf_bytes: bytes,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: datetime | None,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
) -> PdfUploadResponse:
    """一份 PDF 的入庫：逐頁渲染成 PNG，每一頁當成一張照片（design3.md D7）。

    PDF 原始檔不留——照片的「原圖」就是該頁渲染出來的 PNG。
    整份讀不開＝使用者給了壞檔（422，什麼都沒存）；
    個別頁看不懂則只跳過那一頁，其餘頁照樣入庫，跳過的頁碼回報給使用者。
    """
    try:
        page_images = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        raise HTTPException(status_code=422, detail="無法讀取 PDF 檔案")

    created: list[UploadResponse] = []
    skipped_pages: list[int] = []
    for page_number, page_bytes in enumerate(page_images, start=1):
        try:
            created.append(
                _ingest_image(
                    page_bytes,
                    PDF_PAGE_CONTENT_TYPE,
                    vlm,
                    embeddings,
                    now,
                    folders,
                    entities,
                    corrections,
                )
            )
        except HTTPException as error:
            # 只吞「這一頁看不懂」（422）。存檔失敗、資料庫掛掉之類的一律往外丟，
            # 維持單圖既有的語意：伺服器出事就是 500，不可以偽裝成「跳過一頁」。
            if error.status_code != 422:
                raise
            skipped_pages.append(page_number)

    if not created:
        # 一頁都沒成功＝這次上傳什麼都沒存，跟單圖看不懂一樣回 422
        raise HTTPException(
            status_code=422, detail="PDF 每一頁都無法理解，未儲存任何資料"
        )

    return PdfUploadResponse(
        pages=len(page_images), created=created, skipped_pages=skipped_pages
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
