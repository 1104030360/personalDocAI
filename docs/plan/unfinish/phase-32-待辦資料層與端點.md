# Phase 32：待辦資料層與端點（design3.md D13）

> 🎯 **人按「建立」才寫入**：VLM 的待辦建議（P30 已在上傳回應裡）只是建議；
> 本 phase 做「確認寫入」與「列出」兩件事。不做完成勾選、不做過期刪除、不寫 Gmail／日曆（design3 §7、§3）。

**目標：** task 的 repository 三函式＋兩個端點：`POST /photos/{photo_id}/task`（建立，404／409／422）、
`GET /tasks`（列表，附 thumbnail_url 與來源照片 id）。端點 12→14。表已由 P29 建好（photo_id UNIQUE＝每張照片至多一筆）。

## 檔案

- 改：`app/repositories/photo_repository.py`（task 三函式）
- 建：`app/schemas/task.py`（CreateTaskRequest／TaskOut）
- 建：`app/api/routers/tasks.py`（零 SQL）；改：`app/main.py`（include_router）
- 建：`tests/integration/test_tasks.py`

## 契約定稿

```python
# repository（回傳鍵名即 Pydantic 契約）
def create_task(photo_id, *, title, due_date) -> dict   # INSERT ... RETURNING id,photo_id,title,due_date,created_at
def get_task_by_photo(photo_id) -> dict | None
def list_tasks() -> list[dict]   # ORDER BY due_date ASC NULLS LAST, created_at DESC（先到期的排前面；沒到期日的最後）

# schemas/task.py
class CreateTaskRequest(BaseModel):
    title: str                      # 去頭尾空白；空白→ValueError→422「待辦標題不可為空白」（model_validator，鏡射 AssignFolderRequest）
    due_date: str | None = None     # YYYY-MM-DD；解析失敗→422「到期日格式須為 YYYY-MM-DD」（用 date.fromisoformat）

class TaskOut(BaseModel):
    id: int
    photo_id: int
    title: str
    due_date: str | None            # ISO 字串外送（鏡射 content_time 的做法）
    thumbnail_url: str | None       # 端點換算 /photos/{photo_id}/thumbnail；來源照片沒縮圖→None（前端占位）
```

- **`POST /photos/{photo_id}/task`** → 201 TaskOut。順序鐵律：404 照片不存在 →
  409「這張照片已經有待辦了」（`get_task_by_photo` 先查，DB UNIQUE 是最後防線）→ `create_task`。
  不碰 embedding、不碰 VLM——這是純寫入端點。
- **`GET /tasks`** → 200 `[TaskOut]`。thumbnail_url 由端點依照片的 `thumbnail_path` 是否為 NULL 決定
  （鏡射 folders 端點的算法——**不洩硬碟路徑**）；list_tasks 的 SQL JOIN photo 取 thumbnail_path。

## 步驟（先紅再綠）

1. 先紅：`test_tasks.py`——
   `test_建立待辦201與回應形狀`（含 due_date 與 null due 兩例）；
   `test_同一張照片第二筆409`；`test_照片不存在404`；
   `test_標題空白422`／`test_到期日格式錯422`；
   `test_list_依到期日排序_無到期日在最後`（三筆：09-01、08-25、null → 08-25、09-01、null）；
   `test_list_thumbnail_url_有縮圖給網址_沒縮圖給null`；`test_list_初始為空`。
2. 綠：repository 三函式 → schemas → router → main.py。
3. 全量回歸＋零 Ollama 同顆數；`/openapi.json` 清點 14。

## 驗收清單

- [ ] 新測試先紅再綠；全量全綠、零 Ollama 同顆數；端點 14
- [ ] 每張照片至多一筆（409）；驗證錯誤全走 422 且訊息明確
- [ ] SQL 只在 repository；回應不含硬碟路徑
- [ ] 對前端零影響（本 phase 不動 static/）
