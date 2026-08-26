# Phase 59：單圖入庫任務（`run_ingest_job` 的 JPEG／PNG 路徑）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 特別是：**不要**做「失敗列手動再試一次」、不要做處理進度百分比、不要把 `photo` 表加上任何狀態欄位、
> 不要在這個 phase 碰 Celery、Redis、`compose.yaml`，也**不要動 `app/api/routers/photos.py` 一個字**。

> 🎯 **一句話目標：** 新建 `app/services/ingest_job.py`，把「一張 JPEG／PNG 從暫存檔變成收件箱裡的一列照片」
> 這件事寫成一個**不知道 HTTP、也不知道 Celery** 的普通函式 `run_ingest_job(job_id, *, store, vlm, embeddings, now)`，
> 內含**最多 3 次**的看圖重試、失敗時把半成品清乾淨、成功時把任務從 JobStore 刪掉。

**為什麼要做這個：**

現在上傳一張照片，使用者的瀏覽器要**一直等**：等 gemma4 看完圖（本機實測 64〜88 秒）、
等 bge-m3 算完向量、等檔案寫完，才會拿到 201。這段時間什麼都不能做。
增量五要把它拆成兩半——HTTP 只負責「收下」（Phase 62 改成 202），真正的分析交給另一個行程慢慢做。

但**在把 HTTP 改掉之前**，得先有一個「另一個行程可以呼叫的入庫函式」。
那個函式不能長得像現在的 `_ingest_image()`——它滿身都是 HTTP 的東西：
參數靠 FastAPI 的 `Depends(...)` 注入、失敗用 `raise HTTPException(422)` 表達。
Celery worker 裡沒有請求、也沒有人會把 `HTTPException` 翻譯成回應。

所以本 phase 做的就是：**把那段流程重寫成一個純函式**，
所有依賴改用參數傳進來，所有失敗改成寫進 JobStore，並補上 design5 要的 3 次重試與清理規則。

寫完之後這個函式**還沒有人呼叫**（`POST /photos` 要到 Phase 62 才入列）。
它只被測試呼叫——這是刻意的：先讓核心邏輯在測試裡被釘死，再去動破壞性的 API 契約。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **任務本體（task body）** | 「真正要做的那件事」寫成的一個普通函式。Celery 只是負責「叫它」的傳令兵，本身不含任何邏輯 |
| **seam（可替換接縫）** | 程式裡刻意留的一個「換手處」。這裡的接縫是四個參數（`store`／`vlm`／`embeddings`／`now`）：正式跑的時候塞真東西，測試的時候塞假件，函式本身一個字都不用改 |
| **重試迴圈（retry loop）** | 「同一件事失敗了就再做一次，最多 N 次」的 `for` 迴圈。本 phase 的 N＝3，**含第一次**（也就是「第一次 ＋ 兩次補考」，不是「第一次 ＋ 三次補考」） |
| **冪等（idempotent）** | 同一個動作做兩次，結果跟做一次一樣。這裡指「同一個任務被跑第二次，照片不會變成兩張」 |
| **崩潰重送（redelivery）** | worker 做到一半被殺掉時，佇列會認為「這件事沒人做完」，把同一個任務再發給別人做一次。這是佇列的正常行為，不是壞掉 |
| **清理半成品** | 流程做到一半失敗時，把「已經寫出去的檔案」與「已經插進去的資料列」全部收回來，讓結果跟「沒發生過」一樣 |
| **JobStore** | Phase 57 建的「任務狀態本子」。誰做到第幾步、失敗訊息是什麼，都記在這裡。測試用記憶體版，正式用 Redis 版（Phase 65） |
| **staging（暫存區）** | Phase 58 建的 `data/staging/` 目錄。HTTP 收到檔案先丟在這裡，worker 之後再來拿。**影像位元組絕不進 Redis、也絕不當 Celery 參數** |

---

## 1. 對應 design5.md 章節

| 章節／編號 | 內容 |
|---|---|
| **D10** | 失敗重試後刪：同一張圖**含第一次共送 VLM 3 次**；看不懂與呼叫失敗都算；3 次都失敗→整筆拿掉（不留 `photo` 列、刪 staging） |
| **D14** | AI 開關快照：worker 用任務裡的 `ai_backend` 建 VLM 客戶端；embedding 仍一律本機 |
| **D15** | 測試不碰真 Redis：任務本體抽成 `run_ingest_job(...)`，測試直接呼叫 |
| **§2 流程** | 「兩個 worker 各拿一個檔 → JPEG／PNG：VLM 最多 3 次 → embed → INSERT 收件箱 → 原圖＋縮圖落地 → 刪 staging」 |
| **§4.1** | staging：成功入庫或最終失敗都刪 staging |
| **§4.2** | 何時才有 `photo` 列：VLM 成功、embedding 成功之後才 INSERT；落點與現在相同（收件箱、`data/photos`／`data/thumbs`） |
| **§4.3** | JobStore 每筆欄位的用途；`error` 是「給人看的短句」，**不要把 stack 丟給瀏覽器** |
| **§4.4 崩潰重送** | 3 次是**任務函式內部**迴圈，**不要**用 Celery `autoretry` 整份重跑；JPEG／PNG 的冪等規則＝「已有 `photo_ids` → 視為成功」；任務開頭先把 status 改 `analyzing` |
| **§8 錯誤表第 3 列** | JPEG／PNG 看不懂或呼叫失敗 ×3 → 刪 staging、無 `photo` 列、job=`failed` |
| **§8 錯誤表第 6 列** | embedding 失敗 → 尚未 INSERT 則算這次失敗，計入 3 次；3 次後同第 3 列 |
| **§8 錯誤表第 7 列** | 入庫寫檔失敗 → 與現在 `_ingest_image` 相同：清掉半成品再標失敗，不留孤兒列 |
| **§9 測試策略** | 「本增量必加」清單的第 2、3 條（FakeVLM 一次成功／三次失敗——本 phase 在 JobStore 與資料庫層釘住；「job 不在 GET 清單」「pending_count」的 HTTP 面是 Phase 64）＋第 6 條崩潰重送。第 1 條「202 當下」是 Phase 62 的事，本 phase 不碰 |
| **§1.2 被否決** | 「影像位元組當 Celery 參數／塞 Redis」——所以本函式**只吃 job_id** |

PDF 路徑（D11／D12、§8 第 4、5 列）是 **Phase 60**，本 phase 不做。
建議三欄落庫（D16）是 **Phase 61**，本 phase 不做。

---

## 2. 前置條件

- **Phase 57 已完成**：`app/services/ingest_job_store.py` 有 `IngestJob`、`JobStore`、`InMemoryJobStore`；
  `tests/conftest.py` 有第四道 autouse `wire_memory_job_store`。
- **Phase 58 已完成**：`app/services/staging_service.py` 有 `staging_path`／`save_staging`／`read_staging`／`remove_staging`。
- **不需要** Phase 52〜56（那些是階段甲與資料庫遷移，與本檔互不相干；只有 Phase 61 才需要 56）。

開工前**實際跑一次**確認基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps                      # db 必須是 Up (healthy)，否則測試會一整片連線錯誤
pytest -q
```

預期：全綠、0 skipped。顆數＝你**當下實查到的數字**——增量五從 405 起算，
必要前置 Phase 57 加 12、Phase 58 加 10；若照總覽順序把 52〜56 也做完了，會再多 15（＝442）。
本文件之後一律稱這個實查數字為「**開工基線**」。
**先把這個數字抄下來**，第 7 步要拿它來對帳。

再確認兩個前置模組真的存在（沒有就先回去做 57／58，不要在這裡自己補一個）：

```bash
python -c "
from app.services.ingest_job_store import InMemoryJobStore, JobStore, IngestJob
from app.services import staging_service
print('JobStore OK：', [m for m in ('create','get','update','delete','list_open') if hasattr(InMemoryJobStore(), m)])
print('staging OK：', [m for m in ('staging_path','save_staging','read_staging','remove_staging') if hasattr(staging_service, m)])
"
```

預期兩行都印出完整的五個／四個名字。

> ⚠️ **絕對不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。
> `reset_tables` 每顆測試都會 TRUNCATE 同一個測試庫，兩份同時跑會互相清掉對方的資料，
> 症狀是「大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`」。

