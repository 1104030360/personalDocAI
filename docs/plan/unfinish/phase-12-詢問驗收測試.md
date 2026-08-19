# Phase 12：詢問驗收測試（`自然語言詢問.feature` 5 條 Rule 全綠）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 用 pytest-bdd 直接把 `docs/spec/features/自然語言詢問.feature` 當測試跑，5 條 Rule（Q1〜Q5）全部通過。這是第二個驗收里程碑。

---

## 前置條件

- 需要已完成的 phase：**Phase 11**（`POST /ask` 完整可用、測試累計 31）。
- 環境：測試資料庫可用；**不需要 Ollama**（全程用假件）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

跟 Phase 7 一樣的做法，換成詢問這一份規格：把 `.feature` 的每一句步驟對應到程式碼，讓規格自己驗證系統。**規格檔一個字都不能改**（`docs/spec/` 唯讀），英文提問的雙語行為已經在 Phase 9〜11 用額外的單元測試覆蓋過了。

這份規格有兩個新的挑戰：

1. **Given 會給一整張照片表格**（id、text、category、location、items、content_time、uploaded_at）。步驟要照表格把照片寫進測試資料庫。
2. **表格裡的 id 是規格自己編的號碼**（1、2、3），資料庫實際產生的 id 不保證一樣。所以要維護一張「規格 id → 實際 id」的對照表，驗證時做轉換。

另外有一個必須明講的決定：整份規格只有時間過濾那條 Rule 的例子有寫 `Given 現在時間為 "2026-08-18 10:00"`；**其餘沒有指定現在時間的例子，測試一律使用預設固定時間 `2026-08-18 10:00`**。理由很實際——那些例子的照片日期是 2026 年 8 月，如果用「真的今天」去算 30 天，測試會隨著執行日期慢慢壞掉。固定時間讓測試永遠可重現。

---

## ASCII 圖：一個例子如何被驗證

```
 docs/spec/features/自然語言詢問.feature       （規格原檔，唯讀，不得修改）
   Rule: 詢問含時間條件時，系統以內容時間過濾，內容時間為空的照片以上傳時間過濾
     Given 現在時間為 "2026-08-18 10:00"
     And   系統中有底下照片
           | id | text | … | content_time | uploaded_at      |
           | 1  | …    | … | 2026-08-10   | 2026-08-18 10:00 |
           | 2  | …    | … | 2026-05-01   | 2026-08-17 09:00 |
           | 3  | …    | … |              | 2026-08-15 12:00 |
     When  使用者詢問 "我最近買過什麼飲料？"
     Then  時間過濾後的照片為底下照片 → | 1 | | 3 |
              │
              ▼
 tests/test_ask_feature.py
   Given 現在時間  → context["now"] = 2026-08-18 10:00（get_now 會讀它）
   Given 系統中有… → 逐列 photo_repository.insert_photo()，記錄 規格id → 實際id
   When  使用者詢問 → client.post("/ask", json={"question": …})
   Then  時間過濾後 → assert 回應的 retrieved_photo_ids == 對照後的 [1, 3]
              │
              ▼
   假件全部就位：FakeRouter / FakeEmbeddings / FakeAnswerLLM
                ＋固定時鐘（get_now 被覆寫成回傳 context["now"]）
   真的走過：api/routers/ask.py → ask_workflow 的 route 節點
             → retrieval_service → photo_repository 的 SQL 時間過濾
             → generate 節點
```

---

## 逐步驟操作

### 步驟 1：建立 `tests/test_ask_feature.py`

