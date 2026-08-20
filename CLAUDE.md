# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**PersonalDocAI**（舊名 Visual Memory RAG——`docs/spec/` 規格區唯讀、`docs/plan/` 歸檔屬歷史紀錄，兩處仍沿用舊名不回改）：小型、可實際 demo 的 Multimodal RAG backend。使用者上傳照片，系統以 VLM 理解內容轉成文字與結構化 metadata，經 LangChain 產生 embedding 存入 PostgreSQL + pgvector；之後可用自然語言詢問，由 LangGraph workflow 依問題類型路由至 vector semantic search 或 metadata search，最後交給 LLM 產生回答。

**功能核心兩項：上傳照片、自然語言詢問**。2026-08-20 起產品負責人以 `docs/design/design1.md`（增量 canonical design）**正式改規格**，核准新增：存原圖＋縮圖（DB 只記路徑）、資料夾（`category`＝資料夾名稱、VLM 推薦＋人確認）、上傳確認彈窗、資料夾瀏覽——實作路線圖為 `docs/plan/unfinish/phase-00-增量總覽.md`（Phase 15〜26）。design1.md §1.1 明示推翻的舊禁令**僅四項**（不存原始檔、禁照片瀏覽、category 自由字串、網頁僅兩頁/不加端點）；**其餘禁令全部仍有效**（多使用者、刪除照片、非同步佇列、對話記憶、雲端儲存、前端框架等一律禁止）。

