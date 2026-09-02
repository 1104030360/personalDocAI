# Phase 88：cloud_worker 主迴圈與 Mac 上的端到端

> ⚠ **2026-09-01：** 閘門看圖不看檔名。端到端請上傳**內容是收據**的圖；
> `receipt-test.png` 只改檔名、內容是證件，會被判敏感而不進 S3。

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 本 phase 特別**不要**做這四件事：①不要為了「多跑幾張」加執行緒／`asyncio`／多行程
> （EC2 只有 2 vCPU，一次一則就好）；②不要加健康檢查端點、metrics、Prometheus
> （design6 D11：工人**不開任何連接埠**）；③不要建 EC2、不要碰 Dockerfile（那是 Phase 90〜92）；
> ④不要改 `process_job_message()` 一個字（Phase 87 已經釘死，本 phase 只在它外面包一圈迴圈）。

> 🎯 **一句話目標：** 幫 Phase 87 的工人加上**主迴圈**（一直向 jobs 佇列要訊息、
> 收到就處理）、**優雅停止**（Ctrl+C／`docker stop` 送的訊號只是豎旗標，手上這一則做完才退出）、
> **啟動 log**（`cloud_worker 啟動 version=… region=… bucket=…`）與 `python -m` 進入點；
> 然後在這台 Mac 上、對著**真的** S3／真的 SQS／真的 Ollama Cloud 跑一次端到端，
> 最後把操作步驟寫進 `LAUNCH.md`（英文）與 `CLAUDE.md`（繁中）。

**為什麼要做這個：**

Phase 87 寫好的 `process_job_message()` 是一個**只會處理一則訊息**的函式，
而且只有測試會呼叫它。真實世界沒有人餵訊息給它——**它還不是一支能跑的程式**。

本 phase 把它變成一支能跑的程式，而且是**丁段的驗收**（design6 §0 的「丁」那一列）：
「本機模擬工人：jobs→S3→看圖→`result.json`→SendMessage results；本機 Receive 後 GetObject 入庫」。
在這台 Mac 上跑通之後，上 EC2 就只剩「換一台機器跑同一支程式」這一件事——
這正是 design6 §1.2 最後一列否決「第一天同時開六樣東西」的理由。

還有一個實際考量：**在自己的 Mac 上，你看得到終端機。**
到了 EC2 上，那台機器 inbound 全關、沒有 SSH，你只能靠 SSM 與 `docker logs`。
工人邏輯有 bug 的話，在那裡除錯比在這裡難十倍。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **主迴圈（main loop）** | 「一直做同一件事，直到有人叫停」的 `while` 迴圈。這支工人的主迴圈只做兩件事：向 jobs 佇列要一則訊息、有的話就交給 `process_job_message()` |
| **長輪詢（long polling）** | 跟 SQS 要訊息時說「沒有的話你先幫我等最多 20 秒」，而不是「沒有就馬上回我空的」。好處是**少打很多次 API**（＝省錢），壞處是那 20 秒程式在等。20 秒是 AWS 的上限 |
| **SIGTERM** | 作業系統送給行程的「請你收工」訊號。`docker stop` 與 `systemctl stop` 送的就是它（送完會等一段時間，還沒停才強制殺） |
| **SIGINT** | 你在終端機按 **Ctrl+C** 送出的訊號。預設行為是丟出 `KeyboardInterrupt` 直接中斷 |
| **優雅停止（graceful shutdown）** | 收到停止訊號時**不立刻死**，而是把手上這一件事做完再退出。這支工人的「一件事」＝把 `result.json` 寫完、results 訊息送出、jobs 訊息刪掉 |
| **旗標（flag）** | 一個只有真／假兩種值的小開關。訊號處理函式把它豎起來，主迴圈下一圈看到就退出。**訊號處理函式裡不要做正事**——它可能在程式的任何一行中間被叫起來 |
| **backoff（退避）** | 「失敗了先等一下再試」。沒有它的話，AWS 一有問題就會變成全速空轉打 API：CPU 100%、帳單也不好看 |
| **`python -m 模組`** | 用「模組路徑」而不是「檔案路徑」執行 Python。`python -m app.workers.cloud_worker` 會把專案根目錄放進 `sys.path`，所以 `from app.core import config` 才找得到 |
| **logging handler** | 「log 要印到哪裡」的設定。**不掛 handler 的話 Python 只會印 WARNING 以上**，INFO 一行都看不到。uvicorn 會幫 web 行程掛，工人是獨立行程，得自己掛 |
| **`CLOUD_ROUTE=assume`** | 「假設遠端開著、不做探測」的模式（總覽 §2.4.2）。**只給階段丁與除錯用**：工人沒開的時候它會傻傻送出，然後等到逾時才 fallback |
| **`purge-queue`** | 把一條 SQS 佇列裡的訊息全部倒掉。手動煙霧留下的殘訊息用它清。⚠ **60 秒內只能做一次** |
| **`set -a; . ./.env; set +a`** | 把 `.env` 的每一行變成 shell 的環境變數（`set -a` ＝之後設定的變數自動 export）。後面那些 `aws` 指令要用到 `$S3_BUCKET`／`$AWS_REGION` 才不必寫死值。⚠ 載完**一定要接著** `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`：`.env` 那把 key 是給程式用的最小權限（`personaldocai-mac`：**沒有** `sqs:PurgeQueue`、`s3:CreateBucket` 這類管理動作），而環境變數的優先序比 `~/.aws` 高——不 unset 的話 CLI 會默默改用它，`purge-queue` 這種管理指令就 `AccessDenied`（`list-objects-v2` 用這把 key 倒是跑得過，所以不容易發現）（Phase 82 加進 CLAUDE.md 的 AWS 段已經記過這個坑） |

---

## 1. 對應 design6.md 章節

| 章節／編號 | 內容 | 本 phase 怎麼落地 |
|---|---|---|
| **§0「丁」那一列** | 何時算過：本機模擬工人 jobs→S3→看圖→`result.json`→SendMessage results；本機 Receive 後 GetObject 入庫 | §4.6 的人工端到端逐步驟，**這就是丁段的驗收** |
| **D12** | EC2 看圖一律 Ollama Cloud，與頁首開關無關 | `main()` 固定建 `vlm_service.OllamaCloudVLM()`，**不看** `config.AI_BACKEND` |
| **D10** | 遠端關掉＝fallback 本機 | §4.6 收工那一步：改回 `CLOUD_ROUTE=off`；沒改回去的後果寫在 §7 陷阱 3 |
| **D2／D3** | 閘門在本機、敏感與不確定一律留本機 | §4.6 第 ⑨ 步：傳一張 `身分證.png`，工人那一頭**零反應** |
| **§2.3** | Receive 用長輪詢（`WaitTimeSeconds` 最多 20 秒） | `LONG_POLL_SECONDS = 20`，測試斷言 `last_wait_seconds` 就是它 |
| **§9 測試策略** | 「真 AWS 煙霧靠人手」 | 本 phase 的 5 顆自動化測試只測迴圈，真 AWS 全部是 §4.6 的人工步驟 |
| **§12 Demo 2 的前身** | Demo 2 要 EC2 Start；本 phase 是同一條路、只是工人跑在 Mac 上 | §4.6 的步驟與 Demo 2 幾乎逐條對應，差別只有「工人在哪裡」 |
| **§3「Free plan 操作約束寫進 `LAUNCH.md`／`CLAUDE.md`」** | 文件要寫 | §4.7（`LAUNCH.md`，**英文**）與 §4.8（`CLAUDE.md`，繁中） |
| **總覽 §2.7 Phase 88** | 5 顆測試的名稱、動到的四個檔 | §4.1 逐字沿用 |
| **總覽 §10 追認項 l** | `assume` 只給階段丁與除錯用，日常要用 `ec2` | §7 陷阱 3 與兩份文件都寫了「收工改回 `off`」 |

---

## 2. 前置條件

**★ 閘門 G1 已由產品負責人通過。** ★G2 在 **Phase 90 之後**，所以本 phase 還在 G2 之前——
**一台 EC2 都還不能開**（design6 §0 的順序：丁做完、戊前半做完，才輪到 G2）。
本 phase 只會用到 S3 與 SQS（Phase 84／85 已經建好的），**不會建立任何新的 AWS 資源**。

**要先做完的 phase：**

| Phase | 本 phase 會用到它的什麼 |
|---|---|
| 84 | S3 bucket（`$S3_BUCKET`）已存在、BPA 全開、Lifecycle 2 天 |
| 85 | 兩條佇列（`$SQS_JOBS_QUEUE_URL`／`$SQS_RESULTS_QUEUE_URL`）已存在 |
| 86 | `dependencies.get_cloud_route()` 的 `assume` 分支（本機那一端靠它把檔案送出去） |
| 87 | `process_job_message()`、`app/workers/` 套件、`tests/unit/test_cloud_worker_unit.py` |

