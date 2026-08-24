# Phase 41：AI 計時 helper `services/ai_timing.py`（階段乙第 1 步）

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 技術實作已完成。**
> 下方 `365 → 373` 是本 phase 開工時的歷史基線，特意保留；
> 目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，
> 全量為 **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> `ai_timing.log_ai(...)` 生產呼叫點已接齊且掃碼恰好 **8 處**；
> `compileall`、Node 語法檢查與 diff check 均綠。
> 最新 hardening 會把 model／note 正規化成單行並限制長度，避免 log injection、過長內容與
> 敏感模型輸出外洩；`target=None` 的 helper／假件相容路徑可即時讀 config，但真實 client 會把
> request 已選定的 backend／model 封裝成 immutable `AiTarget` 傳入，之後切換全域開關也不會
> 把已發出的呼叫重新貼錯標籤。
> 狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 做一個小工具，讓「每次真的打到模型的呼叫」都能用**一行程式碼**
> 包起來，自動在終端機留下前後兩行、格式統一的訊息與秒數。
> 本 phase 只做工具與它的單元測試，**還不接到任何真的呼叫上**（那是 Phase 42／43）。

**為什麼要有這個工具：** 現在只有「看圖」那一步有秒數（寫死在 `app/api/routers/photos.py` 裡），
其他四種 AI 呼叫（轉向量、判斷查法、產生回答、再建議一個實體）**一行計時訊息都沒有**
（只有失敗時才留下一行 warning，例如 `ask_workflow.py` 的「路由呼叫失敗，fallback 成語意查詢」；
成功走完全程靜悄悄）。
本機看圖一張要 2〜5 分鐘、雲端只要 2 秒——差這麼多，卻只有其中一步看得到數字。
把格式抽成一份共用工具，五種呼叫才會長得一模一樣、才 grep 得出來。

---

## 1. 對應 design4.md 章節

- **§5.2**（格式：兩行一組、五個必要欄位、`elapsed_s` 一位小數、可在結束行後面接人類可讀摘要）
- **§5.3 前半**（「抽一個小 helper，context manager，例外往外傳，helper 只負責打結束＋`ok=false`」）
- **§5.4 第 1、6 列**（新建 `app/services/ai_timing.py`；新建 `tests/unit/test_ai_timing_unit.py`）
- **D7**（計時粒度；失敗也打結束、標 `ok=false`）
- **§5.1 的 backend／model 欄位定義**（哪一種 kind 用哪一顆模型、`embed` 永遠 `local`）

---

## 2. 前置條件

- 無 phase 依賴（可與階段甲平行做，但建議照編號，先把甲收完）。
- 開工基準：`pytest -q` ＝ **365 passed ＋ 2 skipped**（Phase 38 之後的數字）。
  若你還沒做階段甲就先做這一 phase，基準會是 **358 ＋ 2**、做完是 **366 ＋ 2**——
  要對的是「**恰好多 8 顆**」這個差值，不是那個絕對數字。

**先認識兩個名詞（第一次出現）：**

- **context manager（情境管理器）**：Python 的 `with X: …` 語法背後的東西。
  它保證「進入區塊時做一件事、離開區塊時做另一件事」——**而且區塊裡爆炸也照樣做**。
  最常見的例子是 `with open(...) as f:`（離開時保證關檔）。
  這裡我們用它保證「呼叫前打一行、呼叫後打一行」，就算模型丟例外也不會漏掉結束那行。
- **monotonic clock（單調時鐘）**：`time.monotonic()` 回傳的是「開機到現在的秒數」，
  它**只會往前走**。一般的 `time.time()`（牆上時鐘）會被系統校時、換日光節約時間影響，
  量時間差時可能算出負數。所以量「花了多久」一律用 monotonic
  （本專案已有先例：`app/services/camera_session_service.py` 的 `_now()`，
  以及 `app/api/routers/photos.py` 現在那段看圖計時）。

---

## 3. 範圍

### 做

