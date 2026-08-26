# Phase 58：staging 暫存區服務

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候（順便算檔案雜湊、順便壓縮、順便做磁碟容量上限、順便排一個每小時跑的清理排程……），答案一律是「不要」。

> 🎯 **一句話目標：** 做出「檔案在等 worker 看圖的這段時間，先放在哪裡」這一層——寫進去、讀回來、刪掉，外加一支「24 小時掃把」把崩潰後留下來的孤兒檔清掉。

**為什麼要做這個：**

增量五把上傳改成非同步。使用者按下上傳之後，流程長這樣：

```text
HTTP 請求進來（手上有一份影像位元組）
   → 檢查格式（不是 JPEG／PNG／PDF 就 415，什麼都不做）
   → 把位元組**存到某個地方**       ← 這個 phase 要做的就是這一步
   → JobStore 記一筆 queued
   → 把任務丟進佇列
   → 回 202「收下了」，HTTP 結束

（幾十秒到幾分鐘之後）
worker 從佇列拿到這個任務
   → **從剛剛那個地方把位元組讀回來**  ← 也是這個 phase
   → 送去 VLM 看圖 → embedding → INSERT → 存原圖＋縮圖
   → **把暫存的那份刪掉**             ← 還是這個 phase
```

中間那個「某個地方」就是 **staging（暫存區）**：`data/staging/`。

**為什麼不能直接把位元組塞進 Redis 或當成 Celery 任務的參數？** design5.md §4.1 明文禁止，§1.2 也把「影像位元組當 Celery 參數／塞 Redis」列在被否決的方案裡。理由：

- **太大。** 一份多頁 PDF 動輒幾十 MB。Redis 是把資料放在**記憶體**裡的，塞幾份大檔進去就開始吃掉整台機器的記憶體。
- **Celery 的任務參數會被序列化成 JSON 再存進 Redis。** 二進位位元組沒辦法直接放進 JSON，要先做 base64 編碼，體積再脹三分之一，而且每次取任務都要解一次碼。
- **磁碟本來就在那裡。** 原圖與縮圖本來就存在 `data/photos`／`data/thumbs`（Phase 17 做的），staging 只是多一個同層的資料夾，app 與 worker 靠同一個 bind-mount 看到同一份磁碟（Phase 66 會把 `./data` 掛給 worker）。

**那「掃把」又是要幹嘛的？** 正常情況下 staging 檔一定會被刪掉——成功入庫刪、最終失敗也刪（design5 §4.1）。但如果 worker 在半路被殺掉（機器重開、Docker 重啟、Redis 的 volume 掉了），那個檔就會變成**沒有人記得的孤兒**：JobStore 裡查不到它、佇列裡也沒有它的任務，它就會永遠躺在磁碟上。掃把就是後悔藥：**檔案超過 24 小時沒動過、而且 JobStore 已經不記得它了 → 當垃圾刪掉**。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| staging（暫存區） | 「東西暫時放這裡等下一步處理」的地方。本專案指 `data/staging/`，放的是還沒被 VLM 看過的原始檔 |
| 孤兒檔（orphan） | 沒有任何人記得、也不會有人來處理的檔案。崩潰之後留下來的 staging 檔就是 |
| mtime（modification time，最後修改時間） | 作業系統幫每個檔案記的「最後一次被寫入是什麼時候」。我們用它判斷檔案幾歲 |
| epoch 秒數（timestamp） | 電腦記時間的方式：從 1970-01-01 00:00:00 UTC 到現在經過幾秒（一個小數）。`path.stat().st_mtime` 回的就是它，`datetime.timestamp()` 也是回這個 |
| 掃把（sweeper） | 本文件對 `sweep_stale_staging()` 的口語稱呼。「定時掃一遍、把垃圾掃掉」的那種函式 |
| seam（接縫 / 注入點） | 「為了讓測試能替換掉某個東西，而刻意留的一個口」。本專案的 `get_now()` 就是時間的 seam；`sweep_stale_staging(..., now=...)` 也是同一招 |
| `Path` | Python 內建 `pathlib` 的路徑物件。可以用 `/` 接路徑、可以問 `.exists()`、可以 `.mkdir()` |
| `unlink(missing_ok=True)` | 刪檔案；`missing_ok=True` ＝「本來就不存在也算成功」，不會爆錯 |
| `os.utime(path, (atime, mtime))` | 手動把一個檔案的時間戳改掉。測試用它假造「這個檔是 25 小時前寫的」 |
| `tmp_path` | pytest 內建的 fixture，**每個測試函式**自動拿到一個獨立的空暫存資料夾（測完 pytest 會自己清掉） |
| autouse fixture | pytest 的「每個測試都自動套用的前置／後置動作」，不必寫在測試函式的參數列 |
| `.gitignore` | 告訴 git「這些檔案不要納入版本控制」的清單檔 |

---

## 1. 對應 design5.md 章節

- **§4.1「Staging」**（本 phase 的主要依據，逐條）：
  - 路徑 `data/staging/{job_id}`，副檔名依 content type（`.jpg`／`.png`／`.pdf`）
  - `data/` 已在 `.gitignore`；staging 同樣不入版控
  - **禁止**把檔案內容放進 Redis 或 Celery 參數；任務 payload 只帶路徑、content type、檔名、`ai_backend` 快照、來源
  - 成功入庫或最終失敗，都刪 staging
  - **worker／app 啟動時掃 staging：檔案 mtime 超過 24 小時且 JobStore 沒有對應進行中任務 → 當垃圾刪掉**（崩潰後 Redis 也丟了的後悔藥）
