# Phase 81：雲端路 PDF

> 📌 **2026-09-02 校準紀錄**（本檔成稿於 2026-08-31，之後工作樹改過三次：Phase 80 的三處實作裁決、
> 2026-09-01 的閘門改判、2026-09-02 的「中文識別字全部改英文」。裁決全文見
> `.superpowers/sdd/phase0902/progress.md` 的 R0〜R7，事實與命名契約見同目錄 `brief-common.md`）：
>
> | 裁決 | 本檔怎麼改 |
> |---|---|
> | **R1 識別字一律英文** | 函式／變數／類別名全部英文（`_store_cloud_result`／`_store_image_result`／`_store_pdf_result`／`_store_pdf_page`；測試工具 `RECEIPT_UNDERSTANDING`／`RememberDeletedStore`／`WorkerMailbox`／`create_pdf_job`／`inbox_id`／`cloud_route`／`run`）。**`test_中文` 測試函式名、log 字樣、錯誤訊息、註解與 docstring 維持中文** |
> | **R2 步驟 4 不再整檔覆蓋** | `app/services/gated_ingest.py` 以**工作樹實檔**（Phase 80 落地版）為基準，只做「一行 import ＋ 一段 docstring ＋ 四支函式」的編輯；不准動的區塊逐條列在步驟 4 |
> | **R3 顆數** | 開工基線 **613**（不是本檔原寫的 609）；核心 +7、R4 +2 ＝ 完成後 **622**。（2026-09-02 fix wave 裁決 **R11** 又補了 2 顆守門測試 → 最終 **624**，見 §8.1） |
> | **R4 順手做 `max_pages`** | 新增步驟 1b：`pdf_service.render_pages()` 加 keyword-only `max_pages`，閘門的 PDF 分支只渲染第一頁（+2 顆） |
> | **R5 不 commit** | 步驟 6 改成「記工作樹快照」，commit 由產品負責人決定 |
> | **R6 改判前字眼清零** | 閘門自 2026-09-01 起是 `VlmGate`：**一定讀檔、看圖判斷，不依賴檔名**。本檔原本殘留的「靠檔名關鍵字判斷、再由第二顆模型補位」那一整套舊說法（含兩個已否決的關鍵字常數名）全部刪除 |

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
| **design5 D11／D12（未推翻）** | 一檔一任務；重試單位是「一頁」；至少一頁成功就算整筆成功 | `_store_pdf_result()` 的迴圈與收尾 |
| **總覽 §10.2 F** | PDF 的每頁 PNG 由**本機**再 `render_pages()` 一次 | `_store_pdf_result()` 的第 ② 步 |
| **總覽 §2.4.3** | `result.json` 的 PDF 形狀（`kind: "pdf"` ＋ `pages`） | 假工人照這個形狀寫；`_store_pdf_result()` 照這個形狀讀 |
| **總覽 §10.2 R** | 落庫順序固定為 INSERT → **立刻** `store.update(job_id, photo_ids=[photo_id])` → `cleanup()` → `finish_image_job`（`cleanup` 是 S3 網路呼叫，期間被殺不可以變成重送時雙 INSERT） | 單圖分支逐字同 Phase 80；PDF 分支每頁的 `store.update(pages_done=, photo_ids=)` 在整份 `cleanup()` **之前**（`_store_pdf_result()` ③ 的迴圈 → ④ 收尾） |
| **總覽 §10.2 M5／phase0901 ledger Task 2 parked → R4** | 閘門對多頁 PDF 只需要**第一頁**，卻整份 2× 渲染（純浪費 CPU／記憶體，2026-09-02 裁決 R4 順手做掉） | 步驟 1b：`render_pages(..., max_pages=None)` ＋ 閘門改 `max_pages=1`（`test_max_pages只渲染前幾頁`、`test_PDF閘門只渲染第一頁`） |

---

## 2. 前置條件

**要先做完的 phase：74、75、76、77、78、79、80。**
（75 一起列出來的理由：閘門真模型那一支 `OllamaPrivacyModel` 是 75 接的，
而步驟 1b 要改的 `VlmGate` PDF 分支就在 74／75 那條線上。）