**開工前實查基線**（在專案根目錄執行）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps --no-trunc          # 四個服務都要在；db 與 redis 要 Up (healthy)
pytest --collect-only -q | tail -1    # 預期：646 tests collected
pytest -q                             # 預期尾巴：646 passed，0 skipped
git branch --show-current             # 預期：main
```

> **開工基線 ＝ 646**（總覽 §9：Phase 87 收工的數字）。
> 本 phase 結束時應該是 **651**（+5）。交錯做的話絕對數字會不一樣，
> **要對的是「本 phase 新增 5 顆」**。

**§4.6 的人工端到端另外還需要**（現在先檢查，不要等跑到一半才發現）：

```bash
# ① .env 該有的七個變數都有值（只看有沒有，**永遠不要把值印出來**）
for name in S3_BUCKET SQS_JOBS_QUEUE_URL SQS_RESULTS_QUEUE_URL \
            AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY OLLAMA_API_KEY OLLAMA_CLOUD_VLM_MODEL; do
  printf '%s=%s\n' "$name" "$(grep -c "^$name=." .env)"
done
# （變數名故意用 ASCII：bash 不接受中文變數名，zsh 才接受；這段在兩種 shell 都要能貼）
# 預期七行都是 =1（OLLAMA_CLOUD_VLM_MODEL：本專案 .env 釘成 gemma4，雲端沒有本機的 MLX tag）

# ② .env **不可以**有 AWS_ENDPOINT_URL（那是 pytest 的死埠專用）
grep -c "^AWS_ENDPOINT_URL" .env
# 預期印出 0

# ③ 真的連得到 S3 與 SQS（Phase 84／85 寫的檢查腳本）
python scripts/aws_check.py s3 sqs
# 預期兩行都印 OK

# ④ 雲端看圖的模型名有設（.env 的 OLLAMA_CLOUD_VLM_MODEL；沒設就會用 VLM_MODEL 的值，
#    而本機那顆是 MLX 標籤 gemma4:e2b——雲端沒有那個 tag，會 404）
grep -c "^OLLAMA_CLOUD_VLM_MODEL=." .env
# 預期印出 1
```

> ⚠️ **絕對不要同時跑兩份 pytest**（會互相 `TRUNCATE` 測試庫，症狀是大量看似隨機的
> 404 與 `TypeError: 'NoneType' object is not subscriptable`）。

---

## 3. 範圍

### 做

1. `app/workers/cloud_worker.py` 加四樣東西（Phase 87 寫的函式**一個字都不改**）：
   - 兩個模組常數 `LONG_POLL_SECONDS = 20`、`RECEIVE_ERROR_BACKOFF_SECONDS = 5`
   - `_把log印到終端機()`（比照 `app/main.py` 掛 handler）
   - `_接住停止訊號()`（SIGTERM／SIGINT → 旗標；回傳「該停了嗎」的函式）
   - `run_forever(mailbox, vlm, *, should_stop)` 與 `main()`，以及 `if __name__ == "__main__":`
2. `tests/unit/test_cloud_worker_unit.py` 追加 5 顆（主迴圈那一組）。
3. **人工端到端**（丁段驗收）：兩個終端機、真 S3／真 SQS／真 Ollama Cloud，
   非敏感走雲端、敏感留本機、Ctrl+C 優雅停。
4. `LAUNCH.md` 新增第 12 節 "Cloud worker on the Mac"（**英文**）。
5. `CLAUDE.md` 指令區新增對應的繁中小段。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 多執行緒／`asyncio`／一次拿多則訊息 | EC2 是 t4g.small（2 vCPU、2 GB）。看圖的時間全花在等 ollama.com 回覆，並行只會讓失敗變難查。一次一則，做完再拿下一則 |
| 健康檢查端點、metrics、Prometheus | design6 D11：工人**不開任何連接埠**。要看它活著沒，就看 log（`docker logs`／SSM） |
| Celery 的 `autoretry`、或自己寫重試佇列 | 重試已經有兩層：看圖 3 次（`process_job_message` 內部）＋ SQS 的可見度逾時（900 秒後整則重來）。第三層只會讓同一張圖被看六次 |
| 把 `process_job_message()` 改成「不丟例外」 | 丟例外＝訊息不刪＝900 秒後自動重來。自己吞掉反而會出現「訊息刪了但事情沒做」 |
| 建 EC2、寫 systemd、改 `Dockerfile` | Phase 90（映像）、91（網路與 IAM）、92（真機）。**★G2 之前不准開機器** |
| 幫工人加 CLI 參數（`--queue`、`--once`…） | 設定一律走 `.env` → `config`。多一種輸入就多一種「兩邊設定不一樣」的壞法 |
| 把 `CLOUD_ROUTE=assume` 留在 `.env` 當日常設定 | 總覽 §10 追認項 l：`assume` 不做探測，工人沒開時會傻傻送出、等到逾時才 fallback（每張慢 5 分鐘）。日常一律 `off`，戊之後才是 `ec2` |
| 在文件裡寫出 bucket 名、佇列 URL、access key、實例 ID | 總覽 §7 鐵律 10：文件只寫變數名。指令一律用 `$S3_BUCKET` 這種寫法 |
| 動 `compose.yaml` 加第五個服務跑工人 | 總覽 §7 鐵律 11：本增量 `compose.yaml` 零改動。丁段用 `python -m` 手動跑，戊段用 EC2 |

---

## 4. 實作步驟

> 🧪 **順序採 TDD（先紅再綠）**：步驟 1 寫**會紅**的 5 顆 → 步驟 2 跑它看到紅 →
> 步驟 3 寫實作 → 步驟 4 轉綠 → 步驟 5 全量回歸與 ruff →
> 步驟 6 **人工端到端**（丁段驗收）→ 步驟 7〜8 文件 → 步驟 9 commit。

### - [ ] 步驟 1：先寫會紅的 5 顆測試

打開 `tests/unit/test_cloud_worker_unit.py`（Phase 87 建的），做兩件事：

**① 檔案最上面的 import 區改成下面這樣**（比 Phase 87 多了 `import logging` 與
`MailboxMessage` 兩行，其餘一字不變。**位置要對**——`ruff check` 的 I001 會管排序：
標準函式庫一組、自家模組一組，各自照字母排）：

```python
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from app.core import config
from app.services.cloud_ingest import MailboxMessage
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.fakes import FakeMailbox, FakeVLM, ScriptedVLM, make_pdf_bytes, make_png_bytes
```

（`MailboxMessage` 在這裡是**測試**要用的——下面的 helper `一則訊息()` 會 new 它；
工人本體只在 `TYPE_CHECKING` 底下用它。它**定義在 `cloud_ingest.py`**（Phase 77），
`aws_mailbox.py` 只是 import 它來用，所以一律回到定義的地方拿，不要繞道。）

**② 在檔案最後面**（`test_工人不import資料庫與Celery與Redis` 之後）加上這一整段：

```python
# ---------------- 主迴圈（Phase 88）----------------


class 腳本信箱:
    """只提供主迴圈用得到的那一個方法：receive_job()。

    腳本裡每一項可以是三種東西：
      None            → 這一輪長輪詢沒收到東西（佇列空著，這是常態）
      MailboxMessage  → 收到一則
      Exception 的實例 → 這一次 receive 就把它丟出去（模擬憑證過期、網路斷）
    腳本演完之後一律回 None——什麼時候停是 should_stop 決定的，不靠腳本演完。

    為什麼不用 FakeMailbox：那顆假件的 receive_job 是「佇列空了就回 None」，
    排不出「第一次丟例外、第二次才給訊息」這種劇本。而主迴圈要驗的正是那件事。
    """

    def __init__(self, 腳本: list) -> None:
        self.腳本 = list(腳本)
        self.receive_calls = 0
        self.last_wait_seconds: int | None = None

    def receive_job(self, wait_seconds: int):
        self.receive_calls += 1
        self.last_wait_seconds = wait_seconds
        if not self.腳本:
            return None
        項目 = self.腳本.pop(0)
        if isinstance(項目, Exception):
            raise 項目
        return 項目


def 一則訊息(job_id: str = "job-1") -> MailboxMessage:
    """做一則長得跟 SQS 收到的一模一樣的訊息（三個欄位）。"""
    return MailboxMessage(
        job_id=job_id,
        s3_key=f"documents/{job_id}/input.png",
        receipt_handle=f"rh-{job_id}",
    )


def 跑幾輪就停(次數: int):
    """回一個 should_stop：前 N 次回 False（＝再跑一輪），之後永遠 True。

    正式執行時 should_stop 是訊號旗標；測試用這個，所以整組迴圈測試是毫秒等級，
    不必真的送訊號、也不必等 20 秒的長輪詢。
    """
    剩下 = {"次數": 次數}

    def should_stop() -> bool:
        if 剩下["次數"] <= 0:
            return True
        剩下["次數"] -= 1
        return False

    return should_stop


