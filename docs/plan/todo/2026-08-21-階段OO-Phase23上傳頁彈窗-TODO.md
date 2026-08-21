# 2026-08-21 階段OO：Phase 23 上傳頁彈窗——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-23-上傳頁彈窗.md`（階段LL 已校準）。只改 `app/static/upload.html` 一個檔：201 之後開 modal 三選項（採用 AI 建議／改選現有／自建新的），關掉（×／Esc）＝留在「未分類」。零框架、零打包、零新增端點、**零新增自動化測試**（沿 Phase 14 原則，驗收＝瀏覽器實操）。

關鍵設計（計畫已逐字給定 HTML/JS 全文）：

- **禁用 `alert`／`confirm`／`prompt`**：原生對話框會卡頁面、卡瀏覽器自動化；錯誤一律寫進彈窗內的 `<p id="fm-error">`（409 重名／422 空名／連線失敗都顯示在頁內）。
- 彈窗程式碼刻意寫成「只靠 `onAssigned`／`onClosed` 兩個 callback 對外溝通」的共用形狀＋`fm` 前綴隔離全域——Phase 24 會整段搬進 `folder_modal.js`，屆時一行都不用改。
- 選項①②都送 `{"folder_id": N}`（同一條路）；③送 `{"name","description"}`；PATCH 失敗彈窗不關、紅字顯示，可繼續操作。

## 步驟

1. [x] 依計畫整檔替換 `app/static/upload.html`（逐字照抄；由我直接落地）
2. [x] grep 驗收：無 alert/confirm/prompt、無 CDN/框架、git status 僅此一檔（static 範圍）
3. [x] `pytest -q` 仍 **140 passed**（零測試增減）
4. [x] 瀏覽器實操 13 項全過（用使用者常駐的 :8000 dev server＋真 gemma4；三選項各走一次、409/422 頁內紅字、×/Esc 留未分類、正式庫九列軌跡一一對應）
5. [x] 寫階段OO REP＋總覽 P23 打勾

執行方式：檔案由我親自照抄＋review；瀏覽器驗收用 Playwright MCP（專案 CLAUDE.md 指定）。**先不 commit**。
