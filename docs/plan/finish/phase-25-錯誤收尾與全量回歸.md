# Phase 25：錯誤收尾與全量回歸（把 design1.md §12 的每一列都釘上一個測試）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 幫 `design1.md` §12「錯誤與邊界」總表的每一列補上一個指著它的測試（已被 Phase 15〜24 覆蓋的列只做對照、不重寫），跑一次全量回歸並**記下最終測試顆數**，用真模型手動走一遍完整體驗，核對正式庫的舊資料沒有弄丟，最後更新 `CLAUDE.md` 現況段並把本批計畫檔歸檔——**本增量的後端到此收尾**（最後一個 phase 是 Phase 26 美化 UI/UX）。

---

## 前置條件

- 需要已完成的 phase：**Phase 15〜24 全部**（資料庫改版、資料夾資料層、檔案儲存、VLM 推薦、上傳存檔與讀圖、未分類流程與規格改版、歸類端點、資料夾瀏覽端點、上傳頁彈窗、瀏覽頁）。
- 開工前基線（**執行時實查，不要抄本文件的數字**）：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q | tail -1
  ```
  本增量開工前（Phase 14 完成時）是 **79 passed**；Phase 15〜24 完成後為 **140 passed**（2026-08-21 開工前實查）。本 phase 完成後 ＝ **149**（140 ＋ 新檔 9）。把實查數字填進步驟 0 的表格。
- 環境：
  - 測試庫 `PersonalDocAI_test` 可用（Phase 15 已用 `db/schema.sql` 重建成最終版）。
  - 正式庫 `PersonalDocAI` 已跑過 `db/migrate_folders.sql`，2 張舊照片仍在。
  - **只有步驟 7（真模型煙霧）需要 Ollama 真的在跑**；步驟 1〜6 全部用假件，絕不碰真模型。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

Phase 15〜24 是「把新功能做出來」。這個 phase 是「確認做出來的東西壞掉時，壞得跟設計說好的一樣」。

三件事：

1. **錯誤路徑逐列把關**：新增 `tests/integration/test_folder_error_paths.py`，對著 `design1.md` §12 的表格一列一列檢查。已經被前面 phase 的測試守住的列，本文件用對照表註明「已由 Phase N 的哪個檔案把關」就好，**不重寫**（重複的測試只會讓改一次程式要改兩個地方）。
2. **全量回歸＋規格全綠**：把所有測試從頭跑一遍，確認新功能沒有把舊功能弄壞；兩份 `.feature` 規格檔（改版後的上傳、完全沒動的詢問）全部綠燈。
3. **真東西確認**：用真模型、真照片手動走一遍完整體驗；用 SQL 核對正式庫那 2 張舊照片還在、掛在「收據」、路徑欄仍是 NULL。

**這個 phase 特別在意兩種「半套失敗」**（新功能才會有的問題，舊的純資料庫流程沒有）：

- **上傳失敗卻留下檔案**：VLM 看不懂時回 422、資料庫什麼都不寫——這是舊行為。但現在多了寫檔這一步，如果失敗時忘了清乾淨，`data/` 底下就會躺著一個誰也管不到的檔案（叫**孤兒檔案**）。所以要有測試盯著「失敗時 `DATA_DIR` 一個檔案都不准有」。
- **歸類失敗卻改到一半**：`PATCH` 要重算 embedding 再更新資料庫。如果算向量的時候 Ollama 掛了，資料庫必須**完全沒動**——不能出現「資料夾換了、向量還是舊的」這種對不起來的狀態；走「自建」那條路時，也不能留下一個**沒有照片的空資料夾**。Phase 21 的實作順序（先算向量，成功後才 create_folder、才下 UPDATE）本來就保證這兩件事，本 phase 用兩個測試把這個順序釘死，以後有人手癢調換順序就會馬上紅燈。

**名詞**：

- **全量回歸（regression test）**＝把到目前為止所有寫過的測試從頭再跑一遍，確認新加的東西沒有把舊功能弄壞。「回歸」指本來好的東西又壞回去。
- **煙霧測試（smoke test）**＝最粗略的「通電看看會不會冒煙」檢查：用真模型、真照片，手動把主要流程走一遍。**不寫成自動化測試、不進 CI**——真 AI 的輸出不是決定論的，放進自動化測試會時好時壞。
- **錯誤路徑（error path）**＝程式「出事時」走的那條分支（回 415／422／404／409／500 的那些），相對於一切順利的「快樂路徑」。
- **孤兒檔案（orphan file）**＝磁碟上存在、但資料庫裡沒有任何一列指向它的檔案。沒人會去讀它，也沒人會去刪它。
- **`DATA_DIR`**＝Phase 17 加在 `app/core/config.py` 的設定，決定原圖與縮圖實際落地的資料夾。跑 pytest 時由 conftest 的 `isolated_data_dir` fixture 指到一個臨時目錄，所以**測試永遠不會寫進專案的 `data/`**。
- **`rglob("*")`**＝Python `pathlib` 的「遞迴列出這個資料夾底下的所有東西」（`r` 是 recursive）。用它來確認「一個檔案都沒有」。
- **`parametrize`**＝pytest 的裝飾器，讓同一個測試函式用不同的輸入跑好幾遍，每一遍算一個測試。
- **`monkeypatch`**＝pytest 內建的 fixture，暫時改掉某個屬性，測試結束自動還原。
- **partial unique index（部分唯一索引）**＝只對「符合條件的那些列」生效的唯一性限制。`folder_one_inbox` 就是這種：只管 `is_inbox = true` 的列，所以全域只可能有一個收件箱，但普通資料夾要幾個有幾個。
- **孤兒外鍵／FK**＝`photo.folder_id` 指向 `folder.id` 的那條關聯。資料庫會擋住「指到不存在的資料夾」。

---

## ASCII 圖：§12 錯誤表 → 測試對照地圖

```
 design1.md §12（錯誤與邊界）＋ §7.2（PATCH 失敗表）      誰在把關
 ══════════════════════════════════════════════════════════════════════════════
 VLM 看不懂 → 422，不建資料夾、不留檔
   ├─ 回 422、資料庫零筆 ─────────────────► Phase 20 test_error_paths.py（既有）
   ├─ DATA_DIR 一個檔都不留 ──────────────► Phase 19 test_photo_files.py
   │                                          （test_422完全不寫檔）
   └─ 不偷偷新增資料夾 ★ ────────────────► 本 phase ①
 非圖片格式 → 415，完全不寫檔
   ├─ 不寫庫、不留檔 ────────────────────► Phase 19 test_photo_files.py
   │                                          （test_415完全不寫檔）
   └─ 不偷偷新增資料夾 ★ ────────────────► 本 phase ①
 VLM 建議不在清單內 → 改建議「未分類」
   ├─ clamp_category 函式層 ─────────────► Phase 18 test_vlm_service_unit.py
   └─ 端點回應 suggested_folder ★ ───────► 本 phase ②
 「未分類」被當成建議 → 允許 ★ ────────────► 本 phase ③
 關掉 modal → 不 PATCH、留在未分類 ────────► Phase 20 test_upload_feature.py
                                             ＋ Phase 23／24 瀏覽器實操清單
 自建重名 → 409，不覆蓋
   ├─ 完全同名 ─────────────────────────► Phase 21 test_assign_folder.py
   └─ 大小寫不同也要 409 ★ ─────────────► 本 phase ④
 讀不到原圖／縮圖 → 404，前端占位
   ├─ 路徑 NULL 的舊列（兩端點）─────────► Phase 19 test_photo_files.py
   ├─ 縮圖檔被刪 → 404 ─────────────────► Phase 19 test_photo_files.py
   ├─ 原圖檔被刪 → 404 ★ ───────────────► 本 phase ⑤（Phase 19 只驗了縮圖那半）
   ├─ 照片 id 不存在（兩端點）───────────► Phase 19 test_photo_files.py
   └─ 前端顯示占位 ─────────────────────► Phase 24 瀏覽器實操清單第 4 項
                                             （本 phase 步驟 7 第 8 項再驗一次）
 PATCH 照片 id 不存在 → 404 ───────────────► Phase 21 test_assign_folder.py
 PATCH folder_id 不存在 → 404 ─────────────► Phase 21 test_assign_folder.py
 PATCH name 空白／兩個都給／都不給 → 422 ──► Phase 21 test_assign_folder.py
 PATCH 途中 embedding 失敗 → 500
   ├─ 採用現有：照片三欄全未變 ★ ────────► 本 phase ⑥
   └─ 自建：連空資料夾都不留 ★ ─────────► 本 phase ⑦
 試圖刪除未分類 → 本增量沒有刪除 API ★ ────► 本 phase ⑧（掃原始碼）
 ══════════════════════════════════════════════════════════════════════════════
 ★ ＝ tests/integration/test_folder_error_paths.py（本 phase 新增，共 9 個測試）
 已被 Phase 15〜24 覆蓋的分支只做對照、不重寫（重複的測試只會讓
 改一次程式要改兩個地方）；Phase 19 那些測試的內容見 test_photo_files.py。
