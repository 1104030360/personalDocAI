# Phase 21：歸類端點（`PATCH /photos/{id}/folder`——採用現有資料夾或自建一個）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 做出「使用者在彈窗按下確認之後，後端到底做了什麼」的那個端點：把照片從「未分類」搬到指定資料夾（或當場自建一個），同時把 `category` 與 `embedding` 一起更新。

---

## 前置條件

- 需要已完成的 phase：
  - **Phase 15**（`folder` 表、`fetch_photo()` 的 SELECT 已含 `folder_id`）
  - **Phase 16**（`get_folder()`／`find_folder_by_name()`／`create_folder()`／`list_folders()`）
  - **Phase 20**（上傳一律進「未分類」、`UploadResponse` 已有 `folders` 清單、`schemas/photo.py` 已有 `FolderOut`）
- **開工前基線**：先執行 `pytest -q` 把「目前全綠的顆數」記下來（Phase 20 完成後為 **124**，2026-08-21 實查）。本 phase 完成後的顆數 ＝ 基線 **＋8 ＝ 132**。
- 環境：PostgreSQL@17 在 5433、測試庫 `PersonalDocAI_test` 已是最新 schema。**不需要 Ollama**（全程假件）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

Phase 20 之後，照片上傳完會躺在「未分類」，回應也把彈窗要用的資料備齊了。但彈窗上的三個按鈕按下去之後**沒有東西可以打**——本 phase 就是補上那個端點。

彈窗的三個選項，其實只對應**兩種**請求內容（design1.md §7.2）：

| 彈窗選項 | 送出的 body | 後端做的事 |
|---|---|---|
| ① 採用「收據」（AI 建議的那個） | `{"folder_id": 2}` | 查這個資料夾在不在，在就用它 |
| ② 改選其他現有資料夾（下拉選單） | `{"folder_id": 4}` | 同上——**和①走完全一樣的路** |
| ③ 自建新資料夾 | `{"name": "專案X", "description": "跟課程作業有關的照片"}` | 先確認沒重名；資料夾要等向量算好才建（見下） |
| （右上角 ×／按 Esc 關掉） | 不打這個端點 | 照片留在「未分類」 |

①和②在後端是同一件事，這是刻意的：**少一條路就少一種出錯方式**。前端要顯示成兩個按鈕是前端的事（Phase 23）。

### 這個端點為什麼要重算 embedding

上傳當下的向量是用「未分類」合併出來的（design1.md §2、§7.3）。如果歸類只改 `category` 字串而不動向量，會變成：

- **條件查詢**（`category ILIKE '收據'`）→ 沒問題，它讀的是欄位。
- **語意查詢**（向量比對）→ 這張照片的向量裡帶著「類別: 未分類」，少掉了「收據」這個訊號。

所以歸類成功時，要用**新的資料夾名稱**重跑一次 `build_document` → `embed_document`，把向量整條換掉。四個 metadata 欄位裡只有 `category` 變，其餘三欄（location／items／content_time）原封不動。

### 順序很重要：檢查與算向量在前，寫資料庫全部在最後

端點裡的動作順序不是隨便排的：

```
… → 404／409 檢查 → build_document → embed_document（可能失敗）
  →（自建那條路才有）create_folder → 一條 UPDATE（同時寫三個欄位）
```

**所有會寫資料庫的動作都排在 embedding 之後**，於是：

- embedding 算失敗（Ollama 沒開、模型爆炸）→ 直接 500，**資料庫完全沒動**：照片那一列的 `folder_id`、`category`、`embedding` 三個欄位全部維持原狀，也**不會留下任何空資料夾**。這條保證**沒有例外**——不會出現「分類改了但向量還是舊的」或「資料夾建了但照片沒歸進去」這種半調子狀態。
- 自建那條路做得到這件事，靠的是一個小安排：算向量要用的 `category` **直接拿請求裡的 `name`**（Pydantic 驗證器已把前後空白去掉，跟之後 `create_folder` 存進去的名稱一字不差）——不必先把資料夾建出來才知道要填什麼，`create_folder` 就能等 embedding 成功之後再做。
- 三個欄位是**同一條 UPDATE** 寫進去的，資料庫層面天然是一次完成的動作，不可能只寫到一半。

