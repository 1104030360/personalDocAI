# Phase 49：開發熱重載 overlay `compose.dev.yaml`

> 🎯 **提醒：這是 side project，不要過度設計。**

```text
┌─ ⛔ 開工前檢查（兩道閘門）───────────────────────────────────────
│ ✅ **2026-08-24：G1 已通過。** 產品負責人以 dev-prompt
│    `docs/plan/dev-prompts/phase0824.md` 指示「根據 phase-45〜phase-51 進行開發」，
│    並註明「過程中所有的決策都不必徵求任何我的同意」——這就是對 2026-08-23 交出的
│    G1 驗收包（`docs/plan/report/2026-08-23-G1驗收包-請產品負責人確認.md`）的明示放行。
│    下面那句「沒有這句話就停手」保留原文，供日後回看流程用。
│ ① 閘門 G1：產品負責人是否已「明示」G1 通過？沒有就停手（回 phase-44）。
│    G1 是**人**的動作，不是實作者可以自行勾掉的步驟（design4.md §7 明文）。
│ ② 閘門 G2：phase-46 §5.2、phase-47 §4.3 的兩次 diff 都沒有輸出？
│ 兩者都過、而且 phase-48 的常駐模式已經驗收完，才做這一份。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 做一份**只在開發時疊上去**的設定檔，讓你在 Mac 上存檔之後
> 容器裡的 uvicorn 自己重載，不必每次都重建映像。
> **常駐那份 `compose.yaml` 一個字都不改**——開機自動拉起的行程永遠不帶 `--reload`。

**為什麼要分兩份：** 這個專案還在開發，日常會一直改 Python／HTML／CSS。
但「開機自動拉起」的那份如果帶 `--reload`，uvicorn 會一直盯著檔案；
而且無線鏡頭的配對 token 存在記憶體裡，**一重載就配對失效**——
真機驗收到一半突然要重掃 QR，很難查。所以兩種用途分成兩份檔案（design4 D10、§8.4.1）。

**overlay（覆寫檔）是什麼：** `docker compose` 可以一次讀好幾份 yaml，
**後面那份的設定會蓋過前面那份**（清單類的設定另有逐項合併規則，見 §4.1）。
所以 `compose.dev.yaml` 只要寫「要改的那幾項」（啟動指令、掛哪些目錄），
其他（映像、埠、環境變數、`depends_on`）自動沿用 `compose.yaml`。

---

## 1. 對應 design4.md 章節

- **§8.4.1**（整節：為什麼開關寫在 Compose 不是 Dockerfile、兩份的對照表、
  `compose.dev.yaml` 的內容、為什麼要 mount `./app`、不採用 Compose Watch 的理由、
  `--reload` 救不了的四種情況、兩種模式怎麼切換）
- **§8.5**（新建 `compose.dev.yaml`）
- **§8.6 階段丙-3 第 7 步**（遷移驗收過了之後，日常開發改用兩份疊加）
- **D10**（開發熱重載）
- **§1.2**（被否決：常駐 `compose.yaml` 直接加 `--reload`）
- **§8.10**（不做：把 `compose.dev.yaml` 設成開機預設）

---

## 2. 前置條件

- **★ G1、★ G2 都已通過。**
- **Phase 48 已完成**：`docker compose -f compose.yaml up -d` 起得來、
  `curl -k https://127.0.0.1:8000/health` 回 `{"status":"ok"}`、
  `pytest -q` ＝ **402 passed ＋ 2 skipped**。
- **Docker Desktop 正在跑，兩個服務都活著**：

```bash
docker version
docker compose ps
```

  `docker version` 的 Client／Server **兩段都要有輸出**（只有 Client ＝ Docker Desktop 沒開）；
  `docker compose ps` 預期看到 `db` 是 `Up … (healthy)`、`app` 是 `Up …`。

- 本檔所有 `docker compose …` 指令都要在專案根目錄 `/Users/linjunting/personalDocAI` 執行
  ——Compose 是靠「當前目錄有沒有 `compose.yaml`」找設定檔的。

