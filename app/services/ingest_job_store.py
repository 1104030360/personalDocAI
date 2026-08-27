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
    status: str  # JOB_STATUSES 之一
    attempt: int  # 這張／這頁目前第幾次 VLM，1〜3（剛建立時是 0 ＝還沒送過）
    page_count: int | None  # PDF 拆頁後才知道幾頁；圖片永遠是 None
    pages_done: int  # PDF 已處理頁數（含跳過的失敗頁）；崩潰重送靠它續跑
    photo_ids: list[int]  # 已經 INSERT 的照片 id；崩潰重送靠它避免插兩次
    error: str | None  # 失敗時給人看的**短句**，不要把 stack trace 丟給瀏覽器
    ai_backend: str  # 入列當下 config.AI_BACKEND 的快照："local" / "cloud"（D14）
    source: str  # "upload"（電腦選檔）/ "camera"（無線鏡頭快門）


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

    def create(
        self, *, job_id: str, filename: str, content_type: str, ai_backend: str, source: str
    ) -> IngestJob: ...

    def get(self, job_id: str) -> IngestJob | None: ...

    def update(self, job_id: str, **fields) -> IngestJob | None: ...

    def delete(self, job_id: str) -> None: ...

    def list_open(self) -> list[IngestJob]: ...  # 不含成功（成功＝已 delete）


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
            "attempt": 0,  # 0 ＝還沒送過 VLM；第一次送出時才變 1
            "page_count": None,  # PDF 拆頁後才填，圖片永遠是 None
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
        return [_copy(job) for job in self._jobs.values() if job.get("status") in JOB_STATUSES]

    # ---------- 以下是**測試專用**，不屬於 JobStore 契約 ----------

    def clear(self) -> None:
        """清空全部 job。只給 tests/conftest.py 的安全網用。

        Protocol 是結構型別，多幾個方法完全沒關係（RedisJobStore 不會有這一支）。
        刻意不放進 JobStore 契約：正式程式碼沒有任何地方該有「一次清光」的能力。
        """
        self._jobs.clear()


# ---------- Phase 65 追加：正式用的 Redis 實作 ----------

import json  # noqa: E402  （搬去檔頭 import 區也行；寫在這裡是讓整段可以一刀貼上）

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
