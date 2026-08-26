# Phase 61：建議落庫接線（D16——實體與待辦的建議跟著照片一起存下來）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 特別是：**不要**新增端點（本 phase 之後仍然是 **20** 個，Phase 64 才變 22）、
> 不要讓 worker 自動釘實體或建待辦、不要為建議做「歷史紀錄」或「信心分數」，
> 也**不要動 `app/api/routers/photos.py`、`camera.py`、
> `app/repositories/photo_repository.py` 一個字**（最後那個是 Phase 56 的地盤——
> `list_photos_in_folder` 的 SELECT 在那裡就已經改成八欄了，本 phase 只**核對**，見步驟 5-1）。

> 🎯 **一句話目標：** 讓入庫任務在 `INSERT` 那一刻，除了既有的 `suggested_category`，
> 再把**實體建議**（clamp 後的名稱，清單外＝NULL）與**待辦建議**（標題／到期日，可空）
> 一起寫進 `photo` 那一列；並把 `GET /folders/{folder_id}` 的照片摘要從**五鍵擴成八鍵**，
> 讓待決定頁之後（Phase 70）讀得到它們。

**為什麼要做這個：這是「待辦功能會不會整個消失」的分水嶺**

現在（增量四）的流程是這樣的：

```text
使用者上傳 → 伺服器同步看圖 → 201 回應裡塞了三樣建議：
                                  suggested_folder（資料夾）
                                  suggested_entity（實體）
                                  suggested_task （待辦標題＋到期日）
              → 前端拿著這個回應，馬上開三關彈窗：抽屜 → 實體 → 待辦
```

建議**只活在那一次 HTTP 回應裡**，沒有存進資料庫（design3 §2.1 的已知限制）。
以前這樣沒問題，因為彈窗就在上傳當下開，回應還在手上。

但增量五把上傳改成 **202**（Phase 62）：

```text
使用者上傳 → 202 {"job_id": "...", "filename": "...", "content_type": "..."} ← 沒有建議
              → 前端關掉，去做別的事
              → 幾分鐘後 worker 才看完圖 ← **這時候沒有人在等回應了**
              → 使用者晚一點才到待決定頁點那張照片
```

到那個時候，回應早就消失了。如果建議沒有落庫，待決定頁只剩下：

| 彈窗 | 沒有落庫會變成什麼 |
|---|---|
| 抽屜（資料夾） | 還好——`suggested_category` 從 Phase 35 就已經落庫了，選項①畫得出來 |
| 實體 | 選項①（採用建議）消失，只剩②改選現有／③自創／④不釘，外加「再建議一個」（會再打一次模型） |
| **待辦** | **完全沒有入口。** 待辦窗的開窗條件是「有待辦建議才開」；沒有建議 ⇒ 永遠不開 ⇒ **待辦功能從此死掉** |

這就是 design5 D16 與 §1.2 最後一列講的事：
「建議繼續只活在 201 回應、不落庫」被**明確否決**，理由是「上傳改 202 後回應裡沒有建議；待辦窗會從此沒有入口」。

所以本 phase 要做的事只有一句話：**worker 看完圖之後，把當時猜的三件事一起寫進那一列照片。**

**⚠️ 但建議永遠只是建議。** worker **不准**自己去寫 `entity`／`photo_entity`／`task` 這三張表。
「AI 猜這張照片跟你的 MacBook 有關」和「你確認這張照片跟你的 MacBook 有關」是兩件完全不同的事——
前者存在 `photo.suggested_entity`（一個字串），後者才會在 `photo_entity` 產生一列連結。
這條規則從 design3 D3 一路守到現在（design5 §4.2 再次重申），本 phase 不動它。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **落庫** | 「寫進資料庫」的口語說法。相對於「只出現在回應裡、關掉就沒了」 |
| **clamp（夾）** | 把 AI 給的名字「夾」回現有清單裡：對得到就用清單上的原文，對不到就當作沒建議。`clamp_category` 對不到會退回「未分類」，`clamp_entity` 對不到就是 `None`（實體沒有保底選項） |
| **摘要（summary）** | `GET /folders/{id}` 回的每張照片只給幾個欄位，不是整列。目前是五鍵，本 phase 變八鍵 |
| **衍生欄位** | 從別的地方算得出來、不必另存的東西。本 phase **沒有**新增衍生欄位——三個新欄都是 AI 當下的輸出，事後算不回來，所以必須存 |

---

## 1. 對應 design5.md 章節

| 章節／編號 | 內容 |
|---|---|
| **D16** | 建議隨入庫落庫：worker 成功 INSERT 時，除既有 `suggested_category` 外，一併寫入**實體建議**與**待辦建議**（標題／到期日，可空）。仍只是建議：人按確認才寫 `entity`／`photo_entity`／`task` |
| **§1.1** | 推翻「Phase 30：實體／待辦建議只出現在上傳回應」→ 建議寫進 `photo` 列，待決定開窗再讀 |
| **§1.1** | 推翻「design3 §2.1：建議不持久化」→ 建議改落庫 |
| **§1.2 被否決** | 「建議繼續只活在 201 回應、不落庫」——理由就是待辦窗會沒有入口 |
| **§4.2** | 「入庫成功後……另外寫入 D16 的建議欄（資料夾／實體／待辦）。歸類、釘選、建待辦仍靠之後人按的 API，**不在 worker 裡自動做**」 |
| **§6.2** | 待決定頁「建議從 D16 的欄位讀（`GET /folders/{inbox}` 照片摘要比照 `suggested_category` 帶出實體／待辦建議，不必再看一次圖）；沒有待辦建議就不開第三窗」 |
| **§11** | `photo` 表只加建議欄，不加處理狀態、不加 job_id |
| **契約備忘 §4** | 三個新欄的名稱與型別；摘要五鍵 → 八鍵 |

Phase 70 才會真的把這三欄畫進待決定的彈窗鏈；本 phase 只負責**把資料備好、把 API 開出來**。

---

## 2. 前置條件

- **Phase 56 已完成**：`db/migrate_design5.sql` 已把三欄加進 `photo` 表、`db/schema.sql` 已對齊、
  `photo_repository.insert_photo()` 已經**收得下**這三個參數（Phase 56 傳的值都是 None）、
  `PHOTO_COLUMNS` 已含這三欄。
- **Phase 59 已完成**：`app/services/ingest_job.py` 的 `_run_image_job` ／ `_insert_photo_with_files` 已存在。
- **Phase 60 已完成**：`_run_pdf_job` 已存在（PDF 的每一頁共用同一個 `_insert_photo_with_files`，
  所以本 phase 改一次、兩條路都生效）。

