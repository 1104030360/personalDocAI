# Phase 78：閘門接線與 fallback 契約

> ⚠ **本檔已依 2026-09-01 的改判重寫。** 閘門只有一種實作：`VlmGate`——讀檔、縮圖、
> 問看圖模型一句短問題，**不看檔名、沒有字串比對表、沒有可切換的環境變數**。
> 測試裡要某個判斷結果，就覆寫 `FakePrivacyGate(Verdict.X)`，**不要**靠檔名含 `receipt`。
> 閘門要跟頁首那顆「AI 模型：本機｜雲端」開關走（D6），而 worker 行程的
> `config.AI_BACKEND` 永遠是預設值，所以 Celery 這一層用
> `dependencies.build_privacy_gate_for_backend(job["ai_backend"])` 建它（裁決 **R1**，
> 與 `vlm` 那一行同一個理由）。煙霧要量短問耗時就直接撥頁首開關，不必另加 env。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**順手做的三件事：
> ① 不要寫「非敏感 ＋ 遠端可用」那條路（`CloudRoute` 是 Phase 79／80，本 phase 只到
> `raise NotImplementedError("Phase 79")` 為止）；
> ② 不要改 `run_ingest_job` 一個字（它是 fallback 的**目的地**，必須保持是「乾淨的本機路」）；
> ③ 不要在 `photo` 表加欄位、不要新增端點、不要動前端——使用者這一 phase 完全感覺不到任何變化。

> 🎯 **一句話目標：** 讓隱私閘門真的**接線**——Celery 的任務從今天起先呼叫
> `run_gated_ingest_job()`，由它問過閘門與遠端狀態之後，再決定要不要走既有的
> `run_ingest_job()`。本 phase 之後，**四種「遠端不可用」裡的前兩種**已經會正確地
> fallback 回本機，而且 log 上留下 design6 §2.1 規定的那一行字樣。

**為什麼要做這個：**

Phase 74〜77 做出了兩樣東西，但**沒有人在用它們**：

- `privacy_gate.VlmGate`（看一眼圖、判敏感／非敏感／不確定），但沒有人呼叫 `classify()`；
- `cloud_ingest.CloudRouteOff`（會說「遠端不可用」），但沒有人呼叫 `available()`。

本 phase 把它們接到 Celery 上。接完之後，每一張照片在進 **S3／EC2** 之前，
都會先由這台電腦的 worker 分成三類（design6 D2：分類必須在檔案出機房**之前**）：

> 📌 **「在本機做」指的是「由本機的 worker 觸發、在進 AWS 那扇門之前」**，
> 不是「短問一定打本機模型」——短問打哪一顆跟著頁首開關走（D6，2026-09-01 改判）。
> 兩扇門要分清楚：ollama.com 那扇是**開發加速**用的，撥到雲端時連敏感檔的短問也會經過它
> （總覽 §8.2 的已知限制，產品負責人接受）；**S3／EC2 那扇門永遠只認 `NON_SENSITIVE`**。

| 閘門的判斷 | 這一筆會怎樣 | log 上留下 |
|---|---|---|
| `SENSITIVE`（敏感） | 走 `run_ingest_job`（＝增量五那條路） | `route=local verdict=SENSITIVE` |
| `UNCERTAIN`（不確定） | 同上——**不確定一律當敏感辦**（D3） | `route=local verdict=UNCERTAIN` |
| `NON_SENSITIVE` ＋ 遠端不可用 | 同上——這叫 **fallback** | `fallback=local reason=remote_unavailable` |
| `NON_SENSITIVE` ＋ 遠端可用 | **Phase 79 才做**——本 phase 先寫 `route=cloud`、印契約字樣，然後明確 `NotImplementedError`（正式路徑走不到） | `route=cloud verdict=NON_SENSITIVE`（本 phase 就先印，Phase 79 接在它後面送出） |

**這裡最重要的一件事不是「雲端」，而是「退路」。** design6 §0 把它寫成一條禁止：
「遠端不可用時上傳改 5xx 或讓使用者重傳」是**違規的**。
EC2 平常是 **Stop** 的（產品負責人要卡片 $0，用完就關），所以「遠端關著」才是**常態**、不是例外。
先把退路做對、做到有測試釘住，之後每一層才不是在賭「AWS 永遠通」。

做完本 phase 之後：**對外行為仍然零改變**（`CLOUD_ROUTE` 預設 `off`，
`CloudRouteOff.available()` 恆為 `False`，所以每一張照片都會走 fallback ＝ 增量五那條路），
但系統多了一層「岔路口」，而且岔路口的每一條分支都有測試釘住。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **閘門（Privacy Gate）** | 本專案自己寫的判斷器，在照片被送去任何地方之前先問「這張敏不敏感」。**分類這個動作**在檔案進 S3 之前、由這台電腦的 worker 觸發（D2）；它會真的讀檔、縮圖、問看圖模型一句短問題，所以**不便宜**（本機推估 20〜60 秒、雲端約 2 秒，**未實測**——步驟 8b 的煙霧就是去量它）。短問要打哪一顆模型跟著頁首開關走（D6） |
| **三分類（Verdict）** | 閘門只會回三個答案：`SENSITIVE`／`NON_SENSITIVE`／`UNCERTAIN`。規則是「敏感→本機；不確定→本機；**只有非敏感才允許雲端**」 |
| **fallback（退路）** | 「本來想走 A，A 不行就改走 B」。本專案的 B 永遠是既有的 `run_ingest_job()`——也就是「跟增量五完全一樣的做法」 |
| **`fallback=local reason=…`** | 這一行字是**契約**（design6 §2.1 明文要求 log 要寫）。四個 reason：`remote_unavailable`（本 phase）、`submit_failed`（Phase 79）、`result_timeout`／`redelivered_without_result`（Phase 80） |
| **`route=… verdict=…`** | 另一行契約字樣（總覽 §2.5）：`route=local verdict=SENSITIVE`／`UNCERTAIN`（本 phase 會走到）與 `route=cloud verdict=NON_SENSITIVE`（本 phase 先印好、Phase 79 接在它後面真的送出；真機 Demo 2 就是靠這一行認出「這一張走了雲端」） |
| **`caplog`** | pytest 內建的 fixture：「把這次測試期間打出來的 log 抓起來給我看」。本專案用它把上面那行字樣**逐字**釘住 |
| **崩潰重送（redelivery）** | worker 做到一半被殺掉（機器重開、Docker 重啟），佇列沒收到「做完了」的回覆，於是把同一個任務再發一次。冪等就是為了它 |
| **`route` 欄位** | Phase 77 加在 JobStore 上的欄位（`local`／`cloud`）。它有三種狀態：**沒有這個鍵**（還沒判斷過）、`local`、`cloud`。「沒有鍵」與「值是 local」是兩件不同的事——崩潰重送靠這個差別決定「要不要再問一次閘門」 |
| **接線（wiring）** | 把已經做好的零件插到主流程上。本 phase 就是純接線：零件都是 74〜77 做好的 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D2 Privacy Gate 在出門之前** | 分類必須在檔案出機房**之前**做 | `run_gated_ingest_job()` 的第一件事就是 `gate.classify(...)`，而且它跑在本機的 Celery worker 裡（HTTP 那一層一個字都不動） |
| **D3 三分類** | 敏感→本機；不確定→本機；只有非敏感才允許雲端 | `if verdict != Verdict.NON_SENSITIVE: 走本機`——一行把「不確定＝本機」釘死 |
| **D6 閘門跟著頁首開關走** | 閘門用哪一顆模型跟開關走；**不准**去寫入／關掉那顆開關 | `gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"])`（裁決 **R1**）——worker 行程的 `config.AI_BACKEND` 永遠是 `local`，只有入列快照（D14）才是使用者當時撥的位置。本 phase 不寫入 `AI_BACKEND` 一個字 |
| **D5 插在 Celery 開頭** | `POST /photos` 仍 202、仍先 staging；分類在拿 job 之後、看圖之前 | `celery_app.ingest_task` 改呼叫 `run_gated_ingest_job`；`app/api/routers/` 一個字都不動 |
| **D10 遠端關掉＝fallback 本機** | 不上傳失敗、不要求重傳、進度面板語意不變 | `_退回本機路()`：寫 `route=local` → log 契約字樣 → 呼叫 `run_ingest_job` |
| **§2.1 Fallback 契約** | 四種「遠端不可用」＋盡力清乾淨＋log 字樣＋**禁止重跑分類器** | 本 phase 做前兩種（不是 `running`／API 失敗）；`route == "local"` 的崩潰重送**直接走本機、不再問閘門** |
| **§8 錯誤表第 1 列** | 敏感／不確定 → 本機入庫；零 S3／jobs／results | `test_敏感照片走本機_零submit_job記下privacy與route`、`test_不確定照片走本機_零submit` |
| **§8 錯誤表第 2 列** | 非敏感、EC2 Stop → 本機 `run_ingest_job`，202 與進度面板不變 | `test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable` |
| **§8 錯誤表第 3 列** | 非敏感、無 AWS 憑證 → 同上 | `test_非敏感但探測丟例外_同樣fallback本機` |
| **§9 測試策略第 1、2、4、5 條** | 敏感／不確定零 PutObject；假遠端 stopped 走 `run_ingest_job`；DescribeInstances 丟錯同 fallback | 本 phase 的前四顆測試（第 3 條「非敏感＋running」是 Phase 79） |
| **§0 禁止第 6 條** | 遠端不可用時**不准** 5xx、不准要使用者重傳 | 本 phase 的四顆 fallback 測試都斷言「照片照樣入收件箱、列數 1」 |
| **總覽 §2.5** | `run_gated_ingest_job` 的流程規格 | 本 phase 逐字落地前半段（雲端那半段是 79／80／81） |

---

## 2. 前置條件

**要先做完的 phase：**

- **Phase 74**：`app/services/privacy_gate.py` 有 `Verdict`／`PrivacyGate`／`PrivacyModel`／
  `PrivacyJudgement`／`judgement_to_verdict`／`VlmGate`（唯一真閘門，**不看檔名**）；
  `dependencies.get_privacy_gate()` 存在；`tests/fakes.py` 有 `FakePrivacyGate`；
  `conftest.wire_fake_ai` 已經把 `get_privacy_gate` 接成 `FakePrivacyGate(Verdict.UNCERTAIN)`。
