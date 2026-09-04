# 2026-09-02 階段三：Phase 81 總驗收與親自 Review REP

> 對應 TODO：`docs/plan/todo/2026-09-02-階段三-總驗收與親自Review-TODO.md`。ledger：`.superpowers/sdd/phase0902/progress.md`（裁決 R0〜R12 總表在檔尾）。
> 全程不 commit（HEAD 仍 `c265bc3`、零 staged）。工作樹快照：BASE `5509872…` → T81_BASE `3ff4a7b…` → T81_HEAD `67cc8d7…` → T81_FIX1 `5a709f0…` → T_FINAL `ad950d5…`。

## 實作邏輯

最終整體 review 由 controller 親自做（裁決 R10：分支只有一個 task、Opus 已審全 diff，再派一席是重複；產品負責人也明說「最後你再親自 review」），分五件事：逐行讀新碼 → 對照本機路 → 自己跑一次全部證據 → 逐條核對計畫檔與總覽 → 收尾文件與 memory。

## 步驟與結果

| # | 做了什麼 | 結果 |
|---|---|---|
| ① 親讀新碼 | `gated_ingest.py` L298〜585（分流器／`_store_image_result`／`_store_pdf_result`／`_store_pdf_page`）、`fakes.py` 假工人 PDF 岔路、`pdf_service.render_pages(max_pages)`、`privacy_gate.py` 那一行、`test_gated_ingest_pdf.py` 9 顆全文 | 分流依 `job["content_type"]`；三條規則、收據順序（每頁 `store.update` 在整份 cleanup 之前）、`page` 欄位配對、`max_pages` keyword-only 向下相容——全部對；冪等鏈含「雲端做一半→逾時退回本機→`_run_pdf_job` 從 `pages_done` 續跑」成立 |
| ② scoped re-review（Opus，明令不跑 pytest） | R11 兩顆守門測試：**ADDRESSED ×2、零新破壞**；3 nit（測試子類 MRO 繞道無註解、計畫檔 §8.1 收工 SHA 未隨 fix 更新、兩個假信箱 8 行重複）；out-of-scope：頁碼重複（如 `[1,1]`）不會觸發頁數 warning | 裁決 R12：前兩個純文字 nit 由 controller 自己改（加一行註解、補 SHA），改完 `test_gated_ingest_pdf.py` 9 passed、ruff 綠；第三個接受；頁碼重複 warning 留 P95 候選 |
| ③ 自己跑證據（T81_FIX1 之後） | `pytest -q` **624 passed、0 skipped**（23.7s；唯一 warning 是環境層 StarletteDeprecationWarning）；三死埠 **624**；端點三顆 3 passed（仍 22）；`test_ingest_job_pdf.py` 9 passed；`-k 兩頁都成功` 的 log 含 `雲端結果已入庫：2 頁中 2 頁成功`；`ruff format --check` 105 檔＋`ruff check` 全綠；`^\s*(import\|from)\s+boto3` 在 app／tests／scripts／requirements 零命中；三個 app 檔零 `psycopg`／`get_connection`／`cursor(`／`.execute(`；`privacy_gate.py` 零 `AI_BACKEND =`／`RuleGate`／`SENSITIVE_KEYWORDS`；七檔 tokenize 零中文識別字；`ingest_job.py` 兩樹相減空；`data/` 與 `staging/` 乾淨 | 全綠 |
| ④ 逐條核對計畫檔與總覽 | 計畫檔 §6 全部 `- [x]`、零殘留 `- [ ]`；§2／§5／§6／§8 數字一致（613＋11＝624）；§8.1 實作紀錄含 fix wave；總覽 §2.2 row 81／★G1、§2.7 P81、§5.1、§9 row 81 皆 624；`docs/spec/`／`compose*.yaml`／`Dockerfile`／`app/static`／`app/api`／`db/`／`requirements.txt`／`pyproject.toml` 對 BASE_TREE 零改動 | 一致 |
| ⑤ 收尾文件 | 階段一／二／三 TODO 與 REP；memory `increment6-plan-status` 更新（Phase 81 完成、624、★G1 待人）；ledger 裁決總表 R0〜R12 | 完成 |
| ⑥ ★G1 | 階段甲（74〜81）全部完成；下一步是產品負責人的人為閘門——看總覽 §5.1 三條證據（敏感／不確定零 S3、遠端關閉仍 fallback、三死埠顆數不變）並明示「可以開始花 AWS 資源」；在那之前一行 AWS 指令都不准打。本 phase 無需手機／真機／真模型測試（R7） | 待產品負責人 |

## 改動總表（對 BASE_TREE）

| 類別 | 檔案 |
|---|---|
| 產品碼 | `app/services/gated_ingest.py`（+206／−6：import、docstring、分流器、`_store_image_result` 改名、`_store_pdf_result`、`_store_pdf_page`）、`app/services/pdf_service.py`（+10／−3：`max_pages`）、`app/services/privacy_gate.py`（1 行） |
| 測試 | `tests/fakes.py`（+70：假工人 PDF）、`tests/integration/test_gated_ingest_pdf.py`（新，9 顆）、`tests/unit/test_pdf_service_unit.py`（+1）、`tests/unit/test_privacy_gate_unit.py`（+1） |
| 文件 | `docs/plan/unfinish/phase-81-雲端路PDF.md`（校準 59 處＋實作勾選＋§8.1）、`phase-00-增量六總覽.md`（P81 註記／數字 6 處）、三份 TODO、三份 REP |
| 沒動 | `app/services/ingest_job.py`、`docs/spec/`、compose／Dockerfile、前端、`db/`、requirements、正式庫、`.env` |

## 遇到的問題與解決

| 問題 | 解決 |
|---|---|
| 分支只有一個 task，照 SDD 再派一個 Opus 最終席位會重複審同一份 diff | R10：controller 親自做最終整體 review＋自跑全部證據 |
| re-review 的 3 nit 若再開一輪 fix 不成比例 | R12：純文字兩項 controller 自改並重跑該檔；重複 8 行接受 |
| `docs/plan/aws/` 兩份 AWS 開戶新手文件在本 session 期間出現（14:26／14:36），不是任何 task 的產出 | 未動、未刪；提請產品負責人確認來源（可能是另一個 session） |

## 已知限制（沿用階段二 REP；不在本次處理）

`_store_pdf_result` 與 `_run_pdf_job` 約 40 行同義迴圈（plan-mandated）；PDF 全頁做完後 `remove_staging`→`store.delete` 之間被殺的窗口（本機路既有同款，P95 候選）；頁碼重複不觸發 warning（P95 候選）；PDF 雲端路在 ★G1 前只在 `FakeMailbox` 上驗過。

## 測試結果

**624 passed、0 skipped**（613 ＋ 核心 7 ＋ R4 2 ＋ R11 2）；三死埠 624；端點 22；ruff 綠；零 commit。
