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
