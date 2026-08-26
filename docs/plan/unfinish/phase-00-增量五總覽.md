# Phase 00：增量五總覽（design5.md 的實作路線圖，Phase 52〜72）

> **給實作者：** 本總覽把 `docs/design/design5.md`（2026-08-25 產品負責人對話拍板）拆成
> **21 個 phase（52〜72）**，計畫檔在本目錄 `phase-52`〜`phase-72`，**一次做一項**、全程 TDD。
> 衝突時 design5.md 為準；design5 未提及的行為仍依 design4.md／design3.md／design2.md／
> design1.md／design.md v4。

> 🎯 **仍是 side project：不要過度設計。** 只做 design5.md 寫到的事。
> 定案不可逆、人確認才釘實體／建待辦、embeddings 一律本機、單一使用者、不做刪除照片，
> 全部維持前面四個增量不變。

> ⚠️ **順序是硬的：甲 → ★G1（人）→ 乙 → ★G2（人）→ 丙 → ★G3（人）→ 72。**
> design5 §0 標題就寫著「**不可對調**」。三個閘門都是**人的動作**，實作者不可以自己勾掉
> （§4 有完整說明）。

---

## 1. 這次增量在做什麼（新手白話）

design5 寫了三件事，要照 **甲 → 乙 → 丙** 的順序做。它們解決的是三個不同的痛。

### 1.1 階段甲：待決定搬家（Phase 52〜55）

**現在的痛：** 「待決定」是**還沒歸類完的工作**——你上傳了照片、按了「稍後再說」，
它就躺在收件箱等你決定該放進哪個資料夾。可是這個「待辦事項清單」現在跟
**已經整理好的檔案櫃**擠在同一頁（`browse.html` 的第一個 tab）。
心智上這是兩件事：一邊是「還沒做完的事」，一邊是「已經做完的成果」。

**做完之後：** 待決定升格成頂欄的一格，有自己的網址 `/ui/pending.html`，
標題直接寫著還有幾張沒處理（`待決定（3）`）。瀏覽頁只剩「資料夾｜待辦」兩個 tab。
另外，點開待決定照片時跳出的歸類彈窗，**窗頂會多一張原圖**——
以前你只看得到 AI 寫的文字說明，得靠腦補猜這張是什麼；現在直接看圖決定。

這一段**完全是前端**，一行後端程式碼都不碰，也不改任何 API 回應。

### 1.2 階段乙：入庫佇列（Phase 56〜66）—— 這次增量的重頭戲

**現在的痛（最要命的一個）：** 你在上傳頁按下「上傳」之後，
**瀏覽器會整整卡住 2〜5 分鐘**，轉圈圈轉到你以為當機。

為什麼？因為現在的 `POST /photos` 是**同步處理**——FastAPI 收到檔案之後，
在**同一個 HTTP 請求裡**把所有事情做完才回話：格式檢查 → 叫 VLM 看圖 →
把文字轉成向量 → 寫進資料庫 → 存原圖與縮圖。其中「叫 VLM 看圖」這一步，
本機 gemma4 實測要 **64〜88 秒**（`CLAUDE.md` 有紀錄），
增量三加了實體與待辦建議之後 prompt 變長，最慢量到 **2〜5 分鐘**。

這段時間裡你什麼都不能做：不能選下一張、不能去問問題、不能離開頁面
（離開就等於放棄這次上傳）。想傳 3 張？站在電腦前 10 分鐘。

**做完之後：** HTTP 只做「收件員」該做的事——檢查格式、把檔案暫存到硬碟、
在待辦清單上記一筆、把工作丟給排隊區——然後**約 0.1 秒**就回你話。
真正的看圖交給**另外一個行程**（worker）慢慢做。

**這裡有一個關鍵的概念要先講清楚：**

| 回應碼 | 名字 | 白話意思 | 現在／增量五 |
|---|---|---|---|
| **201** | Created | 「**已經建好了**」。你要的那筆資料現在真的存在資料庫裡，我還可以順便把它的內容全部回給你 | 現在是這個 |
| **202** | Accepted | 「**我收下了，還沒做完**」。檔案在我手上、我保證會處理，但**現在資料庫裡還沒有這張照片** | 增量五改成這個 |

這個差別不是換個數字而已，它是**契約的改變**：
202 回應裡**不會**再有 `text`、`suggested_folder`、`folders` 這些東西，
因為那些是 AI 看完圖才生得出來的，而回話當下 AI 根本還沒開始看。
202 只回三樣：`job_id`（這份工作的編號）、`filename`、`content_type`。

也因為這樣，`design.md v4` 那條「上傳為同步處理；完成即代表文字、metadata、
向量皆已儲存」的定案，以及 design1 的「明確不做非同步佇列」，在這個增量**正式作廢**
（見 §3.4）。

### 1.3 階段丙：非同步 UX（Phase 67〜71）

**現在的痛：** 上面那些後端改動，如果前端不跟上，使用者只會覺得「按了上傳，
啥事都沒發生」——照片不在待決定裡，也沒有任何進度可看。

**做完之後：**

- 上傳頁的檔案選擇框加上 `multiple`，**一次可以選好幾個檔**（圖跟 PDF 可以混）
- 每一頁的**右下角**都有同一份**進度面板**，2 秒更新一次，
  告訴你哪些檔在排隊、哪些在分析、第幾次重試、哪些失敗了
- 分析成功的那一列**自己消失**，同時頂欄的「待決定（N）」+1
- 失敗的那一列**留著**，右上角有個 × 可以關掉
- 手機鏡頭**按了快門就可以按下一張**，不必等 VLM
- 上傳當下**不再**跳出那串彈窗鏈（抽屜 → 實體 → 待辦），
  歸類這件事**只在待決定頁做**

### 1.4 全景圖：21 個 phase 與 3 個閘門

```text
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 階段甲：待決定獨立入口（Phase 52〜55）── 純前端，一行後端都不碰          │
  │   52  新建 app/static/pending.html（把 browse 的 showPending 搬過來）    │
  │   53  五頁頂欄統一四格                                                   │
  │         「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」                    │
  │         N 先用 GET /folders 的收件箱 photo_count                         │
  │   54  folder_modal.js 窗頂加 <img>；「稍後再說」文案改指待決定頁         │
  │   55  browse.html 拿掉待決定 tab，無 query 時預設「資料夾」              │
  └──────────────────────────────────────────────────────────────────────────┘
                                       │
     ★★★ 閘門 G1（人）：產品負責人照 design5 §12「階段甲」四條驗收
          沒點頭 = 停在這裡，不准動 POST /photos 的回應碼
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 階段乙：入庫佇列（Phase 56〜66）── 破壞性的 201 改 202 就在這一段        │
  │   56  db/migrate_design5.sql：photo 加建議三欄（值先都是 NULL）          │
  │   57  ingest_job_store.py：JobStore 契約＋InMemoryJobStore               │
  │         ＋conftest 第四道安全網 wire_memory_job_store                    │
  │   58  staging_service.py：寫／讀／刪＋24 小時掃把（啟動接線在 65）       │
  │   59  ingest_job.py：run_ingest_job() 單圖路徑（3 次重試、冪等）         │
  │   60  同一個任務處理整份 PDF（逐頁各 3 次、失敗跳頁、pages_done）        │
  │   61  worker INSERT 時一併寫 D16 三欄；資料夾照片摘要 五鍵改八鍵         │
  │   62  POST /photos 改 202（既有 201 斷言全面改寫，含 BDD binder）        │
  │   63  POST /camera/{token}/photos 改 202；GET latest 行為變窄            │
  │   64  GET /ingest-jobs ＋ POST /ingest-jobs/{id}/dismiss（端點 20 變 22）│
  │   65  celery_app.py＋RedisJobStore＋掃把接線兩頭（app 與 worker）        │
  │   66  compose.yaml 加 redis／worker；LAUNCH.md／CLAUDE.md 更新           │
  └──────────────────────────────────────────────────────────────────────────┘
                                       │
     ★★★ 閘門 G2（人）：產品負責人照 design5 §12「階段乙」五條驗收
          沒點頭 = 停在這裡，前端不准開工（丙全靠乙的契約）
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 階段丙：非同步 UX（Phase 67〜71）── 前端追上乙的新契約                   │
  │   67  progress_panel.js：2 秒輪詢 GET /ingest-jobs，全站右下角面板       │
  │         四種狀態、× dismiss、面板收起、頂欄 N 改由它更新                 │
  │   68  upload.html 加 multiple、每檔一個 POST、拿掉 201 開鏈              │
  │   69  camera-phone.html 202 即可再拍；camera-desk.html 刪 latest 開鏈    │
  │   70  待決定改走完整三關（抽屜、實體、有待辦建議才開的待辦窗）           │
  │   71  §8 十列逐列點名（大多 59〜64 已釘）＋補三缺口＋掃碼                │
  └──────────────────────────────────────────────────────────────────────────┘
                                       │
     ★★★ 閘門 G3（人）：產品負責人明示核准解禁 docs/spec/
          沒核准 = .feature 一個字都不准改（design5 §10 明文）
                                       ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 收尾：Phase 72  規格檔改版與增量五驗收包                                 │
  │   上傳照片／無線鏡頭拍攝／歸類照片／瀏覽檔案櫃 四份 .feature             │
  │   改成「收下不等於已入庫」；產出驗收包交產品負責人                       │
  └──────────────────────────────────────────────────────────────────────────┘
```

### 1.5 同步 vs 非同步：前後對照

```text
┌─ 現在（增量四）＝同步處理，HTTP 回 201 Created ─────────────────────────────────────────────┐
│                                                                                              │
│   瀏覽器                                        FastAPI（uvicorn 這一個行程，自己把事情做完）│
│     |                                           |                                            │
│     |  POST /photos（1 張 JPEG）                |                                            │
│     |------------------------------------------>|  1. 格式檢查        0.001 秒               │
│     |                                           |  2. VLM 看 圖       64〜88 秒 <== 痛點     │
│     |  轉圈圈…整個頁面卡住                      |  3. 轉向量 embed    幾秒                   │
│     |  不能選下一張                             |  4. INSERT photo    0.01 秒                │
│     |  不能去問問題                             |  5. 存原圖＋縮圖    0.1 秒                 │
│     |                                           |                                            │
│     |<------------------------------------------|  201 Created ＝「已經存好了」              │
│     |  回應帶著 text／metadata／suggested_folder／folders 一整份                             │
│     v                                                                                        │
│   當場跳出彈窗鏈（抽屜、實體、待辦），你必須立刻決定                                         │
│                                                                                              │
│   想傳 3 張？要排隊等 3 次，站在電腦前 5〜15 分鐘，中間什麼都做不了。                        │
│                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

                            v v v   增量五改成   v v v

┌─ 增量五＝非同步處理，HTTP 回 202 Accepted ──────────────────────────────────────────────────┐
│                                                                                              │
│   瀏覽器                                        FastAPI（只當「收件員」，不看圖）            │
│     |                                           |                                            │
│     |  POST /photos ×3（一次選 3 個檔）         |                                            │
│     |------------------------------------------>|  1. 格式檢查        0.001 秒               │
│     |                                           |  2. 寫 data/staging/{job_id}               │
│     |<------------------------------------------|  3. JobStore 記成 queued                   │
│     |  202 Accepted                             |  4. 丟一個任務給 Redis                     │
│     |  {job_id, filename, content_type}         |                                            │
│     |  ＝「我收下了，還沒做完」                 |  以上總共約 0.1 秒                         │
│     v                                                                                        │
│   你立刻自由：再選下一批、去問問題、去瀏覽資料夾，全部都可以                                 │
│   右下角進度面板冒出 3 列：queued ／ analyzing ／ retrying                                   │
│                                                                                              │
│            ┈┈┈┈┈┈┈┈┈┈  同一時間，在「另外一個行程」裡  ┈┈┈┈┈┈┈┈┈┈                            │
│                                                                                              │
│   redis 容器（排隊的地方）                      worker 容器（Celery，2 個子行程）            │
│     |                                           |                                            │
│     |--- 任務 1（一個檔＝一個任務）------------>|  從 data/staging 讀檔（不是從 Redis）      │
│     |--- 任務 2 ------------------------------->|  VLM 看圖，同一張最多 3 次                 │
│     |    任務 3 還在排隊（只有 2 個 worker）    |  成功 -> embed -> INSERT 進收件箱          │
│     |                                           |       -> 原圖＋縮圖落地 -> 刪 staging      │
│     |                                           |  3 次都失敗 -> 刪 staging、不留 photo 列   │
│     |                                           v                                            │
│     |                                           成功：job 被刪掉 -> 進度列消失、頂欄 N +1    │
│     |                                           失敗：job=failed -> 進度列留著、可按 × 關掉  │
│                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.6 Docker 容器的樣子（階段乙 Phase 66 之後）

現在有兩個容器（`db`、`app`），這個增量會變成**四個**：

```text
  瀏覽器 / iPhone ──HTTPS :8000──► [app]      只收檔、入列，不看圖
                                     │
                                     ▼
                                  [redis]     排隊的地方；volume: redisdata（AOF）
                                     │
                           Celery 從這裡取出任務
                                     ▼
                                  [worker]    同一份 app 映像，--concurrency=2
                                     │
                     ┌───────────────┼───────────────┐
                     ▼               ▼               ▼
                   [db]         data/staging      Ollama 在 Mac 上
                  Postgres      data/photos      host.docker.internal
                  正本在這      data/thumbs      （刻意不進 Docker）
