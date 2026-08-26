"""上傳存檔與讀圖端點的整合測試（design1.md §6、§7.4、§12）。

檔案一律寫在 conftest 的 isolated_data_dir 指定的暫存目錄，不會碰到專案的 data/。

2026-08-25（Phase 62）起上傳改回 **202**：HTTP 只把位元組收進 data/staging/，
真正寫 data/photos 與 data/thumbs 的是 worker（app/services/ingest_job.py 的
run_ingest_job）。所以本檔一律「POST 拿 202 → 測試自己扮演 worker 把任務跑完
→ 驗資料庫那一列與磁碟上的檔案」。原本「寫檔失敗回 500」的兩顆也跟著搬到
worker 那一側：HTTP 仍然是 202，失敗表現成 job 標 failed（design5.md §8 第 7 列），
但「不留半筆資料、不留孤兒檔案」這條一字未變。
"""

from __future__ import annotations

import io

from PIL import Image

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import staging_service, storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片, 目前的任務清單, 跑完任務
from tests.fakes import FakeEmbeddings, FakeVLM, make_jpeg_bytes, make_png_bytes

TARGET_RECEIPT = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據", location="Target",
    items=["可樂", "洋芋片"], content_time="2026-08-10",
)


def _upload(client, payload=None, content_type="image/png", filename="a.png"):
    """上傳一張看得懂的照片（202 → 測試扮演 worker 跑完任務），回資料庫那一列。

    payload 預設是 Pillow 現產的真 PNG。
    回的鍵是 photo 表的欄位（不再是 201 回應），所以路徑三欄直接讀 列["original_path"]
    之類的就好，不必再 fetch_photo 一次。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)
    if payload is None:
        payload = make_png_bytes(1200, 600)
    return 上傳一張並取回照片(
        client, payload=payload, filename=filename, content_type=content_type
    )


def test_上傳後原圖與縮圖都寫進DATA_DIR(client):
    image_bytes = make_png_bytes(1200, 600)

    列 = _upload(client, payload=image_bytes)

    photo_id = 列["id"]
    # 資料庫存的是以 data/ 開頭的相對路徑（design1.md §6）
    assert 列["original_path"] == f"data/photos/{photo_id}.png"
    assert 列["thumbnail_path"] == f"data/thumbs/{photo_id}.png"
    assert 列["content_type"] == "image/png"
    # 檔案真的在（換算後的實際位置在暫存目錄底下）
    原圖 = storage_service.absolute_path(列["original_path"])
    縮圖 = storage_service.absolute_path(列["thumbnail_path"])
    assert 原圖.is_file() and 縮圖.is_file()
    # 原圖位元組與上傳的一模一樣（走過 staging 一趟也不能少一個位元）；
    # 縮圖被縮到長邊 512
    assert 原圖.read_bytes() == image_bytes
    with Image.open(io.BytesIO(縮圖.read_bytes())) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_jpeg上傳的副檔名是jpg(client):
    列 = _upload(
        client, payload=make_jpeg_bytes(), content_type="image/jpeg", filename="a.jpg"
    )

    assert 列["original_path"].endswith(".jpg")
    assert 列["thumbnail_path"].endswith(".jpg")
    assert 列["content_type"] == "image/jpeg"


def test_讀縮圖端點回200且回的真的是圖片(client):
    photo_id = _upload(client)["id"]

    response = client.get(f"/photos/{photo_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (512, 256)


def test_讀原圖端點回的位元組與上傳的完全相同(client):
    image_bytes = make_png_bytes(1200, 600)
    photo_id = _upload(client, payload=image_bytes)["id"]

    response = client.get(f"/photos/{photo_id}/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == image_bytes


def test_照片不存在讀圖回404(client):
    assert client.get("/photos/9999/thumbnail").status_code == 404
    assert client.get("/photos/9999/image").status_code == 404


def test_舊式資料沒有路徑讀圖回404(client):
    """design1.md §10：遷移進來的舊照片路徑是 NULL，讀圖 404，前端顯示占位。

    這裡直接用 repository 插一列（不走上傳端點），模擬遷移後的舊資料。
    """
    photo_id = photo_repository.insert_photo(
        text="遷移進來的舊照片", category="收據", location="Target",
        items=["可樂"], content_time=None,
        embedding=FakeEmbeddings().embed_query("收據"),
    )["id"]

    row = photo_repository.fetch_photo(photo_id)
    assert row["original_path"] is None
    assert row["thumbnail_path"] is None
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    assert client.get(f"/photos/{photo_id}/image").status_code == 404


def test_檔案被刪掉後讀圖也回404(client):
    列 = _upload(client)
    photo_id = 列["id"]
    storage_service.absolute_path(列["thumbnail_path"]).unlink()

    # 資料庫有路徑、磁碟沒檔案 → 一樣 404，不可以回 500
    assert client.get(f"/photos/{photo_id}/thumbnail").status_code == 404
    # 原圖還在，所以原圖端點仍然 200
    assert client.get(f"/photos/{photo_id}/image").status_code == 200


def test_寫檔失敗時檔案與資料列都不留(client, monkeypatch):
    """寫檔失敗現在發生在 **worker 裡**，不是 HTTP 裡（design5.md §8 第 7 列）。

    所以：
      - HTTP 一定是 202（它只把檔案放進 staging，還沒開始寫 photos/）
      - 「不留半筆資料、不留孤兒檔案」這條**一字未變**，只是改在跑完任務之後驗
      - 不再需要 不擲出例外的client：例外由 run_ingest_job 內部收掉，
        最後表現成 job=failed（3 次重試都失敗）

    ⚠ monkeypatch 一定要在 POST **之前**掛好也可以、在跑任務之前掛好也可以，
      但**不可以**在跑任務之後才掛——那時候檔案早就寫完了。
    """
    def 一定失敗(photo_id, image_bytes, content_type):
        raise RuntimeError("磁碟壞了")

    monkeypatch.setattr(storage_service, "make_thumbnail", 一定失敗)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(1200, 600), "image/png")}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0, "失敗時不可以留下半筆資料"
    # 縮圖之前已經寫出去的原圖也要被清掉
    assert not list((config.DATA_DIR / "photos").glob("*")), "不可以留下孤兒檔案"
    # staging 也要清乾淨（最終失敗＝整筆拿掉，design5.md D10）
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_更新路徑失敗時檔案與資料列都不留(client, monkeypatch):
    """最後一步（UPDATE）失敗也要清乾淨——兩個檔案都已經寫出去了。

    與上一顆同一個手法：HTTP 202，失敗是 worker 那一側的結局（job=failed）。
    """
    def 一定失敗(photo_id, **kwargs):
        raise RuntimeError("資料庫斷線")

    monkeypatch.setattr(photo_repository, "update_photo_paths", 一定失敗)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(1200, 600), "image/png")}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0
    assert not list((config.DATA_DIR / "photos").glob("*"))
    assert not list((config.DATA_DIR / "thumbs").glob("*"))
    assert not staging_service.staging_path(job_id, "image/png").exists()


def test_415完全不寫檔(client):
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415
    # 連 data/ 這個資料夾都不該被建出來
    assert not config.DATA_DIR.exists()


def test_看不懂的照片最後什麼檔案都不留(client):
    """名字從「422完全不寫檔」改掉：HTTP 已經沒有 422 了（那是 worker 的結局）。

    ⚠ 這一顆原本斷言 `not config.DATA_DIR.exists()`，改寫後**不能再這樣寫**——
      staging 在 202 當下就把 data/staging/ 建出來了。改成「裡面沒有任何檔案」。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 202, response.text

    跑完任務(response.json()["job_id"])

    assert photo_repository.count_photos() == 0
    留下的檔案 = [p for p in config.DATA_DIR.rglob("*") if p.is_file()]
    assert 留下的檔案 == [], f"最終失敗不可以留下任何檔案：{留下的檔案}"