- **D7「立刻 202」**：HTTP 只做格式檢查、落 staging、入列。
- **D10／D12**：3 次都失敗 → 整筆拿掉（刪 staging）；PDF 0 頁成功 → 同樣刪 staging。
- **§1.2 被否決**：「影像位元組當 Celery 參數／塞 Redis」——多頁 PDF 太大；staging 走磁碟。
- **§8 錯誤表第 8 列**：Redis 當下掛了 → HTTP 500，**最好連 staging 也別留**（先 staging 再入列的話，失敗路徑要刪 staging）——那條失敗路徑用的就是本 phase 的 `remove_staging()`（實際接線是 Phase 62）。
- **§13 風險**：Redis volume 丟了最多丟進度列與尚未分析的 staging 對應關係；**24 小時掃把會清孤兒檔**。
- 契約備忘 **§3.2**（`STAGING_SUBDIR`／`STAGING_MAX_AGE_HOURS`／五個函式的逐字簽章、副檔名對照）、**§2.1**／**§2.3**（檔名）。

---

## 2. 前置條件

**依賴的 phase：Phase 57（JobStore 與測試安全網）。**

為什麼一定要先做 57：本 phase 的掃把簽章是 `sweep_stale_staging(store: JobStore, ...)`——它要問 JobStore「你還記得這個 job 嗎」。而且掃把的測試需要 Phase 57 那道 `wire_memory_job_store` 安全網來拿一個乾淨的 store。

開工前**實查**：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① Phase 57 真的做完了嗎？
ls -l app/services/ingest_job_store.py
grep -c "@pytest.fixture(autouse=True)" tests/conftest.py     # 要是 4

# ② 資料庫容器活著嗎？db 那一列要是 Up (healthy)
docker compose ps

