# Phase 20：上傳未分類流程與規格改版（照片一律先進「未分類」，AI 只給建議）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 讓 `POST /photos` 改成「上傳當下一律歸到『未分類』、VLM 給的類別只當建議」，回應補上彈窗要用的四塊資料（`folder`／`suggested_folder`／`folders`／`thumbnail_url`），並把 `docs/spec/features/上傳照片.feature` **一次改成新規格**，讓驗收測試跟著規格走。

---

## 前置條件

- 需要已完成的 phase：
  - **Phase 15**（`folder` 表、六個預設資料夾、`insert_photo` 會依 category 掛 `folder_id`）
  - **Phase 16**（`list_folders()` 回 `id,name,description,is_inbox,photo_count`）
  - **Phase 17**（`storage_service`、`config.DATA_DIR`、conftest 的 `isolated_data_dir`）
  - **Phase 18**（`build_vlm_prompt(folders)`、`understand(image_bytes, content_type, folders)`、`clamp_category(category, folders)`）
  - **Phase 19**（上傳寫檔流程、`GET /photos/{id}/thumbnail`／`/image`、`update_photo_paths`／`delete_photo`）
- **開工前基線**：先執行 `pytest -q` 把「目前全綠的顆數」記下來（Phase 15〜17 完成時為 **103**；Phase 18 後 **110**；Phase 19 後 **121**——此即本 phase 的開工基線）。本 phase 完成後的顆數 ＝ 基線 **＋3 ＝ 124**（規格檔從 7 個 Example 增為 10 個）。
- 環境：PostgreSQL@17 在 5433、測試庫 `PersonalDocAI_test` 已用最新 `db/schema.sql` 重建過（有 `folder` 表與六筆種子）。**不需要 Ollama**（全程假件）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

前面五個 phase 把零件都做好了：資料夾表有了、檔案存得下去了、VLM 看得到資料夾清單了、`clamp_category` 也寫好了——但**上傳流程還沒真的用它們**。Phase 18 特別交代「clamp 只加函式，不接進流程」，Phase 19 特別交代「回應 schema 不動」，就是把這兩件事留給本 phase 一次接起來。

接起來之後，上傳的語意變了一句話：

> **VLM 仍然自動分類，但不再默默定案。**（design1.md §2）

具體差別：

| | 舊行為（Phase 01〜19） | 新行為（本 phase 之後） |
|---|---|---|
| 資料庫的 `category` | VLM 說什麼就存什麼（可能是 `Receipt`、可能是任何自創字串） | 一律先存「未分類」 |
| VLM 給的類別 | 直接落庫 | 只當 `suggested_folder` 回給前端，**不落庫** |
| embedding | 用 VLM 的 category 合併後產生 | 用「未分類」合併後產生（歸類後由 Phase 21 的 PATCH 重算） |
| 回應內容 | `id`／`text`／`metadata` | 再加 `folder`／`suggested_folder`／`folders`／`thumbnail_url` |

**為什麼上傳當下的向量用「未分類」也沒關係**：因為使用者一旦在彈窗按下確認，Phase 21 的 `PATCH` 會用新的資料夾名稱把向量整條重算。沒按確認的照片本來就還沒分類，向量裡帶著「未分類」是誠實的（design1.md §7.3）。

### 規格檔這次真的可以改

從 Phase 07 到 Phase 14，`docs/spec/` 一直是**唯讀**的：測試沒過只能改產品程式碼。這次不一樣——產品負責人已於 **2026-08-20 核准解除 `上傳照片.feature` 的唯讀**（撰寫契約 §0、design1.md §1.1），因為「不儲存原始照片檔」「category 由 VLM 自由填」這兩條**舊定案本身已被推翻**，不是實作偷懶。

三條紅線仍在：

1. **只改 `上傳照片.feature` 這一個檔。** `自然語言詢問.feature` 一個字都不准動，它的 5 條 Rule（7 個例子）必須全程保綠。
2. **一次改到位。** 不留「舊 Rule 註解起來、新 Rule 加在下面」這種新舊混雜的過渡產物。
3. **只改被推翻的那幾條。** 格式檢查、看不懂→422、上傳時間、embedding 不為空這些沒被推翻的 Rule，原文一字不動。

### 圖片位元組：沿用 Phase 17／19 已經備好的工具

Phase 19 之後，上傳成功會用 **Pillow** 把照片開起來產生縮圖，所以「預期上傳成功」的測試不能再餵 `b"\x89PNG\r\n\x1a\n fake image bytes"` 這種假位元組（Pillow 打不開 → 走進清理路徑 → 500）。

**這件事 Phase 17／19 已經處理完了**：`tests/fakes.py` 有 `make_png_bytes()`、`make_jpeg_bytes()`、`make_large_png_bytes()` 三個函式，Phase 19 也已經把五個既有測試檔改成用它們。本 phase **不重做這件事**，只要在改寫測試時繼續用同一組函式即可。反過來說，走失敗路徑的測試（415／422／embedding 失敗）繼續用假位元組是刻意的——正好證明那些路徑真的沒去解碼圖片。

**名詞**：

