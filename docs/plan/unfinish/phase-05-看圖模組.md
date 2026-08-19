# Phase 5：看圖服務 vlm_service.py（測試用假件驗收；正式路徑已是 OllamaVLM）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 寫出 `app/services/vlm_service.py`——把照片變成「文字描述＋四個 metadata 欄位」的服務，建立 `app/dependencies.py` 這個依賴注入點，並把「看不懂就 422、什麼都不存」接到 router 上。本 phase **測試**用假件驗收（不需要 Ollama 在跑）；正式程式裡的看圖實作已經是 `OllamaVLM`。

---

## 前置條件

- 需要已完成的 phase：**Phase 4**（`POST /photos` 已有格式檢查）。
- 環境：不需要 Ollama 真的跑起來（本 phase 用假件）；但 **PostgreSQL 必須在跑**——本 phase 的測試會連測試資料庫，確認「什麼都不存」真的成立。沒在跑就先執行 `brew services start postgresql@17`（Phase 1 裝的）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

`vlm_service.py` 的職責只有一件事：**照片 bytes 進去，結構化結果出來**。結果長什麼樣子由一個 Pydantic 模型 `PhotoUnderstanding` 固定死——只有六個欄位，多的一律沒有地方放（這就是「清單外資訊一律捨棄」在源頭的落實）。

**雙語的第一個落地點就在這裡**（design.md §8.1）：prompt 明文要求模型**用照片內容本身的主要語言**寫描述與欄位值——中文收據就寫中文、英文收據就寫英文，**不強制翻譯**。理由是：翻譯會失真、也會多一層沒必要的處理；跨語言的搜尋交給多語 embedding（`bge-m3`）就好。

同時要處理「失敗」。design.md 把三種情況合併成同一種失敗：模型說看不懂（`understood=false`）、回傳格式驗證不過、呼叫時發生例外（例如 Ollama 沒開）。三種都 → HTTP 422 → **什麼都不存**。

為什麼本 phase 的**測試**用假件、但程式裡已經寫好真模型：規格的驗收例子把「VLM 理解其內容為 …」寫在測試步驟裡，等於先發標準答案再考你的上傳程式「有沒有把欄位存對、看不懂有沒有 422」。`FakeVLM` 就是那張答案卡，**不是**因為 prompt 不可靠、也**不是**第二套看圖系統。真的看圖邏輯本 phase 就寫在 `OllamaVLM`；`get_vlm()` 正式執行永遠回它。Phase 8 不是「把假的換成真的」，而是第一次真的打到 Ollama（pytest 之後依然走 Fake）。

**追程式時看哪裡（避免搞混）**：

```
使用者上傳照片（uvicorn / 瀏覽器）——只走右邊，不要打開 tests/

  POST /photos
    → photos.py 的 upload_photo()
    → Depends(get_vlm) → get_vlm() → OllamaVLM()     ★實際執行
    → OllamaVLM.understand()                         ★真的看圖

跳過這兩個：它們沒有「使用者上傳」的執行邏輯
  VLMClient   只是合約（有 understand 就算數），裡面是 ... 沒有程式可跑
  FakeVLM     只住在 tests/fakes.py，只有 pytest 才會塞進來
```

**名詞**：
- **Pydantic 模型**＝用 Python 類別描述「一筆資料該有哪些欄位、什麼型別」，資料不符會自動報錯。
- **結構化輸出（structured output）**＝要求 AI 一定要照指定欄位格式回答，而不是自由發揮一段文字。
- **依賴注入（dependency injection）**＝router 不自己 `OllamaVLM()`，而是「請框架給我一個會看圖的」；正式給真的，pytest 才給假的。這些「請框架給我」的函式集中在 `app/dependencies.py`。
- **假件（stub / fake）**＝考試用的固定答案卡，讓測試可預期。**不**用來判斷模型聰不聰明。
- **Protocol**＝型別合約：「只要有同名方法就算數」，不必繼承。追正式路徑請直接看 `OllamaVLM`。
- **base64**＝把圖片這種二進位資料編碼成一長串純文字的方法。給模型的訊息只能放文字，所以照片要先轉成 base64 才夾得進去。

---

## ASCII 圖：vlm_service 的位置與資料形狀

