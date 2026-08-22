# Phase 33：待辦彈窗與瀏覽第三入口（design3.md D9／D13／D15——鏈 1→2→3 完成）

> 🎯 **純前端 phase**：後端零改動、零新增自動化測試；驗收＝Playwright 實操。
> 待辦窗**只在上傳鏈且 VLM 判斷有 actionable 時**出現（§2.1「空關不跳」；建議不持久化→待決定補完鏈不含它——總覽 §5 已知限制）。

**目標：** ① `task_modal.js`（顯示建議標題／到期日、可修改，「建立待辦」／「略過」兩出口）。
② 上傳頁彈窗鏈補上第三關：抽屜→實體→（有 suggested_task 才）待辦。
③ 瀏覽頁第三分頁「待辦（M）」：列標題、到期日、縮圖，點列開來源原圖。

## 檔案

- 建：`app/static/task_modal.js`（tm 前綴；class 沿用 fm-* 共用視覺）
- 改：`app/static/upload.html`（鏈 2→3）、`app/static/browse.html`（三分頁）、`app/static/style.css`（待辦列表樣式，沿用 tokens）

## task_modal.js 介面定稿

```js
openTaskModal({
  photoId: 7,
  suggestion: {title: "…", due: "2026-09-18" 或 null},  // 呼叫端保證非 null 才開窗
  onDone: function (createdTask 或 null) { … }           // 建立成功帶 TaskOut；略過帶 null
});
```

- 樣板：標題「這張照片裡有一件待辦？」；`#tm-title`（文字輸入，預填 suggestion.title）；
  `#tm-due`（`type="date"`，預填 suggestion.due，可清空）；「建立待辦」`#tm-create`；「略過」`#tm-skip`；`#tm-error`。
- 「建立待辦」→ `POST /photos/{id}/task`，body `{title, due_date: 值或 null}`；
  201 → 關窗、onDone(task)；4xx → 紅字寫 `#tm-error` 窗不關（改完可重按）。「略過」→ 關窗、onDone(null)、不打 API。
- 禁 alert；動態內容 textContent；busy 鎖按鈕。出口只有兩顆按鈕（與另兩窗一致，不裝 Esc／點外）。

## 上傳頁鏈定稿（§2 順序固定：抽屜→實體→待辦）

```js
// entity modal 的 onDone 裡：
if (body.suggested_task && body.suggested_task.title) {
  openTaskModal({ photoId, suggestion: body.suggested_task, onDone: 更新結果卡 });
} else { 更新結果卡; }   // 空關不跳
```
- 結果卡的備註行累積三關結果：資料夾（已歸「收據」／待決定）＋實體（釘了 N 個／未釘）＋待辦（已建立「…」／略過／無）。
- PDF（P28）仍只對 created[0] 跑整條鏈。

## 瀏覽頁三分頁定稿

- 網址規則不變的延伸：`browse.html`＝待決定（預設）、`?tab=folders`＝資料夾、**`?tab=tasks`＝待辦**、`?folder=N`＝縮圖牆。
- `renderTabs(active, pendingCount, taskCount)`：三顆頁籤「待決定(N)｜資料夾｜待辦(M)」；
  M＝`GET /tasks` 的長度（每次進頁多一個小 GET，本地服務無妨）。
- 待辦分頁：空清單訊息「還沒有待辦。上傳時 AI 判斷有可辦事項、且你按「建立」的會出現在這裡。」；
  每列（`ul.tasks > li > a.task-row`）＝縮圖（無→灰底占位）＋標題＋到期日（無→「無到期日」）；
  整列連到 `/photos/{photo_id}/image` 新分頁（「能點回來源圖」——design3 §7；舊照片無原圖 404 屬預期，維持原生行為）。

## Playwright 實操驗收（真伺服器＋真 gemma4）

1. 上傳一張含明確待辦的圖（手寫「9/18 交 Project 2」便條或收據 due 情境）→ 三關依序：抽屜→實體→**待辦窗出現、標題到期日已預填**→建立→結果卡顯示已建立；瀏覽頁待辦分頁看得到、點列開原圖。
2. 上傳一張無待辦的風景圖 → 實體窗結束後**待辦窗不出現**（空關不跳）。
3. 對已有待辦的照片再 `curl POST` → 409；標題空白 422（窗內紅字驗一次）。
4. 待辦分頁：到期日排序正確（先到期在前、無到期日在最後）；tab 計數正確；`?tab=tasks` 直達；上一頁正常。
5. 待決定分頁補完鏈仍是抽屜→實體（**無待辦窗**）；三頁 console 乾淨；`pytest -q` 顆數不動。

## 驗收清單

- [x] 三關鏈完整（§2 順序固定；**空關不跳由真上傳 #22 實測**——實體關結束後待辦窗未開）；
      建立／略過都不打多餘 API（存根 fetch 次數斷言＋真頁面驅動 201）
- [x] 瀏覽頁三分頁、計數（待決定（6）｜資料夾｜待辦（2））、`?tab=tasks` 直達、
      到期排序（09-01 在 09-18 前）、縮圖、點列 `/photos/{id}/image` `_blank`（DDD Playwright 實測）
- [x] `grep -c "alert(\|confirm(\|prompt(" app/static/*.js` ＝ 0；動態內容零 innerHTML 插值
- [x] 後端零改動；全量 pytest 218（P32 的 +11，本 phase 零增減）
