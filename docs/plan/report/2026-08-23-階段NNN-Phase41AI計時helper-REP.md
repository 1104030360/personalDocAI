# 階段NNN REP：Phase 41 AI 計時 helper `services/ai_timing.py`（階段乙第 1 步）

> 日期：2026-08-23　狀態：✅ 完成
> 依據：`docs/plan/unfinish/phase-41-AI計時helper.md`（逐條照做）＋`docs/design/design4.md` §5.1〜§5.3、§5.4 第 1／6 列、D7
> 對應 TODO：`docs/plan/todo/2026-08-23-階段NNN-Phase41AI計時helper-TODO.md`
> 開工基準（實測）：365 passed ＋ 2 skipped　→　完工（實測）：**373 passed ＋ 2 skipped**（恰好 +8）

## 實作邏輯

階段乙第一步只做**工具本身**，不接任何呼叫點（接線是 Phase 42／43）。
所以本 phase 做完，**產品行為逐位元不變**——沒有任何既有程式碼會呼叫這個 helper，
`app/` 底下沒有一個既有檔案被動過。

新建的 `app/services/ai_timing.py` 是一個 context manager；初版用法是 `with log_ai(kind):`，
最終真實 client 用法是 `with log_ai(kind, target=已選定目標):`。
一行包住一次 AI 呼叫，自動在前後各打一行 INFO log，五個必要欄位
（`kind`／`backend`／`model`／`elapsed_s`／`ok`）順序固定，這樣才 grep 得出來。

三個設計決定（全部照計畫，理由記在這裡免得日後有人「順手改掉」）：

1. **本 phase 初版的 backend／model 由 helper 自己從 `config` 推**，呼叫端當時只寫
   `with log_ai("vlm"):`。
   design4 §5.3 的示意是 `with log_ai("vlm", backend=..., model=...)`，`...` 是留給實作填的
   佔位；計畫 §4.2 的 📌 明文決定改由 helper 推。理由：kind→模型是**死的規則**，
   抄到八個呼叫點（Phase 42 三處＋Phase 43 五處）就是八份會各自走鐘的複製品。
   這是歷史 phase-local 設計；最終 hardening 的真實 client 已改傳 immutable target。
2. **初版 fallback 的 `config.AI_BACKEND` 在函式裡即時讀**（不是
   `from app.core.config import AI_BACKEND`）。
   它是頁首那顆「本機｜雲端」開關撥動的執行中狀態，import 進來會定死成伺服器啟動
   當下的值——`config.py` 第 40 行的註解已經寫明這條規矩。
3. **`_目標(kind)` 算在打開始行之前**。kind 打錯時要在「一行 log 都還沒打」的狀態下
   `ValueError`，不然終端機會留下一個永遠等不到結束行的孤兒開始行（計畫 §7 陷阱 9）。

不吞例外是本 phase 最重要的一條（計畫 §7 陷阱 3 稱之為「最嚴重的可能錯誤」）：
`except BaseException` 只記一個旗標、然後**必須 `raise`**，結束行由 `finally` 打。

- 抓 `BaseException` 而不是 `Exception`：Ctrl+C（`KeyboardInterrupt`）與 uvicorn 關機丟的
  不是 `Exception` 的子類，用窄的那個會漏掉結束行。這裡不處理例外、只記旗標，
  所以抓最寬的那個最正確。
- 用 `finally` 而不是 `else`：`else` 只有沒例外時才跑，失敗就不會打結束行。
- `%.1f` 而不是 `str(秒數)`：假件跑得極快，秒數會是 `1.9e-05` 這種科學記號，
  格式化之後是 `0.0`，正是我們要的（實測見下方變異測試的 log 節錄）。

## 步驟