- **Phase 75**：`privacy_gate.OllamaPrivacyModel`（真的看圖、跟 `AI_BACKEND` 走）、
  `shrink_for_model`、`ai_timing` 多認一種 kind `privacy`；
  **`dependencies.build_privacy_gate_for_backend(ai_backend)`**（裁決 R1；寫法比照
  `build_vlm_for_backend`），而 `get_privacy_gate()` ＝
  `build_privacy_gate_for_backend(config.AI_BACKEND)`（web 行程與測試用）。
  **本 phase 的 Celery 那一行要的就是前者。**
- **Phase 76**：`app/services/ingest_job.py` 已經拆出五個公開積木
  （本 phase 只用到 `run_ingest_job`，但 79 之後會用到其他四個）。
- **Phase 77**：`app/services/cloud_ingest.py`、`dependencies.get_cloud_route()`、
  `IngestJob` 的 `privacy`／`route` 欄位、`tests/fakes.py` 的 `FakeCloudRoute`、
  conftest 的第五道安全網 `wire_fake_cloud`。

**★G1 還沒到**：本 phase 全程**零 AWS**（design6 §0 禁止第 1 條）。

開工前**實查**基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db 與 redis 要 Up (healthy)，不然測試會一整片連線錯誤
pytest -q
```

預期：`580 passed`、**0 skipped**（總覽 §9 的累計數字）。以你實查到的為準，
本文件之後稱它「**開工基線**」。

開工前**快照**（總覽 §7 鐵律 12：各 phase 做完**不會**馬上 commit，所以 74〜77 的改動也還躺在工作區；
§6 的 git 驗收一律用「與這份快照相減」，不直接看 `git status`）：

```bash
git status --short -- app tests deploy > /tmp/p78-before.txt
shasum app/services/ingest_job.py > /tmp/p78-ingest_job.sha   # §6 要用它證明本 phase「一個字都沒改」ingest_job.py
```

預期：兩行都**沒有輸出**（結果寫進檔案了）。`cat /tmp/p78-before.txt` 印出 74〜77 動過的檔
（`fakes.py`、`conftest.py`、`privacy_gate.py`…）是正常的——那不是你弄的。

確認四個前置真的在：

```bash
python -c "
from app import dependencies
from app.services.privacy_gate import Verdict
from app.services.cloud_ingest import CloudRouteOff
print('閘門注入點：', dependencies.get_privacy_gate)
print('依快照建閘門：', dependencies.build_privacy_gate_for_backend)
print('三分類：', [v.value for v in Verdict])
print('雲端路關掉時：', CloudRouteOff().available())
"
```

預期：印出**兩個**函式、`['SENSITIVE', 'NON_SENSITIVE', 'UNCERTAIN']`、`False`。

⚠ 這裡只印函式物件、**不要真的呼叫** `get_privacy_gate()`——Phase 75 之後它會建出
`OllamaPrivacyModel`（建物件本身不連線，但沒必要在確認前置時多這一步）。
少了 `build_privacy_gate_for_backend` 就是 Phase 75 還沒做完（裁決 R1），先回去補。

> ⚠️ **絕對不要同時跑兩份 pytest**（會互相 TRUNCATE 測試庫，症狀是大量看似隨機的 404）。

---

## 3. 範圍

### 做

1. **新建 `app/services/gated_ingest.py`**：`run_gated_ingest_job()` ＋ 兩支私有小工具
   （`_遠端可用嗎()`、`_退回本機路()`）＋ 四個 reason 常數。「非敏感 ＋ 遠端可用」那一條寫到
   `store.update(route="cloud")` ＋ 契約 log `route=cloud verdict=NON_SENSITIVE` 為止，
   接著 `raise NotImplementedError("Phase 79")`（79 只換掉那一行 raise，前兩行不必搬）。
2. **`app/celery_app.py`**：`ingest_task` 改呼叫 `run_gated_ingest_job`，
   多傳 `gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"])`
   與 `cloud=dependencies.get_cloud_route()`。
   > 📌 **`gate` 為什麼不是 `get_privacy_gate()`（裁決 R1）**：worker 是另一個行程，
   > 它那份 `config.AI_BACKEND` 永遠是預設的 `"local"`。用 `get_privacy_gate()` 建的話，
   > 使用者把頁首開關撥到雲端時，看圖走雲端、閘門卻仍打本機——**違反 D6 而且安靜**。
   > 入列當下已經把開關值抄進 `job["ai_backend"]`（D14），閘門跟 `vlm` 用同一份快照。
3. **`tests/conftest.py`**：`wire_fake_ai` 對 `get_privacy_gate` **與**
   `build_privacy_gate_for_backend` 都補上 monkeypatch（同一顆假閘門）；
   `目前注入的假件()` 多回 `gate`／`cloud`；`跑完任務()` 改呼叫 `run_gated_ingest_job`。
   > 📌 **既有幾十顆用 `跑完任務()` 的測試行為完全不變**：預設閘門是
   > `FakePrivacyGate(Verdict.UNCERTAIN)`（Phase 74 掛的）＝「不確定」＝走本機，
   > 而預設雲端路是 `CloudRouteOff()`（第五道安全網掛的）＝永遠不可用。
   > 兩個加起來的結果就是「照舊呼叫 `run_ingest_job`」。
4. **新建 `tests/integration/test_gated_ingest.py`**（8 顆）。
5. **`tests/unit/test_celery_app_unit.py`** 追加 1 顆。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 寫「非敏感 ＋ 遠端可用」那條路 | 那是 **Phase 79**。本 phase 那一條明確 `raise NotImplementedError("Phase 79")`——這是本增量**唯二**允許的暫時分支之一（總覽 §2.7），而且正式路徑走不到（`CloudRouteOff.available()` 恆 False） |
| 處理 `route == "cloud"` 的崩潰重送 | 那是 **Phase 80**。本 phase 會寫 `route="cloud"` 的地方只有那條走不到的暫時分支（正式路徑的 `CloudRouteOff.available()` 恆 False；pytest 的第五道安全網也把雲端路關著），所以那個分支現在不存在也不會有人踩到 |
| 改 `app/services/ingest_job.py` | 它是 fallback 的**目的地**，必須保持「乾淨的本機路」。本 phase 一個字都不改（`git diff` 要是空的） |
| 在 fallback 時再問一次閘門 | design6 §2.1 **明文禁止**。已經判定非敏感了，遠端沒了就本機看圖 |
| 把 `route` 顯示在進度面板／回應裡 | 使用者不需要知道這張是雲端跑的（總覽 §2.4.4）。`IngestJobOut` 是逐欄挑的，本 phase 不碰它 |
| 新增第五種 job 狀態（例如 `gating`） | `JOB_STATUSES` 仍是四個。一進門就標 `analyzing`（沿用 design5 §4.4） |
| 讓 `tests/fakes.py` 的 `EagerDispatcher` 也改走閘門 | 它是給「POST 完照片就已經在資料庫裡」的測試用的，走的是**本機路**——那正是那些測試要的。改了只會讓它們無故多繞一圈 |
| 把閘門塞進 `POST /photos`（HTTP 那一層） | design6 D5 明文：**不把本機分類放進 HTTP 路徑**。HTTP 只做格式檢查、落 staging、入列、回 202 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並**真的跑它、親眼看到紅**，
> 步驟 3〜6 才動實作。

### - [x] 步驟 1：先寫測試（紅）——新建 `tests/integration/test_gated_ingest.py`

整份貼上：

