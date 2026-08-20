# Phase 17：檔案儲存服務 storage_service.py（原圖落地＋Pillow 縮圖＋測試隔離）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候（雲端儲存、圖片壓縮參數、WebP、多尺寸縮圖、去識別化……），答案一律是「不要」。

**目標：** 做出「照片檔案要放哪、怎麼放、怎麼找回來」這一層——把上傳進來的原圖寫成檔案、產生一張長邊最多 512px 的縮圖，並讓資料庫只記一串**相對路徑**；同時保證 pytest 永遠不會把垃圾檔案寫進專案的 `data/`。

本 phase **只做服務層**，不改上傳流程、不新增任何 HTTP 端點（那是 Phase 19 的事）。

---

## 前置條件

- 需要已完成的 phase：**Phase 15**（`folder` 表、`photo` 新增 `original_path` / `thumbnail_path` / `content_type` 三個路徑相關欄位、conftest 的 `reset_tables`）、**Phase 16**（資料夾資料層）。
  本 phase 不會直接呼叫 15／16 新增的函式，但照總覽的順序做，基線顆數才對得上。
- 基線（開工前**實查**）：`pytest -q` 全綠。數字＝ **79**（Phase 01〜14）＋ Phase 15、16 各自新增的顆數。動手前先跑一次記下來，本 phase 結束要用它對答案。
- 環境：本 phase 的新測試本身**不碰 Ollama、不碰資料庫**（純檔案操作）；不過 conftest 的 autouse `reset_tables` 每個測試都會連測試庫清資料，所以照舊把 PostgreSQL@17（5433）跑著即可。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

`design.md` v4 有一條規定是「**不儲存原始照片檔**」。`design1.md` §1.1 已由產品負責人**明示推翻**：現在要存原圖 ＋ 縮圖，資料庫只記路徑。本 phase 就是把這件事的「怎麼存」寫出來。

三個要想清楚的問題：

**1. 檔案放哪裡？** 專案根目錄下的 `data/`，分兩個資料夾：

- `data/photos/{id}.jpg|png`：原圖，位元組原封不動寫進去，不做任何轉檔或壓縮。
- `data/thumbs/{id}.jpg|png`：縮圖，長邊最多 512px（等比縮小、**絕不放大**）。

檔名直接用 `photo.id`——資料庫的主鍵天生唯一，不必再發明一套檔名規則（這也是為什麼 Phase 19 的上傳流程一定要「先 INSERT 拿到 id、再寫檔」）。

**2. 資料庫要存什麼字串？** 一律存**以 `data/` 開頭的相對路徑**，例如 `data/photos/1.jpg`。

為什麼不存絕對路徑？因為絕對路徑會把「這台電腦的目錄結構」寫死進資料庫；換一台機器、或測試改用暫存目錄，整批資料就全錯。相對路徑則是「相對於資料根目錄」的位置，換環境只要換根目錄即可。

那「資料根目錄」怎麼決定？新增一個設定 `config.DATA_DIR`（預設 `data`）。要把資料庫裡的 `data/photos/1.jpg` 換算成實際檔案位置時，就是「把第一段 `data` 換成 `DATA_DIR`」——這件事由 `absolute_path()` 一個函式負責，全系統只有它知道換算規則。

**3. 測試怎麼辦？** 這是本 phase 最容易忽略、但最重要的一點：**pytest 絕對不可以把測試產生的圖片寫進專案的 `data/`**。做法是在 `tests/conftest.py` 加一個 autouse fixture，把 `config.DATA_DIR` 指到 pytest 自己準備的暫存資料夾。這個安全網的精神跟既有的 `wire_fake_ai`（絕不打真 Ollama）、`reset_tables`（絕不清正式庫）完全一樣：**危險的預設值由 conftest 統一擋掉，不靠個別測試自律。**

