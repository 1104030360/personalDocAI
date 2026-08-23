"""抽屜糾錯 few-shot 的整合測試（Phase 35、design3.md D11）。

「糾錯」＝VLM 建議 A、使用者定案時選了 B，而且 A≠B。系統把這種例子記下來
（folder_correction 表，Phase 29 已建好），下一次上傳看圖時當 few-shot 注入 prompt。
不是第二個模型、不是微調——仍然只有同一次看圖呼叫，仍然要人按確認。

本檔涵蓋：
  ① repository 兩函式：record_folder_correction／recent_corrections（新的在前、N=5 截斷）
  ② 上傳把「clamp 後的建議」持久化到 photo.suggested_category（沒建議＝NULL）
  ③ PATCH 定案時的記／不記四型（②改選記、③自建記、①採用不記、無建議不記、
     embedding 失敗不記），以及「記錄失敗不可以影響歸類本體」
  ④ 上傳時真的把最近 5 筆注入看圖（PDF 整份只讀一次、各頁共用同一份）
  ⑤ 待決定分頁讀得到同一筆建議（GET /folders/{收件箱} 的照片摘要）

prompt 那一段長什麼樣是純函式的事，測試在 tests/unit/test_vlm_service_unit.py。
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_embeddings, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_pdf_bytes, make_png_bytes

# VLM 的建議是「收據」（六個預設資料夾之一，所以 clamp 會命中並留下建議）。
# text 裡刻意不出現資料夾名稱，糾錯例子的題幹才看得出是照片描述、不是類別名。
超市照片 = PhotoUnderstanding(
    understood=True,
    text="超市購物的照片",
    category="收據",
    location="Costco",
    items=["咖啡", "牛奶"],
    content_time=None,
)

# VLM 推薦六個預設資料夾以外的名字 → clamp 成「未分類」＝這張沒有建議
清單外建議的照片 = PhotoUnderstanding(
    understood=True,
    text="A Costco receipt for cola",
    category="Receipts from Costco",
    location="Costco",
    items=["cola"],
    content_time=None,
)


@pytest.fixture
def 假看圖(wire_fake_ai):
    """接上「看得懂且建議收據」的假看圖，並把實例交給測試。

    顯式依賴 wire_fake_ai 保證它先跑（六個注入點都已接假件），測後由它統一 clear()。
    回傳實例是為了驗 last_corrections——也就是「router 真的把糾錯清單傳進看圖了」。
    """
    fake = FakeVLM(超市照片)
    app.dependency_overrides[get_vlm] = lambda: fake
    return fake


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


class 會炸的Embeddings:
    """embed_query／embed_documents 一律爆炸——模擬歸類途中 Ollama 掛掉。"""

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("Ollama 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Ollama 沒有回應")


def 上傳一張(client, 檔名: str = "a.png") -> dict:
    """上傳一張成功的照片，回傳 201 的 JSON body。"""
    response = client.post(
        "/photos", files={"file": (檔名, make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def 資料夾id(name: str) -> int:
    return photo_repository.find_folder_by_name(name)["id"]


# ---------- ① repository 兩函式 ----------
def test_記一筆糾錯後可以原樣讀回三個欄位():
    photo_repository.record_folder_correction(
        suggested="收據", chosen="飲食", photo_text="餐廳菜單的照片"
    )

    corrections = photo_repository.recent_corrections()

    assert len(corrections) == 1
    # 恰三鍵：few-shot 例子只需要「題幹＋猜錯的＋正確的」，id 與時間沒人看
    assert corrections[0] == {
        "suggested": "收據",
        "chosen": "飲食",
        "photo_text": "餐廳菜單的照片",
    }


def test_最近的糾錯新的在前且預設最多五筆():
    """design3.md §7：N＝5。第 6 筆進來時最舊的那筆就不該再出現在 prompt 裡。"""
    for 第幾筆 in range(6):
        photo_repository.record_folder_correction(
            suggested="收據", chosen=f"夾{第幾筆}", photo_text=f"第{第幾筆}張"
        )

    corrections = photo_repository.recent_corrections()

    assert [c["chosen"] for c in corrections] == ["夾5", "夾4", "夾3", "夾2", "夾1"]
    assert "夾0" not in [c["chosen"] for c in corrections], "最舊的那筆應該被擠掉"


def test_糾錯筆數可以指定():
    for 第幾筆 in range(3):
        photo_repository.record_folder_correction(
            suggested="收據", chosen=f"夾{第幾筆}", photo_text=f"第{第幾筆}張"
        )

    assert [c["chosen"] for c in photo_repository.recent_corrections(limit=2)] == [
        "夾2",
        "夾1",
    ]


def test_一筆糾錯都沒有時回空清單():
    assert photo_repository.recent_corrections() == []


# ---------- ② 上傳把建議持久化 ----------
def test_上傳把clamp後的建議存進照片(client, 假看圖):
    """已釐清 B：建議寫進 photo.suggested_category，PATCH 與待決定分頁都靠它。"""
    body = 上傳一張(client)

    row = photo_repository.fetch_photo(body["id"])
    assert row["suggested_category"] == "收據"
    # 建議只是建議：照片本體仍然一律先進收件箱（design1.md §2 不變）
    assert row["category"] == "未分類"
    assert body["suggested_folder"]["name"] == "收據"


def test_清單外的建議不留建議(client, wire_fake_ai):
    """clamp 成「未分類」＝沒有建議（不是猜錯）→ 欄位存 NULL，之後一律不記糾錯。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(清單外建議的照片)

    body = 上傳一張(client)

    assert photo_repository.fetch_photo(body["id"])["suggested_category"] is None


