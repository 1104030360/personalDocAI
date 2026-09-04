# Phase 86：真 AWS 雲端路接線（`assume` 模式 ＋ 逾時煙霧）

> 📌 **2026-09-02 校準紀錄**（ledger：`.superpowers/sdd/phase0902-1/progress.md` 的裁決 R0〜R7；
> 本檔已依 2026-09-02 工作樹 HEAD `a159131` 逐處校準過，照著做就會對）：
>
> | 裁決 | 落在本檔哪裡 |
> |---|---|
> | **R0** 不 commit、用工作樹快照相減審 | §4.10 從「commit」改成「**記快照**」（`.superpowers/sdd/phase0902-1/snapshot-tree`）；§6 最後一條改成核對 `git status --short` |
> | **R1** 識別字一律英文 | §4.1 的測試碼與 §4.3 的實作碼：`原本的get_cloud_route`→`real_get_cloud_route`、`設定成assume模式`→`configure_assume_mode`、`路`→`route`、`建構參數`→`captured`、`側錄CloudRoute`→`RecordingCloudRoute`、`模式`→`mode`、`信箱`→`mailbox`。**`test_…` 的中文名維持不變**（總覽 §2.7 逐字沿用）；log／錯誤訊息／註解／docstring 也維持中文 |
> | **R2** 顆數以 2026-09-02 實查為準 | 實查 `pytest --collect-only -q` ＝ **624**（不是舊文寫的 632）。Phase 83 +16 → **640 ＝ 本 phase 開工基線**；本 phase +2 → **收工 642**。§2.2／§2.3／§4.4／§6／§8 全部已改 |
> | **R3** AWS 操作由 controller 親自執行 | **§4.5〜§4.8 整段**（煙霧、purge、改 `.env`、restart）＋ §2.2 的 `aws_check.py` 那兩行 ＋ §6 帶 `aws`／`.env` 的條目，全部標了「⚠ 本步驟由 controller 親自執行」。實作 subagent **零 `aws` 指令、零真連線、不改 `.env`、不上傳任何東西** |
> | **R4** `scripts/aws_check.py` 不寫自動化測試 | 本檔只**引用**它（§2.2／§6），顆數 +0 不受影響 |
> | **R5** 煙霧程序 | ① 先 `open -a Ollama`（embeddings 一律本機，非開不可）② 頁首 AI 開關撥到 **cloud** 加速（閘門 0.7 秒、看圖 0.8 秒，取代本機的 1〜5 分鐘）③ 圖以**內容**判定敏感與否（§4.5 步驟 1、§4.6 各給一段 Pillow 產圖碼，已實測畫得出來）④ 做完把開關撥回 **local**、`.env` 改回 `off`／`300` 並 restart worker |
> | **R6** 不需要手機／真機 | 本 phase 零前端、零鏡頭 |
> | **R7** 只改本檔 | 顆數已由 controller 在總覽 §2.7 補上「實 642」＝與本檔一致。**仍待處理的跨檔過期點**：總覽 §2.7 Phase 86 那段煙霧描述與 §5.2 Demo 2 仍寫「檔名 `receipt-test.png`／`身分證.png`」「檔名要打中 Phase 74 的非敏感關鍵字 receipt」——閘門 2026-09-01 起**不看檔名**。屬跨檔問題、**不在本檔修**，由 controller 統一處理 |

> ⚠ **2026-09-01 改判（本檔最重要的一條）：隱私閘門不看檔名。**
> `app/services/privacy_gate.py` 的 `VlmGate.classify()` 第一行就是 `del filename`
> （契約：verdict 不得依賴檔名），判斷一律是「把圖縮到長邊 512 → 送 VLM 短問」。
> 所以煙霧要**用圖的內容**決定它走哪條路：
> 非敏感 ＝ 收據／菜單這類（§4.5 步驟 1 產一張 `RECEIPT／Target／Total` 的圖），
> 敏感 ＝ 證件／薪資單這類（§4.6 產一張 `NATIONAL ID CARD` 的圖）。
> **檔名叫什麼都不影響結果**；`Phase 74 的 NON_SENSITIVE_KEYWORDS／SENSITIVE_KEYWORDS`
> 這兩個名字在現行程式碼裡**已經不存在**，看到任何文件還這樣寫就是過期的。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做的六件事：
> ① **不要**順手把 `ec2` 那一支也做掉（那是 **Phase 89** 的 `Ec2Probe`，而且現在根本還沒有 EC2）；
> ② **不要**寫工人（`cloud_worker.py` 是 **Phase 87／88**）——本 phase 的煙霧**故意讓它沒人接**；
> ③ **不要**改 `gated_ingest.py`／`cloud_ingest.py`（那些在 Phase 78〜81 已經寫完並驗過了，本 phase 只是「把插頭插上」）；
> ④ **不要**把 `.env` 的 `CLOUD_ROUTE` 留在 `assume`——煙霧做完**一定要改回 `off`**（理由見 §4.8）；
> ⑤ **不要**動 `get_cloud_route()` 最後那行 `raise ValueError`（打錯字要當場炸是 Phase 77 釘死的**永久行為**，
>   不是暫時分支；本 phase 只換 `assume` 那一支）；
> ⑥ **不要**把頁首的「AI 模型」開關留在**雲端**——煙霧為了加速把它撥去雲端（§4.5 步驟 0），
>   §4.8 一定要撥回 `local`，否則之後每一次看圖都在燒 Ollama Cloud 的用量（§7 陷阱 14）。

> 🎯 **一句話目標：** 把 `app/dependencies.py` 的 `get_cloud_route()` 補上 `assume` 這一支
> （建一個真的 `AwsMailbox` ＋ `AlwaysRunning` 探測 ＋ 從 config 讀逾時秒數），
> 加 **2 顆**單元測試；然後做一次**故意讓它逾時**的真 AWS 煙霧——
> 沒有任何工人在跑，30 秒後 fallback 回本機入庫、S3 被清乾淨、
> worker 的 log 出現 `fallback=local reason=result_timeout`。
> **這一步驗的正是「雲端壞掉時使用者無感」，比「雲端成功」更重要。**

**為什麼要做這個：**

到 Phase 85 為止，所有零件都齊了：

| 零件 | 誰做的 | 現在的狀態 |
|---|---|---|
| 隱私閘門（三分類） | Phase 74／75 | ✅ 已接在 Celery 開頭 |
| fallback 契約（四種 reason） | Phase 78／79／80 | ✅ 已寫完、已測過（用假信箱） |
| 雲端路流程（送出／等結果／清理） | Phase 77／79／80／81 | ✅ 已寫完、已測過（用假信箱） |
| `AwsMailbox`（真的打 AWS） | Phase 83 | ✅ 已寫完、已測過（用 stub client） |
| S3 寄物櫃 | Phase 84 | ✅ 已建好 |
| 兩條 SQS 佇列 | Phase 85 | ✅ 已建好 |
| **把它們接起來** | **★ 本 phase** | ❌ **還沒有** |

`get_cloud_route()` 到現在為止**只認 `off`**——不管 AWS 那邊多完整，程式永遠拿到一個
「遠端不可用」的物件，所以一張照片都不會出門。本 phase 就是把那條線接上。

**為什麼第一次煙霧要故意讓它失敗：**

因為 design6 的整個設計，最重要的性質不是「雲端會成功」，而是
**「雲端不成功的時候，使用者完全感覺不到」**（D10、§0 禁止第 6 條、§8 錯誤表第 5 列）。

而現在的狀況剛好是**天然的失敗情境**：東西送得出去（S3、SQS 都是真的），
但**另一頭沒有人**（工人是 Phase 87／88 才有）。
所以我們把逾時從 300 秒調成 30 秒，上傳一張非敏感的圖，然後看：

```text
   202 收下  →  閘門說 NON_SENSITIVE  →  送 S3 ＋ 送 jobs 佇列
                                              │
                                     等 results…（30 秒，沒有人回）
                                              │
                                     fallback=local reason=result_timeout
                                              │
                     ← 用 staging 裡那個檔，走完全一樣的本機入庫流程 →
                                              │
                              照片進待決定牆、S3 被清乾淨、job 被刪掉
```

使用者看到的東西：**202、進度面板、待決定牆——與增量五逐字相同。**
唯一的差別在 worker 的 log 多了兩行。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **`CLOUD_ROUTE=assume`（假設模式）** | 「假設遠端一定開著，不要浪費時間去問」。它**不做任何探測**，`available()` 永遠回 `True`。給階段丁（工人在 Mac 上跑）與除錯用；日常要用 `ec2`（總覽 §10.1 追認項 l） |
| **`AlwaysRunning`** | 實作上面那個「假設」的小類別（Phase 77 寫的）：`is_running()` 永遠回 `True`，一次 AWS API 都不打 |
| **探測（probe）** | 「遠端可用嗎」的判斷器。本專案有兩種：`AlwaysRunning`（假設開著）與 `Ec2Probe`（真的去問 `DescribeInstances`，Phase 89 才做） |
| **`CLOUD_RESULT_TIMEOUT_SECONDS`** | 送出之後最多等 results 佇列幾秒。到了還沒收到就 fallback（D10 第 4 條）。預設 **300**（5 分鐘）；本 phase 的煙霧暫時調成 **30**，才不必等五分鐘 |
| **`fallback=local reason=…`** | worker log 裡的**契約字樣**（design6 §2.1 明文）。四種 reason：`remote_unavailable`（探測說不在）、`submit_failed`（送出失敗）、`result_timeout`（等不到結果）、`redelivered_without_result`（崩潰重送但 S3 上沒有結果）。Phase 78〜80 的測試用 `caplog` 釘住這些字 |
| **注入點（injection point）** | 「不要自己去 new 一個物件，而是讓外面把它遞給你」的那個「外面」。本專案集中在 `app/dependencies.py`，`get_cloud_route()` 就是其中一個。換實作只改這一支，呼叫端（`celery_app.ingest_task`）一個字都不必動 |
| **早綁定（early binding）** | `from app.dependencies import get_cloud_route` 這種寫法會在 **import 當下**就抓住那個函式物件，之後別人用 `monkeypatch` 換掉模組屬性也影響不到它。本 phase 的測試**刻意**利用這一點來取得「沒有被安全網換掉的原版」（見 §4.1 的框） |
| **第五道安全網 `wire_fake_cloud`** | Phase 77 加的 autouse fixture：把 `config.CLOUD_ROUTE` 蓋成 `"off"`、把 `get_cloud_route` 換成 `CloudRouteOff()`、把 `AWS_ENDPOINT_URL` 指到死埠。**pytest 絕不連真 AWS** 就是靠它 |
| **煙霧測試（smoke test）** | 「開機冒不冒煙」——用真的東西跑一次最短的完整路徑，看有沒有起火。它**不是**自動化測試，是人手動做一次、看輸出（本專案已有 `scripts/check_embedding_dim.py` 這個前例） |

---

## 1. 對應 design6.md 章節

| design6 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **D10**（遠端關掉＝fallback 本機） | 五種情況任一成立就走 `run_ingest_job`；**不上傳失敗、不要求重傳**；log 明寫 `fallback=local reason=…` | §4.5 的煙霧就是第 4 種（「已送出，但逾時內 results 沒有該 `job_id`」）的真機重現 |
| **§2.1 Fallback 契約** | 四種「遠端不可用」＋盡力清乾淨＋log 字樣＋**禁止再跑一次 classifier** | §4.5 步驟 6〜8：log 有那一行、S3 被清空、照片照樣入庫 |
| **§8 錯誤表第 5 列** | 已送雲端、逾時無 results 訊息 → fallback 本機；冪等避免雙 INSERT | §4.5 步驟 9：`photo` 表只多一列 |
| **§8 錯誤表第 1 列** | 敏感／不確定 → 本機入庫；**零 S3／jobs／results** | §4.6 的敏感檔煙霧 |
| **§0 禁止第 6 條** | 遠端不可用時上傳**不准**改 5xx、不准讓使用者重傳 | §4.5 步驟 4：`POST /photos` 仍然是 **202** |
| **§2.3 SQS 佇列** | jobs body 只有 `job_id` 與 `s3_key` | §4.5 步驟 5：用 `receive-message` 看一眼真的 body |
| **總覽 §2.4.1** | `get_cloud_route()` 的簽章；`CloudRoute(mailbox, probe, *, timeout_seconds)` | §4.3 的完整函式 |
| **總覽 §2.4.2** | `CLOUD_ROUTE`／`CLOUD_RESULT_TIMEOUT_SECONDS`／`S3_BUCKET`／兩個佇列 URL／`AWS_REGION` | §4.3 全部從 `config.X` 即時讀 |
| **總覽 §2.7 Phase 86** | 動到 `app/dependencies.py`、`tests/unit/test_dependencies_cloud_unit.py`（新）、`LAUNCH.md`；**2 顆**測試 | §3「做」清單 |
| **總覽 §10.1 追認項 l** | `assume` 只給階段丁與除錯用；戊之後日常用 `ec2` | §4.8 把 `.env` 改回 `off`；§7 陷阱 4 |
| **總覽 §7 鐵律 5** | boto3 相關 import 寫在 `get_cloud_route()` **函式裡面** | §4.3 的 `from app.services.aws_mailbox import AwsMailbox` 在函式內 |
| **phase-77 §8 的鬧鐘表** | `assume` → `NotImplementedError` 這個暫時分支由 **Phase 86** 換掉，並把同一顆測試 `test_get_cloud_route預設off時回CloudRouteOff` 裡 `assume` 那半拆掉；**不認得的值永遠 `raise ValueError`**（永久行為，不是鬧鐘） | §4.3 的兩個勾選框；§6 有一條專門驗它 |