---

## 3. 範圍

### 做

1. `app/core/config.py` 新增 `VLM_MAX_ATTEMPTS = 3`（契約備忘 §3.6）。
2. 新建 `app/services/ingest_job.py`：
   - `run_ingest_job(job_id, *, store, vlm, embeddings, now)` —— 公開入口，依 `content_type` 分流。
   - `_run_image_job(...)` —— JPEG／PNG 的完整流程。
   - `_understand_and_embed(...)` —— 3 次重試迴圈（看圖＋轉向量）。
   - `_insert_photo_with_files(...)` —— INSERT → 寫原圖 → 寫縮圖 → UPDATE 補路徑，失敗清乾淨再 re-raise。
   - `_fail(...)` —— 刪 staging ＋ 把 job 標成 `failed`。
3. `tests/fakes.py` 新增 `ScriptedVLM`（可以指定「第幾次回什麼、第幾次丟什麼例外」的假件）。
4. 新建 `tests/integration/test_ingest_job.py`（11 顆）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改 `app/api/routers/photos.py` | `POST /photos` 要到 **Phase 62** 才改 202。本 phase 動它，405 顆既有測試會整片變紅，而且兩條契約同時改根本查不出是誰壞的 |
| 改 `app/api/routers/camera.py` | 理由與上一列相同（別讓兩條 API 契約同時在改），而且那是 **Phase 63** 的事 |
| 刪掉 `_ingest_image()` | 它現在還是 `POST /photos` 與鏡頭快門的正式路徑。Phase 62／63 把兩個呼叫端改完之後才輪到它退休 |
| 用 Celery 的 `autoretry_for` 做重試 | design5 §4.4 明文禁止。整份重跑會把**已經 INSERT 的照片再插一次**（詳見 §5 的第二張圖） |
| 在這裡 import `celery` 或 `redis` | 本 phase 不裝這兩個套件（Phase 65 才裝）。`ingest_job.py` 永遠不該知道佇列的存在 |
| 在這裡 import `fastapi` | 這個模組要能在沒有 web 框架的行程裡跑。有 `HTTPException` 就代表沒抽乾淨 |
| 把 `error` 寫成 traceback | design5 §4.3：`error` 是**給人看的短句**。stack trace 進 log，不進瀏覽器 |
| PDF 路徑 | Phase 60 |
| 建議三欄（`suggested_entity` 等）落庫 | Phase 61 |
| 讓 worker 自動釘實體／建待辦 | design5 §4.2：人按確認才寫。本 phase 連 `suggested_*` 都只寫 `suggested_category`（沿用現況） |
| 加「處理狀態」欄位到 `photo` 表 | design5 §11 明文不改。狀態全部活在 JobStore |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：步驟 1〜2 準備常數與假件、步驟 3 寫會紅的測試、步驟 4 跑它確認紅、
> 步驟 5 寫實作、步驟 6 轉綠、步驟 7 全量回歸、步驟 8 commit。

### - [ ] 步驟 1：`app/core/config.py` 加一個常數

打開 `app/core/config.py`，在 `TOP_K = 5` 那一行**後面**加上（跟 `RECENT_DAYS`／`TOP_K` 這些數字型業務常數放在一起；再往下的 `DATA_DIR`／`PDF_CONTENT_TYPE` 等仍在同一段，不要動它們）：

```python
# 同一張照片（或 PDF 的同一頁）最多送 VLM 幾次，**含第一次**（design5.md D10）。
# 3 ＝ 第一次 ＋ 兩次補考。看不懂與呼叫失敗（Ollama 沒開、雲端 401／逾時）都各算一次。
# ★ 這個重試是「入庫任務函式**內部**的 for 迴圈」，不是 Celery 的 autoretry——
#   後者會把整個任務從頭再跑，把已經 INSERT 的照片再插一次（design5.md §4.4）。
VLM_MAX_ATTEMPTS = 3
```

驗一下：

```bash
python -c "from app.core import config; print(config.VLM_MAX_ATTEMPTS)"
```

預期印出 `3`。

### - [ ] 步驟 2：`tests/fakes.py` 加一個「照劇本演」的假件

**為什麼不是改 `FakeVLM`：** `FakeVLM` 的身分就是「一張固定的答案卡」——建構時給一個結果，之後每次都回那一個。
全專案有二十幾個測試檔靠它，`conftest.py` 的 `wire_fake_ai` 也預設塞它。
本 phase 要的是完全不同的東西：**每一次呼叫可以不一樣**，而且要能「丟例外」（模擬 Ollama 沒開）。
把這兩種語意塞進同一個 class，之後讀 `FakeVLM(某結果)` 的人會分不清它到底會回幾次。
所以**新做一個假件**，`FakeVLM` 一個字不動。

打開 `tests/fakes.py`，在 `class FakeEntitySuggester:` **之前**（也就是 `FakeVLM` 的正下方）加上：

```python
class ScriptedVLM:
    """照劇本演的看圖假件：第 1 次回什麼、第 2 次丟什麼，全部先寫好。

    給「重試」相關的測試用（Phase 59 起）。與 FakeVLM 的差別只有一個：
    FakeVLM 是**一張固定答案卡**（每次都回同一個結果），
    ScriptedVLM 是**一疊照順序翻的卡**，而且卡片可以是「丟這個例外」。

    script 裡每一項只能是兩種東西：
      - PhotoUnderstanding → 這一次就回它（understood=False 也是一種合法答案）
      - Exception 的實例   → 這一次就把它丟出去（模擬 Ollama 沒開、雲端 401、逾時）

    劇本演完還被呼叫 → 直接 AssertionError。這是刻意的：
    「多打了一次模型」是本 phase 最需要抓的錯（重試上限沒守住），
    默默重複最後一張卡會讓那種 bug 溜過去。
    """

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0
        self.last_folders: list[dict] | None = None
        self.last_entities: list[dict] | None = None
        self.last_corrections: list[dict] | None = None

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        assert self.calls < len(self.script), (
            f"ScriptedVLM 被呼叫第 {self.calls + 1} 次，但劇本只寫了 "
            f"{len(self.script)} 次——重試次數超過上限了嗎？"
        )
        item = self.script[self.calls]
        self.calls += 1
        self.last_folders = folders
        self.last_entities = entities
        self.last_corrections = corrections
        if isinstance(item, Exception):
            raise item
        return item
```

### - [ ] 步驟 3：先寫測試（紅）——新增 `tests/integration/test_ingest_job.py`

