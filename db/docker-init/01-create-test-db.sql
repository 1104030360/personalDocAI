-- 這個檔只在 pgdata volume「第一次誕生」時被官方映像執行一次（design4.md §8.4）。
-- 正式庫 PersonalDocAI 由 compose 的 POSTGRES_DB 建；這裡補建測試庫。
-- 檔名的 01- 前綴是官方映像的慣例：同一個資料夾裡的檔案照檔名排序執行。
--
-- ⚠ 這裡**只建空的資料庫**，不建表。
--   測試庫的表由 `psql -f db/schema.sql` 重建（schema.sql 開頭是 DROP TABLE，
--   只能打測試庫）；正式庫的資料由 pg_restore 灌進來。
CREATE DATABASE "PersonalDocAI_test";
