"""GET /folders 與 GET /folders/{id} 的整合測試（Phase 22）。

對應 design1.md §7.4：
  GET /folders      → 全部資料夾（含 description、照片張數）
  GET /folders/{id} → 該資料夾 ＋ 照片摘要（id、thumbnail_url、text、uploaded_at）

這兩個端點沒有任何 AI，所以本檔不需要覆寫任何假件——
conftest 的 reset_tables 每個測試前會重播六筆預設資料夾，因此 id 1〜6 是固定的。
"""

from __future__ import annotations

from datetime import date, datetime

from app.repositories import photo_repository
from tests.fakes import FakeEmbeddings

NOW = datetime(2026, 8, 18, 10, 0)

# 預設資料夾的 id（Phase 15 的種子順序，三處同步：schema.sql／migrate_folders.sql／DEFAULT_FOLDERS）
未分類_ID = 1
收據_ID = 2
飲食_ID = 3


def _插入照片(
    text: str,
    category: str,
    *,
    有縮圖: bool,
    suggested_entity: str | None = None,
    suggested_task_title: str | None = None,
    suggested_task_due: date | None = None,
) -> int:
    """插一張照片並回它的 id。

    insert_photo 會依 category 找同名資料夾（Phase 15），所以 category="收據"
    的照片會自動掛在 2 號資料夾底下。有縮圖的才呼叫 update_photo_paths（Phase 19）
    寫入路徑——沒寫路徑的就等於「舊資料」，thumbnail_url 應該是 null。

    三個建議欄（Phase 61 / design5.md D16）預設不給＝舊照片的樣子（全是 NULL）。
    """
    row = photo_repository.insert_photo(
        text=text,
        category=category,
        location="Target",
        items=["可樂"],
        content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=NOW,
        suggested_entity=suggested_entity,
        suggested_task_title=suggested_task_title,
        suggested_task_due=suggested_task_due,
    )
    photo_id = row["id"]
    if 有縮圖:
        photo_repository.update_photo_paths(
            photo_id,
            original_path=f"data/photos/{photo_id}.png",
            thumbnail_path=f"data/thumbs/{photo_id}.png",
            content_type="image/png",
        )
    return photo_id


def test_列出全部資料夾(client):
    response = client.get("/folders")

    assert response.status_code == 200
    folders = response.json()
    # 直接回陣列（不是 {"folders": [...]}），順序照 id
    assert [f["id"] for f in folders] == [1, 2, 3, 4, 5, 6]
    assert [f["name"] for f in folders] == ["未分類", "收據", "飲食", "風景", "文件", "其他"]
    # 只有「未分類」是收件箱（design1.md §5）
    assert folders[0]["is_inbox"] is True
    assert all(f["is_inbox"] is False for f in folders[1:])
    # description 是給 VLM 看的說明，不能是空字串
    assert folders[0]["description"].startswith("不確定")
    assert all(f["description"] != "" for f in folders)
    # 一張照片都沒有時，六個資料夾仍然全部都要出現（LEFT JOIN），張數 0
    assert all(f["photo_count"] == 0 for f in folders)


def test_回應欄位恰好五個(client):
    """response_model 把關：不多回任何內部欄位（例如 created_at）。"""
    folders = client.get("/folders").json()

    assert set(folders[0]) == {"id", "name", "description", "is_inbox", "photo_count"}


def test_資料夾帶照片張數(client):
    _插入照片("在 Target 購買可樂的收據", "收據", 有縮圖=True)
    _插入照片("在 Costco 購買牛奶的收據", "收據", 有縮圖=False)

    folders = client.get("/folders").json()
    張數 = {f["name"]: f["photo_count"] for f in folders}

    assert 張數["收據"] == 2
    assert 張數["未分類"] == 0
    assert 張數["飲食"] == 0


