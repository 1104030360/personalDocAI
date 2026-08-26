# Phase 64：任務清單與關閉端點（端點 20 → 22）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 開兩支新端點——`GET /ingest-jobs`（現在有哪些檔案還在排隊／分析中／失敗了，
> 順便回一個「待決定有幾張」）與 `POST /ingest-jobs/{job_id}/dismiss`（把失敗的那一列關掉）。
> 這是 Phase 67 全站進度面板**唯一**的資料來源。

**為什麼要做這個：** Phase 62／63 之後，上傳與快門都只回一張號碼牌（`job_id`）。
使用者按下上傳，畫面上什麼都沒發生——照片要等 worker 做完才出現在待決定頁，
中間可能是幾十秒也可能是五分鐘。**現在完全沒有辦法知道「做到哪了」。**
本 phase 就是補上那個「問一下」的窗口：前端每 2 秒打一次 `GET /ingest-jobs`，
一次拿回「還在跑的任務清單」＋「待決定現在有幾張」，
右下角的進度面板與頂欄那個 `待決定（N）` 就都有資料可以畫了。

失敗的任務會**留在清單上**（不然使用者永遠不知道有一張照片沒進去）。
留著就要有辦法收掉，所以第二支端點是「把這一列關掉」。

---

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **輪詢（polling）** | 前端每隔一段時間主動問一次伺服器「有沒有新消息」。這裡是每 2 秒。相對的做法是伺服器主動推（WebSocket／SSE），本增量**不做**——2 秒問一次夠用，而且不必多維護一條長連線 |
| **open job（還沒結束的任務）** | 狀態是 `queued`／`analyzing`／`retrying`／`failed` 的任務。**成功的不算**——成功的任務會直接從清單被刪掉（契約備忘 §3.1：成功 ＝ `delete(job_id)`），所以前端不必自己過濾 |
| **dismiss（關掉）** | 把一列失敗的任務從清單上拿掉。**不是刪照片**（失敗的任務本來就沒有照片），也不是「再試一次」（自動 3 次已經用完了，design5 §3 明列不做手動重試） |
| **`pending_count`（待決定張數）** | 收件箱裡有幾張照片。頂欄那個「待決定（N）」的 N 就是它 |
| **收件箱（inbox）** | 名字叫「未分類」的那個資料夾，`folder` 表裡 `is_inbox = true` 的唯一一筆。所有新照片都先進這裡等人歸類 |
| **204 No Content** | HTTP 狀態碼，「做完了，而且沒有東西要回給你」。回應的 body 是空的 |
| **409 Conflict** | HTTP 狀態碼，「你要做的事跟現在的狀態衝突」。這裡是「這筆任務還在跑，不准關掉」 |
| **LEFT JOIN 計數** | SQL 手法：以資料夾為主去數照片，即使一張都沒有，那個資料夾**仍然會出現**、張數是 0（用一般 JOIN 的話空資料夾會整個消失） |

---

## 1. 對應 design5.md 章節

- **§4.3 JobStore**（清單 API 只回四種狀態；**成功＝刪掉那筆 job**；
  `GET /ingest-jobs` 同時帶 `pending_count`——**收件箱照片數，SQL，不是 Redis**；
  關掉失敗列用 `POST /ingest-jobs/{job_id}/dismiss`，**只准 dismiss `failed`**；
  staging 在失敗當下就已刪，dismiss 只是從清單拿掉）
- **§5 API 契約**（兩支新端點；端點 **20 → 22**；清點測試要改數字並繼續斷言沒有 DELETE）
- **§6.1 頂欄**（階段丙起改由全站 JS 向 `GET /ingest-jobs` 輪詢，
  **一次帶回 `jobs` 與 `pending_count`**，用來更新 N 與右下角進度面板；
  不要四個 HTML 各寫一套 `setInterval`）
- **§6.6 進度面板**（四種狀態各顯示什麼；成功不出現；`failed` 右上 × → dismiss）
- **§8 錯誤表第 9 列**（dismiss 一筆還在跑的 job → **409**）
- **§0 禁止事項第三條**（**不准**為了進度面板新增 `DELETE` 進 OpenAPI；
  Phase 37「openapi 零 DELETE」仍有效，關掉失敗列用 `POST`）
- **§3「不做」**（不做失敗列手動「再試一次」、不做 Celery Flower／獨立監控 UI）
- **D9**（成功列消失、頂欄 N +1；失敗列留下可按 × 關掉；清單空了就收起面板）
- **契約備忘 §3.4**（`IngestJobOut`／`IngestJobListOut` 的欄位，逐字照抄）
- **契約備忘 §2.1**（新檔名 `app/api/routers/ingest_jobs.py`，**不可自創別名**）
- **契約備忘 §7 第 4／5 條**（SQL 只准出現在 `photo_repository.py`；`openapi.json` 零 DELETE）

---

## 2. 前置條件

**必須先做完的 phase：**

| Phase | 提供什麼 | 本 phase 哪裡用到 |
|---|---|---|
| 57 | `app/services/ingest_job_store.py`：`JobStore` 協定（含 `get`／`delete`／`list_open`）、`IngestJob` 的欄位、`get_job_store()` 注入點、conftest 的 `wire_memory_job_store` | 兩支端點全部的資料都從這裡拿 |
| 62 | `app/schemas/ingest_job.py`（已有 `IngestAcceptedResponse`）；`POST /photos` 回 202 會真的建出 job | 本 phase 在同一個檔補另外兩個模型；測試靠 202 造出可以列出來的任務 |

（Phase 63 不是硬相依，但依總序排在前面。做完 63 之後，`source` 欄位會有
`upload` 與 `camera` 兩種值，本 phase 的測試可以順便驗到。）

