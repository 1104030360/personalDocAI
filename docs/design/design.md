# PersonalDocAI — 設計文件（舊名 Visual Memory RAG）

> **一句話：把照片變成可以用中文或英文問的記憶。**
> 上傳照片後，AI 會「看懂」照片並把內容存成文字與欄位；之後你直接問「我最近買過什麼飲料？」或「What drinks did I buy recently?」，系統會找出相關照片、依照片內容回答你。

> 🎯 **這是 side project：不要過度設計。** 只做本文件寫到的事；規格沒要求的功能、用不到的抽象層、「以後可能需要」的東西，一律不做。

本文件是本專案的 canonical design（**v4**），依 `docs/spec/prompts/4.design_prompt.md`，從已釐清的規格（`docs/spec/`：18 項釐清全數定案、12 條規則全數附例子）產出。只做設計，不含實作。狀態：**可進入實作規劃**（2026-08-18）。

---

## 0. 快速導覽（先看這裡）

整個系統只有 **兩個 API、一張資料表**：

```
【上傳】POST /photos
  照片 ──> AI 看圖(VLM) ──> 文字描述＋4個欄位 ──> 轉成向量 ──> 存進 PostgreSQL
                                                              (原始照片檔不保留)

【詢問】POST /ask（中文或英文都可以問）
  問題 ──> AI 判斷查法 ──┬─ 條件查詢(SQL 過濾欄位)  ──┐
                         └─ 語意查詢(向量找相近)    ──┴──> AI 依撈到的照片內容回答
                                                          （回答語言跟著問題走）
```

用一張 **Target 收據照片** 走一遍：

1. **上傳收據照** → AI 看圖後存下：
   - 文字描述：`在 Target 購買可樂與洋芋片的收據，日期 2026-08-10`
   - 四個欄位：類別=`收據`、地點=`Target`、物品=`[可樂, 洋芋片]`、內容時間=`2026-08-10`
   - 加上系統自動記的上傳時間，以及整段內容轉成的向量
2. **問「有哪些在 Target 拍的收據？」** → 問題帶明確條件（地點、類別）→ 走**條件查詢**：`WHERE location ILIKE 'Target' AND category ILIKE '收據'` → 找到這張 → AI 回答
3. **問「我最近買過什麼飲料？」**（或英文 "What drinks did I buy recently?"）→ 描述性問題 → 走**語意查詢**（向量相似度）＋「最近 = 30 天內」時間過濾 → AI 回答「可樂」

技術棧：**FastAPI**（API）＋ **PostgreSQL + pgvector**（儲存與向量搜尋）＋ **Ollama**（在本機跑 VLM/LLM 與 embedding——看圖、路由、回答、文字轉向量，全程**不需任何雲端 API key**）＋ **LangChain**（RAG 積木）＋ **LangGraph**（把詢問流程串成圖）。FastAPI／pgvector／LangChain／LangGraph 為規格指定；Ollama 本地執行、分層架構與雙語支援為使用者指示的設計變更（見 §4.3 決策變更記錄）。

---

## 1. 名詞小抄

| 名詞 | 白話解釋 |
|---|---|
| VLM（視覺語言模型） | 會「看圖說話」的 AI 模型。本設計用它把照片轉成文字描述＋四個欄位 |
| embedding／向量 | 把一段文字變成一串數字；**意思相近的文字，數字也相近**。這讓「飲料」能對到「可樂」，也讓中文問題能對到英文內容 |
| 語意查詢（vector semantic search） | 把問題也轉成向量，找出向量最接近的照片——比的是「意思」 |
| 條件查詢（metadata search） | 用固定欄位下 SQL 條件（地點=Target、類別=收據）——比的是「值」 |
| pgvector | PostgreSQL 的擴充套件，讓資料庫可以直接存向量、算相似度 |
| Ollama | 在自己電腦上跑開源 AI 模型的工具，提供本機 API（聊天、看圖、embedding），不需雲端服務與 API key |
| RAG | Retrieval-Augmented Generation：先「檢索」相關資料，再讓 AI「依資料」回答，避免瞎編 |
| LangChain | 提供 Document、embedding 介面等 RAG 積木的框架 |
| LangGraph | 把「判斷 → 查詢 → 回答」串成一張流程圖（graph）的框架 |
| router／service／repository | 分層架構的三層：router 收 HTTP 請求、service 做商業邏輯、repository 負責碰資料庫 |
| stub | 測試時用假物件替換真 AI／真時鐘，讓測試結果可預期 |

