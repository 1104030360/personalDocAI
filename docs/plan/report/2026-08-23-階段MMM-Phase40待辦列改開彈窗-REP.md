# 階段MMM REP：Phase 40 待辦列改開彈窗（階段甲完結）

> 日期：2026-08-23　狀態：✅ 程式碼與主 agent 最終瀏覽器自查完成；**G1 仍待產品負責人親自確認**
> 對應 TODO：`2026-08-23-階段MMM-Phase40待辦列改開彈窗-TODO.md`
> 計畫：`docs/plan/unfinish/phase-40-待辦列改開彈窗.md`；design：`design4.md` §4.1 第 2 列、§4.2 第 1 點、§4.3、D1、§1.1 第 2 列、§9 第 4 列
> 開工基準（實測）：365 passed ＋ 2 skipped → 收工：**365 passed ＋ 2 skipped**（純前端，顆數不變）

## 實作邏輯

階段甲最後一步：把「待辦」分頁接成 Phase 39 那顆窗的**第二個入口**——同一顆窗，不另做一顆
（design4 §1.2 第 6 列已否決「各做一顆不一樣的窗」）。

改之前點一列是 `target="_blank"` 開新分頁、畫面上只有一張裸圖：沒有 AI 寫的說明、
沒有四個欄位，而且人被丟到另一個分頁、要按上一頁才回得來。
design4 §1.1 第 2 列正式推翻 design3.md §7 的「能點回來源圖即可」。

三件事照計畫的順序做，一步都沒跳：

1. **先改 CSS**（計畫 §7 陷阱 1）。`a.task-row` 是元素限定選擇器，標籤換成 `<button>`
   之後整條不生效，待辦列會瞬間變成一排系統原生按鈕。先把 `a` 去掉、補上 `<button>`
   才需要的四項重設（`width: 100%`／`font: inherit`／`text-align: left`／`cursor: pointer`），
   `color: var(--c-text)` 留著——`<button>` 不繼承文字顏色（預設 `buttontext`），
   刪掉待辦標題會從深墨色變成純黑。
2. **窗裡補畫待辦那一行，畫在 `fetch` 之前**。標題與到期日是 `GET /tasks` 的 `TaskOut`
   本來就帶回來的資料，不必等 API——使用者按下去的當下就看得到標題，圖與說明再慢慢補上。
   順手讓 `#pd-title` 依入口切「待辦來源照片」／「照片」（每次開窗都寫，
   所以待辦 → 資料夾牆換著點也不會殘留上一次的標題）。
3. **每一列各掛一個監聽**，不用縮圖牆那種事件委派。待辦列表短，而且每列要帶三個欄位；
   用委派得塞進 `dataset` 再讀出來，全部會變字串、`null` 會變 `"null"`。閉包最單純。

**零新增端點**：窗要的兩個欄位清單裡本來就有，`GET /tasks` 一個字都沒動。

## 步驟

1. 寫 TODO。
2. `app/static/style.css`：`a.task-row` → `.task-row`、`a.task-row:hover` → `.task-row:hover`，
   `.task-row` 補四項 `<button>` 重設，其餘一字不動。
3. `app/static/photo_detail_modal.js`：`openPhotoDetailModal()` 的「清乾淨」段落補
   `config.task` 的畫法 ＋ `#pd-title` 切換，位置在 `fetch` 之前。
4. `app/static/browse.html` 的 `showTasks()`：提示文字改掉；`el("a", …)` → `el("button", …)`
   ＋ `row.type = "button"`；design3 §7 的兩行舊註解與 `row.href`／`row.target`／`row.rel`
   三行整組刪除；每列加 `click` 監聽；第 200 行段落註解出處改成 design4.md D1。
5. 掃碼驗收 ＋ `node --check` ＋ `pytest -q`。

## 測試方式

純前端，依專案慣例（Phase 23／24／31／33／39）**零新增自動化測試**，驗收三層：

| 層 | 方法 | 目的 |
|---|---|---|
| 掃碼 | `rg` 掃計畫 §6 的三組字串 | 證明舊路（開新分頁）真的刪乾淨、CSS 選擇器真的改了 |
| 語法 | `node --check app/static/photo_detail_modal.js` | 純前端沒有測試接得住語法錯 |
| 迴歸 | `pytest -q` | 顆數必須與開工前一致 |

計畫 §4.5 的 9 項瀏覽器實操**本次未做**：埠 8000 有使用者留著的 HTTPS uvicorn，
依指示不動、不自起，由主 agent 之後統一驗收。

## 遇到的問題與解法

### 1. 計畫給的註解字面會讓自己的驗收掃碼誤中

計畫 §4.4 的程式片段裡，新註解第一行寫的是：

```javascript
// 改開頁內詳情窗（design4.md D1／§1.1）：不再 target="_blank" 開新分頁——
```

但同一份計畫 §6 的第一條驗收是「`browse.html` 裡搜不到 `_blank`」。照抄註解就會**自己撞自己**：
`row.target` 那行明明已經刪了，`rg _blank` 仍然掃得到一筆——看起來像沒改完。實測確認會中。

處理方式沿用本專案既有慣例（`folder_modal.js` 第 7 行、Phase 39 計畫 §6 的同類提醒）：
**改寫註解、並在原地補一句自我提醒**，讓掃碼保持有意義：

```javascript
// 改開頁內詳情窗（design4.md D1／§1.1）：不再開新分頁——新分頁只有一張裸圖，
// 看不到 AI 寫的說明，也回不去這一頁。
// （刻意不寫出舊的 target 屬性值：驗收會 grep 掃它，註解不能誤中。）
```

