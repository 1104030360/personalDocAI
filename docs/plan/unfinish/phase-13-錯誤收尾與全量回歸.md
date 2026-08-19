# Phase 13：錯誤路徑收尾與全量回歸

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 把 design.md「錯誤處理總表」的每一列都補上測試、確認沒有多做規格外的東西，最後跑一次全量回歸與中英雙語真模型煙霧測試——**後端到此完成**（網頁介面在 Phase 14）。

---

## 前置條件

- 需要已完成的 phase：**Phase 12**（12 條 Rule 全綠、測試累計 38）。
- 環境：測試資料庫可用；最後的煙霧測試需要 Ollama 真的在跑。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

12 條 Rule 綠燈只證明「規格說要有的行為都有了」。這個 phase 補上另一半：**規格沒明講、但 design.md 已經裁決的錯誤路徑**，以及**規格明說不要做的事真的沒做**。

三件事：
1. 幫錯誤處理總表的七列各補一個測試（有些已經被規格測試覆蓋，補上還沒被覆蓋的）。
2. 逐條核對「明確不做」的清單，確認沒有偷偷長出第三個功能、沒有長出 design.md 裁掉的空殼目錄。
3. 跑一次全量回歸，再用真模型手動走一遍兩個 API——**中文與英文各走一次**。

**兩個關鍵名詞**（「全量回歸」是本 phase 首次出現；「煙霧測試」在 Phase 5、8 出現過，這裡是它最重要的一次上場，一起再解釋一次）：

- **全量回歸（regression test）**：把到目前為止「所有」寫過的測試從頭再跑一遍，確認新加的程式碼沒有弄壞任何舊功能。「回歸」指的是曾經好的東西又壞回去——回歸測試就是抓這種事。
- **煙霧測試（smoke test）**：最粗略的「通電看看會不會冒煙」檢查——用真的模型、真的照片，手動把主要流程走一遍，確認整台機器組起來真的會動。

---

## ASCII 圖：錯誤處理總表

```
 情境                                  依據          HTTP   行為
 ─────────────────────────────────────────────────────────────────────────
 上傳非圖片格式                        已釐清        415    不呼叫 VLM、不寫入
 VLM 看不懂／呼叫失敗                  已釐清        422    什麼都不存
 檔案太大                              已釐清無上限   —     沒有這個錯誤路徑（刻意不寫）
 問題缺漏／空字串                      規格未定義     422    框架既有行為
 路由 AI 失敗                          已釐清        200    fallback 語意查詢，流程繼續
 查無相關照片                          已釐清        200    AI 回覆查無、ids 為 []
 DB 掛了／embedding 呼叫失敗           規格未定義     500    不吞錯，log 留原始錯誤
 ─────────────────────────────────────────────────────────────────────────
        ↑ 本 phase 要讓「每一列都有一個測試指著它」
```

---

## 逐步驟操作

### 步驟 1：建立 `tests/test_error_paths.py`