---

## 3. 範圍

### 做

- 新建 `compose.dev.yaml`（內容照 design4 §8.4.1 的原文）。
- 實測兩種模式的切換（常駐 ↔ 開發），並確認 `docker compose ps --no-trunc` 分得出來。
- 實測熱重載真的有效（改一行 HTML／Python，存檔，畫面／行為跟著變）。
- 實測 `logs -f` 的行為（`Ctrl+C` 只離開 log，容器繼續跑）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在 `compose.yaml` 加 `--reload` | design4 §1.2 明文否決。這份 phase 的重點就是「不要動那一份」 |
| 在 `compose.dev.yaml` 寫 `restart: unless-stopped` | 要寫 `restart: "no"`。開發那份若設成自動重啟，**開機時 Docker 會把帶 `--reload` 的版本拉起來**（§8.4.1 註解明寫） |
| 把 `docker compose -f compose.yaml -f compose.dev.yaml up -d` 設成開機預設 | §8.10 明文不做 |
| 用 Docker Compose Watch（`develop.watch` / `docker compose watch`） | §8.4.1 明文：那是「把檔 sync 進容器再重啟服務」，我們已經有 uvicorn 自己的 `--reload`，再加是第二套重啟機制，side project 不夠單純。官方也說 Watch 是 bind-mount 的補充不是替代：<https://docs.docker.com/compose/how-tos/file-watch/> |
| 把 `data/`／`certs/`／`.env` 的掛法改掉 | 開發那份要**與常駐相同**（§8.4.1 的 yaml 註解就是這樣寫的），差別只在多掛一個 `./app` |
| `docker compose down -v` | 刪 volume ＝ 刪正式庫。永遠禁止 |
| 改程式碼 | 本 phase 零程式碼變更（只有一份新的 yaml）。§4.3 為了驗證熱重載會臨時改兩行，**驗完一定要改回來**（§4.3 最後一步用 `git status --short` 確認） |

---

## 4. 實作步驟

### 4.1 建 `compose.dev.yaml`（design4 §8.4.1 原文）

- [x] 在專案根目錄建立 `compose.dev.yaml`：

```yaml
# compose.dev.yaml —— 只在開發疊上去，開機常駐不要帶這份
services:
  app:
    command: >
      uvicorn app.main:app
      --host 0.0.0.0 --port 8000
      --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
      --reload
    volumes:
      - ./app:/app/app          # 原始碼＋static；容器才能看到你剛存的檔
      - ./data:/app/data        # 與常駐相同
      - ./certs:/app/certs
      - ./.env:/app/.env
    restart: "no"               # 開發用 -d 仍不要 unless-stopped，免得開機把 --reload 拉起來
```

> **兩種設定的合併規則不一樣（很重要，不要記反）**：
> `command`／`restart` 這種**單值**設定，後面那份會把前面那份**整個換掉**；
> 而 `volumes` 這種**清單**設定，是以「**容器內的掛載路徑**」當 key **逐項合併**的——
> 只有同一個容器路徑才會被蓋掉，不同路徑兩邊都留著。
> 官方合併規則：<https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/>
>
> **那為什麼還要把四項全部重列**：因為 design4 §8.4.1 的原文就是這樣寫的（本 phase 照抄不改），
> 而且列全了才能一眼看出「開發模式實際掛了哪四個」，不必翻兩份檔案在腦中合併。
> 真的只寫 `./app` 那一行**也不會**弄丟另外三個（合併規則如上），但不要這樣改。
>
> **為什麼一定要 mount `./app`**：`--reload` 盯的是**容器裡的檔案**。
> 若程式只在映像裡、沒掛進來，你在 Mac 上存檔，容器根本看不到，reload 永遠不會觸發。

