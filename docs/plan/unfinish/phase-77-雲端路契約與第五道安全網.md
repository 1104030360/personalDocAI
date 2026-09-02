# Phase 77：雲端路契約與第五道安全網

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**順手做的三件事：
> ① 不要裝 `boto3`、不要寫任何 AWS 呼叫（那是 Phase 83，而且 ★G1 之前一行 AWS 指令都不准打）；
> ② 不要寫 `CloudRoute`——這個類別在 Phase 77 **整個不存在**（不是空殼、也不是 stub）：
>   `submit`／`fetch_result`／`wait_result`／`cleanup` 是 Phase 79／80 的事；
> ③ 不要把閘門接到 Celery 上（那是 Phase 78）——本 phase 做完，系統的行為與增量五**逐字相同**。

> 🎯 **一句話目標：** 先把「雲端路」這件事的**契約**與**假件**做出來——一份信箱契約（`CloudMailbox`）、
> 一份遠端探測契約（`RemoteProbe`）、一顆「雲端路關掉時的替身」（`CloudRouteOff`），
> 再加上 `tests/conftest.py` 的**第五道 autouse 安全網 `wire_fake_cloud`**，
> 保證 pytest 從此**絕不連真 AWS**。

**為什麼要做這個：**

增量六要讓「明確不敏感」的照片改去雲端看圖。本機這一側要做的事其實只有四件：

1. 問一下遠端工人開著沒；
2. 把檔案與「看圖要用的清單」放進 S3 寄物櫃；
3. 發一則「有新工作了」的訊息到 jobs 佇列；
4. 等 results 佇列回一則「做完了」，再把 `result.json` 拉回來。

這四件事**每一件都會打到 AWS**。如果直接寫成「呼叫 boto3」，那麼之後 Phase 78〜81
的每一顆流程測試（閘門走對了沒、fallback 有沒有發生、逾時會不會重複入庫……）
都得先有一個 AWS 帳號、都得連網、都得花錢。**那是不可接受的**：
本專案的 pytest 從第一天起就「絕不打真 Ollama、絕不連真 Redis、絕不寫專案 `data/`、絕不清正式庫」
（四道 autouse 安全網），雲端這條路沒有理由破例（design6 §9 明文：**pytest 不連真 AWS**）。

所以順序要倒過來：**先訂契約、先做假件、先架安全網，最後才寫真的 AWS 呼叫**。

做完本 phase 之後：

- `app/services/cloud_ingest.py` 存在了，但它**一行 boto3 都沒有**——它只認得「信箱」這份契約。
- `app/core/config.py` 有了 `CLOUD_ROUTE` 等九個新設定，預設值一律是「關掉」與「空的」。
- `app/dependencies.py` 有了 `get_cloud_route()`，`CLOUD_ROUTE=off` 時回一顆
  「永遠說遠端不可用」的替身 `CloudRouteOff()`。
- `tests/conftest.py` 有了第五道安全網：`CLOUD_ROUTE` 被蓋成 `off`、`get_cloud_route` 兩條路都被換掉、
  `AWS_ENDPOINT_URL` 被指到**死埠**（就算有人日後漏接假件，boto3 也只會立刻 connection refused，
  絕不會真的把位元組送出這台機器）。
- `tests/fakes.py` 有了 `FakeMailbox`（一顆假件同時扮演 S3 ＋ 兩條佇列）、`FakeProbe`、
  `ScriptedProbe`、`FakeCloudRoute`——78〜81、87、89 的測試全部靠它們。

**但目前還沒有任何人呼叫它們**：Celery 仍然直接呼叫 `run_ingest_job`（那是 Phase 78 才改），
所以**對外行為零改變、端點仍是 22 個、正式路徑一個位元組都不會出這台機器**。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **S3（Simple Storage Service）** | AWS 的檔案存放服務。你丟一個檔案進去、給它一個名字，之後用那個名字拿回來。本專案只拿它當**寄物櫃**（東西在路上時暫時放的地方），**不是**檔案櫃、不是備份、不是相簿（design6 D8） |
| **bucket（桶）** | S3 裡的一個「大資料夾」，名字**全世界唯一**。所有檔案都放在某個 bucket 裡面 |
| **key（物件鍵）** | 一個檔案在 bucket 裡的完整名字，例如 `documents/abc123/input.jpg`。「key」不是密碼的意思，就是「檔名」 |
| **prefix（前綴）** | S3 其實沒有真的資料夾，只有「名字開頭一樣」的一群檔案。`documents/` 就是本專案用的前綴 |
| **SQS（Simple Queue Service）** | AWS 的訊息佇列。一邊放紙條、另一邊拿紙條。本專案用兩條：`jobs`（本機→工人）與 `results`（工人→本機） |
| **receipt handle（收據把手）** | 從佇列拿走一則訊息時，SQS 給你的一串**臨時**字串。要刪掉那則訊息、或要提早讓它重新出現，都得用它。它**不是** message id，而且每次拿到同一則訊息時都不一樣 |
| **long polling（長輪詢）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 20 秒」，而不是「沒有就馬上回我空的」。好處是少打很多次 API（＝省錢）。20 秒是 AWS 的上限 |
| **ChangeMessageVisibility（改可見度）** | 用 receipt handle 把「這則訊息隱形多久」改掉。改成 **0** ＝「我拿錯了，馬上還回去給別人」。本專案的 `release_result_message()` 就是它 |
| **boto3** | Python 呼叫 AWS 的官方套件。本增量唯一新增的依賴，**Phase 83 才裝**；而且全系統只有 `app/services/aws_mailbox.py` 可以 import 它 |
| **`AWS_ENDPOINT_URL`** | boto3 認得的**標準環境變數**：「不要連 AWS，連這個網址」。本專案只在 pytest 的安全網與「零依賴實證」時把它指到死埠 |
| **死埠（discard port）** | 埠號 9。這是網路標準保留給「丟掉一切」的埠，本機一定沒有程式在聽，所以連它會**立刻** connection refused，而不是卡住等逾時。本專案用它證明「測試真的沒有連出去」 |
| **`Protocol`（協定／結構型別）** | Python 的「只寫規格、不寫實作」的寫法：「只要你有這幾個方法，你就算是一個信箱」，**不必繼承任何東西**。本專案的 `JobStore`／`VLMClient`／`TaskDispatcher` 都是這樣寫的 |
| **契約（contract）** | 本文件裡指「兩邊都必須遵守的形狀」：函式叫什麼、吃什麼、回什麼。契約定好了，兩邊才可以各自替換 |
| **假件（fake）** | 測試用的替身。它不是「空殼」——`FakeMailbox` 真的會記住你放進去的東西、真的會把訊息排隊，只是全部發生在記憶體裡 |
| **autouse fixture** | pytest 的「每個測試都自動套用的前置／後置動作」，不必在測試函式的參數列寫它的名字 |
| **seam（接縫）** | 「可以被抽換的那一點」。本專案的 `get_vlm`／`get_now`／`get_job_store` 都是接縫，`get_cloud_route` 是本 phase 新增的那一個 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **§2 流程** | 上傳 → Celery → Gate →（本機｜雲端）→ 入庫的全景 | 本 phase 只做雲端那半邊的**骨架**：`CloudMailbox`／`RemoteProbe` 兩份契約 ＋ `CloudRouteOff` 替身 ＋ `build_context()` |
| **§2.2 S3 鍵名（契約）** | `documents/{job_id}/input.*`、`documents/{job_id}/result.json` | `CloudMailbox` 的三支鍵名函式（`input_key`／`context_key`／`result_key`）就是這個契約的簽章；`FakeMailbox` 照著實作一份，Phase 83 的 `AwsMailbox` 再實作一份 |
| **§2.3 SQS 佇列（契約）** | 兩條 Standard Queue；body 只有 `job_id`／`s3_key` | 佇列**七支**的簽章——本機端 `send_job`／`receive_result`／`delete_result_message`／`release_result_message`，工人端 `receive_job`／`delete_job_message`／`send_result`；`FakeMailbox` 的兩條清單就是那兩條佇列 |
| **D10 遠端關掉＝fallback** | EC2 不是 running、沒憑證、API 失敗、逾時 → 走本機 | `RemoteProbe` 這份契約 ＋ `CloudRouteOff.available()` 恆為 `False`。**本 phase 之後，正式路徑永遠走本機** |
| **§9 測試策略** | 沿用四道 autouse，再加**假 AWS 客戶端**，pytest 不連真 AWS | 第五道 autouse `wire_fake_cloud` ＋ `FakeMailbox`／`FakeProbe`／`ScriptedProbe`／`FakeCloudRoute` |
| **§4 資料流與冪等** | 狀態放 JobStore，`photo` 表不加欄 | `IngestJob` 加 `privacy`／`route` 兩個**可選**欄位；`photo` 表一個字都不動 |
| **總覽 §2.4.1／§2.4.2／§2.4.5 裁決** | 新檔簽章、設定變數、假件名稱 | 本 phase 逐字落地（名稱自己發明＝錯） |
| **總覽 §10.1 追認項 a** | S3 多一個鍵 `context.json`（design6 §2.2 沒列） | `build_context()` ＋ `CloudMailbox.context_key()`。理由：工人組不出同一份看圖 prompt——資料夾清單、實體清單、糾錯例子全都在**這台 Mac 的資料庫**裡 |
| **總覽 §10.2 追認項 C** | `cloud_ingest.py`（流程）與 `aws_mailbox.py`（boto3）拆兩層 | 本 phase 只做上層。合成一個檔的話，78〜81 的每一顆流程測試都會被迫依賴 boto3 |

---

## 2. 前置條件

**要先做完的 phase：**

- **Phase 74（隱私閘門 VLM 短問：契約與假件）** —— 本 phase 的第五道安全網要放在第四道之後、
  而 Phase 74 已經把 `wire_fake_ai` 改過一次（多接 `get_privacy_gate` → `FakePrivacyGate(Verdict.UNCERTAIN)`）。
  先做 74 才不會兩份改動撞在一起。
  > 📌 **檔名 `phase-74-隱私閘門規則版.md` 是歷史，不改檔名。** 產品負責人 2026-09-01 改判：
  > 閘門**只用 VLM 短問題**（同一顆看圖模型、另一份只答 `{sensitive, confident}` 的短 prompt），
  > **不看檔名、無關鍵字表**。`RuleGate`／`SENSITIVE_KEYWORDS`／`filename_stem` 已否決，不要復活。
