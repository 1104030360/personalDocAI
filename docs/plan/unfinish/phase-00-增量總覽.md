# Phase 0：增量總覽（資料夾＝category、原圖瀏覽的實作路線圖）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> **一句話（引 `docs/design/design1.md`）：上傳後 AI 從現有資料夾裡推薦一個，你確認或自建；之後點開資料夾看縮圖。**
> 這不是第二套分類，也不是第二個分類 AI。`category` 就是資料夾名稱。

本文件是 `docs/design/design1.md`（本增量的 canonical design，2026-08-20 定稿）的**實作路線圖**。設計文件說「系統要長成什麼樣子」，這份路線圖說「照什麼順序做出來」。

---

## 0. 這份路線圖怎麼用

### 0.1 和 `finish/phase-00-總覽.md` 的關係

| 文件 | 涵蓋範圍 | 狀態 |
|---|---|---|
| `docs/plan/finish/phase-00-總覽.md` | Phase 01〜14：上傳、詢問、12 條 Gherkin Rule、兩個純 HTML 頁 | **歷史紀錄**，已全數完成（2026-08-19），不再更動 |
| **本文件**（`unfinish/phase-00-增量總覽.md`） | Phase 15〜26：資料夾、原圖與縮圖、上傳彈窗、瀏覽頁 | **執行中**（P15〜17 已完成並歸檔至 `finish/`，2026-08-20；P18〜24 已完成，2026-08-21；P25 起待做） |

兩份路線圖是接力關係：舊的那份做完了才有這一份的起點。舊路線圖裡「❌ 不做照片瀏覽」「❌ 不保留原始照片檔」這類禁令，**已由產品負責人於 2026-08-20 明示改規格推翻**（詳見 design1.md §1.1），那是正式的規格變更，不是實作時偷加功能。舊路線圖的其他禁令（多使用者、非同步佇列、前端框架、雲端部署……）**全部仍然有效**。

### 0.2 怎麼執行

- **一定要照編號依序做**：Phase 15 → 16 → 17 → … → 26。**順序不可對調。**
  - 唯一的例外是理論上的：Phase 17（檔案儲存服務）與 Phase 16（資料夾資料層）之間沒有互相依賴，理論上可以平行。**但本路線圖一律要求照序做**——side project 一個人做，平行只會讓「現在到底綠不綠」變得說不清楚。
- **每個 phase 結束時，系統都處於「可驗證的狀態」**：跑 `pytest -q` 全綠，UI 相關的 phase 則跑一份瀏覽器實操清單。
- **依序做完 Phase 15〜26 ＝完成本增量**，沒有第 27 個 phase。
- 讀者假設是**程式新手**：每個技術名詞第一次出現都用一句白話解釋，指令可以直接複製貼上執行（macOS）。

### 0.3 開工前的基線

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

預期最後一行：**`79 passed`**（Phase 01〜14 完成時的狀態）。這是整個增量的起跑線，**Phase 15 開工前要實查一次**，對不上就先查清楚再動手。

---

## 1. 三大守則（每個 phase 都適用）

### 守則一：side project，不要過度設計

只做 design1.md 寫到的事。看到「順便加個抽象層」「以後可能會用到」「加個快取吧」的念頭，答案一律是**不要**。design1.md §14 已經把七個被否決的方案寫死了（第二個分類 AI、推兩個建議、兩套平行分類、原圖存 BYTEA……），**不要重開這些討論**。

### 守則二：不留過渡產物，一次改成新的

> 產品負責人原文：**「不留過渡產物，一次改成新的」**——`schema.sql` 直接改成最終版（不是分兩次改）；`db/migrate_folders.sql` 一次跑完；規格檔在 Phase 20 內一次改完；程式不留任何新舊相容分支、不留 deprecated 函式。唯一允許的「舊資料」行為是 design1.md §10 明訂的：舊列路徑 NULL → 讀圖 404 → 前端占位。

具體落地：Phase 24 把 Phase 23 內嵌在 `upload.html` 的彈窗程式碼**搬進**共用檔 `folder_modal.js`，兩邊引用同一份，**不留兩份**；Phase 26 把樣式統一抽到 `style.css`，**不留頁內舊樣式殘骸**。

