"""實體釘選與再建議的整合測試（design3.md D12、Phase 30）。

涵蓋三件事：
① `POST /photos/{id}/entities`：釘現有／自創、四種錯誤碼（404×2、409×2、422），
   以及「釘選不動向量」——實體是別針，不進 embedding（design3.md §5）。
② `POST /photos/{id}/entity-suggestion`：再建議一個、exclude 生效、候選空不呼叫 LLM。
③ 入庫時寫進照片那一列的三個建議欄位
   （suggested_entity／suggested_task_title／suggested_task_due）。

2026-08-25（Phase 62）起上傳改回 202，建議不再出現在 HTTP 回應裡，
而是由 worker 入庫時一起落庫（design5.md D16）——所以 ③ 全部改驗**資料庫那一列**。
"""

from __future__ import annotations

import pytest

from app.dependencies import get_entity_suggester, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片
from tests.fakes import FakeEntitySuggester, FakeVLM

超市照片 = PhotoUnderstanding(
    understood=True,
    text="超市購物的照片",
    category="收據",
    location="Costco",
    items=["咖啡", "牛奶"],
    content_time=None,
)


def 上傳(client, understanding: PhotoUnderstanding = 超市照片) -> dict:
    """走一次真正的上傳流程（202 → 測試扮演 worker 跑完任務），回資料庫那一列。

    回的鍵不一樣了（是 photo 表的欄位，不是 201 回應）；
    但這一檔用到的只有 ["id"]，所以呼叫端一個字都不必改。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(understanding)
    return 上傳一張並取回照片(client)


@pytest.fixture
def 已上傳的照片(client) -> dict:
    return 上傳(client)


# ---------------- ① 釘選 ----------------


def test_釘現有實體回201(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]
    macbook = photo_repository.create_entity("我的 MacBook", "2023 年買的筆電")

    response = client.post(
        f"/photos/{photo_id}/entities", json={"entity_id": macbook["id"]}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["photo_id"] == photo_id
    assert body["entity"] == {
        "id": macbook["id"], "name": "我的 MacBook", "description": "2023 年買的筆電"
    }
    # entities＝自創之後可能變長的完整清單，讓彈窗直接換掉下拉選單
    assert [e["name"] for e in body["entities"]] == ["我的 MacBook"]
    # 連結真的寫進去了
    assert [e["name"] for e in photo_repository.list_photo_entities(photo_id)] == [
        "我的 MacBook"
    ]


def test_一張照片可以釘好幾個實體(client, 已上傳的照片):
    """別針不是抽屜：實體可以疊加（AND），和資料夾的 XOR 不一樣。"""
    photo_id = 已上傳的照片["id"]
    第一個 = photo_repository.create_entity("我的 MacBook", "筆電")
    第二個 = photo_repository.create_entity("Project 2", "課程專案")

    for entity in (第一個, 第二個):
        assert client.post(
            f"/photos/{photo_id}/entities", json={"entity_id": entity["id"]}
        ).status_code == 201

    assert [e["name"] for e in photo_repository.list_photo_entities(photo_id)] == [
        "我的 MacBook", "Project 2"
    ]


def test_自創實體回201且清單加一(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]

    response = client.post(
        f"/photos/{photo_id}/entities",
        json={"name": "  我的 MacBook  ", "description": "2023 年買的筆電"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    # 前後空白由驗證器去掉，「 MacBook 」和「MacBook」不會變成兩件東西
    assert body["entity"]["name"] == "我的 MacBook"
    assert [e["name"] for e in body["entities"]] == ["我的 MacBook"]
    assert [e["name"] for e in photo_repository.list_entities()] == ["我的 MacBook"]
    assert [e["name"] for e in photo_repository.list_photo_entities(photo_id)] == [
        "我的 MacBook"
    ]


def test_自創名稱與現有實體重複回409(client, 已上傳的照片):
    """大小寫不敏感（find_entity_by_name 負責），既有那筆的說明不可被蓋掉。"""
    photo_id = 已上傳的照片["id"]
    photo_repository.create_entity("我的 MacBook", "2023 年買的筆電")

    response = client.post(
        f"/photos/{photo_id}/entities",
        json={"name": "我的 macbook", "description": "不該蓋掉原本的說明"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "實體名稱已存在"
    assert len(photo_repository.list_entities()) == 1
    assert photo_repository.find_entity_by_name("我的 MacBook")["description"] == (
        "2023 年買的筆電"
    )
    # 一個字都沒寫：也沒有偷偷釘上去
    assert photo_repository.list_photo_entities(photo_id) == []


def test_重複釘同一個實體回409(client, 已上傳的照片):
    photo_id = 已上傳的照片["id"]
    macbook = photo_repository.create_entity("我的 MacBook", "筆電")
    assert client.post(
        f"/photos/{photo_id}/entities", json={"entity_id": macbook["id"]}
    ).status_code == 201

    response = client.post(
        f"/photos/{photo_id}/entities", json={"entity_id": macbook["id"]}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "這張照片已釘過這個實體"
    # 沒有變成兩條連結
    assert len(photo_repository.list_photo_entities(photo_id)) == 1


def test_照片不存在回404(client):
    macbook = photo_repository.create_entity("我的 MacBook", "筆電")

    response = client.post("/photos/999/entities", json={"entity_id": macbook["id"]})

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"


def test_實體不存在回404(client, 已上傳的照片):
    response = client.post(
        f"/photos/{已上傳的照片['id']}/entities", json={"entity_id": 999}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到實體"


@pytest.mark.parametrize(
    "body",
    [
        {},                                      # 兩個都不給
        {"entity_id": 1, "name": "我的 MacBook"},  # 兩個都給
        {"name": "   "},                         # name 只有空白
    ],
)
def test_請求必須恰好給一個entity_id或name(client, 已上傳的照片, body):
    response = client.post(f"/photos/{已上傳的照片['id']}/entities", json=body)

    assert response.status_code == 422


def test_釘選不重算向量(client, 已上傳的照片):
    """design3.md §5：實體走連結表，不進向量——embedding 的定義仍是 text＋四欄位。"""
    photo_id = 已上傳的照片["id"]
    macbook = photo_repository.create_entity("我的 MacBook", "筆電")
    釘之前 = photo_repository.fetch_embedding(photo_id)

    assert client.post(
        f"/photos/{photo_id}/entities", json={"entity_id": macbook["id"]}
    ).status_code == 201

    assert photo_repository.fetch_embedding(photo_id) == 釘之前
    row = photo_repository.fetch_photo(photo_id)
    assert row["category"] == "未分類"      # 抽屜也沒被動到


# ---------------- ② 再建議一個 ----------------


def test_再建議回登記的實體(client, 已上傳的照片):
    macbook = photo_repository.create_entity("我的 MacBook", "筆電")
    suggester = FakeEntitySuggester("我的 MacBook")
    app.dependency_overrides[get_entity_suggester] = lambda: suggester

    response = client.post(
        f"/photos/{已上傳的照片['id']}/entity-suggestion", json={"exclude": []}
    )

    assert response.status_code == 200, response.text
    assert response.json()["suggested_entity"] == {
        "id": macbook["id"], "name": "我的 MacBook", "description": "筆電"
    }
    assert suggester.calls == 1


def test_再建議的exclude會把已經看過的排除掉(client, 已上傳的照片):
    """彈窗按「再建議一個」時，已釘與這輪建議過的一律不再出現（design3.md D12）。"""
    macbook = photo_repository.create_entity("我的 MacBook", "筆電")
    project = photo_repository.create_entity("Project 2", "課程專案")
    suggester = FakeEntitySuggester("Project 2")
    app.dependency_overrides[get_entity_suggester] = lambda: suggester

    response = client.post(
        f"/photos/{已上傳的照片['id']}/entity-suggestion",
        json={"exclude": [macbook["id"]]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["suggested_entity"]["id"] == project["id"]
    # 被排除的根本沒進候選清單，模型看不到就不可能挑到它
    assert [e["name"] for e in suggester.last_candidates] == ["Project 2"]


def test_候選為空時回None且完全不呼叫模型(client, 已上傳的照片):
    """沒有東西可挑就不必問 LLM——省一次推論，也不會有幻覺可以夾。"""
    suggester = FakeEntitySuggester("我的 MacBook")
    app.dependency_overrides[get_entity_suggester] = lambda: suggester

    response = client.post(
        f"/photos/{已上傳的照片['id']}/entity-suggestion", json={}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"suggested_entity": None}
    assert suggester.calls == 0


def test_模型挑了候選外的名字一律夾成None(client, 已上傳的照片):
    photo_repository.create_entity("我的 MacBook", "筆電")
    app.dependency_overrides[get_entity_suggester] = lambda: FakeEntitySuggester(
        "我的 iPad"
    )

    response = client.post(
        f"/photos/{已上傳的照片['id']}/entity-suggestion", json={"exclude": []}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"suggested_entity": None}


def test_再建議時照片不存在回404(client):
    photo_repository.create_entity("我的 MacBook", "筆電")

    response = client.post("/photos/999/entity-suggestion", json={"exclude": []})

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"


# ---------------- ③ 入庫時落庫的三個建議欄位 ----------------


def test_上傳回應帶實體建議與完整清單(client):
    """建議改成入庫時寫進照片那一列；「完整清單」則直接問 repository。"""
    photo_repository.create_entity("我的 MacBook", "2023 年買的筆電")
    vlm = FakeVLM(超市照片.model_copy(update={"entity": "我的 macbook"}))
    app.dependency_overrides[get_vlm] = lambda: vlm

    列 = 上傳一張並取回照片(client)

    # 大小寫不同也夾得回清單原文（存的是名稱本身，不是整個實體）
    assert 列["suggested_entity"] == "我的 MacBook"
    assert [e["name"] for e in photo_repository.list_entities()] == ["我的 MacBook"]
    # 仍然只有一次看圖呼叫，而且實體清單真的被傳進去了（要注入 prompt）
    assert vlm.calls == 1
    assert [e["name"] for e in vlm.last_entities] == ["我的 MacBook"]
    # 只是建議：沒有人按確認，連結表就是空的（D3：人確認才落庫）
    assert photo_repository.list_photo_entities(列["id"]) == []


def test_上傳建議清單外的實體時suggested_entity為None(client):
    photo_repository.create_entity("我的 MacBook", "筆電")

    列 = 上傳(client, 超市照片.model_copy(update={"entity": "我的 iPad"}))

    assert 列["suggested_entity"] is None
    # 清單外的名字絕不自動變成新實體
    assert [e["name"] for e in photo_repository.list_entities()] == ["我的 MacBook"]


def test_實體表為空時照片不留任何實體建議(client):
    列 = 上傳(client)

    assert 列["suggested_entity"] is None
    assert photo_repository.list_entities() == []


def test_待辦建議隨入庫寫進照片那一列(client):
    """建議不再出現在上傳回應（202 沒有這種東西），改成入庫時落庫（design5.md D16）。

    這三欄是 Phase 56 加的、Phase 61 接線寫入的；待決定頁開窗時再讀出來，
    所以「202 之後建議會蒸發、待辦窗從此沒有入口」這個坑不存在。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        超市照片.model_copy(
            update={"task_title": "  交 Project 2  ", "task_due": "2026-09-18"}
        )
    )

    列 = 上傳一張並取回照片(client)

    # 前後空白在入庫時就去掉了（與原本回應的行為一字不變）
    assert 列["suggested_task_title"] == "交 Project 2"
    assert 列["suggested_task_due"].isoformat() == "2026-09-18"
    # 仍然只是建議：沒有人按確認，task 表就是空的（D3 人確認才落庫）
    assert photo_repository.get_task_by_photo(列["id"]) is None


def test_待辦到期日看不懂時只留標題且上傳照樣成功(client):
    """到期日推不出來不可以讓整筆入庫失敗——沿用 parse_content_time 的寬容解析。"""
    列 = 上傳(
        client,
        超市照片.model_copy(update={"task_title": "交作業", "task_due": "下週三"}),
    )

    assert 列["suggested_task_title"] == "交作業"
    assert 列["suggested_task_due"] is None


@pytest.mark.parametrize("title", [None, "   "])
def test_沒有待辦時suggested_task為None(client, title):
    列 = 上傳(client, 超市照片.model_copy(update={"task_title": title}))

    assert 列["suggested_task_title"] is None
    assert 列["suggested_task_due"] is None
