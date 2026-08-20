# Phase 15：資料庫一次改版與預設資料夾（folder 表、六筆種子、舊資料遷移）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🧱 **本增量的兩條鐵律**（產品負責人 2026-08-20 拍板，每個 phase 都適用）：
> 1. **不要過度設計**——只做 `docs/design/design1.md` 寫到的事。
> 2. **不留過渡產物，一次改成新的**——`schema.sql` 直接改成最終版（不是分兩次改）；`db/migrate_folders.sql` 一次跑完；程式不留任何新舊相容分支、不留 deprecated（已淘汰但仍留著）函式。唯一允許的「舊資料」行為是 design1.md §10 明訂的：舊列路徑欄位為 NULL → 讀圖 404 → 前端顯示占位。

**目標：** 讓資料庫多出一張「資料夾」表（`folder`）與六筆預設資料夾，並讓每張照片都掛在某一個資料夾底下（`photo.folder_id`），同時把原圖／縮圖路徑欄位一次加好——**但完全不改任何對外行為**，既有 79 個測試必須全部繼續綠。

---

## 前置條件

- 需要已完成的 phase：**Phase 01〜14 全部**（本增量的第一個 phase，接在 v4 完整系統之後）。
- 開工前基線（**執行時要實查一次**）：

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：`79 passed`。**對不上就先停下來查清楚**，不要帶著紅燈開工。
- 設計依據：`docs/design/design1.md` §5（預設六個資料夾）、§6（資料模型）、§10（舊資料遷移）。
- 資料庫：PostgreSQL@17 跑在 **5433** 埠。
  - 正式庫 `PersonalDocAI`：**已有 2 列真實照片**（`category` 皆「收據」），**絕對不可弄丟**——所以正式庫走遷移腳本，不重建。
  - 測試庫 `PersonalDocAI_test`：可以隨便重建。
- 每次開工先執行：

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

現在的系統裡，`photo.category` 是 VLM 隨手填的自由字串（「收據」、`Receipt`、什麼都可能）。這個增量要把它變成**受控的資料夾名稱**：系統有一份資料夾清單，照片只能歸在清單裡的某一個資料夾底下。

要做到這件事，第一步是資料庫得先長出「資料夾」這個概念。本 phase 就只做這一步：

1. **新增 `folder` 表**：欄位是名稱、說明、是不是「收件箱」、建立時間。
2. **塞進六筆預設資料夾**（design1.md §5 原文）：未分類、收據、飲食、風景、文件、其他。順序很重要——**插入順序就是 id 1〜6**，之後測試會直接依賴這個編號。
3. **`photo` 表加四個欄位**：`folder_id`（掛在哪個資料夾，不可為空）、`original_path`／`thumbnail_path`（原圖與縮圖檔案位置，本 phase 先全部留空）、`content_type`（是 JPEG 還是 PNG，本 phase 也先留空）。
4. **`insert_photo` 自動掛資料夾**：寫入照片時，依 `category` 找同名資料夾（不分大小寫）；找不到就掛「未分類」。**`category` 欄位的值本身完全不動**——這樣既有 79 個測試（它們斷言「上傳後 category＝VLM 給的值」）才會繼續綠。真正把 `category` 改成「未分類」是 Phase 20 的事。
5. **正式庫用遷移腳本改**：正式庫有 2 張真照片，不能 `DROP TABLE` 重建，所以另外寫一份**可以重複執行**的 `db/migrate_folders.sql`。

> ⚠️ **為什麼本 phase 一個測試也不該變紅？** 因為對外行為（HTTP 回應、`category` 的值）完全沒動。唯一會動的是「資料庫多了一張表、多了幾個欄位」。如果既有測試紅了，代表你改多了。

**名詞**（讀者是新手，這裡出現的每個非日常用語都解釋一次）：

