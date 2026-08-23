"""vlm_service 的實體／待辦擴充：純函式與 prompt，不碰資料庫、不碰網路（Phase 30）。

design3.md D8：仍然是同一個 gemma4 看一次圖，多出來的只是「建議欄位」，
不是第二個分類模型。D12：AI 一次只建議 1 個實體，且只能從現有清單挑——
清單外的名字絕不自動變成新實體，這由 clamp_entity() 在後端把關。
"""

from app.services.vlm_service import (
    PhotoUnderstanding,
    build_vlm_prompt,
    clamp_entity,
)

# 資料夾清單（沿用 design1.md §5 的前兩筆就夠——本檔驗的是實體與待辦那兩段）
FOLDERS = [
    {"id": 1, "name": "未分類", "description": "不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。"},
    {"id": 2, "name": "收據", "description": "發票、消費憑證、購物明細。"},
]

# 實體清單一開始是空的，只在使用者按「③自創」時才變長（design3.md D12）
ENTITIES = [
    {"id": 1, "name": "我的 MacBook", "description": "2023 年買的筆電"},
    {"id": 2, "name": "Project 2", "description": "這學期的課程專案"},
]


def test_photo_understanding_新增實體與待辦三欄且預設為空():
    """三個新欄位都是「建議」，可以沒有——預設 None＝這張照片沒有實體／沒有待辦。"""
    understanding = PhotoUnderstanding(understood=True, text="一張照片")

    assert understanding.entity is None
    assert understanding.task_title is None
    assert understanding.task_due is None


def test_clamp_entity_命中回清單裡的那一筆():
    """回的是整筆 dict（id 之後要拿來釘選），不是只有名字。"""
    assert clamp_entity("我的 MacBook", ENTITIES) == ENTITIES[0]
    assert clamp_entity("Project 2", ENTITIES) == ENTITIES[1]


def test_clamp_entity_大小寫與前後空白也命中且回原文():
    """鏡射 clamp_category：比對不分大小寫、忽略前後空白，回的一律是清單原文。"""
    assert clamp_entity("project 2", ENTITIES) == ENTITIES[1]
    assert clamp_entity("PROJECT 2", ENTITIES) == ENTITIES[1]
    assert clamp_entity("  Project 2  ", ENTITIES) == ENTITIES[1]


def test_clamp_entity_清單外回None():
    """實體沒有「未分類」這種保底選項——不像就是不像（design3.md D12）。"""
    assert clamp_entity("我的 iPad", ENTITIES) is None
    assert clamp_entity("", ENTITIES) is None
    assert clamp_entity(None, ENTITIES) is None


def test_clamp_entity_清單為空一律回None():
    assert clamp_entity("我的 MacBook", []) is None


def test_build_vlm_prompt_含實體名稱與說明():
    """清單是變數：使用者自創的實體，下一次上傳時模型就看得到。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "現有實體" in prompt
    for entity in ENTITIES:
        assert entity["name"] in prompt
        assert entity["description"] in prompt


def test_build_vlm_prompt_實體規則明講只能選一個且不符合填null():
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "都不符合" in prompt
    assert "填 null" in prompt


def test_build_vlm_prompt_實體清單為空時明講一律填null():
    """實體表一開始是空的，那一段不能留著一串空白讓模型自由發揮。"""
    prompt = build_vlm_prompt(FOLDERS, [], [])

    assert "目前沒有任何實體，entity 一律填 null" in prompt


def test_build_vlm_prompt_含待辦判斷規則():
    """design3.md D13：同一輪判斷有沒有 actionable，有才抽標題與到期。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "task_title" in prompt
    assert "task_due" in prompt
    assert "YYYY-MM-DD" in prompt


def test_build_vlm_prompt_資料夾那一段原封不動():
    """實體與待辦是「加」上去的，既有的六欄位規則一字不變（回歸防線）。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "現有資料夾（category 只能從這裡選一個，禁止自創名稱）" in prompt
    assert "不確定就填「未分類」" in prompt
    assert "照片內容本身的主要語言" in prompt
