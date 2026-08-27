# Phase 71：增量五錯誤收尾與全量回歸

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 把 design5.md §8 錯誤表的 **10 列**逐列**清點到有測試把關**
>（52〜70 全程 TDD，大多數列已由 Phase 59〜64 釘住——本檔補**三個真缺口**）、
> 把 §3「不做」清單與 §1.2 被否決清單變成**掃得出來的斷言**，
> 最後跑一輪完整回歸（含「Redis 位址指到死埠、顆數不變」的零依賴實證），
> 證明增量五做出來的東西**壞掉時壞得跟設計說好的一樣**。

**為什麼要做這個：**

Phase 52〜70 是「把非同步入庫做出來」。這個 phase 是「確認它壞的時候，壞得跟設計說好的一樣」。

非同步特別需要這一關，因為失敗**不再有人看著**。以前上傳是同步的：VLM 看不懂 → HTTP 立刻回 422，
使用者當場就知道。現在 HTTP 兩秒就回 202「收下了」，真正的失敗發生在幾分鐘後、
在另一個行程（worker）裡。如果失敗路徑沒清乾淨，會留下三種看不見的垃圾：

- **孤兒暫存檔**：`data/staging/` 裡躺著一個誰也不會再讀的檔案，磁碟慢慢被吃掉。
- **孤兒照片列**：資料庫有一列，但原圖檔沒寫成功 → 縮圖與大圖全部 404。
- **卡住的進度列**：右下角面板永遠有一列「分析中」，但其實那個任務早就死了。

這三種都不會有人跳出來告訴你。所以要有測試盯著。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **錯誤表** | design5.md §8 那張表：每一列是「一種出錯的情況」，寫明**誰**回應、結果應該是什麼。本 phase 把每一列變成一顆測試 |
| **掃碼** | ⚠ **不是掃 QR code**。是用指令或測試去**掃原始碼**，證明「某個東西不存在」（例如：沒有人寫過 `@router.delete`）。有些規則沒辦法用行為測試證明「不存在」，掃原始碼是最直接的辦法 |
| **孤兒**（orphan） | 只剩半邊的東西。孤兒檔案＝磁碟上有、資料庫沒有任何一列指著它；孤兒列＝資料庫有列、對應的檔案不見了 |
| **零依賴實證** | 把外部服務的位址故意指到一個**沒有人在聽**的埠，再跑一次全量測試。顆數完全一樣 ＝ 證明測試從頭到尾沒有偷偷連過那個服務 |
| **死埠** | 沒有任何程式在監聽的通訊埠。埠 9 是慣例上的「discard」埠，本專案既有的 `OLLAMA_BASE_URL=http://localhost:9` 用的就是它 |
| **`information_schema`** | PostgreSQL 內建的一組唯讀檢視表，可以用 SQL 查「這個資料庫有哪些表、哪些欄位」。用它來證明「`photo` 表**沒有**某個欄位」 |
| **`inspect.signature`** | Python 內建工具，可以問一個函式「你的參數叫什麼、型別註記是什麼」。用它證明「Celery 任務只吃 `job_id`，不吃影像位元組」 |
| **冪等**（idempotent） | 同一個動作做兩次，結果跟做一次一樣。這裡指：同一個 job 被 Celery 重送、任務跑第二次，照片**不會變成兩張** |
| **全量回歸** | 把到目前為止寫過的所有測試從頭再跑一遍，確認新東西沒有把舊功能弄壞 |

---

## 1. 對應 design5.md 章節

| 出處 | 說的是什麼 |
|---|---|
| **§8 錯誤表**（10 列） | 本 phase 的主線之一：§4.1 逐列盤點（大多已由 Phase 59〜64 釘住），新檔 `tests/integration/test_design5_error_paths.py` 補三個真缺口 |
| **§3「不做」**（9 項） | §4.3 逐項掃碼 |
| **§0 四條「禁止」** | 也在 §4.3 逐項掃碼（其中三條可自動化、一條是時序性的，見 §4.3 的表） |
| **§1.2 被否決**（13 列） | 也在 §4.3 逐項掃碼——被否決的方案不是「暫時不做」，是「不准重開」，所以要能掃得出來 |
| **§5 API 契約** | 「清點測試（現有『端點恰 20』『openapi 零 DELETE』）要改數字、並繼續斷言沒有 DELETE」——本 phase 驗收 Phase 64 改的那顆，並補一顆**逐支列名**的 |
| **§9 測試策略** | 「本增量必加」那 11 條契約，逐條對照「誰已經測了」 |
| **§12 階段乙**（第 1、3 條） | 「`pytest -q` 全綠、0 skipped」「Fake 三次失敗：待決定不出現、磁碟 staging 不留」 |
| **§13 風險** | 「host `.venv` 與映像套件分岔」——所以 §4.6 有一條「重建映像後手動煙霧一次」 |

---

## 2. 前置條件

- **Phase 52〜70 全部完成且全綠。** 這是收尾 phase，不是開發 phase。
- **★ 閘門 G2 已由產品負責人通過**（design5 §12「階段乙」五條）。
- **★ 閘門 G3 還沒到。** 本 phase **一個字都不准動 `docs/spec/`**（那是 Phase 72 的事，
  而且要產品負責人明示核准）。
- 本檔所有指令都在**專案根目錄**執行（`grep`／`ls`／`git` 用的都是相對路徑，
  位置跑掉就會查到別的東西、甚至誤判成「通過」）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db／redis 要是 Up (healthy)，app／worker 要是 Up
pytest -q                        # 先確認基準沒跑掉，把顆數記下來
```

把開工基準填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | ＿＿＿ passed ＋ 0 skipped |
| 開工時 `/openapi.json` 端點數 | 應為 **22**（Phase 64 之後） |
| `docker compose ps` 服務數 | 應為 **4**（`db`／`redis`／`app`／`worker`） |

---

## 3. 範圍

### 做

- §8 錯誤表 10 列逐列盤點（§4.1 的對照表），確認每一列都有測試把關。
- 新建 `tests/integration/test_design5_error_paths.py`：補盤點出來的**三個真缺口**
  （寫**原圖**失敗清半成品／JobStore 掛掉 500 且刪 staging／`analyzing`・`retrying` 也不准 dismiss）。
- 在同一個檔補「不做」掃碼（§3 九項＋§0 四條＋§1.2 十三列，能自動化的全部自動化）。
- 全量回歸：`pytest -q`、Redis 死埠、Ollama 死埠、端點清點、正式庫健檢、`docker compose ps`。
- 把「不能自動化」的幾項寫成**人工檢查步驟**，並說明為什麼不能自動化。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 為了讓某顆測試變綠而改產品行為 | 這是**收尾**，不是重寫。首跑紅了＝揪到真缺陷 → 回**對應的 phase** 修產品碼，然後重跑全量（Phase 37 就是這樣抓出「自創實體＋釘選不是同一個交易」那個 bug） |
| 重複測已經有人測的東西 | 每一列先找「誰已經測了」，只補真正的缺口。重複的測試是負債：改一次程式要改兩個地方 |
| 動 `docs/spec/` 任何一個字 | ★G3 還沒過。design5 §10 明文要產品負責人核准才准改 `.feature` |
| 在測試裡連真的 Redis、或啟動 Celery 容器 | design5 §9／D15 明文。任務本體是 `run_ingest_job(...)`，測試**直接呼叫它** |
| 自己 commit、自己把 `unfinish/` 搬進 `finish/` | 歸檔隨 commit 執行，時機由產品負責人決定（Phase 72 §4.9 才處理） |
| 為了「補齊」而幫沒有 Example 的 `#TODO` Rule 寫測試 | 那些 Rule 沒有例子＝規格沒說怎麼驗。硬補是自己發明規格 |
| 改 QR 尺寸那顆測試 | design5 §9 最後一列明文：`.cd-qr svg` 的 `max-width` **不准改小**（增量四唯一一次改產品 CSS，改小 iPhone 就掃不到） |

---

## 4. 實作步驟

### 4.1 先盤點：10 列各由誰把關（做這件事之前不要動手寫測試）

逐列查「誰已經測了」。查法：翻測試檔，或 `pytest -k 關鍵字 --collect-only -q`。
下表是**寫這份計畫時逐份比對 Phase 59〜64 計畫檔的結果**——執行時以 `--collect-only`
的實際輸出為準：表上寫 ✓ 的那顆若真的不在（前面的 phase 執行時被裁掉了），
**回那個 phase 所屬的測試檔補**（行為測試住在它功能的家；本檔只收「跨 phase 收尾」性質的東西）。

> ✅（2026-08-26 校準）本表點名的**每一顆既有測試都已用 `pytest --collect-only -q`
> 對過實際輸出**（`test_ingest_job.py`／`test_ingest_job_pdf.py`／
> `test_ingest_jobs_endpoint.py`／`test_photos_upload.py`／`test_camera_endpoints.py`／
> `test_assign_folder.py`／`test_photo_files.py`），名字**全部逐字對得上、沒有一顆被裁掉**。
> 執行本 phase 時仍要再對一次（52〜70 交錯做，中途可能有人改名）。

