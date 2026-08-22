"""entity 資料層的整合測試：連 PersonalDocAI_test 真測試庫。

對應 design3.md D12（實體＝別針，不是第二套資料夾）與 §5 的 AND——
資料夾是抽屜，一張照片只能放一個；實體是別針，一張照片可以釘好幾個。

每個測試依 tests/conftest.py 的 autouse fixture reset_tables，
在「四張表清空＋六筆預設資料夾重播完畢」的乾淨狀態下執行，
所以每個測試看到的 entity 表一定是空的，id 可以直接寫死。
"""

from datetime import date, datetime

from app.core import config
from app.repositories import photo_repository as repo


def _vec(value: float = 0.01) -> list[float]:
    return [value] * config.EMBEDDING_DIM


def _insert_photo(text: str = "書桌上的 MacBook"):
    """插一張照片，回傳那一列（別針測試需要一個真的 photo_id 才釘得上去）。"""
    return repo.insert_photo(
        text=text,
        category="其他",
        location=None,
        items=["筆電"],
        content_time=date(2026, 8, 10),
        embedding=_vec(),
        uploaded_at=datetime(2026, 8, 18, 10, 0),
    )


def test_list_entities_初始為空():
    """實體清單不像資料夾有種子——清單只在使用者按「自創」時才變長（D12）。"""
    assert repo.list_entities() == []


def test_create_entity_後list拿得到():
    建立的 = repo.create_entity("我的 MacBook", "2021 M1 Pro")

    assert 建立的["id"] == 1  # 空表開始，第一筆就是 1
    assert 建立的["name"] == "我的 MacBook"
    assert 建立的["description"] == "2021 M1 Pro"
    # 鍵名固定，之後 Phase 30 的 Pydantic 模型直接照抄
    assert set(建立的) == {"id", "name", "description"}

    entities = repo.list_entities()
    assert len(entities) == 1
    assert entities[0]["name"] == "我的 MacBook"  # 名稱原文照存，不改寫


def test_find_entity_by_name_大小寫不敏感():
    """Phase 30 的「自創實體」會先用這個函式擋重名（回 409）。"""
    建立的 = repo.create_entity("MacBook", "工作用筆電")

    # 大小寫不同、前後多空白，都要找得到同一筆
    assert repo.find_entity_by_name("  macbook ")["id"] == 建立的["id"]
    assert repo.find_entity_by_name("MACBOOK")["id"] == 建立的["id"]
    assert set(repo.find_entity_by_name("MacBook")) == {"id", "name", "description"}


def test_find_entity_by_name_查無回傳_None():
    assert repo.find_entity_by_name("不存在的實體") is None


def test_pin與list_photo_entities():
    photo = _insert_photo()
    entity = repo.create_entity("我的 MacBook", "2021 M1 Pro")

    repo.pin_entity(photo["id"], entity["id"])

    釘著的 = repo.list_photo_entities(photo["id"])
    assert len(釘著的) == 1
    assert 釘著的[0]["id"] == entity["id"]
    assert 釘著的[0]["name"] == "我的 MacBook"
    assert 釘著的[0]["description"] == "2021 M1 Pro"
    # 只回實體本身的三個欄位，不外送 photo_id／pinned_at 這些連結細節
    assert set(釘著的[0]) == {"id", "name", "description"}


def test_沒釘任何實體的照片回傳空清單():
    photo = _insert_photo()

    assert repo.list_photo_entities(photo["id"]) == []


def test_is_pinned():
    photo = _insert_photo()
    釘了的 = repo.create_entity("我的 MacBook", "2021 M1 Pro")
    沒釘的 = repo.create_entity("我的相機", "旅遊用")

    repo.pin_entity(photo["id"], 釘了的["id"])

    assert repo.is_pinned(photo["id"], 釘了的["id"]) is True
    assert repo.is_pinned(photo["id"], 沒釘的["id"]) is False


def test_同一照片可釘多個實體():
    """一張照片可以同時是「我的 MacBook」和「Project 2」——這就是別針的 AND（§5）。"""
    photo = _insert_photo(text="MacBook 上打開的 Project 2 報告")
    先釘的 = repo.create_entity("我的 MacBook", "2021 M1 Pro")
    後釘的 = repo.create_entity("Project 2", "課程專案")

    repo.pin_entity(photo["id"], 先釘的["id"])
    repo.pin_entity(photo["id"], 後釘的["id"])

    釘著的 = repo.list_photo_entities(photo["id"])
    assert [e["name"] for e in 釘著的] == ["我的 MacBook", "Project 2"]  # 先釘的在前


def test_同一個實體可以被多張照片釘():
    """反過來也成立：多張圖同一件東西，正是實體存在的理由（§5「抽屜是 XOR、實體才是 AND」）。"""
    第一張 = _insert_photo(text="書桌上的 MacBook")
    第二張 = _insert_photo(text="咖啡廳裡的 MacBook")
    entity = repo.create_entity("我的 MacBook", "2021 M1 Pro")

    repo.pin_entity(第一張["id"], entity["id"])
    repo.pin_entity(第二張["id"], entity["id"])

    assert repo.is_pinned(第一張["id"], entity["id"]) is True
    assert repo.is_pinned(第二張["id"], entity["id"]) is True
    # 兩張各自都只看到自己釘的那一筆
    assert [e["id"] for e in repo.list_photo_entities(第一張["id"])] == [entity["id"]]
    assert [e["id"] for e in repo.list_photo_entities(第二張["id"])] == [entity["id"]]