---

## 2. 這份文件的決策怎麼讀

每項設計都標了來源層級，遇到衝突時**上面的層級贏**：

| 標籤 | 意思 | 能不能改 |
|---|---|---|
| 【規格】 | 規格草案明定（技術棧、只有兩個功能） | 不可違反 |
| 【已釐清】 | Clarify 階段與使用者一問一答定案的 18 項決策 | 不得推翻（否決過的方案不重開） |
| 【設計】 | 本文件做的選擇（含使用者後續指示），附理由 | 可以重新論證後更改 |
| 【未定】 | open question | 目前：**無** |

依據優先序：`docs/spec/.clarify/resolved/`（含每題的解決記錄）→ `erm.dbml`＋`features/*.feature` → `design-draft.md`。撰寫時未發現來源互相衝突。

> ⚠️ repo 裡的 `docs/plan/dev-prompts/` 等舊檔與 `docs/design/draft.md` 是**另一個專案（FSE Chat Room）的殘留文件／舊複本**，與本專案無關，設計與實作都不得引用。

---

## 3. 範圍：做什麼、不做什麼

**做**【規格】：上傳照片、自然語言詢問，僅此兩項。定位是**小型、可實際 demo 的 side project backend**，重點在展示技術整合，一切從簡。

**雙語支援**【設計 v3，使用者指示】：詢問與回答支援**中文與英文**——回答語言跟隨提問語言；跨語言的內容召回由多語 embedding（bge-m3）天然支援（細節見 §5.2、§8.3）。

**極簡網頁介面**【設計 v4，使用者指示】：提供兩個網頁——**上傳照片頁**與**問答頁**——讓使用者直接從瀏覽器操作既有的兩個 API。純 HTML＋原生 JavaScript（fetch），由 FastAPI 以 StaticFiles 直接提供，零前端框架、零打包工具。**這不是第三個功能**：沒有新增任何交互點，只是同兩個功能的操作介面，不違反規格「僅兩項功能」。

**明確不做**（每一項都有依據）：

- ❌ 多使用者、帳號登入、`security.py`【已釐清：單一使用者、無認證】
- ❌ 保留或回傳原始照片檔【已釐清：處理完即丟，只留文字/欄位/向量】
- ❌ 照片瀏覽、刪除、編輯——任何第三個功能【規格：僅兩項】
- ❌ 非同步處理、佇列、處理狀態【已釐清：同步，上傳完成＝全部存好】
- ❌ metadata 自由欄位／延伸 JSON【已釐清：固定四欄位，多的直接丟】
- ❌ ORM 與 `models/`、alembic migration【設計：一張表、手寫 SQL，schema.sql 重建即可】
- ❌ 多輪對話記憶、前端框架（React/Vue 等——網頁介面用純 HTML/JS 即可【v4】）、雲端部署

**現況**：repo 是 greenfield——目前只有 `docs/`，零程式碼，全部從零開始。

---

## 4. 系統長什麼樣子

### 4.1 目錄結構【設計 v3：分層架構】

