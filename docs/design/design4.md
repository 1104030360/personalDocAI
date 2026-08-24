# PersonalDocAI — 設計文件（增量四）：照片詳情、AI 計時、Docker 常駐

> **一句話：資料夾與待辦點開同一顆唯讀彈窗看圖＋說明；每次真的呼叫 AI（看圖／embedding／路由／回答／實體建議）都在 log 打前後秒數；最後才把正式庫與 app 搬進 Docker。**

> 🎯 **仍是 side project：不要過度設計。** 只做本文件寫到的事。詢問流程、定案鎖定、三關彈窗鏈、本機 embedding 同源，全部維持 design3.md／design2.md／design1.md／design.md v4 不變。

| 項目 | 內容 |
|---|---|
| 前提 | design3.md（Phase 28〜37）已落地；AI 後端開關（2026-08-22）已在、端點 19 |
| 目的 | 瀏覽時看得到一張照片的完整說明；開發時看得到每次 AI 花多久；開機後服務常駐且正式庫只活在 Docker volume |
| 狀態 | 產品負責人 2026-08-23 grill 拍板（Q1〜Q6），**可寫進本文件** |
| 衝突時誰贏 | 本文件列出的推翻項以本文件為準；未提及的行為仍以 design3.md、design2.md、design1.md、design.md v4 為準 |

---

## 0. 實作計劃總序（不可對調）

本增量拆三段。**Docker 一定最後做。** 前面兩段沒有經過產品負責人確認「沒問題」，不准寫 `compose.yaml`、不准 `pg_dump`、不准停 brew `@17`、不准動正式庫。

```text
階段甲  照片詳情（功能 1＋3 一起）
        GET /photos/{id} ＋ 全站唯一唯讀彈窗
        資料夾牆可點、待辦列改彈窗（不再開新視窗）
            │
            ▼
階段乙  AI 計時 log（功能 2）
        看圖／embedding／路由／回答／實體建議
        本機與雲端同一套格式；PDF 每一頁各打一組
            │
            ▼
     ★ 閘門 G1：產品負責人確認階段甲＋乙沒問題
        驗收清單見 §8.3。沒點頭＝停在這裡。
            │
            ▼
階段丙  Docker 常駐與正式庫遷移（功能 4，最後才做）
        先 5434 並行驗證 → 過閘門 G2 才停 brew → 再起 app
```

| 階段 | 做什麼 | 何時可以開始 | 何時算過 |
|---|---|---|---|
| **甲** | 詳情 API＋唯讀彈窗 | 本文件拍板後即可 | `pytest -q` 綠；瀏覽器：資料夾點開彈窗、待辦點開彈窗且**沒有**新分頁 |
| **乙** | AI 計時 log | 甲合併後即可（可與甲同 PR，但驗收分開看） | 上傳／歸類／詢問／「再建議一個」的 log 都看得到開始／結束／秒數 |
| **閘門 G1** | 人確認甲＋乙 | 甲＋乙都過驗收 | 產品負責人明示「甲乙沒問題，可以做 Docker」 |
| **丙** | Docker | **只有 G1 通過之後** | §12 驗收清單全過 |

**禁止：** 為了趕 Docker 先改 `.env` 連線字串、先停 brew、先建空 volume。  
**禁止：** 把階段丙的檔案「先寫好放著」——`compose.yaml`／`Dockerfile` 也算階段丙，G1 沒過不准建。

---

## 1. 已拍板決策（2026-08-23 grill）

| # | 決策 | 內容 |
|---|---|---|
| D1 | 共用唯讀彈窗 | 資料夾牆點照片、待辦列點一列，開**同一顆**彈窗：上面大圖、下面 `text`。待辦再多一行標題／到期日。不開新視窗（`target=_blank` 拿掉） |
| D2 | 只准看、不准改夾 | 這顆窗是唯讀。沒有歸類按鈕。design2「定案不可逆」仍有效。待決定分頁點照片**仍走歸類鏈**，不走這顆窗 |
| D3 | 詳情欄位 | 彈窗顯示 `text` ＋ metadata 四欄（`category`／`location`／`items`／`content_time`） |
| D4 | 空欄仍列出 | 四欄都畫出來；值是空／空陣列就寫「無」 |
| D5 | 新端點 | 新增 `GET /photos/{id}`。清單端點（`GET /folders/{id}`、`GET /tasks`）維持瘦的，點開再抓。端點 **19→20** |
| D6 | 找不到 vs 沒原圖 | 沒這張照片 → **404**。有這列但 `original_path` 為 NULL（遷移舊照片）→ **200**，`image_url` 為 null，彈窗灰底占位 |
| D7 | AI 計時粒度 | 每一張圖／PDF 每一頁的看圖、embedding **各打一組**開始／結束。詢問：路由、回答、（走向量時）embedding 各一組。失敗也打結束，秒數照記，標 `ok=false` |
| D8 | 同一輪四項都做 | 順序是甲 → 乙 → **人確認** → 丙。不是四項同時開工 |
| D9 | Docker 切法 | app＋db 兩個 container；正式庫 dump／restore 進 `pgvector/pgvector:pg17` named volume；停 brew `@17`（資料目錄先留著當後悔藥）；Ollama 留 Mac 本機；開機靠 Docker Desktop ＋ `restart: unless-stopped` |
| D10 | 開發熱重載 | 仍在開發階段：日常改碼用 `compose.dev.yaml` 覆寫，容器內 `uvicorn --reload` ＋ bind-mount `./app`。開發也 `-d`，紀錄用 `docker compose logs -f app`。**不寫進**常駐用的 `compose.yaml`（開機拉起的那份不准 `--reload`） |