```

### 1.7 新名詞白話表（第一次看到請先讀這張）

| 名詞 | 白話解釋 |
|---|---|
| **佇列（queue）** | 排隊的隊伍。工作丟進去、按先來後到被拿出來做。中文有時寫「隊列」，本專案一律寫「佇列」 |
| **Redis** | 一個把資料放在**記憶體**裡的小型資料庫，因為在記憶體所以極快。本專案只拿它當「排隊的地方」，不拿它存照片 |
| **broker（中間人／訊息仲介）** | 「放任務的那個地方」的正式名稱。在本專案 broker 就是 Redis。設定值叫 `CELERY_BROKER_URL` |
| **Celery** | Python 的背景工作框架。它幫你做「把任務放進 broker」「從 broker 拿出來執行」「執行失敗怎麼辦」這些雜事，你只要寫「這個任務要做什麼」 |
| **worker（工人）** | 真的在做事的那個行程。本專案是一個叫 `worker` 的容器，裡面開 **2** 個子行程（`--concurrency=2`），所以最多同時看兩張圖 |
| **行程（process）** | 作業系統裡「一個正在跑的程式」。`app` 是一個行程、`worker` 是另一個行程。**兩個行程的記憶體是分開的**——這就是為什麼頁首那顆「本機／雲端」開關（存在 app 的記憶體裡）worker 讀不到，必須在入列當下抄一份快照給它（D14） |
| **staging（暫存區）** | 「還沒正式入庫的東西先放這裡」的那個資料夾。本專案是 `data/staging/{job_id}.jpg`。收件當下先把檔案落地，worker 之後再來讀。成功或最終失敗都會刪掉 |
| **202 Accepted** | HTTP 回應碼，意思是「**我收下了，還沒做完**」。跟 201 Created（「已經建好了」）是完全不同的承諾——見 §1.2 的對照表 |
| **輪詢（polling）** | 前端每隔一段時間主動問伺服器「有更新嗎？」。本專案是 2 秒問一次 `GET /ingest-jobs`。（相對的做法叫 push／WebSocket，本增量**不做**） |
| **冪等（idempotent）** | 同一個動作做兩次，結果跟做一次一樣。例如「刪除 id=5 的檔案」是冪等的（第二次刪，它本來就不在了），「照片數 +1」不是冪等的。本增量兩處要冪等：① 資料庫遷移腳本可以重跑 ② 任務被重送時不能插出第二張照片 |
| **AOF（Append Only File）** | Redis 的一種存檔方式：每一個寫入動作都追加寫進一個檔案。好處是 Redis 重啟後資料還在。設定值 `appendonly yes` |
| **named volume（具名磁碟區）** | Docker 自己管理、有名字的一塊硬碟空間。容器砍掉重建，裡面的資料還在。正式庫住在 `personaldocai_pgdata`，Redis 會住在新的 `redisdata` |
| **healthcheck（健康檢查）** | Compose 定期跑一個小指令確認服務真的活著（Redis 是 `redis-cli ping`）。其他服務可以用 `depends_on: service_healthy` 等它 |
| **TypedDict／Protocol** | Python 的兩個型別工具。`TypedDict` ＝「這個 dict 應該有哪些鍵」；`Protocol` ＝「只要有這幾個方法就算數，不必繼承」。本專案用它們定義 `IngestJob` 與 `JobStore`，好處是記憶體版與 Redis 版可以互換 |
| **ack（確認）** | worker 跟 broker 說「這個任務我做完了，可以從隊伍刪掉」。如果 worker 中途被殺、沒 ack，Celery 會把任務**重送**給別人——這就是為什麼要有冪等規則（design5 §4.4） |
| **overlay（覆寫檔）** | 再疊一份 compose 設定上去，後面那份覆寫前面同名的設定。本專案的 `compose.dev.yaml` 就是 overlay |
| **bind-mount** | 把 Mac 上的某個資料夾「接」進容器裡，兩邊看到的是同一份檔案。開發模式靠它讓容器看到你剛改的程式碼 |

---

## 2. Phase 清單與進度

### 開工基準（2026-08-25 實測，開工前務必自己驗一次）

| 項目 | 值 | 怎麼驗 |
|---|---|---|
| 測試顆數 | **405 passed ＋ 0 skipped** | `pytest -q` |
| 端點數 | **20** | `client.get("/openapi.json").json()["paths"]` 展開成 (path, method) 後 `len == 20` |
| 端點清點測試位置 | `tests/integration/test_ask_three_paths.py::test_端點數不變` | Phase 64 改 20 → **22** 時要改這顆的數字與註解（**測試名不改**） |
| openapi 零 DELETE | `tests/integration/test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞` | 增量五**繼續保持**零 DELETE |
| 資料庫 | Docker container，`127.0.0.1:5433`，帳號 `postgres`，正式庫 `PersonalDocAI`、測試庫 `PersonalDocAI_test` | `psql -d PersonalDocAI` |
| 服務 | `docker compose -f compose.yaml up -d`（常駐）／`+ compose.dev.yaml`（開發熱重載） | `docker compose ps --no-trunc` |
| 網址 | **`https://`**localhost:8000（**不是** http，開頭多一個 s） | `curl -k https://127.0.0.1:8000/health` |
| 上一個 phase 編號 | **51**（design4 增量四最後一個） | `ls docs/plan/finish/` |

```bash
# 開工前一次驗完（在專案根目錄）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc          # db 要是 Up (healthy)
pytest -q                             # 預期尾巴：405 passed
curl -k -s https://127.0.0.1:8000/health
```

### 21 個 phase

| Phase | 檔名 | 一句話 | 依賴 | design5 章節 | 完成 |
|---|---|---|---|---|---|
| 52 | `phase-52-待決定新頁.md` | 新建 `app/static/pending.html`，把 `browse.html` 的 `showPending()` 搬過來 | — | §6.2、D1 | [x] |
| 53 | `phase-53-全站頂欄四格.md` | 五頁 header 統一成「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」，N 先用 `GET /folders` 收件箱 `photo_count` | 52 | §6.1、D1 | [x] |
| 54 | `phase-54-歸類彈窗窗頂原圖.md` | `folder_modal.js` 窗頂加 `<img src="/photos/{id}/image">`；「稍後再說」文案改指向待決定頁 | 52（53 亦列前置：頂欄可點到、驗收較順） | §6.2、D2、§1.1 第 5 列 | [x] |
| 55 | `phase-55-瀏覽頁拿掉待決定tab.md` | `browse.html` 只剩「資料夾｜待辦」，無 query 時預設資料夾 | 52、53、54 | §6.3、D1、§1.1 第 4 列 | [x] |
| ★G1 | （人的動作，沒有檔案） | 產品負責人照 design5 §12「階段甲」四條驗收；沒過**不准**開始改上傳契約 | 55 | §0、§12 甲 | [ ] |
| 56 | `phase-56-建議欄資料庫遷移.md` | `db/migrate_design5.sql` 加三欄；`schema.sql` 對齊；repository 讀寫（值先都是 `None`） | —（定稿 §2 明文：無 phase 依賴、可與甲並行；總序仍照 §0 甲→乙） | D16、§11（migrate／schema 兩列） | [x] |
| 57 | `phase-57-JobStore與測試安全網.md` | `ingest_job_store.py`＋`InMemoryJobStore`＋conftest 第四道 autouse `wire_memory_job_store` | —（定稿 §2 明文：可與 52〜56 並行） | §4.3、§9、D15、D14（`ai_backend` 欄） | [x] |
| 58 | `phase-58-staging暫存區服務.md` | `staging_service.py`：寫／讀／刪／24 小時掃把（只寫函式與測試；啟動接線兩頭都在 65） | 57 | §4.1 | [x] |
| 59 | `phase-59-單圖入庫任務.md` | `run_ingest_job()` 單圖路徑：3 次重試、成功 INSERT 收件箱、失敗清乾淨、`photo_ids` 冪等 | 57、58 | §4.2、§4.4、D10、D15、§8 第 3／6／7 列 | [ ] |
| 60 | `phase-60-PDF入庫任務.md` | 同一個任務處理整份 PDF：逐頁各 3 次、失敗跳頁、0 頁成功才整筆失敗、`pages_done` 續跑 | 59 | D11、D12、§4.4、§8 第 4／5 列 | [ ] |
| 61 | `phase-61-建議落庫接線.md` | worker INSERT 時一併寫 D16 三欄；`GET /folders/{id}` 照片摘要五鍵→八鍵 | 56、59、60 | D16、§4.2 第 2 段、§6.2 末段 | [ ] |
| 62 | `phase-62-上傳端點改202.md` | `POST /photos` 落 staging＋建 job＋回 202；既有 201 斷言全面改寫（113 個項目，含 BDD binder）；刪 `_ingest_pdf`＋`PdfUploadResponse` | ★G1；57、58、59、60、61 | §5（第 1 列）、D7、D14、§9、§8 第 1／8 列 | [ ] |
| 63 | `phase-63-鏡頭端點改202.md` | `POST /camera/{token}/photos` 202、不 `set_latest`；`GET latest` 行為變窄；收掉 `_ingest_image`＋`UploadResponse` | 62 | §5（第 2／3 列）、D4、§8 第 2 列、§1.1 第 8 列 | [ ] |
| 64 | `phase-64-任務清單與關閉端點.md` | `GET /ingest-jobs`＋`POST /ingest-jobs/{job_id}/dismiss`；端點 20→22 | 57、62 | §4.3 後半、§5（第 4／5 列）、D9、§8 第 9 列、§1.1 第 7 列 | [ ] |
| 65 | `phase-65-Celery與Redis實作.md` | `celery_app.py`＋`RedisJobStore`＋`requirements.txt` 加 `celery`／`redis`；掃把啟動接線**兩頭都在這裡**（`main.py` lifespan＋`worker_ready`）；`build_vlm_for_backend()` | 57、58、59、60、62 | D5、§4.1 末條、§4.3 前半、§4.4 前半、§4.5 | [ ] |
| 66 | `phase-66-Compose加redis與worker.md` | `compose.yaml` 加兩個服務、`compose.dev.yaml` 加 worker bind-mount、`LAUNCH.md`／`CLAUDE.md` 更新、真容器煙霧 | 65 | §7 全節、D6 | [ ] |
| ★G2 | （人的動作，沒有檔案） | 產品負責人照 design5 §12「階段乙」五條驗收；沒過**不准**開始丙 | 66 | §0、§12 乙 | [ ] |
| 67 | `phase-67-全站進度面板.md` | `progress_panel.js` 2 秒輪詢 `GET /ingest-jobs`，四種狀態、× dismiss、面板收起、頂欄 N 改由它更新（掛桌面五頁，**不含** `camera-phone`） | ★G2；64（另需 62、57／59、52／53、55） | §6.6、§6.1 後半、D8、D9 | [ ] |
| 68 | `phase-68-上傳頁多檔選檔.md` | `upload.html` 加 `multiple`、每檔一個 POST、拿掉 201 開鏈、文案改寫 | ★G2；62、67（52、53 亦列前置） | §6.4、D3、D13 | [ ] |
| 69 | `phase-69-鏡頭連拍與桌面拿掉開鏈.md` | `camera-phone.html` 202 即可再拍＋窄條；`camera-desk.html` 刪 latest→`classify_chain`；`uploaded` WS 通知**保留**（本檔裁決） | ★G2；63、67 | §6.5、D4、D13、§5 末段 | [ ] |
| 70 | `phase-70-待決定走完整三關.md` | 待決定改成抽屜→實體→**有待辦建議才開**待辦窗，建議從 D16 三欄讀；`classify_chain.js` 零呼叫者後刪除（§4.5） | 52、54、61、68；69（僅 §4.5 刪檔要等它） | §6.2 末兩段、D2、D16、§1.1 第 9／10 列 | [ ] |
| 71 | `phase-71-增量五錯誤收尾與全量回歸.md` | §8 十列**逐列點名**證明有人守（大多已由 59〜64 釘住）＋新檔 `test_design5_error_paths.py` 補三個真缺口＋「不做」掃碼；清點端點 22（逐支列名）、零 DELETE | 52〜70 | §8 全表、§9 必加清單、§3「不做」、§0 四條禁止、§1.2 | [ ] |
| ★G3 | （人的動作，沒有檔案） | 產品負責人**明示核准解禁** `docs/spec/`；沒核准**不准**改任何 `.feature` | 71 | §10 | [ ] |
| 72 | `phase-72-規格檔改版與增量五驗收包.md` | ★G3 核准後改**四份** `.feature`（上傳照片／無線鏡頭拍攝／歸類照片／瀏覽檔案櫃——design5 §10 列三份，「歸類照片.feature **等**」的「等」由定稿落成第 4 份）；產出驗收包 | ★G3（＋71） | §10、§12（三段彙整） | [ ] |

