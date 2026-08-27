# 來源：docs/design/design1.md §7.2／§7.3、docs/design/design2.md D1〜D3／D6／D7
# 2026-08-22 依產品負責人指示補進 specs/features
# design2.md 推翻 design1.md「關掉彈窗＝未分類、之後可再歸類」：
#   彈窗不可關；「稍後再說」是明確選項；定案不可逆；不可歸檔到收件箱
# 2026-08-26 依 docs/design/design5.md §10 正式改版（產品負責人核准解除唯讀）：
#   1. design5.md D16 推翻 design2.md D5「待決定的 AI 建議沒有持久化」——
#      建議改為隨入庫寫進照片，所以待決定頁的歸類彈窗有「採用建議」這個選項
Feature: 歸類照片
  使用者確認一張還在待決定（未分類）的照片要進哪個資料夾。
  可以採用現有資料夾、自建新資料夾，或明確選擇稍後再說。
  一旦歸進真資料夾即定案，不可再變更。

  Rule: 將待決定照片歸到現有資料夾後，照片類別等於該資料夾名稱
    Example: 把未分類的收據照片歸到收據
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者將照片 1 歸類到資料夾 "收據"
      Then 照片所屬資料夾為 "收據"
      And 照片的 metadata 類別為 "收據"
      And 照片的 embedding 不為空

  Rule: 自建新資料夾並歸類後，照片進入該資料夾，且資料夾清單含新名稱
    Example: 自建專案X並把照片歸進去
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者為照片 1 自建資料夾，名稱為 "專案X"，說明為 "跟課程作業有關的照片"
      Then 照片所屬資料夾為 "專案X"
      And 照片的 metadata 類別為 "專案X"
      And 系統的資料夾清單包含以下名稱
        | name |
        | 專案X |

  Rule: 自建資料夾名稱與現有資料夾重複時，操作失敗且不覆蓋
    Example: 自建名稱與收據重複
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者為照片 1 自建資料夾，名稱為 "收據"，說明為 "重複的名稱"
      Then 操作失敗
      And 照片所屬資料夾為 "未分類"

  Rule: 自建資料夾名稱為空白時，操作失敗
    Example: 名稱空白
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者為照片 1 自建資料夾，名稱為 ""，說明為 "跟課程作業有關的照片"
      Then 操作失敗
      And 照片所屬資料夾為 "未分類"

  Rule: 使用者選擇稍後再說時，照片仍留在未分類
    Example: 稍後再說不改變歸屬
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者選擇稍後再說
      Then 照片所屬資料夾為 "未分類"

  Rule: 已定案的照片不可再變更資料夾
    Example: 已在收據的照片再歸到飲食
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 收據     | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者將照片 1 歸類到資料夾 "飲食"
      Then 操作失敗
      And 照片所屬資料夾為 "收據"

  Rule: 不可把照片歸檔到未分類
    Example: 待決定照片再歸到未分類
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者將照片 1 歸類到資料夾 "未分類"
      Then 操作失敗
      And 照片所屬資料夾為 "未分類"

  Rule: 照片不存在時，歸類失敗
    Example: 對不存在的照片歸類
      When 使用者將照片 999 歸類到資料夾 "收據"
      Then 操作失敗

  Rule: 目標資料夾不存在時，歸類失敗
    Example: 歸到不存在的資料夾
      Given 系統中有底下照片
        | id | text                             | category | location | items        | content_time | uploaded_at      |
        | 1  | 在 Target 購買可樂與洋芋片的收據 | 未分類   | Target   | 可樂、洋芋片 | 2026-08-10   | 2026-08-18 10:00 |
      When 使用者將照片 1 歸類到資料夾識別碼 999
      Then 操作失敗
      And 照片所屬資料夾為 "未分類"

  Rule: 從待決定頁歸類時，仍可採用入庫當下留下的建議
    # design5.md D16 推翻 design2.md D5：建議已隨入庫寫進照片
    # （suggested_category），所以待決定頁的彈窗有「採用建議」這個選項；
    # 沒有建議的照片照舊只有改選、自建、稍後再說三個出口
    #TODO

  Rule: 建議資料夾為未分類時，不提供採用建議
    # design2.md D6：語意已由「稍後再說」承接
    #TODO

  Rule: 使用者改掉建議時，系統記住此次糾錯
    # design3.md D11：建議被改掉的例子留給下一次看圖；規格文本未給具體建議／選定配對
    #TODO
