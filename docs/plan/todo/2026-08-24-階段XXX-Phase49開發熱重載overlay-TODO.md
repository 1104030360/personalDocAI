# 階段 XXX：Phase 49 —— 開發熱重載 overlay `compose.dev.yaml` TODO

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-49-開發熱重載overlay.md`
> 前置：Phase 48 完成（常駐模式已驗收）

---

## 1. 實作邏輯

做一份**只在開發時疊上去**的設定檔，讓 Mac 上存檔之後容器裡的 uvicorn 自己重載。
**常駐那份 `compose.yaml` 一個字都不改。**

### 為什麼要分兩份（不是「加個開關」就好）

開機自動拉起的行程若帶 `--reload`：uvicorn 會一直盯著檔案，而且**鏡頭配對 token 在記憶體**，
一重載就配對失效——真機驗收到一半突然要重掃 QR，非常難查。

### overlay 的合併規則（不要記反）

| 設定型別 | 合併方式 |
|---|---|
| `command`／`restart`（單值） | 後面那份**整個換掉**前面那份 |
| `volumes`（清單） | 以**容器內的掛載路徑**當 key **逐項合併**，同路徑才蓋掉 |

所以就算只寫 `./app` 那一行，`data`／`certs`／`.env` 也不會消失。
四項全列是照 design4 §8.4.1 原文，也是為了「一眼看得懂實際掛了哪四個」。

`compose.dev.yaml` **一定放最後**——順序寫反最陰險：常駐那份沒有 `command`
（啟動指令在 Dockerfile 的 `CMD`），所以 `--reload` 反而不會消失，
但 `restart` 會被覆寫成 `unless-stopped` ＝「開機自動拉起一個帶 `--reload` 的 app」，
正是 design4 最不想要的結果，而且畫面上完全看不出來。

---

## 2. 步驟

- [ ] 建 `compose.dev.yaml`（`command` 有 `--reload`、`volumes` 四項、`restart: "no"`）
- [ ] `docker compose -f compose.yaml -f compose.dev.yaml config` 驗合併結果
      （`command` 有 `--reload`、四個 volumes、`restart: "no"`、`db` 段與常駐完全相同）
- [ ] 切開發：`stop app` → 兩份疊加 `up -d` → `ps --no-trunc` 的 COMMAND **有** `--reload`
- [ ] **實測 Python 熱重載**：改 `app/main.py` 的 `health()` → log 出現
      `WatchFiles detected changes` → `curl` 反映新行為 → **改回來**
- [ ] **實測 HTML**：改 `app/static/browse.html` 一行提示字 → 不必等重載就看得到 → **改回來**
- [ ] **實測 `logs -f` 的 `Ctrl+C`**：只離開 log，容器繼續跑
- [ ] 切回常駐：兩份 `stop` → `-f compose.yaml up -d` → COMMAND **沒有** `--reload`、`/health` 200
- [ ] `pytest -q` 仍 402 ＋ 2
- [ ] `compose.yaml` 一個字沒改（用 grep 驗，不能用 `git diff`——它是未追蹤檔）
- [ ] 臨時修改都已還原：`git status --short -- app/` 為空

---

## 3. 明確不做

在 `compose.yaml` 加 `--reload`／在 dev overlay 寫 `restart: unless-stopped`／
把兩份疊加設成開機預設／用 Docker Compose Watch／改 `data`｜`certs`｜`.env` 的掛法／
`down -v`／留下測試用的臨時修改
