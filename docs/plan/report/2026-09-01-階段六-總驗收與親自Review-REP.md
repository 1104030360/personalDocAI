# 2026-09-01 階段六：總驗收與親自 Review REP

> 對應 TODO：`docs/plan/todo/2026-09-01-階段六-總驗收與親自Review-TODO.md`。
> 對應 dev-prompt：`docs/plan/dev-prompts/phase0901.md` 約束 5（逐一確認八份計畫檔的想法全部實現）與產品負責人指示「最後你再親自 review 一遍」。
> **全程零 commit**（產品負責人指示）；歸檔（`docs/plan/unfinish/` → `finish/`）隨產品負責人的 commit。

## 實作邏輯

74〜80 每個 phase 都已各自過「實作 → 審稿 → 修正迴圈」，總驗收改用**整條分支**的視角：一位 Opus reviewer 看從開工快照到收工快照的
完整 `app/`＋`tests/` diff（224 KB），對照 design6 六禁、總覽 18 條鐵律、§2.4 契約與 ledger 裡所有 parked／deferred 的 Minor 做 triage；
再由我親自逐檔讀最終版、用 `pytest --collect-only` 核對總覽 §2.7 的 66 顆測試名（＋裁決加的 4 顆）全部存在、親自跑全量與三死埠。

## 步驟與結果

| # | 做了什麼 | 結果 |
|---|---|---|
| 1 | 整條分支 review（Opus）：契約一致性、六禁／鐵律逐條掃、ledger triage | **✅ Ready for commit**；0 Critical／0 Important／5 Minor（M1 `雲端結果已入庫` log 未釘、M2 第一趟落庫不重讀（不可達）、M3 三處過期註解、M4 `ScriptedProbe` 暫無使用者、M5 PDF 閘門全頁渲染）；ledger 全部 can-stay，兩條 recommend-revisit |
| 2 | 裁決 R16：一次 fix wave（Opus）——M1 caplog 釘 log（變異證據）、`base_url` 斷言、M2 說明註解、過期註解 7 處一次改齊（含先前留給 95 的三處） | 8 檔、零行為、零顆數；613／三死埠 613／ruff 綠 |
| 3 | 範圍限定 re-review（Opus） | 4/4 ADDRESSED、零新破壞；兩則註解殘留（「唯一」變假、五道清單少一項） |
| 4 | 裁決 R17：兩則純註解由我自己改（不開第二波） | 併入下一步的 ruff／pytest |
| 5 | **我親自跑**：`ruff format --check && ruff check` → `pytest -q` → 三死埠 → collect → `/openapi.json` 清點 → 掃碼 → `git status` 零改動路徑 → `data/staging` | 104 檔綠；**613 passed／0 skipped**（1 環境 warning）；**613**；613；**22**（GET／PATCH／POST／PUT，零 DELETE）；boto3 import 0、celery_app 禁字 0、新模組 SQL token 0、privacy_gate 禁字 0；`docs/spec/`／compose／Dockerfile／requirements／pyproject／`app/static`／`app/api`／`db/` 零改動；staging 空 |
| 6 | 我親自讀：`privacy_gate.py`、`cloud_ingest.py`（`CloudRoute`＋`_處理別人的訊息`）、`gated_ingest.py` 全文、重構後 `ingest_job.py`、`dependencies.py`、`celery_app.py`、`conftest.py` 五道安全網、`FakeMailbox` 族 | 與 design6／總覽 §2.4〜2.5 一致 |
| 7 | 八份計畫檔 §3「做」逐項對照 | 73 早已完成（08-28）；74〜80 每項都有對應實檔／測試；總覽 §2.7 的 66 顆＋裁決 4 顆全部 collect 到 |
| 8 | 容器切回**常駐**模式（`stop app worker` → `up -d --build`）＋最後煙霧 | 見下方「容器與煙霧」 |
| 9 | `CLAUDE.md` 現況同步（增量六前半成果段、五道安全網、三死埠指令、`CLOUD_ROUTE` 說明）；總覽 §2.2／§6 打勾 74〜80、§9 實查顆數、§10.2 追認項 S、§2.7 P81／P95 註記；memory 更新 | 完成 |

