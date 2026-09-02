# Phase 87：cloud_worker 核心（`process_job_message`）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做這四件事：①不要寫主迴圈、訊號處理與 `python -m`（那是 Phase 88）；
> ②不要連任何真的 AWS（本 phase 一次 AWS 呼叫都沒有，全部用假信箱）；
> ③不要在工人裡算 embedding、也不要碰資料庫（design6 D11／D13）；
> ④不要順手改 `cloud_ingest.py`／`gated_ingest.py`（那是 Phase 77〜81 的檔案，本 phase 一個字都不動）。

> 🎯 **一句話目標：** 新建 `app/workers/cloud_worker.py`，寫出**一個純函式**
> `process_job_message(mailbox, message, vlm)`——它把一則 jobs 訊息從頭處理到尾：
> 冪等檢查 → 從寄物櫃拿檔案與 `context.json` → 用 Ollama Cloud 看圖（最多 3 次）→
> **先** `PutObject result.json`、**再** `SendMessage results`、**最後**刪掉 jobs 訊息。
> 然後用同一顆假信箱跑一次**端到端**：本機送出 → 這支工人處理 → 本機收回入庫。

**為什麼要做這個：**

到 Phase 86 為止，本機這一端已經整條路都通了：閘門會分類、非敏感的檔案會被丟進 S3 寄物櫃、
jobs 佇列會收到一張紙條、本機會在 results 佇列上等答案。**但是另一頭沒有人。**
Phase 86 的真 AWS 煙霧就是刻意讓它等到逾時，然後 fallback 回本機——
那次煙霧驗的是「雲端壞掉時使用者無感」，不是「雲端會做事」。

本 phase 補上「另一頭那個人」。它做的事只有六件（總覽 §2.6），而且**六件都不碰資料庫**：
向量一定要跟庫裡既有的 bge-m3 同源，所以 embedding 永遠留在本機算（design6 D13）；
照片列、原圖、縮圖也一律由本機寫（D1、D13）。工人唯一的產出是一份 `result.json`。

**先在假信箱上做完**（本 phase），**再接真 AWS**（Phase 88），**最後才上 EC2**（Phase 91〜92）。
理由是 design6 §1.2 最後一列已經否決過「第一天同時開六樣東西」：
在一台看不到 shell、只能靠 SSM 的機器上除錯，比在自己的 Mac 上難十倍。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **工人（worker）** | 這裡指**雲端看圖工人** `cloud_worker`，不是增量五那個 Celery worker 容器。兩個都叫 worker 但完全不同：Celery worker 在這台 Mac 上、會寫資料庫；cloud_worker 之後會跑在 EC2 上、**只**看圖 |
| **jobs 訊息 / results 訊息** | 兩條 SQS 佇列上的紙條。jobs＝本機寫給工人的「有新工作，檔案在這個 s3_key」；results＝工人寫給本機的「做完了，去拿 result.json」。**兩張紙條上都只有字串，沒有半個影像位元組** |
| **receipt handle（收據把手）** | 拿走一則 SQS 訊息時 AWS 給你的一串**臨時**字串。要刪掉那則訊息就得用它。它不是訊息 id，而且每次拿到的都不一樣 |
| **visibility timeout（可見度逾時）** | 一則訊息被拿走之後會「隱形」一段時間（本專案 jobs 設 900 秒）。在這段時間內沒被刪掉，它就會重新出現給別人做。所以**處理失敗時不刪訊息**＝自動重來 |
| **at-least-once（至少送一次）** | SQS Standard Queue 的保證：同一則訊息**可能被送兩次以上**。所以收訊息的人必須冪等（design6 D17） |
| **冪等（idempotent）** | 同一件事做兩次，結果跟做一次一樣。工人的冪等做法是「`result.json` 已經在 S3 了就不重看圖」 |
| **寄物櫃 / mailbox** | 本專案對 S3 那個 bucket 的比喻：東西放進去、對方自己來拿，兩邊不必開門互連 |
| **`context.json`** | 本機在送出時一併放進寄物櫃的一份 JSON，裡面是資料夾清單、實體清單、最近的人工糾錯三份清單。**工人沒有資料庫可讀**，靠它才組得出與本機**逐字相同**的看圖 prompt（總覽 §10 追認項 a） |
| **`result.json`** | 工人唯一的產出：看圖結果（對齊 `PhotoUnderstanding` 的九欄）。**不含 embedding 向量**（D13） |
| **`WORKER_VERSION`** | 工人映像被 build 時烙進去的 git commit 短碼。寫進 `result.json`、也會印在啟動 log 裡，Demo 3 靠它證明「EC2 上跑的真的是新映像」 |
| **`TYPE_CHECKING`** | Python 型別標註專用的開關：`if TYPE_CHECKING:` 底下的 `import` **執行時不會真的跑**，只有型別檢查工具（與讀程式的人）看得到。本檔用它讓工人在「不載入 AWS SDK」的情況下也能寫出正確的型別 |
| **AST（抽象語法樹）** | 把一份 `.py` 檔解析成一棵樹的標準函式庫工具（`import ast`）。掃「這個檔到底 import 了什麼」時比 `grep` 可靠——不會誤中註解與字串 |

---

## 1. 對應 design6.md 章節

| 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D9** | 完成訊號＝results 佇列；工人 **PutObject 成功後才 Send**；禁止本機輪詢 HeadObject | `process_job_message` 最後三行的順序鐵律；`test_result先PutObject才SendMessage` 用假信箱的呼叫流水帳釘住 |
| **D11** | EC2 只當工人：不寫 Postgres、不碰 Celery／Redis、不開任何連接埠 | 工人只 import `aws_mailbox`／`vlm_service`／`pdf_service`／`ai_timing`／`config`；`test_工人不import資料庫與Celery與Redis` 用 `ast` 掃 |
| **D12** | EC2 看圖一律 Ollama Cloud，與頁首開關無關 | `process_job_message` 收一個 `VLMClient` 參數（Phase 88 的 `main()` 才決定塞 `OllamaCloudVLM`），所以單元測試塞得進假件 |
| **D13** | 本機入庫：embedding（bge-m3）與 INSERT／原圖／縮圖仍在本機 | `result.json` **沒有** embedding 這個鍵；工人整支程式沒有 `indexing_service` |
| **D17** | SQS at-least-once：工人與本機收結果都必須冪等 | 規則 1（`result.json` 已存在→只補送）與規則 3（input 不在→只刪訊息） |
| **§2 下半（EC2 那段）** | 收 jobs → GetObject input → Ollama Cloud 看圖 → PutObject result.json → SendMessage results | 就是 `process_job_message` 的六個步驟 |
| **§2.2 S3 鍵名** | `documents/{job_id}/input.*`、`documents/{job_id}/result.json` | 鍵名一律跟 `mailbox.input_key()`／`context_key()`／`result_key()` 要，工人**不自己拼字串** |
| **§8 錯誤表第 6 列** | SQS 重送、本機已入庫 → 工人／本機略過 | `test_result已存在時不看圖只補送results並刪jobs訊息`、`test_input不在時只刪jobs訊息什麼都不寫` |
| **§8 錯誤表第 7 列** | VLM 三次失敗 → 不留 photo 列、清 staging；雲端路還要清 S3 | 工人這一側：`understood=false`＋`attempts=3` 寫進 `result.json`（本機收到之後才去標 failed、清 S3——那是 Phase 79 已經做好的事） |
| **§9 測試策略第 3 條** | 非敏感＋假遠端 running → 假工人 Send results 後本機 GetObject 入庫、staging 空 | `tests/integration/test_cloud_roundtrip.py` 兩顆端到端；**從本 phase 起「假工人」換成真的 `process_job_message`** |
| **總覽 §2.6 裁決** | 工人的六條處理規則、順序鐵律、只准 import 那五個模組 | §4.5 的實作逐條照做 |
| **總覽 §10 追認項 a** | S3 多一個鍵 `context.json`（design6 §2.2 沒列） | `read_context()`；缺檔時三份清單都當空的，**不是失敗** |
| **總覽 §10 追認項 g** | 雲端看圖三次都失敗＝這筆 job 失敗，**不是** fallback 本機 | 工人照樣寫出 `understood=false` 的 `result.json`（本機收到就標 failed）；工人**不會**叫本機重看一次 |
| **總覽 §10 追認項 k** | 工人程式放 `app/workers/`，不是 `scripts/` | §4.2 建立套件，`__init__.py` 的 docstring 把理由寫死在原始碼裡 |

