# 2026-08-21 階段XX：Phase 28 PDF 入庫——REP

## 實作邏輯

design3.md D7「接受格式加 PDF；一頁當成一張圖、多頁就多張」。核心手法＝**不開第二套入庫邏輯**：
新模組 `app/services/pdf_service.py`（全系統唯一碰 pypdfium2 的地方）把 PDF 逐頁渲染成 PNG bytes，
router 把既有單圖流程原樣抽成 `_ingest_image()`，PDF 分支逐頁呼叫——每頁存的原圖就是渲染出的 PNG
（content_type=image/png），讀圖端點與縮圖完全不必改。PDF 原始檔不保留（design3 沒寫就不做）。

## 步驟

1. 裝 `pypdfium2>=5.13`（純 wheel、無系統套件）入 requirements.txt。
2. TDD 三輪先紅再綠：unit（渲染單頁／三頁／壞檔丟 `PdfUnreadableError`，RED＝ImportError）→
   integration 7 顆（三頁入庫、壞檔 422 零殘留、全頁看不懂 422、部分頁跳過、pages 不變式×2、
   單圖回應形狀護欄；RED＝KeyError 'pages'）→ BDD（feature 新 Rule，RED＝StepDefinitionNotFoundError）。
3. router：`upload_photo` 只剩「格式檢查→讀 bytes→分流」；`_ingest_pdf` 只吞單頁 422（記 skipped_pages），
   其他例外照舊往外丟 500；一頁都沒成功→422 什麼都不存；`response_model=UploadResponse | PdfUploadResponse`。
4. 規格：`上傳照片.feature` 檔頭註記 design3.md D7 核准、檔尾追加一條 PDF Rule（既有 10 條一字不動）。
5. 前端：`accept` 加 PDF；201 回應帶 `created`＝PDF → 摘要「共 N 頁已入庫 M 頁（第 X 頁看不懂已跳過）」、
   彈窗只為第一頁開（20 頁掃描不逼人連按 20 次），其餘頁導去待決定分頁；單圖路徑文案與 Phase 27 一字不差。

## 測試方式與結果

- 實作者（opus subagent）：RED→GREEN 證據三輪齊全；全量 **163 passed**（152＋11）。
- **Controller 親自複驗**：`pytest -q`＝163、`OLLAMA_BASE_URL=http://localhost:9 pytest -q`＝163（零外部依賴）；
  逐檔 review 全部 diff；`grep` 實證 pypdfium2 只在 pdf_service.py；端點仍 9（openapi 清點，非 app.routes）。
- 前端未跑瀏覽器實操（本 phase 純後端＋一頁小改；Playwright 統一在前端 phase 與總驗收階段跑）。

## 遇到的問題與解法

1. 實作者自我審查修掉五處（未使用 import、重複文案、搬移時弄丟的註解、storage_service 過期註解、
   upload.html 錯誤註解過期）——見 task-28 報告 §4。
2. **規格內部措辭張力**：Rule U1 標題與 415 訊息仍寫「JPEG、PNG」，新 Rule 11 收 PDF。
   測試層無矛盾（U1 的 text/plain 例子仍 415），文字修訂**留給產品負責人**（U1 屬既有 Rule，本輪無權動）。
3. PDF 中途遇非 422 錯誤（如存檔失敗）會保留已成功的前幾頁——這是拆解裁定的語意
   （清理停留在單頁層級，與單圖一致；「全有全無」需跨頁補償，本 phase 刻意不做）。

## 備註

- 新增檔 3、修改檔 9；不 commit。`make_pdf_bytes()` 用 Pillow 原生 PDF 輸出，測試端零新依賴。
