"""無線鏡頭 router（Phase 36，路線 B：即時預覽＋桌面遙控）。

三支 HTTP ＋ 一條 WebSocket：

| 方法 | 路徑 | 誰打 | 作用 |
|---|---|---|---|
| POST | `/camera/session` | 桌面 | 建配對，回 token／手機網址／QR 的 SVG |
| WS | `/camera/{token}/signal?role=desk\\|phone` | 兩邊 | 信令（SDP／ICE）＋遙控指令，**純轉發** |
| POST | `/camera/{token}/photos` | 手機 | 快門那一張 → 轉呼叫既有上傳流程 |
| GET | `/camera/{token}/latest` | 桌面 | 拿最近一次上傳成功的 201 內容，接三關彈窗鏈 |

三件事情要先講清楚：

1. **這裡沒有新的上傳邏輯。** 快門那張照片走的是 photos router 的 `_ingest_image()`
   ——同一套看圖、同一套存檔、同一套「先進未分類」。所以 415／422 的語意
   一字不變，桌面收到的 201 也與 `POST /photos` 完全同形狀（計畫校準 5）。
2. **WebSocket 只是水管。** 伺服器不解讀訊息內容：SDP、ICE candidate、
   `capture`／`switch`／`torch` 全部原文轉發給另一端（計畫校準 4）。
   影像本身走 WebRTC 直接在兩台裝置之間傳，**不經過這台伺服器**。
3. **亂 token／過期 token**：帶 token 的兩支 HTTP（photos／latest）一律 404；
   WebSocket 則在 **accept 之前**就否決——依 ASGI 規格那是 HTTP 握手階段的拒絕，
   瀏覽器看到的是 **HTTP 403**、前端 close 事件拿到的是 1006，**不是** 4404
   （4404 只用在「已經連上、之後配對才失效」的情況，詳見下方 CLOSE_BAD_TOKEN）。

SQL 一個字都沒有——照片相關的資料庫動作全部由 photos router 與 repository 負責。
"""

from __future__ import annotations

import logging
import socket
from datetime import datetime

import segno
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
)
from langchain_core.embeddings import Embeddings

from app.api.routers import photos
from app.core import config
from app.dependencies import get_embeddings, get_now, get_vlm
from app.repositories import photo_repository
from app.schemas.camera import CameraSessionOut
from app.schemas.photo import UploadResponse
from app.services import camera_session_service, vlm_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["camera"])

# 鏡頭只拍照片：PDF 走一般上傳頁，不走這條（計畫校準 5）。
# 用既有清單「減掉」PDF 而不是另外抄一份，格式清單之後改動時兩邊不會走鐘。
CAMERA_CONTENT_TYPES = config.ALLOWED_CONTENT_TYPES - {config.PDF_CONTENT_TYPE}

# 手機取景頁的位置。QR 裡就是這個網址加上 ?token=…
PHONE_PAGE_PATH = "/ui/camera-phone.html"

# 這些 host 手機連不到（它們指的是「桌面自己」），要改用區網 IP
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

# 兩個角色，以及「另一端是誰」——relay 只需要這張對照表
DESK, PHONE = "desk", "phone"
OTHER_ROLE = {DESK: PHONE, PHONE: DESK}

# WebSocket 的關閉代碼。4000〜4999 是「應用程式自訂」的區間，
# 前端看到就知道是我們主動關的，不是網路斷了。
# ⚠ 只有「已經 accept 之後」關閉才送得出這些代碼。accept **之前**就拒絕的連線
#   （亂 token／角色不對）依 ASGI 規格是在 HTTP 握手階段否決，瀏覽器看到的是
#   **HTTP 403**、前端的 close 事件拿到的是 1006——不是 4404。前端因此不靠代碼
#   分辨那一種，只有 4409（讓位）才需要分支。
CLOSE_BAD_TOKEN = 4404      # 連上之後配對才失效（過期／桌面關頁）→ 請下線
CLOSE_SUPERSEDED = 4409     # 同角色有新連線進來 → 舊的讓位

# 單則訊息的長度上限（字元）。SDP 最長也就幾 KB，ICE candidate 與遙控指令是幾十位元組，
# 64K 綽綽有餘；超過的一律丟棄——這條水管是給信令用的，不是拿來傳檔案的。
MAX_MESSAGE_CHARS = 64 * 1024

# 目前活著的連線：{token: {"desk": WebSocket, "phone": WebSocket}}。
# 與 session 一樣全在記憶體、重啟即空。放在 router 而不是 service，
# 是因為 WebSocket 物件屬於「連線」這一層，session service 只管 token 算不算數。
_PEERS: dict[str, dict[str, WebSocket]] = {}


# ---------------- ① 建立配對 ----------------


