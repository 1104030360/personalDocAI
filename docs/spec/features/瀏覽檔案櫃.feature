# 來源：docs/design/design1.md D6／§7.4／§10、docs/design/design2.md D4／D5、docs/design/design3.md D15／§7
# 2026-08-22 依產品負責人指示補進 specs/features
# design2 把瀏覽頁分成「待決定｜資料夾」；design3 再加上「待辦」
# 「未分類」不再以資料夾卡片出現；已定案資料夾的縮圖牆純瀏覽
Feature: 瀏覽檔案櫃
  使用者在瀏覽頁查看尚未歸類的照片、已定案資料夾裡的縮圖，以及已確認的待辦。

  Rule: 開啟瀏覽頁時，目前分頁為待決定
    Example: 預設落在待決定
      When 使用者開啟瀏覽頁
      Then 目前分頁為 "待決定"

  Rule: 待決定區列出尚未歸類的照片
    Example: 未分類的照片出現在待決定區
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
        | 2  | 在 Costco 購買衛生紙的收據       | 收據     | Costco   | 衛生紙       | 2026-08-12   | 2026-08-18 10:05 |
      When 使用者開啟待決定區
      Then 待決定區的照片為底下照片
        | id |
        | 1  |

  Rule: 資料夾清單不包含未分類
    Example: 瀏覽資料夾時看不到未分類
      When 使用者瀏覽資料夾清單
      Then 瀏覽頁的資料夾清單包含以下名稱
        | name |
        | 收據 |
        | 飲食 |
        | 風景 |
        | 文件 |
        | 其他 |
      And 瀏覽頁的資料夾清單不包含以下名稱
        | name   |
        | 未分類 |

  Rule: 點開資料夾後，系統列出該資料夾內的照片
    Example: 開啟收據資料夾
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
        | 2  | 海邊的風景照                     | 風景     | 海邊     |              |              | 2026-08-18 10:10 |
      When 使用者開啟資料夾 "收據"
      Then 該資料夾的照片為底下照片
        | id |
        | 1  |

  Rule: 沒有原圖的照片沒有縮圖網址
    Example: 舊照片沒有縮圖
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      And 照片 1 沒有原圖
      When 使用者開啟資料夾 "收據"
      Then 照片 1 沒有縮圖網址

  Rule: 已定案資料夾內的照片不可再歸類
    # design2.md D4：資料夾 tab 的縮圖牆純瀏覽；再歸類的入口只在待決定區
    #TODO

  Rule: 待辦清單列出已確認的待辦
    Example: 開啟待辦清單
      Given 系統中有底下照片
        | id | text       | category | location | items | content_time | uploaded_at      |
        | 1  | Canvas截圖 | 文件     |          |       |              | 2026-08-18 10:00 |
      And 系統中有底下待辦
        | title        | due        | photo_id |
        | 交 Project 2 | 2026-09-18 | 1        |
      When 使用者開啟待辦清單
      Then 待辦清單如下
        | title        | due        |
        | 交 Project 2 | 2026-09-18 |

  Rule: 點開待辦後，開啟的是該待辦的來源照片
    Example: 從待辦回到來源圖
      Given 系統中有底下照片
        | id | text       | category | location | items | content_time | uploaded_at      |
        | 1  | Canvas截圖 | 文件     |          |       |              | 2026-08-18 10:00 |
      And 系統中有底下待辦
        | title        | due        | photo_id |
        | 交 Project 2 | 2026-09-18 | 1        |
      When 使用者點開待辦 "交 Project 2"
      Then 開啟的照片為底下照片
        | id |
        | 1  |
