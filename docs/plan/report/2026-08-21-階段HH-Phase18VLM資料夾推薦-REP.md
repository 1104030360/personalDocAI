# 2026-08-21 階段HH：Phase 18 VLM 資料夾推薦——REP

## 實作邏輯

依 `unfinish/phase-18-VLM資料夾推薦.md`（GG 校準版）。VLM 的 `category` 從「自由發明的字串」改成「從現有資料夾清單挑一個」，兩道防線：

1. **prompt 注入變數**：`VLM_PROMPT` 常數改為 `build_vlm_prompt(folders)`——每次上傳前把 `list_folders()` 的名稱＋說明組進 prompt（「現有資料夾（category 只能從這裡選一個，禁止自創名稱）」「不確定就填『未分類』」），並補一條語言規則例外：category 一律照清單原文、不隨照片語言改變。使用者自建資料夾下次上傳自動出現在 prompt。
2. **clamp 夾回**：純函式 `clamp_category(category, folders)`——去頭尾空白＋`casefold()` 大小寫不敏感比對，命中回**清單裡的原文**（`"  收據 "`→`收據`、`"RECEIPT"`→`Receipt`），沒命中／None 一律回 `UNCATEGORIZED`（「未分類」）。prompt 是「請你這樣做」，clamp 是「你不這樣做也沒用」。

簽名同步三處：`VLMClient` 協定、`OllamaVLM.understand`、`FakeVLM.understand` 都加 `folders: list[dict]`；`FakeVLM` 另記 `last_folders` 供測試斷言「清單真的傳到了」。呼叫端 `photos.py` ② 看圖前先 `list_folders()` 傳入。**本 phase 到此為止**：clamp 不落庫、回應不變、`insert_photo` 仍存 `understanding.category`（接線是 Phase 20）。

## 步驟（TDD 紅→綠，由 Opus subagent 執行、我親自 review）

1. 改寫 `tests/unit/test_vlm_service_unit.py`（6→12 個測試）→ 實跑確認**紅**：`ImportError: cannot import name 'build_vlm_prompt' from 'app.services.vlm_service'`。
2. `vlm_service.py`：刪 `VLM_PROMPT` 常數，加 `UNCATEGORIZED`／`build_vlm_prompt()`／`clamp_category()`；協定與 `OllamaVLM` 簽名加 `folders`、組訊息改用 `build_vlm_prompt(folders)` → 單元測試**綠**（12 passed）。
3. `tests/fakes.py`：`FakeVLM` 簽名同步＋`last_folders`。
4. `photos.py`：`folders = photo_repository.list_folders()` → `vlm.understand(image_bytes, file.content_type, folders)`（兩行相鄰）。
5. `test_upload_design_rules.py` 檔尾追加 `test_上傳時把現有資料夾清單傳給看圖`（斷言六個預設名稱依序傳入、description 非空）。
6. 全量回歸。

## 測試方式與結果

- TDD 紅：`pytest tests/unit/test_vlm_service_unit.py -q` → collection ImportError（符合預期的紅）。
- 綠：單元檔 **12 passed**；全量 `pytest -q` → **110 passed**（基線 103＋7，與計畫預告一致）。
- 規格保綠：`test_upload_feature.py`＋`test_ask_feature.py` → **14 passed**（12 條 Rule；上傳 7 條不受影響——FakeVLM 回的「收據」本在預設清單且本 phase 未改寫入行為）。
- 驗收清單 grep 逐項通過：`VLM_PROMPT` 已移除、`build_vlm_prompt`／`clamp_category` 兩函式在、三處 `understand` 簽名一致（`-A1` 皆見 `folders`）、`photos.py` 讀清單與看圖兩行相鄰、`clamp_category` 未出現在 `photos.py`（未接進流程）、`ChatOllama` 出現處與開工前完全相同（無第二模型）。
- **我親自複跑**：`pytest -q` → `110 passed`；兩規格檔 `14 passed`。diff 逐字對照計畫程式碼區塊——零偏差。

## 遇到的問題與解法

- 無阻斷問題。subagent 回報三點疑慮均屬預期：①工作區的 docs 改動是階段GG 的校準（非它所改）；②`test_upload_design_rules.py` 的 `PNG_BYTES` 仍是假位元組——Phase 19 步驟 5 會統一換真圖（計畫已點名）；③`clamp_category` 暫無產品端呼叫者——Phase 20 接線（計畫明文如此設計）。

## 備註

- 依使用者指示**本輪先不 commit**；計畫驗收清單的 git commit 步驟延後執行。
- 計畫步驟 8（真模型煙霧，選作）延到階段KK 統一做。
