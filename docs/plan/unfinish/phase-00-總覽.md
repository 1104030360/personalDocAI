# Phase 0：總覽（實作路線圖）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> **一句話：把照片變成可以用中文或英文問的記憶。**
> 上傳照片後，AI 會「看懂」照片並把內容存成文字與欄位；之後你直接問「我最近買過什麼飲料？」或 "What drinks did I buy recently?"，系統會找出相關照片、依照片內容回答你——**回答語言跟著你的提問走**。

本文件是 `docs/design/design.md`（唯一權威設計文件，目前版本 **v4**）的**實作路線圖**。設計文件說「系統長什麼樣子」，這份路線圖說「照什麼順序做出來」。

---

## 0. 這份路線圖怎麼用

- **一定要照編號依序做**：Phase 01 → Phase 02 → … → Phase 14。每個 phase 都假設前一個已經完成。
- **每個 phase 結束時，系統都處於「可驗證的狀態」**：你可以跑一段指令，看到預期的輸出，確定自己沒做錯。
- **依序做完 14 個 phase＝完成 design.md v4 描述的完整系統**：兩個 API（`POST /photos`、`POST /ask`）＋12 條 Gherkin Rule 全數通過＋中英雙語行為有測試把關＋兩個純 HTML 網頁介面。
- 讀者假設是**程式新手**：每個技術名詞第一次出現都會用一句白話解釋，指令可以直接複製貼上執行（macOS）。

**四個貫穿全案的原則**（每個 phase 都適用）：

1. **side project，不過度設計**——只做文件寫到的事。看到「順便加個抽象層」「以後可能會用到」的念頭，答案一律是「不要」。
2. **分層架構，但不建空殼**——`api/routers → services → repositories` 三層各司其職；design.md §4.1 明訂**不建** `models/`、`core/security.py`、`alembic/`、`users/`、`messages/`。每個存在的檔案都有活兒幹。
3. **中英雙語**——照片內容、提問、回答都可能是中文或英文；規格 `.feature` 檔維持中文且**不得修改**，雙語行為用額外的單元測試與手動煙霧測試覆蓋。
4. **網頁介面極簡**【v4】——最後一個 phase 加兩個純 HTML 頁面操作既有的兩個 API：零框架、零打包工具、零新增端點。頁面醜沒關係，能用就好。

**先記住幾個名詞**（design.md §1 名詞小抄的濃縮版，另補上路線圖會用到的幾個詞）：

