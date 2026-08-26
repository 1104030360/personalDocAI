# Phase 56：建議欄資料庫遷移（D16 的資料層）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候（加索引、加處理狀態欄、加 job_id 欄、順便寫個清理腳本……），答案一律是「不要」。

> 🎯 **一句話目標：** 讓 `photo` 表多出三個「VLM 建議」欄位（實體建議、待辦標題建議、待辦到期日建議），並讓 repository 寫得進、讀得回——**但這一個 phase 的值一律是空的**，真正把 VLM 的建議餵進去是 Phase 61 的事。

**為什麼要做這個：**

現在（增量四之前）的流程是這樣的：使用者上傳一張照片，伺服器**同步**看圖、回 201，回應裡一次帶回「建議資料夾」「建議實體」「建議待辦」三份東西，前端立刻拿去畫三個彈窗。**建議只活在那一次 HTTP 回應裡，沒有存進資料庫。**

增量五（design5.md）把上傳改成非同步：HTTP 立刻回 **202**「我收下了」，看圖是稍後由背景的 worker 做的。**那一刻已經沒有人在等這個回應了**——瀏覽器早就拿到 202 走掉了。如果建議仍然只活在回應裡，它會直接蒸發：之後使用者到「待決定」頁點開那張照片，實體彈窗只剩「再建議一個」，待辦彈窗**永遠不會出現**（因為沒有人知道 VLM 當初建議了什麼標題）。

所以 design5.md 的 D16 決定：**worker 成功寫入照片時，順手把三個建議也寫進 `photo` 那一列**。之後待決定頁開窗時直接從資料庫讀，不必再看一次圖。

這個 phase 就是把「那三個欄位」挖出來。挖好之後它們會是空的（NULL），沒有任何人寫值進去——這是刻意的：**資料庫改結構與程式改行為分開兩個 phase 做**，這樣萬一出事，你一眼就知道是哪一邊壞的。

現有的 `suggested_category`（Phase 35 加的「建議資料夾」）**完全不動**，三個新欄位和它並排。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 遷移（migration） | 在**不清空既有資料**的前提下，把資料庫的結構改成新版本的腳本。正式庫有真實照片（2026-08-25 實查 **52** 列），不能砍掉重建，只能走遷移 |
| 冪等（idempotent） | 「同一個動作做兩次，結果跟做一次一樣」。這支遷移腳本設計成可以重複執行：跑第二次不報錯、也不會把資料改壞。做法是每一句都寫成「已經有了就跳過」 |
| `ADD COLUMN IF NOT EXISTS` | PostgreSQL 的語法：「幫這張表加一欄，但如果同名的欄位已經存在就安靜跳過、不要報錯」。冪等就靠它 |
| `TEXT` | PostgreSQL 的字串型別，長度沒有上限。本專案所有文字欄位都用它 |
| `DATE` | PostgreSQL 的**日期**型別：只有年月日，沒有時分秒、沒有時區。`2026-08-21` 就是 `2026-08-21`，不會變成 `2026-08-21 00:00:00+08` |
| `TIMESTAMP` / `timestamptz` | PostgreSQL 的**時間點**型別：年月日**加上**時分秒（`timestamptz` 還帶時區）。本專案的 `uploaded_at` 用它，`content_time`／`due_date` 則不用 |
| NULL | 資料庫的「這一格沒有值」。注意它不等於空字串 `''`，也不等於 0。三個新欄位的既有列全部會是 NULL，語意就是「沒有建議」 |
| 可選參數（optional parameter） | Python 函式定義時就給了預設值的參數，呼叫時可以不寫。`suggested_entity: str \| None = None` 就是：不傳就當作 None |
| 關鍵字參數（keyword-only） | 函式定義裡 `*` 後面的參數，呼叫時**一定要寫參數名字**。`insert_photo(*, text=..., category=...)` 就是這種。好處是呼叫端一看就知道每個值是什麼，不會傳錯順序 |
| 呼叫端（caller） | 「呼叫這個函式的那一段程式」。本文件說「舊呼叫端」時，指的是 `app/api/routers/photos.py` 與一大批既有測試 |
| `pg_dump` / `pg_restore` | PostgreSQL 內建的備份／還原工具。`pg_dump` 把整個資料庫倒成一個檔案 |
| autouse fixture | pytest 的「每個測試都自動套用的前置／後置動作」，不必在測試函式的參數列寫它的名字。本專案的 `reset_tables`、`wire_fake_ai`、`isolated_data_dir` 都是 |
| `TRUNCATE` | 一次清空整張表（比逐列 `DELETE` 快很多）。只給測試用；`reset_tables` 每個測試都會跑一次 |

---

## 1. 對應 design5.md 章節

- **D16「建議隨入庫落庫」**（§1 決策表）：worker 成功 INSERT 時，除既有 `suggested_category` 外，一併寫入實體建議與待辦建議（標題／到期日，可空）。仍只是建議，人按確認才寫 `entity`／`photo_entity`／`task`。
- **§1.1 推翻的舊決策**：`Phase 30「實體／待辦建議只出現在上傳回應」→ 建議寫進 photo 列，待決定開窗再讀`；`design3 §2.1「建議不持久化」→ 建議改落庫`。
- **§4.2「何時才有 `photo` 列」**：入庫成功後另外寫入 D16 的建議欄（資料夾／實體／待辦）。
- **§6.2 `/ui/pending.html`**：階段丙起待決定必須走完整三關，建議從 D16 的欄位讀，**不必再看一次圖**。
- **§11「會動到的檔」**：`db/migrate_design5.sql`（冪等 `ALTER photo`）、`db/schema.sql`（與遷移對齊，測庫重建用）。
- **§11 末段的「不改」**：`photo` 表**只加建議欄**，不加處理狀態、不加 job_id（冪等靠 JobStore 的 `photo_ids`）。
- 契約備忘 **§4**（欄位表）與 **§2.1**（新建檔清單：`db/migrate_design5.sql` 由本 phase 建）。
  （⚠ 2026-08-25 核對：「契約備忘」是規劃階段的工作文件、未入庫。本 phase 需要的欄名與型別
  已逐字寫死在步驟 2／3，驗收一律以本檔內嵌內容為準，不依賴那份文件。）

---

## 2. 前置條件

**依賴的 phase：無。** 本 phase 是增量五的地基之一，可以跟 Phase 52〜55（階段甲的前端）平行做，彼此不衝突。

開工前**實查**基線（不要憑印象，一定要真的跑）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 資料庫容器活著嗎？db 那一列要是 Up (healthy)，否則測試會是一整片連線錯誤
docker compose ps

