# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**PersonalDocAI**（舊名 Visual Memory RAG——`docs/spec/` 規格區唯讀（唯一例外：`上傳照片.feature` 經產品負責人核准、2026-08-21 依 design1.md 改版為 10 條 Rule）、`docs/plan/` 歸檔屬歷史紀錄，兩處仍沿用舊名不回改）：小型、可實際 demo 的 Multimodal RAG backend。使用者上傳照片，系統以 VLM 理解內容轉成文字與結構化 metadata，經 LangChain 產生 embedding 存入 PostgreSQL + pgvector；之後可用自然語言詢問，由 LangGraph workflow 依問題類型路由至 vector semantic search 或 metadata search，最後交給 LLM 產生回答。

**功能核心兩項：上傳照片、自然語言詢問**。2026-08-20 起產品負責人以 `docs/design/design1.md`（增量 canonical design）**正式改規格**，核准新增：存原圖＋縮圖（DB 只記路徑）、資料夾（`category`＝資料夾名稱、VLM 推薦＋人確認）、上傳確認彈窗、資料夾瀏覽——實作路線圖為 `docs/plan/unfinish/phase-00-增量總覽.md`（Phase 15〜26）。design1.md §1.1 明示推翻的舊禁令**僅四項**（不存原始檔、禁照片瀏覽、category 自由字串、網頁僅兩頁/不加端點）；**其餘禁令全部仍有效**（多使用者、刪除照片、非同步佇列、對話記憶、雲端儲存、前端框架等一律禁止）。