### 依賴順序總結

```text
甲   52 → 53 → 54 → 55 → ★G1
     （54 硬依賴 52、53 只是讓驗收動線順；★G1 擋的是 62 起的上傳契約變更）

乙   56 ────────────────────────┐        56、57 定稿 §2 明文「無 phase 依賴、
     57 → 58 → 59 → 60 ────────┴→ 61    可與甲並行」；總序仍照 §0 甲→乙，
                                          各檔顆數基準以「照編號做」計
     ★G1 ＋ 57、58、59、60、61 ──→ 62 → 63
     57、62 ─────────────────────→ 64   （63 非硬依賴，總序在前）
     57、58、59、60、62 ─────────→ 65 → 66 → ★G2

丙   ★G2 → 67（吃 64 的契約）→ 68（另需 62；52、53 亦列前置）
            67 → 69（另需 63）
     52、54、61、68 → 70（§4.5 刪 classify_chain.js 要再等 69）
     52〜70 → 71 → ★G3 → 72
```

> ⚠️ **交錯做的話，各 phase 檔內的絕對顆數對不上是正常的**——56〜58 檔內舉例的
> 絕對數字甚至假設的是「跳過甲直接做乙地基」那條路（詳見 §9 表下的註記）。
> **要看的是「本 phase 新增幾顆」，不是絕對數字**，而且**不准為了湊數字去改或刪測試**。

---

## 3. 覆蓋對照表（「一條不漏」的自我檢查證據）

### 3.1 design5.md 各節 → 落地的 phase

| design5 章節 | 內容 | 由誰落地 |
|---|---|---|
| §0 實作計劃總序 | 甲→乙→丙不可對調；四條禁止 | 本總覽 §1.4 全景圖、§4 三個閘門、下方「四條禁止」醒目框；各 phase 開頭的門檻框 |
| §1 D1〜D16 | 已拍板決策 16 條 | 見下面 **§3.2**（16 條逐條） |
| §1.1 本增量推翻的舊決策 | **10 列**（不是 9 列，見 §3.4 註） | 見下面 **§3.4** |
| §1.2 被否決（不要重開） | 13 列 | 見下面 **§3.5**；同時分散寫進各 phase 的「明確不做」表 |
| §2 流程 | 進圖 → FastAPI → worker → 待決定的全景 | 本總覽 §1.5 對照圖；59／60／62／67 各自的流程圖 |
| §3 範圍「做」 | 11 條 | 52〜72 全部（本表其他列） |
| §3 範圍「不做」 | 9 條（批次歸類、失敗手動重試、狀態欄進 photo、app replica、Flower、Redis 上區網、S3、刪除端點、詢問改版） | **71** 逐條掃碼；各 phase 的「明確不做」表 |
| §4.1 Staging | 路徑、不入版控、禁止塞 Redis、成功／失敗都刪、24 小時掃把 | **58**（五函式＋掃把本體，**明文不接線**）、**62**（收件時落檔＋失敗刪）、**59／60**（讀與刪）、**65**（啟動接線**兩頭都在這裡**：`main.py` lifespan＋`celery_app.py` `worker_ready`）、**66**（真容器 log 驗兩把掃把真的跑了） |
| §4.2 何時才有 `photo` 列 | VLM＋embedding 都成功才 INSERT；202 當下列數不變 | **59**（INSERT 時機）、**62**（202 當下 0 列的新釘測試）、**61**（同一筆 INSERT 帶建議欄） |
| §4.3 JobStore | 兩種實作、四種狀態、成功＝刪、每筆 11 個欄、`pending_count`、dismiss | **57**（契約＋記憶體版＋欄位）、**65**（Redis 版）、**64**（清單／`pending_count`／dismiss 端點） |
| §4.4 崩潰重送 | 不用 Celery autoretry；`photo_ids` 與 `pages_done` 冪等；開頭改 `analyzing` | **59**（單圖 `photo_ids`＋開頭改狀態）、**60**（PDF `pages_done` 續跑）、**65**（Celery 設定不加 autoretry） |
| §4.5 AI 後端 | 開關只在 web 行程；worker 用任務裡的 `ai_backend` 快照自己建 client | **57**（欄位）、**62／63**（入列當下寫快照）、**59／65**（worker 依快照建 `OllamaVLM`／`OllamaCloudVLM`） |
| §5 API 契約（20→22） | 五列 | **62**（`POST /photos`）、**63**（鏡頭兩支）、**64**（新兩支＋清點改 22） |
| §6.1 頂欄（全站） | 四格文字、`aria-current`、甲用 `GET /folders`、丙改輪詢、不要各寫一套 `setInterval` | **53**（甲版）、**67**（丙版接手 N） |
| §6.2 `/ui/pending.html` | 搬 `showPending`、空狀態文案、窗頂原圖、稍後再說文案、丙起走完整三關 | **52**（搬頁＋文案）、**54**（原圖＋稍後再說）、**70**（完整三關＋讀 D16 建議） |
| §6.3 `/ui/browse.html` | 拿掉待決定 tab、預設資料夾、不做 302 轉址 | **55** |
| §6.4 `/ui/upload.html` | `multiple`、每檔一個 POST、拿掉開鏈、文案 | **68** |
| §6.5 鏡頭 | 手機 202 可再拍＋窄條；桌面刪 latest 開鏈；WebRTC／QR／快門／閃光不改 | **69** |
| §6.6 進度面板 | 四種狀態顯示、成功不出現、× dismiss、全空收起、重新整理還在 | **67** |
| §7 Docker 與啟動 | `redis`／`worker` 兩服務、`app` 加設定、`compose.dev.yaml`、啟動指令 | **66**（`65` 先把 Celery 程式與套件備好） |
| §8 錯誤表 10 列 | — | 見下面 **§3.3** |
| §9 測試策略 | 第四道安全網、`run_ingest_job` 直呼、201 斷言改寫三步、必加清單 **11** 條 | **57**（第四道）、**59**（直呼）、**62**（改寫既有斷言＋BDD binder）、**71**（必加 11 條逐條點名「誰已經測了」——大多由 57〜64 各自釘住，71 只補真缺口） |
| §10 規格檔 | 三份 `.feature` 的改法；未核准前不准動 | **★G3** ＋ **72**（定稿把 §10「歸類照片.feature **等**」的「等」落成第 4 份 `瀏覽檔案櫃.feature`——它寫著「預設分頁為待決定」，Phase 55 之後變假，共改**四份**） |
| §11 會動到的檔 | 19 列契約 | 各 phase 的「範圍／做」節；**不改**那一段由 71 掃碼 |
| §12 驗收清單 | 甲 4／乙 5／丙 7 | 本總覽 **§5**；★G1／★G2 各取一段；72 彙整成驗收包 |
| §13 風險與已知限制 | 5 條 | 本總覽 **§8**；各 phase 的「常見陷阱」節 |
| §14 決策紀錄 | 8 題的對話摘要 | 本總覽 §1／§3.2（每條都指回 D 編號） |

### 3.2 D1〜D16 → 落地的 phase（16 條，一條都不能漏）

| # | 決策一句話 | 由誰落地 | 怎麼驗 |
|---|---|---|---|
| **D1** | 待決定從瀏覽頁 tab 移到頂欄，放在「上傳照片」右邊 | **52**（新頁）、**53**（頂欄四格）、**55**（瀏覽頁拿掉 tab） | 瀏覽器：頂欄四格；`/ui/pending.html` 開得起來；`browse.html` 沒有待決定 tab |
| **D2** | 點開仍是彈窗（①②③④四個出口），**窗頂多一張原圖**；補完鏈改為與現在上傳鏈相同（抽屜→實體→有待辦建議才開待辦窗） | **54**（窗頂原圖）、**70**（完整三關） | 瀏覽器：彈窗最上面是原圖；有待辦建議的照片會跳第三窗，沒有則不跳 |
| **D3** | 電腦一次多檔（`<input multiple>`，可含 PDF），每個檔各自入列 | **68** | 瀏覽器：一次選 3 個檔 → 進度面板 3 列 |
| **D4** | 鏡頭連拍：手機快門不必等 VLM，與電腦上傳走**同一條**佇列 | **63**（後端 202）、**69**（前端可連拍） | iPhone：連按兩次快門不必等；`GET /ingest-jobs` 看得到兩列 `source=camera` |
| **D5** | 佇列用 Redis、worker 用 Celery；**不採用** FastAPI BackgroundTasks，也不自寫 Redis list 迴圈 | **65**（程式）、**66**（容器） | `grep -rn "BackgroundTasks" app/` 零輸出；`docker compose ps` 看得到 `redis`／`worker` |
| **D6** | 正式與測試都最多 **2** 個 Celery 子行程（一個 `worker` 容器、`--concurrency=2`）；手動煙霧先切雲端 | **66** | `docker compose ps --no-trunc` 的 COMMAND 欄看得到 `--concurrency=2`（**`--no-trunc` 不能省**，預設會截掉尾巴） |
| **D7** | HTTP 只做格式檢查、落 staging、入列，回 **202** `{job_id, filename, content_type}` | **62**（上傳）、**63**（鏡頭） | `curl` 回 202；回應 JSON 恰三鍵；當下 `select count(*) from photo` 不變 |
| **D8** | 進度面板**全站**（含問問題、瀏覽、待決定、鏡頭桌面、手機取景）；換頁／重新整理靠伺服器清單長回來 | **67**（桌面五頁的面板）、**69**（手機的窄條） | 瀏覽器：上傳中切到問問題頁，列還在；F5 之後也還在 |
| **D9** | 成功列消失、頂欄 N +1；失敗列留下可按 × 關掉；清單空了收起面板 | **57**（成功＝`delete(job_id)`）、**64**（GET 不含成功、dismiss 端點）、**67**（前端行為） | `test_ingest_job.py`：成功後 `list_open()` 不含它；瀏覽器：成功列自己不見 |
| **D10** | 同一張圖（或 PDF 某一頁）**含第一次共 3 次**；看不懂與連線失敗都算；3 次都敗＝整筆拿掉、不留 `photo` 列、刪 staging | **59**（單圖，`VLM_MAX_ATTEMPTS=3`） | `test_ingest_job.py::…三次失敗…`：列數 0、staging 不在、job=`failed` |
| **D11** | PDF 一檔一列、**一個 Celery 任務＝一個檔案**；同一份 PDF 的每頁由**同一個 worker 依序**看完 | **60**（任務本體）、**65**（Celery 任務粒度） | `test_ingest_job_pdf.py`：一次 `run_ingest_job` 把兩頁都做完；`grep` 確認沒有「每頁一個任務」的程式 |
| **D12** | PDF 以**頁**為重試單位：每頁各 3 次，仍失敗就跳過（`skipped_pages` 語意）；**整份 0 頁成功**才整筆失敗 | **60** | `test_ingest_job_pdf.py`：兩頁、第二頁三次失敗 → 一列照片、job 成功；全頁失敗 → 0 列、`failed` |
| **D13** | 上傳當下不開歸類鏈：電腦上傳與鏡頭桌面都**不再**開抽屜→實體→待辦；歸類只發生在待決定 | **68**（上傳頁）、**69**（鏡頭桌面） | `grep -n "classify" app/static/upload.html app/static/camera-desk.html` 零輸出（或只剩註解）；瀏覽器：上傳後不跳窗 |
| **D14** | 入列當下把 `config.AI_BACKEND` 寫進任務；worker 用這張快照；embedding 仍一律本機 | **57**（`ai_backend` 欄）、**62／63**（入列當下寫快照）、**65**（`ingest_task` 消費快照：`build_vlm_for_backend(job["ai_backend"])` 建對的 VLM 客戶端。⚠ `run_ingest_job()` 本身**不讀**這個欄位——它只收呼叫端建好的 `vlm` 參數） | **62／63** 各有「job 的 `ai_backend` 是入列當下的值」斷言；**65** 的 `build_vlm_for_backend` 測試（local→`OllamaVLM`／cloud→`OllamaCloudVLM`）；切換開關不影響已在跑的任務 |
| **D15** | 測試不碰真 Redis：任務本體抽成 `run_ingest_job(...)` 直接呼叫；Job 狀態用可替換 store | **57**（`JobStore` Protocol＋conftest 第四道）、**59**（`run_ingest_job` 簽章） | `pytest -q` 在**沒有 redis 容器**的情況下仍全綠；`CELERY_BROKER_URL` 指死埠跑全量顆數一模一樣（65／66／71 都有這一驗；tests/ 裡的 Redis 只有 65 那組用假 client 的 `RedisJobStore` 序列化測試，不撥真連線） |
| **D16** | worker 成功 INSERT 時一併寫入實體建議與待辦建議（標題／到期日）；仍只是建議，人按確認才寫 `entity`／`photo_entity`／`task` | **56**（三欄遷移）、**61**（落庫＋摘要八鍵）、**70**（讀出來畫選項） | `psql`：新照片的 `suggested_entity` 有值；`GET /folders/{inbox}` 摘要恰八鍵 |

