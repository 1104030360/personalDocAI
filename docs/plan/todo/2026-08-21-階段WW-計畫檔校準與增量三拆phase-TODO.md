# 2026-08-21 階段WW：計畫檔校準與增量三拆 phase——TODO

## 這個階段要做什麼

dev-prompt `phase0821-3.md` 任務一要求「先依專案現況更新計畫檔案，全部更新完才能進下一步」。
現況實查結論（本階段開工前）：

1. `unfinish/phase-27-待決定區與定案鎖定.md` 指到的工作**已由階段VV 全部完成**
   （`pytest -q`＝152 passed 本階段開工重跑實證；Playwright 十項實操見階段VV REP）——
   但計畫檔的驗收清單仍是空勾。→ 需要打勾收尾、標註完成狀態。
2. `docs/design/design3.md`（增量三：無線鏡頭、實體、待辦；2026-08-21 14:08 產品負責人拍板）
   是**最新的 canonical design**，其 §8 明定「落地分 phase、由後續 `docs/plan/unfinish/` 拆」——
   目前 unfinish/ 裡**還沒有任何增量三的計畫檔**。→ 本階段把 design3 拆成 phase 28〜37。

## 實作邏輯

- **校準不改歷史**：phase-27 計畫檔只補「完成註記＋打勾」，不改寫步驟內容（它是階段VV 實作的依據，屬歷史紀錄）。
- **拆 phase 依 design3 §8 與依賴順序**：先資料模型與後端（TDD 可先紅再綠），前端彈窗與瀏覽緊隨其後；
  無線鏡頭（D6 技術路線有待釐清）與詢問三路、few-shot、錯誤收尾排在後面輪次。
- **一次改到位**：entity／photo_entity／task／folder_correction 四張新表用**同一支**遷移腳本
  `db/migrate_design3.sql` 一次建齊（正式庫只遷移一次、備份一次），程式則仍 phase 一次一項。
- **本輪（本 session）實作範圍＝Phase 28〜33**；Phase 34〜37 計畫檔一併寫好，標「下輪校準後實作」。

## 步驟

- [x] 1. 重跑 `pytest -q` 確認 152 passed（開工基線，已完成：152 passed, 8.28s）
- [x] 2. `phase-27-待決定區與定案鎖定.md`：驗收清單逐項打勾＋檔頭補完成註記（含日期與 REP 出處）
- [x] 3. 寫 `unfinish/phase-00-增量三總覽.md`：phase 28〜37 路線圖、範圍、端點數演進、已知限制
- [x] 4. 寫 `unfinish/phase-28-PDF入庫.md` 〜 `phase-33-待辦彈窗與瀏覽待辦tab.md`（本輪實作，含測試先行細節）
- [x] 5. 寫 `unfinish/phase-34〜37`（下輪實作：詢問三路、抽屜糾錯 few-shot、無線鏡頭、錯誤收尾；
      無線鏡頭檔內列「實作前需產品負責人釐清」清單）
- [x] 6. 寫本階段 REP

## 備註

- dev-prompt 指名的計畫檔路徑是 phase-27——依「先依現況更新」的指令精神，
  現況＝phase-27 已完結＋design3 待拆，所以本階段的「更新計畫檔」＝上述 2〜5。
- 全程不 commit（產品負責人指示）。
