# Phase 89：EC2 探測 running（`Ec2Probe` ＋ 60 秒 TTL 快取）

> 📌 **2026-09-02 校準紀錄**（ledger：`.superpowers/sdd/phase0902-2/progress.md` 的裁決 R0〜R10；
> 本檔已依 2026-09-02 晚間工作樹 HEAD `bb3921a` 逐處校準過，照著做就會對）：
>
> | 裁決 | 落在本檔哪裡 |
> |---|---|
> | **R0** 不 commit、用工作樹快照相減審 | §4 最後一步從「commit」改成「**不 commit——記快照**」（`.superpowers/sdd/phase0902-2/snapshot-tree`）；§6 最後兩條改成核對 `git status --short` ＋ 記快照 |
> | **R1** 識別字一律英文 | §2 前置檢查、§4.2a／2b 的測試碼、§4.4 的 `Ec2Probe`、§4.5 的 `_ec2_cloud_route()`／`get_cloud_route()` 全面英文化：`會爆炸的信箱`→`ExplodingMailbox`、`做一個探測`→`make_probe`、`探測`→`probe`、`信箱`→`mailbox`、`狀態`→`state`、`現在`→`now`、`_記住`→`_remember`、`可用`→`available`、`路`→`route`、`建過的`→`captured`、`假的AwsMailbox`→`fake_aws_mailbox`、`清掉ec2路的快取`→`clear_ec2_route_cache`、`模式`→`mode`。**`test_…` 的中文名維持不變**（總覽 §2.7 逐字沿用）；log／錯誤訊息／註解／docstring 也維持中文 |
> | **R2** ★G2 條件式 | §4 最後與檔尾 🚦 已註明：dev-prompt `phase0902-2.md` 明示執行到 Phase 91，controller 親跑 88／90 兩次端到端通過才進 91。**本 phase 仍然一台 EC2 都不開**，這一點沒有變 |
> | **R3** AWS／docker／`.env`／restart／煙霧一律 controller 親做 | §2 的 `docker compose ps` 與 §6 那條唯讀的 `aws ec2 describe-instances` 都標了「⚠ 本步驟由 controller 親自執行」。實作 subagent **零 `aws` 指令、零 `docker` 指令、不改 `.env`** |
> | **R4** 顆數以 2026-09-02 實查 **644** 起算 | 87 收工 656、88 收工 **661 ＝ 本 phase 開工基線**、本 phase +7 → 收工 **668**。§2／§4／§6／§8 全部已改（總覽 §9 寫的是雙寫法「658（實 668）」） |
> | **R7** `CLAUDE.md` 那句過期話由**本 phase** 改 | 新增 **§4 步驟 7**：把指令區「assume／ec2 要到 Phase 86／89 才接、現在 `get_cloud_route()` 會 `NotImplementedError`」改成「off／assume／ec2 三種都已接上（86／89）；日常 off、戊之後才 ec2」。§3「做」也多了第 5 項 |
> | **R5／R6** | 本檔由校準者 C 單獨校準（只改這一個檔）；本 phase 零前端、零鏡頭，**不需要產品負責人的手機** |
>
> **與 2026-09-01 版最重要的三處事實修正**（照舊版做會直接紅）：
> ① 時間 helper 叫 **`advance_clock_frozen(monkeypatch, seconds)`**，不叫 `假裝過了`
>   （同檔另有 `advance_clock_each_call()`，**不可以**拿它測 TTL，理由見 §4.2a）；
> ② `test_dependencies_cloud_unit.py` 現在是 **3 顆**（不是 2 顆），早綁定的名字叫
>   **`real_get_cloud_route`**，而且 `aws_mailbox` 模組**已經**以
>   `from app.services import aws_mailbox as aws_mailbox_module` import 進去了；
> ③ `dependencies.get_cloud_route()` 現行碼的區域變數叫 **`mode`／`mailbox`**（不是中文），
>   §4.5 貼的就是實檔原文。

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
| **總覽 §2.7 Phase 89** | 7 顆測試的名稱、動到的四個檔 | §4 步驟 2 逐字沿用（測試名**一個字都不要改**，總覽釘死；本 phase 另多改一個 `CLAUDE.md`＝裁決 R7，那是文件不是程式，不影響顆數） |

---

## 2. 前置條件

**★ 閘門 G1 已由產品負責人通過**（Phase 82〜86 完成：S3 bucket 與兩條 SQS 佇列都已建好）。
**★ 閘門 G2 還沒到**（它在 Phase 90 之後）——所以本 phase **一台 EC2 都不准開**。
這不影響進度：`Ec2Probe` 的七顆測試全部用假信箱／stub，**沒有 EC2 也測得完**，
真機驗證是 Phase 92 的事。

> 📌 **裁決 R2（2026-09-02）：★G2 走「條件式」。** dev-prompt `phase0902-2.md` 已明示執行到
> Phase 91，憑據是「88 的 Mac 端到端 ＋ 90 的容器端到端由 controller 親跑並通過」。
> **這一條對本 phase 沒有任何鬆綁**：89 仍然是零 AWS 資源、零 EC2、零 `aws` 指令。

**要先做完的 phase：**

| Phase | 本 phase 會用到它的什麼 |
|---|---|
| 77 | `cloud_ingest.py` 這個檔、`CloudMailbox` Protocol（含 `instance_state`）、`RemoteProbe` Protocol、`config.EC2_WORKER_INSTANCE_ID`／`EC2_PROBE_TTL_SECONDS`、`tests/fakes.py` 的 `FakeMailbox`（含 `instance_state_script`／`instance_state_calls`／`calls` 流水帳）；`tests/unit/test_cloud_ingest_unit.py` 裡那顆 `test_get_cloud_route預設off時回CloudRouteOff`（Phase 77 在裡面放了一個「ec2 還是 NotImplementedError」的**鬧鐘**，本 phase 要拆掉它，見步驟 2c） |
| 79 | `CloudRoute` 本體（`available()` 會呼叫 `probe.is_running()`，而且吞例外）；**模組層的 `_now()`／`_sleep()` 兩個時間接縫**（`wait_result` 的 deadline 用）——本 phase 的 TTL 直接呼叫同一個 `_now()`，**不加第二個** |
| 80 | `wait_result` 完整版；它的逾時測試已經 monkeypatch 過 `cloud_ingest._now`，而且**已經在同一個檔案裡定義好兩支時間 helper**——步驟 2a 直接用 `advance_clock_frozen(monkeypatch, 秒數)`（凍結語意），**不要**用 `advance_clock_each_call()`（它每問一次時鐘就往前走，拿去測 TTL 會讓「過了幾秒」變成負數、快取永遠不過期） |
| 83 | `AwsMailbox.instance_state()`（真的打 `DescribeInstances` 的那一支；查無回 `"unknown"`） |
| 86 | `dependencies.get_cloud_route()` 的 `assume` 分支與 `tests/unit/test_dependencies_cloud_unit.py` 這個檔（**實查是 3 顆**——Phase 86 的 2 顆 ＋ 2026-09-02 review fix wave 補的 `test_assume模式把config的四個值對應到AwsMailbox`。三顆用的都是**早綁定**的 `from app.dependencies import get_cloud_route as real_get_cloud_route`，本 phase 的第 7 顆用**同一個名字**；它的 `get_cloud_route()` 一律以**模組屬性** `cloud_ingest.CloudRoute(...)`／`cloud_ingest.AlwaysRunning()` 建物件——第 2 顆靠 `monkeypatch.setattr(cloud_ingest, "CloudRoute", …)`、第 3 顆靠 `monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", …)` 側錄建構參數，直接 import 名字就換不到——本 phase 的 `ec2` 分支與 `_ec2_cloud_route()` 比照。⚠ 那個檔已經有 `from app.services import aws_mailbox as aws_mailbox_module` 這一行了，**別再 import 第二次、也別改名**） |
| 88 | 與本 phase 無直接相依，但它是總覽排定的前一個 phase（顆數基線來自它：88 收工 **661**） |

