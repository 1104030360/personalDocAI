# Phase 76：入庫任務拆成看圖與落庫

> 🎯 **提醒：這是 side project，不要過度設計。** 本 phase 是**純重構**——
> 本 phase 特別**不要**做的四件事：
> ① 不要改任何行為（連 log 的字樣都不要改）；
> ② 不要「順便」優化、順便改名、順便補型別、順便把 PDF 那段也抽成函式；
> ③ 不要動 `run_ingest_job()` 的簽章（`app/celery_app.py`、`tests/conftest.py`、
>    `tests/fakes.py`、兩個既有測試檔都靠它，動了就是一場大混亂）；
> ④ 不要碰 AWS（★G1 之前一行 AWS 指令都不准打，design6 §0 禁止第 1 條）。

> 🎯 **一句話目標：** 把 `app/services/ingest_job.py` 裡幾段藏在私有函式裡的邏輯，
> 抽成**五個公開、可重用的積木**——`load_prompt_context()`／`embed_understanding()`／
> `insert_photo_with_files()`／`finish_image_job()`／`fail_job()`——
> 讓 Phase 79 的雲端路可以直接拿來用。**對外行為零改變；既有測試（含 74／75 新增的 21 顆）
> 一顆都不能改——與開工快照相減後，`tests/` 只准多出 `test_ingest_job.py` 的追加、而且零刪除行。**

**為什麼要做這個：**

增量六的雲端路（Phase 79）長這樣：非敏感的照片送去 S3 → 遠端工人看圖 →
把結果寫成 `result.json` 放回 S3 → 本機拿回來 → **然後呢？**

然後要做的事，跟現在 `run_ingest_job()` 「看圖成功之後」那一段**逐字相同**：

```text
本機路（現在）                                雲端路（Phase 79 之後）
  看圖（本機 Ollama）                           看圖（遠端工人，結果從 S3 拿回來）
  轉向量（bge-m3）→ INSERT ＋ 原圖 ＋ 縮圖   ←── 這三段一模一樣 ──→   同左
  → 刪 staging → 刪 job
```

問題是那三段現在全都埋在 `_run_image_job()` 裡面，前面還掛著底線（Python 的慣例：
**底線開頭 ＝ 這是我自己內部用的，別人不要碰**）。Phase 79 只有兩條路可以走：

1. **複製一份**到 `gated_ingest.py`——於是專案裡有兩份「INSERT → 存原圖 → 產縮圖 →
   失敗清乾淨」的同款程式碼。哪天有人改了其中一份（例如加一個建議欄位），
   另一份會安靜地留在舊行為。這正是產品負責人明令不要的**「過渡產物」**。
2. **先把它抽成積木**，兩條路共用同一支。← **本 phase 做的就是這件事。**

**這一支的價值在「之後」，不在「現在」。** 做完之後專案的行為一個字都不會變，
`pytest -q` 只會多 4 顆（針對積木本身的單元測試）。它是為了讓 Phase 79 只寫「新的東西」，
而不是「新的東西 ＋ 一份複製品」。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **重構（refactor）** | 「**只改結構、不改行為**」的修改。做完之後外面的人（使用者、其他程式、既有測試）感覺不到任何差別。判斷一次修改是不是重構，最硬的標準就是：**既有測試一顆都不必改** |
| **積木（building block）** | 本文件對「抽出來、可以被好幾個地方重複呼叫的小函式」的稱呼：做一件事、參數明確、不知道自己被誰呼叫 |
| **公開 vs 私有（底線）** | Python 沒有真的「private」，靠命名慣例：`_foo` 開頭有底線 ＝「這是內部細節，外面不要依賴它」；`foo` 沒底線 ＝「這是可以被別人用的」。本 phase 把兩支從 `_foo` 改成 `foo`，意思就是「從今天起它是公開契約了」 |
| **`@dataclass`** | Python 的「資料類別」：宣告幾個欄位，它自動幫你生出 `__init__`／`__repr__`／`__eq__`。本專案已經用過（`ai_timing.AiTarget` 就是 `frozen=True, slots=True` 的同款寫法；`camera_session_service.CameraSession` 是一般寫法） |
| **`frozen=True` ／ `slots=True`** | dataclass 的兩個選項：前者「建好之後不能**重新指派欄位**」（⚠ 不擋「改清單裡的內容」）；後者不配 `__dict__`，省記憶體，而且**打錯欄位名會當場 `AttributeError`** |
| **接縫（seam）** | 程式裡「可以把真東西換成假東西」的那個點。本模組一律用 `staging_service.remove_staging(...)` 這種「模組.函式」的寫法呼叫別人，名字在**呼叫當下**才被解析——所以測試（或 §6 的離線 harness）只要把模組上的那個屬性換掉，就攔得到呼叫、不必碰真檔案或真資料庫。pytest 的 `monkeypatch.setattr(...)` 做的就是這件事，而且測試結束會自動還原 |
| **離線 harness** | 一支「不靠 pytest、不碰資料庫」的檢查腳本：把重構前後兩份程式碼用同一套假件跑同樣的情境，逐字比對兩邊做了什麼。它補的是「Docker 沒開時也能先驗行為沒變」這個洞；**它不取代全量 pytest**（§6 有一條專門跑它） |

---

## 1. 對應 design6.md 章節

| 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **§11「會動到的檔」第 2 列** | `app/services/ingest_job.py`／Celery 進入點：「開頭問 gate＋D10」 | 總覽 §3.8 第 2 列裁決：`ingest_job.py` **只做純重構**，閘門另開 `gated_ingest.py`（Phase 78）——`run_ingest_job` 是 fallback 的**目的地**，必須保持一條乾淨的本機路；把閘門塞進去會讓 fallback 變成遞迴呼叫自己 |
| **D13**「本機入庫」 | 拉回 `result.json` 後，**embedding（bge-m3）與 INSERT／原圖／縮圖仍在本機** | `embed_understanding()` 與 `insert_photo_with_files()` 就是那句話的兩個積木。Phase 79 的雲端路直接呼叫它們，所以「向量一律本機」不必再寫第二次 |
| **§4「資料流與冪等」** | Fallback 與雲端路**不可兩路都 INSERT** | `finish_image_job()` 把「寫 photo_ids → 刪 staging → 刪 job」的**順序鐵律**收進一支函式，兩條路共用同一份順序，就不會有一邊寫錯 |

**本 phase 用到的 orchestrator 裁決（總覽 §10）：**

- **總覽 §10.2 追認項 H**：「design6 完全沒提『重構 `ingest_job.py`』——**Phase 76 是計畫層加的一份純重構**。
  沒有它的話，Phase 79 的『用結果落庫』只能複製一份 `_insert_photo_with_files` 與 `_fail`
  （＝兩份會漂移的同款程式碼，違反產品負責人的『不留過渡產物』）。它的驗收條件很硬：
  **對外行為零改變、既有 543 顆一顆都不能改**（與開工快照相減後 `tests/` 只多 `test_ingest_job.py`
  的改動、零刪除行）。」
  **這是計畫層的判斷，不是產品負責人的字。** 不同意的話，回本 phase 取消它，
  並接受 Phase 79 會出現一份複製品。
  > 📌 **校準註（2026-09-01）：** 上面那個「543」是**總覽寫作當下**的全量顆數。
  > 本次的執行順序是 73 → 74 → 75 → **76** → 77（dev-prompt `phase0901.md`），
  > 所以 76 開工時工作區已經有 74／75 新增的 21 顆，基線是 **564**。
  > 驗收要看的是**「與開工快照相減」的結果**（§6 用 `comm -13`），不是那個絕對數字。
- **總覽 §2.4.1**：五個積木的名稱與簽章是契約，逐字沿用。

---

## 2. 前置條件

**依賴的 phase：無**（與 74／75 是不同檔案、不同主題，總覽 §2.3 明寫「可先可後」）。
**但下游有兩個 phase 等著它：** **Phase 77** 的 `build_context(prompt_context: PromptContext)`
吃的就是本 phase 新增的 `PromptContext`（總覽 §2.2 的「依賴」欄寫的是「74、**76**」），
**Phase 78** 則同時用到 74 的閘門與 76 的積木——所以 76 一定要排在 77／78 之前。

**⚠ 本次的實際排法是「排在 75 之後」**（dev-prompt `phase0901.md` 的執行順序是
73 → 74 → 75 → **76** → 77 → …）。所以下面的基線、快照相減與顆數，
一律以「74／75 已經做完、而且**還沒 commit**（總覽 §7 鐵律 12）」為前提。

**閘門：無**（★G1 在 Phase 81 之後）。

開工前**實查**基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 容器活著（本 phase 的 4 顆新測試會真的碰測試資料庫）
docker compose ps --no-trunc      # db 要是 Up (healthy)
#    印出「Cannot connect to the Docker daemon」＝ Docker Desktop 根本沒開：先開它，再
#    docker compose -f compose.yaml up -d      # 四個服務一起拉；等 db 變 healthy 再往下
#    db 沒起來就跑 pytest，會是一整片連線錯誤——那不是程式壞了。