```python
"""design.md §10 錯誤處理總表的逐列驗證。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import (
    get_answerer,
    get_embeddings,
    get_now,
    get_router,
    get_vlm,
)
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter, FakeVLM

NOW = datetime(2026, 8, 18, 10, 0)

TARGET_RECEIPT = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據", location="Target",
    items=["可樂", "洋芋片"], content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_fakes():
    """把五種假件全部接上 app——真 AI 與真時鐘都不會被呼叫，測試結果才可預期。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_answerer] = lambda: FakeAnswerLLM()
    app.dependency_overrides[get_now] = lambda: NOW
    yield
    app.dependency_overrides.clear()


# 下面測試用的 `client` fixture 來自 tests/conftest.py（Phase 5 建立），直接沿用。


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---- 415：上傳非圖片格式 ----
def test_非圖片格式回415且不寫入(client):
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415
    assert response.json()["detail"] == "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"
    assert photo_repository.count_photos() == 0


# ---- 422：VLM 看不懂 ----
def test_vlm看不懂回422且不寫入(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post("/photos", files={"file": ("a.png", b"\x89PNG", "image/png")})

    assert response.status_code == 422
    assert response.json()["detail"] == "VLM 無法理解照片內容，未儲存任何資料"
    assert photo_repository.count_photos() == 0


# ---- 沒有「檔案太大」這個錯誤路徑 ----
def test_大檔案照樣可以上傳(client):
    大檔案 = b"\x89PNG\r\n\x1a\n" + b"0" * (12 * 1024 * 1024)   # 約 12 MB

    response = client.post("/photos", files={"file": ("big.png", 大檔案, "image/png")})

    assert response.status_code == 201, "規格明訂不設檔案大小上限"


def test_程式碼裡沒有任何檔案大小上限檢查():
    # 用「這個測試檔的位置」推回專案根目錄，跑測試時不管人在哪個目錄都找得到檔案
    專案根目錄 = Path(__file__).resolve().parent.parent
    source = (
        (專案根目錄 / "app" / "api" / "routers" / "photos.py").read_text(encoding="utf-8")
        + (專案根目錄 / "app" / "services" / "vlm_service.py").read_text(encoding="utf-8")
    )
    for 關鍵字 in ("max_size", "MAX_SIZE", "413", "too large"):
        assert 關鍵字 not in source, f"不該出現大小限制相關程式碼：{關鍵字}"


# ---- 422：問題缺漏／空字串（框架既有行為）----
# parametrize：同一個測試函式跑兩組輸入（缺 question／空字串），pytest 會算成 2 個測試
@pytest.mark.parametrize("payload", [{}, {"question": ""}])
def test_問題缺漏或空字串回422(client, payload):
    assert client.post("/ask", json=payload).status_code == 422


# ---- 200：路由 AI 失敗仍然回答 ----
def test_路由失敗仍回200並走語意查詢(client):
    class 一定壞掉的Router:
        def route(self, question):
            raise RuntimeError("模型爆炸了")

    app.dependency_overrides[get_router] = lambda: 一定壞掉的Router()

    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    assert response.json()["search_mode"] == "vector semantic search"


# ---- 200：查無相關照片（中英文各驗一次語言跟隨）----
def test_查無照片回200且不編造(client):
    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    body = response.json()
    assert response.status_code == 200
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


def test_英文提問查無照片時用英文回覆(client):
    """雙語：查無結果的回覆語言也要跟隨提問語言。"""
    response = client.post(
        "/ask", json={"question": "What drinks did I buy recently?"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["retrieved_photo_ids"] == []
    assert "No matching photos found." in body["answer"]


# ---- 500：embedding 呼叫失敗（例如 Ollama 沒開）不吞錯 ----
def test_embedding失敗回500(不擲出例外的client):
    class 壞掉的Embeddings:
        def embed_query(self, text):
            raise RuntimeError("Ollama 沒有回應")

        def embed_documents(self, texts):
            raise RuntimeError("Ollama 沒有回應")

    app.dependency_overrides[get_embeddings] = lambda: 壞掉的Embeddings()

    response = 不擲出例外的client.post(
        "/photos", files={"file": ("a.png", b"\x89PNG", "image/png")}
    )

    assert response.status_code == 500
    assert photo_repository.count_photos() == 0, "失敗時不可以留下半筆資料"


# ---- 500：資料庫掛掉不吞錯 ----
def test_資料庫掛掉回500(不擲出例外的client, monkeypatch):
    # monkeypatch：pytest 內建 fixture，暫時改掉某個屬性，測試結束會自動還原。
    # db/session.py 每次連線都重新讀 config.DATABASE_URL（Phase 3 的寫法），
    # 所以這裡改了就會生效。
    monkeypatch.setattr(
        config, "DATABASE_URL", "postgresql://localhost:5433/根本不存在的資料庫"
    )

    response = 不擲出例外的client.post("/ask", json={"question": "隨便問"})

    assert response.status_code == 500
```

### 步驟 2：核對「明確不做」的清單

執行這段檢查腳本，確認沒有多做規格外的東西：

