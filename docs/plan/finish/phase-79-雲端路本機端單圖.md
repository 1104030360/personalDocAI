# Phase 79：雲端路本機端（單圖）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**順手做的三件事：
> ① 不要碰 boto3／不要打任何 `aws` 指令（★G1 還沒過，design6 §0 禁止第 1 條）；
> ② 不要寫「收到別人的訊息」與「崩潰重送 `route=cloud`」的完整規則（那是 Phase 80）；
> ③ 不要寫 PDF 的雲端路（那是 Phase 81）。

> 🎯 **一句話目標：** 把 `CloudRoute` 的本體寫出來（`available`／`submit`／`fetch_result`／
> `wait_result` 基本版／`cleanup`），並**換掉 Phase 78 留下的那一行 `NotImplementedError`**——
> 讓「非敏感 ＋ 遠端開著」的**單圖**真的走完一整圈：
> 送進寄物櫃 → 工人看圖 → 結果回來 → **本機**算向量、本機 INSERT、本機存原圖與縮圖 → 清乾淨。

**為什麼要做這個：**

Phase 78 之後，岔路口的五條出口有四條都通往 `run_ingest_job`（本機），
只有「非敏感 ＋ 遠端開著」那一條是 `NotImplementedError`。本 phase 把它補完。

補完之後，一張非敏感照片的旅程會變成這樣（design6 §2 的流程圖）：

```text
本機：PutObject context.json → PutObject input.png → SendMessage jobs
工人：收 jobs → GetObject input → 看圖 → PutObject result.json → SendMessage results
本機：收 results → GetObject result.json → **本機算向量** → INSERT ＋ 原圖 ＋ 縮圖
      → 刪 S3 三個物件 → 刪 staging → 刪 job（＝成功）
```

有三件事**刻意**留在本機，一步都不外包（design6 D1／D13）：

1. **向量（embedding）**：一定要跟資料庫裡既有的向量同源（本機 bge-m3），
   換一顆模型算出來的向量就比不出東西了。所以 `result.json` **不含向量**。
2. **INSERT 與原圖／縮圖**：正本永遠在這台 Mac 的 Postgres 與 `data/`。
   S3 只是「東西在路上時暫時放的地方」，處理完就刪。
3. **決定「這張算不算成功」**：`job` 的生死（`delete` 或標 `failed`）永遠由本機決定。

**本 phase 全程不需要 AWS 帳號**：測試用的是 `CloudRoute(FakeMailbox(), FakeProbe(True))`
——真的 `CloudRoute`（產品碼），配一顆假信箱。再加一個「假工人」小工具
（`fake_worker_process_one`），把「另一頭真的有人在做事」演出來。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **寄物櫃（mailbox）** | 本專案對 S3 這個角色的比喻：東西放進去、對方自己來拿，兩邊不必見面、不必互相開門 |
| **`context.json`** | 本機放進 S3 的一份小 JSON：資料夾清單、實體清單、最近的糾錯例子。工人靠它組出**同一份**看圖 prompt（總覽 §10 追認項 a） |
| **`result.json`** | 工人放回 S3 的看圖結果（對齊 `PhotoUnderstanding` 的九個欄位）。**不含向量**（design6 D13） |
| **順序鐵律（D9）** | 「東西先進 S3、才發訊息」。反過來的話，收到訊息的人會去拿一個還沒寫完的檔案——那是最難查的一種壞法（安靜地拿到半截 JSON） |
| **長輪詢（long polling）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 20 秒」。20 秒是 AWS 的上限，所以整筆任務的逾時（預設 300 秒）要自己在外面數 |
| **`time.monotonic()`（單調時鐘）** | 只會往前走的時鐘，不受使用者調系統時間或 NTP 校時影響——算「過了幾秒」最可靠。本專案把它包成模組層的 `_now()`，測試才換得掉（寫法沿用 `camera_session_service`） |
| **seam（接縫）** | 「可以被抽換的那一點」。本 phase 新增兩個：`_now()`（現在幾點）與 `_sleep()`（等一下下）。拿它們來「假裝時間過了」的測試小工具（`假裝過了`／`讓時鐘一直走`）是 **Phase 80** 才定義的，本 phase 不寫 |
| **假工人（`fake_worker_process_one`）** | 測試用的小工具：把 `mailbox.jobs` 裡的第一則訊息變成 `result.json` ＋ 一則 results 訊息。它**不是** `cloud_worker.py`（那是 Phase 87），只是「另一頭有人在做事」的最小替身 |
| **盡力清理（best effort cleanup）** | 「刪得掉就刪，刪不掉只記 log、不影響主流程」。善後失敗不可以蓋掉真正的錯誤 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D7 雲端管線只給非敏感** | 僅 `NON_SENSITIVE` **且**遠端可用才 Put → jobs → EC2 → result → results → 本機 Get | `run_gated_ingest_job` 的最後一條分支（換掉 Phase 78 的 `NotImplementedError`） |
| **D8 S3 是寄物櫃** | 處理成功後**刪**；Lifecycle 只是掃把 | `CloudRoute.cleanup()`：成功、失敗、fallback 三條路都會呼叫它 |
| **D9 完成訊號＝results 佇列** | 工人 PutObject 成功後才 Send；本機收到訊息才 GetObject；**禁止輪詢 HeadObject** | `wait_result()` 先收訊息、才 `get_object`；`submit()` 的順序鐵律（context → input → jobs） |
| **D13 本機入庫** | 拉回 `result.json` 後，**embedding 與 INSERT／原圖／縮圖仍在本機** | `_轉向量()` 用 Phase 76 的 `embed_understanding`（`ai_timing` 會留下 `kind=embed backend=local`）；落庫用 `insert_photo_with_files` |
| **§2.1 第 3 條** | PutObject／SendMessage 失敗 → fallback；**盡力刪**、不留半套 | `submit` 丟例外 → `cleanup()` → `_退回本機路(REASON_SUBMIT_FAILED)` |
| **§2.2／§2.3 契約** | S3 鍵名、SQS body | `submit` 用信箱的三支鍵名函式；jobs body 恰兩鍵（測試釘住「不含位元組」） |
| **§8 錯誤表第 4 列** | 送出失敗 → fallback 本機、不留半套 | `test_submit丟例外時fallback本機而且cleanup被呼叫` |
| **§8 錯誤表第 7 列** | 看圖三次失敗 → 不留 photo 列、清 staging；雲端路**還要清 S3** | `test_雲端結果說看不懂_job標failed且不留照片`（總覽 §10 追認項 g：雲端看不懂是**整筆失敗**，不是 fallback） |
| **§9 必釘第 3 條** | 非敏感＋假遠端 running → 有 PutObject＋SendMessage；假工人回結果後本機入庫、staging 空 | 本 phase 的第 5、6 顆測試 |
| **總覽 §5.2（Demo 2 對帳）** | 真機 Demo 要靠 worker log 認出「這一張走了雲端」 | 兩行契約字樣：送出前 **`route=cloud verdict=NON_SENSITIVE`**、成功收尾後 **`雲端結果已入庫：photo_id=…`**（成功的 job 會被刪掉，log 是唯一的證據） |
| **總覽 §10.2 D** | 等雲端結果時 status 維持 `analyzing`，**不新增狀態** | 落庫段不動 status；只有本機重算向量時才寫 `attempt` |
| **總覽 §10.2 E** | 雲端看圖試了幾次**不回寫** job | `result.json` 的 `attempts` 只進 log，不寫 `job["attempt"]` |
| **總覽 §10.2 R** | 雲端路落庫順序固定為 **INSERT → 立刻寫 `photo_ids` → `cleanup()` → `finish_image_job`**（D17：cleanup 是網路呼叫，被殺才不會雙 INSERT） | `_用雲端結果落庫` 第 ⑤ 步：INSERT 一成功就 `store.update(job_id, photo_ids=[photo_id])`，才清 S3；順序斷言併進 `test_雲端入庫後S3三物件與results訊息都被清掉`（顆數不變） |

---

## 2. 前置條件

**要先做完的 phase：74〜78 全部（依序）。** 本 phase 直接用到的是 74 的閘門、76 的五個積木、
77 的契約與假件、78 的接線。

**★G1 還沒到**：本 phase 全程零 AWS。

開工前**實查**基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db 與 redis 要 Up (healthy)
pytest -q
```

預期：`589 passed`、0 skipped（總覽 §9）。**一律以你實查到的數字為準**，本文件稱它「**開工基線**」——
若 Phase 78 依 controller 裁決 R1 多加了一顆（`ingest_task` 要用 `job["ai_backend"]` 的快照建閘門），
基線會是 590。本文件之後所有「全量顆數」的預期都寫成「**開工基線 ＋ 10**」，不要死背 599（**2026-09-01 實作時依 review 裁決 R13 多 1 顆，實際是「開工基線 ＋ 11」＝602**，見 §8）。

確認 Phase 76 的五個積木真的都在（本 phase **五個全部用得到**），
順帶確認 fallback 的目的地 `run_ingest_job` 還在：

```bash
python -c "
from app.services import ingest_job
for 名字 in ('load_prompt_context', 'embed_understanding', 'insert_photo_with_files',
             'finish_image_job', 'fail_job', 'run_ingest_job'):
    assert hasattr(ingest_job, 名字), 名字
