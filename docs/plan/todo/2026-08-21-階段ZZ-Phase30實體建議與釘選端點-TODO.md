# 2026-08-21 階段ZZ：Phase 30 實體建議與釘選端點——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-30-實體建議與釘選端點.md`：①VLM 契約一次擴齊（實體＋待辦建議三欄、
prompt 注入實體清單、`clamp_entity()`）②上傳回應加 `suggested_entity`／`entities`／`suggested_task`
③三個新端點：`GET /entities`、`POST /photos/{id}/entities`（釘選）、`POST /photos/{id}/entity-suggestion`
（再建議一個，新注入點 `get_entity_suggester`）。端點 9→12。

## 實作邏輯

- **人確認才落庫**（design3 D3）：VLM 的實體／待辦輸出只出現在回應；寫入走使用者按出來的 POST。
- **同一個 gemma4 仍只看一次圖**（D8）：上傳 prompt 一次帶齊資料夾＋實體＋待辦規則；
  「再建議一個」是獨立的**文字** LLM 呼叫（不重看圖），有自己的注入點與假件（安全網六個注入點）。
- **建議只能從現有清單挑**（design3 §4）：`clamp_entity` 鏡射 `clamp_category`，
  差異＝沒命中回 **None**（實體沒有「未分類」對應物）。
- **釘選不重算 embedding**：embedding 仍＝text＋四欄位（design.md 定案未動）；實體檢索走連結表（P34）。

## 步驟（TDD 先紅再綠）

- [x] 1. 先紅（unit）：clamp_entity 四情境＋prompt 注入實體清單與待辦規則（10 顆 unit）
- [x] 2. 綠：vlm_service 三欄＋build_vlm_prompt(folders, entities)＋understand 簽名（FakeVLM／分頁VLM 同步）
- [x] 3. 先紅（integration）：GET /entities（2 顆）；釘選與再建議與上傳回應（23 顆）——404×2／409×2／恰一 422／
      embedding 不變／exclude／候選空零呼叫／清單外夾 None／待辦建議三情境
- [x] 4. 綠：schemas/entity.py→entity_suggestion_service.py→routers/entities.py→photos.py 回應擴充→
      dependencies／conftest／fakes（六注入點）
- [x] 5. 全量＋零 Ollama 回歸（207／207）；openapi 清點 12；controller 親自 review diff（通過）

## 執行方式

實作由 subagent（opus）依計畫檔執行；完成後 controller 親自 review 與複驗。全程不 commit。