- [x] 檢查合併後的結果長得對不對（這個指令只解析、不啟動）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml config
```

  預期：`app` 的 `command` 有 `--reload`、`volumes` 有四項、`restart` 是 `"no"`；
  `db` 那一段與常駐完全相同。
  （合併後那四項的順序是「常駐的 `data`／`certs`／`.env` 在前、`./app` 在後」，
  不是 `compose.dev.yaml` 裡的順序——那是合併的結果，不是你寫錯；
  `config` 也會把相對路徑展開成絕對路徑、把 `command` 拆成一個字串陣列，都正常。）

### 4.2 切到開發模式（design4 §8.4.1 的「常駐 → 開發」）

- [x] 先停 app（**db 繼續活著，不必重灌**）：

```bash
docker compose -f compose.yaml stop app
```

- [x] 用兩份疊加起來：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app
```

  `logs -f` 是「跟著看」；`Ctrl+C` 只離開 log，**容器繼續跑**。

- [x] 確認現在跑的是哪一種（**`--no-trunc` 不能省**）：

```bash
docker compose ps --no-trunc
```

  預期：`COMMAND` 欄看得到 `--reload`。
  **不加 `--no-trunc` 會白忙一場**：`docker compose ps` 預設會把 COMMAND 欄截短
  （結尾一個 `…`，像 `"uvicorn app.main:app…"`），而 `--reload` 剛好在這條長指令的
  **最後面**，就這樣被切掉了——於是你會誤以為開發模式沒生效。

> **`-f` 的規矩（記法）**：`-f` 出現幾次、順序都要照抄，而且
> `compose.dev.yaml` 一定放**後面**（後面覆寫前面）。
> 只打 `docker compose up -d` 時，Compose 預設只讀 `compose.yaml`（＝常駐）——
> **在開發模式下手滑打了它，Compose 會發現設定不一樣，把 app 重建成沒有 `--reload` 的版本**，
> 熱重載就這樣安靜地消失了。
> `ps`／`logs` 這種**唯讀**指令，帶不帶 `compose.dev.yaml` 其實都找得到容器
> （同一個專案、同一個服務名 `app`）；但養成「整組照抄」的習慣，
> 就不會有哪一次真的在 `up -d` 上漏掉那一份（design4 §8.4.1 也是這樣寫的）。

### 4.3 實測熱重載真的有效

- [x] 先用瀏覽器開 `https://127.0.0.1:8000/ui/browse.html?tab=folders`，
      **點進任何一個資料夾**——等一下要改的那行提示字就在縮圖牆上方
      （它是 Phase 39 加在 `showFolderPhotos()` 裡的，只有進到資料夾才畫出來）。
- [x] 開著 `logs -f`，在另一個視窗改一行**前端**檔案，例如
      `app/static/browse.html` 裡的那行提示文字（改完記得改回來）：

```text
"點一張照片可以看大圖與完整說明。已定案的照片不能改資料夾。"
   ↓
"點一張照片可以看大圖與完整說明。（熱重載測試）"
```

  存檔後重新整理瀏覽器 → 文字跟著變。
  （靜態檔是每次請求現讀的，所以 HTML／CSS／JS **不需要**等 uvicorn 重載。
  真的沒變的話按 `Cmd`＋`Shift`＋`R` 強制重新整理，先排除瀏覽器快取。）

- [x] 再改一行 **Python**，例如 `app/main.py` 的 `health()`：

```python
    return {"status": "ok"}      →      return {"status": "ok", "hot": "reload"}
```

  存檔後 `logs -f` 那邊應該立刻看到：

```text
WARNING:  WatchFiles detected changes in 'app/main.py'. Reloading...
INFO:     Started server process [...]
```

  然後：

```bash
curl -k https://127.0.0.1:8000/health
```

  預期：`{"status":"ok","hot":"reload"}`。
  **驗完把 `main.py` 改回原樣**，再確認 `curl` 回到 `{"status":"ok"}`。

- [x] `git status --short` 確認沒有把測試用的修改留下來。

### 4.4 切回常駐模式（design4 §8.4.1 的「開發 → 常駐」）

