"""POST /photos 格式檢查的整合測試（TestClient，in-process 不經網路）。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U1「上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗」
  Example「非圖片格式的檔案上傳失敗」：
    When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗 And 系統儲存的照片數量為 0
"""

import base64

from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import get_task_dispatcher, get_vlm
from app.main import app
from app.repositories import photo_repository as repo
from app.services import staging_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳並跑完任務, 目前的任務清單
from tests.fakes import FakeVLM, make_jpeg_bytes

client = TestClient(app)

# 一張合法的 1×1 PNG（與步驟 3 的 /tmp/sample.png 相同內容，70 bytes）
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

看得懂的收據 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


def test_upload_non_image_returns_415_with_message():
    # When 使用者上傳一個非圖片格式的檔案 → Then 操作失敗（415＋規格訊息）
    resp = client.post(
        # 計畫原文寫 b"這不是圖片"，但 Python 的 bytes literal 只允許 ASCII，
        # 會 SyntaxError；改用 .encode() 產生同樣的 UTF-8 位元組，語意不變。
        "/photos",
        files={"file": ("not_image.txt", "這不是圖片".encode(), "text/plain")},
    )
    assert resp.status_code == 415
    assert resp.json() == {"detail": "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"}


def test_upload_non_image_stores_nothing():
    # And 系統儲存的照片數量為 0（U1 第二句：不進行任何後續處理）
    client.post("/photos", files={"file": ("not_image.txt", b"x", "text/plain")})
    assert repo.count_photos() == 0


def test_upload_octet_stream_returns_415():
    # content_type 不在允許清單（未知二進位型別）也一律 415
    resp = client.post(
        "/photos",
        files={"file": ("mystery.bin", b"\x00\x01", "application/octet-stream")},
    )
    assert resp.status_code == 415


# ---------------- 受理：202 ＋ 一張號碼牌 ----------------


def test_上傳PNG受理回202且只回三個欄位():
    """202 ＝「收下了」，不是「存好了」。回應裡沒有照片內容（design5.md D7）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)

    resp = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")})

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert set(body) == {"job_id", "filename", "content_type"}
    assert body["filename"] == "sample.png"
    assert body["content_type"] == "image/png"
    # uuid4().hex ＝ 32 個十六進位字元（沒有連字號）
    assert len(body["job_id"]) == 32


def test_上傳JPEG也受理回202():
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)

    resp = client.post("/photos", files={"file": ("sample.jpg", make_jpeg_bytes(), "image/jpeg")})

    assert resp.status_code == 202, resp.text
    assert resp.json()["content_type"] == "image/jpeg"


def test_202當下資料庫還沒有那一列():
    """★ 增量五新釘的一條（design5.md §9 第 2 步、§4.2）。

    這是整個增量五最重要的一顆測試：它守的是「HTTP 很快」這件事的**證據**。
    有人若把 VLM 又搬回請求裡（例如「反正 eager 比較好測」），這顆會立刻紅。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)

    resp = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")})

    assert resp.status_code == 202, resp.text
    assert repo.count_photos() == 0


def test_202當下staging檔在而任務是queued():
    """三件事都要做到：檔案落地、任務記下來、AI 開關快照存好（design5.md D14）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)

    job_id = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")}).json()[
        "job_id"
    ]

    assert staging_service.staging_path(job_id, "image/png").is_file()
    job = 目前的任務清單().get(job_id)
    assert job["status"] == "queued"
    assert job["filename"] == "sample.png"
    assert job["content_type"] == "image/png"
    assert job["source"] == "upload"
    assert job["ai_backend"] == "local"  # 入列當下的快照，不是 worker 跑的時候才讀


def test_跑完任務之後照片才進收件箱():
    """design5.md §9 的四步樣板：POST → 列數 0 → 跑任務 → 原本的 Then。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)

    結果 = 上傳並跑完任務(client, payload=PNG_BYTES)

    assert repo.count_photos() == 1
    assert len(結果["photo_ids"]) == 1
    row = repo.fetch_photo(結果["photo_ids"][0])
    assert row["text"] == 看得懂的收據.text
    # 成功＝job 被刪掉（契約備忘 §3.1），所以清單裡查不到它了
    assert 結果["job"] is None
    assert 目前的任務清單().list_open() == []
    # staging 用完就刪
    assert not staging_service.staging_path(結果["job_id"], "image/png").exists()


# ---------------- 入列器真的被呼叫了嗎 ----------------


def test_端點真的把job丟給入列器():
    """正式的入列器是 no-op，什麼都不做的東西證明不了自己被呼叫過。

    換上一個「會記帳」的假入列器——有 dispatch() 方法的最小類別，
    與 phase-65 §4.8 測試安全網的假派工（記帳假派工）同一個形狀——
    就驗得出 router 真的有做入列這件事：
    少寫那一行 dispatcher.dispatch(job_id)，這顆會紅。
    """
    記錄: list[str] = []

    class 記帳假派工:
        """符合 TaskDispatcher Protocol 的最小假件：只把 job_id 記下來。"""

        def dispatch(self, job_id: str) -> None:
            記錄.append(job_id)

    假派工 = 記帳假派工()

    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)
    app.dependency_overrides[get_task_dispatcher] = lambda: 假派工

    resp = client.post("/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")})

    assert 記錄 == [resp.json()["job_id"]]


def test_入列失敗時回500而且staging與任務都不留():
    """design5.md §8 第 8 列：Redis 當下掛了 → 500，連 staging 也別留。

    順序鐵律的證明題：先寫 staging 再入列，所以入列炸掉時 staging 已經在磁碟上了，
    失敗路徑必須自己把它刪掉——不刪的話，24 小時掃把清掉之前那個檔案就是垃圾。
    """

    class 一定壞掉的入列器:
        def dispatch(self, job_id: str) -> None:
            raise RuntimeError("Redis 沒有回應")

    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂的收據)
    app.dependency_overrides[get_task_dispatcher] = lambda: 一定壞掉的入列器()

    with TestClient(app, raise_server_exceptions=False) as 不擲出例外的client:
        resp = 不擲出例外的client.post(
            "/photos", files={"file": ("sample.png", PNG_BYTES, "image/png")}
        )

    assert resp.status_code == 500
    assert 目前的任務清單().list_open() == [], "入列失敗的 job 不可以留在清單裡變幽靈"
    留下的檔案 = (
        [p for p in config.DATA_DIR.rglob("*") if p.is_file()] if config.DATA_DIR.exists() else []
    )
    assert 留下的檔案 == [], f"入列失敗不可以留下 staging 檔：{留下的檔案}"


def test_415不建任務也不寫staging():
    """design5.md §8 第 1 列：格式不對 → 415，無 job、無 staging。

    連 data/ 這個資料夾都不該被建出來——格式檢查排在最前面，
    後面那三件事（落 staging／建 job／入列）一件都不會發生。
    """
    resp = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert resp.status_code == 415
    assert 目前的任務清單().list_open() == []
    assert not config.DATA_DIR.exists()


def test_upload_missing_file_returns_422():
    # 沒夾帶檔案 → FastAPI 框架既有的 422，不另外發明行為
    resp = client.post("/photos")
    assert resp.status_code == 422


def test_openapi_has_photos_endpoint():
    # router 真的掛上 main.py（等效驗收第 6 項的 /docs 檢查）
    paths = client.get("/openapi.json").json()["paths"]
    assert "/photos" in paths and "post" in paths["/photos"]