開工前**實際跑一次**確認基線與前置：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps                      # db 必須是 Up (healthy)
pytest -q                              # 把顆數抄下來（＝ Phase 60 結束時的數字）
```

確認 Phase 56 真的做完了（**三個都要通過，缺一個就先回去補，不要在本 phase 自己補**）：

```bash
# ① 測試庫的 photo 表有三個新欄
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -c "\d photo" | grep suggested
```
預期看到四行：`suggested_category`、`suggested_entity`、`suggested_task_title`、`suggested_task_due`
（型別依序是 `text`、`text`、`text`、`date`）。

```bash
# ② insert_photo 收得下三個新參數
python -c "
import inspect
from app.repositories import photo_repository as r
p = inspect.signature(r.insert_photo).parameters
for name in ('suggested_entity','suggested_task_title','suggested_task_due'):
    print(name, '→', '有' if name in p else '★ 缺，先回 Phase 56')
"
```
預期三行都是「有」。

```bash
# ③ 正式庫也遷移過了（Phase 56 的事，這裡只是確認）
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -c "\d photo" | grep suggested_task_due
```
預期看到一行。

> ⚠️ **絕對不要同時跑兩份 pytest**（會互相 TRUNCATE 測試庫）。

---

## 3. 範圍

### 做

1. `app/services/ingest_job.py`
   - `_insert_photo_with_files()` 多收一個 `entities` 參數，並在 INSERT 時多帶三個欄位：
     `suggested_entity`（clamp 後的**名稱字串**）／`suggested_task_title`／`suggested_task_due`。
   - `_run_image_job()` 與 `_run_pdf_job()` 的呼叫端各加一個 `entities=entities`。
2. `app/repositories/photo_repository.py`——**只核對，不改**
   - **核對** Phase 56（步驟 5-4）已把 `list_photos_in_folder()` 的 SELECT 從五欄改成八欄
     （+`suggested_entity`／`suggested_task_title`／`suggested_task_due`）；本 phase **不改這個函式**。
     repository 層——那個 SELECT 加上 `test_folder_repository.py` 的鍵集合斷言——**歸 Phase 56 所有**。
   - 為什麼要留這一步而不是整項刪掉：跳著做、或忘記把 Phase 56 步驟 5-4 做完的人，
     會在這裡（與步驟 5-1 的核對指令）**當場發現**——八鍵的 API 得從八欄的 SELECT 讀出來，
     SELECT 還停在五欄的話，router 取 `row["suggested_entity"]` 會 `KeyError` 炸 500，
     本 phase 的紅燈永遠轉不綠。
3. `app/schemas/folder.py`
   - `PhotoSummary` 從五個欄位變八個。
4. `app/api/routers/folders.py`
   - 組 `PhotoSummary` 時多帶三個欄位（仍然零 SQL）。
5. 測試
   - `tests/integration/test_ingest_job.py` 追加 7 顆。
   - `tests/integration/test_folders_endpoint.py` 追加 2 顆、修改 1 顆的鍵集合斷言。
   -（`tests/integration/test_folder_repository.py` **不動**——那顆鍵集合斷言
     Phase 56 步驟 1-2 已改成八鍵並在當時轉綠，跟 SELECT 一樣歸 Phase 56 所有。）

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| **worker 自動寫 `entity` 表** | design5 §4.2、design3 D3：人按確認才落庫。AI 猜的東西直接變成真實體，使用者的實體清單會被垃圾灌爆，而且**沒有刪除功能**可以收拾 |
| **worker 自動寫 `photo_entity`（釘選）** | 一樣是「人按確認才落庫」（design5 §4.2、design3 D3）。釘選＝人宣告的關聯，是詢問「實體路」的唯一依據（design3 §6）。AI 猜錯釘上去，之後問「跟我 MacBook 有關的」會撈到不相干的照片 |
| **worker 自動寫 `task` 表** | 一樣是「人按確認才落庫」。待辦是「要去做的事」，自動建會變成一份沒人承認的待辦清單。而且待辦沒有刪除端點 |
| **改 `app/repositories/photo_repository.py`（含 `list_photos_in_folder`）** | repository 層歸 **Phase 56**：SELECT 八欄與 `test_folder_repository.py` 的八鍵斷言都在那裡改好、commit 掉了。本 phase 只在步驟 5-1 **核對**；核對不過＝Phase 56 沒做完，回 Phase 56 補，不在這裡改 |
| 新增端點 | 本 phase 只擴充**既有**的 `GET /folders/{id}` 回應欄位。端點數維持 **20**（Phase 64 才變 22） |
| 改 `PhotoDetailOut`（`GET /photos/{id}`） | design4 §4.4 明訂那顆窗是唯讀說明，**刻意不回** `suggested_category`。三個新建議欄同理，不加 |
| 改 `UploadResponse` | 那是 `POST /photos` 的 201 回應：Phase 62 起 `POST /photos` 改回 202 就不再用它（同時刪掉 `_ingest_pdf` 那一組），但它本身要等 **Phase 63** 把鏡頭端點也改完才刪（`camera.py` 用到那時）。現在動它等於白做 |
| 改 `app/static/browse.html` 或任何前端 | 待決定頁走完整三關是 **Phase 70**。本 phase 只把資料與 API 備好 |
| 為建議加「信心分數」「猜了幾次」 | design5 沒寫。三欄就是三欄 |
| 幫舊照片補建議（回填） | 舊照片沒有建議是**正常**的（三欄 NULL），待決定彈窗照舊只有②③④，與現在 `suggested_category` 為 NULL 的處理一致 |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：
> 步驟 1〜3 是「建議落庫」那一半（先紅 → 綠 → 驗），
> 步驟 4〜6 是「摘要八鍵」那一半（先紅 → 綠 → 驗），
> 步驟 7 全量回歸、步驟 8 commit。

### - [ ] 步驟 1：先寫測試（紅）——在 `tests/integration/test_ingest_job.py` **檔案最後面**追加

先在檔案最上方的 import 區補一個名字（`PhotoUnderstanding` 已經有了，這裡要多用 `date`）：

```python
from datetime import date, datetime
```

（原本是 `from datetime import datetime`，改成上面這一行。）

然後在檔案最後面追加：

```python
# ---------------------------- ⑧ 建議落庫（Phase 61 / design5.md D16）----------------------------
#
# 三個新欄位存的都是「AI 當下猜了什麼」，不是「照片屬於什麼」。
# 照片的實際歸屬永遠是收件箱；實體與待辦要等人在待決定的彈窗按下去才會有資料。


def 帶建議的理解(*, entity=None, task_title=None, task_due=None) -> PhotoUnderstanding:
    """一份「看得懂」的理解結果，三個建議欄位可以個別指定。"""
    return PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
        entity=entity,
        task_title=task_title,
        task_due=task_due,
    )


def 跑一次並取回那一列(vlm) -> dict:
    """建 job → 跑任務 → 把入庫的那一列撈回來。"""
    store = InMemoryJobStore()
    job_id = 建一個job(store)
    ingest_job.run_ingest_job(
        job_id, store=store, vlm=vlm, embeddings=FakeEmbeddings(), now=NOW
    )
    assert photo_repository.count_photos() == 1
    photo_id = photo_repository.list_photos_in_folder(收件箱id())[0]["id"]
    return photo_repository.fetch_photo(photo_id)


