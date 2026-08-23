"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
本檔含上傳寫入、兩條檢索查詢（search_by_metadata／search_by_vector，Phase 9 加入）、
資料夾（folder）相關操作（Phase 15 加入），
實體（entity）與別針（photo_entity）相關操作（Phase 29 加入），
以及待辦（task）相關操作（Phase 32 加入）。
詢問的檢索查詢自 Phase 34 起共四條：search_by_metadata／search_by_vector 之外，
再加 list_photos_with_entity（沿別針）與 search_tasks（查待辦表）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core import config
from app.db.session import get_connection

# 每次查詢都取回的欄位，固定順序，避免各處寫法不一致。
# insert_photo 的 RETURNING 與 fetch_photo 的 SELECT 共用這一份，兩邊鍵名保證一致。
PHOTO_COLUMNS = (
    "id, text, category, folder_id, location, items, content_time, uploaded_at, "
    "original_path, thumbnail_path, content_type, suggested_category"
)

# 六筆預設資料夾（design1.md §5 原文）。
# ★ 順序就是 id 1〜6，且三個地方必須一模一樣：
#   db/schema.sql、db/migrate_folders.sql、這裡。改動等於改規格。
DEFAULT_FOLDERS: list[tuple[str, str, bool]] = [
    ("未分類", "不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。", True),
    ("收據", "發票、消費憑證、購物明細。", False),
    ("飲食", "食物、飲料、餐廳、菜單。", False),
    ("風景", "戶外、旅遊、地點、景色。", False),
    ("文件", "非收據的文字資料，例如名片、說明書。", False),
    ("其他", "看懂是什麼，但不符合上面任何一個。", False),
]

# 資料夾每次查詢都取回的欄位，固定順序（不含張數——張數只有 list_folders／get_folder 才算）
FOLDER_COLUMNS = "id, name, description, is_inbox"

# 實體每次查詢都取回的欄位，固定順序。
# 不含 created_at：彈窗只需要「挑得出是哪一個」的資訊，建立時間沒人看。
ENTITY_COLUMNS = "id, name, description"

# 待辦每次查詢都取回的欄位，固定順序。
# 含 created_at：待辦清單的排序要用它當第二順位（見 list_tasks），
# 但它不會外送給前端——只外送哪幾個欄位由 schemas/task.py 的 TaskOut 決定。
TASK_COLUMNS = "id, photo_id, title, due_date, created_at"

# 待辦的三段排序，list_tasks 與 search_tasks 共用**同一份字串**——
# 抄成兩份的話日後只改一邊就會漂移，清單頁與詢問看到的先後就對不上了
# （與 PHOTO_COLUMNS 兩處共用是同一個慣例）。三段的用意見 list_tasks 的 docstring。
TASK_ORDERING = "t.due_date ASC NULLS LAST, t.created_at DESC, t.id DESC"