```python
"""單圖入庫任務的整合測試（design5.md §9「本增量必加」前三條 ＋ §4.4 崩潰重送）。

★ 本檔**不打 HTTP**：直接呼叫 run_ingest_job()。
  這正是 design5 D15 說的「任務本體抽成函式，測試直接呼叫」——
  pytest 因此不必啟動 Celery、不必連 Redis、不必等 worker 排班。

conftest 的四道 autouse 安全網照樣生效：
  reset_tables          → 每顆測試前清空資料庫並重播六筆資料夾（收件箱固定是 id 1）
  isolated_data_dir     → config.DATA_DIR 指到暫存目錄，所以 staging／原圖／縮圖
                          全部寫在暫存目錄，永遠不會弄髒專案的 data/
  wire_fake_ai          → 本檔用不到（沒走 FastAPI 的注入），留著不影響
  wire_memory_job_store → 同樣用不到（store 不經 get_job_store 注入，
                          每顆測試自己 new 一個 InMemoryJobStore），留著不影響

四個依賴一律**當參數傳**，不靠 dependency_overrides：
  store       → 每顆測試自己 new 一個 InMemoryJobStore（不共用，天生隔離）
  vlm         → FakeVLM／ScriptedVLM
  embeddings  → FakeEmbeddings（或本檔的 壞掉的Embeddings）
  now         → FixedClock（**callable**，呼叫它才拿到 datetime）
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core import config
from app.repositories import photo_repository
from app.services import ingest_job, staging_service, storage_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeEmbeddings,
    FakeVLM,
    FixedClock,
    ScriptedVLM,
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
看不懂 = PhotoUnderstanding(understood=False)
# 「看得懂但一個字都沒寫」也算看不懂（沿用 _ingest_image 的 text.strip() 檢查）
空白描述 = PhotoUnderstanding(understood=True, text="   ")


class 壞掉的Embeddings:
    """每次都炸的向量產生器，用來重現 design5 §8 第 6 列（embedding 失敗）。

    刻意寫在本檔而不是 tests/fakes.py：只有這一顆測試需要它，
    放進共用檔會讓「假件清單」多一個沒人用的東西。
    """

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("bge-m3 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("bge-m3 沒有回應")


def 建一個job(
    store: InMemoryJobStore,
    *,
    job_id: str = "job-1",
    content_type: str = "image/png",
    filename: str = "a.png",
    data: bytes | None = None,
    ai_backend: str = "local",
    source: str = "upload",
) -> str:
    """模擬 Phase 62 的 HTTP 端點會做的兩件事：落 staging ＋ 建 job。

    回傳 job_id，讓測試接著餵給 run_ingest_job。
    """
    staging_service.save_staging(
        job_id, content_type, data if data is not None else make_png_bytes()
    )
    store.create(
        job_id=job_id,
        filename=filename,
        content_type=content_type,
        ai_backend=ai_backend,
        source=source,
    )
    return job_id


def 收件箱id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


# ---------------------------- ① 一次就成功 ----------------------------


def test_一次看得懂就入庫_照片進收件箱_staging消失_job被刪():
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = FakeVLM(收據理解)

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    # 照片真的進去了，而且掛在收件箱（design5 §4.2：落點與現在相同）
    assert photo_repository.count_photos() == 1
    photos = photo_repository.list_photos_in_folder(收件箱id())
    assert len(photos) == 1
    row = photo_repository.fetch_photo(photos[0]["id"])
    assert row["text"] == 收據理解.text
    assert row["category"] == "未分類"          # 一律先進收件箱，建議不落庫成歸屬
    assert row["suggested_category"] == "收據"  # 建議照舊存下來（Phase 35 行為不變）
    assert row["uploaded_at"].strftime("%Y-%m-%d %H:%M") == "2026-08-18 10:00"

    # 原圖與縮圖都落地了
    assert storage_service.absolute_path(row["original_path"]).is_file()
    assert storage_service.absolute_path(row["thumbnail_path"]).is_file()

    # staging 清掉、job 刪掉（design5 §4.3：成功＝刪掉這筆 job）
    assert not staging_service.staging_path(job_id, "image/png").exists()
    assert store.get(job_id) is None
    assert store.list_open() == []
    assert vlm.calls == 1, "看得懂就不該重試"


# ---------------------------- ② 三次都看不懂 ----------------------------


def test_三次都看不懂_不留照片_staging不在_job標failed且attempt為3():
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([看不懂, 看不懂, 看不懂])

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    assert vlm.calls == 3, "含第一次共 3 次（design5 D10）"
    assert photo_repository.count_photos() == 0, "看不懂就什麼都不存"
    assert not staging_service.staging_path(job_id, "image/png").exists()

    job = store.get(job_id)
    assert job is not None, "失敗的 job 要留著給進度面板顯示，不可以刪"
    assert job["status"] == "failed"
    assert job["attempt"] == 3
    assert job["photo_ids"] == []
    assert store.list_open() == [job]


def test_呼叫失敗也算一次_三次例外同樣整筆失敗():
    """design5 D10：看不懂與呼叫失敗（Ollama 沒開／雲端 401／逾時）都算一次。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM(
        [
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
        ]
    )

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    assert vlm.calls == 3
    assert photo_repository.count_photos() == 0
    assert store.get(job_id)["status"] == "failed"


def test_空白描述也算看不懂():
    """understood=True 但 text 全是空白 → 沿用 _ingest_image 的判準，算失敗。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([空白描述, 空白描述, 空白描述])

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    assert vlm.calls == 3
    assert photo_repository.count_photos() == 0
    assert store.get(job_id)["status"] == "failed"


# ---------------------------- ③ 第三次才成功 ----------------------------


def test_第三次才成功_照樣只入庫一列():
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([看不懂, RuntimeError("Ollama 沒開"), 收據理解])

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    assert vlm.calls == 3
    assert photo_repository.count_photos() == 1, "重試成功不可以變成三張照片"
    assert store.get(job_id) is None, "成功＝刪 job"
    assert not staging_service.staging_path(job_id, "image/png").exists()


# ---------------------------- ④ embedding 失敗 ----------------------------


def test_轉向量三次都失敗_不留照片_job標failed():
    """design5 §8 第 6 列：尚未 INSERT 就失敗 → 算這次失敗，計入 3 次。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([收據理解, 收據理解, 收據理解])

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=壞掉的Embeddings(), now=NOW
    )

    assert vlm.calls == 3, "embedding 失敗也要重看一次圖（整個 attempt 重來）"
    assert photo_repository.count_photos() == 0
    assert not staging_service.staging_path(job_id, "image/png").exists()
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["attempt"] == 3


# ---------------------------- ⑤ 寫檔失敗 ----------------------------


def test_寫檔失敗_不留照片也不留孤兒檔_job標failed(monkeypatch):
    """design5 §8 第 7 列：與現在 _ingest_image 相同，清掉半成品再標失敗。"""
    def 一定失敗(photo_id, image_bytes, content_type):
        raise RuntimeError("磁碟壞了")

    monkeypatch.setattr(storage_service, "make_thumbnail", 一定失敗)

    store = InMemoryJobStore()
    job_id = 建一個job(store)

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=FakeVLM(收據理解), embeddings=FakeEmbeddings(), now=NOW
    )

    assert photo_repository.count_photos() == 0, "不可以留下孤兒列"
    assert not list((config.DATA_DIR / "photos").glob("*")), "不可以留下孤兒檔案"
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["photo_ids"] == []
    assert not staging_service.staging_path(job_id, "image/png").exists()


# ---------------------------- ⑥ 崩潰重送 ----------------------------


def test_崩潰重送_job已有photo_ids再跑一次_列數仍為1():
    """design5 §4.4：JPEG／PNG 的冪等規則就是「已有 photo_ids → 視為成功」。

    重現方式：先正常跑完一次（job 被刪），再用**同一個 job_id** 重建一筆
    並把 photo_ids 填回去——這就是「worker 做完但 ack 沒送到，佇列又發一次」的樣子。
    """
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    ingest_job.run_ingest_job(
        job_id, store=store, vlm=FakeVLM(收據理解), embeddings=FakeEmbeddings(), now=NOW
    )
    photo_id = photo_repository.list_photos_in_folder(收件箱id())[0]["id"]
    assert photo_repository.count_photos() == 1

    # 佇列把同一個任務再發一次：staging 重新落地、job 重建且帶著 photo_ids
    staging_service.save_staging(job_id, "image/png", make_png_bytes())
    store.create(
        job_id=job_id,
        filename="a.png",
        content_type="image/png",
        ai_backend="local",
        source="upload",
    )
    store.update(job_id, photo_ids=[photo_id])
    第二次的vlm = ScriptedVLM([])   # 劇本是空的：只要被呼叫一次就 AssertionError

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=第二次的vlm, embeddings=FakeEmbeddings(), now=NOW
    )

    assert 第二次的vlm.calls == 0, "已經做完的任務不可以再看一次圖"
    assert photo_repository.count_photos() == 1, "重送不可以變成兩張照片"
    assert store.get(job_id) is None, "重送也要正常收尾（刪 job）"
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_job根本不存在時什麼都不做():
    """job 已過期或已被刪：安靜結束，不可以炸掉整個 worker。"""
    store = InMemoryJobStore()

    ingest_job.run_ingest_job(
        "沒有這筆", store=store, vlm=FakeVLM(收據理解),
        embeddings=FakeEmbeddings(), now=NOW,
    )

    assert photo_repository.count_photos() == 0


# ---------------------------- ⑦ 計時 log 與錯誤訊息 ----------------------------


def test_成功時看圖與轉向量各留一組計時log(caplog):
    """design4.md §5 的計時 log 在 worker 裡也要在（新程式碼一樣要接上）。"""
    caplog.set_level(logging.INFO)
    store = InMemoryJobStore()
    job_id = 建一個job(store)

    ingest_job.run_ingest_job(
        job_id, store=store, vlm=FakeVLM(收據理解), embeddings=FakeEmbeddings(), now=NOW
    )

    開始 = [m for m in caplog.messages if m.startswith("AI 開始 kind=")]
    結束 = [m for m in caplog.messages if m.startswith("AI 結束 kind=")]
    assert len([m for m in 開始 if "kind=vlm " in m]) == 1, caplog.messages
    assert len([m for m in 開始 if "kind=embed " in m]) == 1, caplog.messages
    assert all("ok=true" in m for m in 結束), caplog.messages


def test_失敗訊息是給人看的短句_不含stacktrace():
    """design5 §4.3：error 給人看，stack trace 只進伺服器 log。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)

    ingest_job.run_ingest_job(
        job_id,
        store=store,
        vlm=ScriptedVLM([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")]),
        embeddings=FakeEmbeddings(),
        now=NOW,
    )

    error = store.get(job_id)["error"]
    assert isinstance(error, str) and error.strip()
    assert len(error) <= 40, "進度面板一列放得下才行"
    assert "Traceback" not in error
    assert "RuntimeError" not in error
```