print('五個積木＋run_ingest_job 都在')
"
```

預期輸出：`五個積木＋run_ingest_job 都在`。

> ⚠️ **絕對不要同時跑兩份 pytest。**

---

## 3. 範圍

### 做

1. **`app/services/cloud_ingest.py`**（Phase 77 建的檔，本 phase 加長）：
   - 兩個時間接縫 `_now()`／`_sleep()`（寫法比照 `camera_session_service`）
   - 三個新常數 `CONTEXT_CONTENT_TYPE`／`MAX_WAIT_SECONDS`／`RELEASE_BACKOFF_SECONDS`
   - `_parse_result()`（把 `result.json` 的位元組變成 dict，壞掉回 `None`）與
     `_等幾秒()`（算這一次長輪詢要跟 SQS 說等幾秒：夾在 1〜20 之間）
   - **`CloudRoute` 本體**：`available`／`submit`／`fetch_result`／`wait_result`（基本版）／`cleanup`
2. **`app/services/gated_ingest.py`**：換掉 `NotImplementedError`，補上
   「送出 → 等結果 → 用結果落庫」整條，以及 `_用雲端結果落庫()`／`_轉向量()`／`_理解()` 三支小工具。
   落庫順序依總覽 §10.2 R：INSERT → **立刻寫 `photo_ids`** → 清 S3 → `finish_image_job`。
3. **`tests/fakes.py`**：加假工人 `fake_worker_process_one(mailbox, understanding=None, *, worker_version="fake-worker")`
   （總覽 §2.4.5 寫的是 `(mailbox, understanding)`——多出來的 `worker_version` 是有預設值的
   keyword-only 參數，照總覽的寫法呼叫就對；Phase 81 會沿用同一個簽章）。
4. **`tests/unit/test_cloud_ingest_unit.py`** 追加 4 顆；
   **`tests/integration/test_gated_ingest.py`** 追加 6 顆。
5. **把 Phase 78 寫的兩顆測試升級**（`test_敏感照片走本機_零submit_job記下privacy與route` 與
   `test_不確定照片走本機_零submit`）：`cloud=` 從 `FakeCloudRoute` 換成真的
   `CloudRoute(FakeMailbox(), FakeProbe(True))`，斷言從「`submit_calls == 0`」升級成
   「**假信箱的 `put_calls == 0`**」——那正是總覽 §5.1（★G1 驗收）要的那一句。
   **顆數不變**（那個檔仍是 8 顆），只是把假的路換成真的路。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| `wait_result` 的完整五條規則 | 那是 **Phase 80**。本 phase 只處理「收到自己的訊息」與「deadline」；收到**別人的**訊息一律先還回佇列（那是五條規則裡最保守的做法，不會弄錯任何人的結果） |
| 崩潰重送 `route == "cloud"` 的處理 | 那是 **Phase 80**（它有兩顆專屬測試）。⚠ **已知的暫時缺口**：本 phase 之後，若任務剛好被殺在「送出」與「落庫」之間，重送時會退回去重問閘門、可能再送一次雲端（工人白做一次、S3 多一份垃圾）。不會產生兩張照片（上一趟根本還沒 INSERT），而且 80 緊接著就補起來 |
| PDF 走雲端路 | 那是 **Phase 81**。本 phase 的落庫段只認單圖的 `result.json`。這中間不會有人踩到——`CLOUD_ROUTE` 要到 Phase 86 才可能不是 `off`（77 的 `get_cloud_route()` 對 `assume`／`ec2` 還是 `NotImplementedError`），而 81 在 86 之前。⚠ **也不要為了「保險」加一個 `raise NotImplementedError("Phase 81")` 的 PDF 分支**：總覽 §2.7 明訂本增量只准有**唯二**的暫時分支（77 的 `get_cloud_route` 與 78 的雲端成功路），而本 phase 正是要把後者換掉——§6 的驗收就有一句 `grep NotImplementedError app/services/gated_ingest.py` 預期**零命中** |
| 雲端看圖失敗時「改用本機再看三次」 | 總覽 §10 追認項 g：遠端明明活著、只是 AI 看不懂——本機再看三次多半也一樣，而且會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意。**那是整筆失敗，不是 fallback** |
| 把 `result.json` 的 `attempts` 回寫進 `job["attempt"]` | 總覽 §10.2 E：使用者根本不知道有雲端這回事，進度面板的「第 N 次」如果從 3 開始跳會非常難懂 |
| 新增 job 狀態（例如 `waiting_cloud`） | 總覽 §10.2 D：等結果時 status 就停在 `analyzing`。加一個狀態，`progress_panel.js` 的四種顯示就會少畫一種，而 design6 §3 明文「前端不新增」 |
| 用 `HeadObject` 輪詢 S3 當完成訊號 | design6 §1.2 **已否決**（方案 A）。完成訊號永遠是 results 佇列的那一則訊息，收到之後才 `GetObject` |
| 在 `cleanup()` 裡把刪不掉的錯誤往外丟 | 善後失敗不可以蓋掉真正的錯誤。刪不掉只 log——反正 S3 還有 Lifecycle（2 天）當掃把 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並**真的跑它、親眼看到紅**。

### - [x] 步驟 1：先寫測試（紅）——`tests/unit/test_cloud_ingest_unit.py` 追加 4 顆

- [x] 檔頭的 import 區（模組 docstring 之後、`def 樣本清單` 之前）**整段換成**下面這樣。
  與 Phase 77 相比只多了兩個名字（`CloudRoute`、`FakeProbe`），**其餘一行都不要刪**
  （`dependencies`／`get_cloud_route`／`app` 那幾行是 Phase 77 的兩顆測試在用的）：

```python
from __future__ import annotations

import json
import os

import pytest

from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route
from app.main import app
from app.services.cloud_ingest import (
    ROUTE_OFF_MESSAGE,
    AlwaysRunning,
    CloudRoute,
    CloudRouteOff,
    build_context,
)
from app.services.ingest_job import PromptContext
from tests.fakes import FakeMailbox, FakeProbe
```

- [x] 在檔案**最後面**加上：

```python


# ---------------------------- ⑤ CloudRoute：送出與清理（Phase 79）----------------------------


def 一條路(信箱) -> CloudRoute:
    """真的 CloudRoute ＋ 假信箱 ＋ 「遠端開著」的假探測。"""
    return CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)


def test_submit的順序是先context再input最後jobs():
    """design6 D9 的順序鐵律：**東西先進 S3、才發訊息**。

    反過來的話，工人收到訊息的下一秒就會去 S3 拿檔，拿到的是「還沒寫完」或
    「根本不存在」——而且是**安靜地**壞（拿到半截 JSON，看圖看出一堆奇怪的東西）。
    context 要排在 input 前面則是為了同一個理由再保險一層：工人拿得到圖的那一刻，
    它要用的清單一定已經在了。

    ★ 用 FakeMailbox 的 **calls 流水帳**（總覽 §2.4.5）來驗，不要用 put_calls 這種
      整數計數器——計數器驗得出「幾次」，驗不出「誰先誰後」，而這一條規則要的正是順序。
    """
    信箱 = FakeMailbox()

    一條路(信箱).submit(
        "job-1",
        content_type="image/png",
        file_bytes=b"PNG",
        context={"folders": []},
    )

    assert 信箱.calls == [
        "put_object documents/job-1/context.json",
        "put_object documents/job-1/input.png",
        "send_job job-1",
    ]


def test_jobs訊息恰兩鍵而且不含位元組():
    """design6 §0 禁止第 2 條、§2.3 的 body 契約、§9 必釘第 7 條。

    SQS 單則上限 1 MiB（2025 年中前是 256 KB），一份多頁 PDF 幾十 MB——位元組走 S3，佇列只放「指路的紙條」。
    """
    信箱 = FakeMailbox()

    # 位元組刻意給多一點，證明「再多也不會跑進訊息裡」
    # （⚠ bytes 字面值只能放 ASCII，所以這裡不要寫中文）
    一條路(信箱).submit(
        "job-1",
        content_type="image/png",
        file_bytes=b"PNG-DATA" * 5000,
        context={"folders": [], "entities": [], "corrections": []},
    )

    assert len(信箱.jobs) == 1
    訊息 = 信箱.jobs[0]
    assert set(訊息) == {"job_id", "s3_key"}
    assert 訊息 == {"job_id": "job-1", "s3_key": "documents/job-1/input.png"}
    for 值 in 訊息.values():
        assert isinstance(值, str), f"body 只准放字串：{值!r}"
    assert "send_job job-1" in 信箱.calls


def test_input鍵名依content_type決定副檔名():
    """S3 上的 input 檔名要看得出格式——工人是靠副檔名推 content_type 的（總覽 §2.6 第 4 條）。"""
    for content_type, 副檔名 in (("image/png", ".png"), ("image/jpeg", ".jpg")):
        信箱 = FakeMailbox()

        一條路(信箱).submit("job-9", content_type=content_type, file_bytes=b"x", context={})

        assert f"documents/job-9/input{副檔名}" in 信箱.objects
        assert 信箱.jobs[0]["s3_key"] == f"documents/job-9/input{副檔名}"


def test_cleanup會刪掉三個S3物件():
    """D8：處理完就刪。Lifecycle（2 天）只是掃把，不是主要的清理手段。

    ★ cleanup 拿不到 content_type（簽章只有 job_id），所以它把**三種副檔名**
      的 input 鍵都試著刪一次。多刪不存在的鍵完全無害（真 S3 的 DeleteObjects 也是）。
    """
    信箱 = FakeMailbox()
    信箱.put_object("documents/job-1/input.png", b"x", "image/png")
    信箱.put_object("documents/job-1/context.json", b"{}", "application/json")
    信箱.put_object("documents/job-1/result.json", b"{}", "application/json")
    信箱.put_object("documents/別人的/input.png", b"x", "image/png")

    一條路(信箱).cleanup("job-1")

    assert list(信箱.objects) == ["documents/別人的/input.png"], "只准刪自己的"
    assert 信箱.delete_calls == 1, "一次刪一批，不要一個一個打 API"
```

### - [x] 步驟 2：先寫測試（紅）——`tests/integration/test_gated_ingest.py` 追加 6 顆

- [x] 檔頭的 import 區（模組 docstring 之後、`NOW = …` 之前）**整段換成**下面這樣。
  與 Phase 78 相比多了五個名字（`config`、`cloud_ingest`、`FakeMailbox`、`FakeProbe`、
  `fake_worker_process_one`）；**`FakeCloudRoute` 要留著**（Phase 78 的第 3〜8 顆還在用它）：

```python
from __future__ import annotations

import logging
from datetime import datetime

from app.core import config
from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, staging_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeCloudRoute,
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    fake_worker_process_one,
    make_jpeg_bytes,
    make_png_bytes,
)
```

- [x] 在檔案**最後面**加上：

```python


# ---------------------- ④ 雲端路：非敏感 ＋ 遠端開著（Phase 79）----------------------