def to_vector_literal(embedding: list[float]) -> str:
    """把 Python 的數字清單轉成 pgvector 認得的字串，例如 '[0.1,0.2,0.3]'。"""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def insert_photo(
    *,
    text: str,
    category: str | None,
    location: str | None,
    items: list[str],
    content_time: date | None,
    embedding: list[float],
    uploaded_at: datetime | None = None,
    suggested_category: str | None = None,
) -> dict[str, Any]:
    """寫入一張照片。一條 INSERT 寫完全部欄位，天然原子——不會存到一半。

    uploaded_at 傳 None（正式情況）時，由資料庫的 now() 自動記錄上傳時間；
    測試需要固定時間時才會傳入指定值。這靠下面 SQL 的 COALESCE 做到——
    COALESCE(a, b)＝a 有值就用 a、a 是空的（NULL）才改用 b。

    suggested_category＝上傳當下 VLM 建議的資料夾名稱（Phase 35，已釐清 B）。
    它與照片實際歸屬無關（歸屬看 folder_id，上傳一律是收件箱），
    只是「當時猜了什麼」的存根；沒有建議就留 None，定案時一律不算糾錯。
    """
    # 欄位「名稱」清單用 f-string 帶入（固定常數）；欄位「值」一律用 %(名稱)s
    # 參數帶入，交給 psycopg 安全處理——避免 SQL injection（輸入內容被誤當 SQL 執行）
    # folder_id 由 SQL 當場算出來：
    #   ① 先找名稱和 category 一樣的資料夾（lower() ＝不分大小寫，'receipt' 也對得到 'Receipt'）
    #   ② 找不到（含 category 為 NULL）就退回收件箱「未分類」
    # 兩個子查詢包在 COALESCE 裡，整段仍然是「一條 INSERT」，天然原子。
    # ★ category 欄位的值本身不動——把它改寫成資料夾名稱是 Phase 20（上傳）與 Phase 21（歸類）的事。
    sql = f"""
        INSERT INTO photo (
            text, category, folder_id, location, items, content_time, uploaded_at,
            embedding, suggested_category
        )
        VALUES (
            %(text)s, %(category)s,
            COALESCE(
                (SELECT id FROM folder WHERE lower(name) = lower(%(category)s::text)),
                (SELECT id FROM folder WHERE is_inbox)
            ),
            %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector, %(suggested_category)s
        )
        RETURNING {PHOTO_COLUMNS};
    """
    params = {
        "text": text,
        "category": category,
        "location": location,
        "items": items,
        "content_time": content_time,
        "uploaded_at": uploaded_at,
        "embedding": to_vector_literal(embedding),
        "suggested_category": suggested_category,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetch_photo(photo_id: int) -> dict[str, Any] | None:
    """依 id 取回一張照片；找不到回 None。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PHOTO_COLUMNS} FROM photo WHERE id = %(id)s;",
                {"id": photo_id},
            )
            return cur.fetchone()


def fetch_embedding(photo_id: int) -> str | None:
    """取回某張照片的向量（字串形式），用來確認向量不為空。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding::text AS embedding FROM photo WHERE id = %(id)s;",
                {"id": photo_id},
            )
            row = cur.fetchone()
            return row["embedding"] if row else None


def count_photos() -> int:
    """目前存了幾張照片。驗收規則「系統儲存的照片數量為 0」會用到。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM photo;")
            return cur.fetchone()["n"]


def clear_photos() -> None:
    """清空資料表。只給測試用：每個測試開始前把 photo 表清乾淨。

    TRUNCATE＝一次清空整張表（比逐列 DELETE 快）；
    RESTART IDENTITY＝清空後 id 重新從 1 開始編；
    CASCADE＝連同用外鍵指著 photo 的 photo_entity 與 task 一起清。
    ★ CASCADE 是 Phase 29 加的：那兩張表一出現，不帶 CASCADE 的 TRUNCATE 會被
      PostgreSQL 直接拒絕（cannot truncate a table referenced in a foreign key constraint）。
      語意上也正確——照片沒了，掛在它身上的別針與待辦本來就不該留著。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE photo RESTART IDENTITY CASCADE;")


def reset_folders_and_photos() -> None:
    """把四張表清空並重播六筆預設資料夾。只給測試用。

    TRUNCATE photo, folder, entity, folder_correction＝一次清空四張表；
    RESTART IDENTITY＝把自動編號歸零，重播後 folder 的 id 一定是 1〜6；
    CASCADE＝連同「用外鍵指著上面這些表」的相關表一起清，也就是 photo_entity 與 task
    （兩張都指著 photo）——它們沒有自己的種子資料，被連帶清空就夠了。
    ★ entity 與 folder_correction 沒有被 photo／folder 指著，CASCADE 帶不到，
      所以必須自己列進 TRUNCATE 名單，否則實體會殘留到下一個測試（Phase 29）。
    """
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手（與 conftest 的防呆雙保險）
    assert "PersonalDocAI_test" in config.DATABASE_URL

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE photo, folder, entity, folder_correction "
                "RESTART IDENTITY CASCADE;"
            )
            cur.executemany(
                "INSERT INTO folder (name, description, is_inbox) VALUES (%s, %s, %s);",
                DEFAULT_FOLDERS,
            )