- [x] 寫 TODO。開工前實測基準 `pytest -q` ＝ **365 passed ＋ 2 skipped**（與計畫 §2 一致）。
- [x] 讀 `CLAUDE.md`、計畫全文、`design4.md` §5.1〜§5.3；另確認 `app/core/config.py` 的
      六個常數名稱（`VLM_MODEL`／`OLLAMA_CLOUD_VLM_MODEL`／`LLM_MODEL`／
      `OLLAMA_CLOUD_LLM_MODEL`／`EMBEDDING_MODEL`／`AI_BACKEND`）與計畫的表逐一對得上。
- [x] 另確認 `app/main.py` 掛 handler 時**沒有**設 `propagate = False`
      （第 16〜21 行只有 `addHandler` ＋ `setLevel`）——所以 log 會往上傳到 root，
      `caplog` 抓得到。這是「測試能不能成立」的前提，先查再寫。
- [x] **先寫測試**：新建 `tests/unit/test_ai_timing_unit.py`，八顆照計畫 §4.3 的表逐字命名。
- [x] **跑紅**：`pytest tests/unit/test_ai_timing_unit.py -v` → **收集階段 1 error**，
      `ModuleNotFoundError: No module named 'app.services.ai_timing'`（證據見下）。
- [x] **再寫實作**：新建 `app/services/ai_timing.py`，照計畫 §4.4 的骨架（含 docstring 與註解）。
- [x] 跑綠三連：新檔 **8 passed** → 全量 **373 ＋ 2** → 指死埠 **373 ＋ 2**。
- [x] 額外做一次**變異測試**（見下「遇到的問題與解法」第 2 點），證明測試 3 真的抓得到
      「忘了 `raise`」，改回來後重新驗綠。
- [x] 計畫 §6 驗收清單逐項核對（含掃碼與 `git status`），全過。
- [x] 寫本 REP。

## 測試方式

八顆單元測試，全部用 pytest 內建 `caplog` 抓 log，開頭一律 `caplog.set_level(logging.INFO)`
（helper 打的是 INFO，忘了設會看到空的 `caplog.messages` 而百思不解——計畫 §7 陷阱 7）。

兩條刻意的規矩：

- **秒數只斷言 `>= 0`**：用 `re.compile(r"elapsed_s=([0-9.]+)")` 抓出來轉 `float` 再比。
  全檔**沒有任何「秒數等於某個值」的斷言**（design4 §5.3 明文禁止；假件飛快、真模型
  幾分鐘，寫死必壞）。
- **切後端一律 `monkeypatch.setattr(config, "AI_BACKEND", …)`，連「本機」那半邊也明寫**
  `"local"`。`AI_BACKEND` 是模組層的可變狀態，靠「預設值剛好是 local」會被同一個
  process 裡別人撥過的值絆倒；monkeypatch 還會在每顆測試結束時自動還原。

| # | 測試名稱 | 驗什麼 | 結果 |
|---|---|---|---|
| 1 | `test_成功時打出開始與結束兩行` | `caplog.messages` 恰兩筆，一筆 `AI 開始 ` 開頭、一筆 `AI 結束 ` 開頭 | ✅ |
| 2 | `test_結束行帶ok為true與非負秒數` | 含 `ok=true`；`elapsed_s=([0-9.]+)` 轉 float **≥ 0** | ✅ |
| 3 | `test_例外會往外傳且結束行標ok為false` | `pytest.raises(RuntimeError, match="炸了")` 抓得到，且結束行含 `ok=false` | ✅ |
| 4 | `test_embed的backend永遠是local就算開關撥到雲端` | 撥 cloud 仍 `backend=local`、`model=` 為 `EMBEDDING_MODEL` | ✅ |
| 5 | `test_vlm跟著開關切換backend與model` | local→`VLM_MODEL`；cloud→`OLLAMA_CLOUD_VLM_MODEL` | ✅ |
| 6 | `test_三種文字用途都用LLM模型名` | route／answer／entity_suggest 三個 kind ×本機／雲端 | ✅ |
| 7 | `test_備註接在結束行後面且五個欄位仍在` | `.endswith("text 3 字")` 且五個欄位都還在 | ✅ |
| 8 | `test_未知的kind直接炸掉且一行log都沒打` | `ValueError` 且 `caplog.messages == []` | ✅ |

