# Phase 36：無線鏡頭（路線 B：即時預覽＋桌面遙控）——釐清後待實作

> 🎯 快門是**人按的**（Auto Capture 已否決，D5 不動）。第一版對準 iPhone＋電腦**同一 Wi-Fi**。
> 用途：取代「手機拍完 → AirDrop → 桌面上傳」。

**目標：** 電腦顯示 QR → 手機掃了配對 → 手機瀏覽器開鏡頭 → **電腦即時看到取景** → 電腦或手機都能按快門／切鏡頭／開閃光（能力夠的裝置）→ 拍下的圖自動走既有 `POST /photos` → **三關彈窗只在電腦跳**。

---

## 已釐清（2026-08-22 產品負責人）

| # | 決策 |
|---|---|
| 路線 | **B（桌面主導）**。不是路線 A（掃了跳原生相機拍一張）。 |
| 手機上是什麼 | **瀏覽器取景頁**（getUserMedia）。掃 QR 後開的是本系統的手機頁，不是 iPhone 內建相機 App。 |
| 電腦畫面 | 即時預覽手機鏡頭；另有 Capture／Retake／切鏡頭／閃光。 |
| 手機也能控 | 同一組按鈕（快門、切鏡頭、閃光）。任一邊按，效果相同。 |
| 拍完之後 | 自動上傳進本系統，接既有分類鏈（抽屜→實體→待辦）。彈窗**只在桌面**。 |
| 配對 | QR 裡是臨時 token。單一使用者、沒有登入。草案：有效 **10 分鐘**、同時一個 session、桌面關頁即失效。token 存記憶體，不進資料庫，重啟 uvicorn 即失效。 |

### 這次推翻的舊字句

| 舊（design3 D6／本檔原草案） | 改成 |
|---|---|
| 手機用原生相機 App，不是瀏覽器頁 | 手機用本系統瀏覽器頁當鏡頭，才能即時預覽與桌面遙控 |
| 本 phase 無 WebSocket、桌面 2 秒輪詢最新照片 | 即時預覽需要 **WebRTC 傳影像**；配對／遙控指令用 **WebSocket 做 signaling** |
| 計畫先照路線 A 起草 | 整份改寫為路線 B |

**未推翻：** D5 人按快門、全本地、同一 Wi-Fi、不經雲端、三關彈窗在桌面、不自動拍入庫。

---

## 目標體驗（白話）

```text
電腦上傳頁按「用手機拍」
  → 出現 QR（內容＝ https://<區網IP>:8000/ui/camera-phone.html?token=…）
手機掃碼（與電腦同一 Wi-Fi）
  → 開本系統手機頁、要鏡頭權限
  → 電腦出現即時畫面（你對準什麼，電腦就看到什麼）

任一邊按快門
  → 拍一張 JPEG
  → 自動 POST /photos（VLM＋未分類＋存檔）
  → 電腦跳出既有三關彈窗
  → 手機顯示「到電腦上繼續」；預覽可繼續拍下一張（Retake＝放棄這張、不刪庫，回到取景）

閃光／切鏡頭：指令從電腦經 WebSocket 送到手機，手機改 getUserMedia 約束。
```

---

## 為什麼是 WebRTC，不是 2 秒輪詢

即時預覽＝連續畫面。把每幀 JPEG 輪詢上傳既慢又卡。標準做法：

| 通道 | 載什麼 |
|---|---|
| WebRTC | 手機 → 電腦的**視訊**（低延遲預覽） |
| WebSocket | 交換 SDP／ICE（誰連誰）＋遙控：`capture`／`torch`／`switch` |
| 既有 `POST /photos` | 快門按下後的**那一張靜態圖**（高解析，給 VLM） |

預覽用視訊軌；入庫用拍照當下擷成 JPEG。兩件事不要混成「把預覽幀當正式檔」。

本機兩台裝置、無 STUN／TURN 雲端：同一區網用 **host ICE candidate** 即可。不要接 coturn、不要第三方 QR／信令服務。

---

## HTTPS（B 的硬條件）

手機 Chrome／Safari 的 getUserMedia 需要 **安全來源**（HTTPS 或 localhost）。區網 IP 的 `http://192.168.x.x:8000` **開不了鏡頭**。

**【設計】** 本 phase 開發機用本機自簽憑證（建議 `mkcert`，一次信任後手機也認）。uvicorn 加 `--ssl-certfile`／`--ssl-keyfile`，聽 `0.0.0.0:8000`。QR 用 `https://<區網IP>:8000/...`。

文件寫清楚：第一次手機要信任憑證的步驟。不做雲端憑證、不依賴 ngrok。

---