# ② 測試基線
pytest -q
```

預期：**`564 passed`**（＝ 543 的專案基線 ＋ Phase 74 的 11 顆 ＋ Phase 75 的 10 顆）。
**萬一你是先做本 phase、還沒做 74／75，基線就是 `543`——以你當下實查到的數字為準**，
本文件之後一律稱它「基線」；做完應該是「基線 ＋ 4」（本次的排法＝ 564 → **568**）。

```bash
# ③ 開工前快照（驗收要用「相減」）＋ 留一份重構前的原始檔
#    （§6 有三條驗收要拿它比對；放專案外面，不會被 git 看到）
git status --short -- app tests > /tmp/p76-before.txt
git diff --numstat -- tests/ > /tmp/p76-tests-before.txt   # §6「tests/ 只准動一個檔」要拿它相減
find data -type f | wc -l
cp app/services/ingest_job.py /tmp/ingest_job_before.py
wc -l /tmp/ingest_job_before.py       # 預期：512 行
```

> 📌 **為什麼一定要先留這兩份快照（本次特別重要）：** 依鐵律 12 各 phase 做完**不 commit**，
> 所以 74／75 的改動**還躺在工作區**，`git status`／`git diff` 會一起印出來。
> 開工當下 `/tmp/p76-before.txt` 裡預期會看到這幾筆（都**不是**你改的，本 phase 一個字都不要碰）：
>
> ```text
>  M app/core/config.py                      ← Phase 74
>  M app/dependencies.py                     ← Phase 74／75
>  M app/services/ai_timing.py               ← Phase 75（kind 多一個 privacy）
>  M tests/conftest.py                       ← Phase 74（wire_fake_ai 多接 get_privacy_gate）
>  M tests/fakes.py                          ← Phase 74／75
>  M tests/unit/test_ai_timing_unit.py       ← Phase 75（+1 顆）
> ?? app/services/privacy_gate.py            ← Phase 74 新建
> ?? tests/unit/test_privacy_gate_unit.py    ← Phase 74／75 新建（11＋9＝20 顆）
> ```
>
> （`git diff --numstat -- tests/` 只看得到**已追蹤**的檔，所以 `/tmp/p76-tests-before.txt`
> 裡只會有 `tests/conftest.py`、`tests/fakes.py`、`tests/unit/test_ai_timing_unit.py` 三列；
> 新建的 `test_privacy_gate_unit.py` 是未追蹤檔，不進 `git diff`，這是**正常的**，
> §6 的 `comm -13` 相減照樣成立。）

⚠️ **絕對不要同時跑兩份 pytest。**（理由同 Phase 74 §2。）

---

## 3. 範圍

### 做

1. **`app/services/ingest_job.py` 純重構**（整檔重貼，見 §4 步驟 3）：
   - 新增 `PromptContext`（`@dataclass(frozen=True, slots=True)`，四個欄位）
   - 新增 `load_prompt_context() -> PromptContext`
   - 新增 `embed_understanding(understanding, *, embeddings, inbox_name) -> list[float]`
     （**含 `ai_timing.log_ai("embed", …)`**）
   - `_insert_photo_with_files` → **改名** `insert_photo_with_files`；
     `_fail` → **改名** `fail_job`（兩支的**內容都一個字不改**）
   - 新增 `finish_image_job(job_id, photo_id, *, store, content_type)`
     （原本內嵌在 `_run_image_job` 第 ⑥ 段的三行）
   - `_understand_and_embed` 的四個清單參數收成一個 `context: PromptContext`（**仍是私有**）
   - `_run_image_job`／`_run_pdf_job` 改用上面這些積木（**名字不變、仍是私有**）
2. **`tests/integration/test_ingest_job.py` 追加 4 顆**（針對積木本身）。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 改 `run_ingest_job()` 的簽章 | 四個地方直接呼叫它：`app/celery_app.py`、`tests/conftest.py` 的 `跑完任務()`、`tests/fakes.py` 的 `EagerDispatcher`、`tests/integration/test_ingest_job*.py`。而且 design6 D10 的 fallback **就是呼叫這一支**（總覽 §2.4.1 明文「簽章不改」）。另有一顆掃碼測試 `test_任務本體只吃job_id不吃影像位元組` 用 `inspect.signature` 釘住它 |
| 把 `_run_image_job`／`_run_pdf_job`／`_understand_and_embed` 也改成公開 | 它們是「流程」不是「積木」——Phase 79 的雲端路有自己的流程（結果從 S3 來，不是從 VLM 來），不會呼叫它們。公開了只是多三個外面看得到、卻沒人該用的名字 |
| 把 PDF 的收尾也抽成 `finish_pdf_job()` | 沒有第二個呼叫端（Phase 81 的 PDF 雲端路會沿用 `pages_done`／`photo_ids` 的迴圈寫法，收尾那兩行就在迴圈後面）。**現在抽 ＝ 為了對稱而抽**，那是過度設計 |
| 順便改 log 字樣／補型別註記／改註解／調 import 順序 | log 字樣是可以被 grep 的介面；而每多改一個字，「這次紅是不是我弄的」就多一分不確定。重構要一次只做一件事。**唯一例外**：`_run_pdf_job` 第 ③ 段那句「（與現在 `photos.py` 的 `upload_photo` 讀一次、傳給每頁的作法一致）」隨著它註解的那四行一起搬進 `load_prompt_context()`，語意由該函式的 docstring 承接——而且 `photos.py::upload_photo` 早在 Phase 63 就整段刪了，那句話本來就已經過時 |
| 動 `tests/` 底下**除了 `test_ingest_job.py` 以外**的任何檔 | 這是本 phase 最硬的驗收條件：**與開工快照相減後** `tests/` 只准多出那一個檔，而且**零刪除行**（總覽 §2.7 明文；相減指令見 §6）|
| 把兩支改名函式的舊名字留成別名（`_fail = fail_job`） | 那正是「過渡產物」。專案裡沒有任何**程式碼**在用舊名字（§4 步驟 0 會實查），直接改乾淨 |
| 加 `deprecated` 註解、加 `TODO`、加「之後 Phase 79 會用到」以外的推測 | 不留佔位。要說明用途就寫在 docstring 裡，寫清楚為止 |

---

## 4. 實作步驟

> 🧪 **重構的 TDD 長得不一樣**：這裡沒有「先寫一顆會紅的測試描述新功能」——
> 因為**沒有新功能**。重構的安全網是**既有的那一整批**（專案的 543 顆 ＋ 74／75 新增的 21 顆
> ＝ 564）：改完之後它們必須一顆不差地全綠。
> 新增的 4 顆是給積木本身的契約用的（Phase 79 會直接呼叫它們，所以它們要自己有測試守著），
> 一樣先寫、先看到紅。

### - [x] 步驟 0：先實查「有沒有人在用舊名字」（決定要不要改名）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
grep -rn "_fail\|_insert_photo_with_files\|_understand_and_embed\|_run_image_job\|_run_pdf_job" tests/
```

2026-08-31 實查、**2026-09-01 校準時重跑一次結果相同**的輸出
（**只有兩行，而且兩行都在 docstring 裡、不是程式碼**）：

```text
tests/integration/test_ingest_job_pdf.py:216:    兩種都是同一個例外、同一條 _fail 路），所以整合層驗 b"not a pdf" 這一條就夠。
tests/integration/test_ingest_job_pdf.py:239:    半成品由 _insert_photo_with_files 自己清乾淨，所以不會留孤兒列或孤兒檔。
```

**判讀規則：** grep 出來的若是**程式碼**（例如 `ingest_job._fail(...)`），那個私有名字就
**保留不改**，只把內容換成呼叫新積木（不然那顆測試就得跟著改，違反「既有測試一顆不改」）。
上面兩行是**中文說明文字**、不是呼叫，所以**可以改名**。

⚠ **代價要說在明處：** 改名之後，那兩行註解會提到兩個已經不存在的名字
（`_fail`、`_insert_photo_with_files`）。**本 phase 不准去修它們**——
改一個字就會讓相減後的 `tests/` diff 多出一個檔案與一行刪除，
直接違反本 phase 最硬的驗收條件。這兩句過時註解記在 §8，留給日後順手修。