- **Phase 76（入庫任務拆成看圖與落庫）** —— `build_context()` 吃的是 Phase 76 做出來的
  `PromptContext`（`folders`／`entities`／`corrections`／`inbox_name` 四個欄位的 dataclass）。
  沒有它，本 phase 的 `build_context` 與它的兩顆測試寫不出來。
  > 📌 總覽 §2.2 的「依賴」欄與 §2.3 的順序圖都寫成「74 ＋ 76 → 77」，與本節一致：**74 與 76 都要先做完**。
- Phase 75 做了沒有都不影響本 phase（它加長 `privacy_gate.py`／`ai_timing.py`，
  並把 `dependencies.get_privacy_gate()` 的**本體**換成 `VlmGate(OllamaPrivacyModel())`
  ——都不動本 phase 要改的那幾行）。
  > ⚠️ **74 與 75 都不加任何 `config.py` 變數**（改判後 `PRIVACY_GATE_LOCAL_MODEL`／`PRIVACY_MODEL`
  > 已否決，模型名就是既有的 `VLM_MODEL`／`OLLAMA_CLOUD_VLM_MODEL`）。
  > 所以**本 phase 是增量六第一次動 `app/core/config.py`**——步驟 5 貼的那九行是這個檔的第一批新設定。

**★G1 還沒到**：本 phase 全程**零 AWS**——不開帳號、不裝 boto3、不打任何 `aws` 指令。
（design6 §0 禁止第 1 條：甲還沒綠就開 S3／SQS／EC2。★G1 在 Phase 81 之後。）

開工前**實查**基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 四個容器活著嗎？db 與 redis 要是 Up (healthy)
docker compose ps --no-trunc

# ② 顆數基線（總覽 §9：543 ＋ 74 的 11 ＋ 75 的 10 ＋ 76 的 4 ＝ 568）
pytest -q

# ③ 工作樹快照（本次全程不 commit，git 驗收改用「快照相減」）
#    這支腳本只在物件庫多印一顆 tree SHA，不碰 index、不建 commit、不動 stash
.superpowers/sdd/phase0901/snapshot-tree > /tmp/p77-before-tree.txt
cat /tmp/p77-before-tree.txt
```

②的最後一行預期是：`568 passed`，而且 **0 skipped**。
**以你當下實查到的數字為準**，本文件之後一律稱它「**開工基線**」。
③印出來的那串 40 位十六進位數字之後在步驟 12 與 §6 要用（`git diff <開工前> <做完後>`）。

再確認兩個前置真的在（不在就先回去做 74／76，不要在這裡自己補一個）：

```bash
python -c "
from app.services.privacy_gate import Verdict
from app.services.ingest_job import PromptContext, load_prompt_context
print('Verdict OK：', [v.value for v in Verdict])
print('PromptContext OK：', PromptContext.__dataclass_fields__.keys())
"
```

預期輸出：

```text
Verdict OK： ['SENSITIVE', 'NON_SENSITIVE', 'UNCERTAIN']
PromptContext OK： dict_keys(['folders', 'entities', 'corrections', 'inbox_name'])
```

> ⚠️ **絕對不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。
> `reset_tables` 每顆測試都會 TRUNCATE 同一個測試庫，兩份同時跑會互相清掉對方的資料，
> 症狀是「大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`」，
> 而且每次紅的顆數都不一樣——看起來像程式壞了，其實只是撞在一起。

---

## 3. 範圍

### 做

1. **`app/core/config.py`** 加**九個**新設定（值都是預設，一個真值都不寫進版控）：
   `CLOUD_ROUTE`／`AWS_REGION`／`S3_BUCKET`／`SQS_JOBS_QUEUE_URL`／`SQS_RESULTS_QUEUE_URL`／
   `EC2_WORKER_INSTANCE_ID`／`EC2_PROBE_TTL_SECONDS`／`CLOUD_RESULT_TIMEOUT_SECONDS`／`WORKER_VERSION`，
   外加一段註解說明 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY`／`AWS_ENDPOINT_URL`
   這三個**刻意不在 config 讀**（boto3 自己會去環境變數撈）。
2. **`app/services/ingest_job_store.py`**：`IngestJob` 加 `privacy`／`route` 兩個可選欄位
   （`JOB_STATUSES` 一個字不動、兩個實作的 `create()` 一個字不動）。
3. **新建 `app/services/cloud_ingest.py`**：`MailboxMessage`、`CloudMailbox` Protocol、
   `RemoteProbe` Protocol、`AlwaysRunning`、`CloudRouteOff`、`build_context()`。
4. **`app/dependencies.py`** 加注入點 `get_cloud_route()`（此時**只認 `off`**）。
5. **`tests/fakes.py`** 加四顆假件：`FakeMailbox`、`FakeProbe`、`ScriptedProbe`、`FakeCloudRoute`。
6. **`tests/conftest.py`** 加**第五道 autouse 安全網 `wire_fake_cloud`**。
7. **新建 `tests/unit/test_cloud_ingest_unit.py`**（11 顆）＋
   **`tests/unit/test_ingest_job_store_unit.py`** 追加 1 顆。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 裝 `boto3`、寫 `app/services/aws_mailbox.py` | 那是 **Phase 83**。而且 ★G1 之前一行 AWS 指令都不准打（design6 §0 禁止第 1 條）。本 phase 的假信箱已經足夠讓 78〜81 全部寫完 |
| 寫 `CloudRoute` 的本體（`submit`／`fetch_result`／`wait_result`／`cleanup`） | 那是 **Phase 79**（單圖）與 **80**（逾時與冪等）。本 phase 只做「關掉時的替身」 |
| 寫 `Ec2Probe` | 那是 **Phase 89**。本 phase 只做 `RemoteProbe` 這份契約與 `AlwaysRunning` |
| 讓 `get_cloud_route()` 在 `assume`／`ec2` 時回一個「暫時可用的東西」 | **不留過渡產物**（產品負責人的硬要求）。那兩個值先明確 `raise NotImplementedError`，Phase 86／89 各自換掉一半——寧可大聲壞，不要安靜地走錯路 |
| 把閘門接上 Celery（改 `celery_app.py`） | 那是 **Phase 78**。本 phase 做完，`ingest_task` 一個字都沒改 |
| 新增端點（例如「遠端開著嗎」的除錯端點） | design6 §5 明文：本增量**不新增任何 REST 端點**，端點恆為 **22** |
| 在 `photo` 表加 `route`／`privacy` 欄 | design6 §4 明文：狀態放 **JobStore**。design5 的 `test_photo表沒有處理狀態欄也沒有job_id欄` 仍然有效 |
| 把 `route` 放進 `GET /ingest-jobs` 的回應 | 使用者不需要知道這張是雲端跑的（總覽 §2.4.4）。`IngestJobOut` 是逐欄挑的，不會自己多出來——本 phase 不碰它 |
| 加第五種 job 狀態（例如 `waiting_cloud`） | `JOB_STATUSES` 仍是四個（總覽 §10.2 追認項 D）。多一種狀態，前端的進度面板就會少畫一種，而 design6 §3 明文「前端不新增」 |
| 幫 `FakeMailbox` 做「訊息順序隨機」「重複投遞」的模擬 | 冪等的測試用**明確地再送一次**來寫（Phase 80），比亂數可靠得多。假件要可預測 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並且**真的跑它、親眼看到紅**；
> 步驟 3〜7 才動實作讓它轉綠。「跑它確認紅」不可以跳過——沒看過紅的測試，
> 你不知道它有沒有在測東西。

### - [x] 步驟 1：先寫測試（紅）——新建 `tests/unit/test_cloud_ingest_unit.py`

整份貼上：

```python
"""cloud_ingest 的單元測試：純記憶體，不碰資料庫、不碰網路、**不碰 AWS**。

本檔測的是 Phase 77 的「契約層」：
  - CloudRouteOff：雲端路關掉時的替身（正式路徑目前拿到的就是它）
  - AlwaysRunning：CLOUD_ROUTE=assume 用的探測
  - build_context：要放進 S3 的 context.json 內容
  - FakeMailbox：一顆假件同時扮演 S3 ＋ 兩條佇列（78〜81、87、89 全靠它）
  - 第五道 autouse 安全網 wire_fake_cloud 本身

Phase 79／80 會在本檔追加 CloudRoute 本體的測試；Phase 89 追加 Ec2Probe 的。
"""

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
    CloudRouteOff,
    build_context,
)
from app.services.ingest_job import PromptContext
from tests.fakes import FakeMailbox


def 樣本清單() -> PromptContext:
    """一份長得像真的的 PromptContext（Phase 76 的積木回傳的東西）。

    刻意放中文與 None：中文要驗「序列化之後還是中文」（ensure_ascii=False 有生效），
    None 要驗序列化不會炸。
    """
    return PromptContext(
        folders=[
            {
                "id": 1,
                "name": "未分類",
                "description": "收件箱",
                "is_inbox": True,
                "photo_count": 3,
            },
            {
                "id": 2,
                "name": "收據",
                "description": "買東西的憑證",
                "is_inbox": False,
                "photo_count": 0,
            },
        ],
        entities=[{"id": 7, "name": "我的 MacBook", "description": None}],
        corrections=[
            {"suggested": "飲食", "chosen": "收據", "photo_text": "在 Target 買可樂"},
        ],
        inbox_name="未分類",
    )


# ---------------------------- ① 雲端路關掉時的替身 ----------------------------


def test_CloudRouteOff的available恆為False():
    """CLOUD_ROUTE=off 時正式路徑拿到的就是它：永遠說「遠端不可用」。

    這一顆是整個增量六的保險絲：只要它是綠的，`run_gated_ingest_job` 就永遠
    走 fallback（＝增量五那條路），一個位元組都不會出這台機器。
    """
    路線 = CloudRouteOff()

    assert 路線.available() is False
    assert 路線.available() is False  # 問幾次都一樣，沒有「第一次是 True」這種事