```
 POST /photos ──① 格式檢查(415)──> 通過
 (api/routers/photos.py)             │ image_bytes（只存在記憶體，用完即丟）
        │                            ▼
        │ Depends(get_vlm)  ┌──────────────────────────────────────┐
        └──────────────────>│ app/services/vlm_service.py ★本 phase │
        （app/dependencies）│                                      │
        正式：OllamaVLM     │  OllamaVLM.understand()  ← 追程式看這│
        測試才：FakeVLM     │    圖片轉 base64 ＋ prompt            │
                            │      → 結構化輸出                     │
                            └──────────────────────────────────────┘
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼（中文收據）                                    ▼（英文收據）
  PhotoUnderstanding(                              PhotoUnderstanding(
    understood   = True,                             understood   = True,
    text = "在 Target 購買可樂與洋芋片的收據…",        text = "Receipt from Target with Cola…",
    category     = "收據",                            category     = "Receipt",
    location     = "Target",                          location     = "Target",
    items        = ["可樂", "洋芋片"],                 items        = ["Cola", "Chips"],
    content_time = "2026-08-10",                      content_time = "2026-08-10",
  )                                                 )
             └───────────────────────┬───────────────────────┘
                     ★ 描述用照片自己的語言，系統不翻譯
                                     │
                      understood=False / 格式錯 / 例外
                                     ▼
                          HTTP 422，什麼都不存
```

---

## 逐步驟操作

### 步驟 1：寫 `app/services/vlm_service.py`

（這個檔案與下一步的 `app/dependencies.py`，在 Phase 2 都已經 `touch` 成空檔案——打開時是空的很正常，現在把內容填進去。）

```python
"""AI 看圖：照片 bytes → 文字描述＋四個 metadata 欄位。"""

from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Protocol

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.core import config


class PhotoUnderstanding(BaseModel):
    """VLM 看完照片後唯一被允許回傳的六個欄位。

    欄位清單就是「規格允許的資訊」；清單外的東西沒有地方放，自然被捨棄。
    """

    understood: bool                                 # 看不懂 → False
    text: str = ""                                   # 文字描述（照片主要語言）
    category: str | None = None                      # 類別，例如「收據」或 "Receipt"
    location: str | None = None                      # 地點／商家，例如「Target」
    items: list[str] = Field(default_factory=list)   # 物品清單
    content_time: str | None = None                  # ISO 日期字串，推不出來 → None


VLM_PROMPT = """你是照片理解助手。請看這張照片，只輸出下列六個欄位：

- understood：你是否看得懂這張照片的內容（看不懂填 false）
- text：用一句話描述照片內容
- category：照片類別，例如「收據」「風景」或 "Receipt"、"Landscape"；判斷不出來填 null
- location：地點或商家名稱，例如「Target」；判斷不出來填 null
- items：照片中出現的物品名稱清單；沒有就填空陣列
- content_time：照片內容本身的日期（例如收據上的消費日期），格式 YYYY-MM-DD；推不出來填 null

語言規則（重要）：
- text 與各欄位的值，一律使用**照片內容本身的主要語言**。
  照片上是中文（例如中文收據）就用繁體中文寫；照片上是英文（例如英文收據）就用英文寫。
- 不要翻譯。不要中英混寫。照片上寫 "Cola" 就填 "Cola"，寫「可樂」就填「可樂」。

其他規則：
1. 只准填上面這六個欄位，清單外的任何資訊一律捨棄。
2. 不要編造照片上沒有的資訊。
3. 照片模糊、全黑或看不出任何內容時，understood 填 false。
"""


class VLMClient(Protocol):
    """看圖合約，不是會執行的類別。追正式上傳請直接看下面的 OllamaVLM。

    Protocol＝只要有 understand() 就算數，不必繼承本 class。
    兩個實作都不必寫 class Xxx(VLMClient)：
    - OllamaVLM：正式路徑（uvicorn），真的呼叫本機 gemma4
    - FakeVLM：只在 tests/fakes.py，pytest 的固定答案卡；不是第二套看圖系統
    """

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        ...


class OllamaVLM:
    """正式的看圖實作。使用者上傳照片時，實際跑的就是這一個（本機 gemma4）。"""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        # temperature=0 ＝要模型盡量穩定、不要每次答不一樣
        self._model = ChatOllama(
            model=model or config.VLM_MODEL,
            base_url=base_url or config.OLLAMA_BASE_URL,
            temperature=0,
        ).with_structured_output(PhotoUnderstanding)

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        """看一張照片。任何失敗都回 understood=False，由上層轉成 422。"""
        # HumanMessage＝LangChain 裡「使用者傳給模型的一則訊息」；
        # content 是內容區塊清單，這裡放一塊文字（prompt）＋一塊 base64 圖片
        message = HumanMessage(
            content=[
                {"type": "text", "text": VLM_PROMPT},
                {
                    "type": "image",
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                    "mime_type": content_type,
                },
            ]
        )
        # 失敗就再試一次；仍失敗一律視為「看不懂」
        for _ in range(2):
            try:
                result = self._model.invoke([message])
            except Exception:
                continue
            if isinstance(result, PhotoUnderstanding):
                return result
        return PhotoUnderstanding(understood=False)


def parse_content_time(value: str | None) -> date | None:
    """把 VLM 給的日期字串轉成日期。

    解析不出來就回 None——內容時間本來就是可空欄位，
    不可以因為它讓整個上傳失敗。
    """
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
```

