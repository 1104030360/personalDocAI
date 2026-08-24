# Phase 35：抽屜糾錯 few-shot（design3.md D11，N=5）——下輪校準後實作

> 🎯 不是第二個模型、不是微調（§1.2 已否決）：只是把「建議被你改掉」的例子注入下一次看圖 prompt。仍要人按確認。

**目標：** 記住最近 5 次「VLM 建議 A、使用者選了 B（A≠B）」的糾錯例子，
上傳看圖時把它們當 few-shot 注入 prompt（表 `folder_correction` P29 已建好）。

## 已釐清

- **誰知道「建議是什麼」**（2026-08-22 產品負責人選 **B**）：
  上傳當下把 VLM／clamp 後的建議寫進 `photo.suggested_category`（新欄位，可空）。
  `PATCH` 定案時用「照片上存的建議」對「你這次選的資料夾」；不必靠 PATCH body 帶 `suggested_name`。
  待決定分頁可拿出同一筆建議當選項①，不必再 call 一次看圖。
  舊照片／clamp 成「未分類」＝沒建議 → 欄位 NULL，不記糾錯。
  否決 A（只靠前端臨時帶名，待決定學不到）與「待決定再看一次圖」。
- **「改掉」的定義**（2026-08-22 產品負責人選 **D**）：
  算糾錯＝②改選現有、③自建，且選定名稱 ≠ 存下來的建議。
  不算＝①採用建議、稍後再說。
  不算＝`suggested_category` 為空或「未分類」（clamp 失敗＝沒建議，不是猜錯）。
  上傳彈窗與待決定分頁用同一套規則。

## 待釐清

無。可以進入實作（尚未開工）。

## 拆解（實作時逐條先紅再綠）

1. repository：`record_folder_correction(suggested, chosen, photo_text)`＋`recent_corrections(limit=5)`（新的在前）。
2. 上傳寫入 `suggested_category`；PATCH 定案成功且該欄有值且≠選定名稱 → 記一筆（寫在 update 之後，失敗不影響歸類本體）。
3. `build_vlm_prompt(folders, entities, corrections)`：有糾錯例子時加一段
   「最近的人工糾正（參考這些修正你的判斷）：『{photo_text 節錄}』你猜 {suggested}、正確是 {chosen}」×最多 5 條。
4. 前端：待決定分頁改為可顯示選項①（資料來自照片上存的建議）；上傳彈窗不必多帶 `suggested_name`。
5. 測試：記錄時機（②③記、①不記、無建議不記、embedding 失敗不記）＋prompt 注入＋N=5 截斷（第 6 筆擠掉最舊）＋待決定能讀到同一筆建議。

## 2026-08-22 對現況校準（實作前補充；基線＝218 tests／14 端點／HEAD 0cabb45）

1. **`suggested_category` 是新欄位＝要遷移**（計畫原文漏了遷移路徑）：
   - `db/schema.sql` 的 photo 表加 `suggested_category text`（可空；註明語意）。
   - `db/migrate_design3.sql` 加一段冪等的
     `ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_category text;`
     （沿用「一份增量三遷移檔、可重跑」慣例），**正式庫要執行**（跑兩次證冪等；
     既有列該欄＝NULL＝「沒建議、不記糾錯」語意，正好正確）。
   - `photo_repository.PHOTO_COLUMNS` 加該欄（fetch_photo／PATCH 的 RETURNING 都拿得到；
     `row_to_document` 不讀多的鍵，檢索層零影響）。
2. **上傳寫入**：`insert_photo` 多收 `suggested_category: str | None`；photos router 在
   clamp 之後決定值——`clamp_category` 結果＝「未分類」→ 存 **NULL**（沒建議），
   其餘存清單原文。彈窗①採用建議走 PATCH 時名稱相等 → 依規則自動不記，不用特判。
3. **VLM 介面第三參數（四處同步）**：`build_vlm_prompt(folders, entities, corrections)`；
   `VLMClient.understand(image_bytes, content_type, folders, entities, corrections)`——
   `OllamaVLM`／`tests/fakes.py` 的 `FakeVLM`（記 `last_corrections` 供驗注入）／
   photos router（上傳一開始 `recent_corrections(limit=5)` 讀一次，**PDF 各頁共用同一份**）。
   prompt 段落：有糾錯才加，格式照拆解 3；`corrections` 空清單＝prompt 與現況逐字相同
   （既有 prompt 測試不得變紅）。
4. **PATCH 記糾錯的位置與容錯**：寫在 `update_photo_folder` 成功**之後**；
   條件＝photo 列的 `suggested_category` 非 NULL 且 `casefold()` 後 ≠ 選定名稱；
   `record_folder_correction` 失敗只 log warning、**不影響歸類回應**（try/except）。
   已定案 409／目標收件箱 422／embedding 失敗 500 等既有路徑一律**不記**（它們根本
   走不到 update 之後）。
5. **待決定分頁畫①的資料路徑**：`list_photos_in_folder` 與 `GET /folders/{id}` 的照片摘要
   由四鍵改**五鍵**（+`suggested_category`；design1「恰四鍵」由本 phase 明文修訂，
   既有斷言四鍵的測試同步改）。前端 `browse.html` 待決定 tab：照片有 `suggested_category`
   時，從已載入的資料夾清單找同名 folder → `openFolderModal` 帶 `primary`（畫①）；
   NULL 照舊無①。上傳彈窗（upload.html）零改動。
6. **repository 兩函式**：`record_folder_correction(suggested, chosen, photo_text)`＋
   `recent_corrections(limit=5)`（`ORDER BY id DESC LIMIT n`，新的在前；回
   `suggested/chosen/photo_text` 三鍵）。N=5 不另設 config——design3 §7 暫定值，寫在
   呼叫端常數即可。
7. **測試檔落點**：`tests/integration/test_folder_correction.py`（記錄時機四型＋
   recent 截斷）＋`tests/unit/test_vlm_service_unit.py` 加 prompt 注入案例；
   五鍵摘要改動落在既有 `test_folders_endpoint.py`。

## 驗收清單

- [x] 全量全綠、零 Ollama；建議已持久化（摘要五鍵、待決定畫①）；PATCH 契約零新增欄位
- [x] 糾錯只在真糾錯時記（②③且不同名；①／稍後再說／無建議／409／422／500 皆不記）；
      prompt 最多 5 條、新的優先（兩層測試釘住）
- [x] 正式庫遷移已執行且冪等（跑兩次、22 列零變動）；corrections 空時 prompt 逐字相同
      （黃金檔測試）；真模型端到端煙霧閉環（2026-08-22，詳階段GGG REP）