def test_CloudRouteOff其餘方法一律raise():
    """關掉的路被拿去送東西＝有人接線接錯了，要大聲壞掉，不要安靜地什麼都不做。

    安靜回 None 的話，Phase 79 之後若有人忘了檢查 available()，
    症狀會變成「照片莫名其妙沒有入庫、也沒有錯誤訊息」——最難查的一種。
    """
    路線 = CloudRouteOff()

    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        路線.submit("job-1", content_type="image/png", file_bytes=b"", context={})
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        路線.fetch_result("job-1")
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        路線.wait_result("job-1", store=None)
    with pytest.raises(RuntimeError, match=ROUTE_OFF_MESSAGE):
        路線.cleanup("job-1")


def test_AlwaysRunning恆為True():
    """CLOUD_ROUTE=assume 用的探測：不問 AWS，直接說「開著」（總覽 §10 追認項 l）。

    它只給階段丁（工人跑在這台 Mac 上）與除錯用；戊之後日常一律用 Ec2Probe（Phase 89）。
    """
    探測 = AlwaysRunning()

    assert 探測.is_running() is True
    assert 探測.is_running() is True


# ---------------------------- ② context.json 的內容 ----------------------------


def test_build_context恰三鍵而且可以json序列化():
    """工人靠這包東西組出**同一份** build_vlm_prompt（總覽 §10 追認項 a）。

    三鍵不多不少：多了工人不看、少了工人就少一段 prompt。
    inbox_name **刻意不進去**——收件箱名稱是本機落庫時才要用的東西，工人用不到。
    """
    包裹 = build_context(樣本清單())

    assert set(包裹) == {"folders", "entities", "corrections"}
    assert 包裹["folders"][0]["name"] == "未分類"
    assert 包裹["entities"][0]["name"] == "我的 MacBook"
    assert 包裹["corrections"][0]["chosen"] == "收據"

    # 這一行就是 CloudRoute.submit 真的會做的事（Phase 79）：中文原樣留著
    # （ensure_ascii=False），日期之類不能直接序列化的東西交給 default=str 處理
    文字 = json.dumps(包裹, ensure_ascii=False, default=str)
    assert "我的 MacBook" in 文字
    assert json.loads(文字) == 包裹


def test_build_context不含任何位元組():
    """design6 §0 禁止第 2 條的延伸：要送出去的東西**只有字串**，沒有影像。

    這包東西會被 json.dumps 成字串再 PutObject；夾帶一個 bytes 進去會當場炸，
    但更糟的是有人「順手把縮圖 base64 一下放進來」——那就變成偷偷把影像
    塞進本來只該放清單的地方。這顆測試遞迴地把每個角落都翻過一遍。
    """
    包裹 = build_context(樣本清單())

    def 翻一遍(值) -> None:
        assert not isinstance(值, (bytes, bytearray)), f"context 裡不可以有位元組：{值!r}"
        if isinstance(值, dict):
            for 鍵, 子值 in 值.items():
                assert not isinstance(鍵, (bytes, bytearray))
                翻一遍(子值)
        elif isinstance(值, (list, tuple)):
            for 子值 in 值:
                翻一遍(子值)

    翻一遍(包裹)

    # 順帶驗「回的是複本」：改它不可以動到 repository 給的那份原始清單
    原始 = 樣本清單()
    包裹2 = build_context(原始)
    包裹2["folders"][0]["name"] = "被改掉了"
    assert 原始.folders[0]["name"] == "未分類"


# ---------------------------- ③ 假信箱：S3 那一半 ----------------------------


def test_FakeMailbox的put與get與delete物件行為():
    """假信箱的 S3 那一半：放得進去、拿得回來、刪得掉、拿不到時回 None。

    「拿不到回 None（不是丟例外）」是契約的一部分（Phase 83 的 AwsMailbox
    也要把 NoSuchKey 翻成 None）——`fetch_result` 靠它分辨「結果還沒寫好」。
    """
    信箱 = FakeMailbox()
    鍵 = 信箱.input_key("job-1", "image/png")

    assert 鍵 == "documents/job-1/input.png"
    assert 信箱.input_key("job-1", "image/jpeg") == "documents/job-1/input.jpg"
    assert 信箱.input_key("job-1", "application/pdf") == "documents/job-1/input.pdf"
    assert 信箱.context_key("job-1") == "documents/job-1/context.json"
    assert 信箱.result_key("job-1") == "documents/job-1/result.json"

    assert 信箱.get_object(鍵) is None
    信箱.put_object(鍵, b"PNG-DATA", "image/png")
    assert 信箱.get_object(鍵) == b"PNG-DATA"
    assert 信箱.put_calls == 1
    assert 信箱.get_calls == 2

    信箱.delete_objects([鍵, "documents/job-1/根本沒有這個"])
    assert 信箱.objects == {}
    assert 信箱.delete_calls == 1


def test_FakeMailbox的jobs佇列send後receive再delete():
    """jobs 佇列：本機 Send、工人 Receive／Delete（design6 §2.3）。

    body 恰兩鍵、而且**沒有位元組**——這是 §0 禁止第 2 條在假件層的第一道把關。
    """
    信箱 = FakeMailbox()
    信箱.send_job("job-1", "documents/job-1/input.jpg")

    assert 信箱.send_job_calls == 1
    assert 信箱.jobs == [{"job_id": "job-1", "s3_key": "documents/job-1/input.jpg"}]

    訊息 = 信箱.receive_job(wait_seconds=20)
    assert 訊息 is not None
    assert 訊息.job_id == "job-1"
    assert 訊息.s3_key == "documents/job-1/input.jpg"
    assert 訊息.receipt_handle, "沒有把手就刪不掉這則訊息"
    assert 信箱.jobs == [], "收走之後別人就看不到了（模仿 SQS 的可見度逾時）"

    信箱.delete_job_message(訊息.receipt_handle)
    assert 信箱.receive_job(wait_seconds=0) is None
    assert 信箱.wait_seconds_log == [20, 0], "每次 receive 等幾秒都記下來，給 Phase 80 驗"
    assert 信箱.calls == [
        "send_job job-1",
        "receive_job",
        "delete_job_message",
        "receive_job",
    ], "呼叫流水帳要照順序記下來（Phase 79／87 靠它釘 D9 的順序鐵律）"


def test_FakeMailbox的results佇列release之後可以再收到():
    """release ＝ ChangeMessageVisibility 改成 0 ＝「我拿錯了，立刻還回去」。

    Phase 80 的 wait_result 收到**別人的**結果訊息時就是這樣處理的：
    還回佇列，讓它真正的主人收得到（總覽 §2.5 第 3 條）。
    """
    信箱 = FakeMailbox()
    信箱.send_result("別人的job")

    第一次 = 信箱.receive_result(wait_seconds=20)
    assert 第一次 is not None
    assert 第一次.job_id == "別人的job"
    assert 第一次.s3_key is None, "results 的 body 只有 job_id（design6 §2.3）"

    信箱.release_result_message(第一次.receipt_handle)
    第二次 = 信箱.receive_result(wait_seconds=20)
    assert 第二次 is not None
    assert 第二次.job_id == "別人的job"
    assert 第二次.receipt_handle != 第一次.receipt_handle, "把手每次都不一樣（與真 SQS 同）"

    信箱.delete_result_message(第二次.receipt_handle)
    assert 信箱.receive_result(wait_seconds=0) is None


def test_FakeMailbox佇列空的時候receive回None():
    """空佇列回 None，不是丟例外——真 SQS 長輪詢到時間也是回一份空清單。

    順帶驗 instance_state 的劇本（Phase 89 的 Ec2Probe 要用它數 DescribeInstances
    被叫了幾次）：依序回傳，用完之後重複最後一個。
    """
    信箱 = FakeMailbox()

    assert 信箱.receive_job(wait_seconds=20) is None
    assert 信箱.receive_result(wait_seconds=20) is None

    assert 信箱.instance_state("i-0000") == "running", "預設劇本就是 running"
    信箱.instance_state_script = ["stopped", "running"]
    assert 信箱.instance_state("i-0000") == "stopped"
    assert 信箱.instance_state("i-0000") == "running"
    assert 信箱.instance_state("i-0000") == "running", "劇本演完就重複最後一個"
    assert 信箱.instance_state_calls == 4


# ---------------------------- ④ 注入點與第五道安全網 ----------------------------


def test_get_cloud_route預設off時回CloudRouteOff(monkeypatch):
    """CLOUD_ROUTE=off ＝ 不走雲端。這是 pytest 與新 clone 的預設值。

    ★ 這裡呼叫的是**原本那一支**：檔頭的 `from app.dependencies import get_cloud_route`
      在 pytest 收集階段就把函式物件綁進本檔的名字了，第五道安全網之後對
      `dependencies` 模組屬性做的 monkeypatch 換不掉它——這正是我們要的
      （本顆要測的是真的那一支，不是安全網換上去的替身）。
    """
    assert config.CLOUD_ROUTE == "off", "第五道安全網應該已經把它蓋成 off"
    assert isinstance(get_cloud_route(), CloudRouteOff)

    # assume／ec2 現在還沒接（總覽 §2.7：本增量**唯二**允許的暫時分支之一）。
    # ⚠ 這兩行是**鬧鐘**：
    #     Phase 86 接上 assume 時 → **拆掉 assume 那半**（改成驗它建出 CloudRoute）
    #     Phase 89 接上 ec2 時   → **拆掉 ec2 那半**（改成驗它的探測是 Ec2Probe）
    #   兩個 phase 各自的測試檔（test_dependencies_cloud_unit.py）會接手那一半的驗證。
    for 模式 in ("assume", "ec2"):
        monkeypatch.setattr(config, "CLOUD_ROUTE", 模式)
        with pytest.raises(NotImplementedError):
            get_cloud_route()

    # 打錯字要當場炸，不要默默當成 off——「我明明開了雲端路怎麼都沒送出去」是最難查的
    monkeypatch.setattr(config, "CLOUD_ROUTE", "cloudy")
    with pytest.raises(ValueError):
        get_cloud_route()


