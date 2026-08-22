-- 正式庫（PersonalDocAI）一次性遷移：加上增量三的四張新表。
-- 對應 design3.md D12（實體＝別針）與 D13（待辦），以及 Phase 35 的抽屜糾錯素材。
-- 特性：可重複執行，跑第二次不會出錯也不會改壞資料（全部 CREATE TABLE IF NOT EXISTS）。
-- 日期：2026-08-21（Phase 29）
-- 用法：psql -d PersonalDocAI -f db/migrate_design3.sql
--
-- ⚠️ 測試庫不要用這一份，測試庫直接 psql -d PersonalDocAI_test -f db/schema.sql 重建就好。
-- ⚠️ 這支腳本只加表、不改也不刪任何既有資料；photo 與 folder 一個欄位都沒動。

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

-- ④ 抽屜糾錯素材：Phase 35 的 few-shot 例子從這裡撈；本 phase 只建表，還沒有程式用它
CREATE TABLE IF NOT EXISTS folder_correction (
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  suggested  text    NOT NULL,
  chosen     text    NOT NULL,
  photo_text text    NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
