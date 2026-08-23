# 階段GGG TODO：Phase 35 抽屜糾錯 few-shot（N=5）

> 日期：2026-08-22　狀態：✅ 完成（見同名 REP；真模型煙霧列入階段III）
> 依據：`docs/plan/unfinish/phase-35-抽屜糾錯few-shot.md`（含已釐清 B／D 與 2026-08-22 校準段）＋design3.md D11

## 實作邏輯

不是第二個模型、不是微調：把最近 5 次「VLM 建議 A、使用者定案選了 B（A≠B）」的例子
注入下一次看圖 prompt 當 few-shot。關鍵資料路徑＝**上傳當下把 clamp 後的建議持久化**到
新欄位 `photo.suggested_category`（clamp 成「未分類」＝沒建議＝存 NULL）；PATCH 定案成功後
拿「照片上存的建議」對「這次選定的名稱」（casefold 不分大小寫），②改選／③自建且不同名
才記一筆 `folder_correction`；①採用與稍後再說天然不記（名稱相等或根本沒 PATCH）。
記錄失敗只 log 不影響歸類本體。待決定分頁靠同一筆持久化建議畫出選項①
（摘要四鍵→五鍵），不必再看一次圖。

## 步驟（TDD：每條先紅再綠）

- [x] 遷移：schema.sql 加欄＋migrate_design3.sql 冪等 ALTER＋**正式庫執行（跑兩次證冪等）**
- [x] `PHOTO_COLUMNS` 加 suggested_category；`insert_photo` 多收參數（未分類→NULL）
- [x] repository：`record_folder_correction`＋`recent_corrections(limit=5)`（新的在前）
- [x] `build_vlm_prompt(folders, entities, corrections)`＋`understand()` 第五參數
      （protocol／OllamaVLM／FakeVLM／photos router 四處同步；PDF 各頁共用；
      corrections 空＝prompt 與現況逐字相同——黃金檔測試釘住）
- [x] 上傳寫入建議；PATCH 定案後依規則記糾錯（update 之後、try/except log＋caplog 測試）
- [x] `GET /folders/{id}` 摘要 4→5 鍵；`browse.html` 待決定 tab 有建議時開彈窗帶①
- [x] 測試：記錄時機＋prompt 注入＋N=5 截斷＋待決定讀得到建議；
      新檔 `tests/integration/test_folder_correction.py`（16 顆）＋單元 +4
- [x] 全量 pytest 全綠＋零 Ollama 同顆數（272 passed＋2 skipped 雙跑同顆）

## 執行方式

以 opus subagent 實作（TDD），主線（我）事後跑 task review＋最終親自 review。