```bash
cd /Users/linjunting/personalDocAI

echo "== 端點只能有兩個（外加 /health）=="
grep -rnE "@router\.(get|post|put|patch|delete)" app/api/routers/
grep -nE "@app\.(get|post|put|patch|delete)" app/main.py

echo "== 不得有刪除／瀏覽／編輯照片的端點 =="
grep -rnE "@router\.(delete|put|patch)|@app\.(delete|put|patch)" app/ || echo "OK：沒有"

echo "== 不得儲存原始照片檔（不該出現寫檔）=="
grep -rnE "open\(|write_bytes|shutil|aiofiles" app/ --include="*.py" || echo "OK：沒有寫檔"

echo "== 不得有使用者／帳號相關欄位 =="
grep -rniE "user|account|login|token|password" app/ --include="*.py" db/schema.sql || echo "OK：沒有"

echo "== 不得有非同步佇列／處理狀態 =="
grep -rniE "celery|rq |queue|status_column|processing_state" app/ --include="*.py" || echo "OK：沒有"

echo "== metadata 只能有四個欄位 =="
python -c "from app.schemas.photo import PhotoMetadata; print(sorted(PhotoMetadata.model_fields))"

echo "== 不得使用雲端模型服務 =="
grep -rniE "anthropic|openai|voyage|api_key|API_KEY" app/ --include="*.py" requirements.txt || echo "OK：全本地"

echo "== design.md 裁掉的空殼不得存在 =="
# 逐一檢查：存在就印「違規」，不存在就印「OK」（ls 一次列三個的寫法在「部分存在」時輸出會混淆，不用）
for p in app/models app/core/security.py alembic; do
  if [ -e "$p" ]; then echo "違規：$p 存在"; else echo "OK：$p 不存在"; fi
done

echo "== SQL 只能出現在 repository =="
grep -rlnE "SELECT |INSERT INTO|UPDATE |DELETE FROM|TRUNCATE TABLE" app/ --include="*.py"

echo "== 條件查詢用 ILIKE（雙語）=="
grep -cE "ILIKE %\(" app/repositories/photo_repository.py

echo "== 不得有全域例外捕捉（500 要不吞錯，見常見問題 Q3）=="
grep -rnE "exception_handler" app/ --include="*.py" || echo "OK：沒有全域捕捉"
```

### 步驟 3：把 `CLAUDE.md` 的「指令」章節整理成最終版

`CLAUDE.md` 現在有兩處和指令有關的內容：開頭有一節佔位的「## 指令」（還寫著「尚無可執行的 build / lint / test 指令」），Phase 8 步驟 6 又在檔尾補過一段「## 指令（實作後回填）」。後端完成了，把兩處**合併成一節**。

用編輯器打開 `/Users/linjunting/personalDocAI/CLAUDE.md`：

1. 刪掉檔尾 Phase 8 加的整段「## 指令（實作後回填）」。
2. 把開頭「## 指令」一節的內容（原本那句「尚無可執行的…」）換成下面這樣（外框用**四個反引號**，因為裡面本身有一組三反引號的區塊）：

````markdown
## 指令

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 啟動服務
uvicorn app.main:app --reload --port 8000

# 全部自動化測試（12 條 Rule 驗收＋雙語、單元與錯誤路徑測試；全程使用假件，不需要 Ollama）
pytest -q

# 只跑兩份規格檔（12 條 Rule、14 個例子）
pytest tests/test_upload_feature.py tests/test_ask_feature.py -v

# 手動煙霧測試（需要 Ollama 真的在跑；不進 CI）
python scripts/check_embedding_dim.py

# 資料庫建表
psql -d visual_memory      -f db/schema.sql   # 正式庫
psql -d visual_memory_test -f db/schema.sql   # 測試庫
```
````

3. 順手把 `CLAUDE.md` 裡已經過時的「現況：greenfield……沒有任何程式碼」與「`docs/design/design.md` 目前是空檔」等敘述改成現況（後端程式碼已完成、design 已定稿到 v4）——它們描述的是動工前的狀態，留著會誤導之後打開這個專案的人（或 AI）。

### 步驟 4：全量回歸

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

### 步驟 5：真模型手動煙霧測試（中英雙語，最後的實機確認）

這一步**全程手動**：在終端機照著打、用眼睛核對結果就好，**不要寫成 pytest 測試、不進 CI**。design.md §11 明訂真模型只做少量手動煙霧測試（**含至少一個英文提問例子**）——真 AI 的輸出不是決定論的，放進自動化測試會時好時壞（Phase 8 步驟 6 已立下這條界線，這裡再確認一次）。

```bash
# 0) 前置：Ollama 在跑、正式資料庫已建表
#    注意：schema.sql 開頭是 DROP TABLE IF EXISTS，重跑會「清空重建」資料表——
#    正好把 Phase 8 煙霧測試留下的舊資料清掉，從乾淨狀態開始
brew services start ollama
psql -d visual_memory -f db/schema.sql

# 1) 啟動服務（視窗 A；先 cd ＋啟用虛擬環境）
uvicorn app.main:app --port 8000
```

```bash
# 視窗 B（一樣先 cd ＋啟用虛擬環境）

# 2) 上傳一張真的照片
screencapture -x /tmp/real_photo.png
curl -s -X POST http://localhost:8000/photos \
  -F "file=@/tmp/real_photo.png;type=image/png" | python -m json.tool

