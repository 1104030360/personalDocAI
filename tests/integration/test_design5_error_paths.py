"""增量五（design5.md）§8 錯誤表的收尾驗證（Phase 71）。

體例沿用 Phase 25／37／44 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py）：先盤點、只補 ★ 缺口。
§8 的 10 列大多已由 Phase 59〜64 各自的測試檔釘住（逐列對照表見計畫 phase-71 §4.1；
執行時要用 --collect-only 對過），本檔只補三個真缺口：

| 列 | 情況 | 誰把關 |
|---|---|---|
| 1 | 非 JPEG／PNG／PDF → 415、無 job、無 staging | Phase 62 test_415不建任務也不寫staging |
| 2 | 鏡頭 token 無效 → 404、不讀檔 | Phase 63 三顆＋既有「404 先於 415」那顆 |
| 3 | 圖片 ×3 失敗 → 刪 staging、無列、failed | Phase 59 三顆（vlm.calls==3 在內）＋63／64 端點視角 |
| 4 | PDF 某頁 ×3 → 跳過該頁、其他頁繼續 | Phase 60（每頁呼叫次數 {1:1, 2:3}） |
| 5 | PDF 0 頁成功／無法拆頁 → 同 3 | Phase 60 兩顆（含「拆不開＝0 次模型呼叫」） |
| 6 | embedding 失敗 → 算進 3 次 | Phase 59 test_轉向量三次都失敗_不留照片_job標failed |
| 7 | 寫檔失敗 → 清半成品、不留孤兒列 | Phase 59／62 炸縮圖；★ 本檔【補7】炸原圖 |
| 8 | Redis 掛了 → 500 且不留 staging | Phase 62 佇列那一半；★ 本檔【補8】JobStore 那一半 |
| 9 | dismiss 還在跑的 job → 409 | Phase 64 四顆（queued）；★ 本檔【補9】analyzing／retrying |
| 10 | 已定案再 PATCH → 409（本增量不改） | 既有 test_assign_folder.py（fixture 走真上傳流程） |

【補7】〜【補9】之後是 §3「不做」／§0「禁止」／§1.2「被否決」的掃碼【掃A】〜【掃E】。

⚠ 本檔**不連真 Redis、不啟動 Celery**（design5 D15）：
   任務本體 run_ingest_job(...) 由測試直接呼叫，job 狀態走 conftest 那顆記憶體 store。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.db.session import get_connection
from app.dependencies import get_embeddings, get_job_store, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import staging_service, storage_service
from app.services.ingest_job import run_ingest_job
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 跑完任務
from tests.fakes import FakeVLM, make_png_bytes

專案根目錄 = Path(__file__).resolve().parents[2]

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


@pytest.fixture
def job_store(wire_memory_job_store):
    """conftest 第四道安全網（Phase 57）正在用的**那一顆**記憶體 JobStore。

    ⚠ 不可以在這裡 new 一顆新的 InMemoryJobStore——那樣端點寫進去的 job
      測試這邊看不到（兩顆各記各的），所有斷言都會變成**假綠**。

    Phase 57 的 wire_memory_job_store 是 autouse 而且 `yield store`，
    所以把它寫進參數列就拿得到同一顆。（Phase 62 的 conftest 另外有一個
    `目前的任務清單()`，拿到的也是同一顆——本檔用 fixture 這條路就夠。）
    """
    return wire_memory_job_store


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應，方便驗證。

    （與 test_folder_error_paths.py／test_design3_error_paths.py 的同名 fixture 用意相同。）
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案（含 staging／photos／thumbs 三個子目錄）。

    conftest 的 isolated_data_dir 已把 config.DATA_DIR 指到本測試專屬的臨時目錄，
    所以看到的一定只有「本測試造成的」檔案。沒人寫過檔時那個目錄根本不存在，
    直接 rglob 會炸 FileNotFoundError，所以先判 exists（與前兩個收尾檔同一寫法）。
    """
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


