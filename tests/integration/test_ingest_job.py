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
from datetime import date, datetime

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

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)

    # 照片真的進去了，而且掛在收件箱（design5 §4.2：落點與現在相同）
    assert photo_repository.count_photos() == 1
    photos = photo_repository.list_photos_in_folder(收件箱id())
    assert len(photos) == 1
    row = photo_repository.fetch_photo(photos[0]["id"])
    assert row["text"] == 收據理解.text
    assert row["category"] == "未分類"  # 一律先進收件箱，建議不落庫成歸屬
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

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)

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

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)

    assert vlm.calls == 3
    assert photo_repository.count_photos() == 0
    assert store.get(job_id)["status"] == "failed"


def test_空白描述也算看不懂():
    """understood=True 但 text 全是空白 → 沿用 _ingest_image 的判準，算失敗。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([空白描述, 空白描述, 空白描述])

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)

    assert vlm.calls == 3
    assert photo_repository.count_photos() == 0
    assert store.get(job_id)["status"] == "failed"


# ---------------------------- ③ 第三次才成功 ----------------------------


def test_第三次才成功_照樣只入庫一列():
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    vlm = ScriptedVLM([看不懂, RuntimeError("Ollama 沒開"), 收據理解])

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)

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

    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=壞掉的Embeddings(), now=NOW)

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
    第二次的vlm = ScriptedVLM([])  # 劇本是空的：只要被呼叫一次就 AssertionError

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
        "沒有這筆",
        store=store,
        vlm=FakeVLM(收據理解),
        embeddings=FakeEmbeddings(),
        now=NOW,
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


# ---------------------------- ⑧ 建議落庫（Phase 61 / design5.md D16）----------------------------
#
# 三個新欄位存的都是「AI 當下猜了什麼」，不是「照片屬於什麼」。
# 照片的實際歸屬永遠是收件箱；實體與待辦要等人在待決定的彈窗按下去才會落庫。


def 帶建議的理解(*, entity=None, task_title=None, task_due=None) -> PhotoUnderstanding:
    """一份「看得懂」的理解結果，三個建議欄位可以個別指定。"""
    return PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
        entity=entity,
        task_title=task_title,
        task_due=task_due,
    )


def 跑一次並取回那一列(vlm) -> dict:
    """建 job → 跑任務 → 把入庫的那一列撈回來。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    ingest_job.run_ingest_job(job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW)
    assert photo_repository.count_photos() == 1
    photo_id = photo_repository.list_photos_in_folder(收件箱id())[0]["id"]
    return photo_repository.fetch_photo(photo_id)


def test_實體建議在清單內_落庫成清單上的名稱():
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    # 刻意用不同大小寫與多餘空白：clamp_entity 要夾回**清單上的原文**。
    # 注意整個名稱都要在（clamp 是逐字 casefold 比對、不是模糊比對）：
    # 寫成 "my macbook" 會因為少了「我的」而對不上、退成 None，測試就紅錯地方。
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="  我的 macbook  ")))

    assert row["suggested_entity"] == "我的 MacBook"


def test_實體建議在清單外_落庫NULL():
    """實體沒有「未分類」這種保底：清單上沒有的名字一律不落庫（design3 D12）。"""
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="鄰居的貓")))

    assert row["suggested_entity"] is None


def test_實體清單是空的時候也落庫NULL():
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="任何名字")))

    assert row["suggested_entity"] is None


def test_待辦建議完整_標題與到期日都落庫():
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(task_title="繳交作業三", task_due="2026-08-21")))

    assert row["suggested_task_title"] == "繳交作業三"
    assert row["suggested_task_due"] == date(2026, 8, 21)


def test_待辦建議只有標題沒有到期日_標題落庫日期NULL():
    """日期推不出來只是少一個日期，不可以害整張照片入不了庫（與 content_time 同一原則）。"""
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(task_title=" 繳電費 ", task_due="下週三")))

    assert row["suggested_task_title"] == "繳電費", "前後空白要去掉"
    assert row["suggested_task_due"] is None
    assert photo_repository.count_photos() == 1, "日期看不懂不影響入庫"


def test_照片沒有待辦_標題與日期兩欄都是NULL():
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(task_title="   ")))

    assert row["suggested_task_title"] is None
    assert row["suggested_task_due"] is None


def test_worker不會自己建實體_不會自己釘選_也不會自己建待辦():
    """design5.md §4.2：建議永遠只是建議，人按確認才寫那三張表。"""
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    row = 跑一次並取回那一列(
        FakeVLM(帶建議的理解(entity="我的 MacBook", task_title="繳交作業三", task_due="2026-08-21"))
    )
    photo_id = row["id"]

    # 建議都寫進 photo 那一列了……
    assert row["suggested_entity"] == "我的 MacBook"
    assert row["suggested_task_title"] == "繳交作業三"
    # ……但三張「人確認才寫」的表一列都不能多
    assert photo_repository.list_entities() == [
        {"id": 1, "name": "我的 MacBook", "description": "工作用筆電"}
    ], "worker 不可以自己建新實體"
    assert photo_repository.list_photo_entities(photo_id) == [], "worker 不可以自己釘"
    assert photo_repository.get_task_by_photo(photo_id) is None, "worker 不可以自己建待辦"