| # | 情況（§8 原文） | 預期 | 誰把關（✓＝已有；★＝本檔補） |
|---|---|---|---|
| 1 | 非 JPEG／PNG／PDF | 415；無 job、無 staging | ✓ Phase 62 `test_415不建任務也不寫staging`（三顆既有 415 測試也原樣保留） |
| 2 | 鏡頭 token 無效／過期 | 404；不讀檔 | ✓ Phase 63 `test_亂token不能上傳照片`＋`test_亂token連staging都不會寫`＋`test_過期token不能上傳照片`；「先驗 token 再驗格式」＝既有 `test_camera_endpoints.py::test_亂token加上非法格式回404不是415`（今天就在跑，63 不改它） |
| 3 | JPEG／PNG 看不懂或呼叫失敗 ×3 | 刪 staging；無 `photo` 列；job=`failed` | ✓ Phase 59 `test_三次都看不懂_不留照片_staging不在_job標failed且attempt為3`（**`vlm.calls == 3` 的「恰好 3 次」就在裡面**）＋`test_呼叫失敗也算一次_三次例外同樣整筆失敗`＋`test_空白描述也算看不懂`；端點視角另有 ✓ Phase 63 `test_看不懂的照片是任務失敗不是HTTP失敗`、Phase 64 `test_失敗的任務會留在清單上並帶著錯誤短句` |
| 4 | PDF 某一頁 ×3 | 跳過該頁；其他頁繼續 | ✓ Phase 60 `test_兩頁PDF第二頁三次失敗_只入庫一列_job成功_skipped語意保留`（`每頁呼叫次數 == {1: 1, 2: 3}` ＝「1＋3、不是整份重跑」那個斷言）＋`test_每頁的重試次數各自獨立` |
| 5 | PDF 0 頁成功，或檔無法拆頁 | 同 3 | ✓ Phase 60 `test_每一頁都看不懂_列數0_job標failed`＋`test_壞檔拆不開_job標failed且不留列`（後者連「拆不開＝**0 次**模型呼叫——確定性錯誤不重試、雲端不多收三次費」都釘了） |
| 6 | embedding 失敗 | 算進 3 次；3 次後同 3 | ✓ Phase 59 `test_轉向量三次都失敗_不留照片_job標failed`（`vlm.calls == 3`） |
| 7 | 入庫寫檔失敗 | 清半成品再標失敗，不留孤兒列 | 大半 ✓ Phase 59 `test_ingest_job.py::test_寫檔失敗_不留照片也不留孤兒檔_job標failed`＋Phase 62 改寫的 `test_photo_files.py::test_寫檔失敗時檔案與資料列都不留`——**兩顆炸的都是縮圖（`make_thumbnail`）**；★ 本檔補「炸**原圖**（`save_original`）」那一半 →【補7】 |
| 8 | Redis 當下掛了 | 500；不留 staging | 一半 ✓ Phase 62 `test_入列失敗時回500而且staging與任務都不留`（＝**丟不進佇列**那一半，覆寫 `get_task_dispatcher`）；★ 本檔補 **JobStore 寫不進去**那一半 →【補8】 |
| 9 | dismiss 一筆還在跑的 job | 409 | 大半 ✓ Phase 64 的 204／409／404 四顆（409 那顆用 `queued`）；★ 本檔補「`analyzing`／`retrying` 也不准」→【補9】 |
| 10 | 已定案再 PATCH | 409（本增量不改） | ✓ 既有 `test_assign_folder.py::test_已定案的照片再歸類回409且完全沒被改動`（Phase 27）。它的 fixture `已上傳的照片` 走**真上傳流程**——Phase 62 把 fixture 改成 202＋跑完任務之後，每次全量都等於把「先進收件箱 → 歸類定案 → 再改被 409」整條重走一遍，**全量回歸自動再驗，不必抄一顆** |

- [ ] 逐列打勾。**表上的 ✓ 要用 `--collect-only` 對過才算數**；發現某顆被裁掉了 →
      回那個 phase 的測試檔補，不要搬進本檔。
- [ ] 反過來也一樣：發現某列已被完整測過而你手癢想在本檔再寫一顆 → **不寫**。
      重複的測試是負債：改一次程式要改兩個地方，而且兩個地方遲早會不一致。

> ⚠️ **為什麼本檔的錯誤表只補三顆？** 這正是收尾 phase 的既有作法（Phase 25／37／44：
> 先盤點、只釘 ★ 缺口——Phase 25 就是「九個 ★ 缺口九顆」，不是把 design1 §12 整表重抄）。
> 增量五跟前幾輪不同的是：52〜70 每個 phase 全程 TDD，**各自把自己那幾列在自己的
> 測試檔釘好了**，所以輪到收尾時「逐列有測試」大多是**點名**，不是**補寫**。
> 本檔的重心因此落在 §4.3 的「不做」掃碼——那些沒有別的 phase 會寫。
>
> 三顆補缺跟前面的 phase 節奏不一樣：它們釘的是 52〜70 已經做出來的行為，
> 所以**首跑就應該全綠**。首跑有紅的 ＝ 真的揪到缺陷，回對應的 phase 修**產品程式碼**，
> 不是改測試的斷言。但「綠的」不等於「有測到」：本檔多數斷言是**某個東西不存在**
> （沒有檔案、沒有欄位、沒有 DELETE），天生容易**假綠**——
> 每顆寫完都做一次 30 秒的**反向驗證**：把斷言暫時反過來跑一次，確認它會紅，再改回來。

### 4.2 新建 `tests/integration/test_design5_error_paths.py`（前半：三顆補缺）

Python 區塊整段照抄、分段貼上（每一段開頭都標明對應錯誤表的哪一列）；
**②與⑥兩段是「去哪裡看」的說明與對點指令，不進檔案。**

**① 檔頭與共用工具**

```python
"""增量五（design5.md）§8 錯誤表的收尾驗證（Phase 71）。

體例沿用 Phase 25／37／44 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py）：先盤點、只補 ★ 缺口。
§8 的 10 列大多已由 Phase 59〜64 各自的測試檔釘住（逐列對照表見計畫 phase-71 §4.1；
執行時要用 --collect-only 對過），本檔只補三個真缺口：

| 列 | 情況 | 誰把關 |
|---|---|---|
| 1 | 非 JPEG／PNG／PDF → 415、無 job、無 staging | Phase 62 test_415不建任務也不寫staging |
| 2 | 鏡頭 token 無效 → 404、不讀檔 | Phase 63 三顆＋既有「404 先於 415」那顆 |
| 3 | 圖片 ×3 失敗 → 刪 staging、無列、failed | Phase 59 三顆（vlm.calls==3 在內）＋63／64 端點視角 |
| 4 | PDF 某頁 ×3 → 跳過該頁、其他頁繼續 | Phase 60（每頁呼叫次數 {1:1, 2:3}） |
| 5 | PDF 0 頁成功／無法拆頁 → 同 3 | Phase 60 兩顆（含「拆不開＝0 次模型呼叫」） |
| 6 | embedding 失敗 → 算進 3 次 | Phase 59 test_轉向量三次都失敗_不留照片_job標failed |
| 7 | 寫檔失敗 → 清半成品、不留孤兒列 | Phase 59／62 炸縮圖；★ 本檔【補7】炸原圖 |
| 8 | Redis 掛了 → 500 且不留 staging | Phase 62 佇列那一半；★ 本檔【補8】JobStore 那一半 |
| 9 | dismiss 還在跑的 job → 409 | Phase 64 四顆（queued）；★ 本檔【補9】analyzing／retrying |
| 10 | 已定案再 PATCH → 409（本增量不改） | 既有 test_assign_folder.py（fixture 走真上傳流程） |

【補7】〜【補9】之後是 §3「不做」／§0「禁止」／§1.2「被否決」的掃碼【掃A】〜【掃E】。

⚠ 本檔**不連真 Redis、不啟動 Celery**（design5 D15）：
   任務本體 run_ingest_job(...) 由測試直接呼叫，job 狀態走 conftest 那顆記憶體 store。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.db.session import get_connection
from app.dependencies import get_embeddings, get_job_store, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import staging_service, storage_service
from app.services.ingest_job import run_ingest_job
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 跑完任務
from tests.fakes import FakeVLM, make_png_bytes

專案根目錄 = Path(__file__).resolve().parents[2]

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture
def job_store(wire_memory_job_store):
    """conftest 第四道安全網（Phase 57）正在用的**那一顆**記憶體 JobStore。

    ⚠ 不可以在這裡 new 一顆新的 InMemoryJobStore——那樣端點寫進去的 job
      測試這邊看不到（兩顆各記各的），所有斷言都會變成**假綠**。

    Phase 57 的 wire_memory_job_store 是 autouse 而且 `yield store`，
    所以把它寫進參數列就拿得到同一顆。（Phase 62 的 conftest 另外有一個
    `目前的任務清單()`，拿到的也是同一顆——本檔用 fixture 這條路就夠。）
    """
    return wire_memory_job_store


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。

    （與 test_folder_error_paths.py／test_design3_error_paths.py 的同名 fixture 用意相同。）
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案（含 staging／photos／thumbs 三個子目錄）。

    conftest 的 isolated_data_dir 已把 config.DATA_DIR 指到本測試專屬的臨時目錄，
    所以看到的一定只有「本測試造成的」檔案。沒人寫過檔時那個目錄根本不存在，
    直接 rglob 會炸 FileNotFoundError，所以先判 exists（與前兩個收尾檔同一寫法）。
    """
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


def 入列(client, *, filename="a.png", content_type="image/png",
        payload: bytes | None = None) -> str:
    """走真的 HTTP 端點把一個檔案收下來，回傳 job_id。

    刻意不直接呼叫 staging_service／JobStore：入列這件事的順序
    （先落 staging、再建 job、再丟 Celery）本身就是錯誤表第 8 列在守的東西。
    """
    if payload is None:
        payload = make_png_bytes()
    response = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def 跑任務(job_id: str, vlm, embeddings=None) -> None:
    """測試扮演 worker，把某一個 job 就地跑完（design5 D15：不碰真 Redis、不啟動 Celery）。

    做法是**先把假件掛上 dependency_overrides、再呼叫 conftest 的 `跑完任務()`**
    ——那個 helper 會用 `目前注入的假件()` 把 vlm／embeddings／now 撈出來交給
    `run_ingest_job`，與 Phase 62 之後全專案的寫法一致。

    ⚠ `lambda: vlm` 回的是**同一個實例**——之後要看 `vlm.calls` 之類的累計值才看得到。
      寫成 `lambda: FakeVLM(...)` 這種**每次 new 一顆新的**寫法，累計值永遠是 1（假綠）；
      Phase 59／60 那些數呼叫次數的假件（ScriptedVLM／分頁VLM）同理，都得吃同一個實例。
    """
    app.dependency_overrides[get_vlm] = lambda: vlm
    if embeddings is not None:
        app.dependency_overrides[get_embeddings] = lambda: embeddings
    跑完任務(job_id)


def _讓它爆炸(*args, **kwargs):
    raise RuntimeError("磁碟在寫入途中掛掉")
```