```python
"""隱私閘門接線之後的整合測試（design6 §2、§2.1；Phase 78 建，79／80 會追加）。

★ 本檔**不打 HTTP**：直接呼叫 run_gated_ingest_job()——與 test_ingest_job.py 同一套玩法
  （design5 D15 的延伸：任務本體是一支函式，測試自己扮演 worker）。

conftest 的五道 autouse 安全網照樣生效（尤其第一道會清空測試庫、第三道把
data/ 指到暫存目錄），但本檔的六個依賴一律**當參數傳**，不靠 dependency_overrides：

    store       每顆測試自己 new 一個 InMemoryJobStore（天生隔離）
    vlm         FakeVLM（雲端路走不到它，本機路才用得到）
    embeddings  FakeEmbeddings
    now         FixedClock（**callable**，呼叫它才拿到 datetime）
    gate        FakePrivacyGate（Phase 74）
    cloud       FakeCloudRoute（Phase 77）——Phase 79 起改用真的 CloudRoute ＋ FakeMailbox
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.repositories import photo_repository
from app.services import gated_ingest, staging_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeCloudRoute,
    FakeEmbeddings,
    FakePrivacyGate,
    FakeVLM,
    FixedClock,
    make_jpeg_bytes,
    make_png_bytes,
)

NOW = FixedClock(datetime(2026, 8, 18, 10, 0))

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class 記得最後一筆的Store(InMemoryJobStore):
    """成功時 job 會被刪掉，但測試還想看「刪掉之前 privacy／route 是什麼」。

    只多做一件事：delete() 之前先把那一筆抄一份存進 self.deleted。
    完全只用 JobStore 的公開介面（get／delete）——寫法沿用 test_ingest_job_pdf.py
    的同名類別（那邊也是為了看「刪掉之前」的樣子）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


class 偷看狀態的閘門:
    """被問的那一刻，順手記下 job 的 status 是什麼。

    用來釘 design6 D5 的「一進門就標 analyzing」：進度面板上那一列不可以停在
    queued 讓人以為沒動靜（沿用 design5 §4.4，雲端路一樣要遵守）。
    """

    def __init__(self, store, job_id: str, verdict: Verdict = Verdict.SENSITIVE) -> None:
        self._store = store
        self._job_id = job_id
        self._verdict = verdict
        self.看到的狀態: list[str] = []

    def classify(self, *, filename: str, content_type: str, load_bytes) -> Verdict:
        job = self._store.get(self._job_id)
        self.看到的狀態.append(job["status"] if job else "沒有這筆")
        return self._verdict


def 建一個job(
    store: InMemoryJobStore,
    *,
    job_id: str = "job-1",
    filename: str = "a.png",
    content_type: str = "image/png",
) -> str:
    """模擬 HTTP 端點會做的兩件事：落 staging ＋ 建 job（與 test_ingest_job.py 相同）。

    位元組要跟 content_type 對得上：本機路會真的用 Pillow 打開它做縮圖
    （假位元組會炸 UnidentifiedImageError，Phase 19 起的規矩）。

    ★ `filename` 純粹是**記帳**：本檔每一顆測試的 verdict 都由測試自己傳進來的
      `FakePrivacyGate(...)` 決定，跟檔名沒有關係——真閘門 `VlmGate` 也**不看檔名**
      （總覽 §10.1 f）。取名叫「身分證.png」「receipt.png」只是讓測試讀起來像那麼一回事。
    """
    位元組 = make_jpeg_bytes() if content_type == "image/jpeg" else make_png_bytes()
    staging_service.save_staging(job_id, content_type, 位元組)
    store.create(
        job_id=job_id,
        filename=filename,
        content_type=content_type,
        ai_backend="local",
        source="upload",
    )
    return job_id


def 收件箱id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def 跑(job_id: str, *, store, gate, cloud, vlm=None, embeddings=None) -> None:
    """把六個零件組好、呼叫本 phase 的主角。"""
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=vlm if vlm is not None else FakeVLM(收據理解),
        embeddings=embeddings if embeddings is not None else FakeEmbeddings(),
        now=NOW,
        gate=gate,
        cloud=cloud,
    )


# ---------------------- ① 敏感與不確定：一個位元組都不出門 ----------------------


def test_敏感照片走本機_零submit_job記下privacy與route(caplog):
    """design6 §8 錯誤表第 1 列、§9 必釘第 1 條。

    ★ cloud 刻意用「遠端**開著**」的假件：這樣「零 submit」就只可能是閘門擋下來的，
      不會被「反正遠端也沒開」蒙混過去。
    """
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store, filename="身分證.png")
    閘門 = FakePrivacyGate(Verdict.SENSITIVE)
    路線 = FakeCloudRoute(True)

    跑(job_id, store=store, gate=閘門, cloud=路線)

    # 一個位元組都沒有出門
    assert 路線.submit_calls == 0
    assert 路線.available_calls == 0, "敏感就該直接走本機，連問都不必問遠端"
    # 照片照樣入收件箱（使用者完全無感）
    assert photo_repository.count_photos() == 1
    assert len(photo_repository.list_photos_in_folder(收件箱id())) == 1
    # 兩個新欄位都記下來了
    最後 = store.deleted[job_id]
    assert 最後["privacy"] == "SENSITIVE"
    assert 最後["route"] == "local"
    assert 閘門.calls == 1, "閘門只問一次（一次分類要便宜，design6 D4）"
    assert any("route=local verdict=SENSITIVE" in m for m in caplog.messages), caplog.messages


def test_不確定照片走本機_零submit():
    """design6 D3：**不確定一律當敏感辦**。§9 必釘第 2 條。

    `UNCERTAIN` 在真實世界怎麼來的：模型說「不敏感但我沒把握」、模型丟例外、
    staging 檔讀不到、圖解不開、PDF 拆不開——全部都是（Phase 74／75 的契約）。
    判不出來的代價只能是「沒卸到雲端」，絕不可以是「敏感檔外流」。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個job(store, filename="camera.jpg", content_type="image/jpeg")
    閘門 = FakePrivacyGate(Verdict.UNCERTAIN)
    路線 = FakeCloudRoute(True)

    跑(job_id, store=store, gate=閘門, cloud=路線)

    assert 路線.submit_calls == 0
    assert photo_repository.count_photos() == 1
    最後 = store.deleted[job_id]
    assert 最後["privacy"] == "UNCERTAIN"
    assert 最後["route"] == "local"


# ---------------------- ② 非敏感但遠端不可用：fallback ----------------------


def test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable(caplog):
    """design6 §8 錯誤表第 2 列、§9 必釘第 4 條、§0 禁止第 6 條。

    這是本增量**最重要**的一顆：EC2 平常是 Stop 的，所以這條路才是常態。
    使用者看到的東西必須與增量五**逐字相同**——照片照樣入收件箱，
    唯一的差別是 worker 的 log 多一行。
    """
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store, filename="receipt.png")
    閘門 = FakePrivacyGate(Verdict.NON_SENSITIVE)
    路線 = FakeCloudRoute(False)  # 遠端關著

    跑(job_id, store=store, gate=閘門, cloud=路線)

    assert 路線.available_calls == 1, "非敏感才需要問遠端；而且只問一次"
    assert 路線.submit_calls == 0, "遠端不可用就不可以送出去"
    assert photo_repository.count_photos() == 1, "照片照樣入庫（不准 5xx、不准要人重傳）"
    最後 = store.deleted[job_id]
    assert 最後["privacy"] == "NON_SENSITIVE"
    assert 最後["route"] == "local", "fallback 之後 route 要釘成 local（崩潰重送才不會再送一次）"
    assert any("fallback=local reason=remote_unavailable" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


def test_非敏感但探測丟例外_同樣fallback本機(caplog):
    """design6 §8 錯誤表第 3 列（沒有 AWS 憑證／API 掛了）、§9 必釘第 5 條。

    「問不到答案」與「沒開機」對這個系統來說是同一件事——都走 fallback。
    ⚠ 例外**絕對不可以**往外飛：飛出去的話 Celery 會把整個任務標成失敗，
      使用者就會看到一列莫名其妙的紅字（違反 §0 禁止第 6 條）。
    """
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store, filename="menu.png")
    閘門 = FakePrivacyGate(Verdict.NON_SENSITIVE)
    路線 = FakeCloudRoute(RuntimeError("Unable to locate credentials"))

    跑(job_id, store=store, gate=閘門, cloud=路線)

    assert 路線.submit_calls == 0
    assert photo_repository.count_photos() == 1
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=remote_unavailable" in m for m in caplog.messages)


# ---------------------- ③ 崩潰重送與邊界 ----------------------


def test_崩潰重送時route已是local就不再問閘門():
    """design6 §2.1 的禁止：**fallback 時絕不再跑一次 classifier**。

    重現方式：手動把 job 調成「上一趟已經決定走本機」的樣子（route=local），
    再跑一次。閘門必須**一次都沒被呼叫**。

    為什麼這條規則重要：閘門每問一次就是**真的看一次圖**（Phase 75 之後打的是
    本機或 ollama.com 的看圖模型）。每次崩潰重送都重問一次，等於白花一次推論，
    而且答案還可能跟上一趟不一樣（模型不是決定論的）——已經決定的事就別再問。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="local")
    閘門 = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換一個答案，也不該被問到
    路線 = FakeCloudRoute(True)

    跑(job_id, store=store, gate=閘門, cloud=路線)

    assert 閘門.calls == 0, "route 已經是 local 了，不可以再問一次閘門"
    assert 路線.available_calls == 0
    assert photo_repository.count_photos() == 1


def test_job不存在時安靜結束():
    """job 已過期或已被 dismiss：安靜結束，不可以炸掉整個 worker。

    語意與 run_ingest_job 完全相同（那一支也是 log 一行就 return）。
    """
    store = InMemoryJobStore()

    跑("根本沒有這筆", store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=FakeCloudRoute())

    assert photo_repository.count_photos() == 0


def test_一進門status就變analyzing():
    """design5 §4.4 的規則，雲端路一樣要遵守：崩潰重送時面板不可以停在 queued。

    ★ 順序很重要：**先** update(status="analyzing")、**才**問閘門。
      反過來寫的話，閘門看圖的那幾十秒裡（本機推估 20〜60 秒），面板上那一列
      會一直是「排隊中」，使用者會以為系統當掉了。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    閘門 = 偷看狀態的閘門(store, job_id)

    跑(job_id, store=store, gate=閘門, cloud=FakeCloudRoute())

    assert 閘門.看到的狀態 == ["analyzing"], (
        f"問閘門的時候狀態應該已經是 analyzing：{閘門.看到的狀態}"
    )


def test_閘門收到的檔名就是job裡的filename():
    """這一顆測的是**傳遞**，不是判斷。

    真閘門 `VlmGate` **不看檔名**（總覽 §10.1 f、Phase 74 的 `test_檔名完全不影響判斷`），
    所以傳錯檔名不會改變 verdict——但 `filename` 仍在 `classify()` 的簽章裡：
    假件靠它記帳、log 與日後除錯靠它認人。傳成 `job_id` 那種東西不會壞掉、
    也不會有錯誤訊息，只會讓所有紀錄都變成一串看不懂的號碼，所以釘一顆守著。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store, filename="身分證正面.jpg", content_type="image/jpeg")
    閘門 = FakePrivacyGate(Verdict.SENSITIVE)

    跑(job_id, store=store, gate=閘門, cloud=FakeCloudRoute())

    assert 閘門.last_filename == "身分證正面.jpg"
    assert 閘門.calls == 1
```

### - [x] 步驟 2：先寫測試（紅）——`tests/unit/test_celery_app_unit.py` 追加 1 顆

- [x] 檔頭 import 區改成（多三行；ruff 的 `I` 規則會照這個順序排）：

```python
from app import dependencies
from app.celery_app import celery_app, ingest_task
from app.core import config
from app.services import gated_ingest, vlm_service
from app.services.cloud_ingest import CloudRouteOff
from app.services.privacy_gate import Verdict
from tests.fakes import FakePrivacyGate
```

- [x] 在檔案**最後面**加上：