- **pytest-bdd**＝讓 pytest 直接執行 `.feature` 規格檔的外掛。`scenarios("路徑")` 這一行會把該檔案的每個 `Example` 變成一個測試。
- **Rule / Example**＝Gherkin（規格語言）的兩層結構：`Rule` 是一條規則，`Example` 是這條規則的具體例子。一個 Example ＝ 一個測試。
- **DataTable**＝Gherkin 步驟底下那張用 `|` 畫的表格。pytest-bdd 會把它當成「一列一個清單」交給步驟函式（第 0 列是欄位名）；步驟函式只要宣告一個叫 `datatable` 的參數就拿得到。
- **步驟定義（step definition）**＝把規格裡的一句中文（例如「使用者上傳照片」）對應到一段 Python 程式碼的函式，用 `@given`／`@when`／`@then` 標記。
- **收件箱（inbox）**＝`folder` 表上 `is_inbox=true` 的那一個資料夾，也就是「未分類」。全系統只會有一個（schema 的 partial unique index 保證）。
- **clamp**＝英文「夾住」。`clamp_category()` 的意思是「把 VLM 講的類別夾回資料夾清單內」：清單裡有就用清單裡的原文，沒有就一律變成「未分類」。
- **multipart/form-data**＝瀏覽器上傳檔案時用的請求格式；FastAPI 用 `UploadFile` 接。
- **縮圖（thumbnail）**＝原圖等比例縮小後的小圖（本專案長邊 512px），給瀏覽頁的縮圖牆用，不必每次載入好幾 MB 的原圖。
- **`response_model`**＝FastAPI 的參數，指定「這個端點回應長什麼樣」。它會照著 Pydantic 模型過濾與驗證回應內容——模型上沒有的欄位不會被送出去，模型上有、程式卻沒填的欄位會直接報錯。
- **Pillow**＝Python 最常用的影像處理套件，`import PIL`。本專案只用它產縮圖。

---

## ASCII 圖：上傳最終流程與 201 回應長相

```
【POST /photos 最終流程】（★ ＝ 本 phase 真正改動的地方）

  瀏覽器 ──multipart(file)──▶ ① content_type 是 image/jpeg 或 image/png？
                                 │ 否 → 415（不看圖、不寫庫、不寫檔）
                                 │ 是
                                 ▼
                              ② folders = photo_repository.list_folders()
                                 │   六筆（未分類／收據／飲食／風景／文件／其他＋使用者自建）
                                 ▼
                              ③ vlm.understand(bytes, content_type, folders)
                                 │   看不懂 或 text 全空白 → 422（不寫庫、不寫檔）
                                 ▼
                          ★ ④ suggested_name = clamp_category(VLM 的 category, folders)
                                 │   在清單內 → 用清單裡的原文
                                 │   清單外／None → 「未分類」
                                 ▼
                          ★ ⑤ build_document(text, category="未分類", location, items, time)
                                 │        → embed_document → 1024 維向量
                                 │   ★ 存進去的是「未分類版本」的向量；
                                 │     使用者確認歸類後由 Phase 21 的 PATCH 整條重算
                                 ▼
                          ★ ⑥ INSERT photo（category="未分類"，folder_id 自動掛到收件箱）
                                 ▼
                              ⑦ 存原圖 → 產縮圖 → UPDATE 三個路徑欄位（Phase 19）
                                 │   任何一步失敗 → 刪兩個檔 ＋ 刪這一列 → 往上丟（500）
                                 ▼
                          ★ ⑧ 201

【201 回應長什麼樣】（design1.md §7.1）

  {
    "id": 1,
    "text": "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    "metadata": { "category": "未分類",  ← ★ 不是「收據」
                  "location": "Target",
                  "items": ["可樂","洋芋片"],
                  "content_time": "2026-08-10" },

    "folder":           {"id":1,"name":"未分類","description":"…"},   ← 現在在哪（一定是收件箱）
    "suggested_folder": {"id":2,"name":"收據",  "description":"…"},   ← AI 建議去哪（一定在 folders 裡）
    "folders": [ {…未分類}, {…收據}, {…飲食}, {…風景}, {…文件}, {…其他} ],  ← 彈窗下拉選單用
    "thumbnail_url": "/photos/1/thumbnail"                            ← 彈窗要顯示的縮圖
  }
        └───────────────┬────────────────┘
                        ▼
        Phase 23 的彈窗畫這一頁時，需要的資料**全部在這個回應裡**，
        前端不必再多打一次 API。
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1〜2 先改規格檔與步驟定義（跑起來會**紅**），步驟 3〜4 才改產品程式碼讓它轉綠，步驟 5 收拾既有測試。每一步都附了指令與預期輸出，照著跑就好。

### 步驟 0：確認前置 phase 的東西都在

本 phase 不新建任何工具，但會直接用到 Phase 16〜19 做好的六樣東西。開工前先確認它們都在：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                                   # 記下目前的顆數＝基線
python -c "
from tests.fakes import make_png_bytes, make_jpeg_bytes
from app.repositories.photo_repository import list_folders, get_folder
from app.services.vlm_service import clamp_category
from app.services.storage_service import absolute_path
print('真圖片位元組：', len(make_png_bytes()), len(make_jpeg_bytes()))
print('資料夾清單：', [f['name'] for f in list_folders()])
print('clamp 清單外：', clamp_category('Receipt', list_folders()))
"
```

預期：印出兩個非零長度、六個資料夾名稱（未分類／收據／飲食／風景／文件／其他）、`clamp 清單外： 未分類`。

若 `clamp_category` 或 `make_png_bytes` 找不到，代表 Phase 18／17 還沒完成——回頭把它們做完再繼續。

### 步驟 1：把 `docs/spec/features/上傳照片.feature` 改成新版（一次改完）

**整檔換成下面的內容**（原本 7 條 Rule → 新版 10 條 Rule；沒被推翻的 Rule 原文一字不動）：

