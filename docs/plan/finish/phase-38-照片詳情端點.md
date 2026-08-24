# Phase 38：照片詳情端點 `GET /photos/{photo_id}`（階段甲第 1 步）

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 技術實作已完成。**
> 下方 `358 → 365` 與「先紅後綠」數字是本 phase 開工時的歷史基線，特意保留；
> 目前 Phase 38〜44 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，
> 全量為 **402 passed、2 skipped、1 warning（27.73s）**，dead-Ollama 同顆數（26.47s）。
> 唯一 warning 是 `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> OpenAPI 運算元是 **20**、DELETE 是 **0**，且沒有 `GET /photos` 列出全部照片。
> 最新 hardening 另釘住遺失原圖仍保留詳情契約、前台不外露 raw error，以及長 CJK／數字單位
> 顯示；狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。
> 工作樹仍 dirty；沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 讓前端能用「一張照片的 id」把那張照片的**完整說明**一次抓回來
> （AI 寫的描述 ＋ 類別／地點／物品／內容日期四欄 ＋ 縮圖與原圖的網址），
> 之後 Phase 39／40 的唯讀彈窗才有東西可畫。

**為什麼要新開一支端點：** 現在的兩支清單端點（`GET /folders/{id}`、`GET /tasks`）刻意只回
「畫得出縮圖牆／待辦列」的最少欄位——這叫**瘦契約**：清單一次可能回幾十筆，每一筆都塞完整說明
會讓清單變慢、而且 99% 的資料使用者根本沒點開。所以產品負責人選的是「清單維持瘦，**點開再抓一張**」
（design4 §1.2 明文否決了「清單一次帶齊 metadata」）。

---

## 1. 對應 design4.md 章節

- **§4.4**（`GET /photos/{id}` 的完整規格：路徑、放哪、SQL、404／200、`PhotoDetailOut`）
- **§4.5**（會動到的檔，本 phase 負責 `schemas/photo.py`、`api/routers/photos.py`、`tests/integration/test_photo_detail.py`、端點清點）
- **D3**（詳情欄位＝`text` ＋ metadata 四欄）
- **D5**（新端點；清單維持瘦；端點 **19→20**）
- **D6**（找不到＝404；有列但 `original_path` 為 NULL＝200 且 `image_url` 為 null）
- **§1.1 第 3／4 列**（「不做列出全部照片」仍有效，但允許「依 id 讀一張」；清點測試數字要改）
- **§9 錯誤表第 1、2、3 列**（本 phase 負責後端那半邊）

---

## 2. 前置條件

- 無 phase 依賴——這是增量四的第一步。
- 開工基準：`pytest -q` ＝ **358 passed ＋ 2 skipped**、`/openapi.json` 運算元 ＝ **19**。
- 開工前先確認基準沒跑掉：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

---

## 3. 範圍

### 做

- `app/schemas/photo.py` 新增 **`PhotoDetailOut`**（重用既有 `PhotoMetadata`，不另造四欄）。
- `app/api/routers/photos.py` 新增 **`GET /photos/{photo_id}`**（與 thumbnail／image／PATCH 同一支 router）。
- 新測試檔 `tests/integration/test_photo_detail.py`。
- 既有清點測試 `tests/integration/test_ask_three_paths.py::test_端點數不變` 的數字 **19 → 20**。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 新增 `GET /photos`（列出全部照片） | design1 的禁令**仍然有效**（design4 §1.1 第 3 列、§4.4 末句）。只准「依 id 讀一張」 |
| 改 `GET /folders/{id}` 的**五鍵**照片摘要 | design4 §3「不做」第一條。`tests/integration/test_folders_endpoint.py` 一個字都不准改 |
| 改 `GET /tasks` 的瘦契約 | 同上 |
| 在回應裡加 embedding、folder 物件、`suggested_category`、釘著的實體 | design4 §4.4 明文「不回」。那些不是這顆窗要的 |
| 在回應裡放硬碟路徑（`data/photos/7.jpg`） | 只外送網址（`/photos/7/image`），沿用 folders／tasks 端點的既有慣例 |
| 為這支端點新寫任何 SQL | `photo_repository.fetch_photo()` 已經夠用（見下面 §4.0），router 零 SQL |
| 呼叫 VLM／重算 embedding | 這是一支唯讀端點，`GET` 不該有副作用 |
| 動 `.feature` 規格檔 | design4 §3「規格 `.feature` 本輪不改」 |

---

## 4. 實作步驟（先寫測試再實作）

### 4.0 先確認手上的積木（不寫程式，只讀）

- [ ] 打開 `app/repositories/photo_repository.py`，確認第 22〜25 行的 `PHOTO_COLUMNS` 常數：

```text
PHOTO_COLUMNS = (
    "id, text, category, folder_id, location, items, content_time, uploaded_at, "
    "original_path, thumbnail_path, content_type, suggested_category"
)
```

  這一支端點需要的欄位（`text`／四欄 metadata／兩個路徑／`uploaded_at`）**全部都在裡面**——
  所以 `fetch_photo(photo_id)` 直接就夠用，**不必新增任何 SQL**（design4 §4.4「`fetch_photo` 不必新 SQL」）。

- [ ] 打開 `app/schemas/photo.py`，確認 `PhotoMetadata` 就是那四個欄位
      （`category`／`location`／`items`／`content_time`），新模型要**重用**它而不是複製。

### 4.1 先寫測試（此時全部應該是紅的）

- [ ] 新建 `tests/integration/test_photo_detail.py`，寫下面七顆。

**先看這三個前提，不然第一顆就會卡住：**

1. **假 VLM 的預設值是「看不懂」。** `tests/conftest.py` 的 `wire_fake_ai` 把 `get_vlm`
   接成 `FakeVLM()`（沒帶結果＝`understood=False`），所以直接 `client.post("/photos", ...)`
   會拿到 **422 而不是 201**。要讓上傳成功，本檔必須自己覆寫成「看得懂」的假件——
   照抄 `tests/integration/test_folder_error_paths.py` 第 26〜43 行那一段：
   先宣告一份 `PhotoUnderstanding(understood=True, text=..., category=..., location=...,
   items=[...], content_time="2026-08-10")`，再用一個 `autouse` fixture
   （**參數列要寫 `wire_fake_ai`**，這樣它一定排在 conftest 那條之後執行、測完由它統一清掉）
   把 `app.dependency_overrides[get_vlm]` 換成 `lambda: FakeVLM(那份理解)`。
2. **上傳用的位元組要是「真圖」。** 用 `tests/fakes.py` 的 `make_png_bytes()`；
   手打的 `b"\x89PNG..."` 會在做縮圖那一步被 Pillow 擋下來。
   同一個檔的 `上傳一張(client)`（第 64〜70 行）就是現成樣板，照抄即可。
3. **需要「沒有原圖的舊照片」時不要走上傳端點**，直接呼叫
   `photo_repository.insert_photo(...)`——沒經過存檔那一步，`original_path` 與
   `thumbnail_path` 自然是 NULL。注意 `embedding` 是必填參數（資料表 NOT NULL），
   用假件現算一條就好：`embedding=FakeEmbeddings().embed_query("...")`。
   完整寫法見 `tests/integration/test_design3_error_paths.py` 第 131〜142 行的 `_一張照片()`。
   至於第 5 顆要「把已經存好的原圖檔刪掉」，照抄
   `tests/integration/test_folder_error_paths.py` 第 182 行：
   `storage_service.absolute_path(列["original_path"]).unlink()`。

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 1 | `test_取得照片詳情回200且鍵恰好六個` | `set(body) == {"id","text","metadata","thumbnail_url","image_url","uploaded_at"}` |
| 2 | `test_metadata恰四鍵且值正確` | `set(body["metadata"]) == {"category","location","items","content_time"}`；`content_time` 是 ISO 日期字串。**值怎麼比最保險：直接 `assert 詳情["metadata"] == 上傳201回應["metadata"]`**——同一張照片、同一個 `PhotoMetadata` 模型，兩支端點必須一模一樣。⚠️ 不要手寫 `category == "收據"`：上傳一律先進「未分類」，VLM 的建議不落庫（見 §7 陷阱 8） |
| 3 | `test_照片不存在回404` | `GET /photos/999` → 404，**而且 `response.json()["detail"] == "找不到照片"`**。detail 一定要一起驗：端點還沒寫之前，FastAPI 對「沒有這條路由」本來就回 404（detail 是 `"Not Found"`），只驗狀態碼的話這顆從頭到尾都是綠的＝根本沒測到（§9 錯誤表第 1 列） |
| 4 | `test_舊照片沒有原圖時image_url為null` | 用 `insert_photo` 直接寫一列（不存檔）→ 200，且 `image_url is None`、`thumbnail_url is None`（§9 第 2 列、D6） |
| 5 | `test_原圖被刪掉詳情仍回200` | 正常上傳一張 → 把 `data/` 底下的原圖檔刪掉 → 詳情**仍然 200** 且 `image_url` 有值（§9 第 3 列；「開圖檔」的 404 是 `/photos/{id}/image` 的事，跟這支 JSON 無關） |
| 6 | `test_回應不含硬碟路徑也不含向量` | **第一句先 `assert response.status_code == 200`**，再驗 `response.text` 裡找不到 `"data/"`、`"original_path"`、`"thumbnail_path"`、`"embedding"`。少了前面那一句就會假綠：端點還沒寫時的 404 body（`{"detail":"Not Found"}`）也「找不到」那四個字 |
| 7 | `test_openapi有依id讀一張照片的端點且沒有列出全部` | `"/photos/{photo_id}" in paths` 且 `"get" in paths["/photos/{photo_id}"]`；同時 `"get" not in paths.get("/photos", {})`（＝沒有「列出全部照片」） |

- [ ] 跑一次確認**真的是紅的**（紅了才證明測試有在測東西）：

```bash
pytest tests/integration/test_photo_detail.py -v
```

  預期：七顆全紅（404 或 AssertionError 都可以，重點是沒有一顆意外變綠）。
  第 3、6 顆特別容易「假綠」——上表已經寫了各自要補哪一句斷言來防它。

### 4.2 寫 `PhotoDetailOut`

- [ ] 在 `app/schemas/photo.py` **檔案最後**（現有的 `AssignFolderResponse` 之後）加入。
      唯一的硬性要求是要排在 `PhotoMetadata` **之後**——Python 由上往下讀，
      被引用到的類別必須先定義好；擺在最後也最不打擾既有的閱讀順序：

```python
class PhotoDetailOut(BaseModel):
    """GET /photos/{photo_id} 的回應（HTTP 200，design4.md §4.4）。

    唯讀詳情彈窗要的東西，不多不少：
      - text ＋ metadata 四欄 ＝ 使用者要看的說明
      - 兩個網址        ＝ 圖要去哪裡拿（不是硬碟路徑）
      - uploaded_at     ＝ 什麼時候進來的

    刻意「不回」：embedding（1024 個數字，前端用不到）、folder 物件、
    suggested_category、釘著的實體清單——那些不是這顆窗要回答的問題。
    """

    id: int
    text: str
    metadata: PhotoMetadata
    thumbnail_url: str | None   # thumbnail_path 有值才給網址，舊照片是 None
    image_url: str | None       # original_path 有值才給網址，舊照片是 None
    uploaded_at: datetime       # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00
