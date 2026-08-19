# Phase 1：環境準備

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 在這台 macOS 上準備好三樣東西——Python 虛擬環境與套件、裝了 pgvector 的 PostgreSQL、跑得動 `gemma4` 與 `bge-m3` 的 Ollama——之後所有 phase 都不用再碰安裝問題。

---

## 前置條件

- 需要已完成的 phase：**無**（這是第一個 phase）。
- 環境需求：
  - macOS，且已安裝 **Homebrew**（macOS 上的套件安裝工具，用一行指令幫你裝軟體）。沒有的話先執行：
    ```bash
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```
    剛裝完的 Homebrew 還不在 PATH 裡（終端機會找不到 `brew` 指令）——照安裝器結尾「Next steps」印出的兩行指令執行即可（Apple 晶片 Mac 通常是 `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile` 加上 `eval "$(/opt/homebrew/bin/brew shellenv)"`；Intel Mac 的 brew 在 `/usr/local/bin/brew`）。之後執行 `brew --version` 有印出版本號就代表可以用了。
  - 硬碟空間至少 15 GB（AI 模型檔案很大，`gemma4` 這類多模態模型通常好幾 GB）。
  - 專案資料夾：`/Users/linjunting/personalDocAI`（目前只有 `docs/`）。

---

## 這個 phase 在做什麼

系統要跑起來需要三個「地基」：跑程式的 Python 環境、存資料的資料庫、跑 AI 模型的 Ollama。這一步只做安裝與確認，**不寫任何產品程式碼**。先把地基弄好，後面每個 phase 才不會卡在「裝不起來」而分心。

兩個特別注意：

- 本專案**完全不使用雲端 AI 服務**，不需要任何 API key。所有 AI 都在你自己的電腦上跑（這就是 Ollama 的用途）。
- 本專案要支援**中文與英文**。選 `bge-m3` 當 embedding 模型就是為了這件事——它是**多語模型**（一個模型同時懂很多語言），所以英文問題有機會找到中文寫的照片內容。本 phase 的驗收會分別用中文與英文各測一次向量。

---

## ASCII 圖：這個 phase 準備的三塊地基

```
        你的 macOS 電腦
 ┌───────────────────────────────────────────────────────────┐
 │                                                           │
 │  ①  Python 3.12 虛擬環境 (.venv)                          │
 │      └─ FastAPI / psycopg / LangChain / LangGraph / pytest│
 │                                                           │
 │  ②  PostgreSQL 資料庫（本機服務）                         │
 │      └─ pgvector 擴充套件（讓資料庫能存向量、算相似度）   │
 │      └─ 資料庫 visual_memory（正式）                      │
 │      └─ 資料庫 visual_memory_test（測試專用）             │
 │                                                           │
 │  ③  Ollama（本機服務，網址 http://localhost:11434）       │
 │      ├─ 模型 gemma4  ：看圖＋判斷查法＋產生回答           │
 │      └─ 模型 bge-m3  ：把文字轉成向量（多語：中英都行）   │
 │                                                           │
 └───────────────────────────────────────────────────────────┘
        本 phase 完成 = ①②③ 三塊都「回應正常」
```

---

## 逐步驟操作

### 步驟 1：安裝 uv 並建立虛擬環境

- 「uv」＝新一代的 Python 套件管理工具（一個指令取代 pip 與 venv），速度快很多，需要的 Python 版本也會自動幫你下載。
- 「虛擬環境」＝專門給這個專案用的 Python 套件資料夾，裝在裡面的套件不會污染整台電腦。

```bash
brew install uv

cd /Users/linjunting/personalDocAI
uv venv --python 3.12
source .venv/bin/activate
python -V
```

> 💡 `uv venv --python 3.12` 在電腦上找不到 Python 3.12 時會**自動下載**，所以不需要另外 `brew install python`。建立成功會印出 `Creating virtual environment at: .venv`；`python -V` 應印出 `Python 3.12.x`。

> 💡 本文出現的 `/opt/homebrew/...` 路徑（步驟 3 的 `PATH` 設定會用到）是 **Apple 晶片（M1〜M4）Mac** 的 Homebrew 位置。如果你的 Mac 是 **Intel 晶片**，Homebrew 裝在 `/usr/local`，把 `/opt/homebrew` 一律改成 `/usr/local` 即可。不確定的話執行 `brew --prefix`，印出來的就是你該用的前綴。