```gherkin
# 來源：docs/spec/draft/design-draft.md
# 2026-08-20 依 docs/design/design1.md 正式改版（產品負責人核准解除唯讀）：
#   1. 上傳當下照片一律先歸到「未分類」，VLM 給的類別只是建議，由使用者確認後才定案
#   2. 系統改為保留原始照片檔與縮圖（推翻「不含原始照片檔」的舊定案）
#   3. 成功回應加上所屬資料夾、建議資料夾與完整資料夾清單
Feature: 上傳照片
  使用者透過 FastAPI 上傳照片。
  系統利用 VLM 理解照片內容並轉成文字與結構化 metadata，
  再透過 LangChain 將內容建立成 Document、產生 embedding 向量，
  並使用 PostgreSQL + pgvector 儲存照片資訊、metadata 與向量。
  照片的類別即所屬資料夾的名稱；上傳當下一律為「未分類」，
  VLM 只從現有資料夾清單中推薦一個，由使用者確認後才改變歸屬。

  Rule: 上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗
    # 「圖片格式」指檔案格式（file format）；不設檔案大小上限
    Example: 非圖片格式的檔案上傳失敗
      When 使用者上傳一個非圖片格式的檔案
      Then 操作失敗
      And 系統儲存的照片數量為 0

  Rule: 上傳照片後，系統儲存照片資訊（VLM 理解照片內容後轉成的文字）
    Example: 上傳 Target 收據照片後儲存文字描述
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"

  Rule: 上傳照片後，系統儲存 VLM 產生的結構化 metadata（照片類別、地點/商家、物品清單、內容時間；清單外資訊捨棄），其中照片類別在上傳當下一律為「未分類」
    Example: 上傳 Target 收據照片後儲存結構化 metadata
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 metadata 欄位如下
        | category | location | items        | content_time |
        | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   |
      And 照片所屬資料夾為 "未分類"

  Rule: 上傳照片後，系統儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生）
    Example: 上傳照片後產生 embedding 向量
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 embedding 不為空

  Rule: 上傳照片後，系統記錄上傳時間
    Example: 上傳照片後記錄上傳時間
      Given 現在時間為 "2026-08-18 10:00"
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的上傳時間為 "2026-08-18 10:00"

  Rule: 上傳照片後，系統保留原始照片檔與縮圖
    Example: 上傳照片後保留原圖與縮圖
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的原圖與縮圖都已儲存
      And 回應包含這張照片的縮圖網址

  Rule: 上傳照片成功後，系統回應照片識別碼、文字描述與 metadata
    Example: 上傳成功的回應內容
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 回應包含照片識別碼
      And 回應的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      And 回應的 metadata 欄位如下
        | category | location | items        | content_time |
        | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   |

  Rule: 上傳照片成功後，系統回應照片所屬資料夾、VLM 建議的資料夾與完整資料夾清單
    Example: 上傳成功的回應包含建議資料夾與資料夾清單
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 回應的所屬資料夾為 "未分類"
      And 回應的建議資料夾如下
        | name |
        | 收據 |
      And 回應的資料夾清單包含以下名稱
        | name   |
        | 未分類 |
        | 收據   |
        | 飲食   |
        | 風景   |
        | 文件   |
        | 其他   |

  Rule: VLM 推薦的類別不在資料夾清單中時，建議資料夾改為「未分類」
    Example: VLM 推薦清單外的名稱
      When 使用者上傳一張照片，VLM 推薦的類別為 "Receipt"
      Then 回應的建議資料夾如下
        | name   |
        | 未分類 |
      And 照片的 metadata 類別為 "未分類"

  Rule: VLM 無法理解照片內容時，上傳失敗且不儲存任何資料
    Example: VLM 無法理解照片內容的上傳
      Given VLM 無法理解上傳照片的內容
      When 使用者上傳照片
      Then 操作失敗
      And 系統儲存的照片數量為 0
```

改完先確認條數：

```bash
grep -c "Rule:" docs/spec/features/上傳照片.feature
grep -c "Example:" docs/spec/features/上傳照片.feature
git diff --stat docs/spec/features/
```

預期：前兩個指令各印 `10`；第三個指令**只列出 `上傳照片.feature` 一個檔**（`自然語言詢問.feature` 沒被動到）。

### 步驟 2：把 `tests/integration/test_upload_feature.py` 改成新版（整檔換掉）

改動有四類：(a) 圖片位元組換成真的；(b) `_upload` 之後多了幾個新的 Then 步驟；(c) 新增一個 When 步驟（直接指定 VLM 推薦的類別）；(d) 多了一個讀「整欄」的表格小工具。

