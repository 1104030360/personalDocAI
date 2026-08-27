"""入庫任務的暫存區（staging）：檔案在等 worker 看圖的這段時間放哪裡。

【這個模組解決什麼問題】
增量五把上傳改成非同步：HTTP 只做格式檢查、把檔案放好、入列，然後立刻回 202
（design5.md D7）。真正看圖是幾十秒到幾分鐘之後、由另一個行程（worker）做的。
所以那份影像位元組必須先「放在某個 app 與 worker 都看得到的地方」——就是這裡。

【為什麼放磁碟，不放 Redis／不當 Celery 參數】
design5.md §4.1 明文禁止，§1.2 也把它列在被否決的方案裡：
  * 太大：一份多頁 PDF 動輒幾十 MB，而 Redis 是把資料放在**記憶體**裡的。
  * Celery 的任務參數會被序列化成 JSON 再存進 Redis，二進位要先 base64
    （體積脹三分之一，每次取任務還要解一次碼）。
  * 磁碟本來就在那裡：原圖與縮圖本來就在 data/photos／data/thumbs，
    staging 只是同一層多一個資料夾，app 與 worker 共用同一個 bind-mount。
所以任務 payload 只帶 job_id，位元組由 worker 自己從這裡讀回來
（契約備忘 §3.3：run_ingest_job() **不吃影像位元組**，只吃 job_id）。

【與 storage_service 的分工】
  storage_service ＝ **正本**。原圖 data/photos/{photo_id}、縮圖 data/thumbs/{photo_id}，
                     檔名用資料庫的 photo.id，路徑會被寫進資料庫。
  staging_service ＝ **暫存**。data/staging/{job_id}，檔名用 job_id（照片還不存在，
                     沒有 photo.id 可用），路徑**不進資料庫**、不外送給前端。
                     成功入庫或最終失敗都會被刪掉，不留痕跡。

分層：本模組只做檔案操作，不碰資料庫、不碰 HTTP、不解讀影像內容。
      誰在什麼時候呼叫它，由 api/routers/photos.py（Phase 62）與
      services/ingest_job.py（Phase 59／60）決定。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core import config
from app.services.ingest_job_store import JobStore

# data/ 底下的子資料夾名稱。與 storage_service 的 photos／thumbs 同一層。
STAGING_SUBDIR = "staging"

# 孤兒檔的年齡門檻（小時）。design5.md §4.1 明訂 24。
# ★ 目前只有這一個定義處。日後若真的需要用 .env 覆蓋它（契約備忘 §3.6 提過
#   config.py 也可以放一份），做法是**搬過去**、這裡改讀 config.STAGING_MAX_AGE_HOURS，
#   而不是兩邊各留一份——兩份一定會漂移。
STAGING_MAX_AGE_HOURS = 24

# content_type → 副檔名（**帶點**）。三種與 config.ALLOWED_CONTENT_TYPES 一致。
# ★ 名字刻意不叫 EXTENSIONS：storage_service 已經有一個同名常數，
#   但那邊的值不帶點（"jpg"）而且沒有 PDF（PDF 在 router 就被逐頁換成 PNG 了）。
#   兩個檔案放兩個同名不同值的常數，遲早有人複製貼上出事。
STAGING_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}


def staging_dir() -> Path:
    """暫存區的實際位置：config.DATA_DIR / "staging"。

    每次呼叫都重新讀 config.DATA_DIR（不在 import 時定死），
    測試才能用 conftest 的 isolated_data_dir 把它指到暫存目錄
    ——與 storage_service.absolute_path 完全同一個理由。
    """
    return Path(config.DATA_DIR) / STAGING_SUBDIR


def staging_path(job_id: str, content_type: str) -> Path:
    """這個 job 的暫存檔該叫什麼、放哪裡：data/staging/{job_id}.jpg|.png|.pdf。

    回的是**實際路徑（Path）**，不是「data/ 開頭的相對字串」——
    因為這個值不會被寫進資料庫，只在行程內傳來傳去
    （storage_service 回相對字串是為了存進 DB，這裡沒有這個需求）。

    清單外的 content_type 早在 router 的格式檢查（415）就被擋掉了；
    真的走到這裡代表有 bug，讓 KeyError 直接炸出來，不要默默給預設值
    （與 storage_service._ext 同一個原則）。
    """
    return staging_dir() / f"{job_id}{STAGING_EXTENSIONS[content_type]}"


def save_staging(job_id: str, content_type: str, data: bytes) -> Path:
    """把上傳進來的位元組原封不動寫成暫存檔，回傳它的實際路徑。

    不轉檔、不壓縮、不驗證內容——使用者送什麼就存什麼。
    「這到底是不是一張看得懂的圖」要到 worker 送 VLM 那一步才知道
    （壞檔＝那一次失敗，算進 3 次重試，design5.md 錯誤表 3／5）。
    """
    target = staging_path(job_id, content_type)
    # parents=True ＝中間缺的上層資料夾也一併建；exist_ok=True ＝已存在就當作成功
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def read_staging(job_id: str, content_type: str) -> bytes:
    """把暫存檔讀回來。worker 每次要送 VLM 之前都會呼叫它。

    檔案不在時直接讓 FileNotFoundError 炸出來，不吞錯：
    走到這裡代表「JobStore 說有這個任務，但檔案不見了」，
    那是真的出事了（有人手動刪了 data/staging，或掃把誤刪），
    應該讓它變成一次明確的失敗，而不是安靜地當作空檔繼續跑。
    """
    return staging_path(job_id, content_type).read_bytes()


def remove_staging(job_id: str, content_type: str) -> None:
    """刪掉暫存檔；檔案本來就不在也當作成功（比照 storage_service.remove_if_exists）。

    三種情況都會呼叫它，而且都有可能「檔案已經不在了」：
      1. 成功入庫之後（design5.md §4.1）
      2. 3 次都失敗、整筆放棄之後（D10、錯誤表 3／5）
      3. 入列失敗的清理路徑——先寫 staging 再入列，Redis 掛掉時要把檔刪掉
         （錯誤表第 8 列；接線在 Phase 62）
    崩潰重送時第 1 種會再跑一次，那時檔早就沒了，不可以再爆一次錯。
    """
    staging_path(job_id, content_type).unlink(missing_ok=True)


def sweep_stale_staging(store: JobStore, *, now: datetime | None = None) -> int:
    """把孤兒暫存檔掃掉，回傳刪了幾個。app 與 worker 啟動時各跑一次（design5.md §4.1）。

    【這是後悔藥，不是正常流程】
    正常情況下 staging 檔一定會被 remove_staging() 刪掉（成功刪、最終失敗也刪）。
    但如果 worker 在半路被殺掉（機器重開、Docker 重啟、Redis 的 volume 掉了），
    那個檔就變成**沒有人記得的孤兒**：JobStore 查不到它、佇列裡也沒有它的任務，
    它會永遠躺在磁碟上。這支函式就是來收這種尾的（design5.md §13）。

    【刪除條件：兩個都成立才刪】
      ① 檔案的 mtime（最後修改時間）超過 STAGING_MAX_AGE_HOURS 小時
      ② JobStore 裡查不到同名的 job
    只滿足一個都不刪，理由：
      * 又新又沒 job → 有可能是「這一毫秒剛寫完檔、還沒來得及 store.create()」的
        正常上傳。刪了會讓使用者的檔案憑空消失。
      * 又舊又有 job → JobStore 還記得它，代表這件事還沒了結（排隊排很久、
        長 PDF 還在跑，或異常中斷後還沒收拾完）。不該由掃把插手。
        （失敗列通常不會走到這裡：3 次都失敗的當下 staging 就被刪了，D10。）

    【now 是時間的注入點（seam）】
    預設用真正的現在。測試可以把它往後撥，不必真的等 24 小時
    ——與專案既有的 get_now()／FixedClock 同一招。
    兩邊都用 .timestamp() 換算成 epoch 秒數再比，所以傳「帶時區」或
    「不帶時區」的 datetime 都算得對（見常見陷阱 4）。
    """
    directory = staging_dir()
    if not directory.is_dir():
        # 全新環境（或剛重建 data/）第一次啟動就會遇到，不是錯誤
        return 0

    moment = now if now is not None else datetime.now()
    cutoff = moment.timestamp() - STAGING_MAX_AGE_HOURS * 3600

    removed = 0
    # sorted() ＝順序固定，log 看起來才穩定（iterdir 本身不保證順序）
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue  # staging 底下不該有子資料夾；有就跳過，不遞迴刪
        if path.stat().st_mtime >= cutoff:
            continue  # 還很新
        if store.get(path.stem) is not None:
            continue  # JobStore 還記得它（path.stem ＝去掉副檔名的檔名＝job_id）
        path.unlink(missing_ok=True)
        removed += 1
    return removed
