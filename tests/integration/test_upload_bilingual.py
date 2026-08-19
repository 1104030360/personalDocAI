"""雙語：英文照片的描述與四個欄位原樣儲存，系統不做翻譯（design.md §8.1、§8.3）。

規格 .feature 全為中文且唯讀（design.md §11），雙語行為以本檔額外覆蓋。
"""

from __future__ import annotations

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"

英文收據 = PhotoUnderstanding(
    understood=True,
    text="Receipt from Target with Cola and Chips, dated 2026-08-10",
    category="Receipt",
    location="Target",
    items=["Cola", "Chips"],
    content_time="2026-08-10",
)


def test_英文照片的描述與欄位原樣儲存不翻譯(client):
    # 假 embedding／固定時鐘由 conftest 的 wire_fake_ai 自動接上，這裡只換看圖結果
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    # 回應：英文原文
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["metadata"] == {
        "category": "Receipt",
        "location": "Target",
        "items": ["Cola", "Chips"],
        "content_time": "2026-08-10",
    }
    # 資料庫：也是英文原文，沒有任何一處被翻成中文
    row = photo_repository.fetch_photo(body["id"])
    assert row["category"] == "Receipt"
    assert row["items"] == ["Cola", "Chips"]
    assert photo_repository.fetch_embedding(body["id"]) is not None
