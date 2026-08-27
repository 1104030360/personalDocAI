"""folder 資料層的整合測試：連 PersonalDocAI_test 真測試庫。

對應 design1.md §5（六個預設資料夾）與 §7.4（之後瀏覽端點要用的資料）。
每個測試依 tests/conftest.py 的 autouse fixture reset_tables，
在「兩張表清空＋六筆預設資料夾重播完畢」的乾淨狀態下執行，
所以資料夾 id 一定是 1〜6，可以直接寫死。
"""

from datetime import date, datetime

from app.core import config
from app.repositories import photo_repository as repo

# 種子資料夾的 id（Phase 15 定死的順序）
未分類 = 1
收據 = 2
飲食 = 3


def _vec(value: float = 0.01) -> list[float]:
    return [value] * config.EMBEDDING_DIM


def _insert_photo(category: str | None = "收據", text: str = "在 Target 購買可樂的收據"):
    """插一張照片。category 決定它會被掛到哪個資料夾（Phase 15 的自動歸夾）。"""
    return repo.insert_photo(
        text=text,
        category=category,
        location="Target",
        items=["可樂"],
        content_time=date(2026, 8, 10),
        embedding=_vec(),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )


def test_列出六個預設資料夾():
    folders = repo.list_folders()

    assert [f["name"] for f in folders] == ["未分類", "收據", "飲食", "風景", "文件", "其他"]
    assert [f["id"] for f in folders] == [1, 2, 3, 4, 5, 6]
    # 只有「未分類」是收件箱
    assert [f["is_inbox"] for f in folders] == [True, False, False, False, False, False]
    # description 是給 VLM 看的說明，六筆都不可以是空字串
    assert all(f["description"] for f in folders)
    # 鍵名固定，之後的 Pydantic 模型直接照抄
    assert set(folders[0]) == {"id", "name", "description", "is_inbox", "photo_count"}


def test_資料夾的照片張數會跟著上傳累加():
    _insert_photo(category="收據")
    _insert_photo(category="收據")
    _insert_photo(category="Receipt")  # 清單外 → 自動掛未分類

    張數 = {f["name"]: f["photo_count"] for f in repo.list_folders()}

    assert 張數["收據"] == 2
    assert 張數["未分類"] == 1
    assert 張數["飲食"] == 0  # 空資料夾要出現在清單裡，張數是 0（LEFT JOIN 的重點）


def test_取得單一資料夾():
    _insert_photo(category="收據")

    folder = repo.get_folder(收據)

    assert folder["id"] == 收據
    assert folder["name"] == "收據"
    assert folder["description"] == "發票、消費憑證、購物明細。"
    assert folder["is_inbox"] is False
    assert folder["photo_count"] == 1


def test_取得不存在的資料夾回傳_None():
    assert repo.get_folder(999) is None


def test_依名稱尋找資料夾():
    folder = repo.find_folder_by_name("收據")

    assert folder["id"] == 收據
    assert set(folder) == {"id", "name", "description", "is_inbox"}


def test_依名稱尋找不分大小寫():
    """使用者自建英文資料夾之後，再打小寫也要找得到（Phase 21 擋重名要用）。"""
    建立的 = repo.create_folder("Project X", "課程作業相關的照片")

    assert repo.find_folder_by_name("project x")["id"] == 建立的["id"]
    assert repo.find_folder_by_name("PROJECT X")["id"] == 建立的["id"]


def test_名稱不存在時回傳_None():
    assert repo.find_folder_by_name("不存在的資料夾") is None


def test_建立新資料夾後會出現在清單最後():
    建立的 = repo.create_folder("專案X", "跟課程作業有關的照片")

    assert 建立的["id"] == 7  # 六筆種子之後接著編號
    assert 建立的["name"] == "專案X"
    assert 建立的["description"] == "跟課程作業有關的照片"
    assert 建立的["is_inbox"] is False  # 使用者自建的一律不是收件箱

    folders = repo.list_folders()
    assert len(folders) == 7
    assert folders[-1]["name"] == "專案X"
    assert folders[-1]["photo_count"] == 0


def test_列出資料夾內的照片新的在前():
    第一張 = _insert_photo(text="第一張收據")
    第二張 = _insert_photo(text="第二張收據")
    _insert_photo(category="Receipt", text="不屬於收據資料夾")  # 掛未分類，不該出現

    photos = repo.list_photos_in_folder(收據)

    assert [p["id"] for p in photos] == [第二張["id"], 第一張["id"]]  # id 大的（新的）在前
    assert photos[0]["text"] == "第二張收據"
    assert photos[0]["thumbnail_path"] is None  # 還沒有人寫檔（Phase 17〜19 才做）
    # Phase 35 起由四鍵變五鍵（suggested_category 讓待決定分頁畫得出選項①）；
    # Phase 56 起再變八鍵：D16 的三個建議欄，讓待決定分頁不必再看一次圖
    # 就畫得出實體彈窗的選項①與待辦彈窗的預填值（design5.md §6.2）。
    # ★ 這是 repository 這一層的鍵；GET /folders/{id} 的回應仍是五鍵，
    #   PhotoSummary 只挑它要的那幾個——router 改成八鍵是 Phase 61 的事。
    assert set(photos[0]) == {
        "id",
        "text",
        "uploaded_at",
        "thumbnail_path",
        "suggested_category",
        "suggested_entity",
        "suggested_task_title",
        "suggested_task_due",
    }


def test_空資料夾回傳空清單():
    assert repo.list_photos_in_folder(飲食) == []


def test_資料夾內照片摘要帶得出三個建議欄():
    """Phase 61 的 GET /folders/{inbox} 會靠這三個鍵畫實體／待辦彈窗（design5 §6.2）。

    本 phase 只驗「repository 這一層讀得出來」；router 還沒開始外送它們。
    """
    照片 = repo.insert_photo(
        text="MacBook 上打開的 Project 2 報告",
        category="收據",
        location=None,
        items=[],
        content_time=None,
        embedding=_vec(),  # 檔案上方既有的小工具，回一條 1024 維的假向量
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交 Project 2 報告",
        suggested_task_due=date(2026, 8, 21),
    )

    摘要 = repo.list_photos_in_folder(收據)[0]

    assert 摘要["id"] == 照片["id"]
    assert 摘要["suggested_entity"] == "我的 MacBook"
    assert 摘要["suggested_task_title"] == "繳交 Project 2 報告"
    assert 摘要["suggested_task_due"] == date(2026, 8, 21)