class 有工人的信箱(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了。

    真實世界裡工人是另一台機器上的另一支程式，兩邊是**同時**在跑的；
    測試是單執行緒，所以把「工人動一次」掛在「本機每次去收結果」的那一刻——
    這是最貼近真實時序、又完全可預測的做法。

    工人上工=False ＝「另一頭沒有人」（Phase 80 的逾時測試會用到）。
    刻意寫在本檔而不是 tests/fakes.py：只有雲端路的整合測試用得到它，
    沿用本專案「跨測試檔不共用假件」的慣例（那樣會讓兩份測試綁在一起）。
    """

    def __init__(self, understanding=None, *, 工人上工: bool = True) -> None:
        super().__init__()
        self.understanding = understanding
        self.工人上工 = 工人上工
        self.工人做過幾次 = 0

    def receive_result(self, wait_seconds: int):
        if self.工人上工 and self.jobs:
            fake_worker_process_one(self, self.understanding)
            self.工人做過幾次 += 1
        return super().receive_result(wait_seconds)


class 送不出去的信箱(FakeMailbox):
    """PutObject 成功、SendMessage 失敗——最容易留下「半套」的那一種壞法。"""

    def send_job(self, job_id: str, s3_key: str) -> None:
        raise RuntimeError("SQS 拒絕了這則訊息")


class 壞掉的Embeddings:
    """每次都炸的向量產生器（沿用 test_ingest_job.py 的同名假件，本檔自己留一份）。"""

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("bge-m3 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("bge-m3 沒有回應")


def 雲端路(信箱, *, 開著: bool = True, 逾時秒: int = 5):
    """真的 CloudRoute ＋ 假信箱 ＋ 假探測。

    Phase 79 起一律這樣測，**不再用 FakeCloudRoute**——假的路只證明得了
    「分支走對了」，證明不了「送出去的東西長什麼樣」（總覽 §2.4.5）。
    """
    return cloud_ingest.CloudRoute(信箱, FakeProbe(開著), timeout_seconds=逾時秒)


def test_非敏感且遠端開著_雲端結果回來後本機入庫():
    """design6 §9 必釘第 3 條、D7 的一整圈。

    走完之後：照片在收件箱、staging 空了、job 被刪掉（＝成功的唯一寫法）。
    ★ 本機**沒有**看過圖：本機那顆 vlm 假件的 calls 必須是 0——看圖是工人做的。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個job(store, filename="receipt.png")
    信箱 = 有工人的信箱(收據理解)
    本機的vlm = FakeVLM(收據理解)

    跑(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=雲端路(信箱),
        vlm=本機的vlm,
    )

    assert 信箱.send_job_calls == 1
    assert 信箱.工人做過幾次 == 1
    assert 本機的vlm.calls == 0, "看圖是工人做的，本機不可以再看一次"
    assert photo_repository.count_photos() == 1
    照片 = photo_repository.list_photos_in_folder(收件箱id())
    列 = photo_repository.fetch_photo(照片[0]["id"])
    assert 列["text"] == 收據理解.text
    assert 列["category"] == "未分類", "一律先進收件箱（雲端路也一樣）"
    assert 列["suggested_category"] == "收據", "建議照樣落庫（design5 D16）"
    assert 列["original_path"] and 列["thumbnail_path"], "原圖與縮圖仍然在本機（D1／D13）"
    assert store.get(job_id) is None, "成功＝job 被刪掉"
    assert store.deleted[job_id]["route"] == "cloud"
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_雲端入庫後S3三物件與results訊息都被清掉():
    """D8：S3 是寄物櫃，處理成功就刪；Lifecycle 只是掃把。

    順帶釘住兩件事：
    1. 「results 訊息有被刪掉」——沒刪的話那則訊息會在可見度逾時後重新出現，
       被**下一筆**任務收到（總覽 §8.9 的殘訊息問題）。
    2. **先寫收據、再清 S3**（總覽 §10.2 R、design6 D17）：`photo_ids` 必須在 `cleanup()`
       之前就寫進 store。cleanup 是一次 S3 網路呼叫（S3 不通時 boto3 的重試可拖幾十秒），
       worker 在那段時間被殺的話，沒先寫 photo_ids 的版本會在重送時再 INSERT 一張。
       ★ 併在這一顆裡驗、不另開一顆（顆數不變）：拿 `FakeMailbox.calls` 的長度當時鐘，
         在 store 收到 photo_ids 的那一刻抄下「信箱做到第幾步」，事後檢查那之前沒有 delete_objects。
    """
    信箱 = 有工人的信箱(收據理解)
    寫photo_ids時信箱做到第幾步: list[int] = []

    class 記下時機的Store(記得最後一筆的Store):
        def update(self, 這個job_id, **fields):
            if "photo_ids" in fields:
                寫photo_ids時信箱做到第幾步.append(len(信箱.calls))
            return super().update(這個job_id, **fields)

    store = 記下時機的Store()
    job_id = 建一個job(store)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.objects == {}, f"S3 應該被清空了：{list(信箱.objects)}"
    assert 信箱.results == [], "results 訊息要被刪掉（不然會變成下一筆的殘訊息）"
    assert 信箱.jobs == [], "jobs 訊息要被工人刪掉"

    # 先寫收據、再清 S3（第一次寫 photo_ids 的時候，信箱還沒被叫過 delete_objects）
    assert 寫photo_ids時信箱做到第幾步, "photo_ids 從來沒有寫進 store"
    信箱在那之前做過的事 = 信箱.calls[: 寫photo_ids時信箱做到第幾步[0]]
    assert not any(c.startswith("delete_objects") for c in 信箱在那之前做過的事), (
        f"cleanup 跑在 photo_ids 之前了（總覽 §10.2 R）：{信箱.calls}"
    )
    assert any(c.startswith("delete_objects") for c in 信箱.calls), "cleanup 真的有跑"


def test_雲端結果說看不懂_job標failed且不留照片():
    """design6 §8 錯誤表第 7 列 ＋ 總覽 §10 追認項 g。

    雲端看圖三次都失敗 ＝ **這一筆失敗**，不是 fallback 本機：
    遠端明明活著，只是 AI 看不懂——本機再看三次多半也一樣，
    而且會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    信箱 = 有工人的信箱(None)  # 假工人回「三次都看不懂」
    本機的vlm = FakeVLM(收據理解)

    跑(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=雲端路(信箱),
        vlm=本機的vlm,
    )

    assert photo_repository.count_photos() == 0, "看不懂就什麼都不存（design5 D10 不變）"
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert "看不懂" in job["error"]
    assert 本機的vlm.calls == 0, "不可以改用本機再看一次（那不是這一列的規則）"
    assert 信箱.objects == {}, "失敗也要把 S3 清乾淨"
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_本機轉向量三次都失敗_不會再叫工人重看圖():
    """design6 D13：向量在本機算。算不出來是**本機**的問題，重看圖沒有幫助。

    所以重算向量最多 config.VLM_MAX_ATTEMPTS 次，而且**絕不重跑雲端那一圈**
    （工人做過幾次必須維持 1，送出次數也維持 1）。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    信箱 = 有工人的信箱(收據理解)

    跑(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=雲端路(信箱),
        embeddings=壞掉的Embeddings(),
    )

    assert 信箱.工人做過幾次 == 1, "不可以為了重算向量再送一次雲端"
    assert 信箱.send_job_calls == 1
    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["attempt"] == config.VLM_MAX_ATTEMPTS, "三次都試過了才放棄"
    assert 信箱.objects == {}


def test_雲端路的計時log裡embed是本機(caplog):
    """design6 D13 的證據：整條雲端路上，本機唯一真的打模型的地方是**轉向量**。

    所以 log 裡應該只有 kind=embed（而且 backend=local），一行 kind=vlm 都沒有
    ——那一次看圖發生在工人身上（它有自己的 log，Phase 87 才會出現）。
    """
    caplog.set_level(logging.INFO)
    store = InMemoryJobStore()
    job_id = 建一個job(store)

    跑(
        job_id,
        store=store,
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=雲端路(有工人的信箱(收據理解)),
    )

    開始行 = [m for m in caplog.messages if m.startswith("AI 開始 kind=")]
    embed行 = [m for m in 開始行 if "kind=embed " in m]
    assert len(embed行) == 1, f"應該恰好一次轉向量：{開始行}"
    assert "backend=local" in embed行[0], "向量一律本機（design6 D13）"
    assert [m for m in 開始行 if "kind=vlm " in m] == [], "本機不看圖"


def test_submit丟例外時fallback本機而且cleanup被呼叫(caplog):
    """design6 §8 錯誤表第 4 列、§2.1 第 3 條：送出失敗 → fallback，而且**不留半套**。"""
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store)
    信箱 = 送不出去的信箱()

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.put_calls == 2, "兩個物件已經放上去了（context 與 input）"
    assert 信箱.objects == {}, "cleanup 要把半套的東西刪乾淨"
    assert 信箱.delete_calls == 1
    assert photo_repository.count_photos() == 1, "照片照樣入庫（走 fallback）"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=submit_failed" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )
```

### - [x] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -q
```

預期：收集階段就失敗——

```text
ImportError: cannot import name 'CloudRoute' from 'app.services.cloud_ingest'
```

（或 `cannot import name 'fake_worker_process_one' from 'tests.fakes'`，看你先跑到哪一個。）

### - [x] 步驟 4：綠（1／3）——`tests/fakes.py` 加假工人

- [x] 檔頭 import 區補一行 `import json`（放在 `import io` 與 `import math` 中間，照字母順序）。

- [x] 在檔案**最後面**（Phase 77 那四顆假件之後）加上：

```python


def fake_worker_process_one(mailbox, understanding=None, *, worker_version="fake-worker"):
    """假工人：把 mailbox.jobs 裡的**第一則**訊息做成 result.json ＋ 一則 results 訊息。

    它**不是** app/workers/cloud_worker.py（那是 Phase 87 的事），只是「另一頭真的
    有人在做事」的最小替身：不看圖、不解析影像，照著測試指定的答案寫結果。

      understanding 給一個 PhotoUnderstanding ＝ 工人一次就看懂了
      understanding 給 None                    ＝ 工人試了三次都看不懂

    ★ 順序刻意寫成「**先 PutObject、才 SendMessage**」（design6 D9 的順序鐵律）：
      假件也要教對的做法，Phase 87 的真工人才有樣本可比。

    回傳寫出去的那份 result（測試想再檢查內容時用得到）；jobs 佇列空的時候回 None。
    """
    message = mailbox.receive_job(wait_seconds=0)
    if message is None:
        return None

    result = {
        "job_id": message.job_id,
        "worker_version": worker_version,
        "kind": "image",
        "understood": understanding is not None,
        "attempts": 1 if understanding is not None else config.VLM_MAX_ATTEMPTS,
        "understanding": understanding.model_dump() if understanding is not None else None,
    }
    mailbox.put_object(
        mailbox.result_key(message.job_id),
        json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json",
    )
    mailbox.send_result(message.job_id)
    mailbox.delete_job_message(message.receipt_handle)
    return result
```

### - [x] 步驟 5：綠（2／3）——`app/services/cloud_ingest.py` 加長

**整檔覆蓋**（下面就是本 phase 結束時這個檔案的完整內容）。與 Phase 77 **現行版**相比，
既有段落只改了模組 docstring 的「【Phase 77 只做契約】」那一段（換成「【Phase 79 補上的部分】」），
其餘逐字相同；新增的是**三行 import**（`json`／`time`／`from app.core import config`
——前兩個給 `submit`／`_parse_result` 與兩個時間接縫用，`config` 是 `cleanup()` 要讀
`config.ALLOWED_CONTENT_TYPES`）、兩個時間接縫、三個常數、`_parse_result`／`_等幾秒`、
以及 `CloudRoute` 本體。
⚠ `TYPE_CHECKING` 那段註解刻意寫「資料庫驅動程式」而不寫套件名——design3 的掃碼測試對 `app/`
做**子字串**比對、註解也算，寫出那個名字整顆測試會紅（Phase 77 §7 陷阱 10）：