> ⚠️ **測試餵給 Pillow 的圖片必須是「真的圖」。** 專案現有測試常用 `b"\x89PNG\r\n\x1a\n fake image bytes"` 這種假位元組——以前沒人真的去解碼它，所以沒事。從本 phase 起 Pillow 會**真的把 bytes 打開**，假位元組會直接讓 Pillow 拋出 `UnidentifiedImageError`。所以本 phase 順手在 `tests/fakes.py` 加兩個小工具，用 Pillow 現產一張真的小圖出來給測試用。（既有那些測試檔要跟著改，是 **Phase 19** 的工作——那時上傳流程才真的會走到縮圖這一步；本 phase 不動它們。）

**分層提醒**：`storage_service.py` 只做檔案操作，**不碰資料庫、不碰 HTTP**。誰在什麼時候呼叫它、失敗了要怎麼收拾，全部是 Phase 19 的 router 要決定的事。

**名詞**：

- **Pillow**＝Python 最通用的影像處理套件（安裝時叫 `Pillow`，程式裡 `import PIL`）。本專案只用它三個能力：把 bytes 打開成圖、等比縮小、存成檔案。
- **縮圖（thumbnail）**＝同一張照片的小尺寸版本。瀏覽頁一次要顯示幾十張圖，直接送原圖會很慢又很吃流量，所以另外存一份小的。
- **等比縮小**＝寬高**同時**按同一個比例縮小，圖片不會被壓扁或拉長。Pillow 的 `Image.thumbnail((512, 512))` 就是「把長邊縮到 512、短邊按比例跟著縮」；而且它**只縮不放**——本來就小於 512 的圖會原樣保留。
- **長邊**＝寬與高之中比較大的那一邊。1200×600 的照片長邊是 1200。
- **相對路徑／絕對路徑**＝相對路徑是「從某個起點算起的位置」（`data/photos/1.jpg`）；絕對路徑是「從磁碟最上層算起的完整位置」（`/Users/linjunting/personalDocAI/data/photos/1.jpg`）。
- **`Path`**＝Python 內建 `pathlib` 的路徑物件。比字串好用的地方是可以用 `/` 接路徑（`DATA_DIR / "photos"`）、可以問 `.exists()`、可以 `.mkdir()`。
- **`mkdir(parents=True, exist_ok=True)`**＝建資料夾；`parents=True` 代表「中間缺的上層資料夾也一併建」，`exist_ok=True` 代表「已經存在就當作成功、不要報錯」。
- **`unlink(missing_ok=True)`**＝刪檔案；`missing_ok=True` 代表「本來就不存在也算成功」。
- **`io.BytesIO`**＝「假裝成檔案的一段記憶體」。Pillow 的 `Image.open()` 要一個檔案，但我們手上只有 bytes，用 `BytesIO` 包一層就能直接餵給它，不必先寫到磁碟。
- **`tmp_path`**＝pytest 內建的 fixture，**每個測試函式**自動拿到一個獨立的空暫存資料夾（測完 pytest 會自己清理）。
- **`monkeypatch`**＝pytest 內建的 fixture，暫時改掉某個變數或屬性的值，**測試結束自動還原**。本專案在 `test_資料庫掛掉回500` 已經用過同一招。
- **autouse fixture**＝不必在測試函式的參數列寫出來、pytest 就會自動套用到每個測試的 fixture。`conftest.py` 的 `reset_tables`、`wire_fake_ai` 都是這種。
- **`.gitignore`**＝告訴 git「這些檔案不要納入版本控制」的清單檔。照片是二進位大檔，進 git 會讓 repo 迅速肥大，所以 `data/` 要進這份清單。
- **`uv pip install`**＝本專案用來裝套件的指令（`uv` 是比 `pip` 快很多的套件安裝工具，用法一樣）。
- **`RGB` / `RGBA` 模式**＝Pillow 描述「每個像素存哪些顏色資訊」的代號。`RGB`＝紅綠藍；`RGBA` 多一個 A（透明度）。**JPEG 格式不支援透明度**，所以要把 RGBA 的圖存成 JPEG 之前得先轉成 RGB，否則 Pillow 會報錯。

---

## ASCII 圖：`DATA_DIR` 的目錄結構與相對路徑換算