**開工前先量一次基準：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps            # db 要是 Up (healthy)
pytest -q
```

把顆數抄下來當基線 **N**。本 phase 做完應該是 **N ＋ 12**（新測試檔十二顆；
`test_端點數不變` 是改數字、不是新增，所以不計）。

```bash
python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
paths = TestClient(app).get("/openapi.json").json()["paths"]
運算元 = [(p, m) for p, item in paths.items() for m in item]
print("端點數：", len(運算元))
PY
```

預期：**端點數： 20**。本 phase 之後要變成 **22**。

⚠ **絕對不要同時跑兩份 pytest**（會互相 TRUNCATE 測試庫）。

---

## 3. 範圍

### 做

- 補完 `app/schemas/ingest_job.py`：新增 `IngestJobOut`、`IngestJobListOut`
  （`IngestAcceptedResponse` 是 Phase 62 建的，不動它）。
- 新建 `app/api/routers/ingest_jobs.py`（**零 SQL**）：
  - `GET /ingest-jobs` → 200 `IngestJobListOut`
  - `POST /ingest-jobs/{job_id}/dismiss` → 204／404／409
- `app/main.py` 掛上新 router。
- 新建 `tests/integration/test_ingest_jobs_endpoint.py`（十二顆）。
- 改 `tests/integration/test_ask_three_paths.py::test_端點數不變` 的 `20` → **`22`**。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 用 `DELETE /ingest-jobs/{job_id}` | design5 §0 禁止事項第三條明文禁止。Phase 37 釘死「openapi 零 DELETE」，那條規則到現在仍然有效（`test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞` 守著）。理由是本專案從頭到尾**沒有任何刪除語意**——連照片都不能刪。dismiss 語意上也不是刪除：那筆任務早就結束了、staging 也早就清掉了，dismiss 只是「我知道了，別再顯示」，用 `POST` 表達「我做了一個動作」剛剛好 |
| 讓 dismiss 可以關掉 `queued`／`analyzing`／`retrying` | design5 §4.3 明文「只准 dismiss `failed`；進行中的不准用這個藏起來」。藏起來會讓人以為東西不見了，而它其實還在跑 |
| 做「再試一次」端點 | design5 §3「不做」明列。自動 3 次已經做完了；要重來就重新選檔／重拍 |
| 在 dismiss 時刪 staging 或刪照片 | staging 在最終失敗那一刻就已經被 worker 刪掉了（design5 §4.3 最後一句）。失敗的任務本來就沒有照片可以刪 |
| `pending_count` 從 Redis／JobStore 算 | design5 §4.3 明文「**收件箱照片數，SQL，不是 Redis**」。JobStore 裡沒有「已經入庫但還沒歸類」這種資訊，那是資料庫的事 |
| 在這支 router 裡寫 SQL | 契約備忘 §7 第 4 條：SQL 只准出現在 `app/repositories/photo_repository.py`。本 phase **一行 SQL 都不寫**，也**不新增 repository 函式**（§4.0 說明既有的就夠用） |
| 分頁、篩選、排序參數 | 單人 side project，同時排隊的檔案就那幾個。多做要動端點、動前端、動測試，收益是零 |
| 寫進度面板的 JS／HTML | 那是 **Phase 67**。本 phase 只做後端 |
| 動 `POST /photos`／鏡頭端點 | 那是 Phase 62／63，已經做完 |

---

## 4. 實作步驟（TDD）

### 4.0 先確認手上的積木（不寫程式，只讀）

- [ ] 打開 `app/services/ingest_job_store.py`（Phase 57），確認 `IngestJob` 的欄位
      與 `list_open()` 的語意：

```python
JOB_STATUSES = ("queued", "analyzing", "retrying", "failed")

class IngestJob(TypedDict, total=False):
    job_id: str
    filename: str
    content_type: str
    status: str          # JOB_STATUSES 之一
    attempt: int         # 這張／這頁目前第幾次 VLM，1〜3
    page_count: int | None
    pages_done: int
    photo_ids: list[int]
    error: str | None
    ai_backend: str      # "local" / "cloud"
    source: str          # "upload" / "camera"
```

      `list_open()` 回的就是「還沒結束的」——成功的任務已經被 `delete()` 掉了，
      所以本 phase **不必自己過濾 success**。

- [ ] **`pending_count` 從哪裡來（本 phase 唯一要想一下的問題）**：

      design5 §4.3 說它是「收件箱照片數，SQL，不是 Redis」。
      而 `photo_repository.list_folders()`（Phase 16 就寫好了）**已經回這個數字**：

```python
def list_folders() -> list[dict[str, Any]]:
    """全部資料夾，依 id 排序，每筆附上裡面有幾張照片。"""
    sql = f"""
        SELECT f.id, f.name, f.description, f.is_inbox, count(p.id) AS photo_count
        FROM folder f
        LEFT JOIN photo p ON p.folder_id = f.id
        GROUP BY f.id
        ORDER BY f.id;
    """