**名詞**：

- **PATCH**＝HTTP 動詞，語意是「只改這個東西的一部分」。相對於 PUT（整個換掉）。這裡只改「照片屬於哪個資料夾」，其他欄位不碰，所以用 PATCH。
- **404 Not Found**＝你指名的東西不存在（這裡有兩種：照片不存在、資料夾不存在）。
- **409 Conflict**＝請求本身沒問題，但和「現在的狀態」衝突。自建資料夾撞到已存在的名稱就是典型的 409——不是你寫錯格式（那是 422），而是這個名字已經有人用了。
- **422 Unprocessable Entity**＝送來的資料格式／內容不合規則，FastAPI 對「請求 body 驗證失敗」的預設回應碼。
- **model validator（模型驗證器）**＝Pydantic 提供的掛勾。`@model_validator(mode="after")` 表示「所有欄位各自檢查完之後，再跑這個函式做整體檢查」。適合用來表達「A 和 B 只能給一個」這種**跨欄位**規則——單一欄位的型別檢查做不到這件事。在裡面 `raise ValueError(...)`，FastAPI 就會回 422。
- **恰一（exactly one）**＝`folder_id` 和 `name` 必須「有且只有一個」有值。兩個都給、兩個都不給，都是 422。
- **`RETURNING`**＝PostgreSQL 的語法，讓 `UPDATE`／`INSERT` 在改完之後**順便把那一列回傳**。省掉「改完再 SELECT 一次」的第二趟往返，也保證拿到的就是剛剛寫進去的內容。
- **大小寫不敏感（case-insensitive）**＝比對時不分大小寫，`project x` 和 `Project X` 視為同一個。資料夾重名判斷用的是 Phase 16 的 `find_folder_by_name()`（SQL 寫成 `lower(name) = lower(%s)`）。
- **`parametrize`**＝pytest 的裝飾器，讓同一個測試函式帶不同參數各跑一次；pytest 會把每一組算成一個獨立測試。
- **fixture**＝pytest 幫測試準備好的東西（這裡是「一張已經上傳好、躺在未分類的照片」）。

---

## ASCII 圖：兩種 body 的分支與錯誤碼決策樹