```

- [ ] 檔頭補上 `from datetime import datetime`（目前 `app/schemas/photo.py` 還沒有 import 它；
      `app/schemas/folder.py` 的 `PhotoSummary.uploaded_at` 就是這樣寫的，兩邊慣例一致）。

### 4.3 寫端點

- [ ] 在 `app/api/routers/photos.py` 加入端點。放在 `_send_photo_file`／
      `get_photo_thumbnail`／`get_photo_image` **之後**、`_record_correction_if_changed` 之前
      （現況約在第 347〜349 行之間），讓「讀這張照片」的三支端點排在一起，讀起來像一組。
      **擺哪裡不影響路由比對**（三條路徑不會互相吃掉，理由見 §7 陷阱 1），純粹是可讀性。

```python
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
```

- [ ] `from app.schemas.photo import (...)` 那一段把 `PhotoDetailOut` 加進去
      （維持字母序＝夾在 `PdfUploadResponse` 與 `PhotoMetadata` 之間）。
- [ ] 檔案最上面的 docstring 補一句：現在這支 router 有 `GET /photos/{photo_id}`（詳情）。

### 4.4 改端點清點測試

- [ ] 打開 `tests/integration/test_ask_three_paths.py`，找到最後一顆
      `test_端點數不變`（約在第 423 行）。把 `assert len(運算元) == 19` 改成 **`== 20`**，
      並在 docstring 補一行：

```text
19 → 20 是增量四 Phase 38 的 `GET /photos/{photo_id}`（design4.md D5）。
```

  **不要改測試名稱**：它守的是「詢問這一路沒有偷加端點」（下一行的
  `assert [路徑 for 路徑, _ in 運算元 if 路徑.startswith("/ask")] == ["/ask"]`），
  那件事仍然成立。

  ℹ️ §4.3 做完到這一步之間，`test_端點數不變` 會是紅的（端點已經 20、測試還寫 19）——
  那是預期，不是壞掉；改完數字就綠了。

### 4.5 跑綠

- [ ] 只跑新檔：

```bash
pytest tests/integration/test_photo_detail.py -v
```

  預期：**7 passed**。

- [ ] 跑全量：

```bash
pytest -q
```

  預期：**365 passed ＋ 2 skipped**（358 ＋ 本 phase 的 7 顆；2 skipped 是
  `自然語言詢問.feature` 兩條 `@未實作` Rule，摘標屬產品負責人，不准動）。

- [ ] 零外部依賴實證（把 Ollama 位址指到一個沒人聽的埠，顆數必須一樣）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

### 4.6 手動看一眼（可選但建議，30 秒）

- [ ] **第一個終端機**起伺服器（連的是正式庫，這一步只讀不寫）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- [ ] **第二個終端機**用 curl 打一張真的照片：

```bash
curl -s http://localhost:8000/photos/1 | python -m json.tool
```

  預期看到六個鍵、`metadata` 裡四個欄位、`image_url` 是 `/photos/1/image` 或 `null`。
  正式庫的前兩張舊照片沒有原圖，`image_url` 應該是 `null`——那是**預期行為**，不是 bug。
  正式庫有哪些 id 可以先查：`psql -d PersonalDocAI -c "SELECT id FROM photo ORDER BY id;"`
  （id 1／2 若已不存在就換一個查得到的，這一步只是肉眼看一下，不是驗收條件）。

---

## 5. ASCII 圖：這支端點在整個系統的位置

```text
  瀏覽器（Phase 39／40 的唯讀彈窗）
        │
        │  GET /photos/7
        ▼
  ┌────────────────────────────────────────────────┐
  │ app/api/routers/photos.py                      │
  │   get_photo_detail(photo_id)                   │
  │     ① fetch_photo(7)  ── 沒這列 ──► 404        │
  │     ② 有這列 → 組 PhotoDetailOut → 200         │
  │        （不看圖、不算向量、不寫任何東西）      │
  └────────────────────────────────────────────────┘
        │                              ▲
        │ 唯一的資料來源               │ 零 SQL：router 不自己寫 SQL
        ▼                              │
  ┌────────────────────────────────────────────────┐
  │ app/repositories/photo_repository.py           │
  │   fetch_photo() → SELECT {PHOTO_COLUMNS}       │
  │   （text／category／location／items／          │
  │     content_time／original_path／              │
  │     thumbnail_path／uploaded_at 全都在）       │
  └────────────────────────────────────────────────┘

  回應長相：
  {
    "id": 7,
    "text": "一張 Target 收據，買了可樂。",
    "metadata": { "category": "收據", "location": "Target",
                  "items": ["可樂"], "content_time": "2026-08-10" },
    "thumbnail_url": "/photos/7/thumbnail",   ← 路徑 NULL 時是 null
    "image_url":     "/photos/7/image",       ← 路徑 NULL 時是 null
    "uploaded_at":   "2026-08-18T10:00:00+08:00"
  }

  （這張是「已經定案在收據」的照片，所以 category 是「收據」；
    剛上傳、還沒歸類的照片這裡會是「未分類」——見 §7 陷阱 8）
