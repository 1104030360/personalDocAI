# Phase 81：雲端路 PDF

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**順手做的三件事：
> ① 不要碰 boto3／不要打任何 `aws` 指令（★G1 就在本 phase 之後，還沒過）；
> ② 不要把工人拆好的每頁 PNG 放進 S3（本機自己再拆一次就好，總覽 §10.2 F）；
> ③ 不要為 PDF 開第二種任務（一份 PDF 仍然是**一個** job，design5 D11 沒有被推翻）。

> 🎯 **一句話目標：** 讓 PDF 也能走雲端路——`submit` 送 `input.pdf`，
> 工人回一份 `result["pages"]`（一頁一筆），本機**自己再拆一次頁**拿到要存檔的 PNG，
> 兩邊依頁碼配對之後逐頁落庫；跳頁、`pages_done` 續跑、0 頁成功＝整筆失敗，
> 三條規則與本機路**逐字相同**。

**為什麼要做這個：**

一份多頁 PDF 是這個系統最花時間的東西：本機看一頁要 64〜88 秒，10 頁就是十幾分鐘。
它正是「卸到雲端」最有價值的那一種檔案（雲端看一張約 2 秒）。

而 PDF 的雲端路有一個單圖沒有的問題：**照片的正本要存的是「每一頁的 PNG」，
但工人只會把「看圖結果」寫回來（`result.json` 不含任何影像）。**
那本機要從哪裡拿到那幾張 PNG？

兩個選項：

| 方案 | 代價 | 結論 |
|---|---|---|
| 工人把每頁 PNG 也放進 S3 | 一份 30 頁的掃描件就是 30 個物件；上傳、下載、清理都變 30 倍 | ❌ |
| **本機自己再拆一次頁** | 多花幾百毫秒 CPU（pypdfium2 是純本機運算，不是 AI） | ✅ 總覽 §10.2 F |

所以本機在拿到結果之後會再跑一次 `pdf_service.render_pages()`，
用**頁碼**跟工人回來的 `pages` 配對。

**做完之後，階段甲（Phase 74〜81）就全部完成了**——下一件事是 **★G1**：
產品負責人親眼看過驗收證據、明確說「可以開始花 AWS 資源了」，才可以進 Phase 82。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **拆頁（render pages）** | 把 PDF 的每一頁畫成一張圖片（PNG）。本專案用 `pypdfium2`，全系統只有 `app/services/pdf_service.py` 碰它 |
| **`pages_done`** | JobStore 上的欄位：「這份 PDF 已經處理幾頁了」，**含跳過的失敗頁**。崩潰重送靠它從下一頁接著跑 |
| **跳頁（skipped page）** | 某一頁看不懂／存不了，就跳過它、繼續下一頁。整份 0 頁成功才算整筆失敗（design5 D12） |
| **依頁碼配對** | 工人回來的 `pages` 是一個清單，每一筆有 `page`（頁碼，1 起算）。本機用 `page` 這個欄位去對，**不要用陣列的位置**——順序不保證 |
| **★G1** | 三個閘門的第一個：「甲做完了，可以開始花 AWS 資源」。**它是人的動作**，實作者不可以自己勾掉（總覽 §4） |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D7 雲端管線只給非敏感** | 只有 `NON_SENSITIVE` ＋ 遠端可用才走雲端 | PDF 走同一個岔路口（`test_PDF判定敏感時零submit走本機`） |
| **§2.2 S3 鍵名** | `documents/{job_id}/input.pdf` | `test_submit的input鍵名是input點pdf` |
| **D17 冪等** | 同一 `job_id` 不得 INSERT 兩張 | `pages_done`／`photo_ids` 續跑（`test_崩潰重送從pages_done續跑不重插`） |
| **§8 錯誤表第 7 列** | 看圖三次失敗 → 不留 photo 列、清 staging；雲端路還要清 S3 | `test_全部頁都失敗_job標failed`（每一頁都試過 3 次的是工人） |
| **design5 D11／D12（未推翻）** | 一檔一任務；重試單位是「一頁」；至少一頁成功就算整筆成功 | `_PDF用結果落庫()` 的迴圈與收尾 |
| **總覽 §10.2 F** | PDF 的每頁 PNG 由**本機**再 `render_pages()` 一次 | `_PDF用結果落庫()` 的第 ② 步 |
| **總覽 §2.4.3** | `result.json` 的 PDF 形狀（`kind: "pdf"` ＋ `pages`） | 假工人照這個形狀寫；`_PDF用結果落庫()` 照這個形狀讀 |
| **總覽 §10.2 R** | 落庫順序固定為 INSERT → **立刻** `store.update(job_id, photo_ids=[photo_id])` → `cleanup()` → `finish_image_job`（`cleanup` 是 S3 網路呼叫，期間被殺不可以變成重送時雙 INSERT） | 單圖分支逐字同 Phase 80；PDF 分支每頁的 `store.update(pages_done=, photo_ids=)` 在整份 `cleanup()` **之前**（`_PDF用結果落庫()` ③ 的迴圈 → ④ 收尾） |

---

## 2. 前置條件

**要先做完的 phase：74、76、77、78、79、80。**

