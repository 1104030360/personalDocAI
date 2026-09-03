# Phase 75：隱私閘門 VLM 接線（真模型、縮圖、計時）

> ⚠ **檔名仍叫「本機模型備援」是歷史。** 2026-09-01 改判後，這不是可選備援，
> 是閘門的**唯一實作**。沒有 `PRIVACY_GATE_LOCAL_MODEL`、沒有 `RuleGate`。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的四件事：
> ① 不要把還沒分類的圖送到 **S3／EC2**（D2：AWS 那扇門仍必須等 `NON_SENSITIVE`）；
> ② 不要接進 `ingest_task`（接線仍是 Phase 78）；
> ③ 不要用閘門去**寫入／關掉**頁首開關（D6：跟著走，不准關）；
> ④ 不要碰 AWS、boto3、S3、SQS。
> ⑤ 不要寫檔名關鍵字、不要復活 `RuleGate`。

> 🎯 **一句話目標：** 把 Phase 74 的占位模型換成 `OllamaPrivacyModel`——
> 同一顆看圖 VLM、另一份短 prompt、**跟著 `AI_BACKEND`**；
> 問之前把圖縮到長邊 ≤512；`ai_timing` 多一種 kind `privacy`；
> PDF 先渲染第一頁再問。任何失敗回 `UNCERTAIN`。

**為什麼要做這個：**

Phase 74 的正式路徑還是「永遠 UNCERTAIN」的占位。本 phase 才讓閘門真的看圖。
產品負責人接受成本：本機短問推估 20〜60 秒、雲端約 2 秒（未實測；78 接線後煙霧回填）。
完整 9 欄 understand 仍是入庫那一次——否則 EC2 卸壓沒了。

| 開關 | 閘門短問打哪 | 模型名 |
|---|---|---|
| 本機（預設） | 本機 Ollama | `config.VLM_MODEL` |
| 雲端 | ollama.com | `config.OLLAMA_CLOUD_VLM_MODEL` |

雲端時身分證會先去 ollama.com 問這句。產品負責人 2026-09-01 接受：開關本就是開發加速用。

---

## 1. 對應 design6.md

| 章節 | 落地 |
|---|---|
| **D2／D4／D6** | `OllamaPrivacyModel(backend=config.AI_BACKEND)`；讀開關、不寫開關 |
| **§1.1** | 同一顆 VLM、另一份短 prompt，不是第二個模型 |
| **追認項 L** | 縮圖在 `VlmGate` 問模型之前；`FakePrivacyModel.last_image_bytes` 驗長邊 |

---

## 2. 前置條件

Phase 74 綠（554）。`pytest -q` 554 passed。

**本 phase 做完 = 554 ＋ 10 ＝ 564**（實作時依裁決 R10 再補 2 顆 → **566**，見 §5）。

---

## 3. 範圍

### 做

1. **`PRIVACY_PROMPT` 短指令**（只准回 JSON `{sensitive, confident}`）。
   不准出現 category／location／items／task_title 等入庫欄位。
   雲端路徑尾端另接一段**自己的**「只准回 JSON」指令（＝`ollama_cloud` docstring 講的第②道保險）。
   ⛔ **不可以直接接 `vlm_service.CLOUD_JSON_INSTRUCTION`**：那一段的「長相示意」逐字列著
   understand 的九個鍵（`understood`／`text`／`category`／`items`／`content_time`／`entity`／
   `task_title`／`task_due`…），接上去等於叫模型回**錯的鍵**，而 `PrivacyJudgement` 只有
   `sensitive`／`confident` 兩欄 → 驗證失敗 → 一律 `UNCERTAIN`（安靜地永遠卸不了壓）。
   要抽常數就放 `privacy_gate.py` 自己家、名字加底線（例如 `_CLOUD_JSON_INSTRUCTION`），
   **別動 `vlm_service` 那顆**（它有既有測試釘著）。
2. **`OllamaPrivacyModel`**：跟 `get_vlm`／`build_vlm_for_backend` 同一套後端分流；
   `judge()` 只試一次，任何例外讓呼叫端（`VlmGate`）變 `UNCERTAIN`。
   帶 `timing_target`（`@property` 回 `ai_timing.AiTarget`），比照 `OllamaVLM`。