def 入列(client, *, filename="a.png", content_type="image/png",
        payload: bytes | None = None) -> str:
    """走真的 HTTP 端點把一個檔案收下來，回傳 job_id。

    刻意不直接呼叫 staging_service／JobStore：入列這件事的順序
    （先落 staging、再建 job、再丟 Celery）本身就是錯誤表第 8 列在守的東西。
    """
    if payload is None:
        payload = make_png_bytes()
    response = client.post(
        "/photos", files={"file": (filename, payload, content_type)}
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def 跑任務(job_id: str, vlm, embeddings=None) -> None:
    """測試扮演 worker，把某一個 job 就地跑完（design5 D15：不碰真 Redis、不啟動 Celery）。

    做法是**先把假件掛上 dependency_overrides、再呼叫 conftest 的 `跑完任務()`**
    ——那個 helper 會用 `目前注入的假件()` 把 vlm／embeddings／now 撈出來交給
    `run_ingest_job`，與 Phase 62 之後全專案的寫法一致。

    ⚠ `lambda: vlm` 回的是**同一個實例**——之後要看 `vlm.calls` 之類的累計值才看得到。
      寫成 `lambda: FakeVLM(...)` 這種**每次 new 一顆新的**寫法，累計值永遠是 1（假綠）；
      Phase 59／60 那些數呼叫次數的假件（ScriptedVLM／分頁VLM）同理，都得吃同一個實例。
    """
    app.dependency_overrides[get_vlm] = lambda: vlm
    if embeddings is not None:
        app.dependency_overrides[get_embeddings] = lambda: embeddings
    跑完任務(job_id)


def _讓它爆炸(*args, **kwargs):
    raise RuntimeError("磁碟在寫入途中掛掉")


# ----【補7】錯誤表第 7 列的缺口：寫「原圖」失敗 → 清掉半成品，不留孤兒列 ----
# （炸縮圖的那一半由 Phase 59 test_寫檔失敗_不留照片也不留孤兒檔_job標failed
#   與 Phase 62 改寫的 test_寫檔失敗時檔案與資料列都不留 守著，本檔不重寫。）


def test_第7列_寫原圖失敗時不留孤兒列也不留半個檔(client, job_store, monkeypatch):
    """入庫的順序是 INSERT → 存原圖 → 產縮圖 → UPDATE 回寫路徑（Phase 19 契約）。

    檔名要用 id，所以 INSERT 一定先行——也就是說寫檔失敗時**資料庫已經有一列了**。
    現有的清理語意（remove_if_exists ×2 ＋ delete_photo）必須原封不動搬進 worker：
    失敗時那一列要刪掉，否則待決定牆上會出現一張永遠 404 的卡。

    ⚠ 這一顆刻意**不**斷言呼叫次數。design5 §8 第 6 列明寫 embedding 失敗算進 3 次，
      但第 7 列只說「清掉半成品再標失敗」，沒有說要不要重試——沒說的事不要用測試釘死，
      那會把實作者的合理選擇變成違規。這裡只驗**最終狀態**。
    """
    job_id = 入列(client)
    monkeypatch.setattr(storage_service, "save_original", _讓它爆炸)

    跑任務(job_id, FakeVLM(收據理解))

    assert photo_repository.count_photos() == 0, "寫檔失敗不可以留下孤兒列"
    assert data_dir底下的檔案() == [], "半個檔案都不可以留（含 staging）"
    assert job_store.get(job_id)["status"] == "failed"


# ----【補8】錯誤表第 8 列的缺口：JobStore 寫不進去 → 500，而且不留下暫存檔 ----
# （broker 丟不進佇列的那一半由 Phase 62 test_入列失敗時回500而且staging與任務都不留
#   守著——它覆寫的是 get_task_dispatcher()；本顆覆寫的是 get_job_store()。）


class 會爆炸的JobStore:
    """create() 一律丟例外——模擬 RedisJobStore 連不上 Redis。"""

    def create(self, **kwargs):
        raise RuntimeError("Error 111 connecting to redis:6379. Connection refused.")

    def get(self, job_id):
        return None

    def update(self, job_id, **fields):
        return None

    def delete(self, job_id) -> None:
        return None

    def list_open(self):
        return []


def test_第8列_JobStore寫不進去時回500且不留staging(不擲出例外的client):
    """寫入順序是「先落 staging、再建 job」，所以建 job 失敗時磁碟上已經有檔案了。

    design5 §8 第 8 列明文：「最好連 staging 也別留（寫入順序：先 staging 再入列的話，
    失敗路徑要刪 staging）」。沒有這一段清理，Redis 抖一下就會在磁碟留下垃圾。

    覆寫 get_job_store 之所以蓋得掉 conftest 的 wire_memory_job_store：
    dependency_overrides 是一個 dict、同一個 key 後蓋前——本測試把
    wire_memory_job_store 放進去的那一格換成會爆炸的假件，測後由
    wire_fake_ai 的統一 clear() 收乾淨。
    """
    app.dependency_overrides[get_job_store] = lambda: 會爆炸的JobStore()

    response = 不擲出例外的client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 500, "入列失敗不可以被吞掉（不能假裝 202）"
    assert data_dir底下的檔案() == [], "失敗路徑要把已經落地的 staging 刪掉"
    assert photo_repository.count_photos() == 0


# ----【補9】錯誤表第 9 列：只准關掉失敗的列 ----
#
# ⚠ 這一列 Phase 64 已經測掉大半，**本檔不重寫**：
#     test_ingest_jobs_endpoint.py::test_關掉失敗的那一列回204且清單少一列
#     ::test_關掉還在跑的任務回409（用的是 queued 狀態）
#     ::test_關掉不存在的任務回404
#     ::test_關掉成功的任務也是404
# 本段只補一個真缺口：**「還在跑」不只有 queued 一種**。
# 只檢查 status == "queued" 的實作會讓 analyzing／retrying 的任務被人關掉——
# 那正是「使用者以為檔案沒進系統、再上傳一次 → 結果兩張」的來源。


@pytest.mark.parametrize("進行中的狀態", ["queued", "analyzing", "retrying"])
def test_第9列_三種進行中狀態都不准dismiss(client, job_store, 進行中的狀態):
    """JOB_STATUSES 裡除了 failed 之外的**每一種**都要回 409、而且那筆要留在清單上。

    Phase 64 那顆只驗了 queued（剛入列、還沒跑過）；
    analyzing 與 retrying 是任務真的跑起來之後才會有的狀態，一樣不准藏。
    """
    job_store.create(
        job_id="job-x", filename="a.png", content_type="image/png",
        ai_backend="local", source="upload",
    )
    job_store.update("job-x", status=進行中的狀態)

    response = client.post("/ingest-jobs/job-x/dismiss")

    assert response.status_code == 409, (
        f"{進行中的狀態} 也算「還在跑」，不可以被 dismiss（{response.text}）"
    )
    清單 = client.get("/ingest-jobs").json()["jobs"]
    assert [job["job_id"] for job in 清單] == ["job-x"]
    assert job_store.get("job-x")["status"] == 進行中的狀態, "409 時狀態不可以被改到"


# ----【掃A】§3「不做」與 §1.2「被否決」：前端掃碼 ----
#
# ⚠ 這三項**已經有人測了，本檔不重寫**（重複的測試是負債）：
#   §1.2 第 5 列（進度面板五頁都要在）→ Phase 67 test_progress_panel_contract.py
#                                         ::test_五頁都掛了進度面板
#                                         ＋ ::test_手機取景頁刻意沒有掛面板
#   §0 第 3 條／§1.2 第 10 列（不用 DELETE）→ 同檔 ::test_關掉失敗列用POST不用DELETE
#   全站禁用原生對話框                      → 同檔 ::test_靜態檔沒有原生對話框且面板零innerHTML
# 本段只補真缺口。

前端目錄 = 專案根目錄 / "app" / "static"


def test_待決定頁沒有批次勾選也仍然用彈窗():
    """§3 第 1 列（不做批次歸類）＋ §1.2 第 7 列（不做長頁表單／左右分欄）。"""
    原始碼 = (前端目錄 / "pending.html").read_text(encoding="utf-8")

    assert 'type="checkbox"' not in 原始碼, "待決定不做一次勾多張"
    assert "全選" not in 原始碼
    assert "openFolderModal(" in 原始碼, "待決定的歸類入口仍然是彈窗（產品負責人選 A）"


def test_進度面板沒有再試一次():
    """§3 第 2 列：失敗列不做手動「再試一次」。自動 3 次已經做完；要重來就重新選檔／重拍。

    有「再試一次」按鈕的話，它背後必然要重讀 staging——但 staging 在最終失敗時
    就已經刪掉了，按下去只會得到一個查不到檔案的錯誤。

    ⚠ 關鍵字刻意收得很窄，寬一點的字**全部**會假紅（Phase 67 §7 陷阱 14 記了同一件事）：
      - 不能掃裸的 "retry"：`retrying` 是 JobStore 四個狀態之一（契約備忘 §3.1 的
        JOB_STATUSES），面板處理狀態的程式碼與註解裡**合法地**含有這五個字母。
      - 也不能掃裸的「再試」「再試一次」：面板自己的**輪詢退避**就叫「再試」——
        progress_panel.js 的退避常數註解寫著「…毫秒才再試一次」、連線失敗的
        console 訊息寫著「稍後會自己再試」。那是面板重打 GET /ingest-jobs，
        不是幫失敗的任務重跑，語意完全不同，不是本規則要禁的東西。
      真正要擋的是「給使用者按的重試」。本檔零 innerHTML（Phase 67 契約），
      按鈕文案一定走 textContent ＝ 一個**帶引號的字串字面值**；而做這顆按鈕的人
      第一步一定會取一個 retry 命名。掃這兩種就夠，而且**只**掃這兩種。
    """
    原始碼 = (前端目錄 / "progress_panel.js").read_text(encoding="utf-8")

    # 防呆錨點：確認掃的真的是進度面板（檔案被改名／搬走要紅在這裡，不是默默全過）
    assert "ppDismiss(" in 原始碼, "progress_panel.js 應該要有 ppDismiss（× 關失敗列）"

    # ① 重試按鈕的字串字面值（雙引號是全檔一致的風格，單引號一起擋以防手滑；
    #    「重試」用開引號＋詞，連 "重試中（第 N 次）" 這種帶後綴的顯示措辭一起攔）
    for 字面值 in ('"再試一次"', "'再試一次'", '"Retry"', "'Retry'", '"重試', "'重試"):
        assert 字面值 not in 原始碼, f"進度面板不做手動重試／不顯示重試措辭：{字面值}"

    # ② retry 命名的類名或函式名
    for 識別字 in ("pp-retry", "ppRetry"):
        assert 識別字 not in 原始碼, f"進度面板不做手動重試：{識別字}"


def test_QR的顯示尺寸不准改小():
    """增量四唯一一次改產品 CSS（2026-08-25 真機驗收時修的）。

    Bonjour 主機名讓網址從 93 變 118 字元、QR 從 49 格變 53 格；
    當時 max-width 是 15rem（240px），每格只剩 4.5px，**iPhone 掃不到**——
    QR 畫得出來、只是掃不進去，是典型的安靜壞掉。
    改成 20rem（320px）之後每格 6.0px，兩種網址都好掃。

    既有 test_camera_endpoints.py 那顆比對的是**整行字串**；這一顆改成**比大小**，
    所以有人把 20rem 調成 24rem（更大）不會誤紅，調成 18rem 才會紅。
    """
    樣式 = (前端目錄 / "style.css").read_text(encoding="utf-8")

    比對 = re.search(r"\.cd-qr svg \{[^}]*max-width:\s*([\d.]+)rem", 樣式)
    assert 比對, "找不到 .cd-qr svg 的 max-width（那一行是 QR 可掃性的唯一保證）"
    assert float(比對.group(1)) >= 20, (
        f"QR 顯示尺寸不可以小於 20rem（現在是 {比對.group(1)}rem）——"
        "小於這個值長網址的 QR 會掃不到"
    )


# ----【掃B】§3 第 3 列／§1.2 第 13 列：photo 表該有什麼、不該有什麼 ----

# 「處理到哪了」這種狀態一律住在 JobStore（Redis／記憶體），不進 photo 表。
# design5 §11 末句明文：「photo 表只加建議欄，不加處理狀態、不加 job_id
# （冪等靠 JobStore 的 photo_ids）」。
禁止出現在photo表的欄位 = {
    "status", "state", "processing_status", "ingest_status",
    "job_id", "ingest_job_id", "progress", "attempt", "retry_count",
}

# design5 D16：建議隨入庫落庫，待決定開窗再讀（Phase 56 加的三欄＋Phase 35 那一欄）
必須出現在photo表的欄位 = {
    "suggested_category", "suggested_entity",
    "suggested_task_title", "suggested_task_due",
}


def photo表的欄位() -> set[str]:
    """用 information_schema 問資料庫「photo 表有哪些欄位」。

    conftest 已經把 DATABASE_URL 指到測試庫，所以問的是測試庫的結構——
    而測試庫是用 db/schema.sql 重建的，與正式庫走同一份遷移對齊（design5 §11）。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'photo'
                ORDER BY column_name;
                """
            )
            return {row["column_name"] for row in cur.fetchall()}


