"""全系統唯一寫 SQL 的模組：psycopg 3 ＋ 手寫 SQL。

routers 與 services 一律呼叫這裡的函式，不得自己寫 SQL。
（Phase 9 會在這個檔案加上兩條檢索查詢。）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.db.session import get_connection

# 每次查詢都取回的欄位，固定順序，避免各處寫法不一致
PHOTO_COLUMNS = "id, text, category, location, items, content_time, uploaded_at"


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
    sql = f"""
        INSERT INTO photo (text, category, location, items, content_time, uploaded_at, embedding)
        VALUES (
            %(text)s, %(category)s, %(location)s, %(items)s, %(content_time)s,
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