```
專案根目錄  /Users/linjunting/personalDocAI
├── app/   db/   docs/   tests/   requirements.txt   .gitignore
└── data/                    ← config.DATA_DIR 的預設值（相對目前工作目錄）
    ├── photos/              ← 原圖：檔名就是 photo.id，位元組原封不動
    │   ├── 1.jpg
    │   └── 2.png
    └── thumbs/              ← 縮圖：長邊 ≤ 512px，副檔名與原圖一致
        ├── 1.jpg
        └── 2.png
        （data/ 不進 git；.gitignore 擋掉）


  ┌──────────── 同一個值的兩種身分：DB 存相對、磁碟用絕對 ────────────┐
  │                                                                  │
  │   photo.original_path  =  "data/photos/1.jpg"   ← 永遠長這樣      │
  │                             │                     （換機器也不變）│
  │                             │                                    │
  │        absolute_path(rel)   │  把第一段 "data" 抽掉、             │
  │                             │  換成 config.DATA_DIR              │
  │                             ▼                                    │
  │   正式（uvicorn，DATA_DIR=data）                                  │
  │        → data/photos/1.jpg                                       │
  │   pytest（conftest 把 DATA_DIR 指到 tmp_path/data）               │
  │        → /private/var/…/pytest-123/test_xxx0/data/photos/1.jpg   │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘


  ┌──────────── make_thumbnail：長邊 512、等比、不放大 ────────────┐
  │                                                               │
  │   1200 × 600  ──▶  512 × 256     長邊 1200→512，短邊同比例縮   │
  │    600 × 1200 ──▶  256 × 512     直式照片同理（長邊是高）      │
  │    100 ×  50  ──▶  100 ×  50     本來就比 512 小 → 原樣不動    │
  │                                                               │
  └───────────────────────────────────────────────────────────────┘
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1〜5 是準備工作（裝套件、加設定、加測試工具），步驟 6 先把測試寫出來跑一次看它**紅**（`app/services/storage_service.py` 還不存在，會從 import 就收集失敗），步驟 7 才實作讓它**綠**。

### 步驟 1：把 Pillow 加進 `requirements.txt` 並安裝

打開 `requirements.txt`，在「--- 資料庫 ---」那一段**下面**、「--- AI 積木 ---」那一段**上面**插入新的一段：

```
# --- 影像處理 ---
Pillow>=10.0              # 產生縮圖用；只用到「開檔、等比縮小、存檔」三件事
```

存檔後安裝：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uv pip install -r requirements.txt
```

確認裝好了：

```bash
python -c "import PIL; print('Pillow', PIL.__version__)"
```

預期印出類似 `Pillow 11.x.x`（版本號只要 ≥ 10 都可以）。

### 步驟 2：`.gitignore` 加上 `data/`

打開 `.gitignore`，把內容改成（新增最後兩行）：

```
.venv/
.env
__pycache__/
*.pyc
.pytest_cache/
data/
```

**這一步一定要在寫任何檔案之前做完**，否則第一次上傳產生的照片會出現在 `git status` 裡，很容易被誤 commit 進版本庫（design1.md §6 明文禁止把二進位丟進 repo）。

驗證：

```bash
mkdir -p data/photos && touch data/photos/.keep_test
git status --short data/
rm -rf data
```

預期：`git status --short data/` **沒有任何輸出**（代表 git 完全看不到這個目錄）。驗完記得把剛剛建的 `data/` 刪掉。

### 步驟 3：`app/core/config.py` 新增 `DATA_DIR`

在檔案最上方的 import 區，把：

```python
import os

from dotenv import load_dotenv
```

改成（多一行 `Path`）：

```python
import os
from pathlib import Path

from dotenv import load_dotenv
```

然後在「--- 業務常數 ---」那一段**之內**加上（放哪個位置都不影響行為；本文件選擇放在 `ALLOWED_CONTENT_TYPES` 之前）：

