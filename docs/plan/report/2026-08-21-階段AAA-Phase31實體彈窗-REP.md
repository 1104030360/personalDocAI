# 2026-08-21 階段AAA：Phase 31 實體彈窗——REP

## 實作邏輯

design3.md D12／§2.1 的彈窗 2。新檔 `app/static/entity_modal.js`（全站第二份彈窗）：
結構完全鏡射 folder_modal.js（樣板字串＋只裝一次＋config/callback 對外），**id 用 em- 前綴隔離、
樣式 class 沿用 fm-***（三彈窗共用視覺語言，style.css 零複製——只把 `#em-title`／`#em-primary`
掛進既有 id 選擇器）。與抽屜強制窗不同：實體窗可略過（④），但出口仍只有明確按鈕（不吃 Esc／點外，
三窗行為一致）。釘上（①②③）成功**窗不關**——已釘列表 +1、下拉換成回應裡的最新清單（③自創即時 +1）、
④文字隨成果變（不釘，繼續／完成，繼續）；「再建議一個」帶 exclude＝已釘＋目前①去要下一個，
null 就顯示「沒有其他適合的實體了」。鏈接依 §2.1：抽屜窗結束——**定案或稍後再說都一樣**——接著開實體窗；
上傳頁用回應自帶的 entities/suggested_entity，待決定分頁開窗前現抓 GET /entities、suggested 一律 null
（建議不持久化，沿 design2 D5 先例），reload 移到鏈尾。

## 步驟

1. `entity_modal.js`：狀態三件（emPinned／emSuggested／emEntities）＋三塊重繪（pinned／primary／select）＋
   兩個 API 動作（emPin／emAskForMore）；busy 鎖全部按鈕與輸入；錯誤寫 `#em-error`、提示寫 `#em-note`；
   `emDetailText` 與 fm 版刻意重複十行（兩檔互不 import——改一個彈窗絕不弄壞另一個，註解記明）。
2. `upload.html`：`開始歸類()` 的 onAssigned／onClosed 都改走新函式 `接著釘實體()`（卡片先寫資料夾結果、
   再開實體窗、④後補實體成果）——此函式即 P33 待辦窗的乾淨掛點；PDF（created[0]）同一條鏈。
3. `browse.html`：待決定分頁 onAssigned／onClosed 都續鏈；`接著釘實體(photoId)` 先 getJson("/entities")
   （失敗當空清單開窗——③④仍能走、錯誤會在窗內顯示）。
4. `style.css`：檔頭補「fm-* class＝三彈窗共用視覺、id 各自 fm-/em-/tm-」原則；彈窗區標題同步。

## 測試方式與結果

- `node --check` 語法通過；**node 存根五情境實跑全過**（假 DOM＋排隊假 fetch）：
  ①空清單開窗（①②隱藏、④＝不釘）②③自創釘上（窗不關、已釘列表、④變完成、②出現、輸入清空）
  ③重複釘 409（紅字含訊息、窗不關）④再建議（exclude 第一次 `[1]`、第二次 `[1,2]` 斷言精確；null→①隱藏＋提示）
  ⑤④出口（onDone 帶成果、窗關）。fetch 網址與 body 逐筆驗證。
- `pytest -q`＝**207 passed**（後端零改動）；alert/confirm/prompt 掃碼＝0；
  git status 恰 4 檔（entity_modal.js 新增＋三檔前端修改）。
- Playwright 瀏覽器實操（真伺服器＋真 gemma4）依裁定留待總驗收階段一次跑（含 P33 的鏈 1→2→3）。

## 遇到的問題與解法

1. **subagent 兩次異常**：第一次派工被中止；重派後 34 分鐘**零檔案改動、transcript 僅 143 bytes**（卡死）——
   TaskStop 停掉後改由 controller 親自實作（本 phase 規格是我寫的、前端脈絡都在手，親自寫反而最快最穩）。
2. 存根第一版把 fetchLog 放錯作用域（new Function 內拿不到外層 const）——改由外層直接斷言，重跑全綠。

## 備註

- 新增 1 檔、修改 3 檔；不 commit（e29f5a1 之後的新工作依產品負責人原指示先不 commit）。
