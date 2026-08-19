"""design.md 規定、但規格 .feature 沒涵蓋的上傳行為守衛（自 Phase 5/6 煙霧測試承接）。

- 415 之後不進任何後續處理（design.md §10 錯誤處理總表）
- understood=True 但 text 全空白 → 一樣 422（design.md §8.1「失敗就不存，text 不會空」）
- Rule U4 護欄：向量必須由「文字＋四欄位合併內容」產生（clarify 已否決「只用 text」方案）
"""

from __future__ import annotations

import json

from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.indexing_service import build_document, embed_document
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeEmbeddings, FakeVLM

PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"


def test_非圖片格式不會呼叫看圖(client):
    fake = FakeVLM()
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 415
    assert fake.calls == 0  # 415 之後不會呼叫 understand()


def test_理解結果text全空白也回422且不儲存(client):
    """Rule U7 的另一半：understood=True 但 text 全空白，一樣視為無法理解。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=True, text="   ")
    )

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "VLM 無法理解照片內容，未儲存任何資料"
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

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 201

    stored = json.loads(photo_repository.fetch_embedding(response.json()["id"]))
    document = build_document(
        text="超市購物的照片",
        category="收據",
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