3. **`shrink_for_model(image_bytes) -> bytes`**：長邊 ≤512、輸出 PNG、不放大。
   放在 `VlmGate.classify()` 裡、`model.judge()` 之前。
   ⚠ **controller 裁決 R9（Phase 74 review 抓到）：`VlmGate.classify()` 的 `except Exception` 不准再安靜吞掉。**
   每一種失敗（讀檔、PDF 渲染、縮圖、`model.judge()`）在回 `UNCERTAIN` 之前都要 `logger.warning("隱私閘門判斷失敗，當作 UNCERTAIN：…", exc_info=True)`
   （`privacy_gate.py` 要有 `logger = logging.getLogger(__name__)`）。理由：Phase 78 接線後，一個傳錯 kwarg 的 bug 會讓每張照片都變 UNCERTAIN、一張都卸不出去，而且完全沒有線索——這正是專案錯誤表一向在防的安靜壞掉。比照 `entity_suggestion_service` 失敗回 None 但留 log 的既有慣例。不新增顆數（74 的 `test_模型丟例外回UNCERTAIN`／`test_讀檔失敗回UNCERTAIN` 可順手用 `caplog` 多斷言一句 warning，或不斷言）。
4. **PDF**：`content_type == application/pdf` 時用既有 `pdf_service.render_pages()` 取**第一頁** PNG 再縮、再問。
   零頁／壞檔 → `UNCERTAIN`，不問模型。
5. **`ai_timing`**：`_目標()` 加 `privacy` 分支（`backend`／`model` 與 `vlm` 同一組，**跟著開關**、不是恆 local），
   `log_ai` 的 docstring 從「五選一」改成「六選一」。
6. **`get_privacy_gate()`**：改成 `build_privacy_gate_for_backend(config.AI_BACKEND)`，
   並新增 `build_privacy_gate_for_backend(ai_backend)` ＝ `VlmGate(OllamaPrivacyModel(backend=ai_backend))`
   （**controller 裁決 R1**，寫法比照既有 `build_vlm_for_backend`；理由見步驟 5）。
   刪掉 `_pending_privacy_model`。
7. **10 顆測試**（總覽 §2.7 逐字那些名字）。

> 📌 **`tests/fakes.py` 本 phase 可以不動。** `FakePrivacyModel`（含 `last_image_bytes`）
> 已在 Phase 74 建好，本 phase 的十顆直接用。總覽 §2.7 把 `tests/fakes.py` 列進
> Phase 75 的「動到的檔」、§2.4.5 又把 `FakePrivacyModel` 的「誰建」寫成 75，
> 都是改判前的殘留——**以 74 已建為準**（74 才是需要它的人：`VlmGate` 要一顆 `PrivacyModel`）。

### 明確不做

| 不做 | 為什麼 |
|---|---|
| `PRIVACY_GATE_LOCAL_MODEL`／`PRIVACY_MODEL` | 不再是可選備援；模型就是看圖那顆 |
| 檔名捷徑 | 已否決 |
| 完整 9 欄 understand 當閘門 | 會讓 EC2 沒工作 |
| 接線 | Phase 78 |
| 寫入 `AI_BACKEND` | D6 |

---

## 4. 實作步驟（TDD）

### - [x] 步驟 1：先寫測試（紅）

在 `tests/unit/test_privacy_gate_unit.py` **追加** 9 顆（不要改 74 的 11 顆）。

**先補檔頭的 import**——Phase 74 刻意沒寫這三行（那時沒人用，會被 `ruff check` 判 F401），
現在真的用得到了。**一定要併進檔頭那個 import 區塊**，不可以寫在檔案中間：
`pyproject.toml` 的 `select` 含 `E`，模組層 import 放在函式後面會被判 **E402**；
`I`（isort）也會把它們排回檔頭。加完長這樣（ruff 的排序：先 `app.core`、再
`app.dependencies`、再 `app.services`、再 `app.services.privacy_gate`、最後 `tests.fakes`；
同一行內的名字大寫在前）：

```python
from app.core import config
from app.dependencies import build_privacy_gate_for_backend, get_privacy_gate
from app.services import privacy_gate
from app.services.privacy_gate import (
    PRIVACY_PROMPT,
    PrivacyJudgement,
    Verdict,
    VlmGate,
    judgement_to_verdict,
    shrink_for_model,
)
from tests.fakes import FakePrivacyGate, FakePrivacyModel, make_png_bytes
```

