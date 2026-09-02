# Phase 89：EC2 探測 running（`Ec2Probe` ＋ 60 秒 TTL 快取）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做這四件事：①**不要建立任何 EC2**（★G2 還沒過，
> 一台機器都不准開——本 phase 的測試用假信箱，沒有 EC2 也測得完）；
> ②不要做「自動幫你開機」（`start-instances`）——那會把「用完就 Stop、卡片 $0」
> 這個前提整個打掉（design6 D15、§1.2 第 9 列）；③不要為了「更準」把 TTL 拿掉
> 或改成每張圖都問；④不要在探測失敗時往外丟例外——那會讓照片入不了庫。

> 🎯 **一句話目標：** 在 `app/services/cloud_ingest.py` 加一個 `Ec2Probe`：
> 它用 `mailbox.instance_state(instance_id) == "running"` 判斷遠端能不能用，
> 答案快取 `config.EC2_PROBE_TTL_SECONDS`（預設 60）秒，任何例外一律回 `False` 並留 log；
> 然後把 `dependencies.get_cloud_route()` 的最後一個暫時分支 `ec2` 補上
> ——**做完之後那個函式裡再也沒有 `NotImplementedError`。**

**為什麼要做這個：**

到 Phase 88 為止，本機要判斷「遠端能不能用」只有兩種答案：`off`（永遠不能）
與 `assume`（永遠能）。而現實是**這台 EC2 平常是 Stop 的**——產品負責人要卡片 $0，
用完就關（design6 D15）。所以「遠端關著」才是**常態**，不是例外。

`assume` 模式在機器關著時會怎樣？它會傻傻地把檔案 PutObject 上去、發一則 jobs 訊息，
然後在 results 佇列上空等到 `CLOUD_RESULT_TIMEOUT_SECONDS`（預設 300 秒）才 fallback。
照片最後還是會入庫（fallback 有接住），但**每一張都白白慢了五分鐘**，
而且 S3 上會留下沒人來拿的垃圾。

`Ec2Probe` 就是那句「先問一下」：**不是 `running` 就直接走本機**，
使用者完全感覺不到差別——這正是 **Demo 2b**（design6 §12）要證明的事。

那為什麼要快取？因為「每上傳一張照片就問一次 AWS」很浪費：
`DescribeInstances` 本身不收費，但它是一次跨海的網路往返（東京來回約 50〜200 毫秒），
而且 AWS 對它有速率限制。EC2 從 `stopped` 變成 `running` 本來就要一分鐘上下，
所以 **60 秒內問一次就夠了**——design6 D10 第 1 條寫的「快取可短 TTL」就是這個意思。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **`DescribeInstances`** | AWS EC2 的一支查詢 API：「這台機器現在什麼狀態？」本專案只用它讀狀態，**從來不用它開機或關機** |
| **instance state（實例狀態）** | 一台 EC2 的六種狀態：`pending`（開機中）、`running`（開著）、`stopping`（關機中）、`stopped`（關著）、`shutting-down`／`terminated`（銷毀中／已銷毀）。**只有 `running` 才算可用** |
| **Stop vs Terminate** | **Stop ＝關機**（硬碟留著，開回來東西還在）。**Terminate ＝銷毀**（整台連硬碟一起消失，不可逆）。本專案一律 Stop |
| **TTL（time to live，存活時間）** | 「這個答案可以用多久」。本專案 60 秒：60 秒內再問，直接給上次的答案，不打 AWS |
| **快取（cache）** | 把上次算好的答案先收著，下次直接用。它的代價永遠是「可能是舊的」——所以要配一個 TTL |
| **單調時鐘（monotonic clock）** | 一種**只會往前走**的計時器（`time.monotonic()`）。它不受使用者調系統時間、也不受 NTP 校時影響，所以算「過了幾秒」一定用它，不要用 `datetime.now()` |
| **seam（可替換接縫）** | 程式裡刻意留的一個「換手處」。這裡是模組層的 `_now()`：正式執行是單調時鐘，測試 monkeypatch 它就能「假裝過了 61 秒」，不必真的等一分鐘 |
| **`lru_cache`** | Python 標準函式庫的一個裝飾器，意思是「同樣的參數只算一次，之後直接給上次的結果」。本專案已經用它讓 `OllamaVLM` 等物件整個行程只建一次（`app/dependencies.py`） |
| **stub（替身）** | 測試裡臨時捏的一個小物件，只實作被測程式真正會呼叫的那幾個方法。本 phase 用一個「只有 `instance_state()`、而且一定丟例外」的 stub 測失敗路徑 |

---

## 1. 對應 design6.md 章節

| 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D10 第 1 條** | EC2 實例狀態不是 `running`（`DescribeInstances`；**快取可短 TTL**，避免每張圖都打 AWS） | `Ec2Probe.is_running()` ＋ `EC2_PROBE_TTL_SECONDS`（預設 60）；`test_TTL內不會再打一次DescribeInstances` 用計數器釘住 |
| **D10 第 2 條** | 沒有 AWS 憑證、或 STS／S3／SQS API 失敗 → 遠端不可用 | `except Exception` → `logger.warning` ＋ 回 `False`；**絕不往外丟** |
| **§2.1 Fallback 契約** | 遠端不可用時這筆 job 改走既有 `run_ingest_job` | 本 phase 只負責「回答可不可用」，fallback 那一段是 Phase 78 已經寫好的 |
| **§8 錯誤表第 2 列** | 非敏感、EC2 Stop → 本機 `run_ingest_job`；202 與進度面板不變 | `test_實例狀態stopped與stopping與pending都是False` |
| **§8 錯誤表第 3 列** | 非敏感、無 AWS 憑證 → 同上 | `test_探測丟例外時回False並留log` |
| **§12 Demo 2b** | EC2 Stop 後上傳非敏感；**不必改任何設定**；S3 不出現新物件 | 本 phase 提供「不必改設定」的那個零件（`CLOUD_ROUTE=ec2` 固定不動，靠探測轉彎）；真機驗收是 Phase 92 |
| **§1.2 第 9 列（被否決）** | 常開 EC2 換「永遠卸壓」 | 探測回 `False` 就 fallback，**不會**自動幫你把機器開起來（§3「明確不做」第 1 列） |
| **總覽 §2.4.1** | `Ec2Probe(mailbox, instance_id, *, ttl_seconds)` 的簽章 | §4 步驟 4 ② 逐字照抄 |
| **總覽 §2.4.1（`dependencies.py` 那段註解）** | `ec2` 模式用 `@lru_cache(maxsize=1)` 的 `_ec2_cloud_route()` 建一次共用 | §4 步驟 5 |
| **總覽 §2.4.2** | `EC2_PROBE_TTL_SECONDS = 60`、`EC2_WORKER_INSTANCE_ID`（空） | Phase 77 已經把這兩個放進 `config`，本 phase **只引用** |
| **總覽 §2.7 Phase 89** | 7 顆測試的名稱、動到的四個檔 | §4 步驟 2 逐字沿用 |

---

## 2. 前置條件

**★ 閘門 G1 已由產品負責人通過。**
**★ 閘門 G2 還沒到**（它在 Phase 90 之後）——所以本 phase **一台 EC2 都不准開**。
這不影響進度：`Ec2Probe` 的七顆測試全部用假信箱／stub，**沒有 EC2 也測得完**，
真機驗證是 Phase 92 的事。

**要先做完的 phase：**

