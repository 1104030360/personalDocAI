# Phase 2：分層專案骨架與設定

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 建出 design.md §4.1 規定的**分層目錄**與檔案，完成 `app/core/config.py`（集中管理所有設定與常數）與兩份 `schemas`，並讓 FastAPI 真的能啟動。

---

## 前置條件

- 需要已完成的 phase：**Phase 1**（Python 虛擬環境、套件、PostgreSQL、Ollama 都已就緒）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

現在要把「檔案長在哪裡」定下來。design.md §4.1 明訂用**分層架構**：

- **api/routers**（路由層）：收 HTTP 請求、做輸入檢查、把錯誤翻成 HTTP 狀態碼。
- **services**（服務層）：真正的商業邏輯（看圖、轉向量、檢索、流程圖）。
- **repositories**（資料層）：唯一碰資料庫的地方。
- **schemas**：API 的請求／回應格式。
- **core**：設定與常數。
- **db**：資料庫連線。
- **dependencies.py**：依賴注入點（測試時整組換成假件的那個開關）。

這一步先把檔案都建出來（多數先留空殼），並把所有「會變動的設定」——資料庫網址、Ollama 網址、模型名稱、30 天、top-5——通通集中到 `app/core/config.py`。

**分層不等於加空殼。** design.md §4.1 特別點名：**不建** `models/`（沒有 ORM）、**不建** `core/security.py`（沒有認證）、**不建** `alembic/`（單表用 `schema.sql` 重建）、**不建** `users/`／`messages/`（本專案沒有這些資源）。上面列出的每個檔案在後續 phase 都會被填滿，一個都不是裝飾。（另外 §4.1 目錄裡還有一個 `app/static/`——網頁介面的兩個 HTML 檔——那是 **Phase 14** 才建的，本 phase 不要先建。）

為什麼要先做這件事：之後每個 phase 都只是「把某個空殼填滿」，不用再煩惱檔案要放哪裡；而所有魔術數字集中在一處，換模型、換天數都只改一行。

---

## ASCII 圖：分層骨架與依賴方向（箭頭＝誰用誰，單向不回頭）

```
                       app/main.py           ★ 本階段完成（只掛 /health）
                            │ include_router（P04 / P11 才會真的掛上）
              ┌─────────────┴──────────────┐
              ▼                            ▼
   api/routers/photos.py            api/routers/ask.py      （P04 填 / P11 填）
              │  讀寫格式                   │  讀寫格式
              ▼                            ▼
        schemas/photo.py             schemas/ask.py         ★ 本階段完成

  上傳這條路（photos.py 依序呼叫三個模組，結果交回 router 再往下傳）：
   photos.py ──看圖────> services/vlm_service.py            （P05 填）
   photos.py ──轉向量──> services/indexing_service.py       （P06 填）
   photos.py ──寫入────> repositories/photo_repository.py   （P03 填）

  詢問這條路（ask.py 只呼叫流程圖，流程圖再往下呼叫）：
   ask.py ──> services/ask_workflow.py                      （P10〜11 填）
                         │
                         ▼
              services/retrieval_service.py                 （P09 填）
                         │
                         ▼
        repositories/photo_repository.py   ★ 全系統唯一寫 SQL 的地方
                         │ 用
                         ▼
                 db/session.py（psycopg 連線）（P03 填）
                         │
                         ▼
                PostgreSQL（＋pgvector）

  所有模組 ──讀設定──> core/config.py   ★ 本階段的主角
                          ▲
                          └── 讀取 .env（DATABASE_URL、OLLAMA_BASE_URL、模型名稱）

  app/dependencies.py ── 提供 get_vlm / get_embeddings / get_now …（P05 起陸續填）
                         router 用 Depends(...) 取用，測試時整組換成假件
```

**唯一碰資料庫的是 `repositories/photo_repository.py`**。注意上傳這條路：看圖與轉向量的兩個 service 只跟 Ollama 說話、**不碰資料庫**，寫入是 `photos.py` 這個 router 自己交給 repository 做的；詢問那條路則由 `retrieval_service` 透過 repository 查資料。這就是 design.md §4.2 規定的依賴方向。