```python
"""雲端路的**本機端**：契約、關掉時的替身，以及要寄給工人的那包清單。

【這個模組解決什麼問題】
增量六要讓「明確不敏感」的照片改去雲端看圖（design6 D7）。本機這一側只做四件事：

    ① 問遠端工人開著沒
    ② 把檔案與 context.json 放進 S3 寄物櫃
    ③ 發一則 jobs 訊息（只放 job_id 與 s3_key，**沒有位元組**）
    ④ 等 results 訊息，再把 result.json 拉回來

這個模組就是那四件事的家。

【這個模組刻意不做什麼】
它**不認識 boto3**——全系統只有 app/services/aws_mailbox.py 認識（Phase 83）。
它只認得兩份契約：CloudMailbox（信箱：S3 ＋ 兩條佇列）與 RemoteProbe（遠端開著沒）。
所以 Phase 78〜81 的每一顆流程測試都可以塞一顆假信箱進來跑，
pytest 從頭到尾不連 AWS（design6 §9、總覽 §7 鐵律 2 與第五道安全網）。

它也**不寫資料庫、不寫檔、不看圖**：拉回來的結果要怎麼落庫是
app/services/gated_ingest.py 的事（Phase 78〜81）。
這一層只管「東西怎麼過去、結果怎麼回來」。

【Phase 79 補上的部分】
CloudRoute 本體：available／submit／fetch_result／wait_result（基本版）／cleanup。
wait_result 的完整五條規則（收到別人的訊息怎麼辦）在 Phase 80；
Ec2Probe 在 Phase 89。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.core import config
from app.services.ingest_job_store import JobStore

if TYPE_CHECKING:
    # 只有型別檢查與讀的人需要，執行時不 import。
    # 這一行如果搬到上面去，本模組就會在 import 當下把 ingest_job → photo_repository
    # → 資料庫驅動程式整條拉進來——而 Phase 87 的雲端工人也會 import 到這個模組，
    # 那台 EC2 上根本沒有資料庫可連（design6 D11：工人不寫 Postgres）。
    # ★ 上一行刻意不寫出那個驅動程式套件的名字：design3 的掃碼測試
    #   test_SQL只出現在repository與db層 是對 app/ 底下每個 .py 做**逐字子字串**比對，
    #   註解裡出現那個字也算違規（Phase 77 §7 陷阱 10）。
    from app.services.ingest_job import PromptContext

logger = logging.getLogger(__name__)

# CloudRouteOff 的四個方法被誤呼叫時丟的訊息。抽成常數是為了讓測試 match 得逐字精準。
ROUTE_OFF_MESSAGE = "雲端路未啟用"

# context.json 放進 S3 時標的型別。S3 會把它記在物件的 metadata 上，
# 之後用瀏覽器或 CLI 看的時候才知道那是一份 JSON（工人不靠它判斷，靠鍵名）。
CONTEXT_CONTENT_TYPE = "application/json"

# 一次長輪詢最多讓 SQS 幫我們等幾秒。**20 是 AWS 訂的上限**，不是我們挑的數字。
# 所以「整筆任務最多等 5 分鐘」必須自己在外面數（deadline），不能靠這一個參數。
MAX_WAIT_SECONDS = 20

# 收到別人的訊息、還回佇列之後先歇一下再繼續，避免變成一個全速空轉的迴圈。
RELEASE_BACKOFF_SECONDS = 1


def _now() -> float:
    """現在的時基（秒）。

    用 time.monotonic()（單調時鐘）：它只會往前走，不受使用者調系統時間或 NTP 校時
    影響——算「過了幾秒」最可靠。包成模組層的一支函式是為了讓測試 monkeypatch 它，
    假裝時間過了很久（寫法沿用 app/services/camera_session_service.py 的 _now()）。
    """
    return time.monotonic()


def _sleep(seconds: float) -> None:
    """等一下下。同樣包成一支，測試才換得掉（否則逾時測試會真的睡）。"""
    time.sleep(seconds)


def _等幾秒(剩下: float) -> int:
    """這一次長輪詢要跟 SQS 說「幫我等幾秒」。

    上限 20 是 AWS 訂的；下限 1 是為了不要退化成「短輪詢」——短輪詢會一直空手而回，
    把 API 呼叫次數（也就是錢）浪費掉。剩下不到 1 秒時仍然送 1，
    多等的那一點點由外層的 deadline 收掉。
    """
    return max(1, min(MAX_WAIT_SECONDS, int(剩下)))


def _parse_result(raw: bytes, job_id: str) -> dict | None:
    """把 result.json 的位元組變成 dict；壞掉一律回 None（＝當作沒有結果）。

    為什麼要這麼小心：工人與本機是**兩支不同的程式**（EC2 上跑的可能是舊一點的映像），
    半截的 JSON、被截斷的檔、不是物件的 JSON 都有可能。
    回 None 的下場是 fallback 本機——比讓一個奇怪的 dict 流進落庫段安全得多。
    """
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        logger.warning("job %s 的 result.json 解析不了，當作沒有結果", job_id, exc_info=True)
        return None
    if not isinstance(result, dict):
        logger.warning("job %s 的 result.json 不是一個物件，當作沒有結果", job_id)
        return None
    return result


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    """從佇列拿回來的一則訊息。**只有字串，沒有位元組**（design6 §0 禁止第 2 條）。

      job_id         這則訊息在講哪一筆任務
      s3_key         jobs 訊息才有（input 檔在 S3 的名字）；results 訊息一律是 None
      receipt_handle SQS 給的**臨時**把手。要刪掉這則訊息、或要提早把它還回佇列，
                     都得用它。它不是 message id，每次收到同一則訊息時都不一樣。

    ★ 為什麼定義在這裡、而不是在 aws_mailbox.py：它是 CloudMailbox 這份**契約**的
      一部分（receive_result() 的回傳型別）。定義在 boto3 那一側的話，
      「只想用假信箱跑流程」的測試也得先 import boto3——第五道安全網就白做了。
      Phase 83 的 AwsMailbox 直接 `from app.services.cloud_ingest import MailboxMessage`
      用同一個類別，全系統只有這一個定義。
    """

    job_id: str
    s3_key: str | None
    receipt_handle: str


class CloudMailbox(Protocol):
    """寄物櫃（S3）＋兩條佇列（SQS）的契約（design6 §2.2、§2.3）。

    Protocol ＝「只要你有這些方法，你就算是一個信箱」，**不必繼承任何東西**
    （本專案的 JobStore／VLMClient／TaskDispatcher 都是這樣寫的）。
    兩個實作：正式的 AwsMailbox（Phase 83）與測試的 FakeMailbox（tests/fakes.py）。

    ⚠ Protocol 只是給編輯器與人看的規格，**執行時不會幫你檢查**。
      少寫一個方法不會在 import 時爆錯，會在真的呼叫到時才 AttributeError。

    鍵名三支（input_key／context_key／result_key）刻意放在信箱身上，
    不寫成模組層的函式：鍵名是「S3 那一側的事」，兩個實作各自負責，
    呼叫端（CloudRoute）從頭到尾不必知道 `documents/` 這個前綴長什麼樣。

    ★ 這一份契約**同時涵蓋本機端與工人端**（總覽 §2.4.1）：
      本機用 send_job／receive_result／delete_result_message／release_result_message，
      工人用 receive_job／delete_job_message／send_result，
      兩邊共用 put_object／get_object／三支鍵名；instance_state 只有 Phase 89 的
      Ec2Probe 會用到。合成一份的好處是 FakeMailbox 只要一顆，
      Phase 87 才寫得出「本機送出 → 工人處理**同一顆信箱** → 本機收回入庫」的端到端測試。
    """

    def put_object(self, key: str, body: bytes, content_type: str) -> None: ...

    def get_object(self, key: str) -> bytes | None: ...

    def delete_objects(self, keys: list[str]) -> None: ...

    def send_job(self, job_id: str, s3_key: str) -> None: ...

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None: ...

    def delete_job_message(self, receipt_handle: str) -> None: ...

    def send_result(self, job_id: str) -> None: ...

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None: ...

    def delete_result_message(self, receipt_handle: str) -> None: ...

    def release_result_message(self, receipt_handle: str) -> None: ...

    def input_key(self, job_id: str, content_type: str) -> str: ...

    def context_key(self, job_id: str) -> str: ...

    def result_key(self, job_id: str) -> str: ...

    def instance_state(self, instance_id: str) -> str: ...


class RemoteProbe(Protocol):
    """「遠端工人現在開著嗎」的契約。

    實作只有兩個：AlwaysRunning（下面，assume 模式用）與 Ec2Probe（Phase 89）。
    ★ 實作**自己要吞掉例外**：答不出來就回 False。
      「問不到答案」與「沒開機」對這個系統來說是同一件事——都走 fallback 本機
      （design6 §2.1 第 2 條）。
    """

    def is_running(self) -> bool: ...


class AlwaysRunning:
    """永遠回答「開著」的探測（CLOUD_ROUTE=assume 用；總覽 §10 追認項 l）。

    它只給階段丁（工人跑在這台 Mac 上）與除錯用。
    ⚠ 日常一定要用 ec2 模式：assume 不做任何探測，機器關著時它會傻傻地把檔案送出去，
      然後等到逾時（預設 5 分鐘）才 fallback——白白多等 5 分鐘。
    """

    def is_running(self) -> bool:
        return True


class CloudRoute:
    """本機端的雲端路：把一筆任務寄出去、等結果、收尾（design6 §2）。

    三個零件：
      mailbox         寄物櫃與兩條佇列（正式是 AwsMailbox，測試是 FakeMailbox）
      probe           遠端開著沒（assume 模式是 AlwaysRunning、ec2 模式是 Ec2Probe）
      timeout_seconds 送出之後最多等幾秒（config.CLOUD_RESULT_TIMEOUT_SECONDS）

    ★ 它**不碰資料庫、不寫檔、不看圖**：拉回來的 result.json 要怎麼落庫是
      gated_ingest 的事。這一層只管「東西怎麼過去、結果怎麼回來」。
    """

    def __init__(self, mailbox: CloudMailbox, probe: RemoteProbe, *, timeout_seconds: int) -> None:
        self._mailbox = mailbox
        self._probe = probe
        self._timeout_seconds = timeout_seconds

    def available(self) -> bool:
        """遠端現在能用嗎。**問不出來（例外）一律當作不能用**（design6 §2.1 第 2 條）。

        這裡再吞一次例外是刻意的「雙保險」：gated_ingest 那一層也吞
        （`_遠端可用嗎`），因為 available() 的實作是可以被抽換的，
        而「探測炸掉 ⇒ 整筆任務失敗」是絕對不能發生的事（§0 禁止第 6 條）。
        """
        try:
            return self._probe.is_running()
        except Exception:
            logger.warning("問遠端狀態時出錯，一律當作不可用", exc_info=True)
            return False

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        """把這一筆寄出去。順序是鐵律：**先 context、再 input、最後才發訊息**。

        為什麼順序不能換（design6 D9）：工人收到 jobs 訊息的下一秒就會去 S3 拿檔。
        訊息先發的話，它會拿到「還沒寫完」或「根本不存在」的東西——
        而且是**安靜地**壞（拿到半截 JSON，看圖看出一堆奇怪的東西）。

        任何一步失敗就把例外往外丟：呼叫端（gated_ingest）接到之後會 cleanup
        盡力刪掉半套的東西，然後 fallback 本機（design6 §2.1 第 3 條）。
        """
        context_bytes = json.dumps(context, ensure_ascii=False, default=str).encode("utf-8")
        self._mailbox.put_object(
            self._mailbox.context_key(job_id), context_bytes, CONTEXT_CONTENT_TYPE
        )

        input_key = self._mailbox.input_key(job_id, content_type)
        self._mailbox.put_object(input_key, file_bytes, content_type)

        self._mailbox.send_job(job_id, input_key)
        logger.info("job %s 已送去雲端：%s", job_id, input_key)

    def fetch_result(self, job_id: str) -> dict | None:
        """直接去 S3 看看結果在不在（**只在崩潰重送時**用；Phase 80 接上呼叫端）。

        ⚠ 這**不是**輪詢：正常流程的完成訊號永遠是 results 佇列的那一則訊息（D9），
          design6 §1.2 已經否決過「本機輪詢 HeadObject 當完成訊號」（方案 A）。
          這一支只在「佇列把同一個任務再送一次」時問**一次**，用來避免叫工人白做。
        """
        raw = self._mailbox.get_object(self._mailbox.result_key(job_id))
        if raw is None:
            return None
        return _parse_result(raw, job_id)

    def wait_result(self, job_id: str, *, store: JobStore) -> dict | None:
        """在 results 佇列上等**這一筆**的完成訊號，最多等 timeout_seconds 秒。

        回傳 result.json 的內容；逾時、或「訊息說好了但檔案不在」→ None
        （呼叫端把 None 當成「這條路走不通」→ fallback 本機）。

        ★ Phase 79 的版本只處理兩件事：收到自己的訊息、以及 deadline。
          收到**別人的**訊息一律立刻還回佇列（可見度改 0）——那是五條規則裡最保守的
          做法，不會弄丟任何人的結果。Phase 80 補上「殘訊息順手清掉」那一半。

        ★ store 這個參數本 phase 還用不到，但**現在就放進簽章**：Phase 80 的規則要靠它
          查「別人那一筆還在不在」。簽章是跨 phase 的契約（總覽 §2.4.1），先定好，
          日後新增規則時呼叫端一個字都不必改。
        """
        deadline = _now() + self._timeout_seconds
        while True:
            剩下 = deadline - _now()
            if 剩下 <= 0:
                logger.warning("job %s 等雲端結果逾時（%d 秒）", job_id, self._timeout_seconds)
                return None

            message = self._mailbox.receive_result(_等幾秒(剩下))
            if message is None:
                continue  # 長輪詢等滿了還是沒訊息，再等下一輪（deadline 會收掉）

            if message.job_id == job_id:
                return self._收下自己的結果(message, job_id)

            # 別人的訊息：立刻還回佇列給它的主人（Phase 80 會再細分成兩種情況）
            self._mailbox.release_result_message(message.receipt_handle)
            _sleep(RELEASE_BACKOFF_SECONDS)

    def cleanup(self, job_id: str) -> None:
        """盡力把這一筆在 S3 留下的東西刪光（design6 §2.1「盡力刪物件」、D8）。

        刪三種鍵：input（**三種副檔名都試一次**，因為這裡拿不到 content_type）、
        context.json、result.json。多刪不存在的鍵完全無害（真 S3 的 DeleteObjects 也是）。

        刪不掉只 log、不往外丟：cleanup 永遠是「善後」，
        不可以讓善後失敗蓋掉真正的錯誤（呼叫它的地方通常正在處理另一個失敗）。
        """
        keys = [self._mailbox.input_key(job_id, ct) for ct in sorted(config.ALLOWED_CONTENT_TYPES)]
        keys.append(self._mailbox.context_key(job_id))
        keys.append(self._mailbox.result_key(job_id))
        try:
            self._mailbox.delete_objects(keys)
        except Exception:
            logger.warning("job %s 清 S3 物件時出錯，略過", job_id, exc_info=True)

    def _收下自己的結果(self, message: MailboxMessage, job_id: str) -> dict | None:
        """訊息是我的：去 S3 把 result.json 拿回來，然後把訊息刪掉。

        ★ 就算檔案不在也要**先刪訊息**：那則訊息已經沒有用了，留著只會在可見度逾時後
          再冒出來一次、被下一筆任務收到（總覽 §8.9 的殘訊息問題）。
          檔案不在時回 None ＝ 當成逾時處理 ＝ fallback 本機（總覽 §2.5 第 2 條）。
        """
        raw = self._mailbox.get_object(self._mailbox.result_key(job_id))
        self._mailbox.delete_result_message(message.receipt_handle)
        if raw is None:
            logger.warning("job %s：收到完成訊號，但 S3 上找不到 result.json", job_id)
            return None
        return _parse_result(raw, job_id)


class CloudRouteOff:
    """雲端路關掉時的替身（CLOUD_ROUTE=off——pytest 與新 clone 的預設）。

    它就是「增量六在正式路徑上的保險絲」：available() 恆為 False，
    所以 run_gated_ingest_job（Phase 78）永遠走 fallback ＝ 增量五那條路，
    **一個位元組都不會出這台機器**。

    其餘四個方法一律丟 RuntimeError 而不是安靜地回 None：
    走到那裡代表有人接線接錯了（沒有先問 available() 就送）。
    安靜回 None 的症狀會是「照片莫名其妙沒入庫、也沒有任何錯誤訊息」——最難查的一種。
    """

    def available(self) -> bool:
        return False

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def fetch_result(self, job_id: str) -> dict | None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def wait_result(self, job_id: str, *, store: JobStore) -> dict | None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)

    def cleanup(self, job_id: str) -> None:
        raise RuntimeError(ROUTE_OFF_MESSAGE)


def build_context(prompt_context: PromptContext) -> dict:
    """組出 context.json 的內容：資料夾、實體、糾錯三份清單（總覽 §10 追認項 a）。

    工人拿到它才組得出**同一份** build_vlm_prompt(folders, entities, corrections)——
    那三份清單全都住在這台 Mac 的資料庫裡，工人自己生不出來。
    缺了它工人也不會失敗，只是少了資料夾建議與糾錯 few-shot（照樣看得懂圖）。

    為什麼放 S3 不放 SQS：SQS 的 body 契約只有 job_id 與 s3_key（design6 §2.3），
    而且單則上限只有 1 MiB（2025 年中前是 256 KB），資料夾與實體多起來遲早會超過。

    ★ inbox_name **不放進去**：收件箱名稱是本機落庫時才要用的東西（照片一律先進收件箱），
      工人只負責看圖，用不到。契約恰三鍵，多一鍵少一鍵都會讓兩邊對不起來。

    ★ 每一筆都重新 dict() 一次：回的是**乾淨的複本**，呼叫端改它不會動到
      repository 給的那份資料（那份等一下 run_ingest_job fallback 時還要用）。
    """
    return {
        "folders": [dict(folder) for folder in prompt_context.folders],
        "entities": [dict(entity) for entity in prompt_context.entities],
        "corrections": [dict(correction) for correction in prompt_context.corrections],
    }
```

