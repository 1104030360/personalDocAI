# Phase 22：資料夾瀏覽端點（GET /folders 與 GET /folders/{id}）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 把 Phase 16 已經做好的三個 repository 函式（`list_folders`／`get_folder`／`list_photos_in_folder`）包成兩個唯讀的 HTTP 端點，讓 Phase 24 的瀏覽頁有東西可以呼叫：`GET /folders` 回全部資料夾（含說明與照片張數）、`GET /folders/{id}` 回某個資料夾＋裡面每張照片的摘要（含縮圖網址）。

---

## 前置條件

- 需要已完成的 phase：
  - **Phase 15**（`folder` 表、六筆預設資料夾、`conftest` 的 `reset_tables`）
  - **Phase 16**（`list_folders()`／`get_folder()`／`list_photos_in_folder()` 三個函式）
  - **Phase 19**（`update_photo_paths()`，本 phase 的測試要用它塞縮圖路徑；`GET /photos/{id}/thumbnail` 端點本身已存在）
  - **Phase 21**（`PATCH /photos/{id}/folder`；不是直接相依，但順序照契約不對調）
- 開工前基線：先實查一次並把數字抄下來。
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```
  Phase 20 完成時是 **124 passed**、Phase 21 完成後是 **132 passed**（2026-08-21 校準；此即本 phase 的基線 **N＝132**）。本 phase 做完應該是 **N ＋ 8 ＝ 140**。
- 環境：PostgreSQL@17（5433 埠）要在跑；**本 phase 的測試完全不需要 Ollama**（兩個端點沒有任何 AI）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

到目前為止，資料夾的資料只有 Python 函式讀得到（Phase 16 做的 repository）。網頁是跑在瀏覽器裡的，它只會講 HTTP，所以要有人把那些函式「掛」成網址。這個 phase 就只做這件事——**兩個唯讀端點，沒有任何 AI、沒有任何寫入**。

design1.md §7.4 規定的兩條：

| 方法 | 路徑 | 成功時回什麼 |
|---|---|---|
| `GET` | `/folders` | 全部資料夾（含 description、照片張數） |
| `GET` | `/folders/{id}` | 該資料夾 ＋ 照片摘要（id、thumbnail_url、text、uploaded_at） |

兩個刻意的設計取捨，先講清楚免得動手時想歪：

1. **不做「列出全部照片、不分資料夾」的端點**（design1.md §7.4 明訂）。瀏覽的入口只有資料夾，沒有第二個入口。
2. **`thumbnail_url` 是端點「算」出來的，不是資料庫欄位。** 資料庫存的是檔案路徑（`thumbnail_path`，例如 `data/thumbs/7.png`），那是伺服器硬碟上的位置，**不可以直接給瀏覽器**（瀏覽器讀不到別人電腦的檔案路徑，而且洩漏路徑也沒好處）。端點看到「這列有路徑」就回一個**網址** `/photos/7/thumbnail`（Phase 19 做的讀圖端點）；看到路徑是空的（舊資料沒有原圖）就回 `null`，讓前端自己畫灰底占位（design1.md §10、§12）。

**分層照舊**：SQL 只准寫在 `repositories/photo_repository.py`（Phase 16 已經寫好了）；本 phase 的 router **一行 SQL 都不會出現**，只做「呼叫函式 → 換成回應格式」。

**名詞**：
- **端點（endpoint）**＝一個「網址＋HTTP 方法」的組合，例如 `GET /folders`。伺服器收到符合的請求就執行對應的那個函式。
- **`APIRouter`**＝FastAPI 把一群相關端點包成一組的容器。本專案每個主題一個檔案（`photos.py`、`ask.py`，本 phase 新增 `folders.py`），最後在 `main.py` 用 `include_router()` 全部掛上去。
- **路徑參數（path parameter）**＝網址裡會變動的那一段，例如 `/folders/{folder_id}` 的 `{folder_id}`。函式參數標成 `folder_id: int`，FastAPI 會自動把網址那段轉成整數；轉不動（例如 `/folders/abc`）它自己回 422，不用我們寫。
- **`response_model`**＝告訴 FastAPI「這個端點回應長這樣」。它會照這個模型**過濾並驗證**輸出——模型沒寫的欄位一律不會外流（所以 `original_path` 這種內部欄位不可能不小心被回出去），少寫的欄位則會直接報錯。順便讓 `/docs` 自動產生正確的文件。
- **Pydantic 模型**＝用 Python class 描述資料形狀的工具（`app/schemas/` 底下那些）。FastAPI 用它做驗證與轉 JSON。
- **`str | None`**＝這個欄位可以是字串，也可以是「沒有」。轉成 JSON 時 Python 的 `None` 會變成 JSON 的 `null`。
- **`datetime` 轉 JSON**＝FastAPI 會自動轉成 **ISO 8601** 格式的字串，例如 `"2026-08-18T10:00:00+08:00"`（年-月-日 T 時:分:秒 + 時區）。
- **LEFT JOIN 計數**＝Phase 16 的 `list_folders()` 用來算 `photo_count` 的 SQL 手法：即使資料夾裡一張照片都沒有，那個資料夾**仍然會出現**在結果裡、張數是 0（如果用一般的 JOIN，空資料夾會整個不見）。

---

## ASCII 圖：兩個端點回應長什麼樣

```
  瀏覽器（Phase 24 的 browse.html）
        │  ①GET /folders                     ②GET /folders/2
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ app/api/routers/folders.py   ★本 phase 新增（零 SQL）          │
 └───────┬──────────────────────────────────────┬───────────────┘
         │ list_folders()                       │ get_folder(2)
         │                                      │ list_photos_in_folder(2)
         ▼                                      ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ app/repositories/photo_repository.py（Phase 16 已完成，唯一寫 SQL 的地方） │
 └──────────────────────────────────────────────────────────────┘


 ① GET /folders  →  200，直接回一個「陣列」（不是物件包陣列）
 ┌────────────────────────────────────────────────────────┐
 │ [                                                      │
 │   { "id": 1, "name": "未分類",                          │
 │     "description": "不確定、關掉彈窗、…",                │
 │     "is_inbox": true,  "photo_count": 0 },             │
 │   { "id": 2, "name": "收據",                            │
 │     "description": "發票、消費憑證、購物明細。",          │
 │     "is_inbox": false, "photo_count": 2 },             │
 │   …（共 6 筆預設 ＋ 使用者自建的，ORDER BY id）          │
 │ ]                                                      │
 └────────────────────────────────────────────────────────┘

 ② GET /folders/2  →  200，資料夾本身 ＋ 裡面的照片摘要
 ┌────────────────────────────────────────────────────────┐
 │ {                                                      │
 │   "folder": { "id": 2, "name": "收據",                  │
 │               "description": "發票、消費憑證、購物明細。",│
 │               "is_inbox": false, "photo_count": 2 },   │
 │   "photos": [                                          │
 │     { "id": 7,                        ← 新的在前(id DESC)│
 │       "thumbnail_url": "/photos/7/thumbnail",          │
 │       "text": "在 Target 購買可樂的收據",                │
 │       "uploaded_at": "2026-08-18T10:00:00+08:00" },    │
 │     { "id": 3,                                         │
 │       "thumbnail_url": null,   ← 舊資料沒有原圖          │
 │       "text": "…", "uploaded_at": "…" }                │
 │   ]                                                    │
 │ }                                                      │
 └────────────────────────────────────────────────────────┘

 ③ GET /folders/999（沒有這個 id）→ 404 {"detail": "找不到資料夾"}

  thumbnail_url 是怎麼來的：
     資料庫 thumbnail_path = "data/thumbs/7.png"  → 回 "/photos/7/thumbnail"
     資料庫 thumbnail_path = NULL                 → 回 null（前端畫灰底占位）
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：**先做步驟 1** 把測試檔寫好、跑一次看它**紅**（此時 `/folders` 還不存在，八個測試會因為拿到 404 而全倒——測試檔只 import 既有模組，不會 import 失敗），再照步驟 2〜4 實作讓它轉綠。