| Phase | 本 phase 會用到它的什麼 |
|---|---|
| 77 | `cloud_ingest.py` 這個檔、`CloudMailbox` Protocol（含 `instance_state`）、`RemoteProbe` Protocol、`config.EC2_WORKER_INSTANCE_ID`／`EC2_PROBE_TTL_SECONDS`、`tests/fakes.py` 的 `FakeMailbox`（含 `instance_state_script`／`instance_state_calls`／`calls` 流水帳）；`tests/unit/test_cloud_ingest_unit.py` 裡那顆 `test_get_cloud_route預設off時回CloudRouteOff`（Phase 77 在裡面放了一個「ec2 還是 NotImplementedError」的**鬧鐘**，本 phase 要拆掉它，見步驟 2c） |
| 79 | `CloudRoute` 本體（`available()` 會呼叫 `probe.is_running()`，而且吞例外）；**模組層的 `_now()`／`_sleep()` 兩個時間接縫**（`wait_result` 的 deadline 用）——本 phase 的 TTL 直接呼叫同一個 `_now()`，**不加第二個** |
| 80 | `wait_result` 完整版；它的逾時測試已經 monkeypatch 過 `cloud_ingest._now`（步驟 2a 的 `假裝過了` helper 就是沿用它的） |
| 83 | `AwsMailbox.instance_state()`（真的打 `DescribeInstances` 的那一支；查無回 `"unknown"`） |
| 86 | `dependencies.get_cloud_route()` 的 `assume` 分支與 `tests/unit/test_dependencies_cloud_unit.py` 這個檔（那 2 顆測試用的是**早綁定**的 `from app.dependencies import get_cloud_route as 原本的get_cloud_route`，本 phase 的第 7 顆用**同一個名字**；它的 `get_cloud_route()` 一律以**模組屬性** `cloud_ingest.CloudRoute(...)`／`cloud_ingest.AlwaysRunning()` 建物件——它的第 2 顆測試靠 `monkeypatch.setattr(cloud_ingest, "CloudRoute", …)` 側錄建構參數，直接 import 名字就換不到——本 phase 的 `ec2` 分支與 `_ec2_cloud_route()` 比照） |
| 88 | 與本 phase 無直接相依，但它是總覽排定的前一個 phase（顆數基線來自它） |

**開工前實查基線**（在專案根目錄執行）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc          # db 要 Up (healthy)
pytest --collect-only -q | tail -1    # 預期：651 tests collected
pytest -q                             # 預期尾巴：651 passed，0 skipped
git branch --show-current             # 預期：main
```

> **開工基線 ＝ 651**（Phase 88 收工的數字）。本 phase 結束時應該是 **658**（+7）。
> （與總覽 §9 一致：651 → 658。交錯做的話絕對數字會不一樣——**要對的是「本 phase 新增 7 顆」**。）

再確認三個前置零件真的在（沒有就先回去做對應的 phase）：

```bash
python -c "
from app.core import config
from app.services import cloud_ingest
from tests.fakes import FakeMailbox
信箱 = FakeMailbox()
print('TTL 預設：', config.EC2_PROBE_TTL_SECONDS)
print('instance_id 預設是空的：', config.EC2_WORKER_INSTANCE_ID == '')
print('假信箱有 instance_state：', hasattr(信箱, 'instance_state'),
      hasattr(信箱, 'instance_state_script'), hasattr(信箱, 'instance_state_calls'))
print('CloudRoute 在：', hasattr(cloud_ingest, 'CloudRoute'),
      'AlwaysRunning 在：', hasattr(cloud_ingest, 'AlwaysRunning'))
print('_now 接縫在（Phase 79 建的）：', callable(getattr(cloud_ingest, '_now', None)))
"
```

預期：`TTL 預設： 60`、其餘都是 `True`。
最後一行是 `False` 的話代表 Phase 79 沒做完（它的 `wait_result` 靠這個接縫算 deadline）——
**回去補 Phase 79，不要在本 phase 自己加一個**。

> ⚠️ **絕對不要同時跑兩份 pytest**（會互相 `TRUNCATE` 測試庫，症狀是大量看似隨機的
> 404 與 `TypeError: 'NoneType' object is not subscriptable`）。

---

## 3. 範圍

### 做

1. `app/services/cloud_ingest.py`：
   - `class Ec2Probe`（`is_running()` ＋ TTL 快取 ＋ 例外一律 `False`）。
     時基**直接呼叫 Phase 79 建好的模組層 `_now()`**（`wait_result` 的 deadline 也是用它）；
     **全檔只准有這一個 `_now()`**，本 phase 不新增、不改它。
2. `app/dependencies.py`：
   - `_ec2_cloud_route()`（`lru_cache`，整個行程只建一次）
   - `get_cloud_route()` 補上 `ec2` 分支，**拿掉最後一個 `NotImplementedError`**
     （`off`／`assume` 兩支與最後那行「打錯字就 `ValueError`」**原封不動**；建物件一律走**模組屬性**
     `cloud_ingest.CloudRoute(...)`／`cloud_ingest.Ec2Probe(...)`／`cloud_ingest.AlwaysRunning()`，
     與 Phase 86 同一規則——它的側錄測試靠這一點 monkeypatch）
3. `tests/unit/test_cloud_ingest_unit.py` 追加 6 顆；同檔 Phase 77 那顆
   `test_get_cloud_route預設off時回CloudRouteOff` 裡「`ec2` 仍是 `NotImplementedError`」的鬧鐘段**刪掉**
   （Phase 77 寫它的時候就註明「Phase 89 接上時會紅，把它拆掉」；顆數不變）。
4. `tests/unit/test_dependencies_cloud_unit.py` 追加 1 顆（＋一個清快取的 autouse fixture）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 探測到 `stopped` 就自動 `start-instances` 幫你開機 | design6 §1.2 第 9 列已否決「常開 EC2」；D15 是「用完就 Stop、卡片 $0」。而且開機要一分鐘上下，那張照片還是得等——不如直接走本機（本來就比較快） |
| 把 TTL 拿掉、或改成「每張圖都問一次」 | D10 第 1 條明文要快取。60 秒的代價是「剛開機的頭一分鐘可能還是走本機」——完全可以接受 |
| 把 TTL 做成可以在執行中調整、或做成 LRU 多實例快取 | 一個專案只有一台工人機器。多一個旋鈕就多一種「兩邊設定不一樣」的壞法 |
| 探測失敗時往外丟例外 | design6 §8 第 3 列：沒有憑證要 **fallback**，不是讓照片入不了庫。任何例外都回 `False` |
| 用 `datetime.now()` 算時間差 | 使用者調時間或 NTP 校時會讓它倒退，快取可能一整年不過期。一律 `time.monotonic()` |
| 在 `cloud_ingest.py` 裡 import boto3 | 總覽 §7 鐵律 5：boto3 只准出現在 `aws_mailbox.py`。`Ec2Probe` 只認 `CloudMailbox` 這個 Protocol，所以假信箱就測得完 |
| 在 `cloud_ingest.py` 裡再加一個 `_now()`（或在 `Ec2Probe` 裡直接寫 `time.monotonic()`） | Phase 79 已經有一個模組層的 `_now()`。兩份時基會漂移，而且測試 monkeypatch 只蓋得到其中一個（§7 陷阱 1） |
| 把 `get_cloud_route()` 最後那行 `raise ValueError` 拿掉、或讓不認得的值默默變成 `off` | Phase 77 的測試 `test_get_cloud_route預設off時回CloudRouteOff` 釘住「打錯字要當場炸」。拿掉它 ＝ 那顆紅 ＋「我明明開了雲端路怎麼都沒送出去」這種最難查的壞法回來了 |
| 建立 EC2、security group、IAM role | Phase 91／92，而且要等 **★G2** |
| 把 `CLOUD_ROUTE` 的預設值改成 `ec2` | 預設永遠是 `off`（總覽 §2.4.2）：新 clone 的人、CI、pytest 都不該碰 AWS |
| 幫 `Ec2Probe` 加「連續失敗 N 次就……」的斷路器 | 快取已經把失敗也收下了（60 秒內不會重打）。再多一層狀態機是過度設計 |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：步驟 1 先確認 `_now()` 這個 seam 在 →
> 步驟 2 寫**會紅**的 7 顆（＋拆掉 Phase 77 的鬧鐘）→ 步驟 3 跑它看到紅 → 步驟 4〜5 寫實作 →
> 步驟 6 轉綠 → 步驟 7 全量回歸與 ruff → 步驟 8 commit。

### - [ ] 步驟 1：確認 `cloud_ingest.py` 的 `_now()` 在（Phase 79 建的）

`CloudRoute.wait_result()`（Phase 79）要算「還剩幾秒到 deadline」，所以 Phase 79
已經在 `cloud_ingest.py` 加了模組層的 `_now()`（與 `_sleep()`），寫法沿用
`app/services/camera_session_service.py`。本 phase 的 TTL **直接呼叫它**。先查：

```bash
grep -n "^import time\|^def _now\|^def _sleep" app/services/cloud_ingest.py
```

預期恰好三行命中：`import time`、`def _now() -> float:`、`def _sleep(seconds: float) -> None:`。

- **三行都在** → 本 phase 的程式碼裡凡是要「現在幾秒」一律寫 `_now()`，繼續步驟 2。
- **少了 `_now`** → Phase 79 沒做完，**回去補 Phase 79**。⚠ 千萬不要在本 phase 自己加一個：
  兩份時基會漂移，而且 Phase 80 的逾時測試與本 phase的 TTL 測試 monkeypatch 到哪一個都說不準。

### - [ ] 步驟 2：先寫會紅的 7 顆測試

#### 2a. `tests/unit/test_cloud_ingest_unit.py` 追加 6 顆

打開 `tests/unit/test_cloud_ingest_unit.py`（Phase 77 建、79／80 加長過）。

**時間 helper 沿用 Phase 80 定義在同一檔的 `假裝過了(monkeypatch, 秒數: float)`**
（凍結語意：把 `_now` 換成「現在＋秒數」的函式；同檔已存在，下面那段**不再定義一次**）。先確認它在：

```bash
grep -n "^def 假裝過了" tests/unit/test_cloud_ingest_unit.py
# 預期恰 1 行。0 行＝Phase 80 還沒做完（80 → 88 → 89 是必經順序），先回去做完再來
```

然後在檔案**最後面**加上這一整段：

```python
# ---------------- Ec2Probe：問「那台機器開著嗎」（Phase 89）----------------


