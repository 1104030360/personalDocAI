# Phase 19：上傳存檔與讀圖端點（INSERT→寫檔→UPDATE，失敗全清；GET 縮圖／原圖）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。特別是：**不要**加快取、不要加 ETag、不要加圖片串流、不要加「重新產生縮圖」的維護端點——design1.md 沒寫的一律不做。

**目標：** 把 Phase 17 的三個檔案函式接進上傳流程（**先 INSERT 拿到 id → 寫原圖與縮圖 → UPDATE 把路徑補回去**，任何一步失敗就把檔案與資料列全部清乾淨再把錯誤往外丟），並開出兩個讀圖端點 `GET /photos/{id}/thumbnail`、`GET /photos/{id}/image`。

回應 JSON **本 phase 完全不動**（`thumbnail_url`、`suggested_folder`、`folders` 是 Phase 20 的事），`category` 的行為也**完全不動**（照舊存 VLM 給的值，Phase 20 才改成「未分類」）。

---

## 前置條件

- 需要已完成的 phase：**Phase 15**（`photo` 已有 `original_path` / `thumbnail_path` / `content_type` 三欄，`fetch_photo()` 的 SELECT 已把它們取回來）、**Phase 16**（資料夾資料層）、**Phase 17**（`storage_service` 四個公開函式 `save_original`／`make_thumbnail`／`absolute_path`／`remove_if_exists`、`config.DATA_DIR`、conftest 的 `isolated_data_dir`、`tests/fakes.py` 的 `make_png_bytes()` / `make_jpeg_bytes()`）、**Phase 18**（VLM 收 `folders` 參數）。
- 基線（開工前**實查**）：`pytest -q` 全綠。數字＝ **110**（Phase 15〜17 完成時的 103 ＋ Phase 18 的 7）。動手前先跑一次記下來。
- 環境：需要測試資料庫；本 phase 的測試**不需要 Ollama**。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

### 一、為什麼順序是「INSERT → 寫檔 → UPDATE」

檔名要用 `photo.id`（`data/photos/7.png`），而 `id` 是資料庫在 INSERT 當下才配發的。所以順序只能是：

1. **INSERT**：把文字、四欄位、向量寫進去，拿到 `id`。此時三個路徑欄位還是 `NULL`。
2. **寫檔**：`save_original(id, …)` ＋ `make_thumbnail(id, …)`。
3. **UPDATE**：把兩個路徑與 `content_type` 補回那一列。

有人會問：那第 2 步失敗怎麼辦？資料庫裡不就留下一列「有資料但沒有圖」的照片？

會，所以**要自己收拾**：一旦 2 或 3 出錯，就 `remove_if_exists()` 把可能已經寫出去的兩個檔案刪掉、`delete_photo()` 把那一列刪掉，然後**把原始錯誤重新丟出去**（re-raise）。結果就是「跟沒上傳過一樣」，而使用者收到 500。

**為什麼要 re-raise、不吞掉錯誤？** 這是 design.md 一路守到現在的原則：系統壞掉就要老實說壞掉（回 500 並在伺服器 log 留下原始 traceback），不可以假裝成功、也不可以偽裝成別的錯誤碼。既有測試 `test_embedding失敗回500` 守的就是這條。

> 🤔 **為什麼不用資料庫交易（transaction）把它包起來？** 因為交易只管得到資料庫，管不到磁碟上的檔案——就算 rollback 了，寫出去的圖還在。既然檔案本來就得手動清，資料列也一起手動清，邏輯反而單純一致。本專案的 `get_connection()` 是「一次呼叫一條連線、結束就 commit」，硬要跨三次呼叫做交易得改連線管理，屬過度設計。

### 二、讀圖端點：三種情況都回 404

`GET /photos/{id}/thumbnail` 與 `GET /photos/{id}/image` 的邏輯一模一樣，只差讀哪一個路徑欄位：

- 這個 `id` 根本沒有這一列 → **404**
- 有這一列，但路徑欄位是 `NULL` → **404**（正式庫那 2 張遷移進來的舊照片就走這條，design1.md §10 明訂「不假裝有圖」，前端顯示占位）
- 有路徑，但磁碟上的檔案不見了 → **404**
- 都在 → `FileResponse(實際檔案位置, media_type=該列的 content_type)` → **200**

### 三、⚠️ 一個一定會踩到的坑：既有測試的「假圖片位元組」