### - [ ] 步驟 4：跑它，確認是**紅的**

```bash
pytest tests/integration/test_ingest_job.py -q
```

預期：**整個檔在收集（collection）階段就報錯**——pytest 的結尾是 `1 error`（不會逐顆列出 11 個失敗，
因為 import 就掛了，一顆都跑不起來），內容是 `ModuleNotFoundError: No module named 'app.services.ingest_job'`。
**這就是紅**。看到別的錯誤（例如 `ImportError: cannot import name 'InMemoryJobStore'`）代表 Phase 57／58 沒做完，先回去補。

### - [ ] 步驟 5：綠——新建 `app/services/ingest_job.py`

```python
"""照片入庫的任務本體：一個檔案 ＝ 一次 run_ingest_job（design5.md D11／D15）。

★ 這個模組**不知道 HTTP 是什麼，也不知道 Celery 是什麼。**
  它只吃一個 job_id，其餘全部從參數拿（store／vlm／embeddings／now）。
    - Celery 任務（Phase 65）＝薄薄一層：組好那四個參數，呼叫這裡。
    - pytest（Phase 59）    ＝直接呼叫這裡，不啟動 worker、不連 Redis。
  這條「可替換接縫」（seam）就是 design5 D15 的全部意思。

★ 這裡**沒有 HTTPException**。
  舊的 `photos.py::_ingest_image()` 用「丟 HTTPException(422)」表達「看不懂」，
  因為那時候整段流程活在一個 HTTP 請求裡，FastAPI 會把它翻譯成回應。
  搬進 worker 之後沒有人會做那個翻譯——所以「看不懂」在這裡改用**回傳值**表達
  （`_understand_and_embed` 回 None），最終結果寫進 JobStore：
  `status="failed"` ＋ 一句給人看的短句（design5 §4.3）。

★ 重試在**函式內部**（design5.md §4.4）。
  同一張圖最多送 VLM `config.VLM_MAX_ATTEMPTS` 次（含第一次）。
  ⛔ **絕對不要**改用 Celery 的 `autoretry_for` 讓整個任務重跑——
     那會把已經 INSERT 的照片再插一次。理由與圖解見計畫文件 phase-59 §5。

分層：本模組會呼叫 repository（寫資料庫）、storage_service（寫檔）、
staging_service（讀／刪暫存檔）、vlm_service／indexing_service（AI）。
它**不寫任何 SQL**（全站鐵律：SQL 只在 photo_repository）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.repositories import photo_repository
from app.services import (
    ai_timing,
    indexing_service,
    staging_service,
    storage_service,
    vlm_service,
)
from app.services.ingest_job_store import IngestJob, JobStore

logger = logging.getLogger(__name__)

# 看圖 prompt 要注入幾筆糾錯例子。與 api/routers/photos.py 的同名常數相同值——
# 短暫的兩份是刻意的：Phase 62 先把 POST /photos 改走佇列（並刪 _ingest_pdf 那一組），
# 但 camera.py 還呼叫著 _ingest_image，所以 photos.py 那一份要等 **Phase 63**
# 把鏡頭端點也改完、_ingest_image 退休時一起刪掉，從此只剩這一份。
FEW_SHOT_CORRECTIONS = 5

# 失敗時寫進 job["error"] 的句子。**給人看的短句**，不是 traceback（design5.md §4.3）。
# 進度面板一列就這麼寬，寫太長會被截掉，所以刻意都在 20 個字以內。
ERROR_VLM_FAILED = "AI 看不懂這張照片（已試 {attempts} 次）"
ERROR_WRITE_FAILED = "照片存檔失敗，這張沒有留下資料"


class _NotUnderstood(Exception):
    """「這一次 VLM 沒看懂」。只在本模組內部從 with 區塊丟到迴圈外。

    為什麼要一個例外而不是 if：計時 log 的「結束行要標 ok=false」是靠
    ai_timing 的 with 區塊捕捉例外做到的（design4.md §5.2）。
    在 with 裡面 raise，結束行才會誠實地標成失敗——這與現在
    `_ingest_image` 在 with 裡面 raise HTTPException(422) 是同一個手法。
    """


def run_ingest_job(
    job_id: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """把一個 job 從頭做到尾。不回傳東西——結果全部寫進 JobStore 與資料庫。

    now 是**可呼叫的**（與 dependencies.get_now 同型）：
      - 正式執行傳 `get_now` 本人 → 呼叫得到 None → 上傳時間交給資料庫的 now()
      - 測試傳 FixedClock          → 呼叫得到固定時間
    這裡一定要寫 `now()` 而不是直接把 now 當值用，否則會把函式物件塞進資料庫。

    ★ 任務開頭先把 status 改成 analyzing（design5.md §4.4）：
      崩潰重送時，面板上那一列不會停在 queued 讓人以為沒動靜。
    """
    job = store.get(job_id)
    if job is None:
        # job 過期或已被刪：安靜結束。這不是錯誤——重送時本來就可能撞到。
        # 這裡沒有 content_type，所以連 staging 都算不出路徑；
        # 真的有殘檔就交給 Phase 58 的 24 小時掃把清（design5.md §4.1）。
        logger.warning("job %s 不存在，這次不做任何事", job_id)
        return

    store.update(job_id, status="analyzing")

    if job["content_type"] == config.PDF_CONTENT_TYPE:
        # Phase 60 才實作。目前不可能走到這裡——沒有任何地方會建出 PDF 任務
        #（POST /photos 要到 Phase 62 才改成入列）。
        raise NotImplementedError("PDF 任務在 Phase 60 實作")

    _run_image_job(job, store=store, vlm=vlm, embeddings=embeddings, now=now)


def _run_image_job(
    job: IngestJob,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
) -> None:
    """一張 JPEG／PNG 的完整入庫（design5.md §2、§4.2）。"""
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 冪等檢查（design5.md §4.4）：已經有照片 id 了＝上一次其實做完了，
    #    只是 ack 沒送回佇列。再插一次會變成兩張，所以直接收尾就好。
    if job.get("photo_ids"):
        logger.info(
            "job %s 已有照片 %s，判定為崩潰重送，直接收尾不重做",
            job_id,
            job["photo_ids"],
        )
        staging_service.remove_staging(job_id, content_type)
        store.delete(job_id)
        return

    # ② 從暫存區把位元組讀回來。影像**從來不進 Redis、也不當 Celery 參數**
    #    （design5.md §4.1、§1.2 被否決項）。
    image_bytes = staging_service.read_staging(job_id, content_type)

    # ③ 清單各讀一次（與現在 _ingest_image 的呼叫端一字不差）：
    #    資料夾、實體、最近的糾錯例子都要注入看圖 prompt。
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
    inbox = next(folder for folder in folders if folder["is_inbox"])

    # ④ 看圖＋轉向量，最多 VLM_MAX_ATTEMPTS 次
    result = _understand_and_embed(
        job_id,
        image_bytes,
        content_type,
        store=store,
        vlm=vlm,
        embeddings=embeddings,
        folders=folders,
        entities=entities,
        corrections=corrections,
        inbox_name=inbox["name"],
    )
    if result is None:
        _fail(
            job_id,
            ERROR_VLM_FAILED.format(attempts=config.VLM_MAX_ATTEMPTS),
            store=store,
            content_type=content_type,
        )
        return
    understanding, embedding = result

    # ⑤ 寫資料庫＋寫檔。這一段失敗就是最終失敗（VLM 已經成功了，重看沒有意義）
    try:
        photo_id = _insert_photo_with_files(
            image_bytes,
            content_type,
            understanding,
            embedding,
            inbox_name=inbox["name"],
            folders=folders,
            uploaded_at=now(),
        )
    except Exception:
        logger.exception("job %s 入庫寫入失敗，半成品已清乾淨", job_id)
        _fail(job_id, ERROR_WRITE_FAILED, store=store, content_type=content_type)
        return

    # ⑥ 收尾。photo_ids 一定要在刪 staging 之前寫進去——
    #    順序反過來的話，「剛好在這兩步之間被殺掉」的重送會找不到冪等依據。
    store.update(job_id, photo_ids=[photo_id])
    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    logger.info(
        "job %s 入庫完成：photo_id=%d（先進「%s」，等使用者到待決定頁歸類）",
        job_id,
        photo_id,
        inbox["name"],
    )


def _understand_and_embed(
    job_id: str,
    image_bytes: bytes,
    content_type: str,
    *,
    store: JobStore,
    vlm: vlm_service.VLMClient,
    embeddings: Embeddings,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
    inbox_name: str,
) -> tuple[vlm_service.PhotoUnderstanding, list[float]] | None:
    """看圖 ＋ 轉向量，最多試 config.VLM_MAX_ATTEMPTS 次；全部失敗回 None。

    一次 attempt ＝「看一次圖 ＋ 算一次向量」。兩者任一失敗都算這次失敗
    （design5.md §8 第 6 列：embedding 失敗算進 3 次），下一次從看圖重來。

    ★ 為什麼 embedding 失敗要連圖一起重看？
      因為 embedding 吃的是這次看圖的結果。只重算向量不重看圖也可以，
      但那要多一層狀態；而 3 次上限本來就是保守值，重看一次圖的成本可以接受。
      重點是**兩者都還沒 INSERT**，所以重來完全乾淨。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        # 第 1 次是 analyzing，第 2、3 次是 retrying（design5.md §4.3 的四種狀態）
        store.update(
            job_id,
            status="analyzing" if attempt == 1 else "retrying",
            attempt=attempt,
        )

        try:
            # 計時 log 走全站共用的 ai_timing（design4.md §5）。
            # target 從 vlm 物件身上拿：正式的 OllamaVLM／OllamaCloudVLM 建構時
            # 就把 backend 與 model 記在 timing_target 上，所以 worker 只要
            # 「用任務裡的 ai_backend 快照建對客戶端」，log 的 backend= 自然就對
            #（design5.md D14）。假件沒有這個屬性，會退回讀 config，不影響測試。
            with ai_timing.log_ai(
                "vlm", target=vlm_service.vlm_timing_target(vlm)
            ) as 計時:
                understanding = vlm.understand(
                    image_bytes, content_type, folders, entities, corrections
                )
                if not understanding.understood or not understanding.text.strip():
                    計時.note = (
                        f"understood=false text_chars={len(understanding.text)}"
                    )
                    raise _NotUnderstood()
                計時.note = (
                    f"understood=true text_chars={len(understanding.text)} "
                    f"item_count={len(understanding.items)} "
                    f"category_present={'true' if understanding.category else 'false'} "
                    f"entity_present={'true' if understanding.entity else 'false'} "
                    f"task_present={'true' if understanding.task_title else 'false'}"
                )
        except _NotUnderstood:
            logger.warning("job %s：第 %d 次看圖，AI 說看不懂", job_id, attempt)
            continue
        except Exception:
            # Ollama 沒開、雲端 401／404、逾時、結構化輸出驗證不過……全算一次失敗。
            # exc_info=True 讓 traceback 進伺服器 log；它**不會**進 job["error"]。
            logger.warning(
                "job %s：第 %d 次看圖呼叫失敗", job_id, attempt, exc_info=True
            )
            continue

        # 合併與轉向量一律用收件箱名稱——上傳當下的向量就是未分類版本
        #（design1.md §2；歸類時 PATCH 會整條重算）
        content_time = vlm_service.parse_content_time(understanding.content_time)
        document = indexing_service.build_document(
            text=understanding.text,
            category=inbox_name,
            location=understanding.location,
            items=understanding.items,
            content_time=content_time.isoformat() if content_time else None,
        )
        try:
            with ai_timing.log_ai(
                "embed",
                target=indexing_service.embedding_timing_target(embeddings),
            ):
                embedding = indexing_service.embed_document(embeddings, document)
        except Exception:
            logger.warning(
                "job %s：第 %d 次轉向量失敗", job_id, attempt, exc_info=True
            )
            continue

        return understanding, embedding

    return None


def _insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    uploaded_at: datetime | None,
) -> int:
    """INSERT → 存原圖 → 產縮圖 → UPDATE 補路徑。任何一步失敗就清乾淨再往外丟。

    ★ 這一段是從 `photos.py::_ingest_image()` 的第 ★③〜⑤ 段**原封不動搬過來的**
      （見計畫文件 phase-59 §4 步驟 5 的對照表）：檔名要用 photo.id，
      而 id 是 INSERT 當下才配發的，所以只能先 INSERT、寫完檔再回來補路徑。
      這三步不是一條 SQL，沒有交易可以 rollback（交易也管不到磁碟上的檔案），
      所以失敗時自己把兩個檔案與那一列刪掉，再把原始錯誤往外丟。
      差別只有一個：往外丟之後，接住它的不再是 FastAPI（500），
      而是 `_run_image_job` 的 except（把 job 標成 failed）。
    """
    # VLM 給的類別只當「建議」：夾回清單內，清單外一律變「未分類」。
    # 建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL（Phase 35 的規則不變）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    suggested_category = None if suggested_name == inbox_name else suggested_name

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=vlm_service.parse_content_time(understanding.content_time),
        embedding=embedding,
        uploaded_at=uploaded_at,
        suggested_category=suggested_category,
    )
    photo_id = row["id"]

    original_path: str | None = None
    thumbnail_path: str | None = None
    try:
        original_path = storage_service.save_original(
            photo_id, image_bytes, content_type
        )
        thumbnail_path = storage_service.make_thumbnail(
            photo_id, image_bytes, content_type
        )
        photo_repository.update_photo_paths(
            photo_id,
            original_path=original_path,
            thumbnail_path=thumbnail_path,
            content_type=content_type,
        )
    except Exception:
        # remove_if_exists 吃得下 None（那一步還沒跑到就失敗了）與「檔案本來就不在」
        storage_service.remove_if_exists(original_path)
        storage_service.remove_if_exists(thumbnail_path)
        photo_repository.delete_photo(photo_id)
        raise

    return photo_id


def _fail(job_id: str, message: str, *, store: JobStore, content_type: str) -> None:
    """最終失敗的統一收尾：刪 staging ＋ 把 job 標成 failed。

    **不刪 job**——失敗的那一列要留在進度面板上讓人看到，
    由使用者按 × 走 `POST /ingest-jobs/{id}/dismiss` 才消失（design5.md §4.3）。
    """
    staging_service.remove_staging(job_id, content_type)
    store.update(job_id, status="failed", error=message)
    logger.warning("job %s 最終失敗：%s", job_id, message)
```

