# 2026-08-21 階段BBB：Phase 32 待辦資料層與端點——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-32-待辦資料層與端點.md`：task 的 repository 三函式＋兩個端點——
`POST /photos/{photo_id}/task`（人按「建立」才寫入，404／409／422）、`GET /tasks`（列表，附 thumbnail_url）。
端點 12→14。表已由 Phase 29 建好（photo_id UNIQUE＝每張照片至多一筆，design3 §7 MVP）。

## 實作邏輯

- **人確認才落庫**（design3 D13）：VLM 的待辦建議已在上傳回應（P30），本 phase 只做「確認寫入」與「列出」；
  端點不碰 VLM、不碰 embedding。
- 排序＝`due_date ASC NULLS LAST, created_at DESC`（先到期在前、沒到期日在最後）。
- `thumbnail_url` 由端點依 thumbnail_path 是否 NULL 換算（鏡射 folders 端點——不洩硬碟路徑）。
- 驗證：title 去空白、空白 422；due_date 用 `date.fromisoformat` 驗格式、錯 422（訊息明確）。

## 步驟（TDD 先紅再綠）

- [ ] 1. 先紅：`tests/integration/test_tasks.py`（建立 201 兩例／重複 409／404／空白標題 422／格式錯 422／
      排序／thumbnail_url 兩情境／初始空清單）
- [ ] 2. 綠：repository 三函式（create_task／get_task_by_photo／list_tasks）
- [ ] 3. 綠：schemas/task.py＋routers/tasks.py＋main.py
- [ ] 4. 全量＋零 Ollama 回歸；openapi 清點 14；controller 親自 review diff

## 執行方式

實作由 subagent（opus）執行；controller 親自 review 與複驗。不 commit。
