# Phase 6：indexing_service.py、寫入資料庫與 201 回應

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🔄 **2026-08-19 開工前更新**：對照專案現況重寫步驟——(1) 全面改為 **TDD 順序**（步驟 0 先寫測試跑紅燈，再實作轉綠）；(2) 測試檔依 dev-prompt 指示分目錄：「合併順序固定」等純函式測試移到 `tests/unit/test_indexing_service_unit.py`，煙霧測試在 `tests/integration/test_upload_smoke.py`（Phase 5 已建）；(3) 原「步驟 5 在煙霧測試檔加 wire_fakes fixture」改為**擴充 conftest 既有的 `wire_fake_ai` 安全網**（Phase 5 建立；全套測試因此永不誤打真 Ollama——本 phase 接上 embeddings 後，Phase 5 改寫的兩個 201 測試若無安全網會真的呼叫 bge-m3）；(4) 測試累計數由 6 改為 **35**（Phase 5 結束為 30，含階段I review 後補的「text 全空白也 422」測試）。程式碼區塊（indexing_service／dependencies／fakes／photos）與原計畫一致。

**目標：** 把文字＋四個 metadata 欄位合併成一份 LangChain Document、轉成向量，經 repository 一次寫進資料庫，並回傳規格要求的 201 內容。上傳流程到此**完整跑通**。

---

## 前置條件

- 需要已完成的 phase：**Phase 3**（`photo_repository.insert_photo` 可用）、**Phase 5**（看圖服務與 `POST /photos` 的前兩關；`pytest -q` 現況 **30 passed**；`tests/fakes.py`、conftest 的 `wire_fake_ai`／`client` fixture 已存在）。
- 現況檔案狀態：`app/services/indexing_service.py` 是空檔案（本 phase 填入）；`app/schemas/photo.py` 的 `UploadResponse`／`PhotoMetadata` **已在 Phase 2 寫好**（直接取用）。
- 環境：pytest 仍然**不需要（也絕不可以）呼叫真的 Ollama**（本 phase 用假的 embedding）；但 **PostgreSQL 必須在跑**——本 phase 會真的把資料寫進測試資料庫。沒在跑就先執行 `brew services start postgresql@17`（Phase 1 裝的）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

上傳流程還差三步：把內容轉成向量、寫進資料庫、回傳結果。

轉向量有個關鍵規則（已釐清、不可更動）：**向量要由「文字描述＋四個 metadata 欄位」合併後的內容產生**，不是只用文字。合併的格式必須固定順序，因為「同樣的輸入永遠產生同樣的向量」才有辦法寫測試。

寫入只有一條 `INSERT`（在 repository 裡），所以天然原子：不會出現「存了一半」的照片。

**分層提醒**：router 負責「照順序叫人做事」，service 負責「怎麼做」，repository 負責「怎麼存」。所以合併與轉向量寫在 `services/indexing_service.py`，寫入呼叫 `repositories/photo_repository.insert_photo`，兩者都由 `api/routers/photos.py` 依序呼叫（design.md §4.2 的依賴方向）。

**名詞**：
- **Document**＝LangChain 用來裝「一段文字＋它的 metadata」的標準容器，是 RAG 的基本積木。
- **Embeddings 介面**＝LangChain 定義的「把文字轉成向量」統一介面。正式用 `OllamaEmbeddings`，測試用 `FakeEmbeddings`，兩邊長得一樣所以可以互換。
- **HTTP 201**＝Created，「你要求建立的東西已經建好了」。

---

## ASCII 圖：上傳的完整五步（跨三層）

```
 POST /photos           【api/routers/photos.py】
   │
   ① 檢查 content_type ─────── 非 JPEG/PNG ──> 415（結束）
   │
   ② services/vlm_service.py 看圖 ── 看不懂／失敗 ──> 422（什麼都不存）
   │   PhotoUnderstanding(text, category, location, items, content_time)
   │
   ▼ ★本 phase 從這裡開始
   ③ services/indexing_service.py
      build_document() 固定順序合併（欄位標籤固定用中文，值用原文）：
        在 Target 購買可樂與洋芋片的收據，日期 2026-08-10
        類別: 收據
        地點: Target
        物品: 可樂、洋芋片
        時間: 2026-08-10
      ── 英文照片就是 ──▶
        Receipt from Target with Cola and Chips, dated 2026-08-10
        類別: Receipt
        地點: Target
        物品: Cola、Chips
        時間: 2026-08-10
              │ embed_document()（bge-m3 是多語模型，兩種都吃得下）
              ▼
        [0.013, -0.271, …]  共 1024 個數字
   │
   ▼
   ④ repositories/photo_repository.insert_photo()  一條 INSERT 寫入全部欄位
   │    （上傳時間正式由 DB 的 now() 自動記；測試才用固定時鐘注入固定時間）
   │
   ▼
   ⑤ 回 201 {"id":1, "text":"…", "metadata":{四個欄位}}   【schemas/photo.py，Phase 2 已寫好】
```

