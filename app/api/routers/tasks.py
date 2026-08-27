"""待辦的 router：POST /photos/{photo_id}/task、GET /tasks（design3.md D13）。

SQL 一律在 repository，本檔只做「呼叫函式 → 換成回應格式」。
兩個端點都**不碰 AI**：VLM 的待辦建議在上傳當下就一起給完了（Phase 30），
這裡只負責「人確認之後寫進去」與「列出來看」——不問模型、不重算 embedding。
"""

from datetime import date

from fastapi import APIRouter, HTTPException

from app.repositories import photo_repository
from app.schemas.task import CreateTaskRequest, TaskOut

router = APIRouter(tags=["tasks"])


def _task_out(task: dict, thumbnail_path: str | None) -> TaskOut:
    """把 repository 回來的一列待辦換成回應格式。

    thumbnail_path 只在這裡用來判斷「這張照片有沒有縮圖」，換算成網址之後就丟掉——
    硬碟路徑一個字都不外送（鏡射 folders 端點的算法，design1.md §10）。
    """
    return TaskOut(
        id=task["id"],
        photo_id=task["photo_id"],
        title=task["title"],
        # 資料庫給的是 date 物件，外送成 ISO 字串；沒到期日 → None → JSON null
        due_date=task["due_date"].isoformat() if task["due_date"] else None,
        thumbnail_url=(f"/photos/{task['photo_id']}/thumbnail" if thumbnail_path else None),
    )


@router.post("/photos/{photo_id}/task", status_code=201, response_model=TaskOut)
def create_task(photo_id: int, payload: CreateTaskRequest) -> TaskOut:
    """把待辦真的建起來——VLM 的建議到這一刻才變成資料（design3.md D13）。

    順序是刻意排的：兩道檢查都在前面，寫資料庫的動作在最後——
    任何一關擋下來時，資料庫一個字都沒被寫過（與釘選端點同一套順序）。
    """
    # ① 這張照片存在嗎（先照片後待辦，錯誤訊息才符合直覺）
    photo = photo_repository.fetch_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="找不到照片")

    # ② 一張照片至多一筆待辦（design3.md §7 MVP）。
    #    資料表的 photo_id UNIQUE 是最後一道防線，狀態碼由這裡決定。
    if photo_repository.get_task_by_photo(photo_id) is not None:
        raise HTTPException(status_code=409, detail="這張照片已經有待辦了")

    # 格式已由 CreateTaskRequest 驗過（錯的早就 422 了），這裡不會炸
    due_date = date.fromisoformat(payload.due_date) if payload.due_date else None
    task = photo_repository.create_task(photo_id, title=payload.title, due_date=due_date)
    # 縮圖用上面已經撈到的那一列算，不為了同一張照片再查一次資料庫
    return _task_out(task, photo["thumbnail_path"])


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    """全部待辦，先到期的排前面、沒到期日的排最後（排序由 SQL 決定）。

    不分頁、也沒有「只看未完成」——本增量沒有完成狀態這回事（design3.md §7）。
    """
    return [_task_out(row, row["thumbnail_path"]) for row in photo_repository.list_tasks()]
