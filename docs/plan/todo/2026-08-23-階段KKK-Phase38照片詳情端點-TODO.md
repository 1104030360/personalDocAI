# 階段KKK TODO：Phase 38 照片詳情端點 `GET /photos/{photo_id}`

> 日期：2026-08-23　狀態：✅ 完成（見同名 REP；計畫 §4.6 手動看一眼由主 agent 統一做）
> 依據：`docs/plan/unfinish/phase-38-照片詳情端點.md`（逐條照做）＋`docs/design/design4.md` §4.4、D3／D5／D6、§9 第 1〜3 列
> 開工基準（已實測）：`pytest -q` ＝ 358 passed ＋ 2 skipped；`/openapi.json` 運算元 ＝ 19

## 實作邏輯

增量四階段甲的第一步：讓前端能用「一張照片的 id」把**完整說明**一次抓回來，
之後 Phase 39／40 的唯讀彈窗才有東西可畫。

現在的兩支清單端點（`GET /folders/{id}`、`GET /tasks`）刻意只回「畫得出縮圖牆／待辦列」
的最少欄位，這叫**瘦契約**——清單一次可能回幾十筆，每筆都塞完整說明會變慢，
而且 99% 的資料使用者根本沒點開。所以產品負責人選的是「清單維持瘦、**點開再抓一張**」
（design4 §1.2 明文否決了「清單一次帶齊 metadata」）。

這支端點的性格：

- **唯讀**。不看圖、不重算向量、不寫任何東西——`GET` 不該有副作用。
- **零 SQL**。`photo_repository.fetch_photo()` 的 `PHOTO_COLUMNS` 已含 text／四欄 metadata／
  兩個路徑／`uploaded_at`，router 只呼叫它，不自己開連線。
- **只有一個 404 條件**：`fetch_photo` 回 `None`。**檔案在不在磁碟上跟這支無關**——
  「路徑 NULL 或檔案不見了就 404」是 `/image` 與 `/thumbnail` 的規則（那兩支真的要開檔案）；
  這一支只回 JSON，圖載不出來由前端 `<img>` 的 onerror 降級成占位，不該讓整個窗變 404。
- **不外送硬碟路徑**：`original_path` 有值才給網址 `/photos/{id}/image`，沒有就是 `null`；
  縮圖同理。沿用 folders／tasks 端點的既有慣例。
- **刻意不回** embedding（1024 個數字前端用不到）、folder 物件、`suggested_category`、
  釘著的實體清單——那些不是這顆窗要回答的問題（design4 §4.4 明文「不回」）。

`metadata` **重用**既有的 `PhotoMetadata`（四欄、不多不少），不另造四個欄位——
同一張照片經上傳 201 與本端點出來的 metadata 必須逐鍵相同，測試就是這樣比的。

## 步驟（TDD：先紅再綠）

- [x] **紅**：新建 `tests/integration/test_photo_detail.py`，照計畫 §4.1 的表寫七顆
      （名稱逐字照抄）。三個前提：本檔自己把 `get_vlm` 覆寫成「看得懂」的假件
      （conftest 預設是看不懂＝422）、上傳用 `make_png_bytes()` 真圖、
      「沒有原圖的舊照片」用 `insert_photo()` 直寫不走上傳端點。
      防假綠條款：第 3 顆要驗 `detail == "找不到照片"`（不然端點還沒寫時 FastAPI 本來就 404）、
      第 6 顆第一句先 `assert status_code == 200`（不然 404 的 body 也「找不到」那四個字）、
      第 2 顆用「詳情 metadata ＝ 上傳 201 回應 metadata」比對（不手寫期望值——
      上傳一律先進「未分類」，VLM 的建議不落庫）。
- [x] 跑 `pytest tests/integration/test_photo_detail.py -v` 確認**七顆全紅**，輸出留存給 REP。
- [x] **綠**：`app/schemas/photo.py` 檔尾加 `PhotoDetailOut`（六個欄位；檔頭補
      `from datetime import datetime`）。必須排在 `PhotoMetadata` 之後——Python 由上往下讀。
- [x] **綠**：`app/api/routers/photos.py` 加 `GET /photos/{photo_id}`，位置在 `get_photo_image`
      之後、`_record_correction_if_changed` 之前（讀這張照片的三支端點排在一起）；
      import 按字母序把 `PhotoDetailOut` 夾在 `PdfUploadResponse` 與 `PhotoMetadata` 之間；
      檔頭 docstring 補一句。`content_time` 要 `.isoformat()`；`uploaded_at` **不要**轉字串。
- [x] **綠**：`tests/integration/test_ask_three_paths.py::test_端點數不變` 的 `== 19` 改 `== 20`
      （**測試名不改**——它守的是「詢問這一路沒偷加端點」，那件事仍成立），docstring 補一行。
- [x] 跑綠三連：新檔 7 passed → `pytest -q` ＝ **365 passed ＋ 2 skipped** →
      `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同（零外部依賴實證）。
- [x] 計畫 §6 驗收清單逐項核對（openapi 運算元 20、無 `GET /photos`、DELETE 仍 0、
      `test_folders_endpoint.py` 與 `test_tasks.py` 一字未改且全綠、SQL 掃碼測試仍綠、
      `git diff --stat -- app tests` 恰三檔＋`git status --short` 恰一個 `??`）。
- [x] 寫 REP（實作邏輯／步驟／測試方式／遇到的問題與解法／測試結果五區塊）。

## 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 新增 `GET /photos`（列出全部） | design1 禁令仍有效（design4 §1.1 第 3 列、§4.4 末句），只准依 id 讀一張 |
| 改 `GET /folders/{id}` 五鍵摘要、改 `GET /tasks` 瘦契約 | design4 §3「不做」第一條；那兩個測試檔一個字都不准動 |
| 回應放 embedding／folder 物件／suggested_category／硬碟路徑 | design4 §4.4 明文「不回」 |
| 為這支端點新寫 SQL | `fetch_photo()` 已經夠用，router 零 SQL |
| 呼叫 VLM／重算 embedding | 唯讀端點，`GET` 不該有副作用 |
| 動 `docs/spec/` 任何 `.feature` | design4 §3「規格本輪不改」 |
| 建任何 Docker 檔（`compose.yaml`／`Dockerfile`…） | 階段丙的東西，G1 閘門沒過不准建（design4 §0） |
| 起伺服器做計畫 §4.6 的「手動看一眼」 | 埠 8000 有使用者留著的 uvicorn，不要動；主 agent 之後統一做 |
| `git add`／`git commit` | 本增量全程不 commit |

## 執行方式

以 subagent 實作（TDD 鐵序：先寫測試 → 確認紅 → 實作 → 跑綠），主 agent 事後 review。
