# 釐清策略總覽 (Discovery Overview)

掃描對象：`spec/erm.dbml`、`spec/features/上傳照片.feature`、`spec/features/自然語言詢問.feature`
（原始規格：`docs/spec/draft/design-draft.md`）

## 1. 釐清項目統計

- 資料模型相關：0 項（原 7 項，已全數解決）
- 功能模型相關：0 項（原 8 項＋補遺輪 3 項，已全數解決）
- 總計：0 項待處理（18 項已全數歸檔於 `resolved/`）

## 2. 優先級分佈

- High：0 項（原 5 項，已解決）
- Medium：0 項（原 9 項＋補遺輪 3 項，已解決）
- Low：0 項（原 1 項，已解決）

## 3. 建議釐清順序

首輪四個階段（15 項）與補遺輪（3 項）均已於 2026-08-18 的 Clarify 互動中全數解決，決策記錄見各歸檔項目檔案底部的「解決記錄」。

## 4. 釐清策略說明

- **排除項目**（依「若技術棧問題不阻礙功能釐清則不列入」與「更適合延後到規劃階段」原則）：
  - embedding 的向量維度與 pgvector 型別細節（依賴 embedding model 選擇，屬規劃階段）
  - id 的生成方式（實作細節）
  - FastAPI 端點路徑、LangGraph 節點結構等技術棧設計（不阻礙功能釐清）
- **釐清過程中發現的新歧義**：已於補遺輪收錄為第 16–18 項釐清項目並全數解決

## 5. 覆蓋度摘要

| 分類 | 狀態 | 說明 |
|------|------|------|
| A1. 實體完整性 | Resolved | 單一使用者系統，不建 User 實體；Document 為非持久化中間物，不建模 |
| A2. 屬性定義 | Resolved | 不儲存原始照片檔；metadata 固定四欄位；上傳＋內容時間 |
| A3. 屬性值邊界條件 | Resolved | VLM 失敗則不儲存（無 text 為空的記錄）；content_time 可為空、uploaded_at 必有值 |
| A4. 跨屬性不變條件 | Resolved | embedding 由文字＋metadata 合併之內容產生 |
| A5. 關係與唯一性 | Resolved | 單一使用者、單一實體，無實體關係需求 |
| A6. 生命週期與狀態 | Resolved | 同步處理，無處理狀態欄位需求 |
| B1. 功能識別 | Clear | 兩個交互點（上傳照片、自然語言詢問）皆已識別 |
| B2. 規則完整性 | Resolved | 路由標準、檔案格式限制、上傳回應均已釐清 |
| B3. 例子覆蓋度 | Resolved | 12 條規則全數有 Example（#TODO 已清空） |
| B4. 邊界條件覆蓋 | Resolved | 時間（區間內/外/空值替代）、狀態、類別邊界均有對應 Example；無數值屬性約束需求 |
| B5. 錯誤與異常處理 | Resolved | VLM 失敗（不儲存）、無法判斷類型（預設 vector search）、檢索不到內容（LLM 回覆查無） |
| C1. 詞彙表 | Resolved | 術語統一決策已記錄於 erm.dbml Note（照片、向量/embedding） |
| C2. 術語衝突 | Resolved | 「圖片」正規化為「照片」（「圖片格式」指檔案格式，保留）；向量/embedding 用法已定 |
| D1. 待決事項 | Resolved | 規格檔中已無任何 #TODO 或未決議事項 |
| D2. 模糊描述 | Resolved | 「問題類型」已釐清（LLM 判斷）；「最近」量化為詢問當下回推 30 天內 |
