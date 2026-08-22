# 2026-08-21 階段YY：Phase 29 實體與待辦資料層——TODO

## 這個階段要做什麼

依 `docs/plan/unfinish/phase-29-實體與待辦資料層.md`：建 entity／photo_entity／task／folder_correction
四張表（一支可重跑的 `db/migrate_design3.sql` 一次建齊）＋ entity 的 repository 五函式＋測試安全網擴充。
**對外行為零改變**（端點、回應、前端都不動）。

## 實作邏輯

- 資料庫遷移「一次改到位」：四表同一支腳本，正式庫只動一次、備份一次（P32 的 task 函式、P35 的
  folder_correction 程式之後各自的 phase 才寫）。
- `reset_folders_and_photos()` 的 TRUNCATE 必須明列 entity 與 folder_correction——
  CASCADE 只會連到「指著被清表」的 photo_entity／task，不會反向清掉被 photo_entity 指著的 entity。
- 重名檢查大小寫不敏感放程式層（鏡射 find_folder_by_name），DB UNIQUE 是最後防線。

## 步驟（TDD 先紅再綠）

- [x] 1. schema.sql 加四表＋DROP 順序；重建**測試庫**；全量回歸確認 163 不掉
- [x] 2. 先紅：`tests/integration/test_entity_repository.py`（實作時拆成 9 顆，涵蓋計畫六情境＋「同一實體被多張照片釘」）
- [x] 3. 綠：repository 六函式（list_entities／find_entity_by_name／create_entity／pin_entity／is_pinned／list_photo_entities；計畫標題「五函式」為筆誤，程式區塊本列 6 個簽名）
- [x] 4. `db/migrate_design3.sql`（CREATE TABLE IF NOT EXISTS 可重跑）
- [x] 5. 全量＋零 Ollama 回歸（172／172）；controller 親自 review diff（通過）
- [x] 6. **正式庫遷移由 controller 親自執行**（備份 265KB→跑兩次 NOTICE skipping→\dt 六表→20 photos／10 folders 原封不動）

## 執行方式

實作由 subagent（opus）依計畫檔執行；正式庫遷移是改狀態操作，由我（controller）審完腳本後親自執行。全程不 commit。
