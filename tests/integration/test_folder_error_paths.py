"""design1.md §12 錯誤與邊界總表的逐列驗證（Phase 25 收尾）。

已被 Phase 15〜24 的測試覆蓋的列不在這裡重寫；
完整對照表見 docs/plan/finish/phase-25-錯誤收尾與全量回歸.md 的 ASCII 圖。

2026-08-25（Phase 62）起上傳改回 202，回應裡已經沒有 suggested_folder／folder／
metadata／folders 這些鍵了——「AI 建議了什麼」改成入庫時寫進照片那一列的
`suggested_category` 欄（design5.md D16）。所以本檔的斷言一律改看**資料庫**：
  - `body["suggested_folder"]["name"]` → `列["suggested_category"]`
    ⚠ 建議夾成收件箱（＝等於沒有建議）時存的是 **None**，不是字串「未分類」。
  - `body["folders"]`                   → `photo_repository.list_folders()`
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import get_embeddings, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片, 目前的任務清單, 跑完任務
from tests.fakes import FakeVLM, make_png_bytes

# make_png_bytes 是 Phase 17 加在 tests/fakes.py 的小工具，產生 Pillow 打得開的真 PNG。
# 凡是「預期上傳成功」的測試都必須用它——假的位元組（b"\x89PNG"）會讓縮圖那一步爆掉。

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_folder_error_fakes(wire_fake_ai):
    """預設 VLM「看得懂且推薦收據」；其餘假件與固定時鐘由 conftest 的 wire_fake_ai 接管。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()。
    個別測試要更壞的行為（看不懂／推薦清單外名稱／會炸的 embeddings）就在測試裡再覆寫。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    yield


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案（資料夾不算）。

    conftest 的 isolated_data_dir fixture 已把 config.DATA_DIR 指到本次測試專屬的
    臨時目錄，所以這裡看到的一定只有「本測試造成的」檔案。
    """
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


# 本檔一律用 conftest 的 上傳一張並取回照片(client)：
# 它會 POST（202）→ 測試自己扮演 worker 把任務跑完 → 回傳資料庫那一列。
# 回的鍵是 photo 表的欄位（不是舊的 201 回應），但 ["id"] 一模一樣。


# ---- ① 上傳失敗時，不寫庫、不留檔、也不建資料夾 ----
# Phase 62 起這兩種失敗發生在**不同階段**，所以原本的 parametrize 拆成兩顆：
#   非圖片格式 → HTTP 當場擋（415），連任務都不會建
#   VLM 看不懂 → HTTP 照樣受理（202），試滿次數後由任務標成 failed
def test_非圖片格式時不寫庫不留檔也不建資料夾(client):
    """design1 §12 第一列（415 那一半）：格式檢查排在最前面，行為一字未變。

    「不寫庫」「不留檔」Phase 19／20 已各有測試把關，這裡當雙保險一起斷言；
    本測試真正新補的是最後一條——失敗時**資料夾清單必須維持六個預設值**。
    """
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415, f"狀態碼不對（{response.text}）"
    assert photo_repository.count_photos() == 0, "不可以寫入資料庫"
    assert data_dir底下的檔案() == [], "不可以在 DATA_DIR 留下任何檔案"
    assert len(photo_repository.list_folders()) == 6, "不可以偷偷新增資料夾"


def test_VLM看不懂時不寫庫不留檔也不建資料夾(client):
    """design1 §12 第一列（看不懂那一半）：結局改在 worker，該守的三條不變。

    ⚠ 「不留檔」現在多守一樣東西：收檔時寫進 data/staging/ 的暫存檔，
      整筆失敗時也必須被刪掉（design5.md §4.1、D10），不然它會變成沒人會撿的垃圾。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(PhotoUnderstanding(understood=False))

    response = client.post("/photos", files={"file": ("a.png", make_png_bytes(), "image/png")})
    assert response.status_code == 202, response.text

    job_id = response.json()["job_id"]
    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0, "不可以寫入資料庫"
    assert data_dir底下的檔案() == [], "不可以在 DATA_DIR 留下任何檔案（含 staging 暫存檔）"
    assert len(photo_repository.list_folders()) == 6, "不可以偷偷新增資料夾"