# ③ 測試基線
pytest -q
```

`grep -c` 要印 `4`（四道安全網都在）。基線顆數以你**當下實查到的數字**為準，本文件之後一律稱它「基線」（若 56 → 57 → 58 依序做，這裡會是 `422 passed` ＝ 405 ＋ Phase 56 的 5 ＋ Phase 57 的 12）。

**⚠️ 絕對不要同時跑兩份 pytest。**（理由見 Phase 56 §2。）

---

## 3. 範圍

### 做

1. 新建 `app/services/staging_service.py`：三個常數（`STAGING_SUBDIR`／`STAGING_MAX_AGE_HOURS`／`STAGING_EXTENSIONS` 副檔名對照）＋ 六個函式（五個契約函式＋`staging_dir()` 小工具）——逐字內容全在步驟 2。（「契約備忘」是規劃階段的工作文件、未入庫，驗收以本檔內嵌內容為準；2026-08-25 核對時修正常數與函式的數法。）
2. 新建 `tests/unit/test_staging_service_unit.py`（10 顆）。
3. 驗證 `.gitignore` 的 `data/` 一行已經涵蓋 `data/staging/`（**不必新增任何一行**，但要真的驗一次）。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 把掃把接到 app／worker 的啟動流程 | **程式接線全部在 Phase 65**（`app/main.py` 加 lifespan 掃一次＋`app/celery_app.py` 的 `worker_ready` 訊號掃一次），**Phase 66** 再讓 worker 容器真的跑起來。本 phase 只寫函式與測試——現在還沒有 worker 可以接，而函式寫好沒人叫＝沒有效果，**接線那兩處少一處都是安靜壞掉**，所以 Phase 65 的驗收清單自己會釘 |
| 讓 `POST /photos` 真的呼叫 `save_staging()` | 那是 **Phase 62**。本 phase 對外行為零改變，端點仍是 20 |
| 讓 `run_ingest_job()` 呼叫 `read_staging()` | 那是 **Phase 59／60**。本 phase 還沒有任務本體 |
| 把影像位元組放進 Redis／Celery 參數 | design5 §4.1 明文禁止、§1.2 已否決。這正是本 phase 存在的原因 |
| 檔案內容驗證（真的用 Pillow 打開看看是不是圖） | staging 只是**搬位元組**，一個 byte 都不解讀。是不是真的圖要到 worker 那一步才知道（壞檔＝VLM／Pillow 那邊爆錯 → 算一次失敗，design5 錯誤表 3／5） |
| 算檔案雜湊、去重、壓縮 | design5 沒有要求。多做的每一樣都要多一份程式、多一組測試 |
| 磁碟容量上限、寫滿了怎麼辦 | 沒有需求。真的寫滿就是 `OSError`，由 Phase 62 的 500 路徑處理 |
| 排一個「每小時自動跑」的清理排程 | design5 §4.1 講得很清楚：**app／worker 啟動時各掃一次**。不做 cron、不做 Celery beat |
| 讓掃把把 `data/photos`／`data/thumbs` 也掃一遍 | 那兩個資料夾是**正本**，不是暫存。掃它們＝有機會刪掉真照片 |
| 讓掃把刪掉子資料夾 | staging 底下不該有子資料夾。真的出現了就跳過（`is_file()` 過濾），不要遞迴刪 |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1 先把測試寫好、跑到**紅**；步驟 2 才動實作讓它轉綠。

### 步驟 1：先寫測試（紅）

- [ ] 新建 `/Users/linjunting/personalDocAI/tests/unit/test_staging_service_unit.py`，整份貼上：

```python
"""staging_service 的單元測試：真的寫檔案，但只寫到 tmp_path；不碰資料庫、不碰網路。

design5.md §4.1：
  - 路徑 data/staging/{job_id}，副檔名依 content type（.jpg／.png／.pdf）
  - 成功入庫或最終失敗都刪 staging
  - 啟動時掃一次：mtime 超過 24 小時 **且** JobStore 沒有對應任務 → 當垃圾刪掉

conftest 的 isolated_data_dir 這道 autouse 安全網已經把 config.DATA_DIR 指到
pytest 的暫存資料夾，所以本檔的每一次寫檔都落在 tmp_path 底下，
**永遠不會弄髒專案的 data/**（那裡是真照片的正本，不入版控＝全世界只有一份）。
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest

from app.core import config
from app.services import staging_service
from tests.fakes import make_pdf_bytes, make_png_bytes


def _age(path, hours: float) -> None:
    """把一個檔案的最後修改時間往回撥 hours 小時（假造「這個檔很舊了」）。

    os.utime(path, (atime, mtime)) 兩個值分別是「最後讀取時間」與「最後修改時間」，
    單位都是 epoch 秒數（從 1970-01-01 到現在經過幾秒）。
    """
    moment = time.time() - hours * 3600
    os.utime(path, (moment, moment))


def _create_job(store, job_id: str) -> None:
    """在 JobStore 裡登記一筆，代表「這個檔還有人記得」。"""
    store.create(
        job_id=job_id,
        filename=f"{job_id}.png",
        content_type="image/png",
        ai_backend="local",
        source="upload",
    )


def test_測試期間staging寫在暫存目錄不會弄髒專案的data(tmp_path):
    """安全網本身也要有測試（比照 test_storage_service_unit 的第一顆）。"""
    assert config.DATA_DIR == tmp_path / "data"
    assert staging_service.staging_dir() == tmp_path / "data" / "staging"


def test_副檔名對照三種():
    """圖片兩種＋PDF 一種，與 config.ALLOWED_CONTENT_TYPES 一致（design5.md §4.1）。

    ★ 副檔名帶點（.jpg），與 storage_service.EXTENSIONS（不帶點的 "jpg"）不同——
      那邊是拿去組字串路徑，這邊是直接接在檔名後面。所以常數名字也刻意不一樣。
    """
    assert staging_service.staging_path("j1", "image/jpeg").name == "j1.jpg"
    assert staging_service.staging_path("j2", "image/png").name == "j2.png"
    assert staging_service.staging_path("j3", "application/pdf").name == "j3.pdf"


def test_不支援的content_type直接爆錯():
    """router 早就在格式檢查擋掉了（415）；真的走到這裡代表有 bug，不要默默給預設值。"""
    with pytest.raises(KeyError):
        staging_service.staging_path("j1", "image/gif")


def test_寫進去讀得回來而且位元組一模一樣():
    """staging 只是搬位元組，一個 byte 都不會被改動。

    這裡用真的 PNG 只是為了逼真；staging 從頭到尾不解碼影像，
    所以就算餵假位元組也會通過（與 storage_service 的縮圖不同，那邊會真的用
    Pillow 打開，假位元組會炸 UnidentifiedImageError）。
    """
    原始 = make_png_bytes(1200, 600)

    路徑 = staging_service.save_staging("job-1", "image/png", 原始)

    assert 路徑.is_file()
    assert 路徑 == config.DATA_DIR / "staging" / "job-1.png"
    assert staging_service.read_staging("job-1", "image/png") == 原始


def test_PDF也存得進去():
    """一份 PDF ＝一個 job ＝一個 staging 檔（design5.md D11：一檔一任務）。"""
    原始 = make_pdf_bytes(pages=2)

    路徑 = staging_service.save_staging("job-pdf", "application/pdf", 原始)

    assert 路徑.name == "job-pdf.pdf"
    assert staging_service.read_staging("job-pdf", "application/pdf") == 原始


def test_remove_staging刪得掉():
    """成功入庫與最終失敗都會呼叫它（design5.md §4.1）。"""
    路徑 = staging_service.save_staging("job-1", "image/png", b"whatever")
    assert 路徑.is_file()

    staging_service.remove_staging("job-1", "image/png")

    assert not 路徑.exists()


def test_remove_staging對不存在的檔不炸():
    """崩潰重送時，檔可能已經被上一輪刪掉了；再刪一次不可以爆錯
    （與 storage_service.remove_if_exists 同一個精神）。"""
    staging_service.remove_staging("從來沒有過的 job", "image/png")
    staging_service.remove_staging("從來沒有過的 job", "application/pdf")

    路徑 = staging_service.save_staging("job-1", "image/png", b"whatever")
    staging_service.remove_staging("job-1", "image/png")
    staging_service.remove_staging("job-1", "image/png")   # 第二次
    assert not 路徑.exists()


def test_掃把只刪又舊又沒有job的檔(wire_memory_job_store):
    """四種組合只有一種該被刪：**又舊、又沒人記得**（design5.md §4.1）。

    新檔一律不動——它可能是「一秒前才收下、worker 還沒撿到」的正常檔案。
    有 job 的一律不動——JobStore 還記得它，代表這件事還沒了結
    （排隊排很久、長 PDF 還在跑，或異常中斷後還沒收拾完）。
    """
    store = wire_memory_job_store

    新檔有job = staging_service.save_staging("new-with-job", "image/png", b"a")
    新檔沒job = staging_service.save_staging("new-no-job", "image/png", b"b")
    舊檔有job = staging_service.save_staging("old-with-job", "image/png", b"c")
    舊檔沒job = staging_service.save_staging("old-no-job", "image/png", b"d")

    _age(舊檔有job, 25)
    _age(舊檔沒job, 25)
    _create_job(store, "new-with-job")
    _create_job(store, "old-with-job")

    刪掉幾個 = staging_service.sweep_stale_staging(store)

    assert 刪掉幾個 == 1
    assert 新檔有job.exists(), "才剛收下，不可以刪"
    assert 新檔沒job.exists(), "還很新，可能是剛落地還沒入列，不可以刪"
    assert 舊檔有job.exists(), "JobStore 還記得它（排了很久的隊、或長 PDF 還在跑），不可以刪"
    assert not 舊檔沒job.exists(), "又舊又沒人記得＝孤兒檔，這一種才該刪"


def test_掃把用注入的now判斷幾歲(wire_memory_job_store):
    """now 是時間的注入點（seam），比照專案既有的 get_now()。

    有了它，測試不必等 24 小時、也不必每次都去改檔案的 mtime，
    直接把「現在」往後撥就好。
    """
    檔 = staging_service.save_staging("job-1", "image/png", b"a")

    # 用真正的現在掃：檔案是幾毫秒前寫的，還很新
    assert staging_service.sweep_stale_staging(wire_memory_job_store) == 0
    assert 檔.exists()

    # 把「現在」往後撥 25 小時再掃一次：同一個檔就變成孤兒垃圾了
    未來 = datetime.now() + timedelta(hours=25)
    assert staging_service.sweep_stale_staging(wire_memory_job_store, now=未來) == 1
    assert not 檔.exists()


def test_staging目錄還不存在時掃把回0(wire_memory_job_store):
    """全新環境（或剛重建 data/）第一次啟動就會遇到這個情況，不可以爆錯。"""
    assert not staging_service.staging_dir().exists()

    assert staging_service.sweep_stale_staging(wire_memory_job_store) == 0
```

- [ ] 跑一次，看它紅：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_staging_service_unit.py -q
```

預期：**collection error**（收集測試時 import 就倒了，一顆都跑不起來），訊息是

```
ImportError: cannot import name 'staging_service' from 'app.services' (/Users/linjunting/personalDocAI/app/services/__init__.py)
```

**這就是紅燈，正確。**（不是 `ModuleNotFoundError`——`app/services/` 是一個有 `__init__.py` 的套件，`from` 套件 `import` 一個不存在的子模組，Python 3.12 給的是上面這句，2026-08-25 實測過。）

---

### 步驟 2：實作（綠）——新建 `app/services/staging_service.py`

- [ ] 新建 `/Users/linjunting/personalDocAI/app/services/staging_service.py`，整份貼上：

```python
"""入庫任務的暫存區（staging）：檔案在等 worker 看圖的這段時間放哪裡。

