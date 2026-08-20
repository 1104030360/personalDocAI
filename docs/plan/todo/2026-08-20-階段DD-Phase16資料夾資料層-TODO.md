# 2026-08-20 階段DD：Phase 16 資料夾資料層 TODO

## 目標

照 `docs/plan/unfinish/phase-16-資料夾資料層.md`（階段BB 已校準，零修改）以 TDD 在 `photo_repository.py` 補上五個資料夾函式：`list_folders`（LEFT JOIN 算張數）、`get_folder`、`find_folder_by_name`（lower() 大小寫不敏感）、`create_folder`、`list_photos_in_folder`（新的在前、不含 embedding）。純資料層，零對外行為改變，收 **93 passed**（83＋10）。

## 實作邏輯

- **TDD 先紅再綠**：步驟 1 新檔 `tests/integration/test_folder_repository.py` 整份寫完跑到紅（`10 failed`，紅因＝`list_folders` AttributeError）；步驟 2 實作五函式轉綠。
- **鍵名即契約**：list／get 回 `id,name,description,is_inbox,photo_count`；find／create 回前四鍵；照片摘要回 `id,text,uploaded_at,thumbnail_path`——之後 Phase 18〜22 的 Pydantic 模型照抄。
- **空資料夾張數＝0**：`count(p.id)` 不數 NULL（`count(*)` 會錯算成 1）；重名不在 repository 擋（409 是 Phase 21 router 的事，DB UNIQUE 是最後防線）。
- **執行方式**：implementer subagent（Opus）照計畫逐字實作；完成後本人親自 review diff＋重跑驗收。不 git commit。

## 步驟

- [x] DD1. 確認階段CC 已收 83 passed 再開工（基線鏈）
- [x] DD2. 派 implementer：步驟 1（新測試檔 10 測→紅）→ 步驟 2（FOLDER_COLUMNS＋五函式，插在 reset_folders_and_photos 之後、search_by_metadata 之前）→ 步驟 3（`10 passed`、全量 `93 passed`）→ 步驟 4（SQL-只在-repository grep）
- [x] DD3. 本人 review：diff 逐檔核對、驗收清單逐項驗證（不含 commit 項）、鍵名契約與計畫逐字比對
- [x] DD4. 寫階段DD REP、更新 ledger

## 完成定義

`pytest -q`＝**93 passed**；五函式鍵名契約與計畫完全一致；空資料夾 photo_count=0、`project x` 找得到 `Project X`、`create_folder` 後 id=7、照片摘要新的在前；`app/api/`、`app/schemas/`、`app/services/` 零改動；SQL 仍只在 repository；未做任何 git commit。
