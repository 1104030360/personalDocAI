"""pytest 共用設定：把資料庫指到測試庫，每個測試前清空兩張表並重播預設資料夾。"""

import os

# 一定要在 import app.* 之前設定：app/core/config.py 在 import 時讀環境變數，
# 而 load_dotenv() 不會覆蓋已存在的環境變數，所以這裡先寫入的測試庫 URL 會生效。
TEST_DATABASE_URL = "postgresql://postgres@localhost:5433/PersonalDocAI_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402  （import 順序刻意如此，見上方註解）

from app.core import config  # noqa: E402

# 雙保險：即使 config 已被其他途徑先 import，也強制指向測試庫
config.DATABASE_URL = TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def reset_tables():
    """每個測試開始前清空 photo 與 folder 兩張表，並重播六筆預設資料夾。

    重播是必要的：folder 被 TRUNCATE ... RESTART IDENTITY 清掉後 id 會歸零，
    每個測試因此都拿到一模一樣的 1〜6 六筆資料夾，測試彼此獨立又可預測。
    """
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手
    assert "PersonalDocAI_test" in config.DATABASE_URL
    from app.repositories import photo_repository as repo

    repo.reset_folders_and_photos()
    yield


# ---------- Phase 5 追加、Phase 6 擴充：假件安全網＋API 測試用戶端 ----------
# （import 必須留在 DATABASE_URL 導向之後，理由同檔案開頭註解）
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import (  # noqa: E402
    get_answerer,
    get_embeddings,
    get_entity_suggester,
    get_now,
    get_router,
    get_vlm,
)
from app.main import app  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeAnswerLLM,
    FakeEmbeddings,
    FakeEntitySuggester,
    FakeRouter,
    FakeVLM,
    FixedClock,
)


@pytest.fixture(autouse=True)
def wire_fake_ai():
    """安全網：每個測試預設接上假 AI 與固定時鐘，結束時清掉所有覆寫。

    本機 Ollama 是真的在跑——pytest 絕不能默默打真模型（design.md §11：
    全部測試不依賴任何外部服務）。六個注入點全部都要接上假件，
    需要不同行為的測試自行覆寫：
    - get_vlm 預設「看不懂」假件（要看得懂就覆寫成 FakeVLM(某理解結果)）
    - get_embeddings 預設 FakeEmbeddings（決定論向量）
    - get_now 預設固定時鐘 2026-08-18 10:00（對應規格 Given 的現在時間）
    - get_router 預設 FakeRouter（照登記的問題回查法，沒登記就丟例外模擬無法判斷）
    - get_answerer 預設 FakeAnswerLLM（拿檢索結果模板化回答，不呼叫真 LLM）
    - get_entity_suggester 預設 FakeEntitySuggester（預設誰都不挑，最保守的答案）
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM()
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings()
    app.dependency_overrides[get_now] = FixedClock(datetime(2026, 8, 18, 10, 0))
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_answerer] = lambda: FakeAnswerLLM()
    app.dependency_overrides[get_entity_suggester] = lambda: FakeEntitySuggester()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """安全網：pytest 永遠不把照片檔寫進專案的 data/。

    把 config.DATA_DIR 指到 pytest 給的暫存資料夾（每個測試一個、測完自動清）。
    storage_service 的每個函式都是在呼叫當下才讀 config.DATA_DIR，所以這裡改了就生效。

    這條安全網的精神與 wire_fake_ai（絕不打真 Ollama）、reset_tables（絕不動正式庫）
    完全一樣：危險的預設值由 conftest 統一擋掉，不靠個別測試自律。

    回傳暫存的資料根目錄，需要直接檢查檔案的測試可以把它寫進參數列取用。
    """
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    yield data_dir


def pytest_bdd_apply_tag(tag, function):
    """規格裡標 @未實作 的例子先跳過，等對應 phase 落地再摘標。"""
    if tag == "未實作":
        marker = pytest.mark.skip(reason="規格已寫、對應 phase 尚未實作")
        marker(function)
        return True
    return None


@pytest.fixture
def client() -> TestClient:
    """可以直接呼叫自己 API 的測試用戶端（不需要真的啟動伺服器）。"""
    with TestClient(app) as test_client:
        yield test_client


# ---------- Phase 7 追加：Gherkin 表格小工具（P12 詢問驗收也會用） ----------


def first_row(datatable: list[list[str]]) -> dict[str, str]:
    """把 Gherkin 表格的第一列資料轉成字典（第 0 列是欄位名）。"""
    header, *rows = datatable
    return dict(zip(header, rows[0]))


def split_items(cell: str) -> list[str]:
    """規格表格用「、」分隔多個物品，例如「可樂、洋芋片」。"""
    cell = cell.strip()
    return [part for part in cell.split("、") if part] if cell else []
