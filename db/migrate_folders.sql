-- 正式庫（PersonalDocAI）一次性遷移：加上 folder 表與 photo 的四個新欄位。
-- 對應 design1.md §10。特性：可重複執行，跑第二次不會出錯也不會改壞資料。
-- 用法：psql -d PersonalDocAI -f db/migrate_folders.sql
--
-- ⚠️ 測試庫不要用這一份，測試庫直接 psql -d PersonalDocAI_test -f db/schema.sql 重建就好。

-- ① 建 folder 表（已經有就跳過）＋ 六筆種子（撞名就跳過）
CREATE TABLE IF NOT EXISTS folder (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,
  description text        NOT NULL DEFAULT '',
  is_inbox    boolean     NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 全域最多一個收件箱（部分唯一索引，只對 is_inbox = true 的列生效）
CREATE UNIQUE INDEX IF NOT EXISTS folder_one_inbox ON folder ((true)) WHERE is_inbox;

-- 六筆預設資料夾，內容與順序必須和 db/schema.sql 完全一致
INSERT INTO folder (name, description, is_inbox) VALUES
  ('未分類', '不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。', true),
  ('收據',   '發票、消費憑證、購物明細。',                        false),
  ('飲食',   '食物、飲料、餐廳、菜單。',                          false),
  ('風景',   '戶外、旅遊、地點、景色。',                          false),
  ('文件',   '非收據的文字資料，例如名片、說明書。',              false),
  ('其他',   '看懂是什麼，但不符合上面任何一個。',                false)
ON CONFLICT (name) DO NOTHING;

-- ② photo 加四個新欄位（folder_id 這時先允許 NULL，等 ③ 填完值才收緊）
ALTER TABLE photo ADD COLUMN IF NOT EXISTS folder_id      integer REFERENCES folder (id);
ALTER TABLE photo ADD COLUMN IF NOT EXISTS original_path  text;
ALTER TABLE photo ADD COLUMN IF NOT EXISTS thumbnail_path text;
ALTER TABLE photo ADD COLUMN IF NOT EXISTS content_type   text;

-- ③ 把既有照片掛上資料夾：
--    依 category 找同名資料夾（不分大小寫）；對不到或 category 為空 → 未分類。
--    只處理還沒掛上的列，所以重跑不會動到已經歸好的資料。
UPDATE photo p
SET folder_id = COALESCE(
      (SELECT f.id FROM folder f WHERE lower(f.name) = lower(p.category)),
      (SELECT f.id FROM folder f WHERE f.is_inbox)
    )
WHERE p.folder_id IS NULL;

-- ④ 讓 category 對齊所屬資料夾的名稱（design1.md §6 的雙寫規則：category = folder.name）。
--    對不到資料夾而落到未分類的那些列，category 會在這一步被改成「未分類」。
--    IS DISTINCT FROM ＝「兩邊不一樣（NULL 也算不一樣）」，本來就相同的列不會被更新。
UPDATE photo p
SET category = f.name
FROM folder f
WHERE f.id = p.folder_id AND p.category IS DISTINCT FROM f.name;

-- ⑤ 全部列都掛好資料夾了，把欄位收緊成 NOT NULL（重跑無害）
ALTER TABLE photo ALTER COLUMN folder_id SET NOT NULL;

-- ⑥ 路徑三欄維持 NULL：舊照片本來就沒有原始檔，不假裝有圖。
--    之後 GET /photos/{id}/thumbnail 會回 404，前端顯示占位（design1.md §10、§12）。
