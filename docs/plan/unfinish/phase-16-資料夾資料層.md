# Phase 16：資料夾資料層（folder 的五個 repository 函式）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🧱 **本增量的兩條鐵律**（產品負責人 2026-08-20 拍板，每個 phase 都適用）：
> 1. **不要過度設計**——只做 `docs/design/design1.md` 寫到的事。
> 2. **不留過渡產物，一次改成新的**——程式不留任何新舊相容分支、不留 deprecated（已淘汰但仍留著）函式。

**目標：** 在唯一能寫 SQL 的 `photo_repository.py` 裡，補上「讀寫資料夾」的五個函式，讓之後的 VLM prompt、上傳回應、歸類端點、瀏覽頁都有資料可用。**本 phase 一樣不動任何對外行為**——沒有新端點、沒有新回應欄位，純資料層。

---

## 前置條件

- 需要已完成的 phase：**Phase 15**（`folder` 表、六筆種子、`photo.folder_id`、`conftest` 的 `reset_tables`）。
- 開工前基線（**執行時要實查一次**）：

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：`83 passed`。對不上就先回頭確認 Phase 15 是否完整收尾。
- 設計依據：`docs/design/design1.md` §5（預設資料夾）、§7.2／§7.4（之後要用這些資料的端點）、§11（分層：SQL 只准寫在 repository）。
- 本 phase 的測試**不需要 Ollama**，只連本機測試庫 `PersonalDocAI_test`。
- 每次開工先執行：

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

Phase 15 讓資料庫「有」資料夾了，但目前沒有任何 Python 程式讀得到它——除了 `insert_photo` 內部那段自動歸夾的 SQL 之外，整個 `app/` 對 `folder` 表一無所知。

本 phase 補上五個函式，剛好對應之後每個 phase 的需求：

| 函式 | 一句話 | 之後誰會用 |
|---|---|---|
| `list_folders()` | 全部資料夾＋每個放了幾張照片 | Phase 18（注入 VLM prompt）、Phase 20（上傳回應的 `folders`）、Phase 22（`GET /folders`） |
| `get_folder(folder_id)` | 拿單一資料夾；沒有就回 `None` | Phase 21（歸類到既有資料夾，找不到 → 404）、Phase 22（`GET /folders/{id}`） |
| `find_folder_by_name(name)` | 依名稱找（**不分大小寫**）；沒有就回 `None` | Phase 21（自建資料夾時擋重名 → 409） |
| `create_folder(name, description)` | 建一個新資料夾，回新的那一列 | Phase 21（彈窗選項③「自建並歸類」） |
| `list_photos_in_folder(folder_id)` | 某個資料夾裡的照片摘要，新的在前 | Phase 22（瀏覽頁的縮圖牆） |

**五個函式全部回傳 Python 的 `dict`（字典）**，鍵名固定，之後的 Pydantic 模型直接照抄。這是本專案一貫的做法：repository 回「一列列的字典」，service／router 再組成回應模型。

**「張數」怎麼算**：資料夾裡沒有照片時，答案要是 `0` 而不是「這個資料夾不見了」。所以用 `LEFT JOIN`——以資料夾為主，照片有就配上、沒有就留空，再數一數。這樣六個預設資料夾即使一張照片都沒有，也全都會出現在清單裡。

> ⚠️ **重名交給呼叫端擋**：`create_folder` 不自己檢查名稱重複。design1.md §7.2 規定重名要回 **409**，而 409 是 HTTP 的事，屬於 Phase 21 的 router；那裡會先呼叫 `find_folder_by_name` 判斷。資料庫的 `name UNIQUE` 是**最後一道防線**（真的撞到會丟例外），不是主要流程。這樣分工才不會讓 repository 開始管 HTTP 狀態碼。

**名詞**（延續 Phase 15 的名詞表，這裡只補新出現的）：