---

## 2. 前置條件

### 2.1 前面的 phase

- **★G1 已由產品負責人明示通過。**
- **Phase 74〜81 全部完成**：隱私閘門、`gated_ingest.run_gated_ingest_job()`、
  `cloud_ingest.CloudRoute`／`CloudRouteOff`／`AlwaysRunning`、
  第五道安全網 `wire_fake_cloud`、PDF 雲端路。
- **Phase 82〜85 全部完成**：AWS 帳號、`aws_mailbox.py`、S3 bucket、兩條 SQS 佇列，
  而且 `python scripts/aws_check.py s3 sqs` 兩個都印 OK。

### 2.2 開工基線（實查）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

pytest -q
# 預期尾巴：640 passed，0 skipped
#   ＝ 2026-09-02 實查基線 624（`pytest --collect-only -q`）＋ Phase 83 的 16 顆
#   ⚠ 總覽 §9 軌跡表寫的是 632／634，那是 2026-08-31 寫總覽當下的估算值，**已過期**；
#     一律以「本 phase 新增幾顆」為準（總覽 §9 開頭那句自己就這樣說）。
# 本 phase +2 → 收工 642

# 前面的零件都在
grep -n "^class CloudRoute:" app/services/cloud_ingest.py
grep -n "class CloudRouteOff" app/services/cloud_ingest.py
grep -n "class AlwaysRunning" app/services/cloud_ingest.py
grep -n "def get_cloud_route" app/dependencies.py
grep -n "def run_gated_ingest_job" app/services/gated_ingest.py
# 預期：五行都命中

# AWS 那邊也都在   ⚠ 這一行由 controller 親自執行（裁決 R3；實作 subagent 不跑它）
#   不必 `source .env`：aws_check.py 自己會經 app.core.config 的 load_dotenv 讀 .env，
#   拿的是 personaldocai-mac 那把最小權限 key（S3／SQS 的讀寫本來就該用它）。
python scripts/aws_check.py s3 sqs        # 預期兩個 ✅

# 四個容器活著
docker compose ps --no-trunc              # db／redis 要 Up (healthy)；app／worker 要 Up
#   ⚠ 2026-09-02 現況：app／worker 是用 **dev overlay** 起的（compose.dev.yaml，app 有 --reload）。
#     所以本檔所有 restart 一律帶兩個 -f：
#       docker compose -f compose.yaml -f compose.dev.yaml restart worker

# Ollama 活著（★ 非開不可：embeddings 一律本機 bge-m3，雲端路與 fallback 都要用它）
#   ⚠ 這兩行也是 controller 的事（跟煙霧綁在一起）；§4.1〜§4.4 的 pytest 不需要 Ollama
#     （第二道安全網 wire_fake_ai 早就把 AI 全換成假件了）。
open -a Ollama                            # 2026-09-02 現況：Ollama 沒開，要先開（裁決 R5）
curl -s http://localhost:11434/api/tags | head -c 60
# 預期：印得出 JSON 開頭（`{"models":[...`）。完全沒有輸出 ＝ 還沒起來，等幾秒再試一次。
```

### 2.3 本 phase 對顆數的影響

**+2 顆**（總覽 §2.7），全部在新檔 `tests/unit/test_dependencies_cloud_unit.py`。
開工基線 **640** → 收工 **642**（640 ＝ 2026-09-02 實查的 624 ＋ Phase 83 的 16）。

> 📌 **2026-09-02 review fix wave 之後是 +3**（同一個檔再加一顆
> `test_assume模式把config的四個值對應到AwsMailbox`），全量 **644**。詳見 §8 的 fix wave 那一行。

### 2.4 開工前先看一眼現在的 `get_cloud_route()`

```bash
grep -n -A 20 "def get_cloud_route" app/dependencies.py
```

Phase 77 留下來的版本（`app/dependencies.py` L281〜307，**2026-09-02 實查逐字照抄**，docstring 略）
**四段順序固定**：`off` → `assume`（暫時）→ `ec2`（暫時）→ 打錯字 `ValueError`（永久）：

```python
def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    mode = config.CLOUD_ROUTE
    if mode == "off":
        return cloud_ingest.CloudRouteOff()
    if mode == "assume":
        raise NotImplementedError("CLOUD_ROUTE=assume 要等 Phase 86 接上真 AWS 才能用")
    if mode == "ec2":
        raise NotImplementedError("CLOUD_ROUTE=ec2 要等 Phase 89 的 Ec2Probe 才能用")
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{mode!r}")
```

**本 phase 只換掉 `assume` 那一支**；`off`、`ec2` 與最後那行 `ValueError` **一個字都不動**
（`ec2` 留給 Phase 89；`ValueError` 是**永久行為**——Phase 77 的
`test_get_cloud_route預設off時回CloudRouteOff` 用 `CLOUD_ROUTE=cloudy` 釘著「打錯字要當場炸」，
把它改成「不認得就當 off」那顆就紅，而且「我明明開了雲端路怎麼都沒送出去」這種最難查的壞法會回來）。

另外，Phase 77 在**同一顆測試**裡留了一個「`assume` 還是 `NotImplementedError`」的**鬧鐘**
（phase-77 §8 的鬧鐘表指名 Phase 86 拆掉 `assume` 那半）。接上 `assume` 之後那半會紅——
那是鬧鐘響了，不是壞掉；§4.3 的第二個勾選框就是去拆它（只拆 `assume` 那半，`ec2` 那半留給 Phase 89）。

> ⚠️ **絕對不要同時跑兩份 pytest。** 兩份會互相 `TRUNCATE` 同一個測試庫，
> 症狀是大量看似隨機的 404 與 `TypeError: 'NoneType' object is not subscriptable`。

> ⚠️ **本機真模型很慢，而且不要並行。** 看圖 64〜88 秒（9 欄 prompt 可到 2〜5 分鐘），
> 閘門短問本機也要約 100 秒（phase0901 實測）。§4.5 的煙霧會等到看完圖，
> 所以**一次只上傳一張**，也不要同時去問問題（Phase 48 曾經把 db 容器壓垮過）。
>
> **本 phase 的煙霧一律先把頁首的「AI 模型」開關撥到「雲端」**（裁決 R5；作法見 §4.5 步驟 0）：
> 閘門短問 0.7 秒、看圖 0.8 秒，整條煙霧從十幾分鐘縮到兩三分鐘。
> 那扇門管的是**四個注入點 ＋ 隱私閘門**：`config.AI_BACKEND` 在 `POST /photos` 那一刻被
> 抄進 job（`app/api/routers/photos.py` 的 `ai_backend=config.AI_BACKEND`），worker 再用
> `job["ai_backend"]` 建閘門與 VLM（`app/celery_app.py` 的 `build_privacy_gate_for_backend`／
> `build_vlm_for_backend`）——**worker 行程自己的 `config.AI_BACKEND` 永遠是 `local`**，
> 所以撥開關要在 **app 那一頭**撥，而且要在**上傳之前**撥（總覽 §10.2 追認項 S）。
> ⚠ `embeddings` **不歸這扇門管、永遠本機**（向量必須跟庫裡既有的 bge-m3 同源），
> 所以 Ollama 一定要開著——這就是 §2.2 那行 `open -a Ollama` 的理由。

---

## 3. 範圍

### 做

> ⚠ **第 4〜7 項（＝§4.5〜§4.8）由 controller 親自執行**（裁決 R3）：
> 它們會建立／刪除真的 AWS 物件、改 `.env`、重啟容器。
> 實作 subagent 只做第 **1、2、3、8** 項，**一條 `aws` 指令都不打、不改 `.env`、不上傳任何東西**。

1. `app/dependencies.py` 的 `get_cloud_route()` 補上 **`assume`** 分支：
   建 `AwsMailbox`（bucket／兩條佇列 URL／region 全部從 `config` 即時讀）＋
   `AlwaysRunning()` 探測 ＋ `timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS`。
2. 新建 `tests/unit/test_dependencies_cloud_unit.py`（**2 顆**）。
3. **拆掉 Phase 77 的鬧鐘（`assume` 那半）**：`tests/unit/test_cloud_ingest_unit.py` 的
   `test_get_cloud_route預設off時回CloudRouteOff` 裡「`assume` 要 `NotImplementedError`」那半刪掉
   （只剩 `ec2` 那半留給 Phase 89；`cloudy` → `ValueError` 那段**保留**）。改既有測試，顆數不變。
4. **真 AWS 逾時煙霧**（人工，本 phase 的重頭戲）：頁首 AI 開關撥到**雲端** ＋
   `CLOUD_ROUTE=assume` ＋ `CLOUD_RESULT_TIMEOUT_SECONDS=30`，上傳一張**內容**是收據的圖
   → S3 上真的出現 `input` ＋ `context`、jobs 佇列 1 則、results 佇列 0 則
   → 30 秒後 fallback 本機入庫、S3 清空、log 有 `fallback=local reason=result_timeout`。
5. **敏感檔煙霧**：上傳一張**內容**是證件的圖 → **零 S3 物件**、log 有 `route=local verdict=SENSITIVE`。
6. `aws sqs purge-queue` 把煙霧留在 jobs 佇列的那一則清掉。
7. 頁首開關撥回**本機**；`.env` 改回 `CLOUD_ROUTE=off`、`CLOUD_RESULT_TIMEOUT_SECONDS=300`，restart worker。
8. `LAUNCH.md` §9（Monitoring and logs）新增一個 **"S3 / SQS layer"** 小節（**英文**）。
   （2026-09-02 實查：`LAUNCH.md` 498 行、§9 就叫 `## 9. Monitoring and logs`，
   底下依序有 `### Docker layer`／`### Celery / worker layer`／`### Redis layer`／
   `### app layer (the ask flow and the camera)`——插入點成立，**不必新增章節號**。）

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 做 `ec2` 分支（`Ec2Probe`） | 那是 **Phase 89**。現在連 EC2 都還沒有，做了也驗不動（而且 ★G2 還沒過） |
| 寫 `cloud_worker.py` | 那是 **Phase 87／88**。本 phase 的煙霧**故意**讓 jobs 佇列沒有人消費——那正是要驗的情境 |
| 改 `app/services/gated_ingest.py`／`cloud_ingest.py` | 它們在 Phase 78〜81 已經寫完並被 30 幾顆測試釘住。本 phase 只是「把插頭插上」，一個字都不改 |
| 改 `app/celery_app.py` | Phase 78 已經把 `ingest_task` 改成呼叫 `run_gated_ingest_job(..., cloud=dependencies.get_cloud_route())`，本 phase 換的是那個函式的**內容**，呼叫端不必動 |
| 把 `get_cloud_route()` 最後那行 `raise ValueError` 改成「不認得的值就當 `off`」（或只 log 一行） | Phase 77 的 `test_get_cloud_route預設off時回CloudRouteOff` 用 `CLOUD_ROUTE=cloudy` 釘著「打錯字要當場炸」，改了那顆就紅；而且「我明明把 CLOUD_ROUTE 設成 cloud 了怎麼都沒送出去」是最難查的一種壞法（phase-77 §8 鬧鐘表下方的明文） |
| 把 boto3 的 import 寫在 `dependencies.py` 檔案最上面 | 總覽 §7 鐵律 5：寫在函式裡面（理由與既有的 `get_task_dispatcher()` 相同——pytest 收集階段不必為了一顆字串測試就載入 boto3） |
| 讓 `.env` 停在 `CLOUD_ROUTE=assume` | `assume` 不做任何探測。等 EC2 上線之後如果忘了改，機器關著時它會**傻傻送出、然後等到逾時**才 fallback，每一張白白多花 5 分鐘（總覽 §10.1 追認項 l） |
| 在測試裡真的打 AWS | pytest 絕不連真 AWS（總覽 §7 鐵律 2）。2 顆測試都只檢查「建出來的物件對不對」，一次 API 都不打 |
| 改端點／前端／資料庫 | 端點恆 22、前端零改動、`photo` 表零改動 |
| 改 `compose.yaml` | 本增量零改動。`CLOUD_ROUTE` 等變數走 `.env`（已 bind-mount） |
| 讓頁首的「AI 模型」開關停在**雲端** | 那是煙霧為了加速臨時撥的（§4.5 步驟 0）。留著的話之後每一次看圖、每一次閘門短問都走 Ollama Cloud——**這與 `CLOUD_ROUTE` 是兩件事**，`off` 擋的只是「檔案送不送去 AWS」。§4.8 一定要撥回 `local` |
| 靠**檔名**決定煙霧走哪條路（例如 `cp receipt.png 身分證.png`） | 閘門 2026-09-01 起只看圖的內容（`del filename`）。改名什麼都不會改變，只會讓你以為驗過了 |