### 守則三：規格檔已核准正式改版

`docs/spec/` 在 Phase 01〜14 期間是唯讀的。本增量**解除 `上傳照片.feature` 的唯讀**：Phase 20 一次改成新行為（上傳當下 `category=未分類`、拿掉「不含原始照片檔」、新增建議資料夾相關 Rule），驗收測試跟著規格檔走。

> ⚠️ **`自然語言詢問.feature` 完全不動**，它的 5 條 Rule（Q1〜Q5）必須**全程保綠**——每個 phase 的 `pytest -q` 都會跑到它們。

---

## 2. 名詞（本增量新出現的，舊名詞見 `finish/phase-00-總覽.md`）

| 名詞 | 白話解釋 |
|---|---|
| 資料夾（folder） | 使用者收納照片的類型，有名稱與說明。本增量規定 `photo.category` **等於**所屬資料夾的名稱 |
| 未分類 / 收件箱（inbox） | 系統資料夾。關掉彈窗、或還沒確認歸類的照片先放這裡。不可刪、不可改名，全系統只准有一個 |
| 推薦（suggested folder） | VLM 從現有資料夾清單裡選出的**那一個**，給彈窗的第一個按鈕用。它是建議，不是最終歸屬 |
| 歸類 | 使用者在彈窗（或瀏覽頁）確認照片要放哪個資料夾，系統把 `folder_id`、`category`、`embedding` 一起更新 |
| FK（foreign key，外鍵） | 「這一欄的值必須是另一張表裡真的存在的 id」的規則 |
| 縮圖（thumbnail） | 原圖縮小後的小圖，用來排成一面牆給人瀏覽，載入快很多。本專案用 Pillow 縮到長邊 512 像素 |
| Pillow | Python 最常用的影像處理套件（`import PIL`），本增量只拿它做縮圖 |
| `DATA_DIR` | 檔案要落地在哪個資料夾的設定值。正式是專案根目錄下的 `data/`；測試會被改指到暫存目錄，pytest 永遠不會寫進專案 |
| 相對路徑 | 不含電腦絕對位置的路徑，例如 `data/photos/1.jpg`。資料庫只存相對路徑，換電腦也不會壞 |
| multipart | 瀏覽器上傳檔案時用的 HTTP 格式（`multipart/form-data`），既有的 `POST /photos` 就是收這個 |
| `FileResponse` | FastAPI 內建的回應型別：直接把一個檔案送給瀏覽器（讀圖端點用它） |
| modal（彈窗） | 蓋在頁面上、要處理完才能繼續操作的小視窗。本專案用純 HTML/CSS/JS 做，**禁用 `alert`／`confirm`** |
| `PATCH` | HTTP 動詞，意思是「只改這筆資料的一部分」。歸類端點 `PATCH /photos/{id}/folder` 只更新歸類相關的三個欄位（`folder_id`、`category`、`embedding`），不動文字與其他 metadata |
| `409 Conflict` | HTTP 狀態碼：「跟現有資料衝突」。本增量用在「自建的資料夾名稱已經存在」 |
| `422 Unprocessable Entity` | HTTP 狀態碼：「格式對但內容不合理」。本增量用在「名稱空白」「`folder_id` 和 `name` 沒有恰好給一個」 |
| 佔位圖（placeholder） | 沒有縮圖可顯示時，畫一塊灰底寫「無縮圖」，**不假裝有圖** |
| autouse fixture | pytest 的「每個測試都自動套用的前置／後置動作」，不必在測試函式裡寫它的名字 |
| design skills | Claude Code 的設計技能包（`frontend-design`）。Phase 26 動手前**必須先載入** |

---

## 3. 全部 12 個 Phase

工作量欄位：**S** ＝約半小時內、**M** ＝一到兩小時、**L** ＝需要專心的半天。都是單人 side project 的粗估，不是承諾。

