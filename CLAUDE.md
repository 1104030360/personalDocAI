# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

**PersonalDocAI**（舊名 Visual Memory RAG——`docs/spec/` 規格區唯讀（唯一例外：`上傳照片.feature` 經產品負責人核准、2026-08-21 依 design1.md 改版為 10 條 Rule）、`docs/plan/` 歸檔屬歷史紀錄，兩處仍沿用舊名不回改）：小型、可實際 demo 的 Multimodal RAG backend。使用者上傳照片，系統以 VLM 理解內容轉成文字與結構化 metadata，經 LangChain 產生 embedding 存入 PostgreSQL + pgvector；之後可用自然語言詢問，由 LangGraph workflow 依問題類型路由至 vector semantic search 或 metadata search，最後交給 LLM 產生回答。

**功能核心兩項：上傳照片、自然語言詢問**。2026-08-20 起產品負責人以 `docs/design/design1.md`（增量 canonical design）**正式改規格**，核准新增：存原圖＋縮圖（DB 只記路徑）、資料夾（`category`＝資料夾名稱、VLM 推薦＋人確認）、上傳確認彈窗、資料夾瀏覽——實作路線圖為 `docs/plan/finish/phase-00-增量總覽.md`（Phase 15〜26，已完成歸檔）。design1.md §1.1 明示推翻的舊禁令**僅四項**（不存原始檔、禁照片瀏覽、category 自由字串、網頁僅兩頁/不加端點）；**其餘禁令全部仍有效**（多使用者、刪除照片、非同步佇列、對話記憶、雲端儲存、前端框架等一律禁止）。

