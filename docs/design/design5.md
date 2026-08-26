# PersonalDocAI — 設計文件（增量五）：待決定獨立入口與非同步入庫

> **一句話：待決定從「瀏覽資料夾」搬到頂欄、點開仍用原來的歸類彈窗但窗頂加原圖；電腦可一次選多檔、手機可連拍，HTTP 立刻回「已收下」，VLM 分析交給最多兩個 Celery worker，完成後才進待決定等你歸類。**

> 🎯 **仍是 side project：不要過度設計。** 只做本文件寫到的事。定案不可逆、人確認才釘實體／建待辦、embeddings 一律本機、單一使用者、不做刪除照片，全部維持 design4.md／design3.md／design2.md／design1.md／design.md v4 不變。

| 項目 | 內容 |
|---|---|
| 前提 | 增量四（design4.md，Phase 38〜51）已落地：端點 20；Postgres＋app 在 Docker；Ollama 仍在 Mac |
| 目的 | 上傳／拍照不再被同步 VLM 卡住；待決定是「還沒歸類完的工作」，不該跟已定案的檔案櫃混在同一頁 |
| 狀態 | 產品負責人 2026-08-25 對話拍板，**可寫進本文件**；尚未實作（實作分 phase，一次一項） |
| 衝突時誰贏 | 本文件列出的推翻項以本文件為準；未提及的行為仍以 design4.md、design3.md、design2.md、design1.md、design.md v4 為準 |

---

## 0. 實作計劃總序（不可對調）

本增量拆三段。**Redis／Celery 是乙，不要為了趕非同步先改頂欄又把上傳契約改一半。** 甲可以先讓待決定換位子（上傳暫時仍同步）；乙才是破壞性的 201→202；丙把多檔、進度面板、鏡頭接到乙上面。

```text
階段甲  待決定獨立入口（功能 1）
        頂欄加上「待決定（N）」
        新頁 /ui/pending.html；瀏覽頁拿掉待決定 tab
        歸類彈窗窗頂加原圖
            │
            ▼
階段乙  入庫佇列（功能 2 的後端）
        Redis ＋ Celery（concurrency=2）
        POST /photos 與鏡頭快門改 202
        staging ＋ run_ingest_job ＋ 失敗重試與清理
            │
            ▼
階段丙  非同步 UX（功能 2 的前端）
        電腦一次多檔；全站進度面板
        鏡頭可連拍、桌面不再開上傳彈窗鏈
```

| 階段 | 做什麼 | 何時可以開始 | 何時算過 |
|---|---|---|---|
| **甲** | 待決定搬頂欄＋彈窗原圖 | 本文件拍板後即可 | 頂欄四格；`/ui/pending.html` 縮圖牆可開歸類窗且窗頂有原圖；瀏覽頁預設是資料夾、沒有待決定 tab |
| **乙** | Redis／Celery／202／staging | 甲合併後即可（乙不依賴甲的 HTML，但總序仍甲→乙，避免兩條契約同時改） | `pytest -q` 綠；單檔 POST 回 202、當下 `photo` 表沒多列；測試內跑完任務後照片在收件箱；3 次失敗後列數為 0 且 staging 不在 |
| **丙** | 多檔＋進度面板＋鏡頭 | **只有乙的 API 契約穩定之後** | 一次選多張會出現多列進度；成功列消失、N 加一；失敗列可關掉；手機可連續快門；桌面不開三關彈窗 |

**禁止：** 乙還沒好就把上傳頁改成 `multiple` 卻仍同步等 VLM（那會一次卡住 N 張，比現在更糟）。  
**禁止：** 把影像位元組塞進 Redis。  
**禁止：** 為了進度面板新增 `DELETE` 進 OpenAPI（Phase 37「openapi 零 DELETE」仍有效；關掉失敗列用 `POST`）。  
**禁止：** 處理中、尚未 VLM 成功的檔以空白卡出現在待決定。

---

## 1. 已拍板決策（2026-08-25 對話）