測試 5／6 斷言的是**連在一起的子串**（例如 `f"backend=cloud model={config.OLLAMA_CLOUD_VLM_MODEL}"`），
不是分開兩個 `in`——順便把「兩個欄位相鄰且順序正確」也一起釘住。

不需要伺服器、不碰網路、不碰資料庫：`with` 區塊裡只有 `pass` 或 `raise`。
埠 8000 那個使用者留著的 uvicorn 全程沒動過。

## 遇到的問題與解法

### 1. 計畫要求「斷言 `model={config.VLM_MODEL}`」在某些機器上會是空談——查了才敢照做

計畫 §4.3 測試 5／6 要求斷言 `model={config.VLM_MODEL}` 與 `model={config.OLLAMA_CLOUD_VLM_MODEL}`。
但 `config.py` 第 30／34 行的預設值是「雲端跟本機同名」（`os.getenv(..., VLM_MODEL)`），
所以在一台沒有 `.env` 覆蓋的機器上這兩個值**相等**，`model=` 那半邊就驗不出差異
（`backend=` 那半邊仍然有效）。

先查了本機實際解析出來的值（只印模型名，沒有印 `.env` 裡的 `OLLAMA_API_KEY`）：

```text
VLM_MODEL              = gemma4:e2b
OLLAMA_CLOUD_VLM_MODEL = gemma4
LLM_MODEL              = gemma4:e2b-mlx
OLLAMA_CLOUD_LLM_MODEL = gemma4
EMBEDDING_MODEL        = bge-m3
```

本機與雲端**確實不同名**（CLAUDE.md 記的是兩者都釘成 `gemma4`，實際是 VLM 本機
`gemma4:e2b`、LLM 本機 `gemma4:e2b-mlx`，雲端兩顆都是 `gemma4`），
所以測試 5／6 在這台機器上真的分得出來。

**決定：照計畫寫，斷言 `config.X` 這個「符號」而不是寫死字串。** 理由是這樣兩邊都對——
在本機它是有鑑別力的測試，在沒有 `.env` 的乾淨機器上它退化成只驗 `backend=`，
但**永遠不會誤紅**。反過來若寫死 `"gemma4:e2b"`，換一台機器就假性失敗。
（本輪**沒有**去改 CLAUDE.md 裡那句與實際不符的模型名描述——本 phase 不動既有檔案；
這件事留給主 agent 斟酌。）

### 2. 「先紅後綠」只證明模組不存在，不證明每條斷言有鑑別力 → 補一次變異測試

紅階段是 `ModuleNotFoundError`（計畫 §4.3 就是這樣要求的），它證明「沒有實作就過不了」，
但**不證明**每顆測試的斷言真的咬得住。計畫 §7 陷阱 3 明說「忘了 `raise`」是本 phase
最嚴重的可能錯誤，所以針對這一條做了一次變異測試（本專案有先例：CLAUDE.md 記載
`search_by_vector` 的 30 天過濾也是用變異測試證實的）。

手法：暫時把 helper 裡的 `raise` 拿掉、跑一次、再改回來。結果如預期——
**1 failed（正是測試 3）、7 passed**，且畫面上的 `Captured log call` 順便印出真實格式：

```text
INFO  app.services.ai_timing:ai_timing.py:74 AI 開始 kind=route backend=local model=gemma4:e2b-mlx
INFO  app.services.ai_timing:ai_timing.py:90 AI 結束 kind=route backend=local model=gemma4:e2b-mlx elapsed_s=0.0 ok=false
```

兩件事一次確認：① logger 名稱是 `app.services.ai_timing`（在 `app.*` 底下，`main.py`
掛的 handler 接得到）；② `elapsed_s=0.0`——`%.1f` 確實把假件那個極小的秒數壓成
一位小數，沒有變成科學記號（計畫 §7 陷阱 8）。

