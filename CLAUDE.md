# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**personalDocAI（Visual Memory RAG）**：小型、可實際 demo 的 Multimodal RAG backend。使用者上傳照片，系統以 VLM 理解內容轉成文字與結構化 metadata，經 LangChain 產生 embedding 存入 PostgreSQL + pgvector；之後可用自然語言詢問，由 LangGraph workflow 依問題類型路由至 vector semantic search 或 metadata search，最後交給 LLM 產生回答。

**功能僅兩項：上傳照片、自然語言詢問。不得新增任何其他能力**（多使用者、照片瀏覽/刪除、原始檔儲存、非同步佇列、對話記憶、前端 UI 等一律禁止）。

**現況：Phase 01〜06 已完成**（2026-08-19）——環境就緒（Python 3.12 venv、PostgreSQL@17 於 5433＋pgvector、Ollama gemma4＋bge-m3）、`app/` 分層骨架已建；`photo` 資料表（兩庫＋HNSW cosine 索引）、`db/session.py`、`repositories/photo_repository.py`（全系統唯一寫 SQL）皆完成；**`POST /photos` 全流程可用**：格式檢查（非 JPEG/PNG→415）→ `services/vlm_service.py` 看圖（正式路徑 `OllamaVLM`；看不懂／呼叫失敗／text 空白→422 什麼都不存）→ `services/indexing_service.py` 固定順序合併＋轉向量（`embed_query`）→ 一條 INSERT → `UploadResponse` 201。注入點在 `app/dependencies.py`（`get_vlm`／`get_embeddings`／`get_now`）。實作依 `docs/plan/unfinish/` 的 phase 順序進行（已完成的 phase 計畫歸檔至 `docs/plan/finish/`），進度與紀錄見 `docs/plan/todo/`、`docs/plan/report/`。pytest 測試自 Phase 03 起以 TDD 建立：`tests/unit/`＋`tests/integration/`（目前 36 個全綠），`tests/conftest.py` 自動把 `DATABASE_URL` 切到 `visual_memory_test`、每測清空 `photo` 表，並以 autouse `wire_fake_ai` 把 AI／時鐘預設換成假件（假件在 `tests/fakes.py`；**pytest 絕不呼叫真 Ollama**——本機 Ollama 常駐，忘記覆寫會誤觸真模型推論）。

## 指令

```bash
# 每次開工（每個新終端機視窗都要）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 安裝／更新依賴（本專案用 uv 管理套件）
uv pip install -r requirements.txt

# 啟動開發伺服器（http://localhost:8000，API 文件在 /docs）
uvicorn app.main:app --reload --port 8000

# 跑測試（Phase 03 起；在專案根目錄執行，會自動連 visual_memory_test 並每測清空）
pytest -q

# 手動煙霧測試（需要 Ollama 真的在跑；真模型不寫自動化測試、不進驗收與 CI）
python scripts/check_embedding_dim.py

# 資料庫（本專案的 @17 在 5433；互動 shell 已由 ~/.zshrc 的 PGPORT=5433 設好預設）
psql -d visual_memory       # 正式庫
psql -d visual_memory_test  # 測試庫
```

## 規格驅動工作流程（Spec-driven）

本專案採四階段規格流程，prompt 定義在 `docs/spec/prompts/`：

1. **Formulation**（`1.formulation.md` + `formulation-rules.md`）：從原始規格文本萃取資料模型（DBML → `docs/spec/erm.dbml`）與功能模型（Gherkin → `docs/spec/features/*.feature`）。核心原則是「無腦補」：規格沒寫的欄位、規則、行為一律不加。
2. **Discovery**（`2.discovery.md`）：掃描規格找歧義，產出釐清項目到 `docs/spec/.clarify/`。
3. **Clarify**（`3.clarify.md`）：互動式逐題釐清，答案即時整合回規格檔，已解決項目歸檔至 `docs/spec/.clarify/resolved/`。
4. **Design**（`4.design_prompt.md`）：產出 canonical design 到 `docs/design/design.md`。

**目前進度**：四階段全數完成——18 項釐清 Resolved（見 `.clarify/overview.md`）、12 條 Rule 全數附 Example、無 #TODO；`docs/design/design.md`（**v4**）為 canonical design：分層架構（api/routers→services→repositories）、Ollama 本地模型（gemma4＋bge-m3）、中英雙語、side project 原則、Phase 14 極簡網頁介面。實作路線圖：`docs/plan/unfinish/`（phase-00 總覽＋未完成的 phase-07〜14）；已完成的 phase-01〜06 計畫歸檔於 `docs/plan/finish/`。

### Source of Truth 優先序（衝突時依序採用）

1. `docs/spec/.clarify/resolved/` 的解決記錄（含被否決的選項，**不得重問、不得推翻**）
2. `docs/spec/erm.dbml` 與 `docs/spec/features/*.feature`（clarify 後的最新規格模型）
3. `docs/spec/draft/design-draft.md`（原始規格草案，較粗略處以上兩者為準）

## 不可違反的已定案決策

技術棧（spec-mandated）：FastAPI、PostgreSQL + pgvector、VLM、LangChain（Document/embedding/vector store）、LangGraph（retrieval workflow 與路由）。

Clarify 階段定案（完整清單與被否決方案見 `.clarify/resolved/` 與 `erm.dbml` 的 Note）：

- **單一使用者系統**：不建 User 實體，照片不分擁有者。
- **不儲存原始照片檔**：只存 VLM 轉出的文字（`text`），處理完即捨棄原始檔，任何路徑不得保留或回傳。
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

- **`docs/plan/` 新舊混雜，要分清楚**：`docs/plan/unfinish/`（本專案未完成的 phase 計畫＋phase-00 總覽）、`finish/`（已完成的 phase 計畫）、`todo/`、`report/`、`dev-prompts/phase0818.md`／`phase0819*.md` 是**本專案的文件**；`dev-prompts/phase0808〜0812.md` 等舊檔是另一個專案（18652FSE Chat Room）的殘留（socket.io、JWT、前端約束皆與本專案無關），**禁止引用作為本專案依據**。若出現 `docs/requirments/` 或 `docs/design/draft.md` 亦同（舊複本以 `docs/spec/draft/design-draft.md` 為準）。
- **本機 PostgreSQL 有兩套**：既有 `postgresql@14`（5432 埠）內有**其他專案的資料庫（wanderlove、fse_chat_room），絕不可停用或修改**；本專案用 `postgresql@17` 跑在 **5433 埠**（`DATABASE_URL` 一律帶 `:5433`，互動 shell 由 `PGPORT=5433` 讓 psql 預設連對）。
- `erm.dbml` 的型別受規格型別清單限制（如 `items` 標成 string、`embedding` 標成 float）；落地為實際 PostgreSQL 型別屬 design decision，需在 design 文件裁決並說明對應，**不要回頭改 `erm.dbml`**。
- 本 repo 自 2026-08-19 起**已是 git repository**（分支 `master`；初始 commit 即 Phase 01〜04 完成狀態）。`.venv/`、`.env`、`__pycache__/`、`.pytest_cache/` 不入版控。

## 語言與其他慣例

- 文件與規格一律使用**繁體中文＋台灣常用技術用語**；Gherkin step 以中文描述、DataTable 欄位名用英文、Given/When/Then 用英文關鍵字。
- 使用者層級的 `~/CLAUDE.md` 另有 MCP 使用規則（查最新文件用 Context7、研究類 MCP 只查不改碼、結論附來源連結），同樣適用於本專案。
