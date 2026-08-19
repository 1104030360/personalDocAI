# Phase 7：上傳驗收測試（`上傳照片.feature` 7 條 Rule 全綠）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 用 pytest-bdd 直接把 `docs/spec/features/上傳照片.feature` 當測試跑，7 條 Rule（U1〜U7）全部通過；另外補上兩個規格沒涵蓋但設計有規定的單元測試檔（合併格式、英文照片不翻譯）。這是第一個驗收里程碑。

---

## 前置條件

- 需要已完成的 phase：**Phase 6**（上傳流程完整跑通）。
- 環境：**PostgreSQL 必須在跑**（沒在跑就先 `brew services start postgresql@17`），且測試資料庫 `visual_memory_test` 已建表；**不需要 Ollama**（全程用假件）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

前面幾個 phase 是「我覺得做對了」，這個 phase 是「規格說我做對了」。

`.feature` 檔是規格本身，用 Given / When / Then 寫成。**pytest-bdd** 這個套件可以把每一句步驟對應到一段 Python 程式碼，於是規格檔就直接變成測試。我們**不複製規格內容**——測試直接讀 `docs/spec/features/` 底下的原檔，規格改了測試就跟著改。

這個 phase 不寫任何產品程式碼，只寫測試。如果有 Rule 沒過，代表前面某個 phase 做錯了，要回頭修產品程式碼，**不能改規格檔**（`docs/spec/` 是唯讀的）。

規格檔全部是中文，這是刻意的（design.md §11：不改動規格檔）。**雙語行為用額外的單元測試覆蓋**——所以本 phase 另外建一個 `tests/test_upload_bilingual.py`，驗「英文照片的描述與欄位原樣儲存、不翻譯」。

**名詞**：
- **pytest**＝Python 最常用的測試框架，執行 `pytest` 就會找出所有測試並跑一遍。
- **pytest-bdd**＝讓 pytest 能執行 `.feature` 規格檔的外掛。`scenarios("路徑")` 這一行會把該檔案的所有 Example 變成測試。
- **fixture**＝pytest 提供給測試用的「準備好的東西」（例如一個測試用戶端、一個乾淨的資料庫）。
- **datatable**＝Gherkin 步驟底下那張表格；pytest-bdd 會把它當成「列的清單」交給步驟函式（第 0 列是欄位名）。步驟函式只要宣告一個名叫 `datatable` 的參數就拿得到。
- **`parsers.parse`**＝pytest-bdd 的步驟比對工具。步驟文字裡的 `{text}`、`{count:d}` 是「挖洞」的佔位符，實際值會自動傳進步驟函式的同名參數（`:d` 表示這個洞只收整數）。

---

## ASCII 圖：規格檔如何變成測試

```
 docs/spec/features/上傳照片.feature   （規格原檔，唯讀，不得修改）
   Rule: VLM 無法理解照片內容時，上傳失敗且不儲存任何資料
     Example: VLM 無法理解照片內容的上傳
       Given VLM 無法理解上傳照片的內容
       When  使用者上傳照片
       Then  操作失敗
       And   系統儲存的照片數量為 0
              │
              │ pytest-bdd 的 scenarios() 讀進來
              ▼
 tests/test_upload_feature.py         （步驟定義：一句話 → 一段程式碼）
   @given("VLM 無法理解上傳照片的內容")  → 準備 PhotoUnderstanding(understood=False)
                                          （When 上傳時再包進 FakeVLM）
   @when("使用者上傳照片")               → client.post("/photos", ...)
   @then("操作失敗")                     → assert 狀態碼 >= 400
   @then("系統儲存的照片數量為 0")        → assert photo_repository.count_photos() == 0
              │
              ▼
      真的呼叫 app（FastAPI）→ api/routers/photos.py → services → repositories
              │  假件已注入：FakeVLM / FakeEmbeddings ＋ 固定「現在時間」
              │  （design.md §11 的 FixedClock 角色，由覆寫 get_now 的 lambda 扮演）
              ▼
      真的寫入 visual_memory_test 資料庫

 ── 規格檔沒寫、但設計有規定的行為，另外用單元測試補 ──
 tests/test_indexing.py         合併順序固定（中文＋英文）
 tests/test_upload_bilingual.py 英文照片描述與欄位原樣儲存、不翻譯
```