改回 `raise` 之後重跑，8 顆全綠；最後又跑了一次全量與指死埠，確認檔案已復原。

### 3. IDE 報兩個 `line too long`（81／84 > 79）——不是專案標準，但順手修掉

專案**沒有** flake8 設定檔（`.flake8`／`setup.cfg`／`tox.ini`／`pyproject.toml` 都不存在），
venv 裡也**沒有裝 flake8**；既有檔案超過 79 欄的行數是 `photos.py` 111 行、
`vlm_service.py` 103 行、`test_vlm_service_unit.py` 56 行——顯示 79 欄不是本專案的慣例，
那兩個提示來自 IDE 內建檢查器的預設值。

不過修掉的成本近乎零（把兩個 `assert` 用括號斷行），所以還是修了，讓使用者的 IDE 乾淨。
修完 `ReadLints` 零錯誤、8 顆仍綠。**沒有**因此去動任何既有檔案的行寬。

## 測試結果

### 紅階段（實作前，證據）

```text
$ pytest tests/unit/test_ai_timing_unit.py -v
______________ ERROR collecting tests/unit/test_ai_timing_unit.py ______________
tests/unit/test_ai_timing_unit.py:28: in <module>
    from app.services.ai_timing import log_ai
E   ModuleNotFoundError: No module named 'app.services.ai_timing'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
========================= 1 warning, 1 error in 0.13s ==========================
```

是**收集階段 1 error**、不是 8 個 F——模組還沒建、`import` 就炸了，八顆連跑都還沒跑到。
與計畫 §4.3 的預期逐字相符。

### 綠階段

| 指令 | 結果 | 預期 |
|---|---|---|
| `pytest tests/unit/test_ai_timing_unit.py -v` | **8 passed** | 8 passed ✅ |
| `pytest -q` | **373 passed ＋ 2 skipped** | 373 ＋ 2 ✅ |
| `OLLAMA_BASE_URL=http://localhost:9 pytest -q` | **373 passed ＋ 2 skipped** | 顆數相同 ✅ |

365 → 373 ＝ **恰好 +8**，與計畫 §2 的「要對的是差值」一致。
指死埠（9 是不會有人在聽的埠）顆數不變 ＝ 本 phase 的測試沒有偷偷打真的 Ollama。

### 計畫 §6 驗收清單