- [x] 停開發那組（**沒有指定服務名 ＝ `db` 也會一起停**；下一步的 `up -d` 會把它帶回來，
      資料住在 volume 裡完全不受影響）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml stop
```

- [x] 用常駐那份起來：

```bash
docker compose -f compose.yaml up -d
docker compose ps --no-trunc
```

  預期：`COMMAND` 欄**看不到** `--reload`。
  （畫面上會看到 app 被 `Recreated`——設定變了就一定會重建 container，這是正常的。）

- [x] 確認服務仍正常：

```bash
curl -k https://127.0.0.1:8000/health
```

### 4.5 記住「`--reload` 救不了」的四種情況（design4 §8.4.1）

這四種情況存檔沒用，必須手動處理：

| 情況 | 為什麼救不了 | 怎麼辦 |
|---|---|---|
| 改 `.env` | `app/core/config.py` 在 import 時讀一次，沒有 `.py` 變動就不會重載 | `docker compose -f compose.yaml -f compose.dev.yaml restart app`。⚠ 但 `DATABASE_URL` 與 `OLLAMA_BASE_URL` 這**兩個**由 `compose.yaml` 的 `environment` 覆蓋（`python-dotenv` 不覆寫既有環境變數），在容器裡改 `.env` 的這兩行**怎麼 restart 都不會變**——那是刻意的（phase-48 §4.3、§7 陷阱 4）。要改它們得改 `compose.yaml` |
| 改 `requirements.txt` | 套件裝在映像裡，不在掛進去的原始碼裡 | `docker compose build app`，再 `docker compose -f compose.yaml -f compose.dev.yaml up -d` |
| 改 `certs/` | HTTPS 行程已經握著舊憑證 | 同上面那條 `restart app`（兩份 yaml 都要帶） |
| 正在配對無線鏡頭 | reload ＝ token 清空（Phase 36 既有行為，記憶體 session） | 重產 QR、重掃一次 |

---

## 5. ASCII 圖：兩種模式

```text
   同一個專案、同一個 db、同一個 pgdata volume、同一個 app 容器名
   差別只在「這次指令帶了哪幾份 yaml」

   ┌──────────────────────── 常駐（開機自動拉起）─────────────────────────┐
   │  docker compose -f compose.yaml up -d                                │
   │                                                                      │
   │  app 的啟動指令：uvicorn …（**沒有** --reload）                      │
   │  原始碼：打進映像                                                    │
   │  volumes：data／certs／.env                                          │
   │  restart：unless-stopped  ← 開機由 Docker Desktop 自動拉起           │
   │  改碼要生效：重建映像（docker compose build app）                    │
   │  鏡頭 session：穩，除非你手動重啟 container                          │
   └──────────────────────────────────────────────────────────────────────┘
                    ▲                              │
       docker compose -f compose.yaml \            │  docker compose -f compose.yaml stop app
         -f compose.dev.yaml stop                  │  （db 繼續活著，不必重灌）
                    │                              ▼
   ┌──────────────────────── 開發（日常改碼）─────────────────────────────┐
   │  docker compose -f compose.yaml -f compose.dev.yaml up -d            │
   │  docker compose -f compose.yaml -f compose.dev.yaml logs -f app      │
   │                                                                      │
   │  app 的啟動指令：uvicorn … --reload                                  │
   │  原始碼：bind-mount ./app → /app/app（容器看得到你剛存的檔）         │
   │  volumes：app／data／certs／.env（四項照 design4 原文全列）          │
   │  restart："no"   ← 免得開機把帶 --reload 的版本拉起來                │
   │  改碼要生效：存檔即可（Python 會重載；HTML/CSS/JS 直接重新整理）     │
   │  鏡頭 session：一存檔就失效（與現在 host 開 --reload 相同）          │
   └──────────────────────────────────────────────────────────────────────┘

   怎麼知道現在是哪一種：docker compose ps --no-trunc → COMMAND 欄有沒有 --reload
                        （不加 --no-trunc 會被截短，--reload 在最後面看不到）
   切換當下 app 一定重啟一次 → 鏡頭 token 清空、QR 要重產。
   資料庫與 data/ 的照片完全不受影響。
