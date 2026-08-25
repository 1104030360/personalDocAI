# 階段 YYY 完成報告：Phase 50 丙-4 —— 開機常駐、鏡頭驗證、文件更新、階段丙收尾

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-50-丙4開機常駐與增量收尾.md`
> checkbox：48 個中 **45 個打勾**；**3 個刻意留白**（見 §5 誠實清單）
> 產出：`CLAUDE.md` 大幅改寫、總覽勾選與完成註記、Docker/Ollama 開機設定
> **`app/` 一行未動**

---

## 1. 實作邏輯

Docker 這條線的收尾。四件事：**開機自己回來 → 鏡頭 QR 驗證 → 文件對齊現實 → 十條總驗收**。

### 需要手機的部分怎麼處理

產品負責人 2026-08-24 明示「要用到我的手機的話，你要停下來跟我說，我自己手動測試」。
所以鏡頭驗收切成兩半，**可自動化的那一半全部做完並留下證據**，真機那一段列為待驗、不自行勾選。

---

## 2. 步驟與實測結果

### 2.1 開機常駐

| 項目 | 做法 | 結果 |
|---|---|---|
| Docker Desktop 自動啟動 | GUI 點不到，改直接改設定檔 `~/Library/Group Containers/group.com.docker/settings-store.json` 的 `AutoStart`：`False` → `True`。**先備份**成 `.bak-2026-08-24`，而且是在 `docker desktop stop` **之後**才改（Docker Desktop 活著時改，它退出會用記憶體裡的舊值覆寫回去） | ✅ 重開後讀出來仍是 `True` |
| Ollama 開機啟動 | 用計畫自己列的第二條路：`osascript … make login item … {path:"/Applications/Ollama.app"}` | ✅ 登入項目清單裡看得到 `Ollama`（移除方式已寫進計畫檔） |
| `restart` 政策位置 | `grep -n restart compose.yaml compose.dev.yaml` | ✅ `compose.yaml:32`（db）、`:58`（app）＝`unless-stopped`；`compose.dev.yaml:14` ＝ `"no"` |
| 現在是常駐模式 | `ps --no-trunc` | ✅ COMMAND 無 `--reload` |

### 2.2 實測「自己回來」

```text
測前：app Up 2 分鐘、db Up 2 分鐘 (healthy)      ← unless-stopped 不會叫醒你自己停掉的
docker desktop stop   → ✓ Stopping Docker Desktop
docker desktop start  → ✓ Starting Docker Desktop
daemon ready @ 3s

★ 接下來完全不下任何 up 指令，只是看：
  [5s]  app Up 4 秒、db Up 4 秒 (health: starting)
  [10s] app Up 10 秒、db Up 10 秒 (health: starting)
  [15s] app Up 15 秒、db Up 15 秒 (healthy)        ✅ 自己回來了
curl -k https://127.0.0.1:8000/health → {"status":"ok"}
ps --no-trunc → COMMAND 仍無 --reload（回來的是常駐版，不是 dev overlay）✅
```

### 2.3 ★ 鏡頭驗證——順帶證明了計畫原判準是錯的

**先修憑證**（Phase 48 已重簽為 `172.29.93.122`），然後兩組對照：

```text
en0 = 172.29.93.122

【正確做法】用區網 IP 開桌面頁
  GET  https://172.29.93.122:8000/ui/camera-desk.html   → 200
  POST https://172.29.93.122:8000/camera/session        → 201
    回應鍵：token / phone_url / qr_svg（SVG 長度 2746 ＝ 真的產了圖）
    phone_url = https://172.29.93.122:8000/ui/camera-phone.html?token=…
    QR host = 172.29.93.122   en0 = 172.29.93.122
    ★ 逐字相同 ✅

【對照組】用 127.0.0.1 開桌面頁（會走 _lan_host() 猜）
  POST https://127.0.0.1:8000/camera/session            → 201
    QR host = 172.24.0.3   ← Docker 內部網段，手機一定連不到 ⚠
```

> **這一組對照就是階段 SSS 那個校準的決定性證據。**
> 計畫原本寫「QR 必須是 `192.168.…`、**不可以是 `172.…`**」。但這裡：
> **正確答案是 `172.29.93.122`、錯誤答案是 `172.24.0.3`——兩個都是 `172.x`。**
> 用前綴判斷不但幫不上忙，還會把**正確**的 QR 判成錯的。
> 唯一可靠的判準是「QR 的 host 逐字等於 `ipconfig getifaddr en0` 的輸出」，
> 而這個判準在任何網段（192.168／172.20／10.x）下都成立。

**憑證也一併驗到底**（不只看檔案存在）：

```text
SAN：DNS:localhost, IP:172.29.93.122, IP:127.0.0.1          ✅ 涵蓋現在的 en0
curl -s --cacert "$(mkcert -CAROOT)/rootCA.pem" \
     https://172.29.93.122:8000/health  →  {"status":"ok"}
     ↑ **沒有用 -k**，走完整憑證鏈驗證還是通的 ＝ 手機那邊只要信任了 rootCA 就不會被擋
