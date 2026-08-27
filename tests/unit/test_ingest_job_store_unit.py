"""InMemoryJobStore 的單元測試：純記憶體，不碰資料庫、不碰網路、不碰 Redis。

design5.md §4.3：清單只回 queued／analyzing／retrying／failed 四種狀態，
**成功＝把這筆 job 刪掉**，所以 store 裡根本不存在「成功」這種狀態。
"""

from __future__ import annotations

import json

from app import dependencies
from app.dependencies import get_job_store
from app.main import app
from app.services import ingest_job_store
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
    assert job["attempt"] == 0  # 還沒送過 VLM
    assert job["pages_done"] == 0
    assert job["photo_ids"] == []  # 還沒有任何照片入庫
    assert job["page_count"] is None  # PDF 拆頁後才知道幾頁；圖片永遠是 None
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
        job_id=job_id,
        filename=f"{job_id}.png",
        content_type=content_type,
        ai_backend="local",
        source="upload",
    )
    return client, store


def test_create把job寫成JSON並登記進open集合():
    client = FakeRedisClient()
    store = ingest_job_store.RedisJobStore(client)
    job = store.create(
        job_id="j1",
        filename="收據.jpg",
        content_type="image/jpeg",
        ai_backend="cloud",
        source="upload",
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
    assert 改完["filename"] == "j1.png"  # 沒動到的還在
    assert store.get("j1")["status"] == "analyzing"  # 真的寫回去了


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
            job_id=job_id,
            filename=f"{job_id}.png",
            content_type="image/png",
            ai_backend="local",
            source="upload",
        )
    store.delete("j2")  # 成功＝delete（design5 §4.3）
    assert [job["job_id"] for job in store.list_open()] == ["j1", "j3"]


def test_list_open遇到集合有id但資料不見時自己修好():
    """AOF 半截、或有人手動 DEL 掉某把 key 時，集合裡會留下孤兒 id。

    list_open() 要跳過它、順手 SREM 掉，不可以炸掉整個進度面板。
    """
    client, store = _建一個store()
    client.sadd("ingest:open", "孤兒")  # 只有集合有，沒有對應 JSON
    assert [job["job_id"] for job in store.list_open()] == ["j1"]
    assert client.smembers("ingest:open") == {"j1"}


def test_list_open沒有任何job時回空清單():
    store = ingest_job_store.RedisJobStore(FakeRedisClient())
    assert store.list_open() == []
