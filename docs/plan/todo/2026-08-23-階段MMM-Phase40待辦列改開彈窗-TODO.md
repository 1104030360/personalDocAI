# 階段MMM TODO：Phase 40 待辦列改開彈窗（階段甲完結）

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP；計畫 §4.5 瀏覽器實操已由主 agent 統一驗收完成）
> 依據：`docs/plan/unfinish/phase-40-待辦列改開彈窗.md`（逐條照做）＋`docs/design/design4.md` §4.1 第 2 列、§4.2 第 1 點、§4.3、D1、§1.1 第 2 列、§1.2 第 2 列、§9 第 4 列
> 開工基準（已實測）：`pytest -q` ＝ 365 passed ＋ 2 skipped；Phase 39 已完成（`photo_detail_modal.js` 存在、`.pd-task` 樣式已寫好）

> **後續最終狀態：** 上述 365＋2 是歷史 phase-local 基準。目前 full suite 為
> **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。最終 pass-8 共 25 張 JPEG
> （11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`）；`final_visual_qa_k`、
> `final_visual_qa_l` 均 **PASS／HIGH confidence／25 of 25／zero blockers**。
> 共用詳情窗的 focus trap／背景 `inert`／Tab 與 Shift+Tab／focus restore、stale generation、
> 遺失圖片／raw error／長 CJK 均已 RED→GREEN。G1 B／C／D／E 仍保留空白。
> 狀態為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

## 實作邏輯

階段甲最後一步：把「待辦」分頁從**第二個入口**接上 Phase 39 那顆窗——同一顆，不另做一顆。

現在點一列會 `target="_blank"` 開新分頁，畫面上只有一張裸圖：沒有 AI 寫的說明、
沒有四個欄位，而且人被丟到另一個分頁、要按上一頁才回得來。
產品負責人 grill 時明確要求「不新開 window，圖在窗裡」（design4 §1.1 第 2 列正式推翻
design3.md §7 的「能點回來源圖即可」）。

三件事，順序不能顛倒：

1. **先改 CSS**。`a.task-row` 是**元素限定**選擇器（`<a>` 而且 class 是 task-row 才套用）。
   標籤換成 `<button>` 之後這條就不生效，待辦列會瞬間變成一排系統原生按鈕。
   先把 `a` 去掉、補上 `<button>` 需要的四項重設，重新整理確認畫面沒事，再動 HTML。
   ⚠ `color: var(--c-text);` 一定要留著——`<button>` 不繼承文字顏色（預設是 `buttontext`），
   刪掉待辦標題會從深墨色變成純黑，就違反「長相與改之前一模一樣」那條驗收。
2. **窗裡補畫待辦那一行**，而且**畫在 `fetch` 之前**。標題與到期日是清單（`TaskOut`）
   本來就有的資料，不必等 API——使用者按下去的當下就看得到標題，圖與說明再慢慢補上。
   順手讓 `#pd-title` 依入口切「待辦來源照片」／「照片」，兩個入口一眼分得出來。
3. **每一列各掛一個監聽**（不用縮圖牆那種事件委派）。待辦列表短，而且每列要帶三個欄位
   （photo_id／title／due_date）；用委派就得塞進 `dataset` 再讀出來，全部會變成字串、
   `null` 會變成 `"null"`，反而更容易出錯。直接用閉包抓住 `task` 物件最單純。

**不必新增任何端點**：窗要的 `title` 與 `due_date`，`GET /tasks` 的 `TaskOut` 本來就有。

## 步驟

- [x] 寫 TODO。開工前確認基準是 365 passed ＋ 2 skipped、Phase 39 已完成。
- [x] **先改** `app/static/style.css`：`a.task-row` → `.task-row`、`a.task-row:hover` → `.task-row:hover`
      （原第 596／608 行，Phase 39 加了 pd- 區塊之後往後位移），
      並在 `.task-row` 補四項 `<button>` 重設：`width: 100%`（button 預設寬度是內容寬）、
      `font: inherit`（button 不繼承頁面字型）、`text-align: left`（button 預設置中）、
      `cursor: pointer`（button 預設是箭頭）。其餘一字不動，`color: var(--c-text)` 留著。
- [x] `app/static/photo_detail_modal.js`：`openPhotoDetailModal()` 開頭「清乾淨」那一段，
      把 `pdEl("pd-task").hidden = true;` 換成依 `config.task` 決定的畫法
      （標題 `textContent`；到期日用三元判斷，沒有就寫「無到期日」，不能印出 `null`），
      並加一行 `pdEl("pd-title").textContent = 待辦 ? "待辦來源照片" : "照片";`。
      位置在 `fetch` **之前**。
- [x] `app/static/browse.html` 的 `showTasks()`：
      ① 提示文字改成「點一列可以看這件待辦的來源照片與完整說明。」；
      ② 原第 219〜224 行整組換掉——`el("a", "task-row")` → `el("button", "task-row")` ＋
      `row.type = "button"`，兩行 design3 §7 舊註解與 `row.href`／`row.target`／`row.rel`
      三行**整組刪除**（不留沒人走的舊路）；縮圖／task-title／task-due 三段一字不動；
      在 `const item = document.createElement("li");` 之前加每列的 `click` 監聽；
      ③ 函式上方第 201 行的段落註解出處改成 design4.md D1。
- [x] 自我驗收（計畫 §6 可掃碼的部分）：`browse.html` 搜不到 `_blank`／`row.href`／`row.rel`；
      `style.css` 搜不到 `a.task-row` 且 `.task-row` 裡仍有 `color: var(--c-text)`。
- [x] `pytest -q` 仍是 **365 passed ＋ 2 skipped**（純前端，顆數不變）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在窗裡編輯待辦標題／到期日 | design4 §1.2 第 2 列已否決；本輪只看 |
| 在窗裡刪待辦、打勾完成 | 全系統沒有刪除端點；待辦也沒有完成狀態（design3 §7 MVP） |
| 新增「待辦詳情」端點、讓 `GET /tasks` 多回欄位或改排序 | 標題與到期日清單裡本來就有；design4 §3「不做」 |
| 為待辦另做一顆不一樣的窗 | design4 §1.2 第 6 列已否決：共用一顆，待辦只多一行 |
| 動 `POST /photos/{id}/task` 那條路 | 與本 phase 無關 |
| 在 `browse.html` 再加一次 `photo_detail_modal.js` 的 script 標籤 | Phase 39 已經掛過了 |
| 動待決定分頁、資料夾牆、三關彈窗鏈 | 本 phase 只碰待辦分頁 |
| 為本 phase 新增自動化測試 | 本專案前端慣例；`pytest -q` 顆數維持 365 ＋ 2 |
| 動任何 `app/` 的 Python 檔、既有測試、`docs/spec/` | 純前端 phase；規格本輪不改 |
| 建任何 Docker 檔 | 階段丙的東西，G1 閘門沒過不准建（design4 §0） |
| 起伺服器做計畫 §4.5 的 9 項瀏覽器實操 | 埠 8000 有使用者留著的 uvicorn，不動、不自起；主 agent 之後統一驗收 |
| `git add`／`git commit` | 本增量全程不 commit |

## 執行方式

以 subagent 實作（**先 CSS 後 HTML** 的順序是計畫 §7 陷阱 1 明文要求），
主 agent 事後 review ＋ 瀏覽器統一驗收。本 phase 驗收以「程式碼掃描 ＋ pytest 顆數不變」為準。