```

---

## 6. 驗收清單

- [ ] 七顆新測試**先紅後綠**（紅的證據要留在你的紀錄裡，不是直接寫綠的）
- [ ] `pytest -q` ＝ **365 passed ＋ 2 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] `/openapi.json` 運算元 ＝ **20**，且 `"get" not in paths.get("/photos", {})`
- [ ] `/openapi.json` 的 DELETE 動詞仍是 **0**（design4 §6 有列）——這一條由既有的
      `tests/integration/test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞`
      守著，**本 phase 不必新寫一顆**，只要確認它仍是綠的
- [ ] `tests/integration/test_folders_endpoint.py` 與 `tests/integration/test_tasks.py`
      **一個字都沒改** 且仍全綠（清單契約沒被本 phase 波及）
- [ ] 回應 JSON 裡搜不到 `data/`、`original_path`、`thumbnail_path`、`embedding`
- [ ] router 零 SQL：新端點只呼叫 `photo_repository.fetch_photo()`，沒有自己開連線或送 SQL。
      判準用既有那顆掃碼測試 `tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層`
      （它掃的是 `psycopg`／`get_connection`／`cursor(`／`.execute(` 四個關鍵字），確認它仍是綠的即可。
      **不要**改用 `grep SELECT/INSERT/UPDATE` 判斷——`photos.py` 本來就有一行中文註解寫著「一條 UPDATE」，
      那不是 SQL，只是註解
- [ ] 只動到四個檔。查法要分兩條指令，因為新建的檔案**還沒 `git add`**（本增量全程不 commit），
      `git diff` 看不到未追蹤的檔案：

```bash
git diff --stat -- app tests    # 恰好三個檔：app/schemas/photo.py、app/api/routers/photos.py、
                                #             tests/integration/test_ask_three_paths.py
git status --short -- app tests # 另有 ?? tests/integration/test_photo_detail.py（本 phase 新建）
```

---

## 7. 常見陷阱

1. **路徑撞車的錯覺**：專案已經有 `GET /photos/{photo_id}/thumbnail` 與 `/image`
   （還有別的 router 掛的 `POST /photos/{photo_id}/entities`、`/entity-suggestion`、`/task`）。
   新增 `GET /photos/{photo_id}` **不會**互相吃掉：預設的 `{參數}` 只吃「一段、不含斜線」的字，
   所以 `/photos/{photo_id}` 比對不到 `/photos/7/image`——不是靠先後順序，是路徑形狀本來就不同。
   但要注意：**不要**把新端點寫成 `@router.get("/photos/{photo_id:path}")`，那個 `:path` 轉換器
   會連斜線一起吃（`7/image` 也算一個值），真的會撞車。

2. **`content_time` 忘記轉字串**：資料庫給的是 `date` 物件，`PhotoMetadata.content_time` 宣告的是
   `str | None`。忘了 `.isoformat()` 會在 Pydantic 驗證時炸掉。既有的 `_ingest_image` 與
   `assign_folder` 都已經這樣寫，照抄同一行就好。

3. **`uploaded_at` 不要轉字串**：它宣告成 `datetime`，Pydantic 自己會序列化成 ISO 字串
   （`app/schemas/folder.py` 的 `PhotoSummary` 就是這樣）。手動 `.isoformat()` 反而型別不合。

4. **`items` 是 PostgreSQL 陣列（`text[]`）**：不必自己包 `list(...)`。
   既有的 `assign_folder` 就是直接 `items=row["items"]` 丟進 `PhotoMetadata`（同一個模型、同一種來源），
   所以照抄就對了。同一支函式在餵 `build_document` 時寫成 `list(photo["items"])`，
   那是為了讓合併文字那一段拿到純 Python list，與本端點無關——別跟著抄。

5. **把「檔案不在」誤判成 404**：這是本 phase 最容易寫錯的一條。
   `_send_photo_file` 有三個 404 條件（沒這列／路徑 NULL／檔案不在），
   **不要**照抄過來。詳情端點只有一個 404 條件：`fetch_photo` 回 `None`。

6. **順手「優化」清單端點**：看到 `GET /folders/{id}` 只回五鍵，很容易想「乾脆一起回 metadata」。
   那正是 design4 §1.2 被否決的方案（grill Q3 選項 A）。**不要做。**

7. **端點數字改錯地方**：`tests/integration/test_camera_endpoints.py` 也提到 17／19，
   但那顆測試**沒有斷言總數**（只斷言三支相機端點在、WS 不在），所以**不用改**。
   全系統唯一斷言總數的是 `test_ask_three_paths.py::test_端點數不變`。

8. **以為剛上傳的照片 `category` 就是 VLM 建議的那個**（寫測試最常撞到的一條）：
   不是。Phase 20 起上傳一律先進收件箱，`_ingest_image` 寫進資料庫的 `category` 是
   **`inbox["name"]`＝「未分類」**；VLM 的建議只出現在 201 回應的 `suggested_folder`，
   另外存進 `suggested_category` 那一欄（本端點不外送）。要看到 `category` 變成「收據」，
   必須先呼叫 `PATCH /photos/{id}/folder` 定案。所以第 2 顆測試請用「詳情的 metadata
   ＝上傳回應的 metadata」來比，不要手寫期望值。