def test_第五道安全網把CLOUD_ROUTE蓋成off且AWS_ENDPOINT_URL是死埠():
    """安全網本身也要有測試（比照第四道的 test_安全網已把注入點換成每測獨立的記憶體store）。

    ★ 這一顆**刻意不把 fixture 寫進參數列**：pytest 對「參數列有請求的 fixture」
      無論 autouse 與否都會啟動它，寫了參數列就驗不到 autouse 本身——
      就算有人把 autouse=True 拿掉，這顆照樣綠，形同沒驗。
    """
    assert config.CLOUD_ROUTE == "off"
    assert os.environ["AWS_ENDPOINT_URL"] == "http://127.0.0.1:9", (
        "死埠是最後一道保險：就算有人漏接假件，boto3 也只會立刻 connection refused"
    )

    # 兩條呼叫路都要被換掉（缺一條就是「單跑綠、整包跑紅」的溫床）
    assert get_cloud_route in app.dependency_overrides  # ① Depends() 那條
    assert dependencies.get_cloud_route is not get_cloud_route  # ② 直接呼叫那條
    路線 = dependencies.get_cloud_route()
    assert isinstance(路線, CloudRouteOff)
    assert app.dependency_overrides[get_cloud_route]() is 路線, "兩條路要拿到同一顆"
```

### - [x] 步驟 2：測試（紅）——`tests/unit/test_ingest_job_store_unit.py` 追加 1 顆

在**檔案最後面**（Phase 65 追加的 `RedisJobStore` 那一段之後）加上：

```python


# ---------- 增量六 Phase 77 追加：兩個新欄位 ----------


def test_job可以存取privacy與route兩個新欄位():
    """IngestJob 多兩個**可選**欄位（design6 §4、總覽 §2.4.4）。

      privacy ＝ 隱私閘門判的三分類（SENSITIVE／NON_SENSITIVE／UNCERTAIN）
      route   ＝ 這筆最後走哪條路（local／cloud）

    兩個都**不進 photo 表**（design6 §4 明文：狀態放 JobStore），
    也**不進 GET /ingest-jobs 的回應**（IngestJobOut 是逐欄挑的，使用者看不到 route）。

    為什麼是「可選」而不是在 create() 就填：剛收下檔案的那一刻還沒有人問過閘門，
    填一個假的預設值（例如 route="local"）會讓「還沒判斷」與「判斷結果是本機」
    長得一模一樣——而 Phase 78 的崩潰重送**正是靠這個差別**決定要不要再問一次閘門。
    """
    store = _new_store()
    job = _create(store)

    assert "privacy" not in job, "剛建立時還沒判斷過，這個鍵不該存在"
    assert "route" not in job

    store.update("job-1", privacy="SENSITIVE", route="local")

    改完 = store.get("job-1")
    assert 改完["privacy"] == "SENSITIVE"
    assert 改完["route"] == "local"
    assert 改完["status"] == "queued", "update 只改指定的欄位，其他一個都不動"
    assert 改完["photo_ids"] == []
```

### - [x] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py -q
```

預期：**收集階段就失敗**，錯誤長這樣（模組還不存在）：

```text
ImportError while importing test module '.../tests/unit/test_cloud_ingest_unit.py'.
...
ModuleNotFoundError: No module named 'app.services.cloud_ingest'
```

另一顆：

```bash
pytest tests/unit/test_ingest_job_store_unit.py::test_job可以存取privacy與route兩個新欄位 -q
```

預期：**綠的**（`1 passed`）。這是**正常**的——`IngestJob` 是 `TypedDict`，
執行時就是普通的 `dict`，多塞兩個鍵本來就不會爆。
所以這一顆的價值不在「現在會紅」，而在「**把契約寫進測試**」：
日後有人把 `update()` 改成「只接受白名單欄位」時，它會第一個紅。
（步驟 4 仍然要真的去 `IngestJob` 補上那兩行型別註記——不補的話編輯器與讀者不知道有這兩個欄位。）

### - [x] 步驟 4：綠（1／5）——`app/services/ingest_job_store.py` 加兩個欄位

在 `class IngestJob(TypedDict, total=False):` 的**最後一個欄位** `source: str` 那一行的**下面**加：

```python
    # ---- 增量六 Phase 77 追加（design6.md §4；總覽 §2.4.4）----
    # 兩個都**可選**：剛收下檔案時還沒有人問過閘門，所以這兩個鍵根本不存在。
    # 「鍵不存在」與「值是 local」是**兩件不同的事**——Phase 78 的崩潰重送
    # 就是靠這個差別決定「要不要再問一次閘門」（design6 §2.1 禁止 fallback 時重跑分類器）。
    privacy: str  # 隱私閘門的三分類："SENSITIVE" / "NON_SENSITIVE" / "UNCERTAIN"
    route: str  # 這筆走哪條路："local"（增量五那條）/ "cloud"
```

⚠️ **只加這兩行註記，其餘一個字都不要動**：`JOB_STATUSES` 仍是四個
（**不新增** `waiting_cloud` 之類的狀態，總覽 §10.2 追認項 D）；
`InMemoryJobStore.create()` 與 `RedisJobStore.create()` 的初始欄位也一個都不加
（加了就等於「還沒判斷」被寫成「已判斷成 local」）。

### - [x] 步驟 5：綠（2／5）——`app/core/config.py` 加九個設定

在檔案**最後面**（既有的 `SEARCH_MODE_LABELS = { … }` 那一段之後，也就是目前 `config.py`
的最後一行之後——74／75 一個變數都沒加，所以檔尾就是它）整段貼上：

```python

# --- 增量六：雲端路（design6.md D7〜D10、D15；總覽 §2.4.2）-------------------
# ★ 這一整段只有「名字」與「預設值」，**一個真實的值都不寫進版控**：
#   bucket 名、佇列 URL、實例 id 一律放 .env（.env 不入版控）。

# 雲端路的總開關。只認三種值（dependencies.get_cloud_route() 會擋掉別的）：
#   off    ＝ 完全不走雲端。**pytest 與新 clone 的預設**，行為與增量五逐字相同
#   assume ＝ 假設遠端開著（階段丁：工人跑在這台 Mac 上時用；Phase 86 接）
#   ec2    ＝ 每次送出前用 DescribeInstances 問一下那台機器開著沒（Phase 89 接）
CLOUD_ROUTE = os.getenv("CLOUD_ROUTE", "off")

# AWS 區域：東京（design6 §7）。boto3 的 client 一律**明傳** region_name=config.AWS_REGION，
# 不靠 ~/.aws/config——那個檔不入版控，換一台機器就會變成「在別的區域找不到 bucket」。
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")

# ★ AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY／AWS_ENDPOINT_URL 這三個**刻意不在這裡讀**：
#   它們是 boto3 自己認得的標準環境變數，建 client 時 boto3 會直接去環境裡撈。
#   config 再抄一份副本只會多一個會漂移的地方，而且金鑰一旦變成 Python 變數，
#   任何一次 print(vars(config)) 都會把它印出來。
#   EC2 上完全不放金鑰——那台機器用 instance role 拿臨時憑證（design6 §6）。

# 寄物櫃 bucket 名（Phase 84 建好之後填進 .env）
S3_BUCKET = os.getenv("S3_BUCKET", "")

# 兩條 SQS 佇列的網址（Phase 85 建好之後填進 .env）
SQS_JOBS_QUEUE_URL = os.getenv("SQS_JOBS_QUEUE_URL", "")
SQS_RESULTS_QUEUE_URL = os.getenv("SQS_RESULTS_QUEUE_URL", "")

# CLOUD_ROUTE=ec2 時要探測哪一台（Phase 92 開好實例之後填進 .env）
EC2_WORKER_INSTANCE_ID = os.getenv("EC2_WORKER_INSTANCE_ID", "")

# DescribeInstances 的答案快取幾秒（design6 §2.1 第 1 條「快取可短 TTL」）。
# 不快取的話每一張照片都要打一次 AWS API：慢，而且是可以省下來的錢。
EC2_PROBE_TTL_SECONDS = int(os.getenv("EC2_PROBE_TTL_SECONDS", "60"))

# 送出之後最多等 results 佇列幾秒；到了還沒有結果就 fallback 本機（design6 D10）。
# 300 秒 ＝ 5 分鐘：雲端看一張圖約 2 秒，這個值留的是「工人剛好在忙別的檔」的餘裕。
# 手動煙霧時在 .env 調小比較不必空等（Phase 86 用 30 秒）。
CLOUD_RESULT_TIMEOUT_SECONDS = int(os.getenv("CLOUD_RESULT_TIMEOUT_SECONDS", "300"))

# 雲端工人映像的版本：build 時由 Dockerfile 的 ARG GIT_SHA 烙進去（Phase 90）。
# 只有 app/workers/cloud_worker.py 讀它，啟動時印在 log 第一行——
# Demo 3 就是靠這個字串證明「EC2 上跑的真的是剛剛推上去的那一版」（design6 D16）。
WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")
```

⚠️ **74／75 沒有在 `config.py` 加任何變數**（2026-09-01 改判後，隱私閘門用的就是既有的
`VLM_MODEL`／`OLLAMA_CLOUD_VLM_MODEL`，沒有 `PRIVACY_GATE_LOCAL_MODEL`、沒有 `PRIVACY_MODEL`）。
所以**這一段是增量六第一次動這個檔**。貼完先確認自己貼在對的位置、而且沒有貼重複：

```bash
grep -n "^SEARCH_MODE_LABELS\|^CLOUD_ROUTE\|^WORKER_VERSION" app/core/config.py
```

預期：三行命中，而且 `SEARCH_MODE_LABELS` 的行號**最小**（＝新設定確實接在它後面）。

### - [x] 步驟 6：綠（3／5）——新建 `app/services/cloud_ingest.py`

整份貼上：

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

【Phase 77 只做契約】
本 phase 落地的是：MailboxMessage、兩份 Protocol、AlwaysRunning、CloudRouteOff
（雲端路關掉時的替身）與 build_context()。
真的會把東西送出去的 CloudRoute 在 Phase 79（單圖）與 80（逾時與冪等）；
Ec2Probe 在 Phase 89。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

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

### - [x] 步驟 7：綠（4／5）——`app/dependencies.py` 加注入點

