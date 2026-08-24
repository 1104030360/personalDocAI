# Phase 45：階段丙-0 —— 凍結、盤點與雙備份

> 🎯 **提醒：這是 side project，不要過度設計。**

```text
┌─ ⛔ 開工前檢查（閘門 G1）────────────────────────────────────────
│ 產品負責人是否已「明示」G1 通過？（原話例：「甲乙沒問題，可以做 Docker」）
│ 沒有這句話 → 停手，回去做 phase-44 的 G1 驗收包。
│ ★ G1 是**人**的動作，不是實作者可以自行勾掉的步驟（design4.md §7 明文）。
│ ★ 沒過 G1 之前，連 compose.yaml／Dockerfile 都不准建（design4.md §0 明文）。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 在動任何東西之前，先把「現在的正式庫長什麼樣」拍成**照片**（快照數字），
> 再做**兩份**備份。之後 Docker 那邊灌完資料，就拿這張照片逐項對——對得上才准停 brew（閘門 G2）。

**為什麼要先做這個：** 正式庫裡有真實照片資料，而且它的結構是靠一連串歷史遷移腳本堆起來的
（`db/schema.sql` 開頭是 `DROP TABLE`，**絕對不能拿來重建正式庫**）。
搬家只有一條安全路：`pg_dump` 導出來、`pg_restore` 灌進去、**對數字**。
沒有這張快照，之後灌完根本沒辦法判斷「有沒有掉東西」。

---

## 1. 對應 design4.md 章節

- **§8.3**（現況契約：八條實作時不能弄丟的事實——本 phase 逐條核對一次）
- **§8.6 階段丙-0**（凍結與盤點：停 uvicorn、兩組查詢、兩份 `pg_dump`）
- **§8.8**（備份與回復；後悔藥兩層的第一層就靠「brew 資料目錄沒被刪」）
- **§8.11**（風險表第 2 列：dump 不完整就停 brew ＝ P0；第 3 列：`down -v` 刪 volume ＝ P0）

---

## 2. 前置條件

- **★ G1 已由產品負責人明示通過**（見最上面的門檻框）。
- Phase 38〜44 全部完成，`pytest -q` ＝ 387 passed ＋ 2 skipped。
- 家目錄至少留 1 GB 空間（備份要放兩份；照片檔案不在裡面，所以其實很小，但別卡在這種事）。
- **手上這支 `pg_dump` 必須是 17.x。** 這台 Mac 同時裝了 `postgresql@14` 與 `@17`，
  **兩套的執行檔都在 `PATH` 上**，先確認取到的是哪一支：

```bash
pg_dump --version   # 預期：pg_dump (PostgreSQL) 17.x
which pg_dump       # 預期：/opt/homebrew/opt/postgresql@17/bin/pg_dump
```

  比伺服器舊的 `pg_dump`（例如 14 那支打 17 的庫）會直接中止並印出
  `server version mismatch`，而且**連檔案都不會產生**。
  萬一真的取到 14 那支，把指令改成絕對路徑就好：
  `/opt/homebrew/opt/postgresql@17/bin/pg_dump …`（`psql` 同理）。

**先認識幾個名詞（第一次出現）：**

- **`pg_dump`**：PostgreSQL 官方的「把整個資料庫倒出來」工具。倒出來的東西可以拿去別的地方灌回去。
- **`pg_restore`**：把 `pg_dump` 用**自訂格式**倒出來的檔案灌回資料庫的工具（見下一條）。
- **純文字格式 vs 自訂格式（`-Fc`）**：不加參數時 `pg_dump` 倒出來的是一個**可以用文字編輯器打開**
  的 `.sql` 檔（適合人眼檢查、用 `psql -f` 灌回去）；加了 `-Fc` 則是**壓縮過的二進位** `.dump` 檔
  （比較小、灌回去要用 `pg_restore`、可以選擇性還原）。design4 兩種都要，理由見 §4.4。
- **`--no-owner --no-acl`**：不要把「這張表屬於哪個帳號」「誰有什麼權限」也一起倒出來。
  **必要**：brew 那邊資料庫的擁有者是你的 macOS 帳號（`linjunting`），Docker 裡的官方映像只有
  `postgres` 這個帳號——帶著舊擁有者灌進去會一路報錯「role does not exist」。

---

## 3. 範圍

### 做

- 停掉正在跑的 `uvicorn`（避免遷移途中又有人上傳照片）。
- 對正式庫跑兩組查詢，**把輸出存成一個檔案**放家目錄（那就是「快照」）。
- 做兩份備份：純文字 `.sql` ＋ 自訂格式 `.dump`，都放家目錄。
- 逐條核對 design4 §8.3 的現況契約。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 建 `compose.yaml`／`Dockerfile`／`.dockerignore` | 那是 Phase 46／48。本 phase 只有備份，一個 Docker 指令都不下 |
| `brew services stop postgresql@17` | 那是 Phase 47，而且要先過 G2 |
| `brew uninstall postgresql@17`、刪 `/opt/homebrew/var/postgresql@17` | design4 §8.10 明文：第一個穩定週期內保留後悔藥 |
| 碰 `postgresql@14`（5432 埠） | 裡面是別的專案（wanderlove、fse_chat_room）。**連連上去都不要** |
| 對正式庫跑 `db/schema.sql` | 它開頭是 `DROP TABLE`。§8.10 明文禁止 |
| 把備份檔放進 repo | `.gitignore` 沒有擋 `.sql`／`.dump`，一不小心就會把真實資料 commit 進版控。**一律放家目錄 `~/`** |
| 改任何程式碼 | 本 phase 零程式碼變更 |

---

## 4. 實作步驟

### 4.1 核對現況契約（design4 §8.3，逐條）

- [ ] 正式庫名 `PersonalDocAI`、測試庫名 `PersonalDocAI_test`：

```bash
psql -p 5433 -l
```

- [ ] 現在的連線字串**沒寫帳號密碼**（psycopg 用你的 macOS 帳號連）：
      打開 `.env` 看 `DATABASE_URL`，應該是 `postgresql://localhost:5433/PersonalDocAI`。