# 3) 上傳一個非圖片（應該 415）
echo hi > /tmp/x.txt
curl -i -s -X POST http://localhost:8000/photos \
  -F "file=@/tmp/x.txt;type=text/plain" | head -1

# 4) 條件型詢問（中文）
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"有哪些在 Target 拍的收據？"}' | python -m json.tool

# 5) 語意型詢問（中文）
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"我最近買過什麼飲料？"}' | python -m json.tool

# 6) 語意型詢問（英文）★ 雙語煙霧測試
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"What drinks did I buy recently?"}' | python -m json.tool

# 7) 條件型詢問（英文）★ 雙語煙霧測試
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"Which receipts were taken at Target?"}' | python -m json.tool

# 8) 模糊問題（應該 fallback 到語意查詢）
curl -s -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"幫我找找之前那個"}' | python -m json.tool
```

---

## 驗收標準

1. **錯誤路徑測試全綠**
   ```bash
   pytest tests/test_error_paths.py -v
   ```
   預期最後一行：`11 passed`（檔案裡是 10 個測試函式，其中「問題缺漏或空字串」帶 2 組參數，pytest 會算成 2 個測試）

2. **全量回歸全綠**
   ```bash
   pytest -q
   ```
   預期：`49 passed`（**測試累計數：49**）
   組成：
   | 檔案 | 個數 |
   |---|---|
   | `test_upload_feature.py`（規格 U1〜U7） | 7 |
   | `test_ask_feature.py`（規格 Q1〜Q5） | 7 |
   | `test_indexing.py` | 3 |
   | `test_upload_bilingual.py` | 1 |
   | `test_retrieval.py` | 10 |
   | `test_workflow_route.py` | 5 |
   | `test_ask_endpoint.py` | 5 |
   | `test_error_paths.py` | 11 |
   | **合計** | **49** |
   （若你在前面 phase 多寫或少寫了測試，數字會不同——以實際數字為準，驗收重點是「恰好比 Phase 12 的 38 多出本 phase 的 11 條錯誤路徑測試，而且全部通過」。）

3. **12 條 Rule 全部有對應的測試名稱**
   ```bash
   pytest tests/test_upload_feature.py tests/test_ask_feature.py -v | grep -cE "PASSED"
   ```
   預期輸出：`14`（兩份規格共 14 個例子）。

4. **雙語測試全部在**
   ```bash
   pytest -k "英文 or 大小寫" -v | tail -3
   ```
   預期最後一行：`7 passed, 42 deselected`——**7 個**雙語測試被選中且全部通過：英文照片上傳（P07）、英文合併格式（P07）、地點大小寫與物品大小寫（P09）、英文路由（P10）、英文回答（P11）、英文查無回覆（P13）。

5. **「明確不做」的檢查全數通過**
   步驟 2 的腳本輸出中：
   - 端點清單只有 `@router.post("/photos"...)`、`@router.post("/ask"...)`、`@app.get("/health")` 三行
   - 刪除／瀏覽／編輯端點：`OK：沒有`
   - 寫檔：`OK：沒有寫檔`
   - 使用者欄位：`OK：沒有`
   - 佇列／狀態：`OK：沒有`
   - metadata 欄位：`['category', 'content_time', 'items', 'location']`（按字母排序恰好四個，不多不少）
   - 雲端模型：`OK：全本地`
   - 空殼目錄：三行都是 `OK：… 不存在`
   - SQL 檔案清單：只有 `app/repositories/photo_repository.py` 一行
   - ILIKE 計數：`3`（category／location／unnest 三處 SQL）
   - 全域例外捕捉：`OK：沒有全域捕捉`

6. **真模型煙霧測試逐項符合預期**
   | 步驟 | 預期 |
   |---|---|
   | 2 上傳真照片 | 回 `{"id":…,"text":"…","metadata":{四欄位}}` |
   | 3 上傳非圖片 | 第一行 `HTTP/1.1 415 Unsupported Media Type` |
   | 4 條件型詢問（中） | `search_mode` 為 `"metadata search"`，`answer` 是中文 |
   | 5 語意型詢問（中） | `search_mode` 為 `"vector semantic search"`，`answer` 是中文 |
   | 6 語意型詢問（英） | 回 200，`answer` 是**英文**句子 |
   | 7 條件型詢問（英） | 回 200，`answer` 是**英文**句子（`retrieved_photo_ids` 可能是空的——見常見問題 Q6） |
   | 8 模糊問題 | 回 200，`search_mode` 為 `"vector semantic search"` |

7. **停掉 Ollama，所有自動化測試仍全綠**
   ```bash
   brew services stop ollama && pytest -q && brew services start ollama
   ```
   預期：`49 passed`。（`&&` 遇到失敗會中斷——若 pytest 沒全過，Ollama 會停在關閉狀態，修好後記得手動 `brew services start ollama`。）

---

## 常見問題

**Q1：`test_資料庫掛掉回500` 沒有回 500，而是拋出例外。**
`TestClient` 預設會把伺服器內部例外往外丟。要驗證 500 必須用 `TestClient(app, raise_server_exceptions=False)`（範例已經這樣寫）。

**Q2：`test_大檔案照樣可以上傳` 很慢或記憶體吃緊。**
把 12 MB 調小一點（例如 3 MB）也能達到相同目的——重點是證明「沒有大小上限這個錯誤路徑」，不是壓力測試。

**Q3：要不要加一個「捕捉所有例外並回友善訊息」的處理器？**
不要。design.md 明訂 DB 掛掉／embedding 失敗要**不吞錯**，讓框架回 500 並在 log 留原始錯誤。加了全域捕捉會讓真正的問題被藏起來。至於「log 留原始錯誤」這半句：不用寫任何程式——只要不加全域捕捉，uvicorn 就會自動把原始 traceback 印在伺服器 log；步驟 5 手動測試時在視窗 A 就能親眼看到（自動化測試驗的是「回 500、不吞錯」這半句）。

**Q4：步驟 2 的寫檔檢查，為什麼只掃 `app/` 不掃 `tests/`？**
因為「不得儲存原始照片檔」限制的是**產品程式碼**。測試檔讀寫檔案是正常的（像 `test_程式碼裡沒有任何檔案大小上限檢查` 就會讀自己專案的原始碼）；如果你自己把 grep 範圍擴大到整個專案而抓到 `tests/` 裡的檔案操作，不算違規。

**Q5：真模型的回答品質不好（答非所問、亂加內容、語言不跟隨提問）。**
先確認 prompt 的三條鐵律有寫進去（`grep -n "回答語言必須跟隨" app/services/ask_workflow.py`）。若模型本身能力不足，改 `.env` 的 `LLM_MODEL` 換一個對中英文都較好的模型即可——design.md 明訂模型名稱是 config 常數，換模型不需要改程式碼，也不影響任何自動化測試（測試全用假件）。

**Q6：步驟 5 第 7 項（英文條件型詢問）撈不到任何照片，是 bug 嗎？**
不是。如果 router 抽出的是英文的 `category="receipt"`，而資料庫裡存的是中文「收據」，`ILIKE` 對不上是**預期行為**——design.md §8.3 的已知限制：不做跨語言翻譯對映。回答仍會是 200 且是英文的「查無」句。想看到結果，先上傳一張英文收據照片再問。

**Q7：這裡就是最後一個 phase 了嗎？**
不是。後端到此完成，還有 **Phase 14：極簡網頁介面**（design.md v4 新增）——兩個純 HTML 頁面，讓你不用 curl 也能操作這兩個 API。它不新增任何後端端點，也不影響本 phase 的 49 個測試。

---

## 完成後的專案狀態

**後端完成。** 系統具備 design.md 描述的完整後端能力：

- `POST /photos`：JPEG/PNG 檢查（415）→ 本機 VLM 看圖（看不懂 422、什麼都不存；描述用照片主要語言）→ 文字＋四欄位合併成 Document → `bge-m3` 轉向量 → 一條 INSERT 寫入（上傳時間自動記）→ 回 201。
- `POST /ask`：LangGraph 流程圖，LLM 判斷查法與條件（中英文皆可，失敗一律 fallback 語意查詢）→ 條件查詢（ILIKE）或語意查詢（含「最近 30 天、內容時間優先」過濾）→ LLM 只依撈到的照片內容回答（**語言跟隨提問**、查無就說查無、不編造）→ 回 200 含 `answer`／`search_mode`／`retrieved_photo_ids`。
- 兩份 `.feature` 共 12 條 Rule、14 個例子全綠；錯誤處理總表七列全部有測試把關；雙語行為有 7 個額外測試守著；全部 **49** 個測試不依賴任何外部服務。

下一步（也是最後一步）是 Phase 14：給它一個能用瀏覽器操作的極簡介面。