**開工前實查基線**（在專案根目錄執行）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest --collect-only -q | tail -1    # 預期：661 tests collected
pytest -q                             # 預期尾巴：661 passed，0 skipped
git branch --show-current             # 預期：main
```

> ⚠ **`docker compose ps --no-trunc`（確認 `db` 是 `Up (healthy)`）由 controller 親自執行**（裁決 R3）。
> 實作 subagent **不下任何 `docker` 指令**；跑 pytest 時如果冒出一整片資料庫連線錯誤，
> 不要自己 `docker compose up`——停下來回報 BLOCKED。

> **顆數（2026-09-02 實查；裁決 R4）：** 本輪的共同基線是 `pytest -q` 實查 **644 passed／0 skipped**。
> 依序做下來：Phase 87 +12 → 656、Phase 88 +5 → **661 ＝ 本 phase 的開工基線**、
> 本 phase +7 → 收工 **668**。
> 總覽 §9 那一列寫的是雙寫法「**658（實 668）**」——658 是舊的絕對值、668 才是這一輪要對上的數字。
> 交錯做或先做別的 phase 的話絕對數字會不一樣——**永遠要對的是「本 phase 新增 7 顆」**。

再確認三個前置零件真的在（沒有就先回去做對應的 phase）：

```bash
python -c "
from app.core import config
from app.services import cloud_ingest
from tests.fakes import FakeMailbox
mailbox = FakeMailbox()
print('TTL 預設：', config.EC2_PROBE_TTL_SECONDS)
print('instance_id 預設是空的：', config.EC2_WORKER_INSTANCE_ID == '')
print('假信箱有 instance_state：', hasattr(mailbox, 'instance_state'),
      hasattr(mailbox, 'instance_state_script'), hasattr(mailbox, 'instance_state_calls'))
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
4. `tests/unit/test_dependencies_cloud_unit.py` 追加 1 顆（＋一個清快取的 autouse fixture
   `clear_ec2_route_cache`）。
5. **`CLAUDE.md` 順手改一句過期話**（裁決 R7；見步驟 7）：指令區「── AWS（增量六 Phase 82 起）」
   段落結尾寫著「assume／ec2 要到 Phase 86／89 才接、現在 `get_cloud_route()` 會 `NotImplementedError`」
   ——`assume` 在 Phase 86 就接上了，`ec2` 就是本 phase 接的，**做完這一句就整句錯了**。
   本 phase 是把 `ec2` 接上的那一個，所以順手改正它（**只改那三行註解，不動任何指令**）。

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
> 步驟 6 轉綠 → 步驟 7 順手改正 `CLAUDE.md` 那句過期話（裁決 R7）→
> 步驟 8 全量回歸與 ruff → 步驟 9 **不 commit——記快照**。

### - [x] 步驟 1：確認 `cloud_ingest.py` 的 `_now()` 在（Phase 79 建的）

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

### - [x] 步驟 2：先寫會紅的 7 顆測試

#### 2a. `tests/unit/test_cloud_ingest_unit.py` 追加 6 顆

打開 `tests/unit/test_cloud_ingest_unit.py`（Phase 77 建、79／80 加長過）。

**時間 helper 沿用 Phase 80 定義在同一檔的 `advance_clock_frozen(monkeypatch, seconds: float)`**
（**凍結**語意：把 `_now` 換成「現在＋seconds」的函式，撥完就停在那裡不動；
同檔已存在，下面那段**不再定義一次**）。先確認它在：

```bash
grep -n "^def advance_clock_frozen\|^def advance_clock_each_call" tests/unit/test_cloud_ingest_unit.py
# 預期恰 2 行（Phase 80 一次建了兩支時間 helper）。
# 0 行＝Phase 80 還沒做完（80 → 88 → 89 是必經順序），先回去做完再來
```

> ⚠️ **兩支只能用 `advance_clock_frozen`，不可以用 `advance_clock_each_call`。**
> 後者是「每問一次時鐘就再過 step_seconds 秒」的**會走的**時鐘，而且**從 0 起算**
> （不是接著真時鐘走）。`Ec2Probe` 的快取記的是「上次問的時候真時鐘是幾秒」，
> 換成從 0 起算的假時鐘之後，「現在 − 上次」會變成**負數** → `< ttl_seconds` 永遠成立 →
> 快取永遠不過期，`test_TTL過了會再打一次` 就紅了。
> （這兩句話 Phase 80 已經寫在 `advance_clock_each_call` 的 docstring 裡，
> 檔案裡也有一段註解專門講「`advance_clock_frozen` 從 Phase 89 起才有人用」——就是給本 phase 的。）

然後在檔案**最後面**加上這一整段：

```python
# ---------------- Ec2Probe：問「那台機器開著嗎」（Phase 89）----------------


class ExplodingMailbox:
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


def make_probe(states: list[str], *, instance_id: str = "i-test", ttl_seconds: int = 60):
    """回 (探測物件, 假信箱)。假信箱的 instance_state 會依序回傳 states。"""
    mailbox = FakeMailbox()
    mailbox.instance_state_script = list(states)
    return cloud_ingest.Ec2Probe(mailbox, instance_id, ttl_seconds=ttl_seconds), mailbox


def test_實例狀態running時探測為True():
    """只有 running 才算可用——這是雲端管線唯一的入場券。"""
    probe, mailbox = make_probe(["running"])

    assert probe.is_running() is True
    assert mailbox.instance_state_calls == 1


def test_實例狀態stopped與stopping與pending都是False():
    """design6 §8 第 2 列：EC2 Stop → 本機 run_ingest_job，202 與進度面板不變。

    這裡把六種狀態裡「不是 running」的五種都走一遍：pending 是**開機中**
    （機器還沒準備好收訊息）、stopping 是**關機中**（拿了訊息也做不完）。
    最後多一個 "unknown"：那是 Phase 83 的 AwsMailbox.instance_state() 在
    「查無這台機器」時回的字串（instance id 打錯／機器被 Terminate 超過一小時）。
    每一種都用一顆全新的探測物件，免得被 TTL 快取蓋住。
    """
    for state in ("pending", "stopping", "stopped", "shutting-down", "terminated", "unknown"):
        probe, mailbox = make_probe([state])

        assert probe.is_running() is False, f"{state} 不是 running，不可以送去雲端"
        assert mailbox.instance_state_calls == 1


def test_探測丟例外時回False並留log(caplog):
    """design6 §8 第 3 列：沒有 AWS 憑證 → fallback 本機。

    ⚠ 這裡**絕對不可以**把例外往外丟：往外丟的話 gated_ingest 那一層會炸，
    一張照片會因為「查不到機器狀態」而入不了庫——完全違反 D10
    「不上傳失敗、不要求使用者重傳」。
    """
    caplog.set_level(logging.WARNING)
    mailbox = ExplodingMailbox()
    probe = cloud_ingest.Ec2Probe(mailbox, "i-test", ttl_seconds=60)

    assert probe.is_running() is False
    assert mailbox.instance_state_calls == 1
    assert any("EC2" in message for message in caplog.messages), (
        f"炸掉要留 log，不可以安靜地當作不可用：{caplog.messages}"
    )


def test_TTL內不會再打一次DescribeInstances():
    """D10 第 1 條：快取可短 TTL，避免每張圖都打 AWS。

    劇本第二格是 stopped——如果快取沒生效，第二次就會拿到 False，測試立刻紅。
    """
    probe, mailbox = make_probe(["running", "stopped"], ttl_seconds=60)

    assert probe.is_running() is True
    assert probe.is_running() is True, "TTL 內應該直接給上一次的答案"
    assert mailbox.instance_state_calls == 1, "TTL 內不可以再打一次 DescribeInstances"


def test_TTL過了會再打一次(monkeypatch):
    """快取不是永久的：機器真的被 Stop 了，最多 60 秒之後就要看得到。"""
    probe, mailbox = make_probe(["running", "stopped"], ttl_seconds=60)

    assert probe.is_running() is True
    advance_clock_frozen(monkeypatch, 61)

    assert probe.is_running() is False, "TTL 過了要重新問一次"
    assert mailbox.instance_state_calls == 2


def test_instance_id是空的時候回False而且零呼叫():
    """CLOUD_ROUTE=ec2 卻沒設 EC2_WORKER_INSTANCE_ID ＝ 設定錯誤。

    這時候拿空字串去打 DescribeInstances 只會換來一個看不懂的 AWS 錯誤，
    所以**連問都不要問**：直接當作不可用、留一行 log，照片走本機照樣入庫。
    """
    probe, mailbox = make_probe(["running"], instance_id="")

    assert probe.is_running() is False
    assert mailbox.instance_state_calls == 0, "沒有 instance id 就不該打 AWS"
```

