# Phase 3：資料庫 schema、db/session.py 與 photo_repository.py

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 建出唯一一張資料表 `photo`（含 pgvector 的向量欄位與 HNSW 索引），寫好 `app/db/session.py`（連線）與 `app/repositories/photo_repository.py`——**全系統唯一寫 SQL 的模組**。

---

## 前置條件

- 需要已完成的 phase：**Phase 1**（PostgreSQL＋pgvector 已安裝、兩個資料庫已建立）、**Phase 2**（`app/core/config.py` 已可讀取 `DATABASE_URL`、`EMBEDDING_DIM`）。
- ✅ **2026-08-19 已實測確認**：PG17@5433 執行中、`visual_memory`／`visual_memory_test` 皆存在且 pgvector 0.8.6 已啟用、venv 套件齊全（psycopg 3.3.4、pytest 9.1.1、httpx 0.28.1、python-multipart）——前置條件全數成立；四個目標檔（`db/schema.sql`、`db/session.py`、`photo_repository.py`）目前為空檔，正是本 phase 要填的。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

整個系統只有一張資料表：`photo`。一張照片＝一列資料，欄位有自動編號的 id、文字描述、四個 metadata 欄位、上傳時間、以及一個 1024 維的向量——共 8 欄。

分層架構把「碰資料庫」這件事切成兩個檔案：

- **`app/db/session.py`**：只負責「怎麼開一條連線」。全專案只有這一個地方呼叫 `psycopg.connect()`。
- **`app/repositories/photo_repository.py`**：**全系統唯一寫 SQL 的地方**（design.md §4.2 的硬規則）。其他模組要存取資料，一律呼叫這裡提供的函式。

這樣做的好處是資料存取集中一處，測試好替換、schema 好演進；而把連線獨立出來，是因為它跟「查什麼」無關，混在一起會讓 repository 檔案變雜。

這一步把五個基本操作做出來：寫入（`insert_photo`）、讀出單筆（`fetch_photo`）、取回向量（`fetch_embedding`）、計數（`count_photos`）、清空（`clear_photos`）。後面 Phase 6 的上傳流程用「寫入」，Phase 7 的驗收測試用其餘四個；兩條檢索查詢（`search_by_metadata`／`search_by_vector`）則留到 Phase 9 再加進同一個檔案。

> 🔄 **2026-08-19 更新（dev-prompt `phase0819.md`）：本 phase 改採 TDD＋BDD**——pytest 測試從本 phase 就開始建（原規劃自 Phase 5 起），**先寫測試（步驟 0）看它失敗，再照步驟 1〜4 實作讓它轉綠**。測試分兩層：`tests/unit/`（純函式，不碰資料庫）與 `tests/integration/`（連 `visual_memory_test` 真測試庫）；整合測試以 Given/When/Then 結構對應 `docs/spec/features/上傳照片.feature` 中本階段可落地的資料層行為（U5 上傳時間、U4 embedding 不為空等）。完整 feature 檔驗收（pytest-bdd＋假件）仍照原規劃在 Phase 7，不提前。

---

## ASCII 圖：資料流與 photo 資料表

```
 routers / services（誰都不准自己寫 SQL）
        │  只呼叫函式
        ▼
 ┌──────────────────────────────────────────────────┐
 │ app/repositories/photo_repository.py             │
 │   ★ 全系統唯一寫 SQL 的模組                       │
 │   insert_photo(...)   → 一條 INSERT               │
 │   fetch_photo(id)     → SELECT 單筆               │
 │   fetch_embedding(id) → SELECT 向量               │
 │   count_photos()      → SELECT count(*)           │
 │   clear_photos()      → TRUNCATE（測試用）        │
 │   （P09 再加 search_by_metadata / search_by_vector）│
 └──────────────────────┬───────────────────────────┘
                        │ get_connection()
                        ▼
 ┌──────────────────────────────────────────────────┐
 │ app/db/session.py    psycopg 3（同步）連線         │
 └──────────────────────┬───────────────────────────┘
                        ▼
 ┌──────────────────────────────────────────────────┐
 │ PostgreSQL + pgvector                            │
 │                                                  │
 │  photo                                           │
 │  ├ id           整數，自動編號，主鍵               │
 │  ├ text         VLM 的文字描述（必填）             │
 │  ├ category     類別，可空                        │
 │  ├ location     地點／商家，可空                   │
 │  ├ items        物品清單（陣列）                   │
 │  ├ content_time 內容時間（日期），可空             │
 │  ├ uploaded_at  上傳時間，DB 自動記                │
 │  └ embedding    vector(1024)，必填                │
 │                                                  │
 │  索引：photo_embedding_idx (HNSW, cosine)         │
 └──────────────────────────────────────────────────┘
```