**現況：Phase 01〜14 全數完成（2026-08-19，v4 系統）；增量 Phase 15〜26 全數完成（2026-08-21）——design1.md 描述的「個人視覺檔案櫃」已全部落地；增量二 Phase 27（`docs/design/design2.md`：待決定區與定案鎖定）已完成（2026-08-21）；增量三（`docs/design/design3.md`：無線鏡頭、實體、待辦）**Phase 28〜37 全數實作完成**（28〜33 於 2026-08-21 完成並已 commit——28〜30 在 `e29f5a1`、31〜33 在 `0cabb45`；34〜37 於 2026-08-22 完成，**已於 2026-08-23 進 commit `6392270`**；phase-36 的真機（iPhone）驗收**已於 2026-08-25 由產品負責人完成**——log 逐關留證：desk-ready → torch-supported → WebRTC offer/answer＋ICE（零 STUN/TURN 打洞成功）→ uploading → `POST /camera/{token}/photos` 201 → uploaded → `GET …/latest` 200；照片 #41／#42 真的入庫）。**2026-08-25 真機驗收時另修一處 QR 可掃性**：桌面頁改用 Bonjour 主機名（`<主機名>.local`，好處是 IP 換了也不必改網址／重簽憑證）開之後，網址從 93 → 118 字元，QR 從 49 格變 53 格，而 `style.css` 的 `.cd-qr svg` 當時 `max-width: 15rem`（240px），每格只剩 4.5px、**iPhone 掃不到**（QR 畫得出來、只是掃不進去＝安靜壞掉）；改成 `20rem`（320px）後每格 6.0px，兩種網址都好掃。**這是增量四唯一一次改產品碼**（一行 CSS，純顯示尺寸、零行為變更），並補一顆 `test_qr的顯示尺寸夠大讓長網址也掃得到` 把值釘死（改小會紅，已實測）。**改完後產品負責人真機複驗通過**，`.local` 這條路自此成立：日常網址固定為 `https://<主機名>.local:8000/`，**換 Wi-Fi／IP 變動都不必改網址、也不必重簽憑證**（憑證同時簽了 `.local` 與當下 IP，IP 那條路留作 mDNS 被擋時的退路）；操作手冊見根目錄 `LAUNCH.md`**——環境就緒（Python 3.12 venv、**PostgreSQL 17＋pgvector 跑在 Docker container，發佈於 `127.0.0.1:5433`**——2026-08-24 增量四遷移，brew 的 `postgresql@17` 已停用但資料目錄留著當後悔藥；Ollama 仍在 Mac 上，gemma4＋bge-m3）、`app/` 分層骨架已建；`photo` 資料表（兩庫＋HNSW cosine 索引）、`db/session.py`、`repositories/photo_repository.py`（全系統唯一寫 SQL）皆完成；**`POST /photos` 全流程可用**：格式檢查（非 JPEG/PNG→415）→ `services/vlm_service.py` 看圖（正式路徑 `OllamaVLM`；看不懂／呼叫失敗／text 空白→422 什麼都不存）→ `services/indexing_service.py` 固定順序合併＋轉向量（`embed_query`）→ 一條 INSERT → `UploadResponse` 201。注入點在 `app/dependencies.py`（`get_vlm`／`get_embeddings`／`get_now`）。上傳功能已過**規格驗收**（pytest-bdd 直接掛 `上傳照片.feature`，7 條 Rule U1〜U7 全綠；規格檔唯讀）並完成**真模型煙霧**（`scripts/check_embedding_dim.py` 實測 bge-m3＝1024 維、中英同義句相似度 0.837 vs 無關句 0.377；gemma4 真看圖＋真 HTTP 上傳成功，正式庫已有真實照片資料）。**檢索層與路由已完成**（Phase 09〜10）：`photo_repository` 兩條查詢（條件查詢 `ILIKE`＋`unnest` ILIKE、語意查詢 pgvector `<=>` top-5，共用 `COALESCE(content_time, uploaded_at::date) >= 今天−30天` 時間過濾）、`services/retrieval_service.py` 的 `@chain` 自訂 retriever（DD-4：不用 PGVector store）、`services/ask_workflow.py` 的 LangGraph 圖（START→route→條件邊→retrieve_metadata／retrieve_vector→END；route 由 LLM 一次結構化輸出判查法＋抽條件、中英 few-shot、失敗一律 fallback 語意查詢；真模型路由煙霧中英各一已實測通過）。**詢問端點與規格驗收已完成**（Phase 11〜12）：`ask_workflow.py` 的 generate 節點（`ANSWER_PROMPT` 三條鐵律——只依檢索到的照片內容回答、查無不虛構、**回答語言跟隨提問語言**且照片內容原文不翻譯）＋`api/routers/ask.py` 的 **`POST /ask` 全流程可用**（`AskDeps` 注入 `get_router`／`get_answerer`／`get_embeddings`／`get_today`，`get_today` 鏈到 `get_now`；`search_mode` 與 `retrieved_photo_ids` 直取流程 state、不經 AI，靠 `config.SEARCH_MODE_LABELS` 轉全名；`AskRequest.question` 以 `min_length=1` 讓缺漏／空字串走框架既有 422）。詢問已過**規格驗收**（pytest-bdd 直接掛 `自然語言詢問.feature`，5 條 Rule Q1〜Q5 共 7 例全綠——至此 **12 條 Rule 全數綠燈**）並完成**真模型煙霧**（gemma4：中文問正確引用照片內容且走 metadata search、英文問走 vector semantic search 且回答為英文句、照片內容「可樂」原文保留；回應鍵恰為 answer／retrieved_photo_ids／search_mode）。`tests/conftest.py` 的 `wire_fake_ai` 安全網已涵蓋**全部五個**注入點（`OLLAMA_BASE_URL` 指死埠全量仍 67 passed，實證零 Ollama 依賴）；`search_by_vector` 的 30 天過濾經變異測試證實由 SQL 生效。**錯誤路徑收尾與網頁介面也已完成**（Phase 13〜14）：design.md 錯誤處理總表七列各有測試把關（`integration/test_error_paths.py`：415／422 不寫入、大檔無上限路徑、缺漏空字串 422、路由失敗 200 fallback、查無中英雙語、embedding／DB 失敗 500 不吞錯），「明確不做」清單以檢查腳本逐項核對通過（驗收當時端點恰 3、無寫檔、無 user 欄位、無佇列、metadata 恰四欄、全本地、SQL 只在 repository、無全域例外捕捉；**2026-08-20 依使用者指示追加第 4 個端點 `GET /` → 轉址 `/ui/upload.html`**，歸檔的 phase-13/14 計畫中「端點恰 3」的檢查數字以此為準）；`app/static/upload.html`＋`ask.html` 兩個純 HTML 頁掛在 `/ui`（`main.py` 一行 `app.mount`，**零框架、零打包、零新增端點、零新增自動化測試**），瀏覽器實操驗收（上傳 201／415、中英問答、查無、雙向互連、console 乾淨）與真模型中英雙語煙霧（真照片上傳＋條件／語意／模糊五種詢問）全數通過。**增量 Phase 15〜17 成果（2026-08-20，全程 TDD、對外行為零改變——端點仍 4 個、回應不變）**：`folder` 資料表（六筆預設種子「未分類(收件箱)／收據／飲食／風景／文件／其他」，**插入順序即 id 1〜6**，三處同步定義：`db/schema.sql`、`db/migrate_folders.sql`、`DEFAULT_FOLDERS`；partial unique index `folder_one_inbox` 保證全系統至多一個收件箱）＋`photo` 新增 `folder_id`（NOT NULL FK；`insert_photo` 以 SQL 內 COALESCE＋子查詢依 `category` 不分大小寫自動歸夾、對不到掛「未分類」，**`category` 值本身不改寫**——改寫是 Phase 20/21 的事）與 `original_path`／`thumbnail_path`／`content_type` 三欄（目前恆 NULL，Phase 19 才寫檔回填）；**正式庫已遷移**（可重跑的 `db/migrate_folders.sql`，2 列真照片歸「收據」、路徑 NULL；遷移前備份 `~/PersonalDocAI-backup-遷移前.sql` 保留中）；**資料夾資料層五函式**（`list_folders`／`get_folder`／`find_folder_by_name`(lower() 不分大小寫)／`create_folder`(不自檢重名，409 屬 Phase 21 router)／`list_photos_in_folder`(新的在前、不含 embedding)，回傳鍵名即之後 Pydantic 模型的契約）；**檔案儲存層 `services/storage_service.py`**（原圖位元組原樣落地 `data/photos/{id}.jpg|png`、Pillow 縮圖長邊≤512 等比不放大落地 `data/thumbs/`、DB 只存 `data/` 開頭相對路徑、`absolute_path` 依 `config.DATA_DIR` 呼叫當下換算、`remove_if_exists` 容錯清理；`data/` 已入 `.gitignore`、`Pillow>=10` 入 requirements——2026-08-21 起由 Phase 19 接上上傳流程）。**增量 Phase 18〜20 成果（2026-08-21，全程 TDD＋BDD；上傳行為正式改版、端點 4→6）**：`vlm_service` 的 `VLM_PROMPT` 常數改為 `build_vlm_prompt(folders)`（資料夾清單動態注入 prompt——「category 只能從清單選一個、禁止自創名稱、不確定填『未分類』」；category 一律照清單原文、不隨照片語言翻譯）＋純函式 `clamp_category(category, folders)`（去空白＋`casefold()` 大小寫不敏感，命中回**清單原文**、否則「未分類」），`VLMClient`／`OllamaVLM`／`FakeVLM` 的 `understand()` 皆收 `folders` 參數（仍只有一次看圖呼叫、無第二模型）。上傳流程改為 **INSERT→存原圖→產縮圖→UPDATE 回寫路徑**（檔名要用 id 所以 INSERT 必先行；任何一步失敗＝`remove_if_exists`×2＋`delete_photo` 清乾淨再 re-raise 回 500 不吞錯；這兩個 repository 函式只供失敗清理、無刪除端點），新增 `GET /photos/{id}/thumbnail`／`/image` 兩端點（沒這列／路徑 NULL（遷移舊照片，前端占位）／磁碟檔案不在 → 一律 404；都在 → `FileResponse`＋`media_type`）。**上傳一律先進「未分類」**：clamp 後的建議只出現在回應、不落庫（`suggested_folder` 保證是 `folders` 裡的一筆）；合併與向量用「未分類」（歸類後由 Phase 21 的 PATCH 重算）；201 回應新增 `folder`／`suggested_folder`／`folders`／`thumbnail_url` 四欄位（`schemas/photo.py` 新增 `FolderOut`，只外送 id/name/description）——彈窗要的資料一次帶齊。**`上傳照片.feature` 已正式改版**（7→10 條 Rule、檔頭註明 2026-08-20 核准來源；`自然語言詢問.feature` 一字未動，Q1〜Q5 全程保綠）。「預期上傳成功」的測試自 Phase 19 起一律用 `make_png_bytes()`／`make_jpeg_bytes()`／`make_large_png_bytes()` 真圖（415／422／embedding 失敗路徑**刻意保留**假位元組，證明失敗路徑不解碼圖片）。真模型煙霧（2026-08-21 手動）：真收據 JPEG 經真 gemma4 上傳成功——英文 text／items 原文保留、content_time 讀出圖上日期、`suggested_folder`＝「收據」（真模型從注入清單挑中）、落庫「未分類」；原圖與縮圖落地 `data/`（SHA1 與上傳檔一致、縮圖長邊 512）、讀圖端點 200、舊照片（路徑 NULL）404——**正式庫現有 3 列（2 舊＋1 煙霧）**。**增量 Phase 21〜24 成果（2026-08-21；21／22 全程 TDD、23／24 純前端零新增測試——端點 6→9、網頁 2→3 頁）**：**`PATCH /photos/{id}/folder` 歸類端點**（`AssignFolderRequest` 用 `@model_validator(mode="after")` 做 folder_id／name「恰一」驗證＋name 去空白，違者 422；順序鐵律＝404（先照片後資料夾）／409（`find_folder_by_name` 擋重名）檢查 → 用新名稱 `build_document`＋`embed_document` → 自建這時才 `create_folder` → `update_photo_folder()` **一條 UPDATE** 同寫 folder_id＋category＋重算的 embedding（RETURNING）——**embedding 失敗＝500 且資料庫完全沒動、不留空資料夾**，靠排序不靠交易；歸類後語意查詢拿得到正確類別訊號，design1.md §7.3）。**`GET /folders`／`GET /folders/{id}` 瀏覽端點**（新檔 `schemas/folder.py` 三模型＋`api/routers/folders.py` **零 SQL**；前者直接回陣列含 photo_count（LEFT JOIN，空資料夾不消失），後者回 `{folder, photos}`、摘要恰四鍵（id/thumbnail_url/text/uploaded_at）新的在前，`thumbnail_url` 由端點換算成 `/photos/{id}/thumbnail` 網址——**不洩硬碟路徑**、舊資料 NULL→null 前端占位；不做「列出全部照片」端點、不做分頁）。**前端三頁**：`upload.html` 201 後開三選項 modal（採用建議／改選現有／自建新資料夾；×／Esc＝不呼叫 API 留「未分類」）、新增 `browse.html`（資料夾卡片→縮圖牆→點照片以 `primaryVerb:"維持"` 開同一彈窗再歸類；`?folder=N` 網址切畫面所以上一頁／書籤免費；無縮圖畫灰底「無縮圖」占位）、**彈窗程式碼全站唯一一份 `static/folder_modal.js`**（fm 前綴隔離全域、僅靠 onAssigned/onClosed callback 對外；**禁用 alert/confirm/prompt**，錯誤一律寫進彈窗內 `#fm-error`；動態內容一律 textContent）、三頁導覽互連（`ask.html` 僅 nav 一處改動、行為零變）。Playwright MCP 瀏覽器實操驗收（P23 十三項＋P24 十九項）全數通過：三選項各實走、409/422 彈窗內紅字、×/Esc 留未分類、舊照片占位圖、上一頁／重新整理、上傳頁共用檔回歸；正式庫實測軌跡（照片 7：收據→飲食→旅遊）。**增量 Phase 25〜26 成果（2026-08-21）**：新測試檔 `tests/integration/test_folder_error_paths.py`（9 顆）把 design1.md §12 錯誤表的九個 ★ 缺口釘死（失敗不建資料夾、清單外建議→未分類、重名大小寫 409 不覆蓋、原圖被刪讀原圖 404、PATCH embedding 失敗雙路徑資料庫零變動不留空資料夾、無刪除端點掃碼）——**首跑 0 紅 9 綠**、零產品碼修改；`OLLAMA_BASE_URL` 指死埠全量同顆數（零外部依賴實證）；「明確不做」最終版與正式庫四查詢全過。**Phase 26 美化**：新增 `app/static/style.css`＝全站唯一樣式來源（design tokens：紙白底＋牛皮紙次底＋深琥珀單一強調色 #7c5200、Avenir Next/PingFang 標籤感 display、五級字級六級間距、唯彈窗有陰影；檔頭記禁止清單＋參考來源 immich／photoprism 與選色理由；簽名元素＝資料夾卡片的牛皮紙索引 tab），三頁刪光頁內 `<style>` 改共用（site-header＋aria-current 導覽、panel/status/kv 卡片語言、innerHTML 一律過 `esc()`、屬性不插值），`folder_modal.js` 刪 `FOLDER_MODAL_CSS`＋加焦點管理／`body.fm-open` 鎖捲動／點暗色區關閉（`fmAssign` 等四函式零改動）；Playwright 前後 6＋6 張截圖對比與 17 項實操全過、console 僅預期日誌。已完成 phase 計畫（01〜26 含 phase-00-增量總覽）與 phase-27 歸檔於 `docs/plan/finish/`；增量三計畫（phase-00-增量三總覽＋phase-28〜37）**已全數完成並歸檔於 `docs/plan/finish/`**；增量四與增量五的計畫（含各自 phase-00 總覽）亦已全數歸檔於 `docs/plan/finish/`——`docs/plan/unfinish/` 於 2026-08-27 隨增量五 commit 清空。進度與紀錄見 `docs/plan/todo/`、`docs/plan/report/`。**增量二 Phase 27 成果（2026-08-21，design2.md「待決定區與定案鎖定」，產品負責人對話拍板——推翻 design1 的「關掉彈窗／之後可再歸類／瀏覽頁可改資料夾」三項，其餘不動）**：上傳彈窗改**強制決定**（無 ×／Esc／點外，四個明確出口：採用建議（建議＝未分類時不顯示①）／改選（下拉排除收件箱）／自建／**稍後再說**＝照片留待決定、不打 API）；**定案不可逆（後端擋）**——`PATCH /photos/{id}/folder` 只接受還在收件箱的照片（已定案 **409**「照片已定案，不可再變更資料夾」；目標是收件箱 **422**「不能歸檔到收件箱」），無任何後悔藥；瀏覽頁分「**待決定（N）｜資料夾**」兩個 tab（預設待決定；`?tab=folders`／`?folder=N` 網址直達）——「未分類」不再以卡片出現、待決定 tab 是唯一的第二歸類入口（彈窗無①）、資料夾牆**純瀏覽**（photo-static div、點不動）。資料模型與端點數（9）零變動；+3 tests（`test_assign_folder.py` 11 顆）。**增量三 Phase 28〜30 成果（2026-08-21，design3.md 前半；全程 TDD＋BDD，152→207 tests、端點 9→12）**：**Phase 28 PDF 入庫**（`ALLOWED_CONTENT_TYPES` 加 `application/pdf`；新檔 `services/pdf_service.py`＝全系統唯一碰 pypdfium2 的地方，`render_pages()` 逐頁渲染 PNG、壞檔／零頁丟 `PdfUnreadableError`→422 什麼都不存；router 抽出 `_ingest_image()`（單圖行為一字不變）＋`_ingest_pdf()` 逐頁走同一流程——每頁存成 PNG 所以讀圖端點零改動、只吞單頁 422 記入 `skipped_pages`、全頁失敗 422、部分成功 201 `PdfUploadResponse{pages, created, skipped_pages}`（`response_model` Union）；`上傳照片.feature` 依 design3.md D7 核准追加第 11 條 Rule（PDF 一頁一張），前端 accept 加 PDF、彈窗只為第一頁開；測試工具 `make_pdf_bytes()` 用 Pillow 原生 PDF 輸出）。**Phase 29 資料層**（`db/migrate_design3.sql` 一次建四表且可重跑——`entity`（name UNIQUE）／`photo_entity`（PK(photo_id,entity_id)、ON DELETE CASCADE）／`task`（photo_id UNIQUE＝每張照片至多一筆）／`folder_correction`（P35 才有程式用）；**正式庫已遷移**（備份 `~/PersonalDocAI-backup-增量三前.sql`、跑兩次證冪等、既有資料原封不動）；entity 六函式鏡射 folder 系列；`reset_folders_and_photos` TRUNCATE 明列 entity／folder_correction（CASCADE 只會連到指著被清表的 photo_entity／task）、`clear_photos` 因新外鍵補 CASCADE）。**Phase 30 實體建議與釘選**（`PhotoUnderstanding` 6→9 欄——entity／task_title／task_due 皆為**建議**、人確認才落庫；`build_vlm_prompt(folders, entities)` 同輪注入實體清單與待辦規則、仍只一次看圖呼叫；`clamp_entity()` 清單外回 None（實體無「未分類」保底）；上傳回應加 `suggested_entity`／`entities`／`suggested_task`；新端點 `GET /entities`、`POST /photos/{id}/entities`（釘選：404→409 重名／重複釘→422 恰一，檢查全過才寫、**不重算 embedding**——實體走連結表不進向量）、`POST /photos/{id}/entity-suggestion`（「再建議一個」＝獨立**文字** LLM `entity_suggestion_service.py`、單次嘗試失敗回 null 不 500；候選空零呼叫）；**注入點增為六個**（`get_entity_suggester`＋`FakeEntitySuggester` 入 `wire_fake_ai`））。**增量三 Phase 31〜33 成果（2026-08-21；31／33 前端零新增自動化測試、32 全程 TDD——端點 12→14、彈窗 1→3 份、瀏覽頁 2→3 分頁）**：**彈窗鏈「抽屜→實體→待辦」落地（design3 §2、§2.1）**——新檔 `static/entity_modal.js`（em- id＋fm-* 共用視覺 class：①採用建議②改選現有③自創④不釘（0 釘＝「不釘，繼續」／≥1＝「完成，繼續」）＋「再建議一個」（exclude＝已釘＋目前①；null→「沒有其他適合的實體了」）；釘上成功**窗不關**、②下拉即時換成回應清單）與 `static/task_modal.js`（tm- id：標題／到期日輸入框**預填建議可修改**、「建立待辦」／「略過」兩出口；**僅上傳鏈且 suggested_task 有標題才開**＝空關不跳）；抽屜窗結束（定案**或**稍後再說）一律續鏈到實體窗；待決定分頁補完鏈＝抽屜→實體（無①可「再建議」現算、無待辦窗——建議不持久化，總覽 §5 已知限制）。**Phase 32 待辦端點**：`POST /photos/{id}/task`（404→409「這張照片已經有待辦了」→寫入；CreateTaskRequest 驗證與轉型分離、中文 422 訊息）＋`GET /tasks`（`ORDER BY due_date ASC NULLS LAST, created_at DESC, id DESC`；JOIN photo 取縮圖、thumbnail_url 由 router 換算不洩路徑）。瀏覽頁三分頁「待決定（N）｜資料夾｜待辦（M）」（`?tab=tasks` 直達；待辦列表點列開 `/photos/{id}/image` 新分頁）。階段DDD Playwright 實操（真伺服器＋真 gemma4＋正式庫）：待決定補完鏈（歸檔→實體窗自動開→③自創「我的 MacBook」→②重複釘 409 紅字窗內→④完成）、上傳鏈（#22 ①採用「收據」定案→實體窗→④→**待辦窗未開＝空關不跳實測**）、待辦窗真頁面驅動 201、三分頁計數／到期排序／點回原圖、curl 錯誤路徑六項、console 乾淨；**真模型單次看圖延遲隨 9 欄 prompt 明顯變長（實測 2〜5 分鐘／張，先前 10〜60 秒）——已記錄於階段DDD REP 供產品負責人斟酌**。**增量三 Phase 34〜37 成果（2026-08-22；全程 TDD＋BDD、逐 phase 獨立 review＋fix loop；未 commit）**：**Phase 34 詢問三路**——route 四選一（metadata／vector／**entity**／**task**）：`RouteDecision` 加 `entity_name`／`due_within_days`（`Field(ge=0, le=3650)`，超界＝結構化輸出失敗＝走既有 fallback vector，誠實優於默默 clamp）、`RouterClient.route(question, entity_names)` 介面改版（端點層 `list_entities()` 注入現有實體名單、prompt 補中英 few-shot 各兩例＋「entity_name 一律照清單原文」例外規則）；repository 新查詢 `list_photos_with_entity`（欄位恰餵 `row_to_document`）與 `search_tasks(due_before)`（None＝全部；有值排除無期限；`TASK_ORDERING` 常數與 `list_tasks` 共用）；task Document 的 `metadata["id"]`＝**來源照片 id**（`retrieved_photo_ids` 契約不變）；entity Document **前置一行釘選事實**（真模型煙霧抓到「ids 檢索對了、回答卻說查無」的缺陷後修正——釘選＝人宣告的關聯，內容不必提到那件東西）；`SEARCH_MODE_LABELS` 加 `"entity pin search"`／`"task search"`；真模型煙霧五問全對（英文問句對回中文實體名、待辦 due 排序、回答語言跟隨、「這週」7 天窗）。**Phase 35 抽屜糾錯 few-shot（N=5）**——photo 加 `suggested_category` 欄（`migrate_design3.sql` 追加冪等 ALTER，**正式庫已遷移**、跑兩次證冪等、既有列全 NULL＝沒建議）；上傳存 clamp 後建議（建議＝收件箱→NULL）；PATCH 定案成功後 `_record_correction_if_changed`（casefold 防禦性比對；寫入失敗只 log warning 不影響歸類；409／422／embedding 失敗路徑走不到＝不記）；`build_vlm_prompt(folders, entities, corrections)`（`understand()` 第五參數四處同步、PDF 各頁共用一次讀取；`_excerpt()` 60 字截斷＋摺行防 prompt 注入；**corrections 空＝prompt 與改版前逐字相同**，黃金檔測試釘住）；`GET /folders/{id}` 照片摘要四鍵→**五鍵**（+`suggested_category`，待決定分頁靠它畫選項①、不必再看一次圖）；真模型端到端煙霧閉環（真上傳→建議落庫→改歸→糾錯入庫→下次 prompt 注入格式正確）。**Phase 36 無線鏡頭（路線 B，2026-08-22 已釐清）**——**端點 14→17**：`POST /camera/session`（segno 本機產 QR SVG＋LAN IP 推導：request host 優先、loopback 才 UDP socket 戲法）＋`POST /camera/{token}/photos`（驗 token 後**轉呼叫 `_ingest_image()`**，415／422／先進未分類語意一字不變；成功存 latest）＋`GET /camera/{token}/latest`（200／204）；WS `/camera/{token}/signal?role=desk|phone` 純 relay（**不進 openapi.json**；亂 token accept 前拒＝HTTP 403；binary frame 忽略、64KB 上限、**每訊息重驗 TTL**、同角色重連讓位 4409、desk 斷線＝session 即失效）；新檔 `services/camera_session_service.py`（token 全記憶體、TTL 600 秒、單一 session 新建汰舊、`time.monotonic` 包成 `_now()` seam、identity 比對防跨執行緒誤清）；前端 `camera-desk.html`（QR＋遠端預覽＋四鈕＋彈窗鏈）＋`camera-phone.html`（getUserMedia 後鏡頭、WebRTC 發送端 host ICE 零 STUN/TURN、canvas 原生解析擷 JPEG、閃光**能力回報制**＋`getSettings().torch` 復驗降級）；三關彈窗鏈抽成**全站唯一一份 `static/classify_chain.js`**（upload 頁行為逐位元不變）；`certs/` 入 .gitignore、mkcert＋HTTPS 啟動＋iPhone 信任步驟入本檔指令區；規格 `無線鏡頭拍攝.feature` 兩個 Example 由新 binder `test_camera_feature.py` 綁定（規格檔一字未動）；**真機 iPhone 驗收待產品負責人**（手冊：scratchpad task-36-report.md §7；先 `mkcert -install`）。**Phase 37 錯誤收尾與全量回歸**——`test_design3_error_paths.py` 把 design3 錯誤表 16 列逐列釘死（17 顆；**首跑 16 綠 1 紅＝揪出真缺陷**：自創實體＋釘選兩次呼叫非原子，釘選失敗留「沒人釘的空實體」且重試同名 409 死路→新增 `photo_repository.create_and_pin_entity()` 兩筆 INSERT 同一交易，rollback 實測以真外鍵違反觸發）；「明確不做」12 項掃碼全過（無自動拍／第二模型／tool calling／Gmail·Calendar／雲端 VLM／DELETE／多使用者／螢幕錄製／實體當資料夾／STUN·TURN／第三方 QR／token 落庫）；端點恰 17、openapi 零 DELETE、SQL 只在 repository 皆有自動化測試釘住。**規格檔於 2026-08-22 由產品負責人指示（另一 session）擴充**：+5 個 feature 檔（歸類照片／釘選實體／建立待辦／瀏覽檔案櫃／無線鏡頭拍攝）＋`上傳照片.feature` 補實體／待辦建議 Rule（已綁已綠）＋`自然語言詢問.feature` 補兩條 P34 Rule 掛 `@未實作`。**該兩條已於 2026-08-24（增量四 Phase 51）摘標**——產品負責人 2026-08-23 核准解除唯讀（`docs/spec/` 的第二次正式解禁，檔頭已留核准紀錄），同時把待辦例子的到期日 `2026-09-18` 改成 **`2026-08-21`**（原本落在問句「這週」＝今天 2026-08-18＋7 天＝2026-08-25 的窗外，例子與自己的問句矛盾）；另在 `tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS` **新增**（不是取代）一個**沒有問號**的鍵 `"這週要交什麼"`（假路由逐字查表，規格的問句沒問號、既有那個鍵有全形問號；既有那個鍵另有兩顆測試靠它查表，只能加不能改）。**全量自此無 skipped（Phase 51 當下 404 passed ＋ 0 skipped；之後 QR 尺寸那顆 +1 ＝ 現在 405）**；`pytest_bdd_apply_tag` 與 binder 的 step 全數保留，日後再標 `@未實作` 仍然有效。`app/` 一行未動。**AI 後端切換（2026-08-22 產品負責人本 session 指示；design3「明確不做」的「雲端 VLM」一項自此正式作廢，其餘不做項全部不動）**：上傳頁、問問題頁與無線鏡頭桌面頁（camera-desk）頁首放**同一顆**「AI 模型：本機｜雲端」開關（行為在 `static/ai_switch.js` 全站唯一一份；`GET`／`PUT /settings/ai-backend`，**端點 17→19**、清點測試已同步；狀態存 `config.AI_BACKEND` 純記憶體、**重啟一律回本機**；沒填 key 切雲端＝422 開關不動）。開關管**四個注入點**、每請求即時分流（`get_vlm`／`get_router`／`get_answerer`／`get_entity_suggester`——單圖／PDF 逐頁／無線鏡頭／詢問／「再建議一個」全部跟著走）：雲端實作 `OllamaCloudVLM`／`OllamaCloudRouter`／`OllamaCloudAnswerer`／`OllamaCloudEntitySuggester` 與本機**共用同一份 prompt**（抽出 `build_route_prompt`／`build_answer_prompt`／`_build_pick_prompt` 兩邊逐字相同）、失敗語意逐一鏡射（看圖重試一次→understood=False→422；路由失敗由 route 節點統一 fallback vector；回答失敗 500 不吞錯；建議失敗回 None 留 log）；**embeddings 一律本機、不歸開關管**（向量須與庫裡既有 bge-m3 同源）。共用底座 `services/ollama_cloud.py`＝全系統唯一建雲端 Client 的地方（官方 `ollama` 套件 `Client(host="https://ollama.com", headers=Bearer OLLAMA_API_KEY, timeout=300)`）。`.env`：`OLLAMA_API_KEY`（產品負責人已自填；改 key 要重啟 uvicorn）、`OLLAMA_CLOUD_VLM_MODEL`／`OLLAMA_CLOUD_LLM_MODEL` 可覆蓋（預設同本機模型名——**但本機自 2026-08-22 改用 MLX 標籤 `gemma4:e2b-mlx` 後，兩者已在 .env 明確釘成 `gemma4`**——⚠ 那句話講的其實**只有文字模型**：`.env` 目前是 `VLM_MODEL=gemma4:e2b`（**看圖那顆沒有 `-mlx`**）、`LLM_MODEL=gemma4:e2b-mlx`，對 `kind=vlm` 的 log 時別對錯：雲端沒有本機的 MLX tag，跟著同名會 404，真煙霧踩過——路由 404 被 fallback 吞掉、回答 404 炸 500，route 節點因此補了 fallback 警告 log）。**真雲端煙霧（2026-08-22 產品負責人實測看圖）**：key 通、單張 1.9 秒（本機同 prompt 2〜5 分鐘），抓到 **ollama.com 對 `format=` 不強制**——gemma4 照 prompt 樣式回 markdown 條列→Pydantic json_invalid→422。修法＝三道保險：`format=` 照帶＋各雲端 prompt 尾接「只准回 JSON」指令（`CLOUD_JSON_INSTRUCTION`／`CLOUD_ROUTE_JSON_INSTRUCTION`／`CLOUD_PICK_JSON_INSTRUCTION`）＋`ollama_cloud.extract_json_object()` 剝圍欄／贅字後再交 Pydantic 驗證——共用 prompt 與黃金檔零影響。+17 tests（`test_ai_backend_switch.py` 5＋vlm 雲端解析 6＋雲端路由/回答 4＋雲端實體建議 2；假 key 必須 ASCII——HTTP header 不吃中文）；看圖已由產品負責人真雲端驗過（修正後續驗）、**問答與實體建議的真雲端端到端待產品負責人手動煙霧**。**增量五成果（`docs/design/design5.md`，2026-08-25 產品負責人對話拍板；Phase 52〜72，52〜64 見 commit `e1d1d5e`／`f1a7e71`、65〜72 於 2026-08-26 完成、已於 2026-08-27 進 commit）**：**階段甲 待決定獨立入口**——待決定從瀏覽頁的 tab **升成頂欄第二格**（新頁 `app/static/pending.html`，網址 `/ui/pending.html`）；全站五頁頁首統一成「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」；`folder_modal.js` 窗頂加原圖（`/photos/{id}/image`，沒原圖畫灰底占位）、「稍後再說」文案改指向待決定頁；`browse.html` 只剩「資料夾｜待辦」兩個分頁、無 query 時預設資料夾。**階段乙 入庫佇列**——`POST /photos` 與 `POST /camera/{token}/photos` 從 **201 改成 202**（body 只有 `{job_id, filename, content_type}`），**「HTTP 回來」從此只代表「檔案收下了」，不代表照片已經存好**；檔案先落 `data/staging/{job_id}.jpg|.png|.pdf`（**影像位元組絕不進 Redis／Celery 參數**，任務只帶 `job_id`），再建 job、再丟 Celery；worker（`app/celery_app.py` 的 `ingest_task` → `app/services/ingest_job.py` 的 `run_ingest_job()`）把「看圖 → 轉向量 → INSERT 收件箱 → 存原圖與縮圖」整條搬過去，**同一張圖含第一次共送 VLM 3 次**（看不懂與連線失敗都算、embedding 失敗也算），3 次都失敗＝整筆拿掉（刪 staging、不留 `photo` 列、job 標 `failed`）；PDF **一檔一任務、以頁為重試單位**（每頁各 3 次、失敗跳過該頁、0 頁成功才整筆失敗）；崩潰重送靠 JobStore 的 `photo_ids`／`pages_done` 做冪等（**不用** Celery autoretry）；新增 `GET /ingest-jobs`（回進行中與失敗的任務＋`pending_count`＝收件箱照片數）與 `POST /ingest-jobs/{job_id}/dismiss`（只准關 `failed`；404／409），**端點 20→22、openapi 仍零 DELETE**；`photo` 表冪等遷移（`db/migrate_design5.sql`）加 `suggested_entity`／`suggested_task_title`／`suggested_task_due` 三欄（design5 D16：建議隨入庫落庫，人確認才寫 `entity`／`photo_entity`／`task`），`GET /folders/{id}` 的照片摘要**五鍵→八鍵**；`compose.yaml` 加 `redis`（官方 Redis 7 alpine、AOF、named volume `personaldocai_redisdata`、只綁 `127.0.0.1`）與 `worker`（**同一份 app 映像**、`--concurrency=2`、不掛憑證、**沒有 `--reload`**——改 .py 要 `restart worker`）；真容器雲端煙霧全過（202 實測 0.27 秒、worker log `kind=vlm backend=cloud` 1.1 秒＋`kind=embed backend=local`、照片 #53 進收件箱帶 `suggested_category`、成功＝job 刪掉、壞檔恰 3 次重試留 failed 列、AOF 重啟不掉、staging 收乾淨）。**階段丙 非同步 UX**——上傳頁 `<input multiple>`（圖與 PDF 可混選、每檔各一個 POST 順序送）、拿掉 201 開鏈；`app/static/progress_panel.js` 全站唯一一份進度面板（2 秒輪詢 `GET /ingest-jobs`，四種狀態、× dismiss、清單空了自動收起、頂欄 N 也由它更新）掛在五個頁面；鏡頭手機端 202 即可再拍（純本地窄條計數、不打 API）、桌面端刪掉「GET latest → 開彈窗鏈」改為計數＋面板；**待決定頁改走完整三關**（抽屜 → 實體 → **有待辦建議才開**待辦窗；三關的建議全部讀 D16 落庫的欄位，**不再看第二次圖**），`app/static/classify_chain.js` 零呼叫者後刪除。錯誤收尾：design5 §8 錯誤表 10 列逐列清點到有測試把關（大多在 Phase 59〜64 各自的測試檔，逐列對照表見 phase-71 §4.1；`tests/integration/test_design5_error_paths.py` 共 **20 顆**＝補三個真缺口——寫**原圖**失敗清半成品、JobStore 掛掉 500 且刪 staging、`analyzing`／`retrying` 也不准 dismiss——再把 §3「不做」9 項＋§0 四條禁止＋§1.2 被否決 13 列變成掃碼斷言（`information_schema` 證明 `photo` 表**沒有**處理狀態欄與 `job_id` 欄、`inspect.signature` 證明任務只吃 `job_id`、compose 掃 `--concurrency=2`／redis 沒發佈到區網／沒有 flower 與 ollama 服務、前端零 `alert(`／`confirm(`／`prompt(`、`.cd-qr svg` 的 `max-width` ≥ 20rem）。**零依賴實證多一輪**：`CELERY_BROKER_URL` 指死埠跑全量顆數不變（實證 pytest 零 Redis 依賴，與既有 `OLLAMA_BASE_URL` 指死埠同一手法）。規格檔於 2026-08-26 經產品負責人**第三次核准解除唯讀**（dev-prompt `phase0826.md` 明示指名執行 phase-72，比照 ★G1 前例），改四份 `.feature`（`上傳照片`：「上傳後儲存」→「受理後分析成功才儲存」、VLM 失敗改「連續三次」、刪 `Then 操作失敗`、加「可一次多檔」`#TODO` Rule；`無線鏡頭拍攝`：快門後進佇列、加「桌面不開彈窗」`#TODO` Rule；`歸類照片`：待決定**有**採用建議（D16 推翻 design2 D5）；`瀏覽檔案櫃`：瀏覽頁預設分頁改資料夾），`自然語言詢問`／`釘選實體`／`建立待辦` **一字未動**。全量測試 **543 passed ＋ 0 skipped**（增量五收官；增量六 Phase 74〜80 之後為 **613**，見下一段）。pytest 測試自 Phase 03 起以 TDD 建立：`tests/unit/`＋`tests/integration/`（目前 **613 passed＋0 skipped**（2026-09-01）；另有兩條死埠實證——`CELERY_BROKER_URL`／`OLLAMA_BASE_URL` 指死埠顆數不變，兩個一起指也驗過），`tests/conftest.py` 自動把 `DATABASE_URL` 切到 `PersonalDocAI_test`，並以**五道 autouse 安全網**擋掉危險預設：`reset_tables`（每測清空 `photo`＋`folder`＋`entity`＋`folder_correction`（CASCADE 連帶 `photo_entity`／`task`）並重播六筆資料夾種子，folder id 保證 1〜6；**絕不清正式庫**）、`wire_fake_ai`（AI／時鐘全部換假件；**pytest 絕不呼叫真 Ollama**——本機 Ollama 常駐，忘記覆寫會誤觸真模型推論；真模型只做手動煙霧，不進驗收與 CI）、`isolated_data_dir`（`config.DATA_DIR` 指到 tmp_path；**pytest 絕不寫專案 `data/`**）、`wire_memory_job_store`（增量五 Phase 57 加、65 加長：JobStore 換 `InMemoryJobStore`（dependency_overrides＋monkeypatch 雙管，lifespan 掃把與 Celery 任務的**直接呼叫**也攔得到）、派工換記帳假件；**pytest 絕不連真 Redis、絕不啟動 Celery**）、`wire_fake_cloud`（增量六 Phase 77 加：`config.CLOUD_ROUTE` 蓋成 `off`、`get_cloud_route` 以 dependency_overrides＋monkeypatch 雙管換成 `CloudRouteOff()`、`AWS_ENDPOINT_URL` 指死埠 `http://127.0.0.1:9`；**pytest 絕不連真 AWS**；Phase 78 起 `wire_fake_ai` 另以 monkeypatch 雙名蓋 `get_privacy_gate` 與 `build_privacy_gate_for_backend`、`跑完任務()` 走 `run_gated_ingest_job`）。假件與真圖工具（`make_png_bytes`／`make_jpeg_bytes`——Pillow 會真的解碼，假位元組會炸 `UnidentifiedImageError`）在 `tests/fakes.py`。**增量四成果（`docs/design/design4.md`，2026-08-23 產品負責人 grill 拍板；Phase 38〜51）**：**階段甲 照片詳情（Phase 38〜40，已 commit `507a18f`）**——新增 `GET /photos/{id}`（`PhotoDetailOut`：id／text／metadata 四欄／thumbnail_url／image_url／uploaded_at；**端點 19→20**）、新建 `static/photo_detail_modal.js`（唯讀窗，**沒有**改資料夾的按鈕——design2 的定案不可逆原封不動）、資料夾牆的照片改成可點、待辦列拿掉 `target="_blank"` 改開同一顆窗。**階段乙 AI 計時 log（Phase 41〜43，同 commit）**——新建 `services/ai_timing.py`（context manager），五種 kind（`vlm`／`embed`／`route`／`answer`／`entity_suggest`）在**每一次真的打到模型**時留下前後兩行同格式訊息（`AI 開始 kind=… backend=… model=…` ／ `AI 結束 … elapsed_s=… ok=…`），本機與雲端都接。**Phase 44** 把 design4 §9 錯誤表 1〜5 逐列釘死並產出 G1 驗收包（`docs/plan/report/2026-08-23-G1驗收包-請產品負責人確認.md`；顆數 358→**402**）。**★ 閘門 G1 於 2026-08-24 由產品負責人以 dev-prompt `phase0824.md` 明示通過。** **階段丙 Docker 常駐與正式庫遷移（Phase 45〜50，2026-08-24，依指示未 commit）**——`compose.yaml`（`db` ＝ `pgvector/pgvector:pg17`，發佈 `127.0.0.1:5433`、named volume `personaldocai_pgdata`、`pg_isready` healthcheck；`app` ＝ 自建映像，發佈 `0.0.0.0:8000` HTTPS、`DATABASE_URL=postgresql://postgres@db:5432/…` 與 `OLLAMA_BASE_URL=http://host.docker.internal:11434` 兩個 `environment` 覆蓋 `.env`、三個 bind-mount（`data`／`certs`／`.env`）、`depends_on: service_healthy`、兩者 `restart: unless-stopped`）＋`Dockerfile`（`python:3.12-slim`，**CMD 沒有 `--reload`**）＋`.dockerignore`＋`db/docker-init/01-create-test-db.sql`＋`compose.dev.yaml`（開發 overlay：`--reload`＋多掛 `./app`＋**`restart: "no"`**）。正式庫用 `pg_dump -Fc` → `pg_restore` 搬家，**閘門 G2 的 `diff` 逐字零差異**（37 列照片、10 個資料夾、vector extension、1024 維全數對上）；`.env` 與 `tests/conftest.py` 的連線字串改帶帳號 `postgres@`（Docker 官方映像強制要有帳號），`~/.zshrc` 補 `PGUSER=postgres`＋`PGHOST=127.0.0.1`（Docker 只發佈 TCP 埠、沒有 Unix socket 檔）。brew `postgresql@17` 已 `stop`（**資料目錄 `/opt/homebrew/var/postgresql@17` 保留＝後悔藥第 1 層，第一個穩定週期內不准刪**；`postgresql@14` 於 5432 仍是別的專案的，全程沒碰）。Docker Desktop `AutoStart` 與 Ollama 登入項目都已開，重開 Docker Desktop 實測兩個容器**自己回來**。⚠ **本機真模型很慢而且不要並行**：看圖 64〜88 秒、路由 138 秒、回答 92 秒；Phase 48 曾把上傳與詢問同時打，把 db container 壓垮（postmaster 花 2 分鐘才殺得掉子行程、WAL 自動復原、**資料零損失**），改成順序執行即 100% 正常。⚠ **鏡頭 QR 的 IP 判準已更新**：不要用「是不是 192.168 開頭」判斷——本機區網就是 `172.29.93.122`，而用 `localhost` 開桌面頁時猜出來的 Docker 網段是 `172.24.0.3`，**兩個都是 172.x**；唯一可靠的判準是「**QR 網址的 host 逐字等於 `ipconfig getifaddr en0` 的輸出**」（已實測：用區網 IP 開＝逐字相同、用 `127.0.0.1` 開＝猜成 Docker 網段）。憑證的 SAN 把 IP 寫死，區網 IP 換了要 `mkcert` 重簽並 `docker compose restart app`。

