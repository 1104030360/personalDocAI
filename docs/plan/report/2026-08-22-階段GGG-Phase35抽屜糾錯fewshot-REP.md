# 階段GGG REP：Phase 35 抽屜糾錯 few-shot（N=5）

> 日期：2026-08-22　狀態：✅ 完成（程式、遷移、自動化測試；真模型煙霧列入階段III）
> 對應 TODO：`2026-08-22-階段GGG-Phase35抽屜糾錯fewshot-TODO.md`；計畫：`phase-35-抽屜糾錯few-shot.md`

## 實作邏輯

把「VLM 建議 A、使用者定案選 B（A≠B）」的最近 5 筆例子注入下一次看圖 prompt。
資料路徑：上傳時把 clamp 後的建議持久化到新欄 `photo.suggested_category`
（建議＝收件箱（未分類）→ 存 NULL＝沒建議，用 `is_inbox` 判斷不用字串比對）；
`PATCH /photos/{id}/folder` 定案成功後比對（casefold 防禦性），②改選／③自建且不同名
才 `record_folder_correction`；①採用（名稱相等）與稍後再說（不打 API）天然不記；
記錄失敗只 `logger.warning`、歸類本體照樣 200。看圖端 `build_vlm_prompt` 收第三參數
corrections（`recent_corrections(limit=5)` 上傳開頭讀一次、PDF 各頁共用；`_excerpt()`
截 60 字＋摺行防止照片描述撐破條列／被讀成指令）；corrections 空清單時 prompt 與改版前
**逐字相同**（黃金檔測試釘住）。待決定分頁畫①：`list_photos_in_folder`／
`GET /folders/{id}` 摘要四鍵→五鍵（+`suggested_category`），browse.html 用它對照
資料夾清單開彈窗帶 `primary`。

## 步驟（TDD）

一次寫 24 顆紅測試（`AttributeError`／`KeyError: suggested_category`／四鍵斷言／
`TypeError` 簽名／無 `last_corrections`——全為功能缺席紅）→ 分層實作轉綠：
遷移與 `PHOTO_COLUMNS` → repository 兩函式 → prompt 第五參數四處同步 → 上傳寫入→
PATCH 記錄 → 摘要五鍵與前端。Review 後 polish 再＋1 顆（`_excerpt` 摺行先紅後綠）。

## 測試方式與結果

- 新檔 `tests/integration/test_folder_correction.py`（16 顆：記錄時機四型＋409/422/500
  路徑＋N=5 截斷＋PDF 共用一次讀取＋待決定讀得到建議）；`test_vlm_service_unit.py` +4
  （注入／不注入逐字相同／截斷／摺行／新的在前順序）；簽名連動 5 檔。
- 全量：基線 252 → **272 passed＋2 skipped**；`OLLAMA_BASE_URL` 指死埠同顆數。端點仍 14。
- **正式庫遷移**：`migrate_design3.sql` 追加冪等 `ADD COLUMN IF NOT EXISTS`，實跑兩次
  （第二次 skipping＝冪等實證）；`\d photo` 僅多一欄、`count(*)` 22→22、既有列全 NULL。
- Review：opus reviewer **APPROVED**（含獨立驗證：舊版 prompt 三種輸入 identical、
  正式庫唯讀健檢、grep SQL 只在 repository）；唯一 Important（`_excerpt` 不摺行）
  ＋3 Minor 由 polish fix 收掉（caplog 斷言／渲染順序斷言／casefold docstring）。
- 實作者另做測試庫 Playwright 實操（port 8011）：有建議①出現、無建議無①、鏈接實體窗、
  console 乾淨；正式庫零觸碰。

## 遇到的問題與解法

- **「摘要恰四鍵」規則衝突**：design1 的四鍵摘要拿不到建議 → 依校準裁決改五鍵
  （P35 明文修訂），`test_folders_endpoint.py`／`test_folder_repository.py` 斷言同步。
- **prompt 相容性風險**：糾錯段落插入位置若動到既有段落會影響真模型行為 →
  黃金檔測試斷言「沒有糾錯時整段不出現、接縫逐字相同」。
- **照片描述回饋進 prompt 的注入面**：reviewer 指出多行 photo_text 會撐破條列、
  更易被讀成獨立指令 → `_excerpt()` 摺行＋截 60 字。

## 遺留（記錄於 ledger，不阻塞）

- `folder_correction` 無清理機制（design3 未要求；只讀最近 5 筆無效能問題）。
- 上傳照片.feature 的 D11 Rule 仍 `#TODO` 無 Example（規格唯讀，補例屬產品負責人）。
- 正式庫既有 22 列建議全 NULL——糾錯效果要新上傳＋實際改選才會開始累積。
- 真模型煙霧＝階段III 統一執行。
