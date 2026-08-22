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

## 驗收清單

- [ ] 新測試先紅再綠；全量全綠、零 Ollama 同顆數；`自然語言詢問.feature` 一字未動且全綠
- [ ] 實體問句沿別針找到照片（不靠文字碰運氣）；待辦問句回清單；查無不虛構
- [ ] 路由失敗仍 fallback vector；端點數不變（14）
