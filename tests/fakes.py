"""測試用的假件。真 AI／真時鐘的替身，讓測試結果可預期。"""

from __future__ import annotations

import hashlib
import io
import math
import os
from datetime import datetime
from types import SimpleNamespace

from langchain_core.documents import Document
from PIL import Image

from app.core import config
from app.services.ask_workflow import RouteDecision
from app.services.vlm_service import PhotoUnderstanding


# ---------- 真的圖片位元組（Pillow 讀得開）----------
# 為什麼需要它：從 Phase 17 起系統會真的用 Pillow 把上傳的 bytes 打開來做縮圖。
# b"\x89PNG…" 這種手打的假位元組會讓 Pillow 直接拋 UnidentifiedImageError，
# 所以凡是「預期上傳成功」的測試，一律用下面的函式現產一張真的小圖。


def _image_bytes(width: int, height: int, image_format: str) -> bytes:
    """畫一張純色小圖並轉成該格式的位元組。"""
    buffer = io.BytesIO()   # 假裝成檔案的一段記憶體，不必真的寫到磁碟
    Image.new("RGB", (width, height), color=(200, 120, 60)).save(
        buffer, format=image_format
    )
    return buffer.getvalue()


def make_png_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 PNG。預設 40×20，小到幾乎不花時間。"""
    return _image_bytes(width, height, "PNG")


def make_jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 JPEG。"""
    return _image_bytes(width, height, "JPEG")