**現況：Phase 01〜14 全數完成（2026-08-19，v4 系統）；增量 Phase 15〜26 全數完成（2026-08-21）——design1.md 描述的「個人視覺檔案櫃」已全部落地；增量二 Phase 27（`docs/design/design2.md`：待決定區與定案鎖定）已完成（2026-08-21）；增量三（`docs/design/design3.md`：無線鏡頭、實體、待辦）**Phase 28〜37 全數實作完成**（28〜33 於 2026-08-21 完成並已 commit——28〜30 在 `e29f5a1`、31〜33 在 `0cabb45`；34〜37 於 2026-08-22 完成、依產品負責人指示**未 commit**；phase-36 的真機（iPhone）驗收待產品負責人手動）**——環境就緒（Python 3.12 venv、PostgreSQL@17 於 5433＋pgvector、Ollama gemma4＋bge-m3）、`app/` 分層骨架已建；`photo` 資料表（兩庫＋HNSW cosine 索引）、`db/session.py`、`repositories/photo_repository.py`（全系統唯一寫 SQL）皆完成；**`POST /photos` 全流程可用**：格式檢查（非 JPEG/PNG→415）→ `services/vlm_service.py` 看圖（正式路徑 `OllamaVLM`；看不懂／呼叫失敗／text 空白→422 什麼都不存）→ `services/indexing_service.py` 固定順序合併＋轉向量（`embed_query`）→ 一條 INSERT → `UploadResponse` 201。注入點在 `app/dependencies.py`（`get_vlm`／`get_embeddings`／`get_now`）。上傳功能已過**規格驗收**（pytest-bdd 直接掛 `上傳照片.feature`，7 條 Rule U1〜U7 全綠；規格檔唯讀）並完成**真模型煙霧**（`scripts/check_embedding_dim.py` 實測 bge-m3＝1024 維、中英同義句相似度 0.837 vs 無關句 0.377；gemma4 真看圖＋真 HTTP 上傳成功，正式庫已有真實照片資料）。**檢索層與路由已完成**（Phase 09〜10）：`photo_repository` 兩條查詢（條件查詢 `ILIKE`＋`unnest` ILIKE、語意查詢 pgvector `<=>` top-5，共用 `COALESCE(content_time, uploaded_at::date) >= 今天−30天` 時間過濾）、`services/retrieval_service.py` 的 `@chain` 自訂 retriever（DD-4：不用 PGVector store）、`services/ask_workflow.py` 的 LangGraph 圖（START→route→條件邊→retrieve_metadata／retrieve_vector→END；route 由 LLM 一次結構化輸出判查法＋抽條件、中英 few-shot、失敗一律 fallback 語意查詢；真模型路由煙霧中英各一已實測通過）。**詢問端點與規格驗收已完成**（Phase 11〜12）：`ask_workflow.py` 的 generate 節點（`ANSWER_PROMPT` 三條鐵律——只依檢索到的照片內容回答、查無不虛構、**回答語言跟隨提問語言**且照片內容原文不翻譯）＋`api/routers/ask.py` 的 **`POST /ask` 全流程可用**（`AskDeps` 注入 `get_router`／`get_answerer`／`get_embeddings`／`get_today`，`get_today` 鏈到 `get_now`；`search_mode` 與 `retrieved_photo_ids` 直取流程 state、不經 AI，靠 `config.SEARCH_MODE_LABELS` 轉全名；`AskRequest.question` 以 `min_length=1` 讓缺漏／空字串走框架既有 422）。詢問已過**規格驗收**（pytest-bdd 直接掛 `自然語言詢問.feature`，5 條 Rule Q1〜Q5 共 7 例全綠——至此 **12 條 Rule 全數綠燈**）並完成**真模型煙霧**（gemma4：中文問正確引用照片內容且走 metadata search、英文問走 vector semantic search 且回答為英文句、照片內容「可樂」原文保留；回應鍵恰為 answer／retrieved_photo_ids／search_mode）。`tests/conftest.py` 的 `wire_fake_ai` 安全網已涵蓋**全部五個**注入點（`OLLAMA_BASE_URL` 指死埠全量仍 67 passed，實證零 Ollama 依賴）；`search_by_vector` 的 30 天過濾經變異測試證實由 SQL 生效。**錯誤路徑收尾與網頁介面也已完成**（Phase 13〜14）：design.md 錯誤處理總表七列各有測試把關（`integration/test_error_paths.py`：415／422 不寫入、大檔無上限路徑、缺漏空字串 422、路由失敗 200 fallback、查無中英雙語、embedding／DB 失敗 500 不吞錯），「明確不做」清單以檢查腳本逐項核對通過（驗收當時端點恰 3、無寫檔、無 user 欄位、無佇列、metadata 恰四欄、全本地、SQL 只在 repository、無全域例外捕捉；**2026-08-20 依使用者指示追加第 4 個端點 `GET /` → 轉址 `/ui/upload.html`**，歸檔的 phase-13/14 計畫中「端點恰 3」的檢查數字以此為準）；`app/static/upload.html`＋`ask.html` 兩個純 HTML 頁掛在 `/ui`（`main.py` 一行 `app.mount`，**零框架、零打包、零新增端點、零新增自動化測試**），瀏覽器實操驗收（上傳 201／415、中英問答、查無、雙向互連、console 乾淨）與真模型中英雙語煙霧（真照片上傳＋條件／語意／模糊五種詢問）全數通過。**增量 Phase 15〜17 成果（2026-08-20，全程 TDD、對外行為零改變——端點仍 4 個、回應不變）**：`folder` 資料表（六筆預設種子「未分類(收件箱)／收據／飲食／風景／文件／其他」，**插入順序即 id 1〜6**，三處同步定義：`db/schema.sql`、`db/migrate_folders.sql`、`DEFAULT_FOLDERS`；partial unique index `folder_one_inbox` 保證全系統至多一個收件箱）＋`photo` 新增 `folder_id`（NOT NULL FK；`insert_photo` 以 SQL 內 COALESCE＋子查詢依 `category` 不分大小寫自動歸夾、對不到掛「未分類」，**`category` 值本身不改寫**——改寫是 Phase 20/21 的事）與 `original_path`／`thumbnail_path`／`content_type` 三欄（目前恆 NULL，Phase 19 才寫檔回填）；**正式庫已遷移**（可重跑的 `db/migrate_folders.sql`，2 列真照片歸「收據」、路徑 NULL；遷移前備份 `~/PersonalDocAI-backup-遷移前.sql` 保留中）；**資料夾資料層五函式**（`list_folders`／`get_folder`／`find_folder_by_name`(lower() 不分大小寫)／`create_folder`(不自檢重名，409 屬 Phase 21 router)／`list_photos_in_folder`(新的在前、不含 embedding)，回傳鍵名即之後 Pydantic 模型的契約）；**檔案儲存層 `services/storage_service.py`**（原圖位元組原樣落地 `data/photos/{id}.jpg|png`、Pillow 縮圖長邊≤512 等比不放大落地 `data/thumbs/`、DB 只存 `data/` 開頭相對路徑、`absolute_path` 依 `config.DATA_DIR` 呼叫當下換算、`remove_if_exists` 容錯清理；`data/` 已入 `.gitignore`、`Pillow>=10` 入 requirements——2026-08-21 起由 Phase 19 接上上傳流程）。**增量 Phase 18〜20 成果（2026-08-21，全程 TDD＋BDD；上傳行為正式改版、端點 4→6）**：`vlm_service` 的 `VLM_PROMPT` 常數改為 `build_vlm_prompt(folders)`（資料夾清單動態注入 prompt——「category 只能從清單選一個、禁止自創名稱、不確定填『未分類』」；category 一律照清單原文、不隨照片語言翻譯）＋純函式 `clamp_category(category, folders)`（去空白＋`casefold()` 大小寫不敏感，命中回**清單原文**、否則「未分類」），`VLMClient`／`OllamaVLM`／`FakeVLM` 的 `understand()` 皆收 `folders` 參數（仍只有一次看圖呼叫、無第二模型）。上傳流程改為 **INSERT→存原圖→產縮圖→UPDATE 回寫路徑**（檔名要用 id 所以 INSERT 必先行；任何一步失敗＝`remove_if_exists`×2＋`delete_photo` 清乾淨再 re-raise 回 500 不吞錯；這兩個 repository 函式只供失敗清理、無刪除端點），新增 `GET /photos/{id}/thumbnail`／`/image` 兩端點（沒這列／路徑 NULL（遷移舊照片，前端占位）／磁碟檔案不在 → 一律 404；都在 → `FileResponse`＋`media_type`）。**上傳一律先進「未分類」**：clamp 後的建議只出現在回應、不落庫（`suggested_folder` 保證是 `folders` 裡的一筆）；合併與向量用「未分類」（歸類後由 Phase 21 的 PATCH 重算）；201 回應新增 `folder`／`suggested_folder`／`folders`／`thumbnail_url` 四欄位（`schemas/photo.py` 新增 `FolderOut`，只外送 id/name/description）——彈窗要的資料一次帶齊。**`上傳照片.feature` 已正式改版**（7→10 條 Rule、檔頭註明 2026-08-20 核准來源；`自然語言詢問.feature` 一字未動，Q1〜Q5 全程保綠）。「預期上傳成功」的測試自 Phase 19 起一律用 `make_png_bytes()`／`make_jpeg_bytes()`／`make_large_png_bytes()` 真圖（415／422／embedding 失敗路徑**刻意保留**假位元組，證明失敗路徑不解碼圖片）。真模型煙霧（2026-08-21 手動）：真收據 JPEG 經真 gemma4 上傳成功——英文 text／items 原文保留、content_time 讀出圖上日期、`suggested_folder`＝「收據」（真模型從注入清單挑中）、落庫「未分類」；原圖與縮圖落地 `data/`（SHA1 與上傳檔一致、縮圖長邊 512）、讀圖端點 200、舊照片（路徑 NULL）404——**正式庫現有 3 列（2 舊＋1 煙霧）**。**增量 Phase 21〜24 成果（2026-08-21；21／22 全程 TDD、23／24 純前端零新增測試——端點 6→9、網頁 2→3 頁）**：**`PATCH /photos/{id}/folder` 歸類端點**（`AssignFolderRequest` 用 `@model_validator(mode="after")` 做 folder_id／name「恰一」驗證＋name 去空白，違者 422；順序鐵律＝404（先照片後資料夾）／409（`find_folder_by_name` 擋重名）檢查 → 用新名稱 `build_document`＋`embed_document` → 自建這時才 `create_folder` → `update_photo_folder()` **一條 UPDATE** 同寫 folder_id＋category＋重算的 embedding（RETURNING）——**embedding 失敗＝500 且資料庫完全沒動、不留空資料夾**，靠排序不靠交易；歸類後語意查詢拿得到正確類別訊號，design1.md §7.3）。**`GET /folders`／`GET /folders/{id}` 瀏覽端點**（新檔 `schemas/folder.py` 三模型＋`api/routers/folders.py` **零 SQL**；前者直接回陣列含 photo_count（LEFT JOIN，空資料夾不消失），後者回 `{folder, photos}`、摘要恰四鍵（id/thumbnail_url/text/uploaded_at）新的在前，`thumbnail_url` 由端點換算成 `/photos/{id}/thumbnail` 網址——**不洩硬碟路徑**、舊資料 NULL→null 前端占位；不做「列出全部照片」端點、不做分頁）。**前端三頁**：`upload.html` 201 後開三選項 modal（採用建議／改選現有／自建新資料夾；×／Esc＝不呼叫 API 留「未分類」）、新增 `browse.html`（資料夾卡片→縮圖牆→點照片以 `primaryVerb:"維持"` 開同一彈窗再歸類；`?folder=N` 網址切畫面所以上一頁／書籤免費；無縮圖畫灰底「無縮圖」占位）、**彈窗程式碼全站唯一一份 `static/folder_modal.js`**（fm 前綴隔離全域、僅靠 onAssigned/onClosed callback 對外；**禁用 alert/confirm/prompt**，錯誤一律寫進彈窗內 `#fm-error`；動態內容一律 textContent）、三頁導覽互連（`ask.html` 僅 nav 一處改動、行為零變）。Playwright MCP 瀏覽器實操驗收（P23 十三項＋P24 十九項）全數通過：三選項各實走、409/422 彈窗內紅字、×/Esc 留未分類、舊照片占位圖、上一頁／重新整理、上傳頁共用檔回歸；正式庫實測軌跡（照片 7：收據→飲食→旅遊）。**增量 Phase 25〜26 成果（2026-08-21）**：新測試檔 `tests/integration/test_folder_error_paths.py`（9 顆）把 design1.md §12 錯誤表的九個 ★ 缺口釘死（失敗不建資料夾、清單外建議→未分類、重名大小寫 409 不覆蓋、原圖被刪讀原圖 404、PATCH embedding 失敗雙路徑資料庫零變動不留空資料夾、無刪除端點掃碼）——**首跑 0 紅 9 綠**、零產品碼修改；`OLLAMA_BASE_URL` 指死埠全量同顆數（零外部依賴實證）；「明確不做」最終版與正式庫四查詢全過。**Phase 26 美化**：新增 `app/static/style.css`＝全站唯一樣式來源（design tokens：紙白底＋牛皮紙次底＋深琥珀單一強調色 #7c5200、Avenir Next/PingFang 標籤感 display、五級字級六級間距、唯彈窗有陰影；檔頭記禁止清單＋參考來源 immich／photoprism 與選色理由；簽名元素＝資料夾卡片的牛皮紙索引 tab），三頁刪光頁內 `<style>` 改共用（site-header＋aria-current 導覽、panel/status/kv 卡片語言、innerHTML 一律過 `esc()`、屬性不插值），`folder_modal.js` 刪 `FOLDER_MODAL_CSS`＋加焦點管理／`body.fm-open` 鎖捲動／點暗色區關閉（`fmAssign` 等四函式零改動）；Playwright 前後 6＋6 張截圖對比與 17 項實操全過、console 僅預期日誌。已完成 phase 計畫（01〜26 含 phase-00-增量總覽）與 phase-27 歸檔於 `docs/plan/finish/`；增量三計畫（phase-00-增量三總覽＋phase-28〜37，28〜30 已打勾完成）在 `docs/plan/unfinish/`，進度與紀錄見 `docs/plan/todo/`、`docs/plan/report/`。**增量二 Phase 27 成果（2026-08-21，design2.md「待決定區與定案鎖定」，產品負責人對話拍板——推翻 design1 的「關掉彈窗／之後可再歸類／瀏覽頁可改資料夾」三項，其餘不動）**：上傳彈窗改**強制決定**（無 ×／Esc／點外，四個明確出口：採用建議（建議＝未分類時不顯示①）／改選（下拉排除收件箱）／自建／**稍後再說**＝照片留待決定、不打 API）；**定案不可逆（後端擋）**——`PATCH /photos/{id}/folder` 只接受還在收件箱的照片（已定案 **409**「照片已定案，不可再變更資料夾」；目標是收件箱 **422**「不能歸檔到收件箱」），無任何後悔藥；瀏覽頁分「**待決定（N）｜資料夾**」兩個 tab（預設待決定；`?tab=folders`／`?folder=N` 網址直達）——「未分類」不再以卡片出現、待決定 tab 是唯一的第二歸類入口（彈窗無①）、資料夾牆**純瀏覽**（photo-static div、點不動）。資料模型與端點數（9）零變動；+3 tests（`test_assign_folder.py` 11 顆）。**增量三 Phase 28〜30 成果（2026-08-21，design3.md 前半；全程 TDD＋BDD，152→207 tests、端點 9→12）**：**Phase 28 PDF 入庫**（`ALLOWED_CONTENT_TYPES` 加 `application/pdf`；新檔 `services/pdf_service.py`＝全系統唯一碰 pypdfium2 的地方，`render_pages()` 逐頁渲染 PNG、壞檔／零頁丟 `PdfUnreadableError`→422 什麼都不存；router 抽出 `_ingest_image()`（單圖行為一字不變）＋`_ingest_pdf()` 逐頁走同一流程——每頁存成 PNG 所以讀圖端點零改動、只吞單頁 422 記入 `skipped_pages`、全頁失敗 422、部分成功 201 `PdfUploadResponse{pages, created, skipped_pages}`（`response_model` Union）；`上傳照片.feature` 依 design3.md D7 核准追加第 11 條 Rule（PDF 一頁一張），前端 accept 加 PDF、彈窗只為第一頁開；測試工具 `make_pdf_bytes()` 用 Pillow 原生 PDF 輸出）。**Phase 29 資料層**（`db/migrate_design3.sql` 一次建四表且可重跑——`entity`（name UNIQUE）／`photo_entity`（PK(photo_id,entity_id)、ON DELETE CASCADE）／`task`（photo_id UNIQUE＝每張照片至多一筆）／`folder_correction`（P35 才有程式用）；**正式庫已遷移**（備份 `~/PersonalDocAI-backup-增量三前.sql`、跑兩次證冪等、既有資料原封不動）；entity 六函式鏡射 folder 系列；`reset_folders_and_photos` TRUNCATE 明列 entity／folder_correction（CASCADE 只會連到指著被清表的 photo_entity／task）、`clear_photos` 因新外鍵補 CASCADE）。**Phase 30 實體建議與釘選**（`PhotoUnderstanding` 6→9 欄——entity／task_title／task_due 皆為**建議**、人確認才落庫；`build_vlm_prompt(folders, entities)` 同輪注入實體清單與待辦規則、仍只一次看圖呼叫；`clamp_entity()` 清單外回 None（實體無「未分類」保底）；上傳回應加 `suggested_entity`／`entities`／`suggested_task`；新端點 `GET /entities`、`POST /photos/{id}/entities`（釘選：404→409 重名／重複釘→422 恰一，檢查全過才寫、**不重算 embedding**——實體走連結表不進向量）、`POST /photos/{id}/entity-suggestion`（「再建議一個」＝獨立**文字** LLM `entity_suggestion_service.py`、單次嘗試失敗回 null 不 500；候選空零呼叫）；**注入點增為六個**（`get_entity_suggester`＋`FakeEntitySuggester` 入 `wire_fake_ai`））。**增量三 Phase 31〜33 成果（2026-08-21；31／33 前端零新增自動化測試、32 全程 TDD——端點 12→14、彈窗 1→3 份、瀏覽頁 2→3 分頁）**：**彈窗鏈「抽屜→實體→待辦」落地（design3 §2、§2.1）**——新檔 `static/entity_modal.js`（em- id＋fm-* 共用視覺 class：①採用建議②改選現有③自創④不釘（0 釘＝「不釘，繼續」／≥1＝「完成，繼續」）＋「再建議一個」（exclude＝已釘＋目前①；null→「沒有其他適合的實體了」）；釘上成功**窗不關**、②下拉即時換成回應清單）與 `static/task_modal.js`（tm- id：標題／到期日輸入框**預填建議可修改**、「建立待辦」／「略過」兩出口；**僅上傳鏈且 suggested_task 有標題才開**＝空關不跳）；抽屜窗結束（定案**或**稍後再說）一律續鏈到實體窗；待決定分頁補完鏈＝抽屜→實體（無①可「再建議」現算、無待辦窗——建議不持久化，總覽 §5 已知限制）。**Phase 32 待辦端點**：`POST /photos/{id}/task`（404→409「這張照片已經有待辦了」→寫入；CreateTaskRequest 驗證與轉型分離、中文 422 訊息）＋`GET /tasks`（`ORDER BY due_date ASC NULLS LAST, created_at DESC, id DESC`；JOIN photo 取縮圖、thumbnail_url 由 router 換算不洩路徑）。瀏覽頁三分頁「待決定（N）｜資料夾｜待辦（M）」（`?tab=tasks` 直達；待辦列表點列開 `/photos/{id}/image` 新分頁）。階段DDD Playwright 實操（真伺服器＋真 gemma4＋正式庫）：待決定補完鏈（歸檔→實體窗自動開→③自創「我的 MacBook」→②重複釘 409 紅字窗內→④完成）、上傳鏈（#22 ①採用「收據」定案→實體窗→④→**待辦窗未開＝空關不跳實測**）、待辦窗真頁面驅動 201、三分頁計數／到期排序／點回原圖、curl 錯誤路徑六項、console 乾淨；**真模型單次看圖延遲隨 9 欄 prompt 明顯變長（實測 2〜5 分鐘／張，先前 10〜60 秒）——已記錄於階段DDD REP 供產品負責人斟酌**。**增量三 Phase 34〜37 成果（2026-08-22；全程 TDD＋BDD、逐 phase 獨立 review＋fix loop；未 commit）**：**Phase 34 詢問三路**——route 四選一（metadata／vector／**entity**／**task**）：`RouteDecision` 加 `entity_name`／`due_within_days`（`Field(ge=0, le=3650)`，超界＝結構化輸出失敗＝走既有 fallback vector，誠實優於默默 clamp）、`RouterClient.route(question, entity_names)` 介面改版（端點層 `list_entities()` 注入現有實體名單、prompt 補中英 few-shot 各兩例＋「entity_name 一律照清單原文」例外規則）；repository 新查詢 `list_photos_with_entity`（欄位恰餵 `row_to_document`）與 `search_tasks(due_before)`（None＝全部；有值排除無期限；`TASK_ORDERING` 常數與 `list_tasks` 共用）；task Document 的 `metadata["id"]`＝**來源照片 id**（`retrieved_photo_ids` 契約不變）；entity Document **前置一行釘選事實**（真模型煙霧抓到「ids 檢索對了、回答卻說查無」的缺陷後修正——釘選＝人宣告的關聯，內容不必提到那件東西）；`SEARCH_MODE_LABELS` 加 `"entity pin search"`／`"task search"`；真模型煙霧五問全對（英文問句對回中文實體名、待辦 due 排序、回答語言跟隨、「這週」7 天窗）。**Phase 35 抽屜糾錯 few-shot（N=5）**——photo 加 `suggested_category` 欄（`migrate_design3.sql` 追加冪等 ALTER，**正式庫已遷移**、跑兩次證冪等、既有列全 NULL＝沒建議）；上傳存 clamp 後建議（建議＝收件箱→NULL）；PATCH 定案成功後 `_record_correction_if_changed`（casefold 防禦性比對；寫入失敗只 log warning 不影響歸類；409／422／embedding 失敗路徑走不到＝不記）；`build_vlm_prompt(folders, entities, corrections)`（`understand()` 第五參數四處同步、PDF 各頁共用一次讀取；`_excerpt()` 60 字截斷＋摺行防 prompt 注入；**corrections 空＝prompt 與改版前逐字相同**，黃金檔測試釘住）；`GET /folders/{id}` 照片摘要四鍵→**五鍵**（+`suggested_category`，待決定分頁靠它畫選項①、不必再看一次圖）；真模型端到端煙霧閉環（真上傳→建議落庫→改歸→糾錯入庫→下次 prompt 注入格式正確）。**Phase 36 無線鏡頭（路線 B，2026-08-22 已釐清）**——**端點 14→17**：`POST /camera/session`（segno 本機產 QR SVG＋LAN IP 推導：request host 優先、loopback 才 UDP socket 戲法）＋`POST /camera/{token}/photos`（驗 token 後**轉呼叫 `_ingest_image()`**，415／422／先進未分類語意一字不變；成功存 latest）＋`GET /camera/{token}/latest`（200／204）；WS `/camera/{token}/signal?role=desk|phone` 純 relay（**不進 openapi.json**；亂 token accept 前拒＝HTTP 403；binary frame 忽略、64KB 上限、**每訊息重驗 TTL**、同角色重連讓位 4409、desk 斷線＝session 即失效）；新檔 `services/camera_session_service.py`（token 全記憶體、TTL 600 秒、單一 session 新建汰舊、`time.monotonic` 包成 `_now()` seam、identity 比對防跨執行緒誤清）；前端 `camera-desk.html`（QR＋遠端預覽＋四鈕＋彈窗鏈）＋`camera-phone.html`（getUserMedia 後鏡頭、WebRTC 發送端 host ICE 零 STUN/TURN、canvas 原生解析擷 JPEG、閃光**能力回報制**＋`getSettings().torch` 復驗降級）；三關彈窗鏈抽成**全站唯一一份 `static/classify_chain.js`**（upload 頁行為逐位元不變）；`certs/` 入 .gitignore、mkcert＋HTTPS 啟動＋iPhone 信任步驟入本檔指令區；規格 `無線鏡頭拍攝.feature` 兩個 Example 由新 binder `test_camera_feature.py` 綁定（規格檔一字未動）；**真機 iPhone 驗收待產品負責人**（手冊：scratchpad task-36-report.md §7；先 `mkcert -install`）。**Phase 37 錯誤收尾與全量回歸**——`test_design3_error_paths.py` 把 design3 錯誤表 16 列逐列釘死（17 顆；**首跑 16 綠 1 紅＝揪出真缺陷**：自創實體＋釘選兩次呼叫非原子，釘選失敗留「沒人釘的空實體」且重試同名 409 死路→新增 `photo_repository.create_and_pin_entity()` 兩筆 INSERT 同一交易，rollback 實測以真外鍵違反觸發）；「明確不做」12 項掃碼全過（無自動拍／第二模型／tool calling／Gmail·Calendar／雲端 VLM／DELETE／多使用者／螢幕錄製／實體當資料夾／STUN·TURN／第三方 QR／token 落庫）；端點恰 17、openapi 零 DELETE、SQL 只在 repository 皆有自動化測試釘住。**規格檔於 2026-08-22 由產品負責人指示（另一 session）擴充**：+5 個 feature 檔（歸類照片／釘選實體／建立待辦／瀏覽檔案櫃／無線鏡頭拍攝）＋`上傳照片.feature` 補實體／待辦建議 Rule（已綁已綠）＋`自然語言詢問.feature` 補兩條 P34 Rule 掛 **`@未實作`**（＝全量的 2 skipped；binder steps 已預寫、conftest 有 `pytest_bdd_apply_tag`；**摘標屬產品負責人**——摘標前注意其待辦例子 due=2026-09-18 與問句「這週」的 7 天過濾互相矛盾，擇一修正）。**AI 後端切換（2026-08-22 產品負責人本 session 指示；design3「明確不做」的「雲端 VLM」一項自此正式作廢，其餘不做項全部不動）**：上傳頁、問問題頁與無線鏡頭桌面頁（camera-desk）頁首放**同一顆**「AI 模型：本機｜雲端」開關（行為在 `static/ai_switch.js` 全站唯一一份；`GET`／`PUT /settings/ai-backend`，**端點 17→19**、清點測試已同步；狀態存 `config.AI_BACKEND` 純記憶體、**重啟一律回本機**；沒填 key 切雲端＝422 開關不動）。開關管**四個注入點**、每請求即時分流（`get_vlm`／`get_router`／`get_answerer`／`get_entity_suggester`——單圖／PDF 逐頁／無線鏡頭／詢問／「再建議一個」全部跟著走）：雲端實作 `OllamaCloudVLM`／`OllamaCloudRouter`／`OllamaCloudAnswerer`／`OllamaCloudEntitySuggester` 與本機**共用同一份 prompt**（抽出 `build_route_prompt`／`build_answer_prompt`／`_build_pick_prompt` 兩邊逐字相同）、失敗語意逐一鏡射（看圖重試一次→understood=False→422；路由失敗由 route 節點統一 fallback vector；回答失敗 500 不吞錯；建議失敗回 None 留 log）；**embeddings 一律本機、不歸開關管**（向量須與庫裡既有 bge-m3 同源）。共用底座 `services/ollama_cloud.py`＝全系統唯一建雲端 Client 的地方（官方 `ollama` 套件 `Client(host="https://ollama.com", headers=Bearer OLLAMA_API_KEY, timeout=300)`）。`.env`：`OLLAMA_API_KEY`（產品負責人已自填；改 key 要重啟 uvicorn）、`OLLAMA_CLOUD_VLM_MODEL`／`OLLAMA_CLOUD_LLM_MODEL` 可覆蓋（預設同本機模型名——**但本機自 2026-08-22 改用 MLX 標籤 `gemma4:e2b-mlx` 後，兩者已在 .env 明確釘成 `gemma4`**：雲端沒有本機的 MLX tag，跟著同名會 404，真煙霧踩過——路由 404 被 fallback 吞掉、回答 404 炸 500，route 節點因此補了 fallback 警告 log）。**真雲端煙霧（2026-08-22 產品負責人實測看圖）**：key 通、單張 1.9 秒（本機同 prompt 2〜5 分鐘），抓到 **ollama.com 對 `format=` 不強制**——gemma4 照 prompt 樣式回 markdown 條列→Pydantic json_invalid→422。修法＝三道保險：`format=` 照帶＋各雲端 prompt 尾接「只准回 JSON」指令（`CLOUD_JSON_INSTRUCTION`／`CLOUD_ROUTE_JSON_INSTRUCTION`／`CLOUD_PICK_JSON_INSTRUCTION`）＋`ollama_cloud.extract_json_object()` 剝圍欄／贅字後再交 Pydantic 驗證——共用 prompt 與黃金檔零影響。+17 tests（`test_ai_backend_switch.py` 5＋vlm 雲端解析 6＋雲端路由/回答 4＋雲端實體建議 2；假 key 必須 ASCII——HTTP header 不吃中文）；看圖已由產品負責人真雲端驗過（修正後續驗）、**問答與實體建議的真雲端端到端待產品負責人手動煙霧**。pytest 測試自 Phase 03 起以 TDD 建立：`tests/unit/`＋`tests/integration/`（目前 **358 passed＋2 skipped**），`tests/conftest.py` 自動把 `DATABASE_URL` 切到 `PersonalDocAI_test`，並以**三道 autouse 安全網**擋掉危險預設：`reset_tables`（每測清空 `photo`＋`folder`＋`entity`＋`folder_correction`（CASCADE 連帶 `photo_entity`／`task`）並重播六筆資料夾種子，folder id 保證 1〜6；**絕不清正式庫**）、`wire_fake_ai`（AI／時鐘全部換假件；**pytest 絕不呼叫真 Ollama**——本機 Ollama 常駐，忘記覆寫會誤觸真模型推論；真模型只做手動煙霧，不進驗收與 CI）、`isolated_data_dir`（`config.DATA_DIR` 指到 tmp_path；**pytest 絕不寫專案 `data/`**）。假件與真圖工具（`make_png_bytes`／`make_jpeg_bytes`——Pillow 會真的解碼，假位元組會炸 `UnidentifiedImageError`）在 `tests/fakes.py`。