---

## 4. 實作步驟

> 🧪 **前半段（§4.1〜§4.4）走 TDD**：先寫會紅的測試 → **真的跑它、親眼看到紅** → 實作 → 綠。
> 後半段（§4.5〜§4.8）是**人工煙霧**：指令 → 預期輸出 → 做錯了怎麼退回。

### 4.1 先寫測試（紅）

```text
┌─ ⚠ 這兩顆測試要繞過第五道安全網，作法很特別，先讀完這一段 ─────────────────┐
│                                                                            │
│ `tests/conftest.py` 的 autouse fixture `wire_fake_cloud`（Phase 77 加的）  │
│ 每一顆測試都會做兩件事：                                                    │
│    ① monkeypatch.setattr(config, "CLOUD_ROUTE", "off")                     │
│    ② monkeypatch.setattr(dependencies, "get_cloud_route", lambda: …Off())  │
│                                                                            │
│ ② 把**模組屬性**換掉了，所以測試裡寫 `dependencies.get_cloud_route()`      │
│ 拿到的是假的。但我們這兩顆測試要驗的正是**真的那一支**。                    │
│                                                                            │
│ 解法：在測試檔的**最上面**用                                               │
│     from app.dependencies import get_cloud_route as real_get_cloud_route   │
│ ——這叫「早綁定」：import 發生在 pytest **收集階段**（fixture 還沒跑），      │
│ 所以這個名字抓住的是**原始的函式物件**，之後 monkeypatch 換掉模組屬性       │
│ 也影響不到它。                                                             │
│                                                                            │
│ 📌 平常寫產品碼時這是**要避免**的陷阱（phase-57 §7 陷阱 7 就在講它），       │
│    這裡是**刻意**利用它。所以測試的 docstring 一定要寫清楚，免得日後有人    │
│    「順手改成一致的寫法」，把測試改成永遠測假件。                           │
└────────────────────────────────────────────────────────────────────────────┘
```

- [x] 新建 `/Users/linjunting/personalDocAI/tests/unit/test_dependencies_cloud_unit.py`，**整份逐字貼上**：

```python
"""get_cloud_route() 的單元測試：只檢查「建出來的物件對不對」，**一次 AWS API 都不打**。

建立 boto3 的 client 不會連線（第一次真的呼叫方法時才發 HTTP），而 AlwaysRunning
的 is_running() 是純 Python 的 return True——所以這兩顆測試跑起來又快又安全。
第五道安全網另外還把 AWS_ENDPOINT_URL 指到死埠 http://127.0.0.1:9 當第二層保險。

★ 為什麼是 `from app.dependencies import get_cloud_route as real_get_cloud_route`：
  conftest 的 autouse fixture wire_fake_cloud 會用 monkeypatch 把
  dependencies.get_cloud_route 這個**模組屬性**換成回 CloudRouteOff 的假件。
  而這一行 import 發生在 pytest 的**收集階段**（fixture 還沒跑），
  所以它抓住的是**原始的函式物件**——換模組屬性影響不到它。
  ⚠ 這在產品碼裡是要避免的「早綁定」陷阱，這裡是**刻意**用它來取得原版。
    不要「順手改成 dependencies.get_cloud_route()」，那會讓這兩顆測試變成
    永遠在測假件、永遠綠。
"""

from __future__ import annotations

from app.core import config
from app.dependencies import get_cloud_route as real_get_cloud_route
from app.services import cloud_ingest
from app.services.aws_mailbox import AwsMailbox


def configure_assume_mode(monkeypatch) -> None:
    """把 config 擺成「.env 已經填好、CLOUD_ROUTE=assume」的樣子。

    值都是假的（bucket 與佇列 URL 不存在也沒關係）——本檔不會真的去呼叫它們。
    ⚠ 一定要用 monkeypatch 改 config 的屬性，不要直接指派：
      monkeypatch 會在測試結束時自動還原，直接指派則會污染後面每一顆測試。
    """
    monkeypatch.setattr(config, "CLOUD_ROUTE", "assume")
    monkeypatch.setattr(config, "S3_BUCKET", "test-bucket")
    monkeypatch.setattr(config, "SQS_JOBS_QUEUE_URL", "https://sqs.example.invalid/jobs")
    monkeypatch.setattr(config, "SQS_RESULTS_QUEUE_URL", "https://sqs.example.invalid/results")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")


def test_assume模式建出CloudRoute而且探測恆為True(monkeypatch):
    """assume ＝「假設遠端開著」：回真的 CloudRoute，而且 available() 永遠是 True。

    available() 之所以測得動而且不出網：assume 模式用的探測是 AlwaysRunning，
    它的 is_running() 就是 `return True`，一次 AWS API 都不打（總覽 §2.4.1）。

    這一顆同時守住兩件事：
      ① 不再是 NotImplementedError（Phase 77 留下的暫時分支已被換掉）
      ② 不是 CloudRouteOff（那樣的話 available() 會是 False，照片永遠出不了門）
    """
    configure_assume_mode(monkeypatch)

    route = real_get_cloud_route()

    assert isinstance(route, cloud_ingest.CloudRoute)
    assert not isinstance(route, cloud_ingest.CloudRouteOff)
    assert route.available() is True


def test_assume模式的逾時秒數讀config(monkeypatch):
    """逾時秒數必須是**呼叫當下**從 config 讀的，不可以寫死。

    作法：把 cloud_ingest.CloudRoute 暫時換成一個只記參數的側錄類別，
    這樣不必知道 CloudRoute 內部把 timeout_seconds 存在哪個私有屬性
    （測私有屬性名 ＝ 之後重新命名就會紅，那是假的把關）。

    順便一次驗完建構子的三個位置：mailbox 是真的 AwsMailbox、
    probe 是 AlwaysRunning、timeout_seconds 來自 config。

    為什麼這件事重要：這個數字寫死的話，Phase 92 之後想把逾時從 300 調成別的值
    就得改程式、重建映像；而它本來只該是 .env 的一行。
    """
    configure_assume_mode(monkeypatch)
    monkeypatch.setattr(config, "CLOUD_RESULT_TIMEOUT_SECONDS", 123)

    captured: dict = {}

    class RecordingCloudRoute:
        def __init__(self, mailbox, probe, *, timeout_seconds):
            captured["mailbox"] = mailbox
            captured["probe"] = probe
            captured["timeout_seconds"] = timeout_seconds

    monkeypatch.setattr(cloud_ingest, "CloudRoute", RecordingCloudRoute)

    real_get_cloud_route()

    assert captured["timeout_seconds"] == 123
    assert isinstance(captured["mailbox"], AwsMailbox)
    assert isinstance(captured["probe"], cloud_ingest.AlwaysRunning)
```

> 📌 **第二顆測試有一個前提**：`get_cloud_route()` 必須用**模組屬性**的寫法
> 呼叫 `cloud_ingest.CloudRoute(...)` 與 `cloud_ingest.AlwaysRunning()`，
> 而不是在檔案最上面 `from app.services.cloud_ingest import CloudRoute` 之後直接用
> ——後者是早綁定，`monkeypatch.setattr(cloud_ingest, "CloudRoute", …)` 換不到。
> §4.3 的程式碼就是這樣寫的；Phase 77 的 `off` 分支本來就是 `cloud_ingest.CloudRouteOff()`
> （`app/dependencies.py` 的既有風格就是 `from app.services import (…)` 再用模組屬性，
> 例如 `vlm_service.OllamaVLM()`），不必另外改。

---

### 4.2 跑它，確認是紅的

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_dependencies_cloud_unit.py -v
```

**預期輸出**（兩顆都紅，錯誤是 Phase 77 留下的那個暫時分支）：

```text
FAILED tests/unit/test_dependencies_cloud_unit.py::test_assume模式建出CloudRoute而且探測恆為True
FAILED tests/unit/test_dependencies_cloud_unit.py::test_assume模式的逾時秒數讀config
E   NotImplementedError: CLOUD_ROUTE=assume 要等 Phase 86 接上真 AWS 才能用
2 failed
```

看到 `NotImplementedError` 就對了——那代表測試**真的呼叫到了原版函式**（不是被安全網換掉的假件）。

**如果兩顆是綠的**：那就是早綁定沒生效、你拿到的是假件。
檢查 import 那一行是不是寫成了 `from app import dependencies` ＋ `dependencies.get_cloud_route()`。

---

### 4.3 實作（綠）

- [x] 打開 `/Users/linjunting/personalDocAI/app/dependencies.py`，
      把 `get_cloud_route()` **整支換成下面這一份**：

```python
def get_cloud_route() -> cloud_ingest.CloudRoute | cloud_ingest.CloudRouteOff:
    """這一台現在要不要走雲端路、怎麼走。**全系統只有這一個地方決定。**

    三種模式由 config.CLOUD_ROUTE 決定（總覽 §2.4.2）：
      off    → CloudRouteOff()：available() 恆為 False，gated_ingest 直接 fallback 成
               run_ingest_job——行為與增量五**逐字相同**（pytest 與新 clone 的預設）
      assume → CloudRoute ＋ AwsMailbox ＋ AlwaysRunning：假設遠端開著、**不做探測**
               （階段丁：工人跑在這台 Mac 上時用；機器沒開時它會傻傻送出、等到逾時才
               fallback，所以不要拿來當日常設定——總覽 §10.1 追認項 l）
      ec2    → Phase 89 才接（探測換成 Ec2Probe）

    ★ 打錯字要當場炸（ValueError），不要默默當成 off：
      「我明明把 CLOUD_ROUTE 設成 cloud 了，怎麼都沒送出去」是最難查的一種壞法。
      （Phase 77 的 test_get_cloud_route預設off時回CloudRouteOff 用 CLOUD_ROUTE=cloudy 釘住它。）

    ★ boto3 相關的 import 寫在函式**裡面**（不是檔案最上面），理由與既有的
      get_task_dispatcher() 相同：pytest 收集階段不必為了跑一顆字串測試就載入 boto3，
      而且 CLOUD_ROUTE=off 時根本走不到那一行。

    ★ 三個資源名稱與逾時秒數一律 config.X **即時讀**（不要 from … import X）：
      那樣才改得動（tests 用 monkeypatch 換、.env 改完 restart worker 就生效）。

    pytest 由 tests/conftest.py 的第五道安全網 wire_fake_cloud 兩管齊下換掉它。
    """
    mode = config.CLOUD_ROUTE
    if mode == "off":
        return cloud_ingest.CloudRouteOff()
    if mode == "assume":
        # 只有真的要走雲端時才載入 boto3（唯一入口是 aws_mailbox）
        from app.services.aws_mailbox import AwsMailbox

        mailbox = AwsMailbox(
            bucket=config.S3_BUCKET,
            jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
            results_queue_url=config.SQS_RESULTS_QUEUE_URL,
            region=config.AWS_REGION,
        )
        return cloud_ingest.CloudRoute(
            mailbox,
            cloud_ingest.AlwaysRunning(),
            timeout_seconds=config.CLOUD_RESULT_TIMEOUT_SECONDS,
        )
    if mode == "ec2":
        raise NotImplementedError("CLOUD_ROUTE=ec2 要等 Phase 89 的 Ec2Probe 才能用")
    raise ValueError(f"CLOUD_ROUTE 只認 off／assume／ec2，讀到的是：{mode!r}")
```

> 📌 **本 phase 只換掉 `assume` 那一支。** 上面這一份已與 `app/dependencies.py` 的
> **2026-09-02 實際程式碼逐字對齊**（L281〜307，變數名是英文的 `mode`）：
> `off` 那兩行、`ec2` 那兩行、最後那行 `raise ValueError` 都與 phase-77 §4 步驟 5 相同，
> 你真正改的只有 `assume` 底下那一段（從一行 `raise NotImplementedError(...)` 變成建 `AwsMailbox`
> ＋ `CloudRoute`）。`ec2` 那一支**原封不動**留給 Phase 89；`ValueError` 那行**永遠不拿掉**
> （Phase 89 之後這個函式的長相見 phase-89 §4 步驟 5——`assume` 那段**程式碼**到那時也不會再動，docstring 會重寫）。

- [x] 確認 `app/dependencies.py` 檔案最上面的 import 區有 `cloud_ingest`
      （Phase 77 應該已經加了；沒有的話補進既有那一串）：

```python
from app.services import (
    ask_workflow,
    cloud_ingest,
    entity_suggestion_service,
    indexing_service,
    ingest_job_store,
    privacy_gate,
    vlm_service,
)
```

  （這一串是 ruff 的 `I` 規則排序過的樣子；`ruff format` 會幫你維持。）

- [x] **拆掉 Phase 77 的鬧鐘（`assume` 那半）。** 打開
      `/Users/linjunting/personalDocAI/tests/unit/test_cloud_ingest_unit.py`，找到
      `test_get_cloud_route預設off時回CloudRouteOff`（2026-09-02 實查在該檔 L267〜291），
      把中間這一段（**實檔原文逐字照抄**，L277〜286）：

```python
    # assume／ec2 現在還沒接（總覽 §2.7：本增量**唯二**允許的暫時分支之一）。
    # ⚠ 這兩行是**鬧鐘**：
    #     Phase 86 接上 assume 時 → **拆掉 assume 那半**（改成驗它建出 CloudRoute）
    #     Phase 89 接上 ec2 時   → **拆掉 ec2 那半**（改成驗它的探測是 Ec2Probe）
    #   兩個 phase 各自的測試檔（test_dependencies_cloud_unit.py）會接手那一半的驗證。
    for mode in ("assume", "ec2"):
        monkeypatch.setattr(config, "CLOUD_ROUTE", mode)
        with pytest.raises(NotImplementedError):
            get_cloud_route()
