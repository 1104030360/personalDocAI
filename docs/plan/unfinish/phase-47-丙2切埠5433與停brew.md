# Phase 47：階段丙-2 —— 切回 5433 埠、停掉 brew、連線字串改成帶帳號

> 🎯 **提醒：這是 side project，不要過度設計。**

```text
┌─ ⛔ 開工前檢查（兩道閘門，缺一不可）─────────────────────────────
│ ① 閘門 G1：產品負責人是否已「明示」G1 通過？
│    沒有這句話 → 停手，回去做 phase-44 的 G1 驗收包。G1 是**人**的動作。
│ ② 閘門 G2：phase-46 §5.2 的 diff 是否**沒有任何輸出**？
│    沒過 G2 → **不准停 brew**（design4.md §8.6 丙-1 第 6 步明文）。
│    對不上就停在 5434 慢慢查，舊的那套繼續服務。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 讓 Docker 的資料庫接手 **5433** 這個埠，把 brew 的 `postgresql@17` **停掉**
> （只停服務，**資料目錄留著當後悔藥**），並把 `.env` 與 `tests/conftest.py` 的連線字串
> 換成帶帳號的版本，讓 host 上的 `uvicorn` 與 `pytest` 照常運作。

**為什麼埠要換回 5433：** 停掉 brew 之後 5433 就空出來了；沿用同一個埠，
既有文件、`.env`、`~/.zshrc` 的 `PGPORT=5433`、測試設定幾乎都不用改埠號，
也不會跟 `postgresql@14` 的 5432 打架（design4 §8.4 最後一段）。

**為什麼連線字串一定要加帳號：** 官方 Postgres 映像**強制**有一個 `POSTGRES_USER`
（我們用 `postgres`）。而現在的連線字串 `postgresql://localhost:5433/PersonalDocAI` 沒寫帳號，
psycopg 會自動用你的 macOS 登入帳號（`linjunting`）去連——Docker 裡沒有這個角色，
**一連就失敗**。所以「停 brew」與「改連線字串」必須是**同一次**做完的事。

---

## 1. 對應 design4.md 章節

- **§8.4 的「帳號」段**（使用者 `postgres`、`POSTGRES_HOST_AUTH_METHOD=trust`、
  host 上用 `postgresql://postgres@localhost:5433/…`、`PGUSER=postgres`）
  ——design4 只寫到 `PGUSER`；本計畫**另加 `PGHOST=127.0.0.1`**（§4.4），
  因為 Docker 只發佈 TCP 埠、沒有 brew 那種 Unix socket，光設 `PGUSER` 互動 `psql` 仍連不上
- **§8.4 的「為什麼 host 埠繼續用 5433」段**
- **§8.5**（`.env` 改連線字串、`tests/conftest.py` 對齊）
- **§8.6 階段丙-2**（六個步驟）
- **§8.8**（後悔藥第 1 層就是本 phase 的反向操作）
- **§8.10**（不做：`brew uninstall postgresql@17`）
- **§8.11**（風險第 4 列：conftest 仍用「無帳號 URL」＝ P1，對策「與 `.env` 同一天改」）

> **📌 與 design4 §8.6 的一處順序微調（刻意的，要知道）**
> design4 把「`.env` 改 URL」寫在**丙-3** 第 1 步。本計畫把 `.env` 與 `tests/conftest.py`
> 一起提前到**丙-2**（也就是本 phase），理由是：brew 一停，host 上的 `uvicorn` 與 `pytest`
> 立刻連不上資料庫——若拖到下一個 phase 才改，中間會有一段「系統是壞的」的狀態，
> 違反本增量「每個 phase 做完系統都要可跑、`pytest -q` 全綠」的原則。
> design4 §8.11 風險表第 4 列本來就寫「與 `.env` 同一天改」，這只是把「同一天」寫死成「同一份 phase」。
> **丙-3（Phase 48）因此不需要再改一次 `.env`。**

---

## 2. 前置條件

- **★ G1 已由產品負責人明示通過。**
- **★ G2 已通過**（Phase 46 §5.2 的 `diff` 沒有輸出）。
- Phase 45 的兩份備份都還在家目錄（後悔藥第 2 層）：

```bash
ls -lh ~/PersonalDocAI-backup-docker遷移前.sql \
       ~/PersonalDocAI-backup-docker遷移前.dump
```

- **Docker Desktop 正在跑，而且 Phase 46 的 `db` 還活著**：