- [ ] `tests/conftest.py` 第 7 行寫死測試庫 URL，而且第 26 行斷言 URL 含 `PersonalDocAI_test` 才准清表。
- [ ] `db/schema.sql` 開頭那一段就是 `DROP TABLE IF EXISTS`（第 8〜13 行，六張表整組砍掉；
      第 2 行的 `CREATE EXTENSION IF NOT EXISTS vector` 只是先把 vector 型別備好）
      ——**只能打測試庫**。
- [ ] 正式庫結構靠歷史遷移堆起來（`db/migrate_folders.sql`、`db/migrate_design3.sql`），
      **搬運必須 dump／restore**。
- [ ] 原圖在 host 的 `data/`，資料庫只記相對路徑（所以搬資料庫**不會**搬到照片檔，那是好事）。
- [ ] 鏡頭 token 全在記憶體，重啟 app 就失效（既有行為，遷移不會讓它變差）。
- [ ] 相機 QR 要用 `https://192.168.x.x:8000` 開桌面頁（container 內猜 IP 會猜出 `172.x`）。

### 4.2 凍結（停 uvicorn）

- [ ] 到跑 `uvicorn` 的那個終端機視窗按 `Ctrl+C`。
- [ ] 確認 8000 埠真的空了：

```bash
lsof -iTCP:8000 -sTCP:LISTEN
```

  預期：**沒有輸出**。有輸出就代表還有一個 uvicorn 在背景跑，先把它關掉——
  遷移中途有人上傳照片，快照就會對不上。

### 4.3 拍快照（design4 §8.6 丙-0 第 2 步，指令逐字照抄）

- [ ] 第一組：六張表的列數。

```bash
psql -p 5433 -d PersonalDocAI -c "
SELECT
  (SELECT count(*) FROM photo) AS photos,
  (SELECT count(*) FROM folder) AS folders,
  (SELECT count(*) FROM entity) AS entities,
  (SELECT count(*) FROM photo_entity) AS pins,
  (SELECT count(*) FROM task) AS tasks,
  (SELECT count(*) FROM folder_correction) AS corrections;
"
```

