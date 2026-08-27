"""無線鏡頭三支 HTTP 端點＋一條 WebSocket 的整合測試（Phase 36）。

涵蓋計畫校準 4／5／6／9 的自動化邊界：
① `POST /camera/session`：token、phone_url（含 LAN IP 推導）、qr_svg。
② `WS /camera/{token}/signal`：純 relay、亂／過期 token 拒連、
   同角色重連舊讓位、**desk 斷線＝session 立刻失效**（＝計畫的「桌面關頁即失效」）。
③ `POST /camera/{token}/photos`：轉呼叫既有上傳流程（415／422 語意一字不變）。
④ `GET /camera/{token}/latest`：200／204／404。

⚠ 不自動化測真鏡頭與 WebRTC 畫面（計畫校準 9）——那是產品負責人的真機驗收。
   這裡驗的是「伺服器這一側」：token 生命週期、訊息有沒有正確轉發、照片有沒有真的入庫。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routers import camera
from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import camera_session_service as sessions
from app.services import staging_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import FakeVLM, make_jpeg_bytes, make_pdf_bytes, make_png_bytes

專案根目錄 = Path(__file__).resolve().parents[2]

看得懂的收據 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def 乾淨的session(monkeypatch):
    """每個測試都從「沒有任何配對」開始（session 是模組層單例）。

    連線登記表也一起清：WebSocket 測試留下的殘骸不該影響下一個測試。
    """
    monkeypatch.setattr(sessions, "_session", None)
    monkeypatch.setattr(camera, "_PEERS", {})


@pytest.fixture
def 配對(client) -> str:
    """建一個 session，回傳 token（桌面開頁時做的第一件事）。"""
    response = client.post("/camera/session")
    assert response.status_code == 201, response.text
    return response.json()["token"]


def 拍一張(client, token: str, understanding=看得懂的收據, **kwargs):
    """模擬手機按下快門：把一張真的 JPEG 送到鏡頭上傳端點。

    增量五之後這一支只「受理」（202），不入庫；要看到照片得自己扮演 worker
    把任務跑完（用 tests/conftest.py 的 跑完任務()）。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(understanding)
    files = kwargs.pop("files", {"file": ("shot.jpg", make_jpeg_bytes(), "image/jpeg")})
    return client.post(f"/camera/{token}/photos", files=files)


def 拍一張並跑完任務(client, token: str, understanding=看得懂的收據, **kwargs) -> dict:
    """拍一張 → 斷言 202 → 把那個任務跑完 → 回 {"job_id", "response", "job"}。"""
    response = 拍一張(client, token, understanding, **kwargs)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    跑完任務(job_id)
    return {"job_id": job_id, "response": response, "job": 目前的任務清單().get(job_id)}


# ---------------- ① POST /camera/session ----------------


def test_建立session回token與手機網址與qr(client):
    response = client.post("/camera/session")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"token", "phone_url", "qr_svg"}
    assert len(body["token"]) >= 32
    # 手機掃到的就是「本系統的取景頁＋這次的 token」（計畫「目標體驗」）
    assert body["phone_url"].endswith(f"/ui/camera-phone.html?token={body['token']}")


def test_qr是可以直接塞進網頁的svg字串(client):
    """segno 產的 inline SVG（計畫校準 2）：沒有 XML 宣告，<div> 一塞就顯示。

    不接任何第三方 QR 服務——QR 的內容在自己家裡畫完。
    """
    qr = client.post("/camera/session").json()["qr_svg"]

    assert qr.startswith("<svg")
    assert "<?xml" not in qr


