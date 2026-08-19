"""Phase 5 的暫時性測試：確認看圖有被呼叫、失敗會變成 422、中英文都能處理。"""

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"  # 內容不重要，我們用假件，不會真的去看圖
)

中文收據 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)

英文收據 = PhotoUnderstanding(
    understood=True,
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time="2026-08-10",
)


def test_看得懂的照片回傳理解結果(client):
    fake = FakeVLM(中文收據)
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    assert response.json()["text"] == 中文收據.text
    assert fake.calls == 1


def test_英文照片的描述保持英文不翻譯(client):
    """雙語：VLM 用照片自己的語言描述，系統不做任何翻譯（design.md §8.1）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["metadata"]["category"] == "Receipt"
    assert body["metadata"]["items"] == ["Cola", "Chips"]


def test_看不懂的照片回傳422且不儲存(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "VLM 無法理解照片內容，未儲存任何資料"
    assert photo_repository.count_photos() == 0


def test_非圖片格式不會呼叫看圖(client):
    fake = FakeVLM()
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 415
    assert fake.calls == 0  # 415 之後不會呼叫 understand()


def test_理解結果text全空白也回422且不儲存(client):
    """Rule U7 的另一半：understood=True 但 text 全空白，一樣視為無法理解（見常見問題 Q5）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=True, text="   ")
    )

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "VLM 無法理解照片內容，未儲存任何資料"
    assert photo_repository.count_photos() == 0


def test_上傳成功會完整寫入並回201(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(中文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == 中文收據.text
    assert body["metadata"] == {
        "category": "收據",
        "location": "Target",
        "items": ["可樂", "洋芋片"],
        "content_time": "2026-08-10",
    }

    row = photo_repository.fetch_photo(body["id"])
    assert row["items"] == ["可樂", "洋芋片"]
    assert row["uploaded_at"].strftime("%Y-%m-%d %H:%M") == "2026-08-18 10:00"
    assert photo_repository.fetch_embedding(body["id"]) is not None