# ② 測試基線（2026-08-25 實測為 405 passed ＋ 0 skipped）
pytest -q
```

預期最後一行：`405 passed`（若你是在 Phase 52〜55 之後才做這一支，數字會比 405 大——**以你當下實查到的數字為準**，本文件之後一律用「基線」稱呼它）。

**⚠️ 絕對不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。`tests/conftest.py` 的 autouse `reset_tables` 每個測試都會 `TRUNCATE` 同一個測試庫，兩份同時跑會互相清掉對方的資料，症狀是**大量看似隨機的** 404「找不到照片」與 `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣。

資料庫連線（2026-08-24 起 PostgreSQL 跑在 Docker container）：

```bash
# ~/.zshrc 已設好 PGPORT=5433、PGUSER=postgres、PGHOST=127.0.0.1，互動 shell 可以簡寫
psql -d PersonalDocAI        # 正式庫
psql -d PersonalDocAI_test   # 測試庫

# 腳本裡建議把參數寫明白：
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI
```

---

## 3. 範圍

### 做

1. 新建 `db/migrate_design5.sql`：冪等地幫 `photo` 表加三欄。
2. `db/schema.sql` 同步加同樣三欄（測試庫重建用）。
3. `app/repositories/photo_repository.py`：
   - `PHOTO_COLUMNS` 加三個欄名；
   - `insert_photo()` 加三個**可選**關鍵字參數，預設 `None`；
   - `list_photos_in_folder()` 的 `SELECT` 多帶三個欄。
4. 更新一顆既有測試的鍵集合斷言（五鍵 → 八鍵），新增五顆測試。
5. 正式庫備份 → 遷移 → **跑第二次證明冪等** → 核對。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 讓任何呼叫端真的傳值進三個新欄 | 那是 **Phase 61**（worker INSERT 時一併寫）。本 phase 的驗收條件就是「值一律是 None」——先把地基挖好，行為改動另外一個 phase 才做，出事時一眼看得出是哪一邊 |
| 改 `GET /folders/{folder_id}` 的回應（五鍵 → 八鍵） | 那也是 **Phase 61**。本 phase 只讓 repository 多回三個鍵，router 的 `PhotoSummary` 不動，所以 API 回應**逐位元不變** |
| 幫新欄位加索引 | 沒有任何查詢會用它們當條件（它們只被「用 id 撈某一列」時順便讀出來）。索引要維護成本，不養用不到的 |
| 幫 `photo` 加「處理狀態」欄或 `job_id` 欄 | design5 §11 明文禁止。進度狀態住在 JobStore（Phase 57），冪等靠 JobStore 的 `photo_ids` |
| 幫新欄位加 `NOT NULL` 或預設值 | 既有各列（2026-08-25 實查 52 列）本來就沒有建議，NULL 才是誠實的語意（「沒有建議」）。加了 `NOT NULL DEFAULT ''` 會讓「沒建議」與「建議是空字串」分不出來 |
| 動 `suggested_category` | Phase 35 加的，行為完全正確，三個新欄位跟它並排就好 |
| 改 `reset_folders_and_photos()` 的 `TRUNCATE` 清單 | 本 phase **沒有新增任何表**，只加欄位。`TRUNCATE photo …` 本來就會把整列（含新欄位）清掉 |
| 拿 `db/schema.sql` 打正式庫 | 那支檔案開頭是 `DROP TABLE`，會把 52 張真照片全部刪掉。正式庫**只准**走遷移腳本 |
| 建 `entity`／`task` 的實際資料 | 建議 ≠ 落庫。人在彈窗按下「釘上」「建立待辦」才會寫那兩張表（design3 D12／D13 不變） |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1 先把測試寫好、跑到**紅**；步驟 2〜5 才動實作讓它轉綠。每一步做完打勾。

### 步驟 1：先寫測試（紅）

#### 1-1　`tests/integration/test_photo_repository.py`：在**檔案最後面**接上四顆新測試

- [ ] 打開 `/Users/linjunting/personalDocAI/tests/integration/test_photo_repository.py`，在檔案結尾貼上：

```python


# ---------- Phase 56 追加：D16 的三個建議欄（實體／待辦標題／待辦到期日）----------
# 本 phase 只挖欄位，值一律由呼叫端決定；真的把 VLM 建議餵進來是 Phase 61 的事。


def test_不傳建議參數時三個建議欄都是空的():
    """舊呼叫端相容性：既有的每一處 insert_photo 都沒有傳新參數，不可以壞掉。

    順便也證明「reset_tables 重播六筆種子之後，新寫進去的照片三個建議欄仍是 NULL」——
    autouse 的 reset_tables 每個測試都會 TRUNCATE 再重播資料夾種子，
    種子只重播 folder 表，photo 是空的，所以這裡插進去的是全新的一列。
    NULL（Python 這邊看到的是 None）＝「沒有建議」，正是舊照片與本 phase 該有的語意。
    """
    row = _insert_sample()

    assert row["suggested_entity"] is None
    assert row["suggested_task_title"] is None
    assert row["suggested_task_due"] is None


def test_insert_photo_寫得進三個建議欄():
    """Phase 61 的 worker 會這樣呼叫；本 phase 先把管線接通、確認寫得進去。"""
    row = _insert_sample(
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交 Project 2 報告",
        suggested_task_due=date(2026, 8, 21),
    )

    assert row["suggested_entity"] == "我的 MacBook"
    assert row["suggested_task_title"] == "繳交 Project 2 報告"
    assert row["suggested_task_due"] == date(2026, 8, 21)


def test_fetch_photo_讀得回三個建議欄():
    """insert 的 RETURNING 與 fetch 的 SELECT 共用 PHOTO_COLUMNS，兩邊鍵名保證一致。"""
    inserted = _insert_sample(
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交 Project 2 報告",
        suggested_task_due=date(2026, 8, 21),
    )

    assert repo.fetch_photo(inserted["id"]) == inserted


def test_到期日存的是日期不是時間戳():
    """欄位型別必須是 DATE（只有年月日），不是 TIMESTAMP。

    理由：這個建議之後會被 Phase 70 帶去 POST /photos/{id}/task，
    而 task.due_date 本來就是 DATE。兩邊型別一致，才不會出現
    「建議是 2026-08-21，建成待辦卻變成 2026-08-21 00:00:00+08」這種漂移。
    date 是 datetime 的父類別，所以要用 type() 精確比對，不能用 isinstance。
    """
    row = _insert_sample(suggested_task_due=date(2026, 8, 21))

    assert type(row["suggested_task_due"]) is date
```