### 3.3 §8 錯誤表 10 列 → 落地的 phase

> 📌 **71 的角色不是「把 10 列釘死」，是「逐列點名證明有人守」。** 52〜70 全程 TDD，
> 各 phase 已把自己那幾列在自己的測試檔釘好；71 的盤點（phase-71 §4.1 有逐列對照表，
> 含每一顆測試的名字）只補了 **3 個真缺口**（第 7／8／9 列各半條，見 ★）。
> 執行 71 時要用 `--collect-only` 把 ✓ 逐顆對過——發現被裁掉了就**回那個 phase 的測試檔補**。

| # | 情況 | 誰回 | 結果 | 由誰實作 | 測試把關（✓＝該 phase 自己釘；★＝71 補） |
|---|---|---|---|---|---|
| 1 | 非 JPEG／PNG／PDF | HTTP 立刻 | 415；**無 job、無 staging** | **62**（上傳）、**63**（鏡頭） | ✓ 62 `test_415不建任務也不寫staging`＋既有三顆 415 測試；71 只點名 |
| 2 | 鏡頭 token 無效／過期 | HTTP 立刻 | 404；**不讀檔**（先驗 token 再驗格式） | **63** | ✓ 63 三顆（亂 token／亂 token 連 staging 都不寫／過期 token）＋既有 `test_亂token加上非法格式回404不是415` |
| 3 | JPEG／PNG 看不懂或呼叫失敗 ×3 | worker | 刪 staging；無 `photo` 列；job=`failed` | **59** | ✓ 59 三顆（三次看不懂含 `vlm.calls == 3`／呼叫失敗也算一次／空白描述）；端點視角另有 63／64 各一顆 |
| 4 | PDF 某一頁 ×3 | worker | 跳過該頁；其他頁繼續 | **60** | ✓ 60 兩顆（第二頁三次失敗含「1＋3、不是整份重跑」斷言／每頁重試各自獨立） |
| 5 | PDF 0 頁成功，或檔無法拆頁 | worker | 同第 3 列（整筆失敗、不留列） | **60** | ✓ 60 兩顆（全頁看不懂／壞檔拆不開＝**0 次**模型呼叫） |
| 6 | embedding 失敗 | worker | 尚未 INSERT 則當這次失敗、算進 3 次；3 次後同第 3 列 | **59** | ✓ 59 `test_轉向量三次都失敗_不留照片_job標failed` |
| 7 | 入庫寫檔失敗（現有 cleanup 語意） | worker | 與現在的 cleanup 相同：清掉半成品再標失敗，不留孤兒列 | **59** | ✓ 59＋62 各一顆（兩顆炸的都是**縮圖**）；★ 71【補7】炸**原圖**（`save_original`）那一半 |
| 8 | Redis 當下掛了 | HTTP | 500；**連 staging 也別留**（先 staging 再入列的話，失敗路徑要刪 staging） | **62**（失敗路徑刪 staging）、**65**（真 Redis 才會掛） | ✓ 62 `test_入列失敗時回500而且staging與任務都不留`（＝丟不進佇列那一半）；★ 71【補8】JobStore 寫不進去那一半 |
| 9 | dismiss 一筆還在跑的 job | HTTP | 409 | **64** | ✓ 64 四顆（204／409 用 `queued`／404×2）；★ 71【補9】`analyzing`／`retrying` 也不准（parametrize 3 顆） |
| 10 | 已定案再 `PATCH` | 既有 | 409，本增量**不改** | （不動 `app/`） | ✓ 既有 `test_assign_folder.py`（Phase 27）——62 把 fixture 改成 202＋跑完任務後，全量回歸每次自動重走整條；71 只點名 |

### 3.4 §1.1「本增量明確推翻的舊決策」→ 哪個 phase 執行推翻

> 📌 **誠實標示：這張表是 10 列，不是 9 列。** 撰寫任務書上寫「9 列」，
> 但 `design5.md` 第 74〜85 行實際有 **10 列**。本表把 10 列全部列出，一列都沒少。

| # | 舊決策 | 本增量改成 | 由誰執行推翻 |
|---|---|---|---|
| 1 | `design.md v4`「上傳為同步處理；完成即代表文字、metadata、向量皆已儲存」；「明確不做非同步佇列」 | HTTP 完成＝檔已收下並入列；文字／metadata／向量在 worker 成功之後才存在 | **62**（回應碼與語意）、**59**（真正的入庫時機）、**72**（規格檔改字） |
| 2 | `design1.md`「明確不做非同步佇列」 | 本增量正式做 Redis ＋ Celery | **65**（程式）、**66**（容器） |
| 3 | `design2.md` D1「上傳後強制歸類彈窗」 | 上傳／快門後**不開**彈窗；彈窗只從待決定點開（**仍強制決定**：無 ×／Esc／點外） | **68**（上傳頁）、**69**（鏡頭桌面）；「仍強制決定」由 **70** 保住 |
| 4 | `design2.md` D4「瀏覽頁頂部分待決定｜資料夾」；`design3.md` D15「待決定｜資料夾｜待辦」 | 待決定升成頂欄；瀏覽頁只剩「資料夾｜待辦」 | **53**（頂欄）、**55**（瀏覽頁） |
| 5 | `design2.md` D2 文案「之後到瀏覽頁的待決定分頁完成歸類」 | 改成「到頂欄的待決定頁」 | **54**（改文案） |
| 6 | `POST /photos`、`POST /camera/{token}/photos` 成功 **201** ＋整份 `UploadResponse` | 成功受理 **202** ＋ `job_id`；建議改到照片入庫後、待決定開窗時再抓 | **62**（上傳）、**63**（鏡頭）、**61**（建議改從資料庫來） |
| 7 | Phase 37／design4「端點恰 20」 | 加任務清單與關掉失敗列，變成 **22** | **64**（同時改 `test_端點數不變` 的數字與註解） |
| 8 | 鏡頭桌面「uploaded → `GET latest` → 三關彈窗鏈」 | 快門 202 後不開鏈；`GET latest` 不再承擔「剛拍那張的歸類 payload」 | **63**（後端 latest 變窄）、**69**（桌面刪開鏈） |
| 9 | `design3` §2.1「待決定補完鏈無待辦窗；建議不持久化」 | 建議改落庫（D16）；待決定點開走**完整三關**（有待辦建議才開第三窗） | **56／61**（落庫）、**70**（三關） |
| 10 | Phase 30「實體／待辦建議只出現在上傳回應」 | 建議寫進 `photo` 列，待決定開窗再讀 | **56**（欄位）、**61**（寫入）、**70**（讀出） |

**未推翻（design5 §1.1 末段明列，一條都不准順手改掉）：**
定案不可逆（`PATCH` 只接受收件箱照片）、收件箱＝待決定的儲存位、
VLM 看不懂最終不留照片、415 格式錯誤仍同步、PDF 一頁一張照片、
人確認才釘實體／建待辦、embeddings 一律本機、單一使用者、不做刪除照片、
openapi 零 DELETE、Ollama 不進 Docker、`postgresql@14` 完全不動、
鏡頭 session 仍在 app 記憶體（worker 不參與配對）。

### 3.5 §1.2「被否決（不要重開）」13 列 —— 這是擋牆

> 這 13 條是產品負責人**已經考慮過並否決**的方案。
> 實作到一半「靈機一動」想改成其中任何一條的時候，**先回來看這張表**。
> 要重開任何一條，需要**產品負責人重新裁決**，不是實作者的判斷。

| # | 被否決的方案 | 為什麼否決 | 誰最容易手滑 |
|---|---|---|---|
| 1 | FastAPI `BackgroundTasks`／在 web 行程裡背景看圖 | 與 uvicorn 同行程；`--reload`／`restart app` 會丟掉進行中的工作；也拉不起獨立的兩個 worker | 62（「不如省掉 Redis？」） |
| 2 | 只用 Redis list、自寫 worker 迴圈 | 省掉 Celery，但要自己做 ack／崩潰重送／重試；side project 看起來瘦、維護肥 | 65 |
| 3 | PDF 每一頁一個 Celery 任務 | 同一份檔會被兩個 worker 拆開；進度列難畫。產品負責人要**一檔一任務** | 60 |
| 4 | 整份 PDF 當重試單位（一頁失敗就從頭再跑） | 已成功的頁會被重做；雲端費用與時間乘上頁數 | 60 |
| 5 | 進度只掛在上傳頁 | 換頁就看不見還在跑的工作；鏡頭連拍時人根本不在上傳頁 | 67 |
| 6 | 成功列留在進度面板當第二個待決定 | 成功的去處就是待決定；面板**只**顯示進行中與失敗 | 67 |
| 7 | 待決定改成獨立長頁表單（對話選項 B）或左右分欄（選項 C） | 產品負責人選 A：**沿用彈窗**，只加原圖 | 52、54 |
| 8 | 處理中的檔先 INSERT 空白 `text` 再補 VLM | 違反「`text` 為空的記錄不存在」；待決定也會出現空白卡 | 59、62 |
| 9 | 影像位元組當 Celery 參數／塞進 Redis | 多頁 PDF 太大；staging 走磁碟 | 58、62、65 |
| 10 | 關掉失敗列用 `DELETE /ingest-jobs/{id}` | Phase 37 釘死 **openapi 零 DELETE**；用 `POST …/dismiss` | 64 |
| 11 | 3 個以上 worker、或測試用本機 gemma4 並行 | 產品負責人上限 **2**；本機看圖並行會把機器打掛（Phase 48 已踩過） | 66 |
| 12 | 把 Ollama 搬進 Docker | 仍是 Linux VM，沒有 MLX、也吃不到這台 GPU（design4 的否決仍有效） | 66 |
| 13 | 建議繼續只活在 201 回應、不落庫 | 上傳改 202 後回應裡沒有建議；待辦窗會從此沒有入口 | 56、61 |