```
personalDocAI/
├── app/
│   ├── main.py                    # FastAPI app 組裝：掛上兩個 router
│   ├── dependencies.py            # 依賴注入點：get_vlm / get_embeddings / get_now
│   ├── api/
│   │   └── routers/
│   │       ├── photos.py          # POST /photos（格式檢查、415/422 錯誤轉換）
│   │       └── ask.py             # POST /ask
│   ├── schemas/
│   │   ├── photo.py               # UploadResponse、PhotoMetadata
│   │   └── ask.py                 # AskRequest、AskResponse
│   ├── services/
│   │   ├── vlm_service.py         # AI 看圖：照片 bytes → 文字＋四欄位
│   │   ├── indexing_service.py    # 把文字＋欄位合併成 Document、轉成向量
│   │   ├── retrieval_service.py   # 兩種查詢：語意 / 條件（含 30 天時間過濾）
│   │   └── ask_workflow.py        # LangGraph 流程圖：判斷 → 查詢 → 回答
│   ├── repositories/
│   │   └── photo_repository.py    # ★ 全系統唯一寫 SQL 的模組（psycopg）
│   ├── db/
│   │   └── session.py             # psycopg 資料庫連線
│   ├── core/
│   │   └── config.py              # 環境變數（DATABASE_URL、OLLAMA_BASE_URL）＋模型名稱、RECENT_DAYS=30 等常數
│   └── static/                    # 【v4】極簡網頁介面：純 HTML＋原生 JS，main.py 以 StaticFiles 提供
│       ├── upload.html            #   上傳照片頁（表單 → POST /photos，顯示理解結果）
│       └── ask.html               #   問答頁（輸入框 → POST /ask，顯示回答與依據照片）
├── db/schema.sql                  # 資料表 DDL（photo 表、pgvector、HNSW index）
└── tests/                         # pytest + pytest-bdd，直接拿 docs/spec/features/*.feature 當測試
```

**為什麼分層**：router／service／repository 是業界常見的 FastAPI 組織方式，職責分明、之後擴充有既定位置（使用者指示採用，兼具學習價值）。
**但依 side project 原則裁剪**——分層不等於加空殼：不建 `users/`、`messages/`（本專案沒有這些資源）、不建 `core/security.py`（無認證）、不建 `models/` 與 `alembic/`（無 ORM、單表用 schema.sql 重建）。每個存在的檔案都有活兒幹。

### 4.2 誰依賴誰（單向，不回頭）

```
main.py ──> api/routers/{photos,ask}.py ──> schemas/
                    │
     ┌──────────────┼────────────────────────────┐
photos.py ──> services/vlm_service.py（看圖，結果交回 router 寫入）
   │     └──> services/indexing_service.py（轉向量，交回 router 寫入）
ask.py ─────> services/ask_workflow.py ──> services/retrieval_service.py ──┐
   │                                                                       │
   └──（寫入）────────────────────> repositories/photo_repository.py <──────┘
                                          │ 使用 db/session.py 連線
                                          └──> PostgreSQL(+pgvector)

依賴注入：dependencies.py 提供 get_vlm / get_embeddings / get_now，測試時整組換成假件
外部服務：vlm_service、ask_workflow → Ollama 本機 chat API；indexing_service → Ollama 本機 embed API
（Ollama 是本機常駐服務 http://localhost:11434，不是雲端相依）
```

`photo_repository.py` 是唯一寫 SQL 的地方【設計】——資料存取集中一處，測試好替換、schema 好演進。

### 4.3 技術選型【設計】

| 項目 | 選擇 | 為什麼（被否決的方案） |
|---|---|---|
| 看圖／路由／回答的 AI | **Ollama 本地多模態模型**（預設 `gemma4`），一個模型三用途 | 全本地執行、零 API key、零雲端費用；Ollama 官方文件即以 gemma4 示範「看圖＋JSON schema 結構化輸出」。模型名稱是 config 常數，可自由換（如 Qwen 系列對中文更強）。（否決：v1 的 Claude `claude-opus-5`——使用者指示改為本地 Ollama） |
| 呼叫方式 | LangChain `ChatOllama`＋`with_structured_output()`（底層即 Ollama 的 `format` JSON schema），圖片以 base64 隨訊息傳入，`temperature=0` | Ollama 原生支援 schema 約束輸出且明文支援視覺模型；三個 AI 呼叫共用同一套 LangChain 介面，測試好替換 |
| 文字轉向量 | Ollama `bge-m3`（經 `langchain-ollama` 的 `OllamaEmbeddings`） | 同一個 Ollama 服務搞定；**多語模型，同時支撐中文與英文內容/提問的跨語言召回**；在 Ollama 官方 release 測試模型清單內。（否決：v1 的 Voyage voyage-3——雲端 API key；nomic-embed-text——偏英文且 768 維） |
| 向量維度 | `vector(1024)` | bge-m3 輸出 1024 維——**實作第一步要實測確認**，不符只改一個常數 |
| 資料庫存取 | psycopg 3（同步）＋手寫 SQL | 一張表、六種查詢，手寫 SQL 最好解釋。（否決：SQLAlchemy＋alembic——單表 side project 多兩層沒回報） |
| API 同步模型 | FastAPI 同步 `def`（跑 threadpool） | 上傳本來就是同步流程【已釐清】，避免 async 傳染整條呼叫鏈 |
| 架構樣式 | **分層**：api/routers → services → repositories，schemas 與 core 各歸其位 | 使用者指示（v3）；依 side project 原則裁剪空殼（見 §4.1）。（否決：v2 的單層扁平八模組——功能等價，惟使用者偏好業界分層樣式） |

