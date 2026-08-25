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
