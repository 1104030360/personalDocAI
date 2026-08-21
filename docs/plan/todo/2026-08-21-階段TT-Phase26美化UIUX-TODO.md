# 2026-08-21 階段TT：Phase 26 美化 UI/UX——TODO

## 實作邏輯

依 `unfinish/phase-26-美化UIUX.md`（階段RR 已校準）。核心：**樣式只有一個家**（新增 `style.css`，三頁刪光頁內 `<style>`、`folder_modal.js` 刪 `FOLDER_MODAL_CSS`）＋**拒絕 AI 樣板臉**（設計決策必須來自真實作品、附來源連結；禁止清單寫進檔頭並以腳本把關）。只動 `app/static/` 五檔；零 Python、零測試變動（pytest 前後皆 149）。

計畫寫死的是**決策程序**：步驟 0 前截圖 → 步驟 1 載 frontend-design skill → 步驟 2 查開源照片庫 UI 歸納 2〜3 個具體參考點 → 步驟 3〜4 禁止清單＋design tokens 決策 → 步驟 5〜7 落檔 → 步驟 8 底線腳本 13 項 → 步驟 9 後截圖＋17 項實操 → 步驟 10 顆數不變。

## 步驟

1. [x] 步驟 0：`/tmp/ui-before/` 六張前截圖（1280×800）
2. [x] 步驟 1：載入 `frontend-design` skill（動檔前）
3. [x] 步驟 2：DeepWiki 查 immich／photoprism → 參考點表（含連結，見 REP）
4. [x] 步驟 3〜4：禁止清單＋tokens 決策（紙白＋牛皮紙＋深琥珀 #7c5200、Avenir Next 標籤感、mono 收據字；簽名＝資料夾索引 tab）
5. [x] 步驟 5：`style.css`＋5c 兩自檢 OK
6. [x] 步驟 6：三頁改版完成
7. [x] 步驟 7：`folder_modal.js` 刪樣式＋三件互動（四核心函式零改動）
8. [x] 步驟 8：底線腳本 13 項全符（③⑦ 註解誤中已查證＋校準計畫）
9. [x] 步驟 9：後截圖六張＋八項對比全「後優於前」＋17 項實操全過＋console 僅預期日誌
10. [x] 步驟 10：`pytest -q` 仍 **149**
11. [x] CLAUDE.md 現況段最終收尾（P15〜26 全數完成＋149）
12. [x] 寫階段TT REP＋總覽 P26 打勾（含 §0.1 全數完成、§6 完成註記）

執行方式：本 phase 為設計判斷重的前端工作，由我親自執行全程。**先不 commit**。