def test_實體建議在清單內_落庫成清單上的名稱():
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    # 刻意用不同大小寫與多餘空白：clamp_entity 要夾回**清單上的原文**。
    # 注意整個名稱都要在（clamp 是逐字 casefold 比對、不是模糊比對）：
    # 寫成 "my macbook" 會因為少了「我的」而對不上、退成 None，測試就紅錯地方。
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="  我的 macbook  ")))

    assert row["suggested_entity"] == "我的 MacBook"


def test_實體建議在清單外_落庫NULL():
    """實體沒有「未分類」這種保底：清單上沒有的名字一律不落庫（design3 D12）。"""
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="鄰居的貓")))

    assert row["suggested_entity"] is None


def test_實體清單是空的時候也落庫NULL():
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(entity="任何名字")))

    assert row["suggested_entity"] is None


def test_待辦建議完整_標題與到期日都落庫():
    row = 跑一次並取回那一列(
        FakeVLM(帶建議的理解(task_title="繳交作業三", task_due="2026-08-21"))
    )

    assert row["suggested_task_title"] == "繳交作業三"
    assert row["suggested_task_due"] == date(2026, 8, 21)


def test_待辦建議只有標題沒有到期日_標題落庫日期NULL():
    """日期推不出來只是少一個日期，不可以害整張照片入不了庫（與 content_time 同一原則）。"""
    row = 跑一次並取回那一列(
        FakeVLM(帶建議的理解(task_title=" 繳電費 ", task_due="下週三"))
    )

    assert row["suggested_task_title"] == "繳電費", "前後空白要去掉"
    assert row["suggested_task_due"] is None
    assert photo_repository.count_photos() == 1, "日期看不懂不影響入庫"


def test_照片沒有待辦_標題與日期兩欄都是NULL():
    row = 跑一次並取回那一列(FakeVLM(帶建議的理解(task_title="   ")))

    assert row["suggested_task_title"] is None
    assert row["suggested_task_due"] is None


def test_worker不會自己建實體_不會自己釘選_也不會自己建待辦():
    """design5.md §4.2：建議永遠只是建議，人按確認才寫那三張表。"""
    photo_repository.create_entity("我的 MacBook", "工作用筆電")
    row = 跑一次並取回那一列(
        FakeVLM(帶建議的理解(entity="我的 MacBook", task_title="繳交作業三",
                             task_due="2026-08-21"))
    )
    photo_id = row["id"]

    # 建議都寫進 photo 那一列了……
    assert row["suggested_entity"] == "我的 MacBook"
    assert row["suggested_task_title"] == "繳交作業三"
    # ……但三張「人確認才寫」的表一列都不能多
    assert photo_repository.list_entities() == [
        {"id": 1, "name": "我的 MacBook", "description": "工作用筆電"}
    ], "worker 不可以自己建新實體"
    assert photo_repository.list_photo_entities(photo_id) == [], "worker 不可以自己釘"
    assert photo_repository.get_task_by_photo(photo_id) is None, "worker 不可以自己建待辦"
```

跑一次確認**紅**：

```bash
pytest tests/integration/test_ingest_job.py -q
```

預期：新增 7 顆中**紅 4 顆**——「清單內」「待辦建議完整」「只有標題」「worker不會自己建」
（worker 還沒寫這三欄，斷言值全是 None，例如 `assert None == '我的 MacBook'`）；
另外 3 顆（「清單外」「清單空」「沒有待辦」）**這時就是綠的**——它們斷言的本來就是 NULL，
Phase 59 的程式什麼都不寫時恰好也是 NULL。紅的那 4 顆才是本步驟的紅燈。
Phase 59 原有的 11 顆仍然綠。
（若看到 `KeyError: 'suggested_entity'`，代表 Phase 56 沒把三欄加進 `PHOTO_COLUMNS`——
回 §2 的前置檢查補完再回來，不要在本 phase 自己加。）

### - [ ] 步驟 2：綠——改 `app/services/ingest_job.py`

**2-1. `_insert_photo_with_files` 的簽章多收 `entities`。** 把

```python
def _insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    uploaded_at: datetime | None,
) -> int:
```

改成

```python
def _insert_photo_with_files(
    image_bytes: bytes,
    content_type: str,
    understanding: vlm_service.PhotoUnderstanding,
    embedding: list[float],
    *,
    inbox_name: str,
    folders: list[dict],
    entities: list[dict],
    uploaded_at: datetime | None,
) -> int:
```

**2-2. 把三個建議欄算出來並寫進 INSERT。** 把函式裡原本這一段（Phase 59 寫的）

```python
    # VLM 給的類別只當「建議」：夾回清單內，清單外一律變「未分類」。
    # 建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL（Phase 35 的規則不變）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    suggested_category = None if suggested_name == inbox_name else suggested_name

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=vlm_service.parse_content_time(understanding.content_time),
        embedding=embedding,
        uploaded_at=uploaded_at,
        suggested_category=suggested_category,
    )
```

整段換成

```python
    # ── 三個「建議」欄位（design5.md D16）──────────────────────────────
    # 這裡寫的是「AI 當下猜了什麼」，不是「這張照片屬於什麼」。
    # 照片的實際歸屬永遠是收件箱（category／folder_id 都是「未分類」）；
    # 實體與待辦更是**一列都不寫**——那三張表要等人在待決定的彈窗按下去才有資料
    #（design5.md §4.2、design3.md D3「人確認才落庫」）。
    #
    # 為什麼非存不可：上傳改 202 之後（Phase 62），建議不會再出現在任何回應裡。
    # 不存下來的話，使用者幾分鐘後到待決定頁點開那張照片時，
    # 實體窗會少了選項①、**待辦窗會永遠不開**（開窗條件就是「有待辦建議」）。

    # ① 資料夾建議：夾回清單內，清單外一律變「未分類」。
    #    建議指向收件箱＝clamp 失敗＝根本沒有建議 → 存 NULL（Phase 35 的規則不變）。
    suggested_name = vlm_service.clamp_category(understanding.category, folders)
    suggested_category = None if suggested_name == inbox_name else suggested_name

    # ② 實體建議：同樣夾回清單，但**沒有保底選項**——清單外或都不像就是 None
    #    （clamp_entity 回的是整筆 dict，這一欄只存名稱字串）。
    suggested_entity_row = vlm_service.clamp_entity(understanding.entity, entities)
    suggested_entity = suggested_entity_row["name"] if suggested_entity_row else None

    # ③ 待辦建議：判準與現在 photos.py::_task_suggestion() 逐字相同——
    #    標題是空的（沒填或只有空白）＝這張照片沒有待辦，兩欄都留 NULL。
    #    到期日沿用 parse_content_time 的寬容解析：模型回「下週三」之類推不出來的東西
    #    只是少一個日期，**絕不可以讓整張照片入不了庫**（與 content_time 同一個原則）。
    suggested_task_title: str | None = None
    suggested_task_due = None
    if understanding.task_title and understanding.task_title.strip():
        suggested_task_title = understanding.task_title.strip()
        suggested_task_due = vlm_service.parse_content_time(understanding.task_due)

    row = photo_repository.insert_photo(
        text=understanding.text,
        category=inbox_name,
        location=understanding.location,
        items=understanding.items,
        content_time=vlm_service.parse_content_time(understanding.content_time),
        embedding=embedding,
        uploaded_at=uploaded_at,
        suggested_category=suggested_category,
        suggested_entity=suggested_entity,
        suggested_task_title=suggested_task_title,
        suggested_task_due=suggested_task_due,
    )
