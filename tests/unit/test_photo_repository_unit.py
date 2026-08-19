"""to_vector_literal 的單元測試：純函式，不碰資料庫。"""

from app.repositories.photo_repository import to_vector_literal


def test_to_vector_literal_formats_floats():
    assert to_vector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


def test_to_vector_literal_accepts_ints():
    assert to_vector_literal([1, 2]) == "[1.0,2.0]"
