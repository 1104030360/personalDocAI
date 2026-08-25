# 階段 WWW：Phase 48 丙-3 —— app 容器化、連線切過去、遷移驗收 TODO

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-48-丙3應用容器化與連線切換.md`
> 前置：★G1 ＋ ★G2 已過；Phase 47 完成（db 在 5433、brew 已停、連線字串帶帳號）

---

## 1. 實作邏輯

把 FastAPI／uvicorn 也搬進 container，`compose.yaml` 一次拉起 `db` ＋ `app` 兩個服務。

### 三種連線各走不同的路（這是本 phase 的核心）

```text
  iPhone／瀏覽器 ──HTTPS :8000──► app（容器）
  app ──db:5432──────────────► db（容器）      Compose 內部 DNS，服務名就是主機名
  app ──host.docker.internal:11434──► Ollama（在 Mac 上，不進 Docker）
  host 的 pytest ──127.0.0.1:5433──► db        不進 container
```

**容器裡的 `localhost` 是容器自己**——找 Mac 上的服務要用 `host.docker.internal`，
找另一個容器要用**服務名**。這是本 phase 最容易搞錯的一件事。

### 為什麼 `.env` 不必再改一次

`compose.yaml` 的 `environment` 會**覆蓋** `.env` 裡的同名設定
（`python-dotenv` 的 `load_dotenv()` 預設**不覆寫**已存在的環境變數）。
所以同一份 `.env`：host 用 `localhost:5433`、容器用 `db:5432`，兩邊都對。

### 啟動指令**沒有 `--reload`**

常駐是開機自動拉起的，不該盯檔案；而且鏡頭配對 token 在記憶體，reload ＝ 配對失效。
熱重載是 Phase 49 的 overlay。

---

## 2. 步驟

- [ ] **前置：檢查憑證 SAN**（階段 SSS 校準加的）——`openssl x509 … | grep -A2 SAN`
      要含 `ipconfig getifaddr en0` 的 IP，不然 Phase 50 手機一定連不上
- [ ] 建 `.dockerignore`（`data/`／`certs/`／`.env`／`tests/`／`docs/` 都不送進去）
- [ ] 建 `Dockerfile`（`python:3.12-slim`；先 COPY `requirements.txt` 再裝套件＝改碼不必重裝；
      `CMD` 沒有 `--reload`）
- [ ] `compose.yaml` 加 `app` 服務（`build: .`、`8000:8000` 發佈到 0.0.0.0、
      兩個 `environment`、三個 bind-mount、`depends_on: service_healthy`、`restart: unless-stopped`）
- [ ] `docker compose config`——`app` 那段**不能有 `command:`**（＝用 Dockerfile 的 CMD）
- [ ] `docker compose -f compose.yaml up -d`
- [ ] `docker compose ps --no-trunc`（**`--no-trunc` 不能省**，否則 COMMAND 被截斷、
      `--reload` 在最後面根本看不到）
- [ ] 容器連得到 Ollama：`docker compose exec app python -c "…urlopen(…11434/api/tags).status"` → 200
- [ ] 容器連的是 Docker 的 db：`config.DATABASE_URL` → `postgresql://postgres@db:5432/PersonalDocAI`

### 驗收

- [ ] `curl -k https://127.0.0.1:8000/health` → `{"status":"ok"}`
- [ ] `pytest -q` ＝ 402 ＋ 2；`OLLAMA_BASE_URL=http://localhost:9 pytest -q` 同顆數
- [ ] 上傳一張真照片 → 201、`data/` 出現檔
- [ ] 階段甲回歸：詳情端點 `/photos/{id}` 四欄齊全、瀏覽頁資料端點都 200
- [ ] 問一句話 → 有回答，log 看得到 `kind=route`／`kind=embed`／`kind=answer`
- [ ] `docker compose logs app` 看得到 `kind=vlm`／`kind=embed`
- [ ] **映像裡沒有** `data`／`certs`／`.env`（要分兩步驗：容器裡有＝掛進去的；
      `docker run --rm personaldocai-app ls -a /app` 才是映像本身）
- [ ] `git status --short` 多出 `?? Dockerfile`、`?? .dockerignore`；`app/` 仍為空

---

## 3. 明確不做

在 compose 的 app 加 `--reload`（P49）／建 `compose.dev.yaml`（P49）／
把 Ollama 寫進 compose／`replicas: 2`／把 `data/`｜`certs/` COPY 進映像／
把 pytest 搬進 container／`network_mode: host`／再改一次 `.env`／改 `CLAUDE.md`（P50）