| 名詞 | 白話解釋 |
|---|---|
| API | 程式對外開放的「窗口」。這個專案有兩個窗口：上傳照片、問問題 |
| FastAPI | 用 Python 寫 API 的框架，本專案的兩個窗口都用它做 |
| PostgreSQL | 老牌的開源資料庫系統，本專案所有資料（文字、欄位、向量）都存在這裡 |
| VLM（視覺語言模型） | 會「看圖說話」的 AI 模型。把照片轉成文字描述＋四個欄位 |
| LLM（大型語言模型） | 會讀文字、寫文字的 AI 模型。這裡用來「判斷查法」與「產生回答」 |
| few-shot | 在給 AI 的指示裡先放幾個「問題 → 正確答案」的範例，讓 AI 照樣照做 |
| embedding／向量 | 把一段文字變成一串數字；**意思相近的文字，數字也相近**。多語模型還能讓中文問題對到英文內容 |
| 語意查詢 | 把問題也轉成向量，找出向量最接近的照片——比的是「意思」 |
| 條件查詢 | 用固定欄位下 SQL 條件（地點=Target、類別=收據）——比的是「值」 |
| ILIKE | SQL 的「不分大小寫比對」。`location ILIKE 'target'` 找得到存成 `Target` 的資料 |
| COALESCE | SQL 的「取第一個有值的欄位」。`COALESCE(內容時間, 上傳時間)`：內容時間有值就用它，沒有就退回上傳時間 |
| pgvector | PostgreSQL 的擴充套件，讓資料庫可以直接存向量、算相似度 |
| Ollama | 在自己電腦上跑開源 AI 模型的工具，提供本機 API，不需雲端服務與 API key |
| RAG | 先「檢索」相關資料，再讓 AI「依資料」回答，避免瞎編 |
| LangChain | 提供 Document、embedding 介面等 RAG 積木的框架 |
| LangGraph | 把「判斷 → 查詢 → 回答」串成一張流程圖（graph）的框架 |
| router / service / repository | 分層架構的三層：router 收 HTTP 請求、service 做商業邏輯、repository 負責碰資料庫 |
| stub（假件） | 測試時用假物件替換真 AI／真時鐘，讓測試結果可預期 |
| Gherkin／`.feature` | 用「Given / When / Then」寫成的規格文件，可以直接當測試跑 |
| pytest／pytest-bdd | pytest 是 Python 的測試框架；pytest-bdd 是它的外掛，讓 `.feature` 檔可以直接被 pytest 當測試執行 |
| uv | 新一代 Python 套件管理工具（一個指令取代 pip 與 venv），速度快、會自動下載需要的 Python 版本 |
| 煙霧測試（smoke test） | 用真實服務把主要流程快速走一遍，確認整條路接得起來——不求詳盡，能冒煙就知道有沒有著火 |
| StaticFiles | FastAPI 內建的「送靜態檔案」功能：把一個資料夾掛上網址，瀏覽器就能直接開裡面的 HTML |
| fetch | 瀏覽器內建的 JavaScript 功能，讓網頁直接呼叫後端 API |

---

## 1. 全部 Phase 清單

> 📁 **歸檔規則（2026-08-19 起）**：已完成的 phase 計畫檔移到 `docs/plan/finish/`（目前：01〜04 已歸檔），未完成的留在本資料夾；本總覽（phase-00）恆留 `unfinish/` 供導覽。

| Phase | 檔名 | 一句話 |
|---|---|---|
| 01 | `phase-01-環境準備.md` | 裝好 Python 虛擬環境與套件、PostgreSQL＋pgvector、Ollama 並下載 `gemma4` 與 `bge-m3` 兩個模型 |
| 02 | `phase-02-專案骨架.md` | 建出 design.md §4.1 的**分層目錄**（api/schemas/services/repositories/db/core）與 `core/config.py`，讓 FastAPI 能啟動並回應健康檢查（health check：一個回「服務活著」的測試端點） |
| 03 | `phase-03-資料庫與存取模組.md` | 寫 `db/schema.sql` 建出 `photo` 資料表，並完成 `db/session.py`（連線）與 `repositories/photo_repository.py`（全系統唯一寫 SQL 的模組） |
| 04 | `phase-04-上傳端點與格式檢查.md` | 做出 `api/routers/photos.py` 的 `POST /photos` 骨架，非 JPEG/PNG 一律回 415 且不做任何後續處理 |
| 05 | `phase-05-看圖模組.md` | 寫 `services/vlm_service.py`（先用假件驅動，prompt 明訂描述用照片主要語言），看不懂或呼叫失敗一律回 422 且什麼都不存 |
| 06 | `phase-06-向量與寫入.md` | 寫 `services/indexing_service.py` 把文字＋四欄位合併成 Document 並轉成向量，經 repository 寫進資料庫、回傳 201 |
| 07 | `phase-07-上傳驗收測試.md` | 用 pytest-bdd 直接掛上 `上傳照片.feature`，7 條 Rule（U1〜U7）全綠，並補一個**英文照片**的雙語單元測試 |
| 08 | `phase-08-接上真實模型.md` | 把假的 AI 換成真的 Ollama（`gemma4` 看圖、`bge-m3` 轉向量），**實測 bge-m3 的向量維度**，並用中英文各跑一次煙霧測試 |
| 09 | `phase-09-檢索層.md` | 寫 `services/retrieval_service.py` 的兩條查詢與「最近 30 天」時間過濾；條件查詢一律用 **ILIKE**（含 `unnest` ILIKE）支援英文值 |
| 10 | `phase-10-路由與流程圖.md` | 寫 `services/ask_workflow.py` 的 LangGraph 骨架與 route 節點（few-shot 含中英文例句），判斷失敗一律 fallback 語意查詢 |
| 11 | `phase-11-回答與詢問端點.md` | 加上 generate 節點（鐵律：回答語言跟隨提問語言）與 `api/routers/ask.py` 的 `POST /ask`，回傳 `answer`／`search_mode`／`retrieved_photo_ids` |
| 12 | `phase-12-詢問驗收測試.md` | 用 pytest-bdd 掛上 `自然語言詢問.feature`，5 條 Rule（Q1〜Q5）全綠 |
| 13 | `phase-13-錯誤收尾與全量回歸.md` | 補齊錯誤處理總表所有路徑、跑完 12 條 Rule 全量回歸（把全部測試從頭再跑一次，確認後面的修改沒弄壞前面的功能），並用真模型做中英雙語手動煙霧測試（smoke test：用真實服務快速走一遍主流程）——**後端到此完成** |
| 14 | `phase-14-網頁介面.md` | 【v4】加上 `app/static/upload.html` 與 `ask.html` 兩個純 HTML 頁面（原生 JS `fetch`），`main.py` 以 StaticFiles 掛在 `/ui`；零框架、零打包工具、零新增端點，驗收全靠手動瀏覽器操作 |

