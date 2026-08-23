"""Ollama Cloud 共用小工具（2026-08-22 看圖開關；同日擴及詢問與實體建議）。

全系統唯一建雲端 Client 的地方——看圖（vlm_service.OllamaCloudVLM）、
詢問路由與回答（ask_workflow.OllamaCloudRouter／OllamaCloudAnswerer）、
實體建議（entity_suggestion_service.OllamaCloudEntitySuggester）都跟這裡拿，
host／API key／timeout 只需要對一次。

共同教訓（2026-08-22 真雲端煙霧）：ollama.com 的文件寫支援 format=JSON schema，
但本機 Ollama 是在解碼層做文法約束、雲端對 gemma4 實測**並不強制**——
模型會照 prompt 的樣式回 markdown 條列，Pydantic 直接炸 json_invalid。
所以每個需要結構化輸出的雲端實作都要三道保險：
①format= 照帶（哪天雲端強制了就直接受益）
②prompt 尾端接一段「只准回 JSON」的指令（各模組自帶，因為鍵名不同）
③回覆先用 extract_json_object() 寬鬆抽取，再交 Pydantic 驗證。
"""

from __future__ import annotations

from ollama import Client as OllamaClient

from app.core import config


def build_client(timeout: float = 300) -> OllamaClient:
    """建一個指向 Ollama Cloud 的官方 Client。

    建立 Client 不會連線（真正發請求的是 chat()，與 ChatOllama 同理）。
    timeout 預設 300 秒：雲端沒有本機那種載入模型的數分鐘等待，
    五分鐘還沒回一定是掛了——不給上限的話，掛掉的請求會永遠吊著。
    """
    return OllamaClient(
        host=config.OLLAMA_CLOUD_HOST,
        headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"},
        timeout=timeout,
    )


def extract_json_object(text: str) -> str:
    """從模型回覆裡撈出 JSON 物件（容忍 ```json 圍欄與前後贅字）。

    取第一個「{」到最後一個「}」之間的內容——模型偶爾在 JSON 前後加一句話
    或包個圍欄，整段直接餵 Pydantic 就會炸 json_invalid。
    沒有大括號就原樣回傳，讓 Pydantic 的錯誤訊息照實說
    （例如整段都是條列＝真的沒 JSON 可撈）。
    """
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text