- 新建 `app/services/ai_timing.py`：一個 `log_ai(kind)` context manager ＋ kind→模型的對照。
- 新建 `tests/unit/test_ai_timing_unit.py`：八顆單元測試。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 把秒數寫進資料庫、算平均／P95、做儀表板 | design4 只要「log 打得出來」。不要過度設計 |
| 用 `print()` 或自己開檔案寫 log | 全站用 Python 的 `logging`，`app/main.py` 已經把 `app.*` 的 INFO 接到 uvicorn 終端機 |
| 把秒數寫死當測試斷言 | design4 §5.3 明文：「**不要**把秒數寫死當驗收」。假件跑得飛快，真模型幾分鐘，寫死必壞 |
| 在 helper 裡吞例外、把失敗轉成回傳值 | §5.3 明文：「例外往外傳（422／500 語意不變），helper 只負責打結束＋`ok=false`」 |
| 順手改任何現有的呼叫點 | 那是 Phase 42／43。本 phase 做完，產品行為**零改變** |
| 為 PDF 渲染、存檔、縮圖、SQL、WebRTC、QR、開關 GET／PUT 計時 | §5.1 明文：那些不是模型推論，不計時 |

---

## 4. 實作步驟（先寫測試再實作）

### 4.1 先確認格式長什麼樣（下面前兩段是 design4 §5.2 原文，一個字都不要改）

```text
AI 開始 kind=vlm backend=local model=gemma4
AI 結束 kind=vlm backend=local model=gemma4 elapsed_s=123.4 ok=true
```

失敗時：

```text
AI 結束 kind=vlm backend=cloud model=gemma4 elapsed_s=0.1 ok=false
```

成功且想附人類看的摘要時（**五個必要欄位仍然要在前面**。這一段是照 §5.2
那句「可在結束行後面加人類可讀摘要」造出來的例子，不是原文照抄——摘要的內容自由，
但它前面那五個欄位不自由）：

```text
AI 結束 kind=vlm backend=local model=gemma4 elapsed_s=123.4 ok=true text 42 字、建議類別「收據」
```

規則：

- `kind`／`backend`／`model`／`elapsed_s`／`ok` **五個一定要在**，順序固定——
  這樣才 grep 得出來（例如 `grep "kind=embed"` 只看轉向量花多久）。
- `elapsed_s` **一位小數**（對齊現在看圖 log 的 `%.1f`）。
- `ok` 是小寫的 `true`／`false`（不是 Python 的 `True`）。
- 摘要接在 `ok=` 後面，**不是**插在中間。

### 4.2 kind → backend／model 的對照（design4 §5.1 的表）

| kind | 什麼時候用 | backend | model |
|---|---|---|---|
| `vlm` | 看圖（單圖、PDF 每一頁、無線鏡頭入庫） | `config.AI_BACKEND` | 本機 `config.VLM_MODEL`／雲端 `config.OLLAMA_CLOUD_VLM_MODEL` |
| `embed` | 轉向量（上傳每張／每頁、歸類重算、詢問走向量） | **永遠 `"local"`** | `config.EMBEDDING_MODEL` |
| `route` | 判斷查法 | `config.AI_BACKEND` | 本機 `config.LLM_MODEL`／雲端 `config.OLLAMA_CLOUD_LLM_MODEL` |
| `answer` | 產生回答 | 同上 | 同上 |
| `entity_suggest` | 「再建議一個」 | 同上 | 同上 |

> **📌 開工時與 design4 §5.3 的一處差異（歷史 phase-local 設計）**
> design4 的示意寫成 `with log_ai("vlm", backend=..., model=...)`，`...` 是留給實作填的佔位。
> 本 phase 初版決定**由 helper 自己從 `config` 推**，呼叫端只寫 `with log_ai("vlm"):`。
> 理由：上面這張表是死的規則，抄到八個呼叫點（Phase 42 三處＋Phase 43 五處）就是八份
> 會各自走鐘的複製品；集中在一個函式裡，日後多一顆模型只要改一個地方。
> **最終 hardening 已保留這個 `target=None` fallback，但真實 client 會傳 request 已選定、
> 建構後不可變的 `AiTarget`；log 因此記錄實際 client，不會因後續切換全域開關而 relabel。**

> **⚠️ fallback 的 `config.AI_BACKEND` 要在函式裡即時讀**（寫 `config.AI_BACKEND`，
> **不要** `from app.core.config import AI_BACKEND`）。它是頁首那顆「本機｜雲端」開關撥動的
> 執行中狀態，import 進來就會定死成啟動當下的值。這只服務 helper／假件未提供 target 的
> 相容路徑；真實 VLM／embedding／router／answerer／entity client 不重讀它來標記既有 request。

### 4.3 先寫測試（此時全部應該是紅的：模組還不存在）