- [ ] 第二組：每一張照片的 id、類別、資料夾、有沒有原圖檔。

```bash
psql -p 5433 -d PersonalDocAI -c "
SELECT id, category, folder_id, original_path IS NOT NULL AS has_file
FROM photo ORDER BY id;
"
```

- [ ] **把兩組輸出存下來**（G2 要拿它逐項對；存在家目錄，不進 repo）：

```bash
{
  echo "=== 遷移前快照 $(date '+%F %T') ==="
  psql -p 5433 -d PersonalDocAI -c "
SELECT
  (SELECT count(*) FROM photo) AS photos,
  (SELECT count(*) FROM folder) AS folders,
  (SELECT count(*) FROM entity) AS entities,
  (SELECT count(*) FROM photo_entity) AS pins,
  (SELECT count(*) FROM task) AS tasks,
  (SELECT count(*) FROM folder_correction) AS corrections;
"
  psql -p 5433 -d PersonalDocAI -c "
SELECT id, category, folder_id, original_path IS NOT NULL AS has_file
FROM photo ORDER BY id;
"
} > ~/PersonalDocAI-docker遷移前快照.txt

cat ~/PersonalDocAI-docker遷移前快照.txt
```

- [ ] 順手記三件 G2 也要對的事（可以直接追加到同一個檔案）：

```bash
{
  echo "=== extension ==="
  psql -p 5433 -d PersonalDocAI -c "SELECT extname FROM pg_extension ORDER BY extname;"
  echo "=== 六筆預設資料夾（id 1〜6 種子）==="
  psql -p 5433 -d PersonalDocAI -c "SELECT id, name, is_inbox FROM folder ORDER BY id;"
  echo "=== 向量維度（任一張照片）==="
  psql -p 5433 -d PersonalDocAI -c "SELECT id, vector_dims(embedding) FROM photo ORDER BY id LIMIT 1;"
} >> ~/PersonalDocAI-docker遷移前快照.txt
```

  預期：`pg_extension` 裡看得到 `vector`；`folder` 的 id 是 1〜6 且只有 id=1 的 `is_inbox` 是 `t`；
  `vector_dims` ＝ **1024**。

> ⚠️ **要重跑就從上面那個 `>` 的區塊整個重來一次。** 這一段用的是 `>>`（＝**追加**在檔案後面），
> 單獨再跑一遍會讓同樣的內容在檔案裡出現兩份。Phase 46 的閘門 G2 是拿這個檔去 `diff`，
> 內容重複就會噴出一堆看不懂的差異，讓你誤以為資料搬錯了。
> 不確定檔案長怎樣時，`cat ~/PersonalDocAI-docker遷移前快照.txt` 看一眼最快：
> 從上到下應該恰好是「標題行 → 六張表列數 → 照片列 → extension → 六筆資料夾 → 向量維度」各一次。

> 🔗 **這一節的 SQL 與三個 `echo "=== … ==="` 標題，跟 phase-46 §5.1、phase-47 §4.3 是逐字相同的**
> ——閘門 G2 靠的就是 `diff` 這三份輸出（只跳過第一行的標題與時間）。
> 兩邊的查詢字串或標題文字**只要有人單方面改一個字，G2 就會永遠對不上**，
> 而且差異看起來會很像「資料搬錯了」。真的要調整查詢，三份必須同一次改完。

### 4.4 兩份備份（design4 §8.6 丙-0 第 3 步，指令逐字照抄）

- [ ] 純文字那份（人眼看得懂，之後查差異用）：

```bash
pg_dump -p 5433 -d PersonalDocAI --no-owner --no-acl \
  -f ~/PersonalDocAI-backup-docker遷移前.sql
```

- [ ] 自訂格式那份（Phase 46 要拿它 `pg_restore` 灌進 Docker）：

```bash
pg_dump -p 5433 -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-docker遷移前.dump
```

