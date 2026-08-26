# Phase 57：JobStore 與測試安全網

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候（順便裝 Redis、順便寫 Celery、順便加一個 `list_all()`、順便做過期清理……），答案一律是「不要」。

> 🎯 **一句話目標：** 做出「一筆入庫任務現在跑到哪了」的存放處——先訂一份契約（`JobStore`），再寫**記憶體版**的實作給測試用，並在 `tests/conftest.py` 加上**第四道 autouse 安全網**，保證每個測試都拿到一個乾淨的、絕不連真 Redis 的 store。

**為什麼要做這個：**

增量五要把上傳改成非同步。使用者按下「上傳」之後，HTTP 立刻回 **202**「我收下了」，真正看圖的工作交給背景的 worker 慢慢做（本機 gemma4 看一張圖要 64〜88 秒）。

那問題就來了：**使用者怎麼知道跑到哪了？**

- 剛收下、還沒輪到 → 要顯示「排隊中」
- worker 正在看圖 → 要顯示「分析中（第 1 次）」
- 看不懂、正在重試 → 要顯示「重試中（第 2 次）」
- 三次都失敗 → 要顯示一列紅字，讓人按 × 關掉
- **成功 → 那一列要自己消失**，然後頂欄的「待決定（N）」+1

這些狀態不能放在 `photo` 表（design5 §11 明文禁止：`photo` 只加建議欄，不加處理狀態、不加 job_id）。理由很單純：**分析失敗的檔案根本沒有 `photo` 列**（design5 D10「3 次都失敗＝整筆拿掉」），沒有列就沒地方掛狀態。

所以要另外開一個地方存這些狀態，本專案叫它 **JobStore**。

正式環境的 JobStore 會存在 Redis 裡（**Phase 65** 才做），因為 app 與 worker 是兩個不同的行程，要靠一個共同的地方交換狀態。但 **pytest 絕對不能連真 Redis**（design5 D15、§9），所以本 phase 先做一個「行程內的 dict」版本，測試用它、Phase 65 之前的開發也用它。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| job（任務） | 「一個檔案的入庫工作」。使用者選了 3 個檔就是 3 個 job；一份 10 頁的 PDF 仍然只是 **1 個** job（design5 D11：一檔一任務） |
| JobStore | 「放這些 job 現在跑到哪」的地方。它不放檔案內容，只放狀態（檔名、第幾次、錯誤訊息……） |
| Redis | 一種把資料放在記憶體裡的資料庫，常拿來當「任務排隊的地方」與「跨行程共用的小抄本」。**本 phase 完全不碰它**，Phase 65 才做 |
| broker（中間人） | 任務排隊的地方。app 把任務丟進去、worker 從裡面拿出來。本專案用 Redis 當 broker（Phase 65） |
| worker | 背景做事的行程。它不接 HTTP，只負責從 broker 拿任務、看圖、寫資料庫 |
| 行程（process） | 作業系統眼中「正在跑的一支程式」。app（uvicorn）與 worker（celery）是**兩個不同的行程**，它們的記憶體彼此看不到——這就是為什麼正式環境需要 Redis |
| `Protocol`（協定 / 結構型別） | Python 的一種「只寫規格、不寫實作」的寫法。它說「只要你有這五個方法，你就算是一個 JobStore」，**不需要繼承任何東西**。下面 §4 步驟 2 有完整說明 |
| 結構型別 / 鴨子型別（duck typing） | 「走起來像鴨子、叫起來像鴨子，那它就是鴨子」。判斷一個東西算不算某種型別，看的是**它有哪些方法**，不是它的血統 |
| `TypedDict` | Python 的一種型別註記：「這是一個字典，而且它的鍵長這樣」。它**不是**新的類別，執行時就是一個普通的 `dict`，只是編輯器與人看得懂它該有哪些鍵 |
| `total=False` | `TypedDict` 的選項：「這些鍵不一定每個都要有」。我們用它，因為 `update()` 只會帶進來一部分的鍵 |
| 依賴注入（dependency injection） | 「不要自己去 new 一個物件，而是讓外面把它遞給你」。本專案在 `app/dependencies.py` 集中管理，測試就能用 `app.dependency_overrides` 換成假件 |
| autouse fixture | pytest 的「每個測試都自動套用的前置／後置動作」，不必在測試函式的參數列寫它的名字 |
| 單例（singleton） | 「整個行程只建立一份、大家共用」。`@lru_cache(maxsize=1)` 就是本專案用來做這件事的寫法 |
| 淺複製（shallow copy） | `dict(x)` 會複製一份新的字典，但**裡面的清單仍然是同一個**。所以複製 job 時，`photo_ids` 那個 list 要另外再複製一次 |

---

## 1. 對應 design5.md 章節

- **D5「Redis ＋ Celery」**：佇列用 Redis、worker 用 Celery。（本 phase 只做「狀態存放處」這一半，而且只做記憶體版。）
- **D9「成功列消失」**：分析成功 → 該列從面板拿掉，頂欄「待決定（N）」+1。失敗列留下，可按 × 關掉。
- **D15「測試不碰真 Redis」**：pytest 繼續在 host 跑、繼續 `wire_fake_ai`、繼續不打真 Ollama。**Job 狀態用可替換的 store（測試用記憶體，正式用 Redis）**。
- **D14「AI 開關快照」**：`IngestJob` 的 `ai_backend` 欄就是那張快照的**存放處**——入列當下由 Phase 62／63 寫入、worker 由 Phase 65 讀出建對的 VLM 客戶端。本 phase 只定義欄位與測試（`test_create把五個參數原樣記著` 就在驗它）。（2026-08-25 核對時補列：總覽 §2 表明列 D14 歸本 phase 落地一部分，原 §1 清單漏了。）
- **§4.3「JobStore（進度面板的來源）」**：正式實作 Redis hash／JSON，key 例如 `ingest:{job_id}`；測試實作行程內 dict，autouse fixture 每測清空。清單 API 只回 `queued`／`analyzing`／`retrying`／`failed`。**成功＝刪掉這筆 job**，前端不必自己過濾 success。每筆至少有的 11 個欄位（那張表就是本 phase 的 `IngestJob`）。
- **§4.4「崩潰重送（避免兩張照片）」**：冪等靠 JobStore 的 `photo_ids` 與 `pages_done`。
- **§9「測試策略」**：沿用三道 autouse 安全網，**再加第四道：JobStore 指到記憶體**。
- **§11「會動到的檔」**：`app/services/ingest_job_store.py`（Redis／記憶體兩實作）、`tests/conftest.py`（記憶體 JobStore）。
- 契約備忘 **§3.1**（`JOB_STATUSES`／`IngestJob`／`JobStore`／`InMemoryJobStore`／`get_job_store()` 的逐字簽章）、**§2.1**／**§2.3**（檔名）、**§7 全域鐵律第 2 條**（第四道安全網名字叫 `wire_memory_job_store`——這一條指的是**總覽** §7，總覽存在）。
  （⚠ 2026-08-25 核對：「契約備忘」是規劃階段的工作文件、未入庫。本 phase 需要的簽章已全部
  逐字內嵌在 §4 步驟 2〜4，驗收一律以本檔內嵌內容為準，不依賴那份文件。）