> 📌 檔案最上方的 `from datetime import date, datetime, timezone` 已經 import 過 `date`，不必再加。

#### 1-2　`tests/integration/test_folder_repository.py`：改一顆、加一顆

- [ ] 打開 `/Users/linjunting/personalDocAI/tests/integration/test_folder_repository.py`，找到 `test_列出資料夾內的照片新的在前` 裡的這段（大約在第 121 行）：

```python
    # Phase 35 起由四鍵變五鍵：多的 suggested_category 讓待決定分頁畫得出選項①
    assert set(photos[0]) == {
        "id", "text", "uploaded_at", "thumbnail_path", "suggested_category"
    }
```

**整段換成**：

```python
    # Phase 35 起由四鍵變五鍵（suggested_category 讓待決定分頁畫得出選項①）；
    # Phase 56 起再變八鍵：D16 的三個建議欄，讓待決定分頁不必再看一次圖
    # 就畫得出實體彈窗的選項①與待辦彈窗的預填值（design5.md §6.2）。
    # ★ 這是 repository 這一層的鍵；GET /folders/{id} 的回應仍是五鍵，
    #   PhotoSummary 只挑它要的那幾個——router 改成八鍵是 Phase 61 的事。
    assert set(photos[0]) == {
        "id", "text", "uploaded_at", "thumbnail_path", "suggested_category",
        "suggested_entity", "suggested_task_title", "suggested_task_due",
    }
```

- [ ] 在同一個檔案的**最後面**接上一顆新測試：

```python


def test_資料夾內照片摘要帶得出三個建議欄():
    """Phase 61 的 GET /folders/{inbox} 會靠這三個鍵畫實體／待辦彈窗（design5 §6.2）。

    本 phase 只驗「repository 這一層讀得出來」；router 還沒開始外送它們。
    """
    照片 = repo.insert_photo(
        text="MacBook 上打開的 Project 2 報告",
        category="收據",
        location=None,
        items=[],
        content_time=None,
        embedding=_vec(),          # 檔案上方既有的小工具，回一條 1024 維的假向量
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交 Project 2 報告",
        suggested_task_due=date(2026, 8, 21),
    )

    摘要 = repo.list_photos_in_folder(收據)[0]

    assert 摘要["id"] == 照片["id"]
    assert 摘要["suggested_entity"] == "我的 MacBook"
    assert 摘要["suggested_task_title"] == "繳交 Project 2 報告"
    assert 摘要["suggested_task_due"] == date(2026, 8, 21)
```

> 📌 **這顆新測試不需要新增任何 import。** `test_folder_repository.py` 檔頭已經有 `from datetime import date, datetime` 與 `from app.core import config`（2026-08-25 實查），`收據 = 2` 是檔案裡既有的資料夾 id 常數，`_vec()` 是既有的假向量小工具——全部直接沿用就好，**不要重複 import**。
>
> 為什麼不用檔案裡既有的 `_insert_photo()` 小工具？因為它沒有 `**overrides` 這種轉發機制（參數是寫死的 `category` 與 `text` 兩個），塞不進三個新參數。與其去改那個被十幾顆測試共用的小工具，不如這一顆直接呼叫 `repo.insert_photo`。

#### 1-3　跑一次，看它紅

- [ ] 執行：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_photo_repository.py tests/integration/test_folder_repository.py -q
```

預期：**6 failed**（同兩個檔案裡的其餘既有測試照常綠，passed 的數字不必理會）。六顆的紅法各有不同，對一下才算真的看懂紅燈：

| 紅的測試 | 紅字關鍵句 | 為什麼是這種紅 |
|---|---|---|
| `test_insert_photo_寫得進三個建議欄`、`test_fetch_photo_讀得回三個建議欄`、`test_到期日存的是日期不是時間戳` | `TypeError: insert_photo() got an unexpected keyword argument 'suggested_entity'`（第三顆是 `'suggested_task_due'`） | `insert_photo()` 的參數列還沒有新參數 |
| `test_不傳建議參數時三個建議欄都是空的` | `KeyError: 'suggested_entity'` | 這顆**沒**傳新參數，所以插得進去；但回傳列裡還沒有新欄位，取值就爆 |
| `test_列出資料夾內的照片新的在前`（改過的那顆） | `AssertionError`：五個鍵的集合 ≠ 八個鍵的集合 | `list_photos_in_folder` 的 `SELECT` 還沒多帶三欄 |
| `test_資料夾內照片摘要帶得出三個建議欄` | 與第一列相同的 `TypeError` | 直接呼叫 `repo.insert_photo` 帶了新參數 |

**這就是正確的紅燈。**

---

### 步驟 2：新建 `db/migrate_design5.sql`

- [ ] 建立新檔 `/Users/linjunting/personalDocAI/db/migrate_design5.sql`，內容如下（整份貼上）：

```sql
-- 正式庫（PersonalDocAI）遷移：增量五 design5.md D16「建議隨入庫落庫」。
-- photo 表加三個「VLM 建議」欄位，與 Phase 35 加的 suggested_category 並排。
--
-- 為什麼需要它：增量五把上傳改成非同步（HTTP 立刻回 202，看圖交給背景 worker）。
-- 建議在 worker 跑完時產生，那時已經沒有人在等 HTTP 回應了，
-- 建議如果不落庫就會蒸發——待決定頁開窗時就再也拿不到實體建議與待辦建議
-- （待辦彈窗會從此沒有入口，design5.md D16）。
--
-- 特性：冪等（idempotent）＝可重複執行。跑第二次不會出錯，也不會改壞任何資料。
--       每一句都是 ADD COLUMN IF NOT EXISTS：欄位已經在了就安靜跳過。
-- 日期：2026-08-25（Phase 56）
-- 用法：psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_design5.sql
--
-- ⚠️ 測試庫不要用這一份。測試庫直接重建：
--    psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql
-- ⚠️ 這支腳本只加欄位，不改也不刪任何既有資料；既有列的三個新欄位一律是 NULL。

-- ① VLM 建議的實體名稱。
--    已經在程式層 clamp 過（只會是現有 entity 清單裡的名字之一）；
--    清單外或都不像 → NULL。實體沒有「未分類」這種保底（design3.md D12）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_entity text;

-- ② VLM 建議的待辦標題。NULL ＝這張照片看起來沒有要做的事，
--    待決定頁因此不會跳出待辦彈窗（沿用現在上傳鏈的「空關不跳」規則）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_task_title text;