## 端點與頁面（草案，實作時 TDD）

桌面既有 `/ui/upload.html` 加「用手機拍」。另兩頁：

| 路徑 | 誰用 |
|---|---|
| `/ui/camera-desk.html`（或上傳頁內嵌區塊） | 電腦：QR、即時預覽、遙控鈕、收到照片後接彈窗鏈 |
| `/ui/camera-phone.html` | 手機：取景、本機按鈕、上傳中提示 |

後端（token 全在記憶體）：

| 方法 | 路徑 | 作用 |
|---|---|---|
| `POST` | `/camera/session` | 桌面建 session，回 `{token, phone_url}` |
| `WS` | `/camera/{token}/signal` | 信令＋遙控 JSON |
| `POST` | `/camera/{token}/photos` | 手機送來的快門 JPEG → **轉呼叫既有上傳流程**（同一套 VLM／存檔／201 形狀） |
| `GET` | `/camera/{token}/latest` | 桌面拿最近一次上傳成功的回應（彈窗鏈用）；無則 204 |

亂 token／過期一律 404。不影響既有 `/photos`、`/ask` 測試。

控制指令（WS，誰按都一樣）：

```text
{ "type": "capture" }
{ "type": "switch" }          // 前／後鏡頭
{ "type": "torch", "on": true }  // 閃光；裝置不支援就忽略並回 {type:"torch-unsupported"}
```

---

## 已知限制（寫進計畫，實作不要裝死）

- **iPhone Safari 閃光（torch）不可靠。** 第一版：Android／支援的瀏覽器真的開手電筒；iPhone 不支援就按鈕停用或提示「請用手電筒」。切鏡頭＋快門在 iPhone 必須能用。
- 電腦與手機必須同一 Wi-Fi；訪客網路隔離會配對失敗。
- 預覽解析度可以低；入庫那張用拍照擷取、盡量接近後鏡頭全解析。
- Retake：若上一張**已經** `POST /photos` 成功，不自動刪照片（本專案不做刪除）。Retake＝回到取景再拍一張新的。畫面上的「重拍」若發生在上傳前，只丟棄尚未送出的幀。
- 不自動拍、不雲端、不新前端框架、不做多手機同時配對（一個 session）。

---

## 拆解（實作時逐條先紅再綠；本檔先鎖定方向）

1. session／token（建立、過期 10 分鐘、關頁失效、亂 token 404）。
2. QR：本機畫 SVG 或最小函式庫，內容＝HTTPS 區網 URL＋token。
3. 手機頁 getUserMedia（後鏡頭預設）＋本機快門／切鏡頭／閃光。
4. WebSocket 信令＋WebRTC 視訊到桌面；桌面遙控三鍵。
5. 快門 → JPEG → `POST /camera/{token}/photos` → 既有上傳；桌面收到 201 後走三關彈窗。
6. HTTPS 啟動說明寫進 CLAUDE.md 指令區（實作當下再補正確指令）。
7. 測試：token 過期／404；上傳轉呼叫不改既有 photos 契約；fake 不碰真鏡頭。瀏覽器實操驗收 iPhone＋電腦（無自動化鏡頭測試）。

---

## 2026-08-22 對現況校準（實作前補充；基線＝218 tests／14 端點／HEAD 0cabb45）

1. **端點數 14→17**：`POST /camera/session`＋`POST /camera/{token}/photos`＋
   `GET /camera/{token}/latest` 三支進 `/openapi.json`；**WS 路由不進 openapi.json**
   （FastAPI 行為），所以清點端點一律 17、WS 另以測試把關。
2. **QR 定案**：用 **segno**（純 Python、零相依、BSD；「最小函式庫」的實例）產 SVG 字串，
   `POST /camera/session` 回 `{token, phone_url, qr_svg}`——前端 `<div>` 塞 SVG 即顯示，
   不接任何第三方 QR 服務。segno 入 `requirements.txt`。
3. **session 設計細節**（新檔 `app/services/camera_session_service.py`，token 全在記憶體）：
   `secrets.token_urlsafe(32)`；時基用 `time.monotonic()` 包成模組層 `_now()`（測試
   monkeypatch 它做過期測試，不動 `get_now`——那是「上傳時間」的注入點，別混用）；
   有效 10 分鐘＝`TOKEN_TTL_SECONDS = 600` 常數；**同時一個 session＝新建即汰舊**；
   桌面端 WS 斷線＝session 立即失效（「桌面關頁即失效」的實作定義）。重啟 uvicorn 自然全失效。