> 💡 這裡刻意**沒有**「依序回答的 VLM」「會爆炸的 VLM」「會炸的 Embeddings」這類假件——
> 「第幾次呼叫失敗」的劇本假件住在 Phase 59／60 的測試檔（`ScriptedVLM`／`分頁VLM`），
> 那裡才有在數呼叫次數。本檔的三顆補缺都用最普通的 `FakeVLM`／`monkeypatch` 就夠。

**② 第 1〜6 列：不在本檔（去哪裡看）**

第 1〜6 列的行為測試**全部住在它們功能所屬的檔案**（§4.1 對照表的 ✓ 欄），
本檔不重寫。快速對點名單（執行時用這幾行確認它們真的都在收集得到）：

```bash
pytest --collect-only -q \
  tests/integration/test_photos_upload.py \
  tests/integration/test_ingest_job.py \
  tests/integration/test_ingest_job_pdf.py \
  tests/integration/test_camera_endpoints.py \
  tests/integration/test_ingest_jobs_endpoint.py | grep -c "test_"
```

  預期：一個大於 0 的數字，而且下面這些名字都找得到（`-k` 逐一驗也行）：
  `test_415不建任務也不寫staging`、`test_亂token連staging都不會寫`、
  `test_亂token加上非法格式回404不是415`、
  `test_三次都看不懂_不留照片_staging不在_job標failed且attempt為3`、
  `test_兩頁PDF第二頁三次失敗_只入庫一列_job成功_skipped語意保留`、
  `test_壞檔拆不開_job標failed且不留列`、`test_轉向量三次都失敗_不留照片_job標failed`。
  （測試檔名以 Phase 59〜64 實際建的為準——上面五個路徑照契約備忘 §2.3。）

**③【補7】第 7 列的另一半：寫「原圖」失敗 → 清半成品、不留孤兒列**

Phase 59／62 的寫檔失敗測試炸的都是**縮圖**（`make_thumbnail`，
今天的 `tests/integration/test_photo_files.py:153` 也是同一顆函式）；
「存**原圖**（`save_original`）就爆」這條路沒有人走過——它失敗的時間點更早，
清理範圍不一樣（原圖半個都還沒落地），值得單獨一顆。

```python
# ----【補7】錯誤表第 7 列的缺口：寫「原圖」失敗 → 清掉半成品，不留孤兒列 ----
# （炸縮圖的那一半由 Phase 59 test_寫檔失敗_不留照片也不留孤兒檔_job標failed
#   與 Phase 62 改寫的 test_寫檔失敗時檔案與資料列都不留 守著，本檔不重寫。）


def test_第7列_寫原圖失敗時不留孤兒列也不留半個檔(client, job_store, monkeypatch):
    """入庫的順序是 INSERT → 存原圖 → 產縮圖 → UPDATE 回寫路徑（Phase 19 契約）。

    檔名要用 id，所以 INSERT 一定先行——也就是說寫檔失敗時**資料庫已經有一列了**。
    現有的清理語意（remove_if_exists ×2 ＋ delete_photo）必須原封不動搬進 worker：
    失敗時那一列要刪掉，否則待決定牆上會出現一張永遠 404 的卡。

    ⚠ 這一顆刻意**不**斷言呼叫次數。design5 §8 第 6 列明寫 embedding 失敗算進 3 次，
      但第 7 列只說「清掉半成品再標失敗」，沒有說要不要重試——沒說的事不要用測試釘死，
      那會把實作者的合理選擇變成違規。這裡只驗**最終狀態**。
    """
    job_id = 入列(client)
    monkeypatch.setattr(storage_service, "save_original", _讓它爆炸)

    跑任務(job_id, FakeVLM(收據理解))

    assert photo_repository.count_photos() == 0, "寫檔失敗不可以留下孤兒列"
    assert data_dir底下的檔案() == [], "半個檔案都不可以留（含 staging）"
    assert job_store.get(job_id)["status"] == "failed"
```

> ⚠ `save_original`／`make_thumbnail` 是 `app/services/storage_service.py` **實際的**函式名
> （2026-08-25 用 `grep -n "^def " app/services/storage_service.py` 對過；
> 沒有叫 `save_thumbnail` 的東西）。monkeypatch 之所以有效，前提是 worker 的
> `run_ingest_job` 跟現在的 `photos.py` 一樣寫成 `storage_service.save_original(...)`
> 模組屬性呼叫——對不上就改測試裡的名字（**不要**去 storage_service 加同義函式）。

**④【補8】第 8 列的另一半：JobStore（Redis）寫不進去 → 500 且不留 staging**

正式環境的 Redis 同時扮演兩個角色，所以有兩種掛法：
(a) 任務佇列的 broker——丟 Celery 那一下會爆；(b) 進度用的 `RedisJobStore`——
`store.create()` 會爆。**(a) 已由 Phase 62 的
`test_入列失敗時回500而且staging與任務都不留` 守著**（覆寫 `get_task_dispatcher()`
注入點，連 job 不留幽靈都驗了）；本檔補 (b)。兩種都不需要真的 Redis——
把對應的東西換成「一呼叫就丟例外」的假件即可，而且**兩個掛法走的都是
`Depends()` 注入點**（`get_job_store`／`get_task_dispatcher`），
`dependency_overrides` 蓋得到，與全專案其他假件同一套手法。

```python
# ----【補8】錯誤表第 8 列的缺口：JobStore 寫不進去 → 500，而且不留下暫存檔 ----
# （broker 丟不進佇列的那一半由 Phase 62 test_入列失敗時回500而且staging與任務都不留
#   守著——它覆寫的是 get_task_dispatcher()；本顆覆寫的是 get_job_store()。）


class 會爆炸的JobStore:
    """create() 一律丟例外——模擬 RedisJobStore 連不上 Redis。"""

    def create(self, **kwargs):
        raise RuntimeError("Error 111 connecting to redis:6379. Connection refused.")

    def get(self, job_id):
        return None

    def update(self, job_id, **fields):
        return None

    def delete(self, job_id) -> None:
        return None

    def list_open(self):
        return []


def test_第8列_JobStore寫不進去時回500且不留staging(不擲出例外的client):
    """寫入順序是「先落 staging、再建 job」，所以建 job 失敗時磁碟上已經有檔案了。

    design5 §8 第 8 列明文：「最好連 staging 也別留（寫入順序：先 staging 再入列的話，
    失敗路徑要刪 staging）」。沒有這一段清理，Redis 抖一下就會在磁碟留下垃圾。

    覆寫 get_job_store 之所以蓋得掉 conftest 的 wire_memory_job_store：
    dependency_overrides 是一個 dict、同一個 key 後蓋前——本測試把
    wire_memory_job_store 放進去的那一格換成會爆炸的假件，測後由
    wire_fake_ai 的統一 clear() 收乾淨。
    """
    app.dependency_overrides[get_job_store] = lambda: 會爆炸的JobStore()

    response = 不擲出例外的client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 500, "入列失敗不可以被吞掉（不能假裝 202）"
    assert data_dir底下的檔案() == [], "失敗路徑要把已經落地的 staging 刪掉"
    assert photo_repository.count_photos() == 0
```

**⑤【補9】第 9 列的缺口：`analyzing`／`retrying` 也不准 dismiss**

