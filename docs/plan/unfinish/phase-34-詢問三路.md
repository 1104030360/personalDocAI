# Phase 34：詢問三路（design3.md D14、§6）——下輪校準後實作

> 🎯 仍是**一個 `POST /ask`、一問一答、查無不虛構、回答語言跟隨提問**。
> 檢索來源由路由／檢索層決定，不讓模型自己開工具（不做 agentic RAG——design3 §1.2 已否決）。

**目標：** 路由從二選一變四選一（metadata／vector／**entity**／**task**）；實體路＝沿別針列出掛著的照片、
待辦路＝查 task 表。目標問句：「跟我 MacBook 有關的全部」→ 釘著該實體的照片；「這週要交什麼」→ 待辦清單。

## 拆解（實作時逐條先紅再綠）

1. **repository 兩條新查詢**：`list_photos_with_entity(entity_id)`（JOIN photo_entity，回與檢索層同形的照片欄位、不含 embedding）；
   `search_tasks(due_before: date | None)`（「這週」由 route 抽出範圍；MVP 先做 due_before＋全部兩型）。
2. **RouteDecision 擴充**：`mode: "metadata" | "vector" | "entity" | "task"`＋`entity_name: str | None`＋`due_within_days: int | None`。
   路由 prompt 補中英 few-shot 各一（實體例／待辦例）；**實體名單注入 prompt**（現有實體清單，讓 LLM 對得到名字）；
   路由失敗 fallback 仍一律 vector。
3. **檢索層**：entity 路＝`find_entity_by_name`（大小寫不敏感）→ 命中列照片／沒命中回空（交 LLM 查無句式）；
   task 路＝task 列表轉 Document（title＋due＋來源照片 text）。
4. **workflow**：LangGraph 圖加兩個節點與條件邊；`search_mode` 對外全名在 `config.SEARCH_MODE_LABELS`
   加 `"entity": "entity pin search"`、`"task": "task search"`（實作時與規格檔對一次措辭——`自然語言詢問.feature` 只列了兩種查法，
   **不改規格檔**：新查法只出現在回應欄位，Q1〜Q5 的既有例子行為不變即可）。
5. **假件**：FakeRouter 例子表加實體／待辦問句；FakeAnswerLLM 能吃 task 型 Document。
6. **真模型煙霧（手動）**：中英各一實體問句＋待辦問句；驗 search_mode 與 retrieved_photo_ids。

## 2026-08-22 對現況校準（實作前補充；基線＝218 tests／14 端點／HEAD 0cabb45）

逐條對照 `app/` 現況後，把拆解各條的具體落點寫死（實作照此走，不邊做邊猜）：

1. **拆解 1 的欄位形狀**：`list_photos_with_entity(entity_id)` 的 SELECT 必須含
   `id, text, category, location, items, content_time`（JOIN photo_entity、`ORDER BY p.id`、
   不含 embedding），這樣 `retrieval_service.row_to_document` 一行都不用改就吃得下。
   `search_tasks(due_before: date | None)`：None＝全部待辦；有值＝
   `due_date IS NOT NULL AND due_date <= due_before`（「要交的」語意排除無期限），
   排序沿用 `list_tasks` 的三段（due ASC NULLS LAST → created_at DESC → id DESC）；
   一樣 JOIN photo 取 `text`（task Document 的內容要帶來源照片描述）。
2. **拆解 2 的介面變更（三處同步）**：「實體名單注入 prompt」代表
   `RouterClient.route` 簽名改為 `route(question, entity_names: list[str])`——
   `OllamaRouter`（prompt 加一段現有實體清單＋中英 few-shot 各兩例：實體例／待辦例）、
   `tests/fakes.py` 的 `FakeRouter`（照舊用問句查表，收下 entity_names 即可）、
   `api/routers/ask.py`（端點層呼叫 `photo_repository.list_entities()` 取名單，
   經 `AskDeps` 傳進 workflow；`AskDeps` 加 `entity_names: list[str]` 欄位）。
   `RouteDecision` 加 `entity_name: str | None`／`due_within_days: int | None`，
   「這週」→ `due_within_days=7`。路由失敗 fallback 仍一律 vector（route_node 既有
   try/except 不動）。
3. **拆解 3 的 task Document 契約**：task 轉 Document 時 `metadata["id"]` 必須填
   **來源照片 id**（`photo_id`）——`AskResponse.retrieved_photo_ids` 直取
   `doc.metadata["id"]`，契約「回照片 id」不變，`FakeAnswerLLM` 一行不用改
   （它只讀 page_content 第一行與 `metadata.get("items")`，後者缺省安全）。
   page_content 建議形如「待辦：{title}（到期 {due|無}）\n來源照片：{text}」。
   entity 路：`find_entity_by_name`（既有，P29）沒命中 → retrieved 空 → 交 LLM 查無句式。
4. **拆解 4 的標籤**：`config.SEARCH_MODE_LABELS` 加 `"entity": "entity pin search"`、
   `"task": "task search"`。`自然語言詢問.feature` 只認得既有兩種全名、例子全走
   metadata／vector——**規格檔一字不改**，新查法只出現在新測試。
5. **拆解 5 的假件**：`DEFAULT_ROUTE_DECISIONS` 加實體／待辦問句各（中英）一例；
   FakeRouter 介面隨 2. 改簽名。conftest 的 `wire_fake_ai` 不用動（注入點沒變多）。
6. **測試檔落點**：新整合測試寫 `tests/integration/test_ask_three_paths.py`
   （repository 兩條新查詢＋workflow 兩新節點＋端點 search_mode／retrieved_photo_ids）；
   既有 `test_workflow_route.py`／`test_ask_endpoint.py`／`test_ask_feature.py` 只准變綠不准改行為。
7. **端點數**：本 phase 不加不減（14）；無 schema 遷移（不動資料表）。

## 驗收清單

- [x] 新測試先紅再綠（四階段紅證據見 task-34-report）；全量全綠、零 Ollama 同顆數；
      `自然語言詢問.feature` 一字未動且既有 Q1〜Q5 全綠（另一 session 補的兩條 @未實作 Rule
      被 skip＝摘標屬產品負責人）
- [x] 實體問句沿別針找到照片（不靠文字碰運氣；煙霧後補「Document 自帶釘選事實」修正）；
      待辦問句回清單；查無不虛構
- [x] 路由失敗仍 fallback vector；端點數本 phase 不變（14；P36 後全系統 17）
- [x] task 路回應的 `retrieved_photo_ids` 是來源照片 id；真模型煙霧（2026-08-22 已執行）
      中英實體＋待辦五問全對（詳階段FFF REP）