---

## 2. 前置條件

**依賴的 phase：無。** 本 phase 是增量五的地基之一，可以跟 Phase 52〜56 平行做。

開工前**實查**基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 資料庫容器活著嗎？db 那一列要是 Up (healthy)
docker compose ps

# ② 測試基線（2026-08-25 實測為 405 passed ＋ 0 skipped）
pytest -q
```

若你是在 Phase 56 之後才做這一支，基線會是 410。**以你當下實查到的數字為準**，本文件之後一律稱它「基線」。

**⚠️ 絕對不要同時跑兩份 pytest。**（理由見 Phase 56 §2。）

---

## 3. 範圍

### 做

1. 新建 `app/services/ingest_job_store.py`：
   - `JOB_STATUSES` 常數（四種狀態，**沒有 success**）
   - `IngestJob`（`TypedDict`，11 個欄位）
   - `JobStore`（`Protocol`，五個方法）
   - `InMemoryJobStore`（行程內 dict 實作）
2. `app/dependencies.py` 加注入點 `get_job_store()`。
3. `tests/conftest.py` 加**第四道 autouse 安全網** `wire_memory_job_store`——
   **`dependency_overrides` ＋ `monkeypatch` 兩管齊下**（前者攔 `Depends()`、後者攔「直接呼叫」；
   為什麼缺一不可，見步驟 4 與常見陷阱 7）。
4. 新建 `tests/unit/test_ingest_job_store_unit.py`（12 顆）。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 寫 `RedisJobStore` | 那是 **Phase 65**。本 phase 做完之後 Redis 根本還沒進 compose，寫了也跑不起來、也沒辦法測 |
| 把 `redis` 或 `celery` 加進 `requirements.txt` | 那也是 **Phase 65** 的事。現在加只會讓 host 的 `.venv` 與容器映像多裝兩個用不到的套件，還會讓「重建映像要手動煙霧一次」的成本提早發生 |
| 寫 `run_ingest_job()`（真正的入庫任務） | 那是 **Phase 59／60**。本 phase 只做「狀態放哪裡」，不做「誰去改這些狀態」 |
| 開 `GET /ingest-jobs` 端點 | 那是 **Phase 64**。本 phase 端點數維持 **20** |
| 改 `POST /photos` | 那是 **Phase 62**。本 phase 對外行為零改變 |
| 在 store 裡放檔案內容（影像位元組） | design5 §4.1 明文禁止：多頁 PDF 太大。檔案走磁碟的 staging（Phase 58） |
| 加 `"success"` 狀態 | design5 §4.3：**成功＝刪掉這筆 job**。多一個狀態就多一個前端要過濾的東西，也多一種「忘了過濾」的壞法 |
| 加 `list_all()`／分頁／排序參數 | 進度面板一次最多顯示幾筆進行中的工作，`list_open()` 全回就夠了。不做用不到的彈性 |
| 幫 job 加「自動過期」機制 | 進行中的任務不該被自動清掉；失敗的由人按 × 關掉（D9）。孤兒 staging 檔另有 24 小時掃把（Phase 58） |
| 讓 `InMemoryJobStore` 執行緒安全（加鎖） | uvicorn 單行程、pytest 單執行緒，用不到。真正跨行程共用是 Redis 的責任（Phase 65） |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1 先把測試寫好、跑到**紅**；步驟 2〜4 才動實作讓它轉綠。

### 步驟 1：先寫測試（紅）

- [ ] 新建 `/Users/linjunting/personalDocAI/tests/unit/test_ingest_job_store_unit.py`，整份貼上：

```python
"""InMemoryJobStore 的單元測試：純記憶體，不碰資料庫、不碰網路、不碰 Redis。

design5.md §4.3：清單只回 queued／analyzing／retrying／failed 四種狀態，
**成功＝把這筆 job 刪掉**，所以 store 裡根本不存在「成功」這種狀態。
"""

from __future__ import annotations

from app import dependencies
from app.dependencies import get_job_store
from app.main import app
from app.services.ingest_job_store import JOB_STATUSES, InMemoryJobStore


def _new_store() -> InMemoryJobStore:
    """每顆測試自己開一個乾淨的 store（單元測試不透過依賴注入）。"""
    return InMemoryJobStore()


def _create(store: InMemoryJobStore, job_id: str = "job-1", **overrides):
    """建立一筆標準的 job（可用 overrides 覆寫任一參數）。"""
    params = dict(
        job_id=job_id,
        filename="receipt.jpg",
        content_type="image/jpeg",
        ai_backend="local",
        source="upload",
    )
    params.update(overrides)
    return store.create(**params)


def test_四種狀態的清單裡沒有success():
    """成功不是一種狀態，成功是「這筆 job 從此不存在」（design5 §4.3、D9）。

    如果哪天有人偷偷加了 "success"，進度面板就會多出一列永遠不會消失的成功列，
    而 design5 §1.2 明文否決過「成功列留在進度面板當第二個待決定」。
    """
    assert JOB_STATUSES == ("queued", "analyzing", "retrying", "failed")


def test_create之後是queued而且計數全部歸零():
    store = _new_store()

    job = _create(store)

    assert job["status"] == "queued"
    assert job["attempt"] == 0          # 還沒送過 VLM
    assert job["pages_done"] == 0
    assert job["photo_ids"] == []       # 還沒有任何照片入庫
    assert job["page_count"] is None    # PDF 拆頁後才知道幾頁；圖片永遠是 None
    assert job["error"] is None


def test_create把五個參數原樣記著():
    """ai_backend 是入列當下 AI 開關的快照（D14）；source 分得出上傳與鏡頭。"""
    store = _new_store()

    job = _create(
        store,
        job_id="job-abc",
        filename="報告.pdf",
        content_type="application/pdf",
        ai_backend="cloud",
        source="camera",
    )

    assert job["job_id"] == "job-abc"
    assert job["filename"] == "報告.pdf"
    assert job["content_type"] == "application/pdf"
    assert job["ai_backend"] == "cloud"
    assert job["source"] == "camera"


def test_get拿得回剛建立的那一筆():
    store = _new_store()
    _create(store, "job-1")

    assert store.get("job-1")["filename"] == "receipt.jpg"


def test_get不存在的job回None():
    """不是丟例外——「查無這筆」是正常情況，Phase 64 的端點靠它回 404。"""
    assert _new_store().get("根本沒有這個 id") is None