### 3.6 design5 §0 的四條禁止（**單獨列出，因為最容易被順手違反**）

> ## ⛔ 四條禁止（design5 §0 原文，不可協商）
>
> 1. **禁止：** 乙還沒好就把上傳頁改成 `multiple` 卻仍同步等 VLM。
>    → 那會**一次卡住 N 張**，比現在更糟。`multiple` 是 **Phase 68** 的事，
>    而 68 排在 ★G2 之後。
> 2. **禁止：** 把影像位元組塞進 Redis。
>    → Redis 是記憶體資料庫，多頁 PDF 幾十 MB 塞進去會爆。
>    任務 payload **只帶 `job_id`**，檔案走磁碟 `data/staging/`。
> 3. **禁止：** 為了進度面板新增 `DELETE` 進 OpenAPI。
>    → Phase 37 釘死的「openapi 零 DELETE」仍然有效。關掉失敗列用
>    `POST /ingest-jobs/{job_id}/dismiss`。
> 4. **禁止：** 處理中、尚未 VLM 成功的檔以**空白卡**出現在待決定。
>    → 待決定牆只查收件箱裡**真的有 `photo` 列**的照片。
>    沒有「先插一列空的再補內容」這種做法（見 §3.5 第 8 列）。

---

## 4. 三個閘門（誰確認、卡住怎麼辦）

> 🚦 **閘門是「人」的動作，實作者不可以自己勾掉。**
>
> 這三個框框裡沒有任何一件事是靠跑指令就能通過的。指令只是**證據**，
> 「看過證據、同意往下走」的那個動作必須由**產品負責人**做出來——
> 一句明確的話（口頭、對話、或 dev-prompt 檔案）。
>
> 實作者**不得**：自行勾選、「我覺得應該可以了」、「反正測試都綠了」、
> 「先做下一段，之後再回來補確認」。
>
> **計畫層的落實聲明：** design5 §0 的表格只說「甲合併後即可」「只有乙的 API 契約
> 穩定之後」，§10 只說「要你明示核准」。★G1／★G2／★G3 這三個名字與具體的停手範圍，
> 是**本計畫**把那幾句話落成實作者看得懂的動作，**不是 design5 自己寫的字**。

### ★ G1 —— 階段乙的入場券（design5 §0、§12「階段甲」）

| 項目 | 內容 |
|---|---|
| 是什麼 | 「待決定搬家做完了、產品負責人親眼看過、可以開始改上傳契約」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design5 §12「階段甲」四條驗收（本總覽 §5.1 有逐條指令） |
| 沒過會怎樣 | **Phase 62 起（上傳契約的破壞性變更）全部停擺**——phase-62 定稿 §2 明文要求 ★G1 已通過。**尤其不准動 `POST /photos` 的回應碼**（201→202 一旦動了、前端還沒跟上，整個上傳功能會看起來像壞掉）。56〜61 是純地基、對外行為零改變，定稿檔（56／57 的 §2）明文可與甲並行——G1 卡住時它們不必停；但總序仍建議照編號做，各檔的顆數基準也是照編號算的 |
| 卡住時怎麼辦 | 若產品負責人在瀏覽器上提出問題 → 回到對應的 phase（52／53／54／55）修，改完重看一次。**不要**用「先做乙、之後再回來修甲」繞過——甲是純前端，修起來很快；乙一開工就回不了頭 |

### ★ G2 —— 階段丙的入場券（design5 §0、§12「階段乙」）

| 項目 | 內容 |
|---|---|
| 是什麼 | 「後端的新契約穩定了，前端可以照著它寫」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design5 §12「階段乙」五條驗收（本總覽 §5.2 有逐條指令），其中**第 5 條需要真的跑一次雲端上傳看 worker log** |
| 沒過會怎樣 | Phase 67〜72 全部停擺。理由很實際：階段丙的前端**每一頁**都寫死了 `GET /ingest-jobs` 的回應形狀（`jobs[]`／`pending_count`／四種 `status`）。契約還在變的時候寫前端，等於改兩遍 |
| 卡住時怎麼辦 | ① 先確認是「契約錯」還是「環境沒起來」——`docker compose ps --no-trunc` 看 `redis`／`worker` 是不是 `Up`；② 若是 worker 沒吃到任務，先看 `docker compose logs worker`；③ 若是契約要調（例如欄位名不夠白話），**回到 64 改完再重跑全量**（`test_端點數不變` 的 22 是 64 定的；71 的逐支列名清點在丙末才會做），不要在丙階段一邊寫前端一邊改後端 |

### ★ G3 —— 動 `docs/spec/` 的唯一許可（design5 §10）

| 項目 | 內容 |
|---|---|
| 是什麼 | 產品負責人**明示核准解除** `docs/spec/` 唯讀 |
| 誰確認 | **產品負責人（人）**，而且必須是**明示**（「可以改規格」這種等級的話），不是推論 |
| 為什麼需要 | `docs/spec/` 是規格區、**唯讀**。本增量改的是「上傳何時算存好」這種**規格層級**的語意，不是實作細節。前兩次動規格（2026-08-21 改 `上傳照片.feature`、2026-08-23 摘標）都走了同一道核准 |
| 沒過會怎樣 | Phase 72 停擺，`.feature` **一個字都不准改**。此時 71 已經跑完、系統是可用的，只是規格檔的文字與行為不同步——這個狀態可以停很久，不急 |
| 卡住時怎麼辦 | 就停著。**不要**「先改好放著等核准」——`git status docs/spec/` 一旦不乾淨，後人 `git log` 只會看到「有人違規動了唯讀檔」。核准之後，改動要在 `.feature` 檔頭**留下核准紀錄**（比照 `上傳照片.feature` 既有的寫法） |

---

## 5. 總驗收清單（design5 §12 逐條抄錄 ＋ 每條要跑的指令）

> 這一節是 design5 §12 的**逐條原文**（16 條：甲 4、乙 5、丙 7），
> 下面補上「怎麼驗」。★G1 取 §5.1、★G2 取 §5.2、Phase 72 的驗收包三段全取。

### 5.1 階段甲（4 條）—— ★G1 的內容

- [ ] **頂欄為「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」**

  ```bash
  # 五個頁面都要有，而且文字逐字相同（全形括號）
  grep -c "待決定（" app/static/upload.html app/static/pending.html \
                     app/static/browse.html app/static/ask.html \
                     app/static/camera-desk.html
  # 每個檔至少 1；再用瀏覽器逐頁看一次，當頁那格要有 aria-current="page"
  ```

- [ ] **開 `/ui/pending.html` 看得到收件箱照片；點一張：彈窗最上面是原圖，下面仍是四個歸類出口**

  ```bash
  open "https://localhost:8000/ui/pending.html"
  # 人工確認：① 縮圖牆有照片 ② 點一張跳窗 ③ 窗頂是大圖
  #           ④ 下面四個出口：採用建議／改選現有／自建新資料夾／稍後再說
  #           ⑤ 沒有 × 、按 Esc 沒反應、點暗色區沒反應（強制決定，design2 D1 未推翻）
  ```

- [ ] **`/ui/browse.html` 預設是資料夾卡片，沒有待決定 tab；待辦 tab 仍在**

  ```bash
  open "https://localhost:8000/ui/browse.html"          # 直接看到資料夾卡片
  open "https://localhost:8000/ui/browse.html?tab=tasks" # 待辦仍可用
  grep -n "showPending" app/static/browse.html          # 預期：零輸出
  ```

- [ ] **定案後照片離開待決定、N-1；已定案不能再改夾**

  ```bash
  # 瀏覽器：在 pending 頁把一張照片歸到某個資料夾 → 該照片消失、頂欄數字少 1
  # 再用 curl 確認定案不可逆（換成真的 photo_id）：
  curl -k -s -o /dev/null -w '%{http_code}\n' -X PATCH \
    -H 'Content-Type: application/json' -d '{"folder_id":3}' \
    https://127.0.0.1:8000/photos/<已定案的 id>/folder
  # 預期：409
  ```

### 5.2 階段乙（5 條）—— ★G2 的內容