def test_photo表沒有處理狀態欄也沒有job_id欄():
    """§3 第 3 列：處理狀態不進 photo 表。

    為什麼不能加：加了之後「這張照片存在嗎」就有兩種答案（列在不在 vs 狀態是什麼），
    待決定牆一定會在某個時間點畫出空白卡（design5 §1.2 第 8 列否決的正是那個方案）。
    """
    欄位 = photo表的欄位()

    違規 = 欄位 & 禁止出現在photo表的欄位
    assert 違規 == set(), f"處理狀態只能住在 JobStore，不可以進 photo 表：{違規}"


def test_photo表有D16的四個建議欄():
    """§1.2 第 13 列：建議不能只活在回應裡——202 之後回應根本沒有建議。"""
    欄位 = photo表的欄位()

    缺的 = 必須出現在photo表的欄位 - 欄位
    assert 缺的 == set(), f"D16 的建議欄少了：{缺的}"


# ----【掃C】§3 第 4〜7 列、§1.2 第 1／2／11／12 列：compose 與 requirements ----


def compose原始碼() -> str:
    return (專案根目錄 / "compose.yaml").read_text(encoding="utf-8")


def test_worker只開兩個子行程():
    """design5 D6／§1.2 第 11 列：產品負責人明定上限 2。

    本機看圖會把機器打掛（Phase 48 已經踩過：兩件事同時打，db container 被壓垮、
    postmaster 花 2 分鐘才殺得掉子行程）。
    """
    assert "--concurrency=2" in compose原始碼(), (
        "worker 的 concurrency 必須恰好是 2（design5 D6）"
    )
    assert "--concurrency=3" not in compose原始碼()
    assert "--concurrency=4" not in compose原始碼()