---

## 2. 前置條件

**★ 閘門 G1 已由產品負責人通過**（甲段驗收 ＋ 明示「可以開始花 AWS 資源」）。
沒過的話 Phase 82 之後全部停擺，本 phase 也不例外——但要注意：**本 phase 自己不打任何一行
AWS 指令、不花任何點數**，它排在這裡是因為端到端測試要用到 Phase 77〜81 做好的整條本機路。

**要先做完的 phase：**

| Phase | 本 phase 會用到它的什麼 |
|---|---|
| 77 | `cloud_ingest.CloudMailbox`（型別註記；**已含**工人端的 `receive_job`／`delete_job_message`，總覽 §2.4.1 註記「工人端（87）」）、`MailboxMessage`、`CloudRoute`、`tests/fakes.py` 的 `FakeMailbox`（含呼叫流水帳 `calls: list[str]`，格式 `"put_object <key>"`，**空格分隔**）／`FakeProbe`、conftest 第五道安全網 `wire_fake_cloud` |
| 78〜81 | `gated_ingest.run_gated_ingest_job()`（端到端測試的本機那一端，含 PDF 逐頁配對） |
| 83 | `app/services/aws_mailbox.py`（Phase 88 的 `main()` 會用它建真信箱）。⚠ `MailboxMessage` **定義在 `cloud_ingest.py`**（Phase 77），`aws_mailbox.py` 是 import 它來用的——所以工人的型別註記也一律跟 `cloud_ingest` 要，不要繞道 |
| 86 | `dependencies.get_cloud_route()` 的 `assume` 分支（本 phase 不改它，但 Phase 88 的手動端到端要用） |

