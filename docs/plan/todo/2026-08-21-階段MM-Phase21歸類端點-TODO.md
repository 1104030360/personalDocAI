# 2026-08-21 階段MM：Phase 21 歸類端點——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-21-歸類端點.md`（階段LL 已校準）。彈窗按下去之後後端做的事：

1. `PATCH /photos/{id}/folder`，body 兩種擇一：`{"folder_id": N}`（彈窗選項①②同一條路——少一條路少一種出錯）或 `{"name": "...", "description": "..."}`（選項③自建）。
2. `AssignFolderRequest` 用 `@model_validator(mode="after")` 做「恰一」跨欄位驗證（兩個都給／都不給／name 空白 → 422）；name 順手去頭尾空白。
3. **順序鐵律**：404（照片）→ 404／409（資料夾）檢查 → `build_document`（category 用新資料夾名稱，其餘三欄原封不動）→ `embed_document`（唯一會失敗的 AI 步驟）→ 自建這時才 `create_folder` → **一條 UPDATE** 同寫 `folder_id`＋`category`＋`embedding`（RETURNING）。embedding 失敗＝500 且資料庫完全沒動、不留空資料夾——靠「先算後建」的排序達成，不用交易。
4. 為什麼要重算 embedding：上傳當下向量是「未分類」版本，不重算則語意查詢少掉正確類別訊號（design1.md §7.3）。

## 步驟（TDD 先紅再綠）

1. [x] 新增 `tests/integration/test_assign_folder.py`（8 顆），跑它看**紅**（8 failed，路徑不存在→404）
2. [x] `schemas/photo.py`：`AssignFolderRequest`（model_validator 恰一）＋`AssignFolderResponse`；驗證器單獨檢查腳本輸出全對
3. [x] `photo_repository.py`：`update_photo_folder()`（一條 UPDATE 三欄＋RETURNING，沿用 `PHOTO_COLUMNS`）
4. [x] `photos.py`：PATCH 端點（重用 `_folder_out`）→ **8 passed**（綠）
5. [x] 全量回歸 `pytest -q` → **132 passed**（實得）；ask 規格 7 passed
6. [x] 驗收清單逐項全過（手動確認腳本：500／500＋四 True；我裁定補列 PATCH 於模組 docstring）
7. [x] 寫階段MM REP（含我親自 review diff＋複跑驗證：零偏差）

執行方式：Opus subagent 依計畫實作，我親自 review diff＋複跑驗證。**先不 commit**。
