# 2026-09-02 階段三：Phase 81 總驗收與親自 Review TODO

> 對應 dev-prompt：`docs/plan/dev-prompts/phase0902.md` 約束 5（逐一確認計畫檔的想法全部實現）與產品負責人指示「最後你再親自 review 一遍」。
> 上一階段：`2026-09-02-階段二-雲端路PDF81-TODO.md`。ledger：`.superpowers/sdd/phase0902/progress.md`。

## 實作邏輯（新手白話）

上一場（phase0901）的最終整體 review 是另派一個 Opus 席位看整條分支。這次分支只有一個 task、Opus 已經審過全 diff，
再派一席是重複（裁決 R10）；產品負責人又明說「最後你再親自 review」，所以最終整體 review 由 controller 自己做：

```text
① 逐行讀新碼          gated_ingest.py 的分流器／_store_pdf_result／_store_pdf_page、fakes.py 假工人、
                       pdf_service.render_pages(max_pages)、privacy_gate 那一行、test_gated_ingest_pdf.py 全部 9 顆
② 對照本機路          三條規則、收據順序、冪等鏈（含「雲端做一半 → 逾時退回本機」與「全頁做完後被殺」的窗口）
③ 自己跑一次證據      全量 pytest → 三死埠 → 端點三顆 → 本機 PDF 9 顆 → 契約 log → ruff --check → 掃碼 → 樹相減
④ 逐條核對計畫檔      §3 做／不做、§6 驗收清單、§8 完成狀態；總覽 §2.7 P81／§9 數字
⑤ 收尾文件            階段二／三 REP、memory、ledger 的裁決總表
```

## 步驟

- [x] ① 親讀新碼（階段二已做一次；fix wave 的兩顆守門測試再讀一次）。
- [x] ② scoped re-review（Opus）確認 R11 兩顆 ADDRESSED、零新破壞。
- [x] ③ controller 自己跑最終驗證：**624 passed、0 skipped**；三死埠 624；端點 22；`test_ingest_job_pdf.py` 9 passed；log 含 `雲端結果已入庫：2 頁中 2 頁成功`；ruff 綠；零 boto3 import；三個改到的 app 檔零 SQL token；`privacy_gate.py` 零禁字；七檔 tokenize 零中文識別字；`ingest_job.py` 兩樹相減空；`data/` 乾淨。
- [x] ④ 計畫檔 §6 全部 `- [x]`、§8 數字 624；總覽 P81／§9 624；`docs/spec/`／compose／前端／正式庫零改動。
- [x] ⑤ 寫階段二 REP、階段三 REP；更新 memory（increment6-plan-status）；ledger 列「Rulings I made」總表。
- [x] ⑥ ★G1 提醒：階段甲（74〜81）全部完成，下一步是產品負責人的人為閘門，**一行 AWS 指令都不准打**；本 phase 無需手機／真機測試（R7）。

## 驗收

| 項目 | 預期 |
|---|---|
| 全量／三死埠 | 624 passed、0 skipped，兩者相同 |
| 端點 | 22（三顆清點綠） |
| 改到的檔 | 恰 7 個程式檔（`gated_ingest.py`、`pdf_service.py`、`privacy_gate.py`、`fakes.py`、`test_gated_ingest_pdf.py`、`test_pdf_service_unit.py`、`test_privacy_gate_unit.py`）＋ 計畫檔／總覽／TODO／REP |
| 未 commit | HEAD 仍 `c265bc3`、零 staged |
