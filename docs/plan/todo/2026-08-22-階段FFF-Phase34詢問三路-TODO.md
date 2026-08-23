# 階段FFF TODO：Phase 34 詢問三路（metadata／vector／entity／task 四選一）

> 日期：2026-08-22　狀態：✅ 完成（見同名 REP；真模型煙霧列入階段III）
> 依據：`docs/plan/unfinish/phase-34-詢問三路.md`（含 2026-08-22 校準段）＋design3.md D14、§6

## 實作邏輯

仍是一個 `POST /ask`、一問一答、查無不虛構、回答語言跟隨提問。只把「路由二選一」
擴成四選一：問句點名**已確認的實體**（「跟我 MacBook 有關的全部」）→ 沿別針
（photo_entity）列照片，不靠文字搜尋碰運氣；問句問**待辦／到期**（「這週要交什麼」）→
查 task 表。檢索來源由路由／檢索層決定，不做 agentic RAG（design3 §1.2 已否決）。
路由要對得到實體名稱，所以把現有實體名單注入路由 prompt（端點層讀一次、經 AskDeps 傳入）；
task 檢索結果轉成 Document 時 `metadata["id"]` 一律填來源照片 id，
`retrieved_photo_ids`「回照片 id」的契約因此一字不變。

## 步驟（TDD：每條先紅再綠）

- [x] repository 兩條新查詢：`list_photos_with_entity(entity_id)`（欄位對齊 row_to_document）、
      `search_tasks(due_before)`（None＝全部；有值排除無期限；排序沿 list_tasks）
- [x] `RouteDecision` 擴充（mode 四值＋entity_name＋due_within_days）；
      `RouterClient.route(question, entity_names)` 介面改版（OllamaRouter prompt 注入實體清單
      ＋中英 few-shot；FakeRouter 同步；失敗 fallback 仍 vector）
- [x] 檢索層：entity 路（find_entity_by_name → 列照片／沒命中回空）＋
      task 路（due_within_days → due_before 換算；task→Document）
- [x] workflow 加兩節點與條件邊；`SEARCH_MODE_LABELS` 加 entity／task 全名
- [x] `api/routers/ask.py` 讀 `list_entities()` 傳入 AskDeps
- [x] 假件：DEFAULT_ROUTE_DECISIONS 加中英實體／待辦問句
- [x] 新測試檔 `tests/integration/test_ask_three_paths.py`；既有測試零行為變更
- [x] 全量 pytest 全綠＋`OLLAMA_BASE_URL` 指死埠同顆數；`自然語言詢問.feature` 一字未動
      （252 passed＋2 skipped 雙跑同顆；2 skipped＝外來 @未實作 規格例，摘標屬產品負責人）
- [ ] （階段III 我親跑）真模型煙霧：中英實體問句＋待辦問句

## 執行方式

以 opus subagent 實作（TDD），主線（我）事後跑 task review＋最終親自 review。