def test_主迴圈收到None時繼續等下一則(monkeypatch):
    """佇列空著是**常態**（一天可能只上傳幾張），不可以當成錯誤或直接退出。"""
    處理過的 = []
    monkeypatch.setattr(
        cloud_worker, "process_job_message", lambda 信箱, 訊息, 看圖: 處理過的.append(訊息)
    )
    信箱 = 腳本信箱([None, None, 一則訊息()])

    cloud_worker.run_forever(信箱, FakeVLM(收據理解), should_stop=跑幾輪就停(3))

    assert 信箱.receive_calls == 3, "空手而回時要繼續跑下一圈"
    assert [訊息.job_id for 訊息 in 處理過的] == ["job-1"]
    # 長輪詢：一定要帶 20 秒（AWS 上限）。帶 0 的話會變成短輪詢，一直空轉打 API
    assert 信箱.last_wait_seconds == cloud_worker.LONG_POLL_SECONDS == 20


def test_主迴圈收到訊息就呼叫process_job_message(monkeypatch):
    """迴圈自己不做任何判斷——訊息原封不動、連同信箱與看圖客戶端一起交出去。"""
    收到的 = []
    monkeypatch.setattr(
        cloud_worker,
        "process_job_message",
        lambda 信箱, 訊息, 看圖: 收到的.append((信箱, 訊息, 看圖)),
    )
    信箱 = 腳本信箱([一則訊息("job-9")])
    看圖 = FakeVLM(收據理解)

    cloud_worker.run_forever(信箱, 看圖, should_stop=跑幾輪就停(1))

    assert len(收到的) == 1
    傳進去的信箱, 傳進去的訊息, 傳進去的看圖 = 收到的[0]
    assert 傳進去的信箱 is 信箱
    assert 傳進去的訊息.job_id == "job-9"
    assert 傳進去的看圖 is 看圖, "看圖客戶端要原樣傳進去，不可以在迴圈裡自己建一個"


def test_停止旗標讓主迴圈退出():
    """收到 SIGTERM／Ctrl+C 之後，**下一圈開頭**就要退出——連要訊息都不要再要一次。

    先要了訊息才檢查旗標的話，會多拿一則出來卻沒人做：它會隱形 900 秒才回到佇列，
    看起來就像「有一張照片卡住了十五分鐘」。
    """
    信箱 = 腳本信箱([一則訊息()])

    cloud_worker.run_forever(信箱, FakeVLM(收據理解), should_stop=lambda: True)

    assert 信箱.receive_calls == 0, "已經被要求停止就不該再去要訊息"


def test_單次例外不會讓主迴圈死掉(monkeypatch, caplog):
    """一則壞掉不可以害死整支工人——那台機器沒有人看著，死了就是整條路默默停擺。

    兩種例外都要活下來：向佇列要訊息時炸掉、處理某一則時炸掉。
    處理失敗的那一則**刻意不刪**，它會在可見度逾時（900 秒）之後自己回來重做。
    """
    caplog.set_level(logging.INFO)
    # backoff 平常是 5 秒，測試裡不要真的睡
    monkeypatch.setattr(cloud_worker, "RECEIVE_ERROR_BACKOFF_SECONDS", 0)
    處理過的 = []

    def 會爆一次的處理(信箱, 訊息, 看圖):
        if 訊息.job_id == "job-炸":
            raise RuntimeError("S3 突然不通")
        處理過的.append(訊息.job_id)

    monkeypatch.setattr(cloud_worker, "process_job_message", 會爆一次的處理)
    信箱 = 腳本信箱([RuntimeError("SQS 憑證過期"), 一則訊息("job-炸"), 一則訊息("job-好")])

    cloud_worker.run_forever(信箱, FakeVLM(收據理解), should_stop=跑幾輪就停(3))

    assert 處理過的 == ["job-好"], "前兩輪都爆了，但迴圈要活著跑到第三輪"
    assert 信箱.receive_calls == 3
    炸掉的log = [紀錄 for 紀錄 in caplog.records if 紀錄.levelno >= logging.ERROR]
    assert len(炸掉的log) == 2, "兩次失敗都要留下 log，不可以安靜地吞掉"