| # | 決策 | 內容 |
|---|---|---|
| D1 | 待決定換位子 | 待決定從瀏覽頁 tab **移到頂欄**，放在「上傳照片」右邊。待決定還不是歸類完的結果，不該跟檔案櫃同一頁 |
| D2 | 點開仍是彈窗 | 待決定仍是縮圖牆。點一張開歸類彈窗（①採用／②改選／③自建／④稍後再說），**窗頂多一張原圖**。因為上傳當下不再開鏈（D13），待決定補完鏈改為與**現在的上傳鏈相同**：抽屜 → 實體 → **有待辦建議才開待辦窗**（推翻 design3「待決定沒有待辦窗」——那條的前提是建議只活在 201 回應裡，本增量已不成立） |
| D3 | 電腦一次多檔 | `<input multiple>`：一次可選多張 JPEG／PNG，也可含 PDF。每個檔各自入列 |
| D4 | 鏡頭連拍 | 手機快門不必等 VLM。拍完就能再拍。與電腦上傳走**同一條**佇列 |
| D5 | Redis ＋ Celery | 佇列用 Redis；worker 用 Celery。不採用 FastAPI BackgroundTasks，也不自寫 Redis list 消費迴圈 |
| D6 | 兩個 worker | 正式與測試都最多 **2** 個 Celery 子行程（一個 `worker` 容器、`--concurrency=2`）。測試手動煙霧時先把頁首 AI 開關切到**雲端** |
| D7 | 立刻 202 | HTTP 只做格式檢查、落 staging、入列。回 **202** `{job_id, filename, content_type}`。這不是「照片列已寫入」 |
| D8 | 進度面板全站 | 每一頁右下角同一份面板（含問問題、瀏覽、待決定、鏡頭桌面、手機取景）。換頁／重新整理靠伺服器上的任務清單長回來 |
| D9 | 成功列消失 | 分析成功 → 該列從面板拿掉，頂欄「待決定（N）」+1。失敗列留下，可按 × 關掉。清單空了就收起面板 |
| D10 | 失敗重試後刪 | 同一張圖（或 PDF 的某一頁）**含第一次共送 VLM 3 次**。看不懂與雲端／連線失敗都算。3 次都失敗 → **整筆拿掉**（JPEG／PNG：不留 `photo` 列、刪 staging）。對外結果對齊現在的「看不懂＝什麼都不存」 |
| D11 | PDF 一檔一任務 | 進度列一個檔一列。**一個 Celery 任務＝一個檔案**。同一份 PDF 的每一頁由**同一個 worker 依序**看完，不拆成每頁一個任務 |
| D12 | PDF 以頁為重試單位 | 每一頁各自最多 3 次；仍失敗就跳過（現有 `skipped_pages` 語意）。成功的頁進待決定。**整份 0 頁成功**（或檔壞到無法拆頁）才整筆失敗、不留照片 |
| D13 | 上傳當下不開歸類鏈 | 電腦上傳與鏡頭桌面都**不再**於入庫當下開抽屜→實體→待辦。歸類只發生在待決定 |
| D14 | AI 開關快照 | 入列當下把當時的 `config.AI_BACKEND` 寫進任務。worker 用這張快照看圖。embedding 仍一律本機。頁首開關仍只活在 web 行程記憶體；不靠 worker 去讀那個變數 |
| D15 | 測試不碰真 Redis | pytest 繼續在 host 跑、繼續 `wire_fake_ai`、繼續不打真 Ollama。任務本體抽成 `run_ingest_job(...)`，測試直接呼叫。Job 狀態用可替換的 store（測試用記憶體，正式用 Redis） |
| D16 | 建議隨入庫落庫 | worker 成功 INSERT 時，除既有 `suggested_category` 外，一併寫入 **實體建議**與 **待辦建議**（標題／到期日，可空）。仍只是建議：人按確認才寫 `entity`／`photo_entity`／`task`。沒有這三欄，202 之後建議會蒸發，待決定開窗只剩「再建議一個」、待辦入口消失 |

### 1.1 本增量明確推翻的舊決策

| 舊決策 | 本文件改成 |
|---|---|
| design.md v4「上傳為同步處理；完成即代表文字、metadata、向量皆已儲存」；「明確不做非同步佇列」 | HTTP 完成＝檔已收下並入列。文字／metadata／向量在 worker 成功之後才存在 |
| design1.md「明確不做非同步佇列」 | 本增量正式做 Redis ＋ Celery |
| design2.md D1「上傳後強制歸類彈窗」 | 上傳／快門後不開彈窗。彈窗只從待決定點開（仍強制決定：無 ×／Esc／點外） |
| design2.md D4「瀏覽頁頂部分待決定｜資料夾」；design3.md D15「瀏覽入口為待決定｜資料夾｜待辦」 | 待決定升成頂欄；瀏覽頁只剩「資料夾｜待辦」 |
| design2.md D2 文案「之後到瀏覽頁的待決定分頁完成歸類」 | 改成到頂欄的待決定頁 |
| `POST /photos`、`POST /camera/{token}/photos` 成功 **201** ＋整份 `UploadResponse` | 成功受理 **202** ＋ `job_id`。建議資料夾／實體／待辦改到照片入庫後，從既有詳情／歸類資料讀（待決定開窗時再抓） |
| Phase 37／design4「端點恰 20」 | 加任務清單與關掉失敗列，變成 **22**（見 §5） |
| 鏡頭桌面「uploaded → GET latest → 三關彈窗鏈」 | 快門 202 後不開鏈；GET latest 不再承擔「剛拍那張的歸類 payload」 |
| design3 §2.1「待決定補完鏈無待辦窗；建議不持久化」 | 建議改落庫（D16）；待決定點開走完整三關（有待辦建議才開第三窗） |
| Phase 30「實體／待辦建議只出現在上傳回應」 | 建議寫進 `photo` 列，待決定開窗再讀 |