def test_compose沒有replica也沒有flower也沒有ollama():
    """三條「不做」一起掃（§3 第 4／5 列、§1.2 第 12 列）。

    - replicas：鏡頭配對 session 存在 app 的記憶體裡，兩個行程會配對失敗
    - flower：Celery 的監控 UI，side project 不需要第二個網頁介面
    - ollama：Docker 裡是 Linux VM，沒有 MLX、也吃不到這台 Mac 的 GPU
    """
    原始碼 = compose原始碼()

    for 關鍵字 in ("replicas", "flower", "ollama:", "image: ollama"):
        assert 關鍵字 not in 原始碼, f"compose.yaml 不該出現：{關鍵字}"


def test_redis沒有發佈到區網():
    """§3 第 6 列：Redis 不設密碼，發佈到 0.0.0.0 等於把佇列開放給整個 Wi-Fi。

    做法：redis 服務底下**要嘛沒有 ports**（只走 compose 內部網路，最安全），
    要嘛每一條 ports 都帶 127.0.0.1: 前綴。
    """
    原始碼 = compose原始碼()
    redis區塊 = re.search(r"\n  redis:\n(.*?)(?=\n  \w|\nvolumes:)", 原始碼, re.S)
    assert redis區塊, "compose.yaml 裡找不到 redis 服務"

    for 一行 in redis區塊.group(1).splitlines():
        if re.match(r'\s*-\s*"?\d', 一行):        # 形如   - "6379:6379"
            assert "127.0.0.1:" in 一行, (
                f"Redis 只能綁本機，不可以發佈到區網：{一行.strip()}"
            )