- [ ] 新建 `tests/unit/test_ai_timing_unit.py`。所有測試都用 pytest 內建的 `caplog` fixture
      抓 log，並在開頭 `caplog.set_level(logging.INFO)`（helper 打的是 INFO 等級；
      既有 `tests/unit/test_entity_suggestion_unit.py` 用的是等價的
      `with caplog.at_level(logging.WARNING):` 寫法，兩種都可以，挑一種寫到底就好）。
      切換 AI 後端一律用 `monkeypatch.setattr(config, "AI_BACKEND", "cloud")`——
      monkeypatch 會在該顆測試結束時自動還原，不會污染同一個 process 裡的其他測試。
      （既有 `tests/integration/test_ai_backend_switch.py` 是直接指派 `config.AI_BACKEND = "cloud"`、
      再靠它自己的 autouse fixture 撥回本機；那是它的寫法，新測試用 monkeypatch 更省事。
      那支檔案裡的 `monkeypatch.setattr` 是用在 `OLLAMA_API_KEY` 上，別看串行。）
      **「本機」那半邊也要明寫** `monkeypatch.setattr(config, "AI_BACKEND", "local")`，
      不要靠「預設值剛好是 local」——那是模組層的可變狀態，別人撥過就會互相絆倒。

| # | 測試名稱 | 驗什麼 |
|---|---|---|
| 1 | `test_成功時打出開始與結束兩行` | `with log_ai("vlm"): pass` 之後 `caplog` 恰有兩筆訊息，一筆以 `AI 開始 ` 開頭、一筆以 `AI 結束 ` 開頭 |
| 2 | `test_結束行帶ok為true與非負秒數` | 結束行含 `ok=true`；用正規表示式抓出 `elapsed_s=([0-9.]+)` 且轉成 float **≥ 0**（不准斷言等於某個數字） |
| 3 | `test_例外會往外傳且結束行標ok為false` | `with pytest.raises(RuntimeError):` 包住 `with log_ai("route"): raise RuntimeError("炸了")`；例外照樣傳出來，而且結束行含 `ok=false` |
| 4 | `test_embed的backend永遠是local就算開關撥到雲端` | `AI_BACKEND="cloud"` 時 `log_ai("embed")` 仍是 `backend=local`、`model=` 等於 `config.EMBEDDING_MODEL` |
| 5 | `test_vlm跟著開關切換backend與model` | 撥本機 → `backend=local model={config.VLM_MODEL}`；撥雲端 → `backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}`（兩邊都用 `monkeypatch` 明寫，別靠預設值） |
| 6 | `test_三種文字用途都用LLM模型名` | `route`／`answer`／`entity_suggest` 三個 kind 在本機都是 `model={config.LLM_MODEL}`、撥雲端都是 `config.OLLAMA_CLOUD_LLM_MODEL` |
| 7 | `test_備註接在結束行後面且五個欄位仍在` | `with log_ai("vlm") as 計時: 計時.note = "text 3 字"` → 結束行 `.endswith("text 3 字")`，而且 `kind=`／`backend=`／`model=`／`elapsed_s=`／`ok=true` 五個都還在 |
| 8 | `test_未知的kind直接炸掉且一行log都沒打` | `with pytest.raises(ValueError): with log_ai("亂打"): pass`；而且 `caplog.messages` 是**空的**——連 `AI 開始` 都不准打（沒有結束行的開始行＝孤兒）。打錯 kind 寧可當場炸 |

- [ ] 跑一次確認**真的是紅的**：

```bash
pytest tests/unit/test_ai_timing_unit.py -v
```

  預期：pytest 在**收集階段**（collect）就停下來，畫面上是 **1 error**、不是 8 個 F：
  `ModuleNotFoundError: No module named 'app.services.ai_timing'`。
  模組還沒建、`import` 就炸了，所以八顆測試連跑都還沒跑到——這就是這一步要看到的「紅」。

### 4.4 寫 helper（以下骨架保留開工時初版；最終 API 見本檔頂端 hardening 說明）

- [ ] 新建 `app/services/ai_timing.py`。骨架如下（註解請照本專案風格寫足，這裡只列結構）：