---

## 逐步驟操作

### 步驟 1：建立分層目錄與空檔案

```bash
cd /Users/linjunting/personalDocAI

mkdir -p app/api/routers app/schemas app/services app/repositories app/db app/core
mkdir -p db scripts tests

# 每個 Python 套件資料夾都要有 __init__.py
touch app/__init__.py \
      app/api/__init__.py app/api/routers/__init__.py \
      app/schemas/__init__.py app/services/__init__.py \
      app/repositories/__init__.py app/db/__init__.py app/core/__init__.py \
      tests/__init__.py

# 各層的檔案（本 phase 只填 config.py / schemas / main.py，其餘留空殼）
touch app/main.py app/dependencies.py
touch app/api/routers/photos.py app/api/routers/ask.py
touch app/schemas/photo.py app/schemas/ask.py
touch app/services/vlm_service.py app/services/indexing_service.py \
      app/services/retrieval_service.py app/services/ask_workflow.py
touch app/repositories/photo_repository.py
touch app/db/session.py
touch app/core/config.py
touch db/schema.sql
```

> `__init__.py` 是一個空檔案，它的作用是告訴 Python「這個資料夾是一個可以被 import 的套件」。分層架構的每一層都是一個套件，所以每個資料夾都要有一個。

> ⚠️ 注意有**兩個叫 db 的東西**，不要搞混：
> - `app/db/`＝Python 套件，放資料庫**連線程式碼**（`session.py`）。程式裡寫 `from app.db import session`。
> - `db/`（專案根目錄底下）＝放**SQL 檔**（`schema.sql`）。指令裡寫 `psql -d visual_memory -f db/schema.sql`。
> 這是 design.md §4.1 定的結構，照做即可；它們層級不同，不會互相干擾。

### 步驟 2：建立 `.env`（環境變數檔）

「環境變數」＝放在程式外面的設定值，換機器只改這個檔、不用改程式碼。

建立 `/Users/linjunting/personalDocAI/.env`：

```text
# 資料庫連線字串，格式：postgresql://主機:埠號/資料庫名稱
# （埠號＝同一台電腦上區分不同服務的編號。PostgreSQL 慣例是 5432，
#   但本機的 5432 被既有的 postgresql@14 佔用（其他專案在用），
#   本專案的 @17 跑在 5433——Phase 1 就是這樣設定的，所以這裡寫 5433。
#   這裡刻意沒寫使用者帳號：psycopg 會自動用你 macOS 的登入帳號連線，
#   Homebrew 裝的 PostgreSQL 預設就接受這個帳號，不需要密碼）
DATABASE_URL=postgresql://localhost:5433/visual_memory

# Ollama 本機服務網址（Phase 1 已確認它活著）
OLLAMA_BASE_URL=http://localhost:11434

# 模型名稱：換模型只改這裡
VLM_MODEL=gemma4
LLM_MODEL=gemma4
EMBEDDING_MODEL=bge-m3
```

順手建立 `/Users/linjunting/personalDocAI/.gitignore`（避免把虛擬環境與私密設定加入版本控制）：

```text
.venv/
.env
__pycache__/
*.pyc
.pytest_cache/
```

### 步驟 3：寫 `app/core/config.py`

這是全專案唯一放設定的地方。

```python
"""集中管理設定與常數。全專案唯一讀環境變數的地方。"""

import os

from dotenv import load_dotenv

# 讀取專案根目錄的 .env，把裡面的設定放進環境變數
load_dotenv()

# --- 外部服務位址 ---
# 資料庫連線字串。測試時會由 tests/conftest.py 改成 visual_memory_test
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://localhost:5433/visual_memory"
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

# 允許上傳的圖片格式（其餘一律 415，不做任何後續處理）
ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png"})

# 對外回應用的檢索方式名稱。內部用短代號，回應用規格寫的全名。
SEARCH_MODE_LABELS = {
    "metadata": "metadata search",
    "vector": "vector semantic search",
}
```

