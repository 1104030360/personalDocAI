# 階段FFF REP：Phase 34 詢問三路（metadata／vector／entity／task 四選一）

> 日期：2026-08-22　狀態：✅ 完成（程式與自動化測試；真模型煙霧列入階段III 統一執行）
> 對應 TODO：`2026-08-22-階段FFF-Phase34詢問三路-TODO.md`；計畫：`phase-34-詢問三路.md`

## 實作邏輯

`POST /ask` 仍一問一答、查無不虛構、回答語言跟隨提問；只把路由從二選一擴成四選一。
實體路＝`find_entity_by_name` → `list_photos_with_entity`（JOIN photo_entity，欄位恰為
`row_to_document` 所需六欄）；待辦路＝`search_tasks(due_before)`（None＝全部；有值＝
`due_date IS NOT NULL AND due_date <= …`，「要交的」語意排除無期限；排序與 `list_tasks`
共用 `TASK_ORDERING` 常數）。路由 prompt 注入現有實體名單（端點層 `list_entities()` 經
`AskDeps.entity_names` 傳入；`route(question, entity_names)` 三處同步）＋中英 few-shot
各兩例；失敗 fallback 一律 vector 不變。task 路的 Document `metadata["id"]`＝**來源照片
id**，`retrieved_photo_ids`「回照片 id」契約因此一字不變、`FakeAnswerLLM` 零改動。
`SEARCH_MODE_LABELS` 加 `"entity pin search"`／`"task search"`。端點數不變（14）、無遷移。

## 步驟（TDD 四階段，先紅再綠證據見 scratchpad task-34-report.md）

Stage A repository 兩查詢（紅＝`AttributeError: no attribute 'search_tasks'` → 綠 6 顆）
→ Stage B 檢索層兩路（紅＝`ImportError: entity_search` → 綠 14 顆）
→ Stage C RouteDecision＋workflow 兩節點（紅＝`literal_error: Input should be 'metadata' or
'vector'` → 綠 21 顆）→ Stage D 端點撈實體名單（紅＝`assert [] == ['我的 MacBook', …]`
→ 綠 25 顆）。

## 測試方式與結果

- 新增 `tests/integration/test_ask_three_paths.py`（25→修正輪後 28 顆）＋
  `tests/unit/test_ask_workflow_unit.py`（2 顆）。
- 全量：開工基線 223 passed＋2 skipped → 完工 **252 passed＋2 skipped**；
  `OLLAMA_BASE_URL=http://localhost:9` 同顆數（零 Ollama 實證）。
- `自然語言詢問.feature` 既有 Q1〜Q5 全程保綠；規格檔一字未動（P34 範圍內）。
- Review：opus reviewer 判規格符合 ✅＋NEEDS_FIXES（Important×2＋Minor×7）→ fix round 1
  修 8 項 → scoped re-review **ALL ADDRESSED、無新破壞**。
  未修 1 項（Minor-4：未知 mode 的 KeyError 防線——`RouteDecision` Literal 已在上游擋死、
  不可達；裁決不加不可達防護）。

## 遇到的問題與解法

1. **開工即發現工作區有「外來」規格變更**：另一 session（檔頭註明「產品負責人指示補
   features」）於 09:36〜09:38 補了 7 個規格檔＋conftest `pytest_bdd_apply_tag`＋兩個測試
   binder 的 steps。其中 `自然語言詢問.feature` 新增兩條 P34 Rule 掛 `@未實作`（＝全量的
   2 skipped）。依「docs/spec 唯讀」鐵律**未摘標**——steps 已預寫齊，摘標即跑；
   摘標屬規格編輯，留產品負責人執行。
2. **規格例子與計畫矛盾（待裁決）**：新 Rule 的待辦例子問「這週要交什麼」但 Given 的
   待辦 due=2026-09-18（一個月後），與計畫「這週＝due_within_days=7」過濾互斥——
   摘標當下該例會紅。裁決：維持計畫行為，建議摘標時把例子 due 改到 7 天內
   （或改例句）。已記 ledger（Ruling-6）。
3. **fix round 事故**：修正輪 agent 做變異驗證還原時誤用 `git checkout --`，把未 commit 的
   `retrieval_service.py` 整檔回退（P34 改動一度全失）；以 review 包 diff `git apply` 復原＋
   重補 docstring，我逐行親驗復原完整、全量綠。防再犯：scratchpad 建全量快照
   （35 檔含七個規格檔），後續所有 subagent brief 明令**禁用 git checkout／restore 做還原**。

## 遞延項（階段III 處理／產品負責人裁決）

- 真模型煙霧（中英實體＋待辦問句、驗 search_mode 與 retrieved_photo_ids）＝階段III 我親跑。
- `@未實作` 摘標＋例子日期矛盾＝產品負責人。
- 已知限制入檔：entity／task 路不套 30 天過濾（docstring 已載明理由）；
  實體名對不到回查無、不做模糊建議。