- [ ] **`pytest -q` 全綠、0 skipped**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  # 預期尾巴：<N> passed（N 由實作者當下填回本文件 §9）、沒有 "skipped" 字樣
  # ⚠ 絕對不要同時跑兩份 pytest（會互相 TRUNCATE 測試庫，症狀是隨機 404）
  OLLAMA_BASE_URL=http://localhost:9 pytest -q          # 顆數相同 ＝ 零 Ollama 依賴實證
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q     # 顆數也相同 ＝ 零 Redis 依賴實證（65 起）
  ```

- [ ] **單檔上傳 HTTP 202；當下待決定不會多一張；worker／測試跑完任務後才出現**

  ```bash
  psql -d PersonalDocAI -c "select count(*) from photo"          # 先記下來
  curl -k -s -w '\n%{http_code}\n' -F "file=@/path/to/test.jpg" \
    https://127.0.0.1:8000/photos
  # 預期：202，body 恰三鍵 {job_id, filename, content_type}
  psql -d PersonalDocAI -c "select count(*) from photo"          # 立刻查：數字不變
  curl -k -s https://127.0.0.1:8000/ingest-jobs                  # 看得到那筆 queued/analyzing
  # 等 worker 做完（本機 VLM 要 1〜5 分鐘；建議先把頁首開關切到雲端）
  psql -d PersonalDocAI -c "select count(*) from photo"          # 這時才 +1
  ```

- [ ] **Fake 三次失敗：待決定不出現、磁碟 staging 不留**

  ```bash
  pytest tests/integration/test_ingest_job.py -v
  # 預期：三次失敗那顆綠，斷言含「photo 列數 0」「staging 檔不存在」「job status == failed」
  ls data/staging/    # 正式環境手動煙霧之後也要是空的（或只剩未完成的）
  ```

- [ ] **`docker compose ps` 看得到 `redis` 與 `worker`；worker 為 2 個 concurrency**

  ```bash
  docker compose ps --no-trunc
  # 預期：四列 db / app / redis / worker，狀態 Up；redis 是 Up (healthy)
  # worker 的 COMMAND 欄看得到 --concurrency=2
  # ⚠ --no-trunc 不能省：預設只印開頭 20 個字左右，--concurrency=2 在尾巴，不加就永遠看不到
  ```

- [ ] **頁首切雲端後上傳，worker log 的 `backend=cloud`（手動）**

  ```bash
  # 1. 瀏覽器開任一頁，把頁首「AI 模型」開關切到「雲端」
  # 2. 上傳一張圖
  docker compose logs --tail=200 worker | grep "backend="
  # 預期：看得到 AI 開始 kind=vlm backend=cloud model=...
  #       （這一行由 design4 Phase 41 的 services/ai_timing.py 產生。Phase 59 的
  #         run_ingest_job 看圖時必須帶 target=vlm_service.vlm_timing_target(vlm)——
  #         worker 是另一個行程，不帶 target 它會退回讀自己那份 config.AI_BACKEND、
  #         永遠印 backend=local，這條驗收就永遠過不了。59 §6 有驗收條、65 §4.10 再驗一次）
  ```

### 5.3 階段丙（7 條）

- [ ] **電腦一次選 3 張：3 列進度，可立刻再選下一批，不必等 VLM**

  ```bash
  open "https://localhost:8000/ui/upload.html"
  # 人工：選 3 個檔 → 右下角出現 3 列 → 立刻再選第 4 個檔（不必等）
  curl -k -s https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
  # 預期：jobs 陣列 4 筆，其中最多 2 筆是 analyzing（只有 2 個 worker）
  ```

- [ ] **成功列自己消失，N 加上去；失敗列留下，× 關掉後面板可收起**

  ```bash
  # 人工：盯著面板看成功的那列自己不見、頂欄數字 +1
  # 失敗列按 ×，確認：
  curl -k -s -o /dev/null -w '%{http_code}\n' -X POST \
    https://127.0.0.1:8000/ingest-jobs/<那個 job_id>/dismiss
  # 預期 204；再 GET /ingest-jobs 該筆不見；jobs 空了面板自己收起
  ```

- [ ] **換到問問題頁，進行中的列還在**

  ```bash
  # 人工：上傳中直接點頂欄「問問題」→ 右下角面板還在、內容一樣
  #       按 F5 重新整理 → 還在（狀態來自伺服器，不是瀏覽器記憶體）
  ```

- [ ] **手機連拍至少 2 張不必等第一張看完；桌面不跳出歸類鏈**

  ```bash
  # 用區網 IP 開桌面頁（不要用 localhost，QR 會猜到 Docker 網段）
  ipconfig getifaddr en0
  open "https://$(ipconfig getifaddr en0):8000/ui/camera-desk.html"
  # iPhone 掃 QR → 連按兩次快門 → 兩次都馬上可以再拍
  # 桌面：不跳出抽屜／實體／待辦任何一個彈窗；只有右下角面板多兩列
  ```

- [ ] **一份兩頁 PDF：進度一列；成功頁進待決定**

  ```bash
  curl -k -s -w '\n%{http_code}\n' -F "file=@/path/to/two-pages.pdf" \
    https://127.0.0.1:8000/photos          # 202
  curl -k -s https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
  # 預期：jobs 只有【一】列（D11 一檔一任務），page_count=2、pages_done 會往上跑
  # 做完之後：待決定多兩張（每頁一張，design3 的 PDF 一頁一張照片未推翻）
  ```

- [ ] **待決定點開：窗頂有原圖；有待辦建議會開第三窗，沒有則不跳（空關不跳）**

  ```bash
  open "https://localhost:8000/ui/pending.html"
  # 人工：點一張有待辦建議的 → 抽屜 → 實體 → 待辦窗（標題／到期日已預填）
  #       點一張沒有待辦建議的 → 抽屜 → 實體 → 直接收工，第三窗不跳
  psql -d PersonalDocAI -c \
    "select id, suggested_category, suggested_entity, suggested_task_title, suggested_task_due
       from photo order by id desc limit 5"
  # 先用這個確認哪張有建議、哪張沒有，再去點
  ```

- [ ] **console 沒有非預期錯誤；`alert`／`confirm`／`prompt` 仍禁用**

  ```bash
  grep -rn "alert(\|confirm(\|prompt(" app/static/
  # 預期：零輸出（或只在註解裡出現「禁用 alert」這種說明文字）
  # 瀏覽器：五個頁面各開一次 DevTools Console，只能有預期的日誌
  ```

---

## 6. 進度勾選區

> 📌 2026-08-25：Phase 52〜58 已實作完成（依產品負責人指示**未 commit**；每 phase 均經
> 獨立審查，紀錄在 `docs/plan/report/2026-08-25-增量五甲段-REP.md` 與
> `…乙地基-REP.md`）。★G1 的四條驗收**待產品負責人親自做**——實作者依規不勾。

```text
── 階段甲：待決定獨立入口 ────────────────────────────────────
[x] Phase 52  app/static/pending.html 新建、showPending 搬過來
[x] Phase 53  五頁頂欄四格（N 用 GET /folders 收件箱 photo_count）
[x] Phase 54  folder_modal.js 窗頂原圖＋「稍後再說」文案改指待決定頁
[x] Phase 55  browse.html 拿掉待決定 tab、無 query 預設資料夾
[ ] ★★★ G1   產品負責人照 §5.1 四條看過並明示「可以改上傳契約」

── 階段乙：入庫佇列 ──────────────────────────────────────────
[x] Phase 56  db/migrate_design5.sql 三欄（正式庫跑兩次證冪等）＋schema.sql 對齊
[x] Phase 57  ingest_job_store.py＋InMemoryJobStore＋conftest 第四道 wire_memory_job_store
[x] Phase 58  staging_service.py（寫／讀／刪／24 小時掃把；啟動接線在 65）
[ ] Phase 59  run_ingest_job() 單圖：3 次重試、成功 INSERT 收件箱、失敗清乾淨、photo_ids 冪等
[ ] Phase 60  同一任務跑完整份 PDF：逐頁 3 次、跳頁、0 頁成功才整筆失敗、pages_done 續跑
[ ] Phase 61  D16 三欄隨 INSERT 落庫；GET /folders/{id} 摘要 五鍵 → 八鍵
[ ] Phase 62  POST /photos 回 202（既有 201 斷言全面改寫，含 BDD binder）
[ ] Phase 63  POST /camera/{token}/photos 回 202、不 set_latest；GET latest 行為變窄
[ ] Phase 64  GET /ingest-jobs ＋ POST /ingest-jobs/{id}/dismiss；端點清點 20 → 22
[ ] Phase 65  celery_app.py＋RedisJobStore＋requirements 加 celery／redis
              ＋掃把接線兩頭（main.py lifespan／worker_ready）＋build_vlm_for_backend
[ ] Phase 66  compose.yaml 加 redis／worker；compose.dev.yaml 加 worker bind-mount；文件更新
[ ] ★★★ G2   產品負責人照 §5.2 五條看過並明示「契約穩了，前端可以開工」

── 階段丙：非同步 UX ─────────────────────────────────────────
[ ] Phase 67  progress_panel.js（2 秒輪詢、四種狀態、× dismiss、收起、頂欄 N）
[ ] Phase 68  upload.html multiple＋每檔一個 POST＋拿掉 201 開鏈＋文案改寫
[ ] Phase 69  camera-phone.html 202 即可再拍＋窄條；camera-desk.html 刪 latest 開鏈
[ ] Phase 70  待決定走完整三關（抽屜→實體→有待辦建議才開待辦窗），建議讀 D16 三欄
[ ] Phase 71  §8 十列逐列點名＋補三缺口（新檔 20 顆）＋端點 22 逐支列名＋零 DELETE＋掃碼
[ ] ★★★ G3   產品負責人明示核准解禁 docs/spec/

