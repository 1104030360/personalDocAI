-- 正式庫（PersonalDocAI）遷移：增量五 design5.md D16「建議隨入庫落庫」。
-- photo 表加三個「VLM 建議」欄位，與 Phase 35 加的 suggested_category 並排。
--
-- 為什麼需要它：增量五把上傳改成非同步（HTTP 立刻回 202，看圖交給背景 worker）。
-- 建議在 worker 跑完時產生，那時已經沒有人在等 HTTP 回應了，
-- 建議如果不落庫就會蒸發——待決定頁開窗時就再也拿不到實體建議與待辦建議
-- （待辦彈窗會從此沒有入口，design5.md D16）。
--
-- 特性：冪等（idempotent）＝可重複執行。跑第二次不會出錯，也不會改壞任何資料。
--       每一句都是 ADD COLUMN IF NOT EXISTS：欄位已經在了就安靜跳過。
-- 日期：2026-08-25（Phase 56）
-- 用法：psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -f db/migrate_design5.sql
--
-- ⚠️ 測試庫不要用這一份。測試庫直接重建：
--    psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql
-- ⚠️ 這支腳本只加欄位，不改也不刪任何既有資料；既有列的三個新欄位一律是 NULL。

-- ① VLM 建議的實體名稱。
--    已經在程式層 clamp 過（只會是現有 entity 清單裡的名字之一）；
--    清單外或都不像 → NULL。實體沒有「未分類」這種保底（design3.md D12）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_entity text;

-- ② VLM 建議的待辦標題。NULL ＝這張照片看起來沒有要做的事，
--    待決定頁因此不會跳出待辦彈窗（沿用現在上傳鏈的「空關不跳」規則）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_task_title text;

-- ③ VLM 建議的到期日。
--    型別刻意用 date 不用 timestamp：它之後會被帶去 POST /photos/{id}/task，
--    而 task.due_date 本來就是 date。兩邊一致才不會出現
--    「建議 2026-08-21、建成待辦變 2026-08-21 00:00:00+08」這種漂移。
--    NULL ＝有這件事要做、但推不出期限（仍然是一筆合法的待辦建議）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_task_due date;

-- 刻意不做的事（design5.md §11 明文，別手滑加上去）：
--   * 不加索引：沒有任何查詢拿它們當條件，只在撈某一列時順便讀出來。
--   * 不加 NOT NULL／DEFAULT：既有各列本來就沒有建議，NULL 才是誠實的語意。
--   * 不加「處理狀態」欄、不加 job_id 欄：進度住在 JobStore（Phase 57），
--     崩潰重送的冪等靠 JobStore 的 photo_ids，不靠 photo 表。
