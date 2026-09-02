"""隱私閘門 VLM 短問的契約測試（design6.md D2〜D4，2026-09-01 改判）。

★ 本檔不打真模型。VlmGate 吃 FakePrivacyModel；注入點吃 FakePrivacyGate。
"""

from __future__ import annotations

import base64
import logging

from langchain_core.messages import HumanMessage

from app.core import config
from app.dependencies import build_privacy_gate_for_backend, get_privacy_gate
from app.services import privacy_gate
from app.services.privacy_gate import (
    PRIVACY_PROMPT,
    PrivacyJudgement,
    Verdict,
    VlmGate,
    judgement_to_verdict,
)
from tests.fakes import FakeCloudChat, FakePrivacyGate, FakePrivacyModel, make_png_bytes


def _png() -> bytes:
    """真的 PNG，不是假位元組。

    Phase 75 會在 VlmGate.classify() 裡加一段縮圖（長邊 ≤512），假位元組
    Pillow 解不開 → 那時本檔十一顆裡有九顆會一起變 UNCERTAIN 而翻紅。
    從一開始就用真圖，75 接上縮圖之後這十一顆一顆都不必改。
    """
    return make_png_bytes()


def classify_with(model: FakePrivacyModel, *, filename: str = "any.jpg") -> Verdict:
    return VlmGate(model).classify(
        filename=filename,
        content_type="image/jpeg",
        load_bytes=_png,
    )


def test_模型說敏感回SENSITIVE():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=True, confident=True))
    assert classify_with(model) is Verdict.SENSITIVE
    assert model.calls == 1


def test_模型說不敏感而且有把握回NON_SENSITIVE():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    assert classify_with(model) is Verdict.NON_SENSITIVE


def test_模型說不敏感但沒把握回UNCERTAIN():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=False))
    assert classify_with(model) is Verdict.UNCERTAIN


def test_sensitive即使沒把握也當SENSITIVE():
    """沒把握的「是敏感」仍當敏感——錯的方向必須是留下，不是出門。"""
    assert (
        judgement_to_verdict(PrivacyJudgement(sensitive=True, confident=False)) is Verdict.SENSITIVE
    )


def test_模型丟例外回UNCERTAIN():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True), raise_on_judge=True)
    assert classify_with(model) is Verdict.UNCERTAIN


def test_讀檔失敗回UNCERTAIN():
    def explode() -> bytes:
        raise OSError("staging 沒了")

    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    result = VlmGate(model).classify(
        filename="x.jpg", content_type="image/jpeg", load_bytes=explode
    )
    assert result is Verdict.UNCERTAIN
    assert model.calls == 0


def test_檔名完全不影響判斷():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    gate = VlmGate(model)
    a = gate.classify(filename="身分證.jpg", content_type="image/jpeg", load_bytes=_png)
    b = gate.classify(filename="receipt.jpg", content_type="image/jpeg", load_bytes=_png)
    assert a is Verdict.NON_SENSITIVE
    assert b is Verdict.NON_SENSITIVE


def test_會呼叫load_bytes():
    read_count = {"n": 0}

    def read_bytes() -> bytes:
        read_count["n"] += 1
        return _png()

    VlmGate(FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))).classify(
        filename="ignored.jpg", content_type="image/jpeg", load_bytes=read_bytes
    )
    assert read_count["n"] == 1


def test_get_privacy_gate回VlmGate(monkeypatch):
    # Phase 78 起 conftest 的 wire_fake_ai 會把 dependencies 上這兩個名字都換成
    # 假閘門（celery_app.ingest_task 是**直接呼叫**那條路，dependency_overrides 攔不到）。
    # get_privacy_gate() 是透過模組屬性去呼叫建構函式的，所以會一起拿到假的——
    # 本檔要驗的是「真的那一支長什麼樣」，先把它裝回去（by-name import 拿到的就是原件）。
    monkeypatch.setattr(
        "app.dependencies.build_privacy_gate_for_backend", build_privacy_gate_for_backend
    )
    assert isinstance(get_privacy_gate(), VlmGate)


def test_FakePrivacyGate固定回傳指定verdict():
    fake_gate = FakePrivacyGate(Verdict.SENSITIVE)
    assert (
        fake_gate.classify(filename="x.jpg", content_type="image/png", load_bytes=_png)
        is Verdict.SENSITIVE
    )
    assert fake_gate.calls == 1
    assert fake_gate.last_filename == "x.jpg"


def test_wire_fake_ai預設掛UNCERTAIN():
    """Depends 走 overrides。

    ⚠ Phase 78 起 conftest 的 wire_fake_ai 用 monkeypatch **雙名**蓋掉
    `dependencies.get_privacy_gate` 與 `dependencies.build_privacy_gate_for_backend`，
    所以直接呼叫 get_privacy_gate() 拿到的**也是** FakePrivacyGate（不是正式 VlmGate）。
    要拿正式的那一顆，得像 test_get_privacy_gate回VlmGate 那樣先把真工廠裝回去。
    """
    from app.main import app

    gate = app.dependency_overrides[get_privacy_gate]()
    assert isinstance(gate, FakePrivacyGate)
    assert (
        gate.classify(filename="a.jpg", content_type="image/jpeg", load_bytes=_png)
        is Verdict.UNCERTAIN
    )


