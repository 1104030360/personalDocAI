-- 正式庫（PersonalDocAI）一次性遷移：加上增量三的四張新表，以及 photo 的一個新欄位。
-- 對應 design3.md D12（實體＝別針）與 D13（待辦），以及 D11 的抽屜糾錯（Phase 35）。
-- 特性：可重複執行，跑第二次不會出錯也不會改壞資料
--（全部 CREATE TABLE IF NOT EXISTS ／ ADD COLUMN IF NOT EXISTS）。
-- 日期：2026-08-21（Phase 29 建四表）、2026-08-22（Phase 35 加 photo.suggested_category）
-- 用法：psql -d PersonalDocAI -f db/migrate_design3.sql
--
-- ⚠️ 測試庫不要用這一份，測試庫直接 psql -d PersonalDocAI_test -f db/schema.sql 重建就好。
-- ⚠️ 這支腳本只加表與加欄位，不改也不刪任何既有資料；既有列的新欄位一律是 NULL。

-- ① 實體（別針的「那一件東西」，如「我的 MacBook」）
CREATE TABLE IF NOT EXISTS entity (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,
  description text        NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ② 別針：照片與實體的多對多連結（一張照片可釘多個實體，design3.md §5 的 AND）
CREATE TABLE IF NOT EXISTS photo_entity (
  photo_id  integer NOT NULL REFERENCES photo (id) ON DELETE CASCADE,
  entity_id integer NOT NULL REFERENCES entity (id),
  pinned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (photo_id, entity_id)
);

-- ③ 待辦：人按「建立」才寫入（design3.md D13）；photo_id UNIQUE ＝ 每張照片至多 1 筆
CREATE TABLE IF NOT EXISTS task (
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  photo_id   integer NOT NULL UNIQUE REFERENCES photo (id) ON DELETE CASCADE,
  title      text    NOT NULL,
  due_date   date,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ④ 抽屜糾錯素材：Phase 35 的 few-shot 例子從這裡撈（Phase 35 起真的有程式讀寫它）
CREATE TABLE IF NOT EXISTS folder_correction (
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  suggested  text    NOT NULL,
  chosen     text    NOT NULL,
  photo_text text    NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ⑤ photo 多一欄「上傳當下的建議資料夾名稱」（Phase 35）。
--    定案時拿它跟使用者選的資料夾比，不一樣才記一筆糾錯——所以「建議是什麼」
--    必須存在照片上，不能只靠前端臨時帶（已釐清 B）。
--    ADD COLUMN IF NOT EXISTS ＝跑第二次直接略過，不會出錯。
--    既有的每一列都會拿到 NULL ＝「沒有建議」，正是舊照片該有的語意（一律不算糾錯）。
ALTER TABLE photo ADD COLUMN IF NOT EXISTS suggested_category text;
