# Phase 4：上傳 router 骨架與圖片格式檢查（415）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 在 `app/api/routers/photos.py` 做出 `POST /photos` 端點並掛進 `main.py`，落實第一條規則——**非 JPEG/PNG 的檔案一律失敗（HTTP 415），而且不進行任何後續處理**。

---

## 前置條件

- 需要已完成的 phase：**Phase 2**（分層骨架與 `config.ALLOWED_CONTENT_TYPES`）、**Phase 3**（`photo_repository` 可用，用來確認「照片數量為 0」；2026-08-19 起 Phase 3 亦含 `tests/` 的 TDD 基礎結構——conftest 指向測試庫＋每測清空，12 個測試全綠）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

上傳流程的第一關是「這是不是圖片檔」。design.md 把它放在最前面，理由很實際：**不是圖片就不該浪費 AI 的時間**，也絕對不能留下任何資料。

分層架構把這件事放在 **router 層**：格式檢查屬於「HTTP 請求的輸入驗證」，是 router 的職責，不該下放到 service。這一步先把 router 的「殼」做出來：能接收 multipart 上傳的檔案、能判斷格式、不合格就回 415。合格的檔案暫時只回一段佔位訊息（Phase 5 接上看圖、Phase 6 接上寫入後就會換掉）。

> 🔄 **2026-08-19 更新（dev-prompt `phase0819.md`）：本 phase 改採 TDD＋BDD**——先寫測試（步驟 0）看它失敗（端點不存在 → 404），再照步驟 1〜2 實作讓它轉綠。整合測試用 FastAPI 的 **TestClient**（in-process 呼叫，不經網路），以 Given/When/Then 結構直接對應 `docs/spec/features/上傳照片.feature` 的 **Rule U1**「非圖片格式上傳失敗＋照片數量為 0」。**正式驗證以 pytest 為準**；下方 curl 驗收保留為手動輔助——0818 階段C 已證實部分自動化沙箱環境會擋 localhost 連線（curl 回 000），TestClient 不經網路、不受影響。

**名詞**：
- **APIRouter**＝FastAPI 用來「把一組端點打包成一個模組」的物件。寫好之後在 `main.py` 用 `app.include_router(...)` 掛上去，端點就生效了。
- `multipart/form-data`＝瀏覽器上傳檔案時用的 HTTP 格式，一次可以夾帶檔案與其他欄位。
- `content_type`（也叫 MIME type）＝檔案自報的類型字串，例如 `image/jpeg`、`text/plain`。
- `UploadFile`＝FastAPI 用來接收上傳檔案的物件：`.content_type` 是檔案自報的類型，`.file.read()` 可以讀出檔案內容。參數寫成 `file: UploadFile = File(...)`，就是告訴 FastAPI「從 multipart 表單裡拿名叫 `file` 的檔案欄位，而且必填」。
- **HTTP 狀態碼 415**＝Unsupported Media Type，「你給的檔案類型我不支援」。

---

## ASCII 圖：本 phase 在分層與上傳流程中的位置

```
 POST /photos（multipart/form-data，欄位名 file）
        │
        ▼
 app/main.py  ── include_router ──▶ app/api/routers/photos.py
                                          │
 ┌────────────────────────────────────────┴─────────────────┐
 │ ① router 檢查 content_type      ★本 phase 做這格          │
 │    不是 image/jpeg 或 image/png                           │
 │      → 415，直接結束（不呼叫 service、不碰 repository）    │
 └──────┬───────────────────────────────────────────────────┘
        │ 是圖片（本 phase 先回一段佔位訊息；②〜⑤ 之後才接上）
        ▼
   ② services/vlm_service.py 看圖            （Phase 5 接上）
        ▼
   ③ services/indexing_service.py 轉向量     （Phase 6 接上）
        ▼
   ④ repositories/photo_repository.py 寫入   （Phase 6 接上）
        ▼
   ⑤ 回 201 正式回應                         （Phase 6 接上）
```

---

## 逐步驟操作

### 步驟 0：先寫測試（TDD red）——2026-08-19 增補

**檔案：`tests/integration/test_photos_upload.py`**（7 個整合測試；`tests/conftest.py` 與目錄結構 Phase 3 已建好）：

