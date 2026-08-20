# 2026-08-20 階段EE：Phase 17 檔案儲存服務 TODO

## 目標

照 `docs/plan/unfinish/phase-17-檔案儲存服務.md`（階段BB 已校準，零修改）以 TDD 做出 `app/services/storage_service.py`：原圖原封不動落地 `data/photos/{id}.jpg|png`、Pillow 縮圖長邊 ≤512（等比、不放大）落地 `data/thumbs/`、DB 只存 `data/` 開頭相對路徑（`absolute_path` 負責換算 `config.DATA_DIR`）、`remove_if_exists` 容錯清理；同時建立 conftest `isolated_data_dir` 安全網（pytest 永不寫進專案 data/）與 `tests/fakes.py` 真圖工具。純服務層，不改上傳流程、不加端點，收 **103 passed**（93＋10）。

## 實作邏輯

- **TDD 先紅再綠**：步驟 1〜5 是準備（裝 Pillow、.gitignore 加 data/、config.DATA_DIR、conftest 安全網、fakes 真圖工具）；步驟 6 先寫 `tests/unit/test_storage_service_unit.py` 跑到紅（collection error：模組不存在）；步驟 7 實作轉綠。
- **三道既有安全網精神的延伸**：`isolated_data_dir` 與 `wire_fake_ai`（不打真 Ollama）、`reset_tables`（不清正式庫）同款——危險預設由 conftest 統一擋掉。
- **假位元組陷阱**：Pillow 會真的解碼，`b"\x89PNG fake"` 會炸 `UnidentifiedImageError`——測試一律用 `make_png_bytes()`／`make_jpeg_bytes()` 現產真圖（既有測試檔不動，那是 Phase 19 的事）。
- **執行方式**：implementer subagent（Opus）照計畫逐字實作（含步驟 10 手動確認正式路徑後 `rm -rf data` 清殘留）；完成後本人親自 review diff＋重跑驗收，並以 Context7 覆核 Pillow `Image.thumbnail` 語意（只縮不放、就地修改）。不 git commit。

## 步驟

- [x] EE1. 確認階段DD 已收 93 passed 再開工（基線鏈）
- [x] EE2. 派 implementer：步驟 1（requirements＋uv 裝 Pillow）→ 2（.gitignore data/＋驗證 git 看不見）→ 3（config.DATA_DIR）→ 4（conftest isolated_data_dir）→ 5（fakes 真圖工具）→ 6（單元測試 10 測→紅）→ 7（storage_service 實作）→ 8（`10 passed`）→ 9（全量 `103 passed`）→ 10（手動確認正式路徑＋清殘留）
- [x] EE3. 本人 review：diff 逐檔核對、驗收清單逐項驗證（不含 commit 項；含 `from app.core.config import` 禁令 grep、端點數不變 grep）、Context7 覆核 Pillow 行為
- [x] EE4. 寫階段EE REP、更新 ledger

## 完成定義

`pytest -q`＝**103 passed**；縮圖 1200×600→512×256、100×50 不放大、原圖位元組原樣；`absolute_path` 換算正確且測試期間 DATA_DIR 指向 tmp_path；`data/` 被 git 忽略且專案內無殘留；SQL 仍只在 repository、端點數不變；未做任何 git commit。