| 名詞 | 白話解釋 |
|---|---|
| 資料夾（folder） | 使用者收納照片的類型，有名稱與說明。本增量規定 `photo.category` **等於**它所屬資料夾的 `name` |
| 收件箱（inbox） | 「未分類」這個系統資料夾的角色：不確定要放哪裡的照片先丟這裡。用 `is_inbox = true` 標記，全系統只准有一個 |
| 種子資料（seed） | 建表時就先塞進去的初始資料。這裡指六筆預設資料夾 |
| FK（foreign key，外鍵） | 「這一欄的值必須是另一張表裡真的存在的 id」的規則。`photo.folder_id REFERENCES folder(id)` 就是說：照片只能掛在真的存在的資料夾上，掛一個不存在的編號資料庫會直接拒絕 |
| `REFERENCES folder (id)` | 寫出上面那條 FK 規則的 SQL 語法 |
| `NOT NULL` | 「這一欄不准是空的」。`folder_id integer NOT NULL` ＝每張照片一定要有資料夾 |
| `IDENTITY` | PostgreSQL 的「自動編號」欄位寫法（`GENERATED ALWAYS AS IDENTITY`）。新增一列時 id 自動 +1，不用自己算 |
| `UNIQUE` | 「這一欄不准有重複值」。`name text NOT NULL UNIQUE` ＝資料夾名稱不可重複 |
| partial unique index（部分唯一索引） | 「**只對符合條件的那些列**檢查不可重複」的索引。`CREATE UNIQUE INDEX folder_one_inbox ON folder ((true)) WHERE is_inbox;` 的意思是：在 `is_inbox = true` 的那些列裡，大家的索引值都是同一個固定值 `true`，所以只要出現第二個收件箱就會撞號被擋下來——用一行 SQL 做到「全系統最多一個收件箱」 |
| 索引（index） | 資料庫的「目錄」，讓查詢不必整張表逐列掃描。唯一索引還兼任「不可重複」的守門員 |
| `TRUNCATE` | 一次清空整張表（比逐列 `DELETE` 快很多）。只給測試用 |
| `RESTART IDENTITY` | 清空後把自動編號歸零，id 重新從 1 開始編 |
| `CASCADE`（TRUNCATE 的） | 「連同被外鍵指著的相關表一起清」。這裡我們本來就把 `photo, folder` 兩張一起寫進 TRUNCATE，加 `CASCADE` 只是讓 PostgreSQL 不囉嗦 |
| 遷移（migration） | 在**不清空資料**的前提下，把既有資料庫的結構改成新版本的腳本 |
| 可重跑（idempotent） | 同一份腳本重複執行結果都一樣、不會出錯。靠 `IF NOT EXISTS`／`ON CONFLICT DO NOTHING` 這類寫法達成 |
| `IF NOT EXISTS` | 「已經有了就跳過，不要報錯」 |
| `ON CONFLICT (name) DO NOTHING` | INSERT 時如果撞到 `name` 重複，就安靜地跳過這一列，不報錯 |
| 子查詢（subquery） | 寫在括號裡、當成一個值來用的查詢。例如 `(SELECT id FROM folder WHERE is_inbox)` 會算出「收件箱的 id」這個數字 |
| `COALESCE(a, b)` | SQL 的「取第一個有值的」：`a` 不是 NULL 就用 `a`，是 NULL 才用 `b` |
| `lower(x)` | 把字串轉小寫。`lower(name) = lower(輸入)` ＝不分大小寫比對（中文沒有大小寫，轉了也不變，所以中文名稱不受影響） |
| autouse fixture | pytest 的「每個測試都自動套用的前置／後置動作」，不必在測試函式裡寫它的名字。本專案的 `reset_tables` 與 `wire_fake_ai` 都是 |
| `array_fill(...)` | PostgreSQL 產生「一整排相同數字的陣列」的函式，手動驗證時拿來湊一個假向量用 |

---

## ASCII 圖

### 圖一：資料表結構，改版前 vs 改版後

```
【改版前（v4，Phase 01〜14）】

  ┌───────────────── photo ─────────────────┐
  │ id            integer  IDENTITY PK      │
  │ text          text     NOT NULL         │
  │ category      text     ← VLM 自由字串    │
  │ location      text                      │
  │ items         text[]   NOT NULL         │
  │ content_time  date                      │
  │ uploaded_at   timestamptz NOT NULL      │
  │ embedding     vector(1024) NOT NULL     │
  └─────────────────────────────────────────┘
              （只有一張表）

【改版後（本 phase 做完）】

  ┌──────────────── folder ─────────────────┐
  │ id           integer IDENTITY PK        │◀─────┐
  │ name         text NOT NULL UNIQUE       │      │ FK：照片只能掛在
  │ description  text NOT NULL DEFAULT ''   │      │ 真的存在的資料夾上
  │ is_inbox     boolean NOT NULL false     │      │
  │ created_at   timestamptz NOT NULL now() │      │
  └─────────────────────────────────────────┘      │
   UNIQUE INDEX folder_one_inbox …WHERE is_inbox   │
   （全系統最多一個收件箱）                          │
   種子 6 筆：1 未分類(inbox) / 2 收據 / 3 飲食      │
             4 風景 / 5 文件 / 6 其他               │
                                                   │
  ┌───────────────── photo ─────────────────┐      │
  │ id            integer IDENTITY PK       │      │
  │ text          text NOT NULL             │      │
  │ category      text        ← 值先不動     │      │
  │ folder_id     integer NOT NULL ─────────┼──────┘  ★新
  │ location      text                      │
  │ items         text[] NOT NULL           │
  │ content_time  date                      │
  │ uploaded_at   timestamptz NOT NULL      │
  │ embedding     vector(1024) NOT NULL     │
  │ original_path  text   ← 本 phase 恆 NULL │  ★新
  │ thumbnail_path text   ← 本 phase 恆 NULL │  ★新
  │ content_type   text   ← 本 phase 恆 NULL │  ★新
  └─────────────────────────────────────────┘
   INDEX photo_embedding_idx hnsw（原有，保留）
```