### 步驟 1：先寫測試 `tests/integration/test_folders_endpoint.py`（紅）

新增檔案 `tests/integration/test_folders_endpoint.py`，整份照抄：

```python
"""GET /folders 與 GET /folders/{id} 的整合測試（Phase 22）。

對應 design1.md §7.4：
  GET /folders      → 全部資料夾（含 description、照片張數）
  GET /folders/{id} → 該資料夾 ＋ 照片摘要（id、thumbnail_url、text、uploaded_at）

這兩個端點沒有任何 AI，所以本檔不需要覆寫任何假件——
conftest 的 reset_tables 每個測試前會重播六筆預設資料夾，因此 id 1〜6 是固定的。
"""

from __future__ import annotations

from datetime import date, datetime

from app.repositories import photo_repository
from tests.fakes import FakeEmbeddings

NOW = datetime(2026, 8, 18, 10, 0)

# 預設資料夾的 id（Phase 15 的種子順序，三處同步：schema.sql／migrate_folders.sql／DEFAULT_FOLDERS）
未分類_ID = 1
收據_ID = 2
飲食_ID = 3


def _插入照片(text: str, category: str, *, 有縮圖: bool) -> int:
    """插一張照片並回它的 id。

    insert_photo 會依 category 找同名資料夾（Phase 15），所以 category="收據"
    的照片會自動掛在 2 號資料夾底下。有縮圖的才呼叫 update_photo_paths（Phase 19）
    寫入路徑——沒寫路徑的就等於「舊資料」，thumbnail_url 應該是 null。
    """
    row = photo_repository.insert_photo(
        text=text,
        category=category,
        location="Target",
        items=["可樂"],
        content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=NOW,
    )
    photo_id = row["id"]
    if 有縮圖:
        photo_repository.update_photo_paths(
            photo_id,
            original_path=f"data/photos/{photo_id}.png",
            thumbnail_path=f"data/thumbs/{photo_id}.png",
            content_type="image/png",
        )
    return photo_id


def test_列出全部資料夾(client):
    response = client.get("/folders")

    assert response.status_code == 200
    folders = response.json()
    # 直接回陣列（不是 {"folders": [...]}），順序照 id
    assert [f["id"] for f in folders] == [1, 2, 3, 4, 5, 6]
    assert [f["name"] for f in folders] == [
        "未分類", "收據", "飲食", "風景", "文件", "其他"
    ]
    # 只有「未分類」是收件箱（design1.md §5）
    assert folders[0]["is_inbox"] is True
    assert all(f["is_inbox"] is False for f in folders[1:])
    # description 是給 VLM 看的說明，不能是空字串
    assert folders[0]["description"].startswith("不確定")
    assert all(f["description"] != "" for f in folders)
    # 一張照片都沒有時，六個資料夾仍然全部都要出現（LEFT JOIN），張數 0
    assert all(f["photo_count"] == 0 for f in folders)


def test_回應欄位恰好五個(client):
    """response_model 把關：不多回任何內部欄位（例如 created_at）。"""
    folders = client.get("/folders").json()

    assert set(folders[0]) == {"id", "name", "description", "is_inbox", "photo_count"}


def test_資料夾帶照片張數(client):
    _插入照片("在 Target 購買可樂的收據", "收據", 有縮圖=True)
    _插入照片("在 Costco 購買牛奶的收據", "收據", 有縮圖=False)

    folders = client.get("/folders").json()
    張數 = {f["name"]: f["photo_count"] for f in folders}

    assert 張數["收據"] == 2
    assert 張數["未分類"] == 0
    assert 張數["飲食"] == 0


def test_資料夾內容含照片摘要(client):
    photo_id = _插入照片("在 Target 購買可樂的收據", "收據", 有縮圖=True)

    response = client.get(f"/folders/{收據_ID}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"folder", "photos"}
    assert body["folder"]["name"] == "收據"
    assert body["folder"]["photo_count"] == 1

    assert len(body["photos"]) == 1
    photo = body["photos"][0]
    assert set(photo) == {"id", "thumbnail_url", "text", "uploaded_at"}
    assert photo["id"] == photo_id
    assert photo["text"] == "在 Target 購買可樂的收據"
    # 回的是「網址」不是硬碟路徑，指向 Phase 19 的讀圖端點
    assert photo["thumbnail_url"] == f"/photos/{photo_id}/thumbnail"
    assert photo["uploaded_at"].startswith("2026-08-18")


def test_沒有縮圖的舊照片回null(client):
    """design1.md §10：舊資料路徑是 NULL → 回 null，前端顯示占位，不假裝有圖。"""
    photo_id = _插入照片("沒有原圖的舊資料", "收據", 有縮圖=False)

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert photos[0]["id"] == photo_id
    assert photos[0]["thumbnail_url"] is None


def test_照片新的在前(client):
    先上傳 = _插入照片("先上傳的收據", "收據", 有縮圖=False)
    後上傳 = _插入照片("後上傳的收據", "收據", 有縮圖=False)

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert [p["id"] for p in photos] == [後上傳, 先上傳]


def test_空資料夾回空清單(client):
    response = client.get(f"/folders/{飲食_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["folder"]["name"] == "飲食"
    assert body["folder"]["photo_count"] == 0
    assert body["photos"] == []


def test_資料夾不存在回404(client):
    response = client.get("/folders/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "找不到資料夾"}
```