```

**為什麼 ⑥⑦ 一定成立——PATCH 的執行順序圖（Phase 21 刻意排的：所有資料庫寫入都在最後）：**

```
  PATCH /photos/{id}/folder
        │
        ├─ ① fetch_photo ────────── 找不到 → 404      （唯讀，資料庫沒動）
        ├─ ② 決定目標資料夾「名稱」─ 找不到 → 404      （唯讀，資料庫沒動）
        │      folder_id 路：get_folder
        │      name 路：find_folder_by_name 命中 → 409／沒命中也只記下名稱，先不建
        ├─ ③ build_document(目標名稱當 category …)    （純運算，資料庫沒動）
        ├─ ④ embed_document ───────  ✗ 爆炸 → 500  ←★ 這裡掛掉時
        │                                              資料庫完全沒動：照片三欄沒改，
        │                                              連新資料夾都還沒建（不留空資料夾）
        ├─ ⑤ name 路這時才 create_folder             （向量已經算好握在手上）
        └─ ⑥ update_photo_folder    一條 UPDATE 同時寫
               folder_id ＋ category ＋ embedding    （要嘛全寫、要嘛全不寫）
```

---

## 逐步驟操作

### 步驟 0：記下開工基線（2 分鐘，之後每個數字都要跟它比）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# a) 目前測試顆數
pytest -q | tail -1

# b) 本增量開工前的那個 commit——步驟 3 要用它比對規格檔
#（2026-08-21 校準：歷史訊息寫的是「Phase 11〜14」，原 grep「Phase 14」撈不到；
#  基線 commit 實查為 a4e44ef「feat: Phase 11〜14 全數完成」）
git log --oneline -1 a4e44ef
```

把結果填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` 顆數 | ＿＿＿ passed |
| 本增量基線 commit（短 hash） | ＿＿＿＿＿＿ |

### 步驟 1：先紅——建立 `tests/integration/test_folder_error_paths.py`

TDD 的「先紅」在這裡的意思是：**先把測試寫完整跑一次**。如果 Phase 15〜24 都做對了，這 9 個測試應該幾乎全綠——**任何一個紅的，就是前面 phase 漏了一個錯誤路徑，回去補那個 phase 的程式**（不要改測試去遷就程式）。

整份檔案照抄：

```python
"""design1.md §12 錯誤與邊界總表的逐列驗證（Phase 25 收尾）。

已被 Phase 15〜24 的測試覆蓋的列不在這裡重寫；
完整對照表見 docs/plan/finish/phase-25-錯誤收尾與全量回歸.md 的 ASCII 圖。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.dependencies import get_embeddings, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.fakes import FakeVLM, make_png_bytes

# make_png_bytes 是 Phase 17 加在 tests/fakes.py 的小工具，產生 Pillow 打得開的真 PNG。
# 凡是「預期上傳成功」的測試都必須用它——假的位元組（b"\x89PNG"）會讓縮圖那一步爆掉。

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def wire_folder_error_fakes(wire_fake_ai):
    """預設 VLM「看得懂且推薦收據」；其餘假件與固定時鐘由 conftest 的 wire_fake_ai 接管。

    顯式依賴 wire_fake_ai 保證本 fixture 在它之後執行、測後由它統一 clear()。
    個別測試要更壞的行為（看不懂／推薦清單外名稱／會炸的 embeddings）就在測試裡再覆寫。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    yield


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。"""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案（資料夾不算）。

    conftest 的 isolated_data_dir fixture 已把 config.DATA_DIR 指到本次測試專屬的
    臨時目錄，所以這裡看到的一定只有「本測試造成的」檔案。
    """
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


def 上傳一張(client) -> dict:
    """上傳一張成功的照片，回傳 201 的 JSON body。"""
    response = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---- ① 上傳失敗（415／422）時，不寫庫、不留檔、也不建資料夾 ----