```python
"""把 docs/spec/features/自然語言詢問.feature 當測試跑（5 條 Rule）。"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from app.dependencies import get_answerer, get_embeddings, get_now, get_router
from app.main import app
from app.repositories import photo_repository
from app.services import indexing_service
from tests.conftest import split_items
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

# 直接掛上規格原檔——不複製、不改寫
scenarios("../docs/spec/features/自然語言詢問.feature")

# 規格沒有指定「現在時間」的例子一律用這個固定時間，
# 測試才不會因為今天是哪一天而時好時壞。
DEFAULT_NOW = datetime(2026, 8, 18, 10, 0)


@pytest.fixture
def context() -> dict:
    return {
        "now": DEFAULT_NOW,
        "id_map": {},        # 規格表格裡的 id → 資料庫實際的 id
        "response": None,
    }


@pytest.fixture(autouse=True)
def wire_fakes(context):
    """把四種假件接到 app 上（完全不需要 Ollama）。"""
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_answerer] = lambda: FakeAnswerLLM()
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_now] = lambda: context["now"]
    yield
    app.dependency_overrides.clear()


def _rows(datatable: list[list[str]]) -> list[dict[str, str]]:
    """把 Gherkin 表格轉成「每列一個字典」（第 0 列是欄位名）。"""
    header, *rows = datatable
    return [dict(zip(header, row)) for row in rows]


def _expected_ids(context, datatable) -> list[int]:
    """把規格表格裡的 id 轉成資料庫實際的 id。"""
    return sorted(context["id_map"][row["id"]] for row in _rows(datatable))


def _actual_ids(context) -> list[int]:
    return sorted(context["response"].json()["retrieved_photo_ids"])


# ------------------------------ Given ------------------------------
@given(parsers.parse('現在時間為 "{moment}"'))
def 設定現在時間(context, moment):
    context["now"] = datetime.strptime(moment, "%Y-%m-%d %H:%M")


@given("系統中有底下照片")
def 建立照片(context, datatable):
    embeddings = FakeEmbeddings()
    for row in _rows(datatable):
        content_time_text = row["content_time"].strip()
        content_time = date.fromisoformat(content_time_text) if content_time_text else None
        items = split_items(row["items"])

        # 向量的產生方式與上傳路徑完全一致：文字＋四欄位合併後再轉向量
        document = indexing_service.build_document(
            text=row["text"],
            category=row["category"].strip() or None,
            location=row["location"].strip() or None,
            items=items,
            content_time=content_time.isoformat() if content_time else None,
        )
        stored = photo_repository.insert_photo(
            text=row["text"],
            category=row["category"].strip() or None,
            location=row["location"].strip() or None,
            items=items,
            content_time=content_time,
            embedding=embeddings.embed_query(document.page_content),
            uploaded_at=datetime.strptime(row["uploaded_at"], "%Y-%m-%d %H:%M"),
        )
        context["id_map"][row["id"]] = stored["id"]


@given("系統中沒有任何照片")
def 沒有任何照片():
    assert photo_repository.count_photos() == 0


# ------------------------------- When ------------------------------
@when(parsers.parse('使用者詢問 "{question}"'))
def 使用者詢問(context, client, question):
    context["response"] = client.post("/ask", json={"question": question})
    assert context["response"].status_code == 200, context["response"].text


# ------------------------------- Then ------------------------------
@then(parsers.parse('系統選擇的檢索方式為 "{mode}"'))
def 檢索方式為(context, mode):
    assert context["response"].json()["search_mode"] == mode


@then("時間過濾後的照片為底下照片")
def 時間過濾後的照片為(context, datatable):
    assert _actual_ids(context) == _expected_ids(context, datatable)


@then("回答依據的檢索結果為底下照片")
def 回答依據的檢索結果為(context, datatable):
    assert _actual_ids(context) == _expected_ids(context, datatable)


@then("使用者獲得查無相關照片的回覆")
def 獲得查無回覆(context):
    body = context["response"].json()
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


@then("回答提及底下物品")
def 回答提及物品(context, datatable):
    answer = context["response"].json()["answer"]
    for row in _rows(datatable):
        assert row["name"] in answer, f"回答裡沒有提到「{row['name']}」：{answer}"
```