**★G1 還沒到**：全程零 AWS。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db 與 redis 要 Up (healthy)
pytest -q
```

預期：`609 passed`、0 skipped（總覽 §9）。以實查數字為準，本文稱它「**開工基線**」。

確認本機路的 PDF 規則還在（本 phase 要逐條複製它的行為）：

```bash
python -c "
from app.services import ingest_job, pdf_service
print(ingest_job.ERROR_PDF_UNREADABLE)
print(ingest_job.ERROR_PDF_ALL_PAGES_FAILED)
print(ingest_job.PDF_PAGE_CONTENT_TYPE)
print('拆頁函式：', pdf_service.render_pages)
"
```

預期：印出兩句中文錯誤訊息、`image/png`、一個函式。

> ⚠️ **絕對不要同時跑兩份 pytest。**

---

## 3. 範圍

### 做

1. **`tests/fakes.py`**：`fake_worker_process_one()` 支援 PDF
   （用 `pdf_service.render_pages` 算頁數、每頁一筆結果），新增私有小工具 `_假工人看PDF()`。
2. **`app/services/gated_ingest.py`**：
   - `_用雲端結果落庫()` 改成**分流器**（依 `job["content_type"]`）
   - 原本的本體改名為 `_單圖用結果落庫()`（內容逐字同 Phase 80 定稿版，含總覽 §10.2 R 的
     「INSERT → 立刻寫 `photo_ids` → `cleanup()` → `finish_image_job`」順序）
   - 新增 `_PDF用結果落庫()`（含「工人回的頁數與本機拆出的頁數對不上」的防禦 log）與 `_落一頁()`
   - import 補 `pdf_service`
3. **新建 `tests/integration/test_gated_ingest_pdf.py`**（7 顆）。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 讓工人把每頁 PNG 也放進 S3 | 物件數會隨頁數暴增（30 頁＝30 個物件要上傳、下載、清理）。本機拆頁是純 CPU、幾百毫秒（總覽 §10.2 F） |
| 一頁一個 job（或一頁一則 SQS 訊息） | design5 D11「一檔一任務」**沒有被推翻**。拆開的話進度面板畫不出「一檔一列」，而 design6 §3 明文「前端不新增」 |
| 用陣列位置（index）去配對工人回來的 `pages` | 順序不保證（工人未來若改成並行看圖就會亂）。一律用 `page` 這個欄位對 |
| 為 PDF 另外定義錯誤訊息 | 沿用既有的 `ERROR_PDF_UNREADABLE`／`ERROR_PDF_ALL_PAGES_FAILED`——使用者看到的字要與本機路**完全一樣**（他根本不知道有雲端這回事） |
| 讓「某一頁失敗」變成整筆失敗 | design5 D12：至少一頁成功就算整筆成功。改掉會讓「30 頁裡有一頁是空白頁」的檔整份消失 |
| 在本機重看那些工人看不懂的頁 | 與單圖同一個理由（總覽 §10 追認項 g）：遠端活著、只是看不懂，本機再看也一樣，而且會把 3 次變成 6 次 |
| 動 `app/services/ingest_job.py` | 它仍然是 fallback 的目的地，本 phase 一個字都不改（`git diff` 要是空的） |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並**真的跑它、親眼看到紅**。

### - [ ] 步驟 1：先讓假工人看得懂 PDF——`tests/fakes.py`

> 📌 這一步嚴格說是「測試工具」不是「測試」，所以放在寫測試之前：
> 步驟 2 的測試檔要用到它。

- [ ] 檔頭 import 區加**一行** `from app.services import pdf_service`，放在 `from app.core import config`
  之後、`from app.services.ask_workflow import RouteDecision` 之前（ruff 的 isort 依模組路徑排序，
  `app.services` 排在 `app.services.ask_workflow` 前面）。改完那幾行長這樣（以 Phase 79 結束時的內容為準）：

```python
from app.core import config
from app.services import pdf_service
from app.services.ask_workflow import RouteDecision
from app.services.cloud_ingest import MailboxMessage
from app.services.privacy_gate import Verdict
from app.services.staging_service import STAGING_EXTENSIONS
from app.services.vlm_service import PhotoUnderstanding
```

> 📌 `tests/fakes.py` 的 import 是「一行一個模組」的寫法——**沒有**括號式的
> `from app.services import (…)` 區塊（那是 `app/dependencies.py` 的長相），不要去找。
> 放對位置的話 `ruff check` 不會報 `I001`。細節見本文件 §7 陷阱 9。

- [ ] 把 Phase 79 寫的 `fake_worker_process_one()` **整段換成**下面這兩支
  （原本的單圖邏輯一字未改，只是多了一個 PDF 岔路）：

```python
def fake_worker_process_one(mailbox, understanding=None, *, worker_version="fake-worker"):
    """假工人：把 mailbox.jobs 裡的**第一則**訊息做成 result.json ＋ 一則 results 訊息。

    它**不是** app/workers/cloud_worker.py（那是 Phase 87 的事），只是「另一頭真的
    有人在做事」的最小替身：不看圖、不解析影像，照著測試指定的答案寫結果。

    單圖（.jpg／.png）：
      understanding 給一個 PhotoUnderstanding ＝ 工人一次就看懂了
      understanding 給 None                    ＝ 工人試了三次都看不懂

    PDF（.pdf，Phase 81 加）：見 _假工人看PDF()。

    ★ 順序刻意寫成「**先 PutObject、才 SendMessage**」（design6 D9 的順序鐵律）：
      假件也要教對的做法，Phase 87 的真工人才有樣本可比。

    回傳寫出去的那份 result（測試想再檢查內容時用得到）；jobs 佇列空的時候回 None。
    """
    message = mailbox.receive_job(wait_seconds=0)
    if message is None:
        return None

    if (message.s3_key or "").endswith(".pdf"):
        result = _假工人看PDF(mailbox, message, understanding, worker_version)
    else:
        result = {
            "job_id": message.job_id,
            "worker_version": worker_version,
            "kind": "image",
            "understood": understanding is not None,
            "attempts": 1 if understanding is not None else config.VLM_MAX_ATTEMPTS,
            "understanding": understanding.model_dump() if understanding is not None else None,
        }

    mailbox.put_object(
        mailbox.result_key(message.job_id),
        json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json",
    )
    mailbox.send_result(message.job_id)
    mailbox.delete_job_message(message.receipt_handle)
    return result


def _假工人看PDF(mailbox, message, understanding, worker_version: str) -> dict:
    """PDF 的假結果：先拆頁（只為了知道有幾頁），再一頁一頁照劇本回答。

    understanding 可以給三種東西：
      * 一個 PhotoUnderstanding ＝ 每一頁都看懂了，而且內容都一樣
      * 一個 list               ＝ 逐頁指定（None ＝ 那一頁看不懂）；比頁數短就補 None
      * None                    ＝ 每一頁都看不懂

    拆不開（壞檔）→ `pages` 是**空清單**——與真工人的規則相同（總覽 §2.6 第 5 條），
    本機看到空清單就標 ERROR_PDF_UNREADABLE。

    ⚠ 這裡用的是**產品碼的** pdf_service.render_pages()：假件只負責「演出工人的行為」，
      不自己發明一套拆頁邏輯（不然頁數對不上就會變成假綠）。
    """
    raw = mailbox.get_object(message.s3_key) or b""
    try:
        頁數 = len(pdf_service.render_pages(raw))
    except pdf_service.PdfUnreadableError:
        頁數 = 0

    if isinstance(understanding, list):
        逐頁 = list(understanding) + [None] * max(0, 頁數 - len(understanding))
    else:
        逐頁 = [understanding] * 頁數

    pages = []
    for 頁碼, 這頁 in enumerate(逐頁[:頁數], start=1):
        pages.append(
            {
                "page": 頁碼,
                "understood": 這頁 is not None,
                "attempts": 1 if 這頁 is not None else config.VLM_MAX_ATTEMPTS,
                "understanding": 這頁.model_dump() if 這頁 is not None else None,
            }
        )

    return {
        "job_id": message.job_id,
        "worker_version": worker_version,
        "kind": "pdf",
        "pages": pages,
    }