# ---- ② VLM 推薦清單外的名稱 → 建議改成「未分類」 ----
def test_VLM推薦清單外名稱時建議改成未分類(client):
    """design1 §7.1：建議必須是資料夾清單裡的一筆（清單外的名稱一律夾回「未分類」）。

    Phase 62 起這件事改在入庫時做完並寫進 `suggested_category` 欄，
    夾成收件箱＝等於沒有建議 → 存 NULL。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(
            understood=True,
            text="A Costco receipt for cola",
            category="Receipts from Costco",  # 六個預設資料夾裡沒有這個名字
            location="Costco",
            items=["cola"],
            content_time="2026-08-11",
        )
    )

    列 = 上傳一張並取回照片(client)

    # 清單外 → clamp 成「未分類」＝等於沒有建議 → 建議欄存 NULL（Phase 35 的規則）
    assert 列["suggested_category"] is None
    未分類 = photo_repository.find_folder_by_name("未分類")
    assert 列["folder_id"] == 未分類["id"], "上傳一律先進收件箱"
    assert 列["category"] == "未分類"
    資料夾名稱 = [資料夾["name"] for 資料夾 in photo_repository.list_folders()]
    assert "Receipts from Costco" not in 資料夾名稱, "清單外的推薦名稱不可以被偷偷建成資料夾"


# ---- ③ 「未分類」被當成建議 → 允許（不是錯誤，只是等於沒有建議）----
def test_VLM直接推薦未分類時照樣回201(client):
    """design1 §12：選項①顯示「未分類」與關掉彈窗結果相同，設計上明訂可接受。

    ⚠ 測試名稱裡的「201」是 Phase 62 之前的狀態碼（現在收檔一律 202，
      入庫由 worker 完成）；本 phase 依計畫只改行為斷言、不改這一顆的名字。
      要守的事情一字未變：這種建議不是錯誤，照片照樣入得了庫。
      Phase 35 起「建議＝收件箱」在入庫時就折成 NULL——
      沒有建議與建議指向收件箱本來就是同一件事，所以資料庫只留一種表示法。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(
            understood=True,
            text="一張看不太出來拍什麼的照片",
            category="未分類",
        )
    )

    列 = 上傳一張並取回照片(client)

    assert 列["suggested_category"] is None
    未分類 = photo_repository.find_folder_by_name("未分類")
    assert 列["folder_id"] == 未分類["id"], "建議與實際歸屬都是未分類時，照片就該待在那一筆資料夾裡"


# ---- ④ 自建重名（大小寫不同）→ 409，不新增也不覆蓋 ----
def test_自建資料夾重名大小寫不同也回409且不覆蓋(client):
    """design1 §7.2：自建的 name 與現有資料夾重複（大小寫不敏感）→ 409。

    Phase 21 已驗過「完全同名 → 409」；這裡補的是大小寫不同的那一半。
    """
    第一張 = 上傳一張並取回照片(client)
    建立 = client.patch(
        f"/photos/{第一張['id']}/folder",
        json={"name": "Project X", "description": "課程作業"},
    )
    assert 建立.status_code == 200, 建立.text
    建立後資料夾數 = len(photo_repository.list_folders())

    第二張 = 上傳一張並取回照片(client)
    衝突 = client.patch(
        f"/photos/{第二張['id']}/folder",
        json={"name": "project x", "description": "另一個描述"},
    )

    assert 衝突.status_code == 409
    assert len(photo_repository.list_folders()) == 建立後資料夾數, "409 時不可以新增資料夾"
    重名資料夾 = photo_repository.find_folder_by_name("PROJECT X")
    assert 重名資料夾["description"] == "課程作業", "409 時不可以覆蓋原本的 description"
    assert photo_repository.fetch_photo(第二張["id"])["category"] == "未分類", (
        "409 時第二張照片必須留在未分類"
    )


