"""POST /photos 收 PDF：一頁一張照片（design3.md D7、§7）。

PDF 不走另一套入庫邏輯——每一頁渲染成 PNG 之後，就是一次普通的單圖上傳
（看圖 → 轉向量 → 寫入未分類 → 存原圖＋縮圖）。所以這裡驗的是「拆頁與收尾」：
拆成幾筆、壞檔怎麼收、某一頁看不懂怎麼辦，以及單圖回應有沒有被改到。
"""

from __future__ import annotations

import pytest

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_pdf_bytes, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class 分頁VLM:
    """指定「第幾頁看得懂」的假件，用來重現「部分頁看不懂」。

    FakeVLM 對每一次呼叫都回同一個答案，驗不出「跳過第 2 頁、其餘照收」；
    這個假件只在本檔案用得到，就不放進 tests/fakes.py。
    """

    def __init__(self, 看得懂的頁碼: set[int]) -> None:
        self.看得懂的頁碼 = 看得懂的頁碼      # 1 起算，與 skipped_pages 同一套頁碼
        self.calls = 0

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        if self.calls in self.看得懂的頁碼:
            return 收據理解
        return PhotoUnderstanding(understood=False)


def data_dir底下的檔案() -> list:
    """DATA_DIR 底下所有實際檔案。conftest 已把它指到本測試專屬的臨時目錄。"""
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


def 上傳PDF(client, payload: bytes):
    return client.post(
        "/photos", files={"file": ("scan.pdf", payload, "application/pdf")}
    )


def test_上傳三頁PDF建立三筆照片(client):
    vlm = FakeVLM(收據理解)
    app.dependency_overrides[get_vlm] = lambda: vlm

    response = 上傳PDF(client, make_pdf_bytes(3))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pages"] == 3
    assert body["skipped_pages"] == []
    assert len(body["created"]) == 3
    # 一頁一張，資料庫真的多了三列
    assert photo_repository.count_photos() == 3
    # 看圖是一頁叫一次（不是整份 PDF 叫一次），也沒有第二個模型
    assert vlm.calls == 3

    for 每頁 in body["created"]:
        # 與單圖上傳一致：先進未分類，AI 的建議只出現在回應
        assert 每頁["folder"]["name"] == "未分類"
        assert 每頁["suggested_folder"]["name"] == "收據"
        assert 每頁["thumbnail_url"] == f"/photos/{每頁['id']}/thumbnail"

        row = photo_repository.fetch_photo(每頁["id"])
        # 存下來的是那一頁渲染出的 PNG，不是 PDF——讀圖端點因此不必改
        assert row["content_type"] == "image/png"
        assert storage_service.absolute_path(row["original_path"]).is_file()
        assert storage_service.absolute_path(row["thumbnail_path"]).is_file()


def test_壞PDF回422不存任何資料(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = 上傳PDF(client, b"not a pdf")

    assert response.status_code == 422
    assert response.json() == {"detail": "無法讀取 PDF 檔案"}
    assert photo_repository.count_photos() == 0
    assert data_dir底下的檔案() == []


def test_全部頁看不懂回422不存任何資料(client):
    # conftest 的 wire_fake_ai 預設就是「看不懂」的 FakeVLM，這裡不覆寫即可
    response = 上傳PDF(client, make_pdf_bytes(2))

    assert response.status_code == 422
    assert response.json() == {"detail": "PDF 每一頁都無法理解，未儲存任何資料"}
    assert photo_repository.count_photos() == 0
    assert data_dir底下的檔案() == []


def test_部分頁看不懂時其餘頁照樣入庫並回報跳過的頁碼(client):
    vlm = 分頁VLM(看得懂的頁碼={1, 3})
    app.dependency_overrides[get_vlm] = lambda: vlm

    response = 上傳PDF(client, make_pdf_bytes(3))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pages"] == 3
    # 頁碼從 1 起算，與使用者在 PDF 閱讀器上看到的一致
    assert body["skipped_pages"] == [2]
    assert len(body["created"]) == 2
    assert photo_repository.count_photos() == 2


@pytest.mark.parametrize("頁數", [1, 2])
def test_pages與created長度相加等於跳過的頁數(client, 頁數):
    """不變式：pages ＝ created 筆數 ＋ skipped_pages 筆數（沒有頁會憑空消失）。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    body = 上傳PDF(client, make_pdf_bytes(頁數)).json()

    assert body["pages"] == len(body["created"]) + len(body["skipped_pages"])


def test_單圖上傳回應形狀不變(client):
    """PDF 分支不可以污染單圖回應——鍵集合必須完全在預期之內。

    Phase 30 依計畫加了三個建議欄位（suggested_entity／entities／suggested_task），
    所以這裡跟著加三個鍵；這是「回應形狀」的守門測試，不是規格檔。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 201, response.text
    assert set(response.json()) == {
        "id", "text", "metadata", "folder", "suggested_folder",
        "folders", "thumbnail_url",
        "suggested_entity", "entities", "suggested_task",
    }