### 圖二：兩個資料庫走兩條不同的路

```
                     db/schema.sql（最終版）
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
   PersonalDocAI_test（測試庫）        PersonalDocAI（正式庫）
   可以整個砍掉重建                    有 2 張真照片，不能砍
              │                                │
   psql -f db/schema.sql              psql -f db/migrate_folders.sql
   DROP photo → DROP folder                    │
   → CREATE folder + 種子 6 筆         ① CREATE TABLE IF NOT EXISTS folder + 種子
   → CREATE photo（含 folder_id）      ② ALTER photo ADD COLUMN IF NOT EXISTS ×4
   → CREATE hnsw index                        （folder_id 先允許 NULL）
              │                        ③ UPDATE：依 category 對到同名資料夾，
              ▼                             對不到／category 空 → 未分類，
   每個測試前由 conftest 的                    並把 category 改成「未分類」
   reset_tables 重播六筆種子           ④ ALTER COLUMN folder_id SET NOT NULL
                                              │
                                              ▼
                                       2 列都掛在「收據」，
                                       三個路徑欄位維持 NULL
                                       （之後瀏覽頁顯示占位圖）
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1 先把新測試寫好、跑到**紅**，步驟 2〜5 才動實作讓它轉綠。中間會經過一段「幾乎全部測試都紅」的階段（步驟 3 之後），**那是預期的**，步驟 4〜5 做完就會全綠。

---

### 步驟 1：先寫測試（紅）

打開 `tests/integration/test_photo_repository.py`，在**檔案最後面**（現有的 `test_count_and_clear_photos` 之後）接上四個新測試：

```python


# ---------- Phase 15 追加：資料夾（folder）資料層 ----------


def test_六個預設資料夾的順序就是_folder_id():
    """種子資料的插入順序即 id：1 未分類、2 收據、3 飲食、4 風景、5 文件、6 其他。

    這個順序被 conftest、遷移腳本與之後所有 phase 共用，改動等於改規格。
    """
    for 序號, (資料夾名稱, _說明, _是否收件箱) in enumerate(repo.DEFAULT_FOLDERS, start=1):
        row = _insert_sample(category=資料夾名稱)
        assert row["folder_id"] == 序號, f"{資料夾名稱} 應該掛在 folder_id={序號}"


def test_category_對不到資料夾時掛在未分類():
    """VLM 給了清單外的字串（例如英文的 Receipt）→ 照片掛「未分類」。

    注意：category 欄位的值**不會**被改寫，仍然是 VLM 給的原文。
    把 category 改成「未分類」是 Phase 20 的事，本 phase 不碰對外行為。
    """
    row = _insert_sample(category="Receipt")

    assert row["folder_id"] == 1        # 1 ＝未分類（收件箱）
    assert row["category"] == "Receipt"  # 值本身不動


def test_category_為空時掛在未分類():
    """風景照可能沒有類別（category 為 None）→ 一樣掛「未分類」。"""
    row = _insert_sample(category=None)

    assert row["folder_id"] == 1
    assert row["category"] is None


def test_fetch_photo_會回傳資料夾與檔案路徑欄位():
    """新增的四個欄位讀得回來；本 phase 還沒有人寫檔，所以三個路徑欄位都是空的。"""
    inserted = _insert_sample()

    row = repo.fetch_photo(inserted["id"])

    assert row["folder_id"] == 2          # 2 ＝收據
    assert row["original_path"] is None
    assert row["thumbnail_path"] is None
    assert row["content_type"] is None
```

跑一次看它紅：

```bash
pytest tests/integration/test_photo_repository.py -q
```

預期：**4 failed, 10 passed**——四個新測試都因為 `repo.DEFAULT_FOLDERS` 不存在（`AttributeError`）或欄位不存在而失敗。這就是紅燈，正確。

---

### 步驟 2：把 `db/schema.sql` 改成最終版

**整份檔案換成下面的內容**（一次到位，不分兩次改）。注意 `DROP` 的順序：**先 photo 再 folder**，因為 photo 用外鍵指著 folder，被指著的表不能先砍。

```sql
-- 啟用 pgvector 擴充套件（讓資料庫多出 vector 型別）
CREATE EXTENSION IF NOT EXISTS vector;

