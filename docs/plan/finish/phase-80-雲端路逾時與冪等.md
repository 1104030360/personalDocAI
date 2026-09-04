# Phase 80：雲端路的逾時與冪等

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**順手做的三件事：
> ① 不要碰 boto3／不要打任何 `aws` 指令（★G1 還沒過）；
> ② 不要為了「兩筆任務互相收到對方的結果」去開第二條 results 佇列或改用 FIFO
> （那是 design6 §1.2 已經定調的方向：Standard Queue ＋ 冪等）；
> ③ 不要做 PDF（那是 Phase 81）。

> 🎯 **一句話目標：** 把 `wait_result()` 補成**完整的五條規則**（總覽 §2.5），
> 再補上「崩潰重送而且 `route` 已經是 `cloud`」的兩條分支，
> 讓「等不到結果」「收到別人的結果」「同一筆被送兩次」三種情況全部有明確的行為與測試。

**為什麼要做這個：**

Phase 79 讓順利的那一圈通了。但雲端這條路上，**不順利才是常態**：

| 會發生什麼 | 為什麼會發生 | 沒處理的話 |
|---|---|---|
| 等不到結果 | 工人掛了、EC2 在半路被 Stop、訊息被別人吃掉 | 那一筆會**永遠卡在 analyzing**，照片再也不會出現 |
| 收到**別人的**結果訊息 | results 佇列是**共用的**——兩筆同時在等，A 一定會收到 B 的訊息 | A 把 B 的訊息吃掉並刪除 ⇒ B 等到逾時、白白 fallback 一次 |
| 同一筆被處理兩次 | SQS 是 **at-least-once**（保證至少送一次，可能送兩次以上） | 同一張照片**被插進資料庫兩次**（而且本專案沒有刪除照片的功能） |

這三件事對應 design6 的 D10、D17 與總覽 §8.9。本 phase 全部補完。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **at-least-once（至少送一次）** | SQS Standard Queue 的保證：一則訊息**至少**會被送到一次，但**可能送兩次以上**。所以收訊息的人必須**冪等**（design6 D17） |
| **冪等（idempotent）** | 「做兩次跟做一次結果一樣」。本專案的做法是先看 `job["photo_ids"]`：已經有照片 id 了就直接收尾，不再插一次 |
| **deadline（期限）** | 「最晚做到幾點」。本專案是 `_now() + CLOUD_RESULT_TIMEOUT_SECONDS`（預設 300 秒）。長輪詢一次最多 20 秒，所以要在外面自己數 |
| **可見度逾時（visibility timeout）** | 一則訊息被拿走之後會「隱形」一段時間。這段時間內拿走的人要嘛刪掉它、要嘛就會讓它重新出現給別人 |
| **殘訊息（orphan message）** | 「已經沒有人在等」的結果訊息（那一筆早就做完、被關掉、或已經 fallback 了）。留著它只會在下一筆任務等結果時一直冒出來 |
| **`release`（還回佇列）** | 用 receipt handle 把可見度改成 **0**，那則訊息立刻重新出現給別人收。本專案在「收到別人的訊息、而那一筆還在等」時就是這樣做的 |
| **時間接縫（`_now`／`_sleep`）** | Phase 79 建立的兩支模組層函式。測試 monkeypatch 它們，就能「假裝過了 5 分鐘」而不必真的等 5 分鐘 |
| **凍結時鐘 vs 會走的時鐘** | 測試接管 `_now()` 的兩種方式，本 phase 各給一支 helper。**凍結**＝`假裝過了(monkeypatch, 秒數)`：撥到「現在＋秒數」之後就停住不動，給「問一次 → 撥時間 → 再問一次」這種單點判斷用（Phase 89 的 TTL 快取；`tests/unit/test_camera_session_unit.py` 的同名 helper 也是這個語意）。**會走**＝`讓時鐘一直走(monkeypatch, 每次秒數)`：每問一次就再過 每次秒數 秒，給 `wait_result` 這種「迴圈到 deadline」的測試用。拿錯的症狀見 §7 陷阱 1、9 |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D10 遠端關掉＝fallback** | 「已送出，但在逾時內 results 佇列沒有該 `job_id`」也算不可用 | `wait_result` 回 `None` → `cleanup` → `_退回本機路(REASON_RESULT_TIMEOUT)` |
| **D17 SQS at-least-once** | worker 與本機收結果都必須冪等；同一 `job_id` 不得 INSERT 兩張 | `_用雲端結果落庫` 的 `photo_ids` 檢查（Phase 79 已寫）＋ 本 phase 的重送分支與兩顆測試 |
| **§2.1 第 4 條** | 已送出但逾時沒有結果 → fallback；若已寫到 S3／SQS：**盡力刪物件、刪訊息** | `cleanup` 在每一條 fallback 之前先跑；殘訊息在 `wait_result` 裡順手清掉 |
| **§2.3** | results 佇列由本機 Receive／Delete；長輪詢 `WaitTimeSeconds` 上限 20 秒 | 規則 1 的 `_等幾秒()` 與規則 2 的 `delete_result_message`。**`ChangeMessageVisibility`（`release_result_message`）是計畫層補的**——design6 §2.3 沒寫，出處是總覽 §2.5 第 3 條與 §10.1 追認項 d |
| **§8 錯誤表第 5 列** | 已送雲端、逾時無 results 訊息 → fallback；冪等避免雙 INSERT | `test_逾時沒有結果_fallback本機且log有reason_result_timeout`、`test_逾時fallback之前會先清掉S3物件` |
| **§8 錯誤表第 6 列** | SQS 重送、本機已入庫 → 略過 | `test_同一個job_id的結果送兩次_照片仍然只有一列` |
| **§9 必釘第 6 條** | 已 INSERT 再送一次同 `job_id` result → 列數仍 1 | 同上 |
| **§4 資料流與冪等** | Fallback 與雲端路**不可兩路都 INSERT** | 兩條路各自先看 `photo_ids`：雲端路＝`_用雲端結果落庫` 的第一件事（`test_同一個job_id的結果送兩次_照片仍然只有一列`）；本機路＝既有 `run_ingest_job`（`test_ingest_job.py::test_崩潰重送_job已有photo_ids再跑一次_列數仍為1`，Phase 76 重構後仍綠）。崩潰重送 route=cloud 但結果不在 → 退回本機走的就是後者，所以不會第二次 INSERT |
| **總覽 §10.2 R** | 雲端路落庫順序固定為 INSERT → 立刻 `store.update(job_id, photo_ids=[photo_id])` → `cleanup` → `finish_image_job` | `_用雲端結果落庫` 第 ⑤／⑥ 步（Phase 79 修訂版同款，本 phase 整檔重貼帶著）；`test_崩潰重送route是cloud而且S3有結果_直接落庫零submit` 用同一本流水帳斷言「寫 photo_ids 在 `delete_objects` 之前」 |
| **總覽 §2.5 的五條規則** | `wait_result` 的完整規格 | 本 phase 的主角（§4 步驟 4） |
| **總覽 §8.9** | results 佇列是共用的，會收到別人的訊息 | `_處理別人的訊息()`：還在等 → 還回去；沒人等 → 刪訊息＋清 S3 |
| **總覽 §10.1 追認項 d** | 收到別人的 `job_id` 要「還回去或當殘訊息刪掉」 | 同上（三顆單元測試逐條釘） |
| **總覽 §10.1 追認項 c ＋ §8.8** | 「等 results」是在**同一個 Celery 任務裡**同步長輪詢，佔一個 concurrency 名額（`--concurrency=2` ⇒ 最多兩筆同時在等），但不佔 GPU／CPU | 本 phase 不改這個做法：`wait_result()` 仍然是 `run_gated_ingest_job` 直接呼叫的阻塞迴圈。手動煙霧嫌卡就調小 `CLOUD_RESULT_TIMEOUT_SECONDS`（Phase 86 用 30 秒） |

---

## 2. 前置條件

**要先做完的 phase：74〜79 全部（依序）。** 本 phase 直接改 79 寫的那兩個檔
（`cloud_ingest.py` 與 `gated_ingest.py`），並沿用 78 的整合測試 helper
（`記得最後一筆的Store`／`建一個job`／`跑`）與 79 的假件（`有工人的信箱`／`雲端路`／`收據理解`）。