```python


def test_ingest_task把gate與cloud都傳進去(monkeypatch):
    """design6 D5／D6：Celery 任務從此呼叫 run_gated_ingest_job，六個零件一個都不能少，
    而且 gate 與 vlm 都要用**同一份快照** job["ai_backend"] 建（裁決 R1）。

    ★ 為什麼 celery_app.py 要寫成 `gated_ingest.run_gated_ingest_job(...)`
      而不是 `from app.services.gated_ingest import run_gated_ingest_job` 再直接呼叫：
      **模組屬性是呼叫當下才解析的**，所以 monkeypatch 換得掉；
      早綁定（from … import）拿到的是換掉前的舊參照，這一顆會什麼都抓不到。
      這與第四／五道安全網攔得住 dependencies.get_job_store()／get_cloud_route()
      是同一個道理（Phase 57 陷阱 7）。

    ★ gate 與 cloud 都要拿到**假件**，這一顆才算數：ingest_task 是**直接呼叫**
      dependencies.build_privacy_gate_for_backend()／get_cloud_route()，而
      dependency_overrides 只在 FastAPI 解析 Depends() 時才被查表——所以兩道安全網
      都必須「雙管」（dependency_overrides ＋ monkeypatch）。少了 monkeypatch 那一管，
      這裡拿到的會是真的那一支：Phase 75 之後那一支會建出 OllamaPrivacyModel，
      pytest 就有機會打到真的看圖模型。

    ★ 這一顆刻意把 job 的快照設成 "cloud"、把 worker 行程的 config.AI_BACKEND
      留在 "local"：兩個值不一樣，才驗得出「閘門跟的是快照、不是行程裡那個變數」。
      寫成 get_privacy_gate() 的話 收到參數 會是 ["local"]，這一顆就紅——
      而正式環境裡那個錯誤是**安靜**的（看圖走雲端、閘門仍打本機，違反 D6）。
    """
    # HTTP header 不吃中文，假 key 一律 ASCII（2026-08-22 踩過）
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(config, "AI_BACKEND", "local")  # worker 行程永遠是這個值

    收到: dict = {}
    收到參數: list[str] = []

    def 假的入庫任務(job_id, **kwargs):
        收到["job_id"] = job_id
        收到.update(kwargs)

    def 記帳的建閘門(ai_backend):
        收到參數.append(ai_backend)
        return FakePrivacyGate(Verdict.UNCERTAIN)

    monkeypatch.setattr(gated_ingest, "run_gated_ingest_job", 假的入庫任務)
    monkeypatch.setattr(dependencies, "build_privacy_gate_for_backend", 記帳的建閘門)

    store = dependencies.get_job_store()  # 第四道安全網已經把它換成記憶體版
    store.create(
        job_id="job-1",
        filename="a.png",
        content_type="image/png",
        ai_backend="cloud",  # 入列當下使用者把頁首開關撥在雲端（D14 的快照）
        source="upload",
    )

    ingest_task("job-1")

    assert 收到["job_id"] == "job-1"
    assert set(收到) == {"job_id", "store", "vlm", "embeddings", "now", "gate", "cloud"}
    assert 收到["store"] is store
    assert isinstance(收到["gate"], FakePrivacyGate), (
        "wire_fake_ai 的第二管（monkeypatch）沒接上——ingest_task 是直接呼叫 "
        "dependencies.build_privacy_gate_for_backend()，dependency_overrides 攔不到它"
    )
    assert 收到參數 == ["cloud"], (
        "閘門必須用 job['ai_backend'] 這份快照建（裁決 R1）。拿到 ['local'] "
        "代表寫成了 get_privacy_gate()——worker 行程的 config.AI_BACKEND 永遠是 local，"
        "頁首撥到雲端時閘門會安靜地繼續打本機，違反 D6"
    )
    assert isinstance(收到["cloud"], CloudRouteOff), "第五道安全網把雲端路換成關掉的那一顆"
    assert isinstance(收到["vlm"], vlm_service.OllamaCloudVLM), (
        "看圖物件也是同一份快照建的（增量五既有行為，本 phase 一個字都沒改）"
    )
```

> 📌 **這一顆為什麼不拆成兩顆**：總覽 §2.7 給 Phase 78 的是 **+9 顆**，
> 而「六個零件都傳到了」與「閘門用的是快照」是同一次呼叫的兩個面向，
> 拆開會讓兩顆做一模一樣的前置。顆數維持 589。

### - [x] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_gated_ingest.py -q
```

預期：**收集階段就爆**（模組還不存在）。注意錯誤的名字是 `ImportError`、**不是** `ModuleNotFoundError`
——兩個檔都是 `from app.services import gated_ingest, …` 這種「從套件拿子模組」的寫法，
Python 找不到子模組時報的是這一種（2026-09-01 實查）：

```text
ERROR tests/integration/test_gated_ingest.py
E   ImportError: cannot import name 'gated_ingest' from 'app.services' (/Users/linjunting/personalDocAI/app/services/__init__.py)
```

```bash
pytest tests/unit/test_celery_app_unit.py -q
```

預期：同一句 `ImportError: cannot import name 'gated_ingest' from 'app.services'`（本檔新的 import 也指向還不存在的模組）。

### - [x] 步驟 4：綠（1／3）——新建 `app/services/gated_ingest.py`

整份貼上：

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

【本 phase（78）做到哪裡】
閘門分流、route=local、遠端不可用 → fallback，四件事都做完了。
「非敏感 ＋ 遠端可用」那一條只做到「route=cloud ＋ 契約 log」就 raise NotImplementedError("Phase 79")
——**Phase 79 一定要把那一行 raise 換掉**（總覽 §2.7 已寫進 79 的「做」清單）。
正式路徑走不到那一行：CLOUD_ROUTE 預設 off，CloudRouteOff.available() 恆為 False。

分層：本模組不寫 SQL、不碰 HTTP、不自己看圖——它只是「決定呼叫誰」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.services import cloud_ingest, ingest_job, staging_service, vlm_service
from app.services.ingest_job_store import JobStore
from app.services.privacy_gate import PrivacyGate, Verdict

logger = logging.getLogger(__name__)

# fallback 的四個理由（design6 §2.1）。**這四個字串是契約**——
# log 長什麼樣，design6 §2.1 有明文（`fallback=local reason=…`），測試用 caplog 逐字釘。
# 抽成常數是為了讓「產品碼」與「測試」不會各自打錯字。
REASON_REMOTE_UNAVAILABLE = "remote_unavailable"  # 不是 running／沒憑證／API 掛了（本 phase）
REASON_SUBMIT_FAILED = "submit_failed"  # PutObject 或 SendMessage 失敗（Phase 79）
REASON_RESULT_TIMEOUT = "result_timeout"  # 送出去了但等不到結果（Phase 80）
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

    ★ 型別註記裡的 cloud_ingest.CloudRoute 要 Phase 79 才存在。
      本檔最上面有 `from __future__ import annotations`，所以註記只是**字串**、
      執行時不會被求值——現在寫上去不會炸，79 補完之後這一行也不必再改。

    ★ 不回傳任何東西：結果全部寫進 JobStore 與資料庫（與 run_ingest_job 同語意）。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被 dismiss：安靜結束。這不是錯誤——重送時本來就可能撞到。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    # 一進門就標 analyzing（design5 §4.4，雲端路一樣遵守）：
    # 崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    # ★ 要在問閘門**之前**：閘門會真的看一次圖（本機推估 20〜60 秒）。
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
        # load_bytes 傳的是「還沒執行的那個 lambda」，不是先讀好的位元組。
        # 真閘門（VlmGate）**一定**會呼叫它——要看圖才判得出來——但讀檔這件事
        # 的成敗要由閘門自己接住：staging 檔不在時它回 UNCERTAIN
        # （Phase 74 的 test_讀檔失敗回UNCERTAIN），而不是讓例外從這裡飛出去。
        # 另外，route 已是 local 的崩潰重送根本走不到這一行，也就不必白讀一次磁碟。
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
    # route 先釘成 "cloud"，再留一行契約字樣（總覽 §2.5：真機 Demo 2 靠 `route=cloud` 這一行對帳）。
    # 這兩行 Phase 79 原封不動沿用；79 只換掉最下面那一行 raise。
    store.update(job_id, route="cloud")
    logger.info("job %s route=cloud verdict=%s", job_id, verdict.value)

    # ⛔ 本增量**唯二**允許的暫時分支之一（總覽 §2.7）：Phase 79 一定要把這一行換掉。
    #    正式路徑走不到這裡——CLOUD_ROUTE 預設 off，CloudRouteOff.available() 恆為 False。
    raise NotImplementedError("Phase 79")


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
```

> 📌 **為什麼呼叫既有積木時一律寫 `ingest_job.run_ingest_job(...)`（帶模組名）**，
> 而不是 `from app.services.ingest_job import run_ingest_job`：
> ① 讀的人一眼看得出這支函式**是別人的**（本檔只是決定呼叫誰）；
> ② 模組屬性是呼叫當下才解析的，測試想換掉它時 monkeypatch 才有效；
> ③ Phase 79／81 還要再用四個積木（`load_prompt_context`／`embed_understanding`／
> `insert_photo_with_files`／`finish_image_job`／`fail_job`），全部帶模組名就不必一直改 import 區。

### - [x] 步驟 5：綠（2／3）——`app/celery_app.py` 改呼叫閘門版

這個檔只改**四個地方**，其餘一個字都不要動。

- [x] ① 檔頭 docstring 最後一段，把

```text
★ 本檔刻意寫得很薄（design5.md D15）：所有規則（VLM 重試 3 次、PDF 逐頁、
  失敗清乾淨、冪等）都在 run_ingest_job 裡，這裡只負責「把零件組好、呼叫它」。
  所以測試可以直接呼叫 run_ingest_job，不必啟動 Celery、不必有 Redis。
```

換成

```text
★ 本檔刻意寫得很薄（design5.md D15）：所有規則（VLM 重試 3 次、PDF 逐頁、
  失敗清乾淨、冪等）都在入庫任務裡，這裡只負責「把零件組好、呼叫它」。
  所以測試可以直接呼叫那一支函式，不必啟動 Celery、不必有 Redis。

★ 增量六（Phase 78）起，呼叫的對象換成 app/services/gated_ingest.py 的
  run_gated_ingest_job：它會先問隱私閘門、再問遠端狀態，然後決定這一筆走
  本機（＝既有的 run_ingest_job，行為與增量五逐字相同）還是雲端（design6 D5）。
  本檔仍然只負責「組零件」——多組兩個而已（gate 與 cloud）。
```