### 1.1 本增量明確推翻的舊決策

| 舊決策 | 本文件改成 |
|---|---|
| design2.md D4「資料夾 tab 的縮圖牆純瀏覽，照片不可點、不開彈窗」 | 可點，但只開**唯讀詳情**。仍不能改夾、不開歸類窗 |
| design3.md §7「待辦能列、能點回來源圖即可」（開 `/photos/{id}/image` 新分頁） | 改開頁內 modal；圖在窗裡，不新開 window |
| design1.md「不做列出全部照片的端點」的誤解空間 | **仍不做**列出全部。允許 **依 id 讀一張** 的 `GET /photos/{id}` |
| Phase 37／開關後「端點恰 19」 | 加一支，變成 **20**。清點測試要改數字 |

**未推翻：** 定案不可逆、待決定才是第二歸類入口、三關彈窗鏈、不做刪除、單一使用者、embeddings 一律本機、Ollama 不進 Docker、`postgresql@14` 完全不動、規格 `.feature` 本輪不改（詳情與 log 屬 design 層，以測試＋瀏覽器實操把關）。

### 1.2 被否決（不要重開）

| 方案 | 為什麼否決 |
|---|---|
| 資料夾點開再歸類／改夾 | 推翻 design2 定案鎖定；產品負責人選「只准看」 |
| 待辦彈窗裡編輯或刪待辦 | 規格仍禁刪除；本輪只看 |
| 清單一次帶齊 metadata（grill Q3 選項 A） | 產品負責人選新端點，清單維持瘦 |
| 彈窗只顯示 `text`、不顯示四欄 | 產品負責人選四欄都列、空的寫「無」 |
| 整份 PDF 只打一筆總時間 | 產品負責人要每頁各一組，才看得出哪一頁慢 |
| 資料夾與待辦各做一顆不一樣的窗 | 共用一顆，待辦只多一行 |
| 先做 Docker 再做 UI／log | 庫遷移 P0；與產品行為分開驗收 |
| G1 沒過就先建 Compose／Dockerfile「放著」 | 階段丙的檔案也算階段丙 |
| 常駐 `compose.yaml` 直接加 `uvicorn --reload` | 開機拉起的行程不該盯檔案；鏡頭 session 在記憶體，reload＝配對失效。開發另用 overlay |
| Ollama 進 Docker | Mac Docker 是 Linux VM，沒有 MLX、也吃不到這台 GPU |
| 正式庫跑 `schema.sql` | 開頭是 `DROP TABLE`；搬運必須 dump／restore |
| `docker compose down -v` | 會刪 named volume＝刪正式庫 |
| app 水平擴兩個 replica | 鏡頭 session 在記憶體 |
| 把 `data/` 打進映像 | 原圖在 host，container 只 bind-mount |

---

## 2. 流程

```text
瀏覽／ui/browse.html
  ├─ 【待決定】點照片
  │     → 仍走抽屜→實體（無待辦窗）     ← 本文件不改
  ├─ 【資料夾】→ 縮圖牆 → 點照片
  │     → GET /photos/{id}
  │     → 唯讀彈窗：大圖 ＋ text ＋ 四欄
  └─ 【待辦】點一列
        → 不再開新分頁
        → GET /photos/{id}
        → 同一顆彈窗：待辦標題／到期日 ＋ 大圖 ＋ text ＋ 四欄

上傳／歸類／鏡頭／詢問／再建議一個
  → 每次真的呼叫模型前後打 AI log（§6）
        │
        ▼
  ★ 閘門 G1（人確認甲＋乙）
        │
        ▼
Docker：pg_dump → 5434 灌入 → 對快照 → 停 brew → 5433 切過來 → 起 app
```

---

## 3. 範圍

**做（階段甲）**

- `GET /photos/{id}`
- `static/photo_detail_modal.js`（全站唯一一份）
- `browse.html`：資料夾牆可點；待辦列改 `<button>` 開窗
- `style.css`：唯讀彈窗樣式（沿用 fm 視覺，另用 `pd-` id）

**做（階段乙）**

- 共用計時 helper
- 包住看圖、embedding、路由、回答、實體建議（本機＋雲端）
- 既有「AI 看圖開始／完成」對齊新格式，不要兩套並行

**做（階段丙，G1 之後）**

- `compose.yaml`、`Dockerfile`、`.dockerignore`、`db/docker-init/01-create-test-db.sql`
- `.env` 連線字串加使用者；`tests/conftest.py` 對齊
- 正式庫 dump／restore；停 brew `@17`（不 uninstall）
- CLAUDE.md 指令區改 `docker compose up -d`（丙驗收時才改）

**不做**

- 改 `GET /folders/{id}` 的五鍵摘要、改 `GET /tasks` 的瘦契約
- 新 GET「列出全部照片」
- 規格 `.feature` 本輪不改
- Ollama 進 Docker、停／改 `postgresql@14`、`brew uninstall postgresql@17`
- 把本文件以外的產品行為（歸類、詢問、彈窗鏈）順便重寫

---

## 4. 階段甲 — 照片詳情

### 4.1 誰可以開這顆窗

| 入口 | 現在 | 改成 |
|---|---|---|
| 資料夾縮圖牆 | `div.photo-static`，點不動 | `<button>`，點了開唯讀窗 |
| 待辦列 | `<a target="_blank" href="/photos/{id}/image">` | `<button>`，點了開同一顆窗 |
| 待決定縮圖牆 | 開歸類彈窗鏈 | **不改** |
| 上傳／鏡頭彈窗鏈 | 抽屜→實體→待辦 | **不改** |