```bash
docker compose ps
```

  預期：`db` 是 `Up … (healthy)`、`PORTS` ＝ `127.0.0.1:5434->5432/tcp`
  （**還在 5434**——切到 5433 是本 phase 要做的事）。
  ⚠ 本檔所有 `docker compose …` 指令都要在專案根目錄
  `/Users/linjunting/personalDocAI` 執行——它是靠「當前目錄有沒有 `compose.yaml`」找設定的。

- 沒有任何 uvicorn 在跑（Phase 45 已停；再確認一次）：

```bash
lsof -iTCP:8000 -sTCP:LISTEN
```

  預期：**沒有輸出**。

---

## 3. 範圍

### 做

- `docker compose stop db`
- `compose.yaml` 的埠從 `127.0.0.1:5434:5432` 改成 **`127.0.0.1:5433:5432`**
- `brew services stop postgresql@17`
- 確認 5433 空了，再 `docker compose up -d db`
- 用 Phase 45 的同一組查詢打 `localhost:5433`，數字必須相同
- `.env` 的 `DATABASE_URL` 改成帶帳號
- `tests/conftest.py` 的 `TEST_DATABASE_URL` 改成帶帳號
- `~/.zshrc` 加 `PGUSER=postgres` 與 `PGHOST=127.0.0.1`（讓互動 `psql` 不必每次打
  `-U postgres -h 127.0.0.1`；為什麼連主機也要設見 §4.4）
- `pytest -q` 必須仍是綠的

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| `brew uninstall postgresql@17` | design4 §8.10 明文：第一個穩定週期內保留後悔藥 |
| 刪 `/opt/homebrew/var/postgresql@17`（brew 的資料目錄） | 同上。那是後悔藥第 1 層的全部價值所在 |
| `docker compose down -v`、`docker volume rm …pgdata` | 本 phase 一做完，volume 裡的就是**正本**了（Phase 46 §5.4 那個「砍掉重灌」的特權到此為止）。`-v` 與 `volume rm` ＝ 刪正式庫 |
| 碰 `postgresql@14`（5432） | 別的專案的（wanderlove、fse_chat_room） |
| 建 `Dockerfile`／在 compose 加 `app` 服務 | 那是 Phase 48。本 phase 結束時，app 仍然是 host 上跑的 `uvicorn` |
| 改 `db/schema.sql`、遷移腳本、repository 的 SQL | design4 §8.5 明文「不改」 |
| 順手改 `CLAUDE.md` 的指令區 | 那是 Phase 50（等整套驗收過了再改文件，免得文件先跑到現實前面） |

---

## 4. 實作步驟

### 4.1 停 Docker 的 db、改埠（design4 §8.6 丙-2 第 1、2 步）

- [ ] 停掉 container（**不要用 `down`**）：

```bash
docker compose stop db
```

- [ ] 編輯 `compose.yaml`，把埠那一行與它的註解改成：

```yaml
    ports:
      # 5433 ＝本專案沿用的埠（brew 的 postgresql@17 已於 Phase 47 停用）。
      # 127.0.0.1: 前綴＝只綁本機，同一個 Wi-Fi 的其他裝置打不到資料庫。
      - "127.0.0.1:5433:5432"
```

- [ ] **不要動 `volumes:` 那一段**——同一個 named volume `pgdata`
      （＝Docker 自己管理、有名字的那塊硬碟空間，Phase 46 建的），
      換的只是「外面用哪個埠進來」。資料完全不受影響。

### 4.2 停 brew（design4 §8.6 丙-2 第 3、4 步）

- [ ] 停服務（**只停服務，不移除任何檔案**）：

```bash
brew services stop postgresql@17
```

- [ ] 確認 5433 真的空了：

```bash
lsof -iTCP:5433 -sTCP:LISTEN
```

  預期：**沒有輸出**。有輸出代表 brew 還沒真的停，等幾秒再看一次。

- [ ] 順手確認 `@14` 沒被波及：

```bash
brew services list | grep postgresql
```

  預期：`postgresql@14` 仍是 `started`、`postgresql@17` 變成 `stopped` 或 `none`。

- [ ] 確認 brew 的資料目錄**還在**（後悔藥第 1 層）：

```bash
ls -d /opt/homebrew/var/postgresql@17
```

  預期：路徑存在。**不准刪。**