```bash
# 再掃一次全庫（app ＋ tests），這一條的 `_fail(` 帶括號，只抓「真的在呼叫」的地方
grep -rn "_insert_photo_with_files\|_fail(\|_understand_and_embed\|_run_image_job\|_run_pdf_job" \
  app tests | grep -v "app/services/ingest_job.py"
```

2026-09-01 實查輸出（**恰好兩行，而且兩行都是註解／docstring，兩行都不要改**）：

```text
app/static/progress_panel.js:110:  //   _understand_and_embed() 的迴圈才寫成 1；PDF 拆頁期間那一段肉眼可見。）
tests/integration/test_ingest_job_pdf.py:239:    半成品由 _insert_photo_with_files 自己清乾淨，所以不會留孤兒列或孤兒檔。
```

⚠ 兩條 grep 要**合起來看**才是完整清單：這一條的 `_fail(` **帶了括號**，所以它
**不會**命中 `test_ingest_job_pdf.py:216` 那句「同一條 _fail 路」（那句後面沒有括號），
而上面第一條（`_fail` 不帶括號）會。合計就是三行註解、**零行程式碼**——
結論：`_fail` 與 `_insert_photo_with_files` 這兩個名字**可以放心改掉**。

⚠ `app/services/ingest_job.py` 自己當然滿是這些名字（實查 **18 行**），所以上面用
`grep -v` 把它排掉——本 phase 要改的就是它。

### - [x] 步驟 1：先寫測試（紅）——`tests/integration/test_ingest_job.py`

- [x] 先在 import 區**插入三行**（只准新增，不准改動或刪除既有的行）。原本是：

```python
import logging
from datetime import date, datetime

from app.core import config
```

**改成**：

```python
import logging
from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from app.core import config
```

> 為什麼是這個位置：`dataclasses` 是標準函式庫（跟 `logging`／`datetime` 同一組，字母序在 `datetime` 前面），
> `pytest` 是第三方（自己一組，夾在標準函式庫與 `app.*` 中間，前後各一個空行）。
> 放錯 `ruff check` 會報 `I001`。

- [x] 再在檔案**最後面**追加整段（4 顆測試 ＋ 一個記帳假件）：

```python


# ------------- ⑨ 五個公開積木（增量六 Phase 76 抽出來的）-------------
#
# 這一組不是重測「整條流程」（上面 ①〜⑧ 已經測過了），而是把**積木本身**釘死：
# Phase 79 的雲端路會直接呼叫它們（拿回 result.json 之後用同一套落庫），
# 所以它們的契約（讀什麼、寫什麼、順序）必須自己有測試守著。


class 記下文件的Embeddings:
    """記下「到底把哪一段文字轉成向量」的假件。

    刻意寫在本檔而不是 tests/fakes.py：只有這一顆測試需要它
    （與上面的 壞掉的Embeddings 同一個理由）。
    """

    def __init__(self) -> None:
        self.last_text: str | None = None

    def embed_query(self, text: str) -> list[float]:
        self.last_text = text
        return [0.5] * config.EMBEDDING_DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def test_load_prompt_context讀回三份清單且收件箱名稱正確():
    """三份清單各讀一次，而且收件箱名稱是**從資料夾清單裡找出來的**，不是寫死的字串。"""
    photo_repository.create_entity("我的 MacBook", "工作用筆電")

    context = ingest_job.load_prompt_context()

    assert [f["name"] for f in context.folders] == [
        "未分類",
        "收據",
        "飲食",
        "風景",
        "文件",
        "其他",
    ]
    assert context.inbox_name == "未分類"
    assert [e["name"] for e in context.entities] == ["我的 MacBook"]
    assert context.corrections == [], "還沒有人糾正過任何一張照片"

    # frozen=True：建好之後不准有人中途把裡面的東西換掉
    with pytest.raises(FrozenInstanceError):
        context.inbox_name = "收據"


def test_embed_understanding用收件箱名稱組文件():
    """向量裡的「類別」永遠是收件箱，不是模型猜的那一個（design1.md §2）。

    模型猜「收據」只會存進 suggested_category 那一欄；照片的實際歸屬與**向量**
    都是「未分類」。歸類之後 PATCH /photos/{id}/folder 會把整條重算。
    """
    embeddings = 記下文件的Embeddings()

    向量 = ingest_job.embed_understanding(收據理解, embeddings=embeddings, inbox_name="未分類")

    assert len(向量) == config.EMBEDDING_DIM
    assert embeddings.last_text is not None
    assert "類別: 未分類" in embeddings.last_text
    assert "類別: 收據" not in embeddings.last_text, "模型猜的類別不可以進向量"
    assert 收據理解.text in embeddings.last_text
    assert "地點: Target" in embeddings.last_text
    assert "物品: 可樂、洋芋片" in embeddings.last_text
    assert "時間: 2026-08-10" in embeddings.last_text


def test_finish_image_job的順序是先寫photo_ids再刪staging最後刪job(monkeypatch):
    """三步的順序是鐵律（design5.md §4.4）。

    photo_ids 一定要在刪 staging 之前寫進去：順序反過來的話，
    「剛好在這兩步之間被殺掉」的重送會找不到冪等依據，同一張照片就會被插第二次。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    順序: list[str] = []

    真的update = store.update
    真的delete = store.delete
    真的remove = staging_service.remove_staging

    def 記錄update(這個job_id, **fields):
        if "photo_ids" in fields:
            順序.append("寫photo_ids")
        return 真的update(這個job_id, **fields)

    def 記錄delete(這個job_id):
        順序.append("刪job")
        return 真的delete(這個job_id)

    def 記錄remove(這個job_id, content_type):
        順序.append("刪staging")
        return 真的remove(這個job_id, content_type)

    monkeypatch.setattr(store, "update", 記錄update)
    monkeypatch.setattr(store, "delete", 記錄delete)
    # ingest_job 是用「模組屬性」呼叫 staging_service.remove_staging()，
    # 名字在**呼叫當下**才解析，所以換掉模組上的那個屬性就攔得到。
    monkeypatch.setattr(staging_service, "remove_staging", 記錄remove)

    ingest_job.finish_image_job(job_id, 7, store=store, content_type="image/png")

    assert 順序 == ["寫photo_ids", "刪staging", "刪job"]
    assert store.get(job_id) is None, "成功＝刪掉這筆 job（design5.md §4.3）"


def test_fail_job標failed但不刪job():
    """失敗的那一列要留在進度面板上，等人按 × 才消失（design5.md §4.3）。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)

    ingest_job.fail_job(job_id, "測試用的失敗訊息", store=store, content_type="image/png")

    job = store.get(job_id)
    assert job is not None, "失敗的 job 不可以被刪掉"
    assert job["status"] == "failed"
    assert job["error"] == "測試用的失敗訊息"
    assert job["photo_ids"] == []
    assert store.list_open() == [job]
    assert not staging_service.staging_path(job_id, "image/png").exists(), "staging 要清掉"
```

### - [x] 步驟 2：跑它，確認是**紅的**

```bash
pytest tests/integration/test_ingest_job.py -q
```

預期：**4 顆紅、其餘全綠**，錯誤字樣是四個「還不存在的名字」：

```text
E   AttributeError: module 'app.services.ingest_job' has no attribute 'load_prompt_context'
E   AttributeError: module 'app.services.ingest_job' has no attribute 'embed_understanding'
E   AttributeError: module 'app.services.ingest_job' has no attribute 'finish_image_job'
E   AttributeError: module 'app.services.ingest_job' has no attribute 'fail_job'
```

### - [x] 步驟 3：綠——整份換掉 `app/services/ingest_job.py`

把 `/Users/linjunting/personalDocAI/app/services/ingest_job.py` **整份內容**換成下面這一份。

**先看對照表**（左邊是重構前的東西，右邊是它搬去哪裡）：

| 重構前 | 重構後 | 內容有沒有改 |
|---|---|---|
| `_insert_photo_with_files(...)` | **`insert_photo_with_files(...)`**（去底線） | **一個字都沒改**（只有 docstring 多一段說明為什麼公開） |
| `_fail(job_id, message, *, store, content_type)` | **`fail_job(job_id, message, *, store, content_type)`** | **一個字都沒改** |
| `_run_image_job` 第 ⑥ 段那三行（`store.update(photo_ids=…)` → `staging_service.remove_staging(…)` → `store.delete(…)`） | **`finish_image_job(job_id, photo_id, *, store, content_type)`** | 三行原樣搬進去；順序鐵律寫進 docstring |
| `_run_image_job` 第 ③ 段與 `_run_pdf_job` 第 ③ 段那四行（`list_folders` ／ `list_entities` ／ `recent_corrections` ／ `next(... is_inbox ...)`） | **`load_prompt_context() -> PromptContext`**（新增 `@dataclass PromptContext`） | 四行原樣搬進去，回傳收成一個小物件。⚠ `_run_pdf_job` 那邊多的一句註解「（與現在 `photos.py` 的 `upload_photo` 讀一次、傳給每頁的作法一致）」跟著搬走（`photos.py::upload_photo` 已於 Phase 63 刪除，這句本來就過時），語意由新函式的 docstring 承接 |
| `_understand_and_embed` 後半段（`parse_content_time` → `build_document` → `with ai_timing.log_ai("embed", …)` → `embed_document`） | **`embed_understanding(understanding, *, embeddings, inbox_name)`** | 原樣搬進去；**唯一的差別見下面那個 ⚠** |
| `_understand_and_embed(..., folders=, entities=, corrections=, inbox_name=)` | `_understand_and_embed(..., context=PromptContext)`（**仍然私有**） | 只是把四個參數收成一個 |
| `_run_image_job` ／ `_run_pdf_job` | 名字不變（**仍然私有**），改用上面的積木 | 只換呼叫方式 |
| `run_ingest_job(...)` | **一個字都沒改**（簽章與內容都是） | 沒有 |

> ⚠ **唯一一處「嚴格說起來不是逐字相同」的地方，說在明處：**
> 重構前，`build_document()` 那幾行在 `try` **外面**（只有 `embed_document` 被 `try` 包住）；
> 重構後它們一起被搬進 `embed_understanding()`，而呼叫端把整支包在 `try` 裡。
> 差別只發生在「`build_document()` 自己爆炸」的情況——它是純字串串接，實務上不會發生；
> 而萬一真的發生，新行為（算這次 attempt 失敗、重試）**比舊行為（整個 worker 任務拋例外）更好**。
> §6 的「離線行為等價 harness」把重構前後兩份程式碼用同一套假件跑 14 種情境、逐筆比對呼叫順序與 log，
> 全部相同（審稿時實測）——就是在證明這一處不影響任何現有路徑。

```python
"""照片入庫的任務本體：一個檔案 ＝ 一次 run_ingest_job（design5.md D11／D15）。

★ 這個模組**不知道 HTTP 是什麼，也不知道 Celery 是什麼。**
  它只吃一個 job_id，其餘全部從參數拿（store／vlm／embeddings／now）。
    - Celery 任務（Phase 65）＝薄薄一層：組好那四個參數，呼叫這裡。
    - pytest（Phase 59）    ＝直接呼叫這裡，不啟動 worker、不連 Redis。
  這條「可替換接縫」（seam）就是 design5 D15 的全部意思。

★ 這裡**沒有 HTTPException**。
  增量五之前 photos.py 的同步上傳流程（Phase 63 已整段刪除）用
  「丟 HTTPException(422)」表達「看不懂」，
  因為那時候整段流程活在一個 HTTP 請求裡，FastAPI 會把它翻譯成回應。
  搬進 worker 之後沒有人會做那個翻譯——所以「看不懂」在這裡改用**回傳值**表達
  （`_understand_and_embed` 回 None），最終結果寫進 JobStore：
  `status="failed"` ＋ 一句給人看的短句（design5 §4.3）。

★ 重試在**函式內部**（design5.md §4.4）。
  同一張圖最多送 VLM `config.VLM_MAX_ATTEMPTS` 次（含第一次）。
  ⛔ **絕對不要**改用 Celery 的 `autoretry_for` 讓整個任務重跑——
     那會把已經 INSERT 的照片再插一次。理由與圖解見計畫文件 phase-59 §5。

★ 五個公開積木（增量六 Phase 76 抽出來的；design6 用得到）：
    load_prompt_context()     讀三份清單＋收件箱名稱
    embed_understanding()     把看圖結果轉成向量（含 ai_timing 的 embed 計時 log）
    insert_photo_with_files() INSERT → 存原圖 → 產縮圖 → UPDATE 補路徑
    finish_image_job()        單圖成功收尾（順序鐵律：photo_ids → staging → job）
    fail_job()                最終失敗收尾（刪 staging、標 failed、**不刪 job**）
  抽出來的理由：增量六的雲端路（app/services/gated_ingest.py，Phase 79）拿回
  `result.json` 之後要做的事，與這裡「看圖成功之後」那一段**逐字相同**。
  沒有這五個積木，那邊就得複製一份——兩份會慢慢漂移的同款程式碼，
  正是產品負責人明令不要的「過渡產物」。**本模組對外行為一個字都沒有改變。**

分層：本模組會呼叫 repository（寫資料庫）、storage_service（寫檔）、
staging_service（讀／刪暫存檔）、vlm_service／indexing_service（AI）。
它**不寫任何 SQL**（全站鐵律：SQL 只在 photo_repository）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.repositories import photo_repository
from app.services import (
    ai_timing,
    indexing_service,
    pdf_service,
    staging_service,
    storage_service,
    vlm_service,
)
from app.services.ingest_job_store import IngestJob, JobStore

logger = logging.getLogger(__name__)

# 看圖 prompt 要注入幾筆糾錯例子（design3.md D11／§7 的暫定 N＝5）。
# Phase 59〜62 期間 photos.py 曾短暫留著一份同名常數（舊同步流程在用）；
# Phase 63 把鏡頭端點也改走佇列、舊流程整段退役之後，**全站只剩這一份**。
FEW_SHOT_CORRECTIONS = 5

# 失敗時寫進 job["error"] 的句子。**給人看的短句**，不是 traceback（design5.md §4.3）。
# 進度面板一列就這麼寬，寫太長會被截掉，所以刻意都在 20 個字以內。
ERROR_VLM_FAILED = "AI 看不懂這張照片（已試 {attempts} 次）"
ERROR_WRITE_FAILED = "照片存檔失敗，這張沒有留下資料"

# PDF 的每一頁渲染出來都是 PNG，之後就完全是一次普通的單圖入庫
# （原圖存成 .png、讀圖端點零改動，不必為 PDF 另開一條路）
PDF_PAGE_CONTENT_TYPE = "image/png"

ERROR_PDF_UNREADABLE = "這份 PDF 讀不開或沒有內容"
ERROR_PDF_ALL_PAGES_FAILED = "PDF 每一頁 AI 都看不懂"


class _NotUnderstood(Exception):
    """「這一次 VLM 沒看懂」。只在本模組內部從 with 區塊丟到迴圈外。

    為什麼要一個例外而不是 if：計時 log 的「結束行要標 ok=false」是靠
    ai_timing 的 with 區塊捕捉例外做到的（design4.md §5.2）。
    在 with 裡面 raise，結束行才會誠實地標成失敗——這與增量四的舊同步流程
    在 with 裡面 raise HTTPException(422) 是同一個手法。
    """


@dataclass(frozen=True, slots=True)
class PromptContext:
    """組一次看圖 prompt 需要的四樣東西（增量六 Phase 76 抽出來的）。

    為什麼包成一個小物件而不是繼續傳四個參數：Phase 79 的雲端路要把前三份清單
    原樣序列化成 S3 上的 `documents/{job_id}/context.json` 交給遠端工人
    （總覽 §2.4.3），而工人要靠它組出**同一份** build_vlm_prompt()。
    四個參數散著傳的話，那邊就得自己再組一次，兩邊很容易漏掉其中一份。

    frozen=True ＝建好之後不能改（誰也不能中途把 folders 換掉）；
    slots=True  ＝不配 __dict__，省一點記憶體、而且打錯欄位名會當場 AttributeError。
    ⚠ frozen 擋的是「重新指派欄位」，**不是**「改清單裡的內容」——
      list 本身仍然是可變的。這裡沒有人會去改它，但別誤以為它是深層不可變。
    """

    folders: list[dict]
    entities: list[dict]
    corrections: list[dict]
    inbox_name: str


def load_prompt_context() -> PromptContext:
    """把看圖 prompt 要注入的三份清單各讀一次，順便找出收件箱的名稱。

    三份清單是**變數不是常數**：使用者今天自建了「專案X」資料夾或「我的 MacBook」實體，
    下一次上傳時模型就看得到它（design1.md §8、design3.md D12、D11）。

    ★ 一次任務只讀一次：PDF 的每一頁共用同一份（與增量四舊上傳流程一致）。
      每頁各讀一次不只是浪費，還會讓「同一份檔的各頁看到不一樣的清單」變成可能。
    """
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
    inbox = next(folder for folder in folders if folder["is_inbox"])
    return PromptContext(
        folders=folders,
        entities=entities,
        corrections=corrections,
        inbox_name=inbox["name"],
    )


def run_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """把一個 job 從頭做到尾。不回傳東西——結果全部寫進 JobStore 與資料庫。

    now 是**可呼叫的**（與 dependencies.get_now 同型）：
      - 正式執行傳 `get_now` 本人 → 呼叫得到 None → 上傳時間交給資料庫的 now()
      - 測試傳 FixedClock          → 呼叫得到固定時間
    這裡一定要寫 `now()` 而不是直接把 now 當值用，否則會把函式物件塞進資料庫。

    ★ 任務開頭先把 status 改成 analyzing（design5.md §4.4）：
      崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被刪：安靜結束。這不是錯誤——重送時本來就可能撞到。
        # 這裡沒有 content_type，所以連 staging 都算不出路徑；
        # 真的有殘檔就交給 Phase 58 的 24 小時掃把清（design5.md §4.1）。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    store.update(job_id, status="analyzing")

    if job["content_type"] == config.PDF_CONTENT_TYPE:
        _run_pdf_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    _run_image_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)


def _run_image_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一張 JPEG／PNG 的完整入庫（design5.md §2、§4.2）。"""
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 冪等檢查（design5.md §4.4）：已經有照片 id 了＝上一次其實做完了，
    #    只是 ack 沒送回佇列。再插一次會變成兩張，所以直接收尾就好。
    if job.get("photo_ids"):
        logger.info(
            "job %s 已有照片 %s，判定為崩潰重送，直接收尾不重做",
            job_id,
            job["photo_ids"],
        )
        staging_service.remove_staging(job_id, content_type)
        store.delete(job_id)
        return

    # ② 從暫存區把位元組讀回來。影像**從來不進 Redis、也不當 Celery 參數**
    #    （design5.md §4.1、§1.2 被否決項）。
    image_bytes = staging_service.read_staging(job_id, content_type)

    # ③ 清單各讀一次（與增量四舊上傳流程的呼叫端一字不差）：
    #    資料夾、實體、最近的糾錯例子都要注入看圖 prompt。
    context = load_prompt_context()

    # ④ 看圖＋轉向量，最多 VLM_MAX_ATTEMPTS 次
    result = _understand_and_embed(
        job_id,
        image_bytes,
        content_type,
        store=store,
        vlm=vlm,
        embeddings=embeddings,
        context=context,
    )
    if result is None:
        fail_job(
            job_id,
            ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return
    understanding, embedding = result

    # ⑤ 寫資料庫＋寫檔。這一段失敗就是最終失敗（VLM 已經成功了，重看沒有意義）
    try:
        photo_id = insert_photo_with_files(
            image_bytes,
            content_type,
            understanding,
            embedding,
            inbox_name=context.inbox_name,
            folders=context.folders,
            entities=context.entities,  # ← Phase 61 新增
            uploaded_at=now(),
        )
    except Exception:
        logger.exception("job %s 入庫寫入失敗，半成品已清乾淨", job_id)
        fail_job(job_id, ERROR_WRITE_FAILED, store=store, content_type=content_type)
        return

    # ⑥ 收尾（順序鐵律見 finish_image_job 的 docstring）
    finish_image_job(job_id, photo_id, store=store, content_type=content_type)
    logger.info(
        "job %s 入庫完成：photo_id=%d（先進「%s」，等使用者到待決定頁歸類）",
        job_id,
        photo_id,
        context.inbox_name,
    )


def _run_pdf_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一份 PDF 的完整入庫：同一個 worker 依序把每一頁看完（design5.md D11、D12）。

    ★ 一個任務 ＝ 一個檔案。**不要**把每一頁再丟成一個 Celery 任務——
      那樣同一份檔會被兩個 worker 拆開跑，進度面板畫不出「一檔一列」（§1.2 已否決）。

    ★ 重試單位是「一頁」，不是整份檔。每一頁各自最多 config.VLM_MAX_ATTEMPTS 次，
      仍失敗就**跳過那一頁**繼續下一頁（沿用 design3 起就有的 skipped_pages 語意）。
      整份 0 頁成功（或檔案根本拆不開）才整筆失敗。

    ★ 冪等（design5.md §4.4）：從 job["pages_done"] 的**下一頁**接著跑。
      pages_done ＝「已處理幾頁」，**含跳過的頁**（§4.3 原文）。
      已經成功的頁不重看、不重 INSERT，它們的 id 留在 photo_ids 裡。

    ★ 「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
      IngestJob 的欄位表是跨文件契約，不為了一個衍生值多開一欄。
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 拆頁。整份讀不開（壞檔、加密、零頁）＝這次上傳什麼都存不了
    pdf_bytes = staging_service.read_staging(job_id, content_type)
    try:
        page_images = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        logger.warning("job %s：PDF 拆頁失敗", job_id, exc_info=True)
        fail_job(job_id, ERROR_PDF_UNREADABLE, store=store, content_type=content_type)
        return

    # ② 拆得開才知道幾頁（design5.md §4.3：未拆前 page_count 可為 null）
    store.update(job_id, page_count=len(page_images))

    # ③ 清單在迴圈**外面**讀一次：整份 PDF 的每一頁共用同一份注入 prompt
    context = load_prompt_context()

    # ④ 從上次做到的地方接著跑
    photo_ids: list[int] = list(job.get("photo_ids") or [])
    already_done = job.get("pages_done") or 0
    if already_done:
        logger.info(
            "job %s：崩潰重送，已處理 %d／%d 頁，從第 %d 頁接著跑",
            job_id,
            already_done,
            len(page_images),
            already_done + 1,
        )

    # enumerate 的 start 讓頁碼從「下一頁」開始算，1 起算（與 skipped_pages 同一套）
    for page_number, page_bytes in enumerate(page_images[already_done:], start=already_done + 1):
        photo_id: int | None = None
        result = _understand_and_embed(
            job_id,
            page_bytes,
            PDF_PAGE_CONTENT_TYPE,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            context=context,
        )
        if result is None:
            logger.warning(
                "job %s：第 %d 頁試了 %d 次仍失敗，跳過這一頁",
                job_id,
                page_number,
                config.VLM_MAX_ATTEMPTS,
            )
        else:
            understanding, embedding = result
            try:
                photo_id = insert_photo_with_files(
                    page_bytes,
                    PDF_PAGE_CONTENT_TYPE,
                    understanding,
                    embedding,
                    inbox_name=context.inbox_name,
                    folders=context.folders,
                    entities=context.entities,  # ← Phase 61 新增
                    uploaded_at=now(),
                )
            except Exception:
                # 半成品已由 insert_photo_with_files 自己清乾淨（檔案＋資料列）。
                # 這一頁當成「跳過」處理，不讓它拖垮已經成功的其他頁——
                # 理由見計畫文件 phase-60 §4 步驟 3 的裁決說明。
                logger.exception(
                    "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁",
                    job_id,
                    page_number,
                )

        if photo_id is not None:
            photo_ids.append(photo_id)
        # ★ 成功或跳過都要記 pages_done，而且要與 photo_ids **同一次**寫進去：
        #   分兩次寫的話，剛好被殺在中間的重送會把同一頁再做一次。
        store.update(job_id, pages_done=page_number, photo_ids=list(photo_ids))

    # ⑤ 收尾：至少一頁成功就算整筆成功（design5.md D12）
    if not photo_ids:
        fail_job(
            job_id,
            ERROR_PDF_ALL_PAGES_FAILED,
            store=store,
            content_type=content_type,
        )
        return

    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    logger.info(
        "job %s 入庫完成：%d 頁中 %d 頁成功、%d 頁跳過（photo_ids=%s）",
        job_id,
        len(page_images),
        len(photo_ids),
        len(page_images) - len(photo_ids),
        photo_ids,
    )


def _understand_and_embed(
    job_id: str,
    image_bytes: bytes,
    content_type: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    context: PromptContext,
) -> tuple[vlm_service.PhotoUnderstanding, list[float]] | None:
    """看圖 ＋ 轉向量，最多試 config.VLM_MAX_ATTEMPTS 次；全部失敗回 None。

    一次 attempt ＝「看一次圖 ＋ 算一次向量」。兩者任一失敗都算這次失敗
    （design5.md §8 第 6 列：embedding 失敗算進 3 次），下一次從看圖重來。

    ★ 為什麼 embedding 失敗要連圖一起重看？
      因為 embedding 吃的是這次看圖的結果。只重算向量不重看圖也可以，
      但那要多一層狀態；而 3 次上限本來就是保守值，重看一次圖的成本可以接受。
      重點是**兩者都還沒 INSERT**，所以重來完全乾淨。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        # 第 1 次是 analyzing，第 2、3 次是 retrying（design5.md §4.3 的四種狀態）
        store.update(
            job_id,
            status="analyzing" if attempt == 1 else "retrying",
            attempt=attempt,
        )

        try:
            # 計時 log 走全站共用的 ai_timing（design4.md §5）。
            # target 從 vlm 物件身上拿：正式的 OllamaVLM／OllamaCloudVLM 建構時
            # 就把 backend 與 model 記在 timing_target 上，所以 worker 只要
            # 「用任務裡的 ai_backend 快照建對客戶端」，log 的 backend= 自然就對
            # （design5.md D14）。假件沒有這個屬性，會退回讀 config，不影響測試。
            with ai_timing.log_ai("vlm", target=vlm_service.vlm_timing_target(vlm)) as 計時:
                understanding = vlm.understand(
                    image_bytes,
                    content_type,
                    context.folders,
                    context.entities,
                    context.corrections,
                )
                if not understanding.understood or not understanding.text.strip():
                    計時.note = f"understood=false text_chars={len(understanding.text)}"
                    raise _NotUnderstood()
                計時.note = (
                    f"understood=true text_chars={len(understanding.text)} "
                    f"item_count={len(understanding.items)} "
                    f"category_present={'true' if understanding.category else 'false'} "
                    f"entity_present={'true' if understanding.entity else 'false'} "
                    f"task_present={'true' if understanding.task_title else 'false'}"
                )
        except _NotUnderstood:
            logger.warning("job %s：第 %d 次看圖，AI 說看不懂", job_id, attempt)
            continue
        except Exception:
            # Ollama 沒開、雲端 401／404、逾時、結構化輸出驗證不過……全算一次失敗。
            # exc_info=True 讓 traceback 進伺服器 log；它**不會**進 job["error"]。
            logger.warning("job %s：第 %d 次看圖呼叫失敗", job_id, attempt, exc_info=True)
            continue

        try:
            embedding = embed_understanding(
                understanding, embeddings=embeddings, inbox_name=context.inbox_name
            )
        except Exception:
            logger.warning("job %s：第 %d 次轉向量失敗", job_id, attempt, exc_info=True)
            continue

        return understanding, embedding

    return None


def embed_understanding(
    understanding: vlm_service.PhotoUnderstanding,
    *,
    embeddings: Embeddings,
    inbox_name: str,
) -> list[float]:
    """把一次看圖結果合併成 Document 再轉成向量。失敗就把例外往外丟。

    ★ 合併與轉向量一律用**收件箱名稱**當 category——上傳當下的向量就是「未分類」版本
      （design1.md §2；使用者到待決定頁歸類之後，PATCH 會把整條重算）。
      這也是為什麼參數是 inbox_name 而不是 understanding.category：
      模型猜的類別只會存進 suggested_category 那一欄，**不進向量**。

    ★ 計時 log 在這裡（kind=embed，backend 永遠 local）：向量必須跟庫裡既有的
      bge-m3 同源，所以 embeddings 從來不歸頁首那顆開關管。

    ★ 這一支**不吞例外**：呼叫端要自己決定「算失敗、重來一次」（_understand_and_embed）
      還是「這筆 job 失敗」（Phase 79 的雲端路）。
    """
    content_time = vlm_service.parse_content_time(understanding.content_time)
    document = indexing_service.build_document(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=content_time.isoformat() if content_time else None,
    )
    with ai_timing.log_ai(
        "embed",
        target=indexing_service.embedding_timing_target(embeddings),
    ):
        return indexing_service.embed_document(embeddings, document)


def insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    entities: list[dict],
    uploaded_at: datetime | None,
) -> int:
    """INSERT → 存原圖 → 產縮圖 → UPDATE 補路徑。任何一步失敗就清乾淨再往外丟。

    ★ 這一段是從增量四 photos.py 的舊同步上傳流程第 ★③〜⑤ 段**原封不動搬過來的**
      （對照表見計畫文件 phase-59 §4 步驟 5；該舊流程已於 Phase 63 整段刪除）：
      檔名要用 photo.id，
      而 id 是 INSERT 當下才配發的，所以只能先 INSERT、寫完檔再回來補路徑。
      這三步不是一條 SQL，沒有交易可以 rollback（交易也管不到磁碟上的檔案），
      所以失敗時自己把兩個檔案與那一列刪掉，再把原始錯誤往外丟。
      差別只有一個：往外丟之後，接住它的不再是 FastAPI（500），
      而是 `_run_image_job` 的 except（把 job 標成 failed）。

    ★ 增量六 Phase 76 把名字前面的底線拿掉（原本叫 _insert_photo_with_files）：
      雲端路（Phase 79）拿回 result.json 之後要做的事與這裡完全相同，
      共用同一支才不會出現兩份會漂移的同款程式碼。**函式內容一個字都沒改。**
    """
    # ── 三個「建議」欄位（design5.md D16）──────────────────────────────
    # 這裡寫的是「AI 當下猜了什麼」，不是「這張照片屬於什麼」。
    # 照片的實際歸屬永遠是收件箱（category／folder_id 都是「未分類」）；
    # 實體與待辦更是**一列都不寫**——那三張表要等人在待決定的彈窗按下去才有資料
    # （design5.md §4.2、design3.md D3「人確認才落庫」）。
    #
    # 為什麼非存不可：上傳改 202 之後（Phase 62），建議不會再出現在任何回應裡。
    # 不存下來的話，使用者幾分鐘後到待決定頁點開那張照片時，
    # 實體窗會少了選項①、**待辦窗會永遠不開**（開窗條件就是「有待辦建議」）。

    # ① 資料夾建議：夾回清單內，清單外一律變「未分類」。
    #    建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL（Phase 35 的規則不變）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    suggested_category = None if suggested_name == inbox_name else suggested_name

    # ② 實體建議：同樣夾回清單，但**沒有保底選項**——清單外或都不像就是 None
    #    （clamp_entity 回的是整筆 dict，這一欄只存名稱字串）。
    suggested_entity_row = vlm_service.clamp_entity(understanding.entity, entities)
    suggested_entity = suggested_entity_row["name"] if suggested_entity_row else None

    # ③ 待辦建議：判準與現在 photos.py::_task_suggestion() 逐字相同——
    #    標題是空的（沒填或只有空白）＝這張照片沒有待辦，兩欄都留 NULL。
    #    到期日沿用 parse_content_time 的寬容解析：模型回「下週三」之類推不出來的東西
    #    只是少一個日期，**絕不可以讓整張照片入不了庫**（與 content_time 同一個原則）。
    suggested_task_title: str | None = None
    suggested_task_due = None
    if understanding.task_title and understanding.task_title.strip():
        suggested_task_title = understanding.task_title.strip()
        suggested_task_due = vlm_service.parse_content_time(understanding.task_due)

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=vlm_service.parse_content_time(understanding.content_time),
        embedding=embedding,
        uploaded_at=uploaded_at,
        suggested_category=suggested_category,
        suggested_entity=suggested_entity,
        suggested_task_title=suggested_task_title,
        suggested_task_due=suggested_task_due,
    )
    photo_id = row["id"]

    original_path: str | None = None
    thumbnail_path: str | None = None
    try:
        original_path = storage_service.save_original(photo_id, image_bytes, content_type)
        thumbnail_path = storage_service.make_thumbnail(photo_id, image_bytes, content_type)
        photo_repository.update_photo_paths(
            photo_id,
            original_path=original_path,
            thumbnail_path=thumbnail_path,
            content_type=content_type,
        )
    except Exception:
        # remove_if_exists 吃得下 None（那一步還沒跑到就失敗了）與「檔案本來就不在」
        storage_service.remove_if_exists(original_path)
        storage_service.remove_if_exists(thumbnail_path)
        photo_repository.delete_photo(photo_id)
        raise

    return photo_id


def finish_image_job(job_id: str, photo_id: int, *, store: JobStore, content_type: str) -> None:
    """單圖成功的統一收尾：寫 photo_ids → 刪 staging → 刪 job。

    ★ **三步的順序是鐵律。** photo_ids 一定要在刪 staging 之前寫進去——
      順序反過來的話，「剛好在這兩步之間被殺掉」的重送會找不到冪等依據，
      於是同一張照片會被插第二次（design5.md §4.4）。

    ★ 刪掉 job ＝「成功」（design5.md §4.3：JOB_STATUSES 裡根本沒有 success）。
      所以進度面板的清單天生就不含成功的工作，前端不必自己過濾。

    ★ 只給**單圖**用。PDF 的收尾不一樣：photo_ids 是在逐頁迴圈裡跟 pages_done
      一起寫的，最後只需要刪 staging 與刪 job（見 _run_pdf_job 第 ⑤ 段）。
    """
    store.update(job_id, photo_ids=[photo_id])
    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)


def fail_job(job_id: str, message: str, *, store: JobStore, content_type: str) -> None:
    """最終失敗的統一收尾：刪 staging ＋ 把 job 標成 failed。

    **不刪 job**——失敗的那一列要留在進度面板上讓人看到，
    由使用者按 × 走 `POST /ingest-jobs/{id}/dismiss` 才消失（design5.md §4.3）。
    """
    staging_service.remove_staging(job_id, content_type)
    store.update(job_id, status="failed", error=message)
    logger.warning("job %s 最終失敗：%s", job_id, message)
```

### - [x] 步驟 4：跑測試看它轉綠

> 💡 Docker 的 db 還沒起來？可以先跑 §6 的「離線行為等價 harness」（不碰資料庫、約 10 秒）
> 確認行為沒變；但它**不取代**下面三條——db 起來之後三條都要跑，第 ③ 條才是驗收。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 本檔（既有 18 顆 ＋ 新增 4 顆）→ 預期 22 passed（`pytest --collect-only -q` 實查既有 18）
pytest tests/integration/test_ingest_job.py -q

# ② 另一個直接測任務本體的檔（PDF），一顆都不准紅 → 預期 9 passed（實查顆數，與開工前相同）
pytest tests/integration/test_ingest_job_pdf.py -q

# ③ 全量回歸——**這才是本 phase 真正的驗收**
pytest -q
```

預期尾巴：**基線 ＋ 4 ＝ `568 passed`**（本次排在 75 之後，基線 564），且 **0 skipped**。

**如果有既有測試變紅，那就不是重構，是改壞了。** 最可能的三個地方：
① `vlm.understand()` 的參數順序寫錯（必須是
   `image_bytes, content_type, folders, entities, corrections`）；
② `finish_image_job` 裡三步的順序寫反（崩潰重送那顆會紅）；
③ `load_prompt_context()` 忘了 `limit=FEW_SHOT_CORRECTIONS`（糾錯 few-shot 那幾顆會紅）。

### - [x] 步驟 5：格式與 lint

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：`All checks passed!`

### - [x] 步驟 6：**不 commit**——記下收工快照

> ⛔ **本次全程不 commit**（產品負責人指示，總覽 §7 鐵律 12）。
> 做完只要**印一顆工作樹的 tree SHA** 留著，讓 review 用「相減」看這一支到底改了什麼。
> `snapshot-tree` 只在物件庫多一顆 tree 物件，**不碰真正的 index、不建 commit、不動 stash**。

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0901/snapshot-tree        # 印出 40 個字的 tree SHA，記進交接紀錄
# review 時用：git diff -U10 <開工前的 tree> <這一顆 tree>
```

> 💡 **commit 訊息草稿先留著**（產品負責人日後指示要 commit 時再用，不要自己執行）：
>
> ```text
> refactor: Phase 76 入庫任務拆成看圖與落庫——ingest_job.py 抽出五個公開積木（PromptContext/load_prompt_context、embed_understanding（含 ai_timing embed）、insert_photo_with_files（原 _insert_photo_with_files）、finish_image_job（順序鐵律）、fail_job（原 _fail）），_understand_and_embed 四個清單參數收成 context，+4 tests；run_ingest_job 簽章不變、對外行為零改變、既有測試一顆未改
> ```
>
> 也**不要**把本計畫檔從 `unfinish/` 搬進 `finish/`——`git mv` 會直接 stage，
> 歸檔隨 commit 由產品負責人做（鐵律 12）。

---

## 5. ASCII 圖

### 圖一：重構前後——同樣的流程，只是把三段圈起來給了名字

```text
  重構前（512 行）                        重構後（595 行，行為完全相同）
  run_ingest_job                          run_ingest_job          ★簽章不變
   └─ _run_image_job                       └─ _run_image_job
        list_folders()      ┐                   load_prompt_context()  ←┐
        list_entities()     ├─ 四行              _understand_and_embed   │
        recent_corrections()│                     └ embed_understanding()│
        next(is_inbox)      ┘                    insert_photo_with_files │
        _understand_and_embed                    finish_image_job()      │
          （看圖＋build_document＋embed）         fail_job()              │
        _insert_photo_with_files            └─ _run_pdf_job              │
        store.update(photo_ids) ┐                load_prompt_context()  ←┘
        remove_staging()        ├─ 三行          （逐頁迴圈，同上）
        store.delete()          ┘
        _fail()                                五個**公開積木**（新的公開契約）
   └─ _run_pdf_job（同樣那四行）              ┌────────────────────────────┐
                                              │ load_prompt_context()      │
  ⚠ 藏在底線後面 ＝ 別人不該用                │ embed_understanding()      │
     Phase 79 只能複製一份                    │ insert_photo_with_files()  │
                                              │ finish_image_job()         │
                                              │ fail_job()                 │
                                              └──────────┬─────────────────┘
                                                 Phase 79 的 gated_ingest.py
                                                 拿回 result.json 之後直接呼叫
                                                 這五支，不必複製任何一行
```

### 圖二：`finish_image_job()` 的三步為什麼不能對調

```text
   正確：① store.update(photo_ids=[7]) → ② remove_staging() → ③ store.delete()
   寫反：① remove_staging() → ② store.update(photo_ids=[7]) → ③ store.delete()

   假設 worker 剛好在 ① 與 ② 之間被殺掉（Docker restart、機器關機），佇列會重送：

   正確順序 → job 裡已經有 photo_ids=[7] → 冪等檢查看到它
            → 「其實做完了」→ 收尾、不重做                          ✓
   寫反了   → job 裡還是 photo_ids=[]     → 冪等檢查看到空的
            → 「還沒做」→ 再看一次圖、**再 INSERT 一次**            ✗ 同一張變兩列
```

---

## 6. 驗收清單

- [x] **開工基線已實查**（`pytest -q` 的顆數；本次排在 75 之後 ＝ **564**）

- [x] **五個公開積木都在（都沒有底線），而且舊名字完全消失**（沒留成別名／過渡產物）

  ```bash
  grep -nE "^def load_prompt_context|^def embed_understanding|^def insert_photo_with_files|^def finish_image_job|^def fail_job|^class PromptContext" \
    app/services/ingest_job.py                       # 預期：六行命中
  # 只抓「定義」與「呼叫」，不抓 docstring 裡的提及
  grep -nE 'def _(fail|insert_photo_with_files)\(|[^_a-zA-Z]_(fail|insert_photo_with_files)\(' \
    app/services/ingest_job.py || echo "OK：舊名字已經不存在"     # 預期：印 OK
  ```

  ⚠ **第二條 grep 一定要帶那對括號**（校準時實測踩到）：
  `insert_photo_with_files()` 的新 docstring 裡有一句「（原本叫 `_insert_photo_with_files`）」，
  用 `grep -n "_insert_photo_with_files"` 這種寬鬆寫法會命中那一行，
  於是 `|| echo` 不會觸發，看起來像「舊名字還在」，其實只是說明文字。
  上面這條的判準是「有沒有 `def `」與「後面有沒有 `(`」＝**只看程式碼**。
  想確認它真的抓得到，拿重構前的檔跑一次：
  `grep -nE 'def _(fail|insert_photo_with_files)\(|[^_a-zA-Z]_(fail|insert_photo_with_files)\(' /tmp/ingest_job_before.py`
  （預期 **8 行命中**：2 個 def ＋ 4 次 `_fail(` ＋ 2 次 `_insert_photo_with_files(`）。

- [x] **`run_ingest_job` 的簽章一個字都沒改**

  ```bash
  diff <(grep -A 8 "^def run_ingest_job" /tmp/ingest_job_before.py) \
       <(grep -A 8 "^def run_ingest_job" app/services/ingest_job.py) \
    && echo "OK：簽章逐字相同"
  ```

  預期輸出：`OK：簽章逐字相同`（`diff` 沒有輸出代表兩邊一樣）

- [x] **兩支改名函式的「內容」逐字相同**（只有名字與 docstring 變了）

```bash
python - <<'PY'
import ast

def 函式內容(路徑, 名字):
    """回傳這支函式**去掉 docstring 之後**的程式碼（用 AST 重寫，忽略註解與排版）。"""
    tree = ast.parse(open(路徑, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 名字:
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            return ast.unparse(ast.Module(body=body, type_ignores=[]))
    raise SystemExit(f"找不到 {名字}")

舊 = "/tmp/ingest_job_before.py"
新 = "app/services/ingest_job.py"
for 舊名, 新名 in (("_insert_photo_with_files", "insert_photo_with_files"), ("_fail", "fail_job")):
    相同 = 函式內容(舊, 舊名) == 函式內容(新, 新名)
    print(f"{舊名} → {新名}：", "內容逐字相同" if 相同 else "★ 不同，請檢查 ★")
    assert 相同
PY
```

  預期輸出：

  ```text
  _insert_photo_with_files → insert_photo_with_files： 內容逐字相同
  _fail → fail_job： 內容逐字相同
  ```

- [x] **★ 離線行為等價 harness：14 種情境、重構前後逐字相同**（不碰資料庫、不需要 Docker；約 10 秒）

  這一條補的是「pytest 只能證明既有測試沒紅」這個洞：它把 `/tmp/ingest_job_before.py`（重構前）與
  `app/services/ingest_job.py`（重構後）用**同一套記帳假件**各跑 14 種情境
  （單圖 9 種 ＋ PDF 5 種，與 `test_ingest_job.py`／`test_ingest_job_pdf.py` 走的路徑一一對應），
  把兩邊「呼叫了誰、按什麼順序、寫了什麼狀態、印了什麼 log」逐筆比對——
  連 `fail_job` 那句 warning、`ai_timing` 的前後兩行都在比（只抹平每次都會變的 `elapsed_s=`）。
  哪一筆開始不同就印哪一筆，所以真的改到行為時，你看到的是「舊：… 新：…」而不是一顆看不出原因的紅。
  它**不取代**全量 pytest（沒有真的碰資料庫與 Pillow），是多一層保險，而且 Docker 沒開也跑得動。

  > ✅ **校準時（2026-09-01）已經先跑過一次**：拿 `HEAD` 的 `ingest_job.py`（512 行）當「重構前」、
  > 拿本檔 §4 步驟 3 的程式碼區塊（595 行）當「重構後」，14 行**全部「相同」**、
  > 每一行的「N 筆紀錄」與下面那份預期輸出**逐字相同**、exit code 0。
  > 也就是說：**§4 步驟 3 那份程式碼本身已經驗證過是行為等價的**，
  > 你照著貼完之後這一條應該一次就過；沒過就代表貼的時候漏掉或多打了什麼。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
"""離線行為等價 harness（Phase 76 專用）：同一套記帳假件、同樣 14 種情境，
分別餵給「重構前」與「重構後」兩份 ingest_job，把兩邊「呼叫了什麼、按什麼順序、
寫了什麼狀態、印了什麼 log」逐字比對。

不碰資料庫、不碰 Docker、不碰 Ollama、不碰 Redis——
所有會出門的東西（repository／storage／pdf）都換成記帳假件，
staging 則真的寫進一個暫存目錄（config.DATA_DIR 指過去）。
"""

import importlib.util
import logging
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from app.core import config
from app.repositories import photo_repository
from app.services import pdf_service, staging_service, storage_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM, FixedClock, ScriptedVLM

舊路徑 = "/tmp/ingest_job_before.py"
新路徑 = "app/services/ingest_job.py"


def 載入(名字, 路徑):
    spec = importlib.util.spec_from_file_location(名字, 路徑)
    module = importlib.util.module_from_spec(spec)
    # 一定要先登記進 sys.modules 再執行：@dataclass 建類別時會回頭查
    # sys.modules[cls.__module__]，沒登記會炸 AttributeError: 'NoneType' ... '__dict__'
    sys.modules[名字] = module
    spec.loader.exec_module(module)
    return module


舊 = 載入("ingest_job_before", 舊路徑)
新 = 載入("ingest_job_after", 新路徑)

收據 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
    entity="我的 MacBook",
    task_title="繳交作業三",
    task_due="2026-08-21",
)
看不懂 = PhotoUnderstanding(understood=False)
空白 = PhotoUnderstanding(understood=True, text="   ")
NOW = FixedClock(datetime(2026, 8, 18, 10, 0))
PDF = "application/pdf"