| Phase | 檔名 | 一句話 | 量 | 做完會多什麼 |
|---|---|---|---|---|
| 15 | `phase-15-資料庫一次改版與預設資料夾.md` | `schema.sql` 改成最終版：新增 `folder` 表（含「最多一個收件箱」的部分唯一索引）與六筆種子、`photo` 加 `folder_id` 與原圖／縮圖／格式三欄；正式庫用可重跑的 `migrate_folders.sql` 遷移 | M | 資料庫有資料夾了；正式庫 2 張舊照片歸進「收據」；`conftest` 每測重播六筆種子 |
| 16 | `phase-16-資料夾資料層.md` | `photo_repository` 加五個函式：`list_folders`／`get_folder`／`find_folder_by_name`／`create_folder`／`list_photos_in_folder` | S | 程式讀得到資料夾清單與張數，之後四個 phase（18／20／21／22）的共同地基 |
| 17 | `phase-17-檔案儲存服務.md` | 新檔 `services/storage_service.py`：存原圖、Pillow 產縮圖（長邊 512px）、相對路徑換算、失敗清理；`config` 加 `DATA_DIR`、`.gitignore` 加 `data/` | M | 有能力把照片真的存成檔案；pytest 寫進暫存目錄，永不污染專案 |
| 18 | `phase-18-VLM資料夾推薦.md` | `VLM_PROMPT` 改成 `build_vlm_prompt(folders)` 動態注入資料夾清單；新增 `clamp_category()` 把清單外的名稱夾回「未分類」 | S | VLM 只會從現有資料夾裡挑一個推薦（本 phase 只加函式，還不落庫） |
| 19 | `phase-19-上傳存檔與讀圖端點.md` | 上傳流程改成 INSERT →存原圖→產縮圖→回寫路徑（任何一步失敗就刪檔＋刪列並 re-raise）；新增 `GET /photos/{id}/thumbnail` 與 `/image` | M | 上傳完硬碟真的有圖，瀏覽器打得開；舊列（路徑 NULL）回 404 |
| 20 | `phase-20-上傳未分類流程與規格改版.md` | **本增量最關鍵的 phase**：上傳一律先進「未分類」，回應多帶 `folder`／`suggested_folder`／`folders`／`thumbnail_url`；`上傳照片.feature` 一次改版，相關測試逐一改成新行為 | L | 上傳回應足以讓前端立刻畫出彈窗；規格檔與程式重新對齊 |
| 21 | `phase-21-歸類端點.md` | `PATCH /photos/{id}/folder`：採用現有資料夾或自建；成功後 `folder_id`＋`category`＋**重算的 embedding** 一條 UPDATE 寫完 | M | 使用者的選擇能真的落庫，語意查詢也拿得到正確的類別訊號 |
| 22 | `phase-22-資料夾瀏覽端點.md` | 新檔 `api/routers/folders.py`：`GET /folders`、`GET /folders/{id}`（含照片摘要與 `thumbnail_url`） | S | 瀏覽頁需要的資料備齊 |
| 23 | `phase-23-上傳頁彈窗.md` | 只改 `upload.html`：201 後開 modal，三選項（採用推薦／改選現有／自建新的），關掉＝留在未分類 | M | 上傳完立刻能歸類，human-in-the-loop 成立 |
| 24 | `phase-24-瀏覽頁.md` | 新檔 `browse.html`：資料夾卡片 → 縮圖牆 → 點單張再歸類；彈窗程式碼抽成共用的 `folder_modal.js`；三頁互連 | L | 「我上傳過什麼」終於看得見 |
| 25 | `phase-25-錯誤收尾與全量回歸.md` | 新測試檔把 design1.md §12 錯誤表逐列把關；全量回歸；真模型手動煙霧；正式庫最終核對；更新 `CLAUDE.md`；本批計畫檔移到 `finish/` | M | 每條錯誤路徑都有測試看著；文件與現況一致 |
| 26 | `phase-26-美化UIUX.md` | 載入 design skills、參考網路真實作品，把三頁與彈窗做出一致的視覺個性；**明文拒絕 AI 樣板臉** | L | 不再像一份作業，像一個產品 |

---

## 4. Phase 相依順序