【這個模組解決什麼問題】
增量五把上傳改成非同步：HTTP 只做格式檢查、把檔案放好、入列，然後立刻回 202
（design5.md D7）。真正看圖是幾十秒到幾分鐘之後、由另一個行程（worker）做的。
所以那份影像位元組必須先「放在某個 app 與 worker 都看得到的地方」——就是這裡。

【為什麼放磁碟，不放 Redis／不當 Celery 參數】
design5.md §4.1 明文禁止，§1.2 也把它列在被否決的方案裡：
  * 太大：一份多頁 PDF 動輒幾十 MB，而 Redis 是把資料放在**記憶體**裡的。
  * Celery 的任務參數會被序列化成 JSON 再存進 Redis，二進位要先 base64
    （體積脹三分之一，每次取任務還要解一次碼）。
  * 磁碟本來就在那裡：原圖與縮圖本來就在 data/photos／data/thumbs，
    staging 只是同一層多一個資料夾，app 與 worker 共用同一個 bind-mount。
所以任務 payload 只帶 job_id，位元組由 worker 自己從這裡讀回來
（契約備忘 §3.3：run_ingest_job() **不吃影像位元組**，只吃 job_id）。

【與 storage_service 的分工】
  storage_service ＝ **正本**。原圖 data/photos/{photo_id}、縮圖 data/thumbs/{photo_id}，
                     檔名用資料庫的 photo.id，路徑會被寫進資料庫。
  staging_service ＝ **暫存**。data/staging/{job_id}，檔名用 job_id（照片還不存在，
                     沒有 photo.id 可用），路徑**不進資料庫**、不外送給前端。
                     成功入庫或最終失敗都會被刪掉，不留痕跡。

分層：本模組只做檔案操作，不碰資料庫、不碰 HTTP、不解讀影像內容。
      誰在什麼時候呼叫它，由 api/routers/photos.py（Phase 62）與
      services/ingest_job.py（Phase 59／60）決定。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core import config
from app.services.ingest_job_store import JobStore

# data/ 底下的子資料夾名稱。與 storage_service 的 photos／thumbs 同一層。
STAGING_SUBDIR = "staging"

# 孤兒檔的年齡門檻（小時）。design5.md §4.1 明訂 24。
# ★ 目前只有這一個定義處。日後若真的需要用 .env 覆蓋它（契約備忘 §3.6 提過
#   config.py 也可以放一份），做法是**搬過去**、這裡改讀 config.STAGING_MAX_AGE_HOURS，
#   而不是兩邊各留一份——兩份一定會漂移。
STAGING_MAX_AGE_HOURS = 24

# content_type → 副檔名（**帶點**）。三種與 config.ALLOWED_CONTENT_TYPES 一致。
# ★ 名字刻意不叫 EXTENSIONS：storage_service 已經有一個同名常數，
#   但那邊的值不帶點（"jpg"）而且沒有 PDF（PDF 在 router 就被逐頁換成 PNG 了）。
#   兩個檔案放兩個同名不同值的常數，遲早有人複製貼上出事。
STAGING_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}


def staging_dir() -> Path:
    """暫存區的實際位置：config.DATA_DIR / "staging"。

    每次呼叫都重新讀 config.DATA_DIR（不在 import 時定死），
    測試才能用 conftest 的 isolated_data_dir 把它指到暫存目錄
    ——與 storage_service.absolute_path 完全同一個理由。
    """
    return Path(config.DATA_DIR) / STAGING_SUBDIR


def staging_path(job_id: str, content_type: str) -> Path:
    """這個 job 的暫存檔該叫什麼、放哪裡：data/staging/{job_id}.jpg|.png|.pdf。

    回的是**實際路徑（Path）**，不是「data/ 開頭的相對字串」——
    因為這個值不會被寫進資料庫，只在行程內傳來傳去
    （storage_service 回相對字串是為了存進 DB，這裡沒有這個需求）。

    清單外的 content_type 早在 router 的格式檢查（415）就被擋掉了；
    真的走到這裡代表有 bug，讓 KeyError 直接炸出來，不要默默給預設值
    （與 storage_service._ext 同一個原則）。
    """
    return staging_dir() / f"{job_id}{STAGING_EXTENSIONS[content_type]}"


