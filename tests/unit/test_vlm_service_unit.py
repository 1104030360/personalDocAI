"""vlm_service 的單元測試：純函式與資料模型，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U3「儲存結構化 metadata（四欄位；清單外資訊捨棄）」——六欄位模型＝「清單外沒有地方放」。
雙語（design.md §8.1）：prompt 必須明文要求用照片主要語言、不翻譯。
資料夾推薦（design1.md §8）：prompt 注入現有資料夾清單；clamp_category 把清單外的名稱夾成「未分類」。
"""

from datetime import date

import pytest

from app.core import config
from app.services.ollama_cloud import extract_json_object
from app.services.vlm_service import (
    CLOUD_JSON_INSTRUCTION,
    OllamaCloudVLM,
    PhotoUnderstanding,
    build_vlm_prompt,
    clamp_category,
    parse_content_time,
)
from tests.fakes import FakeCloudChat

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

# 糾錯例子（Phase 35 起 build_vlm_prompt 要第三份清單）。
# 三鍵就是 photo_repository.recent_corrections() 回傳的形狀。
CORRECTIONS = [
    {"suggested": "收據", "chosen": "飲食", "photo_text": "餐廳菜單的照片"},
    {"suggested": "文件", "chosen": "其他", "photo_text": "說明書封面"},
]


def test_photo_understanding_只有九個欄位():
    # 清單外資訊沒有地方放（U3「清單外捨棄」在源頭的落實）。
    # Phase 30 從六欄變九欄：前六欄會落庫，後三欄（entity／task_*）只是建議。
    assert list(PhotoUnderstanding.model_fields) == [
        "understood", "text", "category", "location", "items", "content_time",
        "entity", "task_title", "task_due",
    ]


def test_build_vlm_prompt_含雙語規則():
    # design.md §8.1：描述用照片主要語言、不翻譯（雙語需求的來源，本 phase 不推翻）
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "照片內容本身的主要語言" in prompt
    assert "不要翻譯" in prompt


def test_build_vlm_prompt_含所有資料夾名稱與說明():
    """design1.md §8：清單是變數，使用者自建的資料夾也要出現在 prompt 裡。"""
    prompt = build_vlm_prompt(FOLDERS + [
        {"id": 7, "name": "專案X", "description": "跟課程作業有關的照片"},
    ], ENTITIES, [])

    for folder in FOLDERS:
        assert folder["name"] in prompt
        assert folder["description"] in prompt
    # 使用者後來新建的也要在
    assert "專案X" in prompt
    assert "跟課程作業有關的照片" in prompt


def test_build_vlm_prompt_明講只能從清單選且不可自創():
    """prompt 是第一道防線（第二道是 clamp_category）。措辭語意照 design1.md §8。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "現有資料夾" in prompt
    assert "禁止自創名稱" in prompt
    assert "不確定就填「未分類」" in prompt


# ---- 糾錯 few-shot（Phase 35、design3.md D11）----
def test_build_vlm_prompt_注入糾錯例子():
    """記住「你猜 A、正確是 B」，下一次看圖就把這些例子擺在模型眼前。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, CORRECTIONS)

    assert "最近的人工糾正" in prompt
    assert "「餐廳菜單的照片」你猜「收據」、正確是「飲食」" in prompt
    assert "「說明書封面」你猜「文件」、正確是「其他」" in prompt

    # 渲染順序＝清單順序：recent_corrections() 已保證「新的在前」，
    # build_vlm_prompt 只管照順序輸出，不能自己重排（CORRECTIONS[0] 要比 [1] 先出現）。
    索引_餐廳菜單 = prompt.index("「餐廳菜單的照片」你猜「收據」、正確是「飲食」")
    索引_說明書封面 = prompt.index("「說明書封面」你猜「文件」、正確是「其他」")
    assert 索引_餐廳菜單 < 索引_說明書封面, "corrections[0]（新的）必須排在 corrections[1]（舊的）前面"


def test_build_vlm_prompt_沒有糾錯時那一段整段不出現():
    """空清單＝prompt 與 Phase 35 之前逐字相同（接縫處也不可以多出空行）。"""
    prompt = build_vlm_prompt(FOLDERS, ENTITIES, [])

    assert "人工糾正" not in prompt
    # 接縫：資料夾規則與「現有實體」之間本來就只隔一個空行，不能因為多了一段而變樣
    assert "不確定就填「未分類」。不要翻譯成英文。\n\n現有實體" in prompt