---

## 逐步驟操作（TDD：步驟 0 先寫測試跑紅燈，步驟 1〜3 實作轉綠）

### 步驟 0：測試先行（紅燈）

#### 步驟 0-1：在 `tests/fakes.py` 加上 `FakeEmbeddings` 與 `FixedClock`

把整個檔案改成下面的內容。`FakeVLM` 是 Phase 5 已經寫好的，原封不動；新增的是最上面的 import、`VOCABULARY`／`SYNONYMS` 兩個對照表，以及 `FakeEmbeddings` 與 `FixedClock` 兩個假件：

```python
"""測試用的假件。真 AI／真時鐘的替身，讓測試結果可預期。"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime

from app.core import config
from app.services.vlm_service import PhotoUnderstanding


class FakeVLM:
    """照測試指定的內容回傳；「看不懂」情境回 understood=False。"""

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        self.calls += 1
        return self.result


# 規格例子與雙語測試裡會出現的詞。假的向量只認得這些詞，因此結果完全可預期。
VOCABULARY = [
    # 中文（規格 .feature 的例子用的詞）
    "收據", "風景", "照片", "購買",
    "Target", "Costco", "7-11", "海邊",
    "可樂", "洋芋片", "咖啡", "牛奶", "衛生紙", "飲料",
    # 英文（雙語測試用的詞）
    "Receipt", "receipt", "Cola", "cola", "Chips", "chips",
    "coffee", "milk", "drinks", "drink",
]

# 同義／跨語言對照：左邊的詞出現時，右邊的詞也會被算進向量。
# 這是在假件裡「模擬」多語 embedding 的效果——真的 bge-m3 天生就有這個能力，
# 假件必須手動列出來，測試結果才可預期。
SYNONYMS = {
    "飲料": ["可樂", "咖啡", "牛奶"],
    "drinks": ["可樂", "咖啡", "牛奶", "Cola", "cola"],
    "drink": ["可樂", "咖啡", "牛奶"],
    "receipt": ["收據"],
    "Receipt": ["收據"],
    "cola": ["可樂"],
    "Cola": ["可樂"],
}


class FakeEmbeddings:
    """決定論向量：同樣的文字永遠得到同樣的數字，且不需要任何 AI 服務。

    做法：每個出現過的詞用「雜湊」（把文字換算成一個固定的數字）決定它落在
    向量的哪個位置，該位置 +1；最後做「正規化」（把整條向量縮放成長度 1，
    只留下方向），cosine 相似度比的才會是「內容」而不是「字數多寡」。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * config.EMBEDDING_DIM
        vector[0] = 0.1  # 保底值，避免全零向量讓 cosine 距離算出 NaN
        for word in self._words(text):
            vector[self._slot(word)] += 1.0
        length = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / length for v in vector]

    @staticmethod
    def _words(text: str) -> list[str]:
        found = [word for word in VOCABULARY if word in text]
        for word in list(found):
            found.extend(SYNONYMS.get(word, []))
        return found

    @staticmethod
    def _slot(word: str) -> int:
        digest = hashlib.md5(word.encode("utf-8")).hexdigest()
        return int(digest, 16) % config.EMBEDDING_DIM


class FixedClock:
    """固定的「現在時間」，對應規格的 Given 現在時間為 "2026-08-18 10:00"。"""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment
```

#### 步驟 0-2：擴充 `tests/conftest.py` 的 `wire_fake_ai` 安全網

Phase 5 的 `wire_fake_ai` 只接了 `get_vlm`。本 phase 起，router 會再要 `get_embeddings` 與 `get_now`——若不接假件，Phase 5 改寫的兩個 201 測試會**真的呼叫本機 bge-m3**。把 conftest 追加區塊改成（`client` fixture 不動）：