@pytest.mark.parametrize(
    "情境, files, vlm看得懂, 預期狀態",
    [
        ("非圖片格式", {"file": ("a.txt", b"hi", "text/plain")}, True, 415),
        ("VLM 看不懂", {"file": ("a.png", make_png_bytes(), "image/png")}, False, 422),
    ],
)
def test_上傳失敗時不寫庫不留檔也不建資料夾(client, 情境, files, vlm看得懂, 預期狀態):
    """design1 §12 第一列：不建資料夾、不留檔。

    「不寫庫」「不留檔」Phase 19／20 已各有測試把關（test_415完全不寫檔、
    test_422完全不寫檔、test_vlm看不懂回422且不寫入），這裡當雙保險一起斷言；
    本測試真正新補的是最後一條——失敗時**資料夾清單必須維持六個預設值**。
    """
    if not vlm看得懂:
        app.dependency_overrides[get_vlm] = lambda: FakeVLM(
            PhotoUnderstanding(understood=False)
        )

    response = client.post("/photos", files=files)

    assert response.status_code == 預期狀態, f"{情境}：狀態碼不對（{response.text}）"
    assert photo_repository.count_photos() == 0, f"{情境}：不可以寫入資料庫"
    assert data_dir底下的檔案() == [], f"{情境}：不可以在 DATA_DIR 留下任何檔案"
    assert len(photo_repository.list_folders()) == 6, f"{情境}：不可以偷偷新增資料夾"


# ---- ② VLM 推薦清單外的名稱 → 建議改成「未分類」 ----
def test_VLM推薦清單外名稱時建議改成未分類(client):
    """design1 §7.1：suggested_folder 必須是 folders 裡的一筆。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(
            understood=True,
            text="A Costco receipt for cola",
            category="Receipts from Costco",   # 六個預設資料夾裡沒有這個名字
            location="Costco",
            items=["cola"],
            content_time="2026-08-11",
        )
    )

    body = 上傳一張(client)

    assert body["suggested_folder"]["name"] == "未分類"
    assert body["folder"]["name"] == "未分類"
    assert body["metadata"]["category"] == "未分類"
    資料夾名稱 = [資料夾["name"] for 資料夾 in body["folders"]]
    assert "Receipts from Costco" not in 資料夾名稱, "清單外的推薦名稱不可以被偷偷建成資料夾"


# ---- ③ 「未分類」被當成建議 → 允許 ----
def test_VLM直接推薦未分類時照樣回201(client):
    """design1 §12：選項①顯示「未分類」與關掉彈窗結果相同，設計上明訂可接受。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(
            understood=True,
            text="一張看不太出來拍什麼的照片",
            category="未分類",
        )
    )

    body = 上傳一張(client)

    assert body["suggested_folder"]["name"] == "未分類"
    assert body["suggested_folder"]["id"] == body["folder"]["id"], (
        "建議與實際歸屬都是未分類時，應該指向同一筆資料夾"
    )


# ---- ④ 自建重名（大小寫不同）→ 409，不新增也不覆蓋 ----
def test_自建資料夾重名大小寫不同也回409且不覆蓋(client):
    """design1 §7.2：自建的 name 與現有資料夾重複（大小寫不敏感）→ 409。

    Phase 21 已驗過「完全同名 → 409」；這裡補的是大小寫不同的那一半。
    """
    第一張 = 上傳一張(client)
    建立 = client.patch(
        f"/photos/{第一張['id']}/folder",
        json={"name": "Project X", "description": "課程作業"},
    )
    assert 建立.status_code == 200, 建立.text
    建立後資料夾數 = len(photo_repository.list_folders())

    第二張 = 上傳一張(client)
    衝突 = client.patch(
        f"/photos/{第二張['id']}/folder",
        json={"name": "project x", "description": "另一個描述"},
    )

    assert 衝突.status_code == 409
    assert len(photo_repository.list_folders()) == 建立後資料夾數, "409 時不可以新增資料夾"
    重名資料夾 = photo_repository.find_folder_by_name("PROJECT X")
    assert 重名資料夾["description"] == "課程作業", "409 時不可以覆蓋原本的 description"
    assert photo_repository.fetch_photo(第二張["id"])["category"] == "未分類", (
        "409 時第二張照片必須留在未分類"
    )


# ---- ⑤ 原圖檔案被刪掉 → 404（不可以爆 500）----
def test_原圖被刪掉時讀原圖回404(client):
    """有人手動刪了 data/photos/ 底下的原圖：要回 404，不是 500。

    §12「讀不到原圖／縮圖」這一列的其他情況——路徑 NULL 的舊列、縮圖檔被刪、
    照片 id 不存在——Phase 19 的 test_photo_files.py 已逐一把關（見 ASCII 對照
    地圖），這裡只補它沒驗到的那一半：**原圖端點**對「檔案不見」的反應。
    """
    body = 上傳一張(client)
    列 = photo_repository.fetch_photo(body["id"])
    storage_service.absolute_path(列["original_path"]).unlink()

    response = client.get(f"/photos/{body['id']}/image")

    assert response.status_code == 404


# ---- ⑥⑦ PATCH 途中 embedding 失敗 → 500，資料庫必須完全沒動 ----
class 會炸的Embeddings:
    """embed_query／embed_documents 一律爆炸——模擬歸類途中 Ollama 掛掉。"""

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("Ollama 沒有回應")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Ollama 沒有回應")


def test_PATCH時embedding失敗回500且照片完全沒被改動(不擲出例外的client):
    """⑥ 採用現有資料夾的那條路：先算向量、最後才一條 UPDATE，算失敗時資料庫沒動。

    有人把順序調換（先 UPDATE 再算向量）的話，這個測試會馬上紅。
    """
    body = 上傳一張(不擲出例外的client)
    photo_id = body["id"]
    改動前 = photo_repository.fetch_photo(photo_id)
    改動前向量 = photo_repository.fetch_embedding(photo_id)
    收據 = photo_repository.find_folder_by_name("收據")

    app.dependency_overrides[get_embeddings] = lambda: 會炸的Embeddings()
    response = 不擲出例外的client.patch(
        f"/photos/{photo_id}/folder", json={"folder_id": 收據["id"]}
    )

    assert response.status_code == 500
    改動後 = photo_repository.fetch_photo(photo_id)
    assert 改動後["folder_id"] == 改動前["folder_id"], "folder_id 不可以被改到"
    assert 改動後["category"] == 改動前["category"] == "未分類", "category 不可以被改到"
    assert photo_repository.fetch_embedding(photo_id) == 改動前向量, "embedding 不可以被改到"


def test_PATCH自建時embedding失敗回500且不留空資料夾(不擲出例外的client):
    """⑦ 自建的那條路：create_folder 排在算向量**之後**，算失敗時連資料夾都不會建。

    有人把 create_folder 提前到算向量之前，就會留下一個誰也沒用到的空資料夾，
    這個測試會馬上紅（Phase 21 就是為了這件事把建資料夾排在算向量之後）。
    """
    body = 上傳一張(不擲出例外的client)
    photo_id = body["id"]
    改動前 = photo_repository.fetch_photo(photo_id)

    app.dependency_overrides[get_embeddings] = lambda: 會炸的Embeddings()
    response = 不擲出例外的client.patch(
        f"/photos/{photo_id}/folder",
        json={"name": "專案Y", "description": "不該被建出來"},
    )

    assert response.status_code == 500
    assert photo_repository.find_folder_by_name("專案Y") is None, "500 時不可以留下空資料夾"
    assert len(photo_repository.list_folders()) == 6, "資料夾必須維持六個預設值"
    改動後 = photo_repository.fetch_photo(photo_id)
    assert 改動後["folder_id"] == 改動前["folder_id"], "folder_id 不可以被改到"
    assert 改動後["category"] == 改動前["category"] == "未分類", "category 不可以被改到"


