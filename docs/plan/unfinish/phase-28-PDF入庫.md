# Phase 28：PDF 入庫（design3.md D7——一頁當成一張圖）

> 🎯 **只做 design3 寫到的事**：接受 PDF、一頁→一張 photo、多頁就多張。
> 不保留 PDF 原始檔（photo 的「原圖」＝該頁渲染出的 PNG）；不做頁數上限、不做加密 PDF 支援。

**目標：** `POST /photos` 接受 `application/pdf`。PDF 逐頁渲染成 PNG，每頁走「看圖→轉向量→寫入未分類→存原圖＋縮圖」的**既有單圖流程**；壞 PDF／零頁→422 什麼都不存；某頁看不懂→跳過該頁繼續。單圖（JPEG/PNG）行為與回應**一字不變**。

**依賴：** `pypdfium2>=5`（純 pip wheel、無系統套件、BSD/Apache 授權；2026-08-21 已 dry-run 確認可裝 5.13.0）。

## 檔案

- 改：`requirements.txt`（+pypdfium2）、`app/core/config.py`（ALLOWED_CONTENT_TYPES + application/pdf）
- 建：`app/services/pdf_service.py`（渲染頁→PNG bytes；唯一碰 pypdfium2 的地方）
- 改：`app/api/routers/photos.py`（抽出 `_ingest_image()`；PDF 分支逐頁呼叫）
- 改：`app/schemas/photo.py`（+`PdfUploadResponse`）
- 改：`docs/spec/features/上傳照片.feature`（+1 條 PDF Rule；核准依據 design3.md D7，檔頭註記）
- 建：`tests/unit/test_pdf_service_unit.py`；改：`tests/fakes.py`（+`make_pdf_bytes()`）、
  `tests/integration/test_photos_upload.py` 或新檔 `tests/integration/test_pdf_upload.py`、`test_upload_feature.py`（掛新 Rule）

## 步驟（先紅再綠）

### 步驟 1：工具與假件

- `uv pip install pypdfium2` ＋ requirements.txt 加註解行。
- `tests/fakes.py` 加 `make_pdf_bytes(pages: int = 1) -> bytes`：用 Pillow 產 `pages` 張純色小圖、
  `save(buffer, format="PDF", save_all=True, append_images=其餘頁)`（Pillow 原生會寫 PDF，測試端不需要 pypdfium2 以外的新依賴）。

### 步驟 2：先紅——單元測試 `tests/unit/test_pdf_service_unit.py`

1. `test_單頁PDF渲染出一張PNG`：`render_pages(make_pdf_bytes(1))` → 長度 1，且 `Image.open` 得開、格式 PNG。
2. `test_三頁PDF渲染出三張`：長度 3。
3. `test_壞檔丟PdfUnreadableError`：`render_pages(b"not a pdf")` → `pytest.raises(pdf_service.PdfUnreadableError)`。

### 步驟 3：綠——`app/services/pdf_service.py`

```python
class PdfUnreadableError(Exception): ...
def render_pages(pdf_bytes: bytes, scale: float = 2.0) -> list[bytes]:
    # pypdfium2：PdfDocument(pdf_bytes)；逐頁 page.render(scale=scale).to_pil() → PNG bytes
    # 開檔失敗（PdfiumError 等）一律轉 PdfUnreadableError；空 PDF（0 頁）也算 unreadable
```

### 步驟 4：先紅——整合測試（TestClient，FakeVLM 看得懂版）

1. `test_上傳三頁PDF建立三筆照片`：POST `file=("scan.pdf", make_pdf_bytes(3), "application/pdf")` → 201；
   回應 `{"pages": 3, "created": [3 筆單圖回應], "skipped_pages": []}`；`count_photos()`＝3；
   每筆 folder 是未分類、有 `suggested_folder`；三筆的原圖／縮圖檔案都在（content_type＝image/png）。
2. `test_壞PDF回422不存任何資料`：b"not a pdf" → 422、`count_photos()`＝0、data/ 無檔案。
3. `test_全部頁看不懂回422不存任何資料`：FakeVLM(understood=False)＋2 頁 → 422、0 筆。
4. `test_單圖上傳回應形狀不變`：PNG 上傳 → 回應鍵集合與 Phase 27 相同（無 pages/created 鍵）。
5. （fakes 註記）FakeVLM 每頁各叫一次 → `calls == 頁數`。

### 步驟 5：綠——router 重構＋PDF 分支

- `_ingest_image(image_bytes, content_type, vlm, embeddings, now, folders) -> UploadResponse`：
  把現有 ②〜⑥ 段原樣搬進去（看不懂仍 raise HTTPException 422——單圖語意不變）。
- `upload_photo`：content_type 是 PDF → `render_pages`（`PdfUnreadableError` → 422「無法讀取 PDF 檔案」）→
  逐頁 try `_ingest_image`（頁 PNG、"image/png"），單頁 422 記入 `skipped_pages` 繼續；
  全部頁都失敗 → 422「PDF 每一頁都無法理解，未儲存任何資料」；否則 201 `PdfUploadResponse`。
- `response_model=UploadResponse | PdfUploadResponse`。

### 步驟 6：規格改版＋BDD

- `上傳照片.feature` 檔頭補一行核准註記（design3.md D7、2026-08-21），新增一條 Rule：
  「上傳 PDF 檔案時，系統將每一頁分別儲存為一張照片」＋Example（三頁 PDF→儲存 3 筆）；
  既有 10 條 Rule 一字不動。`test_upload_feature.py` 掛新 Rule 的 steps（用 make_pdf_bytes）。

### 步驟 7：前端一行＋回歸

- `upload.html`：`accept="image/jpeg,image/png,application/pdf"`；201 分支若有 `created` →
  卡片顯示「PDF 共 N 頁，已入庫 M 頁」、只對 `created[0]` 開彈窗鏈，其餘頁文案導去待決定 tab。
- 全量 `pytest -q` 全綠；零 Ollama 同顆數。

## 驗收清單

- [x] 單元＋整合新測試先紅再綠；全量全綠（152→163）、零 Ollama 同顆數（2026-08-21 階段XX，controller 親自重跑實證）
- [x] 單圖回應與 .feature 既有 Rule 零變動（僅新增 PDF Rule；`test_單圖上傳回應形狀不變` 護欄）
- [x] 壞 PDF／全頁看不懂→422 且資料庫、data/ 皆零殘留
- [x] 部分頁看不懂→入庫其餘頁並回報 skipped_pages（頁碼 1 起算）
- [x] SQL 仍只在 repository；pypdfium2 只在 pdf_service.py 出現（grep 實證）