檔案最上面的 import 區要有這三個名字（已經有的不要重複；位置交給 `ruff check --fix` 的排序規則）：

```python
import logging

from app.services import cloud_ingest
from tests.fakes import FakeMailbox
```

- `FakeMailbox`：Phase 77 建檔時就 import 了（`from tests.fakes import FakeMailbox, FakeProbe`），
  **2026-09-02 實查已經在**，不要重複。
- `cloud_ingest`（**整個模組**）：Phase 80 為了 monkeypatch `_now` 已經加了
  （`from app.services import cloud_ingest`，**2026-09-02 實查已經在**）。
  上面的測試要用 `cloud_ingest.Ec2Probe`，而 helper 要 monkeypatch `cloud_ingest._now`
  ——一定要對著**模組**打。
- `logging`：**只有這一個是新的**。`caplog.set_level(logging.WARNING)` 要用；
  Phase 77／79／80 的測試都沒有它，本 phase 要自己加。
  （`import pytest` 也已經在——`test_get_cloud_route預設off時回CloudRouteOff` 的
  `pytest.raises(ValueError)` 還留著，所以 2c 拆完鬧鐘之後它仍然用得到，**不要順手刪掉**。）

#### 2b. `tests/unit/test_dependencies_cloud_unit.py` 追加 1 顆

打開 `tests/unit/test_dependencies_cloud_unit.py`（Phase 86 建的；**2026-09-02 實查 3 顆**
——Phase 86 的 2 顆 ＋ review fix wave 補的 `test_assume模式把config的四個值對應到AwsMailbox`），
在檔案**最後面**加上這一段（含一個 autouse fixture）：

```python
# ---------------- ec2 模式（Phase 89）----------------


@pytest.fixture(autouse=True)
def clear_ec2_route_cache():
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
      換的是 **aws_mailbox_module 這個模組上的屬性**（檔頭那一行
      `from app.services import aws_mailbox as aws_mailbox_module` 就是為了這件事，
      Phase 86 的第 3 顆已經在用同一招）。

    ★ 呼叫的是檔頭早綁定的 real_get_cloud_route（Phase 86 那 3 顆就是用這個名字）：
      第五道安全網每顆測試都會把 dependencies.get_cloud_route 換成「永遠回 CloudRouteOff」
      的替身，寫 dependencies.get_cloud_route() 拿到的會是替身，這顆就永遠紅。

    ★ 四個假值刻意**彼此不同**（沿用 Phase 86 第 3 顆的手法）：全都一樣的話，
      「兩條佇列 URL 對調」這種完全不會報錯的設定錯，這顆測試會照樣綠。
    """
    captured: list[dict] = []
    mailbox = FakeMailbox()
    mailbox.instance_state_script = ["stopped"]

    def fake_aws_mailbox(**kwargs):
        captured.append(kwargs)
        return mailbox

    monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", fake_aws_mailbox)
    monkeypatch.setattr(config, "CLOUD_ROUTE", "ec2")
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-A")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/queue-JOBS")
    monkeypatch.setattr(
        config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/queue-RESULTS"
    )
    monkeypatch.setattr(config, "AWS_REGION", "region-Z")
    monkeypatch.setattr(config, "EC2_WORKER_INSTANCE_ID", "i-test")
    monkeypatch.setattr(config, "EC2_PROBE_TTL_SECONDS", 60)

    route = real_get_cloud_route()

    assert isinstance(route, cloud_ingest.CloudRoute)
    # 四個參數都要從 config 來（打錯區或對到別的 bucket 是最難查的設定錯）
    assert captured == [
        {
            "bucket": "bucket-A",
            "jobs_queue_url": "https://sqs.example.invalid/queue-JOBS",
            "results_queue_url": "https://sqs.example.invalid/queue-RESULTS",
            "region": "region-Z",
        }
    ]
    assert route.available() is False, "機器是 stopped，探測要說不可用"
    assert mailbox.instance_state_calls == 1, "AlwaysRunning 不會問；問了一次就是 Ec2Probe"
    assert mailbox.calls == ["instance_state i-test"], (
        "要問的是 config.EC2_WORKER_INSTANCE_ID 那一台"
    )
    # 整個行程共用同一條路（lru_cache）：再要一次要拿到同一個物件，而且信箱只建過一次
    assert real_get_cloud_route() is route
    assert len(captured) == 1
```

檔案最上面的 import 區改成下面這樣。**2026-09-02 實查：`config`／`real_get_cloud_route`／
`aws_mailbox_module`／`cloud_ingest`／`AwsMailbox` 五行都已經在了，本 phase 只多三行**
——`pytest`、`dependencies`、`FakeMailbox`（位置交給 `ruff check --fix` 排；
檔頭那一行 `from __future__ import annotations` 與檔案 docstring 都不要動）：

```python
import pytest

from app import dependencies
from app.core import config
from app.dependencies import get_cloud_route as real_get_cloud_route
from app.services import aws_mailbox as aws_mailbox_module
from app.services import cloud_ingest
from app.services.aws_mailbox import AwsMailbox
from tests.fakes import FakeMailbox
```