```python
# ----【補9】錯誤表第 9 列：只准關掉失敗的列 ----
#
# ⚠ 這一列 Phase 64 已經測掉大半，**本檔不重寫**：
#     test_ingest_jobs_endpoint.py::test_關掉失敗的那一列回204且清單少一列
#     ::test_關掉還在跑的任務回409（用的是 queued 狀態）
#     ::test_關掉不存在的任務回404
#     ::test_關掉成功的任務也是404
# 本段只補一個真缺口：**「還在跑」不只有 queued 一種**。
# 只檢查 status == "queued" 的實作會讓 analyzing／retrying 的任務被人關掉——
# 那正是「使用者以為檔案沒進系統、再上傳一次 → 結果兩張」的來源。


@pytest.mark.parametrize("進行中的狀態", ["queued", "analyzing", "retrying"])
def test_第9列_三種進行中狀態都不准dismiss(client, job_store, 進行中的狀態):
    """JOB_STATUSES 裡除了 failed 之外的**每一種**都要回 409、而且那筆要留在清單上。

    Phase 64 那顆只驗了 queued（剛入列、還沒跑過）；
    analyzing 與 retrying 是任務真的跑起來之後才會有的狀態，一樣不准藏。
    """
    job_store.create(
        job_id="job-x", filename="a.png", content_type="image/png",
        ai_backend="local", source="upload",
    )
    job_store.update("job-x", status=進行中的狀態)

    response = client.post("/ingest-jobs/job-x/dismiss")

    assert response.status_code == 409, (
        f"{進行中的狀態} 也算「還在跑」，不可以被 dismiss（{response.text}）"
    )
    清單 = client.get("/ingest-jobs").json()["jobs"]
    assert [job["job_id"] for job in 清單] == ["job-x"]
    assert job_store.get("job-x")["status"] == 進行中的狀態, "409 時狀態不可以被改到"
```

**⑥ 第 10 列：不在本檔（為什麼連「回歸顆」都不抄）**

第 10 列（已定案再 PATCH → 409）由既有的
`test_assign_folder.py::test_已定案的照片再歸類回409且完全沒被改動` 守著。
它的 fixture `已上傳的照片` 走**真上傳流程**——Phase 62 把 fixture 改成
「202 ＋ 跑完任務」之後，這顆測試每次全量都把
「入庫先進收件箱 → 歸類定案 → 再改被 409」整條重走一遍。
若 worker 手滑把照片直接寫進建議的資料夾（＝一入庫就定案），
Phase 59 的 `test_一次看得懂就入庫_照片進收件箱_staging消失_job被刪` 會先紅；
在本檔另抄一顆「insert_photo 直接造已定案列再 PATCH」的版本，
連那個回歸都抓不到（它根本不經過上傳流程），純粹是第二份要維護的複本。

- [ ] 跑這三顆補缺：

```bash
pytest tests/integration/test_design5_error_paths.py -v
```

  **預期：5 passed**（【補7】1、【補8】1、【補9】3〔parametrize 三種進行中狀態〕；
  §4.3 的掃碼還沒貼，貼完才會是 20）。
  首跑就綠是正常的；**紅的先問兩件事**：① 是不是我測試寫錯了？② 還是 52〜70 真的有缺陷？
  是②就回對應的 phase 修產品碼、重跑全量，並在紀錄裡寫清楚修了什麼。

- [ ] **反向驗證**（每一顆 30 秒，證明不是假綠）：
  - 【補7】：把 `assert photo_repository.count_photos() == 0` 改成 `== 1` → 要紅
  - 【補8】：把 `assert data_dir底下的檔案() == []` 改成 `!= []` → 要紅
  - 【補9】：把 `assert response.status_code == 409` 改成 `== 200` → 要紅

### 4.3 「不做」掃碼（§3 九項＋§0 四條＋§1.2 十三列）

「掃碼」＝用測試或指令掃**原始碼／資料庫結構／openapi**，證明某個東西不存在。

先看這張總表：**28 項裡有 25 項可以自動化**，剩下 3 項為什麼不行也寫在表裡。
「✓ 既有／✓ Phase NN」＝已經有人測了，**本檔不重寫**；
「【掃A】〜【掃E】」＝本檔要補的那五段掃碼。

| 出處 | 不做什麼 | 怎麼守 |
|---|---|---|
| §3-1 | 批次歸類、待決定一次勾多張 | 【掃A】掃 `pending.html` 沒有 checkbox／全選 |
| §3-2 | 失敗列手動「再試一次」 | 【掃A】掃 `progress_panel.js` 沒有重試**按鈕的字串字面值**與 retry 命名（⚠ 不能掃裸的 `retry`／`再試`——會誤中狀態名 `retrying` 與輪詢退避的註解，詳見那顆測試的 docstring） |
| §3-3 | 處理狀態欄位進 `photo` 表 | 【掃B】`information_schema` |
| §3-4 | 水平擴 app replica | 【掃C】掃 `compose.yaml` 沒有 `replicas`／`scale` |
| §3-5 | Celery Flower、獨立監控 UI | 【掃C】掃 `compose.yaml`／`requirements.txt` |
| §3-6 | 把 Redis 發佈到區網 | 【掃C】redis 若有 `ports` 必須帶 `127.0.0.1:` 前綴 |
| §3-7 | 雲端物件儲存、S3 | 【掃C】掃 `requirements.txt` |
| §3-8 | 刪除照片端點 | ✓ 既有（Phase 37 `test_openapi裡沒有任何DELETE動詞`）＋【掃E】本檔逐支列名 |
| §3-9 | 詢問流程改版 | **人工**：`git diff --stat` 四個檔（見下方「人工檢查 A」） |
| §0-1 | 乙沒好就把上傳頁改 `multiple` | **人工**：這是**時序**，不是程式狀態（見「人工檢查 B」） |
| §0-2 | 把影像位元組塞進 Redis | 【掃D】`inspect.signature` ＋ 掃 `celery_app.py` |
| §0-3 | 為進度面板新增 `DELETE` | ✓ 既有（Phase 64 `test_ingest_jobs_endpoint.py::test_兩支新端點都在openapi裡而且沒有DELETE`＋Phase 67 `test_關掉失敗列用POST不用DELETE`） |
| §0-4 | 處理中的檔以空白卡出現在待決定 | 【掃E】行為測試：入列後收件箱仍是空的 |
| §1.2-1 | FastAPI BackgroundTasks | 【掃C】掃 `app/` 沒有 `BackgroundTasks` |
| §1.2-2 | 只用 Redis list、自寫 worker 迴圈 | 【掃C】`celery_app.py` 存在且 compose 有 worker |
| §1.2-3 | PDF 每頁一個 Celery 任務 | 【掃D】掃 `ingest_job.py` 沒有 `.delay(` |
| §1.2-4 | 整份 PDF 當重試單位 | ✓ Phase 60（`每頁呼叫次數 == {1: 1, 2: 3}` 那兩顆行為測試） |
| §1.2-5 | 進度只掛在上傳頁 | ✓ 既有（Phase 67 `test_五頁都掛了進度面板`＋`test_手機取景頁刻意沒有掛面板`） |
| §1.2-6 | 成功列留在面板當第二個待決定 | ✓ Phase 60（成功 → job 已刪）＋ Phase 64 `test_成功的任務不會出現在清單裡而待決定加一` |
| §1.2-7 | 待決定改長頁表單／左右分欄 | 【掃A】`pending.html` 仍呼叫 `openFolderModal` |
| §1.2-8 | 處理中先 INSERT 空白 `text` | 【掃E】（同 §0-4） |
| §1.2-9 | 影像位元組當 Celery 參數 | 【掃D】（同 §0-2） |
| §1.2-10 | 關掉失敗列用 `DELETE` | ✓ 既有（同 §0-3） |
| §1.2-11 | 3 個以上 worker | 【掃C】compose 的 `--concurrency=2` |
| §1.2-12 | 把 Ollama 搬進 Docker | 【掃C】compose 沒有 ollama 服務 |
| §1.2-13 | 建議繼續只活在 201 回應、不落庫 | 【掃B】三個建議欄真的在 `photo` 表裡 |
| （全站鐵律） | 前端用 `alert(`／`confirm(`／`prompt(` | ✓ 既有（Phase 67 `test_靜態檔沒有原生對話框且面板零innerHTML`） |
| （增量四遺產） | 把 QR 顯示尺寸改小 | ✓ 既有字串版（`test_camera_endpoints.py`）＋【掃A】本檔數值版（≥ 20rem） |

把下面五段接在 `test_design5_error_paths.py` 後面。

> ⚠️（2026-08-26 校準：**掃碼的時序**）掃 A〜E 要掃的東西**現在有五樣還不存在**——
> `app/celery_app.py`（Phase 65 才建）、`app/static/progress_panel.js`（Phase 67 才建）、
> `compose.yaml` 的 `redis`／`worker` 兩個服務與 `--concurrency=2`（Phase 66 才加）、
> `requirements.txt` 的 `celery`（Phase 65／66 才加）。2026-08-26 實查：
> `app/` 底下 `BackgroundTasks`／`background_tasks` **零命中**（那一條今天就成立）、
> `pending.html` 有 `openFolderModal(` 且無 `type="checkbox"`／「全選」、
> `.cd-qr svg` 的 `max-width` 是 `20rem`、`photo` 表四個建議欄都在、
> `test_design3_error_paths.py` 的 `可以碰資料庫的檔案` 恰兩個檔——這幾條也今天就成立。
> 所以**這一整節要等 §2 的前置條件（52〜70 全部完成）成立才跑得起來**；
> 提前跑會紅在「檔案不存在」，那不是缺陷，是順序沒到。

**【掃A】前端掃碼**

