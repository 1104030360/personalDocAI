# 來源：docs/design/design3.md D13／D15／§2.1／§5／§7
# 2026-08-22 依產品負責人指示補進 specs/features
# 待辦不是待決定裡的照片；VLM 只給建議，使用者按「建立」才寫入
# 沒有可辦事項就不開待辦確認（空關不跳，見 上傳照片.feature）
Feature: 建立待辦
  使用者為一張照片確認是否建立待辦。
  可以建立（標題與到期日可改建議），或略過。

  Rule: 使用者確認建立後，該照片有一筆待辦
    Example: 為 Canvas 截圖建立待辦
      Given 系統中有底下照片
        | id | text       | category | location | items | content_time | uploaded_at      |
        | 1  | Canvas截圖 | 未分類   |          |       |              | 2026-08-18 10:00 |
      When 使用者為照片 1 建立待辦，標題為 "交 Project 2"，到期日為 "2026-09-18"
      Then 照片 1 的待辦如下
        | title        | due        |
        | 交 Project 2 | 2026-09-18 |

  Rule: 使用者略過時，該照片沒有待辦
    Example: 略過建立待辦
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者略過建立待辦
      Then 照片 1 沒有待辦

  Rule: 一張照片至多一筆待辦
    # design3.md §5：task 為 0 或 1 筆／圖；規格文本未給第二筆標題
    #TODO