# ---------- ③ PATCH 定案時的記／不記 ----------
def test_改選其他現有資料夾就記一筆糾錯(client, 假看圖):
    """已釐清 D：②改選現有且名稱 ≠ 建議 ＝ 糾錯。"""
    body = 上傳一張(client)

    response = client.patch(
        f"/photos/{body['id']}/folder", json={"folder_id": 資料夾id("飲食")}
    )

    assert response.status_code == 200, response.text
    corrections = photo_repository.recent_corrections()
    assert len(corrections) == 1
    assert corrections[0] == {
        "suggested": "收據",
        "chosen": "飲食",
        "photo_text": "超市購物的照片",
    }


def test_自建新資料夾也記一筆糾錯(client, 假看圖):
    """已釐清 D：③自建同樣算糾錯——使用者等於說「你給的那些都不對」。"""
    body = 上傳一張(client)

    response = client.patch(
        f"/photos/{body['id']}/folder",
        json={"name": "專案X", "description": "跟課程作業有關的照片"},
    )

    assert response.status_code == 200, response.text
    corrections = photo_repository.recent_corrections()
    assert len(corrections) == 1
    assert corrections[0]["suggested"] == "收據"
    assert corrections[0]["chosen"] == "專案X"


def test_採用建議不記糾錯(client, 假看圖):
    """已釐清 D：①採用建議＝猜對了，沒有東西要學。"""
    body = 上傳一張(client)

    response = client.patch(
        f"/photos/{body['id']}/folder", json={"folder_id": 資料夾id("收據")}
    )

    assert response.status_code == 200, response.text
    assert photo_repository.recent_corrections() == []