> **這兩份檔案在「後悔藥」裡的位置（design4 §8.8）：**
> 後悔藥有兩層。**第 1 層（快，30 秒）** 根本不靠備份檔——靠的是
> 「brew 的資料目錄一個字都沒被動過」，隨時 `brew services start postgresql@17` 就回到今天早上。
> **第 2 層（慢，幾分鐘）** 才是這兩份：`.dump` 用 `pg_restore` 灌回任何一邊，
> `.sql` 用文字編輯器打開查「到底差在哪」。
> 所以本增量全程**不准** `brew uninstall postgresql@17`、也不准刪 `/opt/homebrew/var/postgresql@17`
> ——那等於把第 1 層拆掉（design4 §8.10 明文）。

- [ ] 確認兩份都真的產出了、而且不是 0 位元組：

```bash
ls -lh ~/PersonalDocAI-backup-docker遷移前.sql ~/PersonalDocAI-backup-docker遷移前.dump
```

- [ ] 快速自我檢查純文字那份有東西（不是空殼）：

```bash
grep -c "COPY public.photo " ~/PersonalDocAI-backup-docker遷移前.sql
grep -c "CREATE EXTENSION" ~/PersonalDocAI-backup-docker遷移前.sql
```

  預期：兩個都 **≥ 1**。

- [ ] 確認**備份沒有跑進 repo**：

```bash
git status --short | grep -E '\.sql$|\.dump$|快照' || echo "乾淨：沒有備份檔跑進專案目錄"
```

  預期：印出「乾淨：…」那一行。

> ⚠️ **`git status --short` 本身不會是空的，那是正常的**——增量四的計畫檔（`docs/plan/`）
> 本來就還沒 commit。本 phase 要確認的是「**沒有多出** `*.sql`／`*.dump`／快照 `.txt`」，
> 不是「工作區全乾淨」。上面那條指令就是只挑這幾種副檔名來看。

### 4.5 收尾

- [ ] 三個檔案留在 `~/`，**一個都不要刪**——Phase 46 的閘門 G2 要拿快照去 `diff`、
      拿 `.dump` 去 `pg_restore`。
- [ ] （選作）若你另外有工作紀錄（例如 `docs/plan/report/` 的 REP），可以把快照內容貼一份存底。
      那屬於**文件**變更，不影響本 phase「零程式碼變更」的結論；但請在做完上面那個
      `git status` 檢查**之後**再貼，免得自己看不懂多出來的那一列是什麼。
- [ ] `postgresql@17` 仍然在跑（**本 phase 不停它**）：

```bash
brew services list | grep postgresql
```

  預期：`postgresql@17` 是 `started`、`postgresql@14` 也是 `started`（後者是別的專案的，不准動）。

---

## 5. ASCII 圖：這一步在整條遷移路線的位置

```text
   現在（brew 還活著，什麼都沒變）

        Mac
        ├── postgresql@14  :5432   ← 別的專案（wanderlove、fse_chat_room）★ 全程不准碰
        ├── postgresql@17  :5433   ← 本專案正式庫 PersonalDocAI ＋ 測試庫
        ├── Ollama         :11434
        └── uvicorn        :8000   ← ★ 本 phase 先把它停掉（凍結）

   本 phase 做的三件事：

        ┌─────────────────┐
        │ ① 停 uvicorn    │   避免遷移途中又有人上傳，快照才算數
        └─────────────────┘
        ┌──────────────────────────────────────────────────┐
        │ ② 拍快照 → ~/PersonalDocAI-docker遷移前快照.txt  │
        │    ・六張表列數                                  │
        │    ・每張照片 id／category／folder_id／有無檔    │
        │    ・extension／六筆種子／向量維度               │
        └──────────────────┬───────────────────────────────┘
                           │ 這張照片就是閘門 G2 的對照組
                           ▼
        ┌──────────────────────────────────────────────────┐
        │ ③ 兩份備份（都在家目錄，不進 repo）              │
        │    ~/…遷移前.sql    純文字：人眼查差異           │
        │    ~/…遷移前.dump   自訂格式：Phase 46 灌它      │
        └──────────────────────────────────────────────────┘

   ★ 本 phase 結束時，資料一個字沒動、brew 兩套都還在跑、專案目錄零程式碼變更。
     跟開工前只有兩處不同（都是刻意的）：
       ・uvicorn 停了（＝凍結，Phase 47 之前都維持停著）
       ・家目錄多出三個檔案（快照 .txt ＋ 備份 .sql ＋ 備份 .dump）
```

