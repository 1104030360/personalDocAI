# 2026-08-21 階段CCC：Phase 33 待辦彈窗與瀏覽第三入口——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-33-待辦彈窗與瀏覽待辦tab.md`：①`task_modal.js`（顯示建議標題／到期日、
可修改；「建立待辦」／「略過」兩出口）②上傳頁彈窗鏈補第三關（抽屜→實體→**有 suggested_task 才**待辦
——空關不跳）③瀏覽頁第三分頁「待辦（M）」（列標題／到期日／縮圖，點列開來源原圖；`?tab=tasks` 直達）。

## 實作邏輯

- 純前端 phase；後端契約＝Phase 32 定稿（`POST /photos/{id}/task {title, due_date}`→201 TaskOut；
  `GET /tasks`→TaskOut 陣列含 thumbnail_url）。
- 彈窗第三份 `task_modal.js`：tm- id 前綴＋fm-* 共用視覺 class（與前兩窗同一套原則）；
  出口只有「建立待辦」與「略過」兩顆按鈕；錯誤寫窗內 `#tm-error`。
- 待決定分頁的補完鏈**不含**待辦窗（建議不持久化——總覽 §5 已知限制）。
- 與 Phase 32 平行進行（檔案不相交），pytest 於 P32 完成後統一複驗。

## 步驟

- [x] 1. `task_modal.js`（openTaskModal 介面照計畫檔；h3 id 取 `#tm-title`、輸入框 `#tm-title-input`——
      與前兩窗的 title id 慣例一致，計畫檔原寫法微調並記錄）
- [x] 2. `upload.html` 鏈 2→3（`接著釘實體()` 的 onDone 掛待辦窗；無建議不開窗＝空關不跳）
- [x] 3. `browse.html` 三分頁（renderTabs 加「待辦（M）」、`?tab=tasks`、showTasks 列表、點列開原圖）
- [x] 4. `style.css`：`#tm-title`／`#tm-create` 掛進既有選擇器；`input[type="date"]`；待辦列表列樣式（全 tokens）
- [x] 5. node --check＋存根實跑四情境（預填／422 窗不關／201 關窗帶 TaskOut／略過零 API）；alert 掃碼 0
- [x] 6. P32 完成後：全量 pytest 複驗＝218＝零 Ollama；controller review；Playwright 實操於階段DDD 執行

## 執行方式

Controller 親自實作（Phase 31 的 subagent 前端兩次異常後的裁定）；與 Phase 32（subagent、後端）平行。不 commit。