```python
"""把 docs/spec/features/上傳照片.feature 當測試跑（10 條 Rule）。

2026-08-20 規格改版後：上傳當下 category 一律「未分類」，
VLM 給的類別只出現在回應的 suggested_folder，不落庫。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_now, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import first_row, split_items
from tests.fakes import FakeVLM, make_png_bytes, understanding_for_text

# 直接掛上規格原檔——不複製、不改寫（路徑相對於本檔所在資料夾 tests/integration/）
scenarios("../../docs/spec/features/上傳照片.feature")

# 一張真的 PNG（Phase 17 加的工具）。上傳成功會用 Pillow 產縮圖，
# 假位元組會讓縮圖那一步失敗變成 500。
PNG_BYTES = make_png_bytes()

# 規格沒有指定「現在時間」時的預設值，確保測試結果不隨執行日期改變
DEFAULT_NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture
def context() -> dict:
    """一個測試裡各步驟之間傳遞資料的小抽屜。"""
    return {
        "now": DEFAULT_NOW,
        "understanding": PhotoUnderstanding(understood=False),
        "response": None,
    }


@pytest.fixture(autouse=True)
def wire_feature_clock(wire_fake_ai, context):
    """把「現在時間」改接到 context——Given 步驟改 context["now"] 即時生效。

    顯式依賴 conftest 的 wire_fake_ai（假 AI 已接好、測後統一 clear()），
    保證本 fixture 在它之後執行，get_now 的覆寫以這裡為準。
    """
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield


def _upload(context, client, filename="photo.png", content_type="image/png",
            payload=PNG_BYTES):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(context["understanding"])
    context["response"] = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )


def _body(context) -> dict:
    response = context["response"]
    assert response.status_code == 201, response.text
    return response.json()


def _stored_photo(context) -> dict:
    photo_id = _body(context)["id"]
    row = photo_repository.fetch_photo(photo_id)
    assert row is not None, "資料庫裡找不到剛剛上傳的照片"
    return row


def column(datatable: list[list[str]], name: str) -> list[str]:
    """把 Gherkin 表格的某一整欄取出來（第 0 列是欄位名）。

    first_row() 只看第一列資料；資料夾清單那張表有六列，要用這個。
    """
    header, *rows = datatable
    index = header.index(name)
    return [row[index].strip() for row in rows]


# ------------------------------ Given ------------------------------
@given(parsers.parse('現在時間為 "{moment}"'))
def 設定現在時間(context, moment):
    context["now"] = datetime.strptime(moment, "%Y-%m-%d %H:%M")


@given("VLM 無法理解上傳照片的內容")
def vlm看不懂(context):
    context["understanding"] = PhotoUnderstanding(understood=False)


# ------------------------------- When ------------------------------
@when("使用者上傳一個非圖片格式的檔案")
def 上傳非圖片檔(context, client):
    _upload(context, client, filename="note.txt",
            content_type="text/plain", payload="這不是圖片".encode())


@when(parsers.parse('使用者上傳一張照片，VLM 理解其內容為 "{text}"'))
def 上傳照片並指定理解內容(context, client, text):
    context["understanding"] = understanding_for_text(text)
    _upload(context, client)


@when(parsers.parse('使用者上傳一張照片，VLM 推薦的類別為 "{category}"'))
def 上傳照片並指定推薦類別(context, client, category):
    """只關心「VLM 推薦了什麼類別」的例子，文字內容用一句固定的就好。"""
    context["understanding"] = PhotoUnderstanding(
        understood=True,
        text="一張看得懂的照片",
        category=category,
        location=None,
        items=[],
        content_time=None,
    )
    _upload(context, client)


@when("使用者上傳照片")
def 上傳照片(context, client):
    _upload(context, client)


# ------------------------------- Then ------------------------------
@then("操作失敗")
def 操作失敗(context):
    assert context["response"].status_code >= 400, context["response"].text


@then(parsers.parse("系統儲存的照片數量為 {count:d}"))
def 照片數量為(count):
    assert photo_repository.count_photos() == count


@then(parsers.parse('照片的文字描述為 "{text}"'))
def 照片文字描述為(context, text):
    assert _stored_photo(context)["text"] == text


@then("照片的 metadata 欄位如下")
def 照片metadata為(context, datatable):
    expected = first_row(datatable)
    row = _stored_photo(context)
    assert row["category"] == expected["category"]
    assert row["location"] == expected["location"]
    assert row["items"] == split_items(expected["items"])
    stored_time = row["content_time"].isoformat() if row["content_time"] else ""
    assert stored_time == expected["content_time"].strip()


@then(parsers.parse('照片的 metadata 類別為 "{category}"'))
def 照片metadata類別為(context, category):
    assert _stored_photo(context)["category"] == category


@then(parsers.parse('照片所屬資料夾為 "{name}"'))
def 照片所屬資料夾為(context, name):
    """驗 folder_id 真的掛到那個資料夾（不是只有 category 字串對）。"""
    folder = photo_repository.get_folder(_stored_photo(context)["folder_id"])
    assert folder is not None, "photo.folder_id 指向一個不存在的資料夾"
    assert folder["name"] == name


@then("照片的 embedding 不為空")
def 照片embedding不為空(context):
    embedding = photo_repository.fetch_embedding(_body(context)["id"])
    assert embedding is not None
    assert embedding.startswith("[") and len(embedding) > 2


@then("照片的原圖與縮圖都已儲存")
def 照片原圖與縮圖都已儲存(context):
    row = _stored_photo(context)
    assert row["original_path"], "original_path 是空的"
    assert row["thumbnail_path"], "thumbnail_path 是空的"
    assert row["content_type"] == "image/png"
    # 路徑存的是相對路徑（data/photos/1.png），換算成實際位置後檔案要真的在
    assert storage_service.absolute_path(row["original_path"]).exists()
    assert storage_service.absolute_path(row["thumbnail_path"]).exists()


@then(parsers.parse('照片的上傳時間為 "{moment}"'))
def 照片上傳時間為(context, moment):
    uploaded_at = _stored_photo(context)["uploaded_at"]
    assert uploaded_at.strftime("%Y-%m-%d %H:%M") == moment


@then("回應包含照片識別碼")
def 回應包含識別碼(context):
    body = _body(context)
    assert isinstance(body.get("id"), int) and body["id"] > 0


@then(parsers.parse('回應的文字描述為 "{text}"'))
def 回應文字描述為(context, text):
    assert _body(context)["text"] == text


@then("回應的 metadata 欄位如下")
def 回應metadata為(context, datatable):
    expected = first_row(datatable)
    metadata = _body(context)["metadata"]
    assert metadata["category"] == expected["category"]
    assert metadata["location"] == expected["location"]
    assert metadata["items"] == split_items(expected["items"])
    assert (metadata["content_time"] or "") == expected["content_time"].strip()


@then(parsers.parse('回應的所屬資料夾為 "{name}"'))
def 回應所屬資料夾為(context, name):
    assert _body(context)["folder"]["name"] == name


@then("回應的建議資料夾如下")
def 回應建議資料夾為(context, datatable):
    expected = first_row(datatable)
    suggested = _body(context)["suggested_folder"]
    assert suggested["name"] == expected["name"]
    # 規則：建議一定是清單裡的其中一筆（design1.md §7.1）
    assert suggested["name"] in [f["name"] for f in _body(context)["folders"]]


@then("回應的資料夾清單包含以下名稱")
def 回應資料夾清單包含(context, datatable):
    回應清單 = [f["name"] for f in _body(context)["folders"]]
    for name in column(datatable, "name"):
        assert name in 回應清單, f"回應的資料夾清單少了「{name}」：{回應清單}"


@then("回應包含這張照片的縮圖網址")
def 回應包含縮圖網址(context):
    body = _body(context)
    assert body["thumbnail_url"] == f"/photos/{body['id']}/thumbnail"
```