**哪幾段是從 `_ingest_image()` 一字不動搬過來的**（實作時可對照 `app/api/routers/photos.py` 逐行核對）：

| 來源（`photos.py` 行號） | 內容 | 搬到哪 | 有沒有改 |
|---|---|---|---|
| 161〜181 | `with ai_timing.log_ai("vlm", …)` 到 `計時.note = (…6 段…)` | `_understand_and_embed` | **只改一處**：`raise HTTPException(422, …)` → `raise _NotUnderstood()` |
| 187、194 | `clamp_category` ＋「建議指向收件箱就存 NULL」 | `_insert_photo_with_files` | 只改判斷寫法（原本比 `suggested["is_inbox"]`，這裡比名稱，因為不必再回傳 `FolderOut`） |
| 201〜213 | `parse_content_time` ＋ `build_document` ＋ `with ai_timing.log_ai("embed", …)` | `_understand_and_embed` | 一字不動 |
| 215〜224 | `photo_repository.insert_photo(...)` 八個參數 | `_insert_photo_with_files` | 一字不動 |
| 227〜251 | `try: save_original / make_thumbnail / update_photo_paths … except: remove_if_exists ×2 ＋ delete_photo ＋ raise` | `_insert_photo_with_files` | 一字不動 |
| 253 | `logger.info("照片已入庫：…")` | `_run_image_job` | 加上 job_id、文案改指向待決定頁 |
| 255〜274 | `return UploadResponse(...)` | **不搬** | worker 不回應 HTTP。彈窗要的資料改由待決定頁自己去抓（design5 §1.1） |
| 171〜174 | `raise HTTPException(status_code=422, …)` | **不搬** | 這是本 phase 唯一「行為改變」的地方：不再是 422，而是「這次 attempt 失敗，再試」 |