**增量六前半成果（`docs/design/design6.md`，產品負責人 2026-08-31 拍板、2026-09-01 改判「閘門只用 VLM 短問、不看檔名、跟頁首開關」；Phase 74〜80 於 2026-09-01 完成，**74〜86 已由產品負責人 commit（`bb3921a`）**；★G1 已過；87〜91 於 2026-09-02〜03 完成並已 commit；**92-A**（CPU 機 t3.xlarge）已建、Demo 2／2b 通過、日常 Stop；**92-B** 等 G and VT 配額；93〜95 尚未開始（★G3 前不做 OIDC／CD）**：**階段甲 隱私閘門與 fallback**——新檔 `app/services/privacy_gate.py`（`Verdict` 三分類 SENSITIVE／NON_SENSITIVE／UNCERTAIN、`PrivacyJudgement{sensitive, confident}`、`judgement_to_verdict`（sensitive 即使沒把握也算敏感）、`VlmGate`＝唯一真閘門：讀檔→PDF 只渲染第一頁→`shrink_for_model` 縮到長邊 ≤512 轉 PNG→`OllamaPrivacyModel.judge()` 短問（`PRIVACY_PROMPT` 只准回兩欄；雲端接**自己家的** `_CLOUD_JSON_INSTRUCTION`，不可借 `vlm_service.CLOUD_JSON_INSTRUCTION`）→三分類；**每條失敗路徑回 UNCERTAIN 前必留 warning**；`del filename`＝不看檔名）；`ai_timing` 多一種 kind `privacy`（backend／model 跟 vlm 同一組）。**閘門跟頁首開關走但 worker 行程的 `config.AI_BACKEND` 永遠是 local**——所以 `dependencies.build_privacy_gate_for_backend(ai_backend)` 吃入列快照 `job["ai_backend"]`（總覽 §10.2 追認項 S；煙霧實證 worker log 印 `kind=privacy backend=cloud`），`get_privacy_gate()` 只給 web 行程／測試。`ingest_job.py` 純重構抽出五個公開積木（`PromptContext`＋`load_prompt_context`／`embed_understanding`／`insert_photo_with_files`／`finish_image_job`／`fail_job`；`run_ingest_job` 簽章與 log 字樣零改變）。新檔 `app/services/cloud_ingest.py`（**零 boto3**：`MailboxMessage`、`CloudMailbox` 14 支 Protocol、`RemoteProbe`／`AlwaysRunning`、`CloudRouteOff`（available 恆 False、其餘 raise）、`build_context`（context.json 恰三鍵）、`CloudRoute`（`submit` 順序鐵律 context.json→input.*→jobs 訊息、`wait_result` 五條規則（每次長輪詢 ≤20 秒、別人的訊息還回去或當殘訊息連 S3 一起清、deadline→None）、`fetch_result`、`cleanup` 刪三鍵））；config 九個設定（`CLOUD_ROUTE=off` 預設、`AWS_REGION`、`S3_BUCKET`、兩條 SQS URL、`EC2_WORKER_INSTANCE_ID`、`EC2_PROBE_TTL_SECONDS`、`CLOUD_RESULT_TIMEOUT_SECONDS`、`WORKER_VERSION`；AWS 金鑰與 `AWS_ENDPOINT_URL` 不進 config）；`IngestJob` 加 `privacy`／`route` 兩欄（`create()` 不預填，`GET /ingest-jobs` 回應不變）。新檔 `app/services/gated_ingest.py` 的 `run_gated_ingest_job()` 成為 **Celery 任務的新入口**（`celery_app.ingest_task` 多組 `gate`／`cloud` 兩個零件）：一進門 analyzing → `route=local` 崩潰重送不再問閘門 → 問閘門、寫 `privacy` → 非 NON_SENSITIVE 走本機（log `route=local verdict=…`）→ `cloud.available()` False 或丟例外 → `fallback=local reason=remote_unavailable` → 只有非敏感＋遠端可用才 `route=cloud`：submit 失敗→`reason=submit_failed`、等結果逾時或信箱丟例外→`reason=result_timeout`、工人說看不懂→`fail_job`（不是 fallback）、成功→本機 `embed_understanding`（只重算向量）→ `insert_photo_with_files` → **立刻寫 photo_ids** → cleanup → `finish_image_job`；`route=cloud` 崩潰重送 → `fetch_result` 有就落庫前重讀 store 再落庫、沒有就 `reason=redelivered_without_result` 走本機（D17 冪等）。四個 `fallback=local reason=…` 字樣是 design6 §2.1 契約。**測試 543→613**（+70：74 11、75 12、76 4、77 12、78 9、79 11、80 11；含 review 裁決多加的 4 顆）、**0 skipped、端點恆 22**、`docs/spec/`／compose／正式庫零改動；conftest **第五道 autouse 安全網 `wire_fake_cloud`**（`CLOUD_ROUTE` 蓋 off、`get_cloud_route` 雙管換 `CloudRouteOff`、`AWS_ENDPOINT_URL` 指死埠）→ 零依賴實證改成**三死埠一起指**顆數不變。假件 `FakePrivacyGate`／`FakePrivacyModel`／`FakeMailbox`（一顆扮 S3＋兩條佇列、帶 `calls` 流水帳）／`FakeProbe`／`ScriptedProbe`／`FakeCloudRoute`／`fake_worker_process_one` 在 `tests/fakes.py`。**Phase 78 真模型煙霧**：閘門短問本機 gemma4:e2b 99.6 秒（首呼叫含載入）／雲端 0.7 秒，合成測試圖 photo #63／#64 留在正式庫待決定。⚠ **`POST /photos` 之後 worker 多做一次 VLM 短問**（本機約 1〜2 分鐘）才進既有流程，這是產品負責人接受的成本；`CLOUD_ROUTE=off` 時使用者觀感與增量五逐字相同。

