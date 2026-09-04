# Phase 95：增量六錯誤收尾與驗收包

> 📌 **2026-09-03 夜裡校準（接 92〜94 同日拍板；本 phase 仍要等 74〜94 全綠）：**
>
> - **★G1／★G2／★G3 都已由產品負責人通過**（G3 憑據：commit `c40a3b3` 的 Phase 92-A 三份文件、
>   `CLAUDE.md` 概述「92-A CPU 機已建、Demo 2／2b 通過、日常 Stop」、dev-prompt `phase0903-1.md`
>   明示執行 93〜95）。本 phase 不再有任何閘門要等，只等 93／94 做完。
> - **顆數基線改成 702**（2026-09-03 controller 實查全量 **692**；93 +4 → 696、94 +6 → 702）。
>   全檔舊的 662／666／672／682 一律作廢，收工目標 **712**（＋§4.3.3 停放項的顆數，見 §8）。
> - **`test_design6_error_paths.py` 開工時是 16 顆**（Phase 90 的 4 ＋ 產品負責人在 `f2fc067`
>   補的 2 ＋ Phase 93 的 4 ＋ Phase 94 的 6），收工 **26 顆**。
> - **本檔碼區的識別字一律英文**（2026-09-02 產品負責人指示；`test_中文` 測試名保留）。
>   Phase 90／92 已經放進該檔的 helper 就是英文（`read_compose()`／`compose_services()`…），
>   本檔沿用，**不要**再定義中文同名的東西。
> - **§4.3.1 已經不必做**（2026-09-01 的 fix wave 早就把那兩句舊名改掉了），改成一句 `grep` 驗證。
> - 帳號已升 **Paid**。E 段「確認仍是 Free plan／未升 Paid」作廢，改成「確認是 Paid、Budget 還會寄信」。
> - 真機拆兩段（總覽 §10.2 追認項 **U**）：**92-A `t3.xlarge`**（CPU、收工 **Stop**，30 GB ≈ $2.9／月，
>   在 Budget 內、留給 Phase 94 的 Demo 3）與 **92-B `g4dn.xlarge`**（GPU、等 G and VT 配額、測完 **Terminate**）。
>   E 段／§4.6「EC2 必須是 `t4g.small` + `stopped`」改成：**沒有 running 的實例**
>   （`stopped`、`terminated`、`.env` 的 ID 已清空，三者都算過）。
>   Demo **2b 的 Stop** 仍是 G3 證據，不在本 phase 重做。
> - CD 映像是 **`linux/amd64,linux/arm64`**。已知限制「GitHub runner 模擬 arm64 很慢」仍成立（多架構的 ARM 那一半）。
> - design6 §3「EC2 不跑 GPU」隨 D12 作廢——92-B 的工人**就是** g4dn 上自裝 Ollama。
>   §8 第 10 列「誤開 GPU」**不要**掃成禁止 g4dn；掃的是 NAT／EIP／ALB／Lambda／ECS 等沒核准的服務。
> - **本 phase 不依賴 GPU 配額**：★G3 在 92-A 之後，92-B 是獨立後續。
>   配額核准與否都**不必、也不該**為了勾 E5 去開機。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別不要做的四件事：
> ① **不要**為了讓某顆測試變綠而改產品行為（這是**收尾**，不是重寫——首跑紅了＝揪到真缺陷，
> 回**對應的 phase** 修產品碼，然後重跑全量）。
> ⚠ **唯一的例外是 §4.3.3 ①**：`cloud_worker.read_context` 的型別加固（一個私有 helper
> ＋一行 warning），
> 那是前面幾輪 review 就抓到、被明確**停放**到本 phase 的項目（不是本 phase 臨時起意），
> 而且它是「先寫紅測試、再改一行」的 TDD，不是「改產品去湊已經寫好的斷言」；
> ② **不要**重複測已經有人測的東西（每一列先找「誰已經測了」，只補真正的缺口；
> 重複的測試是負債：改一次程式要改兩個地方，而且兩個地方遲早會不一致）；
> ③ **不要**動 `docs/spec/` 任何一個字（design6 §10 明文：本增量**不必**為了 fallback 改 Gherkin）；
> ④ **不要**自己 commit、不要自己把 `unfinish/` 搬進 `finish/`（歸檔隨 commit 執行，時機由產品負責人決定）。

> 🎯 **一句話目標：** 把 design6.md §8 錯誤表的 **10 列**逐列**清點到有測試把關**
>（74〜94 全程 TDD，大多數列已由各自的 phase 釘住——本檔補**兩個真缺口**）、
> 把 §0 六條禁止與 §1.2 十一列「被否決」變成**掃得出來的斷言**（8 顆）、
> 把前面幾輪 review **停放**下來的四件小事一次結清（§4.3.3，+3 顆），
> 跑一輪完整回歸（含「AWS／Redis／Ollama 三個位址一起指到死埠、顆數不變」的零依賴實證），
> 最後產出**增量六驗收包**交給產品負責人。

---

**為什麼要做這個：**

Phase 74〜94 是「把隱私閘門與可關掉的雲端 worker 做出來」。這個 phase 是
**「確認它壞的時候，壞得跟設計說好的一樣」**。

增量六特別需要這一關，因為這一次的失敗**藏在三個不同的地方**：

- **在本機的 worker 裡**（fallback 有沒有真的發生、有沒有把 S3 清乾淨）
- **在遠端的工人裡**（result 有沒有先落地才發訊息、重送有沒有被冪等擋掉）
- **在你根本看不到的地方**——**沒有發生的事**。
  「敏感照片**沒有**被上傳到 S3」這件事，成功的時候是**完全沒有訊號**的：
  沒有 log、沒有畫面變化、沒有任何人會告訴你。
  一旦閘門被改壞（例如有人把 `UNCERTAIN` 也放行），系統會**一切正常地**
  把你的身分證送到別人的機房，而且你永遠不會發現。

所以本檔的重心不是「再測一次功能」，而是**把「不該發生的事」變成看得見的斷言**：
`mailbox.put_calls == 0`、`compose 服務恰好四個`、`工人的 import 名單裡沒有 psycopg`、
`policy JSON 裡沒有 12 位純數字`。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **錯誤表** | design6.md §8 那張表：每一列是「一種出錯的情況」，寫明**誰**回應、結果應該是什麼。本 phase 把每一列清點到「有測試把關」 |
| **盤點** | 動手寫測試**之前**先做的一件事：逐列查「這一列已經有誰在測了？」。查法是翻測試檔、或 `pytest -k 關鍵字 --collect-only -q`。**點名也是把關**——已經有人測的就不要再寫一顆 |
| **真缺口** | 盤點之後發現「這一列**沒有任何人**在測」的那幾列。本檔只補這種。增量六盤下來只有**兩個** |
| **掃碼** | ⚠ **不是掃 QR code**。是用測試去**掃原始碼／設定檔**，證明「某個東西不存在」（例如：`app/` 底下沒有人寫過 `NatGateway`）。有些規則沒辦法用行為測試證明「不存在」，掃原始碼是最直接的辦法 |
| **假綠** | 測試通過了，但它其實什麼都沒測到。本檔多數斷言是**某個東西不存在**（沒有欄位、沒有服務、沒有字樣），天生容易假綠 |
| **反向驗證** | 防假綠的 30 秒動作：把斷言**暫時反過來**跑一次，確認它**會紅**，再改回來。沒紅＝那顆測試在睡覺 |
| **`ast`** | Python 內建的「把程式碼解析成語法樹」的模組。用它問一個檔案「你 import 了哪些模組」，比 `grep "import psycopg"` 準——註解裡寫了那個字不會誤判，而 `from app.db import session` 這種寫法也躲不掉 |
| **`inspect.signature`** | Python 內建工具，可以問一個函式「你的參數叫什麼、型別註記是什麼」 |
| **`information_schema`** | PostgreSQL 內建的一組唯讀檢視表，可以用 SQL 查「這個資料庫有哪些表、哪些欄位」。用它來證明 `photo` 表**沒有**多出欄位 |
| **死埠** | 沒有任何程式在監聽的通訊埠。埠 **9** 是慣例上的 discard 埠，指過去會**立刻** connection refused（而不是卡住等逾時） |
| **零依賴實證** | 把外部服務的位址故意指到死埠，再跑一次全量測試。顆數完全一樣 ＝ 證明測試從頭到尾沒有偷偷連過那個服務。增量六起要**三個一起指**：AWS、Redis、Ollama |
| **驗收包** | 一份給**產品負責人**看的勾選清單（不是給實作者的）。放在 `docs/plan/report/`，A 段是實作者已經跑出來的數字、B〜D 段要人親自點親自看、E 段是簽名 |
| **歸檔** | 計畫檔做完之後從 `docs/plan/unfinish/` 搬到 `docs/plan/finish/`。**隨 commit 執行，時機由產品負責人決定**（`git mv` 會直接 stage，自己搬等於替人決定了 commit 內容） |
| **purge（清空佇列）** | 把一條 SQS 佇列裡的訊息全部倒掉（`aws sqs purge-queue`）。手動煙霧留下的殘訊息用它清。⚠ 60 秒內只能做一次 |

---

## 1. 對應 design6.md 章節

| 出處 | 說的是什麼 | 本 phase 怎麼落地 |
|---|---|---|
| **§8 錯誤表**（10 列） | 每一種出錯情況的預期行為 | §4.1 逐列盤點（大多已由 74〜94 各自的測試檔釘住）；§4.2 補**兩個**真缺口 |
| **§0 六條禁止** | 甲沒綠不准開 AWS／影像不進 SQS／EC2 不開 inbound／不做 NAT 等／Gate 不管頁首開關／遠端不可用不准 5xx | §4.3 的 8 顆掃碼（能自動化的全部自動化）＋ §4.6 的 AWS CLI 檢查（inbound 那條要問真 AWS） |
| **§1.2「被否決」11 列** | 產品負責人**已經考慮過並否決**的方案，不是「暫時不做」 | §4.3 逐列對應（見那一節的對照表） |
| **§3「不做」6 條** | Gate 覆蓋頁首開關／EC2 跑 Postgres·Redis·Celery／S3 當備份／NAT·ALB·EIP·RDS·Lambda·ECS·Macie／常開 EC2／未核准前改 `.feature`。⚠ 「EC2 跑 GPU」原列已隨 D12 作廢——工人就是 g4dn | §4.3 ＋ §4.6 ＋ §4.9（`.feature` 零改動的證明）。掃碼**不**把 `g4dn` 當違規 |
| **§4 資料流與冪等** | 影像不進 Redis／SQS／Celery 參數；`photo` 表不加 `job_id`、不加處理狀態欄 | §4.3 的 `test_兩條佇列的訊息body都不含影像位元組`、`test_photo表沒有為了雲端新增任何欄位` |
| **§5 API 與端點** | 不新增端點；上傳仍 202；openapi 零 DELETE | §4.3 的 `test_端點仍是22支而且openapi零DELETE` |
| **§9 測試策略** | 「必釘」9 條 ＋「pytest **不連真 AWS**」 | §4.1 的盤點表把 9 條逐條點名；§4.4 的三死埠實證 |
| **§12 驗收清單** | Demo 1／2／2b／3 ＋ 費用／安全 3 條 | §4.7 的**驗收包**逐條抄錄 ＋ 每條的指令。E1＝已升 Paid；E5＝terminated／無 running |
| **§13 風險與已知限制**（7 條） | EC2 沒開就不卸壓、敏感檔仍可去 ollama.com、不會更快、Paid 會扣卡、Classifier 會漏、套件分岔。t4g 試用／Free 關帳兩條已過時 | §4.7 驗收包的「已知限制」段已改寫，**讓產品負責人在簽名之前看到** |
| **總覽 §10 誠實揭露**（§10.1 的 a〜l ＋ §10.2 的 A〜U） | design6 沒寫、由計畫層裁決的 **33** 條 | §4.7 驗收包的最後一段做成**逐條打勾的追認清單**（33 條 ＋ 本輪校準的 R0〜R11 共 12 條） |

---

## 2. 前置條件

- **Phase 74〜94 全部完成且全綠。** 這是收尾 phase，不是開發 phase。
- **★ 閘門 G1／G2／G3 都已由產品負責人通過**（G1 在 82 前、G2 在 91 前、G3 在 93 前）。
  **本次：三個都已通過**——G3 的憑據是 commit `c40a3b3`（Phase 92-A 的三份文件）、
  `CLAUDE.md` 概述寫的「92-A CPU 機已建、Demo 2／2b 通過、日常 Stop」，
  以及 dev-prompt `docs/plan/dev-prompts/phase0903-1.md` 明示執行 93〜95。
  **本 phase 沒有任何閘門要等**，唯一的前置是 93／94 做完。
- **EC2 目前沒有 running。** 92-A 那台 `t3.xlarge` 收工是 **Stop**（碟留著給 Demo 3），
  92-B 的 GPU 機（若已做）測完 Terminate。本 phase §4.6 確認
  **沒有 running 的實例**（`stopped`／`terminated`／ID 已清空都算過），**不需要、也不准**再開機。
- 本檔所有指令都在**專案根目錄**執行（`grep`／`ls`／`git` 用的都是相對路徑，
  位置跑掉就會查到別的東西、甚至誤判成「通過」）。

### 開工基線（自己再驗一次，不要抄）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# 暫存檔一律寫進 scratchpad，不要寫 /tmp（與 phase-93 §4.1 同一條規矩：
# /tmp 是全機共用的，不同 session 的檔案會互相蓋掉，而且沒有人會去清）
SCRATCH=/private/tmp/claude-501/-Users-linjunting-personalDocAI/1f4eca1f-0382-4915-97be-215ebc934bab/scratchpad
mkdir -p "$SCRATCH"

# 把 .env 的變數放進 shell（S3_BUCKET、佇列 URL、實例 ID 都要用），
# 然後**立刻拿掉那兩把 key**：.env 裡的是最小權限的 personaldocai-mac，
# 環境變數會蓋過 ~/.aws 的 default profile（personaldocai-admin），
# 留著的話 describe-nat-gateways／budgets 那幾條會撞 AccessDenied（Phase 82 §7 陷阱 1；Console 看不到 Billing 頁另見 82 §4.3／陷阱 6）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
AWS_REGION=${AWS_REGION:-ap-northeast-1}
aws sts get-caller-identity --query Arn --output text
# 預期：結尾是 :user/personaldocai-admin（不是 personaldocai-mac）

docker compose ps --no-trunc
# 預期：四列——db（Up healthy）／redis（Up healthy）／app（Up）／worker（Up）

pytest -q
# 預期：702 passed ＋ 0 skipped
#   算法：2026-09-03 controller 實查全量 **692**（Phase 92 之後；92 本身是人工 phase +0，
#   但產品負責人在 commit f2fc067 補了 2 顆掃碼測試，所以基線不是 690）
#   ＋ Phase 93 的 4 ＋ Phase 94 的 6 ＝ **702**。
#   ⚠ 總覽 §9 那張表的**絕對值**是 2026-08-31 排計畫時的估計（662／666／672／682），
#     74〜92 每一輪 review 都有補顆數，所以絕對值早就對不上了。
#     **要對的是「本 phase +10」**，不是那些絕對數字（總覽 §9 開頭自己也這樣寫）。

pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：16 tests collected（90 的 4 ＋ f2fc067 補的 2 ＋ 93 的 4 ＋ 94 的 6）
#   那 6 個既有的名字（2026-09-03 實查）：
#     test_Dockerfile有cloud_worker這個target
#     test_Dockerfile的app階段在最後
#     test_Dockerfile的cloud_worker帶ARG_GIT_SHA
#     test_compose_yaml沒有新增服務也沒有AWS設定
#     test_unit檔與user_data內嵌段逐字相同          ← f2fc067 補的
#     test_unit只在local才等本機Ollama              ← f2fc067 補的

git branch --show-current            # 預期：main
git status --short docs/spec/        # 預期：無輸出（工作區沒有動到規格）
git log -1 --format='%h %s' -- docs/spec/
# 預期：`39e1c7e feat: 增量五乙丙段收官 Phase 65〜72…`（2026-08-27 那次規格改版）
#   ——**不是**任何增量六的 commit。
#   只看 git status 不夠：前面的 phase 若已經進過 commit，改了規格也看不出來。

# 開工快照（總覽 §7 鐵律 12）：§6 最後一條「本 phase 只動了該動的檔」要拿它來相減
git status --short -- app tests deploy compose.yaml Dockerfile db requirements.txt .github \
  > "$SCRATCH/p95-before.txt"

aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
# 預期：stopped（92-A 那台 t3.xlarge）或 terminated（或 InvalidInstanceID.NotFound／空——ID 已清掉也算過）
# 不准是 running
```

把數字填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | **702** passed ＋ 0 skipped（`--collect-only` 實測 702 tests collected；預期 **702** ＝ 實查基線 692 ＋ 93 的 4 ＋ 94 的 6） |
| 開工時 `test_design6_error_paths.py` 顆數 | **16**（預期 **16**） |
| `docker compose ps` 服務數 | **4**（db healthy／redis healthy／app／worker，worker 的 COMMAND 有 `--concurrency=2`） |
| EC2 狀態 | **`stopped`**（92-A 的 `t3.xlarge`；controller 於 2026-09-03 實查，實作者零 `aws` 指令＝裁決 R3） |
| `aws sts get-caller-identity` 的 Arn 結尾 | **`user/personaldocai-admin`**（controller 實查，同上） |

---

## 3. 範圍

### 做

- **§4.1** design6 §8 錯誤表 10 列逐列盤點（表格反映**事實**，不是抄的）。
- **§4.2** 在 `tests/integration/test_design6_error_paths.py` 補**兩個真缺口**（2 顆）。
- **§4.3** 同一個檔補「不做／禁止／被否決」掃碼（**8 顆**）。
- **§4.3.1**（**只剩一句驗證，不改檔**）確認 `tests/integration/test_ingest_job_pdf.py`
  已經沒有舊名（`_fail`／`_insert_photo_with_files`）——2026-09-01 的 fix wave 早就改完了。
- **§4.3.2** `README.md` 兩處 `543 passed, 0 skipped` → **收工實跑的顆數**（預期 `712`；
  第 20 行附近的 Tests 表格列、第 470 行附近的 `pytest -q` 註解；Phase 92 §4.10 明寫留給本 phase）。
- **§4.3.3** 把前面幾輪 review **停放**下來的四件小事一次結清（+3 顆；其中一項需要
  `cloud_worker.read_context` 的型別加固——這是本 phase 唯一的產品碼改動）。
- **§4.4** 三死埠零依賴實證（AWS ＋ Redis ＋ Ollama 一起指）。
- **§4.5** 正式庫健檢（四個查詢，比照 phase-71 §4.6）。
- **§4.6** 四個服務都在 ＋ **沒有 running 的 EC2** ＋ S3 是空的 ＋ 兩條佇列訊息數 0。
- **§4.7** 產出 `docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`。
- **§4.8** 產出 `docs/plan/todo/<日期>-增量六收尾95-TODO.md` 進度檔。
- **§4.9** 寫下歸檔清單（`unfinish/` 現在只剩 4 份），但**不執行**——等產品負責人決定 commit 時機。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 為了讓某顆測試變綠而改產品行為 | 這是**收尾**，不是重寫。首跑紅了＝揪到真缺陷 → 回**對應的 phase** 修產品碼，然後重跑全量（Phase 37 就是這樣抓出「自創實體＋釘選不是同一個交易」那個 bug）。**例外：§4.3.3 ①**（`read_context` 的型別加固）是前面幾輪 review 明確停放到本 phase 的項目，走的是「先寫紅測試、再改產品」的 TDD |
| 重複測已經有人測的東西 | 每一列先找「誰已經測了」，只補真正的缺口。重複的測試是負債：改一次程式要改兩個地方 |
| 動 `docs/spec/` 任何一個字 | design6 §10 明文：本增量對外上傳契約仍是 202、**不必**為了 fallback 改 Gherkin。要加「敏感不上雲」的 Example **需要另外核准**——那不在本增量的範圍 |
| 在測試裡連真的 AWS／Redis／Ollama、或啟動 Celery | design6 §9 明文。五道 autouse 安全網已經把外部依賴全擋掉；本檔的兩顆行為測試用 `CloudRoute(FakeMailbox(), FakeProbe(...))` |
| 開 EC2「順便再 demo 一次」 | Phase 92 的 Demo 2／2b 與 Phase 94 的 Demo 3 都做過了。本 phase 只**確認沒有 running**。再開機就是在扣卡（`t3.xlarge` 約 $0.2176／小時、`g4dn.xlarge` 約 $0.71／小時） |
| 為了「湊滿十列」而每一列都寫一顆 | §4.1 的盤點就是在防這件事。十列裡有八列已經有人測了 |
| 自己 commit、自己把 `unfinish/` 搬進 `finish/` | 歸檔隨 commit 執行，時機由產品負責人決定（總覽 §7 鐵律 12）。`git mv` 會直接 stage，自己搬等於替人決定了 commit 內容 |
| 自己勾驗收包的 B〜E 段 | 那幾段是**產品負責人**要親自點、親自看、親自簽的。實作者只填 A 段的數字 |
| 改 `.cd-qr svg` 的 `max-width` | 總覽 §7 鐵律 17：那個值背後是真機驗收踩到的**安靜壞掉**（QR 畫得出來但 iPhone 掃不到）。既有測試把它釘死，本增量不准動 |
| 放寬 `mac-policy.json`／給角色多一點權限「以免以後不夠」 | design6 §6「IAM 最小權限」。「先給大一點，之後再收」＝之後不會收 |

---

## 4. 實作步驟

### 4.1 先盤點：§8 錯誤表 10 列各由誰把關（做這件事之前不要動手寫測試）

逐列查「誰已經測了」。查法：`pytest -k 關鍵字 --collect-only -q`，或直接翻測試檔。

> ✅ 下表是**照總覽 §3.3 逐列展開**的結果。**執行時要用 `--collect-only` 的實際輸出
> 重新對一次**：表上寫 ✓ 的那顆若真的不在（前面的 phase 執行時被改名或裁掉了），
> **回那個 phase 所屬的測試檔補**，不要搬進本檔——行為測試住在它功能的家，
> 本檔只收「跨 phase 收尾」性質的東西。

| # | 情況（§8 原文） | 預期 | 誰把關（✓＝已有；★＝本檔補） |
|---|---|---|---|
| 1 | 敏感／不確定 | 本機入庫；零 S3／jobs／results | ✓ **P78** `test_敏感照片走本機_零submit_job記下privacy與route`（斷言含 `mailbox.put_calls == 0`）＋ `test_不確定照片走本機_零submit`；規則層另有 **P74** 的 11 顆 |
| 2 | 非敏感、EC2 Stop | 本機 `run_ingest_job`；202 與進度面板不變 | ✓ **P78** `test_非敏感但遠端關閉_走本機且log有fallback_reason_remote_unavailable`＋ **P89** `test_實例狀態stopped與stopping與pending都是False`；★ 「202 那一半」是本檔【補B】 |
| 3 | 非敏感、無 AWS 憑證 | 同上 | ✓ **P78** `test_非敏感但探測丟例外_同樣fallback本機` ＋ **P89** `test_探測丟例外時回False並留log` |
| 4 | PutObject／jobs SendMessage 失敗 | fallback 本機；不留半套（盡力刪） | ✓ **P79** `test_submit丟例外時fallback本機而且cleanup被呼叫` |
| 5 | 已送雲端、逾時無 results 訊息 | fallback 本機；冪等避免雙 INSERT | ✓ **P80** `test_逾時沒有結果_fallback本機且log有reason_result_timeout` ＋ `test_逾時fallback之前會先清掉S3物件`；真 AWS 那一輪另有 **P86** 的人工煙霧 |
| 6 | SQS 重送（jobs 或 results）、本機已入庫 | 工人／本機略過 | ✓ **P80** `test_同一個job_id的結果送兩次_照片仍然只有一列` ＋ **P87** `test_result已存在時不看圖只補送results並刪jobs訊息`、`test_input不在時只刪jobs訊息什麼都不寫` |
| 7 | VLM 三次失敗（本機或雲端看圖） | 不留 photo 列、清 staging；雲端路還要清 S3 | ✓ **P79** `test_雲端結果說看不懂_job標failed且不留照片` ＋ **P87** `test_看圖三次都失敗_result標understood_false而且attempts是3`；★ **「這是整筆失敗，不是 fallback 本機」沒有人測** → 本檔【補A】 |
| 8 | 格式 415 | 不變；不建 job | ✓ 既有 `test_photos_upload.py` 的三顆：`test_upload_non_image_returns_415_with_message`、`test_upload_octet_stream_returns_415`、`test_415不建任務也不寫staging`（`test_design5_error_paths.py` 檔頭表只**點名**最後那一顆，自己沒有 415 測試）。**本增量一個字都沒改 HTTP 層**，所以這一列是**點名**，不補測 |
| 9 | GitHub OIDC 未鎖 `sub` | 不准合併；trust 必須釘 repo ＋ branch | ✓ **P93** `test_OIDC信任文件的sub逐字鎖住main分支` ＋ `test_OIDC信任文件沒有星號萬用字元`（＋ `test_OIDC信任文件的aud是sts`） |
| 10 | 誤開 NAT／EIP／（未核准的）貴服務 | 本文件禁止；驗收掃 compose／文件／Console。⚠ 原文寫「GPU」＝當時禁止誤開 GPU 機；**2026-09-03 改判工人就是 g4dn**，不要把 `g4dn`／`nvidia` 掃成違規 | ★ 本檔 `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣`（§4.3）＋ §4.6 的 `describe-nat-gateways`／`describe-addresses` 預期空；收工後 **無 running 實例** |

- [x] 逐列打勾。**表上的 ✓ 要用 `--collect-only` 對過才算數。**
- [x] 反過來也一樣：發現某列已被完整測過而你手癢想在本檔再寫一顆 → **不寫**。

順便把 design6 **§9「必釘」9 條**也對一次（總覽 §3.7 有完整對照表）：

```bash
pytest --collect-only -q -k "零submit or 遠端關閉 or 探測丟例外 or 雲端結果 or 送兩次 or body or 敏感中文關鍵字 or 空檔名 or 亂碼檔名" | tail -20
```

- [x] 9 條各自點得到名（少了就回對應的 phase 補，不要搬進本檔）。

> ⚠️ **為什麼本檔的錯誤表只補兩顆？** 這正是收尾 phase 的既有作法
>（Phase 25／37／44／71：先盤點、只釘 ★ 缺口）。74〜94 每個 phase 全程 TDD，
> **各自把自己那幾列在自己的測試檔釘好了**，所以輪到收尾時「逐列有測試」大多是
> **點名**，不是**補寫**。本檔的重心因此落在 §4.3 的掃碼——那些沒有別的 phase 會寫。
>
> 兩顆補缺跟前面的 phase 節奏不一樣：它們釘的是 74〜94 已經做出來的行為，
> 所以**首跑就應該全綠**。首跑有紅的 ＝ 真的揪到缺陷，回對應的 phase 修**產品程式碼**，
> 不是改測試的斷言。

### 4.2 補兩個真缺口（2 顆）

**檔案：** `tests/integration/test_design6_error_paths.py`（Phase 90 開的檔，本檔續寫到最後）。

**① 檔頭的 import 要「補上去」，不是整批換掉。**

現況（2026-09-03 實查）：Phase 90 開檔時放的是 `re`／`Path`／`yaml` ＋ 模組層常數
`PROJECT_ROOT`；Phase 93 會再加 `json` 與兩個常數。**那些一個字都不要動**，
本 phase 只是在同一批 import 底下**再加**幾行（`ruff check --fix` 會自己排順序）：

| 加什麼 | 給誰用 |
|---|---|
| `import ast` | 【掃E】讀工人的語法樹 |
| `import pytest` | 【補B】的 fixture |
| `from fastapi.testclient import TestClient` | 【補B】的 `client_without_server_exceptions` |
| `from app.db.session import get_connection` | 【掃G】查 `information_schema` |
| `from app.dependencies import get_cloud_route, get_privacy_gate, get_vlm` | 兩顆補缺測試的注入點 |
| `from app.main import app` | 同上（`app.dependency_overrides`） |
| `from app.repositories import photo_repository` | 兩顆補缺測試數照片列數 |
| `from app.services import cloud_ingest, gated_ingest, ingest_job, staging_service` | 兩顆補缺測試 |
| `from app.services.aws_mailbox import AwsMailbox` | 【掃D】走真的序列化程式碼 |
| `from app.services.privacy_gate import Verdict` | 兩顆補缺測試 |
| `from app.services.vlm_service import PhotoUnderstanding` | 兩顆補缺測試的假答案卡 |
| `from app.workers import cloud_worker` | 【補A】的假工人；【掃E】的錨點 |
| `from tests.conftest import 目前的任務清單, 跑完任務` | 測試自己扮演 worker（既有的中文 fixture，沿用不改名） |
| `from tests.fakes import FakeMailbox, FakePrivacyGate, FakeProbe, FakeVLM, ScriptedVLM, make_png_bytes` | 假件 |

（`json` 若 Phase 93 已經加過就不必再加；`re`／`Path`／`yaml` 本來就在。）

補完之後，檔頭那一整批應該長這樣（**這是「補完的結果」，不是叫你整段重貼**）：

```python
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.db.session import get_connection
from app.dependencies import get_cloud_route, get_privacy_gate, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, ingest_job, staging_service
from app.services.aws_mailbox import AwsMailbox
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import (
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    ScriptedVLM,
    make_png_bytes,
)
```

> ⚠️ **模組 docstring 不要重寫。** Phase 90 開檔時就寫好了（含那張「誰在什麼時候寫這個檔」
> 的表格，最後一列正是 `Phase 95 | 收尾 | §8 錯誤表逐列補缺口 ＋ §0 六禁與 §1.2
> 被否決清單的掃碼（10 顆）`）。本 phase 只在它的最後補一句：
>
> ```text
> ⚠ 本檔**不連真 AWS、不連真 Redis、不啟動 Celery、不打真 Ollama**（design6 §9）：
>    雲端路一律用 CloudRoute(FakeMailbox(), FakeProbe(...))，
>    任務本體由測試直接呼叫 run_gated_ingest_job（conftest 的 `跑完任務`）。
> ```
>
> ⚠️ **Phase 90／92 已經放在檔頭的東西全部原封不動留著**——模組層常數 `PROJECT_ROOT`
> 與 helper `read_dockerfile()`／`read_compose()`／`read_compose_dev()`／`compose_config()`／
> `compose_services()`／`stage_names()`／`stage_body()`／`_unit_file_text()`／
> `_user_data_embedded_unit()`（**全部是英文名**；舊版計畫寫的 `專案根目錄`／`dockerfile原始碼()`
> 那一套從來沒有存在過）。本 phase 的【掃B】要用其中兩個（`read_compose()`／`compose_services()`），
> **不要**在後面再定義一次同名的東西（`ruff check` 不會抓重複定義，
> 但兩份擺在同一個檔裡會讓後面的人不知道該改哪一個）。
>
> 📌 **`from tests.conftest import 目前的任務清單, 跑完任務` 是唯一保留中文的兩個名字**：
> 它們是 conftest 既有的共用 fixture／helper（增量五就有了，幾十顆測試在用），
> **改名要動一大票既有檔案**，不在本 phase 的範圍。本檔自己新定義的東西一律英文。
>
> ⚠️ **每貼完一段就跑這兩句**，import 排序（ruff 的 `I` 規則：標準函式庫 → 第三方 → 本專案）
> 與區塊之間的空行數（頂層定義之間要**兩行**空白）都由它整理，不必自己數：
>
> ```bash
> ruff check --fix tests/integration/test_design6_error_paths.py
> ruff format tests/integration/test_design6_error_paths.py
> ```
>
> ⚠️ **上面那批 import 的順序是「Phase 74〜94 都做完」時才正確的。** ruff 判斷一個模組
> 是不是本專案的，看的是**檔案在不在磁碟上**：`app/services/aws_mailbox.py`、
> `app/services/privacy_gate.py`、`app/workers/cloud_worker.py` 還不存在的時候，
> ruff 會把那三行當成第三方套件、報 `I001` 要你把它們搬到 `pytest` 那一區
> （2026-08-31 在 74〜94 尚未落地的 repo 上實測就是這樣）。所以**不要**在前面的 phase
> 還沒做完時就先貼本檔；照順序做到 95 再貼，`ruff check` 就是乾淨的。

**② 把下面這一整段追加到檔案最後面（照抄）：**

```python
# ---------------------------------------------------------------------------
# 【補A】§8 錯誤表第 7 列的缺口：雲端看圖三次失敗 ＝ **整筆失敗**，不是 fallback 本機
#
# 為什麼這是缺口：P79 釘了「結果說看不懂 -> job failed、不留照片」，
# P87 釘了「工人那邊真的試了 3 次」。但**沒有人**釘住兩者之間那件事——
# 「本機收到 understood=false 之後，會不會好心地再用本機模型看一次」。
#
# 總覽 §10 追認項 g 的裁決：**不會，也不准**。理由有兩個：
#   1. 遠端明明活著，只是 AI 看不懂——本機再看三次多半也一樣
#   2. 那會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意
# 這件事沒有任何執行期訊號（照片一樣不會出現、job 一樣是 failed），
# 唯一看得出來的是「run_ingest_job 有沒有被呼叫」——所以用 monkeypatch 數它。
# ---------------------------------------------------------------------------

NOT_UNDERSTOOD = PhotoUnderstanding(understood=False)


class WorkerMailbox(FakeMailbox):
    """本機在等結果的那一刻，「另一台機器上的工人」剛好把工作做完了。

    ★ 寫法**沿用既有慣例**：tests/integration/test_gated_ingest.py 與
      tests/integration/test_cloud_roundtrip.py 各自都有一個同名的子類別
      （測試檔之間不互相 import，所以刻意各寫一份）。
      本檔這一份與 test_cloud_roundtrip.py 那一份幾乎逐字相同，差別只有一個：
      這裡餵給工人的是「三次都看不懂」的 ScriptedVLM。

    為什麼要這樣安排：本機端是**同步**的——run_gated_ingest_job 先 submit，
    再 wait_result 長輪詢。測試只有一條執行緒，工人若不在「本機開始等」的那一刻
    動手，wait_result 會空等到逾時然後 fallback，根本走不到「雲端說看不懂」那條路。

    ⚠ 刻意**不用** monkeypatch 換掉 CloudRoute.wait_result：那會把產品碼的方法
      整支換掉，讀測試的人得先確認「換掉之後還有沒有在測原本那支」。
      子類只多接一個 hook，submit()／wait_result()／process_job_message() 三者
      **全部都是真的**（test_cloud_roundtrip.py 的檔頭把這個取捨寫得更詳細）。
    """

    def __init__(self, vlm) -> None:
        super().__init__()
        self.vlm = vlm

    def receive_result(self, wait_seconds: int):
        message = self.receive_job(0)
        while message is not None:
            cloud_worker.process_job_message(self, message, self.vlm)
            message = self.receive_job(0)
        return super().receive_result(wait_seconds)


