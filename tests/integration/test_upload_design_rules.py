"""design.md 規定、但規格 .feature 沒涵蓋的上傳行為守衛（自 Phase 5/6 煙霧測試承接）。

- 415 之後不進任何後續處理（design.md §10 錯誤處理總表）
- understood=True 但 text 全空白 → 一樣視為無法理解、整筆不存
  （design.md §8.1「失敗就不存，text 不會空」）
- Rule U4 護欄：向量必須由「文字＋四欄位合併內容」產生（clarify 已否決「只用 text」方案）

2026-08-25（Phase 62）起上傳改回 202：HTTP 只收檔、入列，看圖與寫入都在 worker。
所以「全空白＝看不懂」的結局從 HTTP 422 換成 job["status"] == "failed"，
而「向量長什麼樣」「清單有沒有傳給看圖」一律等測試扮演 worker 把任務跑完再驗。
"""

from __future__ import annotations

import json

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.indexing_service import build_document, embed_document
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳一張並取回照片, 目前的任務清單, 跑完任務
from tests.fakes import FakeEmbeddings, FakeVLM, make_png_bytes

PNG_BYTES = make_png_bytes()


def test_非圖片格式不會呼叫看圖(client):
    fake = FakeVLM()
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post("/photos", files={"file": ("a.txt", b"hello", "text/plain")})

    assert response.status_code == 415
    assert fake.calls == 0  # 415 之後不會呼叫 understand()


def test_理解結果text全空白最後整筆失敗(client):
    """Rule U7 的另一半：understood=True 但 text 全空白，一樣視為無法理解。

    Phase 62 起這條語意搬進 worker：HTTP 收檔那一刻還沒看過圖，所以一定回 202；
    試滿次數都是「空白＝看不懂」，整筆失敗、資料庫一列都不留。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=True, text="   ")
    )

    response = client.post("/photos", files={"file": ("a.png", PNG_BYTES, "image/png")})
    assert response.status_code == 202, response.text

    job_id = response.json()["job_id"]
    跑完任務(job_id)

    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed"
    assert photo_repository.count_photos() == 0


def test_向量由合併內容產生而非只有文字(client):
    """Rule U4 的護欄：存入的向量＝「文字＋四欄位合併內容」的向量，
    且不等於「只用 text」的向量（clarify 已否決的方案不得悄悄回歸）。

    fixture 刻意讓 metadata 的詞（收據/Costco/咖啡/牛奶）不出現在 text 裡——
    metadata 值若是 text 的子字串，假向量會分不出兩種實作。
    """
    理解結果 = PhotoUnderstanding(
        understood=True,
        text="超市購物的照片",
        category="收據",
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(理解結果)

    列 = 上傳一張並取回照片(client, payload=PNG_BYTES)

    assert 列["category"] == "未分類"
    # 「收據」在預設清單裡 → 建議留著（Phase 62 起寫進照片那一列，不再進回應）
    assert 列["suggested_category"] == "收據"

    stored = json.loads(photo_repository.fetch_embedding(列["id"]))
    # 2026-08-20 起上傳一律用「未分類」合併——VLM 講的「收據」只是建議，不落庫。
    # 歸類後的重算由 PATCH /photos/{id}/folder 負責（Phase 21 另有測試）。
    document = build_document(
        text="超市購物的照片",
        category="未分類",
        location="Costco",
        items=["咖啡", "牛奶"],
        content_time=None,
    )
    expected = embed_document(FakeEmbeddings(), document)
    text_only = FakeEmbeddings().embed_query("超市購物的照片")

    # 與期望向量逐元素比對（pgvector 以 float4 儲存，取 1e-6 容差）
    assert max(abs(a - b) for a, b in zip(stored, expected)) < 1e-6
    # 與「只用 text」的向量必須可區分——否則這個測試就守不住 U4
    assert max(abs(a - b) for a, b in zip(stored, text_only)) > 1e-3


# ---- design1.md §8：上傳時把現有資料夾清單當變數注入 VLM prompt ----
def test_上傳時把現有資料夾清單傳給看圖(client):
    """呼叫端必須真的去資料庫讀清單再傳進 understand()，不是傳空陣列了事。

    conftest 的 reset_tables 每個測試都會重播 design1.md §5 的預設六資料夾，
    所以這裡可以直接斷言那六個名稱。

    Phase 62 起讀清單的「呼叫端」是 run_ingest_job（worker），不再是 router；
    但假件是**同一個實例**（overrides 掛的是 `lambda: fake`），所以照樣驗得到。
    """
    fake = FakeVLM(
        PhotoUnderstanding(
            understood=True,
            text="在 Target 購買可樂的收據",
            category="收據",
            location="Target",
            items=["可樂"],
            content_time="2026-08-10",
        )
    )
    app.dependency_overrides[get_vlm] = lambda: fake

    上傳一張並取回照片(client, payload=PNG_BYTES)

    names = [folder["name"] for folder in fake.last_folders]
    assert names == ["未分類", "收據", "飲食", "風景", "文件", "其他"]
    # description 也要一起傳（prompt 需要它才寫得出「這個資料夾是裝什麼的」）
    assert all(folder["description"] for folder in fake.last_folders)