**開工前實查基線**（在專案根目錄執行）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc          # db 要 Up (healthy)，否則測試會一整片連線錯誤
pytest --collect-only -q | tail -1    # 預期：634 tests collected
pytest -q                             # 預期尾巴：634 passed，0 skipped
git branch --show-current             # 預期：main
```

> **開工基線 ＝ 634**（總覽 §9：543 起算，74〜86 累計 +91）。
> 本 phase 結束時應該是 **646**（+12）。
> 交錯做的話絕對數字會不一樣，**要對的是「本 phase 新增 12 顆」**，不是絕對值。

再確認四個前置模組真的存在（沒有就先回去做對應的 phase，**不要在這裡自己補一個**）：

```bash
python -c "
from app.services import aws_mailbox, cloud_ingest, gated_ingest
from app.services.cloud_ingest import MailboxMessage
from tests.fakes import FakeMailbox, FakePrivacyGate, FakeProbe
print('cloud_ingest OK：', [n for n in ('CloudRoute','CloudRouteOff','AlwaysRunning','build_context') if hasattr(cloud_ingest, n)])
print('gated_ingest OK：', hasattr(gated_ingest, 'run_gated_ingest_job'))
print('MailboxMessage 欄位：', list(MailboxMessage.__dataclass_fields__))
print('FakeMailbox 方法：', [n for n in ('put_object','get_object','delete_objects','send_job','receive_job','delete_job_message','send_result','receive_result','input_key','context_key','result_key') if hasattr(FakeMailbox(), n)])
信箱 = FakeMailbox(); 信箱.put_object(信箱.result_key('job-1'), b'{}', 'application/json'); 信箱.send_result('job-1')
print('流水帳格式：', 信箱.calls)
"
```

預期前四行都印出完整清單；`MailboxMessage 欄位` 要是 `['job_id', 's3_key', 'receipt_handle']`；
第五行要是 `流水帳格式： ['put_object documents/job-1/result.json', 'send_result job-1']`
（**方法名＋一個空格＋參數**——本 phase 的順序斷言就是照這個格式寫的，步驟 1 會再講一次）。

> ⚠️ **絕對不要同時跑兩份 pytest**（兩個終端機、或人跑一份 agent 跑一份）。
> `reset_tables` 每顆測試都會 `TRUNCATE` 同一個測試庫，兩份同時跑會互相清掉對方的資料，
> 症狀是**大量看似隨機的** 404 與 `TypeError: 'NoneType' object is not subscriptable`，
> 而且每次紅的顆數都不一樣——看起來像程式壞了，其實只是撞在一起。

---

## 3. 範圍

### 做

1. 新建 `app/workers/__init__.py`：只有 docstring，說明「這個套件是什麼、為什麼不放 `scripts/`」。
2. 新建 `app/workers/cloud_worker.py`：
   - `CONTENT_TYPE_BY_SUFFIX`、`RESULT_CONTENT_TYPE`、`PDF_PAGE_CONTENT_TYPE` 三個模組常數
   - `content_type_from_key(s3_key) -> str | None`（純函式）
   - `read_context(mailbox, job_id) -> tuple[list, list, list]`
   - `_understand_with_retries(...)`（看圖最多 `config.VLM_MAX_ATTEMPTS` 次，**沒有轉向量**）
   - `build_image_result(...)` / `build_pdf_result(...)`（`result.json` 的兩種形狀）
   - `_process_pdf(...)`（逐頁；拆不開 → `pages` 是空清單）
   - `process_job_message(mailbox, message, vlm)`（六條規則＋順序鐵律）
3. 新建 `tests/unit/test_cloud_worker_unit.py`（10 顆）。
4. 新建 `tests/integration/test_cloud_roundtrip.py`（2 顆端到端）。

（`tests/fakes.py` **零改動**：順序斷言用的呼叫流水帳 `FakeMailbox.calls` 是 Phase 77 依總覽 §2.4.5
做好的，本 phase 只用不改。）

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 主迴圈 `run_forever()`／`main()`／SIGTERM／`python -m` | **Phase 88**。本 phase 要的是「一則訊息怎麼處理」這件事被測到爆，迴圈只是把它包起來 |
| 連真的 S3／SQS | 本 phase 一顆真 AWS 呼叫都沒有。真 AWS 是 Phase 88 的人工端到端 |
| 在工人裡算 embedding | design6 D13：向量必須與庫裡既有的 bge-m3 同源。`result.json` 連 `embedding` 這個鍵都沒有 |
| 在工人裡寫 Postgres、import `photo_repository` | design6 D11。有一顆 `ast` 掃碼測試在守 |
| 在工人裡再跑一次 Privacy Gate | 閘門只在本機、只在檔案出機房**之前**跑一次（D2）。檔案都已經在 S3 了，再問一次沒有任何意義 |
| 三次看不懂之後叫本機重看 | 總覽 §10 追認項 g：遠端明明活著，只是 AI 看不懂——本機再看三次多半一樣，而且會把「3 次」變成「6 次」 |
| 用 `head_object` 輪詢 S3 當完成訊號 | design6 §1.2 第 4 列已否決（方案 A）。工人**主動** SendMessage，本機才不必輪詢 |
| 把工人拆好的每頁 PNG 存回 S3 | 總覽 §10 追認項 F：本機自己再 `render_pages()` 一次。存回去會讓 S3 物件數隨頁數暴增，而拆頁是純 CPU、幾百毫秒的事 |
| 改 `app/services/cloud_ingest.py` 或 `gated_ingest.py` | 那是 Phase 77〜81 的檔案。本 phase 動它，就會變成「兩個 phase 一起改同一條路」，出問題時分不出是誰 |
| 另立一個「工人專用」的信箱 Protocol、或改 `CloudMailbox` | Phase 77 的 `CloudMailbox` **一份 Protocol 就涵蓋本機端＋工人端**：`receive_job`／`delete_job_message` 都在裡面（總覽 §2.4.1 註記「工人端（87）」），`AwsMailbox` 與 `FakeMailbox` 也都實作了。工人直接拿它做型別註記（放 `TYPE_CHECKING` 底下，執行時不載入） |
| 幫工人加設定檔、加 CLI 參數、加健康檢查端點 | design6 D11「無公開 HTTP、無網站、無公網 API」。設定一律走 `.env` → `config` |
| 動 `Dockerfile`／`compose.yaml` | **Phase 90**。本增量 `compose.yaml` 全程零改動（總覽 §7 鐵律 11） |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：步驟 1 確認假信箱的流水帳、步驟 2 建套件 → 步驟 3 寫**會紅**的 12 顆測試 →
> 步驟 4 真的跑它、親眼看到紅 → 步驟 5 寫實作 → 步驟 6 轉綠 → 步驟 7 全量回歸 →
> 步驟 8 ruff → 步驟 9 commit。
> 「跑它確認紅」不可以跳過——沒看過紅的測試，你不知道它有沒有在測東西。

### - [ ] 步驟 1：確認假信箱的呼叫流水帳（Phase 77 已經做好，本 phase 只用不改）

**為什麼要先看它：** 本 phase 最重要的一條規則是**順序**——`result.json` 一定要先落地，
才准發 results 訊息（design6 D9）。順序寫反不會有任何錯誤訊息，只會偶爾出現
「本機被叫醒去拿一個還沒寫完的檔案」這種最難查的壞法。
整數計數器（`put_calls`／`send_result_calls`…）只數「幾次」，數不出「誰先誰後」，
所以 Phase 77 建 `FakeMailbox` 時就多給了它一本按時間排的流水帳 `calls: list[str]`
（總覽 §2.4.5），Phase 79 的「submit 順序 context→input→jobs」測試已經在用它。

**格式是 Phase 77 定的契約，本 phase 的測試斷言照抄**：每個方法被叫一次就 append 一行，
**方法名、一個空格、參數**（沒有冒號）：

| 方法 | 流水帳裡的那一行 |
|---|---|
| `put_object(key, body, content_type)` | `"put_object documents/job-1/result.json"` |
| `get_object(key)` | `"get_object documents/job-1/input.png"` |
| `delete_objects(keys)` | `"delete_objects 5"`（記的是**幾個**鍵，不是鍵名） |
| `send_job(job_id, s3_key)` | `"send_job job-1"` |
| `receive_job(wait_seconds)` | `"receive_job"` |
| `delete_job_message(receipt_handle)` | `"delete_job_message"` |
| `send_result(job_id)` | `"send_result job-1"` |
| `receive_result(wait_seconds)` | `"receive_result"` |
| `delete_result_message(receipt_handle)` | `"delete_result_message"` |
| `release_result_message(receipt_handle)` | `"release_result_message"` |
| `instance_state(instance_id)` | `"instance_state i-0123"` |

驗一下（在專案根目錄）：

```bash
python -c "
from tests.fakes import FakeMailbox
信箱 = FakeMailbox()
信箱.put_object(信箱.result_key('job-1'), b'{}', 'application/json')
信箱.send_result('job-1')
print(信箱.calls)
"
```

預期印出：`['put_object documents/job-1/result.json', 'send_result job-1']`。

印出來不是這個樣子（中間是冒號、鍵名不對、或根本沒有 `calls` 這個屬性）＝ Phase 77 沒照總覽 §2.4.5 做，
**回去修 Phase 77**；不要在本 phase 動 `tests/fakes.py`（本 phase 對它零改動，步驟 7 的 `git diff` 會驗）。

### - [ ] 步驟 2：建立 `app/workers/` 套件

```bash
mkdir -p app/workers
```

新建 `app/workers/__init__.py`，**完整內容**如下（只有 docstring，沒有任何程式碼）：

```python
"""在**別台機器**上跑的行程（目前只有一支：雲端看圖工人 `cloud_worker`）。

【為什麼是 `app/workers/`，不是 `scripts/`】
`.dockerignore`（design4 §8.5 建的檔）把 `scripts/` 整個排除在映像之外：
那些是 host 手動跑的小工具，不必進容器。而工人**一定要進映像**——它就是 EC2 上
唯一要跑的東西。放 `scripts/` 的話 `docker build` 會成功、映像也起得來，
然後在 `python -m app.workers.cloud_worker` 那一刻才 `ModuleNotFoundError`：
**安靜地壞掉**，而且要等到人已經開了一台 EC2 才會發現（總覽 §10 追認項 k）。

【為什麼不放 `app/services/`】
`services/` 底下是「被 app 這個行程呼叫的東西」。工人是**另一個行程的進入點**
（`python -m app.workers.cloud_worker`），身分與 `app/celery_app.py` 相同。
放在自己的套件裡，那顆「工人不准 import 資料庫／Celery／Redis」的掃碼測試
才有一個明確、不會誤傷別人的掃描範圍。

【本套件底下的模組不得 import 的東西】（design6 D11、D13）
`app.repositories`、`app.db`、資料庫驅動程式（那個套件名刻意不寫：design3 的掃碼對 app/ 全樹做子字串比對，註解也算）、`celery`、`redis`。
工人不寫 Postgres、不算 embedding、不碰佇列框架——它只看圖，然後把結果放回寄物櫃。
"""
```

驗一下：

```bash
python -c "import app.workers; print(app.workers.__doc__.splitlines()[0])"
```

預期印出：`在**別台機器**上跑的行程（目前只有一支：雲端看圖工人 `cloud_worker`）。`

### - [ ] 步驟 3：先寫會紅的測試

#### 3a. `tests/unit/test_cloud_worker_unit.py`（10 顆）

新建這個檔案，**完整內容**如下：

```python
"""雲端看圖工人的單元測試（Phase 87；design6 D9／D11／D12／D13／D17、總覽 §2.6）。

這一層完全不碰網路、不碰資料庫、不碰 Celery：
信箱是 tests/fakes.py 的 FakeMailbox（一顆假件同時扮演 S3 ＋ 兩條佇列），
看圖是 FakeVLM／ScriptedVLM。所以這 10 顆跑起來是毫秒等級，而且**永遠不會**
連到真 AWS（就算第五道安全網漏接，boto3 也只會撞死埠）。

刻意的兩條規矩：
1. 訊息一律**從假佇列拿**（send_job → receive_job），不自己 new 一個 MailboxMessage。
   這樣 receipt_handle 是假信箱自己發的，delete_job_message 才對得起來——
   與正式路徑（Phase 88 的主迴圈也是 receive_job 拿的）長得一模一樣。
2. 每一顆會看圖的測試都**同時斷言呼叫次數**（vlm.calls == N）。
   只看 result.json 的內容不夠：「多打了一次模型」是這裡最需要抓的錯。
3. 順序斷言用假信箱的呼叫流水帳 calls（Phase 77 定的格式：方法名＋一個空格＋參數，
   例如 "send_result job-1"）。照步驟 1 印出來的樣子寫，不要自己猜格式。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.core import config
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.fakes import FakeMailbox, FakeVLM, ScriptedVLM, make_pdf_bytes, make_png_bytes

專案根目錄 = Path(__file__).resolve().parents[2]

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)

看不懂 = PhotoUnderstanding(understood=False)


def 準備一則工作(
    信箱: FakeMailbox,
    job_id: str = "job-1",
    *,
    content_type: str = "image/png",
    payload: bytes | None = None,
    s3_key: str | None = None,
):
    """把「本機送出」那一段用假信箱重演一次，回傳工人收到的那則訊息。

    payload 給 None ＝ 這次刻意不放 input 檔（測「input 不在」那條路）。
    s3_key 給值 ＝ 不用 input_key() 算，直接塞一個怪鍵名（測副檔名認不得那條路）。
    """
    鍵 = s3_key if s3_key is not None else 信箱.input_key(job_id, content_type)
    if payload is not None:
        信箱.put_object(鍵, payload, content_type)
    信箱.send_job(job_id, 鍵)
    訊息 = 信箱.receive_job(0)
    assert 訊息 is not None, "假信箱應該要收得到剛剛送進去的那一則"
    return 訊息


def 讀回result(信箱: FakeMailbox, job_id: str = "job-1") -> dict:
    """把工人寫進假信箱的 result.json 解回 dict。"""
    原始 = 信箱.objects[信箱.result_key(job_id)]
    return json.loads(原始.decode("utf-8"))


# ---------------- 順序鐵律（design6 D9）----------------


def test_result先PutObject才SendMessage():
    """result.json 一定要先落地，才准發 results 訊息，最後才刪 jobs 訊息。

    反過來的話，本機會被叫醒去拿一個還沒寫完（或根本不存在）的檔案——
    那是最難查的一種壞法：安靜地拿到半截 JSON。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=make_png_bytes())

    cloud_worker.process_job_message(信箱, 訊息, FakeVLM(收據理解))

    順序 = 信箱.calls
    放結果 = 順序.index(f"put_object {信箱.result_key('job-1')}")
    送通知 = 順序.index("send_result job-1")
    刪訊息 = 順序.index("delete_job_message")
    assert 放結果 < 送通知 < 刪訊息, f"順序不對：{順序}"


# ---------------- 看圖與重試 ----------------


