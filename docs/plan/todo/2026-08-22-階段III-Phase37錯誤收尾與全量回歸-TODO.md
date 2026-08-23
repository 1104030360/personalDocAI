# 階段III TODO：Phase 37 增量三錯誤收尾與全量回歸＋總 review

> 日期：2026-08-22　狀態：✅ 完成（見同名 REP；P36 真機驗收與若干裁決移交產品負責人）
> 依據：`docs/plan/unfinish/phase-37-增量三錯誤收尾與全量回歸.md`（含 2026-08-22 校準段）

## 實作邏輯

鏡射 Phase 13／25 的收尾模式：把 design3 各 phase 的錯誤路徑整理成一張表，逐列標
「已測 ✓（指出測試檔）／缺口 ★（補測試釘死）」；補測試首選**不改產品碼**（首跑就綠＝
行為早已正確、只是沒被釘住；首跑紅＝真 bug，修好並記錄）。「明確不做」清單掃碼核對；
`/openapi.json` 清點端點＝17；正式庫健檢；CLAUDE.md 現況段更新（含修正「31〜33 未
commit」過時敘述）。歸檔 unfinish/→finish/ 依計畫原文「隨 commit」——本輪不 commit，
留待產品負責人 commit 時執行。

## 步驟

- [x] 錯誤表逐列核對（檔案實文 16 列、22 子情境：12 已有既有測試把關、10 缺口）→
      缺口補 17 顆（新檔 `tests/integration/test_design3_error_paths.py`）
- [x] 「明確不做」掃碼 12 項全過（openapi 無 DELETE／端點恰 17／SQL 只在 repository
      三項為自動化測試）
- [x] 全量 `pytest -q`＝341 passed＋2 skipped＝`OLLAMA_BASE_URL` 指死埠同顆數
- [x] `/openapi.json` 端點數＝17；DELETE=0
- [x] 正式庫健檢：六表存在＋photo.suggested_category 欄＋孤兒連結全 0＋收件箱唯一
- [x] CLAUDE.md 現況段更新（含修正「31〜33 未 commit」過時敘述）；總覽 §2 打勾＋完成註記
- [x] 主線親自 review 全部 diff（產品碼逐檔＋前端紀律抽查＋規格 mtime 實證＋conftest）；
      階段III REP 已寫
- [x] 🛑 停下：Phase 36 真機驗收清單交產品負責人（見最終回報；歸檔隨 commit）
      ＊補充：錯誤表首跑 16 綠 1 紅＝揪出「自創實體＋釘選非原子」真缺陷，
      已以 `create_and_pin_entity()` 單一交易修復（計畫表實為 16 列，「17」為 dispatch 誤數）

## 執行方式

錯誤表補測試以 opus subagent 執行；掃碼／健檢／CLAUDE.md／總 review 由主線親自做。
