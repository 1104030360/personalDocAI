# Phase 30：實體建議與釘選端點（design3.md D8／D12）

> 🎯 **人確認才落庫**：VLM 的實體／待辦輸出只是建議、只出現在回應；寫入走使用者按出來的 POST。
> **VLM 契約一次擴齊**（實體＋待辦建議一起加）——同一個 gemma4 仍只看一次圖，之後 P32/33 不再改 prompt。

**目標：** ① `PhotoUnderstanding` 一次加三欄（entity／task_title／task_due），prompt 同步注入「現有實體清單」與待辦判斷規則；`clamp_entity()` 把建議夾回實體清單。② 上傳回應加 `suggested_entity`／`entities`／`suggested_task`。③ 新端點 `GET /entities`、`POST /photos/{id}/entities`（釘選）、`POST /photos/{id}/entity-suggestion`（再建議一個，新注入點）。端點 9→12（P28 不加端點）。

## 檔案

- 改：`app/services/vlm_service.py`（模型三欄、`build_vlm_prompt(folders, entities)`、`clamp_entity()`、`understand()` 加 entities 參數）
- 建：`app/services/entity_suggestion_service.py`（「再建議一個」的文字 LLM；`OllamaEntitySuggester`）
- 改：`app/dependencies.py`（+`get_entity_suggester`）、`tests/fakes.py`（FakeVLM 擴充＋`FakeEntitySuggester`）、
  `tests/conftest.py`（wire_fake_ai 接新注入點）
- 建：`app/schemas/entity.py`（EntityOut／PinEntityRequest／PinEntityResponse／EntitySuggestionRequest／EntitySuggestionResponse）
- 建：`app/api/routers/entities.py`（零 SQL）；改：`app/main.py`（include_router）
- 改：`app/api/routers/photos.py`（上傳回應帶三個新欄位）、`app/schemas/photo.py`（UploadResponse 加欄位＋TaskSuggestion）
- 建：`tests/unit/test_vlm_entity_unit.py`、`tests/integration/test_entities_endpoint.py`、`tests/integration/test_pin_entity.py`

## 契約定稿

```python
class PhotoUnderstanding(BaseModel):      # 6 → 9 欄
    ...既有六欄不動...
    entity: str | None = None       # 從「現有實體清單」挑一個最相關的；清單空或都不像 → None
    task_title: str | None = None   # 照片含可辦事項（繳交、繳費、預約…）才填；沒有 → None
    task_due: str | None = None     # 到期日 YYYY-MM-DD；推不出來 → None

def clamp_entity(name: str | None, entities: list[dict]) -> dict | None:
    # 鏡射 clamp_category：去空白＋casefold 命中 → 回清單裡那筆 dict（原文）；沒命中 → None（實體沒有「未分類」）

class TaskSuggestion(BaseModel):          # schemas/photo.py
    title: str
    due: str | None = None

class UploadResponse(...):                # 只加不改
    suggested_entity: EntityOut | None    # clamp 後的實體建議
    entities: list[EntityOut]             # 完整實體清單（彈窗②下拉）
    suggested_task: TaskSuggestion | None # VLM 判斷的待辦（P33 前端才用；title 空白視同 None）
```

- prompt 追加兩段：「現有實體（entity 只能從這裡選一個最相關的，都不符合或清單為空填 null；照清單原文）：{entity_lines}」
  ＋「待辦：照片內容含有需要去做的事（作業繳交、帳單繳費、預約時間）時，task_title 填一句話、task_due 填 YYYY-MM-DD（推不出填 null）；沒有就兩個都填 null」。實體清單為空時該段寫「（目前沒有任何實體，entity 一律填 null）」。
- `VLMClient.understand(image_bytes, content_type, folders, entities)`；FakeVLM 記 `last_entities`。

## 端點定稿