**增量六後半成果（Phase 81〜91，2026-09-02〜03；81〜86 已 commit `bb3921a`，87〜91 已 commit）**：**81** PDF 走雲端路（`gated_ingest._store_pdf_result`、`render_pages(max_pages=)`、閘門只渲染第一頁）。**82〜86（乙／丙）** AWS 開戶與兩個 IAM 身分（admin＝default profile 給人打 `aws`、`personaldocai-mac`＝`.env` 的最小權限 key 給程式）、`app/services/aws_mailbox.py`（**全系統唯一 import boto3 的地方**，14 支方法照 `CloudMailbox` Protocol）、東京 S3 bucket `personaldocai-mailbox-<後六碼>`（BPA／SSE-S3／`documents/` 2 天 Lifecycle）、SQS `personaldocai-jobs`（Visibility 900）／`personaldocai-results`（30）、`scripts/aws_check.py s3 sqs`、`get_cloud_route()` 的 `assume` 分支＋真 AWS 逾時煙霧。**87〜88（丁）** 新套件 `app/workers/`：`cloud_worker.py` 是寄物櫃另一頭的**雲端看圖工人**——`process_job_message(mailbox, message, vlm)` 六條規則（result.json 已在→只補送 results；壞 s3_key／input 不在→只刪訊息；context.json 缺→三份空清單；看圖最多 `VLM_MAX_ATTEMPTS` 次、PDF 逐頁各算；**先 PutObject result.json → SendMessage results → DeleteMessage jobs** 順序鐵律）、`run_forever`（長輪詢 20 秒、單則例外不刪訊息、receive 失敗退避 5 秒且退避前先看停止旗標）、SIGTERM／SIGINT 只豎旗標做完手上那則才退、`python -m app.workers.cloud_worker` 進入點；工人**零資料庫、零 embedding、零 Celery／Redis、零 `app.dependencies`**（有 `ast` 掃碼守），計時 log 由工人自己包 `log_ai("vlm", target=vlm_timing_target(vlm))`。⚠ **`python -m` 陷阱（2026-09-03 真跑抓到）**：模組以 `__main__` 執行，`logging.getLogger(__name__)` 不在 `app` logger 樹下、INFO 全被吞——所以工人的 logger 是字面名 `"app.workers.cloud_worker"`，並有一顆 subprocess 測試真的用 `-m` 跑來釘住。Mac 端到端（真 S3／SQS／Ollama Cloud）通過：合成收據 9 秒走完雲端路入庫、合成證件 `route=local verdict=SENSITIVE` 零 S3、SIGTERM 優雅退。**89（戊）** `cloud_ingest.Ec2Probe`（`instance_state()=="running"` 才 True、TTL 60 秒快取且失敗也進快取、任何例外→False、`instance_id` 空→零呼叫、log 只印實例 ID 尾 4 碼）＋ `dependencies._ec2_cloud_route()`（`lru_cache` 整個行程一條）→ `CLOUD_ROUTE` 的 off／assume／ec2 三種**全部接上**。**90** `Dockerfile` 三 stage（`base` → `cloud-worker`（`ARG GIT_SHA`／`ENV WORKER_VERSION`、exec-form CMD `python -m app.workers.cloud_worker`、無 EXPOSE）→ **`app` 放最後**所以 compose 零改動）、`.dockerignore` 加 `deploy/`、新檔 `tests/integration/test_design6_error_paths.py`；controller 建出 arm64 映像 `personaldocai-worker:local`、容器端到端通過（`worker_version=bb3921a`）、`docker compose config` 前後 diff 空。**★G2 依裁決 R2 條件式通過**（dev-prompt 明示做到 91 ＋ 十條憑據齊全；產品負責人可事後否決，刪四樣免費資源即可）。**91** AWS 上多了四樣**免費**東西：SG `personaldocai-worker-sg`（inbound `[]`、egress 只 tcp 443）、S3 Gateway VPC endpoint、IAM role＋同名 instance profile `personaldocai-worker-role`（inline `personaldocai-worker-inline` 最小權限＋`AmazonSSMManagedInstanceCore`）、ECR `personaldocai-worker`（tag `bb3921a`＋`latest`，arm64）；進 git 的五個檔 `deploy/aws/worker-role-{trust,policy}.json`（只有 `<ACCOUNT_ID>`／`<AWS_REGION>`／`<S3_BUCKET>` 佔位符）、`deploy/ec2/{user-data.sh,personaldocai-worker.service,worker.env.example}`（unit 與 user-data 內嵌段逐字相同；env 範本只有變數名、**值不要加引號**——systemd 剝引號、docker 不剝）；`.env` 加空的 `EC2_WORKER_INSTANCE_ID=`。**92-A CPU 機已建並驗收**（日常 Stop；92-B GPU 機尚未開）。⚠ 兩個實操陷阱：`docker login` 到 ECR 第一次可能逾時（Docker Desktop 內建代理暫時卡住，重試即可）；zsh 裡 `"$ECR_URI:latest"` 的 `:l` 是小寫修飾子（會變成 `…workeratest`），要寫 `${ECR_URI}:latest`。**測試 644→679、0 skipped、三死埠 679、端點恆 22**；規格區／compose／db／前端零改動；正式庫 70 張（本輪煙霧 +4）。⚠ 2026-09-03 工作樹另有產品負責人的 `docs/design/design7.md`（增量七：雲端工人改 Lambda），本輪未讀未動。

