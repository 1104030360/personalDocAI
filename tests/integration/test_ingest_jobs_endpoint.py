"""任務清單與關閉端點的整合測試（增量五 Phase 64）。

對應 design5.md §4.3、§5、§8 第 9 列。

兩支端點都**零 AI、零 SQL**：
  GET  /ingest-jobs                  → 還沒結束的任務 ＋ 待決定張數
  POST /ingest-jobs/{job_id}/dismiss → 把一列失敗的關掉（只准 failed）

任務怎麼造出來：走真的 POST /photos（Phase 62 之後回 202 並建一筆 job），
需要它「跑完」時就用 tests/conftest.py 的 跑完任務()（測試扮演 worker）。
本檔不直接戳 JobStore 造假任務——那樣驗不到「端點與真流程接得起來」。
"""

from __future__ import annotations

import pytest

from app.dependencies import get_embeddings, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import FakeVLM, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def 看得懂的假VLM(wire_fake_ai):
    """預設「看得懂」；要失敗的測試自己再覆寫成看不懂的。

    顯式依賴 wire_fake_ai 保證本 fixture 排在它之後執行、測後由它統一 clear()。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    yield


def 收下一個檔(client, filename: str = "a.png") -> str:
    """POST 一張圖，回它的 job_id（202 當下任務是 queued、照片還不存在）。"""
    response = client.post("/photos", files={"file": (filename, make_png_bytes(), "image/png")})
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


# ---------------- ① GET /ingest-jobs ----------------


def test_沒有任何任務時回空清單與零(client):
    response = client.get("/ingest-jobs")

    assert response.status_code == 200, response.text
    assert response.json() == {"jobs": [], "pending_count": 0}


def test_剛收下的檔會出現在清單裡且狀態是queued(client):
    job_id = 收下一個檔(client, "收據.png")

    body = client.get("/ingest-jobs").json()

    assert len(body["jobs"]) == 1
    列 = body["jobs"][0]
    assert 列["job_id"] == job_id
    assert 列["filename"] == "收據.png"
    assert 列["content_type"] == "image/png"
    assert 列["status"] == "queued"
    assert 列["attempt"] == 0
    assert 列["error"] is None
    # 還沒有任何照片入庫，所以待決定是 0
    assert body["pending_count"] == 0


def test_清單的每一列恰好八個鍵而且不外送內部狀態(client):
    """response_model 把關：photo_ids／ai_backend／source 是內部狀態，不外送。"""
    收下一個檔(client)

    列 = client.get("/ingest-jobs").json()["jobs"][0]

    assert set(列) == {
        "job_id",
        "filename",
        "content_type",
        "status",
        "attempt",
        "page_count",
        "pages_done",
        "error",
    }


def test_成功的任務不會出現在清單裡而待決定加一(client):
    """design5.md D9：成功 → 那一列消失、頂欄 N +1（成功＝job 被刪掉）。"""
    job_id = 收下一個檔(client)

    跑完任務(job_id)

    body = client.get("/ingest-jobs").json()
    assert body["jobs"] == [], "成功的任務不該留在清單上"
    assert body["pending_count"] == 1


def test_失敗的任務會留在清單上並帶著錯誤短句(client):
    """design5.md D9：失敗列留下，讓使用者知道有一張沒進去。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(PhotoUnderstanding(understood=False))
    job_id = 收下一個檔(client, "看不懂的.png")

    跑完任務(job_id)

    body = client.get("/ingest-jobs").json()
    assert len(body["jobs"]) == 1
    列 = body["jobs"][0]
    assert 列["job_id"] == job_id
    assert 列["status"] == "failed"
    assert 列["error"], "失敗一定要有一句給人看的短話"
    # 失敗＝什麼都沒存，所以待決定仍然是 0
    assert body["pending_count"] == 0
    assert photo_repository.count_photos() == 0


def test_待決定張數跟收件箱一致(client):
    """pending_count 走 SQL（收件箱照片數），不是「跑成功幾筆任務」。

    刻意用兩條路造出照片：一條走上傳流程，一條直接寫資料庫（模擬遷移進來的舊照片）。
    如果有人把 pending_count 改成從 JobStore 數，第二張就會漏掉，這顆會紅。
    """
    跑完任務(收下一個檔(client))

    photo_repository.insert_photo(
        text="遷移進來的舊照片",
        category="未分類",
        location=None,
        items=[],
        content_time=None,
        embedding=app.dependency_overrides[get_embeddings]().embed_query("舊照片"),
    )

    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    assert 收件箱["photo_count"] == 2
    assert client.get("/ingest-jobs").json()["pending_count"] == 2


def test_已定案的照片不算進待決定(client):
    """定案＝離開收件箱，N 要減一（design5.md §12 階段甲第四條的後端那一半）。"""
    job_id = 收下一個檔(client)
    跑完任務(job_id)
    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    photo_id = photo_repository.list_photos_in_folder(收件箱["id"])[0]["id"]
    收據 = photo_repository.find_folder_by_name("收據")

    assert (
        client.patch(f"/photos/{photo_id}/folder", json={"folder_id": 收據["id"]}).status_code
        == 200
    )

    assert client.get("/ingest-jobs").json()["pending_count"] == 0


# ---------------- ② POST /ingest-jobs/{job_id}/dismiss ----------------


def test_關掉失敗的那一列回204且清單少一列(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(PhotoUnderstanding(understood=False))
    job_id = 收下一個檔(client)
    跑完任務(job_id)
    assert len(client.get("/ingest-jobs").json()["jobs"]) == 1

    response = client.post(f"/ingest-jobs/{job_id}/dismiss")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/ingest-jobs").json()["jobs"] == []
    assert 目前的任務清單().get(job_id) is None


def test_關掉還在跑的任務回409(client):
    """design5.md §8 第 9 列：進行中的不准用 dismiss 藏起來。

    藏起來會讓人以為東西不見了，而它其實還在跑——之後照片突然冒出來更嚇人。
    """
    job_id = 收下一個檔(client)  # 還是 queued，沒跑過

    response = client.post(f"/ingest-jobs/{job_id}/dismiss")

    assert response.status_code == 409
    assert response.json()["detail"] == "這筆任務還在進行中，不能關掉"
    # 一個字都沒動：任務還在清單上
    assert len(client.get("/ingest-jobs").json()["jobs"]) == 1


def test_關掉不存在的任務回404(client):
    """順序鐵律：先查「有沒有這筆」（404），再查「狀態對不對」（409）。"""
    response = client.post("/ingest-jobs/根本沒有這個job/dismiss")

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到這筆任務"


def test_關掉成功的任務也是404(client):
    """成功＝那筆 job 已經被刪掉了，所以「找不到」是正確答案（不是 409）。"""
    job_id = 收下一個檔(client)
    跑完任務(job_id)

    assert client.post(f"/ingest-jobs/{job_id}/dismiss").status_code == 404


# ---------------- ③ 清點 ----------------


def test_兩支新端點都在openapi裡而且沒有DELETE(client):
    """design5.md §0 禁止事項第三條：關掉失敗列用 POST，不准新增 DELETE 動詞。"""
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/ingest-jobs"]
    assert "post" in paths["/ingest-jobs/{job_id}/dismiss"]
    assert "delete" not in paths["/ingest-jobs"]
    assert "delete" not in paths["/ingest-jobs/{job_id}/dismiss"]
