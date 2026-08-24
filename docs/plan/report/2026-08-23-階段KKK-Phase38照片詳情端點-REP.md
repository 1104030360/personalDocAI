# 階段KKK REP：Phase 38 照片詳情端點 `GET /photos/{photo_id}`

> 日期：2026-08-23　狀態：✅ 完成（程式＋自動化測試；瀏覽器手動看一眼由主 agent 統一做）
> 對應 TODO：`2026-08-23-階段KKK-Phase38照片詳情端點-TODO.md`
> 計畫：`docs/plan/unfinish/phase-38-照片詳情端點.md`；design：`design4.md` §4.4、D3／D5／D6、§9 第 1〜3 列
> 開工基準（實測）：358 passed ＋ 2 skipped、openapi 運算元 19 → 收工：**365 passed ＋ 2 skipped、運算元 20**

## 實作邏輯

增量四階段甲第一步：讓前端用「一張照片的 id」把完整說明一次抓回來，Phase 39／40 的
唯讀彈窗才有東西可畫。清單端點（`GET /folders/{id}`、`GET /tasks`）維持**瘦契約**，
「點開再抓一張」——design4 §1.2 明文否決了「清單一次帶齊 metadata」。

端點的四個性格，全部照計畫骨架落地：

1. **唯讀**——不看圖、不重算向量、不寫任何東西。`GET` 不該有副作用。
2. **零 SQL**——`PHOTO_COLUMNS` 已含 text／四欄 metadata／兩個路徑／`uploaded_at`，
   router 只呼叫 `photo_repository.fetch_photo()`，沒有新增任何 SQL。
3. **只有一個 404 條件**——`fetch_photo` 回 `None`。`_send_photo_file` 那三個 404 條件
   （沒這列／路徑 NULL／檔案不在）**刻意不照抄**：那是「開圖檔」的規則，這一支只回 JSON。
   圖載不出來由前端 `<img>` onerror 降級成占位，不該讓整個彈窗變 404。
4. **不外送硬碟路徑**——`original_path`／`thumbnail_path` 有值才換算成網址，
   沒有就是 `null`（舊照片前端畫灰底占位）。

`metadata` 重用既有 `PhotoMetadata`（四欄不多不少），所以同一張照片經上傳 201 與本端點
出來的 metadata 必須逐鍵相同——第 2 顆測試就是這樣比的。
刻意不回 embedding／folder 物件／`suggested_category`／實體清單（design4 §4.4 明文）。

## 步驟（TDD 鐵序）

1. 寫 TODO。
2. 新建 `tests/integration/test_photo_detail.py` 七顆（名稱逐字照計畫 §4.1 的表）。
3. **跑紅**（證據見下）→ 七顆全紅，無一顆意外變綠。
4. `app/schemas/photo.py` 檔尾加 `PhotoDetailOut`（六欄），檔頭補 `from datetime import datetime`。
5. `app/api/routers/photos.py` 加 `GET /photos/{photo_id}`，位置在 `get_photo_image` 之後、
   `_record_correction_if_changed` 之前（讀這張照片的三支端點排在一起）；
   import 按字母序夾在 `PdfUploadResponse` 與 `PhotoMetadata` 之間；檔頭 docstring 補一句。
6. `test_ask_three_paths.py::test_端點數不變` 的 `== 19` 改 `== 20`（**測試名不改**）＋docstring 補一行。
7. 跑綠三連 → 驗收清單逐項核對。

## 測試方式

七顆整合測試，走 `TestClient` 打真端點、連測試庫 `PersonalDocAI_test`
（conftest 三道 autouse 安全網照舊：`reset_tables`／`wire_fake_ai`／`isolated_data_dir`）。

三個前提照計畫處理：

- conftest 給 `get_vlm` 的預設是 `FakeVLM()`＝`understood=False`（直接上傳只會 422），
  所以本檔自帶 `autouse` fixture 覆寫成「看得懂」的 `收據理解`，
  **參數列寫 `wire_fake_ai`** 保證排在 conftest 那條之後、測後由它統一 `clear()`。
- 「預期上傳成功」一律用 `make_png_bytes()` 真圖（假位元組會在縮圖那步被 Pillow 擋下）。
- 「沒有原圖的舊照片」用 `photo_repository.insert_photo()` 直寫、不走上傳端點，
  `original_path`／`thumbnail_path` 自然是 NULL；`embedding` 用 `FakeEmbeddings()` 現算一條。

### 防假綠條款（計畫特別標的三條，實測都發揮作用）

| 顆 | 條款 | 紅階段實際訊息 |
|---|---|---|
| 3 | 不能只驗 404，要驗 `detail == "找不到照片"` | `assert 'Not Found' == '找不到照片'` ← 沒這句就從頭綠到尾 |
| 6 | 第一句先 `assert status_code == 200` | 停在那一句（`{"detail":"Not Found"}`）← 沒這句，404 body 也「找不到」那四個字 |
| 2 | 用「詳情 metadata ＝ 上傳 201 metadata」比，不手寫期望值 | 上傳一律先進「未分類」，VLM 建議不落庫，手寫 `"收據"` 會錯 |