從本 phase 起，上傳流程會**真的用 Pillow 把 bytes 打開**來做縮圖。專案裡好幾個既有測試用的是這種假位元組：

```python
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"
```

Pillow 打不開它，會拋 `UnidentifiedImageError` → 走進清理路徑 → 回 500 → 那些「預期 201」的測試全部變紅。

所以本 phase 有一件**必做的維護工作**：把「預期上傳成功」的測試，圖片位元組換成 Phase 17 加好的 `make_png_bytes()` / `make_jpeg_bytes()`。步驟 5 會把**每一個要改的檔案與行號逐一點名**，不留任何「視情況修」的模糊空間。

反過來說，**走失敗路徑的測試不必改**（415 在看圖前就擋掉、422 在寫檔前就擋掉、embedding 失敗也在 INSERT 前就炸掉），它們繼續用假位元組反而是好事——正好證明那些路徑真的沒去解碼圖片。

**名詞**：

- **`FileResponse`**＝FastAPI（其實是底層的 Starlette）提供的一種回應，作用是「把磁碟上的某個檔案直接送給瀏覽器」。你不必自己讀檔、不必自己設 `Content-Length`，它會處理好。
- **`media_type`**＝告訴瀏覽器「這串位元組是什麼東西」的標示（就是 HTTP 的 `Content-Type`）。填 `image/png` 瀏覽器就會把它當圖片顯示；填錯或不填，可能變成下載檔案。
- **re-raise（重新丟出）**＝在 `except` 區塊裡寫一行 `raise`（後面什麼都不接），意思是「我處理完善後了，但這個錯誤還是要繼續往上傳」。原始的錯誤型別與 traceback 都會完整保留。
- **`try / except / raise`**＝Python 的錯誤處理語法。`try:` 裡放可能出錯的動作，出錯時跳到 `except:` 收拾，本專案在收拾完之後 `raise` 讓它繼續往外。
- **原子性（atomic）**＝「要嘛全做完、要嘛當作沒發生」。既有的 `insert_photo` 是一條 SQL 所以天生原子；本 phase 的「INSERT＋寫檔＋UPDATE」不是一條 SQL，所以靠手動清理來達到同樣效果。
- **`UPDATE … SET … WHERE id = …`**＝SQL 的「改某一列的某幾個欄位」。
- **`DELETE FROM … WHERE id = …`**＝SQL 的「刪掉某一列」。本專案沒有刪除照片的 API，這個函式**只給上傳失敗時清理用**。
- **`monkeypatch.setattr(模組, "函式名", 假函式)`**＝pytest 的招式，暫時把某個模組裡的函式換掉（測完自動還原）。本 phase 用它模擬「寫檔失敗」。
- **`raise_server_exceptions=False`**＝`TestClient` 的參數。預設情況下伺服器內部的例外會直接往測試裡丟；設成 `False` 才會像真的伺服器那樣回一個 500 回應，方便斷言。
- **`UnidentifiedImageError`**＝Pillow 在「這串位元組我認不出是什麼圖」時拋的錯誤。

---

## ASCII 圖：上傳的新順序與失敗清理路徑

