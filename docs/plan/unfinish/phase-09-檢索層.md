# Phase 9：檢索服務 retrieval_service.py（兩條查詢＋30 天過濾＋ILIKE 雙語比對）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 做出「怎麼把照片找出來」這一層：條件查詢（SQL 過濾欄位、用 `ILIKE` 大小寫不敏感比對）與語意查詢（向量相似度），兩邊都支援「最近 30 天」的時間過濾。

---

## 前置條件

- 需要已完成的 phase：**Phase 3**（`photo_repository`）、**Phase 6**（`indexing_service.build_document`）、**Phase 8**（真實向量維度已確認）。
- 環境：測試資料庫可用；本 phase 的測試**不需要 Ollama**（用 `FakeEmbeddings`）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

「詢問」功能拆成三塊：判斷要用哪種查法（Phase 10）、把照片撈出來（**本 phase**）、依撈到的內容回答（Phase 11）。

兩種查法的差別很直觀：
- **條件查詢**：問題帶明確條件（地點=Target、類別=收據），就直接下 SQL 精確過濾。
- **語意查詢**：問題是描述性的（「我最近買過什麼飲料？」），就把問題也轉成向量，找向量最接近的 5 張。

還有一條兩邊共用的規則（已釐清，不可更動）：問題含「最近」時，只看**詢問當下回推 30 天**內的照片；判斷依據**優先用照片的內容時間，內容時間空的才用上傳時間**。這句話落地成一句 SQL：`COALESCE(content_time, uploaded_at::date) >= 今天 - 30 天`。

**雙語在這裡的落地點是 `ILIKE`**（design.md §9、§8.3）：條件查詢一律用 `ILIKE` 而不是 `=`，這樣 `target` 也找得到存成 `Target` 的資料；物品比對則用 `EXISTS (SELECT 1 FROM unnest(items) AS i WHERE i ILIKE …)`，讓陣列裡的每個元素也享有同樣的待遇。

> ⚠️ **刻意不做的事**：條件查詢**不做跨語言翻譯對映**。問 `"receipts"` 不會自動對到存成「收據」的類別——這是 design.md §8.3 明訂的**已知限制**。做翻譯對映屬過度設計；而且跨語言的問題自然會被 router 判給語意查詢（Phase 10），那條路本來就跨語言。

另外，design.md 做了一個重要決定（§9 的 **DD-4**）：**不使用 LangChain 內建的 PGVector 向量資料庫元件**，因為它自帶的表結構與我們固定四欄位的 schema 直接衝突。取而代之，用 LangChain 官方文件示範的 **`@chain` 自訂 retriever**——一個回傳 `list[Document]` 的函式。

**分層提醒**：SQL 一律寫在 `repositories/photo_repository.py`；`services/retrieval_service.py` 只決定「用哪一條查詢、帶什麼條件」，並把資料庫的一列列資料組裝成 `Document`。

**名詞**：
- **retriever（檢索器）**＝「給我問題，我還你一堆相關文件」的元件，是 RAG 的檢索半邊。
- **`ILIKE`**＝SQL 的「不分大小寫的字串比對」。不帶萬用字元時，效果等於「不分大小寫的等於」。
- **`unnest(items)`**＝把 PostgreSQL 陣列攤平成一列一個元素，方便逐一比對。
- **`EXISTS (子查詢)`**＝SQL 的「括號裡的查詢查得到至少一列就成立」。搭配 `unnest` 用：陣列攤平後只要有任何一個元素通過 `ILIKE` 比對，整個條件就成立。
- **cosine 距離**＝比較兩個向量方向差多少的算法；pgvector 用 `<=>` 這個符號表示，數字越小越像。
- **`@chain`**＝LangChain 的裝飾器（decorator，寫在函式上一行、幫函式加上額外能力的語法），把一個普通 Python 函式變成可以串接的 LangChain 元件。
- **`COALESCE(a, b)`**＝SQL 的「取第一個有值的」：`a` 不是空值（NULL）就用 `a`，是空值才改用 `b`。「內容時間優先、空的才用上傳時間」就是靠它一句話做到。
- **dataclass**＝Python 內建的 `@dataclass` 裝飾器，自動幫「純粹裝資料的類別」產生初始化等樣板程式碼；本 phase 用它定義過濾條件 `QueryFilters`。