---

## 逐步驟操作

### 步驟 0：先寫測試（TDD red）——2026-08-19 增補

先建測試目錄結構（`tests/` 與其子目錄都是 Python 套件，各放一個空的 `__init__.py`）：

```bash
mkdir -p tests/unit tests/integration
touch tests/unit/__init__.py tests/integration/__init__.py
```

**檔案 1：`tests/conftest.py`**——把資料庫指到測試庫、每個測試前清空 `photo` 表（design.md §11「每測清空」）：

```python
"""pytest 共用設定：把資料庫指到測試庫，並在每個測試前清空 photo 表。"""

import os

# 一定要在 import app.* 之前設定：app/core/config.py 在 import 時讀環境變數，
# 而 load_dotenv() 不會覆蓋已存在的環境變數，所以這裡先寫入的測試庫 URL 會生效。
TEST_DATABASE_URL = "postgresql://localhost:5433/visual_memory_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402  （import 順序刻意如此，見上方註解）

from app.core import config  # noqa: E402

# 雙保險：即使 config 已被其他途徑先 import，也強制指向測試庫
config.DATABASE_URL = TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def clean_photo_table():
    """每個測試開始前清空 photo 表，確保測試彼此獨立。"""
    # 絕不清到正式庫：URL 必須含 visual_memory_test 才動手
    assert "visual_memory_test" in config.DATABASE_URL
    from app.repositories import photo_repository as repo

    repo.clear_photos()
    yield
```

**檔案 2：`tests/unit/test_photo_repository_unit.py`**——純函式單元測試，不碰資料庫：

```python
"""to_vector_literal 的單元測試：純函式，不碰資料庫。"""

from app.repositories.photo_repository import to_vector_literal


def test_to_vector_literal_formats_floats():
    assert to_vector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


def test_to_vector_literal_accepts_ints():
    assert to_vector_literal([1, 2]) == "[1.0,2.0]"
```

**檔案 3：`tests/integration/test_photo_repository.py`**——連 `visual_memory_test` 真資料庫的整合測試（10 個）：

```python
"""photo_repository 的整合測試：連 visual_memory_test 真測試庫。

BDD 對應（docs/spec/features/上傳照片.feature，本階段可落地的資料層行為）：
- U2/U3：文字與四欄位寫入後可原樣讀回（中英文皆可）
- U4：寫入後 embedding 不為空
- U5：不指定上傳時間時由資料庫自動記錄；測試也可注入固定時間
每個測試依 tests/conftest.py 的 autouse fixture 在乾淨的 photo 表上執行。
"""

from datetime import date, datetime, timezone

from app.core import config
from app.repositories import photo_repository as repo


def _vec(value: float = 0.01) -> list[float]:
    return [value] * config.EMBEDDING_DIM


def _insert_sample(**overrides):
    """Given：一筆標準中文收據資料（可用 overrides 覆寫任一欄位）。"""
    params = dict(
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time=date(2026, 8, 10),
        embedding=_vec(),
    )
    params.update(overrides)
    return repo.insert_photo(**params)


def test_insert_photo_returns_full_row():
    # When 寫入中文收據 Then 回傳列含 id 與全部欄位（U2/U3 資料層）
    row = _insert_sample()
    assert row["id"] == 1
    assert row["text"] == "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
    assert row["category"] == "收據"
    assert row["location"] == "Target"
    assert row["items"] == ["可樂", "洋芋片"]
    assert row["content_time"] == date(2026, 8, 10)


def test_insert_photo_english_row():
    # 雙語資料層基礎：英文內容原樣寫入與讀回
    row = _insert_sample(
        text="Receipt from Target with Cola and Chips, dated 2026-08-10",
        category="Receipt",
        items=["Cola", "Chips"],
    )
    assert row["category"] == "Receipt"
    assert row["items"] == ["Cola", "Chips"]


def test_insert_photo_nullable_fields_can_be_empty():
    # 風景照可能沒有類別/商家/內容時間（design.md §7 允許空）
    row = _insert_sample(category=None, location=None, items=[], content_time=None)
    assert row["category"] is None
    assert row["location"] is None
    assert row["items"] == []
    assert row["content_time"] is None


def test_uploaded_at_recorded_by_db_when_not_given():
    # U5：不傳 uploaded_at 時由資料庫 now() 自動記錄
    row = _insert_sample()
    assert row["uploaded_at"] is not None


def test_uploaded_at_uses_given_value_when_provided():
    # 「現在時間為 …」的時鐘注入點：測試可指定固定上傳時間
    fixed = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    row = _insert_sample(uploaded_at=fixed)
    assert row["uploaded_at"] == fixed


def test_fetch_photo_returns_row():
    inserted = _insert_sample()
    assert repo.fetch_photo(inserted["id"]) == inserted


def test_fetch_photo_returns_none_when_missing():
    assert repo.fetch_photo(999) is None


def test_fetch_embedding_not_empty():
    # U4 資料層：寫入後 embedding 不為空
    row = _insert_sample()
    emb = repo.fetch_embedding(row["id"])
    assert emb is not None and emb.startswith("[")


def test_fetch_embedding_none_when_missing():
    assert repo.fetch_embedding(999) is None


def test_count_and_clear_photos():
    assert repo.count_photos() == 0
    _insert_sample()
    _insert_sample()
    assert repo.count_photos() == 2
    repo.clear_photos()
    assert repo.count_photos() == 0
    assert _insert_sample()["id"] == 1  # RESTART IDENTITY：id 重新從 1 起編
```