def test_沒有背景任務框架的替代品也沒有雲端儲存():
    """§1.2 第 1／2 列＋§3 第 7 列。"""
    app目錄原始碼 = "".join(
        檔案.read_text(encoding="utf-8")
        for 檔案 in sorted((專案根目錄 / "app").rglob("*.py"))
    )
    需求 = (專案根目錄 / "requirements.txt").read_text(encoding="utf-8").lower()

    # §1.2 第 1 列：不用 FastAPI BackgroundTasks（與 uvicorn 同行程，restart 會丟工作）
    assert "BackgroundTasks" not in app目錄原始碼
    assert "background_tasks" not in app目錄原始碼
    # §1.2 第 2 列：用的是 Celery，不是自寫的 Redis list 消費迴圈
    assert "celery" in 需求
    assert (專案根目錄 / "app" / "celery_app.py").exists()
    # §3 第 7 列：不做雲端物件儲存
    for 關鍵字 in ("boto3", "s3fs", "minio", "google-cloud-storage"):
        assert 關鍵字 not in 需求, f"不做雲端物件儲存：{關鍵字}"
    # §3 第 5 列：不裝 Flower
    assert "flower" not in 需求


# ----【掃D】§0 第 2 條／§1.2 第 3／9 列：任務只帶 job_id ----