⚠ `shrink_for_model` 只被下面第一顆間接驗到（透過 `VlmGate`），**沒有直接呼叫**——
若你最後沒有直接用到它，就把它從 import 拿掉（F401 會擋 commit）。
`make_png_bytes` 在 74 就已經 import 了（`_png()` 用它），不必重複。

然後追加這 9 顆：

```python
def test_送進模型的圖長邊不超過512():
    from PIL import Image
    import io

    大圖 = Image.new("RGB", (2000, 1000), "white")
    buf = io.BytesIO()
    大圖.save(buf, format="PNG")
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(模型).classify(
        filename="big.jpg", content_type="image/png", load_bytes=lambda: buf.getvalue()
    )
    送出 = Image.open(io.BytesIO(模型.last_image_bytes))
    assert max(送出.size) <= 512


def test_本機後端用本機VLM模型名(monkeypatch):
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    模型 = privacy_gate.OllamaPrivacyModel()
    assert 模型.timing_target.model == config.VLM_MODEL
    assert 模型.timing_target.backend == "local"


def test_雲端後端用雲端VLM模型名(monkeypatch):
    # 假 key 必須是 ASCII（HTTP header 不吃中文）；建 Client 不會連線。
    # 比照既有的 test_雲端VLM暴露建構時選定的不可變計時目標，不靠 .env 有沒有填。
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    模型 = privacy_gate.OllamaPrivacyModel()
    assert 模型.timing_target.model == config.OLLAMA_CLOUD_VLM_MODEL
    assert 模型.timing_target.backend == "cloud"


def test_短prompt不含完整understand欄位():
    for 禁 in ("category", "location", "items", "task_title", "task_due", "content_time"):
        assert 禁 not in PRIVACY_PROMPT


def test_PDF渲染第一頁再問():
    from tests.fakes import make_pdf_bytes

    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(模型).classify(
        filename="scan.pdf",
        content_type="application/pdf",
        load_bytes=make_pdf_bytes,
    )
    assert 模型.calls == 1
    assert 模型.last_image_bytes[:4] == b"\x89PNG"


def test_PDF渲染失敗回UNCERTAIN():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    結果 = VlmGate(模型).classify(
        filename="壞.pdf",
        content_type="application/pdf",
        load_bytes=lambda: b"%PDF-not-a-pdf",
    )
    assert 結果 is Verdict.UNCERTAIN
    assert 模型.calls == 0


def test_縮圖失敗回UNCERTAIN():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    結果 = VlmGate(模型).classify(
        filename="x.jpg",
        content_type="image/jpeg",
        load_bytes=lambda: b"not-an-image",
    )
    assert 結果 is Verdict.UNCERTAIN
    assert 模型.calls == 0


def test_get_privacy_gate跟AI_BACKEND走(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    閘門 = get_privacy_gate()
    assert isinstance(閘門, VlmGate)
    assert 閘門._model.timing_target.backend == "cloud"

    # R1：worker 行程讀不到頁首開關（它的 config.AI_BACKEND 永遠是預設的 "local"），
    # 所以另有一支「明傳後端」的建構函式，Phase 78 會拿 job["ai_backend"] 快照餵它。
    # 這裡順手釘住它真的照參數走，不是又去偷看 config。
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    assert build_privacy_gate_for_backend("cloud")._model.timing_target.backend == "cloud"
    assert build_privacy_gate_for_backend("local")._model.timing_target.backend == "local"


def test_閘門不准寫入AI_BACKEND():
    from pathlib import Path

    原始碼 = Path("app/services/privacy_gate.py").read_text(encoding="utf-8")
    assert "AI_BACKEND =" not in 原始碼
    assert "AI_BACKEND=" not in 原始碼.replace(" ", "")
```

在 `tests/unit/test_ai_timing_unit.py` **檔案最後**追加這一顆（格式抄該檔既有的
`test_vlm跟著開關切換backend與model`：`caplog.set_level(logging.INFO)` ＋
`monkeypatch.setattr(config, "AI_BACKEND", …)` 兩邊都明寫 ＋ 用該檔的 `_結束行(caplog)` helper）：