class 會爆炸的信箱:
    """只有 instance_state()，而且一定丟例外——模擬憑證過期／權限不足／網路斷。

    為什麼不用 FakeMailbox：那顆假件的 instance_state_script 是一串**字串**，
    排不出「這一次丟例外」。而這裡要驗的正是「炸了也要回 False，不可以往外丟」。
    只實作被測程式真的會呼叫的那一個方法，就是 stub 的用法。
    """

    def __init__(self) -> None:
        self.instance_state_calls = 0

    def instance_state(self, instance_id: str) -> str:
        self.instance_state_calls += 1
        raise RuntimeError("AWS 憑證過期")


def 做一個探測(狀態們: list[str], *, instance_id: str = "i-測試", ttl_seconds: int = 60):
    """回 (探測物件, 假信箱)。假信箱的 instance_state 會依序回傳 狀態們。"""
    信箱 = FakeMailbox()
    信箱.instance_state_script = list(狀態們)
    return cloud_ingest.Ec2Probe(信箱, instance_id, ttl_seconds=ttl_seconds), 信箱


def test_實例狀態running時探測為True():
    """只有 running 才算可用——這是雲端管線唯一的入場券。"""
    探測, 信箱 = 做一個探測(["running"])

    assert 探測.is_running() is True
    assert 信箱.instance_state_calls == 1


def test_實例狀態stopped與stopping與pending都是False():
    """design6 §8 第 2 列：EC2 Stop → 本機 run_ingest_job，202 與進度面板不變。

    這裡把六種狀態裡「不是 running」的五種都走一遍：pending 是**開機中**
    （機器還沒準備好收訊息）、stopping 是**關機中**（拿了訊息也做不完）。
    最後多一個 "unknown"：那是 Phase 83 的 AwsMailbox.instance_state() 在
    「查無這台機器」時回的字串（instance id 打錯／機器被 Terminate 超過一小時）。
    每一種都用一顆全新的探測物件，免得被 TTL 快取蓋住。
    """
    for 狀態 in ("pending", "stopping", "stopped", "shutting-down", "terminated", "unknown"):
        探測, 信箱 = 做一個探測([狀態])

        assert 探測.is_running() is False, f"{狀態} 不是 running，不可以送去雲端"
        assert 信箱.instance_state_calls == 1


def test_探測丟例外時回False並留log(caplog):
    """design6 §8 第 3 列：沒有 AWS 憑證 → fallback 本機。

    ⚠ 這裡**絕對不可以**把例外往外丟：往外丟的話 gated_ingest 那一層會炸，
    一張照片會因為「查不到機器狀態」而入不了庫——完全違反 D10
    「不上傳失敗、不要求使用者重傳」。
    """
    caplog.set_level(logging.WARNING)
    信箱 = 會爆炸的信箱()
    探測 = cloud_ingest.Ec2Probe(信箱, "i-測試", ttl_seconds=60)

    assert 探測.is_running() is False
    assert 信箱.instance_state_calls == 1
    assert any("EC2" in 訊息 for 訊息 in caplog.messages), (
        f"炸掉要留 log，不可以安靜地當作不可用：{caplog.messages}"
    )


def test_TTL內不會再打一次DescribeInstances():
    """D10 第 1 條：快取可短 TTL，避免每張圖都打 AWS。

    劇本第二格是 stopped——如果快取沒生效，第二次就會拿到 False，測試立刻紅。
    """
    探測, 信箱 = 做一個探測(["running", "stopped"], ttl_seconds=60)

    assert 探測.is_running() is True
    assert 探測.is_running() is True, "TTL 內應該直接給上一次的答案"
    assert 信箱.instance_state_calls == 1, "TTL 內不可以再打一次 DescribeInstances"


def test_TTL過了會再打一次(monkeypatch):
    """快取不是永久的：機器真的被 Stop 了，最多 60 秒之後就要看得到。"""
    探測, 信箱 = 做一個探測(["running", "stopped"], ttl_seconds=60)

    assert 探測.is_running() is True
    假裝過了(monkeypatch, 61)

    assert 探測.is_running() is False, "TTL 過了要重新問一次"
    assert 信箱.instance_state_calls == 2


def test_instance_id是空的時候回False而且零呼叫():
    """CLOUD_ROUTE=ec2 卻沒設 EC2_WORKER_INSTANCE_ID ＝ 設定錯誤。

    這時候拿空字串去打 DescribeInstances 只會換來一個看不懂的 AWS 錯誤，
    所以**連問都不要問**：直接當作不可用、留一行 log，照片走本機照樣入庫。
    """
    探測, 信箱 = 做一個探測(["running"], instance_id="")

    assert 探測.is_running() is False
    assert 信箱.instance_state_calls == 0, "沒有 instance id 就不該打 AWS"
```

檔案最上面的 import 區要有這三個名字（已經有的不要重複；位置交給 `ruff check --fix` 的排序規則）：

```python
import logging

from app.services import cloud_ingest
from tests.fakes import FakeMailbox
```

- `FakeMailbox`：Phase 77 建檔時就 import 了，**應該已經在**。
- `cloud_ingest`（**整個模組**）：Phase 77／79 只 `from app.services.cloud_ingest import (…)` 幾個名字，
  **沒有** import 模組本身；Phase 80 為了 monkeypatch `_now` 多半已經加了。沒有就加——
  上面的測試要用 `cloud_ingest._now`／`cloud_ingest.Ec2Probe`，而且 monkeypatch 一定要對著**模組**打。
- `logging`：`caplog.set_level(logging.WARNING)` 要用；Phase 77／79 的測試沒有它。

#### 2b. `tests/unit/test_dependencies_cloud_unit.py` 追加 1 顆

打開 `tests/unit/test_dependencies_cloud_unit.py`（Phase 86 建的），
在檔案**最後面**加上這一段（含一個 autouse fixture）：

```python
# ---------------- ec2 模式（Phase 89）----------------


