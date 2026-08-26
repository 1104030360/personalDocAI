-- 啟用 pgvector 擴充套件（讓資料庫多出 vector 型別）
CREATE EXTENSION IF NOT EXISTS vector;

-- 砍表順序固定：被外鍵「指著」的表一定最後砍，否則 PostgreSQL 會拒絕。
-- photo_entity 指著 photo 與 entity、task 指著 photo、photo 指著 folder，
-- 所以由外往內砍：photo_entity → task → photo → entity → folder_correction → folder。
-- （folder_correction 沒有外鍵，位置不影響，排在這裡只是跟著建表順序倒過來寫。）
DROP TABLE IF EXISTS photo_entity;
DROP TABLE IF EXISTS task;
DROP TABLE IF EXISTS photo;
DROP TABLE IF EXISTS entity;
DROP TABLE IF EXISTS folder_correction;
DROP TABLE IF EXISTS folder;

-- ---------- 資料夾（＝使用者看到的分類）----------
CREATE TABLE folder (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,       -- 資料夾名稱，不可重複；photo.category 必須等於它
  description text        NOT NULL DEFAULT '',   -- 說明，會注入 VLM 的 prompt 幫助推薦
  is_inbox    boolean     NOT NULL DEFAULT false,-- 是否為系統收件箱「未分類」
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 全域最多一個收件箱。
-- 這是「部分唯一索引」：只對 is_inbox = true 的列生效，
-- 而它們的索引值都是同一個固定值 (true)，所以第二個收件箱會直接撞號被擋下來。
CREATE UNIQUE INDEX folder_one_inbox ON folder ((true)) WHERE is_inbox;

-- 六筆預設資料夾（design1.md §5 原文）。
-- ★ 插入順序就是 id 1〜6，測試與遷移腳本都依賴這個編號，不要調換。
INSERT INTO folder (name, description, is_inbox) VALUES
  ('未分類', '不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。', true),
  ('收據',   '發票、消費憑證、購物明細。',                        false),
  ('飲食',   '食物、飲料、餐廳、菜單。',                          false),
  ('風景',   '戶外、旅遊、地點、景色。',                          false),
  ('文件',   '非收據的文字資料，例如名片、說明書。',              false),
  ('其他',   '看懂是什麼，但不符合上面任何一個。',                false);

-- ---------- 照片 ----------
CREATE TABLE photo (
  id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text           text        NOT NULL,               -- VLM 的文字描述（失敗就不存，所以不會空）
  category       text,                               -- 必須等於所屬 folder.name；未分類時為「未分類」
  folder_id      integer     NOT NULL REFERENCES folder (id),  -- 掛在哪個資料夾（外鍵，不可為空）
  location       text,                               -- 地點/商家（如：Target），可空
  items          text[]      NOT NULL DEFAULT '{}',  -- 物品清單（多值）
  content_time   date,                               -- 內容時間（如收據日期），可空
  uploaded_at    timestamptz NOT NULL DEFAULT now(), -- 上傳時間，DB 自動記
  embedding      vector(1024) NOT NULL,              -- 文字＋欄位合併內容的向量
  original_path  text,                               -- 原圖位置，如 data/photos/1.jpg；舊資料可空
  thumbnail_path text,                               -- 縮圖位置，如 data/thumbs/1.jpg；舊資料可空
  content_type   text,                               -- image/jpeg 或 image/png
  -- 上傳當下 VLM 建議的資料夾名稱（clamp 過，一定是 folder.name 之一）。Phase 35 加。
  -- NULL ＝「沒有建議」：clamp 成「未分類」的、以及遷移進來的舊照片都是 NULL，
  -- 定案時一律不算糾錯（沒建議不是猜錯）。這欄不影響照片實際歸屬（那是 folder_id）。
  suggested_category text,
  -- ---------- 增量五 D16：建議隨入庫落庫（Phase 56）----------
  -- 三欄與 db/migrate_design5.sql 必須完全一致，改一邊就要改另一邊。
  -- 上傳改成非同步（202）之後建議不再回給前端，只能存在照片上，
  -- 待決定頁開窗時才讀得到（design5.md D16、§6.2）。
  suggested_entity     text,   -- VLM 建議的實體名稱（clamp 過；都不像 → NULL）
  suggested_task_title text,   -- VLM 建議的待辦標題（NULL ＝沒有待辦，待辦窗不跳）
  suggested_task_due   date    -- VLM 建議的到期日（型別對齊 task.due_date，只有年月日）
);

-- 向量索引：HNSW ＋ cosine 距離（pgvector 官方語法）。
-- 索引＝資料庫的「目錄」，查資料不用整張表逐列掃描；
-- HNSW＝專門加速「找最相近向量」的索引演算法；
-- cosine（餘弦）距離＝比較兩個向量的方向有多接近，越接近代表意思越像。
-- 只建這一個索引；demo 資料量用循序掃描就夠，不養用不到的索引
CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);

-- ---------- 實體（＝真實世界的「那一件東西」，如「我的 MacBook」）----------
-- 資料夾是抽屜（一張照片只能放一個，XOR）；實體是別針（一張照片可以釘好幾個，AND）。
-- 清單只在使用者按「自創」時才變長——VLM 只從現有清單挑一個來建議（design3.md D12）。
CREATE TABLE entity (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,   -- 實體名稱（如「我的 MacBook」）；重名檢查大小寫不敏感在程式層
  description text        NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- 別針：照片與實體的多對多連結 ----------
-- 一張照片可釘多個實體，一個實體也可以被多張照片釘（design3.md §5 的 AND）。
CREATE TABLE photo_entity (
  photo_id  integer NOT NULL REFERENCES photo (id) ON DELETE CASCADE,  -- 上傳失敗清理 delete_photo 連動
  entity_id integer NOT NULL REFERENCES entity (id),
  pinned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (photo_id, entity_id)       -- 同一張重複釘同一個實體＝撞主鍵（程式層先擋 409）
);

-- ---------- 待辦：人按「建立」才寫入（design3.md D13）----------
-- VLM 同一輪順便判斷有沒有 actionable，但沒有人按下確認就什麼都不寫——
-- 不自動建待辦、不寫 Gmail、不寫日曆（design3.md D3 的「人確認才落庫」）。
CREATE TABLE task (
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  photo_id   integer NOT NULL UNIQUE REFERENCES photo (id) ON DELETE CASCADE,  -- UNIQUE＝每張照片至多 1 筆（§7 MVP）
  title      text    NOT NULL,
  due_date   date,                        -- 到期日，可空
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- 抽屜糾錯素材：Phase 35 的 few-shot 例子從這裡撈 ----------
-- 使用者每次「不採用建議、改選別的資料夾」就留一筆，讓之後的 VLM prompt 學會這個人的習慣。
-- ★ 本 phase 只建表，還沒有任何程式寫入或讀取它。
CREATE TABLE folder_correction (
  id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  suggested  text    NOT NULL,            -- VLM 當時建議的資料夾名稱
  chosen     text    NOT NULL,            -- 使用者實際選的資料夾名稱
  photo_text text    NOT NULL,            -- 那張照片的文字描述（few-shot 例子的題幹）
  created_at timestamptz NOT NULL DEFAULT now()
);