def 註記文字(參數: inspect.Parameter) -> str:
    """把型別註記統一成字串。

    模組如果有 `from __future__ import annotations`，註記本來就是字串；
    沒有的話是真的型別物件——兩種都要處理得了。
    """
    註記 = 參數.annotation
    if isinstance(註記, str):
        return 註記
    return getattr(註記, "__name__", str(註記))


def test_任務本體只吃job_id不吃影像位元組():
    """design5 §0 禁止第 2 條：影像位元組不准塞進 Redis。

    多頁 PDF 動輒好幾 MB，塞進 Redis 會讓佇列變成檔案伺服器（而且 AOF 會跟著爆）。
    圖走磁碟（data/staging），任務只帶一個 job_id。
    """
    參數 = inspect.signature(run_ingest_job).parameters

    assert list(參數)[0] == "job_id", "第一個參數必須是 job_id"
    assert 註記文字(參數["job_id"]) == "str"
    帶位元組的 = [
        名稱 for 名稱, 參數值 in 參數.items() if "bytes" in 註記文字(參數值)
    ]
    assert 帶位元組的 == [], f"任務不可以吃影像位元組：{帶位元組的}"


def test_Celery任務也只吃job_id():
    """Celery 那一層是薄薄的 wrapper（design5 D15），參數要跟任務本體一致。"""
    celery原始碼 = (專案根目錄 / "app" / "celery_app.py").read_text(encoding="utf-8")

    assert re.search(r"def ingest_task\(\s*job_id:\s*str\s*\)", celery原始碼), (
        "ingest_task 的簽章必須恰好是 (job_id: str)"
    )
    for 關鍵字 in ("bytes", "base64", "image_data", "payload"):
        assert 關鍵字 not in celery原始碼, f"Celery 任務不可以碰位元組：{關鍵字}"


def test_PDF不是每頁一個任務():
    """§1.2 第 3 列：一個 Celery 任務 ＝ 一個檔案（D11）。

    做法上就是「任務本體裡不准再丟任務」——所以 ingest_job.py 不該出現 .delay(。
    每頁一個任務的話，同一份檔會被兩個 worker 拆開跑，進度列也畫不出來。
    """
    任務原始碼 = (
        專案根目錄 / "app" / "services" / "ingest_job.py"
    ).read_text(encoding="utf-8")

    assert ".delay(" not in 任務原始碼
    assert ".apply_async(" not in 任務原始碼


def test_SQL掃碼真的有看到增量五的新檔():
    """既有那顆 test_SQL只出現在repository與db層 是 rglob("*.py")，新檔自動納入。

    這一顆不是重測 SQL，是**證明那顆掃碼掃得到新檔**——
    擋的是「有人為了讓 worker 方便，把新檔加進豁免名單」。
    """
    from tests.integration.test_design3_error_paths import 可以碰資料庫的檔案

    for 新檔 in (
        "app/services/ingest_job.py",
        "app/services/ingest_job_store.py",
        "app/services/staging_service.py",
        "app/celery_app.py",
        "app/api/routers/ingest_jobs.py",
    ):
        assert (專案根目錄 / 新檔).exists(), f"增量五應該有這個檔：{新檔}"
        assert 新檔 not in 可以碰資料庫的檔案, (
            f"{新檔} 不可以被加進「可以寫 SQL」的豁免名單"
        )


