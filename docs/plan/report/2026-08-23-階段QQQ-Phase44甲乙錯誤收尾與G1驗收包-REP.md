# 2026-08-23 階段QQQ：Phase 44 甲乙錯誤收尾、全量回歸與 G1 驗收包——REP

> 最終狀態（2026-08-24）：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**
>
> 本 REP 保留 Phase 44 首次收尾的 387 顆歷史結果；瀏覽器與真模型 hardening 後的
> 最新可重現結果是 402 顆，詳見下方「最終總驗收補記」與階段 RRR。

## 實作邏輯

收尾 phase：不寫新功能，只做四件事——錯誤表逐列盤點（只補真缺口）、三顆收尾測試
（首跑就該綠＋反向驗證防假綠）、全量回歸、產出 G1 檢查表然後**停手等人**。
主 agent 親自執行（不派 subagent），兼作總 review 的一部分。

## 步驟與測試方式

1. **§4.1 錯誤表盤點**：逐列核對計畫表格與實際測試檔，結果與計畫一致——
   1／2／3／5a〜5d 各列都已有測試釘住（`test_photo_detail.py` 三顆、
   `test_ai_timing_log.py` 兩顆、`test_entity_suggestion_unit.py` 一顆、
   既有 422/500 各測），4 與 3b 屬瀏覽器實操（進 G1 包 B/D 段），
   6 屬階段丙。真缺口恰三個：1b（404 無副作用）、原始碼層面無「列出全部」、
   彈窗原始碼層面唯讀。
2. **§4.2 新測試**：新建 `tests/integration/test_design4_error_paths.py` 三顆，
   體例鏡射 `test_design3_error_paths.py`（檔頭盤點表、`專案根目錄`、
   `data_dir底下的檔案()` 含 exists 防呆）。
   - 首跑：**3 passed**（收尾 phase 預期）。
   - **反向驗證**（證明不是假綠）：
     - ① `not in` 暫改 `in` → **1 failed** ✓（改回）
     - ② 在 `photos.py` 檔尾種一行 `# @router.get("/photos")` 註解 → **1 failed** ✓
       （regex 連註解裡的違規字樣都咬得住；種完即刪）
     - ③ 在 `photo_detail_modal.js` 檔尾種一行 `// PATCH` → **1 failed** ✓（種完即刪）
     - 復原後重跑：**3 passed**，且 `rg 反向驗證臨時` 全案無殘留。
3. **§4.3 全量回歸**：
   - Phase 44 首次：`pytest -q` ＝ **387 passed＋2 skipped**（384＋3；19.28s）。
   - Phase 44 首次：`OLLAMA_BASE_URL=http://localhost:9 pytest -q` ＝
     **387 passed＋2 skipped**（18.91s）。
   - 最終 hardening 後：full ＝ **402 passed＋2 skipped＋1 warning**（27.73s）；
     指死 Ollama 埠後同顆數（26.47s）。
   - 最終三份規格 binder ＝ **25 passed＋2 skipped＋1 warning**（2.19s；
     `@未實作` 兩條仍 skip，摘標屬產品負責人）。
   - `git status --porcelain docs/spec/` ＝ 無輸出（規格一字未動）
4. **§4.4 七項「不做」掃碼**：
   - 無「列出全部照片」：openapi 面（P38 兩顆）＋原始碼面（本檔②）皆綠 ✓
   - 無 DELETE：既有 openapi 掃碼測試綠，實測 DELETE=0 ✓
   - 清單契約：`git diff --stat` folder/task 的 schemas＋routers ＝ 無輸出 ✓
   - 彈窗鏈四檔（folder/entity/task_modal、classify_chain）：無輸出 ✓
   - 舊看圖 log：`rg 'logger.info\("AI 看圖' app/` 無輸出 ✓
     （樸素 grep 唯一命中 `app/main.py:15` 的**註解**，計畫明文不用動）
   - SQL 只在 repository：既有掃碼測試在全量中綠 ✓
   - 丙階段檔案：`compose.yaml`／`compose.dev.yaml`／`Dockerfile`／`.dockerignore`／
     `db/docker-init` 全部 No such file ✓
