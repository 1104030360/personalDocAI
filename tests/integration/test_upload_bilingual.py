"""雙語：英文照片的描述與欄位原樣儲存，系統不做翻譯（design.md §8.1、§8.3）。

規格 .feature 全為中文，雙語行為以本檔額外覆蓋。
2026-08-20 起 category 不再由 VLM 決定：英文的 "Receipt" 不在資料夾清單內，
會被 clamp_category 夾成「未分類」——但 text／location／items 依然是英文原文。
2026-08-25（Phase 62）起上傳改回 202，回應裡已經沒有 text／metadata，
所以「不翻譯」一律改驗**資料庫那一列**（測試自己扮演 worker 把任務跑完）。
"""

from __future__ import annotations

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片
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
    """202 之後回應裡沒有 metadata 了，所以整顆改成驗**資料庫那一列**。

    這反而更貼近規格要守的事：「系統不做翻譯」講的是**存下來的東西**，
    不是回應長什麼樣。
    """
    # 假 embedding／固定時鐘由 conftest 的 wire_fake_ai 自動接上，這裡只換看圖結果
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(英文收據)

    列 = 上傳一張並取回照片(client, payload=PNG_BYTES)

    assert 列["text"] == "Receipt from Target with Cola and Chips, dated 2026-08-10"
    # 上傳一律先進收件箱，category 就是「未分類」（這條沒變）
    assert 列["category"] == "未分類"
    # 地點與物品也是英文原文，沒有任何一處被翻成中文
    assert 列["location"] == "Target"
    assert 列["items"] == ["Cola", "Chips"]
    assert 列["content_time"].isoformat() == "2026-08-10"
    # "Receipt" 不在資料夾清單裡 → clamp 成未分類 → 建議欄存 NULL（Phase 35 的規則）
    assert 列["suggested_category"] is None
    assert photo_repository.fetch_embedding(列["id"]) is not None