### - [x] 步驟 6：綠（3／3）——`app/services/gated_ingest.py` 補上雲端成功路

**整檔覆蓋**（下面就是本 phase 結束時這個檔案的完整內容）。與 Phase 78 的版本相比：
那一行 `raise NotImplementedError("Phase 79")` 換成了「送出 → 等結果 → 用結果落庫」；
另外新增一行 `from app.core import config`、既有的 `from app.services.ingest_job_store import …`
多帶一個 `IngestJob`、模組 docstring 改寫、REASON 常數旁的註解改了兩處字，並新增三支小工具。

Phase 78 既有的 `_遠端可用嗎`／`_退回本機路` 與 `run_gated_ingest_job` 的前半段
**可執行的程式碼一行都沒動**，只有註解層面的三處差異：

1. 刪掉 78 為了說明「Phase 79 要換掉那一行」而留的兩段：`run_gated_ingest_job` docstring 的
   ★ 型別註記段、`store.update(job_id, route="cloud")` 上方那兩行。
2. `store.update(job_id, status="analyzing")` 上方那句「問閘門會花幾秒」改寫成
   VlmGate 的語意（閘門一定會送一次 VLM 短問）。
3. `load_bytes=lambda: …` 上方那三行改寫成 VlmGate 的語意（**閘門一定會讀檔**，
   惰性只是為了讓假閘門不必碰磁碟）。

> 📌 第 2、3 點就是 controller 裁決 **R4**（2026-09-01 改判：閘門只用 VLM 短問、不看檔名、
> 沒有關鍵字表，也沒有「本機模型備援」那一層）。Phase 78 校準後應該已經是這個寫法了；
> 若貼上去時發現 78 的檔案裡還留著改判前的舊說法（提到檔名比對或備援層的那種註解），
> 一律以本節的版本為準。

