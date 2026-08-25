# Phase 50：階段丙-4 —— 開機常駐、鏡頭驗證、文件更新與階段丙收尾

（檔名沿用 `phase-50-丙4開機常駐與增量收尾.md` 不改——總覽 §2／§3.1／§3.4／§5
與 `phase-47` §4.3 都**指名**引用這個檔名，改掉會讓那些連結全部失效。
增量四真正的最後一步是 `phase-51`，見下方 📌）

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
│ ② 閘門 G2：phase-46／phase-47 的兩次 diff 都沒有輸出？
│ 兩者都過，而且 phase-48（常駐）與 phase-49（開發 overlay）都驗收完，才做這一份。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 讓電腦開機之後服務**自己回來**（不必開終端機打指令），
> 確認無線鏡頭在容器化之後仍然可用，把 `CLAUDE.md` 的指令區改成新的現實，
> 最後跑完 design4 §8.9 的十條總驗收——**Docker 這條線（階段丙）到此完結**。

> 📌 **本檔不是增量四的最後一個 phase。** 後面還有
> `phase-51-規格摘標與詢問三路驗收.md`（產品負責人 2026-08-23 額外裁決：
> 把 `自然語言詢問.feature` 那兩條 `@未實作` 的 Rule 摘標）。
> ⚠ 它**不在 design4.md 的範圍內**——授權來源是**人**（產品負責人），不是設計文件，
> 所以你在 design4 裡找不到它；總覽 §3.4「裁決二」是它的正式紀錄。
> 它與 Docker 完全無關、不需要 G1／G2，所以排在最後——**排在前面會讓
> design4 §7 的 G1（「既有 2 skipped 仍 skip」）與 §8.9（「與遷移前同顆數」）對不上**。
> 本檔的顆數一律是 **402 passed ＋ 2 skipped**；變成 404 ＋ 0 是 Phase 51 的事。

---

## 1. 對應 design4.md 章節

- **§8.6 階段丙-4**（三個步驟：Docker Desktop 開機啟動、只用 `compose.yaml`、Ollama 開機啟動）
- **§8.7**（拍照會不會壞：五條；QR 裡的 IP 是唯一高風險）
- **§8.8**（備份與回復：日常備份指令、絕對禁止的兩件事、後悔藥兩層）
- **§8.9**（階段丙驗收十條）
- **§8.5 最後一列**（`CLAUDE.md` 指令區改寫）。
  倒數第二列的 `app/api/routers/camera.py` `LAN_HOST` 是 design4 標明的**可選**項——
  **產品負責人 2026-08-23 裁決：本增量明確不做**（見 §3「明確不做」最後一列）
- **§8.10**（不做：把 `compose.dev.yaml` 設成開機預設）
- **§8.11**（風險第 5 列：QR 猜到 Docker 網橋 IP；第 6 列：Ollama 沒開機啟動）

---

## 2. 前置條件

- **★ G1、★ G2 都已通過。**
- **Phase 45〜49 全部完成。** 目前狀態應該是：
  - `docker compose ps` → `db`（healthy，`127.0.0.1:5433->5432`）＋ `app`（`0.0.0.0:8000->8000`）
  - `brew services list` → `postgresql@17` 是 `stopped`、`postgresql@14` 是 `started`
  - `pytest -q` ＝ 402 passed ＋ 2 skipped
  - 專案根目錄有 `compose.yaml`、`compose.dev.yaml`、`Dockerfile`、`.dockerignore`、`db/docker-init/`
- ⚠ **本檔所有 `docker compose …` 指令都要在專案根目錄
  `/Users/linjunting/personalDocAI` 執行**——Compose 是靠「當前目錄有沒有 `compose.yaml`」
  找設定的，在別的目錄下它會說找不到設定檔。`pytest` 那幾步另外還要先
  `source .venv/bin/activate`。

---

## 3. 範圍

### 做

- Docker Desktop 設成登入時自動啟動。
- Ollama 設成開機啟動。
- 確認 `restart: unless-stopped` 只在 `compose.yaml`（不在 dev overlay）。
- 重開 Docker Desktop（或重開機）實測服務自己回來。
- 無線鏡頭在容器化後的驗證（用**區網 IP** 開桌面頁，看 QR 網址）。
- 改寫 `CLAUDE.md` 的指令區與現況段。
- 跑 design4 §8.9 的十條總驗收。
- **階段丙**收尾（`unfinish/` → `finish/` 的歸檔約定、不 commit）。
  增量四的最後一步是 `phase-51`（規格摘標），**本檔不做、也不要提前打它的勾**。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 把 `compose.dev.yaml` 設成開機預設 | design4 §8.10 明文。開機拉起的行程不准帶 `--reload` |