```python
"""POST /photos 格式檢查的整合測試（TestClient，in-process 不經網路）。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U1「上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗」
  Example「非圖片格式的檔案上傳失敗」：
    When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗 And 系統儲存的照片數量為 0
"""

import base64

from fastapi.testclient import TestClient

from app.main import app
from app.repositories import photo_repository as repo

client = TestClient(app)

# 一張合法的 1×1 PNG（與步驟 3 的 /tmp/sample.png 相同內容，70 bytes）
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_upload_non_image_returns_415_with_message():
    # When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗（415＋規格訊息）
    resp = client.post(
        # 注意：不能寫 b"這不是圖片"——Python 的 bytes literal 只允許 ASCII，
        # 會 SyntaxError；用 .encode() 產生同樣的 UTF-8 位元組。
        "/photos",
        files={"file": ("not_image.txt", "這不是圖片".encode(), "text/plain")},
    )
    assert resp.status_code == 415
    assert resp.json() == {"detail": "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"}


def test_upload_non_image_stores_nothing():
    # And 系統儲存的照片數量為 0（U1 第二句：不進行任何後續處理）
    client.post("/photos", files={"file": ("not_image.txt", b"x", "text/plain")})
    assert repo.count_photos() == 0


def test_upload_octet_stream_returns_415():
    # content_type 不在允許清單（未知二進位型別）也一律 415
    resp = client.post(
        "/photos",
        files={"file": ("mystery.bin", b"\x00\x01", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_upload_png_returns_201_placeholder():
    # PNG 通過格式檢查；Phase 6 之前先回佔位回應
    resp = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")})
    assert resp.status_code == 201
    assert resp.json() == {
        "accepted": True,
        "content_type": "image/png",
        "size": len(PNG_BYTES),
    }


def test_upload_jpeg_returns_201():
    # JPEG 也通過（本 phase 只驗 content_type，不驗檔案內容）
    resp = client.post(
        "/photos", files={"file": ("sample.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")}
    )
    assert resp.status_code == 201


def test_upload_missing_file_returns_422():
    # 沒夾帶檔案 → FastAPI 框架既有的 422，不另外發明行為
    resp = client.post("/photos")
    assert resp.status_code == 422


def test_openapi_has_photos_endpoint():
    # router 真的掛上 main.py（等效驗收第 6 項的 /docs 檢查）
    paths = client.get("/openapi.json").json()["paths"]
    assert "/photos" in paths and "post" in paths["/photos"]
```

**看它失敗（red）**：

```bash
python -m pytest tests/integration/test_photos_upload.py -q
```

預期 **6 紅 1 綠**：端點還不存在，POST /photos 回 404、openapi 沒有 `/photos`——這就是「功能還沒做」的正確紅燈。唯 `test_upload_non_image_stores_nothing` 在紅燈階段會**空洞通過**（它斷言的是「沒有寫入」這個副作用不存在；端點 404 時本來就什麼都沒寫，天然成立）——實作後它的價值在於：若有人誤在 415 路徑前加寫入邏輯，它會立刻轉紅。Phase 3 的 12 個測試全程須維持綠燈。接著照步驟 1〜2 實作轉綠。

### 步驟 1：寫 `app/api/routers/photos.py`

```python
"""上傳照片的 router：POST /photos。

router 層的職責：收請求、檢查輸入、把失敗翻成 HTTP 狀態碼。
真正的商業邏輯（看圖、轉向量）在 services，資料寫入在 repositories。
"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core import config

# prefix 不設，因為端點路徑就是 /photos；tags 只影響 /docs 的分組顯示
router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201)
def upload_photo(file: UploadFile = File(...)) -> dict:
    """上傳照片。

    第一關：檔案格式必須是 JPEG 或 PNG，否則回 415 且不做任何後續處理。
    （刻意不檢查檔案大小——已釐清的決策是「不設上限」。）
    """
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    image_bytes = file.file.read()

    # TODO(Phase 5)：接上 services/vlm_service.py 看圖
    # TODO(Phase 6)：接上 services/indexing_service.py 轉向量、
    #                repositories/photo_repository.py 寫入，
    #                並把下面的佔位回應換成 schemas/photo.py 的 UploadResponse
    return {
        "accepted": True,
        "content_type": file.content_type,
        "size": len(image_bytes),
    }
```

### 步驟 2：在 `app/main.py` 掛上這個 router

把 Phase 2 寫的 `main.py` 改成：

```python
"""FastAPI app 組裝：掛上 photos router（ask router 到 Phase 11 才掛）。"""

from fastapi import FastAPI

from app.api.routers import photos

app = FastAPI(title="Visual Memory RAG")

app.include_router(photos.router)
# TODO(Phase 11)：app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}
```

### 步驟 3：準備兩個測試用檔案

```bash
cd /Users/linjunting/personalDocAI

# 一張真的 PNG（1×1 測試用小圖，像素顏色不重要，重點是一個合法的 PNG 檔）
python - <<'PY'
import base64, pathlib
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
pathlib.Path("/tmp/sample.png").write_bytes(png)
PY

# 一個非圖片檔
echo "這不是圖片" > /tmp/not_image.txt
```

### 步驟 4：啟動服務

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

（保持這個視窗跑著，另開一個終端機視窗做驗收——**新視窗一樣要先 `cd` ＋ `source .venv/bin/activate`**。）

---

## 驗收標準

0. **pytest 全綠（TDD green，2026-08-19 增補；正式驗證以此為準）**
   ```bash
   python -m pytest tests -q
   ```
   預期輸出：`19 passed`（Phase 3 的 12 個＋本 phase 的 7 個，無任何失敗）。