class 壞掉的Embeddings:
    def embed_query(self, text):
        raise RuntimeError("bge-m3 沒有回應")

    def embed_documents(self, texts):
        raise RuntimeError("bge-m3 沒有回應")


class 記帳Store(InMemoryJobStore):
    """InMemoryJobStore 的記帳版：每一次 update／delete 都寫進帳本（含順序）。"""

    def __init__(self, 帳本):
        super().__init__()
        self.帳本 = 帳本

    def update(self, job_id, **fields):
        self.帳本.append(("store.update", job_id, fields))
        return super().update(job_id, **fields)

    def delete(self, job_id):
        self.帳本.append(("store.delete", job_id))
        return super().delete(job_id)


class 收集log(logging.Handler):
    def __init__(self, 帳本):
        super().__init__()
        self.帳本 = 帳本

    def emit(self, record):
        # elapsed_s 每次都不一樣，抹平它；其餘一個字都不放過
        msg = re.sub(r"elapsed_s=\d+\.\d+", "elapsed_s=?", record.getMessage())
        self.帳本.append(("log", record.levelname, msg))


# 14 種情境：跟 test_ingest_job.py／test_ingest_job_pdf.py 涵蓋的路徑一一對應
情境們 = [
    ("01 單圖一次成功", dict(vlm=lambda: FakeVLM(收據))),
    ("02 單圖三次都看不懂", dict(vlm=lambda: ScriptedVLM([看不懂] * 3))),
    ("03 單圖三次呼叫都丟例外", dict(vlm=lambda: ScriptedVLM([RuntimeError("refused")] * 3))),
    ("04 單圖空白描述算看不懂", dict(vlm=lambda: ScriptedVLM([空白] * 3))),
    ("05 單圖第三次才成功", dict(vlm=lambda: ScriptedVLM([看不懂, RuntimeError("x"), 收據]))),
    ("06 單圖轉向量三次都失敗", dict(vlm=lambda: ScriptedVLM([收據] * 3), emb=壞掉的Embeddings)),
    ("07 單圖縮圖寫檔失敗", dict(vlm=lambda: FakeVLM(收據), 縮圖炸=True)),
    (
        "08 單圖崩潰重送（已有 photo_ids）",
        dict(vlm=lambda: ScriptedVLM([]), 預填={"photo_ids": [7]}),
    ),
    ("09 job 根本不存在", dict(vlm=lambda: FakeVLM(收據), 有job=False)),
    ("10 PDF 兩頁都成功", dict(ct=PDF, 頁=[b"p1", b"p2"], vlm=lambda: ScriptedVLM([收據, 收據]))),
    ("11 PDF 拆不開", dict(ct=PDF, 拆不開=True, vlm=lambda: ScriptedVLM([]))),
    (
        "12 PDF 第 2 頁三次失敗跳過",
        dict(ct=PDF, 頁=[b"p1", b"p2"], vlm=lambda: ScriptedVLM([收據, 看不懂, 看不懂, 看不懂])),
    ),
    ("13 PDF 全頁失敗", dict(ct=PDF, 頁=[b"p1", b"p2"], vlm=lambda: ScriptedVLM([看不懂] * 6))),
    (
        "14 PDF 崩潰重送從 pages_done 續跑",
        dict(
            ct=PDF,
            頁=[b"p1", b"p2"],
            vlm=lambda: ScriptedVLM([收據]),
            預填={"pages_done": 1, "photo_ids": [7]},
        ),
    ),
]

