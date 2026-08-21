# 來源：docs/spec/draft/design-draft.md
# 2026-08-20 依 docs/design/design1.md 正式改版（產品負責人核准解除唯讀）：
#   1. 上傳當下照片一律先歸到「未分類」，VLM 給的類別只是建議，由使用者確認後才定案
#   2. 系統改為保留原始照片檔與縮圖（推翻「不含原始照片檔」的舊定案）
#   3. 成功回應加上所屬資料夾、建議資料夾與完整資料夾清單
Feature: 上傳照片
  使用者透過 FastAPI 上傳照片。
  系統利用 VLM 理解照片內容並轉成文字與結構化 metadata，
  再透過 LangChain 將內容建立成 Document、產生 embedding 向量，
  並使用 PostgreSQL + pgvector 儲存照片資訊、metadata 與向量。
  照片的類別即所屬資料夾的名稱；上傳當下一律為「未分類」，
  VLM 只從現有資料夾清單中推薦一個，由使用者確認後才改變歸屬。

  Rule: 上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗
    # 「圖片格式」指檔案格式（file format）；不設檔案大小上限
    Example: 非圖片格式的檔案上傳失敗
      When 使用者上傳一個非圖片格式的檔案
      Then 操作失敗
      And 系統儲存的照片數量為 0

  Rule: 上傳照片後，系統儲存照片資訊（VLM 理解照片內容後轉成的文字）
    Example: 上傳 Target 收據照片後儲存文字描述
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"

  Rule: 上傳照片後，系統儲存 VLM 產生的結構化 metadata（照片類別、地點/商家、物品清單、內容時間；清單外資訊捨棄），其中照片類別在上傳當下一律為「未分類」
    Example: 上傳 Target 收據照片後儲存結構化 metadata
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 metadata 欄位如下
        | category | location | items        | content_time |
        | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   |
      And 照片所屬資料夾為 "未分類"

  Rule: 上傳照片後，系統儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生）
    Example: 上傳照片後產生 embedding 向量
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 embedding 不為空

  Rule: 上傳照片後，系統記錄上傳時間
    Example: 上傳照片後記錄上傳時間
      Given 現在時間為 "2026-08-18 10:00"
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的上傳時間為 "2026-08-18 10:00"

  Rule: 上傳照片後，系統保留原始照片檔與縮圖
    Example: 上傳照片後保留原圖與縮圖
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的原圖與縮圖都已儲存
      And 回應包含這張照片的縮圖網址

  Rule: 上傳照片成功後，系統回應照片識別碼、文字描述與 metadata
    Example: 上傳成功的回應內容
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 回應包含照片識別碼
      And 回應的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      And 回應的 metadata 欄位如下
        | category | location | items        | content_time |
        | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   |

  Rule: 上傳照片成功後，系統回應照片所屬資料夾、VLM 建議的資料夾與完整資料夾清單
    Example: 上傳成功的回應包含建議資料夾與資料夾清單
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 回應的所屬資料夾為 "未分類"
      And 回應的建議資料夾如下
        | name |
        | 收據 |
      And 回應的資料夾清單包含以下名稱
        | name   |
        | 未分類 |
        | 收據   |
        | 飲食   |
        | 風景   |
        | 文件   |
        | 其他   |

  Rule: VLM 推薦的類別不在資料夾清單中時，建議資料夾改為「未分類」
    Example: VLM 推薦清單外的名稱
      When 使用者上傳一張照片，VLM 推薦的類別為 "Receipt"
      Then 回應的建議資料夾如下
        | name   |
        | 未分類 |
      And 照片的 metadata 類別為 "未分類"

  Rule: VLM 無法理解照片內容時，上傳失敗且不儲存任何資料
    Example: VLM 無法理解照片內容的上傳
      Given VLM 無法理解上傳照片的內容
      When 使用者上傳照片
      Then 操作失敗
      And 系統儲存的照片數量為 0