```

### - [ ] 步驟 2：先寫測試（紅）——新建 `tests/integration/test_gated_ingest_pdf.py`

整份貼上：

```python
"""PDF 走雲端路的整合測試（design6 D7／D17、design5 D11／D12；Phase 81）。

與 test_gated_ingest.py 同一套玩法：**不打 HTTP**，直接呼叫 run_gated_ingest_job()。
PDF 的位元組用 Phase 28 就有的 tests/fakes.make_pdf_bytes(pages=N) 現產。

⚠ 這裡的「第幾頁」一律 **1 起算**（與既有 skipped_pages 的頁碼慣例相同）。
   程式裡的 pages_done 是「已處理幾頁」，所以做完第 2 頁時 pages_done == 2。

本檔的三個小工具（有工人的信箱／雲端路／記得最後一筆的Store）與
test_gated_ingest.py 的同名工具長得幾乎一樣，但**各留一份**：
跨測試檔 import 假件會把兩份測試綁在一起，那邊改一下這邊就跟著紅
（本專案既有的 分頁VLM 也是這樣各留一份）。
"""

from __future__ import annotations

from datetime import datetime

from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, ingest_job, staging_service
from app.services.ingest_job_store import InMemoryJobStore
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    fake_worker_process_one,
    make_pdf_bytes,
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
    """成功時 job 會被刪掉，但測試還想看「刪掉之前 pages_done／photo_ids 是什麼」。"""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


class 有工人的信箱(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了。

    understanding 直接往下傳給假工人，所以可以給「逐頁的清單」
    （例如 [收據理解, None] ＝ 第 1 頁看得懂、第 2 頁看不懂）。
    """

    def __init__(self, understanding=None, *, 工人上工: bool = True) -> None:
        super().__init__()
        self.understanding = understanding
        self.工人上工 = 工人上工
        self.工人做過幾次 = 0

    def receive_result(self, wait_seconds: int):
        if self.工人上工 and self.jobs:
            fake_worker_process_one(self, self.understanding)
            self.工人做過幾次 += 1
        return super().receive_result(wait_seconds)


def 建一個PDFjob(
    store: InMemoryJobStore,
    *,
    job_id: str = "pdf-1",
    pages: int = 2,
    data: bytes | None = None,
) -> str:
    """模擬 HTTP 端點會做的兩件事：落 staging ＋ 建 job。"""
    staging_service.save_staging(
        job_id,
        "application/pdf",
        data if data is not None else make_pdf_bytes(pages=pages),
    )
    store.create(
        job_id=job_id,
        filename="scan.pdf",
        content_type="application/pdf",
        ai_backend="local",
        source="upload",
    )
    return job_id


def 收件箱id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def 雲端路(信箱, *, 開著: bool = True, 逾時秒: int = 5):
    return cloud_ingest.CloudRoute(信箱, FakeProbe(開著), timeout_seconds=逾時秒)


def 跑(job_id: str, *, store, gate, cloud, vlm=None, embeddings=None) -> None:
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=vlm if vlm is not None else FakeVLM(收據理解),
        embeddings=embeddings if embeddings is not None else FakeEmbeddings(),
        now=NOW,
        gate=gate,
        cloud=cloud,
    )


def test_兩頁都成功_入庫兩列_job被刪_S3清空():
    """PDF 的雲端路走順的樣子：一份兩頁的 PDF ＝ 兩列照片，全部進收件箱。"""
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    信箱 = 有工人的信箱(收據理解)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert photo_repository.count_photos() == 2
    assert len(photo_repository.list_photos_in_folder(收件箱id())) == 2
    最後 = store.deleted[job_id]
    assert 最後["page_count"] == 2
    assert 最後["pages_done"] == 2
    assert len(最後["photo_ids"]) == 2
    assert 最後["route"] == "cloud"
    assert store.get(job_id) is None, "成功＝job 被刪掉"
    assert 信箱.objects == {}, "S3 要清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_第二頁看不懂_只入庫一列_跳過一頁():
    """design5 D12（未推翻）：某一頁不成立就跳過它，其他頁照樣入庫、整筆仍算成功。

    「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    信箱 = 有工人的信箱([收據理解, None])  # 逐頁指定：第 2 頁看不懂

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert photo_repository.count_photos() == 1
    最後 = store.deleted[job_id]
    assert 最後["pages_done"] == 2, "跳過的頁也要算進 pages_done"
    assert len(最後["photo_ids"]) == 1
    assert store.get(job_id) is None, "至少一頁成功就算整筆成功"
    assert 信箱.objects == {}


def test_pages是空清單_job標failed且錯誤是PDF讀不開():
    """工人回報「這份 PDF 拆不開」（pages 是空清單，總覽 §2.4.3）。

    使用者看到的訊息要與本機路**一字不差**——他不知道有雲端這回事。
    """
    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, data=b"this-is-not-a-pdf")
    信箱 = 有工人的信箱(收據理解)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_UNREADABLE
    assert 信箱.objects == {}, "失敗也要把 S3 清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_全部頁都失敗_job標failed():
    """每一頁工人都看不懂（每頁各試了 3 次）＝ 0 頁成功 ＝ 整筆失敗（design5 D12）。"""
    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, pages=2)
    信箱 = 有工人的信箱(None)  # 每一頁都看不懂

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_ALL_PAGES_FAILED
    assert job["pages_done"] == 2, "兩頁都處理過了（只是都跳過）"
    assert 信箱.objects == {}