### 4.2 彈窗長相

順序固定：

1. **待辦列才有：** 標題、到期日（無到期日寫「無到期日」）。資料夾進來就不畫這一行。
2. **圖：** `<img src="{image_url}">`。`image_url` 為 null → 灰底「無原圖」（與縮圖牆占位同一態度）。
3. **description：** `text`（永遠顯示；空字串不當正常路徑，有列就該有 text）。
4. **四欄，每一欄都在：**
   - 類別：`category`，空 →「無」
   - 地點：`location`，空 →「無」
   - 物品：`items` 用頓號串起來；`[]` →「無」
   - 內容日期：`content_time`，空 →「無」

關閉：有 ×、吃 Esc、點暗色區可關。這顆**不是** design2 那種關不掉的強制窗。  
禁用 `alert`／`confirm`／`prompt`。載入中／404 紅字寫在窗內。動態內容一律 `textContent`。

### 4.3 前端契約

新檔 `app/static/photo_detail_modal.js`，前綴 `pd-`，只靠 callback 對外：

```text
openPhotoDetailModal({
  photoId: 7,
  task: null 或 { title, due_date }   // 待辦列才傳
});
```

行為：

1. 開窗、畫「載入中」。
2. `GET /photos/{photoId}`。
3. 200 → 畫圖＋欄位。
4. 404 → 窗內紅字「找不到這張照片」。
5. 網路失敗 → 窗內紅字，不 `alert`。

`browse.html` 掛這一份。其他頁本輪不必掛（上傳鏈不看詳情）。

### 4.4 `GET /photos/{id}`

**路徑：** `GET /photos/{photo_id}`  
**放哪：** `app/api/routers/photos.py`（與 thumbnail／image／PATCH 同一支 router）。  
**SQL：** 既有 `photo_repository.fetch_photo()`（`PHOTO_COLUMNS` 已含 text／四欄／路徑）。router **零 SQL**。不重算 embedding、不呼叫 VLM。

**404：** `fetch_photo` 回 None。  
**200：** 有這列就 200，不管檔案在不在磁碟。讀圖端點（`/image`、`/thumbnail`）仍是「路徑 NULL 或檔案不在 → 404」——那是**開圖檔**，跟這支 JSON 無關。彈窗用 `image_url === null` 決定占位；若 URL 有值但檔被刪，`<img>` 載入失敗再降級占位（前端做，不當 404 整窗）。

**回應 `PhotoDetailOut`（新模型，放 `app/schemas/photo.py`）：**

```text
{
  "id": 7,
  "text": "一張 Target 收據，買了可樂。",
  "metadata": {
    "category": "收據",
    "location": "Target",
    "items": ["可樂"],
    "content_time": "2026-08-10"
  },
  "thumbnail_url": "/photos/7/thumbnail" 或 null,
  "image_url": "/photos/7/image" 或 null,
  "uploaded_at": "2026-08-18T10:00:00+08:00"
}
```

- `metadata` 重用既有 `PhotoMetadata`（四欄、不多不少）。
- `thumbnail_url`：`thumbnail_path` 有值才給網址，**不洩硬碟路徑**。
- `image_url`：`original_path` 有值才給網址。
- **不回** embedding、不回 folder 物件、不回 suggested_category、不回實體清單。那些不是這顆窗要的。
- `content_time` 外送 ISO 日期字串，與上傳回應同一慣例；DB 的 date → `isoformat()`。

**不新增** `GET /photos`（列出全部）。design1 那條禁令仍有效。

### 4.5 會動到的檔（階段甲）

| 檔 | 動作 |
|---|---|
| `app/schemas/photo.py` | 新增 `PhotoDetailOut` |
| `app/api/routers/photos.py` | 新增 `GET /photos/{photo_id}` |
| `app/static/photo_detail_modal.js` | 新建 |
| `app/static/browse.html` | 資料夾牆可點；待辦改 button；掛 modal |
| `app/static/style.css` | `pd-` 彈窗（紙白／琥珀，對齊 fm） |
| `tests/integration/test_photo_detail.py` | 新建：200 欄位、404、舊照片 image_url null、不洩路徑 |
| `tests/integration/test_ask_three_paths.py`（或清點測試） | 端點數 19→20 |
| `tests/integration/test_folders_endpoint.py` | **不改**五鍵摘要 |

`fetch_photo` 不必新 SQL。

---

## 5. 階段乙 — AI 計時 log

### 5.1 要包哪些呼叫

「用到 AI」＝會打 Ollama（本機或 Cloud）的那段。**前後**＝呼叫前一行開始、return／raise 後一行結束。秒數用 `time.monotonic()`。

| kind | 何時 | backend | model |
|---|---|---|---|
| `vlm` | `understand()`（單圖、PDF 每一頁、無線鏡頭入庫） | `config.AI_BACKEND` | 本機 `VLM_MODEL`／雲端 `OLLAMA_CLOUD_VLM_MODEL` |
| `embed` | `embed_document`（上傳每張／每頁）；`embed_document`（PATCH 歸類重算）；`embed_query`（詢問走向量） | **永遠 `local`** | `EMBEDDING_MODEL` |
| `route` | `router.route()` | `config.AI_BACKEND` | 本機 `LLM_MODEL`／雲端 `OLLAMA_CLOUD_LLM_MODEL` |
| `answer` | `answerer.answer()` | 同上 | 同上 |
| `entity_suggest` | 「再建議一個」文字 LLM | 同上 | 同上 |

不計時（不是模型推論）：PDF 渲染、存檔、縮圖、SQL、WebRTC、QR、開關 GET／PUT。

