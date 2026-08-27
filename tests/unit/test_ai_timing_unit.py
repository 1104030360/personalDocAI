"""ai_timing 的單元測試（design4.md §5.1〜§5.3、Phase 41）。

驗的是「格式只有一份」這件事：五種 AI 呼叫（看圖／轉向量／判斷查法／產生回答／
再建議一個）都走同一個 helper，所以五個必要欄位（kind／backend／model／elapsed_s／ok）
的長相與順序在這裡一次釘死——之後才 grep 得出來（例如 grep "kind=embed"
只看轉向量花多久）。

兩條刻意的規矩：

1. **秒數只驗「非負」**，不寫死等於某個數字（design4 §5.3 明文）。
   假件跑得飛快（秒數會是 0.0），真模型一張圖要幾分鐘，寫死必壞。
2. **切後端一律用 `monkeypatch.setattr(config, "AI_BACKEND", …)`，連「本機」那半邊
   也明寫**。`AI_BACKEND` 是模組層的可變狀態（頁首開關撥的就是它），
   靠「預設值剛好是 local」會被同一個 process 裡別人撥過的值絆倒；
   monkeypatch 還會在每顆測試結束時自動還原。

本檔完全不碰網路、不碰資料庫：helper 只做計時與 log，with 區塊裡是 `pass` 或 `raise`。
"""

from __future__ import annotations

import logging
import re
from dataclasses import FrozenInstanceError

import pytest

from app.core import config
from app.services import indexing_service, vlm_service
from app.services.ai_timing import log_ai

# 抓結束行的秒數。design4 §5.2 要求一位小數，所以只會由 [0-9.] 組成
_秒數 = re.compile(r"elapsed_s=([0-9.]+)")

# 五個必要欄位（順序固定）。少一個就 grep 不出來
_必要欄位 = ("kind=", "backend=", "model=", "elapsed_s=", "ok=")


def _結束行(caplog) -> str:
    """抓出那一行結束行（每次呼叫前都只跑過一個 with 區塊）。"""
    結束 = [m for m in caplog.messages if m.startswith("AI 結束 ")]
    assert len(結束) == 1, f"預期恰好一行結束行，實得：{結束}"
    return 結束[0]