---

## 2. Phase 相依順序

```
 P01 環境準備（Python / PostgreSQL+pgvector / Ollama）
  │
  ▼
 P02 分層骨架＋core/config.py
  │
  ▼
 P03 db/schema.sql＋db/session.py＋repositories/photo_repository.py ──┐
  │                                             （P09 也需要 repository）│
  ▼                                                                    │
 P04 api/routers/photos.py 骨架＋格式檢查(415)                          │
  │                                                                    │
  ▼                                                                    │
 P05 services/vlm_service.py（假件驅動）＋看不懂(422)                    │
  │                                                                    │
  ▼                                                                    │
 P06 services/indexing_service.py＋寫入 DB＋201 回應                    │
  │                                                                    │
  ▼                                                                    │
 P07 pytest-bdd：上傳照片.feature 全綠 ★U1〜U7（＋英文照片單元測試）     │
  │                                                                    │
  ▼                                                                    │
 P08 接真 Ollama 模型（實測 bge-m3 維度＋中英煙霧測試）                  │
  │                                                                    │
  ▼                                                                    │
 P09 services/retrieval_service.py 兩路查詢＋30 天過濾＋ILIKE ◀─────────┘
  │
  ▼
 P10 services/ask_workflow.py LangGraph 骨架＋route 節點（含 fallback、中英 few-shot）
  │
  ▼
 P11 generate 節點（回答語言跟隨提問）＋api/routers/ask.py
  │
  ▼
 P12 pytest-bdd：自然語言詢問.feature 全綠 ★Q1〜Q5
  │
  ▼
 P13 錯誤路徑收尾＋12 條 Rule 全量回歸＋中英雙語真模型煙霧測試  ← 後端完成
  │
  ▼
 P14 app/static/ 兩個 HTML 頁面＋main.py 掛 StaticFiles（手動瀏覽器驗收）
```

★ 標記＝驗收里程碑。P14 只加靜態頁，不動任何後端邏輯與測試。

---

## 3. 12 條 Gherkin Rule ➜ 在哪個 Phase 被實作與驗證

Rule 清單直接取自兩份 `.feature` 檔的實際內容，**編號即檔案內順序**。

> ✅ **編號說明**：design.md §13 的 U/Q 編號與本表一致（皆依 `.feature` 檔案內順序），兩邊可直接對照。

### 3.1 `docs/spec/features/上傳照片.feature`（7 條 Rule）