---

## 逐步驟操作

### 步驟 1：在 `tests/fakes.py` 補上「文字 → 假理解結果」的對照

規格的 When 步驟只給了文字描述（`VLM 理解其內容為 "…"`），但 Then 步驟要驗四個 metadata 欄位。所以假件要知道「這段文字對應哪四個欄位」。用一張明確的對照表，最不容易出錯：

```python
# 接在 tests/fakes.py 既有內容後面

# 規格例子出現過的文字 → 對應的假 VLM 結果。
# 規格新增例子時，在這裡補一筆即可。
KNOWN_UNDERSTANDINGS: dict[str, PhotoUnderstanding] = {
    "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10": PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    ),
}


def understanding_for_text(text: str) -> PhotoUnderstanding:
    """依規格步驟給的文字，取出對應的假 VLM 結果。"""
    if text not in KNOWN_UNDERSTANDINGS:
        raise KeyError(
            f"沒有為這段文字準備假的 VLM 結果：{text}\n"
            "請到 tests/fakes.py 的 KNOWN_UNDERSTANDINGS 補一筆。"
        )
    return KNOWN_UNDERSTANDINGS[text]
```

### 步驟 2：在 `tests/conftest.py` 補上共用小工具

放在 `conftest.py`（而不是測試檔裡）是因為 Phase 12 的詢問驗收測試也會用到 `split_items`。

```python
# 接在 tests/conftest.py 既有內容後面


def first_row(datatable: list[list[str]]) -> dict[str, str]:
    """把 Gherkin 表格的第一列資料轉成字典（第 0 列是欄位名）。"""
    header, *rows = datatable
    return dict(zip(header, rows[0]))


def split_items(cell: str) -> list[str]:
    """規格表格用「、」分隔多個物品，例如「可樂、洋芋片」。"""
    cell = cell.strip()
    return [part for part in cell.split("、") if part] if cell else []
```

### 步驟 3：建立 `tests/test_upload_feature.py`

```python
"""把 docs/spec/features/上傳照片.feature 當測試跑（7 條 Rule）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_embeddings, get_now, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import first_row, split_items
from tests.fakes import FakeEmbeddings, FakeVLM, understanding_for_text

# 直接掛上規格原檔——不複製、不改寫
scenarios("../docs/spec/features/上傳照片.feature")

# 假的照片內容。全程用假件，不會真的被拿去看圖
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"

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
def wire_fakes(context):
    """把假件接到 app 上（真 AI 與真時鐘都不會被呼叫）。"""
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield
    app.dependency_overrides.clear()


def _upload(context, client, filename="photo.png", content_type="image/png",
            payload=PNG_BYTES):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(context["understanding"])
    context["response"] = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )


def _stored_photo(context) -> dict:
    photo_id = context["response"].json()["id"]
    row = photo_repository.fetch_photo(photo_id)
    assert row is not None, "資料庫裡找不到剛剛上傳的照片"
    return row


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
            content_type="text/plain", payload=b"這不是圖片")


@when(parsers.parse('使用者上傳一張照片，VLM 理解其內容為 "{text}"'))
def 上傳照片並指定理解內容(context, client, text):
    context["understanding"] = understanding_for_text(text)
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


@then("照片的 embedding 不為空")
def 照片embedding不為空(context):
    embedding = photo_repository.fetch_embedding(context["response"].json()["id"])
    assert embedding is not None
    assert embedding.startswith("[") and len(embedding) > 2


@then(parsers.parse('照片的上傳時間為 "{moment}"'))
def 照片上傳時間為(context, moment):
    uploaded_at = _stored_photo(context)["uploaded_at"]
    assert uploaded_at.strftime("%Y-%m-%d %H:%M") == moment


@then("回應包含照片識別碼")
def 回應包含識別碼(context):
    body = context["response"].json()
    assert isinstance(body.get("id"), int) and body["id"] > 0


@then(parsers.parse('回應的文字描述為 "{text}"'))
def 回應文字描述為(context, text):
    assert context["response"].json()["text"] == text


@then("回應的 metadata 欄位如下")
def 回應metadata為(context, datatable):
    expected = first_row(datatable)
    metadata = context["response"].json()["metadata"]
    assert metadata["category"] == expected["category"]
    assert metadata["location"] == expected["location"]
    assert metadata["items"] == split_items(expected["items"])
    assert (metadata["content_time"] or "") == expected["content_time"].strip()
```

