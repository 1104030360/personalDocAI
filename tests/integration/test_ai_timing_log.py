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

增量五（Phase 62）之後上傳拆成兩段：`POST /photos` 只把檔案收下、回 202，
看圖與轉向量都搬進 worker（`app/services/ingest_job.py` 的 `run_ingest_job`），
所以**計時 log 是在「跑完任務」期間才出現的**——測試自己扮演 worker 把它跑完。
兩個連帶的影響：

  - 202 那一段會多印一行「已受理入庫任務」的 INFO，所以下面的上傳小工具
    一律在 POST 之後、跑任務之前 `caplog.clear()`（就是規矩 3 的同一件事）。
  - 看不懂的那條路現在會照 design5.md §4.4 重試 `config.VLM_MAX_ATTEMPTS` 次，
    所以「失敗」的看圖結束行有那麼多組，不再只有一組。

本檔完全不打真模型：`conftest.py` 的 `wire_fake_ai` 已把六個注入點都換成假件，
需要「看得懂」時在測試裡覆寫 `get_vlm` 即可（覆寫由 `wire_fake_ai` 統一收拾）；
`跑完任務` 用的也正是這幾份假件（見 `tests/conftest.py` 的 `目前注入的假件`）。
"""

from __future__ import annotations

import logging

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片, 目前的任務清單, 跑完任務
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

    ⚠ 「第幾次呼叫＝第幾頁」只有在**每一頁都第一次就看得懂**時才成立：
      增量五起 worker 會為看不懂的那一頁重試 `config.VLM_MAX_ATTEMPTS` 次，
      所以一頁失敗就會吃掉那麼多次呼叫。本檔唯一的用法是「第 1 頁看得懂」，
      第 1 頁必定在第 1 次命中，後面幾次全歸第 2 頁——行為與改版前一致。
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


def _收下再跑完(client, caplog, *, payload: bytes, filename: str, content_type: str):
    """POST（202）→ **清掉 caplog** → 測試扮演 worker 把任務跑完。回 POST 的原始回應。

    ⚠ `caplog.clear()` 那一行不可以省，位置也不能換（一定要卡在 POST 之後、
      跑任務之前）：202 那一段會多印一行「已受理入庫任務」的 INFO，
      而本檔靠 `caplog.messages` 逐則比對，混進去會讓計數與訊息都對不上。
    """
    response = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )
    assert response.status_code == 202, response.text

    caplog.clear()

    跑完任務(response.json()["job_id"])
    return response


def _上傳一張圖(client, caplog):
    """上傳一張 PNG 並把入庫任務跑完（計時 log 是在跑任務期間才出現的）。"""
    return _收下再跑完(
        client,
        caplog,
        payload=make_png_bytes(),
        filename="a.png",
        content_type="image/png",
    )


def _上傳PDF(client, caplog, pages: int):
    """上傳一份 PDF 並把入庫任務跑完（每一頁的 log 都在這段期間出現）。"""
    return _收下再跑完(
        client,
        caplog,
        payload=make_pdf_bytes(pages=pages),
        filename="scan.pdf",
        content_type="application/pdf",
    )


# ---------------------------- 上傳（Phase 42）----------------------------


def test_上傳一張圖各打一組看圖與轉向量的log(client, caplog):
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    _上傳一張圖(client, caplog)

    assert photo_repository.count_photos() == 1
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

    _上傳一張圖(client, caplog)

    assert photo_repository.count_photos() == 1
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
    """看不懂＝這次呼叫失敗，結束行要標 ok=false；「看不懂就整筆不存」的語意沒變。

    增量五（Phase 62）起 HTTP 一定是 202（收下而已），看不懂的結局改在
    worker 那一側呈現：job 標成 failed、照片一列都沒有（樣板 C）。
    而 worker 會照 design5.md §4.4 重試 `config.VLM_MAX_ATTEMPTS` 次，
    所以看圖的結束行有那麼多組、每一組都要誠實地標 ok=false。

    這裡刻意沿用假位元組：看不懂那條路根本不會解碼圖片，
    正好順便證明「最後失敗是 VLM 判的，不是 Pillow 判的」。
    """
    caplog.set_level(logging.INFO)
    # conftest 的 wire_fake_ai 預設就是「看不懂」的 FakeVLM()，這裡不必覆寫

    response = _收下再跑完(
        client, caplog, payload=b"\x89PNG", filename="a.png", content_type="image/png"
    )

    job = 目前的任務清單().get(response.json()["job_id"])
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0
    結束 = 結束行(caplog, "vlm")
    assert len(結束) == config.VLM_MAX_ATTEMPTS, caplog.messages
    assert all("ok=false" in 行 for 行 in 結束), caplog.messages
    # 看不懂就沒走到轉向量那一步
    assert 開始行(caplog, "embed") == []
    assert 結束行(caplog, "embed") == []


def test_PDF兩頁各打兩組(client, caplog):
    """D7：每一頁各一組，不是整份一組總時間（design4 §1.2 已否決總時間）。"""
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    _上傳PDF(client, caplog, pages=2)

    assert photo_repository.count_photos() == 2, "兩頁都看得懂＝兩張照片"
    assert len(開始行(caplog, "vlm")) == 2, caplog.messages
    assert len(開始行(caplog, "embed")) == 2, caplog.messages


def test_PDF跳過的那一頁不打embed(client, caplog):
    """第 2 頁看不懂＝跳過那一頁，整份照樣成功（design5.md D12）。

    「跳過了哪幾頁」不再有 `skipped_pages` 這個回應鍵（202 沒有那種東西，
    Phase 60 也明文不另存欄位），改用「總頁數 − 真的入庫的張數」證明。
    """
    caplog.set_level(logging.INFO)
    vlm = 分頁VLM(看得懂的頁碼={1})
    app.dependency_overrides[get_vlm] = lambda: vlm

    _上傳PDF(client, caplog, pages=2)

    assert photo_repository.count_photos() == 1, "兩頁中只有第 1 頁進得了庫"
    結束 = 結束行(caplog, "vlm")
    # 第 1 頁一次過；第 2 頁被重試到用完 VLM_MAX_ATTEMPTS 次才跳過
    assert len(結束) == 1 + config.VLM_MAX_ATTEMPTS, caplog.messages
    assert "ok=true" in 結束[0]
    assert all("ok=false" in 行 for 行 in 結束[1:]), caplog.messages
    # 第 2 頁根本沒走到轉向量，所以 embed 只有第 1 頁那一組
    assert len(開始行(caplog, "embed")) == 1, caplog.messages
    assert len(結束行(caplog, "embed")) == 1, caplog.messages


def test_歸類重算向量會打embed的log(client, caplog):
    """歸類只重算向量、不重看一次圖，所以只有 embed 那一組。"""
    caplog.set_level(logging.INFO)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    # 樣板 A：這一顆只需要「有一張照片」，用共用工具把上傳與入庫一次做完
    photo_id = 上傳一張並取回照片(client)["id"]

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

    ⚠ 開關一定要在 **POST 之前**撥：AI 開關的快照是**入列當下**拍進任務的
      （design5.md D14）。假件身上沒有 timing_target，ai_timing 會退回讀
      `config.AI_BACKEND`，而 monkeypatch 到測試結束前都還生效，所以
      跑任務期間打出來的 backend 仍然是 cloud。
    """
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    _上傳一張圖(client, caplog)

    assert photo_repository.count_photos() == 1
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