@pytest.fixture(autouse=True)
def 清掉ec2路的快取():
    """_ec2_cloud_route() 是「整個行程只建一次」的（lru_cache），前後都要清。

    不清的話：這一顆測試建的假信箱會被留給後面的測試，或反過來被上一顆的殘留干擾
    ——症狀是「單獨跑綠、整批跑紅」，最難查的那一種。
    """
    dependencies._ec2_cloud_route.cache_clear()
    yield
    dependencies._ec2_cloud_route.cache_clear()


def test_ec2模式建出CloudRoute而且探測是Ec2Probe(monkeypatch):
    """CLOUD_ROUTE=ec2 時要建出「會真的去問機器狀態」的那一條路。

    怎麼證明它是 Ec2Probe 而不是 AlwaysRunning：讓假信箱回 stopped。
    AlwaysRunning 不管三七二十一都回 True、一次 instance_state 都不叫；
    所以 available() 是 False ＋ instance_state 恰被叫一次、而且問的是
    config.EC2_WORKER_INSTANCE_ID 那台，就只可能是 Ec2Probe。

    ★ 這裡把 AwsMailbox 整個換掉，所以**完全不會**碰到 boto3、也不會出網——
      能這樣換是因為 _ec2_cloud_route() 的 import 寫在函式**裡面**
      （`from … import AwsMailbox` 每次呼叫都會重新去模組上取那個名字）。

    ★ 呼叫的是檔頭早綁定的 原本的get_cloud_route（Phase 86 那 2 顆就是用這個名字）：
      第五道安全網每顆測試都會把 dependencies.get_cloud_route 換成「永遠回 CloudRouteOff」
      的替身，寫 dependencies.get_cloud_route() 拿到的會是替身，這顆就永遠紅。
    """
    建過的: list[dict] = []
    信箱 = FakeMailbox()
    信箱.instance_state_script = ["stopped"]

    def 假的AwsMailbox(**kwargs):
        建過的.append(kwargs)
        return 信箱

    monkeypatch.setattr(aws_mailbox, "AwsMailbox", 假的AwsMailbox)
    monkeypatch.setattr(config, "CLOUD_ROUTE", "ec2")
    monkeypatch.setattr(config, "S3_BUCKET", "桶子")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "jobs-url")
    monkeypatch.setattr(config, "SQS_RESULTS_QUEUE_URL", "results-url")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(config, "EC2_WORKER_INSTANCE_ID", "i-測試")
    monkeypatch.setattr(config, "EC2_PROBE_TTL_SECONDS", 60)

    路 = 原本的get_cloud_route()

    assert isinstance(路, cloud_ingest.CloudRoute)
    # 四個參數都要從 config 來（打錯區或對到別的 bucket 是最難查的設定錯）
    assert 建過的 == [
        {
            "bucket": "桶子",
            "jobs_queue_url": "jobs-url",
            "results_queue_url": "results-url",
            "region": "ap-northeast-1",
        }
    ]
    assert 路.available() is False, "機器是 stopped，探測要說不可用"
    assert 信箱.instance_state_calls == 1, "AlwaysRunning 不會問；問了一次就是 Ec2Probe"
    assert 信箱.calls == ["instance_state i-測試"], "要問的是 config.EC2_WORKER_INSTANCE_ID 那台"
    # 整個行程共用同一條路（lru_cache）：再要一次要拿到同一個物件，而且信箱只建過一次
    assert 原本的get_cloud_route() is 路
    assert len(建過的) == 1
```

檔案最上面的 import 區改成下面這樣（Phase 86 建檔時已經有 `config`／`原本的get_cloud_route`／
`cloud_ingest`／`AwsMailbox` 四行，**本 phase 多四行**：`pytest`、`dependencies`、`aws_mailbox`、`FakeMailbox`；
位置交給 `ruff check --fix`）：

```python
import pytest

from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route as 原本的get_cloud_route
from app.services import aws_mailbox, cloud_ingest
from app.services.aws_mailbox import AwsMailbox
from tests.fakes import FakeMailbox
```

> 📌 三件容易搞混的事：
> - `from app import dependencies` 與 `原本的get_cloud_route` **兩個都要**：前者給 autouse fixture 拿
>   `dependencies._ec2_cloud_route.cache_clear()`（這個私有函式沒有被安全網動過，走模組屬性拿沒問題）；
>   後者是**早綁定**的原版 `get_cloud_route`——安全網 monkeypatch 的是模組屬性，換不掉在收集階段
>   就綁進本檔的這個名字。**名字要跟 Phase 86 一樣叫 `原本的get_cloud_route`**，同一個檔案別出現兩種寫法。
> - `from app.services import aws_mailbox`（模組）與 Phase 86 留下的 `from app.services.aws_mailbox import AwsMailbox`
>   （名字）**可以並存**：Phase 86 的第 2 顆用後者做 `isinstance`；本 phase 要 `monkeypatch.setattr(aws_mailbox, "AwsMailbox", …)`，
>   非得對著**模組**打不可。`_ec2_cloud_route()` 裡的 `from app.services.aws_mailbox import AwsMailbox` 是在
>   **呼叫當下**才去模組上取名字，所以換得到。
> - 本檔的測試**不可以**寫 `dependencies.get_cloud_route()`（§7 陷阱 12）。

#### 2c. 拆掉 Phase 77 留在 `test_cloud_ingest_unit.py` 的鬧鐘（顆數不變）

Phase 77 的 `test_get_cloud_route預設off時回CloudRouteOff` 裡有一段：

```python
    for 模式 in ("assume", "ec2"):
        monkeypatch.setattr(config, "CLOUD_ROUTE", 模式)
        with pytest.raises(NotImplementedError):
            get_cloud_route()
```

它的註解寫得很清楚：「Phase 86 接上 assume、Phase 89 接上 ec2 的時候這兩行會紅——
那是**鬧鐘不是壞掉**」。不管它現在長什麼樣（Phase 86 **應該**已經把 `"assume"` 拿掉；
沒拿掉的話這顆從 Phase 86 起就紅著，那就更該現在清乾淨），
**把這一段連同它上面的註解整段刪掉**——
「ec2 建出什麼」由 2b 那顆新測試正面驗證，這裡不再需要負面斷言。

**保留**同一顆測試的另外兩段：開頭的 `assert isinstance(get_cloud_route(), CloudRouteOff)`
與結尾「`CLOUD_ROUTE=cloudy` 要 `ValueError`」——後者是步驟 5 一定要留住的行為。

確認刪乾淨：

```bash
grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py \
  || echo "OK：測試裡再也沒有人期待 NotImplementedError"