def test_update只改指定的欄位其餘不動():
    store = _new_store()
    _create(store, "job-1")

    更新後 = store.update("job-1", status="analyzing", attempt=1)

    assert 更新後["status"] == "analyzing"
    assert 更新後["attempt"] == 1
    # 沒有傳進來的欄位要原封不動
    assert 更新後["filename"] == "receipt.jpg"
    assert 更新後["photo_ids"] == []
    # 而且真的寫回 store，不是只改了回傳的那份複本
    assert store.get("job-1")["status"] == "analyzing"


def test_update不存在的job回None():
    """worker 可能在人把 job 關掉之後才寫狀態；那時安靜地什麼都不做，不要爆錯。"""
    assert _new_store().update("根本沒有這個 id", status="failed") is None


def test_delete之後get回None():
    """成功入庫時 worker 就是這樣做的：store.delete(job_id)（design5 §4.3）。"""
    store = _new_store()
    _create(store, "job-1")

    store.delete("job-1")

    assert store.get("job-1") is None
    # 刪不存在的也不可以爆錯（dismiss 與 worker 可能同時發生）
    store.delete("job-1")


def test_list_open不含已經delete的():
    """前端因此不必自己過濾 success——成功的那筆根本不在清單裡。"""
    store = _new_store()
    _create(store, "還在跑")
    _create(store, "已完成")

    store.delete("已完成")

    assert [job["job_id"] for job in store.list_open()] == ["還在跑"]


def test_list_open四種狀態都回得出來():
    """queued／analyzing／retrying／failed 一個都不能漏——失敗列要留著讓人按 ×。"""
    store = _new_store()
    for index, status in enumerate(JOB_STATUSES):
        _create(store, f"job-{index}")
        store.update(f"job-{index}", status=status)

    回來的 = store.list_open()

    assert [job["status"] for job in 回來的] == list(JOB_STATUSES)
    # 建立順序即顯示順序（dict 保留插入順序），進度面板的列才不會每次輪詢就跳來跳去
    assert [job["job_id"] for job in 回來的] == ["job-0", "job-1", "job-2", "job-3"]


def test_拿到的是複本改它不會動到store裡的資料():
    """Redis 版每次回的一定是新解析出來的字典；記憶體版要裝得一模一樣。

    不這樣做的話，測試在記憶體版上會綠、換成 Redis 就紅——最難查的一種壞法。
    photo_ids 是清單，dict() 只做淺複製，所以要另外再複製一次（見實作的 _copy）。
    """
    store = _new_store()
    _create(store, "job-1")

    到手的 = store.get("job-1")
    到手的["status"] = "我亂改的"
    到手的["photo_ids"].append(999)

    assert store.get("job-1")["status"] == "queued"
    assert store.get("job-1")["photo_ids"] == []


def test_安全網已把注入點換成每測獨立的記憶體store():
    """第四道 autouse 安全網本身也要有測試（比照 isolated_data_dir 的做法）。

    ★ 這一顆**刻意不把 fixture 寫進參數列**：pytest 對「參數列有請求的 fixture」
      無論 autouse 與否都會啟動它，寫了參數列就驗不到 autouse 本身——
      就算有人把 autouse=True 拿掉，這顆照樣綠，形同沒驗。
      不寫參數列、下面的斷言卻全部成立，才證明安全網是「自動」套上的。

    兩條呼叫路都要驗（缺一條就是「單跑綠、整包跑紅」的溫床）：
      ① router 參數列上的 Depends(get_job_store)——FastAPI 查 app.dependency_overrides，
        查表的 key 是「原本那個函式物件」。
      ② 直接呼叫 dependencies.get_job_store()——Phase 65 的 app 啟動掃把（lifespan）
        與 Celery 任務走的就是這條，dependency_overrides 攔不到，靠 monkeypatch。
    """
    # ① Depends() 那條路的覆寫在
    assert get_job_store in app.dependency_overrides
    # ② 直接呼叫那條路已被 monkeypatch 換掉（換掉後不再是原本那個函式）
    assert dependencies.get_job_store is not get_job_store
    # 兩條路拿到的必須是**同一顆** store——不然掃把與端點會各記各的
    store = dependencies.get_job_store()
    assert app.dependency_overrides[get_job_store]() is store
    # 而且每個測試開始時都是全新的空 store，看不到別的測試留下的 job
    assert store.list_open() == []
```

- [ ] 跑一次，看它紅：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_ingest_job_store_unit.py -q
```

預期：**collection error**（收集測試時 import 就倒了，一顆都跑不起來），訊息是

```
ImportError: cannot import name 'get_job_store' from 'app.dependencies' (/Users/linjunting/personalDocAI/app/dependencies.py)
```

**這就是紅燈，正確。** 為什麼是這一句：檔案的 import 由上往下執行，第一個倒的是
`from app.dependencies import get_job_store`（注入點還沒加，步驟 3 才做）；
它擋在前面，所以還輪不到 `app.services.ingest_job_store` 喊「找不到模組」。
（做完步驟 3、還沒做步驟 2 的話，紅字才會換成
`ImportError: cannot import name 'ingest_job_store' from 'app.services'`——2026-08-25 已用
Python 3.12 實測過這兩句的長相，不是 `ModuleNotFoundError`。）

---

### 步驟 2：實作（綠·上）——新建 `app/services/ingest_job_store.py`

- [ ] 新建 `/Users/linjunting/personalDocAI/app/services/ingest_job_store.py`，整份貼上：