## 指令

```bash
# 每次開工（每個新終端機視窗都要）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 安裝／更新依賴（本專案用 uv 管理套件）
uv pip install -r requirements.txt

# 啟動開發伺服器（http://localhost:8000，API 文件在 /docs）
uvicorn app.main:app --reload --port 8000

# ── 無線鏡頭的 HTTPS 憑證（Phase 36；每台機器只做一次）────────────────
# 為什麼一定要 HTTPS：手機瀏覽器只在「安全來源」才給 getUserMedia（鏡頭）權限，
# http://192.168.x.x:8000 一定開不了鏡頭。這是瀏覽器規格，不是設定問題。
brew install mkcert                       # 產本機自簽憑證的工具
mkcert -install                           # 讓這台 Mac 信任 mkcert 的根憑證（會問密碼）
mkdir -p certs                            # certs/ 已入 .gitignore，重新 clone 後不存在
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(ipconfig getifaddr en0) localhost 127.0.0.1
# 憑證要「重簽」的唯一情境：本機區網 IP 換了（憑證把 IP 寫死在 SAN 裡）。
# mkcert -install 晚一步做不影響已產出的憑證——信任的是根憑證，往回回溯就生效。
# iPhone 也要信任同一張根憑證（一次性，換手機才要再做）：
#   1. open "$(mkcert -CAROOT)"            # ＝ ~/Library/Application Support/mkcert
#   2. 把裡面的 rootCA.pem 用 AirDrop 傳到 iPhone（rootCA-key.pem 不要傳）
#   3. iPhone：設定 →（最上方）已下載描述檔 → 安裝 → 輸入密碼 → 安裝
#      找不到那一列時：設定 → 一般 → VPN 與裝置管理 →（描述檔）→ 安裝
#   4. iPhone：設定 → 一般 → 關於 → 憑證信任設定 → 把 mkcert 那一列打開「完全信任」
#      ⚠ 少了第 4 步 Safari 仍會擋，而且錯誤訊息看起來像「網路怪怪的」，很難聯想。

# 啟動 HTTPS 開發伺服器（Phase 36 無線鏡頭專用）
# --host 0.0.0.0 ＝也聽區網那張網卡，手機才連得到
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
# 之後電腦要用 https://<本機區網IP>:8000/ui/camera-desk.html 開頁（不要用 localhost，
# 那樣 QR 只能靠 UDP 偵測猜 IP）。查本機區網 IP：ipconfig getifaddr en0

# 跑測試（Phase 03 起；在專案根目錄執行，會自動連 PersonalDocAI_test 並每測清空）
pytest -q

# 只跑規格檔 binder（上傳＋詢問＋無線鏡頭三份；詢問的兩條 @未實作 Rule 會 skip，摘標屬產品負責人）
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py tests/integration/test_camera_feature.py -v

# 只跑無線鏡頭規格檔（Phase 36；有 Example 的 2 條 Rule，其餘 4 條標 #TODO 不產生 scenario）
pytest tests/integration/test_camera_feature.py -v

# 只跑本增量的錯誤路徑把關（design1.md §12 逐列，9 個）
pytest tests/integration/test_folder_error_paths.py -v

# 手動煙霧測試（需要 Ollama 真的在跑；真模型不寫自動化測試、不進驗收與 CI）
python scripts/check_embedding_dim.py

# 資料庫建表（schema.sql 開頭是 DROP TABLE IF EXISTS，重跑＝清空重建；含 folder 表＋六筆種子）
psql -d PersonalDocAI_test -f db/schema.sql   # 測試庫（可隨意重建）
# ⚠️ 正式庫有真實照片，「不要」用 schema.sql 重建；結構改版一律走可重跑的遷移腳本
psql -d PersonalDocAI -f db/migrate_folders.sql   # 正式庫遷移（idempotent；2026-08-20 已執行）
psql -d PersonalDocAI -f db/migrate_design3.sql   # 正式庫遷移·增量三四表（idempotent；2026-08-21 已執行）

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

**目前進度**：四階段全數完成——18 項釐清 Resolved（見 `.clarify/overview.md`）、12 條 Rule 全數附 Example、無 #TODO；`docs/design/design.md`（**v4**）為 canonical design：分層架構（api/routers→services→repositories）、Ollama 本地模型（gemma4＋bge-m3）、中英雙語、side project 原則、Phase 14 極簡網頁介面。v4 實作已全數完成（phase-01〜14 歸檔於 `docs/plan/finish/`）。**2026-08-20 起增量另有 canonical design `docs/design/design1.md`**（資料夾＝category、原圖瀏覽；詢問流程不變）：design1.md 列明的推翻項以 design1.md 為準，未提及的行為仍以 design.md v4 與 Clarify 為準；增量（P15〜26）進度見 `docs/plan/finish/phase-00-增量總覽.md` §5（全數完成；P20 起 `上傳照片.feature` 為改版後的 10 條 Rule 版本）。**2026-08-21 起另有增量二 canonical design `docs/design/design2.md`**（待決定區與定案鎖定）：其 §1.1 列明的推翻項以 design2.md 為準，未提及者仍依 design1.md／design.md v4；實作計畫 `phase-27-待決定區與定案鎖定.md` 已完成並歸檔於 `docs/plan/finish/`。**2026-08-21 起另有增量三 canonical design `docs/design/design3.md`**（無線鏡頭、實體、待辦——三個彈窗依序、實體＝別針、待辦人確認才建）：其 §1.1 列明的推翻項以 design3.md 為準，未提及者仍依 design2.md／design1.md／design.md v4；實作計畫在 `docs/plan/unfinish/`（phase-00-增量三總覽＋phase-28〜37；**28〜37 全數實作完成**——28〜33 已 commit（`e29f5a1`／`0cabb45`），34〜37 於 2026-08-22 完成、依指示未 commit；phase-36 真機（iPhone）驗收與 `@未實作` 摘標待產品負責人；unfinish/→finish/ 歸檔依慣例隨 commit 執行）。

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
- **原圖與縮圖存在本機 `data/`，不入版控**（`.gitignore` 已加 `data/`）。正式庫的 2 張舊照片沒有原圖（`original_path` 為 NULL），瀏覽時顯示占位是**預期行為**，不是 bug。`DATA_DIR` 在 pytest 由 `isolated_data_dir` fixture 導向臨時目錄，所以跑測試永遠不會弄髒專案的 `data/`。

## 語言與其他慣例

- 文件與規格一律使用**繁體中文＋台灣常用技術用語**；Gherkin step 以中文描述、DataTable 欄位名用英文、Given/When/Then 用英文關鍵字。
- 使用者層級的 `~/CLAUDE.md` 另有 MCP 使用規則（查最新文件用 Context7、研究類 MCP 只查不改碼、結論附來源連結），同樣適用於本專案。
