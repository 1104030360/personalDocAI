"""AI 計時 log 真的接上流程了嗎（design4.md §5.2、§5.3、D7；Phase 42）。

`tests/unit/test_ai_timing_unit.py` 驗的是 helper 本身的格式；這裡驗的是
**呼叫點有沒有包對**——上傳一張圖會不會各打一組看圖與轉向量、
PDF 是不是每頁各一組（而不是整份一組）、看不懂的那一頁有沒有標 `ok=false`
且根本不打 `embed`、歸類重算向量有沒有自己的一組。

三條刻意的規矩：

1. **秒數一律不驗數字**，只看欄位存在與 `ok=` 的真假（design4 §5.3 明文）。
   假件跑得飛快，寫死秒數必壞。
2. **開始行與結束行都含 `kind=vlm `**，所以下面兩個小工具連開頭一起比對；
   只用 `kind=` 過濾會一次撈到兩種、數量全部翻倍。
3. **一顆測試裡做兩件事就要 `caplog.clear()`**：`caplog` 是整顆測試累積的，
   「先上傳再 PATCH」不清掉的話 `kind=embed` 會撈到 2 組。

本檔完全不打真模型：`conftest.py` 的 `wire_fake_ai` 已把六個注入點都換成假件，
需要「看得懂」時在測試裡覆寫 `get_vlm` 即可（覆寫由 `wire_fake_ai` 統一收拾）。
"""

from __future__ import annotations

import logging

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_pdf_bytes, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class 分頁VLM:
    """指定「第幾頁看得懂」的假件，用來重現「部分頁看不懂」。

    寫法照 `tests/integration/test_pdf_upload.py` 的同名假件，但**在本檔自己定義一份**：
    跨測試檔 import 會把兩份測試綁在一起，那邊改一下這邊就跟著紅，不划算。
    """

    def __init__(self, 看得懂的頁碼: set[int]) -> None:
        self.看得懂的頁碼 = 看得懂的頁碼      # 1 起算，與 skipped_pages 同一套頁碼
        self.calls = 0

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        if self.calls in self.看得懂的頁碼:
            return 收據理解
        return PhotoUnderstanding(understood=False)


def 開始行(caplog, kind: str) -> list[str]:
    """這次測試期間，某一種 AI 呼叫的所有「開始」行。"""
    return [m for m in caplog.messages if m.startswith(f"AI 開始 kind={kind} ")]


def 結束行(caplog, kind: str) -> list[str]:
    """這次測試期間，某一種 AI 呼叫的所有「結束」行。"""
    return [m for m in caplog.messages if m.startswith(f"AI 結束 kind={kind} ")]


def _上傳一張圖(client):
    return client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )


def _上傳PDF(client, pages: int):
    payload = make_pdf_bytes(pages=pages)
    return client.post(
        "/photos", files={"file": ("scan.pdf", payload, "application/pdf")}
    )


# ---------------------------- 上傳（Phase 42）----------------------------


def test_上傳一張圖各打一組看圖與轉向量的log(client, caplog):
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = _上傳一張圖(client)

    assert response.status_code == 201, response.text
    assert len(開始行(caplog, "vlm")) == 1, caplog.messages
    assert len(結束行(caplog, "vlm")) == 1, caplog.messages
    assert len(開始行(caplog, "embed")) == 1, caplog.messages
    assert len(結束行(caplog, "embed")) == 1, caplog.messages
    assert "ok=true" in 結束行(caplog, "vlm")[0]
    assert "ok=true" in 結束行(caplog, "embed")[0]


def test_看圖計時備註只記數量與布林值不記AI產生內容(client, caplog):
    caplog.set_level(logging.INFO)
    私密類別 = "AI_PRIVATE_CATEGORY_7fa3"
    私密實體 = "AI_PRIVATE_ENTITY_92bd"
    私密待辦 = "AI_PRIVATE_TASK_c184"
    understanding = PhotoUnderstanding(
        understood=True,
        text="一張需要整理的照片",
        category=私密類別,
        location="AI_PRIVATE_LOCATION_61de",
        items=["AI_PRIVATE_ITEM_38ac"],
        entity=私密實體,
        task_title=私密待辦,
    )
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(understanding)

    response = _上傳一張圖(client)

    assert response.status_code == 201, response.text
    看圖結束 = 結束行(caplog, "vlm")
    assert len(看圖結束) == 1, caplog.messages
    摘要 = 看圖結束[0]
    assert "understood=true" in 摘要
    assert f"text_chars={len(understanding.text)}" in 摘要
    assert "item_count=1" in 摘要
    assert "category_present=true" in 摘要
    assert "entity_present=true" in 摘要
    assert "task_present=true" in 摘要
    for AI原文 in (私密類別, 私密實體, 私密待辦):
        assert AI原文 not in 摘要


def test_看不懂的照片看圖log標ok為false且不打embed(client, caplog):
    """看不懂＝這次呼叫失敗，結束行要標 ok=false；422 的語意一個字都沒變。

    這裡刻意沿用假位元組：看不懂那條路根本不會解碼圖片，
    正好順便證明「422 是 VLM 判的，不是 Pillow 判的」。
    """
    caplog.set_level(logging.INFO)
    # conftest 的 wire_fake_ai 預設就是「看不懂」的 FakeVLM()，這裡不必覆寫

    response = client.post(
        "/photos", files={"file": ("a.png", b"\x89PNG", "image/png")}
    )

    assert response.status_code == 422, response.text
    結束 = 結束行(caplog, "vlm")
    assert len(結束) == 1, caplog.messages
    assert "ok=false" in 結束[0]
    # 看不懂就沒走到轉向量那一步
    assert 開始行(caplog, "embed") == []
    assert 結束行(caplog, "embed") == []