-- 砍表順序固定：先 photo 再 folder。
-- photo.folder_id 用外鍵指著 folder，被指著的表不能先砍，否則 PostgreSQL 會拒絕。
DROP TABLE IF EXISTS photo;
DROP TABLE IF EXISTS folder;

-- ---------- 資料夾（＝使用者看到的分類）----------
CREATE TABLE folder (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,       -- 資料夾名稱，不可重複；photo.category 必須等於它
  description text        NOT NULL DEFAULT '',   -- 說明，會注入 VLM 的 prompt 幫助推薦
  is_inbox    boolean     NOT NULL DEFAULT false,-- 是否為系統收件箱「未分類」
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 全域最多一個收件箱。
-- 這是「部分唯一索引」：只對 is_inbox = true 的列生效，
-- 而它們的索引值都是同一個固定值 (true)，所以第二個收件箱會直接撞號被擋下來。
CREATE UNIQUE INDEX folder_one_inbox ON folder ((true)) WHERE is_inbox;

-- 六筆預設資料夾（design1.md §5 原文）。
-- ★ 插入順序就是 id 1〜6，測試與遷移腳本都依賴這個編號，不要調換。
INSERT INTO folder (name, description, is_inbox) VALUES
  ('未分類', '不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。', true),
  ('收據',   '發票、消費憑證、購物明細。',                        false),
  ('飲食',   '食物、飲料、餐廳、菜單。',                          false),
  ('風景',   '戶外、旅遊、地點、景色。',                          false),
  ('文件',   '非收據的文字資料，例如名片、說明書。',              false),
  ('其他',   '看懂是什麼，但不符合上面任何一個。',                false);

-- ---------- 照片 ----------
CREATE TABLE photo (
  id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text           text        NOT NULL,               -- VLM 的文字描述（失敗就不存，所以不會空）
  category       text,                               -- 必須等於所屬 folder.name；未分類時為「未分類」
  folder_id      integer     NOT NULL REFERENCES folder (id),  -- 掛在哪個資料夾（外鍵，不可為空）
  location       text,                               -- 地點/商家（如：Target），可空
  items          text[]      NOT NULL DEFAULT '{}',  -- 物品清單（多值）
  content_time   date,                               -- 內容時間（如收據日期），可空
  uploaded_at    timestamptz NOT NULL DEFAULT now(), -- 上傳時間，DB 自動記
  embedding      vector(1024) NOT NULL,              -- 文字＋欄位合併內容的向量
  original_path  text,                               -- 原圖位置，如 data/photos/1.jpg；舊資料可空
  thumbnail_path text,                               -- 縮圖位置，如 data/thumbs/1.jpg；舊資料可空
  content_type   text                                -- image/jpeg 或 image/png
);

-- 向量索引：HNSW ＋ cosine 距離（pgvector 官方語法）。
-- 索引＝資料庫的「目錄」，查資料不用整張表逐列掃描；
-- HNSW＝專門加速「找最相近向量」的索引演算法；
-- cosine（餘弦）距離＝比較兩個向量的方向有多接近，越接近代表意思越像。
-- 只建這一個索引；demo 資料量用循序掃描就夠，不養用不到的索引
CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);
```

---

### 步驟 3：重建測試庫

```bash
psql -d PersonalDocAI_test -f db/schema.sql
```

預期輸出（順序如下，兩行 `NOTICE` 都正常：pgvector 擴充套件早就裝好了所以跳過；第一次跑本來就還沒有 `folder` 表所以跳過）：

```
NOTICE:  extension "vector" already exists, skipping
CREATE EXTENSION
DROP TABLE
NOTICE:  table "folder" does not exist, skipping
DROP TABLE
CREATE TABLE
CREATE INDEX
INSERT 0 6
CREATE TABLE
CREATE INDEX
```

確認種子進去了：

```bash
psql -d PersonalDocAI_test -c "SELECT id, name, is_inbox FROM folder ORDER BY id;"
```

預期：6 列，`id=1` 是「未分類」且 `is_inbox = t`，其餘 `f`。

> 😱 **這一步之後跑 pytest 會大面積轉紅**（`null value in column "folder_id" violates not-null constraint`）——因為 `insert_photo` 還沒學會填 `folder_id`。**這是預期的**，下一步就修好。

---

### 步驟 4：改 `app/repositories/photo_repository.py`

#### 4-1　檔案開頭的 docstring 與 `PHOTO_COLUMNS`

把檔案最上方這段：

```python
"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
本檔含上傳寫入與兩條檢索查詢（search_by_metadata／search_by_vector，Phase 9 加入）。
"""
```

改成：

```python
"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
本檔含上傳寫入、兩條檢索查詢（search_by_metadata／search_by_vector，Phase 9 加入），
以及資料夾（folder）相關操作（Phase 15 加入）。
"""
```

再把這一行：

```python
# 每次查詢都取回的欄位，固定順序，避免各處寫法不一致
PHOTO_COLUMNS = "id, text, category, location, items, content_time, uploaded_at"
```

改成（多了四個新欄位；**insert 的 RETURNING 與 fetch 的 SELECT 共用同一份清單**，兩邊回來的字典鍵才會完全一致——既有的 `test_fetch_photo_returns_row` 直接拿兩者做相等比較，靠的就是這一點）：

```python
# 每次查詢都取回的欄位，固定順序，避免各處寫法不一致。
# insert_photo 的 RETURNING 與 fetch_photo 的 SELECT 共用這一份，兩邊鍵名保證一致。
PHOTO_COLUMNS = (
    "id, text, category, folder_id, location, items, content_time, uploaded_at, "
    "original_path, thumbnail_path, content_type"
)