def test_成功時打出開始與結束兩行(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")

    with log_ai("vlm"):
        pass

    assert len(caplog.messages) == 2, f"預期恰好兩行，實得：{caplog.messages}"
    開始, 結束 = caplog.messages
    assert 開始.startswith("AI 開始 ")
    assert 結束.startswith("AI 結束 ")


def test_結束行帶ok為true與非負秒數(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")

    with log_ai("embed"):
        pass

    結束 = _結束行(caplog)
    assert "ok=true" in 結束
    抓到 = _秒數.search(結束)
    assert 抓到 is not None, f"結束行少了 elapsed_s 欄位：{結束}"
    # 只驗非負：秒數多少由當下的機器與模型決定，寫死就是自找麻煩
    assert float(抓到.group(1)) >= 0


def test_例外會往外傳且結束行標ok為false(caplog, monkeypatch):
    """helper 不吞例外：422／500／fallback 的語意一個字都不能被它改掉。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")

    with pytest.raises(RuntimeError, match="炸了"):
        with log_ai("route"):
            raise RuntimeError("炸了")

    assert "ok=false" in _結束行(caplog)


def test_embed的backend永遠是local就算開關撥到雲端(caplog, monkeypatch):
    """向量必須跟庫裡既有的 bge-m3 同源，所以 embeddings 從來不歸那顆開關管。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")

    with log_ai("embed"):
        pass

    結束 = _結束行(caplog)
    assert "backend=local" in 結束
    assert f"model={config.EMBEDDING_MODEL}" in 結束


def test_vlm跟著開關切換backend與model(caplog, monkeypatch):
    caplog.set_level(logging.INFO)

    monkeypatch.setattr(config, "AI_BACKEND", "local")
    with log_ai("vlm"):
        pass
    assert f"backend=local model={config.VLM_MODEL}" in _結束行(caplog)

    caplog.clear()
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")
    with log_ai("vlm"):
        pass
    assert f"backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}" in _結束行(caplog)


def test_三種文字用途都用LLM模型名(caplog, monkeypatch):
    """判斷查法／產生回答／再建議一個都是文字用途，用的是 LLM 那一顆。"""
    caplog.set_level(logging.INFO)

    for kind in ("route", "answer", "entity_suggest"):
        caplog.clear()
        monkeypatch.setattr(config, "AI_BACKEND", "local")
        with log_ai(kind):
            pass
        assert f"kind={kind} backend=local model={config.LLM_MODEL}" in _結束行(caplog)

        caplog.clear()
        monkeypatch.setattr(config, "AI_BACKEND", "cloud")
        with log_ai(kind):
            pass
        assert f"kind={kind} backend=cloud model={config.OLLAMA_CLOUD_LLM_MODEL}" in _結束行(caplog)


def test_備註接在結束行後面且五個欄位仍在(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")

    with log_ai("vlm") as 計時:
        計時.note = "text 3 字"

    結束 = _結束行(caplog)
    # 摘要接在最後面，不是插在五個欄位中間
    assert 結束.endswith("text 3 字")
    for 欄位 in _必要欄位:
        assert 欄位 in 結束, f"結束行少了 {欄位}：{結束}"
    assert "ok=true" in 結束


def test_model與備註含換行ANSI和控制字元時每筆log仍只有一個實體行(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    monkeypatch.setattr(
        config,
        "VLM_MODEL",
        "model\n偽造下一行\r\x1b[31m紅字\x1b[0m\x00",
    )

    with log_ai("vlm") as 計時:
        計時.note = "note\n偽造下一行\t\x1b[2J\x07"

    assert len(caplog.messages) == 2
    for 訊息 in caplog.messages:
        assert 訊息.splitlines() == [訊息]
        assert all(字元.isprintable() for 字元 in 訊息)


def test_過長model與備註會截斷且結束行仍保留五個必要欄位(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")
    monkeypatch.setattr(config, "VLM_MODEL", "x" * 10_000)

    with log_ai("vlm") as 計時:
        計時.note = "y" * 10_000

    開始, 結束 = caplog.messages
    assert 開始.count("x") <= 256
    assert 結束.count("x") <= 256
    assert 結束.count("y") <= 256
    for 欄位 in _必要欄位:
        assert 欄位 in 結束, f"結束行少了 {欄位}：{結束}"


def test_本機VLM的不可變目標可固定一次request實際使用的模型(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    vlm = vlm_service.OllamaVLM(model="request-local-vlm")
    目標 = vlm.timing_target
    monkeypatch.setattr(config, "AI_BACKEND", "cloud")

    with log_ai("vlm", target=目標):
        pass

    assert "backend=local model=request-local-vlm" in _結束行(caplog)
    with pytest.raises(FrozenInstanceError):
        setattr(目標, "model", "被改掉")


def test_雲端VLM暴露建構時選定的不可變計時目標(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "test-key")

    vlm = vlm_service.OllamaCloudVLM(model="request-cloud-vlm")
    目標 = vlm.timing_target

    assert 目標.backend == "cloud"
    assert 目標.model == "request-cloud-vlm"
    with pytest.raises(FrozenInstanceError):
        setattr(目標, "backend", "local")


def test_本機embedding_helper回傳client實際模型的不可變計時目標(monkeypatch):
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "request-local-embed")
    embeddings = indexing_service.build_ollama_embeddings()

    目標 = indexing_service.embedding_timing_target(embeddings)

    assert 目標.backend == "local"
    assert 目標.model == "request-local-embed"
    with pytest.raises(FrozenInstanceError):
        setattr(目標, "model", "被改掉")


def test_未知的kind直接炸掉且一行log都沒打(caplog, monkeypatch):
    """打錯 kind 寧可當場炸：沒有結束行的開始行是 grep 不到的孤兒。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "AI_BACKEND", "local")

    with pytest.raises(ValueError):
        with log_ai("亂打"):
            pass

    assert caplog.messages == []