```python
# 照片檔案的資料根目錄。資料庫存的是「data/photos/1.jpg」這種相對路徑，
# 實際落地位置由這個設定決定：
#   - 正式執行（uvicorn 在專案根目錄啟動）＝專案下的 data/
#   - pytest ＝ tests/conftest.py 的 isolated_data_dir 會把它改成暫存目錄
# 因為測試要能改它，程式裡一律寫 config.DATA_DIR（在函式裡即時讀），
# 絕對不要寫 from app.core.config import DATA_DIR（那樣會在 import 當下就定死值）。
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
```

### 步驟 4：`tests/conftest.py` 新增 `isolated_data_dir` 安全網

打開 `tests/conftest.py`，在 `wire_fake_ai` 這個 fixture 的**後面**（`client` fixture 之前）插入：

```python
@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """安全網：pytest 永遠不把照片檔寫進專案的 data/。

    把 config.DATA_DIR 指到 pytest 給的暫存資料夾（每個測試一個、測完自動清）。
    storage_service 的每個函式都是在呼叫當下才讀 config.DATA_DIR，所以這裡改了就生效。

    這條安全網的精神與 wire_fake_ai（絕不打真 Ollama）、reset_tables（絕不動正式庫）
    完全一樣：危險的預設值由 conftest 統一擋掉，不靠個別測試自律。

    回傳暫存的資料根目錄，需要直接檢查檔案的測試可以把它寫進參數列取用。
    """
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    yield data_dir
```

（`config` 在檔案第 12 行已經 import 過，不必再 import；`pytest` 也已在第 10 行 import。）

### 步驟 5：`tests/fakes.py` 加上「產生真圖」的小工具

打開 `tests/fakes.py`，把最上方的 import 區：

```python
import hashlib
import math
from datetime import datetime

from langchain_core.documents import Document
```

改成（多了 `io` 與 Pillow）：

```python
import hashlib
import io
import math
from datetime import datetime

from langchain_core.documents import Document
from PIL import Image
```

然後在 `FakeVLM` 這個 class 的**前面**（也就是緊接在 import 區之後）插入：

```python
# ---------- 真的圖片位元組（Pillow 讀得開）----------
# 為什麼需要它：從 Phase 17 起系統會真的用 Pillow 把上傳的 bytes 打開來做縮圖。
# b"\x89PNG fake image bytes" 這種假位元組會讓 Pillow 直接拋 UnidentifiedImageError，
# 所以凡是「預期上傳成功」的測試，一律用下面兩個函式現產一張真的小圖。


def _image_bytes(width: int, height: int, image_format: str) -> bytes:
    """畫一張純色小圖並轉成該格式的位元組。"""
    buffer = io.BytesIO()   # 假裝成檔案的一段記憶體，不必真的寫到磁碟
    Image.new("RGB", (width, height), color=(200, 120, 60)).save(
        buffer, format=image_format
    )
    return buffer.getvalue()


def make_png_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 PNG。預設 40×20，小到幾乎不花時間。"""
    return _image_bytes(width, height, "PNG")


def make_jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 JPEG。"""
    return _image_bytes(width, height, "JPEG")
```

### 步驟 6：先寫測試（紅）——新增 `tests/unit/test_storage_service_unit.py`