```

      **整段換成**（只剩 `ec2` 那半）：

```python
    # ec2 現在還沒接（總覽 §2.7：本增量唯二允許的暫時分支，只剩這最後一個）。
    # ⚠ 這幾行是**鬧鐘**：Phase 89 接上 ec2 時 → **拆掉**（改成驗它的探測是 Ec2Probe）。
    #   assume 那半已由 Phase 86 拆掉——它的正面斷言在 test_dependencies_cloud_unit.py。
    monkeypatch.setattr(config, "CLOUD_ROUTE", "ec2")
    with pytest.raises(NotImplementedError):
        get_cloud_route()
```

      那顆測試**開頭**的 `assert isinstance(get_cloud_route(), CloudRouteOff)` 與**結尾**的
      「`CLOUD_ROUTE=cloudy` 要 `ValueError`」**都保留**——後者是永久行為，不是鬧鐘。
      為什麼一定要做：`assume` 現在會回真的 `CloudRoute`、不再 raise，舊的那半會紅
      （`Failed: DID NOT RAISE <class 'NotImplementedError'>`）；而「`assume` 建出什麼」
      已經由 §4.1 那 2 顆正面驗證了，這半鬧鐘的任務完成、功成身退。
      **顆數不變**（改既有測試不計顆）。

- [x] 確認鬧鐘只剩 `ec2` 那半，而且那個檔全綠：

```bash
grep -n '"assume", "ec2"' tests/unit/test_cloud_ingest_unit.py || echo "OK：assume 那半已拆"
grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py
pytest tests/unit/test_cloud_ingest_unit.py -q
```

**預期輸出：** 第一條印 `OK：assume 那半已拆`；第二條只剩 `ec2` 那一處
（`with pytest.raises(NotImplementedError):` 一行）；第三條全部 passed、**0 failed**
（這個檔在 Phase 77／79／80 累積 11＋4＋5＝20 顆；顆數以你實查為準，重點是一顆都不紅）。

---

### 4.4 跑綠、跑全量

- [x] 新測試：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/unit/test_dependencies_cloud_unit.py -v
```

**預期輸出：** `2 passed`

- [x] 全量：

```bash
pytest -q
```

**預期輸出：** `642 passed`，**0 skipped**（640 ＋ 2）。

- [x] 零外部依賴實證（三個死埠一起指，顆數要一模一樣）：

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

**預期輸出：** `642 passed`

> 這一條在本 phase 特別重要：我們剛剛才讓 `get_cloud_route()` 有能力建出**真的**
> AWS client。死埠實證通過，就代表第五道安全網真的把它擋住了、pytest 沒有偷偷連上 AWS。

- [x] 格式與 lint：

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

**預期輸出：** `All checks passed!`

---

### 4.5 ★ 真 AWS 逾時煙霧（本 phase 的重頭戲）

> ⚠️ **§4.5〜§4.8 整段由 controller 親自執行**（裁決 R3）。
> 它會建立與刪除真的 AWS 物件、改 `.env`、重啟容器。
> **實作 subagent 到 §4.4 為止就收工**：不打任何 `aws` 指令、不改 `.env`、不上傳任何東西。

> **這一段會真的把一張照片送上 AWS。** 做之前先確認：
> ① 四個容器都活著（`docker compose ps --no-trunc`）
> ② **Ollama 活著**（`open -a Ollama`；embeddings 一律本機，沒有它入庫那一段一定失敗）
> ③ `python scripts/aws_check.py s3 sqs` 兩個 ✅。

#### 步驟 0：把頁首的 AI 開關撥到「雲端」（省十幾分鐘）

- [x] 執行（`PUT /settings/ai-backend`，body 只有一個鍵 `backend`）：

```bash
cd /Users/linjunting/personalDocAI
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
```

**預期輸出**（恰兩鍵）：

```json
{"backend":"cloud","cloud_configured":true}
```

**為什麼要撥：** 閘門短問與入庫看圖都跟這扇門走。本機要 100 秒＋64〜88 秒，
雲端各約 0.7／0.8 秒（phase0901 實測）——整段煙霧從十幾分鐘縮到兩三分鐘。

**細節（很容易踩）：**

- 這個狀態存在 **app 行程的記憶體**裡（`config.AI_BACKEND`），**重啟 app 就會回到 `local`**。
  重啟 **worker**（步驟 2 要做）不影響它。萬一中途重啟了 app，就把這一步再跑一次。
- worker 行程自己的 `config.AI_BACKEND` 永遠是 `local`；它用的是 `POST /photos` 那一刻
  抄進 job 的快照 `job["ai_backend"]`（總覽 §10.2 追認項 S）。所以**撥開關必須在上傳之前**，
  上傳之後才撥對這一筆完全沒有影響。
- 回應 `"cloud_configured":false` ＝ `.env` 沒有 `OLLAMA_API_KEY`，會回 **422**、開關不動。
- **embeddings 不歸這扇門管、永遠本機**——這就是 Ollama 非開不可的原因。
- §4.8 收尾要撥回 `local`。

#### 步驟 1：準備一張「內容」非敏感的圖

- [x] ⚠ **決定走哪條路的是圖的內容，不是檔名**（2026-09-01 改判；`VlmGate.classify()` 的
      第一行就是 `del filename`）。所以這裡要產一張**看起來就是收據**的圖：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from PIL import Image, ImageDraw, ImageFont


def font(size):
    """macOS 有 Arial；沒有就退回 Pillow 內建的可縮放字型（10.1 起支援 size）。"""
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# 512 是刻意的：閘門會把圖縮到長邊 <= 512（privacy_gate.GATE_IMAGE_MAX_SIDE），
# 一開始就畫這麼大，字才不會在縮圖時糊掉、模型才讀得出來。
image = Image.new("RGB", (512, 384), (250, 248, 240))
draw = ImageDraw.Draw(image)
draw.text((24, 24), "RECEIPT", fill=(20, 20, 20), font=font(44))
draw.text((24, 96), "Target  Store #1842", fill=(40, 40, 40), font=font(30))
for index, line in enumerate(["Cola          45", "Chips         30", "Bread         60"]):
    draw.text((24, 150 + index * 40), line, fill=(40, 40, 40), font=font(28))
draw.text((24, 300), "Total        135", fill=(20, 20, 20), font=font(34))
image.save("/tmp/receipt-test.png")
print("已產生 /tmp/receipt-test.png")
PY
file /tmp/receipt-test.png        # 預期：/tmp/receipt-test.png: PNG image data, 512 x 384, ...
open /tmp/receipt-test.png        # 人眼看一下：RECEIPT／Target／Total 三行都要清楚
```

> 📌 **用英文字，不要用中文字**：`ImageDraw.text()` 的內建字型畫不出中日韓文字
> （會變成空白或方框），而 macOS 的 Arial 也沒有中文字。這張圖只是要讓模型看出
> 「這是一張收據」，英文就夠了。
>
> 📌 **手邊有真收據照片的話更好**（fallback 之後要走完整的本機入庫流程，
> 真照片比合成圖更容易被 VLM 看懂、照片才會真的進待決定牆）：
>
> ```bash
> python - <<'PY'
> from PIL import Image
>
> # ⚠ 不要用 cp 把 .jpg 改名成 .png：curl 會照副檔名送 Content-Type: image/png，
> #   裡面卻是 JPEG 位元組——S3 的鍵名、staging 的副檔名、落地原圖的副檔名
> #   會全部對不上內容（§7 陷阱 12）。一定要真的轉檔。
> Image.open("<你的一張真收據照片>.jpg").convert("RGB").save("/tmp/receipt-test.png")
> print("已產生 /tmp/receipt-test.png")
> PY
> ```
>
> ⚠ 副檔名要與內容一致（PNG 存成 `.png`）——`POST /photos` 看的是 `Content-Type`
> （curl 依副檔名決定），不是檔案內容；不是 JPEG／PNG／PDF 的 Content-Type 才會 415。
> 至於**檔名叫 `receipt-test.png` 只是為了人好認**，對閘門的判定沒有任何影響。

#### 步驟 2：把 `.env` 切成 `assume` ＋ 30 秒逾時

- [x] 編輯 `/Users/linjunting/personalDocAI/.env`（**兩行**，等號兩邊不可以有空白）：

```ini
CLOUD_ROUTE=assume
CLOUD_RESULT_TIMEOUT_SECONDS=30
```

  （這兩行如果原本不在 `.env` 裡，就各新增一行——config 的預設是 `off` 與 300，
  本次煙霧不想等五分鐘。已經有的話改值就好，**不要留兩行同名的**：`load_dotenv` 取最後一個，
  很容易看錯。）

- [x] **restart worker**（`get_cloud_route()` 是 worker 行程在呼叫的；行程只在啟動時讀 `.env`）：

```bash
cd /Users/linjunting/personalDocAI
# 2026-09-02 現況是**開發模式**（compose.dev.yaml 疊加起來的），所以帶兩個 -f：
docker compose -f compose.yaml -f compose.dev.yaml restart worker
# 若當下是常駐模式就少一個 -f：
#   docker compose -f compose.yaml restart worker
# 兩種寫法都只是「重啟現有容器」；.env 是 bind-mount 進去的，重啟就重讀。
# ⚠ 只重啟 worker、**不要重啟 app**：app 一重啟，步驟 0 撥的雲端開關會回到 local。
docker compose exec worker python -c \
  "from app.core import config; print('CLOUD_ROUTE =', config.CLOUD_ROUTE, '| 逾時 =', config.CLOUD_RESULT_TIMEOUT_SECONDS)"
```

**預期輸出：**

```text
CLOUD_ROUTE = assume | 逾時 = 30
```

**做錯了怎麼退回：** 印出 `off` → 忘了 restart，或 `.env` 沒存檔。

#### 步驟 3：先確認 S3 與兩條佇列都是空的（乾淨的起點）

- [x] 執行（`unset` 那一行不能省：不是因為 `list-objects-v2` 跑不過——`.env` 那把
      `personaldocai-mac` 的 key **有** bucket ARN 的 `s3:ListBucket`（總覽 §10.2 P，82 §4.6.1
      的 `ListMailboxBucket`），這條用哪一把都跑得過——而是後面 `purge-queue` 這類管理指令
      只有 admin 才有權限。
      ⚠ **本檔的 `aws` 指令一律不帶 `--profile`**：`~/.aws` 裡**只有 `[default]`**，
      而它的身分就是 admin（`aws sts get-caller-identity --query Arn --output text`
      結尾是 `user/personaldocai-admin`）。**沒有**一個叫 `personaldocai-admin` 的 profile，
      寫 `--profile personaldocai-admin` 會直接 `ProfileNotFound`。
      所以「用哪個身分」完全取決於**環境變數裡有沒有那兩把 key**：
      `source .env` 之後就是 mac 那把（權限小），`unset` 之後才是 default 的 admin。
      ⚠ `unset` 只影響**你這個終端機**；容器裡的 worker 仍然照 `.env` 用 `personaldocai-mac`
      那把最小權限 key 去 Put／Send／Receive——那正是要的，**不要**進容器去 unset 任何東西。
      （這裡之所以還是要 `source .env`，是因為要拿 `$S3_BUCKET`／兩個佇列 URL／`$AWS_REGION`
      這四個**值**；載進來之後立刻把兩把 key 拿掉就好。）：

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws sts get-caller-identity --query Arn --output text   # 結尾要是 user/personaldocai-admin
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'KeyCount'
```

**預期輸出：** 第一行是 admin 的 Arn；第二行是 `0`

#### 步驟 4：上傳（**要看到 202**）

- [x] 執行：

```bash
curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

**預期輸出**（body 恰三鍵 ＋ 狀態碼 202；`job_id` 是隨機的）：

```text
{"job_id":"8f3c...","filename":"receipt-test.png","content_type":"image/png"}
202
```

- [x] 把 `job_id` 記下來（後面幾步要用）：

```bash
JOB_ID=<剛剛那一串>
```

> ⚠ **202 不代表照片已經入庫**（增量五起就是這樣）。它只代表「檔案收下了、排進佇列了」。

**做錯了怎麼退回：**

| 狀態碼 | 意思 | 怎麼修 |
|---|---|---|
| `415` | 檔案不是 JPEG／PNG／PDF | 確認 `/tmp/receipt-test.png` 真的是 PNG（`file /tmp/receipt-test.png`） |
| `000`（curl 連不上） | 用了 `http://`，或 app 容器沒起來 | 網址開頭要有 **s**：`https://`；`docker compose ps` 看 app |
| `500` | 入列失敗（Redis 不通） | `docker compose ps` 看 redis 是不是 `Up (healthy)` |

