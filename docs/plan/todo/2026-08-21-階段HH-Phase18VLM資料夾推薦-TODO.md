# 2026-08-21 階段HH：Phase 18 VLM 資料夾推薦——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-18-VLM資料夾推薦.md`（階段GG 已校準）。核心：把 VLM 的 `category` 從「自由字串」變成「從現有資料夾清單挑一個」——

1. `VLM_PROMPT` 常數 → `build_vlm_prompt(folders)` 函式（清單當變數注入 prompt，含「禁止自創名稱」「不確定就填『未分類』」措辭，保留 v4 語言規則）。
2. 新增純函式 `clamp_category(category, folders)`：去空白＋`casefold()` 大小寫不敏感比對，命中回**清單原文**、沒命中／None 一律回「未分類」——prompt 是「請你這樣做」，clamp 是「你不這樣做也沒用」。
3. `VLMClient` 協定、`OllamaVLM.understand`、`FakeVLM.understand` 三處簽名同步加 `folders` 參數（`FakeVLM` 加 `last_folders` 供測試斷言）。
4. 呼叫端 `photos.py` 先 `list_folders()` 再傳入 `understand()`。
5. **本 phase 不落庫、不改回應**——clamp 接進流程是 Phase 20 的事（現在接會讓上傳規格 7 條 Rule 變紅）。

## 步驟（TDD 先紅再綠）

1. [x] 改寫 `tests/unit/test_vlm_service_unit.py`（6→12 個測試），跑它看**紅**（ImportError: build_vlm_prompt——實得）
2. [x] `vlm_service.py`：刪 `VLM_PROMPT`，加 `UNCATEGORIZED`／`build_vlm_prompt`／`clamp_category`；協定與 `OllamaVLM` 簽名加 `folders` → 單元測試**綠**（12 passed）
3. [x] `tests/fakes.py` 的 `FakeVLM` 簽名同步＋`last_folders`
4. [x] `photos.py` 呼叫端：`folders = photo_repository.list_folders()` → `vlm.understand(..., folders)`
5. [x] `test_upload_design_rules.py` 檔尾追加整合測試 `test_上傳時把現有資料夾清單傳給看圖`
6. [x] 全量回歸 `pytest -q` → **110 passed**（實得）；兩份規格檔 12 條 Rule 全綠（14 passed）
7. [x] 計畫驗收清單逐項核對（grep 全過；commit 步驟依指示延後）
8. [x] 寫階段HH REP（含我親自 review diff＋複跑驗證：零偏差）

執行方式：由 Opus subagent 依計畫實作（計畫內含逐字程式碼），完成後由我親自 review diff＋重跑驗證。**先不 commit**（計畫的 commit 步驟延後）；計畫步驟 8（真模型煙霧，選作）延到階段KK 一併做。