```python
"""AI 呼叫的計時 log（design4.md §5）。

「用到 AI」＝會打 Ollama（本機或 Cloud）的那一段。本檔提供唯一的一種格式，
五種呼叫（看圖／轉向量／判斷查法／產生回答／再建議一個）全部走這裡——
格式只有一份，才 grep 得出來（例如 grep "kind=embed" 只看轉向量花多久）。

本檔不吞例外：區塊裡爆炸時照樣打結束行（標 ok=false），然後把原始例外
原封不動往外丟——422／500／fallback 的語意一個字都不變（design4 §5.3）。
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass

from app.core import config

logger = logging.getLogger(__name__)


def _目標(kind: str) -> tuple[str, str]:
    """這一種呼叫會打到哪裡、用哪顆模型（design4.md §5.1 的表）。

    ★ config.AI_BACKEND 一定要在這裡「即時讀」：它是頁首那顆本機／雲端開關
      撥動的執行中狀態，import 進來就會定死成伺服器啟動當下的值。
    """
    if kind == "embed":
        # 向量永遠本機：庫裡既有的向量是本機 bge-m3 算的，換一顆就比不出東西，
        # 所以 embeddings 從來不歸那顆開關管（dependencies.py 的 get_embeddings）。
        return "local", config.EMBEDDING_MODEL

    是雲端 = config.AI_BACKEND == "cloud"
    if kind == "vlm":
        return config.AI_BACKEND, (
            config.OLLAMA_CLOUD_VLM_MODEL if 是雲端 else config.VLM_MODEL
        )
    if kind in ("route", "answer", "entity_suggest"):
        return config.AI_BACKEND, (
            config.OLLAMA_CLOUD_LLM_MODEL if 是雲端 else config.LLM_MODEL
        )
    # 打錯 kind 的 log 會變成 grep 不到的孤兒，寧可當場炸給實作者看
    raise ValueError(f"未知的 AI 呼叫種類：{kind}")


@dataclass
class AiCall:
    """交給 with 區塊的小物件，目前只有一個用途：讓呼叫端補一句人類看的摘要。

    例：with log_ai("vlm") as 計時: … 計時.note = f"text {n} 字"
    摘要會接在結束行的最後面，五個必要欄位仍在它前面（design4.md §5.2）。
    """

    note: str = ""


@contextmanager
def log_ai(kind: str):
    """把一次 AI 呼叫包起來，前後各打一行。

    kind：vlm／embed／route／answer／entity_suggest 五選一。
    """
    backend, model = _目標(kind)
    抬頭 = f"kind={kind} backend={backend} model={model}"
    logger.info("AI 開始 %s", 抬頭)

    這次 = AiCall()
    起點 = time.monotonic()      # 只會往前走的時鐘，量時間差要用它
    成功 = True
    try:
        yield 這次
    except BaseException:
        # 不做任何處理，只記下「這次失敗了」，然後原封不動往外丟
        成功 = False
        raise
    finally:
        秒數 = time.monotonic() - 起點
        摘要 = f" {這次.note}" if 這次.note else ""
        logger.info(
            "AI 結束 %s elapsed_s=%.1f ok=%s%s",
            抬頭,
            秒數,
            "true" if 成功 else "false",
            摘要,
        )
```

- [ ] 跑綠：

```bash
pytest tests/unit/test_ai_timing_unit.py -v
```

  預期：**8 passed**。

- [ ] 跑全量：

```bash
pytest -q
```

  預期：**373 passed ＋ 2 skipped**（365 ＋ 本 phase 的 8 顆）。
  產品行為**零改變**——本 phase 沒有任何現有程式碼呼叫這個 helper。

- [ ] 零外部依賴實證：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

  預期：**顆數與上一步完全相同**（373 passed ＋ 2 skipped）。9 是一個不會有人在聽的埠，
  指過去顆數還一樣，就證明本 phase 的測試沒有偷偷去打真的 Ollama。

---

## 5. ASCII 圖：這個 with 區塊在做什麼

```text
   程式碼                                終端機看到的

   with log_ai("vlm") as 計時:      ──►  AI 開始 kind=vlm backend=local model=gemma4
       結果 = vlm.understand(...)        （這裡等 2〜5 分鐘…）
       計時.note = "text 42 字"
   （離開 with 區塊）               ──►  AI 結束 …（是一整行，完整長相見下）

   AI 結束 kind=vlm backend=local model=gemma4 elapsed_s=143.7 ok=true  text 42 字
   └──────────────────── 五個必要欄位，順序固定 ─────────────────────┘  └─ 摘要 ─┘


   區塊裡爆炸時（例如 Ollama 沒開）：

   with log_ai("route"):            ──►  AI 開始 kind=route backend=cloud model=gemma4
       decision = router.route(...)  ✗
   （例外往外竄，離開 with 區塊）   ──►  AI 結束 …（是一整行，完整長相見下）

   AI 結束 kind=route backend=cloud model=gemma4 elapsed_s=0.1 ok=false
   └──── 失敗也照樣打這一行，秒數照記，只有 ok= 從 true 變 false ─────┘

   然後例外「原封不動」繼續往外丟——誰本來會接住它、會變成 422 還是 500
   還是 fallback，全部維持原樣（helper 不改語意）


   kind → 打到哪裡（design4 §5.1）

        vlm ────────────┐
        route ──────────┤──► config.AI_BACKEND（頁首開關）→ local 或 cloud
        answer ─────────┤
        entity_suggest ─┘

        embed ─────────────► 永遠 local（向量必須跟庫裡既有的 bge-m3 同源）
```