### 4.3 讓 Docker 接手 5433（design4 §8.6 丙-2 第 5、6 步）

- [ ] 起來：

```bash
docker compose up -d db
docker compose ps
```

  預期：`STATUS` ＝ `Up … (healthy)`；`PORTS` ＝ `127.0.0.1:5433->5432/tcp`。

- [ ] 確認現在 5433 上的是 Docker 那一套：

```bash
lsof -iTCP:5433 -sTCP:LISTEN
```

  預期：看得到 `com.docker` 或 `docker` 之類的行程名（不是 `postgres`）。

- [ ] 用**與 Phase 45 完全相同**的查詢打 5433，數字必須相同：

> 🔗 **下面的 SQL 與三個 `echo "=== … ==="` 標題，跟 phase-45 §4.3、phase-46 §5.1 逐字相同**
> ——這一節的 `diff`（以及 phase-50 §4.5 ① 再對一次的那個 `diff`）就是靠這件事成立的。
> **只要有人單方面改一個字就會永遠對不上**，而且差異看起來會很像「資料搬錯了」。
> 真的要調整查詢，三份必須同一次改完。

```bash
{
  echo "=== 切埠後快照 $(date '+%F %T') ==="
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "
SELECT
  (SELECT count(*) FROM photo) AS photos,
  (SELECT count(*) FROM folder) AS folders,
  (SELECT count(*) FROM entity) AS entities,
  (SELECT count(*) FROM photo_entity) AS pins,
  (SELECT count(*) FROM task) AS tasks,
  (SELECT count(*) FROM folder_correction) AS corrections;
"
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "
SELECT id, category, folder_id, original_path IS NOT NULL AS has_file
FROM photo ORDER BY id;
"
  echo "=== extension ==="
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "SELECT extname FROM pg_extension ORDER BY extname;"
  echo "=== 六筆預設資料夾（id 1〜6 種子）==="
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "SELECT id, name, is_inbox FROM folder ORDER BY id;"
  echo "=== 向量維度（任一張照片）==="
  psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "SELECT id, vector_dims(embedding) FROM photo ORDER BY id LIMIT 1;"
} > ~/PersonalDocAI-docker切埠後快照.txt

diff <(tail -n +2 ~/PersonalDocAI-docker遷移前快照.txt) \
     <(tail -n +2 ~/PersonalDocAI-docker切埠後快照.txt)
```

  **沒有輸出 ＝ 資料完好。** 有輸出就先別往下走——照 §5 圖裡的
  「後悔藥第 1 層」退回遷移前（brew 的資料目錄還在，30 秒就回得去），再把 diff 拿去查。

### 4.4 改連線字串（`.env` 與 `tests/conftest.py` 同一次改）

- [ ] `.env` 的 `DATABASE_URL` 改成：

```text
DATABASE_URL=postgresql://postgres@localhost:5433/PersonalDocAI
```

  順手把上面那段註解更新，說明「帳號 `postgres` 是 Docker 官方映像強制要有的；
  沒有密碼是因為容器設了 `POSTGRES_HOST_AUTH_METHOD=trust`，而且埠只綁 127.0.0.1」。
  （`.env` 不入版控，改了不會出現在 `git status`。）

- [ ] `tests/conftest.py` 第 7 行：

```python
TEST_DATABASE_URL = "postgresql://postgres@localhost:5433/PersonalDocAI_test"
```

  第 26 行那個「URL 必須含 `PersonalDocAI_test` 才准清表」的斷言**一個字都不要動**——
  它是防止測試清到正式庫的安全網，加了帳號之後照樣成立。

- [ ] `~/.zshrc` 補**兩行**（讓互動 `psql` 不必每次打 `-h 127.0.0.1 -U postgres`）：

```bash
export PGUSER=postgres
export PGHOST=127.0.0.1
```

  **為什麼連主機（`PGHOST`）也要設：** 不寫 `-h` 時，`psql` 走的是 **Unix socket**
  （`/tmp` 底下的一個特殊檔案，只有跑在這台機器上的 PostgreSQL 才會產生它），
  而 Docker 只把埠**用 TCP 發佈**到 `127.0.0.1:5433`、**沒有** socket 檔。
  所以 brew 一停，光設 `PGUSER` 是不夠的，`psql -d PersonalDocAI` 會噴
  `connection to server on socket "/tmp/.s.PGSQL.5433" failed: No such file or directory`。
  設了 `PGHOST=127.0.0.1` 等於每次自動補上 `-h 127.0.0.1`（就是 §4.3 那些指令在做的事）。

  既有的 `export PGPORT=5433` 留著。改完開一個新的終端機視窗（或 `source ~/.zshrc`）才生效。
  之後 `psql -d PersonalDocAI` 就能直接連到 Docker 那一套。

