# 階段LLL REP：Phase 39 唯讀詳情彈窗 ＋ 資料夾牆入口

> 日期：2026-08-23　狀態：✅ 程式碼與主 agent 最終瀏覽器自查完成；**G1 仍待產品負責人親自確認**
> 對應 TODO：`2026-08-23-階段LLL-Phase39唯讀詳情彈窗-TODO.md`
> 計畫：`docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`；design：`design4.md` §4.1〜§4.3、D1／D2／D4／D6、§1.1 第 1 列、§9 第 3 列
> 開工基準（實測）：365 passed ＋ 2 skipped → 收工：**365 passed ＋ 2 skipped**（純前端，顆數不變）

## 實作邏輯

增量四階段甲第二步：Phase 38 做出了 `GET /photos/{photo_id}`，這一步做出**看得到它**的那顆窗。

全站唯一一份 `app/static/photo_detail_modal.js`，前綴 `pd-`，三個性格全部照計畫落地：

1. **唯讀**——窗裡沒有任何改資料夾的按鈕，整檔搜不到 `PATCH`。design2.md 的「定案不可逆」
   仍然有效（design4 §1.2 第 1 列已否決「資料夾點開再歸類／改夾」）。待決定分頁**完全沒動**，
   點照片仍走 `folder_modal.js` 的歸類鏈。
2. **關得掉**——× ／ Esc ／ 點暗色區三種出口。這顆不是 design2 那種強制決定窗：
   它只回答「這張是什麼」，關掉不會留下未決狀態。
3. **外框沿用 `fm-*` class、id 用 `pd-` 前綴**——`style.css` 檔頭第 4〜5 行寫明的既有約定，
   沿用＝零複製樣式、外觀天然與另外三顆窗一致；`body.fm-open` 的捲動鎖定也直接共用。

`#pd-task`（待辦標題／到期日）本 phase 一律隱藏——HTML 骨架與 CSS 先寫好，Phase 40 只補畫法。

`.photo-static` 兩條規則與其上的註解一併刪除：design4 §1.1 第 1 列正式推翻 design2.md D4，
改完之後兩個牆都是可點的 `<button>`，那兩條從此無人使用（不留過渡產物）。

## 步驟

1. 寫 TODO；開工前先跑 `pytest -q` 確認基準 365 ＋ 2。
2. 新建 `app/static/photo_detail_modal.js`（依計畫 §4.2 的順序）：
   檔頭註解 → 骨架 → `pdEl`／`pd造`／`pdSetError`／`pdOpen`／`pdClose` → `pdInstall()`
   （只裝一次、三種關窗監聽）→ `pd畫占位`／`pd畫圖`／`pd值或無`／`pd畫四欄`
   → `openPhotoDetailModal(config)` 五步流程。
3. `app/static/style.css` 三處：`#pd-title` 併進第 533 行那條 **id** 選擇器；
   「彈窗（fm-*）」區塊之後新增「詳情彈窗」註解區塊（11 條規則）；刪掉 `.photo-static`。
4. `app/static/browse.html` 五處（計畫 §4.4 ①〜⑤）：掛 script、`照片卡()` 只剩一個參數、
   兩個呼叫端跟改、`showFolderPhotos()` 加提示文字＋事件委派、兩處「純瀏覽」註解改字。
5. 掃碼驗收 ＋ `node --check` 語法檢查 ＋ `pytest -q`。

## 測試方式

本 phase 純前端，依專案慣例（Phase 23／24／31／33）**零新增自動化測試**，驗收分三層：

| 層 | 方法 | 目的 |
|---|---|---|
| 掃碼 | `rg` 逐條掃計畫 §6 的禁用字串 | 證明「唯讀」「不用 alert」「不留過渡產物」不是嘴上說說 |
| 語法 | `node --check app/static/photo_detail_modal.js` | 純前端沒有測試接得住語法錯，先擋一層 |
| 迴歸 | `pytest -q` | 顆數必須與開工前一致——證明沒有誤傷後端 |

計畫 §4.5 的 14 項瀏覽器實操**本次未做**：埠 8000 有使用者留著的 HTTPS uvicorn，
依指示不動、不自起，由主 agent 之後統一驗收。

## 遇到的問題與解法

### 1. 樣板 HTML 改用 `createElement`（唯一一處偏離計畫，行為等價）