**★G1 還沒到**：全程零 AWS。

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc     # db 與 redis 要 Up (healthy)
pytest -q
```

預期：`613 passed`、0 skipped（2026-09-02 實查；總覽 §9 的 609 是 80 的舊估值，
裁決 R3 已改成實查值）。以實查數字為準，本文稱它「**開工基線**」。

確認本機路的 PDF 規則還在（本 phase 要逐條複製它的行為），
順便看一眼 `render_pages` 現在的簽章（步驟 1b 會加 `max_pages`）：

```bash
python -c "
import inspect
from app.services import ingest_job, pdf_service
print(ingest_job.ERROR_PDF_UNREADABLE)
print(ingest_job.ERROR_PDF_ALL_PAGES_FAILED)
print(ingest_job.PDF_PAGE_CONTENT_TYPE)
print('拆頁函式簽章：', inspect.signature(pdf_service.render_pages))
"
```

預期（2026-09-02 實查）：

```text
這份 PDF 讀不開或沒有內容
PDF 每一頁 AI 都看不懂
image/png
拆頁函式簽章： (pdf_bytes: 'bytes', scale: 'float' = 2.0) -> 'list[bytes]'
```

最後那一行**還沒有** `max_pages`——步驟 1b 才會把它加上去（裁決 R4）。
（型別被引號包住是因為 `pdf_service.py` 有 `from __future__ import annotations`，
註記在執行期是字串，不是簽章寫錯了。）

> ⚠️ **絕對不要同時跑兩份 pytest。**

---

## 3. 範圍

### 做

1. **`tests/fakes.py`**：`fake_worker_process_one()` 支援 PDF
   （用 `pdf_service.render_pages` 算頁數、每頁一筆結果），新增私有小工具 `_fake_worker_read_pdf()`。
2. **`app/services/gated_ingest.py`**（**以工作樹實檔為基準只加 PDF 分支**，裁決 R2）：
   - `_store_cloud_result()` 改成**分流器**（依 `job["content_type"]`）——**沿用既有函式名**，
     它是 `run_gated_ingest_job()` 與 `_resume_cloud_route()` 兩處的呼叫點
   - 原本的本體改名為 `_store_image_result()`（**函式體一個字都不動**，含總覽 §10.2 R 的
     「INSERT → 立刻寫 `photo_ids` → `cleanup()` → `finish_image_job`」順序）
   - 新增 `_store_pdf_result()`（含「工人回的頁數與本機拆出的頁數對不上」的防禦 log）與 `_store_pdf_page()`
   - import 補 `pdf_service`；模組 docstring 的「【本 phase（80）做到哪裡】」改成 81 版
3. **新建 `tests/integration/test_gated_ingest_pdf.py`**（7 顆）。
4. **（2026-09-02 裁決 R4）`max_pages`**：`app/services/pdf_service.py` 的 `render_pages()`
   加一個 keyword-only 參數 `max_pages: int | None = None`（`None` ＝全部渲染，**既有呼叫端一個字都不改**）；
   `app/services/privacy_gate.py` 的閘門 PDF 分支改成 `render_pages(image_bytes, max_pages=1)[0]`。
   +2 顆單元測試。理由：閘門只看第一頁，卻對 30 頁的掃描件整份 2× 渲染——純浪費 CPU／記憶體，
   改動 3 行、零行為變化（phase0901 ledger Task 2 parked minor ＋ FINAL review M5 留給 81 的項目）。

### 明確不做（防手滑）

| 不做什麼 | 為什麼 |
|---|---|
| 讓工人把每頁 PNG 也放進 S3 | 物件數會隨頁數暴增（30 頁＝30 個物件要上傳、下載、清理）。本機拆頁是純 CPU、幾百毫秒（總覽 §10.2 F） |
| 一頁一個 job（或一頁一則 SQS 訊息） | design5 D11「一檔一任務」**沒有被推翻**。拆開的話進度面板畫不出「一檔一列」，而 design6 §3 明文「前端不新增」 |
| 用陣列位置（index）去配對工人回來的 `pages` | 順序不保證（工人未來若改成並行看圖就會亂）。一律用 `page` 這個欄位對 |
| 為 PDF 另外定義錯誤訊息 | 沿用既有的 `ERROR_PDF_UNREADABLE`／`ERROR_PDF_ALL_PAGES_FAILED`——使用者看到的字要與本機路**完全一樣**（他根本不知道有雲端這回事） |
| 讓「某一頁失敗」變成整筆失敗 | design5 D12：至少一頁成功就算整筆成功。改掉會讓「30 頁裡有一頁是空白頁」的檔整份消失 |
| 在本機重看那些工人看不懂的頁 | 與單圖同一個理由（總覽 §10 追認項 g）：遠端活著、只是看不懂，本機再看也一樣，而且會把 3 次變成 6 次 |
| 動 `app/services/ingest_job.py` | 它仍然是 fallback 的目的地，本 phase 一個字都不改。⚠ **驗法不能用 `git diff`**：工作樹裡 74〜80 的改動全都還沒 commit（產品負責人指示不 commit），`git diff app/services/ingest_job.py` 現在本來就有輸出。改用開工快照相減，寫法見 §6 |
| 為了 R4 順手改 `ingest_job.py` 的 `render_pages()` 呼叫 | 本機路要的是**整份**的每一頁，`max_pages` 預設 `None` ＝ 全部渲染，所以 `ingest_job.py:275` 那一行不必動也不該動（R4 的向下相容就是靠這件事證明的） |

---

## 4. 實作步驟

> 🧪 **全程 TDD（先紅再綠）**：步驟 1〜2 先寫**會紅**的測試並**真的跑它、親眼看到紅**。

### - [x] 步驟 1：先讓假工人看得懂 PDF——`tests/fakes.py`

> 📌 這一步嚴格說是「測試工具」不是「測試」，所以放在寫測試之前：
> 步驟 2 的測試檔要用到它。

- [x] 檔頭 import 區加**一行** `from app.services import pdf_service`，放在 `from app.core import config`
  之後、`from app.services.ask_workflow import RouteDecision` 之前（ruff 的 isort 依模組路徑排序，
  `app.services` 排在 `app.services.ask_workflow` 前面）。改完那幾行長這樣
  （**以 2026-09-02 的工作樹實檔為準**＝ `tests/fakes.py` 的 L17〜L23，只有中間那一行是新的）：

```python
from app.core import config
from app.services import pdf_service
from app.services.ask_workflow import RouteDecision
from app.services.cloud_ingest import MailboxMessage
from app.services.privacy_gate import PrivacyJudgement, Verdict
from app.services.staging_service import STAGING_EXTENSIONS
from app.services.vlm_service import PhotoUnderstanding
```

> 📌 `tests/fakes.py` 的 import 是「一行一個模組」的寫法——**沒有**括號式的
> `from app.services import (…)` 區塊（那是 `app/dependencies.py` 的長相），不要去找。
> 放對位置的話 `ruff check` 不會報 `I001`。細節見本文件 §7 陷阱 9。

- [x] 把 Phase 79 寫的 `fake_worker_process_one()`（工作樹實檔 `tests/fakes.py` 的最後一支函式）
  **整段換成**下面這兩支。原本的單圖邏輯一字未改，只多了兩件事：
  docstring 補「單圖／PDF」兩個小標，以及 `result = {...}` 前面多一個 `if …endswith(".pdf")` 岔路。

```python
def fake_worker_process_one(mailbox, understanding=None, *, worker_version="fake-worker"):
    """假工人：把 mailbox.jobs 裡的**第一則**訊息做成 result.json ＋ 一則 results 訊息。

    它**不是** app/workers/cloud_worker.py（那是 Phase 87 的事），只是「另一頭真的
    有人在做事」的最小替身：不看圖、不解析影像，照著測試指定的答案寫結果。

    單圖（.jpg／.png）：
      understanding 給一個 PhotoUnderstanding ＝ 工人一次就看懂了
      understanding 給 None                    ＝ 工人試了三次都看不懂

    PDF（.pdf，Phase 81 加）：見 _fake_worker_read_pdf()。

    ★ 順序刻意寫成「**先 PutObject、才 SendMessage**」（design6 D9 的順序鐵律）：
      假件也要教對的做法，Phase 87 的真工人才有樣本可比。

    回傳寫出去的那份 result（測試想再檢查內容時用得到）；jobs 佇列空的時候回 None。
    """
    message = mailbox.receive_job(wait_seconds=0)
    if message is None:
        return None

    if (message.s3_key or "").endswith(".pdf"):
        result = _fake_worker_read_pdf(mailbox, message, understanding, worker_version)
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


def _fake_worker_read_pdf(mailbox, message, understanding, worker_version: str) -> dict:
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
        page_count = len(pdf_service.render_pages(raw))
    except pdf_service.PdfUnreadableError:
        page_count = 0

    if isinstance(understanding, list):
        per_page = list(understanding) + [None] * max(0, page_count - len(understanding))
    else:
        per_page = [understanding] * page_count

    pages = []
    for page_number, page_understanding in enumerate(per_page[:page_count], start=1):
        pages.append(
            {
                "page": page_number,
                "understood": page_understanding is not None,
                "attempts": 1 if page_understanding is not None else config.VLM_MAX_ATTEMPTS,
                "understanding": (
                    page_understanding.model_dump() if page_understanding is not None else None
                ),
            }
        )

    return {
        "job_id": message.job_id,
        "worker_version": worker_version,
        "kind": "pdf",
        "pages": pages,
    }
```

### - [x] 步驟 1b：`max_pages`（TDD；2026-09-02 裁決 R4）

> 📌 這一步與 PDF 雲端路**沒有先後相依**（它動的是閘門那條線），只是既然本 phase 正在碰
> `pdf_service`，就順手把它做掉。想先做步驟 2〜5 再回來做也可以，**顆數與驗收清單不變**。
>
> 為什麼要做：`VlmGate` 的 PDF 分支寫的是 `render_pages(image_bytes)[0]`——
> 只用第一頁，卻把整份 PDF 都用 2× 倍率渲染過一遍。一份 30 頁的掃描件因此白畫 29 張
> 1200×1700 的圖，純浪費 CPU 與記憶體。改動 3 行、**零行為變化**。

- [x] 先寫兩顆**會紅**的測試。

  第一顆放 `tests/unit/test_pdf_service_unit.py`（接在既有的 `test_壞檔丟PdfUnreadableError` 後面；
  這個檔已經 `from app.services import pdf_service` ＋ `from tests.fakes import make_pdf_bytes`，
  不必再加 import）：

```python
def test_max_pages只渲染前幾頁():
    """閘門只需要第一頁（Phase 81 裁決 R4）：30 頁的掃描件不必整份渲染。

    max_pages=None ＝ 全部——既有呼叫端（ingest_job._run_pdf_job）一個字都不必改，
    這一顆就是那個「向下相容」的證據。給的數字比實際頁數大也不會炸。
    """
    pdf_bytes = make_pdf_bytes(3)

    assert len(pdf_service.render_pages(pdf_bytes, max_pages=1)) == 1
    assert len(pdf_service.render_pages(pdf_bytes, max_pages=None)) == 3
    assert len(pdf_service.render_pages(pdf_bytes, max_pages=5)) == 3
