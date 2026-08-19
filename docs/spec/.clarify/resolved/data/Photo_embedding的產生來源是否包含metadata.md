# 釐清問題

embedding 的產生來源「內容」是否同時包含 VLM 轉成的文字與結構化 metadata？（規格寫「透過 LangChain 將內容建立成 Document、產生 embeddings」，但「內容」範圍未明確）

# 定位

ERM：Photo 實體的跨屬性不變條件「embedding 由內容產生」中，來源屬性為 text（文字）或 text + metadata

# 多選題

| 選項 | 描述 |
|--------|-------------|
| A | 僅以 VLM 轉成的文字產生 embedding |
| B | 以文字＋metadata 合併後產生 embedding |
| Short | 提供其他簡短答案（<=5 字）|

# 影響範圍

- ERM：Photo 的跨屬性不變條件定義
- 功能「上傳照片」：儲存 embeddings 向量規則的驗收內容
- 功能「自然語言詢問」：vector semantic search 能召回的資訊範圍（metadata 是否參與語意檢索）

# 優先級

Medium
- 不阻礙核心建模，但影響檢索品質的定義與上傳規則的可驗證性

---
# 解決記錄

- **回答**：B - 以文字＋metadata（category、location、items、content_time）合併後產生 embedding
- **更新的規格檔**：spec/erm.dbml、spec/features/上傳照片.feature
- **變更內容**：embedding 欄位 note 與跨屬性不變條件改為「文字＋metadata 合併之內容產生」，移除「規格未明確定義」區段（已全數釐清）；「上傳照片」embeddings 規則補明來源
