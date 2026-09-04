# 2026-09-01 階段六：總驗收與親自 Review TODO

> 對應 dev-prompt：`docs/plan/dev-prompts/phase0901.md` 約束 5（逐一確認八份計畫檔的想法全部實現）與產品負責人指示「最後你再親自 review 一遍」。
> 上一階段：`2026-09-01-階段五-雲端路79-80-TODO.md`。

## 實作邏輯

74〜80 每個 phase 都已各自過「實作 → 審稿 → 修正迴圈」的關卡，但那是**逐 phase 的視角**。
總驗收要做的是**整條分支的視角**：七個 phase 疊起來之後，整體有沒有前後矛盾、有沒有被後一 phase 悄悄改掉的前一 phase 契約、
ledger 裡 parked／deferred 的 Minor 有沒有哪一條其實該在 commit 前修掉。做法比照 SDD 流程：一位最強模型的 reviewer 看**整條分支的 diff**，
再由我親自逐檔讀過並對照八份計畫檔的「做」清單逐項打勾。

## 步驟

- [x] 全量回歸（613／三死埠 613／collect 613）：`pytest -q`（預期 611、0 skipped、只有基線 warning）；三死埠一起指顆數不變；`pytest --collect-only -q | tail -1`。
- [x] `ruff format --check app tests scripts && ruff check app tests scripts` 全綠（104 檔）（＝CI 會跑的兩句）。
- [x] 清點（22／零 DELETE／spec 乾淨／掃碼全零）：端點 22（`/openapi.json` 展開，不用 `app.routes`）、openapi 零 DELETE；`git status --short docs/spec/` 空；`compose*.yaml`／`requirements.txt`／`Dockerfile`／前端零改動；`app/` 全樹 SQL token 掃碼（既有測試）；`boto3` 零 import；`celery_app.py` 零位元組字樣。
- [x] 整條分支 review（✅ Ready for commit，0 Critical／0 Important／5 Minor；一次 fix wave＝M1 log 釘、base_url 斷言、M2 註解、過期註解 7 處；re-review 進行中）：用 `snapshot-tree` 從 BASE_TREE 到收工 tree 產 review 包（只含 `app/`、`tests/`），派最強模型的 reviewer（點名 ledger 的 parked／deferred Minor 清單，請它 triage 哪些該 commit 前修）。有 finding → **一次**修正派工 → 一次範圍限定 re-review → 殘餘裁決。
- [x] 我親自 review（三個新模組＋重構後 ingest_job.py＋celery_app／dependencies／conftest／fakes 全部讀過；總覽 §2.7 74〜80 的 66 顆＋裁決 4 顆全部 collect 到）：逐檔讀 `privacy_gate.py`／`cloud_ingest.py`／`gated_ingest.py`／`ingest_job.py`（重構後）／`dependencies.py`／`celery_app.py`／`config.py`／`ingest_job_store.py`／`conftest.py`／`fakes.py` 的最終版；對照八份計畫檔 §3「做」清單逐項確認已實現；核對總覽 §2.7 的測試名逐字存在（`pytest --collect-only`）。
- [~] 容器模式收工（**未能**切回常駐：`--build` 卡在 load metadata for python:3.12-slim、Docker VM 對 Hub 不通；裁決 R18 留 dev overlay、新碼已生效；指令留給產品負責人）：把 dev overlay 切回常駐（`docker compose -f compose.yaml -f compose.dev.yaml stop && docker compose -f compose.yaml up -d --build`），再上傳一張合成圖做最後煙霧（常駐映像跑的是新碼）；確認 `docker compose ps --no-trunc` 沒有 `--reload`。
- [x] `CLAUDE.md` 現況同步：增量六 Phase 74〜80 成果段（閘門、五積木、雲端路契約、第五道安全網、接線、CloudRoute 單圖、逾時冪等；顆數 543→611；端點 22；不 commit；裁決 S；容器模式）＋指令區補 `CLOUD_ROUTE` 說明。
- [x] 更新總覽 §6 勾選區（74〜80 打勾）、§2.2 完成欄；ledger 收官；memory 更新。
- [x] 寫 REP（`2026-09-01-階段六-總驗收與親自Review-REP.md`）＋給產品負責人的最終 recap（含全部 Rulings 清單、待歸檔清單、留在正式庫的煙霧照片 #63／#64）。

## 驗收

| 檢查 | 預期 |
|---|---|
| 全量 | 611 passed、0 skipped（543＋11＋12＋4＋12＋9＋10＋10） |
| 三死埠 | 611 |
| 端點 | 22、零 DELETE |
| 零改動 | `docs/spec/`、compose、requirements、Dockerfile、前端、正式庫結構 |
| 八份計畫 | §3「做」逐項 ✅；§2.7 測試名逐字存在 |
| 整條分支 review | 0 Critical／0 Important 未處理 |

## 安全鐵律

不 commit、不搬檔（列給產品負責人的 commit 時 `git mv` 清單：phase-73〜80 → `docs/plan/finish/`）；`docker compose down -v` 永遠禁止；切回常駐時只用 `stop`＋`up -d --build`。