# ---- ⑧ 本增量沒有刪除 API（未分類不可刪的前提）----
def test_沒有任何刪除端點():
    """design1 §12 最後一列：本增量不做刪除 API。沒有刪除端點，就不可能刪掉未分類。"""
    專案根目錄 = Path(__file__).resolve().parents[2]
    routers目錄 = 專案根目錄 / "app" / "api" / "routers"
    原始碼 = "".join(
        檔案.read_text(encoding="utf-8") for 檔案 in sorted(routers目錄.glob("*.py"))
    )
    原始碼 += (專案根目錄 / "app" / "main.py").read_text(encoding="utf-8")

    for 關鍵字 in ("@router.delete", "@app.delete"):
        assert 關鍵字 not in 原始碼, f"本增量不做刪除 API，不該出現：{關鍵字}"
```

### 步驟 2：跑新檔，確認 9 passed

```bash
pytest tests/integration/test_folder_error_paths.py -v
```

預期最後一行：`9 passed`。

組成（8 個測試函式，其中 1 個帶參數）：

| 測試函式 | 個數 |
|---|---|
| `test_上傳失敗時不寫庫不留檔也不建資料夾`（415／422 兩組） | 2 |
| `test_VLM推薦清單外名稱時建議改成未分類` | 1 |
| `test_VLM直接推薦未分類時照樣回201` | 1 |
| `test_自建資料夾重名大小寫不同也回409且不覆蓋` | 1 |
| `test_原圖被刪掉時讀原圖回404` | 1 |
| `test_PATCH時embedding失敗回500且照片完全沒被改動` | 1 |
| `test_PATCH自建時embedding失敗回500且不留空資料夾` | 1 |
| `test_沒有任何刪除端點` | 1 |
| **合計** | **9** |

> 🔴 **紅燈了怎麼辦**：回去修**對應的 phase 的程式**，不要改測試。對照表：①→Phase 19／20、②③→Phase 18／20、④→Phase 16／21、⑤→Phase 19、⑥⑦→Phase 21、⑧→全部（有人偷加了刪除端點）。

### 步驟 3：兩份規格檔全綠（詢問規格必須「一個字都沒改過」）

```bash
# a) 詢問規格：5 條 Rule、7 個例子，本增量全程不得更動
pytest tests/integration/test_ask_feature.py -v | tail -3
# 預期最後一行：7 passed

# b) 詢問規格「檔案本身」零變動——用步驟 0 記下的基線 commit（a4e44ef）
git diff --stat a4e44ef -- docs/spec/features/自然語言詢問.feature
# 預期：完全沒有輸出（沒有輸出＝沒有差異）
# 更強的證明（2026-08-21 校準補充）：這個檔從專案 init commit 之後就沒有任何 commit 動過它
git log --oneline -- docs/spec/features/自然語言詢問.feature
# 預期：只有一行（64c412f init）

# c) 上傳規格（Phase 20 已依 design1.md 正式改版）
pytest tests/integration/test_upload_feature.py -v | tail -3
# 預期：10 passed（Phase 20 改版後的例子數；以實際輸出為準）

# d) 兩份一起跑，數一數總例子數
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v \
  | grep -c PASSED
```

把結果填進表（執行時填入）：

| 項目 | 實查值 |
|---|---|
| `test_ask_feature.py` | ＿＿ passed（必須恰好 **7**） |
| `自然語言詢問.feature` 與基線的差異 | ＿＿（必須是「無輸出」） |
| `test_upload_feature.py` | ＿＿ passed |
| 兩份規格合計例子數 | ＿＿ |

### 步驟 4：全量回歸，並記下最終顆數

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# a) 全量
pytest -q | tail -1

# b) 每個檔案幾個測試（把 collect 出來的測試 id 依檔名分組數一數）
pytest --collect-only -q | grep "::" | cut -d: -f1 | sort | uniq -c | sort -k2

# c) 零外部服務依賴：把 Ollama 位址指到沒有服務在聽的埠，全量仍要全綠
OLLAMA_BASE_URL=http://localhost:9 pytest -q | tail -1
```

把 (b) 的輸出整理成這張表，**這就是「記下最終顆數」的成果**（執行時填入）：

| 檔案 | 個數 |
|---|---|
| `unit/test_photo_repository_unit.py` | ＿＿ |
| `unit/test_vlm_service_unit.py` | ＿＿ |
| `unit/test_indexing_service_unit.py` | ＿＿ |
| `unit/test_storage_service_unit.py`（Phase 17） | ＿＿ |
| `integration/test_photo_repository.py` | ＿＿ |
| `integration/test_folder_repository.py`（Phase 16） | ＿＿ |
| `integration/test_photo_files.py`（Phase 19） | ＿＿ |
| `integration/test_photos_upload.py` | ＿＿ |
| `integration/test_upload_feature.py`（改版後上傳規格） | ＿＿ |
| `integration/test_upload_bilingual.py` | ＿＿ |
| `integration/test_upload_design_rules.py` | ＿＿ |
| `integration/test_assign_folder.py`（Phase 21） | ＿＿ |
| `integration/test_folders_endpoint.py`（Phase 22） | ＿＿ |
| `integration/test_retrieval.py` | ＿＿ |
| `integration/test_workflow_route.py` | ＿＿ |
| `integration/test_ask_endpoint.py` | ＿＿ |
| `integration/test_ask_feature.py`（詢問規格） | 7 |
| `integration/test_error_paths.py` | ＿＿ |
| `integration/test_folder_error_paths.py`（本 phase） | 9 |
| **合計（＝最終測試顆數）** | **＿＿** |

**這個「合計」數字要寫進三個地方**：本文件的驗收清單、`CLAUDE.md` 現況段（步驟 8）、commit 訊息（步驟 10）。

### 步驟 5：核對「明確不做」與本增量的底線

Phase 13 有一份「明確不做」檢查腳本。本增量推翻了其中兩條（現在**可以**寫檔、**可以**瀏覽），所以腳本要換成下面這份最終版。整段貼進終端機執行：