跑一次，**現在應該是紅的**：

```bash
pytest tests/integration/test_upload_feature.py -q
```

預期：**5 failed, 5 passed** 之類的結果（確切數字不重要，重點是有紅）。紅的原因有兩種，都在意料之中：

1. `KeyError: 'folder'`／`'suggested_folder'`／`'thumbnail_url'`——回應還沒有這些欄位（步驟 3、4 補）。
2. `assert '收據' == '未分類'`——資料庫還存著 VLM 給的類別（步驟 4 改）。

### 步驟 3：擴充 `app/schemas/photo.py`

在 `PhotoMetadata` 之後、`UploadResponse` 之前插入 `FolderOut`，再把 `UploadResponse` 補四個欄位。**把檔案下半段這幾行**：

```python
class UploadResponse(BaseModel):
    """POST /photos 成功時的回應（HTTP 201）。"""

    id: int
    text: str
    metadata: PhotoMetadata
```

**改成**：

```python
class FolderOut(BaseModel):
    """回應裡的資料夾。彈窗只需要這三個欄位，其餘（is_inbox、張數）不外送。"""

    id: int
    name: str
    description: str


class UploadResponse(BaseModel):
    """POST /photos 成功時的回應（HTTP 201）。

    2026-08-20 起多帶四樣東西，讓前端一收到回應就能把彈窗畫出來，
    不必再多打一次 API（design1.md §7.1）。
    """

    id: int
    text: str
    metadata: PhotoMetadata
    folder: FolderOut            # 照片現在在哪個資料夾——上傳當下一定是「未分類」
    suggested_folder: FolderOut  # VLM 建議去哪個資料夾（保證是 folders 裡的一筆）
    folders: list[FolderOut]     # 完整資料夾清單，給彈窗的下拉選單用
    thumbnail_url: str           # 例如 "/photos/1/thumbnail"
```

### 步驟 4：改 `app/api/routers/photos.py` 的上傳流程

Phase 18 已經把 `folders` 撈出來傳給 `understand()`，Phase 19 已經接上寫檔流程。本 phase 只動三個地方（下面用 ★ 標出）：**合併與寫入改用「未分類」**、**算出建議資料夾**、**回應補四個欄位**。

先確認檔案最上方的 import 有這幾行（`FolderOut` 是本 phase 新加的）：

```python
from app.schemas.photo import FolderOut, PhotoMetadata, UploadResponse
from app.services import indexing_service, storage_service, vlm_service
```

在 `router = APIRouter(tags=["photos"])` 那一行**後面**加一個小工具：

```python
def _folder_out(folder: dict) -> FolderOut:
    """把 repository 回來的資料夾 dict 挑出三個欄位。

    repository 的 dict 還帶 is_inbox 與 photo_count，
    這裡明確只取三個，回應長什麼樣一眼看得出來。
    """
    return FolderOut(
        id=folder["id"], name=folder["name"], description=folder["description"]
    )
```

然後把 `upload_photo` 整個函式**換成下面這一版**（Phase 19 已完成的寫檔段落原樣保留）：

```python
@router.post("/photos", status_code=201, response_model=UploadResponse)
def upload_photo(
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse:
    """上傳照片：格式檢查 → 看圖 → 轉向量 → 寫入「未分類」→ 存檔 → 回 201。

    照片一律先掛在「未分類」；VLM 給的類別只是建議（回應的 suggested_folder），
    真正的歸類由使用者在彈窗確認後呼叫 PATCH /photos/{id}/folder（Phase 21）。
    全程在同一個請求內完成；任何一步失敗＝整筆不存在、也不留檔。
    """
    # ① 格式檢查
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    image_bytes = file.file.read()

    # ② 看圖：把現有資料夾清單當變數注入 prompt（design1.md §8）
    folders = photo_repository.list_folders()
    understanding = vlm.understand(image_bytes, file.content_type, folders)
    if not understanding.understood or not understanding.text.strip():
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )

    # ★③ VLM 給的類別只當「建議」：夾回清單內，清單外一律變「未分類」
    #    next(...)＝從清單裡挑出第一個符合條件的元素。
    #    收件箱用 is_inbox 這個欄位找，不用字串比對——資料庫欄位比字串常數可靠。
    #    兩個 next() 都保證找得到（schema 有六筆種子，clamp 只會回清單內的名稱）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    inbox = next(folder for folder in folders if folder["is_inbox"])
    suggested = next(folder for folder in folders if folder["name"] == suggested_name)

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
    )

    # ⑤ 存原圖與縮圖，再把路徑補回那一列（Phase 19 原樣保留）
    #    這三步不是一條 SQL，所以沒有資料庫交易可以幫忙 rollback：
    #    任何一步失敗就自己把檔案與資料列清乾淨，再把原始錯誤往外丟（不吞錯 → 500）。
    photo_id = row["id"]
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

    # ★⑥ 回 201：把彈窗要用的四樣東西一起帶回去
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
    )
```

> ⚠️ 若步驟 ⑤ 的寫檔段落與 Phase 19 落地的版本不一樣（例如變數命名不同），**以 Phase 19 已經在跑的版本為準**，不要為了對齊本文件把它改掉。本 phase 只負責 ★ 那三段。

再跑一次規格測試，**這次要全綠**：

```bash
pytest tests/integration/test_upload_feature.py -v
```

預期最後一行：`10 passed`。測試名稱應該對應到 10 個 Example：