```
 起點：Phase 01〜14 完成（79 tests 全綠、POST /photos、POST /ask、/ui 兩頁）
  │
  ▼
 P15 db/schema.sql 最終版＋folder 表＋六筆種子＋photo 四個新欄位
  │   ＋db/migrate_folders.sql（正式庫）＋conftest reset_tables
  │
  ├──────────────┐
  ▼              ▼
 P16 資料夾      P17 storage_service（存原圖／Pillow 縮圖／路徑換算）
     資料層          ＋config.DATA_DIR＋.gitignore data/
  │   五個函式    │   （理論上可與 P16 平行，本路線圖一律照序做）
  │              │
  ▼              │
 P18 VLM prompt 注入資料夾清單＋clamp_category ◀───┘
  │   （需要 P16 的 list_folders）
  ▼
 P19 上傳寫檔（INSERT→存檔→回寫路徑）＋GET 縮圖/原圖端點
  │   （需要 P17 的 storage_service）
  ▼
 P20 ★ 上傳一律「未分類」＋回應擴充＋上傳照片.feature 一次改版
  │   （需要 P16 清單、P18 clamp、P19 寫檔與 thumbnail_url）
  ▼
 P21 PATCH /photos/{id}/folder：採用現有／自建＋重算 embedding
  │   （需要 P16 的 get_folder／find_folder_by_name／create_folder）
  ▼
 P22 GET /folders、GET /folders/{id} ＋ app/schemas/folder.py
  │   （需要 P16 的 list_folders／list_photos_in_folder）
  ▼
 P23 upload.html 彈窗（三選項＋關掉＝未分類）
  │   （需要 P20 的回應欄位、P21 的 PATCH）
  ▼
 P24 browse.html 縮圖牆＋folder_modal.js 共用彈窗＋三頁互連
  │   （需要 P22 的兩個端點、P19 的讀圖端點；把 P23 的彈窗搬進共用檔）
  ▼
 P25 ★ 錯誤表逐列把關＋全量回歸＋真模型煙霧＋正式庫核對＋CLAUDE.md
  │
  ▼
 P26 ★ 美化 UI/UX（design skills＋真實作品參考＋拒絕 AI 感）  ← 本增量完成
```

★ ＝驗收里程碑。P20 是規格改版點，P25 是全量回歸點，P26 是收尾點。

---

## 5. 進度表

執行時逐格打勾。「累計」欄是做完該 phase 後 `pytest -q` 應該顯示的數字。

> 🔄 **累計顆數的填法（沿用 `finish/phase-00-總覽.md` 的既有慣例）**：P15／P16 的數字已由該 phase 計畫定案；**P17 起各列等各該 phase 開工前、依該 phase 計畫確定後再填入**——先猜一個數字只會讓之後的驗收對不上。UI 類 phase（P23／P24／P26）依 Phase 14 原則**不新增自動化測試**，累計不變。