```
              PATCH /photos/{photo_id}/folder     body 只有兩種長相
                              │
        ┌─────────────────────▼──────────────────────┐
        │ ⓪ Pydantic 先驗 body（AssignFolderRequest） │
        │    folder_id 與 name 恰好一個有值？          │
        └─────────────────────┬──────────────────────┘
                否 ┌──────────┴──────────┐ 是
                   │ 兩個都給            │
                   │ 兩個都不給          │
                   │ name 去空白後是空的 │
                   ▼                     │
               ┌───────┐                 │
               │  422  │                 │   （FastAPI 自動回，端點函式根本沒被呼叫）
               └───────┘                 │
                                         ▼
                       ┌──────────────────────────────────┐
                       │ ① fetch_photo(photo_id)          │
                       └─────────────┬────────────────────┘
                            None ────┴──▶ ┌───────────────────┐
                                          │ 404「找不到照片」  │
                                          └───────────────────┘
                              有這張照片
                                    │
        ┌───────────────────────────┴────────────────────────────┐
        │  body = {"folder_id": 2}          │  body = {"name": "專案X", …}
        │  （選項① 採用建議／② 改選）        │  （選項③ 自建）
        ▼                                   ▼
   ② get_folder(2)                     ③ find_folder_by_name("專案X")
        │                                   │
   None ┴─▶ ┌────────────────────┐     命中 ┴─▶ ┌──────────────────────┐
            │ 404「找不到資料夾」 │              │ 409「資料夾名稱已存在」│
            └────────────────────┘              └──────────────────────┘
        有 → category = 資料夾名稱          沒命中 → category = 請求裡的 name
        │                                          （注意：這裡**還沒**建資料夾）
        └─────────────────┬─────────────────────────┘
                          ▼
    ④ build_document(text, category, location, items, content_time)
                          ▼
    ④ embed_document(embeddings, document)      ← 這裡失敗 → 500
                          │                        資料庫完全沒動：照片三欄原封不動，
                          │                        也沒有半個新資料夾被建出來
                          ▼
    ⑤ 自建那條路此時才 create_folder("專案X", …) → folder
       （folder_id 那條路直接沿用 ② 查到的 folder）
                          ▼
    ⑥ update_photo_folder(photo_id, folder_id=…, category=…, embedding=…)
       └── 一條 UPDATE 同時寫三欄 ＋ RETURNING 把整列拿回來
                          ▼
                    ┌──────────────────────────────────────────────┐
                    │ 200                                          │
                    │ { "id": 1,                                   │
                    │   "folder":  {"id":2,"name":"收據","descr…"}, │
                    │   "metadata":{"category":"收據",             │
                    │               "location":"Costco",           │
                    │               "items":["咖啡","牛奶"],        │
                    │               "content_time":null} }         │
                    └──────────────────────────────────────────────┘
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1 先把測試寫好（此時端點還不存在，PATCH 會拿到 404，測試紅），步驟 2〜4 才依序補 schema、repository、端點，讓它一路轉綠。

### 步驟 1：先寫測試 `tests/integration/test_assign_folder.py`

建立這個檔案（完整內容）：

```python
"""PATCH /photos/{id}/folder 的整合測試（design1.md §7.2、§7.3、§13）。

涵蓋：採用現有資料夾、自建新資料夾、四種錯誤碼（404×2、409、422）。
"""

from __future__ import annotations

import json

import pytest

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.indexing_service import build_document, embed_document
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes

# text 裡刻意不出現任何資料夾名稱：
# 假向量只認得詞表裡的詞，text 若已經含「收據」兩個字，
# 歸類前後算出來的向量會一模一樣，「有沒有重算」就驗不出來了。
超市照片 = PhotoUnderstanding(
    understood=True,
    text="超市購物的照片",
    category="收據",          # VLM 的建議（上傳時不會落庫，只出現在 suggested_folder）
    location="Costco",
    items=["咖啡", "牛奶"],
    content_time=None,
)