1. 非圖片格式的檔案上傳失敗
2. 上傳 Target 收據照片後儲存文字描述
3. 上傳 Target 收據照片後儲存結構化 metadata
4. 上傳照片後產生 embedding 向量
5. 上傳照片後記錄上傳時間
6. 上傳照片後保留原圖與縮圖
7. 上傳成功的回應內容
8. 上傳成功的回應包含建議資料夾與資料夾清單
9. VLM 推薦清單外的名稱
10. VLM 無法理解照片內容的上傳

### 步驟 5：逐檔檢視既有測試（四個檔，每一個測試都點名）

先跑全量看紅在哪：

```bash
pytest -q
```

以下把**每一個測試**點名，說明「改／不改」與理由。

兩個前提先講清楚，才知道什麼**不用**再做：

1. **圖片位元組 Phase 19 已經全部換好了**（五個檔案、五處，改用 `make_png_bytes()`／`make_jpeg_bytes()`／`make_large_png_bytes()`）。本 phase 只處理**行為斷言**的改版，不再碰位元組。
2. 不在下列清單裡的檔案（`tests/unit/`、`test_ask_endpoint.py`、`test_ask_feature.py`、`test_retrieval.py`、`test_workflow_route.py`、`test_photo_repository.py`、Phase 16 的 `test_folder_repository.py`、Phase 19 的 `test_photo_files.py`）**完全不用動**——它們要不是不經過上傳端點（直接用 repository 寫測試資料），就是本來就照新流程寫的。特別是 `test_retrieval.py` 直接用 `insert_photo(category="Receipt")` 塞資料，不受「上傳一律未分類」影響。

#### (a) `tests/integration/test_upload_bilingual.py`（1 個測試）

`test_英文照片的描述與欄位原樣儲存不翻譯` **要改**：VLM 回的 `Receipt` 不在資料夾清單裡，新行為下它會被 clamp 成「未分類」，而 `text`／`location`／`items` 仍保持英文原文。這個測試因此變得更有價值——它同時守住「不翻譯」與「清單外→未分類」。**整檔換成**：

```python
"""雙語：英文照片的描述與欄位原樣儲存，系統不做翻譯（design.md §8.1、§8.3）。

規格 .feature 全為中文，雙語行為以本檔額外覆蓋。
2026-08-20 起 category 不再由 VLM 決定：英文的 "Receipt" 不在資料夾清單內，
會被 clamp_category 夾成「未分類」——但 text／location／items 依然是英文原文。
"""

from __future__ import annotations

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_png_bytes

PNG_BYTES = make_png_bytes()   # Phase 19 已改成這樣，本 phase 沿用

英文收據 = PhotoUnderstanding(
    understood=True,
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time="2026-08-10",
)


def test_英文照片的描述與欄位原樣儲存不翻譯(client):
    # 假 embedding／固定時鐘由 conftest 的 wire_fake_ai 自動接上，這裡只換看圖結果
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    # 回應：英文原文（唯一的例外是 category——它現在代表「所屬資料夾」）
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["metadata"] == {
        "category": "未分類",
        "location": "Target",
        "items": ["Cola", "Chips"],
        "content_time": "2026-08-10",
    }
    # "Receipt" 不在資料夾清單裡 → 建議也退回「未分類」（design1.md §7.1）
    assert body["suggested_folder"]["name"] == "未分類"
    assert body["folder"]["name"] == "未分類"
    # 資料庫：地點與物品也是英文原文，沒有任何一處被翻成中文
    row = photo_repository.fetch_photo(body["id"])
    assert row["category"] == "未分類"
    assert row["location"] == "Target"
    assert row["items"] == ["Cola", "Chips"]
    assert photo_repository.fetch_embedding(body["id"]) is not None
```

#### (b) `tests/integration/test_upload_design_rules.py`（4 個測試——原 3 個＋Phase 18 追加 1 個）

| 測試 | 改不改 | 說明 |
|---|---|---|
| `test_非圖片格式不會呼叫看圖` | **不改** | 415 在看圖與寫檔之前就結束 |
| `test_理解結果text全空白也回422且不儲存` | **不改** | 422 也在寫檔之前 |
| `test_向量由合併內容產生而非只有文字` | **要改** | 期望向量的 category 要從「收據」改成「未分類」 |
| `test_上傳時把現有資料夾清單傳給看圖`（Phase 18 追加） | **不改** | 只驗「清單有傳給 `understand()`」與回 201；本 phase 之後上傳照樣先讀清單再看圖，不受「一律掛未分類」影響 |

（檔案開頭的 `PNG_BYTES` 已由 Phase 19 改成 `make_png_bytes()`，本 phase 不動它。）

把 `test_向量由合併內容產生而非只有文字` 裡計算期望向量的這一段：

```python
    stored = json.loads(photo_repository.fetch_embedding(response.json()["id"]))
    document = build_document(
        text="超市購物的照片",
        category="收據",
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
```

改成（只有 `category` 那一行變了，另外補一句註解）：

```python
    stored = json.loads(photo_repository.fetch_embedding(response.json()["id"]))
    # 2026-08-20 起上傳一律用「未分類」合併——VLM 講的「收據」只是建議，不落庫。
    # 歸類後的重算由 PATCH /photos/{id}/folder 負責（Phase 21 另有測試）。
    document = build_document(
        text="超市購物的照片",
        category="未分類",
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
```

順手在同一個測試的 `assert response.status_code == 201` 下面補兩行，把「不落庫」講死：

```python
    assert response.json()["metadata"]["category"] == "未分類"
    assert response.json()["suggested_folder"]["name"] == "收據"
```

> 這個測試的護欄仍然有效：`text` 是「超市購物的照片」，裡面沒有 Costco／咖啡／牛奶，所以「合併版向量」和「只有 text 的向量」依然分得出來（`> 1e-3` 那一行）。「未分類」不在假件的詞表裡，不影響比對。

