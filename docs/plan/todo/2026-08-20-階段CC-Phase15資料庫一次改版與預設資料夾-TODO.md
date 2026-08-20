# 2026-08-20 階段CC：Phase 15 資料庫一次改版與預設資料夾 TODO

## 目標

照 `docs/plan/unfinish/phase-15-資料庫一次改版與預設資料夾.md`（階段BB 已校準，零修改）以 TDD 完成：`folder` 表＋六筆預設種子＋單一收件箱保證、`photo` 加四欄（`folder_id` NOT NULL FK＋三個路徑欄）、`insert_photo` 依 category 自動歸夾（**category 值不動**）、conftest 換 `reset_tables` 每測重播種子、正式庫以可重跑的 `db/migrate_folders.sql` 遷移（先 `pg_dump` 備份）。對外行為零改變：79 個既有測試全綠，收 **83 passed**。

## 實作邏輯

- **TDD 先紅再綠**：步驟 1 先加 4 個新測試跑到紅（`4 failed, 10 passed`，紅因＝`DEFAULT_FOLDERS` AttributeError＋`folder_id` KeyError）；步驟 2〜3 改 schema 重建測試庫（此時大面積紅是預期）；步驟 4〜5 改 repository 與 conftest 轉綠。
- **兩庫兩條路**：測試庫 `schema.sql` 砍掉重建（DROP 順序先 photo 再 folder）；正式庫 2 列真照片不可失，走 idempotent 遷移腳本，動手前必先 `pg_dump` 備份。
- **不碰對外行為**：`category` 值原樣寫入（歸夾靠 SQL 內 `COALESCE`＋兩個子查詢當場算 `folder_id`）；`UploadResponse`／Document 組裝皆逐鍵取值，多出的鍵不外漏（階段BB 已證明）。
- **執行方式**：implementer subagent（Opus）照計畫逐字實作並回報紅／綠證據；完成後由本人親自 review 完整 diff、重跑驗收清單。**不 git commit**（使用者指示，計畫驗收清單的 commit 項跳過）。

## 步驟

- [x] CC1. 派 implementer：計畫步驟 1（4 新測試→紅）→ 步驟 2（schema.sql 最終版）→ 步驟 3（重建測試庫＋核對種子）→ 步驟 4（repository：DEFAULT_FOLDERS／insert_photo 歸夾／reset_folders_and_photos）→ 步驟 5（conftest reset_tables）→ 步驟 6（`14 passed`、全量 `83 passed`）
- [x] CC2. implementer 續作：步驟 7（migrate_folders.sql）→ 步驟 8（pg_dump 備份 → 正式庫遷移 → 核對 2 列歸「收據」三路徑 NULL → 重跑證 idempotent → 第二收件箱被擋）
- [x] CC3. 本人 review：完整 diff 逐檔核對（schema／migrate／repository／conftest／測試檔）、驗收清單 12 項逐項驗證（不含 commit 項）、SQL-只在-repository grep
- [x] CC4. 寫階段CC REP、更新 ledger

## 完成定義

`pytest -q`＝**83 passed**（79 既有全綠＋新 4）；正式庫 2 列 `folder_id=2`（收據）、三路徑欄 NULL、遷移腳本連跑兩次無錯、第二收件箱被 `folder_one_inbox` 擋下；SQL 仍只在 `photo_repository.py`；未做任何 git commit。