```

**2-3. 兩個呼叫端各加一行 `entities=entities,`。**

`_run_image_job` 裡的：

```python
        photo_id = _insert_photo_with_files(
            image_bytes,
            content_type,
            understanding,
            embedding,
            inbox_name=inbox["name"],
            folders=folders,
            entities=entities,          # ← Phase 61 新增
            uploaded_at=now(),
        )
```

`_run_pdf_job` 裡的：

```python
                photo_id = _insert_photo_with_files(
                    page_bytes,
                    PDF_PAGE_CONTENT_TYPE,
                    understanding,
                    embedding,
                    inbox_name=inbox["name"],
                    folders=folders,
                    entities=entities,          # ← Phase 61 新增
                    uploaded_at=now(),
                )
```

> ✅ 兩條路共用同一個 `_insert_photo_with_files`，所以 **PDF 的每一頁也會自動有三個建議欄**，
> 不必為 PDF 另外寫一份。

**2-4.** `folders`／`entities` 這兩份清單本來就已經在 prompt 裡注入了——
Phase 59 的 `_run_image_job` 第 ③ 段已經照 `photos.py::upload_photo` 抄過來：

```python
    folders = photo_repository.list_folders()
    entities = photo_repository.list_entities()
    corrections = photo_repository.recent_corrections(limit=FEW_SHOT_CORRECTIONS)
```

而 `_understand_and_embed` 把三份原樣傳給 `vlm.understand(...)`，
`vlm_service.build_vlm_prompt(folders, entities, corrections)` 再把它們組進 prompt。
**這一段本 phase 一個字都不用改**，只是要確認它真的在（步驟 3 的驗收指令會查）。

跑新測試看它轉綠：

```bash
pytest tests/integration/test_ingest_job.py -v
```

預期最後一行：`18 passed`（Phase 59 的 11 ＋ 本 phase 的 7）。

### - [ ] 步驟 3：確認 prompt 注入沒有斷掉

```bash
awk '/def _run_image_job/,/^def _understand_and_embed/' app/services/ingest_job.py \
  | grep -n "list_folders\|list_entities\|recent_corrections"
```

預期**六行**——awk 的範圍從 `_run_image_job` 一路涵蓋到 `_understand_and_embed` 之前，
中間夾著 Phase 60 加的 `_run_pdf_job`，所以兩個函式各出現一組三行；
兩組的順序都必須是 `list_folders` → `list_entities` → `recent_corrections`（與 `photos.py` 相同）。

```bash
pytest tests/integration/test_ingest_job_pdf.py -q
```

預期：`9 passed`（Phase 60 的那顆「清單只讀一次」也還要是綠的）。

### - [ ] 步驟 4：先寫測試（紅）——摘要五鍵 → 八鍵

**4-1. 核對（不改）：`tests/integration/test_folder_repository.py` 的鍵集合斷言已是八鍵。**
Phase 56 步驟 1-2 已把 `test_列出資料夾內的照片新的在前` 第 121〜124 行的斷言從五鍵改成八鍵
（同一個 phase 的步驟 5-4 也把 `list_photos_in_folder` 的 SELECT 改成八欄，所以那顆**當時就轉綠了**），
還新增了一顆 `test_資料夾內照片摘要帶得出三個建議欄`。repository 層歸 Phase 56 所有，
**本 phase 不動這個檔**。核對指令：

```bash
grep -n "suggested_task_due" tests/integration/test_folder_repository.py
```

預期：**恰三行命中**（八鍵斷言裡一行＋Phase 56 新增的 `test_資料夾內照片摘要帶得出三個建議欄` 裡兩行）。
**零命中 → Phase 56 步驟 1-2 沒做完**：回 Phase 56 把它補完（連同步驟 5-4 的 SELECT），
不要在本 phase 改這個檔。

**4-2. 改 `tests/integration/test_folders_endpoint.py` 第 105〜108 行。** 把

```python
    # Phase 35 起由四鍵變五鍵：多的 suggested_category 讓待決定分頁畫得出選項①
    assert set(photo) == {
        "id", "thumbnail_url", "text", "uploaded_at", "suggested_category"
    }
```

改成

```python
    # Phase 35 起由四鍵變五鍵（suggested_category），
    # Phase 61 起由五鍵變八鍵：上傳改 202 之後，建議只能從這裡讀（design5.md D16、§6.2）
    assert set(photo) == {
        "id", "thumbnail_url", "text", "uploaded_at",
        "suggested_category", "suggested_entity",
        "suggested_task_title", "suggested_task_due",
    }
```

**4-3. 在 `tests/integration/test_folders_endpoint.py` 最後面追加一顆。**
先把檔案最上方的輔助函式 `_插入照片` 改成收得下三個建議（第 26〜50 行的那一個）：

```python
def _插入照片(
    text: str,
    category: str,
    *,
    有縮圖: bool,
    suggested_entity: str | None = None,
    suggested_task_title: str | None = None,
    suggested_task_due: date | None = None,
) -> int:
    """插一張照片並回它的 id。

    insert_photo 會依 category 找同名資料夾（Phase 15），所以 category="收據"
    的照片會自動掛在 2 號資料夾底下。有縮圖的才呼叫 update_photo_paths（Phase 19）
    寫入路徑——沒寫路徑的就等於「舊資料」，thumbnail_url 應該是 null。

    三個建議欄（Phase 61 / design5.md D16）預設不給＝舊照片的樣子（全是 NULL）。
    """
    row = photo_repository.insert_photo(
        text=text,
        category=category,
        location="Target",
        items=["可樂"],
        content_time=date(2026, 8, 10),
        embedding=FakeEmbeddings().embed_query(text),
        uploaded_at=NOW,
        suggested_entity=suggested_entity,
        suggested_task_title=suggested_task_title,
        suggested_task_due=suggested_task_due,
    )
    photo_id = row["id"]
    if 有縮圖:
        photo_repository.update_photo_paths(
            photo_id,
            original_path=f"data/photos/{photo_id}.png",
            thumbnail_path=f"data/thumbs/{photo_id}.png",
            content_type="image/png",
        )
    return photo_id