def test_看圖三次都失敗_result標understood_false而且attempts是3():
    """看不懂與呼叫失敗都各算一次，共 config.VLM_MAX_ATTEMPTS 次（design5 D10 的規則沿用）。

    工人**不會**因此叫本機重看一次（總覽 §10 追認項 g）：遠端明明活著，
    只是 AI 看不懂，本機再看三次多半一樣。它照樣把 understood=false 寫出去，
    由本機收到之後標 failed、清 S3。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=make_png_bytes())
    看圖 = ScriptedVLM([看不懂, RuntimeError("雲端 401"), 看不懂])

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 3, "上限沒守住"
    結果 = 讀回result(信箱)
    assert 結果["kind"] == "image"
    assert 結果["understood"] is False
    assert 結果["attempts"] == 3
    assert 結果["understanding"] is None
    # 失敗也照樣走完順序鐵律：不刪訊息的話它每 900 秒就回來一次
    assert 信箱.calls.count("delete_job_message") == 1


def test_一次就成功_attempts是1():
    """看得懂就不再看第二次；九個欄位原樣進 result.json，而且**沒有** embedding。"""
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=make_png_bytes())
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 1
    結果 = 讀回result(信箱)
    assert 結果["understood"] is True
    assert 結果["attempts"] == 1
    assert 結果["understanding"]["text"] == 收據理解.text
    assert 結果["understanding"]["items"] == ["可樂", "洋芋片"]
    assert 結果["job_id"] == "job-1"
    assert 結果["worker_version"] == config.WORKER_VERSION
    # D13：向量一律本機算，工人的產出裡不可以有任何向量
    assert "embedding" not in json.dumps(結果)


# ---------------- 冪等（design6 D17）----------------


def test_result已存在時不看圖只補送results並刪jobs訊息():
    """至少送一次：同一則 jobs 訊息可能被送兩次。

    第二次要**完全不看圖**（看圖是要花錢的），也不可以蓋掉已經寫好的 result.json
    ——本機可能正在讀它。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=make_png_bytes())
    既有結果 = b'{"job_id": "job-1", "kind": "image", "understood": true}'
    信箱.put_object(信箱.result_key("job-1"), 既有結果, "application/json")
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 0, "重送不可以再看一次圖"
    assert 信箱.objects[信箱.result_key("job-1")] == 既有結果, "既有的 result.json 被蓋掉了"
    assert 信箱.calls.count("send_result job-1") == 1, "還是要補送一則 results 叫醒本機"
    assert 信箱.calls.count("delete_job_message") == 1


def test_input不在時只刪jobs訊息什麼都不寫():
    """input 不在了 ＝ 本機已經逾時 fallback、自己看完圖入庫、並把 S3 清乾淨了。

    這時候**寫任何東西都是有害的**：多一份 result.json，下一次重送就會以為
    「有結果可用」而去補送 results，把本機叫醒去處理一張早就入庫的照片。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=None)  # 刻意不放 input
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 0
    assert 信箱.result_key("job-1") not in 信箱.objects, "什麼都不該寫"
    assert 信箱.calls.count("send_result job-1") == 0
    assert 信箱.calls.count("delete_job_message") == 1, "訊息一定要刪，不然每 900 秒回來一次"


# ---------------- context.json ----------------


def test_context缺檔時三份清單都當空的():
    """沒有 context.json 不是失敗：少了資料夾清單只是少了「建議收進哪個資料夾」，
    照片內容照樣看得懂。三份清單都當空的，prompt 照樣組得出來。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=make_png_bytes())  # 沒有放 context.json
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.last_folders == []
    assert 看圖.last_entities == []
    assert 看圖.last_corrections == []
    # 有 context.json 時三份清單原樣傳進去這件事，由端到端那兩顆負責驗
    # （tests/integration/test_cloud_roundtrip.py，那裡的 context 是真的從資料庫來的）


# ---------------- 從 s3_key 推 content_type ----------------


def test_content_type由s3_key的副檔名推出來():
    """工人只拿得到一個鍵名字串，必須自己還原「這是 JPEG、PNG 還是 PDF」。

    推不出來時**不要亂猜**：把一份 .txt 當成 JPEG 送去看圖，錯誤會在很後面
    才以「AI 看不懂」的樣子出現。認不得就刪掉訊息（留著它只會每 900 秒回來一次）。
    """
    assert cloud_worker.content_type_from_key("documents/a/input.jpg") == "image/jpeg"
    assert cloud_worker.content_type_from_key("documents/a/input.png") == "image/png"
    assert cloud_worker.content_type_from_key("documents/a/input.pdf") == "application/pdf"
    assert cloud_worker.content_type_from_key("documents/a/input.txt") is None
    assert cloud_worker.content_type_from_key("documents/a/input") is None

    # 認不得的鍵名走到 process_job_message：不看圖、不寫東西、只把訊息刪掉
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, payload=b"x", s3_key="documents/job-1/input.txt")
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 0
    assert 信箱.result_key("job-1") not in 信箱.objects
    assert 信箱.calls.count("delete_job_message") == 1


# ---------------- PDF ----------------


def test_PDF拆不開時pages是空清單():
    """壞檔／加密／零頁 → pages 是空清單，**不丟例外**。

    工人照樣把 result.json 寫出去、照樣刪訊息（不然它會一直重送）；
    本機收到空清單之後依既有規則把整筆標成「這份 PDF 讀不開或沒有內容」。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, content_type="application/pdf", payload=b"this is not a pdf")
    看圖 = FakeVLM(收據理解)

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 0, "拆不開就不該送任何一次模型"
    結果 = 讀回result(信箱)
    assert 結果["kind"] == "pdf"
    assert 結果["pages"] == []
    assert 信箱.calls.count("send_result job-1") == 1


def test_PDF每一頁各自最多三次():
    """重試單位是「一頁」，不是整份檔（沿用 design5 D12 的既有語意）。

    第 1 頁一次就過（1 次），第 2 頁三次都失敗（3 次）＝總共 4 次呼叫。
    劇本只寫 4 張卡：多打一次模型就會 AssertionError，這正是我們要抓的錯。
    """
    信箱 = FakeMailbox()
    訊息 = 準備一則工作(信箱, content_type="application/pdf", payload=make_pdf_bytes(pages=2))
    看圖 = ScriptedVLM([收據理解, 看不懂, 看不懂, RuntimeError("雲端逾時")])

    cloud_worker.process_job_message(信箱, 訊息, 看圖)

    assert 看圖.calls == 4
    結果 = 讀回result(信箱)
    assert 結果["kind"] == "pdf"
    assert [頁["page"] for 頁 in 結果["pages"]] == [1, 2]
    assert 結果["pages"][0]["understood"] is True
    assert 結果["pages"][0]["attempts"] == 1
    assert 結果["pages"][0]["understanding"]["text"] == 收據理解.text
    assert 結果["pages"][1]["understood"] is False
    assert 結果["pages"][1]["attempts"] == 3
    assert 結果["pages"][1]["understanding"] is None


# ---------------- 掃碼：工人碰不到的東西 ----------------


def test_工人不import資料庫與Celery與Redis():
    """design6 D11／D13：工人只看圖，不寫 Postgres、不算 embedding、不碰佇列框架。

    用 ast 解析真正的 import 名單，不用 grep——grep 會誤中註解與 docstring
    （工人模組的 docstring 刻意寫成「不 import 資料庫驅動程式」——不能把 psycopg 這幾個字母寫進
    app/ 底下任何檔案，design3 的 SQL 掃碼對 app/ 全樹做子字串比對，連註解也算）。
    """
    原始碼 = (專案根目錄 / "app" / "workers" / "cloud_worker.py").read_text(encoding="utf-8")
    樹 = ast.parse(原始碼)

    # 記「完整的點分名稱」：from app.services import ai_timing → app.services.ai_timing。
    # 只記 節點.module（＝app.services）的話，下面的白名單分不出 ai_timing 與 ingest_job，
    # 而且 app.services 本身不在白名單裡，測試會對著正確的實作一直紅。
    匯入的: set[str] = set()
    for 節點 in ast.walk(樹):
        if isinstance(節點, ast.Import):
            匯入的.update(別名.name for 別名 in 節點.names)
        elif isinstance(節點, ast.ImportFrom) and 節點.module:
            匯入的.update(f"{節點.module}.{別名.name}" for 別名 in 節點.names)

    禁止 = ("psycopg", "redis", "celery", "sqlalchemy", "app.db", "app.repositories")
    違規 = sorted(名 for 名 in 匯入的 for 前綴 in 禁止 if 名 == 前綴 or 名.startswith(前綴 + "."))
    assert 違規 == [], f"工人不可以 import 這些：{違規}"

    # 正面表列：工人只准碰這幾個自家模組（總覽 §2.6 最後一行）。
    # cloud_ingest 是型別註記用的（TYPE_CHECKING，執行時不載入）；
    # aws_mailbox 先放進白名單，因為 Phase 88 的 main() 會在函式裡 import 它建真信箱
    # （ast.walk 連函式裡的 import 也看得到，所以現在就要放行）。
    允許的自家模組 = {
        "app.core.config",
        "app.services.ai_timing",
        "app.services.aws_mailbox",
        "app.services.cloud_ingest",
        "app.services.pdf_service",
        "app.services.vlm_service",
    }
    多出來的 = {
        名
        for 名 in 匯入的
        if 名.startswith("app")
        and not any(名 == 允 or 名.startswith(允 + ".") for 允 in 允許的自家模組)
    }
    assert 多出來的 == set(), f"工人多 import 了自家模組：{多出來的}"
```

#### 3b. `tests/integration/test_cloud_roundtrip.py`（2 顆端到端）

新建這個檔案，**完整內容**如下：

```python
"""端到端：本機送出 → 工人處理 → 本機收回入庫（Phase 87；design6 §9 必釘第 3 條）。

