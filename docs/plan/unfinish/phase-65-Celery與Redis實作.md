# Phase 65：Celery 與 Redis 實作（純程式碼，還不碰 Compose）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。想「順便加個 Flower 監控面板／重試按鈕／換成 RabbitMQ」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 把「真正的佇列」寫出來——新增 `app/celery_app.py`（Celery 實例＋一顆薄薄的 `ingest_task`）、把 JobStore 的正式實作換成 `RedisJobStore`、把 Phase 62 那個「什麼都不做」的過渡派工換成真的 `ingest_task.delay(job_id)`。**這一份完全不碰 `compose.yaml`**——容器怎麼起是 Phase 66 的事。

**為什麼要做這個：**

Phase 57〜64 已經把非同步入庫的**骨架**做完了：`run_ingest_job()`（真正看圖、重試、寫庫的那一段）、`JobStore`（記錄「這個檔跑到哪了」，目前只有記憶體版）、`staging_service`（上傳當下先把檔落到 `data/staging/`）、`POST /photos` 回 202、`GET /ingest-jobs`。

**但佇列現在是空的。** `POST /photos` 收下檔案、寫 staging、在 JobStore 記一筆 `queued`，然後……就沒有然後了：**沒有任何人去執行 `run_ingest_job`**，目前只有 pytest 會直接呼叫它。用瀏覽器上傳一張照片，它會永遠停在「排隊中」。

這個 phase 就是把「沒有然後」補上：裝 Celery 與 redis 客戶端、讓入列真的把工作丟進 Redis、讓 job 狀態存進 Redis（而不是只活在 web 行程記憶體）——**因為 worker 是另一個行程，它看不到 web 行程的記憶體**。做完這一份程式碼就完整了，只差 Phase 66 把 `redis` 與 `worker` 兩個容器拉起來。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 佇列（queue） | 排隊的隊伍。有人把工作丟進去，有人拿出來做；丟的人不必等做的人做完 |
| broker（中間人／訊息中介） | 佇列**實際住的地方**。本專案用 Redis 當 broker：web 行程把「請處理 job_id=abc」寫進 Redis，worker 從 Redis 拿出來 |
| Redis | 把資料放在記憶體裡的資料庫，速度極快。這裡拿它做兩件事：① 當 Celery 的 broker ② 存 job 的進度狀態 |
| Celery | Python 的任務佇列函式庫。幫你處理「丟進 broker」「worker 取出執行」「worker 掛掉怎麼辦」這些瑣事 |
| worker（工人行程） | **另一個 Python 行程**，專門從佇列拿工作來做。跟 uvicorn（web）是兩個獨立行程，**記憶體不共用** |
| concurrency（並行數） | 一個 worker 同時開幾個子行程做事。固定 **2**（design5 D6：產品負責人上限 2） |
| `-A`（`--app`） | Celery 指令列參數，告訴它「Celery 實例在哪個模組的哪個變數」。詳見 §4.6 |
| task（任務） | 用 `@celery_app.task` 裝飾過的函式，可以被「丟進佇列稍後執行」 |
| `.delay(...)` | 「把這顆任務丟進佇列」的簡寫。`task.delay(x)` ＝ `task.apply_async(args=[x])` |
| result backend | Celery 存「任務回傳值」的地方。**我們不用**，理由見 §4.6 |
| 快照（snapshot） | 把某個當下的值抄一份存起來。入列當下把 `config.AI_BACKEND` 抄進 job，worker 用抄本 |
| pipeline（管線） | Redis 客戶端功能：把好幾個命令**一次送出去**。這裡拿它把「寫 job」與「登記進集合」綁在一起 |
| Set（集合） | Redis 的一種型別：一袋不重複的字串。`SADD` 加、`SREM` 移除、`SMEMBERS` 全部列出 |
| 序列化（serialize） | 把 Python 物件轉成可以存起來的字串。這裡用 JSON |
| lifespan | FastAPI 的「服務啟動時做什麼、關閉時做什麼」掛勾點 |
| signal（訊號） | Celery 的掛勾點。`worker_ready` ＝「worker 準備好接工作了」的那一刻 |

---

## 1. 對應 design5.md 章節

- **D5「Redis ＋ Celery」**：佇列用 Redis、worker 用 Celery；不採用 BackgroundTasks、也不自寫消費迴圈。
- **D6「兩個 worker」**：最多 2 個 Celery 子行程。本 phase 只把數字寫進註解，真的設定在 Phase 66。
- **D14「AI 開關快照」**：worker 用 job 裡的 `ai_backend` 建 VLM 客戶端；embedding 仍一律本機。
- **D15「測試不碰真 Redis」**：任務本體是 `run_ingest_job(...)`，Celery 任務只是薄薄一層 wrapper。
- **§4.1 Staging** 末條：worker／app 啟動時掃 staging，24 小時以上的孤兒檔清掉。
- **§4.3 JobStore**：「正式實作：Redis hash／JSON，key 例如 `ingest:{job_id}`」「**成功＝刪掉這筆 job**」。
- **§4.4 崩潰重送**：VLM 的 3 次是**任務函式內部**迴圈，**不要**用 Celery `autoretry` 整份重跑。
- **§4.5 AI 後端**：worker 必須用任務裡的 `ai_backend` 自己建 VLM，**與 `get_vlm()` 同一套實作、同一份 prompt**。
- **§9 測試策略**：第四道 autouse 安全網；pytest **不連真 Redis、不啟動 Celery 容器**。
- **§11**：`Celery app ＋ worker 進入點`（新建）、`requirements.txt` 加 `celery`／`redis`（`>=` 風格）。
- **§13 風險**：host `.venv` 與映像套件分岔——重建映像仍要手動煙霧一次上傳。
- 契約備忘 **§3.1**（`RedisJobStore`）、**§3.5**（`celery_app.py` 簽章與 worker 啟動指令）、**§3.6**（`CELERY_BROKER_URL`）、**§7**（鐵律第 2 條）。

---

## 2. 前置條件

**依賴：Phase 57、58、59、60、62。**（61 與 64 不是硬依賴，但實務上排在前面，做這一支時應該都在了。）

開工前**實查**基線，不要憑印象：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

docker compose ps          # db 那一列要是 Up (healthy)，否則測試會是一整片連線錯誤
pytest -q                  # 2026-08-25 增量五開工基線是 405；做到這裡會更大，以實查為準

ls -l app/services/ingest_job_store.py app/services/staging_service.py app/services/ingest_job.py
grep -n "get_job_store\|get_task_dispatcher" app/dependencies.py
grep -n "wire_memory_job_store" tests/conftest.py
grep -n "VLM_MAX_ATTEMPTS" app/core/config.py
grep -n "STAGING_MAX_AGE_HOURS" app/services/staging_service.py
```

預期：三個檔都在；`dependencies.py` 有那兩個函式；`conftest.py` 有 `wire_memory_job_store`；
`config.py` 已經有 `VLM_MAX_ATTEMPTS`（Phase 59 加）；`STAGING_MAX_AGE_HOURS` **只在**
`staging_service.py`（Phase 58 加，且 phase-58 §6 有一條驗收釘死「`app/core/config.py` 裡
不該有第二份」——契約備忘 §3.6 把它也列進 config.py 是契約自己的筆誤，以 phase-58 為準）。
本 phase **不要**重複加它們、也**不要**把 `STAGING_MAX_AGE_HOURS` 搬進 config.py，
只加 `CELERY_BROKER_URL` 一個。

**⚠️ 絕對不要同時跑兩份 pytest。** autouse 的 `reset_tables` 每顆測試都 `TRUNCATE` 同一個測試庫，兩份同時跑會互相清資料，症狀是**大量看似隨機的** 404 與 `TypeError: 'NoneType' object is not subscriptable`，每次紅的顆數還不一樣。

**本 phase 不需要 Redis 真的在跑。** 全部測試都用假的 Redis 客戶端（一個普通 Python 物件），連 `redis://` 都不會撥出去。

---

## 3. 範圍

### 做

