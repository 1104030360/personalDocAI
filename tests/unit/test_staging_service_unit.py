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
    staging_service.remove_staging("job-1", "image/png")  # 第二次
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