1. **`GET /entities`** → 200 `[EntityOut{id,name,description}]`（ORDER BY id）。
2. **`POST /photos/{photo_id}/entities`**（釘選）→ 201 `PinEntityResponse{photo_id, entity: EntityOut, entities: [EntityOut]}`。
   - body：`{"entity_id": 3}`（①②）或 `{"name": "我的 MacBook", "description": "…"}`（③自創）——
     「恰一」驗證與去空白完全鏡射 `AssignFolderRequest`（model_validator）。
   - 順序鐵律：404 照片不存在 → entity_id 路徑：404 實體不存在／name 路徑：`find_entity_by_name` 命中 → 409「實體名稱已存在」
     → `is_pinned` → 409「這張照片已釘過這個實體」→（name 路徑此時才）`create_entity` → `pin_entity`。
   - **不重算 embedding**（實體不進向量，檢索走連結表——design3 §5；embedding 定義仍是 design.md 的 text＋四欄位）。
3. **`POST /photos/{photo_id}/entity-suggestion`**（再建議一個）→ 200 `{"suggested_entity": EntityOut | None}`。
   - body：`{"exclude": [1, 4]}`（已釘＋這輪已建議過的 entity id；預設 []）。
   - 404 照片不存在；候選＝`list_entities()` 減 exclude；候選空 → 直接回 None **不呼叫 LLM**。
   - `OllamaEntitySuggester.pick(photo: dict, candidates: list[dict]) -> str | None`：ChatOllama structured output
     `EntityPick{entity: str | None}`，prompt 給照片 text＋四欄位＋候選清單，要求挑一個最相關或 null；
     回來再過 `clamp_entity(名字, candidates)` 夾一次；呼叫失敗回 None（不 500——建議本來就可有可無，但要 log warning）。
   - **新注入點 `get_entity_suggester`**：正式 OllamaEntitySuggester（lru_cache）；
     conftest `wire_fake_ai` 預設 `FakeEntitySuggester()`（照建構子登記的答案回，預設回 None）。

## 步驟（先紅再綠）

1. 先紅（unit）：`test_vlm_entity_unit.py`——
   `clamp_entity` 四情境（命中原文／大小寫空白命中／沒命中 None／清單空 None）；
   `build_vlm_prompt(folders, entities)` 內含實體名稱與「填 null」規則；空清單有「一律填 null」句。
2. 綠：vlm_service 三欄＋clamp_entity＋prompt；FakeVLM 同步簽名（既有測試跟著改參數——一次到位，不留舊簽名）。
3. 先紅（integration）：`test_entities_endpoint.py`——GET 空陣列／建立後看得到；
   `test_pin_entity.py`——釘現有 201＋回應形狀、自創 201 清單+1、重名 409、重複釘 409、照片不存在 404、實體不存在 404、
   恰一驗證 422（都給／都沒給／name 空白）、**釘選後 `fetch_embedding` 不變**（實體不動向量的實證）、
   再建議：FakeEntitySuggester 登記答案→回該實體、exclude 生效、候選空回 None 且 suggester 零呼叫、
   上傳回應含 `suggested_entity`（FakeVLM 給清單內名字→夾中；給清單外→None）＋`entities`＋`suggested_task`。
4. 綠：schemas/entity.py → routers/entities.py → photos.py 回應擴充 → dependencies／conftest／fakes。
5. 全量回歸＋零 Ollama 同顆數；`/openapi.json` 清點 12。

## 驗收清單

- [x] 新測試先紅再綠（+35）；全量全綠 172→**207**、零 Ollama 同顆數（controller 複驗）；端點 **12**（openapi 清點）
- [x] 上傳仍只有一次看圖呼叫（FakeVLM.calls==1 斷言）；「再建議」是獨立文字呼叫、有獨立假件（單次嘗試＋log fallback）
- [x] 釘選不動 embedding（fetch_embedding 前後相同實測）；重名／重複釘 409；恰一 422
- [x] wire_fake_ai 涵蓋六個注入點（vlm／embeddings／now／router／answerer／entity_suggester）
- [x] 上傳既有回應欄位一字不變（.feature 全綠；`test_單圖上傳回應形狀不變` 護欄鍵集合 +3 屬守門測試同步）