```python
"""storage_service 的單元測試：真的寫檔案，但只寫到 tmp_path；不碰資料庫、不碰網路。

design1.md §6：原圖 data/photos/{id}.jpg|png、縮圖 data/thumbs/{id}.jpg|png，
資料庫只存以 data/ 開頭的相對路徑。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core import config
from app.services import storage_service
from tests.fakes import make_jpeg_bytes, make_png_bytes


def _open(path):
    """把寫出去的檔案讀回來、用 Pillow 打開，確認它真的是一張圖。"""
    return Image.open(io.BytesIO(path.read_bytes()))


def test_測試期間DATA_DIR指向暫存目錄(tmp_path):
    """安全網本身也要有測試：pytest 不可以寫進專案的 data/。"""
    assert config.DATA_DIR == tmp_path / "data"


def test_副檔名對照表():
    assert storage_service._ext("image/jpeg") == "jpg"
    assert storage_service._ext("image/png") == "png"


def test_不支援的content_type直接爆錯():
    """router 早就在格式檢查擋掉了；真的走到這裡代表有 bug，不可以默默給預設值。"""
    with pytest.raises(KeyError):
        storage_service._ext("image/gif")


def test_存原圖回相對路徑且檔案內容一模一樣():
    image_bytes = make_png_bytes()

    rel_path = storage_service.save_original(1, image_bytes, "image/png")

    # 回的是「以 data/ 開頭的相對路徑」——這個字串會原封不動存進資料庫
    assert rel_path == "data/photos/1.png"
    saved = storage_service.absolute_path(rel_path)
    assert saved.is_file()
    # 原圖不轉檔、不壓縮：位元組要與上傳的完全相同
    assert saved.read_bytes() == image_bytes


def test_jpeg存成jpg副檔名():
    rel_path = storage_service.save_original(7, make_jpeg_bytes(), "image/jpeg")

    assert rel_path == "data/photos/7.jpg"
    assert storage_service.absolute_path(rel_path).is_file()


def test_縮圖長邊縮到512且維持比例():
    image_bytes = make_png_bytes(1200, 600)

    rel_path = storage_service.make_thumbnail(3, image_bytes, "image/png")

    assert rel_path == "data/thumbs/3.png"
    with _open(storage_service.absolute_path(rel_path)) as thumbnail:
        # 長邊 1200 → 512，短邊按同一個比例 600 → 256（等比，不會被壓扁）
        assert thumbnail.size == (512, 256)


def test_比512小的圖不會被放大():
    """Image.thumbnail 只縮不放——小圖原樣保留，不要浪費空間去補像素。"""
    rel_path = storage_service.make_thumbnail(4, make_png_bytes(100, 50), "image/png")

    with _open(storage_service.absolute_path(rel_path)) as thumbnail:
        assert thumbnail.size == (100, 50)


def test_原圖與縮圖各自一個資料夾不會互相覆蓋():
    image_bytes = make_png_bytes(1200, 600)

    original = storage_service.save_original(9, image_bytes, "image/png")
    thumbnail = storage_service.make_thumbnail(9, image_bytes, "image/png")

    assert original == "data/photos/9.png"
    assert thumbnail == "data/thumbs/9.png"
    # 同一個 id、兩個檔案，內容不同（縮圖被縮小了）
    assert storage_service.absolute_path(original).read_bytes() != \
        storage_service.absolute_path(thumbnail).read_bytes()


def test_absolute_path把開頭的data換成DATA_DIR():
    assert storage_service.absolute_path("data/photos/1.png") == \
        config.DATA_DIR / "photos" / "1.png"
    assert storage_service.absolute_path("data/thumbs/1.png") == \
        config.DATA_DIR / "thumbs" / "1.png"


def test_remove_if_exists刪得掉也吃得下None與不存在的路徑():
    rel_path = storage_service.save_original(5, make_png_bytes(), "image/png")
    assert storage_service.absolute_path(rel_path).is_file()

    storage_service.remove_if_exists(rel_path)
    assert not storage_service.absolute_path(rel_path).exists()

    # 上傳失敗清理時，路徑可能根本還沒產生（None）或檔案已經不在——都不可以爆錯
    storage_service.remove_if_exists(None)
    storage_service.remove_if_exists("")
    storage_service.remove_if_exists(rel_path)
```

跑一次，確認它是**紅**的：

```bash
pytest tests/unit/test_storage_service_unit.py -q
```

預期：collection error，訊息類似 `ModuleNotFoundError: No module named 'app.services.storage_service'`。這就是紅。

### 步驟 7：實作（綠）——新增 `app/services/storage_service.py`

