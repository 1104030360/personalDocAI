"""無線鏡頭的配對 session（Phase 36，計畫校準 3）。

一句話：這裡管的是「手機掃到的那個 token 現在還算不算數」，**沒有別的**。

刻意做的取捨（全部來自計畫的「已釐清」表）：
- **token 全在記憶體，不進資料庫**：它是一次性的配對憑證，不是資料。
  重啟 uvicorn ＝ 全部失效，這是預期行為，不是 bug。
- **同時只有一個 session**：模組層一個單槽（`_session`）就夠了，不需要字典。
  第二台裝置配對＝第一台出局（`create_session()` 汰舊）。
- **有效 10 分鐘**（`TOKEN_TTL_SECONDS`）。
- **桌面關頁即失效**：實作定義是「desk 角色的 WebSocket 斷線時呼叫 `invalidate()`」，
  由 `api/routers/camera.py` 負責觸發——這一層只提供動作，不知道 WebSocket 是什麼。

時基為什麼是 `time.monotonic()`：它是「單調時鐘」，只會往前走，
不受使用者調系統時間、也不受 NTP 校時影響——算「過了幾秒」最可靠。
包成模組層的 `_now()` 是為了讓測試 monkeypatch 它假裝過了 11 分鐘。
⚠ 不要拿 `app.dependencies.get_now` 來用：那是「照片的上傳時間」注入點，
   與這裡的「配對過期沒」是兩件事，混用會讓兩邊的測試互相絆倒。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

# 配對有效期。草案定 10 分鐘（計畫「已釐清」表）——改這個數字等於改規格。
TOKEN_TTL_SECONDS = 600

# token 的隨機位元組數。32 bytes 經 URL-safe base64 之後是 43 個字元，
# 放進 QR 綽綽有餘，也遠遠猜不到（單一使用者、沒有登入，靠的就是「猜不到」）。
TOKEN_BYTES = 32


@dataclass
class CameraSession:
    """一次配對。

    latest ＝ 這次配對「最近一次上傳成功」的回應內容：
    手機拍完把 201 存在這裡，桌面用 GET /camera/{token}/latest 取走接彈窗鏈。
    型別寫 Any 是因為這一層不該知道 UploadResponse 長什麼樣——它只是個保管箱。
    """

    token: str
    created_at: float
    latest: Any | None = None


# 唯一的那一組配對。None ＝ 現在沒有人配對。
_session: CameraSession | None = None


def _now() -> float:
    """現在的時基（秒）。測試會 monkeypatch 這個函式，正式執行永遠是單調時鐘。"""
    return time.monotonic()


def create_session() -> CameraSession:
    """建立一組新的配對，並**汰掉舊的**（同時只有一個）。"""
    global _session
    _session = CameraSession(
        token=secrets.token_urlsafe(TOKEN_BYTES), created_at=_now()
    )
    return _session


def get_session(token: str) -> CameraSession | None:
    """拿出這個 token 對應的配對；不存在、對不上或已過期一律回 None。

    呼叫端（router）看到 None 就一律回 404／拒連——
    「亂 token」與「過期 token」對外是同一件事，不必分兩種錯誤。
    """
    global _session
    session = _session                       # 先抓成區域變數，下面全程對同一個物件判斷
    if session is None or session.token != token:
        return None
    # 滿 10 分鐘即失效（>= 不留模糊地帶），順手把過期的清掉。
    # 清的時候比對「是不是同一個物件」（is）而不是只看 token：
    # uvicorn 是多執行緒的，這中間若有人建了新配對，_session 已經換人，
    # 不可以把新的那組一起抹掉。
    if _now() - session.created_at >= TOKEN_TTL_SECONDS:
        if _session is session:
            _session = None
        return None
    return session


def invalidate(token: str) -> None:
    """讓這個 token 立刻失效（桌面關頁／WebSocket 斷線時呼叫）。

    傳進來的若不是目前這組配對就什麼都不做——
    舊分頁斷線時不可以把新配對一起弄掉（比對用 is，理由同 get_session）。
    """
    global _session
    session = _session
    if session is not None and session.token == token and _session is session:
        _session = None


def set_latest(token: str, payload: Any) -> None:
    """記住這次配對最近一次上傳成功的回應。

    token 已失效就靜靜不做事：那代表這張照片的主人早就走了，
    存起來也沒有人會來拿（照片本身仍然入庫了，這裡只是配對的暫存）。
    """
    session = get_session(token)
    if session is not None:
        session.latest = payload


def get_latest(token: str) -> Any | None:
    """取出最近一次上傳成功的回應；還沒拍過或 token 已失效都是 None。"""
    session = get_session(token)
    return session.latest if session is not None else None