**現況：Phase 01〜14 全數完成（2026-08-19，v4 系統）；增量 Phase 15〜17 已完成（2026-08-20），Phase 18〜26 待做**——環境就緒（Python 3.12 venv、PostgreSQL@17 於 5433＋pgvector、Ollama gemma4＋bge-m3）、`app/` 分層骨架已建；`photo` 資料表（兩庫＋HNSW cosine 索引）、`db/session.py`、`repositories/photo_repository.py`（全系統唯一寫 SQL）皆完成；**`POST /photos` 全流程可用**：格式檢查（非 JPEG/PNG→415）→ `services/vlm_service.py` 看圖（正式路徑 `OllamaVLM`；看不懂／呼叫失敗／text 空白→422 什麼都不存）→ `services/indexing_service.py` 固定順序合併＋轉向量（`embed_query`）→ 一條 INSERT → `UploadResponse` 201。注入點在 `app/dependencies.py`（`get_vlm`／`get_embeddings`／`get_now`）。上傳功能已過**規格驗收**（pytest-bdd 直接掛 `上傳照片.feature`，7 條 Rule U1〜U7 全綠；規格檔唯讀）並完成**真模型煙霧**（`scripts/check_embedding_dim.py` 實測 bge-m3＝1024 維、中英同義句相似度 0.837 vs 無關句 0.377；gemma4 真看圖＋真 HTTP 上傳成功，正式庫已有真實照片資料）。**檢索層與路由已完成**（Phase 09〜10）：`photo_repository` 兩條查詢（條件查詢 `ILIKE`＋`unnest` ILIKE、語意查詢 pgvector `<=>` top-5，共用 `COALESCE(content_time, uploaded_at::date) >= 今天−30天` 時間過濾）、`services/retrieval_service.py` 的 `@chain` 自訂 retriever（DD-4：不用 PGVector store）、`services/ask_workflow.py` 的 LangGraph 圖（START→route→條件邊→retrieve_metadata／retrieve_vector→END；route 由 LLM 一次結構化輸出判查法＋抽條件、中英 few-shot、失敗一律 fallback 語意查詢；真模型路由煙霧中英各一已實測通過）。**詢問端點與規格驗收已完成**（Phase 11〜12）：`ask_workflow.py` 的 generate 節點（`ANSWER_PROMPT` 三條鐵律——只依檢索到的照片內容回答、查無不虛構、**回答語言跟隨提問語言**且照片內容原文不翻譯）＋`api/routers/ask.py` 的 **`POST /ask` 全流程可用**（`AskDeps` 注入 `get_router`／`get_answerer`／`get_embeddings`／`get_today`，`get_today` 鏈到 `get_now`；`search_mode` 與 `retrieved_photo_ids` 直取流程 state、不經 AI，靠 `config.SEARCH_MODE_LABELS` 轉全名；`AskRequest.question` 以 `min_length=1` 讓缺漏／空字串走框架既有 422）。詢問已過**規格驗收**（pytest-bdd 直接掛 `自然語言詢問.feature`，5 條 Rule Q1〜Q5 共 7 例全綠——至此 **12 條 Rule 全數綠燈**）並完成**真模型煙霧**（gemma4：中文問正確引用照片內容且走 metadata search、英文問走 vector semantic search 且回答為英文句、照片內容「可樂」原文保留；回應鍵恰為 answer／retrieved_photo_ids／search_mode）。`tests/conftest.py` 的 `wire_fake_ai` 安全網已涵蓋**全部五個**注入點（`OLLAMA_BASE_URL` 指死埠全量仍 67 passed，實證零 Ollama 依賴）；`search_by_vector` 的 30 天過濾經變異測試證實由 SQL 生效。**錯誤路徑收尾與網頁介面也已完成**（Phase 13〜14）：design.md 錯誤處理總表七列各有測試把關（`integration/test_error_paths.py`：415／422 不寫入、大檔無上限路徑、缺漏空字串 422、路由失敗 200 fallback、查無中英雙語、embedding／DB 失敗 500 不吞錯），「明確不做」清單以檢查腳本逐項核對通過（驗收當時端點恰 3、無寫檔、無 user 欄位、無佇列、metadata 恰四欄、全本地、SQL 只在 repository、無全域例外捕捉；**2026-08-20 依使用者指示追加第 4 個端點 `GET /` → 轉址 `/ui/upload.html`**，歸檔的 phase-13/14 計畫中「端點恰 3」的檢查數字以此為準）；`app/static/upload.html`＋`ask.html` 兩個純 HTML 頁掛在 `/ui`（`main.py` 一行 `app.mount`，**零框架、零打包、零新增端點、零新增自動化測試**），瀏覽器實操驗收（上傳 201／415、中英問答、查無、雙向互連、console 乾淨）與真模型中英雙語煙霧（真照片上傳＋條件／語意／模糊五種詢問）全數通過。**增量 Phase 15〜17 成果（2026-08-20，全程 TDD、對外行為零改變——端點仍 4 個、回應不變）**：`folder` 資料表（六筆預設種子「未分類(收件箱)／收據／飲食／風景／文件／其他」，**插入順序即 id 1〜6**，三處同步定義：`db/schema.sql`、`db/migrate_folders.sql`、`DEFAULT_FOLDERS`；partial unique index `folder_one_inbox` 保證全系統至多一個收件箱）＋`photo` 新增 `folder_id`（NOT NULL FK；`insert_photo` 以 SQL 內 COALESCE＋子查詢依 `category` 不分大小寫自動歸夾、對不到掛「未分類」，**`category` 值本身不改寫**——改寫是 Phase 20/21 的事）與 `original_path`／`thumbnail_path`／`content_type` 三欄（目前恆 NULL，Phase 19 才寫檔回填）；**正式庫已遷移**（可重跑的 `db/migrate_folders.sql`，2 列真照片歸「收據」、路徑 NULL；遷移前備份 `~/PersonalDocAI-backup-遷移前.sql` 保留中）；**資料夾資料層五函式**（`list_folders`／`get_folder`／`find_folder_by_name`(lower() 不分大小寫)／`create_folder`(不自檢重名，409 屬 Phase 21 router)／`list_photos_in_folder`(新的在前、不含 embedding)，回傳鍵名即之後 Pydantic 模型的契約）；**檔案儲存層 `services/storage_service.py`**（原圖位元組原樣落地 `data/photos/{id}.jpg|png`、Pillow 縮圖長邊≤512 等比不放大落地 `data/thumbs/`、DB 只存 `data/` 開頭相對路徑、`absolute_path` 依 `config.DATA_DIR` 呼叫當下換算、`remove_if_exists` 容錯清理；`data/` 已入 `.gitignore`、`Pillow>=10` 入 requirements——**尚無人呼叫**，Phase 19 才接上傳流程）。已完成 phase 計畫（01〜17）歸檔於 `docs/plan/finish/`，增量路線圖與待做計畫（phase-00-增量總覽、18〜26）在 `docs/plan/unfinish/`，進度與紀錄見 `docs/plan/todo/`、`docs/plan/report/`。pytest 測試自 Phase 03 起以 TDD 建立：`tests/unit/`＋`tests/integration/`（目前 **103** 個全綠），`tests/conftest.py` 自動把 `DATABASE_URL` 切到 `PersonalDocAI_test`，並以**三道 autouse 安全網**擋掉危險預設：`reset_tables`（每測清空 `photo`＋`folder` 兩表並重播六筆種子，folder id 保證 1〜6；**絕不清正式庫**）、`wire_fake_ai`（AI／時鐘全部換假件；**pytest 絕不呼叫真 Ollama**——本機 Ollama 常駐，忘記覆寫會誤觸真模型推論；真模型只做手動煙霧，不進驗收與 CI）、`isolated_data_dir`（`config.DATA_DIR` 指到 tmp_path；**pytest 絕不寫專案 `data/`**）。假件與真圖工具（`make_png_bytes`／`make_jpeg_bytes`——Pillow 會真的解碼，假位元組會炸 `UnidentifiedImageError`）在 `tests/fakes.py`。