> 補充：`parse_content_time()` 在本 phase 只是先寫好、先驗收（見驗收標準第 3 條），還不會被任何人呼叫——**Phase 6** 寫入資料庫之前才會用它把日期字串轉成真正的日期，轉不出來就存 NULL。現在不要把它接進 router。

### 步驟 2：寫 `app/dependencies.py`（依賴注入點）

這是全專案「測試時要換成假件」的唯一開關。本 phase 先放看圖的那一個，後面 phase 會陸續補上其餘五個。

**正式跑伺服器時這裡不會出現 Fake。** `get_vlm()` 永遠回 `OllamaVLM`。只有 pytest 寫 `app.dependency_overrides[get_vlm] = lambda: FakeVLM(...)` 才會暫時換成答案卡；測完 `conftest.py` 會 `clear()`。

程式碼裡的 `@lru_cache` 是 Python 內建的「把函式結果記下來」裝飾器：第一次呼叫真的執行並記住結果，之後每次呼叫都直接回傳同一個結果——這裡拿它確保 `OllamaVLM` 全程只建立一次。

```python
"""依賴注入點：router 用 Depends(...) 取用；pytest 才用 dependency_overrides 換成假件。

追正式上傳：get_vlm() → OllamaVLM。不要在這個檔找 FakeVLM（它在 tests/）。

design.md §4.2：get_vlm / get_embeddings / get_now 是三個主要注入點；
詢問流程另外需要 get_router / get_answerer / get_today（Phase 11 補上）。
"""

from __future__ import annotations

from functools import lru_cache

from app.services import vlm_service


@lru_cache(maxsize=1)
def _ollama_vlm() -> vlm_service.OllamaVLM:
    """只建立一次，之後重複使用（建立物件本身不會連線）。"""
    return vlm_service.OllamaVLM()


def get_vlm() -> vlm_service.VLMClient:
    """給 router 的看圖物件。正式執行永遠是 OllamaVLM。

    pytest 若要換成 FakeVLM：app.dependency_overrides[get_vlm] = ...
    那個覆寫只活在測試裡，不影響 uvicorn。
    """
    return _ollama_vlm()
```

### 步驟 3：改 `app/api/routers/photos.py`，把看圖接進上傳流程

```python
"""上傳照片的 router：POST /photos。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core import config
from app.dependencies import get_vlm
from app.services import vlm_service

router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=201)
def upload_photo(
    file: UploadFile = File(...),
    # Depends(get_vlm)＝請框架給一個會看圖的。正式是 OllamaVLM；
    # 只有 pytest 才會覆寫成 FakeVLM。型別寫 VLMClient 只是合約，追程式看 OllamaVLM。
    vlm: vlm_service.VLMClient = Depends(get_vlm),
) -> dict:
    """上傳照片：格式檢查 → 看圖 →（Phase 6）轉向量、寫入、回 201。"""
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

    # TODO(Phase 6)：indexing_service 轉向量 → photo_repository 寫入 → 回 201 正式回應
    return {
        "understood": True,
        "text": understanding.text,
        "category": understanding.category,
        "location": understanding.location,
        "items": understanding.items,
        "content_time": understanding.content_time,
    }
```