```

  第二顆放 `tests/unit/test_privacy_gate_unit.py`（接在既有的 `test_PDF渲染失敗回UNCERTAIN` 後面。
  `make_pdf_bytes` 沿用該檔既有的寫法：在函式裡 local import，不動檔頭那一行）：

```python
def test_PDF閘門只渲染第一頁(monkeypatch):
    """R4：閘門對多頁 PDF 只渲染第一頁。

    包住**真的** render_pages（不是換成假的）：既驗「有沒有把 max_pages 傳下去」，
    也驗「傳下去之後真的還拿得到一張 PNG」——換成假的就只驗得到前者。
    """
    from tests.fakes import make_pdf_bytes

    seen_kwargs: dict = {}
    real_render_pages = privacy_gate.pdf_service.render_pages

    def recording_render_pages(pdf_bytes, *args, **kwargs):
        seen_kwargs.update(kwargs)
        return real_render_pages(pdf_bytes, *args, **kwargs)

    monkeypatch.setattr(privacy_gate.pdf_service, "render_pages", recording_render_pages)

    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(model).classify(
        filename="scan.pdf",
        content_type="application/pdf",
        load_bytes=lambda: make_pdf_bytes(3),
    )

    assert seen_kwargs.get("max_pages") == 1, "閘門要明講『只要第一頁』"
    assert model.calls == 1
    assert model.last_image_bytes[:4] == b"\x89PNG", "送進模型的仍然是那一頁的 PNG"
```

- [x] 跑它，確認是**紅的**：

```bash
pytest tests/unit/test_pdf_service_unit.py::test_max_pages只渲染前幾頁 \
       tests/unit/test_privacy_gate_unit.py::test_PDF閘門只渲染第一頁 -q
```

  預期：2 紅。第一顆是 `TypeError: render_pages() got an unexpected keyword argument 'max_pages'`；
  第二顆是 `AssertionError: assert None == 1`（閘門現在根本沒傳這個參數）。

- [x] 綠：`app/services/pdf_service.py` 的 `render_pages()` 改簽章與迴圈。
  **只動這三處**，`DEFAULT_SCALE`、`PdfUnreadableError`、兩個 `raise`（壞檔、零頁）都不動：

```python
def render_pages(
    pdf_bytes: bytes, scale: float = DEFAULT_SCALE, *, max_pages: int | None = None
) -> list[bytes]:
    """把整份 PDF 逐頁渲染成 PNG 位元組，回傳的順序即頁序。

    順序很重要：呼叫端用「第幾個」回報 skipped_pages 的頁碼。

    max_pages 只給閘門用：看第一頁就夠時不必整份渲染（None ＝ 全部，既有呼叫端不必改）。
    """
```

  迴圈本體只在最前面多兩行（其餘四行一字不改）：

```python
        pages: list[bytes] = []
        for index, page in enumerate(document):
            if max_pages is not None and index >= max_pages:
                break
            # render() 回傳的是 PDFium 的點陣圖，to_pil() 換成 Pillow 圖片物件，
            # 再存成 PNG bytes——之後的存檔與縮圖都吃 bytes，跟一般上傳沒有兩樣。
            image = page.render(scale=scale).to_pil()
```

  > ⚠ `break` 要放在**迴圈裡面**，不要改成 `for page in list(document)[:max_pages]`：
  > `PdfDocument` 是惰性容器，先攤成 list 就等於把每一頁的物件都建出來，省不到什麼。
  > 也**不要**把「零頁 → raise」搬進迴圈——`max_pages=0` 與「這份 PDF 真的沒有頁」
  > 是兩件事，前者本來就沒有呼叫端會傳。

- [x] 綠：`app/services/privacy_gate.py` 的 `VlmGate.classify()` PDF 分支，
  **只改呼叫那一行**（上面兩行「只看第一頁」的註解不動）：

```python
                image_bytes = pdf_service.render_pages(image_bytes, max_pages=1)[0]
```

- [x] 再跑一次那兩顆（預期 `2 passed`），然後把**所有會碰到 `render_pages()` 的檔**一起跑一遍，
  確認向下相容真的成立：

```bash
pytest tests/unit/test_pdf_service_unit.py::test_max_pages只渲染前幾頁 \
       tests/unit/test_privacy_gate_unit.py::test_PDF閘門只渲染第一頁 -q   # 預期 2 passed

pytest tests/unit/test_pdf_service_unit.py tests/unit/test_privacy_gate_unit.py \
       tests/integration/test_ingest_job_pdf.py tests/integration/test_pdf_upload.py -q
```

  第二句預期：**全綠、一顆都不准紅**（`test_pdf_service_unit.py` 4、
  `test_privacy_gate_unit.py` 23，另兩檔以實查為準）。

### - [x] 步驟 2：先寫測試（紅）——新建 `tests/integration/test_gated_ingest_pdf.py`

整份貼上：

```python
"""PDF 走雲端路的整合測試（design6 D7／D17、design5 D11／D12；Phase 81）。

與 test_gated_ingest.py 同一套玩法：**不打 HTTP**，直接呼叫 run_gated_ingest_job()。
PDF 的位元組用 Phase 28 就有的 tests/fakes.make_pdf_bytes(pages=N) 現產。

⚠ 這裡的「第幾頁」一律 **1 起算**（與既有 skipped_pages 的頁碼慣例相同）。
   程式裡的 pages_done 是「已處理幾頁」，所以做完第 2 頁時 pages_done == 2。

本檔的三個小工具（WorkerMailbox／cloud_route／RememberDeletedStore）與
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

RECEIPT_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class RememberDeletedStore(InMemoryJobStore):
    """成功時 job 會被刪掉，但測試還想看「刪掉之前 pages_done／photo_ids 是什麼」。"""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: dict[str, dict] = {}

    def delete(self, job_id: str) -> None:
        snapshot = self.get(job_id)
        if snapshot is not None:
            self.deleted[job_id] = dict(snapshot)
        super().delete(job_id)


class WorkerMailbox(FakeMailbox):
    """本機在等結果的時候，「另一頭」剛好把工作做完了。

    understanding 直接往下傳給假工人，所以可以給「逐頁的清單」
    （例如 [RECEIPT_UNDERSTANDING, None] ＝ 第 1 頁看得懂、第 2 頁看不懂）。
    """

    def __init__(self, understanding=None, *, worker_on_duty: bool = True) -> None:
        super().__init__()
        self.understanding = understanding
        self.worker_on_duty = worker_on_duty
        self.worker_runs = 0

    def receive_result(self, wait_seconds: int):
        if self.worker_on_duty and self.jobs:
            fake_worker_process_one(self, self.understanding)
            self.worker_runs += 1
        return super().receive_result(wait_seconds)


def create_pdf_job(
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


def inbox_id() -> int:
    return next(f for f in photo_repository.list_folders() if f["is_inbox"])["id"]


def cloud_route(mailbox, *, running: bool = True, timeout_seconds: int = 5):
    return cloud_ingest.CloudRoute(mailbox, FakeProbe(running), timeout_seconds=timeout_seconds)


def run(job_id: str, *, store, gate, cloud, vlm=None, embeddings=None) -> None:
    gated_ingest.run_gated_ingest_job(
        job_id,
        store=store,
        vlm=vlm if vlm is not None else FakeVLM(RECEIPT_UNDERSTANDING),
        embeddings=embeddings if embeddings is not None else FakeEmbeddings(),
        now=NOW,
        gate=gate,
        cloud=cloud,
    )


def test_兩頁都成功_入庫兩列_job被刪_S3清空():
    """PDF 的雲端路走順的樣子：一份兩頁的 PDF ＝ 兩列照片，全部進收件箱。"""
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 2
    assert len(photo_repository.list_photos_in_folder(inbox_id())) == 2
    last_job = store.deleted[job_id]
    assert last_job["page_count"] == 2
    assert last_job["pages_done"] == 2
    assert len(last_job["photo_ids"]) == 2
    assert last_job["route"] == "cloud"
    assert store.get(job_id) is None, "成功＝job 被刪掉"
    assert mailbox.objects == {}, "S3 要清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_第二頁看不懂_只入庫一列_跳過一頁():
    """design5 D12（未推翻）：某一頁不成立就跳過它，其他頁照樣入庫、整筆仍算成功。

    「跳過了幾頁」不另外存欄位——算得出來：pages_done − len(photo_ids)。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox([RECEIPT_UNDERSTANDING, None])  # 逐頁指定：第 2 頁看不懂

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 1
    last_job = store.deleted[job_id]
    assert last_job["pages_done"] == 2, "跳過的頁也要算進 pages_done"
    assert len(last_job["photo_ids"]) == 1
    assert store.get(job_id) is None, "至少一頁成功就算整筆成功"
    assert mailbox.objects == {}