```

預期印出 `OK：測試裡再也沒有人期待 NotImplementedError`。

### - [ ] 步驟 3：跑它，親眼看到紅

```bash
pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -q
```

預期尾巴長這樣（其餘顆數依你的檔案而定）：

```text
6 failed, N passed, 3 errors
```

- **6 failed** ＝ `test_cloud_ingest_unit.py` 本 phase 那 6 顆，錯誤字樣是
  `AttributeError: module 'app.services.cloud_ingest' has no attribute 'Ec2Probe'`。
- **3 errors**（不是 failed）＝ `test_dependencies_cloud_unit.py` **整個檔案的 3 顆**
  （本 phase 的 1 顆 ＋ Phase 86 的 2 顆）。因為 2b 加的 autouse fixture 在**每顆測試開始前**
  就去拿 `dependencies._ec2_cloud_route`，而它還不存在，所以是 fixture 階段的
  `AttributeError: module 'app.dependencies' has no attribute '_ec2_cloud_route'`。
  Phase 86 那 2 顆這時候跟著 ERROR 是**預期的**，步驟 5 做完就一起恢復。
- Phase 77 那顆 `test_get_cloud_route預設off時回CloudRouteOff` 在 2c 拆掉鬧鐘之後**仍然綠**
  （它剩下的兩段都與 ec2 無關）。

### - [ ] 步驟 4：實作 `Ec2Probe`（`app/services/cloud_ingest.py`）

**① 時基**：**不新增任何東西**。Phase 79 建、Phase 80 補了一段 ★ docstring 的模組層 `_now()`
長這樣（貼出來是讓你認得它，**不要再貼一次進檔案**；以檔案裡的為準）：

```python
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
```

下面 `Ec2Probe` 裡凡是要「現在幾秒」都寫 `_now()`——**不要**在 class 裡直接寫
`time.monotonic()`（那樣 `假裝過了()` 就撥不動它，`test_TTL過了會再打一次` 會紅）。

**② `Ec2Probe`**——加在 `AlwaysRunning` 後面（兩個都是 `RemoteProbe` 的實作，放一起）。
本 phase 結束時這個 class 的**完整內容**：

```python
class Ec2Probe:
    """問 AWS「那台工人機器現在開著嗎」，答案快取 ttl_seconds 秒。

    為什麼要快取（design6 D10 第 1 條「快取可短 TTL，避免每張圖都打 AWS」）：
    每上傳一張非敏感照片就要探測一次。DescribeInstances 本身不收費，
    但它是一次跨海的網路往返（東京來回約 50〜200 毫秒），而且有 API 速率限制。
    EC2 從 stopped 變成 running 本來就要一分鐘上下，所以 60 秒內問一次就夠了。

    ★ 快取活在**這個物件身上**。要讓它跨照片生效，整個行程必須共用同一個
      Ec2Probe——所以 dependencies._ec2_cloud_route() 加了 lru_cache（見那裡的說明）。

    ★ 任何例外都當成「不可用」（design6 §8 錯誤表第 3 列）：沒有 AWS 憑證、
      API 掛了、instance id 打錯……全部回 False，讓 gated_ingest 走 fallback。
      **絕對不可以往外丟**——那會讓一張照片因為「查不到機器狀態」而入不了庫，
      直接違反 D10「不上傳失敗、不要求使用者重傳」。

    ★ 它**不會**幫你把機器開起來。design6 §1.2 第 9 列已否決「常開 EC2」，
      D15 是「用完就 Stop」；而且開機要一分鐘上下，那張照片還是得等——
      不如直接走本機（本來就比較快）。
    """

    def __init__(self, mailbox: CloudMailbox, instance_id: str, *, ttl_seconds: int) -> None:
        self._mailbox = mailbox
        self._instance_id = instance_id
        self._ttl_seconds = ttl_seconds
        self._cached: bool | None = None  # None ＝ 還沒問過
        self._cached_at = 0.0

    def is_running(self) -> bool:
        """現在能不能把照片送去雲端。只有狀態是 "running" 才回 True。"""
        if not self._instance_id:
            # CLOUD_ROUTE=ec2 卻沒設 EC2_WORKER_INSTANCE_ID：這是設定錯誤，
            # 但不可以讓照片入不了庫。回 False 走 fallback，並且大聲留 log。
            # 拿空字串去打 DescribeInstances 只會換來一個看不懂的 AWS 錯誤，
            # 所以**連問都不要問**。
            logger.warning("沒有設定 EC2_WORKER_INSTANCE_ID，EC2 一律當作不可用")
            return False

        現在 = _now()
        if self._cached is not None and 現在 - self._cached_at < self._ttl_seconds:
            return self._cached

        try:
            狀態 = self._mailbox.instance_state(self._instance_id)
        except Exception:
            # 憑證過期、權限不足、網路不通……全部當成「不可用」。
            # 失敗的答案**也要進快取**：AWS 壞掉時不該每張照片都再去撞一次牆。
            logger.warning("查不到 EC2 狀態，當作遠端不可用", exc_info=True)
            return self._記住(False, 現在)

        logger.info("EC2 探測：instance=%s state=%s", self._instance_id, 狀態)
        return self._記住(狀態 == "running", 現在)

    def _記住(self, 可用: bool, 現在: float) -> bool:
        """把答案存進快取並回傳它（成功與失敗都存，理由見 is_running 的註解）。"""
        self._cached = 可用
        self._cached_at = 現在
        return 可用
```

### - [ ] 步驟 5：`get_cloud_route()` 補上 `ec2` 分支（`app/dependencies.py`）

打開 `app/dependencies.py`，把 Phase 77 建、Phase 86 改過的 `get_cloud_route()`
**整段換成**下面這一份，並在它**上面**新增 `_ec2_cloud_route()`。

> 📌 下面貼的是**本 phase 結束時這兩個函式的完整內容**（直接整段取代，不必逐行比對）。
> 行為上你真正改的只有兩件事：`ec2` 那一行從 `raise NotImplementedError(...)`
> 變成 `return _ec2_cloud_route()`，以及新增 `_ec2_cloud_route()` 本身。
> **`off`／`assume` 兩支與最後那行 `raise ValueError` 的行為不准動**——
> Phase 77 的 `test_get_cloud_route預設off時回CloudRouteOff` 釘著「`CLOUD_ROUTE=cloudy` 要炸」，
> Phase 86 的 2 顆釘著 `assume` 建出什麼。
> **建物件一律走模組屬性**（`cloud_ingest.CloudRoute(...)`／`cloud_ingest.Ec2Probe(...)`／
> `cloud_ingest.AlwaysRunning()`／`cloud_ingest.CloudRouteOff()`），不要在檔頭
> `from app.services.cloud_ingest import CloudRoute`——Phase 86 的第 2 顆測試靠
> `monkeypatch.setattr(cloud_ingest, "CloudRoute", 側錄CloudRoute)` 側錄建構參數，早綁定的名字換不到。

```python
@lru_cache(maxsize=1)
def _ec2_cloud_route() -> cloud_ingest.CloudRoute:
    """ec2 模式的雲端路，**整個行程只建一次**（手法與 _ollama_vlm 相同）。

    ★ 為什麼一定要共用同一個物件：Ec2Probe 的 TTL 快取是**物件身上的狀態**。
      每次呼叫都 new 一個的話，快取永遠是空的——等於每張照片都打一次
      DescribeInstances，design6 D10 第 1 條要的「避免每張圖都打 AWS」就落空了。
      順便也省下每次重建 boto3 client 的成本（那不是免費的）。

    ★ 代價：改了 .env 之後要重啟 worker 才生效。這與本專案既有的規則一致
      （CLAUDE.md 指令區：「改 .env → restart app worker」）。

    ★ AwsMailbox 的 import 寫在函式**裡面**（與 get_task_dispatcher 同一個理由）：
      pytest 收集階段不必為了一顆字串測試就載入 AWS SDK；
      而且測試可以 monkeypatch aws_mailbox.AwsMailbox 把它整個換掉。
    """
    # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox；與 assume 那支同一句）
    from app.services.aws_mailbox import AwsMailbox

    信箱 = AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )
    # 同一顆信箱同時給 CloudRoute（S3／SQS）與 Ec2Probe（DescribeInstances）用
    return cloud_ingest.CloudRoute(
        信箱,
        cloud_ingest.Ec2Probe(
            信箱,
            config.EC2_WORKER_INSTANCE_ID,
            ttl_seconds=config.EC2_PROBE_TTL_SECONDS,
        ),
        timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
    )