1. `requirements.txt` 加 `celery`、`redis`。
2. `app/core/config.py` 加 `CELERY_BROKER_URL`。
3. `app/services/ingest_job_store.py` 加 `RedisJobStore`（`InMemoryJobStore` 一個字不動）。
4. `app/dependencies.py` 三處：抽出 `build_vlm_for_backend()`、`get_job_store()` 換真貨、`get_task_dispatcher()` 換真貨。
5. 新建 `app/celery_app.py`：Celery 實例 ＋ `ingest_task` ＋ `CeleryDispatcher` ＋ `worker_ready` 掃把。
6. `app/main.py` 加 lifespan，啟動時掃一次過期 staging。
7. `tests/conftest.py`：把第四道安全網補齊（fixture 名字不改，只加長身體）。
8. 新增測試：`RedisJobStore` 序列化、`celery_app` 煙霧。
9. 全量綠 ＋ **把 `CELERY_BROKER_URL` 指到死埠**再跑一次，顆數必須一模一樣。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 改 `compose.yaml`／`compose.dev.yaml` | 那是 **Phase 66**。這一份純程式碼，做完「worker 仍然跑不起來」是正常的 |
| 改 `LAUNCH.md`／`CLAUDE.md` | 也是 **Phase 66** 的事——兩份操作手冊要跟著容器一起改才對得上現實 |
| 用 Celery 的 `autoretry_for`／`max_retries` | design5 §4.4：3 次重試是 `run_ingest_job` **內部**迴圈。再包一層＝已 INSERT 的照片被插第二次 |
| 設 result backend | design5 §4.3：狀態走自己的 JobStore。開了只會為每顆任務多寫一筆沒人看的墓碑 |
| 用 `KEYS ingest:*` 列 job | Redis 官方明文「Don't use `KEYS` in your regular application code」，選型說明見 §4.4 |
| 把影像位元組放進 Celery 參數或 Redis | design5 §4.1 明文禁止。任務參數只有一個 `job_id` 字串 |
| 幫 job 加 `EXPIRE` | 失敗列要留給人看、給人按 ×。垃圾清理靠 `sweep_stale_staging()` |
| 另開一個 Redis database（`/1`）放 job | 契約 §3.6 只給一個 `CELERY_BROKER_URL`；我們的 key 都有 `ingest:` 前綴，跟 Celery 的分得很開 |
| 讓 worker 讀 `config.AI_BACKEND` | **D14 明文禁止**，那是 web 行程的記憶體變數。§4.5 有整段醒目說明 |
| 讓 embeddings 跟著 AI 開關走 | 向量必須與庫裡既有的 bge-m3 同源，**永遠本機** |
| 新增任何 HTTP 端點 | 端點數 Phase 64 已定在 **22**，本 phase 一個都不加 |
| 裝 `flower`／`celery beat` | design5 §3「不做」：不做 Flower、不做獨立監控 UI |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：§4.3 先把測試寫到**紅**，§4.4 之後才動實作。每步做完打勾。

### 4.1 `requirements.txt` 加兩個套件

- [ ] 在 `# --- 設定 ---` 那一段**之前**插入：

```text
# --- 佇列（增量五 design5.md D5：非同步入庫）---
celery>=5.4               # 任務佇列：把「等一下再做的事」丟給另一個行程做
redis>=5.0                # Redis 的 Python 客戶端；Celery 用它連 broker，RedisJobStore 也直接用
```

**為什麼兩行而不是一行 `celery[redis]`：** 官方建議寫法是 `pip install -U "celery[redis]"`（那個 bundle 會順便裝 redis 客戶端）。但我們**自己也直接用**它存 job 狀態，不是只有 Celery 在用——明寫成一條相依，讀 `requirements.txt` 的人才看得出「這個專案自己也會呼叫 Redis」。
來源：<https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html>

**下限怎麼來的：** 2026-08-25 查 PyPI，`celery` 最新 **5.6.3**（requires-python `>=3.9`）、`redis` 最新 **8.1.0**（requires-python `>=3.10`）；本機 Python 3.12 兩個都吃得下。專案慣例只釘下限，所以寫 `>=5.4` 與 `>=5.0`（都是實際存在、遠早於最新版的穩定版）。
來源：<https://pypi.org/project/celery/>、<https://pypi.org/project/redis/>

- [ ] 在 host 裝起來：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uv pip install -r requirements.txt
python -c "import celery, redis; print(celery.__version__, redis.__version__)"
```

```text
┌─ ⚠️ 已知落差：host 的 .venv ≠ 容器映像 ────────────────────────────
│ `requirements.txt` 全是 `>=`，而映像是在 `docker compose build` 那一刻才解析版本。
│ 「host 裝到 5.6.3」不代表「映像裡也是 5.6.3」。這是 CLAUDE.md 已記在案的取捨
│ （side project 先不釘版），代價是：**「重建映像」要當成需要手動煙霧一次的動作。**
│ 本 phase 只在 host 裝；Phase 66 會 build，那時**一定要**照它的 §4.7 跑真容器煙霧，
│ 不可以只看 pytest 綠就收工（design5 §13 最後一列）。
└──────────────────────────────────────────────────────────────────
```

### 4.2 `app/core/config.py` 加 `CELERY_BROKER_URL`

- [ ] 在 `OLLAMA_BASE_URL` 那一行之後加：

```python
# 佇列的中間人（broker）位址（增量五 design5.md D5／§7）。
# 預設值是**容器裡**的長相：redis 是 compose 的服務名、6379 是 Redis 預設埠、
# /0 是 Redis 的第 0 號 database（Redis 內建 16 個互不相干的編號空間）。
# 在 Mac 上跑 pytest 時根本用不到它——測試的 JobStore 是記憶體版、派工是假的
# （tests/conftest.py 的 wire_memory_job_store）。
# 真要在 host 手動連容器裡的 Redis 除錯，就在 .env 覆蓋成 redis://127.0.0.1:6379/0。
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
```

URL 格式來源（`redis://:password@hostname:port/db_number`，各段皆可省略）：
<https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html>

### 4.3 先寫測試（紅）

#### 4.3-1　新建 `tests/unit/test_celery_app_unit.py`

> 這個檔名契約 §2.3 沒有列（那張表只列 57／58／59／60／64／71 的測試檔）。
> 本 phase 新增，命名沿用既有的 `tests/unit/*_unit.py` 慣例。

```python
"""app/celery_app.py 的煙霧測試（Phase 65）。

只驗「組裝對不對」，不驗行為：匯入得起來、broker 指到設定、沒有 result backend、
任務名稱逐字等於契約 §3.5、依快照挑 VLM 且不受 config.AI_BACKEND 影響（D14 守門員）。

全程零網路：建 Celery 實例不會連 broker；建 OllamaVLM／OllamaCloudVLM 也不會連線
（真正發請求的是 invoke()／chat()）。
"""

from app import dependencies
from app.celery_app import celery_app, ingest_task
from app.core import config
from app.services import vlm_service


def test_celery實例的broker等於設定裡那一條():
    assert celery_app.conf.broker_url == config.CELERY_BROKER_URL


def test_沒有設定result_backend():
    # design5 §4.3：狀態走自己的 JobStore。沒設定時 Celery 給 None 或空字串，兩種都算過
    assert not celery_app.conf.result_backend


def test_任務名稱逐字等於契約寫的那一個():
    assert ingest_task.name == "personaldocai.ingest"
    assert "personaldocai.ingest" in celery_app.tasks   # 真的登記進任務表，worker 才找得到


def test_快照決定用哪一種看圖物件(monkeypatch):
    # HTTP header 不吃中文，假 key 一律 ASCII（2026-08-22 踩過）
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    assert isinstance(
        dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM
    )
    assert isinstance(dependencies.build_vlm_for_backend("local"), vlm_service.OllamaVLM)


def test_快照贏過開關(monkeypatch):
    """D14 的守門員：worker 只認快照，不認 config.AI_BACKEND。

    這一顆紅了，代表 worker 會被「使用者中途撥回本機」影響，或更糟——
    worker 行程裡的 AI_BACKEND 永遠是 local，於是快照 cloud 也走本機。
    """
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    assert isinstance(dependencies.build_vlm_for_backend("local"), vlm_service.OllamaVLM)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    assert isinstance(
        dependencies.build_vlm_for_backend("cloud"), vlm_service.OllamaCloudVLM
    )
```

#### 4.3-2　`tests/unit/test_ingest_job_store_unit.py`：檔尾接上假 Redis 與新測試

- [ ] 檔案最上面補 import（Phase 57 若已有就不必重複）：

```python
import json

from app.services import ingest_job_store
```

- [ ] 把下面整段接在 Phase 57 那些 `InMemoryJobStore` 測試**之後**（前面那些不要動）：

