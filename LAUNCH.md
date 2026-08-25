# LAUNCH.md — 啟動與日常操作

PersonalDocAI 自 2026-08-24 起跑在 Docker 裡，**開機會自動啟動，平常不用下任何指令**。

---

## 目錄

1. [快速開始](#1-快速開始)
2. [網址一覽](#2-網址一覽)
3. [啟動與停止](#3-啟動與停止)
4. [開發模式（熱重載）](#4-開發模式熱重載)
5. [換網路時要做的事](#5-換網路時要做的事)
6. [跑測試](#6-跑測試)
7. [資料庫](#7-資料庫)
8. [備份](#8-備份)
9. [排錯](#9-排錯)
10. [絕對不要做的事](#10-絕對不要做的事)

---

## 1. 快速開始

**什麼都不用做，直接開這個網址：**

```
https://linjuntingdeMacBook-Pro-1071.local:8000/
```

這個網址**永遠不會變**（換 Wi-Fi、IP 變了都一樣）。設成書籤即可。

服務沒起來的話：

```bash
docker compose -f compose.yaml up -d
```

---

## 2. 網址一覽

以 `HOST` 代表 `linjuntingdeMacBook-Pro-1071.local`：

| 頁面 | 網址 |
|---|---|
| 首頁（自動轉上傳頁） | `https://HOST:8000/` |
| 上傳 | `https://HOST:8000/ui/upload.html` |
| 檔案櫃 | `https://HOST:8000/ui/browse.html` |
| 問問題 | `https://HOST:8000/ui/ask.html` |
| 無線鏡頭（桌面） | `https://HOST:8000/ui/camera-desk.html` |
| API 文件 | `https://HOST:8000/docs` |

規則：

- **一定要 `https`** —— `http://` 完全連不上
- **首頁用 `.local` 主機名開**，不要用 `localhost`。其他頁用 `localhost` 沒差，
  但從首頁點到鏡頭頁時，QR 會指向 Docker 內部網段（`172.x`），手機連不到
- 手機不用自己打網址，掃 QR 即可

**為什麼用 `.local` 而不是 IP**：`.local` 是這台 Mac 的 Bonjour 名字，
會自動跟著當下的 IP 走。換 Wi-Fi、DHCP 重新配發 IP 都不影響，
**網址不用改、憑證也不用重簽**。（憑證裡同時簽了 IP，所以 IP 那條路也還能用，當退路。）

---

## 3. 啟動與停止

```bash
cd /Users/linjunting/personalDocAI

# 啟動（常駐模式）
docker compose -f compose.yaml up -d

# 停止
docker compose stop

# 看狀態
docker compose ps

# 看 log
docker compose logs -f app          # Ctrl+C 只離開 log，容器繼續跑
```

⚠️ 用 `docker compose stop` 停掉之後，**重開機不會自己回來**，要手動 `up -d`。

---

## 4. 開發模式（熱重載）

改 `app/` 底下的程式碼存檔後自動生效。

```bash
# 常駐 → 開發
docker compose -f compose.yaml stop app
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app

# 開發 → 常駐
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d

# 現在是哪一種模式（看 COMMAND 有沒有 --reload）
docker compose ps --no-trunc
```

`--no-trunc` 不能省，不加的話 COMMAND 會被截斷、看不到結尾的 `--reload`。

**存檔沒反應的四種情況：**

| 改了什麼 | 怎麼辦 |
|---|---|
| `.env` | `docker compose -f compose.yaml -f compose.dev.yaml restart app` |
| `requirements.txt` | `docker compose build app` 再 `up -d` |
| `certs/` | 同 `.env`，`restart app` |
| 正在配對鏡頭 | reload 會清空 token，重產 QR 重掃 |

⚠️ 真機鏡頭驗收一律用**常駐模式**（開發模式每存一次檔配對就失效）。

---

## 5. 換網路時要做的事

**用 `.local` 網址的話：不用做任何事。** 名字會自動跟著新 IP 走。

只有這兩種情況要動手：

**① 換了電腦名稱**（系統設定 → 一般 → 關於 → 名稱）

```bash
cd /Users/linjunting/personalDocAI
scutil --get LocalHostName          # 查新名字，書籤換成它
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

**② 網路擋 mDNS，`.local` 不通**（公司／公共 Wi-Fi 比較常見）

退回用 IP，這時才要重簽憑證：

```bash
ipconfig getifaddr en0              # 查 IP，網址換成它
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

檢查憑證涵蓋哪些位址：

```bash
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
```

⚠️ **測鏡頭測到一半不要跑 `restart`** —— 配對 token 存在記憶體，一重啟就失效，QR 要重產。

---

## 6. 跑測試

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                        # 預期 405 passed
OLLAMA_BASE_URL=http://localhost:9 pytest -q     # 零外部依賴驗證，顆數要相同
```

前提：`docker compose ps` 的 `db` 要是 `Up (healthy)`（測試庫住在容器裡）。

⚠️ **不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。測試每一顆都會 TRUNCATE 同一個測試庫，兩份同時跑會互相清掉資料，症狀是大量看似隨機的 404 與 `NoneType` 錯誤。

---

## 7. 資料庫

`~/.zshrc` 已設好 `PGPORT=5433`、`PGUSER=postgres`、`PGHOST=127.0.0.1`，所以：

```bash
psql -d PersonalDocAI        # 正式庫
psql -d PersonalDocAI_test   # 測試庫

# 明寫參數版（腳本裡用這個）
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI
```

三個變數缺一不可：

- 少 `PGHOST` → `connection to server on socket "/tmp/.s.PGSQL.5433" failed`
- 少 `PGUSER` → `role "linjunting" does not exist`

⚠️ `postgresql@14`（5432 埠）是**別的專案**的（wanderlove、fse_chat_room），絕不可停用或修改。

---

## 8. 備份

```bash
# 資料庫
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump

# 照片原圖（★ 上面那行不含照片檔，data/ 不入版控，全世界只有一份）
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
```

還原：

```bash
pg_restore -h 127.0.0.1 -p 5433 -U postgres --no-owner --no-acl \
  --dbname=PersonalDocAI ~/PersonalDocAI-backup-YYYY-MM-DD.dump
```

---

## 9. 排錯

| 症狀 | 原因 | 解法 |
|---|---|---|
| 網頁完全開不起來 | 用了 `http://` | 改成 `https://` |
| 憑證警告 | 用區網 IP 開、憑證未涵蓋該 IP | 重簽憑證（§5） |
| **QR 是 `172.x` 開頭** | 桌面頁用 `localhost` 開的 | 關掉分頁，用 `.local` 網址重開 |
| `.local` 網址開不起來 | 這個網路擋 mDNS | 退回用 IP：`ipconfig getifaddr en0`，並重簽憑證（§5）|
| QR 顯示正常但手機掃不到 | 網址太長 → QR 格子太密 | `style.css` 的 `.cd-qr svg` `max-width` 要 ≥ `20rem`（有測試釘住）。網址越長格數越多，格子就越細 |
| 手機掃了打不開 | ① QR 的 IP 不對 ② iPhone 未信任根憑證 ③ 網路擋 | 依序查；`log` 若沒有 `role=phone` 就是手機根本沒連到 |
| 桌面一直顯示「對面不在線」 | 手機沒連上 | 同上 |
| 上傳／問問題回 500 | Ollama 沒開 | `curl -s http://localhost:11434/api/tags` 確認 |
| 上傳很慢（1〜2 分鐘） | 本機模型就是這麼慢 | 正常。看圖 60〜90 秒、路由 138 秒、回答 92 秒 |
| 同時上傳＋問問題 → 500 | 主機資源被壓垮 | **一次只做一件事** |
| pytest 大量隨機失敗 | 兩份 pytest 同時跑 | 等另一份跑完 |

看 log：

```bash
docker compose logs app --tail 50
docker compose logs app | grep "kind="        # AI 計時
docker compose logs app | grep "role=phone"   # 手機有沒有連上
```

---

## 10. 絕對不要做的事

| 指令 | 後果 |
|---|---|
| `docker compose down -v` | **刪掉正式庫**（`-v` 連 volume 一起刪） |
| `docker volume rm personaldocai_pgdata` | **刪掉正式庫** |
| `docker system prune --volumes` | **刪掉正式庫**（任何一次 `down` 之後都危險） |
| Docker Desktop → Reset to factory defaults | **刪掉正式庫** |
| 把 `compose.yaml` 的 `pg17` 改成 `pg18` | PGDATA 路徑不同 → 建新空叢集，看起來像資料全沒了 |
| 對正式庫跑 `db/schema.sql` | 開頭是 `DROP TABLE` |
| `brew uninstall postgresql@17` | 那是後悔藥第 1 層（資料目錄 `/opt/homebrew/var/postgresql@17` 保留中） |
| 停用／修改 `postgresql@14` | 別的專案在用 |

停服務一律用 `docker compose stop`。

---

## 附錄：目前架構

```
Mac
├── postgresql@14 (brew) :5432   別的專案，不碰
├── postgresql@17 (brew)  ---    已停；資料目錄保留當後悔藥
├── Ollama              :11434   留在 Mac（要 MLX／GPU）
├── data/ certs/ .env            bind-mount 進容器
├── .venv/ + pytest              在 host 跑，連 127.0.0.1:5433
└── Docker Desktop（開機自動啟動）
      ├── app  0.0.0.0:8000      HTTPS，常駐無 --reload
      └── db   127.0.0.1:5433    volume: personaldocai_pgdata

連線：
  瀏覽器／手機 ──HTTPS 8000──► app
  app ──db:5432──────────────► db
  app ──host.docker.internal:11434──► Ollama
  手機 ══WebRTC 直連══► Mac 瀏覽器（鏡頭預覽，不經伺服器）
```

相關文件：`CLAUDE.md`（專案全貌與開發規則）、`docs/design/`（設計決策）、`docs/plan/`（實作紀錄）。