#### 步驟 5：**30 秒內**去看 S3 與佇列（動作要快）

- [x] 執行（建議先把這幾行貼好，上傳完馬上按 Enter）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "documents/$JOB_ID/" \
  --region "$AWS_REGION" --query 'Contents[].Key' --output text
```

**預期輸出**（兩個物件；**沒有** `result.json`，因為沒有任何工人）：

```text
documents/8f3c.../context.json	documents/8f3c.../input.png
```

- [x] 看 jobs 佇列有一則、results 佇列 0 則：

```bash
for URL in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  echo "── ${URL##*/}"
  aws sqs get-queue-attributes --queue-url "$URL" --region "$AWS_REGION" \
    --attribute-names ApproximateNumberOfMessages --query 'Attributes' --output json
done
```

**預期輸出**（數字是**近似值**，可能要幾秒才反映）：

```text
── personaldocai-jobs
{
    "ApproximateNumberOfMessages": "1"
}
── personaldocai-results
{
    "ApproximateNumberOfMessages": "0"
}
```

> 📌 **這一格就是 design6 §0「丙」的具體證據**：
> jobs 佇列有一則「來拿東西」的紙條，results 佇列還是空的（因為沒人做事）。

- [x] （可選，但很值得看一眼）把那則訊息的 body 印出來，親眼確認**裡面沒有位元組**：

```bash
aws sqs receive-message --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION" \
  --max-number-of-messages 1 --wait-time-seconds 5 \
  --query 'Messages[0].Body' --output text
```

**預期輸出**（恰兩個鍵、都是字串）：

```text
{"job_id": "8f3c...", "s3_key": "documents/8f3c.../input.png"}
```

> ⚠ 這一條會把訊息「拿走」，它會隱形 900 秒（jobs 的 `VisibilityTimeout`）。
> 不影響本次煙霧（本來就沒有人要處理它），而且 §4.7 會把整條佇列 purge 掉。

#### 步驟 6：等超過 30 秒，看 fallback 的那一行 log

- [x] 執行：

```bash
sleep 40
docker compose logs --tail=200 worker | grep -E "route=|fallback="
```

**預期輸出**（兩行，順序如下；`[...]` 那段是 Celery 的時間戳與行程名，`job` 後面接的是你的 `job_id`）：

```text
worker-1  | [2026-08-31 22:41:03,512: INFO/ForkPoolWorker-1] job 8f3c... route=cloud verdict=NON_SENSITIVE
worker-1  | [2026-08-31 22:41:34,020: WARNING/ForkPoolWorker-1] job 8f3c... fallback=local reason=result_timeout
```

（字樣來自 `gated_ingest.py` 的 `logger.info("job %s route=cloud verdict=%s", …)` 與
`logger.warning("job %s fallback=local reason=%s", …)`——`job_id` 在**句首**，不在句尾。
兩行中間另外會有一行 `job 8f3c... 等雲端結果逾時（30 秒）`，那是 `CloudRoute.wait_result` 的
warning，沒被這條 grep 撈到是正常的。）

- 第一行：閘門判定**非敏感**、探測（`AlwaysRunning`）說可用 → 走雲端路。
- 第二行：等了 30 秒沒有人回 → **fallback 回本機**。
  `fallback=local reason=…` 是 design6 §2.1 的**契約字樣**（Phase 78〜80 的測試用 `caplog` 釘住）。

**做錯了怎麼退回：**

| 看到什麼 | 意思 | 怎麼修 |
|---|---|---|
| 只有 `fallback=local reason=remote_unavailable`，**沒有** `route=cloud` 那行 | `CLOUD_ROUTE` 還是 `off`（restart 沒生效，或 `.env` 沒存檔）：`CloudRouteOff.available()` 恆 False，閘門雖判 NON_SENSITIVE 也直接 fallback。`assume` 模式的探測是 `AlwaysRunning`，**不可能**出現這個 reason | 回步驟 2，用那條 `docker compose exec worker python -c …` 確認印出 `assume` |
| `route=local verdict=UNCERTAIN` | 閘門**看不清楚**這張圖（`sensitive=false` 但 `confident=false`，或讀檔／縮圖／模型呼叫失敗）。**與檔名無關**——`VlmGate.classify()` 第一行就 `del filename` | 先看 worker log 有沒有 `隱私閘門判斷失敗，當作 UNCERTAIN` 那類 warning（每條失敗路徑都會留一行）；沒有的話就是模型真的沒把握 → 換一張字更大更清楚的圖（步驟 1 那段已經畫成 512 寬、字級 28 以上），或改用一張真收據照片 |
| `route=local verdict=SENSITIVE`（可是你傳的是收據） | 閘門真的覺得圖裡有個人資訊（例如你用的真收據上有地址或電話） | 換一張沒有個資的收據；或直接接受——**這一格證明的是閘門會擋，不是壞掉**，但那樣就驗不到雲端那條路，逾時煙霧要另外用一張過得了閘門的圖重做 |
| `route=cloud …` 之後接 `fallback=local reason=submit_failed` | S3 或 SQS 送出失敗（多半是 `.env` 的三個資源名稱空的或打錯，或 IAM 權限不足） | `python scripts/aws_check.py s3 sqs` 先跑一次；`docker compose logs worker --tail=100` 看 `送去雲端失敗` 那行底下的 traceback |
| 完全沒有 log | worker 沒拿到任務 | `docker compose logs worker --tail=50` 看有沒有連線錯誤 |

#### 步驟 7：等本機看完圖，確認照片真的入庫、S3 被清乾淨

- [x] 等 worker 做完（步驟 0 已把開關撥到雲端，看圖約 1 秒；忘了撥就是本機 gemma4 的 64〜88 秒。
      **embedding 那一段一律本機**，所以總時間至少還要加上 bge-m3 的幾秒）：

```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
```

**預期輸出**（`jobs` 陣列裡**沒有**你那一筆 ＝ 成功；成功的 job 會被刪掉。
`pending_count` 是收件箱**現在**的照片數，要比上傳前**多 1**——下面的 12 只是例子）：

```json
{
    "jobs": [],
    "pending_count": 12
}
```

- [x] 資料庫確實多了一列：

```bash
psql -d PersonalDocAI -c "select id, category, left(text, 40) as text_head from photo order by id desc limit 1"
```

**預期輸出：** 最新那一列就是剛剛上傳的照片（`category` 通常是「未分類」——
上傳一律先進收件箱，這是增量一以來的規則）。

- [x] **S3 已經被清乾淨**（fallback 之前 `cloud.cleanup()` 會盡力刪掉三個物件）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'KeyCount'
```

**預期輸出：** `0`

- [x] 待決定牆上看得到它（人工）：

```bash
open "https://localhost:8000/ui/pending.html"
```

**預期：** 頂欄「待決定（N）」比上傳前多 1，牆上有那張照片。

> 📌 **這一格就是本 phase 最重要的結論：**
> 使用者從頭到尾看到的是 202 → 進度面板 → 待決定牆——
> **與增量五逐字相同**。雲端整條路壞掉（根本沒有工人），他完全不知道。

---

### 4.6 敏感檔煙霧（零 S3）

> ⚠ **本節同樣由 controller 親自執行**（裁決 R3）。

- [x] 準備一張**內容**是證件的圖（⛔ **不可以** `cp /tmp/receipt-test.png /tmp/身分證.png`
      ——閘門不看檔名，改名只會得到跟上一節一樣的 `NON_SENSITIVE`，等於什麼都沒驗到）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from PIL import Image, ImageDraw, ImageFont


def font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


# 全部是**編造的假資料**，不要用任何一個人的真證件。
# 內容要打中 PRIVACY_PROMPT 列的例子（身分證件、健保卡、駕照、護照…）。
image = Image.new("RGB", (512, 324), (238, 244, 250))
draw = ImageDraw.Draw(image)
draw.rectangle((8, 8, 503, 315), outline=(60, 90, 140), width=3)
draw.text((28, 28), "NATIONAL ID CARD", fill=(20, 30, 60), font=font(36))
draw.text((28, 96), "Name: WANG XIAO MING", fill=(30, 30, 30), font=font(26))
draw.text((28, 140), "ID No: A123456789", fill=(30, 30, 30), font=font(26))
draw.text((28, 184), "Date of birth: 1990-01-01", fill=(30, 30, 30), font=font(26))
draw.text((28, 228), "Address: 100 Test Road, Taipei", fill=(30, 30, 30), font=font(24))
image.save("/tmp/id-card-test.png")
print("已產生 /tmp/id-card-test.png")
PY
file /tmp/id-card-test.png        # 預期：PNG image data, 512 x 324, ...
open /tmp/id-card-test.png        # 人眼看一下：五行字都要清楚
```

- [x] 上傳：

```bash
curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/id-card-test.png" \
  https://127.0.0.1:8000/photos
```

**預期輸出：** `202`（body 的 `filename` 是 `id-card-test.png`）

> 📌 **檔名故意取成 `id-card-test.png` 而不是 `身分證.png`**：
> 這一節要證明的是「**內容**敏感就擋得下來」。檔名本來就不影響判定
> （`del filename`），取個中性一點的名字反而能順便說明這件事。

- [x] **立刻**看 S3（這一次應該**什麼都不會出現**）：

```bash
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'KeyCount'
```

**預期輸出：** `0`（★ **敏感檔零 S3 呼叫** ——design6 §8 錯誤表第 1 列、§6 第 1 列）

- [x] 看 log：

```bash
docker compose logs --tail=100 worker | grep -E "route=|fallback="
```

**預期輸出**（這一筆**只有一行**，而且**沒有** `fallback=`——它根本沒去試雲端；
上面可能還看得到 §4.5 那一筆的兩行，看 `job` 後面的 id 分辨）：

```text
worker-1  | [2026-08-31 22:48:10,077: INFO/ForkPoolWorker-2] job 5d2e... route=local verdict=SENSITIVE
```

- [x] 等它做完，照片一樣會進待決定牆（本機路完全照舊）。

**做錯了怎麼退回：** 看到 `verdict=UNCERTAIN` 而不是 `SENSITIVE` →
模型沒把握（`sensitive=false, confident=false`），或讀檔／縮圖／呼叫模型的某一步失敗
（那三條路各會留一行 `隱私閘門判斷失敗，當作 UNCERTAIN` 的 warning，先去 log 裡找）。
**注意：`UNCERTAIN` 也是走本機、也是零 S3**（D3：不確定當敏感辦），
所以「零 S3」這個結論仍然成立，只是沒驗到「敏感」那一條。
想驗準一點就把圖畫得更像證件（照 `app/services/privacy_gate.py` 的 `PRIVACY_PROMPT`
列出來的例子挑一種：身分證件、健保卡、駕照、護照、病歷、處方箋、薪資單、
銀行對帳單、信用卡卡面、報稅資料、含個人地址或電話的信件）。

---

### 4.7 收尾①：把 jobs 佇列裡的殘訊息清掉

> ⚠ **本節由 controller 親自執行**（裁決 R3；`purge-queue` 是不可逆的管理操作）。

> 步驟 5 那則「來拿東西」的紙條**還在佇列裡**（沒有任何工人消費它）。
> 不清掉的話，Phase 88 工人第一次啟動時會拿到它，然後發現 S3 上的 input 已經不在了
> ——雖然工人有處理這種情況（總覽 §2.6 第 2 步：只刪訊息、什麼都不寫），
> 但那會在 log 裡留下一則莫名其妙的紀錄，除錯時很干擾。

- [x] 執行：

```bash
aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"
```

**預期輸出：** 完全沒有輸出。

- [x] 等一分鐘再確認：

```bash
sleep 60
for URL in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  echo "── ${URL##*/}"
  aws sqs get-queue-attributes --queue-url "$URL" --region "$AWS_REGION" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
done
```

**預期輸出：** 四個數字全部是 `"0"`。

```text
┌─ ⚠ purge 的兩個 60 秒（Phase 85 §4.8 已經說過一次，這裡再提醒）──────────────┐
│ ① 刪除過程本身要花最多 60 秒 → purge 完馬上看數字，看到不是 0 是正常的。      │
│ ② **60 秒內不可以再 purge 同一條佇列** → 第二次會回                          │
│    AWS.SimpleQueueService.PurgeQueueInProgress（HTTP 400）。不要重試，等滿一分鐘。│
│ ⚠ purge 需要 sqs:PurgeQueue 權限，而 personaldocai-mac-policy **沒有**它       │
│   （清佇列是人做的事）。所以一定要先 unset 那兩個環境變數，用 admin 身分跑。   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

### 4.8 收尾②：把 `.env` 改回 `off`、開關撥回「本機」

> ⚠ **本節由 controller 親自執行**（裁決 R3／R5）。這是最容易忘的一節。

- [x] 編輯 `/Users/linjunting/personalDocAI/.env`，把兩行改回：

```ini
CLOUD_ROUTE=off
CLOUD_RESULT_TIMEOUT_SECONDS=300
```

- [x] restart 並確認：

