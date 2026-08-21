# 2026-08-21 階段II：Phase 19 上傳存檔與讀圖端點——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-19-上傳存檔與讀圖端點.md`（階段GG 已校準）。核心：把 Phase 17 的檔案函式接進上傳流程，並開兩個讀圖端點——

1. **順序只能是 INSERT → 寫檔 → UPDATE**：檔名要用 `photo.id`，而 id 是 INSERT 當下才配發的。
2. **失敗全清＋re-raise**：寫檔或補路徑任何一步炸掉 → `remove_if_exists` 刪兩個檔＋`delete_photo` 刪那一列 → `raise` 原樣往外丟（回 500 不吞錯）——「跟沒上傳過一樣」。交易包不住磁碟檔案，所以手動清理反而邏輯一致。
3. `photo_repository` 新增 `update_photo_paths()`／`delete_photo()`（後者僅供失敗清理，不是刪除功能）。
4. 讀圖端點 `GET /photos/{id}/thumbnail`、`/image`：沒這列／路徑 NULL（遷移舊照片）／檔案不在磁碟 → 一律 404；都在 → `FileResponse` ＋ `media_type`。
5. **必做維護**：上傳流程從此真的用 Pillow 開圖 → 五個既有測試檔的「假圖片位元組」逐一換成 `make_png_bytes()`／`make_jpeg_bytes()`／新增的 `make_large_png_bytes()`（隨機雜訊、壓不掉，證明無大小上限）。走失敗路徑（415/422/embedding 失敗）的測試**刻意保留**假位元組——證明那些路徑沒去解碼圖片。
6. 回應 JSON 與 `category` 行為本 phase **完全不動**（Phase 20 才改）。

## 步驟（TDD 先紅再綠）

1. [x] 新增 `tests/integration/test_photo_files.py`（11 個測試，計畫逐字），跑它看**紅**（實得 7 failed, 4 passed）
2. [x] `photo_repository.py` 加 `update_photo_paths`／`delete_photo`（放 `reset_folders_and_photos` 之後、`list_folders` 之前）
3. [x] `photos.py`：import 補 `FileResponse`／`storage_service`；④ INSERT 之後插入 ⑤ 寫檔＋失敗清理段；檔尾加 `_send_photo_file`＋兩個 GET 端點；35 行舊註解改版
4. [x] `pytest tests/integration/test_photo_files.py -v` → **11 passed**（綠）
5. [x] 修既有測試假位元組（五檔五處全改）＋`tests/fakes.py` 加 `make_large_png_bytes`（import os）
6. [x] 全量回歸 `pytest -q` → **121 passed**（實得）；規格 12 條 Rule 全綠（14 passed）
7. [x] 計畫驗收清單逐項核對（全過；端點檢查指令因 FastAPI 0.141 改用 openapi 版——計畫已同步校準；fakes.py 註解措辭微調讓 grep 乾淨）
8. [x] 寫階段II REP（含我親自 review diff＋複跑驗證）

執行方式：Opus subagent 依計畫實作，我親自 review＋重跑驗證。**先不 commit**；計畫步驟 7（真模型瀏覽器實測）延到階段KK。
