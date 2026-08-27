"""pytest 共用設定：把資料庫指到測試庫，並套上四道 autouse 安全網。

reset_tables          每測清空四張表＋重播六筆資料夾種子（絕不動正式庫）
wire_fake_ai          六個 AI 注入點全換假件＋固定時鐘（絕不打真 Ollama）
isolated_data_dir     DATA_DIR 指到 tmp_path（絕不寫專案的 data/）
wire_memory_job_store JobStore 指到每測獨立的記憶體實作（Depends 與直接
                      呼叫兩條路都攔；絕不連真 Redis）
"""

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

from app import dependencies  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_answerer,
    get_embeddings,
    get_entity_suggester,
    get_job_store,
    get_now,
    get_router,
    get_task_dispatcher,
    get_vlm,
)
from app.main import app  # noqa: E402
from app.services.ingest_job_store import InMemoryJobStore  # noqa: E402
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


@pytest.fixture(autouse=True)
def wire_memory_job_store(monkeypatch):
    """第四道安全網（Phase 57 建、Phase 65 加長）：JobStore 一律記憶體版，派工一律假的。

    pytest **絕不連真 Redis、絕不啟動 Celery**（design5.md §9、契約 §7 第 2 條）。
    本機開發時 Redis 容器常常開著，忘了覆寫就會默默把測試資料寫進去。

    三件事缺一不可：
    ① dependency_overrides → router 上 Depends(get_job_store) 的拿到記憶體版
       （Phase 57 原有的那一半，原封不動）
    ② monkeypatch dependencies.get_job_store → **直接呼叫**的地方也拿到同一顆
       （app/main.py 的 lifespan 掃把、app/celery_app.py 的 ingest_task 都不走 Depends）
    ③ 派工換成假的 → 不然 POST /photos 會真的 .delay() 出去撞 Redis。
       假件必須有 .dispatch() 方法（phase-62 的 TaskDispatcher Protocol；
       router 呼叫的是 dispatcher.dispatch(job_id)，塞裸函式會炸 AttributeError）。
       要跑任務的測試一律**自己**呼叫 run_ingest_job(...)（design5.md §9 的圖）。
    """
    store = InMemoryJobStore()
    dispatched: list[str] = []

    class 記帳假派工:
        """符合 TaskDispatcher Protocol 的最小假件：只把 job_id 記下來。"""

        def dispatch(self, job_id: str) -> None:
            dispatched.append(job_id)

    假派工 = 記帳假派工()

    app.dependency_overrides[get_job_store] = lambda: store
    monkeypatch.setattr(dependencies, "get_job_store", lambda: store)
    app.dependency_overrides[get_task_dispatcher] = lambda: 假派工
    monkeypatch.setattr(dependencies, "get_task_dispatcher", lambda: 假派工)

    # 要斷言「有沒有派工出去」的測試，把這個 fixture 寫進參數列、讀 store.dispatched
    store.dispatched = dispatched
    yield store
    app.dependency_overrides.pop(get_job_store, None)
    app.dependency_overrides.pop(get_task_dispatcher, None)


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


# ---------- 增量五 Phase 62：上傳改 202 之後的共用小工具 ----------
#
# 為什麼需要它們：上傳從「一次做完」變成「兩段」——HTTP 收下（202），
# worker 才真的入庫。測試沒有 worker，所以測試自己扮演 worker：
# 拿 202 給的 job_id，直接呼叫 run_ingest_job（design5.md §9、D15）。
# 這幾個工具把那串動作包起來，讓既有測試的改寫變成機械式的一行替換。
# （get_job_store 檔頭已 import，這裡不重覆。）

from app.repositories import photo_repository as _repo  # noqa: E402
from app.services.ingest_job import run_ingest_job  # noqa: E402
from tests.fakes import make_png_bytes  # noqa: E402


def 目前的任務清單():
    """拿到「router 現在真的在用」的那一份 JobStore。

    Phase 57 的 wire_memory_job_store 可能是用 dependency_overrides 換的，
    也可能是換掉模組層的實例——兩種寫法這個函式都拿得到同一份，
    所以測試不必知道它是怎麼接的。
    """
    factory = app.dependency_overrides.get(get_job_store, get_job_store)
    return factory()