| # | Rule 原文（節錄） | 實作於 | 自動化驗證於 |
|---|---|---|---|
| U1 | 上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗 | **P04**（`api/routers/photos.py` content_type 檢查 → 415） | **P07**、P13 回歸 |
| U2 | 上傳照片後，系統儲存照片資訊（VLM 理解照片內容後轉成的文字；不含原始照片檔） | **P05**（`services/vlm_service.py` 產文字）＋ **P06**（`repositories/photo_repository.py` 寫入 `text`） | **P07**、P13 回歸 |
| U3 | 上傳照片後，系統儲存 VLM 產生的結構化 metadata（照片類別、地點/商家、物品清單、內容時間；清單外資訊捨棄） | **P05**（`PhotoUnderstanding` 六欄位＋prompt 明文只准填這些）＋ **P06**（寫入四欄位） | **P07**、P13 回歸 |
| U4 | 上傳照片後，系統儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生） | **P06**（`services/indexing_service.py` 合併 Document → 轉向量 → 寫入 `embedding`） | **P07**、P13 回歸 |
| U5 | 上傳照片後，系統記錄上傳時間 | **P03**（`uploaded_at` 欄位＋`DEFAULT now()`）＋ **P06**（寫入路徑） | **P07**、P13 回歸 |
| U6 | 上傳照片成功後，系統回應照片識別碼、文字描述與 metadata | **P02**（`schemas/photo.py` 的 `UploadResponse`）＋ **P06**（201 回應） | **P07**、P13 回歸 |
| U7 | VLM 無法理解照片內容時，上傳失敗且不儲存任何資料 | **P05**（`understood=false`／例外 → 422，不寫入） | **P07**、P13 回歸 |

### 3.2 `docs/spec/features/自然語言詢問.feature`（5 條 Rule）

| # | Rule 原文（節錄） | 實作於 | 自動化驗證於 |
|---|---|---|---|
| Q1 | 詢問時，系統根據問題類型決定走 vector semantic search 或 PostgreSQL metadata search | **P10**（`services/ask_workflow.py` route 節點＋條件邊）＋ **P11**（回應的 `search_mode`） | **P12**、P13 回歸 |
| Q2 | 詢問含時間條件時，系統以內容時間過濾，內容時間為空的照片以上傳時間過濾 | **P09**（`repositories/photo_repository.py` 的 `COALESCE(content_time, uploaded_at::date) >= 今天-30天`） | **P12**、P13 回歸 |
| Q3 | 無法判斷問題類型時，系統走 vector semantic search | **P10**（route 例外／格式不符 → `mode="vector"`、條件全空） | **P12**、P13 回歸 |
| Q4 | 檢索不到任何相關內容時，系統回覆查無相關照片（由 LLM 產生，不得編造照片內容） | **P11**（generate 節點 prompt 三條鐵律） | **P12**、P13 回歸 |
| Q5 | 詢問後，系統將檢索到的內容交給 LLM 產生回答 | **P11**（generate 節點＋回應的 `retrieved_photo_ids`） | **P12**、P13 回歸 |

> **覆蓋檢查**：12 條 Rule 全數出現在上表，每條都至少有一個「實作 Phase」與一個「驗證 Phase」。P07 覆蓋 U1〜U7、P12 覆蓋 Q1〜Q5、P13 把兩份 `.feature` 一起跑一次做全量回歸。**沒有任何一條 Rule 沒有主人。**

> 📄 **P14（網頁介面）不在上表**，這是正確的：它**不是第三個功能**，也不對應任何一條 Rule——只是同兩個既有 API 的瀏覽器操作介面（design.md §3、§6）。它不新增後端端點、不改動任何測試。

### 3.3 雙語需求 ➜ 在哪個 Phase 落實

規格 `.feature` 檔全為中文且不得修改，所以雙語行為靠**實作要求＋額外測試**落實（design.md §8.3、§11）：