```

      （現況的 `sql = f"""` 真的帶著 `f` 前綴——雖然裡面沒有插值，對照時別以為抄錯；
      docstring 的第一行後面其實還有幾行解釋 LEFT JOIN 的說明文字，
      這裡只節錄第一行與 SQL。本 phase **不改**這個函式，只是讀它確認欄位名。）

      收件箱就是 `is_inbox` 為 `true` 的那一筆（全系統保證至多一個——
      `folder_one_inbox` 這個部分唯一索引擋著），所以：

```python
pending_count = next(f["photo_count"] for f in photo_repository.list_folders() if f["is_inbox"])
```

      **裁決：不新增任何 repository 函式、不寫任何新 SQL。**
      理由：① 既有函式已經算出這個數字；② 它是同一條 LEFT JOIN，
      不會因為收件箱是空的就漏掉（`count(p.id)` 不把 NULL 算進去，空資料夾正確得到 0）；
      ③ 資料夾就六筆起跳，多回幾筆完全不痛；
      ④ 少一個函式就少一份要維護的 SQL——這是 side project。

      > 如果**真的**在效能上出問題了（照片幾萬張、資料夾幾百個），那時再加一個
      > `count_inbox_photos()` 也不遲。現在加就是過度設計。

- [ ] 打開 `tests/integration/test_ask_three_paths.py` 最後一顆 `test_端點數不變`
      （約在第 423 行），確認現在寫的是 `assert len(運算元) == 20`。

### 4.1 補完 `app/schemas/ingest_job.py`

- [ ] 在 `IngestAcceptedResponse` **下面**加入兩個模型（契約備忘 §3.4，逐字照抄欄位）：

```python
class IngestJobOut(BaseModel):
    """GET /ingest-jobs 清單裡的一列（design5.md §4.3、§6.6）。

    這是「進度面板上那一列」要畫的東西，不多不少：

      queued            → 「檔名」（PDF 若已知頁數則「檔名（N 頁）」）
      analyzing/retrying→ 「檔名 第 attempt 次」（PDF 加「第 pages_done／page_count 頁」）
      failed            → 「檔名」＋ error 這句短話，右上角一個 ×

    刻意「不回」JobStore 裡另外三樣：
      photo_ids  ── 崩潰重送用的內部狀態，前端拿去也不知道要幹嘛
      ai_backend ── 使用者不需要在進度列上看到「這張是雲端跑的」
      source     ── 使用者同樣不需要看到（電腦上傳或手機拍的，檔名就看得出來了）
    留在 JobStore 裡不外送，是「回應只回畫得出來的東西」的一貫作法
    （比照 GET /folders/{id} 的瘦契約）。
    """

    job_id: str
    filename: str
    content_type: str
    status: str                    # queued / analyzing / retrying / failed
    attempt: int                   # 這張／這頁目前第幾次 VLM，1〜3
    page_count: int | None = None  # PDF 才有；還沒拆頁前是 None
    pages_done: int = 0            # PDF 已處理頁數（含跳過的）
    error: str | None = None       # 失敗時給人看的短句（**不要**把 stack 丟給瀏覽器）


class IngestJobListOut(BaseModel):
    """GET /ingest-jobs 的回應（HTTP 200）。

    一次輪詢帶回兩件事，讓前端只要打一支就能同時更新
    右下角的進度面板與頂欄的「待決定（N）」（design5.md §6.1）：

      jobs          ── 還沒結束的任務（queued／analyzing／retrying／failed）。
                       **成功的不會出現**——成功＝那筆 job 被刪掉了，
                       所以前端不必自己過濾（design5.md §4.3）。
      pending_count ── 待決定（＝收件箱）現在有幾張照片。
                       這個數字走 SQL、不走 Redis：JobStore 裡沒有
                       「已入庫但還沒歸類」這種資訊，那是資料庫的事。
    """

    jobs: list[IngestJobOut]
    pending_count: int
```

### 4.2 先寫測試（此時應該全部是紅的）

- [ ] 新建 `tests/integration/test_ingest_jobs_endpoint.py`，整份照抄：

```python
"""任務清單與關閉端點的整合測試（增量五 Phase 64）。

對應 design5.md §4.3、§5、§8 第 9 列。

兩支端點都**零 AI、零 SQL**：
  GET  /ingest-jobs                  → 還沒結束的任務 ＋ 待決定張數
  POST /ingest-jobs/{job_id}/dismiss → 把一列失敗的關掉（只准 failed）

任務怎麼造出來：走真的 POST /photos（Phase 62 之後回 202 並建一筆 job），
需要它「跑完」時就用 tests/conftest.py 的 跑完任務()（測試扮演 worker）。
本檔不直接戳 JobStore 造假任務——那樣驗不到「端點與真流程接得起來」。
"""

from __future__ import annotations

import pytest

from app.dependencies import get_embeddings, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import FakeVLM, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture(autouse=True)
def 看得懂的假VLM(wire_fake_ai):
    """預設「看得懂」；要失敗的測試自己再覆寫成看不懂的。

    顯式依賴 wire_fake_ai 保證本 fixture 排在它之後執行、測後由它統一 clear()。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)
    yield


def 收下一個檔(client, filename: str = "a.png") -> str:
    """POST 一張圖，回它的 job_id（202 當下任務是 queued、照片還不存在）。"""
    response = client.post(
        "/photos", files={"file": (filename, make_png_bytes(), "image/png")}
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


# ---------------- ① GET /ingest-jobs ----------------


def test_沒有任何任務時回空清單與零(client):
    response = client.get("/ingest-jobs")

    assert response.status_code == 200, response.text
    assert response.json() == {"jobs": [], "pending_count": 0}


def test_剛收下的檔會出現在清單裡且狀態是queued(client):
    job_id = 收下一個檔(client, "收據.png")

    body = client.get("/ingest-jobs").json()

    assert len(body["jobs"]) == 1
    列 = body["jobs"][0]
    assert 列["job_id"] == job_id
    assert 列["filename"] == "收據.png"
    assert 列["content_type"] == "image/png"
    assert 列["status"] == "queued"
    assert 列["attempt"] == 0
    assert 列["error"] is None
    # 還沒有任何照片入庫，所以待決定是 0
    assert body["pending_count"] == 0


def test_清單的每一列恰好八個鍵而且不外送內部狀態(client):
    """response_model 把關：photo_ids／ai_backend／source 是內部狀態，不外送。"""
    收下一個檔(client)

    列 = client.get("/ingest-jobs").json()["jobs"][0]

    assert set(列) == {
        "job_id", "filename", "content_type", "status",
        "attempt", "page_count", "pages_done", "error",
    }


def test_成功的任務不會出現在清單裡而待決定加一(client):
    """design5.md D9：成功 → 那一列消失、頂欄 N +1（成功＝job 被刪掉）。"""
    job_id = 收下一個檔(client)

    跑完任務(job_id)

    body = client.get("/ingest-jobs").json()
    assert body["jobs"] == [], "成功的任務不該留在清單上"
    assert body["pending_count"] == 1


def test_失敗的任務會留在清單上並帶著錯誤短句(client):
    """design5.md D9：失敗列留下，讓使用者知道有一張沒進去。"""
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )
    job_id = 收下一個檔(client, "看不懂的.png")

    跑完任務(job_id)

    body = client.get("/ingest-jobs").json()
    assert len(body["jobs"]) == 1
    列 = body["jobs"][0]
    assert 列["job_id"] == job_id
    assert 列["status"] == "failed"
    assert 列["error"], "失敗一定要有一句給人看的短話"
    # 失敗＝什麼都沒存，所以待決定仍然是 0
    assert body["pending_count"] == 0
    assert photo_repository.count_photos() == 0