```bash
cd /Users/linjunting/personalDocAI
docker compose -f compose.yaml -f compose.dev.yaml restart worker
docker compose exec worker python -c \
  "from app.core import config; print('CLOUD_ROUTE =', config.CLOUD_ROUTE, '| 逾時 =', config.CLOUD_RESULT_TIMEOUT_SECONDS)"
```

**預期輸出：**

```text
CLOUD_ROUTE = off | 逾時 = 300
```

- [x] **把頁首的 AI 開關撥回「本機」**（步驟 0 撥去雲端的那一顆；`local` 是預設值，
      不撥回來的話之後每一次上傳都會走 Ollama Cloud、算的是別人的錢）：

```bash
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'
curl -sk https://127.0.0.1:8000/settings/ai-backend
```

**預期輸出：** 兩行都是 `{"backend":"local","cloud_configured":true}`

> 📌 這個狀態本來就存在記憶體、重啟 app 就會回 `local`——但**不要靠重啟去還原**：
> 現在是開發模式（`--reload`），app 什麼時候重啟不由你決定，中間那段時間就是雲端在跑。

> **為什麼一定要改回來**（總覽 §10.1 追認項 l）：
> `assume` **不做任何探測**。留著它的話，之後每一張非敏感照片都會先送上 S3、
> 然後傻傻等到逾時才 fallback——**每張白白多花 5 分鐘**，而且 S3 上會一直有殘骸進出。
> 真正的日常模式是 `ec2`（Phase 89 做探測、Phase 92 才在 `.env` 切過去）。
> 在那之前，`off` 是唯一正確的值。

---

### 4.9 `LAUNCH.md` §9 新增 "S3 / SQS layer" 小節（**英文**）

> `LAUNCH.md` 與 `README.md` 自 2026-08-27 起是**英文**（總覽 §3.8）。
> 這一節要放在 §9 Monitoring and logs 裡，**接在 "Redis layer" 之後、"app layer" 之前**
> ——順序是「由外而內」：Docker → Celery/worker → Redis → **S3/SQS** → app。
>
> ✅ **2026-09-02 實查**：`LAUNCH.md` 共 498 行，`## 9. Monitoring and logs` 在 L296，
> 底下依序是 `### Docker layer (are the services alive)`（L309）、
> `### Celery / worker layer (what is happening to the photos)`（L319）、
> `### Redis layer (the queue and progress data themselves)`（L338）、
> `### app layer (the ask flow and the camera)`（L360）。
> **§9 已經存在，不必新增章節**；下面那個「插在 `### app layer` 之前」的錨點也對得上
> （行號會隨編輯漂移，動手前用 `grep -n "### app layer" LAUNCH.md` 再確認一次）。
>
> ⚠ **這一節是實作 subagent 做得了的**（純文件、零 AWS），不必等 controller。

- [x] 打開 `/Users/linjunting/personalDocAI/LAUNCH.md`，
      在 `### app layer (the ask flow and the camera)` 這一行的**前面**插入：

````markdown
### S3 / SQS layer (the cloud route)

Only relevant when `CLOUD_ROUTE` is not `off`. With `off` (the default) nothing ever
reaches AWS, and every command below simply reports an empty, idle mailbox.

```bash
set -a; . ./.env; set +a                          # load $S3_BUCKET and the two queue URLs
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # so the CLI uses ~/.aws, not the app's key
aws sts get-caller-identity --query Arn --output text
                                                  # expect: .../personaldocai-admin

# Anything in flight right now? (a finished job cleans up after itself, so normally empty)
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'Contents[].Key' --output text

# How many messages are waiting / in flight on each queue
for URL in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  echo "-- ${URL##*/}"
  aws sqs get-queue-attributes --queue-url "$URL" --region "$AWS_REGION" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
done

# Which route did each photo take? The worker log is the only place this is visible.
docker compose logs worker | grep -E "route=|fallback="
```

How to read it:

- `documents/` empty and both queues at 0 = idle. That is the normal resting state.
- `route=local verdict=SENSITIVE` or `verdict=UNCERTAIN` — the privacy gate kept the file
  on this machine. Nothing was sent to AWS. The gate looks at the **image itself** (it is
  shown to a vision model, one short question), never at the filename, and anything it is
  not confident about stays here. That is the intended default.
- `route=cloud verdict=NON_SENSITIVE` — it went to S3 and onto the jobs queue.
- `fallback=local reason=...` — it tried the cloud route and came back. Four reasons:
  `remote_unavailable` (the instance is not running, or `CLOUD_ROUTE=off`),
  `submit_failed` (S3 or SQS refused),
  `result_timeout` (nobody answered within `CLOUD_RESULT_TIMEOUT_SECONDS`),
  `redelivered_without_result` (the task was retried but no result was on S3).
  In every case the photo still lands in the inbox exactly as it would have without AWS —
  that is the whole point of the design.
- Objects left under `documents/` for more than a few minutes mean a cleanup was missed.
  They are harmless: the bucket lifecycle rule expires everything under that prefix after
  two days.
- Messages piling up on `personaldocai-jobs` mean nobody is consuming them (no worker
  running). Clear them with
  `aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"`
  — once per 60 seconds at most, and it takes up to a minute to take effect.

`ApproximateNumberOfMessages` is approximate on purpose: SQS is distributed, so the
number lags a send or a delete by up to a minute. Wait before concluding anything.
````

**預期結果：** `LAUNCH.md` 多這一節，其他內容一個字都沒動。

**做錯了怎麼退回：** `git diff LAUNCH.md` 看一眼；插錯位置就 `git checkout -- LAUNCH.md` 重來。

---

### 4.10 不 commit——記快照

> ⚠ **總覽 §7 鐵律 12：commit 節奏由產品負責人決定。**
> 2026-09-02 的指示是**不 commit**（裁決 R0）——**不要 `git add`、不要 `git commit`、
> 不要 `git stash`、不要 `git mv`**。審查改用「工作樹快照的 tree SHA 相減」。

- [x] 收工時記下這一份工作樹的快照（**不建 commit、不動 index**，只在物件庫多一顆 tree）：

```bash
cd /Users/linjunting/personalDocAI
.superpowers/sdd/phase0902-1/snapshot-tree      # 印出一顆 40 字元的 tree SHA，記進 ledger
git status --short -- app tests LAUNCH.md       # 看變更恰為下面那四個檔
```

**預期：** `git status --short` 恰好列出四個檔——

```text
 M app/dependencies.py
 M tests/unit/test_cloud_ingest_unit.py
?? tests/unit/test_dependencies_cloud_unit.py
 M LAUNCH.md
```

（`.env` 不入版控所以不會出現；`data/` 被 `.gitignore` 擋掉也不會出現。
review 時用 `git diff -U10 <開工的 tree> <收工的 tree>`，
或 `.superpowers/sdd/phase0902-1/review-package-tree <A> <B> <輸出檔>`。）

---

## 5. ASCII 圖

### 圖一：`get_cloud_route()` 的三種模式各回什麼

```text
                       .env 的 CLOUD_ROUTE
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
      "off"               "assume"                "ec2"
   （預設；pytest        （★ 本 phase）          （Phase 89）
     與新 clone）
        │                     │                     │
        ▼                     ▼                     ▼
  CloudRouteOff()      CloudRoute(               CloudRoute(
    available()          AwsMailbox(...),          AwsMailbox(...),
    恆 False             AlwaysRunning(),          Ec2Probe(mailbox, instance_id,
    其餘方法 raise       timeout_seconds=            ttl_seconds=60),
                           config.CLOUD_          timeout_seconds=…)
                           RESULT_TIMEOUT_
                           SECONDS)                    │
        │                     │                        │
        ▼                     ▼                        ▼
  永遠 fallback 本機    永遠說「遠端可用」，      每次先問 DescribeInstances
  （行為＝增量五）      送出去等到逾時才知道      （60 秒快取），不是 running
                                                  就直接 fallback，不白等

  ⚠ 本 phase 只做中間那一支。右邊那一支仍然 raise NotImplementedError("Phase 89")。
```

### 圖二：本 phase 煙霧的時間軸（**故意沒有工人**）

```text
  t=0s     curl -F file=@receipt-test.png  ──▶  POST /photos
           ├─ 格式檢查 → 寫 data/staging/{job_id}.png → 建 job → 丟 Celery
           └─ 回 202 {"job_id","filename","content_type"}         ← 使用者只看到這個

  t≈0s     worker 撿到 job → run_gated_ingest_job()
           ├─ gate.classify(...)：讀圖 → 縮到長邊 512 → VLM 短問 → NON_SENSITIVE
           │     ⚠ 判定看的是**圖的內容**，`del filename`——檔名叫什麼都一樣
           │     （開關撥雲端約 0.7 秒；本機約 100 秒）
           ├─ cloud.available() → AlwaysRunning → True
           └─ log: route=cloud verdict=NON_SENSITIVE

  t≈1s     cloud.submit()
           ├─ PutObject documents/{id}/context.json     ← ★ 看得到
           ├─ PutObject documents/{id}/input.png        ← ★ 看得到
           └─ SendMessage → [jobs 佇列] 1 則             ← ★ 看得到

  t=1〜31s  cloud.wait_result()：長輪詢 results 佇列…
           ⋯⋯⋯ 沒有任何工人在跑，results 永遠是空的 ⋯⋯⋯

  t≈31s    deadline 到（CLOUD_RESULT_TIMEOUT_SECONDS=30）
           ├─ cloud.cleanup() → 刪掉那三個（其實只有兩個）S3 物件
           ├─ store.update(route="local")
           └─ log: fallback=local reason=result_timeout      ← ★ 契約字樣

  t≈31s    run_ingest_job()  ← 完全就是增量五那條路
           ├─ 看圖（開關撥雲端約 0.8 秒；本機 gemma4 要 64〜88 秒）
           ├─ 本機 embed（bge-m3，永遠本機）
           ├─ INSERT photo → 存原圖 → 產縮圖 → UPDATE 路徑
           ├─ 刪 data/staging/{job_id}.png
           └─ store.delete(job_id)     ＝「成功」的唯一寫法

  t≈40s    ✅ 待決定牆 +1、進度面板那一列自己消失、S3 是空的、job 不見了
  （本機   ⚠ jobs 佇列裡那一則**還在**（沒人消費）→ §4.7 用 purge 清掉
   ≈120s）

  ★ 使用者從頭到尾看到的：202 → 進度面板 → 待決定牆。與增量五逐字相同。
    整條雲端路壞掉（根本沒有工人），他完全不知道——這就是 D10 要的效果。
```

---

## 6. 驗收清單

> 📌 本節所有 `aws` 指令都假設你還在 §4.5 步驟 3 那個終端機（已經 `set -a; . ./.env; set +a`
> 載入 `$S3_BUCKET`／兩個佇列 URL／`$AWS_REGION`，**而且** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`
> 讓 CLI 用 default profile 的 admin 身分——**不帶 `--profile`**，`~/.aws` 只有 `[default]`）。
> 換了視窗就把那三行再跑一次；`aws sts get-caller-identity --query Arn --output text`
> 的結尾要是 `user/personaldocai-admin`。這只管你的 shell，worker 容器一律不動。
>
> ⚠ **凡是帶 `aws`、改 `.env`、`restart`、上傳的條目，都由 controller 親自核對**（裁決 R3）；
> 實作 subagent 負責的是「不帶 aws」的那幾條（測試、grep、ruff、`git status`）。

- [x] **開工基線已實查**：`pytest -q` ＝ 640 passed ＋ 0 skipped
      （640 ＝ 2026-09-02 實查的 624 ＋ Phase 83 的 16；總覽 §9 寫的 632 已過期）

- [x] **新測試 2 顆全綠**

  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest tests/unit/test_dependencies_cloud_unit.py -v
  ```
  預期最後一行：`2 passed`

- [x] **這兩顆真的在測原版函式**（把 `assume` 那一支暫時改回
      `raise NotImplementedError("x")`，跑一次應該是 **2 failed**；確認會紅之後改回來）

  ```bash
  pytest tests/unit/test_dependencies_cloud_unit.py -q
  ```
  這一招驗的是「早綁定有沒有生效」——兩顆若在改壞之後仍然綠，
  代表你拿到的是安全網的假件，測試等於沒有在測（見 §7 陷阱 3）。

- [x] **Phase 77 的鬧鐘只剩 `ec2` 那半，而且那顆測試仍然綠（含「打錯字要炸」）**

  ```bash
  grep -n '"assume", "ec2"' tests/unit/test_cloud_ingest_unit.py || echo "OK：assume 那半已拆"
  grep -n "NotImplementedError" tests/unit/test_cloud_ingest_unit.py
  pytest "tests/unit/test_cloud_ingest_unit.py::test_get_cloud_route預設off時回CloudRouteOff" -q
  ```
  預期：`OK：assume 那半已拆`；第二條只剩 `ec2` 那一處；`1 passed`
  （它同時驗了 `off` → `CloudRouteOff` 與 `cloudy` → `ValueError`——後者證明本 phase
  沒把「打錯字要當場炸」改壞）。