以下 `curl` 指令為**手動輔助驗收**（沙箱環境會擋 localhost 連線時可只跑第 0 項），在**另一個終端機視窗**執行（步驟 4 的服務要保持跑著）。幾個參數的意思：`-F "file=@路徑"`＝用 multipart/form-data 夾帶檔案、欄位名叫 `file`；`;type=...`＝明確指定 content_type；`-i`＝連回應標頭一起印出（`| head -1` 只看第一行的狀態碼）；`-s`＝不印進度資訊。

1. **非圖片格式 → 415，且訊息正確**
   ```bash
   curl -i -s -X POST http://localhost:8000/photos \
     -F "file=@/tmp/not_image.txt;type=text/plain" | head -1
   curl -s -X POST http://localhost:8000/photos \
     -F "file=@/tmp/not_image.txt;type=text/plain"
   ```
   預期第一行：`HTTP/1.1 415 Unsupported Media Type`
   預期回應內容：`{"detail":"上傳檔案必須為常見圖片格式（如 JPEG、PNG）"}`

2. **非圖片上傳後，資料庫照片數量仍為 0**（規則 U1 的第二句）
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   python -c "from app.repositories import photo_repository as repo; print('照片數量:', repo.count_photos())"
   ```
   預期輸出：`照片數量: 0`

   > 若印出的不是 0，那是 Phase 3 手動試寫入留下的資料（正常情況下 Phase 3 驗收第 6 項已經清空）。先執行 `python -c "from app.repositories import photo_repository as repo; repo.clear_photos()"` 清空，再重跑第 1 項與本項。

3. **PNG 可以通過格式檢查**
   ```bash
   curl -i -s -X POST http://localhost:8000/photos \
     -F "file=@/tmp/sample.png;type=image/png" | head -1
   curl -s -X POST http://localhost:8000/photos \
     -F "file=@/tmp/sample.png;type=image/png"
   ```
   預期第一行：`HTTP/1.1 201 Created`
   預期回應內容：`{"accepted":true,"content_type":"image/png","size":70}`（步驟 3 產生的 1x1 PNG 固定是 70 bytes，所以 `size` 就是 70）

4. **JPEG 也可以通過**
   ```bash
   sips -s format jpeg /tmp/sample.png --out /tmp/sample.jpg >/dev/null
   curl -i -s -X POST http://localhost:8000/photos \
     -F "file=@/tmp/sample.jpg;type=image/jpeg" | head -1
   ```
   預期：`HTTP/1.1 201 Created`

5. **沒有夾帶檔案時，FastAPI 自己回 422**（框架既有行為，不另外發明）
   ```bash
   curl -i -s -X POST http://localhost:8000/photos | head -1
   ```
   預期：`HTTP/1.1 422 Unprocessable Entity`（或 `422 Unprocessable Content`，視版本而定）

6. **router 真的被掛上了**
   瀏覽器開 <http://localhost:8000/docs>，應該看到 `GET /health` 與 `POST /photos` 兩個端點，`POST /photos` 在 `photos` 這個分組底下。

---

## 常見問題

**Q1：`curl` 上傳回 `{"detail":[{"type":"missing","loc":["body","file"]...}]}`。**
表單欄位名稱必須是 `file`。指令要寫成 `-F "file=@路徑"`，不能用別的名字。

**Q2：明明是 PNG 卻被回 415。**
`curl` 猜測的 content_type 可能不是 `image/png`。用 `;type=image/png` 明確指定（驗收指令已經這樣寫）。真實瀏覽器上傳時會自動帶正確的類型。

**Q3：`Form data requires "python-multipart" to be installed`。**
少裝套件。執行 `uv pip install "python-multipart>=0.0.9"`（Phase 1 的 `requirements.txt` 已包含）。

**Q4：`404 Not Found`，端點根本不存在。**
`main.py` 忘了 `app.include_router(photos.router)`，或 import 路徑寫錯（要是 `from app.api.routers import photos`）。

**Q5：想不想順便擋「檔案太大」？**
**不要。** 已釐清的決策是「不設檔案大小上限」，design.md §10 明寫「沒有這個錯誤路徑」。多寫等於違反規格。

**Q6：允許的格式清單要不要放寬（例如加 webp、heic）？**
**不要。** `config.ALLOWED_CONTENT_TYPES` 就是 `image/jpeg` 與 `image/png` 兩個，規格寫的是「常見圖片格式（如 JPEG、PNG）」，多加就是自行擴張規格。

---

## 完成後的專案狀態

`POST /photos` 端點存在於 `api/routers/photos.py` 並已掛上 `main.py`，完整落實規則 U1：非 JPEG/PNG 的上傳一律 415、不進入任何後續處理、資料庫維持 0 筆；合格的圖片目前只會拿到一段佔位回應。`tests/integration/test_photos_upload.py` 的 7 個測試（含 U1 的 BDD 對應）與 Phase 3 的 12 個測試共 19 個全綠。