> 📌 四件容易搞混的事：
> - `from app import dependencies` 與 `real_get_cloud_route` **兩個都要**：前者給 autouse fixture 拿
>   `dependencies._ec2_cloud_route.cache_clear()`（這個私有函式沒有被安全網動過，走模組屬性拿沒問題）；
>   後者是**早綁定**的原版 `get_cloud_route`——安全網 monkeypatch 的是模組屬性，換不掉在收集階段
>   就綁進本檔的這個名字。**名字要跟 Phase 86 一樣叫 `real_get_cloud_route`**，同一個檔案別出現兩種寫法。
> - `from app.services import aws_mailbox as aws_mailbox_module`（模組）**已經在檔案裡了**
>   ——Phase 86 的第 3 顆 `test_assume模式把config的四個值對應到AwsMailbox` 就是靠它側錄的。
>   **不要**再加一行 `from app.services import aws_mailbox`（那會變成同一個模組兩個名字，
>   而且 `ruff check --fix` 也不會幫你合併），直接沿用 `aws_mailbox_module` 這個名字。
> - 它與 Phase 86 留下的 `from app.services.aws_mailbox import AwsMailbox`（名字）**可以並存**：
>   Phase 86 的第 2 顆用後者做 `isinstance`；本 phase 要
>   `monkeypatch.setattr(aws_mailbox_module, "AwsMailbox", …)`，非得對著**模組**打不可。
>   `_ec2_cloud_route()` 裡的 `from app.services.aws_mailbox import AwsMailbox` 是在
>   **呼叫當下**才去模組上取名字，所以換得到。
> - 本檔的測試**不可以**寫 `dependencies.get_cloud_route()`（§7 陷阱 12）。

#### 2c. 拆掉 Phase 77 留在 `test_cloud_ingest_unit.py` 的鬧鐘（顆數不變）

Phase 77 的 `test_get_cloud_route預設off時回CloudRouteOff` 裡有一段
（**2026-09-02 實查原文**，Phase 86 已經把 `assume` 那半拆掉了，現在只剩 `ec2` 這一段）：

```python
    # ec2 現在還沒接（總覽 §2.7：本增量唯二允許的暫時分支，只剩這最後一個）。
    # ⚠ 這幾行是**鬧鐘**：Phase 89 接上 ec2 時 → **拆掉**（改成驗它的探測是 Ec2Probe）。
    #   assume 那半已由 Phase 86 拆掉——它的正面斷言在 test_dependencies_cloud_unit.py。
    monkeypatch.setattr(config, "CLOUD_ROUTE", "ec2")
    with pytest.raises(NotImplementedError):
        get_cloud_route()
```

它的註解自己就寫著「Phase 89 接上 ec2 時 → **拆掉**」——那是**鬧鐘不是壞掉**。
**把這六行（三行註解 ＋ 三行程式）整段刪掉**——
「ec2 建出什麼」由 2b 那顆新測試正面驗證，這裡不再需要負面斷言。

**保留**同一顆測試的另外兩段：開頭的 `assert isinstance(get_cloud_route(), CloudRouteOff)`
與結尾「`CLOUD_ROUTE=cloudy` 要 `ValueError`」——後者是步驟 5 一定要留住的行為。

確認刪乾淨：

```bash
grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py \
  || echo "OK：測試裡再也沒有人期待 NotImplementedError"
```

預期印出 `OK：測試裡再也沒有人期待 NotImplementedError`。

### - [x] 步驟 3：跑它，親眼看到紅

```bash
pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -q
```

預期尾巴長這樣（其餘顆數依你的檔案而定）：

```text
6 failed, N passed, 4 errors
```

- **6 failed** ＝ `test_cloud_ingest_unit.py` 本 phase 那 6 顆，錯誤字樣是
  `AttributeError: module 'app.services.cloud_ingest' has no attribute 'Ec2Probe'`。
- **4 errors**（不是 failed）＝ `test_dependencies_cloud_unit.py` **整個檔案的 4 顆**
  （本 phase 的 1 顆 ＋ Phase 86 的 **3** 顆）。因為 2b 加的 autouse fixture 在**每顆測試開始前**
  就去拿 `dependencies._ec2_cloud_route`，而它還不存在，所以是 fixture 階段的
  `AttributeError: module 'app.dependencies' has no attribute '_ec2_cloud_route'`。
  Phase 86 那 3 顆這時候跟著 ERROR 是**預期的**，步驟 5 做完就一起恢復。
- Phase 77 那顆 `test_get_cloud_route預設off時回CloudRouteOff` 在 2c 拆掉鬧鐘之後**仍然綠**
  （它剩下的兩段——開頭 `isinstance(get_cloud_route(), CloudRouteOff)` 與結尾
  `CLOUD_ROUTE=cloudy` 要 `ValueError`——都與 ec2 無關；`monkeypatch` 參數與 `pytest` import
  也都還用得到，**不要順手刪**）。

### - [x] 步驟 4：實作 `Ec2Probe`（`app/services/cloud_ingest.py`）

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
`time.monotonic()`（那樣 `advance_clock_frozen()` 就撥不動它，`test_TTL過了會再打一次` 會紅）。

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

        now = _now()
        if self._cached is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached

        try:
            state = self._mailbox.instance_state(self._instance_id)
        except Exception:
            # 憑證過期、權限不足、網路不通……全部當成「不可用」。
            # 失敗的答案**也要進快取**：AWS 壞掉時不該每張照片都再去撞一次牆。
            logger.warning("查不到 EC2 狀態，當作遠端不可用", exc_info=True)
            return self._remember(False, now)

        logger.info("EC2 探測：instance=%s state=%s", self._instance_id, state)
        return self._remember(state == "running", now)
        # ⚠ 2026-09-03 fix wave（ledger R20 之後的 C2）：實檔改成只印實例 ID 尾 4 碼
        #   （repo 是 PUBLIC、log 常貼進報告）；以 app/services/cloud_ingest.py 為準。

    def _remember(self, available: bool, now: float) -> bool:
        """把答案存進快取並回傳它（成功與失敗都存，理由見 is_running 的註解）。"""
        self._cached = available
        self._cached_at = now
        return available