跑一次看它紅：

```bash
pytest tests/integration/test_folders_endpoint.py -v
```

預期：**8 failed**（每個 `client.get("/folders…")` 都拿到 404，因為端點還不存在）。這就是「紅」。

### 步驟 2：新增 `app/schemas/folder.py`

新增檔案 `app/schemas/folder.py`，整份照抄：

```python
"""資料夾瀏覽的 API 資料格式（Pydantic 模型）。

只給 GET /folders 與 GET /folders/{id} 兩個唯讀端點用；
上傳與歸類的模型在 app/schemas/photo.py，不要混在一起。
"""

from datetime import datetime

from pydantic import BaseModel


class FolderWithCount(BaseModel):
    """一個資料夾＋裡面有幾張照片。

    photo_count 由 repository 的 LEFT JOIN 算出來（空資料夾也會是 0，不會消失）。
    """

    id: int
    name: str
    description: str
    is_inbox: bool          # 只有系統收件箱「未分類」是 true
    photo_count: int


class PhotoSummary(BaseModel):
    """縮圖牆上一張照片要顯示的資訊。

    thumbnail_url 是「網址」不是硬碟路徑：資料庫的 thumbnail_path 有值時
    換算成 /photos/{id}/thumbnail（Phase 19 的讀圖端點）；舊資料沒有路徑時
    是 None（JSON 的 null），前端顯示灰底占位（design1.md §10）。
    """

    id: int
    thumbnail_url: str | None
    text: str
    uploaded_at: datetime   # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00


class FolderDetailResponse(BaseModel):
    """GET /folders/{id} 的回應：資料夾本身 ＋ 裡面的照片摘要（新的在前）。"""

    folder: FolderWithCount
    photos: list[PhotoSummary]
```