> 📝 **決策變更記錄**：
> - **v1**（2026-08-18 上午）：模型採 Claude `claude-opus-5`＋Voyage `voyage-3`。
> - **v2**（同日）：依使用者指示改為 **Ollama 本地模型**（gemma4＋bge-m3）。
> - **v3**（同日）：依使用者指示——(a) 架構改為**分層**（api/routers／schemas／services／repositories／db／core，已裁剪空殼）；(b) 新增**中英雙語支援**；(c) 全案標註 **side project 不過度設計**原則。
> - **v4**（同日，本版）：依使用者指示新增**極簡網頁介面**——上傳頁＋問答頁，純 HTML＋原生 JS fetch，FastAPI StaticFiles 提供；不新增後端 API 與功能交互點、不用前端框架，於最後一個 phase 實作。
> 以上皆屬【設計】層級——規格只要求功能與技術棧存在，未指定供應商／架構樣式／語言範圍——變更合規；12 條 Rule 與所有【已釐清】決策不受影響。

---

## 5. 兩條流程的細節

### 5.1 上傳照片（`POST /photos`）

```
收到檔案
 ① routers/photos.py        檢查 content_type：非 JPEG/PNG → 415 結束【已釐清：格式限制、無大小上限】
 ② services/vlm_service.py  Ollama VLM 看圖 → {understood, text, category, location, items, content_time}
                            看不懂或呼叫失敗 → 422 結束，什麼都不存【已釐清】
 ③ services/indexing_service.py  文字＋四欄位 合併成一段文字 → Ollama bge-m3 轉成向量【已釐清：向量來源含 metadata】
 ④ repositories/photo_repository.py  一條 INSERT 寫入全部欄位（上傳時間由 DB now() 自動記）【已釐清：同步】
 ⑤ 回 201                   {id, text, metadata 四欄位}【已釐清：回應內容】
```

關鍵性質：**全程在同一個請求內完成；任何一步失敗＝整筆不存在**（只有一條 INSERT，天然原子，不會有「存了一半」的照片）。

### 5.2 自然語言詢問（`POST /ask`）

LangGraph 流程圖（與官方 adaptive-RAG 範例同款的條件路由模式）：

```
        START
          │  route：Ollama LLM 結構化輸出 → 查法 + 過濾條件（中文或英文問題皆可）
          │        判斷失敗/出錯 → 一律走語意查詢【已釐清 fallback】
   ┌──────┴──────┐
條件查詢        語意查詢          ←（兩邊都套用時間過濾，若問題含「最近」等時間條件）
(SQL 過濾)    (向量相似 top-5)
   └──────┬──────┘
       generate：Ollama LLM 只依撈到的照片內容回答，回答語言跟隨提問語言
               撈不到 → 回「查無相關照片」，禁止編造【已釐清】
          END → 200 {answer, search_mode, retrieved_photo_ids}
```

流程圖的 state【設計】：

```python
class AskState(TypedDict):
    question: str
    mode: str                        # "metadata" | "vector"
    filters: QueryFilters            # category / location / item / recent（皆可空）
    retrieved: list[RetrievedPhoto]  # id + text + 四欄位
    answer: str
```

**路由怎麼判斷**【設計】：一次 Ollama LLM 結構化輸出呼叫，同時回傳查法與過濾條件：

```python
class RouteDecision(BaseModel):
    mode: Literal["metadata", "vector"]
    category: str | None   # 例：收據
    location: str | None   # 例：Target
    item: str | None       # 例：可樂
    recent: bool           # 問題是否含「最近／recently」類時間條件
```