### 5.2 格式（本機／雲端同一套）

兩行一組，方便 grep：

```text
AI 開始 kind=vlm backend=local model=gemma4
AI 結束 kind=vlm backend=local model=gemma4 elapsed_s=123.4 ok=true
```

失敗：

```text
AI 結束 kind=vlm backend=cloud model=gemma4 elapsed_s=0.1 ok=false
```

- `elapsed_s` 一位小數（對齊現在的看圖 log）。
- 看圖成功可在結束行後面加人類可讀摘要（字數、建議類別），但 **kind／backend／model／elapsed_s／ok 必須在**，方便用 `kind=embed` 過濾。
- 既有 `AI 看圖開始`／`AI 看圖完成（N.N 秒）` **改走這套**，不要舊新兩套並行。

PDF 三頁＝三組 `vlm` ＋三組 `embed`（某一頁 422 跳過＝那頁 `vlm` 的 `ok=false`，該頁不打 `embed`）。  
詢問走 metadata／entity／task＝沒有 `embed` 那一組（沒呼叫 `embed_query`）。走 vector 才有。

### 5.3 實作位置

抽一個小 helper（建議 `app/services/ai_timing.py`），context manager：

```text
with log_ai("vlm", backend=..., model=...):
    understanding = vlm.understand(...)
```

例外往外傳（422／500 語意不變），helper 只負責打結束＋`ok=false`。

包的呼叫點：

- `photos._ingest_image`：看圖、embedding（鏡頭與 PDF 每頁都走這裡，包一次就夠）
- `photos.assign_folder`：歸類重算 embedding
- `ask_workflow.route_node`：路由
- `retrieval_service.vector_search`（或 `embed_query` 那一行）：詢問 embedding
- `ask_workflow.generate_node`：回答
- `entity_suggestion_service` 本機＋雲端各一處

pytest 的 Fake 也會打 log（秒數接近 0）。可用 `caplog` 抽樣確認有開始／結束／kind；**不要**把秒數寫死當驗收。真模型秒數只做手動煙霧。

### 5.4 會動到的檔（階段乙）

| 檔 | 動作 |
|---|---|
| `app/services/ai_timing.py` | 新建 helper |
| `app/api/routers/photos.py` | 看圖改走 helper；補 embedding 計時 |
| `app/services/ask_workflow.py` | route／answer |
| `app/services/retrieval_service.py` | 向量路的 embed_query |
| `app/services/entity_suggestion_service.py` | 本機＋雲端 |
| `tests/unit/test_ai_timing_unit.py` | helper：成功／例外都有結束行、ok 對、秒數 ≥ 0 |
| `tests/integration/test_ai_timing_log.py` | 上傳一張、詢問向量、詢問非向量（無 embed）、再建議一個——`caplog` 看 kind |

---

## 6. 階段甲＋乙的測試與前端驗收

**自動化（甲）**

- 有照片 → 200，鍵恰為 id／text／metadata／thumbnail_url／image_url／uploaded_at
- metadata 恰四鍵，重用 `PhotoMetadata`
- 沒這 id → 404
- `original_path` NULL → 200 且 `image_url` 為 null
- JSON 不含硬碟路徑、不含 embedding
- `/openapi.json` 運算元數 **20**；有 `GET /photos/{photo_id}`；DELETE 仍 0

**自動化（乙）**

- helper 單元測試
- 上傳假 VLM 路徑看得到 `kind=vlm` 與 `kind=embed`
- 詢問走 vector 看得到 `route`＋`embed`＋`answer`；走 metadata 沒有 `embed`

**瀏覽器（甲，產品負責人確認 G1 用）**

- 資料夾牆點一張：彈窗、大圖、text、四欄；Esc 可關；背後仍是資料夾牆
- 空欄顯示「無」
- 待辦點一列：**沒有**新分頁；窗頂有標題／到期日；下面同樣是圖＋說明
- 待決定點一張：仍開歸類窗，不是詳情窗
- 舊照片無原圖：灰底占位，窗還是開得起來

**終端機（乙，G1 用）**

- 本機看圖一張：`kind=vlm` 與 `kind=embed` 各一組
- 切雲端再上傳：`vlm` 的 `backend=cloud`，`embed` 仍 `backend=local`
- 問一句語意題：`route`／`embed`／`answer`
- PDF 兩頁：兩組 `vlm`、兩組 `embed`

---

## 7. 閘門 G1（階段丙的唯一入場券）

同時成立才能做 Docker：

- [ ] 階段甲自動化全綠
- [ ] 階段乙自動化全綠
- [ ] 全量 `pytest -q` 與開工前同顆數關係合理（只多甲乙新測試；既有 2 skipped 仍 skip）
- [ ] 產品負責人做過 §6 瀏覽器三條（資料夾／待辦／待決定）
- [ ] 產品負責人看過 §6 終端機 log 樣本，格式可接受
- [ ] 產品負責人明示：「甲乙沒問題，可以做 Docker」

少任何一項，階段丙不准開始。實作者不得自行把 G1 勾過。

---

## 8. 階段丙 — Docker 常駐與正式庫遷移（最後才做）

> **本節在 G1 通過之前只是設計。不准建檔、不准執行遷移指令。**

### 8.1 這節解決什麼

電腦開著就能用檔案櫃，重開機後 Docker 自動把服務拉起來。資料庫不再靠 brew `postgresql@17:5433`，改由 `pgvector/pgvector:pg17` 的 named volume 活著。

拍板路線（D9）：

> `pg_dump` 正式庫 → 灌進 Docker volume → 停掉 brew `@17`（避免兩套庫並存）→ 之後備份／重開機只靠 Docker。