### 步驟 2：執行並逐條確認

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/test_ask_feature.py -v
```

---

## 驗收標準

1. **詢問規格 7 個例子全綠**
   ```bash
   pytest tests/test_ask_feature.py -v
   ```
   預期最後一行：`7 passed`
   預期看到 7 個測試名稱，正好對應規格的 7 個 Example（涵蓋全部 5 條 Rule）：
   - 條件過濾型問題走 metadata search
   - 語意描述型問題走 vector semantic search
   - 最近的照片以內容時間優先過濾、缺漏時用上傳時間
   - 模糊問題走 vector semantic search
   - 沒有任何照片時詢問
   - 詢問在 Target 拍的收據
   - 詢問最近買過的飲料

2. **兩份規格一起跑全綠**
   ```bash
   pytest tests/test_upload_feature.py tests/test_ask_feature.py -v
   ```
   預期最後一行：`14 passed`（上傳 7 ＋ 詢問 7）

3. **全部測試一起跑全綠**
   ```bash
   pytest -q
   ```
   預期：`38 passed`（**測試累計數：38**＝ Phase 11 的 31 ＋ 本 phase 的 7）

4. **時間過濾那條真的是靠 SQL 生效**（拿掉時間條件會看到不同結果）
   ```bash
   pytest tests/test_ask_feature.py -k "最近的照片" -v
   ```
   預期：`1 passed`。若你暫時把 `app/repositories/photo_repository.py` 裡 **`search_by_vector`** 的 `COALESCE(...)` 時間條件（`if recent:` 底下那段）註解掉再跑，這條應該要**失敗**——確認它真的在守規則，而不是碰巧通過。（這個例子走語意查詢，所以要註解的是 `search_by_vector` 那一處，不是 `search_by_metadata`。測完記得改回來。）

5. **完全不需要 Ollama**
   ```bash
   brew services stop ollama && pytest -q && brew services start ollama
   ```
   預期：`38 passed`

6. **規格檔沒有被動過**
   ```bash
   grep -c "Rule:" docs/spec/features/自然語言詢問.feature
   ```
   預期輸出：`5`

---

## 常見問題

**Q1：`KeyError: '1'`（找不到規格 id 對應的實際 id）。**
`Given 系統中有底下照片` 沒有執行到，或表格欄位名不是 `id`。確認步驟字串一字不差，並確認 `context` fixture 在同一個測試裡被共用（pytest 的 fixture 在單一測試內只會建立一次）。

**Q2：`回答提及底下物品` 過不了，回答裡沒有「可樂」。**
檢查 `FakeAnswerLLM` 是不是有把每張照片的 `items` 放進回答（Phase 11 的版本有）。也檢查該筆照片是不是被時間過濾掉了——用 `-v` 加上 `--pdb`，或在步驟裡印出 `retrieved_photo_ids` 觀察。另外注意：規格例子是中文問題，`FakeAnswerLLM` 會走中文分支（「依照片內容回答：…（物品：可樂、洋芋片）」），物品名稱在裡面。

**Q3：`時間過濾後的照片為底下照片` 得到三筆而不是兩筆。**
代表 `recent` 沒有傳到 SQL。檢查 `FakeRouter` 對「我最近買過什麼飲料？」是不是回 `recent=True`，以及 `route_node` 有沒有把 `decision.recent` 放進 `QueryFilters`。

**Q4：`使用者詢問` 步驟拿到 422。**
`AskRequest.question` 有 `min_length=1`，空字串會被擋。規格的問題都不是空的，若出現 422 多半是 JSON 鍵打錯（必須是 `question`）。

**Q5：測試順序不同時結果不一樣。**
`conftest.py` 的 `clean_database` 是 `autouse=True`，每個測試前都會 `TRUNCATE ... RESTART IDENTITY`，所以每個測試都從空資料庫開始。若仍不穩定，檢查是不是有測試自己開了連線卻沒關閉。

**Q6：要不要把英文提問的例子也加進 `.feature` 檔，讓驗收更完整？**
**不可以。** `docs/spec/` 是唯讀的，design.md §11 明訂「雙語行為以額外單元測試＋煙霧測試覆蓋，不改規格檔」。英文行為已經有 `tests/test_indexing.py`、`tests/test_upload_bilingual.py`、`tests/test_retrieval.py`、`tests/test_workflow_route.py`、`tests/test_ask_endpoint.py` 五個檔案共 **6 個測試**在守（就是本文件最後說的「6 個額外測試」那一批）。

---

## 完成後的專案狀態

第二個驗收里程碑達成：`自然語言詢問.feature` 的 5 條 Rule（Q1〜Q5）全部由自動化測試把關並通過。至此 **12 條 Rule 全數綠燈**，兩個 API 的規格行為都已完成，雙語行為也有 6 個額外測試守著。測試累計 **38** 個。
