# Phase 42：看圖與轉向量的計時接線（階段乙第 2 步）

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 實作與真模型自驗已完成。**
> 下方 `373 → 379` 是本 phase 當時的歷史基線，不回改；
> 目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，
> 全量為 **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> 串行真模型證據全部 `ok=true`：最新本機 PNG 重跑為 `vlm gemma4:e2b 33.1s`／
> `embed bge-m3 2.4s`；
> 兩頁 PDF 為第 1 頁 `vlm 29.2s`／`embed 0.1s`、第 2 頁 `vlm 26.1s`／`embed 0.1s`；
> 歸檔只有 `embed 0.1s`；雲端 PNG 為 `vlm gemma4 7.1s`／本機 `embed 0.4s`。
> 最新 hardening 讓真實 VLM／embedding client 把 request 已選定的 immutable target 傳給計時器，
> 並把看圖 note 限為數量與布林摘要，不記 AI 產生內容；helper／假件無 target 時才走 config fallback。
> 狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 把 Phase 41 做好的 `log_ai()` 接到**上傳這條路**上——
> 看圖（`kind=vlm`）與轉向量（`kind=embed`）各打一組開始／結束，
> 而且把現在寫死在 router 裡的「AI 看圖開始／完成（N.N 秒）」**改走新格式、不留兩套**。

**涵蓋範圍比想像的大：** 單圖上傳、PDF 的每一頁、無線鏡頭拍的照片，
三條路**全部**走同一個函式 `photos._ingest_image()`，所以在那裡包一次就三條都有了。
歸類（`PATCH /photos/{id}/folder`）重算向量是另一個地方，要各別包一次。

---

## 1. 對應 design4.md 章節

- **§5.1**（`vlm`／`embed` 兩列：何時、backend、model）
- **§5.2**（倒數第二段：PDF 三頁＝三組 `vlm` ＋三組 `embed`，某頁 422 跳過＝那頁 `vlm` 的 `ok=false`、該頁不打 `embed`；
  以及格式那幾條 bullet 的最後一條：既有「AI 看圖開始／完成」**改走這套，不要舊新兩套並行**）
- **§5.3**（包的呼叫點前兩個：`photos._ingest_image`、`photos.assign_folder`）
- **§5.4 第 2、7 列**（改 `app/api/routers/photos.py`；新建 `tests/integration/test_ai_timing_log.py`）
- **D7**（每一張圖／每一頁各打一組；失敗也打結束、標 `ok=false`）
- **§9 錯誤表第 5 列**（AI 呼叫失敗：既有 422／500 語意**不變**，只是多一行 `ok=false`）

---

## 2. 前置條件

- **Phase 41 已完成且全綠**（`app/services/ai_timing.py` 存在，`with ai_timing.log_ai("vlm"):` 可用）。
- 建議先把階段甲（38〜40）收完，這樣一次只會有一件事在動。
- **開工基準顆數：`pytest -q` ＝ 373 passed ＋ 2 skipped**
  （＝ 增量四開工的 358 ＋ Phase 38 的 7 顆 ＋ Phase 41 的 8 顆；
  Phase 39／40 是純前端、依本專案慣例零新增自動化測試）。
  若你**還沒**做階段甲就先做乙，把本檔的全量數字各減 7（373→366、379→372）；
  本 phase 新增的 6 顆與其他驗收條件都不受影響。

---

## 3. 範圍

### 做

- `app/api/routers/photos.py`：
  - `_ingest_image()` 的看圖那一段改用 `with log_ai("vlm")`，並把既有三行 `logger.info` 收掉；
  - `_ingest_image()` 的 `embed_document(...)` 包上 `with log_ai("embed")`；
  - `assign_folder()` 的 `embed_document(...)` 包上 `with log_ai("embed")`；
  - 移除已經沒人用的 `import time`。