def save_staging(job_id: str, content_type: str, data: bytes) -> Path:
    """把上傳進來的位元組原封不動寫成暫存檔，回傳它的實際路徑。

    不轉檔、不壓縮、不驗證內容——使用者送什麼就存什麼。
    「這到底是不是一張看得懂的圖」要到 worker 送 VLM 那一步才知道
    （壞檔＝那一次失敗，算進 3 次重試，design5.md 錯誤表 3／5）。
    """
    target = staging_path(job_id, content_type)
    # parents=True ＝中間缺的上層資料夾也一併建；exist_ok=True ＝已存在就當作成功
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def read_staging(job_id: str, content_type: str) -> bytes:
    """把暫存檔讀回來。worker 每次要送 VLM 之前都會呼叫它。

    檔案不在時直接讓 FileNotFoundError 炸出來，不吞錯：
    走到這裡代表「JobStore 說有這個任務，但檔案不見了」，
    那是真的出事了（有人手動刪了 data/staging，或掃把誤刪），
    應該讓它變成一次明確的失敗，而不是安靜地當作空檔繼續跑。
    """
    return staging_path(job_id, content_type).read_bytes()


def remove_staging(job_id: str, content_type: str) -> None:
    """刪掉暫存檔；檔案本來就不在也當作成功（比照 storage_service.remove_if_exists）。

    三種情況都會呼叫它，而且都有可能「檔案已經不在了」：
      1. 成功入庫之後（design5.md §4.1）
      2. 3 次都失敗、整筆放棄之後（D10、錯誤表 3／5）
      3. 入列失敗的清理路徑——先寫 staging 再入列，Redis 掛掉時要把檔刪掉
         （錯誤表第 8 列；接線在 Phase 62）
    崩潰重送時第 1 種會再跑一次，那時檔早就沒了，不可以再爆一次錯。
    """
    staging_path(job_id, content_type).unlink(missing_ok=True)


def sweep_stale_staging(store: JobStore, *, now: datetime | None = None) -> int:
    """把孤兒暫存檔掃掉，回傳刪了幾個。app 與 worker 啟動時各跑一次（design5.md §4.1）。

    【這是後悔藥，不是正常流程】
    正常情況下 staging 檔一定會被 remove_staging() 刪掉（成功刪、最終失敗也刪）。
    但如果 worker 在半路被殺掉（機器重開、Docker 重啟、Redis 的 volume 掉了），
    那個檔就變成**沒有人記得的孤兒**：JobStore 查不到它、佇列裡也沒有它的任務，
    它會永遠躺在磁碟上。這支函式就是來收這種尾的（design5.md §13）。

    【刪除條件：兩個都成立才刪】
      ① 檔案的 mtime（最後修改時間）超過 STAGING_MAX_AGE_HOURS 小時
      ② JobStore 裡查不到同名的 job
    只滿足一個都不刪，理由：
      * 又新又沒 job → 有可能是「這一毫秒剛寫完檔、還沒來得及 store.create()」的
        正常上傳。刪了會讓使用者的檔案憑空消失。
      * 又舊又有 job → JobStore 還記得它，代表這件事還沒了結（排隊排很久、
        長 PDF 還在跑，或異常中斷後還沒收拾完）。不該由掃把插手。
        （失敗列通常不會走到這裡：3 次都失敗的當下 staging 就被刪了，D10。）

    【now 是時間的注入點（seam）】
    預設用真正的現在。測試可以把它往後撥，不必真的等 24 小時
    ——與專案既有的 get_now()／FixedClock 同一招。
    兩邊都用 .timestamp() 換算成 epoch 秒數再比，所以傳「帶時區」或
    「不帶時區」的 datetime 都算得對（見常見陷阱 4）。
    """
    directory = staging_dir()
    if not directory.is_dir():
        # 全新環境（或剛重建 data/）第一次啟動就會遇到，不是錯誤
        return 0

    moment = now if now is not None else datetime.now()
    cutoff = moment.timestamp() - STAGING_MAX_AGE_HOURS * 3600

    removed = 0
    # sorted() ＝順序固定，log 看起來才穩定（iterdir 本身不保證順序）
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue                       # staging 底下不該有子資料夾；有就跳過，不遞迴刪
        if path.stat().st_mtime >= cutoff:
            continue                       # 還很新
        if store.get(path.stem) is not None:
            continue                       # JobStore 還記得它（path.stem ＝去掉副檔名的檔名＝job_id）
        path.unlink(missing_ok=True)
        removed += 1
    return removed
```

---

### 步驟 3：跑測試看它轉綠

- [ ] 先跑新測試：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_staging_service_unit.py -v
```

預期最後一行：`10 passed`。

- [ ] 再跑全量：

```bash
pytest -q
```

預期：**基線 ＋ 10**，全綠、0 skipped。**既有測試一顆都不准紅**——本 phase 只新增一個沒有人呼叫的模組，對外行為零改變。

---

### 步驟 4：確認 `.gitignore` 已經涵蓋 staging（**不必新增任何一行**）

`.gitignore` 目前已有 `data/` 這一行。git 的規則是「一個目錄被忽略，底下所有東西都跟著被忽略」，所以 `data/staging/` 天生就被涵蓋了——**不要**再手動加一行 `data/staging/`，那只是噪音。

但要真的驗一次，不要憑印象：

- [ ] 執行：

```bash
cd /Users/linjunting/personalDocAI
mkdir -p data/staging && touch data/staging/驗證用.jpg
git status --short data/
git check-ignore -v data/staging/驗證用.jpg
rm -f data/staging/驗證用.jpg
```

預期：
- `git status --short data/` **沒有任何輸出**（代表 git 完全看不到它）
- `git check-ignore -v` 印出類似 `.gitignore:6:data/	data/staging/驗證用.jpg`（第 6 行的 `data/` 這條規則命中）

驗完記得把驗證用的檔案刪掉（上面最後一行已經做了）。

> 📌 **不要 `rm -rf data`。** 你的 `data/` 裡有約 54 MB 的真照片（50 張照片的原圖與縮圖），而且**不入版控＝全世界只有一份**。只刪剛剛 `touch` 出來的那一個檔就好。

