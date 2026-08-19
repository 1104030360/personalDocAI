"""測試用的假件。真 AI／真時鐘的替身，讓測試結果可預期。"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime

from app.core import config
from app.services.vlm_service import PhotoUnderstanding


class FakeVLM:
    """考試用的固定答案卡，不是正式看圖系統。

    測試會先指定「請當作收據、店名 Target」；understand() 照念，不呼叫 Ollama。
    沒給 result 時預設 understood=False（規格：看不懂 → 422、什麼都不存）。
    """

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0

    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        self.calls += 1
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