4. **WS `/camera/{token}/signal` 純 relay**：`?role=desk|phone` 兩角色各一條連線，
   伺服器只把 JSON 原文轉發給另一端（SDP／ICE／`capture`／`switch`／`torch` 都一樣），
   不解讀內容。亂／過期 token：HTTP 三支一律 404；WS 直接拒絕（accept 前驗，
   `WebSocketException`／close code 4404）。同角色重連＝舊連線讓位。
5. **`POST /camera/{token}/photos` 轉呼叫既有流程**：與 `POST /photos` 相同的
   `File(...)`＋`Depends(get_vlm/get_embeddings/get_now)`，驗完 token 直接呼叫
   photos router 抽好的 `_ingest_image()`（415／422 語意一字不變；PDF 不收——鏡頭只拍 JPEG，
   非 JPEG/PNG 一律 415）。成功的 201 回應存進 session（`latest`），並回給手機。
   `GET /camera/{token}/latest`：有＝200 回同形狀 JSON、沒有＝204。桌面收到手機 WS
   `{type:"uploaded"}` 通知後打 latest 拿 201 內容 → 接既有三關彈窗鏈。
6. **LAN IP 推導**：`phone_url` 的 host＝request 的 Host（桌面用 `https://192.168.x.x:8000`
   開頁時天然正確）；host 是 localhost／127.0.0.1 時退而用 UDP socket 戲法
   （`connect(("8.8.8.8", 80))` 取本機區網 IP，不真的發包）偵測。scheme 沿用 request。
7. **頁面**：`upload.html` 加「用手機拍」連結 → 新頁 `camera-desk.html`（QR＋`<video>`
   遠端預覽＋Capture／Retake／切鏡頭／閃光四鈕＋201 後接彈窗鏈——復用既有
   `folder_modal.js`／`entity_modal.js`／`task_modal.js`，鏈邏輯照 upload.html 的寫法）；
   新頁 `camera-phone.html`（getUserMedia 後鏡頭 `facingMode:"environment"`、本機同組按鈕、
   快門＝`<video>` 幀畫進 canvas → `toBlob("image/jpeg")` 高解析擷取 → POST；上傳中提示
   「到電腦上繼續」）。WebRTC：手機為視訊發送端，host ICE candidate、無 STUN/TURN；
   兩頁 JS 分別內嵌或 `camera_desk.js`／`camera_phone.js`（cd-/cp- 前綴隔離，沿彈窗慣例）；
   禁 alert/confirm/prompt、動態內容 textContent（全站鐵律）。
8. **HTTPS（mkcert）**：`brew install mkcert`（含 `mkcert -install` 信任本機 CA）→
   `mkcert <區網IP> localhost 127.0.0.1` 產憑證放 `certs/`（入 .gitignore）→
   `uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile certs/key.pem
   --ssl-certfile certs/cert.pem`。**iPhone 信任步驟**（一次性）：把 `mkcert -CAROOT`
   的 `rootCA.pem` 傳到手機（AirDrop）→ 設定 App 安裝描述檔 → 設定 → 一般 → 關於 →
   憑證信任設定打開完全信任。指令與步驟寫進 CLAUDE.md 指令區＋本檔。
9. **測試邊界**：自動化測試涵蓋 session 生命週期（建立／過期／汰舊／亂 token 404）、
   WS relay（TestClient `websocket_connect` 雙端互轉＋拒連）、camera photos 轉呼叫
   （FakeVLM 走通、415／422、latest 200/204、上傳成功後 latest 有料）；
   **不自動化測真鏡頭／WebRTC 畫面**——iPhone＋電腦真機驗收由產品負責人手動執行
   （實作完成後停下來交棒）。既有 `/photos`、`/ask` 測試零改動。

## 驗收清單

- [ ] 同一 Wi-Fi：掃 QR → 電腦 1 秒內看到即時取景（不是 2 秒一張靜態圖）〔🛑 真機・待產品負責人；
      桌面雙分頁模擬已通過（connectionState=connected＋960×540 預覽）〕
- [ ] 電腦按快門與手機按快門都能入庫，桌面跳出抽屜彈窗鏈〔🛑 真機・待產品負責人〕
- [ ] 切鏡頭可用；閃光在不支援的裝置優雅降級〔🛑 真機・待產品負責人；能力回報制已實作〕
- [x] token 過期／亂 token 404；既有 pytest 顆數不因真鏡頭變少（324→341 全綠）；
      零 Ollama 安全網仍在（雙跑同顆數）；HTTPS 啟動驗證通過（--ssl 起服務、/health 200）
- [x] 全程無雲端信令、無第三方 QR 服務、無 Auto Capture；端點數＝17（WS 不計，測試釘住）

## 待釐清

無。可以進入實作（尚未開工）。