```python
# ---------- Phase 65 追加：RedisJobStore 的序列化測試 ----------
#
# 用一個「夠用就好」的假 Redis：只實作 RedisJobStore 真的會呼叫的那幾個命令。
# 刻意寫在這個測試檔裡、不放進 tests/fakes.py——只有這一支用得到它，
# 而 tests/fakes.py 是 conftest 匯入的公用假件區，放進去等於全域多一個名字。
#
# 值一律存 str，模仿正式路徑 Redis(..., decode_responses=True) 的行為。
# 不加那個參數的話 Redis 回來的是 bytes，smembers() 拿到 b"abc"，
# 組出來的 key 會變成 "ingest:b'abc'"，而且是**安靜地錯**。


class FakeRedisClient:
    """假 Redis：一個普通的 Python 物件，不開 socket、不連線。"""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def set(self, key: str, value: str) -> None:
        self.strings[key] = value

    def get(self, key: str) -> str | None:
        return self.strings.get(key)

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.strings.get(key) for key in keys]

    def delete(self, key: str) -> None:
        self.strings.pop(key, None)

    def sadd(self, key: str, *members: str) -> None:
        self.sets.setdefault(key, set()).update(members)

    def srem(self, key: str, *members: str) -> None:
        self.sets.setdefault(key, set()).difference_update(members)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)


class FakePipeline:
    """假 pipeline：記下命令，execute() 時照順序套用到 FakeRedisClient 上。"""

    def __init__(self, client: FakeRedisClient) -> None:
        self._client = client
        self._queued: list[tuple[str, tuple]] = []

    def set(self, key, value):
        self._queued.append(("set", (key, value)))
        return self

    def delete(self, key):
        self._queued.append(("delete", (key,)))
        return self

    def sadd(self, key, *members):
        self._queued.append(("sadd", (key, *members)))
        return self

    def srem(self, key, *members):
        self._queued.append(("srem", (key, *members)))
        return self

    def execute(self) -> list:
        for name, args in self._queued:
            getattr(self._client, name)(*args)
        self._queued.clear()
        return []


def _建一個store(job_id="j1", content_type="image/png"):
    client = FakeRedisClient()
    store = ingest_job_store.RedisJobStore(client)
    store.create(
        job_id=job_id, filename=f"{job_id}.png", content_type=content_type,
        ai_backend="local", source="upload",
    )
    return client, store


def test_create把job寫成JSON並登記進open集合():
    client = FakeRedisClient()
    store = ingest_job_store.RedisJobStore(client)
    job = store.create(
        job_id="j1", filename="收據.jpg", content_type="image/jpeg",
        ai_backend="cloud", source="upload",
    )
    # 初始值逐字照契約 §3.1
    assert job["status"] == "queued"
    assert job["attempt"] == 0
    assert job["pages_done"] == 0
    assert job["photo_ids"] == []
    assert job["page_count"] is None
    assert job["ai_backend"] == "cloud"
    assert job["source"] == "upload"
    # 真的落成 JSON 字串，key 是 ingest:{job_id}；也登記進「還沒結束」的集合
    assert json.loads(client.strings["ingest:j1"])["filename"] == "收據.jpg"
    assert client.smembers("ingest:open") == {"j1"}


def test_get讀回來的與create給的一模一樣_找不到回None():
    _, store = _建一個store()
    assert store.get("j1")["filename"] == "j1.png"
    assert store.get("不存在") is None


def test_update只改指定欄位其餘保留():
    _, store = _建一個store()
    改完 = store.update("j1", status="analyzing", attempt=1)
    assert 改完["status"] == "analyzing"
    assert 改完["attempt"] == 1
    assert 改完["filename"] == "j1.png"                 # 沒動到的還在
    assert store.get("j1")["status"] == "analyzing"     # 真的寫回去了


def test_update不存在的job回None且不寫任何東西():
    client = FakeRedisClient()
    store = ingest_job_store.RedisJobStore(client)
    assert store.update("不存在", status="failed") is None
    assert client.strings == {}


def test_非字串欄位能原樣往返():
    """photo_ids 是 list[int]、page_count 是 int|None、error 是 str|None。

    JSON 序列化最容易在這裡出事（例如 list 存成字串卻讀回字串）。
    """
    _, store = _建一個store(content_type="application/pdf")
    store.update("j1", page_count=3, pages_done=2, photo_ids=[11, 12], error=None)
    讀回 = store.get("j1")
    assert 讀回["page_count"] == 3
    assert 讀回["photo_ids"] == [11, 12]
    assert 讀回["error"] is None


def test_delete同時刪掉JSON與open集合裡的id():
    client, store = _建一個store()
    store.delete("j1")
    assert client.strings == {}
    assert client.smembers("ingest:open") == set()
    assert store.get("j1") is None


def test_list_open只回還沒刪掉的job():
    client = FakeRedisClient()
    store = ingest_job_store.RedisJobStore(client)
    for job_id in ("j1", "j2", "j3"):
        store.create(
            job_id=job_id, filename=f"{job_id}.png", content_type="image/png",
            ai_backend="local", source="upload",
        )
    store.delete("j2")                     # 成功＝delete（design5 §4.3）
    assert [job["job_id"] for job in store.list_open()] == ["j1", "j3"]


def test_list_open遇到集合有id但資料不見時自己修好():
    """AOF 半截、或有人手動 DEL 掉某把 key 時，集合裡會留下孤兒 id。

    list_open() 要跳過它、順手 SREM 掉，不可以炸掉整個進度面板。
    """
    client, store = _建一個store()
    client.sadd("ingest:open", "孤兒")      # 只有集合有，沒有對應 JSON
    assert [job["job_id"] for job in store.list_open()] == ["j1"]
    assert client.smembers("ingest:open") == {"j1"}


def test_list_open沒有任何job時回空清單():
    store = ingest_job_store.RedisJobStore(FakeRedisClient())
    assert store.list_open() == []
```

- [ ] **跑它，確認是紅的：**

```bash
pytest tests/unit/test_ingest_job_store_unit.py tests/unit/test_celery_app_unit.py -q
```

  預期：大量 `AttributeError: module 'app.services.ingest_job_store' has no attribute 'RedisJobStore'`
  與 `ModuleNotFoundError: No module named 'app.celery_app'`。**這是對的**，往下做。

### 4.4 `RedisJobStore`（`app/services/ingest_job_store.py` 檔尾追加）

```text
┌─ 選型：`list_open()` 怎麼知道有哪些 job？（三選一，選第三個）────────
│
│ ① `KEYS ingest:*` ——❌ 不用。Redis 官方原文警告：
│     "Use extreme care when using this command in production environments.
│      It may ruin performance when it is executed against large databases.
│      ... Don't use KEYS in your regular application code.
│      If you're looking for a way to find keys in a subset of your keyspace,
│      consider using SCAN or sets."
│    它是 O(N)，N ＝**整個 database 的 key 數**（裡面還有 Celery 自己一堆 key），
│    而且會**卡住** Redis 直到掃完（Redis 是單執行緒）。進度面板每 2 秒打一次
│    `GET /ingest-jobs`，等於每 2 秒卡一次。
│    來源：<https://redis.io/docs/latest/commands/keys/>
│
│ ② `SCAN` ——❌ 不用。它不卡住 Redis，是官方推薦的兩個替代之一。
│    但代價：(a) 要自己寫「一直掃到游標回 0」的迴圈；(b) 掃描期間新增／刪除的 key
│    **不保證**掃得到，同一把 key 還可能重複出現、程式要自己去重。
│    成本仍跟整個 keyspace 大小成正比。
│
│ ③ **自己維護一個 Set** ——✅ 選這個（官方推薦的另一個替代）。
│    多一把 key `ingest:open` 放「還沒結束的 job_id」：
│    `create()` 時 `SADD`、`delete()` 時 `SREM`；`list_open()` ＝
│    `SMEMBERS` 拿一小袋 id ＋ 一次 `MGET` 撈回 JSON。
│    成本跟「**進行中的 job 數**」成正比，不是整個 keyspace。而且 design5 §4.3 的
│    「成功＝刪掉這筆 job」剛好讓集合一直很小（平常是空的，忙時個位數）。
│
│ 代價：兩份資料要同步。處理方式：寫入用 **pipeline** 把 `SET`＋`SADD`
│（與 `DEL`＋`SREM`）一次送出；`list_open()` 做**自我修復**——集合裡有 id 但
│ JSON 不見了就順手 `SREM`。
└──────────────────────────────────────────────────────────────────
```

- [ ] 在檔案**最後面**追加（`InMemoryJobStore` 一個字都不要改）：