```python
"""照片檔案的落地：寫原圖、產縮圖、換算路徑、失敗清理。

分層：本模組只做檔案操作，不碰資料庫、不碰 HTTP。
「什麼時候呼叫、失敗了怎麼收拾」由 api/routers/photos.py 決定（Phase 19）。

路徑約定（design1.md §6）：
  資料庫存的一律是「以 data/ 開頭的相對路徑」，例如 data/photos/1.jpg。
  實際落地位置＝把開頭那段 data 換成 config.DATA_DIR。
  這樣資料庫裡的值不隨執行環境改變（正式在專案下、pytest 在暫存目錄）。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.core import config

# 資料庫相對路徑固定的第一段；換算實際位置時由 config.DATA_DIR 取代它
DB_ROOT = "data"
# 兩個子資料夾
ORIGINAL_DIR = "photos"
THUMBNAIL_DIR = "thumbs"

# 縮圖長邊上限（px）。等比縮小、絕不放大——design1.md 沒有多尺寸需求，就這一種
THUMBNAIL_MAX_SIDE = 512

# content_type → 副檔名。清單與 config.ALLOWED_CONTENT_TYPES 一致
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}
# 副檔名 → Pillow 的格式代號（存檔時要指定，不能靠副檔名猜）
PIL_FORMATS = {"jpg": "JPEG", "png": "PNG"}


def _ext(content_type: str) -> str:
    """image/jpeg → "jpg"、image/png → "png"。

    清單外的 content_type 早在 router 的格式檢查（415）就被擋掉了；
    真的走到這裡代表有 bug，讓 KeyError 直接炸出來，不要默默給預設值。
    """
    return EXTENSIONS[content_type]


def absolute_path(rel_path: str) -> Path:
    """把資料庫存的相對路徑換算成實際檔案位置。

    "data/photos/1.jpg" → config.DATA_DIR / "photos" / "1.jpg"

    每次呼叫都重新讀 config.DATA_DIR（不在 import 時定死），
    測試才能用 monkeypatch 把它指到暫存目錄。
    """
    parts = Path(rel_path).parts
    if parts and parts[0] == DB_ROOT:
        parts = parts[1:]
    return Path(config.DATA_DIR).joinpath(*parts)


def _prepare(photo_id: int, content_type: str, sub_dir: str) -> tuple[str, Path]:
    """算出相對路徑與實際位置，並把資料夾先建好。"""
    rel_path = f"{DB_ROOT}/{sub_dir}/{photo_id}.{_ext(content_type)}"
    target = absolute_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return rel_path, target


def save_original(photo_id: int, image_bytes: bytes, content_type: str) -> str:
    """把原圖原封不動寫成檔案，回傳要存進資料庫的相對路徑。

    不轉檔、不壓縮、不改尺寸——使用者上傳什麼就存什麼。
    """
    rel_path, target = _prepare(photo_id, content_type, ORIGINAL_DIR)
    target.write_bytes(image_bytes)
    return rel_path


def make_thumbnail(photo_id: int, image_bytes: bytes, content_type: str) -> str:
    """產生縮圖（長邊最多 512px、等比、不放大），回傳相對路徑。

    Image.thumbnail() 是「就地修改」：它直接把圖改小，不回傳新物件；
    而且本來就小於上限的圖不會被放大，所以小圖原樣保留。
    """
    rel_path, target = _prepare(photo_id, content_type, THUMBNAIL_DIR)

    # BytesIO＝把手上的 bytes 包成「假裝是檔案」的物件，直接餵給 Pillow
    with Image.open(io.BytesIO(image_bytes)) as image:
        thumbnail = image.copy()   # 複製一份，離開 with 之後才還能繼續用

    thumbnail.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE))

    image_format = PIL_FORMATS[_ext(content_type)]
    if image_format == "JPEG" and thumbnail.mode != "RGB":
        # JPEG 不支援透明度：帶 A（透明）或調色盤模式的圖要先轉成 RGB 才存得下去
        thumbnail = thumbnail.convert("RGB")

    thumbnail.save(target, format=image_format)
    return rel_path


def remove_if_exists(rel_path: str | None) -> None:
    """刪掉一個檔案；路徑是 None／空字串／檔案本來就不在，都當作成功。

    上傳流程失敗時要把已經寫出去的檔案清乾淨（Phase 19），
    那個情境下「還沒產生路徑」與「檔案已不在」都是正常狀況，不可以再爆一次錯。
    """
    if not rel_path:
        return
    absolute_path(rel_path).unlink(missing_ok=True)
```