```

> 📌 **`logger` 已經在了**：`cloud_ingest.py` 檔頭第 50 行就是
> `logger = logging.getLogger(__name__)`，不必再建一個。
> 同理 `CloudMailbox` 這個型別註記也在同一個檔案裡（Protocol，L135），直接寫名字即可。
>
> 📌 **不要新增 import。** 本 phase 在 `cloud_ingest.py` 只加這一個 class，
> 它用到的 `_now()`／`logger`／`CloudMailbox` 三個名字全部是同檔既有的
> ——`import` 區一行都不會動（驗收清單有一條在查「沒有 boto3」）。

### - [x] 步驟 5：`get_cloud_route()` 補上 `ec2` 分支（`app/dependencies.py`）

打開 `app/dependencies.py`。**2026-09-02 實查**，Phase 77 建、Phase 86 改過的
`get_cloud_route()` 就在檔案最後面，**現在逐字長這樣**：

```python
def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    """這一台現在要不要走雲端路、怎麼走。**全系統只有這一個地方決定。**

    三種模式由 config.CLOUD_ROUTE 決定（總覽 §2.4.2）：
      off    → CloudRouteOff()：available() 恆為 False，gated_ingest 直接 fallback 成
               run_ingest_job——行為與增量五**逐字相同**（pytest 與新 clone 的預設）
      assume → CloudRoute ＋ AwsMailbox ＋ AlwaysRunning：假設遠端開著、**不做探測**
               （階段丁：工人跑在這台 Mac 上時用；機器沒開時它會傻傻送出、等到逾時才
               fallback，所以不要拿來當日常設定——總覽 §10.1 追認項 l）
      ec2    → Phase 89 才接（探測換成 Ec2Probe）

    ★ 打錯字要當場炸（ValueError），不要默默當成 off：
      「我明明把 CLOUD_ROUTE 設成 cloud 了，怎麼都沒送出去」是最難查的一種壞法。
      （Phase 77 的 test_get_cloud_route預設off時回CloudRouteOff 用 CLOUD_ROUTE=cloudy 釘住它。）

    ★ boto3 相關的 import 寫在函式**裡面**（不是檔案最上面），理由與既有的
      get_task_dispatcher() 相同：pytest 收集階段不必為了跑一顆字串測試就載入 boto3，
      而且 CLOUD_ROUTE=off 時根本走不到那一行。

    ★ 三個資源名稱與逾時秒數一律 config.X **即時讀**（不要 from … import X）：
      那樣才改得動（tests 用 monkeypatch 換、.env 改完 restart worker 就生效）。

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    mode = config.CLOUD_ROUTE
    if mode == "off":
        return cloud_ingest.CloudRouteOff()
    if mode == "assume":
        # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox）
        from app.services.aws_mailbox import AwsMailbox

        mailbox = AwsMailbox(
            bucket=config.S3_BUCKET,
            jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
            results_queue_url=config.SQS_RESULTS_QUEUE_URL,
            region=config.AWS_REGION,
        )
        return cloud_ingest.CloudRoute(
            mailbox,
            cloud_ingest.AlwaysRunning(),
            timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
        )
    if mode == "ec2":
        raise NotImplementedError("CLOUD_ROUTE=ec2 要等 Phase 89 的 Ec2Probe 才能用")
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{mode!r}")
```

你要改的只有**三個地方**，其餘一個字都不要動：

| # | 改哪裡 | 改成什麼 |
|---|---|---|
| ① | docstring 裡 `ec2    → Phase 89 才接（探測換成 Ec2Probe）` 那一行 | 換成真正的說明（見下面完整版） |
| ② | `if mode == "ec2":` 底下那行 `raise NotImplementedError(...)` | 換成一行註解 ＋ `return _ec2_cloud_route()` |
| ③ | 在 `get_cloud_route()` **上面**新增一個函式 | `_ec2_cloud_route()`（見下面完整版） |

> ⚠️ **`off`／`assume` 兩支與最後那行 `raise ValueError` 一個字都不准動。**
> Phase 77 的 `test_get_cloud_route預設off時回CloudRouteOff` 釘著「`CLOUD_ROUTE=cloudy` 要炸」，
> Phase 86 的 **3 顆**釘著 `assume` 建出什麼（含四個 keyword 有沒有擺對）。
>
> ⚠️ **結尾實查已經是 `raise ValueError(...)`，維持原樣就對了。**
> phase-86 §4.3 貼的那份範本結尾寫的是「不認得的值 → `logger.warning` ＋ 回 `CloudRouteOff()`」，
> 但實作當時已經照它自己的 📌「以 Phase 77 的實際程式碼為準」做對了。看到 `raise ValueError` 不要「修正」它。
>
> ⚠️ **建物件一律走模組屬性**（`cloud_ingest.CloudRoute(...)`／`cloud_ingest.Ec2Probe(...)`／
> `cloud_ingest.AlwaysRunning()`／`cloud_ingest.CloudRouteOff()`），不要在檔頭
> `from app.services.cloud_ingest import CloudRoute`——Phase 86 的第 2 顆測試靠
> `monkeypatch.setattr(cloud_ingest, "CloudRoute", RecordingCloudRoute)` 側錄建構參數，早綁定的名字換不到。
>
> ⚠️ **`from functools import lru_cache` 已經在檔頭第 19 行**（既有的 `_ollama_vlm()` 等三支在用），
> **不要再 import 一次**。

改完之後，這兩個函式的完整內容是：

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

    mailbox = AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )
    # 同一顆信箱同時給 CloudRoute（S3／SQS）與 Ec2Probe（DescribeInstances）用
    return cloud_ingest.CloudRoute(
        mailbox,
        cloud_ingest.Ec2Probe(
            mailbox,
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
      （Phase 77 的 test_get_cloud_route預設off時回CloudRouteOff 用 CLOUD_ROUTE=cloudy 釘住它。）

    ★ boto3 相關的 import 寫在函式**裡面**（不是檔案最上面），理由與既有的
      get_task_dispatcher() 相同：pytest 收集階段不必為了跑一顆字串測試就載入 boto3，
      而且 CLOUD_ROUTE=off 時根本走不到那一行。

    ★ 三個資源名稱與逾時秒數一律 config.X **即時讀**（不要 from … import X）：
      那樣才改得動（tests 用 monkeypatch 換、.env 改完 restart worker 就生效）。

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    mode = config.CLOUD_ROUTE
    if mode == "off":
        return cloud_ingest.CloudRouteOff()
    if mode == "assume":
        # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox）
        from app.services.aws_mailbox import AwsMailbox

        mailbox = AwsMailbox(
            bucket=config.S3_BUCKET,
            jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
            results_queue_url=config.SQS_RESULTS_QUEUE_URL,
            region=config.AWS_REGION,
        )
        return cloud_ingest.CloudRoute(
            mailbox,
            cloud_ingest.AlwaysRunning(),
            timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
        )
    if mode == "ec2":
        # 整個行程共用一條（lru_cache）：Ec2Probe 的 TTL 快取住在物件身上
        return _ec2_cloud_route()
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{mode!r}")
```

> ⚠️ **`assume` 那一段刻意不加 `lru_cache`**：`AlwaysRunning` 沒有任何狀態，
> 共用它一點好處都沒有；而且 `assume` 是除錯模式，每次讀最新的 `.env` 反而方便。
> 不對稱是**刻意的**，理由已經寫在 `_ec2_cloud_route()` 的 docstring 裡。

做完之後確認暫時分支真的沒了：

```bash
grep -n "NotImplementedError" app/dependencies.py || echo "OK：get_cloud_route 已經沒有暫時分支"
```

預期印出 `OK：get_cloud_route 已經沒有暫時分支`
（Phase 77 那個「其他值先 raise」的暫時分支，到這裡正式除役）。

### - [x] 步驟 6：跑新測試，看它轉綠

```bash
pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -v
```

預期：全綠，而且本 phase 新增的那 7 顆都在裡面（其餘是 Phase 77／79／80／86 的；
Phase 86 那 **3** 顆在步驟 3 ERROR 過，現在應該一起回綠）。

### - [x] 步驟 7：順手改正 `CLAUDE.md` 的一句過期話（裁決 R7）

`CLAUDE.md` 指令區「── AWS（增量六 Phase 82 起）」那一段的**結尾三行**現在是：

```text
# 增量六雲端路總開關：.env 的 CLOUD_ROUTE（off＝預設，行為與增量五逐字相同；assume／ec2 要到 Phase 86／89 才接、
# 現在 get_cloud_route() 會 NotImplementedError）。AWS 那九個變數只寫名字不寫值（見 app/core/config.py 檔尾）；
# ★G1（Phase 81 之後、產品負責人明示）之前不要填任何 AWS 值、不要打任何 aws 指令。
```

這三行**做完步驟 5 就整段錯了**：`assume` 在 Phase 86 就接上了、`ec2` 就是本 phase 接的，
`get_cloud_route()` 裡再也沒有 `NotImplementedError`；★G1 也早就通過了（S3 bucket 與兩條
SQS 佇列都已經建好）。本 phase 是把最後一支接上的那一個，所以**由本 phase 改**（裁決 R7）。

把上面那三行**整段換成**：

```text
# 增量六雲端路總開關：.env 的 CLOUD_ROUTE。**off／assume／ec2 三種都已經接上了**
#   off    ＝不走雲端（預設；行為與增量五逐字相同，pytest 與新 clone 都是它）
#   assume ＝假設遠端開著、不做探測（Phase 86 接的；只給「工人跑在這台 Mac 上」與除錯用。
#            機器沒開時它會傻傻送出、等到 CLOUD_RESULT_TIMEOUT_SECONDS 才 fallback，每張慢 5 分鐘）
#   ec2    ＝用 DescribeInstances 問那台機器是不是 running，答案快取 60 秒（Phase 89 接的；
#            要等 Phase 92 開好實例、.env 填了 EC2_WORKER_INSTANCE_ID 才有意義）
# **日常請維持 off**；改了要 restart worker 才生效（ec2 那條路是 lru_cache，行程只建一次）。
# AWS 那九個變數只寫名字不寫值（見 app/core/config.py 檔尾）。
# ★G1 已由產品負責人通過（Phase 82〜86 完成：S3 bucket 與兩條 SQS 佇列都在）。
```

> ⚠️ **只改這三行註解，不要動同一段落裡的任何指令**（`aws sts get-caller-identity`、
> `aws budgets describe-budgets`、`set -a; . ./.env; set +a` 那幾行）。
> 也**不要**把任何 bucket 名、佇列 URL、實例 ID、access key 寫進去——
> 這個 repo 是 public，同一段落上面那條「⛔ 機密永遠只寫變數名，不寫值」對本步驟一樣有效。

> 📌 這是本 phase **唯一**會動到 `app/`／`tests/` 以外的檔案。
> `docs/spec/`、總覽、其他 phase 計畫檔、`compose*.yaml`、`.env` 一律不碰。

> ⚠️ **Phase 88 也會動 `CLAUDE.md`**（它在 AWS 段**之後**、「── 格式與 lint」**之前**
> 插一個新的繁中小段）。兩者位置不同、**不會衝突**，但如果 88 已經做完，
> 你要改的那三行**行號會往前不變、往後的東西被推移**——所以
> **一律用「內容」定位，不要用行號**（找 `增量六雲端路總開關` 這幾個字）。
> 反過來，你也**不要順手動 88 插進去的那一段**。

### - [x] 步驟 8：全量回歸與 ruff

```bash
pytest -q
```

預期：**開工基線 ＋ 7**（＝**668**；開工基線 661，見 §2），全綠、0 skipped。

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

### - [x] 步驟 9：不 commit——記快照

> ⚠️ **總覽 §7 鐵律 12：commit 節奏由產品負責人決定。**
> 2026-09-02 的指示是**不 commit**（裁決 R0）——**不要 `git add`、不要 `git commit`、
> 不要 `git stash`、不要 `git mv`**。審查改用「工作樹快照的 tree SHA 相減」。

```bash
cd /Users/linjunting/personalDocAI
git status --short -- app tests CLAUDE.md   # 看變更恰為下面那五個檔
.superpowers/sdd/phase0902-2/snapshot-tree  # 印出一顆 40 字元的 tree SHA，記進 ledger
```

**預期：** `git status --short` 恰好列出五個檔——

```text
 M app/dependencies.py
 M app/services/cloud_ingest.py
 M tests/unit/test_cloud_ingest_unit.py
 M tests/unit/test_dependencies_cloud_unit.py
 M CLAUDE.md
```

（`.env` 不入版控所以不會出現；`data/` 被 `.gitignore` 擋掉也不會出現。
review 時用 `git diff -U10 <開工的 tree> <收工的 tree>`，
或 `.superpowers/sdd/phase0902-2/review-package-tree <A> <B> <輸出檔>`。
`git log -1 --format=%H` 必須仍然是開工時的那一顆。）

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

- [x] **`Ec2Probe` 的簽章與總覽 §2.4.1 逐字相同**：
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
- [x] **只有一個 `_now()`**（不可以有兩份時基），而且 `time.monotonic()` 只出現在它裡面：
      ```bash
      grep -c "^def _now" app/services/cloud_ingest.py
      grep -n "time.monotonic()" app/services/cloud_ingest.py
      ```
      預期第一句印 `1`；第二句恰好**兩行**、而且都在 `_now()` 裡（一行是它的 docstring、
      一行是 `return time.monotonic()`）。多出第三行＝有人在 `Ec2Probe` 裡直接呼叫了單調時鐘
      ——`advance_clock_frozen()` 撥不動它，改成呼叫 `_now()`
- [x] **時基是單調時鐘，不是 `datetime`**：
      ```bash
      grep -n "datetime.now\|datetime.utcnow\|time.time()" app/services/cloud_ingest.py \
        || echo "OK：沒有用會倒退的時鐘"
      ```
      預期印出 `OK：沒有用會倒退的時鐘`
- [x] **探測不會往外丟例外**：
      ```bash
      grep -n -A5 "self._mailbox.instance_state" app/services/cloud_ingest.py
      ```
      預期那五行裡看得到 `except Exception:`、`logger.warning(...)` 與 `return self._remember(False, now)`
- [x] **Phase 77 的鬧鐘已拆、測試裡沒有人再期待暫時分支**：
      ```bash
      grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py \
        tests/unit/test_dependencies_cloud_unit.py || echo "OK：測試裡零 NotImplementedError"
      ```
      預期印出 `OK：測試裡零 NotImplementedError`
- [x] **`cloud_ingest.py` 沒有 import boto3**（總覽 §7 鐵律 5）：
      ```bash
      grep -n "boto3" app/services/cloud_ingest.py || echo "OK：boto3 只在 aws_mailbox.py"
      ```
      預期印出 `OK：boto3 只在 aws_mailbox.py`
- [x] **不會自動開機**（design6 §1.2 第 9 列）：
      ```bash
      grep -nE "start_instances|start-instances|stop_instances" app/ -r \
        || echo "OK：程式不會自己開關 EC2"
      ```
      預期印出 `OK：程式不會自己開關 EC2`
- [x] **`get_cloud_route()` 三個分支都真的實作了**：
      ```bash
      grep -n "NotImplementedError" app/dependencies.py || echo "OK：沒有暫時分支了"
      ```
      預期印出 `OK：沒有暫時分支了`
- [x] **`ec2` 那條路整個行程只建一次**：
      ```bash
      grep -n -B1 "def _ec2_cloud_route" app/dependencies.py
      ```
      預期上一行是 `@lru_cache(maxsize=1)`
- [x] **建物件走模組屬性、boto3 只在函式裡載入**（Phase 86 的側錄測試與本 phase 的第 7 顆都靠這個）：
      ```bash
      grep -n "^from app.services.cloud_ingest import\|^from app.services.aws_mailbox import" app/dependencies.py \
        || echo "OK：dependencies.py 檔頭沒有直接 import 這兩個模組裡的名字"
      grep -c "cloud_ingest.Ec2Probe(\|cloud_ingest.CloudRoute(\|cloud_ingest.AlwaysRunning(" app/dependencies.py
      ```
      預期第一句印出 `OK：…`；第二句印出 `4`（`_ec2_cloud_route` 裡 `CloudRoute`＋`Ec2Probe` 各一、
      `assume` 那支 `CloudRoute`＋`AlwaysRunning` 各一）
- [x] `pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -v` 全綠，
      而且看得到本 phase 那 7 顆的名字（`test_dependencies_cloud_unit.py` 這個檔應該是 **4 顆**
      ＝ Phase 86 的 3 顆 ＋ 本 phase 的 1 顆）
- [x] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ 開工基線 **661** ＋ **7** ＝ **668**
      （2026-09-02 實查基線 644；87 +12、88 +5 之後就是 661。總覽 §9 寫的是雙寫法「658（實 668）」）
- [x] **三死埠零依賴實證**（顆數與上一條相同；本 phase 的程式碰得到 AWS，這條特別重要）：
      ```bash
      AWS_ENDPOINT_URL=http://127.0.0.1:9 \
      CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
      OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
      ```
- [x] **本 phase 動到的四個 .py 檔零中文識別字**（裁決 R1；`test_…` 名不算）：
      ```bash
      for f in app/services/cloud_ingest.py app/dependencies.py \
               tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py; do
        python -c "
import io, tokenize, sys
src = open(sys.argv[1], encoding='utf-8').read()
bad = sorted({t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
              if t.type == tokenize.NAME and not t.string.isascii()
              and not t.string.startswith('test_')})
print(sys.argv[1], bad)
" "$f"
      done
      ```
      預期四行都是 `… []`（log／錯誤訊息／註解／docstring 的中文不受影響，
      `test_中文` 的測試名也刻意排除——那是總覽 §2.7 逐字釘死的）
- [x] **端點仍是 22**（本 phase 不碰任何 router）：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `22`
- [x] **專案的 `data/` 沒有被弄髒**：
      ```bash
      find data/staging -type f -mmin +60 2>/dev/null | head; echo "---"
      ```
      預期 `---` 之前沒有輸出
- [x] **`.env` 仍是 `CLOUD_ROUTE=off`**（本 phase 沒有要跑真 AWS）：
      ```bash
      grep -n "^CLOUD_ROUTE=" .env || echo "（沒有這一行也算 off：config 的預設值就是 off）"
      ```
      預期 `CLOUD_ROUTE=off`（Phase 86 收尾時明寫進去的），或那句括號提示；**不可以**是 `assume`／`ec2`
- [x] **規格區一字未動**：`git status --short docs/spec/` → 零輸出
- [x] **沒有建立任何 AWS 資源**（★G2 之前不准開機器）
      ⚠ **本條由 controller 親自執行**（裁決 R3）——實作 subagent **一句 `aws` 指令都不准打**，
      本 phase 的七顆測試全部用假信箱／stub，沒有 AWS 也跑得完。
      這條是**唯讀**查詢，用 Phase 82 `aws configure` 設好的 default 身分
      （`personaldocai-admin`，**不必也不要加 `--profile`**——本機沒有那個 profile 名）：
      ```bash
      # ⚠ 不要先 `source .env` 再打 aws：.env 裡的是程式用的最小權限 key，
      #   環境變數優先序比 ~/.aws 高，會蓋掉 admin 身分。
      #   已經 source 過的話先 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`。
      aws ec2 describe-instances --region ap-northeast-1 \
        --filters Name=tag:Name,Values=personaldocai-worker \
        --query 'Reservations[].Instances[].InstanceId' --output text
      ```
      預期：**沒有輸出**（一台都還沒建）。這是本 phase 唯一會打到 AWS 的指令，而且只是「看」
- [x] `ruff format --check app tests scripts && ruff check app tests scripts` 兩句都乾淨
- [x] **`CLAUDE.md` 那句過期話已改正**（裁決 R7；步驟 7）：
      ```bash
      grep -n "NotImplementedError" CLAUDE.md || echo "OK：CLAUDE.md 不再說 get_cloud_route 會 NotImplementedError"
      grep -n "三種都已經接上" CLAUDE.md
      ```
      預期第一句印出 `OK：…`；第二句恰 1 行
- [x] **git 收尾＝不 commit、記快照**（2026-09-02 的指示；裁決 R0）
      ```bash
      cd /Users/linjunting/personalDocAI
      git status --short -- app tests CLAUDE.md   # 變更恰為那五個檔
      .superpowers/sdd/phase0902-2/snapshot-tree  # 收工的 tree SHA，記進 ledger
      ```
      預期：`git status --short` 恰五行（`app/dependencies.py`、`app/services/cloud_ingest.py`、
      兩個 `tests/unit/` 的檔、`CLAUDE.md`）；**沒有** `git add`／`git commit`／`git stash` 的痕跡
      （`git log -1 --format=%H` 仍然是開工時的那一顆）

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
   **正解**：`advance_clock_frozen(monkeypatch, 61)`——把 `_now` 換成「現在＋61 秒」的函式
   （Phase 80 已經定義在 `tests/unit/test_cloud_ingest_unit.py` 裡，寫法比照
   `tests/unit/test_camera_session_unit.py` 的 `假裝過了`）。
   ⚠ **不要拿同檔的 `advance_clock_each_call()`**：它是「每問一次就往前走」而且**從 0 起算**的
   假時鐘，`現在 − 上次問的時候` 會變成負數 → 快取永遠不過期 → 這一顆永遠紅
   （Phase 80 已經把這句話寫進那支 helper 的 docstring）。

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
    ⚠ 這是 **Phase 92 之後**日常維運的知識，**不是本 phase 的步驟**——
    本 phase 的實作者不下任何 `docker` 指令、不改 `.env`（裁決 R3）。

12. **在第 7 顆測試裡寫 `dependencies.get_cloud_route()`，永遠拿到 `CloudRouteOff`。**
    第五道安全網每顆測試都把 `dependencies.get_cloud_route` 這個**模組屬性**換成替身。
    **正解**：用檔頭早綁定的 `from app.dependencies import get_cloud_route as real_get_cloud_route`
    （Phase 86 那 3 顆就是這個名字；Phase 77 那顆在另一個檔、沒取別名），它在收集階段就綁好原版函式，
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
`describe-instances`（而且**由 controller 親自執行**，裁決 R3），它的預期輸出就是「空的」。

順手清掉的一個過期事實（裁決 R7）：`CLAUDE.md` 指令區原本寫著
「assume／ec2 要到 Phase 86／89 才接、現在 `get_cloud_route()` 會 `NotImplementedError`」
——步驟 7 已把它改成「off／assume／ec2 三種都已接上（86／89）；日常 off、戊之後才 ec2」。

已經被釘死的行為：`running` 才算可用（其餘五種狀態加上 Phase 83 的 `"unknown"` 全是 `False`）、
TTL 內只打一次 `DescribeInstances`、TTL 過了會重問、例外一律 `False` 並留 log、
`instance_id` 是空的時候連問都不問、`ec2` 模式建出來的路真的帶著 `Ec2Probe` 而且整個行程只建一次、
`CLOUD_ROUTE` 打錯字仍然當場 `ValueError`（Phase 77 那顆保留的斷言）。

**與總覽的差異：零。** 新增測試 7 顆（`test_cloud_ingest_unit.py` 6 ＋
`test_dependencies_cloud_unit.py` 1），名稱與總覽 §2.7 逐字相同；另外**刪掉** Phase 77
那顆測試裡的鬧鐘段（顆數不變、零刪測試）。

顆數：開工基線 **661** ＋ **7** ＝ **668**（2026-09-02 實查 644 起算：87 +12 → 656、
88 +5 → 661、本 phase +7 → 668；總覽 §9 那一列寫的是雙寫法「**658（實 668）**」，
658 是舊絕對值、668 才是這一輪要對上的數字）。端點仍 **22**。

**動到的檔恰五個**：`app/services/cloud_ingest.py`、`app/dependencies.py`、
`tests/unit/test_cloud_ingest_unit.py`、`tests/unit/test_dependencies_cloud_unit.py`、
`CLAUDE.md`（步驟 7 的三行註解）。**不 commit**——收工只記工作樹快照（裁決 R0）。

---

## 9. 實作紀錄（2026-09-02，實作 subagent）

**結論：照計畫做完，與計畫檔零實質差異。** 動到的檔恰五個，未 commit（裁決 R0）。

| 項目 | 實際值 |
|---|---|
| 開工基線（實查 `pytest --collect-only -q`） | **663 tests collected**（88 的 review fix round 之後；計畫檔 §2 寫的 661 是 fix round 前的預估） |
| 收工全量 `pytest -q` | **670 passed、0 skipped**（＝663 ＋ 7；本 phase 新增恰 7 顆，與總覽 §2.7 相同） |
| 三死埠（`AWS_ENDPOINT_URL`／`CELERY_BROKER_URL`／`OLLAMA_BASE_URL` 全指 `127.0.0.1:9`） | **670 passed**（顆數相同＝零外部依賴） |
| warning | 只有基線那一個 `StarletteDeprecationWarning`（環境層，非本 phase 造成） |
| `ruff format --check` ／ `ruff check` | `113 files already formatted` ／ `All checks passed!` |
| 端點 | **22**（未動任何 router） |
| 工作樹快照 tree SHA（程式碼與 `CLAUDE.md` 改完、本檔勾選之前） | `3b10a7d5926d1ff3d112cd5b739063f409a57755`；本檔勾選後的最終值見 `.superpowers/sdd/phase0902-2/task-3-report.md` |
| HEAD | 仍是 `bb3921a97846c30daa5589b0559ae604a6d82596`（無 commit／add／stash） |

**RED 證據**（步驟 3，`pytest tests/unit/test_cloud_ingest_unit.py tests/unit/test_dependencies_cloud_unit.py -q`）：
`6 failed, 20 passed, 4 errors`——6 failed 是本 phase 在 `test_cloud_ingest_unit.py` 的 6 顆
（`AttributeError: module 'app.services.cloud_ingest' has no attribute 'Ec2Probe'`）；
4 errors 是 `test_dependencies_cloud_unit.py` 整個檔（新 autouse fixture 在
`AttributeError: module 'app.dependencies' has no attribute '_ec2_cloud_route'` 階段就 ERROR），
**與計畫檔步驟 3 預測的數字逐一相同**。

**GREEN 證據**（步驟 6）：同兩檔 `30 passed`（`test_dependencies_cloud_unit.py` 恰 4 顆
＝ Phase 86 的 3 ＋ 本 phase 的 1；Phase 86 那 3 顆已從 ERROR 回綠）。

**與計畫檔的差異（僅兩處，都是文字層面、非行為）：**

1. **顆數基線 661 → 實查 663。** Phase 88 的 review fix round 之後基線變成 663，
   所以收工是 **670**（不是計畫檔寫的 668）。「本 phase 新增 7 顆」這件事完全沒變。
2. **兩條驗收 grep 的「預期輸出」在本 repo 拿不到那句 OK 字樣**（**不是缺陷**，都是既有的
   docstring 文字被子字串比對打到，兩者皆非本 phase 寫的、也非真的違規）：
   - `grep -n "NotImplementedError" tests/unit/…` 仍會命中 `test_dependencies_cloud_unit.py:51`
     ——那是 Phase 86 那顆測試 **docstring 裡的一句說明**（「① 不再是 NotImplementedError」），
     **沒有任何測試再 `pytest.raises(NotImplementedError)`**（Phase 77 的鬧鐘已依步驟 2c 整段刪除）。
   - `grep -n "boto3" app/services/cloud_ingest.py` 仍會命中檔案 docstring 與 `MailboxMessage`
     的註解（Phase 77 寫的散文，例如「它**不認識 boto3**」）。已改用 `ast` 實證
     `cloud_ingest.py` 與 `dependencies.py` 兩檔**都沒有任何 boto3 的 import 語句**。

**逐項自我檢查（全過）：** `Ec2Probe.__init__` 簽章 ＝
`(self, mailbox: 'CloudMailbox', instance_id: 'str', *, ttl_seconds: 'int') -> 'None'`；
`grep -c "^def _now"` ＝ 1、`time.monotonic()` 恰兩行且都在 `_now()` 內（零新增時基）；
無 `datetime.now`／`time.time()`；例外路徑 `except Exception:` → `logger.warning(..., exc_info=True)`
→ `return self._remember(False, now)`（不外丟）；`app/` 全樹無 `start_instances`／`stop_instances`；
`app/dependencies.py` 零 `NotImplementedError`；`@lru_cache(maxsize=1)` 就在 `_ec2_cloud_route` 上一行；
檔頭沒有 `from app.services.cloud_ingest import …`／`from app.services.aws_mailbox import …`，
`cloud_ingest.Ec2Probe(`／`CloudRoute(`／`AlwaysRunning(` 合計 **4** 次；四個 .py 檔 tokenize
掃出的非 ASCII 識別字皆為 `[]`；`data/staging` 無殘留；`.env` 仍 `CLOUD_ROUTE=off`（未改）；
`git status --short docs/spec/` 零輸出；`git status --short -- app tests CLAUDE.md` 恰五個
修改檔（另有 Phase 87／88 留下的三個未追蹤項，非本 phase 產生）。

**未做（留給 controller，裁決 R3）：** §6 驗收清單那條唯讀的
`aws ec2 describe-instances`（本 phase 一句 `aws` 指令都沒打，也沒下任何 `docker` 指令、
沒改 `.env`、沒建任何 AWS 資源）。

---

> ## 🚦 下一個 phase 是 90，做完之後就是 ★G2
>
> **Phase 90** 把 `Dockerfile` 改成多階段（`base` → `cloud-worker` → **`app` 放最後**），
> build 出一個 `linux/arm64` 的工人映像，並用 `--env-file .env` 在這台 Mac 上
> **以容器**重做一次 Phase 88 的端到端。`compose.yaml` 一個字都不會改
> （不帶 `--target` 的 `docker build .` 仍然蓋出 app 映像）。
>
> **然後就要停下來過 ★ 閘門 G2**（總覽 §4；2026-09-02 已由 controller 裁決 R2 走**條件式**
> ——dev-prompt 明示執行到 91，憑據是 88 與 90 兩次端到端由 controller 親跑並通過；
> 產品負責人仍可事後否決，91 建的全部是免費且可逆的資源，而且**不啟動任何實例**）：
>
> | 項目 | 內容 |
> |---|---|
> | 是什麼 | 「工人在 Mac 上（含容器）真的跑通了，可以開一台 EC2 了」的一句話 |
> | 誰確認 | **產品負責人（人）** |
> | 憑什麼 | design6 §0 丁那列 ＋ arm64 映像在 Mac 上跑得起來；逐條指令見總覽 §5.5 最後一條 |
> | 沒過會怎樣 | **Phase 91〜95 全部停擺。** EC2 一開就開始扣**點數**，而點數用完會關帳（Free plan 不扣卡，資源直接消失）。工人本身有 bug 的話，你會在一台看不到 shell、只能靠 SSM 的機器上除錯 |
>
> **實作者不可以自己勾掉閘門。** 指令只是證據，「看過證據、同意往下走」
> 必須由產品負責人明說（或如本輪：由 dev-prompt 明示範圍 ＋ controller 依裁決 R2 補齊憑據）。

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