```python
# ---------- Phase 65 追加：正式用的 Redis 實作 ----------

import json  # 搬去檔頭 import 區也行；寫在這裡是讓整段可以一刀貼上

# key 的長相：
#   ingest:{job_id}  一筆 job 的 JSON
#   ingest:open      還沒結束的 job_id 集合（成功＝delete，所以平常是空的）
# 前綴讓我們的 key 跟 Celery 塞在同一個 database 的 key（celery、_kombu.*、unacked*）
# 完全分得開，不必為了乾淨另外開一個 database。
JOB_KEY_PREFIX = "ingest:"
OPEN_SET_KEY = "ingest:open"


def job_key(job_id: str) -> str:
    """一筆 job 在 Redis 裡的 key。"""
    return f"{JOB_KEY_PREFIX}{job_id}"


class RedisJobStore:
    """把 job 狀態存進 Redis 的實作（正式路徑，design5.md §4.3）。

    為什麼不能放行程記憶體：**worker 是另一個行程**。web 建的 job，worker 要看得到、
    改得動，人再從 web 的 GET /ingest-jobs 讀回來——三方碰同一份資料，只能放共用的地方。

    介面與 InMemoryJobStore 逐字相同（契約 §3.1 的 JobStore Protocol），
    所以 run_ingest_job 不知道自己拿到哪一種，測試才換得掉。

    client 從外面注入（dependencies.get_job_store 建好給它），本類別不決定連哪台
    ——單元測試才塞得進假的客戶端。

    ★ 前提：client 必須用 decode_responses=True 建，回來的才是 str。
      沒有那個參數的話 smembers() 回 bytes，組出的 key 變成 "ingest:b'abc'"，
      而且是安靜地錯——list_open() 只是永遠回空清單。
    """

    def __init__(self, client) -> None:
        self._client = client

    def create(
        self,
        *,
        job_id: str,
        filename: str,
        content_type: str,
        ai_backend: str,
        source: str,
    ) -> IngestJob:
        """建一筆新的 job。初始值逐字照契約 §3.1。"""
        job: IngestJob = {
            "job_id": job_id,
            "filename": filename,
            "content_type": content_type,
            "status": "queued",
            "attempt": 0,
            "page_count": None,
            "pages_done": 0,
            "photo_ids": [],
            "error": None,
            "ai_backend": ai_backend,
            "source": source,
        }
        # pipeline ＝ 兩個命令一次送出。不是交易，但至少不會「寫了 JSON、
        # 網路斷在中間、集合沒登記到」——那樣這筆 job 會從進度面板憑空消失。
        pipe = self._client.pipeline()
        pipe.set(job_key(job_id), json.dumps(job))
        pipe.sadd(OPEN_SET_KEY, job_id)
        pipe.execute()
        return job

    def get(self, job_id: str) -> IngestJob | None:
        raw = self._client.get(job_key(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    def update(self, job_id: str, **fields) -> IngestJob | None:
        """改幾個欄位。找不到就回 None（不會建出一筆半殘的 job）。

        這是「讀出來、改一改、寫回去」，中間沒有鎖。實務上安全，因為同一筆 job
        幾乎不可能被兩個行程同時改：web 只在 create（入列）與 delete（dismiss）時碰它，
        worker 負責 status／attempt／pages_done／photo_ids；唯一想得到的競態是
        「worker 正在寫 status、人同時按 dismiss」，但 dismiss 只准對 failed，
        而 failed 是 worker 寫完就不再動的終態。side project 不上樂觀鎖（WATCH／MULTI）。
        """
        job = self.get(job_id)
        if job is None:
            return None
        job.update(fields)
        self._client.set(job_key(job_id), json.dumps(job))
        return job

    def delete(self, job_id: str) -> None:
        """把這筆 job 從系統拿掉。**成功入庫走的就是這一條**（design5 §4.3）。"""
        pipe = self._client.pipeline()
        pipe.delete(job_key(job_id))
        pipe.srem(OPEN_SET_KEY, job_id)
        pipe.execute()

    def list_open(self) -> list[IngestJob]:
        """列出還沒結束的 job（queued／analyzing／retrying／failed）。

        成功的已經被 delete 掉，所以這裡天生不含成功；再對 JOB_STATUSES 濾一次
        是防禦性的——與 InMemoryJobStore.list_open 同一道（Phase 57）：兩種實作
        對外行為必須一致，測試才換得掉。
        用 job_id 排序只是要「同一份資料每次回來順序一樣」（測試好寫、面板不會每 2 秒
        跳來跳去）；真正要怎麼排是 Phase 67 前端的事。
        """
        job_ids = sorted(self._client.smembers(OPEN_SET_KEY))
        if not job_ids:
            return []
        raws = self._client.mget([job_key(job_id) for job_id in job_ids])

        jobs: list[IngestJob] = []
        孤兒: list[str] = []
        for job_id, raw in zip(job_ids, raws):
            if raw is None:
                # 集合有這個 id，但 JSON 不見了（AOF 半截、有人手動 DEL…）。
                # 這種殘骸不該讓整個進度面板炸掉，順手清掉即可。
                孤兒.append(job_id)
                continue
            job = json.loads(raw)
            if job.get("status") not in JOB_STATUSES:
                # 沒定義過的狀態不准出現在使用者的進度面板上（防禦性，同記憶體版）
                continue
            jobs.append(job)
        if 孤兒:
            self._client.srem(OPEN_SET_KEY, *孤兒)
        return jobs
```

### 4.5 `app/dependencies.py`：三處改動

```text
┌─ ⚠️⚠️ 本 phase 最容易做錯、而且錯了**不會報錯**的地方 ⚠️⚠️ ────────
│
│ **worker 是另一個行程。**
│
│ 頁首那顆「AI 模型：本機｜雲端」開關打的是 PUT /settings/ai-backend，
│ 它只做一件事：`config.AI_BACKEND = request.backend`
│ ——那是 **web 行程（uvicorn）記憶體裡的一個變數**。
│
│ worker 是 `celery … worker` 這個**完全獨立的 Python 行程**，它有自己一份
│ `app.core.config` 模組，`AI_BACKEND` 在它那邊**從啟動到死都是預設值 "local"**。
│
│   ✗ worker 裡呼叫 dependencies.get_vlm()
│       → 永遠拿本機 gemma4 → 使用者切了雲端也沒用，而且**畫面上完全看不出來**
│         （202 照回、進度列照走，只是慢到天荒地老）
│   ✓ worker 依 **job 裡的 ai_backend 快照** 自己建 VLM 客戶端
│
│ design5 D14／§4.5 明文：worker「必須用任務裡的 ai_backend 自己建 VLM 客戶端
│ （本機 OllamaVLM／雲端 OllamaCloudVLM），**與 get_vlm() 同一套實作、同一份 prompt**」。
│
│ 「同一套實作」怎麼做到不走樣：把 get_vlm() 現在那兩行 if／return 原封不動抽成
│ build_vlm_for_backend(ai_backend)，再讓 get_vlm() 去呼叫它。兩邊拿到的是
│ **同兩個 lru_cache 出來的物件**，prompt 一律由 vlm_service.build_vlm_prompt()
│ 產生，不可能分岔。
└──────────────────────────────────────────────────────────────────
```

- [ ] **改動一：抽出 `build_vlm_for_backend()`。** 把現在的 `get_vlm()` 換成下面兩個函式
      （`_ollama_vlm()`／`_ollama_cloud_vlm()` 兩個 lru_cache helper 一個字都不動）：

```python
def build_vlm_for_backend(ai_backend: str) -> vlm_service.VLMClient:
    """依「指定的」後端建看圖物件——**不看** config.AI_BACKEND。

    誰會用它：
    - get_vlm()（下面那個）：web 行程，參數是當下的開關值
    - app/celery_app.py 的 ingest_task：worker 行程，參數是**入列當下寫進 job 的快照**
      （design5.md D14）。worker 讀不到 web 行程的開關，只能靠快照。

    兩條路拿到同兩個物件、同一份 prompt——這一支就是「同一套實作」的保證。
    """
    if ai_backend == "cloud":
        return _ollama_cloud_vlm()
    return _ollama_vlm()


def get_vlm() -> vlm_service.VLMClient:
    """給 router 的看圖物件。跟著頁首的 AI 開關走：本機（預設）或 Ollama Cloud。

    每個請求都當場讀一次 config.AI_BACKEND——開關撥完，下一次上傳立刻生效。

    pytest 若要換成 FakeVLM：app.dependency_overrides[get_vlm] = ...
    那個覆寫只活在測試裡，不影響 uvicorn。
    """
    return build_vlm_for_backend(config.AI_BACKEND)
```

- [ ] **改動二：`get_job_store()` 正式回 `RedisJobStore`**（換掉 Phase 57 那個「正式也回記憶體版」的過渡實作）：

```python
@lru_cache(maxsize=1)
def _redis_client():
    """整個行程共用一個 Redis 客戶端。

    建立它**不會連線**（redis-py 是第一次真的下命令時才撥號），所以 pytest
    就算不小心走到這裡也不會卡在連線逾時。

    decode_responses=True 一定要有：不加的話 Redis 回來的是 bytes，
    smembers() 拿到 b"abc"，組出來的 key 變成 "ingest:b'abc'"——而且是安靜地錯，
    list_open() 只會永遠回空清單。
    from_url 的 URL 格式：<https://redis.readthedocs.io/en/stable/connections.html>
    """
    import redis

    return redis.Redis.from_url(config.CELERY_BROKER_URL, decode_responses=True)


def get_job_store() -> ingest_job_store.JobStore:
    """入庫任務的進度簿。

    正式：Redis（web 與 worker 兩個行程共用同一份資料）。
    測試：tests/conftest.py 的 wire_memory_job_store 會換成 InMemoryJobStore
    ——pytest 絕不連真 Redis（design5 §9、契約 §7 第 2 條）。
    """
    return ingest_job_store.RedisJobStore(_redis_client())
```

  （檔案最上面的 `from app.services import (...)` **Phase 57 就已經**把 `ingest_job_store`
  加進去了，這裡不必再動 import。）