### 8.2 為什麼這樣切 container

| 單位 | 放哪 | 為什麼 |
|---|---|---|
| PostgreSQL 17 + pgvector | **自己的 container `db`** | 官方映像、資料生命週期比 app 長、重開 app 不丟庫 |
| FastAPI / uvicorn | **自己的 container `app`** | 對外 HTTPS、WebSocket、上傳、詢問 |
| Ollama（`gemma4`、`gemma4:e2b-mlx`、`bge-m3`） | **Mac 本機，不進 Docker** | Docker Desktop on Mac 是 Linux VM，沒有 MLX、也吃不到這台 GPU。Embedding 必須本機 `bge-m3`，跟庫裡既有向量同源，雲端開關管不到它 |
| 原圖／縮圖 `data/`、mkcert `certs/` | bind-mount 進 `app` | 檔在 host，container 只讀寫 |
| `postgresql@14:5432` | **完全不動** | 裡面是別的專案（wanderlove、fse_chat_room） |

不要把 app 跟 Postgres 塞同一個 container。不要用 `network_mode: host`（Docker Desktop Mac 行為跟 Linux 不同，Compose 服務名 DNS 也會失效）。

```text
iPhone / 瀏覽器 ──HTTPS :8000──► [app]
                                    │  Compose 預設 network
                                    ▼
                                 [db]  volume: pgdata
                                    │
[app] ──host.docker.internal:11434──► Ollama（Mac）
```

官方依據：

- 容器連 host 服務用 `host.docker.internal`：<https://docs.docker.com/desktop/features/networking/networking-how-tos/>
- Compose 服務名當 DNS：<https://docs.docker.com/compose/how-tos/networking/>
- 發佈埠 `HOST:CONTAINER`：<https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/>

### 8.3 現況契約（實作時不能弄丟）

- 正式庫名：`PersonalDocAI`；測試庫名：`PersonalDocAI_test`
- 現在連線：`postgresql://localhost:5433/PersonalDocAI`——**沒寫帳號密碼**，psycopg 用 macOS 登入帳號
- `tests/conftest.py` 寫死測試庫 URL，並斷言 URL 含 `PersonalDocAI_test` 才准清表
- `schema.sql` 開頭是 `DROP TABLE`——**只能打測試庫**
- 正式庫結構靠歷史遷移堆起來，搬運必須 dump／restore
- 原圖在 host `data/`；DB 只記相對路徑
- 鏡頭 token 全在記憶體；重啟 app＝配對失效（既有行為）
- 相機 QR：用 `https://192.168.x.x:8000` 開桌面頁；container 內猜 IP 常猜出 `172.x`

搬進 Docker 之後，連線字串一定會多出使用者（官方映像強制有 `POSTGRES_USER`）。這是對 `.env` 與 `conftest.py` 的契約變更，必須寫進步驟。

### 8.4 目標架構

**`db`**

- 映像：`pgvector/pgvector:pg17`
- 容器內埠：5432
- host 對外：`127.0.0.1:5433:5432`（只綁本機，區網打不到 Postgres）
- volume：`pgdata` → `/var/lib/postgresql/data`
- `POSTGRES_DB=PersonalDocAI`
- init 腳本再建 `PersonalDocAI_test`（只在 volume 第一次誕生時跑）
- healthcheck：`pg_isready`
- `restart: unless-stopped`

**`app`**

- 自建 `Dockerfile`：Python 3.12-slim，`pip install -r requirements.txt`
- `uvicorn app.main:app --host 0.0.0.0 --port 8000`，掛 mkcert 憑證（**這份常駐指令沒有 `--reload`**）
- `ports: ["8000:8000"]`（發到 0.0.0.0，手機才連得到）
- `DATABASE_URL=postgresql://postgres@db:5432/PersonalDocAI`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- mount：`./data`、`./certs`、`.env`（常駐只掛資料與憑證，**不掛原始碼**——程式在映像裡）
- `depends_on: db`（`condition: service_healthy`）
- `restart: unless-stopped`
- **只能一個 replica**

**刻意不進 Compose：** Ollama、pytest（仍在 host 跑、連 `127.0.0.1:5433` 的測試庫）、`postgresql@14`。

#### 8.4.1 開發熱重載（現在還在開發階段，D10）

你猜得對：**開關寫在 Compose，不是寫在 Dockerfile。**  
Dockerfile 負責「映像裡有哪些套件」；要不要盯檔案重啟，是**啟動指令**的事，所以放 yaml。

但**不要**把 `--reload` 加在常駐那份 `compose.yaml`。理由：

| | 常駐 `compose.yaml` | 開發 overlay `compose.dev.yaml` |
|---|---|---|
| 何時用 | 開機自動拉起、鏡頭真機驗收 | 日常改 Python／HTML／CSS |
| 原始碼 | 打進映像 | bind-mount `./app` 進容器 |
| 啟動 | `uvicorn …`（無 `--reload`） | 同一條加上 `--reload` |
| 改碼要重啟嗎 | 要重建映像（或之後再 overlay） | 存檔後 uvicorn 自己重載 |
| 鏡頭 session | 穩，除非你手動重啟 container | 一存檔就失效（跟現在 host 開 `--reload` 一樣） |