- 新建 `tests/integration/test_ai_timing_log.py`（Phase 43 會在同一個檔案續寫詢問那半邊）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 舊的「AI 看圖開始／完成（N.N 秒）」留著並行 | design4 §5.2 明文：「**不要舊新兩套並行**」。兩種格式會讓 grep 出來的結果自相矛盾 |
| 改任何 HTTP 狀態碼或錯誤訊息 | §9 第 5 列：語意**不變**。看不懂還是 422、存檔失敗還是 500 |
| 為 PDF 打一筆「整份總時間」 | design4 §1.2 明文否決：產品負責人要每頁各一組，才看得出哪一頁慢 |
| 為 PDF 渲染（`pdf_service.render_pages`）、存原圖、產縮圖、寫 SQL 計時 | §5.1 明文：不是模型推論，不計時 |
| 把計時包進 `indexing_service.embed_document()` 裡面 | §5.3 指定包在**呼叫點**。包在 `embed_document` 裡看起來更省事，但那會讓「哪一次上傳、哪一頁」的上下文消失；而且詢問那條路的向量是 `retrieval_service` 直接呼叫 `embeddings.embed_query`（Phase 43 另外包），根本不經過它 |
| 把計時包進 `vlm_service.OllamaVLM` 裡面 | 同上。而且那樣 pytest 的 `FakeVLM` 就不會打 log，測試看不到東西（design4 §5.3：「pytest 的 Fake 也會打 log」） |
| 動 `app/api/routers/camera.py` | 它是**轉呼叫** `photos._ingest_image()`，包在那裡就自動涵蓋了。這個檔一個字都不用改 |

---

## 4. 實作步驟（先寫測試再實作）

### 4.1 先看懂現在長什麼樣（不寫程式，只讀）

- [ ] 打開 `app/api/routers/photos.py`，找到 `_ingest_image()` 的第 146〜170 行
      （從註解 ② 開頭到最後那個 `logger.info(...)` 的收尾括號，**這一整段等一下會被換掉**）：

```python
    # ② 看圖（把現有資料夾、實體清單與最近的糾錯例子注入 prompt——
    #    design1.md §8、design3.md D12、D11）
    #    仍然只有這一次看圖呼叫，沒有第二個分類模型：實體與待辦是同一次輸出多出來的欄位。
    #    起訖各記一筆 log：真模型一張圖要看數分鐘，終端機沒有動靜時分不出
    #    「還在算」與「卡死」，這兩行就是給人盯進度用的。
    logger.info("AI 看圖開始：%s，%d bytes", content_type, len(image_bytes))
    看圖起點 = time.monotonic()
    understanding = vlm.understand(
        image_bytes, content_type, folders, entities, corrections
    )
    看圖秒數 = time.monotonic() - 看圖起點
    if not understanding.understood or not understanding.text.strip():
        logger.info("AI 看圖完成（%.1f 秒）：看不懂 → 422 不儲存", 看圖秒數)
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )
    logger.info(
        "AI 看圖完成（%.1f 秒）：text %d 字、建議類別「%s」、建議實體「%s」、待辦「%s」",
        看圖秒數,
        len(understanding.text),
        understanding.category,
        understanding.entity,
        understanding.task_title,
    )
```

- [ ] 記住三件事：
  1. 這裡已經有 `time.monotonic()` 計時了——本 phase 是把它**換成共用的那一套**，不是加第二套。
  2. 看不懂時是 `raise HTTPException(422)`，`vlm.understand()` 本身**不會丟例外**
     （`OllamaVLM` 與雲端的 `OllamaCloudVLM` 內部都已經把失敗吃掉、回 `understood=False`，
     見 `app/services/vlm_service.py` 的兩處 `return PhotoUnderstanding(understood=False)`）。
     所以 `kind=vlm` 的 `ok=false` 實務上只會由「看不懂 → 422」這條路產生。
  3. 舊 log 帶了 `content_type` 與 bytes 數——新格式沒有這兩樣。可以接受：
     設計文件指定的必要欄位是那五個，摘要留給「字數／建議類別」（design4 §5.2）。

