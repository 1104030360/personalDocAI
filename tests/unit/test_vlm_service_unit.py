"""vlm_service 的單元測試：純函式與資料模型，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U3「儲存結構化 metadata（四欄位；清單外資訊捨棄）」——六欄位模型＝「清單外沒有地方放」。
雙語（design.md §8.1）：prompt 必須明文要求用照片主要語言、不翻譯。
資料夾推薦（design1.md §8）：prompt 注入現有資料夾清單；clamp_category 把清單外的名稱夾成「未分類」。
"""

from datetime import date

from app.services.vlm_service import (
    PhotoUnderstanding,
    build_vlm_prompt,
    clamp_category,
    parse_content_time,
)

# 對應 design1.md §5 的預設六資料夾（這裡只列測試需要的欄位）
FOLDERS = [
    {"id": 1, "name": "未分類", "description": "不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。"},
    {"id": 2, "name": "收據", "description": "發票、消費憑證、購物明細。"},
    {"id": 3, "name": "飲食", "description": "食物、飲料、餐廳、菜單。"},
    {"id": 4, "name": "風景", "description": "戶外、旅遊、地點、景色。"},
    {"id": 5, "name": "文件", "description": "非收據的文字資料，例如名片、說明書。"},
    {"id": 6, "name": "其他", "description": "看懂是什麼，但不符合上面任何一個。"},
]

# 實體清單（Phase 30 起 build_vlm_prompt 要兩份清單）。
# 實體那一段本身的測試在 tests/unit/test_vlm_entity_unit.py，這裡只是把參數補齊。
ENTITIES = [{"id": 1, "name": "我的 MacBook", "description": "2023 年買的筆電"}]


def test_photo_understanding_只有九個欄位():
    # 清單外資訊沒有地方放（U3「清單外捨棄」在源頭的落實）。
    # Phase 30 從六欄變九欄：前六欄會落庫，後三欄（entity／task_*）只是建議。
    assert list(PhotoUnderstanding.model_fields) == [
        "understood", "text", "category", "location", "items", "content_time",
        "entity", "task_title", "task_due",
    ]


def test_build_vlm_prompt_含雙語規則():
    # design.md §8.1：描述用照片主要語言、不翻譯（雙語需求的來源，本 phase 不推翻）
    prompt = build_vlm_prompt(FOLDERS, ENTITIES)

    assert "照片內容本身的主要語言" in prompt
    assert "不要翻譯" in prompt


def test_build_vlm_prompt_含所有資料夾名稱與說明():
    """design1.md §8：清單是變數，使用者自建的資料夾也要出現在 prompt 裡。"""
    prompt = build_vlm_prompt(FOLDERS + [
        {"id": 7, "name": "專案X", "description": "跟課程作業有關的照片"},
    ], ENTITIES)

    for folder in FOLDERS:
        assert folder["name"] in prompt
        assert folder["description"] in prompt
    # 使用者後來新建的也要在
    assert "專案X" in prompt
    assert "跟課程作業有關的照片" in prompt


def test_build_vlm_prompt_明講只能從清單選且不可自創():
    """prompt 是第一道防線（第二道是 clamp_category）。措辭語意照 design1.md §8。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES)

    assert "現有資料夾" in prompt
    assert "禁止自創名稱" in prompt
    assert "不確定就填「未分類」" in prompt


def test_clamp_category_清單內就回清單裡的原文():
    assert clamp_category("收據", FOLDERS) == "收據"
    assert clamp_category("飲食", FOLDERS) == "飲食"


def test_clamp_category_大小寫混用也命中且回原文():
    """大小寫不敏感比對；回的是資料夾清單裡的原文，不是模型打的那個大小寫。"""
    folders = FOLDERS + [{"id": 7, "name": "Receipt", "description": "英文收據資料夾"}]

    assert clamp_category("receipt", folders) == "Receipt"
    assert clamp_category("RECEIPT", folders) == "Receipt"
    assert clamp_category("  Receipt  ", folders) == "Receipt"


def test_clamp_category_清單外一律變未分類():
    """design1.md §12：VLM 建議不在 list 內 → 後端改建議「未分類」。"""
    assert clamp_category("美食", FOLDERS) == "未分類"
    assert clamp_category("Receipt", FOLDERS) == "未分類"   # 清單裡只有中文「收據」
    assert clamp_category("", FOLDERS) == "未分類"


def test_clamp_category_沒填也變未分類():
    assert clamp_category(None, FOLDERS) == "未分類"


# ---- 以下四個是既有測試，原封不動保留 ----
def test_parse_content_time_解析ISO日期():
    assert parse_content_time("2026-08-10") == date(2026, 8, 10)


def test_parse_content_time_帶時間字尾只取日期():
    # VLM 偶爾會回 "2026-08-10T00:00:00" 之類，前 10 個字元就是日期
    assert parse_content_time("2026-08-10T00:00:00") == date(2026, 8, 10)


def test_parse_content_time_解析不出回None():
    # 內容時間本來就可空，解析失敗不得讓上傳失敗（design.md §8.1）
    assert parse_content_time("去年夏天") is None


def test_parse_content_time_空值回None():
    assert parse_content_time(None) is None
    assert parse_content_time("") is None