- [x] 把檔頭的 `from app.services import (...)` 那一段補上 `cloud_ingest`（**照字母順序**插進去，
  ruff 的 import 排序才不會抓）：

```python
from app.services import (
    ask_workflow,
    cloud_ingest,
    entity_suggestion_service,
    indexing_service,
    ingest_job_store,
    privacy_gate,
    vlm_service,
)
```

> （`privacy_gate` 是 Phase 74 加的，要留著。）**照字母順序**擺就對了；
> 擺錯的話 `ruff check` 會報 `I001`（跑 `ruff check --fix` 可自動修好）。

- [x] 在檔案**最後面**（`get_task_dispatcher()` 之後）加上：

```python


# ---------------- 增量六 Phase 77：雲端路的注入點（design6 D7／D10）----------------


def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    """這一台現在要不要走雲端路、怎麼走。**全系統只有這一個地方決定。**

    三種模式（config.CLOUD_ROUTE，預設 off）：
      off    → CloudRouteOff()：available() 恆為 False，行為與增量五**逐字相同**
      assume → Phase 86 才接（CloudRoute ＋ AwsMailbox ＋ AlwaysRunning）
      ec2    → Phase 89 才接（探測換成 Ec2Probe）

    ★ 打錯字要當場炸（ValueError），不要默默當成 off：
      「我明明把 CLOUD_ROUTE 設成 cloud 了，怎麼都沒送出去」是最難查的一種壞法。

    ★ 回傳型別註記裡的 cloud_ingest.CloudRoute 要 Phase 79 才存在。本檔最上面有
      `from __future__ import annotations`，所以註記只是**字串**、執行時不會被求值，
      現在寫上去不會炸——這樣 79 補完之後這一行不必再動。
      （前提：這一支**不可以**被寫成 Depends(get_cloud_route) 塞進 router，
      那會讓 FastAPI 真的去解析型別。本增量不新增端點，也不需要。）

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    模式 = config.CLOUD_ROUTE
    if 模式 == "off":
        return cloud_ingest.CloudRouteOff()
    if 模式 == "assume":
        raise NotImplementedError("CLOUD_ROUTE=assume 要等 Phase 86 接上真 AWS 才能用")
    if 模式 == "ec2":
        raise NotImplementedError("CLOUD_ROUTE=ec2 要等 Phase 89 的 Ec2Probe 才能用")
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{模式!r}")
```

### - [x] 步驟 8：綠（5／5 之一）——`tests/fakes.py` 加四顆假件

- [x] 檔頭 import 區的 `from app...` 那幾行，照字母順序**插入兩行**
  （`cloud_ingest` 排在 `ask_workflow` 之後；`staging_service` 排在 Phase 74 加的 `privacy_gate` 之後、
  `vlm_service` 之前）。⚠ 兩行**不是**相鄰的，改完整段長這樣：

```python
from app.core import config
from app.services.ask_workflow import RouteDecision
from app.services.cloud_ingest import MailboxMessage
from app.services.privacy_gate import Verdict
from app.services.staging_service import STAGING_EXTENSIONS
from app.services.vlm_service import PhotoUnderstanding
```

- [x] 在檔案**最後面**整段貼上：

```python


# ---------- 增量六 Phase 77：雲端路的假件 ----------
#
# 這一區的四顆假件是 Phase 78〜81（本機端流程）、87（工人）、89（EC2 探測）
# 全部測試的地基。它們**沒有一行 boto3**，也不連任何網路——
# 「pytest 絕不連真 AWS」（design6 §9）的實際做法就是這裡。

# S3 上寄物櫃的前綴（design6 §2.2 的鍵名契約）。
# 副檔名借用 staging 那一張表（同樣是那三種格式）：兩份一定會漂移，
# 而鍵名是**跨機器**的契約——本機寫的名字，EC2 上的工人要拿得到。
S3_PREFIX = "documents"


class FakeMailbox:
    """一顆假件同時扮演 S3 寄物櫃與兩條 SQS 佇列（總覽 §2.4.5）。

    為什麼三個角色合成一顆：一次雲端往返會同時碰到三者（Put 物件 → 發 jobs 訊息 →
    工人 Get 物件 → Put 結果 → 發 results 訊息 → 本機 Get 結果），
    拆成三顆假件的話，每個測試都要自己把三顆接起來，而且很容易接錯。
    合成一顆之後，Phase 87 的端到端測試可以直接寫成
    「本機送出 → 假工人處理**同一顆信箱** → 本機收回入庫」。

    它模仿的 SQS 行為（只模仿真的會影響正確性的那幾件）：
      * receive 會把訊息**從佇列拿走**（模仿可見度逾時：別人暫時看不到它）
      * delete 要帶 receipt handle（把手不對＝當場 AssertionError，比默默成功好）
      * release 把訊息放回**佇列前端**（模仿 ChangeMessageVisibility 改成 0）
      * 佇列空的時候 receive 回 None（真 SQS 長輪詢到時間也是回空的）
      * **不模仿**：亂序、重複投遞、可見度會自己過期。冪等要用「明確地再送一次」
        來測（Phase 80），比亂數可靠得多——假件要可預測。

    計數器與流水帳（測試靠它們斷言「有沒有真的送出去」「先後順序對不對」）：
      calls                                         **呼叫流水帳**：每被叫一次就記一行
                                                    （例如 "put_object documents/x/input.png"）。
                                                    整數計數器驗得出「幾次」，驗不出「誰先誰後」
                                                    ——D9 的順序鐵律只能靠這一份清單釘（總覽 §2.4.5）
      put_calls / get_calls / delete_calls          S3 三種操作各幾次
      send_job_calls / send_result_calls            兩條佇列各發了幾則
      wait_seconds_log                              每次 receive 說要等幾秒（Phase 80 驗 <= 20）
      instance_state_calls                          DescribeInstances 被叫幾次（Phase 89 驗快取）
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.jobs: list[dict] = []
        self.results: list[dict] = []
        self.calls: list[str] = []
        self.put_calls = 0
        self.get_calls = 0
        self.delete_calls = 0
        self.send_job_calls = 0
        self.send_result_calls = 0
        self.wait_seconds_log: list[int] = []
        # instance_state() 依序回傳這個清單，用完之後重複最後一個。
        # 預設「開著」＝ 大部分測試不必管它；要測「關機了」就把它換掉。
        self.instance_state_script: list[str] = ["running"]
        self.instance_state_calls = 0
        self._handle_seq = 0
        self._in_flight: dict[str, tuple[list[dict], dict]] = {}

    # ---------- 鍵名（design6 §2.2 的契約；Phase 83 的 AwsMailbox 要逐字相同）----------

    def input_key(self, job_id: str, content_type: str) -> str:
        return f"{S3_PREFIX}/{job_id}/input{STAGING_EXTENSIONS[content_type]}"

    def context_key(self, job_id: str) -> str:
        return f"{S3_PREFIX}/{job_id}/context.json"

    def result_key(self, job_id: str) -> str:
        return f"{S3_PREFIX}/{job_id}/result.json"

    # ---------- S3 那一半 ----------

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        assert isinstance(body, bytes), "S3 只收位元組；字串要自己先 encode"
        self.calls.append(f"put_object {key}")
        self.put_calls += 1
        self.objects[key] = body

    def get_object(self, key: str) -> bytes | None:
        """拿不到回 None（**不是**丟例外）——真的 AwsMailbox 會把 NoSuchKey 翻成 None。"""
        self.calls.append(f"get_object {key}")
        self.get_calls += 1
        return self.objects.get(key)

    def delete_objects(self, keys: list[str]) -> None:
        """盡力刪：本來就不在的鍵不算錯（真 S3 的 DeleteObjects 也是這個行為）。"""
        self.calls.append(f"delete_objects {len(keys)}")
        self.delete_calls += 1
        for key in keys:
            self.objects.pop(key, None)

    # ---------- jobs 佇列（本機 Send、工人 Receive／Delete）----------

    def send_job(self, job_id: str, s3_key: str) -> None:
        self.calls.append(f"send_job {job_id}")
        self.send_job_calls += 1
        self.jobs.append({"job_id": job_id, "s3_key": s3_key})

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None:
        self.calls.append("receive_job")
        return self._receive(self.jobs, wait_seconds)

    def delete_job_message(self, receipt_handle: str) -> None:
        self.calls.append("delete_job_message")
        self._delete_message(receipt_handle)

    # ---------- results 佇列（工人 Send、本機 Receive／Delete／Release）----------

    def send_result(self, job_id: str) -> None:
        self.calls.append(f"send_result {job_id}")
        self.send_result_calls += 1
        self.results.append({"job_id": job_id})

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None:
        self.calls.append("receive_result")
        return self._receive(self.results, wait_seconds)

    def delete_result_message(self, receipt_handle: str) -> None:
        self.calls.append("delete_result_message")
        self._delete_message(receipt_handle)

    def release_result_message(self, receipt_handle: str) -> None:
        """把手上這則訊息立刻還回佇列前端（＝ ChangeMessageVisibility 改成 0）。"""
        self.calls.append("release_result_message")
        queue, body = self._in_flight.pop(receipt_handle)
        queue.insert(0, body)

    # ---------- EC2（Phase 89 的 Ec2Probe 用）----------

    def instance_state(self, instance_id: str) -> str:
        self.calls.append(f"instance_state {instance_id}")
        self.instance_state_calls += 1
        答案 = self.instance_state_script[0]
        if len(self.instance_state_script) > 1:
            self.instance_state_script.pop(0)
        return 答案

    # ---------- 內部 ----------

    def _receive(self, queue: list[dict], wait_seconds: int) -> MailboxMessage | None:
        """從佇列前端拿一則走，發一個新的 receipt handle。**不會真的等** wait_seconds 秒。

        ⚠ 正因為它不等，「等到逾時」的測試一定要接管 cloud_ingest 的時間接縫
          _now()／_sleep()（Phase 79 才建），否則 wait_result 的迴圈會全速空轉到 deadline。
          接管用的小工具由 Phase 80 的測試檔定義：假裝過了(monkeypatch, 秒數) ＝ 一次撥到
          未來然後凍結、讓時鐘一直走(monkeypatch, 每次秒數) ＝ 每問一次就再前進。
          **本 phase 不定義任何時間 helper**——tests/fakes.py 裡沒有、也不該有它們。
        """
        self.wait_seconds_log.append(wait_seconds)
        if not queue:
            return None
        body = queue.pop(0)
        self._handle_seq += 1
        handle = f"receipt-{self._handle_seq}"
        self._in_flight[handle] = (queue, body)
        return MailboxMessage(
            job_id=body["job_id"],
            s3_key=body.get("s3_key"),
            receipt_handle=handle,
        )

    def _delete_message(self, receipt_handle: str) -> None:
        assert receipt_handle in self._in_flight, (
            f"要刪的訊息不在手上（把手 {receipt_handle!r}）——真 SQS 會安靜地不做事，"
            "所以這裡改成大聲炸掉，才抓得到「把手用錯／刪兩次」"
        )
        self._in_flight.pop(receipt_handle)


class FakeProbe:
    """假的遠端探測（總覽 §2.4.5）。

    running 給 True／False 決定答案；給一個**例外實例**就在被問時丟出來
    ——用來重現 design6 §2.1 第 2 條「沒有 AWS 憑證／API 失敗」那一種不可用。
    """

    def __init__(self, running: bool | Exception = True) -> None:
        self.running = running
        self.calls = 0

    def is_running(self) -> bool:
        self.calls += 1
        if isinstance(self.running, Exception):
            raise self.running
        return self.running


class ScriptedProbe:
    """依序回一串答案的假探測；用完之後重複最後一個（總覽 §2.4.5）。

    給 CloudRoute(信箱, probe) 的流程測試用：答案寫成 [True, False] 就能演
    「第一次可用、第二次不可用」這種劇本。
    ⚠ **不是**給 Phase 89 的 Ec2Probe 做 TTL 測試用——那組要數的是 DescribeInstances
      被叫了幾次，靠的是 FakeMailbox.instance_state_script ＋ instance_state_calls。
    """

    def __init__(self, answers: list[bool]) -> None:
        assert answers, "至少要給一個答案"
        self.answers = list(answers)
        self.calls = 0

    def is_running(self) -> bool:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


class FakeCloudRoute:
    """只回答「遠端可不可用」的假雲端路。**只給 Phase 77／78 用。**

    Phase 79 起一律改用真的 `CloudRoute(FakeMailbox(), FakeProbe(True), timeout_seconds=…)`
    ——假的路只證明得了「分支走對了」，證明不了「送出去的東西長什麼樣」
    （總覽 §2.4.5 那一列的原話）。

    available 給 True／False 決定答案；給一個**例外實例**就丟出來
    （閘門那一層必須把它當作「不可用」，不可以讓整個任務炸掉）。
    """

    def __init__(self, available: bool | Exception = True) -> None:
        self._available = available
        self.available_calls = 0
        self.submit_calls = 0
        self.cleanup_calls = 0

    def available(self) -> bool:
        self.available_calls += 1
        if isinstance(self._available, Exception):
            raise self._available
        return self._available

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        self.submit_calls += 1

    def fetch_result(self, job_id: str) -> dict | None:
        return None

    def wait_result(self, job_id: str, *, store) -> dict | None:
        return None

    def cleanup(self, job_id: str) -> None:
        self.cleanup_calls += 1
```

