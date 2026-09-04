"""EC2（與階段丁的這台 Mac）上跑的雲端看圖工人：收 jobs 訊息 → 看圖 → 寫 result.json。

【它在整條路上的位置】
本機（這台 Mac）把「明確不敏感」的照片放進 S3 寄物櫃、在 jobs 佇列丟一張紙條，
然後就到 results 佇列上等答案。真正動手看圖的是**這支程式**——
階段丁（Phase 88）它跑在這台 Mac 上，階段戊（Phase 92）之後跑在一台 t4g.small 的
EC2 上，兩邊是同一份程式碼、同一個映像。

【它只做六件事】（總覽 §2.6）
  1. result.json 已經在 S3 了 → 這是重送：補送一則 results、刪掉 jobs 訊息就走（D17）
  2. s3_key 認不得（空的、或副檔名不是三種之一）→ 刪掉訊息就走（留著只會一直重來）
  3. input 檔不在了 → 本機已經 fallback 並清乾淨：刪掉訊息就走，**什麼都不寫**
  4. 讀 context.json（資料夾／實體／糾錯三份清單；缺檔就三份都當空的）
  5. 看圖：單圖最多 config.VLM_MAX_ATTEMPTS 次；PDF 逐頁、每頁各自最多這麼多次
  6. PutObject result.json → SendMessage results → DeleteMessage jobs（**順序不可對調**）

【它絕對不做的事】（design6 D11、D13）
  ⛔ 不寫 Postgres、不碰 photo_repository、不 import 資料庫驅動程式
  ⛔ 不算 embedding——向量一律由本機的 bge-m3 算（必須與庫裡既有的向量同源）
  ⛔ 不碰 Celery、不碰 Redis、不碰 data/staging（EC2 上根本沒有那個目錄）
  ⛔ 不開任何連接埠（EC2 的 security group inbound 是空的，它只有出站的 HTTPS）
  ⛔ 不重跑 Privacy Gate——閘門只在本機、只在檔案出機房**之前**跑一次（D2）
  這幾條有一顆掃碼測試 test_工人不import資料庫與Celery與Redis 在守。

【看圖用哪一顆：WORKER_VLM_BACKEND】（2026-09-03 產品負責人改判，design6 D12 作廢）
原本寫死 Ollama Cloud（D12 假設「EC2 沒有 GPU、也不裝本機 Ollama」）。
現在 EC2 改用 GPU 機器、自己裝 Ollama，所以看圖後端變成一個設定：
  cloud ＝ ollama.com（OLLAMA_API_KEY／OLLAMA_CLOUD_VLM_MODEL）。這台 Mac 上手動煙霧的預設
  local ＝ **工人所在那台機器**上的 Ollama（OLLAMA_BASE_URL／VLM_MODEL）。GPU EC2 用這個
「local」講的是工人自己那一台，不是使用者的 Mac，也**不是**頁首那顆本機／雲端開關
（那顆管的是本機那條路，而且是 web 行程記憶體裡的狀態，這個行程根本讀不到）。
選哪一個是 main() 的事，build_worker_vlm() 負責挑；process_job_message() 只收一個
VLMClient 參數——所以單元測試塞得進假件，一顆真的模型呼叫都不會發生。
"""

from __future__ import annotations

import json
import logging
import signal
import time
from typing import TYPE_CHECKING, Callable

from app.core import config
from app.services import ai_timing, pdf_service, vlm_service

if TYPE_CHECKING:
    # 只給型別檢查與讀程式的人看，**執行時不會真的 import**。
    # 這樣「import app.workers.cloud_worker」不會把 AWS SDK 一起拉進來，
    # 單元測試（假信箱）因此完全不必碰那個套件。
    # ★ CloudMailbox（Phase 77，總覽 §2.4.1）一份 Protocol 涵蓋本機端＋工人端的全部操作：
    #   工人用到的 receive_job()／delete_job_message() 就在裡面（註記「工人端（87）」），
    #   AwsMailbox 與 FakeMailbox 兩個實作也都有，所以不必另立一個工人專用的 Protocol。
    # ⚠ MailboxMessage 也跟 cloud_ingest 要（它就**定義在那裡**，Phase 77）。
    #   aws_mailbox.py 是 import 它來用的，繞道那邊拿雖然也拿得到，
    #   但會讓「這個名字到底住在哪」變得不明確——一律回到定義的地方拿。
    from app.services.cloud_ingest import CloudMailbox, MailboxMessage