---

## 6. 驗收清單

- [ ] 八顆單元測試**先紅後綠**
- [ ] `pytest -q` ＝ **373 passed ＋ 2 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] `app/services/ai_timing.py` 裡沒有 `print(`、沒有 `open(`、沒有 `try: … except: pass`
- [ ] `app/services/ai_timing.py` 裡是 `config.AI_BACKEND`，**不是** `from app.core.config import AI_BACKEND`
- [ ] 測試裡**沒有**任何「秒數等於某個值」的斷言（只有 `>= 0`）
- [ ] 產品行為零改變：`git status --short -- app tests` 比開工前**只多兩行 `??`**
      （`app/services/ai_timing.py` 與 `tests/unit/test_ai_timing_unit.py`），**沒有多出任何 `M`**
      ＝本 phase 沒有動到任何既有檔案。

  > ⚠️ **不是「輸出必須只有兩行」。** 增量四**全程不 commit**（產品負責人 2026-08-23 裁決），
  > 所以你做到這裡時，Phase 38〜40 改過的 `app/api/routers/photos.py`、`app/schemas/photo.py`、
  > `app/static/*` 等等**本來就會掛在那裡**顯示 `M`，那是正常的、不要去「清乾淨」。
  > 最保險的做法：**動手前**先存一份快照，做完再比對——
  > 開工前 `git status --short -- app tests > /tmp/p41-before.txt`，
  > 收尾時 `git status --short -- app tests | diff /tmp/p41-before.txt -`，
  > 預期差異恰好是那兩行新檔（`>` 開頭的兩行）。
  > （新檔還沒 `git add`，`git diff` 看不到它們，所以這裡用 `git status`。）

---

## 7. 常見陷阱

1. **`finally` 寫成 `else`**：`else` 只有在沒有例外時才跑，那樣失敗就不會打結束行了。
   必須是 `finally`。

2. **接 `Exception` 而不是 `BaseException`**：使用者按 Ctrl+C（`KeyboardInterrupt`）
   或 uvicorn 關機時丟的是 `BaseException` 的子類，用 `except Exception` 抓不到——
   結束行會漏掉。這裡我們**不處理**例外、只記一個旗標再 `raise`，所以抓最寬的那個最正確。

3. **忘了 `raise`**：`except BaseException: 成功 = False` 後面沒有 `raise`，
   就變成 helper 把例外吃掉了——上傳看不懂會從 422 變成「若無其事地繼續」。
   這是本 phase 最嚴重的可能錯誤。

4. **用 `time.time()`**：見上面 monotonic 的說明。量時間差一律 `time.monotonic()`。

5. **log 等級用 `debug`**：`app/main.py` 只把 INFO 以上接到終端機（第 21 行 `setLevel(logging.INFO)`），
   用 `debug` 會什麼都看不到。用 `logger.info`。

6. **logger 名稱自己亂取**：一定要用 `logging.getLogger(__name__)`
   （會得到 `app.services.ai_timing`）。取成別的名字就不在 `app.*` 底下，
   `main.py` 掛的那個 handler 接不到，終端機一片安靜。

7. **測試用 `caplog` 卻忘了 `set_level`**：INFO 訊息預設可能被過濾掉，
   測試會看到空的 `caplog.messages` 而百思不解。第一行就寫 `caplog.set_level(logging.INFO)`。

8. **把 `elapsed_s` 印成科學記號**：假件跑得極快，秒數可能是 `1.9e-05`。
   用 `%.1f` 格式化之後會是 `0.0`，正是我們要的（不要用 `str(秒數)`）。

9. **把 `_目標(kind)` 挪到 `logger.info("AI 開始 …")` 後面**：kind 打錯時會先印出一行開始、
   然後才炸掉，終端機就留下一個永遠等不到結束行的孤兒。骨架的順序是「先算出
   backend／model，再打開始行」，兩行不要對調（測試 8 就是在抓這件事）。