---

## ASCII 圖：檢索層的兩條路

```
      request = {question, mode, filters, today, embeddings}
                            │
              ┌─────────────┴──────────────┐
              │ services/retrieval_service │  ★本 phase（@chain 自訂 retriever）
              │        photo_retriever     │
              └─────────────┬──────────────┘
    mode="metadata"         │         mode="vector"
              ▼                        ▼
 ┌───────────────────────────┐  ┌────────────────────────────────┐
 │ 條件查詢                   │  │ 語意查詢                        │
 │ photo_repository           │  │ 問題 → embeddings.embed_query   │
 │   .search_by_metadata      │  │ photo_repository                │
 │ WHERE category ILIKE …     │  │   .search_by_vector             │
 │   AND location ILIKE …     │  │ ORDER BY embedding <=> 問題向量  │
 │   AND EXISTS(unnest ILIKE) │  │ LIMIT 5                         │
 │  ★ ILIKE：target 命中 Target│  │  ★ bge-m3 多語：英文問題也能召回 │
 └───────────┬───────────────┘  └───────────────┬────────────────┘
             │      兩邊都可加上時間過濾           │
             │  AND COALESCE(content_time, uploaded_at::date)
             │        >= 今天 - 30 天
             └───────────────┬───────────────────┘
                             ▼
                  list[Document]（每份帶 id 與四欄位）
```

---

## 逐步驟操作

### 步驟 1：在 `app/repositories/photo_repository.py` 加上兩個查詢函式

先把檔案最上方既有的這一行 import：

```python
from datetime import date, datetime
```

改成（多了 `timedelta`，等一下算「今天 − 30 天」要用）：

```python
from datetime import date, datetime, timedelta
```

再補上 config 的 import（`RECENT_DAYS`、`TOP_K` 要用）：

```python
from app.core import config
```

然後把下面兩個函式接在檔案既有內容後面：

```python
def search_by_metadata(
    *,
    category: str | None,
    location: str | None,
    item: str | None,
    recent: bool,
    today: date,
) -> list[dict[str, Any]]:
    """條件查詢：把 route 抽出來的條件全部用 AND 串起來。

    沒有給的條件就不加進 WHERE；一個條件都沒有就等於查全部。

    比對一律用 ILIKE（不分大小寫），所以 'target' 找得到 'Target'——
    這是雙語支援的一部分（design.md §9）。ILIKE 不帶萬用字元時，
    效果就是「不分大小寫的等於」，不會變成模糊比對。
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if category:
        conditions.append("category ILIKE %(category)s")
        params["category"] = category
    if location:
        conditions.append("location ILIKE %(location)s")
        params["location"] = location
    if item:
        # items 是陣列：unnest 把它攤成一列一個元素，逐一做 ILIKE 比對
        conditions.append(
            "EXISTS (SELECT 1 FROM unnest(items) AS i WHERE i ILIKE %(item)s)"
        )
        params["item"] = item
    if recent:
        conditions.append(
            "COALESCE(content_time, uploaded_at::date) >= %(since)s"
        )
        params["since"] = today - timedelta(days=config.RECENT_DAYS)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {PHOTO_COLUMNS} FROM photo {where} ORDER BY id;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def search_by_vector(
    *,
    embedding: list[float],
    recent: bool,
    today: date,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """語意查詢：找向量最接近問題的幾張照片。

    <=> 是 pgvector 的 cosine 距離運算子，數字越小代表意思越接近。
    因為向量是多語模型產生的，英文問題也可能撈到中文內容的照片。
    """
    params: dict[str, Any] = {
        "qvec": to_vector_literal(embedding),
        "limit": limit or config.TOP_K,
    }
    conditions: list[str] = []
    if recent:
        conditions.append(
            "COALESCE(content_time, uploaded_at::date) >= %(since)s"
        )
        params["since"] = today - timedelta(days=config.RECENT_DAYS)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT {PHOTO_COLUMNS}
        FROM photo
        {where}
        ORDER BY embedding <=> %(qvec)s::vector
        LIMIT %(limit)s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
```