# ⚠ 名字要用**字面字串**，不可以用 __name__（2026-09-03 fix round 1，真機上踩到）：
#   用 `python -m app.workers.cloud_worker` 跑時，這個模組的 __name__ 是 "__main__"，
#   於是 logger 會叫 "__main__" ——**不在** _configure_logging() 掛 handler 的「app」樹底下，
#   啟動行、「result.json 已放好」、「收到停止訊號」這些 INFO 全會被 Python 的
#   lastResort（只印 WARNING 以上）吞掉，工人看起來像整個沒在動（log 檔 0 bytes）。
#   寫死 "app.workers.cloud_worker" 就不管是被 import 還是被 -m 執行都掛在 app 樹下。
logger = logging.getLogger("app.workers.cloud_worker")

# 副檔名 → content_type。本機端 submit 時用 mailbox.input_key() 決定副檔名
# （總覽 §2.4.3 的鍵名契約），這裡是那條規則的**反向**：工人只拿得到一個 s3_key，
# 必須自己還原出「這是 JPEG、PNG 還是 PDF」，才知道要不要先拆頁。
# ★ 這是 staging_service.STAGING_EXTENSIONS 的反向表，但**刻意不 import 它**：
#   那個模組是本機端的暫存區，會去讀 config.DATA_DIR——而 EC2 上根本沒有 data/。
CONTENT_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".pdf": config.PDF_CONTENT_TYPE,
}

# result.json 放進 S3 時標的 Content-Type。純粹是禮貌（S3 不會因此拒收），
# 但 AWS Console 上點開來會直接顯示成 JSON 而不是下載，除錯時省事。
RESULT_CONTENT_TYPE = "application/json"

# PDF 的每一頁渲染出來都是 PNG（pdf_service.render_pages 回的就是 PNG 位元組）。
# ★ ingest_job.py 也有一個同名常數、同一個值。**不可以** import 它——
#   那個模組會拉進 photo_repository ＝ 資料庫層，違反 D11。
#   兩行字的重複換一個「工人與資料庫零關係」的硬保證，很划算。
PDF_PAGE_CONTENT_TYPE = "image/png"

# 向 jobs 佇列要訊息時，「沒有的話你先幫我等最多幾秒」。
# 20 是 AWS 的上限（長輪詢）。改小＝空手而回的次數變多＝ReceiveMessage 的請求數變多，
# 而 SQS 是按請求數計費的；改成 0 就是短輪詢，等於全速空轉打 API。
LONG_POLL_SECONDS = 20

# receive 本身失敗（憑證過期、網路斷、SQS 暫時性錯誤）時，先睡幾秒再試。
# 沒有它的話迴圈會變成「全速空轉打一個一定會失敗的 API」——CPU 100%、帳單也不好看。
RECEIVE_ERROR_BACKOFF_SECONDS = 5


class _NotUnderstood(Exception):
    """「這一次看不懂」。只在本模組內部從 with 區塊丟到迴圈外。

    為什麼要一個例外而不是 if：ai_timing 的結束行要標 ok=false，是靠
    「with 區塊裡有沒有例外」決定的（design4.md §5.2）。在 with 裡面 raise，
    log 才會誠實地說這一次失敗——寫法與 ingest_job.py 的同名類別一致。
    """


def content_type_from_key(s3_key: str) -> str | None:
    """從 S3 鍵名的副檔名推出 content_type；推不出來回 None。

    純函式（不碰網路、不碰檔案），所以單元測試直接餵字串就驗得完。
    推不出來時**不要亂猜**：把一份 .txt 當成 JPEG 送去看圖，錯誤會在很後面
    才以「AI 看不懂」的樣子出現，比當場承認「這個鍵名我不認得」難查十倍。
    """
    lowered = s3_key.lower()
    for suffix, content_type in CONTENT_TYPE_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return content_type
    return None