```python
"""入庫任務的岔路口：先問隱私閘門，再決定這一筆走本機還是雲端（design6 §2、§2.1）。

【為什麼不把這一段寫進 ingest_job.py】
run_ingest_job() 是 fallback 的**目的地**。把閘門塞進它裡面的話，
「雲端不行 → 改走本機」就會變成「自己呼叫自己」——遞迴，而且很難讀。
拆成兩個檔之後責任非常乾淨：

    gated_ingest.run_gated_ingest_job()  ＝ 決定走哪一條路（本檔）
    ingest_job.run_ingest_job()          ＝ 純本機路，一個字都沒改（增量五那一條）

【Celery 從此呼叫這裡】
app/celery_app.py 的 ingest_task 改成呼叫本檔，並多傳兩個零件：
gate（隱私閘門）與 cloud（雲端路）。兩個都是注入點，pytest 換得掉。

【三條鐵律】
1. **不確定＝本機**（design6 D3）：只有明確的 NON_SENSITIVE 才有資格走雲端。
   判斷失誤的代價因此是「這張沒卸到雲端」（＝跟現在一模一樣），而不是「敏感檔外流」。
2. **fallback 時絕不再問一次閘門**（design6 §2.1 明文禁止）：已經判定非敏感了，
   遠端沒了就本機看圖，不要卡在「非敏感但不上雲」。
3. **遠端不可用時使用者無感**（design6 §0 禁止第 6 條）：不改 5xx、不要求重傳，
   進度面板的四種狀態一個字都不變。唯一的差別在 worker 的 log。

【雲端路上，哪些事仍然留在本機】（design6 D1／D13）
  * 向量（embedding）：一定要跟庫裡既有的向量同源（本機 bge-m3），所以 result.json 不含向量
  * INSERT ＋ 原圖 ＋ 縮圖：正本永遠在這台 Mac
  * 「這一筆算不算成功」：job 的生死（delete 或標 failed）永遠由本機決定

【本 phase（79）做到哪裡】
單圖的雲端路整圈都通了。**還沒做**的兩件事：
  * 崩潰重送 route == "cloud"（Phase 80）
  * PDF 的雲端路（Phase 81）——本檔的落庫段目前只認單圖的 result.json

分層：本模組不寫 SQL、不碰 HTTP、不自己看圖——它只是「決定呼叫誰」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import cloud_ingest, ingest_job, staging_service, vlm_service
from app.services.ingest_job_store import IngestJob, JobStore
from app.services.privacy_gate import PrivacyGate, Verdict

logger = logging.getLogger(__name__)

# fallback 的四個理由（design6 §2.1）。**這四個字串是契約**——
# log 長什麼樣，design6 §2.1 有明文（`fallback=local reason=…`），測試用 caplog 逐字釘。
# 抽成常數是為了讓「產品碼」與「測試」不會各自打錯字。
REASON_REMOTE_UNAVAILABLE = "remote_unavailable"  # 不是 running／沒憑證／API 掛了（Phase 78）
REASON_SUBMIT_FAILED = "submit_failed"  # PutObject 或 SendMessage 失敗（Phase 79）
REASON_RESULT_TIMEOUT = "result_timeout"  # 送出去了但等不到結果（Phase 79 接、80 補測試）
REASON_REDELIVERED_WITHOUT_RESULT = "redelivered_without_result"  # 重送但 S3 沒結果（Phase 80）


def run_gated_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    gate: PrivacyGate,
    cloud: cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff,
) -> None:
    """一筆任務的岔路口。前四個零件原樣往下傳，後兩個在這裡用掉。

    ★ 不回傳任何東西：結果全部寫進 JobStore 與資料庫（與 run_ingest_job 同語意）。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被 dismiss：安靜結束。這不是錯誤——重送時本來就可能撞到。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    # 一進門就標 analyzing（design5 §4.4，雲端路一樣遵守）：
    # 崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    # ★ 要在問閘門**之前**：閘門一定會真的送一次 VLM 短問（總覽 §10.2 追認項 L 的推估：
    #   本機 20〜60 秒、雲端約 2 秒，未實測），那段時間面板不可以停在 queued。
    store.update(job_id, status="analyzing")

    route = job.get("route")
    if route == "local":
        # 崩潰重送，而且上一趟已經決定走本機了。**不再問一次閘門**（design6 §2.1）。
        logger.info("job %s 崩潰重送：route 已經是 local，直接走本機路", job_id)
        ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    verdict = gate.classify(
        filename=job.get("filename", ""),
        content_type=job["content_type"],
        # load_bytes 傳進去的是一個**還沒被呼叫**的函式（惰性）。唯一的真閘門
        # VlmGate（Phase 74）**一定會呼叫它**——閘門只看圖、不看檔名，也沒有關鍵字表
        # （總覽 §10.1 追認項 f）；讀檔或問模型丟例外一律回 UNCERTAIN。
        # 之所以不先把位元組讀好再傳，是為了讓測試的假閘門（FakePrivacyGate）
        # 連磁碟都不必碰——真閘門那一側完全不因此少讀一次檔。
        load_bytes=lambda: staging_service.read_staging(job_id, job["content_type"]),
    )
    store.update(job_id, privacy=verdict.value)

    if verdict != Verdict.NON_SENSITIVE:
        # 敏感 → 本機；不確定 → 也是本機（design6 D3）。**一個位元組都不出門。**
        store.update(job_id, route="local")
        logger.info("job %s route=local verdict=%s", job_id, verdict.value)
        ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    if not _遠端可用嗎(cloud, job_id):
        _退回本機路(
            job_id,
            REASON_REMOTE_UNAVAILABLE,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    # ---- 非敏感 ＋ 遠端可用 ＝ 唯一有資格走雲端的情況（design6 D7）----
    store.update(job_id, route="cloud")
    logger.info("job %s route=cloud verdict=%s", job_id, verdict.value)

    try:
        cloud.submit(
            job_id,
            content_type=job["content_type"],
            file_bytes=staging_service.read_staging(job_id, job["content_type"]),
            context=cloud_ingest.build_context(ingest_job.load_prompt_context()),
        )
    except Exception:
        # PutObject／SendMessage 失敗（design6 §8 錯誤表第 4 列）。
        # 先盡力刪掉半套的東西，再退回本機——**不留半套**是 §2.1 的明文要求。
        logger.warning("job %s：送去雲端失敗", job_id, exc_info=True)
        cloud.cleanup(job_id)
        _退回本機路(
            job_id,
            REASON_SUBMIT_FAILED,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    result = cloud.wait_result(job_id, store=store)
    if result is None:
        # 逾時，或「訊息說好了但 S3 上找不到結果」（design6 §8 錯誤表第 5 列）
        cloud.cleanup(job_id)
        _退回本機路(
            job_id,
            REASON_RESULT_TIMEOUT,
            store=store,
            vlm=vlm,
            embeddings=embeddings,
            now=now,
        )
        return

    _用雲端結果落庫(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)


def _遠端可用嗎(cloud, job_id: str) -> bool:
    """問雲端路「現在能用嗎」。**問不出來就是不能用**（design6 §2.1 第 2 條）。

    這裡把例外吃掉是刻意的：沒有 AWS 憑證、DescribeInstances 被拒、網路不通——
    對使用者來說全部都是「這次走本機」，不是「上傳失敗」（§0 禁止第 6 條）。
    真正的原因寫進 log（exc_info=True 會帶 traceback），**不寫進 job["error"]**
    ——那一欄是給人看的短句，而且這一筆根本沒有失敗。
    """
    try:
        return cloud.available()
    except Exception:
        logger.warning("job %s：問遠端狀態時出錯，一律當作不可用", job_id, exc_info=True)
        return False


def _退回本機路(
    job_id: str,
    reason: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """退回本機路：釘 route、記一行契約字樣的 log，然後跑既有的 run_ingest_job。

    ★ route 釘成 "local" 是給「這一趟又被殺掉、佇列再送一次」用的：
      下一趟一進門就看到 route=local，直接走本機——不會再問閘門，
      也不會再送一次雲端（那會讓工人白做一次、S3 多一份垃圾）。

    ★ 這裡**不再問一次閘門**（design6 §2.1 的禁止）：已經判定是非敏感了，
      遠端沒了就本機看圖。
    """
    store.update(job_id, route="local")
    logger.warning("job %s fallback=local reason=%s", job_id, reason)
    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)


def _用雲端結果落庫(
    job: IngestJob,
    result: dict,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """拿工人看好的結果，在**本機**完成剩下的事（design6 D13）：

        算向量 → INSERT ＋ 存原圖 ＋ 存縮圖 → **立刻寫 photo_ids** → 清 S3 → 收尾（刪 staging、刪 job）

    ★ 用的是 Phase 76 抽出來的積木（embed_understanding／insert_photo_with_files／
      finish_image_job／fail_job），所以本機路與雲端路的落庫行為**逐字相同**——
      建議欄位、收件箱、縮圖長邊、失敗清理，全部不必再寫一次（也就不會漂移）。
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 冪等（design6 D17）：上一次其實已經插進去了，只是收尾被打斷。
    #    再插一次會變成兩張照片——這是 SQS at-least-once 最典型的災難。
    if job.get("photo_ids"):
        logger.info("job %s 已有照片 %s，判定為崩潰重送，直接收尾", job_id, job["photo_ids"])
        cloud.cleanup(job_id)
        ingest_job.finish_image_job(
            job_id, job["photo_ids"][0], store=store, content_type=content_type
        )
        return

    # ② 工人說看不懂（三次都失敗）＝ **這一筆失敗**，不是 fallback（總覽 §10 追認項 g）
    understanding = _理解(result.get("understanding")) if result.get("understood") else None
    if understanding is None:
        logger.warning("job %s：雲端看不懂（工人試了 %s 次）", job_id, result.get("attempts"))
        cloud.cleanup(job_id)
        ingest_job.fail_job(
            job_id,
            ingest_job.ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return

    # ③ 向量在**本機**算（D13）。算不出來是本機的問題，重看圖沒有幫助，所以只重算向量。
    清單 = ingest_job.load_prompt_context()
    embedding = _轉向量(job_id, understanding, store=store, embeddings=embeddings, 清單=清單)
    if embedding is None:
        cloud.cleanup(job_id)
        ingest_job.fail_job(
            job_id,
            ingest_job.ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return

    # ④ INSERT ＋ 原圖 ＋ 縮圖（失敗時 insert_photo_with_files 自己會清乾淨再往外丟）
    try:
        photo_id = ingest_job.insert_photo_with_files(
            staging_service.read_staging(job_id, content_type),
            content_type,
            understanding,
            embedding,
            inbox_name=清單.inbox_name,
            folders=清單.folders,
            entities=清單.entities,
            uploaded_at=now(),
        )
    except Exception:
        logger.exception("job %s 入庫寫入失敗，半成品已清乾淨", job_id)
        cloud.cleanup(job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_WRITE_FAILED, store=store, content_type=content_type
        )
        return

    # ⑤ INSERT 一成功就**立刻**把收據寫進 JobStore（總覽 §10.2 R；design6 D17）。
    #    下面的 cleanup 是 S3 網路呼叫（boto3 會自己重試，可拖數十秒）；這段期間 worker 被殺，
    #    佇列會再送一次同一個 job_id → 重送時 result.json 已經被 cleanup 刪掉 → fallback 本機
    #    → run_ingest_job 看到 photo_ids 才會「直接收尾不重做」。沒先寫 photo_ids 的版本
    #    會在這裡再 INSERT 一張——SQS at-least-once 最典型的災難（phase-79 review 抓到的）。
    store.update(job_id, photo_ids=[photo_id])

    # ⑥ 再清 S3、最後收尾。**收尾一定要放最後**：finish_image_job 會把 job 刪掉，
    #    刪掉之後就沒有人記得要清 S3 了（它會再寫一次 photo_ids，與 ⑤ 重複無害）。
    cloud.cleanup(job_id)
    ingest_job.finish_image_job(job_id, photo_id, store=store, content_type=content_type)
    # ★ 這一行是**契約字樣**：Phase 88（Mac 端到端）與 92（Demo 2）都靠 grep 它對帳
    #   （`docker compose logs worker | grep 雲端結果已入庫`）。成功的 job 會被刪掉，
    #   所以「照片真的從雲端回來了」在 log 上只剩這一行證據。
    logger.info("job %s 雲端結果已入庫：photo_id=%d", job_id, photo_id)


def _轉向量(
    job_id: str,
    understanding: vlm_service.PhotoUnderstanding,
    *,
    store: JobStore,
    embeddings: Embeddings,
    清單: ingest_job.PromptContext,
) -> list[float] | None:
    """在本機把看圖結果轉成向量，最多試 config.VLM_MAX_ATTEMPTS 次；全部失敗回 None。

    ★ 只重算向量、**不重看圖**：圖是工人看的、結果已經拿到了。重看要再跑一整圈雲端
      （再 Put 一次、再等一次），而失敗的是本機的 bge-m3，重看圖一點幫助也沒有。

    ★ status 沿用既有語意：第 1 次 analyzing，第 2、3 次 retrying（design5 §4.3）。
      **雲端看圖試了幾次不回寫**（總覽 §10.2 E）：使用者根本不知道有雲端這回事，
      面板上的「第 N 次」如果從 3 開始跳會非常難懂。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        store.update(
            job_id,
            status="analyzing" if attempt == 1 else "retrying",
            attempt=attempt,
        )
        try:
            return ingest_job.embed_understanding(
                understanding, embeddings=embeddings, inbox_name=清單.inbox_name
            )
        except Exception:
            logger.warning("job %s：第 %d 次轉向量失敗", job_id, attempt, exc_info=True)
    return None


def _理解(payload: object) -> vlm_service.PhotoUnderstanding | None:
    """把 result.json 裡的 understanding 還原成 PhotoUnderstanding；還原不了回 None。

    為什麼要這麼小心：工人與本機是**兩支不同的程式**（EC2 上跑的可能是舊一點的映像），
    欄位不一定對得上。驗證不過就當作「這張看不懂」——
    寧可少一張照片，也不要讓一筆奇怪的 JSON 變成資料庫裡一列奇怪的資料。

    「看得懂但一個字都沒寫」也算看不懂（`text.strip()`）：與本機路的判準逐字相同。
    """
    if not isinstance(payload, dict):
        return None
    try:
        # model_validate ＝ 交給 Pydantic 驗整個 dict（型別、必填欄、多餘鍵），
        # 不用 **payload 拆開傳——那樣遇到不是字串的鍵會炸出另一種例外，訊息也難懂。
        understanding = vlm_service.PhotoUnderstanding.model_validate(payload)
    except Exception:
        logger.warning("result.json 的 understanding 欄位長得不對，當作看不懂", exc_info=True)
        return None
    if not understanding.understood or not understanding.text.strip():
        return None
    return understanding
```

### - [x] 步驟 7：把 Phase 78 那兩顆測試升級成「真的 CloudRoute」

Phase 78 的前兩顆用的是 `FakeCloudRoute`（假的路），只證明得了「分支走對了」。
總覽 §5.1（★G1 的驗收）要的是更硬的那一句：**假信箱的 `put_calls == 0`**。
本 phase 已經有真的 `CloudRoute` 了，把它們換掉——**顆數不變**（仍是 8 顆）。

- [x] `test_敏感照片走本機_零submit_job記下privacy與route` 裡，把這一行

```python
    路線 = FakeCloudRoute(True)
```

換成這三行（探測另外拿在手上，是為了保住 Phase 78 那句「連問都不必問遠端」的斷言）：

```python
    信箱 = FakeMailbox()
    探測 = FakeProbe(True)  # 遠端「開著」：零 Put 就只可能是閘門擋的，不是遠端關著
    路線 = cloud_ingest.CloudRoute(信箱, 探測, timeout_seconds=5)
```

並把兩行斷言

```python
    assert 路線.submit_calls == 0
    assert 路線.available_calls == 0, "敏感就該直接走本機，連問都不必問遠端"
```

換成

```python
    assert 信箱.put_calls == 0, "design6 §9 必釘第 1 條：敏感檔的 PutObject 次數必須是 0"
    assert 信箱.send_job_calls == 0
    assert 信箱.objects == {}
    assert 探測.calls == 0, "敏感就該直接走本機，連問都不必問遠端"
```