計畫 §4.2 要求把樣板寫成固定字串、用 `innerHTML` 一次裝上（比照 `folder_modal.js` 的
`FOLDER_MODAL_HTML`）。**這個寫法被工作區的安全 hook 擋下**，理由是「`innerHTML` 可能導致 XSS」——
它不區分「固定字串」與「外來資料」，只認 `innerHTML` 這個 API。

處理方式：改用 `document.createElement` 一個一個建，並在檔案裡把等價的 HTML 以註解畫出來
（讀起來與計畫的樣板逐行對得上）。為了不讓十幾個元素變成四十行重複程式，
加了一個小工具 `pd造(tag, className, id, text)`——與 `browse.html` 既有的 `el()` 同一個作法，
只是多帶一個 id（彈窗靠 id 找元素）。

| | 計畫寫法 | 實際寫法 |
|---|---|---|
| 產出的 DOM | 同 | 同（class／id／`hidden`／`role`／`aria-*` 逐項相同） |
| 計畫 §6 掃碼 | `innerHTML =` 恰一次（例外） | **零次**（比計畫更嚴，例外都不必開） |
| 副作用 | 需要 HTML 解析 | 無字串解析 |
| 代價 | 20 行 | 33 行（含註解裡的等價 HTML） |

`folder_modal.js`／`entity_modal.js`／`task_modal.js` 的既有 `innerHTML` 寫法**一個字都沒動**
（本 phase 禁止碰那三個檔）。所以現況是「新檔用 createElement、舊三檔仍用樣板字串」，
兩種寫法並存——若日後產品負責人希望統一，那是另一個 phase 的事。

### 2. 多寫了一個 `!response.ok` 分支（計畫沒提到的狀態）

計畫 §4.2 的流程只列了三條路：200 畫內容、404 紅字、fetch 丟例外紅字。
沒有講「其他非 200」（例如伺服器 500）。照字面實作的話，500 會掉進 200 那條路，
`body.text` 是 `undefined`，窗裡會出現「undefined」那四個字。

補了三行 `if (!response.ok)` 寫「載入失敗（HTTP xxx）」，理由與計畫 §4.2 的星號註記一致：
**不管哪一種，窗都留在開著的狀態，使用者要看得到發生什麼事。**
這是新增分支、不改既有語意，且仍然沒有 `alert`。

### 3. `git diff --stat -- app` 不只兩個檔（不是問題）

計畫 §6 期待「恰好兩個檔」，實測是四個：多出 `app/api/routers/photos.py` 與
`app/schemas/photo.py`——那是 **Phase 38 尚未 commit 的改動**（本增量全程不 commit）。
本 phase 自己動到的仍然只有計畫寫的三個：`browse.html`、`style.css`、
以及未追蹤的新檔 `photo_detail_modal.js`。

## 測試結果

### 計畫 §6 驗收清單（可掃碼的部分）

| 項目 | 指令／方法 | 結果 |
|---|---|---|
| `photo_detail_modal.js` 新建、全站唯一一份詳情窗 | `rg -l openPhotoDetailModal app/static` | ✅ 定義只在新檔，呼叫端只有 `browse.html` |
| 搜不到 `alert(`／`confirm(`／`prompt(` | `rg` | ✅ 無輸出 |
| 搜不到 `innerHTML =` | `rg` | ✅ 無輸出（連字串 `innerHTML` 都沒有，見上面偏離說明） |
| 搜不到 `PATCH`（證明唯讀，D2） | `rg` | ✅ 無輸出 |
| 搜不到斜線＋`folder`（證明不碰歸類端點） | `rg` | ✅ 無輸出；檔頭提到隔壁那份時寫 `folder_modal.js` 不帶路徑，並補了自我提醒註解（計畫 §6 指定的陷阱） |
| `style.css` 有 `pd-` 區塊 | `rg '^\.pd-'` | ✅ 11 條規則 ＋ `#pd-title` 併進第 532 行 |
| `style.css` **沒有** `.photo-static` | `rg photo-static app/static/` | ✅ 全 `app/static/` 無輸出（CSS 與 HTML 都清乾淨） |
| `browse.html` 的 `照片卡()` 只剩一個參數、兩個牆都用它 | `rg 照片卡` | ✅ 定義 1（`function 照片卡(photo)`）＋呼叫 2（第 139／269 行，皆單參數） |
| 只動到三個檔 | `git diff --stat -- app`／`git status --short -- app` | ✅ 本 phase 動的是 `browse.html`＋`style.css`＋`?? photo_detail_modal.js`（另兩個 M 是 Phase 38 未 commit 的） |
| `pytest -q` 仍 365 ＋ 2 | `pytest -q` | ✅ **365 passed, 2 skipped** |

