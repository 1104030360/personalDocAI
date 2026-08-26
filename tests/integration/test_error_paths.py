"""design.md §10 錯誤處理總表的逐列驗證。

2026-08-25（Phase 62）起上傳改回 202：HTTP 只做格式檢查、落 staging、入列，
看圖與寫入都搬到 worker 去了。所以本檔四條上傳相關的路徑分成兩種：
  - 415（格式不對）：HTTP 當場擋下，行為一字未變。
  - 「看不懂」「轉向量失敗」：HTTP 一律 202，失敗改在**跑完任務之後**
    看 job 的 status（design5.md §8 第 3／6 列）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import get_embeddings, get_router, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import FakeVLM, make_large_png_bytes

TARGET_RECEIPT = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據", location="Target",
    items=["可樂", "洋芋片"], content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_error_fakes(wire_fake_ai):
    """把 VLM 換成「看得懂」的假件；其餘假件與固定時鐘由 conftest 的 wire_fake_ai 統一接管。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()。
    個別測試要更壞的行為（看不懂／壞掉的 router／壞掉的 embeddings）就在測試裡再覆寫。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(TARGET_RECEIPT)
    yield


# 下面測試用的 `client` fixture 來自 tests/conftest.py（Phase 5 建立），直接沿用。


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# ---- 415：上傳非圖片格式 ----
def test_非圖片格式回415且不寫入(client):
    response = client.post("/photos", files={"file": ("a.txt", b"hi", "text/plain")})

    assert response.status_code == 415
    assert response.json()["detail"] == "上傳檔案必須為常見圖片格式（如 JPEG、PNG）"
    assert photo_repository.count_photos() == 0


# ---- VLM 看不懂：HTTP 照樣受理，最後由任務標成 failed ----
def test_vlm看不懂最後整筆失敗且不寫入(client):
    """原本是 HTTP 422；Phase 62 起「看不懂」是 worker 的結局，不是收檔的結局。

    收檔那一刻還沒有人看過圖，所以 202 是誠實的；試滿 VLM_MAX_ATTEMPTS 次
    仍看不懂才整筆失敗（design5.md §8 第 3 列），資料庫一列都不留。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )

    response = client.post("/photos", files={"file": ("a.png", b"\x89PNG", "image/png")})
    assert response.status_code == 202, response.text

    job_id = response.json()["job_id"]
    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0


# ---- 沒有「檔案太大」這個錯誤路徑 ----
def test_大檔案照樣可以上傳(client):
    大檔案 = make_large_png_bytes()   # 真的圖、真的大（隨機雜訊壓不掉）
    assert len(大檔案) > 3 * 1024 * 1024, "這個測試要用真的大檔才有意義"

    response = client.post("/photos", files={"file": ("big.png", 大檔案, "image/png")})

    assert response.status_code == 202, "規格明訂不設檔案大小上限"


def test_程式碼裡沒有任何檔案大小上限檢查():
    # 用「這個測試檔的位置」推回專案根目錄（tests/integration/ → 上兩層），
    # 跑測試時不管人在哪個目錄都找得到檔案
    專案根目錄 = Path(__file__).resolve().parents[2]
    source = (
        (專案根目錄 / "app" / "api" / "routers" / "photos.py").read_text(encoding="utf-8")
        + (專案根目錄 / "app" / "services" / "vlm_service.py").read_text(encoding="utf-8")
    )
    for 關鍵字 in ("max_size", "MAX_SIZE", "413", "too large"):
        assert 關鍵字 not in source, f"不該出現大小限制相關程式碼：{關鍵字}"


# ---- 422：問題缺漏／空字串（框架既有行為）----
# parametrize：同一個測試函式跑兩組輸入（缺 question／空字串），pytest 會算成 2 個測試
@pytest.mark.parametrize("payload", [{}, {"question": ""}])
def test_問題缺漏或空字串回422(client, payload):
    assert client.post("/ask", json=payload).status_code == 422


# ---- 200：路由 AI 失敗仍然回答 ----
def test_路由失敗仍回200並走語意查詢(client):
    class 一定壞掉的Router:
        # 簽名要跟上 Phase 34 的 route(question, entity_names)：少一個參數的話，
        # 這裡會在「進到函式本體之前」就先炸 TypeError，測的就變成「簽名不對也
        # fallback」而不是本測試要守的「模型爆炸也 fallback」。
        def route(self, question, entity_names):
            raise RuntimeError("模型爆炸了")

    app.dependency_overrides[get_router] = lambda: 一定壞掉的Router()

    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200
    assert response.json()["search_mode"] == "vector semantic search"


# ---- 200：查無相關照片（中英文各驗一次語言跟隨）----
def test_查無照片回200且不編造(client):
    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    body = response.json()
    assert response.status_code == 200
    assert body["retrieved_photo_ids"] == []
    assert "查無相關照片" in body["answer"]


def test_英文提問查無照片時用英文回覆(client):
    """雙語：查無結果的回覆語言也要跟隨提問語言。"""
    response = client.post(
        "/ask", json={"question": "What drinks did I buy recently?"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["retrieved_photo_ids"] == []
    assert "No matching photos found." in body["answer"]


# ---- embedding 呼叫失敗（例如 Ollama 沒開）：算進重試次數，用完就整筆失敗 ----
def test_embedding一直失敗最後整筆失敗(client):
    """原本是 HTTP 500（同步流程裡不吞錯）；Phase 62 起轉向量在 worker 裡。

    design5.md §8 第 6 列：轉向量失敗與看圖失敗共用同一組重試次數，
    所以這裡的假 embeddings 一路爆炸，一次 `跑完任務` 就把 VLM_MAX_ATTEMPTS
    次用完 → job 標成 failed、資料庫一列都不留（不吞錯這條原則沒變，
    只是「不吞錯」的表現從 500 換成 job["status"] == "failed"）。
    """
    class 壞掉的Embeddings:
        def embed_query(self, text):
            raise RuntimeError("Ollama 沒有回應")

        def embed_documents(self, texts):
            raise RuntimeError("Ollama 沒有回應")

    app.dependency_overrides[get_embeddings] = lambda: 壞掉的Embeddings()

    response = client.post(
        "/photos", files={"file": ("a.png", b"\x89PNG", "image/png")}
    )
    assert response.status_code == 202, response.text

    job_id = response.json()["job_id"]
    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0, "失敗時不可以留下半筆資料"


# ---- 500：資料庫掛掉不吞錯 ----
def test_資料庫掛掉回500(不擲出例外的client, monkeypatch):
    # monkeypatch：pytest 內建 fixture，暫時改掉某個屬性，測試結束會自動還原。
    # db/session.py 每次連線都重新讀 config.DATABASE_URL（Phase 3 的寫法），
    # 所以這裡改了就會生效。
    monkeypatch.setattr(
        config, "DATABASE_URL", "postgresql://localhost:5433/根本不存在的資料庫"
    )

    response = 不擲出例外的client.post("/ask", json={"question": "隨便問"})

    assert response.status_code == 500