| ✔ | Phase | 主要產出 | 新增測試 | `pytest -q` 累計 |
|---|---|---|---|---|
| ☑ | — | 開工基線實查（2026-08-20 實跑） | — | **79** |
| ☑ | 15 | `schema.sql` 最終版、`migrate_folders.sql`、`DEFAULT_FOLDERS`、`reset_tables`（2026-08-20 完成） | `integration/test_photo_repository.py` +4 | **83** |
| ☑ | 16 | folder 五個 repository 函式（2026-08-20 完成） | `integration/test_folder_repository.py` 10 | **93** |
| ☑ | 17 | `services/storage_service.py`、`config.DATA_DIR`、`isolated_data_dir` fixture（2026-08-20 完成） | `unit/test_storage_service_unit.py` 10 | **103** |
| ☑ | 18 | `build_vlm_prompt(folders)`、`clamp_category()`（2026-08-21 完成） | `unit/test_vlm_service_unit.py` 追加 6＋`integration/test_upload_design_rules.py` 追加 1 | **110**（實測相符） |
| ☑ | 19 | 上傳寫檔流程、`GET /photos/{id}/thumbnail`／`/image`（2026-08-21 完成） | `integration/test_photo_files.py` 11 | **121**（實測相符） |
| ☑ | 20 | 未分類流程、回應擴充、`上傳照片.feature` 改版（2026-08-21 完成） | 既有上傳測試改版＋規格 Example 7→10 | **124**（實測相符） |
| ☑ | 21 | `PATCH /photos/{id}/folder`、重算 embedding（2026-08-21 完成） | `integration/test_assign_folder.py` 8 | **132**（實測相符） |
| ☑ | 22 | `api/routers/folders.py`、`schemas/folder.py`（2026-08-21 完成） | `integration/test_folders_endpoint.py` 8 | **140**（實測相符） |
| ☑ | 23 | `upload.html` 彈窗（2026-08-21 完成，Playwright MCP 實操 13 項全過） | 0（瀏覽器實操驗收） | 不變（140） |
| ☑ | 24 | `browse.html`、`folder_modal.js`、三頁互連（2026-08-21 完成，Playwright MCP 實操 19 項全過） | 0（瀏覽器實操驗收） | 不變（140） |
| ☐ | 25 | 錯誤表把關、全量回歸、`CLAUDE.md`、計畫檔歸檔 | `integration/test_folder_error_paths.py` | 開工前依該 phase 計畫填入 |
| ☐ | 26 | 三頁視覺打磨、`style.css` | 0（瀏覽器實操驗收） | 不變 |

---

## 6. 最終驗收定義（本增量算不算做完）

依序滿足下面兩組條件，本增量才算完成。

### 6.1 Phase 25 的清單（自動化與資料）

- [ ] `docs/spec/features/自然語言詢問.feature` 的 **5 條 Rule 全綠**（全程未修改該檔）
- [ ] `docs/spec/features/上傳照片.feature`（Phase 20 改版後的新版）**全數 Rule 全綠**
- [ ] `pytest -q` **全量全綠**，最終顆數記錄在 Phase 25 的報告裡
- [ ] design1.md §12 錯誤表**逐列**都有測試把關（已被其他 phase 覆蓋的，在 Phase 25 文件裡註明由哪個測試守著即可，不重寫）
- [ ] 正式庫核對 SQL：2 張舊照片在「收據」、三個路徑欄位 NULL、瀏覽頁顯示占位
- [ ] 真模型手動煙霧（**不進 CI**）：真照片上傳 → 建議合理 → 三種歸類各一次 → 瀏覽頁看得到縮圖 → `POST /ask` 條件／語意／查無各問一次
- [ ] `CLAUDE.md` 現況段已更新為 Phase 15〜26 完成的敘述；本批計畫檔已從 `unfinish/` 移到 `finish/`

### 6.2 Phase 26 的瀏覽器驗收（視覺與互動）

- [ ] 動手前已載入 `frontend-design` skill；已參考網路上的真實作品並在回答中**列出來源連結**
- [ ] 三頁（upload／browse／ask）＋彈窗共用一套設計 tokens，沒有頁內舊樣式殘骸
- [ ] 沒有「AI 樣板臉」：無紫色漸層背景、無置中大卡片＋emoji 大標題、無千篇一律的系統字型堆疊、無無意義的玻璃擬態
- [ ] Playwright MCP 截圖前後對比、console 乾淨、三頁互連正常
- [ ] 全流程走一遍：上傳 → 彈窗三選項 → 歸類 → 瀏覽頁看到它在新資料夾裡
- [ ] `pytest -q` 仍然全綠（Phase 26 不該動到任何測試）

---

## 7. 不准做的事（每個 phase 都適用）

沿用 `finish/phase-00-總覽.md` 第 5 節，**扣掉本增量正式推翻的三項**（不存原圖、不做照片瀏覽、不為介面新增端點），其餘全部有效：