- [x] **`get_cloud_route()` 的 `assume` 分支已實作，`ec2` 仍是 `NotImplementedError`**

  ```bash
  grep -n -A 60 "def get_cloud_route" app/dependencies.py | grep -E "assume|ec2|NotImplementedError|AwsMailbox|AlwaysRunning|raise ValueError"
  ```
  預期看得到：`assume` 分支裡有 `AwsMailbox` 與 `AlwaysRunning`；
  `ec2` 那一支仍然是 `raise NotImplementedError("CLOUD_ROUTE=ec2 要等 Phase 89 …")`；
  最後一行仍是 `raise ValueError(...)`（`-A 60` 是因為 docstring 很長，30 行會被截掉）。

- [x] **boto3 相關的 import 寫在函式裡面，不在檔案最上面**

  ```bash
  grep -nE "^(from|import) .*(boto3|aws_mailbox)" app/dependencies.py || echo "OK：檔案最上面沒有"
  grep -n "    from app.services.aws_mailbox import AwsMailbox" app/dependencies.py
  ```
  預期：第一條印 `OK：檔案最上面沒有`；第二條命中一行（**有縮排**＝在函式裡）。

- [x] **`boto3` 仍然只在 `aws_mailbox.py`**（本 phase 沒有破壞 Phase 83 的規則）

  ```bash
  pytest "tests/unit/test_aws_mailbox_unit.py::test_boto3只在aws_mailbox裡出現" -q
  ```
  預期：`1 passed`

- [x] **全量測試 ＝ 開工基線 ＋ 2**

  ```bash
  pytest -q
  ```
  預期：`642 passed`（fix wave 後實查 **644**），**0 skipped**
  📌 2026-09-02 review fix wave 之後：**644**（本檔 +1、Phase 83 +1）。

- [x] **零外部依賴實證（三個死埠一起指，顆數不變）**

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```
  預期：`642 passed`（fix wave 後實查 **644**）（與上一條一模一樣）。
  ★ 這一條在本 phase 特別重要：`get_cloud_route()` 現在**有能力**建出真的 AWS client，
  顆數不變就代表第五道安全網真的擋住了。

- [x] **端點仍是 22 支、openapi 零 DELETE**

  ```bash
  pytest tests/integration/test_nav_header.py::test_端點數仍為22 \
         "tests/integration/test_design5_error_paths.py::test_端點恰好是這22支" -q
  ```
  預期：`2 passed`

- [x] **★ 真 AWS 逾時煙霧四格全對**（人工，**controller 親自執行**；證據就是 §4.5 的輸出）

  | 格 | 要看到什麼 |
  |---|---|
  | 上傳 | `POST /photos` 回 **202**，body 恰三鍵（**不是** 5xx——design6 §0 禁止第 6 條） |
  | 送出當下 | S3 有 `documents/{job_id}/context.json` 與 `input.png` 兩個物件；jobs 佇列 `ApproximateNumberOfMessages` ≈ **1**；results 佇列 **0** |
  | 30 秒後 | worker log 有 `route=cloud verdict=NON_SENSITIVE` **與** `fallback=local reason=result_timeout` 兩行（`verdict` 是**看圖內容**判的，不是檔名） |
  | 做完 | `GET /ingest-jobs` 的 `jobs` 陣列裡沒有那一筆（＝成功）；`photo` 表 **+1**；`documents/` 的 `KeyCount` 回到 **0**；待決定牆 +1 |

- [x] **★ 敏感檔煙霧：零 S3**（人工，**controller 親自執行**；圖的**內容**是證件，不是靠檔名）

  ```bash
  aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
    --region "$AWS_REGION" --query 'KeyCount'
  docker compose logs --tail=100 worker | grep -E "route=|fallback="
  ```
  預期：`KeyCount` 是 `0`；log **只有** `route=local verdict=SENSITIVE`，
  **沒有** `fallback=`（它根本沒去試雲端）。

- [x] **兩條佇列都清乾淨了**（等一分鐘再看）

  ```bash
  sleep 60
  for URL in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
    aws sqs get-queue-attributes --queue-url "$URL" --region "$AWS_REGION" \
      --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
      --query 'Attributes' --output json
  done
  ```
  預期：四個數字全部 `"0"`

- [x] **★ `.env` 已改回 `off`、頁首開關已撥回 `local`**（最容易忘的一條；**controller 親自執行**）

  ```bash
  grep -n '^CLOUD_ROUTE=' /Users/linjunting/personalDocAI/.env
  grep -n '^CLOUD_RESULT_TIMEOUT_SECONDS=' /Users/linjunting/personalDocAI/.env
  docker compose exec worker python -c \
    "from app.core import config; print(config.CLOUD_ROUTE, config.CLOUD_RESULT_TIMEOUT_SECONDS)"
  ```
  預期：`.env` 是 `CLOUD_ROUTE=off` 與 `CLOUD_RESULT_TIMEOUT_SECONDS=300`；
  容器印出 `off 300`。

  ```bash
  curl -sk https://127.0.0.1:8000/settings/ai-backend
  ```
  預期：`{"backend":"local","cloud_configured":true}`

- [x] **`LAUNCH.md` 有新小節，而且是英文**

  ```bash
  grep -n "S3 / SQS layer" /Users/linjunting/personalDocAI/LAUNCH.md
  grep -n "### app layer" /Users/linjunting/personalDocAI/LAUNCH.md
  ```
  預期：兩行都命中，而且 **`S3 / SQS layer` 的行號比 `### app layer` 小**（放在它前面）。

- [x] **專案的 `data/` 沒被弄髒**（煙霧上傳的兩張照片是**正常入庫**，
      不算弄髒；要檢查的是 staging 有沒有孤兒）

  ```bash
  cd /Users/linjunting/personalDocAI
  ls data/staging/ | wc -l                 # 預期：0（成功或最終失敗都會刪掉暫存檔）
  find data/staging -type f -mmin +60      # 預期：沒有輸出（沒有一小時以上的孤兒）
  git status --short data/                 # 預期：零輸出（.gitignore 擋掉了）
  ```

- [x] **格式與 lint 過**

  ```bash
  ruff format --check app tests scripts && ruff check app tests scripts
  ```
  預期：`All checks passed!`

- [x] **機密沒有進 repo**

  ```bash
  cd /Users/linjunting/personalDocAI
  git status --short | grep -E '(^|/)\.env$' && echo "⛔ 停手" || echo "OK：.env 沒進版控"
  grep -rn "sqs\.ap-northeast-1\.amazonaws\.com/[0-9]\|personaldocai-mailbox-[0-9]" \
    docs/ deploy/ scripts/ app/ tests/ CLAUDE.md README.md LAUNCH.md 2>/dev/null \
    && echo "⛔ 有檔案寫死了資源名稱" || echo "OK：沒有寫死"
  ```
  預期：兩行都印 `OK：…`

- [x] **`docs/spec/` 一字未動**

  ```bash
  git status --short docs/spec/
  ```
  預期：零輸出

- [x] **git 收尾＝不 commit、記快照**（2026-09-02 的指示；裁決 R0）

  ```bash
  cd /Users/linjunting/personalDocAI
  git status --short -- app tests LAUNCH.md    # 變更恰為那四個檔
  .superpowers/sdd/phase0902-1/snapshot-tree   # 收工的 tree SHA，記進 ledger
  ```
  預期：`git status --short` 恰四行（`app/dependencies.py`、兩個 `tests/unit/` 的檔、
  `LAUNCH.md`）；**沒有** `git add`／`git commit`／`git stash` 的痕跡
  （`git log -1 --format=%H` 仍然是開工時的那顆）。

---

## 7. 常見陷阱

1. **症狀：** 煙霧做完幾天後，每一張非敏感照片都要多等五分鐘才進待決定牆。
   **原因：** `.env` 的 `CLOUD_ROUTE` 還停在 **`assume`**。
   `assume` **不做任何探測**，所以它每次都會傻傻地送上 S3、然後等到
   `CLOUD_RESULT_TIMEOUT_SECONDS`（預設 300 秒）才 fallback——而根本沒有工人在跑。
   **正解：** §4.8 一定要做完。日常正確的值是 `off`（Phase 92 之後才換成 `ec2`）。
   §6 驗收清單特別把它列成一條，就是因為這是最容易忘的一步。

2. **症狀：** 改了 `.env`，但 log 完全沒有 `route=` 那一行，行為跟改之前一模一樣。
   **原因：** 忘了 `docker compose restart worker`。
   `get_cloud_route()` 是 **worker 行程**在呼叫的，而行程只在啟動時讀 `.env`。
   （順帶一提：`app` 容器也讀 `.env`，但雲端路完全不經過它——上傳端只負責收檔與入列。）
   **正解：**
   ```bash
   docker compose -f compose.yaml -f compose.dev.yaml restart worker
   docker compose exec worker python -c "from app.core import config; print(config.CLOUD_ROUTE)"
   ```
   ⚠ 另外：**改 `app/` 底下的 `.py` 之後 worker 也不會自己 reload**（Celery 沒有 `--reload`），
   `CLAUDE.md` 早就記過這件事——症狀是「HTTP 行為已是新碼、照片分析卻還是舊行為，而且完全不報錯」。

3. **症狀：** 那兩顆新測試一開始就是綠的（還沒實作就綠了）。
   **原因：** 測試裡寫成 `dependencies.get_cloud_route()`（模組屬性存取），
   於是拿到的是第五道安全網 `wire_fake_cloud` 換上去的假件——它永遠回 `CloudRouteOff()`。
   **正解：** 一定要用檔案最上面的
   `from app.dependencies import get_cloud_route as real_get_cloud_route`（早綁定）。
   §6 驗收清單有一條「故意改壞看它紅」就是在驗這件事。
   ⚠ 注意這與產品碼的規則**相反**：產品碼要用模組屬性存取（才 monkeypatch 得到），
   這裡是刻意要「換不到」。測試的 docstring 一定要寫清楚，免得日後被「順手改成一致」。

4. **症狀：** `pytest --collect-only` 忽然變慢，或 CI 上出現與 boto3 有關的錯誤。
   **原因：** 有人把 `from app.services.aws_mailbox import AwsMailbox` 搬到
   `app/dependencies.py` 的**檔案最上面**。那會讓每一次 import `dependencies`（也就是
   幾乎每一顆測試）都連帶載入 boto3 與整包 botocore 的服務模型。
   **正解：** 寫在 `get_cloud_route()` **函式裡面**（總覽 §7 鐵律 5；
   既有的 `get_task_dispatcher()` 對 Celery 用的是同一招）。

5. **症狀：** 上傳之後去看 S3，什麼都沒有，以為「根本沒送出去」。
   **原因：** **動作太慢**。逾時只有 30 秒，超過之後 `cleanup()` 已經把物件刪光了。
   **正解：** 上傳前就先把那條 `list-objects-v2` 貼在另一個終端機視窗準備好，
   `curl` 一回 202 就馬上按 Enter。
   真的錯過了也沒關係——log 那兩行（`route=cloud` ＋ `fallback=…result_timeout`）
   已經是完整的證據。想再看一次就把 `CLOUD_RESULT_TIMEOUT_SECONDS` 暫時調成 120 再傳一張。

6. **症狀：** `aws sqs purge-queue` 回 `AccessDenied ... sqs:PurgeQueue`
   （`list-objects-v2` 用 `.env` 那把 key 其實跑得過，所以通常卡到 purge 才發現）。
   **原因：** 用到了 `.env` 裡那把最小權限的 key（`set -a; . ./.env` 會把它載進 shell）。
   `personaldocai-mac-policy` **沒有** `sqs:PurgeQueue`（清佇列是**人**做的事）；
   它**有** `s3:ListBucket`（總覽 §10.2 P——沒有它 GetObject 缺 key 會回 403 而不是 404）。
   **正解：** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` 之後再跑，
   並用 `aws sts get-caller-identity --query Arn --output text` 確認是
   `:user/personaldocai-admin`。
   ⚠ **不要試著用 `--profile personaldocai-admin` 解決**：`~/.aws` 裡只有 `[default]`，
   沒有那個名字的 profile，只會多拿到一個 `ProfileNotFound`。
   身分是靠「環境變數裡有沒有那兩把 key」決定的，不是靠 profile 名字。

7. **症狀：** log 印的是 `route=local verdict=UNCERTAIN`，不是 `NON_SENSITIVE`。
   **原因：** 閘門看不清楚這張圖，**跟檔名一點關係都沒有**——`VlmGate.classify()`
   第一行就是 `del filename`（2026-09-01 改判；`NON_SENSITIVE_KEYWORDS` 這個名字
   在現行程式碼裡**已經不存在**，看到還這樣寫的文件就是過期的）。
   `UNCERTAIN` 只有兩種來源：① 模型回 `sensitive=false` 但 `confident=false`；
   ② 讀檔／PDF 渲染／縮圖／呼叫模型其中一步炸了（每一條都會留一行
   `隱私閘門判斷失敗，當作 UNCERTAIN` 的 warning）。
   **正解：** 先去 worker log 找那一行 warning 分辨是①還是②。
   是①就把圖畫得更清楚（§4.5 步驟 1 已經是 512 寬、字級 28 以上），或改用一張真收據照片。
   ⚠ **`UNCERTAIN` 走本機是「正確」行為**（D3：不確定當敏感辦），只是你沒驗到雲端那條路。

8. **症狀：** fallback 之後 job 變成 `failed`，待決定牆沒有 +1。
   **原因：** 多半**不是** fallback 壞掉，而是 **VLM 真的看不懂那張圖**
   （例如你用程式產的純色／純文字圖）——連續三次看不懂＝整筆失敗，
   這是增量五 D10 就有的行為。
   **正解：** 用一張真的照片（真收據、真菜單都行）；或把頁首開關撥到雲端
   （§4.5 步驟 0，雲端模型讀合成圖上的英文字比本機 gemma4 穩）。
   要分辨是哪一種：log 裡有沒有 `fallback=local reason=result_timeout`——
   有，就代表 fallback 這一段是好的，failed 是後面看圖那一段的事。

9. **症狀：** `ApproximateNumberOfMessages` 顯示 0，但你明明剛送出一則。
   **原因：** 名字裡的 **Approximate 是認真的**——這個數字會落後最多一分鐘。
   **正解：** 等一下再看；或用 `aws sqs receive-message --wait-time-seconds 5`
   直接把它撈出來看（⚠ 撈出來它會隱形 900 秒）。

10. **症狀：** 以為 `POST /photos` 回 202 就代表照片已經入庫，於是馬上去待決定牆找，
    找不到就以為壞了。
    **原因：** **202 不是 201**（增量五起就是這樣）。它只代表「檔案收下了、排進佇列了」。
    **正解：** 這一刻資料庫的 `photo` 表列數**不變**、待決定牆上也不會有東西。
    要看進度：`curl -sk https://127.0.0.1:8000/ingest-jobs`。
    這一次還先白等了 30 秒的雲端逾時，之後才開始看圖——開關撥雲端約再 5 秒、
    忘了撥（本機 gemma4）則要再 64〜88 秒，**所以 40 秒到兩分鐘才出現都是正常的**。