── 收尾 ──────────────────────────────────────────────────────
[ ] Phase 72  四份 .feature 改「收下 ≠ 已入庫」＋檔頭留核准紀錄＋產出驗收包
```

> 📌 **commit 節奏提醒（詳見 §7 鐵律 12）：** 本增量的 commit 節奏由**產品負責人**決定。
> 未指示前不要自己 commit、也不要把 `unfinish/` 搬進 `finish/`（歸檔隨 commit 執行）；
> 各 phase 的 git 驗收一律用「**與開工前快照相減**」的寫法，兩種節奏都成立。

---

## 7. 全域鐵律（每個 phase 的計畫檔都隱含這一節，違反等於做錯）

### 1. 全程 TDD

先寫**會紅**的測試 → **真的跑它、親眼看到紅** → 寫最小實作 → 跑綠 → 收工。
「跑它確認紅」這一步不可以跳過——沒看過紅的測試，你不知道它到底有沒有在測東西
（Phase 37 就是靠這個流程揪出「自創實體＋釘選非原子」的真缺陷）。
前端 phase 依本專案慣例**不做 Playwright 自動化**、以瀏覽器實操驗收為主
（逐項做完、console 要乾淨）；但定稿的 21 份裡真正「零新增自動化測試」的
只有 **52 與 54**——53（+7）、55（+3）、67（+7）、68（+3）、69（+3）、70（+3）
都帶少量**原始碼字串契約測試**（比照既有 `片語` 測試的做法，design5 §9 末段授權），
顆數見 §9 的表。

### 2. pytest 的四道安全網，一道都不准繞過

pytest **絕不打真 Ollama、絕不連真 Redis、絕不啟動 Celery 容器、絕不寫專案 `data/`、
絕不清正式庫**。靠 `tests/conftest.py` 的 autouse fixture：

| fixture | 擋掉什麼 | 誰加的 |
|---|---|---|
| `reset_tables` | 每測清空**測試庫**的表並重播六筆資料夾種子；**絕不清正式庫** | 既有 |
| `wire_fake_ai` | AI 與時鐘全部換成假件；**pytest 絕不呼叫真 Ollama**（本機 Ollama 常駐，忘了覆寫會誤觸真模型推論，一顆測試跑一分鐘） | 既有 |
| `isolated_data_dir` | `config.DATA_DIR` 指到臨時目錄；**pytest 絕不寫專案 `data/`**（`data/staging/` 也一樣） | 既有 |
| **`wire_memory_job_store`** | `get_job_store()` 指到 `InMemoryJobStore`；**pytest 絕不連真 Redis** | **Phase 57 新加，名字照這個** |

### 3. 絕對不要同時跑兩份 pytest

兩個終端機、或「人跑一份、agent 跑一份」都不行。`reset_tables` 每個測試都會
`TRUNCATE` 同一個測試庫，兩份同時跑會互相清掉對方的資料。
**症狀是大量看似隨機的 404「找不到照片」與 `TypeError: 'NoneType' object is not subscriptable`，
而且每次紅的顆數都不一樣**——看起來像程式壞了，其實只是撞在一起
（2026-08-24 實際踩過，用 `pg_stat_activity` 才抓到一邊在 TRUNCATE、一邊在 INSERT）。
等另一份跑完再跑。

### 4. SQL 只准出現在 `app/repositories/photo_repository.py`

router 零 SQL、service 零 SQL、Celery 任務也零 SQL。
本增量特別容易犯規的兩處：
① Phase 64 的 `pending_count`（收件箱照片數）**不寫任何新 SQL、也不新增 repository 函式**
（該檔 §4.0 的裁決：既有 `photo_repository.list_folders()` 回的收件箱 `photo_count`
已經是這個數字，直接用）——尤其不可以在 router 裡自己寫 `SELECT count(*)`；
② Phase 59／61 的 worker INSERT 一樣走**既有的** repository 函式
（`insert_photo`／`update_photo_paths`／`delete_photo`……），
`ingest_job.py` 與 `celery_app.py` 全程零 SQL（71 的掃碼會驗）。

### 5. `openapi.json` 零 DELETE

Phase 37 釘死的規矩仍然有效。關掉失敗列用 `POST /ingest-jobs/{job_id}/dismiss`，
**不是** `DELETE`。既有的 `test_openapi裡沒有任何DELETE動詞` 一字不改，全程保綠。

### 6. 這些東西本增量一律不做

不新增刪除照片端點、不做多使用者、不做對話記憶、**embeddings 一律本機**
（向量必須跟庫裡既有的 bge-m3 同源，所以它**不歸頁首那顆 AI 開關管**——
只有看圖／路由／回答／實體建議四個注入點歸開關管）。

### 7. 正式庫改結構一律走「可重跑的遷移腳本」

Phase 56 的 `db/migrate_design5.sql` 必須是**冪等**的（跑兩次結果一樣），
寫法比照既有的 `db/migrate_design3.sql`。
**絕不准**用 `db/schema.sql` 重建正式庫——那個檔開頭是 `DROP TABLE IF EXISTS`，
跑下去正式庫的照片就沒了。`schema.sql` 只給**測試庫**重建用。
執行前先備份（`CLAUDE.md` 指令區有兩種寫法），執行後**真的跑第二次**證明冪等。

### 8. `docker compose down -v` 永遠禁止

`-v` ＝連 named volume 一起刪 ＝ **刪掉正式庫**（`personaldocai_pgdata` 裡是正本）。
停服務一律用 `docker compose stop`。同理危險的還有
`docker system prune --volumes`、`docker volume prune -a`、
`docker volume rm personaldocai_pgdata`、Docker Desktop 的 "Reset to factory defaults"。
本增量新增的 `redisdata` volume（實際名字 `personaldocai_redisdata`）相對不痛
（丟了只丟進度列與還沒分析完的任務），但**指令是同一個**——養成不打 `-v` 的習慣。

### 9. `postgresql@14`（5432 埠）全程不准碰

那是別的專案（wanderlove、fse_chat_room）的資料庫。不准停、不准改、不准連。
本專案一律 `127.0.0.1:5433`、帳號 `postgres`。

### 10. `docs/spec/` 唯讀——Phase 72 之前一個字都不准改

Phase 52〜71 期間 `git status --short docs/spec/` 必須是**乾淨的**。
Phase 72 動手之前要先過 ★G3（產品負責人明示核准解禁）。
核准之後，改動要在 `.feature` 檔頭留下核准紀錄。
「先改好放著等核准」也不行——見 §4 的 ★G3 那一格。

### 11. QR 尺寸那顆測試不准改小

`app/static/style.css` 的 `.cd-qr svg { max-width: 20rem; }` 是增量四唯一一次改產品碼，
背後是 2026-08-25 真機驗收踩到的**安靜壞掉**：改用 `<主機名>.local` 之後網址從 93 變 118 字元、
QR 從 49 格變 53 格，`15rem` 時每格只剩 4.5px，**QR 畫得出來但 iPhone 掃不到**。
有一顆 `test_qr的顯示尺寸夠大讓長網址也掃得到` 把值釘死，改小會紅。本增量不准動它。

### 12. commit 節奏由產品負責人決定；git 驗收一律用「與開工前快照相減」

21 份定稿裡有兩種節奏並存：**56〜61** 帶「跑綠 → `git commit`」的步驟
（本專案 TDD 慣例），而 **66／70／71／72** 明文「沿用產品負責人既有指示：
不 commit、改完先檢視；`unfinish/` → `finish/` 的歸檔隨 commit 執行」
（呼應增量四階段丙 45〜51 依指示未 commit 的前例）。**兩種都不是實作者可以自己選的**：

- **本增量到底逐 phase commit、還是整批一次，由產品負責人決定**；他沒指示前，
  照 66〜72 的寫法**先不 commit**（56〜61 檔內的 commit 步驟此時跳過，訊息文字留著備用）。
- 為了讓兩種節奏都驗得動，各 phase 的 git 驗收**一律用「與開工前快照相減」**的寫法
  （開工先 `git status --short -- app tests > /tmp/pNN-before.txt`，收工再比一次——
  67／68／69 的定稿就是這樣寫的）；**不要**寫「`git status` 只准有 X 個檔」這種
  只在「前面都已 commit」時才成立的斷言。
- 不管哪種節奏：**不准自己把計畫檔搬進 `finish/`**（`git mv` 會直接 stage），
  歸檔動作隨 commit 執行（Phase 72 §4.9 只列清單）。

---

## 8. 已知限制（MVP 刻意為之；design5 §13 的白話重寫）

### 8.1 本機 VLM 仍然很慢，兩個 worker 不會讓它變快

**是什麼：** 兩個 worker 只讓你「一邊看兩張」，gemma4 本身還是 64〜88 秒一張
（加了實體／待辦建議的長 prompt 之後最慢 2〜5 分鐘）。三張圖仍然要跑兩輪。

**為什麼可以接受：** 這個增量解決的是「**人被卡住**」，不是「模型變快」。
以前是「人跟機器一起等」，現在是「機器自己等，人去做別的事」。
真的要快就用頁首開關切**雲端**（實測單張 1.9 秒），手動煙霧一律建議先切雲端。
worker 上限 2 是產品負責人明訂的（D6），也是實測結論——
Phase 48 曾把上傳與詢問同時打，把 db container 壓垮（postmaster 花 2 分鐘才殺得掉子行程）。

### 8.2 `--reload` 救不了 worker

**是什麼：** 開發模式（`compose.dev.yaml`）裡 uvicorn 有 `--reload`，你存檔它自己重啟。
**Celery 沒有這個功能**——它不會盯著檔案。改完 `app/` 底下的 Python 之後，
`worker` 還在跑舊碼。症狀很難聯想：「HTTP 已經是新行為、分析結果卻還是舊的」。

**為什麼可以接受：** 加一行手動指令就解決，而且 design5 §7 明文要求寫進文件：

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

替 worker 也裝一套檔案監看（例如 `watchdog` 包一層）是**多餘的複雜度**，
side project 不值得。Phase 66 要把這條寫進 `LAUNCH.md` 與 `CLAUDE.md` 指令區。

### 8.3 Redis 的 volume 不是正式庫，丟了不心疼

**是什麼：** Redis volume（`redisdata`，實際名字 `personaldocai_redisdata`）裡只有「進度列」與「哪個 staging 檔對應哪個任務」。
丟了的話，進行中的任務會消失、staging 目錄會留下孤兒檔。

**為什麼可以接受：** `photo` 的**正本**仍在 Postgres ＋ `data/photos`，一張都不會少。
而且 §4.1 的 24 小時掃把會把孤兒 staging 檔清掉
（規則：mtime 超過 24 小時**且** JobStore 沒有對應的進行中任務）。
最壞情況是「有幾張圖沒進庫，重新上傳一次」——可接受的代價。
（還是開了 AOF：`appendonly yes`，重開 Docker 之後進度列與失敗列會回來。）

### 8.4 鏡頭 token 仍在 app 的記憶體裡

**是什麼：** 重啟 `app` ＝配對失效，QR 要重產、手機要重掃。這跟現在一模一樣，本增量沒改。

**為什麼可以接受：** 已經 202 收下的檔**由 worker 繼續做完，不依賴 token**——
token 只管「這支手機有沒有權限往這台電腦傳檔」，檔案一旦落到 staging 就跟 token 無關了。
真正想解決要把 session 搬進 Redis，那會牽動 WebSocket 信令的整個設計，
而且 design5 §3 明文「不做水平擴 app replica」——沒有第二個 app，就沒有必要。

### 8.5 host 的 `.venv` 與容器映像的套件版本會分岔

**是什麼：** `requirements.txt` 全部用 `>=`，而容器映像是在 `docker compose build` 當下
才解析版本的。所以「host 的 `.venv`」與「容器裡」會慢慢不一樣
（增量四實測：langchain-core host 1.5.6／container 1.6.0）。
意思是 `pytest -q` 全綠**驗的是 host 那一份環境，不等於驗過實際跑的映像**。
加了 `celery` 與 `redis` 兩個套件之後這個落差更明顯。

**為什麼可以接受：** side project 先不釘版；代價是「**重建映像**要當成需要手動煙霧一次的動作」。
Phase 65／66 之後每次 `docker compose build`，至少跑一次「上傳一張圖 → 等 worker 做完 →
看得到照片進待決定」。真的要根治就把 `pip freeze` 釘進 requirements（或另開 `requirements.lock`）——
本增量**不做**。

### 8.6 進度是「輪詢」的，不是即時推播

**是什麼：** 前端每 2 秒問一次 `GET /ingest-jobs`。所以進度列最多會慢 2 秒才更新。

**為什麼可以接受：** 一次分析要 1〜5 分鐘，慢 2 秒完全無感。
改成 WebSocket 推播要多維護一條連線、多處理斷線重連，
而本專案的 WebSocket（鏡頭信令）已經是最複雜的一塊了，不值得再加一條。

### 8.7 失敗了不能按「再試一次」

**是什麼：** design5 §3 明文「不做失敗列手動再試一次」。3 次自動重試做完就是做完了。

**為什麼可以接受：** 自動已經試了 3 次（含第一次）。連 3 次都看不懂的圖，
第 4 次通常也一樣——要嘛換一張拍得清楚一點的，要嘛切到雲端模型再傳一次。
重新選檔／重拍就等於重試，多一顆按鈕只是多一條要維護的路徑。

### 8.8 待決定沒有「一次勾多張」

**是什麼：** design5 §3 明文「不做批次歸類」。一張一張點、一張一張走三關。

**為什麼可以接受：** 歸類這件事本來就要看圖判斷，批次選了也還是要一張張決定放哪。
真正省時間的是「上傳不再卡住」，那件事這個增量做了。

---

## 9. 顆數與端點數的變化軌跡

> ⚠️ **下表的「新增幾顆」逐份抄自 21 份定稿計畫檔自己宣稱的數字**（哪一份的哪一行，
> 見各檔 §2／§6）；「做完後累計」是**照編號順序做**推算出來的參考值。
> 實作時一律以 `pytest -q` 實查為準——**要對的是「本 phase 新增幾顆」，不是絕對數字**
> （56〜58 定稿明文可與甲並行，所以那三份檔內的絕對數字是「跳過甲直接做乙」情境的，
> 見表下的兩則註記）。
>
> **不變的規則：顆數只增不減。**
> 任何一個 phase 做完之後，`pytest -q` 的 passed 數字**不可以比上一個 phase 少**，
> `skipped` 全程**必須是 0**（Phase 51 已經把 `@未實作` 摘光了）。
> 少了就是有人刪測試或標了 skip，**先查，不要改測試去湊**。

| Phase | 這個 phase 對顆數做了什麼（定稿宣稱） | 新增 | 做完後累計（照編號做） | 端點數 |
|---|---|---|---|---|
| （開工） | 2026-08-25 實測基準 | — | **405 ＋ 0 skipped** | **20** |
| 52 | 純前端新頁（零新增自動化測試） | +0 | 405 | 20 |
| 53 | 新檔 `test_nav_header.py`（7 顆前端契約） | **+7** | 412 | 20 |
| 54 | 純前端彈窗（零新增） | +0 | 412 | 20 |
| 55 | `test_nav_header.py` 追加 3 顆 | **+3** | 415 | 20 |
| 56 | 遷移冪等＋repository 讀寫三欄，新增 5 顆；另**改** 1 顆鍵集合斷言（五鍵→八鍵，改不計顆） | **+5** | 420 | 20 |
| 57 | 新檔 `test_ingest_job_store_unit.py`（12 顆） | **+12** | 432 | 20 |
| 58 | 新檔 `test_staging_service_unit.py`（10 顆） | **+10** | 442 | 20 |
| 59 | 新檔 `test_ingest_job.py`（11 顆：成功／3 次失敗／embedding 失敗／寫檔失敗／冪等重送／計時 log） | **+11** | 453 | 20 |
| 60 | 新檔 `test_ingest_job_pdf.py`（9 顆：跳頁／0 頁成功／`pages_done` 續跑／清單只讀一次；與 59 的檔合跑＝20） | **+9** | 462 | 20 |
| 61 | `test_ingest_job.py` 追加 7＋`test_folders_endpoint.py` 追加 2（另改 2 顆鍵集合斷言，不計顆） | **+9** | 471 | 20 |
| **62** | **改寫 113 個既有 201 測試項目**成「202 → 跑任務 → 原本的 Then」（含 BDD binder；`test_photos_upload.py` 13 顆＝留 5＋換 2＋新 6）——⚠ 改寫是同一顆測試從 2 步變 4 步，**不是刪掉再寫一顆，顆數仍只增不減** | **+6** | 477 | 20 |
| 63 | `test_camera_endpoints.py` 34 → 38（新 5、刪 1，含 latest 行為變窄的新釘）；binder 改寫 | **+4** | 481 | 20 |
| **64** | 新檔 `test_ingest_jobs_endpoint.py`（12 顆）＋**改 `test_端點數不變` 的 20 → 22**（改不計顆） | **+12** | 493 | **20 → 22** ← 本增量**唯一**一次端點變動 |
| 65 | 5 顆 celery 煙霧＋9 顆 `RedisJobStore` 序列化（**假 client，不連真 Redis**） | **+14** | 507 | 22 |
| 66 | Compose 設定與文件（真容器煙霧是**手動**，不進自動化） | +0 | 507 | 22 |
| 67 | 新檔 `test_progress_panel_contract.py`（7 顆）；`test_nav_header.py` 一顆**原地換掉**（不計顆） | **+7** | 514 | 22 |
| 68 | `test_progress_panel_contract.py` 追加 3 顆 | **+3** | 517 | 22 |
| 69 | 同檔再追加 3 顆 | **+3** | 520 | 22 |
| 70 | 後端契約 1 顆（首跑就綠）＋新檔 `test_pending_chain.py` 2 顆 | **+3** | 523 | 22 |
| **71** | 新檔 `test_design5_error_paths.py` **20 顆**＝5 顆補缺（【補7】1＋【補8】1＋【補9】3）＋15 顆掃碼（掃A 3＋掃B 2＋掃C 4＋掃D 4＋掃E 2）；§8 其餘各列**點名**既有測試、不重寫 | **+20** | 543 | 22 |
| 72 | 四份 `.feature` 文字改版；定稿 §2 明文「本 phase **不會改變**顆數」（binder 只跑不改） | +0 | **543** | 22 |
| （收工） | 合計 +138 | — | **543 ＋ 0 skipped**（照編號做的推算值，以實查為準） | **22** |

> ⚠️ **已知斷鏈（定稿檔之間的數字對不上，以各檔「自己那份新增幾顆」為準）：**
> `phase-59` §2 寫「必要前置 Phase 57 加 **11**……（＝441）」，但 `phase-57` 定稿通篇是
> **12 顆**（新檔 12 passed、範圍與 commit 訊息皆 12）——59 那句是舊數字沒跟上。
> 照編號做到 59 開工時應是 **442**、做完 **453**。實作時以 `pytest -q` 實查為準。
>
> 📌 **56〜58 檔內的絕對數字是另一條路徑的：** 這三份定稿明文「可與甲並行」，
> 所以檔內舉例的絕對值假設「跳過甲直接做乙地基」（56：基線 405 → 410；57：若在 56 後
> 基線 410；58：若 56→57→58 依序做＝422）。照編號做時要自己把甲段的 +10 加上去——
> 這正是它們通篇改用「基線」稱呼、要你**實查**的原因。

### 端點數怎麼算（不要用 `app.routes`）

```python
# 正確做法（既有 test_端點數不變 就是這樣寫的）
paths = client.get("/openapi.json").json()["paths"]
運算元 = [(path, method) for path, item in paths.items() for method in item]
assert len(運算元) == 22
```

⚠️ **不要用 `app.routes` 清點**——FastAPI 0.141 有 `_IncludedRouter` 的已知坑，
路由不會被攤平，數出來的數字是錯的（`~/.claude/.../memory/fastapi-routes-not-flattened.md` 有記）。

⚠️ **WebSocket `/camera/{token}/signal` 不算在裡面**——依 FastAPI 的行為它不會出現在
`openapi.json`。本增量也不加新的 WebSocket。

### 20 → 22 是哪兩支

| 方法 | 路徑 | 加在哪個 phase |
|---|---|---|
| `GET` | `/ingest-jobs` | 64 |
| `POST` | `/ingest-jobs/{job_id}/dismiss` | 64 |

改的（不影響數量，只改回應碼與 body）：`POST /photos`（62）、
`POST /camera/{token}/photos`（63）、`GET /camera/{token}/latest`（63，行為變窄）。

---

## 10. design5 沒寫清楚、由計畫層裁決的項目（給實作者與產品負責人的誠實揭露）

> 📌 **本節的前身是「撰寫本總覽時發現的缺口」表**：總覽先寫、21 份 phase 後成稿，
> 當時列了 5 處「design5 有寫、但沒人接」。**定稿之後 5 條全部有主了**——
> 本節改為記錄「design5 怎麼寫的 → 計畫層怎麼裁決 → 落在哪個 phase」，
> 讓產品負責人一眼看出**哪些判斷是計畫自己補的**（不是 design5 的字）。
> 要推翻其中任何一條，請直接對對應 phase 檔提出，**不要**由實作者自行改判。
> （phase-67 §4.7 引用本表「第 3 列」、phase-69 §3 引用「第 4 列」——列序不可重排。）

| # | design5 怎麼寫的 | 計畫層怎麼裁決 | 落在哪個 phase |
|---|---|---|---|
| 1 | §4.1 末條：「**worker／app 啟動時**掃 staging，mtime 超過 24 小時且 JobStore 沒有對應進行中任務 → 刪掉」——只講了要掃，沒指派誰在啟動時呼叫 | 函式與接線**分開**：58 只寫 `sweep_stale_staging()` 函式與測試、其「明確不做」表明文不接線；**兩頭的程式接線都在 65**——app 這頭是 `main.py` 的 lifespan、worker 那頭是 `celery_app.py` 的 `worker_ready` 訊號（app 與 worker 是兩個行程，**兩處少一處都是安靜壞掉**，65 §6 有驗收條釘住）；66 零程式碼，只在真容器 log 驗兩把掃把真的跑了。⚠ 本表舊版寫「58 負責 app 啟動＋66 負責 worker」——**那是錯的**，以定稿為準 | **58**（函式）→ **65**（接線兩頭）→ **66**（真容器驗證） |
| 2 | §12 階段乙第 5 條要驗「worker log 的 `backend=cloud`」，但沒明講 worker 的 VLM 呼叫要包 `ai_timing` | `run_ingest_job` 的看圖／轉向量沿用 design4 的 `ai_timing.log_ai`（kind 仍是 `vlm`／`embed`；PDF 逐頁比照 design4 D7「每頁各一組」），且**必帶 `target=vlm_service.vlm_timing_target(vlm)`**——worker 是另一個行程，不帶 target 的話 `ai_timing` 會退回讀 worker 自己那份 `config.AI_BACKEND`（永遠 local）：log 說謊但功能正常，G2 第 5 條永遠過不了。59 的實作碼與 §6 驗收清單都有帶；65 §4.10 在接上 Celery 時要求再親手驗一次 | **59**（實作＋驗收）、**60**（逐頁沿用同一個 helper）、**65 §4.10**（再驗）、**66**（真容器煙霧＝G2 第 5 條） |
| 3 | D8 說進度面板含「**手機取景**」；§6.5 卻說 camera-phone「進度用**窄條**，不擋快門」——兩句對不起來 | 取 §6.5（更具體、理由寫在它裡面——「不擋快門」；`.cp-controls` 就貼在畫面下緣，右下角面板一定壓到「開閃光」）：**67 做桌面五頁**（upload／pending／browse／ask／camera-desk）的完整面板、**69 做 camera-phone 的窄條**。手機端「可以」呼叫同一支 `GET /ingest-jobs`（只是**不要**把整個面板疊在取景畫面上擋到快門）；69 §4.2 進一步選了**連打都不打**——窄條只講純本地的「已送出幾張」（省電、零新失敗模式）。兩份定稿各自附理由、結論一致（完整說明在 67 §4.7） | **67**（桌面五頁）、**69**（手機窄條） |
| 4 | §5 末段：「手機端**可**繼續送 `uploaded` 當『這張已進佇列』通知桌面」——「可」＝可選，沒說做不做 | **69 §3「做」第 5 項明確裁決：做（保留）。** 理由：(a) 桌面按快門後的解鎖靠它（`收到照片()` 的 `等照片(false)`），不送的話從電腦按快門會**永遠鎖死**；(b) 桌面「這次配對已收下 N 張」的計數也靠它。桌面收到後**只**更新計數與進度面板（`ppStart()`）、不開任何彈窗——「桌面只更新進度／預覽狀態，不開 `classify_chain`」是 design5 的硬規定，69 §4.4 落地 | **69**（§3「做」第 5 項） |
| 5 | §11 列了會動到的檔，但沒說 202 之後 `UploadResponse`／`PdfUploadResponse` 的去留 | 跟著「最後一個呼叫者消失」分兩步刪：**62 刪 `_ingest_pdf`＋`PdfUploadResponse`＋`PDF_PAGE_CONTENT_TYPE`**（`_ingest_pdf` 的唯一呼叫者在 62 消失），並在 `UploadResponse` docstring 註明退休時程；**63 改完鏡頭端點、`_ingest_image` 零呼叫者之後，連同 `UploadResponse`／`TaskSuggestion` 一起刪**（63 §4.4 有完整步驟與 grep 閘門）。不默默留著 | **62**（PDF 那組）、**63**（單圖那組） |

**21 份定稿另外補的幾個計畫層判斷**（design5 也沒裁到，一併記錄）：

- **AI 開關要不要補到瀏覽／待決定兩頁**——design5 §6.1 的頂欄示意圖畫了
  `[AI 本機｜雲端]`、還寫「每一頁的 header 都長這樣」，但 §3「做」與 §11 都沒指派。
  **53 裁決：不默默補**（開關狀態存在伺服器，上傳頁撥了全站都跟著、功能不缺）；
  這是**未指派的產品決策**，★G1 驗收時當面請產品負責人裁決，他沒說要補就維持現況
  （52／53 的「明確不做」表各有完整說明）。
- **「稍後再說」的兩句舊文案**（`classify_chain.js` 第 53 行與 `upload.html` `pdf摘要()`）——
  Phase 55 刪掉瀏覽頁待決定分頁之後、到 68／69 改文案之前，它們會指向一個不存在的分頁。
  **54／55 裁決：不偷偷修**（主人是 68／69），這段期間看到它是**預期、不是 bug**，
  ★G1 時當面向產品負責人交代（54／55 的「明確不做」表＋55 §7 陷阱 5）。
- **PDF 某一頁「寫檔失敗」怎麼辦**——§8 第 4 列只講 VLM 失敗、第 7 列只講單圖。
  **60 裁決：當成「跳過該頁」**（已成功的頁不受影響；每頁都寫檔失敗＝`photo_ids` 空
  → 走整筆失敗），由 `test_某頁寫檔失敗_當成跳過該頁_其他頁照樣入庫` 釘住（60 §4 步驟 3 末的醒目說明）。
- **`skipped_pages` 不在 `IngestJob` 契約裡**——**60 裁決：不加欄位**，跳過頁數是
  算得出來的衍生值 `pages_done − len(photo_ids)`（60 的「明確不做」表）。
- **design5 §10 只列三份 `.feature`**——「`歸類照片.feature` **等**」的「等」由
  **72 落成第 4 份 `瀏覽檔案櫃.feature`**（它寫著「預設分頁為待決定」，55 之後變假）。
- **`上傳照片.feature` 的 `Then 操作失敗` step 在 202 之後會撞 `status_code >= 400`**——
  **62 §4.7 把 binder 的該 step 一併改掉**（62 §6 有一條加星驗收：「漏了它，
  `上傳照片.feature` 不可能 16 passed」）；規格**原文**那一行仍要等 ★G3 之後由 72 刪。

另外兩點**不是裁決，是名詞對照**，先寫在這裡免得對數字時困惑：

- 契約 §9 的 Phase 53 寫「**五頁** header」，design5 §6.1 寫「每一頁」。
  實際有 `site-header` 的是 `upload`／`pending`／`browse`／`ask`／`camera-desk` **五頁**；
  `camera-phone` 是全螢幕取景畫面，本來就沒有頂欄。**五頁是對的。**
- `GET /folders/{folder_id}` 照片摘要目前是**五鍵**
  （`id`／`thumbnail_url`／`text`／`uploaded_at`／`suggested_category`），
  Phase 61 加成**八鍵**（＋`suggested_entity`／`suggested_task_title`／`suggested_task_due`）。
  design5 §6.2 說的「比照 `suggested_category` 帶出實體／待辦建議」指的就是這件事。

---

## 11. 開工前的最後檢查

```bash
# 1. 環境
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc                  # db、app 都要 Up；db 是 Up (healthy)

# 2. 基準
pytest -q                                     # 405 passed，且沒有 skipped
curl -k -s https://127.0.0.1:8000/health      # 200

# 3. 工作區乾淨（避免把別的東西一起 commit）
git status --short

# 4. 備份（Phase 56 要改正式庫結構，動手前一定要有備份）
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-增量五前.dump
tar -czf ~/PersonalDocAI-data-增量五前.tar.gz data/
#    ⚠ 第二行不能省：data/ 裡是原圖與縮圖，不入版控，全世界只有一份。
#      資料庫還原回來但 data/ 沒了的話，照片列還在、縮圖與大圖全變 404。

# 5. 讀完這三份再動手
#    docs/design/design5.md               ← canonical design，全文
#    docs/plan/unfinish/phase-52-*.md     ← 第一個要做的 phase
#    CLAUDE.md                            ← 專案現況與指令區
```

**開始做吧。一次一個 phase，先寫會紅的測試。**