- ❌ 多使用者、帳號登入、`core/security.py`
- ❌ 多輪對話記憶、雲端部署、`users/` 之類本專案沒有的空殼資源目錄（分層 ≠ 建空殼）
- ❌ 第二個分類／推薦模型，或第二個 `ChatOllama`（design1.md §8：仍然只有**一次**看圖呼叫）
- ❌ 把 `location` 或 `items` 當資料夾（design1.md §3）
- ❌ 刪除照片、刪除資料夾（尤其不可刪「未分類」）
- ❌ 資料夾巢狀、標籤多對多、相簿分享（design1.md §15）
- ❌ 原圖存進 PostgreSQL 的 BYTEA、或把圖檔丟在 repo 根目錄（design1.md §14）
- ❌ 改 `POST /ask` 的路由或 prompt 鐵律
- ❌ 非同步處理、佇列、處理狀態欄位
- ❌ metadata 自由欄位／延伸 JSON（固定四欄位）
- ❌ ORM、`models/`、alembic migration（手寫 SQL，`schema.sql` 重建即可）
- ❌ 前端框架（React／Vue／jQuery／CSS 框架／npm／打包工具——只准純 HTML＋原生 JS）
- ❌ 網頁用 `alert`／`confirm`（一律頁內訊息）
- ❌ 為那幾個網頁寫瀏覽器自動化測試（頁面驗收以手動／Playwright MCP 實操為準）
- ❌ 把模型換回雲端服務（一律本機 Ollama，零 API key）
- ❌ 檔案大小上限檢查（已釐清：無上限，刻意不寫）
- ❌ 條件查詢的跨語言翻譯對映（問 `receipts` 不會自動對到「收據」）
- ❌ 深色模式、RWD 完美適配（Phase 26 桌機優先，手機能用即可）
- ❌ 修改 `docs/spec/features/自然語言詢問.feature`（**唯一可改的規格檔是 `上傳照片.feature`，且只在 Phase 20 一次改完**）

另外：`docs/plan/dev-prompts/phase0808〜0812.md` 等舊檔是**另一個專案（18652FSE Chat Room）的殘留**，不得引用作為本專案依據。

---

## 8. 本總覽的驗收清單

這份文件是地圖，不是工作。它的「完成」定義是：12 個 phase 計畫檔都在、內容互相對得上、進度表可以開始打勾。

- [ ] `docs/plan/unfinish/` 下有 **13 份檔案**：`phase-00-增量總覽.md` 與 `phase-15` 〜 `phase-26` 共 12 份 phase 計畫

  ```bash
  ls docs/plan/unfinish/
  ```

- [ ] 每份 phase 計畫都有：🎯 side project 提醒、目標、前置條件（含基線）、名詞表、至少一張 ASCII 圖、TDD 逐步驟、驗收清單
- [ ] 本文件第 3 節的 12 個檔名與實際檔名**一字不差**
- [ ] 開工基線已實查

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期最後一行：`79 passed`

- [ ] **git commit**（計畫檔本身進版控）

  ```bash
  git add docs/plan/unfinish/
  git commit -m "docs: 增量計畫 phase-15〜26——資料夾＝category、原圖瀏覽的實作路線圖（依 design1.md：folder 表與六筆種子、原圖/縮圖落地、VLM 推薦、未分類流程與規格改版、歸類與瀏覽端點、彈窗與瀏覽頁、錯誤收尾、UI/UX 美化），基線 79 tests"
  ```

---

## 9. 完成後的專案狀態

依序完成 Phase 15〜26 後，PersonalDocAI 從「一個會回答問題的 RAG demo」變成**看得見、分得開、還能再問**的個人視覺檔案櫃：

- 上傳一張照片，AI 看完圖會從現有資料夾裡推薦一個；照片先安全地躺在「未分類」，**由你確認**要採用推薦、改選其他資料夾，還是自建一個新的——關掉彈窗也不會遺失，之後隨時能再歸類。
- 原圖與縮圖真的存在硬碟上（`data/photos/`、`data/thumbs/`，不入版控），瀏覽頁點開資料夾就是一面縮圖牆；2 張沒有原圖的舊照片老老實實顯示占位，不假裝有圖。
- `category` 不再是 VLM 自由發明的字串，而是受控的資料夾名稱——條件查詢因此更穩。
- `POST /ask` 的行為**一個字都沒變**，5 條 Rule 全程保綠。
- 三個網頁有一致的視覺個性，不是紫色漸層＋emoji 大標題的 AI 樣板臉。