def test_pages是空清單_job標failed且錯誤是PDF讀不開():
    """工人回報「這份 PDF 拆不開」（pages 是空清單，總覽 §2.4.3）。

    使用者看到的訊息要與本機路**一字不差**——他不知道有雲端這回事。
    """
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, data=b"this-is-not-a-pdf")
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_UNREADABLE
    assert mailbox.objects == {}, "失敗也要把 S3 清乾淨"
    assert not staging_service.staging_path(job_id, "application/pdf").exists()


def test_全部頁都失敗_job標failed():
    """每一頁工人都看不懂（每頁各試了 3 次）＝ 0 頁成功 ＝ 整筆失敗（design5 D12）。"""
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = WorkerMailbox(None)  # 每一頁都看不懂

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert photo_repository.count_photos() == 0
    job = store.get(job_id)
    assert job["status"] == "failed"
    assert job["error"] == ingest_job.ERROR_PDF_ALL_PAGES_FAILED
    assert job["pages_done"] == 2, "兩頁都處理過了（只是都跳過）"
    assert mailbox.objects == {}


def test_崩潰重送從pages_done續跑不重插():
    """design6 D17 ＋ design5 §4.4：從 pages_done 的**下一頁**接著跑。

    重現方式：手動做出「上一趟已經做完第 1 頁、而且已經送去雲端」的狀態
    （pages_done=1、photo_ids 帶著那一頁的 id、route=cloud），
    再把工人算好的結果放進 S3，然後重跑一次。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=3)

    # 第 1 頁在上一趟已經入庫了。直接用 repository 插一列就好——本顆要的是那個**狀態**
    first_page = photo_repository.insert_photo(
        text=RECEIPT_UNDERSTANDING.text,
        category="未分類",
        location=RECEIPT_UNDERSTANDING.location,
        items=RECEIPT_UNDERSTANDING.items,
        content_time=None,
        embedding=FakeEmbeddings().embed_query(RECEIPT_UNDERSTANDING.text),
        uploaded_at=NOW(),
    )
    store.update(job_id, page_count=3, pages_done=1, photo_ids=[first_page["id"]], route="cloud")
    assert photo_repository.count_photos() == 1

    # 工人上一趟算好的結果還在 S3（三頁都看懂了）。這裡直接借假工人把 result.json 寫好：
    # 放一份真的 input.pdf ＋ 發一則 jobs 訊息 → 假工人做一次 → 再把 results 訊息清掉
    # （這一趟不是靠 results 訊息叫醒的，是崩潰重送 → 靠 fetch_result 直接去 S3 拿）。
    # ⚠ input.pdf 一定要是**真的 PDF**：假工人用產品碼的 render_pages() 去數頁數，
    #   放 b"x" 的話它會判成「拆不開」，這一顆就會紅在完全無關的地方。
    mailbox = FakeMailbox()
    input_key = mailbox.input_key(job_id, "application/pdf")
    mailbox.put_object(input_key, make_pdf_bytes(pages=3), "application/pdf")
    mailbox.send_job(job_id, input_key)
    fake_worker_process_one(
        mailbox, [RECEIPT_UNDERSTANDING, RECEIPT_UNDERSTANDING, RECEIPT_UNDERSTANDING]
    )
    mailbox.results.clear()

    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 就算換答案也不該被問到
    run(job_id, store=store, gate=gate, cloud=cloud_route(mailbox))

    assert gate.calls == 0, "route 已經有值，不可以再問一次閘門"
    assert photo_repository.count_photos() == 3, "第 1 頁不可以被插第二次"
    last_job = store.deleted[job_id]
    assert last_job["pages_done"] == 3
    assert last_job["photo_ids"][0] == first_page["id"], "原本那一頁的 id 要留著"
    assert len(last_job["photo_ids"]) == 3


def test_PDF判定敏感時零submit走本機():
    """design6 D3／§9 必釘第 1 條：PDF 走的是同一個岔路口，沒有例外。

    ⚠ 真閘門 `VlmGate` 看的是**圖**不是檔名（2026-09-01 改判；design6 D4、總覽 §10.1 f）——
      PDF 的話它會渲染第一頁再問模型。本檔不測那一段（那是 test_privacy_gate_unit.py 的事），
      直接用 `FakePrivacyGate(Verdict.SENSITIVE)` 指定 verdict，
      驗的是「敏感的 PDF 一個位元組都不會出門」。
    """
    store = RememberDeletedStore()
    job_id = create_pdf_job(store, pages=2)
    mailbox = FakeMailbox()

    run(job_id, store=store, gate=FakePrivacyGate(Verdict.SENSITIVE), cloud=cloud_route(mailbox))

    assert mailbox.put_calls == 0, "敏感檔的 PutObject 次數必須是 0"
    assert mailbox.send_job_calls == 0
    assert photo_repository.count_photos() == 2, "照樣走本機入庫（兩頁）"
    assert store.deleted[job_id]["privacy"] == "SENSITIVE"
    assert store.deleted[job_id]["route"] == "local"


def test_submit的input鍵名是input點pdf():
    """design6 §2.2：`documents/{job_id}/input.pdf`。

    工人是靠副檔名推 content_type 的（總覽 §2.6 第 4 條），推錯就會拿去當圖片看。
    ★ 用 `mailbox.calls`（呼叫流水帳）驗：`objects` 在成功之後會被 cleanup 清空，
      流水帳則會留著整趟的歷史。
    """
    store = InMemoryJobStore()
    job_id = create_pdf_job(store, pages=1)
    mailbox = WorkerMailbox(RECEIPT_UNDERSTANDING)

    run(
        job_id, store=store, gate=FakePrivacyGate(Verdict.NON_SENSITIVE), cloud=cloud_route(mailbox)
    )

    assert f"put_object documents/{job_id}/input.pdf" in mailbox.calls
    assert f"put_object documents/{job_id}/context.json" in mailbox.calls
    assert photo_repository.count_photos() == 1
```

### - [x] 步驟 3：跑它，確認是**紅的**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_gated_ingest_pdf.py -q
```

預期：**多顆紅**。最典型的錯誤是「PDF 走了單圖的落庫段」：

```text
AssertionError: assert 0 == 2
 +  where 0 = count_photos()
```

（Phase 80 的 `_store_cloud_result` 只認 `result["understanding"]`，
PDF 的結果沒有那個鍵 → 被判成「看不懂」→ job 標 failed、零列照片。）

### - [x] 步驟 4：綠——`app/services/gated_ingest.py` 補上 PDF 分支

> ⚠ **不是整檔覆蓋**（2026-09-02 裁決 R2）。本檔成稿於 2026-08-31，之後 `gated_ingest.py`
> 又被改過三次（Phase 80 的三處實作裁決、2026-09-01 的閘門改判、2026-09-02 的識別字英文化），
> 照舊版整檔貼會**把那些改動全部洗掉**。請以**工作樹實檔**為基準，用 Edit 做下面六處。

**先看一眼現況**（本步驟開始前，這個檔是 445 行，應該長這樣）：

```bash
grep -n "^from app.services import\|^def \|【本 phase" app/services/gated_ingest.py
```

預期（2026-09-02 實查；行號會隨編輯往下移，只用來確認「起點沒認錯」）：

```text
28:【本 phase（80）做到哪裡】
46:from app.services import cloud_ingest, ingest_job, staging_service, vlm_service
61:def run_gated_ingest_job(
188:def _remote_available(cloud, job_id: str) -> bool:
203:def _fallback_to_local(
226:def _best_effort_cloud_cleanup(cloud, job_id: str) -> None:
240:def _resume_cloud_route(
295:def _store_cloud_result(
392:def _embed_with_retries(
424:def _parse_understanding(payload: object) -> vlm_service.PhotoUnderstanding | None:
```

#### ⛔ 以下一個字都不准動

| 不准動的東西 | 為什麼 |
|---|---|
| `run_gated_ingest_job()` **全文** | 裡面有三樣東西是 80 才長出來的：閘門改判之後的那段 `load_bytes` 註解（「一定會呼叫 load_bytes」）、**裁決 R14 的 `cloud.wait_result(...)` try/except**（信箱丟例外要當成逾時，否則 job 永遠卡在 analyzing）、以及呼叫 `_store_cloud_result(...)` 前那 **7 行**「這裡傳的是進門時那份 job 複本」的註解（final fix M2）。本 phase 連一個字都不必改它——分流是在 `_store_cloud_result()` 裡面做的 |
| `_remote_available()`、`_fallback_to_local()`、`_best_effort_cloud_cleanup()` | 與檔案型別無關，PDF 走的是同一批 |
| `_resume_cloud_route()` **全文** | 尤其落庫前重讀的那一行 `latest_job = store.get(job_id) or job`（D17 的最後一道保險，校準時發現舊版重貼碼漏掉它）。PDF 的崩潰重送走的就是這一支，漏了會在 `--concurrency=2` 下重插 |
| `_embed_with_retries()`、`_parse_understanding()` | 兩支都與型別無關，PDF 每一頁直接重用；`_parse_understanding()` 的「多餘鍵會被忽略」那段措辭是 80 的定稿，不要換回舊版 |
| 四個 `REASON_*` 常數 | design6 §2.1 的契約字串 |

> ★ **分流器沿用既有名字 `_store_cloud_result` 是刻意的**：它有**兩個**呼叫點
> （`run_gated_ingest_job()` 最後一行、`_resume_cloud_route()` 裡面），
> 沿用名字就不必動那兩處——也就順便保住了上面那 7 行註解與重讀行。

**改完之後的函式順序**（前五支原地不動）：

```text
run_gated_ingest_job → _remote_available → _fallback_to_local → _best_effort_cloud_cleanup
→ _resume_cloud_route → _store_cloud_result（分流器）→ _store_image_result
→ _store_pdf_result → _store_pdf_page → _embed_with_retries → _parse_understanding
```

最後兩支本來就在檔尾，**不必搬動**——新的三支插在 `_resume_cloud_route()` 與
`_embed_with_retries()` 之間即可。

#### - [x] 4-1 import 補 `pdf_service`（一行換一行）

原行：

```python
from app.services import cloud_ingest, ingest_job, staging_service, vlm_service
```

新行（照字母序插在 `ingest_job` 與 `staging_service` 之間，ruff 的 isort 才不會報 `I001`）：

```python
from app.services import cloud_ingest, ingest_job, pdf_service, staging_service, vlm_service
```

#### - [x] 4-2 模組 docstring：「【本 phase（80）做到哪裡】」那一段換成 81 版

原文（五行）：

```text
【本 phase（80）做到哪裡】
單圖的雲端路整圈都通了，四種「遠端不可用」也全部有退路：
不是 running／沒憑證（Phase 78）、送出失敗（79）、逾時（79 接、80 補測試）、
崩潰重送但沒有結果（80）。**還沒做**：PDF 的雲端路（Phase 81）——
本檔的落庫段目前只認單圖的 result.json。
```

改成：

```text
【本 phase（81）做到哪裡】
雲端路**全部做完**了：單圖與 PDF、順利的一圈與四種不順利
（不是 running／沒憑證（Phase 78）、送出失敗（79）、逾時（79／80）、
崩潰重送但沒有結果（80））。接下來是 ★G1——產品負責人點頭之後才開始碰 AWS。

PDF 的雲端路有一件事與單圖不同（總覽 §10.2 F）：**本機自己再拆一次頁**。
工人拆頁是為了看圖，本機拆頁是為了拿到「要存檔的那幾張 PNG」——
把工人拆好的每頁 PNG 放 S3 會讓物件數隨頁數暴增，而拆頁是純 CPU、幾百毫秒的事。
```

#### - [x] 4-3 把現在的 `_store_cloud_result()` 改名成 `_store_image_result()`

**只改 `def` 那一行的名字**：

```python
def _store_cloud_result(      # ← 原本
def _store_image_result(      # ← 改成
```

docstring（`"""拿工人看好的結果，在**本機**完成剩下的事（design6 D13）：` 那一段）
與函式體的 ①〜⑥（冪等 → 看不懂 → 轉向量 → INSERT → **立刻寫 photo_ids** → cleanup ＋ 收尾 ＋ 契約 log）
**一個字都不動**。

> 📌 校準註（2026-09-02）：本檔舊版曾把這段函式體整段重貼一次。實檔與那份重貼碼比對之後
> **語意完全相同**，差別只有識別字英文化以及隨之而來的兩處自動換行
> （`understanding = (...)` 與 `_embed_with_retries(...)` 被 ruff format 折成多行）。
> 既然要保的就是實檔那一份，本步驟改成「只改名」，不再貼函式體——**貼了就有洗掉的風險**。

#### - [x] 4-4 在 `_store_image_result()` **前面**插入分流器（沿用舊名 `_store_cloud_result`）

```python
def _store_cloud_result(
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
        _store_pdf_result(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
        return
    _store_image_result(job, result, store=store, embeddings=embeddings, now=now, cloud=cloud)
```

#### - [x] 4-5 新增 `_store_pdf_result()`（放在 `_store_image_result()` 後面）

```python
def _store_pdf_result(
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
        _best_effort_cloud_cleanup(cloud, job_id)
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
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_UNREADABLE, store=store, content_type=content_type
        )
        return

    store.update(job_id, page_count=len(page_images))
    prompt_context = ingest_job.load_prompt_context()

    # ③ 依頁碼配對（工人回的順序不保證，用 page 這個欄位對，不要用陣列索引）
    page_results = {page.get("page"): page for page in pages if isinstance(page, dict)}
    if len(page_results) != len(page_images):
        # 兩邊拆的是同一份檔、用的是同一支 pdf_service，正常情況頁數一定相同。
        # 對不上＝工人是別的版本、或檔在半路壞了。對不上的頁由下面的 .get() 當「沒有結果」跳過，
        # 這裡先大聲記一行——不然「少了幾頁」會安靜地變成幾個跳頁，事後很難查。
        logger.warning(
            "job %s：工人回了 %d 頁的結果，本機拆出 %d 頁，對不上的頁會被跳過",
            job_id,
            len(page_results),
            len(page_images),
        )

    photo_ids: list[int] = list(job.get("photo_ids") or [])
    already_done = job.get("pages_done") or 0
    if already_done:
        logger.info(
            "job %s：崩潰重送，已處理 %d／%d 頁，從第 %d 頁接著跑",
            job_id,
            already_done,
            len(page_images),
            already_done + 1,
        )

    for page_number, page_bytes in enumerate(page_images[already_done:], start=already_done + 1):
        photo_id = _store_pdf_page(
            job_id,
            page_number,
            page_bytes,
            page_results.get(page_number),
            store=store,
            embeddings=embeddings,
            now=now,
            prompt_context=prompt_context,
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
        _best_effort_cloud_cleanup(cloud, job_id)
        ingest_job.fail_job(
            job_id, ingest_job.ERROR_PDF_ALL_PAGES_FAILED, store=store, content_type=content_type
        )
        return

    _best_effort_cloud_cleanup(cloud, job_id)
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
```

> 📌 `already_done` 這個**區域變數**只是「進門時已經做完幾頁」的快照，迴圈裡不會更新它
> （更新的是 JobStore 上的 `pages_done` 欄位）。名字與本機路 `ingest_job._run_pdf_job` **相同**（2026-09-02 裁決 R8），
> 兩邊指的是同一件事。

#### - [x] 4-6 新增 `_store_pdf_page()`（放在 `_store_pdf_result()` 後面）

```python
def _store_pdf_page(
    job_id: str,
    page_number: int,
    page_bytes: bytes,
    page_result: dict | None,
    *,
    store: JobStore,
    embeddings: Embeddings,
    now: Callable[[], datetime | None],
    prompt_context: ingest_job.PromptContext,
) -> int | None:
    """把 PDF 的一頁變成資料庫裡的一列；這一頁不成立就回 None（＝跳過它）。

    三種「跳過」：工人沒回這一頁、工人說看不懂、本機轉向量或寫檔失敗。
    三種都只影響**這一頁**——其他頁照樣入庫（design5 D12 的 skipped_pages 語意）。
    """
    understanding = (
        _parse_understanding(page_result.get("understanding"))
        if page_result and page_result.get("understood")
        else None
    )
    if understanding is None:
        logger.warning("job %s：第 %d 頁雲端看不懂或沒有結果，跳過這一頁", job_id, page_number)
        return None

    embedding = _embed_with_retries(
        job_id, understanding, store=store, embeddings=embeddings, prompt_context=prompt_context
    )
    if embedding is None:
        logger.warning("job %s：第 %d 頁本機轉向量失敗，跳過這一頁", job_id, page_number)
        return None

    try:
        return ingest_job.insert_photo_with_files(
            page_bytes,
            ingest_job.PDF_PAGE_CONTENT_TYPE,
            understanding,
            embedding,
            inbox_name=prompt_context.inbox_name,
            folders=prompt_context.folders,
            entities=prompt_context.entities,
            uploaded_at=now(),
        )
    except Exception:
        # 半成品已由 insert_photo_with_files 自己清乾淨（檔案＋資料列）
        logger.exception(
            "job %s：第 %d 頁入庫寫入失敗，半成品已清乾淨，跳過這一頁", job_id, page_number
        )
        return None
```

### - [x] 步驟 5：跑測試，看它轉綠

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_gated_ingest_pdf.py -v
```

預期最後一行：`9 passed`（核心 7 ＋ fix wave R11 的 2 顆）。

```bash
pytest tests/integration/test_ingest_job_pdf.py -q
```

預期：`9 passed`——**本機路的 PDF 一顆都不准紅**（本 phase 沒有改 `ingest_job.py`）。

步驟 1b 的兩顆也要一起確認（`render_pages` 的簽章換了，這兩個檔是最容易被波及的）：

```bash
pytest tests/unit/test_pdf_service_unit.py tests/unit/test_privacy_gate_unit.py -q
```

預期：`27 passed`（兩檔開工時實查 25 ＝ `test_pdf_service_unit.py` 3 ＋
`test_privacy_gate_unit.py` 22，各加一顆新的）、**一顆都不准紅**。

```bash
pytest -q
ruff format --check app tests scripts && ruff check app tests scripts
```

預期：**開工基線 613 ＋ 11**（核心 7 ＋ R4 2 ＋ fix wave R11 2）＝ **624**、0 skipped；格式與 lint 全過。

### - [x] 步驟 6：不 commit——記下工作樹快照

> ⚠ **產品負責人指示：全程不 commit、不 `git add`／`stash`／`mv`**（2026-09-02 裁決 R5，
> 沿用 phase0901 R3；總覽 §7 鐵律 12 的「commit 節奏由產品負責人決定」在本輪的具體落法）。
> 歸檔（`unfinish/` → `finish/`）也一樣，之後隨 commit 由產品負責人做。

驗收改用「工作樹快照相減」：本 phase 開工前與收工後各印一次 tree SHA，review 時 `git diff` 兩者。

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0902/snapshot-tree      # 開工前先跑一次，把 SHA 記下來
# ……做完步驟 1〜5 之後再跑一次……
.superpowers/sdd/phase0902/snapshot-tree      # 收工的 SHA
git diff -U10 <開工SHA> <收工SHA>              # 這就是本 phase 的全部改動
```

（`snapshot-tree` 只在物件庫多一顆 tree 物件：它複製一份 index 到暫存檔再 `write-tree`，
**不碰真正的 index、不建 commit、不動 stash**。）

commit message 草稿先留在這裡，等產品負責人決定要不要用：

```text
feat: Phase 81 雲端路 PDF——_store_cloud_result 依 content_type 分流（單圖／PDF）、
新增 _store_pdf_result 與 _store_pdf_page（本機自己 render_pages 拿每頁 PNG、依 page 欄位
與工人結果配對、跳頁與 pages_done 續跑與 0 頁失敗三條規則沿用本機路）、假工人支援 PDF；
順帶 render_pages(max_pages=) 讓隱私閘門只渲染第一頁，+9 tests；階段甲全部完成，下一步是 ★G1
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
   run_gated_ingest_job → route == "cloud" → _resume_cloud_route
        │
        ├ latest_job = store.get(job_id) or job   ← 落庫前重讀（D17 最後一道保險）
        ▼
   fetch_result（直接去 S3 拿，**不重送**）→ 有！
        │
        ▼
   _store_cloud_result → content_type 是 application/pdf → _store_pdf_result
        ├ 本機 render_pages() → 5 張 PNG
        ├ pages_done = job["pages_done"] = 2
        └ for 迴圈從 page_images[2:] 開始，頁碼從 3 起算
             → 第 1、2 頁**不重看、不重插**（它們的 id 還在 photo_ids 裡）
```

---

## 6. 驗收清單

- [x] **開工基線已實查**：`pytest -q` 記下顆數（2026-09-02 實查 **613**）

- [x] **開工快照已記下**：`.superpowers/sdd/phase0902/snapshot-tree` 的輸出（步驟 6 要用它相減）

- [x] **三支新函式都在，而且原本的單圖本體只是改名**

  ```bash
  grep -nE "^def _store_cloud_result|^def _store_image_result|^def _store_pdf_result|^def _store_pdf_page" \
    app/services/gated_ingest.py
  ```

  預期：4 行命中，而且**順序就是這四個**（分流器在最前面）

- [x] **PDF 的三條規則都用既有常數，沒有自己發明新訊息**

  ```bash
  grep -nE "ingest_job\.(ERROR_PDF_UNREADABLE|ERROR_PDF_ALL_PAGES_FAILED|PDF_PAGE_CONTENT_TYPE)" \
    app/services/gated_ingest.py
  grep -nE "^(ERROR_PDF_UNREADABLE|ERROR_PDF_ALL_PAGES_FAILED|PDF_PAGE_CONTENT_TYPE) *=" \
    app/services/gated_ingest.py || echo "OK：本檔沒有重新定義這三個常數"
  ```

  預期：第一句 **4 行命中**（`ERROR_PDF_UNREADABLE` 兩處、`ERROR_PDF_ALL_PAGES_FAILED` 一處、
  `PDF_PAGE_CONTENT_TYPE` 一處；`_store_pdf_result()` 的 docstring 也提到常數名，但它前面沒有
  `ingest_job.`，所以不會被這一句算進去）；第二句印 `OK：本檔沒有重新定義這三個常數`

- [x] **單圖分支「先寫收據」那一行還在，而且在清 S3 之前（總覽 §10.2 R）**

  ```bash
  grep -nA5 "store.update(job_id, photo_ids=\[photo_id\])" app/services/gated_ingest.py
  ```

  預期：命中恰 1 處（在 `_store_image_result()` 裡；PDF 那一支寫的是
  `pages_done=page_number, photo_ids=list(photo_ids)`，字串不同不會被算進去），
  而且緊接的那 5 行裡依序出現 `_best_effort_cloud_cleanup(cloud, job_id)` 與
  `ingest_job.finish_image_job(...)`——先寫收據、再清 S3、最後收尾

- [x] **80 的三處實作裁決都還在**（校準 R2：確認沒有被舊版整檔碼洗掉）

  ```bash
  grep -n "latest_job = store.get(job_id) or job" app/services/gated_ingest.py
  grep -n "當作逾時" app/services/gated_ingest.py
  grep -n "多餘鍵會被忽略" app/services/gated_ingest.py
  ```

  預期：三句各 **1 行命中**（依序是 `_resume_cloud_route()` 的重讀行、`wait_result` 的
  R14 try/except、`_parse_understanding()` 的定稿措辭）

- [x] **`ingest_job.py` 一個字都沒改**

  ⚠ **不能用 `git diff --stat app/services/ingest_job.py`**：工作樹裡 74〜80 的改動全都還沒
  commit（產品負責人指示不 commit），拿 HEAD 比一定有輸出。要拿**本 phase 的兩個快照**相減：

  ```bash
  git diff --stat <開工SHA> <收工SHA> -- app/services/ingest_job.py
  ```

  預期：沒有輸出（兩個 SHA 來自步驟 6 的 `snapshot-tree`）

- [x] **本機路的 PDF 沒有被影響**

  ```bash
  pytest tests/integration/test_ingest_job_pdf.py -q
  ```

  預期：`9 passed`

- [x] **新測試 9 顆全綠**（核心 7 ＋ 2026-09-02 fix wave R11 補的 2 顆守門測試）

  ```bash
  pytest tests/integration/test_gated_ingest_pdf.py -v
  ```

  預期：`9 passed`

- [x] **PDF 成功時也留下「完成」那一行 log**（與單圖同一個前綴，Phase 88／92 靠 grep 它）

  ```bash
  pytest tests/integration/test_gated_ingest_pdf.py -k 兩頁都成功 \
         -o log_cli=true -o log_cli_level=INFO -q 2>&1 | grep 雲端結果已入庫
  ```

  預期：一行含 `雲端結果已入庫：2 頁中 2 頁成功`
  （之後在真機上是 `docker compose logs worker | grep 雲端結果已入庫`）

- [x] **R4：`max_pages` 的兩顆全綠**

  ```bash
  pytest tests/unit/test_pdf_service_unit.py::test_max_pages只渲染前幾頁 \
         tests/unit/test_privacy_gate_unit.py::test_PDF閘門只渲染第一頁 -q
  ```

  預期：`2 passed`

- [x] **R4：閘門真的只要第一頁，而且本機路仍然要整份**

  ```bash
  grep -n "max_pages=1" app/services/privacy_gate.py
  grep -rn "max_pages" app/services/ingest_job.py || echo "OK：本機路沒有用 max_pages（整份渲染）"
  ```

  預期：第一句 **恰 1 行**；第二句印 `OK：本機路沒有用 max_pages（整份渲染）`

- [x] **全量 pytest 顆數 ＝ 開工基線 613 ＋ 11**（核心 7 ＋ R4 2 ＋ fix wave R11 2）

  ```bash
  pytest -q
  ```

  預期：`624 passed`、**0 skipped**

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

  預期：`624 passed`

- [x] **`app/` 全樹仍然零 boto3**（★G1 的前提之一：甲全程沒碰過 AWS）

  ```bash
  grep -rnE "^\s*(import|from)\s+boto3" app/ tests/ scripts/ requirements.txt || echo "OK：整個專案還沒有 boto3"
  ```

  預期：印 `OK：整個專案還沒有 boto3`（只抓 **import**：`config.py`／`cloud_ingest.py`／`gated_ingest.py` 的註解本來就提到 boto3 這個字，`grep -rn boto3` 一定會命中——2026-09-02 實作時發現，controller 已改指令）

- [x] **專案的 `data/` 沒被弄髒**

  ```bash
  git status --short data/ ; find data/staging -type f | head
  ```

  預期：兩行都沒有輸出

- [x] **收工快照與改動範圍**：再跑一次 `.superpowers/sdd/phase0902/snapshot-tree`，
  然後 `git diff --stat <開工SHA> <收工SHA>`——變更項應**恰為本 phase 的 7 個檔**：

  ```text
  app/services/gated_ingest.py            分流器＋兩支 PDF 函式（4-1〜4-6）
  app/services/pdf_service.py             R4：render_pages(..., max_pages=None)
  app/services/privacy_gate.py            R4：閘門 PDF 分支改 max_pages=1
  tests/fakes.py                          假工人支援 PDF
  tests/integration/test_gated_ingest_pdf.py   新檔，7 顆
  tests/unit/test_pdf_service_unit.py     +1 顆（R4）
  tests/unit/test_privacy_gate_unit.py    +1 顆（R4）
  ```

  **不 commit**（裁決 R5）：`git add`／`git commit`／`git stash` 一律不做。

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
   **不要**為此在 `_store_pdf_result()` 多接一個 `except FileNotFoundError`——本機路的
   `_run_pdf_job` 也是同樣讓它炸出來，兩邊要一致（本 phase 的原則就是三條規則逐字相同）。

9. **忘了在 `tests/fakes.py` 補 `from app.services import pdf_service`。**
   症狀：`fake_worker_process_one` 拆頁時 `NameError: name 'pdf_service' is not defined`
   （`_fake_worker_read_pdf` 用到 `pdf_service.render_pages()`／`pdf_service.PdfUnreadableError`）。
   它是新的**一行**、放在 `from app.core import config` 之後即可（步驟 1 有貼改完的樣子）；
   `fakes.py` 沒有括號式的 `from app.services import (…)` 區塊，不要去找。

10. **把單圖分支的 `store.update(job_id, photo_ids=[photo_id])` 挪到 `cleanup()` 之後
    （或省掉，反正 `finish_image_job` 也會寫）。**
    `cleanup()` 是 S3 網路呼叫（boto3 自己會重試，可拖數十秒）。這段期間 worker 被殺 →
    佇列重送同一個 job_id → `result.json` 已被刪 → fallback 本機 → `run_ingest_job` 看不到
    `photo_ids` → **再 INSERT 一張**（違反 design6 D17）。收據一定要在 INSERT 成功的**下一行**
    就寫（總覽 §10.2 R）。PDF 分支不必另外加：迴圈裡每頁那一次
    `store.update(pages_done=, photo_ids=)` 本來就在整份 `cleanup()` 之前。

11. **（R2）照本檔舊版的「整檔覆蓋」貼 `gated_ingest.py`。**
    本檔成稿於 2026-08-31，那份重貼碼比工作樹實檔**少三樣東西**：`_resume_cloud_route()` 的
    重讀行 `latest_job = store.get(job_id) or job`、`wait_result` 外面的 R14 try/except、
    以及 `_store_cloud_result(...)` 呼叫前那 7 行註解。三樣裡只有一樣**會被 pytest 抓到**
    （`test_gated_ingest.py::test_等結果時信箱丟例外_fallback本機而且清乾淨` 會紅）；
    另外兩樣**全綠通過**——重讀行防的是 `--concurrency=2` 的並行窗口，單執行緒測試分不出來
    （那顆測試的 docstring 自己寫了這件事），註解更是沒有測試在守。
    也就是說：貼錯了會**看起來像成功**，卻默默把 80 的兩處裁決退回。
    步驟 4 已改成編輯清單，照它做即可；§6 另有一條專門的 grep 在守這三樣東西。

12. **（R4）把 `max_pages` 寫成位置參數，或順手改掉 `ingest_job.py` 的呼叫。**
    它是 **keyword-only**（`*` 後面）而且預設 `None`，就是為了讓既有兩個呼叫端一個字都不必改；
    寫成位置參數的話 `render_pages(pdf_bytes, 2.0)` 這種呼叫會突然變成「只渲染 2 頁」。
    本機路要的是**整份**，`ingest_job.py` 那一行不要動——那正是向下相容的證據。

---

## 8. 完成後的專案狀態

**階段甲（Phase 74〜81）全部完成。** 雲端路在假信箱上已經整條跑得通：

- 閘門三分類 ＋「不確定＝本機」（74／75／78）
- 四種「遠端不可用」都會 fallback，而且 log 有契約字樣（78／79／80）
- 單圖與 PDF 的雲端成功路（79／81）、逾時與冪等（80）

**對外行為仍然零改變**：`CLOUD_ROUTE` 預設 `off`、端點仍 **22**、`photo` 表零改動、
前端零改動、`requirements.txt` **還沒有 boto3**。
整個階段甲**一行 AWS 指令都沒有打過**（design6 §0 禁止第 1 條）。

測試累計 ＝ **開工基線 613 ＋ 11 ＝ 624**（0 skipped）。端點 **22**（不變）。
拆法：**Phase 81 核心 +7**（`test_gated_ingest_pdf.py` 新檔）、
**2026-09-02 fix wave R11 +2**（同一個新檔的兩顆守門測試，見 §8.1）、
**裁決 R4 `max_pages` +2**（`test_pdf_service_unit.py`／`test_privacy_gate_unit.py` 各一顆）。
總覽 §9 與 §2.7 的舊數字 609／616 是 Phase 80 當時的估值，2026-09-02 已一併校準
（總覽 P81 那一段有註記）。

**本 phase 不 commit**（裁決 R5）：改動留在工作樹，靠步驟 6 的兩個 tree 快照相減驗收；
歸檔（`unfinish/` → `finish/`）之後隨 commit 由產品負責人做。

**不需要手動／真機測試**（裁決 R7）：本 phase 零前端、零無線鏡頭改動、★G1 前零 AWS；
真模型煙霧也不做——PDF 的雲端路在 ★G1 之前只能靠 `FakeMailbox` 演。

---

## 8.1 實作紀錄（2026-09-02，實作者）

全程 TDD、照步驟 1〜6 走完，計畫檔的碼**逐字沿用**（測試檔與四支函式都是從本檔的
程式碼區塊直接取出來寫進實檔的，沒有重打）。與計畫檔零差異。

| 項目 | 結果 |
|---|---|
| 步驟 1b RED | `2 failed`＝`TypeError: render_pages() got an unexpected keyword argument 'max_pages'` ＋ `AssertionError: assert None == 1`（與計畫檔預測逐字相同） |
| 步驟 1b GREEN | `2 passed`；向下相容那一句（四個檔）`43 passed` |
| 步驟 3 RED | `6 failed, 1 passed`——紅的典型訊息就是計畫檔寫的 `assert 0 == 2 where 0 = count_photos()`（PDF 走了單圖落庫段）；`test_PDF判定敏感時零submit走本機` 因為走本機路，改動前就已經是綠的 |
| 步驟 5 GREEN | `test_gated_ingest_pdf.py` **7 passed**（fix wave R11 之後 9 passed）；`test_ingest_job_pdf.py` **9 passed**；兩個單元檔 **27 passed** |
| 全量 | **624 passed、0 skipped**（＝開工基線 613 ＋ 11）；三死埠一起指也是 **624 passed** |
| ruff | `105 files left unchanged` ＋ `All checks passed!` |
| 工作樹快照 | 開工 `dc4b5839d714fd2234023fab5bece5f446de96b0`、收工 `a0a1e624ca09cb2a95bec46e601c052f040e031c`（fix wave R11 後 `5a709f0ffc2ce3292b2a86a382a7f1a6ac916c40`，只多測試檔）；兩者相減恰為 §6 列的 7 個檔（另有一份校準期的 REP.md，非本 task 產出）。`ingest_job.py` 兩快照相減**無輸出** |
| 不 commit | 遵守裁決 R5：全程沒有 `git add`／`commit`／`stash`／`mv` |

### 2026-09-02 fix wave R11（review Approved／0 Critical／0 Important，兩條 Minor 由 controller 判定要補）

**只加測試，產品碼一個字都沒動。** 在 `tests/integration/test_gated_ingest_pdf.py` 檔尾補 2 顆守門測試
（檔內另加兩個常數 `PAGE1_UNDERSTANDING`／`PAGE2_UNDERSTANDING`、一個 helper `original_bytes()`、
兩個假信箱 `ReversedWorkerMailbox`／`PartialWorkerMailbox`；`tests/fakes.py` 沒有動）：

| 測試 | 守的是什麼 |
|---|---|
| `test_工人回的pages反序_仍依page欄位配對` | §7 陷阱 1：配對用 `page` 欄位、不是陣列位置。原本 7 顆分不出這件事（假工人一律照順序產生 `pages`） |
| `test_工人只回第二頁_第一頁跳過且原圖是第二頁` | 兩條原本零覆蓋的分支：`_store_pdf_result` 的「頁數對不上」warning、`_store_pdf_page` 的 `page_result is None` → 跳過 |

**變異證據**（證明這兩顆真的會咬）：把 `gated_ingest.py` 的 `page_results.get(page_number)` 暫改成
`pages[page_number - 1]` → **恰好這 2 顆紅、原本 7 顆全綠**
（`2 failed, 7 passed`；紅在 `AssertionError: 第一頁的文字要配第一頁的圖`＝原圖位元組配錯頁）。改回來後 9 passed。

顆數：**622 → 624**（0 skipped）；三死埠一起指也是 624。

⚠ §6 的「`app/` 全樹仍然零 boto3」那一句實跑時**不會**印出 `OK：整個專案還沒有 boto3`——
`config.py`／`cloud_ingest.py`／`gated_ingest.py` 的**註解**裡本來就提到 boto3 這個字（Phase 77／79 就有），
所以 `grep -rn boto3` 一定有命中。真正要驗的是「有沒有 import」：
`grep -rnE "^\s*(import|from)\s+boto3" app/ tests/ scripts/` → 零命中，`requirements.txt` 也沒有 boto3。


### ★ 下一步是閘門 G1（人的動作，實作者不可以自己勾掉）

> 🚦 **★G1 就在本 phase 之後、Phase 82 之前。**
> 下表逐字抄自總覽 §4。**沒有產品負責人明確點頭，一行 AWS 指令都不准打。**

| 項目 | 內容 |
|---|---|
| 是什麼 | 「閘門與 fallback 做完了、產品負責人親眼看過，可以開 AWS 帳號了」的一句話 |
| 誰確認 | **產品負責人（人）** |
| 憑什麼確認 | design6 §0 甲那列三條：① 敏感／不確定**零 S3 呼叫** ② 假遠端關閉時非敏感也走 `run_ingest_job` ③ pytest 不連 AWS。逐條指令見總覽 **§5.1** |
| 沒過會怎樣 | **Phase 82 起全部停擺，一行 AWS 指令都不准打**（design6 §0 禁止第 1 條）。不能「先開個帳號放著」——開戶就開始算 Free plan 的 6 個月 |
| 卡住時怎麼辦 | 若是測試沒過 → 回 74〜81 對應的 phase 修。若是產品負責人對「短問題把什麼當敏感」有意見 → 回 **Phase 75** 改 `PRIVACY_PROMPT`（那是給 VLM 的短指令，不是檔名表）。**不要**用「先開 S3 試試看」繞過——甲全部是本機的事，修起來很快 |

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
pytest -q                                    # 預期：624 passed
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