| 雙語需求（design.md 出處） | 實作於 | 驗證於 |
|---|---|---|
| VLM 的文字描述與欄位用**照片主要語言**，不強制翻譯（§8.1） | **P05**（`vlm_service.VLM_PROMPT`） | **P07**（`tests/test_upload_bilingual.py`） |
| 條件查詢用 **ILIKE**（含 `unnest` ILIKE）大小寫不敏感比對（§9） | **P09**（`photo_repository.search_by_metadata`） | **P09**（2 個大小寫測試） |
| route 的 few-shot 含**英文例句** `"What drinks did I buy recently?"`（§5.2） | **P10**（`ask_workflow.ROUTE_PROMPT`） | **P10**（英文提問走語意查詢） |
| generate 鐵律：**回答語言跟隨提問語言**（§8.3） | **P11**（`ask_workflow.ANSWER_PROMPT`） | **P11**（英文提問得英文回答） |
| 跨語言召回由多語 embedding `bge-m3` 天然支援（§5.2、§8.3） | **P08**（接上真模型） | **P08**、**P13**（真模型手動煙霧測試含英文提問） |
| **已知限制（刻意不解）**：條件查詢不做跨語言翻譯對映（§8.3） | ——（不實作） | **P09** 常見問題、**P13** 常見問題 |
| 問答頁的輸入框中英文皆可、回答語言跟隨提問（§6 網頁介面【v4】） | **P14**（`app/static/ask.html`） | **P14**（手動瀏覽器操作：中英各問一次） |

---

## 4. 最終長出來的專案結構

依序做完 14 個 phase 之後，`/Users/linjunting/personalDocAI/` 會長成這樣。`app/`、`db/`、`tests/` 三個部分與 design.md §4.1 一致；其餘（`.venv/`、`.env`、`.gitignore`、`requirements.txt`、`scripts/`、`pytest.ini`）是開發過程需要的輔助檔案，design.md 不管到這個層級：

