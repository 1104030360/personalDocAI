# Phase 74：隱私閘門 VLM 短問（契約與假件）

> ⚠ **檔名仍叫「規則版」是歷史。** 產品負責人 2026-09-01 改判：閘門**只用 VLM 短問題、不看檔名、無關鍵字表**。本檔已照新 D2／D4 重寫。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的四件事：
> ① 不要接線——寫完之後**沒有任何人會呼叫它**（接線是 Phase 78 的事）；
> ② 不要寫 `OllamaPrivacyModel`／縮圖／`ai_timing` kind `privacy`（那是 Phase 75）；
> ③ 不要碰 AWS、boto3、S3、SQS（★G1 之前一行 AWS 指令都不准打）；
> ④ 不要拿隱私閘門去**關**頁首那顆「AI 模型：本機｜雲端」開關（D6：閘門跟著走，不准關它）。
> ⑤ 不要寫 `RuleGate`、`SENSITIVE_KEYWORDS`、`filename_stem`、檔名比對——**已否決**。

> 🎯 **一句話目標：** 新建 `app/services/privacy_gate.py`，做出
> `Verdict` 三分類、`PrivacyJudgement`、`judgement_to_verdict`、
> `PrivacyGate`／`PrivacyModel` 兩個 Protocol、唯一真閘門 `VlmGate`
> （永遠讀檔、**不看檔名**）、以及測試假件。
> `get_privacy_gate()` 回 `VlmGate`；`wire_fake_ai` 預先掛
> `FakePrivacyGate(Verdict.UNCERTAIN)`。

**為什麼要做這個：**

增量六要把「明確不敏感」的照片卸到雲端看圖。卸之前必須先問「這張能不能進 S3」。
檔名規則（2026-08-31 初稿）會漏：`IMG_4821.jpg` 的身分證、`camera.jpg` 的收據都看不出來。
產品負責人 2026-09-01 改判：**看圖、短問題、成本要承擔**。

本 phase 先把**判斷契約**釘死（假模型、不打真 Ollama）。真模型與縮圖是 Phase 75。
接線是 Phase 78。做完之後對外行為一個字都沒變。

| 分類 | 意思 | 之後（Phase 78 接線後） |
|---|---|---|
| `SENSITIVE` | 短問判定有個人敏感資訊 | **不進 S3**，本機入庫 |
| `NON_SENSITIVE` | 短問判定不敏感而且有把握 | 才有資格走雲端管線 |
| `UNCERTAIN` | 沒把握、看不懂、讀檔失敗、模型丟例外 | **當敏感辦**，不進 S3 |

**「不確定＝本機」仍是最重要的一條。** 錯的代價是沒卸走，不是敏感檔進 AWS。

**新名詞：**

| 名詞 | 白話 |
|---|---|
| **VlmGate** | 唯一真閘門。讀位元組、問注入進來的 `PrivacyModel`、把 `PrivacyJudgement` 轉成 `Verdict`。**不看檔名** |
| **PrivacyJudgement** | 模型的兩欄答案：`sensitive`（是不是敏感）、`confident`（有沒有把握） |
| **短問題** | 只問敏不敏感，不是完整 9 欄 understand（那是入庫看圖） |
| **兩扇門** | ollama.com（頁首開關，開發加速）≠ S3／EC2（只有 `NON_SENSITIVE` 才能進） |

---

## 1. 對應 design6.md

| 章節 | 本 phase 怎麼落地 |
|---|---|
| **D2**（2026-09-01） | 分類在 PutObject 之前由 worker 觸發。本 phase 還沒接線，只提供判斷器 |
| **D3** | `Verdict` 三個值 |
| **D4**（2026-09-01） | `VlmGate` 永遠讀檔、不看檔名。真 VLM 是 Phase 75 |
| **D6** | `privacy_gate.py` **不准寫入** `AI_BACKEND`。讀它是 Phase 75 的事 |
| **§9** | 11 顆假模型測試（總覽 §2.7） |
| **§10.1 f** | 不看檔名；`test_檔名完全不影響判斷` |

---

## 2. 前置條件

