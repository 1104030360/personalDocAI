# 2026-08-21 階段CCC：Phase 33 待辦彈窗與瀏覽第三入口——REP

## 實作邏輯

design3.md D9／D13／D15 的最後一關。①全站第三份彈窗 `task_modal.js`（tm- id＋fm-* 共用視覺 class）：
標題與到期日放在**可修改的輸入框**（AI 抽的是草稿，人改完再按建立）；出口只有「建立待辦」（POST）與
「略過」（不打 API）兩顆按鈕。②上傳頁鏈 2→3：`接著釘實體()` 的 onDone 接 `接著確認待辦()`——
**只有 `suggested_task.title` 存在才開窗**（§2.1「空關不跳」），結果卡逐關累積三種決定的成果。
③瀏覽頁第三分頁「待辦（M）」：`?tab=tasks` 直達、清單一列一件事（縮圖／標題／到期日靠右等寬字）、
整列連 `/photos/{photo_id}/image` 開新分頁（「能點回來源圖」，§7）；三個分頁的頁籤計數互通。
待決定分頁的補完鏈**不含**待辦窗（建議不持久化——總覽 §5 已知限制）。

## 步驟

1. `task_modal.js`：openTaskModal（預填建議、busy 鎖全欄位、錯誤寫 `#tm-error`、略過零 API）。
   計畫檔原寫輸入框 id 為 `#tm-title`——實作把 h3 取 `#tm-title`（與 `#fm-title`／`#em-title` 的 CSS
   慣例一致）、輸入框改 `#tm-title-input`（已記錄於 TODO）。
2. `upload.html`：`接著確認待辦()`＋掛第三個 script；無建議時鏈到實體即收工（行為與 P31 完全相同）。
3. `browse.html`：`renderTabs(active, pendingCount, taskCount)` 三頁籤；`showTasks()`；
   `?tab=tasks` 路由；三個 view 都補抓 `GET /tasks` 當計數（本地服務多一個小 GET 無妨）。
4. `style.css`：`#tm-title`／`#tm-create` 掛進既有選擇器；`input[type="date"]` 併入彈窗輸入框樣式；
   新增待辦列表區（`ul.tasks`／`a.task-row`／`.task-thumb(-empty)`／`.task-due` 等寬靠右），全走 tokens。

## 測試方式與結果

- `node --check` 三份彈窗檔全過；**task_modal 存根四情境實跑全過**（假 DOM＋排隊假 fetch）：
  ①預填建議值 ②422 紅字在窗內、窗不關 ③改標題＋清到期日→201、窗關、onDone 帶 TaskOut
  （body 斷言 `{title, due_date: null}` 精確）④略過→零 API（fetch 總次數斷言）＋onDone(null)。
- `pytest -q`＝**218 passed**＝零 Ollama 同顆數（P32 落地後 controller 統一複驗；本 phase 後端零改動）。
- alert/confirm/prompt 掃碼＝0（三份彈窗檔）；動態內容一律 textContent。
- Playwright 瀏覽器實操（真伺服器＋真 gemma4 的 1→2→3 全鏈、三分頁、點回原圖）於總驗收階段執行。

## 遇到的問題與解法

1. 與 P32 平行開發（P31 的 subagent 兩次異常後，前端改 controller 親自寫）：檔案零相交、
   pytest 等 P32 收工才跑——避免共用測試庫的 TRUNCATE 互撞。
2. 存根第一版留了一行草稿殘留（模板字串誤插）→ 移除後全綠。

## 備註

- 新增 1 檔（task_modal.js）、修改 3 檔（upload／browse／style）；不 commit。