```

然後在檔案最後面追加：

```python
def test_摘要帶著實體與待辦的建議(client):
    """design5.md D16／§6.2：上傳改 202 之後，待決定頁只能從這裡讀到建議。

    沒有這三個欄位，實體窗就少了選項①、**待辦窗會永遠不開**。
    """
    photo_id = _插入照片(
        "在 Target 購買可樂的收據",
        "收據",
        有縮圖=True,
        suggested_entity="我的 MacBook",
        suggested_task_title="繳交作業三",
        suggested_task_due=date(2026, 8, 21),
    )

    photos = client.get(f"/folders/{收據_ID}").json()["photos"]

    assert photos[0]["id"] == photo_id
    assert photos[0]["suggested_entity"] == "我的 MacBook"
    assert photos[0]["suggested_task_title"] == "繳交作業三"
    assert photos[0]["suggested_task_due"] == "2026-08-21"   # JSON 是 ISO 字串


def test_沒有建議的舊照片三個欄位都是null(client):
    """遷移進來的舊照片沒有建議，是**預期行為**（彈窗照舊只有②③④）。"""
    _插入照片("沒有任何建議的舊資料", "收據", 有縮圖=False)

    photo = client.get(f"/folders/{收據_ID}").json()["photos"][0]

    assert photo["suggested_entity"] is None
    assert photo["suggested_task_title"] is None
    assert photo["suggested_task_due"] is None
```

跑一次確認**紅**（指令刻意連 `test_folder_repository.py` 一起跑——它必須**全綠**，
那是「Phase 56 真的做完了」的另一個證據）：

```bash
pytest tests/integration/test_folder_repository.py tests/integration/test_folders_endpoint.py -q
```

預期：**恰 3 顆紅，全部在 `test_folders_endpoint.py`**；`test_folder_repository.py` 的 11 顆**一顆都不紅**。逐顆點名：

| 測試 | 紅／綠 | 為什麼 |
|---|---|---|
| `test_folders_endpoint.py::test_資料夾內容含照片摘要`（4-2 改過的那顆） | **紅** | 斷言已改成期望八鍵，但 `PhotoSummary` 還是五個欄位——repository 多回的三鍵被 `response_model` **默默丟掉**，回應仍是五鍵，`assert set(photo) == {…八鍵…}` 不成立 |
| `test_folders_endpoint.py::test_摘要帶著實體與待辦的建議`（4-3 新增） | **紅** | 回應 JSON 裡根本沒有 `suggested_entity` 這個鍵 → `KeyError: 'suggested_entity'` |
| `test_folders_endpoint.py::test_沒有建議的舊照片三個欄位都是null`（4-3 新增） | **紅** | 同上：`KeyError: 'suggested_entity'` |
| `test_folder_repository.py::test_列出資料夾內的照片新的在前` | **綠** | **這顆現在就是綠的**——Phase 56 已把它的斷言改成八鍵、SELECT 也改成八欄，兩邊在 Phase 56 步驟 6 就對上了。（本文件舊版把它算成第 4 顆紅，那是同一件事寫進兩份任務書時算錯的；它不在本 phase 的紅燈裡） |

紅的顆數不是 3 就先停：紅燈跑進 `test_folder_repository.py` 那邊＝Phase 56 沒做完
（回 Phase 56 補，不要在這裡改它的檔）；`test_folders_endpoint.py` 紅的不是上面那三顆＝4-2／4-3 沒貼齊。

### - [ ] 步驟 5：綠——repository 只核對，schema 與 router 各改一處

**5-1. 核對（不改）：`app/repositories/photo_repository.py` 的 `list_photos_in_folder` 已是八欄。**
SELECT 從五欄改八欄是 **Phase 56 步驟 5-4** 做掉的事，**本 phase 不改這個函式**（一個字都不改）。
這三欄是 design5.md D16 的命脈——上傳改成 202 之後，建議不再出現在任何回應裡，
少了它們，待決定頁的實體窗會沒有選項①、**待辦窗會永遠不開**——但把它們 SELECT 出來的那半
歸 Phase 56，本 phase 負責的是下游的 schema 與 router（5-2、5-3）。核對指令：

```bash
awk '/def list_photos_in_folder/,/fetchall/' app/repositories/photo_repository.py \
  | grep -n "suggested_entity"
```

預期：**恰一行**——SELECT 的第二行，`suggested_entity, suggested_task_title, suggested_task_due`
三個欄名都在上面。**零命中＝SELECT 還停在五欄 → 回去把 Phase 56 步驟 5-4 做完，不要在這裡改**
（在這裡改，兩份 phase 的 commit 歸屬就對不上了）。

下面是 Phase 56 做完之後這個函式**該有的樣子**——貼在這裡只是讓你對照核對用，**不是叫你改**：

```python
def list_photos_in_folder(folder_id: int) -> list[dict[str, Any]]:
    """某個資料夾裡的照片摘要，新的在前（Phase 22 的縮圖牆要用）。

    只取瀏覽需要的欄位——不回傳 embedding（1024 個數字，前端用不到）。
    ORDER BY id DESC＝id 由大到小；id 自動遞增，所以「大的」就是「晚上傳的」。

    ★ Phase 35 從四欄變五欄：多的 suggested_category 是給「待決定」分頁畫選項①用的
      （design1「摘要恰四鍵」由 phase-35 明文修訂）。有了它，待決定分頁就能拿出
      上傳當下那一筆建議，不必為了畫①再看一次圖。
    ★ Phase 56 再從五欄變八欄：D16 的三個建議欄。理由完全相同，只是對象換成
      實體彈窗的選項①與待辦彈窗的預填值——上傳改 202 之後建議不再回給前端，
      待決定頁只能從這裡讀（design5.md D16、§6.2）。
      本 phase 三個值一律是 NULL；真的餵值進去是 Phase 61。
    ★ 注意分層：這是 repository 回的鍵。GET /folders/{id} 的回應現在仍是五鍵，
      因為 schemas/folder.py 的 PhotoSummary 只挑它要的那幾個。
      把回應也加成八鍵是 Phase 61 的事，本 phase 的 API 回應逐位元不變。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, text, uploaded_at, thumbnail_path, suggested_category,
                       suggested_entity, suggested_task_title, suggested_task_due
                FROM photo
                WHERE folder_id = %(folder_id)s
                ORDER BY id DESC;
                """,
                {"folder_id": folder_id},
            )
            return cur.fetchall()