**看它失敗（red）**：

```bash
python -m pytest tests -q
```

預期**全部失敗／collection error**：`photo_repository.py` 還是空檔，`ImportError`／`AttributeError` 就是「功能還不存在」的正確紅燈。接著照步驟 1〜4 實作，把紅燈轉綠。

### 步驟 1：寫 `db/schema.sql`

「DDL」＝Data Definition Language，就是「建表用的 SQL」。把下面整段內容存進**專案根目錄底下的** `db/schema.sql`（Phase 2 已建立這個空檔，貼上覆蓋即可）。資料表與索引的定義與 design.md §7 完全一致，只多加一行 `DROP TABLE IF EXISTS photo;`，讓這份 SQL 可以重複執行（Phase 8 若實測維度不同要重建資料表，就是重跑這份檔案）。

```sql
-- 啟用 pgvector 擴充套件（讓資料庫多出 vector 型別）
CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS photo;

CREATE TABLE photo (
  id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text         text        NOT NULL,               -- VLM 的文字描述（失敗就不存，所以不會空）
  category     text,                               -- 類別（如：收據 / Receipt），可空
  location     text,                               -- 地點/商家（如：Target），可空
  items        text[]      NOT NULL DEFAULT '{}',  -- 物品清單（多值）
  content_time date,                               -- 內容時間（如收據日期），可空
  uploaded_at  timestamptz NOT NULL DEFAULT now(), -- 上傳時間，DB 自動記
  embedding    vector(1024) NOT NULL               -- 文字＋欄位合併內容的向量
);

-- 向量索引：HNSW ＋ cosine 距離（pgvector 官方語法）。
-- 索引＝資料庫的「目錄」，查資料不用整張表逐列掃描；
-- HNSW＝專門加速「找最相近向量」的索引演算法；
-- cosine（餘弦）距離＝比較兩個向量的方向有多接近，越接近代表意思越像。
-- 只建這一個索引；demo 資料量用循序掃描就夠，不養用不到的索引
CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);
```

> `vector(1024)` 的 1024 是**假設值**，Phase 8 會用真的 `bge-m3` 實測。若實測不是 1024，改 `config.EMBEDDING_DIM` 與這裡的數字，再重跑一次建表即可。

> 💡 `category`／`location` 存的是**照片本身語言的值**（中文收據存「收據」、英文收據存 `Receipt`）。查詢時靠 `ILIKE` 做大小寫不敏感比對（Phase 9），資料庫層不做任何語言轉換。

### 步驟 2：把資料表建到兩個資料庫

```bash
cd /Users/linjunting/personalDocAI

psql -d visual_memory      -f db/schema.sql
psql -d visual_memory_test -f db/schema.sql
```

（再提醒一次：`psql` 一定要帶 `-d 資料庫名稱`。）

### 步驟 3：寫 `app/db/session.py`

它用 **psycopg 3**（Phase 1 裝好的「Python 連 PostgreSQL」套件）以**同步**方式執行 SQL——「同步」＝送出查詢後等資料庫回覆才繼續往下走，不用 async，符合 design.md §4.3「上傳全程同步」的決策。