```
POST /photos  (multipart/form-data, 欄位 file)
│
├─ ① content_type 檢查 ────── 非 JPEG/PNG ──▶ 415
│                                             （不看圖、不寫檔、不碰資料庫）
├─ ② folders = list_folders()
│    vlm.understand(bytes, ct, folders) ── 看不懂／text 空白 ──▶ 422
│                                             （不寫檔、不碰資料庫）
├─ ③ build_document → embed_document ────── 失敗 ──▶ 500
│                                             （不寫檔、資料庫還沒動過）
│
├─ ④ INSERT photo ──▶ 拿到 id = 7    ← 檔名要用 id，所以 INSERT 一定先做
│                     （此時 original_path / thumbnail_path / content_type 都是 NULL）
│   ┌────────────────── 從這裡開始有東西要收拾 ──────────────────┐
│   │                                                            │
│   ├─ ⑤ save_original(7, bytes, "image/png")  → data/photos/7.png
│   ├─ ⑥ make_thumbnail(7, bytes, "image/png") → data/thumbs/7.png
│   └─ ⑦ UPDATE photo SET original_path, thumbnail_path, content_type
│       │                                                        │
│       ├── 三步都成功 ─────────────────────────▶ 201            │
│       │      （回應 JSON 本 phase 不動：id / text / metadata）   │
│       │                                                        │
│       └── ⑤⑥⑦ 任何一步炸掉                                     │
│              remove_if_exists(原圖路徑)   ← 可能還是 None，函式吃得下
│              remove_if_exists(縮圖路徑)                          │
│              delete_photo(7)                                    │
│              raise  ← 不吞錯，原始錯誤往外丟，框架回 500          │
│              結果：磁碟沒檔案、資料庫沒那一列，跟沒上傳過一樣      │
│   └────────────────────────────────────────────────────────────┘


GET /photos/{id}/thumbnail        GET /photos/{id}/image
        │                                 │
        └──────────── 同一段邏輯，只差讀哪一欄 ────────────┘
                      row = fetch_photo(id)
                        ├ row is None            ─▶ 404
                        ├ 路徑欄位是 NULL        ─▶ 404 ← 遷移進來的舊照片走這條
                        ├ 檔案不在磁碟上         ─▶ 404
                        └ 都在 ─▶ FileResponse(absolute_path(路徑),
                                               media_type=row["content_type"]) ─▶ 200
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1 先寫新測試檔看它紅，步驟 2〜4 實作讓它綠，步驟 5 修既有測試的假圖片位元組，步驟 6 全量回歸。

### 步驟 1：先寫測試（紅）——新增 `tests/integration/test_photo_files.py`

```python
"""上傳存檔與讀圖端點的整合測試（design1.md §6、§7.4、§12）。

檔案一律寫在 conftest 的 isolated_data_dir 指定的暫存目錄，不會碰到專案的 data/。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, make_jpeg_bytes, make_png_bytes

TARGET_RECEIPT = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據", location="Target",
    items=["可樂", "洋芋片"], content_time="2026-08-10",
)


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _upload(client, payload=None, content_type="image/png", filename="a.png"):
    """上傳一張看得懂的照片。payload 預設是 Pillow 現產的真 PNG。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)
    if payload is None:
        payload = make_png_bytes(1200, 600)
    return client.post("/photos", files={"file": (filename, payload, content_type)})


def test_上傳後原圖與縮圖都寫進DATA_DIR(client):
    image_bytes = make_png_bytes(1200, 600)

    response = _upload(client, payload=image_bytes)

    assert response.status_code == 201
    photo_id = response.json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    # 資料庫存的是以 data/ 開頭的相對路徑（design1.md §6）
    assert row["original_path"] == f"data/photos/{photo_id}.png"
    assert row["thumbnail_path"] == f"data/thumbs/{photo_id}.png"
    assert row["content_type"] == "image/png"
    # 檔案真的在（換算後的實際位置在暫存目錄底下）
    原圖 = storage_service.absolute_path(row["original_path"])
    縮圖 = storage_service.absolute_path(row["thumbnail_path"])
    assert 原圖.is_file() and 縮圖.is_file()
    # 原圖位元組與上傳的一模一樣；縮圖被縮到長邊 512
    assert 原圖.read_bytes() == image_bytes
    with Image.open(io.BytesIO(縮圖.read_bytes())) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_jpeg上傳的副檔名是jpg(client):
    response = _upload(
        client, payload=make_jpeg_bytes(), content_type="image/jpeg", filename="a.jpg"
    )

    assert response.status_code == 201
    row = photo_repository.fetch_photo(response.json()["id"])
    assert row["original_path"].endswith(".jpg")
    assert row["thumbnail_path"].endswith(".jpg")
    assert row["content_type"] == "image/jpeg"