```bash
cd /Users/linjunting/personalDocAI

echo "== 端點清單（本增量後應為 9 個）=="
grep -rnE "@router\.(get|post|put|patch|delete)" app/api/routers/
grep -nE "@app\.(get|post|put|patch|delete)" app/main.py

echo "== 不得有任何刪除端點 =="
grep -rnE "@router\.delete|@app\.delete" app/ || echo "OK：沒有刪除端點"

echo "== 寫檔只准出現在 storage_service.py =="
grep -rlnE "open\(|write_bytes|shutil|aiofiles|\.save\(|unlink" app/ --include="*.py"

echo "== 不得有使用者／帳號相關欄位 =="
grep -rniE "user|account|login|token|password" app/ --include="*.py" db/schema.sql || echo "OK：沒有"

echo "== 不得有非同步佇列／處理狀態 =="
grep -rniE "celery|rq |queue|status_column|processing_state" app/ --include="*.py" || echo "OK：沒有"

echo "== metadata 仍然只能有四個欄位 =="
python -c "from app.schemas.photo import PhotoMetadata; print(sorted(PhotoMetadata.model_fields))"

echo "== 不得使用雲端模型服務 =="
grep -rniE "anthropic|openai|voyage|api_key|API_KEY" app/ --include="*.py" requirements.txt || echo "OK：全本地"

echo "== 不得引入 ORM／遷移框架（仍是手寫 SQL）=="
grep -rniE "sqlalchemy|alembic" app/ --include="*.py" requirements.txt || echo "OK：沒有"

echo "== SQL 只能出現在 repository =="
# 2026-08-21 校準：pattern 用「UPDATE photo」而非「UPDATE 」——photos.py 第 225 行
# 有一句 P21 計畫指定的中文註解「⑥ 一條 UPDATE 同時寫…」，泛用 pattern 會誤中（它不是 SQL）
grep -rlnE "SELECT |INSERT INTO|UPDATE photo|DELETE FROM|TRUNCATE" app/ --include="*.py"

echo "== 不得有全域例外捕捉（500 要不吞錯）=="
grep -rnE "exception_handler" app/ --include="*.py" || echo "OK：沒有全域捕捉"

echo "== data/ 不入版控 =="
grep -qx "data/" .gitignore && echo "OK：.gitignore 有 data/" || echo "違規：.gitignore 少了 data/"
git ls-files data/ | head -5
[ -z "$(git ls-files data/)" ] && echo "OK：data/ 沒有任何檔案被 git 追蹤" || echo "違規：有原圖進了版控"

echo "== 沒有第二個分類模型／第二個 workflow =="
grep -rnc "ChatOllama" app/services/*.py

echo "== 前端仍是零框架、零打包 =="
ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
grep -riE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/ || echo "OK：沒有外部前端函式庫"
```

**逐項預期輸出**：

| 檢查 | 預期 |
|---|---|
| 端點清單 | 共 9 行：`POST /photos`、`GET /photos/{photo_id}/thumbnail`、`GET /photos/{photo_id}/image`、`PATCH /photos/{photo_id}/folder`（以上 `photos.py`）、`POST /ask`（`ask.py`）、`GET /folders`、`GET /folders/{folder_id}`（`folders.py`）、`GET /health`、`GET /`（`main.py`） |
| 刪除端點 | `OK：沒有刪除端點` |
| 寫檔檔案清單 | 只有 `app/services/storage_service.py` 一行 |
| 使用者欄位 | `OK：沒有` |
| 佇列／狀態 | `OK：沒有` |
| metadata 欄位 | `['category', 'content_time', 'items', 'location']`（恰四個） |
| 雲端模型 | `OK：全本地` |
| ORM／遷移框架 | `OK：沒有` |
| SQL 檔案清單 | 只有 `app/repositories/photo_repository.py` 一行 |
| 全域例外捕捉 | `OK：沒有全域捕捉` |
| `data/` | 兩行都是 `OK：…` |
| `ChatOllama` 計數 | 每個 services 檔案一行（`grep -c` 連 0 的也會列出；import 那一行也算一次）：`vlm_service.py:2`（import 1＋`OllamaVLM` 建構 1）、`ask_workflow.py:3`（import 1＋route 1＋answer 1），其餘檔案皆 `:0`——**`vlm_service.py` 必須是 2**，出現 3 就代表有人加了第二個分類模型 |
| 前端相依 | 兩行 `OK：…` |

### 步驟 6：正式庫最終核對（那 2 張真實照片不可以弄丟）

```bash
psql -d PersonalDocAI
```

在 psql 裡逐句執行：

```sql
-- a) 六個預設資料夾在，且全域只有一個收件箱
SELECT id, name, is_inbox FROM folder ORDER BY id;
SELECT count(*) AS 收件箱數 FROM folder WHERE is_inbox;

-- b) 每一張照片都掛在某個資料夾底下（folder_id 是 NOT NULL，這是雙保險）
SELECT count(*) AS 沒有資料夾的照片 FROM photo WHERE folder_id IS NULL;

-- c) ★ 核心：遷移進來的舊照片（路徑欄位 NULL 的那些）必須在「收據」
SELECT p.id,
       p.category,
       f.name AS 資料夾,
       p.original_path,
       p.thumbnail_path
FROM photo p
JOIN folder f ON f.id = p.folder_id
WHERE p.original_path IS NULL
ORDER BY p.id;

-- d) category 與資料夾名稱必須一致（design1 §6 的雙寫規則）
SELECT count(*) AS 對不起來的列
FROM photo p JOIN folder f ON f.id = p.folder_id
WHERE p.category IS DISTINCT FROM f.name;
```

**預期**：

| 查詢 | 預期結果 |
|---|---|
| a | 至少 6 列：`1 未分類 t`、`2 收據 f`、`3 飲食 f`、`4 風景 f`、`5 文件 f`、`6 其他 f`（煙霧測試自建的資料夾會排在 7 之後）；收件箱數 = **1** |
| b | `0` |
| c | **恰 2 列**（`id` 1 與 2）；`category` 皆為「收據」、`資料夾` 皆為「收據」、兩個路徑欄皆為空（psql 顯示為空白） |
| d | `0` |

離開 psql：`\q`。

> ⚠️ **正式庫絕不能跑 `db/schema.sql`**——那支開頭是 `DROP TABLE`，會把這 2 張真實照片清掉。正式庫只跑 `db/migrate_folders.sql`（可重跑、不清資料）。

### 步驟 7：真模型手動煙霧測試（全程手動，不寫成 pytest、不進 CI）

**為什麼手動**：真 AI 的輸出不是決定論的，寫成自動化測試會時好時壞。這一步是「通電看看會不會冒煙」，用眼睛核對。