def test_待決定張數跟收件箱一致(client):
    """pending_count 走 SQL（收件箱照片數），不是「跑成功幾筆任務」。

    刻意用兩條路造出照片：一條走上傳流程，一條直接寫資料庫（模擬遷移進來的舊照片）。
    如果有人把 pending_count 改成從 JobStore 數，第二張就會漏掉，這顆會紅。
    """
    跑完任務(收下一個檔(client))

    photo_repository.insert_photo(
        text="遷移進來的舊照片",
        category="未分類",
        location=None,
        items=[],
        content_time=None,
        embedding=app.dependency_overrides[get_embeddings]().embed_query("舊照片"),
    )

    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    assert 收件箱["photo_count"] == 2
    assert client.get("/ingest-jobs").json()["pending_count"] == 2


def test_已定案的照片不算進待決定(client):
    """定案＝離開收件箱，N 要減一（design5.md §12 階段甲第四條的後端那一半）。"""
    job_id = 收下一個檔(client)
    跑完任務(job_id)
    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    photo_id = photo_repository.list_photos_in_folder(收件箱["id"])[0]["id"]
    收據 = photo_repository.find_folder_by_name("收據")

    assert client.patch(
        f"/photos/{photo_id}/folder", json={"folder_id": 收據["id"]}
    ).status_code == 200

    assert client.get("/ingest-jobs").json()["pending_count"] == 0


# ---------------- ② POST /ingest-jobs/{job_id}/dismiss ----------------


def test_關掉失敗的那一列回204且清單少一列(client):
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(
        PhotoUnderstanding(understood=False)
    )
    job_id = 收下一個檔(client)
    跑完任務(job_id)
    assert len(client.get("/ingest-jobs").json()["jobs"]) == 1

    response = client.post(f"/ingest-jobs/{job_id}/dismiss")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/ingest-jobs").json()["jobs"] == []
    assert 目前的任務清單().get(job_id) is None


def test_關掉還在跑的任務回409(client):
    """design5.md §8 第 9 列：進行中的不准用 dismiss 藏起來。

    藏起來會讓人以為東西不見了，而它其實還在跑——之後照片突然冒出來更嚇人。
    """
    job_id = 收下一個檔(client)          # 還是 queued，沒跑過

    response = client.post(f"/ingest-jobs/{job_id}/dismiss")

    assert response.status_code == 409
    assert response.json()["detail"] == "這筆任務還在進行中，不能關掉"
    # 一個字都沒動：任務還在清單上
    assert len(client.get("/ingest-jobs").json()["jobs"]) == 1


def test_關掉不存在的任務回404(client):
    """順序鐵律：先查「有沒有這筆」（404），再查「狀態對不對」（409）。"""
    response = client.post("/ingest-jobs/根本沒有這個job/dismiss")

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到這筆任務"


def test_關掉成功的任務也是404(client):
    """成功＝那筆 job 已經被刪掉了，所以「找不到」是正確答案（不是 409）。"""
    job_id = 收下一個檔(client)
    跑完任務(job_id)

    assert client.post(f"/ingest-jobs/{job_id}/dismiss").status_code == 404


# ---------------- ③ 清點 ----------------


def test_兩支新端點都在openapi裡而且沒有DELETE(client):
    """design5.md §0 禁止事項第三條：關掉失敗列用 POST，不准新增 DELETE 動詞。"""
    paths = client.get("/openapi.json").json()["paths"]

    assert "get" in paths["/ingest-jobs"]
    assert "post" in paths["/ingest-jobs/{job_id}/dismiss"]
    assert "delete" not in paths["/ingest-jobs"]
    assert "delete" not in paths["/ingest-jobs/{job_id}/dismiss"]
