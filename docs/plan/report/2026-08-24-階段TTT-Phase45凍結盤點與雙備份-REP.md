# 階段 TTT 完成報告：Phase 45 丙-0 —— 凍結、盤點與雙備份

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-45-丙0凍結盤點與雙備份.md`（30 個 checkbox 全數打勾）
> 產出：**零程式碼變更、零 Docker 指令**；家目錄多三個檔案

---

## 1. 實作邏輯

搬家前先拍一張「現在長什麼樣」的照片，再做兩份備份。
**這張照片就是閘門 G2 的對照組**——沒有它，Phase 46 灌完資料根本無從判斷有沒有掉東西。

順序有意義：**先凍結，再拍照**。遷移途中若有人上傳一張照片，快照就對不上，
G2 會卡住而且看起來像「資料搬錯了」。

```text
① 停 uvicorn ──► ② 拍快照 ──► ③ 兩份備份
   （凍結）        （G2 的      （.dump 給 P46 灌
                    對照組）      .sql 給人眼查差異）
```

---

## 2. 步驟與實測結果

### 2.1 現況契約八條（design4 §8.3）——逐條核對通過

| # | 契約 | 實測 |
|---|---|---|
| 1 | 兩個資料庫都在 | `psql -p 5433 -l` → `PersonalDocAI`、`PersonalDocAI_test`（owner ＝ `linjunting`） |
| 2 | 連線字串**沒有帳號** | `.env:7` ＝ `postgresql://localhost:5433/PersonalDocAI` |
| 3 | conftest 的安全網 | 第 7 行 `TEST_DATABASE_URL = "postgresql://localhost:5433/PersonalDocAI_test"`；第 26 行 `assert "PersonalDocAI_test" in config.DATABASE_URL` |
| 4 | `schema.sql` 開頭是 `DROP TABLE` | 第 8〜13 行六張表整組砍（由外往內：`photo_entity`→`task`→`photo`→`entity`→`folder_correction`→`folder`）；第 2 行先 `CREATE EXTENSION IF NOT EXISTS vector` |
| 5 | 結構靠歷史遷移堆起來 | `db/` 底下確實有 `migrate_folders.sql`、`migrate_design3.sql`、`schema.sql` 三份 |
| 6 | 原圖在 host，DB 只記相對路徑 | `SELECT id, original_path, thumbnail_path` → 照片 3 是 `data/photos/3.jpg`／`data/thumbs/3.jpg`；照片 1、2 是 NULL（舊資料，預期行為） |
| 7 | 鏡頭 token 全在記憶體 | `camera_session_service.py:51` ＝ `_session: CameraSession \| None = None`（模組層變數，不進 DB） |
| 8 | QR 要用區網 IP 開桌面頁 | `camera.py:70` `LOOPBACK_HOSTS`、`:129-130` 落在 loopback 才呼叫 `_lan_host()` |

### 2.2 凍結

host 上跑著的是 **HTTPS 版** uvicorn（PID 14766，
`--host 0.0.0.0 --port 8000 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem`）。
送 `SIGINT`（＝終端機按 `Ctrl+C` 的等效動作）停掉：

```text
lsof -iTCP:8000 -sTCP:LISTEN  →  沒有輸出   ✅
ps -p 14766                   →  行程已結束 ✅
```

### 2.3 快照 → `~/PersonalDocAI-docker遷移前快照.txt`

指令**逐字照抄計畫 §4.3**（G2 的 `diff` 就靠這件事成立）。內容摘要：

```text
photos | folders | entities | pins | tasks | corrections
    37 |      10 |        2 |   11 |     2 |           1

照片 37 列（id 1〜37）：
  id 1、2 → has_file = f（Phase 15 之前的舊照片，沒有原圖，預期行為）
  id 3〜37 → has_file = t
  category 分佈：收據 ×14、文件 ×8、其他 ×4、未分類 ×5、飲食 ×2、
                 風景／專案X／旅遊／專案1／煙霧測試 各 ×1

extension：plpgsql、vector          ✅ vector 在
folder：10 筆（id 1〜6 種子 ＋ 自建的 14 專案X／15 旅遊／16 煙霧測試／17 專案1）
        只有 id=1「未分類」的 is_inbox = t   ✅
vector_dims(embedding)：1024        ✅
```

> ⚠️ **發現一處計畫與現實的落差，已回寫計畫檔**：
> 計畫 §4.3 寫「預期：`folder` 的 id 是 **1〜6**」，但正式庫其實有 **10 筆**——
> 多出來的四筆是 Phase 21 起「自建新資料夾」功能留下的**真實使用者資料**，完全正常。
> 這一條要驗的是「**六筆種子還在、收件箱只有一個**」，不是「總共只有六筆」。
> 已在 `phase-45` §4.3 與 `phase-46` §5.3 各補一則實測說明——
> 否則 Phase 46 對 G2 檢查表時會以為灌錯庫。