| 項目 | 結果 |
|---|---|
| 八顆單元測試先紅後綠 | ✅ 紅＝收集期 `ModuleNotFoundError`；綠＝8 passed |
| `pytest -q` ＝ 373 passed ＋ 2 skipped | ✅ 實測相符 |
| `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同 | ✅ 373 ＋ 2 |
| helper 裡沒有 `print(`、`open(`、`try: … except: pass` | ✅ 掃碼各 0（裸 `except:` 也是 0） |
| helper 裡是 `config.AI_BACKEND`，不是 from-import | ✅ `config.AI_BACKEND` 出現 4 次；`import AI_BACKEND` 0 次 |
| 測試裡沒有「秒數等於某值」的斷言（只有 `>= 0`） | ✅ 全檔只有 `float(...) >= 0` 一處數值比較 |
| `git status --short -- app tests` 沒有動到既有檔案 | ✅ 見下方說明 |

補充掃碼（鐵律逐條）：`time.monotonic` 2 次／`time.time(` **0** 次；
`logger.info` 2 次／`logger.debug` **0** 次；`getLogger(__name__)` 1 次；
`finally:` 1 次、`raise` 1 次、`except BaseException` 1 次；
`select`／`insert`／`repository`／`psycopg` 字樣 **0** 次（不寫資料庫、不算統計）。

### 「沒有動到既有檔案」的證據

計畫 §6 寫的是「`git status --short -- app tests` 恰好只有兩行 `??`」，那是**乾淨工作樹**下的
預期。實際上工作樹裡有 Phase 38〜40 留下的變動（本增量全程不 commit），所以看到的是
4 個 `??` ＋ 5 個 `M`。用**修改時間**證明哪些是本輪的（本 session 從 15:06 開始）：

```text
Aug 23 15:12:18   app/services/ai_timing.py           ← 本輪新建
Aug 23 15:10:50   tests/unit/test_ai_timing_unit.py   ← 本輪新建
Aug 23 15:03:14   app/static/browse.html              ← Phase 40
Aug 23 15:02:31   app/static/photo_detail_modal.js    ← Phase 39
Aug 23 15:02:23   app/static/style.css                ← Phase 40
Aug 23 14:47:42   tests/integration/test_ask_three_paths.py  ← Phase 34／38
Aug 23 14:47:34   app/api/routers/photos.py           ← Phase 38
Aug 23 14:47:16   app/schemas/photo.py                ← Phase 38
Aug 23 14:46:46   tests/integration/test_photo_detail.py     ← Phase 38
```

本輪的兩個檔是**唯二**在 15:06 之後被寫過的；其餘全部在 15:03:14 以前，
早於本 session 開始，一個都不是本輪動的。**本 phase 恰好只新建兩個檔**
（＋本 TODO／REP 兩份文件），零既有檔案修改。

### 產品行為

**零改變。** 沒有任何既有程式碼呼叫 `log_ai`——接線是 Phase 42（`photos.py` 看圖＋embedding、
`assign_folder` 重算）與 Phase 43（`ask_workflow` 的 route／answer、
`retrieval_service` 的 `embed_query`、`entity_suggestion_service` 本機＋雲端）。
`photos.py` 現有那段寫死的 `AI 看圖開始`／`AI 看圖完成（%.1f 秒）` **本輪刻意保留原樣**
（design4 §5.2 最後一列要求「改走這套、不要新舊並行」，但那是 Phase 42 的動作）。

## 給 Phase 42／43 接手的人

1. 當時用法是一行 `with log_ai("vlm"):`，由 helper 從 config fallback；最終真實 client
   應使用 `with log_ai("vlm", target=已選定目標):`，讓 backend／model 對應實際 request，
   不被後續全域開關 relabel。想附摘要就接 `as 計時:`，
   然後 `計時.note = f"text {n} 字"`，摘要會接在結束行**最後面**。
2. kind 五選一（`vlm`／`embed`／`route`／`answer`／`entity_suggest`），打錯當場 `ValueError`。
3. `embed` 永遠 `backend=local`，不歸開關管。
4. helper 不改任何例外語意，所以包上去之後 422／500／fallback 的行為**不需要**跟著改測試。
5. design4 §5.4 還列了一個 `tests/integration/test_ai_timing_log.py`（上傳一張、詢問向量、
   詢問非向量、再建議一個，用 `caplog` 看 kind）——那是接線之後才寫得出來的，
   本 phase 沒有建這個檔。

## 最終 hardening 補記（2026-08-24）

- `AiTarget` 是 frozen immutable value；真實 VLM／embedding／router／answerer／entity client
  把建構／request 已選定的 backend 與 model 傳給 `log_ai(..., target=...)`。`target=None` 仍保留
  給 helper 單元測試與沒有 target 的假件，才會即時讀 config；兩者不可混稱。
- model／note 的控制字元、ANSI／換行會轉成單行，過長值會截斷；看圖 note 只保留數量與布林
  摘要，不記 AI 產生內容。這些 RED→GREEN regression 釘住 log injection、log flooding 與隱私面。
- 最終 targeted 為 **112 passed, 2 skipped, 1 warning in 9.42s**；full 為
  **402 passed, 2 skipped, 1 warning in 27.73s**。唯一 warning 是
  `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
- 狀態：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**。工作樹仍 dirty；
  沒有 commit、release、Docker／Compose 或 Phase 45 工作。