### 步驟 2：寫 `app/services/retrieval_service.py`

```python
"""檢索服務：條件查詢與語意查詢，兩者都可套用 30 天時間過濾。

SQL 一律寫在 repositories/photo_repository.py，這裡只負責決定
「用哪一條、帶什麼條件」，並把資料庫的一列列資料組裝成 LangChain 的 Document。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import chain

from app.core import config
from app.repositories import photo_repository
from app.services import indexing_service


@dataclass
class QueryFilters:
    """從問題抽出來的過濾條件，四個都可以是空的。

    值是 route 從問題裡抽出來的原文（中文問題抽中文、英文問題抽英文），
    比對交給 SQL 的 ILIKE；系統不做跨語言翻譯（design.md §8.3 的已知限制）。
    """

    category: str | None = None
    location: str | None = None
    item: str | None = None
    recent: bool = False   # 問題是否含「最近／recently」這類時間條件


def row_to_document(row: dict[str, Any]) -> Document:
    """把資料庫的一列照片組成 Document（內容格式與寫入時完全一致）。"""
    content_time = row["content_time"].isoformat() if row["content_time"] else None
    document = indexing_service.build_document(
        text=row["text"],
        category=row["category"],
        location=row["location"],
        items=list(row["items"]),
        content_time=content_time,
    )
    document.metadata["id"] = row["id"]
    return document


def metadata_search(filters: QueryFilters, today: date) -> list[Document]:
    """條件查詢：用固定欄位過濾（ILIKE，不分大小寫）。"""
    rows = photo_repository.search_by_metadata(
        category=filters.category,
        location=filters.location,
        item=filters.item,
        recent=filters.recent,
        today=today,
    )
    return [row_to_document(row) for row in rows]


def vector_search(
    question: str,
    embeddings: Embeddings,
    filters: QueryFilters,
    today: date,
) -> list[Document]:
    """語意查詢：問題轉成向量，找最接近的 TOP_K 張。"""
    question_vector = embeddings.embed_query(question)
    rows = photo_repository.search_by_vector(
        embedding=question_vector,
        recent=filters.recent,
        today=today,
        limit=config.TOP_K,
    )
    return [row_to_document(row) for row in rows]


@chain
def photo_retriever(request: dict[str, Any]) -> list[Document]:
    """自訂 retriever（LangChain 官方示範的 @chain 寫法）。

    request 需要五個鍵：
      question   : 使用者的問題（中文或英文）
      mode       : "metadata" 或 "vector"
      filters    : QueryFilters
      today      : 詢問當下的日期
      embeddings : 產生向量的元件（正式是 Ollama，測試是假件）
    """
    filters: QueryFilters = request["filters"]
    today: date = request["today"]

    if request["mode"] == "metadata":
        return metadata_search(filters, today)
    return vector_search(request["question"], request["embeddings"], filters, today)
```

### 步驟 3：建立 `tests/test_retrieval.py`

這裡把規格「時間過濾」那條 Rule 的資料原封不動搬進來，加上 30 天邊界測試，確認**條件查詢與語意查詢共用同一條時間過濾**，並補兩個 ILIKE 的雙語測試。