```python
"""入庫任務（ingest job）的狀態存放處：一份契約 ＋ 記憶體實作。

【這個模組解決什麼問題】
增量五把上傳改成非同步：HTTP 立刻回 202「收下了」，看圖交給背景 worker。
那「現在跑到哪了」要放在哪裡？不能放 photo 表——分析失敗的檔案根本沒有 photo 列
（design5.md D10：3 次都失敗＝整筆拿掉），沒有列就沒地方掛狀態。
所以另開一個地方，本專案叫它 JobStore（design5.md §4.3）。

【為什麼有「契約」與「實作」兩層】
正式環境的 app 與 worker 是**兩個不同的行程**，記憶體彼此看不到，
所以正式的 JobStore 必須放在 Redis 裡（RedisJobStore，Phase 65 才做）。
但 pytest 絕對不能連真 Redis（design5.md D15、§9），所以另外有一個
「行程內 dict」的版本給測試用（InMemoryJobStore，就在下面）。
兩個實作長得一模一樣（都有那五個方法），呼叫端因此完全不必知道自己拿到的是哪一個。

【成功＝刪掉這筆 job】
JOB_STATUSES 裡**沒有 "success"**。worker 成功入庫時做的事是 store.delete(job_id)。
所以進度面板拉回來的清單天生就不含成功的工作，前端不必自己過濾
（design5.md §4.3、D9；§1.2 明文否決過「成功列留在面板當第二個待決定」）。

分層：本模組只管狀態的存取，不看圖、不寫資料庫、不碰 HTTP、不碰檔案。
      誰在什麼時候改這些狀態，是 app/services/ingest_job.py 的事（Phase 59／60）。
"""

from __future__ import annotations

from typing import Protocol, TypedDict

# 一筆任務可能出現的四種狀態。**刻意沒有 "success"**，理由見模組 docstring。
#   queued    ＝已收下、還沒輪到（HTTP 剛回 202 的那一刻）
#   analyzing ＝worker 正在送這張／這頁去 VLM
#   retrying  ＝上一次失敗了，正在送第 2 或第 3 次（design5.md D10：含第一次共 3 次）
#   failed    ＝3 次都失敗，整筆放棄。staging 已刪、photo 表沒有這一列，
#               這一列會留在進度面板上等人按 ×（POST /ingest-jobs/{id}/dismiss）
JOB_STATUSES = ("queued", "analyzing", "retrying", "failed")


class IngestJob(TypedDict, total=False):
    """一筆任務的完整長相（design5.md §4.3 的欄位表）。

    TypedDict ＝「這是一個字典，而且它的鍵長這樣」。它不是新的類別，
    執行時就是普通的 dict——所以可以直接丟給 Pydantic 模型、直接 json 序列化，
    Redis 版也可以直接 json.dumps 存進去。編輯器與人則看得懂它該有哪些鍵。

    total=False ＝「這些鍵不一定每個都要有」。update() 只會帶一部分的鍵進來，
    寫成 total=True 的話那裡就會被型別檢查抱怨。
    """

    job_id: str
    filename: str
    content_type: str
    status: str          # JOB_STATUSES 之一
    attempt: int         # 這張／這頁目前第幾次 VLM，1〜3（剛建立時是 0 ＝還沒送過）
    page_count: int | None   # PDF 拆頁後才知道幾頁；圖片永遠是 None
    pages_done: int      # PDF 已處理頁數（含跳過的失敗頁）；崩潰重送靠它續跑
    photo_ids: list[int]     # 已經 INSERT 的照片 id；崩潰重送靠它避免插兩次
    error: str | None    # 失敗時給人看的**短句**，不要把 stack trace 丟給瀏覽器
    ai_backend: str      # 入列當下 config.AI_BACKEND 的快照："local" / "cloud"（D14）
    source: str          # "upload"（電腦選檔）/ "camera"（無線鏡頭快門）


class JobStore(Protocol):
    """JobStore 的**契約**：只寫「要有哪些方法」，不寫怎麼做。

    Protocol ＝ Python 的「結構型別」（也叫鴨子型別）：
    走起來像鴨子、叫起來像鴨子，那它就是鴨子。
    只要一個物件有下面這五個方法，它**就算是**一個 JobStore，
    **完全不必繼承這個類別**。

    為什麼用 Protocol 而不是「讓兩個實作去繼承一個基底類別」：
      1. 不必為了「被當成 JobStore」而多寫一行 `class RedisJobStore(JobStore)`；
         少一條繼承關係，就少一種「改了基底類別把兩個實作一起弄壞」的可能。
      2. 測試裡臨時捏一個「只有這五個方法的小假件」也能直接用，不必先去繼承什麼。
      3. 本專案已經用同一招處理 VLMClient／RouterClient／AnswerClient
         （VLMClient 在 app/services/vlm_service.py；Router／Answer 兩個在
         app/services/ask_workflow.py），寫法一致，讀的人不必再學一種。

    ⚠ Protocol 只是給編輯器與人看的規格，執行時**不會**幫你檢查。
      少寫一個方法不會在 import 時爆錯，會在真的呼叫到的時候才 AttributeError。
      所以下面的 InMemoryJobStore 五個方法一個都不能少。
    """

    def create(self, *, job_id: str, filename: str, content_type: str,
               ai_backend: str, source: str) -> IngestJob: ...

    def get(self, job_id: str) -> IngestJob | None: ...

    def update(self, job_id: str, **fields) -> IngestJob | None: ...

    def delete(self, job_id: str) -> None: ...

    def list_open(self) -> list[IngestJob]: ...   # 不含成功（成功＝已 delete）


def _copy(job: IngestJob) -> IngestJob:
    """回一份獨立的複本，讓呼叫端改它也不會動到 store 裡面的資料。

    為什麼一定要複製：Redis 版每次都是「從 Redis 讀字串 → 解析成新字典」，
    天生就是複本。記憶體版如果直接把內部那份交出去，
    測試在記憶體版上會綠、換成 Redis 就紅——最難查的一種壞法。

    dict(job) 是**淺複製**：新字典是新的，但 photo_ids 指向的仍然是同一個清單。
    所以那一個清單要另外再複製一次，否則
    `store.get(id)["photo_ids"].append(7)` 會偷偷改到 store 裡的資料。
    """
    clone = dict(job)
    clone["photo_ids"] = list(job.get("photo_ids") or [])
    return clone  # type: ignore[return-value]


class InMemoryJobStore:
    """行程內的 dict 實作。給 pytest 用，也給 Phase 65 之前的開發用。

    ⚠ 它的資料只活在**這一個行程的記憶體**裡：
      - uvicorn 重啟 ＝清空
      - app 與 worker 是兩個行程 ＝彼此看不到對方的 job
    所以它不是正式方案，正式方案是 Phase 65 的 RedisJobStore。

    沒有加鎖（threading.Lock）：uvicorn 單行程、pytest 單執行緒，用不到。
    真正的跨行程共用是 Redis 的責任，不要在這裡自己造一套。
    """

    def __init__(self) -> None:
        # dict 保留插入順序（Python 3.7+ 的保證），所以 list_open() 回來的先後
        # 就是「先收下的排前面」——進度面板的列才不會每次輪詢就跳來跳去
        self._jobs: dict[str, IngestJob] = {}

    def create(
        self,
        *,
        job_id: str,
        filename: str,
        content_type: str,
        ai_backend: str,
        source: str,
    ) -> IngestJob:
        """收下一個新檔案時建立一筆。四個計數欄一律從「什麼都還沒發生」開始。"""
        job: IngestJob = {
            "job_id": job_id,
            "filename": filename,
            "content_type": content_type,
            "status": "queued",
            "attempt": 0,          # 0 ＝還沒送過 VLM；第一次送出時才變 1
            "page_count": None,    # PDF 拆頁後才填，圖片永遠是 None
            "pages_done": 0,
            "photo_ids": [],
            "error": None,
            "ai_backend": ai_backend,
            "source": source,
        }
        self._jobs[job_id] = job
        return _copy(job)

    def get(self, job_id: str) -> IngestJob | None:
        """查一筆；查無回 None（不是丟例外——「查無」是正常情況）。"""
        job = self._jobs.get(job_id)
        return _copy(job) if job is not None else None

    def update(self, job_id: str, **fields) -> IngestJob | None:
        """改一筆的部分欄位，回傳改完之後的整筆；job 已經不在了就回 None。

        為什麼「不在了」要安靜回 None 而不是爆錯：worker 有可能在人已經把
        這筆關掉（dismiss）之後才寫狀態，那時什麼都不做才是對的。
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.update(fields)
        return _copy(job)

    def delete(self, job_id: str) -> None:
        """刪掉一筆。**成功入庫走的就是這一支**（design5.md §4.3）。

        人按進度面板的 × 關掉失敗列，走的也是這一支（Phase 64 的 dismiss）。
        刪不存在的不可以爆錯——兩邊有可能同時發生。
        """
        self._jobs.pop(job_id, None)

    def list_open(self) -> list[IngestJob]:
        """全部「還沒結束」的任務，先收下的排前面。

        成功的那些早就被 delete 掉了，所以這裡天生就不含成功——
        前端不必自己過濾（design5.md §4.3）。
        另外用 JOB_STATUSES 再濾一次是防禦性的：萬一日後有人手滑寫進一個
        沒定義過的狀態，它不會莫名其妙出現在使用者的進度面板上。
        """
        return [
            _copy(job)
            for job in self._jobs.values()
            if job.get("status") in JOB_STATUSES
        ]

    # ---------- 以下是**測試專用**，不屬於 JobStore 契約 ----------

    def clear(self) -> None:
        """清空全部 job。只給 tests/conftest.py 的安全網用。

        Protocol 是結構型別，多幾個方法完全沒關係（RedisJobStore 不會有這一支）。
        刻意不放進 JobStore 契約：正式程式碼沒有任何地方該有「一次清光」的能力。
        """
        self._jobs.clear()
```

