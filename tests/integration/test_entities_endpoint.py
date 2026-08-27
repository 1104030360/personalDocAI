"""GET /entities 的整合測試（design3.md D12）。

實體表和資料夾不一樣：沒有預設種子，一開始就是空的，
清單只在使用者按「③自創」時才變長。
"""

from __future__ import annotations

from app.repositories import photo_repository


def test_一開始沒有任何實體(client):
    """資料夾有六筆種子，實體沒有——空清單是正常狀態，不是錯誤。"""
    response = client.get("/entities")

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_建立後依id排序列出且只有三個欄位(client):
    macbook = photo_repository.create_entity("我的 MacBook", "2023 年買的筆電")
    project = photo_repository.create_entity("Project 2", "這學期的課程專案")

    response = client.get("/entities")

    assert response.status_code == 200, response.text
    body = response.json()
    # 順序照 id（先建的在前），前端下拉選單才每次長得一樣
    assert [e["id"] for e in body] == [macbook["id"], project["id"]]
    assert body[0] == {
        "id": macbook["id"],
        "name": "我的 MacBook",
        "description": "2023 年買的筆電",
    }
    # created_at 之類的內部欄位不外送
    assert all(set(e) == {"id", "name", "description"} for e in body)