⚠ 名稱裡的「假工人」是沿用 Phase 79 的講法。**從本 phase 起它不再是假的**：
   處理訊息的是真正的 app/workers/cloud_worker.process_job_message()，
   假的只剩「信箱」（FakeMailbox 同時扮演 S3 ＋ 兩條佇列）與「看圖」（FakeVLM）。
   換句話說，這兩顆測試涵蓋的程式碼路徑，與 EC2 上真的跑起來時**完全相同**，
   差別只在 boto3 那一層被換掉了。

【怎麼安排先後】
run_gated_ingest_job() 是一條龍：送出 → 長輪詢等 results → 用結果落庫。
測試只有一條執行緒，如果不做任何事，wait_result() 會空等到逾時然後 fallback，
根本走不到雲端成功那條路。

做法：monkeypatch CloudRoute.wait_result，讓它「**先讓工人把 jobs 佇列清空，
再呼叫原本的 wait_result**」。這樣：
  - submit() 是真的（真的 PutObject 兩個物件、真的 SendMessage jobs）
  - process_job_message() 是真的
  - wait_result() 是真的（真的 ReceiveMessage results、真的 GetObject result.json）
  只有「工人在哪一個時間點動手」是我們安排的——而那件事在正式環境本來就是
  另一台機器上非同步發生的，測試沒有辦法、也不需要重現它的時序。

（另一個做法是讓 FakeMailbox 支援 on_send_job 回呼。不採用的理由：那會為了
 這兩顆測試在共用假件上多開一個只有這裡用得到的鉤子，而且「誰在什麼時候動手」
 會藏在 fakes.py 裡，讀測試的人看不到。）