- [ ] **改動二之二：把 Phase 57 的 `_memory_job_store()` 這個 `@lru_cache` helper 整段刪掉。**
      它唯一的兩個用途都在本 phase 消失：`get_job_store()` 的舊本體（上面已換成 Redis 版）、
      `tests/conftest.py` 那行 `dependencies._memory_job_store().clear()` 雙保險（§4.8 會一併
      拿掉，由 monkeypatch 取代）。留著＝一顆永遠沒人呼叫的單例，之後讀碼的人會以為還有第三條路。
      刪完跑 `grep -rn "_memory_job_store" app/ tests/` 必須**零輸出**（§6 有這一條）。

- [ ] **改動三：`get_task_dispatcher()` 的函式本體換成真的派工。** 這正是 phase-62 §4.2
      預告的那一次換裝（「換的時候只改 `get_task_dispatcher()` 這一個函式，router 一個字都不動」）：
      `TaskDispatcher` Protocol、`NoopDispatcher` 類別、router 裡的 `dispatcher.dispatch(job_id)`
      **全部一個字都不動**。`NoopDispatcher` 從此沒人用，**留著不刪**——刪它就多了第二處改動，
      而且它的 docstring 本來就寫明自己只活在 Phase 62〜64，讀到的人不會誤會：

```python
def get_task_dispatcher() -> TaskDispatcher:
    """給 router 的入列器。**全系統只有這一個地方碰 Celery。**

    Phase 62〜64 這裡回 NoopDispatcher（沒人接住任務是當時的預期行為）；
    Phase 65 起回 CeleryDispatcher（住在 app/celery_app.py），它的 dispatch(job_id)
    會真的把訊息寫進 Redis。router 只呼叫 dispatcher.dispatch(job_id)，
    完全不知道底下是 Celery——這正是 Phase 62 先立好抽象、本 phase 才換得掉的原因。

    ★ import 寫在函式裡面（不是檔案最上面），兩個理由：
      ① app/celery_app.py 會 import 這個模組（它要拿 get_job_store、
         build_vlm_for_backend、get_embeddings）。這裡若在最上面 import 它，就是循環匯入。
      ② pytest 收集階段不必為了跑一顆前端字串測試就把整個 Celery 拉起來
        （測試一律被 §4.8 的假派工蓋掉，這個函式本體在 pytest 裡根本不會執行）。
    """
    from app.celery_app import CeleryDispatcher

    return CeleryDispatcher()
```

  `CeleryDispatcher` 本身住在 `app/celery_app.py`（§4.6 有完整程式碼），與 phase-62 §4.2
  的三實作表逐字對上（`CeleryDispatcher`｜`app/celery_app.py`｜`ingest_task.delay(job_id)`）。
  ⚠ **不要**把它寫成「回傳一個裸函式」：router 呼叫的是 `dispatcher.dispatch(job_id)`
  （phase-62 的 Protocol 只有這一個方法），裸函式沒有 `.dispatch` 屬性，一上傳就炸
  `AttributeError`。

### 4.6 新建 `app/celery_app.py`

```python
"""Celery 的進入點（增量五 design5.md D5／D15；契約 §3.5）。

worker 用這一支啟動：

    celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=2

那串 `-A`（＝ `--app`）要怎麼讀：
    app.celery_app          ← Python 模組路徑，也就是這個檔案（app/celery_app.py）
                .celery_app ← 這個模組裡那個變數的名字（下面 celery_app = Celery(...)）
官方文件寫的正式格式是 module.path:attribute（冒號版）；點號版等價、兩種都收。
只寫 `-A app.celery_app`（不指名變數）通常也動得了——官方的搜尋順序是：
屬性 app → 屬性 celery → 「模組裡任何值是 Celery 實例的屬性」，第三步會撈到 celery_app。
但那是靠搜尋：哪天這個檔多出第二個 Celery 物件（或變數改名）就挑不準；
把變數名寫全＝完全不靠搜尋。（搜尋全部落空時的錯誤長相：
Unable to load celery application. Module 'app.celery_app' has no attribute 'app'。）
<https://docs.celeryq.dev/en/stable/getting-started/next-steps.html>
<https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html>

★ 本檔刻意寫得很薄（design5.md D15）：所有規則（VLM 重試 3 次、PDF 逐頁、
  失敗清乾淨、冪等）都在 run_ingest_job 裡，這裡只負責「把零件組好、呼叫它」。
  所以測試可以直接呼叫 run_ingest_job，不必啟動 Celery、不必有 Redis。
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready

from app import dependencies
from app.core import config
from app.services import staging_service
from app.services.ingest_job import run_ingest_job

logger = logging.getLogger(__name__)

# 第一個參數是「這個 app 的名字」，會出現在 worker 的啟動畫面與 log 裡。
# backend=None ＝**不要 result backend**（design5.md §4.3）：
#   result backend 是 Celery 存「任務回傳值」的地方。我們的任務回傳 None，
#   進度狀態全部走自己的 JobStore（前端 GET /ingest-jobs 讀的就是它），
#   開了它只會為每顆任務多寫一筆永遠沒人看的「墓碑」。
#   官方設定表也寫得很清楚：result_backend 預設就是「沒有」
#  （原文 "Default: No result backend enabled by default."）。
#   <https://docs.celeryq.dev/en/stable/userguide/configuration.html>
# （契約 §3.5 的範例寫 settings.CELERY_BROKER_URL——那是通稱；本專案的設定模組
#   叫 config（app/core/config.py），常數名相同。不要真的去建一個 settings 模組。）
celery_app = Celery("personaldocai", broker=config.CELERY_BROKER_URL, backend=None)

# broker 一時連不上時，啟動階段要不要重試。官方設定表列的預設是 Enabled，
# 但某些 5.x 版本啟動時會為了 6.0 的行為變更印一段提醒——明寫這一行就不會再唸。
celery_app.conf.broker_connection_retry_on_startup = True


@celery_app.task(name="personaldocai.ingest")
def ingest_task(job_id: str) -> None:
    """worker 真正執行的東西——薄薄一層 wrapper（design5.md D15）。

    只做四件事：撈 job、依快照組零件、呼叫 run_ingest_job、結束。

    ★ 為什麼 vlm 用 job["ai_backend"] 而不是 dependencies.get_vlm()：
      頁首開關改的是 **web 行程**記憶體裡的 config.AI_BACKEND；worker 是另一個行程，
      它那份永遠是預設的 "local"。入列當下已經把當時的值抄進 job（D14），用抄本才對。

    ★ 為什麼 embeddings 直接用 get_embeddings()：向量**永遠本機**、不歸開關管
      ——庫裡既有的向量都是本機 bge-m3 算的，換一顆就比不出東西。

    ★ 這裡**沒有** Celery 的 autoretry（design5.md §4.4）：「同一張圖最多送 VLM 3 次」
      是 run_ingest_job **內部**的迴圈。在這一層再加自動重試，會讓「已經 INSERT 成功的
      JPEG 被插第二次」。崩潰重送的冪等靠 job 裡的 photo_ids／pages_done，也在那裡。
    """
    store = dependencies.get_job_store()
    job = store.get(job_id)
    if job is None:
        # 任務被重送、但這筆 job 已經被 dismiss 或清掉了。什麼都不做就好
        # ——丟例外只會讓 Celery 印出一整片沒有意義的紅字。
        logger.warning("找不到 job，略過這次派工：job_id=%s", job_id)
        return

    run_ingest_job(
        job_id,
        store=store,
        vlm=dependencies.build_vlm_for_backend(job["ai_backend"]),
        embeddings=dependencies.get_embeddings(),
        now=dependencies.get_now,
    )


class CeleryDispatcher:
    """把一筆 job 丟進佇列的入列器——phase-62 §4.2 三實作表的第三個，本 phase 落地。

    router 只呼叫 dispatch(job_id)（Phase 62 的 TaskDispatcher Protocol 就這一個方法）；
    dependencies.get_task_dispatcher() 回的就是這一個。

    dispatch 裡的 .delay(x) ＝ .apply_async(args=[x]) 的簡寫（官方 Calling Tasks 指南）。
    那一行**只是把訊息寫進 Redis**，不等 worker 做完——這就是 202 的由來。
    <https://docs.celeryq.dev/en/stable/userguide/calling.html>
    """

    def dispatch(self, job_id: str) -> None:
        ingest_task.delay(job_id)


@worker_ready.connect
def _worker啟動時掃一次過期暫存檔(sender=None, **kwargs) -> None:
    """worker 準備好接工作的那一刻，順手清掉 data/staging 裡的孤兒檔。

    worker_ready 是 Celery 的訊號（signal），意思是「worker 初始化完成、可以開始拿工作」。
    <https://docs.celeryq.dev/en/stable/userguide/signals.html>

    為什麼要掃：上傳當下先落 staging 再入列。那之間斷電、或 Redis 資料掉了，
    那個檔就變成沒人認領的孤兒。sweep_stale_staging()（Phase 58 寫好的）只清
    「超過 24 小時、而且 JobStore 裡沒有對應進行中任務」的檔——正在跑的絕不會被誤刪。

    整段包在 try 裡：掃把失敗只是少清幾個垃圾檔，**絕不可以讓 worker 起不來**。
    """
    try:
        清掉幾個 = staging_service.sweep_stale_staging(dependencies.get_job_store())
        logger.info("staging 掃把（worker 啟動）：清掉 %d 個過期暫存檔", 清掉幾個)
    except Exception:
        logger.warning("staging 掃把執行失敗，不影響 worker 啟動", exc_info=True)
```