### 步驟 4：寫 `app/schemas/photo.py`（上傳的回應格式）

「Pydantic」是一個定義資料格式並自動驗證的套件；FastAPI 會用它自動檢查輸入、自動產生回應 JSON。

```python
"""上傳照片的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel, Field


class PhotoMetadata(BaseModel):
    """照片的結構化 metadata：固定四個欄位，不多不少。

    欄位值使用照片內容本身的語言（中文收據就是中文、英文收據就是英文），
    系統不做翻譯——跨語言的搜尋交給多語 embedding 處理（design.md §8.3）。
    """

    category: str | None = None       # 類別，例如「收據」或 "Receipt"
    location: str | None = None       # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)  # 物品清單
    content_time: str | None = None   # 內容時間，ISO 日期字串，例如「2026-08-10」


class UploadResponse(BaseModel):
    """POST /photos 成功時的回應（HTTP 201）。"""

    id: int
    text: str
    metadata: PhotoMetadata
```

### 步驟 5：寫 `app/schemas/ask.py`（詢問的請求／回應格式）

```python
"""自然語言詢問的 API 資料格式（Pydantic 模型）。"""

from pydantic import BaseModel


class AskRequest(BaseModel):
    """POST /ask 的請求內容。問題可以是中文或英文。"""

    question: str


class AskResponse(BaseModel):
    """POST /ask 成功時的回應（HTTP 200）。

    answer 的語言跟隨提問語言（中文問→中文答、英文問→英文答）。
    """

    answer: str
    search_mode: str            # "metadata search" 或 "vector semantic search"
    retrieved_photo_ids: list[int]
```

### 步驟 6：寫 `app/main.py`（先只有一個健康檢查端點）

「健康檢查端點」＝一個只會回答「我還活著」的簡單網址，用來確認服務有成功啟動。正式的兩個端點會在 Phase 4（`POST /photos`）與 Phase 11（`POST /ask`）才被 `include_router` 掛上來。

```python
"""FastAPI app 組裝。兩個 router 會在 Phase 4 與 Phase 11 掛上來。"""

from fastapi import FastAPI

app = FastAPI(title="Visual Memory RAG")


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}


# TODO(Phase 4)：app.include_router(photos.router)
# TODO(Phase 11)：app.include_router(ask.router)
```

### 步驟 7：啟動服務

