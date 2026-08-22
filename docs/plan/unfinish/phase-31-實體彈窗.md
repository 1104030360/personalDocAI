# Phase 31：實體彈窗（design3.md D12、§2.1——彈窗鏈 1→2）

> 🎯 **純前端 phase**：後端零改動、零新增自動化測試；驗收＝Playwright 實操。
> 彈窗程式碼一站一份原則不變：實體彈窗獨立成 `entity_modal.js`（em 前綴），與 folder_modal.js 互不相碰。

**目標：** 新增實體彈窗（①採用建議②改選現有③自創④不釘＋「再建議一個」，可連續釘多個）；
上傳頁與待決定分頁的抽屜彈窗結束後（**含「稍後再說」——§2.1 鏈仍繼續**）接著開實體窗。

## 檔案

- 建：`app/static/entity_modal.js`
- 改：`app/static/upload.html`（鏈 1→2）、`app/static/browse.html`（待決定分頁鏈 1→2）、
  `app/static/style.css`（檔頭註記：`.fm-*` 樣式類名為三個彈窗**共用**的視覺語言，id 才分 fm-/em-/tm-）

## entity_modal.js 介面定稿

```js
openEntityModal({
  photoId: 7,
  entities: [{id,name,description}, …],   // ② 下拉（完整實體清單；空清單→②整列隱藏）
  suggested: {id,name,description} 或 null, // ①；null＝整列不顯示（待決定分頁進來都是 null）
  onDone: function (pinnedList) { … }       // 使用者按④離開；帶這輪釘上的實體陣列（可為空）
});
```

- 樣板（class 沿用 fm-*、id 全部 em-*）：標題「要把這張照片釘上實體嗎？（可釘多個）」；
  已釘列表 `#em-pinned`（textContent 逐一 append）；①`#em-primary`「釘上「名稱」」＋說明；
  ②下拉＋「釘上這個實體」；③`#em-name`／`#em-desc-input`＋「建立並釘上」；
  「再建議一個」`#em-more`；④`#em-skip`——文字動態：這輪釘 0 個＝「不釘，繼續」、≥1＝「完成，繼續」。
- 行為：
  - 釘上（①②③都走 `POST /photos/{id}/entities`）成功 → **窗不關**：加進已釘列表、
    回應的 `entities` 覆寫下拉資料（③自創後清單會 +1）、①若正是剛釘的實體則隱藏、清空③輸入。
  - 「再建議一個」→ `POST /photos/{id}/entity-suggestion`，body `{exclude: 已釘 id ＋ 目前①的 id}` →
    有結果：更新①（顯示並改字）；null：①隱藏＋窗內訊息「沒有其他適合的實體了」。等待期間所有按鈕 disabled。
  - 錯誤（409 重複釘／409 重名／422 空白）一律寫 `#em-error`，**禁 alert**。
  - 出口只有④（實體窗「可略過但不強制」＝有明確出口即可；不裝 Esc／點外，跟 folder modal 行為一致、少一套監聽）。
  - 動態內容一律 textContent；busy 狀態鎖全部按鈕（含 select）。

## 鏈接規則（§2.1 定稿）

- `upload.html`：201 後 `openFolderModal` 的 **onAssigned 與 onClosed 都** →
  `openEntityModal({photoId, entities: body.entities, suggested: body.suggested_entity, onDone: …}）`；
  onDone 後更新結果卡（釘了 N 個實體／未釘）。PDF（P28 的 created[0]）同一條鏈。
- `browse.html` 待決定分頁：`openFolderModal` 的 onAssigned／onClosed 都 → 先 `getJson("/entities")` →
  `openEntityModal({photoId, entities, suggested: null, onDone: function(){ location.reload(); }})`
  （建議不持久化——①要靠使用者按「再建議一個」現算；reload 移到鏈的最尾端）。

## Playwright 實操驗收（真伺服器 :8000＋真 gemma4）

1. 上傳→抽屜窗選資料夾定案→**實體窗自動接著開**；上傳→「稍後再說」→實體窗**照樣開**（§2.1）。
2. 實體清單空時：②整列隱藏、①無建議隱藏，只剩③④；③自建「我的 MacBook」→ 已釘列表出現、窗仍開。
3. 再釘第二個（③）→ 已釘 2 個；④文字變「完成，繼續」；按④→窗關、結果卡顯示釘了 2 個。
4. 重複釘同一個 → 窗內紅字 409、窗不關、已釘列表不變。
5. 「再建議一個」：至少 2 個實體存在時對新照片按 → ①出現（或「沒有其他適合的實體了」——依真模型輸出，兩種都算過，驗的是流程不炸）。
6. 待決定分頁點照片→抽屜窗（無①）→歸檔→實體窗開（無①、可「再建議一個」）→④→回待決定且該照片已消失。
7. `curl` 釘選／再建議端點手打一輪（404／409／422 各一）。
8. 三頁 console 乾淨（僅既有 favicon 噪音）；`pytest -q` 顆數不動。

## 驗收清單

- [ ] 彈窗鏈 1→2 兩條入口（上傳頁／待決定分頁）都通，含「稍後再說」仍續鏈
- [ ] 可連續釘多個；③自創後下拉即時 +1；409／422 紅字在窗內
- [ ] `grep -c "alert(\|confirm(\|prompt(" app/static/*.js` ＝ 0
- [ ] 後端零改動（`git diff app/ --stat` 只有 static/）；全量 pytest 顆數不變
