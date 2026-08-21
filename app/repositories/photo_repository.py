"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
本檔含上傳寫入、兩條檢索查詢（search_by_metadata／search_by_vector，Phase 9 加入），
以及資料夾（folder）相關操作（Phase 15 加入）。
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
    "original_path, thumbnail_path, content_type"
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
) -> dict[str, Any]:
    """寫入一張照片。一條 INSERT 寫完全部欄位，天然原子——不會存到一半。

    uploaded_at 傳 None（正式情況）時，由資料庫的 now() 自動記錄上傳時間；
    測試需要固定時間時才會傳入指定值。這靠下面 SQL 的 COALESCE 做到——
    COALESCE(a, b)＝a 有值就用 a、a 是空的（NULL）才改用 b。
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
            text, category, folder_id, location, items, content_time, uploaded_at, embedding
        )
        VALUES (
            %(text)s, %(category)s,
            COALESCE(
                (SELECT id FROM folder WHERE lower(name) = lower(%(category)s::text)),
                (SELECT id FROM folder WHERE is_inbox)
            ),
            %(location)s, %(items)s, %(content_time)s,
            COALESCE(%(uploaded_at)s::timestamptz, now()),
            %(embedding)s::vector
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
    RESTART IDENTITY＝清空後 id 重新從 1 開始編。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE photo RESTART IDENTITY;")


def reset_folders_and_photos() -> None:
    """把兩張表清空並重播六筆預設資料夾。只給測試用。

    TRUNCATE photo, folder＝一次清空兩張表（photo 用外鍵指著 folder，
    所以兩張要一起清，不能只清 folder）；
    RESTART IDENTITY＝把自動編號歸零，重播後 folder 的 id 一定是 1〜6；
    CASCADE＝連同被外鍵指著的相關表一起清（這裡兩張本來就都寫進去了，加著保險）。
    """
    # 絕不清到正式庫：URL 必須含 PersonalDocAI_test 才動手（與 conftest 的防呆雙保險）
    assert "PersonalDocAI_test" in config.DATABASE_URL

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE photo, folder RESTART IDENTITY CASCADE;")
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

    只取瀏覽需要的四個欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path
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
