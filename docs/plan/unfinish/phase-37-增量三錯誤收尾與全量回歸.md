# Phase 37：增量三錯誤收尾與全量回歸——下輪（增量三全部落地後）實作

> 🎯 鏡射 Phase 13／25 的收尾模式：把 design3 各 phase 的錯誤路徑整理成一張表逐列釘測試，
> 「明確不做」清單掃碼核對，最後全量回歸＋（視情況）真模型煙霧補齊。

## 錯誤表草案（實作時逐列補「已測 ✓／缺口 ★」）

| 情境 | 預期 | 出處 |
|---|---|---|
| 壞 PDF／零頁 | 422 什麼都不存 | P28 |
| PDF 部分頁看不懂 | 入庫其餘頁＋skipped_pages 回報 | P28 |
| PDF 全部頁看不懂 | 422 什麼都不存（data/ 零殘留） | P28 |
| 釘選：照片／實體不存在 | 404 | P30 |
| 釘選：重名／重複釘 | 409（大小寫不敏感；DB PK 最後防線） | P30 |
| 再建議：候選空 | 回 null 且零 LLM 呼叫 | P30 |
| 再建議：LLM 失敗 | 回 null 不 500（log warning） | P30 |
| 待辦：重複建立 | 409；標題空白／到期格式錯 422 | P32 |
| 實體／待辦寫入失敗 | 500 不吞錯；資料庫零半套狀態 | P30/32 |
| 詢問：實體名對不到 | 查無句式、不虛構 | P34 |
| 詢問：待辦問句但無待辦 | 查無句式、不虛構 | P34 |
| 糾錯：record 寫入失敗 | 歸類本體照樣成功（log warning） | P35 |
| 鏡頭：亂 token／過期 token | HTTP 三支一律 404 | P36 |
| 鏡頭：亂 token 連 WS | 拒絕連線（不 accept 成功） | P36 |
| 鏡頭：session 汰舊 | 舊 token 立即 404（同時只有一個 session） | P36 |
| 無刪除端點（照片／實體／待辦） | 掃碼證明 DELETE 動詞不存在 | design3 §3 |

## 「明確不做」最終掃碼（design3 §3 不做清單逐項）

自動拍、第二模型、agent tool calling、Gmail／Calendar、雲端 VLM、刪除、多使用者、螢幕錄製、實體當資料夾。
（P36 追加：無雲端信令／STUN／TURN、無第三方 QR 服務、token 不落資料庫。）

## 收尾

- [x] 全量 `pytest -q`＝**341 passed＋2 skipped**＝零 Ollama 同顆數（外部依賴零實證；
      錯誤表首跑揪出並修復「自創實體＋釘選非原子」真缺陷——`create_and_pin_entity` 單一交易）
- [x] `/openapi.json` 端點數＝**17**、DELETE=0；SQL 只在 repository（三項皆自動化測試）
- [x] 正式庫健檢（六表＋photo.suggested_category 欄、孤兒連結全 0、收件箱唯一）
- [x] CLAUDE.md 現況段更新（已修正「31〜33 未 commit」——實際已含在 commit 0cabb45）；
      unfinish/ 歸檔至 finish/＝隨 commit（本輪產品負責人指示不 commit，歸檔留待 commit 時執行）
