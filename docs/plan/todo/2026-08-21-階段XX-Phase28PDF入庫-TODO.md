# 2026-08-21 階段XX：Phase 28 PDF 入庫——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-28-PDF入庫.md`：`POST /photos` 接受 `application/pdf`，
一頁渲染成一張 PNG、每頁走既有單圖流程（design3.md D7「一頁當成一張圖；多頁就多張」）。
單圖行為與回應一字不變。

## 實作邏輯

- 渲染器選 **pypdfium2**（純 pip wheel、無系統套件、BSD/Apache；dry-run 實測可裝 5.13.0），
  只封在新檔 `app/services/pdf_service.py`。
- router 把既有 ②〜⑥ 段抽成 `_ingest_image()`（行為不變），PDF 分支逐頁呼叫；
  某頁 VLM 看不懂＝只跳過該頁（skipped_pages 回報），全部頁失敗＝422 什麼都不存。
- 回應：單圖形狀不變；PDF 回 `{pages, created:[單圖回應…], skipped_pages}`（`response_model` 用 Union）。
- 規格：`上傳照片.feature` 依 design3.md D7 核准**新增一條 PDF Rule**（檔頭註記核准來源，
  比照 Phase 20 依 design1 改版先例）；既有 10 條 Rule 一字不動。
- 測試工具：`make_pdf_bytes(pages)` 用 Pillow 原生 PDF 輸出（測試端零新依賴）。

## 步驟（TDD 先紅再綠）

- [x] 1. 裝 pypdfium2＋requirements.txt
- [x] 2. 先紅：`tests/unit/test_pdf_service_unit.py`（單頁／三頁／壞檔三顆）
- [x] 3. 綠：`pdf_service.render_pages()`＋`PdfUnreadableError`
- [x] 4. 先紅：`tests/integration/test_pdf_upload.py`（三頁入庫／壞檔 422／全頁看不懂 422／單圖形狀不變……共 7 顆）
- [x] 5. 綠：router 抽 `_ingest_image` ＋ PDF 分支＋`PdfUploadResponse`
- [x] 6. `上傳照片.feature` 加 PDF Rule＋`test_upload_feature.py` 掛 steps
- [x] 7. `upload.html` accept＋PDF 結果卡（彈窗只跑第一頁）
- [x] 8. 全量＋零 Ollama 回歸（163／163）；親自 review diff（通過，見 REP）

## 執行方式

實作由 subagent（opus）依計畫檔執行（TDD 紅綠證據寫入報告）；完成後由我親自 review diff 與重跑驗證（產品負責人指示的分工）。全程不 commit。