**未推翻：** 定案不可逆（`PATCH` 只接受收件箱照片）、收件箱＝待決定的儲存位、VLM 看不懂最終不留照片、415 格式錯誤仍同步、PDF 一頁一張照片、人確認才釘實體／建待辦、embeddings 一律本機、單一使用者、不做刪除照片、openapi 零 DELETE、Ollama 不進 Docker、`postgresql@14` 完全不動、鏡頭 session 仍在 app 記憶體（worker 不參與配對）。

### 1.2 被否決（不要重開）

| 方案 | 為什麼否決 |
|---|---|
| FastAPI BackgroundTasks／在 web 行程裡背景看圖 | 與 uvicorn 同行程；`--reload`／`restart app` 會丟進行中工作；拉不起獨立兩個 worker |
| 只用 Redis list、自寫 worker 迴圈 | 省 Celery 但要自做 ack／崩潰重送／重試；side project 看起來瘦、維護肥 |
| PDF 每一頁一個 Celery 任務 | 同一份檔會被兩個 worker 拆開；進度列難畫。產品負責人要一檔一任務 |
| 整份 PDF 當重試單位（一頁失敗就從頭再跑） | 已成功的頁會被重做；雲端費用與時間乘上頁數 |
| 進度只掛在上傳頁 | 換頁就看不見還在跑的工作；鏡頭連拍時人也不在上傳頁 |
| 成功列留在進度面板當第二個待決定 | 成功的去處就是待決定；面板只顯示進行中與失敗 |
| 待決定改成獨立長頁表單（對話選項 B）或左右分欄（選項 C） | 產品負責人選 A：沿用彈窗，只加原圖 |
| 處理中的檔先 INSERT 空白 `text` 再補 VLM | 違反「`text` 為空的記錄不存在」；待決定也會出現空白卡 |
| 影像位元組當 Celery 參數／塞 Redis | 多頁 PDF 太大；staging 走磁碟 |
| 關掉失敗列用 `DELETE /ingest-jobs/{id}` | Phase 37 釘死 openapi 零 DELETE |
| 3 個以上 worker、或測試用本機 gemma4 並行 | 產品負責人上限 2；本機看圖會把機器打掛（Phase 48 已踩過） |
| 把 Ollama 搬進 Docker | 仍是 Linux VM，沒有 MLX、也吃不到這台 GPU（design4 否決仍有效） |
| 建議繼續只活在 201 回應、不落庫 | 上傳改 202 後回應裡沒有建議；待辦窗會從此沒有入口 |

---

## 2. 流程

```text
進圖（擇一，不是串起來）
  電腦：一次選 N 個 JPEG／PNG／PDF
  或 無線鏡頭：人按快門，一張一張 POST
        │
        ▼
  FastAPI（仍同步、必須很快）
    格式不對 → 415，不建任務
    鏡頭 token 無效 → 404，不建任務
    其餘 → 寫 data/staging/{job_id}
         → JobStore 記 queued
         → Celery 丟一個「整檔」任務
         → 202 { job_id, filename, content_type }
        │
        ▼
  你立刻可以再選檔／再拍
  右下角面板出現 queued／分析中
        │
        ▼
  兩個 worker 各拿一個檔
    JPEG／PNG：
      VLM 最多 3 次 → embed → INSERT 收件箱 → 原圖＋縮圖落地 → 刪 staging
    PDF：
      拆頁後依序；每頁 VLM 最多 3 次；失敗跳過；成功頁各自 INSERT
      0 頁成功 → 整筆失敗、刪 staging、不留列
        │
        ├─ 成功 → 進度列消失；待決定（N）+1
        └─ 失敗 → 進度列留下（× 可關掉）；庫裡沒有這張

待決定 /ui/pending.html
  縮圖牆（只含已入庫、仍在收件箱的照片）
  點照片 → 歸類彈窗（窗頂原圖）→ 實體 → 有待辦建議才開待辦窗
  定案 → 離開待決定、進資料夾（不可逆，design2 D3）

瀏覽 /ui/browse.html
  【資料夾】｜【待辦】     ← 沒有待決定 tab
```

上傳頁與鏡頭桌面頁**都不再呼叫** `classify_chain.js` 的開鏈時機（檔案可留著給待決定頁組鏈，或待決定頁直接 `openFolderModal`＋`openEntityModal`，與現在 `browse.html` 的待決定分頁相同）。