> 之後**每次開新終端機視窗要做這個專案**，都要先執行：
> ```bash
> cd /Users/linjunting/personalDocAI && source .venv/bin/activate
> ```
> 看到提示字元前面出現 `(.venv)` 就代表啟用成功。**本路線圖每個 phase 的第一個指令都會提醒你這件事，不是複製貼上的贅字。**

### 步驟 2：寫 `requirements.txt` 並安裝套件

「requirements.txt」＝這個專案需要哪些套件的清單檔。

建立 `/Users/linjunting/personalDocAI/requirements.txt`：

```text
# --- Web 框架 ---
fastapi>=0.115            # 提供 HTTP API 的框架
uvicorn[standard]>=0.30   # 實際把 FastAPI 跑起來的伺服器
python-multipart>=0.0.9   # 讓 FastAPI 能接收上傳的檔案
pydantic>=2.7             # 定義資料格式並自動驗證

# --- 資料庫 ---
psycopg[binary]>=3.2      # Python 連 PostgreSQL 的套件（第 3 代）

# --- AI 積木 ---
langchain-core>=1.0       # LangChain 的核心：Document、Embeddings 介面、@chain
langchain-ollama>=1.0     # 用 LangChain 的介面呼叫本機 Ollama
langgraph>=1.0            # 把「判斷 → 查詢 → 回答」串成流程圖

# --- 設定 ---
python-dotenv>=1.0        # 讀 .env 檔裡的環境變數

# --- 測試 ---
pytest>=8.0               # 測試框架
pytest-bdd>=8.1           # 讓 pytest 能直接執行 .feature 規格檔（Rule/Example 需要這個版本以上）
httpx>=0.27               # 測試時用來呼叫自己的 API
```

安裝：

```bash
cd /Users/linjunting/personalDocAI
source .venv/bin/activate
uv pip install -r requirements.txt
```

> 💡 `uv pip ...`＝用 uv 執行「跟 pip 一樣的指令」，用法相同但快很多。之後所有裝套件、查套件的指令都用 `uv pip` 開頭。

### 步驟 3：安裝 PostgreSQL 與 pgvector

- **PostgreSQL**＝關聯式資料庫，本專案唯一的資料儲存處。
- **pgvector**＝PostgreSQL 的擴充套件，讓資料庫多出 `vector` 這種欄位型別，可以直接算「兩段文字有多像」。

> ⚠️ **這台機器的實況（2026-08-18 偵察）**：本機已有 `postgresql@14` 在預設的 5432 埠運行，裡面有**其他專案的資料庫**（wanderlove、fse_chat_room）——**不能動它、不能停它**。因此本專案的 @17 改裝在 **5433 埠**與 @14 並存。設定完成後的副作用：互動終端機裡 `psql` 不帶參數時預設連 5433（本專案的 @17）；要連舊的 @14 請自行加 `psql -p 5432`。其他專案的伺服器程式用自己的連線設定、不讀 `~/.zshrc`，不受影響。

```bash
brew install postgresql@17

# 把 @17 改到 5433 埠（避開 @14 佔用的 5432）——設定檔尾端追加的設定會蓋過前面的預設值
echo "port = 5433" >> /opt/homebrew/var/postgresql@17/postgresql.conf
brew services start postgresql@17

# 讓 psql 等指令可以直接使用、且預設連 5433（zsh）
echo 'export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"' >> ~/.zshrc
echo 'export PGPORT=5433' >> ~/.zshrc
source ~/.zshrc

brew install pgvector
```

> 💡 `PGPORT`＝psql／createdb 這些指令的「預設埠號」環境變數。設了它，本路線圖後續所有不帶 `-p` 的資料庫指令就會自動連到 5433，**文件裡的指令都不用改**。Python 程式則不依賴它——連線字串一律明確寫 `:5433`（見 Phase 2 的 `.env`）。

建立兩個資料庫（一個正式用、一個測試用），並在兩個裡面都啟用 pgvector：

