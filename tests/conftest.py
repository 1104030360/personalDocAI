"""pytest 共用設定：把資料庫指到測試庫，並在每個測試前清空 photo 表。"""

import os

# 一定要在 import app.* 之前設定：app/core/config.py 在 import 時讀環境變數，
# 而 load_dotenv() 不會覆蓋已存在的環境變數，所以這裡先寫入的測試庫 URL 會生效。
TEST_DATABASE_URL = "postgresql://localhost:5433/visual_memory_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402  （import 順序刻意如此，見上方註解）

from app.core import config  # noqa: E402

# 雙保險：即使 config 已被其他途徑先 import，也強制指向測試庫
config.DATABASE_URL = TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def clean_photo_table():
    """每個測試開始前清空 photo 表，確保測試彼此獨立。"""
    # 絕不清到正式庫：URL 必須含 visual_memory_test 才動手
    assert "visual_memory_test" in config.DATABASE_URL
    from app.repositories import photo_repository as repo

    repo.clear_photos()
    yield