---

### 步驟 3：實作（綠·中）——`app/dependencies.py` 加注入點

- [ ] 打開 `/Users/linjunting/personalDocAI/app/dependencies.py`，把上方的 import（約第 24〜29 行）：

```python
from app.services import (
    ask_workflow,
    entity_suggestion_service,
    indexing_service,
    vlm_service,
)
```

**換成**（多一行 `ingest_job_store`，維持字母順序）：

```python
from app.services import (
    ask_workflow,
    entity_suggestion_service,
    indexing_service,
    ingest_job_store,
    vlm_service,
)
```

- [ ] 在檔案**最後面**（`get_today` 之後）接上：

```python


# ---------- 入庫任務的狀態存放處（Phase 57；design5.md §4.3）----------


@lru_cache(maxsize=1)
def _memory_job_store() -> ingest_job_store.InMemoryJobStore:
    """整個行程共用同一個記憶體 store。

    @lru_cache(maxsize=1) 就是本專案的「只建立一次」寫法（與 _ollama_vlm 同一招）。
    不共用的話，每個 HTTP 請求都會拿到一個全新的空 store，
    上一個請求建的 job 下一個請求就查不到了。
    """
    return ingest_job_store.InMemoryJobStore()


def get_job_store() -> ingest_job_store.JobStore:
    """任務狀態存放處的唯一取用入口。

    現在一律回記憶體實作。**Phase 65** 會改成「有設定 CELERY_BROKER_URL 就回
    RedisJobStore」——正式環境的 app 與 worker 是兩個行程，記憶體版彼此看不到。

    ⚠ 它有兩種呼叫端，pytest 攔截的方法**不一樣**（Phase 65 起兩種都會出現）：
      1. router 參數列上的 Depends(get_job_store)——測試用
         app.dependency_overrides[get_job_store] 換（只有 FastAPI 解析 Depends 時才查表）。
      2. 把它當**普通函式直接呼叫**——Phase 65 的 app 啟動掃把（main.py 的 lifespan）
         與 Celery 的 ingest_task（它們不是 HTTP 請求，沒有 Depends 可攔）。
         這種呼叫 dependency_overrides 根本看不到，測試靠 conftest 的
         monkeypatch.setattr 換掉本函式（wire_memory_job_store 安全網的第二管）。
         ★ 因此直接呼叫端一律要寫「from app import dependencies」＋
           「dependencies.get_job_store()」——呼叫當下才解析模組屬性，monkeypatch
           換得掉；寫成「from app.dependencies import get_job_store」再呼叫是早綁定，
           換不掉（見 tests/conftest.py 的說明與本 phase 常見陷阱 7）。
      拿到 store 之後怎麼用：run_ingest_job() 仍是**明寫參數**收它
      （Phase 59 的簽章約定——store 是參數，不是任務本體裡的隱形全域）。
    """
    return _memory_job_store()
```

---

### 步驟 4：實作（綠·下）——`tests/conftest.py` 加第四道安全網

- [ ] 打開 `/Users/linjunting/personalDocAI/tests/conftest.py`，把 import 區（約第 39〜55 行）：

```python
from app.dependencies import (  # noqa: E402
    get_answerer,
    get_embeddings,
    get_entity_suggester,
    get_now,
    get_router,
    get_vlm,
)
from app.main import app  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeAnswerLLM,
    FakeEmbeddings,
    FakeEntitySuggester,
    FakeRouter,
    FakeVLM,
    FixedClock,
)
```

**換成**（多 import 兩樣：`dependencies` 模組本身、`get_job_store`，以及 `InMemoryJobStore`）：

```python
from app import dependencies  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_answerer,
    get_embeddings,
    get_entity_suggester,
    get_job_store,
    get_now,
    get_router,
    get_vlm,
)
from app.main import app  # noqa: E402
from app.services.ingest_job_store import InMemoryJobStore  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeAnswerLLM,
    FakeEmbeddings,
    FakeEntitySuggester,
    FakeRouter,
    FakeVLM,
    FixedClock,
)
```

- [ ] 在 `isolated_data_dir` 這個 fixture 的**後面**（`pytest_bdd_apply_tag` 之前）插入第四道安全網：