語意與計畫完全相同，只是不寫出那個屬性值。**這是本 phase 唯一一處與計畫字面不同的地方。**

### 2. `.task-row` 的行號與計畫寫的不同（不是問題）

計畫寫「第 596／608 行」，實際在第 663／679 行——Phase 39 在前面插了 `pd-` 區塊（約 60 行），
整段往後位移。改的是同兩條規則，內容一致。

### 3. `text-decoration: none;` 留著

計畫 §4.3 說這行對 `<button>` 沒有作用、留著或刪掉都可以，並建議「留著比較不會動到不該動的東西」。
照建議留著。

## 測試結果

### 計畫 §6 驗收清單（可掃碼的部分）

| 項目 | 指令 | 結果 |
|---|---|---|
| `browse.html` 搜不到 `_blank`／`row.href`／`row.rel` | `rg '_blank\|row\.href\|row\.rel' app/static/browse.html` | ✅ 無輸出（改寫註解後；三行連結設定已整組刪除） |
| `style.css` 搜不到 `a.task-row` | `rg 'a\.task-row' app/static/style.css` | ✅ 無輸出 |
| `.task-row` 裡仍有 `color: var(--c-text)` | 讀規則全文 | ✅ 第 676 行仍在 |
| 待辦列改成 `<button>` ＋ `type="button"` | `rg task-row app/static/browse.html` | ✅ `el("button", "task-row")`＋`row.type = "button"` |
| 資料夾牆進來窗頂沒有待辦那一行、待辦進來有 | 讀 `openPhotoDetailModal` | ✅ `pdEl("pd-task").hidden = !待辦;`；`#pd-title` 同步切換 |
| 沒有到期日時寫「無到期日」（不能印 `null`） | 讀程式 | ✅ 三元判斷，與清單那一行同一寫法 |
| 待辦那一行畫在 `fetch` 之前 | 讀程式 | ✅ 第 197〜204 行，`fetch` 在第 215 行 |
| `#pd-task` 內容用 `textContent` | 讀程式 | ✅ 兩行都是 `textContent` |
| `pytest -q` 仍 365 ＋ 2 | `pytest -q` | ✅ **365 passed, 2 skipped** |
| 只動到三個檔 | `git status --short -- app` | ✅ `browse.html`＋`style.css`＋`?? photo_detail_modal.js`（另兩個 M 是 Phase 38 未 commit 的 Python 檔） |

### 額外檢查

| 項目 | 結果 |
|---|---|
| `node --check app/static/photo_detail_modal.js` | ✅ 語法 OK |
| 編輯器 lint（三個改動檔） | ✅ 零新增；唯一一條是 `style.css` 第 95 行的既有提示 |
| `GET /tasks` 契約與排序未動 | ✅ `app/` 的 Python 檔本 phase 零改動 |
| 待決定分頁、資料夾牆、三關彈窗鏈未被波及 | ✅ `folder_modal.js`／`entity_modal.js`／`task_modal.js`／`classify_chain.js`／`upload.html`／`ask.html`／`camera-*.html` 皆無變動 |
| 未新增 script 標籤（Phase 39 已掛） | ✅ `browse.html` 仍是三個 `<script src>` |
| `docs/spec/` 未動、未建 Docker 檔、未 commit | ✅ |

### 刻意未做

- 計畫 §4.5 的 9 項瀏覽器實操（含在 Console 執行 `openPhotoDetailModal({photoId: 99999, …})`
  驗 §9 錯誤表第 4 列）：埠 8000 有使用者留著的伺服器，依指示不動、不自起，主 agent 統一驗收。
- 未新增任何自動化測試（本專案前端慣例）。

## 階段甲狀態

Phase 38（端點）／39（唯讀彈窗＋資料夾牆入口）／40（待辦列入口）三份程式碼皆完成，
`pytest -q` ＝ 365 passed ＋ 2 skipped。**階段甲的瀏覽器實操驗收尚未進行**——
design4 §7 的閘門 G1 還要階段乙（AI 計時 log）＋產品負責人明示點頭，實作者不得自行勾過。

## 最終總驗收補記（2026-08-24，取代上段「尚未實操」的暫時狀態）

主 agent 後續已用 localhost 在 `1280x900`、`768x900`、`375x812` 三種 viewport
完成待辦列表與詳情窗自查。保留的 25 張全新 JPEG（與 Phase 39／待決定流程共用證據包）位於：

`/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`

精確分布為 11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`。已實操確認：待辦列在
**同一頁**開共用詳情窗、有到期日與無到期日兩種資料皆正確、遺失縮圖降級成占位、長 CJK／
日期／數字單位在平板與手機寬度不被不自然拆開；×／Esc／暗色背景關閉、focus trap、背景
`inert`、Tab／Shift+Tab 循環、focus restore 與 generation token 忽略 stale response 都已
RED→GREEN。待決定照片仍開歸類窗，沒有被改成詳情窗；raw error 不會外露。

最終自動化為 **402 passed, 2 skipped, 1 warning in 27.73s**；唯一 warning 是
`StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
`node --check app/static/photo_detail_modal.js`、`node --check app/static/folder_modal.js`、
`git diff --check` 皆為 exit 0。這些是技術自證，不替產品負責人在 G1 包 B〜E 勾選。

兩位最新獨立視覺 reviewer（`final_visual_qa_k`、`final_visual_qa_l`）最終皆為
**PASS／HIGH confidence／25 of 25／zero blockers**，技術視覺 gate 已完成；這仍不替產品負責人
勾選 G1 B／D／E。
狀態維持：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty；
沒有 commit、release、Docker／Compose 或 Phase 45 工作。