def test_送進模型的圖長邊不超過512():
    import io

    from PIL import Image

    big_image = Image.new("RGB", (2000, 1000), "white")
    buf = io.BytesIO()
    big_image.save(buf, format="PNG")
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(model).classify(
        filename="big.jpg", content_type="image/png", load_bytes=lambda: buf.getvalue()
    )
    sent_image = Image.open(io.BytesIO(model.last_image_bytes))
    assert max(sent_image.size) <= 512
    # 縮完一律是 PNG，所以問模型時報的 content_type 也固定是它（不是原檔那個）
    assert model.last_content_type == "image/png"


def test_本機後端用本機VLM模型名(monkeypatch):
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    model = privacy_gate.OllamaPrivacyModel()
    assert model.timing_target.model == config.VLM_MODEL
    assert model.timing_target.backend == "local"


def test_雲端後端用雲端VLM模型名(monkeypatch):
    # 假 key 必須是 ASCII（HTTP header 不吃中文）；建 Client 不會連線。
    # 比照既有的 test_雲端VLM暴露建構時選定的不可變計時目標，不靠 .env 有沒有填。
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    model = privacy_gate.OllamaPrivacyModel()
    assert model.timing_target.model == config.OLLAMA_CLOUD_VLM_MODEL
    assert model.timing_target.backend == "cloud"


def test_短prompt不含完整understand欄位():
    for forbidden in ("category", "location", "items", "task_title", "task_due", "content_time"):
        assert forbidden not in PRIVACY_PROMPT


def test_PDF渲染第一頁再問():
    from tests.fakes import make_pdf_bytes

    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(model).classify(
        filename="scan.pdf",
        content_type="application/pdf",
        load_bytes=make_pdf_bytes,
    )
    assert model.calls == 1
    assert model.last_image_bytes[:4] == b"\x89PNG"


def test_PDF渲染失敗回UNCERTAIN():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    result = VlmGate(model).classify(
        filename="壞.pdf",
        content_type="application/pdf",
        load_bytes=lambda: b"%PDF-not-a-pdf",
    )
    assert result is Verdict.UNCERTAIN
    assert model.calls == 0


def test_PDF閘門只渲染第一頁(monkeypatch):
    """R4：閘門對多頁 PDF 只渲染第一頁。

    包住**真的** render_pages（不是換成假的）：既驗「有沒有把 max_pages 傳下去」，
    也驗「傳下去之後真的還拿得到一張 PNG」——換成假的就只驗得到前者。
    """
    from tests.fakes import make_pdf_bytes

    seen_kwargs: dict = {}
    real_render_pages = privacy_gate.pdf_service.render_pages

    def recording_render_pages(pdf_bytes, *args, **kwargs):
        seen_kwargs.update(kwargs)
        return real_render_pages(pdf_bytes, *args, **kwargs)

    monkeypatch.setattr(privacy_gate.pdf_service, "render_pages", recording_render_pages)

    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    VlmGate(model).classify(
        filename="scan.pdf",
        content_type="application/pdf",
        load_bytes=lambda: make_pdf_bytes(3),
    )

    assert seen_kwargs.get("max_pages") == 1, "閘門要明講『只要第一頁』"
    assert model.calls == 1
    assert model.last_image_bytes[:4] == b"\x89PNG", "送進模型的仍然是那一頁的 PNG"


def test_縮圖失敗回UNCERTAIN():
    model = FakePrivacyModel(PrivacyJudgement(sensitive=False, confident=True))
    result = VlmGate(model).classify(
        filename="x.jpg",
        content_type="image/jpeg",
        load_bytes=lambda: b"not-an-image",
    )
    assert result is Verdict.UNCERTAIN
    assert model.calls == 0


def test_get_privacy_gate跟AI_BACKEND走(monkeypatch):
    # Phase 78 起 conftest 的 wire_fake_ai 會把 dependencies 上這兩個名字都換成
    # 假閘門（celery_app.ingest_task 是**直接呼叫**那條路，dependency_overrides 攔不到）。
    # get_privacy_gate() 是透過模組屬性去呼叫建構函式的，所以會一起拿到假的——
    # 本檔要驗的是「真的那一支長什麼樣」，先把它裝回去（by-name import 拿到的就是原件）。
    monkeypatch.setattr(
        "app.dependencies.build_privacy_gate_for_backend", build_privacy_gate_for_backend
    )
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    gate = get_privacy_gate()
    assert isinstance(gate, VlmGate)
    assert gate._model.timing_target.backend == "cloud"

    # R1：worker 行程讀不到頁首開關（它的 config.AI_BACKEND 永遠是預設的 "local"），
    # 所以另有一支「明傳後端」的建構函式，Phase 78 會拿 job["ai_backend"] 快照餵它。
    # 這裡順手釘住它真的照參數走，不是又去偷看 config。
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    assert build_privacy_gate_for_backend("cloud")._model.timing_target.backend == "cloud"
    assert build_privacy_gate_for_backend("local")._model.timing_target.backend == "local"


