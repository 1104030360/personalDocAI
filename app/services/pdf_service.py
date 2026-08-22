"""PDF → 一頁一張 PNG。全系統唯一碰 pypdfium2 的地方（design3.md D7、§7）。

分層：本模組只做「把頁畫成圖」，不碰資料庫、不碰 HTTP、也不寫檔。
渲染出來的 PNG 位元組交回 api/routers/photos.py，由它一頁一頁走既有的單圖流程
（看圖 → 轉向量 → 寫入未分類 → 存原圖＋縮圖），所以 PDF 不需要第二套入庫邏輯。

不保留 PDF 原始檔：photo 的「原圖」就是該頁渲染出來的 PNG。
"""

from __future__ import annotations

import io

import pypdfium2 as pdfium

# 渲染倍率。PDF 是向量格式，沒有「原始像素」可言，倍率決定畫多細：
# 2.0 ＝ 以兩倍解析度畫出來，A4 約 1200×1700px——夠 VLM 讀清楚掃描件上的字，
# 也還在縮圖（長邊 512）之上，不必為了畫質再調高而拖慢每一頁。
DEFAULT_SCALE = 2.0


class PdfUnreadableError(Exception):
    """這份 PDF 打不開或一頁都沒有。

    自己一個例外類別，是為了讓 router 分得出「使用者給了壞檔」（422）與
    「伺服器出事」（500）——直接把 pypdfium2 的例外往外丟會全部變成 500。
    """


def render_pages(pdf_bytes: bytes, scale: float = DEFAULT_SCALE) -> list[bytes]:
    """把整份 PDF 逐頁渲染成 PNG 位元組，回傳的順序即頁序。

    順序很重要：呼叫端用「第幾個」回報 skipped_pages 的頁碼。
    """
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as error:
        # 壞檔、加密的 PDF 都走這條（本增量不做加密 PDF 支援）
        raise PdfUnreadableError("無法讀取 PDF 檔案") from error

    # with 區塊結束時會關掉文件，把 PDFium 那邊的原生記憶體立刻還回去
    with document:
        if len(document) == 0:
            raise PdfUnreadableError("這份 PDF 沒有任何一頁")

        pages: list[bytes] = []
        for page in document:
            # render() 回傳的是 PDFium 的點陣圖，to_pil() 換成 Pillow 圖片物件，
            # 再存成 PNG bytes——之後的存檔與縮圖都吃 bytes，跟一般上傳沒有兩樣。
            image = page.render(scale=scale).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pages.append(buffer.getvalue())

    return pages