---

### 步驟 5：git commit

> ⚠ **依總覽 §7 鐵律 12：commit 節奏由產品負責人決定，他沒指示前先不 commit——本步驟此時跳過**，
> 指令與訊息留著備用。git 驗收改用「與開工前 `git status` 快照相減」。（2026-08-25 核對時補上。）

- [ ] 執行（**僅在產品負責人指示 commit 時**）：

```bash
cd /Users/linjunting/personalDocAI
git add app/services/staging_service.py tests/unit/test_staging_service_unit.py
git commit -m "feat: Phase 58 staging 暫存區服務——staging_service.py（staging_path／save／read／remove／sweep_stale_staging 五函式；檔案走磁碟不進 Redis，design5 §4.1）、24 小時掃把只刪『又舊又沒有 job』的孤兒檔、now 為可注入的時間 seam，+10 tests；沒有人呼叫它（接線在 62／59／65），端點仍 20、對外行為零改變"
```

---

## 5. ASCII 圖

### 圖一：`data/` 的目錄結構（本 phase 新增最下面那一格）

```text
專案根目錄  /Users/linjunting/personalDocAI
├── app/   db/   docs/   tests/   compose.yaml   .gitignore
└── data/                      ← config.DATA_DIR 的預設值
    │                            （pytest 時被 isolated_data_dir 指到 tmp_path/data）
    │                            .gitignore 有 data/ 這一行 → 整棵樹都不入版控
    │
    ├── photos/                ← 【正本】原圖，檔名＝photo.id，路徑寫進資料庫
    │   ├── 41.jpg
    │   └── 42.png
    │
    ├── thumbs/                ← 【正本】縮圖（長邊 ≤ 512px），檔名＝photo.id
    │   ├── 41.jpg
    │   └── 42.png
    │
    └── staging/               ★ 本 phase 新增【暫存】
        ├── a1b2c3.jpg              檔名＝job_id（那時還沒有 photo.id）
        ├── d4e5f6.pdf              路徑**不進資料庫**、不外送給前端
        └── （成功或最終失敗之後，這裡的檔都會被刪掉；
              崩潰留下來的孤兒由 24 小時掃把收拾）
```

### 圖二：一個檔案從 staging 進 photos 的旅程

```text
   使用者選檔                                        瀏覽器
   ────────                                        ────────
      │  POST /photos（multipart，一份影像位元組）        ▲
      ▼                                                 │
  ┌──────────────────────── app（uvicorn）──────────────┴───────┐
  │  ① 格式檢查：不是 JPEG／PNG／PDF → 415，什麼都不做           │
  │  ② save_staging(job_id, content_type, data)  ← 本 phase     │
  │     位元組落到 data/staging/{job_id}.jpg                     │
  │  ③ store.create(job_id=…)  → status="queued"（Phase 57）    │
  │  ④ 把任務丟進佇列（只帶 job_id，**不帶位元組**）             │
  │  ⑤ 回 202 {job_id, filename, content_type}                  │
  └──────────────────────────────┬──────────────────────────────┘
                                 │  （幾十秒〜幾分鐘之後）
                                 ▼
  ┌──────────────────────── worker（celery）────────────────────┐
  │  ⑥ read_staging(job_id, content_type)        ← 本 phase     │
  │     位元組讀回來（app 與 worker 共用同一個 ./data bind-mount）│
  │  ⑦ VLM 看圖（最多 3 次）→ embedding                         │
  │  ⑧ INSERT 一列 photo（進收件箱）→ 拿到 photo.id             │
  │  ⑨ storage_service.save_original / make_thumbnail           │
  │     data/photos/{photo.id}.jpg ＋ data/thumbs/{photo.id}.jpg│
  │     ★ 這兩個路徑**寫進資料庫**（正本從這一刻起成立）        │
  │  ⑩ remove_staging(job_id, content_type)      ← 本 phase     │
  │     data/staging/{job_id}.jpg 刪掉，暫存區不留痕跡           │
  │  ⑪ store.delete(job_id)  ＝「成功」（Phase 57）             │
  └─────────────────────────────────────────────────────────────┘

   ⚠ 如果 worker 在 ⑥〜⑩ 之間被殺掉（機器重開、Docker 重啟、Redis volume 掉了），
     staging 的那個檔就沒人記得了 → 變成孤兒 → 由下面那支掃把收拾。
```

### 圖三：掃把的判斷表（**兩個條件都成立才刪**）

```text
   sweep_stale_staging(store, now=…)
   對 data/staging/ 底下的每一個檔案問兩個問題：

                     │ JobStore 還記得它       │ JobStore 查不到它
                     │ (store.get(stem) 有值)  │ (store.get(stem) is None)
   ──────────────────┼─────────────────────────┼──────────────────────────
   mtime 在 24 小時內 │  保留                   │  保留
   （還很新）         │  排隊中，或正在跑       │  可能是「剛寫完檔、還沒
                     │                         │  來得及 create()」的正常上傳
   ──────────────────┼─────────────────────────┼──────────────────────────
   mtime 超過 24 小時 │  保留                   │  ★ 刪掉 ★
   （很舊了）         │  JobStore 還記得＝這件事 │  又舊又沒人記得＝孤兒垃圾
                     │  還沒結束，掃把不插手    │  （崩潰之後留下來的）
   ──────────────────┴─────────────────────────┴──────────────────────────

   誰來按下這個按鈕：**app 啟動時一次、worker 啟動時一次**（design5.md §4.1）。
   ★ 本 phase 只寫這支函式與測試，**兩處接線都在 Phase 65**：
     app/main.py 的 lifespan ＋ app/celery_app.py 的 worker_ready 訊號
     （Phase 66 只是讓 worker 容器真的跑起來）。現在還沒有 worker 可以接，
     app 的啟動流程也還沒有理由要動。
   不做 cron、不做 Celery beat、不做每小時自動跑（design5 沒有要求）。
```

---

## 6. 驗收清單