```python
# ----【掃A】§3「不做」與 §1.2「被否決」：前端掃碼 ----
#
# ⚠ 這三項**已經有人測了，本檔不重寫**（重複的測試是負債）：
#   §1.2 第 5 列（進度面板五頁都要在）→ Phase 67 test_progress_panel_contract.py
#                                         ::test_五頁都掛了進度面板
#                                         ＋ ::test_手機取景頁刻意沒有掛面板
#   §0 第 3 條／§1.2 第 10 列（不用 DELETE）→ 同檔 ::test_關掉失敗列用POST不用DELETE
#   全站禁用原生對話框                      → 同檔 ::test_靜態檔沒有原生對話框且面板零innerHTML
# 本段只補真缺口。

前端目錄 = 專案根目錄 / "app" / "static"


def test_待決定頁沒有批次勾選也仍然用彈窗():
    """§3 第 1 列（不做批次歸類）＋ §1.2 第 7 列（不做長頁表單／左右分欄）。"""
    原始碼 = (前端目錄 / "pending.html").read_text(encoding="utf-8")

    assert 'type="checkbox"' not in 原始碼, "待決定不做一次勾多張"
    assert "全選" not in 原始碼
    assert "openFolderModal(" in 原始碼, "待決定的歸類入口仍然是彈窗（產品負責人選 A）"


def test_進度面板沒有再試一次():
    """§3 第 2 列：失敗列不做手動「再試一次」。自動 3 次已經做完；要重來就重新選檔／重拍。

    有「再試一次」按鈕的話，它背後必然要重讀 staging——但 staging 在最終失敗時
    就已經刪掉了，按下去只會得到一個查不到檔案的錯誤。

    ⚠ 關鍵字刻意收得很窄，寬一點的字**全部**會假紅（Phase 67 §7 陷阱 14 記了同一件事）：
      - 不能掃裸的 "retry"：`retrying` 是 JobStore 四個狀態之一（契約備忘 §3.1 的
        JOB_STATUSES），面板處理狀態的程式碼與註解裡**合法地**含有這五個字母。
      - 也不能掃裸的「再試」「再試一次」：面板自己的**輪詢退避**就叫「再試」——
        progress_panel.js 的退避常數註解寫著「…毫秒才再試一次」、連線失敗的
        console 訊息寫著「稍後會自己再試」。那是面板重打 GET /ingest-jobs，
        不是幫失敗的任務重跑，語意完全不同，不是本規則要禁的東西。
      真正要擋的是「給使用者按的重試」。本檔零 innerHTML（Phase 67 契約），
      按鈕文案一定走 textContent ＝ 一個**帶引號的字串字面值**；而做這顆按鈕的人
      第一步一定會取一個 retry 命名。掃這兩種就夠，而且**只**掃這兩種。
    """
    原始碼 = (前端目錄 / "progress_panel.js").read_text(encoding="utf-8")

    # 防呆錨點：確認掃的真的是進度面板（檔案被改名／搬走要紅在這裡，不是默默全過）
    assert "ppDismiss(" in 原始碼, "progress_panel.js 應該要有 ppDismiss（× 關失敗列）"

    # ① 重試按鈕的字串字面值（雙引號是全檔一致的風格，單引號一起擋以防手滑；
    #    「重試」用開引號＋詞，連 "重試中（第 N 次）" 這種帶後綴的顯示措辭一起攔）
    for 字面值 in ('"再試一次"', "'再試一次'", '"Retry"', "'Retry'", '"重試', "'重試"):
        assert 字面值 not in 原始碼, f"進度面板不做手動重試／不顯示重試措辭：{字面值}"

    # ② retry 命名的類名或函式名
    for 識別字 in ("pp-retry", "ppRetry"):
        assert 識別字 not in 原始碼, f"進度面板不做手動重試：{識別字}"


def test_QR的顯示尺寸不准改小():
    """增量四唯一一次改產品 CSS（2026-08-25 真機驗收時修的）。

    Bonjour 主機名讓網址從 93 變 118 字元、QR 從 49 格變 53 格；
    當時 max-width 是 15rem（240px），每格只剩 4.5px，**iPhone 掃不到**——
    QR 畫得出來、只是掃不進去，是典型的安靜壞掉。
    改成 20rem（320px）之後每格 6.0px，兩種網址都好掃。

    既有 test_camera_endpoints.py 那顆比對的是**整行字串**；這一顆改成**比大小**，
    所以有人把 20rem 調成 24rem（更大）不會誤紅，調成 18rem 才會紅。
    """
    樣式 = (前端目錄 / "style.css").read_text(encoding="utf-8")

    比對 = re.search(r"\.cd-qr svg \{[^}]*max-width:\s*([\d.]+)rem", 樣式)
    assert 比對, "找不到 .cd-qr svg 的 max-width（那一行是 QR 可掃性的唯一保證）"
    assert float(比對.group(1)) >= 20, (
        f"QR 顯示尺寸不可以小於 20rem（現在是 {比對.group(1)}rem）——"
        "小於這個值長網址的 QR 會掃不到"
    )
```

**【掃B】資料庫結構掃碼**

```python
# ----【掃B】§3 第 3 列／§1.2 第 13 列：photo 表該有什麼、不該有什麼 ----

# 「處理到哪了」這種狀態一律住在 JobStore（Redis／記憶體），不進 photo 表。
# design5 §11 末句明文：「photo 表只加建議欄，不加處理狀態、不加 job_id
# （冪等靠 JobStore 的 photo_ids）」。
禁止出現在photo表的欄位 = {
    "status", "state", "processing_status", "ingest_status",
    "job_id", "ingest_job_id", "progress", "attempt", "retry_count",
}

# design5 D16：建議隨入庫落庫，待決定開窗再讀（Phase 56 加的三欄＋Phase 35 那一欄）
必須出現在photo表的欄位 = {
    "suggested_category", "suggested_entity",
    "suggested_task_title", "suggested_task_due",
}


def photo表的欄位() -> set[str]:
    """用 information_schema 問資料庫「photo 表有哪些欄位」。

    conftest 已經把 DATABASE_URL 指到測試庫，所以問的是測試庫的結構——
    而測試庫是用 db/schema.sql 重建的，與正式庫走同一份遷移對齊（design5 §11）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'photo'
                ORDER BY column_name;
                """
            )
            return {row["column_name"] for row in cur.fetchall()}


def test_photo表沒有處理狀態欄也沒有job_id欄():
    """§3 第 3 列：處理狀態不進 photo 表。

    為什麼不能加：加了之後「這張照片存在嗎」就有兩種答案（列在不在 vs 狀態是什麼），
    待決定牆一定會在某個時間點畫出空白卡（design5 §1.2 第 8 列否決的正是那個方案）。
    """
    欄位 = photo表的欄位()

    違規 = 欄位 & 禁止出現在photo表的欄位
    assert 違規 == set(), f"處理狀態只能住在 JobStore，不可以進 photo 表：{違規}"


def test_photo表有D16的四個建議欄():
    """§1.2 第 13 列：建議不能只活在回應裡——202 之後回應根本沒有建議。"""
    欄位 = photo表的欄位()

    缺的 = 必須出現在photo表的欄位 - 欄位
    assert 缺的 == set(), f"D16 的建議欄少了：{缺的}"
```

**【掃C】設定檔與相依掃碼**

```python
# ----【掃C】§3 第 4〜7 列、§1.2 第 1／2／11／12 列：compose 與 requirements ----


def compose原始碼() -> str:
    return (專案根目錄 / "compose.yaml").read_text(encoding="utf-8")


def test_worker只開兩個子行程():
    """design5 D6／§1.2 第 11 列：產品負責人明定上限 2。

    本機看圖會把機器打掛（Phase 48 已經踩過：兩件事同時打，db container 被壓垮、
    postmaster 花 2 分鐘才殺得掉子行程）。
    """
    assert "--concurrency=2" in compose原始碼(), (
        "worker 的 concurrency 必須恰好是 2（design5 D6）"
    )
    assert "--concurrency=3" not in compose原始碼()
    assert "--concurrency=4" not in compose原始碼()


def test_compose沒有replica也沒有flower也沒有ollama():
    """三條「不做」一起掃（§3 第 4／5 列、§1.2 第 12 列）。

    - replicas：鏡頭配對 session 存在 app 的記憶體裡，兩個行程會配對失敗
    - flower：Celery 的監控 UI，side project 不需要第二個網頁介面
    - ollama：Docker 裡是 Linux VM，沒有 MLX、也吃不到這台 Mac 的 GPU
    """
    原始碼 = compose原始碼()

    for 關鍵字 in ("replicas", "flower", "ollama:", "image: ollama"):
        assert 關鍵字 not in 原始碼, f"compose.yaml 不該出現：{關鍵字}"


def test_redis沒有發佈到區網():
    """§3 第 6 列：Redis 不設密碼，發佈到 0.0.0.0 等於把佇列開放給整個 Wi-Fi。

    做法：redis 服務底下**要嘛沒有 ports**（只走 compose 內部網路，最安全），
    要嘛每一條 ports 都帶 127.0.0.1: 前綴。
    """
    原始碼 = compose原始碼()
    redis區塊 = re.search(r"\n  redis:\n(.*?)(?=\n  \w|\nvolumes:)", 原始碼, re.S)
    assert redis區塊, "compose.yaml 裡找不到 redis 服務"

    for 一行 in redis區塊.group(1).splitlines():
        if re.match(r'\s*-\s*"?\d', 一行):        # 形如   - "6379:6379"
            assert "127.0.0.1:" in 一行, (
                f"Redis 只能綁本機，不可以發佈到區網：{一行.strip()}"
            )


def test_沒有背景任務框架的替代品也沒有雲端儲存():
    """§1.2 第 1／2 列＋§3 第 7 列。"""
    app目錄原始碼 = "".join(
        檔案.read_text(encoding="utf-8")
        for 檔案 in sorted((專案根目錄 / "app").rglob("*.py"))
    )
    需求 = (專案根目錄 / "requirements.txt").read_text(encoding="utf-8").lower()

    # §1.2 第 1 列：不用 FastAPI BackgroundTasks（與 uvicorn 同行程，restart 會丟工作）
    assert "BackgroundTasks" not in app目錄原始碼
    assert "background_tasks" not in app目錄原始碼
    # §1.2 第 2 列：用的是 Celery，不是自寫的 Redis list 消費迴圈
    assert "celery" in 需求
    assert (專案根目錄 / "app" / "celery_app.py").exists()
    # §3 第 7 列：不做雲端物件儲存
    for 關鍵字 in ("boto3", "s3fs", "minio", "google-cloud-storage"):
        assert 關鍵字 not in 需求, f"不做雲端物件儲存：{關鍵字}"
    # §3 第 5 列：不裝 Flower
    assert "flower" not in 需求
```