def test_PDF兩頁各打兩組(client, caplog):
    """D7：每一頁各一組，不是整份一組總時間（design4 §1.2 已否決總時間）。"""
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = _上傳PDF(client, pages=2)

    assert response.status_code == 201, response.text
    assert len(開始行(caplog, "vlm")) == 2, caplog.messages
    assert len(開始行(caplog, "embed")) == 2, caplog.messages


def test_PDF跳過的那一頁不打embed(client, caplog):
    caplog.set_level(logging.INFO)
    vlm = 分頁VLM(看得懂的頁碼={1})
    app.dependency_overrides[get_vlm] = lambda: vlm

    response = _上傳PDF(client, pages=2)

    assert response.status_code == 201, response.text
    assert response.json()["skipped_pages"] == [2]
    結束 = 結束行(caplog, "vlm")
    assert len(結束) == 2, caplog.messages
    assert "ok=true" in 結束[0]
    assert "ok=false" in 結束[1]
    # 第 2 頁根本沒走到轉向量，所以 embed 只有第 1 頁那一組
    assert len(開始行(caplog, "embed")) == 1, caplog.messages
    assert len(結束行(caplog, "embed")) == 1, caplog.messages


def test_歸類重算向量會打embed的log(client, caplog):
    """歸類只重算向量、不重看一次圖，所以只有 embed 那一組。"""
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    上傳 = _上傳一張圖(client)
    assert 上傳.status_code == 201, 上傳.text
    photo_id = 上傳.json()["id"]

    # caplog 是整顆測試累積的：不清掉的話上傳那一組會混進下面的斷言
    caplog.clear()

    response = client.patch(
        f"/photos/{photo_id}/folder", json={"folder_id": 2}
    )

    assert response.status_code == 200, response.text
    assert len(開始行(caplog, "embed")) == 1, caplog.messages
    assert len(結束行(caplog, "embed")) == 1, caplog.messages
    assert "ok=true" in 結束行(caplog, "embed")[0]
    assert 開始行(caplog, "vlm") == []


def test_切到雲端時看圖是cloud而轉向量仍是local(client, caplog, monkeypatch):
    """向量必須跟庫裡既有的 bge-m3 同源，所以 embeddings 從來不歸那顆開關管。

    `wire_fake_ai` 仍把 get_vlm 換成假件，所以撥到雲端**不會**真的打雲端；
    這顆測的是 log 的 backend／model 欄位有沒有跟著開關走。
    """
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    response = _上傳一張圖(client)

    assert response.status_code == 201, response.text
    看圖 = 開始行(caplog, "vlm") + 結束行(caplog, "vlm")
    轉向量 = 開始行(caplog, "embed") + 結束行(caplog, "embed")
    assert len(看圖) == 2, caplog.messages
    assert len(轉向量) == 2, caplog.messages
    for 行 in 看圖:
        assert f"backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}" in 行
    for 行 in 轉向量:
        assert f"backend=local model={config.EMBEDDING_MODEL}" in 行


# ---------------------------- 詢問（Phase 43）----------------------------
#
# 一句話問答會打幾次模型，log 上看得出來：
#   走語意查詢 → route ＋ embed ＋ answer ＝ 三組
#   走條件／實體／待辦 → route ＋ answer      ＝ 兩組（那三路只查 SQL）
# 問句用的是 tests/fakes.py 的 FakeRouter 登記過的那幾句；
# 沒登記的問句它會丟例外（模擬「模型判斷不出來」），測試 3 就是靠這個。


def test_詢問走語意查詢會打route與embed與answer三組(client, caplog):
    caplog.set_level(logging.INFO)

    response = client.post("/ask", json={"question": "我最近買過什麼飲料？"})

    assert response.status_code == 200, response.text
    assert response.json()["search_mode"] == "vector semantic search"
    for kind in ("route", "embed", "answer"):
        assert len(開始行(caplog, kind)) == 1, (kind, caplog.messages)
        結束 = 結束行(caplog, kind)
        assert len(結束) == 1, (kind, caplog.messages)
        assert "ok=true" in 結束[0]


def test_詢問走條件查詢沒有embed那一組(client, caplog):
    """條件查詢只查 SQL，不必把問題轉成向量（design4 §5.2 最後一句）。"""
    caplog.set_level(logging.INFO)

    response = client.post("/ask", json={"question": "有哪些在 Target 拍的收據？"})

    assert response.status_code == 200, response.text
    assert response.json()["search_mode"] == "metadata search"
    assert len(開始行(caplog, "route")) == 1, caplog.messages
    assert len(開始行(caplog, "answer")) == 1, caplog.messages
    assert 開始行(caplog, "embed") == []
    assert 結束行(caplog, "embed") == []


def test_路由失敗時route標ok為false且仍走語意查詢(client, caplog):
    """例外先穿過 log_ai（打 ok=false）再被 except 接住——fallback 語意一字未變。"""
    caplog.set_level(logging.INFO)

    # FakeRouter 沒登記過的問句會丟例外，模擬「LLM 判斷不出來」
    response = client.post("/ask", json={"question": "幫我找找之前那個"})

    assert response.status_code == 200, response.text
    assert response.json()["search_mode"] == "vector semantic search"
    結束 = 結束行(caplog, "route")
    assert len(結束) == 1, caplog.messages
    assert "ok=false" in 結束[0]
    # fallback 成語意查詢＝仍然有轉向量那一組
    assert len(開始行(caplog, "embed")) == 1, caplog.messages
    assert len(開始行(caplog, "answer")) == 1, caplog.messages
