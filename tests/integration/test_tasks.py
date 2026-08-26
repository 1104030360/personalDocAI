"""待辦（task）建立與列出的整合測試（design3.md D13、Phase 32）。

VLM 的待辦建議（Phase 30 已放在上傳回應的 suggested_task）**只是建議**；
本檔驗收的是「人按下建立才寫入」與「列出來看」兩件事：
① `POST /photos/{id}/task`：201 與回應形狀、409（一張照片至多一筆）、404、422×2。
② `GET /tasks`：先到期的排前面、沒到期日的排最後、thumbnail_url 不外洩硬碟路徑。

不做完成勾選、不做刪除、不做分頁（design3.md §7 MVP）。

每個測試依 tests/conftest.py 的 autouse fixture reset_tables，
在「四張表清空＋六筆預設資料夾重播完畢」的乾淨狀態下執行，
task 表被 CASCADE 一起清掉，所以每個測試看到的待辦清單一定是空的。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片
from tests.fakes import FakeVLM

課本照片 = PhotoUnderstanding(
    understood=True,
    text="課本上寫著 Project 2 的截止日",
    category="文件",
    location=None,
    items=["課本"],
    content_time=None,
)


def 上傳(client) -> dict:
    """走一次真正的上傳流程（會存檔＝有縮圖），回傳**資料庫那一列**。

    增量五（Phase 62）起 POST /photos 只收下檔案回 202，照片要等 worker
    跑完任務才入庫；共用工具 上傳一張並取回照片() 幫測試扮演那個 worker，
    最後回 photo_repository.fetch_photo() 的 dict。

    回的鍵從「201 回應」換成「photo 表的欄位」，但本檔的呼叫端只用 ["id"]，
    所以一個字都不必改。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(課本照片)
    return 上傳一張並取回照片(client)


@pytest.fixture
def 已上傳的照片(client) -> dict:
    return 上傳(client)


def 直接寫一列照片(text: str = "沒有縮圖的舊照片") -> dict:
    """繞過上傳流程直接插一列——**不會存檔**，所以 thumbnail_path 是 NULL。

    這正是正式庫那兩張遷移前舊照片的長相（CLAUDE.md 的「重要陷阱」），
    也是 thumbnail_url 要回 null 讓前端畫占位的那一種。
    """
    return photo_repository.insert_photo(
        text=text,
        category="其他",
        location=None,
        items=[],
        content_time=None,
        embedding=[0.01] * config.EMBEDDING_DIM,
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )


# ---------------- ① 建立待辦 ----------------


def test_建立待辦回201與回應形狀(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]

    response = client.post(
        f"/photos/{photo_id}/task",
        json={"title": "  交 Project 2  ", "due_date": "2026-09-18"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # 恰好這五個鍵：created_at 是內部欄位，不外送
    assert set(body) == {"id", "photo_id", "title", "due_date", "thumbnail_url"}
    assert body["photo_id"] == photo_id
    # 前後空白由驗證器去掉
    assert body["title"] == "交 Project 2"
    assert body["due_date"] == "2026-09-18"
    assert body["thumbnail_url"] == f"/photos/{photo_id}/thumbnail"
    # 真的寫進資料庫了（不是只回應給前端看）
    assert photo_repository.get_task_by_photo(photo_id)["title"] == "交 Project 2"


def test_建立待辦可以沒有到期日(client, 已上傳的照片):
    """看不出期限的待辦照樣成立——due_date 可空（design3.md §7）。"""
    photo_id = 已上傳的照片["id"]

    response = client.post(f"/photos/{photo_id}/task", json={"title": "交作業"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "photo_id", "title", "due_date", "thumbnail_url"}
    assert body["due_date"] is None
    assert photo_repository.get_task_by_photo(photo_id)["due_date"] is None


def test_同一張照片第二筆待辦回409(client, 已上傳的照片):
    """photo_id UNIQUE＝一張照片至多一筆待辦（design3.md §7 MVP）。"""
    photo_id = 已上傳的照片["id"]
    assert client.post(
        f"/photos/{photo_id}/task", json={"title": "交 Project 2"}
    ).status_code == 201

    response = client.post(f"/photos/{photo_id}/task", json={"title": "改成別的"})

    assert response.status_code == 409
    assert response.json()["detail"] == "這張照片已經有待辦了"
    # 沒有被第二次的標題蓋掉
    assert photo_repository.get_task_by_photo(photo_id)["title"] == "交 Project 2"
    assert len(client.get("/tasks").json()) == 1


def test_照片不存在回404(client):
    response = client.post("/photos/999/task", json={"title": "交 Project 2"})

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"
    assert client.get("/tasks").json() == []


@pytest.mark.parametrize("title", ["", "   "])
def test_標題空白回422(client, 已上傳的照片, title):
    response = client.post(
        f"/photos/{已上傳的照片['id']}/task", json={"title": title}
    )

    assert response.status_code == 422
    assert "待辦標題不可為空白" in response.text
    assert photo_repository.get_task_by_photo(已上傳的照片["id"]) is None


@pytest.mark.parametrize("due_date", ["下週三", "2026-13-45"])
def test_到期日格式錯回422(client, 已上傳的照片, due_date):
    response = client.post(
        f"/photos/{已上傳的照片['id']}/task",
        json={"title": "交 Project 2", "due_date": due_date},
    )

    assert response.status_code == 422
    assert "到期日格式須為 YYYY-MM-DD" in response.text
    assert photo_repository.get_task_by_photo(已上傳的照片["id"]) is None


# ---------------- ② 列出待辦 ----------------


def test_list初始為空(client):
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_list依到期日排序_無到期日在最後(client):
    """先到期的排前面；沒到期日的不是「最早」而是「最後」（NULLS LAST）。"""
    for title, due_date in [
        ("九月一號到期", "2026-09-01"),
        ("八月廿五到期", "2026-08-25"),
        ("沒有期限", None),
    ]:
        photo_id = 直接寫一列照片(text=title)["id"]
        assert client.post(
            f"/photos/{photo_id}/task", json={"title": title, "due_date": due_date}
        ).status_code == 201

    response = client.get("/tasks")

    assert response.status_code == 200
    assert [t["title"] for t in response.json()] == [
        "八月廿五到期", "九月一號到期", "沒有期限"
    ]
    assert [t["due_date"] for t in response.json()] == [
        "2026-08-25", "2026-09-01", None
    ]


def test_list的thumbnail_url有縮圖給網址_沒縮圖給null(client, 已上傳的照片):
    """回的是網址不是硬碟路徑；沒縮圖的舊照片回 null 讓前端畫占位。"""
    有縮圖 = 已上傳的照片["id"]
    沒縮圖 = 直接寫一列照片()["id"]
    for photo_id in (有縮圖, 沒縮圖):
        assert client.post(
            f"/photos/{photo_id}/task", json={"title": f"照片 {photo_id} 的待辦"}
        ).status_code == 201

    response = client.get("/tasks")

    assert response.status_code == 200
    tasks = response.json()
    assert all(set(t) == {"id", "photo_id", "title", "due_date", "thumbnail_url"}
               for t in tasks)
    網址 = {t["photo_id"]: t["thumbnail_url"] for t in tasks}
    assert 網址 == {有縮圖: f"/photos/{有縮圖}/thumbnail", 沒縮圖: None}
    # 硬碟路徑（data/thumbs/…）一個字都不能出現在回應裡
    assert "data/" not in response.text