### 步驟 4：把暫時性的煙霧測試換成兩個正式的單元測試檔

`tests/test_upload_smoke.py` 的內容幾乎都被上面的正式驗收取代了，只有兩件事是規格 `.feature` 沒驗、但 design.md 有規定的，要保留下來：

- **合併順序固定**（design.md §9）：規格只驗「embedding 不為空」，沒驗合併格式。
- **英文照片不翻譯**（design.md §8.1、§8.3）：規格全是中文例子，雙語行為靠額外測試覆蓋。

做法：建兩個新檔案，再刪掉整個煙霧測試檔。

```bash
cd /Users/linjunting/personalDocAI
rm tests/test_upload_smoke.py
```

建立 `tests/test_indexing.py`：

```python
"""合併內容的格式必須固定：同輸入 → 同向量（design.md §9）。"""

from app.services.indexing_service import build_document


def test_合併內容的順序固定():
    document = build_document(
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    )
    assert document.page_content == (
        "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10\n"
        "類別: 收據\n"
        "地點: Target\n"
        "物品: 可樂、洋芋片\n"
        "時間: 2026-08-10"
    )


def test_空欄位會被省略():
    document = build_document(
        text="海邊的風景照", category="風景", location="海邊",
        items=[], content_time=None,
    )
    assert document.page_content == "海邊的風景照\n類別: 風景\n地點: 海邊"


def test_英文內容的欄位值保持原文標籤仍為中文():
    """雙語：標籤是固定格式的一部分不變，值保持照片原文（不翻譯）。"""
    document = build_document(
        text="Receipt from Target with Cola and Chips",
        category="Receipt", location="Target",
        items=["Cola", "Chips"], content_time="2026-08-10",
    )
    assert document.page_content == (
        "Receipt from Target with Cola and Chips\n"
        "類別: Receipt\n"
        "地點: Target\n"
        "物品: Cola、Chips\n"
        "時間: 2026-08-10"
    )
```

建立 `tests/test_upload_bilingual.py`：

```python
"""雙語：英文照片的描述與四個欄位原樣儲存，系統不做翻譯（design.md §8.1、§8.3）。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.dependencies import get_embeddings, get_now, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"

英文收據 = PhotoUnderstanding(
    understood=True,
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_fakes():
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_now] = lambda: datetime(2026, 8, 18, 10, 0)
    yield
    app.dependency_overrides.clear()


def test_英文照片的描述與欄位原樣儲存不翻譯(client):
    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    # 回應：英文原文
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["metadata"] == {
        "category": "Receipt",
        "location": "Target",
        "items": ["Cola", "Chips"],
        "content_time": "2026-08-10",
    }
    # 資料庫：也是英文原文，沒有任何一處被翻成中文
    row = photo_repository.fetch_photo(body["id"])
    assert row["category"] == "Receipt"
    assert row["items"] == ["Cola", "Chips"]
    assert photo_repository.fetch_embedding(body["id"]) is not None
```

---

## 驗收標準

