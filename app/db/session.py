"""資料庫連線。全專案唯一呼叫 psycopg.connect() 的地方。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.core import config


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """開一條資料庫連線，用完自動關閉並 commit。

    - `@contextmanager` ＝讓這個函式可以用 `with ... as conn:` 的寫法，
      區塊結束時自動收尾。
    - `row_factory=dict_row` 讓查詢結果變成字典（欄位名 → 值），比較好讀。
    - 每次呼叫都重新讀 `config.DATABASE_URL`，測試才能把它指到測試資料庫。
    """
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn
