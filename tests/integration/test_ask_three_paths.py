"""詢問三路：實體別針路與待辦路（design3.md D14、§6；Phase 34）。

原本的兩路（條件查詢／語意查詢）一字不動，本檔驗收的是新加的兩路：

① repository 兩條新查詢：`list_photos_with_entity`（沿別針列照片）、
   `search_tasks`（待辦，可帶「到期日在某天以前」的範圍）。
② 檢索層兩條新路：entity 路（實體名對不到就回空，交 LLM 回查無）、
   task 路（把待辦轉成 Document，且 metadata["id"] 是**來源照片 id**）。
③ workflow：路由四選一、`AskDeps` 帶著現有實體名單給 router 認名字。
④ 端點：`search_mode` 的新全名與 `retrieved_photo_ids`。

目標問句（design3.md §6 驗收用）：
  「跟我 MacBook 有關的全部」→ 沿別針找到照片，不靠文字碰運氣
  「這週要交什麼？」        → 待辦清單，不是猜照片描述

`自然語言詢問.feature` 一字未改：規格只認得既有兩種查法，
新查法只出現在本檔（總覽 §4 的裁決）。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.dependencies import get_router
from app.main import app
from app.repositories import photo_repository
from app.services.ask_workflow import AskDeps, RouteDecision, run_ask
from app.services.retrieval_service import (
    QueryFilters,
    entity_search,
    photo_retriever,
    task_search,
)
from tests.fakes import FakeAnswerLLM, FakeEmbeddings, FakeRouter

NOW = datetime(2026, 8, 18, 10, 0)
TODAY = NOW.date()


def _insert(text: str, *, category: str = "文件", location: str | None = None,
            items: list[str] | None = None,
            content_time: date | None = None) -> int:
    """直接寫一列照片（不走上傳流程，本檔不關心存檔），回傳 id。"""
    return photo_repository.insert_photo(
        text=text,
        category=category,
        location=location,
        items=items or [],
        content_time=content_time,
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=NOW,
    )["id"]


@pytest.fixture
def MacBook三張照片():
    """建一個實體，釘住其中兩張照片（中間那張刻意不釘）。

    回傳 (實體, 釘住的兩個 id, 沒釘的那個 id)。
    """
    entity = photo_repository.create_entity("我的 MacBook", "工作用的筆電")
    釘住甲 = _insert("MacBook 的保固卡")
    沒釘 = _insert("海邊的風景照", category="風景", location="海邊")
    釘住乙 = _insert("MacBook 的購買收據", category="收據", items=["筆電"])
    photo_repository.pin_entity(釘住甲, entity["id"])
    photo_repository.pin_entity(釘住乙, entity["id"])
    return entity, [釘住甲, 釘住乙], 沒釘


@pytest.fixture
def 三筆待辦():
    """三筆待辦：兩筆有到期日（八月廿、九月一）、一筆沒期限。"""
    近的 = _insert("課本上寫著 Project 2 的截止日")
    遠的 = _insert("繳費單，九月一號前要繳")
    沒期限的 = _insert("修水管的估價單")
    photo_repository.create_task(近的, title="交 Project 2", due_date=date(2026, 8, 20))
    photo_repository.create_task(遠的, title="繳費", due_date=date(2026, 9, 1))
    photo_repository.create_task(沒期限的, title="約師傅修水管", due_date=None)
    return 近的, 遠的, 沒期限的


# ---------------- ① repository：兩條新查詢 ----------------


def test_list_photos_with_entity_只回釘著的那些照片(MacBook三張照片):
    """實體路的重點：沿**別針**列照片，中間那張沒釘的不會混進來。"""
    entity, 釘住的, _沒釘 = MacBook三張照片

    rows = photo_repository.list_photos_with_entity(entity["id"])

    assert [row["id"] for row in rows] == 釘住的   # ORDER BY p.id


def test_list_photos_with_entity_欄位剛好餵得進檢索層(MacBook三張照片):
    """欄位形狀＝row_to_document 要的那六個，不多不少。

    少一個 row_to_document 就會 KeyError；多帶 embedding 則是白花頻寬
    （1024 個浮點數撈回來沒人用）。釘死它，日後有人改 SELECT 會馬上被抓到。
    """
    entity, 釘住的, _沒釘 = MacBook三張照片

    rows = photo_repository.list_photos_with_entity(entity["id"])

    assert set(rows[0]) == {
        "id", "text", "category", "location", "items", "content_time"
    }


def test_list_photos_with_entity_沒有任何別針回空清單():
    """剛自創、還沒釘上任何照片的實體：回空，不是報錯。"""
    entity = photo_repository.create_entity("Project 2", "這學期的專題")
    _insert("完全無關的照片")

    assert photo_repository.list_photos_with_entity(entity["id"]) == []


def test_search_tasks_不給範圍回全部且排序同list_tasks(三筆待辦):
    """due_before=None ＝「我有哪些待辦」，先到期的在前、沒期限的最後。"""
    rows = photo_repository.search_tasks(due_before=None)

    assert [row["title"] for row in rows] == ["交 Project 2", "繳費", "約師傅修水管"]


def test_search_tasks_給範圍只回該日以前到期的(三筆待辦):
    """「這週要交什麼」＝有期限且期限在範圍內；沒期限的**排除**。

    沒期限的那筆不是「最早到期」而是「這件事沒有 deadline」，
    問「這週要交什麼」時把它列出來只會製造假的急迫感。
    """
    rows = photo_repository.search_tasks(due_before=date(2026, 8, 25))

    assert [row["title"] for row in rows] == ["交 Project 2"]


def test_search_tasks_同到期日晚建立的在前():
    """三段排序的第二段（created_at DESC）也要被釘住，不能只測第一段。

    兩筆同一天到期：後建立的排前面。id DESC 是第三段保險（同一交易內
    created_at 可能相同），這裡兩次 create_task 各自成交易、時間戳必不同，
    所以這顆守的是 created_at 段；字串共用（TASK_ORDERING）讓第三段不會漂移。
    """
    先建的 = _insert("同一天到期的甲")
    後建的 = _insert("同一天到期的乙")
    photo_repository.create_task(先建的, title="甲", due_date=date(2026, 8, 25))
    photo_repository.create_task(後建的, title="乙", due_date=date(2026, 8, 25))

    rows = photo_repository.search_tasks(due_before=date(2026, 8, 25))

    assert [row["title"] for row in rows] == ["乙", "甲"]


def test_search_tasks_帶回來源照片的文字(三筆待辦):
    """待辦轉 Document 時要附上來源照片描述，所以查詢就得 JOIN photo 取 text。"""
    近的, _遠的, _沒期限的 = 三筆待辦

    rows = photo_repository.search_tasks(due_before=None)

    第一筆 = rows[0]
    assert set(第一筆) == {"id", "photo_id", "title", "due_date", "created_at", "text"}
    assert 第一筆["photo_id"] == 近的
    assert 第一筆["text"] == "課本上寫著 Project 2 的截止日"


# ---------------- ② 檢索層：兩條新路 ----------------


def test_entity_search_沿別針找到照片(MacBook三張照片):
    """Document 的 metadata 形狀與另外兩路一樣（同一個 row_to_document），
    但 page_content **第一行**換成釘選事實——理由見 entity_search 的 docstring
    （Ruling-9 修正：電費單的文字裡本來就不會提到「MacBook」，
    回答模型得看到「這張為什麼相關」才有材料誠實引用，不會誤判查無）。
    """
    _entity, 釘住的, _沒釘 = MacBook三張照片

    documents = entity_search("我的 MacBook")

    assert [doc.metadata["id"] for doc in documents] == 釘住的
    # 第一行是釘選事實：含實體名、且講明是「釘」上去的關聯
    first_line = documents[0].page_content.splitlines()[0]
    assert "我的 MacBook" in first_line
    assert "釘" in first_line
    # 第二行起是原內容，格式與寫入時一致（原本的第一行往後退一行，不多不少）
    assert documents[0].page_content.splitlines()[1] == "MacBook 的保固卡"


def test_entity_search_名稱大小寫與空白都不影響(MacBook三張照片):
    """沿用 find_entity_by_name 的 lower()＋trim()：問句寫 macbook 也對得到。"""
    _entity, 釘住的, _沒釘 = MacBook三張照片

    documents = entity_search("  我的 macbook  ")

    assert [doc.metadata["id"] for doc in documents] == 釘住的


@pytest.mark.parametrize("名字", [None, "從來沒建過的東西"])
def test_entity_search_對不到實體回空清單(名字, MacBook三張照片):
    """對不到就回空，讓 generate 節點交給 LLM 回「查無相關照片」。

    刻意**不** fallback 去做語意查詢：使用者指名了某件東西，
    硬塞幾張猜的照片比誠實說沒有更糟（design.md 鐵律 2「查無不虛構」）。
    """
    assert entity_search(名字) == []


def test_task_search_轉成Document且id是來源照片id(三筆待辦):
    """契約：retrieved_photo_ids 一律是**照片** id，待辦路也不例外。"""
    近的, 遠的, 沒期限的 = 三筆待辦

    documents = task_search(None, TODAY)

    assert [doc.metadata["id"] for doc in documents] == [近的, 遠的, 沒期限的]


def test_task_search_內容含標題到期日與來源照片描述(三筆待辦):
    documents = task_search(None, TODAY)

    assert documents[0].page_content == (
        "待辦：交 Project 2（到期 2026-08-20）\n"
        "來源照片：課本上寫著 Project 2 的截止日"
    )
    # 沒有到期日的那筆要寫「無」，不能印出 None
    assert documents[-1].page_content.startswith("待辦：約師傅修水管（到期 無）")


def test_task_search_限定天數只回範圍內的(三筆待辦):
    """「這週要交什麼」＝ due_within_days=7，從詢問當下（TODAY）往後算。"""
    近的, _遠的, _沒期限的 = 三筆待辦

    documents = task_search(7, TODAY)

    assert [doc.metadata["id"] for doc in documents] == [近的]


def test_task_search_零天只回今天到期的():
    """due_within_days=0（「今天要交什麼」）是合法邊界，不是「沒給範圍」。

    實作若把 is not None 寫成真假值判斷，0 會被當成 None 走「全部都回」——
    語意正好相反。這顆測試就是釘住那一行的。
    """
    今天到期 = _insert("今天要交的作業")
    三天後到期 = _insert("三天後的繳費單")
    photo_repository.create_task(今天到期, title="今天交", due_date=TODAY)
    photo_repository.create_task(三天後到期, title="三天後繳", due_date=date(2026, 8, 21))

    documents = task_search(0, TODAY)

    assert [doc.metadata["id"] for doc in documents] == [今天到期]


def test_自訂retriever也認得新的兩種模式(MacBook三張照片, 三筆待辦):
    """photo_retriever 是唯一的檢索入口，四種模式都要走得通。"""
    _entity, 釘住的, _沒釘 = MacBook三張照片
    近的, _遠的, _沒期限的 = 三筆待辦

    entity_result = photo_retriever.invoke({
        "question": "跟我 MacBook 有關的全部",
        "mode": "entity",
        "filters": QueryFilters(entity_name="我的 MacBook"),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })
    task_result = photo_retriever.invoke({
        "question": "這週要交什麼？",
        "mode": "task",
        "filters": QueryFilters(due_within_days=7),
        "today": TODAY,
        "embeddings": FakeEmbeddings(),
    })

    assert [doc.metadata["id"] for doc in entity_result] == 釘住的
    assert [doc.metadata["id"] for doc in task_result] == [近的]


# ---------------- ③ workflow：路由四選一 ----------------


@pytest.fixture
def deps() -> AskDeps:
    """詢問流程的假件組。entity_names ＝端點會從資料庫撈給 router 認名字的清單。"""
    return AskDeps(
        router=FakeRouter(),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=TODAY,
        entity_names=["我的 MacBook"],
    )


def test_實體問句走實體路(deps, MacBook三張照片):
    """design3.md §6 的目標問句一：不靠文字碰運氣，沿別針拿到照片。"""
    _entity, 釘住的, 沒釘 = MacBook三張照片

    state = run_ask("跟我 MacBook 有關的全部", deps)

    assert state["mode"] == "entity"
    assert state["filters"].entity_name == "我的 MacBook"
    assert [doc.metadata["id"] for doc in state["retrieved"]] == 釘住的
    assert 沒釘 not in [doc.metadata["id"] for doc in state["retrieved"]]


def test_英文實體問句也走實體路(deps, MacBook三張照片):
    """雙語：實體名單注入 prompt，所以英文問句也對得到中文命名的實體。"""
    _entity, 釘住的, _沒釘 = MacBook三張照片

    state = run_ask("Show me everything about my MacBook", deps)

    assert state["mode"] == "entity"
    assert [doc.metadata["id"] for doc in state["retrieved"]] == 釘住的
    assert state["answer"].startswith("Based on the photos")


def test_待辦問句走待辦路(deps, 三筆待辦):
    """design3.md §6 的目標問句二：查待辦表，不是猜照片描述。"""
    近的, _遠的, _沒期限的 = 三筆待辦

    state = run_ask("這週要交什麼？", deps)

    assert state["mode"] == "task"
    assert state["filters"].due_within_days == 7
    assert [doc.metadata["id"] for doc in state["retrieved"]] == [近的]
    assert "交 Project 2" in state["answer"]


def test_英文待辦問句也走待辦路(deps, 三筆待辦):
    近的, _遠的, _沒期限的 = 三筆待辦

    state = run_ask("What is due this week?", deps)

    assert state["mode"] == "task"
    assert [doc.metadata["id"] for doc in state["retrieved"]] == [近的]
    # 回答語言跟隨提問語言的鐵律，task 路也要守（與實體路那顆對稱）
    assert state["answer"].startswith("Based on the photos")


def test_沒講期限的待辦問句回全部(deps, 三筆待辦):
    """「我有哪些待辦」沒有時間範圍 → due_within_days 空 ＝ 全部（含沒期限的）。"""
    state = run_ask("我有哪些待辦？", deps)

    assert state["mode"] == "task"
    assert state["filters"].due_within_days is None
    assert len(state["retrieved"]) == 3


def test_路由拿得到現有實體名單(deps, MacBook三張照片):
    """實體名單要注入 prompt，LLM 才對得到名字（校準 2）。

    假件不會真的照名單思考，但會記下收到什麼——這裡驗的是「呼叫端真的傳了」。
    """
    run_ask("跟我 MacBook 有關的全部", deps)

    assert deps.router.last_entity_names == ["我的 MacBook"]


def test_實體對不到時查無不虛構(MacBook三張照片):
    """路由挑了一個資料庫裡沒有的名字：回空、由 LLM 說查無，不改走語意查詢。"""
    deps = AskDeps(
        router=FakeRouter({
            "跟我 iPad 有關的全部": RouteDecision(mode="entity", entity_name="我的 iPad")
        }),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=TODAY,
        entity_names=["我的 MacBook"],
    )

    state = run_ask("跟我 iPad 有關的全部", deps)

    assert state["mode"] == "entity"
    assert state["retrieved"] == []
    assert "查無相關照片" in state["answer"]


# ---------------- ④ 端點：POST /ask 的回應欄位 ----------------


@pytest.fixture
def 假路由(wire_fake_ai):
    """換上一顆「同一個實例」的 FakeRouter，測試才驗得到端點傳了什麼給它。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()——
    沿用 test_ask_endpoint.py 的既有慣例。
    """
    fake_router = FakeRouter()
    app.dependency_overrides[get_router] = lambda: fake_router
    yield fake_router


def test_端點實體問句的回應(client, 假路由, MacBook三張照片):
    _entity, 釘住的, _沒釘 = MacBook三張照片

    response = client.post("/ask", json={"question": "跟我 MacBook 有關的全部"})

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "entity pin search"
    assert body["retrieved_photo_ids"] == 釘住的


def test_端點待辦問句回的是來源照片id(client, 假路由, 三筆待辦):
    """契約不變：欄位叫 retrieved_photo_ids，待辦路回的也必須是照片 id。"""
    近的, _遠的, _沒期限的 = 三筆待辦

    response = client.post("/ask", json={"question": "這週要交什麼？"})

    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "task search"
    assert body["retrieved_photo_ids"] == [近的]
    assert "交 Project 2" in body["answer"]


def test_端點把資料庫裡的實體名單傳給路由(client, 假路由, MacBook三張照片):
    """端點負責撈名單（校準 2）；漏傳的話模型就永遠對不到自訂名字。"""
    photo_repository.create_entity("Project 2", "這學期的專題")

    client.post("/ask", json={"question": "跟我 MacBook 有關的全部"})

    assert 假路由.last_entity_names == ["我的 MacBook", "Project 2"]


def test_端點數不變(client):
    """本 phase 不加不減端點：詢問三路全部塞在既有的 POST /ask 裡（D14）。

    數字 14 → 17 是 Phase 36 無線鏡頭加的三支（`POST /camera/session`、
    `POST /camera/{token}/photos`、`GET /camera/{token}/latest`，phase-36 校準 1）；
    信令用的 WebSocket 依 FastAPI 的行為不會出現在 openapi.json，所以不計入。
    17 → 19 是 2026-08-22 AI 後端開關的兩支（GET／PUT `/settings/ai-backend`，
    產品負責人指示、未走 phase 計畫；見 test_ai_backend_switch.py）。
    19 → 20 是增量四 Phase 38 的 `GET /photos/{photo_id}`（design4.md D5）。
    20 → 22 是增量五 Phase 64 的兩支（`GET /ingest-jobs` ＋
    `POST /ingest-jobs/{job_id}/dismiss`，design5.md §5）——
    進度面板的資料來源與「關掉失敗列」；關掉刻意用 POST 不用 DELETE
    （design5.md §0 禁止事項第三條，openapi 仍然零 DELETE）。
    詢問這一路仍然一支都沒加——這顆測試守的是那件事，不是總數本身。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(path, method) for path, item in paths.items() for method in item]

    assert len(運算元) == 22
    assert [路徑 for 路徑, _ in 運算元 if 路徑.startswith("/ask")] == ["/ask"]