```python
@pytest.fixture(autouse=True)
def wire_memory_job_store(monkeypatch):
    """安全網四：pytest 永遠用記憶體 JobStore，絕不連真 Redis，而且每測清空。

    這條安全網的精神與前三條完全一樣（wire_fake_ai 絕不打真 Ollama、
    reset_tables 絕不動正式庫、isolated_data_dir 絕不寫專案的 data/）：
    **危險的預設值由 conftest 統一擋掉，不靠個別測試自律。**

    ★ 為什麼一定要 autouse（不能「需要的測試自己寫」）：
      job 的狀態是**跨請求活著**的（app/dependencies.py 的 _memory_job_store
      是整個行程共用的單例）。少了這條，A 測試建的 job 會被 B 測試的
      GET /ingest-jobs 看到，症狀是「pending_count 多了一筆」「進度清單長度不對」
      這種**看似隨機的紅**——而且單獨跑那顆測試永遠是綠的，只有整包跑才會紅，
      跟 2026-08-24 那次「兩份 pytest 互相 TRUNCATE」一樣難查。

    ★ 為什麼要「dependency_overrides ＋ monkeypatch」兩管齊下，缺一不可：
      ① app.dependency_overrides[get_job_store] 只攔得住 router 參數列上的
        Depends(get_job_store)——只有 FastAPI 解析 Depends 時才會查這張表，
        查表的 key 是「原本那個函式物件」。
      ② 但 Phase 65 起有兩處是把 get_job_store 當**普通函式直接呼叫**的：
        app/main.py 的 lifespan 掃把、app/celery_app.py 的 ingest_task
        （它們不是 HTTP 請求，Depends 根本不存在）。直接呼叫 dependency_overrides
        看不到；只做 ① 的話，那兩處會拿到行程共用的單例（Phase 65 之後更會拿到
        真的往 redis://redis:6379 撥號的 RedisJobStore），與每測的 store 各記各的
        ——這就是跨測試污染的第二條漏水路。monkeypatch.setattr 換掉的是模組屬性，
        直接呼叫端寫 dependencies.get_job_store()（呼叫當下才解析名字）就攔得到；
        測試結束時 pytest 會自動還原，不必自己收。

    回傳這個測試專屬的 store，需要直接檢查／預先塞 job 的測試可以把它寫進參數列。
    """
    store = InMemoryJobStore()
    app.dependency_overrides[get_job_store] = lambda: store              # ① Depends() 這條路
    monkeypatch.setattr(dependencies, "get_job_store", lambda: store)    # ② 直接呼叫這條路
    # 第三道保險：萬一日後有人在自己檔案的最上面 from app.dependencies import
    # get_job_store（早綁定，② 換不到他手上那份舊參照）再呼叫，摸到的會是行程共用的
    # 單例——先把單例清空，至少保證上一個測試留下的 job 不會漏到下一個測試。
    # （正確寫法是模組屬性存取 dependencies.get_job_store()，見常見陷阱 7。）
    dependencies._memory_job_store().clear()
    yield store
    app.dependency_overrides.pop(get_job_store, None)
```

- [ ] 順手把檔案第一行的 docstring：

```python
"""pytest 共用設定：把資料庫指到測試庫，每個測試前清空兩張表並重播預設資料夾。"""
```

**換成**：

```python
"""pytest 共用設定：把資料庫指到測試庫，並套上四道 autouse 安全網。

  reset_tables          每測清空四張表＋重播六筆資料夾種子（絕不動正式庫）
  wire_fake_ai          六個 AI 注入點全換假件＋固定時鐘（絕不打真 Ollama）
  isolated_data_dir     DATA_DIR 指到 tmp_path（絕不寫專案的 data/）
  wire_memory_job_store JobStore 指到每測獨立的記憶體實作（Depends 與直接
                        呼叫兩條路都攔；絕不連真 Redis）
"""
```

---

### 步驟 5：跑測試看它轉綠

- [ ] 先跑新測試：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_ingest_job_store_unit.py -v
```

預期最後一行：`12 passed`。

- [ ] 再跑全量：

```bash
pytest -q
```

預期：**基線 ＋ 12**，全綠、0 skipped。**既有測試一顆都不准紅**——本 phase 沒有改任何 router、任何 schema、任何 SQL，對外行為零改變。

若既有測試紅了，最可能的原因是 `conftest.py` 的 import 區改壞了（例如漏了 `# noqa: E402`，或把 `from app import dependencies` 放在檔案最上面而不是那一段裡）。

---

### 步驟 6：git commit

> ⚠ **依總覽 §7 鐵律 12：commit 節奏由產品負責人決定，他沒指示前先不 commit——本步驟此時跳過**，
> 指令與訊息留著備用。git 驗收改用「與開工前 `git status` 快照相減」。（2026-08-25 核對時補上。）

- [ ] 執行（**僅在產品負責人指示 commit 時**）：

```bash
cd /Users/linjunting/personalDocAI
git add app/services/ingest_job_store.py app/dependencies.py tests/conftest.py \
        tests/unit/test_ingest_job_store_unit.py
git commit -m "feat: Phase 57 JobStore 與測試安全網——ingest_job_store.py（JOB_STATUSES 四種無 success、IngestJob TypedDict 11 欄、JobStore Protocol 五方法、InMemoryJobStore 回複本）、dependencies 加 get_job_store 注入點、conftest 加第四道 autouse 安全網 wire_memory_job_store（dependency_overrides＋monkeypatch 兩管齊下：Depends 與直接呼叫都攔；絕不連真 Redis、每測清空），+12 tests；端點仍 20、對外行為零改變"
```

---

## 5. ASCII 圖

### 圖一：一筆 job 的生命週期狀態機

```text
                        POST /photos（或鏡頭快門）受理成功
                        寫 staging → store.create() → 回 202
                                     │
                                     ▼
                            ┌──────────────────┐
                            │      queued      │   attempt   = 0
                            │   （排隊中）      │   pages_done= 0
                            └────────┬─────────┘   photo_ids = []
                                     │             error     = None
                       worker 撿到這個檔，第一件事就是改狀態
                                     │
                                     ▼
                            ┌──────────────────┐
                   ┌───────►│    analyzing     │   attempt = 1
                   │        │   （分析中）      │
                   │        └────────┬─────────┘
                   │                 │
      VLM 這次失敗   │                 │  VLM 這次成功
   （看不懂／連線失敗／│                 │
     embedding 失敗）│                 ▼
                   │        embed → INSERT 收件箱 → 存原圖＋縮圖 → 刪 staging
          ┌────────┴───────┐          │
          │    retrying    │          ▼
          │  attempt = 2   │   ★ store.delete(job_id)
          │  attempt = 3   │     ＝「成功」在這個系統裡的唯一寫法
          └────────┬───────┘     （JOB_STATUSES 裡沒有 "success"）
                   │                  │
     第 3 次還是失敗 │                  ▼
     （含第一次共 3 次，D10）    進度面板那一列**自己消失**
                   │            頂欄「待決定（N）」+1
                   ▼
          ┌──────────────────┐
          │      failed      │   error = "看不懂這張照片"（短句，不是 stack）
          │   （紅字留著）    │   staging 已刪、photo 表沒有這一列
          └────────┬─────────┘
                   │
                   │  人在進度面板按那一列右上角的 ×
                   ▼
        POST /ingest-jobs/{job_id}/dismiss   → store.delete(job_id)
                   │                            （Phase 64）
                   ▼
          那一列從清單消失；清單空了 → 面板收起

   ┌────────────────────────────────────────────────────────────────┐
   │ 兩條路都以 delete 收尾，差別只在「誰按的」：                    │
   │   成功 → worker 自己刪  ｜  失敗 → 人看過了才按 × 刪            │
   │ 所以 list_open() 回來的永遠是「還沒結束、或結束了但你還沒看」。 │
   └────────────────────────────────────────────────────────────────┘
```

### 圖二：一份契約、兩個實作（本 phase 只做左邊那個）