### 4.7 `app/main.py`：啟動時也掃一次

> 掃把接線的分工，先講清楚免得對不上帳：phase-58 只寫 `sweep_stale_staging()` 函式本體，
> 明文說「接線是 Phase 65／66 的事」。**兩頭的接線其實都在本 phase**——app 這頭是本節的
> lifespan，worker 那頭是 §4.6 的 `worker_ready` 掃把；Phase 66 零程式碼，只在真容器的
> worker log 裡驗到那行「staging 掃把（worker 啟動）」（phase-66 §4.6）。

- [ ] 在 `app = FastAPI(...)` **之前**加入 lifespan，並把原本那一行換成最後那一行。
      新增的兩個 import（`asynccontextmanager`、`dependencies`／`staging_service`）併進檔頭；
      lifespan 函式要放在 `_app_logger` 那段設定**之後**——它的身體用得到 `_app_logger`：

```python
from contextlib import asynccontextmanager

from app import dependencies
from app.services import staging_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動／關閉時要做的事（增量五 design5.md §4.1）。

    啟動時掃一次 data/staging，把「超過 24 小時、而且 JobStore 裡沒有對應進行中任務」
    的孤兒檔清掉。這是崩潰後的後悔藥——上傳當下先落 staging 再入列，中間斷電的話
    那個檔就沒人認領了。

    worker 那邊也有一份一樣的（app/celery_app.py 的 worker_ready）。兩邊都掃是刻意的：
    常駐時兩個容器一起起來，誰先掃到都行；只起其中一個時也不會漏。
    sweep_stale_staging 本身冪等，掃兩次沒有副作用。

    整段包在 try 裡：掃把失敗只是少清幾個垃圾檔，**絕不可以讓服務起不來**。
    """
    try:
        清掉幾個 = staging_service.sweep_stale_staging(dependencies.get_job_store())
        _app_logger.info("staging 掃把（app 啟動）：清掉 %d 個過期暫存檔", 清掉幾個)
    except Exception:
        _app_logger.warning("staging 掃把執行失敗，不影響服務啟動", exc_info=True)
    yield
    # 關閉時沒有要做的事：資料庫連線是每個請求現開現關（app/db/session.py）


app = FastAPI(title="PersonalDocAI", lifespan=lifespan)
```

  （`include_router` 那七行、`/health`、`/`、`app.mount("/ui", …)` 全部不動。）

### 4.8 `tests/conftest.py`：把第四道安全網補齊

```text
┌─ ⚠️ 為什麼非補不可 ─────────────────────────────────────────────
│ `app.dependency_overrides[...]` **只對 router 上的 Depends(...) 生效**。
│ 但本 phase 新增了兩個「直接呼叫」的地方：
│   ① app/main.py 的 lifespan 掃把 → 直接 dependencies.get_job_store()
│      （conftest 的 client fixture 用 `with TestClient(app)`，**會真的觸發 lifespan**）
│   ② app/celery_app.py 的 ingest_task → 同樣直接呼叫
│ 這兩處會拿到**正式的 RedisJobStore**，一下命令就往 redis://redis:6379 撥號——
│ Mac 上根本沒有那台主機，於是一堆連線錯誤或逾時。
│
│ 另外 get_task_dispatcher() 現在回的是 CeleryDispatcher——`POST /photos` 一入列
│ 就 .delay()，測試會直接撞 Redis。
│
│ 修法：在**既有的** wire_memory_job_store 裡加 monkeypatch 與預設假派工。
│ **fixture 名字不要改**（契約 §7 第 2 條釘死了），只是把身體加長。
└──────────────────────────────────────────────────────────────────
```

- [ ] 把 Phase 57 建的那道 fixture 改成下面這樣。**與 Phase 57 版逐項對照**：
      autouse、名字、`yield store`、結束時 `pop` 覆寫——**全部保留**；
      多了 `monkeypatch` 參數、兩個 `monkeypatch.setattr`、預設假派工；
      **少了** `dependencies._memory_job_store().clear()` 那一行雙保險
      （那個單例已在 §4.5 改動二之二刪除；monkeypatch 比清空更徹底——
      直接呼叫的人拿到的就是本測試這一顆，不是另一顆要記得清的全域）：

```python
@pytest.fixture(autouse=True)
def wire_memory_job_store(monkeypatch):
    """第四道安全網（Phase 57 建、Phase 65 加長）：JobStore 一律記憶體版，派工一律假的。

    pytest **絕不連真 Redis、絕不啟動 Celery**（design5.md §9、契約 §7 第 2 條）。
    本機開發時 Redis 容器常常開著，忘了覆寫就會默默把測試資料寫進去。

    三件事缺一不可：
    ① dependency_overrides → router 上 Depends(get_job_store) 的拿到記憶體版
       （Phase 57 原有的那一半，原封不動）
    ② monkeypatch dependencies.get_job_store → **直接呼叫**的地方也拿到同一顆
       （app/main.py 的 lifespan 掃把、app/celery_app.py 的 ingest_task 都不走 Depends）
    ③ 派工換成假的 → 不然 POST /photos 會真的 .delay() 出去撞 Redis。
       假件必須有 .dispatch() 方法（phase-62 的 TaskDispatcher Protocol；
       router 呼叫的是 dispatcher.dispatch(job_id)，塞裸函式會炸 AttributeError）。
       要跑任務的測試一律**自己**呼叫 run_ingest_job(...)（design5.md §9 的圖）。
    """
    store = InMemoryJobStore()
    dispatched: list[str] = []

    class 記帳假派工:
        """符合 TaskDispatcher Protocol 的最小假件：只把 job_id 記下來。"""

        def dispatch(self, job_id: str) -> None:
            dispatched.append(job_id)

    假派工 = 記帳假派工()

    app.dependency_overrides[get_job_store] = lambda: store
    monkeypatch.setattr(dependencies, "get_job_store", lambda: store)
    app.dependency_overrides[get_task_dispatcher] = lambda: 假派工
    monkeypatch.setattr(dependencies, "get_task_dispatcher", lambda: 假派工)

    # 要斷言「有沒有派工出去」的測試，把這個 fixture 寫進參數列、讀 store.dispatched
    store.dispatched = dispatched
    yield store
    app.dependency_overrides.pop(get_job_store, None)
    app.dependency_overrides.pop(get_task_dispatcher, None)
```

  import 只差一樣：`from app.dependencies import (...)` 那一串**加上 `get_task_dispatcher`**。
  （`from app import dependencies`、`get_job_store`、`InMemoryJobStore` 三樣 Phase 57 都已經加了。）

> 📌 Phase 62 **沒有**動過這道 fixture——它那兩顆入列器測試（記事本入列器／一定壞掉的入列器）
> 是每顆自己 `app.dependency_overrides[get_task_dispatcher] = ...`，測完由 wire_fake_ai 的
> teardown `clear()` 收走。所以 ③ 的預設假派工**全部是本 phase 新加**，不是「確認還在」。
> 有沒有接對，§4.9 的死埠實證會告訴你答案。

### 4.9 跑起來（綠）＋ 零外部依賴實證

- [ ] 跑新測試 → 全綠：

```bash
pytest tests/unit/test_ingest_job_store_unit.py tests/unit/test_celery_app_unit.py -q
```

- [ ] 跑全量：`pytest -q` → 預期 `基線 + 14 passed`（5 顆 celery 煙霧 ＋ 9 顆 RedisJobStore），**0 failed、0 error**。

- [ ] **零外部依賴實證（本 phase 最重要的一條）。** 把 broker 指到一個保證沒人在聽的埠再跑一次全量，顆數必須**一模一樣**：