@pytest.fixture
def 已上傳的照片(client):
    """先走一次真正的上傳流程，拿到一張躺在「未分類」的照片。

    回傳的是 201 的完整回應內容（含 folders 清單，後面挑 id 要用）。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(超市照片)
    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["metadata"]["category"] == "未分類", "前置條件：上傳後應該在未分類"
    return body


def _folder_id(上傳回應: dict, name: str) -> int:
    """從上傳回應的資料夾清單裡挑出某個資料夾的 id。"""
    return next(f["id"] for f in 上傳回應["folders"] if f["name"] == name)


def _stored_embedding(photo_id: int) -> list[float]:
    return json.loads(photo_repository.fetch_embedding(photo_id))


def _expected_embedding(category: str) -> list[float]:
    """如果向量真的用這個類別重算過，應該長這樣。"""
    document = build_document(
        text="超市購物的照片",
        category=category,
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
    return embed_document(FakeEmbeddings(), document)


def _max_diff(a: list[float], b: list[float]) -> float:
    """兩條向量差最多的那一格差多少。"""
    return max(abs(x - y) for x, y in zip(a, b))


def test_採用現有資料夾後分類與向量都更新(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]
    收據id = _folder_id(已上傳的照片, "收據")
    上傳當下的向量 = _stored_embedding(photo_id)

    response = client.patch(f"/photos/{photo_id}/folder", json={"folder_id": 收據id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == photo_id
    assert body["folder"]["id"] == 收據id
    assert body["folder"]["name"] == "收據"
    assert body["metadata"]["category"] == "收據"
    # 另外三個 metadata 欄位不受歸類影響
    assert body["metadata"]["location"] == "Costco"
    assert body["metadata"]["items"] == ["咖啡", "牛奶"]
    assert body["metadata"]["content_time"] is None

    # 資料庫：category 與 folder_id 一起改（design1.md §6 的雙寫規則）
    row = photo_repository.fetch_photo(photo_id)
    assert row["category"] == "收據"
    assert row["folder_id"] == 收據id

    # 向量真的用新類別重算過（pgvector 以 float4 儲存，取 1e-6 容差）
    重算後的向量 = _stored_embedding(photo_id)
    assert _max_diff(重算後的向量, _expected_embedding("收據")) < 1e-6
    # 而且和上傳當下（未分類版本）的向量不同——沒重算的話這一行會失敗
    assert _max_diff(重算後的向量, 上傳當下的向量) > 1e-3


def test_自建資料夾後照片歸它新資料夾也進入清單(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]

    response = client.patch(
        f"/photos/{photo_id}/folder",
        json={"name": "專案X", "description": "跟課程作業有關的照片"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["folder"]["name"] == "專案X"
    assert body["folder"]["description"] == "跟課程作業有關的照片"
    assert body["metadata"]["category"] == "專案X"
    assert photo_repository.fetch_photo(photo_id)["folder_id"] == body["folder"]["id"]

    # 自建的資料夾和預設六個進同一張表（design1.md §5）
    assert "專案X" in [f["name"] for f in photo_repository.list_folders()]

    # 下次上傳的回應也看得到它——也就是說下一次 VLM 的 prompt 也會看到
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(超市照片)
    第二次上傳 = client.post(
        "/photos", files={"file": ("b.png", make_png_bytes(), "image/png")}
    )
    assert 第二次上傳.status_code == 201
    assert "專案X" in [f["name"] for f in 第二次上傳.json()["folders"]]


def test_照片不存在回404(client, 已上傳的照片):
    """先檢查照片、再檢查資料夾——所以就算 folder_id 是對的也回「找不到照片」。"""
    收據id = _folder_id(已上傳的照片, "收據")

    response = client.patch("/photos/999/folder", json={"folder_id": 收據id})

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"


def test_資料夾不存在回404(client, 已上傳的照片):
    response = client.patch(
        f"/photos/{已上傳的照片['id']}/folder", json={"folder_id": 999}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到資料夾"
    # 沒有偷偷改到照片
    assert photo_repository.fetch_photo(已上傳的照片["id"])["category"] == "未分類"


def test_自建名稱與現有資料夾重複回409(client, 已上傳的照片):
    """「收據」是預設資料夾之一，不可以被自建流程蓋掉（design1.md §12）。

    大小寫不敏感的比對由 Phase 16 的 find_folder_by_name() 負責，
    該函式的大小寫測試在 tests/integration/test_folder_repository.py，這裡不重複。
    """
    原本的資料夾數 = len(photo_repository.list_folders())

    response = client.patch(
        f"/photos/{已上傳的照片['id']}/folder",
        json={"name": "收據", "description": "我自己的收據夾"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "資料夾名稱已存在"
    # 沒有多建一個，也沒有改到原本那個的 description
    assert len(photo_repository.list_folders()) == 原本的資料夾數
    assert photo_repository.find_folder_by_name("收據")["description"] != "我自己的收據夾"


# parametrize：同一個測試跑三組不合法的 body，pytest 會算成 3 個測試
@pytest.mark.parametrize(
    "body",
    [
        {},                                 # 兩個都不給
        {"folder_id": 1, "name": "專案X"},   # 兩個都給
        {"name": "   "},                    # name 只有空白
    ],
)
def test_請求必須恰好給一個folder_id或name(client, 已上傳的照片, body):
    response = client.patch(f"/photos/{已上傳的照片['id']}/folder", json=body)

    assert response.status_code == 422
```

跑一次，**現在應該是紅的**：

```bash
pytest tests/integration/test_assign_folder.py -q
```

預期：`8 failed`，錯誤訊息類似 `assert 404 == 200`（`/photos/{id}/folder` 這個路徑還不存在，FastAPI 一律回 404；連期望 404 的兩個測試也會因為 detail 對不上而紅）。這就是紅燈。

### 步驟 2：在 `app/schemas/photo.py` 加請求與回應模型

先把檔案最上方的 import：

```python
from pydantic import BaseModel, Field
```

改成（多了 `model_validator`）：

```python
from pydantic import BaseModel, Field, model_validator
```

再把下面兩個模型接在檔案最後面（`UploadResponse` 之後）：

```python
class AssignFolderRequest(BaseModel):
    """PATCH /photos/{id}/folder 的請求（design1.md §7.2）。

    兩種長相，擇一：
      採用現有資料夾（彈窗選項①②）：{"folder_id": 2}
      自建新資料夾（彈窗選項③）    ：{"name": "專案X", "description": "…"}
    """

    folder_id: int | None = None
    name: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def 必須恰好給一個(self) -> "AssignFolderRequest":
        """跨欄位檢查：folder_id 與 name 有且只有一個。

        mode="after" ＝各欄位型別都驗完之後才跑這裡。
        在這裡 raise ValueError，FastAPI 會自動變成 422 回應。
        """
        if self.name is not None:
            if not self.name.strip():
                raise ValueError("資料夾名稱不可為空白")
            # 順手把前後空白去掉，"收據 " 與 "收據" 才不會變成兩個資料夾
            self.name = self.name.strip()

        # 兩邊同時是 None（都沒給）或同時不是 None（都給了）→ 都不合法
        if (self.folder_id is None) == (self.name is None):
            raise ValueError("folder_id 與 name 必須恰好提供一個")
        return self


class AssignFolderResponse(BaseModel):
    """PATCH /photos/{id}/folder 成功時的回應（HTTP 200）。

    回這張照片「歸類之後」的狀態：現在在哪個資料夾、四個 metadata 欄位長怎樣
    （其中 category 已經等於資料夾名稱）。
    """

    id: int
    folder: FolderOut
    metadata: PhotoMetadata
```

端點還沒做，所以測試還是紅的（`/photos/{id}/folder` 這個路徑還沒註冊，會拿到 404）。先單獨確認驗證器本身寫對了：

```bash
python -c "
import pydantic
from app.schemas.photo import AssignFolderRequest

for body in ({}, {'folder_id': 1, 'name': '專案X'}, {'name': '   '}):
    try:
        AssignFolderRequest(**body)
        print('沒擋下來（錯）：', body)
    except pydantic.ValidationError:
        print('擋下來了：', body)

print('去空白後：', repr(AssignFolderRequest(name=' 專案X ').name))
print('只給 folder_id：', AssignFolderRequest(folder_id=2).folder_id)
"
```

預期輸出：

```
擋下來了： {}
擋下來了： {'folder_id': 1, 'name': '專案X'}
擋下來了： {'name': '   '}
去空白後： '專案X'
只給 folder_id： 2
```

> 這三種不合法的 body 之所以會變成 422，是因為 body 驗證失敗時 FastAPI 根本不會呼叫端點函式——`raise ValueError` 直接被翻譯成 422 回應。

### 步驟 3：在 `app/repositories/photo_repository.py` 加一條 UPDATE

接在檔案既有內容後面（放在 `delete_photo` 之後、兩條 search 函式之前或之後都可以）：

```python
def update_photo_folder(
    photo_id: int,
    *,
    folder_id: int,
    category: str,
    embedding: list[float],
) -> dict[str, Any]:
    """歸類：一條 UPDATE 同時寫 folder_id、category 與重算後的 embedding。

    三個欄位一起寫，資料庫層面是一次完成的動作——
    不會出現「資料夾改了但向量還是舊的」這種半調子狀態（design1.md §6 的雙寫規則）。

    RETURNING ＝ 改完順便把那一列回傳，省掉再 SELECT 一次。
    """
    sql = f"""
        UPDATE photo
        SET folder_id = %(folder_id)s,
            category  = %(category)s,
            embedding = %(embedding)s::vector
        WHERE id = %(photo_id)s
        RETURNING {PHOTO_COLUMNS};
    """
    params = {
        "photo_id": photo_id,
        "folder_id": folder_id,
        "category": category,
        "embedding": to_vector_literal(embedding),
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
```

> 📌 `PHOTO_COLUMNS` 是檔案最上方那個「每次查詢都取回的欄位」常數，Phase 15 已經把 `folder_id`／`original_path`／`thumbnail_path`／`content_type` 四個新欄位加進去了。這裡直接沿用它，**不要**自己重列一串欄位名——欄位再變動時只要改一個地方。

### 步驟 4：在 `app/api/routers/photos.py` 加 PATCH 端點

先確認 import：

```python
from app.schemas.photo import (
    AssignFolderRequest,
    AssignFolderResponse,
    FolderOut,
    PhotoMetadata,
    UploadResponse,
)
```

再把端點接在 `upload_photo` 與兩個 `GET` 端點之後（檔案最後面）：

```python
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

    # ②／③ 決定 category 要用的名稱（request 已保證 folder_id 與 name 恰好一個有值）。
    #    這一段只查不寫：自建那條路的 create_folder 刻意排在 embedding 之後（見 ⑤），
    #    embedding 失敗時才不會留下一個沒有照片的空資料夾。
    if payload.folder_id is not None:
        folder = photo_repository.get_folder(payload.folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="找不到資料夾")
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
```

> `_folder_out()` 是 Phase 20 在同一個檔案裡加的小工具（把 repository 的 dict 挑出 `id`／`name`／`description` 三個欄位）。這裡直接重用，不要再寫第二個。

再跑一次，**這次要全綠**：

```bash
pytest tests/integration/test_assign_folder.py -v
```

預期最後一行：`8 passed`。

### 步驟 5：全量回歸並 commit

```bash
pytest -q
```

預期：全綠，顆數 ＝ 步驟開工時記下的基線 **＋8 ＝ 132**。

順手確認三件事：

```bash
# 1. PATCH 端點真的掛上去了
grep -n 'router.patch' app/api/routers/photos.py

# 2. SQL 依然只出現在 repository 一個檔案
grep -rlnE "SELECT |INSERT INTO|UPDATE photo|TRUNCATE" app/ --include="*.py"

# 3. 詢問規格沒被波及（歸類後的 category 仍供 ILIKE 使用）
pytest tests/integration/test_ask_feature.py -v
```

預期：第 1 個指令印出一行；第 2 個指令**只印**  `app/repositories/photo_repository.py`；第 3 個 `7 passed`。

commit（訊息裡的「累計 NN」請填上一步 `pytest -q` 實際印出的數字）：

```bash
git add app/schemas/photo.py app/repositories/photo_repository.py app/api/routers/photos.py tests/integration/test_assign_folder.py
git commit -m "feat: Phase 21 歸類端點——PATCH /photos/{id}/folder（採用現有資料夾／自建，擇一驗證 422、找不到 404×2、重名 409），先重算 embedding 再動資料庫（自建路徑也先算後建，失敗不留空資料夾），一條 UPDATE 同寫 folder_id／category／embedding，+8 tests（累計 NN）"
```

---

## 驗收清單

- [ ] `pytest tests/integration/test_assign_folder.py -v` → **8 passed**
- [ ] 兩種 body 都走得通：`{"folder_id": N}` 與 `{"name": "…", "description": "…"}`
- [ ] 四種錯誤碼都有測試把關：404（照片）／404（資料夾）／409（重名）／422（擇一驗證 3 例）
- [ ] 歸類後 `category`＝資料夾名稱、`folder_id` 也一起更新（雙寫規則）
- [ ] 歸類後 `embedding` 與上傳當下不同，且等於「用新類別重算」的結果
- [ ] `grep -n 'router.patch' app/api/routers/photos.py` → 有一行輸出
- [ ] `grep -rlnE "SELECT |INSERT INTO|UPDATE photo|TRUNCATE" app/ --include="*.py"` → **只有** `app/repositories/photo_repository.py`
- [ ] 手動確認「embedding 失敗時資料庫完全沒動」——照片三欄原封不動，**自建那條路也不留空資料夾**（Phase 25 會把它變成常駐測試，這裡先用手動確認一次）：
      ```bash
      python - <<'PY'
      import os
      os.environ["DATABASE_URL"] = "postgresql://localhost:5433/PersonalDocAI_test"
      os.environ["DATA_DIR"] = "/tmp/personaldocai-manual-check"

      from fastapi.testclient import TestClient
      from app.dependencies import get_embeddings, get_vlm
      from app.main import app
      from app.repositories import photo_repository
      from app.services.vlm_service import PhotoUnderstanding
      from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes

      photo_repository.reset_folders_and_photos()
      app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
      app.dependency_overrides[get_vlm] = lambda: FakeVLM(PhotoUnderstanding(
          understood=True, text="超市購物的照片", category="收據",
          location="Costco", items=["咖啡", "牛奶"], content_time=None))

      client = TestClient(app, raise_server_exceptions=False)
      body = client.post("/photos",
                         files={"file": ("a.png", make_png_bytes(), "image/png")}).json()
      before = photo_repository.fetch_photo(body["id"])
      before_vec = photo_repository.fetch_embedding(body["id"])

      class 壞掉的Embeddings:
          def embed_query(self, text): raise RuntimeError("Ollama 沒有回應")
          def embed_documents(self, texts): raise RuntimeError("Ollama 沒有回應")
      app.dependency_overrides[get_embeddings] = lambda: 壞掉的Embeddings()

      收據id = next(f["id"] for f in body["folders"] if f["name"] == "收據")
      resp = client.patch(f"/photos/{body['id']}/folder", json={"folder_id": 收據id})
      after = photo_repository.fetch_photo(body["id"])

      print("狀態碼：", resp.status_code)
      print("category 沒變：", before["category"] == after["category"] == "未分類")
      print("folder_id 沒變：", before["folder_id"] == after["folder_id"])
      print("embedding 沒變：", before_vec == photo_repository.fetch_embedding(body["id"]))

      # 自建那條路也試一次：embedding 失敗必須連資料夾都不建
      resp2 = client.patch(f"/photos/{body['id']}/folder",
                           json={"name": "專案X", "description": "測試用"})
      print("自建路徑狀態碼：", resp2.status_code)
      print("沒留下空資料夾：",
            "專案X" not in [f["name"] for f in photo_repository.list_folders()])
      PY
      ```
      預期輸出：`狀態碼： 500`、`自建路徑狀態碼： 500`，其餘四行都是 `True`
- [ ] `pytest tests/integration/test_ask_feature.py -v` → **7 passed**（詢問規格 5 條 Rule 不受影響）
- [ ] `pytest -q` **全綠**，顆數 ＝ 基線 ＋8 ＝ **132**
- [ ] `git commit` 完成（訊息含實際累計顆數）

---

## 常見問題

**Q1：為什麼彈窗有三個選項，端點卻只有兩條路？**
選項①（採用建議）和②（下拉選單改選）送出的都是 `{"folder_id": N}`——差別只在「那個 N 是誰決定的」，那是前端的事。後端多一條路只會多一種出錯方式。

**Q2：`{"folder_id": 1, "name": "專案X"}` 為什麼不是「以 folder_id 優先」就好？**
因為那會讓前端的 bug 靜悄悄地被吞掉：使用者以為自己建了「專案X」，結果照片被歸到 id=1。「恰一」是明確的契約，撰寫契約 §4 也是這樣定的。

**Q3：`name` 給了 `"  "`（只有空白）為什麼是 422 不是 409？**
422 是「你送來的東西格式不合規則」，409 是「格式沒問題但和現況衝突」。空白名稱連格式都不合格，資料庫裡也不該出現名字是空白的資料夾。

**Q4：自建資料夾時 `description` 沒給怎麼辦？**
預設是空字串 `""`（`folder.description` 的資料庫預設也是 `''`）。**不要**自動生成 description，也不要因為沒給 description 就退回 422——design1.md §7.2 的 body 範例只把 `name` 當必要條件。

**Q5：如果 embedding 在「自建」那條路失敗，會留下一個空資料夾嗎？**
不會。`create_folder` 刻意排在 embedding **之後**：算向量用的 category 直接拿請求裡的 `name`（Pydantic 驗證器已去掉前後空白，跟之後 `create_folder` 存進去的名稱一字不差），所以失敗當下連資料夾都還沒建。500 之後資料庫完全沒動——照片三欄原封不動、資料夾清單也跟按下按鈕之前一模一樣，使用者重試就是乾淨的一次新請求。這條保證沒有例外，**不要**為它加交易（transaction）包裝或補償刪除邏輯——順序排對了就不需要。

**Q6：歸類之後條件查詢還找得到嗎？**
找得到，而且更穩。`search_by_metadata` 讀的是 `category` 欄位，歸類後它等於資料夾名稱（受控的中文名稱），不會再出現 `Receipt` vs 「收據」對不到的問題——這正是 design1.md §2 最後一句講的效果。（跨語言的「問 receipts 對不到 收據」限制仍在，那是 design.md §8.3 的已知限制，本增量不解。）

**Q7：可不可以順便做「把資料夾改名」或「刪除資料夾」？**
不可以。design1.md §3「不做」與 §15 都明列不做刪除；改名也沒有在範圍內。

**Q8：可不可以順便讓 PATCH 支援一次歸類多張照片？**
不可以。彈窗一次只處理一張照片（design1.md §7.2 的路徑就是 `/photos/{id}/folder`）。批次歸類沒有在設計裡。

**Q9：測試裡的 `_max_diff(…) > 1e-3` 這行是在防什麼？**
防「假裝有重算」。如果實作只改了 `category` 字串、把舊向量原封不動寫回去，`< 1e-6` 那一行還是可能會過（因為期望值算出來剛好一樣的話），但 `> 1e-3` 這行一定會失敗。兩行合起來才守得住「向量真的用新類別重算過」。

**Q10：`test_照片不存在回404` 為什麼要先建一張照片（用了 `已上傳的照片` fixture）？**
為了讓 `folder_id` 是一個**真的存在**的資料夾 id。這樣測試才能證明「照片檢查排在資料夾檢查前面」——如果順序反了，回的會是「找不到資料夾」而不是「找不到照片」。

---

## 完成後的專案狀態

彈窗背後的後端補齊了：照片可以從「未分類」搬到任何現有資料夾，也可以當場開一個新資料夾把它放進去；`category`、`folder_id`、`embedding` 三者一起更新，語意查詢拿得到正確的類別訊號。自建的資料夾立刻進入同一份清單，下一次上傳時 VLM 的 prompt 就看得到它。**但使用者還是只能用 curl 打這個端點**——把它接成真正的彈窗是 Phase 23、把照片列出來看是 Phase 22 與 24 的事。測試顆數 ＝ 開工基線 ＋8 ＝ **132**。
