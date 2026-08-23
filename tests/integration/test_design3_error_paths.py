"""增量三（design3.md）錯誤與邊界總表的逐列驗證（Phase 37 收尾）。

對照表在 `docs/plan/unfinish/phase-37-增量三錯誤收尾與全量回歸.md`
的「錯誤表草案」（16 列）。已經被 Phase 28〜36 的測試覆蓋的列**不在這裡重寫**——
本檔只補那些「行為早就對了、只是沒有測試釘住」的缺口，體例沿用 Phase 25 的
`test_folder_error_paths.py`：每一段開頭標明對應錯誤表的哪一列。

本檔補的缺口（其餘各列由既有測試把關，對照表見該 phase 的報告）：

| 列 | 缺口 | 本檔的測試 |
|---|---|---|
| 1 | 壞 PDF 的另一半：**零頁** PDF | ① |
| 5 | 409 的**最後防線**（資料庫 UNIQUE／主鍵）本身 | ② |
| 7 | 再建議時 **LLM 真的爆炸** → 回 None 不往外丟 | ③ |
| 9 | 實體／待辦**寫入失敗** → 500 不吞錯、資料庫零半套 | ④ |
| 11 | 待辦問句但**一筆待辦都沒有** → 查無不虛構 | ⑤ |
| 13/15 | 鏡頭 token 失效的兩種剩餘組合（過期／被汰舊） | ⑥ |
| 16 | 「無刪除端點」改用 **openapi** 掃（既有那顆掃原始碼） | ⑦ |
| — | 收尾清單的「SQL 只在 repository」掃碼 | ⑦ |
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime
from pathlib import Path

import psycopg
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import get_entity_suggester, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import camera_session_service as sessions
from app.services import entity_suggestion_service
from app.services.ask_workflow import AskDeps, RouteDecision, run_ask
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import (
    FakeAnswerLLM,
    FakeEmbeddings,
    FakeEntitySuggester,
    FakeRouter,
    FakeVLM,
    make_jpeg_bytes,
    make_png_bytes,
)

專案根目錄 = Path(__file__).resolve().parents[2]

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。

    （與 test_folder_error_paths.py 的同名 fixture 用意相同。）
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def 上傳一張(client) -> dict:
    """上傳一張成功的照片，回傳 201 的 JSON body。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案。conftest 已把它指到本測試專屬的臨時目錄。"""
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


# ---- ① 錯誤表第 1 列：壞 PDF／零頁 → 422 什麼都不存 ----


def make_zero_page_pdf_bytes() -> bytes:
    """產一份**真的零頁**的 PDF（用 pypdfium2 自己的寫入器建空文件再存出來）。

    不用手工拼 PDF 語法：手拼的檔案 PDFium 會當成壞檔，那就變成在測「壞檔」
    （既有的 test_壞PDF回422不存任何資料 已經測過那一半）。
    """
    document = pdfium.PdfDocument.new()
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_零頁PDF回422且什麼都不存(client):
    """錯誤表第 1 列的另一半：「壞檔」已有測試，這裡補「零頁」。

    收尾行為與壞檔完全一樣——422、資料庫零列、DATA_DIR 零檔案。
    （實作上這兩種情況都收斂成 pdf_service.PdfUnreadableError，所以訊息也共用。）
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = client.post(
        "/photos",
        files={"file": ("empty.pdf", make_zero_page_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 422, response.text
    assert photo_repository.count_photos() == 0
    assert data_dir底下的檔案() == []


# ---- ② 錯誤表第 5 列：409 背後的「最後防線」＝資料庫約束本身 ----
#
# router 先擋成 409 這一半，Phase 30 的 test_pin_entity.py 已經測過
# （test_自創名稱與現有實體重複回409、test_重複釘同一個實體回409）。
# 這裡補的是「萬一有人把 router 的檢查拿掉」時，資料庫還擋不擋得住。


def _一張照片() -> int:
    """直接寫一列照片（本段不關心上傳流程），回傳 id。"""
    return photo_repository.insert_photo(
        text="測試用的照片",
        category="未分類",
        location=None,
        items=[],
        content_time=None,
        embedding=FakeEmbeddings().embed_query("測試用的照片"),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )["id"]


def test_重複釘同一個實體的最後防線是photo_entity主鍵():
    """PK(photo_id, entity_id)：繞過 router 直接釘第二次，資料庫要擋下來。"""
    photo_id = _一張照片()
    entity = photo_repository.create_entity("我的 MacBook", "筆電")
    photo_repository.pin_entity(photo_id, entity["id"])

    with pytest.raises(psycopg.errors.UniqueViolation):
        photo_repository.pin_entity(photo_id, entity["id"])

    assert len(photo_repository.list_photo_entities(photo_id)) == 1


def test_實體同名的最後防線是entity的UNIQUE():
    """entity.name UNIQUE：繞過 router 直接建同名實體，資料庫要擋下來。

    ⚠ 資料庫這一關是**區分大小寫**的（UNIQUE 比的是原文）——
    「我的 macbook」與「我的 MacBook」在資料庫眼中是兩筆。
    大小寫不敏感是 router 用 find_entity_by_name（lower()）多加的那一層，
    由 test_pin_entity.py::test_自創名稱與現有實體重複回409 把關。
    """
    photo_repository.create_entity("我的 MacBook", "筆電")

    with pytest.raises(psycopg.errors.UniqueViolation):
        photo_repository.create_entity("我的 MacBook", "另一台")

    assert len(photo_repository.list_entities()) == 1


def test_一張照片第二筆待辦的最後防線是task的UNIQUE():
    """task.photo_id UNIQUE：繞過 router 直接建第二筆，資料庫要擋下來。"""
    photo_id = _一張照片()
    photo_repository.create_task(photo_id, title="交 Project 2", due_date=None)

    with pytest.raises(psycopg.errors.UniqueViolation):
        photo_repository.create_task(photo_id, title="又一件事", due_date=None)


# ---- ③ 錯誤表第 7 列：再建議時 LLM 失敗 → 回 None 不 500（log warning）----
#
# 「候選為空不呼叫模型」「模型挑了清單外的名字被夾成 None」Phase 30 已測；
# 這裡補真正的失敗路徑：**模型呼叫本身爆炸**。守門的 try/except 寫在
# OllamaEntitySuggester.pick 裡（正式路徑唯一的實作），所以直接對它測。


class 會爆炸的模型:
    """invoke 一律丟例外——模擬 Ollama 沒開／連線逾時。"""

    def invoke(self, messages):
        raise RuntimeError("Ollama 沒有回應")


class 回垃圾的模型:
    """結構化輸出解析失敗時，langchain 可能回一個不是 EntityPick 的東西。"""

    def invoke(self, messages):
        return {"這不是": "EntityPick"}


def _建一個不連線的建議器() -> entity_suggestion_service.OllamaEntitySuggester:
    """建立正式的建議器物件。

    建構子只是把 ChatOllama 組起來，**不會連線**（真正發出請求的是 invoke），
    而下一行就會把 _model 換掉，所以這顆測試不依賴 Ollama 有沒有在跑。
    """
    return entity_suggestion_service.OllamaEntitySuggester()


def test_再建議時模型爆炸只回None並留下警告(caplog):
    """建議可有可無：失敗就這次不給建議，不可以讓整個請求變成 500。

    但一定要留 log——不然「Ollama 沒開」會無聲變成「AI 覺得都不像」。
    """
    suggester = _建一個不連線的建議器()
    suggester._model = 會爆炸的模型()
    photo = {
        "text": "MacBook 的維修發票", "category": "收據", "location": "Apple",
        "items": ["筆電"], "content_time": date(2026, 8, 10),
    }

    with caplog.at_level(logging.WARNING):
        結果 = suggester.pick(photo, [{"name": "我的 MacBook", "description": "筆電"}])

    assert 結果 is None
    assert "實體建議呼叫失敗" in caplog.text


def test_再建議時模型回傳非結構化結果也只回None(caplog):
    """挑不出來與挑壞了都一樣：回 None，讓彈窗只剩②③④三個出口。"""
    suggester = _建一個不連線的建議器()
    suggester._model = 回垃圾的模型()
    photo = {
        "text": "MacBook 的維修發票", "category": "收據", "location": None,
        "items": [], "content_time": None,
    }

    with caplog.at_level(logging.WARNING):
        結果 = suggester.pick(photo, [{"name": "我的 MacBook", "description": "筆電"}])

    assert 結果 is None
    assert "未回傳有效的結構化結果" in caplog.text


def test_建議器整條掛掉時端點照樣回200與null(client):
    """端點視角：拿不到建議是**正常結果**（200＋null），不是錯誤。"""
    photo_repository.create_entity("我的 MacBook", "筆電")
    body = 上傳一張(client)
    # FakeEntitySuggester 預設誰都不挑，正好等於「模型失敗後回 None」的下場
    app.dependency_overrides[get_entity_suggester] = lambda: FakeEntitySuggester(None)

    response = client.post(
        f"/photos/{body['id']}/entity-suggestion", json={"exclude": []}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"suggested_entity": None}


# ---- ④ 錯誤表第 9 列：實體／待辦寫入失敗 → 500 不吞錯、資料庫零半套狀態 ----


def _讓它爆炸(*args, **kwargs):
    raise RuntimeError("資料庫在寫入途中掛掉")


def test_釘現有實體時寫入失敗回500且完全沒留下連結(不擲出例外的client, monkeypatch):
    """釘現有＝單一 INSERT：失敗就什麼都沒寫，天然沒有半套狀態。"""
    body = 上傳一張(不擲出例外的client)
    photo_id = body["id"]
    entity = photo_repository.create_entity("我的 MacBook", "筆電")
    monkeypatch.setattr(photo_repository, "pin_entity", _讓它爆炸)

    response = 不擲出例外的client.post(
        f"/photos/{photo_id}/entities", json={"entity_id": entity["id"]}
    )

    assert response.status_code == 500, "寫入失敗不可以被吞掉"
    assert photo_repository.list_photo_entities(photo_id) == []
    assert len(photo_repository.list_entities()) == 1, "現有實體不可以被動到"


def test_自創實體與釘選是同一個交易_釘不上就連實體都不會留下():
    """★ 首跑紅的那一顆（詳見 Phase 37 報告）：自創路徑原本會留下半套狀態。

    自創＝「建實體」＋「釘上去」兩筆寫入。原本是兩次 repository 呼叫、
    兩條各自的連線，第二筆失敗時第一筆已經 commit——留下一個沒釘上的空實體，
    使用者重試同名會撞 409「實體名稱已存在」，走進死路
    （＝Phase 21「500 時不可以留下空資料夾」的同一條規則）。
    修法是把兩筆寫入放進 create_and_pin_entity 的**同一個交易**。

    這裡刻意用**真的資料庫錯誤**來驗（釘到一個不存在的照片 → photo_entity 外鍵違反），
    不是把函式換成假件——只有真的 rollback 才擋得住「連線在中途掛掉」這種現實情況。
    """
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        photo_repository.create_and_pin_entity(
            999999, name="我的 MacBook", description="不該被建出來"
        )

    assert photo_repository.find_entity_by_name("我的 MacBook") is None, (
        "釘不上去時連實體都不該留下（兩筆寫入必須同生共死）"
    )
    assert photo_repository.list_entities() == []


def test_自創實體時寫入失敗回500且什麼都沒留下(不擲出例外的client, monkeypatch):
    """端點視角：那一次原子寫入若整個失敗，500 不吞錯、資料庫零殘留。"""
    body = 上傳一張(不擲出例外的client)
    photo_id = body["id"]
    monkeypatch.setattr(photo_repository, "create_and_pin_entity", _讓它爆炸)

    response = 不擲出例外的client.post(
        f"/photos/{photo_id}/entities",
        json={"name": "我的 MacBook", "description": "不該被建出來"},
    )

    assert response.status_code == 500, "寫入失敗不可以被吞掉"
    assert photo_repository.find_entity_by_name("我的 MacBook") is None
    assert photo_repository.list_photo_entities(photo_id) == []


def test_待辦寫入失敗回500且沒有半筆待辦(不擲出例外的client, monkeypatch):
    """待辦＝單一 INSERT：失敗就什麼都沒寫。"""
    body = 上傳一張(不擲出例外的client)
    photo_id = body["id"]
    monkeypatch.setattr(photo_repository, "create_task", _讓它爆炸)

    response = 不擲出例外的client.post(
        f"/photos/{photo_id}/task", json={"title": "交 Project 2"}
    )

    assert response.status_code == 500, "寫入失敗不可以被吞掉"
    assert photo_repository.get_task_by_photo(photo_id) is None
    assert photo_repository.list_tasks() == []


# ---- ⑤ 錯誤表第 11 列：待辦問句但一筆待辦都沒有 → 查無句式、不虛構 ----


def test_待辦問句但一筆待辦都沒有時查無不虛構():
    """「實體名對不到」那一列 Phase 34 已測；這裡補待辦路的空手而回。

    重點是**不改走語意查詢**：mode 仍然是 task、檢索結果是空的，
    由 generate 節點交給 LLM 說「查無」（design.md 鐵律：查無不虛構）。
    """
    photo_repository.create_task(_一張照片(), title="這筆待會被清掉", due_date=None)
    photo_repository.reset_folders_and_photos()   # 照片沒了，待辦被 CASCADE 一起帶走

    deps = AskDeps(
        router=FakeRouter(
            {"這週要交什麼？": RouteDecision(mode="task", due_within_days=7)}
        ),
        answerer=FakeAnswerLLM(),
        embeddings=FakeEmbeddings(),
        today=date(2026, 8, 18),
    )

    state = run_ask("這週要交什麼？", deps)

    assert state["mode"] == "task"
    assert state["retrieved"] == []
    assert "查無相關照片" in state["answer"]


# ---- ⑥ 錯誤表第 13／15 列：鏡頭 token 失效的剩餘組合 ----
#
# 兩支帶 token 的 HTTP 端點 ×（亂 token／過期／被新配對汰舊）＝六格。
# Phase 36 已測四格（亂 token 兩支、過期上傳、汰舊 latest），這裡補剩下兩格。


def 拍一張(client, token: str):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    return client.post(
        f"/camera/{token}/photos",
        files={"file": ("shot.jpg", make_jpeg_bytes(), "image/jpeg")},
    )


def test_過期的token也拿不到latest(client, monkeypatch):
    """第 13 列：過期 token 打 GET /camera/{token}/latest 也是 404。"""
    token = client.post("/camera/session").json()["token"]
    assert 拍一張(client, token).status_code == 201
    assert client.get(f"/camera/{token}/latest").status_code == 200

    現在 = sessions._now()
    monkeypatch.setattr(sessions, "_now", lambda: 現在 + sessions.TOKEN_TTL_SECONDS + 1)

    assert client.get(f"/camera/{token}/latest").status_code == 404


def test_被汰舊的token也不能上傳照片(client):
    """第 15 列：同時只有一組配對，舊 token 立刻變陌生人（上傳這一支也是 404）。"""
    舊token = client.post("/camera/session").json()["token"]
    client.post("/camera/session")

    assert 拍一張(client, 舊token).status_code == 404
    assert photo_repository.count_photos() == 0


# ---- ⑦ 錯誤表第 16 列＋收尾掃碼：無刪除端點、SQL 只在 repository ----


def test_openapi裡沒有任何DELETE動詞(client):
    """design3 §3「不做刪除」：從**對外介面**證明，不是只看原始碼。

    既有的 test_folder_error_paths.py::test_沒有任何刪除端點 掃的是 router 原始碼
    （擋「有人寫了 @router.delete」）；這一顆掃的是實際產生的 openapi.json
    （擋「用別的寫法掛上了 DELETE 路由」）。兩顆守的是同一條規則的兩面。
    """
    paths = client.get("/openapi.json").json()["paths"]

    有delete的路徑 = [路徑 for 路徑, item in paths.items() if "delete" in item]
    assert 有delete的路徑 == [], f"本專案不做刪除 API：{有delete的路徑}"


# 唯二可以碰資料庫連線／SQL 的檔案（design.md 分層：repository 是唯一寫 SQL 的地方）
可以碰資料庫的檔案 = {
    "app/repositories/photo_repository.py",   # 全系統唯一寫 SQL 的地方
    "app/db/session.py",                      # 全系統唯一呼叫 psycopg.connect 的地方
}

# 只要出現這些字，就代表這個檔案自己在開連線或送 SQL
資料庫關鍵字 = ("psycopg", "get_connection", "cursor(", ".execute(")


def test_SQL只出現在repository與db層():
    """收尾掃碼：router／service／schema 一律零 SQL、零資料庫連線。

    順帶把兩個增量三的規則一起釘住：
    - 無線鏡頭的 token **不落資料庫**（camera_session_service 全在記憶體）
    - 實體不是第二套資料夾（entities router 只呼叫 repository，不自己寫 SQL）
    """
    違規: list[str] = []
    for 檔案 in sorted((專案根目錄 / "app").rglob("*.py")):
        相對路徑 = 檔案.relative_to(專案根目錄).as_posix()
        if 相對路徑 in 可以碰資料庫的檔案:
            continue
        原始碼 = 檔案.read_text(encoding="utf-8")
        命中 = [關鍵字 for 關鍵字 in 資料庫關鍵字 if 關鍵字 in 原始碼]
        if 命中:
            違規.append(f"{相對路徑}：{命中}")

    assert 違規 == [], f"SQL／資料庫連線只能寫在 repository 與 db 層：{違規}"


def test_只有db層session呼叫psycopg_connect():
    """再收一層：連線字串只在一個地方讀，測試才有辦法整組導向測試庫。"""
    session原始碼 = (專案根目錄 / "app/db/session.py").read_text(encoding="utf-8")
    repository原始碼 = (
        專案根目錄 / "app/repositories/photo_repository.py"
    ).read_text(encoding="utf-8")

    assert "psycopg.connect(" in session原始碼
    assert "psycopg.connect(" not in repository原始碼