```python
"""檢索層測試：兩條查詢 ＋ 30 天時間過濾（含邊界）＋ ILIKE 大小寫不敏感。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.repositories import photo_repository
from app.services.retrieval_service import (
    QueryFilters,
    metadata_search,
    photo_retriever,
    vector_search,
)
from tests.fakes import FakeEmbeddings

NOW = datetime(2026, 8, 18, 10, 0)
TODAY = NOW.date()


def _insert(text, category, location, items, content_time, uploaded_at):
    return photo_repository.insert_photo(
        text=text,
        category=category,
        location=location,
        items=items,
        content_time=content_time,
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=uploaded_at,
    )["id"]


@pytest.fixture
def 三張規格照片():
    """完全照 自然語言詢問.feature 的資料表建立。"""
    id1 = _insert("在 Target 購買可樂的收據", "收據", "Target", ["可樂"],
                  date(2026, 8, 10), datetime(2026, 8, 18, 10, 0))
    id2 = _insert("在 Costco 購買牛奶的收據", "收據", "Costco", ["牛奶"],
                  date(2026, 5, 1), datetime(2026, 8, 17, 9, 0))
    id3 = _insert("在 7-11 購買咖啡的收據", "收據", "7-11", ["咖啡"],
                  None, datetime(2026, 8, 15, 12, 0))
    return id1, id2, id3


@pytest.fixture
def 一張英文收據():
    """欄位值是英文、而且是大寫開頭——用來驗 ILIKE 的大小寫不敏感。"""
    return _insert("Receipt from Target with Cola and Chips", "Receipt", "Target",
                   ["Cola", "Chips"], date(2026, 8, 10), datetime(2026, 8, 18, 10, 0))


def _ids(documents):
    return sorted(doc.metadata["id"] for doc in documents)


def test_時間過濾以內容時間優先缺漏時用上傳時間(三張規格照片):
    id1, id2, id3 = 三張規格照片

    documents = vector_search(
        "我最近買過什麼飲料？", FakeEmbeddings(),
        QueryFilters(recent=True), TODAY,
    )

    # 1 號的內容時間 2026-08-10 在 30 天內 → 保留
    # 2 號的內容時間 2026-05-01 超過 30 天——雖然它的上傳時間 2026-08-17
    #   就在昨天，仍以內容時間為準 → 被排除
    # 3 號沒有內容時間，改看上傳時間 2026-08-15（在 30 天內）→ 保留
    assert _ids(documents) == sorted([id1, id3])

    # 條件查詢也套用同一條時間過濾（兩路共用），結果必須一致
    metadata_documents = metadata_search(
        QueryFilters(category="收據", recent=True), TODAY
    )
    assert _ids(metadata_documents) == sorted([id1, id3])


def test_沒有時間條件時不做時間過濾(三張規格照片):
    id1, id2, id3 = 三張規格照片

    documents = vector_search(
        "買過什麼？", FakeEmbeddings(), QueryFilters(recent=False), TODAY
    )

    assert _ids(documents) == sorted([id1, id2, id3])


# parametrize＝讓同一個測試函式帶多組參數各跑一次（這裡是 29／30／31 天三組），
# pytest 會把它算成 3 個測試
@pytest.mark.parametrize(
    "天數, 應該被找到",
    [(29, True), (30, True), (31, False)],
)
def test_三十天邊界(天數, 應該被找到):
    photo_id = _insert("在 Target 購買可樂的收據", "收據", "Target", ["可樂"],
                       TODAY - timedelta(days=天數), datetime(2026, 8, 18, 10, 0))

    documents = vector_search(
        "我最近買過什麼飲料？", FakeEmbeddings(), QueryFilters(recent=True), TODAY
    )

    assert (photo_id in _ids(documents)) is 應該被找到


def test_條件查詢用欄位過濾(三張規格照片):
    id1, _, _ = 三張規格照片

    documents = metadata_search(
        QueryFilters(category="收據", location="Target"), TODAY
    )

    assert _ids(documents) == [id1]


def test_條件查詢可以過濾物品(三張規格照片):
    _, id2, _ = 三張規格照片

    documents = metadata_search(QueryFilters(item="牛奶"), TODAY)

    assert _ids(documents) == [id2]


def test_地點比對不分大小寫(一張英文收據):
    """雙語：問題寫 target（小寫），也要找到存成 Target 的照片（ILIKE）。"""
    documents = metadata_search(QueryFilters(location="target"), TODAY)

    assert _ids(documents) == [一張英文收據]


def test_物品比對不分大小寫(一張英文收據):
    """雙語：陣列裡的元素也走 ILIKE（unnest + ILIKE）。"""
    documents = metadata_search(QueryFilters(item="cola"), TODAY)

    assert _ids(documents) == [一張英文收據]


def test_自訂retriever兩種模式都能用(三張規格照片):
    id1, _, _ = 三張規格照片

    metadata_result = photo_retriever.invoke({
        "question": "有哪些在 Target 拍的收據？",
        "mode": "metadata",
        "filters": QueryFilters(category="收據", location="Target"),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })
    vector_result = photo_retriever.invoke({
        "question": "我最近買過什麼飲料？",
        "mode": "vector",
        "filters": QueryFilters(recent=True),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })

    assert _ids(metadata_result) == [id1]
    assert len(vector_result) >= 1
    # 回傳的是 LangChain 的 Document，內容格式與寫入時一致
    assert vector_result[0].page_content.startswith("在 ")
```

