# 階段LLL TODO：Phase 39 唯讀詳情彈窗 ＋ 資料夾牆入口

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP；計畫 §4.5 瀏覽器實操已由主 agent 統一驗收完成）
> 依據：`docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`（逐條照做）＋`docs/design/design4.md` §4.1〜§4.3、D1／D2／D4／D6、§1.1 第 1 列、§9 第 3 列
> 開工基準（已實測）：`pytest -q` ＝ 365 passed ＋ 2 skipped（Phase 38 之後的基準）

> **後續最終狀態：** 上述 365＋2 是歷史 phase-local 基準。目前 full suite 為
> **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。最終 pass-8 共 25 張 JPEG
> （11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`）；`final_visual_qa_k`、
> `final_visual_qa_l` 均 **PASS／HIGH confidence／25 of 25／zero blockers**。
> 最新 RED→GREEN 已涵蓋 focus trap、背景 `inert`、Tab／Shift+Tab、focus restore、stale
> generation、遺失圖片、raw error 與長 CJK。這是技術自驗，G1 B／C／D／E 仍保留空白。
> 狀態為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

## 實作邏輯

增量四階段甲的第二步：Phase 38 做出了 `GET /photos/{photo_id}`，這一步做出**看得到它**的那顆窗。

全站唯一一份 `photo_detail_modal.js`，前綴 `pd-`，性格三句話：

1. **唯讀**。窗裡沒有任何改資料夾的按鈕——design2.md 的「定案不可逆」仍然有效，
   design4 §1.2 第 1 列已明文否決「資料夾點開再歸類／改夾」。待決定分頁點照片**仍走歸類鏈**，
   不走這顆窗（design4 §4.1 第 3 列明寫「不改」）。
2. **關得掉**。× ／ Esc ／ 點暗色區三種出口都要有。這顆**不是** design2 那種強制決定窗——
   它只回答「這張是什麼」，沒有需要使用者拍板的事，關掉不會留下未決狀態。
3. **外框沿用 `fm-*` class、id 用 `pd-` 前綴**。那是 `style.css` 檔頭第 4〜5 行寫明的既有約定
   （class 共用視覺語言、id 各自加前綴），沿用＝零複製樣式、外觀天然與另外三顆窗一致。

同一顆窗兩種入口：本 phase 只接資料夾縮圖牆（`task: null`），待辦列是 Phase 40 的事。
所以本 phase 的 `#pd-task` 一律隱藏，但 HTML 樣板與 CSS 先寫好，Phase 40 只補畫法。

**`.photo-static` 要一起刪掉**：design4 §1.1 第 1 列正式推翻了 design2.md D4
（「資料夾 tab 的縮圖牆純瀏覽、照片不可點」），改完之後兩個牆都是可點的 `<button>`，
那兩條 CSS 從此無人使用。留著會讓下一個人以為縮圖牆還有「不可點」的模式（不留過渡產物）。

## 步驟

- [x] 寫 TODO。開工前先跑 `pytest -q` 確認基準是 365 passed ＋ 2 skipped。
- [x] 新建 `app/static/photo_detail_modal.js`（計畫 §4.2 逐條）：
      檔頭註解（用法、三種關窗、禁 alert）→ 固定樣板 HTML 字串 → `pdReady`／`pdLastFocus`
      → `pdEl`／`pdSetError`／`pdOpen`／`pdClose` → `pdInstall()`（只裝一次、三種關窗的監聽）
      → `pd畫占位`／`pd畫圖`／`pd值或無`／`pd畫四欄` → `openPhotoDetailModal(config)` 五步流程。
      ⚠ 計畫 §6 的掃碼陷阱：檔頭提到隔壁那份時寫 `folder_modal.js`（**不帶斜線**），
      寫成帶路徑的形式會讓「搜不到斜線＋folder」那條驗收誤中。
