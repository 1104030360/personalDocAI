# 2026-08-21 階段JJ：Phase 20 上傳未分類流程與規格改版——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-20-上傳未分類流程與規格改版.md`（階段GG 已校準）。本增量最關鍵的 phase：把 Phase 15〜19 做好的零件一次接起來，上傳語意變成——**VLM 仍然自動分類，但不再默默定案**（design1.md §2）。

| | 舊行為 | 新行為 |
|---|---|---|
| DB 的 `category` | VLM 說什麼存什麼 | 一律先存「未分類」（`folder_id` 掛收件箱） |
| VLM 給的類別 | 直接落庫 | 經 `clamp_category` 夾回清單 → 只當回應的 `suggested_folder`，不落庫 |
| embedding | 用 VLM category 合併 | 用「未分類」合併（歸類後 Phase 21 PATCH 重算） |
| 201 回應 | id／text／metadata | ＋`folder`／`suggested_folder`／`folders`／`thumbnail_url` 四塊（彈窗一次拿齊） |

**規格檔正式改版**（產品負責人 2026-08-20 核准解除 `上傳照片.feature` 唯讀）：7→10 條 Rule 一次改到位；三條紅線——只改這一檔（`自然語言詢問.feature` 一字不動）、不留新舊混雜、沒被推翻的 Rule 原文不動。BDD 驗收測試 `test_upload_feature.py` 跟著規格檔改版。

## 步驟（BDD/TDD 先紅再綠）

1. [x] 步驟 0 前置確認（六樣零件都在；基線 121 實查）
2. [x] `上傳照片.feature` 整檔換新版（10 Rule／10 Example；檔頭註明 2026-08-20 改版來源）
3. [x] `test_upload_feature.py` 整檔換新版 → 實跑**紅**（5 failed, 5 passed；KeyError 'folder' 與 assert '收據'=='未分類'，恰為計畫預告）
4. [x] `schemas/photo.py`：插入 `FolderOut`；`UploadResponse` 補四欄位
5. [x] `photos.py`：`_folder_out()`；三處★改動（P19 寫檔段原樣保留）→ 規格測試**綠**（10 passed）
6. [x] 逐檔收拾：(a) bilingual 整檔換版 (b) design_rules 向量測試改「未分類」＋兩行斷言 (c)(d) photos_upload／error_paths 零改動實跑確認（7／11 passed）
7. [x] 全量回歸 `pytest -q` → **124 passed**（實得）；ask 7 passed；`自然語言詢問.feature` 零 diff
8. [x] 計畫驗收清單逐項核對（含「不含原始照片檔」grep 的計畫自我矛盾——已裁定改為排除註解行掃描並校準計畫；手動回應長相腳本實跑通過）
9. [x] 寫階段JJ REP（含我親自 review diff＋複跑驗證）

執行方式：Opus subagent 依計畫實作，我親自 review＋重跑驗證。**先不 commit**。
