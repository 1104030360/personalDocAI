# 來源：docs/design/design3.md D9／D12／§2.1／§4
# 2026-08-22 依產品負責人指示補進 specs/features
# 實體是別針（可重疊），不是抽屜；AI 一次只建議 1 個；只有自創才讓清單 +1
Feature: 釘選實體
  使用者為一張照片釘上真實世界的物件。
  可以採用建議、改選現有、自創，或略過不釘。
  一張照片可釘多個實體；建議只能從現有清單挑，清單外不當成新名字自動寫入。

  Rule: 將現有實體釘到照片後，該照片帶著這個實體
    Example: 把我的 MacBook 釘到維修發票
      Given 系統中有底下照片
        | id | text     | category | location | items | content_time | uploaded_at      |
        | 1  | 維修發票 | 未分類   |          |       |              | 2026-08-18 10:00 |
      And 系統中有底下實體
        | name         |
        | 我的 MacBook |
      When 使用者將實體 "我的 MacBook" 釘到照片 1
      Then 照片 1 釘上的實體如下
        | name         |
        | 我的 MacBook |

  Rule: 自創實體後，實體清單新增該名稱，且照片釘上它
    Example: 自創我的 MacBook 並釘上
      Given 系統中有底下照片
        | id | text     | category | location | items | content_time | uploaded_at      |
        | 1  | 維修發票 | 未分類   |          |       |              | 2026-08-18 10:00 |
      When 使用者為照片 1 自創實體 "我的 MacBook"
      Then 照片 1 釘上的實體如下
        | name         |
        | 我的 MacBook |
      And 系統的實體清單包含以下名稱
        | name         |
        | 我的 MacBook |

  Rule: 使用者略過釘選時，照片不釘任何實體
    Example: 不釘，繼續
      Given 系統中有底下照片
        | id | text       | category | location | items | content_time | uploaded_at      |
        | 1  | Canvas截圖 | 未分類   |          |       |              | 2026-08-18 10:00 |
      When 使用者略過釘選實體
      Then 照片 1 釘上的實體數量為 0

  Rule: 一張照片可以釘上多個實體
    # design3.md D12 明示可釘好幾個；規格文本只給了「我的 MacBook」一個實體名稱
    #TODO

  Rule: 使用者要求再建議一個時，系統再給下一個實體建議
    # design3.md D12：同一窗再給下一個建議；規格文本未給第二個實體名稱
    #TODO
