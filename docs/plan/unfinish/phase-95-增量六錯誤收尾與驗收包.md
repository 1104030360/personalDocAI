# Phase 95：增量六錯誤收尾與驗收包

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別不要做的四件事：
> ① **不要**為了讓某顆測試變綠而改產品行為（這是**收尾**，不是重寫——首跑紅了＝揪到真缺陷，
> 回**對應的 phase** 修產品碼，然後重跑全量）；
> ② **不要**重複測已經有人測的東西（每一列先找「誰已經測了」，只補真正的缺口；
> 重複的測試是負債：改一次程式要改兩個地方，而且兩個地方遲早會不一致）；
> ③ **不要**動 `docs/spec/` 任何一個字（design6 §10 明文：本增量**不必**為了 fallback 改 Gherkin）；
> ④ **不要**自己 commit、不要自己把 `unfinish/` 搬進 `finish/`（歸檔隨 commit 執行，時機由產品負責人決定）。

> 🎯 **一句話目標：** 把 design6.md §8 錯誤表的 **10 列**逐列**清點到有測試把關**
>（74〜94 全程 TDD，大多數列已由各自的 phase 釘住——本檔補**兩個真缺口**）、
> 把 §0 六條禁止與 §1.2 十一列「被否決」變成**掃得出來的斷言**（8 顆），
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
| **§3「不做」6 條** | Gate 覆蓋頁首開關／EC2 跑 Postgres·Redis·Celery·GPU／S3 當備份／NAT·ALB·EIP·RDS·Lambda·ECS·Macie／常開 EC2／未核准前改 `.feature` | §4.3 ＋ §4.6 ＋ §4.9（`.feature` 零改動的證明） |
| **§4 資料流與冪等** | 影像不進 Redis／SQS／Celery 參數；`photo` 表不加 `job_id`、不加處理狀態欄 | §4.3 的 `test_兩條佇列的訊息body都不含影像位元組`、`test_photo表沒有為了雲端新增任何欄位` |
| **§5 API 與端點** | 不新增端點；上傳仍 202；openapi 零 DELETE | §4.3 的 `test_端點仍是22支而且openapi零DELETE` |
| **§9 測試策略** | 「必釘」9 條 ＋「pytest **不連真 AWS**」 | §4.1 的盤點表把 9 條逐條點名；§4.4 的三死埠實證 |
| **§12 驗收清單** | Demo 1／2／2b／3 ＋ 費用／安全 3 條 | §4.7 的**驗收包**逐條抄錄 ＋ 每條的指令 |
| **§13 風險與已知限制**（7 條） | EC2 Stop 不卸壓、敏感檔仍可去 ollama.com、不會更快、Free plan 會關帳、t4g 試用不一致、Classifier 會漏、套件分岔 | §4.7 驗收包的「已知限制」段照抄，**讓產品負責人在簽名之前看到** |
| **總覽 §10 誠實揭露**（a〜l ＋ A〜K） | design6 沒寫、由計畫層裁決的 23 條 | §4.7 驗收包的最後一段做成**逐條打勾的追認清單** |

---

## 2. 前置條件

- **Phase 74〜94 全部完成且全綠。** 這是收尾 phase，不是開發 phase。
- **★ 閘門 G1／G2／G3 都已由產品負責人通過**（G1 在 82 前、G2 在 91 前、G3 在 93 前）。
- **EC2 目前是 `stopped`**（Phase 94 的 Demo 3 步驟 7 做完的狀態）。
  本 phase §4.6 會**確認**它是 stopped，但**不需要**把它開機。
- 本檔所有指令都在**專案根目錄**執行（`grep`／`ls`／`git` 用的都是相對路徑，
  位置跑掉就會查到別的東西、甚至誤判成「通過」）。

### 開工基線（自己再驗一次，不要抄）

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

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
# 預期：672 passed ＋ 0 skipped（Phase 94 之後的累計；總覽 §9）
#   （＝總覽 §9 Phase 94 那列的累計；要對的是「本 phase +10」）

pytest tests/integration/test_design6_error_paths.py --collect-only -q | tail -1
# 預期：14 tests collected（90 的 4 ＋ 93 的 4 ＋ 94 的 6）

git branch --show-current            # 預期：main
git status --short docs/spec/        # 預期：無輸出（工作區沒有動到規格）
git log -1 --format='%h %s' -- docs/spec/
# 預期：增量五 Phase 72 那一筆（2026-08-27 規格改版）——**不是**任何增量六的 commit。
#   只看 git status 不夠：前面的 phase 若已經進過 commit，改了規格也看不出來。

# 開工快照（總覽 §7 鐵律 12）：§6 最後一條「本 phase 沒有改到產品碼」要拿它來相減
git status --short -- app tests deploy compose.yaml Dockerfile db requirements.txt .github \
  > /tmp/p95-before.txt

aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text
# 預期：stopped
```

把數字填進這張表（**執行時填入，不要留空交差**）：

| 項目 | 值 |
|---|---|
| 開工時 `pytest -q` | ＿＿＿ passed ＋ 0 skipped（總覽 §9 寫 **672**） |
| 開工時 `test_design6_error_paths.py` 顆數 | ＿＿＿（總覽 §9 寫 **14**） |
| `docker compose ps` 服務數 | ＿＿＿（應為 **4**） |
| EC2 狀態 | ＿＿＿（應為 `stopped`） |
| `aws sts get-caller-identity` 的 Arn 結尾 | ＿＿＿（應為 `user/personaldocai-admin`） |

---

## 3. 範圍

### 做

- **§4.1** design6 §8 錯誤表 10 列逐列盤點（表格反映**事實**，不是抄的）。
- **§4.2** 在 `tests/integration/test_design6_error_paths.py` 補**兩個真缺口**（2 顆）。
- **§4.3** 同一個檔補「不做／禁止／被否決」掃碼（**8 顆**）。
- **§4.3.1** 把 `tests/integration/test_ingest_job_pdf.py` 兩句還寫著舊名（`_fail`／
  `_insert_photo_with_files`）的**註解**改成 Phase 76 之後的新名（純註解、零行為；
  Phase 76 §8 明寫「最自然的時機是 Phase 95」）。
- **§4.3.2** `README.md` 兩處 `543 passed, 0 skipped` → `682 passed, 0 skipped`（第 20 行附近的
  Tests 表格列、第 470 行附近的 `pytest -q` 註解；Phase 92 §4.10 明寫留給本 phase）。
- **§4.4** 三死埠零依賴實證（AWS ＋ Redis ＋ Ollama 一起指）。
- **§4.5** 正式庫健檢（四個查詢，比照 phase-71 §4.6）。
- **§4.6** 四個服務都在 ＋ EC2 是 `stopped` ＋ S3 是空的 ＋ 兩條佇列訊息數 0。
- **§4.7** 產出 `docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`。
- **§4.8** 產出 `docs/plan/todo/<日期>-增量六收尾95-TODO.md` 進度檔。
- **§4.9** 寫下歸檔清單（74〜95 ＋ 總覽），但**不執行**——等產品負責人決定 commit 時機。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 為了讓某顆測試變綠而改產品行為 | 這是**收尾**，不是重寫。首跑紅了＝揪到真缺陷 → 回**對應的 phase** 修產品碼，然後重跑全量（Phase 37 就是這樣抓出「自創實體＋釘選不是同一個交易」那個 bug） |
| 重複測已經有人測的東西 | 每一列先找「誰已經測了」，只補真正的缺口。重複的測試是負債：改一次程式要改兩個地方 |
| 動 `docs/spec/` 任何一個字 | design6 §10 明文：本增量對外上傳契約仍是 202、**不必**為了 fallback 改 Gherkin。要加「敏感不上雲」的 Example **需要另外核准**——那不在本增量的範圍 |
| 在測試裡連真的 AWS／Redis／Ollama、或啟動 Celery | design6 §9 明文。五道 autouse 安全網已經把外部依賴全擋掉；本檔的兩顆行為測試用 `CloudRoute(FakeMailbox(), FakeProbe(...))` |
| 開 EC2「順便再 demo 一次」 | Phase 92 的 Demo 2／2b 與 Phase 94 的 Demo 3 都做過了。本 phase 只**確認機器是 stopped**。開了就在燒點數（D15） |
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
| 10 | 誤開 NAT／EIP／GPU | 本文件禁止；驗收掃 compose／文件／Console | ★ 本檔 `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣`（§4.3）＋ §4.6 的 `describe-nat-gateways`／`describe-addresses` 預期空 |

- [ ] 逐列打勾。**表上的 ✓ 要用 `--collect-only` 對過才算數。**
- [ ] 反過來也一樣：發現某列已被完整測過而你手癢想在本檔再寫一顆 → **不寫**。

順便把 design6 **§9「必釘」9 條**也對一次（總覽 §3.7 有完整對照表）：

```bash
pytest --collect-only -q -k "零submit or 遠端關閉 or 探測丟例外 or 雲端結果 or 送兩次 or body or 敏感中文關鍵字 or 空檔名 or 亂碼檔名" | tail -20
```

- [ ] 9 條各自點得到名（少了就回對應的 phase 補，不要搬進本檔）。

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

**① 檔頭的 import 要補齊。** Phase 90 開檔時只有 `re` 與 `Path`，Phase 93 加了 `json`。
本 phase 還要用到下面這些，把最上面那一批 import 換成：

```python
"""增量六（design6.md）的收尾驗證：§8 錯誤表逐列點名、§0／§1.2／§3 的掃碼。

體例沿用 Phase 25／37／44／71 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py、test_design5_error_paths.py）：
**先盤點、只補 ★ 缺口**。§8 的 10 列大多已由 Phase 74〜94 各自的測試檔釘住
（逐列對照表見計畫 phase-95 §4.1；執行時要用 --collect-only 對過），
本檔只補兩個真缺口：

| 列 | 情況 | 誰把關 |
|---|---|---|
| 7 | 雲端看圖三次失敗 | P79／P87 各釘一半；★ 本檔【補A】釘「是整筆失敗，不是 fallback 本機」 |
| 2 | 非敏感但遠端關掉 | P78／P89 釘 worker 那一半；★ 本檔【補B】釘「HTTP 仍然 202，不是 5xx」 |

【補A】【補B】之後是 §0 六條禁止／§1.2 被否決 11 列／§3「不做」的掃碼【掃A】〜【掃H】。

⚠ 本檔**不連真 AWS、不連真 Redis、不啟動 Celery、不打真 Ollama**（design6 §9）：
   雲端路一律用 CloudRoute(FakeMailbox(), FakeProbe(...))，
   任務本體由測試直接呼叫 run_gated_ingest_job（conftest 的 `跑完任務`）。

⚠ Dockerfile／compose 的掃碼由 Phase 90 放在本檔前段；
   OIDC trust／deploy policy 的掃碼由 Phase 93 放在中段；
   CD workflow 的掃碼由 Phase 94 放在中後段。本 phase 從最後面續寫。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_connection
from app.dependencies import get_cloud_route, get_privacy_gate, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, ingest_job, staging_service
from app.services.aws_mailbox import AwsMailbox
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from app.workers.cloud_worker import process_job_message
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

> ⚠️ **只換 import 那一批。** 緊接在 import 後面、Phase 90 放的五個模組層 helper
> **原封不動留著**——`專案根目錄`、`dockerfile原始碼()`、`compose原始碼()`、
> `compose服務清單()`、`stage名稱清單()`。本 phase 的【掃B】就是要用其中兩個，
> **不要**在後面再定義一次同名的東西（`ruff check` 不會抓重複定義，
> 但兩份擺在同一個檔裡會讓後面的人不知道該改哪一個）。
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

看不懂 = PhotoUnderstanding(understood=False)


def 讓工人在本機等結果之前先做完(monkeypatch, 信箱: FakeMailbox, 工人的看圖) -> None:
    """把「工人在另一台機器上做事」這件事插在 wait_result 之前。

    為什麼要這樣插：本機端是**同步**的——run_gated_ingest_job 先 submit、
    再 wait_result 長輪詢。測試裡沒有第二個執行緒，所以工人必須在本機開始等
    **之前**把 jobs 佇列裡的訊息全部做完，wait_result 才拿得到結果。

    寫法與 Phase 87 `test_cloud_roundtrip.py` 的同名 helper **逐字相同**
    （刻意複製這八行而不是跨測試檔 import：測試檔之間不互相 import）。
    差別只在這裡餵的是**真的** process_job_message ＋ 會看不懂三次的 ScriptedVLM，
    不是 Phase 79 的假工人 fake_worker_process_one。
    """
    原本的 = cloud_ingest.CloudRoute.wait_result

    def 先讓工人做一輪(self, job_id, *, store):
        訊息 = 信箱.receive_job(0)
        while 訊息 is not None:
            process_job_message(信箱, 訊息, 工人的看圖)
            訊息 = 信箱.receive_job(0)
        return 原本的(self, job_id, store=store)

    monkeypatch.setattr(cloud_ingest.CloudRoute, "wait_result", 先讓工人做一輪)


def test_雲端看圖三次失敗是整筆失敗不是fallback本機(client, monkeypatch):
    """遠端活著、只是看不懂 -> job failed、零照片、S3 清空、**不重跑本機**。

    ⚠ monkeypatch 兩個模組的同名屬性：
        Phase 78 的 gated_ingest.py 寫的是 `ingest_job.run_ingest_job(...)`（帶模組名），
        所以蓋 ingest_job 那一個就攔得到；第二個 setattr 是保險——哪天有人改成
        `from app.services.ingest_job import run_ingest_job`，那個名字會綁在 gated_ingest
        模組上，只蓋 ingest_job 就攔不到了。兩個都蓋，這顆才不會因為 import 風格而假綠。
    """
    本機路被呼叫: list[str] = []

    def 記下本機路(job_id: str, **kwargs) -> None:
        本機路被呼叫.append(job_id)

    monkeypatch.setattr(ingest_job, "run_ingest_job", 記下本機路)
    if hasattr(gated_ingest, "run_ingest_job"):
        monkeypatch.setattr(gated_ingest, "run_ingest_job", 記下本機路)

    信箱 = FakeMailbox()
    工人vlm = ScriptedVLM([看不懂, 看不懂, 看不懂])
    讓工人在本機等結果之前先做完(monkeypatch, 信箱, 工人vlm)
    路 = cloud_ingest.CloudRoute(信箱, FakeProbe(True), timeout_seconds=5)
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: 路

    response = client.post(
        "/photos", files={"file": ("receipt-2026.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    assert 工人vlm.calls == 3, f"雲端工人應該看圖恰好 3 次，實際 {工人vlm.calls} 次"
    assert 本機路被呼叫 == [], (
        "雲端看不懂 ＝ 整筆失敗（總覽 §10 追認項 g）；"
        f"不可以再跑一次本機的 run_ingest_job：{本機路被呼叫}"
    )
    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed", f"job 應該標 failed：{job}"
    assert photo_repository.count_photos() == 0, "看不懂就不留任何 photo 列"
    assert 信箱.objects == {}, "失敗路徑也要把 S3 的三個物件清乾淨（§8 第 7 列）"
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

看得懂 = PhotoUnderstanding(
    understood=True,
    text="某間咖啡店的菜單，拿鐵 120 元",
    category="飲食",
    location="咖啡店",
    items=["拿鐵"],
)


@pytest.fixture
def 不擲出例外的client():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應而不是往外炸。

    這一顆要驗的正是「**不會**變成 5xx」，所以必須用這個 client——
    用一般的 client 的話，真的壞掉時測試會炸在 raise，看不到狀態碼是幾。
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_遠端不可用時上傳仍然回202不會變5xx(不擲出例外的client):
    """design6 §0 禁止第 6 條、D10：遠端關掉時使用者**完全無感**。"""
    信箱 = FakeMailbox()
    路 = cloud_ingest.CloudRoute(信箱, FakeProbe(False), timeout_seconds=5)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(看得懂)  # fallback 用的本機看圖
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: 路

    response = 不擲出例外的client.post(
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
    assert 信箱.put_calls == 0, "探測不通過就不該有任何 S3 呼叫"
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
# 【補A】：把「本機路被呼叫 == []」暫改成 "!= []"，跑一次要紅
# 【補B】：把「== 202」暫改成 "== 500"，跑一次要紅
```

- [ ] 兩顆各做過一次反向驗證，親眼看到紅，再改回來。

### 4.3 「不做／禁止／被否決」掃碼（8 顆）

**先把對應關係列清楚**（每一顆守的是哪幾條規則）：

| 掃碼測試 | design6 出處 | 守的是什麼 |
|---|---|---|
| `test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣` | §0 禁止第 4 條、§1.2 第 8 列、§3「不做」第 4 條、§8 第 10 列 | 沒有人「順手」開了會燒點數的服務 |
| `test_compose沒有為了雲端新增任何服務` | 總覽 §7 鐵律 11、§1.2 第 1 列 | **AWS 的九個變數名與工人名稱不進 compose**（設定走 `.env`）；「服務仍恰四個」沿用 Phase 90 的 `compose服務清單()` 當錨點。分工：Phase 90 那顆守「多階段沒波及 compose」（`build: .`×2、零 `target:`、`image: personaldocai-app`×2、四個服務），本顆守「零 AWS 設定」 |
| `test_端點仍是22支而且openapi零DELETE` | §5 | 本增量不新增使用者打的 REST 端點 |
| `test_兩條佇列的訊息body都不含影像位元組` | §0 禁止第 2 條、§1.2 第 3 列、§4 第 1 條、§9 必釘第 7 條 | 位元組走 S3，佇列只放指路的紙條 |
| `test_工人不寫Postgres也不算embedding` | D11、D13、§3「不做」第 2 條 | 工人只看圖；向量與資料庫永遠在本機 |
| `test_boto3唯一入口仍是aws_mailbox` | 總覽 §7 鐵律 5 | 流程層只認 `CloudMailbox` Protocol，所以測得動、也擋得住第五道安全網被繞過 |
| `test_photo表沒有為了雲端新增任何欄位` | §4 最後一條、總覽 §7 鐵律 13 | `route`／`privacy` 住 JobStore，不進 `photo` 表 |
| `test_隱私閘門不會去關AI後端開關` | D6、§0 禁止第 5 條 | 閘門可讀 AI_BACKEND，不准寫入或關掉開關 |

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
# ---------------------------------------------------------------------------

# 設定檔（deploy/**、.github/workflows/*.yml、compose*.yaml）用的樣式。
# 前半是資源名與 CLI 子指令；後半是 IAM 動作前綴 lambda:／ecs:／rds:，
# 前面必須**不是**字元（引號、空白、冒號都可以）——不加這個條件的話，
# keywords:／records:／specs: 這種普通的 YAML 鍵會被 rds:／ecs: 誤中（假紅）。
# re.I：NatGateway／natgateway／ElastiCache 都要抓得到。
設定檔禁字 = re.compile(
    r"NatGateway|nat-gateway|allocate-address|elasticloadbalancing|fargate|elasticache"
    r"|(?<![\w-])(?:lambda|ecs|rds):",
    re.I,
)

# app/ 的 .py 用的關鍵字（全部轉小寫之後比對）。
# 只掃「真的會建出那些資源」的長相，不掃裸關鍵字。
產品碼禁字 = (
    "natgateway",
    "nat_gateway",
    "nat-gateway",
    "allocate_address",
    "allocate-address",
    "elasticloadbalancing",
    "fargate",
    'client("lambda"',
    'client("ecs"',
    'client("rds"',
)


def test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣():
    """design6 §0 禁止第 4 條：這些服務全都沒有需求，而且 NAT 會直接打爆 Free plan 點數。

    掃三棵樹：app/（產品碼）、deploy/（IAM policy 與 EC2 開機腳本）、
    .github/workflows/（CI 與 CD）＋ compose*.yaml。

    刻意**不掃** docs/、LAUNCH.md、CLAUDE.md：那些文件本來就合法地寫著「禁止 NAT」
    這幾個字，掃了只會假紅。文件那一半交給 §4.6 的人工檢查（describe-nat-gateways）。
    """
    違規: list[str] = []

    for 檔案 in sorted((專案根目錄 / "app").rglob("*.py")):
        原始碼 = 檔案.read_text(encoding="utf-8").lower()
        命中 = [關鍵字 for 關鍵字 in 產品碼禁字 if 關鍵字 in 原始碼]
        if 命中:
            違規.append(f"{檔案.relative_to(專案根目錄).as_posix()}：{命中}")

    設定檔: list[Path] = []
    for 樣式 in ("deploy/**/*", ".github/workflows/*.yml", "compose*.yaml"):
        設定檔 += [路徑 for 路徑 in 專案根目錄.glob(樣式) if 路徑.is_file()]
    for 檔案 in sorted(設定檔):
        命中 = 設定檔禁字.findall(檔案.read_text(encoding="utf-8"))
        if 命中:
            違規.append(f"{檔案.relative_to(專案根目錄).as_posix()}：{命中}")

    assert 違規 == [], f"design6 §0 禁止第 4 條：不做 NAT／EIP／ALB／RDS／Lambda／ECS：{違規}"

    # 防呆錨點：確認真的掃到東西了（目錄被改名／glob 寫錯要紅在這裡，不是默默全過）
    assert (專案根目錄 / "deploy" / "aws").is_dir(), "deploy/aws/ 應該存在（Phase 82 起）"
    assert (專案根目錄 / ".github" / "workflows" / "deploy.yml").exists(), (
        ".github/workflows/deploy.yml 應該存在（Phase 94）"
    )


# ---------------------------------------------------------------------------
# 【掃B】總覽 §7 鐵律 11：compose.yaml 本增量零改動
# ---------------------------------------------------------------------------


# 總覽 §2.4.2 裡所有跟 AWS／雲端路有關的變數名（九個）。它們**只准住在 .env**。
# 哪天有人在 compose.yaml 的 environment: 底下加了其中任何一個，這一顆就紅。
AWS的設定變數 = (
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
        ——build: . 兩處、零 target:、image: personaldocai-app 兩處、服務恰四個。
      本顆守「零 AWS 設定」——九個變數名與工人名稱都不出現。
    服務清單這裡也看一眼，但**沿用 Phase 90 的 compose服務清單()**（同一個檔的模組層 helper），
    不自己再寫一份 regex：直接對整份 compose.yaml 抓 `^  ([a-z][\\w-]*):$` 會連
    volumes: 底下的 pgdata:／redisdata: 一起抓進來（Phase 90 實測回 6 個而不是 4 個）。
    """
    原文 = compose原始碼()

    for 變數 in AWS的設定變數:
        assert 變數 not in 原文, f"AWS 的設定走 .env，不進 compose.yaml（總覽 §7 鐵律 11）：{變數}"
    for 名稱 in ("cloud_worker", "cloud-worker"):
        assert 名稱 not in 原文, f"本機不跑雲端工人容器，那是 EC2 的事（總覽 §7 鐵律 11）：{名稱}"

    # 錨點：確認讀到的真的是那份 compose（服務仍是四個；主斷言在 Phase 90 那顆）
    assert compose服務清單() == ["db", "redis", "app", "worker"]


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
      （逐支列名由 test_design5_error_paths.py::test_端點恰好是這22支 守著）。

    ⚠ 不要用 app.routes 清點——FastAPI 0.141 有 _IncludedRouter 的已知坑，
      路由不會被攤平，數出來的數字是錯的。一律走 /openapi.json。
      WebSocket /camera/{token}/signal 依 FastAPI 的行為不進 openapi，不計入。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(路徑, 動詞) for 路徑, item in paths.items() for 動詞 in item]

    assert len(運算元) == 22, f"本增量端點恆為 22（design6 §5），現在是 {len(運算元)}"
    assert [動詞 for _, 動詞 in 運算元 if 動詞 == "delete"] == [], "系統仍然沒有任何刪除功能"