```bash
createdb visual_memory
createdb visual_memory_test

psql -d visual_memory      -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d visual_memory_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> 💡 `psql` 的 `-d` 參數是「連到哪個資料庫」。**本專案所有 `psql` 指令都一定要寫 `-d 資料庫名稱`**——不寫的話 psql 會去連一個和你 macOS 帳號同名的資料庫，通常根本不存在，就會看到 `database "linjunting" does not exist`。

### 步驟 4：安裝 Ollama 並下載兩個模型

**Ollama**＝在自己電腦上跑開源 AI 模型的工具。它啟動後會在 `http://localhost:11434` 開一個本機服務，程式就用這個網址呼叫 AI。

兩個會用到的名詞：**curl**＝在終端機裡發出 HTTP 請求的指令（等於用文字模式「打開一個網址」）；**JSON**＝一種用大括號與引號組成的文字資料格式，程式之間交換資料的通用寫法。

> 💡 **這台機器的實況**：已裝好**官方 App 版** Ollama（`/Applications/Ollama.app`），服務已經在跑——下面兩行安裝指令**跳過**，直接從「確認服務活著」開始即可。沒裝過 Ollama 的機器才需要那兩行（brew 版與 App 版擇一，不要都裝）。

```bash
# （已裝官方 App 版的機器跳過這兩行）
brew install ollama
brew services start ollama

# 確認服務活著（回傳一段 JSON 就是活的）
curl http://localhost:11434/api/tags
```

下載本專案要用的兩個模型（第一次會下載好幾 GB，需要一點時間）：

```bash
# 多模態模型：會看圖，也會讀文字寫文字。負責「看圖 / 判斷查法 / 產生回答」三件事
ollama pull gemma4

# embedding 模型：把文字轉成向量。多語模型，中文與英文都支援
ollama pull bge-m3
```

### 步驟 5：三塊地基各做一次「活著沒」的確認

```bash
cd /Users/linjunting/personalDocAI
source .venv/bin/activate

# ① Python 與套件
python -c "import fastapi, psycopg, langchain_core, langchain_ollama, langgraph, pytest_bdd; print('python ok')"

# ② PostgreSQL 與 pgvector
psql -d visual_memory -c "SELECT extname FROM pg_extension WHERE extname='vector';"

# ③ Ollama 與兩個模型
ollama list
```

---

## 驗收標準

逐條執行，看到對應輸出才算過。