### - [ ] 步驟 6：跑新測試，看它轉綠

```bash
pytest tests/integration/test_ingest_job.py -v
```

預期最後一行：`11 passed`。

### - [ ] 步驟 7：全量回歸

```bash
pytest -q
```

預期：**開工基線 ＋ 11**，全綠、0 skipped。
`app/api/routers/photos.py` 一個字都沒改，所以基線內既有的每一顆都不該動。

再驗一次「零外部依賴」（把 Ollama 指到一個死埠，顆數要一模一樣）：

```bash
OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q
```

預期：顆數與上一行相同。

### - [ ] 步驟 8：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/core/config.py app/services/ingest_job.py \
        tests/fakes.py tests/integration/test_ingest_job.py
git commit -m "feat: Phase 59 單圖入庫任務——run_ingest_job() 抽出 HTTP 無關的入庫流程，含 3 次看圖重試（看不懂與呼叫失敗都算）、失敗清 staging 與半成品、photo_ids 冪等擋崩潰重送，+11 tests"
```

---

## 5. ASCII 圖

### 5.1 單圖任務的完整流程（含三次重試迴圈與兩個出口）

```text
run_ingest_job(job_id, store=…, vlm=…, embeddings=…, now=…)
│
├─ job = store.get(job_id)
│     job is None ─────────────────────────────────▶ 【安靜結束】log 一行就好
│                                                     （過期或已被刪；殘檔交給 24h 掃把）
├─ store.update(status="analyzing")      ← design5 §4.4：開頭先改，面板才不會卡在 queued
│
├─ content_type 是 PDF？ ── 是 ──▶ 【Phase 60】_run_pdf_job(...)
│                          否
│                           ▼
├─ ① 冪等檢查：job["photo_ids"] 非空？
│        是 ──▶ 刪 staging ──▶ store.delete(job_id) ──▶ 【出口 A：成功（重送）】
│        否
│         ▼
├─ ② image_bytes = staging_service.read_staging(job_id, content_type)
│        （影像從磁碟來，**不從 Redis、不從 Celery 參數**）
│
├─ ③ folders / entities / corrections 各讀一次；inbox = 收件箱那筆
│
├─ ④ ┌───────────── 重試迴圈 for attempt in 1..VLM_MAX_ATTEMPTS(=3) ─────────────┐
│    │  store.update(status = attempt==1 ? "analyzing" : "retrying", attempt=n)  │
│    │                                                                           │
│    │  with log_ai("vlm"):  vlm.understand(bytes, ct, folders, entities, corr)  │
│    │        │                                                                  │
│    │        ├─ understood=False 或 text 全空白 ─▶ 這次失敗（ok=false）─┐        │
│    │        ├─ 丟例外（Ollama 沒開／雲端 401／逾時）─▶ 這次失敗 ───────┤        │
│    │        └─ 看得懂                                                  │        │
│    │              ▼                                                    │        │
│    │  build_document(category=收件箱名稱)                              │        │
│    │  with log_ai("embed"): embed_document(...)                        │        │
│    │        ├─ 丟例外 ─▶ 這次失敗（§8 第 6 列：算進 3 次）─────────────┤        │
│    │        └─ 成功 ─▶ return (understanding, embedding) ──── 跳出迴圈 │        │
│    │                                                                   │        │
│    │              第 1、2 次失敗 ─▶ continue（回迴圈頂端，attempt+1）◀──┘        │
│    │              第 3 次失敗   ─▶ 迴圈跑完 ─▶ return None                      │
│    └───────────────────────────────────────────────────────────────────────────┘
│         │                                    │
│    None │                    (understanding, │ embedding)
│         ▼                                    ▼
│    _fail(job_id,                    ⑤ _insert_photo_with_files(...)
│      "AI 看不懂這張照片（已試 3 次）")     ├ INSERT photo（收件箱、suggested_category）
│      ├ 刪 staging                          ├ save_original  → data/photos/{id}.png
│      ├ status="failed" + error             ├ make_thumbnail → data/thumbs/{id}.png
│      └ **不刪 job**（面板要顯示）          └ UPDATE 補三個路徑欄位
│         │                                    │
│         ▼                                    ├─ 任何一步炸掉：
│  【出口 B：失敗】                            │    remove_if_exists ×2
│   photo 表 0 列                              │    delete_photo(id)
│   staging 不在                               │    raise ─▶ 外面接住 ─▶ _fail(
│   job.status = "failed"                      │                "照片存檔失敗，這張沒有留下資料")
│   job.attempt = 3                            │              ─▶ 【出口 B：失敗】
│                                              └─ 三步都成功 ─▶ photo_id
│                                                   │
│                                                   ▼
│                                       ⑥ store.update(photo_ids=[photo_id])  ← 先寫這個
│                                          staging_service.remove_staging(...)
│                                          store.delete(job_id)
│                                                   │
│                                                   ▼
│                                           【出口 A：成功】
│                                            photo 表 +1（在收件箱）
│                                            staging 不在
│                                            job 不見了 → 面板那一列消失
│                                            待決定（N）+1
```

### 5.2 為什麼「崩潰重送」不會變成兩張照片

```text
情境：worker 已經把照片插進資料庫、也寫好檔，但就在「回報佇列說我做完了」之前被殺掉
     （Docker restart、機器沒電、`docker compose restart worker`……）
     佇列沒收到回報，就認定「這件事沒人做完」，把同一個任務再發一次。

