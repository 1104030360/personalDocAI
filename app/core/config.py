"""集中管理設定與常數。全專案唯一讀環境變數的地方。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 讀取專案根目錄的 .env，把裡面的設定放進環境變數
load_dotenv()

# --- 外部服務位址 ---
# 資料庫連線字串。測試時會由 tests/conftest.py 改成 PersonalDocAI_test
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5433/PersonalDocAI")
# Ollama 本機服務網址（不是雲端，不需要 API key）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# 佇列的中間人（broker）位址（增量五 design5.md D5／§7）。
# 預設值是**容器裡**的長相：redis 是 compose 的服務名、6379 是 Redis 預設埠、
# /0 是 Redis 的第 0 號 database（Redis 內建 16 個互不相干的編號空間）。
# 在 Mac 上跑 pytest 時根本用不到它——測試的 JobStore 是記憶體版、派工是假的
# （tests/conftest.py 的 wire_memory_job_store）。
# 真要在 host 手動連容器裡的 Redis 除錯，就在 .env 覆蓋成 redis://127.0.0.1:6379/0。
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

# --- Ollama Cloud（2026-08-22 產品負責人指示新增：看圖與詢問可切雲端）---
# API key 放 .env（OLLAMA_API_KEY=…）。沒填時開關切不到雲端（PUT 回 422）；
# 填好之後要重啟伺服器才生效——config 只在啟動時讀一次 .env。
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
# Ollama Cloud 的網址（官方套件的雲端用法就是指到這裡＋帶 Bearer key）
OLLAMA_CLOUD_HOST = os.getenv("OLLAMA_CLOUD_HOST", "https://ollama.com")

# --- 模型名稱（換模型只改這裡，或改 .env）---
# 多模態模型：看圖用
VLM_MODEL = os.getenv("VLM_MODEL", "gemma4")
# 雲端看圖用的模型名稱：預設跟本機同名，雲端上叫別的名字就在 .env 覆蓋
OLLAMA_CLOUD_VLM_MODEL = os.getenv("OLLAMA_CLOUD_VLM_MODEL", VLM_MODEL)
# 同一個多模態模型也拿來做「判斷查法」與「產生回答」
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4")
# 雲端的文字模型（詢問路由／回答、實體建議）：預設同本機，可在 .env 覆蓋
OLLAMA_CLOUD_LLM_MODEL = os.getenv("OLLAMA_CLOUD_LLM_MODEL", LLM_MODEL)

# AI 後端的**執行中狀態**："local"（本機 Ollama，預設）或 "cloud"（Ollama Cloud）。
# 上傳頁與問問題頁頁首的開關透過 PUT /settings/ai-backend 撥它（同一個系統狀態），
# 管的是**所有 gemma4 呼叫**：看圖、詢問路由、回答、實體建議。embeddings 不歸它管
# ——向量必須跟資料庫裡既有的 bge-m3 向量同源，永遠本機。
# 伺服器重啟一律回到 "local"。讀它的地方一律寫 config.AI_BACKEND 在函式裡即時讀
# （同 DATA_DIR 的理由，見下），絕不要 from … import AI_BACKEND 定死值。
AI_BACKEND = "local"
# embedding 模型：把文字轉成向量。bge-m3 是多語模型，同時支撐中文與英文
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

# --- 業務常數 ---
# 向量維度。bge-m3 預期輸出 1024 維，Phase 8 會實測確認；
# 若實測不同，只要改這個數字並重建資料表即可。
EMBEDDING_DIM = 1024

# 「最近」的定義：詢問當下回推 30 天（已釐清的決策，不可自行更動）
RECENT_DAYS = 30

# 語意查詢一次取回幾張照片
TOP_K = 5

# 同一張照片（或 PDF 的同一頁）最多送 VLM 幾次，**含第一次**（design5.md D10）。
# 3 ＝ 第一次 ＋ 兩次補考。看不懂與呼叫失敗（Ollama 沒開、雲端 401／逾時）都各算一次。
# ★ 這個重試是「入庫任務函式**內部**的 for 迴圈」，不是 Celery 的 autoretry——
#   後者會把整個任務從頭再跑，把已經 INSERT 的照片再插一次（design5.md §4.4）。
VLM_MAX_ATTEMPTS = 3

# 照片檔案的資料根目錄。資料庫存的是「data/photos/1.jpg」這種相對路徑，
# 實際落地位置由這個設定決定：
#   - 正式執行（uvicorn 在專案根目錄啟動）＝專案下的 data/
#   - pytest ＝ tests/conftest.py 的 isolated_data_dir 會把它改成暫存目錄
# 因為測試要能改它，程式裡一律寫 config.DATA_DIR（在函式裡即時讀），
# 絕對不要寫 from app.core.config import DATA_DIR（那樣會在 import 當下就定死值）。
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

# PDF 自 design3.md D7 起也收：不直接入庫，而是逐頁渲染成 PNG 走同一套單圖流程，
# 所以它只出現在「可不可以上傳」這一關，不會進到存檔那一層（見 storage_service.EXTENSIONS）
PDF_CONTENT_TYPE = "application/pdf"

# 允許上傳的檔案格式（其餘一律 415，不做任何後續處理）
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", PDF_CONTENT_TYPE})

# 對外回應用的檢索方式名稱。內部用短代號，回應用規格寫的全名。
# 前兩個是 自然語言詢問.feature 明文寫的全名，**一個字都不能動**；
# 後兩個是 Phase 34 新增的兩路（design3.md §6），規格檔沒提到，
# 只會出現在回應欄位——所以措辭沿用同一種「名詞片語 + search」的長相。
SEARCH_MODE_LABELS = {
    "metadata": "metadata search",
    "vector": "vector semantic search",
    "entity": "entity pin search",
    "task": "task search",
}

# --- 增量六：雲端路（design6.md D7〜D10、D15；總覽 §2.4.2）-------------------
# ★ 這一整段只有「名字」與「預設值」，**一個真實的值都不寫進版控**：
#   bucket 名、佇列 URL、實例 id 一律放 .env（.env 不入版控）。

# 雲端路的總開關。只認三種值（dependencies.get_cloud_route() 會擋掉別的）：
#   off    ＝ 完全不走雲端。**pytest 與新 clone 的預設**，行為與增量五逐字相同
#   assume ＝ 假設遠端開著（階段丁：工人跑在這台 Mac 上時用；Phase 86 接）
#   ec2    ＝ 每次送出前用 DescribeInstances 問一下那台機器開著沒（Phase 89 接）
CLOUD_ROUTE = os.getenv("CLOUD_ROUTE", "off")

# AWS 區域：東京（design6 §7）。boto3 的 client 一律**明傳** region_name=config.AWS_REGION，
# 不靠 ~/.aws/config——那個檔不入版控，換一台機器就會變成「在別的區域找不到 bucket」。
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")

# ★ AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY／AWS_ENDPOINT_URL 這三個**刻意不在這裡讀**：
#   它們是 boto3 自己認得的標準環境變數，建 client 時 boto3 會直接去環境裡撈。
#   config 再抄一份副本只會多一個會漂移的地方，而且金鑰一旦變成 Python 變數，
#   任何一次 print(vars(config)) 都會把它印出來。
#   EC2 上完全不放金鑰——那台機器用 instance role 拿臨時憑證（design6 §6）。

# 寄物櫃 bucket 名（Phase 84 建好之後填進 .env）
S3_BUCKET = os.getenv("S3_BUCKET", "")

# 兩條 SQS 佇列的網址（Phase 85 建好之後填進 .env）
SQS_JOBS_QUEUE_URL = os.getenv("SQS_JOBS_QUEUE_URL", "")
SQS_RESULTS_QUEUE_URL = os.getenv("SQS_RESULTS_QUEUE_URL", "")

# CLOUD_ROUTE=ec2 時要探測哪一台（Phase 92 開好實例之後填進 .env）
EC2_WORKER_INSTANCE_ID = os.getenv("EC2_WORKER_INSTANCE_ID", "")

# DescribeInstances 的答案快取幾秒（design6 §2.1 第 1 條「快取可短 TTL」）。
# 不快取的話每一張照片都要打一次 AWS API：慢，而且是可以省下來的錢。
EC2_PROBE_TTL_SECONDS = int(os.getenv("EC2_PROBE_TTL_SECONDS", "60"))

# 送出之後最多等 results 佇列幾秒；到了還沒有結果就 fallback 本機（design6 D10）。
# 300 秒 ＝ 5 分鐘：雲端看一張圖約 2 秒，這個值留的是「工人剛好在忙別的檔」的餘裕。
# 手動煙霧時在 .env 調小比較不必空等（Phase 86 用 30 秒）。
CLOUD_RESULT_TIMEOUT_SECONDS = int(os.getenv("CLOUD_RESULT_TIMEOUT_SECONDS", "300"))

# 雲端工人映像的版本：build 時由 Dockerfile 的 ARG GIT_SHA 烙進去（Phase 90）。
# 只有 app/workers/cloud_worker.py 讀它，啟動時印在 log 第一行——
# Demo 3 就是靠這個字串證明「EC2 上跑的真的是剛剛推上去的那一版」（design6 D16）。
WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")