**2026-09-03 改判：EC2 改 GPU 機自裝 Ollama（design6 D12 作廢；總覽 §10.2 追認項 T；產品負責人拍板「留著開關」）**：工人看圖後端由 `config.WORKER_VLM_BACKEND` 決定——`cloud`（預設；留空或不填也算）＝ollama.com、`local`＝**工人所在那台機器**的 Ollama（GPU EC2 用這個；`OLLAMA_BASE_URL`／`VLM_MODEL`，不需要 `OLLAMA_API_KEY`）；`cloud_worker.build_worker_vlm()` 分流、打錯字當場炸、啟動行尾多 `vlm=… model=…`；`process_job_message` 六規則與 S3／SQS 契約一字未動。`deploy/ec2/`：Ollama 跑 host（官方 `ollama.service`、只聽 127.0.0.1），工人容器 `docker run --network host`，unit 加 `After=/Wants=ollama.service`＋等 `/api/tags` 120 秒的 `ExecStartPre`（`{1..60}`）；user-data 先裝 unit＋enable 再裝 Ollama＋`ollama pull gemma4:e2b`（非致命）；`worker.env.example` 多 `WORKER_VLM_BACKEND`／`OLLAMA_BASE_URL`／`VLM_MODEL`（值不加引號）。Mac 上 `WORKER_VLM_BACKEND=local` 完整回合實測通過（本機看圖 90 秒、`雲端結果已入庫 #73`）。ECR `latest` 改推**多架構**（amd64＋arm64）manifest、tag `bb3921a-dirty`（未 commit）。**2026-09-03 再改判：phase-92 拆兩段（總覽 §10.2 追認項 U）**——**92-A（現在做）** `t3.xlarge`（x86_64、一般 AL2023、**30 GB gp3**、`worker.env` 填 `WORKER_VLM_BACKEND=cloud`），把整條 AWS 流程與 Demo 2／2b 驗完，**收工 Stop**（30 GB ≈ $2.9／月，在 $5 Budget 內，留給 Phase 94 的 Demo 3）；前置只要 Standard 配額 `L-1216C47A`（本帳號實查 **8 vCPU**，新帳號 Standard 預設常是 5，**不必申請**）。**92-B（配額核准後）** 先 Terminate 92-A → `g4dn.xlarge`＋Deep Learning Base OSS NVIDIA GPU AMI＋**80 GB gp3**＋`local` → 多驗 `nvidia-smi`／`ollama ps` 兩關 → 測完 **Terminate**（80 GB 停著 ≈ $7.7／月，超過 Budget）。**★G3 移到 92-A 之後**（93／94／95 都不依賴 GPU）。**G and VT 配額 `L-DB2E81BA` 目前 0、申請已送出、狀態 `CASE_OPENED`——不要重送**。兩台**都是 x86_64**，多架構映像那條不變；兩段共用同一份 `deploy/ec2/` 三檔。⚠ 92-A 若要在同一台試 `local` 硬跑 CPU 推論，**必須先把 Mac `.env` 的 `CLOUD_RESULT_TIMEOUT_SECONDS` 從 300 暫調 900 並 restart worker，做完改回 300**（否則本機先 `fallback=local reason=result_timeout`、工人稍後放好的 `result.json` 變孤兒）。phase-92-A 已實作並驗收；93／94／95 尚未開始。要改回純雲端推論：`worker.env` 留空 `WORKER_VLM_BACKEND` 即可，零程式碼。啟動時四個看圖設定（cloud：`OLLAMA_API_KEY`＋`OLLAMA_CLOUD_VLM_MODEL`；local：`OLLAMA_BASE_URL`＋`VLM_MODEL`）都會檢查，缺了大聲退出。測試 **690**（2026-09-03 晚 review 補一顆 `test_AWS_REGION留空等於東京`）。

## 指令

```bash
# 每次開工（每個新終端機視窗都要）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 安裝／更新依賴（本專案用 uv 管理套件）
uv pip install -r requirements.txt
# ⚠ **已知落差（2026-08-24 code review 發現，尚未處理）**：`requirements.txt` 全部是 `>=`，
#   而容器映像是在 build 當下才解析版本的，所以「host 的 .venv」與「容器裡」會慢慢分岔。
#   實測：langchain-core host 1.5.6 / container 1.6.0；uvicorn host 0.52.3 / container 0.52.4。
#   意思是 `pytest -q` 全綠**驗的是 host 那一份環境，不等於驗過實際跑的映像**。
#   目前的取捨：side project 先不釘版；代價是「重建映像」要當成需要手動煙霧一次的動作
#   （`docker compose build app` 之後至少跑一次上傳＋問一句話）。
#   真的要根治：把 .venv 的 `pip freeze` 釘進 requirements（或另開 requirements.lock）。

# ── 啟動服務（2026-08-24 增量四起：跑在 Docker 裡，不再手動打 uvicorn）──────
#
# ⚠️ **`http://localhost:8000` 從此開不起來了（會完全連不上，curl 回 000）。**
#    容器的啟動指令固定帶 --ssl-keyfile／--ssl-certfile（寫在 Dockerfile 的 CMD），
#    因為無線鏡頭需要「安全來源」手機才給鏡頭權限，而一個行程沒辦法同時聽 HTTP 與 HTTPS。
#    以前手動跑 `uvicorn --reload --port 8000`（純 HTTP）的習慣要改掉——**網址開頭多一個 s**：
#      ✗ http://localhost:8000/
#      ✓ https://localhost:8000/
#    這台 Mac 已經 mkcert -install 過，所以 https://localhost 與 https://127.0.0.1
#    **不會跳憑證警告**（實測不帶 -k 驗證也是 200）。會跳警告的只有「用區網 IP 開」
#    而且憑證還沒重簽成當下 IP 的時候。
#
# 網址一律 https://localhost:8000 或 https://127.0.0.1:8000；API 文件在 /docs

# 常駐（開機也是用這一份自動拉起；一次四個服務 db／redis／app／worker，沒有 --reload）
docker compose -f compose.yaml up -d

# ⚠ 改過 requirements.txt 之後一定要帶 --build，否則新套件不會進映像
#   （worker 會噴 ModuleNotFoundError: No module named 'celery' 然後一直重啟）
docker compose -f compose.yaml up -d --build

# 日常開發（熱重載；兩份疊加，compose.dev.yaml 一定放後面）
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
#   logs -f ＝跟著看，Ctrl+C 只離開 log，容器繼續跑
#   worker ＝ 背景分析照片的那個行程；kind=vlm／kind=embed 的計時 log 在它那邊，不在 app

# 現在跑的是哪一種：看 COMMAND 欄（app 有沒有 --reload、worker 有沒有 --concurrency=2）
# --no-trunc 不能省：不加的話 COMMAND 只印開頭 20 個字左右，結尾那些旗標根本不會顯示
docker compose ps --no-trunc

# 切換（切換當下 app 一定重啟一次 → 鏡頭 token 清空、QR 要重產）
docker compose -f compose.yaml stop app worker                # 常駐 → 開發（第一步）
docker compose -f compose.yaml -f compose.dev.yaml up -d      # 常駐 → 開發（第二步）
docker compose -f compose.yaml -f compose.dev.yaml stop       # 開發 → 常駐（第一步）
docker compose -f compose.yaml up -d                          # 開發 → 常駐（第二步）

# ⛔ 會弄丟正式庫的四種操作（volume `personaldocai_pgdata` 裡是**正本**）：
#    1. `docker compose down -v`（-v ＝連 volume 一起刪）。停服務一律用 `docker compose stop`
#    2. `docker system prune --volumes` / `docker volume prune -a`
#       ——刪掉「沒有 container 指著」的具名 volume，也就是任何一次 `docker compose down` 之後
#       都危險；Docker Desktop 的 "Reset to factory defaults" 與 Volumes 分頁的垃圾桶同理
#    3. `docker volume rm personaldocai_pgdata`
#    4. 把 `compose.yaml` 的映像 tag 從 pg17 換成 pg18（pg18 的 PGDATA 路徑不一樣，
#       掛載點不再是 PGDATA → initdb 建新空叢集 → 看起來像資料全沒了。詳見 compose.yaml 的註解）
#    刪之前一定先備份（本檔下面有「日常備份」兩種寫法）。
#
# ── 增量五新增：第二個 volume `personaldocai_redisdata`（Redis 的 AOF）──
#   ⚠ 它**不是**正式庫，兩者差很多：
#     personaldocai_pgdata     ← 正式庫（照片列、資料夾、實體、待辦、向量）。丟了＝災難
#     personaldocai_redisdata  ← 進度列、失敗列、還沒做完的任務。丟了只丟「還沒分析完
#                                的那幾張」，已入庫的照片一張都不會少（正本在 pgdata ＋
#                                data/photos）。那幾張重新上傳即可；它們在 data/staging
#                                的暫存檔會由 24 小時掃把自動清掉
#   所以 `down -v` 仍然絕對禁止（會兩個一起刪）；但真的只需要清 Redis 時，
#   `docker volume rm personaldocai_redisdata` 是可接受的損失——**前提是當下沒有任務在跑**。
#
# 備份不必管 Redis：日常備份（下面那兩種寫法）只倒 Postgres，
# 因為 Redis 裡沒有任何「丟了就再也拿不回來」的東西。

# ⚠ `restart: unless-stopped` 的字面意思是「**除非你自己停過**」：
#    用 `docker compose stop` 停掉的容器，重開機／重開 Docker Desktop **不會**自己回來。
#    「晚上收工 stop、早上開機」的話，要自己 `docker compose -f compose.yaml up -d` 再拉起來。

# ⚠ `up -d` **不會**重建映像。改了 app/ 底下的程式碼之後切回常駐模式，跑的還是舊映像
#    （開發模式是 bind-mount 所以看得到新碼，常駐模式的程式在映像裡）。
#    要讓新碼進常駐：`docker compose -f compose.yaml up -d --build`

# 改了東西要怎麼生效（--reload 救不了的五種情況）
#   改 app/ 的 .py   → **app 會自己 reload，但 worker 不會**（Celery 沒有這種東西）。
#                      症狀：HTTP 行為已是新碼、照片分析卻還是舊行為，而且完全不報錯。
#                      docker compose -f compose.yaml -f compose.dev.yaml restart worker
#   改 .env          → docker compose -f compose.yaml -f compose.dev.yaml restart app worker
#                      ⚠ 但 DATABASE_URL／OLLAMA_BASE_URL／CELERY_BROKER_URL 這三個
#                        由 compose.yaml 的 environment 覆蓋（app 與 worker 都是），
#                        在容器裡改 .env 的這三行怎麼 restart 都不會變（刻意的）
#   改 requirements  → docker compose build app，再 up -d（worker 用同一份映像，一起更新）
#   改 certs/        → restart app（worker 不聽 HTTPS，用不到憑證）
#   正在配對鏡頭     → reload ＝ token 清空，重產 QR 重掃一次

