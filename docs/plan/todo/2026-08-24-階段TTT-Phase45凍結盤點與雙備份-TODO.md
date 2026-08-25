# 階段 TTT：Phase 45 丙-0 —— 凍結、盤點與雙備份 TODO

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-45-丙0凍結盤點與雙備份.md`
> 前置：階段 SSS 校準完成；★G1 已於 2026-08-24 通過

---

## 1. 實作邏輯（為什麼這樣做）

正式庫裡有**真實照片資料**，而且它的結構是靠一連串歷史遷移腳本堆起來的
（`db/schema.sql` 開頭是 `DROP TABLE`，**絕對不能拿來重建正式庫**）。
搬家只有一條安全路：

```text
pg_dump 導出  →  pg_restore 灌進 Docker  →  拿「搬家前的照片」逐項對帳
                                              ↑ 就是本階段要拍的快照
```

**沒有這張快照，之後灌完根本沒辦法判斷「有沒有掉東西」**——這就是閘門 G2 的對照組。

另外要先「凍結」：遷移途中若有人（或自己）上傳一張照片，快照就對不上，
G2 會白白卡住半天。所以第一件事是停掉 uvicorn。

**本階段零程式碼變更、一個 Docker 指令都不下。**

---

## 2. 步驟

### 2.1 核對現況契約（計畫 §4.1，八條逐條）

- [ ] `psql -p 5433 -l` 看得到 `PersonalDocAI` 與 `PersonalDocAI_test`
- [ ] `.env` 的 `DATABASE_URL` ＝ `postgresql://localhost:5433/PersonalDocAI`（**沒有帳號**）
- [ ] `tests/conftest.py` 第 7 行寫死測試庫 URL、第 26 行有「URL 必須含 `PersonalDocAI_test`」的斷言
- [ ] `db/schema.sql` 開頭是 `DROP TABLE IF EXISTS`（只能打測試庫）
- [ ] 正式庫結構靠 `db/migrate_folders.sql`、`db/migrate_design3.sql` 堆起來
- [ ] 原圖在 host 的 `data/`，DB 只記相對路徑
- [ ] 鏡頭 token 全在記憶體
- [ ] 相機 QR 要用區網 IP 開桌面頁

### 2.2 凍結

- [ ] 停掉跑在 8000 的 uvicorn
- [ ] `lsof -iTCP:8000 -sTCP:LISTEN` **沒有輸出**

### 2.3 拍快照 → `~/PersonalDocAI-docker遷移前快照.txt`

**⚠ 指令逐字照抄計畫 §4.3**（G2 靠 `diff` 這三份輸出，字串差一個字就永遠對不上）。
第一段用 `>`（覆寫）、第二段用 `>>`（追加）——**要重跑就從 `>` 那段整個重來**。

內容順序（固定）：標題行 → 六張表列數 → 每張照片一列 → extension → 六筆資料夾 → 向量維度

預期：`pg_extension` 有 `vector`；`folder` id 1〜6 且只有 id=1 的 `is_inbox` 是 `t`；
`vector_dims` ＝ **1024**

### 2.4 兩份備份（都放家目錄 `~/`，**不進 repo**）

- [ ] 純文字：`~/PersonalDocAI-backup-docker遷移前.sql`（人眼查差異用）
- [ ] 自訂格式：`~/PersonalDocAI-backup-docker遷移前.dump`（Phase 46 拿它灌）
- [ ] 兩個 `--no-owner --no-acl` **不能省**（Docker 裡沒有 `linjunting` 這個角色）
- [ ] 兩份都不是 0 位元組
- [ ] `grep -c "COPY public.photo "` 與 `grep -c "CREATE EXTENSION"` 都 ≥ 1

### 2.5 收尾

- [ ] `git status --short | grep -E '\.sql$|\.dump$|快照'` → 印「乾淨：…」
- [ ] `brew services list`：`@17` 仍 started、`@14` 仍 started
- [ ] 專案根目錄仍沒有 `compose.yaml`／`Dockerfile`／`.dockerignore`（G1 之前不准建）

---

## 3. 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 建 `compose.yaml`／`Dockerfile`／`.dockerignore` | 那是 Phase 46／48 |
| `brew services stop postgresql@17` | 那是 Phase 47，而且要先過 G2 |
| `brew uninstall`、刪 `/opt/homebrew/var/postgresql@17` | 後悔藥第 1 層 |
| 碰 `postgresql@14`（5432） | 別的專案（wanderlove、fse_chat_room）——**連連上去都不要** |
| 對正式庫跑 `db/schema.sql` | 開頭是 `DROP TABLE` |
| 把備份放進 repo | `.gitignore` **沒有**擋 `.sql`／`.dump`，一律 `~/` |
| 改任何程式碼 | 本 phase 零程式碼變更 |

---

## 4. 驗收（計畫 §6）

- [ ] G1 已通過（2026-08-24，dev-prompt `phase0824.md`）
- [ ] 8000 埠沒有 listener
- [ ] 快照 `.txt` 存在且六段內容齊全
- [ ] `.sql`／`.dump` 兩份都在、都不是 0 位元組
- [ ] `git status --short` 沒有多出 `*.sql`／`*.dump`／快照 `.txt`
- [ ] brew 兩套都還 started
- [ ] `ls compose.yaml Dockerfile .dockerignore` → 三個都 `No such file`