- [ ] 找到第 199 行（`_ingest_image` 裡）與第 432 行（`assign_folder` 裡）兩處：

```python
    embedding = indexing_service.embed_document(embeddings, document)
```

  這兩行就是「轉向量」——`embed_document` 內部呼叫 `embeddings.embed_query()`，真的會打到 Ollama。

### 4.2 決定「看不懂」算不算 `ok=false`（這是本 phase 唯一需要判斷的設計點）

**算。** 依據是 design4 §5.2 倒數第二段的原文：

> PDF 三頁＝三組 `vlm` ＋三組 `embed`（**某一頁 422 跳過＝那頁 `vlm` 的 `ok=false`**，該頁不打 `embed`）。

所以做法是：把 `raise HTTPException(422)` **放進 `with` 區塊裡面**。
`log_ai` 看到區塊丟例外就會打 `ok=false`，然後原封不動把例外往外丟——
422 的語意一個字都沒變（`_ingest_pdf` 照樣接得住、照樣記進 `skipped_pages`）。

```text
       with log_ai("vlm") as 計時:   ← 一進來就打「AI 開始 …」
   ┌──     understanding = vlm.understand(...)   ← 真的打模型
   │       if 看不懂:
   │           計時.note = "看不懂 → 422 不儲存"
   │           raise HTTPException(422) ────────────────┐
   │       計時.note = "text 42 字、建議類別「收據」…"  │
   └──  （with 區塊到這裡結束）                         │ 例外原封不動穿過 with
                                                        ▼
                      log_ai 打結束行：有例外 → ok=false，沒例外 → ok=true；
                      然後把 HTTPException 繼續往外丟（422 語意一個字沒變）
```

左邊那條 `┌ │ └` 標的是 **`with` 區塊的範圍**：兩個 `計時.note = …`（看不懂那條、
看得懂那條）都在區塊**裡面**，寫到區塊外面就太晚了——結束行早就印出去了。

> 本檔的圖為了排版寫成 `log_ai(...)`，**實際程式碼一律是 `ai_timing.log_ai(...)`**——
> `app/services/` 底下的東西本專案一律「import 模組、用 `模組.函式`」
> （`photos.py` 第 24 行就是這樣引 `indexing_service` 等四個），見 §4.4 的 import 步驟。

### 4.3 先寫測試（此時應該是紅的）