## 遇到的問題與解法

本 phase **零意外**：計畫的程式骨架、插入位置、測試表逐條可用，沒有需要偏離的地方，
產品碼與既有測試也沒有任何連帶修改。三件值得記錄的判斷：

- **路徑撞車是錯覺**（計畫 §7 陷阱 1）：新增 `GET /photos/{photo_id}` 不會吃掉
  `/photos/7/image`——預設 `{參數}` 只吃「一段、不含斜線」的字，是路徑形狀不同，不是靠先後順序。
  實測 openapi 四條 `/photos*` 路徑並存、`/image` 與 `/thumbnail` 的既有測試全綠。
  **沒有**用 `{photo_id:path}`（那個轉換器會連斜線一起吃，才會真的撞車）。
- **`content_time` 要 `.isoformat()`、`uploaded_at` 不要**：前者 DB 給 `date` 物件而
  `PhotoMetadata.content_time` 宣告 `str | None`；後者宣告 `datetime`，Pydantic 自己序列化。
- **Lint**：`test_photo_detail.py` 有 2 條 Flake8「line too long（>79）」。專案沒有
  flake8／ruff／pyproject 設定，且既有 `app`＋`tests` 已有 1889 行超過 79 字元，
  79 是 linter 預設值而非本專案慣例，故維持與周邊程式一致的寫法。
  `photos.py` 的 basedpyright 錯誤全為既有（無法解析 fastapi 匯入、`assign_folder` 的
  `folder` 可能未繫結），**新增區段零錯誤**。

## 測試結果

### 紅階段（實作前，`pytest tests/integration/test_photo_detail.py`）

```text
tests/integration/test_photo_detail.py:66:  AssertionError: {"detail":"Not Found"}
tests/integration/test_photo_detail.py:91:  KeyError: 'metadata'
tests/integration/test_photo_detail.py:106: AssertionError: assert 'Not Found' == '找不到照片'
tests/integration/test_photo_detail.py:127: AssertionError: {"detail":"Not Found"}
tests/integration/test_photo_detail.py:146: AssertionError: {"detail":"Not Found"}
tests/integration/test_photo_detail.py:163: AssertionError: {"detail":"Not Found"}
tests/integration/test_photo_detail.py:173: AssertionError: assert '/photos/{photo_id}' in {...}
7 failed, 1 warning in 0.58s
```

### 綠階段

| 指令 | 結果 |
|---|---|
| `pytest tests/integration/test_photo_detail.py -v` | **7 passed** |
| `pytest -q` | **365 passed ＋ 2 skipped**（358 ＋ 7，計畫預期值） |
| `OLLAMA_BASE_URL=http://localhost:9 pytest -q` | **365 passed ＋ 2 skipped**（同顆數＝零外部依賴實證） |

### 計畫 §6 驗收清單

| 項目 | 結果 |
|---|---|
| 七顆先紅後綠 | ✅ 紅 7／綠 7，紅階段訊息如上 |
| `pytest -q` ＝ 365 passed ＋ 2 skipped | ✅ |
| `OLLAMA_BASE_URL` 指死埠同顆數 | ✅ 365 passed ＋ 2 skipped |
| openapi 運算元 ＝ 20 | ✅ 實測 20 |
| `"get" not in paths["/photos"]`（不做列出全部） | ✅ True |
| openapi DELETE 動詞仍 0 | ✅ 實測 0；`test_openapi裡沒有任何DELETE動詞` PASSED |
| `test_folders_endpoint.py`／`test_tasks.py` 一字未改且全綠 | ✅ `git status --short` 無輸出；兩檔 19 passed |
| 回應搜不到 `data/`／`original_path`／`thumbnail_path`／`embedding` | ✅ 第 6 顆把關 |
| router 零 SQL | ✅ `test_SQL只出現在repository與db層` PASSED；只呼叫 `fetch_photo()` |
| 只動四個檔 | ✅ `git diff --stat -- app tests` 恰三檔（photos.py router／photo.py schemas／test_ask_three_paths.py）；`git status --short` 另有一個 `?? tests/integration/test_photo_detail.py` |
| 2 skipped 未被動到 | ✅ 仍是那兩條 `@未實作` 規格例（摘標屬產品負責人） |
| `docs/spec/` 未動 | ✅ `git status --short -- docs/spec` 無輸出 |
| 未建任何 Docker 檔（G1 閘門前禁止） | ✅ 無 `compose`／`Dockerfile`／`.dockerignore` |

### 刻意未做

- 計畫 §4.6「手動看一眼」（起 uvicorn ＋ curl 正式庫一張照片）：埠 8000 有使用者留著的
  伺服器，依指示不動、不自起，由主 agent 之後統一做。這一步計畫本身也註明「可選、不是驗收條件」。
- 未 `git add`／`git commit`（本增量全程不 commit）。