- [x] ② import 區，把這兩行

```python
from app.services import staging_service
from app.services.ingest_job import run_ingest_job
```

換成一行

```python
from app.services import gated_ingest, staging_service
```

- [x] ③ `ingest_task` 的 docstring 裡兩處提到舊名字的地方改掉：

| 原文 | 改成 |
|---|---|
| `只做四件事：撈 job、依快照組零件、呼叫 run_ingest_job、結束。` | `只做四件事：撈 job、依快照組零件、呼叫 run_gated_ingest_job、結束。` |
| `是 run_ingest_job **內部**的迴圈。在這一層再加自動重試，會讓「已經 INSERT 成功的` | `是入庫任務**內部**的迴圈。在這一層再加自動重試，會讓「已經 INSERT 成功的` |

並在該 docstring 的最後補一段：

```text
    ★ gate 與 cloud 為什麼在這裡才拿（design6 D5、D10）：
      gate  ＝ 隱私閘門。**分類要在檔案出機房之前**，所以它必須由 worker 觸發，
              不能放進 HTTP 路徑（那會讓 202 變慢，而且 D5 明文禁止）。
      cloud ＝ 雲端路。CLOUD_ROUTE 預設 off，此時 get_cloud_route() 回一顆
              「永遠說遠端不可用」的替身，於是每一筆都走 fallback ＝ 增量五那條路。
      兩個都用 dependencies.xxx() **直接呼叫**（不是 Depends）——這裡不是 HTTP 請求，
      所以 pytest 靠 monkeypatch 那一管換掉它們（conftest 第四／五道安全網）。

    ★ 為什麼 gate 用 build_privacy_gate_for_backend(job["ai_backend"])，
      而不是 get_privacy_gate()——**與上面 vlm 那一行同一個理由**（D6、D14）：
      閘門的短問要跟頁首那顆「AI 模型：本機｜雲端」開關走，而 get_privacy_gate()
      讀的是 config.AI_BACKEND；worker 是另一個行程，它那份永遠是預設的 "local"。
      用它建的話，使用者撥到雲端時「看圖走雲端、閘門仍打本機」——**安靜地違反 D6**。
      入列當下已經把開關值抄進 job 了，閘門與看圖用同一份快照才對得起來。
      （AWS 那扇門不受這個影響：不管短問打哪裡，只有 NON_SENSITIVE 才進得了 S3。）
```

- [x] ④ 函式本體最後那段呼叫，把

```python
    run_ingest_job(
        job_id,
        store=store,
        vlm=dependencies.build_vlm_for_backend(job["ai_backend"]),
        embeddings=dependencies.get_embeddings(),
        now=dependencies.get_now,
    )
```

換成

```python
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=dependencies.build_vlm_for_backend(job["ai_backend"]),
        embeddings=dependencies.get_embeddings(),
        now=dependencies.get_now,
        gate=dependencies.build_privacy_gate_for_backend(job["ai_backend"]),
        cloud=dependencies.get_cloud_route(),
    )
```

> ⛔ **`gate=` 那一行不要寫成 `dependencies.get_privacy_gate()`**（裁決 R1）。
> 那樣做這一份計畫的測試會紅（`test_ingest_task把gate與cloud都傳進去` 斷言
> `收到參數 == ["cloud"]`），而正式環境裡的症狀是**安靜的**：頁首撥到雲端時，
> 看圖走 ollama.com、閘門卻還在打本機那顆——D6 說「閘門跟著開關走」。
> `get_privacy_gate()` 仍然有用，但它的使用者是 **web 行程與 pytest**，不是這裡。

> ⛔ **改完務必跑這一行**（`tests/integration/test_design5_error_paths.py::test_Celery任務也只吃job_id`
> 會掃這個檔案的原始碼，出現這四個字之中任何一個就紅）：
>
> ```bash
> grep -nE "bytes|base64|image_data|payload" app/celery_app.py || echo "OK：乾淨"
> ```
>
> 預期印 `OK：乾淨`。**寫註解時請用「位元組」三個中文字**，不要寫英文的那個字。

### - [x] 步驟 6：綠（3／3）——`tests/conftest.py` 讓 `跑完任務()` 走閘門版

- [x] 把這一行

```python
from app.services.ingest_job import run_ingest_job  # noqa: E402
```

換成

```python
from app.services.gated_ingest import run_gated_ingest_job  # noqa: E402
```

- [x] **`wire_fake_ai` 補上第二管，而且要蓋兩個名字（本 phase 才需要）。**
  Phase 74 掛 `get_privacy_gate` 時只用了 `dependency_overrides` 一管——那時沒有任何
  「直接呼叫」的地方，所以夠用。**本 phase 之後不夠了**：`celery_app.ingest_task`
  是把 `dependencies.build_privacy_gate_for_backend(...)` 當普通函式**直接呼叫**的，
  `dependency_overrides` 只在 FastAPI 解析 `Depends()` 時才被查表，攔不到它。
  少了第二管的症狀：跑到那一行時會建出真的 `OllamaPrivacyModel`（Phase 75）
  ——**pytest 有機會打到真的看圖模型**（本機 Ollama 或 ollama.com）。

  兩個名字都要蓋（裁決 R1）：`get_privacy_gate`（不吃參數，web 路徑與既有測試用）
  與 `build_privacy_gate_for_backend`（吃一個 `ai_backend` 參數，Celery 用）。
  後者的假件**收下參數就丟掉**——測試不在乎快照是什麼，只在乎「拿到的是假閘門」；
  真的要驗快照有沒有傳對的是 `tests/unit/test_celery_app_unit.py` 那一顆（它自己再蓋一次）。

  把 fixture 的參數列從 `def wire_fake_ai():` 改成 `def wire_fake_ai(monkeypatch):`，
  並把 Phase 74 加的那一行（長得像
  `app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.UNCERTAIN)`）
  換成**四行**：

```python
    # 第五道之外的雙管：ingest_task 是直接呼叫，dependency_overrides 攔不到它。
    # 三條路要拿到**同一顆**假閘門，測試才驗得出「誰問過閘門幾次」。
    假閘門 = FakePrivacyGate(Verdict.UNCERTAIN)
    app.dependency_overrides[get_privacy_gate] = lambda: 假閘門
    monkeypatch.setattr(dependencies, "get_privacy_gate", lambda: 假閘門)
    monkeypatch.setattr(dependencies, "build_privacy_gate_for_backend", lambda _: 假閘門)
```

- [x] 把 `目前注入的假件()` 整支換成：

```python
def 目前注入的假件() -> dict:
    """把測試現在掛在 dependency_overrides 上的假件挖出來，交給入庫任務。

    這是讓改寫變便宜的關鍵：既有測試那一行
        app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    **一個字都不必改**——它原本是給 router 用的，現在改成給任務用。

    注意 get_now 的取法不一樣：它的覆寫值本身就是 callable（FixedClock 實例），
    所以直接把那個物件交出去；get_vlm／get_embeddings 的覆寫值是「工廠」
    （lambda: FakeVLM(...)），要呼叫一次才拿得到物件。

    增量六（Phase 78）多回兩個零件：
      gate  ＝ 隱私閘門。wire_fake_ai 預設掛 FakePrivacyGate(Verdict.UNCERTAIN)
              ＝「不確定」＝走本機，所以**既有幾十顆用 跑完任務() 的測試行為零改變**。
      cloud ＝ 雲端路。第五道安全網 wire_fake_cloud 預設掛 CloudRouteOff()
              ＝ available() 恆為 False ＝ 永遠 fallback 本機。
    兩個都用 .get(注入點, 注入點) 取，理由與前三個一致（不必知道安全網是怎麼接的）。
    ⚠ 但 gate 這一條的退路**不安全**：安全網真的沒掛上時，get_privacy_gate() 會建出
      Phase 75 的 OllamaPrivacyModel ＝ 真的打模型。真正的主力是 wire_fake_ai 裡
      那兩行 monkeypatch（cloud 的退路 CloudRouteOff 則怎樣都不會連外）。
    """
    assert get_vlm in app.dependency_overrides, (
        "conftest 的 wire_fake_ai 應該已經把 get_vlm 換成假件了——"
        "沒有的話這裡會去打真的 Ollama（pytest 絕不打真模型）"
    )
    return {
        "vlm": app.dependency_overrides[get_vlm](),
        "embeddings": app.dependency_overrides[get_embeddings](),
        "now": app.dependency_overrides[get_now],
        "gate": app.dependency_overrides.get(get_privacy_gate, get_privacy_gate)(),
        "cloud": app.dependency_overrides.get(get_cloud_route, get_cloud_route)(),
    }
```

- [x] 把 `跑完任務()` 整支換成：

```python
def 跑完任務(job_id: str) -> None:
    """測試扮演 worker：把某一個 job 就地跑完（design5.md §9）。

    用的假件就是測試自己掛上去的那幾份，所以「這次看圖看得懂嗎」「時鐘停在哪一天」
    完全由測試決定，與正式路徑的 worker 用**同一支函式**。

    ★ 增量六（Phase 78）起呼叫的是 run_gated_ingest_job（與 Celery 任務同一支）。
      預設的閘門是「不確定」、預設的雲端路是「關掉的」，兩個加起來的結果
      就是「照舊呼叫 run_ingest_job」——**既有測試的行為一個字都沒變**。
      要測雲端路的測試不走這裡，它們自己組零件（見 tests/integration/test_gated_ingest.py）。
    """
    假件 = 目前注入的假件()
    run_gated_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=假件["vlm"],
        embeddings=假件["embeddings"],
        now=假件["now"],
        gate=假件["gate"],
        cloud=假件["cloud"],
    )
```

- [x] 檔頭的 `from app.dependencies import (...)` 要含 `get_cloud_route`（Phase 77 加的）
  與 `get_privacy_gate`（Phase 74 加的）。確認一下：

```bash
grep -n "get_cloud_route\|get_privacy_gate\|build_privacy_gate_for_backend" tests/conftest.py | head
```