┌─────────────── ✗ 錯誤做法：用 Celery autoretry_for 整份重跑 ───────────────┐
│                                                                            │
│  第 1 次   看圖 ✓ → 轉向量 ✓ → INSERT photo#41 ✓ → 寫檔 ✓ → 💥 被殺        │
│                                        └─ 資料庫裡已經有 photo#41 了       │
│                                                                            │
│  重送      整個任務函式從第一行再跑一次                                     │
│            看圖 ✓ → 轉向量 ✓ → INSERT photo#42 ✓ → 寫檔 ✓ → 完成           │
│                                        └─ 又插了一張！                      │
│                                                                            │
│  結果：待決定頁出現**兩張一模一樣的照片**，而且使用者要各歸類一次。          │
│        更糟的是這種 bug 只在「剛好被殺在那個時間點」才發生，很難重現。       │
└────────────────────────────────────────────────────────────────────────────┘

┌─────────────── ✓ 本 phase 的做法：photo_ids 當「我做過了」的收據 ───────────┐
│                                                                            │
│  第 1 次   看圖 ✓ → 轉向量 ✓ → INSERT photo#41 ✓ → 寫檔 ✓                  │
│                                    │                                       │
│                                    ▼                                       │
│                       store.update(photo_ids=[41])   ← **先蓋這個章**       │
│                                    │                                       │
│                                    ▼                                       │
│                       remove_staging() → store.delete() → 💥 被殺在這附近   │
│                                                                            │
│            JobStore 裡那筆 job 的內容：{... "photo_ids": [41] ...}          │
│                                                                            │
│  重送      run_ingest_job 一開頭：                                          │
│            store.update(status="analyzing")                                │
│            _run_image_job → ① if job["photo_ids"]:  ← 蓋過章了！            │
│                               刪 staging（可能已經不在，remove 吃得下）      │
│                               store.delete(job_id)                          │
│                               return   ← **一次圖都沒看、一列都沒插**       │
│                                                                            │
│  結果：照片仍然只有 photo#41 一張。重送是安全的。                            │
└────────────────────────────────────────────────────────────────────────────┘

