# 階段 YYY：Phase 50 丙-4 —— 開機常駐、鏡頭驗證、文件更新、階段丙收尾 TODO

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-50-丙4開機常駐與增量收尾.md`
> 前置：Phase 45〜49 全部完成

---

## 1. 實作邏輯

讓電腦開機之後服務**自己回來**（不必開終端機打指令），確認無線鏡頭在容器化之後仍可用，
把 `CLAUDE.md` 的指令區改成新的現實，最後跑完 design4 §8.9 的十條總驗收。
**Docker 這條線（階段丙）到此完結**——增量四真正的最後一步是 Phase 51（規格摘標）。

### 🙋 需要手機的部分：停下來交產品負責人

產品負責人 2026-08-24 明示「如果要測試需要用到我的手機，你要停下來跟我說我自己手動測試」。
所以本階段把鏡頭驗收**切成兩半**：

| 半 | 內容 | 誰做 |
|---|---|---|
| 可自動化 | QR 網址的 host 是否等於 `en0`、憑證 SAN 是否涵蓋該 IP、HTTPS 憑證鏈是否驗得過 | **實作者**（本階段做完） |
| 需要真機 | iPhone 掃 QR → 鏡頭權限 → 桌面即時預覽 → 快門 → 三關彈窗鏈 | **產品負責人手動** |

---

## 2. 步驟

### 2.1 開機常駐

- [ ] Docker Desktop 設成登入時自動啟動
- [ ] Ollama 設成開機啟動
- [ ] 確認 `restart: unless-stopped` **只在** `compose.yaml`；`compose.dev.yaml` 是 `restart: "no"`
- [ ] 確認現在跑的是常駐模式（`ps --no-trunc` 的 COMMAND 沒有 `--reload`）

### 2.2 實測「自己回來」

- [ ] ⚠ 測之前兩個容器必須都是 `Up`（`unless-stopped` 不會叫醒你自己 `stop` 掉的）
- [ ] 停掉 Docker Desktop → 重開 → **什麼指令都不打** → 兩個服務自己回來、`/health` 200

### 2.3 鏡頭驗證（實作者做得到的那一半）

- [ ] `ipconfig getifaddr en0` 查區網 IP
- [ ] 憑證 SAN 要涵蓋該 IP，否則重簽 ＋ `docker compose restart app`
- [ ] 用**區網 IP** 開 `camera-desk.html`、建 session，
      **QR 網址的 host 必須逐字等於 `en0` 的輸出**
- [ ] 對照組：用 `127.0.0.1` 開會走 `_lan_host()` 猜 → 記錄猜出什麼（證明判準的必要性）
- [ ] 🙋 **【交產品負責人】** iPhone 實機掃 QR 全流程

### 2.4 改寫 `CLAUDE.md`

- [ ] 啟動伺服器：`uvicorn` → Docker 兩模式切換 ＋ `--no-trunc` 提醒 ＋ `down -v` 警告
- [ ] HTTPS：憑證由 compose 掛進容器；補「重簽前先檢查 SAN」
- [ ] `psql` 全部補 `-h 127.0.0.1 -U postgres`；`~/.zshrc` 三變數說明；brew `@17` 已停註記
- [ ] 新增「日常備份」一段（方式 A 容器內 ／ 方式 B host）
- [ ] `pytest` 那段加「仍在 host 跑、db 要 healthy」
- [ ] 現況段：顆數 402＋2、端點 20、Docker、三句過期敘述更正

### 2.5 design4 §8.9 十條總驗收

① 列數 ② vector＋1024 ③ brew 狀態 ④ 5433 是 Docker ⑤ pytest ⑥ /health
⑦ 上傳 ⑧ 詳情彈窗 ⑨ 鏡頭 QR ⑩ 重開 Docker Desktop

### 2.6 階段丙收尾

- [ ] 總覽 §2／§5／§6 打勾到 **Phase 50 為止**（51 留空）＋完成註記
- [ ] `grep -rn "LAN_HOST"` 零輸出
- [ ] **不要 commit**

---

## 3. 明確不做

把 dev overlay 設成開機預設／讓 brew `@17` 開機啟動／動 `@14`／`brew uninstall`／
`down -v`／接 STUN·TURN／改任何產品行為／**加 `LAN_HOST`**／`git commit`／
提前打 Phase 51 的勾