判斷標準寫進 prompt（即已釐清的定義）：**帶明確條件（商家/類別/時間）→ 條件查詢；描述性問題 → 語意查詢**。few-shot 錨點含中英文例句：「有哪些在 Target 拍的收據？」→ 條件查詢、「我最近買過什麼飲料？」與 "What drinks did I buy recently?" → 語意查詢。呼叫出錯或格式不符 → `mode="vector"`、條件全空。

**時間過濾**（兩條查詢路共用）【已釐清】：「最近」＝詢問當下回推 **30 天**（`core/config.py` 常數）；優先用照片的內容時間，內容時間空的照片改用上傳時間——SQL 一句話落實：

```sql
COALESCE(content_time, uploaded_at::date) >= (今天 - 30天)
```

---

## 6. HTTP API 契約

### `POST /photos` — 上傳照片

Request：`multipart/form-data`，欄位 `file`。

成功 `201`：

```json
{ "id": 1,
  "text": "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
  "metadata": { "category": "收據", "location": "Target",
                "items": ["可樂", "洋芋片"], "content_time": "2026-08-10" } }
```

失敗（規格說「操作失敗」，HTTP 落地是【設計】）：

| 狀態碼 | 情境 | 回應 |
|---|---|---|
| `415` | 檔案不是 JPEG/PNG（不進任何後續處理） | `{"detail": "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"}` |
| `422` | VLM 看不懂照片或呼叫失敗（什麼都不存） | `{"detail": "VLM 無法理解照片內容，未儲存任何資料"}` |

不設檔案大小上限【已釐清】——刻意不寫任何 max-size 檢查。

### `POST /ask` — 自然語言詢問（中/英文皆可）

Request：`{"question": "有哪些在 Target 拍的收據？"}` 或 `{"question": "Which receipts were taken at Target?"}`

成功 `200`：

```json
{ "answer": "你有一張 8 月 10 日在 Target 購買可樂與洋芋片的收據。",
  "search_mode": "metadata search",
  "retrieved_photo_ids": [1] }
```

為什麼多回 `search_mode` 和 `retrieved_photo_ids`【設計】：規格的驗收例子要驗「系統選了哪種查法」「回答依據哪些照片」——放進回應，測試就能**黑箱驗證**。查無結果時 `retrieved_photo_ids` 為 `[]`、`answer` 是 AI 產生的查無回覆（語言跟隨提問）。

`question` 缺漏或空字串 → 框架既有的 `422`（規格沒定義詢問前置條件，不另外發明行為）。

### 網頁介面【v4】

`app/static/` 的兩個靜態頁由 main.py 以 StaticFiles 掛載（如 `/ui/upload.html`、`/ui/ask.html`）：上傳頁＝檔案選擇表單 → `fetch POST /photos` → 顯示 201 的理解結果或 415/422 錯誤訊息；問答頁＝問題輸入框（中英文皆可）→ `fetch POST /ask` → 顯示 `answer`、`search_mode` 與依據照片 id。**不新增任何其他後端端點**；頁面驗收以手動瀏覽器操作為準。

---

## 7. 資料庫設計

規格的 ERM（受限只能用 int/float/string 等型別標記）落地成真實 PostgreSQL 型別【設計】：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE photo (
  id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text         text        NOT NULL,               -- VLM 的文字描述（失敗就不存，所以不會空）
  category     text,                               -- 類別（如：收據），可空
  location     text,                               -- 地點/商家（如：Target），可空
  items        text[]      NOT NULL DEFAULT '{}',  -- 物品清單（多值）
  content_time date,                               -- 內容時間（如收據日期），可空【已釐清】
  uploaded_at  timestamptz NOT NULL DEFAULT now(), -- 上傳時間，DB 自動記【已釐清】
  embedding    vector(1024) NOT NULL               -- 文字＋欄位合併內容的向量【已釐清】
);

CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);
```

型別選擇的理由（皆【設計】）：

- `id` 用 DB 自增整數——沒有跨系統需求，UUID 被否決
- `category`/`location` 允許空——風景照可能沒類別/商家（規格驗收資料裡就有空欄位）
- `items` 用原生陣列 `text[]`——可直接對清單過濾；否決 JSONB（無巢狀需求）與子表（單表不值得 join）
- `content_time` 用 `date`——規格例子都是日期精度（收據日期），和 30 天運算相容
- 向量索引用 HNSW＋cosine（pgvector 官方語法）；**不建其他索引**——demo 資料量 seq scan 就夠

---

## 8. 三個 AI 呼叫的設計

### 8.1 看圖（services/vlm_service.py）

一次 `ChatOllama.with_structured_output(PhotoUnderstanding)` 呼叫（底層是 Ollama 的 `format` JSON schema，官方文件明文支援視覺模型＋結構化輸出的組合）：base64 圖片＋指示 → 結構化輸出，`temperature=0` 求穩定：

```python
class PhotoUnderstanding(BaseModel):
    understood: bool          # 看不懂 → false
    text: str                 # 文字描述（以照片內容的主要語言撰寫，中/英皆可）
    category: str | None
    location: str | None
    items: list[str]
    content_time: str | None  # ISO 日期，推不出來 → null
```

- Prompt 明文只准填這些欄位——「清單外資訊一律捨棄」【已釐清】在源頭落實，不靠後段過濾。
- **語言**【設計 v3】：文字描述與欄位值以**照片內容的主要語言**為準（英文收據就寫英文），不強制翻譯——跨語言的召回交給多語 embedding（§8.3）。
- **失敗的定義**【設計】：`understood=false`、格式驗證失敗、呼叫例外（含 Ollama 服務未啟動，重試後仍失敗）→ 通通視為「VLM 無法理解」→ 422 不存。
- `content_time` 解析不出日期 → 當 null，**不**讓上傳失敗。

### 8.2 路由（services/ask_workflow.py 的 route 節點）

見 §5.2——一次結構化輸出同時拿到查法與條件，中英文問題皆可；出錯就 fallback 語意查詢。

### 8.3 回答（services/ask_workflow.py 的 generate 節點）與雙語策略

輸入＝問題＋撈到的照片（id、文字、四欄位）。Prompt 的三條鐵律：

1. **只能依據提供的照片內容回答**，不得用外部知識補充
2. 撈不到照片 → 回「查無相關照片」的自然語言，**不得虛構**【已釐清】
3. **回答語言跟隨提問語言**（中文問→中文答、英文問→英文答），直接回答

**雙語支援怎麼落地**【設計 v3】：

- **語意查詢天然跨語言**：bge-m3 是多語 embedding，「What drinks did I buy?」的向量能召回中文寫的「可樂」內容——這正是 v2 選它的原因，v3 直接受益
- **條件查詢用大小寫不敏感比對**：`ILIKE`（見 §9），"target" 能中 "Target"
- **已知限制（刻意不解）**：條件查詢的值**不做跨語言翻譯對映**（問 "receipts" 不會自動對到存成「收據」的類別）——做翻譯對映屬過度設計；跨語言問題自然會被 router 判給語意查詢路徑，該路徑本來就跨語言

`search_mode` 和 `retrieved_photo_ids` 從流程 state 直接取，**不經過 AI**【設計】。

---

## 9. 檢索層與最關鍵的一個設計決策

**DD-4【設計】：不用 LangChain 的 PGVector vector store。**

原因：PGVector store 自帶表結構（UUID 主鍵＋JSONB metadata），跟已釐清的固定欄位 schema（整數 id、獨立欄位、可 SQL 過濾）**直接衝突**，硬用會變成兩張表雙寫。

取而代之：`photo` 一張表是唯一事實來源；LangChain 的規格角色由三個積木滿足——**Embeddings 介面**（OllamaEmbeddings）＋ **Document 組裝** ＋ 官方文件示範的 **`@chain` 自訂 retriever**（回傳 `list[Document]` 的 Runnable）。被否決：PGVector store（schema 衝突）、完全不用 LangChain（違反規格）。

`services/retrieval_service.py` 的兩條查詢（SQL 都在 `repositories/photo_repository.py`）：

```sql
-- 語意查詢：問題轉向量 → 找最近的 5 張（<=> 是 pgvector 的 cosine 距離）
SELECT id, ... FROM photo [WHERE 時間過濾]
ORDER BY embedding <=> %(qvec)s LIMIT 5;