**★G1 還沒到**：全程零 AWS。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db 與 redis 要 Up (healthy)
pytest -q
```

預期：`599 passed`、0 skipped（總覽 §9；**2026-09-01 實查 602**——R10／R13 共多 3 顆）。**以實查數字為準**，本文稱它「**開工基線**」，
底下所有顆數一律寫成「基線 ＋ N」。

> ⚠️ 基線有可能是 **600**：controller 裁決 R1（D6 在 worker 行程的落地）要求 Phase 78 多釘一顆
> 「閘門是用 job 的 `ai_backend` 快照建的」。78 若是用**新加一顆**（而不是在既有那顆多加一個斷言）
> 的方式做，基線就是 600、本 phase 做完是 610。**兩個數字都不算錯**——
> 對帳看的是「跑完之後恰好比開工基線多 10」，不是那個絕對值。

確認 Phase 79 的兩個時間接縫真的在（本 phase 的測試全靠它們）：

```bash
python -c "
from app.services import cloud_ingest
print('接縫：', cloud_ingest._now, cloud_ingest._sleep)
print('現在的時基：', round(cloud_ingest._now(), 1))
"
```

預期：印出兩個函式與一個數字。

> ⚠️ **絕對不要同時跑兩份 pytest。**

---

## 3. 範圍

### 做

1. **`app/services/cloud_ingest.py`**：
   - `wait_result()` 補成**完整五條規則**（總覽 §2.5）
   - 新增私有方法 `_處理別人的訊息()`（規則 3：還回去 or 當殘訊息刪掉＋清 S3）
   - `_now()` 的 docstring 補一句：**Phase 89 的 `Ec2Probe` 會共用同一支**，不要再建第二個
2. **`app/services/gated_ingest.py`**：
   - 新增 `route == "cloud"` 的崩潰重送分支（`_繼續雲端路()`）；它在落庫前**重新 `store.get(job_id)`**
     一次（D17 的最後一道保險——`run_gated_ingest_job` 開頭那份 job 是複本，
     `--concurrency=2` 時兩個子行程撿到同一筆會看不到對方剛寫的 `photo_ids`）
   - 新增 `_盡力清雲端()`，並把 Phase 79 那七處 `cloud.cleanup(job_id)` 全部改走它
     （理由：重送分支拿到的 `cloud` **有可能是 `CloudRouteOff`**——使用者半路把
     `CLOUD_ROUTE` 改回 `off`——那一顆的每一支方法都會丟 `RuntimeError`）
   - 落庫順序改為 **INSERT → 立刻寫 `photo_ids` → 清 S3 → 收尾**（總覽 §10.2 R；Phase 79 的
     修訂版也是這個順序，整檔重貼要帶著）；`_理解()` 改用 `PhotoUnderstanding.model_validate()`
3. **`tests/unit/test_cloud_ingest_unit.py`** 追加 5 顆；
   **`tests/integration/test_gated_ingest.py`** 追加 5 顆。
   前者同時放進**兩支語意相反的時鐘 helper**：`假裝過了`（**凍結**，Phase 89 的 TTL 測試沿用）與
   `讓時鐘一直走`（**會走**，本 phase 所有 `wait_result` 測試用）；後者只留 `讓時鐘一直走`。
4. **controller 裁決 R14（2026-09-01，Phase 79 review 的 Minor 升級為本 phase 的做項）**：
   `gated_ingest.py` 呼叫 `cloud.wait_result(job_id, store=store)` 那一行要**包 `try/except Exception`**——
   真 `AwsMailbox.receive_result`／`get_object` 在網路抖動時會丟例外，目前會一路飛到 `celery_app.ingest_task`
   （那裡沒有 try、也沒有 autoretry），結果是 job **永遠卡在 analyzing**、staging 與 S3 都留著、面板不會出現失敗列。
   處理方式：`logger.warning("job %s：等雲端結果時信箱出錯，當作逾時", job_id, exc_info=True)`，然後**視為 `None`**
   → 走既有的 `result_timeout` 那條（`_盡力清雲端` ＋ `fallback=local reason=result_timeout`）。
   對應**加 1 顆** `tests/integration/test_gated_ingest.py::test_等結果時信箱丟例外_fallback本機而且清乾淨`
   （信箱的 `receive_result` 被 monkeypatch 成丟 `RuntimeError`；斷言照片仍入庫一列、job 被刪、caplog 有
   `fallback=local reason=result_timeout`、`delete_objects` 被呼叫）。**本 phase 因此為 +11（總覽 +10）**，§8 要明寫。
5. **順手修一處註解（Phase 79 review Minor 3）**：`_理解()` 的說明寫「`model_validate` 會驗多餘鍵」不正確——
   `PhotoUnderstanding` 沒設 `extra="forbid"`，Pydantic v2 預設**忽略**多餘鍵。整檔重貼時把那句改成
   「驗型別與必填欄；多餘鍵會被忽略（沒設 extra="forbid"）」。不改行為。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 每個 job 開一條自己的 results 佇列 | 佇列數量會無上限成長（而且要自己清）。總覽 §8.9：收到別人的訊息是 Standard Queue 的**本質**，不是 bug |
| 改用 FIFO 佇列 | 又貴又慢，而且 FIFO 解的是「順序」問題，不是「共用」問題。design6 §2.3 明訂兩條都是 Standard |
| 用 `HeadObject` 輪詢 S3 當完成訊號 | design6 §1.2 **已否決**（方案 A）。`fetch_result()` 只在崩潰重送時問**一次**，那不是輪詢 |
| 讓 `wait_result` 在收到別人的訊息時「順便幫它落庫」 | 那會讓兩個 Celery 子行程同時寫同一筆 job，而且完全無法推理。**還回去**就好 |
| 為了逾時而縮短 `CLOUD_RESULT_TIMEOUT_SECONDS` 的預設值 | 300 秒是總覽 §2.4.2 定的。手動煙霧要快就在 `.env` 調（Phase 86 用 30 秒） |
| 崩潰重送時再 submit 一次 | 上一趟送出去的東西還在 S3／佇列裡，工人可能正在做。再送一次＝工人白做一次＋S3 多一份垃圾 |
| PDF 的雲端路 | Phase 81 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並**真的跑它、親眼看到紅**。

### - [x] 步驟 1：先寫測試（紅）——`tests/unit/test_cloud_ingest_unit.py` 追加 5 顆

- [x] 檔頭 import 區補**兩行**（照字母順序）：

```python
from app.services import cloud_ingest
from app.services.ingest_job_store import InMemoryJobStore
```

  補完之後，那一段的 `app.*` 應該長這樣（`from app.services import cloud_ingest` 要在
  `from app.services.cloud_ingest import (...)` **前面**——ruff 的 isort 是照模組路徑排的）：

```python
from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route
from app.main import app
from app.services import cloud_ingest
from app.services.cloud_ingest import (
    ROUTE_OFF_MESSAGE,
    AlwaysRunning,
    CloudRoute,
    CloudRouteOff,
    build_context,
)
from app.services.ingest_job import PromptContext
from app.services.ingest_job_store import InMemoryJobStore
from tests.fakes import FakeMailbox, FakeProbe
```

  > ⚠️ 少了 `from app.services import cloud_ingest` 這一行，兩支時鐘 helper（`假裝過了()`／`讓時鐘一直走()`）裡的
  > `monkeypatch.setattr(cloud_ingest, "_now", …)` 會直接 `NameError`
  > ——Phase 79 的 import 區只從那個模組**挑名字**，沒有把模組本身帶進來。

- [x] 在檔案**最後面**加上：

```python


# ------------------- ⑥ wait_result 的五條規則（Phase 80）-------------------
#
# 兩支時鐘 helper，語意**相反**，別拿錯：
#   假裝過了(monkeypatch, 秒數)          凍結時鐘——撥到「現在＋秒數」之後就停在那裡不動。
#                                        給「單點判斷」用：問一次 → 撥 61 秒 → 再問一次（Phase 89 的 TTL 快取）。
#   讓時鐘一直走(monkeypatch, 每次秒數)   會走的時鐘——每問一次就再過 每次秒數 秒。
#                                        給 wait_result 這種「迴圈到 deadline」的測試用。
# 本 phase 的五顆都會進 wait_result 的迴圈，所以**全部用 讓時鐘一直走**；
# 假裝過了 從 Phase 89 起才有人用，先放在這裡是為了兩支並排、語意一次講清楚
# （tests/unit/test_camera_session_unit.py 的同名 helper 就是凍結語意——名字要對得上）。


def 假裝過了(monkeypatch, 秒數: float) -> None:
    """把時基往前撥。撥完之後所有 _now() 的呼叫都會看到「未來」——而且**停在那裡不動**（凍結）。

    寫法與 tests/unit/test_camera_session_unit.py 的同名 helper 一致（凍結語意）。
    Phase 89 的 Ec2Probe TTL 測試就是這樣用：問一次 → 假裝過了(monkeypatch, 61) → 再問一次。
    順手把 _sleep 換成不睡：凍結的世界裡沒有人該真的睡。

    ⚠ **不要**拿它來測 wait_result 的逾時：deadline 是進迴圈前用 _now() + timeout_seconds
      算的，時鐘凍結的話「剩下」永遠等於逾時秒數，那個迴圈會**永遠跑不完**。
      會進迴圈的測試一律用下面的 讓時鐘一直走()。
    """
    現在 = cloud_ingest._now()
    monkeypatch.setattr(cloud_ingest, "_now", lambda: 現在 + 秒數)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda 秒: None)


