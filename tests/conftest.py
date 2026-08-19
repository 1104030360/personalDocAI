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


# ---------- Phase 5 追加：假件安全網＋API 測試用戶端 ----------
# （import 必須留在 DATABASE_URL 導向之後，理由同檔案開頭註解）
from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import get_vlm  # noqa: E402
from app.main import app  # noqa: E402
from tests.fakes import FakeVLM  # noqa: E402


@pytest.fixture(autouse=True)
def wire_fake_ai():
    """安全網：每個測試預設把看圖換成「看不懂」假件，結束時清掉所有覆寫。

    本機 Ollama 是真的在跑（gemma4）——測試忘記覆寫 get_vlm 時，
    寧可拿到可預期的 422，也絕不讓 pytest 默默打真模型。
    需要「看得懂」的測試自行覆寫 get_vlm。
    （Phase 6 會在這裡再加 get_embeddings／get_now 的假件。）
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    """可以直接呼叫自己 API 的測試用戶端（不需要真的啟動伺服器）。"""
    with TestClient(app) as test_client:
        yield test_client
