"""實體（別針）的 router：GET /entities、POST /photos/{id}/entities、
POST /photos/{id}/entity-suggestion（design3.md D12）。

SQL 一律在 repository，本檔只做「呼叫函式 → 換成回應格式」。
釘選端點**不碰 embedding**：實體走連結表，不進向量（design3.md §5），
embedding 的定義仍然是 design.md 的 text ＋ metadata 四欄位。
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_entity_suggester
from app.repositories import photo_repository
from app.schemas.entity import (
    EntityOut,
    EntitySuggestionRequest,
    EntitySuggestionResponse,
    PinEntityRequest,
    PinEntityResponse,
)
from app.services import entity_suggestion_service, vlm_service

router = APIRouter(tags=["entities"])


def _entity_out(entity: dict) -> EntityOut:
    """repository 回來的實體 dict 剛好就是三個欄位，直接展開。"""
    return EntityOut(**entity)


@router.get("/entities", response_model=list[EntityOut])
def list_entities() -> list[EntityOut]:
    """全部實體，照 id 排序。一開始是空陣列（實體表沒有種子）。"""
    return [_entity_out(row) for row in photo_repository.list_entities()]


@router.post(
    "/photos/{photo_id}/entities", status_code=201, response_model=PinEntityResponse
)
def pin_entity(photo_id: int, payload: PinEntityRequest) -> PinEntityResponse:
    """把一個實體釘到照片上：釘現有的，或當場自創一個（design3.md D12）。

    順序是刻意排的：所有檢查都在前面，寫資料庫的動作全部在最後——
    任何一關擋下來時，資料庫一個字都沒被寫過（不會留下沒人用的空實體，
    也不會出現「建了實體卻沒釘上」的半套狀態）。
    """
    # ① 這張照片存在嗎（先照片後實體，錯誤訊息才符合直覺；與 assign_folder 同一套順序）
    if photo_repository.fetch_photo(photo_id) is None:
        raise HTTPException(status_code=404, detail="找不到照片")

    # ② 決定要釘哪一個。這一段只查不寫：自創那條路的 create_entity 排在最後（見 ④）。
    if payload.entity_id is not None:
        # 實體清單很短（只在使用者按「自創」時才 +1），
        # 用現成的 list_entities() 挑出那一筆就好，不必為此多寫一條 SQL。
        entity = next(
            (
                row
                for row in photo_repository.list_entities()
                if row["id"] == payload.entity_id
            ),
            None,
        )
        if entity is None:
            raise HTTPException(status_code=404, detail="找不到實體")
        # ③ 同一張照片重複釘同一個實體＝按了兩次，擋成 409（連結表主鍵是最後防線）。
        #    自創那條路不必查：名稱沒撞到就代表這個實體還不存在，當然沒被釘過。
        if photo_repository.is_pinned(photo_id, entity["id"]):
            raise HTTPException(status_code=409, detail="這張照片已釘過這個實體")
    else:
        # 自創：重名交由這裡擋（大小寫不敏感），資料庫的 name UNIQUE 是最後防線
        if photo_repository.find_entity_by_name(payload.name) is not None:
            raise HTTPException(status_code=409, detail="實體名稱已存在")
        # ④ 全部檢查都過了才真的建（名稱已由驗證器去過空白）
        entity = photo_repository.create_entity(payload.name, payload.description)

    photo_repository.pin_entity(photo_id, entity["id"])

    # 回完整清單（自創時已經 +1），彈窗直接拿去換掉下拉選單
    return PinEntityResponse(
        photo_id=photo_id,
        entity=_entity_out(entity),
        entities=[_entity_out(row) for row in photo_repository.list_entities()],
    )


@router.post(
    "/photos/{photo_id}/entity-suggestion", response_model=EntitySuggestionResponse
)
def suggest_entity(
    photo_id: int,
    payload: EntitySuggestionRequest,
    suggester: entity_suggestion_service.EntitySuggesterClient = Depends(
        get_entity_suggester
    ),
) -> EntitySuggestionResponse:
    """再建議一個實體：從「還沒看過的」候選裡挑一個（design3.md D12）。

    這是唯讀端點——只給建議，釘不釘是使用者按下 POST /photos/{id}/entities 的事。
    建議可有可無：挑不出來、模型失敗都回 null（200），不是錯誤。
    """
    photo = photo_repository.fetch_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="找不到照片")

    excluded = set(payload.exclude)
    candidates = [
        row for row in photo_repository.list_entities() if row["id"] not in excluded
    ]
    if not candidates:
        # 沒有東西可挑就不必問 LLM——省一次推論，也不會有幻覺可以夾
        return EntitySuggestionResponse(suggested_entity=None)

    # 模型只能挑候選清單裡的，所以夾也是夾**候選**（被 exclude 掉的不可能回來）
    picked = vlm_service.clamp_entity(suggester.pick(photo, candidates), candidates)
    return EntitySuggestionResponse(
        suggested_entity=_entity_out(picked) if picked else None
    )