def test_啟動時印出version與region與bucket(monkeypatch, caplog):
    """啟動行是**唯一**能證明「EC2 上跑的是哪一版映像」的東西（design6 D16、Demo 3）。

    三個欄位缺一不可：
      version ← WORKER_VERSION（build 時由 ARG GIT_SHA 烙進去，Phase 90）
      region  ← 打錯區的話 S3 與 SQS 會「查無此桶／此佇列」
      bucket  ← 對到別的 bucket 是最難查的一種設定錯
    """
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config, "WORKER_VERSION", "abc1234")
    monkeypatch.setattr(config, "AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(config, "S3_BUCKET", "personaldocai-mailbox-測試")

    cloud_worker.run_forever(腳本信箱([]), FakeVLM(收據理解), should_stop=lambda: True)

    啟動行 = [訊息 for 訊息 in caplog.messages if 訊息.startswith("cloud_worker 啟動 ")]
    assert len(啟動行) == 1, f"預期恰好一行啟動 log，實得：{caplog.messages}"
    assert "version=abc1234" in 啟動行[0]
    assert "region=ap-northeast-1" in 啟動行[0]
    assert "bucket=personaldocai-mailbox-測試" in 啟動行[0]
```

### - [ ] 步驟 2：跑它，親眼看到紅

```bash
pytest tests/unit/test_cloud_worker_unit.py -q
```

預期：**5 顆紅、10 顆綠**，紅的錯誤字樣是

```text
AttributeError: module 'app.workers.cloud_worker' has no attribute 'run_forever'
```

（`LONG_POLL_SECONDS`／`RECEIVE_ERROR_BACKOFF_SECONDS` 也還不存在，
錯誤訊息可能是這兩個其中之一，都算正確的紅。）

### - [ ] 步驟 3：寫實作

打開 `app/workers/cloud_worker.py`。**Phase 87 寫的七個函式一個字都不改**，
只動 import 區、加兩個常數、在檔案最後面加三個函式與一個 `__main__` 區塊。

**① 檔案最上面的 import 區，本 phase 結束時的完整長相：**

```python
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
    # 單元測試（假信箱）因此完全不必碰 boto3。
    # ★ CloudMailbox（Phase 77，總覽 §2.4.1）一份 Protocol 涵蓋本機端＋工人端的全部操作：
    #   工人用到的 receive_job()／delete_job_message() 就在裡面（註記「工人端（87）」），
    #   AwsMailbox 與 FakeMailbox 兩個實作也都有，所以不必另立一個工人專用的 Protocol。
    # ⚠ MailboxMessage 也跟 cloud_ingest 要（它就**定義在那裡**，Phase 77）。
    #   aws_mailbox.py 是 import 它來用的，繞道那邊拿雖然也拿得到，
    #   但會讓「這個名字到底住在哪」變得不明確——一律回到定義的地方拿。
    from app.services.cloud_ingest import CloudMailbox, MailboxMessage
```

（比 Phase 87 多了 `signal`、`time` 與 `typing.Callable` 三個標準函式庫的名字，
其餘（含 `TYPE_CHECKING` 底下那幾行註解）一字不變。`app.*` 的 import 名單**完全沒有變**
——那顆 `ast` 掃碼測試照樣綠。）

**② 兩個模組常數**（接在 Phase 87 的 `PDF_PAGE_CONTENT_TYPE` 後面）：

```python
# 向 jobs 佇列要訊息時，「沒有的話你先幫我等最多幾秒」。
# 20 是 AWS 的上限（長輪詢）。改小＝空手而回的次數變多＝ReceiveMessage 的請求數變多，
# 而 SQS 是按請求數計費的；改成 0 就是短輪詢，等於全速空轉打 API。
LONG_POLL_SECONDS = 20

# receive 本身失敗（憑證過期、網路斷、SQS 暫時性錯誤）時，先睡幾秒再試。
# 沒有它的話迴圈會變成「全速空轉打一個一定會失敗的 API」——CPU 100%、帳單也不好看。
RECEIVE_ERROR_BACKOFF_SECONDS = 5
```

**③ 檔案最後面加這三個函式與 `__main__` 區塊（完整內容）：**

```python
def _把log印到終端機() -> None:
    """讓 app.* 的 INFO log 出現在終端機（寫法與 app/main.py 完全一樣）。

    工人是**獨立行程**：沒有 uvicorn、也沒有 Celery 幫忙配置 logging。
    什麼都不做的話，Python 的最後防線只會印 WARNING 以上——
    啟動行、每張圖的 kind=vlm 計時、「result 已放好」全都是 INFO，一行都看不到。
    在 EC2 上這尤其致命：那台機器 inbound 全關，你只能靠 docker logs 看它在幹嘛。

    ★ logger 名稱是 "app"（不是 __name__）：本模組的 logger 叫
      app.workers.cloud_worker，掛在 "app" 上就一起收得到，
      連 vlm_service 與 ai_timing 的 log 也一起有——與 app/main.py 同一個道理。
    """
    工人logger = logging.getLogger("app")
    if not 工人logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        工人logger.addHandler(handler)
        工人logger.setLevel(logging.INFO)


def _接住停止訊號() -> Callable[[], bool]:
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
    狀態 = {"要停了": False}

    def 處理(signum, frame) -> None:
        if 狀態["要停了"]:
            # 第二次：使用者等不及了。先還原成系統預設的處理方式（＝直接結束行程），
            # 再把同一個訊號補發給自己——這一行之後就不會再回來了。
            logger.warning("再收到一次停止訊號，直接中斷")
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)
            return
        狀態["要停了"] = True
        logger.info("cloud_worker 收到停止訊號 signal=%s，做完手上這一則就退出", signum)

    signal.signal(signal.SIGTERM, 處理)
    signal.signal(signal.SIGINT, 處理)
    return lambda: 狀態["要停了"]


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
    logger.info(
        "cloud_worker 啟動 version=%s region=%s bucket=%s",
        config.WORKER_VERSION,
        config.AWS_REGION,
        config.S3_BUCKET,
    )
    while not should_stop():
        try:
            message = mailbox.receive_job(LONG_POLL_SECONDS)
        except Exception:
            logger.exception("向 jobs 佇列要訊息失敗，%d 秒後再試", RECEIVE_ERROR_BACKOFF_SECONDS)
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
      不會把 AWS SDK 一起拉進來，單元測試完全不必碰 boto3。
      理由與 dependencies.get_task_dispatcher() 相同。

    ★ 看圖固定用 OllamaCloudVLM（design6 D12）：EC2 沒有 GPU、也不裝本機 Ollama。
      這裡**不看** config.AI_BACKEND——那顆頁首開關管的是本機那條路（D6），
      而且它是 web 行程記憶體裡的狀態，這個行程根本讀不到。
    """
    _把log印到終端機()

    缺少 = [
        名稱
        for 名稱, 值 in (
            ("S3_BUCKET", config.S3_BUCKET),
            ("SQS_JOBS_QUEUE_URL", config.SQS_JOBS_QUEUE_URL),
            ("SQS_RESULTS_QUEUE_URL", config.SQS_RESULTS_QUEUE_URL),
            ("OLLAMA_API_KEY", config.OLLAMA_API_KEY),
        )
        if not 值
    ]
    if 缺少:
        # 早點、大聲地壞掉。少了佇列 URL 的話 boto3 會丟一句看不懂的 ParamValidationError；
        # 少了 OLLAMA_API_KEY 更慘——每張圖都 401、看三次、然後標成「看不懂」，
        # 從 log 上看起來像「AI 變笨了」。
        raise SystemExit(f"cloud_worker 無法啟動：.env 少了這些設定 {'、'.join(缺少)}")

    from app.services.aws_mailbox import AwsMailbox

    mailbox = AwsMailbox(
        bucket=config.S3_BUCKET,
        jobs_queue_url=config.SQS_JOBS_QUEUE_URL,
        results_queue_url=config.SQS_RESULTS_QUEUE_URL,
        region=config.AWS_REGION,
    )
    run_forever(mailbox, vlm_service.OllamaCloudVLM(), should_stop=_接住停止訊號())


if __name__ == "__main__":
    # `python -m app.workers.cloud_worker` 會執行到這裡。
    # ⚠ 一定要用 -m（模組路徑），不要 `python app/workers/cloud_worker.py`：
    #   後者會把 app/workers/ 當成 sys.path[0]，`from app.core import config`
    #   立刻 ModuleNotFoundError。
    main()
```

### - [ ] 步驟 4：跑新測試，看它轉綠

```bash
pytest tests/unit/test_cloud_worker_unit.py -v
```

預期最後一行：`15 passed`（Phase 87 的 10 顆 ＋ 本 phase 的 5 顆）。

### - [ ] 步驟 5：全量回歸與 ruff

```bash
pytest -q
```

預期：**開工基線 ＋ 5**（＝651），全綠、0 skipped。

```bash
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
```

預期：顆數與上一行相同（零外部依賴實證）。

```bash
ruff format --check app tests scripts && ruff check app tests scripts
```

預期兩句都乾淨。

### - [ ] 步驟 6：人工端到端（**丁段的驗收**，真 S3／真 SQS／真 Ollama Cloud）

```text
┌─ ⚠️ 開始之前先讀這三句 ────────────────────────────────────────────────
│
│ 1. 這一節會**真的用到 AWS**（S3 的 PutObject／GetObject／DeleteObject、
│    SQS 的 Send／Receive／Delete）。這些呼叫在 Free plan 的點數下幾乎不花錢
│    （每則訊息、每個物件都是千分之一美分等級），但它們是真的。
│    **不會**開任何 EC2——那要等 ★G2 之後。
│ 2. 全程只會有**一張測試照片**進入雲端管線。做完 S3 應該是空的、兩條佇列都是 0 則。
│ 3. **收工一定要把 .env 的 CLOUD_ROUTE 改回 off 並 restart worker。**
│    忘了改的話，之後每一張非敏感照片都會先送去 S3、等到逾時才 fallback
│    ——照片還是會入庫，但每張慢 5 分鐘（見 §7 陷阱 3）。
└────────────────────────────────────────────────────────────────────────
```

- [ ] **① 先把逾時調短**（萬一哪裡卡住，不必等 5 分鐘）。編輯 `.env`：

```ini
CLOUD_ROUTE=assume
CLOUD_RESULT_TIMEOUT_SECONDS=30
```

  `assume` ＝「假設遠端開著、不做探測」（總覽 §2.4.2）。
  現在還沒有 `Ec2Probe`（那是 Phase 89），所以只能用它。

- [ ] **② 讓本機那條路吃到新設定。** 只需要重啟 `worker` 容器——
      `get_cloud_route()` 只有 Celery 任務會呼叫，`app` 那個行程根本用不到它：

```bash
cd /Users/linjunting/personalDocAI
docker compose -f compose.yaml restart worker
# 開發模式的話：docker compose -f compose.yaml -f compose.dev.yaml restart worker
docker compose ps --no-trunc | grep worker      # 確認它回來了
```

- [ ] **③ 終端機 A：把工人跑起來。**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python -m app.workers.cloud_worker
```

  ⚠ 這個視窗**不要** `set -a; . ./.env`、也**不要** `unset`：工人是自己讀 `.env` 的，
  而且它要的正是 `.env` 裡那把 `personaldocai-mac` 的 key（Phase 82 給程式用的最小權限身分）。
  「載入 `.env` 再 `unset`」只給**打 `aws` 指令的那個視窗**用——那個視窗要用的是
  `~/.aws` 裡 `personaldocai-admin` 的 default profile。兩種身分別混在同一個視窗。

  預期**立刻**印出一行（然後就安靜地等訊息，那是對的）：

```text
INFO:     cloud_worker 啟動 version=dev region=ap-northeast-1 bucket=personaldocai-mailbox-XXXXXX
```

  `version=dev` 是正確的：`WORKER_VERSION` 的預設值就是 `dev`，
  要等 Phase 90 把它 build 進映像才會變成 git 短碼。

  **沒印出來、而是噴錯的話對照這張表：**

  | 錯誤訊息 | 原因 | 怎麼辦 |
  |---|---|---|
  | `cloud_worker 無法啟動：.env 少了這些設定 …` | `.env` 少了那幾個變數 | 回 §2 的檢查清單 |
  | `ModuleNotFoundError: No module named 'app'` | 用了 `python app/workers/cloud_worker.py`，**或**不是在專案根目錄下 `python -m`（`app` 沒裝進 venv，`-m` 只把目前目錄放進 `sys.path`） | `cd /Users/linjunting/personalDocAI` 之後一定用 `python -m app.workers.cloud_worker` |
  | 啟動行印出來了，接著**每 5 秒重複一段** `向 jobs 佇列要訊息失敗` 的 traceback，裡面是 `NoCredentialsError`／`InvalidClientTokenId` | `.env` 的 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` 缺了或值打錯（Phase 82 那把 `personaldocai-mac` 的 key）。工人**不會死**——這是刻意的（EC2 上憑證暫時失效時它要撐著），所以症狀是一直重試 | Ctrl+C 停掉、修好 `.env` 再跑。`.env` 是**從 `app/core/` 往上找**的，跟你在哪個目錄啟動無關 |
  | `EndpointConnectionError: …127.0.0.1:9` | `.env` 裡有 `AWS_ENDPOINT_URL`（那是 pytest 專用的死埠） | 把那一行刪掉 |

- [ ] **④ 終端機 B：看本機 worker 容器的 log。**

```bash
docker compose logs -f worker
```

  `-f` ＝跟著看；`Ctrl+C` 只離開 log，容器繼續跑。

- [ ] **⑤ 準備一張檔名明確非敏感的圖。** 檔名**很重要**——規則版閘門只看檔名
      （總覽 §10 追認項 f）。把任何一張 PNG 複製成 `receipt-test.png`：

```bash
cp <任意一張圖.png> ~/Desktop/receipt-test.png
```

- [ ] **⑥ 上傳（第三個終端機視窗，或用瀏覽器）：**

```bash
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@$HOME/Desktop/receipt-test.png" \
  https://127.0.0.1:8000/photos
```

  預期最後一行是 `202`，body 恰三鍵：

```json
{"job_id": "…32 個十六進位字…", "filename": "receipt-test.png", "content_type": "image/png"}
```

- [ ] **⑦ 終端機 A（工人）應該在幾秒內動起來：**

```text
INFO:     AI 開始 kind=vlm backend=cloud model=gemma4
INFO:     AI 結束 kind=vlm backend=cloud model=gemma4 elapsed_s=2.1 ok=true understood=true text_chars=…
INFO:     job <job_id>：result.json 已放好、results 已送出（worker_version=dev）
```

  三個重點：
  - `backend=cloud` ← 工人固定走 Ollama Cloud（D12），與頁首那顆開關無關
  - `model=gemma4` ← 就是 `.env` 的 `OLLAMA_CLOUD_VLM_MODEL`；印出 `gemma4:e2b` 這種帶本機 tag 的名字
    ＝ §2 的檢查 ④ 沒過，雲端會 404、三次都「看不懂」（§7 陷阱 8）
  - `elapsed_s` 大約 **1〜3 秒**（雲端；本機 gemma4 是 64〜88 秒）
  - 沒有任何 `kind=embed` ← 向量不在這裡算（D13）

- [ ] **⑧ 終端機 B（本機 worker 容器）應該接著動：**

```text
INFO:     job <job_id> route=cloud verdict=NON_SENSITIVE
INFO:     job <job_id> 已送去雲端：documents/<job_id>/input.png
INFO:     AI 開始 kind=embed backend=local model=bge-m3
INFO:     AI 結束 kind=embed backend=local model=bge-m3 elapsed_s=0.4 ok=true
INFO:     job <job_id> 雲端結果已入庫：photo_id=<n>
```

  （`route=cloud` 那一行是 Phase 78／79 留的字樣，總覽 §5.2 的 Demo 2 也是抓它。
  **這裡不該出現任何 `fallback=` 的行**——有的話代表雲端那條路沒走通，往下看 §7 陷阱。
  ⚠ 雲端路**不會**印本機路那一行「入庫完成」（它在 `_run_image_job` 裡）；
  雲端路自己的完成訊號是最後那行 **`雲端結果已入庫`**（Phase 79 的「用結果落庫」收尾時印，
  PDF 版是「N 頁中 M 頁成功」）。用 `docker compose logs worker | grep 雲端結果已入庫` 找得到。
  除了這一行，「做完了」還要靠下面這四樣證據互相印證。）

  然後四件事都要成立（**在第三個視窗做，不要在終端機 A**——終端機 A 是工人，
  它要的正是 `.env` 那把 key，別在那裡 unset）：

```bash
set -a; . ./.env; set +a          # 讓 .env 的變數進環境（值不要印出來）
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
# ↑ 不能省：.env 那把是程式用的最小權限 key（沒有 sqs:PurgeQueue、沒有 s3:CreateBucket 這類管理動作），
#   環境變數又蓋過 ~/.aws，不 unset 的話 CLI 會默默改用它——list-objects-v2 雖然跑得過，
#   ⑪ 的 purge-queue 就 AccessDenied（Phase 82 記過）

# 這筆 job 已經從進度清單消失（成功＝job 被刪掉；失敗會留一列 status=failed）
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
# 預期：jobs 陣列裡沒有剛剛那個 job_id，pending_count 比上傳前多 1

# 寄物櫃應該是空的（三個物件都被本機 cleanup 刪掉了）
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'Contents[].Key' --output text
# 預期：印 None（＝一個物件都沒有；--output text 對空結果就是印這個字），
#       或只剩上一輪煙霧的殘骸（Lifecycle 兩天內會清掉）

# 兩條佇列都空了
aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages --region "$AWS_REGION"
aws sqs get-queue-attributes --queue-url "$SQS_RESULTS_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages --region "$AWS_REGION"
# 兩個都預期 "ApproximateNumberOfMessages": "0"

# 照片真的入庫了
psql -d PersonalDocAI -c "select id, left(text, 40) from photo order by id desc limit 1"
```

  最後用瀏覽器開 `https://127.0.0.1:8000/ui/pending.html`：
  剛剛那張要在待決定牆上，頂欄的「待決定（N）」比上傳前多 1。

- [ ] **⑨ 敏感檔測試：工人應該完全沒反應。**

```bash
cp <任意一張圖.png> ~/Desktop/身分證.png
curl -k -s -w '\n%{http_code}\n' \
  -F "file=@$HOME/Desktop/身分證.png" \
  https://127.0.0.1:8000/photos
```

  預期：
  - `202`（與上一張一模一樣——使用者完全感覺不到差別）
  - **終端機 A（工人）一行新的 log 都沒有**
  - 終端機 B 有 `route=local verdict=SENSITIVE`
  - S3 沒有任何新物件（再跑一次上面那個 `list-objects-v2`）
  - 照片照樣進待決定（本機看圖；本機 gemma4 要 64〜88 秒，想快一點就先把
    **頁首那顆 AI 開關**切到雲端——那是另一扇門，與 Privacy Gate 無關，design6 D6）

- [ ] **⑩ 終端機 A 按 Ctrl+C，看它優雅停止。**

```text
INFO:     cloud_worker 收到停止訊號 signal=2，做完手上這一則就退出
INFO:     cloud_worker 已停止 version=dev
```

  ⚠ **最多要等 20 秒**才會看到第二行——那是長輪詢還沒回來（不是當掉）。
  等不及就再按一次 Ctrl+C，會直接中斷。

- [ ] **⑪ 收工：把設定改回去。** 編輯 `.env`：

```ini
CLOUD_ROUTE=off
```

  （`CLOUD_RESULT_TIMEOUT_SECONDS` 留 30 或改回 300 都可以，`off` 模式下用不到它。）

```bash
docker compose -f compose.yaml restart worker
docker compose logs --tail=5 worker      # 確認它起來了
```

  順手確認兩條佇列都沒有殘留（有的話清掉；**每條佇列的 `purge-queue` 60 秒內只能做一次**）：

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY      # purge-queue 不在 .env 那把 key 的權限裡
for url in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  aws sqs get-queue-attributes --queue-url "$url" \
    --attribute-names ApproximateNumberOfMessages --region "$AWS_REGION"
done
# 哪一條不是 "0" 就清哪一條：
aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"
aws sqs purge-queue --queue-url "$SQS_RESULTS_QUEUE_URL" --region "$AWS_REGION"
```

### - [ ] 步驟 7：`LAUNCH.md` 新增第 12 節（**英文**）

`LAUNCH.md` 自 2026-08-27 起是**英文**（`README.md` 也是），改它一律用英文。

**① 在檔案最上面的 `## Contents` 清單最後加一行：**

```markdown
12. [Cloud worker on the Mac](#12-cloud-worker-on-the-mac)
```

**② 在 `## 11. Never do these` 那一節的結尾、`## Appendix: current architecture` 之前**
插入下面這一整節。

> 為什麼放在第 11 節後面而不是插進中間：插中間要把 11 節之後的編號全部往後推，
> 而檔案裡（以及 `README.md`、`CLAUDE.md`）到處都是 `#9-monitoring-and-logs`
> 這種錨點連結，全部會斷。多一節接在後面，只要動兩個地方。

````markdown
## 12. Cloud worker on the Mac

The **cloud worker** is the process that looks at photos on the *other* side of the mailbox.
It is not the Celery worker container — that one stays on this Mac and writes to the database.
The cloud worker only looks at images and writes one `result.json` back into S3.

From increment six it can run in two places: on this Mac (this section) or on an EC2
instance (added later). Both run exactly the same code.

**You only need this when you want to exercise the cloud pipeline by hand.**
Day to day it should not be running, and `CLOUD_ROUTE` in `.env` should be `off`.

### What has to be in place

- `.env` has values for `S3_BUCKET`, `SQS_JOBS_QUEUE_URL`, `SQS_RESULTS_QUEUE_URL`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `OLLAMA_API_KEY` and
  `OLLAMA_CLOUD_VLM_MODEL` — and **no** `AWS_ENDPOINT_URL` (that one is only for pytest,
  where it points at a dead port so nothing can reach the internet).
- The bucket and both queues exist:

```bash
python scripts/aws_check.py s3 sqs      # both lines must print OK
```

### Run it (terminal A)

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python -m app.workers.cloud_worker
```

Do **not** source `.env` or `unset` anything in this terminal: the worker reads `.env` by
itself and needs the `personaldocai-mac` key that lives there. Sourcing `.env` and then
`unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` is only for the shell where you type `aws`
commands — that shell should be on the `personaldocai-admin` profile from `~/.aws`.

The first line tells you which build, which region and which bucket it is talking to:

```text
INFO:     cloud_worker 啟動 version=dev region=ap-northeast-1 bucket=...
```

`version=dev` is correct here — the real git sha is only baked in when the image is built.

Use `python -m` (a module path), **not** `python app/workers/cloud_worker.py`: the second
form puts `app/workers/` on the import path and `from app.core import config` fails
immediately. It also has to be started **from the project root** — `app` is not installed
into the venv, so `python -m` only finds it because the current directory is on `sys.path`.
(`.env` is not the reason: `load_dotenv()` in `app/core/config.py` walks up from that file's
own directory, so the keys are found from anywhere.) If the worker starts but then repeats a
`NoCredentialsError` / `InvalidClientTokenId` traceback every 5 seconds, the AWS key in
`.env` is missing or wrong — the worker deliberately keeps retrying instead of dying; press
Ctrl+C, fix `.env`, start it again.

### Point the local side at it (terminal B)

```bash
# 1. In .env:   CLOUD_ROUTE=assume      ("assume the remote worker is up; do not probe")
#               CLOUD_RESULT_TIMEOUT_SECONDS=30    (optional, keeps mistakes short)
# 2. Only the worker container reads this setting (add -f compose.dev.yaml in dev mode):
docker compose -f compose.yaml restart worker
docker compose logs -f worker
```

Now upload a photo whose **file name** clearly reads as non-sensitive — the rule-based gate
only looks at the name, nothing else:

```bash
curl -k -s -w '\n%{http_code}\n' -F "file=@$HOME/Desktop/receipt-test.png" \
  https://127.0.0.1:8000/photos          # 202
```

What you should see:

| Where | What |
|---|---|
| terminal A (cloud worker) | `kind=vlm backend=cloud`, about 1–3 s, then `result.json 已放好` |
| terminal B (worker container) | `route=cloud verdict=NON_SENSITIVE`, then `kind=embed backend=local`, then `雲端結果已入庫：photo_id=<n>` (the cloud path's own completion line; `grep 雲端結果已入庫`) — and the job disappears from `GET /ingest-jobs` |
| S3 | empty again once it is done (the local side deletes all three objects) |
| both queues | `ApproximateNumberOfMessages` back to `0` |
| the app | the photo is on the pending wall, exactly as with any other upload |

A file named `身分證.png` (or `passport`, `salary`, …) never reaches the cloud worker at all:
terminal A stays silent, terminal B logs `route=local verdict=SENSITIVE`, and S3 gets nothing.
That is the whole point of the gate.

### Stop it

Press **Ctrl+C** in terminal A. It prints `收到停止訊號` and then finishes the message it is
holding before exiting, so it never leaves half a job behind. **This can take up to 20
seconds** — that is the SQS long poll finishing, not a hang. Press Ctrl+C again to cut it short.

### When you are done — this part is not optional

```bash
# In .env:   CLOUD_ROUTE=off
docker compose -f compose.yaml restart worker
```

If you leave `CLOUD_ROUTE=assume` behind with no worker running, every non-sensitive upload
will be pushed to S3 and then sit there until `CLOUD_RESULT_TIMEOUT_SECONDS` expires before
falling back to local processing. Nothing is lost — the photo still lands in the inbox — but
every one of them is several minutes slower, and the only clue is a `fallback=local
reason=result_timeout` line in the worker log.

Leftover queue messages from a smoke test:

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # so the CLI uses ~/.aws, not the app's key
aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages --region "$AWS_REGION"
aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"   # once per 60 s
```
````

### - [ ] 步驟 8：`CLAUDE.md` 指令區新增繁中小段

在 `CLAUDE.md` 的「指令」區塊，**接在 Phase 82 加的「AWS（增量六 Phase 82 起）」那一段之後、
「跑測試」那一段之前**，加入下面這一段（同一個 bash 區塊裡）：

```bash
# ── 雲端看圖工人（增量六 Phase 88；**平常不用開**）─────────────────────
# 它是「寄物櫃另一頭」那個看圖的人，跟 compose 裡那個 worker 容器完全是兩回事：
#   worker 容器      ＝ Celery，在這台 Mac 上，會寫資料庫、算向量
#   cloud_worker     ＝ 只看圖（Ollama Cloud），把 result.json 放回 S3，不碰資料庫
# 日常 .env 是 CLOUD_ROUTE=off，這支東西完全不會被用到，也不必開。
#
# 終端機 A：把工人跑起來（**一定要在專案根目錄**——app 沒裝進 venv，`python -m` 只認
#           目前目錄；.env 倒是從 app/core/ 往上找、在哪裡啟動都讀得到）
#           這個視窗**不要** source .env、也不要 unset：工人自己讀 .env，要的正是裡面那把
#           personaldocai-mac 的 key。「載入 .env 再 unset」只給打 aws 指令的視窗用（admin profile）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python -m app.workers.cloud_worker
#   預期第一行：cloud_worker 啟動 version=dev region=ap-northeast-1 bucket=…
#   ⚠ 一定要用 -m。python app/workers/cloud_worker.py 會 ModuleNotFoundError: No module named 'app'
#   Ctrl+C 停：先印「收到停止訊號」，**最多等 20 秒**（長輪詢還沒回來）才真的退出；
#              再按一次 Ctrl+C 會直接中斷
#
# 終端機 B：讓本機那條路真的把非敏感照片送出去
#   .env 改 CLOUD_ROUTE=assume（assume ＝假設遠端開著、不做探測；Phase 89 之後日常用 ec2）
#   順手把 CLOUD_RESULT_TIMEOUT_SECONDS 調成 30，出錯時不必等 5 分鐘
docker compose -f compose.yaml restart worker      # 只有 worker 會讀這個設定，app 不必動
docker compose logs -f worker                      # 看 route=／fallback=／kind=embed
#
# ⚠⚠ 收工一定要把 .env 改回 CLOUD_ROUTE=off，再 restart worker 一次。
#     忘了改＝之後每一張**非敏感**照片都會先送去 S3、等到 CLOUD_RESULT_TIMEOUT_SECONDS
#     逾時才 fallback 回本機。照片不會不見，但每張慢好幾分鐘，而且唯一的線索只有
#     worker log 裡那行 fallback=local reason=result_timeout。
#
# 敏感／不確定的照片（檔名有「身分證」「passport」這類字、或看不出來）**永遠不會**
# 進雲端管線，所以工人那一頭會完全沒反應——那是對的，不是壞了。
#
# 手動煙霧留下的殘訊息（每條佇列 60 秒只能清一次；在打 aws 指令的視窗做，不是終端機 A）：
#   set -a; . ./.env; set +a
#   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY    # .env 那把沒有 sqs:PurgeQueue（見上面 AWS 段）
#   aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"
```

### - [ ] 步驟 9：commit

```bash
cd /Users/linjunting/personalDocAI
git add app/workers/cloud_worker.py tests/unit/test_cloud_worker_unit.py \
        LAUNCH.md CLAUDE.md
git commit -m "feat: Phase 88 雲端工人主迴圈——run_forever() 長輪詢 20 秒、SIGTERM／SIGINT 優雅停、啟動 log 帶 version/region/bucket、python -m 進入點；Mac 端到端（真 S3／SQS／Ollama Cloud）通過，LAUNCH.md 加第 12 節、CLAUDE.md 指令區同步，+5 tests"
```

> 📌 **commit 節奏由產品負責人決定**（總覽 §7 鐵律 12）。未指示前不要自己 commit。

---

## 5. ASCII 圖

### 5.1 兩個終端機 ＋ AWS：一張非敏感照片的完整時序

```text
 你（第三個視窗）      本機 worker 容器        AWS（S3 ＋ 兩條佇列）  終端機 A
 curl POST /photos      （Celery）                                   cloud_worker
      │                      │                                           │
      │──── 202 ────────────▶│  ← 檔案落 data/staging/{job_id}.png       │ receive_job(20)
      │                      │     job 進 Redis、派工                    │  ⏳ 長輪詢
      │                      │                                           │
      │                 run_gated_ingest_job                             │
      │                      │                                           │
      │            ① 閘門 RuleGate("receipt-test.png")                   │
      │                      │  → NON_SENSITIVE                          │
      │            ② cloud.available()  → True（assume 模式不探測）      │
      │                      │                                           │
      │            ③ submit()：                                          │
      │                      │──── PutObject context.json ───────▶│      │
      │                      │──── PutObject input.png ──────────▶│      │
      │                      │──── SendMessage jobs {job_id,key} ▶│      │
      │                      │                                    │─────▶│ 收到！
      │            ④ wait_result()：ReceiveMessage results        │      │
      │                      │  ⏳ 長輪詢（最多 30 秒，我們調短的）│      │ ⑤ GetObject input
      │                      │                                    │◀─────│    GetObject context
      │                      │                                    │      │ ⑥ Ollama Cloud 看圖
      │                      │                                    │      │    kind=vlm backend=cloud
      │                      │                                    │      │    約 1〜3 秒
      │                      │                                    │◀─────│ ⑦ PutObject result.json
      │                      │                                    │◀─────│ ⑧ SendMessage results
      │                      │                                    │◀─────│ ⑨ DeleteMessage jobs
      │                      │◀─── results {job_id} ──────────────│      │ receive_job(20)
      │                      │──── GetObject result.json ────────▶│      │  ⏳ 等下一則
      │                      │                                           │
      │            ⑩ 本機 embed（bge-m3，kind=embed backend=local）      │
      │               INSERT photo ＋ 原圖 ＋ 縮圖                        │
      │               DeleteObjects ×3 ─────────────────────▶│（S3 清空） │
      │               刪 staging → 刪 job（＝成功）                       │
      │                      │                                           │
      ▼                      ▼                                           ▼
  待決定（N）+1        log: route=cloud                         log: result 已放好
                       log: kind=embed backend=local                  version=dev

 ⚠ 敏感檔（身分證.png）在 ① 就轉彎：route=local、直接 run_ingest_job，
   右邊兩欄（AWS 與終端機 A）**一個字都不會動**。
```

### 5.2 停止訊號為什麼只豎旗標

```text
┌── ✗ 在訊號處理函式裡直接收工 ────────────────────────────────────────────┐
│  你按 Ctrl+C 的那一瞬間，程式可能正停在**任何一行**：                     │
│    …剛 PutObject 完 result.json、還沒 SendMessage…                        │
│  在處理函式裡 sys.exit() ＝ 那一則的 results 沒送、jobs 訊息沒刪，        │
│  而 result.json 已經在 S3 上了 → 本機等到逾時 fallback → 重看一次圖。     │
└──────────────────────────────────────────────────────────────────────────┘

┌── ✓ 本 phase 的做法：只豎旗標，讓迴圈自己收工 ──────────────────────────┐
│                                                                          │
│   Ctrl+C ──▶ 處理()：狀態["要停了"] = True ＋ 印一行  ← 只做這兩件事      │
│                        │                                                 │
│   主迴圈仍在 receive_job(20) 裡等（最多 20 秒）                          │
│   或正在 process_job_message() 裡把手上這一則做完                        │
│                        │                                                 │
│                        ▼                                                 │
│   下一圈開頭：while not should_stop():  ← 看到旗標，直接離開迴圈          │
│                        │                                                 │
│                        ▼                                                 │
│   log「cloud_worker 已停止」→ 行程結束，**沒有任何半成品**               │
│                                                                          │
│   代價：按下去之後最多要等 20 秒。這就是為什麼要印那一行「收到停止訊號」  │
│         ——不然你會以為它當掉了，然後去按 Ctrl+C 兩三次。                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 驗收清單

- [ ] **`python -m` 跑得起來、啟動 log 三個欄位都在**：
      ```bash
      cd /Users/linjunting/personalDocAI && source .venv/bin/activate
      python -m app.workers.cloud_worker & WORKER_PID=$!
      sleep 3; kill -TERM "$WORKER_PID"; wait "$WORKER_PID"; echo "exit=$?"
      ```
      預期依序印出 `INFO:     cloud_worker 啟動 version=dev region=… bucket=…`、
      `INFO:     cloud_worker 收到停止訊號 signal=15，做完手上這一則就退出`、
      （最多 20 秒後）`INFO:     cloud_worker 已停止 version=dev`，最後 `exit=0`
      （macOS 沒有 `timeout` 指令，所以用「背景執行 ＋ `kill -TERM`」；這順便把 `docker stop`
      會走的 SIGTERM 路徑真的驗過一次——5 顆自動化測試只驗了 `should_stop` 旗標，沒驗訊號）
- [ ] **長輪詢是 20 秒**（AWS 上限；改小＝多花 API 請求費）：
      ```bash
      grep -n "^LONG_POLL_SECONDS" app/workers/cloud_worker.py
      ```
      預期 `LONG_POLL_SECONDS = 20`
- [ ] **兩個停止訊號都接了**：
      ```bash
      grep -n "signal.SIGTERM\|signal.SIGINT" app/workers/cloud_worker.py
      ```
      預期兩行（`docker stop` 送 SIGTERM、Ctrl+C 送 SIGINT，少接一個就會被硬殺）
- [ ] **看圖固定用雲端、不看頁首開關**（design6 D12／D6）：
      ```bash
      grep -c "vlm_service.OllamaCloudVLM()" app/workers/cloud_worker.py
      python -c "import ast,pathlib;t=ast.parse(pathlib.Path('app/workers/cloud_worker.py').read_text());print([n.lineno for n in ast.walk(t) if isinstance(n,ast.Attribute) and n.attr=='AI_BACKEND'])"
      ```
      預期第一句印 `1`（只在 `main()` 建一次）、第二句印 `[]`（**程式碼**裡沒有任何一處讀
      `config.AI_BACKEND`。用 `ast` 而不是 `grep`：註解與 docstring 裡有提到這個名字，grep 會誤中）
- [ ] **工人的 `app.*` import 名單沒有變**（那顆 `ast` 掃碼測試照樣綠）：
      ```bash
      pytest tests/unit/test_cloud_worker_unit.py -k import -v
      ```
      預期 `1 passed, 14 deselected`
- [ ] `pytest tests/unit/test_cloud_worker_unit.py -v` → `15 passed`
- [ ] **全量 `pytest -q` 全綠、0 skipped**，顆數 ＝ 開工基線 ＋ **5**（＝651）
- [ ] **三死埠零依賴實證**（顆數與上一條相同）：
      ```bash
      AWS_ENDPOINT_URL=http://127.0.0.1:9 \
      CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
      OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q
      ```
- [ ] **端點仍是 22**：
      ```bash
      python -c "
      from fastapi.testclient import TestClient
      from app.main import app
      paths = TestClient(app).get('/openapi.json').json()['paths']
      print(sum(len(ms) for ms in paths.values()))
      "
      ```
      預期印出 `22`
- [ ] **人工端到端（丁段驗收）全部走過**：非敏感走雲端入庫、敏感零 S3、
      Ctrl+C 優雅停、S3 空、兩條佇列 0 則（步驟 6 的 ⑦〜⑪）
- [ ] **`.env` 已改回 `CLOUD_ROUTE=off` 而且 worker 重啟過**：
      ```bash
      grep -n "^CLOUD_ROUTE=" .env
      docker compose logs --tail=5 worker
      ```
      預期 `CLOUD_ROUTE=off`
- [ ] **專案的 `data/` 沒有被弄髒**（`data/staging` 只該有正在跑的）：
      ```bash
      find data/staging -type f -mmin +60 2>/dev/null | head; echo "---"
      ```
      預期 `---` 之前沒有輸出
- [ ] **文件兩份都改了、而且 `LAUNCH.md` 是英文**：
      ```bash
      grep -n "12. Cloud worker on the Mac" LAUNCH.md
      grep -n "cloud_worker" CLAUDE.md | head -3
      ```
      預期 `LAUNCH.md` 有目錄那一行與章節標題各一；`CLAUDE.md` 指令區出現 `python -m app.workers.cloud_worker`
- [ ] **文件裡沒有寫出任何值**（總覽 §7 鐵律 10）：
      ```bash
      grep -nE "AKIA|amazonaws\.com/[0-9]{12}|personaldocai-mailbox-[0-9]" LAUNCH.md CLAUDE.md \
        || echo "OK：沒有機密或帳號 ID"
      ```
      預期印出 `OK：沒有機密或帳號 ID`
- [ ] **規格區一字未動**：`git status --short docs/spec/` → 零輸出
- [ ] `ruff format --check app tests scripts && ruff check app tests scripts` 兩句都乾淨

---

## 7. 常見陷阱

1. **不是從專案根目錄啟動工人 → `No module named 'app'`。**
   `app` 沒有裝進 venv（專案從來沒做 `pip install -e .`），所以 `python -m app.workers.cloud_worker`
   找得到 `app` 的唯一理由是「目前目錄在 `sys.path` 裡」。
   **症狀**：`ModuleNotFoundError: No module named 'app'`（跟陷阱 2 同一句錯誤、不同原因）。
   **正解**：`cd /Users/linjunting/personalDocAI` 再跑。
   ⚠ 不要把這個坑跟 `.env` 混在一起：`load_dotenv()` 是從 `app/core/config.py` **自己所在的目錄
   往上找** `.env`（python-dotenv 的預設行為，2026-08-31 實測從 `/tmp` 啟動也讀得到），
   所以 `NoCredentialsError` 從來不是「目錄不對」，而是 `.env` 裡的 AWS key 缺了或打錯
   （步驟 6 ③ 的表有這一列）。

2. **用 `python app/workers/cloud_worker.py` 而不是 `python -m …`。**
   前者把 `app/workers/` 當成搜尋路徑的第一個位置，於是 `from app.core import config`
   立刻 `ModuleNotFoundError: No module named 'app'`。
   **正解**：一律 `python -m app.workers.cloud_worker`（`-m` ＝用模組路徑執行）。

3. **收工忘了把 `CLOUD_ROUTE` 改回 `off`。**
   `assume` 的意思是「假設遠端開著」——它**不做任何探測**（總覽 §10 追認項 l）。
   工人關掉之後，每一張非敏感照片都會照樣被 PutObject 上去、然後在 results 佇列上
   空等到 `CLOUD_RESULT_TIMEOUT_SECONDS`（預設 300 秒）才 fallback。
   **症狀**：照片還是會入庫（fallback 有接住），但每張慢好幾分鐘，
   而且唯一的線索是 worker log 裡那行 `fallback=local reason=result_timeout`。
   **正解**：步驟 6 的 ⑪ 不可以跳過。Phase 89 之後日常應該用 `ec2`（會探測），
   `assume` 只留給除錯。

4. **改了 `.env` 卻沒重啟 worker 容器。**
   `config` 只在行程啟動時讀一次 `.env`。
   **症狀**：`.env` 明明寫著 `assume`，worker log 卻一直是 `fallback=local reason=remote_unavailable`
   （或根本沒有 `route=` 那一行）。
   **正解**：`docker compose -f compose.yaml restart worker`。
   （只要 restart `worker`：`get_cloud_route()` 只有 Celery 任務會呼叫，`app` 用不到。）

5. **以為 Ctrl+C 沒反應。**
   訊號只豎旗標，而迴圈可能正卡在最多 20 秒的長輪詢裡，所以**最多要等 20 秒**。
   那行「收到停止訊號」就是為了讓你知道它聽到了。等不及就**再按一次**：
   第二次會直接中斷（處理器還原成系統預設、訊號補發給自己，退出碼 130）——
   手上那一則可能沒刪，但它 900 秒後會自己回到佇列，不會不見。

6. **忘了掛 logging handler，然後以為工人卡住了。**
   工人是獨立行程，沒有 uvicorn 幫忙配置 logging。少了 `_把log印到終端機()`，
   Python 只印 WARNING 以上——啟動行、`kind=vlm` 計時、「result 已放好」全都是 INFO。
   **症狀**：跑起來之後終端機**一片空白**，看起來像當掉了。
   **正解**：`main()` 第一行就呼叫它（寫法與 `app/main.py` 完全一樣）。

7. **`.env` 裡留著 `AWS_ENDPOINT_URL`。**
   那是 pytest 第五道安全網用的死埠（`http://127.0.0.1:9`），
   留在 `.env` 的話工人一啟動就 `EndpointConnectionError`。
   **正解**：`.env` **永遠不要**有這一行；它只在跑「零依賴實證」時當成臨時環境變數。

8. **雲端模型名沒設，一直 404 卻看起來像「AI 變笨」。**
   本機的看圖模型在 `.env` 是 MLX 標籤（`VLM_MODEL=gemma4:e2b`），
   **雲端沒有那個 tag**。`OLLAMA_CLOUD_VLM_MODEL` 沒設的話會沿用本機那個名字 → 404 →
   看三次 → `understood=false`。
   **症狀**：每一張都「AI 看不懂」，但 log 的 `elapsed_s` 只有零點幾秒（真的在看圖不會這麼快）。
   **正解**：`.env` 明寫 `OLLAMA_CLOUD_VLM_MODEL=gemma4`（CLAUDE.md 已經記過這個坑）。

9. **上傳的檔名沒有帶關鍵字，結果整條雲端路都沒走到。**
   規則版閘門**只看檔名**（總覽 §10 追認項 f）。`IMG_4821.png` 是 `UNCERTAIN` ＝ 走本機，
   工人那一頭完全沒反應——那不是壞掉，是規格。
   **正解**：煙霧用的檔案一定要叫 `receipt-test.png` 這種名字。

10. **上傳與詢問同時打本機模型。**
    CLAUDE.md 記載 Phase 48 曾經把 db container 壓垮（postmaster 花 2 分鐘才殺得掉子行程）。
    **正解**：一次做一件事。真的想快，就把頁首那顆 AI 開關撥到雲端
    ——那是另一扇門，與 Privacy Gate 無關（design6 D6）。

11. **兩份 pytest 同時跑。**
    `reset_tables` 每顆測試都會 `TRUNCATE` 同一個測試庫，症狀是大量看似隨機的 404
    與 `TypeError: 'NoneType' object is not subscriptable`，每次紅的顆數還不一樣。

12. **`set -a; . ./.env; set +a` 之後 `aws` 指令忽然 `AccessDenied`。**
    `.env` 裡那把 `AWS_ACCESS_KEY_ID`／`AWS_SECRET_ACCESS_KEY` 是 Phase 82 給**程式**用的
    最小權限 key（`personaldocai-mac`：`documents/` 前綴的物件操作、bucket 的 `s3:ListBucket`、
    兩條佇列的程式端操作、`ec2:DescribeInstances`——**沒有** `sqs:PurgeQueue`、**沒有**
    `s3:CreateBucket` 這類「管理用」的動作），而環境變數的優先序**高於** `~/.aws` 裡 admin 的 profile。
    **症狀**：`aws sqs purge-queue` 回 `AccessDenied ... sqs:PurgeQueue`（`list-objects-v2` 與
    `get-queue-attributes` 用這把 key 其實跑得過，所以你會以為 CLI 沒問題、卡在 purge 才發現），
    但工人與 worker 容器都好好的。
    **正解**：載完 `.env` 馬上 `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`
    （步驟 6 的 ⑧／⑪ 都寫了），而且**只在第三個視窗做**——終端機 A 那支工人要的正是
    `.env` 那把 key，別在那裡 unset。

---

## 8. 完成後的專案狀態

`app/workers/cloud_worker.py` 從「一個只有測試會呼叫的函式」變成**一支能跑的程式**：
`python -m app.workers.cloud_worker` 就會啟動，印出一行帶 `version`／`region`／`bucket`
的啟動 log，然後一直向 jobs 佇列要訊息；`docker stop` 或 Ctrl+C 會讓它把手上這一則
做完才退出。單則失敗、甚至向佇列要訊息失敗，都不會讓它死掉。

**丁段（design6 §0 的「丁」那一列）到此驗收完畢**：本機送出 → 真 S3／真 SQS →
工人用真的 Ollama Cloud 看圖 → `result.json` → results → 本機 GetObject → 入庫。
敏感檔則一個位元組都沒有離開這台機器。

**對外行為零改變**：`POST /photos` 仍是 202、進度面板不變、端點仍 22、
`compose.yaml` 一個字都沒動。日常 `.env` 是 `CLOUD_ROUTE=off`，
所以這支工人平常根本不會被用到。

文件多了兩處：`LAUNCH.md` 第 12 節 "Cloud worker on the Mac"（英文）與
`CLAUDE.md` 指令區的繁中小段，兩處都寫了「收工要改回 `off`」這個最容易忘的動作。

**與總覽的差異：零。** 新增測試 5 顆，名稱與總覽 §2.7 逐字相同。
另外多了一個**公開**函式 `run_forever(mailbox, vlm, *, should_stop)`——總覽 §2.4.1 的
`cloud_worker.py` 簽章表只列了 `process_job_message` 與 `main`，**請 orchestrator 把
`run_forever` 補進去**（它才是 5 顆迴圈測試的受測對象；`main()` 只是把訊號旗標接上去再呼叫它）。

顆數：開工基線 ＋ **5** ＝ **651**。端點仍 **22**。

**下一個 phase：Phase 89** —— `Ec2Probe`（`DescribeInstances` ＋ 60 秒 TTL 快取），
讓本機在送出之前先問一句「那台機器現在開著嗎」，並把 `get_cloud_route()` 的
最後一個暫時分支 `ec2` 補上。之後 **Phase 90**（多階段 `Dockerfile` ＋ arm64 映像）做完，
才輪到 **★G2**——**產品負責人點頭之前，一台 EC2 都不准開。**

---

## 附：本文件引用的官方文件

- [SQS 長輪詢（`WaitTimeSeconds` 上限 20 秒）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html)
- [SQS 可見度逾時（處理失敗不刪訊息，時間到自動重來）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [SQS `PurgeQueue`（60 秒只能做一次）](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_PurgeQueue.html)
- [boto3 憑證來源順序（環境變數排在很前面）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
- [boto3 設定（含 `AWS_ENDPOINT_URL`）](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html)
- [Python `signal` 模組（處理函式裡只做最短的事）](https://docs.python.org/3/library/signal.html)
- [Python `logging` handler 與層級](https://docs.python.org/3/howto/logging.html)
- [Python `-m` 執行模組](https://docs.python.org/3/using/cmdline.html#cmdoption-m)
- [Docker `stop` 送 SIGTERM 的行為](https://docs.docker.com/reference/cli/docker/container/stop/)
- 專案內文件：`docs/design/design6.md`（§0 丁那列、D2／D6／D10／D12、§2.3、§9、§12）、
  `docs/plan/unfinish/phase-00-增量六總覽.md`（§2.4.2 設定、§2.6 工人規則、
  §2.7 本 phase 的測試清單、§5.2 Demo 2、§10 追認項 f／l）、
  `LAUNCH.md` 第 9 節（各層的 log 指令）、`CLAUDE.md` 指令區