```python
# ---------- Phase 5 追加、Phase 6 擴充：假件安全網＋API 測試用戶端 ----------
# （import 必須留在 DATABASE_URL 導向之後，理由同檔案開頭註解）
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import get_embeddings, get_now, get_vlm  # noqa: E402
from app.main import app  # noqa: E402
from tests.fakes import FakeEmbeddings, FakeVLM, FixedClock  # noqa: E402


@pytest.fixture(autouse=True)
def wire_fake_ai():
    """安全網：每個測試預設接上假 AI 與固定時鐘，結束時清掉所有覆寫。

    本機 Ollama 是真的在跑——pytest 絕不能默默打真模型（design.md §11：
    全部測試不依賴任何外部服務）。需要不同行為的測試自行覆寫：
    - get_vlm 預設「看不懂」假件（要看得懂就覆寫成 FakeVLM(某理解結果)）
    - get_embeddings 預設 FakeEmbeddings（決定論向量）
    - get_now 預設固定時鐘 2026-08-18 10:00（對應規格 Given 的現在時間）
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM()
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_now] = FixedClock(datetime(2026, 8, 18, 10, 0))
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    """可以直接呼叫自己 API 的測試用戶端（不需要真的啟動伺服器）。"""
    with TestClient(app) as test_client:
        yield test_client
```

#### 步驟 0-3：建立 `tests/unit/test_indexing_service_unit.py`（4 個單元測試）

合併與轉向量的純邏輯，不碰資料庫、不碰網路（原計畫的「合併內容的順序固定」煙霧測試與驗收 3／4 條在此自動化）：

```python
"""indexing_service 的單元測試：合併與轉向量的純邏輯，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U4「儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生）」
——合併順序固定＝「同輸入同向量」的前提（design.md §9）。
"""

from app.core import config
from app.services.indexing_service import build_document, embed_document
from tests.fakes import FakeEmbeddings


def test_合併內容的順序固定():
    document = build_document(
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    )
    assert document.page_content == (
        "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10\n"
        "類別: 收據\n"
        "地點: Target\n"
        "物品: 可樂、洋芋片\n"
        "時間: 2026-08-10"
    )
    assert document.metadata == {
        "category": "收據",
        "location": "Target",
        "items": ["可樂", "洋芋片"],
        "content_time": "2026-08-10",
    }


def test_空欄位直接省略():
    document = build_document(
        text="海邊的風景照", category="風景", location="海邊", items=[], content_time=None
    )
    assert document.page_content == "海邊的風景照\n類別: 風景\n地點: 海邊"


def test_英文值保持原文而標籤固定中文():
    # design.md §9：標籤是固定格式的一部分不隨語言變，值保持原文，跨語言交給多語 embedding
    document = build_document(
        text="Receipt from Target with Cola and Chips",
        category="Receipt",
        location="Target",
        items=["Cola", "Chips"],
        content_time="2026-08-10",
    )
    assert document.page_content == (
        "Receipt from Target with Cola and Chips\n"
        "類別: Receipt\n"
        "地點: Target\n"
        "物品: Cola、Chips\n"
        "時間: 2026-08-10"
    )


def test_embed_document_長度正確且同輸入同向量():
    document = build_document(
        text="在 Target 購買可樂與洋芋片的收據",
        category="收據",
        location="Target",
        items=["可樂"],
        content_time=None,
    )
    first = embed_document(FakeEmbeddings(), document)
    second = embed_document(FakeEmbeddings(), document)
    assert len(first) == config.EMBEDDING_DIM
    assert first == second  # 決定論：同輸入永遠同向量
```

#### 步驟 0-4：擴充煙霧測試 `tests/integration/test_upload_smoke.py`

兩個改動：

**(a)** 在檔案最後加上這個新測試（假 embedding 與固定時鐘由 conftest 的 `wire_fake_ai` 自動接上，這裡只需覆寫看圖結果）：

```python
def test_上傳成功會完整寫入並回201(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(中文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == 中文收據.text
    assert body["metadata"] == {
        "category": "收據",
        "location": "Target",
        "items": ["可樂", "洋芋片"],
        "content_time": "2026-08-10",
    }

    row = photo_repository.fetch_photo(body["id"])
    assert row["items"] == ["可樂", "洋芋片"]
    assert row["uploaded_at"].strftime("%Y-%m-%d %H:%M") == "2026-08-18 10:00"
    assert photo_repository.fetch_embedding(body["id"]) is not None
```

**(b)** ⚠️ Phase 5 的 `test_英文照片的描述保持英文不翻譯` 現在會真的走完寫入流程。它斷言的是回應的 `text`／`category`／`items`——本 phase 把回應換成 `UploadResponse` 之後，`category` 與 `items` 移進了 `metadata` 裡面。**請把那個測試的最後兩行斷言改成**：