- [ ] **開工前確認 Phase 57 已完成**

  ```bash
  ls -l app/services/ingest_job_store.py
  grep -c "@pytest.fixture(autouse=True)" tests/conftest.py
  ```

  預期：檔案存在；`grep -c` 印 `4`

- [ ] **五個契約函式與常數都在，簽章與本檔步驟 2 的程式碼逐字相同**（「契約備忘」未入庫，以本檔內嵌內容為準）

  ```bash
  grep -nE "^STAGING_SUBDIR|^STAGING_MAX_AGE_HOURS|^def staging_path|^def save_staging|^def read_staging|^def remove_staging|^def sweep_stale_staging" \
    app/services/staging_service.py
  ```

  預期：七行命中（`staging_dir()` 是額外的小工具，不在契約裡，多它無妨）

- [ ] **24 小時這個數字只有一個定義處**

  ```bash
  grep -rn "STAGING_MAX_AGE_HOURS" app/ --include="*.py"
  ```

  預期：每一行命中的檔名**都是** `app/services/staging_service.py`（約 4 行：`= 24` 的定義、
  兩處註解／docstring 提到這個名字、`sweep_stale_staging` 內的使用）。
  **`app/core/config.py` 一行都不該有。**
  ⚠ 給 Phase 65 的實作者：契約備忘 §3.6 也列了一份 `config.py` 版的
  `STAGING_MAX_AGE_HOURS`——**不要照著補**，唯一定義處就是本 phase 的
  `staging_service.py`（兩份一定漂移；真要可用 `.env` 覆蓋時是「搬家」不是「加一份」，
  見程式碼裡常數旁的註解）。Phase 65 開工前置檢查若在 `config.py` 找它而找不到，
  **是預期，不是本 phase 漏做**。

- [ ] **本 phase 完全沒碰 Redis／Celery**（驗 import 與 requirements，不驗註解——
  註解本來就在解釋「為什麼不用它們」，抓字串一定誤中）

  ```bash
  grep -nE "^(import|from) .*(redis|celery)" app/services/staging_service.py || echo "OK：程式沒有 import"
  grep -inE "redis|celery" requirements.txt || echo "OK：requirements 沒有加套件"
  ```

  預期：兩行都印 `OK：…`

- [ ] **沒有任何地方寫 `from app.core.config import DATA_DIR`**（那樣測試就改不動了）

  ```bash
  grep -n "from app.core.config import" app/services/staging_service.py || echo "OK：走 config.DATA_DIR"
  ```

  預期輸出：`OK：走 config.DATA_DIR`

- [ ] **新測試 10 顆全綠**

  ```bash
  pytest tests/unit/test_staging_service_unit.py -v
  ```

  預期最後一行：`10 passed`

- [ ] **掃把的四種組合都被測到**

  ```bash
  grep -n "新檔有job\|新檔沒job\|舊檔有job\|舊檔沒job" tests/unit/test_staging_service_unit.py | wc -l
  ```

  預期：`10`——四個變數各有「建立」與「斷言」兩行（8），外加兩個「舊檔」在 `_age(...)` 撥舊 mtime 時又各出現一行（+2）

- [ ] **`.gitignore` 已涵蓋 staging（不必新增規則）**

  ```bash
  cd /Users/linjunting/personalDocAI
  mkdir -p data/staging && touch data/staging/驗證用.jpg
  git status --short data/
  git check-ignore -v data/staging/驗證用.jpg
  rm -f data/staging/驗證用.jpg
  ```

  預期：`git status --short data/` 無輸出；`check-ignore` 印出 `.gitignore:…:data/	data/staging/驗證用.jpg`

- [ ] **本 phase 沒有任何人呼叫這個模組**（接線是 62／59／65 的事）

  ```bash
  grep -rn "staging_service" app/ --include="*.py" | grep -v "app/services/staging_service.py"
  ```

  預期：**沒有任何輸出**

- [ ] **端點數仍是 20**

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

  預期：**基線 ＋ 10**，且 **0 skipped**

- [ ] **pytest 沒有弄髒專案的 `data/`**（跑完全量之後再看一次）

  ```bash
  ls data/ && git status --short
  ```

  預期：`data/` 底下**沒有** `staging/` 這個資料夾（因為測試全都寫在 tmp_path），`git status` 沒有任何 `data/` 相關的行

- [ ] **git 收尾符合現行節奏**：產品負責人已指示 commit → 步驟 5 已執行；
  未指示（現行預設）→ 跳過 commit，改核對「`git status --short -- app tests` 的新增項
  恰為本 phase 的兩個檔」（與開工前快照相減）

---

## 7. 常見陷阱

1. **把 `now` 的預設值寫成 `datetime.now(timezone.utc)`，卻拿 `.replace()` 之類的方式跟 mtime 硬比。**
   `path.stat().st_mtime` 回的是 **epoch 秒數**（一個浮點數），沒有時區的概念。本文件的實作兩邊都先 `.timestamp()` 換算成 epoch 秒數再比，所以你傳「帶時區」或「不帶時區」的 `datetime` 都算得對。**但如果你改成先把 mtime 轉成 `datetime` 再跟 `now` 相減**，就會踩到經典的 `TypeError: can't subtract offset-naive and offset-aware datetimes`，或者更糟——不報錯但差了 8 小時（台灣時區），讓 24 小時的門檻變成 16 或 32 小時。**照本文件的寫法用 `.timestamp()` 比較就不會遇到。**

2. **掃把只檢查「舊」，忘了檢查「JobStore 有沒有這筆」。**
   症狀非常隱蔽：平常都對，直到某個檔在佇列裡躺超過 24 小時——這完全可能發生：晚上收工 `docker compose stop`、隔天下午才拉起來，昨晚排進去還沒輪到的檔一開機就滿 24 小時了；或一份幾百頁的 PDF 用本機 gemma4 跑（一頁 64〜88 秒、每頁最多 3 次，光它自己就能吃掉十幾個小時，前面再排幾個檔就過線）。這時 JobStore 明明還記得它（`queued` 或 `analyzing`），漏了條件的掃把卻**在 worker 還沒讀完（甚至還沒開始讀）時把檔刪掉**——之後 `read_staging` 直接 `FileNotFoundError`，一筆好好的上傳莫名變失敗。兩個條件缺一不可。