開發時兩份疊在一起（後面的覆寫前面的 `command` 與 `volumes`），**也用 `-d` 背景跑**。重載與看圖秒數一律用 Docker log 看（產品負責人 2026-08-23 指定）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app
```

`logs -f` 是跟著看、不中斷；`Ctrl+C` 只離開 log，**容器繼續跑**。要停 app 用下面切換段落的 `stop`。

`compose.dev.yaml` 對 `app` 只覆寫這幾項（階段丙才建檔，此處是契約）：

```yaml
# compose.dev.yaml —— 只在開發疊上去，開機常駐不要帶這份
services:
  app:
    command: >
      uvicorn app.main:app
      --host 0.0.0.0 --port 8000
      --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
      --reload
    volumes:
      - ./app:/app/app          # 原始碼＋static；容器才能看到你剛存的檔
      - ./data:/app/data        # 與常駐相同
      - ./certs:/app/certs
      - ./.env:/app/.env
    restart: "no"               # 開發用 -d 仍不要 unless-stopped，免得開機把 --reload 拉起來
```

為什麼還要 mount `./app`：`--reload` 盯的是**容器裡的檔案**。若程式只在映像裡、沒掛進來，你在 Mac 存檔，容器看不到，reload 永遠不會觸發。

不採用 Docker Compose Watch（`develop.watch` / `docker compose watch`）當本輪方案：那是「把檔 sync 進容器再重啟服務」。我們已經有 uvicorn 自己的 `--reload`，再加 Watch 是第二套重啟，side project 不夠單純。官方也說 Watch 是 bind-mount 的補充，不是替代：<https://docs.docker.com/compose/how-tos/file-watch/>

**開發時仍要手動重來的情況（`--reload` 救不了）：**

- 改 `.env`（`config.py` 在 import 時讀一次；沒有 `.py` 變動就不會重載）
- 改 `requirements.txt`（要重建映像：`docker compose build app`）
- 改 `certs/`（HTTPS 行程已握著舊檔）
- 正在配對鏡頭：reload＝token 清空，重產 QR（Phase 36 既有行為）

**鏡頭真機驗收、開機常駐**只用：

```bash
docker compose -f compose.yaml up -d
```

不要帶 `compose.dev.yaml`。

**怎麼切換（同一套 db，只換 app 怎麼啟動）**

沒有頁面上的開關。Compose 看的是你**這次指令帶了哪幾份 yaml**。兩種模式共用同一個專案、同一個 `pgdata` volume、同一個 `app` 容器名；切換＝先停再換指令啟動。**禁止** `docker compose down -v`（`-v` 會刪正式庫）。

```bash
# 現在跑的是哪一種
docker compose ps
# 開發中：COMMAND 欄會看到 --reload
# 常駐：看不到 --reload，且 app 是 Up（detached）
```

開發 → 常駐（要驗鏡頭、或下班讓它自己跑）：

```bash
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d
```

常駐 → 開發（開始改碼）：

```bash
docker compose -f compose.yaml stop app    # db 繼續活著，不必重灌
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app
```

`logs -f` 的 `-f` 檔案列表與 `up -d` 必須同一組，才找得到這個 app 容器。  
切換當下 app 一定重啟一次 → 鏡頭 token 清空，QR 要重產。資料庫與 `data/` 照片不受影響。

記法：`-f` 出現幾次、順序都要照抄。只打 `docker compose up` 時，Compose 預設只讀 `compose.yaml`（常駐）。開發一定要**兩份都寫**，而且 `compose.dev.yaml` 放後面（後面覆寫前面）。開發與常駐都 `-d`；差別只在有沒有帶 `compose.dev.yaml`。

**帳號：** 使用者 `postgres`；`POSTGRES_HOST_AUTH_METHOD=trust`；Postgres 只發佈到 `127.0.0.1:5433`。host 上 psql／pytest 用 `postgresql://postgres@localhost:5433/…`。互動 shell 既有 `PGPORT=5433` 可留；停 brew 後加 `PGUSER=postgres`。

**為什麼 host 埠繼續用 5433：** 停掉 brew 後 5433 會空出來；pytest 與舊文件幾乎不用改埠；不跟 `@14` 的 5432 打架。切換當下不能直接在 5433 起 Docker（brew 還佔著）→ 先 5434 驗證再改回 5433。

### 8.5 會動到的檔（只在階段丙寫）

| 檔 | 動作 |
|---|---|
| `compose.yaml` | 新建。`db` + `app`，named volume `pgdata`；app **無** `--reload` |
| `compose.dev.yaml` | 新建。開發 overlay：`--reload` ＋ bind-mount `./app`。不入常駐啟動指令 |
| `Dockerfile` | 新建。Python 3.12-slim、uvicorn |
| `.dockerignore` | 新建。排除 `.venv/`、`.git/`、`data/`、`certs/`、`.env`、`docs/`、`tests/` |
| `db/docker-init/01-create-test-db.sql` | 新建。`CREATE DATABASE "PersonalDocAI_test";` |
| `.env` | 改 `DATABASE_URL` 使用者；app 容器內另用 compose 覆寫成 `@db:5432`。**不入版控** |
| `tests/conftest.py` | 測試 URL 改成帶 `postgres@localhost:5433`（或改讀環境變數，預設仍指測試庫） |
| `app/api/routers/camera.py` | 可選：`LAN_HOST` 覆寫 `_lan_host()`，避免 container 猜出 `172.x` |
| `CLAUDE.md` 指令區 | 開發／常駐切換見 design4.md §8.4.1；psql 補 `-U postgres`；註明 brew `@17` 已停 |

**不改：** `db/schema.sql`、遷移腳本、repository SQL、規格檔、`postgresql@14`。

### 8.6 遷移順序（不可對調）

原則：brew 資料目錄**不要刪、不要 `brew uninstall`**，只停服務。那是最快的後悔藥。

**階段丙-0 — 凍結與盤點（brew 還活著）**