def make_large_png_bytes(side: int = 1200) -> bytes:
    """產生一張『真的很大』的 PNG（約 4 MB 以上），用來證明系統沒有檔案大小上限。

    刻意用隨機雜訊：純色圖片會被 PNG 壓成幾 KB，撐不出檔案大小。
    os.urandom(n)＝n 個隨機位元組；每個像素 3 個位元組（RGB）。
    """
    buffer = io.BytesIO()
    pixels = os.urandom(side * side * 3)
    Image.frombytes("RGB", (side, side), pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def make_pdf_bytes(pages: int = 1) -> bytes:
    """產生一份真的 PDF，每頁一張純色小圖（Phase 28）。

    Pillow 自己就會寫 PDF（save(format="PDF")），測試端因此不必多裝套件：
    save_all=True ＋ append_images=其餘頁 ＝ 把多張圖寫成多頁的同一份檔案。
    """
    first, *rest = [
        Image.new("RGB", (40, 20), color=(30 + index * 40, 120, 60))
        for index in range(pages)
    ]
    buffer = io.BytesIO()
    first.save(buffer, format="PDF", save_all=True, append_images=rest)
    return buffer.getvalue()


class FakeVLM:
    """考試用的固定答案卡，不是正式看圖系統。

    測試會先指定「請當作收據、店名 Target」；understand() 照念，不呼叫 Ollama。
    沒給 result 時預設 understood=False（規格：看不懂 → 422、什麼都不存）。

    folders／entities／corrections 參數只是為了與 VLMClient 協定一致
    （Phase 18 加 folders、Phase 30 加 entities、Phase 35 加 corrections）：
    假件不會真的照著清單思考，但會把收到的三份清單記在
    last_folders／last_entities／last_corrections，
    讓測試可以驗「呼叫端真的把三份都傳進去了」。
    """

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0
        self.last_folders: list[dict] | None = None
        self.last_entities: list[dict] | None = None
        self.last_corrections: list[dict] | None = None

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        self.last_folders = folders
        self.last_entities = entities
        self.last_corrections = corrections
        return self.result


class FakeEntitySuggester:
    """「再建議一個實體」的固定答案卡，不呼叫 Ollama。

    建構子登記這次要挑哪一個名字（預設 None＝都不像，也就是最保守的答案）；
    calls 與 last_candidates 讓測試驗得出「候選空時根本沒問模型」
    與「exclude 掉的實體真的沒進候選清單」。
    """

    def __init__(self, result: str | None = None) -> None:
        self.result = result
        self.calls = 0
        self.last_candidates: list[dict] | None = None

    def pick(self, photo: dict, candidates: list[dict]) -> str | None:
        self.calls += 1
        self.last_candidates = candidates
        return self.result


# 規格例子與雙語測試裡會出現的詞。假的向量只認得這些詞，因此結果完全可預期。
VOCABULARY = [
    # 中文（規格 .feature 的例子用的詞）
    "收據", "風景", "照片", "購買",
    "Target", "Costco", "7-11", "海邊",
    "可樂", "洋芋片", "咖啡", "牛奶", "衛生紙", "飲料",
    # 英文（雙語測試用的詞）
    "Receipt", "receipt", "Cola", "cola", "Chips", "chips",
    "coffee", "milk", "drinks", "drink",
]

# 同義／跨語言對照：左邊的詞出現時，右邊的詞也會被算進向量。
# 這是在假件裡「模擬」多語 embedding 的效果——真的 bge-m3 天生就有這個能力，
# 假件必須手動列出來，測試結果才可預期。
SYNONYMS = {
    "飲料": ["可樂", "咖啡", "牛奶"],
    "drinks": ["可樂", "咖啡", "牛奶", "Cola", "cola"],
    "drink": ["可樂", "咖啡", "牛奶"],
    "receipt": ["收據"],
    "Receipt": ["收據"],
    "cola": ["可樂"],
    "Cola": ["可樂"],
}


class FakeEmbeddings:
    """決定論向量：同樣的文字永遠得到同樣的數字，且不需要任何 AI 服務。

    做法：每個出現過的詞用「雜湊」（把文字換算成一個固定的數字）決定它落在
    向量的哪個位置，該位置 +1；最後做「正規化」（把整條向量縮放成長度 1，
    只留下方向），cosine 相似度比的才會是「內容」而不是「字數多寡」。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * config.EMBEDDING_DIM
        vector[0] = 0.1  # 保底值，避免全零向量讓 cosine 距離算出 NaN
        for word in self._words(text):
            vector[self._slot(word)] += 1.0
        length = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / length for v in vector]

    @staticmethod
    def _words(text: str) -> list[str]:
        found = [word for word in VOCABULARY if word in text]
        for word in list(found):
            found.extend(SYNONYMS.get(word, []))
        return found

    @staticmethod
    def _slot(word: str) -> int:
        digest = hashlib.md5(word.encode("utf-8")).hexdigest()
        return int(digest, 16) % config.EMBEDDING_DIM


class FixedClock:
    """固定的「現在時間」，對應規格的 Given 現在時間為 "2026-08-18 10:00"。"""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


# 規格例子出現過的文字 → 對應的假 VLM 結果。
# 規格新增例子時，在這裡補一筆即可。
KNOWN_UNDERSTANDINGS: dict[str, PhotoUnderstanding] = {
    "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10": PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    ),
}


def understanding_for_text(text: str) -> PhotoUnderstanding:
    """依規格步驟給的文字，取出對應的假 VLM 結果。"""
    if text not in KNOWN_UNDERSTANDINGS:
        raise KeyError(
            f"沒有為這段文字準備假的 VLM 結果：{text}\n"
            "請到 tests/fakes.py 的 KNOWN_UNDERSTANDINGS 補一筆。"
        )
    return KNOWN_UNDERSTANDINGS[text]


# 規格例子與雙語測試裡的問題 → 應該得到的判斷結果
DEFAULT_ROUTE_DECISIONS: dict[str, RouteDecision] = {
    # 規格 .feature 的兩個中文例子
    "有哪些在 Target 拍的收據？": RouteDecision(
        mode="metadata", category="收據", location="Target", recent=False
    ),
    "我最近買過什麼飲料？": RouteDecision(mode="vector", recent=True),
    # 雙語測試用的英文問題
    "What drinks did I buy recently?": RouteDecision(mode="vector", recent=True),
    # 英文條件型問題：條件值照原文抽（小寫 target），交給 SQL 的 ILIKE 去比對。
    # 注意這裡刻意沒抽 category="receipt"——抽了也對不到中文的「收據」，
    # 因為系統不做跨語言翻譯對映（design.md §8.3 的已知限制）。
    "Which receipts were taken at target?": RouteDecision(
        mode="metadata", location="target", recent=False
    ),
    # ---- Phase 34 詢問三路：實體路與待辦路（design3.md §6 的目標問句）----
    # entity_name 刻意兩種語言都填中文的「我的 MacBook」：實體名單有注入 prompt，
    # 所以模型該把問句對回**清單裡的原文**，而不是照抄問句寫法（ROUTE_PROMPT 的例外規則）。
    "跟我 MacBook 有關的全部": RouteDecision(
        mode="entity", entity_name="我的 MacBook"
    ),
    "Show me everything about my MacBook": RouteDecision(
        mode="entity", entity_name="我的 MacBook"
    ),
    "這週要交什麼？": RouteDecision(mode="task", due_within_days=7),
    # 規格 自然語言詢問.feature「問到待辦或到期時」那條 Rule 的問句**沒有問號**。
    # 假路由是逐字查表的，差一個全形問號就查不到 → 丟例外 → fallback 成語意查詢，
    # 規格驗收會紅在 search_mode。兩個鍵並存：有問號那個另有兩顆測試在用。
    "這週要交什麼": RouteDecision(mode="task", due_within_days=7),
    "What is due this week?": RouteDecision(mode="task", due_within_days=7),
    # 沒講期限＝列出全部待辦（含沒有到期日的那些）
    "我有哪些待辦？": RouteDecision(mode="task"),
}


class FakeRouter:
    """照例子指定回查法。

    遇到沒登記過的問題（例如模糊問題「幫我找找之前那個」）就丟例外，
    模擬「LLM 無法判斷」，用來驗證 fallback 一定會走語意查詢。

    entity_names 只是為了與 RouterClient 協定一致（Phase 34 加入）：
    假件用問句查表，不會真的看名單，但會把收到的清單記在 last_entity_names，
    讓測試驗得出「端點真的把資料庫裡的實體名單傳進來了」——
    與 FakeVLM 記 last_folders／last_entities 是同一個手法。
    """

    def __init__(self, decisions: dict[str, RouteDecision] | None = None) -> None:
        self.decisions = (
            DEFAULT_ROUTE_DECISIONS if decisions is None else decisions
        )
        self.last_entity_names: list[str] | None = None

    def route(self, question: str, entity_names: list[str]) -> RouteDecision:
        self.last_entity_names = entity_names
        if question not in self.decisions:
            raise RuntimeError(f"無法判斷問題類型：{question}")
        return self.decisions[question]


def _looks_english(text: str) -> bool:
    """粗略判斷一段文字是不是英文：完全沒有中日韓漢字就當英文。

    這只是假件用的簡易規則，用來重現「回答語言跟隨提問語言」的行為；
    產品程式碼裡沒有、也不需要這種判斷（真模型看得懂提問語言）。
    """
    return not any("一" <= ch <= "鿿" for ch in text)


class FakeAnswerLLM:
    """拿檢索結果模板化回答；空結果回查無句式。回答語言跟隨提問語言。

    行為固定，讓「回答提及可樂」「使用者獲得查無相關照片的回覆」
    「英文問題得到英文回答」都可以被驗證。
    """

    def answer(self, question: str, documents: list[Document]) -> str:
        english = _looks_english(question)

        if not documents:
            return "No matching photos found." if english else "查無相關照片。"

        pieces = []
        for document in documents:
            first_line = document.page_content.splitlines()[0]
            items = document.metadata.get("items") or []
            if english:
                item_text = ", ".join(items) if items else "none"
                pieces.append(f"{first_line} (items: {item_text})")
            else:
                item_text = "、".join(items) if items else "無"
                pieces.append(f"{first_line}（物品：{item_text}）")

        if english:
            return "Based on the photos: " + "; ".join(pieces)
        return "依照片內容回答：" + "；".join(pieces)


class FakeCloudChat:
    """長得像 ollama.Client 的最小假件：chat() 回固定內容、記下每次呼叫。

    給雲端實作（OllamaCloudVLM／OllamaCloudRouter／OllamaCloudAnswerer／
    OllamaCloudEntitySuggester）的單元測試用：建構真物件後把 _client 換成這個，
    練的是「回覆 → 解析」那一段，不碰網路（教訓見 ollama_cloud 模組 docstring——
    ollama.com 對 format= 不強制，解析層必須自己扛）。
    """

    def __init__(self, content: str | None):
        self._content = content
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=self._content))
