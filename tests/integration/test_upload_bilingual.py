"""雙語：英文照片的描述與欄位原樣儲存，系統不做翻譯（design.md §8.1、§8.3）。

規格 .feature 全為中文，雙語行為以本檔額外覆蓋。
2026-08-20 起 category 不再由 VLM 決定：英文的 "Receipt" 不在資料夾清單內，
會被 clamp_category 夾成「未分類」——但 text／location／items 依然是英文原文。
"""

from __future__ import annotations

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_png_bytes

PNG_BYTES = make_png_bytes()   # Phase 19 已改成這樣，本 phase 沿用

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
    # 回應：英文原文（唯一的例外是 category——它現在代表「所屬資料夾」）
    assert body["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    assert body["metadata"] == {
        "category": "未分類",
        "location": "Target",
        "items": ["Cola", "Chips"],
        "content_time": "2026-08-10",
    }
    # "Receipt" 不在資料夾清單裡 → 建議也退回「未分類」（design1.md §7.1）
    assert body["suggested_folder"]["name"] == "未分類"
    assert body["folder"]["name"] == "未分類"
    # 資料庫：地點與物品也是英文原文，沒有任何一處被翻成中文
    row = photo_repository.fetch_photo(body["id"])
    assert row["category"] == "未分類"
    assert row["location"] == "Target"
    assert row["items"] == ["Cola", "Chips"]
    assert photo_repository.fetch_embedding(body["id"]) is not None