```

> 📌 上面 docstring 裡的「本 phase」與「回應現在仍是五鍵」講的都是 **Phase 56 當下**；
> 你等一下做完 5-2／5-3，回應就是八鍵了。這段 docstring 連同整個函式歸 Phase 56 所有，
> 看到它「過期」也**不要順手去改**——沿革註記寫在哪個 phase 的 commit，就留在那裡。

**5-2. `app/schemas/folder.py`。** 檔案最上方的 import 改成：

```python
from datetime import date, datetime
```

`PhotoSummary` 整個換成：

```python
class PhotoSummary(BaseModel):
    """縮圖牆上一張照片要顯示的資訊。

    thumbnail_url 是「網址」不是硬碟路徑：資料庫的 thumbnail_path 有值時
    換算成 /photos/{id}/thumbnail（Phase 19 的讀圖端點）；舊資料沒有路徑時
    是 None（JSON 的 null），前端顯示灰底占位（design1.md §10）。

    欄位數的沿革：
      Phase 22 四鍵 → Phase 35 五鍵（+suggested_category）→ **Phase 61 八鍵**。

    後面三個是 design5.md D16 的「建議落庫」：上傳自 Phase 62 起回 202，
    建議不會再出現在任何回應裡，待決定頁只能從這支端點讀。
    三個都是**建議**，不是事實——照片實際釘了哪些實體要看 photo_entity，
    有沒有待辦要看 task 表。人在彈窗按下去，那兩張表才會有資料。
    舊照片三個都是 None，彈窗照舊只有②③④，這是預期行為。
    """

    id: int
    thumbnail_url: str | None
    text: str
    uploaded_at: datetime   # 轉成 JSON 時是 ISO 字串，例如 2026-08-18T10:00:00+08:00
    suggested_category: str | None
    suggested_entity: str | None        # clamp 後的實體**名稱**，清單外＝None
    suggested_task_title: str | None    # 沒有可辦的事＝None（待辦窗就不開）
    suggested_task_due: date | None     # 轉成 JSON 時是 "2026-08-21" 這種字串
```

**5-3. `app/api/routers/folders.py` 的 `get_folder`。** 把組 `PhotoSummary` 那一段換成：

```python
    photos = [
        PhotoSummary(
            id=row["id"],
            # 有存過縮圖檔才給網址；舊資料沒有路徑 → None → JSON null
            thumbnail_url=(
                f"/photos/{row['id']}/thumbnail" if row["thumbnail_path"] else None
            ),
            text=row["text"],
            uploaded_at=row["uploaded_at"],
            # 上傳當下的三個建議（Phase 35 的資料夾 ＋ Phase 61 的實體與待辦）：
            # 待決定頁靠它們畫選項①與決定要不要開待辦窗；沒建議就是 null。
            suggested_category=row["suggested_category"],
            suggested_entity=row["suggested_entity"],
            suggested_task_title=row["suggested_task_title"],
            suggested_task_due=row["suggested_task_due"],
        )
        for row in photo_repository.list_photos_in_folder(folder_id)
    ]
```

跑一次看它轉綠：

```bash
pytest tests/integration/test_folder_repository.py tests/integration/test_folders_endpoint.py -v
```

預期兩個檔全綠：`test_folders_endpoint.py` 是 `10 passed`（原本 8 ＋ 新增 2）、
`test_folder_repository.py` 維持 `11 passed`（Phase 56 之後的顆數——本 phase 沒加也沒改它）。

### - [ ] 步驟 6：確認端點數**沒有變**

```bash
python -c "
from fastapi.testclient import TestClient
from app.main import app
paths = TestClient(app).get('/openapi.json').json()['paths']
print('端點數：', sum(len(ms) for ms in paths.values()))
"
```

預期印出 `端點數： 20`。本 phase 只加回應欄位，一個端點都沒新增。

### - [ ] 步驟 7：全量回歸

```bash
pytest -q
```

預期：**Phase 60 結束時的顆數 ＋ 9**（`test_ingest_job.py` +7、`test_folders_endpoint.py` +2），
全綠、0 skipped。

零外部依賴實證：

```bash
OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q
```

預期：顆數相同。

### - [ ] 步驟 8：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/services/ingest_job.py \
        app/schemas/folder.py app/api/routers/folders.py \
        tests/integration/test_ingest_job.py \
        tests/integration/test_folders_endpoint.py
git commit -m "feat: Phase 61 建議落庫接線（D16）——worker INSERT 時一併寫 suggested_entity（clamp 後）／suggested_task_title／suggested_task_due，GET /folders/{id} 摘要五鍵→八鍵；worker 仍不碰 entity／photo_entity／task 三表，端點仍 20，+9 tests"
```

> 📌 `app/repositories/photo_repository.py` 與 `tests/integration/test_folder_repository.py`
> **刻意不在清單裡**：那兩個檔是 Phase 56 改好、commit 過的，本 phase 只核對、沒有改。
> `git status` 若看到它們有改動，代表你手滑動到了 Phase 56 的地盤——先還原再 commit。
>（commit 訊息裡的「摘要五鍵→八鍵」指的是 `GET /folders/{id}` 的**回應**；
> repository 那層的五欄→八欄已寫在 Phase 56 的 commit 訊息裡，這裡不重複認領。）

---

## 5. ASCII 圖：一則「建議」的一生