#### (c) `tests/integration/test_photos_upload.py`（7 個測試）

| 測試 | 改不改 | 說明 |
|---|---|---|
| `test_upload_non_image_returns_415_with_message` | 不改 | 415，不寫檔 |
| `test_upload_non_image_stores_nothing` | 不改 | 同上 |
| `test_upload_octet_stream_returns_415` | 不改 | 同上 |
| `test_upload_png_understood_returns_201` | 不改 | 它的 `PNG_BYTES` 本來就是真的 1×1 PNG（base64 解出來的），Pillow 開得起來；這個測試只驗「PNG 通得過格式閘門＋回 201＋文字對」，新欄位由規格檔的 Rule 把關 |
| `test_upload_jpeg_understood_returns_201` | 不改 | Phase 19 已經把假 JPEG 換成 `make_jpeg_bytes()` |
| `test_upload_missing_file_returns_422` | 不改 | 沒夾檔案，框架就擋掉了 |
| `test_openapi_has_photos_endpoint` | 不改 | 只看路徑有沒有掛上 |

**這個檔本 phase 一行都不用改。** 它的七個測試全部只驗「格式閘門」與「回 201」，沒有任何一個斷言 `category` 等於 VLM 給的值——所以規格改版不會波及它。跑一次確認就好：

```bash
pytest tests/integration/test_photos_upload.py -q
```

預期：`7 passed`。

#### (d) `tests/integration/test_error_paths.py`（11 個測試，含 parametrize 展開）

| 測試 | 改不改 | 說明 |
|---|---|---|
| `test_非圖片格式回415且不寫入` | 不改 | 415 在看圖與寫檔前就結束 |
| `test_vlm看不懂回422且不寫入` | 不改 | 422 也在寫檔前，`b"\x89PNG"` 沒被 Pillow 碰到 |
| `test_大檔案照樣可以上傳` | 不改 | Phase 19 已經換成 `make_large_png_bytes()` |
| `test_程式碼裡沒有任何檔案大小上限檢查` | 不改 | 本 phase 沒有引入 `max_size`／`413` 之類的東西（改完記得別加） |
| `test_問題缺漏或空字串回422`（×2） | 不改 | 打的是 `/ask` |
| `test_路由失敗仍回200並走語意查詢` | 不改 | 打的是 `/ask` |
| `test_查無照片回200且不編造` | 不改 | 打的是 `/ask` |
| `test_英文提問查無照片時用英文回覆` | 不改 | 打的是 `/ask` |
| `test_embedding失敗回500` | 不改 | embedding 在 INSERT 與寫檔之前就炸掉，`count_photos() == 0` 依然成立 |
| `test_資料庫掛掉回500` | 不改 | 打的是 `/ask` |

**這個檔本 phase 也一行都不用改**（它的 `TARGET_RECEIPT` 假件雖然 `category="收據"`，但沒有任何測試去斷言存進去的 category 是什麼）。跑一次確認：

```bash
pytest tests/integration/test_error_paths.py -q
```

預期：全綠（顆數以實際輸出為準）。

### 步驟 6：全量回歸並 commit

```bash
pytest -q
```

預期：全綠，顆數 ＝ 步驟 0 記下的基線 **＋3 ＝ 124**。

再單獨確認詢問規格沒被波及：

```bash
pytest tests/integration/test_ask_feature.py -v
git diff --stat docs/spec/features/自然語言詢問.feature
```

預期：前者 `7 passed`（Q1〜Q5 共 7 個例子）；後者**沒有任何輸出**（檔案一個字都沒動）。

commit（訊息裡的「累計 NN」請填上一步 `pytest -q` 實際印出的數字）：

```bash
git add docs/spec/features/上傳照片.feature app/schemas/photo.py app/api/routers/photos.py tests/
git commit -m "feat: Phase 20 上傳未分類流程與規格改版——上傳一律先掛「未分類」、VLM 類別只當建議（clamp 後回 suggested_folder），回應加 folder／suggested_folder／folders／thumbnail_url；上傳規格檔正式改版（7→10 條 Rule）＋既有上傳測試同步改版，+3 tests（累計 NN）"
```

---

## 驗收清單

- [ ] `pytest tests/integration/test_upload_feature.py -v` → **10 passed**，10 個名稱與規格 Example 一一對應
- [ ] `grep -c "Rule:" docs/spec/features/上傳照片.feature` → `10`；`grep -c "Example:" …` → `10`
- [ ] Rule 正文已無「不含原始照片檔」約束（2026-08-21 校準：檔頭 `#` 註解會逐字引用舊定案宣告其被推翻，屬預期，掃描時要排除註解行）：
      ```bash
      grep -v "^#" docs/spec/features/上傳照片.feature | grep -n "不含原始照片檔" || echo "OK：已移除"
      ```
      → 印 `OK：已移除`
- [ ] `grep -n "2026-08-20 依 docs/design/design1.md 正式改版" docs/spec/features/上傳照片.feature` → 有輸出（檔頭註解已註明改版來源）
- [ ] `git diff --stat docs/spec/features/自然語言詢問.feature` → **沒有輸出**（詢問規格一個字沒動）
- [ ] `pytest tests/integration/test_ask_feature.py -v` → **7 passed**（Q1〜Q5 全綠）
- [ ] 資料庫真的存「未分類」：
      ```bash
      psql -d PersonalDocAI_test -c "SELECT category, folder_id FROM photo LIMIT 1;"
      ```
      （跑完 pytest 後表會被清空，這一項用下面的手動確認代替也可以）
