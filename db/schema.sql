-- 啟用 pgvector 擴充套件（讓資料庫多出 vector 型別）
CREATE EXTENSION IF NOT EXISTS vector;

-- 砍表順序固定：先 photo 再 folder。
-- photo.folder_id 用外鍵指著 folder，被指著的表不能先砍，否則 PostgreSQL 會拒絕。
DROP TABLE IF EXISTS photo;
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
  content_type   text                                -- image/jpeg 或 image/png
);

-- 向量索引：HNSW ＋ cosine 距離（pgvector 官方語法）。
-- 索引＝資料庫的「目錄」，查資料不用整張表逐列掃描；
-- HNSW＝專門加速「找最相近向量」的索引演算法；
-- cosine（餘弦）距離＝比較兩個向量的方向有多接近，越接近代表意思越像。
-- 只建這一個索引；demo 資料量用循序掃描就夠，不養用不到的索引
CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);