```text
① VLM 看圖（worker 裡，一次呼叫就出九個欄位）
   ┌──────────────────────────────────────────────────────────────────────┐
   │ PhotoUnderstanding(                                                   │
   │   understood=True,                                                    │
   │   text="繳費單：第三次作業，8/21 前交",                                │
   │   category="收據",          ← 資料夾建議                              │
   │   location="…", items=[…], content_time="2026-08-18",                 │
   │   entity="我的 macbook",    ← 實體建議（模型自己打的，大小寫不一定對） │
   │   task_title="繳交作業三",  ← 待辦建議（標題）                        │
   │   task_due="2026-08-21",    ← 待辦建議（到期日）                      │
   │ )                                                                     │
   └──────────────────────────────────────────────────────────────────────┘
                                    │
② clamp（夾回現有清單。這一步是**保險**——prompt 已經叫模型只從清單挑，但模型不聽話是常態）
                                    ▼
   ┌────────────────────────────┬─────────────────────────────────────────┐
   │ clamp_category("收據",      │ 對得到 → 回清單原文「收據」             │
   │   folders)                 │ 對不到 → 回「未分類」＝**根本沒有建議** │
   ├────────────────────────────┼─────────────────────────────────────────┤
   │ clamp_entity(              │ 對得到 → 回整筆 dict，取 name           │
   │   "我的 macbook", entities)│          →「我的 MacBook」（清單原文）  │
   │                            │ 對不到 → None（實體**沒有**保底選項）   │
   ├────────────────────────────┼─────────────────────────────────────────┤
   │ task_title.strip()         │ 有字 → 留著；全空白 → None（＝沒待辦）  │
   │ parse_content_time(due)    │ 看得懂 → date；「下週三」→ None         │
   └────────────────────────────┴─────────────────────────────────────────┘
                                    │
③ 落庫（**Phase 61 就是在做這一步**）——一條 INSERT，四個建議欄跟著照片一起寫進去
                                    ▼
   photo 表的那一列：
   ┌───────────────────────────────────────────────────────────────────────┐
   │ id                   = 73                                             │
   │ text / category / location / items / content_time / embedding …       │
   │ folder_id            = 1（未分類＝收件箱）  ← **實際歸屬，不是建議**  │
   │ category             = "未分類"             ← 也是實際歸屬            │
   │ ─────────────────── 以下四欄都只是「當時猜了什麼」 ─────────────────── │
   │ suggested_category   = "收據"          （Phase 35 就有）              │
   │ suggested_entity     = "我的 MacBook"  ← Phase 61 新增                │
   │ suggested_task_title = "繳交作業三"    ← Phase 61 新增                │
   │ suggested_task_due   = 2026-08-21      ← Phase 61 新增                │
   └───────────────────────────────────────────────────────────────────────┘

   ⛔ 此時 entity 表、photo_entity 表、task 表**一列都沒有多**。
      worker 不做人該做的決定（design5 §4.2、design3 D3）。

                                    │
④ 讀出來（GET /folders/{收件箱id} 的照片摘要，Phase 61 從五鍵擴成八鍵）
                                    ▼
   { "id": 73,
     "thumbnail_url": "/photos/73/thumbnail",
     "text": "繳費單：第三次作業，8/21 前交",
     "uploaded_at": "2026-08-18T10:00:00+08:00",
     "suggested_category":   "收據",
     "suggested_entity":     "我的 MacBook",       ← 新
     "suggested_task_title": "繳交作業三",         ← 新
     "suggested_task_due":   "2026-08-21" }        ← 新

                                    │
⑤ 待決定頁畫成選項①（**Phase 70** 才做，本 phase 只把資料備好）
                                    ▼
   ┌─ 抽屜窗 ────────────────┐  ┌─ 實體窗 ──────────────┐  ┌─ 待辦窗 ──────────────┐
   │ ① 採用建議「收據」      │→ │ ① 採用建議           │→ │ 標題：[繳交作業三   ] │
   │ ② 改選現有              │  │    「我的 MacBook」   │  │ 到期：[2026-08-21   ] │
   │ ③ 自建新資料夾          │  │ ② 改選現有           │  │                       │
   │ ④ 稍後再說              │  │ ③ 自創               │  │ [建立待辦] [略過]     │
   └─────────────────────────┘  │ ④ 不釘，繼續         │  └───────────────────────┘
                                └───────────────────────┘   ★ suggested_task_title
                                                               是空的就**不開這一窗**
                                    │
⑥ 人按下去，這時候才真的寫那三張表（既有端點，本 phase 不改）
                                    ▼
   PATCH /photos/73/folder        → photo.folder_id ／ category ／ embedding 一起更新（定案，不可逆）
   POST  /photos/73/entities      → entity（自創才建）＋ photo_entity 一列（釘選）
   POST  /photos/73/task          → task 一列

   ★ 建議欄不會被清掉，也不會被改。它們是「當時猜了什麼」的存根：
     抽屜那一欄還有第二個用途——定案時拿來比對「猜的 vs 選的」，
     不一樣就記一筆糾錯素材當下次看圖的 few-shot（Phase 35 的 D11）。
```

---

## 6. 驗收清單

- [ ] 三個建議欄真的寫進去了（跑那 7 顆）：
      ```bash
      pytest tests/integration/test_ingest_job.py -q
      ```
      預期 `18 passed`（Phase 59 的 11 ＋ 本 phase 的 7）
- [ ] **worker 不碰那三張表**（design5 §4.2 的硬規則）：
      ```bash
      grep -nE "create_entity|pin_entity|create_and_pin_entity|create_task|create_folder|update_photo_folder|record_folder_correction" app/services/ingest_job.py || echo "OK：worker 不做人該做的決定"
      ```
      預期印出 `OK：worker 不做人該做的決定`
- [ ] `clamp_entity` 的結果**才**落庫（不是原始輸出）：
      ```bash
      grep -n "clamp_entity\|suggested_entity" app/services/ingest_job.py
      ```
      預期 `clamp_entity(...)` 在 `suggested_entity=` 之前，且 `suggested_entity` 取的是 `["name"]`
- [ ] 兩條路（單圖／PDF）都帶了 `entities`：
      ```bash
      grep -n "entities=entities" app/services/ingest_job.py
      ```
      預期**兩處**（`_run_image_job` 與 `_run_pdf_job` 各一）
- [ ] 摘要真的是八鍵（本 phase 改的 API 層＋Phase 56 改的 repository 層一起驗）：
      ```bash
      pytest tests/integration/test_folders_endpoint.py tests/integration/test_folder_repository.py -q
      ```
      預期全綠（`test_folders_endpoint.py` 10 顆、`test_folder_repository.py` 11 顆——
      後者的八鍵斷言是 Phase 56 的成果，本 phase 沒動那個檔）
- [ ] SQL 仍只在 repository（router 零 SQL；跑既有的自動化掃碼那一顆）：
      ```bash
      pytest tests/integration/test_design3_error_paths.py -k "SQL只出現在repository" -v
      ```
      預期 `1 passed`（不要自己 grep 大寫 `UPDATE ` 之類的字面——`ingest_job.py` 與
      `photos.py` 的說明文字裡本來就有這些詞，會誤中；理由詳見 phase-59 §6 同名項）
- [ ] **端點數仍是 20**：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `20`
- [ ] openapi 仍然零 DELETE：
      ```bash
      pytest tests/integration/test_design3_error_paths.py -k "DELETE" -v
      ```
      預期 `1 passed`
- [ ] `photos.py`、`camera.py`、前端，以及 **Phase 56 擁有的 repository 層**
      （`photo_repository.py`＋`test_folder_repository.py`）**一個字都沒改**：
      ```bash
      git diff --stat app/api/routers/photos.py app/api/routers/camera.py app/static/ \
        app/repositories/photo_repository.py tests/integration/test_folder_repository.py
      ```
      預期：**無輸出**（repository 那兩個檔有 diff ＝手滑動到 Phase 56 的東西，先還原）
- [ ] `GET /photos/{id}` 的唯讀窗**沒有**被順手加欄位（design4 §4.4 刻意不回建議）：
      ```bash
      pytest tests/integration/test_photo_detail.py -q
      ```
      預期全綠
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ Phase 60 結束時 ＋ **9**
- [ ] 零外部依賴：`OLLAMA_BASE_URL=http://127.0.0.1:1 pytest -q` 顆數相同
- [ ] 正式庫的三欄還在（Phase 56 遷過，本 phase 沒有動結構）：
      ```bash
      psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI \
        -c "SELECT count(*) FILTER (WHERE suggested_entity IS NOT NULL) AS 有實體建議,
                   count(*) FILTER (WHERE suggested_task_title IS NOT NULL) AS 有待辦建議,
                   count(*) AS 全部 FROM photo;"
      ```
      預期：前兩個都是 0（舊照片本來就沒有建議），`全部` 是現有照片數。**這是預期行為，不是 bug**

---

## 7. 常見陷阱

1. **把 `clamp_entity()` 回傳的 dict 整個塞進 `suggested_entity`。**
   `clamp_entity` 回的是 `{"id": 1, "name": "我的 MacBook", "description": "…"}`，
   而資料庫那一欄是 `TEXT`。
   **症狀**：`psycopg` 丟 `ProgrammingError: cannot adapt type 'dict'`，或者存進去變成 `"{'id': 1, ...}"` 這種字串。
   **正解**：`suggested_entity_row["name"] if suggested_entity_row else None`。
   **為什麼不存 id？** 因為實體沒有刪除功能、但名稱是使用者認得的東西；
   而且契約備忘 §4 白紙黑字寫「`suggested_entity` `TEXT` VLM 建議的實體名稱」。