```
personalDocAI/
├── .venv/                     # Python 虛擬環境（P01，由 uv 建立）
├── .env                       # 環境變數（P02）
├── .gitignore                 # 排除 .venv/.env 等不進版本控制的檔案（P02）
├── requirements.txt           # 套件清單（P01）
├── pytest.ini                 # pytest 設定（P05）
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI app 組裝：掛上兩個 router ＋ StaticFiles（P02、P04、P11、P14）
│   ├── dependencies.py        # 依賴注入點：get_vlm / get_embeddings / get_now / get_router / get_answerer / get_today（P02、P05、P06、P11）
│   ├── api/
│   │   ├── __init__.py
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── photos.py      # POST /photos（格式檢查、415/422 錯誤轉換）（P04、P05、P06）
│   │       └── ask.py         # POST /ask（P11）
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── photo.py           # UploadResponse、PhotoMetadata（P02）
│   │   └── ask.py             # AskRequest、AskResponse（P02、P11）
│   ├── services/
│   │   ├── __init__.py
│   │   ├── vlm_service.py     # AI 看圖：照片 bytes → 文字＋四欄位（P05）
│   │   ├── indexing_service.py    # 文字＋欄位合併成 Document、轉成向量（P06）
│   │   ├── retrieval_service.py   # 兩種查詢：語意 / 條件（含 30 天時間過濾）（P09）
│   │   └── ask_workflow.py    # LangGraph 流程圖：判斷 → 查詢 → 回答（P10、P11）
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── photo_repository.py    # ★ 全系統唯一寫 SQL 的模組（psycopg）（P03、P09）
│   ├── db/
│   │   ├── __init__.py
│   │   └── session.py         # psycopg 資料庫連線（P03）
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py          # 環境變數＋模型名稱、EMBEDDING_DIM、RECENT_DAYS=30、TOP_K=5 等常數（P02）
│   └── static/                # 【v4】極簡網頁介面（純 HTML＋原生 JS，沒有 __init__.py）
│       ├── upload.html        #   上傳照片頁：表單 → fetch POST /photos → 顯示理解結果（P14）
│       └── ask.html           #   問答頁：輸入框（中英皆可）→ fetch POST /ask → 顯示回答（P14）
├── db/
│   └── schema.sql             # 資料表 DDL（photo 表、pgvector、HNSW index）（P03）
├── scripts/
│   └── check_embedding_dim.py # 實測 bge-m3 向量維度（P08）
└── tests/
    ├── __init__.py
    ├── conftest.py            # 測試共用設定：指向測試庫＋每測清空 photo 表（P03 起；P05/P06 擴充假件安全網與 client fixture、P07 擴充表格小工具）
    ├── unit/                  # 【2026-08-19 起】單元測試：純函式，不碰資料庫
    │   ├── __init__.py
    │   └── test_photo_repository_unit.py  # to_vector_literal（P03）
    ├── integration/           # 【2026-08-19 起】整合測試：連 visual_memory_test 測試庫
    │   ├── __init__.py
    │   ├── test_photo_repository.py       # repository 五操作＋U4/U5 資料層（P03）
    │   └── test_photos_upload.py          # POST /photos 格式檢查＝Rule U1（P04）
    ├── fakes.py               # FakeVLM / FakeEmbeddings / FakeRouter / FakeAnswerLLM / FixedClock（P05、P06、P07、P10、P11）
    ├── test_indexing.py       # Document 合併順序固定（中英文）（P07）
    ├── test_upload_bilingual.py   # 英文照片描述與欄位原樣儲存（P07）
    ├── test_upload_feature.py     # 掛 docs/spec/features/上傳照片.feature（P07）
    ├── test_retrieval.py      # 兩條查詢＋30 天邊界＋ILIKE 大小寫（P09）
    ├── test_workflow_route.py # route 節點＋fallback＋英文提問（P10）
    ├── test_ask_endpoint.py   # POST /ask 基本行為＋英文回答（P11）
    ├── test_ask_feature.py    # 掛 docs/spec/features/自然語言詢問.feature（P12）
    └── test_error_paths.py    # 錯誤處理總表逐列驗證（P13）
```

> 過程中還會出現一個**暫時性**檔案 `tests/integration/test_upload_smoke.py`（P05 建立、P06 擴充、**P07 刪除**）。它不在最終結構裡。

**測試數量的累進**（每個 phase 的驗收都會叫你核對這個數字，對不上就代表漏做或多做）：

> 🔄 **2026-08-19 更新（dev-prompt `phase0819.md`）**：改採 TDD——pytest 測試自 **P03** 起建立（原為 P05 起），並分 `tests/unit/` 與 `tests/integration/` 兩個子目錄；P05 之後各檔的歸屬子目錄，等各該 phase 開工前更新計畫時再定。P03/P04 之後的累計數已依此順移 +19。
> 🔄 **2026-08-19 再更新（dev-prompt `phase0819-1.md`，P05/P06 開工前；階段I review 後 P05 smoke +1）**：P05／P06 兩列已依更新後計畫改定（TDD 單元測試計入、佔位測試改寫、conftest 假件安全網、review 後補「text 全空白也 422」），累計 **30／36**；**P07 起各列仍為舊制數字**，照慣例等各該 phase 開工前更新計畫時再重算。