-- ③ VLM 建議的到期日。
--    型別刻意用 date 不用 timestamp：它之後會被帶去 POST /photos/{id}/task，
--    而 task.due_date 本來就是 date。兩邊一致才不會出現
--    「建議 2026-08-21、建成待辦變 2026-08-21 00:00:00+08」這種漂移。
--    NULL ＝有這件事要做、但推不出期限（仍然是一筆合法的待辦建議）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_task_due date;

-- 刻意不做的事（design5.md §11 明文，別手滑加上去）：
--   * 不加索引：沒有任何查詢拿它們當條件，只在撈某一列時順便讀出來。
--   * 不加 NOT NULL／DEFAULT：既有各列本來就沒有建議，NULL 才是誠實的語意。
--   * 不加「處理狀態」欄、不加 job_id 欄：進度住在 JobStore（Phase 57），
--     崩潰重送的冪等靠 JobStore 的 photo_ids，不靠 photo 表。
```

---

### 步驟 3：`db/schema.sql` 同步加同樣三欄

> ⚠️ **`db/schema.sql` 的第 8〜13 行是 `DROP TABLE`。** 這支檔案是「砍掉重建」用的，**只能打測試庫**。拿它打正式庫＝52 張真照片當場消失，而且沒有 undo。

- [ ] 打開 `/Users/linjunting/personalDocAI/db/schema.sql`，找到 `CREATE TABLE photo (...)` 裡的最後一欄 `suggested_category text`（大約第 53〜56 行）：

```sql
  -- 上傳當下 VLM 建議的資料夾名稱（clamp 過，一定是 folder.name 之一）。Phase 35 加。
  -- NULL ＝「沒有建議」：clamp 成「未分類」的、以及遷移進來的舊照片都是 NULL，
  -- 定案時一律不算糾錯（沒建議不是猜錯）。這欄不影響照片實際歸屬（那是 folder_id）。
  suggested_category text
);
```

**整段換成**（注意 `suggested_category` 後面多了一個逗號）：

```sql
  -- 上傳當下 VLM 建議的資料夾名稱（clamp 過，一定是 folder.name 之一）。Phase 35 加。
  -- NULL ＝「沒有建議」：clamp 成「未分類」的、以及遷移進來的舊照片都是 NULL，
  -- 定案時一律不算糾錯（沒建議不是猜錯）。這欄不影響照片實際歸屬（那是 folder_id）。
  suggested_category text,
  -- ---------- 增量五 D16：建議隨入庫落庫（Phase 56）----------
  -- 三欄與 db/migrate_design5.sql 必須完全一致，改一邊就要改另一邊。
  -- 上傳改成非同步（202）之後建議不再回給前端，只能存在照片上，
  -- 待決定頁開窗時才讀得到（design5.md D16、§6.2）。
  suggested_entity     text,   -- VLM 建議的實體名稱（clamp 過；都不像 → NULL）
  suggested_task_title text,   -- VLM 建議的待辦標題（NULL ＝沒有待辦，待辦窗不跳）
  suggested_task_due   date    -- VLM 建議的到期日（型別對齊 task.due_date，只有年月日）
);
```

---

### 步驟 4：重建測試庫

- [ ] 執行：

```bash
cd /Users/linjunting/personalDocAI
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql
```

預期輸出（`NOTICE` 都正常：pgvector 早就裝好了、有些表本來就存在）：

```
NOTICE:  extension "vector" already exists, skipping
CREATE EXTENSION
DROP TABLE
DROP TABLE
DROP TABLE
DROP TABLE
DROP TABLE
DROP TABLE
CREATE TABLE
CREATE INDEX
INSERT 0 6
CREATE TABLE
CREATE INDEX
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
```

- [ ] 確認三個新欄位真的在，而且型別對：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='photo' AND column_name LIKE 'suggested%' ORDER BY column_name;"
```

預期：

```
     column_name      | data_type
----------------------+-----------
 suggested_category   | text
 suggested_entity     | text
 suggested_task_due   | date
 suggested_task_title | text
(4 筆資料)
```

**`suggested_task_due` 一定要是 `date`，不是 `timestamp without time zone`。** 對不上就回頭看步驟 3 是不是打錯型別。

---

### 步驟 5：改 `app/repositories/photo_repository.py`

#### 5-1　`PHOTO_COLUMNS` 加三個欄名

- [ ] 找到檔案上方（約第 22 行）的：

```python
PHOTO_COLUMNS = (
    "id, text, category, folder_id, location, items, content_time, uploaded_at, "
    "original_path, thumbnail_path, content_type, suggested_category"
)
```

**換成**：

```python
PHOTO_COLUMNS = (
    "id, text, category, folder_id, location, items, content_time, uploaded_at, "
    "original_path, thumbnail_path, content_type, suggested_category, "
    "suggested_entity, suggested_task_title, suggested_task_due"
)
```

> 📌 這一份清單同時被 `insert_photo` 的 `RETURNING`、`fetch_photo` 的 `SELECT`、`search_by_metadata`、`search_by_vector`、`update_photo_folder` 共用，所以改常數就等於五個地方一起改好了。`test_fetch_photo_returns_row` 直接拿 insert 與 fetch 的結果做相等比較，靠的就是這一點。

#### 5-2　`insert_photo()` 加三個可選參數

- [ ] 找到 `def insert_photo(` 的參數列（約第 62〜72 行），把：

```python
def insert_photo(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: date | None,
    embedding: list[float],
    uploaded_at: datetime | None = None,
    suggested_category: str | None = None,
) -> dict[str, Any]:
```

**換成**：

```python
def insert_photo(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: date | None,
    embedding: list[float],
    uploaded_at: datetime | None = None,
    suggested_category: str | None = None,
    suggested_entity: str | None = None,
    suggested_task_title: str | None = None,
    suggested_task_due: date | None = None,
) -> dict[str, Any]:
```

- [ ] 在同一個函式的 docstring 最後面（`只是「當時猜了什麼」的存根；沒有建議就留 None，定案時一律不算糾錯。` 那句之後、`"""` 之前）補上一段：

```python
    suggested_entity／suggested_task_title／suggested_task_due＝增量五 D16 的三個建議。
    與 suggested_category 同一個性質：只是「VLM 當時猜了什麼」的存根，
    不代表照片真的釘了實體、也不代表真的有一筆待辦——那兩件事要人在彈窗按下確認，
    分別寫進 photo_entity 與 task 兩張表（design3.md D12／D13 不變）。
    為什麼要存：上傳改成非同步（202）之後，看圖是背景 worker 做的，
    那時已經沒有人在等 HTTP 回應，建議不落庫就會蒸發（design5.md D16）。
    ★ Phase 56 的每一個呼叫端都不傳這三個，所以值一律是 None；
      真的把 VLM 的建議餵進來是 Phase 61 的事。
```