1. **Python 版本**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate && python -V
   ```
   預期：`Python 3.12.x`（小數點後版本不同沒關係）。

2. **套件都裝好了**
   ```bash
   python -c "import fastapi, psycopg, langchain_core, langchain_ollama, langgraph, pytest_bdd; print('python ok')"
   ```
   預期輸出：`python ok`（沒有任何 `ModuleNotFoundError`）。

3. **pgvector 已啟用**
   ```bash
   psql -d visual_memory -c "SELECT extname FROM pg_extension WHERE extname='vector';"
   ```
   預期輸出包含一行 `vector`，最後一行是 `(1 row)`。

4. **測試用資料庫也啟用了 pgvector**
   ```bash
   psql -d visual_memory_test -c "SELECT extname FROM pg_extension WHERE extname='vector';"
   ```
   預期同上。

5. **Ollama 服務活著**
   ```bash
   curl -s http://localhost:11434/api/tags | head -c 200
   ```
   預期：印出一段以 `{"models":[` 開頭的 JSON（不是 `Connection refused`）。

6. **兩個模型都下載完成**
   ```bash
   ollama list
   ```
   預期：清單中同時看到 `gemma4` 與 `bge-m3` 兩列。名稱後面帶標籤也算通過（例如顯示成 `gemma4:latest`、`bge-m3:latest`）。

7. **中文能跑一次向量**
   ```bash
   curl -s http://localhost:11434/api/embed \
     -d '{"model":"bge-m3","input":"在 Target 購買可樂的收據"}' | head -c 120
   ```
   預期：印出以 `{"model":"bge-m3","embeddings":[[` 開頭的 JSON，後面接一長串小數。若印出 `{"error":` 開頭的內容，回到驗收第 6 條確認 `bge-m3` 真的下載完成。

8. **英文也能跑一次向量**（雙語支援的第一個確認）
   ```bash
   curl -s http://localhost:11434/api/embed \
     -d '{"model":"bge-m3","input":"Receipt from Target with Cola"}' | head -c 120
   ```
   預期：同樣印出 `{"model":"bge-m3","embeddings":[[` 開頭的 JSON。中英文都拿得到向量，代表這個多語模型可以同時服務兩種語言的內容。

9. **真的能跑一次看圖**（最有信心的一關）

   下面那串引號裡的長亂碼是一張 **1×1 的白色 PNG 圖片**，用 **base64**（把圖片檔轉成純文字的編碼方式）表示，直接塞在請求裡送給模型看——不需要準備任何圖片檔。`"stream": false` 是要求模型「整段回答一次給我」，不要一小段一小段地傳。
   ```bash
   curl -s http://localhost:11434/api/chat -d '{
     "model": "gemma4",
     "stream": false,
     "messages": [{
       "role": "user",
       "content": "這張圖片是什麼顏色？",
       "images": ["iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"]
     }]
   }'
   ```
   預期：印出一段 JSON，其中 `"message"` 裡的 `"content"` 有模型寫的文字（回答內容與語言都不固定，說「白色」或 "white" 或「看不出來」都算通過——這一關只驗證模型**收得到圖、答得出話**）。若印出 `{"error":` 開頭的內容，代表 `gemma4` 沒下載成功或不支援看圖，回到步驟 4 與常見問題 Q4。

---

## 常見問題

**Q1：`curl http://localhost:11434/api/tags` 回 `Connection refused`。**
Ollama 服務沒啟動。執行 `brew services start ollama`，等 5 秒再試一次。如果還是不行，開一個終端機視窗執行 `ollama serve` 讓它在前景跑，觀察錯誤訊息。

**Q2：`CREATE EXTENSION vector` 報錯 `could not open extension control file ... vector.control`。**
pgvector 沒有裝到「你正在用的那一版 PostgreSQL」。macOS 上常見於同時裝了 `postgresql@16`、`postgresql@17`。解法：先用 `psql -d visual_memory -c "SHOW server_version;"` 看實際版本，再執行 `brew uninstall pgvector && brew install pgvector`（Homebrew 會對應目前的預設 PostgreSQL 版本），最後重跑 `CREATE EXTENSION`。

**Q3：`createdb: error: connection to server ... failed`。**
PostgreSQL 服務沒啟動，或 `PATH`／`PGPORT` 沒設好。執行 `brew services list` 確認 `postgresql@17` 狀態是 `started`；再執行 `echo $PGPORT` 確認印出 `5433`——沒有的話，確認步驟 3 的兩行 `export ...` 已寫進 `~/.zshrc` 並執行過 `source ~/.zshrc`。注意本機的 5432 是舊的 @14（別的專案在用），連錯埠會看到「資料庫不存在」或連線失敗。

**Q4：`ollama pull gemma4` 說找不到模型。**
模型名稱在 Ollama 官方庫中可能帶標籤（例如 `gemma4:latest` 或帶參數量的變體）。先執行 `ollama pull gemma4:latest` 試一次；若仍失敗，改用你的 Ollama 版本支援的多模態模型名稱，並記下這個名稱——Phase 2 會把它寫進 `app/core/config.py` 的 `VLM_MODEL` 常數，**換模型只要改這一個常數**（design.md §4.3 就是這樣規定的）。

**Q5：`uv pip install` 卡在編譯 psycopg。**
確認你裝的是 `psycopg[binary]`（清單裡已經是），它會直接下載編譯好的版本，不需要本機編譯器。若仍失敗，執行 `uv pip install --only-binary :all: "psycopg[binary]>=3.2"`。

**Q6：可不可以順便裝 Docker、CI、alembic、SQLAlchemy 之類的？**
**不要。** design.md §3 與 §4.3 明訂不用 ORM、不用 migration 工具，本專案也不做雲端部署。清單上沒有的一律不裝。

---

## 完成後的專案狀態

電腦上已經有可用的 Python 虛擬環境（含全部套件）、裝好 pgvector 的兩個 PostgreSQL 資料庫、以及能實際回應的 Ollama 與兩個模型（中英文都測過向量）——地基齊備，但還沒有任何一行專案程式碼。