def update_photo_paths(
    photo_id: int,
    *,
    original_path: str,
    thumbnail_path: str,
    content_type: str,
) -> None:
    """把寫好的檔案路徑補回那一列（INSERT 之後、同一個請求之內完成）。

    為什麼要分兩次寫：檔名要用 photo.id，而 id 是 INSERT 當下才配發的，
    所以只能先 INSERT 拿 id、寫完檔再回來補路徑（design1.md §6）。
    """
    sql = """
        UPDATE photo
        SET original_path  = %(original_path)s,
            thumbnail_path = %(thumbnail_path)s,
            content_type   = %(content_type)s
        WHERE id = %(id)s;
    """
    params = {
        "original_path": original_path,
        "thumbnail_path": thumbnail_path,
        "content_type": content_type,
        "id": photo_id,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def delete_photo(photo_id: int) -> None:
    """刪掉一列照片。

    ⚠️ 這**不是**「刪除照片」功能——design1.md §15 明訂本增量不做刪除 API。
    它只給上傳流程的失敗清理用：INSERT 之後寫檔失敗時，
    要把那一列一起收掉，讓整次上傳「像沒發生過」。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM photo WHERE id = %(id)s;", {"id": photo_id})


def update_photo_folder(
    photo_id: int,
    *,
    folder_id: int,
    category: str,
    embedding: list[float],
) -> dict[str, Any]:
    """歸類：一條 UPDATE 同時寫 folder_id、category 與重算後的 embedding。

    三個欄位一起寫，資料庫層面是一次完成的動作——
    不會出現「資料夾改了但向量還是舊的」這種半調子狀態（design1.md §6 的雙寫規則）。

    RETURNING ＝ 改完順便把那一列回傳，省掉再 SELECT 一次。
    """
    sql = f"""
        UPDATE photo
        SET folder_id = %(folder_id)s,
            category  = %(category)s,
            embedding = %(embedding)s::vector
        WHERE id = %(photo_id)s
        RETURNING {PHOTO_COLUMNS};
    """
    params = {
        "photo_id": photo_id,
        "folder_id": folder_id,
        "category": category,
        "embedding": to_vector_literal(embedding),
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def list_folders() -> list[dict[str, Any]]:
    """全部資料夾，依 id 排序，每筆附上裡面有幾張照片。

    用 LEFT JOIN 而不是 JOIN：以資料夾為主，沒有任何照片的資料夾也要出現在清單裡。
    count(p.id) 不會把 NULL 算進去，所以空資料夾正確地得到 0
    （若寫成 count(*) 會變成 1，那是常見的坑）。
    GROUP BY 只寫 f.id 就夠——f.id 是主鍵，PostgreSQL 知道其他 f. 欄位由它唯一決定。
    """
    sql = f"""
        SELECT f.id, f.name, f.description, f.is_inbox, count(p.id) AS photo_count
        FROM folder f
        LEFT JOIN photo p ON p.folder_id = f.id
        GROUP BY f.id
        ORDER BY f.id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def get_folder(folder_id: int) -> dict[str, Any] | None:
    """依 id 取回一個資料夾（含照片張數）；找不到回 None。"""
    sql = """
        SELECT f.id, f.name, f.description, f.is_inbox, count(p.id) AS photo_count
        FROM folder f
        LEFT JOIN photo p ON p.folder_id = f.id
        WHERE f.id = %(id)s
        GROUP BY f.id;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": folder_id})
            return cur.fetchone()


def find_folder_by_name(name: str) -> dict[str, Any] | None:
    """依名稱找資料夾，不分大小寫；找不到回 None。

    lower(name) = lower(輸入)＝兩邊都轉小寫再比，所以 'project x' 找得到 'Project X'。
    中文沒有大小寫，轉了也不變，中文名稱不受影響。
    Phase 21 的「自建資料夾」會先用這個函式擋重名（回 409），
    資料庫的 name UNIQUE 只是最後一道防線。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {FOLDER_COLUMNS} FROM folder WHERE lower(name) = lower(%(name)s::text);",
                {"name": name},
            )
            return cur.fetchone()


def create_folder(name: str, description: str) -> dict[str, Any]:
    """建立一個使用者自訂的資料夾，回傳新的那一列。

    is_inbox 用資料表的預設值 false——收件箱只有系統預設的「未分類」一個，
    使用者建不出第二個（folder_one_inbox 這個部分唯一索引會擋住）。
    重名的判斷交給呼叫端（先用 find_folder_by_name 查），這裡不管 HTTP 狀態碼。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO folder (name, description)
                VALUES (%(name)s, %(description)s)
                RETURNING {FOLDER_COLUMNS};
                """,
                {"name": name, "description": description},
            )
            return cur.fetchone()