---

## 3. 範圍

**做：**

- 頂欄四格＋`/ui/pending.html`＋瀏覽頁拿掉待決定 tab
- 歸類彈窗窗頂原圖；「稍後再說」文案改指向待決定頁
- Redis ＋ Celery worker（concurrency=2）
- staging 目錄、JobStore、`run_ingest_job`
- `POST /photos`、`POST /camera/{token}/photos` 改 202
- `GET /ingest-jobs`、`POST /ingest-jobs/{job_id}/dismiss`
- 全站進度面板＋`<input multiple>`
- 鏡頭桌面不開上傳彈窗鏈；快門可連拍
- 對應測試與 `LAUNCH.md`／`CLAUDE.md` 指令區更新
- `photo` 表冪等遷移：實體建議、待辦建議落庫（D16）
- 規格 `.feature` 在產品負責人核准解禁後，改成「收下 ≠ 已入庫」（見 §10）

**不做：**

- 批次歸類、待決定一次勾多張
- 失敗列手動「再試一次」（自動 3 次已做完；要重來就重新選檔／重拍）
- 處理狀態欄位進 `photo` 表
- 水平擴 app replica（鏡頭 session 仍在記憶體）
- Celery Flower、獨立監控 UI
- 把 Redis 發佈到區網
- 雲端物件儲存、S3
- 刪除照片端點
- 詢問流程改版（待決定裡已入庫的照片仍可被問到，與現在收件箱照片相同）

---

## 4. 資料流與冪等

### 4.1 Staging

- 路徑：`data/staging/{job_id}`（副檔名依 content type：`.jpg`／`.png`／`.pdf`）
- `data/` 已在 `.gitignore`；staging 同樣不入版控
- **禁止**把檔案內容放進 Redis 或 Celery 參數；任務 payload 只帶路徑、content type、檔名、`ai_backend` 快照、來源（`upload`／`camera`）
- 成功入庫或最終失敗，都刪 staging
- worker／app 啟動時掃 staging：檔案 mtime 超過 **24 小時**且 JobStore 沒有對應進行中任務 → 當垃圾刪掉（崩潰後 Redis 也丟了的後悔藥）

### 4.2 何時才有 `photo` 列

VLM（該頁／該張）成功、embedding 成功之後才 `INSERT`。202 當下 `photo` 表列數不變。待決定牆只查收件箱，因此不會出現「分析中的空白卡」。

入庫成功後的落點與現在相同：folder＝未分類（收件箱）、原圖＋縮圖在 `data/photos`／`data/thumbs`。另外寫入 D16 的建議欄（資料夾／實體／待辦）。歸類、釘選、建待辦仍靠之後人按的 API，不在 worker 裡自動做。

### 4.3 JobStore（進度面板的來源）

正式實作：Redis hash／JSON，key 例如 `ingest:{job_id}`。  
測試實作：行程內 dict，autouse fixture 每測清空。

清單 API 只回這些狀態：`queued`、`analyzing`、`retrying`、`failed`。  
**成功＝刪掉這筆 job**（或標記後永不出現在 GET）。前端不必自己過濾 success。

每筆至少有：

| 欄 | 用途 |
|---|---|
| `job_id` | 202 回給前端的 id |
| `filename` | 進度列顯示 |
| `content_type` | 圖或 PDF |
| `status` | 上列四種之一 |
| `attempt` | 目前這張／這頁第幾次 VLM（1〜3） |
| `page_count` | PDF 才有；拆頁後才填，未拆前可為 null |
| `pages_done` | PDF 已處理頁數（含跳過） |
| `photo_ids` | 已 INSERT 的 id 列表（崩潰重送用） |
| `error` | 失敗時給人看的短句（不要把 stack 丟給瀏覽器） |
| `ai_backend` | 入列當下的 `local`／`cloud` |
| `source` | `upload`／`camera` |

`GET /ingest-jobs` 同時帶 `pending_count`（收件箱照片數，SQL，不是 Redis），讓頂欄 N 與面板同一次輪詢更新。

關掉失敗列：`POST /ingest-jobs/{job_id}/dismiss`。只准 dismiss `failed`；進行中的不准用這個藏起來。staging 在失敗當下就已刪，dismiss 只是從清單拿掉。

### 4.4 崩潰重送（避免兩張照片）

Celery 任務在 worker 被殺時可能回到佇列。VLM 的 3 次是**任務函式內部**迴圈，**不要**再用 Celery `autoretry` 整份重跑（那會把已 INSERT 的 JPEG 再插一次）。

冪等規則：

- JPEG／PNG：JobStore 已有 `photo_ids` → 視為成功，刪 staging，結束。
- PDF：依 `pages_done` 從下一頁繼續；已成功的頁不重看、不重 INSERT。
- 任務開頭先把 status 改成 `analyzing`。

### 4.5 AI 後端

`PUT /settings/ai-backend` 仍只改 web 行程的 `config.AI_BACKEND`。  
worker 是另一個行程，必須用任務裡的 `ai_backend` 自己建 VLM 客戶端（本機 `OllamaVLM`／雲端 `OllamaCloudVLM`），與 `get_vlm()` 同一套實作、同一份 prompt。

手動煙霧：先切雲端，再上傳／連拍。已在佇列裡的任務不因中途切回本機而改道。

---

## 5. API 契約

現況端點 20。本增量 **20→22**。

| 方法 | 路徑 | 變更 |
|---|---|---|
| `POST /photos` | 改 | 受理成功 **202**，body `{job_id, filename, content_type}`。415 不變。不再於這個請求回 `text`／`suggested_folder`／`folders` |
| `POST /camera/{token}/photos` | 改 | 先驗 token（404）再驗格式（415），其餘與上列相同 **202**。**不再** `set_latest` 成 `UploadResponse` |
| `GET /camera/{token}/latest` | 行為變窄 | 入列不再寫 latest。沒有已完成的 latest → 維持 **204**。桌面不再靠它開彈窗鏈 |
| `GET /ingest-jobs` | **新** | `{jobs: [...], pending_count: N}`。`jobs` 不含成功 |
| `POST /ingest-jobs/{job_id}/dismiss` | **新** | 只對 `failed`；204。找不到 404；不是 failed → 409 |

WebSocket `/camera/{token}/signal` 不變（信令）。手機端在 202 之後即可再拍；可繼續送 `uploaded` 當「這張已進佇列」通知桌面，但桌面**只更新進度／預覽狀態，不開 `classify_chain`**。

清點測試（現有「端點恰 20」「openapi 零 DELETE」）要改數字、並繼續斷言沒有 DELETE。

---

## 6. 頁面

### 6.1 頂欄（全站）

```text
PersonalDocAI    上傳照片 ｜ 待決定（N）｜ 瀏覽資料夾 ｜ 問問題     [AI 本機｜雲端]
```

每一頁的 header 都長這樣（`aria-current` 標當頁）。  
階段甲還沒有 `GET /ingest-jobs`：N 用既有 `GET /folders` 收件箱的 `photo_count` 即可（待決定頁本來就會打這支）。  
階段丙起改由全站 JS 向 `GET /ingest-jobs` 輪詢（約 2 秒），一次帶回 `jobs` 與 `pending_count`，用來更新 N 與右下角進度面板。不要四個 HTML 各寫一套 `setInterval`。

### 6.2 `/ui/pending.html`（新頁，階段甲）

搬現在 `browse.html` 的 `showPending()`：收件箱縮圖牆、空狀態、點開歸類鏈。  
空狀態文案改成分析完成的照片會出現在這裡（不要再寫「上傳時按稍後再說才看得到」當唯一來源——現在**所有**新圖都先來這裡）。

歸類彈窗：`folder_modal.js` 窗頂加 `<img>`，src 用 `/photos/{id}/image`（沒原圖的舊資料灰底占位，與瀏覽牆相同）。實體／待辦彈窗不必再放一次大圖。  
「稍後再說」說明改成留在待決定頁。

階段甲（上傳仍 201）：待決定鏈可暫維持現在的抽屜→實體（無待辦窗），因為上傳鏈還在。  
階段丙（上傳不再開鏈）：待決定必須改走完整三關，建議從 D16 的欄位讀（`GET /folders/{inbox}` 照片摘要比照 `suggested_category` 帶出實體／待辦建議，不必再看一次圖）；沒有待辦建議就不開第三窗（與現在上傳鏈「空關不跳」相同）。

### 6.3 `/ui/browse.html`

拿掉待決定 tab。無 query 時預設資料夾卡片（現在無 query 是待決定）。  
`?tab=folders` 仍可用；`?tab=tasks`、`?folder=N` 不變。  
不要做「舊書籤 browse.html 自動轉址到 pending」——頂欄已經有待決定，多一個 302 容易繞。

### 6.4 `/ui/upload.html`

- `input` 加 `multiple`（階段丙；甲／乙可先維持單檔，但乙起 API 已是 202）
- 每個檔一個 `POST /photos`（前端連發即可，不必再做一個「一次塞 N 個檔」的新後端）
- 拿掉 201 後開 `classify_chain` 的邏輯
- 文案：先收下，分析完進待決定再歸類

PDF 與圖可以混在同一次選檔裡。

### 6.5 鏡頭

