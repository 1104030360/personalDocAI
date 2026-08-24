# Phase 48：階段丙-3 —— app 容器化、連線切過去、遷移驗收

> 🎯 **提醒：這是 side project，不要過度設計。**

```text
┌─ ⛔ 開工前檢查（兩道閘門，缺一不可）─────────────────────────────
│ ① 閘門 G1：產品負責人是否已「明示」G1 通過？沒有就停手（回 phase-44）。
│    G1 是**人**的動作，不是實作者可以自行勾掉的步驟。
│ ② 閘門 G2：phase-46 §5.2 的 diff 沒有輸出、phase-47 §4.3 的 diff 也沒有輸出？
│    沒過就不該走到這裡——你現在應該還在 5434 查資料，brew 還開著。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 把 FastAPI／uvicorn 也搬進 container，用 `compose.yaml` 一次把
> `db` ＋ `app` 兩個服務拉起來；app 連 `db`（走 Compose 內部網路）、連 Mac 上的 Ollama
> （走 `host.docker.internal`）；然後跑一輪完整驗收。
> **這一份的 app 啟動指令沒有 `--reload`**（開發用的熱重載是 Phase 49 的 overlay）。

---

## 1. 對應 design4.md 章節

- **§8.2**（為什麼 app 與 db 要分開；Ollama 留在 Mac；`data/`／`certs/` 用 bind-mount）
- **§8.4 的 `app` 段**（Dockerfile、啟動指令、`ports`、兩個環境變數、三個 mount、`depends_on`、
  `restart`、只能一個 replica）
- **§8.5**（新建 `Dockerfile`、`.dockerignore`；compose 加 `app`）
- **§8.6 階段丙-3**（第 2〜6 步；第 1 步的 `.env` 已在 Phase 47 做完，見那一份 §1 最後的說明框；
  第 7 步「日常開發改用兩份 yaml 疊加」屬 Phase 49）
- **§8.10**（不做：Ollama 進 Docker、app 擴兩個 replica、把 `data/` 打進映像、常駐加 `--reload`）
- **§8.11**（風險第 6 列：Ollama 沒開機啟動 → embedding／本機看圖會 500）

---

## 2. 前置條件

- **★ G1、★ G2 都已通過。**
- **Phase 47 已完成**：Docker 的 db 在 5433、brew `@17` 已停、`.env` 與 `conftest.py` 已帶帳號、
  `pytest -q` ＝ 387 passed ＋ 2 skipped。
- **Docker Desktop 正在跑、db 還活著**：

```bash
docker version
docker compose ps
```

  `docker version` 的 Client／Server **兩段都要有輸出**（只有 Client ＝ Docker Desktop 沒開）；
  `docker compose ps` 預期看到 `db` 是 `Up … (healthy)`、`PORTS` 是 `127.0.0.1:5433->5432/tcp`。
  （以下所有 `docker compose …` 指令都要在專案根目錄 `/Users/linjunting/personalDocAI` 執行，
  Compose 才找得到 `compose.yaml`。）

- **mkcert 憑證必須已經產生**（app 用 HTTPS 啟動，沒有憑證會起不來）：

```bash
ls -l certs/cert.pem certs/key.pem
```

  沒有的話照 `CLAUDE.md` 指令區的 mkcert 步驟先產一次（`certs/` 已入 `.gitignore`）。

- **Ollama 正在跑**（app 容器要連它）：

```bash
curl -s http://localhost:11434/api/tags | head -c 100
```

  預期：印出一段 JSON 的開頭（本機已安裝的模型清單）。完全沒有輸出＝Ollama 沒開。

- **host 上的 uvicorn 要停掉**（Phase 47 §4.5 叫你起的那一個；回到跑它的那個終端機按 `Ctrl+C`）。
  不停的話，8000 埠會被它佔住，container 起不來：

```bash
lsof -iTCP:8000 -sTCP:LISTEN
```

  預期：沒有輸出。

**先認識兩個名詞（第一次出現）：**

- **bind-mount（目錄掛載）**：把 Mac 上的某個資料夾「掛」進 container 裡。
  兩邊看到的是**同一份檔案**——container 寫進去，Mac 上馬上看得到。
  原圖與縮圖（`data/`）、憑證（`certs/`）都用這種方式，所以照片檔仍然住在 Mac 上，
  不會被關進 container 裡跟著一起消失（design4 §8.2）。
  它跟 named volume（Phase 46 講過的 `pgdata`）不同：named volume 的位置由 Docker 決定、
  你不會用 Finder 去翻；bind-mount 是你指定 Mac 上的哪個資料夾。
- **`host.docker.internal`**：Docker Desktop 提供的特殊網址，container 用它可以連回
  「跑 Docker 的那台 Mac 本身」。Ollama 跑在 Mac 上（不進 Docker），所以 app 容器要用這個名字找它。
  官方說明：<https://docs.docker.com/desktop/features/networking/networking-how-tos/>

---

## 3. 範圍

### 做

- 新建 `Dockerfile`。
- 新建 `.dockerignore`。
- `compose.yaml` 加上 `app` 服務。
- `docker compose -f compose.yaml up -d` 起兩個服務。
- 跑 design4 §8.6 丙-3 的驗收（`/health`、`pytest`、上傳煙霧、詳情窗回歸）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在 `compose.yaml` 的 app 加 `--reload` | design4 §1.2／§8.10 明文否決。開機拉起的行程不該盯檔案；鏡頭 session 在記憶體，reload ＝ 配對失效。開發用 overlay 是 Phase 49 |
| 建 `compose.dev.yaml` | 那是 Phase 49。這一份 phase 先把「常駐」那條路走通 |
| 把 Ollama 也寫進 compose | design4 §8.2／§8.10 明文：Mac 的 Docker 是 Linux VM，沒有 MLX、也吃不到這台 GPU；embedding 必須用本機 `bge-m3` 與庫裡既有向量同源 |
| `deploy.replicas: 2` 之類的水平擴充 | §8.10：鏡頭 session 在記憶體，兩個 replica 會配對失敗 |
| 把 `data/` 或 `certs/` `COPY` 進映像 | §8.10：檔在 host，container 只 bind-mount。打進映像會讓照片跟著映像走、而且映像變超大 |
| 把 pytest 搬進 container 跑 | §8.4「刻意不進 Compose」：pytest 仍在 host 跑，連 `127.0.0.1:5433` 的測試庫 |
| `network_mode: host` | §8.2：Docker Desktop on Mac 行為不同，而且 Compose 服務名 DNS 會失效 |
| 再改一次 `.env` | Phase 47 已經改好了（見 phase-47 §1 最後的說明框） |
| 改 `CLAUDE.md` | 那是 Phase 50 |

---

## 4. 實作步驟

### 4.1 建 `.dockerignore`

- [ ] 在專案根目錄建立 `.dockerignore`（決定「build 映像時**不要**送進去的東西」；
      送越少，build 越快、映像越小）：

```text
# build 映像時不要送進去的東西（design4.md §8.5）
.venv/
.git/
.gitignore
# **/ ＝連子資料夾裡的也算。沒有 **/ 的話只會比對最外層那一個，
# app/api/__pycache__ 這種就會被送進去（Docker 的比對規則：* 不跨資料夾）
**/__pycache__/
**/*.pyc
.pytest_cache/

# 照片與縮圖：住在 host，靠 bind-mount 進去（§8.10 明文不打進映像）
data/
# 憑證：同上，而且是機密
certs/
# 環境設定：同上，而且含 API key
.env

# 這些在 container 裡用不到
docs/
tests/
scripts/
.playwright-mcp/
.superpowers/
.claude/
.DS_Store
```

### 4.2 建 `Dockerfile`

- [ ] 在專案根目錄建立 `Dockerfile`：

```dockerfile
# PersonalDocAI 的 app 映像（design4.md §8.4）。
# 只負責「映像裡有哪些套件、程式碼放哪」——要不要盯檔案重啟（--reload）
# 是「啟動指令」的事，寫在 compose 那邊（design4.md §8.4.1）。

FROM python:3.12-slim

# 不要產生 .pyc、log 直接吐出來不緩衝（不然 docker logs 會延遲看到）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只複製 requirements.txt 再安裝：程式碼改了但套件沒改時，
# Docker 會直接重用上一次安裝好的那一層，build 快很多
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再複製程式碼（含 app/static/ 的網頁）
COPY app ./app

# 對外的埠。實際發佈到 Mac 的哪個埠由 compose 的 ports 決定
EXPOSE 8000

# 常駐用的啟動指令：**沒有 --reload**（design4.md D10）。
# --host 0.0.0.0 ＝也聽容器外面來的連線；HTTPS 憑證由 bind-mount 掛進來。
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "certs/key.pem", "--ssl-certfile", "certs/cert.pem"]
```

### 4.3 在 `compose.yaml` 加 `app` 服務

- [ ] 在 `services:` 底下、`db:` 之後加入（`volumes:` 那一段的 `pgdata:` 維持在檔案最後）：

```yaml
  app:
    build: .                       # 用同目錄的 Dockerfile 蓋映像
    ports:
      # 發佈到 0.0.0.0（不加 127.0.0.1 前綴）——手機要連得到才做得了無線鏡頭
      - "8000:8000"
    environment:
      # ★ 容器裡的連線字串：走 Compose 內部網路，服務名 db 就是主機名，
      #   而且用的是容器內的 5432（不是 Mac 上的 5433）。
      #   這一行會**覆蓋** .env 裡的同名設定（python-dotenv 預設不覆寫既有環境變數），
      #   所以 host 上的 .env 仍然可以寫 localhost:5433 給 pytest 與手動 psql 用。
      DATABASE_URL: postgresql://postgres@db:5432/PersonalDocAI
      # ★ Ollama 跑在 Mac 上、不進 Docker：容器用這個特殊名字連回宿主機
      OLLAMA_BASE_URL: http://host.docker.internal:11434
    volumes:
      # 原圖與縮圖住在 host（§8.10：不打進映像）
      - ./data:/app/data
      # mkcert 憑證（HTTPS，手機鏡頭需要安全來源）
      - ./certs:/app/certs
      # 其餘設定（模型名稱、OLLAMA_API_KEY…）；連線字串由上面 environment 覆蓋
      - ./.env:/app/.env
      # ★ 常駐**不掛原始碼**——程式在映像裡（bind-mount 原始碼是 Phase 49 的開發 overlay）
    depends_on:
      db:
        condition: service_healthy   # 等 db 的 healthcheck 綠了才啟動 app
    restart: unless-stopped
    # ★ 只能一個 replica（鏡頭配對 session 存在記憶體裡，兩個行程會配對失敗）
```

- [ ] 檢查 yaml（這個指令只解析、不啟動任何東西）：

```bash
docker compose config
```

  預期：把合併後的整份設定印出來，沒有錯誤訊息；`app` 那一段的 `command` 欄位**不存在**
  （＝用 Dockerfile 的 `CMD`，也就是沒有 `--reload` 的那一條）。

### 4.4 起來（design4 §8.6 丙-3 第 4 步）

- [ ] 起兩個服務（指令逐字照抄 design4 §8.6 丙-3 第 4 步）：

```bash
docker compose -f compose.yaml up -d
```

  第一次會花幾分鐘 build 映像（下載 Python 基底、裝套件）。
  **db 不會被重來一次**——它的設定這次沒改，Compose 只會建新的 `app`；
  就算哪天真的重建了 db，資料住在 `pgdata` volume 裡也不會丟。

- [ ] 看狀態（`--no-trunc` ＝不要截斷欄位）：

```bash
docker compose ps --no-trunc
```

  預期：`db` 是 `Up … (healthy)`；`app` 是 `Up …`，`PORTS` 顯示 `0.0.0.0:8000->8000/tcp`，
  **COMMAND 欄看不到 `--reload`**。
  （不加 `--no-trunc` 的話 COMMAND 只會顯示開頭 20 個字左右、長得像 `"uvicorn app.main:a…"`，
  那樣**看不出**後面有沒有 `--reload`——這一關就白驗了。）

- [ ] 看 app 的 log（確認 uvicorn 真的起來了）：

```bash
docker compose logs app | tail -20
```

  預期：`Uvicorn running on https://0.0.0.0:8000`。

- [ ] 確認 container **連得到 Mac 上的 Ollama**（先確認這一步，等一下上傳失敗時才不用瞎猜）：

```bash
docker compose exec app python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"
```

  預期：印出 `200`。
  （映像裡沒有 `curl`，所以改用 Python 內建的 `urllib` 問一句。
  出現 `URLError`／連線被拒 → 多半是 Ollama 沒開，回 §2 用 `curl` 在 Mac 上再確認一次。）

- [ ] 確認 app **真的連到 Docker 的 db**（這一 phase 叫「連線切換」，就是在切這條）：

```bash
docker compose exec app python -c "from app.core import config; print(config.DATABASE_URL)"
```

  預期：印出 `postgresql://postgres@db:5432/PersonalDocAI`（是 `db:5432`，**不是** `localhost:5433`）。
  若印出的是 `.env` 裡那條 `localhost:5433`，代表 compose 的 `environment` 沒生效——
  回 §4.3 檢查那兩行有沒有打錯字，改完 `docker compose up -d app` 重建。

### 4.5 驗收（design4 §8.6 丙-3 第 5、6 步）

- [ ] 健康檢查（`-k` ＝ 不驗憑證，因為是自簽的）：

```bash
curl -k https://127.0.0.1:8000/health
```

  預期：`{"status":"ok"}`

- [ ] host 上跑測試（連的是 Docker 裡的 `PersonalDocAI_test`）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**387 passed ＋ 2 skipped**。

- [ ] 零外部依賴實證（把 Ollama 網址指到一個死埠，顆數仍要一模一樣）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

  預期：仍是 **387 passed ＋ 2 skipped**。
  （這條打的是 host 上的 pytest，不影響已經跑起來的 container。）

- [ ] 瀏覽器開 `https://127.0.0.1:8000/ui/upload.html`
      （**是 https，不是 http**；自簽憑證會跳警告，選「繼續前往」）。
- [ ] **上傳煙霧**：上傳一張真照片 → 201、彈窗鏈跳出來、`data/` 出現新檔：

```bash
ls -lt data/photos | head -3
```

- [ ] **看 AI 計時 log 有沒有跟著進來**（階段乙的回歸，同時證明容器連得到 Ollama）：

```bash
docker compose logs -f app
```

  上傳一張圖會看到**兩組、每組兩行**：`kind=vlm` 的開始／結束，加上 `kind=embed` 的開始／結束
  （長相例：`AI 開始 kind=vlm backend=local model=…` ／ `AI 結束 kind=vlm … elapsed_s=… ok=true`）。
  `Ctrl+C` 只是離開 log，**容器繼續跑**。

- [ ] **階段甲的回歸**（design4 §8.9 第 8 條）：
      開 `https://127.0.0.1:8000/ui/browse.html?tab=folders` → 點一張照片 → 詳情窗開得起來、
      大圖與四欄都在；切到待辦分頁 → 點一列 → 同一顆窗、沒有新分頁。
- [ ] **問一句話**（證明 `route`／`answer` 也連得到 Ollama）：
      `https://127.0.0.1:8000/ui/ask.html` 問「我最近買過什麼飲料？」→ 有回答，
      log 看得到 `kind=route`／`kind=embed`／`kind=answer` 三組。
      （若真模型這次把它判成條件查詢，就**不會**有 `kind=embed` 那一組——那是 design4 §5.2
      寫好的行為、不是壞掉；換一句更明顯的語意描述題再看一次即可。`route` 與 `answer` 一定要有。）

---

## 5. ASCII 圖：現在的整台機器

```text
   Mac（host）
   │
   ├── postgresql@14 (brew) :5432   ← 別的專案 ★ 全程沒碰
   ├── postgresql@17 (brew)  :---   ← ○stopped；資料目錄留著＝後悔藥第 1 層
   ├── Ollama              :11434   ← 留在 Mac（有 MLX、吃得到 GPU）
   ├── data/  certs/  .env          ← 檔案住這裡，靠 bind-mount 進容器
   ├── .venv/ ＋ pytest             ← 測試仍在 host 跑，連 127.0.0.1:5433
   │
   └── Docker Desktop
         ├── container: app  (自建映像)
         │     uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-*   ← 無 --reload
         │     容器內 :8000 ──發佈──► Mac 的 0.0.0.0:8000（手機連得到）
         │     mount:  ./data → /app/data      （原圖與縮圖）
         │             ./certs → /app/certs    （mkcert 憑證）
         │             ./.env  → /app/.env     （模型名、API key）
         │     env:    DATABASE_URL=postgresql://postgres@db:5432/PersonalDocAI
         │             OLLAMA_BASE_URL=http://host.docker.internal:11434
         │
         │        ┌──── Compose 預設網路：服務名 db 就是主機名 ────┐
         │        │                                                │
         └── container: db (pgvector/pgvector:pg17) ◄──────────────┘
               容器內 :5432 ──發佈──► Mac 的 127.0.0.1:5433（只綁本機）
               volume: pgdata    ← 正式庫住這裡

   四條連線：
     iPhone／瀏覽器  ──HTTPS :8000──►  app
     app             ──db:5432──────►  db          （Compose 內部 DNS）
     app             ──host.docker.internal:11434──►  Ollama（在 Mac 上）
     host 的 pytest  ──127.0.0.1:5433──►  db        （不進 container）
```

---

## 6. 驗收清單

- [ ] `Dockerfile`、`.dockerignore` 存在；`compose.yaml` 有 `db` 與 `app` 兩個服務
- [ ] `docker compose ps --no-trunc`：兩個都 `Up`，`db` 是 `(healthy)`，
      **app 的 COMMAND 看不到 `--reload`**（一定要加 `--no-trunc`，否則 COMMAND 被截斷、驗不到）
- [ ] `curl -k https://127.0.0.1:8000/health` → `{"status":"ok"}`
- [ ] 容器內的 `config.DATABASE_URL` 是 `postgresql://postgres@db:5432/PersonalDocAI`（§4.4 最後一步）
- [ ] `pytest -q` ＝ **387 passed ＋ 2 skipped**（在 host 跑）
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] 上傳一張測試圖：201、`data/` 出現檔、瀏覽頁看得到（§8.9 第 7 條）
- [ ] 資料夾／待辦詳情彈窗在 Docker app 上仍可用（§8.9 第 8 條，階段甲回歸）
- [ ] `docker compose logs app` 看得到 `kind=vlm`／`kind=embed`／`kind=route`／`kind=answer`
      （階段乙回歸，同時證明容器連得到 Ollama）
- [ ] 映像裡**沒有**照片與憑證（要分兩步才驗得出來——**跑起來的 container 裡一定看得到**，
      因為那三項是掛進去的；真正要證明的是「**映像本身**沒有」）：

```bash
# ① 跑起來的 container 裡有什麼（-a 才看得到 .env 這種點開頭的檔）
docker compose exec app ls -a /app
```

  預期：`app`、`requirements.txt`（映像帶的）＋ `data`、`certs`、`.env`（bind-mount 掛進來的）。

```bash
# ② 映像本身有什麼：不掛任何東西，直接拿映像開一個用完即丟的容器
docker compose images app        # 先看映像叫什麼（REPOSITORY 欄，通常是 personaldocai-app）
docker run --rm personaldocai-app ls -a /app   # 映像名以上一行看到的為準
```

  預期：**只有** `app` 與 `requirements.txt`；**沒有** `data`／`certs`／`.env`
  （§8.10：那三項住在 host，不打進映像）。

- [ ] 版控狀態符合預期（**用 `git status --short`，不要用 `git diff --stat`**）：

```bash
git status --short
```

  預期：多出 `?? Dockerfile`、`?? .dockerignore` 兩個新檔；`compose.yaml` 與 `db/docker-init/`
  仍顯示 `??`（Phase 46 新建、依產品負責人指示**還沒 commit**）。
  除了這些與 `docs/` 底下的計畫檔之外，不該有其他產品程式碼被動到。
  ⚠ **這一條不能用 `git diff --stat` 對**：它只看得到「已追蹤」的檔案，
  而 `compose.yaml`／`Dockerfile`／`.dockerignore` **三個都還沒 `git add`**，
  `git diff --stat` 會是空的、證明不了任何事（phase-47 §6、phase-49 §6 有同一則提醒）。
  本 phase 對 `compose.yaml` 的修改請直接開檔看（或 `grep -n "app:" compose.yaml`）。

---

## 7. 常見陷阱

1. **8000 埠被佔住**：忘了停 host 上的 uvicorn，`docker compose up` 會噴
   `bind: address already in use`。先 `lsof -iTCP:8000 -sTCP:LISTEN` 確認。

2. **憑證不存在，app 一直重啟**：`restart: unless-stopped` 會讓它一直試。
   `docker compose logs app` 會看到 `No such file or directory: 'certs/key.pem'`。
   先產憑證（`CLAUDE.md` 指令區有 mkcert 步驟），再 `docker compose up -d app`。

3. **用 `http://` 開頁**：app 是用 HTTPS 起的，`http://127.0.0.1:8000` 會連不上或是亂碼。
   一律用 `https://`。自簽憑證的警告點「繼續前往」。

4. **以為 `.env` 裡的 `DATABASE_URL` 會生效**：容器裡不會——compose 的 `environment`
   會覆蓋它（`python-dotenv` 的 `load_dotenv()` 預設**不覆寫**已存在的環境變數）。
   這是刻意的：host 用 `localhost:5433`、容器用 `db:5432`，同一個 `.env` 兩邊都對。

5. **在容器裡用 `localhost` 找 Ollama 或資料庫**：容器裡的 `localhost` 是**容器自己**。
   找 Mac 上的服務要用 `host.docker.internal`，找另一個容器要用**服務名**（`db`）。

6. **把 `data/` COPY 進 Dockerfile**：映像會變成好幾 GB，而且每次上傳新照片映像就過期了。
   `.dockerignore` 已經擋掉，不要繞過。

7. **改了 `requirements.txt` 卻只 `up -d`**：套件是在 build 時裝進映像的，
   改了要重建：`docker compose build app` 再 `docker compose up -d app`。

8. **想用 `docker compose down` 收工**：用 `docker compose stop`。
   `down` 會移除 container（資料還在 volume，不會丟），但手滑打成 `down -v` 就是刪正式庫。

9. **想順手加 `--reload`**：不要。那是 Phase 49 的 overlay 做的事，
   而且 design4 §1.2 明文否決「常駐 `compose.yaml` 直接加 `--reload`」。

10. **`docker compose ps` 的 COMMAND 欄被截斷**：預設只顯示開頭 20 個字左右
    （`"uvicorn app.main:a…"`），你會以為「看不到 `--reload` ＝ 通過」，其實是根本沒顯示到那裡。
    驗這一項一律加 `--no-trunc`。

11. **bind-mount 的來源路徑打錯或不存在**：Docker **不會報錯**，它會在 Mac 上默默建一個
    **同名的空資料夾**（例如把 `./.env` 打成 `./env`，你的專案就會多一個叫 `env` 的資料夾），
    然後容器裡讀到的是空的。看到專案根目錄冒出沒印象的資料夾就是這一條，
    刪掉它、把 `compose.yaml` 的路徑改對再 `docker compose up -d app`。

12. **這一輪先不要驗無線鏡頭的 QR**：container 裡猜區網 IP 常猜成 Docker 網橋的 `172.x`
    （design4 §8.7 說那是唯一高風險）。鏡頭是 **Phase 50** 的驗收項目，
    到時候要用 `https://<Mac 的區網 IP>:8000/ui/camera-desk.html` 開頁、不要用 localhost。