def 目前注入的假件() -> dict:
    """把測試現在掛在 dependency_overrides 上的假件挖出來，交給 run_ingest_job。

    這是讓改寫變便宜的關鍵：既有測試那一行
        app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    **一個字都不必改**——它原本是給 router 用的，現在改成給任務用。

    注意 get_now 的取法不一樣：它的覆寫值本身就是 callable（FixedClock 實例），
    所以直接把那個物件交出去；get_vlm／get_embeddings 的覆寫值是「工廠」
    （lambda: FakeVLM(...)），要呼叫一次才拿得到物件。
    """
    assert get_vlm in app.dependency_overrides, (
        "conftest 的 wire_fake_ai 應該已經把 get_vlm 換成假件了——"
        "沒有的話這裡會去打真的 Ollama（pytest 絕不打真模型）"
    )
    return {
        "vlm": app.dependency_overrides[get_vlm](),
        "embeddings": app.dependency_overrides[get_embeddings](),
        "now": app.dependency_overrides[get_now],
    }


def 跑完任務(job_id: str) -> None:
    """測試扮演 worker：把某一個 job 就地跑完（design5.md §9）。

    用的假件就是測試自己掛上去的那幾份，所以「這次看圖看得懂嗎」「時鐘停在哪一天」
    完全由測試決定，與正式路徑的 worker 用同一個函式 run_ingest_job。
    """
    假件 = 目前注入的假件()
    run_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=假件["vlm"],
        embeddings=假件["embeddings"],
        now=假件["now"],
    )


def _收件箱照片ids() -> list[int]:
    """收件箱裡現在有哪些照片 id（新的在前）。"""
    inbox = next(f for f in _repo.list_folders() if f["is_inbox"])
    return [row["id"] for row in _repo.list_photos_in_folder(inbox["id"])]


def 上傳並跑完任務(
    client,
    *,
    payload: bytes | None = None,
    filename: str = "a.png",
    content_type: str = "image/png",
) -> dict:
    """POST /photos → 斷言 202 → 把那個任務跑完 → 回報結果。

    回傳一個字典，四個鍵：
      job_id    ：202 給的號碼牌
      response  ：POST 的原始回應（要驗 202 的 body 時用得到）
      job       ：跑完之後的任務狀態；**成功時是 None**（成功＝job 被刪掉）
      photo_ids ：這一次新進收件箱的照片 id（單圖一個、PDF 可能多個，由小到大）

    photo_ids 為什麼要用「前後比對」算出來，不是從 job 讀：
    契約備忘 §3.1 說「成功 ＝ delete(job_id)」，所以任務跑完之後那筆 job
    連同它的 photo_ids 一起消失了。改用「跑之前收件箱有誰、跑之後多了誰」，
    對單圖與 PDF 都成立，也不必為此新增任何 repository 函式。
    """
    if payload is None:
        payload = make_png_bytes()

    前 = set(_收件箱照片ids())
    response = client.post("/photos", files={"file": (filename, payload, content_type)})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    新增 = sorted(i for i in _收件箱照片ids() if i not in 前)
    return {
        "job_id": job_id,
        "response": response,
        "job": 目前的任務清單().get(job_id),
        "photo_ids": 新增,
    }


def 上傳一張並取回照片(client, **kwargs) -> dict:
    """單圖捷徑：上傳並跑完任務之後，直接把資料庫那一列回來。

    回的就是 photo_repository.fetch_photo() 的那個 dict，所以既有測試裡的
    `body["id"]` 一個字都不必改；`body["metadata"]["category"]` 這種
    「201 回應才有的巢狀形狀」則要改成 `列["category"]`（見 phase 文件 §4.6）。
    """
    結果 = 上傳並跑完任務(client, **kwargs)
    assert len(結果["photo_ids"]) == 1, (
        f"這個捷徑只給單圖用，這次進了 {len(結果['photo_ids'])} 張——PDF 請改用 上傳並跑完任務()"
    )
    return _repo.fetch_photo(結果["photo_ids"][0])