### - [x] 步驟 9：綠（5／5 之二）——`tests/conftest.py` 加第五道安全網

- [x] 檔頭 docstring 只動**兩處**：第一行的「四道」改「五道」、清單**最後多列一行** `wire_fake_cloud`。

  ⚠ **`wire_fake_ai` 那一行不要碰**——Phase 74 已經把它從「六個注入點」改成「七個」了，
  照它當下留下的字樣原樣保留。下面這一份是**改完之後大概長這樣**的示意（`wire_fake_ai`
  那一行以你檔案裡的實況為準，不要拿這裡的字覆蓋回去）：

```python
"""pytest 共用設定：把資料庫指到測試庫，並套上五道 autouse 安全網。

reset_tables          每測清空四張表＋重播六筆資料夾種子（絕不動正式庫）
wire_fake_ai          七個注入點全換假件＋固定時鐘（絕不打真 Ollama）
isolated_data_dir     DATA_DIR 指到 tmp_path（絕不寫專案的 data/）
wire_memory_job_store JobStore 指到每測獨立的記憶體實作（Depends 與直接
                      呼叫兩條路都攔；絕不連真 Redis）
wire_fake_cloud       雲端路一律關掉、AWS_ENDPOINT_URL 指死埠（絕不連真 AWS）
"""
```

- [x] `from app.dependencies import (...)` 那一段補上 `get_cloud_route`（照字母順序，
  放在 `get_answerer` 之後）。

- [x] `from app.main import app` 的下一行加上：

```python
from app.services.cloud_ingest import CloudRouteOff  # noqa: E402
```

- [x] 在 `wire_memory_job_store` 這個 fixture 的**後面**加上：

```python


@pytest.fixture(autouse=True)
def wire_fake_cloud(monkeypatch):
    """第五道安全網（Phase 77）：雲端路一律關著，而且就算漏接也連不出去。

    pytest **絕不連真 AWS**（design6 §9、總覽 §7 鐵律 2）。三件事缺一不可：

    ① config.CLOUD_ROUTE 蓋成 "off"
       ——.env 裡萬一寫了 assume／ec2（手動煙霧完忘了改回來），測試也不受影響。
    ② get_cloud_route 兩條呼叫路都換成同一顆 CloudRouteOff()：
       Depends() 那條靠 dependency_overrides、**直接呼叫**那條靠 monkeypatch。
       Celery 的 ingest_task（Phase 78 起）走的正是直接呼叫那條，
       只做前者的話它會拿到真的那一支（理由與第四道完全相同，見 Phase 57 陷阱 7）。
    ③ AWS_ENDPOINT_URL 指到死埠 http://127.0.0.1:9：
       萬一日後真的有人建了 boto3 client，它也只會**立刻** connection refused，
       絕不會真的把位元組送出這台機器。埠 9 是網路標準保留的 discard 埠，
       本機一定沒有程式在聽，所以是「立刻拒絕」而不是「卡住等逾時」。

    回傳那顆 CloudRouteOff，需要斷言「有沒有被拿去用」的測試可以寫進參數列。
    """
    monkeypatch.setattr(config, "CLOUD_ROUTE", "off")
    路線 = CloudRouteOff()
    app.dependency_overrides[get_cloud_route] = lambda: 路線
    monkeypatch.setattr(dependencies, "get_cloud_route", lambda: 路線)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    yield 路線
    app.dependency_overrides.pop(get_cloud_route, None)
```

> 📌 為什麼放在第四道**後面**：`wire_fake_ai` 的收尾是
> `app.dependency_overrides.clear()`（會把整張表清光）。pytest 的 autouse fixture
> 是「定義順序啟動、反過來收尾」，所以排在它後面的兩道會先收自己的、
> 最後才輪到那個 clear——順序反了的話覆寫會被別人清掉。
> （就算真的排錯，②的 monkeypatch 那一管仍然擋得住——這就是「雙管」的意義。）

### - [x] 步驟 10：跑測試，看它轉綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py -v
```

預期最後一行：`11 passed`。

```bash
pytest tests/unit/test_ingest_job_store_unit.py -q
```

預期：`22 passed`（開工前這個檔是 **21** 顆——Phase 57 的 12 ＋ Phase 65 的 9——加本 phase 的 1；
**以你實查到的數字為準**，重點是比開工前多 1）。

### - [x] 步驟 11：全量回歸 ＋ 格式檢查

```bash
pytest -q
```

預期：**開工基線 ＋ 12**（＝ 580），全綠、**0 skipped**。
既有測試**一顆都不准紅**——本 phase 沒有改任何 router、任何 SQL、任何既有函式的行為。

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：`… files already formatted` ＋ `All checks passed!`。
若 `ruff check` 報 `I001`（import 排序），跑 `ruff check --fix app tests` 讓它自己修，
再跑一次 `ruff format --check`。

### - [x] 步驟 12：**不 commit**——記下收工快照

> ⛔ **本次全程不 commit**（產品負責人 2026-09-01 指示，總覽 §7 鐵律 12）。
> 不要 `git add`、不要 `git commit`、不要把計畫檔搬進 `finish/`（`git mv` 會直接 stage）。
> 歸檔與 commit 由產品負責人在整批做完之後自己決定。

```bash
cd /Users/linjunting/personalDocAI
# 收工快照（與 §2 的開工快照相減，就是本 phase 的完整 diff）
.superpowers/sdd/phase0901/snapshot-tree > /tmp/p77-after-tree.txt
git diff -U10 "$(cat /tmp/p77-before-tree.txt)" "$(cat /tmp/p77-after-tree.txt)" --stat
```

預期 `--stat` 恰好列出本 phase 的 **8 個檔**（`app/services/cloud_ingest.py` 與
`tests/unit/test_cloud_ingest_unit.py` 是新檔，其餘六個是修改），**零刪除行**以外的檔案一個都不該出現。

<details>
<summary>commit 訊息草稿（產品負責人日後要用時再貼；現在不要執行）</summary>

```bash
git add app/services/cloud_ingest.py app/services/ingest_job_store.py app/core/config.py \
        app/dependencies.py tests/fakes.py tests/conftest.py \
        tests/unit/test_cloud_ingest_unit.py tests/unit/test_ingest_job_store_unit.py