def test_qr的顯示尺寸夠大讓長網址也掃得到():
    """QR 的 CSS 顯示上限決定「每一格有多少 px」＝手機掃不掃得到。

    2026-08-25 真機踩過：桌面頁改用 Bonjour 主機名（`<主機名>.local`）開之後，
    網址從 93 字元變成 118 字元 → QR 從 49 格變 53 格，
    而當時 `max-width` 是 15rem（240px），每格只剩 240/53 ≈ 4.5px，**iPhone 掃不到**。
    放大到 20rem（320px）後每格 6.0px，兩種網址都好掃。

    釘住它的理由：這是**安靜壞掉**的那種 bug——QR 看起來正常、只是掃不進去，
    排版時有人為了版面把它縮小，沒有人會聯想到「鏡頭功能壞了」。
    """
    樣式原始碼 = (專案根目錄 / "app" / "static" / "style.css").read_text(encoding="utf-8")

    assert ".cd-qr svg { width: 100%; height: auto; max-width: 20rem; }" in 樣式原始碼


def test_手機網址沿用桌面開頁的host(client):
    """桌面用 https://192.168.x.x:8000 開頁時，QR 天然就是對的網址（計畫校準 6）。

    TestClient 的 host 是 testserver，所以這裡驗「有照用」。
    """
    phone_url = client.post("/camera/session").json()["phone_url"]

    assert phone_url.startswith("http://testserver/ui/camera-phone.html")


def test_用localhost開頁時改用區網ip(client, monkeypatch):
    """localhost 的網址手機連不到，所以退而偵測本機的區網 IP（計畫校準 6）。

    偵測手法（UDP socket 戲法）在測試裡換成固定值——測試不該依賴這台機器的網路。
    """
    monkeypatch.setattr(camera, "_lan_host", lambda: "10.0.0.34")

    phone_url = client.post("/camera/session", headers={"host": "localhost:8000"}).json()[
        "phone_url"
    ]

    assert phone_url.startswith("http://10.0.0.34:8000/ui/camera-phone.html")


def test_再建一個session會汰掉舊的(client):
    """同時只有一組配對：舊 token 立刻變成陌生人（HTTP 一律 404）。"""
    舊token = client.post("/camera/session").json()["token"]

    client.post("/camera/session")

    assert client.get(f"/camera/{舊token}/latest").status_code == 404


# ---------------- ② WS /camera/{token}/signal ----------------


def test_訊息從桌面原文轉發到手機(client, 配對):
    """伺服器只負責轉發，不解讀內容（計畫校準 4）——SDP／ICE／遙控指令一視同仁。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            desk.send_text('{"type":"capture"}')

            assert phone.receive_text() == '{"type":"capture"}'


def test_訊息從手機原文轉發到桌面(client, 配對):
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            phone.send_text('{"type":"offer","sdp":"v=0…"}')

            assert desk.receive_text() == '{"type":"offer","sdp":"v=0…"}'


def test_亂token連不上websocket(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/camera/亂打的token/signal?role=desk"):
            pass


def test_過期token連不上websocket(client, 配對, monkeypatch):
    現在 = sessions._now()
    monkeypatch.setattr(sessions, "_now", lambda: 現在 + sessions.TOKEN_TTL_SECONDS + 1)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/camera/{配對}/signal?role=desk"):
            pass


def test_沒帶角色連不上websocket(client, 配對):
    """role 是必填：伺服器要知道這條線是哪一端，才知道訊息要轉給誰。"""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/camera/{配對}/signal"):
            pass


def test_角色不是desk或phone就連不上(client, 配對):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/camera/{配對}/signal?role=第三者"):
            pass


def test_桌面斷線session立刻失效(client, 配對):
    """「桌面關頁即失效」的實作定義（計畫校準 3）。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk"):
        pass

    assert sessions.get_session(配對) is None
    assert client.get(f"/camera/{配對}/latest").status_code == 404