# ---------------------------------------------------------------------------
# 【掃D】§0 禁止第 2 條／§4 第 1 條／§9 必釘第 7 條：佇列只放紙條，不放位元組
# ---------------------------------------------------------------------------


class 只記帳的S3:
    """AwsMailbox 建構時可以注入 client；塞這個進去就完全不會碰 boto3。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class 只記帳的SQS:
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
    sqs = 只記帳的SQS()
    信箱 = AwsMailbox(
        bucket="不會用到",
        jobs_queue_url="https://sqs.example/jobs",
        results_queue_url="https://sqs.example/results",
        region="ap-northeast-1",
        s3=只記帳的S3(),
        sqs=sqs,
        ec2=object(),
    )

    信箱.send_job("job-abc", "documents/job-abc/input.png")
    信箱.send_result("job-abc")

    assert len(sqs.sent) == 2, "應該恰好送出兩則（jobs 一則、results 一則）"
    for 呼叫 in sqs.sent:
        body = 呼叫["MessageBody"]
        assert isinstance(body, str), "body 必須是字串"
        解析 = json.loads(body)  # 位元組塞得進去的話這一行就會炸
        assert set(解析) <= {"job_id", "s3_key"}, f"body 只准有 job_id 與 s3_key：{sorted(解析)}"
        assert len(body.encode("utf-8")) < 1024, (
            f"body 應該只有幾十個位元組，現在是 {len(body.encode('utf-8'))}"
        )
        for 疑似位元組 in ("base64", "data:image", "\\x89PNG", "%PDF"):
            assert 疑似位元組 not in body, f"佇列訊息不可以帶影像：{疑似位元組}"


# ---------------------------------------------------------------------------
# 【掃E】D11／D13／§3「不做」第 2 條：工人不碰資料庫、不算 embedding
# ---------------------------------------------------------------------------

工人不可以引入的頂層模組 = {"psycopg", "celery", "redis", "langchain_ollama", "langchain_core"}


def test_工人不寫Postgres也不算embedding():
    """D11：EC2 只當工人（無 DB、無 Celery、無 Redis）；D13：向量一律本機 bge-m3。

    用 ast 而不是 grep：
      - 註解裡寫了「不 import psycopg」不會誤判成違規
      - `from app.db import session` 這種寫法 grep "import psycopg" 抓不到，ast 抓得到
    """
    來源 = (專案根目錄 / "app" / "workers" / "cloud_worker.py").read_text(encoding="utf-8")
    樹 = ast.parse(來源)

    匯入: set[str] = set()
    for 節點 in ast.walk(樹):
        if isinstance(節點, ast.Import):
            匯入 |= {別名.name for 別名 in 節點.names}
        elif isinstance(節點, ast.ImportFrom) and 節點.module:
            匯入.add(節點.module)

    違規 = sorted(名稱 for 名稱 in 匯入 if 名稱.split(".")[0] in 工人不可以引入的頂層模組)
    assert 違規 == [], f"工人不可以碰資料庫／Celery／Redis／向量套件（D11、D13）：{違規}"
    違規 = sorted(名稱 for 名稱 in 匯入 if "photo_repository" in 名稱 or 名稱.startswith("app.db"))
    assert 違規 == [], f"工人不可以碰 repository 或 db 層（D11）：{違規}"

    # embedding 那一半：工人不算向量，result.json 也不含 embedding 這個鍵（D13）。
    # 同樣走語法樹而不是掃原始碼文字：cloud_worker.py 的 docstring 本來就寫著
    # 「不算 embedding」這幾個字，用子字串比對會自己把自己掃紅。
    #   名稱   ＝ 程式裡用到的識別字（變數、屬性、import 進來的名字）
    #   字串常數 ＝ 寫死的字串（result.json 的鍵名就是這種）——比對**整個字串相等**，
    #             所以 docstring 裡的長句不會誤中，dict 鍵 "embedding" 卻逃不掉
    名稱: set[str] = set()
    字串常數: set[str] = set()
    for 節點 in ast.walk(樹):
        if isinstance(節點, ast.Name):
            名稱.add(節點.id)
        elif isinstance(節點, ast.Attribute):
            名稱.add(節點.attr)
        elif isinstance(節點, ast.alias):
            名稱.add(節點.asname or 節點.name)
        elif isinstance(節點, ast.Constant) and isinstance(節點.value, str):
            字串常數.add(節點.value)

    向量相關的名字 = {
        "get_embeddings",
        "embed_understanding",
        "embed_query",
        "embed_documents",
        "Embeddings",
        "OllamaEmbeddings",
        "FakeEmbeddings",
    }
    assert not (名稱 & 向量相關的名字), (
        f"向量一律在本機算（D13）：工人不該碰 {sorted(名稱 & 向量相關的名字)}"
    )
    assert "embedding" not in 字串常數, "result.json 不含 embedding 這個鍵（D13）"

    # 防呆錨點：確認掃的真的是工人（檔案搬走／改名要紅在這裡）
    assert "def process_job_message(" in 來源
    assert "def main(" in 來源


# ---------------------------------------------------------------------------
# 【掃F】總覽 §7 鐵律 5：boto3 只准出現在 aws_mailbox.py
# ---------------------------------------------------------------------------

# 只比對**真的 import 敘述**（行首 + import/from + boto3 或 botocore），
# 不是掃裸的 "boto3" 五個字——這樣本檔自己提到 boto3（註解、豁免名單、斷言訊息）
# 不會把自己掃紅。樣式與 Phase 83 那顆逐字相同（含縮排＝函式裡的延遲 import 也抓得到）。
BOTO3引入 = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)

# 總覽 §2.7 定的三個放行檔。「放行」只是允許、不是要求：
# scripts/aws_check.py（Phase 84）其實走的是 AwsMailbox、沒有直接 import boto3，
# 留在名單裡不會讓這一顆變鬆。
可以引入boto3的檔案 = {
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
    違規: list[str] = []
    for 樹根 in ("app", "tests", "scripts"):
        for 檔案 in sorted((專案根目錄 / 樹根).rglob("*.py")):
            相對路徑 = 檔案.relative_to(專案根目錄).as_posix()
            if 相對路徑 in 可以引入boto3的檔案:
                continue
            if BOTO3引入.search(檔案.read_text(encoding="utf-8")):
                違規.append(相對路徑)

    assert 違規 == [], f"boto3 只准出現在 app/services/aws_mailbox.py（總覽 §7 鐵律 5）：{違規}"

    # 反過來也釘一次：入口檔**必須**真的 import 了，不然這一顆會變成永遠綠的裝飾品
    入口檔 = 專案根目錄 / "app" / "services" / "aws_mailbox.py"
    assert BOTO3引入.search(入口檔.read_text(encoding="utf-8")), (
        "aws_mailbox.py 應該要 import boto3"
    )


# ---------------------------------------------------------------------------
# 【掃G】§4 最後一條／總覽 §7 鐵律 13：photo 表不加任何欄
# ---------------------------------------------------------------------------

# 增量五結束時 photo 表的欄位集合（db/schema.sql 逐欄對過）。
# 增量六**一欄都不准動**：route／privacy 住 JobStore（design6 §4 明文）。
增量五結束時的photo欄位 = {
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
            欄位 = {row["column_name"] for row in cur.fetchall()}

    assert 欄位 == 增量五結束時的photo欄位, (
        f"photo 表本增量零改動；多出來：{sorted(欄位 - 增量五結束時的photo欄位)}；"
        f"少掉了：{sorted(增量五結束時的photo欄位 - 欄位)}"
    )


# ---------------------------------------------------------------------------
# 【掃H】D6／§0 禁止第 5 條／§1.2 第 7 列：兩扇門完全分開
# ---------------------------------------------------------------------------


def test_隱私閘門不會去關AI後端開關():
    """D6（2026-09-01）：閘門**跟著**頁首開關走，但**不准寫入／關掉**它。

    閘門短問讀 config.AI_BACKEND 選本機或雲端 VLM（與 get_vlm 同一套）。
    禁止的是「敏感就強制把開關撥回本機」或寫入 AI_BACKEND。
    """
    for 檔名 in ("privacy_gate.py", "gated_ingest.py"):
        原始碼 = (專案根目錄 / "app" / "services" / 檔名).read_text(encoding="utf-8")
        assert "AI_BACKEND =" not in 原始碼, f"{檔名} 不可以寫入頁首的 AI 模型開關（D6）"
        assert "settings/ai-backend" not in 原始碼, f"{檔名} 不可以打開關端點"
```

**貼完先整理格式，再跑一次（首跑應該全綠）：**

```bash
ruff check --fix tests/integration/test_design6_error_paths.py
ruff format tests/integration/test_design6_error_paths.py
pytest tests/integration/test_design6_error_paths.py -v
```

**預期：24 passed** ＝ Phase 90 的 4 ＋ Phase 93 的 4 ＋ Phase 94 的 6 ＋ 本 phase 的 10。

**反向驗證（防假綠；至少做四次）：**

| 顆 | 怎麼弄紅 |
|---|---|
| `test_compose沒有為了雲端新增任何服務` | 在 `compose.yaml` 的 `worker:` → `environment:` 底下暫時加一行 `      S3_BUCKET: x`，跑一次要紅在「AWS 的設定走 .env」，再刪掉 |
| `test_photo表沒有為了雲端新增任何欄位` | 把 `增量五結束時的photo欄位` 暫時拿掉 `"embedding"`，跑一次要紅在「少掉了」，再加回去 |
| `test_boto3唯一入口仍是aws_mailbox` | 把 `可以引入boto3的檔案` 裡的 `app/services/aws_mailbox.py` 暫時刪掉，跑一次要紅，再加回去 |
| `test_工人不寫Postgres也不算embedding` | 在 `cloud_worker.py` 最上面暫時加一行 `import redis`，跑一次要紅，再刪掉 |

- [ ] 四次紅都親眼看過了。**沒紅過的「某個東西不存在」型斷言，你不知道它有沒有在睡覺。**

### 4.3.1 Phase 76 留下的兩句舊名註解（純註解、零行為）

Phase 76 把 `_fail` → `fail_job`、`_insert_photo_with_files` → `insert_photo_with_files` 之後，
`tests/integration/test_ingest_job_pdf.py` 有**兩句 docstring** 仍寫舊名。76 為了守住
「既有測試檔一個字都不改」刻意沒動它們，並在 §8 把這件事留給本 phase（收尾本來就會清點 `tests/`）。

```bash
grep -n "_fail\b\|_insert_photo_with_files" tests/integration/test_ingest_job_pdf.py
# 預期恰兩行（Phase 76 記的是第 216 與 239 行；以 grep 為準，不要靠行號）：
#   …兩種都是同一個例外、同一條 _fail 路），所以整合層驗 b"not a pdf" 這一條就夠。
#   …半成品由 _insert_photo_with_files 自己清乾淨，所以不會留孤兒列或孤兒檔。
```

- [ ] 把那兩句裡的 `_fail` 改成 `fail_job`、`_insert_photo_with_files` 改成 `insert_photo_with_files`
      （只動這兩個詞，其他一個字都不碰）。
- [ ] 再 grep 一次，預期**零命中**；然後：

```bash
ruff format --check tests/integration/test_ingest_job_pdf.py && ruff check tests/integration/test_ingest_job_pdf.py
pytest tests/integration/test_ingest_job_pdf.py -q     # 預期：顆數與改之前一模一樣、全綠
git diff --stat -- tests/integration/test_ingest_job_pdf.py   # 預期：1 file changed, 2 insertions(+), 2 deletions(-)
```

> 這一步**不算**「改了既有測試」——動的是 docstring 裡的兩個名字，斷言與流程一個字都沒變。
> 它會出現在 §6 最後一條的 `git status` 相減結果裡（預期就是要有它）。

### 4.3.2 `README.md` 的 Tests 顆數（543 → 682；純文件）

Phase 92 §4.10 改 `README.md` 時明寫「Tests 那一列本 phase 不要動——增量六做完是 682，
那是 Phase 95 收尾時一起改的事」。現在就是那個時候；**先跑完 §4.4 拿到 682 再改**，數字要抄實跑的。

```bash
grep -n "543 passed, 0 skipped" README.md
# 預期恰兩行（第 20 行附近「| Tests | **543 passed, 0 skipped** …」與
#            第 470 行附近「pytest -q            # 543 passed, 0 skipped」；以 grep 為準，不要靠行號）
```

- [ ] 兩處的 `543` 都改成 `682`（其餘一個字不碰；`CLAUDE.md` 的顆數放到 §8 第 3 點、commit 之後一起更新）。
- [ ] 再 grep 一次 `543 passed`，預期**零命中**；`git diff --stat README.md` 預期 `2 insertions(+), 2 deletions(-)`。

### 4.4 全量回歸與三死埠零依賴實證

```bash
# 1) 全量
pytest -q
# 預期：682 passed ＋ 0 skipped（開工基線 672 ＋ 10；總覽 §9）
#      「0 skipped」＝ pytest 不會印那一段（自 Phase 51 摘標之後就沒有 skipped 了）

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
# 預期：增量五 Phase 72 那一筆（2026-08-27 規格改版）——不是任何增量六的 commit
git log -1 --format='%h %s' -- .github/workflows/test.yml
# 預期：4269985 ci: GitHub Actions 跑 ruff check／format 與 pytest（Phase 73；既有 CI 零改動）

# 6) 格式與 lint
ruff format --check app tests scripts && ruff check app tests scripts
```

- [ ] 六項全部符合預期。顆數填進來：基準 ＿＿＿ → 完成 ＿＿＿。

> ⚠️ **埠 9 是保留的 discard 埠**，本機一定沒人在聽，指過去會**立刻** connection refused
> 而不是卡住等逾時。顆數不一樣、或出現連線逾時，代表**某條路徑真的去打了那個服務**
> ——最常見的原因是某顆測試繞過了假件（例如自己 `new` 了一個真的 `AwsMailbox`）。
>
> ⚠️ **絕對不要同時跑兩份 pytest。** `reset_tables` 每測都 `TRUNCATE` 同一個測試庫，
> 兩份同時跑會互相清掉對方的資料。症狀是**大量看似隨機的** 404 與
> `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣。

### 4.5 正式庫健檢（四個查詢；比照 phase-71 §4.6）

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

### 4.6 四個服務、EC2 是 stopped、S3 是空的、佇列是空的

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

# ② EC2 必須是 stopped（Demo 都做完了，用完就關；D15）
aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].{Type:InstanceType,Arch:Architecture,State:State.Name}'
# 預期：{"Type": "t4g.small", "Arch": "arm64", "State": "stopped"}

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

- [ ] 新建 `docs/plan/report/<你交出去的那一天>-增量六驗收包-請產品負責人確認.md`
      （檔名日期換成實際日期），內容**照抄下面整段**，
      **A 段的數字換成你這次實際跑出來的**：

`````markdown
# 增量六驗收包（2026-XX-XX）——請產品負責人確認

> **給產品負責人：** 這是「本機隱私閘門」與「可關掉的雲端 worker」的驗收清單。
> 全部看過、沒問題的話，請說一句「**增量六沒問題**」——有這句話，實作者才會
> 把 `docs/plan/unfinish/` 的 23 份計畫檔（總覽 ＋ phase-74〜95）歸檔、把整個增量進 commit。
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

- [x] `pytest -q` ＝ **＿＿＿ passed ＋ 0 skipped**（增量六開工時是 543，收工是 **682**，合計 +139）
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
      收尾檔 `tests/integration/test_design6_error_paths.py` 共 **24 顆**
      ＝ Dockerfile／compose 4 ＋ OIDC 4 ＋ CD 6 ＋ 本輪 10；逐列對照表在 phase-95 §4.1）
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
| B1 | 準備一張檔名明確敏感的圖（例如 `身分證正面.jpg`，內容隨便）。上傳頁選它按上傳：畫面**立刻**回應，右下角出現一列進度 | ⬜ |
| B2 | 馬上看 S3：**完全沒有東西**（連 `documents/` 前綴都不會出現）<br>`aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION"` | ⬜ |
| B3 | 看 worker 的 log（指令見表格下方）：有一行 `route=local verdict=SENSITIVE`；**沒有**任何 `fallback=` 那一行（它根本沒打算走雲端） | ⬜ |
| B4 | 等 worker 跑完（本機模型 64〜88 秒；想快就把頁首開關撥到「雲端」）：進度列自己消失、頂欄「待決定（N）」+1、待決定頁多一張 | ⬜ |
| B5 | 再傳一張**看不出來**的（檔名是 `IMG_4821.jpg` 這種，或用手機鏡頭拍一張＝檔名「快門.jpg」）：一樣走本機，log 是 `route=local verdict=UNCERTAIN` | ⬜ |

看 worker log 的指令（B3、B5、C5、C9 都用這一條）：

```bash
docker compose logs --tail=200 worker | grep -e "route=" -e "fallback="
```

> 💡 **B5 是這個增量最重要的一條規則的實地演練：「不確定 ＝ 當敏感辦」。**
> 閘門判斷失誤時，代價是「這張照片沒有卸到雲端」（＝跟增量五一模一樣），
> 而不是「敏感檔外流」。

---

## C. Demo 2 ＋ 2b — 非敏感走雲端再回家、遠端關掉自動退回（design6 §12 原文）

> Demo 2 原文：**EC2 Start；上傳非敏感；S3 曾出現 input／result 後刪掉；照片進待決定；詢問能問到。**
> Demo 2b 原文：**EC2 Stop 後上傳非敏感；不必改任何設定；進度與入庫與增量五相同；S3 不出現新物件。**

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| C1 | 開機並等它 running：<br>`aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"`<br>`aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"` | ⬜ |
| C2 | 確認本機 `.env` 是 `CLOUD_ROUTE=ec2`，然後 `docker compose -f compose.yaml restart worker` | ⬜ |
| C3 | 上傳一張檔名明確非敏感的圖（例如 `receipt-2026.jpg`）：畫面立刻回應（202） | ⬜ |
| C4 | **馬上**看 S3（動作很快，晚了就看不到）：出現 `documents/<job_id>/context.json` 與 `input.jpg`，之後多一個 `result.json`<br>`aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ --region "$AWS_REGION" --query 'Contents[].Key' --output text` | ⬜ |
| C5 | worker 的 log（同 B 段那條指令）有 `route=cloud verdict=NON_SENSITIVE`，**沒有** `fallback=` 那一行 | ⬜ |
| C6 | 跑完之後 S3 **是空的**（本機把三個物件都刪了）；照片進了待決定牆；到問問題頁問一句跟那張照片有關的話，**回答引用得到它** | ⬜ |
| C7 | **Demo 2b：** 關機並等它 stopped：<br>`aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"`<br>`aws ec2 wait instance-stopped --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"` | ⬜ |
| C8 | **本機什麼設定都不要改**（`CLOUD_ROUTE` 仍是 `ec2`），再上傳一張非敏感的（例如 `menu-2026.jpg`）：**仍然是 202**，右下角進度列的樣子與增量五**完全一樣** | ⬜ |
| C9 | worker 的 log（同 B 段那條指令）有 `fallback=local reason=remote_unavailable`；S3 **一個新物件都沒有**；等它跑完，照片一樣入庫 | ⬜ |

> 💡 **C8／C9 就是這個增量的核心承諾：遠端關掉時，你完全感覺不到。**
> 唯一的差別在 worker 的 log 多一行字。

---

## D. Demo 3 — CD（design6 §12 原文）

> 原文：**改 worker 一點點 → push → CI 綠 → ECR 有該 commit SHA →
> Start 後 SSM 跑的是新 image（Stop 時至少 ECR 已更新）。**

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| D1 | 到 GitHub 的 Actions 頁面看那次 push：**`test` 綠了之後，`deploy` 才出現並開始跑**（不是同時） | ⬜ |
| D2 | `deploy` 的七個 step 全綠。⏱ `Build and push` 第一次要 **5〜15 分鐘**（GitHub 的機器是 x86，要模擬 ARM，很慢——這是預期的，不是壞掉） | ⬜ |
| D3 | 最後一步的 log 是 `instance state: stopped`，並印一則藍色提示 `instance not running; image pushed, next Start pulls latest`，**而且 job 是綠的**（機器沒開不算部署失敗） | ⬜ |
| D4 | ECR 上看得到那次 commit 的完整 sha，而且與 `latest` 在**同一組**（＝同一份映像掛兩個 tag）<br>`aws ecr describe-images --repository-name personaldocai-worker --region "$AWS_REGION" --query 'imageDetails[?imageTags].imageTags[]' --output json` | ⬜ |
| D5 | Start 之後，遠端工人的啟動 log 的 `version=` **逐字等於**那個 sha（＝真的跑的是新映像；**不是**看 `latest` 這個標籤）<br>指令見 phase-94 §4.8 步驟 5 | ⬜ |
| D6 | **做完 Stop。** | ⬜ |

---

## E. 費用／安全（design6 §12 剩下的三條）

> 原文三條：**Free plan、未升 Paid；Budget 有寄信設定** ／
> **Security group inbound 空；無 NAT、無 EIP** ／ **pytest 全綠且不碰真 AWS**。

| # | 請做什麼 / 看什麼 | 結果 |
|---|---|---|
| E1 | AWS Console → Billing and Cost Management → 確認方案仍是 **Free plan**（**未升 Paid**）、點數還有剩 | ⬜ |
| E2 | Budget 還在而且會寄信（**用 `personaldocai-admin` 身分**：它是 `~/.aws` 的 default profile，前提是「準備」那段已經 `unset` 掉 `.env` 的兩把 key，而且 root 已開「IAM user and role access to billing information」——Phase 82 §4.3 最後一步；最小權限的 `personaldocai-mac` 沒有 `budgets:ViewBudget`，用它會 AccessDenied）：`aws budgets describe-budgets --account-id "$ACCOUNT_ID" --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit}' --output table`（預期：`personaldocai-budget`、5 USD）<br>`aws budgets describe-notifications-for-budget --account-id "$ACCOUNT_ID" --budget-name personaldocai-budget --query 'Notifications[].{Type:NotificationType,Th:Threshold}'`（預期：ACTUAL 與 FORECASTED 各一筆、80） | ⬜ |
| E3 | Security group 的 inbound 是**空的**、outbound 只有 tcp 443：<br>`aws ec2 describe-security-groups --region "$AWS_REGION" --filters Name=group-name,Values=personaldocai-worker-sg --query 'SecurityGroups[0].IpPermissions'`（預期 `[]`） | ⬜ |
| E4 | 沒有 NAT、沒有 Elastic IP：<br>`aws ec2 describe-nat-gateways --region "$AWS_REGION" --filter Name=state,Values=pending,available --query 'NatGateways[].NatGatewayId' --output text`（預期空；`--filter` 是單數，這支指令的怪癖）<br>`aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[].AllocationId' --output text`（預期空） | ⬜ |
| E5 | **EC2 現在是 `stopped`**：`aws ec2 describe-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION" --query 'Reservations[0].Instances[0].{Type:InstanceType,Arch:Architecture,State:State.Name}'`（預期 `t4g.small` / `arm64` / **`stopped`**） | ⬜ |
| E6 | S3 是空的、兩條佇列訊息數都是 0（見上面 §4.6 的 ③④ 指令） | ⬜ |
| E7 | 看一眼 A 段第一行與第二行：`pytest -q` 全綠、三死埠顆數相同 | ⬜ |

---

## F. 最後

- [ ] 我（產品負責人）確認：**增量六沒問題。** 日期：__________

---

## 要你追認的裁決（design6 沒寫、由計畫層決定的 23 條）

> 這些**不是**你拍板的字，是實作計畫為了做得下去而補的決定。
> 每一條都寫在總覽 §10，也都註明「不同意的話回哪個 phase 改」。
> **請逐條看過並打勾；有任何一條不同意，直接說，實作者會回那個 phase 改。**

| # | 裁決 | 追認 |
|---|---|---|
| a | S3 多一個鍵 `documents/{job_id}/context.json`（工人靠它組出**同一份** prompt；放 SQS 會違反「body 只含 job_id、s3_key」） | ⬜ |
| b | 分支是 **`main`**，OIDC 的 `sub` 鎖 `…:ref:refs/heads/main`（design6 §6 寫的 `master` 是筆誤） | ⬜ |
| c | 本機「等雲端結果」是在**同一個 Celery 任務裡同步長輪詢**（佔一個 concurrency 名額，但不佔 GPU） | ⬜ |
| d | results 佇列是共用的，收到別人的 `job_id` 要「還回去或當殘訊息刪掉」 | ⬜ |
| e | 開機拉 `latest`；CD 同時推 `<sha>` 與 `latest`；「跑的是不是新映像」靠工人 log 的 `version=` 驗 | ⬜ |
| f | 隱私規則版**只看檔名**（不打開圖）；鏡頭拍的「快門.jpg」永遠 `UNCERTAIN`＝本機 | ⬜ |
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
| G | ★G1 ＝ 甲的驗收 ＋ 你明示「可以開始花 AWS 資源」；**Phase 82 排在 G1 之後**（開戶就開始算 Free plan 的 6 個月） | ⬜ |
| H | **Phase 76 是計畫層加的一份純重構**（design6 完全沒提）；沒有它，Phase 79 只能複製一份會漂移的同款程式碼 | ⬜ |
| I | 多建一個 **`personaldocai-admin`**（AdministratorAccess）**只給 Mac 上的 `aws` CLI 用**；程式用的 `personaldocai-mac` 仍是最小權限，它的 key 只在 `.env`（載進 shell 後要 `unset`） | ⬜ |
| J | Phase 83 **多加 1 顆** `test_get_object拿得回位元組而delete_objects送出鍵清單`（+16 不是 +15）；顆數軌跡自 83 起 +1，終值 **682** | ⬜ |
| K | 工人收到**壞訊息**（`s3_key` 空的、或副檔名不是 .jpg／.png／.pdf）→ log warning、刪掉那則 jobs 訊息、什麼都不寫（不然它每 900 秒回來一次） | ⬜ |

---

## 附註（實作者）

**規格檔（★）**：`docs/spec/` **全增量一個字都沒改**——design6 §10 明文
「本增量對外上傳契約仍是 202 ＋ 分析成功才有照片；**不必**為了 fallback 改 Gherkin
（那是內部路由）」。要加「敏感不上雲」的 Example **需要另外核准**，不在本增量範圍。

**已知限制（design6 §13 ＋ 計畫層補充，照抄；請在簽名之前看過）：**

- **EC2 Stop 的時候不卸壓。** 機器關著就等於沒有雲端管線，每一張非敏感照片都會退回本機看圖。
  這是用來換「卡片 $0」的代價。要卸壓就先 Start。
- **頁首撥雲端時，敏感檔的影像仍然可以去 ollama.com。** Privacy Gate 管的是
  S3／SQS／EC2 這條管線，**不管**頁首那顆開關（D6）。
  ⚠ **對外說法不可以寫成「敏感資料完全不出雲」**（design6 §6 明文）。
- **EC2 ＋ Ollama Cloud 不會比「本機 ＋ 頁首雲端開關」更快。** 多了 S3 上傳、SQS 來回、
  S3 下載三段來回。開機的價值是**卸掉本機的 Celery／GPU 名額**與**作品集管線**，不是延遲。
- **Free plan 滿 6 個月或點數用完會關帳。** 不是扣卡，是**資源消失**（90 天內可升 Paid 救回）。
  雲端上沒有正本——S3 只有處理中的暫存檔、EC2 只有一支無狀態工人，照片一張都不會少。
- **t4g 試用與 Free plan 的文件可能不一致。** 開機後看帳單；沒有 $0 那一列就立刻 Stop，
  只吃微量點數。
- **Classifier 一定會漏。** 規則版只看**檔名**；證件照未必有關鍵字。所以「不確定」一律當本機。
  **這不是合規等級的 DLP。**
- **等雲端結果的時候佔一個 Celery 名額。** 兩個名額之一在長輪詢（不佔 GPU）。
- **results 佇列是共用的**，會收到別人的訊息；本機會還回去或當殘訊息刪掉。
- **開機拉的是 `latest`**，不是某個固定 sha。
- **GitHub runner 模擬 arm64 很慢**（第一次 build 5〜15 分鐘）。
- **host 的 `.venv` 與映像裡的套件會分岔**（`requirements.txt` 全是 `>=`），
  ARM worker 映像同樣有這個問題。所以「重建映像」要當成需要手動煙霧一次的動作。
`````

- [ ] 交出去之前，把 A 段的 `＿＿＿` 全部填上實際數字、標題的日期換成當天。
- [ ] **停在這裡。** 不要因為「看起來都沒問題」就自己勾 B〜F 段、或自己 commit。

### 4.8 產出進度檔（`docs/plan/todo/`）

比照既有慣例（檔名格式 `<日期>-<這一批的名字>-TODO.md`，例如
`2026-08-26-增量五收尾71-72-TODO.md`）新建 **`docs/plan/todo/<日期>-增量六收尾95-TODO.md`**，
內容照抄下面整段、**把 `[ ]` 依實際進度改成 `[x]`**。
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
- [ ] 戊後半 91〜92：SG／IAM role／ECR／真機 Demo 2／2b／文件三份（662，+0）
- [ ] ★G3
- [ ] 己 93〜94：OIDC 部署角色／`deploy.yml` ＋ Demo 3（662 → **672**）
- [ ] 95：錯誤表盤點＋2 顆補缺＋8 顆掃碼＋三死埠實證＋驗收包（672 → **682**）
- [ ] 寫 REP（`docs/plan/report/<日期>-增量六收尾95-REP.md`）

## 鐵律

- 顆數只增不減、`skipped` 全程 0；不准為了湊數字改或刪測試
- `docs/spec/` 全程零改動（`git status --short docs/spec/` 必須一直是空的）
- 端點恆 22、openapi 零 DELETE；`compose.yaml` 零改動；`photo` 表零改動
- 每個 phase 的驗收都要有三死埠零依賴實證
- **每一次開 EC2 之後都要 Stop**；`docker compose down -v` 永遠禁止
- 不 commit、不搬 `unfinish/` → `finish/`（隨 commit 執行，時機由產品負責人決定）
````

- [ ] 建好了，而且閘門那三行**留白等人填**（不要自己寫日期）。

### 4.9 歸檔清單（**寫下來，不執行**）

產品負責人說「增量六沒問題」而且指示 commit 之後，把下面這 **23 份**從
`docs/plan/unfinish/` 搬到 `docs/plan/finish/`：

```text
phase-00-增量六總覽.md
phase-74-隱私閘門規則版.md              phase-85-建SQS兩條佇列.md
phase-75-隱私閘門本機模型備援.md        phase-86-真AWS雲端路接線.md
phase-76-入庫任務拆成看圖與落庫.md      phase-87-cloud_worker核心.md
phase-77-雲端路契約與第五道安全網.md    phase-88-cloud_worker主迴圈與Mac端到端.md
phase-78-閘門接線與fallback契約.md      phase-89-EC2探測running.md
phase-79-雲端路本機端單圖.md            phase-90-worker映像arm64.md
phase-80-雲端路逾時與冪等.md            phase-91-EC2的網路IAM與ECR.md
phase-81-雲端路PDF.md                   phase-92-EC2真機與文件.md
phase-82-AWS帳號與工具.md               phase-93-GitHub_OIDC與部署角色.md
phase-83-aws_mailbox模組.md             phase-94-CD工作流程.md
phase-84-建S3寄物櫃.md                  phase-95-增量六錯誤收尾與驗收包.md
```

搬法（**產品負責人指示才做**）：

```bash
git mv docs/plan/unfinish/phase-00-增量六總覽.md docs/plan/finish/
for n in $(seq 74 95); do
  git mv docs/plan/unfinish/phase-$n-*.md docs/plan/finish/
done
ls docs/plan/unfinish/
# 預期：只剩 phase-73-pre-commit與CI.md（那一份**不要動**——它是上一輪的，
#       產品負責人還沒指示歸檔）
```

產品負責人指示 commit 時，本 phase 的檔案清單（給那一次 `git add` 用；歸檔的 `git mv` 另計）：

```bash
git add tests/integration/test_design6_error_paths.py \
        tests/integration/test_ingest_job_pdf.py \
        README.md \
        docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md \
        docs/plan/todo/<日期>-增量六收尾95-TODO.md
# commit 訊息（供參考）：
#   test: Phase 95 增量六錯誤收尾——§8 十列逐列點名＋2 顆真缺口（雲端看不懂＝整筆失敗不 fallback、
#   遠端關掉仍 202）＋8 顆掃碼（NAT／EIP／Lambda／ECS 字樣、compose 零 AWS 設定、端點 22 零 DELETE、
#   佇列 body 無位元組、工人不碰 DB／embedding、boto3 唯一入口、photo 表 16 欄凍結、閘門不碰 AI 開關）、
#   三死埠實證顆數不變、test_ingest_job_pdf 兩句舊名註解改新名、README 的 Tests 543 → 682；672 → 682、端點仍 22
```

> ⚠️ **`git mv` 會直接 stage。** 這就是為什麼本 phase **不執行**它——
> 自己搬等於替產品負責人決定了那一筆 commit 裡有什麼（總覽 §7 鐵律 12）。
>
> ⚠️ **`phase-73-pre-commit與CI.md` 不要一起搬。** 它是上一輪（增量五之後的工程後盾）的
> 計畫檔，仍在 `unfinish/`，本增量從頭到尾都不要碰它。

- [ ] 清單寫進 REP／TODO，**指令沒有執行**。

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

- [ ] **§4.1 的 10 列盤點做完**，表格反映**事實**（每一顆 ✓ 都用 `--collect-only` 對過）；
      design6 §9「必釘」9 條也各自點得到名
- [ ] **本檔 10 顆全綠**，而且**至少六顆做過反向驗證**（§4.2 的兩顆 ＋ §4.3 的四顆）

  ```bash
  pytest tests/integration/test_design6_error_paths.py -v
  # 預期：24 passed ＝ 90 的 4 ＋ 93 的 4 ＋ 94 的 6 ＋ 本 phase 的 10
  ```

- [ ] **全量顆數 ＝ 開工基線 ＋ 10 ＝ 682 ＋ 0 skipped**（基準 ＿＿＿ → 完成 ＿＿＿）；
      **三死埠零依賴實證**：三個一起指、以及一次一個，顆數**全部相同**

  ```bash
  pytest -q
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
  ```

- [ ] **端點 ＝ 22、DELETE ＝ 0**（本檔那顆 ＋ 既有三顆清點測試都還綠）；
      **`photo` 表 16 欄、與增量五結束時逐字相同**（【掃G】＋ §4.5 的查詢 c）；
      **`compose.yaml` 恰四個服務、零 AWS 設定**；`Dockerfile` 只有 Phase 90 那一次改動
- [ ] **`boto3` 只在三個檔**（`aws_mailbox.py`／它的單元測試／`scripts/aws_check.py`）；
      **工人不 import 資料庫／Celery／Redis／向量套件**，也沒有 `"embedding"` 這個鍵
- [ ] **`docs/spec/` 全增量零改動**、**`.github/workflows/test.yml` 零改動**（工作區與
      歷史兩邊都看）；**三份規格 binder 全綠、零 SKIPPED**（27 顆；規格共七份，
      有 binder 的是上傳／詢問／無線鏡頭）

  ```bash
  git status --short docs/spec/ && git diff --stat -- docs/spec/     # 兩個都預期：無輸出
  git log -1 --format='%h %s' -- docs/spec/                 # 預期：增量五 Phase 72 那一筆
  git log -1 --format='%h %s' -- .github/workflows/test.yml # 預期：4269985（Phase 73）
  pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
         tests/integration/test_camera_feature.py -v
  ```

- [ ] **正式庫四個查詢全部符合預期**；`find data/staging -mmin +1440` 無輸出
- [ ] **`docker compose ps --no-trunc` ＝ 四個服務**，worker 的 COMMAND 有 `--concurrency=2`
- [ ] **EC2 是 `stopped`**、**S3 `documents/` 是空的**、**兩條佇列訊息數都是 0**；
      **沒有 NAT、沒有 EIP、SG 的 `IpPermissions` 是 `[]`、Budget 還會寄信**（§4.6 的 ②〜⑦）
- [ ] **`ruff format --check app tests scripts && ruff check app tests scripts`** exit 0
- [ ] **§4.3.1 的兩句註解已改**（`grep -n "_fail\b\|_insert_photo_with_files" tests/integration/test_ingest_job_pdf.py` 零命中；該檔顆數不變）
- [ ] **§4.3.2 `README.md` 兩處 Tests 顆數已改成 682**（`grep -c "543 passed" README.md` ＝ 0；`682 passed, 0 skipped` 恰兩處）
- [ ] **本 phase 沒有改到任何產品程式碼**

  ```bash
  git status --short -- app tests deploy compose.yaml Dockerfile db requirements.txt .github \
    | diff /tmp/p95-before.txt -
  ```

  預期：`diff` 只多出兩行——`M tests/integration/test_design6_error_paths.py` 與
  `M tests/integration/test_ingest_job_pdf.py`（§4.3.1 的兩句註解）
  （§2 開工時存的快照 `/tmp/p95-before.txt` 拿來相減；另外兩個新檔在 `docs/plan/`、`README.md` 也不在這個範圍）。`app/` 底下若多出新的 `M`，代表你改了不該改的——
  除非那是「揪到真缺陷、回原 phase 修」的結果，那就要在紀錄裡寫清楚修了什麼、並重跑全量。

- [ ] **驗收包已產出**（`docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`），
      A 段的數字**全部填好**、B〜F 段**留白**
- [ ] **進度檔已產出**（`docs/plan/todo/<日期>-增量六收尾95-TODO.md`），閘門三行**留白**
- [ ] **沒有 commit、沒有把 `unfinish/` 搬進 `finish/`**（§4.9 只寫清單、不執行）

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

4. **`test_隱私閘門不會去關AI後端開關` 掃的是寫入，不是讀取。**
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

8. **看到「24 passed」就以為 §0／§1.2／§3 全部守住了。**
   §4.6 那七項是**人工**的（EC2 狀態、S3 空不空、佇列殘訊息、NAT／EIP、SG inbound、Budget），
   測試跑再多次也不會幫你做。尤其 **EC2 是不是 `stopped`**——
   忘了 Stop 就是在燒點數，而且 pytest 永遠不會告訴你。

9. **`docs/spec/` 被「順手」改了一個字。**
   **症狀：** `git status --short docs/spec/` 有輸出。
   **原因：** 最常見的是編輯器自動加了行尾空白或換行。
   **正解：** `git checkout -- docs/spec/` 還原。design6 §10 明文本增量**不必**改 Gherkin；
   要改需要產品負責人**另外核准**（前三次解禁都有留檔頭紀錄，這一輪沒有）。

10. **自己把 `unfinish/` 搬進 `finish/`。**
    **症狀：** 產品負責人下次 `git status` 看到一堆 `R`（rename）已經被 stage 了。
    **原因：** `git mv` 會**直接 stage**。
    **正解：** §4.9 只**寫下清單**、不執行。歸檔隨 commit 執行，時機由產品負責人決定
    （總覽 §7 鐵律 12）。⚠ 也**不要**把 `phase-73-pre-commit與CI.md` 一起搬——
    那是上一輪的，本增量從頭到尾都不要碰它。

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
    **正解：** 沿用 Phase 90 放在同一個檔裡的 `compose服務清單()`——它先把 `services:` 區塊切出來
    再抓。§4.3 的【掃B】就是這樣寫的；**不要**自己再寫一份。

---

## 8. 完成後的專案狀態

**系統多了什麼：**

| 在哪裡 | 多了什麼 |
|---|---|
| repo | `tests/integration/test_design6_error_paths.py` +10 顆（該檔共 **24** 顆）；`tests/integration/test_ingest_job_pdf.py` 兩句 docstring 改用 Phase 76 的新名（零行為）；`README.md` 兩處 Tests 顆數 543 → 682；`docs/plan/report/<日期>-增量六驗收包-請產品負責人確認.md`（新）；`docs/plan/todo/<日期>-增量六收尾95-TODO.md`（新） |
| 產品程式碼 | **零改動**（除非盤點時揪到真缺陷，那要回原 phase 修並寫進紀錄） |

**對外行為變了沒：完全沒有。** 端點仍 **22**、openapi 仍**零 DELETE**、
`POST /photos` 仍 **202** 且回應三鍵、前端零改動、`compose.yaml` 零改動、
正式庫零改動、`docs/spec/` 零改動。

**顆數：**

| | 顆數 |
|---|---|
| 增量六開工（Phase 74 之前） | **543** ＋ 0 skipped |
| 開工基線（Phase 94 之後） | **672** ＋ 0 skipped（Phase 83 交付 +16，總覽 §10.2 追認項 J） |
| 本 phase 新增 | **+10**（2 顆補缺 ＋ 8 顆掃碼） |
| 完成後 | **682** ＋ 0 skipped |

與總覽 §2.7／§9 的 Phase 95 那一列**完全一致（+10，累計 682）**。整個增量六合計 **+139**。

**下一步（不是 phase，是人的事）：**

1. 把驗收包交給產品負責人，等他說「**增量六沒問題**」。
2. 他若對「要你追認的裁決」那 23 條有任何一條不同意 → 回那一條寫的 phase 改，
   然後重跑全量與相關的 Demo。
3. 他指示 commit 之後：commit ＋ 執行 §4.9 的歸檔指令 ＋ 更新 `CLAUDE.md` 的「專案概述」
   現況段（比照增量五的做法，在最後面追加一整段增量六成果）。
4. 寫 REP（`docs/plan/report/<日期>-增量六收尾95-REP.md`，檔名比照 `2026-08-26-增量五收尾71-72-REP.md`）。

**做完之後，`docs/plan/unfinish/` 應該只剩 `phase-73-pre-commit與CI.md` 一份。**

---

## 附：本文件引用的官方文件

- [PostgreSQL `information_schema.columns`](https://www.postgresql.org/docs/17/infoschema-columns.html)
  ——【掃G】用它證明 `photo` 表一欄都沒加
- [Python `ast` 模組](https://docs.python.org/3/library/ast.html)
  ——【掃E】用它讀工人的 import 名單（比 `grep` 準：註解不會誤判、`from … import` 躲不掉）
- [pytest `--collect-only`](https://docs.pytest.org/en/stable/how-to/usage.html)
  ——§4.1 盤點時用來確認「那顆測試真的存在」
- [SQS 訊息大小上限（現為 1 MiB）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-managing-large-messages.html)
  ——【掃D】的理由
- [SQS `PurgeQueue`（60 秒只能做一次）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
- [AWS CLI `s3api list-objects-v2`](https://docs.aws.amazon.com/cli/latest/reference/s3api/list-objects-v2.html)
- [AWS CLI `sqs get-queue-attributes`](https://docs.aws.amazon.com/cli/latest/reference/sqs/get-queue-attributes.html)
- [AWS CLI `ec2 describe-nat-gateways`](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-nat-gateways.html)
- [AWS CLI `ec2 describe-addresses`（Elastic IP）](https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-addresses.html)
- [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html)
- [EC2 Stop 與 Terminate 的差別](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