- [ ] 手動確認回應長相（不需要 Ollama）：
      ```bash
      python - <<'PY'
      import os
      # 一定要在 import app.* 之前指到測試庫（config 在 import 當下就讀環境變數）
      os.environ["DATABASE_URL"] = "postgresql://localhost:5433/PersonalDocAI_test"
      # 檔案也寫到暫存區，不要在專案的 data/ 留下手動測試的殘骸
      os.environ["DATA_DIR"] = "/tmp/personaldocai-manual-check"

      from fastapi.testclient import TestClient
      from app.dependencies import get_vlm, get_embeddings
      from app.main import app
      from app.repositories import photo_repository
      from app.services.vlm_service import PhotoUnderstanding
      from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes
      import json

      photo_repository.reset_folders_and_photos()
      app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
      app.dependency_overrides[get_vlm] = lambda: FakeVLM(PhotoUnderstanding(
          understood=True, text="在 Target 購買可樂的收據", category="收據",
          location="Target", items=["可樂"], content_time="2026-08-10"))
      body = TestClient(app).post(
          "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
      ).json()
      print(json.dumps({k: body[k] for k in
            ("metadata", "folder", "suggested_folder", "thumbnail_url")},
            ensure_ascii=False, indent=2))
      print("folders：", [f["name"] for f in body["folders"]])
      PY
      ```
      預期：`metadata.category` 與 `folder.name` 都是「未分類」、`suggested_folder.name` 是「收據」、`thumbnail_url` 是 `/photos/1/thumbnail`、`folders` 印出六個名稱
- [ ] pytest 沒有寫進專案的 `data/`：`ls data/photos 2>/dev/null | wc -l` 在跑 `pytest -q` **前後各執行一次，兩次數字相同**（`data/` 已被 .gitignore 忽略，用 `git status` 看不出來；Phase 17 的 `isolated_data_dir` 應把測試檔案全部導到 tmp）
- [ ] `pytest -q` **全綠**，顆數 ＝ 基線 ＋3 ＝ **124**
- [ ] `git commit` 完成（訊息含實際累計顆數）

---

## 常見問題

**Q1：規格檔不是唯讀嗎？改它會不會違反前面 phase 的規定？**
`上傳照片.feature` 的唯讀已由產品負責人於 2026-08-20 明示解除（撰寫契約 §0.1、design1.md §1.1）。原因是「不儲存原始照片檔」「category 由 VLM 自由填」這兩條**定案本身被推翻**了，不是實作做不到。但解除範圍只有這一個檔：`自然語言詢問.feature` 仍然唯讀。

**Q2：為什麼不乾脆讓上傳直接存 VLM 建議的資料夾，使用者要改再改就好？**
design1.md §14 已經否決這個方案（「沒選就自動採用 AI 第一推薦」＝失去 human-in-the-loop）。上傳只負責把照片安全收進來，分類是使用者的決定。

**Q3：`next(folder for folder in folders if folder["is_inbox"])` 找不到會怎樣？**
會丟 `StopIteration` → 500。這不會發生：`db/schema.sql` 與 `db/migrate_folders.sql` 都會種入「未分類」，而且 `folder_one_inbox` 這個唯一索引保證全域只有一個收件箱。**不要**為此加 try/except 或預設值——那是在掩蓋「資料庫沒建好」這種應該吵起來的問題。

**Q4：`suggested_folder` 可不可以是 null（VLM 完全沒概念的時候）？**
不行。design1.md §7.1 規定它一定是 `folders` 裡的一筆；VLM 沒概念時 `clamp_category` 會回「未分類」，此時選項①和「關掉彈窗」結果相同——設計文件明說「可接受」。回應模型也把它宣告成必填的 `FolderOut`，少填會直接報錯。

**Q5：測試跑完專案裡出現了 `data/photos/1.png`，是不是寫錯地方了？**
是。Phase 17 的 `isolated_data_dir` fixture 應該把 `config.DATA_DIR` 指到 pytest 的暫存資料夾。出現這種檔案代表某個測試繞過了 fixture（例如自己 import 了 `config` 之前的舊值）。先把檔案刪掉，再檢查 `tests/conftest.py` 的 fixture 是不是 `autouse=True`。

**Q6：`照片所屬資料夾為 "未分類"` 這條過不了，但 `metadata.category` 是對的。**
代表 `category` 字串寫對了，但 `folder_id` 沒掛對。看 Phase 15 的 `insert_photo`——它是用「大小寫不敏感比對同名資料夾」決定 `folder_id` 的，如果找不到就掛收件箱。傳進去的 category 必須**一字不差**是「未分類」（不要寫成「未分類 」或「未分類照片」）。

**Q7：可不可以順便把 `PhotoMetadata.category` 改名成 `folder_name`？**
不可以。`category` 是 `photo` 表的既有欄位，條件查詢（`search_by_metadata`）與 embedding 合併格式都讀它；改名會連帶動到詢問流程，超出本 phase 範圍（design1.md §6 明講「category 是給檢索用的冗餘欄位，保留」）。

**Q8：`test_upload_feature.py` 報 `StepDefinitionNotFoundError`。**
步驟字串必須和 `.feature` 檔**一字不差**，包含全形逗號「，」與空白。把 `.feature` 裡那一行複製貼上到 `@when(...)`／`@then(...)` 裡最保險。

---

## 完成後的專案狀態

上傳流程完成最終形：照片進來 → VLM 帶著資料夾清單看圖 → 建議被夾回清單內 → 照片先躺在「未分類」→ 原圖與縮圖落地 → 201 回應一次帶齊彈窗要用的所有資料。規格檔已正式改版成新行為（10 條 Rule 全綠），詢問規格 5 條 Rule 完全不受影響。**但使用者還沒辦法「確認歸類」**——按下彈窗按鈕之後要打的那個端點是 Phase 21 的事。測試顆數 ＝ 開工基線 ＋3 ＝ **124**。