def test_雲端看圖三次失敗是整筆失敗不是fallback本機(client, monkeypatch):
    """遠端活著、只是看不懂 -> job failed、零照片、S3 清空、**不重跑本機**。

    ⚠ monkeypatch 兩個模組的同名屬性：
        Phase 78 的 gated_ingest.py 寫的是 `ingest_job.run_ingest_job(...)`（帶模組名），
        所以蓋 ingest_job 那一個就攔得到；第二個 setattr 是保險——哪天有人改成
        `from app.services.ingest_job import run_ingest_job`，那個名字會綁在 gated_ingest
        模組上，只蓋 ingest_job 就攔不到了。兩個都蓋，這顆才不會因為 import 風格而假綠。
    """
    local_route_calls: list[str] = []

    def record_local_route(job_id: str, **kwargs) -> None:
        local_route_calls.append(job_id)

    monkeypatch.setattr(ingest_job, "run_ingest_job", record_local_route)
    if hasattr(gated_ingest, "run_ingest_job"):
        monkeypatch.setattr(gated_ingest, "run_ingest_job", record_local_route)

    worker_vlm = ScriptedVLM([NOT_UNDERSTOOD, NOT_UNDERSTOOD, NOT_UNDERSTOOD])
    mailbox = WorkerMailbox(worker_vlm)
    route = cloud_ingest.CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: route

    response = client.post(
        "/photos", files={"file": ("receipt-2026.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    assert worker_vlm.calls == 3, f"雲端工人應該看圖恰好 3 次，實際 {worker_vlm.calls} 次"
    assert local_route_calls == [], (
        "雲端看不懂 ＝ 整筆失敗（總覽 §10 追認項 g）；"
        f"不可以再跑一次本機的 run_ingest_job：{local_route_calls}"
    )
    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed", f"job 應該標 failed：{job}"
    assert photo_repository.count_photos() == 0, "看不懂就不留任何 photo 列"
    assert mailbox.objects == {}, "失敗路徑也要把 S3 的三個物件清乾淨（§8 第 7 列）"
    assert not staging_service.staging_path(job_id, "image/png").exists(), "staging 要刪掉"


# ---------------------------------------------------------------------------
# 【補B】§8 錯誤表第 2 列的另一半：遠端不可用時，**HTTP 仍然 202**
#
# 為什麼這是缺口：P78 釘的是 worker 那一半（走 run_ingest_job、caplog 有
# fallback=local reason=remote_unavailable）。但 design6 §0 的第 6 條禁止講的是
# **HTTP 那一半**：「遠端不可用時上傳不准改 5xx、不准讓使用者重傳」。
#
# 這一顆從**使用者的角度**走一遍：探測說「沒開」的情況下，
# POST /photos 仍然 202、body 仍然恰三鍵、跑完任務之後照片仍然入庫一列。
#
# ⚠ 本機看圖那顆假件一定要自己換成「看得懂」的：conftest 的 wire_fake_ai 預設掛的是
#   FakeVLM()＝看不懂，fallback 走本機路時會試三次然後標 failed，列數永遠是 0。
# ---------------------------------------------------------------------------

MENU_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="某間咖啡店的菜單，拿鐵 120 元",
    category="飲食",
    location="咖啡店",
    items=["拿鐵"],
)


@pytest.fixture
def client_without_server_exceptions():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應而不是往外炸。

    這一顆要驗的正是「**不會**變成 5xx」，所以必須用這個 client——
    用一般的 client 的話，真的壞掉時測試會炸在 raise，看不到狀態碼是幾。
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_遠端不可用時上傳仍然回202不會變5xx(client_without_server_exceptions):
    """design6 §0 禁止第 6 條、D10：遠端關掉時使用者**完全無感**。"""
    mailbox = FakeMailbox()
    route = cloud_ingest.CloudRoute(mailbox, FakeProbe(False), timeout_seconds=5)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(MENU_UNDERSTANDING)  # fallback 用的本機看圖
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: route

    response = client_without_server_exceptions.post(
        "/photos", files={"file": ("menu-2026.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 202, f"遠端關掉不可以變成 5xx：{response.status_code}"
    assert set(response.json()) == {"job_id", "filename", "content_type"}, (
        "202 的回應形狀與增量五逐字相同（使用者看不到 route）"
    )
    job_id = response.json()["job_id"]
    assert photo_repository.count_photos() == 0, "202 只代表收下了，這一刻還沒入庫"

    跑完任務(job_id)

    assert photo_repository.count_photos() == 1, "fallback 之後照片仍然要入庫（D10）"
    assert 目前的任務清單().get(job_id) is None, "成功＝job 被刪掉（與增量五同語意）"
    assert mailbox.put_calls == 0, "探測不通過就不該有任何 S3 呼叫"
```

**③ 首跑（預期兩顆都綠——它們釘的是 74〜94 已經做出來的行為）：**

```bash
pytest tests/integration/test_design6_error_paths.py -k "三次失敗 or 不會變5xx" -v
```

**預期：2 passed。**
**首跑有紅** ＝ 真的揪到缺陷 → 回對應的 phase（【補A】回 **79**、【補B】回 **78**）
修**產品程式碼**，然後重跑全量。**不要改測試的斷言去湊綠。**

**④ 反向驗證（防假綠，30 秒）：**

```bash
# 【補A】：把「local_route_calls == []」暫改成 "!= []"，跑一次要紅
# 【補B】：把「== 202」暫改成 "== 500"，跑一次要紅
```

- [x] 兩顆各做過一次反向驗證，親眼看到紅，再改回來。

### 4.3 「不做／禁止／被否決」掃碼（8 顆）

**先把對應關係列清楚**（每一顆守的是哪幾條規則）：

| 掃碼測試 | design6 出處 | 守的是什麼 |
|---|---|---|
| `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣` | §0 禁止第 4 條、§1.2 第 8 列、§3「不做」第 4 條、§8 第 10 列 | 沒有人「順手」開了會燒點數的服務 |
| `test_compose沒有為了雲端新增任何服務` | 總覽 §7 鐵律 11、§1.2 第 1 列 | **AWS 的九個變數名與工人名稱不進 compose**（設定走 `.env`）；「服務仍恰四個」沿用 Phase 90 的 `compose_services()` 當錨點。分工：Phase 90 那顆守「多階段沒波及 compose」（`build: .`×2、零 `target:`、`image: personaldocai-app`×2、四個服務），本顆守「零 AWS 設定」 |
| `test_端點仍是22支而且openapi零DELETE` | §5 | 本增量不新增使用者打的 REST 端點。**與 design5 那顆互補**：`test_design5_error_paths.py::test_端點恰好是這22支` 逐支列名（增量五的證據），本顆同時斷言「總數 22」與「openapi 零 DELETE」（增量六自己的證據） |
| `test_兩條佇列的訊息body都不含影像位元組` | §0 禁止第 2 條、§1.2 第 3 列、§4 第 1 條、§9 必釘第 7 條 | 位元組走 S3，佇列只放指路的紙條 |
| `test_工人不寫Postgres也不算embedding` | D11、D13、§3「不做」第 2 條 | 工人只看圖；向量與資料庫永遠在本機。**與 Phase 87 那顆互補**（見下面【掃E】的分工說明）：87 掃 import 名單，本顆掃**識別字、字串常數與動態載入** |
| `test_boto3唯一入口仍是aws_mailbox` | 總覽 §7 鐵律 5 | 流程層只認 `CloudMailbox` Protocol，所以測得動、也擋得住第五道安全網被繞過 |
| `test_photo表沒有為了雲端新增任何欄位` | §4 最後一條、總覽 §7 鐵律 13 | `route`／`privacy` 住 JobStore，不進 `photo` 表 |
| `test_隱私閘門不會去碰AI後端開關` | D6、§0 禁止第 5 條 | 閘門可讀 AI_BACKEND，不准寫入或關掉開關 |

**把下面這一整段追加到檔案最後面（接在【補B】後面）：**

```python
# ---------------------------------------------------------------------------
# 【掃A】§0 禁止第 4 條／§1.2 第 8 列／§8 第 10 列：不做 NAT／EIP／ALB／Lambda／ECS
#
# ⚠ 關鍵字刻意分兩組，而且收得很窄——寬一點的字**全部**會假紅：
#   - Python 檔絕對不能掃裸的 "lambda:"。`lambda: FakeVLM(...)` 這種匿名函式
#     在本專案滿地都是（dependency_overrides 幾乎每一行都有），掃了會一片假紅。
#   - 同理不能掃裸的 "ecs:"：雖然 "services:" 裡沒有這四個字連在一起，
#     但把它放進 Python 那一組遲早會撞到別的東西。
#   所以：「IAM 動作前綴」那一組只掃**設定檔**（JSON／YAML），
#         Python 那一組改掃「boto3 建 client 的長相」與資源名稱。
#
# 📌 2026-09-03 校準時**對現況的每一個檔實跑過**這兩組樣式，全部**零命中**、不會首跑假紅
#    （而且刻意挑了「含 Terminate 的 deploy.yml」與「含 ExecStartPre 的四個檔」當對照組，
#      確認邊界條件真的擋住了那兩個假紅）：
#      app/ 全樹（.py）
#      deploy/aws/{mac-policy,s3-lifecycle,worker-role-trust,worker-role-policy}.json
#      deploy/ec2/{personaldocai-worker.service,user-data.sh,worker.env.example}
#      compose.yaml、compose.dev.yaml、.github/workflows/test.yml
#      Phase 94 將寫的 .github/workflows/deploy.yml（內容取自 phase-94 §4.3）
#      Phase 93 將寫的 deploy/aws/{github-oidc-trust,github-deploy-policy}.json
#        （內容取自 phase-93 §4.3／§4.4；裡面只有 sts:／ecr:／ssm:／ec2: 這些字，
#          `ecr:` 不會被 `ecs:` 誤中、`arn:aws:ec2:` 也不會——樣式收的是 ecs: 不是 ec2:）
# ---------------------------------------------------------------------------

# 設定檔（deploy/**、.github/workflows/*.yml、compose*.yaml）用的樣式，**兩組**：
#   前半＝資源名與 CLI 子指令，兩側都要求「不是英文字母」（`(?<![A-Za-z])…(?![A-Za-z])`）
#   後半＝IAM 動作前綴 `lambda:`／`ecs:`／`rds:`，前面必須不是字元或減號
# re.I：NatGateway／natgateway／NAT_Gateway／ElastiCache 都要抓得到。
#
# ⚠ **兩側的邊界條件不可以拿掉，也不可以把關鍵字放寬成裸字**（2026-09-03 校準時
#   由另一位校準者點名的假紅陷阱，實查驗證過）：
#     * 裸的 `nat` 在 re.I 下會命中 **Termi·NAT·e**——`deploy.yml` 裡就有這個字
#     * 裸的 `ecs` 在 re.I 下會命中 **Ex·ecS·tartPre**——`deploy/ec2/` 有四個檔在用
#     * 沒有 `(?<![\w-])` 的話，`keywords:`／`records:`／`specs:` 這種普通 YAML 鍵
#       會被 `rds:`／`ecs:` 誤中
#   所以資源名一律寫**完整**（`nat[ _-]?gateway`，不是 `nat`），動作前綴一律**帶冒號**。
#
# ⚠ 刻意**不掃**裸的 `alb`：它太短，而且真的要開 ALB 一定會在設定裡留下
#   `elasticloadbalancing`（IAM 動作前綴）或 `elbv2`（CLI／SDK 的服務名）——掃那兩個就夠，
#   掃 `alb` 只是在替未來的自己埋假紅。
CONFIG_FORBIDDEN = re.compile(
    r"(?<![A-Za-z])(?:nat[ _-]?gateway|elastic[ _-]?ip|allocate-address"
    r"|elasticloadbalancing|elbv2|fargate|elasticache)(?![A-Za-z])"
    r"|(?<![\w-])(?:lambda|ecs|rds):",
    re.I,
)

# app/ 的 .py 用的關鍵字（全部轉小寫之後比對）。
# 只掃「真的會建出那些資源」的長相，不掃裸關鍵字（理由同上：`lambda:` 這種匿名函式
# 在 dependency_overrides 裡滿地都是，掃了會一片假紅）。
CODE_FORBIDDEN = (
    "natgateway",
    "nat_gateway",
    "nat-gateway",
    "allocate_address",
    "allocate-address",
    "elasticloadbalancing",
    "elasticache",
    "fargate",
    'client("lambda"',
    'client("ecs"',
    'client("rds"',
    'client("elbv2"',
)


def test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣():
    """design6 §0 禁止第 4 條：這些服務全都沒有需求，而且 NAT 東京約 $45／月。

    ⚠ 不掃 GPU／g4dn／nvidia：2026-09-03 改判工人就是 g4dn 上自裝 Ollama。

    掃三棵樹：app/（產品碼）、deploy/（IAM policy 與 EC2 開機腳本）、
    .github/workflows/（CI 與 CD）＋ compose*.yaml。

    刻意**不掃** docs/、LAUNCH.md、CLAUDE.md：那些文件本來就合法地寫著「禁止 NAT」
    這幾個字，掃了只會假紅。文件那一半交給 §4.6 的人工檢查（describe-nat-gateways）。
    """
    violations: list[str] = []

    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        hits = [keyword for keyword in CODE_FORBIDDEN if keyword in source]
        if hits:
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：{hits}")

    config_files: list[Path] = []
    for pattern in ("deploy/**/*", ".github/workflows/*.yml", "compose*.yaml"):
        config_files += [path for path in PROJECT_ROOT.glob(pattern) if path.is_file()]
    for path in sorted(config_files):
        hits = CONFIG_FORBIDDEN.findall(path.read_text(encoding="utf-8"))
        if hits:
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：{hits}")

    assert violations == [], f"design6 §0 禁止第 4 條：不做 NAT／EIP／ALB／RDS／Lambda／ECS：{violations}"

    # 防呆錨點：確認真的掃到東西了（目錄被改名／glob 寫錯要紅在這裡，不是默默全過）
    assert (PROJECT_ROOT / "deploy" / "aws").is_dir(), "deploy/aws/ 應該存在（Phase 82 起）"
    assert (PROJECT_ROOT / ".github" / "workflows" / "deploy.yml").exists(), (
        ".github/workflows/deploy.yml 應該存在（Phase 94）"
    )


# ---------------------------------------------------------------------------
# 【掃B】總覽 §7 鐵律 11：compose.yaml 本增量零改動
# ---------------------------------------------------------------------------


# 總覽 §2.4.2 裡所有跟 AWS／雲端路有關的變數名（九個）。它們**只准住在 .env**。
# 哪天有人在 compose.yaml 的 environment: 底下加了其中任何一個，這一顆就紅。
AWS_SETTING_NAMES = (
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "S3_BUCKET",
    "SQS_JOBS_QUEUE_URL",
    "SQS_RESULTS_QUEUE_URL",
    "EC2_WORKER_INSTANCE_ID",
    "CLOUD_ROUTE",
)


def test_compose沒有為了雲端新增任何服務():
    """AWS 的設定全部走 .env（app 與 worker 早就 bind-mount 了它），compose 零 AWS 字樣。

    為什麼不加第五個服務：本機**不跑** cloud_worker 容器——那是 EC2 的事。
    丁段（Phase 88／90）在 Mac 上跑工人時用的是 `docker run`／`python -m`，
    刻意不進 compose，這樣「常駐四個服務」這件事就永遠不會被雲端污染。

    分工（兩顆各守各的，不重複）：
      Phase 90 的 test_compose_yaml沒有新增服務也沒有AWS設定 守「多階段沒波及 compose」
        ——build: . 兩處、零 target:、image: personaldocai-app 兩處、服務恰四個，
        另外掃 AWS_／S3_BUCKET／SQS_／CLOUD_ROUTE 四個**前綴**。
      本顆守「九個變數名逐字都不在」＋「工人的服務名不在」——比前綴那一組更精確，
        而且把 cloud_worker／cloud-worker 這兩個名字也擋掉（前綴掃不到它們）。
    服務清單這裡也看一眼，但**沿用 Phase 90 的 compose_services()**（同一個檔的模組層 helper），
    不自己再寫一份 regex：直接對整份 compose.yaml 抓 `^  ([a-z][\\w-]*):$` 會連
    volumes: 底下的 pgdata:／redisdata: 一起抓進來（Phase 90 實測回 6 個而不是 4 個）。
    """
    source = read_compose()

    for name in AWS_SETTING_NAMES:
        assert name not in source, f"AWS 的設定走 .env，不進 compose.yaml（總覽 §7 鐵律 11）：{name}"
    for keyword in ("cloud_worker", "cloud-worker"):
        assert keyword not in source, (
            f"本機不跑雲端工人容器，那是 EC2 的事（總覽 §7 鐵律 11）：{keyword}"
        )

    # 錨點：確認讀到的真的是那份 compose（服務仍是四個；主斷言在 Phase 90 那顆）
    assert compose_services() == ["db", "redis", "app", "worker"]


# ---------------------------------------------------------------------------
# 【掃C】§5：不新增使用者打的 REST 端點
# ---------------------------------------------------------------------------


def test_端點仍是22支而且openapi零DELETE(client):
    """design6 §5 明文「本增量不要求為雲端管線新增使用者打的 REST 端點」。

    ⚠ 為什麼還要再寫一顆（既有已經有三顆在數 22）：
      既有那三顆是**增量五**留下來的證據，證明的是「增量五之後是 22」。
      本檔是**增量六自己的**證據——半年後有人問「增量六到底有沒有偷加端點」，
      答案要在增量六的收尾檔裡找得到，而不是靠「別的增量的測試還是綠的」去推論。
      這一顆刻意只數總數與 DELETE，不重抄那 22 支的清單
      （逐支列名由 test_design5_error_paths.py::test_端點恰好是這22支 守著）——
      **分工，不是重複**。

    ⚠ 不要用 app.routes 清點——FastAPI 0.141 有 _IncludedRouter 的已知坑，
      路由不會被攤平，數出來的數字是錯的。一律走 /openapi.json。
      WebSocket /camera/{token}/signal 依 FastAPI 的行為不進 openapi，不計入。
    """
    paths = client.get("/openapi.json").json()["paths"]
    operations = [(path, method) for path, item in paths.items() for method in item]

    assert len(operations) == 22, f"本增量端點恆為 22（design6 §5），現在是 {len(operations)}"
    assert [method for _, method in operations if method == "delete"] == [], (
        "系統仍然沒有任何刪除功能"
    )


# ---------------------------------------------------------------------------
# 【掃D】§0 禁止第 2 條／§4 第 1 條／§9 必釘第 7 條：佇列只放紙條，不放位元組
# ---------------------------------------------------------------------------


class RecordingS3:
    """AwsMailbox 建構時可以注入 client；塞這個進去就完全不會碰 boto3。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class RecordingSqs:
    """把 send_message 收到的參數原樣留下來，讓測試檢查 MessageBody 長什麼樣。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}


def test_兩條佇列的訊息body都不含影像位元組():
    """design6 §0 禁止第 2 條：SQS 單則上限 1 MiB（2025 年中前 256 KB），一份多頁 PDF 幾十 MB。

    ⚠ 這一顆走的是**真的序列化程式碼**（AwsMailbox.send_job／send_result），
      只是把 boto3 的 client 換成記帳假件——所以它證明的是「真的送出去的那個 body
      長什麼樣」，不是「假件記了什麼」。

    Phase 83 已經有 test_send_job的body恰兩鍵／test_send_result的body恰一鍵；
    這一顆的角度不同：**兩條一起**、而且驗「解析得出來 ＋ 夠小 ＋ 沒有編碼過的影像」。
    """
    sqs = RecordingSqs()
    mailbox = AwsMailbox(
        bucket="不會用到",
        jobs_queue_url="https://sqs.example/jobs",
        results_queue_url="https://sqs.example/results",
        region="ap-northeast-1",
        s3=RecordingS3(),
        sqs=sqs,
        ec2=object(),
    )

    mailbox.send_job("job-abc", "documents/job-abc/input.png")
    mailbox.send_result("job-abc")

    assert len(sqs.sent) == 2, "應該恰好送出兩則（jobs 一則、results 一則）"
    for call in sqs.sent:
        body = call["MessageBody"]
        assert isinstance(body, str), "body 必須是字串"
        payload = json.loads(body)  # 位元組塞得進去的話這一行就會炸
        assert set(payload) <= {"job_id", "s3_key"}, f"body 只准有 job_id 與 s3_key：{sorted(payload)}"
        assert len(body.encode("utf-8")) < 1024, (
            f"body 應該只有幾十個位元組，現在是 {len(body.encode('utf-8'))}"
        )
        for marker in ("base64", "data:image", "\\x89PNG", "%PDF"):
            assert marker not in body, f"佇列訊息不可以帶影像：{marker}"


# ---------------------------------------------------------------------------
# 【掃E】D11／D13／§3「不做」第 2 條：工人不碰資料庫、不算 embedding
#
# ★ 分工（2026-09-03 校準裁決 R10）——**與 Phase 87 那顆互補，不重抄**：
#     tests/unit/test_cloud_worker_unit.py::test_工人不import資料庫與Celery與Redis
#       用 ast 掃 **import 名單**：黑名單（redis／celery／app.db／app.repositories／
#       app.dependencies／app.services.ingest_job／app.services.staging_service）
#       ＋ 白名單（只准那六個自家模組）＋ 禁相對 import。那一層已經很完整。
#     本顆掃 87 掃不到的三個面向：
#       ① **識別字**：程式裡有沒有用到向量／資料庫相關的名字（import 以外的路徑，
#          例如有人把 embeddings 當參數傳進來、或呼叫 mailbox 以外的東西）
#       ② **字串常數**：result.json 有沒有多一個 "embedding" 鍵；有沒有把模組路徑
#          寫成字串（importlib.import_module("app.db.session") 這種繞過 ast import 的寫法）
#       ③ **動態載入**：有沒有 importlib／__import__（有的話 ① ② 都擋不住）
#
# ⚠ 為什麼**不能**改成「掃全文文字（含註解）有沒有 photo_repository／embed」：
#   工人自己的模組 docstring 就寫著「⛔ 不寫 Postgres、不碰 photo_repository」與
#   「⛔ 不算 embedding」——那是**正確的文件**，掃全文會把它掃成違規（2026-09-03
#   校準時對實檔跑過：photo_repository 命中第 18／84 行、embed 命中第 19／171 行）。
#   所以字串比對一律走「**整個字串常數相等**」，長句 docstring 不會誤中。
# ---------------------------------------------------------------------------

WORKER_SOURCE = PROJECT_ROOT / "app" / "workers" / "cloud_worker.py"

# 識別字（變數、屬性、import 進來的名字）。工人碰到其中任何一個都是違規。
FORBIDDEN_WORKER_NAMES = {
    "get_embeddings",
    "embed_understanding",
    "embed_query",
    "embed_documents",
    "Embeddings",
    "OllamaEmbeddings",
    "FakeEmbeddings",
    "photo_repository",
    "get_connection",
    "insert_photo",
}

# 寫死的字串。比對**整個字串相等**，所以 docstring 裡的長句不會誤中，
# 但 dict 的鍵 "embedding" 與 importlib.import_module("app.db.session") 逃不掉。
FORBIDDEN_WORKER_STRINGS = {
    "embedding",
    "app.db",
    "app.db.session",
    "app.repositories",
    "app.repositories.photo_repository",
    "app.dependencies",
    "app.services.indexing_service",
    "app.services.ingest_job",
}


def test_工人不寫Postgres也不算embedding():
    """D11：EC2 只當工人（無 DB、無 Celery、無 Redis）；D13：向量一律本機 bge-m3。

    用 ast 而不是 grep：
      - 註解與 docstring 裡寫了「不碰 photo_repository」不會誤判成違規
      - `getattr(module, "insert_photo")` 這種寫法 grep 抓得零零落落，ast 一次抓齊
    """
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    names: set[str] = set()
    constants: set[str] = set()
    dynamic_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.add(node.value)

    # ① 識別字
    assert not (names & FORBIDDEN_WORKER_NAMES), (
        "工人不碰資料庫、也不算向量（D11／D13）；"
        f"出現了：{sorted(names & FORBIDDEN_WORKER_NAMES)}"
    )

    # ② 字串常數（result.json 的鍵 ＋ 用字串繞過 import 檢查的模組路徑）
    assert not (constants & FORBIDDEN_WORKER_STRINGS), (
        "工人的字串常數不可以是這些（result.json 不含 embedding 鍵、"
        f"也不准用字串指到資料庫層）：{sorted(constants & FORBIDDEN_WORKER_STRINGS)}"
    )

    # ③ 動態載入：有它的話 ① ② 都可以被組字串繞過去
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"importlib", "__import__"}:
            dynamic_imports.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr == "import_module":
            dynamic_imports.append(node.attr)
    assert dynamic_imports == [], (
        "工人不准動態載入模組（那會繞過 Phase 87 那顆 import 掃碼）："
        f"{sorted(set(dynamic_imports))}"
    )

    # ④ 兩個窄的 import 定錨（完整的黑白名單由 Phase 87 那顆守，這裡只點名兩個
    #    「一旦出現就代表向量或注入層被搬上工人」的模組，讓本顆的名字名副其實）
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    for forbidden in ("app.services.indexing_service", "app.dependencies"):
        offenders = sorted(
            name for name in imported if name == forbidden or name.startswith(forbidden + ".")
        )
        assert offenders == [], f"工人不可以 import {forbidden}（D11／D13）：{offenders}"

    # 防呆錨點：確認掃的真的是工人（檔案搬走／改名要紅在這裡）
    assert "def process_job_message(" in source
    assert "def main(" in source


# ---------------------------------------------------------------------------
# 【掃F】總覽 §7 鐵律 5：boto3 只准出現在 aws_mailbox.py
# ---------------------------------------------------------------------------

# 只比對**真的 import 敘述**（行首 + import/from + boto3 或 botocore），
# 不是掃裸的 "boto3" 五個字——這樣本檔自己提到 boto3（註解、豁免名單、斷言訊息）
# 不會把自己掃紅。樣式與 Phase 83 那顆逐字相同（含縮排＝函式裡的延遲 import 也抓得到）。
BOTO3_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)

# 總覽 §2.7 定的三個放行檔。「放行」只是允許、不是要求：
# scripts/aws_check.py（Phase 84）其實走的是 AwsMailbox、沒有直接 import boto3，
# 留在名單裡不會讓這一顆變鬆。
BOTO3_ALLOWED_FILES = {
    "app/services/aws_mailbox.py",  # 全系統唯一的 AWS SDK 入口
    "tests/unit/test_aws_mailbox_unit.py",  # 它的單元測試（from botocore.exceptions import ClientError）
    "scripts/aws_check.py",  # host 手動用的連線檢查（不進映像）
}


def test_boto3唯一入口仍是aws_mailbox():
    """Phase 83 那顆只掃 app/；這一顆掃 app/ ＋ tests/ ＋ scripts/ 三棵樹。

    為什麼要拆成兩顆而不是把 83 那顆擴大：83 守的是「產品碼的分層」
    （cloud_ingest.py 只認 CloudMailbox Protocol，所以它的測試才用得動假信箱）；
    本顆守的是「**整個 repo** 只有那三個檔碰得到 AWS SDK」——
    包含測試自己。少了這一顆，有人在某顆測試裡 import boto3 直接打真 AWS，
    第五道安全網（wire_fake_cloud）就被繞過去了，而且完全沒有訊號。
    """
    violations: list[str] = []
    for tree_root in ("app", "tests", "scripts"):
        for path in sorted((PROJECT_ROOT / tree_root).rglob("*.py")):
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            if relative_path in BOTO3_ALLOWED_FILES:
                continue
            if BOTO3_IMPORT.search(path.read_text(encoding="utf-8")):
                violations.append(relative_path)

    assert violations == [], (
        f"boto3 只准出現在 app/services/aws_mailbox.py（總覽 §7 鐵律 5）：{violations}"
    )

    # 反過來也釘一次：入口檔**必須**真的 import 了，不然這一顆會變成永遠綠的裝飾品
    entry_point = PROJECT_ROOT / "app" / "services" / "aws_mailbox.py"
    assert BOTO3_IMPORT.search(entry_point.read_text(encoding="utf-8")), (
        "aws_mailbox.py 應該要 import boto3"
    )


# ---------------------------------------------------------------------------
# 【掃G】§4 最後一條／總覽 §7 鐵律 13：photo 表不加任何欄
# ---------------------------------------------------------------------------

# 增量五結束時 photo 表的欄位集合（db/schema.sql 逐欄對過；2026-09-03 再對一次，相同）。
# 增量六**一欄都不准動**：route／privacy 住 JobStore（design6 §4 明文）。
PHOTO_COLUMNS = {
    "id",
    "text",
    "category",
    "folder_id",
    "location",
    "items",
    "content_time",
    "uploaded_at",
    "embedding",
    "original_path",
    "thumbnail_path",
    "content_type",
    "suggested_category",
    "suggested_entity",
    "suggested_task_title",
    "suggested_task_due",
}


def test_photo表沒有為了雲端新增任何欄位():
    """design6 §4：「photo 表不加 job_id、不加處理狀態欄（design5 禁令仍有效）」。

    ⚠ 比對的是**整個集合逐字相等**，不只是「沒有 route 這一欄」。
      只檢查黑名單的話，有人加一個叫 cloud_state 的欄位照樣過關。

    conftest 已把 DATABASE_URL 指到測試庫，而測試庫是用 db/schema.sql 重建的——
    所以問的是「schema.sql 現在長什麼樣」，正式庫走同一份遷移對齊。
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
            columns = {row["column_name"] for row in cur.fetchall()}

    assert columns == PHOTO_COLUMNS, (
        f"photo 表本增量零改動；多出來：{sorted(columns - PHOTO_COLUMNS)}；"
        f"少掉了：{sorted(PHOTO_COLUMNS - columns)}"
    )


# ---------------------------------------------------------------------------
# 【掃H】D6／§0 禁止第 5 條／§1.2 第 7 列：兩扇門完全分開
# ---------------------------------------------------------------------------


def test_隱私閘門不會去碰AI後端開關():
    """D6（2026-09-01）：閘門**跟著**頁首開關走，但**不准寫入／關掉**它。

    閘門短問讀 config.AI_BACKEND 選本機或雲端 VLM（與 get_vlm 同一套）。
    禁止的是「敏感就強制把開關撥回本機」或寫入 AI_BACKEND。
    """
    for filename in ("privacy_gate.py", "gated_ingest.py"):
        source = (PROJECT_ROOT / "app" / "services" / filename).read_text(encoding="utf-8")
        assert "AI_BACKEND =" not in source, f"{filename} 不可以寫入頁首的 AI 模型開關（D6）"
        assert "settings/ai-backend" not in source, f"{filename} 不可以打開關端點"
```

**貼完先整理格式，再跑一次（首跑應該全綠）：**

```bash
ruff check --fix tests/integration/test_design6_error_paths.py
ruff format tests/integration/test_design6_error_paths.py
pytest tests/integration/test_design6_error_paths.py -v
```

**預期：26 passed** ＝ Phase 90 的 4 ＋ `f2fc067` 補的 2 ＋ Phase 93 的 4 ＋ Phase 94 的 6 ＋ 本 phase 的 10。

**反向驗證（防假綠；至少做四次）：**

| 顆 | 怎麼弄紅 |
|---|---|
| `test_compose沒有為了雲端新增任何服務` | 在 `compose.yaml` 的 `worker:` → `environment:` 底下暫時加一行 `      S3_BUCKET: x`，跑一次要紅在「AWS 的設定走 .env」，再刪掉 |
| `test_photo表沒有為了雲端新增任何欄位` | 把 `PHOTO_COLUMNS` 暫時拿掉 `"embedding"`，跑一次要紅在「少掉了」，再加回去 |
| `test_boto3唯一入口仍是aws_mailbox` | 把 `BOTO3_ALLOWED_FILES` 裡的 `app/services/aws_mailbox.py` 暫時刪掉，跑一次要紅，再加回去 |
| `test_工人不寫Postgres也不算embedding` | 在 `cloud_worker.py` 裡暫時把 `build_image_result()` 回傳的 dict 加一個 `"embedding": None` 鍵，跑一次要紅在「字串常數」，再刪掉。**不要**改成 `import redis` 來驗——那條是 Phase 87 那顆在守的，本顆刻意不重抄 import 名單（互補分工） |

- [x] 四次紅都親眼看過了。**沒紅過的「某個東西不存在」型斷言，你不知道它有沒有在睡覺。**

### 4.3.1 Phase 76 留下的兩句舊名註解 —— **已經不必做了，只驗一次**

Phase 76 把 `_fail` → `fail_job`、`_insert_photo_with_files` → `insert_photo_with_files` 之後，
`tests/integration/test_ingest_job_pdf.py` 曾有**兩句 docstring** 仍寫舊名，76 §8 把它留給本 phase。
**2026-09-01 Phase 74〜80 收工的 final fix wave 已經順手改掉了**（同一輪還改了
`test_ai_timing_log.py`／`test_folder_correction.py` 的「六個注入點」、`test_ingest_job.py` 的「四道」、
`test_entity_suggestion_unit.py` 的「五種 kind」、`test_privacy_gate_unit.py` 的 `get_privacy_gate()` docstring；
總覽 §2.7 的 Phase 95 段已經把這一項劃掉）。所以本 phase **不改這個檔**，只留一句驗證：

```bash
grep -nE '_fail\b|_insert_photo_with_files' tests/integration/test_ingest_job_pdf.py
# 預期：**無輸出**（2026-09-03 校準時實跑確認過）
```

- [x] 跑過，確認無輸出。**有輸出**才回頭改那兩句（只動那兩個詞，其他一個字都不碰），
      改完 `ruff format --check` ＋ `ruff check` ＋ `pytest tests/integration/test_ingest_job_pdf.py -q`
      顆數不變，並在 §6 最後一條的相減結果裡把它算進去。

### 4.3.2 `README.md` ＋ `CLAUDE.md` 的 Tests 顆數（543 → 收工實跑值；純文件、三處）

Phase 92 §4.10 改 `README.md` 時明寫「Tests 那一列本 phase 不要動——增量六做完再一起改」。
現在就是那個時候。**先跑完 §4.4 拿到實際數字再改**，數字要抄實跑的，不要抄計畫。

> 預期是 **715**（開工基線 702 ＋ §4.2／§4.3 的 10 ＋ §4.3.3 的 3）。
> 真正要寫進去的是**收工那一次 `pytest -q` 的輸出**，不是這裡印的預期值。

```bash
grep -n "543 passed" README.md CLAUDE.md
# 預期恰三行（2026-09-03 校準時實查，以 grep 為準、不要靠行號）：
#   README.md:23   | Tests | **543 passed, 0 skipped** (includes pytest-bdd …
#   README.md:473  pytest -q            # 543 passed, 0 skipped
#   CLAUDE.md:473  #   （2026-08-27 實測 543 passed，與帶 .env 跑的結果相同。）  ← **這一行不要改**
grep -n "顆數要跟本機一樣" CLAUDE.md
#   CLAUDE.md:461  #   pytest -q      ← 顆數要跟本機一樣（543）                ← **這一行要改**
```

- [x] `README.md` 兩處的 `543` 改成收工實跑值。
- [x] `CLAUDE.md` 第 461 行附近「顆數要跟本機一樣（**543**）」那個數字改成同一個值
      （校準者 A 在 Phase 93 的跨檔回報點名的；它是 `── CI：GitHub Actions（Phase 73）` 段
      在描述 CI 會跑什麼，不是歷史紀錄，所以是**過期**不是**史料**）。
- [x] **這三處以外的 `543` 一個都不要碰**，它們是**歷史敘述**，改掉等於竄改紀錄：
      - `CLAUDE.md` L11「全量測試 **543 passed ＋ 0 skipped**（增量五收官…）」
      - `CLAUDE.md` L13「**測試 543→613**（+70…）」
      - `CLAUDE.md` L473「（2026-08-27 實測 543 passed，與帶 .env 跑的結果相同。）」——有寫日期＝史料

> ⚠️ **驗證用的 grep 一定要排除 `5433`**（資料庫的埠號，`CLAUDE.md` 裡有十幾個）。
> 直接 `grep 543` 會噴一整片假警報：
>
> ```bash
> grep -nE '(^|[^0-9])543([^0-9]|$)' README.md CLAUDE.md
> # 收工後預期：只剩 CLAUDE.md 的那三行歷史敘述（L11／L13／L473），README.md 零命中
> ```

- [x] `git diff --stat README.md CLAUDE.md` 預期 `README.md | 2 +-`、`CLAUDE.md | 2 +-`
      （各 2 行改動；`CLAUDE.md` 的「專案概述」現況段仍然留到 §8 第 3 點、commit 之後才寫）。

> 📌 **另外發現（校準時順手查到，本 phase 不強制做）：** `LAUNCH.md` 第 225 行也有一句
> `pytest -q    # expect 543 passed`。它是給產品負責人看的操作手冊，同樣過期。
> 要改就順手一起改（純文件、零風險）；不改就寫進 REP 的「已知待辦」，不要默默放著。

### 4.3.3 前輪 review 停放項（四件小事，+3 顆）

> 📌 **這一節是哪來的：** Phase 80 與 Phase 90／92 的 review 各留了幾個「不影響本 phase 驗收、
> 但確實是缺口」的項目，當時的裁決是**停放到收尾 phase 一次結清**（總覽 §2.7 的 Phase 95 段
> 就寫著那兩個「候選補測」）。2026-09-03 校準時逐項對過實檔，四項全部仍然成立。
>
> **四項各自獨立**，做完一項就跑一次那個檔，不要堆在一起。

| # | 停放項 | 動到哪個檔 | 新增顆數 |
|---|---|---|---|
| ① | `read_context` 對「值不是 list」沒有防護（會丟 TypeError ＝毒訊息） | `app/workers/cloud_worker.py`（**本 phase 唯一的產品碼改動**）＋ `tests/unit/test_cloud_worker_unit.py` | **+1** |
| ② | `from_lines` 的正規式少了 `re.I`，與同檔的 `stage_names()` 不一致 | `tests/integration/test_design6_error_paths.py` | +0（改既有那顆） |
| ③ | `test_cloud_worker_unit.py` 的模組 docstring 寫死「這 10 顆」，實際 31 顆 | `tests/unit/test_cloud_worker_unit.py` | +0（純註解） |
| ④ | Phase 80 review 點名的兩個候選補測 | `tests/integration/test_gated_ingest.py`、`tests/unit/test_cloud_ingest_unit.py` | **+2** |

---

#### ① `read_context`：context.json 的值不是 list 時會丟 TypeError

**先看現況**（`app/workers/cloud_worker.py`，2026-09-03 實查在第 151〜155 行）：

```python
    return (
        list(payload.get("folders") or []),
        list(payload.get("entities") or []),
        list(payload.get("corrections") or []),
    )
```

`payload` 已經確定是 dict（上一段的 `isinstance(payload, dict)` 擋過了），但**值**沒人檢查：

| context.json | `list(x or [])` 的結果 | 後果 |
|---|---|---|
| `{"folders": 5}` | `TypeError: 'int' object is not iterable` | 例外衝出 `process_job_message` → **jobs 訊息沒被刪** → 900 秒後回來再炸 ＝ 永遠出不去的**毒訊息** |
| `{"entities": "abc"}` | `["a", "b", "c"]` | **安靜地**把三個假實體餵進 prompt |
| `{"corrections": {"a": 1}}` | `["a"]` | 同上 |

而 `read_context` 的 docstring 明明寫著「缺檔或內容壞掉 → 三份都當空清單，**不是失敗**」。

**TDD：先寫紅測試。** 加到 `tests/unit/test_cloud_worker_unit.py` 的
`test_context是合法JSON但不是物件時三份清單也當空的` 後面（同一組 context 測試放一起）：

```python
def test_context值不是list時當空清單不炸(caplog):
    """三個鍵的**值**型別不對（不是缺檔、也不是壞 JSON）——這是第三種壞法。

    ⚠ 為什麼它是真缺口：`{"folders": 5}` 的 json.loads 過得了關、payload 也真的是 dict，
      所以既有那兩顆（解不開／不是物件）都攔不到它。
      加固之前 `list(5 or [])` 會丟 TypeError，一路衝出 process_job_message ->
      jobs 訊息**沒被刪掉** -> 900 秒後回來再炸一次 = 永遠出不去的毒訊息。
      字串與 dict 更陰險：`list("abc")` 會**安靜地**變成三個假資料夾餵進 prompt。

    三種都走一遍，而且順帶確認它照樣走完整條路（有寫 result、有刪 jobs 訊息）。
    """
    caplog.set_level(logging.WARNING)
    for raw in (b'{"folders": 5}', b'{"entities": "abc"}', b'{"corrections": {"a": 1}}'):
        mailbox = FakeMailbox()
        message = queue_one_job(mailbox, payload=make_png_bytes())
        mailbox.put_object(mailbox.context_key("job-1"), raw, "application/json")
        vlm = FakeVLM(RECEIPT_UNDERSTANDING)

        cloud_worker.process_job_message(mailbox, message, vlm)

        assert vlm.last_folders == [], f"{raw!r} 的 folders 應該被當成空清單"
        assert vlm.last_entities == [], f"{raw!r} 的 entities 應該被當成空清單"
        assert vlm.last_corrections == [], f"{raw!r} 的 corrections 應該被當成空清單"
        assert mailbox.calls.count("delete_job_message") == 1, "訊息要被刪掉，不可以變成毒訊息"

    assert any("不是清單" in line for line in caplog.messages), (
        f"型別不對也要留 warning，不可以安靜地當空的：{caplog.messages}"
    )
```

```bash
pytest tests/unit/test_cloud_worker_unit.py -k "不是list" -v
# 預期：**紅**（第一個 case 就 TypeError）——沒紅代表你貼錯地方了
```

**再改產品碼（最小改動）。** 在 `read_context` **上面**加一個私有 helper：

```python
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
```

然後把 `read_context` 的 `return` 那一段換成：

```python
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
```

```bash
pytest tests/unit/test_cloud_worker_unit.py -q      # 預期：32 passed（31 ＋ 1）
pytest tests/integration/test_cloud_roundtrip.py -q # 端到端也再跑一次（context 的正常路徑）
ruff format tests/unit/test_cloud_worker_unit.py app/workers/cloud_worker.py
ruff check app tests
```

- [x] 紅 → 綠走過一遍（紅的那次要親眼看到 `TypeError`）。
- [x] 這是本 phase **唯一**的產品碼改動，要寫進 §6 最後一條的相減說明與 REP。

> ⚠️ **不要順手做別的事**：不要改 `read_context` 的回傳型別、不要驗清單裡每一筆是不是 dict
> （那是 VLM prompt 組裝的事，而且清單內容本來就是本機自己寫進去的）。
> 這一項只擋「值的型別不對」這一種壞法。

---

#### ② `from_lines` 的正規式補 `re.I`

`tests/integration/test_design6_error_paths.py::test_Dockerfile的app階段在最後` 裡有一行
（2026-09-03 實查在第 153 行）：

```python
    from_lines = re.findall(r"^FROM\b", source, re.M)
```

同一個檔的 `stage_names()` 用的是 `re.M | re.I`（Docker 的指令**不分大小寫**）。兩邊不一致：

- 有人把 `FROM` 寫成小寫 `from base AS x` → `stage_names()` 抓得到、`from_lines` 抓不到
  → `len(from_lines) != len(names)` → **假紅**，而且錯誤訊息會說「有一個 stage 沒寫 AS 名字」，
  完全指錯方向。
- 反過來，小寫的**無名** stage（`from base`）兩邊都抓不到 → 那顆守的正是這個壞法，卻**假綠**。

- [x] 把那一行改成 `re.findall(r"^FROM\b", source, re.M | re.I)`（只加 `| re.I`，其他不動）。
- [x] `pytest tests/integration/test_design6_error_paths.py -k app階段 -v` 仍然綠。

---

#### ③ `test_cloud_worker_unit.py` 的模組 docstring 寫死顆數

檔頭第 5 行（2026-09-03 實查）：

> `看圖是 FakeVLM／ScriptedVLM。所以這 10 顆跑起來是毫秒等級，而且**永遠不會**`

那是 Phase 87 開檔時的數字，88／90／92 追加之後**實際是 31 顆**（本節 ① 之後 32）。
寫死的數字沒有測試在守，只會愈來愈錯。

- [x] 把「這 10 顆」改成不寫死數字的說法，例如「**所以本檔跑起來是毫秒等級**」。
- [x] 純 docstring，零行為；`pytest tests/unit/test_cloud_worker_unit.py -q` 顆數不變。

---

#### ④a 崩潰重送時 `cloud` 已經是 `CloudRouteOff`（+1；`tests/integration/test_gated_ingest.py`）

**這條路是怎麼發生的：** 任務跑到一半，使用者把 `.env` 的 `CLOUD_ROUTE` 改回 `off`、
`restart worker`。佇列把同一個 `job_id` 再送一次時，job 的 `route` 還是 `"cloud"`，
但新行程手上的 `cloud` 已經是 `CloudRouteOff` ——它的 `fetch_result()` 與 `cleanup()`
**都會丟 `RuntimeError`**（那顆替身刻意不安靜回 None）。

`gated_ingest._resume_cloud_route` 與 `_best_effort_cloud_cleanup` 的兩個 `try`
就是為這一刻寫的（兩支的 docstring 都明寫「cloud 有可能已經是 CloudRouteOff」），
但**沒有任何測試證明過**。Phase 80 的 review 點名了它，顆數留給 95。

加到 `test_gated_ingest.py` 的 `test_崩潰重送route是cloud但S3沒有結果_fallback本機` 後面
（同一組「崩潰重送」的測試放一起）：

```python
def test_崩潰重送時雲端路已經關掉_照樣fallback本機(caplog):
    """使用者在任務跑到一半把 .env 改回 CLOUD_ROUTE=off 並 restart worker。

    重送回來時 job 的 route 還是 "cloud"，但手上的 cloud 已經換成 CloudRouteOff——
    它的 fetch_result／cleanup **都會丟 RuntimeError**。
    `_resume_cloud_route` 與 `_best_effort_cloud_cleanup` 那兩個 try 就是為了這一刻
    （兩支的 docstring 都寫明了「cloud 有可能已經是 CloudRouteOff」），
    但在本 phase 之前**零測試**——註解說有防護，沒有人證明過。

    正確行為：兩個例外都被吃掉並留 warning -> fallback 本機
    -> reason=redelivered_without_result -> 照片照樣入庫一列。
    """
    caplog.set_level(logging.INFO)
    store = RememberDeletedStore()
    job_id = create_job(store)
    store.update(job_id, privacy="NON_SENSITIVE", route="cloud")
    gate = FakePrivacyGate(Verdict.SENSITIVE)  # 走到就代表「重送又問了一次閘門」＝違規

    run(job_id, store=store, gate=gate, cloud=cloud_ingest.CloudRouteOff())

    assert gate.calls == 0, "route 已經有值就不准再問閘門（design6 §2.1）"
    assert photo_repository.count_photos() == 1, "走本機把它做完（使用者無感）"
    assert store.deleted[job_id]["route"] == "local"
    assert any("fallback=local reason=redelivered_without_result" in m for m in caplog.messages), (
        f"design6 §2.1 要求的 log 字樣不見了：{caplog.messages}"
    )
    # 防假綠：RuntimeError 真的發生過才算數（不然「CloudRouteOff 安靜回 None」也會綠）
    assert any("崩潰重送時讀不到雲端結果" in m for m in caplog.messages), (
        f"fetch_result 應該丟 RuntimeError 並被 _resume_cloud_route 記下來：{caplog.messages}"
    )
```

```bash
pytest tests/integration/test_gated_ingest.py -k 雲端路已經關掉 -v   # 預期：1 passed
```

> 這一顆**首跑就該綠**（它釘的是 78〜80 已經做出來的行為）。首跑紅＝真的揪到缺陷 → 回 **80** 修。
> 反向驗證：把 `assert gate.calls == 0` 暫改成 `== 1`，要紅。

---

#### ④b 「處理別人的訊息」時 `store.get` 丟例外（+1；`tests/unit/test_cloud_ingest_unit.py`）

`CloudRoute._handle_foreign_message` 的第一行是 `other_job = store.get(message.job_id)`。
`store` 在正式路徑是 `RedisJobStore`——**它會丟例外**（Redis 半路連不上）。
`wait_result` 沒有接，所以例外一路飛到 `gated_ingest`，被裁決 R14 的那個 try
當成逾時處理（cleanup ＋ `fallback=local reason=result_timeout`）。

**結論：行為是安全的**（照片照樣入庫、使用者無感），**但白費一趟**——
我們自己的 result 可能下一秒就到了，卻因為**別人的**訊息把整個等待中斷掉。
Phase 80 的 review 記了這件事，裁決是「**釘住現況**，要改回 80 改」，所以本 phase 只補測試。

加到 `test_cloud_ingest_unit.py` 的 `test_收到別人的訊息而那筆已改走本機時刪訊息也刪S3` 後面：

```python
class ExplodingStore(InMemoryJobStore):
    """get() 一律丟例外的 JobStore（模擬 Redis 半路連不上）。"""

    def get(self, job_id: str):
        raise RuntimeError("Redis 連不上")


def test_處理別人的訊息時store掛掉_例外往外丟(monkeypatch):
    """規則 3 的邊界：`_handle_foreign_message` 要查 store 才知道「別人那筆還在不在」。

    store.get 丟例外時，`wait_result` **不接**——例外一路往外丟到 gated_ingest，
    那裡的 try（裁決 R14）把它當成逾時：cleanup ＋ fallback=local reason=result_timeout。
    行為是**安全**的（照片照樣入庫），代價是「白白放棄這一趟雲端」：
    我們自己的結果可能下一秒就到了，卻因為別人的訊息把整個等待中斷掉。

    這一顆只**釘住現況**（收尾 phase 不改產品行為）。真的要改成「查不到就當作沒人在等」
    要回 Phase 80 改 `_handle_foreign_message`，那是另一個 phase 的事。

    順帶釘兩件事：那則**別人的**訊息既沒被刪、也沒被還回去（真 SQS 要等可見度逾時才會
    再出現），別人的 S3 物件也一個都沒被動到——例外中斷不可以順手毀掉別人的東西。
    """
    advance_clock_each_call(monkeypatch, 2.0)
    mailbox = FakeMailbox()
    put_three_objects(mailbox, "別人")
    mailbox.send_result("別人")
    route = CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)

    with pytest.raises(RuntimeError):
        route.wait_result("我的", store=ExplodingStore())

    assert "delete_result_message" not in mailbox.calls
    assert "release_result_message" not in mailbox.calls
    assert mailbox.result_key("別人") in mailbox.objects
```

```bash
pytest tests/unit/test_cloud_ingest_unit.py -k store掛掉 -v      # 預期：1 passed
```

> 反向驗證：把 `pytest.raises(RuntimeError)` 暫時拿掉（直接呼叫），跑一次要紅在 `RuntimeError`。

---

- [x] 四項全部做完，四個檔各自跑過：
      `test_cloud_worker_unit.py`（32）、`test_design6_error_paths.py`（26）、
      `test_gated_ingest.py`（+1）、`test_cloud_ingest_unit.py`（+1）。
- [x] 這一節帶來的是 **+3 顆**（§4.4 那個 **715** 已經把它們算進去了；§8 的顆數表同）。

### 4.4 全量回歸與三死埠零依賴實證

```bash
# 1) 全量
pytest -q
# 預期：715 passed ＋ 0 skipped
#      ＝ 開工基線 702 ＋ §4.2／§4.3 的 10 ＋ §4.3.3 的 3
#      「0 skipped」＝ pytest 不會印那一段（自 Phase 51 摘標之後就沒有 skipped 了）
#      ⚠ 總覽 §9 寫的是 **682**（+10，累計）——那是 2026-08-31 排計畫時的估計值，
#        沒有算進 74〜92 各輪 review 補的顆數，也沒有 §4.3.3 那 3 顆。
#        **要對的是「本 phase +13」**（10 ＋ 3），不是絕對數字。差額要寫進 §8 與 REP。

# 2) 三個死埠一起指（增量六起的標準寫法）。顆數必須**完全相同**
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q

# 3) 一次一個，證明它們不會互相掩護（發現顆數變了才知道是哪一個）
AWS_ENDPOINT_URL=http://127.0.0.1:9 pytest -q
CELERY_BROKER_URL=redis://127.0.0.1:9/0 pytest -q
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q

# 4) 三份規格 binder 單獨再跑一次（規格共七份，其中三份有 binder；確認 .feature 沒被波及）
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
       tests/integration/test_camera_feature.py -v
# 預期：全綠，-v 的輸出裡一個 SKIPPED 都沒有（27 顆）

# 5) 規格檔真的一個字都沒改（工作區 ＋ 歷史兩邊都看：前面的 phase 可能已經進過 commit，
#    只看 git status 會漏掉「改了而且 commit 了」）
git status --short docs/spec/          # 預期：完全沒有輸出
git diff --stat -- docs/spec/          # 預期：完全沒有輸出
git log -1 --format='%h %s' -- docs/spec/
# 預期：`39e1c7e feat: 增量五乙丙段收官 Phase 65〜72…`（2026-08-27 規格改版）
#       ——不是任何增量六的 commit
git log -1 --format='%h %s' -- .github/workflows/test.yml
# 預期：4269985 ci: GitHub Actions 跑 ruff check／format 與 pytest（Phase 73；既有 CI 零改動）

# 6) 格式與 lint
ruff format --check app tests scripts && ruff check app tests scripts
```

- [x] 六項全部符合預期。顆數填進來：基準 **702** → 完成 **716**（計畫寫 715；多的那一顆是裁決 R18 ②，見 §10）。

> ⚠️ **埠 9 是保留的 discard 埠**，本機一定沒人在聽，指過去會**立刻** connection refused
> 而不是卡住等逾時。顆數不一樣、或出現連線逾時，代表**某條路徑真的去打了那個服務**
> ——最常見的原因是某顆測試繞過了假件（例如自己 `new` 了一個真的 `AwsMailbox`）。
>
> ⚠️ **絕對不要同時跑兩份 pytest。** `reset_tables` 每測都 `TRUNCATE` 同一個測試庫，
> 兩份同時跑會互相清掉對方的資料。症狀是**大量看似隨機的** 404 與
> `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣。

### 4.5 正式庫健檢（四個查詢；比照 phase-71 §4.6）

> 👤 **這一節與 §4.6 由 controller（Fable）親自執行**（2026-09-03 裁決 R3）：
> 它們碰的是**正式庫**與**真的 AWS**，subagent 一律零 `aws`／`docker`／`psql -d PersonalDocAI` 指令。
> 實作 subagent 負責的是 §4.2／§4.3／§4.3.3 的程式與 §4.4 的 pytest，
> 以及 §4.7／§4.8 兩份文件的初稿（數字留白，由 controller 填實查值）。

```bash
psql -d PersonalDocAI
```

在 psql 裡逐句執行：

```sql
-- a) 六個預設資料夾在，且全系統只有一個收件箱
SELECT id, name, is_inbox FROM folder ORDER BY id;
SELECT count(*) AS 收件箱數 FROM folder WHERE is_inbox;

-- b) 每一張照片都掛在某個資料夾底下，而且 category 與資料夾名稱一致
SELECT count(*) AS 沒有資料夾的照片 FROM photo WHERE folder_id IS NULL;
SELECT count(*) AS 對不起來的列
FROM photo p JOIN folder f ON f.id = p.folder_id
WHERE p.category IS DISTINCT FROM f.name;

-- c) ★ 增量六一欄都沒加：這一句要**恰好**列出 16 欄
SELECT string_agg(column_name, ', ' ORDER BY column_name) AS photo的欄位
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'photo';

-- d) 沒有孤兒列：有列就一定有文字（分析成功才寫得進來）
SELECT count(*) AS 有列但沒文字 FROM photo WHERE text IS NULL OR btrim(text) = '';
```

**預期：**

| 查詢 | 預期結果 |
|---|---|
| a | 至少 6 列（`1 未分類 t`、`2 收據 f`、`3 飲食 f`、`4 風景 f`、`5 文件 f`、`6 其他 f`，自建的排在 7 之後）；收件箱數 ＝ **1** |
| b | 兩個都是 **0** |
| c | **恰好 16 欄**，而且**沒有** `route`／`privacy`／`job_id`／`cloud_*` 之類的新欄（與【掃G】那顆的清單逐字相同） |
| d | **0**——「`text` 為空的記錄不存在」這條鐵律在正式庫也成立 |

離開 psql：`\q`。

- [ ] 四個查詢全部符合預期。
- [ ] 暫存區沒有留垃圾：

```bash
find data/staging -type f -mmin +1440 2>/dev/null | head
# 預期：沒有輸出（-mmin +1440 ＝超過 24 小時沒被動過的檔案）
```

### 4.6 四個服務、EC2 沒有 running、S3 是空的、佇列是空的

> 👤 **controller 親做**（同 §4.5）。下面每一條都要真的打到 AWS。

```bash
# ① 本機四個服務
docker compose ps --no-trunc
# 預期：四列——db（Up healthy）／redis（Up healthy）／app（Up）／worker（Up）
#      worker 那一列的 COMMAND 欄看得到 --concurrency=2
#      （--no-trunc 不能省：不加的話 COMMAND 只印開頭 20 個字左右）

set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY      # 下面的 aws 指令要用 admin 身分（§2 說明過）
AWS_REGION=${AWS_REGION:-ap-northeast-1}
aws sts get-caller-identity --query Arn --output text   # 預期結尾 :user/personaldocai-admin

# ② EC2 不准 running（Demo 都做完了）
aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table
# 預期：空表格。
# 若 .env 還留著舊 ID，也可以查那一筆：
# aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
#   --query 'Reservations[0].Instances[0].{Type:InstanceType,Arch:Architecture,State:State.Name}'
# 預期 Arch=x86_64；Type/State 兩種都算過：t3.xlarge/stopped（92-A 留著給 Demo 3）
#      或 g4dn.xlarge/terminated（92-B 測完刪機）；InvalidInstanceID.NotFound 也算過

# ③ S3 寄物櫃是空的（處理完就刪；D8）
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"
# 預期：回應裡**沒有** Contents（CLI 對空清單常常**什麼都不印**——那也是「空的」的意思）。
#      最多剩 Lifecycle 兩天內會清掉的殘骸

# ④ 兩條佇列都沒有殘訊息
for Q in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  aws sqs get-queue-attributes --queue-url "$Q" --region "$AWS_REGION" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes'
done
# 預期：兩條都是 {"ApproximateNumberOfMessages": "0", "ApproximateNumberOfMessagesNotVisible": "0"}
# 有殘訊息就 purge（⚠ 60 秒內只能做一次）：
#   aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"

# ⑤ 沒有誤開會燒點數的東西（§0 禁止第 4 條的真 AWS 那一半）
#    describe-nat-gateways 的過濾旗標是單數的 --filter（這支指令的怪癖，不是筆誤）；
#    只列 pending／available 兩種狀態，刪掉的（deleted）不算
aws ec2 describe-nat-gateways --region "$AWS_REGION" \
  --filter Name=state,Values=pending,available \
  --query 'NatGateways[].NatGatewayId' --output text                    # 預期：空
aws ec2 describe-addresses --region "$AWS_REGION" \
  --query 'Addresses[].AllocationId' --output text                      # 預期：空

# ⑥ EC2 的 inbound 仍然是空的（§0 禁止第 3 條）
aws ec2 describe-security-groups --region "$AWS_REGION" \
  --filters Name=group-name,Values=personaldocai-worker-sg \
  --query 'SecurityGroups[0].{In:IpPermissions,Out:IpPermissionsEgress[].{P:IpProtocol,From:FromPort,To:ToPort}}'
# 預期：In 是 []；Out 只有一條 tcp 443 -> 443

# ⑦ Budget 還在、還會寄信（§7 警報）
#    ⚠ 這兩條只有 admin 身分看得到：最小權限的 personaldocai-mac 沒有 budgets:ViewBudget，
#      而且 root 要先開過「IAM user and role access to billing information」（Phase 82 §4.3
#      最後一步）。回 AccessDenied 先看上面 sts 那一行的 Arn 是不是 admin。
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit}' --output table
aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" \
  --budget-name personaldocai-budget \
  --query 'Notifications[].{Type:NotificationType,Th:Threshold}'
# 預期：personaldocai-budget、上限 5 USD；ACTUAL 與 FORECASTED 各一筆、Threshold 80
```

- [ ] 七項全部符合預期。**⑤⑥ 有任何輸出就是違反了 §0 的禁止，停下來處理。**

### 4.7 產出增量六驗收包

> 📌 **體例**：與既有的 `docs/plan/report/2026-08-26-增量五驗收包-請產品負責人確認.md`
> 與 `2026-08-23-G1驗收包-請產品負責人確認.md` 相同：
> `# ⋯驗收包（日期）——請產品負責人確認` 標題 → `> **給產品負責人：**` 引言
> （含「說出哪一句話才算通過」）→ `**準備：**` ＋ 一段 bash →
> **A 段自動化用 `- [x]`（實作者可自勾）** → **B〜E 段人工留白（表格 ⬜）** →
> **F 段一行簽名 `日期：__________`** → `## 附註（實作者）`。

- [x] 新建 `docs/plan/report/<你交出去的那一天>-增量六驗收包-請產品負責人確認.md`
      （檔名日期換成實際日期），內容**照抄下面整段**，
      **A 段的數字換成你這次實際跑出來的**：

`````markdown
# 增量六驗收包（2026-XX-XX）——請產品負責人確認

> **給產品負責人：** 這是「本機隱私閘門」與「可關掉的雲端 worker」的驗收清單。
> 全部看過、沒問題的話，請說一句「**增量六沒問題**」——有這句話，實作者才會
> 把 `docs/plan/unfinish/` 剩下的 4 份計畫檔（總覽 ＋ phase-93／94／95）歸檔、
> 把整個增量進 commit（74〜92 那 19 份已經在 `finish/` 了，其中 83〜92 的搬移還沒 commit，
> 會跟著這一次一起進去）。
>
> 清單分六段：
> **A** 是自動化跑出來的數字（實作者已勾，你看一眼就好）；
> **B〜E** 是 design6 §12 的四個 Demo ＋ 費用／安全三條，**要你親自做、親自看**；
> **F** 是你簽名。最後還有一段「**要你追認的裁決**」——那是 design6 沒寫、由計畫層決定的事。

**準備：**

```bash
cd /Users/linjunting/personalDocAI
source .venv/bin/activate
docker compose -f compose.yaml up -d
docker compose -f compose.yaml logs -f app worker

# 另開一個視窗：把 .env 的變數放進 shell（下面的 aws 指令都要用），
# 然後把 .env 那兩把 key 從 shell 拿掉——aws 指令一律用 ~/.aws 的 personaldocai-admin
# （.env 裡的是最小權限的 personaldocai-mac，看不到 Budget、也看不到 NAT／EIP 清單）
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws sts get-caller-identity --query Arn --output text   # 結尾要是 :user/personaldocai-admin
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "$AWS_REGION / $S3_BUCKET"     # ⚠ 這一行的輸出不要貼進任何文件
```

網址一律 **`https://`**（開頭多一個 s；容器固定跑 HTTPS，`http://` 完全連不上）：

- 上傳頁 `https://localhost:8000/ui/upload.html`
- 待決定頁 `https://localhost:8000/ui/pending.html`
- 問問題頁 `https://localhost:8000/ui/ask.html`

> 💡 **B 段（Demo 1）與 E 段不必開 EC2。** 只有 C 段（Demo 2）與 D 段（Demo 3 的後半）
> 要 Start，而且**做完一定要 Stop**（E 段最後一條會再確認一次）。

---

## A. 自動化（實作者已跑，請看數字）

- [x] `pytest -q` ＝ **＿＿＿ passed ＋ 0 skipped**（增量六開工時是 **543**，收工預期 **715**）
- [x] **三個死埠一起指，顆數完全相同** ＝ 測試從頭到尾沒有連過真的 AWS／Redis／Ollama

  ```bash
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

- [x] `/openapi.json` 端點數 ＝ **22**（**與增量五完全相同**——本增量一支端點都沒加）
- [x] DELETE 動詞 ＝ **0**（系統仍然沒有任何刪除功能）
- [x] `photo` 表欄位 ＝ **16 欄，與增量五結束時逐字相同**
      （`route`／`privacy` 住在 JobStore，不進資料庫）
- [x] design6 §8 錯誤表 **10 列**逐列有測試把關（大多在 Phase 74〜94 各自的測試檔；
      收尾檔 `tests/integration/test_design6_error_paths.py` 共 **26 顆**
      ＝ Dockerfile／compose 4 ＋ EC2 unit 2 ＋ OIDC 4 ＋ CD 6 ＋ 本輪 10；
      逐列對照表在 phase-95 §4.1）
- [x] `docker compose ps` ＝ **四個服務**：`db`／`redis`／`app`／`worker`
      （**沒有**為了雲端多開第五個），worker 的 concurrency ＝ **2**
- [x] 正式庫健檢：資料夾六筆、收件箱恰 1、沒有 `folder_id` 為空的照片、
      沒有 `text` 為空的照片、`photo` 表 16 欄
- [x] `docs/spec/` **全增量一個字都沒改**（`git status --short docs/spec/` 無輸出；
      `git log -1 -- docs/spec/` 最後一筆仍是增量五 Phase 72 的規格改版）
- [x] `.github/workflows/test.yml`（既有 CI）**一個字都沒改**
      （`git log -1 -- .github/workflows/test.yml` 仍是 Phase 73 那一筆 `4269985`）

---

## B. Demo 1 — 敏感留本機（design6 §12 原文）

> 原文：**上傳判定敏感（或規則打中）的檔；S3 bucket 無該 `job_id`；待決定有照片。**

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| B1 | 準備一張**內容**看起來像證件的圖（畫面上有姓名、出生年月日、證號那種；⚠ **檔名完全不影響判斷**——閘門是 VLM 看圖的一句短問，2026-09-01 改判後**不看檔名**，取名叫 `身分證正面.jpg` 一點用都沒有）。上傳頁選它按上傳：畫面**立刻**回應，右下角出現一列進度 | ⬜ |
| B2 | 馬上看 S3：**完全沒有東西**（連 `documents/` 前綴都不會出現）<br>`aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"` | ⬜ |
| B3 | 看 worker 的 log（指令見表格下方）：有一行 `route=local verdict=SENSITIVE`；**沒有**任何 `fallback=` 那一行（它根本沒打算走雲端） | ⬜ |
| B4 | 等 worker 跑完（本機模型 64〜88 秒；想快就把頁首開關撥到「雲端」）：進度列自己消失、頂欄「待決定（N）」+1、待決定頁多一張 | ⬜ |
| B5 | 再傳一張**內容說不準**的（模糊的、拍歪的、或是一張純色圖；用手機鏡頭隨手拍一張也可以）：一樣走本機，log 是 `route=local verdict=UNCERTAIN` | ⬜ |

看 worker log 的指令（B3、B5、C5、C9 都用這一條）：

```bash
docker compose logs --tail=200 worker | grep -e "route=" -e "fallback="
```

> 💡 **B5 是這個增量最重要的一條規則的實地演練：「不確定 ＝ 當敏感辦」。**
> 閘門判斷失誤時，代價是「這張照片沒有卸到雲端」（＝跟增量五一模一樣），
> 而不是「敏感檔外流」。
>
> 💡 **B 段全程不必開 EC2**，而且**閘門看的是圖、不是檔名**（2026-09-01 改判；總覽 §10.1 f）。
> 想快一點就先把頁首那顆「AI 模型」開關撥到「雲端」再上傳（閘門那句短問：本機 1〜2 分鐘、
> 雲端不到 1 秒），做完撥回「本機」。⚠ 快照是在**上傳當下**抄進 job 的，所以順序不能顛倒。

---

## C. Demo 2 ＋ 2b — 非敏感走雲端再回家、遠端關掉自動退回（design6 §12 原文）

> Demo 2 原文：**EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉；照片進待決定；詢問能問到。**
> Demo 2b 原文：**EC2 Stop 後上傳非敏感；不必改任何設定；進度與入庫與增量五相同；S3 不出現新物件。**

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| C1 | 開機並等它 running：<br>`aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"`<br>`aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"` | ⬜ |
| C2 | 確認本機 `.env` 是 `CLOUD_ROUTE=ec2`，然後 `docker compose -f compose.yaml restart worker` | ⬜ |
| C3 | 上傳一張**內容**明顯不敏感的圖（收據、菜單、風景照；同樣**與檔名無關**）：畫面立刻回應（202） | ⬜ |
| C4 | **馬上**看 S3（動作很快，晚了就看不到）：出現 `documents/<job_id>/context.json` 與 `input.jpg`，之後多一個 `result.json`<br>`aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION" --query 'Contents[].Key' --output text` | ⬜ |
| C5 | worker 的 log（同 B 段那條指令）有 `route=cloud verdict=NON_SENSITIVE`，**沒有** `fallback=` 那一行 | ⬜ |
| C6 | 跑完之後 S3 **是空的**（本機把三個物件都刪了）；照片進了待決定牆；到問問題頁問一句跟那張照片有關的話，**回答引用得到它** | ⬜ |
| C7 | **Demo 2b：** 關機並等它 stopped：<br>`aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"`<br>`aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"` | ⬜ |
| C8 | **本機什麼設定都不要改**（`CLOUD_ROUTE` 仍是 `ec2`），再上傳一張內容不敏感的（另一張收據或菜單）：**仍然是 202**，右下角進度列的樣子與增量五**完全一樣** | ⬜ |
| C9 | worker 的 log（同 B 段那條指令）有 `fallback=local reason=remote_unavailable`；S3 **一個新物件都沒有**；等它跑完，照片一樣入庫 | ⬜ |

> 💡 **C8／C9 就是這個增量的核心承諾：遠端關掉時，你完全感覺不到。**
> 唯一的差別在 worker 的 log 多一行字。
> 2b **必須先 Stop**（碟還在、探測才會說不是 running）。C9 過了之後**不要留 running 的機器**：
> 92-A 那台 `t3.xlarge` 停著即可（30 GB ≈ $2.9／月，Demo 3 還要用）；只有 92-B 的 GPU 機才 Terminate（見 D6／E5）。

---

## D. Demo 3 — CD（design6 §12 原文）

> 原文：**改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA →
> Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）。**
>
> ⏳ **這一段要等你自己 push 之後才做得了**（2026-09-03 裁決 R0）。
> CD 是被「`test` 在 `main` 上跑綠」觸發的，而 `deploy.yml` 這個檔**必須先存在於 `main`**
> 才會生效——這兩件事都需要 `git push`，而**實作者全程不 commit、不 push**
> （目前本機有 10 個 commit 還沒推上去，`origin/main` 停在 `a53ab57`）。
>
> **所以：** 你決定 commit＋push 之後，照 `docs/plan/unfinish/phase-94-CD工作流程.md` §4.8
> 的逐步手冊做一次（步驟 0 先 `git push origin main` 把既有的 commit 連同 `deploy.yml`
> 一起推上去——**那一輪的 `deploy` 有沒有跑不算數**；步驟 1 再改 `cloud_worker.py` 一行註解、
> commit、push，那一輪才是 Demo 3），然後回來勾下面六格。
>
> **本輪實作者就位的是：** `deploy.yml`、6 顆 CD 掃碼測試、README 的 CI/CD 小段、
> GitHub 的 secret 與 variable。**沒有就位的只有「真的跑一次」。**

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| D1 | 到 GitHub 的 Actions 頁面看那次 push：**`test` 綠了之後，`deploy` 才出現並開始跑**（不是同時） | ⬜ |
| D2 | `deploy` 的七個 step 全綠。⏱ `Build and push` 第一次要 **5〜15 分鐘**（多架構：amd64 原生、arm64 走 QEMU——這是預期的，不是壞掉） | ⬜ |
| D3 | 最後一步的 log 是 `instance state:` **不是** `running`（`stopped`／`terminated`／查無此實例都算），並印一則藍色提示 `instance not running; image pushed, next Start pulls latest`，**而且 job 是綠的**（機器沒開不算部署失敗） | ⬜ |
| D4 | ECR 上看得到那次 commit 的完整 sha，而且與 `latest` 在**同一組**（＝同一份映像掛兩個 tag）<br>`aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" --query 'imageDetails[?imageTags].imageTags[]' --output json` | ⬜ |
| D5 | Start 之後，遠端工人的啟動 log 的 `version=` **逐字等於**那個 sha（＝真的跑的是新映像；**不是**看 `latest` 這個標籤）<br>指令見 phase-94 §4.8 步驟 5 | ⬜ |
| D6 | **做完收工**：Demo 3 用的是 92-A 那台 `t3.xlarge` → **Stop**（30 GB ≈ $2.9／月，Budget 內，下次還要用）；只有 92-B 的 GPU 機才 **Terminate**（80 GB 關機約 $7.7／月）。SG／IAM／S3／SQS／ECR 一律留下。 | ⬜ |

---

## E. 費用／安全（design6 §12 剩下的三條）

> 原文三條經 2026-09-03 改寫：**Paid plan、Budget 有寄信設定** ／
> **Security group inbound 空；無 NAT、無 EIP** ／ **pytest 全綠且不碰真 AWS**。
> （原文「Free plan、未升 Paid」已過時——帳號已升 Paid。）

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| E1 | AWS Console → Billing and Cost Management → 確認方案是 **Paid**（2026-09-03 已升）。忘關機器會**扣卡**（`t3.xlarge` $0.2176／小時、`g4dn.xlarge` $0.71／小時）。Budget 上限仍 $5：92-A 停著的 30 GB 碟約 $2.9／月（在額度內），GPU 機跑一小時就可能觸發 80% 警報——這是提醒不是 bug | ⬜ |
| E2 | Budget 還在而且會寄信（**用 `personaldocai-admin` 身分**：它是 `~/.aws` 的 default profile，前提是「準備」那段已經 `unset` 掉 `.env` 的兩把 key，而且 root 已開「IAM user and role access to billing information」——Phase 82 §4.3 最後一步；最小權限的 `personaldocai-mac` 沒有 `budgets:ViewBudget`，用它會 AccessDenied）：`aws budgets describe-budgets --account-id "$ACCOUNT_ID" --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit}' --output table`（預期：`personaldocai-budget`、5 USD）<br>`aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" --budget-name personaldocai-budget --query 'Notifications[].{Type:NotificationType,Th:Threshold}'`（預期：ACTUAL 與 FORECASTED 各一筆、80） | ⬜ |
| E3 | Security group 的 inbound 是**空的**、outbound 只有 tcp 443：<br>`aws ec2 describe-security-groups --region "$AWS_REGION" --filters Name=group-name,Values=personaldocai-worker-sg --query 'SecurityGroups[0].IpPermissions'`（預期 `[]`） | ⬜ |
| E4 | 沒有 NAT、沒有 Elastic IP：<br>`aws ec2 describe-nat-gateways --region "$AWS_REGION" --filter Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId' --output text`（預期空；`--filter` 是單數，這支指令的怪癖）<br>`aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text`（預期空） | ⬜ |
| E5 | **沒有 running 的 EC2**：`aws ec2 describe-instances --region "$AWS_REGION" --filters Name=instance-state-name,Values=running --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType}' --output table`（預期空表）。若 `.env` 的 ID 還在：State 是 **`stopped`**（92-A 的 `t3.xlarge`，刻意留著給 Demo 3）或 **`terminated`**（92-B 的 `g4dn.xlarge`）都算過；Arch 都應是 `x86_64`。**只有「running」不算過** | ⬜ |
| E6 | S3 是空的、兩條佇列訊息數都是 0（見上面 §4.6 的 ③④ 指令） | ⬜ |
| E7 | 看一眼 A 段第一行與第二行：`pytest -q` 全綠、三死埠顆數相同 | ⬜ |

---

## F. 最後

- [ ] 我（產品負責人）確認：**增量六沒問題。** 日期：__________

---

## 要你追認的裁決（design6 沒寫、由計畫層決定的 33 條 ＋ 本輪校準的 12 條）

> 這些**不是**你拍板的字，是實作計畫為了做得下去而補的決定。
> 前 33 條都寫在總覽 §10（§10.1 的 a〜l 共 12 條 ＋ §10.2 的 A〜U 共 21 條），
> 也都註明「不同意的話回哪個 phase 改」；最後 12 條是 2026-09-03 校準這一輪新裁的。
> **請逐條看過並打勾；有任何一條不同意，直接說，實作者會回那個 phase 改。**

| # | 裁決 | 追認 |
|---|---|---|
| a | S3 多一個鍵 `documents/{job_id}/context.json`（工人靠它組出**同一份** prompt；放 SQS 會違反「body 只含 job_id、s3_key」） | ⬜ |
| b | 分支是 **`main`**，OIDC 的 `sub` 鎖 `…:ref:refs/heads/main`（design6 §6 寫的 `master` 是筆誤） | ⬜ |
| c | 本機「等雲端結果」是在**同一個 Celery 任務裡同步長輪詢**（佔一個 concurrency 名額，但不佔 GPU） | ⬜ |
| d | results 佇列是共用的，收到別人的 `job_id` 要「還回去或當殘訊息刪掉」 | ⬜ |
| e | 開機拉 `latest`；CD 同時推 `<sha>` 與 `latest`；「跑的是不是新映像」靠工人 log 的 `version=` 驗 | ⬜ |
| f | 隱私閘門**不看檔名**（2026-09-01 你改判的）：`camera.jpg`、`IMG_4821.jpg`、`身分證.jpg` 一律送 VLM 短問；短問失敗 → `UNCERTAIN` ＝ 留本機、不進 S3 | ⬜ |
| g | **雲端看圖三次都失敗＝這筆 job 失敗**，不是再用本機看一次（遠端活著，只是 AI 看不懂） | ⬜ |
| h | EC2 上的機密用 **Session Manager 手動**放 `/opt/personaldocai/worker.env`，不用 Parameter Store | ⬜ |
| i | 改掉增量五那顆「`boto3` 禁止」的掃碼測試（design6 §1.1 正式推翻）；`s3fs`／`minio`／`google-cloud-storage` 仍然禁止 | ⬜ |
| j | `Dockerfile` 改多階段、`app` 那一段放最後，所以 `compose.yaml` 一個字都不必改 | ⬜ |
| k | 工人程式放 `app/workers/cloud_worker.py`（`.dockerignore` 排除 `scripts/`，放那裡會**安靜地**不進映像） | ⬜ |
| l | `CLOUD_ROUTE=assume` 只給 Mac 上跑工人與除錯用；日常一律 `ec2` | ⬜ |
| A | design6 §9 說「測試名稱實作時可調」——計畫層改成**不可調**（22 份文件要互相對齊） | ⬜ |
| B | `test_design6_error_paths.py` 在 **Phase 90 就開檔**，不等到 95 | ⬜ |
| C | 雲端路拆成兩層：`cloud_ingest.py`（流程）＋ `aws_mailbox.py`（唯一碰 boto3） | ⬜ |
| D | 等雲端結果時 job 的 status **維持 `analyzing`**，不新增第五種狀態 | ⬜ |
| E | 雲端看圖的次數**不回寫** `job["attempt"]`（進度面板的「第 N 次」不會忽然跳） | ⬜ |
| F | PDF 走雲端路時，每頁 PNG **本機自己再 `render_pages()` 一次**，不把工人拆好的頁放 S3 | ⬜ |
| G | ★G1 ＝ 甲的驗收 ＋ 你明示「可以開始花 AWS 資源」；**Phase 82 排在 G1 之後**。帳號其後已升 Paid（2026-09-03）；GPU 配額是另一筆申請 | ⬜ |
| H | **Phase 76 是計畫層加的一份純重構**（design6 完全沒提）；沒有它，Phase 79 只能複製一份會漂移的同款程式碼 | ⬜ |
| I | 多建一個 **`personaldocai-admin`**（AdministratorAccess）**只給 Mac 上的 `aws` CLI 用**；程式用的 `personaldocai-mac` 仍是最小權限，它的 key 只在 `.env`（載進 shell 後要 `unset`） | ⬜ |
| J | Phase 83 **多加 1 顆** `test_get_object拿得回位元組而delete_objects送出鍵清單`（+16 不是 +15） | ⬜ |
| K | 工人收到**壞訊息**（`s3_key` 空的、或副檔名不是 .jpg／.png／.pdf）→ log warning、刪掉那則 jobs 訊息、什麼都不寫（不然它每 900 秒回來一次） | ⬜ |
| L | 隱私閘門的**縮圖**（長邊 ≤512、轉 PNG）在呼叫短問模型**之前**做；短問跟頁首 AI 開關走、模型名與 `get_vlm` 同一套 | ⬜ |
| M | OIDC 的 `sub` 用 GitHub 的**不可變主體格式**（含 owner／repo 的數字 ID），不是 design6 §6 寫的舊格式；`deploy` 的 `if` 另外要求 `event == 'push'`（防 fork PR 的分支也叫 `main`） | ⬜ |
| N | `personaldocai-mac` 那把 key **兩邊的權限都要有**（本機端 ＋ 工人端）：Phase 88／90 在這台 Mac 上跑工人用的就是它 | ⬜ |
| O | systemd unit 用 `docker stop -t 120` ＋ `TimeoutStopSec=150`（多頁 PDF 可能超過 docker 預設的 10 秒寬限）；`run-instances` 加 `HttpPutResponseHopLimit=2`（容器裡的 boto3 拿 instance role 憑證要多一跳） | ⬜ |
| P | 兩份 IAM policy 都加 bucket ARN 的 `s3:ListBucket`——沒有它，對不存在的鍵做 `GetObject` 會回 403 而不是 404，而本增量有三處靠 404 判「還沒有」 | ⬜ |
| Q | SQS 單則上限現在是 **1 MiB**（design6 §1.2 寫的 256 KB 是舊值）；結論不變——影像仍然不進 SQS | ⬜ |
| R | 雲端路落庫的順序固定為 **INSERT → 立刻寫 `photo_ids` → cleanup S3 → 收尾**（cleanup 是網路呼叫，可拖數十秒；順序反了會在崩潰重送時多插一張照片） | ⬜ |
| S | 閘門跑在 Celery worker，而 worker 行程的 `AI_BACKEND` 永遠是 `local`——所以閘門要用**入列當下抄進 job 的快照**建（`build_privacy_gate_for_backend(job["ai_backend"])`），不然頁首撥雲端時閘門仍打本機而且**安靜** | ⬜ |
| T | **2026-09-03 你改判**：EC2 改 GPU 機自裝 Ollama（design6 D12 作廢）。工人多一個 `WORKER_VLM_BACKEND`（`cloud` 預設｜`local`）、映像改推多架構、`deploy/ec2/` 三檔跟著改 | ⬜ |
| U | **2026-09-03 你拍板**：Phase 92 拆成 **92-A**（`t3.xlarge` CPU 機，把整條 AWS 流程與 Demo 2／2b 驗完，收工 **Stop**）與 **92-B**（`g4dn.xlarge` GPU 機，等配額，測完 **Terminate**）；★G3 移到 92-A 之後 | ⬜ |

**2026-09-03 校準這一輪新裁的 12 條（`.superpowers/sdd/phase0903-1/progress.md` 的 R0〜R11）：**

| # | 裁決 | 追認 |
|---|---|---|
| R0 | 實作者**全程不 commit、不 push**；**Demo 3 留給你自己做**（見 D 段） | ⬜ |
| R1 | 程式碼裡的識別字（函式、類別、fixture、變數、常數）**一律英文**；`test_中文` 測試名、註解、docstring、log 訊息、斷言訊息仍是中文 | ⬜ |
| R2 | **★G3 判定為已通過**（憑據：commit `c40a3b3` 的 92-A 三份文件、`CLAUDE.md` 概述的「Demo 2／2b 通過」、dev-prompt 明示執行 93〜95） | ⬜ |
| R3 | AWS 資源的建立、`gh secret／variable set`、改 `.env`、重啟容器、真煙霧、正式庫健檢**一律由 controller 親自執行**，實作 subagent 零 `aws`／`gh`／`docker` 指令 | ⬜ |
| R4 | 顆數以 **2026-09-03 實查的 692** 起算（不是總覽 §9 的估計值）：93 → 696、94 → 702、95 → 712 ＋ §4.3.3 的 3 ＝ **715** | ⬜ |
| R5 | 93／94／95 三份計畫檔由三位校準者平行改，**總覽由 controller 改**（避免互相覆蓋） | ⬜ |
| R6 | 93〜95 全程**不需要你的手機**（零前端、零鏡頭改動） | ⬜ |
| R7 | 總覽 §2.7 兩個過期的測試名以現況為準（94 的多架構那顆、95 的「不會去**碰**AI後端開關」） | ⬜ |
| R8 | 95 的四個過期段落改寫：§4.3.1 已修不必再做、README 543、§4.9 歸檔清單、E 段 Paid | ⬜ |
| R9 | 前幾輪 review **停放**的四項在 95 一次結清（§4.3.3）；其中 `read_context` 的型別加固是本 phase **唯一**的產品碼改動 | ⬜ |
| R10 | 95 的【掃E】改成與 Phase 87 那顆 ast 掃碼**互補**（87 掃 import 名單，95 掃識別字／字串常數／動態載入），不重抄 | ⬜ |
| R11 | 外部事實（AWS／GitHub 文件、六個 action 的版本）一律用工具**現查**並在計畫檔附來源，不憑記憶 | ⬜ |

---

## 附註（實作者）

**規格檔（★）**：`docs/spec/` **全增量一個字都沒改**——design6 §10 明文
「本增量對外上傳契約仍是 202 ＋ 分析成功才有照片；**不必**為了 fallback 改 Gherkin
（那是內部路由）」。要加「敏感不上雲」的 Example **需要另外核准**，不在本增量範圍。

**已知限制（design6 §13 ＋ 計畫層補充，2026-09-03 改寫過時條；請在簽名之前看過）：**

- **EC2 沒開（Stop 或 Terminate）的時候不卸壓。** 沒有雲端管線，每一張非敏感照片都會退回本機看圖。
  要卸壓就先 Start（或重建一台）。92-A 那台 `t3.xlarge` 停著只要 ≈ $2.9／月，刻意留著；
  但**不要**留 stopped 的 80 GB GPU 碟（≈ $7.7／月，超過 Budget）。
- **頁首撥雲端時，敏感檔的影像仍然可以去 ollama.com。** Privacy Gate 管的是
  S3／SQS／EC2 這條管線，**不管**頁首那顆開關（D6）。
  ⚠ **對外說法不可以寫成「敏感資料完全不出雲」**（design6 §6 明文）。
- **EC2 不會 magically 讓「本機 ＋ 頁首雲端開關」變快**（不論工人是 92-A 的轉送 `ollama.com`
  還是 92-B 的自跑 GPU）。
  多了 S3 上傳、SQS 來回、S3 下載。開機的價值是**卸掉本機的 Celery 名額**與**作品集管線**。
- **帳號已升 Paid。** 忘關機器會**扣卡**：`t3.xlarge` 約 $0.2176／小時（一天 ≈ $5.2）、
  `g4dn.xlarge` 約 $0.71／小時（一天 ≈ $17），兩者都另加 IPv4 $0.005／小時。
  雲端上沒有正本——S3 只有處理中的暫存檔、EC2 只有一支無狀態工人，照片一張都不會少。
- **Classifier 一定會漏。** 閘門是 VLM 短問（不看檔名）；證件照未必被判敏感。所以「不確定」一律當本機。
  **這不是合規等級的 DLP。**
- **等雲端結果的時候佔一個 Celery 名額。** 兩個名額之一在長輪詢（不佔本機 GPU）。
- **results 佇列是共用的**，會收到別人的訊息；本機會還回去或當殘訊息刪掉。
- **開機拉的是 `latest`**，不是某個固定 sha。
- **GitHub runner 建多架構的 arm64 那一半很慢**（第一次 build 5〜15 分鐘；amd64 是原生）。
- **host 的 `.venv` 與映像裡的套件會分岔**（`requirements.txt` 全是 `>=`），
  worker 映像同樣有這個問題。所以「重建映像」要當成需要手動煙霧一次的動作。
`````

- [x] 交出去之前，把 A 段的 `＿＿＿` 全部填上實際數字、標題的日期換成當天。
- [x] **停在這裡。** 不要因為「看起來都沒問題」就自己勾 B〜F 段、或自己 commit。

### 4.8 產出進度檔（`docs/plan/todo/`）

比照既有慣例（檔名格式 `<日期>-<這一批的名字>-TODO.md`，例如
`2026-08-26-增量五收尾71-72-TODO.md`）新建
**`docs/plan/todo/2026-09-03-階段十七-增量六收尾95-TODO.md`**（日期換成實際交出去那一天），
內容照抄下面整段、**把 `[ ]` 依實際進度改成 `[x]`**。

> 📌 **本輪的 TODO 編號從「階段十四」起算**（2026-09-03 這一批共五份）：
> 十四＝三份計畫檔校準、十五＝Phase 93、十六＝Phase 94、**十七＝Phase 95（本檔）**、
> 十八＝總驗收。`docs/plan/todo/` 已經有 `2026-09-03-階段十四-計畫檔校準93到95-TODO.md`，
> 檔名體例照著它寫。
（74〜94 各批做的時候已經各有自己的 TODO／REP；本檔是收尾那一份，順便把整個增量的
閘門紀錄集中留一次。）

````markdown
# 2026-XX-XX 增量六收尾（Phase 95；74〜94 進度總表）TODO

> 計畫檔：`docs/plan/unfinish/phase-00-增量六總覽.md` ＋ `phase-74`〜`phase-95`。
> canonical design：`docs/design/design6.md`（2026-08-31 產品負責人對話拍板）。

## 實作邏輯

甲（74〜81）全程 TDD、**零 AWS**：先做隱私閘門與 fallback 契約，行為與增量五 100% 相同。
★G1 之後才開帳號。乙（82〜84）S3 寄物櫃、丙（85〜86）兩條 SQS、丁（87〜88）Mac 上的工人、
戊（89〜92）EC2、己（93〜94）CD、95 收尾與驗收包。三個閘門都是**人**的動作。

## ★ 閘門紀錄（誰、什麼時候、憑什麼）

- ★G1（81 之後、82 之前）：＿＿＿＿＿＿（日期／依據）
- ★G2（90 之後、91 之前）：＿＿＿＿＿＿
- ★G3（92 之後、93 之前）：＿＿＿＿＿＿

## 步驟

- [ ] 甲 74〜81：privacy_gate／ingest_job 重構／cloud_ingest 契約＋第五道安全網／
      gated_ingest 接線／CloudRoute 單圖／逾時與冪等／PDF（543 → **616**）
- [ ] ★G1
- [ ] 乙 82〜84：開戶＋Budget＋兩個 IAM user／`aws_mailbox.py`（+16，總覽追認項 J）＋
      改 design5 的 boto3 掃碼／建 bucket（616 → **632**）
- [ ] 丙 85〜86：兩條佇列／`get_cloud_route()` 補 assume ＋真 AWS 逾時煙霧（632 → **634**）
- [ ] 丁 87〜88：`process_job_message`＋假信箱端到端／主迴圈＋Mac 上真跑（634 → **651**）
- [ ] 戊前半 89〜90：`Ec2Probe`／Dockerfile 多階段 arm64（651 → **662**）
- [ ] ★G2
- [ ] 戊後半 91〜92：SG／IAM role／ECR／真機 Demo 2／2b（**92-A `t3.xlarge`**）／文件三份
      （92 是人工 phase +0，但收尾時另補了 2 顆掃碼＝`f2fc067`；**實查基線 692**）
- [ ] ★G3
- [ ] 己 93〜94：OIDC 部署角色（692 → **696**）／`deploy.yml`（696 → **702**）
      ＋ Demo 3（**待產品負責人 push 後執行**）
- [ ] 95：錯誤表盤點＋2 顆補缺＋8 顆掃碼＋停放項 3 顆＋三死埠實證＋驗收包（702 → **715**）
- [ ] 寫 REP（`docs/plan/report/<日期>-增量六收尾95-REP.md`）

> ⚠️ 上面括號裡「543 → 616 → 632 …」那幾個是**總覽 §9 排計畫時的估計值**；
> 74〜92 每一輪 review 都有補顆數，所以從 82 起絕對值就對不上了
> （2026-09-03 實查：Phase 92 之後是 **692**，不是 662）。
> **要對的是每個 phase「新增幾顆」**，絕對值一律以當天的 `pytest -q` 為準。

## 鐵律

- 顆數只增不減、`skipped` 全程 0；不准為了湊數字改或刪測試
- `docs/spec/` 全程零改動（`git status --short docs/spec/` 必須一直是空的）
- 端點恆 22、openapi 零 DELETE；`compose.yaml` 零改動；`photo` 表零改動
- 每個 phase 的驗收都要有三死埠零依賴實證
- **每一次開 EC2 之後都要 Stop**；`docker compose down -v` 永遠禁止
- 不 commit、不搬 `unfinish/` → `finish/`（隨 commit 執行，時機由產品負責人決定）
````

- [x] 建好了，而且閘門那三行**留白等人填**（不要自己寫日期）。

### 4.9 歸檔清單（**寫下來，不執行**）

**現況（2026-09-03 實查，與舊版計畫寫的不一樣，注意看）：**

| 在哪裡 | 有哪些 | 狀態 |
|---|---|---|
| `docs/plan/unfinish/` | `phase-00-增量六總覽.md`、`phase-93`、`phase-94`、`phase-95` | **只剩這 4 份** |
| `docs/plan/finish/` | `phase-73`〜`phase-82`（10 份） | 已搬、**已 commit** |
| `docs/plan/finish/` | `phase-83`〜`phase-92`（10 份） | 已搬、**還沒 commit**（工作樹裡是 10 個 `D` ＋ 10 個 `??`） |

也就是說：**產品負責人自己已經把 74〜92 搬完了**（`phase-73` 也早就在 `finish/`）。
本 phase 要寫下來的歸檔清單因此只剩 **4 份**：

```text
phase-00-增量六總覽.md
phase-93-GitHub_OIDC與部署角色.md
phase-94-CD工作流程.md
phase-95-增量六錯誤收尾與驗收包.md
```

搬法（**產品負責人指示才做**）：

```bash
git mv docs/plan/unfinish/phase-00-增量六總覽.md docs/plan/finish/
for n in 93 94 95; do
  git mv docs/plan/unfinish/phase-$n-*.md docs/plan/finish/
done
ls docs/plan/unfinish/
# 預期：**完全沒有輸出**（`unfinish/` 清空——與增量五收官時同一個狀態）
```

⚠️ 那一次 commit 裡除了這 4 份的 rename，還會帶著**83〜92 那 10 份已經搬好但還沒 commit 的
rename**（`git status` 現在看到的 10 個 `D` ＋ 10 個 `??`）。那是產品負責人自己搬的，
**不要動它、也不要「幫忙」還原**。

產品負責人指示 commit 時，本 phase 的檔案清單（給那一次 `git add` 用；歸檔的 `git mv` 另計）：

```bash
git add tests/integration/test_design6_error_paths.py \
        tests/unit/test_cloud_worker_unit.py \
        tests/unit/test_cloud_ingest_unit.py \
        tests/integration/test_gated_ingest.py \
        app/workers/cloud_worker.py \
        README.md CLAUDE.md \
        docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md \
        docs/plan/todo/<日期>-階段十七-增量六收尾95-TODO.md
# commit 訊息（供參考）：
#   test: Phase 95 增量六錯誤收尾——§8 十列逐列點名＋2 顆真缺口（雲端看不懂＝整筆失敗不 fallback、
#   遠端關掉仍 202）＋8 顆掃碼（NAT／EIP／Lambda／ECS 字樣、compose 零 AWS 設定、端點 22 零 DELETE、
#   佇列 body 無位元組、工人不碰 DB／embedding、boto3 唯一入口、photo 表 16 欄凍結、閘門不碰 AI 開關）
#   ＋前輪停放項 3 顆（context 值非 list 不炸、崩潰重送遇 CloudRouteOff、別人的訊息撞上 store 例外），
#   read_context 型別加固（唯一產品碼改動）、三死埠實證顆數不變、README 與 CLAUDE.md 顆數更新；
#   702 → 715、端點仍 22
```

> ⚠️ **`git mv` 會直接 stage。** 這就是為什麼本 phase **不執行**它——
> 自己搬等於替產品負責人決定了那一筆 commit 裡有什麼（總覽 §7 鐵律 12）。

- [x] 清單寫進 REP／TODO，**指令沒有執行**。

---

## 5. ASCII 圖：§8 錯誤表 10 列各自在哪一層被攔下

「P78」＝ Phase 78 的測試檔、「本檔」＝ `test_design6_error_paths.py`，
測試全名見 §4.1 的對照表。

```text
 ══════════════════════════════════════════════════════════════════════════════
  HTTP 層（app 容器，同步；使用者當場看得到）  ── 本增量**一個字都沒改**
 ══════════════════════════════════════════════════════════════════════════════
   POST /photos ／ POST /camera/{token}/photos
        ├─【8】非 JPEG／PNG／PDF ──► 415  無 job、無 staging   ✓ 既有（增量五）
        └─ 落 staging → 建 job → 丟 Celery → **202**
                 │
                 │  ★【2 的另一半】遠端關掉時**仍然 202**，不准變 5xx
                 │     （design6 §0 禁止第 6 條）── ★ 本檔【補B】
                 ▼
 ══════════════════════════════════════════════════════════════════════════════
  worker 層（Celery）：run_gated_ingest_job(job_id, …)
 ══════════════════════════════════════════════════════════════════════════════
        │  status = analyzing
        │
   ★岔路①  gate.classify(檔名, content_type, load_bytes)
        ├─【1】SENSITIVE ─────────┐
        ├─【1】UNCERTAIN ─────────┤ route=local，**零 S3 呼叫**   ✓ P78 兩顆
        │                         │                              （put_calls == 0）
        │  NON_SENSITIVE          │
        ▼                         │
   ★岔路②  cloud.available()      │
        ├─【2】不是 running ──────┤ fallback reason=remote_unavailable  ✓ P78／P89
        ├─【3】探測丟例外 ────────┤ 同上                                ✓ P78／P89
        │  True                   │
        ▼                         │
        submit：PutObject context → PutObject input → SendMessage jobs
        ├─【4】任何一步丟例外 ────┤ cleanup ＋ fallback reason=submit_failed  ✓ P79
        │                         │
        ▼                         │
   ★岔路③  wait_result（長輪詢，最多 CLOUD_RESULT_TIMEOUT_SECONDS）
        ├─【5】逾時沒結果 ────────┤ cleanup ＋ fallback reason=result_timeout ✓ P80
        ├─【6】收到重送的訊息 ────┤ 冪等：列數仍 1                            ✓ P80
        │  拿到 result.json        │
        ▼                         ▼
        understood=false          run_ingest_job(job_id, …)   ← 增量五那條原路
        │                          （看圖 → 轉向量 → INSERT ＋ 原圖 ＋ 縮圖）
        │【7】fail_job ＋ cleanup S3
        │    ★ **不是** fallback 本機（總覽 §10 追認項 g）── ★ 本檔【補A】
        └─ understood=true → 本機 embed → INSERT → cleanup → finish
 ══════════════════════════════════════════════════════════════════════════════
  遠端（EC2 工人）：process_job_message
        ├─【6】result 已存在 ──► 只補 send_result ＋ 刪 jobs 訊息          ✓ P87
        ├─【6】input 不在 ─────► 只刪 jobs 訊息，什麼都不寫                ✓ P87
        └─【7】看圖 3 次都失敗 ► result.understood=false, attempts=3        ✓ P87
 ══════════════════════════════════════════════════════════════════════════════
  設定與部署（沒有執行期訊號，只能掃碼）
        ├─【9】OIDC 未鎖 sub ──► trust 的 StringEquals 逐字               ✓ P93 兩顆
        └─【10】誤開 NAT／EIP ─► 掃 app/、deploy/、workflows、compose      ★ 本檔【掃A】
                                 ＋ §4.6 的 describe-nat-gateways／addresses
```

---

## 6. 驗收清單

- [x] **§4.1 的 10 列盤點做完**，表格反映**事實**（每一顆 ✓ 都用 `--collect-only` 對過）；
      design6 §9「必釘」9 條也各自點得到名
- [x] **本檔 10 顆全綠**，而且**至少六顆做過反向驗證**（§4.2 的兩顆 ＋ §4.3 的四顆）

  ```bash
  pytest tests/integration/test_design6_error_paths.py -v
  # 預期：26 passed ＝ 90 的 4 ＋ f2fc067 的 2 ＋ 93 的 4 ＋ 94 的 6 ＋ 本 phase 的 10
  ```

- [x] **§4.3.3 的四項全部結清**，三顆新測試各自綠、各自做過反向驗證

  ```bash
  pytest tests/unit/test_cloud_worker_unit.py -q       # 預期：32 passed（31 ＋ 1）
  pytest tests/integration/test_gated_ingest.py -q     # 預期：比改之前多 1
  pytest tests/unit/test_cloud_ingest_unit.py -q       # 預期：比改之前多 1
  ```

- [x] **全量顆數 ＝ 開工基線 ＋ 14 ＝ 716 ＋ 0 skipped**（基準 **702** → 完成 **716**；計畫寫 +13／715，多的一顆是裁決 R18 ②）；
      **三死埠零依賴實證**：三個一起指、以及一次一個，顆數**全部相同**

  ```bash
  pytest -q
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

- [x] **端點 ＝ 22、DELETE ＝ 0**（本檔那顆 ＋ 既有三顆清點測試都還綠）；
      **`photo` 表 16 欄、與增量五結束時逐字相同**（【掃G】＋ §4.5 的查詢 c）；
      **`compose.yaml` 恰四個服務、零 AWS 設定**；`Dockerfile` 只有 Phase 90 那一次改動
- [x] **`boto3` 只在三個檔**（`aws_mailbox.py`／它的單元測試／`scripts/aws_check.py`）；
      **工人不 import 資料庫／Celery／Redis／向量套件**，也沒有 `"embedding"` 這個鍵
- [x] **`docs/spec/` 全增量零改動**、**`.github/workflows/test.yml` 零改動**（工作區與
      歷史兩邊都看）；**三份規格 binder 全綠、零 SKIPPED**（27 顆；規格共七份，
      有 binder 的是上傳／詢問／無線鏡頭）

  ```bash
  git status --short docs/spec/ && git diff --stat -- docs/spec/     # 兩個都預期：無輸出
  git log -1 --format='%h %s' -- docs/spec/                 # 預期：39e1c7e（增量五 Phase 72）
  git log -1 --format='%h %s' -- .github/workflows/test.yml # 預期：4269985（Phase 73）
  pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
         tests/integration/test_camera_feature.py -v
  ```

- [ ] **正式庫四個查詢全部符合預期**；`find data/staging -mmin +1440` 無輸出
- [ ] **`docker compose ps --no-trunc` ＝ 四個服務**，worker 的 COMMAND 有 `--concurrency=2`
- [ ] **沒有 running 的 EC2**、**S3 `documents/` 是空的**、**兩條佇列訊息數都是 0**；
      **沒有 NAT、沒有 EIP、SG 的 `IpPermissions` 是 `[]`、Budget 還會寄信**（§4.6 的 ②〜⑦）
- [x] **`ruff format --check app tests scripts && ruff check app tests scripts`** exit 0
- [x] **§4.3.1 只是驗證**（`grep -nE '_fail\b|_insert_photo_with_files' tests/integration/test_ingest_job_pdf.py`
      零命中；**該檔不該出現在下面的相減結果裡**）
- [x] **§4.3.2 三處 Tests 顆數已改成收工實跑值**
      （`grep -n "543 passed" README.md` ＝ 0 命中；`CLAUDE.md` 只剩三行歷史敘述——
      用 `grep -nE '(^|[^0-9])543([^0-9]|$)' README.md CLAUDE.md` 驗，**不要**直接 grep `543`，
      那會撞到十幾個資料庫埠號 `5433`）
- [x] **本 phase 只動了該動的檔**

  ```bash
  git status --short -- app tests deploy compose.yaml Dockerfile db requirements.txt .github \
    | diff "$SCRATCH/p95-before.txt" -
  ```

  預期：`diff` 只多出**五行**——
  `M app/workers/cloud_worker.py`（§4.3.3 ① 的型別加固，**本 phase 唯一的產品碼改動**）、
  `M tests/integration/test_design6_error_paths.py`、
  `M tests/unit/test_cloud_worker_unit.py`、
  `M tests/unit/test_cloud_ingest_unit.py`、
  `M tests/integration/test_gated_ingest.py`。
  （§2 開工時存的快照 `$SCRATCH/p95-before.txt` 拿來相減；`README.md`／`CLAUDE.md` 與
  兩個新文件檔在 `docs/plan/`，都不在這個範圍。）
  `app/` 底下若多出**別的** `M`，代表你改了不該改的——除非那是「揪到真缺陷、回原 phase 修」
  的結果，那就要在紀錄裡寫清楚修了什麼、並重跑全量。

- [x] **驗收包已產出**（`docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`），
      A 段的數字**全部填好**、B〜F 段**留白**（D 段另有一句「待產品負責人 push 後執行」）
- [x] **進度檔已產出**（`docs/plan/todo/<日期>-階段十七-增量六收尾95-TODO.md`），閘門三行**留白**
- [x] **沒有 commit、沒有把 `unfinish/` 搬進 `finish/`**（§4.9 只寫清單、不執行）

---

## 7. 常見陷阱

1. **以為「掃碼」是掃 QR code。**
   不是。是掃**原始碼與設定檔**。這個詞從 Phase 44 沿用下來，
   而本專案剛好又真的有一個 QR code（無線鏡頭），所以特別容易混淆。
   §4.3 那一整節沒有任何一步需要拿手機出來。

2. **在 Python 檔上掃 `lambda:` 這個關鍵字，得到一片假紅。**
   **症狀：** `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣` 紅出幾十個檔案。
   **原因：** `lambda: FakeVLM(...)` 這種匿名函式在本專案滿地都是
   （`dependency_overrides` 幾乎每一行都有）。
   **正解：** §4.3 的關鍵字**刻意分兩組**——「IAM 動作前綴」（`lambda:`／`ecs:`／`rds:`）
   只掃**設定檔**（JSON／YAML），Python 那一組改掃 `client("lambda"` 這種
   「真的會建出那個資源」的長相。**不要**把兩組合併。

3. **`test_端點仍是22支` 覺得是多餘的，想刪掉。**
   **症狀：** 「既有已經有三顆在數 22 了啊」。
   **原因與正解：** 既有那三顆是**增量五**留下來的證據。半年後有人問
   「增量六到底有沒有偷加端點」，答案要在**增量六自己的收尾檔**裡找得到，
   而不是靠「別的增量的測試還是綠的」去推論。
   這一顆刻意只數總數與 DELETE，不重抄那 22 支的清單（逐支列名由
   `test_design5_error_paths.py::test_端點恰好是這22支` 守著）——**分工，不是重複**。

4. **`test_隱私閘門不會去碰AI後端開關` 掃的是寫入，不是讀取。**
   `privacy_gate.py` **可以**讀 `config.AI_BACKEND`（2026-09-01：短問跟開關走）。
   紅燈條件是出現 `AI_BACKEND =`（賦值）或開關端點路徑。註解寫 `AI_BACKEND` 沒關係。

5. **在測試裡自己 `new` 一顆新的假件，斷言永遠成立。**
   **症狀：** `信箱.put_calls == 0` 永遠通過——**假綠**。
   **原因：** 端點／任務用的是 `dependency_overrides` 裡的**那一顆**，你手上的是另一顆。
   **正解：** 先把物件建好、`app.dependency_overrides[get_cloud_route] = lambda: 路`
   （回**同一個實例**），然後用你手上那個變數去斷言。
   **`lambda: CloudRoute(FakeMailbox(), ...)` 這種「每次 new 一顆新的」寫法，
   計數器永遠是 0。**

6. **【補A】的 monkeypatch 只蓋一個模組，於是測試假綠。**
   **症狀：** `本機路被呼叫 == []` 永遠通過，就算實作真的去跑了 `run_ingest_job`。
   **原因：** `gated_ingest.py` 若寫的是 `from app.services.ingest_job import run_ingest_job`，
   那個名字就綁在 `gated_ingest` 這個模組上——只蓋 `ingest_job.run_ingest_job` 蓋不到。
   **正解：** §4.2 的寫法**兩個模組都蓋**（用 `hasattr` 判斷第二個存不存在），
   所以不管實作用哪種 import 風格都攔得到。
   驗證方法：反向驗證時把斷言改成 `!= []`，它必須紅。

7. **只跑新檔就收工。**
   一定要跑全量，而且要跑**三死埠**那幾輪。本 phase 動到的是 conftest 級別的東西
   （兩顆行為測試依賴第五道安全網 `wire_fake_cloud`），只跑一個檔看不出有沒有波及別人。

8. **看到「26 passed」就以為 §0／§1.2／§3 全部守住了。**
   §4.6 那七項是**人工**的（EC2 狀態、S3 空不空、佇列殘訊息、NAT／EIP、SG inbound、Budget），
   測試跑再多次也不會幫你做。尤其 **有沒有 running 的 EC2**——
   忘了 Terminate 就是在扣卡，而且 pytest 永遠不會告訴你。

9. **`docs/spec/` 被「順手」改了一個字。**
   **症狀：** `git status --short docs/spec/` 有輸出。
   **原因：** 最常見的是編輯器自動加了行尾空白或換行。
   **正解：** `git checkout -- docs/spec/` 還原。design6 §10 明文本增量**不必**改 Gherkin；
   要改需要產品負責人**另外核准**（前三次解禁都有留檔頭紀錄，這一輪沒有）。

10. **自己把 `unfinish/` 搬進 `finish/`。**
    **症狀：** 產品負責人下次 `git status` 看到一堆 `R`（rename）已經被 stage 了。
    **原因：** `git mv` 會**直接 stage**。
    **正解：** §4.9 只**寫下清單**、不執行。歸檔隨 commit 執行，時機由產品負責人決定
    （總覽 §7 鐵律 12）。⚠ 而且 `unfinish/` 現在**只剩 4 份**（總覽 ＋ 93／94／95）——
    74〜92 產品負責人自己搬完了（83〜92 那 10 份的搬移還沒 commit），**不要動它們**。

11. **`aws budgets`／`describe-nat-gateways`／`describe-security-groups` 回 `AccessDenied`。**
    **症狀：** §4.6 的 ⑤⑥⑦ 或驗收包 E2〜E4 不是「空」而是紅字 AccessDenied。
    **原因：** `set -a; . ./.env; set +a` 把 `.env` 裡 **personaldocai-mac** 的那兩把 key 放進了
    環境變數，而環境變數會**蓋過** `~/.aws` 的 default profile（personaldocai-admin）。
    mac 這個身分只有 S3 該 prefix／兩條佇列／`ec2:DescribeInstances`，其他一律拒絕。
    **正解：** 載完 `.env` 立刻 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`，
    再用 `aws sts get-caller-identity --query Arn --output text` 確認結尾是 `user/personaldocai-admin`
    （§2、§4.6、驗收包「準備」三處都寫了）。Budget 那兩條另外還要 root 開過
    「IAM user and role access to billing information」（Phase 82 §4.3 最後一步）。

12. **【掃B】自己寫 regex 抓服務名，永遠紅在「6 個而不是 4 個」。**
    **症狀：** `compose 的服務必須恰好是這四個：['db', 'redis', 'app', 'worker', 'pgdata', 'redisdata']`。
    **原因：** 對**整份** `compose.yaml` 跑 `^  ([a-z][\w-]*):$`，檔尾 `volumes:` 底下的
    `pgdata:`／`redisdata:` 同樣是兩格縮排、同樣以冒號結尾，會一起被抓進來（Phase 90 實測）。
    **正解：** 沿用 Phase 90 放在同一個檔裡的 `compose_services()`——它先把 `services:` 區塊切出來
    再抓。§4.3 的【掃B】就是這樣寫的；**不要**自己再寫一份。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 多了什麼 |
|---|---|
| repo | `tests/integration/test_design6_error_paths.py` +10 顆（該檔共 **26** 顆）；§4.3.3 的三顆分別落在 `tests/unit/test_cloud_worker_unit.py`（+1，該檔 32）、`tests/integration/test_gated_ingest.py`（+1）、`tests/unit/test_cloud_ingest_unit.py`（+1）；`README.md` 兩處 ＋ `CLAUDE.md` 一處的 Tests 顆數改成實跑值；`docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`（新）；`docs/plan/todo/<日期>-階段十七-增量六收尾95-TODO.md`（新） |
| 產品程式碼 | **只有一處**：`app/workers/cloud_worker.read_context` 的型別加固（§4.3.3 ①，前輪 review 停放項）。其餘零改動——除非盤點時揪到真缺陷，那要回原 phase 修並寫進紀錄 |

**對外行為變了沒：完全沒有。** 端點仍 **22**、openapi 仍**零 DELETE**、
`POST /photos` 仍 **202** 且回應三鍵、前端零改動、`compose.yaml` 零改動、
正式庫零改動、`docs/spec/` 零改動。
（`read_context` 那一處也不改對外行為：它只是把「值的型別不對」從**炸掉**改成**當空清單**，
而那正是它 docstring 一直寫著的契約。）

**顆數：**

| | 顆數 |
|---|---|
| 增量六開工（Phase 74 之前） | **543** ＋ 0 skipped |
| Phase 92 之後（2026-09-03 controller 實查） | **692** ＋ 0 skipped |
| 開工基線（Phase 94 之後） | **702**（＝ 692 ＋ 93 的 4 ＋ 94 的 6） |
| 本 phase 新增 | **+13** ＝ 2 顆補缺 ＋ 8 顆掃碼 ＋ **§4.3.3 的 3 顆** |
| 完成後 | **715** ＋ 0 skipped |

> ⚠️ **與總覽 §2.7／§9 的差額要在 REP 寫清楚**（總覽 §10.2 追認項 A 的規矩：
> 「真的必須多加一顆時可以加，但要在該 phase §8 明寫『比總覽多 N 顆』」）：
>
> - 總覽 §2.7／§9 的 Phase 95 那一列寫的是 **+10、累計 682**。
> - 本 phase 實際 **+13**（多 3 顆＝§4.3.3 的停放項：`read_context` 型別、
>   崩潰重送遇 `CloudRouteOff`、別人的訊息撞上 `store.get` 例外），累計 **715**。
> - 累計值的差（682 vs 715）**不是本 phase 造成的**：74〜92 每一輪 review 都補過顆數
>   （§9 那張表自己也標了好幾個「實 +N」），到 92 為止實查就是 692 而不是 662。

**下一步（不是 phase，是人的事）：**

1. 把驗收包交給產品負責人，等他說「**增量六沒問題**」。
2. 他若對「要你追認的裁決」那 45 條（總覽 §10 的 33 條 ＋ 本輪校準的 R0〜R11）
   有任何一條不同意 → 回那一條寫的 phase 改，然後重跑全量與相關的 Demo。
3. **Demo 3 要等他自己 `git push`**（見驗收包 D 段與 phase-94 §4.8）。
4. 他指示 commit 之後：commit ＋ 執行 §4.9 的歸檔指令 ＋ 更新 `CLAUDE.md` 的「專案概述」
   現況段（比照增量五的做法，在最後面追加一整段增量六成果）。
5. 寫 REP（`docs/plan/report/<日期>-增量六收尾95-REP.md`，檔名比照 `2026-08-26-增量五收尾71-72-REP.md`）。

**做完之後（產品負責人指示歸檔並 commit 之後），`docs/plan/unfinish/` 應該是空的。**

---

## §9 2026-09-03 校準紀錄

> 這一節是給**實作者與 reviewer** 看的 diff 摘要：本檔在 2026-09-03 被校準過一輪，
> 下面是「改了什麼、為什麼」。校準的依據是 `.superpowers/sdd/phase0903-1/brief-common.md`
> 與 `calib-brief.md`（controller 裁決 R0〜R11），以及**對實檔的逐項實查**。

### A. 事實對齊（舊值 → 現況）

| # | 位置 | 舊 | 新 | 為什麼 |
|---|---|---|---|---|
| 1 | 檔頭、§2、§4.4、§6、§8 | 開工基線 **672**、收工 **682** | 開工 **702**、收工 **715** | 2026-09-03 實查全量 **692**（Phase 92 之後）；74〜92 每一輪 review 都補過顆數，總覽 §9 的絕對值是 2026-08-31 的估計。93 +4 → 696、94 +6 → 702、95 +13 → 715 |
| 2 | §2、§4.3 尾、§6、§8 | 收尾檔 **14／24** 顆 | **16／26** 顆 | 產品負責人在 commit `f2fc067` 補了 2 顆（`test_unit檔與user_data內嵌段逐字相同`、`test_unit只在local才等本機Ollama`） |
| 3 | §2 | 「★G1／G2／G3 都已通過」沒有憑據 | 補上 G3 的三項憑據並註明「本次：已通過」 | 裁決 R2 |
| 4 | §2、§6 | 快照寫 `/tmp/p95-before.txt` | `$SCRATCH/p95-before.txt`（§2 開頭定義 `SCRATCH`） | 與 phase-93 §4.1 同一條規矩：`/tmp` 是全機共用的，沒有人會去清 |
| 5 | §2、§4.4、§6 | `git log -- docs/spec/` 預期「Phase 72 那一筆」 | 補上實際 hash **`39e1c7e`** | 實查；有 hash 才驗得動 |
| 6 | §4.3.1 | 「把兩句舊名 docstring 改掉」（一整節的動作） | **改成一句 `grep` 驗證，不改檔** | 實跑 `grep -nE '_fail\b\|_insert_photo_with_files' tests/integration/test_ingest_job_pdf.py` **無輸出**——2026-09-01 的 fix wave 早就改完了（總覽 §2.7 也已劃掉這一項）。裁決 R8 |
| 7 | §4.3.2 | README 兩處 543 → 682 | README 兩處 ＋ **`CLAUDE.md` 第 461 行**改成收工實跑值；並明列**不准動**的三行歷史敘述 | 校準者 A 的跨檔回報；另補「驗證用的 grep 一定要排除 `5433`」（`CLAUDE.md` 裡有十幾個資料庫埠號） |
| 8 | §4.9、§7 陷阱 10、§8 | 「23 份要歸檔」「只剩 phase-73」 | **只剩 4 份**（總覽＋93／94／95）；`phase-73`〜`92` 都已在 `finish/`（83〜92 的搬移尚未 commit） | 實查 `git ls-files`／`git status`。裁決 R8 |
| 9 | 驗收包 B1／B5／C3／C8 | 「檔名明確敏感的圖」「檔名 `IMG_4821.jpg`」 | 改成**內容**敏感／不敏感，並加註「閘門不看檔名」 | 2026-09-01 產品負責人改判（總覽 §10.1 f）：閘門是 VLM 看圖的短問，`del filename`。照舊寫法做 Demo 會得到與預期相反的結果 |
| 10 | 驗收包「要你追認的裁決」 | 23 條（a〜l ＋ A〜K） | **33 條**（總覽 §10.1 的 a〜l ＋ §10.2 的 A〜**U**）＋ 本輪 **R0〜R11** 共 12 條 | 總覽 §10.2 已經長到 U；追認項 **f** 的內容同時修正（「只看檔名」→「不看檔名」），**J** 拿掉過期的終值 682 |
| 11 | 驗收包 D 段 | 六格照做 | 加一段「⏳ 要等你自己 `git push` 之後才做得了」，並說明本輪就位的是什麼 | 裁決 R0：實作者全程不 commit／不 push；`deploy.yml` 必須先在 `main` 上才會被觸發 |
| 12 | §4.5／§4.6 | 沒寫誰做 | 明寫「**由 controller 親自執行**」 | 裁決 R3：AWS／docker／正式庫一律 controller 親做 |
| 13 | §4.8 | 檔名 `<日期>-增量六收尾95-TODO.md` | `2026-09-03-階段十七-增量六收尾95-TODO.md`，並說明本輪 TODO 從「階段十四」起算 | 與同批的其他四份對齊 |

### B. 識別字英文化（裁決 R1；`test_中文` 測試名保留）

| 舊（中文） | 新（英文） | 在哪一段 |
|---|---|---|
| `讓工人在本機等結果之前先做完(...)` | **`class WorkerMailbox(FakeMailbox)`** | §4.2【補A】——**順便改對了寫法**，見下面 C-1 |
| `看不懂` | `NOT_UNDERSTOOD` | §4.2【補A】 |
| `本機路被呼叫`／`記下本機路` | `local_route_calls`／`record_local_route` | §4.2【補A】 |
| `信箱`／`工人vlm`／`路` | `mailbox`／`worker_vlm`／`route` | §4.2 兩顆、§4.3【掃D】 |
| `看得懂` | `MENU_UNDERSTANDING` | §4.2【補B】 |
| `不擲出例外的client` | `client_without_server_exceptions` | §4.2【補B】 |
| `設定檔禁字`／`產品碼禁字` | `CONFIG_FORBIDDEN`／`CODE_FORBIDDEN` | §4.3【掃A】 |
| `違規`／`檔案`／`原始碼`／`命中`／`設定檔`／`樣式` | `violations`／`path`／`source`／`hits`／`config_files`／`pattern` | §4.3【掃A】 |
| `AWS的設定變數`／`原文`／`變數`／`名稱` | `AWS_SETTING_NAMES`／`source`／`name`／`keyword` | §4.3【掃B】 |
| `運算元` | `operations` | §4.3【掃C】 |
| `只記帳的S3`／`只記帳的SQS` | `RecordingS3`／`RecordingSqs` | §4.3【掃D】 |
| `呼叫`／`解析`／`疑似位元組` | `call`／`payload`／`marker` | §4.3【掃D】 |
| `工人不可以引入的頂層模組`／`來源`／`樹`／`匯入`／`節點`／`別名`／`名稱`／`字串常數`／`向量相關的名字` | 【掃E】整段重寫（見 C-2）：`WORKER_SOURCE`／`FORBIDDEN_WORKER_NAMES`／`FORBIDDEN_WORKER_STRINGS`／`source`／`tree`／`names`／`constants`／`dynamic_imports`／`imported` | §4.3【掃E】 |
| `BOTO3引入`／`可以引入boto3的檔案`／`樹根`／`相對路徑`／`入口檔` | `BOTO3_IMPORT`／`BOTO3_ALLOWED_FILES`／`tree_root`／`relative_path`／`entry_point` | §4.3【掃F】 |
| `增量五結束時的photo欄位`／`欄位` | `PHOTO_COLUMNS`／`columns` | §4.3【掃G】 |
| `檔名`／`原始碼` | `filename`／`source` | §4.3【掃H】 |

**保留中文的只有兩個**：`from tests.conftest import 目前的任務清單, 跑完任務`——那是 conftest
既有的共用 fixture／helper（增量五就有，幾十顆測試在用），改名要動一大票既有檔案。

> 📌 每一個碼區都用 `python tokenize` 掃過非 ASCII 的 `NAME` token，
> 結果只剩 `test_` 開頭的測試名與上面那兩個 conftest helper。

### C. 依實檔修正的做法（不只是改名）

1. **【補A】的假工人改用 `WorkerMailbox(FakeMailbox)` 子類，不再 monkeypatch
   `CloudRoute.wait_result`。** 舊版的 helper docstring 寫「與 Phase 87
   `test_cloud_roundtrip.py` 的同名 helper **逐字相同**」——實查發現**不是**：
   那個檔用的是 `WorkerMailbox` 子類，而且它的模組 docstring 花了一整段解釋
   **為什麼刻意不 monkeypatch 產品碼的方法**（「那會把產品碼的方法換掉，讀測試的人得先確認
   換掉之後還有沒有在測原本那支」）。`test_gated_ingest.py` 也是同一個寫法。
   照舊版寫會憑空多一個與全庫慣例相反的作法，所以改成子類。
2. **【掃E】整段重寫成與 Phase 87 互補**（裁決 R10）。Phase 87 的
   `test_工人不import資料庫與Celery與Redis` 已經用 ast 掃 import 名單（黑名單＋白名單＋
   禁相對 import，三層），舊版【掃E】把那一半又抄了一次。現在本顆只掃 87 掃不到的三件事：
   **識別字**、**字串常數**、**動態載入**（`importlib`／`__import__`），
   另加兩個窄的 import 定錨（`app.services.indexing_service`／`app.dependencies`）讓名字名副其實。
   ⚠ **裁決 R10 原本寫的「掃工人檔全文（含註解）不得出現 `photo_repository`／`embed`」做不到**：
   工人自己的模組 docstring 就寫著「⛔ 不寫 Postgres、不碰 `photo_repository`」與
   「⛔ 不算 embedding」——那是**正確的文件**，掃全文會把它掃成違規
   （實跑確認：`photo_repository` 命中第 18／84 行、`embed` 命中第 19／171 行）。
   所以字串比對一律走「**整個字串常數相等**」。改法與結果都已寫進碼區的註解。
3. **【掃A】的關鍵字加了詞邊界。** 舊版是 `NatGateway|nat-gateway|…|(?<![\w-])(?:lambda|ecs|rds):`，
   實跑對現況全部輸入是零命中；但為了防止後人把它放寬成裸字，改成
   `(?<![A-Za-z])(?:nat[ _-]?gateway|elastic[ _-]?ip|…)(?![A-Za-z])` 並在註解裡寫死兩個假紅陷阱：
   **裸的 `nat` 會命中 Termi·NAT·e**（`deploy.yml` 有這個字）、
   **裸的 `ecs` 會命中 Ex·ecS·tartPre**（`deploy/ec2/` 四個檔在用）。
   順手補了 `elastic ip`／`elbv2`／`elasticache`，**刻意不掃裸的 `alb`**（太短、只會埋假紅；
   真的開 ALB 一定會留下 `elasticloadbalancing` 或 `elbv2`）。
4. **【掃B】的分工說明改成事實。** Phase 90 那顆已經在掃 `AWS_`／`S3_BUCKET`／`SQS_`／
   `CLOUD_ROUTE` 四個**前綴**了（2026-09-02 校準裁決 R10 加的第 ④ 條），所以本顆的分工
   改寫成「九個變數名**逐字**都不在 ＋ 工人的服務名不在」——前綴掃不到 `cloud_worker`。
5. **【掃C】【掃E】的分工在對照表與 docstring 都寫明**，避免被當成重複測試砍掉。
6. **反向驗證表的第 4 列改了做法**：舊版叫人「在 `cloud_worker.py` 加 `import redis`」——
   那驗的是 Phase 87 那顆，不是本顆。改成「在 `build_image_result()` 的 dict 加一個
   `"embedding": None` 鍵」，才真的會紅在【掃E】。
7. **檔頭 import 從「整批換掉」改成「補上去」。** 現況檔頭是 `re`／`Path`／`yaml` ＋
   `PROJECT_ROOT` ＋ 九個**英文** helper（`read_dockerfile()`／`read_compose()`／
   `compose_config()`／`compose_services()`／`stage_names()`／`stage_body()`／
   `_unit_file_text()`／`_user_data_embedded_unit()`／`read_compose_dev()`）——
   舊版計畫寫的 `專案根目錄`／`dockerfile原始碼()` 那一套**從來沒有存在過**。
   同理模組 docstring 也已經寫好了（含那張「誰在什麼時候寫這個檔」的表），不要重寫。

### D. 新增 §4.3.3「前輪 review 停放項」（裁決 R9；+3 顆）

| 項 | 實檔判讀 | 做法 |
|---|---|---|
| ① `read_context` | `app/workers/cloud_worker.py` L151〜155 現在是 `list(payload.get("folders") or [])`。**dict 已經擋過了**（L140 的 `isinstance`），但**值**沒擋：`{"folders": 5}` → `TypeError`（毒訊息）、`{"entities": "abc"}` → `["a","b","c"]`（安靜的假資料） | 新增私有 helper `_only_list()` ＋ 一行 `dropped` warning；先寫紅測試 `test_context值不是list時當空清單不炸`（三種型別各走一遍）。**本 phase 唯一的產品碼改動** |
| ② `from_lines` | **存在**（`test_design6_error_paths.py` L153 `re.findall(r"^FROM\b", source, re.M)`），而同檔的 `stage_names()` 用 `re.M \| re.I` | 加 `\| re.I`；無新測試 |
| ③ docstring | `tests/unit/test_cloud_worker_unit.py` L5「所以這 **10 顆**跑起來是毫秒等級」，實查 **31 顆** | 改成不寫死數字；純註解 |
| ④a `CloudRouteOff` 重送 | `gated_ingest._resume_cloud_route`（`fetch_result` 包 try）＋ `_best_effort_cloud_cleanup`（`cleanup` 包 try）**都已經實作了**，兩支 docstring 也都寫明「cloud 有可能已經是 CloudRouteOff」，但**零測試** | 新測試 `test_崩潰重送時雲端路已經關掉_照樣fallback本機`（放 `test_gated_ingest.py`，體例照隔壁那顆）。斷言：`gate.calls == 0`、照片入庫 1 列、`route` 變 `local`、log 有 `fallback=local reason=redelivered_without_result`，**再加一條防假綠**——log 必須有「崩潰重送時讀不到雲端結果」（證明 `RuntimeError` 真的發生過） |
| ④b `store.get` 丟例外 | `CloudRoute._handle_foreign_message` 第一行就是 `store.get(...)`，`wait_result` **沒有** try → 例外往外丟 → `gated_ingest` 的 R14 try 收成 `result_timeout` | 新測試 `test_處理別人的訊息時store掛掉_例外往外丟`（放 `test_cloud_ingest_unit.py`）。**只釘現況**（收尾不改行為），順帶釘「別人的訊息沒被刪也沒被還回去、別人的 S3 物件沒被動」 |

> 計畫檔提到的 `_繼續雲端路`／`_處理別人的訊息` 是**舊中文名**，實檔是
> `_resume_cloud_route`／`_handle_foreign_message`——本節一律用實檔的名字。

### E. 外部事實複查（裁決 R11；2026-09-03 以 WebFetch 讀官方頁）

| 事實 | 計畫原本寫的 | 查到的 | 結論 |
|---|---|---|---|
| SQS 單則訊息上限 | 1 MiB（256 KB 是舊值） | 「The minimum message size is 1 byte (1 character). The maximum is **1,048,576 bytes (1 MiB)**」 | **相同**；來源換成更權威的 quotas 頁 |
| `PurgeQueue` 60 秒限制 | 60 秒只能做一次 | 「The message deletion process takes up to **60 seconds**… `PurgeQueueInProgress`：previously received a PurgeQueue request within the last 60 seconds」 | **相同** |
| `describe-nat-gateways` 的旗標 | `--filter`（單數，這支指令的怪癖） | AWS CLI 參考頁的 Options 就是 `--filter (list)` | **相同** |
| `information_schema.columns` | 用它查 `photo` 的欄位 | PostgreSQL 17 文件確認有 `table_name`／`column_name` | **相同** |

### F. 實跑證據（校準時做的唯讀檢查）

```text
pytest tests/integration/test_design6_error_paths.py --collect-only -q  -> 6 tests
pytest tests/unit/test_cloud_worker_unit.py         --collect-only -q  -> 31 tests
grep -nE '_fail\b|_insert_photo_with_files' tests/integration/test_ingest_job_pdf.py -> 無輸出
【掃A】兩組樣式對 16 份輸入實跑（deploy/aws 四份、deploy/ec2 三份、compose 兩份、
       test.yml、phase-94 §4.3 的 deploy.yml、phase-93 §4.3／§4.4 五個 json 區塊）-> 零命中
       （其中 deploy.yml 含 "Terminate"、deploy/ec2 三檔含 "ExecStartPre"，都沒有被誤中）
【掃A】CODE_FORBIDDEN 對 app/ 全樹 49 個 .py 實跑 -> 零命中
【掃E】三組斷言對 app/workers/cloud_worker.py 實跑 -> 零命中（不會首跑假紅）
db/schema.sql 的 photo 表逐欄清點 -> 恰 16 欄，與【掃G】的 PHOTO_COLUMNS 逐字相同
```

### G. 已知的跨檔問題（**本輪不動，留給 controller**）

1. **總覽 §2.7 的 Phase 95 段**：測試名第 8 顆已經是「不會去**碰**」（本檔已對齊）；
   但那一段的「+10 顆（累計 **682**）」與 §9 那張表的 92〜95 列都要跟著改成 692／696／702／715，
   而且要註明 §4.3.3 多的 3 顆（追認項 A 的規矩）。
2. **總覽 §9** 的 92 那一列還寫著「662」（沒有「實 672」），與 89／90 兩列的體例不一致。
3. **`LAUNCH.md` 第 225 行** `pytest -q  # expect 543 passed` 也過期（本檔 §4.3.2 已把它列成「另外發現」）。
4. **`CLAUDE.md` 的「專案概述」現況段**要在 commit 之後補一整段增量六成果（本檔 §8 第 4 點已寫）。

---

## 附：本文件引用的官方文件

- [PostgreSQL `information_schema.columns`](https://www.postgresql.org/docs/17/infoschema-columns.html)
  ——【掃G】用它證明 `photo` 表一欄都沒加
- [Python `ast` 模組](https://docs.python.org/3/library/ast.html)
  ——【掃E】與 §4.3.3 ① 用它讀工人的語法樹（比 `grep` 準：註解與 docstring 不會誤判）
- [pytest `--collect-only`](https://docs.pytest.org/en/stable/how-to/usage.html)
  ——§4.1 盤點時用來確認「那顆測試真的存在」
- [Amazon SQS 訊息配額（單則上限 **1,048,576 bytes ＝ 1 MiB**）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)
  ——【掃D】的理由（2026-09-03 複查：官方頁逐字寫 "The maximum is 1,048,576 bytes (1 MiB)"；
  design6 §1.2 寫的 256 KB 是舊值，結論不變）
- [SQS `PurgeQueue`（60 秒只能做一次）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
  ——2026-09-03 複查：`PurgeQueueInProgress` 的說明逐字寫「within the last 60 seconds」
- [AWS CLI `s3api list-objects-v2`](https://docs.aws.amazon.com/cli/latest/reference/s3api/list-objects-v2.html)
- [AWS CLI `sqs get-queue-attributes`](https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-attributes.html)
- [AWS CLI `ec2 describe-nat-gateways`](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-nat-gateways.html)
  ——2026-09-03 複查：Options 欄逐字是 `--filter (list)`（**單數**，不是 `--filters`）
- [AWS CLI `ec2 describe-addresses`（Elastic IP）](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-addresses.html)
- [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
- [EC2 Stop 與 Terminate 的差別](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)

---

## §10 實作紀錄（2026-09-03，Opus 實作者）

### A. 做了什麼

| 步驟 | 結果 |
|---|---|
| §4.1 盤點 | `pytest --collect-only -q` 開工 **702 tests**；表上 **20 個 ✓ 測試名逐一 `grep` 對過，全部點得到**（每個恰 1 筆）。沒有任何一顆要「回原 phase 補」 |
| §4.2【補A】【補B】 | **首跑就綠**（釘的是 74〜94 已經做出來的行為）＝**零真缺陷**。兩顆各做一次反向變異、親眼看紅、改回 |
| §4.3【掃A】〜【掃H】 | 8 顆**首跑全綠**。反向變異做了 **8 次**（計畫只要求 4 次），全部看到紅 |
| §4.3.1 | `grep -nE '_fail\b\|_insert_photo_with_files' tests/integration/test_ingest_job_pdf.py` → **無輸出**（exit 1）。該檔零改動 |
| §4.3.2 | `README.md` 兩處 ＋ `CLAUDE.md` 第 471 行（CI 段）＋ `LAUNCH.md` 第 225 行的 `543` → **716**。收工後 `README.md`／`LAUNCH.md` 零命中，`CLAUDE.md` 只剩 L11／L13／L483 三行歷史敘述 |
| §4.3.3 ① | **TDD 走完紅→綠**：紅的那次是 `TypeError: 'int' object is not iterable`（`app/workers/cloud_worker.py:152`）。加 `_only_list()` ＋ `dropped` warning 之後綠。**本 phase 唯一的產品碼改動** |
| §4.3.3 ② | `from_lines` 補 `re.M \| re.I`。順手驗過它真的有牙：在 Dockerfile 尾巴加一個小寫無名 stage `from base`，**有 `re.I` 會紅、拿掉 `re.I` 會假綠** |
| §4.3.3 ③ | `test_cloud_worker_unit.py` 檔頭「這 10 顆」→「**本檔**跑起來是毫秒等級」（純 docstring） |
| §4.3.3 ④a／④b | 兩顆**首跑就綠**（釘現況），各做一次反向變異看紅 |
| R18 四項 | ①③④ 改既有 93 那兩顆的斷言（顆數不變）、② 新增 1 顆。四項各做一次反向變異看紅 |
| §4.4 | 全量 **716 passed ＋ 0 skipped**；三死埠一起指 **716**；三個死埠各單指一次也都 **716**；三份 binder **27 顆全綠零 SKIPPED**；`docs/spec/` 工作區與歷史都零改動（`39e1c7e`）、`test.yml` 仍是 `4269985`；`ruff format --check` ＋ `ruff check` exit 0 |
| §4.5／§4.6 | **controller 親做**（裁決 R3），dry run 全過。數字已抄進驗收包 A 段 |
| §4.7 | `docs/plan/report/2026-09-03-增量六驗收包-請產品負責人確認.md`（A 段填實跑值、B〜F 段留白、D 段標「⏳ 待你 push 後執行」） |
| §4.8 | `docs/plan/todo/2026-09-03-階段十七-增量六收尾95-TODO.md`（controller 已建）**併入**進度總表與閘門紀錄（三行留白）、勾完做完的步驟 |
| §4.9 | 歸檔清單寫進驗收包與 TODO，**指令沒有執行**；零 git 操作 |

### B. 改了哪些檔（逐檔一行）

| 檔案 | 改了什麼 |
|---|---|
| `tests/integration/test_design6_error_paths.py` | +11 顆（2 補缺 ＋ 8 掃碼 ＋ 1 顆 R18 ②）、檔頭 import 補齊、模組 docstring 尾補一句「不連真 AWS／Redis／Celery／Ollama」、`from_lines` 補 `re.I`、93 那兩顆的三處斷言強化（R18 ①③④）。**16 → 27 顆** |
| `tests/unit/test_cloud_worker_unit.py` | +1 顆 `test_context值不是list時當空清單不炸`；檔頭 docstring 拿掉寫死的「10 顆」。**31 → 32 顆** |
| `tests/integration/test_gated_ingest.py` | +1 顆 `test_崩潰重送時雲端路已經關掉_照樣fallback本機`。**21 → 22 顆** |
| `tests/unit/test_cloud_ingest_unit.py` | +1 顆 `test_處理別人的訊息時store掛掉_例外往外丟`（含 `ExplodingStore`）。**28 → 29 顆** |
| `app/workers/cloud_worker.py` | **唯一的產品碼改動**：新增私有 helper `_only_list()`、`read_context` 的 return 段改用它並多一行 `dropped` warning |
| `README.md`／`CLAUDE.md`／`LAUNCH.md` | 各改一行測試顆數（`543` → `716`；`README.md` 兩行） |
| `docs/plan/report/2026-09-03-增量六驗收包-請產品負責人確認.md` | 新增 |
| `docs/plan/todo/2026-09-03-階段十七-增量六收尾95-TODO.md` | 補進度總表／閘門紀錄／歸檔清單、勾步驟 |

`git status --short -- app tests deploy compose.yaml Dockerfile db requirements.txt .github` 相對開工只多**四行**
（`app/workers/cloud_worker.py`、`tests/unit/test_cloud_worker_unit.py`、`tests/unit/test_cloud_ingest_unit.py`、
`tests/integration/test_gated_ingest.py`）——`test_design6_error_paths.py` 的 `M` 與三個 `??`（`deploy.yml`、
兩份 `deploy/aws/*.json`）在開工時就已經存在（Phase 93／94 留下的，尚未 commit）。
`compose.yaml`／`Dockerfile`／`deploy/` 全部零改動（反向變異用過的那幾個檔都以 `git diff` 或 `shasum -c` 驗過還原乾淨）。

### C. 與計畫的差異（逐條）

1. **顆數 +14 不是 +13，累計 716 不是 715。** 多的一顆是 controller 追加的裁決 R18 ②
   `test_部署policy恰五段而且SendCommand綁實例與document`（Phase 93 review 的 deferred minor，
   本 phase 順手結清）。`test_design6_error_paths.py` 因此是 **27 顆**，不是計畫寫的 26。
   §2、§4.4、§6、§8 的 715／26 都以此為準；驗收包與 TODO 已寫明差額。
2. **R18 的另外三項是「改既有 93 測試的斷言」**（顆數不變）：`test_部署用的policy裡沒有寫死帳號ID`
   補 `<INSTANCE_ID>` 佔位斷言、迴圈內的裸 `json.loads(source)` 改成 `try/except JSONDecodeError` ＋
   `pytest.fail(f"{path.name} 不是合法 JSON：{exc}")`、`test_OIDC信任文件的aud是sts` 的 `aud` 斷言補失敗訊息。
   新測試依 dispatch 放在**檔尾本 phase 的區塊**（不插在 93／94 兩區之間——檔頭那張「誰在哪個 phase 加了什麼」
   的表是時間軸，插中間會對不上）。
3. **§4.3.2 多改一處**：計畫把 `LAUNCH.md` 第 225 行的 `expect 543 passed` 列成「另外發現、不強制做」。
   本輪一起改了（純文件、零風險），所以是四處不是三處。
4. **§6 的 `git diff --stat README.md CLAUDE.md` 預期「各 2 行」對不上**：那兩個檔在開工時**已經是 `M`**
   （Phase 93 加了 CLAUDE.md 的「部署角色」段、Phase 94 加了 README 的 CI/CD 小段，都還沒 commit），
   所以 `--stat` 會把它們的改動一起算進去。本輪自己只動了 `README.md` 兩行、`CLAUDE.md` 一行、`LAUNCH.md` 一行。
5. **`ruff check --fix` 會先把還沒被用到的 import 刪掉**（`ast`／`get_connection`／`AwsMailbox` 在只貼完
   §4.2 兩顆時是未使用的）。實作順序因此是「貼完 §4.3 的掃碼 → 再把那三行 import 補回去 → `ruff check --fix`」。
   計畫 §4.2 ① 的 import 清單本身沒有錯，只是要等 §4.3 貼完才會全部有人用。
6. **反向變異做了 12 次，不是計畫寫的 6 次**：§4.2 兩顆、§4.3 八顆各一次（計畫只要求四顆）、
   §4.3.3 ②（`re.I` 的正反兩面）、④a、④b，再加 R18 四項。全部親眼看紅、看完還原。
7. **design6 §9「必釘」9 條的關鍵字有三個點不到名**：`敏感中文關鍵字`／`空檔名`／`亂碼檔名`
   ——那三條是 2026-09-01 改判前 `RuleGate`（看檔名）時代的測試名。改判之後閘門**不看檔名**，
   對應的把關換成 `tests/unit/test_privacy_gate_unit.py::test_檔名完全不影響判斷`
   （同檔另有 22 顆閘門測試）。**不是缺口，是那三個名字隨規格改判一起作廢了。**
   其餘 6 條（`零submit`／`遠端關閉`／`探測丟例外`／`雲端結果`／`送兩次`／`body`）全部點得到名。
8. **`docker compose ps` 跑過一次**（只為了確認 db 是 `Up (healthy)`，實作者規則要求開工前確認）。
   除此之外零 `docker`／零 `aws`／零 `gh`／零 git 寫入操作。

### D. 顆數的組成（716）

```text
702  開工基線（Phase 94 之後）
+ 2  §4.2 兩顆真缺口     （雲端看不懂＝整筆失敗、遠端關掉仍 202）
+ 8  §4.3 八顆掃碼       （NAT/EIP/Lambda/ECS、compose 零 AWS、端點 22 零 DELETE、佇列 body、
                          工人不碰 DB/embedding、boto3 唯一入口、photo 16 欄、閘門不碰 AI 開關）
+ 3  §4.3.3 停放項       （read_context 值非 list ＋ 崩潰重送遇 CloudRouteOff ＋ 別人的訊息撞 store 例外）
+ 1  裁決 R18 ②         （部署 policy 恰五段、SendCommand 綁實例＋document）
———
716  收工（0 skipped；warning 只有環境層的 StarletteDeprecationWarning）
```

### E. 疑慮

- **無。** 兩顆補缺與八顆掃碼首跑全綠 ＝ 74〜94 沒有留下真缺陷；
  唯一改到的產品碼（`read_context`）是前輪 review 明確停放的項目，走的是先紅後綠的 TDD。
- 待 controller 收工再跑一次 §4.5／§4.6，並在產品負責人 push 之後補做驗收包 D 段（Demo 3）。