預期：`get_cloud_route` 與 `get_privacy_gate` 都出現在 import 區（各至少一次），
外加 `wire_fake_ai` 裡那兩行 `monkeypatch.setattr(...)`。
`build_privacy_gate_for_backend` **不必**進 import 區——monkeypatch 是拿
「模組物件 ＋ 名字字串」換的（`dependencies` 已經 import 了），寫進 import 區只會多一個沒人用的名字。

### - [x] 步驟 7：跑測試，看它轉綠

```bash
pytest tests/integration/test_gated_ingest.py -v
```

預期最後一行：`8 passed`。

```bash
pytest tests/unit/test_celery_app_unit.py -v
```

預期：`6 passed`（既有 5 ＋ 本 phase 1）。

### - [x] 步驟 8：全量回歸 ＋ 格式檢查

```bash
pytest -q
```

預期：**開工基線 ＋ 9**（＝ 589），全綠、**0 skipped**。

⚠️ 這一步是本 phase 最關鍵的驗收：**既有 580 顆一顆都不准紅**。
`跑完任務()` 換了呼叫對象，等於幾十顆既有測試的入庫路徑都被動過一次——
它們仍然綠，才證明「預設閘門不確定 ＋ 預設雲端路關掉 ＝ 行為與增量五逐字相同」。

如果紅了，先看是哪一種：

| 症狀 | 多半是什麼 |
|---|---|
| 一大票測試都說 `NotImplementedError: Phase 79` | 預設閘門不是 UNCERTAIN（回去看 Phase 74 的 `wire_fake_ai`），或第五道安全網沒掛上（`CloudRouteOff` 的 `available()` 應該恆為 False） |
| `AttributeError: 'function' object has no attribute 'classify'` | `目前注入的假件()` 裡的 gate 忘了呼叫工廠（少了最後那對括號） |
| `TypeError: run_gated_ingest_job() got an unexpected keyword argument` | 簽章打錯字，對照步驟 4 的六個具名參數 |
| `tests/integration/test_design5_error_paths.py::test_Celery任務也只吃job_id` 紅 | `celery_app.py` 裡出現了 `bytes`／`payload`／`base64`／`image_data` 其中一個字（多半在你新寫的註解裡） |

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：`… files already formatted` ＋ `All checks passed!`。

### - [x] 步驟 8b：手動煙霧（真模型；**不進 pytest、不進 CI**）——量閘門短問到底多慢（★ 未做：由 controller 在 review 之後自己跑；本 phase 的實作者不執行真模型煙霧）

> ✅ **2026-09-01 controller 實測（dev overlay、CLOUD_ROUTE 預設 off、Ollama 0.33.2、合成收據圖 smoke-receipt.png）：**
> - 本機腿（開關＝本機）：`AI 開始 kind=privacy backend=local model=gemma4:e2b` → `AI 結束 … elapsed_s=99.6 ok=true`（首次呼叫含模型載入）→ `fallback=local reason=remote_unavailable` → `kind=vlm … elapsed_s=83.1` → `kind=embed backend=local … 47.3` → `入庫完成：photo_id=63`。202 到入庫共 218 秒。
> - 雲端腿（PUT ai-backend=cloud）：`kind=privacy backend=cloud model=gemma4 elapsed_s=0.7 ok=true` → `fallback=local reason=remote_unavailable` → `kind=vlm backend=cloud … 0.8` → `kind=embed backend=local … 0.5` → `入庫完成：photo_id=64`。共 6 秒。之後已把開關還原為本機。
> - 兩腿都證明：閘門用的是 job 的 `ai_backend` 快照（worker 行程的 config 是 local，log 卻印 `backend=cloud`＝裁決 R1／§10.2 S 生效）；契約字樣逐字命中；使用者觀感（202、面板、待決定多一張）與增量五相同。秒數已回填總覽 §8.6。


> 為什麼在本 phase：總覽 §10.2 追認項 **L** 把「閘門的 VLM 短問到底多慢」的**實測**
> 指定給本 phase 回填（Phase 75 做出真模型時沒排煙霧，因為那時沒有人呼叫閘門；
> 接線之後才真的跑得到）。**沒有任何環境變數要改**——閘門就是唯一實作，
> 要換後端就撥頁首那顆開關。跑兩次、抄兩個數字，就這樣。
> 需要 host 的 Ollama 在跑（`open -a Ollama`，等 4 秒再
> `curl -s http://127.0.0.1:11434/api/version`）、Docker 四個容器 Up。

> ⚠ **worker 沒有 `--reload`。** 常駐模式改完程式要
> `docker compose -f compose.yaml up -d --build` 才會跑到新碼；
> 開發 overlay 下也只有 app 會自己 reload，worker 要
> `docker compose -f compose.yaml -f compose.dev.yaml restart worker`。
> 忘了這一步的症狀：HTTP 已是新行為、log 裡卻一行 `kind=privacy` 都沒有，而且**不報錯**。

- [ ] 盯著 worker 的 log（分析都印在它那邊，不在 app）：

  ```bash
  docker compose -f compose.yaml -f compose.dev.yaml logs -f worker
  ```

- [ ] **第一趟：本機**（頁首開關維持預設的「本機」）。挑一張**真的**、內容**不敏感**的照片
  （菜單、風景、收據都行），用上傳頁 `https://localhost:8000/ui/upload.html` 傳，或：

  ```bash
  curl -sk -F "file=@$HOME/Desktop/IMG_4821.jpg;type=image/jpeg" https://127.0.0.1:8000/photos
  ```

  預期：`{"job_id": "…", "filename": "IMG_4821.jpg", "content_type": "image/jpeg"}`（202；照片**還沒**入庫）。

- [ ] worker log 預期依序出現（一次只傳一張——本機模型很慢而且不要並行，CLAUDE.md 的老規矩）：

  ```text
  AI 開始 kind=privacy backend=local model=<config.VLM_MODEL 的值>
  AI 結束 kind=privacy backend=local model=<…> elapsed_s=NN.N ok=true   ← ★ 抄這個數字
  job <job_id> route=local verdict=UNCERTAIN             ← 或 SENSITIVE
  job <job_id> fallback=local reason=remote_unavailable   ← 只有 verdict=NON_SENSITIVE 才走到這一行
                                                            （CLOUD_ROUTE 預設 off ⇒ 遠端恆為不可用）
  AI 開始 kind=vlm backend=local model=…                 ← 然後才是原本的看圖（64〜88 秒）
  ```

  > 📌 `route=local verdict=…` 與 `fallback=local reason=…` 是**兩條互斥的路**：
  > 前者是「敏感／不確定」，後者是「非敏感但遠端關著」。同一筆 job 只會看到其中一行。
  > 兩行都沒有 ＝ 接線沒生效（多半是 worker 還在跑舊碼，見上面的 ⚠）。

- [ ] **第二趟：雲端**（需要 `.env` 有 `OLLAMA_API_KEY`）。把頁首那顆「AI 模型：本機｜雲端」
  撥到**雲端**，再傳一張。log 應該變成：

  ```text
  AI 開始 kind=privacy backend=cloud model=<config.OLLAMA_CLOUD_VLM_MODEL 的值>
  AI 結束 kind=privacy backend=cloud model=<…> elapsed_s=N.N ok=true    ← ★ 抄這個數字
  ```

  `backend` 仍是 `local` 就是 D6 沒落地——多半是 `celery_app.py` 的 `gate=` 寫成了
  `get_privacy_gate()`（裁決 R1；worker 行程的 `config.AI_BACKEND` 永遠是 `local`）。
  撥回本機之後記得再確認一次開關的位置（開關是純記憶體的，重啟 app 一律回本機）。

- [ ] **把兩個 `elapsed_s` 連同日期回報給 controller**，由 controller 更新總覽
  **§8.6／§8.10** 與 **§10.2 追認項 L**（把「推估 20〜60 秒、雲端約 2 秒、未實測」換成實測值）。
  ⚠ **不要自己改總覽**——校準規則第 1 條：總覽層的問題寫進回報，不自己動手。

### - [x] 步驟 9：不 commit——記下快照

> ⚠ **產品負責人指示本次全程不 commit**（總覽 §7 鐵律 12：commit 節奏由他決定）。
> 本步驟只做兩件事：① 跑 §6 最後那條 `comm -13` 相減、確認新出現的檔恰好是那五列；
> ② 把下面這段 commit 訊息**留著備用**（等他指示時再貼），不要自己執行。

```bash
# ⛔ 未經產品負責人指示不要執行這兩行
cd /Users/linjunting/personalDocAI
git add app/services/gated_ingest.py app/celery_app.py tests/conftest.py \
        tests/integration/test_gated_ingest.py tests/unit/test_celery_app_unit.py
git commit -m "feat: Phase 78 閘門接線與 fallback 契約——新增 gated_ingest.run_gated_ingest_job（一進門標 analyzing、問閘門、privacy 與 route 寫進 JobStore；敏感與不確定一律走本機；遠端不可用或探測丟例外一律 fallback 並留 log fallback=local reason=remote_unavailable；route 已是 local 的崩潰重送不再問閘門）、celery_app.ingest_task 改呼叫它並多傳 gate（依 job 的 ai_backend 快照建，D6）與 cloud、conftest 的跑完任務改走閘門版，+9 tests；雲端成功路暫留 NotImplementedError（Phase 79 換掉），端點仍 22、對外行為零改變"
```

---

## 5. ASCII 圖

### 圖一：`run_gated_ingest_job` 的岔路口（★ ＝本 phase 落地的部分）