```python
"""資料庫連線。全專案唯一呼叫 psycopg.connect() 的地方。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.core import config


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """開一條資料庫連線，用完自動關閉並 commit。

    - `@contextmanager` ＝讓這個函式可以用 `with ... as conn:` 的寫法，
      區塊結束時自動收尾。
    - `row_factory=dict_row` 讓查詢結果變成字典（欄位名 → 值），比較好讀。
    - 每次呼叫都重新讀 `config.DATABASE_URL`，測試才能把它指到測試資料庫。
    """
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn
```

### 步驟 4：寫 `app/repositories/photo_repository.py`

```python
"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
（Phase 9 會在這個檔案加上兩條檢索查詢。）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.db.session import get_connection

# 每次查詢都取回的欄位，固定順序，避免各處寫法不一致
PHOTO_COLUMNS = "id, text, category, location, items, content_time, uploaded_at"


def to_vector_literal(embedding: list[float]) -> str:
    """把 Python 的數字清單轉成 pgvector 認得的字串，例如 '[0.1,0.2,0.3]'。"""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def insert_photo(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: date | None,
    embedding: list[float],
    uploaded_at: datetime | None = None,
) -> dict[str, Any]:
    """寫入一張照片。一條 INSERT 寫完全部欄位，天然原子——不會存到一半。

    uploaded_at 傳 None（正式情況）時，由資料庫的 now() 自動記錄上傳時間；
    測試需要固定時間時才會傳入指定值。這靠下面 SQL 的 COALESCE 做到——
    COALESCE(a, b)＝a 有值就用 a、a 是空的（NULL）才改用 b。
    """
    # 欄位「名稱」清單用 f-string 帶入（固定常數）；欄位「值」一律用 %(名稱)s
    # 參數帶入，交給 psycopg 安全處理——避免 SQL injection（輸入內容被誤當 SQL 執行）
    sql = f"""
        INSERT INTO photo (text, category, location, items, content_time, uploaded_at, embedding)
        VALUES (
            %(text)s, %(category)s, %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector
        )
        RETURNING {PHOTO_COLUMNS};
    """
    params = {
        "text": text,
        "category": category,
        "location": location,
        "items": items,
        "content_time": content_time,
        "uploaded_at": uploaded_at,
        "embedding": to_vector_literal(embedding),
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetch_photo(photo_id: int) -> dict[str, Any] | None:
    """依 id 取回一張照片；找不到回 None。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PHOTO_COLUMNS} FROM photo WHERE id = %(id)s;",
                {"id": photo_id},
            )
            return cur.fetchone()


def fetch_embedding(photo_id: int) -> str | None:
    """取回某張照片的向量（字串形式），用來確認向量不為空。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding::text AS embedding FROM photo WHERE id = %(id)s;",
                {"id": photo_id},
            )
            row = cur.fetchone()
            return row["embedding"] if row else None


def count_photos() -> int:
    """目前存了幾張照片。驗收規則「系統儲存的照片數量為 0」會用到。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM photo;")
            return cur.fetchone()["n"]


def clear_photos() -> None:
    """清空資料表。只給測試用：每個測試開始前把 photo 表清乾淨。

    TRUNCATE＝一次清空整張表（比逐列 DELETE 快）；
    RESTART IDENTITY＝清空後 id 重新從 1 開始編。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE photo RESTART IDENTITY;")
```

### 步驟 5：手動試一次寫入與讀出（中文與英文各一筆）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

python - <<'PY'
from datetime import date
from app.core import config
from app.repositories import photo_repository as repo

repo.clear_photos()

