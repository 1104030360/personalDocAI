# 2026-08-21 階段AAA：Phase 31 實體彈窗——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-31-實體彈窗.md`：新增 `app/static/entity_modal.js`（①採用建議②改選現有
③自創④不釘＋「再建議一個」，可連續釘多個），上傳頁與瀏覽頁待決定分頁的抽屜彈窗結束後
（**含「稍後再說」——design3 §2.1 鏈仍繼續**）接著開實體窗。純前端 phase：後端零改動、pytest 顆數不變（207）。

## 實作邏輯

- 彈窗程式碼一站一份原則：實體彈窗獨立 `entity_modal.js`（id 用 em- 前綴；**樣式 class 沿用 fm-***
  ＝三個彈窗共用的視覺語言，style.css 檔頭註記，零重複 CSS）。
- 釘上（①②③都打 `POST /photos/{id}/entities`）成功**窗不關**：已釘列表 +1、回應的 entities 覆寫下拉
  （③自創清單即時 +1）、④按鈕文字 0 釘＝「不釘，繼續」／≥1＝「完成，繼續」。
- 「再建議一個」打 `POST /photos/{id}/entity-suggestion`（exclude＝已釘＋目前①）；null→①隱藏＋窗內訊息。
- 錯誤一律寫 `#em-error`（禁 alert）；動態內容 textContent；busy 鎖全部按鈕。
- 鏈接：upload.html 的 onAssigned／onClosed 都 → openEntityModal（entities／suggested 取自上傳回應）；
  browse.html 待決定分頁 → 先 GET /entities → openEntityModal（suggested:null）→ onDone 才 reload。
- P33 會在 entity 的 onDone 接待辦窗——onDone 保持乾淨的單一掛點。

## 步驟

- [x] 1. `entity_modal.js`（openEntityModal 介面照計畫檔定稿）
- [x] 2. `upload.html` 鏈 1→2（單圖與 PDF created[0] 同一條；`接著釘實體()` 為 P33 待辦窗的乾淨掛點）
- [x] 3. `browse.html` 待決定分頁鏈 1→2（開窗前現抓 GET /entities；reload 移到鏈尾）
- [x] 4. `style.css` 檔頭註記 fm-* 為共用彈窗樣式；`#em-title`／`#em-primary` 掛進既有 id 選擇器（零複製）
- [x] 5. node --check＋node 存根五情境實跑（空清單開窗／釘後窗不關與清單更新／409 紅字／再建議 exclude 正確／④ onDone）；`pytest -q` 仍 207；alert 掃碼 0
- [x] 6. controller 親自實作與檢查（Playwright 實操統一在總驗收階段跑）

## 執行方式（實際）

原派 subagent（opus）兩次均異常（一次被中止、一次 34 分鐘零產出卡死）——改由 controller **親自實作**
（規格與前端脈絡皆在手，實作＋自我驗證一次完成）。瀏覽器實操於總驗收階段親自跑。不 commit。