2. **忘了 `clamp`，直接存 `understanding.entity`。**
   模型很常回清單上沒有的東西（「我的筆電」「MacBook Pro 14"」）。直接存的話，
   待決定頁的選項①會出現一個**根本不存在的實體**，使用者按下去 → 找不到 id → 只能自創一個名字相近的新實體 → 清單越長越亂。
   **正解**：`clamp_entity()` 對不到就是 `None`（實體沒有「未分類」保底），這是 design3 D12 的原意。

3. **待辦標題是空白卻還是把到期日存進去。**
   會產生「沒有標題、只有日期」的半殘建議。Phase 70 的開窗條件是看標題，
   結果就是「窗不開，但資料庫裡有個沒人看得到的日期」。
   **正解**：`if title and title.strip():` 成立時才一起算 due；否則兩欄都 `None`。
   這與現在 `photos.py::_task_suggestion()` 回 `None`（整個 `suggested_task` 是 None，不是空殼）是同一個判準。

4. **到期日解析失敗就讓整張照片入不了庫。**
   模型很常回「下週三」「月底前」。`parse_content_time()` 對這些會回 `None`，**這是設計好的**。
   如果有人改成 `date.fromisoformat(...)` 直接炸，那張照片會走進 `_insert_photo_with_files` 的 except → 被當成寫檔失敗 → 整張沒了。
   **正解**：一律用 `vlm_service.parse_content_time()`，它解析不出來就回 `None`。

5. **以為 repository 已經回八鍵，API 就會自動變八鍵。**
   SELECT 那半是 **Phase 56** 改的：repository 從那時起就回八鍵了，但 `GET /folders/{id}` 至今仍回五鍵——
   因為 Pydantic 的 `response_model` 會把 `PhotoSummary` 沒宣告的鍵**默默丟掉**（不會報錯）。
   本 phase 要補的就是下游那兩層：`PhotoSummary`（5-2）與 router（5-3）。
   **症狀**（漏改其中一層時）：repository 的測試全綠、端點的測試卻說少三個鍵，
   而且錯誤訊息只說 `assert set(...) == {...}`，看不出是哪一層。
   **正解**：「兩層要一起對」這個教訓仍然成立——只是 SELECT 那半早在 Phase 56 就對好了，
   本 phase 對 repository **只核對不改**（5-1），要一起改的是 schema 與 router（5-2、5-3），缺一不可。

6. **把三個新欄位順手加進 `PhotoDetailOut`（`GET /photos/{id}`）。**
   那顆窗是 design4 §4.4 定的**唯讀說明窗**，它的 docstring 明寫「刻意不回 suggested_category」。
   加了不會壞，但 `test_photo_detail.py` 的「六個鍵不多不少」那顆會紅，而且違反那份設計的原意。
   **正解**：不要加。建議是「待決定頁」要的東西，不是「看照片說明」要的東西。

7. **以為舊照片沒有建議是 bug，寫個腳本去回填。**
   舊照片是在這三欄存在之前入庫的，AI 當時根本沒被問過這些問題——回填只能靠**重新看一次圖**，
   那要幾十分鐘、還會產生與當初不一樣的答案。
   **正解**：三欄 NULL 就是 NULL。待決定彈窗照舊只有②③④（與 `suggested_category` 為 NULL 時完全一樣的處理）。

8. **在 `test_folders_endpoint.py` 直接 `assert photos[0]["suggested_task_due"] == date(2026, 8, 21)`。**
   那是**端點**回的 JSON，日期已經被 Pydantic 序列化成字串了。
   **症狀**：`assert '2026-08-21' == datetime.date(2026, 8, 21)` 失敗，很容易誤以為是資料庫存錯。
   **正解**：端點層比字串 `"2026-08-21"`；repository 層（`fetch_photo`）才比 `date` 物件。

9. **只改了 `_run_image_job` 的呼叫端，忘了 `_run_pdf_job`。**
   `_insert_photo_with_files` 多了必填的 keyword-only 參數 `entities`，漏掉的那一邊會丟
   `TypeError: _insert_photo_with_files() missing 1 required keyword-only argument: 'entities'`。
   PDF 的那條路只有 `test_ingest_job_pdf.py` 會走到，所以**一定要把那個檔也跑一次**（步驟 3）。

10. **Phase 56 沒做完就開始做本 phase。**
    `insert_photo()` 收不下那三個參數 → `TypeError: insert_photo() got an unexpected keyword argument`；
    或是資料庫沒有那三欄 → `psycopg.errors.UndefinedColumn`；
    或是 `list_photos_in_folder` 的 SELECT 還停在五欄 → 步驟 4-1／5-1 的核對抓得到
    （硬做下去的症狀是步驟 4 的紅燈轉不綠：router 取 `row["suggested_entity"]` 時 `KeyError` 炸 500）。
    **正解**：照 §2 的三個確認指令逐一跑過再開工，4-1／5-1 的核對不過就回 Phase 56。
    **不要在本 phase 自己加欄位、也不要自己改 SELECT**——
    正式庫的結構改動一律走可重跑的遷移腳本，repository 層整個是 Phase 56 的職責。

11. **`db` 沒起來就跑 pytest。** 這一片測試會全紅在連線錯誤，看起來像欄位寫錯了。
    先 `docker compose ps` 確認 `db` 是 `Up (healthy)`。

---

## 8. 完成後的專案狀態

`photo` 那一列現在帶著**四個建議欄**：`suggested_category`（Phase 35 就有）加上本 phase 的
`suggested_entity`／`suggested_task_title`／`suggested_task_due`。
worker 每成功入庫一張照片（單圖或 PDF 的每一頁），就把「AI 當時猜了什麼」一起寫下來。

`GET /folders/{folder_id}` 的照片摘要從五鍵擴成八鍵，
所以待決定頁之後只要打這一支就拿得到全部三種建議，**不必再看一次圖**。

**沒有變的東西**（很重要）：`entity`／`photo_entity`／`task` 三張表在 worker 手上仍然是唯讀的——
一列都不會多。釘選與建待辦仍然只發生在使用者按下彈窗按鈕之後。
端點數仍是 **20**、openapi 仍然零 DELETE、`POST /photos` 仍然是同步的 201。

到這裡，**階段乙的資料面已經全部就緒**：任務本體會跑（59／60）、建議不會蒸發（61）。
接下來 **Phase 62** 才是那個破壞性的一步：`POST /photos` 改成落 staging ＋ 建 job ＋ 回 **202**，
並把全專案既有的 201 斷言（含 BDD binder）改寫成「202 → 跑任務 → 再驗照片」。

測試累計 ＝ Phase 60 結束時 ＋ **9**。