**【掃D】任務參數掃碼（影像位元組不准進 Redis）**

```python
# ----【掃D】§0 第 2 條／§1.2 第 3／9 列：任務只帶 job_id ----


def 註記文字(參數: inspect.Parameter) -> str:
    """把型別註記統一成字串。

    模組如果有 `from __future__ import annotations`，註記本來就是字串；
    沒有的話是真的型別物件——兩種都要處理得了。
    """
    註記 = 參數.annotation
    if isinstance(註記, str):
        return 註記
    return getattr(註記, "__name__", str(註記))


def test_任務本體只吃job_id不吃影像位元組():
    """design5 §0 禁止第 2 條：影像位元組不准塞進 Redis。

    多頁 PDF 動輒好幾 MB，塞進 Redis 會讓佇列變成檔案伺服器（而且 AOF 會跟著爆）。
    圖走磁碟（data/staging），任務只帶一個 job_id。
    """
    參數 = inspect.signature(run_ingest_job).parameters

    assert list(參數)[0] == "job_id", "第一個參數必須是 job_id"
    assert 註記文字(參數["job_id"]) == "str"
    帶位元組的 = [
        名稱 for 名稱, 參數值 in 參數.items() if "bytes" in 註記文字(參數值)
    ]
    assert 帶位元組的 == [], f"任務不可以吃影像位元組：{帶位元組的}"


def test_Celery任務也只吃job_id():
    """Celery 那一層是薄薄的 wrapper（design5 D15），參數要跟任務本體一致。"""
    celery原始碼 = (專案根目錄 / "app" / "celery_app.py").read_text(encoding="utf-8")

    assert re.search(r"def ingest_task\(\s*job_id:\s*str\s*\)", celery原始碼), (
        "ingest_task 的簽章必須恰好是 (job_id: str)"
    )
    for 關鍵字 in ("bytes", "base64", "image_data", "payload"):
        assert 關鍵字 not in celery原始碼, f"Celery 任務不可以碰位元組：{關鍵字}"


def test_PDF不是每頁一個任務():
    """§1.2 第 3 列：一個 Celery 任務 ＝ 一個檔案（D11）。

    做法上就是「任務本體裡不准再丟任務」——所以 ingest_job.py 不該出現 .delay(。
    每頁一個任務的話，同一份檔會被兩個 worker 拆開跑，進度列也畫不出來。
    """
    任務原始碼 = (
        專案根目錄 / "app" / "services" / "ingest_job.py"
    ).read_text(encoding="utf-8")

    assert ".delay(" not in 任務原始碼
    assert ".apply_async(" not in 任務原始碼


def test_SQL掃碼真的有看到增量五的新檔():
    """既有那顆 test_SQL只出現在repository與db層 是 rglob("*.py")，新檔自動納入。

    這一顆不是重測 SQL，是**證明那顆掃碼掃得到新檔**——
    擋的是「有人為了讓 worker 方便，把新檔加進豁免名單」。
    """
    from tests.integration.test_design3_error_paths import 可以碰資料庫的檔案

    for 新檔 in (
        "app/services/ingest_job.py",
        "app/services/ingest_job_store.py",
        "app/services/staging_service.py",
        "app/celery_app.py",
        "app/api/routers/ingest_jobs.py",
    ):
        assert (專案根目錄 / 新檔).exists(), f"增量五應該有這個檔：{新檔}"
        assert 新檔 not in 可以碰資料庫的檔案, (
            f"{新檔} 不可以被加進「可以寫 SQL」的豁免名單"
        )
```

**【掃E】端點清點與「不出現空白卡」**

```python
# ----【掃E-1】§5：端點恰 22、零 DELETE，而且是**這 22 支** ----

# 逐支列名，不只是數總數。總數對但少一支多一支的情況，只數總數是抓不到的。
# （2026-08-26 校準：下面這 22 支已與 Phase 64 之後的實際 /openapi.json 逐支比對過，
#   一支不多、一支不少；總數的把關另有 test_ask_three_paths.py::test_端點數不變
#   與 test_nav_header.py::test_端點數仍為22 兩顆既有測試。）
增量五之後的端點 = {
    ("/", "get"),
    ("/health", "get"),
    ("/photos", "post"),
    ("/photos/{photo_id}", "get"),
    ("/photos/{photo_id}/image", "get"),
    ("/photos/{photo_id}/thumbnail", "get"),
    ("/photos/{photo_id}/folder", "patch"),
    ("/photos/{photo_id}/entities", "post"),
    ("/photos/{photo_id}/entity-suggestion", "post"),
    ("/photos/{photo_id}/task", "post"),
    ("/folders", "get"),
    ("/folders/{folder_id}", "get"),
    ("/entities", "get"),
    ("/tasks", "get"),
    ("/ask", "post"),
    ("/settings/ai-backend", "get"),
    ("/settings/ai-backend", "put"),
    ("/camera/session", "post"),
    ("/camera/{token}/photos", "post"),
    ("/camera/{token}/latest", "get"),
    ("/ingest-jobs", "get"),                      # ★ Phase 64 新增
    ("/ingest-jobs/{job_id}/dismiss", "post"),    # ★ Phase 64 新增
}


def test_端點恰好是這22支(client):
    """§5：20 → 22。信令用的 WebSocket 依 FastAPI 的行為不進 openapi，所以不計入。

    既有 test_ask_three_paths.py::test_端點數不變 守的是**總數**；
    這一顆守的是**清單**——擋「刪了一支又加了一支，總數剛好還是 22」。
    """
    paths = client.get("/openapi.json").json()["paths"]
    實際 = {(路徑, 動詞) for 路徑, item in paths.items() for 動詞 in item}

    assert 實際 == 增量五之後的端點, (
        f"多出來：{sorted(實際 - 增量五之後的端點)}；"
        f"少掉了：{sorted(增量五之後的端點 - 實際)}"
    )
    assert len(實際) == 22


# 「dismiss 那一支是 POST 不是 DELETE」由 Phase 67 的
# test_progress_panel_contract.py::test_關掉失敗列用POST不用DELETE 守著；
# 「openapi 完全沒有 DELETE 動詞」由 Phase 37 的
# test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞 守著。本檔不重寫。


# ----【掃E-2】§0 禁止第 4 條／§1.2 第 8 列：處理中的檔不准以空白卡出現在待決定 ----


def test_入列當下待決定牆完全沒有動靜(client, job_store):
    """202 只代表「檔案收下了」，不代表「照片存在了」（design5 D7、§4.2）。

    待決定牆查的是收件箱，而收件箱裡只有 INSERT 過的列——
    只要沒有人偷偷先 INSERT 一列空白的，牆上就不可能出現空白卡。
    """
    收件箱 = photo_repository.find_folder_by_name("未分類")

    job_id = 入列(client)

    assert photo_repository.count_photos() == 0
    detail = client.get(f"/folders/{收件箱['id']}").json()
    assert detail["photos"] == [], "分析還沒成功，待決定牆上不該有任何卡片"
    assert client.get("/ingest-jobs").json()["pending_count"] == 0
    # 但是暫存檔要在、job 要是 queued——不然 worker 等一下沒東西可做
    assert staging_service.staging_path(job_id, "image/png").exists()
    assert job_store.get(job_id)["status"] == "queued"
```

- [ ] 跑全檔：

```bash
pytest tests/integration/test_design5_error_paths.py -v
```

  **預期：20 passed**（5 顆補缺〔【補7】1＋【補8】1＋【補9】3〕＋ 15 顆掃碼
  〔掃A 3＋掃B 2＋掃C 4＋掃D 4＋掃E 2〕）。

### 4.4 三項不能自動化的，改成人工檢查

**人工檢查 A — §3 第 9 列「不做詢問流程改版」**

不能自動化的理由：這是「**沒有改動**」，不是「某個東西不存在」。
測試只能斷言程式現在長什麼樣，沒辦法斷言「它跟三週前一樣」——那是版本控制的工作。

```bash
git diff --stat 4345846 -- app/services/ask_workflow.py \
                            app/services/retrieval_service.py \
                            app/api/routers/ask.py app/schemas/ask.py
```

- [ ] **預期：完全沒有輸出。**（`4345846` 是增量四收尾（Phase 45〜51）那個 commit＝
      **增量五的開工基準**。⚠ 不要拿 `6392270`（增量三收尾）當基準——
      增量四的 Phase 41〜43 把 AI 計時 log 接進了詢問那幾個檔（在 `507a18f`），
      用它比對會把增量四的**合法**改動誤報成「增量五改了檢索」。）
      有輸出就逐行看：是不是有人為了非同步順手改了檢索。

