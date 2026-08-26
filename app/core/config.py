"""集中管理設定與常數。全專案唯一讀環境變數的地方。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 讀取專案根目錄的 .env，把裡面的設定放進環境變數
load_dotenv()

# --- 外部服務位址 ---
# 資料庫連線字串。測試時會由 tests/conftest.py 改成 PersonalDocAI_test
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://localhost:5433/PersonalDocAI"
)
# Ollama 本機服務網址（不是雲端，不需要 API key）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

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
