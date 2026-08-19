"""pytest 專用假件。正式上傳走 OllamaVLM，不會讀這個檔。"""

from __future__ import annotations

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