### 步驟 8：跑測試看它轉綠

```bash
pytest tests/unit/test_storage_service_unit.py -v
```

預期最後一行：`10 passed`（10 個測試函式）。

### 步驟 9：全量回歸

```bash
pytest -q
```

預期：**基線顆數 ＋ 10**，全綠。本 phase 沒有改任何對外行為（沒動 router、沒動 schema、沒動既有服務），所以既有測試一顆都不該變紅。

### 步驟 10：手動確認正式路徑真的會寫到專案的 `data/`

自動化測試永遠寫在暫存目錄，所以「正式執行時真的會寫進 `data/`」要手動確認一次：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from app.services import storage_service
from tests.fakes import make_png_bytes

original = storage_service.save_original(999, make_png_bytes(1200, 600), "image/png")
thumbnail = storage_service.make_thumbnail(999, make_png_bytes(1200, 600), "image/png")
print("原圖相對路徑：", original)
print("縮圖相對路徑：", thumbnail)
print("原圖實際位置：", storage_service.absolute_path(original).resolve())
print("縮圖實際位置：", storage_service.absolute_path(thumbnail).resolve())
PY
ls -l data/photos data/thumbs
git status --short          # data/ 不該出現在這裡
rm -rf data                 # 手動測試的殘留清掉
```

預期：
- 兩個相對路徑分別是 `data/photos/999.png`、`data/thumbs/999.png`
- 兩個實際位置都在 `/Users/linjunting/personalDocAI/data/…`
- `ls` 看得到兩個檔案，縮圖明顯比原圖小
- `git status --short` **沒有任何 `data/` 相關的行**

---

## 驗收清單

- [ ] `requirements.txt` 有 `Pillow>=10.0`，且 `python -c "import PIL"` 不報錯
- [ ] `.gitignore` 含 `data/`；建一個 `data/` 後 `git status --short data/` 無輸出
- [ ] `app/core/config.py` 有 `DATA_DIR = Path(os.getenv("DATA_DIR", "data"))`
- [ ] `tests/conftest.py` 有 autouse 的 `isolated_data_dir`，把 `config.DATA_DIR` 指到 `tmp_path`
- [ ] `tests/fakes.py` 有 `make_png_bytes()` 與 `make_jpeg_bytes()`，產生的是 Pillow 打得開的真圖
- [ ] `app/services/storage_service.py` 五個函式都在：`_ext`、`save_original`、`make_thumbnail`、`absolute_path`、`remove_if_exists`
- [ ] 縮圖長邊確實是 512、等比、不放大（`pytest tests/unit/test_storage_service_unit.py -v` → `10 passed`）
- [ ] 沒有任何地方寫 `from app.core.config import DATA_DIR`（那樣測試就改不動了）：
      ```bash
      grep -rn "from app.core.config import" app/ tests/ --include="*.py" || echo "OK：全部走 config.XXX"
      ```
      預期印出 `OK：全部走 config.XXX`
- [ ] SQL 依然只出現在 repository 一個檔案（本 phase 不該碰到 SQL）：
      ```bash
      grep -rlnE "SELECT |INSERT INTO|UPDATE |DELETE FROM|TRUNCATE" app/ --include="*.py"
      ```
      預期輸出只有一行 `app/repositories/photo_repository.py`
- [ ] 本 phase **沒有**新增任何 HTTP 端點：
      ```bash
      grep -rn "@router\.\|@app\." app/ --include="*.py" | wc -l
      ```
      預期數字與開工前相同（Phase 19 才會增加）
- [ ] 步驟 10 的手動確認四項全部符合預期，且測完已 `rm -rf data`
- [ ] **全量 `pytest -q` 全綠**，顆數＝開工前基線 ＋ 10
- [ ] git commit：
      ```bash
      cd /Users/linjunting/personalDocAI
      git add requirements.txt .gitignore app/core/config.py app/services/storage_service.py \
              tests/conftest.py tests/fakes.py tests/unit/test_storage_service_unit.py
      git commit -m "feat: Phase 17 檔案儲存服務——原圖原樣落地＋Pillow 縮圖（長邊 512、等比不放大）、DB 存 data/ 開頭相對路徑、conftest 把 DATA_DIR 隔離到 tmp_path，+10 tests"
      ```

---

## 常見問題

**Q1：測試報 `PIL.UnidentifiedImageError: cannot identify image file`。**
你把假位元組（`b"\x89PNG fake"`）餵給 Pillow 了。凡是會走到 `make_thumbnail` 的測試，圖片位元組一律用 `tests/fakes.py` 的 `make_png_bytes()` / `make_jpeg_bytes()` 現產。這也是本 phase 特地加那兩個小工具的原因。

**Q2：為什麼縮圖不順便存成 WebP／不順便壓縮品質／不順便存多種尺寸？**
design1.md 沒有要求，就是不做。瀏覽頁只需要一種尺寸的縮圖，多做的每一種都要多一份儲存、多一段程式碼、多一組測試——典型的過度設計。

**Q3：`save_original` 為什麼不驗證「這真的是一張圖」？**
格式檢查（415）在 router 已經做了，判斷依據是 `content_type`（design.md 的既有行為，Phase 19 不改它）。若使用者硬把 `.txt` 改名成 `.png` 上傳，`make_thumbnail` 會在 Pillow 那一步爆錯，由 Phase 19 的清理邏輯把半成品收乾淨並回 500。**不要**在這裡另外發明一種「圖片內容驗證」錯誤碼——design1.md §12 的錯誤表沒有那一列。

**Q4：`DATA_DIR` 預設是相對路徑 `data`，如果我從別的目錄啟動 uvicorn 會怎樣？**
檔案會寫到那個目錄底下的 `data/`，跟專案的 `data/` 不是同一個。本專案的既有慣例是「在專案根目錄啟動」（`uvicorn app.main:app --reload --port 8000`），照做就沒事。真的需要固定位置時，在 `.env` 加一行絕對路徑即可：`DATA_DIR=/Users/linjunting/personalDocAI/data`。

**Q5：`isolated_data_dir` 會不會拖慢測試？**
不會。`tmp_path` 只是建一個空資料夾，沒有 I/O 成本；而且大多數測試根本不會寫檔（不碰上傳流程就不會產生任何檔案）。

**Q6：為什麼 `absolute_path` 要用 `Path(rel_path).parts` 這麼繞，不直接字串取代？**
因為 `"data/photos/1.jpg".replace("data", DATA_DIR)` 會把**路徑中間**出現的 `data` 也換掉（例如未來有人把資料夾取名 `metadata`）。用 `parts` 只處理「第一段」，語意精確得多。

**Q7：可以順便寫一個「清掉沒人用的孤兒檔案」的維護指令嗎？**
不可以。刪除照片這件事 design1.md §15 明訂本增量不做，孤兒檔案自然也不會產生（Phase 19 的失敗路徑會自己清乾淨）。

**Q8：`thumbnail = image.copy()` 那一行是必要的嗎？**
是。`Image.open()` 是**惰性**的——它不會馬上把整張圖讀進記憶體，離開 `with` 區塊、底層的 `BytesIO` 關掉之後就讀不到像素了。`copy()` 會強制把資料讀進來並複製一份，之後才能安全地縮圖與存檔。

---

## 完成後的專案狀態

系統多了一層「照片檔案怎麼存」的能力：原圖原樣落地、縮圖等比縮到長邊 512、資料庫只需要記一串 `data/…` 開頭的相對路徑，而且 pytest 保證不會把測試垃圾寫進專案。`data/` 已被 git 忽略。

但目前**還沒有人呼叫它**——上傳流程沒改、也還沒有讀圖端點。接下來 Phase 18 讓 VLM 從現有資料夾清單裡推薦一個，Phase 19 才把本 phase 的三個函式接進上傳流程並開出 `GET /photos/{id}/thumbnail`、`GET /photos/{id}/image` 兩個端點。

測試累計 ＝ 開工前基線 ＋ **10**。