## 容器與煙霧

- Phase 78 煙霧（dev overlay）：本機腿閘門 99.6 秒（首呼叫含載入）／雲端腿 0.7 秒，photo #63／#64 入正式庫待決定；R1 在正式路徑生效。
- 收工：切回常駐並 `--build`（映像含新碳）；最後煙霧結果寫在下方「收工煙霧」。
- **收工實況（裁決 R18）**：`docker compose -f compose.yaml up -d --build` 跑了 17 分鐘沒有產出新映像；用 `build --progress=plain` 診斷卡在
  `#3 load metadata for docker.io/library/python:3.12-slim`，`docker pull python:3.12-slim` 90 秒也沒回——**Docker VM 對 Docker Hub 的路當時不通**
  （host 的 curl 到 registry 正常；容器在 13:44 還能打 ollama.com）。我沒有重啟 Docker Desktop（同一台還跑著別的專案的容器）、沒有改 Dockerfile。
  → 服務目前跑在 **開發 overlay**（`app` 有 `--reload`、`worker` bind-mount `./app`，**新碼已生效**、health ok、worker ready、開關＝本機）。
  ⚠ 開發 overlay 是 `restart: "no"`：**重開機後不會自己回來**，要手動 `docker compose -f compose.yaml -f compose.dev.yaml up -d`。
  常駐映像 `personaldocai-app` 仍是 08-26 的舊碼（不含 74〜80）；要回常駐模式請在 Docker 對 Hub 恢復後（或重啟 Docker Desktop 後）執行：
  `docker compose -f compose.yaml -f compose.dev.yaml stop && docker compose -f compose.yaml up -d --build`，再上傳一張圖看 worker log 有 `kind=privacy` 那兩行即可。
- 收工煙霧：dev overlay 上的新碼已由 Phase 78 的兩腿煙霧驗過（本機腿 99.6s／雲端腿 0.7s，photo #63／#64）；final fix wave 之後 `app/` 只多了 7 行註解，行為不變，未再重跑真模型。

## 遇到的問題與裁決

| 問題 | 裁決 |
|---|---|
| 最終 review 五個 Minor 要不要現在修 | R16：只修零行為、零顆數的（log 釘、斷言、註解）；M4 留 89／95（`ScriptedProbe` 計畫明訂給 89）、M5 留 81（`pdf_service` 加 `max_pages`） |
| re-review 後兩則註解殘留 | R17：controller 自己改（SDD 規則無第二波；純文字） |
| 常駐映像沒有 --reload，改碼後常駐模式跑的是舊碼 | 收工 `up -d --build` 重建映像，並做最後煙霧證明新碼在映像裡 |
| Phase 81 若照舊計畫檔整檔重貼會弄丟 80 的 R14／重讀／註解修正 | 總覽 §2.7 P81 註記：以 80 落地版為基準只加 PDF 分支 |

## 給產品負責人的清單

- **不需要手機**：74〜80 沒有動到無線鏡頭（`camera-*.html`、`/camera/*` 端點零改動）。
- **commit 時**：`git mv docs/plan/unfinish/phase-73-*.md docs/plan/unfinish/phase-74-*.md … phase-80-*.md docs/plan/finish/`（八份；73 是已追蹤檔、74〜80 是未追蹤檔）。
- **留在正式庫的東西**：合成測試圖 photo #63、#64（「SMOKE TEST 2026-09-01 … COFFEE SHOP RECEIPT」）在待決定裡，可歸檔或忽略。
- **`.env` 不必改**：`CLOUD_ROUTE` 預設 off；★G1 前不要填任何 AWS 值。
