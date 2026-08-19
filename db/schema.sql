-- 啟用 pgvector 擴充套件（讓資料庫多出 vector 型別）
CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS photo;

CREATE TABLE photo (
  id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text         text        NOT NULL,               -- VLM 的文字描述（失敗就不存，所以不會空）
  category     text,                               -- 類別（如：收據 / Receipt），可空
  location     text,                               -- 地點/商家（如：Target），可空
  items        text[]      NOT NULL DEFAULT '{}',  -- 物品清單（多值）
  content_time date,                               -- 內容時間（如收據日期），可空
  uploaded_at  timestamptz NOT NULL DEFAULT now(), -- 上傳時間，DB 自動記
  embedding    vector(1024) NOT NULL               -- 文字＋欄位合併內容的向量
);

-- 向量索引：HNSW ＋ cosine 距離（pgvector 官方語法）。
-- 索引＝資料庫的「目錄」，查資料不用整張表逐列掃描；
-- HNSW＝專門加速「找最相近向量」的索引演算法；
-- cosine（餘弦）距離＝比較兩個向量的方向有多接近，越接近代表意思越像。
-- 只建這一個索引；demo 資料量用循序掃描就夠，不養用不到的索引
CREATE INDEX photo_embedding_idx ON photo USING hnsw (embedding vector_cosine_ops);
