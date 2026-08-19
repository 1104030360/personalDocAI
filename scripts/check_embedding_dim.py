"""實測 embedding 模型的向量維度，確認 config.EMBEDDING_DIM 設定正確，
順便量一次「中文句子 vs 英文同義句」的相似度，確認多語能力真的存在。

用法（在專案根目錄執行）：python scripts/check_embedding_dim.py
"""

import math
import sys
from pathlib import Path

# 用 `python scripts/check_embedding_dim.py` 執行時，Python 只會在 scripts/
# 資料夾裡找模組，會找不到 app 套件——把專案根目錄加進搜尋路徑就解決了。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config  # noqa: E402  （必須在改完搜尋路徑之後 import）
from app.services import indexing_service  # noqa: E402

中文句 = "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
英文句 = "Receipt from Target with Cola and Chips, dated 2026-08-10"
無關句 = "海邊的風景照"


def cosine(a: list[float], b: list[float]) -> float:
    """兩條向量的 cosine 相似度：1 代表方向完全一樣，0 代表毫無關係。"""
    dot = sum(x * y for x, y in zip(a, b))
    length = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / length if length else 0.0


def main() -> None:
    embeddings = indexing_service.build_ollama_embeddings()
    中文向量 = embeddings.embed_query(中文句)
    英文向量 = embeddings.embed_query(英文句)
    無關向量 = embeddings.embed_query(無關句)

    print(f"模型：{config.EMBEDDING_MODEL}")
    print(f"實測維度：{len(中文向量)}")
    print(f"設定維度（config.EMBEDDING_DIM）：{config.EMBEDDING_DIM}")
    print(f"前 5 個數字：{中文向量[:5]}")
    print(f"中英同義句相似度：{cosine(中文向量, 英文向量):.3f}")
    print(f"中文 vs 無關句相似度：{cosine(中文向量, 無關向量):.3f}")

    if len(中文向量) == config.EMBEDDING_DIM:
        print("✅ 維度一致，不用改任何東西")
    else:
        print("❌ 維度不一致！請照下面兩步修正：")
        print(f"   1. 把 app/core/config.py 的 EMBEDDING_DIM 改成 {len(中文向量)}")
        print(f"   2. 把 db/schema.sql 的 vector(1024) 改成 vector({len(中文向量)})，")
        print("      再執行 psql -d visual_memory -f db/schema.sql")
        print("      與 psql -d visual_memory_test -f db/schema.sql")


if __name__ == "__main__":
    main()