def test_桌面斷線會把手機的連線也關掉(client, 配對):
    """桌面走了，手機那條線留著也沒用——直接請它下線，頁面才好顯示「配對已結束」。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
        with client.websocket_connect(f"/camera/{配對}/signal?role=desk"):
            pass

        with pytest.raises(WebSocketDisconnect):
            phone.receive_text()


def test_手機斷線session還在(client, 配對):
    """手機收訊不好斷一下線很正常，配對不該因此作廢——重新掃同一張 QR 就能回來。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=phone"):
        pass

    assert sessions.get_session(配對) is not None


def test_同角色重連舊連線讓位(client, 配對):
    """手機重新整理頁面＝第二條 phone 連線；訊息要走新的那條（計畫校準 4）。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone"):
            with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as 新手機:
                desk.send_text('{"type":"switch"}')

                assert 新手機.receive_text() == '{"type":"switch"}'


def test_對端不在時訊息丟掉不會炸(client, 配對):
    """手機還沒連上就先按鈕：訊息直接丟掉，連線要好好活著（不排隊、不重送）。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        desk.send_text('{"type":"capture"}')
        desk.send_text('{"type":"switch"}')

        # 手機後來才連上：先前丟掉的不補送，之後的照樣轉發
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            desk.send_text('{"type":"torch","on":true}')

            assert phone.receive_text() == '{"type":"torch","on":true}'


def test_二進位frame不會弄斷連線(client, 配對):
    """本系統的信令只有 JSON 文字；瀏覽器若送來二進位 frame，丟掉就好。

    修正前這裡會炸 KeyError('text')：desk 端連帶跑進 finally 把整組配對作廢，
    等於「對面傳錯一個封包，配對就死了」。
    """
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            phone.send_bytes(b"\x00\x01\x02")  # 不是文字，應該被忽略

            phone.send_text('{"type":"offer","sdp":"v=0"}')
            assert desk.receive_text() == '{"type":"offer","sdp":"v=0"}'
    # 配對沒有被那個二進位 frame 弄死（desk 是正常結束才失效的）
    assert sessions.get_session(配對) is None