# ----【掃E-1】§5：端點恰 22、零 DELETE，而且是**這 22 支** ----

# 逐支列名，不只是數總數。總數對但少一支多一支的情況，只數總數是抓不到的。
# （2026-08-26 校準：下面這 22 支已與 Phase 64 之後的實際 /openapi.json 逐支比對過，
#   一支不多、一支不少；總數的把關另有 test_ask_three_paths.py::test_端點數不變
#   與 test_nav_header.py::test_端點數仍為22 兩顆既有測試。）
增量五之後的端點 = {
    ("/", "get"),
    ("/health", "get"),
    ("/photos", "post"),
    ("/photos/{photo_id}", "get"),
    ("/photos/{photo_id}/image", "get"),
    ("/photos/{photo_id}/thumbnail", "get"),
    ("/photos/{photo_id}/folder", "patch"),
    ("/photos/{photo_id}/entities", "post"),
    ("/photos/{photo_id}/entity-suggestion", "post"),
    ("/photos/{photo_id}/task", "post"),
    ("/folders", "get"),
    ("/folders/{folder_id}", "get"),
    ("/entities", "get"),
    ("/tasks", "get"),
    ("/ask", "post"),
    ("/settings/ai-backend", "get"),
    ("/settings/ai-backend", "put"),
    ("/camera/session", "post"),
    ("/camera/{token}/photos", "post"),
    ("/camera/{token}/latest", "get"),
    ("/ingest-jobs", "get"),                      # ★ Phase 64 新增
    ("/ingest-jobs/{job_id}/dismiss", "post"),    # ★ Phase 64 新增
}


def test_端點恰好是這22支(client):
    """§5：20 → 22。信令用的 WebSocket 依 FastAPI 的行為不進 openapi，所以不計入。

    既有 test_ask_three_paths.py::test_端點數不變 守的是**總數**；
    這一顆守的是**清單**——擋「刪了一支又加了一支，總數剛好還是 22」。
    """
    paths = client.get("/openapi.json").json()["paths"]
    實際 = {(路徑, 動詞) for 路徑, item in paths.items() for 動詞 in item}

    assert 實際 == 增量五之後的端點, (
        f"多出來：{sorted(實際 - 增量五之後的端點)}；"
        f"少掉了：{sorted(增量五之後的端點 - 實際)}"
    )
    assert len(實際) == 22


# 「dismiss 那一支是 POST 不是 DELETE」由 Phase 67 的
# test_progress_panel_contract.py::test_關掉失敗列用POST不用DELETE 守著；
# 「openapi 完全沒有 DELETE 動詞」由 Phase 37 的
# test_design3_error_paths.py::test_openapi裡沒有任何DELETE動詞 守著。本檔不重寫。


# ----【掃E-2】§0 禁止第 4 條／§1.2 第 8 列：處理中的檔不准以空白卡出現在待決定 ----


def test_入列當下待決定牆完全沒有動靜(client, job_store):
    """202 只代表「檔案收下了」，不代表「照片存在了」（design5 D7、§4.2）。

    待決定牆查的是收件箱，而收件箱裡只有 INSERT 過的列——
    只要沒有人偷偷先 INSERT 一列空白的，牆上就不可能出現空白卡。
    """
    收件箱 = photo_repository.find_folder_by_name("未分類")

    job_id = 入列(client)

    assert photo_repository.count_photos() == 0
    detail = client.get(f"/folders/{收件箱['id']}").json()
    assert detail["photos"] == [], "分析還沒成功，待決定牆上不該有任何卡片"
    assert client.get("/ingest-jobs").json()["pending_count"] == 0
    # 但是暫存檔要在、job 要是 queued——不然 worker 等一下沒東西可做
    assert staging_service.staging_path(job_id, "image/png").exists()
    assert job_store.get(job_id)["status"] == "queued"