中文那筆 = repo.insert_photo(
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time=date(2026, 8, 10),
    embedding=[0.01] * config.EMBEDDING_DIM,
)
英文那筆 = repo.insert_photo(
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time=date(2026, 8, 10),
    embedding=[0.02] * config.EMBEDDING_DIM,
)
print("中文那筆：", 中文那筆["id"], 中文那筆["items"])
print("英文那筆：", 英文那筆["id"], 英文那筆["items"])
print("照片數量：", repo.count_photos())
print("向量前 20 字：", repo.fetch_embedding(中文那筆["id"])[:20])
PY
```

（兩筆都寫得進去，就證明資料表對中英文內容一視同仁——這是雙語支援的資料層基礎。）

---

## 驗收標準

1. **資料表建立成功、欄位型別正確**
   ```bash
   psql -d visual_memory -c "\d photo"
   ```
   預期看到 8 個欄位，其中 `items` 型別是 `text[]`、`content_time` 是 `date`、`uploaded_at` 是 `timestamp with time zone`、`embedding` 是 `vector(1024)`，最下方有索引 `photo_embedding_idx ... hnsw`。

2. **測試資料庫也建好了**
   ```bash
   psql -d visual_memory_test -c "\d photo" | head -3
   ```
   預期看到 `Table "public.photo"`。

3. **步驟 5 的腳本可以跑完**，輸出類似：
   ```
   中文那筆： 1 ['可樂', '洋芋片']
   英文那筆： 2 ['Cola', 'Chips']
   照片數量： 2
   向量前 20 字： [0.01,0.01,0.01,0.01
   ```

4. **上傳時間真的由資料庫自動記**
   ```bash
   psql -d visual_memory -c "SELECT id, uploaded_at FROM photo;"
   ```
   預期兩列的 `uploaded_at` 都有值（就是你剛剛執行腳本的時間），而不是 `NULL`。

5. **SQL 真的只出現在 repository 一個檔案**
   ```bash
   grep -rlnE "SELECT |INSERT INTO|UPDATE |DELETE FROM|TRUNCATE TABLE" app/ --include="*.py"
   ```
   預期輸出**只有一行**：`app/repositories/photo_repository.py`
   （之後每個 phase 都可以重跑這一條——輸出永遠只能有這一行，這是 design.md §4.2 的硬規則。）

6. **清空可用**
   ```bash
   python -c "from app.repositories import photo_repository as repo; repo.clear_photos(); print(repo.count_photos())"
   ```
   預期輸出：`0`

7. **pytest 全綠（TDD green，2026-08-19 增補）**
   ```bash
   python -m pytest tests -q
   ```
   預期輸出：`12 passed`（`tests/unit` 2 個＋`tests/integration` 10 個；步驟 0 的紅燈全數轉綠）。

---

## 常見問題

**Q1：`psycopg.errors.UndefinedObject: type "vector" does not exist`。**
這個資料庫沒有啟用 pgvector。執行 `psql -d visual_memory -c "CREATE EXTENSION IF NOT EXISTS vector;"`（測試庫也要做一次），再重跑 `psql -d visual_memory -f db/schema.sql`。

**Q2：寫入時報 `expected 1024 dimensions, not N`。**
你給的向量長度和資料表宣告的 `vector(1024)` 不一致。向量長度必須永遠等於 `config.EMBEDDING_DIM`。Phase 8 實測真實維度後，要同步改 `config.EMBEDDING_DIM` 與 `db/schema.sql`，並重跑建表。

**Q3：`connection to server at "localhost" (::1), port 5433 failed`。**
PostgreSQL 沒在跑。執行 `brew services start postgresql@17`，等幾秒再試。

**Q4：`items` 寫進去變成字串而不是陣列。**
`items` 參數要傳 Python 的 `list[str]`（例如 `["可樂", "洋芋片"]`），psycopg 3 會自動對應到 PostgreSQL 的 `text[]`。不要自己先用 `"、".join(...)` 拼成字串。

**Q5：`ModuleNotFoundError: No module named 'app.db.session'`。**
`app/db/__init__.py` 沒建。分層架構每個資料夾都需要它（Phase 2 步驟 1 有做）。另外注意**專案根目錄的 `db/` 資料夾不是 Python 套件**，也不需要 `__init__.py`——它只放 `schema.sql`。

**Q6：要不要順便加 SQLAlchemy、alembic，或幫其他欄位建索引？**
**不要。** design.md §4.3 明訂手寫 SQL、不用 ORM 與 migration；§7 明訂「不建其他索引——demo 資料量 seq scan 就夠」。

---

## 完成後的專案狀態

資料庫已經有唯一一張 `photo` 表與向量索引；`db/session.py` 負責連線、`repositories/photo_repository.py` 能寫入、讀出（含向量）、計數、清空，而且 SQL 只出現在這一個檔案。系統已經「存得下照片資料」（中英文皆可），但還沒有任何 API 端點可以接收上傳。另外（2026-08-19 起）`tests/` 已有 TDD 基礎結構——`conftest.py`（指向測試庫＋每測清空）＋`tests/unit/`＋`tests/integration/`，12 個測試全綠；之後各 phase 的測試都往這兩個子目錄累加。