### 步驟 3：新增 `app/api/routers/folders.py`

新增檔案 `app/api/routers/folders.py`，整份照抄：

```python
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
```

> 兩個函式的名字和 repository 的函式同名沒關係——呼叫時一律寫成 `photo_repository.list_folders()`，前面有模組名，不會撞到。

### 步驟 4：在 `app/main.py` 掛上新 router

現在的 `app/main.py` 第 9 行是：

```python
from app.api.routers import ask, photos
```

改成（多一個 `folders`，照字母順序排）：

```python
from app.api.routers import ask, folders, photos
```

現在的第 13〜14 行是：

```python
app.include_router(photos.router)
app.include_router(ask.router)
```

在後面補一行：

```python
app.include_router(photos.router)
app.include_router(ask.router)
app.include_router(folders.router)
```

`main.py` 其他部分（`/health`、`/` 轉址、`app.mount("/ui", …)`）**完全不動**。

### 步驟 5：跑測試看它轉綠

```bash
pytest tests/integration/test_folders_endpoint.py -v
```

預期：`8 passed`。

再跑全量：

```bash
pytest -q
```

預期：`N + 8 passed`（N＝132，即 **140 passed**）。

### 步驟 6：用真的伺服器看一眼（可選但建議）

```bash
uvicorn app.main:app --reload --port 8000
```

另開一個終端機：

```bash
curl -s http://localhost:8000/folders | python -m json.tool
curl -s http://localhost:8000/folders/2 | python -m json.tool
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/folders/999
```

預期：第一行印出全部資料夾（至少六筆預設；Phase 21 手動實測若建過新資料夾也會出現）。「收據」的 `photo_count` **至少是 2**——那兩張遷移進來的真實舊照片；Phase 19〜21 的手動實測若有上傳新照片，數字會更多。第二行印出收據資料夾＋照片摘要，其中**那兩張舊照片的 `thumbnail_url` 是 `null`**（舊資料沒有原圖，design1.md §10）、手動實測新上傳的照片則是 `/photos/{id}/thumbnail`；第三行印出 `404`。

也可以打開 <http://localhost:8000/docs>，會看到自動產生的 `folders` 這一組文件。

---

## 驗收清單

- [ ] `tests/integration/test_folders_endpoint.py` 存在，且是**先寫測試看它紅**才實作的
- [ ] 新檔 `app/schemas/folder.py` 有三個模型：`FolderWithCount`、`PhotoSummary`、`FolderDetailResponse`
- [ ] 新檔 `app/api/routers/folders.py` 有兩個端點，且**沒有任何 SQL**
      ```bash
      grep -nE "SELECT |INSERT INTO|UPDATE |TRUNCATE" app/api/routers/folders.py || echo "OK：router 沒有 SQL"
      ```
      預期：`OK：router 沒有 SQL`
- [ ] SQL 仍然只出現在 repository 一個檔案
      ```bash
      grep -rlnE "SELECT |INSERT INTO|TRUNCATE TABLE" app/ --include="*.py"
      ```
      預期輸出**只有一行**：`app/repositories/photo_repository.py`