還有一個很窄的縫：「INSERT 成功了，但 store.update(photo_ids=…) 還沒寫進去就被殺」。
那一瞬間重送確實會插出第二張。這是 side project 的取捨——要完全消滅它得讓
資料庫與 JobStore 在同一個交易裡，成本遠大於收益（design5 §13 的精神）。
本 phase 能做的是把那個縫**縮到最短**：INSERT／寫檔一結束就立刻蓋章，
中間不插任何其他動作。
```

---

## 6. 驗收清單

- [ ] `config.VLM_MAX_ATTEMPTS` 是 3：
      ```bash
      python -c "from app.core import config; assert config.VLM_MAX_ATTEMPTS == 3; print('OK')"
      ```
      預期印出 `OK`
- [ ] `ingest_job.py` **沒有** import fastapi、celery、redis：
      ```bash
      grep -nE "^(import|from) +(fastapi|celery|redis)" app/services/ingest_job.py || echo "OK：沒有任何 HTTP／佇列的 import"
      ```
      預期印出 `OK：沒有任何 HTTP／佇列的 import`
      （⚠ 不要改成 grep 字串 `HTTPException`——模組 docstring 為了解釋設計，**刻意寫著**
      「這裡沒有 HTTPException」這幾個字，直接 grep 字面會誤中說明文字、永遠印不出 OK。
      只查 import 行就夠：真的引進 fastapi 一定有一行 `from fastapi import …`。）
- [ ] SQL 仍只出現在 repository（跑既有的自動化掃碼那一顆）：
      ```bash
      pytest tests/integration/test_design3_error_paths.py -k "SQL只出現在repository" -v
      ```
      預期 `1 passed`。（它掃的是 `psycopg`／`get_connection`／`cursor(`／`.execute(`
      這些「真的在開連線、送 SQL」的關鍵字。⚠ 不要自己 grep 大寫的 `UPDATE ` 之類——
      `photos.py` 的註解本來就寫著「一條 UPDATE 同時寫…」、本 phase 的
      `_insert_photo_with_files` docstring 也寫著「INSERT → … → UPDATE 補路徑」，
      字面 grep 會誤中說明文字，看起來像違規其實不是。）
- [ ] `photos.py` 與 `camera.py` **一個字都沒改**：
      ```bash
      git diff --stat app/api/routers/photos.py app/api/routers/camera.py
      ```
      預期：**無輸出**
- [ ] 重試上限接上了：
      ```bash
      grep -n "range(1, config.VLM_MAX_ATTEMPTS + 1)" app/services/ingest_job.py
      ```
      預期恰好一行（重試迴圈只有一份，在 `_understand_and_embed` 裡）
- [ ] 計時 log 接上了，而且**兩處都帶 `target=`**：
      ```bash
      grep -n -A2 "ai_timing.log_ai(" app/services/ingest_job.py
      ```
      預期兩組——第一組下一行是 `"vlm", target=vlm_service.vlm_timing_target(vlm)`，
      第二組接著 `"embed",` 與 `target=indexing_service.embedding_timing_target(embeddings),`。
      （`log_ai(` 與 kind 字串不在同一行，直接 grep `log_ai("vlm"` 會一無所獲。
      `target=` 不能省：worker 是另一個行程，不帶 target 的話 `ai_timing` 會退回讀
      worker 自己的 `config.AI_BACKEND`——那永遠是 `local`，log 會騙人，
      ★G2 第 5 條「worker log 顯示 backend=cloud」的驗收就永遠過不了。）
- [ ] 清理路徑照舊（三件事都在，順序不變）：
      ```bash
      grep -n "storage_service.remove_if_exists\|photo_repository.delete_photo\|raise$" app/services/ingest_job.py
      ```
      預期恰四行、行號由小到大：`storage_service.remove_if_exists(original_path)` →
      `storage_service.remove_if_exists(thumbnail_path)` → `photo_repository.delete_photo(photo_id)` →
      單獨一行的 `raise`（帶模組前綴才不會誤中「remove_if_exists 吃得下 None」那行註解）
- [ ] worker 不會自己釘實體、建待辦、建資料夾（design5 §4.2）：
      ```bash
      grep -nE "create_entity|pin_entity|create_and_pin_entity|create_task|create_folder|update_photo_folder" app/services/ingest_job.py || echo "OK：worker 不做人該做的決定"
      ```
      預期印出 `OK：worker 不做人該做的決定`
- [ ] `pytest tests/integration/test_ingest_job.py -v` → `11 passed`
- [ ] 三次失敗之後，磁碟與資料庫都乾淨（測試已釘，但親自看一次更安心）：
      ```bash
      pytest tests/integration/test_ingest_job.py -k "三次都看不懂" -v
      ```
      預期 `1 passed`
- [ ] 崩潰重送那顆真的在跑：
      ```bash
      pytest tests/integration/test_ingest_job.py -k "崩潰重送" -v
      ```
      預期 `1 passed`
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ 開工基線 ＋ **11**
- [ ] 零外部依賴實證：`OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q` 顆數相同
- [ ] 端點數**沒變**（本 phase 不碰任何 router）：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `20`
- [ ] 專案的 `data/` 沒有被弄髒：
      ```bash
      ls data/staging 2>/dev/null || echo "OK：沒有 staging 殘留"
      ```
      預期印出 `OK：沒有 staging 殘留`（`data/` 不入版控，`isolated_data_dir` 讓 pytest
      全寫在暫存目錄；專案 `data/` 底下**不該**因為跑測試而多出 staging 目錄）

---

## 7. 常見陷阱

1. **把 `now` 當成值用，結果把函式物件寫進資料庫。**
   `dependencies.get_now()` 在 router 裡是被 `Depends()` **呼叫過**才進參數的（`now: datetime | None = Depends(get_now)`），
   所以 router 收到的是「值」。但 `run_ingest_job` 收到的是**函式本身**（契約備忘 §3.3：「callable 回 datetime」）。
   寫成 `uploaded_at=now` 會把 `<function get_now>` 塞進 SQL 參數。
   **症狀**：`psycopg` 丟 `ProgrammingError: cannot adapt type 'function'`，或測試裡上傳時間變成一串奇怪的東西。
   **正解**：一定寫 `now()`。

2. **在 worker 裡呼叫 `dependencies.get_vlm()`，雲端開關永遠失效。**
   `get_vlm()` 讀的是 `config.AI_BACKEND`，那是 **web 行程記憶體裡**的變數。
   worker 是另一個行程，它的 `config.AI_BACKEND` 永遠是啟動時的預設值 `"local"`。
   **症狀**：頁首明明切到雲端、上傳卻慢得像本機，而且 log 的 `backend=local`。
   **正解**：本 phase 的 `run_ingest_job` **不呼叫** `get_vlm()`——`vlm` 是參數。
   Phase 65 的 Celery 任務要照 `job["ai_backend"]` 這張快照自己 `OllamaVLM()` 或 `OllamaCloudVLM()`（design5 D14）。

3. **用 Celery 的 `autoretry_for` 取代內部迴圈。**
   看起來更「正統」，但會把已經 INSERT 的照片再插一次（§5.2 的圖）。
   design5 §4.4 明文禁止。本 phase 連 Celery 都還沒裝，但 Phase 65 寫任務時很容易順手加上，
   所以現在就把理由寫在 `ingest_job.py` 的模組 docstring 裡。

4. **`ScriptedVLM` 的劇本長度寫錯，測試變成「不知道在測什麼」。**
   劇本寫 4 個而程式只呼叫 3 次 → 測試會綠，但根本沒驗到上限。
   所以每顆重試測試都要**同時**斷言 `vlm.calls == 3`，不能只看資料庫結果。
   反過來，劇本寫 2 個而程式呼叫 3 次 → `AssertionError: ScriptedVLM 被呼叫第 3 次…`，這是好事（上限沒守住）。

5. **忘記 `staging` 也寫在 `config.DATA_DIR` 底下。**
   `isolated_data_dir` 會把 `DATA_DIR` 指到暫存目錄，所以測試裡的 staging 檔也在暫存目錄。
   如果你在測試裡自己組路徑（例如寫死 `Path("data/staging/job-1.png")`），
   **症狀**：測試在你的機器上綠、在別人的機器上把專案 `data/` 弄髒，或是 `FileNotFoundError`。
   **正解**：一律用 `staging_service.staging_path(job_id, content_type)`。

6. **`_NotUnderstood` 寫在 `with` 區塊外面，計時 log 的 `ok=` 就會說謊。**
   `ai_timing.log_ai` 是靠「with 區塊裡有沒有例外」決定結束行標 `ok=true` 還是 `ok=false`。
   把「看不懂就 raise」搬到 `with` 外面，那一行會變成 `ok=true`，之後 grep log 找失敗會找不到。
   這與現在 `_ingest_image` 把 422 寫在 `with` 裡面是同一個理由（`photos.py` 第 158〜160 行的註解已經解釋過）。

7. **`except Exception` 把 `_NotUnderstood` 也一起吃掉，導致 log 出現一堆假 traceback。**
   Python 的 `except` 是**由上往下**比對的，所以 `except _NotUnderstood:` 一定要寫在 `except Exception:` **前面**。
   順序寫反不會壞掉，但每次「AI 說看不懂」都會印出一整段 traceback，真的壞掉時反而看不出來。

8. **在 `_run_image_job` 裡先刪 staging 再寫 `photo_ids`。**
   順序反了，「剛好被殺在中間」的重送會：staging 沒了 → `read_staging` 丟 `FileNotFoundError` → 任務再失敗一次 → job 被標 failed，
   但資料庫裡其實**已經有那張照片**。使用者會看到「面板說失敗、待決定卻多一張」。
   **正解**：`store.update(photo_ids=…)` → `remove_staging(…)` → `store.delete(…)`，順序不可對調。

9. **想順手把 `photos.py` 的 `_ingest_image` 刪掉「免得重複」。**
   現在 `POST /photos` 與 `POST /camera/{token}/photos` 都還靠它。刪掉會讓 405 顆測試裡的上傳部分全紅，
   而且你會同時在改「入庫邏輯」與「API 契約」兩件事，出問題時分不出是誰。
   短暫的重複是**刻意**的，Phase 62／63 把兩個呼叫端改完之後才動它。

10. **拿到 job 之後直接改它的欄位（例如 `job["status"] = "failed"`），以為會寫回 store。**
    不會。Phase 57 的 `InMemoryJobStore` **刻意**讓 `get()`／`update()`／`list_open()` 都回傳
    獨立副本（`_copy()`，連 `photo_ids` 清單都另外複製），就是為了跟 `RedisJobStore`
    （每次從 Redis 讀字串再解析，天生是副本）行為一致——改副本，兩種實作都**安靜地什麼都沒改**。
    **症狀**：斷言時發現 store 裡的狀態跟你「改過」的不一樣，看起來像 store 壞了。
    **正解**：一律走 `store.update(job_id, 欄位=值)`。本 phase 的程式碼已經全部這樣寫，維持它。

11. **`docker compose ps` 沒看 db 就直接跑 pytest。**
    db 沒起來時，這 11 顆測試會全部紅在連線錯誤，看起來像「程式寫錯了」。
    先 `docker compose ps` 確認 `db` 是 `Up (healthy)`。

---

## 8. 完成後的專案狀態

系統多了一個**沒有人呼叫**的函式 `run_ingest_job()`——這是刻意的。
它把「一張照片怎麼從暫存檔變成收件箱裡的一列」完整地表達了一次，
而且完全不依賴 FastAPI、Celery 或 Redis：四個依賴全部從參數進來，
所以 pytest 可以直接呼叫它、Celery 之後也可以直接呼叫它。

重試（3 次，含第一次）、失敗清理（staging ＋ 半成品檔案 ＋ 資料列）、
崩潰重送的冪等（`photo_ids` 當收據）都已經被 11 顆測試釘死。

`POST /photos` 仍然是同步的 201，`_ingest_image()` 仍然是它的正式路徑——
**對外行為在本 phase 一個字都沒變**。

接下來 **Phase 60** 在同一個檔案加上 PDF 路徑（一個任務處理整份檔、逐頁各 3 次、
失敗跳頁、`pages_done` 續跑），**Phase 61** 讓 worker 在 INSERT 時把實體／待辦建議也寫進去，
之後 **Phase 62** 才真的把 `POST /photos` 改成 202（並刪掉從此沒人用的 `_ingest_pdf` 那一組）；
`_ingest_image` 與 `UploadResponse` 因為鏡頭端點還在用，要到 **Phase 63** 才正式退休。

測試累計 ＝ 開工基線 ＋ **11**。