# ---- ⑤ 原圖檔案被刪掉 → 404（不可以爆 500）----
def test_原圖被刪掉時讀原圖回404(client):
    """有人手動刪了 data/photos/ 底下的原圖：要回 404，不是 500。

    §12「讀不到原圖／縮圖」這一列的其他情況——路徑 NULL 的舊列、縮圖檔被刪、
    照片 id 不存在——Phase 19 的 test_photo_files.py 已逐一把關（見 ASCII 對照
    地圖），這裡只補它沒驗到的那一半：**原圖端點**對「檔案不見」的反應。
    """
    # 上傳一張並取回照片() 回的就是資料庫那一列，所以不必再 fetch_photo 一次
    列 = 上傳一張並取回照片(client)
    storage_service.absolute_path(列["original_path"]).unlink()

    response = client.get(f"/photos/{列['id']}/image")

    assert response.status_code == 404


# ---- ⑥⑦ PATCH 途中 embedding 失敗 → 500，資料庫必須完全沒動 ----
class 會炸的Embeddings:
    """embed_query／embed_documents 一律爆炸——模擬歸類途中 Ollama 掛掉。"""

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("Ollama 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Ollama 沒有回應")


def test_PATCH時embedding失敗回500且照片完全沒被改動(不擲出例外的client):
    """⑥ 採用現有資料夾的那條路：先算向量、最後才一條 UPDATE，算失敗時資料庫沒動。

    有人把順序調換（先 UPDATE 再算向量）的話，這個測試會馬上紅。
    """
    改動前 = 上傳一張並取回照片(不擲出例外的client)
    photo_id = 改動前["id"]
    改動前向量 = photo_repository.fetch_embedding(photo_id)
    收據 = photo_repository.find_folder_by_name("收據")

    app.dependency_overrides[get_embeddings] = lambda: 會炸的Embeddings()
    response = 不擲出例外的client.patch(
        f"/photos/{photo_id}/folder", json={"folder_id": 收據["id"]}
    )

    assert response.status_code == 500
    改動後 = photo_repository.fetch_photo(photo_id)
    assert 改動後["folder_id"] == 改動前["folder_id"], "folder_id 不可以被改到"
    assert 改動後["category"] == 改動前["category"] == "未分類", "category 不可以被改到"
    assert photo_repository.fetch_embedding(photo_id) == 改動前向量, "embedding 不可以被改到"


def test_PATCH自建時embedding失敗回500且不留空資料夾(不擲出例外的client):
    """⑦ 自建的那條路：create_folder 排在算向量**之後**，算失敗時連資料夾都不會建。

    有人把 create_folder 提前到算向量之前，就會留下一個誰也沒用到的空資料夾，
    這個測試會馬上紅（Phase 21 就是為了這件事把建資料夾排在算向量之後）。
    """
    改動前 = 上傳一張並取回照片(不擲出例外的client)
    photo_id = 改動前["id"]

    app.dependency_overrides[get_embeddings] = lambda: 會炸的Embeddings()
    response = 不擲出例外的client.patch(
        f"/photos/{photo_id}/folder",
        json={"name": "專案Y", "description": "不該被建出來"},
    )

    assert response.status_code == 500
    assert photo_repository.find_folder_by_name("專案Y") is None, "500 時不可以留下空資料夾"
    assert len(photo_repository.list_folders()) == 6, "資料夾必須維持六個預設值"
    改動後 = photo_repository.fetch_photo(photo_id)
    assert 改動後["folder_id"] == 改動前["folder_id"], "folder_id 不可以被改到"
    assert 改動後["category"] == 改動前["category"] == "未分類", "category 不可以被改到"


# ---- ⑧ 本增量沒有刪除 API（未分類不可刪的前提）----
def test_沒有任何刪除端點():
    """design1 §12 最後一列：本增量不做刪除 API。沒有刪除端點，就不可能刪掉未分類。"""
    專案根目錄 = Path(__file__).resolve().parents[2]
    routers目錄 = 專案根目錄 / "app" / "api" / "routers"
    原始碼 = "".join(檔案.read_text(encoding="utf-8") for 檔案 in sorted(routers目錄.glob("*.py")))
    原始碼 += (專案根目錄 / "app" / "main.py").read_text(encoding="utf-8")

    for 關鍵字 in ("@router.delete", "@app.delete"):
        assert 關鍵字 not in 原始碼, f"本增量不做刪除 API，不該出現：{關鍵字}"