```bash
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q
```

  埠 9 是 `discard` 保留埠，本機不會有人聽；與既有的 `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 完全同一套手法。
  **紅了代表**：有某條路徑真的去連 Redis 了，八成是 §4.8 三件事漏做一件。用錯誤訊息裡的檔名／行號回去找誰呼叫了 `get_job_store()` 或 `.delay()`。

- [ ] 既有那條也跑一次，確認沒回頭破壞什麼：`OLLAMA_BASE_URL=http://localhost:9 pytest -q` → 顆數相同。

- [ ] 端點數沒變（本 phase 一個端點都不加）：

```bash
pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
```

### 4.10 ⚠️ 一定要親手確認：worker 的 `backend=cloud` log

```text
┌─ ⚠️ 這一條直接決定 Phase 66 的 ★G2 第 5 條過不過 ──────────────────
│ design5 §12「階段乙」最後一條驗收是：
│   「頁首切雲端後上傳，worker log 的 backend=cloud（手動）」
│
│ 那行 log 是 app/services/ai_timing.py 印的，它決定 backend 的方式有兩種：
│   (a) 呼叫端有傳 target= → 用傳進來的那個
│   (b) 沒傳 → 自己去讀 config.AI_BACKEND
│
│ **在 worker 行程裡，(b) 永遠是 "local"**（那顆變數在 worker 裡沒人撥過）。
│ 所以 run_ingest_job 呼叫 ai_timing.log_ai("vlm", …) 時**一定要帶**
│ target=vlm_service.vlm_timing_target(vlm)——那支會讀 VLM 物件建構當下記下的
│ timing_target（OllamaCloudVLM.__init__ 裡是 AiTarget(backend="cloud", …)），
│ log 才寫得出 backend=cloud。
│
│ 沒帶的話：程式**功能完全正常**（雲端真的被呼叫、照片真的入庫），只有 log 騙人
│ ——而你在 Phase 66 會對著一行 backend=local 懷疑人生。
└──────────────────────────────────────────────────────────────────
```

- [ ] 用 grep 確認：

```bash
grep -n -A3 'log_ai("vlm"' app/services/ingest_job.py
```

  預期看得到 `target=vlm_service.vlm_timing_target(vlm)`（與 `app/api/routers/photos.py` 的 `_ingest_image` 逐字相同）。**沒有的話現在就補上**——這本來是 Phase 59 該做到的，在這裡補比在 Phase 66 猜快得多。

  兩件不用擔心的事：`kind=embed` 那一組**本來就永遠是** `backend=local`（`ai_timing._目標()` 對 embed 寫死本機，因為向量永遠本機）；加 `target=` 不會改變任何 422／500 語意，既有測試蓋著。

---

## 5. ASCII 圖：三個行程，誰握著什麼

```text
 ┌──────────────────────── web 行程（uvicorn） ─────────────────────────────────┐
 │  記憶體：config.AI_BACKEND = "local"/"cloud"  ← 頁首開關撥的就是它           │
 │          鏡頭 session token                                                  │
 │                                                                              │
 │  POST /photos                                                                │
 │   ① 格式不對 → 415（無 job、無 staging）                                     │
 │   ② save_staging(job_id, …)                    ──寫檔──► data/staging/…      │
 │   ③ store.create(…, ai_backend=config.AI_BACKEND ★快照★)  ──► Redis          │
 │   ④ dispatcher.dispatch(job_id)（CeleryDispatcher）                          │
 │      ＝ ingest_task.delay(job_id)                          ──► Redis         │
 │   ⑤ 202 {job_id, filename, content_type}                                     │
 │  GET /ingest-jobs → store.list_open()                      ──► Redis         │
 │  POST …/dismiss   → store.delete(job_id)                   ──► Redis         │
 └──────────────────────────────────────────────────────────────────────────────┘
          │ TCP redis://redis:6379/0                    ▲ TCP（讀進度給面板）
          ▼                                             │
 ┌──────────────────────── Redis ───────────────────────────────────────────────┐
 │  ★ 只放小小的字串，**絕不放影像位元組**（design5 §4.1 明文禁止）             │
 │  我們的 key： ingest:{job_id}  ＝ 一筆 job 的 JSON                           │
 │               ingest:open      ＝ 還沒結束的 job_id 集合（list_open 用）     │
 │  Celery 的 key：celery / _kombu.* / unacked*   ← 它自己管，我們不碰          │
 │  磁碟：AOF（appendonly yes，Phase 66 才設）→ 重開容器後進度列還在            │
 └──────────────────────────────────────────────────────────────────────────────┘
          │ Celery 從佇列取出任務                       ▲ TCP（改 status／attempt）
          ▼                                             │
 ┌──────────────────────── worker 行程（celery … --concurrency=2） ─────────────┐
 │  記憶體：config.AI_BACKEND = "local"  ← ★ 永遠是這個，沒人撥得到它 ★         │
 │                                                                              │
 │  ingest_task(job_id)   ← 薄薄一層（D15）                                     │
 │    store = get_job_store();  job = store.get(job_id)                         │
 │    vlm   = build_vlm_for_backend(job["ai_backend"])  ★用快照，不看開關★      │
 │    run_ingest_job(job_id, store=…, vlm=…, embeddings=…, now=…)               │
 │      ├─ read_staging(job_id)   ──讀檔──► data/staging/…                      │
 │      ├─ VLM 最多 3 次 ──HTTP──► Ollama（本機 or Cloud，看快照）              │
 │      ├─ embed ──HTTP──► 本機 bge-m3（★永遠本機，不歸開關管★）                │
 │      ├─ INSERT ──► Postgres（收件箱）＋ 原圖／縮圖寫 data/photos、thumbs     │
 │      ├─ 成功 → remove_staging ＋ store.delete(job_id)   ← 成功＝刪掉這筆     │
 │      └─ 3 次失敗 → remove_staging ＋ store.update(status="failed")           │
 └──────────────────────────────────────────────────────────────────────────────┘

 誰握著什麼（一句話版）
   AI 開關   ── web 行程的記憶體（worker 讀不到）
   快照      ── 寫在 job 裡（worker 唯一的依據）
   影像      ── 磁碟 data/staging（Redis 與 Celery 參數都只帶 job_id 字串）
   進度狀態  ── Redis（三方共用的唯一真相）
   照片正本  ── Postgres ＋ data/photos（Redis 掉了也不會少一張）

 本 phase 做完的長相：三個框的程式碼都寫好了，但 redis 與 worker 兩個容器還沒建
 → **實際跑起來仍然不會動**。那是 Phase 66。
```

---

## 6. 驗收清單

- [ ] 套件裝好：`grep -n "^celery\|^redis" requirements.txt`；`python -c "import celery, redis; print(celery.__version__, redis.__version__)"` 印得出版本
- [ ] `grep -n "CELERY_BROKER_URL" app/core/config.py` 看得到，預設值逐字是 `redis://redis:6379/0`
- [ ] `grep -n "class InMemoryJobStore\|class RedisJobStore\|OPEN_SET_KEY" app/services/ingest_job_store.py` 三個都在
- [ ] **`list_open()` 沒用 `KEYS` 也沒用 `SCAN`**（選型的硬證據）：

```bash
grep -rn "\.keys(\|\.scan(\|scan_iter" app/services/ingest_job_store.py
```

  預期：**沒有任何輸出**。

- [ ] `grep -n "personaldocai.ingest\|backend=None\|celery_app = Celery\|class CeleryDispatcher" app/celery_app.py` 四行都在
- [ ] **全系統只有一個地方碰 Celery**（日後要換掉只改一個檔的證據；
      `--include` 的引號不能省——zsh 會把沒引號的 `*.py` 當 glob 展開、直接報
      `no matches found`）：

```bash
grep -rn "import celery\|from celery\|from app.celery_app" app/ --include="*.py" | grep -v "^app/celery_app.py"
```

  預期：只有 `app/dependencies.py` 那一行 `from app.celery_app import CeleryDispatcher`
  （而且在 `get_task_dispatcher()` 函式**裡面**）。router／service 一律不該出現。

- [ ] **Phase 57 的過渡單例已刪乾淨**（§4.5 改動二之二）：

```bash
grep -rn "_memory_job_store" app/ tests/
```

  預期：**沒有任何輸出**。

- [ ] **worker 不讀 `config.AI_BACKEND`**（D14 的硬證據）：
      `grep -n "AI_BACKEND" app/celery_app.py` → **沒有任何輸出**