```python
def test_privacy這個kind也有前後兩行log(caplog, monkeypatch):
    """隱私閘門的短問也是一次真的模型推論，所以一樣要留前後兩行。

    模型跟看圖那顆同一顆（design6 §1.1「同一顆 VLM、另一份短 prompt」），
    所以 backend／model 與 kind=vlm 完全同一組——跟著頁首開關走，不是恆 local。
    """
    caplog.set_level(logging.INFO)

    monkeypatch.setattr(config, "AI_BACKEND", "local")
    with log_ai("privacy"):
        pass
    assert len(caplog.messages) == 2, f"預期恰好兩行，實得：{caplog.messages}"
    assert caplog.messages[0].startswith("AI 開始 ")
    assert f"kind=privacy backend=local model={config.VLM_MODEL}" in _結束行(caplog)

    caplog.clear()
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    with log_ai("privacy"):
        pass
    assert f"kind=privacy backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}" in _結束行(caplog)
```

該檔的 import 已經有 `logging`、`config`、`log_ai`、`_結束行`，**不必再加任何 import**。

（可選、不影響顆數：該檔的模組 docstring 與 `ai_timing.py` 的模組 docstring 都寫「五種呼叫」，
現在是六種。要順手改就一起改，不改也不會紅。）

跑紅：

```bash
pytest tests/unit/test_privacy_gate_unit.py tests/unit/test_ai_timing_unit.py -q
```

### - [x] 步驟 2：縮圖與 PDF 進 `VlmGate`

`VlmGate.classify()` 順序：

1. `load_bytes()`
2. 若 `content_type == application/pdf`：`pdf_service.render_pages` 取第一頁；零頁／例外 → `UNCERTAIN`
3. `shrink_for_model(...)`；解不開 → `UNCERTAIN`
4. `model.judge(縮圖, "image/png")`
5. `judgement_to_verdict`

`shrink_for_model` 用 Pillow，長邊 ≤512、等比、不放大、存 PNG。
可參考 `storage_service.make_thumbnail()`（同一個 512，那邊的常數叫 `THUMBNAIL_MAX_SIDE`），
但**不要**寫進 `data/thumbs`——只回位元組（閘門的縮圖是「送進模型前的縮小」，不是使用者看的縮圖）。

**74 的十一顆必須全部繼續綠**，不是只有兩顆：`_png()` 在 74 就已經回真 PNG
（那正是為了這一刻——假位元組在這裡會解不開，九顆會一起變 `UNCERTAIN`）。
特別盯這三顆：`test_模型說敏感回SENSITIVE`（`模型.calls == 1`）、`test_會呼叫load_bytes`、
`test_檔名完全不影響判斷`。

`test_送進模型的圖長邊不超過512` 的 `load_bytes=buf.getvalue` 要注意：`getvalue` 是方法，應 `load_bytes=lambda: buf.getvalue()`。寫測試時用 lambda，不要把 bound method 傳錯成「每次回同一個 buffer 物件」。

### - [x] 步驟 3：`OllamaPrivacyModel`

簽章照總覽 §2.4.1：`def __init__(self, *, backend: str | None = None) -> None`。
實作逐項比照 `app/services/vlm_service.py` 的 `OllamaVLM`（本機）與 `OllamaCloudVLM`（雲端）——
下面每一行都是實檔現在的長相，照抄就不會走鐘：

- `backend is None` 時即時讀 `config.AI_BACKEND`（`__init__` 裡讀一次就好，
  之後 `timing_target` 是**不可變**的 `AiTarget`——與 `OllamaVLM` 一樣，一次呼叫的後端不被開關中途改掉）
- **`timing_target`**：`self._timing_target = AiTarget(backend=…, model=…)` ＋
  `@property def timing_target(self) -> AiTarget: return self._timing_target`
  （`AiTarget` 從 `app.services.ai_timing` import，`vlm_service.py` 就是這樣寫的；
  它是 `@dataclass(frozen=True, slots=True)`，只有 `backend` 與 `model` 兩欄）
- **local**：`ChatOllama(model=…, base_url=config.OLLAMA_BASE_URL, temperature=0)`
  `.with_structured_output(PrivacyJudgement)`；模型名 `config.VLM_MODEL`。
  訊息用 `HumanMessage(content=[{"type": "text", "text": PRIVACY_PROMPT},
  {"type": "image", "base64": base64.b64encode(image_bytes).decode("ascii"),
  "mime_type": content_type}])`，再 `self._model.invoke([message])`