```python
    assert body["metadata"]["category"] == "Receipt"
    assert body["metadata"]["items"] == ["Cola", "Chips"]
```

第一行 `assert body["text"] == ...` 不用改。

**影響面檢查（改完應該不用再動的檔案）**：`test_看得懂的照片回傳理解結果` 只斷言 201＋`text`＋呼叫次數 → 換成 `UploadResponse` 後依然成立，不用改；Phase 5 改寫的 `test_upload_png_understood_returns_201`／`test_upload_jpeg_understood_returns_201` 只斷言 201（＋`text`）→ 也不用改（它們如今會走完整寫入流程，靠 conftest 假件保持決定論）；`test_看不懂的照片回傳422且不儲存` 與 `test_理解結果text全空白也回422且不儲存` 走 422 短路（到不了轉向量），也不用改——而且從本 phase 起它們的 `count_photos() == 0` 斷言才真正有牙齒（Phase 5 時本來就沒有寫入路徑）。

#### 步驟 0-5：跑紅燈留證據

```bash
python -m pytest tests -q
```

預期：**collection error**（conftest 從 `dependencies.py` import 不到 `get_embeddings`／`get_now`；unit 測試從空的 `indexing_service.py` import 不到 `build_document`）——「功能不存在」的正確紅燈。把輸出留給 report。

### 步驟 1：寫 `app/services/indexing_service.py`

```python
"""把文字＋四個 metadata 欄位合併成 Document，再轉成向量。"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from app.core import config


def build_document(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: str | None,
) -> Document:
    """把文字與四個欄位合併成一份 Document。

    合併順序固定為「文字 / 類別 / 地點 / 物品 / 時間」，空欄位直接省略。
    順序固定，同樣的輸入才會得到同樣的向量——這是測試可行的前提。

    欄位標籤（類別/地點/物品/時間）一律用中文，**不隨內容語言改變**：
    標籤只是把欄位串起來的固定格式，換來換去反而讓「同輸入同向量」不成立。
    欄位的「值」則保持原文（英文照片就是英文），跨語言比對交給多語 embedding。
    """
    lines = [text]
    if category:
        lines.append(f"類別: {category}")
    if location:
        lines.append(f"地點: {location}")
    if items:
        lines.append("物品: " + "、".join(items))
    if content_time:
        lines.append(f"時間: {content_time}")

    return Document(
        page_content="\n".join(lines),
        metadata={
            "category": category,
            "location": location,
            "items": items,
            "content_time": content_time,
        },
    )


def build_ollama_embeddings() -> OllamaEmbeddings:
    """正式用的向量產生器：本機 Ollama 的 bge-m3（多語模型）。"""
    return OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def embed_document(embeddings: Embeddings, document: Document) -> list[float]:
    """把 Document 的內容轉成向量。

    刻意用 embed_query（一段文字進、一條向量出）：上傳存的內容和之後
    詢問的問題走**同一種轉法**，兩邊的向量才落在同一個空間、才能比較。
    """
    return embeddings.embed_query(document.page_content)
```

### 步驟 2：在 `app/dependencies.py` 加上 `get_embeddings` 與 `get_now`

把 Phase 5 建立的檔案改成下面這樣（新增最下面兩組）：

```python
"""依賴注入點：router 用 Depends(...) 取用，測試用 dependency_overrides 換成假件。"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.services import indexing_service, vlm_service


@lru_cache(maxsize=1)
def _ollama_vlm() -> vlm_service.OllamaVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線）。"""
    return vlm_service.OllamaVLM()


@lru_cache(maxsize=1)
def _ollama_embeddings() -> Embeddings:
    return indexing_service.build_ollama_embeddings()


def get_vlm() -> vlm_service.VLMClient:
    return _ollama_vlm()


def get_embeddings() -> Embeddings:
    return _ollama_embeddings()


def get_now() -> datetime | None:
    """『現在時間』。

    正式執行回傳 None，代表上傳時間交給資料庫的 now() 自動記錄。
    測試需要固定時間時，用 dependency_overrides 換成 FixedClock。
    """
    return None
```

（Phase 5 版 `get_vlm` 的 docstring 內容可以保留——上面是最小可讀版本，兩者擇一，行為相同。）

### 步驟 3：改寫 `app/api/routers/photos.py`，把流程接完