def test_沒有建議的照片不記糾錯(client, wire_fake_ai):
    """已釐清 D：suggested_category 為空＝clamp 失敗＝沒建議，不是猜錯。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(清單外建議的照片)
    body = 上傳一張(client)

    response = client.patch(
        f"/photos/{body['id']}/folder", json={"folder_id": 資料夾id("飲食")}
    )

    assert response.status_code == 200, response.text
    assert photo_repository.recent_corrections() == []


def test_PATCH途中embedding失敗時不記糾錯(不擲出例外的client, 假看圖):
    """記錄寫在 update 成功之後——500 的路徑根本走不到那裡。"""
    body = 上傳一張(不擲出例外的client)

    app.dependency_overrides[get_embeddings] = lambda: 會炸的Embeddings()
    response = 不擲出例外的client.patch(
        f"/photos/{body['id']}/folder", json={"folder_id": 資料夾id("飲食")}
    )

    assert response.status_code == 500
    assert photo_repository.recent_corrections() == [], "沒有歸類成功就不該留下糾錯"


def test_記錄糾錯失敗不影響歸類本體(client, 假看圖, monkeypatch, caplog):
    """糾錯只是學習素材：寫不進去就算了（log warning、不是靜默吞掉），使用者的歸類照樣成功。"""
    body = 上傳一張(client)

    def 會炸的記錄(**kwargs):
        raise RuntimeError("folder_correction 寫入失敗")

    monkeypatch.setattr(photo_repository, "record_folder_correction", 會炸的記錄)

    with caplog.at_level(logging.WARNING):
        response = client.patch(
            f"/photos/{body['id']}/folder", json={"folder_id": 資料夾id("飲食")}
        )

    assert response.status_code == 200, response.text
    assert response.json()["folder"]["name"] == "飲食"
    assert photo_repository.fetch_photo(body["id"])["category"] == "飲食"
    # 確認例外真的有被記下來（log warning），不是被 except Exception 靜默吞掉
    assert "糾錯素材寫入失敗" in caplog.text
    assert any(record.levelname == "WARNING" for record in caplog.records)


# ---------- ④ 上傳時注入最近 5 筆 ----------
def test_上傳看圖時帶入最近五筆糾錯(client, 假看圖):
    for 第幾筆 in range(6):
        photo_repository.record_folder_correction(
            suggested="收據", chosen=f"夾{第幾筆}", photo_text=f"第{第幾筆}張"
        )

    上傳一張(client)

    assert [c["chosen"] for c in 假看圖.last_corrections] == [
        "夾5", "夾4", "夾3", "夾2", "夾1",
    ]


def test_沒有糾錯時帶入空清單(client, 假看圖):
    上傳一張(client)

    assert 假看圖.last_corrections == []


def test_PDF整份只讀一次糾錯清單各頁共用(client, 假看圖, monkeypatch):
    """校準 §3：PDF 各頁共用同一份——上傳一開始讀一次就好，不是每頁查一次資料庫。"""
    photo_repository.record_folder_correction(
        suggested="收據", chosen="飲食", photo_text="餐廳菜單的照片"
    )
    次數 = {"n": 0}
    真的讀 = photo_repository.recent_corrections

    def 計數(*args, **kwargs):
        次數["n"] += 1
        return 真的讀(*args, **kwargs)

    monkeypatch.setattr(photo_repository, "recent_corrections", 計數)

    response = client.post(
        "/photos", files={"file": ("a.pdf", make_pdf_bytes(pages=2), "application/pdf")}
    )

    assert response.status_code == 201, response.text
    assert response.json()["pages"] == 2
    assert 假看圖.calls == 2, "兩頁都要真的看圖"
    assert 次數["n"] == 1, "糾錯清單整份 PDF 只讀一次"
    assert [c["chosen"] for c in 假看圖.last_corrections] == ["飲食"]


# ---------- ⑤ 待決定分頁讀得到同一筆建議 ----------
def test_待決定分頁的照片摘要帶著同一筆建議(client, 假看圖):
    """校準 §5：前端靠這個欄位畫選項①，不必再 call 一次看圖。"""
    body = 上傳一張(client)
    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])

    photos = client.get(f"/folders/{收件箱['id']}").json()["photos"]

    assert photos[0]["id"] == body["id"]
    assert photos[0]["suggested_category"] == "收據"