1. 停掉正在跑的 uvicorn，避免遷移中途又寫入。
2. 對正式庫拍照（結構＋列數＋關鍵列）：

```bash
psql -p 5433 -d PersonalDocAI -c "
SELECT
  (SELECT count(*) FROM photo) AS photos,
  (SELECT count(*) FROM folder) AS folders,
  (SELECT count(*) FROM entity) AS entities,
  (SELECT count(*) FROM photo_entity) AS pins,
  (SELECT count(*) FROM task) AS tasks,
  (SELECT count(*) FROM folder_correction) AS corrections;
"
psql -p 5433 -d PersonalDocAI -c "
SELECT id, category, folder_id, original_path IS NOT NULL AS has_file
FROM photo ORDER BY id;
"
```

3. 兩份備份（都放家目錄，不進 repo）：

```bash
pg_dump -p 5433 -d PersonalDocAI --no-owner --no-acl \
  -f ~/PersonalDocAI-backup-docker遷移前.sql

pg_dump -p 5433 -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-docker遷移前.dump
```

`--no-owner --no-acl` 是必要的：brew 庫的擁有者是 macOS 帳號，Docker 裡是 `postgres`。

**階段丙-1 — 空庫先在 5434 並行（brew 仍佔 5433）**

1. 寫好 `compose.yaml`，**暫時** `ports: ["127.0.0.1:5434:5432"]`，先不要起 `app`（或用 profile 只起 `db`）。
2. `docker compose up -d db`，等到 healthcheck 綠。
3. 確認 init 建了兩個資料庫：`PersonalDocAI`（空）、`PersonalDocAI_test`。
4. 灌正式庫：

```bash
pg_restore -h 127.0.0.1 -p 5434 -U postgres --no-owner --no-acl \
  --dbname=PersonalDocAI \
  ~/PersonalDocAI-backup-docker遷移前.dump
```

5. 測庫用 schema 重建（測庫本來就可以砍）：

```bash
psql -h 127.0.0.1 -p 5434 -U postgres -d PersonalDocAI_test \
  -f db/schema.sql
```

6. **閘門 G2：** 丙-0 的 count／照片列必須與 5434 逐項相同；`CREATE EXTENSION vector` 已在；`folder` id 1〜6 種子還在。不過這關，**不准停 brew**。

**階段丙-2 — 切埠、停 brew（只有 G2 過了才能做）**

1. `docker compose stop db`
2. compose 改成 `127.0.0.1:5433:5432`（**同一個 named volume `pgdata`，不要 `down -v`**）
3. `brew services stop postgresql@17`
4. 確認 5433 已空：`lsof -iTCP:5433 -sTCP:LISTEN`
5. `docker compose up -d db`
6. 再用丙-0 同一組查詢打 `localhost:5433`，數字必須相同

此時 brew `@17` 的資料目錄（`/opt/homebrew/var/postgresql@17`）仍在磁碟上，只是服務停了。

**階段丙-3 — 起 app、改連線**

1. `.env` 的 host 開發用 URL 改成 `postgresql://postgres@localhost:5433/PersonalDocAI`
2. compose 給 app 的 URL 是 `postgresql://postgres@db:5432/PersonalDocAI`
3. `OLLAMA_BASE_URL=http://host.docker.internal:11434`
4. 先用常駐指令驗遷移：`docker compose -f compose.yaml up -d`
5. `curl -k https://127.0.0.1:8000/health` → `{"status":"ok"}`
6. host 上 `pytest -q` 必須仍綠（連的是 Docker 裡的 `PersonalDocAI_test`）
7. 遷移驗收過了之後，日常開發改用  
   `docker compose -f compose.yaml -f compose.dev.yaml up -d`  
   看重載與 AI 秒數：`docker compose -f compose.yaml -f compose.dev.yaml logs -f app`

**階段丙-4 — 開機常駐**

1. Docker Desktop → Settings → General → **Start Docker Desktop when you sign in**
2. compose：**只**用 `compose.yaml` 的 `restart: unless-stopped`。開機自動拉起**不准**帶 `compose.dev.yaml`（否則每次開機都 `--reload`）
3. Ollama app 開機啟動（embedding／本機看圖仍靠它）

**不要**再讓 `brew services` 把 `@17` 設成開機啟動。`@14` 維持原樣。

### 8.7 拍照會不會壞

| 路徑 | 影響 |
|---|---|
| WebRTC 預覽 | 不受影響。影像不經過 container，也不經過 Postgres |
| 信令 WebSocket、快門上傳 | 走發佈後的 `:8000`。只要 8000 綁 0.0.0.0 就跟現在一樣 |
| QR 裡的 IP | **唯一高風險。** 用 localhost 開桌面頁時，container 內 `_lan_host()` 常回 `172.x` |
| HTTPS / mkcert | 憑證仍在 host `certs/`，mount 進去。區網 IP 換了要重簽 |
| 配對 session | app 重啟即失效——跟現在一樣 |

操作慣例：常駐時桌面頁用 `https://<區網IP>:8000/ui/camera-desk.html`，不要用 localhost。  
實作可加 `LAN_HOST` 當後備，但不是遷移成功的必要條件。

### 8.8 備份與回復

之後日常備份（只靠 Docker）：

```bash
docker compose exec db pg_dump -U postgres -d PersonalDocAI --no-owner --no-acl \
  -f /tmp/PersonalDocAI.dump
docker compose cp db:/tmp/PersonalDocAI.dump ~/PersonalDocAI-backup-$(date +%F).dump
```

或在 host：

```bash
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump
```

**絕對禁止**（沒有新備份時）：`docker compose down -v`、`docker volume rm …pgdata`。