原本 = {
    "DATA_DIR": config.DATA_DIR,
    "list_folders": photo_repository.list_folders,
    "list_entities": photo_repository.list_entities,
    "recent_corrections": photo_repository.recent_corrections,
    "insert_photo": photo_repository.insert_photo,
    "update_photo_paths": photo_repository.update_photo_paths,
    "delete_photo": photo_repository.delete_photo,
    "save_original": storage_service.save_original,
    "make_thumbnail": storage_service.make_thumbnail,
    "remove_if_exists": storage_service.remove_if_exists,
    "render_pages": pdf_service.render_pages,
    "read_staging": staging_service.read_staging,
    "remove_staging": staging_service.remove_staging,
}


def 跑一次(模組, 情境):
    帳本 = []
    config.DATA_DIR = Path(tempfile.mkdtemp())
    序號 = iter(range(101, 999))

    def list_folders():
        帳本.append(("repo.list_folders",))
        return [
            {"id": i + 1, "name": n, "description": d, "is_inbox": inbox, "photo_count": 0}
            for i, (n, d, inbox) in enumerate(photo_repository.DEFAULT_FOLDERS)
        ]

    def list_entities():
        帳本.append(("repo.list_entities",))
        return [{"id": 1, "name": "我的 MacBook", "description": "工作用筆電"}]

    def recent_corrections(limit):
        帳本.append(("repo.recent_corrections", limit))
        return []

    def insert_photo(**kw):
        embedding = kw.pop("embedding")
        row = {"id": next(序號)}
        帳本.append(("repo.insert_photo", kw, len(embedding), round(sum(embedding), 6), row["id"]))
        return row

    def update_photo_paths(photo_id, **kw):
        帳本.append(("repo.update_photo_paths", photo_id, kw))

    def delete_photo(photo_id):
        帳本.append(("repo.delete_photo", photo_id))

    def save_original(photo_id, image_bytes, content_type):
        帳本.append(("storage.save_original", photo_id, image_bytes, content_type))
        return f"data/photos/{photo_id}.x"

    def make_thumbnail(photo_id, image_bytes, content_type):
        if 情境.get("縮圖炸"):
            帳本.append(("storage.make_thumbnail 炸", photo_id))
            raise RuntimeError("磁碟壞了")
        帳本.append(("storage.make_thumbnail", photo_id, content_type))
        return f"data/thumbs/{photo_id}.x"

    def remove_if_exists(path):
        帳本.append(("storage.remove_if_exists", path))

    def render_pages(pdf_bytes):
        帳本.append(("pdf.render_pages", pdf_bytes))
        if 情境.get("拆不開"):
            raise pdf_service.PdfUnreadableError("讀不開")
        return list(情境["頁"])

    def read_staging(job_id, ct):
        帳本.append(("staging.read", job_id, ct))
        return 原本["read_staging"](job_id, ct)

    def remove_staging(job_id, ct):
        帳本.append(
            ("staging.remove", job_id, ct, staging_service.staging_path(job_id, ct).exists())
        )
        return 原本["remove_staging"](job_id, ct)

    photo_repository.list_folders = list_folders
    photo_repository.list_entities = list_entities
    photo_repository.recent_corrections = recent_corrections
    photo_repository.insert_photo = insert_photo
    photo_repository.update_photo_paths = update_photo_paths
    photo_repository.delete_photo = delete_photo
    storage_service.save_original = save_original
    storage_service.make_thumbnail = make_thumbnail
    storage_service.remove_if_exists = remove_if_exists
    pdf_service.render_pages = render_pages
    staging_service.read_staging = read_staging
    staging_service.remove_staging = remove_staging

    handler = 收集log(帳本)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        ct = 情境.get("ct", "image/png")
        store = 記帳Store(帳本)
        job_id = "沒有這筆"
        if 情境.get("有job", True):
            job_id = "job-1"
            staging_service.save_staging(job_id, ct, b"fake-bytes")
            store.create(
                job_id=job_id,
                filename="a.png",
                content_type=ct,
                ai_backend="local",
                source="upload",
            )
            if 情境.get("預填"):
                store.update(job_id, **情境["預填"])
        emb = 情境.get("emb", FakeEmbeddings)()
        模組.run_ingest_job(job_id, store=store, vlm=情境["vlm"](), embeddings=emb, now=NOW)
        帳本.append(("final.job", store.get(job_id)))
        帳本.append(("final.staging_exists", staging_service.staging_path(job_id, ct).exists()))
    finally:
        root.removeHandler(handler)
        for 名, 值 in 原本.items():
            if 名 == "DATA_DIR":
                config.DATA_DIR = 值
            elif 名 in ("save_original", "make_thumbnail", "remove_if_exists"):
                setattr(storage_service, 名, 值)
            elif 名 == "render_pages":
                pdf_service.render_pages = 值
            elif 名 in ("read_staging", "remove_staging"):
                setattr(staging_service, 名, 值)
            else:
                setattr(photo_repository, 名, 值)
    return 帳本