def 讓時鐘一直走(monkeypatch, 每次秒數: float = 2.0) -> None:
    """把 cloud_ingest 的兩個時間接縫換掉：**每問一次時鐘，就再過了 每次秒數 秒**；睡覺完全不睡。

    語意講清楚：_now() 第一次被問回「每次秒數」，第二次回「2×每次秒數」……一直往前走。
    wait_result 進迴圈前問一次（算 deadline）、每一圈再問一次（算剩下），
    所以 每次秒數 給得越大，迴圈跑越少圈就到 deadline。

    ⚠ 不接管的話，逾時測試會**真的**跑滿 timeout_seconds 秒，而且是**全速空轉**：
      FakeMailbox 的 receive 是立刻回 None 的（它不會真的等 20 秒），
      所以那個迴圈會用 100% CPU 空轉到 deadline。

    ⚠ 它從 0 起算、不是接著真時鐘走：給 wait_result 用沒問題（deadline 也是用同一支算的），
      但**不可以**拿去測 Ec2Probe 的 TTL——那個快取記的是「上次問」的真時鐘秒數，
      接管之後「過了幾秒」會變成負數，快取永遠不過期（Phase 89 的 TTL 測試用 假裝過了）。
    """
    現在 = {"秒": 0.0}

    def _假的now() -> float:
        現在["秒"] += 每次秒數
        return 現在["秒"]

    monkeypatch.setattr(cloud_ingest, "_now", _假的now)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda 秒: None)


def 建一筆(store: InMemoryJobStore, job_id: str, **fields) -> None:
    """在 store 裡放一筆長得像真的的 job（wait_result 的第 3 條規則會去查它）。"""
    store.create(
        job_id=job_id,
        filename="a.png",
        content_type="image/png",
        ai_backend="local",
        source="upload",
    )
    if fields:
        store.update(job_id, **fields)


def 放三個物件(信箱: FakeMailbox, job_id: str) -> None:
    """把一筆任務在 S3 上會留下的三個物件都放好。"""
    信箱.put_object(信箱.input_key(job_id, "image/png"), b"PNG", "image/png")
    信箱.put_object(信箱.context_key(job_id), b"{}", "application/json")
    信箱.put_object(信箱.result_key(job_id), b"{}", "application/json")


def test_wait_result每次等待的秒數都不超過20(monkeypatch):
    """規則 1：`receive_result(wait_seconds=min(20, 剩餘秒數))`。

    20 是 **AWS 訂的上限**（WaitTimeSeconds 最大值），超過會被 API 直接拒絕。
    所以「整筆最多等 300 秒」必須自己在外面數 deadline，不能塞給這個參數。

    時鐘每問一次走 3 秒、整筆最多等 30 秒：「剩下」從 27 秒開始、每圈少 3 秒。
    前幾圈要被壓到 20（上限），剩下不到 20 之後要跟著縮短——
    整串實際會是 [20, 20, 20, 18, 15, 12, 9, 6, 3]（第 10 圈剩下 0 ⇒ 逾時回 None）。
    min() 的**兩半**都要驗到：只驗「≤ 20」的話，一個永遠送 20 的實作也會綠。

    下限 1 是 _等幾秒() 的另一半（不要退化成短輪詢，Phase 79 定的），所以斷言寫 1 <= 秒 <= 20。
    """
    讓時鐘一直走(monkeypatch, 3.0)
    信箱 = FakeMailbox()
    路 = CloudRoute(信箱, FakeProbe(True), timeout_seconds=30)

    assert 路.wait_result("我的", store=InMemoryJobStore()) is None, "沒有結果就是 None"
    assert 信箱.wait_seconds_log, "至少要問過佇列一次"
    assert all(1 <= 秒 <= 20 for 秒 in 信箱.wait_seconds_log), 信箱.wait_seconds_log
    assert 信箱.wait_seconds_log[0] == 20, "剩下 27 秒時要被壓到上限 20"
    assert any(秒 < 20 for 秒 in 信箱.wait_seconds_log), "快到期時要跟著剩餘秒數縮短"


def test_收到別人的訊息而那筆還在雲端路時把訊息還回去(monkeypatch):
    """規則 3 的前半：那一筆還在等（store 裡有它、而且 route 不是 local）→ **還回去**。

    ⚠ 絕對不可以順手刪掉：刪了的話它的主人會等到逾時、白白 fallback 一次
      （而且工人明明已經把結果算好了）。
    """
    讓時鐘一直走(monkeypatch, 2.0)
    信箱 = FakeMailbox()
    放三個物件(信箱, "別人")
    信箱.send_result("別人")
    store = InMemoryJobStore()
    建一筆(store, "別人", route="cloud")
    路 = CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)

    assert 路.wait_result("我的", store=store) is None, "我的結果沒來，所以是逾時"

    assert 信箱.results == [{"job_id": "別人"}], "別人的訊息要被還回佇列"
    assert "release_result_message" in 信箱.calls
    assert "delete_result_message" not in 信箱.calls, "還在等的訊息一次都不可以刪"
    assert 信箱.result_key("別人") in 信箱.objects, "更不可以刪別人的 S3 物件"


def test_收到別人的訊息而那筆已不在store時刪訊息也刪S3(monkeypatch):
    """規則 3 的後半（情況一）：store 裡查無 → 那一筆早就做完或被 dismiss 了。

    這是**殘訊息**：沒有人在等它。刪掉訊息，順手把它的三個 S3 物件也清乾淨——
    不然那三個檔要躺到 Lifecycle 兩天後才過期，而且下一筆任務每次等結果都會撿到它。
    """
    讓時鐘一直走(monkeypatch, 2.0)
    信箱 = FakeMailbox()
    放三個物件(信箱, "早就做完的")
    信箱.send_result("早就做完的")
    路 = CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)

    assert 路.wait_result("我的", store=InMemoryJobStore()) is None

    assert 信箱.results == [], "沒有人在等的殘訊息要刪掉"
    assert 信箱.objects == {}, "順手把它的 S3 物件也清乾淨"
    assert "delete_result_message" in 信箱.calls


def test_收到別人的訊息而那筆已改走本機時刪訊息也刪S3(monkeypatch):
    """規則 3 的後半（情況二）：store 裡有它，但 route 已經是 local。

    意思是「那一筆已經放棄雲端、走本機重做了」——工人這時候才把結果送回來，
    一樣是遲到的殘訊息（它的主人根本不會再來收）。
    """
    讓時鐘一直走(monkeypatch, 2.0)
    信箱 = FakeMailbox()
    放三個物件(信箱, "已經改走本機的")
    信箱.send_result("已經改走本機的")
    store = InMemoryJobStore()
    建一筆(store, "已經改走本機的", route="local")
    路 = CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)

    assert 路.wait_result("我的", store=store) is None

    assert 信箱.results == []
    assert 信箱.objects == {}


def test_自己的訊息但result_json不在時回None(monkeypatch):
    """規則 2 的後半：工人說「寫好了」，S3 上卻找不到 result.json。

    這不該發生（D9 的順序鐵律是「先 Put 才 Send」），但真的發生時要有明確行為：
    **刪掉訊息**（留著只會變成下一筆的殘訊息）＋ 回 None（＝當逾時處理 → fallback 本機）。

    第一則就是自己的，理論上第一圈就回來；仍然接管時鐘是保險——
    實作寫錯（沒有 return）時，這一顆才會紅而不是卡死。
    """
    讓時鐘一直走(monkeypatch)
    信箱 = FakeMailbox()
    信箱.send_result("我的")  # 只有訊息，沒有 result.json
    路 = CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)

    assert 路.wait_result("我的", store=InMemoryJobStore()) is None

    assert 信箱.results == [], "訊息要刪掉"
    assert "delete_result_message" in 信箱.calls
```

### - [x] 步驟 2：先寫測試（紅）——`tests/integration/test_gated_ingest.py` 追加 5 顆

- [x] 檔頭 import 區補一行 `import json`（放在 `import logging` 前面，照字母順序）。

- [x] 在檔案**最後面**加上：

```python


# ---------------------- ⑤ 逾時與崩潰重送（Phase 80）----------------------


def 讓時鐘一直走(monkeypatch, 每次秒數: float = 2.0) -> None:
    """把 cloud_ingest 的兩個時間接縫換掉（與 test_cloud_ingest_unit.py 的同名工具相同）。

    **每問一次時鐘就再過了 每次秒數 秒**；睡覺完全不睡。詳細語意見那一份的 docstring。
    本檔只需要這一支：這裡會走到逾時迴圈的測試要的都是「時間會走」。
    凍結時鐘的 假裝過了() 本檔用不到，所以不留（Phase 89 的 TTL 測試在單元測試檔）。

    刻意在本檔自己留一份：跨測試檔 import 小工具會把兩份測試綁在一起，
    那邊改一下這邊就跟著紅（本專案既有的 分頁VLM 也是這樣各留一份）。
    """
    現在 = {"秒": 0.0}

    def _假的now() -> float:
        現在["秒"] += 每次秒數
        return 現在["秒"]

    monkeypatch.setattr(cloud_ingest, "_now", _假的now)
    monkeypatch.setattr(cloud_ingest, "_sleep", lambda 秒: None)


def 放一份結果(信箱: FakeMailbox, job_id: str, understanding) -> None:
    """直接把一份 result.json 放進 S3（模擬「工人上一趟已經做完了」）。

    格式與 tests/fakes.py 的假工人寫出來的**完全一致**（總覽 §2.4.3）。

    ★ 直接塞進 `objects`、**不走 `put_object()`**：那一支會把 `put_calls` 加一，
      而崩潰重送的測試要斷言「本機這一趟一個 Put 都沒有」——工人上一趟放的東西
      不該算在本機頭上。
    """
    result = {
        "job_id": job_id,
        "worker_version": "fake-worker",
        "kind": "image",
        "understood": understanding is not None,
        "attempts": 1,
        "understanding": understanding.model_dump() if understanding is not None else None,
    }
    信箱.objects[信箱.result_key(job_id)] = json.dumps(
        result, ensure_ascii=False, default=str
    ).encode("utf-8")


