# 階段HHH REP：Phase 36 無線鏡頭（路線 B：即時預覽＋桌面遙控）

> 日期：2026-08-22　狀態：✅ 程式與自動化測試完成；**🛑 真機驗收（iPhone）待產品負責人手動**
> 對應 TODO：`2026-08-22-階段HHH-Phase36無線鏡頭-TODO.md`；計畫：`phase-36-無線鏡頭.md`
> 真機驗收操作手冊：scratchpad `task-36-report.md` §7（mkcert → iPhone 信任 → 13 步實測清單＋排查表）

## 實作邏輯

桌面 `POST /camera/session` 建 session（token 記憶體、`secrets.token_urlsafe`、TTL 600 秒、
新建汰舊、桌面 WS 斷線即失效）回 `{token, phone_url, qr_svg}`（segno 本機產 SVG、
LAN IP 由 request host 優先推導）。手機掃 QR 開 `camera-phone.html`（getUserMedia 後鏡頭）
→ WebRTC 視訊軌送桌面（host ICE、無 STUN/TURN）；`WS /camera/{token}/signal?role=desk|phone`
純 relay（SDP/ICE/`capture`/`switch`/`torch`；亂 token accept 前拒、64KB 上限、
每訊息重驗 TTL、binary frame 忽略）。任一邊快門＝手機 canvas 擷原生解析 JPEG
`POST /camera/{token}/photos` → **轉呼叫 photos 的 `_ingest_image()`**（八參數含 P35 的
corrections，415/422 語意一字不變）→ `set_latest` → 桌面收 `uploaded` 通知打
`GET /camera/{token}/latest` → 走三關彈窗鏈。彈窗鏈抽成**全站唯一一份**
`static/classify_chain.js`（upload.html／camera-desk.html 共用，render 回呼帶頁面差異；
upload 頁行為逐位元不變）。閃光採**能力回報制**（三時機重報、desk 未收到回報前停用、
iOS `applyConstraints` 靜默 resolve 用 `getSettings().torch` 復驗）。

## 步驟（TDD）

三個測試檔先紅（collection `ImportError`）再逐模組轉綠：`test_camera_session_unit.py`
（17 顆：TTL 邊界 600 秒、汰舊、invalidate、identity 比對、latest）→
`test_camera_endpoints.py`（27→修正輪 33 顆：404 族、WS relay 雙向、拒連、同角色讓位、
binary frame、過期停轉、64KB、404 先於 415、對端不在丟棄、desk 斷線關 phone）→
`test_camera_feature.py`（2 顆 **BDD binder 直掛唯讀規格** `無線鏡頭拍攝.feature` 的兩個
Example：快門入庫進未分類、未按快門 `count_photos()==0`；#TODO Rule 無 Example 不綁）。

## 測試方式與結果

- 全量：基線 272 → **324 passed＋2 skipped**（+52）；`OLLAMA_BASE_URL` 指死埠同顆數。
- `/openapi.json` 端點＝**17**（camera 三支在列、WS 不在——有測試釘住）。
- 過期測試全靠 monkeypatch `_now`（`time.monotonic` seam）、零 sleep、WS 測試連跑三次同顆。
- Review：opus reviewer 校準九條全 ✅（含 segno SVG 無網址明文、規格檔 mtime 實證未被動、
  binder 步驟與規格逐字相符）→ NEEDS_FIXES（I1 binary frame 炸 WS＋連帶滅配對／
  I2 過期後 relay 續命／I3 閃光降級通知可能永久遺失／I4 彈窗鏈 70 行複製兩份＋11 項 Minor
  ＋手冊 2 處誤導）→ fix round 1 全數處置 → scoped re-review ALL ADDRESSED
  （兩項誤判 OPEN 經直接證據裁定：report 在 scratchpad、M10 註記在 §9）。
- 實作者真瀏覽器冒煙（非自動化）：雙分頁配對 `connectionState=connected`＋960×540 預覽、
  切鏡頭 `replaceTrack` 不重新協商、torch 優雅降級、桌面關頁→兩條 HTTP 404、
  upload 頁鏈輸出與抽檔前逐位元相同；正式庫零觸碰。

## 遇到的問題與解法

- **WS 拒連的 close code**：ASGI 語意下 accept 前拒絕呈現為 HTTP 403／瀏覽器 1006，
  非自訂 4404——前端只依 accept 後的 4409（讓位）分支，註解同步修正。
- **mkcert 手冊兩處錯**：reviewer 以 openssl 證實「-install 後要重簽」是多餘誤導
  （CA 信任回溯）；真正要重簽的情境＝**區網 IP 換了**（SAN 綁死）。CLAUDE.md 已補
  `mkdir -p certs` 與 iOS「VPN 與裝置管理」入口。
- **iOS torch 靜默 resolve**：`applyConstraints` 對不支援約束不拋錯——改能力回報＋
  `getSettings().torch` 復驗，寧可少顆按鈕不要兩邊都以為燈亮著。

## 交產品負責人（🛑 停下）

1. **真機驗收（iPhone＋電腦同 Wi-Fi）**：先 `mkcert -install`（要密碼）→ 照 scratchpad
   `task-36-report.md` §7 手冊逐步（AirDrop rootCA.pem → 設定安裝＋憑證信任 → HTTPS 啟動
   → 掃 QR → 快門／切鏡頭／閃光降級／彈窗鏈 13 步）。
2. **裁決 ×3**：手機要不要補「重拍」鈕（計畫已釐清表＝三顆鈕 vs 規格 #TODO Rule 寫兩邊可重拍）；
   TTL 600 秒 vs 真模型看圖 2〜5 分/張（一次配對實拍 2〜4 張，可改 TTL 或活動續期）；
   殭屍桌面分頁（第二分頁開新 session 後第一分頁無提示，與 TTL 議題同綑）。
3. token 出現在網址與 uvicorn access log（全本地可接受，已注記——要收斂得改標頭/cookie）。