# 六筆預設資料夾（design1.md §5 原文）。
# ★ 順序就是 id 1〜6，且三個地方必須一模一樣：
#   db/schema.sql、db/migrate_folders.sql、這裡。改動等於改規格。
DEFAULT_FOLDERS: list[tuple[str, str, bool]] = [
    ("未分類", "不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。", True),
    ("收據", "發票、消費憑證、購物明細。", False),
    ("飲食", "食物、飲料、餐廳、菜單。", False),
    ("風景", "戶外、旅遊、地點、景色。", False),
    ("文件", "非收據的文字資料，例如名片、說明書。", False),
    ("其他", "看懂是什麼，但不符合上面任何一個。", False),
]
```

#### 4-2　`insert_photo` 的 SQL 加上 `folder_id`

把 `insert_photo` 裡現有的 SQL 這一段：

```python
    sql = f"""
        INSERT INTO photo (text, category, location, items, content_time, uploaded_at, embedding)
        VALUES (
            %(text)s, %(category)s, %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector
        )
        RETURNING {PHOTO_COLUMNS};
    """
```

改成：

```python
    # folder_id 由 SQL 當場算出來：
    #   ① 先找名稱和 category 一樣的資料夾（lower() ＝不分大小寫，'receipt' 也對得到 'Receipt'）
    #   ② 找不到（含 category 為 NULL）就退回收件箱「未分類」
    # 兩個子查詢包在 COALESCE 裡，整段仍然是「一條 INSERT」，天然原子。
    # ★ category 欄位的值本身不動——把它改寫成資料夾名稱是 Phase 20（上傳）與 Phase 21（歸類）的事。
    sql = f"""
        INSERT INTO photo (
            text, category, folder_id, location, items, content_time, uploaded_at, embedding
        )
        VALUES (
            %(text)s, %(category)s,
            COALESCE(
                (SELECT id FROM folder WHERE lower(name) = lower(%(category)s::text)),
                (SELECT id FROM folder WHERE is_inbox)
            ),
            %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector
        )
        RETURNING {PHOTO_COLUMNS};
    """
```

`params` 那一段**完全不用改**（`%(category)s` 出現兩次沒關係，psycopg 支援同一個具名參數重複使用）。

#### 4-3　新增 `reset_folders_and_photos()`

接在既有的 `clear_photos()` **後面**（`search_by_metadata` 之前）加上：

```python
def reset_folders_and_photos() -> None:
    """把兩張表清空並重播六筆預設資料夾。只給測試用。

    TRUNCATE photo, folder＝一次清空兩張表（photo 用外鍵指著 folder，
    所以兩張要一起清，不能只清 folder）；
    RESTART IDENTITY＝把自動編號歸零，重播後 folder 的 id 一定是 1〜6；
    CASCADE＝連同被外鍵指著的相關表一起清（這裡兩張本來就都寫進去了，加著保險）。
    """
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手（與 conftest 的防呆雙保險）
    assert "PersonalDocAI_test" in config.DATABASE_URL

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE photo, folder RESTART IDENTITY CASCADE;")
            cur.executemany(
                "INSERT INTO folder (name, description, is_inbox) VALUES (%s, %s, %s);",
                DEFAULT_FOLDERS,
            )
```

> 📌 **既有的 `clear_photos()` 保留不動**。它只清 `photo`（不動 `folder`），仍然被 `tests/integration/test_photo_repository.py::test_count_and_clear_photos` 使用，**不是過渡產物**，不要順手刪掉。

`fetch_photo()`、`count_photos()`、`search_by_metadata()`、`search_by_vector()` 都**不用改**——它們共用 `PHOTO_COLUMNS`，改常數就等於一起改好了。

---

### 步驟 5：改 `tests/conftest.py`

把現有的這段：

```python
@pytest.fixture(autouse=True)
def clean_photo_table():
    """每個測試開始前清空 photo 表，確保測試彼此獨立。"""
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手
    assert "PersonalDocAI_test" in config.DATABASE_URL
    from app.repositories import photo_repository as repo

    repo.clear_photos()
    yield
