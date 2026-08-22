# 2026-08-21 階段WW：計畫檔校準與增量三拆 phase——REP

## 實作邏輯

dev-prompt `phase0821-3.md` 任務一＝「先依現況更新計畫檔」。開工實查：
① unfinish/ 只剩 `phase-27-待決定區與定案鎖定.md`，其工作已由階段VV 完成（重跑 `pytest -q`＝**152 passed** 實證；
Playwright 十項見 VV REP）但驗收清單未打勾——屬「計畫內容是舊的」。
② `docs/design/design3.md`（增量三，2026-08-21 14:08 拍板）§8 明定「落地分 phase、由後續 unfinish/ 拆」，
而 unfinish/ 尚無任何增量三計畫——這就是「後續」該做的事。
故本階段＝phase-27 收尾註記＋把 design3 拆成 **Phase 28〜37** 十個計畫檔。

## 步驟

1. `pytest -q` 重跑確認基線 152 passed（8.28s）；`uv pip install --dry-run pypdfium2` 確認 PDF 依賴可裝（5.13.0）。
2. 通讀 design3.md 全文＋核心程式碼（vlm_service／photos router／repository／conftest／fakes／
   schemas／config／folder_modal.js／upload.html／browse.html），計畫檔全部引用實際函式簽名。
3. `phase-27`：檔頭補「✅ 已完成（階段VV）」註記＋驗收清單八項打勾（依 VV REP 與本日重跑實證）。
4. 新增 `phase-00-增量三總覽.md`：10 個 phase 的路線圖、依賴順序、端點數演進（9→14）、
   全域鐵律（人確認才落庫／一次看圖／clamp 回清單／安全網先行）、已知限制（建議不持久化等）。
5. 新增 phase-28〜33（本輪實作，含先紅再綠的測試明細）與 phase-34〜37（下輪；
   36 無線鏡頭因 design3 D6「原生相機」與「桌面 Capture」有內部張力，列「實作前需產品負責人釐清」清單，不猜）。

## 關鍵拆解決策（與依據）

- **遷移一次改到位**：entity／photo_entity／task／folder_correction 四表同一支 `db/migrate_design3.sql`
  （正式庫只動一次、備份一次）；程式仍 phase 一次一項。
- **VLM 契約一次擴齊**（P30 同時加實體＋待辦建議三欄）：D8「同一個 VLM 看一次」——prompt 只翻修一次，P32/33 不再動。
- **實體建議＝clamp 回現有實體清單**（design3 §4「建議」定義：清單外不當新名字）；清單空→null，無「未分類」對應物。
- **釘選不重算 embedding**：embedding 定義仍是 design.md 的 text＋四欄位；實體檢索走連結表（P34）。
- **「再建議一個」是獨立文字 LLM 呼叫**（不重看圖），新注入點 `get_entity_suggester` 進 wire_fake_ai 安全網。
- **建議不持久化**（沿 design2 先例）：待決定補完鏈＝抽屜→實體（無①、可現算「再建議」）、無待辦窗；記入總覽已知限制。
- **多頁 PDF 只對第一頁跑彈窗鏈**，其餘頁進待決定——待決定分頁本來就是補完入口，不連跳 N 條鏈。
- **`上傳照片.feature` 將加一條 PDF Rule**（P28）：核准依據＝design3.md D7（產品負責人拍板「接受格式加 PDF」），
  比照 Phase 20 依 design1 改版的先例，檔頭註記核准來源；既有 10 條 Rule 一字不動。

## 測試方式與結果

- 開工基線：`pytest -q` → **152 passed**（本階段只動 docs/，結束時未再跑——程式碼零改動）。
- 計畫自我校對：design3 D5〜D15 逐項對到 phase（D5/D6→36、D7→28、D8→30、D9→31+33、D10→既有、D11→35、
  D12→29/30/31、D13→32/33、D14→34、D15→33）；跨檔簽名一致
  （clamp_entity 回 dict|None、PinEntityRequest 恰一、suggested_task.title/due ↔ CreateTaskRequest.title/due_date）。

## 遇到的問題與解法

- **dev-prompt 指名的計畫檔（phase-27）已完成**：依任務一「依現況更新」的精神處理——現況＝27 完結＋design3 待拆，
  故「更新計畫檔」＝27 收尾註記＋28〜37 新增（本判斷已記錄於 WW TODO 備註）。
- **design3 D6 內部張力**（原生相機 vs 桌面 Capture/切鏡頭/閃光）：不猜、不實作，寫成 phase-36 的釐清清單。

## 備註

- 本輪（本 session）實作範圍＝Phase 28〜33＋總驗收；34〜37 留待下輪 dev-prompt。
- 全程不 commit（產品負責人指示）。