---

## 6. 驗收清單

- [ ] G1 已由產品負責人明示通過（有那句話，日期記下來了）
- [ ] 8000 埠沒有任何 listener（uvicorn 已停）
- [ ] `~/PersonalDocAI-docker遷移前快照.txt` 存在，內容含：六張表列數、每張照片一列、
      `vector` extension、`folder` id 1〜6、`vector_dims`＝1024
- [ ] `~/PersonalDocAI-backup-docker遷移前.sql` 存在且不是 0 位元組
- [ ] `~/PersonalDocAI-backup-docker遷移前.dump` 存在且不是 0 位元組
- [ ] `git status --short` 與開工前**相同**——本 phase 零程式碼變更；要確認的是
      **沒有多出** `*.sql`／`*.dump`／快照 `.txt`（§4.4 最後那條指令會印「乾淨：…」）
- [ ] `brew services list`：`postgresql@17` 仍 `started`、`postgresql@14` 仍 `started`
- [ ] 專案根目錄**仍然沒有** `compose.yaml`／`Dockerfile`／`.dockerignore`：

```bash
ls compose.yaml Dockerfile .dockerignore 2>&1 | grep -c "No such file"
```

  （在專案根目錄 `/Users/linjunting/personalDocAI` 跑。）
  預期：**3**（三個都不存在＝G1 之前不准建，design4 §0 明文）。

---

## 7. 常見陷阱

1. **忘了停 uvicorn**：`--reload` 的 uvicorn 常常被丟在某個分頁跑一整天。
   遷移途中有人（或你自己）上傳一張照片，快照就對不上，G2 會白白卡住。
   一定要用 `lsof -iTCP:8000 -sTCP:LISTEN` 確認。

2. **`pg_dump` 忘了 `--no-owner --no-acl`**：灌進 Docker 時會一路噴
   `role "linjunting" does not exist`。這兩個參數是**必要**的，不是可選的。

3. **只做一份備份**：design4 要兩份是有理由的——`.dump` 用來灌、`.sql` 用來**查**。
   灌完發現少了三列，你會很想用文字編輯器打開來看，那時候只有 `.dump` 就麻煩了。

4. **備份放進專案目錄**：`.gitignore` 只擋了 `data/`、`.env`、`certs/` 等，
   **沒有**擋 `*.sql`／`*.dump`。放進 repo 再 `git add .` 就會把真實照片描述 commit 進版控。
   一律 `~/`。

5. **快照只看列數不看照片列**：只對六個數字很容易「數字對、內容錯」
   （例如某張照片的 `folder_id` 跑掉了）。第二組查詢的每一列都要對。

6. **順手就把 brew 停掉**：不行。停 brew 是 Phase 47，而且前面還有一個 G2。
   這個順序是 design4 §8.6 明文寫「不可對調」的。

7. **用到 `postgresql@14` 那一套的執行檔**：這台 Mac 兩套 PostgreSQL 的 `psql`／`pg_dump`
   **都在 `PATH` 上**（`/opt/homebrew/opt/postgresql@14/bin` 也在裡面），有兩件事要顧：
   - **埠**：本專案的互動 shell 已由 `~/.zshrc` 的 `PGPORT=5433` 指到對的埠，
     而且上面每一條指令都明寫 `-p 5433`，照抄就不會連錯。
     **不要**為了省事把 `-p 5433` 拿掉。
   - **版本**：`pg_dump` 比伺服器舊會直接中止（`server version mismatch`）**而且不產生檔案**。
     §2 的 `pg_dump --version` 就是先擋這一關；真的取到 14 那支就改用絕對路徑
     `/opt/homebrew/opt/postgresql@17/bin/pg_dump`。

8. **`-p 5433` 打成 `-p 5432`**：5432 是 `postgresql@14`，裡面是**別的專案**的資料庫
   （wanderlove、fse_chat_room）。備份錯的庫還算小事，怕的是養成習慣後在 Phase 47
   對著它下停服務的指令。看到 `-p 5432` 一律當成打錯字。