- [ ] `app/main.py` 有 `app.include_router(folders.router)`
- [ ] 端點數正確
      ```bash
      grep -rnE "@router\.(get|post|put|patch|delete)" app/api/routers/ | wc -l
      grep -nE "@app\.(get|post|put|patch|delete)" app/main.py | wc -l
      ```
      預期：第一個是 `7`（photos.py 四個：POST /photos、GET thumbnail、GET image、PATCH folder；ask.py 一個；folders.py 兩個），第二個是 `2`（`/health`、`/`）。合計 9 個端點。
- [ ] 本 phase 的測試全綠
      ```bash
      pytest tests/integration/test_folders_endpoint.py -v
      ```
      預期：`8 passed`
- [ ] **全量 `pytest -q` 全綠**
      ```bash
      cd /Users/linjunting/personalDocAI && source .venv/bin/activate
      pytest -q
      ```
      預期：`N + 8 passed`（N＝132，即 **140 passed**），且沒有任何測試變紅——本 phase 沒改動任何既有行為。
- [ ] git commit
      ```bash
      git add app/schemas/folder.py app/api/routers/folders.py app/main.py tests/integration/test_folders_endpoint.py
      git commit -m "feat: Phase 22 資料夾瀏覽端點——GET /folders 與 GET /folders/{id}（照片摘要含縮圖網址、舊資料回 null、不存在回 404），+8 tests"
      ```

---

## 常見問題

**Q1：`GET /folders` 為什麼直接回一個陣列，不包成 `{"folders": [...]}`？**
契約與 design1.md §7.4 就是這樣定的，前端也照這個形狀寫。包一層在這裡沒有帶來任何好處（沒有分頁、沒有總數要放），多包一層反而要改兩邊。**不要自己改形狀**——Phase 24 的 `browse.html` 直接對這個陣列做迴圈。

**Q2：`/folders/{id}` 已經有 `photo_count` 了，為什麼還要回 `photos` 陣列？**
`photo_count` 是「有幾張」（列表頁上顯示用），`photos` 是「有哪些」（縮圖牆用）。兩者都是同一次請求就拿到，前端不必再打第二次。

**Q3：照片很多的時候要不要加分頁（pagination）？**
**不要。** 這是單人 side project，照片是自己一張張上傳的。分頁要動端點、要動前端、要動測試，收益是零。design1.md §3 的「不做」清單雖然沒明列分頁，但「不過度設計」的原則涵蓋它。

**Q4：`thumbnail_url` 可不可以直接回 `thumbnail_path`（`data/thumbs/7.png`）讓前端當 `<img src>` 用？**
不行。`data/thumbs/7.png` 是**伺服器硬碟上的路徑**，瀏覽器拿去當網址會變成 `http://localhost:8000/data/thumbs/7.png`，而我們**沒有**把 `data/` 掛成靜態目錄（也不該掛——那等於把整個照片資料夾對外開放）。正確做法就是回 Phase 19 那個讀圖端點的網址。

**Q5：`GET /folders/abc` 會怎樣？**
FastAPI 看到 `folder_id: int` 卻收到 `abc`，會自動回 **422**（參數格式錯誤），不會進到我們的函式。這是框架既有行為，不用寫測試也不用處理——和 Phase 11 讓「問題空字串」走框架既有 422 是同一個道理。

**Q6：測試裡的 `未分類_ID = 1` 這種寫死的 id 靠得住嗎？**
靠得住，因為 Phase 15 的 `reset_folders_and_photos()` 用 `TRUNCATE … RESTART IDENTITY` 後**照固定順序**重插六筆，所以每個測試開始時 id 一定是 1〜6。這也是為什麼契約要求「六筆種子每測重播」。

**Q7：要不要順便做「改資料夾名稱」或「刪除資料夾」？**
**不要。** design1.md §3 與 §15 明列不做刪除；改名也沒在範圍內。本 phase 只有兩個 `GET`。

---

## 完成後的專案狀態

後端的資料夾功能到此完整：建（Phase 21 的自建）、歸類（Phase 21 的 PATCH）、讀圖（Phase 19）、**瀏覽（本 phase）**。瀏覽頁需要的資料現在全部拿得到——`GET /folders` 給資料夾卡片，`GET /folders/{id}` 給縮圖牆，缺圖的照片明確回 `null` 讓前端畫占位。接下來 Phase 23、24 才是把這些資料畫到畫面上。測試累計 **N ＋ 8 ＝ 140**。
