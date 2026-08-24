# 2026-08-23 階段QQQ：Phase 44 甲乙錯誤收尾、全量回歸與 G1 驗收包——TODO

> 對應計畫：`docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
> 本階段由主 agent 親自執行（收尾兼總 review 的一部分，不派 subagent）。

## 目前執行真相

- ✅ Phase 44 技術收尾與實作者自驗已完成。歷史 Phase 44 收尾為 387＋2；
  目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，spec binder 為
  **25 passed、2 skipped、1 warning（2.19s）**，全量為
  **402 passed、2 skipped、1 warning（27.73s）**，dead-Ollama 同顆數（26.47s）。
  唯一 warning 是 `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
- OpenAPI **20**、DELETE **0**、沒有 `GET /photos` 列出全部照片；
  `compileall`、Node 語法檢查、diff check 均綠，生產呼叫點恰 **8** 處，
  `docs/spec/` 乾淨，沒有 Docker／Compose 檔案。
- 瀏覽器技術自驗與 dual-reviewer gate 已完成：25 張 JPEG（11 張 `1280x900`、
  7 張 `768x900`、7 張 `375x812`）；`final_visual_qa_k`、`final_visual_qa_l` 皆
  **PASS／HIGH confidence／25 of 25／zero blockers**，證據在 `phase38-44-final-pass-8/`。
- 最新 hardening 已涵蓋 modal focus／`inert`／stale generation、structured-output failure truth、
  log 安全與隱私、immutable target，以及遺失圖片／raw error／長 CJK。
- 產品負責人 G1 B／C／D／E 仍全部留白。狀態為
  **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，未 commit、
  未 release、未做 Phase 45，也未建立 Docker／Compose。Phase 38〜44／G1 不需要手機、QR 或熱點。

## 實作邏輯

Phase 38〜43 已由三個 subagent＋主 agent 抽驗完成（384 passed＋2 skipped）。
本階段是「收尾」不是「新功能」：

1. **錯誤表盤點在先**：design4 §9 第 1〜5 列逐列找「誰已經測了」，只補真缺口
   （重複的測試是負債）。依計畫 §4.1 的盤點表，真缺口只有三個：
   詳情 404 不打 AI 不寫檔（1b）、原始碼層面沒有「列出全部照片」路由、
   詳情彈窗原始碼層面唯讀（D2）。
2. **收尾測試首跑就該綠**：三顆釘的都是 38〜43 已完成的行為。紅了＝揪到真缺陷
   （回原 phase 修產品碼，不是改斷言）。
3. **「綠」不等於「有測到」**：三顆裡兩顆是「斷言不存在」，天生易假綠——
   每顆都做反向驗證（斷言暫時反過來必須紅，再改回）。
4. 全量回歸＋「不做」清單掃碼＋產出 G1 檢查表（填實際數字），然後**停手等人**。

## 步驟

- [x] §4.1 錯誤表逐列盤點（核對計畫表格與實際測試檔）
- [x] 新建 `tests/integration/test_design4_error_paths.py`（三顆，鏡射 design3 收尾檔體例）
- [x] 首跑（預期 3 passed）＋三顆反向驗證（各自反轉斷言必須紅）
- [x] 全量 `pytest -q`（Phase 44 歷史收尾 387 passed＋2 skipped；目前 402＋2＋1 warning）＋指死埠同顆數
- [x] 規格檔 binder 三份單獨跑＋`git status docs/spec/` 乾淨
- [x] §4.4 七項「不做」掃碼（清單契約、彈窗鏈四檔、舊 log、SQL 歸屬、無 Docker 檔…）
- [x] 產出 G1 驗收包（`docs/plan/report/2026-08-23-G1驗收包-請產品負責人確認.md`，
      填入實跑數字與 .env 實際模型名）
- [x] 寫階段QQQ REP
- [x] **停在 G1。不做 Phase 45、不建任何 Docker 檔案。**