```bash
# 0) 前置：Ollama 在跑（本機是 App 版，不歸 brew services 管）、PostgreSQL@17 在跑
pgrep -fl "ollama serve" || open -a Ollama
brew services start postgresql@17

# 1) 啟動服務（視窗 A）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

接著在瀏覽器與視窗 B 逐項做，**每一項都寫下「看到什麼」**：

| # | 做什麼 | 看什麼（通過條件） |
|---|---|---|
| 1 | 開 <http://localhost:8000/ui/upload.html>，選一張**真的**照片（收據、食物、風景都行；`screencapture -x /tmp/real.png` 也可以）按上傳 | 等 10〜60 秒後跳出 modal；選項①的按鈕文字是「採用『某個資料夾』」，那個資料夾名稱要**跟照片內容合理相符**（收據照片→收據、食物照片→飲食）；下方顯示該資料夾的 description |
| 2 | modal 選項①「採用『…』」 | modal 關閉；頁面結果區的「類別」變成該資料夾名稱 |
| 3 | 再上傳一張，modal 用選項②的 `<select>` 改選另一個現有資料夾 → 按「歸到這個資料夾」 | modal 關閉；類別變成你選的那個 |
| 4 | 再上傳一張，modal 用選項③輸入名稱「煙霧測試」＋description「Phase 25 煙霧用」→「建立並歸類」 | modal 關閉；類別變成「煙霧測試」 |
| 5 | 再上傳一張，直接按右上「×」或 Esc 關掉 modal | 頁面顯示「已放進『未分類』，之後可到瀏覽頁再歸類」；**沒有**發出 PATCH |
| 6 | 開 <http://localhost:8000/ui/browse.html> | 看得到資料夾卡片；「煙霧測試」在裡面且張數 = 1；「未分類」張數 ≥ 1 |
| 7 | 點進任一有照片的資料夾 | 縮圖牆看得到**真的縮圖**（不是破圖）；點單張會跳出同一套三選項 modal，選項①文字是「維持『目前資料夾』」 |
| 8 | 點進「收據」資料夾 | 遷移進來的 2 張舊照片顯示**灰底占位「無縮圖」**（不是破圖、不是紅字錯誤） |
| 9 | 開 <http://localhost:8000/ui/ask.html>，問條件型問題（例如「有哪些在 Target 拍的收據？」） | 回 200；`檢索方式：metadata search`；回答是**中文** |
| 10 | 問語意型問題（例如「我最近買過什麼飲料？」） | `檢索方式：vector semantic search`；回答是中文 |
| 11 | 問一個絕對查不到的（例如「有哪些在南極拍的照片？」） | 回答是「查無相關照片」之類的句子、**不編造內容**；`依據照片 id：（沒有找到相關照片）` |
| 12 | 英文問一句（例如 `What drinks did I buy recently?`） | 回 200；回答是**英文**句子 |
| 13 | 視窗 A 的終端機 | 全程沒有 traceback（除非你刻意製造錯誤） |
| 14 | `ls -R data/` | `data/photos/` 與 `data/thumbs/` 各有跟本次上傳張數相同的檔案；縮圖檔明顯比原圖小 |

> 📌 這一步會在正式庫留下真實資料，這是預期的（Phase 14 的煙霧也是這樣）。**不要**為了清乾淨而去跑 `db/schema.sql`。

### 步驟 8：更新 `CLAUDE.md`

> 🔧 **2026-08-21 校準**：本步驟原文假設 CLAUDE.md 還停在「Phase 01〜14、79 tests」的狀態、要求一次寫入整段增量敘述。實際上 P15〜17／P18〜20／P21〜24 的成果段已在各輪收尾時逐段寫入（現況段目前是「Phase 18〜24 已完成（2026-08-21），Phase 25〜26 待做」、顆數 **140**）。因此本步驟改為**增量式收尾**，下方 a)〜c) 為改寫後的指引；原文附的整段長敘述**不再使用**（其內容已分散存在）。

**a) 現況段**（兩處）：
1. 現況 header 由「…Phase 18〜24 已完成（2026-08-21），Phase 25〜26 待做」改成「…**增量 Phase 15〜26 全數完成（2026-08-21）**」。
2. 在 P21〜24 成果段之後**追加一小段** P25〜26 成果（錯誤表逐列把關的新測試檔＋顆數、真模型煙霧、`style.css` 設計 tokens 與三頁改版——P26 完成後一併寫入，見階段 TT），並把「目前 **140** 個全綠」改成最終顆數 **149**。

原文以下這段整段長敘述**跳過不用**（保留於此僅供對照）：

```
**2026-08-20 增量（`docs/design/design1.md`：資料夾＝category、原圖瀏覽）Phase 15〜26 全數完成**：新增 `folder` 表（六筆種子，「未分類」為 `is_inbox`，`folder_one_inbox` partial unique index 保證全域只有一個收件箱），`photo` 新增 `folder_id`／`original_path`／`thumbnail_path`／`content_type`；正式庫以 `db/migrate_folders.sql`（可重跑、不清資料）一次遷移完成，2 張舊照片歸入「收據」、路徑欄維持 NULL（瀏覽顯示占位，不假裝有圖）。上傳流程改為：格式檢查 → 讀出全部資料夾 → VLM 看圖（prompt 動態注入資料夾清單，`clamp_category()` 把清單外的推薦壓成「未分類」；**仍然只有一次看圖、沒有第二個分類模型**）→ **一律以 category=「未分類」建立 Document 與 embedding** → INSERT → `app/services/storage_service.py` 存原圖與 Pillow 512px 長邊縮圖（落地位置由 `config.DATA_DIR` 決定，pytest 由 `isolated_data_dir` fixture 指到臨時目錄；寫檔失敗會刪檔＋刪列再 re-raise）→ 201 回應含 `folder`／`suggested_folder`／`folders`／`thumbnail_url`。歸類走 `PATCH /photos/{id}/folder`（`folder_id` 與 `name`＋`description` 擇一，404／404／409／422；成功時**先重算 embedding、後一條 UPDATE** 同時寫 `folder_id`＋`category`＋`embedding`，自建路徑的 `create_folder` 也排在算向量之後——所以算向量失敗時資料庫完全沒動、不留空資料夾）。新增 `GET /folders`、`GET /folders/{id}`、`GET /photos/{id}/thumbnail`、`GET /photos/{id}/image`（路徑 NULL／檔案不存在／id 不存在一律 404）——**端點共 9 個**。網頁介面三頁（`upload.html`／`browse.html`／`ask.html`）＋共用 `folder_modal.js`＋共用 `style.css`（Phase 26 美化），仍是**零框架、零打包、零自動化測試**，驗收以瀏覽器實操為準。`docs/spec/features/上傳照片.feature` 已於 Phase 20 依 design1.md **正式改版**（產品負責人核准解除唯讀）；`自然語言詢問.feature` 全程未動、5 條 Rule 全綠。錯誤路徑由 `tests/integration/test_folder_error_paths.py`（9 個測試，已被 Phase 19〜21 覆蓋的列不重寫）對著 design1.md §12 逐列把關。測試總數 **NNN** 全綠且不依賴任何外部服務。本批 phase 計畫已歸檔至 `docs/plan/finish/`（含 `phase-00-增量總覽.md`）。
```

**b) 指令段**（2026-08-21 校準：`migrate_folders.sql` 那條指令**已存在**於 CLAUDE.md，不重複加）：只補上這一條：

```bash
# 只跑本增量的錯誤路徑把關（9 個）
pytest tests/integration/test_folder_error_paths.py -v
```

並在啟動伺服器那段的註解補上三個頁面網址：

```bash
# 啟動開發伺服器（http://localhost:8000，API 文件在 /docs）
# 網頁介面：/ui/upload.html（上傳）、/ui/browse.html（瀏覽）、/ui/ask.html（問答）
uvicorn app.main:app --reload --port 8000
```

**c) 重要陷阱段**：補一條：

```
- **原圖與縮圖存在本機 `data/`，不入版控**（`.gitignore` 已加 `data/`）。正式庫的 2 張舊照片沒有原圖（`original_path` 為 NULL），瀏覽時顯示占位是**預期行為**，不是 bug。`DATA_DIR` 在 pytest 由 `isolated_data_dir` fixture 導向臨時目錄，所以跑測試永遠不會弄髒專案的 `data/`。
```

### 步驟 9：把本批計畫檔歸檔到 `docs/plan/finish/`

> 🔧 **2026-08-21 校準**：phase-15〜24 共十份已於前兩輪隨 commit 歸檔，`unfinish/` 只剩 **3 份**（`phase-00-增量總覽.md`、`phase-25`、`phase-26`）；且 `git mv` 會直接 stage、與本輪「先不 commit」的指示衝突——**本步驟與步驟 10 一併延後到使用者要求 commit 時執行**，屆時只移剩餘 3 份。

```bash
cd /Users/linjunting/personalDocAI
git mv docs/plan/unfinish/phase-00-增量總覽.md docs/plan/finish/
git mv docs/plan/unfinish/phase-25-*.md docs/plan/finish/
git mv docs/plan/unfinish/phase-26-*.md docs/plan/finish/