#### 5-3　`insert_photo()` 的 SQL 與 params 加三欄

- [ ] 把 `insert_photo` 裡的 SQL（約第 90〜106 行）：

```python
    sql = f"""
        INSERT INTO photo (
            text, category, folder_id, location, items, content_time, uploaded_at,
            embedding, suggested_category
        )
        VALUES (
            %(text)s, %(category)s,
            COALESCE(
                (SELECT id FROM folder WHERE lower(name) = lower(%(category)s::text)),
                (SELECT id FROM folder WHERE is_inbox)
            ),
            %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector, %(suggested_category)s
        )
        RETURNING {PHOTO_COLUMNS};
    """
```

**換成**：

```python
    sql = f"""
        INSERT INTO photo (
            text, category, folder_id, location, items, content_time, uploaded_at,
            embedding, suggested_category,
            suggested_entity, suggested_task_title, suggested_task_due
        )
        VALUES (
            %(text)s, %(category)s,
            COALESCE(
                (SELECT id FROM folder WHERE lower(name) = lower(%(category)s::text)),
                (SELECT id FROM folder WHERE is_inbox)
            ),
            %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector, %(suggested_category)s,
            %(suggested_entity)s, %(suggested_task_title)s, %(suggested_task_due)s
        )
        RETURNING {PHOTO_COLUMNS};
    """
```

- [ ] 把緊接在下面的 `params` 字典：

```python
    params = {
        "text": text,
        "category": category,
        "location": location,
        "items": items,
        "content_time": content_time,
        "uploaded_at": uploaded_at,
        "embedding": to_vector_literal(embedding),
        "suggested_category": suggested_category,
    }
```

**換成**：

```python
    params = {
        "text": text,
        "category": category,
        "location": location,
        "items": items,
        "content_time": content_time,
        "uploaded_at": uploaded_at,
        "embedding": to_vector_literal(embedding),
        "suggested_category": suggested_category,
        "suggested_entity": suggested_entity,
        "suggested_task_title": suggested_task_title,
        "suggested_task_due": suggested_task_due,
    }
```

> ⚠️ **欄位名清單、`VALUES` 的佔位符、`params` 三處必須同時改。** 只改 `PHOTO_COLUMNS` 而忘了改 `INSERT INTO photo (...)` 的欄位清單，症狀特別討人厭：測試會「綠得像是成功了」（`RETURNING` 讀得回三個 `None`），但值其實根本沒寫進去——直到 Phase 61 才會發現。步驟 1 的 `test_insert_photo_寫得進三個建議欄` 就是專門擋這件事的。

#### 5-4　`list_photos_in_folder()` 的 SELECT 多帶三欄

- [ ] 找到 `def list_photos_in_folder(` （約第 343 行），把整個函式：

```python
def list_photos_in_folder(folder_id: int) -> list[dict[str, Any]]:
    """某個資料夾裡的照片摘要，新的在前（Phase 22 的縮圖牆要用）。

    只取瀏覽需要的五個欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。

    ★ Phase 35 從四欄變五欄：多的 suggested_category 是給「待決定」分頁畫選項①用的
      （design1「摘要恰四鍵」由 phase-35 明文修訂）。有了它，待決定分頁就能拿出
      上傳當下那一筆建議，不必為了畫①再看一次圖。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path, suggested_category
                FROM photo
                WHERE folder_id = %(folder_id)s
                ORDER BY id DESC;
                """,
                {"folder_id": folder_id},
            )
            return cur.fetchall()
```

**換成**：

```python
def list_photos_in_folder(folder_id: int) -> list[dict[str, Any]]:
    """某個資料夾裡的照片摘要，新的在前（Phase 22 的縮圖牆要用）。

    只取瀏覽需要的欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。

    ★ Phase 35 從四欄變五欄：多的 suggested_category 是給「待決定」分頁畫選項①用的
      （design1「摘要恰四鍵」由 phase-35 明文修訂）。有了它，待決定分頁就能拿出
      上傳當下那一筆建議，不必為了畫①再看一次圖。
    ★ Phase 56 再從五欄變八欄：D16 的三個建議欄。理由完全相同，只是對象換成
      實體彈窗的選項①與待辦彈窗的預填值——上傳改 202 之後建議不再回給前端，
      待決定頁只能從這裡讀（design5.md D16、§6.2）。
      本 phase 三個值一律是 NULL；真的餵值進去是 Phase 61。
    ★ 注意分層：這是 repository 回的鍵。GET /folders/{id} 的回應現在仍是五鍵，
      因為 schemas/folder.py 的 PhotoSummary 只挑它要的那幾個。
      把回應也加成八鍵是 Phase 61 的事，本 phase 的 API 回應逐位元不變。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path, suggested_category,
                       suggested_entity, suggested_task_title, suggested_task_due
                FROM photo
                WHERE folder_id = %(folder_id)s
                ORDER BY id DESC;
                """,
                {"folder_id": folder_id},
            )
            return cur.fetchall()
```

---

### 步驟 6：跑測試看它轉綠

- [ ] 先跑改動到的兩個檔案：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_photo_repository.py tests/integration/test_folder_repository.py -v
```

預期：**全綠**，其中步驟 1 寫的六顆（四顆新的 photo_repository ＋ 一顆改過的 ＋ 一顆新的 folder_repository）都是 `PASSED`。

- [ ] 再跑全量：

```bash
pytest -q
```

預期：**基線 ＋ 5**（本 phase 淨新增五顆測試；那顆五鍵改八鍵的是「改」不是「加」）。若基線是 405，這裡就是 `410 passed`。

**既有測試一顆都不准紅。** 紅了就代表改到了對外行為——最可能的兩個原因：
1. `test_folders_endpoint.py` 的五鍵斷言紅了 → 你不小心也改了 `app/schemas/folder.py` 的 `PhotoSummary`。那是 Phase 61 的事，改回來。
2. `test_fetch_photo_returns_row` 紅了 → `PHOTO_COLUMNS` 與 `INSERT INTO photo (...)` 的欄位清單沒對齊。

---

### 步驟 7：備份正式庫（**動遷移之前一定要做**）

- [ ] **先記下遷移前的照片數**（步驟 8 的最後一關要拿這個數字來對，沒抄就對不了）：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "SELECT count(*) FROM photo;"
```