| 名詞 | 白話解釋 |
|---|---|
| `JOIN` | 把兩張表按照某個對應關係「併起來看」。這裡是「照片的 `folder_id` 對上資料夾的 `id`」 |
| `LEFT JOIN` | 併表時**以左邊那張表為主**：左邊每一列都會出現在結果裡，右邊沒有對應資料就填空。用 `folder LEFT JOIN photo`，空資料夾才不會從清單裡消失 |
| 聚合函式（aggregate） | 把多列壓成一個數字的函式，例如 `count(...)`（數幾列）、`sum(...)`（加總） |
| `count(p.id)` | 數「有對應到照片的列」有幾筆。`LEFT JOIN` 沒配到時 `p.id` 是空的（NULL），而 `count(欄位)` **不數 NULL**，所以空資料夾正確地得到 `0`（如果寫成 `count(*)` 會變成 1，這是常見的坑） |
| `GROUP BY` | 「先分組，再對每一組做聚合」。`GROUP BY f.id` ＝每個資料夾各算一次張數 |
| 只寫 `GROUP BY f.id` 可以嗎 | 可以。`f.id` 是主鍵（primary key），PostgreSQL 知道其他 `f.` 欄位由它唯一決定，所以不必把 `f.name`、`f.description` 全部列進 `GROUP BY` |
| `ORDER BY id DESC` | 依 id **由大到小**排序。id 是自動遞增的，所以「大的＝晚上傳的」，等於「新的在前」 |
| `RETURNING` | PostgreSQL 的貼心語法：INSERT／UPDATE 之後順便把剛寫進去的那一列回傳，不必再查一次 |
| 別名（alias） | SQL 裡的暫時簡稱。`FROM folder f` 之後就能用 `f.name` 代替 `folder.name`，句子短很多 |
| `bigint` | PostgreSQL 的大整數型別。`count(...)` 回的是 `bigint`，psycopg 會自動轉成 Python 的 `int`，不用特別處理 |

---

## ASCII 圖：五個函式，以及之後誰會來拿

```
                       ┌───────────────────────────────────────┐
   Phase 18            │  app/services/vlm_service.py          │
   VLM 推薦資料夾  ────▶│  build_vlm_prompt(folders)            │
                       └────────────────┬──────────────────────┘
                                        │ list_folders()
   Phase 20            ┌────────────────┴──────────────────────┐
   上傳回應 folders ──▶│  app/api/routers/photos.py            │
   Phase 21            │  POST /photos                         │
   PATCH 歸類     ────▶│  PATCH /photos/{id}/folder            │
                       └──┬────────────┬───────────┬───────────┘
                          │            │           │
              get_folder()│  find_folder_by_name() │ create_folder()
                          │            │           │
   Phase 22            ┌──┴────────────┴───────────┴───────────┐
   GET /folders    ───▶│  app/api/routers/folders.py           │
   GET /folders/{id}   │                                       │
                       └──┬─────────────────────┬──────────────┘
                          │ list_folders()      │ list_photos_in_folder()
                          ▼                     ▼
       ╔═══════════════════════════════════════════════════════╗
       ║   app/repositories/photo_repository.py                ║  ★本 phase
       ║   ── 全系統唯一寫 SQL 的地方 ──                        ║
       ║                                                       ║
       ║   list_folders()          → [{id,name,description,    ║
       ║      folder LEFT JOIN photo    is_inbox,photo_count}] ║
       ║      GROUP BY f.id / ORDER BY f.id                    ║
       ║                                                       ║
       ║   get_folder(id)          → 同上鍵 或 None            ║
       ║                                                       ║
       ║   find_folder_by_name(n)  → {id,name,description,     ║
       ║      lower(name)=lower(%s)     is_inbox} 或 None      ║
       ║                                                       ║
       ║   create_folder(n, d)     → 同上鍵（RETURNING）       ║
       ║                                                       ║
       ║   list_photos_in_folder(id) → [{id,text,uploaded_at,  ║
       ║      ORDER BY id DESC              thumbnail_path}]   ║
       ╚═══════════════════════════┬═══════════════════════════╝
                                   │
                   ┌───────────────┴───────────────┐
                   ▼                               ▼
            ┌─────────────┐                 ┌─────────────┐
            │   folder    │◀── folder_id ───│    photo    │
            │ 六筆預設    │    （FK 外鍵）   │             │
            └─────────────┘                 └─────────────┘
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1 先把整份測試檔寫好、跑到**紅**（`AttributeError: module 'app.repositories.photo_repository' has no attribute 'list_folders'`），步驟 2 才實作讓它轉綠。

---

### 步驟 1：建立測試檔 `tests/integration/test_folder_repository.py`（紅）

新檔，完整內容如下：

```python
"""folder 資料層的整合測試：連 PersonalDocAI_test 真測試庫。

對應 design1.md §5（六個預設資料夾）與 §7.4（之後瀏覽端點要用的資料）。
每個測試依 tests/conftest.py 的 autouse fixture reset_tables，
在「兩張表清空＋六筆預設資料夾重播完畢」的乾淨狀態下執行，
所以資料夾 id 一定是 1〜6，可以直接寫死。
"""

from datetime import date, datetime

from app.core import config
from app.repositories import photo_repository as repo

# 種子資料夾的 id（Phase 15 定死的順序）
未分類 = 1
收據 = 2
飲食 = 3


def _vec(value: float = 0.01) -> list[float]:
    return [value] * config.EMBEDDING_DIM