-- 條件查詢：route 抽出的條件全部 AND；ILIKE = 大小寫不敏感比對【設計 v3，支援英文值】
SELECT id, ... FROM photo
WHERE category ILIKE %(category)s AND location ILIKE %(location)s
  AND EXISTS (SELECT 1 FROM unnest(items) AS i WHERE i ILIKE %(item)s)
  [AND 時間過濾];
```

Document 合併規則【設計】：`page_content` = 固定順序的 `{text}\n類別: …\n地點: …\n物品: …\n時間: …`（空欄位省略）——順序固定，同輸入同向量，才可測試。

---

## 10. 錯誤處理總表

| 情境 | 依據 | HTTP | 行為 |
|---|---|---|---|
| 上傳非圖片格式 | 已釐清 | 415 | 不呼叫 VLM、不寫入 |
| VLM 看不懂／呼叫失敗 | 已釐清 | 422 | 什麼都不存 |
| 檔案太大 | 已釐清：無上限 | — | 沒有這個錯誤路徑 |
| 問題缺漏/空字串 | 規格未定義 | 422（框架既有） | 不另外發明行為 |
| 路由 AI 失敗 | 已釐清 | 200 | fallback 語意查詢，流程繼續 |
| 查無相關照片 | 已釐清 | 200 | AI 回覆查無、`retrieved_photo_ids: []` |
| DB 掛了／embedding 呼叫失敗（如 Ollama 未啟動） | 規格未定義 | 500（框架既有） | 不吞錯，log 留原始錯誤 |

---

## 11. 測試策略

驗收基準＝`docs/spec/features/` 兩份檔案（**12 條 Rule、14 個 Example**：上傳 7＋詢問 7），用 pytest＋pytest-bdd 直接掛上 feature 檔，配本機 PostgreSQL 測試庫（每測清空 `photo` 表）。規格例子皆為中文；**雙語行為（英文提問）以少量額外單元測試＋煙霧測試覆蓋**，不改動規格檔【設計 v3】。

規格的例子把 VLM 結果寫在 When 步驟裡——這暗示**所有外部智能都要能換成假的**。因此 AI client、embeddings、時鐘全部經 `dependencies.py` 注入，測試時 override：

| 假物件 | 行為 | 驗的例子 |
|---|---|---|
| FakeVLM | 照步驟指定的內容回傳；「看不懂」情境回 `understood=false` | 上傳的全部 7 條規則 |
| FakeEmbeddings | 決定論向量（詞彙雜湊），讓「飲料→可樂」排序可預期 | 語意查詢 |
| FakeRouter | 照例子指定回查法；模糊問題回「無法判斷」驗 fallback | 路由＋fallback |
| FakeAnswerLLM | 拿檢索結果模板化回答；空結果回查無句式 | 回答＋查無 |
| FixedClock（實作＝覆寫 get_now 的假函式） | 「現在時間為 …」的 Given | 上傳時間＋30 天過濾 |

真 Ollama 模型只做少量手動煙霧測試（都在本機跑，含至少一個英文提問例子），不進驗收與 CI。

---

## 12. 實作順序（六個切片，每片交付即可驗證）

```
S1 建表＋repository ──> S2 上傳端點(全假件，上傳7條規則全綠) ──> S3 接真模型(實測向量維度)
S1 ────────────────> S4 檢索層(兩種查詢＋時間邊界測試)      ──┐
                                          S3 ─────────────────┴─> S5 LangGraph＋/ask(詢問5條規則全綠)
                                                                  S6 錯誤路徑收尾＋全量回歸＋煙霧測試