def _only_list(value: object) -> list[dict]:
    """context.json 的三個鍵**只認 list**，其他型別一律當空清單。

    為什麼不能只寫 `list(value or [])`（2026-09-03 收尾時補的）：
      {"folders": 5}      -> list(5)        TypeError（例外往外丟 → 訊息沒被刪 → 毒訊息）
      {"folders": "abc"}  -> ["a","b","c"]  **安靜地**變成三個假資料夾
      {"folders": {"a":1}} -> ["a"]         同上
    三種都不是「壞檔」（json.loads 過得了關、payload 也真的是 dict），
    所以上面兩道 except／isinstance 都攔不到它們。
    """
    return list(value) if isinstance(value, list) else []


def read_context(mailbox: CloudMailbox, job_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    """把 context.json 讀回三份清單：資料夾、實體、最近的人工糾錯。

    這三份清單住在**本機的資料庫**裡，工人沒有資料庫可讀（D11），
    所以本機在送出時把它們一起寫進 documents/{job_id}/context.json
    （總覽 §10 追認項 a）。有了它，工人組出來的 prompt 與本機自己看圖時**逐字相同**。

    缺檔或內容壞掉 → 三份都當空清單，**不是失敗**：
    少了資料夾清單只是少了「建議收進哪個資料夾」，照片內容照樣看得懂。
    """
    raw = mailbox.get_object(mailbox.context_key(job_id))
    if raw is None:
        logger.info("job %s：沒有 context.json，三份清單都當空的", job_id)
        return [], [], []
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("job %s：context.json 解不開，三份清單都當空的", job_id, exc_info=True)
        return [], [], []
    if not isinstance(payload, dict):
        # `[]`／`null`／`"x"` 都是**合法的 JSON**，所以上面那個 except 接不到它們，
        # 但它們沒有 .get()——不擋的話下一行會丟 AttributeError，一路衝出
        # process_job_message、jobs 訊息不會被刪，然後每 900 秒回來炸一次，
        # 變成一則永遠出不去的毒訊息。docstring 說的是「內容壞掉 → 三份都當空清單」。
        logger.warning(
            "job %s：context.json 不是一個物件（%s），三份清單都當空的",
            job_id,
            type(payload).__name__,
        )
        return [], [], []
    dropped = [
        key
        for key in ("folders", "entities", "corrections")
        if payload.get(key) is not None and not isinstance(payload.get(key), list)
    ]
    if dropped:
        # 與上面兩條壞檔路徑同一個規矩：**降級可以，安靜不行**。
        # 少了資料夾清單會以「AI 最近都建議未分類」的樣子出現，沒有人會聯想到 context.json。
        logger.warning("job %s：context.json 的 %s 不是清單，當空的", job_id, dropped)
    return (
        _only_list(payload.get("folders")),
        _only_list(payload.get("entities")),
        _only_list(payload.get("corrections")),
    )


def _understand_with_retries(
    vlm: vlm_service.VLMClient,
    image_bytes: bytes,
    content_type: str,
    *,
    job_id: str,
    label: str,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
) -> tuple[vlm_service.PhotoUnderstanding | None, int]:
    """看一張圖，最多 config.VLM_MAX_ATTEMPTS 次。回 (結果或 None, 實際看了幾次)。

    規則與本機的 ingest_job._understand_and_embed **刻意一致**（沿用 design5 D10）：
    看不懂（understood=False 或 text 全是空白）與呼叫失敗（雲端 401、逾時、
    JSON 解析不過）都各算一次。差別只有一個——**這裡沒有轉向量那一段**，
    因為向量一律本機算（design6 D13）。

    label 只是給 log 看的人話（"單圖" 或 "第 2 頁"），不影響任何行為。
    """
    for attempt in range(1, config.VLM_MAX_ATTEMPTS + 1):
        try:
            # ★ 計時 log 由**工人自己包**（總覽 §2.6 第 5 條「ai_timing kind=vlm backend=cloud」）。
            #   2026-09-02 實查：OllamaCloudVLM.understand() 內部**沒有** log_ai，
            #   它只有「失敗再試一次」那一層；全站唯一包 vlm 計時的地方是
            #   ingest_job.py L403，本函式與它逐字相同。
            # target 從 vlm 物件身上拿：正式的 OllamaCloudVLM 建構時就把
            # backend=cloud 與模型名記在 timing_target 上，所以工人的 log 會誠實地
            # 印 kind=vlm backend=cloud。不帶 target 的話 ai_timing 會退回讀
            # 這個行程的 config.AI_BACKEND——那永遠是預設的 "local"，log 會騙人。
            with ai_timing.log_ai("vlm", target=vlm_service.vlm_timing_target(vlm)) as timing:
                understanding = vlm.understand(
                    image_bytes, content_type, folders, entities, corrections
                )
                if not understanding.understood or not understanding.text.strip():
                    timing.note = f"understood=false text_chars={len(understanding.text)}"
                    raise _NotUnderstood()
                timing.note = (
                    f"understood=true text_chars={len(understanding.text)} "
                    f"item_count={len(understanding.items)}"
                )
        except _NotUnderstood:
            # ⚠ 這一條一定要寫在 except Exception 前面：Python 由上往下比對，
            #    順序反了的話每次「看不懂」都會印出一整段沒有意義的 traceback
            logger.warning("job %s %s：第 %d 次看圖，AI 說看不懂", job_id, label, attempt)
            continue
        except Exception:
            # 雲端 401（key 錯）、404（雲端沒這個模型）、逾時、JSON 驗證不過……全算一次。
            # exc_info=True 讓 traceback 進 log；它不會進 result.json
            logger.warning("job %s %s：第 %d 次看圖呼叫失敗", job_id, label, attempt, exc_info=True)
            continue
        return understanding, attempt
    return None, config.VLM_MAX_ATTEMPTS


def build_image_result(
    job_id: str, understanding: vlm_service.PhotoUnderstanding | None, attempts: int
) -> dict:
    """組出單圖的 result.json 內容（總覽 §2.4.3 的形狀，恰六個鍵）。

    understanding 是 None ＝ 三次都失敗。本機收到之後會把整筆標 failed、清掉 S3
    ——**不會**再用本機看一次（總覽 §10 追認項 g）。
    """
    return {
        "job_id": job_id,
        "worker_version": config.WORKER_VERSION,
        "kind": "image",
        "understood": understanding is not None,
        "attempts": attempts,
        # model_dump() ＝ Pydantic 把九個欄位倒成一個普通 dict。
        # 九個欄位全是 str／bool／list[str]／None，所以 json.dumps 一定序列化得了。
        "understanding": understanding.model_dump() if understanding is not None else None,
    }


def build_pdf_result(job_id: str, pages: list[dict]) -> dict:
    """組出 PDF 的 result.json 內容（總覽 §2.4.3 的形狀，恰四個鍵）。

    pages 是空清單 ＝ 這份 PDF 根本拆不開。本機收到之後依既有規則把整筆標成
    「這份 PDF 讀不開或沒有內容」（ingest_job.ERROR_PDF_UNREADABLE）。
    """
    return {
        "job_id": job_id,
        "worker_version": config.WORKER_VERSION,
        "kind": "pdf",
        "pages": pages,
    }


def _process_pdf(
    job_id: str,
    pdf_bytes: bytes,
    vlm: vlm_service.VLMClient,
    *,
    folders: list[dict],
    entities: list[dict],
    corrections: list[dict],
) -> dict:
    """把一份 PDF 逐頁看完，組出 pages 清單。

    ★ 重試單位是「一頁」，不是整份檔（沿用 design5 D12）：某一頁三次都失敗就記
      understood=false，**繼續下一頁**，不讓它拖垮已經看懂的其他頁。

    ★ 拆不開（壞檔、加密、零頁）→ pages 是空清單，**不丟例外**：
      工人照樣把 result.json 寫出去、照樣刪掉 jobs 訊息。不寫的話那則訊息會在
      可見度逾時之後回來，然後永遠重複同一個失敗。

    ★ 這裡拆出來的每頁 PNG **不寫回 S3**（總覽 §10 追認項 F）：本機要存檔時
      自己再 render_pages() 一次就好。存回去會讓 S3 物件數隨頁數暴增，
      而拆頁是純 CPU、幾百毫秒的事。
    """
    try:
        page_images = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        logger.warning("job %s：PDF 拆不開，pages 回空清單", job_id, exc_info=True)
        return build_pdf_result(job_id, [])

    pages: list[dict] = []
    for page_number, page_bytes in enumerate(page_images, start=1):
        understanding, attempts = _understand_with_retries(
            vlm,
            page_bytes,
            PDF_PAGE_CONTENT_TYPE,
            job_id=job_id,
            label=f"第 {page_number} 頁",
            folders=folders,
            entities=entities,
            corrections=corrections,
        )
        pages.append(
            {
                "page": page_number,
                "understood": understanding is not None,
                "attempts": attempts,
                "understanding": (
                    understanding.model_dump() if understanding is not None else None
                ),
            }
        )
    logger.info(
        "job %s：PDF %d 頁看完，%d 頁看得懂",
        job_id,
        len(pages),
        sum(1 for page in pages if page["understood"]),
    )
    return build_pdf_result(job_id, pages)


def process_job_message(
    mailbox: CloudMailbox, message: MailboxMessage, vlm: vlm_service.VLMClient
) -> None:
    """處理一則 jobs 訊息。六條規則見模組 docstring 與總覽 §2.6。

    ★ 這個函式**會**把例外往外丟（例如 S3 突然不通）。這是刻意的：
      Phase 88 的主迴圈接住它、記 log、繼續跑下一則；沒被刪掉的那則 jobs 訊息
      會在可見度逾時（900 秒）之後重新出現，自然重來一次。
      這正是 SQS「至少送一次」的正確用法——自己在這裡吞掉例外反而會讓
      「訊息被刪了但事情沒做」變成可能。
    """
    job_id = message.job_id
    result_key = mailbox.result_key(job_id)

    # ① 冪等（D17）：result.json 已經在了 ＝ 上一輪其實做完了，只是 results 訊息
    #    或刪訊息那一步沒完成。重看一次圖只是多花錢，而且會蓋掉本機可能正在讀的檔案。
    if mailbox.get_object(result_key) is not None:
        logger.info("job %s：result.json 已存在，判定為重送，補送 results 就好", job_id)
        mailbox.send_result(job_id)
        mailbox.delete_job_message(message.receipt_handle)
        return

    # ② s3_key 認不得（欄位是空的、或副檔名不在三種之內）＝這則訊息永遠處理不了。
    #    留著它只會每 900 秒回來一次，所以刪掉並留 log。
    content_type = content_type_from_key(message.s3_key) if message.s3_key else None
    if content_type is None:
        logger.warning("job %s：s3_key 認不出格式（%s），刪掉這則訊息", job_id, message.s3_key)
        mailbox.delete_job_message(message.receipt_handle)
        return

    # ③ input 不在了 ＝ 本機已經逾時 fallback、自己看完圖入庫、並把 S3 清乾淨了
    #    （總覽 §2.5）。這時候**什麼都不可以寫**：多一份 result.json，
    #    下一次重送就會以為「有結果可用」而去把本機叫醒。
    image_bytes = mailbox.get_object(message.s3_key)
    if image_bytes is None:
        logger.info("job %s：input 檔已經不在，本機應該已經 fallback，只刪訊息", job_id)
        mailbox.delete_job_message(message.receipt_handle)
        return

    # ④ 三份清單（缺檔就都當空的）
    folders, entities, corrections = read_context(mailbox, job_id)

    # ⑤ 看圖。PDF 要先拆頁，每一頁各自最多三次
    if content_type == config.PDF_CONTENT_TYPE:
        result = _process_pdf(
            job_id,
            image_bytes,
            vlm,
            folders=folders,
            entities=entities,
            corrections=corrections,
        )
    else:
        understanding, attempts = _understand_with_retries(
            vlm,
            image_bytes,
            content_type,
            job_id=job_id,
            label="單圖",
            folders=folders,
            entities=entities,
            corrections=corrections,
        )
        result = build_image_result(job_id, understanding, attempts)

    # ⑥ 順序鐵律（design6 D9）：result 先落地，才准發 results 訊息，最後才刪 jobs 訊息。
    #    反過來的話，本機會被叫醒去拿一個還沒寫完（或根本不存在）的檔案——
    #    那是最難查的一種壞法：安靜地拿到半截 JSON。
    body = json.dumps(result, ensure_ascii=False).encode("utf-8")
    mailbox.put_object(result_key, body, RESULT_CONTENT_TYPE)
    mailbox.send_result(job_id)
    mailbox.delete_job_message(message.receipt_handle)
    logger.info(
        "job %s：result.json 已放好、results 已送出（worker_version=%s）",
        job_id,
        config.WORKER_VERSION,
    )


def build_worker_vlm() -> vlm_service.VLMClient:
    """依 config.WORKER_VLM_BACKEND 挑一顆看圖客戶端給工人用。

    2026-09-03 產品負責人改判，design6 D12（「EC2 看圖一律 Ollama Cloud、實例無 GPU」）作廢：
      cloud ＝ ollama.com（OllamaCloudVLM，讀 OLLAMA_API_KEY／OLLAMA_CLOUD_VLM_MODEL）
      local ＝ **工人所在那台機器**上的 Ollama（OllamaVLM，自己去讀 VLM_MODEL／OLLAMA_BASE_URL）

    ⚠ 「local」不是「使用者的 Mac」，是**工人自己那一台**：在 GPU EC2 上跑時，
      OLLAMA_BASE_URL 指的是那台 EC2 自己的 127.0.0.1:11434
      （systemd unit 的 docker run 加 --network host 就是為了讓容器打得到它）。
    ⚠ 這裡**不看** config.AI_BACKEND：那顆頁首開關管的是本機那條路（design6 D6），
      而且它是 web 行程記憶體裡的狀態，工人這個行程讀不到也不該讀。
    ⚠ 值在**呼叫當下**才讀（不是 import 當下），所以測試 monkeypatch config 換得掉。

    打錯字**當場炸**，不預設退回任何一種：悄悄退回 cloud 的話，GPU EC2 會一直打
    ollama.com——帳單在漲、GPU 閒著，而 log 只會誠實地印 vlm=cloud，
    沒有任何東西看起來壞掉，所以沒有人會去看。
    """
    value = config.WORKER_VLM_BACKEND
    if value == "cloud":
        return vlm_service.OllamaCloudVLM()
    if value == "local":
        return vlm_service.OllamaVLM()
    raise ValueError(f"WORKER_VLM_BACKEND 只認 cloud／local，讀到的是：{value!r}")


def _configure_logging() -> None:
    """讓 app.* 的 INFO log 出現在終端機（寫法與 app/main.py L26〜33 完全一樣）。

    工人是**獨立行程**：沒有 uvicorn、也沒有 Celery 幫忙配置 logging。
    什麼都不做的話，Python 的最後防線只會印 WARNING 以上——
    啟動行、每張圖的 kind=vlm 計時、「result 已放好」全都是 INFO，一行都看不到。
    在 EC2 上這尤其致命：那台機器 inbound 全關，你只能靠 docker logs 看它在幹嘛。

    ★ logger 名稱是 "app"（不是 __name__）：本模組的 logger 叫
      app.workers.cloud_worker，掛在 "app" 上就一起收得到，
      連 vlm_service 與 ai_timing 的 log 也一起有——與 app/main.py 同一個道理。
    """
    worker_logger = logging.getLogger("app")
    if not worker_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        worker_logger.addHandler(handler)
        worker_logger.setLevel(logging.INFO)


def _install_stop_signal() -> Callable[[], bool]:
    """把 SIGTERM 與 SIGINT 接起來，回傳一個「該停了嗎」的函式。

    SIGTERM ＝ docker stop／systemctl stop 送的「請你收工」；
    SIGINT  ＝ 你在終端機按 Ctrl+C。
    兩個都**不直接殺行程**，只把旗標豎起來——手上這一則會做完
    （result.json 寫完、results 送出、jobs 訊息刪掉）才退出，不留半成品。

    ★ 訊號處理函式裡只做「豎旗標 ＋ 印一行」這種最短的事：
      它可能在程式的任何一行中間被叫起來，在裡面做正事（例如寫 S3）
      會踩到各種難以重現的競態。

    ⚠ 迴圈可能正卡在最多 20 秒的長輪詢裡，所以按下去之後**最多要等 20 秒**才真的退出。
      等不及就**再按一次**：第二次收到同一種訊號就把處理器還原成系統預設、再把訊號補發
      給自己，行程立刻結束（SIGINT 的退出碼是 130、SIGTERM 是 143）。
      代價是手上那一則可能沒刪，不過它 900 秒後會自己回到佇列，不會不見。
    """
    state = {"stopping": False}

    def _handle_signal(signum, frame) -> None:
        if state["stopping"]:
            # 第二次：使用者等不及了。先還原成系統預設的處理方式（＝直接結束行程），
            # 再把同一個訊號補發給自己——這一行之後就不會再回來了。
            logger.warning("再收到一次停止訊號，直接中斷")
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)
            return
        state["stopping"] = True
        logger.info("cloud_worker 收到停止訊號 signal=%s，做完手上這一則就退出", signum)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    return lambda: state["stopping"]