- [ ] 新建 `tests/integration/test_ai_timing_log.py`。共通做法：
  - 檔頭要 import 的東西（下面的片段都會用到）：

    ```python
    import logging

    from app.core import config
    from app.dependencies import get_vlm
    from app.main import app
    from app.services.vlm_service import PhotoUnderstanding
    from tests.fakes import FakeVLM, make_pdf_bytes, make_png_bytes
    ```

    覆寫的 `app.dependency_overrides` 不必自己收拾——`conftest.py` 的 `wire_fake_ai`
    每顆測試結束都會 `clear()`（既有測試檔全都靠這條安全網）。
  - 每顆測試第一行 `caplog.set_level(logging.INFO)`（helper 打的是 INFO；不設就撈不到）。
    本專案已有用 `caplog` 的先例可對照：`tests/integration/test_folder_correction.py` 第 244 行
    的 `with caplog.at_level(logging.WARNING):`——兩種寫法都可以，`set_level` 是「整顆測試都有效」。
  - 寫兩個小工具把 log 撈出來。**注意開始行與結束行都含 `kind=vlm `，只用 kind 過濾會撈到兩種**，
    所以要連開頭一起比對：

    ```python
    def 開始行(caplog, kind: str) -> list[str]:
        return [m for m in caplog.messages if m.startswith(f"AI 開始 kind={kind} ")]

    def 結束行(caplog, kind: str) -> list[str]:
        return [m for m in caplog.messages if m.startswith(f"AI 結束 kind={kind} ")]
    ```

  - 需要「看得懂」的 VLM 時，在測試（或 fixture）裡覆寫注入點：

    ```python
    收據理解 = PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    )
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    ```

    （既有寫法見 `tests/integration/test_pdf_upload.py` 第 20 行的 `收據理解`
    與 `tests/integration/test_assign_folder.py` 第 22 行的 `超市照片`——
    **不要**用 `tests/fakes.py` 的 `understanding_for_text()`：它只認得
    `KNOWN_UNDERSTANDINGS` 裡登記過的規格原句，傳別的字串會直接 `KeyError`。）
  - 「預期上傳成功」的測試一律用真圖／真 PDF（`make_png_bytes()`、`make_pdf_bytes(pages=2)`），
    這是 Phase 19 起的專案慣例；只有「看不懂 → 422」那顆可以沿用假位元組
    （那條路根本不會解碼圖片）。上傳的呼叫寫法照既有測試：

    ```python
    client.post("/photos", files={"file": ("a.png", make_png_bytes(), "image/png")})
    client.post("/photos", files={"file": ("scan.pdf", make_pdf_bytes(pages=2), "application/pdf")})
    ```

    （見 `tests/integration/test_assign_folder.py` 第 40 行、
    `tests/integration/test_pdf_upload.py` 第 62 行的 `上傳PDF`。）
  - 需要「一頁看得懂、一頁看不懂」時，**照 `tests/integration/test_pdf_upload.py` 第 30 行的
    `分頁VLM` 寫法在本檔自己定義一份**（跨測試檔 import 會把兩份測試綁在一起，不划算）。
  - **同一顆測試裡做了兩件事時，中間要 `caplog.clear()`**：`caplog` 是整顆測試累積的，
    「先上傳再 PATCH」不清掉的話，`kind=embed` 會撈到 2 組（上傳 1 組＋歸類 1 組）。

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 1 | `test_上傳一張圖各打一組看圖與轉向量的log` | `POST /photos` 成功後：`kind=vlm` 的開始／結束各 1 行、`kind=embed` 的開始／結束各 1 行；兩個結束行都是 `ok=true` |
| 2 | `test_看不懂的照片看圖log標ok為false且不打embed` | 用預設的 `FakeVLM()`（看不懂）上傳 → 422；`kind=vlm` 結束行含 `ok=false`；**完全沒有** `kind=embed` 的行（看不懂就沒走到轉向量） |
| 3 | `test_PDF兩頁各打兩組` | 上傳 `make_pdf_bytes(pages=2)` → `kind=vlm` 的開始行 2 條、`kind=embed` 的開始行 2 條（D7：每頁各一組） |
| 4 | `test_PDF跳過的那一頁不打embed` | `分頁VLM(看得懂的頁碼={1})` 上傳兩頁 → `kind=vlm` 結束行 2 條（一條 `ok=true`、一條 `ok=false`）、`kind=embed` 只有 **1** 條 |
| 5 | `test_歸類重算向量會打embed的log` | 上傳一張 → **`caplog.clear()`** → `PATCH /photos/{id}/folder`（歸到「收據」，`{"folder_id": 2}`）→ 出現 `kind=embed` 的開始／結束各 1 行、`ok=true`，而且**沒有** `kind=vlm`（歸類不重看一次圖） |
| 6 | `test_切到雲端時看圖是cloud而轉向量仍是local` | `monkeypatch.setattr(config, "AI_BACKEND", "cloud")` 後上傳 → `kind=vlm` 那兩行是 `backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}`；`kind=embed` 那兩行仍是 `backend=local model={config.EMBEDDING_MODEL}` |

> **測試 6 的注意**：`wire_fake_ai` 會把 `get_vlm` 覆寫成 `FakeVLM`，所以撥到雲端**並不會**真的
> 打雲端（安全網仍在）。這顆測的是「log 的 backend／model 欄位有跟著開關走」，不是真的連雲端。

- [ ] 跑一次確認**真的是紅的**：