---

## 驗收標準

1. **檢索層測試全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/test_retrieval.py -v
   ```
   預期最後一行：`10 passed`（8 個測試函式，其中邊界測試帶 3 組參數，pytest 算成 3 個）

2. **全部測試一起跑仍然全綠**
   ```bash
   pytest -q
   ```
   預期：`21 passed`（**測試累計數：21**＝ Phase 7 的 11 ＋ 本 phase 的 10）

3. **時間過濾的 SQL 真的是設計文件那句**
   ```bash
   grep -n "COALESCE(content_time, uploaded_at::date)" app/repositories/photo_repository.py
   ```
   預期：印出兩行（條件查詢與語意查詢各一處）。

4. **條件查詢真的用 ILIKE，而且沒有殘留 `=` 比對**
   ```bash
   grep -nE "ILIKE %\(" app/repositories/photo_repository.py
   grep -n "category = %" app/repositories/photo_repository.py || echo "OK：沒有用 = 做欄位比對"
   ```
   預期：第一個指令印出**三行 SQL**（category／location／unnest 各一；`ILIKE %(` 這個樣式只會命中真正的 SQL，不會命中註解裡提到的 ILIKE）；第二個指令印出 `OK：沒有用 = 做欄位比對`。

5. **SQL 依然只出現在 repository 一個檔案**
   ```bash
   grep -rlnE "SELECT |INSERT INTO|TRUNCATE TABLE" app/ --include="*.py"
   ```
   預期輸出**只有一行**：`app/repositories/photo_repository.py`
   （這裡刻意不把 `ILIKE` 放進搜尋字串——`retrieval_service.py` 的**註解**會提到它，但那不是 SQL。）

6. **手動確認 30 天邊界**
   ```bash
   python - <<'PY'
   from datetime import date, datetime, timedelta
   from app.core import config
   config.DATABASE_URL = "postgresql://localhost:5433/visual_memory_test"
   from app.repositories import photo_repository as repo
   from app.services.retrieval_service import QueryFilters, vector_search
   from tests.fakes import FakeEmbeddings

   today = date(2026, 8, 18)
   repo.clear_photos()
   for days in (30, 31):
       repo.insert_photo(text=f"{days} 天前的收據", category="收據", location="Target",
                         items=["可樂"], content_time=today - timedelta(days=days),
                         embedding=FakeEmbeddings().embed_query("收據"),
                         uploaded_at=datetime(2026, 8, 18, 10, 0))
   found = vector_search("最近的飲料", FakeEmbeddings(), QueryFilters(recent=True), today)
   print("找到：", [d.page_content.splitlines()[0] for d in found])
   PY
   ```
   預期輸出：`找到： ['30 天前的收據']`（31 天前那張被排除）

7. **手動確認 ILIKE 的雙語效果**
   ```bash
   python - <<'PY'
   from datetime import date, datetime
   from app.core import config
   config.DATABASE_URL = "postgresql://localhost:5433/visual_memory_test"
   from app.repositories import photo_repository as repo
   from app.services.retrieval_service import QueryFilters, metadata_search
   from tests.fakes import FakeEmbeddings

   repo.clear_photos()
   repo.insert_photo(text="Receipt from Target with Cola", category="Receipt",
                     location="Target", items=["Cola"], content_time=date(2026, 8, 10),
                     embedding=FakeEmbeddings().embed_query("Receipt"),
                     uploaded_at=datetime(2026, 8, 18, 10, 0))
   today = date(2026, 8, 18)
   print("location='target' →", len(metadata_search(QueryFilters(location="target"), today)))
   print("location='TARGET' →", len(metadata_search(QueryFilters(location="TARGET"), today)))
   print("item='cola'       →", len(metadata_search(QueryFilters(item="cola"), today)))
   print("category='收據'   →", len(metadata_search(QueryFilters(category="收據"), today)))
   PY
   ```
   預期輸出：
   ```
   location='target' → 1
   location='TARGET' → 1
   item='cola'       → 1
   category='收據'   → 0
   ```
   最後那行 `0` **是正確的**——這正是 design.md §8.3 的已知限制：不做跨語言翻譯對映，中文的「收據」對不到存成 `Receipt` 的資料。這種問題會由 route 判給語意查詢處理。

---

## 常見問題

**Q1：語意查詢報錯 `operator does not exist: vector <=> unknown`。**
問題向量沒有轉成 `vector` 型別。SQL 裡要寫 `%(qvec)s::vector`（步驟 1 的程式碼已經是），參數則要用 `to_vector_literal()` 轉成 `[0.1,0.2,…]` 這種字串。

**Q2：語意查詢的排序結果每次不一樣。**
若有多筆距離完全相同，PostgreSQL 不保證順序。測試斷言請用「集合比較」（像範例的 `sorted(...)`），不要依賴特定順序。

**Q3：時間過濾把不該排除的照片排除了。**
檢查 `today` 傳的是不是「詢問當下的日期」。`RECENT_DAYS` 固定 30（已釐清的決策），不要在別處另外寫死天數。

**Q4：`ILIKE` 會不會變成模糊比對，讓 `item="樂"` 也找到「可樂」？**
不會。ILIKE 只有在值裡出現萬用字元 `%`（任意多字）或 `_`（任意一字）時才會模糊比對；我們傳進去的是使用者問題裡抽出來的完整詞，沒有萬用字元，所以效果就是「不分大小寫的等於」。`item="樂"` 找不到「可樂」，這是正確行為。

**Q5：那如果使用者問題裡真的有 `%` 呢？**
那筆查詢就查不到東西（或多查到一些）。這是 side project 可以接受的邊界情況，design.md 沒有要求處理——**不要**為此加逸出（escape）邏輯。

**Q6：可不可以加一個「英文 → 中文」的欄位對照表，讓 `receipts` 對到「收據」？**
**不可以。** design.md §8.3 明列這是「已知限制（刻意不解）」，做翻譯對映屬過度設計。跨語言的問題交給語意查詢那條路。

**Q7：可不可以改用 LangChain 的 PGVector 向量資料庫元件？**
不行。design.md 的 DD-4 明訂不用，因為它自帶 UUID 主鍵＋JSONB metadata 的表結構，和我們固定四欄位的 schema 衝突，硬用會變成兩張表雙寫。

---

## 完成後的專案狀態

系統已經「找得到照片」：條件查詢能用類別／地點／物品過濾（`ILIKE`，大小寫不敏感，支援英文值），語意查詢能用向量找出最接近的 5 張，兩邊都正確套用「最近＝30 天、內容時間優先」的規則（規則 Q2 已成立）。但還沒有東西決定要走哪一條路，也還沒有人負責回答。測試累計 **21** 個。