- [x] `test_不確定照片走本機_零submit` 同樣處理：把這一行

```python
    路線 = FakeCloudRoute(True)
```

換成

```python
    信箱 = FakeMailbox()
    路線 = 雲端路(信箱)
```

並把 `assert 路線.submit_calls == 0` 換成

```python
    assert 信箱.put_calls == 0
```

> 📌 `雲端路()` 這支小工具定義在本檔**後半**（步驟 2 貼上去的那一段），而這兩顆測試在前半——
> 這樣寫沒問題：Python 是在測試**執行**的那一刻才去找 `雲端路` 這個名字，那時整個檔案早就載入完了。

> 📌 `FakeCloudRoute` **仍然留著**：R13 新增的 `test_雲端路available本身丟例外_閘門層也當作不可用` 用它釘 `_遠端可用嗎` 那層的雙保險（Phase 78 的「遠端關閉／探測丟例外」兩顆已於本 phase 升級成真 `CloudRoute`），
> 因為那兩顆要的正是「路本身說不可用」這件事，不必真的有信箱。

### - [x] 步驟 8：跑測試，看它轉綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -v
```

預期：**`30 passed`**（unit 15 ＝ 11 ＋ 4，integration **15** ＝ 8 ＋ 6 ＋ **1**——
最後那一顆是 review 裁決 R13 追加的 `test_雲端路available本身丟例外_閘門層也當作不可用`，
見 §8「比總覽多 1 顆」）。
若某一顆卡住超過 10 秒，**立刻 Ctrl+C**，看常見陷阱 1（多半是 `有工人的信箱` 沒接上，
於是 `wait_result` 全速空轉到 deadline）。

```bash
pytest -q
```

預期：**開工基線 ＋ 11**（R13 追加一顆之後；實際 ＝ 591 ＋ 11 ＝ **602**），
全綠、**0 skipped**。

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：`… files already formatted` ＋ `All checks passed!`。

### - [x] 步驟 9：**不 commit**——記下工作樹快照

> ⚠ **本次增量全程不 commit**（產品負責人 2026-09-01 指示；總覽 §7 鐵律 12）。
> 不要 `git add`、不要 `git commit`、也不要把本計畫檔從 `unfinish/` 搬到 `finish/`
> （`git mv` 會直接 stage）。歸檔隨日後的 commit 由產品負責人做。

驗收改用「工作樹快照相減」：開工前先印一次、收工後再印一次，兩顆 tree SHA 相減就是本 phase 的全部改動。

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0901/snapshot-tree           # 開工前先跑一次，把 SHA 記下來（稱它 A）
# …（步驟 1〜8）…
.superpowers/sdd/phase0901/snapshot-tree           # 收工後再跑一次（稱它 B）
git diff --stat <A> <B>                            # 預期恰好 5 個檔（見下面的清單）
git diff -U10 <A> <B>                              # 逐行看改了什麼
```

預期 `git diff --stat` 只列這 5 個檔，**零刪除行以外的檔案一個都不該出現**：
`app/services/cloud_ingest.py`、`app/services/gated_ingest.py`、`tests/fakes.py`、
`tests/unit/test_cloud_ingest_unit.py`、`tests/integration/test_gated_ingest.py`。

> 📌 commit message 草稿先留著（日後產品負責人指示 commit 時直接用）：
>
> ```text
> feat: Phase 79 雲端路本機端單圖——CloudRoute 本體（available 吞例外、submit 順序 context→input→jobs、fetch_result、wait_result 基本版＋_now 與 _sleep 兩個時間接縫、cleanup 盡力刪三種鍵）、gated_ingest 補上雲端成功路（本機算向量最多三次、insert_photo_with_files、清 S3、finish_image_job；看不懂＝整筆失敗不 fallback）、fakes 加假工人 fake_worker_process_one，+10 tests；零 boto3、端點仍 22
> ```

---

## 5. ASCII 圖

### 圖一：一張非敏感照片的完整時序（本 phase 讓這一整圈通了）

```text
  本機 Celery worker                S3 寄物櫃              兩條 SQS 佇列        工人（假的／EC2）
 ────────────────────            ─────────────           ──────────────      ──────────────────
  run_gated_ingest_job
    │
    │ gate.classify → NON_SENSITIVE
    │ cloud.available() → True
    │ store.update(route="cloud")
    │
    ├─ submit ①  PutObject ──────► documents/{id}/context.json
    │      ②  PutObject ──────► documents/{id}/input.png
    │      ③  SendMessage ──────────────────────► jobs ──────────────► receive_job
    │                                                                        │
    │  （★ 順序鐵律 D9：東西先進 S3，才發訊息）                               │ GetObject input
    │                                                                        │ GetObject context
    │ wait_result（長輪詢，每次最多 20 秒，總共 300 秒）                    │ 看圖（Ollama Cloud）
    │      │                                                                 │
    │      │                        documents/{id}/result.json ◄── PutObject ┤ ④
    │      │                                                                 │
    │      │◄──────────────────────────────── results ◄──── SendMessage ─────┤ ⑤
    │      │                                                                 │ delete_job_message
    │      │ GetObject result.json ◄──────────┘                              ▼
    │      │ delete_result_message ─────────► results（刪掉，不留殘訊息）
    │      ▼
    │  用結果落庫（**全部在本機**，design6 D13）
    │      ├ embed_understanding      ← 本機 bge-m3（log: kind=embed backend=local）
    │      ├ insert_photo_with_files  ← INSERT ＋ data/photos ＋ data/thumbs
    │      ├ store.update(photo_ids)  ← ★ 先寫收據（總覽 §10.2 R）：cleanup 是網路呼叫，被殺才不會雙 INSERT
    │      ├ cloud.cleanup            → 刪掉 S3 上那三個物件（D8：寄物櫃不是檔案櫃）
    │      └ finish_image_job         → 再寫一次 photo_ids（冪等）→ 刪 staging → 刪 job（＝成功）
    ▼
  照片出現在「待決定」牆上——使用者完全看不出這一張是雲端看的。
```

### 圖二：三種結局（本 phase 全部落地）

```text
                          cloud.submit()
                                │
             ┌──────────────────┼───────────────────────────┐
             │                  │                           │
        丟例外                 成功                        成功
             │                  │                           │
             ▼                  ▼                           ▼
      cleanup(S3)        wait_result → 結果            wait_result → 結果
      route=local        understood=true               understood=false
      log reason=        │                             │
      submit_failed      ▼                             ▼
      run_ingest_job   本機算向量（最多 3 次）        cleanup(S3)
      （＝照片照樣      │                             fail_job（不留照片、清 staging）
        入庫）          ├ 成功 → INSERT → 寫收據      │
                        │        → cleanup → finish   ▼
                        └ 3 次都失敗 → cleanup      進度面板留一列紅字，
                                     → fail_job     等人按 × 關掉
                                                    ★ **不是** fallback 本機
                                                      （總覽 §10 追認項 g）
```