def run_forever(
    mailbox: CloudMailbox,
    vlm: vlm_service.VLMClient,
    *,
    should_stop: Callable[[], bool],
) -> None:
    """主迴圈：一直向 jobs 佇列要訊息，收到就處理，直到 should_stop() 說停。

    should_stop 是**注入進來的**（正式執行是訊號旗標，測試是「跑 N 輪就停」），
    所以整組迴圈測試是毫秒等級，不必真的送訊號、也不必等 20 秒。

    兩種例外都不會讓迴圈死掉：
      * 要訊息時失敗（憑證過期、網路斷）→ 記 log、睡 RECEIVE_ERROR_BACKOFF_SECONDS 秒再試
      * 處理某一則時失敗 → 記 log，**不刪那則訊息**，它會在可見度逾時（900 秒）之後
        自己回到佇列重做。這正是 SQS「至少送一次」的用法：不確定有沒有做完，就讓它重來，
        而重來會撞到 process_job_message 的冪等檢查（result.json 已存在）。
    """
    # vlm=／model= 從**這顆 vlm 物件**身上拿（正式的兩個實作建構時就把 backend 與模型名
    # 記在 timing_target 上）。同一個映像在 Mac 上跑是 cloud、在 GPU EC2 上跑是 local，
    # 兩邊的帳單、延遲、失敗長相完全不同——設定填錯時這一行是唯一的線索。
    target = vlm_service.vlm_timing_target(vlm)
    logger.info(
        "cloud_worker 啟動 version=%s region=%s bucket=%s vlm=%s model=%s",
        config.WORKER_VERSION,
        config.AWS_REGION,
        config.S3_BUCKET,
        target.backend,
        target.model,
    )
    while not should_stop():
        try:
            message = mailbox.receive_job(LONG_POLL_SECONDS)
        except Exception:
            logger.exception("向 jobs 佇列要訊息失敗，%d 秒後再試", RECEIVE_ERROR_BACKOFF_SECONDS)
            if should_stop():
                # ⚠ 睡之前要先問一次（2026-09-03 fix round 1）：Ctrl+C 很常正好落在
                #   「AWS 不通、正在退避」的這一段，而 PEP 475 之後 time.sleep 收到訊號
                #   會**續睡**——不先問的話使用者要多等整個退避時間才看得到行程結束。
                break
            time.sleep(RECEIVE_ERROR_BACKOFF_SECONDS)
            continue
        if message is None:
            # 佇列空著是常態（一天可能只上傳幾張），不是錯誤
            continue
        try:
            process_job_message(mailbox, message, vlm)
        except Exception:
            logger.exception(
                "處理這一則失敗，訊息先不刪，等可見度逾時之後會重來：job_id=%s",
                message.job_id,
            )
    logger.info("cloud_worker 已停止 version=%s", config.WORKER_VERSION)