def test_閘門不准寫入AI_BACKEND():
    from pathlib import Path

    source = Path("app/services/privacy_gate.py").read_text(encoding="utf-8")
    assert "AI_BACKEND =" not in source
    assert "AI_BACKEND=" not in source.replace(" ", "")


# ---------- judge() 兩條路徑的行為覆蓋（Phase 75 review／controller 裁決 R10）----------
#
# 上面十顆只碰得到 timing_target，judge() 的函式體一行都沒被執行過。
# 下面兩顆把「怎麼組訊息、怎麼解析回覆」釘死：那一段打錯字的話，閘門會變成
# 永遠 UNCERTAIN、一張都卸不出去，而且只在 warning 裡出聲——正是本專案一向在防的安靜壞掉。
# 兩顆都不碰網路：雲端換掉 ollama_cloud.build_client、本機換掉 ChatOllama。


def test_雲端短問回覆包著圍欄也解析得出來(monkeypatch):
    """ollama.com 對 format= 不強制，回覆可能包在 ```json 圍欄裡（ollama_cloud 的既有教訓）。"""
    # 假 key 必須是 ASCII（HTTP header 不吃中文）；這裡連 Client 都是假的，不會撥號
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")
    fake_client = FakeCloudChat(
        '這是模型多講的一句話\n```json\n{"sensitive": false, "confident": true}\n```\n收尾贅字'
    )
    monkeypatch.setattr(privacy_gate.ollama_cloud, "build_client", lambda: fake_client)

    image_bytes = make_png_bytes()
    judgement = privacy_gate.OllamaPrivacyModel(backend="cloud").judge(image_bytes, "image/png")

    assert judgement == PrivacyJudgement(sensitive=False, confident=True)

    (call,) = fake_client.calls
    assert call["model"] == config.OLLAMA_CLOUD_VLM_MODEL
    assert call["format"] == PrivacyJudgement.model_json_schema()
    assert call["options"] == {"temperature": 0}

    message = call["messages"][0]
    # 官方套件的 images 直接吃 raw bytes，不是 base64 字串
    assert message["images"] == [image_bytes]
    assert message["content"].startswith(PRIVACY_PROMPT)
    # 雲端才接自己那段「只准回 JSON」；接錯成 vlm_service 那顆會叫模型回 understand 的九個鍵
    assert message["content"].endswith(privacy_gate._CLOUD_JSON_INSTRUCTION)


def test_本機短問把圖以base64塞進HumanMessage(caplog, monkeypatch):
    received: dict = {}

    class FakeChat:
        def invoke(self, messages):
            received["messages"] = messages
            return PrivacyJudgement(sensitive=True, confident=True)

    class FakeChatOllama:
        def __init__(self, **kwargs):
            received["建構參數"] = kwargs

        def with_structured_output(self, schema):
            received["schema"] = schema
            return FakeChat()

    monkeypatch.setattr(privacy_gate, "ChatOllama", FakeChatOllama)
    caplog.set_level(logging.INFO)
    image_bytes = make_png_bytes()

    judgement = privacy_gate.OllamaPrivacyModel(backend="local").judge(image_bytes, "image/png")

    assert judgement == PrivacyJudgement(sensitive=True, confident=True)
    assert received["schema"] is PrivacyJudgement
    assert received["建構參數"]["model"] == config.VLM_MODEL
    assert received["建構參數"]["base_url"] == config.OLLAMA_BASE_URL
    assert received["建構參數"]["temperature"] == 0

    message = received["messages"][0]
    assert isinstance(message, HumanMessage)
    assert message.content[0] == {"type": "text", "text": PRIVACY_PROMPT}
    image_block = message.content[1]
    assert image_block["type"] == "image"
    assert image_block["base64"] == base64.b64encode(image_bytes).decode("ascii")
    assert image_block["mime_type"] == "image/png"

    # log_ai 真的把這一次呼叫包住了（kind=privacy，backend／model 跟看圖那顆同一組）
    start_lines = [m for m in caplog.messages if m.startswith("AI 開始 ")]
    end_lines = [m for m in caplog.messages if m.startswith("AI 結束 ")]
    assert (
        len(start_lines) == 1
        and f"kind=privacy backend=local model={config.VLM_MODEL}" in start_lines[0]
    )
    assert (
        len(end_lines) == 1
        and f"kind=privacy backend=local model={config.VLM_MODEL}" in end_lines[0]
    )
    assert "ok=true" in end_lines[0]