```text
   Celery 撿到一個 job_id
            │
            ▼
   job = store.get(job_id) ──── None ──► ★ log 一行、安靜 return（不可以炸掉 worker）
            │
            ▼
   ★ store.update(status="analyzing")     ← 先改狀態、才問閘門（面板不會卡在「排隊中」）
            │
            ▼
   job 裡已經有 route 了嗎？（崩潰重送才會有）
            │
            ├─ route == "local" ─► ★ 直接 run_ingest_job（**不再問閘門**，§2.1 禁止）
            │
            ├─ route == "cloud" ─►   Phase 80：先去 S3 看結果在不在
            │                        （本 phase 沒有人會寫 "cloud"，所以碰不到）
            ▼
   ★ verdict = gate.classify(filename=…, content_type=…, load_bytes=…)
   ★ store.update(privacy=verdict.value)
            │
            ├─ SENSITIVE  ─┐
            ├─ UNCERTAIN  ─┴─► ★ route=local
            │                  ★ log "route=local verdict=…"
            │                  ★ run_ingest_job ＝ 增量五那條路（一個位元組都不出門）
            ▼
        NON_SENSITIVE
            │
            ▼
   ★ cloud.available()？（例外也算「不可用」）
            │
            ├─ 否 ─► ★ route=local
            │        ★ log "fallback=local reason=remote_unavailable"
            │        ★ run_ingest_job
            ▼
            是
            │
            ▼
   ★ store.update(route="cloud")
   ★ log "route=cloud verdict=NON_SENSITIVE"   ← Demo 2 對帳的那一行，本 phase 就先印
            │
            ▼
   ⛔ raise NotImplementedError("Phase 79")   ← 本 phase 唯一的暫時分支（79 只換掉這一行）
      （正式路徑走不到：CLOUD_ROUTE 預設 off ⇒ CloudRouteOff.available() 恆 False）

   ┌────────────────────────────────────────────────────────────────────────┐
   │ 五條出口裡有四條都通往同一個地方：ingest_job.run_ingest_job()。         │
   │ 那正是重點——**退路是主線，雲端才是例外。**                             │
   │ EC2 平常是 Stop 的，所以第四條（fallback）才是日常會走的那一條。        │
   └────────────────────────────────────────────────────────────────────────┘
```

### 圖二：接線前後，誰呼叫誰

```text
  增量五（Phase 65〜72）                    增量六（本 phase 之後）
  ─────────────────────                    ─────────────────────────
  celery_app.ingest_task                   celery_app.ingest_task
        │                                        │
        │ 組 4 個零件                             │ 組 6 個零件（多 gate、cloud）
        ▼                                        ▼
  ingest_job.run_ingest_job          gated_ingest.run_gated_ingest_job
   （看圖→向量→INSERT→存檔）                 │
                                             ├─ 敏感／不確定 ─────┐
                                             ├─ 遠端不可用 ───────┤
                                             │                    ▼
                                             │      ingest_job.run_ingest_job
                                             │        （一個字都沒改）
                                             └─ 非敏感＋遠端可用 ─► Phase 79 的雲端路

  tests/conftest.py 的 跑完任務()                 tests/conftest.py 的 跑完任務()
        └─► run_ingest_job                            └─► run_gated_ingest_job
                                                 （預設閘門「不確定」＋雲端路「關掉」
                                                   ⇒ 實際上還是走到 run_ingest_job，
                                                   所以既有幾十顆測試行為零改變）
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` 記下顆數（預期 580）

- [x] **新模組的七個名字都在**（4 個 reason 常數 ＋ 3 支函式）

  ```bash
  grep -nE "^REASON_|^def run_gated_ingest_job|^def _遠端可用嗎|^def _退回本機路" \
    app/services/gated_ingest.py
  ```

  預期：7 行命中（4 個 reason 常數 ＋ 3 支函式）

- [x] **雲端那條的兩行契約已就位、暫時分支恰一處**（Phase 79 接手時只換 raise）

  ```bash
  grep -nE '^ +(store\.update\(job_id, route="cloud"\)|logger\.info\("job %s route=cloud verdict=%s"|raise NotImplementedError\("Phase 79"\))' \
    app/services/gated_ingest.py
  ```

  預期：**恰 3 行**，順序是 update → log → raise（三行緊鄰，中間只隔註解）

