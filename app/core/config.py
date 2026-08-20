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

# --- 模型名稱（換模型只改這裡，或改 .env）---
# 多模態模型：看圖用
VLM_MODEL = os.getenv("VLM_MODEL", "gemma4")
# 同一個多模態模型也拿來做「判斷查法」與「產生回答」
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4")
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

# 照片檔案的資料根目錄。資料庫存的是「data/photos/1.jpg」這種相對路徑，
# 實際落地位置由這個設定決定：
#   - 正式執行（uvicorn 在專案根目錄啟動）＝專案下的 data/
#   - pytest ＝ tests/conftest.py 的 isolated_data_dir 會把它改成暫存目錄
# 因為測試要能改它，程式裡一律寫 config.DATA_DIR（在函式裡即時讀），
# 絕對不要寫 from app.core.config import DATA_DIR（那樣會在 import 當下就定死值）。
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

# 允許上傳的圖片格式（其餘一律 415，不做任何後續處理）
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png"})

# 對外回應用的檢索方式名稱。內部用短代號，回應用規格寫的全名。
SEARCH_MODE_LABELS = {
    "metadata": "metadata search",
    "vector": "vector semantic search",
}