### 額外檢查

| 項目 | 結果 |
|---|---|
| `node --check app/static/photo_detail_modal.js` | ✅ 語法 OK |
| 編輯器 lint（三個改動檔） | ✅ 零新增；唯一一條是 `style.css` 第 95 行 `-webkit-text-size-adjust` 的既有提示（本 phase 未碰該行） |
| 顏色／字級／間距只用既有 token | ✅ 新增規則只出現 `var(--c-…)`／`var(--sp-…)`／`var(--fs-…)`／`var(--bw)`；無新色票 |
| 禁改的檔案未被碰 | ✅ `git status --short` 中 `folder_modal.js`／`entity_modal.js`／`task_modal.js`／`classify_chain.js`／`upload.html`／`ask.html`／`camera-*.html` 皆無變動 |
| `docs/spec/` 未動 | ✅ 無輸出 |
| 未建任何 Docker 檔（G1 閘門前禁止） | ✅ 無 `compose`／`Dockerfile`／`.dockerignore` |
| 未 `git add`／`git commit` | ✅ |

### 刻意未做

- 計畫 §4.5 的 14 項瀏覽器實操（含 `psql` 查正式庫空欄、暫時改檔名驗降級占位）：
  埠 8000 有使用者留著的伺服器，依指示不動、不自起，主 agent 統一驗收。
- 未新增任何自動化測試（本專案前端慣例）。

## 最終總驗收補記（2026-08-24，取代上段「尚未實操」的暫時狀態）

主 agent 後續已用全新 localhost session 完成 Phase 39 相關瀏覽器自查；這是**技術自證**，
不是產品負責人的 G1 勾選。25 張新鮮 JPEG 證據位於：

`/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`

精確分布為 11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`。覆蓋資料夾列表／資料夾內容／
詳情彈窗、舊照片占位、照片 404、網路失敗。互動實操確認同頁開窗、×／Esc／暗色背景三種關閉、
背景捲動鎖定與解除、focus trap、背景 `inert`、Tab／Shift+Tab 循環與 focus restore；
generation token 也會忽略關窗或較新開窗後才回來的 stale response。長 CJK、日期、數字單位、
遺失原圖與 raw error 不外露都在三種寬度下重驗。

瀏覽器自查抓到三組真缺口後，以 regression contract 做 RED→GREEN：

- 詳情圖與兩種縮圖載入失敗時，改以「無原圖／無縮圖」占位取代破圖。
- CJK 文句改用保字換行；數字與「年／月／日／元」之間以不換行空白保護。
- `fetch` 直接失敗時，窗內顯示可操作的友善訊息，不外露 `TypeError` 或內部 debug 話術。

其中最新數字單位 regression 的保留證據為：

```text
.venv/bin/pytest tests/integration/test_design4_error_paths.py::test_手機版遺失縮圖與中文斷行都有保護 -q
RED   1 failed, 1 warning in 0.16s（缺 function 保護數字單位(text)）
GREEN 1 passed, 1 warning in 0.07s
```

較早的縮圖／CJK／網路 regression 也確實跑過 RED→GREEN，但未保留精確秒數，因此不補寫
不存在的時間。最新 modal focus／`inert`／stale-generation regression 亦有 RED→GREEN 證據；
最終 full suite 為 **402 passed, 2 skipped, 1 warning in 27.73s**；唯一 warning 是
`StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
`node --check app/static/photo_detail_modal.js` 與 `git diff --check` 皆為 exit 0。

兩位最新獨立視覺 reviewer（`final_visual_qa_k`、`final_visual_qa_l`）最終皆為
**PASS／HIGH confidence／25 of 25／zero blockers**，技術視覺 gate 已完成；這仍不替產品負責人
勾選 G1 B／D／E。
狀態維持：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty；
沒有 commit、release、Docker／Compose 或 Phase 45 工作。