## 指令

```bash
# 每次開工（每個新終端機視窗都要）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 安裝／更新依賴（本專案用 uv 管理套件）
uv pip install -r requirements.txt

# 啟動開發伺服器（http://localhost:8000，API 文件在 /docs）
uvicorn app.main:app --reload --port 8000

# 跑測試（Phase 03 起；在專案根目錄執行，會自動連 PersonalDocAI_test 並每測清空）
pytest -q

# 只跑兩份規格檔（12 條 Rule、14 個例子）
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v

# 手動煙霧測試（需要 Ollama 真的在跑；真模型不寫自動化測試、不進驗收與 CI）
python scripts/check_embedding_dim.py

# 資料庫建表（schema.sql 開頭是 DROP TABLE IF EXISTS，重跑＝清空重建；含 folder 表＋六筆種子）
psql -d PersonalDocAI_test -f db/schema.sql   # 測試庫（可隨意重建）
# ⚠️ 正式庫有真實照片，「不要」用 schema.sql 重建；結構改版一律走可重跑的遷移腳本
psql -d PersonalDocAI -f db/migrate_folders.sql   # 正式庫遷移（idempotent；2026-08-20 已執行）

# 資料庫（本專案的 @17 在 5433；互動 shell 已由 ~/.zshrc 的 PGPORT=5433 設好預設）
psql -d PersonalDocAI       # 正式庫
psql -d PersonalDocAI_test  # 測試庫
```

## 規格驅動工作流程（Spec-driven）

本專案採四階段規格流程，prompt 定義在 `docs/spec/prompts/`：

1. **Formulation**（`1.formulation.md` + `formulation-rules.md`）：從原始規格文本萃取資料模型（DBML → `docs/spec/erm.dbml`）與功能模型（Gherkin → `docs/spec/features/*.feature`）。核心原則是「無腦補」：規格沒寫的欄位、規則、行為一律不加。
2. **Discovery**（`2.discovery.md`）：掃描規格找歧義，產出釐清項目到 `docs/spec/.clarify/`。
3. **Clarify**（`3.clarify.md`）：互動式逐題釐清，答案即時整合回規格檔，已解決項目歸檔至 `docs/spec/.clarify/resolved/`。
4. **Design**（`4.design_prompt.md`）：產出 canonical design 到 `docs/design/design.md`。

**目前進度**：四階段全數完成——18 項釐清 Resolved（見 `.clarify/overview.md`）、12 條 Rule 全數附 Example、無 #TODO；`docs/design/design.md`（**v4**）為 canonical design：分層架構（api/routers→services→repositories）、Ollama 本地模型（gemma4＋bge-m3）、中英雙語、side project 原則、Phase 14 極簡網頁介面。v4 實作已全數完成（phase-01〜14 歸檔於 `docs/plan/finish/`）。**2026-08-20 起增量另有 canonical design `docs/design/design1.md`**（資料夾＝category、原圖瀏覽；詢問流程不變）：design1.md 列明的推翻項以 design1.md 為準，未提及的行為仍以 design.md v4 與 Clarify 為準；增量實作進度見 `docs/plan/unfinish/phase-00-增量總覽.md` §5（P15〜17 已完成）。

### Source of Truth 優先序（衝突時依序採用）

1. `docs/spec/.clarify/resolved/` 的解決記錄（含被否決的選項，**不得重問、不得推翻**）
2. `docs/spec/erm.dbml` 與 `docs/spec/features/*.feature`（clarify 後的最新規格模型）
3. `docs/spec/draft/design-draft.md`（原始規格草案，較粗略處以上兩者為準）

## 不可違反的已定案決策

技術棧（spec-mandated）：FastAPI、PostgreSQL + pgvector、VLM、LangChain（Document/embedding/vector store）、LangGraph（retrieval workflow 與路由）。

Clarify 階段定案（完整清單與被否決方案見 `.clarify/resolved/` 與 `erm.dbml` 的 Note）：