def test_資料夾內容含照片摘要(client):
    photo_id = _插入照片("在 Target 購買可樂的收據", "收據", 有縮圖=True)

    response = client.get(f"/folders/{收據_ID}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"folder", "photos"}
    assert body["folder"]["name"] == "收據"
    assert body["folder"]["photo_count"] == 1

    assert len(body["photos"]) == 1
    photo = body["photos"][0]
    # Phase 35 起由四鍵變五鍵（suggested_category），
    # Phase 61 起由五鍵變八鍵：上傳改 202 之後，建議只能從這裡讀（design5.md D16、§6.2）
    assert set(photo) == {
        "id",
        "thumbnail_url",
        "text",
        "uploaded_at",
        "suggested_category",
        "suggested_entity",
        "suggested_task_title",
        "suggested_task_due",
    }
    assert photo["id"] == photo_id
    assert photo["text"] == "在 Target 購買可樂的收據"
    # 回的是「網址」不是硬碟路徑，指向 Phase 19 的讀圖端點
    assert photo["thumbnail_url"] == f"/photos/{photo_id}/thumbnail"
    assert photo["uploaded_at"].startswith("2026-08-18")


def test_沒有縮圖的舊照片回null(client):
    """design1.md §10：舊資料路徑是 NULL → 回 null，前端顯示占位，不假裝有圖。"""
    photo_id = _插入照片("沒有原圖的舊資料", "收據", 有縮圖=False)

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert photos[0]["id"] == photo_id
    assert photos[0]["thumbnail_url"] is None


def test_照片新的在前(client):
    先上傳 = _插入照片("先上傳的收據", "收據", 有縮圖=False)
    後上傳 = _插入照片("後上傳的收據", "收據", 有縮圖=False)

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert [p["id"] for p in photos] == [後上傳, 先上傳]


def test_空資料夾回空清單(client):
    response = client.get(f"/folders/{飲食_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["folder"]["name"] == "飲食"
    assert body["folder"]["photo_count"] == 0
    assert body["photos"] == []


def test_資料夾不存在回404(client):
    response = client.get("/folders/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "找不到資料夾"}


def test_摘要帶著實體與待辦的建議(client):
    """design5.md D16／§6.2：上傳改 202 之後，待決定頁只能從這裡讀到建議。

    沒有這三個欄位，實體窗就少了選項①、**待辦窗會永遠不開**。
    """
    photo_id = _插入照片(
        "在 Target 購買可樂的收據",
        "收據",
        有縮圖=True,
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交作業三",
        suggested_task_due=date(2026, 8, 21),
    )

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert photos[0]["id"] == photo_id
    assert photos[0]["suggested_entity"] == "我的 MacBook"
    assert photos[0]["suggested_task_title"] == "繳交作業三"
    assert photos[0]["suggested_task_due"] == "2026-08-21"  # JSON 是 ISO 字串


def test_沒有建議的舊照片三個欄位都是null(client):
    """遷移進來的舊照片沒有建議，是**預期行為**（彈窗照舊只有②③④）。"""
    _插入照片("沒有任何建議的舊資料", "收據", 有縮圖=False)

    photo = client.get(f"/folders/{收據_ID}").json()["photos"][0]

    assert photo["suggested_entity"] is None
    assert photo["suggested_task_title"] is None
    assert photo["suggested_task_due"] is None


def test_待決定的實體建議名字在實體清單裡逐字對得到(client):
    """Phase 70：待決定頁靠「名字」把建議對回整筆實體物件，才拿得到 id 去釘。

    Phase 61 已經釘住 GET /folders/{id} 的八鍵與三個欄位的值；
    這一顆釘的是**跨端點的名字契約**：photo.suggested_entity 那個字串，
    必須與 GET /entities 回的 name **逐字相同**（同樣的大小寫、同樣的空白）。
    只要有一邊做了正規化，前端的
        全部實體.find(e => e.name === photo.suggested_entity)
    就會對不到——實體窗的①會靜靜消失，不會有任何錯誤訊息。

    另外，這一顆走的是**收件箱**那條路（Phase 61 那兩顆用的是「收據」資料夾）：
    待決定頁讀的就是收件箱，兩條路各驗一次。
    """
    photo_repository.create_entity("我的 MacBook", "筆電")
    photo_id = _插入照片(
        "MacBook 的維修發票",
        "未分類",  # insert_photo 會依 category 掛到同名資料夾（Phase 15）
        有縮圖=True,
        suggested_entity="我的 MacBook",
    )

    摘要 = client.get(f"/folders/{未分類_ID}").json()["photos"]
    清單 = client.get("/entities").json()

    assert [p["id"] for p in 摘要] == [photo_id]
    建議名稱 = 摘要[0]["suggested_entity"]
    對到的 = [entity for entity in 清單 if entity["name"] == 建議名稱]
    assert len(對到的) == 1, (
        f"待決定頁靠名字對回實體：「{建議名稱}」在 /entities 裡找不到逐字相同的那一筆"
    )
    assert isinstance(對到的[0]["id"], int), "對到之後要拿得到 id（彈窗要它才釘得上）"