def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    """這一台現在要不要走雲端路、怎麼走。**全系統只有這一個地方決定。**

    三種模式由 config.CLOUD_ROUTE 決定（總覽 §2.4.2）：
      off    → CloudRouteOff()：available() 恆為 False，gated_ingest 直接 fallback 成
               run_ingest_job——行為與增量五**逐字相同**（pytest 與新 clone 的預設）
      assume → CloudRoute ＋ AwsMailbox ＋ AlwaysRunning：假設遠端開著、**不做探測**
               （階段丁：工人跑在這台 Mac 上時用；機器沒開時它會傻傻送出、等到逾時才
               fallback，所以不要拿來當日常設定——總覽 §10.1 追認項 l）
      ec2    → CloudRoute ＋ AwsMailbox ＋ Ec2Probe：用 DescribeInstances 問那台機器
               現在是不是 running（戊之後的日常；整個行程共用一條，見 _ec2_cloud_route）

    ★ 打錯字要當場炸（ValueError），不要默默當成 off：
      「我明明把 CLOUD_ROUTE 設成 cloud 了，怎麼都沒送出去」是最難查的一種壞法。

    ★ 每次呼叫都當場讀一次 config.CLOUD_ROUTE：這樣改 .env ＋ restart worker 就生效，
      不必改程式。

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    模式 = config.CLOUD_ROUTE
    if 模式 == "off":
        return cloud_ingest.CloudRouteOff()
    if 模式 == "assume":
        # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox）
        from app.services.aws_mailbox import AwsMailbox

        信箱 = AwsMailbox(
            bucket=config.S3_BUCKET,
            jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
            results_queue_url=config.SQS_RESULTS_QUEUE_URL,
            region=config.AWS_REGION,
        )
        return cloud_ingest.CloudRoute(
            信箱,
            cloud_ingest.AlwaysRunning(),
            timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
        )
    if 模式 == "ec2":
        # 整個行程共用一條（lru_cache）：Ec2Probe 的 TTL 快取住在物件身上
        return _ec2_cloud_route()
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{模式!r}")
```

> ⚠️ 如果你打開檔案看到 Phase 86 留下的 `assume` 段長得跟上面**不完全一樣**
> （例如變數命名、註解），以**檔案裡現有的那段**為準、只動 `ec2` 那一行——
> Phase 86 的 2 顆測試釘的是行為，不是字面。
>
> ⚠️ **結尾一定要是 `raise ValueError(...)`。** phase-86 §4.3 貼的那份範本結尾是
> 「不認得的值 → `logger.warning` ＋ 回 `CloudRouteOff()`」，但它自己的 📌 說「以 Phase 77 的實際程式碼為準、
> 只換 `assume` 那三行」——而 Phase 77 的程式碼與測試（`CLOUD_ROUTE=cloudy` 要 `ValueError`）都是「打錯字當場炸」。
> 兩邊不一致時 **Phase 77 贏**（它有測試釘著）。如果你的檔案現在是 warning 那種寫法，
> 那顆測試從 Phase 86 起就紅著，本步驟順手改回 `raise ValueError`。

> ⚠️ **`assume` 那一段刻意不加 `lru_cache`**：`AlwaysRunning` 沒有任何狀態，
> 共用它一點好處都沒有；而且 `assume` 是除錯模式，每次讀最新的 `.env` 反而方便。
> 不對稱是**刻意的**，理由已經寫在 `_ec2_cloud_route()` 的 docstring 裡。

做完之後確認暫時分支真的沒了：

```bash
grep -n "NotImplementedError" app/dependencies.py || echo "OK：get_cloud_route 已經沒有暫時分支"
```

預期印出 `OK：get_cloud_route 已經沒有暫時分支`
（Phase 77 那個「其他值先 raise」的暫時分支，到這裡正式除役）。

### - [ ] 步驟 6：跑新測試，看它轉綠

```bash
pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -v
```

預期：全綠，而且本 phase 新增的那 7 顆都在裡面（其餘是 Phase 77／79／80／86 的；
Phase 86 那 2 顆在步驟 3 ERROR 過，現在應該一起回綠）。

### - [ ] 步驟 7：全量回歸與 ruff

```bash
pytest -q
```

預期：**開工基線 ＋ 7**（＝658），全綠、0 skipped。

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

預期：顆數與上一行相同（零外部依賴實證——本 phase 新增的程式碼碰得到 AWS，
所以這一條特別重要：它證明那七顆測試真的沒有出網）。

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期兩句都乾淨。

### - [ ] 步驟 8：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/services/cloud_ingest.py app/dependencies.py \
        tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py
git commit -m "feat: Phase 89 EC2 探測——Ec2Probe 用 DescribeInstances 判斷 running、60 秒 TTL 快取（成功與失敗都快取）、任何例外一律回 False 留 log；get_cloud_route() 補 ec2 分支並移除最後一個 NotImplementedError，+7 tests"
```

> 📌 **commit 節奏由產品負責人決定**（總覽 §7 鐵律 12）。未指示前不要自己 commit。

---

## 5. ASCII 圖

### 5.1 TTL 快取的時間軸（60 秒問一次，其餘直接給上次的答案）

```text
時間 →  0s      5s     10s     30s     59s │ 61s     90s    121s
        │       │       │       │       │  │  │       │       │
上傳    ①       ②       ③       ④       ⑤  │  ⑥       ⑦       ⑧
        │       │       │       │       │  │  │       │       │
        ▼       ▼       ▼       ▼       ▼  │  ▼       ▼       ▼
is_running()                              │
        │       │       │       │       │  │  │       │       │
   ┌────┴───┐   │       │       │       │  │  │       │       │
   │沒有快取│   │  快取還新鮮（現在 − 存的時間 < 60）│  │       │
   │  ↓     │   │       │       │       │  │  │       │       │
   │打 AWS  │  直接回答  直接回答  直接回答  直接回答 │ 打 AWS  直接回答  打 AWS
   │DescribeInstances                     │  │ （過期了）      （又過 60 秒）
   │  ↓     │                             │  │  ↓
   │"running"                             │  │ "stopped"
   │  ↓     │                             │  │  ↓
   │存快取＋回 True                        │  │ 存快取＋回 False
   └────────┘                             │  │
                                          │  │
  ①〜⑤ 五張照片，只打了 1 次 AWS ─────────┘  └─ TTL 過了才重新問
                                             ⑥ 之後才看得到機器被 Stop 了

  ⚠ 代價：機器剛被 Stop 的那 60 秒內，照片仍會被送去 S3、然後等到逾時才 fallback。
     這是刻意接受的——比起「每張照片都打一次 AWS」，一分鐘的窗口便宜得多。
     （真的被卡到也不會掉資料：fallback 一定會把照片入庫，只是慢。）

  ⚠ 失敗的答案也會進快取：AWS 憑證過期時，60 秒內的照片直接走本機，
     不會每一張都再去撞一次牆。
```

### 5.2 三種 `CLOUD_ROUTE` 的差別（本 phase 補上最後一個）

```text
                    available() 會做什麼            機器關著時的下場
                    ─────────────────────────       ────────────────────────────────
  CLOUD_ROUTE=off   永遠回 False（連問都不問）      完全不碰 AWS ＝ 增量五的行為
   （預設；pytest、  ↑ Phase 77                     使用者 100% 無感
    新 clone、CI）

  CLOUD_ROUTE=      永遠回 True（假設開著）         照樣 PutObject ＋ SendMessage，
    assume          ↑ Phase 86                      然後空等到 CLOUD_RESULT_TIMEOUT_
   （只給階段丁與                                   SECONDS（預設 300 秒）才 fallback
    除錯用）                                        → 每張慢 5 分鐘、S3 留垃圾

  CLOUD_ROUTE=ec2   問 DescribeInstances，          直接回 False → 立刻走本機
   （戊之後的日常）  60 秒內只問一次                 → **這就是 Demo 2b**
                    ↑ 本 phase                      → S3 一個新物件都不會出現

  三種模式**都不會**讓使用者看到失敗：202 照回、進度面板照跑、照片照樣入庫。
  差別只在 worker 的 log（route=cloud／fallback=local reason=remote_unavailable）
  與「這一張到底花了多久」。
```

---

## 6. 驗收清單

- [ ] **`Ec2Probe` 的簽章與總覽 §2.4.1 逐字相同**：
      ```bash
      python -c "
      import inspect
      from app.services.cloud_ingest import Ec2Probe
      print(inspect.signature(Ec2Probe.__init__))
      "
      ```
      預期印出 `(self, mailbox: 'CloudMailbox', instance_id: 'str', *, ttl_seconds: 'int') -> 'None'`
      （型別外面那層引號是正常的：`cloud_ingest.py` 檔頭有 `from __future__ import annotations`，
      註記在執行期是**字串**，`inspect` 就照字串印。名字與順序對就好）
- [ ] **只有一個 `_now()`**（不可以有兩份時基），而且 `time.monotonic()` 只出現在它裡面：
      ```bash
      grep -c "^def _now" app/services/cloud_ingest.py
      grep -n "time.monotonic()" app/services/cloud_ingest.py
      ```
      預期第一句印 `1`；第二句恰好**兩行**、而且都在 `_now()` 裡（一行是它的 docstring、
      一行是 `return time.monotonic()`）。多出第三行＝有人在 `Ec2Probe` 裡直接呼叫了單調時鐘
      ——`假裝過了()` 撥不動它，改成呼叫 `_now()`
- [ ] **時基是單調時鐘，不是 `datetime`**：
      ```bash
      grep -n "datetime.now\|datetime.utcnow\|time.time()" app/services/cloud_ingest.py \
        || echo "OK：沒有用會倒退的時鐘"
      ```
      預期印出 `OK：沒有用會倒退的時鐘`
- [ ] **探測不會往外丟例外**：
      ```bash
      grep -n -A5 "self._mailbox.instance_state" app/services/cloud_ingest.py
      ```
      預期那五行裡看得到 `except Exception:`、`logger.warning(...)` 與 `return self._記住(False, 現在)`
- [ ] **Phase 77 的鬧鐘已拆、測試裡沒有人再期待暫時分支**：
      ```bash
      grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py \
        tests/unit/test_dependencies_cloud_unit.py || echo "OK：測試裡零 NotImplementedError"
      ```
      預期印出 `OK：測試裡零 NotImplementedError`
- [ ] **`cloud_ingest.py` 沒有 import boto3**（總覽 §7 鐵律 5）：
      ```bash
      grep -n "boto3" app/services/cloud_ingest.py || echo "OK：boto3 只在 aws_mailbox.py"
      ```
      預期印出 `OK：boto3 只在 aws_mailbox.py`
- [ ] **不會自動開機**（design6 §1.2 第 9 列）：
      ```bash
      grep -nE "start_instances|start-instances|stop_instances" app/ -r \
        || echo "OK：程式不會自己開關 EC2"
      ```
      預期印出 `OK：程式不會自己開關 EC2`
- [ ] **`get_cloud_route()` 三個分支都真的實作了**：
      ```bash
      grep -n "NotImplementedError" app/dependencies.py || echo "OK：沒有暫時分支了"
      ```
      預期印出 `OK：沒有暫時分支了`
- [ ] **`ec2` 那條路整個行程只建一次**：
      ```bash
      grep -n -B1 "def _ec2_cloud_route" app/dependencies.py
      ```
      預期上一行是 `@lru_cache(maxsize=1)`
- [ ] **建物件走模組屬性、boto3 只在函式裡載入**（Phase 86 的側錄測試與本 phase 的第 7 顆都靠這個）：
      ```bash
      grep -n "^from app.services.cloud_ingest import\|^from app.services.aws_mailbox import" app/dependencies.py \
        || echo "OK：dependencies.py 檔頭沒有直接 import 這兩個模組裡的名字"
      grep -c "cloud_ingest.Ec2Probe(\|cloud_ingest.CloudRoute(\|cloud_ingest.AlwaysRunning(" app/dependencies.py
      ```
      預期第一句印出 `OK：…`；第二句印出 `4`（`_ec2_cloud_route` 裡 `CloudRoute`＋`Ec2Probe` 各一、
      `assume` 那支 `CloudRoute`＋`AlwaysRunning` 各一）
- [ ] `pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -v` 全綠，
      而且看得到本 phase 那 7 顆的名字
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ 開工基線 ＋ **7**（＝658）
- [ ] **三死埠零依賴實證**（顆數與上一條相同；本 phase 的程式碰得到 AWS，這條特別重要）：
      ```bash
      AWS_ENDPOINT_URL=http://127.0.0.1:9 \
      CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
      OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
      ```
- [ ] **端點仍是 22**（本 phase 不碰任何 router）：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `22`
- [ ] **專案的 `data/` 沒有被弄髒**：
      ```bash
      find data/staging -type f -mmin +60 2>/dev/null | head; echo "---"
      ```
      預期 `---` 之前沒有輸出
- [ ] **`.env` 仍是 `CLOUD_ROUTE=off`**（本 phase 沒有要跑真 AWS）：
      ```bash
      grep -n "^CLOUD_ROUTE=" .env || echo "（沒有這一行也算 off：config 的預設值就是 off）"
      ```
      預期 `CLOUD_ROUTE=off`（Phase 86 收尾時明寫進去的），或那句括號提示；**不可以**是 `assume`／`ec2`
- [ ] **規格區一字未動**：`git status --short docs/spec/` → 零輸出
- [ ] **沒有建立任何 AWS 資源**（★G2 之前不准開機器；這條是**唯讀**查詢，用 Phase 82 `aws configure`
      設好的 admin 身分，不必 source `.env`）：
      ```bash
      aws ec2 describe-instances --region ap-northeast-1 \
        --filters Name=tag:Name,Values=personaldocai-worker \
        --query 'Reservations[].Instances[].InstanceId' --output text
      ```
      預期：**沒有輸出**（一台都還沒建）。這是本 phase 唯一會打到 AWS 的指令，而且只是「看」
- [ ] `ruff format --check app tests scripts && ruff check app tests scripts` 兩句都乾淨

---

## 7. 常見陷阱

1. **在 `cloud_ingest.py` 裡再加一個 `_now()`（或在 `Ec2Probe` 裡直接寫 `time.monotonic()`）。**
   Phase 79 為了 `CloudRoute.wait_result()` 的 deadline **已經有一個了**。
   兩份時基會漂移，而且測試 `monkeypatch.setattr(cloud_ingest, "_now", …)`
   只會蓋掉其中一個——另一邊照樣走真的時鐘。
   **症狀**：`test_TTL過了會再打一次` 紅（撥了 61 秒探測卻沒重問），
   或反過來 `wait_result` 的逾時測試莫名其妙變慢或變紅。
   **正解**：步驟 1 的 grep 確認它在，然後 `Ec2Probe` 裡一律呼叫 `_now()`；
   grep 不到就是 Phase 79 沒做完，回去補，不要在這裡加。

2. **用 `datetime.now()` 算 TTL。**
   使用者調系統時間、或 NTP 往回校時，`現在 − 存的時間` 會變成負數 →
   `< 60` 永遠成立 → **快取一整年都不過期**，機器早就 Stop 了本機還以為它開著。
   **正解**：一律 `time.monotonic()`（單調時鐘，只會往前走）。

3. **探測失敗時把例外往外丟。**
   `gated_ingest` 呼叫 `cloud.available()` 的那一行沒有包 try——例外會一路往上，
   Celery 任務失敗，**那張照片就入不了庫**。這直接違反 D10
   「不上傳失敗、不要求使用者重傳」。
   **症狀**：AWS 憑證過期的那一天，所有非敏感照片全部卡在 `analyzing`。
   **正解**：`except Exception:` → log → `return False`。

4. **每次呼叫 `get_cloud_route()` 都 new 一個 `Ec2Probe`。**
   TTL 快取是**物件身上的狀態**。每次新建＝快取永遠是空的＝每張照片都打一次
   `DescribeInstances`——D10 第 1 條要的東西就落空了，而且測試**完全看不出來**
   （單元測試是直接 new 一個探測物件在測，不經過 `get_cloud_route()`）。
   **正解**：`_ec2_cloud_route()` 加 `@lru_cache(maxsize=1)`；驗收清單有一條在查它。

5. **忘了在測試裡清 `lru_cache`。**
   `_ec2_cloud_route()` 只建一次，所以第一顆跑到它的測試會把「那次的假信箱」
   留給後面所有測試。
   **症狀**：**單獨跑綠、整批跑紅**（或反過來），而且順序一換結果就變——最難查的那一種。
   **正解**：`test_dependencies_cloud_unit.py` 的 autouse fixture 前後各
   `dependencies._ec2_cloud_route.cache_clear()` 一次。

6. **以為 `pending` 也算開著。**
   `pending` 是「開機中」——機器還沒準備好收訊息，工人的容器也還沒起來。
   這時候送過去，訊息會躺在佇列裡直到可見度逾時，而本機早就逾時 fallback 了。
   **正解**：`狀態 == "running"`，一個字都不要放寬。

7. **測試裡用 `time.sleep(61)` 等 TTL 過期。**
   那會讓整批測試多花一分鐘，而且以後每個人每次跑都要付這一分鐘。
   **正解**：`假裝過了(monkeypatch, 61)`——把 `_now` 換成「現在＋61 秒」的函式
   （寫法比照 `tests/unit/test_camera_session_unit.py`）。

8. **把 `.env` 的 `CLOUD_ROUTE` 順手改成 `ec2` 來「試試看」。**
   本 phase 結束時**還沒有任何 EC2**，`EC2_WORKER_INSTANCE_ID` 也是空的 →
   探測會一路走「沒有 instance id」那條 → 每張照片的 worker log 都會多一行警告。
   功能沒壞（照片照樣入庫），但那不是本 phase 要驗的東西。
   **正解**：`.env` 保持 `CLOUD_ROUTE=off`，等 Phase 92 真機起來才改。

9. **兩份 pytest 同時跑。**
   `reset_tables` 每顆測試都會 `TRUNCATE` 同一個測試庫，症狀是大量看似隨機的 404
   與 `TypeError: 'NoneType' object is not subscriptable`，每次紅的顆數還不一樣。

10. **剛 Stop 完機器就上傳，worker log 卻是 `route=cloud`，然後等了五分鐘才 fallback。**（Phase 92 之後才會遇到）
    這不是探測壞了，是 TTL：上一次探測（≤60 秒前）答的是 `running`，快取還新鮮，
    本機就照舊送出，直到 `CLOUD_RESULT_TIMEOUT_SECONDS` 才 `reason=result_timeout`。
    **正解**：Stop 之後等 60 秒再傳；急的話 `docker compose restart worker`（快取住在行程裡，
    重啟就空了）。這一分鐘的窗口是 D10「快取可短 TTL」刻意接受的代價，**不要**為了它把 TTL 拿掉。

11. **改了 `.env` 的 `EC2_WORKER_INSTANCE_ID`（或 `EC2_PROBE_TTL_SECONDS`），探測卻還在問舊的那台。**
    `_ec2_cloud_route()` 是 `lru_cache`：第一次呼叫就把當時的 instance id 與 TTL 綁進
    `Ec2Probe` 物件裡，之後每個任務拿到的都是同一顆。而且 `config.py` 本來就只在行程啟動時讀一次 `.env`。
    **症狀**：Phase 92 換了實例（或 Terminate 重建），worker log 一直是 `state=unknown`。
    **正解**：`docker compose -f compose.yaml -f compose.dev.yaml restart worker`
    （與 CLAUDE.md「改 .env → restart app worker」同一條規則；`app` 容器用不到探測，可以不重啟）。

12. **在第 7 顆測試裡寫 `dependencies.get_cloud_route()`，永遠拿到 `CloudRouteOff`。**
    第五道安全網每顆測試都把 `dependencies.get_cloud_route` 這個**模組屬性**換成替身。
    **正解**：用檔頭早綁定的 `from app.dependencies import get_cloud_route as 原本的get_cloud_route`
    （Phase 86 那 2 顆就是這個名字；Phase 77 那顆在另一個檔、沒取別名），它在收集階段就綁好原版函式，
    安全網換不到它。`_ec2_cloud_route` 沒被換，走模組屬性拿沒問題。
    ⚠ 反過來，**產品碼**（`get_cloud_route()`／`_ec2_cloud_route()`）建物件一定要走模組屬性
    `cloud_ingest.CloudRoute(...)`，不要在檔頭 `from app.services.cloud_ingest import CloudRoute`——
    Phase 86 的側錄測試 `monkeypatch.setattr(cloud_ingest, "CloudRoute", …)` 換不到早綁定的名字。

---

## 8. 完成後的專案狀態

本機端終於能自己回答「那台工人機器現在開著嗎」：`Ec2Probe` 用一次
`DescribeInstances` 得到答案、快取 60 秒、任何例外都當成「不可用」。
`dependencies.get_cloud_route()` 的三種模式（`off`／`assume`／`ec2`）**全部實作完畢**
——Phase 77 留下的最後一個 `NotImplementedError` 到此除役，
本增量從此**沒有任何暫時分支**（產品負責人的第 ② 條硬要求：不留過渡產物）。

**對外行為零改變**：`.env` 仍是 `CLOUD_ROUTE=off`，所以日常操作與增量五逐字相同；
`POST /photos` 仍是 202、端點仍 22、`compose.yaml` 一個字都沒動。
**也沒有建立任何 AWS 資源**——本 phase 唯一打到 AWS 的是驗收清單裡那一條唯讀的
`describe-instances`，而它的預期輸出就是「空的」。

已經被釘死的行為：`running` 才算可用（其餘五種狀態加上 Phase 83 的 `"unknown"` 全是 `False`）、
TTL 內只打一次 `DescribeInstances`、TTL 過了會重問、例外一律 `False` 並留 log、
`instance_id` 是空的時候連問都不問、`ec2` 模式建出來的路真的帶著 `Ec2Probe` 而且整個行程只建一次、
`CLOUD_ROUTE` 打錯字仍然當場 `ValueError`（Phase 77 那顆保留的斷言）。

**與總覽的差異：零。** 新增測試 7 顆（`test_cloud_ingest_unit.py` 6 ＋
`test_dependencies_cloud_unit.py` 1），名稱與總覽 §2.7 逐字相同；另外**刪掉** Phase 77
那顆測試裡的鬧鐘段（顆數不變、零刪測試）。

顆數：開工基線 651 ＋ **7** ＝ **658**（與總覽 §9 一致）。端點仍 **22**。

---

> ## 🚦 下一個 phase 是 90，做完之後就是 ★G2
>
> **Phase 90** 把 `Dockerfile` 改成多階段（`base` → `cloud-worker` → **`app` 放最後**），
> build 出一個 `linux/arm64` 的工人映像，並用 `--env-file .env` 在這台 Mac 上
> **以容器**重做一次 Phase 88 的端到端。`compose.yaml` 一個字都不會改
> （不帶 `--target` 的 `docker build .` 仍然蓋出 app 映像）。
>
> **然後就要停下來過 ★ 閘門 G2**（總覽 §4）：
>
> | 項目 | 內容 |
> |---|---|
> | 是什麼 | 「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的一句話 |
> | 誰確認 | **產品負責人（人）** |
> | 憑什麼 | design6 §0 丁那列 ＋ arm64 映像在 Mac 上跑得起來；逐條指令見總覽 §5.5 最後一條 |
> | 沒過會怎樣 | **Phase 91〜95 全部停擺。** EC2 一開就開始扣**點數**，而點數用完會關帳（Free plan 不扣卡，資源直接消失）。工人本身有 bug 的話，你會在一台看不到 shell、只能靠 SSM 的機器上除錯 |
>
> **實作者不可以自己勾掉閘門。** 指令只是證據，「看過證據、同意往下走」
> 必須由產品負責人明說。

---

## 附：本文件引用的官方文件

- [EC2 實例的生命週期與六種狀態](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [`DescribeInstances` API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstances.html)
- [boto3 EC2 client `describe_instances`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html)
- [EC2 API 的速率限制（為什麼要快取）](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/throttling.html)
- [Python `time.monotonic()`（單調時鐘）](https://docs.python.org/3/library/time.html#time.monotonic)
- [Python `functools.lru_cache`](https://docs.python.org/3/library/functools.html#functools.lru_cache)
- [pytest `monkeypatch`](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- 專案內文件：`docs/design/design6.md`（D10、D15、§2.1、§8 第 2／3 列、§12 Demo 2b、§1.2 第 9 列）、
  `docs/plan/unfinish/phase-00-增量六總覽.md`（§2.4.1 `Ec2Probe` 簽章、§2.4.2 設定表、
  §2.7 本 phase 的測試清單、§4 ★G2、§5.3 Demo 2b）、
  `app/services/camera_session_service.py`（`_now()` seam 的既有寫法）