全部相同 = True
for 名字, 情境 in 情境們:
    舊帳 = 跑一次(舊, 情境)
    新帳 = 跑一次(新, 情境)
    相同 = 舊帳 == 新帳
    全部相同 &= 相同
    print(f"{名字:<34} {len(舊帳):>3} 筆紀錄  {'相同' if 相同 else '★ 不同 ★'}")
    if not 相同:
        for i, (a, b) in enumerate(zip(舊帳, 新帳)):
            if a != b:
                print(f"    第 {i} 筆開始不同：\n      舊：{a}\n      新：{b}")
                break
        if len(舊帳) != len(新帳):
            print(f"    筆數不同：舊 {len(舊帳)}、新 {len(新帳)}")
print("=" * 60)
print("14 種情境全部逐字相同 ＝ 行為等價" if 全部相同 else "★ 有情境不同，重構改到行為了 ★")
raise SystemExit(0 if 全部相同 else 1)
PY
```

  預期輸出（14 行都是「相同」、最後一行「行為等價」、exit code 0；
  「N 筆紀錄」是那條路徑上呼叫＋log 的總數，兩邊一定一樣，數字不同代表你改了假件不是改了程式）：

  ```text
  01 單圖一次成功                           20 筆紀錄  相同
  02 單圖三次都看不懂                         22 筆紀錄  相同
  03 單圖三次呼叫都丟例外                       22 筆紀錄  相同
  04 單圖空白描述算看不懂                       22 筆紀錄  相同
  05 單圖第三次才成功                         28 筆紀錄  相同
  06 單圖轉向量三次都失敗                       28 筆紀錄  相同
  07 單圖縮圖寫檔失敗                         22 筆紀錄  相同
  08 單圖崩潰重送（已有 photo_ids）              7 筆紀錄  相同
  09 job 根本不存在                         3 筆紀錄  相同
  10 PDF 兩頁都成功                        32 筆紀錄  相同
  11 PDF 拆不開                           9 筆紀錄  相同
  12 PDF 第 2 頁三次失敗跳過                  36 筆紀錄  相同
  13 PDF 全頁失敗                         40 筆紀錄  相同
  14 PDF 崩潰重送從 pages_done 續跑          24 筆紀錄  相同
  ============================================================
  14 種情境全部逐字相同 ＝ 行為等價
  ```

  ⚠ 這支腳本真的抓得到「順序寫反」：審稿時把 `finish_image_job` 的前兩行對調再跑一次，
  情境 01 與 05 立刻印出 `★ 不同 ★`，並指出第 14 筆從 `('store.update', 'job-1', {'photo_ids': [101]})`
  變成了 `('staging.remove', 'job-1', 'image/png', True)`。想親眼看一次可以照做，**看完記得改回來**。

  ⚠ 它的 `sys.modules[名字] = module` 那一行不能省：`@dataclass` 建類別時會回頭查
  `sys.modules[cls.__module__]`，用 `importlib` 從檔案載入卻沒登記，會炸
  `AttributeError: 'NoneType' object has no attribute '__dict__'`（審稿時踩過）。

- [x] **新測試 4 顆全綠、本檔共 22 顆**

  ```bash
  pytest tests/integration/test_ingest_job.py -q
  ```

  預期最後一行：`22 passed`

- [x] **另一個直接測任務本體的檔全綠**

  ```bash
  pytest tests/integration/test_ingest_job_pdf.py -q
  ```

  預期：`9 passed`（開工前實查也是 9，本 phase 不准讓它變）

- [x] **★ 本 phase 最硬的一條：`tests/` 只准動一個檔，而且零刪除行**（與 §2 的快照相減）

  ```bash
  comm -13 <(sort /tmp/p76-tests-before.txt) <(git diff --numstat -- tests/ | sort)
  ```

  `comm -13` ＝ 把「只在開工前快照裡」與「兩邊都有」的行藏起來，只印**本 phase 新增的差異**。
  預期輸出**恰好一行**（三欄是「新增行數、刪除行數、檔名」，欄與欄之間是 Tab；
  中間那個 **`0` 就是零刪除行**；126 ＝ import 區的 3 行 ＋ 檔尾追加的 123 行，
  校準時逐字貼過一次實測就是 126，多貼少貼一個空行會差 1，不必緊張）：

  ```text
  126	0	tests/integration/test_ingest_job.py
  ```

  為什麼要相減、不直接看 `git diff --stat tests/`：依總覽 §7 鐵律 12，各 phase 做完**不會** commit，
  而**本次 76 排在 75 之後**，所以 `tests/conftest.py`／`tests/fakes.py`／`tests/unit/test_ai_timing_unit.py`
  的改動一定還躺在工作區，直接看會多出它們的名字，看起來像你改到了別的測試。
  （未追蹤的 `tests/unit/test_privacy_gate_unit.py` 不進 `git diff`，兩邊都看不到它，不影響相減。）

  ⚠ 相減後多於一行、或第二欄不是 `0`，就代表**你改到了既有測試**——
  那不是重構，回去看是哪裡把行為改掉了。

- [x] **全量測試 ＝ 開工基線 ＋ 4**

  ```bash
  pytest -q
  ```

  預期：`568 passed`（＝基線 564 ＋ 4），**0 skipped**

- [x] **端點仍 22 支零 DELETE ＋ 三顆與本模組直接相關的掃碼測試全綠**
  （任務只吃 `job_id`、不再丟任務、SQL 不外洩）

  ```bash
  pytest "tests/integration/test_design5_error_paths.py::test_端點恰好是這22支" \
         "tests/integration/test_nav_header.py::test_端點數仍為22" \
         "tests/integration/test_ask_three_paths.py::test_端點數不變" \
         "tests/integration/test_design5_error_paths.py::test_任務本體只吃job_id不吃影像位元組" \
         "tests/integration/test_design5_error_paths.py::test_PDF不是每頁一個任務" \
         "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：`6 passed`