> ⚠️ **2026-08-20 增量修正**（design1.md §1.1，產品負責人明示改規格）：下列定案中**四項被正式推翻**——「不儲存原始照片檔」→ 改存原圖＋縮圖（檔案系統，DB 記相對路徑）；「禁照片瀏覽」→ 新增資料夾瀏覽（縮圖牆）；「category 由 VLM 自由填」→ category 必須是資料夾清單中的名稱（VLM 只推薦、人確認）；「網頁僅兩頁／不新增端點」→ 新增資料夾／歸類／讀圖端點與瀏覽頁。**其餘定案（含本清單其他各條與所有被否決方案）仍然有效、不得重開。**

- **單一使用者系統**：不建 User 實體，照片不分擁有者。
- **不儲存原始照片檔**（⚠️ 已被 design1.md 推翻，見上）：只存 VLM 轉出的文字（`text`），處理完即捨棄原始檔，任何路徑不得保留或回傳。
- metadata **固定四欄位**：`category`、`location`、`items`、`content_time`；清單外資訊一律捨棄（自由 JSON 方案已被否決）。
- **上傳為同步處理**：完成即代表文字、metadata、向量皆已儲存；無處理狀態欄位。
- VLM 無法理解照片 → 上傳失敗、不儲存任何資料（不存在 `text` 為空的記錄）。
- 上傳檔案須為常見圖片格式（JPEG、PNG 等），不設大小上限；成功回應含照片識別碼＋文字描述＋metadata 四欄位。
- 詢問路由**由 LLM 判斷**（帶明確過濾條件→metadata search；語意描述型→vector search）；無法判斷時**預設 vector search**（關鍵字規則路由已被否決）。
- **「最近」= 詢問當下回推 30 天**；時間過濾以 `content_time` 優先，為空改用 `uploaded_at`。
- 檢索無結果仍交 LLM 產生「查無相關照片」回覆，**不得編造照片內容**。
- embedding 由 `text` ＋四個 metadata 欄位合併內容產生（僅文字方案已被否決）。
- 術語：一律稱「照片」（不稱「圖片」，「圖片格式」指檔案格式時例外）；中文稱「向量／embedding 向量」，欄位名維持 `embedding`。

## 測試設計前提

`.feature` 的 Example 把 VLM 理解結果寫在 When 步驟、以資料表驗收，隱含 **VLM、LLM 路由、LLM 回答生成、時鐘（「現在時間」）都必須可注入替換（stub）**。實作架構必須保留這些注入點，兩份 `.feature` 即驗收規格。

## 重要陷阱

- **`docs/plan/` 新舊混雜，要分清楚**：`docs/plan/unfinish/`（本專案未完成的 phase 計畫）、`finish/`（已完成的 phase 計畫＋phase-00 總覽）、`todo/`、`report/`、`dev-prompts/phase0818.md`／`phase0819*.md`／`phase1819-3.md` 是**本專案的文件**；`dev-prompts/phase0808〜0812.md` 等舊檔是另一個專案（18652FSE Chat Room）的殘留（socket.io、JWT、前端約束皆與本專案無關），**禁止引用作為本專案依據**。若出現 `docs/requirments/` 或 `docs/design/draft.md` 亦同（舊複本以 `docs/spec/draft/design-draft.md` 為準）。
- **本機 PostgreSQL 有兩套**：既有 `postgresql@14`（5432 埠）內有**其他專案的資料庫（wanderlove、fse_chat_room），絕不可停用或修改**；本專案用 `postgresql@17` 跑在 **5433 埠**（`DATABASE_URL` 一律帶 `:5433`，互動 shell 由 `PGPORT=5433` 讓 psql 預設連對）。
- `erm.dbml` 的型別受規格型別清單限制（如 `items` 標成 string、`embedding` 標成 float）；落地為實際 PostgreSQL 型別屬 design decision，需在 design 文件裁決並說明對應，**不要回頭改 `erm.dbml`**。
- 本 repo 自 2026-08-19 起**已是 git repository**（分支 `master`；初始 commit 即 Phase 01〜04 完成狀態）。`.venv/`、`.env`、`__pycache__/`、`.pytest_cache/`、`data/`（照片與縮圖，2026-08-20 起）不入版控——**禁止把二進位照片 commit 進 repo**。

## 語言與其他慣例

- 文件與規格一律使用**繁體中文＋台灣常用技術用語**；Gherkin step 以中文描述、DataTable 欄位名用英文、Given/When/Then 用英文關鍵字。
- 使用者層級的 `~/CLAUDE.md` 另有 MCP 使用規則（查最新文件用 Context7、研究類 MCP 只查不改碼、結論附來源連結），同樣適用於本專案。
