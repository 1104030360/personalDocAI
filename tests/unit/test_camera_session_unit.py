"""無線鏡頭配對 session 的單元測試（Phase 36，計畫校準 3）。

這一層完全不碰 HTTP、不碰資料庫、不碰 AI——它只有一件事：
「這個 token 現在還算不算數」。所以測試也只驗這件事的四種變化：
建立、過期、汰舊、作廢，外加「最近一次拍到的東西」放在哪裡。

時間怎麼測：正式程式用 time.monotonic()（單調時鐘，只會往前走，
不受使用者調系統時間影響），但它被包在模組層的 _now() 裡，
測試 monkeypatch 掉 _now 就能「假裝過了 11 分鐘」，不必真的等 10 分鐘。
⚠ 這裡刻意不用 app.dependencies.get_now——那是「照片的上傳時間」注入點，
   兩件事不要混用（計畫校準 3 明文）。
"""

from __future__ import annotations

import pytest

from app.services import camera_session_service as sessions


@pytest.fixture(autouse=True)
def 乾淨的session(monkeypatch):
    """每個測試都從「一個 session 都沒有」開始。

    session 是模組層的單例（同時只有一個，計畫已釐清），
    monkeypatch 會在測試結束後自動把原值放回去，不會污染其他測試。
    """
    monkeypatch.setattr(sessions, "_session", None)


def 假裝過了(monkeypatch, 秒數: float) -> None:
    """把時基往前撥。撥完之後所有 _now() 的呼叫都會看到「未來」。"""
    現在 = sessions._now()
    monkeypatch.setattr(sessions, "_now", lambda: 現在 + 秒數)


# ---------------- 建立 ----------------


def test_有效期是十分鐘():
    """草案定的 10 分鐘＝600 秒（計畫「已釐清」表）。改這個數字要先改計畫。"""
    assert sessions.TOKEN_TTL_SECONDS == 600


def test_建立session會給一個夠長的token():
    session = sessions.create_session()

    # secrets.token_urlsafe(32) 出來的字串長度會超過 32；重點是「猜不到」
    assert isinstance(session.token, str)
    assert len(session.token) >= 32


def test_每次建立的token都不一樣():
    第一次 = sessions.create_session().token
    第二次 = sessions.create_session().token

    assert 第一次 != 第二次


def test_剛建好的session拿得到():
    session = sessions.create_session()

    assert sessions.get_session(session.token) is session


# ---------------- 過期 ----------------


def test_還沒滿十分鐘的token仍然有效(monkeypatch):
    session = sessions.create_session()
    假裝過了(monkeypatch, sessions.TOKEN_TTL_SECONDS - 1)

    assert sessions.get_session(session.token) is not None


def test_剛好滿十分鐘的token就失效(monkeypatch):
    """邊界：滿 600 秒即失效（>= TTL），不給模糊地帶。"""
    session = sessions.create_session()
    假裝過了(monkeypatch, sessions.TOKEN_TTL_SECONDS)

    assert sessions.get_session(session.token) is None


def test_超過十分鐘的token失效(monkeypatch):
    session = sessions.create_session()
    假裝過了(monkeypatch, sessions.TOKEN_TTL_SECONDS + 1)

    assert sessions.get_session(session.token) is None


# ---------------- 汰舊與作廢 ----------------


def test_新建session會汰掉舊的():
    """同時只有一個 session（計畫「已釐清」表）：第二台裝置配對，第一台就出局。"""
    舊的 = sessions.create_session()
    新的 = sessions.create_session()

    assert sessions.get_session(舊的.token) is None
    assert sessions.get_session(新的.token) is not None


def test_作廢之後token立刻失效():
    """桌面關頁＝desk 的 WebSocket 斷線＝呼叫這個函式（計畫校準 3）。"""
    session = sessions.create_session()

    sessions.invalidate(session.token)

    assert sessions.get_session(session.token) is None


def test_作廢別人的token不會殃及現有session():
    """亂 token 呼叫 invalidate 不可以把好好的 session 弄掉。"""
    session = sessions.create_session()

    sessions.invalidate("這不是任何人的token")

    assert sessions.get_session(session.token) is not None


def test_亂token拿不到session():
    sessions.create_session()

    assert sessions.get_session("亂打的token") is None


def test_沒有任何session時拿不到():
    assert sessions.get_session("任何東西") is None


# ---------------- 最近一次拍到的東西 ----------------


def test_還沒拍過時latest是空的():
    session = sessions.create_session()

    assert sessions.get_latest(session.token) is None


def test_設定之後拿得回同一份():
    """桌面靠這個把手機拍的那張照片接回三關彈窗鏈（計畫校準 5）。"""
    session = sessions.create_session()
    照片回應 = {"id": 7, "text": "一張收據"}

    sessions.set_latest(session.token, 照片回應)

    assert sessions.get_latest(session.token) == 照片回應


def test_設定latest會覆蓋前一張():
    session = sessions.create_session()
    sessions.set_latest(session.token, {"id": 1})

    sessions.set_latest(session.token, {"id": 2})

    assert sessions.get_latest(session.token) == {"id": 2}


def test_對亂token設定latest不會炸也不會留下東西():
    session = sessions.create_session()

    sessions.set_latest("亂打的token", {"id": 9})

    assert sessions.get_latest(session.token) is None


def test_過期之後連latest都拿不到(monkeypatch):
    session = sessions.create_session()
    sessions.set_latest(session.token, {"id": 3})

    假裝過了(monkeypatch, sessions.TOKEN_TTL_SECONDS + 1)

    assert sessions.get_latest(session.token) is None
