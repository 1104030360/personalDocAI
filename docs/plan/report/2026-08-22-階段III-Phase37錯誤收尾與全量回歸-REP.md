# 階段III REP：Phase 37 增量三錯誤收尾與全量回歸＋總 review

> 日期：2026-08-22　狀態：✅ 完成（自動化部分；P36 真機驗收與若干裁決移交產品負責人）
> 對應 TODO：`2026-08-22-階段III-Phase37錯誤收尾與全量回歸-TODO.md`；計畫：`phase-37-增量三錯誤收尾與全量回歸.md`

## 實作邏輯

鏡射 Phase 13／25 的收尾模式：design3 錯誤表（校準後 16 列）逐列標「已測 ✓（測試名）／
缺口 ★」，缺口以新檔 `tests/integration/test_design3_error_paths.py` 釘死（17 顆；體例照
`test_folder_error_paths.py`）。**首跑 16 綠 1 紅**——紅的那顆揪出一個真缺陷：
「③自創實體並釘上」是 `create_entity`＋`pin_entity` 兩次呼叫、各自開連線，
釘選那步失敗會留下**沒人釘的空實體**，使用者重試同名還撞 409 走進死路（違反
design3 錯誤表「寫入失敗＝資料庫零半套狀態」與 Phase 21「不留空資料夾」同一條規則）。
修法＝新增 `photo_repository.create_and_pin_entity()`：兩筆 INSERT 放進**同一個
`get_connection()` 交易**（psycopg 連線區塊正常結束 commit、例外整批 rollback），
router 自創分支改呼叫它；rollback 用真的外鍵違反實測、非假件。回應形狀與端點數零變動。

## 步驟

1. 錯誤表 16 列稽核（12 子情境已有既有測試把關、10 缺口）→ 補 17 顆 → 首跑 → 修缺陷 → 全綠。
2. 「明確不做」12 項掃碼全過（自動拍／第二模型／tool calling／Gmail·Calendar／雲端 VLM／
   DELETE／多使用者／螢幕錄製／實體當資料夾／STUN·TURN 雲端信令／第三方 QR／token 落庫），
   其中「openapi 無 DELETE」「端點恰 17」「SQL 只在 repository」為自動化測試。
3. camera.py 模組 docstring 過時註解（P36 re-review M5 殘留）修正。
4. 正式庫健檢（我親跑、唯讀）：六表在、`photo.suggested_category` 欄在、孤兒連結全 0、
   收件箱唯一。
5. CLAUDE.md 現況段全面更新（修正「31〜33 未 commit」過時敘述——實已含 `0cabb45`；
   新增 P34〜37 成果段；指令區規格 binder 清單更新）；總覽 §2 打勾＋第二輪完成註記。
6. 真模型煙霧（我親跑）：P34 五問（含實體路缺陷修正後 zh/en 重驗）、P35 端到端閉環、
   P36 HTTPS 啟動驗證——詳見各階段 REP 與 scratchpad smoke log。
7. **最終親自 review**（phase0822 指示）：逐檔看完全部產品 diff（ask_workflow／
   retrieval_service／vlm_service／photos／ask／entities／folders／camera／
   camera_session_service／classify_chain.js／schemas／db 遷移／browse.html／main／config／
   fakes）＋前端紀律抽查（innerHTML 僅常數與 esc() 包裝＋自家 segno SVG）＋規格檔 mtime
   實證我方零觸碰＋conftest diff 恰 9 行（外來 hook）。

## 測試方式與結果（我親自複跑的最終數字）

- `pytest -q`＝**341 passed＋2 skipped**；`OLLAMA_BASE_URL=http://localhost:9` **同顆數**
  （零外部依賴實證）。2 skipped＝規格 `@未實作` 兩例（摘標屬產品負責人）。
- `/openapi.json` 端點＝**17**；DELETE 動詞＝**0**。
- 本輪四個 phase 的測試軌跡：218（基線）→223（外來規格 +5）→252（P34）→272（P35）→
  324（P36）→**341**（P37）。

## 遇到的問題與解法

- 計畫寫「17 列」實為 16 列（我 dispatch 時誤數）——稽核以檔案實文為準，無漏列。
- 首跑紅＝真缺陷（見上），依「修復不得影響其他功能」原則以交易修復並全量回歸。

## 移交產品負責人（詳見最終回報）

真機驗收（iPhone）、`@未實作` 摘標＋待辦例子日期矛盾、手機重拍鈕、TTL 600 秒 vs 看圖延遲、
commit 與 unfinish/→finish/ 歸檔。