**人工檢查 B — §0 禁止第 1 條「乙沒好就把上傳頁改 `multiple` 卻仍同步」**

不能自動化的理由：這是**時序**問題（「在什麼時候做了什麼」），不是最終狀態。
現在 62〜68 全部做完了，`multiple` 本來就該在、上傳本來就該是非同步——
兩件事都成立，測試看不出當初有沒有搶跑。

- [ ] 用 phase 順序證明：`docs/plan/unfinish/` 裡 `phase-68-上傳頁多檔選檔.md`
      的「前置條件」寫著依賴 62 與 67。做的人照著順序走就不會搶跑。
- [ ] 現況再確認一次（兩件事必須**同時**成立）：

```bash
grep -n "multiple" app/static/upload.html          # 要有
grep -n "202" app/static/upload.html               # 要有（前端在等 202，不是 201）
grep -n "startClassifyChain" app/static/upload.html # 要**沒有**（Phase 68 已拿掉）
```

**人工檢查 C — 重建映像之後的手動煙霧**

不能自動化的理由：`requirements.txt` 全部是 `>=`，映像是在 build 當下才解析版本的，
所以 **host 的 `.venv` 與容器裡的套件會慢慢分岔**（design4 已知落差、design5 §13 再列一次）。
`pytest -q` 全綠驗的是 **host 那一份環境**，不等於驗過實際在跑的映像。

- [ ] 加了 `celery` 與 `redis` 兩個套件之後，**至少手動走一次**：

```bash
docker compose -f compose.yaml build app
docker compose -f compose.yaml up -d
docker compose -f compose.yaml logs -f app worker
```

  然後在瀏覽器（`https://localhost:8000/ui/upload.html`，頁首開關先撥到**雲端**）
  上傳一張圖 → 右下角出現一列進度 → 列消失、頂欄「待決定（N）」+1 →
  到待決定頁點開，三關走得完。

### 4.5 全量回歸

- [ ] 全量：

```bash
pytest -q
```

  **預期：全綠、`0 skipped`**（`skipped` 那一段從 Phase 51 摘標之後就整個消失了，
  pytest 不會印 `0 skipped`，那是正常的）。
  顆數 ＝ 開工基準 ＋ 20。填進來：基準 ＿＿＿ → 完成 ＿＿＿。

- [ ] **零 Redis 依賴實證**（本增量新增的那一輪；顆數必須完全相同）：

```bash
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q
```

  埠 9 沒有任何東西在聽。顆數一樣 ＝ 證明 pytest 從頭到尾**沒有連過 Redis**
  （design5 D15／§9）。**顆數不一樣、或出現連線逾時**，代表某條路徑真的去打了 broker
  ——最常見的原因是某顆測試呼叫了 `ingest_task.delay(...)` 而不是 `run_ingest_job(...)`。

- [ ] **零 Ollama 依賴實證**（既有手法，繼續跑）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

- [ ] **兩個一起指死**（最強的一輪）：

```bash
CELERY_BROKER_URL=redis://127.0.0.1:9/0 OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

- [ ] 三份規格 binder 單獨再跑一次（確認 `.feature` 沒被本增量波及）：

```bash
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
       tests/integration/test_camera_feature.py -v
```

  預期：全綠，**`-v` 的輸出裡一個 `SKIPPED` 都沒有**。

- [ ] 規格檔真的一個字都沒改（★G3 還沒過）：

```bash
git status --short docs/spec/
```

  預期：**乾淨的**（沒有任何輸出）。

### 4.6 正式庫健檢（四個查詢）

```bash
psql -d PersonalDocAI
```

在 psql 裡逐句執行：

```sql
-- a) 六個預設資料夾在，且全系統只有一個收件箱
SELECT id, name, is_inbox FROM folder ORDER BY id;
SELECT count(*) AS 收件箱數 FROM folder WHERE is_inbox;

-- b) 每一張照片都掛在某個資料夾底下，而且 category 與資料夾名稱一致
SELECT count(*) AS 沒有資料夾的照片 FROM photo WHERE folder_id IS NULL;
SELECT count(*) AS 對不起來的列
FROM photo p JOIN folder f ON f.id = p.folder_id
WHERE p.category IS DISTINCT FROM f.name;

-- c) ★ 增量五的四個建議欄真的在，而且舊照片是 NULL（不是空字串）
SELECT count(*) AS 總列數,
       count(suggested_category)   AS 有資料夾建議,
       count(suggested_entity)     AS 有實體建議,
       count(suggested_task_title) AS 有待辦建議
FROM photo;

-- d) ★ 沒有孤兒列：有路徑的列都是分析成功才寫進來的
SELECT count(*) AS 有列但沒文字 FROM photo WHERE text IS NULL OR btrim(text) = '';
```

**預期**：

| 查詢 | 預期結果 |
|---|---|
| a | 至少 6 列（`1 未分類 t`、`2 收據 f`、`3 飲食 f`、`4 風景 f`、`5 文件 f`、`6 其他 f`，自建的排在 7 之後）；收件箱數 ＝ **1** |
| b | 兩個都是 **0** |
| c | 四個欄位都查得出來（**不會噴 `column does not exist`**）；`有實體建議`／`有待辦建議` 通常遠小於總列數（大多數照片沒有這兩種建議），那是正常的 |
| d | **0**——「`text` 為空的記錄不存在」這條鐵律（design5 §1.2 第 8 列）在正式庫也成立 |

離開 psql：`\q`。

- [ ] 順便看一眼暫存區沒有留垃圾：

```bash
ls -la data/staging/ 2>/dev/null || echo "（還沒有任何暫存檔，這也正常）"
find data/staging -type f -mmin +1440 2>/dev/null | head
```

  第二行的預期：**沒有輸出**（`-mmin +1440` ＝超過 24 小時沒被動過的檔案；
  真的有的話就是 `sweep_stale_staging` 那把掃把沒被呼叫到，回 Phase 58 看）。

### 4.7 四個服務都在

```bash
docker compose ps --no-trunc
```

- [ ] **預期：四列**——`db`（`Up (healthy)`）、`redis`（`Up (healthy)`）、
      `app`（`Up`）、`worker`（`Up`）。
- [ ] `worker` 那一列的 `COMMAND` 欄裡看得到 **`--concurrency=2`**。
      （`--no-trunc` 不能省：不加的話 `COMMAND` 只印開頭 20 個字左右，結尾的旗標根本不會顯示。）

---

## 5. ASCII 圖：10 列錯誤各自在哪一層被攔下（以及誰的測試守著）

「P59」＝Phase 59 的測試檔、「本檔」＝ `test_design5_error_paths.py`，
測試全名見 §4.1 的對照表。

```text
 ══════════════════════════════════════════════════════════════════════════
  HTTP 層（app 容器，同步；使用者當場看得到）
 ══════════════════════════════════════════════════════════════════════════
   POST /photos ／ POST /camera/{token}/photos
        │
        ├─【2】token 無效／過期 ──────► 404      無 job、無 staging、**不讀檔**
        │     （鏡頭那一支：token 先驗，格式後驗）  └─ P63 三顆＋既有「404 先於 415」
        │
        ├─【1】非 JPEG／PNG／PDF ─────► 415      無 job、無 staging
        │                                          └─ P62 415不建任務也不寫staging
        │
        ├─ 落 staging（data/staging/{job_id}.jpg|.png|.pdf）
        │        │
        ├─【8】JobStore 寫不進去 ─────► 500      ★ 要把剛落地的 staging 刪掉
        │     （＝Redis 掛了的一半）               └─ 本檔【補8】
        │
        ├─ 建 job（status=queued）
        │
        ├─【8】丟不進 Celery 佇列 ────► 500      ★ 一樣要刪剛落地的 staging
        │     （＝Redis 掛了的另一半）             └─ P62 入列失敗時回500
        │
        └─ 202 {job_id, filename, content_type}
                 │
                 │  ⚠ 這一刻 photo 表**列數不變**
                 │     待決定牆是空的、pending_count 不變 ── 本檔【掃E-2】
                 ▼
 ══════════════════════════════════════════════════════════════════════════
  worker 層（Celery，非同步；使用者只從進度面板看得到）
 ══════════════════════════════════════════════════════════════════════════
   run_ingest_job(job_id)  ← 只吃 job_id，圖從磁碟讀（本檔【掃D】）
        │
        │  status = analyzing
        │
        ├── JPEG／PNG ────────────────────────────────────────────────┐
        │     每張最多 3 次（含第一次）                                │
        │       ├─【3】看不懂 ×3 ──────────┐                          │
        │       ├─【3】連線失敗 ×3 ────────┤                          │
        │       └─【6】embedding 失敗 ×3 ──┤ 三種都吃同一份額度       │
        │                                  ▼                          │
        │                       刪 staging、無 photo 列、job=failed    │
        │                       進度面板留一列（可按 × 關掉）           │
        │                       └─ P59 三顆＋P63／P64 端點視角          │
        │       │                                                     │
        │       └─ 成功 ─► INSERT（收件箱）                            │
        │                    │                                        │
        │                    ├─【7】存原圖失敗 ──┐ 清半成品            │
        │                    ├─【7】產縮圖失敗 ──┤ ＋ delete_photo     │
        │                    │                   ▼                    │
        │                    │        無孤兒列、無半個檔、job=failed    │
        │                    │        └─ 原圖＝本檔【補7】；            │
        │                    │           縮圖＝P59＋P62 那兩顆          │
        │                    │                                        │
        │                    └─ 成功 ─► 刪 staging、**delete(job)**    │
        │                               進度列消失、待決定 N ＋1        │
        │                                                             │
        └── PDF ─────────────────────────────────────────────────────┘
              拆頁（拆不了＝【5】後半：0 次模型呼叫就整筆失敗）
              逐頁依序，**每頁**各自最多 3 次
                ├─【4】某頁 ×3 ─► 跳過那一頁，其他頁繼續
                │                  └─ P60（每頁呼叫次數 {1:1, 2:3}）
                └─【5】0 頁成功 ─► 與【3】相同下場
                                   └─ P60 兩顆（全滅＋壞檔 0 次呼叫）

 ══════════════════════════════════════════════════════════════════════════
  既有層（本增量不改，但要證明沒被弄壞）
 ══════════════════════════════════════════════════════════════════════════
   POST /ingest-jobs/{job_id}/dismiss
        ├─【9】那筆還在跑 ───────────► 409     那一列仍留在清單上
        │        └─ queued＝P64；analyzing／retrying＝本檔【補9】
        ├─    找不到 ────────────────► 404     P64
        └─    是 failed ─────────────► 204     從清單消失（P64）

   PATCH /photos/{id}/folder
        └─【10】照片已定案 ──────────► 409     資料夾一個字都沒變
                （design2 D3，本增量未推翻）     └─ 既有 test_assign_folder.py