git commit -m "feat: Phase 77 雲端路契約與第五道安全網——cloud_ingest.py（MailboxMessage／CloudMailbox 與 RemoteProbe 兩份 Protocol／AlwaysRunning／CloudRouteOff／build_context）、config 加九個雲端設定（預設全關）、dependencies.get_cloud_route（只認 off，assume 與 ec2 明確 NotImplementedError）、IngestJob 加 privacy 與 route 兩個可選欄位、fakes 加 FakeMailbox 與 FakeProbe 與 ScriptedProbe 與 FakeCloudRoute、conftest 第五道 autouse wire_fake_cloud（CLOUD_ROUTE 蓋 off＋雙管換 get_cloud_route＋AWS_ENDPOINT_URL 指死埠），+12 tests；零 boto3、端點仍 22、對外行為零改變"
```

</details>

---

## 5. ASCII 圖

### 圖一：一份契約、兩個實作——本 phase 只做左邊那一半

```text
                    CloudMailbox（Protocol ＝只寫規格、不寫實作）
        put_object / get_object / delete_objects                       ← S3（兩邊共用）
        send_job / receive_job / delete_job_message                    ← jobs 佇列
        send_result / receive_result / delete_result_message /
        release_result_message                                         ← results 佇列
        input_key / context_key / result_key / instance_state          （共 14 支）
                        ▲                              ▲
        「有這些方法就算數」│                              │「有這些方法就算數」
                        │                              │
    ┌───────────────────┴──────────┐      ┌────────────┴───────────────────┐
    │  FakeMailbox                 │      │  AwsMailbox                    │
    │  ★ Phase 77（本 phase）      │      │  ★ Phase 83（**不是現在**）    │
    │                              │      │                                │
    │  objects: dict 一份          │      │  真的 boto3：S3 ＋ SQS ＋ EC2  │
    │  jobs / results 兩個 list    │      │  **全系統唯一 import boto3 處** │
    │  全部在記憶體，零網路         │      │  正式路徑用它                   │
    │  pytest 用它                 │      │  （★G1 通過之後才做）           │
    └──────────────────────────────┘      └────────────────────────────────┘

    呼叫端（Phase 79 的 CloudRoute）只知道「我拿到一個信箱」，
    完全不知道也不必知道自己拿到的是哪一個 → 換實作不必改任何呼叫端，
    而且**所有流程測試都不必連 AWS**（design6 §9）。
```

### 圖二：五道 autouse 安全網（本 phase 加最後一道）

```text
   每一顆測試開始之前，pytest 自動做這五件事：

   ①  reset_tables          清空測試庫四張表＋重播六筆資料夾種子
                            🛡 絕不動正式庫

   ②  wire_fake_ai          AI 注入點全換假件＋固定時鐘
                            🛡 絕不打真 Ollama（本機 Ollama 常駐著）

   ③  isolated_data_dir     config.DATA_DIR → tmp_path/data
                            🛡 絕不寫專案的 data/（52 MB 真照片，不入版控）

   ④  wire_memory_job_store JobStore → 每測獨立的 InMemoryJobStore
                            🛡 絕不連真 Redis、絕不啟動 Celery

   ⑤  wire_fake_cloud       config.CLOUD_ROUTE → "off"
       ★ 本 phase 新增       get_cloud_route → CloudRouteOff()（雙管）
                            AWS_ENDPOINT_URL → http://127.0.0.1:9（死埠）
                            🛡 絕不連真 AWS、絕不花到一毛錢

   ┌──────────────────────────────────────────────────────────────────────┐
   │ 為什麼要「雙管」（④ 與 ⑤ 都是）：                                     │
   │   dependency_overrides 只在 FastAPI 解析 Depends() 時才被查表；       │
   │   Celery 的 ingest_task 是把 get_cloud_route 當普通函式**直接呼叫**， │
   │   查表根本不會發生。少了 monkeypatch 那一管，測試會單跑綠、整包跑紅。 │
   └──────────────────────────────────────────────────────────────────────┘
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` 記下顆數（預期 568）

- [x] **新模組的七個公開名字（五個類別 ＋ 一個函式 ＋ 一個常數）都在，簽章與 §4 步驟 6 逐字相同**

  ```bash
  grep -nE "^ROUTE_OFF_MESSAGE|^class MailboxMessage|^class CloudMailbox|^class RemoteProbe|^class AlwaysRunning|^class CloudRouteOff|^def build_context" \
    app/services/cloud_ingest.py
  ```

  預期：7 行命中（常數 1 ＋ 類別 5 ＋ 函式 1）

- [x] **`cloud_ingest.py` 沒有 import boto3，也沒有任何資料庫字樣**

  ```bash
  # ① boto3：只查 import 那一句。docstring 裡提到「boto3」這個詞沒關係——
  #    Phase 83 的掃碼 test_boto3只在aws_mailbox裡出現 是用正規表示式比對 import 句
  grep -nE "^(import|from) +(boto3|botocore)" app/services/cloud_ingest.py || echo "OK：沒有 import boto3"
  # ② 資料庫：四個關鍵字做**逐字子字串**比對，連註解都不准出現——
  #    這四個字就是 test_SQL只出現在repository與db層 掃 app/ 全樹用的那四個
  grep -nE "psycopg|get_connection|cursor\(|\.execute\(" app/services/cloud_ingest.py || echo "OK：零資料庫字樣"
  pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：第一段印 `OK：沒有 import boto3`、第二段印 `OK：零資料庫字樣`、最後一行 `1 passed`。
  ⚠ 第二段若有命中，多半是你在註解裡寫了資料庫驅動程式的套件名（§7 陷阱 10）——改寫註解，**不要**改掃碼測試

- [x] **九個設定都在，而且預設值就是「關掉」與「空的」**

  ```bash
  python -c "
  from app.core import config
  print(config.CLOUD_ROUTE, config.AWS_REGION, config.EC2_PROBE_TTL_SECONDS,
        config.CLOUD_RESULT_TIMEOUT_SECONDS, config.WORKER_VERSION)
  print(repr(config.S3_BUCKET), repr(config.SQS_JOBS_QUEUE_URL),
        repr(config.SQS_RESULTS_QUEUE_URL), repr(config.EC2_WORKER_INSTANCE_ID))
  "
  ```

  預期兩行：`off ap-northeast-1 60 300 dev` 與 `'' '' '' ''`
  （若你的 `.env` 已經寫了值，這裡會顯示那些值——**那不算錯**，
  但要確認 `CLOUD_ROUTE` 仍是 `off`，否則手動跑 app 時會走到還沒接好的分支）

- [x] **config 沒有偷抄 AWS 金鑰**

  ```bash
  grep -n "AWS_ACCESS_KEY_ID\|AWS_SECRET_ACCESS_KEY" app/core/config.py
  ```

  預期：只命中**註解**那兩行（`# ★ AWS_ACCESS_KEY_ID／…` 開頭），
  **不可以**出現 `os.getenv("AWS_ACCESS_KEY_ID"…)`

- [x] **第五道安全網是 autouse，而且雙管都在**

  ```bash
  grep -n -B2 "def wire_fake_cloud" tests/conftest.py
  grep -n 'monkeypatch.setattr(dependencies, "get_cloud_route"' tests/conftest.py
  grep -c "@pytest.fixture(autouse=True)" tests/conftest.py
  ```

  預期：第一個指令印出緊鄰上一行是 `@pytest.fixture(autouse=True)`；
  第二個恰一行命中；第三個輸出 `5`

- [x] **新測試 12 顆全綠**

  ```bash
  pytest tests/unit/test_cloud_ingest_unit.py -v
  pytest tests/unit/test_ingest_job_store_unit.py -q
  ```

  預期：`11 passed` ＋ `22 passed`（後者 ＝ 開工前的 21 ＋ 1；以實查為準，重點是多一顆）

- [x] **全量 pytest 顆數 ＝ 開工基線 ＋ 12**

  ```bash
  pytest -q
  ```

  預期：`580 passed`、**0 skipped**

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

  預期：`580 passed`——與上一條**同樣的顆數**。
  ⚠ 絕對不要同時跑兩份 pytest（會互相 TRUNCATE 測試庫）

- [x] **專案的 `data/` 沒被弄髒**（第三道安全網仍然有效）

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都**沒有輸出**（`data/` 有 `.gitignore` 擋著，staging 正常情況是空的）

- [x] **安全網真的有效**：把 `wire_fake_cloud` 的 `autouse=True` 改成 `autouse=False`，
  跑 `pytest tests/unit/test_cloud_ingest_unit.py -q`，
  應該看到 `test_第五道安全網把CLOUD_ROUTE蓋成off且AWS_ENDPOINT_URL是死埠` 變紅
  （`KeyError: 'AWS_ENDPOINT_URL'` 或 `assert get_cloud_route in app.dependency_overrides` 的 AssertionError）；
  **確認會紅之後改回 `autouse=True`**

- [x] **git 收尾：不 commit，用快照相減**（步驟 12）

  ```bash
  .superpowers/sdd/phase0901/snapshot-tree > /tmp/p77-after-tree.txt
  git diff --stat "$(cat /tmp/p77-before-tree.txt)" "$(cat /tmp/p77-after-tree.txt)"
  git status --short -- docs/spec   # 鐵律 16：規格檔全程乾淨
  ```

  預期：`--stat` 恰為本 phase 的 **8 個檔**（2 新 ＋ 6 改），
  `docs/spec/` **沒有輸出**。**工作區不可以有任何 staged 的東西**（本次全程不 commit）

---

## 7. 常見陷阱

1. **把 `MailboxMessage` 定義到 `aws_mailbox.py` 去（照總覽 §2.4.1 的排版直覺）。**
   會壞。`cloud_ingest.py` 的 `CloudMailbox.receive_result()` 回傳型別就是它，
   定義在 boto3 那一側的話，本模組（以及每一顆流程測試）都得 import 到 boto3——
   第五道安全網白做，Phase 83 之前甚至根本 import 不起來（套件還沒裝）。
   **正解**：定義在 `cloud_ingest.py`，Phase 83 的 `AwsMailbox` 反過來 import 它。

2. **把 `from app.services.ingest_job import PromptContext` 從 `if TYPE_CHECKING:` 搬到最上面。**
   看起來比較「正常」，但會把 `ingest_job → photo_repository → psycopg` 整條拉進來。
   Phase 87 的雲端工人也會 import 到 `cloud_ingest`（拿 `MailboxMessage`），
   而那台 EC2 上根本沒有資料庫可連（design6 D11）。
   有 `from __future__ import annotations` 在，型別註記只是字串，不搬也完全正常運作。

3. **`get_cloud_route()` 的 `assume`／`ec2` 分支「先回一個 `CloudRouteOff()` 當佔位」。**
   那是**過渡產物**（產品負責人的硬要求之一：不留新舊相容分支）。更糟的是它會安靜地
   讓「我明明開了 assume」變成「什麼都沒送出去」。**正解**是明確 `raise NotImplementedError`，
   Phase 86／89 各自換掉一半——而且 `test_get_cloud_route預設off時回CloudRouteOff`
   會在那兩個 phase 變紅，剛好當提醒。