```bash
pytest tests/integration/test_ai_timing_log.py -v
```

  預期：六顆全紅（撈不到任何 `kind=` 的行）。

### 4.4 改 `_ingest_image()` 的看圖那一段

- [ ] 把 4.1 抄下來那一整段換成：

```python
    # ② 看圖（把現有資料夾、實體清單與最近的糾錯例子注入 prompt——
    #    design1.md §8、design3.md D12、D11）
    #    仍然只有這一次看圖呼叫，沒有第二個分類模型。
    #    計時 log 走全站共用的 ai_timing（design4.md §5）：真模型一張圖要看數分鐘，
    #    終端機沒有動靜時分不出「還在算」與「卡死」，這兩行就是給人盯進度用的。
    #    「看不懂 → 422」刻意寫在 with 區塊**裡面**：那一頁對這次呼叫來說就是失敗，
    #    結束行要標 ok=false（design4.md §5.2 的 PDF 規則）。例外原封不動往外丟，
    #    422 的語意一個字都沒變。
    with ai_timing.log_ai("vlm") as 計時:
        understanding = vlm.understand(
            image_bytes, content_type, folders, entities, corrections
        )
        if not understanding.understood or not understanding.text.strip():
            計時.note = "看不懂 → 422 不儲存"
            raise HTTPException(
                status_code=422,
                detail="VLM 無法理解照片內容，未儲存任何資料",
            )
        計時.note = (
            f"text {len(understanding.text)} 字、"
            f"建議類別「{understanding.category}」、"
            f"建議實體「{understanding.entity}」、"
            f"待辦「{understanding.task_title}」"
        )
```

- [ ] `from app.services import indexing_service, pdf_service, storage_service, vlm_service`
      那一行把 `ai_timing` 加進去（維持字母序 → `ai_timing, indexing_service, pdf_service, …`）。
- [ ] 檔案最上面（第 4 行）把 `import time` **刪掉**。刪之前先確認沒有別的地方在用它：

```bash
grep -n "time\.monotonic\|time\.time(" app/api/routers/photos.py
```

  預期：**沒有輸出**。（不要直接 grep `time\.`——`content_time.isoformat()` 也會中，
  那是 `date` 物件的方法，跟 `time` 模組無關。）

### 4.5 包住兩處轉向量

- [ ] `_ingest_image()` 第 199 行附近：

```python
    with ai_timing.log_ai("embed"):
        embedding = indexing_service.embed_document(embeddings, document)
```

- [ ] `assign_folder()` 第 432 行附近（那段註解 ④ 已經寫明「唯一會呼叫 AI、可能失敗的一步」，
      正好對應這裡要包的東西）：

```python
    with ai_timing.log_ai("embed"):
        embedding = indexing_service.embed_document(embeddings, document)
```

  這裡若失敗，`log_ai` 打 `ok=false` 之後例外照樣往外丟 → 仍然是 500、資料庫仍然完全沒動
  （既有的「排序不靠交易」設計一個字都沒變）。

### 4.6 跑綠

```bash
pytest tests/integration/test_ai_timing_log.py -v     # 預期 6 passed
pytest -q                                             # 預期 379 passed ＋ 2 skipped
OLLAMA_BASE_URL=http://localhost:9 pytest -q          # 顆數相同
```

- [ ] **特別確認這幾顆既有測試沒有變紅**（它們守的是「語意不變」）：

```bash
pytest tests/integration/test_pdf_upload.py tests/integration/test_error_paths.py \
       tests/integration/test_photo_files.py tests/integration/test_assign_folder.py -v
```

### 4.7 終端機實地看一眼（design4 §6「終端機（乙，G1 用）」的第 1、2、4 條）

> §6 的第 3 條（「問一句語意題：`route`／`embed`／`answer`」）要等 Phase 43 才有東西可看。
> 下面第四條「歸類只有一組 `embed`」是本 phase 自己補的，設計文件沒列，但它是
> §5.3「`photos.assign_folder`：歸類重算 embedding」那一行的直接證據。