| 讓 `brew services` 把 `postgresql@17` 設成開機啟動 | §8.6 丙-4 最後一句明文。兩套庫並存會非常混亂 |
| 動 `postgresql@14` 的開機設定 | 別的專案的，**維持原樣** |
| `brew uninstall postgresql@17`、刪它的資料目錄 | §8.10：第一個穩定週期內保留後悔藥 |
| `docker compose down -v`、`docker volume rm …pgdata` | §8.8 明文「絕對禁止」（在沒有新備份時）＝刪正式庫 |
| 為了 QR 的 IP 問題去接 STUN／TURN | §8.10 明文不做。用區網 IP 開頁就解決了 |
| 改任何產品行為（歸類、詢問、彈窗鏈、詳情窗） | §8.10 最後一列：本階段不改產品行為。**本檔沒有任何例外**——連 design4 標為「可選」的 `LAN_HOST` 也不做（見下一列） |
| **加 `LAN_HOST` 環境變數覆寫 `camera.py` 的 `_lan_host()`** | **產品負責人 2026-08-23 裁決：本增量明確不做。**<br>① design4 §8.5 把它寫成「**可選**」、§8.7 最後一句明說它「**不是遷移成功的必要條件**」——它從來就不是驗收項。<br>② QR 猜錯 IP 的**唯一**起因是「桌面頁用 `localhost`／`127.0.0.1` 開」；`_phone_url()` 優先沿用「你是用什麼網址開這一頁的」，所以**改用 `https://<區網IP>:8000` 開頁就沒事**，一行程式都不必寫（替代做法見 §4.3）。<br>③ 不做它，收尾顆數就乾淨地維持 **402 passed ＋ 2 skipped**（不會出現 403 那個分岔）。<br>④ 日後真的遇到非它不可的情境（例如桌面頁一定得從別台機器用主機名開），**再另案處理**——本增量不寫程式、不寫測試、不改 `compose.yaml` |
| `git commit` | 沿用產品負責人既有指示：改完先檢視。歸檔 `unfinish/`→`finish/` 隨 commit 執行 |

---

## 4. 實作步驟

### 4.1 開機常駐（design4 §8.6 丙-4）

- [x] **Docker Desktop**：選單列的鯨魚圖示 → Settings → General →
      勾選 **Start Docker Desktop when you sign in**。
      **2026-08-24 實作者的做法（等價，可回溯）**：GUI 沒辦法用指令點，所以改成直接改設定檔——
      `~/Library/Group Containers/group.com.docker/settings-store.json` 的
      `AutoStart` 由 `False` 改成 `True`。**改之前先備份**成
      `settings-store.json.bak-2026-08-24`，而且是在 `docker desktop stop` 之後才改
      （Docker Desktop 活著時改，它退出時會用記憶體裡的舊值覆寫回去）。
      改完 `docker desktop start`，重新讀出來確認仍是 `True`。
- [x] **確認 `restart` 政策只在常駐那份**：

```bash
grep -n "restart" compose.yaml compose.dev.yaml
```

  預期：`compose.yaml` 的 `db` 與 `app` 各有 `restart: unless-stopped`；
  `compose.dev.yaml` 的 `app` 是 `restart: "no"`。

- [x] **確認現在跑的是常駐模式**（不是 dev overlay）：

```bash
docker compose ps --no-trunc
```

  預期：`COMMAND` 欄**看不到** `--reload`。
  ⚠ **`--no-trunc` 不能省**：不加的話 COMMAND 只顯示開頭 20 個字左右
  （長得像 `"uvicorn app.main:a…"`），而 `--reload` 是**接在最後面**的——
  你會看到「沒有 `--reload`」而以為過關，其實是根本沒顯示到那裡
  （phase-48 §7 陷阱 10 已經踩過這一條）。
  真的看得到 `--reload` 就先切回去：

```bash
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d
```

- [x] **Ollama 開機啟動**（**2026-08-24 實作者用的是計畫自己列的第二條路**：
      `osascript -e 'tell application "System Events" to make login item at end
      with properties {path:"/Applications/Ollama.app", hidden:false}'`，
      驗證方式是再把登入項目列出來、確認 `Ollama` 在裡面。
      要移除的話：`osascript -e 'tell application "System Events" to delete login item "Ollama"'`）：
      打開 Ollama 應用程式 → 設定裡勾「Launch on login」
      （不同版本文字略有不同；也可以用 macOS 的「系統設定 → 一般 → 登入項目」加進去）。
      **這一步不能省**：embedding 與本機看圖都靠它，沒開的話上傳會 500——
      而 Docker Desktop 救不了它（design4 §8.11 風險第 6 列）。

### 4.2 實測「自己回來」（design4 §8.9 最後一條）

> ⚠️ **實測之前，兩個容器一定要是「跑著」的狀態。** `restart: unless-stopped` 的
> `unless-stopped` 就是字面意思：**你自己用 `stop` 停掉的容器，Docker 不會替你叫醒**。
> 所以如果 §4.1 你走了「切回常駐」那條路，最後一個動作必須是
> `docker compose -f compose.yaml up -d`，不能停在 `stop`——否則這一節怎麼測都不會回來，
> 而你會以為是 `restart` 政策沒生效。先 `docker compose ps` 看兩個都是 `Up` 再往下。

