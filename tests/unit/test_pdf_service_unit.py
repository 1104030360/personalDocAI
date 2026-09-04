"""pdf_service 的單元測試：只把 PDF 渲染成圖，不碰資料庫、不碰網路、不寫檔。

design3.md D7／§7：PDF **一頁一張 photo**——這個模組負責的就是前半段「頁 → 圖」，
「圖 → photo」由 api/routers/photos.py 交給既有的單圖流程處理。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import pdf_service
from tests.fakes import make_pdf_bytes


def test_單頁PDF渲染出一張PNG():
    pages = pdf_service.render_pages(make_pdf_bytes(1))

    assert len(pages) == 1
    # 渲染結果要是真的 PNG 位元組：Pillow 打得開、格式就是 PNG。
    # 後面存檔與縮圖都吃這串 bytes，所以這裡就要驗到「真的能用」。
    with Image.open(io.BytesIO(pages[0])) as image:
        assert image.format == "PNG"


def test_三頁PDF渲染出三張():
    # 多頁就多張，順序即頁序（skipped_pages 回報的頁碼靠這個順序才有意義）
    assert len(pdf_service.render_pages(make_pdf_bytes(3))) == 3


def test_壞檔丟PdfUnreadableError():
    """讀不開的檔案要換成自家例外，router 才有東西可以接成 422。

    直接讓 pypdfium2 的例外往外跑會變成 500——「壞檔」是使用者的問題，不是伺服器的。
    """
    with pytest.raises(pdf_service.PdfUnreadableError):
        pdf_service.render_pages(b"not a pdf")


def test_max_pages只渲染前幾頁():
    """閘門只需要第一頁（Phase 81 裁決 R4）：30 頁的掃描件不必整份渲染。

    max_pages=None ＝ 全部——既有呼叫端（ingest_job._run_pdf_job）一個字都不必改，
    這一顆就是那個「向下相容」的證據。給的數字比實際頁數大也不會炸。
    """
    pdf_bytes = make_pdf_bytes(3)

    assert len(pdf_service.render_pages(pdf_bytes, max_pages=1)) == 1
    assert len(pdf_service.render_pages(pdf_bytes, max_pages=None)) == 3
    assert len(pdf_service.render_pages(pdf_bytes, max_pages=5)) == 3