ls docs/plan/unfinish/    # 預期：空的
ls docs/plan/finish/      # 預期：原本 15 份 ＋ 本批 13 份 ＝ 28 份
```

> `phase-00-增量總覽.md` 與既有的 `phase-00-總覽.md` 是**不同檔名**，不會覆蓋——前者是本增量（Phase 15〜26）的地圖，後者是 Phase 01〜14 的歷史。

### 步驟 10：git commit

```bash
cd /Users/linjunting/personalDocAI
git add -A
git status            # 確認沒有 data/ 底下的圖片被加進來
git commit -m "$(cat <<'EOF'
feat: Phase 25 錯誤收尾與全量回歸——design1 §12 錯誤表逐列把關（新增 test_folder_error_paths.py，9 tests）、兩份規格全綠、正式庫遷移核對、CLAUDE.md 現況校正、本批計畫歸檔

- 新增 tests/integration/test_folder_error_paths.py：415/422 不建資料夾（不寫庫不留檔雙保險）、清單外建議→未分類、未分類被當建議允許、自建重名大小寫不敏感 409 不覆蓋、原圖被刪讀原圖 404、PATCH 時 embedding 失敗 500 且 folder_id/category/embedding 全未變、自建路徑 embedding 失敗不留空資料夾、無任何刪除端點
- §12 已被 Phase 18/19/20/21/23/24 覆蓋的列以對照表註明，不重寫（舊列/縮圖被刪/id 不存在讀圖 404 由 Phase 19 test_photo_files.py 把關；前端占位由 Phase 24 瀏覽器實操把關）
- 全量回歸 NNN passed；OLLAMA_BASE_URL 指死埠仍全綠（零外部服務依賴）
- 詢問規格 7 例全綠且 .feature 自基線零變動；改版後上傳規格全綠
- 「明確不做」最終版核對通過：端點恰 9、寫檔只在 storage_service、SQL 只在 repository、metadata 恰四欄、無刪除端點、無 ORM、data/ 未進版控
- 正式庫核對：六個預設資料夾、收件箱恰 1、2 張舊照片在「收據」且路徑 NULL、category 與 folder.name 全數一致
- 真模型中英雙語煙霧手動通過（三種歸類各一、關掉 modal、瀏覽頁縮圖與占位、ask 條件/語意/查無/英文）
- CLAUDE.md 現況段補增量敘述、指令段補 migrate_folders.sql 與三頁網址、陷阱段補 data/ 不入版控
- docs/plan/unfinish/ 13 份計畫全數歸檔至 finish/

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ShM1riRpQnG94w5eAt3BQp
EOF
)"
```

> commit 訊息裡的 `NNN` 換成步驟 4 記下的最終顆數；`Claude-Session` 換成你這次工作階段的網址。

---

## 驗收清單

- [ ] 步驟 0 的兩個基線值已填寫（開工顆數、基線 commit hash）
- [ ] Phase 23 與 Phase 24 的瀏覽器實操驗收清單先前已全勾（§12 的「關掉 modal」與「前端占位」兩列靠它們把關）
- [ ] `tests/integration/test_folder_error_paths.py` 已建立，`pytest tests/integration/test_folder_error_paths.py -v` = **9 passed**
- [ ] ASCII 對照地圖共 12 列（§12 的 7 列＋v4 的 415＋§7.2 的四種失敗〔409 與 §12「自建重名」同一列〕＋§7.3 的 embedding 失敗）每一列都有歸屬，沒有任何一列是「沒人管」
- [ ] `pytest tests/integration/test_ask_feature.py` = **7 passed**（詢問規格 5 條 Rule 全綠）
- [ ] `git diff --stat <基線hash> -- docs/spec/features/自然語言詢問.feature` **無任何輸出**
- [ ] `pytest tests/integration/test_upload_feature.py` 全綠（改版後上傳規格全數 Rule）
- [ ] 步驟 4 的每檔顆數表已填滿，**最終顆數 = ＿＿＿**（三處一致：本清單、`CLAUDE.md`、commit 訊息）
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 與正常跑的顆數**完全相同**（＝**149**，證明零 Ollama 依賴）
- [ ] 步驟 5 檢查腳本每一項都符合預期（特別是：端點恰 **9**、寫檔只在 `storage_service.py`、SQL 只在 `photo_repository.py`、metadata 恰四欄、無刪除端點、`data/` 未進版控、`vlm_service.py` 的 `ChatOllama` 恰 **2** 行——import＋建構各一，建構恰 1 處）
- [ ] 步驟 6 正式庫四個查詢全部符合預期（**2 張舊照片在「收據」、兩個路徑欄皆 NULL**、收件箱恰 1、`category` 與 `folder.name` 零不一致）
- [ ] 步驟 7 真模型煙霧 14 項全部通過，且視窗 A 沒有 traceback
- [ ] `CLAUDE.md` 三處已更新（現況段、指令段、陷阱段），最終顆數已填入
- [ ] `docs/plan/unfinish/` 已清空，13 份計畫檔在 `docs/plan/finish/`（2026-08-21 校準：**延後與 commit 一起做**——git mv 會 stage、與「先不 commit」衝突；15〜24 十份已在 finish/）
- [ ] **最後一步**：`pytest -q` 全綠 → `git add -A` → `git status` 確認沒有圖片檔被加入 → `git commit`（訊息照步驟 10；2026-08-21 校準：**延後至使用者要求 commit 時執行**）

---

## 常見問題

**Q1：`test_上傳失敗時不寫庫不留檔也不建資料夾` 紅了，`DATA_DIR` 裡真的有檔案。**
代表 Phase 19 的失敗清理沒做好。檢查 `photos.py` 上傳流程：415 與 422 這兩條路是**在寫檔之前**就 `raise HTTPException` 的，根本不該碰到 `save_original`。若真的碰到了，八成是有人把寫檔提前到 VLM 之前——改回「INSERT → 寫檔 → UPDATE 路徑」的順序（Phase 19 契約）。

**Q2：`test_PATCH時embedding失敗回500且照片完全沒被改動`（或 `…不留空資料夾`）紅了。**
代表 Phase 21 的順序寫反了：`category` 被改掉＝先 UPDATE 再算向量（或分成兩條 UPDATE）；留下空資料夾＝`create_folder` 被提前到算向量之前。正確順序照 ASCII 順序圖：先 `build_document`（目標名稱當 category）→ `embed_document` → 自建路徑這時才 `create_folder` → 最後**一條** `update_photo_folder` 同時寫三個欄位。這也是為什麼契約規定它是一條 UPDATE 而不是三條。

**Q3：`test_自建資料夾重名大小寫不同也回409且不覆蓋` 紅了——回的是 200，而且真的多了一個 `project x` 資料夾。**
代表 `find_folder_by_name` 沒有做大小寫不敏感比對（Phase 16 契約要求 `lower(name) = lower(%s)`），於是沒攔到、一路 `create_folder` 成功——資料庫的 `UNIQUE` 只擋「一字不差」的重名，大小寫不同在它眼裡是兩個名字。修 `find_folder_by_name`，不要去改資料庫的 UNIQUE——那是完全同名時的最後防線，本來就該在。

**Q4：`test_原圖被刪掉時讀原圖回404` 紅了，回 500。**
讀圖端點只檢查了「路徑是不是 NULL」，忘了檢查「檔案在不在」。Phase 19 契約寫的是三種情況都要 404：列不存在、路徑 NULL、**檔案不存在**。在 `FileResponse` 之前加一個 `if not path.exists(): raise HTTPException(404)`（兩個讀圖端點都要有——Phase 19 的測試驗過縮圖那個，這裡驗的是原圖那個）。

**Q5：全量回歸的顆數跟我預期的對不上，少了幾個。**
先跑 `pytest --collect-only -q | grep "::" | cut -d: -f1 | sort | uniq -c` 看是哪個檔案少了，再跟步驟 4 的表格比對。常見原因：Phase 20 改版時把某個舊測試刪掉卻沒記錄。**不要為了湊數字硬加測試**——把差異找出來、確認是刻意刪的就好，然後把真實數字記下來。

**Q6：正式庫的查詢 (c) 回了 3 列或 0 列，不是 2 列。**
- 回 3 列以上：步驟 7 的煙霧測試上傳失敗留下了沒路徑的列，或是有人手動插了資料。用 `SELECT id, text, uploaded_at FROM photo WHERE original_path IS NULL ORDER BY id;` 看多出來的是誰，確認不是那 2 張真的舊照片再處理。
- 回 0 列：**最可能是有人對正式庫跑了 `db/schema.sql`**（開頭 `DROP TABLE`）。那 2 張真實照片沒有備份就救不回來了。以後正式庫只跑 `migrate_folders.sql`。

**Q7：可不可以把真模型煙霧測試寫成 pytest，這樣以後就自動了？**
**不可以。** 這條界線從 Phase 8 就立下了，Phase 13 再確認過一次：真 AI 的輸出不是決定論的，寫成自動化測試會時好時壞，最後大家會學會忽略紅燈。真模型只做手動煙霧、不進驗收與 CI。

**Q8：`test_沒有任何刪除端點` 這種「掃自己原始碼」的測試不奇怪嗎？**
不奇怪，這是 Phase 13 就用過的手法（`test_程式碼裡沒有任何檔案大小上限檢查`）。有些規格說的是「不准有某個東西」，沒有辦法用行為測試證明「不存在」，掃原始碼是最直接的做法。它的價值在於：半年後有人想「順手加個刪除功能」時，會先被這個測試擋一下。

**Q9：這是最後一個 phase 嗎？**
不是。後端到此收尾，還有 **Phase 26：美化 UI/UX**——只動前端四個檔案（`upload.html`／`browse.html`／`ask.html`／`folder_modal.js`）加一支共用 `style.css`，**零自動化測試變動**，本 phase 記下的顆數在 Phase 26 完成後必須一模一樣。

---

## 完成後的專案狀態

**本增量的後端完成。** design1.md 描述的能力全部落地並被測試守著：

- 上傳：格式檢查（415）→ VLM 看圖並從現有資料夾推薦一個（看不懂 422，**不寫庫也不留檔**）→ 以「未分類」建 embedding → 存原圖與 512px 縮圖 → 201 回應帶 `folder`／`suggested_folder`／`folders`／`thumbnail_url`。
- 歸類：`PATCH /photos/{id}/folder` 採用現有或自建（404／404／409／422），成功時先重算 embedding 再一條 UPDATE 雙寫 `folder_id` 與 `category`；算向量失敗時資料庫零變動，自建路徑也不會留下空資料夾。
- 瀏覽：`GET /folders`、`GET /folders/{id}`、`GET /photos/{id}/thumbnail`、`GET /photos/{id}/image`（讀不到一律 404，前端占位）。
- 詢問：**完全沒動**，5 條 Rule 全程保綠。
- design1.md §12 錯誤表每一列都有測試指著它；全量測試 **＿＿＿ passed**、不依賴任何外部服務；正式庫的 2 張真實照片安全歸入「收據」。

下一步（也是最後一步）是 Phase 26：把三個頁面從「能用」變成「看得下去」，且不長出任何 AI 樣板臉。