- [x] 完全結束 Docker Desktop（鯨魚圖示 → Quit Docker Desktop），等它真的關掉。
- [x] 重新打開 Docker Desktop，**什麼指令都不要打**，等 30〜60 秒。

> ⚠️ **那 30〜60 秒不是客套話，前幾秒的 500 是預期的。** `compose.yaml` 的
> `depends_on: condition: service_healthy` **只在 `docker compose up` 時生效**；
> 重開機（或重開 Docker Desktop）時，容器是 Docker daemon 依 `restart: unless-stopped`
> 直接拉起來的，**不會**等 db 變 healthy。`app/db/session.py` 是**每個請求**才
> `psycopg.connect()`，所以 app 照樣起得來、只是 db 還沒好的那幾秒請求會 500，
> db 一 healthy 就自動恢復——**不是 bug，不用改設定**。
> 所以下面那兩條指令請等 `docker compose ps` 的 `db` 顯示 `(healthy)` 之後再打。
- [x] 檢查：

```bash
docker compose ps
curl -k https://127.0.0.1:8000/health
```

  預期：兩個服務都 `Up`、`/health` 回 `{"status":"ok"}`。

- [ ] **（更完整，建議做）真的重開機一次**，開機後不打任何指令，
      直接用瀏覽器開 `https://127.0.0.1:8000/ui/upload.html` → 頁面出得來。
      **2026-08-24：未做，刻意留白。** 實作者不應該在產品負責人外出時重開他的電腦
      （會關掉他所有開著的東西）。已做的是**等價但較輕的**那一半：
      `docker desktop stop` → `docker desktop start` → **完全不下任何 `up` 指令**，
      兩個容器 15 秒內自己回來、`/health` 200。真正的「重開機」留給產品負責人順手驗。

### 4.3 無線鏡頭在容器化之後的驗證（design4 §8.7）

**唯一高風險是 QR 裡的 IP。** 原因：`app/api/routers/camera.py` 的 `_phone_url()` 會優先沿用
「桌面是用什麼網址開這一頁的」；只有在 host 落在 `LOOPBACK_HOSTS`
（`localhost`／`127.0.0.1`／`::1`／`0.0.0.0` 這幾個「指向自己」的位址）時，才退而用
`_lan_host()`（UDP socket 戲法）猜區網 IP。**在容器裡猜**很可能猜出 Docker 內部網段的 `172.x`，
手機連不到。

> 這一節同時也是 **Phase 36 一直掛著的「真機（iPhone）驗收」**——CLAUDE.md 現況段記著它
> 「待產品負責人手動」。做完這一節就可以把那一項一起結掉。

- [x] 先查本機區網 IP：

```bash
ipconfig getifaddr en0
```

> ⚠️ **2026-08-24 校準：判準從「看前綴」改成「跟 `en0` 逐字比對」。**
> 原文寫「必須是 `192.168.…`、**不可以是 `172.…`**」。這條規則在**這台機器上是錯的**：
> 本次實測 `ipconfig getifaddr en0` ＝ **`172.29.93.122`**——`172.16.0.0/12` 也是合法的
> 私有網段（RFC 1918），它是**真的區網 IP**，不是 Docker 網橋。
> 更麻煩的是：Docker 預設的網段池正好也在 `172.17`〜`172.31`，
> **光看 `172.` 這個前綴，根本分不出「真區網」與「Docker 內部網段」。**
>
> **正確的判準只有一個：QR 裡的 host 必須逐字等於 `ipconfig getifaddr en0` 的輸出。**
> 這個判準在任何網段下都成立（家裡的 192.168、熱點的 172.20、公司的 10.x 都一樣），
> 而且不必去記 Docker 用哪些網段。

- [x] **憑證要涵蓋這個 IP**（mkcert 把 IP 寫死在 SAN 裡；不對的話手機會被 Safari 擋，
      而且錯誤訊息看起來像「網路怪怪的」）：