**後悔藥（兩層）：**

1. **快：** `docker compose stop db` → `brew services start postgresql@17` → `.env` 改回無帳號的舊 URL。brew 資料目錄沒被刪就立刻回到遷移前。
2. **慢：** 用 `~/PersonalDocAI-backup-docker遷移前.dump` 灌回任一邊。

### 8.9 階段丙驗收

- [ ] 正式庫 photo／folder／entity／task／photo_entity／folder_correction 列數與遷移前快照相同
- [ ] `vector` extension 在；任一張照片 `vector_dims(embedding)=1024`
- [ ] brew `@17` 為 `stopped`；`@14` 仍為 `started` 且 5432 未被本專案佔用
- [ ] `127.0.0.1:5433` 是 Docker Postgres，不是 brew
- [ ] `pytest -q` 與遷移前同顆數（含既有 skipped）
- [ ] `GET /health` 200
- [ ] 上傳一張測試圖：201、`data/` 出現檔、瀏覽頁看得到
- [ ] 資料夾／待辦詳情彈窗在 Docker app 上仍可用（甲的回歸）
- [ ] 鏡頭：用區網 IP 開桌面頁，QR 網址是 `https://192.168.…` 不是 `172.…`
- [ ] 重開 Docker Desktop 後 `app`／`db` 自己回來

### 8.10 階段丙明確不做

- Ollama 進 Docker
- 停或改 `postgresql@14`
- `brew uninstall postgresql@17`（第一個穩定週期內保留後悔藥）
- 正式庫跑 `schema.sql`
- `docker compose down -v`
- app 水平擴成兩個 replica
- STUN／TURN、雲端資料庫、把 `data/` 打進映像
- 常駐 `compose.yaml` 加 `--reload`、或把 `compose.dev.yaml` 設成開機預設
- 本階段不改產品行為（歸類、詢問、彈窗鏈、詳情窗）

### 8.11 階段丙風險

| 風險 | 嚴重度 | 對策 |
|---|---|---|
| G1 沒過就遷移 | P0 | §0／§7 硬閘門 |
| dump 不完整就停 brew | P0 | G2：5434 對得上快照才停 |
| `down -v` 刪 volume | P0 | 文件禁止；brew 目錄先留著 |
| conftest 仍用「無帳號 URL」 | P1 | 與 `.env` 同一天改 |
| QR 猜到 Docker 網橋 IP | P1 | 用區網 IP 開頁；可選 `LAN_HOST` |
| Ollama 沒開機啟動 | P1 | embedding／本機看圖會 500；Desktop 救不了它 |
| 映像第一次 init 後才改 init SQL | P2 | init 只跑一次；測庫用 `psql -f schema.sql` 補 |

---

## 9. 錯誤表（本增量新增／要測的）

| # | 情境 | 預期 |
|---|---|---|
| 1 | `GET /photos/{id}` 沒這列 | 404，不寫檔、不打 AI |
| 2 | 有列、路徑 NULL | 200，`image_url`／`thumbnail_url` 為 null |
| 3 | 有列、路徑有值但磁碟檔沒了 | JSON 仍 200；`<img>` 失敗 → 窗內占位，不當整窗 404 |
| 4 | 待辦列點下去、詳情 404 | 窗開著、紅字；不是新分頁空白 |
| 5 | AI 呼叫失敗 | 既有 422／500／fallback **語意不變**；多一行 `ok=false` 的結束 log |
| 6 | Docker G2 對不上快照 | 停在 5434，brew 繼續服務 |

---

## 10. 決策紀錄

- **Decision：** 共用唯讀詳情彈窗＋`GET /photos/{id}`；AI 每次真呼叫打前後秒數；Docker 最後做，且必須等甲＋乙經產品負責人確認。
- **Why now：** 瀏覽時看不到完整說明；待辦開新視窗不好對照文字；本機／雲端看圖時間差很大，log 卻只有看圖有秒數；要常駐且單一資料來源。
- **Evidence / assumptions：** `fetch_photo` 已有四欄與路徑，不必新 SQL；`GET /folders/{id}` 摘要維持五鍵；正式庫有真實照片，必須 dump 不能重建；本機 MLX 模型不能進 Linux container。
- **Included scope：** §3 三段。
- **Excluded scope：** 改夾、刪待辦、Ollama 容器化、卸載 brew `@17`。
- **Success：** 甲乙過 G1；丙過 §8.9。
- **Failure：** G1 沒過 → 不做丙。G2 對不上 → 不停 brew。
- **Immediate next：** 實作階段甲（詳情 API＋彈窗）。階段丙的檔案一概先不要建。

---

## 11. 給實作者的檢查清單

開工前先讀 §0。若你正要建 `compose.yaml` 或跑 `pg_dump`：回頭看 G1 有沒有被產品負責人勾過。沒有就停手。

```text
[ ] 階段甲：GET /photos/{id} + photo_detail_modal.js + browse.html
[ ] 階段甲測試綠、端點 20、瀏覽器三入口
[ ] 階段乙：ai_timing.py 包五種 kind
[ ] 階段乙測試綠、終端機 log 樣本可讀
[ ] ★ G1 產品負責人點頭
[ ] 階段丙-0 備份兩份在家目錄
[ ] 階段丙-1 5434 灌入
[ ] ★ G2 列數對得上
[ ] 階段丙-2 停 brew、切回 5433
[ ] 階段丙-3 起 app（先無 reload 驗遷移）、pytest 仍綠
[ ] 確認 compose.dev.yaml 存在且日常開發用兩份疊加
[ ] 階段丙-4 開機常駐只帶 compose.yaml
```