### 步驟 4：建立 `tests/fakes.py`（五種假件的第一種）

這個檔**只給 pytest 用**。追「使用者上傳一張照片」時不要打開它。`FakeVLM` 不是因為 prompt 不夠準才存在：規格測試要固定「理解結果＝收據／Target」，才能驗收上傳程式有沒有把欄位存對。模型聰不聰明是 Phase 8 用手打真 Ollama 才看的。

```python
"""pytest 專用假件。正式上傳走 OllamaVLM，不會讀這個檔。"""

from __future__ import annotations

from app.services.vlm_service import PhotoUnderstanding


class FakeVLM:
    """考試用的固定答案卡，不是正式看圖系統。

    測試會先指定「請當作收據、店名 Target」；understand() 照念，不呼叫 Ollama。
    沒給 result 時預設 understood=False（規格：看不懂 → 422、什麼都不存）。
    """

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        self.calls += 1
        return self.result
```

### 步驟 5：建立 `tests/conftest.py`（測試共用設定）

`conftest.py` 是 pytest 的慣例檔名：放在 `tests/` 底下，裡面的設定會自動套用到所有測試。**fixture**＝pytest 的「測試前準備／測試後收拾」函式：測試把它的名字寫在參數裡就會自動拿到它準備好的東西（例如下面的 `client`）；標了 `autouse=True` 的則不用點名、對每個測試都生效。

```python
"""所有測試共用的設定與 fixture。"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.core import config

# 測試一律用測試資料庫，絕不碰正式資料庫。
# 這一行必須在 import repository／app 之前執行——db/session.py 每次連線都重讀
# config.DATABASE_URL，所以只要在任何連線發生前改掉就有效。
config.DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://localhost:5433/visual_memory_test"
)

from app.main import app  # noqa: E402  （必須在改完 DATABASE_URL 之後 import）
from app.repositories import photo_repository  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    """每個測試開始前把 photo 表清乾淨。

    autouse=True ＝不用在測試參數裡點名，pytest 對每個測試都會自動先執行它。
    """
    photo_repository.clear_photos()
    yield


@pytest.fixture
def client() -> TestClient:
    """可以直接呼叫自己 API 的測試用戶端（不需要真的啟動伺服器）。"""
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
```

### 步驟 6：建立暫時的煙霧測試 `tests/test_upload_smoke.py`

（「煙霧測試」＝最粗略的「通電看會不會冒煙」測試。Phase 7 會被正式的規格測試取代，這個檔案屆時會被刪掉。）

```python
"""Phase 5 的暫時性測試：確認看圖有被呼叫、失敗會變成 422、中英文都能處理。"""

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"  # 內容不重要，我們用假件，不會真的去看圖
)

中文收據 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)

英文收據 = PhotoUnderstanding(
    understood=True,
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time="2026-08-10",
)


def test_看得懂的照片回傳理解結果(client):
    fake = FakeVLM(中文收據)
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    assert response.json()["text"] == 中文收據.text
    assert fake.calls == 1


def test_英文照片的描述保持英文不翻譯(client):
    """雙語：VLM 用照片自己的語言描述，系統不做任何翻譯（design.md §8.1）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["category"] == "Receipt"
    assert body["items"] == ["Cola", "Chips"]


def test_看不懂的照片回傳422且不儲存(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "VLM 無法理解照片內容，未儲存任何資料"
    assert photo_repository.count_photos() == 0


def test_非圖片格式不會呼叫看圖(client):
    fake = FakeVLM()
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 415
    assert fake.calls == 0  # 415 之後完全不進入後續處理
```

### 步驟 7：建立 `pytest.ini`

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

---

## 驗收標準