4. **`wire_fake_cloud` 只做 `dependency_overrides`、忘了 monkeypatch。**
   本 phase 之後**看起來完全沒事**（沒有人直接呼叫 `get_cloud_route`），
   到 Phase 78 把 Celery 接上去之後才爆：`ingest_task` 是把它當普通函式直接呼叫的，
   查表根本不會發生 → 測試拿到真的那一支 → `CLOUD_ROUTE` 若不是 off 就會嘗試連 AWS。
   這是 Phase 57 陷阱 7 的同一個坑，本專案已經踩過一次。

5. **`FakeMailbox._receive` 不把訊息從清單拿走，只是「看一眼」。**
   那樣 Phase 80 的「收到別人的訊息 → 還回去」測試會永遠綠（因為訊息本來就還在），
   而真的 SQS 收走之後別人是看不到的。假件模仿錯了行為，測試就會**假綠**——
   換成真 AWS 才發現「兩筆任務互相偷結果」。

6. **`instance_state_script` 用「第幾次呼叫」當索引。**
   測試常常是「先問一次（用預設 running）→ 換掉劇本 → 再問」，用呼叫次數當索引的話
   換掉劇本之後索引已經跑掉了，答案會錯開一格。**正解**是每次從清單前端拿、
   只剩一個時就重複它（步驟 8 的寫法）。

7. **`.env` 的 `EC2_PROBE_TTL_SECONDS`／`CLOUD_RESULT_TIMEOUT_SECONDS` 填了非數字（例如 `60 秒`）。**
   症狀：**整個 app 在 import config 當下就炸**（`ValueError: invalid literal for int()`），
   而且 app 與 worker 兩個容器會一直重啟。那是**刻意的**——設定寫錯要當場知道，不要默默用預設值。
   順帶：`os.getenv` 的預設值要給**字串** `"60"`、外面再包 `int(...)`（步驟 5 的寫法）；
   直接給 `60` 這次剛好能動，但下一個人照抄去寫 `bool(os.getenv("X", False))` 就會踩到
   `bool("false") is True`。

8. **步驟 1 的測試檔寫好之後就跑 `ruff check`，結果它說 import 排序錯了。**
   那是**假警報**，原因很反直覺：ruff 的 isort 是**看檔案存不存在**來分「自家程式」與
   「第三方套件」的。`app/services/cloud_ingest.py` 這時候還沒建，所以
   `from app.services.cloud_ingest import …` 會被當成第三方、被要求搬到第三方套件那一區
   （`pytest` 那一群）裡面——審稿時用 ruff 0.16.5 實測過，真的會報。**正解**：照本文件的步驟順序走（先建模組（步驟 6）、再改 `fakes.py`／
   `conftest.py`（步驟 8／9）、最後才在步驟 11 跑格式檢查），警報自己會消失。
   不要為了讓它安靜而真的把 import 搬位置——模組建好之後那個位置反而變成錯的。

9. **測試裡想放一段「假圖」，寫成 `信箱.put_object(鍵, b"假的PNG", "image/png")`。**
   `SyntaxError: bytes can only contain ASCII literal characters`——Python 的 `b"…"` 字面值
   **只准 ASCII**，中文一個都不行，而且是整個測試檔在**收集階段**就爆（看起來像 pytest 壞了）。
   **正解**：內容用 ASCII（`b"PNG-DATA"`，步驟 1 就是這樣寫）；真的要中文就
   `"假的PNG".encode()`；要一張真的圖就用 `make_png_bytes()`。

10. **在 `cloud_ingest.py` 的註解裡寫了資料庫驅動程式的套件名，`test_SQL只出現在repository與db層` 就紅了。**
    那顆 design3 的掃碼測試是對 `app/` 底下**每一個** `.py` 做**逐字子字串**比對，
    關鍵字是 `psycopg`／`get_connection`／`cursor(`／`.execute(`——**註解與 docstring 也算**。
    本 phase 的 `TYPE_CHECKING` 註解就是為了這個才寫成「資料庫驅動程式」而不是套件名
    （審稿時第一版真的踩到）。**正解**：改寫註解；**不要**把 `cloud_ingest.py` 加進白名單
    `可以碰資料庫的檔案`（總覽 §7 鐵律 4 明文禁止）。
    對照：docstring 裡提到「boto3」這個詞**沒關係**——Phase 83 的 boto3 掃碼是用正規表示式比對 `import` 句。

---

## 8. 完成後的專案狀態

系統多了一層「雲端路的契約」：

- `app/services/cloud_ingest.py`（新）：`MailboxMessage`、`CloudMailbox`／`RemoteProbe` 兩份 Protocol、
  `AlwaysRunning`、`CloudRouteOff`、`build_context()`——公開名字恰 **7 個**（5 類別 ＋ 1 函式 ＋ 1 常數）。
  **零 boto3、零 SQL、零網路。**
  > 📌 `CloudRoute`（會真的送出去的那一顆）與 `Ec2Probe` 在本 phase **完全不存在**——
  > 不留空殼、不留 `NotImplementedError` 的 stub（總覽 §2.4.1 的簽章草圖已標明「79／80 補本體」「89 加 Ec2Probe」）。
  > `get_cloud_route()` 的回傳型別註記裡雖然寫得出 `cloud_ingest.CloudRoute`，
  > 那只是 `from __future__ import annotations` 之下的一個**字串**，執行時不求值。
- `app/core/config.py`：九個新設定，預設一律「關掉／空的」。
- `app/services/ingest_job_store.py`：`IngestJob` 多兩個**可選**欄位 `privacy`／`route`。
- `app/dependencies.py`：`get_cloud_route()`——`off` 回 `CloudRouteOff()`，
  `assume`／`ec2` 明確 `NotImplementedError`（本增量**唯二**允許的暫時分支之一）。
- `tests/fakes.py`：`FakeMailbox`／`FakeProbe`／`ScriptedProbe`／`FakeCloudRoute`。
- `tests/conftest.py`：**第五道 autouse 安全網 `wire_fake_cloud`**。

**對外行為零改變**：端點仍 **22**、`openapi.json` 仍零 DELETE、`POST /photos` 仍回 202、
`GET /ingest-jobs` 的回應形狀一個字都沒變（`IngestJobOut` 是逐欄挑的，`route` 不會外洩）。
**還沒有任何人呼叫這些新東西**——Celery 仍然直接呼叫 `run_ingest_job`。

**留給下一個 phase 的接口**（Phase 78 會用到，名字逐字沿用）：

| 名字 | 在哪裡 | 誰會用 |
|---|---|---|
| `cloud_ingest.CloudRouteOff` | `app/services/cloud_ingest.py` | 78（型別）、conftest 第五道安全網 |
| `cloud_ingest.build_context(prompt_context)` | 同上 | 79 的 `submit` |
| `cloud_ingest.MailboxMessage` | 同上 | 79／80（`wait_result`）、83（`AwsMailbox` import 它）、87（工人） |
| `dependencies.get_cloud_route()` | `app/dependencies.py` | 78 的 `celery_app.ingest_task` |
| `IngestJob["privacy"]`／`["route"]` | `app/services/ingest_job_store.py` | 78（寫入）、80（崩潰重送靠 `route` 判斷） |
| `FakeMailbox`／`FakeProbe`／`ScriptedProbe`／`FakeCloudRoute` | `tests/fakes.py` | 78〜81、87、89 的測試 |

> ⏰ **兩個鬧鐘**（本 phase 刻意留下的暫時分支，各由一個 phase 拆掉）：
>
> | 暫時分支 | 誰拆掉 | 拆成什麼 |
> |---|---|---|
> | `get_cloud_route()` 的 `assume` → `NotImplementedError` | **Phase 86** | 建 `CloudRoute(AwsMailbox(...), AlwaysRunning(), …)`；同時把 `test_get_cloud_route預設off時回CloudRouteOff` 裡 `assume` 那半改成正面斷言 |
> | `get_cloud_route()` 的 `ec2` → `NotImplementedError` | **Phase 89** | 探測換成 `Ec2Probe(...)`；同時把那顆測試裡 `ec2` 那半改成正面斷言 |
>
> **不認得的值（例如 `cloudy`）永遠 `raise ValueError`**——那不是暫時分支，是永久行為：
> 打錯字要當場炸，不可以默默當成 `off`（「我明明開了雲端路怎麼都沒送出去」是最難查的）。

下一步：**Phase 78** 把隱私閘門接到 Celery 上（`gated_ingest.run_gated_ingest_job`），
讓「敏感／不確定 → 本機」「非敏感但遠端不可用 → fallback 本機」兩條路真的跑起來。

測試累計 ＝ 開工基線 ＋ **12**（總覽 §9：580）。端點 **22**（不變）。

> 📌 **實作紀錄（2026-09-01）：** 開工基線實查是 **570**（不是本文件寫的 568）、做完 **582**（不是 580）。
> 差的那 2 顆是 Phase 75 依裁決 R10 多加的，與本 phase 無關；**本 phase 仍然恰好 +12**
> （`test_cloud_ingest_unit.py` 11 ＋ `test_ingest_job_store_unit.py` 1）。
> 本文件其餘寫 568／580 的地方（§2、§6、步驟 11）同此換算：一律以「開工基線 ＋ 12」為準。

---

## 附：本文件引用的官方文件

- [boto3 設定（含 `AWS_ENDPOINT_URL` 這個標準環境變數）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html)
- [boto3 憑證的來源順序（環境變數、`~/.aws/`、instance role）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
- [SQS `ChangeMessageVisibility`（把可見度改成 0 ＝ 立刻還回佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html)
- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS Standard Queue（at-least-once、不保證順序）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [Python `typing.Protocol`（結構型別）](https://docs.python.org/3/library/typing.html#typing.Protocol)
- [Python `typing.TYPE_CHECKING`（只給型別檢查用的 import）](https://docs.python.org/3/library/typing.html#typing.TYPE_CHECKING)
- [pytest fixture（autouse 與收尾順序）](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest `monkeypatch`（`setattr`／`setenv`，測試結束自動還原）](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
