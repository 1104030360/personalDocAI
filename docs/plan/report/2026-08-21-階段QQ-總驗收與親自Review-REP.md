# 2026-08-21 階段QQ：總驗收與親自 Review（P21〜P24 收尾）——REP

## 實作邏輯

第二輪（dev-prompt `phase0821-1.md`）四個 phase 全部完成：P21／22 後端由 Opus subagent 依（LL 校準後的）計畫 TDD 實作、P23／24 前端由我依計畫逐字落地；每階段完成當下已各自 review＋驗證。本階段做整輪最終把關。

## 親自 Review 結論

- **後端**：P21 的 schemas／repository／endpoint 與 P22 的三個新檔已於各階段逐段對照計畫（零偏差）；本階段補終審兩個新測試檔全文（`test_assign_folder.py` 8 顆、`test_folders_endpoint.py` 8 顆）——與計畫逐字一致。
- **前端**：四個 static 檔由我親自落地＋Playwright 實操共 32 項驗收（13＋19）全過；彈窗程式碼全站唯一一份（grep 實證）。
- **裁定與例外**：見下「遇到的問題」。

## 最終新鮮驗證

| 項目 | 結果 |
|---|---|
| `pytest -q` | **140 passed**（124→132→140→140→140，各段與計畫預告一致） |
| 兩份規格檔 | **17 passed**（15 條 Rule；`自然語言詢問.feature` 全程零 diff） |
| SQL 位置 | 精確 pattern（`UPDATE photo`）：只在 `photo_repository.py`。泛用 pattern 另命中 `photos.py:225`——那是 P21 計畫指定的**中文註解**「⑥ 一條 UPDATE 同時寫…」，非 SQL（P21 計畫的驗收 grep 本就用精確 pattern 避開；P25 的「明確不做」腳本應沿用精確版） |
| 端點清單 | 恰 **9** 條：`GET /`、`POST /ask`、`GET /folders`、`GET /folders/{id}`、`GET /health`、`POST /photos`、`PATCH /photos/{id}/folder`、`GET /photos/{id}/image`、`/thumbnail` |
| 彈窗單一份 | `FOLDER_MODAL_HTML` 僅 folder_modal.js 2 處；HTML 零殘留 |
| 靜態頁 | 無 alert/confirm/prompt、無 CDN／框架、無 npm |

## 文件收尾

- `CLAUDE.md`：現況改「Phase 18〜24 已完成（2026-08-21），Phase 25〜26 待做」＋新增 P21〜24 成果段（歸類端點順序鐵律、瀏覽端點 thumbnail_url 換算、三頁＋唯一彈窗檔、Playwright 32 項）＋測試顆數 124→**140**；規格驅動段進度改 P15〜24。
- 總覽 §0.1 狀態行改「P18〜24 已完成；P25 起待做」；§5 的 P21〜24 四列已打勾（132／140／不變／不變，皆實測相符）。

## 遇到的問題與解法（本輪裁定彙整）

1. **`curl -I` 對 `GET /` 回 405**：FastAPI `@app.get` 不自動支援 HEAD；瀏覽器走 GET（307 正確）。→ P24 計畫的檢查指令已校準為 GET 版並註記。
2. **泛用 SQL grep 誤中 photos.py 的中文註解**（「一條 UPDATE 同時寫」為 P21 計畫指定原文）→ 不改註解；以 P21 計畫自帶的精確 pattern 為準，REP 註記供 P25 沿用。
3. **P21 模組 docstring 未列 PATCH**（subagent 守「不順便改」而未動）→ 我裁定補一行，保持檔案門面誠實。
4. **P23 驗收項目 8 沿用項目 7 的既開彈窗驗 ×**（行為覆蓋相同，省一次 60 秒真模型上傳）→ 已於 OO REP 記錄。
5. Playwright 檔案上傳限專案根目錄 → 經 `.playwright-mcp/` 中轉，驗收後整目錄清除。
6. favicon.ico 404 為 Phase 14 以來既有噪音（瀏覽器自動請求）→ 不加 favicon（計畫外）；正常流程 console 零錯誤。

## 測試結果總結

**140 passed 全綠**；正式庫終態 10 列照片＋8 個資料夾（六預設＋專案X＋旅遊），照片 7 的「收據→飲食→旅遊」軌跡即三選項實測紀錄；design1.md §0 三缺口（看得見／分得開／還能再問）全部補完。

## 未完成／延後（依使用者指示）

- **git commit 未執行**（「先不 commit」）。建議拆法：①`feat: Phase 18〜20`（vlm_service／photos router 上傳段／schemas photo 四欄位／上傳規格改版＋對應測試）②`feat: Phase 21〜22`（PATCH 歸類＋folders 端點＋16 tests）③`feat: Phase 23〜24`（三個 static 頁＋folder_modal.js）④`docs:` 計畫校準＋TODO/REP＋CLAUDE.md＋phase-18〜24 歸檔 `finish/`。各 phase 計畫的驗收清單內含 commit 訊息模板（P20 累計 124、P21 累計 132、P22 累計 140）。
- phase-18〜24 計畫檔歸檔 `finish/` 與 commit 一起做（避免未 commit 的 rename 干擾檢視）。
- 增量僅剩 **P25（錯誤收尾與全量回歸）**、**P26（美化 UI/UX）**。
