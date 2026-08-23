# 階段HHH TODO：Phase 36 無線鏡頭（路線 B：即時預覽＋桌面遙控）

> 日期：2026-08-22　狀態：✅ 程式與自動化測試完成（見同名 REP）；🛑 真機驗收待產品負責人
> 依據：`docs/plan/unfinish/phase-36-無線鏡頭.md`（路線 B 已釐清＋2026-08-22 校準段）＋design3.md D5/D6

## 實作邏輯

電腦顯示 QR（內容＝HTTPS 區網 URL＋臨時 token）→ 手機掃碼開本系統取景頁
（getUserMedia）→ WebRTC 把手機視訊軌即時送到桌面（同區網 host ICE、無 STUN/TURN）→
WebSocket `/camera/{token}/signal` 當信令＋遙控通道（capture／switch／torch，純 relay）→
任一邊按快門＝手機 canvas 擷高解析 JPEG `POST /camera/{token}/photos` → **轉呼叫既有
`_ingest_image()`**（同一套 VLM／未分類／存檔／201）→ 桌面收 WS 通知打
`GET /camera/{token}/latest` 拿 201 內容 → 接既有三關彈窗鏈。token 全在記憶體
（10 分鐘、單一 session、桌面斷線即失效）；快門永遠是人按的（D5）。

## 步驟（後端 TDD；前端頁面無自動化鏡頭測試）

- [x] `requirements.txt` 加 segno（1.6.6）；`camera_session_service.py`（17 顆單元測試先紅再綠）
- [x] `app/api/routers/camera.py` 三 HTTP＋一 WS（33 顆整合測試；404 族／relay／拒連／
      binary frame／過期停轉／64KB 上限／404 先於 415）
- [x] main.py 掛 router；端點 14→17（openapi 測試釘住、WS 不在其中）
- [x] 前端三檔＋彈窗鏈抽成全站唯一 `classify_chain.js`（upload 頁行為逐位元不變）；
      閃光能力回報制（iOS 靜默 resolve 用 getSettings 復驗）
- [x] HTTPS：mkcert 已裝＋certs/ 已產（SAN=10.0.0.34/localhost/127.0.0.1）＋.gitignore；
      CLAUDE.md 指令區含 mkdir -p certs／iPhone 信任步驟（含 VPN 與裝置管理入口）
- [x] BDD：`test_camera_feature.py` 綁定唯讀規格 `無線鏡頭拍攝.feature` 兩個 Example
- [x] 全量 324 passed＋2 skipped、`OLLAMA_BASE_URL` 指死埠同顆數
- [ ] 🛑 **真機驗收（iPhone＋電腦同 Wi-Fi）＝產品負責人手動**（手冊：scratchpad
      task-36-report.md §7；先 `mkcert -install` 要密碼）

## 執行方式

以 opus subagent 實作（TDD），主線（我）事後跑 task review＋最終親自 review；
真機部分明確停下請產品負責人操作。