```python
"""上傳照片的 router：POST /photos。"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.photo import PhotoMetadata, UploadResponse
from app.services import indexing_service, vlm_service

router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201, response_model=UploadResponse)
def upload_photo(
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse:
    """上傳照片：格式檢查 → 看圖 → 轉向量 → 寫入 → 回 201。

    全程在同一個請求內完成；任何一步失敗＝整筆不存在。
    """
    # ① 格式檢查
    if file.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    # 原始照片只存在這個變數裡，函式結束就消失——絕不寫進磁碟或資料庫
    image_bytes = file.file.read()

    # ② 看圖
    understanding = vlm.understand(image_bytes, file.content_type)
    if not understanding.understood or not understanding.text.strip():
        raise HTTPException(
            status_code=422,
            detail="VLM 無法理解照片內容，未儲存任何資料",
        )

    # ③ 合併成 Document，再轉成向量
    content_time = vlm_service.parse_content_time(understanding.content_time)
    content_time_text = content_time.isoformat() if content_time else None
    document = indexing_service.build_document(
        text=understanding.text,
        category=understanding.category,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time_text,
    )
    embedding = indexing_service.embed_document(embeddings, document)

    # ④ 一條 INSERT 寫入
    row = photo_repository.insert_photo(
        text=understanding.text,
        category=understanding.category,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time,
        embedding=embedding,
        uploaded_at=now,
    )

    # ⑤ 回 201
    return UploadResponse(
        id=row["id"],
        text=row["text"],
        metadata=PhotoMetadata(
            category=row["category"],
            location=row["location"],
            items=row["items"],
            content_time=row["content_time"].isoformat() if row["content_time"] else None,
        ),
    )
```

### 步驟 4：轉綠

```bash
python -m pytest tests -q
```

預期：**35 passed**。有紅就修到綠——但只准改「本 phase 動過的東西」，Phase 3〜5 的既有行為不得為了過測試而更動。

---

## 驗收標準