★ 「寫收據」＝ `store.update(job_id, photo_ids=[photo_id])`，一定在 cleanup **之前**（總覽 §10.2 R）：
cleanup 是網路呼叫，worker 在那段時間被殺的話，沒先寫收據的版本會在重送時再 INSERT 一張。

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` 記下顆數（總覽 §9 是 589；裁決 R10 讓 Phase 78
  多 2 顆——**以實查為準**，本次實查 **591**）

- [x] **`CloudRoute` 的五支公開方法與兩個接縫都在**

  ```bash
  grep -nE "^class CloudRoute|^    def (available|submit|fetch_result|wait_result|cleanup)|^def _now|^def _sleep" \
    app/services/cloud_ingest.py
  ```

  預期：**14 行**命中——`^class CloudRoute` 同時對到 `class CloudRoute:` 與 `class CloudRouteOff:`（2 行）、
  兩個類別各有 5 支同名方法（10 行）、`_now` 與 `_sleep`（2 行）。
  重點是 `class CloudRoute:`、`def _now`、`def _sleep` 各恰出現**一次**

- [x] **Phase 78 的 `NotImplementedError` 真的被換掉了**

  ```bash
  grep -n "NotImplementedError" app/services/gated_ingest.py || echo "OK：已經換掉了"
  ```

  預期：印 `OK：已經換掉了`（整個增量六只剩 `dependencies.get_cloud_route()` 那兩處，
  由 Phase 86／89 換掉）

- [x] **兩個新檔都沒有 boto3、沒有 SQL**

  ```bash
  grep -nE "psycopg|cursor\(|\.execute\(" app/services/cloud_ingest.py app/services/gated_ingest.py \
    || echo "OK：零 SQL 子字串"
  grep -nE "^\s*(import|from) +(boto3|botocore)" app/services/cloud_ingest.py app/services/gated_ingest.py \
    || echo "OK：零 boto3 import"
  pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：印 `OK：零 SQL 子字串`、`OK：零 boto3 import`，然後 `1 passed`。
  第一句是**逐字子字串** grep、預期零命中：design3 那顆掃碼測試對 `app/` 底下每個 `.py` 做子字串比對，
  **註解與 docstring 也算**——所以 `app/` 底下任何檔都不能出現「psycopg」「cursor(」「.execute(」這幾個字
  （`cloud_ingest.py` 的 `TYPE_CHECKING` 註解因此只寫「資料庫驅動程式」，不寫套件名）。
  第二句只看 import 行：docstring 裡提到「boto3」這個**字**是允許的（Phase 83 的掃碼看的也是 import 行）。

- [x] **`ingest_job.py` 仍然一個字都沒改**

  ```bash
  git diff --stat <開工前的快照 A> <收工後的快照 B> -- app/services/ingest_job.py
  ```

  預期：沒有輸出（本 phase 只**呼叫**它的積木）。
  ⚠ **不要用 `git diff --stat app/services/ingest_job.py`**：本次增量全程不 commit，
  那個指令是跟 HEAD（`a53ab57`）比，會把 Phase 76 的整份重構一起列出來——那不是本 phase 的改動。
  判準一律是「兩顆工作樹快照相減」（步驟 9）

- [x] **新測試 10 顆全綠，而且 ★G1 要的那句斷言已經在**

  ```bash
  pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -q
  grep -n "put_calls == 0" tests/integration/test_gated_ingest.py
  ```

  預期：`30 passed`（R13 追加一顆）；第二個指令**三行**命中——敏感、不確定，
  外加 controller 追加的「探測丟例外」那一顆（也升級成真 CloudRoute 了）

- [x] **先寫收據、才清 S3**（總覽 §10.2 R；防 D17 雙 INSERT）

  ```bash
  grep -nE "photo_ids=\[photo_id\]|cloud\.cleanup\(job_id\)|finish_image_job\(job_id, photo_id" \
    app/services/gated_ingest.py
  ```

  預期：最後三行命中是相鄰的 `store.update(job_id, photo_ids=[photo_id])` → `cloud.cleanup(job_id)`
  → `ingest_job.finish_image_job(...)`，行號遞增（前面幾行 `cloud.cleanup(job_id)` 是失敗路徑的，不算）。
  順序斷言在 `test_雲端入庫後S3三物件與results訊息都被清掉` 裡（顆數不變）

- [x] **雲端成功時真的留下「完成」那一行 log**（Phase 88／92 的 Demo 靠 grep 它對帳）

  ```bash
  pytest tests/integration/test_gated_ingest.py -k 雲端結果回來後本機入庫 \
         -o log_cli=true -o log_cli_level=INFO -q 2>&1 | grep 雲端結果已入庫
  ```

  預期：至少一行含 `雲端結果已入庫：photo_id=`
  （之後在真機上是 `docker compose logs worker | grep 雲端結果已入庫`）

- [x] **全量 pytest 顆數 ＝ 開工基線 ＋ 10**（實作時 R13 再補 1 顆 → **＋ 11**）

  ```bash
  pytest -q
  ```

  預期：**開工基線 ＋ 11**（R13 追加一顆之後；實際 591 ＋ 11 ＝ **602**）、**0 skipped**

- [x] **端點仍 22、openapi 零 DELETE**

  ```bash
  pytest tests/integration/test_ask_three_paths.py::test_端點數不變 \
         tests/integration/test_nav_header.py::test_端點數仍為22 -q
  ```

  預期：`2 passed`

- [x] **零依賴實證（顆數必須完全一樣）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

  預期：**與上一項逐字相同的顆數**（差一顆就代表有測試偷連外部服務）

- [x] **專案的 `data/` 沒被弄髒**

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都沒有輸出

- [x] **沒有任何測試會真的睡**（全量跑完的時間與開工前相當，不該多出幾分鐘）

  ```bash
  pytest tests/integration/test_gated_ingest.py --durations=5 -q
  ```

  預期：最慢的那幾顆都在 1 秒以內

- [x] **git 收尾（本次不 commit）**：步驟 9 的兩顆快照相減，
  `git diff --stat <A> <B>` 的變更項恰為本 phase 的 5 個檔；
  `git status --short docs/spec/` 全程零輸出（總覽 §7 鐵律 16）

---

## 7. 常見陷阱

1. **測試卡住不動（跑了好幾分鐘還沒結束）。**
   `wait_result` 是一個「等到 deadline 為止」的迴圈，而 `FakeMailbox.receive_result`
   **不會真的等**（它立刻回 None）——所以只要結果永遠不來，那個迴圈就會**全速空轉**
   到逾時秒數為止。本 phase 的測試都用 `有工人的信箱`（本機一去收，工人就把工作做完了），
   而且 `逾時秒=5`，所以不會卡。**Phase 80 的逾時測試一定要接管 `cloud_ingest._now`**
   （那份文件定義兩支時間小工具：`假裝過了()`＝把時鐘凍結在某一刻、`讓時鐘一直走()`＝每問一次
   就往前跳。本 phase 只建 `_now()`／`_sleep()` 兩個接縫，**不定義任何時間 helper**）。

2. **`submit` 的順序寫成「先發訊息、再放檔案」。**
   本機測試多半照樣綠（假工人是在本機收訊息之後才動的），
   但真的上 EC2 之後會出現「工人拿到 404、或拿到半截檔案」——而且是**安靜地**壞。
   design6 D9 是硬規定：**PutObject 成功後才 Send**。`test_submit的順序是先context再input最後jobs`
   用 `FakeMailbox.calls`（呼叫流水帳）把先後順序釘死。

3. **雲端看不懂時「改用本機再看三次」。**
   直覺上很貼心，實際上違反總覽 §10 追認項 g：遠端明明活著、只是 AI 看不懂——
   本機再看三次多半也一樣，而且會把「3 次」變成「6 次」（design5 D10 的重試上限語意被破壞），
   使用者要多等好幾分鐘才看到同一列紅字。**那是整筆失敗，不是 fallback。**

4. **落庫段忘了先檢查 `job["photo_ids"]`（冪等），或把 `photo_ids` 留到 `finish_image_job` 才寫。**
   SQS 是 at-least-once（D17）：同一則訊息可能被送兩次。少了那個檢查，
   「已經 INSERT 成功但收尾被打斷」的重送會**插出第二張一模一樣的照片**——
   而且照片沒有刪除端點（design6 未推翻），只能自己去資料庫刪。
   後半更陰險：`cleanup()` 是一次 S3 網路呼叫（S3 不通時 boto3 的重試可拖幾十秒），
   worker 在那段時間被殺的話，重送那一趟看到 `photo_ids` 是空的、result.json 又已經被刪
   → fallback 本機 → 再 INSERT 一張。**INSERT 一成功就寫 `photo_ids`**（總覽 §10.2 R）；
   `test_雲端入庫後S3三物件與results訊息都被清掉` 釘住這個順序。

5. **`cleanup()` 只刪「這次的 content_type」對應的 input 鍵。**
   簽章只有 `job_id`（契約如此），拿不到 content_type。只刪一種的話，
   fallback 之後 S3 上會留下一個孤兒 input 檔（要等 Lifecycle 兩天後才消失）。
   **三種副檔名都刪一次**，多刪不存在的鍵完全無害。

6. **在 `cleanup()` 或 `_收下自己的結果()` 裡把例外往外丟。**
   那兩支都是「善後」。善後失敗把真正的錯誤蓋掉，是最讓人抓狂的一種 bug
   （log 上只看得到「刪不掉」，看不到「為什麼會走到刪的那一步」）。

7. **`_轉向量` 寫成「連圖一起重看」（照抄 `_understand_and_embed` 的作法）。**
   本機路那樣寫是對的（圖就在手上、重看很便宜）；雲端路重看要**再跑一整圈**
   （再 Put 一次、再排一次隊、再等一次），而失敗的是本機的 bge-m3。
   `test_本機轉向量三次都失敗_不會再叫工人重看圖` 會抓到（`工人做過幾次` 會變成 3）。

8. **把 `result.json` 的 `attempts` 回寫進 `job["attempt"]`。**
   總覽 §10.2 E 明文不要：使用者不知道有雲端這回事，
   面板上的「第 N 次」忽然從 3 開始跳，只會讓人以為系統壞了。

---

## 8. 完成後的專案狀態

**單圖的雲端路整圈通了**（在假信箱上）：

- `app/services/cloud_ingest.py`：`CloudRoute` 本體 ＋ `_now()`／`_sleep()` 兩個時間接縫 ＋
  `_parse_result()`／`_等幾秒()`。仍然**零 boto3**。
- `app/services/gated_ingest.py`：Phase 78 的 `NotImplementedError` 已換成
  「送出 → 等結果 → 用結果落庫」，另加三支小工具 `_用雲端結果落庫`／`_轉向量`／`_理解`。
  落庫順序 **INSERT → 立刻寫 `photo_ids` → 清 S3 → `finish_image_job`**（總覽 §10.2 R）。
- `tests/fakes.py`：假工人 `fake_worker_process_one`。

**對外行為仍然零改變**：`CLOUD_ROUTE` 預設 `off`，正式路徑仍然每一筆都走本機。
端點仍 **22**、`photo` 表零改動、前端零改動。

**design6 §8 錯誤表現在釘住五列**：第 1、2、3 列（Phase 78）＋ 第 4 列（送出失敗）
＋ 第 7 列（看圖三次失敗）。剩下第 5、6 列（逾時與重送，Phase 80）。

**已知的暫時缺口**（Phase 80 補）：任務若剛好被殺在「送出」與「落庫」之間，
重送時 `route` 已經是 `"cloud"`，而本 phase 沒有處理那個分支——它會退回去重問閘門、
可能再送一次雲端（工人白做一次、S3 多一份垃圾）。**不會產生兩張照片**
（上一趟根本還沒 INSERT），而且 Phase 80 有兩顆專屬測試把它補起來。

**留給下一個 phase 的接口**：

| 名字 | 在哪裡 | Phase 80／81 怎麼用 |
|---|---|---|
| `CloudRoute.wait_result(job_id, *, store)` | `cloud_ingest.py` | 80 補完整五條規則（簽章不變） |
| `CloudRoute.fetch_result(job_id)` | 同上 | 80 的崩潰重送分支呼叫它 |
| `_now()`／`_sleep()`／`RELEASE_BACKOFF_SECONDS`／`MAX_WAIT_SECONDS` | 同上 | 80 定義的兩支時間小工具（`假裝過了`＝凍結、`讓時鐘一直走`＝前進）monkeypatch 前兩個；本 phase **不定義任何時間 helper**；89 的 `Ec2Probe` 共用同一個 `_now()` |
| `_用雲端結果落庫(job, result, *, store, embeddings, now, cloud)` | `gated_ingest.py` | 81 在它裡面加 PDF 分支；80／81 整檔重貼時**要帶著**「INSERT → 立刻寫 photo_ids → cleanup → finish」的順序（總覽 §10.2 R） |
| `_轉向量`／`_理解` | 同上 | 81 的每一頁都會用到 |
| `fake_worker_process_one(mailbox, understanding)` | `tests/fakes.py` | 81 讓它支援 PDF |
| `有工人的信箱`／`雲端路()` | `tests/integration/test_gated_ingest.py` | 80 直接沿用；81 在 PDF 那個檔自己留一份 |

下一步：**Phase 80** 把 `wait_result` 補成完整五條規則（收到別人的訊息怎麼辦）、
加上崩潰重送 `route == "cloud"` 的兩條分支與 D17 冪等。

測試累計 ＝ 開工基線 ＋ **11**（總覽 §9 寫 +10／599；R13 多 1 顆，實查 602）。端點 **22**（不變）。
> 📌 **實作紀錄（2026-09-01）**：開工基線實查 **591**（總覽 §9 的 589 是裁決 R10 之前的數字，R10 讓 Phase 78 多 2 顆），本 phase 收工後全量 **602 passed、0 skipped**。
>
> **比總覽多 1 顆**：`test_雲端路available本身丟例外_閘門層也當作不可用`（在 `tests/integration/test_gated_ingest.py`）。
> 來源是 review 裁決 **R13** Finding 2——步驟 7 把「探測丟例外」那一顆升級成真 `CloudRoute` 之後，
> 例外在 `CloudRoute.available()` 就被吞掉了，`gated_ingest._遠端可用嗎` 那層**刻意的雙保險** try/except
> 失去所有覆蓋（整段刪掉全量不會紅）。新那顆用 `FakeCloudRoute(RuntimeError(...))` 把它釘回來，
> 變異實驗（拆掉 try/except）實測會紅、還原後綠。
> 同一輪 R13 Finding 1 另在 `test_雲端入庫後S3三物件與results訊息都被清掉` 補兩行斷言
> （`delete_result_message`／`delete_job_message` 要出現在 `FakeMailbox.calls` 流水帳裡——
> `信箱.results == []` 證明不了「訊息被刪掉」，因為 `_receive` 當下就把它 pop 進 `_in_flight` 了），**不加顆**。
>
> 所以本 phase 實際 **+11**（`test_cloud_ingest_unit.py` +4、`test_gated_ingest.py` +7），總覽 §9 之後的累計數字要 +1。

---

## 附：本文件引用的官方文件

- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS Standard Queue（at-least-once、不保證順序）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 大訊息與 S3 pointer（為什麼位元組要走 S3）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
- [S3 `DeleteObjects`（一次刪一批；刪不存在的鍵不算錯）](https://docs.aws.amazon.com/AmazonS3/latest/API/API_DeleteObjects.html)
- [Python `time.monotonic()`（單調時鐘）](https://docs.python.org/3/library/time.html#time.monotonic)
- [Python `json.dumps`（`ensure_ascii`／`default`）](https://docs.python.org/3/library/json.html#json.dumps)
- [Pydantic `model_dump()`（把模型變成 dict）](https://docs.pydantic.dev/latest/concepts/serialization/)
- [pytest `caplog`（抓 log 來斷言）](https://docs.pytest.org/en/stable/how-to/logging.html)