- [x] **`gated_ingest.py` 零 SQL、零 boto3**

  ```bash
  grep -nE "boto3|psycopg|cursor\(|\.execute\(" app/services/gated_ingest.py || echo "OK：乾淨"
  pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：印 `OK：乾淨` ＋ `1 passed`

- [x] **`ingest_job.py` 一個字都沒改**（它是 fallback 的目的地）

  ```bash
  shasum -c /tmp/p78-ingest_job.sha
  ```

  預期：`app/services/ingest_job.py: OK`（與 §2 的快照逐位元相同）。
  不用 `git diff`：Phase 76 的重構若還沒 commit，`git diff` 會把 76 的改動一起印出來，看起來像本 phase 動了它。

- [x] **Celery 那一層還是只吃 `job_id`，而且沒有位元組字樣**

  ```bash
  grep -nE "bytes|base64|image_data|payload" app/celery_app.py || echo "OK：乾淨"
  pytest tests/integration/test_design5_error_paths.py::test_Celery任務也只吃job_id \
         tests/integration/test_design5_error_paths.py::test_任務本體只吃job_id不吃影像位元組 -q
  ```

  預期：印 `OK：乾淨` ＋ `2 passed`

- [x] **契約 log 字樣真的會出現**（不要只信測試，自己看一次）

  ```bash
  pytest tests/integration/test_gated_ingest.py -k 遠端關閉 -o log_cli=true -o log_cli_level=INFO -q 2>&1 | grep "fallback=local"
  ```

  預期：至少一行含 `fallback=local reason=remote_unavailable`

- [x] **新測試 9 顆全綠**

  ```bash
  pytest tests/integration/test_gated_ingest.py tests/unit/test_celery_app_unit.py -v
  ```

  預期：`14 passed`（8 ＋ 6）

- [x] **全量 pytest 顆數 ＝ 開工基線 ＋ 9**

  ```bash
  pytest -q
  ```

  預期：`589 passed`、**0 skipped**、既有測試**零紅**

- [x] **端點仍 22、openapi 零 DELETE**

  ```bash
  pytest tests/integration/test_ask_three_paths.py::test_端點數不變 \
         tests/integration/test_nav_header.py::test_端點數仍為22 \
         tests/integration/test_design5_error_paths.py::test_端點恰好是這22支 -q
  ```

  預期：`3 passed`

- [x] **零依賴實證（顆數必須完全一樣）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

  預期：`589 passed`

- [x] **專案的 `data/` 沒被弄髒**

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都沒有輸出

- [x] **git 收尾（與 §2 快照相減；總覽 §7 鐵律 12）**：本次**不 commit**（步驟 9），只核對

  ```bash
  comm -13 <(sort /tmp/p78-before.txt) <(git status --short -- app tests deploy | sort)
  ```

  `comm -13` ＝ 把「開工前就已經在」的行藏起來，只印**本 phase 新出現的**。預期恰為下面這幾列
  （` M` ＝ 改了既有檔、`??` ＝ 新檔）：

  ```text
   M app/celery_app.py
   M tests/conftest.py
   M tests/unit/test_celery_app_unit.py
  ?? app/services/gated_ingest.py
  ?? tests/integration/test_gated_ingest.py
  ```

  ⚠ 74〜77 還沒 commit 的話，` M tests/conftest.py` 那一列**開工時就在快照裡**（74／77 都動過它），
  會被 `comm` 藏掉——少了它是正常的；其餘四列一定要在。多出任何別的檔名都要追。

---

## 7. 常見陷阱

1. **先問閘門、才把 status 改成 `analyzing`。**
   順序錯了 pytest 也會全綠（假閘門是瞬間的），但真跑起來時閘門要看一次圖
   （本機推估 20〜60 秒），面板上那一列會一直停在「排隊中」，使用者以為系統當掉。
   `test_一進門status就變analyzing` 就是專門擋這個的——它用一個「被問時偷看狀態」的
   假閘門，所以順序寫反一定會紅。

2. **`load_bytes` 先讀好再傳進去（傳 `staging_service.read_staging(...)` 的結果，
   或寫成 `load_bytes=lambda: 已經讀好的位元組`）。**
   壞在兩個地方：① staging 檔不在時，例外會從 `run_gated_ingest_job` 這一層飛出去，
   而契約說那要變成 `UNCERTAIN`（Phase 74 的 `test_讀檔失敗回UNCERTAIN` 把它釘在閘門裡）；
   ② `route` 已是 `local` 的崩潰重送根本不問閘門，卻仍白讀一次磁碟。
   一定要傳「還沒執行的那個 lambda」，讓閘門自己決定什麼時候讀、讀壞了怎麼算。

3. **`_遠端可用嗎()` 沒有把例外吃掉。**
   `FakeCloudRoute(RuntimeError(...))` 那一顆會紅，而真實世界的症狀更糟：
   AWS 憑證過期的那一天，**每一張非敏感照片都會變成進度面板上的一列紅字**
   ——而 design6 §0 禁止第 6 條明文說「遠端不可用時不准讓使用者重傳」。

4. **`celery_app.py` 寫成 `from app.services.gated_ingest import run_gated_ingest_job`。**
   `test_ingest_task把gate與cloud都傳進去` 會紅而且訊息很難懂（`收到` 是空的）。
   原因是**早綁定**：那個名字在 import 當下就指向舊的函式物件，
   之後 monkeypatch 模組屬性換不掉它。一律寫 `gated_ingest.run_gated_ingest_job(...)`。

5. **在 `celery_app.py` 的新註解裡寫了英文的 "bytes"（或 payload／base64／image_data）。**
   `test_Celery任務也只吃job_id` 是**掃原始碼字串**的，不管你寫在註解還是程式碼裡，
   一律紅。而且錯誤訊息只說「不可以碰位元組」，讓人以為是程式邏輯出問題。
   **註解一律寫中文的「位元組」。**

6. **fallback 的時候忘了寫 `route="local"`。**
   本 phase 的測試會抓到（`test_非敏感但遠端關閉…` 有斷言），但真正的代價在 Phase 79 之後：
   任務被殺掉、佇列重送時，那一筆會**再問一次閘門、再送一次雲端**——
   工人白做一次、S3 多一份垃圾，而且違反 §2.1 的禁止。

7. **以為改了 `跑完任務()` 就得把 `tests/fakes.py` 的 `EagerDispatcher` 也一起改。**
   不必，而且不要改。它是給「POST 完照片就要在資料庫裡」的測試用的，走本機路正是那些
   測試要的東西。改了只會讓它們無故多繞一圈閘門，一點好處都沒有。

8. **`verdict is not Verdict.NON_SENSITIVE`（用 `is not` 而不是 `!=`）。**
   `Verdict` 是 `StrEnum`，成員之間用 `is` 比對本身沒錯；但假件或未來的模型版若回傳
   **純字串** `"NON_SENSITIVE"`，`is not` 會是 True → 明明是非敏感卻走本機。
   用 `!=` 兩種都對（`StrEnum` 的成員與同值字串相等），語意也更寬容。

9. **驗收時 `git status` 印出一大堆不是自己改的檔（`fakes.py`、`privacy_gate.py`、`cloud_ingest.py`…），以為自己弄壞了什麼。**
   總覽 §7 鐵律 12：各 phase 做完**不會**馬上 commit，所以 74〜77 的成果都還躺在工作區。
   正解是 §2 開工前先照快照、§6 用 `comm -13` 相減——只看「本 phase 新出現的」那幾列。
   同理 `git diff app/services/ingest_job.py` 會印出 Phase 76 的重構，不代表本 phase 動了它；
   用 `shasum -c` 比對 §2 存下的雜湊才準。

10. **`gate=` 寫成 `dependencies.get_privacy_gate()`（裁決 R1）。**
    這是本 phase 最容易手滑、而且**壞得最安靜**的一處：`get_privacy_gate()` 讀的是
    `config.AI_BACKEND`，而 worker 是另一個行程、它那份永遠是預設的 `"local"`。
    於是使用者把頁首撥到雲端時，看圖走 ollama.com、閘門卻還在打本機那顆——違反 D6，
    而且**沒有任何錯誤訊息**，只有 log 裡那行 `kind=privacy backend=local` 露了餡。
    正解是 `dependencies.build_privacy_gate_for_backend(job["ai_backend"])`，
    與上面 `vlm=dependencies.build_vlm_for_backend(job["ai_backend"])` 完全同一個理由（D14 的快照）。
    `test_ingest_task把gate與cloud都傳進去` 斷言 `收到參數 == ["cloud"]` 就是擋這個。

11. **步驟 8b 煙霧時，worker log 裡一行 `kind=privacy` 都沒有，以為閘門壞了。**
    先查 worker 是不是還在跑舊碼——**Celery 沒有 `--reload`**，常駐模式要
    `docker compose -f compose.yaml up -d --build`、開發 overlay 下要
    `restart worker`（改 `app/` 的 .py 只有 app 會自己 reload）。
    症狀正是「HTTP 行為已經是新的、分析卻還是舊行為，而且完全不報錯」。
    第二個常見原因：host 的 Ollama 沒開——`Errno 101 Network is unreachable`
    先查 `open -a Ollama`，不要去查 Docker 網路。

---

## 8. 完成後的專案狀態

系統多了一個岔路口：

- `app/services/gated_ingest.py`（新）：`run_gated_ingest_job()` ＋ 兩支私有小工具 ＋
  四個 `REASON_*` 常數（其中兩個要到 79／80 才用到，先定義好，讓契約集中在一個地方）。
  雲端那一條已經寫到 `route=cloud` ＋ 契約 log，只剩最後一行 `raise` 等 Phase 79 換成真的送出。
- `app/celery_app.py`：`ingest_task` 改組**六個**零件、呼叫 `run_gated_ingest_job`；
  `gate` 與 `vlm` 都用同一份快照 `job["ai_backend"]` 建（裁決 R1 ＝ D6 在 worker 行程的落地）。
- `tests/conftest.py`：`wire_fake_ai` 的第二管同時蓋住 `get_privacy_gate` 與
  `build_privacy_gate_for_backend`（同一顆假閘門）；`跑完任務()` 也走同一支
  （所以測試與正式路徑仍然是同一條路）。

**對外行為零改變**：`CLOUD_ROUTE` 預設 `off` ⇒ `CloudRouteOff.available()` 恆為 `False`
⇒ 每一張非敏感照片都走 fallback ⇒ 與增量五**逐字相同**。
端點仍 **22**、`openapi.json` 仍零 DELETE、`photo` 表零改動、前端零改動。

**design6 §8 錯誤表已經釘住三列**：第 1 列（敏感／不確定）、第 2 列（EC2 Stop）、
第 3 列（沒有 AWS 憑證）。剩下第 4 列（送出失敗，Phase 79）與第 5／6 列（逾時與重送，Phase 80）。

**留給下一個 phase 的接口**（Phase 79 會用到，名字逐字沿用）：

| 名字 | 在哪裡 | Phase 79 怎麼用 |
|---|---|---|
| `run_gated_ingest_job(job_id, *, store, vlm, embeddings, now, gate, cloud)` | `app/services/gated_ingest.py` | 簽章**不再變**；79／80／81 只補分支 |
| `REASON_SUBMIT_FAILED`／`REASON_RESULT_TIMEOUT`／`REASON_REDELIVERED_WITHOUT_RESULT` | 同上 | 79 用第一個、80 用後兩個 |
| `_退回本機路(job_id, reason, *, store, vlm, embeddings, now)` | 同上 | 79／80 的每一條 fallback 都呼叫它 |
| `_遠端可用嗎(cloud, job_id)` | 同上 | 不變 |
| `store.update(job_id, route="cloud")` ＋ `logger.info("job %s route=cloud verdict=%s", …)` | 同上（`raise NotImplementedError` 的前兩行） | 79 **不動這兩行**，直接在它們後面接 `cloud.submit(...)`、把 raise 換掉 |
| `記得最後一筆的Store`／`建一個job`／`跑` | `tests/integration/test_gated_ingest.py` | 79／80 追加的測試直接用 |

下一步：**Phase 79** 寫 `CloudRoute` 的本體（`available`／`submit`／`fetch_result`／
`wait_result` 基本版／`cleanup`），並**換掉本 phase 那一行 `NotImplementedError`**，
讓「非敏感 ＋ 遠端開著」真的把單圖送出去、把結果拉回來落庫。

測試累計 ＝ 開工基線 ＋ **9**（總覽 §9：589）。端點 **22**（不變）。
**與總覽 §2.7 一顆不多、一顆不少**——R1 要求的「閘門用的是快照」是加在
`test_ingest_task把gate與cloud都傳進去` 裡的兩行斷言，沒有另開新的一顆。

> 📌 **2026-09-01 實作實查：開工基線 582、做完 591**（本檔各處寫的 580／589 是
> 總覽 §9 的舊累計數字；Phase 75 實作時依 controller 裁決 **R10** 多補了 2 顆，
> 所以之後每個 phase 的**絕對值一律 +2**。**本 phase 新增仍然恰好 +9**，
> 與總覽 §2.7 一顆不差——要對的是「+9」，不是絕對值。）

**要回報給 controller 的一件事**：步驟 8b 量到的兩個 `elapsed_s`（本機／雲端），
由 controller 更新總覽 §8.6／§8.10 與 §10.2 追認項 L——本檔與實作者都**不改總覽**。

---

## 附：本文件引用的官方文件

- [Celery 任務的呼叫與 `.delay()`](https://docs.celeryq.dev/en/stable/userguide/calling.html)
- [Celery 設定表（`result_backend` 預設沒有）](https://docs.celeryq.dev/en/stable/userguide/configuration.html)
- [pytest `caplog`（抓 log 來斷言）](https://docs.pytest.org/en/stable/how-to/logging.html)
- [pytest `monkeypatch.setattr`（換掉模組屬性，測試結束自動還原）](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- [Python `logging` 的 `%s` 延後格式化與 `exc_info=True`](https://docs.python.org/3/library/logging.html#logging.Logger.warning)
- [Python `enum.StrEnum`（成員與同值字串相等）](https://docs.python.org/3/library/enum.html#enum.StrEnum)

---

## 9. 實作紀錄（2026-09-01，實作 subagent 補記）

**與本文件的唯一差異：多改了一個檔 `tests/unit/test_privacy_gate_unit.py`（Phase 75 的測試檔），各加一行、斷言一字未改。**

步驟 6 照本文件把 `wire_fake_ai` 的第二管接上（雙名 monkeypatch）之後，全量出現
**2 紅**：`test_get_privacy_gate回VlmGate` 與 `test_get_privacy_gate跟AI_BACKEND走`。

原因（本文件沒預見）：`dependencies.get_privacy_gate()` 的函式體是
`return build_privacy_gate_for_backend(config.AI_BACKEND)`——那是一次**模組全域查表**。
那兩顆測試雖然是 `from app.dependencies import get_privacy_gate` 早綁定拿到**原件**，
但原件一被呼叫就會去查已經被 monkeypatch 換成假閘門的 `build_privacy_gate_for_backend`，
於是 `isinstance(…, VlmGate)` 拿到 `FakePrivacyGate` 而翻紅。
（`build_privacy_gate_for_backend("cloud")` 那兩行**沒有**受影響——早綁定拿到的是原件本身。）

修法（最小、且不動任何斷言）：那兩顆各加一行，把真的建構函式先裝回去再驗——

```python
    monkeypatch.setattr(
        "app.dependencies.build_privacy_gate_for_backend", build_privacy_gate_for_backend
    )
```

這樣兩顆測試的**意圖完全保留**（仍然是在驗 `get_privacy_gate()` 真的回 `VlmGate`、
真的跟 `config.AI_BACKEND` 走），而第二管安全網對 `celery_app` 那條直接呼叫的路
仍然生效。**請 controller 追認**：dispatch 原本要求「不動 74〜77 的測試內容」，
這是 R1 的雙名 monkeypatch 與 Phase 75 既有測試之間的真衝突，兩者不可能都不動。

**顆數**：開工基線 582 → 做完 **591**（+9，與總覽 §2.7 一顆不差）、0 skipped、
warning 只有基線那一個 StarletteDeprecationWarning。
`shasum app/services/ingest_job.py` 與開工前逐位元相同。
**步驟 8b 的真模型煙霧未做**（由 controller 在 review 之後自己跑）。