```

改成（改名 `reset_tables`，並改呼叫 `reset_folders_and_photos()`）：

```python
@pytest.fixture(autouse=True)
def reset_tables():
    """每個測試開始前清空 photo 與 folder 兩張表，並重播六筆預設資料夾。

    重播是必要的：folder 被 TRUNCATE ... RESTART IDENTITY 清掉後 id 會歸零，
    每個測試因此都拿到一模一樣的 1〜6 六筆資料夾，測試彼此獨立又可預測。
    """
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手
    assert "PersonalDocAI_test" in config.DATABASE_URL
    from app.repositories import photo_repository as repo

    repo.reset_folders_and_photos()
    yield
```

順手把檔案第一行的 docstring：

```python
"""pytest 共用設定：把資料庫指到測試庫，並在每個測試前清空 photo 表。"""
```

改成：

```python
"""pytest 共用設定：把資料庫指到測試庫，每個測試前清空兩張表並重播預設資料夾。"""
```

---

### 步驟 6：跑測試（綠）

```bash
pytest tests/integration/test_photo_repository.py -q
```

預期：`14 passed`（原本 10 個 ＋ 本 phase 新增 4 個）。

再跑全量：

```bash
pytest -q
```

預期：`83 passed`（＝開工基線 **79** ＋ 本 phase 新增 **4**）。
**79 個既有測試一個都不准紅**——紅了就代表改到了對外行為，回頭檢查步驟 4-2 是不是不小心動了 `category` 的值。

---

### 步驟 7：寫 `db/migrate_folders.sql`（正式庫專用，可重跑）

建立新檔 `db/migrate_folders.sql`，內容如下：

```sql
-- 正式庫（PersonalDocAI）一次性遷移：加上 folder 表與 photo 的四個新欄位。
-- 對應 design1.md §10。特性：可重複執行，跑第二次不會出錯也不會改壞資料。
-- 用法：psql -d PersonalDocAI -f db/migrate_folders.sql
--
-- ⚠️ 測試庫不要用這一份，測試庫直接 psql -d PersonalDocAI_test -f db/schema.sql 重建就好。