| Phase | 新增測試 | `pytest -q` 累計 |
|---|---|---|
| P03【TDD 提前】 | `unit/test_photo_repository_unit.py` 2＋`integration/test_photo_repository.py` 10 | **12** |
| P04【TDD 提前】 | `integration/test_photos_upload.py` 7 | **19** |
| P05 | `unit/test_vlm_service_unit.py` 6＋`integration/test_upload_smoke.py` 5（另改寫 upload 兩個佔位測試） | **30** |
| P06 | `unit/test_indexing_service_unit.py` 4＋smoke 同檔 +2（英文斷言改 metadata 巢狀；review 後補 U4 護欄） | **36** |
| P07 | 刪掉 smoke 6，新增 feature 7＋indexing 3＋bilingual 1 | **30** |
| P08 | 0（不加需要真模型的測試） | **30** |
| P09 | `test_retrieval.py` 10 | **40** |
| P10 | `test_workflow_route.py` 5 | **45** |
| P11 | `test_ask_endpoint.py` 5 | **50** |
| P12 | `test_ask_feature.py` 7 | **57** |
| P13 | `test_error_paths.py` 11 | **68** |
| P14 | 0（網頁介面手動驗收，不寫自動化測試） | **68** |

---

## 5. 不准做的事（每個 phase 都適用）

以下取自 design.md §3「明確不做」與 §4.1 的分層裁剪原則，做了就是違規：

- ❌ 多使用者、帳號登入、`core/security.py`
- ❌ 保留或回傳原始照片檔（處理完即丟）
- ❌ 照片瀏覽、刪除、編輯——任何第三個功能
- ❌ 非同步處理、佇列、處理狀態欄位
- ❌ metadata 自由欄位／延伸 JSON（固定四欄位，多的直接丟）
- ❌ ORM 與 `models/`、`alembic/` migration（一張表、手寫 SQL，`schema.sql` 重建即可）
- ❌ `users/`、`messages/` 之類本專案沒有的資源目錄（分層 ≠ 建空殼）
- ❌ 多輪對話記憶、**前端框架**（React／Vue／jQuery／CSS 框架／npm／打包工具——網頁介面只准純 HTML＋原生 JS）、雲端部署
- ❌ 把模型換回雲端服務（本專案一律用本機 Ollama，零 API key）
- ❌ 檔案大小上限檢查（已釐清：無上限，刻意不寫）
- ❌ 條件查詢的跨語言翻譯對映（問 "receipts" 不會自動對到「收據」——design.md §8.3 明訂這是刻意接受的限制）
- ❌ 為了網頁介面新增任何後端端點（P14 只加 `app.mount(...)` 送靜態檔）
- ❌ 為那兩個網頁寫瀏覽器自動化測試（design.md §6：頁面驗收以手動操作為準）
- ❌ 修改 `docs/spec/` 或 `docs/design/` 底下任何檔案

另外：`docs/plan/` 裡**本路線圖（`unfinish/` 的 phase-00〜14）以外**的既有舊檔案（例如 `dev-prompts/phase0812.md`）是**另一個專案（FSE Chat Room）的殘留文件**，實作時不得讀取或引用；若還看到 `docs/requirments/` 之類的殘留資料夾，同樣一律忽略。

---

## 6. 完成後的專案狀態

依序完成 P01〜P14 後，你會有一個可以本機 demo 的 Multimodal RAG 系統（多模態＝同時處理圖片與文字），後端是**分層**的，前面還有一層極簡網頁：

- 上傳一張收據照片會得到 201 與結構化結果——不論照片上是中文還是英文，描述與欄位都用照片本身的語言。
- 問「有哪些在 Target 拍的收據？」會走條件查詢（`ILIKE` 比對，`target` 也找得到 `Target`）。
- 問「我最近買過什麼飲料？」或 "What drinks did I buy recently?" 會走語意查詢並套用 30 天過濾，跨語言召回靠多語 embedding。
- 回答一律由 LLM 依撈到的照片內容產生、**語言跟隨提問**、查無資料時不編造。
- 12 條 Gherkin Rule 全部有自動化測試把關（**68 個測試全綠**，2026-08-19 起含 P03/P04 的 TDD 測試），且全部測試不依賴任何外部服務（整合測試只用本機測試庫）。
- 不想打 `curl` 的時候，直接開 <http://localhost:8000/ui/upload.html> 與 <http://localhost:8000/ui/ask.html> 用瀏覽器操作——兩個純 HTML 檔，零框架、零打包工具、零新增端點。