```

---

## 6. 驗收清單

- [x] `compose.dev.yaml` 存在，內容與 design4 §8.4.1 的原文一致
      （`command` 有 `--reload`、`volumes` 四項、`restart: "no"`）
- [x] `docker compose -f compose.yaml -f compose.dev.yaml config` 合併結果正確
- [x] 切到開發模式後 `docker compose ps --no-trunc` 的 COMMAND 欄**有** `--reload`
- [x] 改一行 Python 存檔 → `logs -f` 看得到 `Reloading...`、`curl` 反映新行為
- [x] 改一行 HTML 存檔 → 重新整理瀏覽器就看得到（不需要重載）
- [x] `Ctrl+C` 離開 `logs -f` 之後，`docker compose ps` 顯示容器**仍在跑**
- [x] 切回常駐模式後 `docker compose ps --no-trunc` 的 COMMAND 欄**沒有** `--reload`，
      `/health` 仍 200
- [x] 切回常駐之後 `pytest -q` 仍是 **402 passed ＋ 2 skipped**
      （本 phase 沒動程式碼、沒動資料庫，顆數不該有任何變化）
- [x] `compose.yaml` **一個字都沒改**——用 grep 驗，**不要**用 `git diff`：

```bash
grep -n -- "--reload" compose.yaml | grep -v "#"   # 預期：沒有輸出
grep -n "5433" compose.yaml          # 預期：看得到 127.0.0.1:5433:5432（Phase 47 改的那一行）
```

  （**2026-08-24 校準**：原本寫的是不接 `| grep -v "#"` 的版本，但那樣**一定會有一行輸出**
  ——`compose.yaml` 第 3 行本來就有一句警語註解「永遠不要在這裡加 uvicorn 的 `--reload`」，
  那是計畫自己給的檔案內容。要驗的是「有沒有真的設定」，所以要把註解行濾掉。）
  （`compose.yaml` 是 Phase 46 新建、依產品負責人指示**還沒 commit** 的檔案＝「未追蹤」，
  所以 `git diff compose.yaml` 永遠是空的、證明不了任何事——phase-47 §6 有同一則提醒。）

- [x] 測試用的臨時修改都已還原：`git status --short` 裡**沒有** `app/` 底下的檔案
- [x] 版控狀態符合預期（**用 `git status --short`，不要用 `git diff --stat`**——
      新建的檔案是未追蹤的，`git diff --stat` 根本看不到它）：
      本 phase 只多出一個 `?? compose.dev.yaml`；
      **2026-08-24 校準**——此時工作區裡「應該有」的東西是固定的這幾樣：
      `?? compose.yaml`、`?? compose.dev.yaml`、`?? Dockerfile`、`?? .dockerignore`、
      `?? db/docker-init/`（P46／P48／P49 新建）、` M tests/conftest.py`（P47 改）、
      加上 `docs/` 底下的計畫檔／TODO／REP。
      **`git status --short -- app/` 必須是空的**（Phase 38〜44 已進 commit `507a18f`；
      §4.3 為了驗熱重載臨時改的 `app/main.py`、`app/static/browse.html` 若沒還原，
      就會在這裡現形——這也正是這一條最有價值的地方）

---

## 7. 常見陷阱

1. **以為 `volumes` 是「整段覆寫」**：**不是。** Compose 合併多份檔案時，
   `command`／`restart` 這種單值設定才是整個換掉；`volumes` 是**以容器內的掛載路徑逐項合併**
   （同路徑才蓋掉）。所以就算只寫 `./app` 那一行，`data`／`certs`／`.env` 也不會消失。
   本 phase 四項全列是照 design4 §8.4.1 原文、也是為了「一眼看得懂」，不是為了「怕弄丟」。
   對合併結果沒把握時，**跑 `docker compose -f compose.yaml -f compose.dev.yaml config` 看**，
   那是唯一不會記錯的方法。官方規則：
   <https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/>

2. **在 dev overlay 寫 `restart: unless-stopped`**：開機時 Docker Desktop 會把它拉起來，
   於是「常駐」變成帶 `--reload` 的版本——正是 design4 要避免的事。一定是 `restart: "no"`。
   反過來說也要有心理準備：**停在開發模式時重開 Docker Desktop，`db` 會自己回來、`app` 不會**
   （`restart: "no"` 就是這個意思）。那是刻意的，不是壞掉——重新 `up -d` 一次就好，
   或是照 §4.4 切回常駐再收工。

3. **`-f` 忘了帶或順序寫反**（兩種後果都很難察覺）：
   - `docker compose up -d`（忘了帶 `-f compose.dev.yaml`）＝ Compose 發現設定不同，
     **把 app 重建成常駐版**，`--reload` 靜悄悄消失，你還會以為熱重載壞了；
   - `-f compose.dev.yaml -f compose.yaml`（順序反了）**更陰險**：常駐那份**沒有**寫 `command`
     （啟動指令在 `Dockerfile` 的 `CMD` 裡），所以 `--reload` 反而**不會**消失，
     但 `restart` 會被覆寫成 `unless-stopped`——正好變成「開機自動拉起一個帶 `--reload` 的 app」，
     也就是 design4 §1.2／§8.10 最不想要的結果，而且畫面上完全看不出來。
   **`compose.dev.yaml` 永遠放最後**；不確定就先 `config` 一次，確認 `restart` 是 `"no"`。

4. **以為 `logs -f` 的 `Ctrl+C` 會停掉服務**：不會，那只是離開 log。
   要停服務用 `docker compose … stop`。（順帶一提：`logs` 的 `-f` 是 follow，
   `compose` 的 `-f` 是 file，兩個 `-f` 意思完全不同——這是最容易混淆的一點。）

5. **改了 `.env` 卻等 reload**：不會觸發（沒有 `.py` 變動）。要 `restart app`。

6. **改了 `requirements.txt` 卻只 `up -d`**：套件在映像裡，要 `docker compose build app`。

7. **開發模式下做鏡頭真機驗收**：每存一次檔配對就失效。真機驗收一律用常駐模式
   （`docker compose -f compose.yaml up -d`，不帶 dev）。

8. **兩種模式同時 `up`**：不會有兩個 app（容器名相同，後者會取代前者），
   但你會搞不清楚現在是哪一種。**先 `stop` 再 `up`**，並用 `docker compose ps --no-trunc` 確認。

9. **存檔了，`logs -f` 卻一點反應都沒有**：uvicorn 的 `--reload` 是靠 `watchfiles` 這個套件
   監看檔案變動（`requirements.txt` 的 `uvicorn[standard]` 會把它一起裝進來），
   而變動通知要從 Mac 穿過 Docker Desktop 的檔案共享層傳進容器，偶爾會傳不到。
   先依序確認三件事：
   ① 你改的是 `app/` 底下的 **`.py`**（`--reload` 預設只認 `.py`；HTML/CSS/JS 本來就不會觸發重載）；
   ② `docker compose ps --no-trunc` 的 COMMAND 真的有 `--reload`；
   ③ `docker compose exec app ls -l app/main.py` 看得到你剛存檔的時間（＝掛載是通的）。
   三項都對還是沒動靜，就讓它改用「定時輪詢」——在 `compose.dev.yaml` 的 `app` 底下加：

```yaml
    environment:
      WATCHFILES_FORCE_POLLING: "true"   # 收不到檔案變動通知時的備案，能不加就不加
```

   （這是 `watchfiles` 自己的開關，可在 `.venv/lib/python3.12/site-packages/watchfiles/main.py`
   的 `_default_force_polling()` 看到；它只會在 WSL 上自動開啟，macOS 的 Docker **不會**自動開。
   輪詢比較吃 CPU，而且加了之後這一份就跟 design4 §8.4.1 的原文有出入——
   真的要加就在檔案裡補一行註解說明原因。）
