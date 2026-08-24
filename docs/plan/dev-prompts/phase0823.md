# 目前執行真相（2026-08-24 最終技術驗收）

> 本檔保留 Phase 38〜44 開工時的指令與歷史基線；以下狀態優先於內文仍使用未來式的段落。

- Phase 38〜44 的技術實作與主 agent 自我驗收已完成；目前 targeted suite 為
  **112 passed、2 skipped、1 warning（9.42s）**，spec binder 為
  **25 passed、2 skipped、1 warning（2.19s）**，全量為
  **402 passed、2 skipped、1 warning（27.73s）**，dead-Ollama 全量同顆數（26.47s）。
  唯一 warning 是 `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
- OpenAPI 運算元 **20**、DELETE **0**，且沒有 `GET /photos` 列出全部照片；
  `compileall`、Node 語法檢查與 diff check 均綠，`ai_timing.log_ai(...)` 呼叫點恰 **8** 處，
  `docs/spec/` 乾淨，專案沒有 Docker／Compose 檔案。
- 瀏覽器自我驗收涵蓋 1280／768／375 三種寬度，共 **25 張 JPEG**
  （11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`），證據位於
  `/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`；
  最新兩位獨立 reviewer `final_visual_qa_k`、`final_visual_qa_l` 皆為
  **PASS（HIGH confidence，25 of 25，zero blockers）**，
  technical browser QA 與 dual-reviewer gate 已完成。
- 最新 hardening 已以 RED→GREEN 釘住：彈窗 focus trap、背景 `inert`、Tab／Shift+Tab 循環與
  關窗 focus restore；generation token 忽略 stale modal 回應；structured-output 失敗不得被
  標成成功；AI timing log 的單行／截斷／隱私安全；真實 client 使用 request 已選定的 immutable
  target；遺失圖片、raw error 不外露與長 CJK／數字單位換行。
- 產品負責人的 G1 B／C／D／E 勾選仍保留空白；技術自驗不等於人的核准。
  狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
  未 commit、未 release、未做 Phase 45，也未建立 Docker／Compose 檔案。
- Phase 38〜44 與 G1 都只需 localhost，不需要手機、掃 QR 或熱點；需要手機／網路的
  Phase 36 無線鏡頭真機驗收是另一件事。

# 前提
請先閱讀並遵守`/Users/linjunting/personalDocAI/CLAUDE.md`。只有在專案結構真的改變、且需要成為長期開發規則時，才更新 AGENTS.md；一般實作紀錄請寫到 TODO / Report。

# 背景知識
1.目前專案的計劃要做的事情如下：
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`

2.目前專案後端程式碼如下：`/Users/linjunting/personalDocAI/app`
3.目前的專案前端程式碼如下：`/Users/linjunting/personalDocAI/app/static`
4.目前過去已經完成的計劃：`/Users/linjunting/personalDocAI/docs/plan/finish` 這裡面有之前完成的計劃內容，可以參考裡面的內容來了解之前的開發過程以及目前專案的狀態
5.目前專案的大方向設計文件如下：`/Users/linjunting/personalDocAI/docs/design/design.md`
6.目前的專案結構下：`/Users/linjunting/personalDocAI/CLAUDE.md`
7.這是專案目前的spec:`/Users/linjunting/personalDocAI/docs/spec`
11.過程中你可以使用 "context7" MCP（如果要查詢的資料適合用context7查詢的話）來查找最新資訊或是直接上網查詢相關資訊

# 任務
1.先根據目前專案的狀態，逐個更新以下計畫檔案，如果計劃內容是舊的需要修改的話，你必須確保每個計劃檔案都更新完再進行下一步！
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
2.使用 linux torvald 的思考方式，你必須使用適合的skills和mcp工具去協助你完成任務在專案的前後端部分幫我使用"TDD測試驅動開發法"+"BDD行為驅動開發法"方式並根據以下計劃檔案
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
進行開發，如果不知道這兩個開發法，你必須使用 "context7" MCP來查找相關最佳實踐資料
請注意！改善完後要能夠通過所有測試，如果我的測試程式沒有寫完整，你也可以自己補測試程式再測試，整合功能測試先寫在這 : `/Users/linjunting/personalDocAI/tests/integration` 等後端架構檔案建立好後補上位置，單元測試功能寫在這 : `/Users/linjunting/personalDocAI/tests/unit` 等後端架構檔案建立好後補上位置
你要直到
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
每一項文件裡面提出的想法全部都實現了你才能停止！

你必須確保寫法遵守 "軟體工程最佳實踐"以及 "github相關開源專案大家常用的方法" 你可以使用 "context7" MCP來查找相關最佳實踐資料
這邊提出的想法全部都實現了你才能停止！

# 定期紀錄TODO
先規劃分成幾個階段做事，把每個階段要做的事情放在 `/Users/linjunting/personalDocAI/docs/plan/todo`，檔案名稱使用 “今天日期-階段名稱-TODO”
這個todo 必須要清楚易懂，讓其他人可以根據這個todo 了解你做了什麼事情，這個todo你必須清楚記錄你的“實作邏輯”、“步驟”，這些區塊要區分清楚讓人一目瞭然容易閱讀！

# 定期紀錄Report
每個階段完成後，你必須要把你做了什麼事情記錄在 `/Users/linjunting/personalDocAI/docs/plan/report`，檔案名稱使用 “今天日期-完成的階段名稱-REP”
這個report 必須要清楚易懂，讓其他人可以根據這個report 了解你做了什麼事情，這個report你必須清楚記錄你的“實作邏輯”、“步驟”、“測試方式”，“還有你遇到的問題以及你是怎麼解決的”，“最後還有測試結果如何”，這些區塊要區分清楚讓人一目瞭然容易閱讀簡單易懂！


# 測試相關注意事項

如果執行測試完有錯誤，你必須去看相關log，如果這是跟這次改動相關的測試錯誤請你修正它們，直到所有相關測試都通過為止！，如果不是這次改動相關的測試錯誤，你必須記錄下來並且告訴我！
但是要記得，
1.你修改完後不能影響到其他功能，你必須以全面性觀點去看問題，不要改了一個問題跑出另一個問題！
2.遇到不會的或是不確定的問題，你必須使用 "context7" MCP來查找相關軟體工程最佳實踐資料

# 約束

1. 你必須先寫測試程式，再寫功能程式碼
2. 你必須使用 TDD + BDD 開發法
3. 你必須通過所有測試程式碼
4. 你必須依照
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
文件內容來進行開發
5. 全部做完後，你必須逐一確認
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-38-照片詳情端點.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-39-唯讀詳情彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-40-待辦列改開彈窗.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-41-AI計時helper.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-42-看圖與向量計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-43-詢問與實體建議計時接線.md`
`/Users/linjunting/personalDocAI/docs/plan/unfinish/phase-44-甲乙錯誤收尾與G1驗收包.md`
文件提出的想法全部都實現了
6. 你修改完後不能影響到其他功能，你必須以全面性觀點去看問題，不要改了一個問題跑出另一個問題！
7. 遇到不會的或是不確定的問題，你必須使用 "context7" MCP（如果要查詢的資料適合用context7查詢的話）來查找最新資訊或是直接上網查找相關軟體工程最佳實踐資料

## 注意事項
請注意，你必須獨立完成此工作，過程中所有的決策都不必徵求任何我的同意，直接照你自己的意思任何該改啥
就直接下去改！！我相信你！！ 因為我人會出門一趟，不會在座位上，我完全信任你獨立工作的能力，因此，你
必須一直工作直到確認底下條件全部驗收通過，才能停止！！