- [x] `app/static/style.css`：
      ① `#pd-title` 加進第 533〜535 行那條 **id** 選擇器（不加＝這顆窗的 `<h3>` 掉回瀏覽器
      預設樣式，而且右上角的 × 會壓在標題上）；
      ② 「彈窗（fm-*）」區塊之後新增「詳情彈窗」註解區塊，照計畫 §4.3 的表寫 11 條規則
      （顏色／字級／間距只用既有 design tokens，不新增色票）；
      ③ 刪掉 `.photo-static` 兩條規則與其上那行註解。
- [x] `app/static/browse.html` 四處（計畫 §4.4 ①〜⑤）：
      ① 第 25 行後掛 `<script src="/ui/photo_detail_modal.js"></script>`；
      ② `照片卡(photo, 可點)` → `照片卡(photo)`，一律產生 `<button class="photo">`；
      ③ 兩個呼叫端（`showPending`／`showFolderPhotos`）跟著拿掉第二個參數；
      ④ `showFolderPhotos()` 加提示文字 ＋ 整面牆一個 `click` 事件委派開窗（`task: null`）；
      ⑤ 兩處「純瀏覽」註解改字（第 33 行網址對照表、第 246 行段落標題）。
- [x] 自我驗收（計畫 §6 可掃碼的部分）：js 檔搜不到 `alert(`／`confirm(`／`prompt(`／
      `PATCH`／斜線＋`folder`，`innerHTML =` 恰一次（裝樣板的固定字串）；
      `style.css` 搜不到 `.photo-static`、有 `pd-` 區塊；`browse.html` 的 `照片卡` 只剩一個參數。
- [x] `pytest -q` 仍是 **365 passed ＋ 2 skipped**（純前端，顆數不變）。
- [x] `git diff --stat -- app` 恰兩檔 ＋ `git status --short -- app` 一個 `??`（新建的 js）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 窗裡放「改資料夾」「重新歸類」按鈕 | design4 D2、§1.2 第 1 列已否決 |
| 窗裡放刪除照片／刪待辦 | 全系統沒有刪除端點（design3 §3、design4 §1.2 第 2 列） |
| 動待決定分頁的行為 | design4 §4.1 第 3 列明寫「不改」——仍走抽屜→實體歸類鏈 |
| 動 `folder_modal.js`／`entity_modal.js`／`task_modal.js`／`classify_chain.js` | 計畫 §7 陷阱 6：一個字都不碰。焦點管理與捲動鎖定在自己的 `pd` 版本重寫一份小的 |
| 在 `upload.html`／`ask.html`／`camera-desk.html` 掛這一份 js | design4 §4.3 末句：其他頁本輪不必掛 |
| 用 `alert`／`confirm`／`prompt` 顯示錯誤 | 全站鐵律。錯誤一律寫進窗內的 `#pd-error` |
| 用 `innerHTML` 塞 AI 產生的文字 | 全站鐵律。動態內容一律 `textContent` |
| 為這顆窗新增自動化測試 | 本專案前端慣例（Phase 23／24／31／33 皆然）：純前端零新增自動化測試 |
| 做上一張／下一張、放大縮小、下載圖 | design4 沒要求；不要過度設計 |
| 把 `.photo-static` 留著「以防萬一」 | 計畫 §7 陷阱 7：沒人用的 CSS 就是垃圾，不留過渡產物 |
| 動任何 `app/` 的 Python 檔、既有測試、`docs/spec/` | 純前端 phase；規格本輪不改（design4 §3） |
| 建任何 Docker 檔 | 階段丙的東西，G1 閘門沒過不准建（design4 §0） |
| 起伺服器做計畫 §4.5 的 14 項瀏覽器實操 | 埠 8000 有使用者留著的 HTTPS uvicorn，不動、不自起；主 agent 之後統一驗收 |
| `git add`／`git commit` | 本增量全程不 commit |

## 執行方式

以 subagent 實作，主 agent 事後 review ＋ 瀏覽器統一驗收。
本 phase 驗收以「程式碼掃描 ＋ pytest 顆數不變」為準。