**依賴：無。** 開工基線與 Phase 73 之後相同。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest --collect-only -q | tail -1   # 預期：543 tests collected
pytest -q                            # 預期：543 passed、0 skipped
```

**本 phase 做完 = 543 ＋ 11 ＝ 554。**

⚠️ 絕對不要同時跑兩份 pytest（`reset_tables` 會互清）。

---

## 3. 範圍

### 做

1. **新建 `app/services/privacy_gate.py`**
   - `Verdict(StrEnum)`：`SENSITIVE`／`NON_SENSITIVE`／`UNCERTAIN`
   - `PrivacyJudgement`：`sensitive: bool`、`confident: bool`
   - `judgement_to_verdict(judgement) -> Verdict`
   - `PrivacyGate` Protocol：`classify(*, filename, content_type, load_bytes) -> Verdict`
   - `PrivacyModel` Protocol：`judge(image_bytes, content_type) -> PrivacyJudgement`
   - `VlmGate(model)`：讀 `load_bytes()` → `model.judge(...)` → `judgement_to_verdict`；讀檔或 judge 丟例外 → `UNCERTAIN`；**verdict 不讀 filename**
2. **`app/dependencies.py` 加 `get_privacy_gate()`** → `VlmGate(_pending_privacy_model())`。
   `_pending_privacy_model()` 回一個「任何呼叫都回 `PrivacyJudgement(sensitive=False, confident=False)`」的內部物件（＝永遠 `UNCERTAIN`）。Phase 75 把這裡換成 `OllamaPrivacyModel`。沒人呼叫它，行為安全。
3. **`tests/fakes.py`**：`FakePrivacyGate(verdict)`（記 `calls`／`last_filename`／`last_content_type`）、`FakePrivacyModel(judgement)`（記 `calls`／`last_image_bytes`／`last_content_type`；可設 `raise_on_judge`）。
4. **`tests/conftest.py` 的 `wire_fake_ai`**：`get_privacy_gate → FakePrivacyGate(Verdict.UNCERTAIN)`
   （目前是**六個** overrides，本 phase 之後變**七個**；兩處 docstring 的「六個」要一起改，見步驟 4）。
5. **新建 `tests/unit/test_privacy_gate_unit.py`（11 顆）**——總覽 §2.7 逐字那些名字。

> 📌 **`app/core/config.py` 本 phase 一個字都不動。** 總覽 §2.7 的「動到的檔」還列著它，
> 那是 2026-09-01 改判前的殘留（規則版時代要放 `SENSITIVE_KEYWORDS`／`PRIVACY_GATE_LOCAL_MODEL`，
> 兩者都已否決）。VLM 短問要用的模型名（`VLM_MODEL`／`OLLAMA_CLOUD_VLM_MODEL`）與
> `AI_BACKEND` **config 早就有了**，Phase 75 直接讀即可。

### 明確不做

| 不做 | 為什麼 |
|---|---|
| 檔名關鍵字／`RuleGate`／`filename_stem` | 2026-09-01 否決 |
| `OllamaPrivacyModel`、縮圖、kind `privacy` | Phase 75 |
| 接進 `ingest_task` | Phase 78 |
| 寫入 `config.AI_BACKEND` | D6 |
| AWS | ★G1 之前禁止 |
| 新端點 | design6 §5，恆 22 支 |

---

## 4. 實作步驟（TDD）

### - [x] 步驟 1：先寫測試（紅）

新建 `tests/unit/test_privacy_gate_unit.py`：

```python
"""隱私閘門 VLM 短問的契約測試（design6.md D2〜D4，2026-09-01 改判）。

★ 本檔不打真模型。VlmGate 吃 FakePrivacyModel；注入點吃 FakePrivacyGate。
"""

from __future__ import annotations

from app.dependencies import get_privacy_gate
from app.services.privacy_gate import PrivacyJudgement, Verdict, VlmGate, judgement_to_verdict
from tests.fakes import FakePrivacyGate, FakePrivacyModel, make_png_bytes