把印出來的數字抄下來。2026-08-24 增量四 G2 核對時是 **37**；之後若又上傳過照片，這裡會更大——**一律以你現在抄下來的為準**，本文件後面的「37」都只是示意。

正式庫裡是真實照片，遷移沒有反向腳本。先倒一份出來留著。**兩種寫法擇一即可**：

- [ ] **方式 A（在容器裡倒，再抓出來）**：這一份是純文字 SQL（副檔名雖然叫 `.dump`），要灌回去是用 `psql -f`，不是 `pg_restore`。

```bash
cd /Users/linjunting/personalDocAI
docker compose exec db pg_dump -U postgres -d PersonalDocAI --no-owner --no-acl \
  -f /tmp/PersonalDocAI.dump
docker compose cp db:/tmp/PersonalDocAI.dump ~/PersonalDocAI-backup-增量五前.dump
```

- [ ] **方式 B（在 host 倒）**：這一份有 `-Fc`（自訂格式），灌回去用 `pg_restore`。

```bash
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-增量五前.dump
```

- [ ] 確認檔案真的產出來了、而且不是 0 bytes：

```bash
ls -lh ~/PersonalDocAI-backup-增量五前.dump
```

> ⚠️ **上面兩種都只備份到資料庫，沒有備份照片檔。** `data/` 裡是約 54 MB 的原圖與縮圖（50 張照片的 `original_path` 指著它），而它**不入版控**（`.gitignore` 擋掉了）＝全世界只有一份，連 `git clean -xdf` 都會把它清掉。資料庫還原回來但 `data/` 沒了的話，照片列還在、縮圖與大圖全變 404。真的在意就一起帶上：
>
> ```bash
> cd /Users/linjunting/personalDocAI
> tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
> ```

---

### 步驟 8：正式庫遷移 ＋ 跑第二次證明冪等

- [ ] 第一次執行：

```bash
cd /Users/linjunting/personalDocAI
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_design5.sql
```

預期輸出（三行，沒有任何 `ERROR`）：

```
ALTER TABLE
ALTER TABLE
ALTER TABLE
```

- [ ] **第二次執行同一支腳本**（這就是「冪等」的驗證：同一個動作做兩次，結果跟做一次一樣）：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_design5.sql
```

預期輸出（多了三行 `NOTICE`，代表欄位已存在所以跳過；**仍然沒有任何 `ERROR`**）：

```
NOTICE:  column "suggested_entity" of relation "photo" already exists, skipping
ALTER TABLE
NOTICE:  column "suggested_task_title" of relation "photo" already exists, skipping
ALTER TABLE
NOTICE:  column "suggested_task_due" of relation "photo" already exists, skipping
ALTER TABLE
```

- [ ] 核對欄位型別：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
  -c "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='photo' AND column_name LIKE 'suggested%' ORDER BY column_name;"
```

預期：

```
     column_name      | data_type | is_nullable
----------------------+-----------+-------------
 suggested_category   | text      | YES
 suggested_entity     | text      | YES
 suggested_task_due   | date      | YES
 suggested_task_title | text      | YES
(4 筆資料)
```

- [ ] 核對既有資料**完全沒被動到**：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
  -c "SELECT count(*) AS 照片數, count(suggested_entity) AS 有實體建議的, count(suggested_task_title) AS 有待辦建議的, count(suggested_task_due) AS 有到期日的 FROM photo;"
```

預期（`count(欄位)` 不會把 NULL 算進去，所以後三個都是 0；照片數以 37 示意）：

```
 照片數 | 有實體建議的 | 有待辦建議的 | 有到期日的
--------+--------------+--------------+------------
     37 |            0 |            0 |          0
(1 筆資料)
```

**照片數要跟步驟 7 開頭抄下來的那個數字一模一樣。** 少了就立刻停手、用步驟 7 的備份還原。

---

### 步驟 9：git commit

> ⚠ **依總覽 §7 鐵律 12：commit 節奏由產品負責人決定，他沒指示前先不 commit——本步驟此時跳過**，
> 下面的指令與訊息文字留著備用（將來他說「commit」時直接照抄）。git 驗收改用
> 「與開工前 `git status` 快照相減」的寫法。（2026-08-25 核對時補上這段前提。）

- [ ] 執行（**僅在產品負責人指示 commit 時**）：

```bash
cd /Users/linjunting/personalDocAI
git add db/migrate_design5.sql db/schema.sql app/repositories/photo_repository.py \
        tests/integration/test_photo_repository.py tests/integration/test_folder_repository.py
git commit -m "feat: Phase 56 建議欄資料庫遷移——photo 加 suggested_entity/suggested_task_title/suggested_task_due 三欄（migrate_design5.sql 冪等、正式庫已跑兩次證明；schema.sql 同步），insert_photo 加三個可選參數、list_photos_in_folder 五鍵→八鍵；值一律 None（餵值是 Phase 61），API 回應逐位元不變，+5 tests"
```

---

## 5. ASCII 圖

### 圖一：`photo` 表改版前後的欄位對照

```text
【改版前（增量四完成、Phase 51 之後）】

  ┌──────────────────────── photo ────────────────────────┐
  │ id                 integer  IDENTITY PK               │
  │ text               text     NOT NULL                  │
  │ category           text                               │
  │ folder_id          integer  NOT NULL → folder(id)     │
  │ location           text                               │
  │ items              text[]   NOT NULL DEFAULT '{}'     │
  │ content_time       date                               │
  │ uploaded_at        timestamptz NOT NULL DEFAULT now() │
  │ embedding          vector(1024) NOT NULL              │
  │ original_path      text                               │
  │ thumbnail_path     text                               │
  │ content_type       text                               │
  │ suggested_category text     ← Phase 35（建議資料夾）  │
  └───────────────────────────────────────────────────────┘

【改版後（本 phase 做完）】

  ┌──────────────────────── photo ────────────────────────┐
  │ …上面 12 欄一字不動…                                  │
  │ suggested_category   text   ← Phase 35（建議資料夾）  │
  │ ─────────────────── 增量五 D16 ─────────────────────  │
  │ suggested_entity     text   ★新（建議實體名稱）       │
  │ suggested_task_title text   ★新（建議待辦標題）       │
  │ suggested_task_due   date   ★新（建議到期日）         │
  └───────────────────────────────────────────────────────┘
        ▲                            ▲
        │                            │
   四個建議欄一組                本 phase 三個新欄
   都是「VLM 當時猜了什麼」      **全部是 NULL**
   都不代表照片真的歸了／        （沒有任何呼叫端傳值）
   釘了／建了待辦                 Phase 61 才餵值