def test_讀縮圖端點回200且回的真的是圖片(client):
    photo_id = _upload(client).json()["id"]

    response = client.get(f"/photos/{photo_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_讀原圖端點回的位元組與上傳的完全相同(client):
    image_bytes = make_png_bytes(1200, 600)
    photo_id = _upload(client, payload=image_bytes).json()["id"]

    response = client.get(f"/photos/{photo_id}/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == image_bytes


def test_照片不存在讀圖回404(client):
    assert client.get("/photos/9999/thumbnail").status_code == 404
    assert client.get("/photos/9999/image").status_code == 404


def test_舊式資料沒有路徑讀圖回404(client):
    """design1.md §10：遷移進來的舊照片路徑是 NULL，讀圖 404，前端顯示占位。

    這裡直接用 repository 插一列（不走上傳端點），模擬遷移後的舊資料。
    """
    photo_id = photo_repository.insert_photo(
        text="遷移進來的舊照片", category="收據", location="Target",
        items=["可樂"], content_time=None,
        embedding=FakeEmbeddings().embed_query("收據"),
    )["id"]

    row = photo_repository.fetch_photo(photo_id)
    assert row["original_path"] is None
    assert row["thumbnail_path"] is None
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    assert client.get(f"/photos/{photo_id}/image").status_code == 404


def test_檔案被刪掉後讀圖也回404(client):
    photo_id = _upload(client).json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    storage_service.absolute_path(row["thumbnail_path"]).unlink()

    # 資料庫有路徑、磁碟沒檔案 → 一樣 404，不可以回 500
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    # 原圖還在，所以原圖端點仍然 200
    assert client.get(f"/photos/{photo_id}/image").status_code == 200


def test_寫檔失敗時檔案與資料列都不留(不擲出例外的client, monkeypatch):
    """design.md 的不吞錯原則：失敗回 500，而且不可以留下半筆資料或孤兒檔案。"""
    def 一定失敗(photo_id, image_bytes, content_type):
        raise RuntimeError("磁碟壞了")

    monkeypatch.setattr(storage_service, "make_thumbnail", 一定失敗)

    response = _upload(不擲出例外的client)

    assert response.status_code == 500
    assert photo_repository.count_photos() == 0, "失敗時不可以留下半筆資料"
    # 縮圖之前已經寫出去的原圖也要被清掉
    assert not list((config.DATA_DIR / "photos").glob("*")), "不可以留下孤兒檔案"


def test_更新路徑失敗時檔案與資料列都不留(不擲出例外的client, monkeypatch):
    """最後一步（UPDATE）失敗也要清乾淨——兩個檔案都已經寫出去了。"""
    def 一定失敗(photo_id, **kwargs):
        raise RuntimeError("資料庫斷線")

    monkeypatch.setattr(photo_repository, "update_photo_paths", 一定失敗)

    response = _upload(不擲出例外的client)

    assert response.status_code == 500
    assert photo_repository.count_photos() == 0
    assert not list((config.DATA_DIR / "photos").glob("*"))
    assert not list((config.DATA_DIR / "thumbs").glob("*"))


def test_415完全不寫檔(client):
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415
    # 連 data/ 這個資料夾都不該被建出來
    assert not config.DATA_DIR.exists()


def test_422完全不寫檔(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 422
    assert photo_repository.count_photos() == 0
    assert not config.DATA_DIR.exists()
```

跑一次確認它**紅**：

```bash
pytest tests/integration/test_photo_files.py -q
```

預期：大量失敗（`update_photo_paths` 不存在、`/photos/1/thumbnail` 回 404 因為根本沒這個路由⋯⋯）。這就是紅。

### 步驟 2：`photo_repository.py` 新增兩個函式

打開 `app/repositories/photo_repository.py`，把下面兩個函式接在 `reset_folders_and_photos()`（Phase 15 新增，位於 `clear_photos()` 之後）的後面、Phase 16 的資料夾函式 `list_folders()` 之前，讓照片「寫入類」的函式聚在一起（資料夾五函式與兩條檢索查詢維持在它們後面）：

```python
def update_photo_paths(
    photo_id: int,
    *,
    original_path: str,
    thumbnail_path: str,
    content_type: str,
) -> None:
    """把寫好的檔案路徑補回那一列（INSERT 之後、同一個請求之內完成）。

    為什麼要分兩次寫：檔名要用 photo.id，而 id 是 INSERT 當下才配發的，
    所以只能先 INSERT 拿 id、寫完檔再回來補路徑（design1.md §6）。
    """
    sql = """
        UPDATE photo
        SET original_path  = %(original_path)s,
            thumbnail_path = %(thumbnail_path)s,
            content_type   = %(content_type)s
        WHERE id = %(id)s;
    """
    params = {
        "original_path": original_path,
        "thumbnail_path": thumbnail_path,
        "content_type": content_type,
        "id": photo_id,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def delete_photo(photo_id: int) -> None:
    """刪掉一列照片。

    ⚠️ 這**不是**「刪除照片」功能——design1.md §15 明訂本增量不做刪除 API。
    它只給上傳流程的失敗清理用：INSERT 之後寫檔失敗時，
    要把那一列一起收掉，讓整次上傳「像沒發生過」。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM photo WHERE id = %(id)s;", {"id": photo_id})
```

### 步驟 3：改寫 `app/api/routers/photos.py` 的上傳流程

打開 `app/api/routers/photos.py`。

**3-1. 檔頭與 import 區**（第 1〜12 行）改成：

```python
"""照片 router：POST /photos（上傳）＋ GET /photos/{id}/thumbnail、/image（讀圖）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.photo import PhotoMetadata, UploadResponse
from app.services import indexing_service, storage_service, vlm_service
```

（改動兩處：多 import `FileResponse`、`services` 那行多 import `storage_service`；檔頭 docstring 更新。）

另外，第 35 行有一句從本 phase 起**不再屬實**的註解（v4 時代原圖真的不落地，現在會寫進磁碟了）：

```python
    # 原始照片只存在這個變數裡，函式結束就消失——絕不寫進磁碟或資料庫
```

改成：

```python
    # 讀出整個上傳檔的位元組：看圖、轉向量用它，第 ⑤ 段也用它寫原圖與縮圖
    #（「不儲存原始照片檔」是 v4 的舊決策，design1.md §1.1 已明示推翻）
```

**3-2. 上傳函式的第 ④ 段之後**：把原本的

```python
    # ④ 一條 INSERT 寫入
    row = photo_repository.insert_photo(
        text=understanding.text,
        category=understanding.category,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time,
        embedding=embedding,
        uploaded_at=now,
    )

    # ⑤ 回 201
    return UploadResponse(
```

改成（中間插入寫檔與補路徑那一段，並把回應的編號改成 ⑥）：

```python
    # ④ 一條 INSERT 寫入（先拿到 id——檔名要用它）
    row = photo_repository.insert_photo(
        text=understanding.text,
        category=understanding.category,
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

    # ⑥ 回 201（回應內容本 phase 不動；thumbnail_url 等欄位是 Phase 20 才加）
    return UploadResponse(
```

**3-3. 檔案最後面**加上兩個讀圖端點與它們共用的小函式：

```python
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
```

> 📌 這兩個端點**不需要**寫 `response_model`：FastAPI 看到回傳型別是 `Response` 的子類別（`FileResponse` 就是）就會直接把它送出去，不做任何序列化。

### 步驟 4：跑新測試看它轉綠

```bash
pytest tests/integration/test_photo_files.py -v
```

預期最後一行：`11 passed`（11 個測試函式）。

### 步驟 5：修既有測試的「假圖片位元組」（**逐一點名，不准漏**）

現在跑全量會看到既有測試變紅：

```bash
pytest -q
```

原因就是前面說的：那些測試餵給上傳端點的是 Pillow 打不開的假位元組。下面**五個檔案、五處**要改，一處都不能少：

| # | 檔案 | 位置 | 現在的內容 | 改成 |
|---|---|---|---|---|
| 1 | `tests/integration/test_upload_feature.py` | 第 21 行 | `PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"` | `PNG_BYTES = make_png_bytes()` |
| 2 | `tests/integration/test_upload_bilingual.py` | 第 14 行 | 同上 | `PNG_BYTES = make_png_bytes()` |
| 3 | `tests/integration/test_upload_design_rules.py` | 第 19 行 | 同上 | `PNG_BYTES = make_png_bytes()` |
| 4 | `tests/integration/test_photos_upload.py` | 第 75 行（`test_upload_jpeg_understood_returns_201` 內） | `b"\xff\xd8\xff\xe0fakejpeg"` | `make_jpeg_bytes()` |
| 5 | `tests/integration/test_error_paths.py` | 第 70 行（`test_大檔案照樣可以上傳` 內） | `大檔案 = b"\x89PNG\r\n\x1a\n" + b"0" * (12 * 1024 * 1024)` | `大檔案 = make_large_png_bytes()`（見 5-1） |

三個檔案（#1〜#3）的 import 也要跟著加：在既有的 `from tests.fakes import ...` 那一行把 `make_png_bytes` 加進去，例如 `test_upload_bilingual.py` 第 12 行

```python
from tests.fakes import FakeVLM
```

改成

```python
from tests.fakes import FakeVLM, make_png_bytes
```

`test_upload_feature.py` 第 15 行

```python
from tests.fakes import FakeVLM, understanding_for_text
```

改成

```python
from tests.fakes import FakeVLM, make_png_bytes, understanding_for_text
```

`test_upload_design_rules.py` 第 17 行

```python
from tests.fakes import FakeEmbeddings, FakeVLM
```

改成

```python
from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes
```

`test_photos_upload.py` 第 17 行

```python
from tests.fakes import FakeVLM
```

改成

```python
from tests.fakes import FakeVLM, make_jpeg_bytes
```

並把第 74〜76 行

```python
    resp = client.post(
        "/photos", files={"file": ("sample.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")}
    )
```

改成

```python
    resp = client.post(
        "/photos", files={"file": ("sample.jpg", make_jpeg_bytes(), "image/jpeg")}
    )
```

> ✅ **`test_photos_upload.py` 第 22 行的 `PNG_BYTES` 不必改**——它是 base64 解出來的**真實 1×1 PNG**，Pillow 打得開，縮圖會原樣保留 1×1。

**5-1. `tests/fakes.py` 補一個「真的很大的 PNG」**

`test_大檔案照樣可以上傳` 要證明「系統沒有檔案大小上限」，所以檔案得真的大。純色圖片會被 PNG 壓成幾 KB，證明不了什麼，所以要用**隨機雜訊**（壓不掉）。在 `tests/fakes.py` 的 `make_jpeg_bytes()` 後面加上：

```python
def make_large_png_bytes(side: int = 1200) -> bytes:
    """產生一張『真的很大』的 PNG（約 4 MB 以上），用來證明系統沒有檔案大小上限。

    刻意用隨機雜訊：純色圖片會被 PNG 壓成幾 KB，撐不出檔案大小。
    os.urandom(n)＝n 個隨機位元組；每個像素 3 個位元組（RGB）。
    """
    buffer = io.BytesIO()
    pixels = os.urandom(side * side * 3)
    Image.frombytes("RGB", (side, side), pixels).save(buffer, format="PNG")
    return buffer.getvalue()
```

並把 `tests/fakes.py` 最上方的 import 補一個 `os`：

```python
import hashlib
import io
import math
import os
from datetime import datetime
```

**5-2. 改 `test_error_paths.py`**

第 15 行

```python
from tests.fakes import FakeVLM
```

改成

```python
from tests.fakes import FakeVLM, make_large_png_bytes
```

第 69〜74 行整個函式改成：

```python
def test_大檔案照樣可以上傳(client):
    大檔案 = make_large_png_bytes()   # 真的圖、真的大（隨機雜訊壓不掉）
    assert len(大檔案) > 3 * 1024 * 1024, "這個測試要用真的大檔才有意義"

    response = client.post("/photos", files={"file": ("big.png", 大檔案, "image/png")})

    assert response.status_code == 201, "規格明訂不設檔案大小上限"
```

> ✅ **`test_error_paths.py` 其餘用假位元組的地方一律不動**，而且**刻意**不動：
> - 第 61 行 `test_vlm看不懂回422且不寫入`：422 在寫檔之前就中斷了，位元組根本沒被解碼。
> - 第 144 行 `test_embedding失敗回500`：embedding 在 INSERT 之前就炸了，同理。
>
> 它們繼續用假位元組還能通過，正好**證明**這兩條失敗路徑真的沒有去碰圖片檔案。

### 步驟 6：全量回歸

```bash
pytest -q
```

預期：**基線顆數 ＋ 11 ＝ 121**，全綠。

順便確認兩份規格檔仍然全綠（本 phase 沒有改任何規格行為）：

```bash
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v
```

預期：12 條 Rule、14 個例子全綠。

### 步驟 7：手動實測（真的用瀏覽器看到圖）

自動化測試都寫在暫存目錄，所以「正式跑起來真的能看到圖」要親手確認一次。

視窗 A：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

視窗 B（需要本機 Ollama 有在跑，因為這裡走的是真 VLM）：

```bash
cd /Users/linjunting/personalDocAI
# 準備一張真的照片（沒有的話用手機拍一張存成 ~/Desktop/receipt.jpg）
curl -s -X POST http://localhost:8000/photos \
     -F "file=@$HOME/Desktop/receipt.jpg;type=image/jpeg" | python -m json.tool
```

記下回應裡的 `id`（假設是 3），然後：

```bash
ls -l data/photos data/thumbs
curl -s -o /tmp/thumb.png -w "縮圖 HTTP %{http_code}  型別 %{content_type}  大小 %{size_download}\n" \
     http://localhost:8000/photos/3/thumbnail
curl -s -o /tmp/full.jpg  -w "原圖 HTTP %{http_code}  型別 %{content_type}  大小 %{size_download}\n" \
     http://localhost:8000/photos/3/image
curl -s -o /dev/null -w "不存在的照片 HTTP %{http_code}\n" http://localhost:8000/photos/9999/thumbnail
```

預期：
- `data/photos/3.jpg` 與 `data/thumbs/3.jpg` 都在，縮圖明顯小很多
- 縮圖與原圖都是 `HTTP 200`、型別 `image/jpeg`
- 不存在的照片是 `HTTP 404`
- 直接在瀏覽器打開 `http://localhost:8000/photos/3/thumbnail`，**看得到圖**

最後確認正式庫那兩張舊照片（遷移進來、路徑是 NULL）真的回 404：

```bash
psql -d PersonalDocAI -c "SELECT id, category, original_path, thumbnail_path FROM photo ORDER BY id LIMIT 3;"
curl -s -o /dev/null -w "舊照片 1 HTTP %{http_code}\n" http://localhost:8000/photos/1/thumbnail
```

預期：SQL 顯示前兩列的兩個路徑都是空的；`curl` 印出 `舊照片 1 HTTP 404`。

---

## 驗收清單

- [ ] `photo_repository.py` 有 `update_photo_paths()` 與 `delete_photo()`，且 SQL 仍只出現在這個檔案：
      ```bash
      grep -rlnE "SELECT |INSERT INTO|UPDATE |DELETE FROM|TRUNCATE" app/ --include="*.py"
      ```
      預期輸出只有一行 `app/repositories/photo_repository.py`
- [ ] `photos.py` 的順序是 INSERT → 寫檔 → UPDATE：
      ```bash
      grep -n "insert_photo\|save_original\|make_thumbnail\|update_photo_paths\|remove_if_exists\|delete_photo\|raise$" app/api/routers/photos.py
      ```
      預期行號由小到大依序是 `insert_photo` → `save_original` → `make_thumbnail` → `update_photo_paths` → `remove_if_exists`（一行註解＋兩次呼叫）→ `delete_photo` → 單獨一行的 `raise`
- [ ] 失敗路徑是 **re-raise**（沒有把錯誤吞掉、沒有自己回別的狀態碼）：
      ```bash
      grep -n "except Exception" app/api/routers/photos.py
      ```
      預期恰好一處，且該區塊最後一行是單獨的 `raise`
- [ ] 兩個讀圖端點都在，且都用 `FileResponse` ＋ `media_type`：
      ```bash
      grep -n "@router.get\|FileResponse(" app/api/routers/photos.py
      ```
- [ ] 端點數量：`POST /photos`、`POST /ask`、`GET /`、`GET /health`、`GET /photos/{photo_id}/thumbnail`、`GET /photos/{photo_id}/image`——本 phase 淨增 **2** 個
      （2026-08-21 校準：本專案的 FastAPI 0.141 會把 `include_router()` 包成 `_IncludedRouter`、不攤平進 `app.routes`，直接列 `app.routes` 看不到 router 端點；改查 `/openapi.json`，與既有測試 `test_openapi_has_photos_endpoint` 同一慣例）：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      for p, ms in sorted(paths.items()):
          print(sorted(m.upper() for m in ms), p)
      "
      ```
- [ ] 回應 JSON **沒變**：`app/schemas/photo.py` 一行都沒改（`git diff --stat app/schemas/photo.py` 無輸出）
- [ ] `category` 行為**沒變**：`photos.py` 的 `insert_photo(... category=understanding.category ...)` 維持原樣（Phase 20 才改）
- [ ] `pytest tests/integration/test_photo_files.py -v` → `11 passed`
- [ ] 步驟 5 的五處假位元組**全部**改完；`test_error_paths.py` 第 61、144 行**刻意保留**假位元組
      ```bash
      grep -rn "fake image bytes\|fakejpeg" tests/ || echo "OK：預期成功的測試都改用真圖了"
      ```
      預期印出 `OK：預期成功的測試都改用真圖了`
- [ ] `pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v` 全綠（12 條 Rule、14 個例子）
- [ ] 步驟 7 的手動實測全部符合預期（含瀏覽器真的看到圖、正式庫舊照片 404）
- [ ] 手動實測產生的 `data/` **不在** `git status` 裡
- [ ] **全量 `pytest -q` 全綠**，顆數＝開工前基線 ＋ 11 ＝ **121**
- [ ] git commit：
      ```bash
      cd /Users/linjunting/personalDocAI
      git add app/api/routers/photos.py app/repositories/photo_repository.py \
              tests/fakes.py tests/integration/test_photo_files.py \
              tests/integration/test_upload_feature.py tests/integration/test_upload_bilingual.py \
              tests/integration/test_upload_design_rules.py tests/integration/test_photos_upload.py \
              tests/integration/test_error_paths.py
      git commit -m "feat: Phase 19 上傳存檔與讀圖端點——INSERT→寫檔→UPDATE 三步＋失敗清檔清列 re-raise、GET /photos/{id}/thumbnail 與 /image（路徑 NULL 或檔案不在一律 404），既有測試改用 Pillow 真圖，+11 tests"
      ```

---

## 常見問題

**Q1：測試報 `PIL.UnidentifiedImageError: cannot identify image file`。**
有測試把假位元組餵給上傳端點了。回到步驟 5 的表格逐一核對；漏掉的多半是自己後來新寫的測試。凡是「預期 201」的上傳測試，一律用 `make_png_bytes()` / `make_jpeg_bytes()`。

**Q2：為什麼不乾脆讓 `make_thumbnail` 失敗時「跳過縮圖」就好，不要整個上傳失敗？**
因為那樣會產生「有原圖沒縮圖」的半殘資料，瀏覽頁得多一套 fallback，錯誤還被藏起來。design.md 一路守的原則是「壞了就老實回 500」。真正的舊資料占位情境（路徑 NULL）是遷移造成的，那條路徑已經有明確設計（design1.md §10），不要拿它當藉口新增第二種半殘狀態。

**Q3：`delete_photo()` 會不會被誤用成「刪除照片功能」？**
函式 docstring 已經寫明它只給失敗清理用，而且沒有任何端點呼叫它。Phase 25 的「明確不做」核對會再檢查一次「沒有刪除端點」。

**Q4：`FileResponse` 需要額外裝套件（例如 aiofiles）嗎？**
不用。專案現有的 Starlette 版本自己就處理得了檔案回應。

**Q5：`test_檔案被刪掉後讀圖也回404` 為什麼要特地測？**
因為「資料庫說有、磁碟上沒有」是真實會發生的狀況（有人手動刪了 `data/`）。如果沒有 `is_file()` 那一道檢查，`FileResponse` 會在送出時炸掉變成 500，使用者看到的是「伺服器壞了」而不是「這張沒有圖」。

**Q6：讀圖端點要不要加權限檢查？**
不用。本專案是**單一使用者系統**（Clarify 定案、design1.md §15 重申），沒有登入、沒有擁有者概念。加權限＝發明規格沒有的東西。

**Q7：`GET /photos/{photo_id}/thumbnail` 會不會跟 `POST /photos` 的路由撞到？**
不會，路徑不同（多了 `/{photo_id}/thumbnail` 這一段），HTTP 方法也不同。

**Q8：可不可以順便加個 `Cache-Control` 讓瀏覽器快取縮圖？**
不要。side project、單機、資料量小，快取只會在開發時造成「改了圖卻沒更新」的困惑。design1.md 沒寫的一律不做。

**Q9：`test_寫檔失敗時檔案與資料列都不留` 為什麼用 `monkeypatch` 換掉 `make_thumbnail`，而不是真的弄壞磁碟？**
因為真的弄壞磁碟很難、也不可重現。`monkeypatch` 換一個「一定丟例外」的假函式，正好精準模擬「第 ⑥ 步失敗」，而且測完自動還原。

---

## 完成後的專案狀態

照片**真的存下來了，而且看得到**：上傳時先 INSERT 拿 id、寫原圖與縮圖、再把路徑補回那一列；三步之中任何一步失敗，檔案與資料列都會被清乾淨並老實回 500。`GET /photos/{id}/thumbnail` 與 `GET /photos/{id}/image` 兩個端點可以直接在瀏覽器打開看圖；遷移進來的舊照片（路徑 NULL）回 404，等前端顯示占位。

還沒做的是本增量的重點體驗：上傳後 `category` 仍照舊存 VLM 給的值、回應也還沒有 `suggested_folder` / `folders` / `thumbnail_url`。接下來 **Phase 20** 會把「一律先進未分類 ＋ 回傳建議與完整清單」的新流程接起來，並正式改版 `上傳照片.feature` 規格檔。

測試累計 ＝ 開工前基線 ＋ **11** ＝ **121**。