> **⚠️ 注意這兩行會影響整台機器的 `psql` 預設帳號與預設主機。**
> 如果你之後要用 `psql` 連 `postgresql@14`（別的專案），三個變數都要自己用旗標蓋掉：
> `psql -h 127.0.0.1 -p 5432 -U <原本的帳號> -d <資料庫>`（`@14` 一樣聽得到 TCP 的 127.0.0.1）。
> 本專案不碰 `@14`，但你的其他專案會。

### 4.5 驗證系統仍然可跑

- [ ] 測試（連的是 Docker 裡的 `PersonalDocAI_test`）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**387 passed ＋ 2 skipped**（與遷移前完全相同的顆數）。

- [ ] 零外部依賴實證（把 Ollama 網址指到一個沒人聽的埠，顆數還是要一樣）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

  預期：與上一步**同顆數**（證明測試從頭到尾沒打到真的 Ollama）。

- [ ] 伺服器（**仍然是 host 上的 uvicorn**，app 容器化是下一個 phase；
      在**已啟用 venv** 的終端機執行）：

```bash
uvicorn app.main:app --reload --port 8000
```

  另一個終端機：

```bash
curl -s http://localhost:8000/health
```

  預期：`{"status":"ok"}`

- [ ] 瀏覽器開 `http://localhost:8000/ui/browse.html?tab=folders`：
      資料夾、照片、縮圖都看得到（縮圖來自 host 的 `data/`，本 phase 完全沒動它）。
- [ ] 點一張照片：Phase 39 的詳情窗照常開得起來。
- [ ] 上傳一張新照片：201、`data/` 出現檔案、彈窗鏈照跑。
      （這一步同時證明「寫入」也正常，不只是讀取。）

---

## 5. ASCII 圖：切換的那一刻

```text
  ── 之前（Phase 46 結束時）────────────────────────────────────────
     brew postgresql@17  :5433  ●running   ← 正本，host 的 uvicorn／pytest 連這裡
     docker  db          :5434  ●running   ← 複本，剛灌好、G2 已對帳
     .env  DATABASE_URL = postgresql://localhost:5433/PersonalDocAI   （無帳號）

  ── 本 phase 的四個動作（順序不可對調）──────────────────────────
     ① docker compose stop db          （先讓 5434 那個停下來）
     ② compose.yaml 埠 5434 → 5433     （改設定，還沒起）
     ③ brew services stop postgresql@17（5433 空出來）
        └─ lsof -iTCP:5433 確認真的空了
     ④ docker compose up -d db          （Docker 接手 5433）
        └─ 用 Phase 45 的查詢對一次數字

  ── 之後（本 phase 結束時）────────────────────────────────────────
     brew postgresql@14  :5432  ●running   ← 別的專案 ★ 全程沒碰
     brew postgresql@17  :---   ○stopped   ← 資料目錄還在＝後悔藥第 1 層
     docker  db          :5433  ●running   ← ★ 正本現在住這裡（volume: pgdata）
     host   uvicorn      :8000  （手動跑） ← app 容器化是 Phase 48
     .env  DATABASE_URL = postgresql://postgres@localhost:5433/PersonalDocAI
                                       ↑ 多了帳號，這是本 phase 的另一半

     ┌───────────────────────────────────────────────────────────┐
     │ 後悔藥第 1 層（30 秒回到遷移前）                          │
     │   docker compose stop db                                  │
     │   brew services start postgresql@17                       │
     │   .env 改回 postgresql://localhost:5433/PersonalDocAI     │
     │   tests/conftest.py 也改回無帳號的 URL                    │
     │   ~/.zshrc 的 PGUSER／PGHOST 兩行先註解掉                 │
     └───────────────────────────────────────────────────────────┘
```

---

## 6. 驗收清單