-- ① 建 folder 表（已經有就跳過）＋ 六筆種子（撞名就跳過）
CREATE TABLE IF NOT EXISTS folder (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,
  description text        NOT NULL DEFAULT '',
  is_inbox    boolean     NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 全域最多一個收件箱（部分唯一索引，只對 is_inbox = true 的列生效）
CREATE UNIQUE INDEX IF NOT EXISTS folder_one_inbox ON folder ((true)) WHERE is_inbox;

-- 六筆預設資料夾，內容與順序必須和 db/schema.sql 完全一致
INSERT INTO folder (name, description, is_inbox) VALUES
  ('未分類', '不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。', true),
  ('收據',   '發票、消費憑證、購物明細。',                        false),
  ('飲食',   '食物、飲料、餐廳、菜單。',                          false),
  ('風景',   '戶外、旅遊、地點、景色。',                          false),
  ('文件',   '非收據的文字資料，例如名片、說明書。',              false),
  ('其他',   '看懂是什麼，但不符合上面任何一個。',                false)
ON CONFLICT (name) DO NOTHING;

-- ② photo 加四個新欄位（folder_id 這時先允許 NULL，等 ③ 填完值才收緊）
ALTER TABLE photo ADD COLUMN IF NOT EXISTS folder_id      integer REFERENCES folder (id);
ALTER TABLE photo ADD COLUMN IF NOT EXISTS original_path  text;
ALTER TABLE photo ADD COLUMN IF NOT EXISTS thumbnail_path text;
ALTER TABLE photo ADD COLUMN IF NOT EXISTS content_type   text;

-- ③ 把既有照片掛上資料夾：
--    依 category 找同名資料夾（不分大小寫）；對不到或 category 為空 → 未分類。
--    只處理還沒掛上的列，所以重跑不會動到已經歸好的資料。
UPDATE photo p
SET folder_id = COALESCE(
      (SELECT f.id FROM folder f WHERE lower(f.name) = lower(p.category)),
      (SELECT f.id FROM folder f WHERE f.is_inbox)
    )
WHERE p.folder_id IS NULL;

-- ④ 讓 category 對齊所屬資料夾的名稱（design1.md §6 的雙寫規則：category = folder.name）。
--    對不到資料夾而落到未分類的那些列，category 會在這一步被改成「未分類」。
--    IS DISTINCT FROM ＝「兩邊不一樣（NULL 也算不一樣）」，本來就相同的列不會被更新。
UPDATE photo p
SET category = f.name
FROM folder f
WHERE f.id = p.folder_id AND p.category IS DISTINCT FROM f.name;

-- ⑤ 全部列都掛好資料夾了，把欄位收緊成 NOT NULL（重跑無害）
ALTER TABLE photo ALTER COLUMN folder_id SET NOT NULL;

-- ⑥ 路徑三欄維持 NULL：舊照片本來就沒有原始檔，不假裝有圖。
--    之後 GET /photos/{id}/thumbnail 會回 404，前端顯示占位（design1.md §10、§12）。
```

---

### 步驟 8：對正式庫跑一次遷移並核對

**動手前先備份**——正式庫裡的 2 張真實照片是全系統唯一沒有第二份的資料（測試庫可以隨時重建，正式庫不行），而且遷移沒有反向腳本。先把整個庫倒成一個檔案留著：

```bash
pg_dump -d PersonalDocAI -f ~/PersonalDocAI-backup-遷移前.sql
```

（`pg_dump` ＝ PostgreSQL 內建的備份工具，把整個資料庫的結構與資料倒成一份 SQL 純文字檔。萬一遷移結果不如預期，用 `psql -d PersonalDocAI -f ~/PersonalDocAI-backup-遷移前.sql` 之前先手動清庫再灌回即可。遷移驗收通過後這個檔案可以刪。）

備份完成後才跑遷移：

```bash
psql -d PersonalDocAI -f db/migrate_folders.sql
```

預期輸出：

```
CREATE TABLE
CREATE INDEX
INSERT 0 6
ALTER TABLE
ALTER TABLE
ALTER TABLE
ALTER TABLE
UPDATE 2
UPDATE 0
ALTER TABLE
```

（`UPDATE 2` ＝兩張舊照片掛上資料夾；`UPDATE 0` ＝它們的 `category` 本來就是「收據」，和資料夾名稱一致，不需要改。）

核對結果：

```bash
psql -d PersonalDocAI -c "SELECT p.id, p.category, p.folder_id, f.name AS folder_name, p.original_path, p.thumbnail_path, p.content_type FROM photo p JOIN folder f ON f.id = p.folder_id ORDER BY p.id;"
```

預期：

```
 id | category | folder_id | folder_name | original_path | thumbnail_path | content_type
----+----------+-----------+-------------+---------------+----------------+--------------
  1 | 收據     |         2 | 收據        |               |                |
  2 | 收據     |         2 | 收據        |               |                |
(2 筆資料)
```

**兩列都在「收據」、三個路徑欄位都是空的**——這正是 design1.md §10 期望的結果。

再驗一次「可重跑」：

```bash
psql -d PersonalDocAI -f db/migrate_folders.sql
psql -d PersonalDocAI -c "SELECT count(*) AS 資料夾數 FROM folder;"
```

預期：第二次執行不報任何 `ERROR`（種子那行會顯示 `INSERT 0 0`，代表六筆都撞名跳過），資料夾數仍是 `6`。

順便確認「全系統最多一個收件箱」真的被擋住：

```bash
psql -d PersonalDocAI -c "INSERT INTO folder (name, description, is_inbox) VALUES ('第二收件箱','測試用',true);"
```

預期：出現錯誤 `ERROR: duplicate key value violates unique constraint "folder_one_inbox"`——**這就是正確行為**（資料沒有被寫進去，不需要清理）。

---

## 驗收清單

- [ ] 開工前實查基線 `pytest -q` ＝ **79 passed**
- [ ] `db/schema.sql` 已是最終版：`DROP photo` → `DROP folder` → `CREATE folder` → `folder_one_inbox` 部分唯一索引 → 六筆種子 → `CREATE photo`（含 `folder_id NOT NULL REFERENCES folder(id)` 與三個新欄位）→ HNSW 索引保留
- [ ] 測試庫已用 `psql -d PersonalDocAI_test -f db/schema.sql` 重建，`SELECT id, name, is_inbox FROM folder ORDER BY id;` 回 6 列且 id=1 為「未分類」`is_inbox = t`
- [ ] `photo_repository.py`：已加 `DEFAULT_FOLDERS`、`reset_folders_and_photos()`；`PHOTO_COLUMNS` 已含四個新欄位；`insert_photo` 用 `COALESCE` ＋兩個子查詢決定 `folder_id`
- [ ] `insert_photo` **沒有**改寫 `category` 的值（Phase 20 才做）
- [ ] `clear_photos()` 仍保留（`test_count_and_clear_photos` 還在用）
- [ ] `tests/conftest.py` 的 autouse fixture 已改名 `reset_tables` 並呼叫 `reset_folders_and_photos()`
- [ ] `db/migrate_folders.sql` 已建立，且**連跑兩次都不報錯**
- [ ] 跑遷移**之前**已用 `pg_dump` 備份正式庫（步驟 8 開頭）
- [ ] 正式庫核對 SQL 顯示：2 列都掛在「收據」（`folder_id = 2`）、三個路徑欄位皆 NULL
- [ ] 第二個收件箱寫入被 `folder_one_inbox` 擋下
- [ ] **全量測試全綠**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：`83 passed`（＝基線 79 ＋ 本 phase 新增 4；**79 個既有測試一個都沒紅**）

- [ ] **SQL 依然只出現在 repository 一個檔案**

  ```bash
  grep -rlnE "SELECT |INSERT INTO|TRUNCATE|ALTER TABLE" app/ --include="*.py"
  ```

  預期輸出**只有一行**：`app/repositories/photo_repository.py`

- [ ] **git commit**

  ```bash
  git add db/schema.sql db/migrate_folders.sql app/repositories/photo_repository.py tests/conftest.py tests/integration/test_photo_repository.py
  git commit -m "feat: Phase 15 資料庫一次改版——folder 表＋六筆預設資料夾種子（partial unique index 保證單一收件箱）、photo 掛 folder_id 與原圖/縮圖/格式三欄、insert_photo 依 category 自動歸夾、conftest 改 reset_tables 每測重播種子、正式庫 migrate_folders.sql 可重跑遷移（2 列歸「收據」、路徑留 NULL），+4 tests（累計 83）"
  ```

---

## 常見問題

**Q1：`CREATE UNIQUE INDEX folder_one_inbox ON folder ((true)) WHERE is_inbox;` 這個 `((true))` 是什麼鬼？**
它是「表達式索引」：索引的內容不是某個欄位，而是一個算出來的值——這裡固定算成 `true`。加上 `WHERE is_inbox` 之後，只有收件箱那幾列會被放進索引，而它們的索引值全都是 `true`，所以第二列一進來就撞號。用一行 SQL 換到「全系統最多一個收件箱」的保證，不用寫任何 Python 檢查。

**Q2：為什麼 `insert_photo` 不改 `category` 的值？資料夾不是應該等於 category 嗎？**
最終確實要相等（design1.md §6），但**本 phase 刻意不做**：79 個既有測試斷言「上傳後 category ＝ VLM 給的值」，現在就改會讓它們全紅，而本 phase 的驗收條件就是「不改對外行為」。改寫 `category` 是 Phase 20（上傳一律「未分類」）與 Phase 21（歸類後寫成資料夾名稱）的工作。

**Q3：測試庫可以改用 `migrate_folders.sql` 嗎？**
不要。兩個檔案各有各的角色：`schema.sql` 是**最終版建表腳本**（重跑＝清空重建，測試庫專用），`migrate_folders.sql` 是**一次性遷移腳本**（保留資料，正式庫專用）。混用會讓兩邊的結構慢慢走鐘。

**Q4：`TRUNCATE photo, folder` 為什麼要把兩張寫在一起？**
`photo.folder_id` 用外鍵指著 `folder`。如果只清 `folder`，PostgreSQL 會因為「還有照片指著這些資料夾」而拒絕；兩張一起寫進同一個 `TRUNCATE`，資料庫就知道你要一次清乾淨。

**Q5：正式庫遷移跑壞了怎麼辦？**
先別重跑。用 `psql -d PersonalDocAI -c "SELECT id, category, folder_id FROM photo ORDER BY id;"` 看實際狀態：只要 `folder_id` 是 NULL，重跑腳本的第 ③ 步就會補上；`folder` 表已存在也不影響（`IF NOT EXISTS` 會跳過）。**這份腳本設計成可重跑，就是為了讓你能安心再跑一次。**

**Q6：可不可以順便加個 `folder` 的 `updated_at`、或做刪除資料夾的功能？**
不可以。design1.md §3 明列「不做刪除照片、刪除系統資料夾」，§6 的欄位就是全部。這是 side project，不過度設計。

---

## 完成後的專案狀態

資料庫已經是本增量的**最終結構**：`folder` 表帶六筆預設資料夾與「最多一個收件箱」的保證，每張照片都掛在某個資料夾底下，原圖／縮圖／格式三個欄位也預留好了（目前全空）。正式庫的 2 張真實照片安然無恙地歸進「收據」。

但這一切目前只有資料層看得到——API 回應、上傳流程、網頁都還完全沒變。下一步（Phase 16）要把資料夾**讀得出來**：清單、單一資料夾、依名稱尋找、建立新資料夾、列出資料夾內的照片。測試累計 **83** 個。