- [x] **零依賴實證 ＋ 專案的 `data/` 沒被弄髒**

  ```bash
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q      # 預期 568 passed、全綠
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q # 同上
  find data -type f | wc -l                          # 與 §2 開工前記下的數字相同
  ```

  （本增量的第三個死埠 `AWS_ENDPOINT_URL` 要等 **Phase 77** 的第五道安全網 `wire_fake_cloud`
  才有意義，總覽 §7 鐵律 2 明寫「從 Phase 83 起改成三個死埠一起指」——本 phase 兩個就夠。）

- [x] **格式與 lint 全過**

  ```bash
  ruff format --check app tests scripts && ruff check app tests scripts
  ```

  預期：`All checks passed!`

- [x] **只動了該動的兩個檔，而且 `docs/spec/` 全程零改動**（同樣與 §2 的快照相減）

  ```bash
  git status --short docs/spec/                                                # 預期：零輸出
  comm -13 <(sort /tmp/p76-before.txt) <(git status --short -- app tests | sort)  # 預期恰為下面兩列
  ```

  ```text
   M app/services/ingest_job.py
   M tests/integration/test_ingest_job.py
  ```

  ⚠ **本次 `/tmp/p76-before.txt` 一定不是空的**（74／75 的八筆改動還在工作區，清單見 §2），
  所以這裡**一定要走 `comm -13` 相減**，不要直接看 `git status`。