```text
                 JobStore（Protocol ＝只寫規格、不寫實作）
                 create / get / update / delete / list_open
                        ▲                         ▲
       「有這五個方法」   │                         │  「有這五個方法」
        就算數，不必繼承 │                         │   就算數，不必繼承
                        │                         │
    ┌───────────────────┴────┐      ┌────────────┴──────────────────┐
    │  InMemoryJobStore      │      │  RedisJobStore                │
    │  ★ Phase 57（本 phase）│      │  ★ Phase 65（**不是現在**）   │
    │                        │      │                               │
    │  行程內一個 dict       │      │  真的存進 Redis（key 例如     │
    │  重啟就沒了            │      │  ingest:{job_id}，JSON 字串）  │
    │  app 與 worker 看不到  │      │  app 與 worker 兩個行程共用    │
    │  對方的資料            │      │  同一份狀態                   │
    │                        │      │                               │
    │  pytest 用它           │      │  正式環境用它                 │
    │  （D15：絕不連真 Redis）│      │  （requirements 加 redis 套件）│
    └────────────────────────┘      └───────────────────────────────┘

    呼叫端（router / run_ingest_job）只知道「我拿到一個 JobStore」，
    完全不知道也不必知道自己拿到的是哪一個 → 換實作不必改任何呼叫端。
```

### 圖三：四道 autouse 安全網（本 phase 加最後一道）

```text
   每一顆測試開始之前，pytest 自動做這四件事：

   ①  reset_tables            TRUNCATE photo/folder/entity/folder_correction
                              ＋重播六筆資料夾種子
                              🛡 絕不動正式庫（URL 必須含 PersonalDocAI_test）

   ②  wire_fake_ai            六個 AI 注入點全換成假件＋固定時鐘
                              🛡 絕不打真 Ollama（本機 Ollama 常駐著，
                                 忘記覆寫會誤觸真模型推論，一張圖 64〜88 秒）

   ③  isolated_data_dir       config.DATA_DIR → tmp_path/data
                              🛡 絕不寫專案的 data/（那裡是 52 MB 真照片，
                                 而且不入版控＝全世界只有一份）

   ④  wire_memory_job_store   get_job_store → 這一顆測試專屬的 InMemoryJobStore
       ★ 本 phase 新增        （兩條呼叫路都指到同一顆：Depends() 靠
                               dependency_overrides、直接呼叫靠 monkeypatch）
                              🛡 絕不連真 Redis，而且每測都是全新的空 store
                              🛡 少了它 → A 測試建的 job 被 B 測試看到
                                 → 看似隨機的紅（單跑綠、整包跑紅）
```

---

## 6. 驗收清單

- [ ] **開工基線已實查**：`pytest -q` 記下顆數

- [ ] **四個新符號都在，簽章與本檔 §4 步驟 2 的程式碼逐字相同**（「契約備忘」未入庫，以本檔內嵌內容為準）

  ```bash
  grep -nE "^JOB_STATUSES|^class IngestJob|^class JobStore|^class InMemoryJobStore" \
    app/services/ingest_job_store.py
  ```

  預期：四行命中

- [ ] **`JOB_STATUSES` 恰好四種、沒有 success**（不要用 `grep -c '"success"'` 之類的寫法驗——
  模組 docstring 與註解本來就寫著「沒有 "success"」這幾個字，會誤中）

  ```bash
  grep -n 'JOB_STATUSES = ("queued", "analyzing", "retrying", "failed")' app/services/ingest_job_store.py
  ```

  預期：恰一行命中（整個 tuple 逐字釘死＝四種、順序、無 success 一次驗完；
  執行期的把關另有 `test_四種狀態的清單裡沒有success` 那顆）

- [ ] **本 phase 完全沒碰 Redis／Celery**（驗 import 與 requirements，不驗註解——
  註解本來就會解釋「為什麼還不用 Redis」，抓字串會一直誤中）

  ```bash
  grep -rnE "^(import|from) .*(redis|celery)" app/ --include="*.py" || echo "OK：程式沒有 import"
  grep -inE "redis|celery" requirements.txt || echo "OK：requirements 沒有加套件"
  ```

  預期：兩行都印 `OK：…`（有命中就是不小心 `import redis`／`import celery`，或把套件加進 requirements 了）

- [ ] **注入點就位，而且風格跟 `get_vlm` 一致**

  ```bash
  grep -n "def get_job_store\|_memory_job_store" app/dependencies.py
  ```

  預期：四行命中——`@lru_cache` 那支 `def _memory_job_store` 的定義、`def get_job_store` 的定義、
  docstring 裡提到 `wire_memory_job_store` 安全網的那一行（字串裡含 `_memory_job_store`，屬正常）、
  `get_job_store` 內的 `return _memory_job_store()`

- [ ] **第四道安全網是 autouse，而且兩管都在**

  ```bash
  grep -n -B2 "def wire_memory_job_store" tests/conftest.py
  grep -n 'monkeypatch.setattr(dependencies, "get_job_store"' tests/conftest.py
  ```

  預期：第一個指令印出緊鄰上一行是 `@pytest.fixture(autouse=True)`；
  第二個指令恰一行命中（在 `wire_memory_job_store` 的函式體內）

- [ ] **四道安全網都在**

  ```bash
  grep -c "@pytest.fixture(autouse=True)" tests/conftest.py
  ```

  預期輸出：`4`

- [ ] **新測試 12 顆全綠**

  ```bash
  pytest tests/unit/test_ingest_job_store_unit.py -v
  ```

  預期最後一行：`12 passed`

- [ ] **端點數仍是 20**（本 phase 不開任何端點）

  ```bash
  pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
  ```

  預期：`1 passed`

- [ ] **SQL 依然只出現在 repository 一層**（本 phase 不該碰到 SQL；跑既有的自動化掃碼，
  不要自己 grep——手寫的 `grep "UPDATE "` 會被別的檔案裡的中文註解誤中）

  ```bash
  pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -q
  ```

  預期：`1 passed`