```

### 圖二：兩個資料庫走兩條不同的路（**千萬不要走錯**）

```text
                  結構的兩份定義，內容必須一模一樣
        db/schema.sql（最終版）      db/migrate_design5.sql（遷移）
                 │                              │
                 ▼                              ▼
   ┌──────────────────────────┐   ┌──────────────────────────────┐
   │ PersonalDocAI_test       │   │ PersonalDocAI                │
   │ 測試庫，可以隨便重建     │   │ 正式庫，52 張真照片，不能砍  │
   └──────────────────────────┘   └──────────────────────────────┘
                 │                              │
   psql … -f db/schema.sql        psql … -f db/migrate_design5.sql
   ① DROP TABLE ×6  ← 砍光        ① ALTER TABLE ADD COLUMN
   ② CREATE TABLE ×6               IF NOT EXISTS ×3
   ③ 種子 6 筆資料夾              （既有資料一列都不動，
                 │                  新欄位全部拿到 NULL）
                 ▼                              │
   每個測試前由 conftest 的                     ▼
   reset_tables 再 TRUNCATE                跑第二次 →
   ＋重播六筆種子                          3 個 NOTICE「already exists」
                                           ＋ 0 個 ERROR ＝冪等成立

   ⛔ 把左邊那支拿去打右邊 ＝ DROP TABLE photo ＝ 52 張照片當場消失，
      而且 data/ 裡的原圖也從此變成沒人指著的孤兒檔。沒有 undo。
```

### 圖三：一個「建議」從哪來、到哪去（本 phase 只做中間那一格）

```text
   Phase 61（worker 看完圖）        Phase 56 ← 你在這裡        Phase 70（待決定開窗）
   ────────────────────────        ──────────────────        ──────────────────────
   VLM 回一份 PhotoUnderstanding
     entity      = "我的 MacBook"          photo 那一列          GET /folders/{inbox}
     task_title  = "繳交報告"      ──▶  suggested_entity  ──▶   帶出三個建議
     task_due    = 2026-08-21             suggested_task_title   實體窗畫選項①
          │                               suggested_task_due     待辦窗預填標題／日期
          │                                      ▲                      │
     clamp 成清單裡的名字                        │                      ▼
     （清單外 → None）                    本 phase 只挖欄位       人按「釘上」／「建立」
                                          值一律是 NULL          才真的寫 photo_entity／task
                                                                 （建議 ≠ 落庫，D12／D13 不變）
```

---

## 6. 驗收清單

每一條都要真的跑指令、真的看輸出，不要憑印象打勾。

- [ ] **開工基線已實查**：`pytest -q` 記下顆數（2026-08-25 為 `405 passed`）
- [ ] **`db/migrate_design5.sql` 存在，且只有三句 `ALTER TABLE`**

  ```bash
  grep -c "^ALTER TABLE photo ADD COLUMN IF NOT EXISTS" db/migrate_design5.sql
  ```

  預期輸出：`3`
  （開頭的 `^` 不能省：檔頭註解也提到「ADD COLUMN IF NOT EXISTS」這串字，不加 `^` 會多算一行變 4。）

- [ ] **`db/migrate_design5.sql` 裡沒有任何破壞性語句**

  ```bash
  grep -nEi "DROP |TRUNCATE|DELETE FROM|UPDATE " db/migrate_design5.sql || echo "OK：只加欄位，不動資料"
  ```

  預期輸出：`OK：只加欄位，不動資料`

- [ ] **`db/schema.sql` 與遷移腳本的三欄一致**

  ```bash
  grep -nE "suggested_entity|suggested_task_title|suggested_task_due" db/schema.sql db/migrate_design5.sql
  ```

  預期：六行命中（兩個檔各三行），且 `suggested_task_due` 兩邊都寫 `date`

- [ ] **測試庫已重建，三個新欄型別正確**

  ```bash
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test \
    -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='photo' AND column_name LIKE 'suggested%' ORDER BY column_name;"
  ```

  預期：四列，`suggested_task_due` 的 `data_type` 是 `date`

- [ ] **repository 每一處都改到**

  ```bash
  grep -n "suggested_entity" app/repositories/photo_repository.py
  ```

  預期：**7 行**命中（照本文件的程式碼貼就是恰好 7——`PHOTO_COLUMNS`、`insert_photo` 參數列、`insert_photo` docstring、`INSERT INTO` 欄位清單、`VALUES` 佔位符、`params` 字典、`list_photos_in_folder` 的 `SELECT`）。**少於 7 行＝有地方漏改**（例如漏了 `params` 字典——正是陷阱 7 那種假綠的近親），回頭對步驟 5

- [ ] **SQL 依然只出現在 repository 一層**（跑既有的自動化掃碼，不要自己 grep——
  手寫的 `grep "UPDATE "` 會被 `app/api/routers/photos.py` 裡「一條 UPDATE 同時寫…」
  這種**中文註解**誤中，白白虛驚一場）

  ```bash
  pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：`1 passed`

- [ ] **本 phase 沒有新增／減少任何 HTTP 端點**（仍是 20）

  ```bash
  pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
  ```

  預期：`1 passed`

- [ ] **`GET /folders/{id}` 的回應形狀沒變**（仍是五鍵，八鍵是 Phase 61）

  ```bash
  pytest tests/integration/test_folders_endpoint.py -q
  ```

  預期：全綠，一顆都沒紅

- [ ] **正式庫遷移前已備份，檔案不是 0 bytes**

  ```bash
  ls -lh ~/PersonalDocAI-backup-增量五前.dump
  ```

- [ ] **正式庫遷移跑了兩次，第二次 0 個 ERROR、3 個 `already exists` NOTICE**（步驟 8 的輸出）

- [ ] **正式庫照片數沒變、三個新欄全是 NULL**

  ```bash
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
    -c "SELECT count(*) AS 照片數, count(suggested_entity) AS 有實體建議的, count(suggested_task_title) AS 有待辦建議的, count(suggested_task_due) AS 有到期日的 FROM photo;"
  ```

  預期：照片數與步驟 7 開頭抄下來的數字相同（示意值 37），後三個都是 `0`

- [ ] **全量測試全綠**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：**基線 ＋ 5**（若基線 405 則為 `410 passed`），且 **0 skipped**

- [ ] **零 Ollama 依賴仍然成立**（把 Ollama 網址指到一個死埠，顆數要完全一樣）

  ```bash
  OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q
  ```

  預期：與上一條同樣的顆數、同樣全綠