def _insert_photo(category: str | None = "收據", text: str = "在 Target 購買可樂的收據"):
    """插一張照片。category 決定它會被掛到哪個資料夾（Phase 15 的自動歸夾）。"""
    return repo.insert_photo(
        text=text,
        category=category,
        location="Target",
        items=["可樂"],
        content_time=date(2026, 8, 10),
        embedding=_vec(),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )


def test_列出六個預設資料夾():
    folders = repo.list_folders()

    assert [f["name"] for f in folders] == ["未分類", "收據", "飲食", "風景", "文件", "其他"]
    assert [f["id"] for f in folders] == [1, 2, 3, 4, 5, 6]
    # 只有「未分類」是收件箱
    assert [f["is_inbox"] for f in folders] == [True, False, False, False, False, False]
    # description 是給 VLM 看的說明，六筆都不可以是空字串
    assert all(f["description"] for f in folders)
    # 鍵名固定，之後的 Pydantic 模型直接照抄
    assert set(folders[0]) == {"id", "name", "description", "is_inbox", "photo_count"}


def test_資料夾的照片張數會跟著上傳累加():
    _insert_photo(category="收據")
    _insert_photo(category="收據")
    _insert_photo(category="Receipt")  # 清單外 → 自動掛未分類

    張數 = {f["name"]: f["photo_count"] for f in repo.list_folders()}

    assert 張數["收據"] == 2
    assert 張數["未分類"] == 1
    assert 張數["飲食"] == 0  # 空資料夾要出現在清單裡，張數是 0（LEFT JOIN 的重點）


def test_取得單一資料夾():
    _insert_photo(category="收據")

    folder = repo.get_folder(收據)

    assert folder["id"] == 收據
    assert folder["name"] == "收據"
    assert folder["description"] == "發票、消費憑證、購物明細。"
    assert folder["is_inbox"] is False
    assert folder["photo_count"] == 1


def test_取得不存在的資料夾回傳_None():
    assert repo.get_folder(999) is None


def test_依名稱尋找資料夾():
    folder = repo.find_folder_by_name("收據")

    assert folder["id"] == 收據
    assert set(folder) == {"id", "name", "description", "is_inbox"}


def test_依名稱尋找不分大小寫():
    """使用者自建英文資料夾之後，再打小寫也要找得到（Phase 21 擋重名要用）。"""
    建立的 = repo.create_folder("Project X", "課程作業相關的照片")

    assert repo.find_folder_by_name("project x")["id"] == 建立的["id"]
    assert repo.find_folder_by_name("PROJECT X")["id"] == 建立的["id"]


def test_名稱不存在時回傳_None():
    assert repo.find_folder_by_name("不存在的資料夾") is None


def test_建立新資料夾後會出現在清單最後():
    建立的 = repo.create_folder("專案X", "跟課程作業有關的照片")

    assert 建立的["id"] == 7  # 六筆種子之後接著編號
    assert 建立的["name"] == "專案X"
    assert 建立的["description"] == "跟課程作業有關的照片"
    assert 建立的["is_inbox"] is False  # 使用者自建的一律不是收件箱

    folders = repo.list_folders()
    assert len(folders) == 7
    assert folders[-1]["name"] == "專案X"
    assert folders[-1]["photo_count"] == 0


def test_列出資料夾內的照片新的在前():
    第一張 = _insert_photo(text="第一張收據")
    第二張 = _insert_photo(text="第二張收據")
    _insert_photo(category="Receipt", text="不屬於收據資料夾")  # 掛未分類，不該出現

    photos = repo.list_photos_in_folder(收據)

    assert [p["id"] for p in photos] == [第二張["id"], 第一張["id"]]  # id 大的（新的）在前
    assert photos[0]["text"] == "第二張收據"
    assert photos[0]["thumbnail_path"] is None  # 還沒有人寫檔（Phase 17〜19 才做）
    assert set(photos[0]) == {"id", "text", "uploaded_at", "thumbnail_path"}


def test_空資料夾回傳空清單():
    assert repo.list_photos_in_folder(飲食) == []