- [ ] `grep -n -A3 'log_ai("vlm"' app/services/ingest_job.py` 看得到 `target=vlm_service.vlm_timing_target(vlm)`（§4.10）
- [ ] `grep -n -A20 "def wire_memory_job_store" tests/conftest.py` 看得到 `monkeypatch.setattr` 與 `get_task_dispatcher`
- [ ] `pytest -q` ＝ 基線 ＋ 14，全綠
- [ ] **死埠實證**：`CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q` 與上一條**顆數完全相同、全綠**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] 端點仍 **22**、openapi 仍零 DELETE：

```bash
pytest tests/integration/test_ask_three_paths.py::test_端點數不變 \
       tests/integration/test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞 -q
```

- [ ] **`compose.yaml`／`compose.dev.yaml`／`LAUNCH.md`／`CLAUDE.md` 一個字都沒改**（那是 Phase 66）：

```bash
git status --short -- compose.yaml compose.dev.yaml LAUNCH.md CLAUDE.md
```

  預期：**沒有任何輸出**。

- [ ] `git status --short` 只多出／改到：`app/celery_app.py`（新）、`app/core/config.py`、`app/dependencies.py`、`app/main.py`、`app/services/ingest_job_store.py`、`requirements.txt`、`tests/conftest.py`、`tests/unit/test_celery_app_unit.py`（新）、`tests/unit/test_ingest_job_store_unit.py`，以及 `docs/` 底下的計畫檔

---

## 7. 常見陷阱

1. **循環匯入：`ImportError: cannot import name 'CeleryDispatcher' from partially initialized module`。**
   一 import `app.main` 就炸。原因是把 `from app.celery_app import CeleryDispatcher` 寫在
   `app/dependencies.py` 的**檔案最上面**，而 `app/celery_app.py` 又 import 了 `app.dependencies`，兩邊互咬。
   **修法：那一行一定要寫在 `get_task_dispatcher()` 函式裡面**（§4.5 改動三的程式碼就是這樣寫的）。

2. **`decode_responses=True` 忘了加 → `list_open()` 永遠回空清單，而且不報錯。**
   沒有它，`smembers()` 回 `bytes`，組出來的 key 變成 `"ingest:b'abc'"`，`mget` 全拿到 `None`，
   然後自我修復那段還會把它們 `SREM` 掉——進度面板永遠空的，log 一行錯誤都沒有。
   單元測試的 `FakeRedisClient` 值一律用 `str`，就是為了逼實作照這個前提寫。

3. **忘了改 `tests/conftest.py`（§4.8）→ pytest 卡住或一大片連線錯誤。**
   `dependency_overrides` 只管 `Depends()`，管不到 lifespan 與 Celery 任務裡的直接呼叫。
   症狀：`with TestClient(app)` 那一行卡好幾秒才炸，或出現 `Error 8 connecting to redis:6379`
   （找不到主機名 `redis`——那是**容器內部**才有的名字）。

4. **在 Celery 任務上加 `autoretry_for=(Exception,)` 或 `max_retries`。**
   design5 §4.4 明文禁止。後果：JPEG 已經 INSERT 成功、任務在寫檔那一步炸了，Celery 整份重跑
   → **同一張照片被插第二次**，待決定出現兩張一模一樣的卡。重試規則全在 `run_ingest_job` 裡。

5. **設了 result backend。** 看到 `backend=None` 覺得怪、順手填一個——不要。填了之後每顆任務都會在
   Redis 多寫一筆結果墓碑（預設留 24 小時），我們一筆都不會讀，還會讓除錯時眼花。

6. **在 worker 裡呼叫 `dependencies.get_vlm()`。** 本 phase 最陰的坑，因為它**不會報錯**：
   使用者切了雲端、上傳、202、進度列正常走、照片最後也真的進待決定——只是全程用本機 gemma4，
   一張圖 64〜88 秒。要到 Phase 66 對著 worker log 才發現 `backend=local`。
   守門的是 §4.3-1 的 `test_快照贏過開關`。

7. **以為 `celery_app.py` 寫好就會自己跑起來。** 不會。worker 是一個**要有人去啟動的行程**。
   本 phase 結束時你在瀏覽器上傳，照片仍然會永遠停在「排隊中」——**這是預期的**，Phase 66 才建 worker 容器。

8. **`-A` 少寫最後一段（寫成 `-A app.celery_app`）。** 通常**不會**立刻爆——官方的搜尋順序
   （屬性 `app` → 屬性 `celery` → 「模組裡任何值是 Celery 實例的屬性」）第三步會撈到
   `celery_app`，worker 照樣起得來。危險在「靠搜尋」：哪天這個檔多出第二個 Celery 物件
   （或變數改名）就挑錯；搜尋全部落空時的錯誤訊息
   `Unable to load celery application. Module 'app.celery_app' has no attribute 'app'`
   又很容易被誤讀成「檔案不見了」。契約 §3.5 釘死全寫版 `-A app.celery_app.celery_app`
   ＝不靠搜尋、不吃這兩種虧。
   來源：<https://docs.celeryq.dev/en/stable/getting-started/next-steps.html>

9. **想在 `RedisJobStore.update()` 裡加鎖。** 不要。§4.4 的 docstring 已寫清楚為什麼碰不到競態。
   加 `WATCH`／`MULTI` 會讓這個檔行數翻倍還要處理重試——side project 的複雜度預算不花在這裡。

10. **只跑 `pytest -q` 就宣告完工。** 最關鍵的驗收是 `CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q`。
    平常那一次可能剛好因為 Redis 容器沒開、連線被**立刻拒絕**而看起來沒事；但在真的有 Redis 的環境下，
    同一段程式會安靜地把測試資料寫進去。死埠那條才是硬證據。

11. **把 `redis` 套件跟「Redis 伺服器」搞混。** `pip install redis` 裝的是**客戶端函式庫**（話筒），
    不是 Redis 本身。伺服器是 Phase 66 用 Docker 映像跑起來的。所以本 phase 裝完之後
    `redis-cli` 在 Mac 上仍然不存在，那是正常的。

12. **順手把 `compose.yaml` 一起改了。** 驗收清單有一條就是它必須沒被動過。
    兩件事分兩個 phase 是刻意的：程式碼壞了跟容器設定壞了，症狀長得完全不一樣，混在一起改會分不出來。

---

## 附：本文件引用的官方文件

| 主題 | 連結 |
|---|---|
| Celery 第一支任務（`Celery(...)` 建構、`-A` 用法、worker 啟動指令） | <https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html> |
| Celery `--app` 的正式格式（「in the form of `module.path:attribute`」）與只給模組名時的搜尋順序（屬性 `app` → 屬性 `celery` → 「any attribute in the module proj where the value is a Celery application」）——**這段在 Next Steps 頁，CLI reference 沒有** | <https://docs.celeryq.dev/en/stable/getting-started/next-steps.html> |
| Celery 用 Redis 當 broker（URL 格式 `redis://:password@hostname:port/db_number`、各段皆可省略「will default to localhost on port 6379, using database 0」、`celery[redis]` bundle） | <https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html> |
| Celery 指令列參考（選項清單；`-c/--concurrency`「The default is the number of CPUs available on your system.」；`-l/--loglevel`。⚠ `-A` 這頁只列名字、不講格式，格式見上面 Next Steps 那列） | <https://docs.celeryq.dev/en/stable/reference/cli.html> |
| Celery 設定表（`result_backend` 預設「沒有」、`broker_connection_retry_on_startup`、`worker_concurrency`） | <https://docs.celeryq.dev/en/stable/userguide/configuration.html> |
| Celery 訊號（`worker_ready`：Dispatched when the worker is ready to accept work） | <https://docs.celeryq.dev/en/stable/userguide/signals.html> |
| Celery 呼叫任務（`.delay(*args, **kwargs) calls .apply_async(args, kwargs)`） | <https://docs.celeryq.dev/en/stable/userguide/calling.html> |
| Redis `KEYS` 命令（「Don't use KEYS in your regular application code… consider using SCAN or sets」） | <https://redis.io/docs/latest/commands/keys/> |
| redis-py 連線（`Redis.from_url(url, **kwargs)`、URL 長相） | <https://redis.readthedocs.io/en/stable/connections.html> |
| PyPI `celery`（2026-08-25 最新 5.6.3，requires-python `>=3.9`） | <https://pypi.org/project/celery/> |
| PyPI `redis`（2026-08-25 最新 8.1.0，requires-python `>=3.10`） | <https://pypi.org/project/redis/> |

（`~/CLAUDE.md` 的 MCP 規則要求「查最新官方文件優先用 Context7」。撰寫與 2026-08-25 review 覆核時
工作階段都沒有掛載 Context7，依同一條規則的後備做法改用官方站台直查；上表每一條都是實際讀過的頁面。
覆核時更正了一處：`-A` 的 `module.path:attribute` 格式與搜尋順序寫在 **Next Steps** 頁，
CLI reference 只列選項名、不講格式——引用來源已跟著改。）