- `camera-phone.html`：`POST` 得 202 就允許下一拍；進度用窄條，不擋快門
- `camera-desk.html`：刪「GET latest → classify_chain」；進度走全站面板。WebRTC 預覽、QR、快門、閃光**不改**

### 6.6 進度面板

| 狀態 | 顯示 |
|---|---|
| `queued` | 檔名；PDF 若已知頁數則「檔名（N 頁）」 |
| `analyzing`／`retrying` | 檔名＋第幾次；PDF 加「第 p／N 頁」 |
| 成功 | 不出現（JobStore 已刪） |
| `failed` | 檔名＋短錯誤；右上 × → dismiss |

全部成功（或失敗都 dismiss）→ 面板收起。  
重新整理後，進行中與未 dismiss 的失敗要還在。

---

## 7. Docker 與啟動（階段乙才建）

在既有 `compose.yaml`（`db`＋`app`）加上兩個服務。**不要**新開一份 compose 取代常駐檔。

```text
瀏覽器 / iPhone ──HTTPS :8000──► [app] 只收檔、入列
                                    │
                                    ▼
                                 [redis]   volume: redisdata（AOF）
                                    │
                          Celery 取出任務
                                    ▼
                                 [worker]  concurrency=2
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                 [db]          data/staging      Ollama on Mac
                               data/photos     host.docker.internal
```

**`redis`**

- 映像：官方 Redis 7（alpine 即可）
- 不發佈到 `0.0.0.0`。若為了 host 除錯要發佈，只綁 `127.0.0.1:6379`
- named volume ＋ AOF（`appendonly yes`）：重開 Docker 後進行中的任務與失敗列還在
- healthcheck：`redis-cli ping`
- `restart: unless-stopped`

**`worker`**

- **同一份** app 映像（Dockerfile 不必為 worker 另寫一份）
- command：`celery -A … worker --concurrency=2`（模組路徑實作時定，契約是 concurrency=2）
- 環境：與 app 相同的 `DATABASE_URL`、`OLLAMA_BASE_URL`，外加 `CELERY_BROKER_URL=redis://redis:6379/0`
- volume：至少 `./data`、`./.env`（要寫原圖／縮圖／staging；憑證不必，worker 不聽 HTTPS）
- `depends_on`：`db` healthy、`redis` healthy
- `restart: unless-stopped`
- **不要** `--reload`。Celery 不會跟 uvicorn 一樣盯檔

**`app` 加什麼**

- 環境加同一個 `CELERY_BROKER_URL`
- `depends_on` 加 `redis` healthy（沒有 Redis 就無法 202 入列）

**`compose.dev.yaml`**

- `app` 維持現在的 `--reload` ＋ bind-mount `./app`
- `worker` 也 bind-mount `./app`，否則開發時 worker 還在跑映像裡的舊碼
- 改 Python 後 **必須** `docker compose … restart worker`（Celery 沒有 uvicorn 那種 reload）
- `restart: "no"` 比照現在的 app 開發 overlay，避免開機把開發 worker 拉起來

**啟動（寫進 `LAUNCH.md`／`CLAUDE.md` 指令區，階段乙才改那些檔）：**

```bash
# 常駐（含 redis、worker）
docker compose -f compose.yaml up -d

# 開發
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
```

`docker compose ps --no-trunc` 應看得到 worker 的 `--concurrency=2`。

**測試時用雲端 AI：** 頁首切雲端後再上傳。worker 吃的是入列快照，不是「切了之後才影響已經在跑的任務」。

刻意不進 Compose：Ollama、pytest、`postgresql@14`。pytest 仍在 host、連 `127.0.0.1:5433` 的測試庫。

---

## 8. 錯誤表

| # | 情況 | 誰回 | 結果 |
|---|---|---|---|
| 1 | 非 JPEG／PNG／PDF | HTTP 立刻 | 415；無 job、無 staging |
| 2 | 鏡頭 token 無效／過期 | HTTP 立刻 | 404；不讀檔 |
| 3 | JPEG／PNG 看不懂或呼叫失敗 ×3 | worker | 刪 staging；無 `photo` 列；job=`failed` |
| 4 | PDF 某一頁 ×3 | worker | 跳過該頁；其他頁繼續 |
| 5 | PDF 0 頁成功，或檔無法拆頁 | worker | 同 3 |
| 6 | embedding 失敗 | worker | 尚未 INSERT 則當這次失敗，算進 3 次；3 次後同 3 |
| 7 | 入庫寫檔失敗（現有 cleanup 語意） | worker | 與現在 `_ingest_image` 相同：清掉半成品再標失敗，不留孤兒列 |
| 8 | Redis 當下掛了 | HTTP | 500；最好連 staging 也別留（寫入順序：先 staging 再入列的話，失敗路徑要刪 staging） |
| 9 | dismiss 一筆還在跑的 job | HTTP | 409 |
| 10 | 已定案再 PATCH | 既有 | 409，本文件不改 |