```

- [ ] 跑一次確認**真的是紅的**：

```bash
pytest tests/integration/test_ingest_jobs_endpoint.py -v
```

  預期：**12 failed**（每個 `client.get("/ingest-jobs")` 都拿到 404，因為端點還不存在；
  `test_兩支新端點都在openapi裡而且沒有DELETE` 會炸 `KeyError: '/ingest-jobs'`）。
  這就是「紅」——紅了才證明測試有在測東西。

  ℹ️ 十二顆是把上面那份照抄的結果。**開工當下一律以 `-v` 印出的清單為準**，
  全量顆數 ＝ 基線 ＋ 12（`test_ask_three_paths.py::test_端點數不變` 是改數字、
  不是新增，所以不計）。

### 4.3 寫 router（讓它轉綠）

- [ ] 新建 `app/api/routers/ingest_jobs.py`，整份照抄：

```python
"""入庫任務的 router：GET /ingest-jobs、POST /ingest-jobs/{job_id}/dismiss。

這兩支是 Phase 67 全站進度面板**唯一**的資料來源：
前端每 2 秒打一次 GET，一次拿回「還在跑的任務」＋「待決定有幾張」，
用來更新右下角的面板與頂欄的「待決定（N）」（design5.md §6.1）。

三件事先講清楚：

1. **零 SQL。** 任務資料在 JobStore（記憶體或 Redis），待決定張數呼叫
   photo_repository.list_folders() 拿——這個檔案一行 SQL 都沒有
   （SQL 只准寫在 repository，全專案唯一例外沒有）。
2. **零 AI。** 這裡只是把已經存在的狀態讀出來，不看圖、不算向量。
3. **關掉失敗列用 POST，不是 DELETE。** design5.md §0 禁止事項第三條：
   Phase 37 釘死的「openapi 零 DELETE」到現在仍然有效。而且 dismiss 語意上
   本來就不是刪除——那筆任務早就結束了、staging 也早就清掉了，
   dismiss 只是「我知道了，別再顯示」。
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from app.dependencies import get_job_store
from app.repositories import photo_repository
from app.schemas.ingest_job import IngestJobListOut, IngestJobOut
from app.services.ingest_job_store import JobStore

router = APIRouter(tags=["ingest-jobs"])


def _job_out(job: dict) -> IngestJobOut:
    """把 JobStore 那一筆換成回應格式。

    用 .get() 取值而不是 job["…"]：IngestJob 是 total=False 的 TypedDict
    （欄位可以不存在），剛建好的任務就還沒有 error／page_count。
    少一個鍵不該讓整支清單端點 500。
    """
    return IngestJobOut(
        job_id=job["job_id"],
        filename=job["filename"],
        content_type=job["content_type"],
        status=job["status"],
        attempt=job.get("attempt", 0),
        page_count=job.get("page_count"),
        pages_done=job.get("pages_done", 0),
        error=job.get("error"),
    )


def _pending_count() -> int:
    """待決定（＝收件箱）現在有幾張照片。

    走 SQL、不走 Redis（design5.md §4.3 明文）：JobStore 裡沒有
    「已經入庫但還沒歸類」這種資訊——遷移進來的舊照片、上一次開機前就在
    收件箱的照片，都不會有對應的 job。這個數字只有資料庫知道。

    list_folders() 的 LEFT JOIN 已經把 photo_count 算好了（Phase 16），
    所以這裡不必新增任何 SQL；收件箱是 is_inbox 為 true 的唯一一筆
    （folder_one_inbox 這個部分唯一索引保證全系統至多一個）。
    """
    return next(
        folder["photo_count"]
        for folder in photo_repository.list_folders()
        if folder["is_inbox"]
    )


@router.get("/ingest-jobs", response_model=IngestJobListOut)
def list_ingest_jobs(store: JobStore = Depends(get_job_store)) -> IngestJobListOut:
    """還沒結束的任務 ＋ 待決定張數（design5.md §4.3、§6.1）。

    jobs 只會有四種狀態：queued／analyzing／retrying／failed。
    **成功的不會出現**——成功那一刻 worker 就把那筆 job 刪掉了，
    所以前端不必自己過濾 success（契約備忘 §3.1）。

    刻意不分頁、不排序參數、不篩選：單人系統，同時排隊的就那幾個檔案。
    """
    return IngestJobListOut(
        jobs=[_job_out(job) for job in store.list_open()],
        pending_count=_pending_count(),
    )


@router.post("/ingest-jobs/{job_id}/dismiss", status_code=204)
def dismiss_ingest_job(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> Response:
    """把一列**失敗**的任務從清單上關掉（design5.md §4.3、§8 第 9 列）。

    ★ 順序鐵律：**先 404（有沒有這筆）再 409（狀態對不對）**。
      反過來的話，不存在的 job_id 會拿到 409「還在進行中」——
      在講一件根本不存在的事，使用者完全看不懂。
      （這條順序與 PATCH /photos/{id}/folder「先照片後資料夾」是同一個道理。）

    只准關掉 failed：進行中的不准用這個藏起來（藏起來會讓人以為東西不見了，
    而它其實還在跑，之後照片突然冒出來更嚇人）。

    這裡**不刪 staging、也不刪照片**：
      - staging 在最終失敗那一刻就已經被 worker 刪掉了（design5.md §4.3 最後一句）
      - 失敗的任務本來就沒有照片
    dismiss 純粹是「從清單拿掉」，所以回 204（做完了，沒有東西要回給你）。
    """
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到這筆任務")
    if job["status"] != "failed":
        raise HTTPException(status_code=409, detail="這筆任務還在進行中，不能關掉")

    store.delete(job_id)
    # 直接回 Response 物件＝送出一個「沒有內容」的成功回應
    return Response(status_code=204)
```

### 4.4 掛上 `app/main.py`

- [ ] 現在的第 10 行是：

```python
from app.api.routers import ask, camera, entities, folders, photos, settings, tasks
```

  改成（多一個 `ingest_jobs`，照字母順序排）：

```python
from app.api.routers import (
    ask,
    camera,
    entities,
    folders,
    ingest_jobs,
    photos,
    settings,
    tasks,
)
```

- [ ] 在 `app.include_router(settings.router)` **後面**補一行：

```python
# 入庫任務清單（增量五 Phase 64）：全站進度面板與頂欄「待決定（N）」的唯一資料來源
# GET /ingest-jobs ＋ POST /ingest-jobs/{job_id}/dismiss（端點 20 → 22）
app.include_router(ingest_jobs.router)
```

- [ ] 第一行的 docstring 從「掛上七個 router」改成「掛上八個 router」。

- [ ] `main.py` 其他部分（`/health`、`/` 轉址、`app.mount("/ui", …)`）**完全不動**。

### 4.5 改端點清點測試（20 → 22）

- [ ] 打開 `tests/integration/test_ask_three_paths.py`，找到最後一顆 `test_端點數不變`。

**改寫前：**

```python
def test_端點數不變(client):
    """本 phase 不加不減端點：詢問三路全部塞在既有的 POST /ask 裡（D14）。

    數字 14 → 17 是 Phase 36 無線鏡頭加的三支（`POST /camera/session`、
    `POST /camera/{token}/photos`、`GET /camera/{token}/latest`，phase-36 校準 1）；
    信令用的 WebSocket 依 FastAPI 的行為不會出現在 openapi.json，所以不計入。
    17 → 19 是 2026-08-22 AI 後端開關的兩支（GET／PUT `/settings/ai-backend`，
    產品負責人指示、未走 phase 計畫；見 test_ai_backend_switch.py）。
    19 → 20 是增量四 Phase 38 的 `GET /photos/{photo_id}`（design4.md D5）。
    詢問這一路仍然一支都沒加——這顆測試守的是那件事，不是總數本身。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(path, method) for path, item in paths.items() for method in item]

    assert len(運算元) == 20
    assert [路徑 for 路徑, _ in 運算元 if 路徑.startswith("/ask")] == ["/ask"]