def main() -> None:
    """`python -m app.workers.cloud_worker` 的進入點。

    只做四件事：設定 log → 檢查設定 → 組零件 → 進主迴圈。
    所有規則都在 process_job_message 裡，這裡刻意寫得很薄——
    與 app/celery_app.py 的 ingest_task 同一個精神（design5 D15）。

    ★ AwsMailbox 的 import 寫在函式**裡面**：這樣「import app.workers.cloud_worker」
      不會把 AWS SDK 一起拉進來，單元測試完全不必碰那個套件。
      理由與 dependencies.get_task_dispatcher() 相同。

    ★ AwsMailbox.__init__ 的參數**全部是關鍵字**（實檔簽章第一個位置就是 `*`），
      所以下面一定要寫 bucket=／jobs_queue_url=／results_queue_url=／region=，
      照順序丟位置參數會 TypeError。

    ★ 看圖用哪一顆由 WORKER_VLM_BACKEND 決定（2026-09-03 改判，design6 D12 作廢），
      挑的邏輯在 build_worker_vlm()。**不看** config.AI_BACKEND——那顆頁首開關管的是
      本機那條路（D6），而且它是 web 行程記憶體裡的狀態，這個行程根本讀不到。
      ⚠ 這裡**不**經過 app.dependencies：那個模組檔頭就 import ingest_job_store（→ redis），
        工人不准把 redis 拉進來（D11）。直接跟 vlm_service 要即可。

    ★ 「缺了什麼算缺設定」跟著後端走，四個都在啟動時檢查：
        cloud → OLLAMA_API_KEY（不然每張圖 401）＋ OLLAMA_CLOUD_VLM_MODEL
        local → OLLAMA_BASE_URL ＋ VLM_MODEL
      ⚠ 「config 有預設值所以不會缺」是**錯的**：worker.env 是用 docker run --env-file
        餵進來的，範本裡那些 `NAME=`（空值）會**蓋掉** config 的預設，變成空字串。
        而空的模型名或空的 base_url 不會讓任何東西當場壞掉——客戶端建得起來、
        也連得上，只是每一張圖都失敗三次然後標成「看不懂」，log 上像「AI 變笨了」。
      反過來說 local 模式**不該**因為少一把用不到的 key 就不肯啟動——
      那等於逼 GPU EC2 為了開機而多放一份沒有用途的機密。
    """
    _configure_logging()

    backend = config.WORKER_VLM_BACKEND
    required = [
        ("S3_BUCKET", config.S3_BUCKET),
        ("SQS_JOBS_QUEUE_URL", config.SQS_JOBS_QUEUE_URL),
        ("SQS_RESULTS_QUEUE_URL", config.SQS_RESULTS_QUEUE_URL),
    ]
    if backend == "cloud":
        required.append(("OLLAMA_API_KEY", config.OLLAMA_API_KEY))
        # 模型名同理（VLM_MODEL 那個坑的雲端版）：config 那一行是
        # os.getenv("OLLAMA_CLOUD_VLM_MODEL", VLM_MODEL)，key 在、值是空的時候拿到 ""，
        # **不會**退回 VLM_MODEL——空模型名照樣建得出客戶端、照樣連得上，只是每張圖都失敗。
        required.append(("OLLAMA_CLOUD_VLM_MODEL", config.OLLAMA_CLOUD_VLM_MODEL))
    elif backend == "local":
        # VLM_MODEL 不能漏：ChatOllama(model="") 建得起來、也連得上 Ollama，
        # 只是每一張圖都失敗——看三次、標成「看不懂」，log 上像「AI 突然變笨了」。
        required.append(("OLLAMA_BASE_URL", config.OLLAMA_BASE_URL))
        required.append(("VLM_MODEL", config.VLM_MODEL))
    else:
        # 打錯字也走「早點、大聲地壞掉」這條路（build_worker_vlm 也會擋，
        # 但那要等到組零件那一步，訊息還會夾在一堆 traceback 裡）。
        logger.error(
            "cloud_worker 無法啟動：WORKER_VLM_BACKEND 只認 cloud／local，讀到的是：%r",
            backend,
        )
        raise SystemExit(1)

    missing = [name for name, value in required if not value]
    if missing:
        # 早點、大聲地壞掉。少了佇列 URL 的話 boto3 會丟一句看不懂的 ParamValidationError；
        # 少了 OLLAMA_API_KEY 更慘——每張圖都 401、看三次、然後標成「看不懂」，
        # 從 log 上看起來像「AI 變笨了」。
        # ★ 訊息走 logger（不是 SystemExit 的字串，2026-09-03 fix round 1）：
        #   這樣它會經過 _configure_logging() 掛的 handler，與其他每一行 log 同一個格式；
        #   同時也是「handler 真的接得到這個模組」的證據（有一顆子行程測試在守）。
        logger.error("cloud_worker 無法啟動：.env 少了這些設定 %s", "、".join(missing))
        raise SystemExit(1)

    from app.services.aws_mailbox import AwsMailbox

    mailbox = AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )
    run_forever(mailbox, build_worker_vlm(), should_stop=_install_stop_signal())


if __name__ == "__main__":
    # `python -m app.workers.cloud_worker` 會執行到這裡。
    # ⚠ 一定要用 -m（模組路徑），不要 `python app/workers/cloud_worker.py`：
    #   後者會把 app/workers/ 當成 sys.path[0]，`from app.core import config`
    #   立刻 ModuleNotFoundError。
    main()