使用者看得到的失敗＝進度列。不要用 `alert`。

---

## 9. 測試策略

沿用三道 autouse 安全網：`reset_tables`、`wire_fake_ai`、`isolated_data_dir`。  
再加第四道：**JobStore 指到記憶體**，pytest **不連真 Redis、不啟動 Celery 容器**。

任務本體：

```text
router 入列 → Celery 只負責呼叫 run_ingest_job(...)
測試        → 直接呼叫 run_ingest_job(...)（FakeVLM／FakeEmbeddings／get_now）
```

既有「When 使用者上傳… Then 系統儲存的照片數量為 1」類測試改成：

1. `POST` 得 **202**
2. 斷言此時 `photo` 列數仍為 0（新釘）
3. 用回傳的 `job_id` 呼叫 `run_ingest_job`
4. 再跑原來的 Then

BDD binder（`test_upload_feature.py`、`test_camera_feature.py`）同樣：When 步驟裡要把該任務跑完，Then 才看得到照片。規格語句改成「收下後分析完成才入庫」（§10），測試才對得上人話。

本增量必加（名稱實作時可調，契約要覆蓋）：

- 202 當下無新列、staging 在、JobStore 為 queued
- FakeVLM 一次成功 → 收件箱一列、staging 消失、job 不在 GET 清單、`pending_count`=1
- FakeVLM 三次 `understood=False` → 列數 0、staging 不在、job=`failed`
- PDF 兩頁、第二頁三次失敗 → 一列照片、job 成功（不在清單）、skipped 語意保留
- PDF 全頁失敗 → 列數 0、failed
- 崩潰重送：job 已有 `photo_ids` 再跑一次 → 列數仍為 1
- dismiss failed → GET 不再列出；dismiss analyzing → 409
- 鏡頭亂 token 仍 404；好 token 202 且可立刻再 POST 第二張
- 清點：端點 22、openapi 無 DELETE
- 前端契約：頂欄含「待決定」；`browse.html` 原始碼不再當預設待決定入口（可用字串釘，比照現有 `片語` 測試）
- QR 尺寸那顆（design4 增量四唯一產品 CSS）不准改小

前端進度面板、多檔選檔：沿 Phase 14／23，**不新增** Playwright 自動化；瀏覽器實操驗收（§12）。

---

## 10. 規格檔（需產品負責人核准解禁）

`docs/spec/` 唯讀。本增量會改上傳「何時算存好」，與 Phase 20／Phase 51 相同，**要你明示核准**才能改 `.feature`。

預期要動的檔（核准後才改，本文件先把方向釘死）：

| 檔 | 改什麼 |
|---|---|
| `上傳照片.feature` | 「上傳後系統儲存」改為：受理後經分析成功才儲存；可一次多檔但不要求 Example 寫 N 張。分析失敗 3 次後數量仍為 0 |
| `無線鏡頭拍攝.feature` | 「走既有上傳並先進未分類」改為先進佇列，分析成功後才在未分類；桌面不在快門當下開彈窗。When 步驟仍可用 FakeVLM 指定理解結果（binder 會把任務跑完） |
| `歸類照片.feature` 等 | 入口從「瀏覽頁待決定 tab」改為「待決定頁」——若 Example 有寫路徑才改；沒寫則不動 |

未核准前：實作可以先讓測試 binder 對齊新 API，但**不要改** `docs/spec/features/`。

---

## 11. 會動到的檔（實作時才寫；此處是契約）

| 檔 | 階段 | 動作 |
|---|---|---|
| `app/static/pending.html` | 甲 | 新建 |
| `app/static/browse.html` | 甲 | 拿掉待決定 tab；預設資料夾 |
| `app/static/folder_modal.js` | 甲 | 窗頂原圖；稍後再說文案 |
| 各頁 `site-header` | 甲／丙 | 四格導覽；丙再掛進度 JS |
| `app/static/progress_panel.js`（名稱可調） | 丙 | 全站唯一進度＋N |
| `app/static/upload.html` | 丙 | `multiple`；拿掉開鏈 |
| `app/static/camera-desk.html` | 丙 | 拿掉 latest→開鏈 |
| `app/static/camera-phone.html` | 丙 | 202 後可再拍；窄條進度 |
| `app/api/routers/photos.py` | 乙 | 入列；抽出 `run_ingest_job` 可給 worker 用 |
| `app/api/routers/camera.py` | 乙 | 202；不 set_latest |
| `app/api/routers/ingest_jobs.py`（名稱可調） | 乙 | GET 清單＋POST dismiss |
| `app/services/ingest_job_store.py` 等 | 乙 | Redis／記憶體兩實作 |
| Celery app ＋ worker 進入點 | 乙 | 新建 |
| `compose.yaml`／`compose.dev.yaml` | 乙 | `redis`、`worker` |
| `requirements.txt` | 乙 | `celery`、`redis`（版本下限與現況 `>=` 風格一致；已知映像與 host 會分岔，重建後要手動煙霧） |
| `db/migrate_design5.sql`（名稱可調） | 乙 | 冪等 `ALTER photo`：實體建議、待辦標題／到期日。正式庫跑兩次證冪等；測庫可走 schema 或同腳本 |
| `db/schema.sql` | 乙 | 與遷移對齊（測庫重建用） |
| `tests/conftest.py` | 乙 | 記憶體 JobStore；eager 呼叫 `run_ingest_job` 的 helper |
| 既有大量 `201` 斷言 | 乙 | 改 202＋跑任務 |
| `LAUNCH.md`、`CLAUDE.md` 指令區 | 乙 | 啟動／restart worker／雲端煙霧 |
| `docs/spec/features/*.feature` | 乙或丙末 | **僅在核准解禁後** |

