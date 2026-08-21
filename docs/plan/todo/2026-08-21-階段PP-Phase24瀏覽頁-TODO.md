# 2026-08-21 階段PP：Phase 24 瀏覽頁——TODO

## 實作邏輯

依 `docs/plan/unfinish/phase-24-瀏覽頁.md`（階段LL 已校準）。design1.md §0 三缺口的最後一塊——「我上傳過什麼」有地方看：

1. **`browse.html` 兩個畫面靠網址切**：`?folder=N` 有無決定畫「資料夾卡片清單」或「縮圖牆」——普通 `<a>` 連結整頁重載，上一頁／重新整理／書籤免費就有，零狀態管理。
2. **縮圖牆**：`<img src="/photos/{id}/thumbnail">`；`thumbnail_url` 為 null（舊資料）畫灰底「無縮圖」占位；點一張（event delegation 整面牆一個監聽器）開同一套彈窗，①的字改「維持」（`primaryVerb`）；PATCH 成功 `location.reload()`。
3. **彈窗搬家（不留兩份）**：Phase 23 的整段彈窗程式碼原封不動剪進 `app/static/folder_modal.js`（僅補兩句計畫指定的註解），兩頁 `<script src>` 引用；`upload.html` 內嵌版刪除。
4. 三頁導覽列互連（upload／browse／ask 各三連結）；`GET /` 轉址不動；**一行 Python 都不改**。
5. 安全寫法：動態內容一律 `document.createElement`＋`textContent`（AI 產生的文字不進 innerHTML）。

## 步驟

1. [x] 新增 `app/static/folder_modal.js`（＝P23 彈窗段＋兩句註解）
2. [x] `upload.html`：刪內嵌彈窗段→`<script src="/ui/folder_modal.js"></script>`；nav 補「瀏覽資料夾」
3. [x] `ask.html`：nav 補「瀏覽資料夾」（唯一改動）
4. [x] 新增 `app/static/browse.html`（計畫逐字）
5. [x] 靜態檢查全過（`/` 轉址檢查校準為 GET 版——FastAPI @app.get 不支援 HEAD）
6. [x] `pytest -q` 仍 **140 passed**
7. [x] Playwright MCP 實操 19 項全過（照片 7 旅程：收據→飲食→旅遊；上傳頁共用檔回歸 OK；console 僅預期日誌）
8. [x] 寫階段PP REP＋總覽 P24 打勾

執行方式：檔案由我親自照抄＋review；瀏覽器驗收 Playwright MCP。**先不 commit**。