def list_photos_in_folder(folder_id: int) -> list[dict[str, Any]]:
    """某個資料夾裡的照片摘要，新的在前（Phase 22 的縮圖牆要用）。

    只取瀏覽需要的五個欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。

    ★ Phase 35 從四欄變五欄：多的 suggested_category 是給「待決定」分頁畫選項①用的
      （design1「摘要恰四鍵」由 phase-35 明文修訂）。有了它，待決定分頁就能拿出
      上傳當下那一筆建議，不必為了畫①再看一次圖。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path, suggested_category
                FROM photo
                WHERE folder_id = %(folder_id)s
                ORDER BY id DESC;
                """,
                {"folder_id": folder_id},
            )
            return cur.fetchall()


def search_by_metadata(
    *,
    category: str | None,
    location: str | None,
    item: str | None,
    recent: bool,
    today: date,
) -> list[dict[str, Any]]:
    """條件查詢：把 route 抽出來的條件全部用 AND 串起來。

    沒有給的條件就不加進 WHERE；一個條件都沒有就等於查全部。

    比對一律用 ILIKE（不分大小寫），所以 'target' 找得到 'Target'——
    這是雙語支援的一部分（design.md §9）。ILIKE 不帶萬用字元時，
    效果就是「不分大小寫的等於」，不會變成模糊比對。
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}

    if category:
        conditions.append("category ILIKE %(category)s")
        params["category"] = category
    if location:
        conditions.append("location ILIKE %(location)s")
        params["location"] = location
    if item:
        # items 是陣列：unnest 把它攤成一列一個元素，逐一做 ILIKE 比對
        conditions.append(
            "EXISTS (SELECT 1 FROM unnest(items) AS i WHERE i ILIKE %(item)s)"
        )
        params["item"] = item
    if recent:
        conditions.append(
            "COALESCE(content_time, uploaded_at::date) >= %(since)s"
        )
        params["since"] = today - timedelta(days=config.RECENT_DAYS)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {PHOTO_COLUMNS} FROM photo {where} ORDER BY id;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def search_by_vector(
    *,
    embedding: list[float],
    recent: bool,
    today: date,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """語意查詢：找向量最接近問題的幾張照片。

    <=> 是 pgvector 的 cosine 距離運算子，數字越小代表意思越接近。
    因為向量是多語模型產生的，英文問題也可能撈到中文內容的照片。
    """
    params: dict[str, Any] = {
        "qvec": to_vector_literal(embedding),
        "limit": limit or config.TOP_K,
    }
    conditions: list[str] = []
    if recent:
        conditions.append(
            "COALESCE(content_time, uploaded_at::date) >= %(since)s"
        )
        params["since"] = today - timedelta(days=config.RECENT_DAYS)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT {PHOTO_COLUMNS}
        FROM photo
        {where}
        ORDER BY embedding <=> %(qvec)s::vector
        LIMIT %(limit)s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# ---------- 實體（entity）＝別針，Phase 29 加入 ----------
# 資料夾是抽屜（一張照片只能放一個，XOR）；實體是別針（一張照片可以釘好幾個，AND）。
# 對應 design3.md D12 與 §5。


def list_entities() -> list[dict[str, Any]]:
    """全部實體，依 id 排序。

    和 list_folders 不同，這裡不附照片張數——Phase 30 的實體彈窗只要一份
    名稱清單讓人挑（D12 的②改選現有），沒有「實體牆」要顯示張數。
    也不像 folder 有六筆種子：實體表一開始是空的，
    清單只在使用者按「自創」時才變長（D12）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {ENTITY_COLUMNS} FROM entity ORDER BY id;")
            return cur.fetchall()