### 2.4 兩份備份

```text
~/PersonalDocAI-backup-docker遷移前.sql    480K   純文字（人眼查差異）
~/PersonalDocAI-backup-docker遷移前.dump   189K   自訂格式 -Fc（P46 拿它灌）

自我檢查：
  grep -c "COPY public.photo " …sql  →  1   ✅（≥1）
  grep -c "CREATE EXTENSION"    …sql  →  1   ✅（≥1）
```

兩份都帶 `--no-owner --no-acl`——**這不是可選的**：brew 這邊的擁有者是 macOS 帳號
`linjunting`（§2.1 第 1 條的 `psql -l` 看得到），Docker 官方映像只有 `postgres`，
帶著舊擁有者灌進去會一路噴 `role "linjunting" does not exist`。

### 2.5 收尾檢查

| 檢查 | 結果 |
|---|---|
| 備份沒跑進 repo | `git status --short \| grep -E '\.sql$\|\.dump$\|快照'` → 印「乾淨：…」✅ |
| brew 兩套都還在 | `postgresql@14 started`、`postgresql@17 started` ✅（本 phase 不停任何一個） |
| G1 之前不准建的三個檔 | `ls compose.yaml Dockerfile .dockerignore` → **3 個 No such file** ✅ |
| 8000 埠 | 空 ✅ |

順手把 Docker Desktop 也啟動了（`open -a Docker`，Phase 46 要用）：`docker info` 已回應 → daemon ready。

---

## 3. 測試方式

本 phase **沒有程式碼變更，所以沒有自動化測試**。驗收全靠終端機輸出：

- 八條契約：各自一條 `psql`／`sed`／`grep` 指令，眼睛對
- 凍結：`lsof` ＋ `ps`（兩種方式互相佐證）
- 快照：`cat` 出來逐段確認六個區塊各出現一次（不多不少——`>>` 追加那段跑兩次會變兩份）
- 備份：`ls -lh`（不是 0 位元組）＋ 兩個 `grep -c`（不是空殼）

---

## 4. 遇到的問題與解法

| # | 問題 | 解法 |
|---|---|---|
| 1 | **沒有終端機可以按 `Ctrl+C`**：計畫寫「到跑 uvicorn 的那個視窗按 Ctrl+C」，但那支是產品負責人自己開的 | 用 `kill -INT <pid>` 送 `SIGINT`——那正是 `Ctrl+C` 送出的訊號，等效且更精確（不會誤停別的行程）。事後用 `lsof` ＋ `ps` 兩種方式各驗一次 |
| 2 | **`folder` 有 10 筆，計畫寫 6 筆**：第一眼會懷疑「是不是連錯庫了」 | 對照 `CLAUDE.md` 的 Phase 21 記載（「自建新資料夾」）確認那四筆是真實使用者資料。**沒有動任何資料**，改的是計畫檔的敘述（把「id 是 1〜6」改成「六筆種子還在」），並在 `phase-46` G2 檢查表同步補註——避免下一步誤判 |
| 3 | 計畫 §4.1 第 8 條寫死「QR 要用 `https://192.168.x.x`」，與階段 SSS 的 C4 校準不一致 | 一併改成「`https://<區網IP>`，判準見 `phase-50` §4.3 校準框」，讓七份檔案的說法一致 |

---

## 5. 測試結果

**全數通過。** Phase 45 的 30 個 checkbox 全部打勾（計畫 §4 實作步驟 ＋ §6 驗收清單）。

本 phase 結束時與開工前的差異，**恰好就是計畫 §5 ASCII 圖寫的那兩處**：

```text
・uvicorn 停了（＝凍結，Phase 47 之前維持停著）
・家目錄多出三個檔案：
    ~/PersonalDocAI-docker遷移前快照.txt      ← G2 的對照組
    ~/PersonalDocAI-backup-docker遷移前.sql   ← 後悔藥第 2 層（查差異）
    ~/PersonalDocAI-backup-docker遷移前.dump  ← 後悔藥第 2 層（灌回去）

資料一個字沒動、brew 兩套都還在跑、專案目錄零程式碼變更。
```

---

## 6. 交給 Phase 46 的關鍵數字（G2 就是拿這些來對）

```text
photos 37 ／ folders 10 ／ entities 2 ／ pins 11 ／ tasks 2 ／ corrections 1
extension：plpgsql ＋ vector
folder：id 1〜6 種子 ＋ 自建 14／15／16／17，只有 id=1 is_inbox=t
vector_dims：1024
照片 id 1、2 的 has_file = f（舊資料無原圖，預期）
```