def _png() -> bytes:
    """真的 PNG，不是假位元組。

    Phase 75 會在 VlmGate.classify() 裡加一段縮圖（長邊 ≤512），假位元組
    Pillow 解不開 → 那時本檔十一顆裡有九顆會一起變 UNCERTAIN 而翻紅。
    從一開始就用真圖，75 接上縮圖之後這十一顆一顆都不必改。
    """
    return make_png_bytes()


def 判斷(模型: FakePrivacyModel, *, filename: str = "any.jpg") -> Verdict:
    return VlmGate(模型).classify(
        filename=filename,
        content_type="image/jpeg",
        load_bytes=_png,
    )


def test_模型說敏感回SENSITIVE():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=True, confident=True))
    assert 判斷(模型) is Verdict.SENSITIVE
    assert 模型.calls == 1


def test_模型說不敏感而且有把握回NON_SENSITIVE():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    assert 判斷(模型) is Verdict.NON_SENSITIVE


def test_模型說不敏感但沒把握回UNCERTAIN():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=False))
    assert 判斷(模型) is Verdict.UNCERTAIN


def test_sensitive即使沒把握也當SENSITIVE():
    """沒把握的「是敏感」仍當敏感——錯的方向必須是留下，不是出門。"""
    assert (
        judgement_to_verdict(PrivacyJudgement(sensitive=True, confident=False)) is Verdict.SENSITIVE
    )


def test_模型丟例外回UNCERTAIN():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True), raise_on_judge=True)
    assert 判斷(模型) is Verdict.UNCERTAIN


def test_讀檔失敗回UNCERTAIN():
    def 炸掉() -> bytes:
        raise OSError("staging 沒了")

    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    結果 = VlmGate(模型).classify(filename="x.jpg", content_type="image/jpeg", load_bytes=炸掉)
    assert 結果 is Verdict.UNCERTAIN
    assert 模型.calls == 0


def test_檔名完全不影響判斷():
    模型 = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    閘門 = VlmGate(模型)
    a = 閘門.classify(filename="身分證.jpg", content_type="image/jpeg", load_bytes=_png)
    b = 閘門.classify(filename="receipt.jpg", content_type="image/jpeg", load_bytes=_png)
    assert a is Verdict.NON_SENSITIVE
    assert b is Verdict.NON_SENSITIVE


def test_會呼叫load_bytes():
    讀了 = {"n": 0}

    def 讀() -> bytes:
        讀了["n"] += 1
        return _png()

    VlmGate(FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))).classify(
        filename="ignored.jpg", content_type="image/jpeg", load_bytes=讀
    )
    assert 讀了["n"] == 1


def test_get_privacy_gate回VlmGate():
    assert isinstance(get_privacy_gate(), VlmGate)


def test_FakePrivacyGate固定回傳指定verdict():
    假 = FakePrivacyGate(Verdict.SENSITIVE)
    assert (
        假.classify(filename="x.jpg", content_type="image/png", load_bytes=_png)
        is Verdict.SENSITIVE
    )
    assert 假.calls == 1
    assert 假.last_filename == "x.jpg"


def test_wire_fake_ai預設掛UNCERTAIN():
    """Depends 走 overrides；直接呼叫 get_privacy_gate() 仍是正式 VlmGate。"""
    from app.main import app

    閘門 = app.dependency_overrides[get_privacy_gate]()
    assert isinstance(閘門, FakePrivacyGate)
    assert (
        閘門.classify(filename="a.jpg", content_type="image/jpeg", load_bytes=_png)
        is Verdict.UNCERTAIN
    )