- [ ] **git 收尾符合現行節奏**：產品負責人已指示 commit → 步驟 9 的指令已執行；
  未指示（現行預設）→ 跳過 commit，改核對「`git status --short -- app db tests` 的新增項
  恰為本 phase 的五個檔」（與開工前快照相減）

---

## 7. 常見陷阱

1. **`psql` 噴 `connection to server on socket "/tmp/.s.PGSQL.5433" failed`。**
   你漏了主機參數。2026-08-24 起資料庫跑在 Docker 裡，Docker **只把埠用 TCP 發佈出來、沒有 Unix socket 檔**（socket 是 `/tmp` 底下的一個特殊檔案，本機行程之間直接對話用的）。不寫主機時 `psql` 預設走 socket，當然找不到。解法：`~/.zshrc` 要有 `PGHOST=127.0.0.1`（已設好，新開的終端機才會生效），或每次都明寫 `-h 127.0.0.1`。

2. **`psql` 噴 `role "linjunting" does not exist`。**
   你漏了帳號。Docker 官方 Postgres 映像裡的帳號是 `postgres`，不是你的 macOS 使用者名稱。解法：`~/.zshrc` 要有 `PGUSER=postgres`，或每次明寫 `-U postgres`。

3. **手滑把 `db/schema.sql` 打到正式庫。**
   症狀：指令跑完看起來很正常（一堆 `DROP TABLE` / `CREATE TABLE`），然後打開網頁發現**一張照片都沒有**。原因：`schema.sql` 開頭就是六句 `DROP TABLE IF EXISTS`。這件事沒有 undo，只能用步驟 7 的備份還原（而 `data/` 裡的原圖檔會變成沒人指著的孤兒）。
   **養成習慣：任何要打正式庫的指令，先把 `-d` 後面那個字唸出來一次。** `PersonalDocAI` 是正式庫，`PersonalDocAI_test` 才是可以隨便砍的。

4. **`suggested_task_due` 寫成 `timestamp` 或 `timestamptz`。**
   症狀不會在本 phase 出現，會在 **Phase 70** 才爆：待決定的待辦彈窗預填日期時，值變成 `2026-08-21T00:00:00+08:00`，前端 `<input type="date">` 直接顯示空白（它只吃 `YYYY-MM-DD`）。而且與 `task.due_date`（本來就是 `date`）型別不一致，建立待辦時還要多做一次轉型。步驟 4 與步驟 8 的型別核對指令就是專門擋這件事的。

5. **第一次型別寫錯，重跑遷移不會幫你改回來。**
   `ADD COLUMN IF NOT EXISTS` 的判斷只看「有沒有同名欄位」，**不看型別**。所以如果第一次跑成 `timestamp`，之後把腳本改成 `date` 再跑一次，PostgreSQL 只會說「already exists, skipping」，型別依然是錯的。修法是手動改型別（正式庫上三欄都還是空的，轉型不會失敗）：

   ```bash
   psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
     -c "ALTER TABLE photo ALTER COLUMN suggested_task_due TYPE date;"
   ```

6. **`ADD COLUMN IF NOT EXISTS` 在很舊的 PostgreSQL 上不存在。**
   這個語法是 PostgreSQL 9.6 才有的。本專案跑的是 **pg17**（`pgvector/pgvector:pg17` 映像），完全支援，所以本 phase 不會踩到。**但要注意 compose.yaml 的映像 tag 不可以自己換成 pg18**——pg18 的 `PGDATA` 路徑不一樣，掛載點不再是 PGDATA，`initdb` 會建一個新的空叢集，看起來就像資料全沒了（`compose.yaml` 的註解有寫）。

7. **只改了 `PHOTO_COLUMNS`，忘了改 `INSERT INTO photo (...)` 的欄位清單。**
   這是本 phase 最陰險的一種壞法：**測試會綠**（`RETURNING` 讀得回三個 `None`，跟「本來就沒傳值」長得一模一樣），但值其實根本寫不進去。要到 Phase 61 真的餵值時才會發現「怎麼寫進去又不見了」。步驟 1 的 `test_insert_photo_寫得進三個建議欄` 就是專門擋這件事的——**寫完實作務必確認那一顆真的從紅轉綠**，不要跳過。

8. **忘了改 `test_folder_repository.py` 的五鍵斷言。**
   症狀：`AssertionError: assert {...8 個鍵...} == {...5 個鍵...}`。這是**預期中的紅**——它正好證明你的 `SELECT` 真的多帶了三欄。照步驟 1-2 改成八鍵即可。

9. **順手把 `app/schemas/folder.py` 的 `PhotoSummary` 也加成八鍵。**
   症狀：`test_folders_endpoint.py` 的五鍵斷言紅了。那是 **Phase 61** 的工作，本 phase 的驗收條件是「API 回應逐位元不變」。改回來。

10. **同時跑兩份 pytest。**
    症狀：大量看似隨機的 404「找不到照片」與 `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣，看起來像程式壞了。原因：兩份都在 `TRUNCATE` 同一個測試庫。等另一份跑完再跑。

11. **`docker compose down -v`。**
    `-v` ＝連 volume 一起刪，正式庫的正本 `personaldocai_pgdata` 會直接消失。**永遠禁止**。停服務一律用 `docker compose stop`。同理危險的還有 `docker system prune --volumes`、`docker volume prune -a`、Docker Desktop 的 "Reset to factory defaults"。

12. **忘了 `data/` 沒被 `pg_dump` 備份到。**
    `pg_dump` 只倒資料庫。原圖與縮圖在 `data/`，不入版控，全世界只有一份。備份時要另外 `tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/`。

---

## 8. 完成後的專案狀態

`photo` 表多出三個建議欄，兩個資料庫（正式庫走冪等遷移、測試庫走 `schema.sql` 重建）都已對齊；repository 寫得進、讀得回；`list_photos_in_folder` 從五鍵變八鍵。

**對外行為零改變**：端點仍是 20 個，`POST /photos` 的 201 回應與 `GET /folders/{id}` 的五鍵回應都逐位元不變——因為還沒有任何呼叫端傳值進新欄位，三個欄位的每一格都是 NULL。

下一步：**Phase 57** 做 JobStore（進度面板的資料來源）與第四道測試安全網，**Phase 58** 做 staging 暫存區。三支地基都好了之後，**Phase 59／60** 才寫真正的入庫任務 `run_ingest_job()`，**Phase 61** 回頭把 VLM 的建議餵進本 phase 挖好的這三個欄位。

測試累計 ＝ 開工基線 ＋ **5**。
