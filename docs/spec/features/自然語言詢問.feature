# 來源：docs/spec/draft/design-draft.md
# 2026-08-22 依 docs/design/design3.md D14／§6 追加兩條 Rule（產品負責人指示補 features）：
#   問到已確認的實體名稱 → 沿別針列出掛著的照片
#   問到待辦／到期 → 查待辦表
# 這兩條套 @未實作（Phase 34 尚未落地）；既有 Q1〜Q5 例子一字未動
# 2026-08-23 產品負責人核准解除唯讀（design4.md §1.1「規格 .feature 本輪不改」的正式例外）：
#   1. 最後兩條 Rule（實體別針／待辦）的 @未實作 摘除——Phase 34 已落地
#      （檢索方式全名 entity pin search／task search）
#   2. 待辦例子的到期日 2026-09-18 → 2026-08-21：原本的日期落在問句「這週」的
#      7 天窗之外（今天 2026-08-18 ＋ 7 ＝ 2026-08-25），例子與它自己的問句互相矛盾
Feature: 自然語言詢問
  使用者直接用自然語言詢問照片相關問題。
  系統使用 LangGraph 建立 retrieval workflow，根據問題類型決定走 vector semantic search、
  PostgreSQL metadata search、實體別針查詢或待辦查詢，最後把檢索到的內容交給 LLM 產生回答。
  仍是一次一問一答；檢索來源由路由／檢索層決定，不讓模型自己呼叫工具。

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

  Rule: 問到已確認的實體名稱時，系統沿實體別針列出掛著的照片
    # 驗收問句來自 design3.md §6；檢索方式對外全名為 entity pin search

    Example: 問跟我 MacBook 有關的全部
      Given 系統中有底下照片
        | id | text     | category | location | items | content_time | uploaded_at      |
        | 1  | 維修發票 | 收據     |          |       |              | 2026-08-18 10:00 |
        | 2  | 海邊風景 | 風景     | 海邊     |       |              | 2026-08-18 10:10 |
      And 照片 1 釘上實體 "我的 MacBook"
      When 使用者詢問 "跟我 MacBook 有關的全部"
      Then 系統選擇的檢索方式為 "entity pin search"
      And 回答依據的檢索結果為底下照片
        | id |
        | 1  |

  Rule: 問到待辦或到期時，系統查待辦表
    # 驗收問句來自 design3.md §6；檢索方式對外全名為 task search

    Example: 問這週要交什麼
      Given 現在時間為 "2026-08-18 10:00"
      And 系統中有底下照片
        | id | text       | category | location | items | content_time | uploaded_at      |
        | 1  | Canvas截圖 | 文件     |          |       |              | 2026-08-18 10:00 |
      And 系統中有底下待辦
        | title        | due        | photo_id |
        | 交 Project 2 | 2026-08-21 | 1        |
      When 使用者詢問 "這週要交什麼"
      Then 系統選擇的檢索方式為 "task search"
      And 回答依據的待辦如下
        | title        |
        | 交 Project 2 |