def test_過大的訊息被丟掉但連線還在(client, 配對):
    """SDP／ICE／遙控指令都遠小於上限；異常巨大的訊息不轉發，也不斷線。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            desk.send_text("x" * (camera.MAX_MESSAGE_CHARS + 1))

            desk.send_text('{"type":"capture"}')
            assert phone.receive_text() == '{"type":"capture"}'


def test_連上之後才過期就停止轉發並關閉兩端(client, 配對, monkeypatch):
    """TTL 不能只在連線當下驗一次——已連上的線也要跟著過期（不然 10 分鐘形同虛設）。"""
    with client.websocket_connect(f"/camera/{配對}/signal?role=desk") as desk:
        with client.websocket_connect(f"/camera/{配對}/signal?role=phone") as phone:
            現在 = sessions._now()
            monkeypatch.setattr(sessions, "_now", lambda: 現在 + sessions.TOKEN_TTL_SECONDS + 1)

            desk.send_text('{"type":"capture"}')

            # 這則不會被轉發，兩端都被請下線
            with pytest.raises(WebSocketDisconnect):
                phone.receive_text()


# ---------------- ③ POST /camera/{token}/photos ----------------


def test_手機拍的照片走的是既有受理流程(client, 配對):
    """轉呼叫 photos 的 _accept_upload（design5.md §5）：202 的形狀與 POST /photos 一模一樣。"""
    response = 拍一張(client, 配對)

    assert response.status_code == 202, response.text
    body = response.json()
    # 與電腦上傳同一個模型：三個鍵，不多不少
    assert set(body) == {"job_id", "filename", "content_type"}
    assert body["filename"] == "shot.jpg"
    assert body["content_type"] == "image/jpeg"
    assert len(body["job_id"]) == 32  # uuid4().hex


def test_快門當下資料庫還沒有那一列而staging檔在(client, 配對):
    """★ 連拍的前提：這一刻什麼慢動作都還沒發生（design5.md §4.2）。"""
    job_id = 拍一張(client, 配對).json()["job_id"]

    assert photo_repository.count_photos() == 0
    assert staging_service.staging_path(job_id, "image/jpeg").is_file()
    job = 目前的任務清單().get(job_id)
    assert job["status"] == "queued"
    # 來源要標成 camera：進度面板之後要分得出「電腦上傳的」與「手機拍的」
    assert job["source"] == "camera"
    assert job["ai_backend"] == "local"  # 入列當下的快照（D14）


def test_好token可以立刻再拍第二張(client, 配對):
    """★ design5.md §9 明列的一條：連拍的後端前提。

    第一張還沒被任何人分析（我們刻意**不跑任務**），第二張就要收得下來——
    這正是「拍完就能再拍」在後端這一側的意思。兩張各自一筆 job、各自一個 staging 檔。
    """
    第一張 = 拍一張(client, 配對)
    第二張 = 拍一張(client, 配對)

    assert 第一張.status_code == 202, 第一張.text
    assert 第二張.status_code == 202, 第二張.text
    第一個job = 第一張.json()["job_id"]
    第二個job = 第二張.json()["job_id"]
    assert 第一個job != 第二個job, "兩張照片不可以共用同一個 job_id"
    assert staging_service.staging_path(第一個job, "image/jpeg").is_file()
    assert staging_service.staging_path(第二個job, "image/jpeg").is_file()
    assert len(目前的任務清單().list_open()) == 2


def test_連拍兩張各自跑完任務都會入庫(client, 配對):
    """兩筆任務互不干擾：各跑各的，最後收件箱有兩張。"""
    job1 = 拍一張(client, 配對).json()["job_id"]
    job2 = 拍一張(client, 配對).json()["job_id"]

    跑完任務(job1)
    跑完任務(job2)

    assert photo_repository.count_photos() == 2
    assert 目前的任務清單().list_open() == [], "兩筆都成功＝兩筆都被刪掉"


def test_手機拍的照片跑完任務之後真的進了資料庫(client, 配對):
    結果 = 拍一張並跑完任務(client, 配對)

    assert photo_repository.count_photos() == 1
    assert 結果["job"] is None, "成功＝job 被刪掉（契約備忘 §3.1）"
    列 = photo_repository.list_photos_in_folder(
        next(f["id"] for f in photo_repository.list_folders() if f["is_inbox"])
    )[0]
    row = photo_repository.fetch_photo(列["id"])
    assert row["text"] == 看得懂的收據.text
    # 一律先進未分類，等人在待決定頁定案（design2.md D3 的定案流程沒有被繞過）
    assert photo_repository.get_folder(row["folder_id"])["is_inbox"] is True


def test_亂token不能上傳照片(client):
    assert 拍一張(client, "亂打的token").status_code == 404


def test_亂token加上非法格式回404不是415(client):
    """檢查順序是刻意的：token 先驗——陌生人連「你檔案格式不對」都不該聽到。"""
    response = 拍一張(client, "亂打的token", files={"file": ("note.txt", b"x", "text/plain")})

    assert response.status_code == 404


def test_亂token連staging都不會寫(client):
    """design5.md §8 第 2 列：token 無效 → 404，**不讀檔**、不建任務、不落 staging。"""
    拍一張(client, "亂打的token")

    assert 目前的任務清單().list_open() == []
    assert not config.DATA_DIR.exists()


def test_過期token不能上傳照片(client, 配對, monkeypatch):
    現在 = sessions._now()
    monkeypatch.setattr(sessions, "_now", lambda: 現在 + sessions.TOKEN_TTL_SECONDS + 1)

    assert 拍一張(client, 配對).status_code == 404
    assert photo_repository.count_photos() == 0


def test_非圖片格式回415什麼都不存(client, 配對):
    """415 的語意與 POST /photos 一字不變（design5.md §8 第 1 列）。"""
    response = 拍一張(client, 配對, files={"file": ("note.txt", b"x", "text/plain")})

    assert response.status_code == 415
    assert photo_repository.count_photos() == 0
    assert 目前的任務清單().list_open() == []
    assert not config.DATA_DIR.exists()


def test_鏡頭不收pdf(client, 配對):
    """鏡頭只拍 JPEG：PDF 走一般上傳頁，不走這條（415，不是 202）。"""
    response = 拍一張(
        client, 配對, files={"file": ("scan.pdf", make_pdf_bytes(), "application/pdf")}
    )

    assert response.status_code == 415
    assert 目前的任務清單().list_open() == []


def test_看不懂的照片是任務失敗不是HTTP失敗(client, 配對):
    """★ 語意搬家了：「看不懂」現在是 **worker** 的結局，不是 HTTP 的。

    對外的最終結果一字不變（design5.md D10）：什麼都不存。
    變的只是「使用者什麼時候知道」——從當場 422 變成進度面板上出現一列失敗。
    """
    結果 = 拍一張並跑完任務(client, 配對, understanding=PhotoUnderstanding(understood=False))

    assert 結果["response"].status_code == 202, "HTTP 這一層不判斷看不看得懂"
    assert 結果["job"]["status"] == "failed"
    assert photo_repository.count_photos() == 0
    assert not staging_service.staging_path(結果["job_id"], "image/jpeg").exists()


def test_png也收(client, 配對):
    """快門擷的是 JPEG，但格式檢查沿用既有清單，PNG 一樣通過。"""
    response = 拍一張(client, 配對, files={"file": ("shot.png", make_png_bytes(), "image/png")})

    assert response.status_code == 202


# ---------------- ④ GET /camera/{token}/latest（行為變窄）----------------


def test_還沒拍過回204(client, 配對):
    response = client.get(f"/camera/{配對}/latest")

    assert response.status_code == 204
    assert response.content == b""


def test_拍過之後latest仍然是204(client, 配對):
    """★ 行為變窄（design5.md §5、§1.1）：入列**不再**寫 latest。

    以前：手機拍完 → 伺服器把 201 內容存進 session → 桌面來拿 → 開三關彈窗鏈。
    現在：快門當下只有一個 job_id，根本沒有「那張照片的歸類 payload」可以存
          （VLM 都還沒看圖）。桌面改看全站進度面板（Phase 67），
          歸類一律在待決定頁做（design5.md D13）。

    端點刻意保留（§5 沒說刪、端點數算式要它），只是永遠回 204。
    """
    拍一張並跑完任務(client, 配對)

    response = client.get(f"/camera/{配對}/latest")

    assert response.status_code == 204
    assert response.content == b""


def test_latest不再宣告UploadResponse這種回應形狀(client):
    """openapi 那一面：不可以宣告一個永遠不會出現的 200 形狀。

    留著 response_model=UploadResponse 的話，/docs 上會寫「這支會回整份照片內容」，
    而它其實永遠只回 204——文件說謊比沒有文件更糟。
    """
    spec = client.get("/openapi.json").json()["paths"]["/camera/{token}/latest"]["get"]

    assert "200" not in spec["responses"], spec["responses"]
    assert "204" in spec["responses"]


def test_亂token拿不到latest(client):
    assert client.get("/camera/亂打的token/latest").status_code == 404


# ---------------- ⑤ 端點清點 ----------------


def test_三支端點都在openapi裡而websocket不在(client):
    """WS 路由不進 openapi.json 是 FastAPI 的行為（計畫校準 1）——Phase 36 當時端點數 17
    （2026-08-22 AI 後端開關 +2 成 19；總數清點在 test_ask_three_paths.py）。"""
    paths = client.get("/openapi.json").json()["paths"]

    assert "post" in paths["/camera/session"]
    assert "post" in paths["/camera/{token}/photos"]
    assert "get" in paths["/camera/{token}/latest"]
    assert "/camera/{token}/signal" not in paths