- [x] 起真的伺服器（真 Ollama）：

```bash
uvicorn app.main:app --reload --port 8000
```

- [x] 用瀏覽器 `http://localhost:8000/ui/upload.html` 上傳一張真照片，終端機應該看到：

```text
INFO:     AI 開始 kind=vlm backend=local model=gemma4:e2b
INFO:     AI 結束 kind=vlm backend=local model=gemma4:e2b elapsed_s=143.7 ok=true text 42 字、建議類別「收據」、建議實體「None」、待辦「繳電費」
INFO:     AI 開始 kind=embed backend=local model=bge-m3
INFO:     AI 結束 kind=embed backend=local model=bge-m3 elapsed_s=0.4 ok=true
INFO:     照片已入庫：photo_id=23（先進「未分類」，等使用者歸類）
```

  ⚠️ **模型名一律以你 `.env` 裡的實際設定為準，看圖與文字用的不是同一顆。**
  目前 `.env` 是 `VLM_MODEL=gemma4:e2b`（看圖）、`LLM_MODEL=gemma4:e2b-mlx`（路由／回答／實體建議）、
  `EMBEDDING_MODEL=bge-m3`（向量）——所以本 phase 的 `kind=vlm` 印的是 **`gemma4:e2b`**（沒有 `-mlx`），
  帶 MLX 標籤的那顆要到 Phase 43 的 `route`／`answer` 才會出現。
  （CLAUDE.md 現況段那句「本機自 2026-08-22 改用 MLX 標籤 `gemma4:e2b-mlx`」講的是文字模型，
  對看圖模型並不精確；以 `.env` 為準。）

- [x] 把頁首開關撥到「雲端」再上傳一張，`kind=vlm` 那兩行的 `backend` 應該變成 `cloud`、
      `model` 變成 `.env` 裡的 `OLLAMA_CLOUD_VLM_MODEL`（＝`gemma4`），
      而 `kind=embed` 那兩行**仍然是 `backend=local model=bge-m3`**。
- [x] 上傳一份兩頁 PDF，應該看到 **兩組 `vlm` ＋ 兩組 `embed`**（不是一組總時間）。
- [x] 在瀏覽頁的待決定分頁把一張照片歸檔，應該看到**一組 `embed`**（歸類重算），沒有 `vlm`。

---

## 5. ASCII 圖：一次上傳會打幾組 log

```text
  三個入口，同一個函式（… ＝ 配對用的 token，例：POST /camera/abc123/photos）
  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
  │ 桌面上傳 JPEG/PNG  │  │ 桌面上傳 PDF       │  │ 無線鏡頭快門       │
  │ POST /photos       │  │ POST /photos       │  │ POST /camera/…     │
  └─────────┬──────────┘  └─────────┬──────────┘  └─────────┬──────────┘
            │                       │ 逐頁渲染成 PNG        │ 轉呼叫
            │                       ▼                       │
            │            ┌──────────────────────┐           │
            └───────────►│ photos._ingest_image │◄──────────┘
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
     with log_ai("vlm")                          with log_ai("embed")
     ├ AI 開始 kind=vlm …                        ├ AI 開始 kind=embed …
     │   vlm.understand(...)                     │   embed_document(...)
     └ AI 結束 kind=vlm … ok=true/false          └ AI 結束 kind=embed … ok=true


  PDF 兩頁、第 2 頁看不懂：

     第 1 頁  AI 開始 kind=vlm …
              AI 結束 kind=vlm … ok=true  text 12 字…
              AI 開始 kind=embed …
              AI 結束 kind=embed … ok=true
     第 2 頁  AI 開始 kind=vlm …
              AI 結束 kind=vlm … ok=false 看不懂 → 422 不儲存
              （沒有 embed —— 根本沒走到轉向量那一步）
     結果     201 {"pages": 2, "created": [1 筆], "skipped_pages": [2]}   ← 語意一字未變


  歸類（PATCH /photos/{id}/folder）：

     AI 開始 kind=embed …
     AI 結束 kind=embed … ok=true          ← 只有轉向量，沒有看圖（不重看一次圖）
```