1. **四個煙霧測試全綠**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest tests/test_upload_smoke.py -v
   ```
   預期最後一行：`4 passed`

2. **全部測試一起跑也是 4 個**
   ```bash
   pytest -q
   ```
   預期：`4 passed`（**測試累計數：4**）

3. **`PhotoUnderstanding` 真的只有六個欄位**（清單外資訊沒有地方放）
   ```bash
   python -c "from app.services.vlm_service import PhotoUnderstanding; print(list(PhotoUnderstanding.model_fields))"
   ```
   預期輸出：`['understood', 'text', 'category', 'location', 'items', 'content_time']`

4. **日期解析的行為正確**
   ```bash
   python -c "from app.services.vlm_service import parse_content_time as p; print(p('2026-08-10'), p('去年夏天'), p(None))"
   ```
   預期輸出：`2026-08-10 None None`

5. **prompt 真的寫了「用照片主要語言」的規則**（雙語需求的來源）
   ```bash
   grep -n "照片內容本身的主要語言" app/services/vlm_service.py
   grep -n "不要翻譯" app/services/vlm_service.py
   ```
   預期：各印出一行。

6. **資料庫仍然是空的**（本 phase 還沒寫入任何東西）
   ```bash
   python -c "
   from app.core import config
   config.DATABASE_URL='postgresql://localhost:5433/visual_memory_test'
   from app.repositories import photo_repository as repo
   print(repo.count_photos())
   "
   ```
   預期輸出：`0`

---

## 常見問題

**Q1：`ImportError: cannot import name 'HumanMessage'`。**
`langchain-core` 沒裝或版本太舊。執行 `uv pip install -U "langchain-core>=1.0" "langchain-ollama>=1.0"`。

**Q2：`ChatOllama` 建立時就報連線錯誤。**
不應該發生——建立物件不會連線。若真的發生，代表你在 `dependencies.py` 的模組最外層直接呼叫了 `OllamaVLM()`。請確認它包在 `_ollama_vlm()` 函式裡並加了 `@lru_cache`，只有真的要用時才建立。

**Q3：測試時仍然去呼叫真的 Ollama。**
`app.dependency_overrides[get_vlm] = ...` 的鍵必須是**同一個函式物件**。要 `from app.dependencies import get_vlm` 匯入（router 也是從這裡匯入的），不能自己再定義一個同名函式。

**Q4：圖片區塊格式報錯 `Unsupported content block type: image`。**
你的 `langchain-core` 還是 0.x。兩種解法：升級到 1.x（建議，Phase 1 的 `requirements.txt` 裝的就是 1.x），或把圖片區塊改成舊格式：
```python
b64 = base64.b64encode(image_bytes).decode("ascii")
{"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}}
```

**Q5：`understood=True` 但 `text` 是空字串，會怎樣？**
一樣回 422。design.md 說「失敗就不存，所以 `text` 不會空」，程式碼裡的 `not understanding.text.strip()` 就是在守這條。

**Q6：四個測試全部報 `connection to server at "localhost" ... port 5433 failed`。**
PostgreSQL 沒在跑（`conftest.py` 的 `clean_database` 是 `autouse=True`，每個測試前都會連測試資料庫清空 `photo` 表）。執行 `brew services start postgresql@17`，等幾秒再重跑 `pytest`。

**Q7：既然要支援雙語，要不要在這裡把英文描述翻成中文再存？**
**不要。** design.md §8.1／§8.3 明訂不做翻譯對映——原文照存，跨語言召回交給多語 embedding。加翻譯層就是過度設計。

**Q8：`VLMClient` / `FakeVLM` 會不會讓追程式搞混？要不要刪掉 Fake？**
**不要刪。** 追使用者上傳只看：`photos.py` → `get_vlm()` → `OllamaVLM.understand()`。`VLMClient` 沒有執行邏輯；`FakeVLM` 只在 `tests/`。Fake 考的是「欄位有沒有存對」，不是「prompt／模型準不準」。刪了之後 Phase 7 的規格 Example 沒辦法自動對答案。

---

## 完成後的專案狀態

上傳流程已經走到第二關：格式合格的照片會交給 `services/vlm_service.py`，看不懂／呼叫失敗一律 422 且資料庫維持 0 筆（規則 U7 已經成立）；看得懂的照片能拿到結構化結果，**中英文照片都用自己的語言描述**，但還沒轉成向量、也還沒寫進資料庫。測試累計 **4** 個。
