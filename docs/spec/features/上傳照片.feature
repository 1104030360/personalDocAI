# 來源：docs/spec/draft/design-draft.md
Feature: 上傳照片
  使用者透過 FastAPI 上傳照片。
  系統利用 VLM 理解照片內容並轉成文字與結構化 metadata，
  再透過 LangChain 將內容建立成 Document、產生 embedding 向量，
  並使用 PostgreSQL + pgvector 儲存照片資訊、metadata 與向量。

  Rule: 上傳檔案必須為常見圖片格式（如 JPEG、PNG），非圖片格式上傳失敗
    # 「圖片格式」指檔案格式（file format）；不設檔案大小上限
    Example: 非圖片格式的檔案上傳失敗
      When 使用者上傳一個非圖片格式的檔案
      Then 操作失敗
      And 系統儲存的照片數量為 0

  Rule: 上傳照片後，系統儲存照片資訊（VLM 理解照片內容後轉成的文字；不含原始照片檔）
    Example: 上傳 Target 收據照片後儲存文字描述
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"

  Rule: 上傳照片後，系統儲存 VLM 產生的結構化 metadata（照片類別、地點/商家、物品清單、內容時間；清單外資訊捨棄）
    Example: 上傳 Target 收據照片後儲存結構化 metadata
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 metadata 欄位如下
        | category | location | items        | content_time |
        | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   |

  Rule: 上傳照片後，系統儲存透過 LangChain 產生的 embedding 向量（由文字與 metadata 合併之內容產生）
    Example: 上傳照片後產生 embedding 向量
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的 embedding 不為空

  Rule: 上傳照片後，系統記錄上傳時間
    Example: 上傳照片後記錄上傳時間
      Given 現在時間為 "2026-08-18 10:00"
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 照片的上傳時間為 "2026-08-18 10:00"

  Rule: 上傳照片成功後，系統回應照片識別碼、文字描述與 metadata
    Example: 上傳成功的回應內容
      When 使用者上傳一張照片，VLM 理解其內容為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      Then 回應包含照片識別碼
      And 回應的文字描述為 "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
      And 回應的 metadata 欄位如下
        | category | location | items        | content_time |
        | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   |

  Rule: VLM 無法理解照片內容時，上傳失敗且不儲存任何資料
    Example: VLM 無法理解照片內容的上傳
      Given VLM 無法理解上傳照片的內容
      When 使用者上傳照片
      Then 操作失敗
      And 系統儲存的照片數量為 0
