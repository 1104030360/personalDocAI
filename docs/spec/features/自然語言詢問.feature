# 來源：docs/spec/draft/design-draft.md
Feature: 自然語言詢問
  使用者直接用自然語言詢問照片相關問題。
  系統使用 LangGraph 建立 retrieval workflow，根據問題類型決定走 vector semantic search
  或 PostgreSQL metadata search，最後把檢索到的內容交給 LLM 產生回答。

  Rule: 詢問時，系統根據問題類型決定走 vector semantic search 或 PostgreSQL metadata search
    # 分類標準：由 LLM 判斷——問題帶明確過濾條件（商家、類別、時間）走 metadata search；語意/內容描述型走 vector semantic search

    Example: 條件過濾型問題走 metadata search
      When 使用者詢問 "有哪些在 Target 拍的收據？"
      Then 系統選擇的檢索方式為 "metadata search"

    Example: 語意描述型問題走 vector semantic search
      When 使用者詢問 "我最近買過什麼飲料？"
      Then 系統選擇的檢索方式為 "vector semantic search"

  Rule: 詢問含時間條件時，系統以內容時間過濾，內容時間為空的照片以上傳時間過濾
    # 「最近」定義為詢問當下時間回推 30 天內
    Example: 最近的照片以內容時間優先過濾、缺漏時用上傳時間
      Given 現在時間為 "2026-08-18 10:00"
      And 系統中有底下照片
        | id | text                     | category | location | items | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂的收據 | 收據     | Target   | 可樂  | 2026-08-10   | 2026-08-18 10:00 |
        | 2  | 在 Costco 購買牛奶的收據 | 收據     | Costco   | 牛奶  | 2026-05-01   | 2026-08-17 09:00 |
        | 3  | 在 7-11 購買咖啡的收據   | 收據     | 7-11     | 咖啡  |              | 2026-08-15 12:00 |
      When 使用者詢問 "我最近買過什麼飲料？"
      Then 時間過濾後的照片為底下照片
        | id |
        | 1  |
        | 3  |

  Rule: 無法判斷問題類型時，系統走 vector semantic search
    Example: 模糊問題走 vector semantic search
      When 使用者詢問 "幫我找找之前那個"
      Then 系統選擇的檢索方式為 "vector semantic search"

  Rule: 檢索不到任何相關內容時，系統回覆查無相關照片（由 LLM 產生，不得編造照片內容）
    Example: 沒有任何照片時詢問
      Given 系統中沒有任何照片
      When 使用者詢問 "有哪些在 Target 拍的收據？"
      Then 使用者獲得查無相關照片的回覆

  Rule: 詢問後，系統將檢索到的內容交給 LLM 產生回答
    Example: 詢問在 Target 拍的收據
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
        | 2  | 在 Costco 購買衛生紙的收據       | 收據     | Costco   | 衛生紙       | 2026-08-12   | 2026-08-18 10:05 |
        | 3  | 海邊的風景照                     | 風景     | 海邊     |              |              | 2026-08-18 10:10 |
      When 使用者詢問 "有哪些在 Target 拍的收據？"
      Then 回答依據的檢索結果為底下照片
        | id |
        | 1  |

    Example: 詢問最近買過的飲料
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
        | 2  | 在 Costco 購買衛生紙的收據       | 收據     | Costco   | 衛生紙       | 2026-08-12   | 2026-08-18 10:05 |
        | 3  | 海邊的風景照                     | 風景     | 海邊     |              |              | 2026-08-18 10:10 |
      When 使用者詢問 "我最近買過什麼飲料？"
      Then 回答提及底下物品
        | name |
        | 可樂 |
