# PersonalDocAI 的映像（design4.md §8.4 建立；增量六 Phase 90 改成多階段）。
#
# 三個 stage，關係是這樣：
#
#     base ────┬──> cloud-worker   （EC2 上跑的工人；CMD 是 python -m app.workers.cloud_worker）
#              │
#              └──> app            （FastAPI／uvicorn；★ 一定要放最後，理由見下）
#
# ★ `app` 為什麼一定要放在檔案的最後：
#   不帶 `--target` 的 `docker build .` 會建到**最後一個 stage** 為止。
#   compose.yaml 的 app 與 worker 兩個服務都寫 `build: .`（沒有 target:），
#   所以只要 app 在最後，compose 蓋出來的就仍然是同一份 app 映像
#   ——compose.yaml 一個字都不必改（增量六總覽 §10 追認項 j）。
#   把順序調換的後果是**安靜的**：compose 會蓋出一個 CMD 是工人的映像，
#   app 容器起來之後開始去 SQS 收訊息、沒有人聽 8000 埠，而且不會有任何錯誤訊息。
#
# 只負責「映像裡有哪些套件、程式碼放哪、預設怎麼啟動」——要不要盯檔案重啟（--reload）
# 是「啟動指令」的事，寫在 compose 那邊（design4.md §8.4.1）。


# ---------- stage 1：base（套件 ＋ 程式碼；兩個下游 stage 共用這一層）----------
FROM python:3.12-slim AS base

# 不要產生 .pyc、log 直接吐出來不緩衝（不然 docker logs 會延遲看到）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只複製 requirements.txt 再安裝：程式碼改了但套件沒改時，
# Docker 會直接重用上一次安裝好的那一層，build 快很多
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再複製程式碼（含 app/static/ 的網頁，以及 app/workers/ 的雲端工人）
# ★ .dockerignore 排除了 scripts/，所以工人程式一定要放 app/ 底下才會進映像
#   （增量六總覽 §10 追認項 k；放錯地方的話 build 會成功、run 時才 ModuleNotFoundError）
COPY app ./app

# ★ base 刻意不寫 CMD：它不會被直接跑，只是給下面兩個 stage 當底。


# ---------- stage 2：cloud-worker（EC2 上跑的工人）----------
FROM base AS cloud-worker

# GIT_SHA ＝ build 當下的 git commit 短碼，由 --build-arg 傳進來。
# ARG 只在 build 期間存在；用 ENV 把它「烙」成執行期的環境變數，
# 工人啟動時才讀得到（app/core/config.py 的 WORKER_VERSION，預設 "dev"）。
# 這是「EC2 上跑的到底是不是新映像」的唯一可靠驗證方式
# ——工人啟動 log 會印 version=<sha>（增量六總覽 §10 追認項 e、design6 D16）。
ARG GIT_SHA=dev
ENV WORKER_VERSION=$GIT_SHA

# 工人不聽任何埠（design6 D11：EC2 inbound 全關），所以沒有 EXPOSE。
# 它只主動往外連 S3／SQS／ollama.com（全部 TCP 443）。
CMD ["python", "-m", "app.workers.cloud_worker"]


# ---------- stage 3：app（FastAPI；★ 必須是檔案裡的最後一個 stage）----------
FROM base AS app

# 對外的埠。實際發佈到 Mac 的哪個埠由 compose 的 ports 決定
EXPOSE 8000

# 常駐用的啟動指令：**沒有 --reload**（design4.md D10）。
# --host 0.0.0.0 ＝也聽容器外面來的連線；HTTPS 憑證由 bind-mount 掛進來。
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "certs/key.pem", "--ssl-certfile", "certs/cert.pem"]