**不改：** `postgresql@14`、詢問 workflow、定案 `PATCH` 規則、openapi 零 DELETE。`photo` 表只加建議欄，不加處理狀態、不加 job_id（冪等靠 JobStore 的 `photo_ids`）。

---

## 12. 驗收清單（給產品負責人）

**階段甲**

- [ ] 頂欄為「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」
- [ ] 開 `/ui/pending.html` 看得到收件箱照片；點一張：彈窗**最上面是原圖**，下面仍是四個歸類出口
- [ ] `/ui/browse.html` 預設是資料夾卡片，沒有待決定 tab；待辦 tab 仍在
- [ ] 定案後照片離開待決定、N-1；已定案不能再改夾

**階段乙**

- [ ] `pytest -q` 全綠、0 skipped
- [ ] 單檔上傳 HTTP 202；當下待決定不會多一張；worker／測試跑完任務後才出現
- [ ] Fake 三次失敗：待決定不出現、磁碟 staging 不留
- [ ] `docker compose ps` 看得到 `redis` 與 `worker`；worker 為 2 個 concurrency
- [ ] 頁首切雲端後上傳，worker log 的 `backend=cloud`（手動）

**階段丙**

- [ ] 電腦一次選 3 張：3 列進度，可立刻再選下一批，不必等 VLM
- [ ] 成功列自己消失，N 加上去；失敗列留下，× 關掉後面板可收起
- [ ] 換到問問題頁，進行中的列還在
- [ ] 手機連拍至少 2 張不必等第一張看完；桌面**不**跳出歸類鏈
- [ ] 一份兩頁 PDF：進度一列；成功頁進待決定
- [ ] 待決定點開：窗頂有原圖；有待辦建議會開第三窗，沒有則不跳（空關不跳）
- [ ] console 沒有非預期錯誤；`alert`／`confirm`／`prompt` 仍禁用

---

## 13. 風險與已知限制

- **本機 VLM 仍然慢。** 兩個 worker 只讓你「一邊看兩張」，不能讓 gemma4 變快。測試請用雲端。
- **`--reload` 救不了 worker。** 改 `app/` 後開發模式記得 `restart worker`，否則會出現「HTTP 已是新碼、分析還是舊碼」。
- **Redis volume 不是正式庫。** 丟了最多丟進度列與尚未分析的 staging 對應關係；24 小時掃把會清孤兒檔。`photo` 正本仍在 Postgres ＋ `data/photos`。
- **鏡頭 token 仍在 app 記憶體。** 重啟 app＝配對失效，與現在相同；已 202 的檔由 worker 繼續做完，不依賴 token。
- **host `.venv` 與映像套件分岔**（design4 已知）：加了 Celery 之後，重建映像仍要手動煙霧一次上傳。

---

## 14. 決策紀錄（對話摘要）

| 題 | 產品負責人 | 記入 |
|---|---|---|
| VLM 失敗怎麼辦 | 重試 3 次（含第一次），再走「整筆刪掉」 | D10 |
| 待決定點開的介面 | 仍是彈窗，窗頂加原圖 | D2 |
| 進度面板範圍 | 全站，換頁不消失 | D8 |
| 成功列 | 自動消失；失敗留下 | D9 |
| PDF | 進佇列；一檔一列；**一個 worker 處理整個檔**（不論幾頁） | D11 |
| PDF 重試單位 | 每一頁各自 3 次，失敗跳過；0 頁成功才整筆失敗 | D12 |
| 技術骨架 | Redis ＋ Celery，最多兩個 worker | D5、D6 |
| 202 後建議怎麼還在 | 入庫時寫進 photo（比照 suggested_category） | D16 |