---

## 6. 驗收清單

- [ ] 六顆新測試**先紅後綠**
- [ ] `pytest -q` ＝ **379 passed ＋ 2 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] `grep -rn "AI 看圖開始\|AI 看圖完成" app/` **搜不到任何結果**（舊格式已完全移除，沒有兩套並行）。
      注意要用 `-rn`（`-n` 不會進資料夾），而且**不要**只搜「AI 看圖」——
      `app/main.py` 的註解、`vlm_service.py` 的檔頭說明、`camera.py` 第 291 行的
      「（AI 看圖見下一行）」、兩個 HTML 的等待字樣都含這三個字，**它們都不是舊 log、不用動**
- [ ] `grep -n "^import time" app/api/routers/photos.py` 搜不到（已刪）
- [ ] 既有錯誤路徑測試全綠：`test_pdf_upload.py`、`test_error_paths.py`、
      `test_photo_files.py`、`test_assign_folder.py`、`test_folder_error_paths.py`、
      `test_design3_error_paths.py`
- [x] §4.7 的終端機四條實地看過（本機／雲端／PDF／歸類）
- [ ] 只動到兩個檔。查法要分兩條指令，因為新建的檔案**還沒 `git add`**（本增量全程不 commit），
      `git diff` 看不到未追蹤的檔案（phase-43 §6 有同一則提醒）：

```bash
git diff --stat -- app tests    # 恰好一個檔：app/api/routers/photos.py
git status --short -- app tests # 另有 ?? tests/integration/test_ai_timing_log.py（本 phase 新建）
                                #      ?? app/services/ai_timing.py（Phase 41 新建，本 phase 不改它）
```

---

## 7. 常見陷阱

1. **把 422 的 `raise` 放到 `with` 外面**：那樣看不懂會變成 `ok=true`，
   PDF 跳過的那一頁在 log 上看起來像成功。**一定要在區塊裡面 raise。**

2. **`計時.note` 設在 `raise` 之後**：那行永遠不會執行。看不懂那條路要先設 note 再 raise。

3. **忘了刪舊的三行 `logger.info`**：留著就變成一次上傳打五行、兩種格式，
   grep `AI 結束` 會撈到不完整的資料。design4 §5.2 明文禁止。

4. **`import time` 沒刪**：不會壞，但 lint 會抱怨，而且下一個人會以為還有別的地方在計時。

5. **把 `with` 包太大**：例如把整個 `_ingest_image` 包進 `log_ai("vlm")`，
   那樣存檔失敗也會被算進「看圖時間」，而且 `kind=vlm` 的 `ok=false` 會變成「存檔壞了」的意思。
   **只包真的打模型的那幾行。**

6. **在 `_ingest_pdf` 裡另外包一層**：不要。每頁的 log 是 `_ingest_image` 打的，
   在外面再包一層就變成「整份總時間」，那是 design4 §1.2 已否決的方案。

7. **改到 `camera.py`**：不用改。它第 297 行就是呼叫 `photos._ingest_image(...)`，
   自動繼承這次的計時。它第 291 行那句「（AI 看圖見下一行）」改版後**仍然成立**——
   下一行變成 `AI 開始 kind=vlm …`，還是看圖那一行。

8. **測試斷言 `elapsed_s` 的值**：假件跑得極快，秒數是 `0.0`。斷言「有這個欄位」就好，
   不要斷言數字（design4 §5.3 明文）。

9. **一顆測試裡做兩件事卻忘了 `caplog.clear()`**：`caplog` 是整顆測試累積的。
   測試 5「上傳完再 PATCH」如果沒清，`kind=embed` 會撈到 2 組（上傳 1 組＋歸類 1 組），
   斷言「各 1 行」就會紅——而且紅得像是產品程式碼壞了，很浪費時間。