```

⚠ **import 那一段刻意只有 `app.dependencies`／`app.services.privacy_gate`／`tests.fakes` 三行。**
`from app.core import config` 與
`from app.services import privacy_gate` 這兩個在本 phase 的十一顆裡**一次都沒用到**，
寫上去會被 `ruff check` 判 **F401（imported but unused）**——`pyproject.toml` 的
`select = ["E", "F", "I"]` 開著 F，pre-commit hook 會擋下 commit。
那兩行要等 **Phase 75** 真的用到（`config.AI_BACKEND`、`privacy_gate.OllamaPrivacyModel`）
才加進來，那時 ruff 就不吵了。

跑一次確認紅：

```bash
pytest tests/unit/test_privacy_gate_unit.py -q
```

### - [x] 步驟 2：實作 `privacy_gate.py`

```python
"""隱私閘門：照片進 S3 之前，用 VLM 短問題分成三類。

不看檔名。filename 只在簽章裡因為呼叫端本來就有、假件要記帳。
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class Verdict(StrEnum):
    SENSITIVE = "SENSITIVE"
    NON_SENSITIVE = "NON_SENSITIVE"
    UNCERTAIN = "UNCERTAIN"


class PrivacyJudgement(BaseModel):
    sensitive: bool
    confident: bool


def judgement_to_verdict(judgement: PrivacyJudgement) -> Verdict:
    if judgement.sensitive:
        return Verdict.SENSITIVE
    if judgement.confident:
        return Verdict.NON_SENSITIVE
    return Verdict.UNCERTAIN


class PrivacyGate(Protocol):
    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict: ...


class PrivacyModel(Protocol):
    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement: ...


class VlmGate:
    """唯一真閘門：讀檔 → 問模型 → 三分類。不看 filename。"""

    def __init__(self, model: PrivacyModel) -> None:
        self._model = model

    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict:
        del filename  # 契約：verdict 不得依賴檔名
        try:
            圖 = load_bytes()
            判斷 = self._model.judge(圖, content_type)
        except Exception:
            return Verdict.UNCERTAIN
        return judgement_to_verdict(判斷)
```

### - [x] 步驟 3：假件

在 `tests/fakes.py` 追加：

```python
class FakePrivacyGate:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0
        self.last_filename = None
        self.last_content_type = None

    def classify(self, *, filename, content_type, load_bytes):
        self.calls += 1
        self.last_filename = filename
        self.last_content_type = content_type
        return self.verdict


class FakePrivacyModel:
    def __init__(self, judgement, *, raise_on_judge=False):
        self.judgement = judgement
        self.raise_on_judge = raise_on_judge
        self.calls = 0
        self.last_image_bytes = None
        self.last_content_type = None

    def judge(self, image_bytes, content_type):
        self.calls += 1
        self.last_image_bytes = image_bytes
        self.last_content_type = content_type
        if self.raise_on_judge:
            raise RuntimeError("假模型炸掉")
        return self.judgement
```

（把 `verdict`／`judgement` 的型別註解補上，與專案既有 fake 風格對齊。）

### - [x] 步驟 4：注入點與安全網

`app/dependencies.py`：

```python
def _pending_privacy_model() -> privacy_gate.PrivacyModel:
    """Phase 75 之前沒有真 Ollama。沒人呼叫 classify，回永遠 UNCERTAIN 是安全的。"""

    class _AlwaysUncertain:
        def judge(self, image_bytes: bytes, content_type: str) -> privacy_gate.PrivacyJudgement:
            return privacy_gate.PrivacyJudgement(sensitive=False, confident=False)

    return _AlwaysUncertain()


def get_privacy_gate() -> privacy_gate.PrivacyGate:
    return privacy_gate.VlmGate(_pending_privacy_model())
```

`tests/conftest.py`（實檔 302 行）三件事：

1. **import**：`from app.dependencies import (...)` 那一塊（帶 `# noqa: E402` 的那個）
   把 `get_privacy_gate` 依字母序插進去（`get_now` 之後、`get_router` 之前——n ＜ p ＜ r；放錯位置 ruff 會報 I001，2026-09-01 實作時實測）；
   `from tests.fakes import (...)` 那一塊加 `FakePrivacyGate`（在 `FakeRouter` 前面）；
   另外要 `from app.services.privacy_gate import Verdict`（同樣帶 `# noqa: E402`——
   本檔的 import 刻意不在檔頭，`E402` 是逐行 noqa 掉的，不是整檔關掉）。
2. **`wire_fake_ai` 本體**：在既有六行 `app.dependency_overrides[...] = ...` 之後多一行
   `app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.UNCERTAIN)`。
   結尾的 `app.dependency_overrides.clear()` 不動。
3. **兩處 docstring 的「六個」都要改成「七個」**（只改一處會前後矛盾）：
   - 檔頭 docstring 第 4 行：`wire_fake_ai          六個 AI 注入點全換假件＋固定時鐘（絕不打真 Ollama）`
   - `wire_fake_ai` 自己的 docstring：`六個注入點全部都要接上假件，` ——
     同一段下面還有六個「- get_xxx 預設 …」的條列，順手補第七條
     `- get_privacy_gate 預設 FakePrivacyGate(UNCERTAIN)（＝全部走本機，既有 543 顆行為零改變）`。

### - [x] 步驟 5：綠

```bash
pytest tests/unit/test_privacy_gate_unit.py -q   # 11 passed
pytest -q                                        # 554 passed、0 skipped
```

風格（`pyproject.toml` 的 `select = ["E","F","I"]`；pre-commit hook 與 CI 都跑同一套）：

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

掃碼：`privacy_gate.py` 裡不准出現 `SENSITIVE_KEYWORDS`、`RuleGate`、`AI_BACKEND =`。

**不 commit**（增量六期間 commit 節奏由產品負責人決定，總覽 §7 鐵律 12）。
驗收改用「與開工前快照相減」：開工前先 `git status --short -- app tests > /tmp/p74-before.txt`，
收工再比一次，預期只多出 `app/services/privacy_gate.py`、`app/dependencies.py`、
`tests/fakes.py`、`tests/conftest.py`、`tests/unit/test_privacy_gate_unit.py` 五個檔。

---

## 5. 完成後的專案狀態

- 端點仍 22、對外行為零改變
- 多 11 顆；累計 554
- 正式路徑的 `get_privacy_gate()` 回 `VlmGate`（模型是永遠 UNCERTAIN 的占位；75 換掉）
- 測試路徑永遠 `FakePrivacyGate(UNCERTAIN)`＝接線後既有測試仍走本機

---

## 6. 常見陷阱

1. **用檔名當捷徑。** 產品負責人否決了。`del filename` 就是為了讓「順手 `if 'passport' in filename`」編不過／測得出來。
2. **搞混「直接呼叫」與「Depends 解析」。** `dependency_overrides` **只在 FastAPI 解析 `Depends(...)` 時生效**，
   直接 `get_privacy_gate()` 拿到的永遠是正式函式——所以 `test_get_privacy_gate回VlmGate`
   照上面那樣寫就測得到正式路徑，**不必**去 `pop` 那個 key。
   真正要小心的是別把它寫成 `app.dependency_overrides[get_privacy_gate]()`——那是下一顆
   （`test_wire_fake_ai預設掛UNCERTAIN`）在測的東西，兩顆會變成同一顆。
3. **把 `judgement_to_verdict` 做成「沒把握一律 UNCERTAIN」。** `sensitive=True, confident=False` 必須是 `SENSITIVE`。
4. **在 74 就打真 Ollama。** 本檔零網路。真模型是 75。
5. **把 `_png()` 寫成假位元組。** 本 phase 不解碼圖，假的也會綠——但 Phase 75 會在
   `classify()` 裡加縮圖，那時假位元組解不開、十一顆裡有九顆一起變 UNCERTAIN 而翻紅。
   `_png()` 從一開始就回 `make_png_bytes()`（真 PNG）。

---

## 7. 做完之後

Phase 75：同一顆看圖模型、短 prompt、跟 `AI_BACKEND`、縮圖 512、kind `privacy`、PDF 渲染第一頁。

⚠ **Phase 75 還會多做一件本 phase 刻意不做的事**（controller 裁決 R1）：
在 `app/dependencies.py` 新增 `build_privacy_gate_for_backend(ai_backend: str)`，
並讓 `get_privacy_gate()` ＝ `build_privacy_gate_for_backend(config.AI_BACKEND)`。
理由是 **worker 行程的 `config.AI_BACKEND` 永遠是預設的 `"local"`**（頁首開關撥的是 web 行程的
記憶體狀態），Phase 78 接進 Celery 時只能靠 `job["ai_backend"]` 快照——沿用既有
`build_vlm_for_backend()` 的同一套寫法。**本 phase 不要先做**：74 的 `get_privacy_gate()`
就是 `VlmGate(_pending_privacy_model())`，占位模型永遠回 `UNCERTAIN`，沒有後端可分流。