11. **症狀：** 實作完 `assume` 之後跑全量，
    `tests/unit/test_cloud_ingest_unit.py::test_get_cloud_route預設off時回CloudRouteOff` 紅了，
    錯誤是 `Failed: DID NOT RAISE <class 'NotImplementedError'>`。
    **原因：** 那是 Phase 77 刻意留的**鬧鐘**（`assume` 還沒接時要 raise）——現在接上了，鬧鐘就響。
    **正解：** §4.3 的第二個勾選框——只拆 `assume` 那半；`ec2` 那半與 `cloudy → ValueError` 都留著。
    **不要**為了讓它綠而把 `get_cloud_route()` 的 `assume` 改回 raise、也不要整顆測試刪掉
    （刪了「打錯字要炸」就沒人守了）。

12. **症狀：** 待決定牆上的縮圖看起來正常，但 `data/photos/` 裡多出來的那個 `.png`
    用 `file` 看是 `JPEG image data`。
    **原因：** 步驟 1 用 `cp` 把 `.jpg` 直接改名成 `.png`。curl 依副檔名送 `image/png`，
    整條路（staging 副檔名、S3 鍵名 `input.png`、落地原圖）都照 PNG 記，內容卻是 JPEG。
    Pillow 讀縮圖時看的是內容所以不會炸，這件事因此**安靜地**發生。
    **正解：** 步驟 1 那段 Pillow 轉檔（`Image.open(...).convert("RGB").save("....png")`），
    轉完用 `file` 看一眼是 `PNG image data`。

13. **症狀：** 明明照 §4.5 步驟 0 把開關撥到雲端了，worker 的 log 卻印
    `AI 開始 kind=privacy backend=local`，整段煙霧還是慢得像走路。
    **原因：** 撥開關的時機不對，或中途重啟了 app。這個狀態是
    **`POST /photos` 那一刻**被抄進 job 的（`ai_backend=config.AI_BACKEND`），
    worker 之後只認 `job["ai_backend"]` 那份快照——**上傳之後才撥，對這一筆完全沒用**；
    而 `config.AI_BACKEND` 存在 app 行程的記憶體裡，**app 一重啟就回到 `local`**
    （開發模式有 `--reload`，改到任何 `app/` 的 `.py` 都會重啟）。
    **正解：** 上傳前先 `curl -sk https://127.0.0.1:8000/settings/ai-backend` 看一眼是不是
    `cloud`，不是就再撥一次，然後**馬上**上傳。

14. **症狀：** 煙霧全部做完幾天後，才發現 Ollama Cloud 的用量一直在跑。
    **原因：** §4.8 只改了 `.env` 的 `CLOUD_ROUTE`，忘了把**頁首開關**撥回 `local`。
    那扇門管的是四個注入點加隱私閘門，跟 `CLOUD_ROUTE` 是**兩件事**——
    `CLOUD_ROUTE=off` 只是「不把檔案送去 AWS」，看圖仍然可以是 Ollama Cloud。
    **正解：** §4.8 最後那一條 `PUT {"backend":"local"}` 一定要做，
    並用 `GET /settings/ai-backend` 確認。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

- `app/dependencies.py` 的 `get_cloud_route()` 現在**認得 `assume`**：
  它會建一個真的 `AwsMailbox`（bucket、兩條佇列 URL、region 全部從 `config` 即時讀）、
  搭配 `AlwaysRunning()` 探測、逾時秒數來自 `config.CLOUD_RESULT_TIMEOUT_SECONDS`。
  boto3 的 import 寫在函式裡面。
- 新檔 `tests/unit/test_dependencies_cloud_unit.py`（**2 顆**，一次 AWS API 都不打）。
- `tests/unit/test_cloud_ingest_unit.py` 的 `test_get_cloud_route預設off時回CloudRouteOff`：
  鬧鐘只剩 `ec2` 那半（Phase 89 拆），`off → CloudRouteOff` 與 `cloudy → ValueError` 兩段原封不動。
- `LAUNCH.md` §9 多一個英文小節 **"S3 / SQS layer (the cloud route)"**：
  怎麼看 S3 有沒有東西、兩條佇列各有幾則、每一張照片走了哪條路。
- **一次真 AWS 煙霧的證據**：**內容**非敏感的照片真的上過 S3 與 jobs 佇列、
  30 秒後真的 fallback 回本機、S3 真的被清乾淨、照片真的進了待決定牆；
  **內容**敏感的照片**零 S3 呼叫**（兩者都是閘門看圖判的，與檔名無關）。

**對外行為變了沒：完全沒有。**

煙霧做完 `.env` 已經改回 `CLOUD_ROUTE=off`（頁首 AI 開關也撥回 `local`），
所以 `get_cloud_route()` 又回到 `CloudRouteOff()`——**日常使用時一張照片都不會出門**。
上傳、待決定、詢問、進度面板一個像素都沒變。
端點仍是 **22** 支、openapi 零 DELETE、`photo` 表零改動、前端零改動、
`compose.yaml` 零改動、`docs/spec/` 一字未動。

**這一步真正證明了什麼（★ 本 phase 的價值）：**

| 已證明 | 證據 |
|---|---|
| 本機端真的送得出去（S3 ＋ SQS 都通、IAM 權限夠） | S3 上真的出現兩個物件、jobs 佇列真的多一則 |
| **雲端整條路壞掉時，使用者完全無感** | 202 照舊、進度面板照舊、照片照樣進待決定牆 |
| fallback 的 log 字樣是真的（不只是測試裡的 `caplog`） | worker log 有 `fallback=local reason=result_timeout` |
| 失敗時不留半套 | `documents/` 的 `KeyCount` 回到 0 |
| 敏感檔真的一個位元組都不出門 | 上傳一張**畫成證件**的圖之後 S3 仍然是空的、log 只有 `route=local verdict=SENSITIVE`（檔名是中性的 `id-card-test.png`，證明擋下來的是**內容**） |

**還沒有的東西**（刻意的）：**沒有工人**（jobs 佇列的訊息沒有人消費，Phase 87／88 才有）、
沒有 `ec2` 探測（Phase 89）、沒有 EC2（Phase 91／92，而且要先過 ★G2）。

**下一個 phase：Phase 87「`cloud_worker` 核心」**——
寫 `app/workers/cloud_worker.py` 的 `process_job_message()`：
收 jobs 訊息 → 冪等檢查（`result.json` 已存在就跳過）→ 從 S3 拿 `input` 與 `context` →
用 `OllamaCloudVLM` 看圖（最多 3 次）→ **先** `PutObject result.json`、**才** `send_result` →
刪掉 jobs 訊息。全部用 `FakeMailbox` 測（**不連網**），
還有兩顆**端到端**測試：本機送出 → 假工人處理同一顆 `FakeMailbox` → 本機收回入庫（單圖與 PDF 各一）。

**顆數：** 開工基線 **640** ＋ **2** ＝ **642**（0 skipped）。

**2026-09-02 review fix wave**：+1 顆 `test_assume模式把config的四個值對應到AwsMailbox`
（側錄 `app.services.aws_mailbox.AwsMailbox` 這個**模組屬性**——延遲 import 在呼叫當下才解析，
所以換得掉；四個 config 值刻意彼此不同，斷言四個 keyword 逐一對得上、**兩條佇列 URL 沒有對調**。
變異證據＝把 `dependencies.py` 的兩條 URL 暫時對調就會紅）、
`LAUNCH.md` §S3 / SQS layer 兩處措辭（`off` 模式下 worker log 仍會有 `route=local` 與
`fallback=local reason=remote_unavailable`＝正常；`set -a` 那行的註解補上 `$AWS_REGION`）、
`test_aws_mailbox_unit.py` 的掃碼測試加守「`app/dependencies.py` 檔頭不得 import `aws_mailbox`」
（提到檔頭會讓 pytest 收集階段間接載入 boto3，而原本的樣式只認直接 `import boto3` 的檔）。
本檔的顆數因此是 **+3**、全量 **644**。
（總覽 §9 Phase 86 那一列寫的是 634——那是 2026-08-31 的估算值，**已過期**；
要對的是「本 phase 新增 2 顆」，不是絕對數字。）
（Phase 77 那顆鬧鐘測試只改內容、不增不減。）

---


## 8.1 執行紀錄（2026-09-02，煙霧由 controller 親自執行；值不寫進文件）

- 前置：`open -a Ollama`（0.33.2，embeddings 本機）；頁首開關 `PUT /settings/ai-backend` 撥 **cloud**（閘門與看圖跟開關走，快 20 倍）；`.env` `CLOUD_ROUTE=assume`／`CLOUD_RESULT_TIMEOUT_SECONDS=30`、`docker compose -f compose.yaml -f compose.dev.yaml restart worker` → worker 內 `get_cloud_route()` 回 `CloudRoute`、`available()=True`；起點 S3 documents/ 空、兩佇列 0／0、正式庫 64 張。
- 逾時腿：上傳 Pillow 合成收據（內容非敏感）→ **202**；t≈6s S3 出現 `context.json`＋`input.png`、jobs 紙條 body 恰 `{"job_id","s3_key"}`（無位元組）、results 0；log `route=cloud verdict=NON_SENSITIVE` → 33 秒後 `fallback=local reason=result_timeout` → job 被刪（成功）、照片 65、S3 documents/ 空、jobs 剩 1 則沒人接的紙條。
- 敏感腿：上傳 Pillow 合成假身分證 → **202** → log `route=local verdict=SENSITIVE` → 該 job S3 前綴零物件、results 0 → ~5 秒後入庫（照片 66）。
- 收尾：`aws sqs purge-queue` jobs → 60 秒後兩佇列 0／0；`.env` 改回 `off`／`300`＋restart worker（讀到 `CloudRouteOff`）；開關撥回 local；S3 空。
- 全量／三死埠／端點等數字見 §6（最終驗證於 review fix wave 後由 controller 跑；R11 fix wave 讓 83 的測試檔 +1、本檔測試 +1 → 全量 **644**；controller 最終驗證 644／0 skipped、三死埠 644）。

## 附：本文件引用的官方文件

**boto3 / AWS SDK**

- [boto3 憑證與環境變數（環境變數優先於 `~/.aws`）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
- [boto3 設定（含 `AWS_ENDPOINT_URL` 這個標準環境變數）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html)
- [boto3 S3 client：`put_object`／`get_object`／`delete_objects`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html)
- [boto3 SQS client：`send_message`／`receive_message`／`delete_message`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sqs.html)

**AWS CLI（煙霧用到的指令）**

- [`aws s3api list-objects-v2`](https://docs.aws.amazon.com/cli/latest/reference/s3api/list-objects-v2.html)
- [`aws sqs get-queue-attributes`](https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-attributes.html)
- [`aws sqs receive-message`](https://docs.aws.amazon.com/cli/latest/reference/sqs/receive-message.html)
- [`aws sqs purge-queue`（60 秒內只能一次；刪除過程最多 60 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
- [`aws sts get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)

**SQS 行為**

- [SQS 短輪詢與長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS 可見度逾時](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [SQS Standard Queue（at-least-once，所以要冪等）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html)

**pytest**

- [`monkeypatch`（`setattr` 會在測試結束自動還原）](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)

**Celery**

- [Celery 沒有 `--reload`：改了程式碼要重啟 worker](https://docs.celeryq.dev/en/stable/userguide/workers.html)