class 把寫入也記進流水帳的Store(記得最後一筆的Store):
    """update(photo_ids=…) 時往**信箱的** calls 流水帳記一行。

    「photo_ids 寫進 job」與「delete_objects 清 S3」分別發生在 store 與信箱兩顆假件上，
    各自的計數器比不出先後；把 store 的這一種寫入也記進同一本流水帳，順序才比得出來
    （總覽 §10.2 R 要的就是先後）。其餘行為與 記得最後一筆的Store 完全相同。

    ⚠ 本 phase 有兩顆測試用它，而且要驗的順序**方向相反**，別看錯：
      * 雲端路成功落庫（`test_崩潰重送route是cloud而且S3有結果…`）：
        寫 photo_ids **在** 清 S3 **之前**（§10.2 R——收據先寫，cleanup 才是網路呼叫）
      * 逾時 fallback（`test_逾時fallback之前會先清掉S3物件`）：
        清 S3 **在** 寫 photo_ids **之前**（§2.1——先把半套清掉，才退回本機入庫）
      不衝突：兩處的 photo_ids 是**不同人**寫的（前者是雲端路自己，後者是 fallback 的
      run_ingest_job），中間夾的都是同一次 cleanup。
    """

    def __init__(self, 信箱: FakeMailbox) -> None:
        super().__init__()
        self.信箱 = 信箱

    def update(self, job_id: str, **fields):
        if "photo_ids" in fields:
            self.信箱.calls.append("store.update photo_ids")
        return super().update(job_id, **fields)


def test_逾時沒有結果_fallback本機且log有reason_result_timeout(monkeypatch, caplog):
    """design6 §8 錯誤表第 5 列、D10 的第 4 種「遠端不可用」。

    情境：送出去了，但工人掛了／EC2 在半路被 Stop——結果永遠不會來。
    使用者**完全無感**：照片照樣入收件箱，只是慢一點（等了逾時秒數）。
    """
    讓時鐘一直走(monkeypatch)
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store)
    信箱 = 有工人的信箱(收據理解, 工人上工=False)  # 另一頭根本沒有人

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.send_job_calls == 1, "有送出去（只是沒人做）"
    assert photo_repository.count_photos() == 1, "照片照樣入庫（§0 禁止第 6 條）"
    assert store.deleted[job_id]["route"] == "local", "fallback 之後 route 要改成 local"
    assert any("fallback=local reason=result_timeout" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )


def test_逾時fallback之前會先清掉S3物件(monkeypatch):
    """§2.1：「若已寫到 S3／SQS：**盡力刪物件、刪訊息**，避免下次 Start 重複處理」。

    不清的話，下次 EC2 開機時工人會看到一則舊的 jobs 訊息、把那張圖再看一次——
    而本機早就已經用 fallback 入庫了。

    「**之前**」怎麼證明：光看最後的 objects == {} 只證明得了「有清」，證明不了「先清」。
    所以 store 用把 photo_ids 寫入也記進**信箱同一本流水帳**的版本——
    fallback 的 run_ingest_job 入庫成功時會寫一次 photo_ids，
    那一行落在 delete_objects 後面，就等於「清 S3 發生在本機入庫之前」。
    """
    讓時鐘一直走(monkeypatch)
    信箱 = 有工人的信箱(收據理解, 工人上工=False)
    store = 把寫入也記進流水帳的Store(信箱)
    job_id = 建一個job(store)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.objects == {}, f"S3 應該被清乾淨了：{list(信箱.objects)}"
    assert 信箱.delete_calls >= 1
    assert photo_repository.count_photos() == 1

    第一次清S3 = next(i for i, c in enumerate(信箱.calls) if c.startswith("delete_objects"))
    第一次寫photo_ids = 信箱.calls.index("store.update photo_ids")
    assert 第一次清S3 < 第一次寫photo_ids, (
        f"清 S3 要在 fallback 真的入庫之前（design6 §2.1）：{信箱.calls}"
    )


def test_同一個job_id的結果送兩次_照片仍然只有一列(monkeypatch):
    """design6 D17、§9 必釘第 6 條：SQS 是 at-least-once，同一筆可能被處理兩次。

    情境（就是總覽 §10.2 R 講的那條時序）：上一趟其實已經 INSERT 成功了、`photo_ids` 也寫進去了，
    但在那之後、`cleanup` 與「刪 job」之前被殺掉，於是佇列把同一個任務再送一次，
    而且 S3 上的結果還在（cleanup 沒跑完）。
    **必須直接收尾，不可以插出第二張照片**（本專案沒有刪除照片的功能）。

    第二趟靠什麼擋下來：`route == "cloud"` → `_繼續雲端路` → `fetch_result` 拿到結果 →
    **重讀一次 job**（`store.get`）→ `photo_ids` 有值 → `_用雲端結果落庫` 第一件事就收尾。
    這一顆用「重新建 job 並先寫好 `photo_ids`」來擺出那個時序，所以它同時涵蓋
    「開頭那次 `store.get` 就看得到 `photo_ids`」與「落庫前重讀」兩條路——
    單執行緒測試分不出這兩者，重讀真正防的是 `--concurrency=2` 的並行窗口（見 §7 陷阱 12）。
    """
    # 綠的時候這一顆根本不會進 wait_result；接管時鐘是為了**紅的那一次**——
    # Phase 79 的碼沒有 route=cloud 分支，第二趟會再 submit 一次然後等到逾時，
    # 不接管的話那一次紅會先空轉 5 秒。
    讓時鐘一直走(monkeypatch)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store)
    信箱 = 有工人的信箱(收據理解)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))
    assert photo_repository.count_photos() == 1
    照片id = store.deleted[job_id]["photo_ids"][0]

    # ---- 佇列把同一個任務再送一次 ----
    建一個job(store, job_id=job_id)  # staging 與 job 都重新出現（模擬重送）
    store.update(job_id, route="cloud", photo_ids=[照片id])
    第二顆信箱 = FakeMailbox()
    放一份結果(第二顆信箱, job_id, 收據理解)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(第二顆信箱))

    assert photo_repository.count_photos() == 1, "同一個 job_id 不可以插出第二張照片"
    assert 第二顆信箱.send_job_calls == 0, "重送時不可以再送一次雲端"
    assert store.get(job_id) is None, "直接收尾（＝job 被刪掉）"
    assert 第二顆信箱.objects == {}, "S3 也要清乾淨"


def test_崩潰重送route是cloud而且S3有結果_直接落庫零submit():
    """總覽 §2.5：`route == "cloud"` 的重送先去 S3 看結果在不在。

    在 → 直接用它落庫。**不可以再 submit 一次**：上一趟送出去的東西還在，
    工人可能正在做，再送一次只是讓它白做一次、S3 多一份垃圾。

    順便釘住總覽 §10.2 R 的落庫順序：INSERT 之後**先寫 photo_ids、再清 S3**。
    反過來的話，清 S3 清到一半被殺掉，重送時 job 裡沒有 photo_ids → 同一張照片插第二次。
    """
    信箱 = FakeMailbox()
    store = 把寫入也記進流水帳的Store(信箱)
    job_id = 建一個job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")  # 上一趟已經送出去了
    放一份結果(信箱, job_id, 收據理解)
    閘門 = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換答案也不該被問到

    跑(job_id, store=store, gate=閘門, cloud=雲端路(信箱))

    assert 閘門.calls == 0, "route 已經有值了，不可以再問一次閘門（design6 §2.1）"
    assert 信箱.send_job_calls == 0, "不可以再送一次"
    assert 信箱.put_calls == 0, "本機這一趟一個 Put 都沒有（結果是工人上一趟放的）"
    assert photo_repository.count_photos() == 1, "用 S3 上那份結果落庫"
    assert store.get(job_id) is None
    assert 信箱.objects == {}, "落庫之後把 S3 清乾淨"

    第一次寫photo_ids = 信箱.calls.index("store.update photo_ids")
    第一次清S3 = next(i for i, c in enumerate(信箱.calls) if c.startswith("delete_objects"))
    assert 第一次寫photo_ids < 第一次清S3, (
        f"photo_ids 要在清 S3 **之前**寫進 job（總覽 §10.2 R）：{信箱.calls}"
    )


def test_崩潰重送route是cloud但S3沒有結果_fallback本機(caplog):
    """另一半：結果不在（工人根本沒做完、或訊息被別人當殘訊息清掉了）。

    那一趟的結果**永遠不會來了**（results 訊息已經被誰收走）——所以不要再等，
    直接退回本機。log 的 reason 是 `redelivered_without_result`。
    """
    caplog.set_level(logging.INFO)
    store = 記得最後一筆的Store()
    job_id = 建一個job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")
    信箱 = FakeMailbox()  # S3 上什麼都沒有

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.send_job_calls == 0
    assert photo_repository.count_photos() == 1, "走本機把它做完"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=redelivered_without_result" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )
```

### - [x] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -q
```

預期：**5 紅**——單元 2 顆（`test_收到別人的訊息而那筆已不在store時刪訊息也刪S3`、
`test_收到別人的訊息而那筆已改走本機時刪訊息也刪S3`）＋ 整合 3 顆
（`test_同一個job_id的結果送兩次_照片仍然只有一列`、`test_崩潰重送route是cloud…` 兩顆）；其餘綠。
典型的錯誤長相：

```text
AssertionError: 沒有人在等的殘訊息要刪掉
assert [{'job_id': '早就做完的'}] == []
```

（Phase 79 的基本版一律「還回去」，所以殘訊息不會被刪掉——這正是本 phase 要補的。）
`test_同一個job_id…` 紅在 `send_job_calls == 0`（79 沒有 route=cloud 分支，第二趟會再 submit 一次）；
`test_崩潰重送route是cloud…` 兩顆紅在「閘門被問了」或 log 字樣不見。

其餘 5 顆在 79 的碼下**本來就綠**——它們是「釘住不要退步」的測試：
`test_wait_result每次等待…`（79 已有 `_等幾秒`）、`test_收到別人的訊息而那筆還在雲端路時把訊息還回去`
（79 一律還回去）、`test_自己的訊息但result_json不在時回None`（79 的 `_收下自己的結果` 已會刪訊息）、
`test_逾時…` 兩顆（79 已接逾時 fallback 與 cleanup）。**先綠不代表寫錯**，但也要親眼確認它們真的綠。

> ⚠️ 如果有測試**跑很久不結束**，代表 `讓時鐘一直走()` 沒接上、或拿成凍結的 `假裝過了()`（見常見陷阱 1、9）。Ctrl+C 之後檢查
> `monkeypatch.setattr(cloud_ingest, "_now", …)` 那兩行是不是打在**同一個模組物件**上。

### - [x] 步驟 4：綠（1／2）——`app/services/cloud_ingest.py` 補完五條規則

**整檔覆蓋**（下面就是本 phase 結束時這個檔案的完整內容。與 Phase 79 的版本**逐行比對只差四處**：
模組 docstring、`_now()` 的 docstring 多一段、`wait_result()` 的規則說明與本體、
新增的 `_處理別人的訊息()`。`TYPE_CHECKING` 那段註解 Phase 79 已經是同一份寫法——
刻意不寫出資料庫驅動套件的名字，因為既有的 design3 掃碼 `test_SQL只出現在repository與db層`
是**逐字子字串**比對、註解也算；你的 79 若還是更早的版本，這裡會多出第五處差別）：

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