- [ ] `compose.yaml` 的埠是 `127.0.0.1:5433:5432`，`volumes` 那段沒動過
- [ ] `docker compose ps`：`db` 是 `Up … (healthy)`、`PORTS` 顯示 `127.0.0.1:5433->5432/tcp`
- [ ] `brew services list`：`postgresql@17` ＝ `stopped`；`postgresql@14` ＝ `started`
- [ ] `/opt/homebrew/var/postgresql@17` **仍然存在**（沒有刪、沒有 uninstall）
- [ ] `lsof -iTCP:5433 -sTCP:LISTEN` 顯示的是 Docker 的行程
- [ ] §4.3 的 `diff` **沒有任何輸出**（資料完好）
- [ ] `.env` 的 `DATABASE_URL` 含 `postgres@`
- [ ] `tests/conftest.py` 的 `TEST_DATABASE_URL` 含 `postgres@`，且第 26 行的安全網斷言沒動
- [ ] `pytest -q` ＝ **387 passed ＋ 2 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] host 上 `uvicorn` 起得來、`/health` 回 200、瀏覽頁看得到照片、上傳一張會成功
- [ ] **新開一個終端機**打 `psql -d PersonalDocAI` 連得到 Docker 那一套
      （＝`PGHOST`／`PGUSER`／`PGPORT` 三個變數都生效了）
- [ ] 版控狀態符合預期（本 phase 只該動 `compose.yaml` 與 `tests/conftest.py`）：

```bash
git status --short
```

  預期：`tests/conftest.py` 顯示 ` M`（已追蹤、被改過）；`compose.yaml` 與 `db/docker-init/`
  顯示 `??`（Phase 46 新建、還沒 commit——本專案依產品負責人指示暫不 commit）。
  除了這些與 `docs/` 底下的計畫檔之外，**不該有其他產品程式碼被動到**。
  **不要用 `git diff --stat` 來對這一條**：它只看得到「已追蹤」的檔案，
  新建的 `compose.yaml` 根本不會出現在裡面。
  `.env` 與 `~/.zshrc` 兩處也都不會出現（前者在 `.gitignore`、後者不在專案裡）。

---

## 7. 常見陷阱

1. **順序做反（先停 brew 再改埠）**：那樣中間會有一段時間 5433 沒人聽，而 Docker 還在 5434。
   不會壞掉，但你會以為出事了。照 §5 的四個動作順序做。

2. **忘了改 `tests/conftest.py`**：停 brew 之後 `pytest` 會整套紅，錯誤訊息長得像
   `connection failed: FATAL: role "linjunting" does not exist`。
   看到這個訊息就是**這一條**（design4 §8.11 風險表第 4 列預言過）。
   如果訊息換成 `relation "photo" does not exist`，那就不是這一條，而是
   Phase 46 §4.5 的測試庫沒重建——補跑一次（**注意埠現在是 5433**）：
   `psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql`。

3. **`.env` 改了但沒重啟 uvicorn**：`app/core/config.py` 只在 import 時讀一次 `.env`。
   改完一定要重啟伺服器。

4. **用 `docker compose down` 而不是 `stop`**：`down` 會把 container 移除（volume 還在，
   資料不會丟），但如果手滑打成 `down -v` 就是刪正式庫。養成只用 `stop` 的習慣。

5. **以為改埠要重灌資料**：不用。埠只是「外面怎麼進來」，資料住在 volume 裡，
   跟埠一點關係都沒有。`volumes:` 那段不要動。
   §4.3 的 `docker compose up -d db` 會印 `Recreated`（改了埠設定就一定會重建 container），
   那是**正常的**——重建的是 container，volume `pgdata` 原封不動。

6. **`brew uninstall postgresql@17`**：不准。design4 §8.10 明列。
   那是唯一一顆「30 秒回到遷移前」的後悔藥。

7. **直接 `psql -d PersonalDocAI`，卻沒設 §4.4 那兩個環境變數**：會噴兩種錯誤之一——
   少了 `PGHOST=127.0.0.1` 是 `connection to server on socket "/tmp/.s.PGSQL.5433" failed:
   No such file or directory`（沒有 `-h` 就走 Unix socket，而 Docker 只發佈 TCP 埠）；
   少了 `PGUSER=postgres` 則是 `role "linjunting" does not exist`。
   要嘛設環境變數並開新終端機，要嘛每次自己打 `psql -h 127.0.0.1 -U postgres -d PersonalDocAI`。

8. **以為 app 也已經容器化了**：還沒。本 phase 結束時 app 仍然是你手動跑的 `uvicorn`，
   只是它連的資料庫換成 Docker 那一套。app 容器化是 Phase 48。