5. **§4.5 G1 驗收包**：已產出
   `docs/plan/report/2026-08-23-G1驗收包-請產品負責人確認.md`，
   A 段四項實跑數字已填、B〜E 留給產品負責人親自勾；
   準備文字採一般化的「停止任何舊 instance 後，以 `--reload` 重新啟動」，不綁定特定
   終端機編號。

## 遇到的問題與解法

1. **openapi 實測數字**：清點腳本印出 `運算元數: 20 | DELETE: 0 | 有 GET /photos/{photo_id}:
   True | 沒有列出全部: True`——與 D5 完全一致，直接填進 G1 包。
2. **反向驗證的做法比計畫更強**：計畫只要求「斷言反過來會紅」；②③兩顆我改用
   「種一個真違規」驗證（比反轉斷言更能證明偵測力），三顆都咬得住。
3. Phase 44 首次收尾當下未改任何產品程式碼；後續總驗收在瀏覽器、真模型與安全 review
   找到缺口，已回相應 Phase 39〜43 做 RED→GREEN：破圖占位、CJK／數字單位換行、raw error
   不外露、focus trap／背景 `inert`／Tab 與 Shift+Tab／focus restore、stale modal generation、
   local structured output 明寫 `method="function_calling"` 且失敗須 `ok=false`、單行截斷的隱私
   安全 log，以及 request-selected immutable target 防 relabeling。
4. 初次實體建議真模型 QA 與 `pytest` 並行，測試 fixture truncate 共用
   `PersonalDocAI_test` 後造成 404；該次證據無效並已作廢，乾淨 serial rerun 成功後才入表。
5. 兩位最新獨立視覺 reviewer（`final_visual_qa_k`、`final_visual_qa_l`）最終皆為
   **PASS／HIGH confidence／25 of 25／zero blockers**；技術視覺 gate 完成，但不取代產品負責人
   親自勾選 G1 B／D／E。

## 測試結果

- Phase 44 新檔首跑 **3 passed**；反向驗證三顆皆能紅；復原後 **3 passed**。
- 最終 targeted：**112 passed＋2 skipped＋1 warning in 9.42s**。
- 最終 full：**402 passed＋2 skipped＋1 warning in 27.73s**；指死 Ollama 埠
  **同顆數 in 26.47s**；binder **25 passed＋2 skipped＋1 warning in 2.19s**。
- 唯一 warning 是
  `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
- `python -m compileall`、兩份 JS 的 `node --check` 與 `git diff --check` 均為 exit 0；
  OpenAPI operations=20、DELETE=0、沒有 `GET /photos`，且有 `GET /photos/{photo_id}`。
- `docs/spec/` 乾淨、`ai_timing.log_ai(...)` 恰 8 處、專案根目錄沒有 Docker／compose 檔案。
- **停在 G1**：Phase 45 未動工、無任何 Docker 檔案。等產品負責人那句
  「甲乙沒問題，可以做 Docker」。

## 最終總驗收補記

主 agent 的瀏覽器自查留下 25 張新鮮 JPEG：

`/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`

證據精確分布為 11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`，覆蓋 folders／detail／
兩個詳情窗入口／tasks／pending／classification，以及 placeholder、404、network、CJK／日期／
數字單位、same-tab、×／Escape／backdrop、focus trap、背景 `inert`、Tab／Shift+Tab、focus restore、
scroll lock 與 stale-response 保護。這是 localhost 技術自查；
Phase 36 的手機／QR／hotspot 真機項目是另一件事，不在 Phase 38〜44／G1 範圍。

真模型自查亦完成本機與雲端的單圖、兩頁 PDF、歸類、語意／metadata 詢問、實體建議，
全部有效 serial rerun 的結束行為 `ok=true`。完整秒數、TDD RED→GREEN 與工具證據記在
`docs/plan/report/2026-08-23-階段RRR-總驗收與親自Review-REP.md`。

工作樹仍 dirty，沒有 commit、沒有 release。產品負責人尚未親自勾 G1 B〜E，也尚未說出
「甲乙沒問題，可以做 Docker」；因此技術自證完成不等於 release 或 Docker 開工授權。