```

**改寫後：**

```python
def test_端點數不變(client):
    """本 phase 不加不減端點：詢問三路全部塞在既有的 POST /ask 裡（D14）。

    數字 14 → 17 是 Phase 36 無線鏡頭加的三支（`POST /camera/session`、
    `POST /camera/{token}/photos`、`GET /camera/{token}/latest`，phase-36 校準 1）；
    信令用的 WebSocket 依 FastAPI 的行為不會出現在 openapi.json，所以不計入。
    17 → 19 是 2026-08-22 AI 後端開關的兩支（GET／PUT `/settings/ai-backend`，
    產品負責人指示、未走 phase 計畫；見 test_ai_backend_switch.py）。
    19 → 20 是增量四 Phase 38 的 `GET /photos/{photo_id}`（design4.md D5）。
    20 → 22 是增量五 Phase 64 的兩支（`GET /ingest-jobs` ＋
    `POST /ingest-jobs/{job_id}/dismiss`，design5.md §5）——
    進度面板的資料來源與「關掉失敗列」；關掉刻意用 POST 不用 DELETE
    （design5.md §0 禁止事項第三條，openapi 仍然零 DELETE）。
    詢問這一路仍然一支都沒加——這顆測試守的是那件事，不是總數本身。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(path, method) for path, item in paths.items() for method in item]

    assert len(運算元) == 22
    assert [路徑 for 路徑, _ in 運算元 if 路徑.startswith("/ask")] == ["/ask"]
```

  **不要改測試名稱**：它守的是「詢問這一路沒有偷加端點」（下一行那個斷言），
  那件事仍然成立。

  ℹ️ §4.4 做完到這一步之間，`test_端點數不變` 會是紅的（端點已經 22、測試還寫 20）——
  那是預期，不是壞掉；改完數字就綠了。

### 4.6 確認「零 DELETE」那顆仍然是綠的

design5 §0 禁止事項第三條說得很直接：**不准為了進度面板新增 `DELETE` 進 OpenAPI。**
Phase 37 為此寫了兩顆守門測試，本 phase **不必新寫**，只要確認它們仍是綠的：

```bash
pytest "tests/integration/test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞" \
       "tests/integration/test_folder_error_paths.py::test_沒有任何刪除端點" -v
```

預期：**2 passed**。

**為什麼「關掉失敗列」刻意用 `POST` 而不是 `DELETE`（寫給以後會想改的人）：**

1. **規則層面**：Phase 37 把「openapi 零 DELETE」釘成了本專案的鐵律，
   design5 §0 明文說它「仍然有效」。開一個例外，那條鐵律就等於沒有了——
   下一次有人想加 `DELETE /photos/{id}` 時，就沒有東西擋得住。
2. **語意層面**：dismiss **不是刪除**。那筆任務早就結束了（失敗了），
   staging 也早在失敗那一刻就被清掉了，資料庫裡從頭到尾沒有這張照片。
   dismiss 只是「我看到了，別再顯示在面板上」——那是一個**動作**，不是刪一個資源。
   用 `POST …/dismiss` 表達動作，比 `DELETE …` 更貼近真正發生的事。
3. **實務層面**：`POST` 的路徑帶著動詞（`/dismiss`），以後要加第二種收尾動作
   （真的需要的話）也放得下；`DELETE` 只有一種。

### 4.7 跑綠

- [ ] 只跑新檔：

```bash
pytest tests/integration/test_ingest_jobs_endpoint.py -v
```

  預期：**12 passed**。

- [ ] 全量：

```bash
pytest -q
```

  預期：**N ＋ 12 passed ＋ 0 skipped**（N ＝ Phase 63 做完的顆數；
  `test_端點數不變` 是改數字不是新增，所以不計）。

- [ ] 零外部依賴實證：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

  預期：顆數完全相同。

- [ ] 端點數 22、零 DELETE：

```bash
python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
paths = TestClient(app).get("/openapi.json").json()["paths"]
運算元 = [(p, m) for p, item in paths.items() for m in item]
print("端點數：", len(運算元))
print("DELETE：", [p for p, m in 運算元 if m == "delete"])
for 路徑 in ("/ingest-jobs", "/ingest-jobs/{job_id}/dismiss"):
    print(路徑, "→", list(paths[路徑]))
PY
```

  預期：`端點數： 22`、`DELETE： []`、
  `/ingest-jobs → ['get']`、`/ingest-jobs/{job_id}/dismiss → ['post']`。

- [ ] router 零 SQL：

```bash
grep -nE "SELECT |INSERT INTO|UPDATE |TRUNCATE|psycopg|cursor\(|\.execute\(" \
  app/api/routers/ingest_jobs.py || echo "OK：router 沒有 SQL"
```

  預期：`OK：router 沒有 SQL`。
  （既有的掃碼測試 `test_design3_error_paths.py::test_SQL只出現在repository與db層`
  也會自動把新檔掃進去——確認它仍是綠的即可。）

### 4.8 手動看一眼（可選但建議，1 分鐘）

- [ ] 開發模式起服務：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

- [ ] 空清單長什麼樣：

```bash
curl -sk https://localhost:8000/ingest-jobs | python -m json.tool
```

  預期：`{"jobs": [], "pending_count": <收件箱現在有幾張>}`。

- [ ] 收下一個檔再看一次：

```bash
curl -sk -X POST https://localhost:8000/photos \
  -F "file=@/tmp/sample.png;type=image/png" | python -m json.tool
curl -sk https://localhost:8000/ingest-jobs | python -m json.tool
```

  預期：第二次會看到一列 `"status": "queued"`。
  ⚠ **它會永遠停在 queued**——Phase 62〜64 期間正式的入列器是 no-op，
  沒有人會去把它撿起來做（見 phase-62 §4.2 的紅框）。這是**預期行為**，
  Phase 65／66 接上 Celery 之後才會真的動起來。

- [ ] 試試 dismiss 一筆還在跑的：

```bash
curl -sk -o /dev/null -w "%{http_code}\n" -X POST \
  https://localhost:8000/ingest-jobs/<剛剛那個 job_id>/dismiss
curl -sk -o /dev/null -w "%{http_code}\n" -X POST \
  https://localhost:8000/ingest-jobs/根本沒有這個/dismiss
```

  預期：第一行 `409`、第二行 `404`。

---

## 5. ASCII 圖：前端每 2 秒問一次，拿到什麼、怎麼畫

```text
  瀏覽器（隨便哪一頁：上傳／待決定／瀏覽／問問題／鏡頭桌面）
  ┌────────────────────────────────────────────────────────────────┐
  │  progress_panel.js（Phase 67 才寫；全站唯一一份）              │
  │  setInterval(輪詢, PP_POLL_MS = 2000)                          │
  └───────────────────────────┬────────────────────────────────────┘
                              │  每 2 秒一次
                              │  GET /ingest-jobs
                              ▼
  ┌────────────────────────────────────────────────────────────────┐
  │  app/api/routers/ingest_jobs.py   ★本 phase 做這一格（零 SQL） │
  │                                                                │
  │   jobs          ◄── store.list_open()                          │
  │                     （JobStore：記憶體／Redis）                │
  │                     只回 queued／analyzing／retrying／failed   │
  │                     成功的早就被 delete 掉了 ← 不必自己過濾    │
  │                                                                │
  │   pending_count ◄── photo_repository.list_folders()            │
  │                     挑 is_inbox 那一筆的 photo_count           │
  │                     （SQL，不是 Redis——design5 §4.3）         │
  └───────────────────────────┬────────────────────────────────────┘
                              │  200
                              ▼
   {
     "jobs": [
       { "job_id":"3f2b…", "filename":"收據.png",  "content_type":"image/png",
         "status":"analyzing", "attempt":2, "page_count":null,
         "pages_done":0, "error":null },
       { "job_id":"9a1c…", "filename":"帳單.pdf",  "content_type":"application/pdf",
         "status":"retrying",  "attempt":3, "page_count":5,
         "pages_done":2, "error":null },
       { "job_id":"c07e…", "filename":"模糊.jpg",  "content_type":"image/jpeg",
         "status":"failed",    "attempt":3, "page_count":null,
         "pages_done":0, "error":"看不懂這張照片（已重試 3 次）" }
     ],
     "pending_count": 7
   }
                              │
             ┌────────────────┴─────────────────┐
             ▼                                  ▼
   ┌──────────────────────┐        ┌───────────────────────────────┐
   │ 頂欄（每一頁都有）   │        │ 右下角進度面板 #pp-panel      │
   │                      │        │                               │
   │ 上傳照片 ｜          │        │  收據.png     分析中 第 2 次  │
   │ 待決定（7）｜  ◄──── │        │  帳單.pdf     重試中 第 3 次  │
   │ 瀏覽資料夾 ｜        │        │               第 2／5 頁      │
   │ 問問題               │        │  模糊.jpg  失敗           [×] │
   │                      │        │    看不懂這張照片（已重試… ） │
   │ N 就是               │        └───────────────┬───────────────┘
   │ pending_count        │                        │
   └──────────────────────┘                        │ 按下 ×
                                                   ▼
                                POST /ingest-jobs/c07e…/dismiss
                                                   │
                                    ┌──────────────┴──────────────┐
                                    │  是 failed  → 204，清單少一列│
                                    │  還在跑     → 409（不准藏）  │
                                    │  查無此筆   → 404            │
                                    └─────────────────────────────┘

  三種狀態的變化，都不必前端自己維護：
    成功  → 下一次輪詢那一列就不見了，pending_count 同時 +1（D9）
    失敗  → 那一列變成 failed，pending_count 不動（什麼都沒存）
    全空  → jobs == [] → 面板自己收起來（Phase 67 做這一段）
```

---

## 6. 驗收清單

- [ ] `app/schemas/ingest_job.py` 現在有**三個**模型
      ```bash
      grep -c "^class " app/schemas/ingest_job.py
      ```
      預期：`3`（`IngestAcceptedResponse`／`IngestJobOut`／`IngestJobListOut`）
- [ ] 新檔 `app/api/routers/ingest_jobs.py` 存在，兩支端點、**零 SQL**
      ```bash
      grep -nE "SELECT |INSERT INTO|UPDATE |TRUNCATE|psycopg|cursor\(|\.execute\(" \
        app/api/routers/ingest_jobs.py || echo "OK：router 沒有 SQL"
      ```
      預期：`OK：router 沒有 SQL`
- [ ] SQL 仍然只出現在 repository 與 db 層（既有掃碼測試守著）
      ```bash
      pytest "tests/integration/test_design3_error_paths.py::test_SQL只出現在repository與db層" -v
      ```
      預期：`1 passed`
- [ ] **沒有新增任何 repository 函式**（`pending_count` 用既有的 `list_folders()`）
      ```bash
      git diff --stat -- app/repositories/photo_repository.py
      ```
      預期：**沒有任何輸出**
- [ ] `app/main.py` 有 `app.include_router(ingest_jobs.router)`
- [ ] 新測試**先紅後綠**（紅的證據要留在紀錄裡）
- [ ] `pytest tests/integration/test_ingest_jobs_endpoint.py -v` ＝ **12 passed**
- [ ] dismiss 的三種結果各有測試釘住
      ```bash
      pytest "tests/integration/test_ingest_jobs_endpoint.py::test_關掉失敗的那一列回204且清單少一列" \
             "tests/integration/test_ingest_jobs_endpoint.py::test_關掉還在跑的任務回409" \
             "tests/integration/test_ingest_jobs_endpoint.py::test_關掉不存在的任務回404" -v
      ```
      預期：`3 passed`
- [ ] **端點數 ＝ 22**，且 `test_ask_three_paths.py::test_端點數不變` 的註解補了那一句
      ```bash
      pytest "tests/integration/test_ask_three_paths.py::test_端點數不變" -v
      grep -n "20 → 22" tests/integration/test_ask_three_paths.py
      ```
- [ ] **`openapi.json` 的 DELETE 仍然是 0**
      ```bash
      pytest "tests/integration/test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞" \
             "tests/integration/test_folder_error_paths.py::test_沒有任何刪除端點" -v
      ```
      預期：`2 passed`
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ Phase 63 完成時 ＋ 12
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數完全相同
- [ ] **`docs/spec/` 一個字都沒被動到**
      ```bash
      git status --short -- docs/spec/
      ```
      預期：沒有任何輸出
- [ ] 前端一個字都沒改（進度面板是 Phase 67）
      ```bash
      git diff --stat -- app/static/
      git status --short -- app/static/
      ```
      預期：兩行都沒有輸出
- [ ] 只動到**五個檔**：改三個、新建兩個（新建的檔 `git diff` 看不到，要用 `git status` 另查）
      ```bash
      git diff --stat -- app tests    # app/schemas/ingest_job.py、app/main.py、
                                      # tests/integration/test_ask_three_paths.py
      git status --short -- app tests # 另有 ?? app/api/routers/ingest_jobs.py
                                      #      ?? tests/integration/test_ingest_jobs_endpoint.py
      ```

---

## 7. 常見陷阱

1. **`pending_count` 用「跑成功幾筆任務」算。**
   會漏掉兩種照片：① 上一次開機前就躺在收件箱、還沒歸類的；
   ② 遷移進來的舊照片（`original_path` 是 NULL 那兩張）。
   它們都沒有對應的 job，JobStore 完全不知道它們存在。
   design5 §4.3 明文「**收件箱照片數，SQL，不是 Redis**」。
   `test_待決定張數跟收件箱一致` 就是靠「一張走上傳、一張直接寫資料庫」把這件事釘死的。

2. **dismiss 的檢查順序寫反（先 409 再 404）。**
   反了的話，打一個根本不存在的 `job_id` 會拿到 409「這筆任務還在進行中」——
   在講一件不存在的事，使用者完全看不懂。
   **先查有沒有這筆（404），再查狀態對不對（409）**，
   與 `PATCH /photos/{id}/folder` 的「先照片後資料夾」是同一條規則。

3. **以為 dismiss 一筆成功的任務應該回 409 或 204。**
   是 **404**。成功那一刻 worker 就把那筆 job 刪掉了（契約備忘 §3.1：成功 ＝ `delete`），
   所以「找不到」才是正確答案。`test_關掉成功的任務也是404` 守這件事。

4. **想用 `DELETE /ingest-jobs/{job_id}`。**
   design5 §0 禁止事項第三條明文禁止，而且有兩顆既有測試守著
   （`test_openapi裡沒有任何DELETE動詞`、`test_沒有任何刪除端點`）。
   §4.6 有完整的三個理由。真的忍不住的時候：那兩顆一紅，就是在提醒你這件事。

5. **在 dismiss 裡順手刪 staging 或刪照片。**
   兩樣都不必：staging 在最終失敗那一刻就被 worker 刪掉了（design5 §4.3 最後一句），
   而失敗的任務本來就沒有照片。多寫那兩行不但沒用，還會在「檔案本來就不在」時
   多一個可能炸掉的地方。

6. **`_job_out()` 用 `job["error"]` 而不是 `job.get("error")`。**
   `IngestJob` 是 `total=False` 的 TypedDict——欄位**可以不存在**。
   剛建好的任務（`status="queued"`）就還沒有 `error`／`page_count`。
   用 `job["error"]` 會在最平常的情況下噴 `KeyError`，
   而症狀是「整支清單端點 500」，跟「某一筆任務怪怪的」看起來很不一樣，很難查。

7. **忘了改 `test_端點數不變` 的數字。**
   §4.4 掛上 router 之後，那一顆會立刻紅（端點 22、測試寫 20）。
   那是**預期**，不是壞掉。改成 22 並在 docstring 補一句
   「22 是增量五 Phase 64 的兩支」——**不要改測試名稱**，
   它守的是「詢問這一路沒有偷加端點」，那件事仍然成立。

8. **改錯地方的端點數字。**
   `tests/integration/test_camera_endpoints.py` 的 docstring 也提到 17／19，
   但那顆測試**沒有斷言總數**（只斷言三支相機端點在、WS 不在），所以**不用改**。
   全系統唯一斷言總數的是 `test_ask_three_paths.py::test_端點數不變`。

9. **手動測試時看到任務永遠停在 `queued`，以為端點壞了。**
   沒壞。Phase 62〜64 期間正式的入列器是 `NoopDispatcher`（什麼都不做），
   Celery 要 **Phase 65** 才建、worker 容器要 **Phase 66** 才起。
   所以清單會正確地顯示「有一筆 queued」，然後它就一直待在那裡。
   要看到它動起來，只能在 pytest 裡（測試自己扮演 worker 呼叫 `run_ingest_job`），
   或等 Phase 65／66。

10. **在 router 裡寫 SQL 算收件箱張數。**
    契約備忘 §7 第 4 條：SQL 只准出現在 `app/repositories/photo_repository.py`。
    既有的 `list_folders()` 已經把數字算好了，直接用；
    真的要新增函式也得寫在 repository 裡，不能寫在 router。
    掃碼測試 `test_SQL只出現在repository與db層` 會抓（它掃的是
    `psycopg`／`get_connection`／`cursor(`／`.execute(` 四個關鍵字）。

11. **順手把進度面板的 JS 也寫了。**
    那是 **Phase 67**。本 phase 做完之後，`app/static/` 底下一個字都不該變——
    驗收清單裡有 `git diff --stat -- app/static/` 這一條在確認。
    後端契約先穩定、前端才接得上，是 design5 §0 的階段順序。