"""

from __future__ import annotations

from datetime import datetime

from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, staging_service
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.conftest import 目前的任務清單
from tests.fakes import (
    FakeEmbeddings,
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    FixedClock,
    make_pdf_bytes,
    make_png_bytes,
)

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


def 讓工人在本機等結果之前先做完(monkeypatch, 信箱: FakeMailbox, 工人的看圖) -> None:
    """把「工人在另一台機器上做事」這件事插在 wait_result 之前（理由見檔頭）。"""
    原本的 = cloud_ingest.CloudRoute.wait_result

    def 先讓工人做一輪(self, job_id, *, store):
        訊息 = 信箱.receive_job(0)
        while 訊息 is not None:
            cloud_worker.process_job_message(信箱, 訊息, 工人的看圖)
            訊息 = 信箱.receive_job(0)
        return 原本的(self, job_id, store=store)

    monkeypatch.setattr(cloud_ingest.CloudRoute, "wait_result", 先讓工人做一輪)


def 上傳並拿到job_id(client, *, filename: str, payload: bytes, content_type: str) -> str:
    """走真的 HTTP 端點把檔案收下來（202），回傳 job_id。

    刻意不直接呼叫 staging_service／JobStore：入列的順序（先落 staging、
    再建 job、再派工）本身就是增量五的契約，端到端測試要連它一起走一遍。
    """
    回應 = client.post("/photos", files={"file": (filename, payload, content_type)})
    assert 回應.status_code == 202, 回應.text
    return 回應.json()["job_id"]


def 收件箱的照片() -> list[dict]:
    收件箱 = next(f for f in photo_repository.list_folders() if f["is_inbox"])
    return photo_repository.list_photos_in_folder(收件箱["id"])


def test_單圖端到端_本機送出_假工人處理_本機入庫(client, monkeypatch):
    信箱 = FakeMailbox()
    工人的看圖 = FakeVLM(收據理解)
    本機的看圖 = FakeVLM(收據理解)  # 雲端路走通的話，這一顆**一次都不該被呼叫**
    讓工人在本機等結果之前先做完(monkeypatch, 信箱, 工人的看圖)

    job_id = 上傳並拿到job_id(
        client, filename="receipt-2026.png", payload=make_png_bytes(), content_type="image/png"
    )

    gated_ingest.run_gated_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=本機的看圖,
        embeddings=FakeEmbeddings(),
        now=FixedClock(datetime(2026, 8, 18, 10, 0)),
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_ingest.CloudRoute(信箱, FakeProbe(True), timeout_seconds=5),
    )

    # ① 工人看了一次圖；本機一次都沒看（雲端路不重看圖，D13 只把 embedding 留在本機）
    assert 工人的看圖.calls == 1
    assert 本機的看圖.calls == 0

    # ② context.json 真的把本機資料庫裡的資料夾清單送到了工人手上
    #    （總覽 §10 追認項 a 的靠山：沒有它，工人組出來的 prompt 會少掉三段）
    assert len(工人的看圖.last_folders) == 6, "reset_tables 種了六筆資料夾，六筆都要送過去"
    assert "收據" in [資料夾["name"] for 資料夾 in 工人的看圖.last_folders]
    assert 工人的看圖.last_entities == []
    assert 工人的看圖.last_corrections == []

    # ③ 照片真的進了收件箱，內容是工人看出來的那一份
    照片們 = 收件箱的照片()
    assert len(照片們) == 1
    assert 照片們[0]["text"] == 收據理解.text

    # ④ 寄物櫃與兩條佇列都清乾淨了（input／context／result 三個物件都被刪）
    assert 信箱.objects == {}
    assert 信箱.jobs == []
    assert 信箱.results == []

    # ⑤ staging 刪了、job 也刪了（成功＝job 消失，與增量五同語意）
    assert not staging_service.staging_path(job_id, "image/png").exists()
    assert 目前的任務清單().get(job_id) is None


def test_PDF端到端_兩頁都回來_入庫兩列(client, monkeypatch):
    信箱 = FakeMailbox()
    工人的看圖 = FakeVLM(收據理解)
    讓工人在本機等結果之前先做完(monkeypatch, 信箱, 工人的看圖)

    job_id = 上傳並拿到job_id(
        client,
        filename="menu-2026.pdf",
        payload=make_pdf_bytes(pages=2),
        content_type="application/pdf",
    )

    gated_ingest.run_gated_ingest_job(
        job_id,
        store=目前的任務清單(),
        vlm=FakeVLM(收據理解),
        embeddings=FakeEmbeddings(),
        now=FixedClock(datetime(2026, 8, 18, 10, 0)),
        gate=FakePrivacyGate(Verdict.NON_SENSITIVE),
        cloud=cloud_ingest.CloudRoute(信箱, FakeProbe(True), timeout_seconds=5),
    )

    # 工人逐頁看：兩頁＝兩次呼叫（拆頁在工人那邊做，存檔用的 PNG 由本機自己再拆一次）
    assert 工人的看圖.calls == 2
    assert len(收件箱的照片()) == 2
    assert 信箱.objects == {}
    assert not staging_service.staging_path(job_id, "application/pdf").exists()
    assert 目前的任務清單().get(job_id) is None
```

### - [ ] 步驟 4：跑它，親眼看到紅

```bash
pytest tests/unit/test_cloud_worker_unit.py tests/integration/test_cloud_roundtrip.py -q
```

預期：**收集階段就失敗**，錯誤字樣是

```text
ImportError: cannot import name 'cloud_worker' from 'app.workers' (…/app/workers/__init__.py)
```

（`app/workers/__init__.py` 已經在了，所以 `app.workers` 這個套件找得到；找不到的是裡面的 `cloud_worker`。
兩個測試檔都寫 `from app.workers import cloud_worker`，Python 對「套件在、子模組不在」報的是
`ImportError: cannot import name …`，**不是** `ModuleNotFoundError`——看到後者代表連 `app/workers/`
都還沒建，回步驟 2。）

⚠ 若這裡出現的是 `ImportError: cannot import name 'FakeMailbox' from 'tests.fakes'`，
代表 Phase 77 還沒做完，**回去做完再回來**——不要在這裡自己補一個假信箱。

### - [ ] 步驟 5：寫實作

新建 `app/workers/cloud_worker.py`，**完整內容**如下（本 phase 結束時這個檔就長這樣；
Phase 88 會在它後面再加主迴圈，**現有的函式一個字都不會改**）：

```python
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

【看圖固定走 Ollama Cloud】（design6 D12）
EC2 沒有 GPU、也不裝本機 Ollama。但「用哪個客戶端」是 main()（Phase 88）決定的，
process_job_message() 只收一個 VLMClient 參數——所以單元測試塞得進假件，
一顆真的模型呼叫都不會發生。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.core import config
from app.services import ai_timing, pdf_service, vlm_service

if TYPE_CHECKING:
    # 只給型別檢查與讀程式的人看，**執行時不會真的 import**。
    # 這樣「import app.workers.cloud_worker」不會把 AWS SDK 一起拉進來，
    # 單元測試（假信箱）因此完全不必碰 boto3。
    # ★ CloudMailbox（Phase 77，總覽 §2.4.1）一份 Protocol 涵蓋本機端＋工人端的全部操作：
    #   工人用到的 receive_job()／delete_job_message() 就在裡面（註記「工人端（87）」），
    #   AwsMailbox 與 FakeMailbox 兩個實作也都有，所以不必另立一個工人專用的 Protocol。
    # ⚠ MailboxMessage 也跟 cloud_ingest 要（它就**定義在那裡**，Phase 77）。
    #   aws_mailbox.py 是 import 它來用的，繞道那邊拿雖然也拿得到，
    #   但會讓「這個名字到底住在哪」變得不明確——一律回到定義的地方拿。
    from app.services.cloud_ingest import CloudMailbox, MailboxMessage

# 名字一定要是 __name__（＝app.workers.cloud_worker）：Phase 88 的 main() 把 handler
# 掛在「app」這個 logger 上，取成別的名字就不在 app.* 底下，終端機會一片安靜
logger = logging.getLogger(__name__)

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
#   那個模組會拉進 photo_repository（＝資料庫驅動程式），違反 D11。
#   兩行字的重複換一個「工人與資料庫零關係」的硬保證，很划算。
PDF_PAGE_CONTENT_TYPE = "image/png"


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
    小寫 = s3_key.lower()
    for 副檔名, content_type in CONTENT_TYPE_BY_SUFFIX.items():
        if 小寫.endswith(副檔名):
            return content_type
    return None


def read_context(mailbox: CloudMailbox, job_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    """把 context.json 讀回三份清單：資料夾、實體、最近的人工糾錯。

    這三份清單住在**本機的資料庫**裡，工人沒有資料庫可讀（D11），
    所以本機在送出時把它們一起寫進 documents/{job_id}/context.json
    （總覽 §10 追認項 a）。有了它，工人組出來的 prompt 與本機自己看圖時**逐字相同**。

    缺檔或內容壞掉 → 三份都當空清單，**不是失敗**：
    少了資料夾清單只是少了「建議收進哪個資料夾」，照片內容照樣看得懂。
    """
    原始 = mailbox.get_object(mailbox.context_key(job_id))
    if 原始 is None:
        logger.info("job %s：沒有 context.json，三份清單都當空的", job_id)
        return [], [], []
    try:
        內容 = json.loads(原始.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("job %s：context.json 解不開，三份清單都當空的", job_id, exc_info=True)
        return [], [], []
    return (
        list(內容.get("folders") or []),
        list(內容.get("entities") or []),
        list(內容.get("corrections") or []),
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
            # target 從 vlm 物件身上拿：正式的 OllamaCloudVLM 建構時就把
            # backend=cloud 與模型名記在 timing_target 上，所以工人的 log 會誠實地
            # 印 kind=vlm backend=cloud。不帶 target 的話 ai_timing 會退回讀
            # 這個行程的 config.AI_BACKEND——那永遠是預設的 "local"，log 會騙人。
            with ai_timing.log_ai("vlm", target=vlm_service.vlm_timing_target(vlm)) as 計時:
                understanding = vlm.understand(
                    image_bytes, content_type, folders, entities, corrections
                )
                if not understanding.understood or not understanding.text.strip():
                    計時.note = f"understood=false text_chars={len(understanding.text)}"
                    raise _NotUnderstood()
                計時.note = (
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
        頁面們 = pdf_service.render_pages(pdf_bytes)
    except pdf_service.PdfUnreadableError:
        logger.warning("job %s：PDF 拆不開，pages 回空清單", job_id, exc_info=True)
        return build_pdf_result(job_id, [])

    pages: list[dict] = []
    for 頁碼, 頁位元組 in enumerate(頁面們, start=1):
        understanding, attempts = _understand_with_retries(
            vlm,
            頁位元組,
            PDF_PAGE_CONTENT_TYPE,
            job_id=job_id,
            label=f"第 {頁碼} 頁",
            folders=folders,
            entities=entities,
            corrections=corrections,
        )
        pages.append(
            {
                "page": 頁碼,
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
        sum(1 for 頁 in pages if 頁["understood"]),
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
```

### - [ ] 步驟 6：跑新測試，看它轉綠

```bash
pytest tests/unit/test_cloud_worker_unit.py tests/integration/test_cloud_roundtrip.py -v
```

預期最後一行：`12 passed`。

### - [ ] 步驟 7：全量回歸

```bash
pytest -q
```

預期：**開工基線 ＋ 12**（＝646），全綠、0 skipped。
`app/services/` 一個字都沒改，所以基線內既有的每一顆都不該動：

```bash
git diff --stat app/services app/api app/core
```

預期：**無輸出**（本 phase 只新增 `app/workers/` 兩個檔與 `tests/` 兩個新檔；`tests/fakes.py` 也不動）。

再驗「零外部依賴」——三個死埠一起指，顆數要一模一樣：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

預期：顆數與上一行相同（埠 9 是保留的 discard 埠，本機一定沒人聽，
會立刻 connection refused 而不是卡住等逾時）。

### - [ ] 步驟 8：格式與 lint

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期兩句都沒有輸出（或印 `All checks passed!`）。要改檔就跑：

```bash
ruff format app tests scripts && ruff check --fix app tests scripts
```

改完再跑一次步驟 6，確認還是 12 綠。

### - [ ] 步驟 9：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/workers/__init__.py app/workers/cloud_worker.py \
        tests/unit/test_cloud_worker_unit.py \
        tests/integration/test_cloud_roundtrip.py
git commit -m "feat: Phase 87 雲端看圖工人核心——process_job_message() 六條規則（冪等、input 不在只刪訊息、context 缺檔當空清單、看圖三次、PDF 逐頁）＋順序鐵律 result→results→delete，假信箱端到端單圖與 PDF 各一，+12 tests"
```

> 📌 **commit 節奏由產品負責人決定**（總覽 §7 鐵律 12）。未指示前不要自己 commit，
> 也不要把 `unfinish/` 的計畫檔搬進 `finish/`。

---

## 5. ASCII 圖

### 5.1 工人處理一則訊息的六條規則（三個提早出口、一條主線）

```text
process_job_message(mailbox, message, vlm)
│
│   message ＝ {job_id, s3_key, receipt_handle}   ← 從 jobs 佇列拿到的紙條
│
├─① get_object(documents/{id}/result.json) 有東西？
│      有 ──▶ send_result(job_id) ──▶ delete_job_message ──▶ 【出口 A：重送，什麼都不做】
│             （D17 冪等：上一輪其實做完了，只是通知或刪訊息沒完成）
│      沒有
│       ▼
├─② content_type_from_key(s3_key) 認得嗎？（.jpg / .png / .pdf）
│      認不得 ──▶ delete_job_message ──▶ 【出口 B：壞紙條，刪掉免得每 900 秒回來】
│      認得
│       ▼
├─③ get_object(s3_key) 拿得到 input 嗎？
│      拿不到 ──▶ delete_job_message ──▶ 【出口 C：本機已 fallback，一個字都不准寫】
│      拿得到
│       ▼
├─④ context = get_object(documents/{id}/context.json)
│      沒有 ──▶ folders=[] entities=[] corrections=[]   （不是失敗）
│      有   ──▶ 三份清單原樣取出
│       ▼
├─⑤ 看圖（唯一會花錢的一步；ai_timing 每次都留前後兩行 kind=vlm backend=cloud）
│   │
│   ├─ 單圖：┌── for attempt in 1..VLM_MAX_ATTEMPTS(=3) ──────────────────┐
│   │        │  vlm.understand(bytes, ct, folders, entities, corrections) │
│   │        │    ├ understood=False 或 text 全空白 ─▶ 這次失敗 ──┐       │
│   │        │    ├ 丟例外（401／逾時／JSON 壞） ─────▶ 這次失敗 ──┤       │
│   │        │    └ 看得懂 ─▶ return (understanding, attempt) ────┼─ 跳出 │
│   │        │       第 1、2 次失敗 ─▶ continue ◀─────────────────┘       │
│   │        │       第 3 次失敗   ─▶ return (None, 3)                    │
│   │        └────────────────────────────────────────────────────────────┘
│   │        → build_image_result(job_id, understanding, attempts)
│   │
│   └─ PDF：render_pages(bytes)
│            ├ 拆不開 ─▶ pages = []           （本機收到會標「PDF 讀不開」）
│            └ 拆得開 ─▶ 每一頁各跑一次上面那個迴圈，逐頁記
│                        {page, understood, attempts, understanding}
│            → build_pdf_result(job_id, pages)
│       ▼
└─⑥ 順序鐵律（D9）── 這三行的先後不可以動 ──────────────────────────────
       put_object(documents/{id}/result.json, json)    ← 先讓結果落地
              │
              ▼
       send_result(job_id)                             ← 才准叫醒本機
              │
              ▼
       delete_job_message(receipt_handle)              ← 最後才把紙條撕掉
              │
              ▼
       【出口 D：做完了】
```

### 5.2 為什麼順序不能對調（把 send 放到 put 前面會怎樣）

```text
┌── ✗ 錯誤順序：先 SendMessage、再 PutObject ──────────────────────────────┐
│                                                                          │
│  工人  send_result(job_id) ─────────────┐                                │
│                                          │ 幾毫秒                        │
│  本機  ReceiveMessage results ◀──────────┘                               │
│        GetObject documents/{id}/result.json                              │
│              └─ 還沒寫！S3 回 NoSuchKey                                  │
│                 → 本機依規則當「工人說寫好了卻找不到」→ 回 None           │
│                 → 整筆 fallback 回本機重看一次圖                          │
│                                                                          │
│  工人  put_object(result.json)  ← 這時候才寫進去，但已經沒有人要看了      │
│        （而且它會留在 S3 上，等 Lifecycle 兩天後掃掉）                    │
│                                                                          │
│  結果：**功能看起來是好的**（照片還是入庫了，因為 fallback 有接住），      │
│        只是每一張都白白多花了一次雲端看圖的錢與一次本機看圖的時間。       │
│        而且它只在「網路剛好比較慢」的時候發生——最難查的那一種。          │
└──────────────────────────────────────────────────────────────────────────┘

┌── ✓ 正確順序：PutObject 成功之後才 SendMessage（design6 D9 原文）────────┐
│                                                                          │
│  工人  put_object(result.json)  ← S3 回 200 才算數                       │
│              │                                                           │
│              ▼                                                           │
│        send_result(job_id)                                               │
│              │                                                           │
│              ▼                                                           │
│  本機  ReceiveMessage results → GetObject → **一定拿得到**               │
│                                                                          │
│  最後才 delete_job_message：萬一 put 或 send 中間爆炸，那則 jobs 訊息     │
│  還在（只是隱形 900 秒），時間到自然重來一次——而重來會撞到規則①的       │
│  冪等檢查，所以不會重看圖。三件事的順序合起來才是完整的保險。            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 驗收清單

- [ ] **套件位置正確**（放錯地方會安靜地不進映像）：
      ```bash
      ls app/workers/__init__.py app/workers/cloud_worker.py
      grep -n "scripts/" .dockerignore
      ```
      預期兩個檔都在；`.dockerignore` 那行證明 `scripts/` 確實被排除（所以工人不能放那裡）
- [ ] **工人沒有 import 資料庫／Celery／Redis**：
      ```bash
      pytest tests/unit/test_cloud_worker_unit.py -k import -v
      ```
      預期 `1 passed`（用 `ast` 掃真正的 import 名單，不會誤中註解）
- [ ] **工人不算 embedding、不碰資料庫那一層**（只看真正的 import 敘述——docstring 與註解裡
      提到 `photo_repository` 這個名字不算，工人的 docstring 就寫著「不碰 photo_repository」）：
      ```bash
      grep -nE "^[[:space:]]*(from|import) .*(indexing_service|ingest_job|photo_repository|repositories|app\.db)" \
        app/workers/cloud_worker.py || echo "OK：工人不碰向量也不碰資料庫"
      ```
      預期印出 `OK：工人不碰向量也不碰資料庫`
- [ ] **順序鐵律接對了**（主線最後三行的先後）：
      ```bash
      grep -n "mailbox.put_object(result_key\|mailbox.send_result(job_id)\|mailbox.delete_job_message(message.receipt_handle)" app/workers/cloud_worker.py
      ```
      預期**最後三筆**依序是 `put_object(result_key` → `send_result(job_id)` → `delete_job_message(`；
      它們前面另外會出現規則①的 `send_result` 與三個提早出口的 `delete_job_message`，屬正常
- [ ] **重試上限只有一份**：
      ```bash
      grep -c "range(1, config.VLM_MAX_ATTEMPTS + 1)" app/workers/cloud_worker.py
      ```
      預期印出 `1`（單圖與 PDF 共用同一個迴圈）
- [ ] `pytest tests/unit/test_cloud_worker_unit.py -v` → `10 passed`
- [ ] `pytest tests/integration/test_cloud_roundtrip.py -v` → `2 passed`
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ 開工基線 ＋ **12**（＝646）
- [ ] **三死埠零依賴實證**（顆數與上一條相同）：
      ```bash
      AWS_ENDPOINT_URL=http://127.0.0.1:9 \
      CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
      OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
      ```
- [ ] **端點仍是 22**（本 phase 不碰任何 router）：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `22`
- [ ] **專案的 `data/` 沒有被弄髒**：
      ```bash
      find data/staging -type f 2>/dev/null | head; echo "---"
      ```
      預期 `---` 之前沒有輸出（`isolated_data_dir` 讓 pytest 全寫在暫存目錄）
- [ ] **規格區一字未動**：
      ```bash
      git status --short docs/spec/
      ```
      預期：零輸出
- [ ] **`app/services/` 與 `app/api/` 零改動**：
      ```bash
      git diff --stat app/services app/api app/core
      ```
      預期：無輸出
- [ ] `ruff format --check app tests scripts && ruff check app tests scripts` 兩句都乾淨

---

## 7. 常見陷阱

1. **把工人放進 `scripts/`，映像裡就沒有它——而且是安靜地沒有。**
   `.dockerignore`（design4 §8.5 建的檔）排除 `scripts/`。`docker build` 會成功、
   映像也起得來，`python -m scripts.cloud_worker` 那一刻才 `ModuleNotFoundError`。
   **症狀**：EC2 上 systemd 每隔幾秒重啟一次容器，log 只有一行 import 錯誤。
   **正解**：`app/workers/`，而且 `__init__.py` 的 docstring 已經把理由寫死在原始碼裡。

2. **先 `send_result` 再 `put_object`。**
   看起來只是兩行對調，實際後果見 §5.2：本機被叫醒去拿一個還沒寫完的檔案 →
   當成「工人說寫好了卻找不到」→ 整筆 fallback 回本機重看一次圖。
   **症狀**：功能正常（照片還是入庫了），但每一張都白白多花一次雲端＋一次本機的看圖，
   而且只在網路比較慢時才發生。
   **正解**：`put_object` → `send_result` → `delete_job_message`，順序寫死，測試釘住。

3. **`input` 不在時順手寫一份「失敗的 result.json」。**
   直覺上「記錄一下也好」，實際上是有害的：那份 result 會讓**下一次重送**撞到規則①，
   於是又 `send_result` 一次，把本機叫醒去處理一張早就入庫的照片。
   **正解**：input 不在＝本機已經自己做完了，**一個字都不要寫**，只刪訊息。

4. **在 `except Exception` 後面才寫 `except _NotUnderstood`。**
   Python 的 `except` 由上往下比對，順序反了不會壞掉，但每次「AI 說看不懂」都會印出
   一整段 traceback，真的壞掉時反而看不出來（與 `ingest_job.py` 同一個坑）。

5. **`ScriptedVLM` 的劇本長度寫錯，測試變成「不知道在測什麼」。**
   劇本寫 4 張而程式只呼叫 3 次 → 測試會綠，但根本沒驗到上限。
   所以每顆重試測試都**同時**斷言 `vlm.calls == N`。
   反過來（劇本 2 張、程式呼叫 3 次）會直接 `AssertionError: ScriptedVLM 被呼叫第 3 次…`
   ——那是好事，代表上限沒守住。

6. **流水帳的格式寫成冒號（`"send_result:job-1"`），測試在 `list.index` 那一行炸 `ValueError`。**
   `FakeMailbox.calls` 的格式是 Phase 77 定的：**方法名、一個空格、參數**
   （`"send_result job-1"`、`"put_object documents/job-1/result.json"`），Phase 79 的 submit 順序測試
   已經照這個格式在用。**症狀**：`ValueError: 'send_result:job-1' is not in list`，而把 `順序` 印出來
   明明看得到那一筆。**正解**：照步驟 1 印出來的樣子抄；不要為了配合自己的斷言去改 `tests/fakes.py`。

7. **在工人裡 `from app.services.ingest_job import PDF_PAGE_CONTENT_TYPE`「避免重複」。**
   那個模組會拉進 `photo_repository` ＝ `psycopg` ＝ 違反 D11，而且掃碼測試會立刻變紅。
   兩行字的重複換一個「工人與資料庫零關係」的硬保證，是本 phase 刻意做的取捨。

8. **測試裡自己 `new` 一個 `MailboxMessage` 塞進去。**
   那樣 `receipt_handle` 是你捏的，`delete_job_message` 對不上假信箱的內部帳。
   **正解**：一律 `send_job(...)` → `receive_job(0)`，與正式路徑（Phase 88 的主迴圈）
   拿訊息的方式一模一樣。

9. **端到端測試忘了 monkeypatch `wait_result`，然後看著它「卡住」。**
   其實不會卡很久——`timeout_seconds=5`，五秒後 fallback 回本機，測試會**綠**，
   但綠的原因是 fallback 成功，雲端那條路一次都沒走到（假綠）。
   **怎麼發現**：`工人的看圖.calls == 1` 這條斷言會變成 0。所以那條斷言不可以省。

10. **以為工人 log 的 `backend=cloud` 是 `config.AI_BACKEND` 決定的。**
    不是。工人是獨立行程，它的 `config.AI_BACKEND` 永遠是預設的 `"local"`
    （頁首那顆開關撥的是 **web 行程**記憶體裡的變數）。log 印得出 `backend=cloud`
    是因為 `OllamaCloudVLM` 自己帶著 `timing_target`，而 `_understand_with_retries`
    有把 `target=vlm_service.vlm_timing_target(vlm)` 傳進 `log_ai`。
    **把那個 `target=` 拿掉，Phase 88 的人工驗收就會一直看到 `backend=local`。**

11. **`docker compose ps` 沒看 `db` 就直接跑 pytest。**
    `db` 沒起來時，端到端那兩顆會紅在連線錯誤，看起來像「程式寫錯了」。
    先確認 `db` 是 `Up (healthy)`。

---

## 8. 完成後的專案狀態

系統多了一支**還沒有人會自己啟動**的工人程式 `app/workers/cloud_worker.py`——
它有完整的處理邏輯，但沒有主迴圈、也沒有 `python -m` 進入點（那是 Phase 88）。
現在只有測試會呼叫它。

已經被釘死的行為：順序鐵律（`result.json` → results → 刪 jobs 訊息）、
兩種冪等（result 已存在／input 不在）、看圖三次上限（單圖與 PDF 逐頁各自算）、
`context.json` 缺檔時三份清單當空的、`result.json` 的兩種形狀（image／pdf）、
以及「工人不 import 資料庫、Celery、Redis」這條掃碼防線。

**對外行為零改變**：`POST /photos` 仍是 202、`GET /ingest-jobs` 形狀不變、端點仍 22、
`compose.yaml` 一個字都沒動。`CLOUD_ROUTE` 預設仍是 `off`，所以日常操作完全沒有差別。

**與總覽的差異：** 新增測試 12 顆（單元 10 ＋ 端到端 2），名稱與總覽 §2.7 逐字相同；
`tests/fakes.py` **零改動**（順序斷言用的呼叫流水帳 `FakeMailbox.calls` 是 Phase 77 依總覽 §2.4.5
做好的，本 phase 只用）。唯一比總覽 §2.6 多的是一條防呆：**s3_key 認不得（欄位是空的、或副檔名
不是三種之一）→ 只刪訊息、不看圖、不寫東西**（規則②）。總覽的六步假設 s3_key 一定是本機用
`input_key()` 算出來的，沒說認不得時怎麼辦；留著那則訊息只會每 900 秒回來一次，所以刪掉並留 log。

**本 phase 做的一個小決定（寫在這裡，免得之後有人改來改去）：**
`MailboxMessage` 與 `CloudMailbox` 兩個型別註記，工人一律
`from app.services.cloud_ingest import CloudMailbox, MailboxMessage`，
而且放在 `if TYPE_CHECKING:` 底下。三個理由：
① **回到定義的地方拿**——`MailboxMessage` 就定義在 `cloud_ingest.py`（Phase 77），
`aws_mailbox.py` 只是 import 它來用；繞道那邊拿雖然也拿得到，但會讓「這個名字住在哪」
變得不明確。② 放 `TYPE_CHECKING` 底下，執行時完全不 import，
所以「`import app.workers.cloud_worker`」**不會把 AWS SDK 一起拉進來**——
10 顆單元測試用假信箱就跑得完，一次都不碰 boto3。
③ 工人因此也**不會**把 boto3 傳染給 `cloud_ingest`（總覽 §7 鐵律 5：boto3 只准在
`aws_mailbox.py`）。真正需要 SDK 的地方只有 Phase 88 的 `main()`，它把
`from app.services.aws_mailbox import AwsMailbox` 寫在函式**裡面**，同一個道理。

顆數：開工基線 ＋ **12** ＝ **646**（總覽 §9 的累計數字）。端點仍 **22**。

**下一個 phase：Phase 88** —— 幫這支工人加上主迴圈（`run_forever` ＋ SIGTERM ＋ 啟動 log）、
`python -m app.workers.cloud_worker` 進入點，然後在這台 Mac 上對著**真的** S3／SQS／
Ollama Cloud 跑一次端到端（丁段的驗收），並把操作步驟寫進 `LAUNCH.md` 與 `CLAUDE.md`。
之後 Phase 89（`Ec2Probe`）、Phase 90（arm64 映像）做完才輪到 **★G2**。

---

## 附：本文件引用的官方文件

- [SQS Standard Queue（at-least-once、可能重複）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)
- [SQS 可見度逾時（visibility timeout）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [SQS `DeleteMessage`（要用 receipt handle）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_DeleteMessage.html)
- [SQS 大訊息與 S3 pointer（為什麼位元組要走 S3）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
- [boto3 S3 client：`put_object`／`get_object`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [Python `ast` 模組（解析 import 名單用）](https://docs.python.org/3/library/ast.html)
- [Python `typing.TYPE_CHECKING`](https://docs.python.org/3/library/typing.html#typing.TYPE_CHECKING)
- [Pydantic `model_dump()`](https://docs.pydantic.dev/latest/concepts/serialization/)
- 專案內文件：`docs/design/design6.md`（D9／D11／D12／D13／D17、§2、§2.2、§8、§9）、
  `docs/plan/unfinish/phase-00-增量六總覽.md`（§2.4.1 簽章、§2.4.3 result.json、
  §2.4.5 假件、§2.6 工人規則、§2.7 本 phase 的測試清單、§10 追認項 a／g／k）