```bash
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
ipconfig getifaddr en0
# 上面那份清單裡沒有下面這個 IP → 重簽，然後 docker compose restart app
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

  （2026-08-24 實測：憑證原本簽的是舊 IP `172.20.10.6`，與現在的 `172.29.93.122` 對不上，
  phase-48 §2 已經把「開工前先檢查 SAN」寫進前置條件。）

- [x] **用區網 IP 開桌面頁**（不要用 localhost）：

```text
https://<剛才查到的 IP>:8000/ui/camera-desk.html
```

- [x] 看畫面上顯示的手機網址／QR 內容：**必須逐字等於 `ipconfig getifaddr en0` 的輸出**
      （design4 §8.9 第 9 條；判準的校準理由見上面那個說明框）。
      **這一項實作者自己驗得到**——用瀏覽器開桌面頁、把畫面上的網址跟 `en0` 對一下即可，
      不需要手機。
- [x] 🙋 **【產品負責人 2026-08-25 已完成】** 用 iPhone（同一個 Wi-Fi）掃 QR → 開得起來、要鏡頭權限 →
      桌面看得到即時預覽 → 按快門 → 桌面跳出三關彈窗鏈。
      （憑證信任步驟見 `CLAUDE.md` 指令區；換手機才要重做。）
      **2026-08-24 產品負責人指示：需要用到手機的部分停下來交給他手動測**，
      實作者做到「QR 網址正確」為止，真機那一段列為待驗項、不自行勾選。

- [x] **QR 的 IP 跟 `en0` 對不上怎麼辦（不改程式的解法，30 秒）**：

  九成九是因為那個分頁是用 `localhost`／`127.0.0.1` 開的。
  `_phone_url()` 的規則是「**優先沿用你開這一頁時用的網址**」，
  只有當網址落在 `LOOPBACK_HOSTS`（`localhost`／`127.0.0.1`／`::1`／`0.0.0.0`）
  這幾個「指向自己」的位址時，才退而用 `_lan_host()` 去猜——
  而在容器裡猜，猜到的就是 Docker 內部網段的 `172.x`。

  ```text
  ✗ https://localhost:8000/ui/camera-desk.html      → 走猜的 → QR 可能是 Docker 網段
  ✓ https://<ipconfig getifaddr en0 的輸出>:8000/ui/camera-desk.html
                                                    → 沿用你打的 IP → QR 一定跟它一樣
  ```

  ⚠️ **2026-08-24 校準：不要用「是不是 172 開頭」判斷。** 這台 Mac 的區網 IP
  本來就是 `172.29.93.122`（合法私有網段），而 Docker 的網段池也在 `172.x`
  ——唯一可靠的判準是「QR 的 host **逐字等於** `ipconfig getifaddr en0` 的輸出」。

  **處置：** 關掉那個分頁，用上一步 `ipconfig getifaddr en0` 查到的 IP 重開一次，
  QR 就會跟著變。這是**操作慣例**，不是 workaround——桌面頁本來就該用區網 IP 開
  （`CLAUDE.md` 指令區從 Phase 36 起就是這樣寫的）。

  ⛔ **不要為了它加 `LAN_HOST` 環境變數覆寫。** 產品負責人 2026-08-23 裁決：
  **本增量明確不做**（理由與日後的處理方式見 §3「明確不做」最後一列）。
  本檔的顆數因此一律是 **402 passed ＋ 2 skipped**，沒有 403 這個分岔。

### 4.4 改寫 `CLAUDE.md` 的指令區（design4 §8.5 最後兩列）

- [x] **啟動伺服器**那一段：把 `uvicorn app.main:app --reload --port 8000` 換成 Docker 版本，
      並保留「怎麼切換兩種模式」的說明（指向 design4 §8.4.1）：

```bash
# 常駐（開機也是用這一份自動拉起；沒有 --reload）
docker compose -f compose.yaml up -d

# 日常開發（熱重載；兩份疊加，compose.dev.yaml 一定放後面）
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app
#   logs -f ＝跟著看，Ctrl+C 只離開 log，容器繼續跑

# 現在跑的是哪一種：看 COMMAND 欄有沒有 --reload
# --no-trunc 不能省：不加的話 COMMAND 只印開頭 20 個字左右，結尾的 --reload 根本不會顯示
docker compose ps --no-trunc

# 切換（切換當下 app 一定重啟一次 → 鏡頭 token 清空、QR 要重產）
docker compose -f compose.yaml stop app                       # 常駐 → 開發（第一步）
docker compose -f compose.yaml -f compose.dev.yaml up -d      # 常駐 → 開發（第二步）
docker compose -f compose.yaml -f compose.dev.yaml stop       # 開發 → 常駐（第一步）
docker compose -f compose.yaml up -d                          # 開發 → 常駐（第二步）