```bash
cd /Users/linjunting/personalDocAI
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

（`uvicorn` 是 Phase 1 裝好的伺服器程式，負責把 FastAPI 真的跑起來；`--reload` ＝改程式碼會自動重啟，開發時很方便。要停止按 `Ctrl + C`。）

---

## 驗收標準

1. **分層目錄結構正確**
   ```bash
   cd /Users/linjunting/personalDocAI
   find app -name "*.py" | sort
   ```
   預期輸出剛好是這 21 行（`find` 會把每個 `__init__.py` 也列出來）：
   ```
   app/__init__.py
   app/api/__init__.py
   app/api/routers/__init__.py
   app/api/routers/ask.py
   app/api/routers/photos.py
   app/core/__init__.py
   app/core/config.py
   app/db/__init__.py
   app/db/session.py
   app/dependencies.py
   app/main.py
   app/repositories/__init__.py
   app/repositories/photo_repository.py
   app/schemas/__init__.py
   app/schemas/ask.py
   app/schemas/photo.py
   app/services/__init__.py
   app/services/ask_workflow.py
   app/services/indexing_service.py
   app/services/retrieval_service.py
   app/services/vlm_service.py
   ```
   重點是**沒有** `app/models/`、`app/core/security.py`、`alembic/` 這些 design.md 明訂不建的東西。

2. **不該存在的東西真的不存在**
   ```bash
   for p in app/models app/core/security.py alembic; do
     if [ -e "$p" ]; then echo "違規：$p 不應該存在，請刪除"; else echo "OK：$p 不存在"; fi
   done
   ```
   預期輸出剛好三行 OK（出現任何一行「違規」就要把該項刪掉再驗一次）：
   ```
   OK：app/models 不存在
   OK：app/core/security.py 不存在
   OK：alembic 不存在
   ```

3. **設定讀得到**
   ```bash
   python -c "from app.core import config; print(config.VLM_MODEL, config.EMBEDDING_MODEL, config.RECENT_DAYS, config.EMBEDDING_DIM, config.TOP_K)"
   ```
   預期輸出：`gemma4 bge-m3 30 1024 5`

4. **服務啟動並回應健康檢查**（開兩個終端機視窗：一個跑服務，一個下指令；**兩個視窗都要先 `cd` ＋啟用虛擬環境**）
   ```bash
   curl -s http://localhost:8000/health
   ```
   預期輸出：`{"status":"ok"}`

5. **自動產生的 API 文件打得開**
   瀏覽器開 <http://localhost:8000/docs>，應該看到 FastAPI 的互動式文件頁面，裡面目前只有一個 `GET /health`。

6. **兩份 schemas 都能正常建立**
   ```bash
   python -c "from app.schemas.photo import UploadResponse, PhotoMetadata; print(UploadResponse(id=1, text='t', metadata=PhotoMetadata()).model_dump())"
   python -c "from app.schemas.ask import AskRequest, AskResponse; print(AskResponse(answer='a', search_mode='metadata search', retrieved_photo_ids=[1]).model_dump())"
   ```
   預期輸出：
   ```
   {'id': 1, 'text': 't', 'metadata': {'category': None, 'location': None, 'items': [], 'content_time': None}}
   {'answer': 'a', 'search_mode': 'metadata search', 'retrieved_photo_ids': [1]}
   ```

---

## 常見問題

**Q1：`ModuleNotFoundError: No module named 'app'`。**
你不在專案根目錄執行。所有指令都要先 `cd /Users/linjunting/personalDocAI`，Python 才找得到 `app` 這個資料夾。

**Q2：`ModuleNotFoundError: No module named 'app.core'`（或 `app.schemas` 等）。**
少了 `__init__.py`。分層架構的**每一個**資料夾都要有一個空的 `__init__.py`，包含 `app/api/` 與 `app/api/routers/` 這種巢狀的。重跑步驟 1 的 `touch` 指令即可。

**Q3：`config.DATABASE_URL` 印出來還是預設值，`.env` 沒生效。**
`.env` 必須放在專案根目錄 `/Users/linjunting/personalDocAI/.env`，而且執行指令時的所在目錄也要是專案根目錄——`load_dotenv()` 會從所在位置一層層往上找 `.env`，人在專案根目錄它就一定找得到。另外確認 `python-dotenv` 有裝：`uv pip show python-dotenv`。都沒問題的話，檢查 `.env` 裡的變數名稱有沒有打錯字（要和 `config.py` 裡 `os.getenv("...")` 的字串一模一樣）。

**Q4：`uvicorn: command not found`。**
虛擬環境沒啟用。執行 `source .venv/bin/activate`，提示字元前面要看到 `(.venv)`。

**Q5：埠號 8000 被占用（`Address already in use`）。**
換一個埠號：`uvicorn app.main:app --reload --port 8001`，後續驗收指令裡的 `8000` 也一起換掉。

**Q6：既然要分層，要不要順便建 `app/models/`、`app/core/security.py`、`alembic/`？**
**不要。** design.md §4.1 明文寫「分層不等於加空殼」，這三個都在「明確不做」清單裡：沒有 ORM 就不需要 `models/`、沒有認證就不需要 `security.py`、一張表用 `schema.sql` 重建就不需要 migration 工具。建了就是違反設計。

---

## 完成後的專案狀態

專案已經有 design.md §4.1 規定的**分層骨架**（`app/static/` 除外——那是 Phase 14 的網頁介面）與集中式設定，兩份 schemas 可用，FastAPI 可以啟動並回應 `GET /health`；但還沒有資料庫資料表，兩個正式端點也還不存在（`api/routers/` 底下兩個檔案目前是空的）。