1. **上傳規格 7 個例子全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/test_upload_feature.py -v
   ```
   預期最後一行：`7 passed`
   預期看到 7 個測試名稱，分別對應 7 條 Rule 底下的 Example（名稱取自 `.feature` 檔原文）：
   1. 非圖片格式的檔案上傳失敗
   2. 上傳 Target 收據照片後儲存文字描述
   3. 上傳 Target 收據照片後儲存結構化 metadata
   4. 上傳照片後產生 embedding 向量
   5. 上傳照片後記錄上傳時間
   6. 上傳成功的回應內容
   7. VLM 無法理解照片內容的上傳

2. **全部測試一起跑也全綠**
   ```bash
   pytest -q
   ```
   預期最後一行：`11 passed`（規格 7 ＋ indexing 3 ＋ 雙語 1）（**測試累計數：11**）

3. **沒有任何步驟沒對應到程式碼**
   ```bash
   pytest tests/test_upload_feature.py 2>&1 | grep -i "StepDefinitionNotFound" || echo "所有步驟都有對應"
   ```
   預期輸出：`所有步驟都有對應`

4. **煙霧測試檔真的刪掉了**
   ```bash
   ls tests/test_upload_smoke.py 2>/dev/null || echo "OK：暫時性檔案已移除"
   ```
   預期輸出：`OK：暫時性檔案已移除`

5. **測試沒有碰到正式資料庫**
   ```bash
   psql -d visual_memory -c "SELECT count(*) FROM photo;"   # 記下這個數字
   pytest -q
   psql -d visual_memory -c "SELECT count(*) FROM photo;"   # 應該和剛剛記的一樣
   ```
   預期：前後兩次的筆數**相同**——測試只碰 `visual_memory_test`（`conftest.py` 已把 `DATABASE_URL` 指向它），正式資料庫完全不受影響。

6. **測試完全不需要 Ollama**
   ```bash
   brew services stop ollama
   pytest -q
   brew services start ollama
   ```
   預期：Ollama 停掉的情況下測試仍然 `11 passed`（因為 AI 全部被假件取代）。三行分開執行——就算第二行測試失敗，也記得把第三行跑完，讓 Ollama 恢復運作。

7. **規格檔沒有被動過**
   ```bash
   grep -c "Rule:" docs/spec/features/上傳照片.feature
   ```
   預期輸出：`7`（規格檔是唯讀的，測試通不過只能改產品程式碼）。

---

## 常見問題

**Q1：`StepDefinitionNotFoundError: Step definition is not found: When "使用者上傳照片"`。**
步驟字串必須和 `.feature` 檔**一字不差**，包含全形逗號「，」與空白。把 `.feature` 裡那一行複製貼上到 `@when(...)` 裡最保險。

**Q2：`FeatureError` 或 `Rule` 不被支援。**
`Rule` 與 `Example` 需要較新的 pytest-bdd（使用官方 Gherkin 解析器的版本）。執行 `uv pip install -U "pytest-bdd>=8.1"` 後再跑一次。

**Q3：找不到 feature 檔（`FileNotFoundError`）。**
`scenarios("../docs/spec/features/上傳照片.feature")` 的路徑是相對於**測試檔所在資料夾**（`tests/`），跟你在哪個資料夾執行 `pytest` 無關。確認兩件事：測試檔真的放在 `tests/` 底下；專案根目錄底下真的有 `docs/spec/features/上傳照片.feature`（檔名一字不差）。

**Q4：`照片的上傳時間為 "2026-08-18 10:00"` 這條過不了。**
兩個常見原因：(a) `Given 現在時間為 …` 的步驟沒有在 When 之前生效——確認 `wire_fakes` 的 `get_now` 覆寫是讀 `context["now"]` 的 lambda，而不是在 fixture 建立當下就把值固定；(b) 比對方式錯誤——只能比對到「分」，不要比對整個 `datetime` 物件。

**Q5：測試之間互相影響（第二個測試看到第一個測試的資料）。**
`conftest.py` 的 `clean_database` 是 `autouse=True`，每個測試前都會 `TRUNCATE`。若沒生效，確認這個 fixture 真的在 `tests/conftest.py` 裡，而且沒有被覆寫。

**Q6：規格檔沒有英文例子，可不可以自己加一條英文 Rule？**
**不可以。** `docs/spec/` 是唯讀的。design.md §11 明訂雙語行為用**額外的單元測試**覆蓋，這就是 `tests/test_upload_bilingual.py` 的存在理由。

---

## 完成後的專案狀態

第一個驗收里程碑達成：`上傳照片.feature` 的 7 條 Rule（U1〜U7）全部由自動化測試把關並通過，另外有 3 個合併格式測試與 1 個英文照片測試守住 design.md 規定但規格沒寫的行為，而且完全不依賴真的 AI 服務。系統的「上傳」功能在規格層面已經完成。測試累計 **11** 個。
