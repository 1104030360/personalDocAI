# 階段 VVV：Phase 47 丙-2 —— 切回 5433、停 brew、連線字串帶帳號 TODO

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-47-丙2切埠5433與停brew.md`
> 前置：★G1（2026-08-24）＋ **★G2（階段 UUU，diff 無輸出）** 都已通過

---

## 1. 實作邏輯

**這是整條遷移路線的「切換那一刻」。** 兩件事必須**同一次**做完：

1. **埠切回 5433** —— 停掉 brew 之後 5433 就空了；沿用同一個埠，既有文件、`.env`、
   `~/.zshrc` 的 `PGPORT=5433`、測試設定幾乎都不用改埠號。
2. **連線字串加帳號** —— 官方 Postgres 映像**強制**有一個 `POSTGRES_USER`（我們用 `postgres`）。
   現在的 `postgresql://localhost:5433/PersonalDocAI` **沒寫帳號**，psycopg 會自動用
   macOS 登入帳號 `linjunting` 去連——**Docker 裡沒有這個角色，一連就失敗**。

只做①不做②＝系統立刻壞掉。所以計畫把 design4 原本排在丙-3 的「改 `.env`」
提前到本 phase，讓每個 phase 做完系統都是可跑的。

### 四個動作，順序不可對調

```text
① docker compose stop db           （先讓 5434 那個停下來）
② compose.yaml 埠 5434 → 5433      （改設定，還沒起）
③ brew services stop postgresql@17 （5433 空出來）
   └─ lsof -iTCP:5433 確認真的空了
④ docker compose up -d db          （Docker 接手 5433）
   └─ 用 Phase 45 的查詢對一次數字
```

順序做反（先停 brew 再改埠）不會壞，但中間會有一段 5433 沒人聽、而 Docker 還在 5434
的狀態，很容易讓人以為出事了。

---

## 2. 步驟

- [ ] ① `docker compose stop db`（**不要用 `down`**）
- [ ] ② `compose.yaml` 埠改成 `127.0.0.1:5433:5432`，**`volumes:` 那段一個字不動**
      （換的只是「外面用哪個埠進來」，資料住在 volume 裡）
- [ ] ③ `brew services stop postgresql@17`（**只停服務，不移除任何檔案**）
  - [ ] `lsof -iTCP:5433 -sTCP:LISTEN` 沒有輸出
  - [ ] `brew services list`：`@14` 仍 started、`@17` 變 stopped/none
  - [ ] `ls -d /opt/homebrew/var/postgresql@17` **仍存在**（後悔藥第 1 層）
- [ ] ④ `docker compose up -d db` → `PORTS` ＝ `127.0.0.1:5433->5432/tcp`
  - [ ] `lsof -iTCP:5433` 顯示的是 Docker 的行程（不是 `postgres`）
  - [ ] 產出 `~/PersonalDocAI-docker切埠後快照.txt`，與遷移前 `diff` **無輸出**
- [ ] ⑤ `.env` 的 `DATABASE_URL` → `postgresql://postgres@localhost:5433/PersonalDocAI`
- [ ] ⑥ `tests/conftest.py` 第 7 行 → `postgresql://postgres@localhost:5433/PersonalDocAI_test`
      （**第 26 行的安全網斷言一個字不動**）
- [ ] ⑦ `~/.zshrc` 補 `export PGUSER=postgres` 與 `export PGHOST=127.0.0.1`
      （`PGHOST` 不能漏：Docker 只發佈 TCP 埠、沒有 Unix socket 檔）
- [ ] ⑧ `pytest -q` ＝ **402 passed ＋ 2 skipped**
- [ ] ⑨ `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 同顆數
- [ ] ⑩ host uvicorn 起得來、`/health` 200、瀏覽頁看得到照片、上傳一張會成功

---

## 3. 明確不做

| 不做 | 為什麼 |
|---|---|
| `brew uninstall postgresql@17` | 後悔藥第 1 層的全部價值 |
| 刪 `/opt/homebrew/var/postgresql@17` | 同上 |
| `docker compose down -v`、`volume rm …pgdata` | **本 phase 一做完 volume 裡就是正本**——P46 §5.4 的「砍掉重灌」特權到此為止 |
| 碰 `postgresql@14`（5432） | 別的專案的 |
| 建 `Dockerfile`／在 compose 加 `app` | Phase 48 |
| 改 `db/schema.sql`、遷移腳本、repository 的 SQL | design4 §8.5 明文「不改」 |
| 順手改 `CLAUDE.md` 指令區 | Phase 50 |

---

## 4. 驗收（計畫 §6，13 項）

見計畫檔；重點是 §4.3 的 `diff` 無輸出 ＋ `pytest` 兩輪同顆數 ＋
brew 資料目錄還在 ＋ 新終端機 `psql -d PersonalDocAI` 連得到 Docker。