def _lan_host() -> str:
    """偵測本機在區網裡的 IP（給手機連的那個位址）。

    手法叫 UDP socket 戲法：對一個外部位址「connect」一個 UDP socket——
    UDP 沒有握手，所以**不會真的送出任何封包**，但作業系統會為它挑好
    「要從哪張網卡出去」，於是 getsockname() 就吐出那張網卡的 IP。
    比讀 hostname 可靠（hostname 常常解析成 127.0.0.1）。

    真的失敗（例如完全沒有網路）就退回 localhost：QR 會掃不到，
    但頁面不該因此掛掉——桌面上仍看得到網址，人自己讀得出問題。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        logger.warning("偵測區網 IP 失敗，QR 會指向 localhost（手機連不到）")
        return "localhost"
    finally:
        probe.close()


def _phone_url(request: Request, token: str) -> str:
    """組出手機要打開的網址（計畫校準 6）。

    host 一律沿用「桌面現在是用什麼網址開這一頁的」——
    產品負責人用 https://192.168.x.x:8000 開頁時，QR 天然就是對的。
    只有在 host 指向桌面自己（localhost／127.0.0.1）時才需要猜區網 IP。
    scheme 也照抄：HTTPS 開頁 → QR 是 https（手機的鏡頭權限需要安全來源）。
    """
    hostname = (request.url.hostname or "").lower()
    if hostname in LOOPBACK_HOSTS or not hostname:
        hostname = _lan_host()
    port = request.url.port
    netloc = f"{hostname}:{port}" if port else hostname
    return f"{request.url.scheme}://{netloc}{PHONE_PAGE_PATH}?token={token}"


@router.post("/camera/session", status_code=201, response_model=CameraSessionOut)
def create_camera_session(request: Request) -> CameraSessionOut:
    """桌面開頁時打這一支：建配對、回手機網址與它的 QR。

    QR 在本機用 segno 畫成 SVG 字串（計畫校準 2）——不接任何雲端 QR 服務，
    前端 `<div>` 直接塞這段字串就顯示得出來。
    """
    session = camera_session_service.create_session()
    phone_url = _phone_url(request, session.token)
    # error="m" ＝中等容錯（約 15%）：手機拿歪一點、螢幕反光一點也掃得到。
    # svg_inline() 出來的字串沒有 XML 宣告，可以直接嵌進 HTML。
    qr_svg = segno.make(phone_url, error="m").svg_inline(scale=5)
    return CameraSessionOut(
        token=session.token, phone_url=phone_url, qr_svg=qr_svg
    )


# ---------------- ② 信令與遙控（WebSocket） ----------------


async def _close_quietly(websocket: WebSocket, code: int) -> None:
    """關掉一條連線，對面早就走掉也不要炸。

    這裡吞例外是刻意的：關連線只是善後動作，失敗了沒有任何人需要知道，
    更不該讓「桌面已經斷線」這件事再引發第二個錯誤。
    """
    try:
        await websocket.close(code=code)
    except (RuntimeError, WebSocketDisconnect):
        pass


@router.websocket("/camera/{token}/signal")
async def camera_signal(
    websocket: WebSocket, token: str, role: str = Query(...)
) -> None:
    """信令＋遙控的雙向水管。伺服器只轉發，不解讀內容（計畫校準 4）。

    兩端各開一條（`?role=desk` 與 `?role=phone`），任一端送進來的文字
    原封不動送到另一端。SDP／ICE 用它交換，`capture`／`switch`／`torch`
    也用它——對伺服器來說都只是字串。

    ⚠ **desk 斷線＝配對立刻失效**（計畫校準 3 的「桌面關頁即失效」）：
      之後手機打任何 HTTP 都是 404，得重掃新的 QR。
    ⚠ **TTL 在迴圈裡每收一則就重驗**：只在連線當下驗一次的話，
      配對過期後這條線還會繼續轉發，10 分鐘的期限形同虛設。
    """
    # 驗在 accept 之前：不合法的連線根本不建立
    if role not in OTHER_ROLE or camera_session_service.get_session(token) is None:
        raise WebSocketException(code=CLOSE_BAD_TOKEN, reason="配對無效或已過期")

    await websocket.accept()
    peers = _PEERS.setdefault(token, {})

    # 同角色重連＝舊的讓位（手機重新整理頁面時會走到這裡）。
    # 先把位子換成新連線再關舊的：反過來做的話，舊連線關閉到新連線登記之間
    # 有一小段「這個角色不存在」的空窗，那期間對面送來的訊息會被白白丟掉。
    previous = peers.get(role)
    peers[role] = websocket
    if previous is not None:
        await _close_quietly(previous, CLOSE_SUPERSEDED)

    try:
        while True:
            # 用 receive() 而不是 receive_text()：對面送來二進位 frame 時
            # receive_text() 會炸 KeyError('text')，desk 端還會連帶把整組配對作廢。
            # 這條水管只收 JSON 文字，其他一律安靜丟掉。
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            # 連上之後才過期：停止轉發並請兩端下線（前端會顯示「請重新掃 QR」）
            if camera_session_service.get_session(token) is None:
                other = peers.pop(OTHER_ROLE[role], None)
                if other is not None:
                    await _close_quietly(other, CLOSE_BAD_TOKEN)
                await _close_quietly(websocket, CLOSE_BAD_TOKEN)
                break

            text = message.get("text")
            if text is None:
                continue                      # 二進位 frame：不是信令，丟掉
            if len(text) > MAX_MESSAGE_CHARS:
                logger.warning(
                    "無線鏡頭信令訊息過大（%d 字元）已丟棄，role=%s", len(text), role
                )
                continue

            other = peers.get(OTHER_ROLE[role])
            if other is not None:
                await other.send_text(text)
                # 只記前 60 字元：看得出 {"type":"uploading"} 這類開頭就夠診斷了，
                # SDP 全文幾 KB 沒必要進 log。伺服器仍然不解讀內容（純轉發不變）。
                logger.info(
                    "信令轉發 %s→%s：%.60s", role, OTHER_ROLE[role], text
                )
            else:
                # 對面還沒連上就把訊息丟掉——不排隊、不重送。
                # 信令本來就是「現在講給現在在線的人聽」，補送舊的 SDP 只會更亂。
                # 記一筆丟棄：桌面「沒收到上傳中」這類問題，看這行就知道是哪端不在線。
                logger.info(
                    "信令丟棄 %s→%s（對面不在線）：%.60s",
                    role,
                    OTHER_ROLE[role],
                    text,
                )
    except WebSocketDisconnect:
        pass
    finally:
        # 被新連線頂掉的那條不要動登記表（那已經是別人的位子了）
        if peers.get(role) is websocket:
            peers.pop(role, None)
            if role == DESK:
                camera_session_service.invalidate(token)
                # 桌面走了，手機留著也沒用：直接請它下線，頁面才好顯示「配對已結束」
                phone = peers.pop(PHONE, None)
                if phone is not None:
                    await _close_quietly(phone, CLOSE_BAD_TOKEN)
        if not peers:
            _PEERS.pop(token, None)


# ---------------- ③ 快門那一張 ----------------


@router.post(
    "/camera/{token}/photos", status_code=201, response_model=UploadResponse
)
def upload_camera_photo(
    token: str,
    file: UploadFile = File(...),
    vlm: vlm_service.VLMClient = Depends(get_vlm),
    embeddings: Embeddings = Depends(get_embeddings),
    now: datetime | None = Depends(get_now),
) -> UploadResponse:
    """手機按下快門之後送上來的那一張（計畫校準 5）。

    這裡只多做兩件事：**驗 token** 與 **把 201 存進 session**；
    中間的入庫完全轉呼叫 photos router 的 `_ingest_image()`，
    所以「看不懂＝422 什麼都不存」「先進未分類」「原圖＋縮圖落地」
    全部與桌面上傳一模一樣，沒有第二套規則要維護。

    注意順序：token 先驗（亂 token 一律 404，連檔案格式都不必看）。
    """
    if camera_session_service.get_session(token) is None:
        raise HTTPException(status_code=404, detail="配對無效或已過期，請重新掃描 QR")

    if file.content_type not in CAMERA_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="上傳檔案必須為常見圖片格式（如 JPEG、PNG）",
        )

    image_bytes = file.file.read()
    logger.info(
        "無線鏡頭快門：收到 %d bytes（token %s…），開始入庫（AI 看圖見下一行）",
        len(image_bytes),
        token[:8],
    )

    # 與 POST /photos 一樣，在入庫前各讀一次清單（注入看圖 prompt 用）
    response = photos._ingest_image(
        image_bytes,
        file.content_type,
        vlm,
        embeddings,
        now,
        photo_repository.list_folders(),
        photo_repository.list_entities(),
        photo_repository.recent_corrections(limit=photos.FEW_SHOT_CORRECTIONS),
    )

    # 存進 session 給桌面來拿——手機端接著會用 WebSocket 送 {"type":"uploaded"} 通知桌面。
    # 走到這裡代表已經 201 了；422 那條路根本不會執行到，所以 latest 永遠是成功的那張。
    camera_session_service.set_latest(token, response)
    logger.info(
        "無線鏡頭快門：photo_id=%d 入庫完成，等桌面來拿並開彈窗鏈", response.id
    )
    return response


# ---------------- ④ 桌面來拿最近一張 ----------------


@router.get(
    "/camera/{token}/latest",
    response_model=UploadResponse,
    responses={204: {"description": "這次配對還沒有拍過任何照片"}},
)
def get_camera_latest(token: str) -> UploadResponse | Response:
    """桌面拿最近一次上傳成功的 201 內容，接既有三關彈窗鏈（計畫校準 5）。

    還沒拍過就回 204（No Content，空的回應）——不是錯誤，只是還沒輪到桌面做事。
    """
    if camera_session_service.get_session(token) is None:
        raise HTTPException(status_code=404, detail="配對無效或已過期，請重新掃描 QR")

    latest = camera_session_service.get_latest(token)
    if latest is None:
        # 直接回一個 Response 物件＝跳過 response_model，才送得出「沒有內容」
        return Response(status_code=204)
    logger.info("無線鏡頭：桌面已取走 photo_id=%d，接著開彈窗鏈", latest.id)
    return latest