```

跑一次看它紅：

```bash
pytest tests/integration/test_folder_repository.py -q
```

預期：`10 failed`，錯誤訊息類似 `AttributeError: module 'app.repositories.photo_repository' has no attribute 'list_folders'`。這就是紅燈，正確。

---

### 步驟 2：在 `app/repositories/photo_repository.py` 實作五個函式

#### 2-1　先加一個欄位清單常數

在 Phase 15 加的 `DEFAULT_FOLDERS` **後面**接上：

```python
# 資料夾每次查詢都取回的欄位，固定順序（不含張數——張數只有 list_folders／get_folder 才算）
FOLDER_COLUMNS = "id, name, description, is_inbox"
```

#### 2-2　把五個函式接在 `reset_folders_and_photos()` 後面

（放在 `search_by_metadata` 之前，讓「資料夾相關」的函式聚在一起）

```python
def list_folders() -> list[dict[str, Any]]:
    """全部資料夾，依 id 排序，每筆附上裡面有幾張照片。

    用 LEFT JOIN 而不是 JOIN：以資料夾為主，沒有任何照片的資料夾也要出現在清單裡。
    count(p.id) 不會把 NULL 算進去，所以空資料夾正確地得到 0
    （若寫成 count(*) 會變成 1，那是常見的坑）。
    GROUP BY 只寫 f.id 就夠——f.id 是主鍵，PostgreSQL 知道其他 f. 欄位由它唯一決定。
    """
    sql = f"""
        SELECT f.id, f.name, f.description, f.is_inbox, count(p.id) AS photo_count
        FROM folder f
        LEFT JOIN photo p ON p.folder_id = f.id
        GROUP BY f.id
        ORDER BY f.id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def get_folder(folder_id: int) -> dict[str, Any] | None:
    """依 id 取回一個資料夾（含照片張數）；找不到回 None。"""
    sql = """
        SELECT f.id, f.name, f.description, f.is_inbox, count(p.id) AS photo_count
        FROM folder f
        LEFT JOIN photo p ON p.folder_id = f.id
        WHERE f.id = %(id)s
        GROUP BY f.id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": folder_id})
            return cur.fetchone()