def find_entity_by_name(name: str) -> dict[str, Any] | None:
    """依名稱找實體，不分大小寫且忽略前後空白；找不到回 None。

    寫法鏡射 find_folder_by_name，差別是輸入多包一層 trim()——
    彈窗的輸入框很容易多打一個空白，「 MacBook 」和「MacBook」要算同一件東西。
    Phase 30 的「自創實體」會先用這個函式擋重名（回 409），
    資料庫的 name UNIQUE 只是最後一道防線。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {ENTITY_COLUMNS} FROM entity WHERE lower(name) = lower(trim(%(name)s::text));",
                {"name": name},
            )
            return cur.fetchone()


def create_entity(name: str, description: str) -> dict[str, Any]:
    """只建立一個實體（不釘到任何照片上），回傳新的那一列。

    ⚠ 使用者按「③自創」走的**不是**這一支，而是下面的 create_and_pin_entity——
    自創一定伴隨「釘上去」，兩件事必須同生共死（見那支的說明）。
    這一支留著當資料層的基本寫入（建立與釘選各有一支，才拼得出組合的那一支），
    也是測試準備「已經存在的實體」時用的。

    重名的判斷交給呼叫端（先用 find_entity_by_name 查），
    這裡不自檢、也不管 HTTP 狀態碼——分工與 create_folder 完全一致。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO entity (name, description)
                VALUES (%(name)s, %(description)s)
                RETURNING {ENTITY_COLUMNS};
                """,
                {"name": name, "description": description},
            )
            return cur.fetchone()


def pin_entity(photo_id: int, entity_id: int) -> None:
    """把一個實體釘到一張照片上（在 photo_entity 加一列連結）。

    刻意寫成單純的 INSERT，不做 upsert：重複釘同一個實體要由 Phase 30 的
    router 先用 is_pinned 擋成 409，主鍵 (photo_id, entity_id) 只是最後一道防線。
    這和 create_folder／create_entity 不自檢重名是同一個分工原則——
    資料層只負責寫，狀態碼一律由 router 決定。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO photo_entity (photo_id, entity_id)
                VALUES (%(photo_id)s, %(entity_id)s);
                """,
                {"photo_id": photo_id, "entity_id": entity_id},
            )


def create_and_pin_entity(
    photo_id: int, *, name: str, description: str
) -> dict[str, Any]:
    """自創一個實體**並且**立刻釘到照片上，回傳新的那一列（Phase 37 收尾補的）。

    為什麼不是「呼叫 create_entity 再呼叫 pin_entity」就好？
    因為那是兩條各自開連線的 SQL，中間如果出事（資料庫掛掉、連線斷掉），
    實體已經建好、別針卻沒釘上——使用者拿到 500，之後重試「③自創」同一個名字
    還會撞 409「實體名稱已存在」，可是那個實體其實誰也沒釘上，走進死路。
    這正是 Phase 21「500 時不可以留下空資料夾」的同一條規則（design3 錯誤表：
    寫入失敗時資料庫零半套狀態）。

    這裡的做法是把兩筆 INSERT 放進**同一個交易**：`with get_connection()` 區塊
    正常結束才 commit，區塊裡丟出例外就整批 rollback。所以結果只有兩種——
    「實體建好且釘上」或「什麼都沒發生」，不會有中間狀態。
    （Phase 19 的存檔沒辦法這樣做，因為檔案系統不是交易式的，只好自己清乾淨；
    這裡兩邊都在資料庫裡，交由資料庫保證更可靠。）

    重名與重複釘的判斷仍然交給呼叫端（router 先查、先回 409），
    資料庫的 name UNIQUE 與 photo_entity 主鍵只是最後防線。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO entity (name, description)
                VALUES (%(name)s, %(description)s)
                RETURNING {ENTITY_COLUMNS};
                """,
                {"name": name, "description": description},
            )
            entity = cur.fetchone()
            cur.execute(
                """
                INSERT INTO photo_entity (photo_id, entity_id)
                VALUES (%(photo_id)s, %(entity_id)s);
                """,
                {"photo_id": photo_id, "entity_id": entity["id"]},
            )
            return entity


def is_pinned(photo_id: int, entity_id: int) -> bool:
    """這張照片有沒有釘過這個實體。Phase 30 的重複釘檢查會用到。

    EXISTS ＝資料庫找到第一列就可以停手，不必真的把那一列撈回來。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM photo_entity
                    WHERE photo_id = %(photo_id)s AND entity_id = %(entity_id)s
                ) AS pinned;
                """,
                {"photo_id": photo_id, "entity_id": entity_id},
            )
            return cur.fetchone()["pinned"]


def list_photo_entities(photo_id: int) -> list[dict[str, Any]]:
    """某張照片釘著的全部實體，先釘的在前。

    連結表只存 id，名稱與說明要 JOIN entity 才拿得到。
    ORDER BY 補上 e.id 當第二順位：pinned_at 精確到微秒，
    但兩次釘選理論上可能落在同一微秒，加了才保證排序每次都一樣（測試才穩）。
    只回實體本身的三個欄位——pinned_at 是連結的內部細節，前端用不到。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.name, e.description
                FROM photo_entity pe
                JOIN entity e ON e.id = pe.entity_id
                WHERE pe.photo_id = %(photo_id)s
                ORDER BY pe.pinned_at, e.id;
                """,
                {"photo_id": photo_id},
            )
            return cur.fetchall()


def list_photos_with_entity(entity_id: int) -> list[dict[str, Any]]:
    """釘著某個實體的全部照片（Phase 34 詢問三路的「實體路」）。

    為什麼要有這條、而不是拿 search_by_metadata 湊：
    別針是**明確的人工連結**，問「跟我 MacBook 有關的全部」時就該沿著它走，
    不是去賭照片描述裡剛好有沒有寫到「MacBook」這幾個字（design3.md §6）。

    SELECT 的欄位刻意就是 retrieval_service.row_to_document 要的那六個：
    多帶 embedding 是白撈 1024 個浮點數，少一個則會讓那邊 KeyError。
    ORDER BY p.id ＝與 search_by_metadata 同一種穩定順序（照片 id 遞增），
    不用 pinned_at：使用者問的是「這些照片」，不是「我什麼時候釘的」。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.text, p.category, p.location, p.items, p.content_time
                FROM photo_entity pe
                JOIN photo p ON p.id = pe.photo_id
                WHERE pe.entity_id = %(entity_id)s
                ORDER BY p.id;
                """,
                {"entity_id": entity_id},
            )
            return cur.fetchall()


# ---------- 待辦（task），Phase 32 加入 ----------
# VLM 只給建議（上傳回應的 suggested_task，Phase 30）；人按下「建立」才會走到這裡。
# 對應 design3.md D13 與 §7：一張照片至多一筆待辦（photo_id UNIQUE），
# 沒有完成勾選、沒有刪除、不寫 Gmail／日曆。


def create_task(
    photo_id: int, *, title: str, due_date: date | None
) -> dict[str, Any]:
    """建立一筆待辦，回傳新的那一列。

    due_date 收的是 date 物件（字串怎麼來、格式錯了怎麼辦，是 router 那層
    用 CreateTaskRequest 驗的事）；None ＝這件事沒有期限，照樣是一筆待辦。
    重複建立的判斷交給呼叫端（先用 get_task_by_photo 查），這裡不自檢、
    也不管 HTTP 狀態碼——分工與 create_folder／create_entity 完全一致，
    資料表的 photo_id UNIQUE 只是最後一道防線。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO task (photo_id, title, due_date)
                VALUES (%(photo_id)s, %(title)s, %(due_date)s)
                RETURNING {TASK_COLUMNS};
                """,
                {"photo_id": photo_id, "title": title, "due_date": due_date},
            )
            return cur.fetchone()


def get_task_by_photo(photo_id: int) -> dict[str, Any] | None:
    """這張照片的待辦；還沒建過回 None。

    因為 photo_id 是 UNIQUE，這裡最多只會有一列，不必擔心要挑哪一筆。
    Phase 32 的 router 用它把「同一張照片建第二筆」擋成 409。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {TASK_COLUMNS} FROM task WHERE photo_id = %(photo_id)s;",
                {"photo_id": photo_id},
            )
            return cur.fetchone()