# ── 增量五（2026-08-26 起）：多了 redis 與 worker 兩個服務 ──────────────
#
# `docker compose up -d` 現在會一次拉起**四個**服務：
#   db      PostgreSQL 17 ＋ pgvector（正式庫的正本，發佈 127.0.0.1:5433）
#   redis   任務佇列（broker）＋ 進度狀態。**只綁 127.0.0.1，不對區網開放**
#   app     FastAPI（HTTPS :8000）——只收檔、入列，不看圖
#   worker  Celery（--concurrency=2）——真正看圖、轉向量、寫入資料庫的是它
#
# 常駐與開發模式的指令**完全沒變**（compose.yaml 裡多兩個服務而已）。
# 看兩個服務的 log（分析進度印在 worker 那邊）：
#   docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
# 確認 worker 真的是兩個子行程（--no-trunc 不能省，不加看不到結尾的旗標）：
#   docker compose ps --no-trunc | grep worker      # COMMAND 欄要有 --concurrency=2
#
# ⚠ **202 不是 201。** `POST /photos` 與 `POST /camera/{token}/photos` 從增量五起回
#    **202 Accepted**，body 只有 {job_id, filename, content_type}。
#    202 的意思是「**檔案收下了、排進佇列了**」，**不是**「照片已經存好了」——
#    這一刻資料庫的 photo 表列數**不變**、待決定牆上也不會出現任何東西。
#    要確認一個檔案到底進去了沒，看這支：
#      curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
#    jobs 陣列裡**沒有**它 ＝ 分析成功（成功的 job 會被刪掉）；
#    status 是 failed ＝ 三次都失敗、庫裡沒有這張照片（按面板上的 × 關掉那一列）。
#
# ── data/staging/：暫存區（增量五新增）───────────────────────────────
# 收下但還沒分析完的原始檔住在這裡，檔名就是 job_id：
#   data/staging/{job_id}.jpg | .png | .pdf
# 成功入庫或最終失敗，這個檔都會被刪掉。所以**正常情況下它應該接近是空的**。
# 超過 24 小時還在的檔案 ＝ 孤兒（多半是 worker 在跑到一半時整台機器關掉了）。
# app 與 worker 啟動時會自己掃一次、把孤兒清掉；想手動看有沒有殘留：
#   find data/staging -type f -mmin +1440
#   ↑ 預期沒有輸出。有輸出也不必緊張——那些檔案沒有任何一列資料庫指著它們，
#     直接刪掉是安全的（照片正本在 data/photos/，不在這裡）。
# ⚠ 備份的時候 data/staging/ **不必**帶上（那是半成品，不是資料）。
#    要備份的仍然是資料庫 ＋ data/photos/ ＋ data/thumbs/。

# ── 無線鏡頭的 HTTPS 憑證（Phase 36；每台機器只做一次）────────────────
# 為什麼一定要 HTTPS：手機瀏覽器只在「安全來源」才給 getUserMedia（鏡頭）權限，
# http://192.168.x.x:8000 一定開不了鏡頭。這是瀏覽器規格，不是設定問題。
# ⚠ 重新 clone 之後**先** `touch .env`（再照 .env.example 之類的內容填）：
#    `.env` 不入版控，而 compose.yaml 有一條 `./.env:/app/.env` 的 bind-mount——
#    來源檔不存在時 Docker **不會報錯，它會在專案根目錄默默建一個叫 .env 的「資料夾」**，
#    然後容器裡讀到空的、`load_dotenv()` 靜靜地什麼都沒載入（模型名、OLLAMA_API_KEY 全空）。
brew install mkcert                       # 產本機自簽憑證的工具
mkcert -install                           # 讓這台 Mac 信任 mkcert 的根憑證（會問密碼）
mkdir -p certs                            # certs/ 已入 .gitignore，重新 clone 後不存在
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(ipconfig getifaddr en0) localhost 127.0.0.1
# 憑證要「重簽」的唯一情境：本機區網 IP 換了（憑證把 IP 寫死在 SAN 裡）。
# 先檢查現在的憑證涵蓋哪些位址，再決定要不要重簽：
#   openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
#   ipconfig getifaddr en0
#   ↑ 上面那份清單裡沒有下面這個 IP 就要重簽。重簽完 `docker compose restart app`
#     （HTTPS 行程在啟動時就把憑證讀進記憶體了，換檔不會自動生效）。
# mkcert -install 晚一步做不影響已產出的憑證——信任的是根憑證，往回回溯就生效。
# iPhone 也要信任同一張根憑證（一次性，換手機才要再做）：
#   1. open "$(mkcert -CAROOT)"            # ＝ ~/Library/Application Support/mkcert
#   2. 把裡面的 rootCA.pem 用 AirDrop 傳到 iPhone（rootCA-key.pem 不要傳）
#   3. iPhone：設定 →（最上方）已下載描述檔 → 安裝 → 輸入密碼 → 安裝
#      找不到那一列時：設定 → 一般 → VPN 與裝置管理 →（描述檔）→ 安裝
#   4. iPhone：設定 → 一般 → 關於 → 憑證信任設定 → 把 mkcert 那一列打開「完全信任」
#      ⚠ 少了第 4 步 Safari 仍會擋，而且錯誤訊息看起來像「網路怪怪的」，很難聯想。

# HTTPS 怎麼起：2026-08-24 起**不必自己打 uvicorn** ——憑證由 compose bind-mount 進容器
# （`./certs:/app/certs`），啟動指令寫在 `Dockerfile` 的 CMD（常駐）與 `compose.dev.yaml`
# 的 command（開發），兩者都已帶 --ssl-keyfile／--ssl-certfile 與 --host 0.0.0.0
# （0.0.0.0 ＝也聽區網那張網卡，手機才連得到）。上面「啟動服務」那段的指令就夠了。
#
# 電腦要用 https://<本機區網IP>:8000/ui/camera-desk.html 開鏡頭桌面頁（**不要用 localhost**，
# 那樣 QR 只能靠 UDP 偵測猜 IP，而在容器裡猜會猜到 Docker 內部網段，手機連不到）。
# 查本機區網 IP：ipconfig getifaddr en0
# ⚠ 判斷 QR 對不對的唯一可靠方法：**QR 網址的 host 逐字等於 `ipconfig getifaddr en0` 的輸出**。
#   不要用「是不是 192.168 開頭」判斷——2026-08-24 實測本機區網就是 172.29.93.122，
#   而用 localhost 開頁時猜出來的 Docker 網段是 172.24.0.3，**兩個都是 172.x**，看前綴分不出來。

# ── AWS（增量六 Phase 82 起）────────────────────────────────────────
# 區域固定東京 ap-northeast-1。帳號是 **Free plan**（點數制，升 Paid 前不扣卡）。
# ⛔ 不要按 Console 上的 "Upgrade to Paid plan"；⛔ 不要開 Organizations／Control Tower
#    （會自動升 Paid 而且點數作廢）。
#
# 這台 Mac 上有**兩個** AWS 身分，用途完全分開，不要弄混：
#   personaldocai-admin  ← 人用的（AdministratorAccess）。key 在 ~/.aws（aws configure）
#                           所有 `aws ...` 指令都用它，不必加 --profile
#   personaldocai-mac    ← 程式用的（最小權限：documents/ 前綴 ＋ 兩條佇列 ＋
#                           ec2:DescribeInstances；建 bucket／建佇列／清佇列都不行）。key 在 .env，
#                           給 worker 容器裡的 boto3；Phase 88／90 在 Mac 上跑工人也是用它（總覽 §10.2 N）
#
# 我是誰／連得上嗎（不需要任何權限，最適合當第一個檢查）
aws sts get-caller-identity          # Arn 結尾要是 user/personaldocai-admin
aws configure get region             # 預期：ap-northeast-1

# 預算警報（每月 $5，實際與預測各 80% 寄信；開戶第一天就建好了）
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Amount:BudgetLimit.Amount,Unit:BudgetLimit.Unit}' --output table

# ⚠ 想在 shell 裡用 .env 的變數（$S3_BUCKET 之類）時，**不要**整份載進來就打 aws 指令：
#   .env 裡的 AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY 是**程式用的最小權限 key**，
#   而環境變數的優先序比 ~/.aws 高 → CLI 會改用它 → 建資源時 AccessDenied。
#   正確寫法（載完馬上把那兩個丟掉，讓 CLI 回去用 admin 的 profile）：
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
echo "$AWS_REGION / $S3_BUCKET"      # 確認讀到了；⚠ 不要把輸出貼進任何文件

# ⛔ 機密永遠只寫變數名，不寫值：access key、OLLAMA_API_KEY、實例 ID 一個字都不准
#    出現在 docs/、README.md、LAUNCH.md、CLAUDE.md、deploy/ 或任何 commit 裡。
#    .env 不入版控（.gitignore 已擋）。deploy/aws/*.json 裡的帳號 ID 一律寫 <ACCOUNT_ID>。

# 跑測試（Phase 03 起；在專案根目錄執行，會自動連 PersonalDocAI_test 並每測清空）
# ⚠ 測試仍在 **host** 跑（不進 container），連的是 Docker 裡的 PersonalDocAI_test；
#   `docker compose ps` 的 `db` 要是 `Up (healthy)` 才跑得起來，否則會是一整片連線錯誤。
# ⚠ **絕對不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）：
#   `tests/conftest.py` 的 autouse `reset_tables` 每個測試都會 TRUNCATE 同一個測試庫，
#   兩份同時跑會互相清掉對方的資料。症狀是**大量看似隨機的** 404「找不到照片」與
#   `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣——
#   看起來像程式壞了，其實只是撞在一起（2026-08-24 實際踩過，用 pg_stat_activity 抓到
#   一邊在 TRUNCATE、一邊在 INSERT）。等另一份跑完再跑。
pytest -q

# 零依賴實證（增量六 Phase 77 起三個死埠一起指；顆數要與上面相同＝pytest 零 Ollama／Redis／AWS 依賴）
AWS_ENDPOINT_URL=http://127.0.0.1:9 CELERY_BROKER_URL=redis://127.0.0.1:9/0 OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q

# 增量六雲端路總開關：.env 的 CLOUD_ROUTE。**off／assume／ec2 三種都已經接上了**
#   off    ＝不走雲端（預設；行為與增量五逐字相同，pytest 與新 clone 都是它）
#   assume ＝假設遠端開著、不做探測（Phase 86 接的；只給「工人跑在這台 Mac 上」與除錯用。
#            機器沒開時它會傻傻送出、等到 CLOUD_RESULT_TIMEOUT_SECONDS 才 fallback，每張慢 5 分鐘）
#   ec2    ＝用 DescribeInstances 問那台機器是不是 running，答案快取 60 秒（Phase 89 接的；
#            92-A CPU 機已建、.env 已填 EC2_WORKER_INSTANCE_ID）
# **日常是 ec2**（機器 Stop 時探測回 not running，自動 fallback 本機）；改了要 restart worker
# 才生效（ec2 那條路是 lru_cache，行程只建一次）。除錯要一秒排除雲端嫌疑再切 off。
# AWS 那九個變數只寫名字不寫值（見 app/core/config.py 檔尾）。
# ★G1 已由產品負責人通過（Phase 82〜86 完成：S3 bucket 與兩條 SQS 佇列都在）。

# ── 雲端看圖工人（增量六 Phase 88；**平常不用開**）─────────────────────
# 它是「寄物櫃另一頭」那個看圖的人，跟 compose 裡那個 worker 容器完全是兩回事：
#   worker 容器      ＝ Celery，在這台 Mac 上，會寫資料庫、算向量
#   cloud_worker     ＝ 只看圖（打哪一顆看 WORKER_VLM_BACKEND），把 result.json 放回 S3，不碰資料庫
# 只在這台 Mac 上手動跑工人時才把 CLOUD_ROUTE 改 assume；日常遠端工人見下面 EC2 段。
#
# 終端機 A：把工人跑起來（**一定要在專案根目錄**——app 沒裝進 venv，`python -m` 只認
#           目前目錄；.env 倒是從 app/core/ 往上找、在哪裡啟動都讀得到）
#           這個視窗**不要** source .env、也不要 unset：工人自己讀 .env，要的正是裡面那把
#           personaldocai-mac 的 key。「載入 .env 再 unset」只給打 aws 指令的視窗用
#           （那個視窗用 ~/.aws 的 default profile ＝ admin，**不要**加 --profile，
#            這台機器沒有具名的 personaldocai-admin profile）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python -m app.workers.cloud_worker
#   預期第一行：cloud_worker 啟動 version=dev region=ap-northeast-1 bucket=… vlm=cloud model=…
#
#   ── 工人看圖用哪一顆：WORKER_VLM_BACKEND（2026-09-03 產品負責人改判，design6 D12 作廢）──
#     cloud（**預設**，留空或不填都是它）＝ ollama.com，要 OLLAMA_API_KEY／OLLAMA_CLOUD_VLM_MODEL。
#                                    這台 Mac 手動煙霧走的就是這條
#     local ＝ **工人所在那台機器**上的 Ollama，要 OLLAMA_BASE_URL／VLM_MODEL；
#             **92-B 的 GPU EC2 用這個**（機器上自己裝 Ollama、模型跑 GPU），此時不必給 OLLAMA_API_KEY。
#             ⚠ **92-A 的 CPU EC2（t3.xlarge）日常填 cloud**——機型不決定後端，那台只是把圖轉送 ollama.com。
#               同一台可暫時切 local 試 CPU 推論（見下面 EC2 段；先把 Mac 逾時調 900）。
#             在 Mac 上也能設 local，但本機 gemma4 一張要 64〜88 秒，不適合煙霧
#     ⚠ 跟頁首那顆「AI 模型：本機｜雲端」開關**完全無關**（那顆管本機那條路與隱私閘門）；
#       打錯字工人會當場拒絕啟動（不會安靜地退回某一種）。啟動行的 vlm=／model= 就是證據
#   ⚠ 一定要用 -m。python app/workers/cloud_worker.py 會 ModuleNotFoundError: No module named 'app'
#   Ctrl+C 停：先印「收到停止訊號」，**最多等 20 秒**（長輪詢還沒回來）才真的退出；
#              再按一次 Ctrl+C 會直接中斷
#
# 終端機 B：讓本機那條路真的把非敏感照片送出去
#   .env 改 CLOUD_ROUTE=assume（assume ＝假設遠端開著、不做探測；Phase 89 之後日常用 ec2）
#   順手把 CLOUD_RESULT_TIMEOUT_SECONDS 調成 30，出錯時不必等 5 分鐘
#   ⚠ 下面兩句的 -f 要跟你當初啟動時用的一致；開發模式（這台機器的常態）是兩個 -f 都帶
docker compose -f compose.yaml -f compose.dev.yaml restart worker   # 只有 worker 讀這個設定，app 不必動
docker compose -f compose.yaml -f compose.dev.yaml logs -f worker   # 看 route=／fallback=／kind=embed
#
# 想讓煙霧快一點：先把頁首那顆「AI 模型」開關撥到雲端再上傳——隱私閘門是**同一顆看圖模型
# 的一次短問**，跟著這顆開關走（design6 D4／D6）：本機約 1〜2 分鐘、雲端不到 1 秒。
#   curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
#     -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
#   ⚠ 快照是在**上傳當下**抄進 job 的，所以要先撥再上傳；收工撥回 {"backend":"local"}。
#   ⚠ 這扇門與閘門是兩件事，雲端工人打哪一顆由 WORKER_VLM_BACKEND 決定，不受它影響。
#
# ⚠⚠ 收工一定要把 .env 改回 CLOUD_ROUTE=off（順手把 CLOUD_RESULT_TIMEOUT_SECONDS 改回 300），
#     再 restart worker 一次。
#     忘了改＝之後每一張**非敏感**照片都會先送去 S3、等到 CLOUD_RESULT_TIMEOUT_SECONDS
#     逾時才 fallback 回本機。照片不會不見，但每張慢好幾分鐘，而且唯一的線索只有
#     worker log 裡那行 fallback=local reason=result_timeout。
#
# 隱私閘門**看圖不看檔名**（2026-09-01 產品負責人改判）：內容是證件、帳單這類的照片
# ——以及模型說不準的照片——一律留在本機，所以工人那一頭會完全沒反應，那是對的、不是壞了。
# 改檔名沒有任何用；煙霧要用**內容真的不敏感**的圖（例如用 Pillow 畫一張寫著
# RECEIPT／TOTAL 的 PNG），另外畫一張假證件圖驗「敏感留本機」。
#
# 手動煙霧留下的殘訊息（每條佇列 60 秒只能清一次；在打 aws 指令的視窗做，不是終端機 A）：
#   set -a; . ./.env; set +a
#   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY    # .env 那把沒有 sqs:PurgeQueue（見上面 AWS 段）
#   aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"