def test_build_vlm_prompt_糾錯例子的照片描述過長時只節錄():
    """few-shot 是提示不是全文——題幹太長只會稀釋掉真正要學的「A→B」。"""
    長描述 = "很" * 200

    prompt = build_vlm_prompt(
        FOLDERS,
        ENTITIES,
        [{"suggested": "收據", "chosen": "飲食", "photo_text": 長描述}],
    )

    assert 長描述 not in prompt
    assert "很" * 60 + "…" in prompt


def test_build_vlm_prompt_糾錯例子換行會被摺成單行():
    """photo_text 含換行時，整條例子不能被撐成多行。

    few-shot 的一條例子＝一行「你猜 A、正確是 B」；換行若原樣保留，
    會讓模型把換行後的內容讀成獨立的一行指令，破壞條列結構。
    """
    多行描述 = "餐廳菜單\n主餐區\n甜點區"

    prompt = build_vlm_prompt(
        FOLDERS,
        ENTITIES,
        [{"suggested": "收據", "chosen": "飲食", "photo_text": 多行描述}],
    )

    # 換行被摺成空白，例子仍是單行完整字串
    assert "「餐廳菜單 主餐區 甜點區」你猜「收據」、正確是「飲食」" in prompt
    # 帶原始換行的版本不該出現在 prompt 裡
    assert 多行描述 not in prompt


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


# ---- 雲端看圖的輸出解析（2026-08-22 AI 後端開關；真雲端煙霧的回歸）----
#
# ollama.com 對 format= 不見得強制（gemma4 實測回了 markdown 條列），
# 所以雲端路徑靠 prompt 尾端指令＋寬鬆抽取。這裡用 FakeCloudChat 練——
# 一樣不碰網路（OllamaCloudVLM 的建構子只組物件，真正連線的是 chat()）。


@pytest.fixture(autouse=True)
def 雲端假key(monkeypatch):
    """雲端類別建構時拿 config.OLLAMA_API_KEY 組 HTTP header：
    蓋成固定 ASCII 假值，測試不因開發機 .env 有沒有填真 key 而變色。"""
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")


def _雲端看圖(content: str | None) -> tuple[PhotoUnderstanding, FakeCloudChat]:
    vlm = OllamaCloudVLM(model="gemma4")
    fake = FakeCloudChat(content)
    vlm._client = fake
    result = vlm.understand(b"png bytes", "image/png", FOLDERS, ENTITIES, [])
    return result, fake


def test_extract_json_object_純JSON原樣通過():
    assert extract_json_object('{"a": 1}') == '{"a": 1}'


def test_extract_json_object_剝掉圍欄與前後贅字():
    回覆 = '好的，以下是結果：\n```json\n{"understood": true}\n```\n希望有幫助！'
    assert extract_json_object(回覆) == '{"understood": true}'


def test_extract_json_object_沒有大括號就原樣回傳():
    # 讓 Pydantic 的錯誤訊息照實說「這不是 JSON」，不要假裝撈到了什麼
    assert extract_json_object("- understood：true") == "- understood：true"


def test_雲端回覆包著圍欄也解析得出來():
    result, fake = _雲端看圖('```json\n{"understood": true, "text": "一張收據"}\n```')

    assert result.understood is True
    assert result.text == "一張收據"
    assert len(fake.calls) == 1
    # 送出去的內容＝共用 prompt＋雲端的「只准回 JSON」指令（共用段逐字不動）
    content = fake.calls[0]["messages"][0]["content"]
    assert content == build_vlm_prompt(FOLDERS, ENTITIES, []) + CLOUD_JSON_INSTRUCTION


def test_雲端回覆是條列時重試一次後視為看不懂():
    """2026-08-22 真雲端煙霧的原始症狀：markdown 條列 → 兩試皆敗 → 422 不儲存。"""
    result, fake = _雲端看圖("- understood：true\n- text：一張收據")

    assert result.understood is False
    assert len(fake.calls) == 2  # 與本機同一套節奏：失敗就再試一次


def test_雲端回覆是None也視為看不懂不炸例外():
    result, _ = _雲端看圖(None)

    assert result.understood is False
