"""vlm_service 的單元測試：純函式與資料模型，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U3「儲存結構化 metadata（四欄位；清單外資訊捨棄）」——六欄位模型＝「清單外沒有地方放」。
雙語（design.md §8.1）：VLM_PROMPT 必須明文要求用照片主要語言、不翻譯。
"""

from datetime import date

from app.services.vlm_service import VLM_PROMPT, PhotoUnderstanding, parse_content_time


def test_photo_understanding_只有六個欄位():
    # 清單外資訊沒有地方放（U3「清單外捨棄」在源頭的落實）
    assert list(PhotoUnderstanding.model_fields) == [
        "understood", "text", "category", "location", "items", "content_time",
    ]


def test_vlm_prompt_含雙語規則():
    # design.md §8.1：描述用照片主要語言、不翻譯（雙語需求的來源）
    assert "照片內容本身的主要語言" in VLM_PROMPT
    assert "不要翻譯" in VLM_PROMPT


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