【Phase 79／80 補上的部分】
CloudRoute 本體：available／submit／fetch_result／wait_result／cleanup。
wait_result 的**完整五條規則**（含「收到別人的結果訊息怎麼辦」）在 Phase 80 落地，
規格見計畫總覽 §2.5。Ec2Probe（真的去問 EC2 開著沒）在 Phase 89。
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

    ★ **這一支之後 Phase 89 的 Ec2Probe 也會用**（它的 TTL 快取要算「上次問是幾秒前」）。
      不要再建第二個時鐘接縫：兩個的話，測試就得記得同時 monkeypatch 兩支，
      而漏掉一支的症狀是「快取的測試偶爾紅」——最難查的那一種。
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

        五條規則（總覽 §2.5，Phase 80 完整落地）：

          1. 迴圈到 deadline 為止（deadline ＝ 進迴圈前的 _now() ＋ timeout_seconds，
             而 timeout_seconds 來自 config.CLOUD_RESULT_TIMEOUT_SECONDS，預設 300 秒），
             每次 receive_result(wait_seconds=min(20, 剩餘秒數))——換算在 _等幾秒() 裡，
             它另有下限 1（剩不到 1 秒仍送 1，免得退化成短輪詢）
          2. 收到的 job_id **是我的**：去 S3 拿 result.json；
             有 → 解析、刪訊息、回傳；沒有 → 刪訊息、回 None（當逾時 → fallback）
          3. 收到的是**別人的**：見 _處理別人的訊息()
          4. deadline 到了仍然沒有 → 回 None
          5. 每則訊息只解析 job_id，**不含任何位元組**（design6 §0 禁止第 2 條）

        ★ store 是規則 3 要用的：它得查「別人那一筆現在還在不在、走的是哪條路」。
        """
        deadline = _now() + self._timeout_seconds
        while True:
            剩下 = deadline - _now()
            if 剩下 <= 0:
                # 規則 4：等到期限了。回 None ⇒ 呼叫端 cleanup ＋ fallback 本機（D10）
                logger.warning("job %s 等雲端結果逾時（%d 秒）", job_id, self._timeout_seconds)
                return None

            message = self._mailbox.receive_result(_等幾秒(剩下))
            if message is None:
                continue  # 長輪詢等滿了還是沒訊息，再等下一輪（deadline 會收掉）

            if message.job_id == job_id:
                return self._收下自己的結果(message, job_id)

            self._處理別人的訊息(message, store=store)

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

    def _處理別人的訊息(self, message: MailboxMessage, *, store: JobStore) -> None:
        """規則 3：results 佇列是**共用的**，兩筆同時在等時一定會收到對方的訊息（總覽 §8.9）。

        兩種情況，處理方式完全相反：

          ① 那一筆**還在雲端路等**（store 裡有它，而且 route 不是 "local"——
             總覽 §2.5 第 3 條的「否則」，逐字對齊）
             → 立刻還回佇列（可見度改 0），讓它的主人收得到。
               ⚠ 絕對不可以順手刪掉：刪了它的主人會等到逾時、白白 fallback 一次。

          ② 那一筆**已經沒有人在等**（store 裡查無 ＝ 早就做完或被 dismiss；
             或 route 已經是 "local" ＝ 那一筆已經 fallback 了）
             → 這是**遲到的殘訊息**：刪掉訊息，順手把它的 S3 物件也清乾淨。
               不清的話那三個檔要躺到 Lifecycle 兩天後才過期，而且下一筆任務
               每次等結果都會撿到同一則沒用的訊息。

        還回去之後 _sleep 一下下（RELEASE_BACKOFF_SECONDS）：不歇的話，
        「只有別人的訊息」那段時間會變成一個全速空轉的迴圈。
        """
        別人的 = store.get(message.job_id)
        還在等 = 別人的 is not None and 別人的.get("route") != "local"
        if 還在等:
            self._mailbox.release_result_message(message.receipt_handle)
            _sleep(RELEASE_BACKOFF_SECONDS)
            return

        logger.info("收到沒有人在等的結果訊息（job %s），順手清掉", message.job_id)
        self._mailbox.delete_result_message(message.receipt_handle)
        self.cleanup(message.job_id)


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

### - [x] 步驟 5：綠（2／2）——`app/services/gated_ingest.py` 補上崩潰重送

**整檔覆蓋**（與 Phase 79 的差別有四處：模組 docstring、新增 `route == "cloud"` 分支、
新增 `_盡力清雲端()` 與 `_繼續雲端路()`、以及把七處 `cloud.cleanup(job_id)` 全部改走 `_盡力清雲端()`。
落庫段「INSERT → 立刻寫 photo_ids → 清 S3 → 收尾」的順序與 `_理解()` 改用 `model_validate` 是
總覽 §10.2 R 的修訂，Phase 79 的修訂版同樣有——79 若還是舊版，這裡就再多兩處差別）：

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

【本 phase（80）做到哪裡】
單圖的雲端路整圈都通了，四種「遠端不可用」也全部有退路：
不是 running／沒憑證（Phase 78）、送出失敗（79）、逾時（79 接、80 補測試）、
崩潰重送但沒有結果（80）。**還沒做**：PDF 的雲端路（Phase 81）——
本檔的落庫段目前只認單圖的 result.json。

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
    # ★ 要在問閘門**之前**：閘門（VlmGate）一定會把圖送去問 VLM 一句短問題，
    #   本機推估 20〜60 秒、雲端約 2 秒（總覽 §10.2 L）——標晚了那一列會停在 queued 很久。
    store.update(job_id, status="analyzing")

    route = job.get("route")
    if route == "local":
        # 崩潰重送，而且上一趟已經決定走本機了。**不再問一次閘門**（design6 §2.1）。
        logger.info("job %s 崩潰重送：route 已經是 local，直接走本機路", job_id)
        ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=embeddings, now=now)
        return

    if route == "cloud":
        # 崩潰重送，而且上一趟已經送去雲端了（總覽 §2.5）。同樣**不再問一次閘門**。
        _繼續雲端路(job, store=store, vlm=vlm, embeddings=embeddings, now=now, cloud=cloud)
        return

    verdict = gate.classify(
        filename=job.get("filename", ""),
        content_type=job["content_type"],
        # 閘門是 VlmGate（Phase 74 建、75 接真模型）：它**一定**會呼叫 load_bytes——
        # 判斷靠**看圖**，不看檔名（2026-09-01 改判；design6 D4、總覽 §8.10、§10.1 追認項 f）。
        # filename 照樣傳，但那只是給呼叫端與假件記帳用，verdict 不准依賴它。
        # 仍然寫成 lambda 而不是先讀好：讀檔什麼時候發生、失敗了算什麼，都由閘門決定
        # （契約在總覽 §2.4.1：load_bytes 失敗 → UNCERTAIN ⇒ 走本機，不是讓這一筆失敗）。
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
        _盡力清雲端(cloud, job_id)
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
        _盡力清雲端(cloud, job_id)
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


def _盡力清雲端(cloud, job_id: str) -> None:
    """盡力清掉這一筆在 S3 上的殘留。清不掉只 log——善後失敗不可以蓋掉真正的錯誤。

    CloudRoute.cleanup() 自己已經吞過一次例外，為什麼這裡還要再包一層：
    **這裡的 cloud 有可能是 CloudRouteOff**——使用者在任務半路把 CLOUD_ROUTE 改回 off
    （或 .env 的 AWS 設定被清掉、容器重啟），而那一顆的每一支方法都會丟 RuntimeError。
    清不掉也沒關係：S3 還有 Lifecycle（2 天）當掃把。
    """
    try:
        cloud.cleanup(job_id)
    except Exception:
        logger.warning("job %s 清雲端殘留時出錯，略過", job_id, exc_info=True)


def _繼續雲端路(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """崩潰重送，而且上一趟已經送去雲端了：看結果在不在，決定落庫還是退回本機。

    ⚠ 這裡**絕不重新 submit**：上一趟送出去的東西還在 S3 與 jobs 佇列裡，
      工人可能正在做、也可能已經做完。再送一次只會讓它白做一次、S3 多一份垃圾。

    ⚠ 也**不再問一次閘門**（design6 §2.1 的禁止）：route 已經有值就代表判斷過了。

    fetch_result 用 try 包起來的理由與 _盡力清雲端 相同：cloud 有可能已經是 CloudRouteOff。
    拿不到結果 ＝ 那一趟的結果永遠不會來了（results 訊息多半已經被誰當殘訊息清掉），
    所以不要再等，直接退回本機（reason=redelivered_without_result）。

    ★ 落庫前**重新 store.get 一次**（D17 的最後一道保險）：
      run_gated_ingest_job 開頭那份 job 是**一份複本**（JobStore 的 get 一律回複本），
      拿到之後這條路上還隔著一次 fetch_result（S3 網路呼叫）。
      Celery 是 --concurrency=2（總覽 §8.8），同一個 job_id 被兩個子行程同時撿到時，
      舊複本會看不到「另一邊剛剛寫進去的 photo_ids」——照著它走就會 INSERT 第二張。
      重讀不能把那個窗口關到零（那要資料庫層的唯一鍵，本增量不做），但能把它縮到
      「store.get 到 INSERT」這幾行之內。查無（半路被 dismiss）就沿用手上那份，
      行為與重讀之前完全一樣。
    """
    job_id = job["job_id"]
    try:
        result = cloud.fetch_result(job_id)
    except Exception:
        logger.warning("job %s：崩潰重送時讀不到雲端結果", job_id, exc_info=True)
        result = None

    if result is not None:
        最新 = store.get(job_id) or job
        logger.info("job %s 崩潰重送：S3 上已經有結果了，直接落庫", job_id)
        _用雲端結果落庫(最新, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
        return

    _盡力清雲端(cloud, job_id)
    _退回本機路(
        job_id,
        REASON_REDELIVERED_WITHOUT_RESULT,
        store=store,
        vlm=vlm,
        embeddings=embeddings,
        now=now,
    )


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
        _盡力清雲端(cloud, job_id)
        ingest_job.finish_image_job(
            job_id, job["photo_ids"][0], store=store, content_type=content_type
        )
        return

    # ② 工人說看不懂（三次都失敗）＝ **這一筆失敗**，不是 fallback（總覽 §10 追認項 g）
    understanding = _理解(result.get("understanding")) if result.get("understood") else None
    if understanding is None:
        logger.warning("job %s：雲端看不懂（工人試了 %s 次）", job_id, result.get("attempts"))
        _盡力清雲端(cloud, job_id)
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
        _盡力清雲端(cloud, job_id)
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
        _盡力清雲端(cloud, job_id)
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
    _盡力清雲端(cloud, job_id)
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

### - [x] 步驟 6：跑測試，看它轉綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -v
```

預期：**`41 passed`**（unit 20 ＝ 15 ＋ 5，integration 21 ＝ 15 ＋ 6——含 R13 那 1 顆與 R14 那 1 顆）。

```bash
pytest -q
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：**開工基線 ＋ 11**（含裁決 R14 的 1 顆）、0 skipped（總覽 §9 是 609；實查 602 → **613**）；
格式與 lint 全過。

### - [x] 步驟 7：**不 commit**——記下快照

> ⚠ **產品負責人指示：本次（phase0901）全程不 commit**，也不要把計畫檔搬進 `finish/`
> （`git mv` 會直接 stage）。總覽 §7 鐵律 12：commit 節奏由產品負責人決定。

驗收改用「與開工前的工作樹快照相減」。開工前先存一份，做完再存一份：

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0901/snapshot-tree     # 開工前跑一次，把印出來的 tree SHA 記下來
# …做完 Phase 80 之後…
.superpowers/sdd/phase0901/snapshot-tree     # 再跑一次
git diff -U10 <開工前的SHA> <做完的SHA>       # 逐行看這個 phase 到底改了什麼
```

`snapshot-tree` 只是把工作樹寫成一顆 tree 物件（不碰 index、不建 commit、不動 stash），
所以跑幾次都不會弄髒任何東西。

改到的檔案應該**恰好四個**，順手核對一次：

```bash
git status --short -- app tests
# 預期恰四行（M app/services/cloud_ingest.py、M app/services/gated_ingest.py、
#              M tests/unit/test_cloud_ingest_unit.py、M tests/integration/test_gated_ingest.py）
```

commit message 草稿先留著，等產品負責人說要 commit 時再用：

```text
feat: Phase 80 雲端路逾時與冪等——wait_result 補完五條規則（deadline、自己的訊息、別人的訊息還回去或當殘訊息刪掉並清 S3、每次等待不超過 20 秒）、gated_ingest 補上崩潰重送 route=cloud 兩條分支（S3 有結果直接落庫零 submit／沒有結果 fallback 並留 log reason=redelivered_without_result）、cleanup 一律走 _盡力清雲端（cloud 可能是 CloudRouteOff），+10 tests；端點仍 22、對外行為零改變
```

---

## 5. ASCII 圖

### 圖一：`wait_result` 的五條規則（決策樹）

```text
                    wait_result(job_id, store)
                              │
                deadline = _now() + timeout_seconds
                              │
        ┌─────────────────────▼─────────────────────┐
        │  剩下 = deadline - _now()                  │
        └─────────────────────┬─────────────────────┘
                              │
                     剩下 <= 0 ？
                     ├── 是 ──► 【規則 4】回 None
                     │           ＝逾時 ⇒ 呼叫端 cleanup ＋ fallback 本機（D10）
                     否
                      │
        【規則 1】receive_result(wait_seconds = min(20, 剩下))
                      │            ↑ 20 是 AWS 的上限，不是我們挑的
                      │
              收到訊息了嗎？
              ├── 沒有（None）──► 回上面再等一輪
              有
               │
        message.job_id == 我的 job_id ？
        │                                   │
       是                                   否
        │                                   │
 【規則 2】                            【規則 3】查 store.get(別人的 job_id)
 get_object(result.json)                    │
        │                    ┌──────────────┴───────────────┐
   有？  │                   │                              │
   ├─ 有 ─► 刪訊息          那一筆還在等                  沒有人在等了
   │        解析成 dict     （store 有它 ＋               （store 查無 ＝ 做完／被關掉
   │        **回傳**          route != "local"）            或 route == "local" ＝ 已 fallback）
   │                              │                              │
   └─ 沒有 ─► 刪訊息        release_result_message         delete_result_message
              回 None       （可見度改 0，立刻還給主人）   ＋ cleanup(它的三個 S3 物件)
              （＝當逾時）         │                              │
                             _sleep(1) 再繼續               繼續等我的
                                    │                              │
                                    └──────────┬───────────────────┘
                                               ▼
                                        回上面再等一輪

   【規則 5】每則訊息 body 只有 job_id（與 s3_key），**一個位元組都沒有**。
```

### 圖二：一筆 job 被送兩次，為什麼不會變成兩張照片

```text
   第一趟                                        第二趟（SQS at-least-once 重送）
   ───────                                       ──────────────────────────────
   submit → 工人 → result.json                   run_gated_ingest_job(同一個 job_id)
   wait_result 拿到結果                                    │
   本機算向量                                       job.get("route") == "cloud"
   INSERT photo（id=42）                                   │
   store.update(photo_ids=[42])  ◄── 冪等的依據      _繼續雲端路 → fetch_result
   cleanup(S3)（網路呼叫，可能拖幾十秒）                    │
   ✂ 殺在這裡（機器重開／容器重啟）                 S3 上還有結果 → 落庫前**重讀一次 job**
   （staging 還在、job 還在、S3 可能清了一半）        （store.get，拿最新的 photo_ids）
                                                           │
                                                  _用雲端結果落庫 第一件事：
                                                  job.get("photo_ids") 有值！
                                                           │
                                                  ★ 直接收尾，**不再 INSERT**
                                                    cleanup(S3) → finish_image_job
                                                    （寫 photo_ids → 刪 staging → 刪 job）
                                                           │
                                                     照片仍然只有一張

   ★ 順序鐵律（總覽 §10.2 R）：INSERT → 立刻寫 photo_ids → cleanup(S3) → finish_image_job。
     cleanup 清到一半被殺、S3 的 result.json 已經不在 → 重送時 fetch_result 拿不到 →
     退回本機 run_ingest_job → 它一樣先看 photo_ids → 也不會 INSERT 第二次。

   ★ 冪等的依據為什麼要**重讀**：run_gated_ingest_job 開頭那份 job 是複本，而
     `--concurrency=2`（總覽 §8.8）＝同一個 job_id 有可能被兩個 Celery 子行程同時撿到。
     舊複本看不到另一邊剛寫進去的 photo_ids；所以 _繼續雲端路 在落庫前再 store.get 一次。
     這條路上唯一真正的正本仍然是 JobStore 裡那筆 job，不是誰手上的複本。
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` 記下顆數（總覽 §9 是 599；R1 若讓 Phase 78 多一顆就是 600
  ——**以實查為準**，後面每一項的「＋10」都是跟這個數字比）

- [x] **五條規則的三支程式都在**

  ```bash
  grep -nE "^    def wait_result|^    def _收下自己的結果|^    def _處理別人的訊息" \
    app/services/cloud_ingest.py
  ```

  預期：**4 行**命中（`wait_result` 兩次——`CloudRoute` 與 `CloudRouteOff` 各一支，正常——
  加 `_收下自己的結果`、`_處理別人的訊息` 各一次）

- [x] **崩潰重送與盡力清理都在**

  ```bash
  grep -nE "^def _繼續雲端路|^def _盡力清雲端|route == \"cloud\"" app/services/gated_ingest.py
  grep -c "cloud.cleanup(job_id)" app/services/gated_ingest.py
  ```

  預期：第一個 3 行命中；第二個輸出 **`1`**（只剩 `_盡力清雲端` 裡面那一處）

- [x] **落庫順序：photo_ids 寫在清 S3 之前（總覽 §10.2 R）**

  ```bash
  grep -n -A5 "photo_ids=\[photo_id\]" app/services/gated_ingest.py
  ```

  預期：恰 1 處命中；接下來五行是「空行 → ⑥ 的兩行註解 → `_盡力清雲端(cloud, job_id)` →
  `ingest_job.finish_image_job(...)`」（由上到下就是 INSERT → 寫 photo_ids → 清 S3 → 收尾）
  ——`-A4` 會**剛好少印**最後那一行 `finish_image_job`，所以這裡是 `-A5`

- [x] **兩個檔仍然零 boto3、零 SQL**（兩條分開查，因為判準不同）

  ```bash
  # (1) boto3／botocore 只看 import 句——docstring 本來就會提到「boto3」這個字（Phase 83 的掃碼也只認 import）
  grep -nE "^\s*(import|from) +(boto3|botocore)" app/services/cloud_ingest.py app/services/gated_ingest.py \
    || echo "OK：零 boto3 import"
  # (2) design3 的四個資料庫字樣**連註解都不准出現**（既有 test_SQL只出現在repository與db層 是子字串比對）
  grep -nE "psycopg|get_connection|cursor\(|\.execute\(" app/services/cloud_ingest.py app/services/gated_ingest.py \
    || echo "OK：零資料庫字樣"
  pytest tests/integration/test_design3_error_paths.py -q
  ```

  預期：前兩句各印一行 `OK：…`（任何一句印出命中行就是要改，**改註解也算**）；第三句全綠

- [x] **兩支時鐘 helper 都在、而且只在該在的地方**

  ```bash
  grep -n "^def 假裝過了\|^def 讓時鐘一直走" tests/unit/test_cloud_ingest_unit.py
  grep -c "^def 讓時鐘一直走" tests/integration/test_gated_ingest.py
  # ⚠ 樣式要用 "^ +"（縮排開頭＝呼叫），不能只寫 "假裝過了(monkeypatch"
  #   ——那樣會連 def 那一行自己也命中，這一句就永遠印不出 OK
  grep -nE "^ +假裝過了\(monkeypatch" tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py \
    || echo "OK：本 phase 沒有測試呼叫凍結版（Phase 89 才會）"
  ```

  預期：第一句 2 行（`假裝過了` 凍結、`讓時鐘一直走` 會走）；第二句印 `1`；第三句印 `OK：…`

- [x] **新測試 10 顆全綠**

  ```bash
  pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py -q
  ```

  預期：`41 passed`

- [x] **全量 pytest 顆數 ＝ 開工基線 ＋ 11**（R14）

  ```bash
  pytest -q
  ```

  預期：**開工基線 ＋ 11**、**0 skipped**（總覽 §9 是 `609 passed`；實查 602 → 613，R14 多 1 顆）

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

  預期：**與上一項逐字相同的顆數**（總覽 §9 是 `609 passed`）——差一顆就代表有測試偷連外部服務

- [x] **沒有任何測試會真的等**（本 phase 全是逾時測試，最容易寫成真的睡 5 分鐘）

  ```bash
  pytest tests/unit/test_cloud_ingest_unit.py tests/integration/test_gated_ingest.py --durations=5 -q
  ```

  預期：最慢的那幾顆都在 1 秒以內

- [x] **專案的 `data/` 沒被弄髒**

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都沒有輸出

- [x] **git 收尾（本次全程不 commit）**：照步驟 7 跑一次
  `.superpowers/sdd/phase0901/snapshot-tree` 記下做完的 tree SHA，並核對
  `git status --short -- app tests` 的變更項恰為本 phase 的 4 個檔；
  計畫檔**留在** `docs/plan/unfinish/`（不搬 `finish/`——`git mv` 會直接 stage）

---

## 7. 常見陷阱

1. **測試跑不完（卡住好幾分鐘）。**
   `wait_result` 是「等到 deadline」的迴圈，而 `FakeMailbox.receive_result` **不會真的等**
   ——它立刻回 `None`。所以只要沒接管 `_now()`，那個迴圈就會**全速空轉**到逾時秒數為止
   （`timeout_seconds=5` 還好，`300` 就是五分鐘的 100% CPU）。
   **每一顆會進 `wait_result` 迴圈的測試都要先呼叫 `讓時鐘一直走(monkeypatch)`**
   ——是「會走」那支，不是凍結的 `假裝過了`（拿錯的下場見陷阱 9）。

2. **`monkeypatch.setattr("app.services.cloud_ingest._now", …)` 打錯對象。**
   一定要打在**模組物件**上（`monkeypatch.setattr(cloud_ingest, "_now", …)`），
   而且產品碼裡必須寫 `_now()`（模組層函式呼叫），不可以寫成
   `from time import monotonic` 再直接用——那樣就沒有接縫可以換了。

3. **規則 3 的兩種情況做反了（還在等的刪掉、沒人等的還回去）。**
   症狀非常詭異：兩筆一起上傳時，**兩筆都會逾時 fallback**（互相把對方的訊息還來還去，
   或互相把對方的結果刪掉）。三顆單元測試就是為了把這兩種情況分開釘死。

4. **收到別人的訊息時忘了 `_sleep`。**
   還回去之後它立刻又會被自己收到（假信箱是放回**前端**的），於是變成一個
   「收 → 還 → 收 → 還」的全速迴圈，CPU 直接滿載。真 SQS 也一樣
   （可見度改成 0 ＝ 馬上重新出現）。

5. **崩潰重送時「順手再 submit 一次比較保險」。**
   不保險，是**浪費**：上一趟的 input 與 jobs 訊息都還在，工人可能正在看那張圖。
   再送一次 ＝ 工人看兩次（雲端看圖是要錢的）＋ S3 多一份垃圾 ＋ results 佇列多一則
   之後沒人要的訊息。

6. **`_用雲端結果落庫` 的冪等檢查被改到 `understanding` 判斷後面。**
   順序很重要：**先看 `photo_ids`**（那是「上一趟做完了」的唯一證據），
   再解析結果。反過來的話，遇到「上一趟成功、但這次 result.json 剛好壞掉」
   就會把一筆**已經入庫成功**的任務標成 failed。

7. **`_盡力清雲端` 被還原成直接 `cloud.cleanup(job_id)`。**
   崩潰重送那條路上，`cloud` 有可能是 `CloudRouteOff`（使用者半路把 `CLOUD_ROUTE`
   改回 `off`），它的每一支方法都會丟 `RuntimeError`——那會讓整個 Celery 任務炸掉，
   使用者看到一列莫名其妙的失敗，而那張照片其實只要走本機就好。

8. **以為「job 被 delete 之後 store.get 還查得到」。**
   `記得最後一筆的Store` 只是把**刪掉之前**的快照抄一份到 `deleted`；
   `store.get(job_id)` 在成功之後一律是 `None`。測試要驗 `route`／`photo_ids`
   一律去 `store.deleted[job_id]` 拿。

9. **兩支時鐘 helper 拿反了。**
   `假裝過了()` 是**凍結**時鐘（撥到「現在＋N 秒」就停住）；`讓時鐘一直走()` 是**會走**的時鐘
   （每問一次再過 N 秒）。拿凍結的去測 `wait_result`：deadline 是進迴圈前用 `_now()` 算的，
   時鐘不動的話「剩下」永遠等於逾時秒數，**迴圈永遠跑不完**（症狀同陷阱 1）。
   反過來拿會走的去測 Phase 89 的 `Ec2Probe` TTL：那個快取記的是「上次問」的**真時鐘**秒數
   （幾千秒），而 `讓時鐘一直走` 從 0 起算，「過了幾秒」變成負數，快取永遠不過期，
   `test_TTL過了會再打一次`（總覽 §2.7 Phase 89）會紅——而且症狀是「快取永遠不過期」，
   不是卡住，很難聯想到時鐘拿錯。
   名字要對得上專案既有慣例：`tests/unit/test_camera_session_unit.py` 的 `假裝過了` 就是凍結語意，
   所以「會走」那支**不可以**叫 `假裝過了`。

10. **不懂 results 佇列的可見度逾時為什麼是 30 秒（總覽 §2.8），以為改大一點比較安全。**
    30 秒＝「本機拿到一則結果訊息之後，最多 30 秒沒刪它，它就會重新出現給別人」。
    這個數字刻意很短：本機拿到**自己的**訊息之後只做兩件事（GetObject＋刪訊息，一秒內完事）；
    **別人的**訊息則被 `release` 立刻還回去（可見度改 0），根本不靠它自然過期。
    真正靠它的只有「本機拿到自己的訊息、刪之前就崩潰」這一種：訊息 30 秒後重新出現 →
    下一筆任務撿到它、`store.get` 查得到而且 route 還是 cloud → 還回去（在崩潰那筆被重送之前，
    這則訊息會被還來還去，每次歇 1 秒——總覽 §8.9 的已知代價）→ 崩潰那筆被佇列重送、
    走 `_繼續雲端路` 用 S3 上的結果落庫（它**不會**去 results 佇列收那則訊息）、job 刪掉 →
    再下一筆撿到它時 `store.get` 是 None → 當殘訊息刪掉並清 S3。改成 900 秒的話，
    這條自我修復的路每一步都要多等 15 分鐘；改成 0 則等於沒有「隱形」，兩個 Celery 子行程會同時拿到同一則。

11. **把 `_用雲端結果落庫` 第 ⑤ 步那行 `store.update(job_id, photo_ids=[photo_id])` 刪掉，理由是
    「`finish_image_job` 反正會再寫一次，重複」。**
    不是重複，是**保險**（總覽 §10.2 R）：中間隔著 `cleanup` 這個網路呼叫（boto3 遇到暫時性錯誤會自己
    重試，可以拖幾十秒）。殺在那幾十秒裡，job 沒有 photo_ids、S3 的 result.json 可能已經刪了 →
    重送 → `fetch_result` 拿不到 → 退回本機 → `run_ingest_job` 看不到 photo_ids → **第二張照片**。
    `test_崩潰重送route是cloud而且S3有結果_直接落庫零submit` 最後那個斷言（寫 photo_ids 的流水帳
    位置要在 `delete_objects` 之前）就是為了抓這一刀。

12. **把 `_繼續雲端路` 裡的 `最新 = store.get(job_id) or job` 改回直接用 `job`，理由是
    「開頭才剛讀過，重複」。**
    不是重複：`JobStore.get()` 回的是**複本**（`ingest_job_store._copy()`，Redis 版天生如此），
    而開頭讀完之後這條路上還隔著一次 `fetch_result`（S3 網路呼叫）。Celery 是
    `--concurrency=2`（總覽 §8.8），同一個 `job_id` 被兩個子行程同時撿到時，舊複本看不到
    另一邊剛寫進去的 `photo_ids` ⇒ **INSERT 第二張照片**（而本專案沒有刪除照片的功能）。
    重讀關不掉整個窗口（那要資料庫層的唯一鍵，本增量不做），但能把它縮到「`store.get` 到
    INSERT」這幾行。⚠ 這一刀**兩顆冪等測試都抓不到**（單執行緒測試看不出複本與正本的差別），
    所以它只能靠這條註解與 review 守著——別因為「測試照樣綠」就把它刪掉。

---

## 8. 完成後的專案狀態

雲端路的**單圖**部分完全做完了：順利的一圈（Phase 79）＋ 四種不順利（78／79／80）。

- `app/services/cloud_ingest.py`：`wait_result()` 五條規則齊全，多一支 `_處理別人的訊息()`；
  `TYPE_CHECKING` 那段註解不含資料庫驅動套件的名字（design3 掃碼是子字串比對，既有測試仍綠）。
- `tests/unit/test_cloud_ingest_unit.py`：兩支時鐘 helper——`假裝過了`（凍結，本 phase 沒有測試用它，
  Phase 89 才會）與 `讓時鐘一直走`（會走，本 phase **八顆**會進迴圈的測試都用它：單元 5 顆全部
  ＋ 整合的兩顆逾時與「送兩次」那顆；兩顆 `test_崩潰重送…` 不進迴圈，所以沒收 `monkeypatch`）。
- `app/services/gated_ingest.py`：多一條 `route == "cloud"` 的重送分支
  （`_繼續雲端路()`）與 `_盡力清雲端()`；所有清 S3 的呼叫都走後者；落庫順序固定為
  INSERT → 立刻寫 photo_ids → 清 S3 → 收尾（總覽 §10.2 R）；`_理解()` 用 `model_validate`。

**design6 §8 錯誤表現在十列裡有七列已經有測試把關**：第 1、2、3 列（78）、第 4、7 列（79）、
第 5、6 列（80）。其中兩列**還會再補**（總覽 §3.3）：第 2 列 Phase 89 補
`test_實例狀態stopped與stopping與pending都是False`、第 6／7 列 Phase 87 補工人端那一半、
第 7 列 Phase 95 再補一顆「雲端看圖三次失敗是整筆失敗不是 fallback 本機」。
剩下第 8 列（格式 415，既有測試已守）、第 9 列（OIDC，Phase 93）、第 10 列（誤開 NAT，Phase 95）。

**對外行為仍然零改變**：`CLOUD_ROUTE` 預設 `off`、端點仍 **22**、`photo` 表零改動、前端零改動。

**留給下一個 phase 的接口**（Phase 81 會用到）：

| 名字 | 在哪裡 | Phase 81 怎麼用 |
|---|---|---|
| `_用雲端結果落庫(job, result, *, store, embeddings, now, cloud)` | `gated_ingest.py` | 在它裡面依 `content_type` 分流出 PDF 分支 |
| `_轉向量`／`_理解`／`_盡力清雲端` | 同上 | PDF 的每一頁都會用到 |
| `_繼續雲端路` | 同上 | PDF 的崩潰重送走同一條（靠 `pages_done` 續跑） |
| `讓時鐘一直走(monkeypatch, 每次秒數)`（會走） | 兩個測試檔各一份 | **81 用不到**（它的 7 顆都不會進逾時迴圈：假工人一收就回結果、重送走 `fetch_result`），不必留 |
| `假裝過了(monkeypatch, 秒數)`（凍結） | 只在 `tests/unit/test_cloud_ingest_unit.py` | 81 用不到；**Phase 89** 的 `Ec2Probe` TTL 測試沿用它（那份文件寫「Phase 80 已定義就跳過不貼」，簽章 `假裝過了(monkeypatch, 秒數: float) -> None` 已對齊） |
| `放一份結果(信箱, job_id, understanding)` | `tests/integration/test_gated_ingest.py` | 81 寫一個 PDF 版本（`kind="pdf"` ＋ `pages`） |

下一步：**Phase 81** 讓 PDF 也走雲端路（`result["pages"]` 逐頁與本機 `render_pages()` 配對），
做完就到 **★G1**——甲的驗收，產品負責人點頭之後才可以開始碰 AWS。

測試累計 ＝ 開工基線 ＋ **11**（總覽 §9 記的是 609；R1 若讓 Phase 78 多一顆就是 610）。
**實查（2026-09-01 實作當下）：開工基線 602 → 做完 613 passed、0 skipped。**
基線之所以是 602 而不是 599／600：R10 與 R13 兩條 review 裁決在 74〜79 期間共多加了 3 顆。
本 phase 是 **+11**（總覽 §2.7 的 10 顆 ＋ 裁決 R14 的
`test_等結果時信箱丟例外_fallback本機而且清乾淨` 1 顆，見 §3「做」第 4 點）——
**比總覽多 1 顆**。端點 **22**（不變）。
本次全程**不 commit**，驗收看快照相減（步驟 7）。

---

## 附：本文件引用的官方文件

- [SQS Standard Queue（at-least-once、不保證順序）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS `ChangeMessageVisibility`（改成 0 ＝ 立刻還回佇列）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ChangeMessageVisibility.html)
- [SQS 可見度逾時（visibility timeout）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [S3 Lifecycle（本專案的掃把：`documents/` 2 天過期）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [Python `time.monotonic()`（單調時鐘）](https://docs.python.org/3/library/time.html#time.monotonic)
- [pytest `monkeypatch.setattr`（換掉模組屬性）](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