- [x] **收工快照已記下**（本次全程**不 commit**，總覽 §7 鐵律 12；見 §4 步驟 6）

  ```bash
  .superpowers/sdd/phase0901/snapshot-tree     # 印出 40 字的 tree SHA，寫進交接紀錄
  ```

---

## 7. 常見陷阱

1. **順手把 `_run_image_job`／`_run_pdf_job` 也改成公開。**
   Phase 79 的雲端路**不會**呼叫它們（它的結果是從 S3 拿回來的，不是從 VLM 來的），
   所以公開只是多兩個「外面看得到、卻沒人該用的名字」。而且一旦公開，
   日後就會有人真的去呼叫它，本機路與雲端路的界線就模糊了。

2. **改到既有測試「讓它過」。**
   本 phase 的整個意義就是「行為沒變」。既有測試紅了＝行為變了＝重構失敗，
   正確反應是**回去看程式哪裡寫錯**，不是改測試。驗收清單那條
   `comm -13 <(sort /tmp/p76-tests-before.txt) <(git diff --numstat -- tests/ | sort)`
   （相減後只准一個檔、零刪除行）就是專門擋這件事的。

3. **`vlm.understand()` 的參數順序寫錯。**
   合約是 `understand(image_bytes, content_type, folders, entities, corrections)`——
   五個**位置參數**，而 `folders` 與 `entities` 都是 `list[dict]`、型別一模一樣，
   **寫反了不會爆錯，只會安靜地把實體清單當成資料夾清單塞進 prompt**。
   好消息是既有測試抓得到：`FakeVLM` 把三份清單記在 `last_folders`／`last_entities`／
   `last_corrections`。

4. **以為 `@dataclass(frozen=True)` 讓 `PromptContext` 完全不可變。**
   它擋的是「重新指派欄位」（`context.folders = [...]` 會炸），
   **不擋**「改清單裡的內容」（`context.folders.append(...)` 照樣成功）。
   本專案沒有人會去改它，但別誤以為它是深層不可變——尤其是 Phase 79 要把
   `context.folders` 序列化成 `context.json` 送去 S3 的時候。

5. **把 PDF 的收尾也硬塞進 `finish_image_job()`。**
   兩者不一樣：PDF 的 `photo_ids` 是在逐頁迴圈裡跟 `pages_done` **一起**寫的
   （不能留到最後才寫，否則崩潰重送會重跑已經做完的頁），最後只需要刪 staging 與刪 job。
   硬塞的話會把 PDF 的 `photo_ids` 覆蓋成只有一個 id——多頁 PDF 的冪等就毀了，
   而且 `test_崩潰重送從pages_done續跑不重插` 會紅得莫名其妙。
   函式名字裡的 `image` 就是在提醒這件事。

6. **`load_prompt_context()` 忘了 `limit=FEW_SHOT_CORRECTIONS`。**
   `recent_corrections()` 的預設 limit 剛好也是 5，所以**忘了寫也會過測試**——
   然後哪天有人改了那個常數，看圖 prompt 的糾錯例子數量就不會跟著變。
   明寫參數，不要靠兩邊的預設值剛好一樣。

7. **在 `embed_understanding()` 裡「順手」把 `category` 改成 `understanding.category`。**
   看起來更「正確」，其實是**改行為**：向量裡的類別**永遠是收件箱**（design1.md §2），
   模型猜的那個只會存進 `suggested_category` 欄位。改了之後歸類前後的向量會不一致，
   而且 `test_embed_understanding用收件箱名稱組文件` 會紅。

8. **把 `ai_timing.log_ai("embed", …)` 留在原地、沒跟著搬進 `embed_understanding()`。**
   後果是 Phase 79 的雲端路呼叫它時**不會留下計時 log**，於是 design6 D13「向量一律本機」
   在 log 上沒有證據——而 Phase 79 的 `test_雲端路的計時log裡embed是本機` 正是靠這一行。

9. **同時跑兩份 pytest。** 症狀：大量看似隨機的 404 與
   `TypeError: 'NoneType' object is not subscriptable`（兩份都在 `TRUNCATE` 同一個測試庫）。
   本 phase 特別容易踩到——重構時很想「一邊跑全量、一邊跑單檔快速確認」。忍住，一次一份。

10. **忘了先把重構前的檔案備份到 `/tmp/ingest_job_before.py`。** §6 有**三條**驗收需要它
    （簽章 `diff`、兩支改名函式的 AST 內容比對、離線等價 harness；§2 的說法是對的）。
    忘了的話從 git 拿回來：`git show HEAD:app/services/ingest_job.py > /tmp/ingest_job_before.py`
    （前提是本 phase 的修改**還沒 commit**——依鐵律 12，本來就還沒）。

11. **把 §6 的離線 harness 存成檔案再用 `python 檔名.py` 跑，結果 `ModuleNotFoundError: No module named 'app'`。**
    Python 跑「檔案」時會把**那個檔所在的目錄**放在 `sys.path` 最前面，不是你所在的專案根目錄，
    所以 `import app` 找不到。正解：照文件用 `python - <<'PY'`（從專案根目錄餵 stdin，`sys.path[0]` 就是根目錄），
    真的想存成檔案就 `PYTHONPATH=. python 檔名.py`（審稿時實際踩過）。

12. **`git diff --stat tests/` 印出一堆不是你改的檔（`fakes.py`、`conftest.py`、`test_ai_timing_unit.py`……）。**
    不是你手滑——依鐵律 12 各 phase 做完不 commit，74／75 的改動**一定**還躺在工作區
    （本次 76 排在 75 之後，清單見 §2）。
    這就是 §6 那兩條 git 驗收改用「與 §2 快照相減（`comm -13`）」的原因；
    忘了在 §2 留快照的話，現在補一份「扣掉 `test_ingest_job.py` 與 `ingest_job.py` 的版本」也行：
    `git diff --numstat -- tests/ | grep -v test_ingest_job.py > /tmp/p76-tests-before.txt`。

---

## 8. 完成後的專案狀態

`app/services/ingest_job.py` 從 512 行變成 595 行，多出來的幾乎全是 docstring 與註解——
**邏輯一行都沒有增減**。裡面多了五個**公開契約**：`load_prompt_context()`（讀三份清單＋收件箱名稱，
回一個 `PromptContext`）、`embed_understanding()`（合併成 Document 再轉向量，含 `kind=embed` 的計時 log）、
`insert_photo_with_files()`（原 `_insert_photo_with_files`，去底線）、
`finish_image_job()`（單圖成功收尾的三步鐵律）、`fail_job()`（原 `_fail`）。

**對外行為零改變**：`run_ingest_job()` 的簽章一個字都沒動、端點仍 **22** 支、
`POST /photos` 仍回 202、進度面板不變、`photo` 表不變、log 字樣不變。
**既有測試（專案的 543 顆 ＋ 74／75 的 21 顆）一顆都沒有被修改**
（與開工快照相減後 `tests/` 只多 `test_ingest_job.py` 的追加、零刪除行），
而且 §6 的離線 harness 證明重構前後 14 種情境的呼叫順序、狀態與 log **逐筆相同**。

**留下的一個小瑕疵（誠實記在這裡）：** `tests/integration/test_ingest_job_pdf.py`
第 216 與 239 行的**中文註解**還寫著 `_fail` 與 `_insert_photo_with_files` 這兩個已經不存在的名字。
本 phase 刻意不修（修了就會讓 `tests/` 的 diff 多一個檔與一行刪除，違反本 phase 最硬的驗收條件）。
它們是純文字、不影響行為，**留給日後任何一次會動到那個檔的 phase 順手改掉**——
最自然的時機是 Phase 95（收尾 phase 本來就會清點 `tests/`；這一句是建議，phase-95 的做清單目前沒有這一列）。

**下一個 phase：Phase 77「雲端路契約與第五道安全網」**——**它會直接用到本 phase 的
`PromptContext`**（`build_context(prompt_context: PromptContext) -> dict`，總覽 §2.4.1），
所以本 phase 的 `PromptContext` 欄位名一個字都不能自己改。Phase 77 新建
`app/services/cloud_ingest.py`（兩份 Protocol＝`CloudMailbox`／`RemoteProbe`，
外加 `CloudRouteOff`、`AlwaysRunning`、`build_context()`）、
把增量六的設定常數放進 `config.py`、開 `get_cloud_route()` 注入點，並在 `tests/conftest.py`
加**第五道 autouse 安全網** `wire_fake_cloud`（`CLOUD_ROUTE` 蓋成 `off`、`AWS_ENDPOINT_URL`
指到死埠——**pytest 絕不連真 AWS**）。Phase 78 才把 74 的閘門與 77 的雲端路接進 Celery。

**測試顆數 ＝ 開工基線 ＋ 4 ＝ 568**（與總覽 §9 的軌跡表一致）。**端點仍 22。**

> 📌 **2026-09-01 實作實查：開工基線 566、做完 570**（Phase 75 依 R10 多 2 顆，本 phase 仍 +4）。本文件其餘處寫的 564／568 是 R10 之前的數字；驗收看的是「本 phase +4」與「與開工快照相減」，不是絕對值。

---

## 附：本文件引用的官方文件

- [`dataclasses`（`frozen`／`slots` 兩個選項）](https://docs.python.org/3/library/dataclasses.html)
- [`dataclasses.FrozenInstanceError`](https://docs.python.org/3/library/dataclasses.html#dataclasses.FrozenInstanceError)
- [`ast.unparse()`（把 AST 印回程式碼；§6 的「內容逐字相同」檢查用它）](https://docs.python.org/3/library/ast.html#ast.unparse)
- [pytest `monkeypatch`（換掉模組屬性與物件方法）](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- [`importlib.util.spec_from_file_location`（§6 harness 用它把重構前的檔案當成模組載入）](https://docs.python.org/3/library/importlib.html#importlib.util.spec_from_file_location)
- [`comm`（POSIX；§6 用 `comm -13` 把「開工前快照」從現況裡減掉）](https://pubs.opengroup.org/onlinepubs/9699919799/utilities/comm.html)
- [`git diff --stat`（看一次改動動了哪些檔、增刪幾行）](https://git-scm.com/docs/git-diff)
- [LangChain `Embeddings` 介面（`embed_query`／`embed_documents`）](https://python.langchain.com/docs/concepts/embedding_models/)