def list_tasks() -> list[dict[str, Any]]:
    """全部待辦，先到期的排前面、沒到期日的排最後。

    ORDER BY 三段各有用意：
      due_date ASC NULLS LAST ＝先到期的先做；沒填期限的不是「最早」而是「最後」。
        （PostgreSQL 的 ASC 預設就是 NULLS LAST，這裡仍寫明白——
         日後若有人改成 DESC，才不會安靜地把沒期限的翻到最前面。）
      created_at DESC ＝同一天到期時，晚建立的排前面。
      id DESC ＝created_at 精確到微秒，但同一個交易裡建的兩筆會拿到一模一樣的
        時間戳；加了 id 才保證排序每次都一樣（測試才穩，與 list_photo_entities
        補 e.id 是同一個教訓）。

    JOIN photo 是為了順便取回來源照片的 thumbnail_path——待辦清單要顯示縮圖。
    用 JOIN 而不是 LEFT JOIN 沒有風險：photo_id 是 NOT NULL 外鍵，
    照片被刪時 ON DELETE CASCADE 會把待辦一起帶走，不存在「孤兒待辦」。
    路徑換算成網址是 router 的事（不洩硬碟路徑）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT t.id, t.photo_id, t.title, t.due_date, t.created_at,
                       p.thumbnail_path
                FROM task t
                JOIN photo p ON p.id = t.photo_id
                ORDER BY {TASK_ORDERING};
                """
            )
            return cur.fetchall()