- **cloud**：client 一律跟 `ollama_cloud.build_client()` 拿（**全系統唯一建雲端 Client 的地方**）；
  模型名 `config.OLLAMA_CLOUD_VLM_MODEL`；訊息是 dict：
  `{"role": "user", "content": PRIVACY_PROMPT + <自己那段只准回 JSON 的指令>, "images": [image_bytes]}`
  （官方套件的 `images` 直接吃 raw bytes、自己判圖片格式，所以雲端路徑用不到 `content_type`）；
  呼叫 `self._client.chat(model=…, messages=[message],
  format=PrivacyJudgement.model_json_schema(), options={"temperature": 0})`，
  回來先 `ollama_cloud.extract_json_object(response.message.content or "")`
  再 `PrivacyJudgement.model_validate_json(...)`
- prompt ＝ `PRIVACY_PROMPT`；雲端才在尾端接自己那段 JSON 保險
  （⛔ 不是 `vlm_service.CLOUD_JSON_INSTRUCTION`，理由見 §3 第 1 項）
- `with log_ai("privacy", target=self.timing_target)` 包住那一次呼叫
- **只試一次**（不像 `OllamaVLM` 那樣 `for _ in range(2)`）；例外往外丟，
  由 `VlmGate` 收成 `UNCERTAIN`——閘門的失敗方向本來就是「留在本機」，不必重試

`PRIVACY_PROMPT` 大意（繁中即可）：

> 這張圖有沒有個人敏感資訊（身分證件、健保卡、病歷、薪資、銀行帳單、護照等）？
> 只回 JSON：`{"sensitive": true或false, "confident": true或false}`。
> 看不清楚就 `confident=false`。不要描述圖、不要翻譯、不要其他欄位。

### - [x] 步驟 4：`ai_timing` 加 kind `privacy`

`app/services/ai_timing.py`（實檔 130 行）兩處：

1. **`_目標(kind)`**：現在的分支是 `embed` 一條、`vlm` 一條、`("route","answer","entity_suggest")` 一條，
   其餘 `raise ValueError`。把 `privacy` 併進 **`vlm` 那一條**（同一組 backend／model）：

```python
    if kind in ("vlm", "privacy"):
        return AiTarget(
            backend=config.AI_BACKEND,
            model=config.OLLAMA_CLOUD_VLM_MODEL if 是雲端 else config.VLM_MODEL,
        )
```

   ⚠ **不要**改成 `if kind == "privacy": return AiTarget(backend="local", …)`——
   閘門跟著頁首開關走（D6），寫死 local 的話雲端時 log 會說謊。
   也不要動 `embed` 那條的 `backend="local"`（向量永遠本機，那是另一回事）。

2. **`log_ai` 的 docstring**：`kind：vlm／embed／route／answer／entity_suggest 五選一。`
   → 六選一，把 `privacy` 加進去。

### - [x] 步驟 5：`get_privacy_gate` 換成真模型（＋ R1 的 `build_privacy_gate_for_backend`）

`app/dependencies.py`：刪掉 `_pending_privacy_model`，換成**兩支**——
寫法整個比照同檔既有的 `build_vlm_for_backend()` ／ `get_vlm()` 那一對：

```python
def build_privacy_gate_for_backend(ai_backend: str) -> privacy_gate.PrivacyGate:
    """依「指定的」後端建隱私閘門——**不看** config.AI_BACKEND。

    誰會用它：
    - get_privacy_gate()（下面那個）：web 行程／pytest，參數是當下的開關值
    - Phase 78 的 app/celery_app.py：worker 行程，參數是**入列當下寫進 job 的快照**
      job["ai_backend"]。worker 行程的 config.AI_BACKEND 永遠是預設的 "local"
      （頁首開關撥的是 web 行程的記憶體狀態，兩個行程不共用），所以這裡若改讀
      config 就會變成「頁首撥雲端、閘門仍打本機」——違反 D6 而且完全不出聲。

    理由與寫法同 build_vlm_for_backend()（design5.md D14 的同一個坑）。
    """
    return privacy_gate.VlmGate(privacy_gate.OllamaPrivacyModel(backend=ai_backend))


def get_privacy_gate() -> privacy_gate.PrivacyGate:
    """給 Depends 的隱私閘門。跟著頁首的 AI 開關走（理由與寫法同 get_vlm）。"""
    return build_privacy_gate_for_backend(config.AI_BACKEND)
```