1. **煙霧測試全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/integration/test_upload_smoke.py -v
   ```
   預期最後一行：`6 passed`

2. **indexing 單元測試全綠**
   ```bash
   pytest tests/unit/test_indexing_service_unit.py -v
   ```
   預期最後一行：`4 passed`

3. **全部測試一起跑**
   ```bash
   pytest -q
   ```
   預期：`35 passed`（**測試累計數：35** ＝ Phase 5 的 30 ＋ unit 4 ＋ smoke 1）

4. **合併內容格式正確（中文）**（已由單元測試把關；此指令供人工複核）
   ```bash
   python -c "
   from app.services.indexing_service import build_document
   print(repr(build_document(text='海邊的風景照', category='風景', location='海邊', items=[], content_time=None).page_content))
   "
   ```
   預期輸出：`'海邊的風景照\n類別: 風景\n地點: 海邊'`（沒有物品與時間兩行——空欄位省略）

5. **合併內容格式正確（英文，值保持原文）**（已由單元測試把關；此指令供人工複核）
   ```bash
   python -c "
   from app.services.indexing_service import build_document
   print(build_document(text='Receipt from Target with Cola and Chips', category='Receipt', location='Target', items=['Cola','Chips'], content_time='2026-08-10').page_content)
   "
   ```
   預期輸出：
   ```
   Receipt from Target with Cola and Chips
   類別: Receipt
   地點: Target
   物品: Cola、Chips
   時間: 2026-08-10
   ```
   （標籤固定中文、值保持英文原文——這就是設計要的行為。）

6. **資料庫真的多了一筆完整資料**
   跑測試沒辦法直接看到資料——測試每次開始前都會清空資料表。改用下面這個腳本手動走一次「合併 → 轉向量 → 寫入」，資料會留在測試資料庫裡：
   ```bash
   python - <<'PY'
   from datetime import date, datetime
   from app.core import config
   config.DATABASE_URL = "postgresql://localhost:5433/visual_memory_test"
   from app.repositories import photo_repository as repo
   from app.services import indexing_service
   from tests.fakes import FakeEmbeddings
   repo.clear_photos()
   TEXT = "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
   doc = indexing_service.build_document(text=TEXT, category="收據", location="Target",
                                         items=["可樂","洋芋片"], content_time="2026-08-10")
   vec = indexing_service.embed_document(FakeEmbeddings(), doc)
   print("向量長度：", len(vec))
   row = repo.insert_photo(text=TEXT, category="收據", location="Target",
                           items=["可樂","洋芋片"], content_time=date(2026, 8, 10),
                           embedding=vec, uploaded_at=datetime(2026, 8, 18, 10, 0))
   print("寫入 id：", row["id"], "上傳時間：", row["uploaded_at"])
   PY
   ```
   預期輸出：
   ```
   向量長度： 1024
   寫入 id： 1 上傳時間： 2026-08-18 10:00:00+08:00
   ```
   （時區偏移視你的系統設定而定，重點是日期與時分是 `2026-08-18 10:00`。）
   接著用 psql 看剛剛寫入的那筆資料：
   ```bash
   psql -d visual_memory_test -c "SELECT id, text, category, location, items, content_time, uploaded_at, vector_dims(embedding) FROM photo;"
   ```
   預期看到 **1 筆**資料：`id` 是 `1`、`category` 是 `收據`、`location` 是 `Target`、`items` 顯示為 `{可樂,洋芋片}`、`content_time` 是 `2026-08-10`、`vector_dims` 是 `1024`。

7. **用真正的 HTTP 請求跑一次也可以**（可選，需要 Ollama）
   ```bash
   uvicorn app.main:app --port 8000   # 另一個視窗，記得先 cd ＋啟用虛擬環境
   curl -s -X POST http://localhost:8000/photos -F "file=@/tmp/sample.png;type=image/png"
   ```
   預期：回傳 `{"id":…,"text":"…","metadata":{…}}`。若 Ollama 沒開會拿到 422（因為看圖失敗被歸類為「無法理解」），這也是 design.md 規定的行為。（`/tmp/sample.png` 是 Phase 4 產生的測試圖片；若已被系統清掉，重跑 Phase 4 的產生指令即可。）

---

## 常見問題

**Q1：寫入時報 `expected 1024 dimensions`。**
`FakeEmbeddings` 產生的向量長度來自 `config.EMBEDDING_DIM`，資料表宣告的是 `db/schema.sql` 裡的 `vector(1024)`。兩邊必須一樣。改任何一邊都要同步改另一邊，並對兩個資料庫重跑建表：`psql -d visual_memory -f db/schema.sql` 與 `psql -d visual_memory_test -f db/schema.sql`。

**Q2：`content_time` 回應變成 `"2026-08-10T00:00:00"` 之類的格式。**
回應要的是純日期字串。確認 router 用的是 `row["content_time"].isoformat()`（`date` 型別的 `isoformat()` 就是 `YYYY-MM-DD`），不要傳 `datetime`。

**Q3：上傳時間對不上，差了幾小時。**
`uploaded_at` 是 `timestamptz`（帶時區的時間）。測試傳入的固定時間沒有時區，資料庫會用伺服器時區解讀，取回時會帶上偏移量。比較時只比對「年月日時分」（如驗收指令的 `strftime("%Y-%m-%d %H:%M")`），不要直接比對物件。

**Q4：能不能順手把原始照片存下來？**
**不可以。** 已釐清的決策是「不儲存原始照片檔」，任何路徑都不得保留或回傳。`image_bytes` 用完就該消失。

**Q5：`metadata` 想多塞一個欄位（例如金額）。**
不行。固定四欄位是已釐清的決策，多的資訊在 `PhotoUnderstanding` 就沒有地方放，也不得新增欄位。

**Q6：合併時的標籤「類別/地點/物品/時間」要不要依內容語言改成 Category/Location/…？**
**不要。** 標籤是固定格式的一部分，換了就破壞「同輸入同向量」。design.md §9 明訂合併規則是固定順序的那五行，值保持原文即可。

**Q7：為什麼假 embedding／固定時鐘接在 conftest 而不是煙霧測試檔裡？**
因為需要它們的不只煙霧測試——Phase 5 改寫的兩個 201 測試也會走完整寫入流程。放 conftest 的 `wire_fake_ai`（autouse）一處搞定，並保證「全套 pytest 永不呼叫真 Ollama」（design.md §11）。個別測試要不同行為時自行覆寫即可。

---

## 完成後的專案狀態

`POST /photos` 已經完整可用：合格照片會被看圖、合併成 Document、轉成向量、經 repository 一次寫進資料庫，並回傳 `id`＋文字＋四欄位 metadata；中文與英文照片都能正確處理且不翻譯。規則 U1〜U7 的行為都已實作，只差用 `.feature` 檔正式驗收（Phase 7）。測試累計 **35** 個（unit 12＝8＋4；integration 23＝22＋1），全部不依賴 Ollama。