def search_tasks(due_before: date | None) -> list[dict[str, Any]]:
    """詢問用的待辦查詢（Phase 34 詢問三路的「待辦路」）。

    和 list_tasks 是兩個函式而不是一個帶參數的，理由是它們服務兩件事：
      list_tasks   ＝待辦分頁要「畫清單」，所以 JOIN 取 thumbnail_path。
      search_tasks ＝詢問要「餵給 LLM 回答」，所以 JOIN 取 text（照片描述）；
                     縮圖對回答一點用都沒有。
    排序共用 TASK_ORDERING 這一份常數，兩邊看到的先後才一致（理由見 list_tasks）。

    due_before 是「這週要交什麼」抽出來的範圍上界（route 給 due_within_days，
    檢索層換算成日期）：
      None ＝不限期限，就是「我有哪些待辦」，全部都回。
      有值 ＝**必須有到期日**且落在該日（含當日）以前。
             沒期限的那筆在這裡刻意被排除——它不是「最早到期」，
             而是「這件事沒有 deadline」，列進「這週要交什麼」只會製造假的急迫感。
    """
    params: dict[str, Any] = {}
    where = ""
    if due_before is not None:
        where = "WHERE t.due_date IS NOT NULL AND t.due_date <= %(due_before)s"
        params["due_before"] = due_before

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT t.id, t.photo_id, t.title, t.due_date, t.created_at,
                       p.text
                FROM task t
                JOIN photo p ON p.id = t.photo_id
                {where}
                ORDER BY {TASK_ORDERING};
                """,
                params,
            )
            return cur.fetchall()


# ---------- 抽屜糾錯（folder_correction），Phase 35 加入 ----------
# 「糾錯」＝上傳時 VLM 建議 A、使用者定案時選了 B，而且 A≠B。
# 這些例子會被注入下一次看圖的 prompt 當 few-shot（design3.md D11）——
# 不是第二個模型、也不是微調，只是把「你上次猜錯了什麼」擺在模型眼前。


def record_folder_correction(*, suggested: str, chosen: str, photo_text: str) -> None:
    """記一筆糾錯素材。什麼情況才算糾錯由呼叫端（router）判斷，這裡只負責寫。

    分工與 create_folder／create_entity／create_task 一致：資料層不做規則判斷。
    三個欄位就是 few-shot 例子的全部——題幹（photo_text）＋猜錯的（suggested）
    ＋正確的（chosen）；照片 id 刻意不存，因為 prompt 用不到，
    存了反而讓「刪掉照片」多一層牽扯（本系統也沒有刪除端點）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO folder_correction (suggested, chosen, photo_text)
                VALUES (%(suggested)s, %(chosen)s, %(photo_text)s);
                """,
                {"suggested": suggested, "chosen": chosen, "photo_text": photo_text},
            )


def recent_corrections(limit: int = 5) -> list[dict[str, Any]]:
    """最近幾筆糾錯，新的在前（第 6 筆進來時最舊的那筆就落榜）。

    ORDER BY id DESC ＝新的在前（id 自動遞增，大的就是晚寫的；
    不用 created_at 排序，同一秒內寫兩筆時它分不出先後）。
    只回 few-shot 要用的三個欄位，鍵名即 build_vlm_prompt() 期待的形狀。

    limit 的預設 5 對應 design3.md §7 的暫定 N；正式路徑上的權威值寫在呼叫端
    （api/routers/photos.py 的 FEW_SHOT_CORRECTIONS），這裡的預設只是方便手動呼叫。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT suggested, chosen, photo_text
                FROM folder_correction
                ORDER BY id DESC
                LIMIT %(limit)s;
                """,
                {"limit": limit},
            )
            return cur.fetchall()