⚠ **不要**給 `OllamaPrivacyModel` 加 `@lru_cache`（`_ollama_vlm()` 那種）：
它的後端是建構參數，快取一顆會讓第二次呼叫拿到第一次的後端。
`ChatOllama`／`ollama_cloud.build_client()` 建物件本身不連線，每次建一顆是可接受的成本。

### - [x] 步驟 6：綠

```bash
pytest tests/unit/test_privacy_gate_unit.py tests/unit/test_ai_timing_unit.py -q
pytest -q    # 566 passed、0 skipped
```

風格（pre-commit hook 與 CI 跑的是同一套）：

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

掃碼：`privacy_gate.py` 無 `RuleGate`、無 `SENSITIVE_KEYWORDS`、無 `AI_BACKEND =`。
可讀 `config.AI_BACKEND`。

**不 commit**（總覽 §7 鐵律 12：commit 節奏由產品負責人決定）。
驗收用「與開工前快照相減」：開工前 `git status --short -- app tests > /tmp/p75-before.txt`，
收工再比一次，預期只多出 `app/services/privacy_gate.py`、`app/services/ai_timing.py`、
`app/dependencies.py`、`tests/unit/test_privacy_gate_unit.py`、`tests/unit/test_ai_timing_unit.py`
（`tests/fakes.py`／`tests/conftest.py` 的改動是 Phase 74 留下的，不是本 phase 的）。

---

## 5. 完成後的專案狀態

- 端點仍 22、仍未接線
- 累計 **566**（＝ 554 ＋ 10 ＋ 2）
- **比總覽多 2 顆**（564→566）：`test_雲端短問回覆包著圍欄也解析得出來`、`test_本機短問把圖以base64塞進HumanMessage`——Phase 75 review 抓到 `judge()` 零覆蓋，controller 裁決 R10 就地補齊
- 正式 `get_privacy_gate()` 會打真模型——**所以 pytest 必須繼續走 FakePrivacyGate**，否則全量會打 Ollama
- `dependencies.build_privacy_gate_for_backend(ai_backend)` 已就位，**Phase 78 直接拿它餵 `job["ai_backend"]` 快照**（R1）

---

## 6. 常見陷阱

1. **kind=privacy 卻把 backend 寫死 local。** 閘門跟開關走，雲端時 log 必須是 `backend=cloud`。
2. **短 prompt 不小心複製 `build_vlm_prompt`。** `test_短prompt不含完整understand欄位` 就是擋這個。
3. **雲端路徑順手接了 `vlm_service.CLOUD_JSON_INSTRUCTION`。** 那一段的長相示意逐字列著
   understand 的九個鍵，接上去等於叫模型回錯的鍵 → `PrivacyJudgement` 驗證不過 → 一律 `UNCERTAIN`。
   **而且沒有測試會抓到**（`test_短prompt不含完整understand欄位` 只看 `PRIVACY_PROMPT` 本身），
   症狀是「雲端永遠卸不了壓」這種安靜壞掉。雲端那段 JSON 指令要自己寫，鍵名只有
   `sensitive`／`confident`。
4. **PDF 整份丟給 VLM。** 只渲染第一頁。多頁薪資單只有封面被看——失敗方向是 UNCERTAIN／可能漏，仍好過完全不看。
5. **74 的 `test_讀檔失敗` 被縮圖路徑改壞。** 讀檔例外必須在 shrink 之前就被接住，`model.calls == 0`。
6. **忘了 `wire_fake_ai`。** 本 phase 一接真模型，沒掛假件的測試會真的打 Ollama。554 顆必須仍全綠。
7. **`get_privacy_gate()` 裡直接 `OllamaPrivacyModel()`（不經 `build_privacy_gate_for_backend`）。**
   那樣 Phase 78 的 worker 就沒有「明傳後端」的入口，只能去讀那個永遠是 `"local"` 的
   `config.AI_BACKEND`——D6 會安靜地失效（R1）。

---

## 7. 做完之後

Phase 76 純重構 `ingest_job.py`（與閘門無關）。
Phase 78 才把閘門接進 Celery——那時 `celery_app.ingest_task` 傳的是
`gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"])`（**不是** `get_privacy_gate()`，R1），
`tests/conftest.py` 的假件要**同時**蓋 `dependencies.get_privacy_gate` 與
`dependencies.build_privacy_gate_for_backend`（後者收一個參數、忽略它、回同一顆假閘門）。