def find_folder_by_name(name: str) -> dict[str, Any] | None:
    """依名稱找資料夾，不分大小寫；找不到回 None。

    lower(name) = lower(輸入)＝兩邊都轉小寫再比，所以 'project x' 找得到 'Project X'。
    中文沒有大小寫，轉了也不變，中文名稱不受影響。
    Phase 21 的「自建資料夾」會先用這個函式擋重名（回 409），
    資料庫的 name UNIQUE 只是最後一道防線。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {FOLDER_COLUMNS} FROM folder WHERE lower(name) = lower(%(name)s::text);",
                {"name": name},
            )
            return cur.fetchone()


def create_folder(name: str, description: str) -> dict[str, Any]:
    """建立一個使用者自訂的資料夾，回傳新的那一列。

    is_inbox 用資料表的預設值 false——收件箱只有系統預設的「未分類」一個，
    使用者建不出第二個（folder_one_inbox 這個部分唯一索引會擋住）。
    重名的判斷交給呼叫端（先用 find_folder_by_name 查），這裡不管 HTTP 狀態碼。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO folder (name, description)
                VALUES (%(name)s, %(description)s)
                RETURNING {FOLDER_COLUMNS};
                """,
                {"name": name, "description": description},
            )
            return cur.fetchone()


def list_photos_in_folder(folder_id: int) -> list[dict[str, Any]]:
    """某個資料夾裡的照片摘要，新的在前（Phase 22 的縮圖牆要用）。

    只取瀏覽需要的四個欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path
                FROM photo
                WHERE folder_id = %(folder_id)s
                ORDER BY id DESC;
                """,
                {"folder_id": folder_id},
            )
            return cur.fetchall()
```

> 💡 `list_folders` 的 SQL 用了 f-string 但其實沒有插值，這是為了和檔案裡其他查詢的寫法一致；若嫌多餘，把 `f"""` 改成 `"""` 也可以，行為完全相同。

---

### 步驟 3：跑測試（綠）

```bash
pytest tests/integration/test_folder_repository.py -q
```

預期：`10 passed`。

再跑全量：

```bash
pytest -q
```

預期：`93 passed`（＝開工基線 **83** ＋ 本 phase 新增 **10**）。既有 83 個測試一個都不准紅——本 phase 只加新函式，沒動任何既有程式碼路徑。

---

### 步驟 4：確認分層沒有破功

```bash
grep -rlnE "SELECT |INSERT INTO|LEFT JOIN|TRUNCATE" app/ --include="*.py"
```

預期輸出**只有一行**：`app/repositories/photo_repository.py`

---

## 驗收清單

- [ ] 開工前實查基線 `pytest -q` ＝ **83 passed**
- [ ] 新檔 `tests/integration/test_folder_repository.py` 已建立，含 **10 個測試**
- [ ] `photo_repository.py` 已加 `FOLDER_COLUMNS` 常數與五個函式：`list_folders`、`get_folder`、`find_folder_by_name`、`create_folder`、`list_photos_in_folder`
- [ ] 五個函式回傳的鍵名與契約完全一致：
  - `list_folders` / `get_folder` → `id, name, description, is_inbox, photo_count`
  - `find_folder_by_name` / `create_folder` → `id, name, description, is_inbox`
  - `list_photos_in_folder` → `id, text, uploaded_at, thumbnail_path`
- [ ] 空資料夾的 `photo_count` 是 `0`（不是 1、也不是整筆消失）
- [ ] `find_folder_by_name` 大小寫不敏感（`project x` 找得到 `Project X`）
- [ ] `list_photos_in_folder` 新的在前（`ORDER BY id DESC`），且**不回傳 embedding**
- [ ] `create_folder` 沒有自己檢查重名（那是 Phase 21 router 的責任）
- [ ] 本 phase **沒有**新增任何端點、沒有改任何回應模型、沒有改 `app/api/`、`app/schemas/`、`app/services/`
- [ ] SQL 仍然只出現在 `app/repositories/photo_repository.py` 一個檔案
- [ ] **全量測試全綠**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：`93 passed`（＝基線 83 ＋ 本 phase 新增 10）

- [ ] **git commit**

  ```bash
  git add app/repositories/photo_repository.py tests/integration/test_folder_repository.py
  git commit -m "feat: Phase 16 資料夾資料層——list_folders／get_folder／find_folder_by_name／create_folder／list_photos_in_folder 五個 repository 函式（LEFT JOIN 算張數、空資料夾為 0、lower() 大小寫不敏感、照片新的在前），+10 tests（累計 93）"
  ```

---

## 常見問題

**Q1：為什麼空資料夾一定要用 `count(p.id)`，不能用 `count(*)`？**
`LEFT JOIN` 配不到照片時，右邊那些欄位會補成 NULL，但**那一列還在**。`count(*)` 是「數列數」，會把這一列算成 1，於是空資料夾變成「有 1 張照片」。`count(欄位)` 則會跳過 NULL，正確得到 0。這是 SQL 最常見的坑之一，測試 `test_資料夾的照片張數會跟著上傳累加` 就是在守它。

**Q2：`find_folder_by_name` 為什麼用 `lower(name) = lower(%s)`，不用 Phase 9 那個 `ILIKE`？**
兩者在這裡效果相同，但語意不一樣：`ILIKE` 是「樣式比對」，使用者名稱裡若剛好有 `%` 或 `_` 會變成萬用字元，拿來擋重名很危險（`專案%` 可能誤判成已存在）。`lower() = lower()` 是老老實實的字串相等比較，適合「這個名字是不是已經被用掉了」。檢索那邊用 `ILIKE` 是為了和既有查詢一致，兩處的選擇各有理由，不要統一。

**Q3：`create_folder` 撞名的話會怎樣？**
資料庫的 `name UNIQUE` 會丟出 `UniqueViolation` 例外，請求變成 500。**這是可接受的最後防線**——正常流程裡 Phase 21 會先用 `find_folder_by_name` 查過，撞名時回 409，根本走不到這裡。不要在 `create_folder` 裡加 try/except 把例外吞掉，那會讓真正的錯誤消失（違反 design.md「500 不吞錯」的原則）。

**Q4：可不可以順便加 `update_folder`／`delete_folder`？**
不可以。design1.md §3「不做」明列：不做刪除照片、不做刪除系統資料夾；§15 也寫了不做資料夾巢狀、標籤多對多。這是 side project，只做用得到的。

**Q5：`list_photos_in_folder` 要不要加分頁（limit／offset）？**
不要。design1.md 沒寫分頁，demo 的資料量是個位數。加分頁就是過度設計。

**Q6：資料夾 id 可以不要寫死在測試裡嗎？**
可以但沒必要。Phase 15 已經把「插入順序即 id 1〜6」定成規格（三處同步：`schema.sql`、`migrate_folders.sql`、`DEFAULT_FOLDERS`），而 `reset_tables` 每個測試都重播一次種子，id 保證穩定。寫死反而讓測試在有人偷改順序時立刻報警。

---

## 完成後的專案狀態

資料層已經完整支援資料夾：讀得出清單與張數、查得到單一資料夾、能依名稱（不分大小寫）尋找、能建立新資料夾、能列出某個資料夾裡的照片摘要。這五個函式是接下來四個 phase（18 的 VLM prompt、20 的上傳回應、21 的歸類端點、22 的瀏覽端點）共同的地基。

系統對外行為仍然一模一樣——API 回應、上傳流程、網頁都還沒變。下一步（Phase 17）要處理「原圖與縮圖怎麼落地成檔案」。測試累計 **93** 個。