def test_崩潰重送從pages_done續跑不重插():
    """design6 D17 ＋ design5 §4.4：從 pages_done 的**下一頁**接著跑。

    重現方式：手動做出「上一趟已經做完第 1 頁、而且已經送去雲端」的狀態
    （pages_done=1、photo_ids 帶著那一頁的 id、route=cloud），
    再把工人算好的結果放進 S3，然後重跑一次。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=3)

    # 第 1 頁在上一趟已經入庫了。直接用 repository 插一列就好——本顆要的是那個**狀態**
    第一頁 = photo_repository.insert_photo(
        text=收據理解.text,
        category="未分類",
        location=收據理解.location,
        items=收據理解.items,
        content_time=None,
        embedding=FakeEmbeddings().embed_query(收據理解.text),
        uploaded_at=NOW(),
    )
    store.update(job_id, page_count=3, pages_done=1, photo_ids=[第一頁["id"]], route="cloud")
    assert photo_repository.count_photos() == 1

    # 工人上一趟算好的結果還在 S3（三頁都看懂了）。這裡直接借假工人把 result.json 寫好：
    # 放一份真的 input.pdf ＋ 發一則 jobs 訊息 → 假工人做一次 → 再把 results 訊息清掉
    # （這一趟不是靠 results 訊息叫醒的，是崩潰重送 → 靠 fetch_result 直接去 S3 拿）。
    # ⚠ input.pdf 一定要是**真的 PDF**：假工人用產品碼的 render_pages() 去數頁數，
    #   放 b"x" 的話它會判成「拆不開」，這一顆就會紅在完全無關的地方。
    信箱 = FakeMailbox()
    input鍵 = 信箱.input_key(job_id, "application/pdf")
    信箱.put_object(input鍵, make_pdf_bytes(pages=3), "application/pdf")
    信箱.send_job(job_id, input鍵)
    fake_worker_process_one(信箱, [收據理解, 收據理解, 收據理解])
    信箱.results.clear()

    閘門 = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換答案也不該被問到
    跑(job_id, store=store, gate=閘門, cloud=雲端路(信箱))

    assert 閘門.calls == 0, "route 已經有值，不可以再問一次閘門"
    assert photo_repository.count_photos() == 3, "第 1 頁不可以被插第二次"
    最後 = store.deleted[job_id]
    assert 最後["pages_done"] == 3
    assert 最後["photo_ids"][0] == 第一頁["id"], "原本那一頁的 id 要留著"
    assert len(最後["photo_ids"]) == 3


def test_PDF判定敏感時零submit走本機():
    """design6 D3／§9 必釘第 1 條：PDF 走的是同一個岔路口，沒有例外。

    ⚠ 規則版只看檔名，而 PDF 的檔名常常是「掃描件.pdf」這種看不出內容的東西——
      那會判 UNCERTAIN（也是走本機）。這一顆用一個明確敏感的檔名，
      驗的是「敏感的 PDF 一個位元組都不會出門」。
    """
    store = 記得最後一筆的Store()
    job_id = 建一個PDFjob(store, pages=2)
    信箱 = FakeMailbox()

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=雲端路(信箱))

    assert 信箱.put_calls == 0, "敏感檔的 PutObject 次數必須是 0"
    assert 信箱.send_job_calls == 0
    assert photo_repository.count_photos() == 2, "照樣走本機入庫（兩頁）"
    assert store.deleted[job_id]["privacy"] == "SENSITIVE"
    assert store.deleted[job_id]["route"] == "local"


def test_submit的input鍵名是input點pdf():
    """design6 §2.2：`documents/{job_id}/input.pdf`。

    工人是靠副檔名推 content_type 的（總覽 §2.6 第 4 條），推錯就會拿去當圖片看。
    ★ 用 `信箱.calls`（呼叫流水帳）驗：`objects` 在成功之後會被 cleanup 清空，
      流水帳則會留著整趟的歷史。
    """
    store = InMemoryJobStore()
    job_id = 建一個PDFjob(store, pages=1)
    信箱 = 有工人的信箱(收據理解)

    跑(job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=雲端路(信箱))

    assert f"put_object documents/{job_id}/input.pdf" in 信箱.calls
    assert f"put_object documents/{job_id}/context.json" in 信箱.calls
    assert photo_repository.count_photos() == 1
```

### - [ ] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_gated_ingest_pdf.py -q
```

預期：**多顆紅**。最典型的錯誤是「PDF 走了單圖的落庫段」：

```text
AssertionError: assert 0 == 2
 +  where 0 = count_photos()
```

（Phase 80 的 `_用雲端結果落庫` 只認 `result["understanding"]`，
PDF 的結果沒有那個鍵 → 被判成「看不懂」→ job 標 failed、零列照片。）

### - [ ] 步驟 4：綠——`app/services/gated_ingest.py` 補上 PDF 分支

**整檔覆蓋**（下面就是本 phase 結束時這個檔案的完整內容。與 Phase 80 的差別有四處：
模組 docstring、import 補 `pdf_service`、`_用雲端結果落庫()` 變成**分流器**
（原本的本體改名為 `_單圖用結果落庫()`，內容逐字同 Phase 80 定稿版）、新增 `_PDF用結果落庫()` 與 `_落一頁()`）：

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

【本 phase（81）做到哪裡】
雲端路**全部做完**了：單圖與 PDF、順利的一圈與四種不順利
（不是 running／沒憑證（Phase 78）、送出失敗（79）、逾時（79／80）、
崩潰重送但沒有結果（80））。接下來是 ★G1——產品負責人點頭之後才開始碰 AWS。

PDF 的雲端路有一件事與單圖不同（總覽 §10.2 F）：**本機自己再拆一次頁**。
工人拆頁是為了看圖，本機拆頁是為了拿到「要存檔的那幾張 PNG」——
把工人拆好的每頁 PNG 放 S3 會讓物件數隨頁數暴增，而拆頁是純 CPU、幾百毫秒的事。

分層：本模組不寫 SQL、不碰 HTTP、不自己看圖——它只是「決定呼叫誰」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from langchain_core.embeddings import Embeddings

from app.core import config
from app.services import cloud_ingest, ingest_job, pdf_service, staging_service, vlm_service
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
    # ★ 要在問閘門**之前**：模型備援版（Phase 75）會花上幾秒鐘。
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
        # load_bytes 是**惰性**的：規則版（Phase 74）根本不會呼叫它（只看檔名），
        # 只有模型備援版（Phase 75）在規則說不確定時才會真的去讀檔。
        # 寫成 lambda 而不是先讀好，就是為了「規則命中時連磁碟都不必碰」。
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
    """
    job_id = job["job_id"]
    try:
        result = cloud.fetch_result(job_id)
    except Exception:
        logger.warning("job %s：崩潰重送時讀不到雲端結果", job_id, exc_info=True)
        result = None

    if result is not None:
        logger.info("job %s 崩潰重送：S3 上已經有結果了，直接落庫", job_id)
        _用雲端結果落庫(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
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
    """依檔案型別分流：單圖一張、PDF 一頁一張（沿用 design5 D11「一檔一任務」）。

    分流的依據是 job 的 content_type，**不是** result.json 的 kind：
    job 是我們自己寫的（HTTP 收檔時就決定了），kind 是工人寫的。
    兩邊不一致時（例如工人是舊版映像）以本機的為準——落庫是本機的責任。
    """
    if job["content_type"] == config.PDF_CONTENT_TYPE:
        _PDF用結果落庫(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
        return
    _單圖用結果落庫(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)


def _單圖用結果落庫(
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


def _PDF用結果落庫(
    job: IngestJob,
    result: dict,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    cloud,
) -> None:
    """PDF 的雲端路落庫：工人逐頁看好的結果 ＋ **本機自己拆的那幾張 PNG**。

    ★ 為什麼本機要再拆一次頁（總覽 §10.2 F）：
      工人拆頁是為了看圖；本機拆頁是為了拿到「要存進 data/photos 的那幾張 PNG」。
      把工人拆好的每頁 PNG 放 S3 會讓物件數隨頁數暴增（一份 30 頁的掃描件就 30 個物件），
      而 pypdfium2 拆頁是純 CPU、幾百毫秒的事。

    ★ 三條規則與本機路（ingest_job._run_pdf_job）**逐字相同**：
      ① 每一頁各自成敗：某一頁看不懂就跳過那一頁，其他頁照樣入庫
      ② 0 頁成功才整筆失敗（ERROR_PDF_ALL_PAGES_FAILED）
      ③ 崩潰重送從 pages_done 的**下一頁**接著跑，已成功的頁不重插
         （pages_done ＝「已處理幾頁」，**含跳過的頁**；每一頁的收據在整份 cleanup() 之前
         就已經寫進 JobStore——總覽 §10.2 R）
    """
    job_id = job["job_id"]
    content_type = job["content_type"]

    # ① 工人說這份 PDF 拆不開（pages 是空清單）＝ 這次上傳什麼都存不了
    pages = result.get("pages")
    if not isinstance(pages, list) or not pages:
        logger.warning("job %s：雲端回報 PDF 拆不開", job_id)
        _盡力清雲端(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_UNREADABLE, store=store, content_type=content_type
        )
        return

    # ② 本機自己拆一次頁，拿到要存檔的 PNG 位元組
    try:
        page_images = pdf_service.render_pages(staging_service.read_staging(job_id, content_type))
    except pdf_service.PdfUnreadableError:
        # 工人拆得開、本機拆不開：多半是 staging 檔在半路壞了（很罕見）
        logger.warning("job %s：本機拆頁失敗", job_id, exc_info=True)
        _盡力清雲端(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_UNREADABLE, store=store, content_type=content_type
        )
        return

    store.update(job_id, page_count=len(page_images))
    清單 = ingest_job.load_prompt_context()

    # ③ 依頁碼配對（工人回的順序不保證，用 page 這個欄位對，不要用陣列索引）
    每頁結果 = {頁.get("page"): 頁 for 頁 in pages if isinstance(頁, dict)}
    if len(每頁結果) != len(page_images):
        # 兩邊拆的是同一份檔、用的是同一支 pdf_service，正常情況頁數一定相同。
        # 對不上＝工人是別的版本、或檔在半路壞了。對不上的頁由下面的 .get() 當「沒有結果」跳過，
        # 這裡先大聲記一行——不然「少了幾頁」會安靜地變成幾個跳頁，事後很難查。
        logger.warning(
            "job %s：工人回了 %d 頁的結果，本機拆出 %d 頁，對不上的頁會被跳過",
            job_id,
            len(每頁結果),
            len(page_images),
        )

    photo_ids: list[int] = list(job.get("photo_ids") or [])
    已處理 = job.get("pages_done") or 0
    if 已處理:
        logger.info(
            "job %s：崩潰重送，已處理 %d／%d 頁，從第 %d 頁接著跑",
            job_id,
            已處理,
            len(page_images),
            已處理 + 1,
        )

    for page_number, page_bytes in enumerate(page_images[已處理:], start=已處理 + 1):
        photo_id = _落一頁(
            job_id,
            page_number,
            page_bytes,
            每頁結果.get(page_number),
            store=store,
            embeddings=embeddings,
            now=now,
            清單=清單,
        )
        if photo_id is not None:
            photo_ids.append(photo_id)
        # 成功或跳過都要記 pages_done，而且要與 photo_ids **同一次**寫進去：
        # 分兩次寫的話，剛好被殺在中間的重送會把同一頁再做一次（沿用本機路的作法）。
        # ★ 這一行也是 PDF 版的「先寫收據」（總覽 §10.2 R）：每一頁的收據在**這裡**、
        #   在整份的 cleanup()（下面 ④）之前就已經落到 JobStore——cleanup 期間被殺，
        #   重送會從 pages_done 的下一頁接著跑，已入庫的頁不會再插一次。
        store.update(job_id, pages_done=page_number, photo_ids=list(photo_ids))

    # ④ 收尾：至少一頁成功就算整筆成功（design5 D12）。
    #    走到這裡時每一頁的 pages_done／photo_ids 都已經在 JobStore 裡了（③ 的迴圈每頁寫一次），
    #    所以下面的 cleanup（S3 網路呼叫）與刪 job 之間被殺也不會雙 INSERT（總覽 §10.2 R）。
    if not photo_ids:
        _盡力清雲端(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_ALL_PAGES_FAILED, store=store, content_type=content_type
        )
        return

    _盡力清雲端(cloud, job_id)
    staging_service.remove_staging(job_id, content_type)
    store.delete(job_id)
    # ★ 契約字樣（與單圖那一行同一個前綴）：Phase 88／92 的 Demo 靠 grep「雲端結果已入庫」對帳。
    #   跳過幾頁算得出來：len(page_images) − len(photo_ids)，不必再印一個欄位。
    logger.info(
        "job %s 雲端結果已入庫：%d 頁中 %d 頁成功（photo_ids=%s）",
        job_id,
        len(page_images),
        len(photo_ids),
        photo_ids,
    )


def _落一頁(
    job_id: str,
    page_number: int,
    page_bytes: bytes,
    這頁: dict | None,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    清單: ingest_job.PromptContext,
) -> int | None:
    """把 PDF 的一頁變成資料庫裡的一列；這一頁不成立就回 None（＝跳過它）。

    三種「跳過」：工人沒回這一頁、工人說看不懂、本機轉向量或寫檔失敗。
    三種都只影響**這一頁**——其他頁照樣入庫（design5 D12 的 skipped_pages 語意）。
    """
    understanding = _理解(這頁.get("understanding")) if 這頁 and 這頁.get("understood") else None
    if understanding is None:
        logger.warning("job %s：第 %d 頁雲端看不懂或沒有結果，跳過這一頁", job_id, page_number)
        return None

    embedding = _轉向量(job_id, understanding, store=store, embeddings=embeddings, 清單=清單)
    if embedding is None:
        logger.warning("job %s：第 %d 頁本機轉向量失敗，跳過這一頁", job_id, page_number)
        return None

    try:
        return ingest_job.insert_photo_with_files(
            page_bytes,
            ingest_job.PDF_PAGE_CONTENT_TYPE,
            understanding,
            embedding,
            inbox_name=清單.inbox_name,
            folders=清單.folders,
            entities=清單.entities,
            uploaded_at=now(),
        )
    except Exception:
        # 半成品已由 insert_photo_with_files 自己清乾淨（檔案＋資料列）
        logger.exception(
            "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁", job_id, page_number
        )
        return None


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

### - [ ] 步驟 5：跑測試，看它轉綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_gated_ingest_pdf.py -v
```

預期最後一行：`7 passed`。

```bash
pytest tests/integration/test_ingest_job_pdf.py -q
```

預期：`9 passed`——**本機路的 PDF 一顆都不准紅**（本 phase 沒有改 `ingest_job.py`）。

```bash
pytest -q
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：**開工基線 ＋ 7**（＝ 616）、0 skipped；格式與 lint 全過。

### - [ ] 步驟 6：commit

> ⚠ 依總覽 §7 鐵律 12：commit 節奏由產品負責人決定。

```bash
cd /Users/linjunting/personalDocAI
git add app/services/gated_ingest.py tests/fakes.py tests/integration/test_gated_ingest_pdf.py
git commit -m "feat: Phase 81 雲端路 PDF——_用雲端結果落庫 依 content_type 分流（單圖／PDF）、新增 _PDF用結果落庫 與 _落一頁（本機自己 render_pages 拿每頁 PNG、依 page 欄位與工人結果配對、跳頁與 pages_done 續跑與 0 頁失敗三條規則沿用本機路）、假工人支援 PDF，+7 tests；階段甲全部完成，下一步是 ★G1"
```

---

## 5. ASCII 圖

### 圖一：PDF 的雲端路——兩邊各拆一次頁，靠**頁碼**配對

```text
   本機                                            工人（EC2／假工人）
  ────────────────────────────────              ─────────────────────────
   submit：input.pdf ＋ context.json  ──S3──►    GetObject input.pdf
   send_job {job_id, s3_key}          ──SQS──►   render_pages() ← 為了**看圖**
                                                        │
                                                 一頁一頁送 Ollama Cloud
                                                        │
                                                 result.json:
                                                 { "kind": "pdf",
                                                   "pages": [
                                                     {"page": 1, "understood": true,  …},
                                                     {"page": 2, "understood": false, …} ] }
   wait_result ◄──SQS── send_result ◄──S3──  PutObject result.json
        │
        ▼
   render_pages() ← 為了**存檔**（總覽 §10.2 F：PNG 不進 S3，本機自己拆更便宜）
        │   （頁數與 pages 對不上 → 先 log warning；對不上的頁當「沒有結果」跳過）
        ├── 第 1 頁：pages[page==1].understood ＝ true
        │            → 本機算向量 → INSERT ＋ 存 PNG ＋ 縮圖 → photo_ids += [id]
        │            → store.update(pages_done=1, photo_ids=[…])
        │
        ├── 第 2 頁：pages[page==2].understood ＝ false
        │            → **跳過這一頁**（其他頁照樣入庫，design5 D12）
        │            → store.update(pages_done=2, photo_ids=[…])   ← 跳過的頁也算
        │
        ▼
   （每頁的 pages_done／photo_ids 都已在迴圈裡寫好 → 下面清 S3 時被殺也不會重插，§10.2 R）
   photo_ids 不是空的 → 清 S3 → 刪 staging → 刪 job（＝成功）
   photo_ids 是空的   → 清 S3 → fail_job(ERROR_PDF_ALL_PAGES_FAILED)

   ★ 配對用的是 **page 這個欄位**，不是陣列位置——工人回來的順序不保證。
```

### 圖二：崩潰重送怎麼從第 3 頁接著跑

```text
   job（JobStore 上的狀態）            資料庫              S3
   ──────────────────────            ────────          ─────────
   route="cloud"                     照片 #71（第 1 頁）  result.json 還在
   page_count=5                      照片 #72（第 2 頁）  input.pdf 還在
   pages_done=2
   photo_ids=[71, 72]
        │
        │   ✂ 機器在這裡被重開
        ▼
   佇列把同一個 job_id 再送一次
        │
        ▼
   run_gated_ingest_job → route == "cloud" → _繼續雲端路
        │
        ▼
   fetch_result（直接去 S3 拿，**不重送**）→ 有！
        │
        ▼
   _PDF用結果落庫
        ├ 本機 render_pages() → 5 張 PNG
        ├ 已處理 = pages_done = 2
        └ for 迴圈從 page_images[2:] 開始，頁碼從 3 起算
             → 第 1、2 頁**不重看、不重插**（它們的 id 還在 photo_ids 裡）
```

---

## 6. 驗收清單

- [ ] **開工基線已實查**：`pytest -q` 記下顆數（預期 609）

- [ ] **三支新函式都在，而且原本的單圖本體只是改名**

  ```bash
  grep -nE "^def _用雲端結果落庫|^def _單圖用結果落庫|^def _PDF用結果落庫|^def _落一頁" \
    app/services/gated_ingest.py
  ```

  預期：4 行命中

- [ ] **PDF 的三條規則都用既有常數，沒有自己發明新訊息**

  ```bash
  grep -nE "ingest_job\.(ERROR_PDF_UNREADABLE|ERROR_PDF_ALL_PAGES_FAILED|PDF_PAGE_CONTENT_TYPE)" \
    app/services/gated_ingest.py
  grep -nE "^(ERROR_PDF_UNREADABLE|ERROR_PDF_ALL_PAGES_FAILED|PDF_PAGE_CONTENT_TYPE) *=" \
    app/services/gated_ingest.py || echo "OK：本檔沒有重新定義這三個常數"
  ```

  預期：第一句 **4 行命中**（`ERROR_PDF_UNREADABLE` 兩處、`ERROR_PDF_ALL_PAGES_FAILED` 一處、
  `PDF_PAGE_CONTENT_TYPE` 一處；`_PDF用結果落庫()` 的 docstring 也提到常數名，但它前面沒有
  `ingest_job.`，所以不會被這一句算進去）；第二句印 `OK：本檔沒有重新定義這三個常數`

- [ ] **單圖分支「先寫收據」那一行還在，而且在清 S3 之前（總覽 §10.2 R）**

  ```bash
  grep -nA5 "store.update(job_id, photo_ids=\[photo_id\])" app/services/gated_ingest.py
  ```

  預期：命中恰 1 處，而且緊接的那 5 行裡依序出現 `_盡力清雲端(cloud, job_id)` 與
  `ingest_job.finish_image_job(...)`——先寫收據、再清 S3、最後收尾

- [ ] **`ingest_job.py` 一個字都沒改**

  ```bash
  git diff --stat app/services/ingest_job.py
  ```

  預期：沒有輸出

- [ ] **本機路的 PDF 沒有被影響**

  ```bash
  pytest tests/integration/test_ingest_job_pdf.py -q
  ```

  預期：`9 passed`

- [ ] **新測試 7 顆全綠**

  ```bash
  pytest tests/integration/test_gated_ingest_pdf.py -v
  ```

  預期：`7 passed`

- [ ] **PDF 成功時也留下「完成」那一行 log**（與單圖同一個前綴，Phase 88／92 靠 grep 它）

  ```bash
  pytest tests/integration/test_gated_ingest_pdf.py -k 兩頁都成功 \
         -o log_cli=true -o log_cli_level=INFO -q 2>&1 | grep 雲端結果已入庫
  ```

  預期：一行含 `雲端結果已入庫：2 頁中 2 頁成功`
  （之後在真機上是 `docker compose logs worker | grep 雲端結果已入庫`）

- [ ] **全量 pytest 顆數 ＝ 開工基線 ＋ 7**

  ```bash
  pytest -q
  ```

  預期：`616 passed`、**0 skipped**

- [ ] **端點仍 22、openapi 零 DELETE**

  ```bash
  pytest tests/integration/test_ask_three_paths.py::test_端點數不變 \
         tests/integration/test_nav_header.py::test_端點數仍為22 \
         tests/integration/test_design5_error_paths.py::test_端點恰好是這22支 -q
  ```

  預期：`3 passed`

- [ ] **零依賴實證（顆數必須完全一樣）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

  預期：`616 passed`

- [ ] **`app/` 全樹仍然零 boto3**（★G1 的前提之一：甲全程沒碰過 AWS）

  ```bash
  grep -rn "boto3" app/ requirements.txt || echo "OK：整個專案還沒有 boto3"
  ```

  預期：印 `OK：整個專案還沒有 boto3`

- [ ] **專案的 `data/` 沒被弄髒**

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都沒有輸出

- [ ] **git 收尾**：未指示 commit 時跳過步驟 6，改核對
  `git status --short -- app tests` 的變更項恰為本 phase 的 3 個檔

---

## 7. 常見陷阱

1. **用陣列位置去配對工人回來的 `pages`（`pages[i]` 對 `page_images[i]`）。**
   現在會過（假工人是照順序寫的），但 `page` 這個欄位存在的理由就是「順序不保證」
   ——工人日後若改成並行看圖、或某一頁被跳過沒有寫進 `pages`，位置就全錯開了，
   而且是**安靜地**錯（第 3 頁的文字被存成第 5 頁的照片）。一律用 `page` 對。

2. **忘了本機要自己再 `render_pages()` 一次，改去 S3 找每頁 PNG。**
   S3 上**只有 `input.pdf`**（總覽 §10.2 F：工人拆好的 PNG 不放 S3）。
   找不到就會變成「照片存進去了，但原圖與縮圖是空的」。

3. **把 `pages_done` 只在「成功的頁」加一。**
   規則是「**已處理**幾頁，含跳過的頁」（design5 §4.3 原文）。只算成功頁的話，
   崩潰重送會把**已經跳過的那幾頁再看一次**，而且永遠卡在同一頁。

4. **`pages_done` 與 `photo_ids` 分兩次 `store.update`。**
   剛好被殺在兩次之間的重送，會把同一頁再做一次（插出重複的照片）。
   一定要**同一次**寫進去——這是從本機路 `_run_pdf_job` 原樣搬過來的規矩。

5. **PDF 拆不開時回 `ERROR_PDF_ALL_PAGES_FAILED`（或反過來）。**
   兩句話給使用者的意思完全不同：「這份 PDF 讀不開或沒有內容」＝檔案本身有問題；
   「PDF 每一頁 AI 都看不懂」＝檔是好的但看不懂。用錯會讓人往完全錯的方向查。

6. **假工人用自己寫的方式數頁數（例如「檔案大小除以 X」或寫死 2 頁）。**
   一定要用產品碼的 `pdf_service.render_pages()`：兩邊數出來的頁數不一致時，
   配對會整個錯開，而測試會**假綠**（因為假工人回的 pages 剛好跟本機拆出來的一樣多）。

7. **在 `test_崩潰重送從pages_done續跑不重插` 裡把 `input.pdf` 放成 `b"x"`。**
   假工人會用 `render_pages()` 去數頁數，`b"x"` 拆不開 → `pages` 是空清單 →
   本機標 `ERROR_PDF_UNREADABLE`，這顆測試就會紅在完全無關的地方（而且訊息很難懂）。
   放 `make_pdf_bytes(pages=3)`。

8. **崩潰重送時 `data/staging/` 裡的那份 PDF 已經不在了。**
   雲端路的 PDF 要讀 staging **兩次**：送出時（`submit` 的 `file_bytes`）與結果回來之後
   （本機再 `render_pages()` 一次，拿存檔用的 PNG）。第二次讀不到時 `read_staging()` 會直接丟
   `FileNotFoundError`（`staging_service` 刻意不吞它——「JobStore 說有這個任務、檔卻不見了」
   是真的出事），這一筆會停在 `analyzing`。正常情況下不會發生：24 小時掃把
   （`sweep_stale_staging`）只清「JobStore 查不到 job」的孤兒檔，job 還在就不會動它；
   真的發生＝有人手動清了 `data/staging/`（或整個 `data/` 被 `git clean -xdf` 掃掉）。
   **不要**為此在 `_PDF用結果落庫()` 多接一個 `except FileNotFoundError`——本機路的
   `_run_pdf_job` 也是同樣讓它炸出來，兩邊要一致（本 phase 的原則就是三條規則逐字相同）。

9. **忘了在 `tests/fakes.py` 補 `from app.services import pdf_service`。**
   症狀：`fake_worker_process_one` 拆頁時 `NameError: name 'pdf_service' is not defined`
   （`fake_worker_process_pdf` 用到 `pdf_service.render_pages()`／`pdf_service.PdfUnreadableError`）。
   它是新的**一行**、放在 `from app.core import config` 之後即可（步驟 1 有貼改完的樣子）；
   `fakes.py` 沒有括號式的 `from app.services import (…)` 區塊，不要去找。

10. **把單圖分支的 `store.update(job_id, photo_ids=[photo_id])` 挪到 `cleanup()` 之後
    （或省掉，反正 `finish_image_job` 也會寫）。**
    `cleanup()` 是 S3 網路呼叫（boto3 自己會重試，可拖數十秒）。這段期間 worker 被殺 →
    佇列重送同一個 job_id → `result.json` 已被刪 → fallback 本機 → `run_ingest_job` 看不到
    `photo_ids` → **再 INSERT 一張**（違反 design6 D17）。收據一定要在 INSERT 成功的**下一行**
    就寫（總覽 §10.2 R）。PDF 分支不必另外加：迴圈裡每頁那一次
    `store.update(pages_done=, photo_ids=)` 本來就在整份 `cleanup()` 之前。

---

## 8. 完成後的專案狀態

**階段甲（Phase 74〜81）全部完成。** 雲端路在假信箱上已經整條跑得通：

- 閘門三分類 ＋「不確定＝本機」（74／75／78）
- 四種「遠端不可用」都會 fallback，而且 log 有契約字樣（78／79／80）
- 單圖與 PDF 的雲端成功路（79／81）、逾時與冪等（80）

**對外行為仍然零改變**：`CLOUD_ROUTE` 預設 `off`、端點仍 **22**、`photo` 表零改動、
前端零改動、`requirements.txt` **還沒有 boto3**。
整個階段甲**一行 AWS 指令都沒有打過**（design6 §0 禁止第 1 條）。

測試累計 ＝ 開工基線 ＋ **7**（總覽 §9：**616**）。端點 **22**（不變）。

---

### ★ 下一步是閘門 G1（人的動作，實作者不可以自己勾掉）

> 🚦 **★G1 就在本 phase 之後、Phase 82 之前。**
> 下表逐字抄自總覽 §4。**沒有產品負責人明確點頭，一行 AWS 指令都不准打。**

| 項目 | 內容 |
|---|---|
| 是什麼 | 「閘門與 fallback 做完了、產品負責人親眼看過，可以開 AWS 帳號了」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design6 §0 甲那列三條：① 敏感／不確定**零 S3 呼叫** ② 假遠端關閉時非敏感也走 `run_ingest_job` ③ pytest 不連 AWS。逐條指令見總覽 **§5.1** |
| 沒過會怎樣 | **Phase 82 起全部停擺，一行 AWS 指令都不准打**（design6 §0 禁止第 1 條）。不能「先開個帳號放著」——開戶就開始算 Free plan 的 6 個月 |
| 卡住時怎麼辦 | 若是測試沒過 → 回 74〜81 對應的 phase 修。若是產品負責人對「哪些關鍵字算敏感」有意見 → 回 **Phase 74** 改 `SENSITIVE_KEYWORDS`／`NON_SENSITIVE_KEYWORDS`（那是兩個模組常數，改完只影響 74 的測試）。**不要**用「先開 S3 試試看」繞過——甲全部是本機的事，修起來很快 |

**把下面三段輸出交給產品負責人看**（總覽 §5.1 的三條）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 敏感／不確定零 S3 呼叫；照片仍入收件箱
pytest tests/integration/test_gated_ingest.py -v
#   預期：test_敏感照片走本機_零submit_job記下privacy與route 綠
#         test_不確定照片走本機_零submit 綠
#         兩顆的斷言都含「假信箱的 put_calls == 0」與「收件箱多一張」

# ② 假遠端關閉時，非敏感也走 run_ingest_job
pytest tests/integration/test_gated_ingest.py -k 遠端關閉 -v
#   預期綠，而且 caplog 斷言含 fallback=local reason=remote_unavailable

# ③ pytest 不連 AWS（三個死埠一起指，顆數不變）
pytest -q                                    # 預期：616 passed
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q # 預期：顆數一模一樣
```

**★G1 通過之後**才進 **Phase 82**（AWS 帳號與工具：Free plan 開戶、**先建 Budget**、
東京區、AWS CLI、IAM user）。

---

## 附：本文件引用的官方文件

- [pypdfium2（PDF 拆頁；本專案只在 `pdf_service.py` 用它）](https://pypdfium2.readthedocs.io/en/stable/)
- [SQS Standard Queue（at-least-once，所以要冪等）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [S3 物件鍵命名（`documents/{job_id}/input.pdf`）](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html)
- [Pydantic `model_dump()`／`model_validate`（result.json 的 understanding 來回轉換）](https://docs.pydantic.dev/latest/concepts/serialization/)
- [Python `enumerate(..., start=n)`（頁碼 1 起算）](https://docs.python.org/3/library/functions.html#enumerate)