- [ ] **全量測試全綠**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q
  ```

  預期：**基線 ＋ 12**，且 **0 skipped**

- [ ] **零外部依賴仍然成立**（Ollama 指死埠，顆數要完全一樣）

  ```bash
  OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q
  ```

  預期：與上一條同樣的顆數、同樣全綠

- [ ] **安全網真的有效**：故意把 `wire_memory_job_store` 的 `autouse=True` 改成 `autouse=False`，跑 `pytest tests/unit/test_ingest_job_store_unit.py -q` 應該看到 `test_安全網已把注入點換成每測獨立的記憶體store` 變紅（第一句 `assert get_job_store in app.dependency_overrides` 的 `AssertionError`），其餘 11 顆仍綠（它們自己 `_new_store()`，不吃注入）；**確認會紅之後把它改回 `autouse=True`**。這一招驗得動的前提是那顆測試**沒有**把 fixture 寫進參數列——參數列有請求的 fixture 就算不是 autouse 也會被啟動，寫了參數列這一關就會假綠

- [ ] **git 收尾符合現行節奏**：產品負責人已指示 commit → 步驟 6 已執行；
  未指示（現行預設）→ 跳過 commit，改核對「`git status --short -- app tests` 的新增項
  恰為本 phase 的四個檔」（與開工前快照相減）

---

## 7. 常見陷阱

1. **以為 `Protocol` 執行時會幫你檢查。**
   它不會。`Protocol` 純粹是給編輯器與人看的規格，Python 執行時**不會**驗證 `InMemoryJobStore` 到底有沒有那五個方法。少寫一個不會在 import 時爆錯，會在 Phase 62 真的呼叫到的時候才 `AttributeError: 'InMemoryJobStore' object has no attribute 'list_open'`。所以五個方法一個都不能少，而且步驟 1 的測試每一支都有摸到。

2. **忘了 `wire_memory_job_store` 要 `autouse=True`。**
   症狀是最難查的一種：**單獨跑某一顆測試永遠是綠的，整包跑才會紅，而且每次紅的顆數不一樣。** 原因是 `app/dependencies.py` 的 `_memory_job_store()` 是 `@lru_cache` 的行程共用單例，沒有安全網的話 A 測試建的 job 會被 B 測試的 `GET /ingest-jobs` 看到（Phase 64 之後）。驗收清單最後第二條就是專門叫你把它弄紅一次、確認安全網真的有在擋。

3. **`InMemoryJobStore` 直接把內部那份字典交出去（沒有 `_copy`）。**
   測試會綠，因為記憶體版就是同一份物件。但換成 Redis 版就會紅——Redis 版每次都是「讀字串 → 解析成新字典」，天生是複本。這種「換實作才爆」的壞法極難查。`test_拿到的是複本改它不會動到store裡的資料` 就是專門擋這件事的。

4. **`_copy` 只寫 `dict(job)`，忘了複製 `photo_ids`。**
   `dict()` 是**淺複製**：新字典是新的，但 `photo_ids` 指向的仍是同一個清單。症狀：`store.get(id)["photo_ids"].append(7)` 會偷偷改到 store 裡的資料，而 `photo_ids` 正是 Phase 59 崩潰重送的冪等依據（§4.4）——被污染的話會出現「同一張照片插了兩次」。

5. **順手就把 `RedisJobStore` 也寫了、或把 `redis` 加進 `requirements.txt`。**
   本 phase 之後 Redis 根本還沒進 `compose.yaml`（那是 Phase 66），寫了跑不起來也測不到，只會多一份沒被驗證過的程式碼。而且 `requirements.txt` 一動，容器映像就得重建，而**重建映像在本專案要當成「需要手動煙霧一次」的動作**（`CLAUDE.md` 已知落差：host 的 `.venv` 與映像會慢慢分岔）。Phase 65 一次做完才划算。

6. **在 `conftest.py` 把 `from app import dependencies` 放到檔案最上面。**
   會壞。`tests/conftest.py` 的前 15 行有一段很敏感的順序：**一定要先把 `DATABASE_URL` 環境變數設成測試庫，才能 import 任何 `app.*`**（`app/core/config.py` 在 import 當下就讀環境變數）。所以所有 `app.*` 的 import 都必須留在那一段之後，並且帶 `# noqa: E402`。放錯位置的症狀是測試會連上**正式庫**——`reset_tables` 的 `assert "PersonalDocAI_test" in config.DATABASE_URL` 會擋下來，但那已經是嚇一跳的等級了。

7. **以為 `dependency_overrides` 蓋得住所有呼叫。**
   蓋不住。`app.dependency_overrides` 只在 FastAPI 解析 `Depends(...)` 時才被查表；而 Phase 65 的 app 啟動掃把（`main.py` 的 lifespan）與 Celery 的 `ingest_task` **不是 HTTP 請求**，它們是把 `get_job_store` 當普通函式**直接呼叫**——查表根本不會發生。所以第四道安全網必須「`dependency_overrides` ＋ `monkeypatch`」兩管齊下（步驟 4 的 ①②）。只做 ① 的症狀：本 phase 全綠、看起來沒事，到 Phase 65 之後 `with TestClient(app)` 一觸發 lifespan 就拿到正式 store 往 `redis://redis:6379` 撥號——卡好幾秒或一片連線錯誤。另外兩個相關的鐵則：**直接呼叫端一律寫 `from app import dependencies` ＋ `dependencies.get_job_store()`**（模組屬性在呼叫當下才解析，monkeypatch 換得掉），不要在檔案最上面 `from app.dependencies import get_job_store` 再呼叫——早綁定拿到的是換掉前的舊參照；而拿到 store 之後，`run_ingest_job(job_id, store=..., ...)` 仍是**明寫參數**收它（契約備忘 §3.3），**這也是為什麼測試可以直接呼叫 `run_ingest_job` 而不必啟動任何伺服器**（design5 §9）。

8. **`update()` 對不存在的 job 丟例外。**
   契約寫的是回 `None`。理由：worker 有可能在人已經按 × 把那筆關掉之後才寫狀態，那時安靜地什麼都不做才是對的；丟例外會讓 worker 在正常情況下噴一個假的錯誤。

9. **偷偷加一個 `"success"` 狀態「這樣比較好懂」。**
   design5 §4.3 明訂成功＝刪掉，§1.2 明文否決過「成功列留在進度面板當第二個待決定」。加了它，前端就得自己過濾（多一種「忘了過濾」的壞法），而且成功的工作會永遠佔著面板不走。

10. **同時跑兩份 pytest。**
    症狀：大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`。原因是兩份都在 `TRUNCATE` 同一個測試庫。等另一份跑完再跑。

11. **`page_count` 在圖片的 job 上填 0 而不是 `None`。**
    契約是 `int | None`，圖片永遠是 `None`。填 0 的話進度面板會顯示「（0 頁）」，而規則是「PDF 若已知頁數則顯示『檔名（N 頁）』」（§6.6）——0 頁是一種明確的錯誤狀態（design5 錯誤表第 5 列：檔壞到無法拆頁），不該拿來代表「這不是 PDF」。

---

## 8. 完成後的專案狀態

系統多了一個「一筆入庫任務跑到哪了」的存放處：一份契約（`JobStore`）＋一個記憶體實作（`InMemoryJobStore`），注入點在 `app/dependencies.py` 的 `get_job_store()`，而 pytest 有了第四道 autouse 安全網——`dependency_overrides`（攔 `Depends()`）＋ `monkeypatch`（攔直接呼叫）兩管齊下——保證每個測試都拿到乾淨的、絕不連真 Redis 的 store。

**但目前還沒有任何人呼叫它**——沒有 router 建 job、沒有 worker 改 job、沒有端點列 job。對外行為零改變，端點仍是 20 個。

下一步：**Phase 58** 做 staging 暫存區（影像位元組落磁碟，因為 design5 §4.1 明文禁止把它塞進 Redis）；**Phase 59／60** 才寫真正的 `run_ingest_job()`，那時本 phase 的五個方法會第一次真的被用到；**Phase 64** 開 `GET /ingest-jobs` 把 `list_open()` 的結果送給進度面板；**Phase 65** 才補上 `RedisJobStore`。

測試累計 ＝ 開工基線 ＋ **12**。