```

### 2.4 `CLAUDE.md` 改寫（六個小節逐項）

| 小節 | 改了什麼 |
|---|---|
| 啟動伺服器 | `uvicorn app.main:app --reload --port 8000` → Docker 常駐／開發兩種模式、切換四步、`ps --no-trunc` 的理由、`down -v` 警告、**「`--reload` 救不了的四種情況」**對照表 |
| HTTPS | 改成「憑證由 compose bind-mount 進容器，啟動指令寫在 `Dockerfile`／`compose.dev.yaml`」；重簽那段補上**先檢查 SAN** 的指令；mkcert 與 iPhone 信任步驟**保留不動**（那些仍是在 Mac 上做的） |
| 鏡頭桌面頁 | 補上「**判斷 QR 對不對的唯一可靠方法是與 `en0` 逐字比對**」，並寫出本次實測的兩個 `172.x` 數字，讓下一個人不會再用前綴判斷 |
| 資料庫 | 三條 `psql -d … -f db/*.sql` 全部補 `-h 127.0.0.1 -p 5433 -U postgres`；新增 `~/.zshrc` 三變數說明與**漏掉會噴什麼錯**；brew `@17` 已停＋資料目錄留著的註記；`@14` 仍是別的專案的 |
| 日常備份 | 新增一整段（方式 A 容器內 `pg_dump`＋`compose cp`；方式 B host `-Fc`），含「A 沒有 `-Fc` ＝純文字，要用 `psql -f` 灌回去」的提醒 |
| `pytest` | 加「測試仍在 **host** 跑、連的是 Docker 裡的測試庫、`db` 要 `Up (healthy)` 才跑得起來」 |
| 現況段 | 顆數 358→**402**；補整段增量四成果（階段甲／乙／G1／階段丙的檔案與設定、G2 證據、真模型延遲與「不要並行」的教訓、QR 判準）；更正三句過期敘述：① 34〜37「未 commit」→ 已進 `6392270` ② 環境「PostgreSQL@17 於 5433」→ Docker container ③ MLX 那句補上「**看圖那顆沒有 `-mlx`**」（`.env` 是 `VLM_MODEL=gemma4:e2b`、`LLM_MODEL=gemma4:e2b-mlx`） |
| 設計文件沿革段 | 增量三計畫改指 `finish/`、補上增量四 design4 與 Phase 38〜51 的現況 |

### 2.5 design4 §8.9 十條總驗收——**全過**

| # | 項目 | 實測 |
|---|---|---|
| ① | 六張表列數與遷移前快照相同 | `diff` P45 遷移前 vs P47 切埠後 → **零輸出** ✅ |
| ② | `vector` extension ＋ `vector_dims`＝1024 | `plpgsql`、`vector`；`1024` ✅ |
| ③ | brew `@17` stopped、`@14` started | `@17` ＝ `none`、`@14` ＝ `started`；5432 上是 `postgres`（**別的專案的，本來就該在那裡**，不是 Docker） ✅ |
| ④ | `127.0.0.1:5433` 是 Docker | `lsof` 顯示 `com.docke`（不是 `postgres`）；`db` `Up (healthy)` `127.0.0.1:5433->5432/tcp` ✅ |
| ⑤ | `pytest -q` ＝ 402 ＋ 2 | `402 passed, 2 skipped, 1 warning in 49.32s` ✅ |
| ⑥ | `/health` 200 | `{"status":"ok"}` ✅ |
| ⑦ | 上傳測試圖 | **201**，81.4s，id=40，`data/photos/40.jpg` 出現，收件箱 `photo_count` 8 ✅ |
| ⑧ | 詳情彈窗（階段甲回歸） | `browse.html`／`photo_detail_modal.js`／`/folders/2`／`/tasks` 皆 200；兩筆待辦指到的照片 21、22 的 `GET /photos/{id}` 都回六鍵＋四欄 metadata ✅ |
| ⑨ | 鏡頭 QR | QR host 與 `en0` 逐字相同（§2.3） ✅ |
| ⑩ | 重開 Docker Desktop 後自己回來 | 15 秒內，未下任何指令（§2.2） ✅ |
| ＋ | `LAN_HOST` 掃碼 | `grep -rn "LAN_HOST" app/ compose.yaml compose.dev.yaml` **零輸出** ✅ |

---

## 3. 測試方式

沒有新增自動化測試（本 phase 是設定與文件）。驗收設計成**每一條都留下可回頭核對的輸出**：

- 開機常駐：不是「看設定有沒有勾」，而是**真的停掉再開**，然後**刻意不下任何 `up` 指令**，
  用輪詢記錄容器什麼時候自己回來（5s／10s／15s 三筆）
- 鏡頭：不是「看起來像對的」，而是**程式化比對** QR host 與 `ipconfig getifaddr en0` 的字串，
  再加一組**反例**（用 `127.0.0.1` 開）證明判準真的區分得出來
- 憑證：不只看 SAN 有沒有那個 IP，還用 `--cacert` 走完整憑證鏈打一次 `/health`
- 十條總驗收：每條都貼實際輸出，不用「通過」兩個字帶過

---

## 4. 遇到的問題與解法

| # | 問題 | 解法 |
|---|---|---|
| 1 | **Docker Desktop 的「開機啟動」是 GUI 勾選，指令點不到** | 改設定檔 `settings-store.json` 的 `AutoStart`。關鍵是**順序**：必須在 `docker desktop stop` 之後才改，否則 Docker Desktop 退出時會用記憶體裡的舊值覆寫回去（我一開始就是照這個順序做的，所以沒踩到）。改前備份、改後重開再讀一次確認持久化。這一步順便就把 §4.2 的「重開 Docker Desktop」測完了，一石二鳥 |
| 2 | **Ollama 沒有可寫的設定檔**：`~/.ollama/config.json` 不存在，`defaults read com.electron.ollama` 也沒有相關鍵 | 用計畫**自己列的第二條路**（「也可以用 macOS 的『系統設定 → 一般 → 登入項目』加進去」）：`osascript` 加登入項目，再列出清單確認。移除指令也一併寫進計畫檔，讓這個動作可回溯 |
| 3 | **計畫的 QR 判準在這台機器上是錯的** | 這在階段 SSS 就校準過了，本階段拿到**決定性證據**：正確 QR 是 `172.29.93.122`、錯誤 QR 是 `172.24.0.3`，**兩個都是 172.x**。已把兩個實測數字寫進 `CLAUDE.md`、`phase-50`、總覽 §5，讓後人不必再推一次 |
| 4 | **§4.2 的「真的重開機一次」我沒有做** | 產品負責人外出中，重開他的電腦會關掉他所有開著的東西——**這不是我該替他做的決定**。做的是等價但較輕的那一半（停/開 Docker Desktop，容器自己回來）。計畫檔那一條**保留未勾**並註明理由，留給產品負責人順手驗 |

---

## 5. 誠實清單：**沒有做完**的 3 個 checkbox

| 項目 | 為什麼沒做 | 誰來做 |
|---|---|---|
| §4.2「真的重開機一次」 | 產品負責人外出中，不該替他重開電腦 | 產品負責人（順手即可；等價的輕量版已驗過） |
| §4.3 iPhone 實機掃 QR → 預覽 → 快門 → 三關彈窗鏈 | **需要手機**，產品負責人明示要自己測 | 產品負責人 |
| §6 驗收清單同一項（真機） | 同上 | 產品負責人 |

**除此之外的 45 個 checkbox 全部完成。**

---

## 6. 測試結果

**十條總驗收全過（＋`LAN_HOST` 掃碼那一條 ＝ 11 條）。**

```text
── 收工後的最終狀態 ─────────────────────────────────────────────
   macOS 登入
      ├─► Docker Desktop 自動啟動（AutoStart = True）
      │      └─► restart: unless-stopped 把兩個服務拉回來
      │             ├── db  127.0.0.1:5433  volume: personaldocai_pgdata
      │             └── app 0.0.0.0:8000    HTTPS，無 --reload
      └─► Ollama 自動啟動（登入項目）:11434
             ├── gemma4:e2b       （看圖／VLM——**沒有** -mlx）
             ├── gemma4:e2b-mlx   （路由／回答／實體建議）
             └── bge-m3           （向量；永遠本機）

   pytest      402 passed ＋ 2 skipped
   端點        20
   正式庫      photo 40 列（37 原始 ＋ P47／P48／P50 各一張煙霧）
   brew        @17 none（資料目錄 90M 保留）／@14 started（別的專案，沒碰）

── 後悔藥（第一個穩定週期內不要清）──────────────────────────────
   /opt/homebrew/var/postgresql@17               brew 資料目錄（第 1 層，30 秒回復）
   ~/PersonalDocAI-backup-docker遷移前.sql       純文字，查差異用
   ~/PersonalDocAI-backup-docker遷移前.dump      自訂格式，灌回去用（第 2 層）
   ~/PersonalDocAI-backup-2026-08-24-P48復原後.dump   P48 崩潰復原後補的
   ~/PersonalDocAI-docker遷移前快照.txt          對帳用（P45）
   ~/PersonalDocAI-docker灌入後快照.txt          G2 的對照（P46）
   ~/PersonalDocAI-docker切埠後快照.txt          §4.5 ① 的對照（P47）
   ★ 那三份快照是 §4.5 ① 唯一的證據來源，刪了就再也對不出來
```

**沒有 commit**（沿用產品負責人既有指示）；`unfinish/`→`finish/` 歸檔隨 commit 執行。

---

## 7. 給 Phase 51 的提醒

- 顆數基準仍是 **402 ＋ 2**；Phase 51 做完會變 **404 ＋ 0**。
- 跑 pytest 前確認 `docker compose ps` 的 `db` 是 `Up (healthy)`（測試庫住在容器裡）。
- `CLAUDE.md` 現況段的顆數這一輪剛寫成 402＋2，Phase 51 要改成 404＋0，
  而且指令區「只跑規格檔 binder」那句「兩條 `@未實作` Rule 會 skip」也要一起改，**兩處要一致**。