```

（細部拆解見 `docs/plan/unfinish/` 的 phase 文件。）

---

## 13. 規則覆蓋對照（12 條全有人負責）

| # | 規則（節錄） | 負責位置 |
|---|---|---|
| U1 | 非圖片格式上傳失敗 | routers/photos.py content_type 檢查（§6） |
| U2 | 儲存文字描述（不含原始檔） | vlm_service → photo_repository（§5.1、§8.1） |
| U3 | 儲存四欄位 metadata、清單外捨棄 | vlm_service schema＋prompt（§8.1） |
| U4 | 儲存向量（文字＋metadata 合併） | indexing_service（§9） |
| U5 | 記錄上傳時間 | photo_repository `DEFAULT now()`（§7） |
| U6 | 成功回應 id＋文字＋metadata | routers/photos.py／schemas/photo.py（§6） |
| U7 | VLM 看不懂 → 失敗不儲存 | vlm_service 失敗判定＋422（§8.1、§10） |
| Q1 | 依問題類型選查法 | ask_workflow route 節點（§5.2）＋回應 `search_mode`（§6） |
| Q2 | 時間過濾：內容時間優先、空用上傳時間 | photo_repository 的 COALESCE（§5.2、§9） |
| Q3 | 無法判斷 → 語意查詢 | route 節點 fallback 分支（§5.2） |
| Q4 | 查無 → 回覆查無、不編造 | generate prompt 鐵律（§8.3） |
| Q5 | 檢索內容交給 AI 回答 | ask_workflow generate 節點（§8.3） |

約束稽核（無第三功能、無原始檔路徑、僅四欄位、同步、LLM 路由＋vector fallback、空結果經 LLM 禁編造、30 天/內容時間優先）已逐項核對，**無違反**。

---

## 14. 假設、限制與未定案

**假設**（實作時要驗證，不是既定事實）：

- bge-m3 輸出 1024 維 → 實作早期以 `len(embed_query(...))` 實測；不符只改 `vector(n)` 常數
- 本機已安裝 Ollama，且已 `ollama pull` 所選的多模態模型（預設 `gemma4`）與 `bge-m3`
- 本地多模態模型對**中文與英文**照片內容的理解品質足以 demo（不足時換模型＝改一個 config 常數，如換 Qwen 系列）
- 測試環境有裝好 pgvector 的本機 PostgreSQL

**限制**：真實 AI 輸出非決定論，驗收全靠假件；條件查詢不做跨語言翻譯對映（§8.3 的已知限制）；未設計大資料量的索引與分頁（side project 定位，明確不做）。

**未定案（open questions）：無**——規格 18 項全數定案，撰寫過程未發現需要回饋規格的新歧義。

---

## 15. 來源清單（Source Inventory）

**規格來源（全數讀取）**：`docs/spec/draft/design-draft.md`、`docs/spec/erm.dbml`、`docs/spec/features/上傳照片.feature`（7 Rules）、`docs/spec/features/自然語言詢問.feature`（5 Rules）、`docs/spec/.clarify/overview.md`、`.clarify/resolved/data/`（7 份）、`.clarify/resolved/features/`（11 份）、`/Users/linjunting/CLAUDE.md`；repo 現況實查（greenfield）。

**外部查證**（Context7 MCP＋官方文件，2026-08-18）：

- LangGraph 條件路由（`add_conditional_edges(START, route, {...})`）：<https://github.com/langchain-ai/langgraph>（adaptive/corrective RAG 範例）
- pgvector `vector` 型別、`<=>` cosine、HNSW index：<https://github.com/pgvector/pgvector>
- LangChain 自訂 retriever（`@chain`）與 `Document`：<https://docs.langchain.com/oss/python/langchain/knowledge-base>
- Ollama 結構化輸出（`format`＝JSON schema，官方即以視覺模型＋Pydantic schema 示範）與視覺輸入：<https://github.com/ollama/ollama>（docs/capabilities/structured-outputs.mdx、docs/capabilities/vision.mdx、docs/api.md）
- Ollama embeddings API（`POST /api/embed`）與官方 release 測試 embedding 模型清單（含 `bge-m3`）：<https://github.com/ollama/ollama>
- LangChain 的 `ChatOllama`／`with_structured_output`／`OllamaEmbeddings`：<https://docs.langchain.com/oss/python/langchain/models>、<https://docs.langchain.com/oss/python/langchain/knowledge-base>
- FastAPI `UploadFile`／`content_type`：<https://fastapi.tiangolo.com/tutorial/request-files>、<https://fastapi.tiangolo.com/reference/uploadfile>
- （v1 已置換選型的查證來源，僅存參考）Claude API：<https://platform.claude.com/docs>；Voyage：<https://docs.voyageai.com>