3. **掃把只檢查「JobStore 沒這筆」，忘了檢查「舊」。**
   症狀更誇張：使用者上傳的每一個檔都有可能憑空消失。因為 Phase 62 的順序是「先寫 staging、再 `store.create()`」，那中間有一瞬間是「檔在、job 還沒建」。剛好在那一瞬間有人重啟 app（掃把在 startup 跑），檔就沒了。

4. **用 `path.name` 當 job_id（而不是 `path.stem`）。**
   `path.name` 是 `a1b2c3.jpg`（**含副檔名**），`path.stem` 才是 `a1b2c3`。用錯的話 `store.get()` 永遠查不到，於是**每一個超過 24 小時的檔都會被刪**，包含還在跑的。`test_掃把只刪又舊又沒有job的檔` 裡的「舊檔有job」那一項就是專門擋這件事的。

5. **以為 `data/staging/` 需要在 `.gitignore` 多加一行。**
   不需要。`.gitignore` 已有 `data/`，git 的規則是「目錄被忽略，底下全部跟著忽略」。多加一行只是噪音。步驟 4 用 `git check-ignore -v` 驗過即可。

6. **驗證完 `.gitignore` 之後手滑打了 `rm -rf data`。**
   你的 `data/` 裡有約 54 MB 的真照片（50 張照片的原圖與縮圖），**不入版控＝全世界只有一份**，`pg_dump` 也備份不到它（`pg_dump` 只倒資料庫）。刪掉的話照片列還在、縮圖與大圖全變 404。步驟 4 只刪 `data/staging/驗證用.jpg` 那一個檔。

7. **把 `EXTENSIONS` 這個名字直接抄過來用。**
   `storage_service.py` 已經有一個 `EXTENSIONS`，但值是 `{"image/jpeg": "jpg"}`（**不帶點**，而且**沒有 PDF**——PDF 在 router 就被 `pdf_service` 逐頁換成 PNG 了）。兩個檔案放兩個同名不同值的常數，遲早有人複製貼上出事。本文件用 `STAGING_EXTENSIONS`（帶點、含 PDF）。

8. **在 `save_staging` 裡「順便」用 Pillow 打開檔案確認它是不是真的圖。**
   不要。staging 只是搬位元組，一個 byte 都不解讀。「這到底是不是一張看得懂的圖」是 worker 送 VLM 那一步的事——壞檔＝那一次失敗，算進 3 次重試（design5 錯誤表 3／5）。在這裡先驗會多出一種 design5 錯誤表沒有的錯誤碼，而且假位元組的測試會全部炸掉。

9. **`read_staging` 找不到檔案時「安靜地回 `b""`」。**
   不要吞錯。走到這裡代表「JobStore 說有這個任務，但檔案不見了」——那是真的出事了（有人手動刪了 `data/staging`、或掃把誤刪）。讓 `FileNotFoundError` 炸出來，變成一次明確的失敗；回空位元組只會讓 VLM 對著 0 bytes 說「看不懂」，然後你去查 3 次重試為什麼全失敗，查半天。

10. **把掃把接到 app 的啟動流程、或順便寫個 Celery beat 排程。**
    接線是 **Phase 65** 的事（`app/main.py` 的 lifespan ＋ `app/celery_app.py` 的 `worker_ready`，兩處都在那一份文件裡有完整程式碼），而且現在根本沒有 worker 可以接。design5 §4.1 也講得很清楚：**app／worker 啟動時各掃一次**，不做定時排程。本 phase 的驗收清單有一條就是「沒有任何人呼叫這個模組」。

11. **忘了 Phase 57 是本 phase 的硬前置。**
    如果 Phase 57 還沒做，`staging_service.py` 第一行的
    `from app.services.ingest_job_store import JobStore` 會在 **import 當下**就倒——
    整份 10 顆直接 collection error（`ImportError: cannot import name 'ingest_job_store'
    from 'app.services'`），連 fixture 解析都輪不到。先把 57 做完。
    （2026-08-25 核對時修正：舊版寫「三顆掃把測試噴 fixture not found」，那是 57 做了一半
    （模組在、conftest 沒加 fixture）才會出現的樣子。）

12. **同時跑兩份 pytest。**
    症狀：大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`。原因是兩份都在 `TRUNCATE` 同一個測試庫。等另一份跑完再跑。

---

## 8. 完成後的專案狀態

系統多了一層「檔案在等 worker 的時候放哪裡」的能力：`data/staging/{job_id}.jpg|.png|.pdf` 寫得進、讀得回、刪得掉，外加一支「又舊又沒人記得才刪」的 24 小時掃把。`data/` 的 `.gitignore` 已經涵蓋它，pytest 全部寫在 tmp_path、永遠不會弄髒專案的 `data/`。

**但目前還沒有任何人呼叫它**——`POST /photos` 還沒改（Phase 62）、`run_ingest_job()` 還不存在（Phase 59／60）、掃把也還沒接到任何啟動流程（兩處接線都在 Phase 65：app 的 lifespan 與 worker 的 `worker_ready`）。對外行為零改變，端點仍是 20 個。

到這裡，階段乙的**三支地基**（Phase 56 建議欄、Phase 57 JobStore、Phase 58 staging）就全部到位了。下一步 **Phase 59** 會把它們串起來，寫出真正的任務本體 `run_ingest_job()`：從 staging 讀圖 → VLM 最多 3 次 → embedding → INSERT 收件箱 → 存原圖縮圖 → 刪 staging → `store.delete()`。

測試累計 ＝ 開工基線 ＋ **10**。