# ⛔ 絕對不要跑 `docker compose down -v`：-v 會刪掉 pgdata volume ＝ 刪正式庫。
#    要停服務一律用 `docker compose stop`。
```

- [x] **HTTPS 那一段**：原本的 `uvicorn --ssl-keyfile …` 指令改成註明
      「憑證由 compose bind-mount 進容器，啟動指令寫在 `Dockerfile`／`compose.dev.yaml`」；
      mkcert 的產憑證步驟與 iPhone 信任步驟**保留不動**（那些仍然是在 Mac 上做的）。
      補一句：**區網 IP 換了要重簽憑證**，重簽完 `docker compose restart app`。

- [x] **資料庫那一段**：`psql` 全部補 `-h 127.0.0.1 -U postgres`（含既有那三條
      `psql -d … -f db/*.sql`），並註明 brew `@17` 已停：

```bash
# 資料庫現在跑在 Docker 裡（brew 的 postgresql@17 已於增量四停用，資料目錄留著當後悔藥）
# ~/.zshrc 三個變數都生效：PGPORT=5433（本來就有）＋ PGUSER=postgres、PGHOST=127.0.0.1
# （後面兩個是 Phase 47 §4.4 新加的），所以互動 shell 可以直接：
psql -d PersonalDocAI        # 正式庫（Docker）
psql -d PersonalDocAI_test   # 測試庫（Docker）
# 明寫參數的版本（腳本裡建議這樣寫）：
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI

# ⚠️ postgresql@14（5432 埠）仍然是別的專案（wanderlove、fse_chat_room）的，絕不可停用或修改。
```

  ⚠ `PGHOST=127.0.0.1` **不能漏**：不寫主機時 `psql` 走的是 Unix socket
  （`/tmp` 底下的特殊檔案），而 Docker 只把埠用 TCP 發佈出來、**沒有** socket 檔——
  漏了它，`psql -d PersonalDocAI` 會噴
  `connection to server on socket "/tmp/.s.PGSQL.5433" failed`
  （phase-47 §4.4 加這一行的理由就在這裡）。

- [x] **新增「日常備份」一段**（design4 §8.8 原文，指令逐字照抄）：

```bash
# 日常備份（擇一即可）
# 方式 A：在容器裡倒，再抓出來。注意這一份沒有 -Fc ＝純文字 SQL（副檔名雖然叫 .dump），
#         要灌回去是用 psql -f，不是 pg_restore。
docker compose exec db pg_dump -U postgres -d PersonalDocAI --no-owner --no-acl \
  -f /tmp/PersonalDocAI.dump
docker compose cp db:/tmp/PersonalDocAI.dump ~/PersonalDocAI-backup-$(date +%F).dump

# 方式 B：或在 host（這一份有 -Fc ＝自訂格式，灌回去用 pg_restore）：
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump
```

- [x] **`pytest` 那一段**：加一句「測試仍在 host 跑（不進 container），連的是 Docker 裡的
      `PersonalDocAI_test`；`docker compose ps` 的 `db` 要是 `Up (healthy)` 才跑得起來」。

- [x] **現況段（檔案最前面那一大段）**：補上增量四的成果——
      照片詳情端點與唯讀彈窗、AI 計時 log 五種 kind、Docker 常駐與正式庫遷移；
      數字更新為 **`pytest -q` ＝ 402 passed ＋ 2 skipped**、**端點 20**、
      **正式庫在 Docker（`127.0.0.1:5433`），brew `@17` 已停**。
      順手把現況段兩句**已經過期**的話一併更正（都不是增量四造成的，但改到這一段就一起清乾淨）：
  - 「Phase 34〜37 與 AI 後端開關**未 commit**」——已經進 commit `6392270` 了。
    複驗指令（挑一個那次 commit 才出現的檔案，看它最後一次被 commit 是哪一筆）：

    ```bash
    git log --oneline -1 -- app/services/camera_session_service.py
    # 預期印出：6392270 feat: Phase 34〜37＋AI 後端切換……
    ```

    ⚠ **不要**用 `git status` 判斷這件事——`git status` 只告訴你「現在有什麼沒提交」，
    不會告訴你「某個檔案上次是哪一筆 commit 進去的」。要問後者就得用 `git log`（上面那條）。
    **2026-08-24 校準**：原文接著寫「做到這裡 `app/`、`tests/` 一定是一大片未提交的變更」——
    那個前提已經不成立了。**Phase 38〜44 已於 2026-08-23 進 commit `507a18f`**，
    所以做到這裡 `git status --short -- app/` 應該是**空的**；
    未提交的只有階段丙新建的 `compose.*`／`Dockerfile`／`.dockerignore`／`db/docker-init/`、
    Phase 47 改的 `tests/conftest.py`，以及 `docs/` 底下的計畫檔與 TODO／REP。
  - 「phase-36 的真機（iPhone）驗收**待產品負責人手動**」——§4.3 做完就結掉了，改成已完成並註明日期。
  - 另外，本機模型那句「自 2026-08-22 改用 MLX 標籤 `gemma4:e2b-mlx`」講的其實**只有文字模型**
    （`.env` 目前是 `VLM_MODEL=gemma4:e2b`、`LLM_MODEL=gemma4:e2b-mlx`）；
    順手補上「看圖那顆沒有 `-mlx`」，免得下一個人照著它去對 `kind=vlm` 的 log 對不上
    （phase-42 §4.7 有同一則提醒）。

### 4.5 design4 §8.9 十條總驗收（逐條執行）

- [x] ① 六張表的列數與遷移前快照相同——**比對的是 Phase 45 與 Phase 47 那兩份存檔**：

```bash
diff <(tail -n +2 ~/PersonalDocAI-docker遷移前快照.txt) \
     <(tail -n +2 ~/PersonalDocAI-docker切埠後快照.txt)
```

  預期：**沒有任何輸出**（＝搬家那一刻資料逐字相同，這是這一條真正要證明的事）。

> ⚠️ **不要「現場再跑一次查詢」來對這一條，會白白嚇自己一跳。**
> 切埠之後，Phase 47 §4.5、Phase 48 §4.5 與下面第 ⑦ 條各上傳了一張測試照片，
> 所以**現在的 `photo` 列數一定比遷移前多**（多幾張要看你實際傳了幾張）。
> 那是**預期中的新增資料**，不是搬丟了。真的想現場對，就用
> 「現在的列數 −（搬完之後上傳的張數）＝ 遷移前列數」自己算一次，
> 別直接拿去 `diff` 那兩個存檔。

- [x] ② `vector` extension 在；任一照片 `vector_dims(embedding)` ＝ **1024**：

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
  -c "SELECT extname FROM pg_extension ORDER BY extname;" \
  -c "SELECT id, vector_dims(embedding) FROM photo ORDER BY id LIMIT 1;"
```

  預期：第一段的清單裡看得到 `vector`；第二段那一列的 `vector_dims` 是 `1024`。

- [x] ③ brew `@17` 是 `stopped`；`@14` 仍 `started` 且 5432 沒被本專案佔用：

```bash
brew services list | grep postgresql
lsof -iTCP:5432 -sTCP:LISTEN
```

  預期：第一條印出 `postgresql@14 started`、`postgresql@17 stopped`（或 `none`）；
  第二條印出的是 **brew `@14` 的 `postgres` 行程**——那是**別的專案**的，
  本來就該在那裡聽，**看到它是正常的、不准去停它**。
  要確認的只有一件事：那不是 Docker（`COMMAND` 欄不是 `com.docke…`）。

- [x] ④ `127.0.0.1:5433` 是 Docker Postgres，不是 brew：

```bash
lsof -iTCP:5433 -sTCP:LISTEN
docker compose ps
```

  預期：第一條的 `COMMAND` 欄是 `com.docke…`／`docker` 之類的行程名（**不是** `postgres`）；
  第二條看到 `db` 是 `Up … (healthy)`、`PORTS` 是 `127.0.0.1:5433->5432/tcp`。

- [x] ⑤ `pytest -q` ＝ **402 passed ＋ 2 skipped**（與遷移前同顆數；
      要先 `cd /Users/linjunting/personalDocAI && source .venv/bin/activate`，
      而且 `docker compose ps` 的 `db` 要是 `Up (healthy)`——測試庫從 Phase 47 起
      就住在那個 container 裡，db 還沒好就跑會是一整片連線錯誤，不是測試壞了）。
      **這個數字沒有任何但書**：`LAN_HOST` 本增量不做（§3 最後一列），
      所以不會變成 403；那 2 skipped 也一定還在——摘標是 Phase 51 的事，
      提前摘會讓這一條（design4 §8.9「與遷移前同顆數，含既有 skipped」）對不上
- [x] ⑥ `curl -k https://127.0.0.1:8000/health` → `{"status":"ok"}`
- [x] ⑦ 上傳一張測試圖：201、`data/` 出現檔、瀏覽頁看得到
- [x] ⑧ 資料夾／待辦詳情彈窗在 Docker app 上仍可用（階段甲回歸）
- [x] ⑨ 鏡頭：用區網 IP 開桌面頁，QR 網址的 host **逐字等於** `ipconfig getifaddr en0`
      的輸出（§4.3；判準已於 2026-08-24 從「看 192.168／172 前綴」校準為逐字比對）
- [x] ⑩ 重開 Docker Desktop 後 `app`／`db` 自己回來（§4.2）

### 4.6 階段丙收尾（增量四還有最後一個 Phase 51）

> 📌 這裡收的是**階段丙（Docker）**這條線。增量四真正的最後一步是
> `phase-51-規格摘標與詢問三路驗收.md`（與 Docker 無關）。所以下面**不要**把
> 總覽的 51 那一列打勾、也不要寫「增量四完結」——那是 Phase 51 §4.6 的事。

- [x] 更新 `docs/plan/unfinish/phase-00-增量四總覽.md`：
      §2 的進度表把 **38〜50** 與 **★G1** 打勾（**51 那一列留空**；
      那張表裡只有 G1 一列，**G2 的勾在 §6**，不用在 §2 找）、
      §5 總驗收清單的「階段甲＋乙」與「階段丙」兩段打勾（**「規格摘標」那一段留空**）、
      §6 進度勾選區把 38〜50 與 **★G1／★G2** 兩列打勾（**Phase 51 那兩行留空**），
      並在表格下方加一段完成註記（照增量三總覽 §2 的「完成註記」寫法）：
      日期、階段丙收工時的 `pytest` 顆數（**402 ＋ 2**）、端點數、
      G1／G2 通過的證據、真機鏡頭驗收結果，並註明「Phase 51 未做，做完再補最終顆數」。
- [x] `git status` 看一次完整的變更清單，**逐檔自己 review 一遍**。
- [x] **不要 commit**（沿用產品負責人既有指示：改完先檢視）。
      `docs/plan/unfinish/` → `finish/` 的歸檔依慣例**隨 commit 執行**——
      commit 的時機由產品負責人決定。
- [x] 把「後悔藥還在」這件事寫進交付說明：
      brew `@17` 的資料目錄 `/opt/homebrew/var/postgresql@17` 仍在磁碟上，
      兩份 `~/PersonalDocAI-backup-docker遷移前.*` 與三份對帳快照
      （`~/PersonalDocAI-docker{遷移前,灌入後,切埠後}快照.txt`）仍在家目錄。
      **第一個穩定週期內不要清掉**（design4 §8.10）——
      快照那三份是 §4.5 ① 唯一的證據來源，刪了就再也對不出來。

---

## 5. ASCII 圖：收工後的最終狀態

```text
   ── 開機（你什麼都不用打）────────────────────────────────────────
        macOS 登入
           │
           ├─► Docker Desktop 自動啟動（Settings → Start when you sign in）
           │      └─► compose.yaml 的 restart: unless-stopped 把兩個服務拉回來
           │             ├── db  :5433（127.0.0.1，只綁本機）  volume: pgdata
           │             └── app :8000（0.0.0.0，手機連得到）  HTTPS
           │
           └─► Ollama 自動啟動（Launch on login）  :11434
                  ├── gemma4:e2b       （看圖／VLM——沒有 -mlx！見 §4.4 最後一點）
                  ├── gemma4:e2b-mlx   （路由／回答／實體建議）
                  └── bge-m3           （向量；永遠本機，不歸 AI 後端開關管）

   ── 平常怎麼用 ───────────────────────────────────────────────────
        看檔案櫃    https://127.0.0.1:8000/ui/browse.html
        無線鏡頭    https://<區網IP>:8000/ui/camera-desk.html   ← 一定用區網 IP
        改程式      docker compose -f compose.yaml -f compose.dev.yaml up -d
        跑測試      pytest -q          （在 host，連 127.0.0.1:5433 的測試庫）
        備份        pg_dump -h 127.0.0.1 -p 5433 -U postgres … （§8.8）

   ── 後悔藥（第一個穩定週期內不要清）──────────────────────────────
        /opt/homebrew/var/postgresql@17           ← brew 資料目錄（第 1 層，30 秒回復）
        ~/PersonalDocAI-backup-docker遷移前.sql   ← 純文字，查差異用
        ~/PersonalDocAI-backup-docker遷移前.dump  ← 自訂格式，灌回去用（第 2 層）
        ~/PersonalDocAI-docker遷移前快照.txt      ← 對帳用的那張照片（P45）
        ~/PersonalDocAI-docker灌入後快照.txt      ← G2 的對照（P46）
        ~/PersonalDocAI-docker切埠後快照.txt      ← §4.5 ① 的對照（P47）

   ── ⛔ 永遠不要 ──────────────────────────────────────────────────
        docker compose down -v          （-v ＝ 刪 pgdata ＝ 刪正式庫）
        docker volume rm …pgdata
        brew uninstall postgresql@17    （第一個穩定週期內）
        對正式庫跑 db/schema.sql        （開頭是 DROP TABLE）
        碰 postgresql@14（5432）        （別的專案）
```

---

## 6. 驗收清單

- [x] Docker Desktop 已設定登入時自動啟動
- [x] Ollama 已設定開機啟動
- [x] `restart: unless-stopped` 只在 `compose.yaml`；`compose.dev.yaml` 是 `restart: "no"`
- [x] `docker compose ps --no-trunc` 的 COMMAND 欄**看不到** `--reload`（＝跑的是常駐那份）
- [x] 重開 Docker Desktop（或重開機）後兩個服務自己回來、`/health` 200
- [x] 用區網 IP 開 `camera-desk.html`：QR 網址的 host **逐字等於** `ipconfig getifaddr en0` 的輸出
      （實作者自驗；判準見 §4.3 的 2026-08-24 校準框）
- [x] 憑證 SAN 含現在的 en0 IP（`openssl x509 … -text | grep -A2 "Subject Alternative Name"`）
- [x] 🙋 **【產品負責人 2026-08-25 已完成】** iPhone 掃 QR → 預覽 → 快門 → 桌面跳出三關彈窗鏈
      （真機；同時結掉 Phase 36 掛著的真機驗收）。
      2026-08-24 產品負責人指示：需要手機的部分停下來交給他手動測，實作者不自行勾選
- [x] `CLAUDE.md` 指令區已改：Docker 啟動／兩模式切換／`psql` 補 `-h 127.0.0.1 -U postgres`
      （含 `~/.zshrc` 三個變數的說明）／brew `@17` 已停的註記／日常備份／pytest 說明；
      現況段數字已更新（**402＋2**、端點 20——沒有但書：`LAN_HOST` 本增量不做；
      404＋0 是 Phase 51 摘標之後才改的數字，本檔不要提前寫）
- [x] design4 §8.9 的十條**逐條打勾**（§4.5）
- [x] **沒有**加 `LAN_HOST`：`grep -rn "LAN_HOST" app/ compose.yaml compose.dev.yaml`
      **沒有任何輸出**（本增量明確不做，§3 最後一列）
- [x] `phase-00-增量四總覽.md` 的勾選區已更新到 **Phase 50 為止**（51 那一列留空），並附完成註記
- [x] `git status` 已逐檔 review；**沒有 commit**
- [x] 後悔藥（brew 資料目錄＋兩份備份＋三份對帳快照）都還在

---

## 7. 常見陷阱

1. **開機時被 dev overlay 拉起來**：`compose.dev.yaml` 若寫了 `restart: unless-stopped`
   就會發生。檢查方式：重開 Docker Desktop 之後 `docker compose ps --no-trunc` 的 COMMAND 欄
   **不可以**出現 `--reload`。**一定要加 `--no-trunc`**：預設會把 COMMAND 截成
   開頭 20 個字左右，而 `--reload` 在最後面，不加就永遠「看不到」，這一關等於白驗
   （phase-48 §7 陷阱 10）。

2. **忘了 Ollama**：Docker Desktop 回來了、頁面也開得起來，但一上傳就 500。
   `docker compose logs app` 會看到連線失敗。Ollama 不在 Docker 裡，
   **Docker Desktop 的自動啟動救不了它**（design4 §8.11 風險第 6 列）。

3. **用 localhost 開鏡頭桌面頁**：`_phone_url()` 會退而在**容器裡**猜 IP，
   猜出 `172.x` 的 Docker 內部網段，手機一定連不到。**一律用區網 IP 開頁。**

4. **區網 IP 換了**：mkcert 憑證把 IP 寫死在 SAN 裡，換了要重簽
   （`CLAUDE.md` 指令區有指令），重簽後 `docker compose restart app`（HTTPS 行程握著舊檔）。

5. **`CLAUDE.md` 改一半**：只改了啟動指令、忘了 `psql` 的 `-U postgres`／`-h 127.0.0.1`，
   下一次要查資料庫時會撞 `role "linjunting" does not exist`（少帳號）或
   `connection to server on socket "/tmp/.s.PGSQL.5433" failed`（少主機）然後懷疑人生。
   §4.4 的六個小節逐項做完。

6. **順手清後悔藥**：「都跑一個禮拜了，brew 那個資料夾佔空間，刪掉吧」——**不要**。
   design4 §8.10 說第一個穩定週期內保留。要清也是產品負責人決定。

7. **在收尾時順手改產品行為**：§8.10 最後一列明文「本階段不改產品行為」。
   看到想改的東西就記下來，留給下一個增量。

8. **自己 commit**：沿用既有指示——改完先給產品負責人檢視。
   `unfinish/` → `finish/` 的歸檔也是隨 commit 才做，不要提前搬檔案。

9. **停在 `stop` 的狀態就去測開機**：`restart: unless-stopped` 的字面意思就是
   「**除非你自己停過**」——被 `docker compose stop` 停掉的容器，Docker Desktop
   重開後**不會**替你叫醒。§4.2 會怎麼等都等不到，然後你會去懷疑 `restart` 政策寫錯了。
   測之前先 `docker compose ps` 確認兩個都是 `Up`。

10. **拿「現在的列數」去對 §4.5 ① 的遷移前快照**：搬完之後 Phase 47／48 與第 ⑦ 條
    各上傳過測試照片，`photo` 一定變多。那是新增資料不是搬丟了——這一條要對的是
    Phase 45 與 Phase 47 那**兩份存檔**（見 §4.5 ① 的說明框）。

11. **看到 QR 的 IP 不對就衝去寫 `LAN_HOST`**：先換成用區網 IP 開頁再看一次（§4.3），
    而且先確認你是拿 `ipconfig getifaddr en0` 在對、不是憑「172 開頭就是 Docker」的印象。
    產品負責人 2026-08-23 已裁決本增量**明確不做** `LAN_HOST`——寫了它，
    §4.5 ⑤ 的顆數會從 402 變成 403，而那個分岔正是這次裁決要消掉的東西。

12. **順手把那兩條 `@未實作` 摘掉**：`pytest -q` 尾巴的 2 skipped 看起來很礙眼，
    但它們是 design4 §7（G1「既有 2 skipped 仍 skip」）與 §8.9（「與遷移前同顆數，
    含既有 skipped」）的**驗收基準**。摘標是 **Phase 51** 的事，
    而且要連規格裡那個矛盾的到期日一起改——在這裡順手摘，
    §4.5 ⑤ 立刻對不上，還會被誤判成搬家搬壞了。