# ── 雲端工人（EC2；增量六 Phase 92 起）──────────────────────────
#
# 這是**可選**的：EC2 平常是 **stopped**，關著的時候整個系統跟增量五完全一樣
# （每一張照片都在這台 Mac 上看圖）。開它只是為了把「非敏感照片的看圖」卸出去。
#
# ⚠ 現在那台是 **CPU 機（t3.xlarge、一般 AL2023、30 GB gp3）**，工人把圖**轉送 ollama.com**
#   看（worker.env 的 WORKER_VLM_BACKEND=cloud）。GPU 機（g4dn.xlarge、T4、自己跑 Ollama、
#   WORKER_VLM_BACKEND=local）是**之後**的事——G and VT 配額（L-DB2E81BA）還在 AWS 人工審核，
#   帳號上限仍是 0。先用 CPU 機把 AWS 那一整條流程驗完（Phase 92-A），GPU 只影響
#   「看圖那一步在哪裡做、要幾秒」（Phase 92-B）。兩段跑的是**同一份** user-data／unit／映像。
# 用哪一顆由**那台機器上**的 /opt/personaldocai/worker.env 裡的 WORKER_VLM_BACKEND 決定
# （本機的 .env **沒有**這個變數，Mac 上跑工人時預設是 cloud）。
# systemd unit **只有** WORKER_VLM_BACKEND=local 才等 127.0.0.1:11434（最多 120 秒）；
# cloud／空值直接放行。user-data 的 ollama pull 是非致命的——第一次失敗的話，切 local
# 之前要自己補 `sudo ollama pull gemma4:e2b`。
# 只有**隱私閘門判為 NON_SENSITIVE** 而且**機器真的 running** 的照片才會走雲端；
# 敏感與不確定的照片**不進 S3、不到 EC2**。⚠ 頁首那顆「AI 模型：本機｜雲端」是另一扇門
# （design6 D6）：撥到雲端時任何照片的影像照樣送 ollama.com 看圖——閘門不管那扇門，
# 所以**不要**把這段講成「敏感資料完全不出雲」（design6 §6 明文禁止這種說法）。
#
# 先把 .env 帶進 shell（下面每一條都要用 $AWS_REGION 與 $EC2_WORKER_INSTANCE_ID），
# 然後**馬上**把 .env 那把程式用的 key 丟掉，讓 CLI 回去用 ~/.aws 的 admin（見上面 AWS 段）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

# 開機（開完等一分鐘，systemd 會自己把工人拉起來、並從 ECR 拉最新的映像）
aws ec2 start-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"

# ⛔ 關機（★ 每一次 demo／除錯結束都要做，忘了就在扣卡）
aws ec2 stop-instances  --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"

# 「我是不是忘了關？」——收工前跑這一行，預期是**空表格**
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table

# 看那台機器的狀態與 log（**沒有 SSH**，管理一律走 SSM）
aws ssm start-session --target "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
#   進去之後：systemctl status personaldocai-worker --no-pager
#             sudo docker logs cloud-worker --tail 50      ← 第一行有 version=<git sha>
#                                                            與 vlm=cloud｜local model=…
#             sudo journalctl -u personaldocai-worker -n 50 --no-pager
#             systemctl is-active ollama  ← 只有 WORKER_VLM_BACKEND=local 才必須是 active
#                                           （unit 只在 local 才等 11434）
#             nvidia-smi     ← **只有 GPU 機才有**；CPU 機印 command not found 是正常的
#             ollama ps      ← GPU 機上 PROCESSOR 欄要是 100% GPU
#             exit
#   ⚠ 需要外掛：brew install --cask session-manager-plugin（每台 Mac 一次）
#
# 不想開 session，只想跑一句指令：
#   CMD_ID=$(aws ssm send-command --region "$AWS_REGION" \
#     --instance-ids "$EC2_WORKER_INSTANCE_ID" --document-name AWS-RunShellScript \
#     --parameters 'commands=["docker logs cloud-worker 2>&1 | tail -n 20"]' \
#     --query 'Command.CommandId' --output text)
#   sleep 5; aws ssm get-command-invocation --region "$AWS_REGION" \
#     --command-id "$CMD_ID" --instance-id "$EC2_WORKER_INSTANCE_ID" \
#     --query 'StandardOutputContent' --output text
#
# 本機這邊怎麼切（改完要 restart worker，app 不必動）：
#   CLOUD_ROUTE=off     完全不走雲端（除錯時先切這個，一秒排除雲端嫌疑）
#   CLOUD_ROUTE=assume  假設遠端開著、不做探測（只給開發用；機器關著會白等 5 分鐘才 fallback）
#   CLOUD_ROUTE=ec2     ★ 日常就是這個：每次送出前先問一次 DescribeInstances（答案快取 60 秒）
#   走了雲端的證據（本機 worker log 三行，依序）：route=cloud verdict=NON_SENSITIVE →
#   kind=embed backend=local → 雲端結果已入庫：photo_id=…（雲端路**不印**本機路的「入庫完成」）
#   docker compose logs --tail=200 worker | grep -E "route=|fallback=|雲端結果已入庫"
#   docker compose -f compose.yaml -f compose.dev.yaml restart worker
#   ⛔ 那一行 restart **不能省**，有兩個理由：① config 只在行程啟動時讀一次 .env；
#      ② ec2 模式的 CloudRoute 是 dependencies._ec2_cloud_route()（@lru_cache），
#         整個行程共用同一顆物件，第一次建立時就把 instance id 與模式吃進去了。
#         不重啟的話 .env 改了也換不掉它，而且**完全不會報錯**。
#
# 💡 要跑 demo 的話，上傳**之前**先把頁首那顆「AI 模型」開關撥到雲端：隱私閘門跟著它走，
#    撥本機的話那句短問要 1〜2 分鐘照片才會出門，撥雲端不到 1 秒。做完撥回本機。
#    （快照是在上傳當下抄進 job 的，所以順序不能顛倒。）
#
# ⚠ **機器關著不是壞掉**。CLOUD_ROUTE=ec2 時探測發現它不是 running，就直接走本機那條路，
#   log 寫 fallback=local reason=remote_unavailable；上傳仍然回 202、進度面板一模一樣。
# ⚠ **剛 Stop 完的 60 秒內**，探測可能還拿著「running」的快取，於是照片會被送出去、
#   然後等到逾時（CLOUD_RESULT_TIMEOUT_SECONDS=300）才 fallback。這是**預期行為**，
#   不是 bug。要立刻生效就 restart worker（快取在行程記憶體裡）。
#
# 選配：同一台 CPU 機切 local 試本機 Ollama（不是閘門）。CPU gemma4:e2b 常超過 300 秒，
#   **一定要先**把 Mac .env 的 CLOUD_RESULT_TIMEOUT_SECONDS 暫調 900 並 restart worker，
#   否則本機先 fallback=local reason=result_timeout、工人稍後放好的 result.json 變孤兒。
#   SSM 進去改 worker.env：WORKER_VLM_BACKEND=local、OLLAMA_BASE_URL=http://127.0.0.1:11434、
#   VLM_MODEL=gemma4:e2b（不要 -mlx）；AWS／ECR／S3／SQS 那幾行不要動。
#   第一次 boot 的 pull 失敗過的話補 sudo ollama pull gemma4:e2b，再
#   sudo systemctl restart personaldocai-worker。第一行必須是 vlm=local model=gemma4:e2b。
#   只傳一張靜態圖（不要 PDF）。做完 worker.env 改回 cloud、Mac 逾時改回 300，兩邊都重啟。
#   ⛔ 不要把 900 留過夜。
#
# ⛔ 這些永遠不准做：
#   1. 對「還要再用」的機器 terminate-instances ← Stop 才留得住碟（worker.env、7 GB 模型、
#      映像都在）。CPU 機收工一律 Stop（30 GB ≈ $2.9／月，在 Budget 內，Demo 3 還要用它）
#   2. 建 NAT Gateway                 ← 東京約 $45／月
#   3. 配 Elastic IP                  ← 2024-02 起配了就每小時扣、不管機器有沒有在跑
#   4. 開任何 inbound 規則（含 SSH 22）← design6 D11；管理只走 SSM
#   5. 用一般的 AL2023 AMI 開**GPU 機** ← 沒有 NVIDIA 驅動，Ollama 會**安靜地**退回 CPU
#      （能跑、但一張圖好幾分鐘，而且不會有任何錯誤訊息）。GPU 機要用 Deep Learning Base GPU AMI。
#      反過來也一樣：**不要用 GPU AMI 開 CPU 機**（那顆快照 75 GB，根碟只能開 ≥80 GB＝白付）
#   6. 讓 Ollama 聽 0.0.0.0 ← 它只該聽 127.0.0.1；容器靠 --network host 打得到
#   （帳號已升 Paid：忘關會扣卡。升 Paid **不會**自動給 GPU 配額。）
#
# ⚠ 配額分兩條，不要搞混：
#   CPU 機（t3.xlarge）吃 Running On-Demand **Standard** instances（L-1216C47A）——本帳號 8，夠用
#   GPU 機（g4dn.xlarge）吃 Running On-Demand **G and VT** instances（L-DB2E81BA）——本帳號 0、
#     申請中（CASE_OPENED）。沒核准就 run-instances 會回 VcpuLimitExceeded，一台都開不出來。
#     **不要重送申請**（同一條重送只會被合併）。
#
# 費用：t3.xlarge 開機約 $0.2176／小時（忘一天 ≈ $5.2）；g4dn.xlarge 約 $0.71／小時
#      （忘一天 ≈ $17、一個月 ≈ $515）。兩者都另加公有 IPv4 $0.005／小時（只在 running 時算）。
#      **關機也會扣碟錢**：30 GB gp3 ≈ $2.9／月（Budget 內，所以 CPU 機留著）、
#      80 GB gp3 ≈ $7.7／月（超過 Budget，所以 GPU 機測完要 terminate）。
#      Budget 警報 personaldocai-budget（每月 $5，實際與預測各 80% 寄信）。

# ── 格式與 lint：pre-commit（Phase 73，2026-08-27）──────────────────
# **重新 clone 之後要跑一次**，hook 不會自己出現（它寫在 .git/hooks/，不進版控）：
pre-commit install
# 之後每次 git commit，會對「staged 的 .py」自動跑：
#   ruff check --fix  → 能修的直接修（import 排序等）；修不掉的（例如 E402）擋下 commit
#   ruff format       → 重排空白、換行、引號
# hook 改過檔之後那次 commit 會失敗，這是正常的：`git add` 再 commit 一次就過。
# 沒跑 pre-commit install 的人照樣 commit 得了，那時就靠 push 之後的 CI 紅燈擋。
#
# 手動跑（不經 git，等同 hook 的「只檢查、不改檔」版本，也等同 CI 跑的那兩句）：
ruff format --check app tests scripts && ruff check app tests scripts
# 真的要改檔：把 --check 拿掉、check 加 --fix
#
# ⚠ 這台機器上有**兩顆 ruff**，別搞混：
#     .venv/bin/ruff                        ← 你手動打指令、以及 CI 用的（pip 裝的）
#     ~/.cache/pre-commit/repo*/py_env-*/bin/ruff  ← git commit 時 hook 用的
#   hook 那顆是 pre-commit 照 .pre-commit-config.yaml 的 `rev` 自己從 GitHub 下載的，
#   **跟 .venv 完全無關**（所以沒 activate venv 也 commit 得動，實測過）。
#   升級 ruff 要「三個地方一起動」：requirements.txt 的 `ruff>=0.16,<0.17`、
#   .pre-commit-config.yaml 的 `rev:`，然後重跑 `ruff format app tests scripts`
#   收下新版帶來的格式差異。少動一個就會「這台過、那台紅」而且訊息看不出原因。
#   目前釘的是 0.16.5（整庫格式基線就是它跑出來的）。
#
# ⚠ 砍掉重建 .venv 之後要重跑 `pre-commit install`：
#   .git/hooks/pre-commit 裡把 .venv/bin/python3 的**絕對路徑**寫死了。
#   好消息是它壞掉時會 exit 1 擋下 commit（大聲壞，不是安靜放行）。
#
# ⚠ .pre-commit-config.yaml 的兩個 hook 都寫死 `types_or: [python, pyi]`，不要拿掉：
#   上游 ruff-format 的預設含 markdown，會連 .md 裡的 ```python 區塊一起重排
#   （實測本 repo 有 39 份會被改到，包含 docs/design/design.md 與整批已歸檔的
#   docs/plan/finish/phase-*.md——那些是歷史紀錄，不該被工具動到）。

