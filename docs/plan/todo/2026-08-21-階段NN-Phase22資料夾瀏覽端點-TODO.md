# 2026-08-21 階段NN：Phase 22 資料夾瀏覽端點——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-22-資料夾瀏覽端點.md`（階段LL 已校準）。把 Phase 16 的三個 repository 函式包成兩個**唯讀、零 AI** 端點，餵 Phase 24 的瀏覽頁：

1. `GET /folders` → 直接回陣列（不包物件）：id/name/description/is_inbox/photo_count，照 id 排序；空資料夾靠 LEFT JOIN 仍出現（張數 0）。
2. `GET /folders/{id}` → `{folder, photos}`；photos 摘要恰四鍵（id/thumbnail_url/text/uploaded_at）、新的在前；**`thumbnail_url` 是端點算出來的網址**（`/photos/{id}/thumbnail`），不是硬碟路徑——舊資料路徑 NULL → 回 `null` 讓前端畫占位（design1.md §10）。找不到資料夾 404。
3. 新檔 `schemas/folder.py`（三模型）＋`api/routers/folders.py`（零 SQL）＋`main.py` 掛 router（唯二 Python 改動）。
4. 明確不做：列出全部照片端點、分頁、改名／刪除（design1.md §7.4、§3、不過度設計）。

## 步驟（TDD 先紅再綠）

1. [x] 新增 `tests/integration/test_folders_endpoint.py`（8 顆），跑它看**紅**（8 failed，/folders 不存在→404）
2. [x] 新增 `app/schemas/folder.py`：`FolderWithCount`／`PhotoSummary`／`FolderDetailResponse`
3. [x] 新增 `app/api/routers/folders.py`：兩個 GET（零 SQL）
4. [x] `main.py`：import 補 `folders`＋`include_router(folders.router)` → **8 passed**（綠）
5. [x] 全量回歸 `pytest -q` → **140 passed**（實得）
6. [x] 驗收 grep 全過（router 零 SQL、SQL 只在 repository、@router 7＋@app 2、openapi 端點恰 9 條）
7. [x] 寫階段NN REP（含我親自 review 三新檔＋複跑驗證：零偏差）

執行方式：Opus subagent 依計畫實作，我親自 review diff＋複跑驗證。**先不 commit**；計畫步驟 6（真伺服器 curl）併入前端 phase 驗收。
