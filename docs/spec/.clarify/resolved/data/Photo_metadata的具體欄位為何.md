# 釐清問題

Photo 的結構化 metadata 具體包含哪些欄位？（規格例句涉及購買物品「飲料」、拍攝地點「Target」、照片類別「收據」，但未定義任何欄位）

# 定位

ERM：Photo 實體的 metadata 屬性（目前為單一 string，無欄位定義）

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 固定欄位結構（例如：照片類別、地點/商家、物品清單、時間），需逐一明確定義 |
| B | 由 VLM 自由產生，欄位不固定，以彈性結構（如 JSON）儲存 |
| C | 固定核心欄位（供 metadata search 使用）＋ VLM 自由延伸欄位 |
| Short | 提供其他簡短答案（<=5 字）|

# 影響範圍

- ERM：metadata 是否拆成獨立欄位或子實體
- 功能「自然語言詢問」：PostgreSQL metadata search 能過濾哪些條件（例句「在 Target 拍的收據」需要地點與類別欄位才能查詢）
- 功能「上傳照片」：VLM 產出的驗收標準
- 測試：所有涉及 metadata 的 Example 資料

# 優先級

High
- metadata search 是核心檢索路徑之一，欄位未定義則該路徑的功能與測試皆無法定義

# 依賴/組合

- 建議與「Photo_是否需要記錄時間資訊以支援最近查詢」一併釐清

---
# 解決記錄

- **回答**：僅固定欄位（對應本項目選項 A）——照片類別 (category)、地點/商家 (location)、物品清單 (items)、內容時間 (content_time)；VLM 產出不在清單的資訊一律捨棄
- **更新的規格檔**：spec/erm.dbml、spec/features/上傳照片.feature
- **變更內容**：Photo 的 metadata 單一欄位拆為四個固定欄位並各附 note；Note 新增已釐清決策；「上傳照片」metadata 儲存規則補明固定欄位清單與捨棄原則（時間可能是 metadata 欄位之一）