```

---

## 6. 驗收清單

- [ ] §4.1 的 10 列盤點做完，表格反映**事實**（不是抄的）
- [ ] `pytest tests/integration/test_design5_error_paths.py -v` ＝ **20 passed**（5 補缺〔補7 1＋補8 1＋補9 3〕＋ 15 掃碼〔掃A 3＋掃B 2＋掃C 4＋掃D 4＋掃E 2〕）
- [ ] 至少四顆做過**反向驗證**（斷言反過來會紅）＝證明不是假綠——【補7】【補8】【補9】各一次（§4.2 末的三條）＋ QR 數值版一次（把 `>= 20` 暫改 `>= 25` 要紅）
- [ ] `pytest -q` 全綠、**0 skipped**；顆數 ＝ 開工基準 ＋20（基準 ＿＿＿ → 完成 ＿＿＿）
- [ ] `CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q` 顆數**完全相同**（零 Redis 依賴實證）
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數**完全相同**
- [ ] 兩個環境變數同時指死埠跑一輪，顆數仍然相同
- [ ] `/openapi.json` 端點 ＝ **22**，而且**逐支對得上** §4.3【掃E】那份清單；DELETE ＝ **0**
- [ ] `photo` 表用 `information_schema` 查過：**沒有**處理狀態欄、**沒有** `job_id`；
      **有** D16 的四個建議欄
- [ ] `compose.yaml` 掃過：`--concurrency=2`、沒有 replicas／flower／ollama、redis 沒發佈到區網
- [ ] `run_ingest_job` 與 `ingest_task` 的簽章都只吃 `job_id`，沒有任何 `bytes` 參數
- [ ] 前端掃過（本檔補的）：待決定沒有勾選；面板沒有重試**按鈕字面值**與 retry 命名（關鍵字收窄的理由見那顆測試的 docstring）
- [ ] 前端掃過（既有的仍綠，只跑不改）：

```bash
pytest tests/integration/test_progress_panel_contract.py -v
```

  預期：全綠——`test_五頁都掛了進度面板`、`test_手機取景頁刻意沒有掛面板`、
  `test_關掉失敗列用POST不用DELETE`、`test_靜態檔沒有原生對話框且面板零innerHTML` 都在裡面
- [ ] `.cd-qr svg` 的 `max-width` **≥ 20rem**（新的數值版測試綠，既有的字串版也綠）
- [ ] 三份規格 binder 全綠、零 SKIPPED
- [ ] `git status --short docs/spec/` **乾淨**（★G3 還沒過，一個字都沒動）
- [ ] 人工檢查 A（詢問流程零改動）、B（上傳頁三個 grep）、C（重建映像後手動煙霧）各做過一次
- [ ] 正式庫四個查詢全部符合預期；`find data/staging -mmin +1440` 無輸出
- [ ] `docker compose ps --no-trunc` ＝ **四個服務**，`worker` 的 COMMAND 有 `--concurrency=2`
- [ ] 本 phase **沒有改到任何產品程式碼**：

```bash
git status --short -- app/ compose.yaml db/ requirements.txt
```

  預期：與開工前**完全相同**（本 phase 只該多出 `?? tests/integration/test_design5_error_paths.py`）。
  `app/` 底下若多出新的 `M`，代表你改了不該改的——除非那是「揪到真缺陷、回原 phase 修」的結果，
  那就要在紀錄裡寫清楚修了什麼、並重跑全量。

- [ ] **沒有 commit**；`unfinish/` → `finish/` 的歸檔留給 Phase 72 §4.9

---

## 7. 常見陷阱

1. **在測試裡自己 `new` 一顆 `InMemoryJobStore`。**
   症狀：`job_store.get(job_id)` 一律回 `None`，或 `list_open()` 永遠是空的，
   斷言「沒有 job」永遠成立——**假綠**。
   原因：端點寫進去的是 conftest 覆寫的**那一顆**，你手上的是另一顆。
   修法：用 §4.2 那個 `job_store` fixture，它拿的是 `wire_memory_job_store` 交出來的同一顆。

2. **忘了 staging 也住在 `DATA_DIR` 底下。**
   `data_dir底下的檔案()` 會把 `data/staging/*` 一起算進去。
   所以「入列之後」那一刻它**不是**空的（【掃E-2】那顆就是在驗這件事）；
   只有在**最終成功或最終失敗之後**才該是空的。
   把 `assert data_dir底下的檔案() == []` 放錯位置，會得到一顆莫名其妙的紅。

3. **全量回歸時 Phase 59／60 的呼叫次數斷言紅了（`vlm.calls`／`每頁呼叫次數`），以為是測試寫錯。**
   先看數字差在哪：
   - 單圖跑出 **1** 次 → 實作根本沒重試（`VLM_MAX_ATTEMPTS` 沒接上）
   - 單圖跑出 **9** 次 → 重試迴圈套了兩層（Celery `autoretry` ＋ 函式內迴圈），
     那正是 design5 §4.4 明文禁止的組合
   - PDF 跑出 `{1: 2, 2: 2, 3: 2}` 這類**每頁平均分攤**的形狀（而不是 `{1: 1, 2: 3}`）
     → 用整份 PDF 當重試單位（§1.2 第 4 列否決）
   三種都是**產品碼**的問題，回 Phase 59／60 修，不要改測試的數字。

4. **`run_ingest_job` 把例外往外丟。**
   症狀：測試裡 `跑任務(...)` 直接炸掉，還沒跑到 assert。
   這代表實作讓例外逃出去了——Celery 收到例外會把任務標記失敗，
   而且（若有人順手開了 `autoretry_for`）會**整份重跑**，已經 INSERT 的 JPEG 會再插一次。
   design5 §4.4 要的是「任務函式**自己**吞下去、自己把 job 標成 failed」。
   回 Phase 59 修，不要在測試裡包 `pytest.raises` 遮過去。

5. **Phase 67 那顆 `test_靜態檔沒有原生對話框且面板零innerHTML` 假紅。**
   最可能是有人在註解裡寫了 `alert()`（帶括號）。
   三支彈窗檔頭當初刻意寫成「一律不用 alert／confirm／prompt」（**沒有括號**），
   `folder_modal.js` 第 7 行還特別留了一句說明。要寫註解就照那個寫法，不要加括號。

6. **`redis` 區塊的正規表示式抓不到。**
   `test_redis沒有發佈到區網` 用 `\n  redis:\n` 定位，**縮排是兩個空格**。
   如果 Phase 66 把服務名寫成別的（例如 `broker:`），那顆會直接紅在
   「compose.yaml 裡找不到 redis 服務」。改測試裡的服務名，
   **不要**去改 compose——服務名是 `CELERY_BROKER_URL=redis://redis:6379/0` 的主機名，
   改了連線就斷了。

7. **以為「掃碼」是掃 QR code。**
   不是。是掃**原始碼**。這個詞從 Phase 44 沿用下來，
   而本專案剛好又真的有一個 QR code（無線鏡頭），所以特別容易混淆。
   §4.3 那一整節沒有任何一步需要拿手機出來。

8. **為了「湊滿十列」而重複測。**
   §4.1 的盤點就是在防這件事：十列裡有七列已由 Phase 59〜64 完整測過，
   本檔才只有三顆補缺。看到「本檔怎麼只測三列」手癢想補齊的話，
   先回去讀 §4.1 的 ✓ 欄——**點名也是把關**。
   重複的測試是負債：改一次程式要改兩個地方，而且兩個地方遲早會不一致。

9. **只跑新檔就收工。**
   一定要跑全量，而且要跑**兩個死埠**那幾輪。
   本 phase 動到的是 conftest 級別的東西（`job_store` fixture 依賴第四道安全網），
   只跑一個檔看不出有沒有波及別人。

10. **看到「20 passed」就以為 §3／§1.2 全部守住了。**
    §4.4 那三項是**人工**的，測試跑再多次也不會幫你做。
    特別是 C（重建映像後的手動煙霧）——`pytest -q` 驗的是 host 的 `.venv`，
    不是實際在跑的映像。加了 celery／redis 兩個新套件之後，這一步不能省。