# ── CI：GitHub Actions（Phase 73）─────────────────────────────────
# 檔案：.github/workflows/test.yml。每次 push 與 PR 跑一顆 job，內容等價於：
#   ruff format --check app tests scripts     ← 不准改檔，格式不對就紅
#   ruff check app tests scripts
#   psql … -f db/schema.sql                   ← CI 的庫是全新的空庫，表要自己建
#   pytest -q                                 ← 顆數要跟本機一樣（543）
# CI 自己起一個 pgvector:pg17 當附屬容器並映到 5433（跟 tests/conftest.py 對齊），
# **不起** Redis／Celery worker／Ollama、不建 app 映像、沒有 .env——
# 那五道 autouse 安全網（增量六起含 wire_fake_cloud）已經把外部依賴全擋掉了，測試不需要它們。
#
# ⚠ 本機想預演 CI 的環境（CI 上沒有 .env，config 全走預設值）：
#   把那些變數先設進環境再跑 pytest 即可——load_dotenv() 預設不覆蓋既有環境變數，
#   所以 .env 會被自動略過，**不必去動那個檔**（動它會連帶影響正在跑的 app 容器，
#   而且來源檔消失時 Docker 會默默建一個叫 .env 的「資料夾」）：
#     env OLLAMA_API_KEY= VLM_MODEL=gemma4 LLM_MODEL=gemma4 \
#         OLLAMA_CLOUD_VLM_MODEL=gemma4 OLLAMA_CLOUD_LLM_MODEL=gemma4 \
#         EMBEDDING_MODEL=bge-m3 pytest -q
#   （2026-08-27 實測 543 passed，與帶 .env 跑的結果相同。）

# 只跑規格檔 binder（上傳＋詢問＋無線鏡頭三份；2026-08-24 摘標後**全綠、零 skip**，共 27 顆）
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py tests/integration/test_camera_feature.py -v

# 只跑無線鏡頭規格檔（Phase 36；有 Example 的 2 條 Rule，其餘 4 條標 #TODO 不產生 scenario）
pytest tests/integration/test_camera_feature.py -v

# 只跑本增量的錯誤路徑把關（design1.md §12 逐列，9 個）
pytest tests/integration/test_folder_error_paths.py -v

# 手動煙霧測試（需要 Ollama 真的在跑；真模型不寫自動化測試、不進驗收與 CI）
python scripts/check_embedding_dim.py

# 資料庫建表（schema.sql 開頭是 DROP TABLE IF EXISTS，重跑＝清空重建；含 folder 表＋六筆種子）
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql   # 測試庫（可隨意重建）
# ⚠️ 正式庫有真實照片，「不要」用 schema.sql 重建；結構改版一律走可重跑的遷移腳本
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_folders.sql   # 正式庫遷移（idempotent；2026-08-20 已執行）
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_design3.sql   # 正式庫遷移·增量三四表（idempotent；2026-08-21 已執行）

# ── 資料庫（2026-08-24 增量四起跑在 Docker 裡；brew 的 postgresql@17 已停用，
#    資料目錄 /opt/homebrew/var/postgresql@17 留著當後悔藥，第一個穩定週期內不要刪）──
# ~/.zshrc 三個變數都生效：PGPORT=5433（本來就有）＋ PGUSER=postgres、PGHOST=127.0.0.1
# （後面兩個是 2026-08-24 Phase 47 新加的），所以互動 shell 可以直接：
psql -d PersonalDocAI        # 正式庫（Docker）
psql -d PersonalDocAI_test   # 測試庫（Docker）
# 明寫參數的版本（腳本裡建議這樣寫）：
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI
# ⚠ PGHOST=127.0.0.1 不能漏：不寫主機時 psql 走的是 Unix socket（/tmp 底下的特殊檔案），
#   而 Docker 只把埠用 TCP 發佈出來、沒有 socket 檔——漏了它會噴
#   `connection to server on socket "/tmp/.s.PGSQL.5433" failed`。
#   少了 PGUSER=postgres 則是 `role "linjunting" does not exist`（Docker 裡沒有這個角色）。
# ⚠️ postgresql@14（5432 埠）仍然是別的專案（wanderlove、fse_chat_room）的，絕不可停用或修改。
#   要連它得三個變數都用旗標蓋掉：psql -h 127.0.0.1 -p 5432 -U <原本的帳號> -d <資料庫>

# ── 日常備份（擇一即可）──────────────────────────────────────────
# 方式 A：在容器裡倒，再抓出來。注意這一份沒有 -Fc ＝純文字 SQL（副檔名雖然叫 .dump），
#         要灌回去是用 psql -f，不是 pg_restore。
docker compose exec db pg_dump -U postgres -d PersonalDocAI --no-owner --no-acl \
  -f /tmp/PersonalDocAI.dump
docker compose cp db:/tmp/PersonalDocAI.dump ~/PersonalDocAI-backup-$(date +%F).dump

# 方式 B：或在 host（這一份有 -Fc ＝自訂格式，灌回去用 pg_restore）：
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump

# ⚠ **上面兩種都只備份到資料庫，沒有備份照片檔**（2026-08-24 code review 指出的缺口）。
#   `data/` 裡是 52 MB 的原圖與縮圖（38 張照片的 original_path 指著它），
#   而它 **不入版控**（`.gitignore` 擋掉了）＝ 全世界只有一份，
#   連 `git clean -xdf` 都會把它清掉。資料庫還原回來但 `data/` 沒了的話，
#   照片列還在、縮圖與大圖全變 404。真的在意的話，備份時一起帶上：
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
```

## 規格驅動工作流程（Spec-driven）

本專案採四階段規格流程，prompt 定義在 `docs/spec/prompts/`：

1. **Formulation**（`1.formulation.md` + `formulation-rules.md`）：從原始規格文本萃取資料模型（DBML → `docs/spec/erm.dbml`）與功能模型（Gherkin → `docs/spec/features/*.feature`）。核心原則是「無腦補」：規格沒寫的欄位、規則、行為一律不加。
2. **Discovery**（`2.discovery.md`）：掃描規格找歧義，產出釐清項目到 `docs/spec/.clarify/`。
3. **Clarify**（`3.clarify.md`）：互動式逐題釐清，答案即時整合回規格檔，已解決項目歸檔至 `docs/spec/.clarify/resolved/`。
4. **Design**（`4.design_prompt.md`）：產出 canonical design 到 `docs/design/design.md`。

**目前進度**：四階段全數完成——18 項釐清 Resolved（見 `.clarify/overview.md`）、12 條 Rule 全數附 Example、無 #TODO；`docs/design/design.md`（**v4**）為 canonical design：分層架構（api/routers→services→repositories）、Ollama 本地模型（gemma4＋bge-m3）、中英雙語、side project 原則、Phase 14 極簡網頁介面。v4 實作已全數完成（phase-01〜14 歸檔於 `docs/plan/finish/`）。**2026-08-20 起增量另有 canonical design `docs/design/design1.md`**（資料夾＝category、原圖瀏覽；詢問流程不變）：design1.md 列明的推翻項以 design1.md 為準，未提及的行為仍以 design.md v4 與 Clarify 為準；增量（P15〜26）進度見 `docs/plan/finish/phase-00-增量總覽.md` §5（全數完成；P20 起 `上傳照片.feature` 為改版後的 10 條 Rule 版本）。**2026-08-21 起另有增量二 canonical design `docs/design/design2.md`**（待決定區與定案鎖定）：其 §1.1 列明的推翻項以 design2.md 為準，未提及者仍依 design1.md／design.md v4；實作計畫 `phase-27-待決定區與定案鎖定.md` 已完成並歸檔於 `docs/plan/finish/`。**2026-08-21 起另有增量三 canonical design `docs/design/design3.md`**（無線鏡頭、實體、待辦——三個彈窗依序、實體＝別針、待辦人確認才建）：其 §1.1 列明的推翻項以 design3.md 為準，未提及者仍依 design2.md／design1.md／design.md v4；實作計畫在 `docs/plan/finish/`（phase-00-增量三總覽＋phase-28〜37，**全數完成**——28〜33 在 `e29f5a1`／`0cabb45`、34〜37 在 `6392270`）；`@未實作` 摘標**已於 2026-08-24（增量四 Phase 51）完成**；phase-36 的真機（iPhone）驗收仍待產品負責人手動。**2026-08-23 起另有增量四 canonical design `docs/design/design4.md`**（照片詳情唯讀窗、AI 計時 log、Docker 常駐與正式庫遷移）：實作路線圖 `docs/plan/finish/phase-00-增量四總覽.md`（Phase 38〜50 ＋ 產品負責人額外裁決的 Phase 51 規格摘標）；38〜44 已 commit（`507a18f`），★G1 於 2026-08-24 通過，45〜51 已進 commit `4345846`；unfinish/→finish/ 歸檔依慣例隨 commit 執行。**2026-08-25 起另有增量五 canonical design `docs/design/design5.md`**（待決定升頂欄獨立入口、入庫佇列 202＋Celery×Redis、非同步 UX）：其列明的推翻項以 design5.md 為準，未提及者仍依 design4.md 以降；實作計畫 phase-00-增量五總覽＋phase-52〜72 已全數完成並歸檔於 `docs/plan/finish/`（52〜58 在 `e1d1d5e`、59〜64 在 `f1a7e71`、65〜72 於 2026-08-27 進 commit）。

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

`.feature` 的 Example 把 VLM 理解結果寫在 When 步驟、以資料表驗收，隱含 **VLM、LLM 路由、LLM 回答生成、時鐘（「現在時間」）都必須可注入替換（stub）**。實作架構必須保留這些注入點，`docs/spec/features/` 底下的 `.feature` 即驗收規格（**目前七份**：上傳照片／自然語言詢問／歸類照片／釘選實體／建立待辦／瀏覽檔案櫃／無線鏡頭拍攝；其中三份已有 binder 在跑＝上傳、詢問、無線鏡頭）。

## 重要陷阱

- **`docs/plan/` 新舊混雜，要分清楚**：`docs/plan/unfinish/`（本專案未完成的 phase 計畫）、`finish/`（已完成的 phase 計畫＋phase-00 總覽）、`todo/`、`report/`、`dev-prompts/phase0818.md`／`phase0819*.md`／`phase1819-3.md` 是**本專案的文件**；`dev-prompts/phase0808〜0812.md` 等舊檔是另一個專案（18652FSE Chat Room）的殘留（socket.io、JWT、前端約束皆與本專案無關），**禁止引用作為本專案依據**。若出現 `docs/requirments/` 或 `docs/design/draft.md` 亦同（舊複本以 `docs/spec/draft/design-draft.md` 為準）。
- **本機 PostgreSQL 有兩套**：既有 `postgresql@14`（5432 埠）內有**其他專案的資料庫（wanderlove、fse_chat_room），絕不可停用或修改**；本專案**自 2026-08-24（增量四 Phase 47）起，資料庫改跑在 Docker container**，一樣發佈在 **5433 埠**（`127.0.0.1:5433`），brew 的 `postgresql@17` 已 `stop`（資料目錄保留當後悔藥）。⚠ **互動 shell 光有 `PGPORT=5433` 不夠**——Docker 只發佈 TCP 埠、沒有 Unix socket 檔，而且官方映像的帳號是 `postgres` 不是 `linjunting`，所以 `~/.zshrc` 另外加了 `PGUSER=postgres` 與 `PGHOST=127.0.0.1`（三個都要才連得上，細節見上面指令區的資料庫段）。
- `erm.dbml` 的型別受規格型別清單限制（如 `items` 標成 string、`embedding` 標成 float）；落地為實際 PostgreSQL 型別屬 design decision，需在 design 文件裁決並說明對應，**不要回頭改 `erm.dbml`**。
- 本 repo 自 2026-08-19 起**已是 git repository**（分支 `master`；初始 commit 即 Phase 01〜04 完成狀態）。`.venv/`、`.env`、`__pycache__/`、`.pytest_cache/`、`data/`（照片與縮圖，2026-08-20 起）不入版控——**禁止把二進位照片 commit 進 repo**。
- **原圖與縮圖存在本機 `data/`，不入版控**（`.gitignore` 已加 `data/`）。正式庫的 2 張舊照片沒有原圖（`original_path` 為 NULL），瀏覽時顯示占位是**預期行為**，不是 bug。`DATA_DIR` 在 pytest 由 `isolated_data_dir` fixture 導向臨時目錄，所以跑測試永遠不會弄髒專案的 `data/`。
- **`POST /photos` 回 202 不代表照片已經入庫**（增量五起）。202 只代表「檔案收下了、排進佇列了」；真正的入庫發生在 worker 裡，本機模型要 64〜88 秒、雲端約 2 秒。所以「上傳完馬上去待決定頁看不到照片」是**預期行為**，不是 bug——等右下角的進度列消失、頂欄「待決定（N）」加 1 才算完成。寫測試時同理：`POST` 之後要**自己呼叫 `run_ingest_job(job_id, …)`** 把任務跑完，才看得到照片（`tests/conftest.py` 的第四道安全網 `wire_memory_job_store` 已經把 JobStore 指到記憶體，**pytest 絕不連真 Redis、絕不啟動 Celery**）。

## 語言與其他慣例

- 文件與規格一律使用**繁體中文＋台灣常用技術用語**；Gherkin step 以中文描述、DataTable 欄位名用英文、Given/When/Then 用英文關鍵字。
- 使用者層級的 `~/CLAUDE.md` 另有 MCP 使用規則（查最新文件用 Context7、研究類 MCP 只查不改碼、結論附來源連結），同樣適用於本專案。
