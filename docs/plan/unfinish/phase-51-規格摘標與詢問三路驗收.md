# Phase 51：規格摘標與詢問三路驗收（`自然語言詢問.feature` 兩條 `@未實作` 落地）

> 🎯 **提醒：這是 side project，不要過度設計。**

```text
┌─ 本 phase 與 Docker 無關 ────────────────────────────────────────
│ 不需要 G1／G2 門檻框：這裡不碰 compose、不碰資料庫搬家、不碰正式庫。
│ 只在 host 跑 `pytest`，動兩個檔：規格（兩個標籤＋一格日期＋檔頭核准紀錄）、
│ 測試假件 `tests/fakes.py`（一行）；收尾另外更新 CLAUDE.md 與總覽兩份文件。
│ 唯一與 Docker 沾邊的一句：Phase 47 之後測試庫住在 container 裡，
│ 所以跑 pytest 前要確認 `docker compose ps` 的 `db` 是 `Up (healthy)`。
└──────────────────────────────────────────────────────────────────
```

> 🎯 **一句話目標：** 把 `docs/spec/features/自然語言詢問.feature` 那兩條掛著 `@未實作`
> 的 Rule（實體別針路、待辦路）**摘掉標籤、修掉規格自己寫錯的到期日**，
> 讓 Phase 34 早就做好的「詢問三路」正式進規格驗收——
> 全量測試從 **387 passed ＋ 2 skipped** 變成 **389 passed ＋ 0 skipped**。

> **為什麼排在增量四最後一個（不是提前做）：**
> design4 §7 的閘門 G1 明文要求「既有 **2 skipped 仍 skip**」，§8.9 的階段丙驗收也要求
> 「`pytest -q` 與遷移前**同顆數（含既有 skipped）**」。摘標會把 2 skipped 變成 0，
> 提前做就會讓這兩條驗收**對不上**——實作者得一路解釋「數字不一樣是因為別的事」，
> 那正是閘門最不該有的雜訊。排在最後，38〜50 的顆數鏈（387 ＋ 2）**完全不受影響**，
> 只有本 phase 自己把它變成 389 ＋ 0。

---

## 1. 對應章節（本 phase 的授權來源）

**⚠ 這是 `docs/spec/` 唯讀規格區的第二次正式解禁，授權寫在這裡，不要略過。**

| 出處 | 說的是什麼 |
|---|---|
| **產品負責人 2026-08-23 裁決** | 「那兩條 `@未實作` 的 Rule，**修改規格裡的日期後摘標**。」——本 phase 的全部授權來源 |
| `docs/design/design4.md` §1.1 未推翻清單 | 原文寫「規格 `.feature` 本輪不改」。**本 phase 是這一條的正式例外**，由上一列核准；除了本檔列出的三處，`.feature` 其餘一字不動 |
| `CLAUDE.md` 專案概述第一段 | 「`docs/spec/` 規格區唯讀（唯一例外：`上傳照片.feature` 經產品負責人核准、2026-08-21 依 design1.md 改版）」——**這次是同一種先例的第二次**，所以檔頭要照樣留下核准紀錄（見 §4.2） |
| `docs/design/design3.md` D14、§6 | 那兩條 Rule 的內容出處（實體別針路、待辦路的目標問句）。**功能本身 Phase 34 早就做完了**，本 phase 不寫任何新功能 |
| `docs/plan/finish/phase-34-詢問三路.md` 驗收清單第 1 條 | 當時明寫：「另一 session 補的兩條 @未實作 Rule 被 skip ＝ **摘標屬產品負責人**」 |
| `docs/plan/unfinish/phase-44-…` §8 陷阱 4 | 明寫摘標前「他還得先處理規格裡『到期 2026-09-18』與『這週』互相矛盾那件事」——**本 phase 處理的就是它** |

---

## 2. 前置條件

- **Phase 50 已完成**（增量四的 Docker 那條線收工、`CLAUDE.md` 指令區已改寫）。
- 目前狀態應該是：`pytest -q` ＝ **387 passed ＋ 2 skipped**、`/openapi.json` 端點 ＝ **20**。
- 本檔所有指令都在專案根目錄執行，並且要先進虛擬環境：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps          # db 要是 Up (healthy)，測試庫在它裡面（Phase 47 之後）
pytest -q                  # 先確認基準沒跑掉：387 passed ＋ 2 skipped
```

- **不需要**閘門 G1／G2 的檢查框：那兩道閘門守的是「可不可以碰 Docker／可不可以停 brew」，
  本 phase 兩件事都不做。

### 先認識三個名詞（新手向）

- **摘標**＝把 Gherkin 例子上面那一行 `@未實作` 標籤**刪掉**。
  標籤本身不是註解，它會被 `tests/conftest.py` 攔下來變成 pytest 的「跳過」。
- **binder**（綁定檔）＝把規格 `.feature` 的中文句子接到 Python 程式碼的那個檔。
  本專案的詢問 binder 是 `tests/integration/test_ask_feature.py`，
  第 21 行 `scenarios("../../docs/spec/features/自然語言詢問.feature")`
  ＝「把那份規格原檔直接當測試跑」（不複製、不改寫）。
- **假路由**（`FakeRouter`）＝測試用的替身，不打真模型。
  它的做法是**查表**：`tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS` 是一份
  「問句 → 該走哪一路」的對照表，問句**沒登記過就丟例外**（模擬「LLM 判不出來」）。

---

## 3. 範圍

### 做

- 摘掉 `自然語言詢問.feature` 第 75、91 行的兩個 `@未實作` 標籤。
- 把待辦例子（原檔第 99 行）的到期日 `2026-09-18` 改成 **`2026-08-21`**（理由見 §4.4、§5 的時間軸）。
  ⚠ 本檔提到規格檔的行號一律是**動筆前**的原檔行號，改到一半會漂（見 §4.1 開頭的提醒）。
- 在 `.feature` 檔頭補一段 **2026-08-23 核准紀錄**（比照 `上傳照片.feature` 的既有寫法）。
- 在 `tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS` **新增一行**
  `"這週要交什麼"`（規格用的是**沒有問號**的寫法，現有那一行是有問號的，見 §4.3）。
- 全量回歸、更新 `CLAUDE.md` 現況段與總覽勾選區。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 動 Q1〜Q5 那既有五條 Rule（`.feature` 第 12〜70 行） | 它們從 Phase 12 起一路全綠，是**回歸基準**。這次核准的只有那兩條新 Rule 與一格日期 |
| 動另外六份 `.feature`（`上傳照片`／`歸類照片`／`釘選實體`／`建立待辦`／`瀏覽檔案櫃`／`無線鏡頭拍攝`） | 產品負責人這次的裁決只提到 `自然語言詢問.feature`。唯讀規格區沒被核准的部分**仍然唯讀** |
| 改任何產品程式碼（`app/` 底下一行都不准動） | 功能 Phase 34 已落地且真模型煙霧過。**紅的是規格寫錯了日期，不是程式算錯了窗**——把 `due_within_days`、`<=`、`+7` 任何一項改掉，等於把規格的筆誤搬進程式裡（§8 陷阱 5） |
| 把 `tests/fakes.py` 既有那行 `"這週要交什麼？"`（**有**問號）**改掉** | `test_ask_three_paths.py` 有**兩顆測試真的靠這個鍵查表**（第 318、405 行；另有第 265 行寫著同一個字串，但它直接呼叫 retriever、不經路由）。要**加一行**，不是改一行（§8 陷阱 1） |
| 刪掉 `tests/conftest.py` 的 `pytest_bdd_apply_tag`（第 99〜105 行） | 摘完之後全專案暫時沒有 `@未實作`，但那個 hook 是**安全網**：日後補新規格再標一次就會自動 skip。留著（§8 陷阱 2） |
| 新增端點、改回應欄位、改 `SEARCH_MODE_LABELS` | 端點維持 **20**；`"entity pin search"`／`"task search"` 兩個全名 Phase 34 就定了，規格例子照抄的就是它們 |
| 新增自動化測試 | 本 phase 的產出是「**既有的兩顆從 skip 變 pass**」，不是多寫測試 |
| `git commit` | 沿用產品負責人既有指示：改完先檢視。`unfinish/` → `finish/` 的歸檔隨 commit 執行 |

---

## 4. 實作步驟

### 4.0 先看懂「現在是什麼狀況」（不動手，5 分鐘）

- [ ] 確認那兩條 Rule 真的被 skip（**這是純收集，不會跑到資料庫**）：

```bash
pytest tests/integration/test_ask_feature.py --collect-only -q
pytest tests/integration/test_ask_feature.py --collect-only -q -m skip
```

  預期：第一條印出 **9 個**測試，最後兩個是
  `test_問跟我_macbook_有關的全部` 與 `test_問這週要交什麼`；
  第二條印出 `2/9 tests collected (7 deselected)`
  ——那 2 個就是全量 `pytest -q` 尾巴看到的 **2 skipped**。

- [ ] 讀一遍 skip 是怎麼發生的：`tests/conftest.py` 第 99〜105 行

```python
def pytest_bdd_apply_tag(tag, function):
    """規格裡標 @未實作 的例子先跳過，等對應 phase 落地再摘標。"""
    if tag == "未實作":
        marker = pytest.mark.skip(reason="規格已寫、對應 phase 尚未實作")
        marker(function)
        return True
    return None
```

  `pytest_bdd_apply_tag` 是 pytest-bdd 的官方 hook：規格裡每個標籤都會經過它一次。
  回傳 `True` ＝「這個標籤我處理掉了」；回傳 `None` ＝「交還給 pytest-bdd 預設處理」。
  所以 `@未實作` 這四個字**只在這裡**有意義，刪掉標籤就等於解除 skip，**不必改任何程式**。

- [ ] **先拍一份「動筆前的 `app/` 長相」**（§4.5 收尾要拿它比對）。
      本增量全程不 commit，所以階段甲乙（Phase 38〜43）改過的產品碼都還躺在工作區裡——
      唯一能證明「本 phase 沒碰產品碼」的方式，就是前後兩份清單一模一樣：

```bash
git status --short -- app/ > /tmp/phase51-app-before.txt
cat /tmp/phase51-app-before.txt      # 看一眼：這些都是前面 phase 留下的，不是你的
```

### 4.1 步驟一：只摘標籤，先看紅（**這一步刻意不改日期**）

> ⚠️ **行號會漂，別照著數字連刪兩次。** 本檔提到規格檔的行號
> （75／81／82／91／93／96／99／100）**一律指動筆前的原檔**。
> 刪掉第 75 行的那一刻，原本的第 91 行就變成第 90 行了。
> 保險做法二選一：**由下往上刪**（先 91、再 75），或直接在編輯器裡搜尋 `@未實作` 刪兩次。
> 後面每個步驟也一樣——看到行號對不上，先數一下前面刪了／加了幾行，不要以為規格被別人動過。

- [ ] 刪掉 `docs/spec/features/自然語言詢問.feature` 的**第 75 行**與**第 91 行**
      （兩行都只有縮排＋`@未實作`，整行刪掉，不要留空行）：

```diff
   Rule: 問到已確認的實體名稱時，系統沿實體別針列出掛著的照片
     # 驗收問句來自 design3.md §6；檢索方式對外全名為 entity pin search
 
-    @未實作
     Example: 問跟我 MacBook 有關的全部
```

```diff
   Rule: 問到待辦或到期時，系統查待辦表
     # 驗收問句來自 design3.md §6；檢索方式對外全名為 task search
 
-    @未實作
     Example: 問這週要交什麼
```

- [ ] 跑 binder：

```bash
pytest tests/integration/test_ask_feature.py -v
```

**預期：8 passed、1 failed、0 skipped**——原本那 7 顆照舊綠、
**實體那條一摘就綠、待辦那條紅**。（`skipped` 從這一刻起就是 0 了。）

- **實體那條為什麼一摘就綠**：功能（Phase 34）、binder 的五個步驟（§6 表格的第 70／103／
  123／130／140 行）、假路由的登記（`tests/fakes.py` 第 238〜240 行）三者早就到位，
  唯一擋著它的就是那個標籤。
- **待辦那條的紅長這樣**（`-v` 之外建議加 `-k 這週` 只跑它，訊息比較好讀）：

```text
FAILED tests/integration/test_ask_feature.py::test_問這週要交什麼
E   AssertionError: assert 'vector semantic search' == 'task search'
```

  同一次輸出裡（`Captured log call` 區塊）還會看到一行**警告**：

```text
WARNING  app.services.ask_workflow:ask_workflow.py:311 路由呼叫失敗，fallback 成語意查詢
RuntimeError: 無法判斷問題類型：這週要交什麼
```

> ⚠️ **這一步的紅跟你以為的原因不一樣，別急著改日期。**
> 表面上是「檢索方式不對」，`RuntimeError` 那一行才是真話：
> **假路由的對照表裡沒有「這週要交什麼」這個鍵**（現有那一行是「這週要交什麼**？**」，
> 多一個全形問號）。查不到鍵 → 丟例外 → `route_node` 依設計 fallback 成語意查詢
> （`ask_workflow.py` 第 305〜315 行）→ `search_mode` 當然變成 `vector semantic search`。
> 日期矛盾這時候**還輪不到上場**，因為根本沒走到待辦那一路。
> 先修對照表（§4.3），日期的紅才會浮出來（§4.4）。

### 4.2 順手把核准紀錄寫進 `.feature` 檔頭（**不要略過**）

`docs/spec/` 是唯讀規格區。沒有這段紀錄，下一個人 `git log` 看到規格被改，
只能推論「有人違規動了唯讀檔」。`上傳照片.feature` 的檔頭已經有三筆同樣格式的紀錄
（2026-08-20／08-21／08-22），照抄那個寫法即可。

- [ ] 在 `自然語言詢問.feature` 現有檔頭註解的**最後一行之後**、`Feature:` 之前，**插入**：

```text
# 2026-08-23 產品負責人核准解除唯讀（design4.md §1.1「規格 .feature 本輪不改」的正式例外）：
#   1. 最後兩條 Rule（實體別針／待辦）的 @未實作 摘除——Phase 34 已落地
#      （檢索方式全名 entity pin search／task search）
#   2. 待辦例子的到期日 2026-09-18 → 2026-08-21：原本的日期落在問句「這週」的
#      7 天窗之外（今天 2026-08-18 ＋ 7 ＝ 2026-08-25），例子與它自己的問句互相矛盾
```

- [ ] **現有的第 1〜5 行一個字都不要改。** 那是**時序紀錄**（2026-08-22 當時確實套了
      `@未實作`），不是現況描述；照 `上傳照片.feature` 的慣例，新的一筆往下疊就好。

> 這一段**恰好 5 行**（§4.5 與 §7 會核對這個數字）；插進去之後，
> 這個檔案後面每一行的行號都**往下推 5 行**（第 99 行的日期那一列因此落到第 102 行，見 §4.4）。
>
> **這一節是本檔唯一「超出『一格日期＋兩個標籤』」的改動。** 理由寫在上面那段。
> 若產品負責人認為連檔頭註解都不該碰：**整個 §4.2 刪掉即可**，
> §4.1／§4.3／§4.4 一步都不受影響（記得連 §7 驗收清單第 3 條與 §8 陷阱 6 一起拿掉，
> 而且改完後日期那一列會回到第 97 行，不是第 102 行）。

### 4.3 步驟二：假路由補一個鍵（測試碼，不是產品碼）

- [ ] 在 `tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS`（第 221〜248 行）裡，
      **在既有那行「這週要交什麼？」旁邊新增一行**（不是改它）：

```python
    "這週要交什麼？": RouteDecision(mode="task", due_within_days=7),
    # 規格 自然語言詢問.feature「問到待辦或到期時」那條 Rule 的問句**沒有問號**。
    # 假路由是逐字查表的，差一個全形問號就查不到 → 丟例外 → fallback 成語意查詢，
    # 規格驗收會紅在 search_mode。兩個鍵並存：有問號那個另有兩顆測試在用。
    "這週要交什麼": RouteDecision(mode="task", due_within_days=7),
    "What is due this week?": RouteDecision(mode="task", due_within_days=7),
```

> ⚠️ **這段是「插入」不是「整段貼上」。** 上面第一行與最後一行（有問號那個鍵、英文那個鍵）
> 是 `tests/fakes.py` 裡**本來就存在**的兩行，列在這裡只是給你當**定位錨點**，
> 讓你看得出新的四行（三行註解＋一行新鍵）要夾在它們**中間**。
> 整段複製貼上去覆蓋，就等於把既有那兩行重寫一次——萬一貼歪或縮排跑掉，
> 你會親手踩中本檔 §8 陷阱 1 說的那件事。**只把中間那四行打進去就好。**

> **為什麼不是「把規格的問句加上問號」去遷就假件？**
> 方向要對：規格是 source of truth，假件是為了服務規格而存在的。
> phase-34 的計畫（拆解 5）本來就寫「`DEFAULT_ROUTE_DECISIONS` 加實體／待辦問句各一例」，
> 只是當時是照 design3 §6 的原文（有問號）登記的，規格檔後來由另一個 session 補寫成沒問號。
> 補一行是**把假件對齊規格**，改規格則是反過來。
>
> **為什麼不是把既有那行的鍵直接換成沒問號的？**
> 有問號那個鍵**有兩顆測試真的靠它查表**（`tests/integration/test_ask_three_paths.py`
> 第 318 行 `test_待辦問句走待辦路`、第 405 行 `test_端點待辦問句回的是來源照片id`——
> 兩顆都用 `FakeRouter()` 的預設對照表；同檔第 265 行也寫著同一個字串，
> 但它是直接呼叫 `photo_retriever`、不經路由，改鍵不會弄紅它）。
> 換掉鍵會讓那兩顆連帶變紅——那是**你弄壞的**，不是規格的問題。
> **兩個鍵並存**，代價只有一行。

- [ ] 重跑：

```bash
pytest tests/integration/test_ask_feature.py -v
```

**預期：還是 8 passed、1 failed，但紅的位置往後移了一步**——
`search_mode` 那一步過了，紅在最後一步：

```text
FAILED tests/integration/test_ask_feature.py::test_問這週要交什麼
E   AssertionError: 回答裡沒有提到「交 Project 2」：查無相關照片。
E   assert '交 Project 2' in '查無相關照片。'
```

  而且這次 `Captured log call` 裡**不會**再有那行 `路由呼叫失敗` 的警告。
  這才是**日期矛盾**真正現形的樣子：路由判對了、走了待辦路、
  但 `search_tasks` 用 `due_date <= 2026-08-25` 去撈，`2026-09-18` 撈不到，
  檢索結果是空的 → 假回答模型（`FakeAnswerLLM`）依規矩回「查無相關照片。」。

### 4.4 步驟三：改那一格日期（只有這一格）

- [ ] 把 `自然語言詢問.feature` **待辦例子那一列**的日期改掉，**其餘欄位一字不動**
      （原檔第 99 行；經過 §4.1 刪 2 行、§4.2 加 5 行之後，它已經漂到**第 102 行**——
      最保險的找法是搜尋 `交 Project 2`，不要盲信行號）：

```diff
       And 系統中有底下待辦
         | title        | due        | photo_id |
-        | 交 Project 2 | 2026-09-18 | 1        |
+        | 交 Project 2 | 2026-08-21 | 1        |
```

  ⚠ Gherkin 表格是用 `|` 對齊的，`2026-09-18` 與 `2026-08-21` **剛好一樣長（10 個字元）**，
  所以直接覆蓋數字就好，不必重排空白。

#### 為什麼是 2026-08-21，不是別的日期

先把「這週」的實際換算攤開（三個檔案接力，每一步都可注入、可測）：

| 步驟 | 在哪 | 做什麼 |
|---|---|---|
| ① 現在時間 | `.feature` 的 `Given 現在時間為 "2026-08-18 10:00"` → binder 第 65〜67 行寫進 `context["now"]` → 第 45 行 `app.dependency_overrides[get_now]` | 把「現在」固定成 2026-08-18 10:00 |
| ② 換成日期 | `app/dependencies.py` 第 129〜134 行 `get_today()` ＝ `now.date()` | `today` ＝ `2026-08-18` |
| ③ 抽出天數 | 假路由回 `RouteDecision(mode="task", due_within_days=7)`（「這週」＝ 7） | 7 |
| ④ 換成上界 | `app/services/retrieval_service.py` 第 169〜173 行 `due_before = today + timedelta(days=7)` | `due_before` ＝ **2026-08-25** |
| ⑤ 真的去撈 | `app/repositories/photo_repository.py` 第 736 行 `WHERE t.due_date IS NOT NULL AND t.due_date <= %(due_before)s` | **`<=`：含 08-25 當天；沒有下界** |

所以「撈得到」的範圍是 **`(-∞, 2026-08-25]`**。挑日期的四個理由：

1. **必須落在窗內** → `2026-09-18` 出局（比上界還晚 24 天）。
2. **不挑上界 `2026-08-25`**：那是**邊界值**。規格的 Example 是「這個功能長什麼樣」的示範，
   不是邊界測試；邊界早就有專門的測試釘著了——
   `tests/integration/test_ask_three_paths.py::test_search_tasks_給範圍只回該日以前到期的`（第 126 行，用的正是 08-25）
   與 `::test_task_search_零天只回今天到期的`（第 236 行，釘 `due_within_days=0`）。
   讓規格 Example 也踩在邊界上，日後只要有人把 `<=` 改成 `<`、或把 `+7` 改成 `+6`，
   **紅的會是規格驗收**，看起來像「規格寫錯了」，其實是程式改了——診斷成本高得沒必要。
3. **不挑今天 `2026-08-18`、也不挑更早的日期**：今天是另一端的邊界（理由同上）；
   更早的日期雖然也撈得到（沒有下界），但「這週**要交**什麼」配一個**已經過期**的到期日，
   讀起來莫名其妙——規格是寫給人看的。
4. **`2026-08-21` 兩端都不踩，而且連「這週」的自然語意都站得住**：
   離今天 3 天、離上界 4 天；2026-08-18 是**星期二**、08-21 是**星期五**、
   這一週的星期日是 08-23。所以就算日後有人把「這週」的定義從
   「往後 7 天」改成「到本週日為止」，`08-21` 照樣在窗內（`08-25` 就會出窗）。
   ——挑一個**兩種合理定義都成立**的日期，例子才不會因為實作換算方式微調就壞掉。

- [ ] 重跑 binder：

```bash
pytest tests/integration/test_ask_feature.py -v
```

  **預期：9 passed、0 failed、0 skipped。**

### 4.5 步驟四：全量回歸

- [ ] 全量：

```bash
pytest -q
```

  **預期：389 passed ＋ 0 skipped**（387 ＋ 原本 skip 的那 2 顆變成 pass）。
  `skipped` 那一段會**整個消失**（pytest 不會印 `0 skipped`），這是正常的。

- [ ] 零外部依賴實證（顆數必須完全相同，證明沒有偷打真 Ollama）：

```bash
OLLAMA_BASE_URL=http://localhost:9 pytest -q
```

- [ ] 三份規格 binder 單獨再跑一次：

```bash
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py \
       tests/integration/test_camera_feature.py -v
```

  預期：全綠，**而且 `-v` 的輸出裡一個 `SKIPPED` 都沒有**。

- [ ] 確認規格區只動了該動的地方：

```bash
git diff --stat docs/spec/
git diff docs/spec/features/自然語言詢問.feature
```

  預期：`--stat` 只列出**一個檔**（`自然語言詢問.feature`）；
  `git diff` 的內容恰好是：檔頭多 5 行核准紀錄、少 2 行 `@未實作`、1 行日期改動
  （`--stat` 那一行會長成 `6 insertions(+), 3 deletions(-)` 之類——5＋1 進、2＋1 出）。
  **其他六份 `.feature` 必須完全沒出現在 `--stat` 裡。**

- [ ] 確認產品程式碼一行都沒動。

  ⚠️ **這裡不能期待「空輸出」**：本增量**全程不 commit**（產品負責人既有指示，見 §3 明確不做最後一列），
  所以階段甲乙（Phase 38〜43）改過的 `app/` 檔案這時**一定還掛在工作區裡**，
  `git status --short -- app/` 印出東西是**正常的**。要驗的是「**跟你動筆前一模一樣**」，
  所以動筆前先拍一份、做完再比對：

```bash
# 動筆前先拍（建議併進 §4.0 一起做）
git status --short -- app/ > /tmp/phase51-app-before.txt
# 全部做完之後比對
git status --short -- app/ | diff /tmp/phase51-app-before.txt - \
  && echo "app/ 與動筆前完全相同"
```

  預期：`diff` **沒有印出任何差異行**，最後看到「app/ 與動筆前完全相同」。
  （本 phase 只該改到 `docs/spec/`、`tests/fakes.py`、`CLAUDE.md`、`docs/plan/` 四處。
  真的多出東西，就是手滑改到產品碼——照 §8 陷阱 5 還原。）

### 4.6 步驟五：收尾（文件）

- [ ] **更新 `CLAUDE.md` 現況段**（Phase 50 §4.4 剛把數字寫成 387＋2，本 phase 改成 389＋0）：
  - `pytest -q` 的顆數：**387 passed ＋ 2 skipped** → **389 passed ＋ 0 skipped**
    （現況段裡這個數字出現不只一次，用 `grep -n "387\|2 skipped" CLAUDE.md` 逐處確認）。
  - 「規格檔於 2026-08-22 由產品負責人指示擴充……補兩條 P34 Rule 掛 `@未實作`
    （＝全量的 2 skipped……**摘標屬產品負責人**——摘標前注意其待辦例子 due=2026-09-18
    與問句「這週」的 7 天過濾互相矛盾，擇一修正）」這一整段，改寫成**已完成**的敘述：
    2026-08-23 產品負責人核准解除唯讀，兩條 Rule **已摘標**、到期日已改為 2026-08-21
    （落在「這週」的 7 天窗內），**全量已無 skipped**；`pytest_bdd_apply_tag`
    與 binder 的 step 全數保留，日後再標 `@未實作` 仍然有效。
  - 「只跑規格檔 binder」那條指令的說明（指令區）裡「詢問的兩條 `@未實作` Rule 會 skip，
    摘標屬產品負責人」也要一起改掉——**兩處敘述要一致**。
- [ ] **更新 `docs/plan/unfinish/phase-00-增量四總覽.md`**：
      §2 進度表把 51 打勾、§5 總驗收清單「規格摘標」那一段打勾、§6 進度勾選區打勾，
      並把 Phase 50 留下的完成註記補上本 phase 的最終數字（**389 passed ＋ 0 skipped**、端點仍為 20）。
      （總覽 §5「規格摘標」那一段已經有 `tests/fakes.py` 補鍵、`git status -- app/` 不會是空的
      這兩列，不必重複補；只有**一處措辭**要順手對齊：總覽寫「`test_ask_three_paths.py` 三處在用」，
      精確講是**兩顆靠對照表查表**（第 318、405 行），第 265 行只是寫著同一個字串、
      直接呼叫 retriever 不經路由——**結論不變：只准加、不准改**。）
- [ ] `git status` 看一次完整變更清單，**逐檔自己 review 一遍**。
- [ ] **不要 commit**（沿用產品負責人既有指示）。
      `docs/plan/unfinish/` → `finish/` 的歸檔依慣例**隨 commit 執行**，時機由產品負責人決定。

---

## 5. ASCII 圖

### 5.1 「這週」的 7 天窗，與四個候選日期的關係

```text
   ────────────┬────────────┬────────────┬────────────────────┬────────▶ 到期日
           2026-08-18   2026-08-21   2026-08-25           2026-09-18
               │            │            │                    │
               │            │            │                    └─ ✘ 規格「現在」寫的日期
               │            │            │                       ＝今天＋31 天，遠在窗外
               │            │            │                       ＝步驟三之前那條紅的原因
               │            │            └─ ⚠ due_before ＝今天＋7 天 ＝ 窗的上界
               │            │               SQL 是 <=，所以「含」08-25 當天
               │            │               ← 邊界值，規格 Example 刻意不挑它
               │            └─ ★ 本 phase 要改成的日期（星期五）
               │               離今天 3 天、離上界 4 天，兩端都不踩；
               │               這一週的星期日是 08-23，所以「往後 7 天」與
               │               「到本週日」兩種定義下它都在窗內
               └─ 今天：Given 現在時間為 "2026-08-18 10:00"（星期二）
                  ← 也是邊界（另一端），同樣不挑

   撈得到的範圍：  ◄══════════════════════════════════╣ 08-25（含當天）
                   ↑ 沒有下界：SQL 只有 due_date <= due_before，
                     所以「早就過期的」也會被撈出來。這是 MVP 的取捨，
                     不是 bug——本 phase 不動它。

   換算鏈（每一步都在不同的檔，都可注入、都有測試）：
     Given 現在時間 ──► get_now ──► get_today ──► today = 2026-08-18
     "這週" ──► RouteDecision.due_within_days = 7
     retrieval_service.task_search ──► due_before = today + 7 天 = 2026-08-25
     photo_repository.search_tasks ──► WHERE due_date IS NOT NULL AND due_date <= due_before
```

### 5.2 摘標前後，測試怎麼變

```text
  ── 摘標前（Phase 38〜50 期間；顆數不准動）────────────────────────────
     pytest -q  →  387 passed ＋ 2 skipped
     tests/integration/test_ask_feature.py（9 個）
       ├─ 條件過濾型問題走 metadata search          PASS  ┐
       ├─ 語意描述型問題走 vector semantic search   PASS  │
       ├─ 最近的照片以內容時間優先過濾…             PASS  │ Q1〜Q5
       ├─ 模糊問題走 vector semantic search         PASS  │ 既有五條 Rule
       ├─ 沒有任何照片時詢問                        PASS  │ （本 phase 完全不碰）
       ├─ 詢問在 Target 拍的收據                    PASS  │
       ├─ 詢問最近買過的飲料                        PASS  ┘
       ├─ 問跟我 MacBook 有關的全部                 SKIP  ◄── @未實作（第 75 行）
       └─ 問這週要交什麼                            SKIP  ◄── @未實作（第 91 行）

  ── 步驟一：只刪那兩個標籤（日期先不動）──────────────────────────────
       ├─ 問跟我 MacBook 有關的全部                 PASS  ← Phase 34 早就做好了
       └─ 問這週要交什麼                            FAIL
            AssertionError: assert 'vector semantic search' == 'task search'
            + 警告 RuntimeError: 無法判斷問題類型：這週要交什麼
            ＝ 假路由沒有「這週要交什麼」這個鍵（現有那個多一個問號）

  ── 步驟二：tests/fakes.py 補一行沒問號的鍵 ───────────────────────────
       └─ 問這週要交什麼                            FAIL  ← 紅往後移了一步
            AssertionError: 回答裡沒有提到「交 Project 2」：查無相關照片。
            ＝ 這才是「日期矛盾」：09-18 落在 7 天窗外，撈到空的

  ── 步驟三：規格待辦例子的到期日 2026-09-18 → 2026-08-21 ──────────────
       └─ 問這週要交什麼                            PASS

  ── 摘標後 ────────────────────────────────────────────────────────────
     pytest -q  →  389 passed ＋ 0 skipped
                   （387 ＋ 那 2 顆；skipped 那一段會整個消失）
```

---

## 6. 如果紅的原因跟預期不同怎麼辦（診斷指引）

下表是本 phase 動筆前**實際查證過**的每一個可能斷點。
對症狀之前先做一件事：**跑 `pytest tests/integration/test_ask_feature.py -k 這週 -v`**，
只跑那一顆，訊息才不會被另外八顆蓋掉；並且把 `Captured log call` 區塊看完
（`route_node` 的 fallback 警告就印在那裡）。

| 症狀 | 怎麼判別 | 最可能的原因 | 怎麼辦 |
|---|---|---|---|
| 刪完標籤，數字還是 387 ＋ **2 skipped** | `pytest tests/integration/test_ask_feature.py --collect-only -q -m skip` 仍印 `2/9` | `@未實作` 沒真的刪掉（可能刪成空行、或改成了註解 `# @未實作`——Gherkin 的註解仍是註解，但標籤沒了才算摘掉） | 整行刪除；再跑一次 `-m skip`，要印 `no tests collected (9 deselected)`（＝9 顆都在、但沒有任何一顆掛著 skip） |
| 收集階段就炸 `StepDefinitionNotFoundError` | 錯誤訊息會直接印出找不到的那一句中文 step | binder 少了那一步的定義 | **本次查證：12 個 step 全部都在**（見下方清單），正常不該發生。真的發生就先看是不是規格句子被改動了一個字 |
| **實體**那條紅在 `search_mode`，實際值 `vector semantic search`，且有 `RuntimeError: 無法判斷問題類型：跟我 MacBook 有關的全部` | 看 `Captured log call` | 假路由第 238 行那個鍵被人改過 | **本次查證：第 238 行的鍵與規格第 82 行的問句逐字相同**，正常不該發生。真的發生就把鍵改回規格原文 |
| **實體**那條紅在 `retrieved_photo_ids == []`（沒有 fallback 警告） | `search_mode` 已經是 `entity pin search` | `find_entity_by_name` 對不到——Given 建的實體名與 `RouteDecision.entity_name` 不一致 | 兩邊都該是「我的 MacBook」：規格第 81 行 vs `tests/fakes.py` 第 239 行 |
| **待辦**那條紅在 `search_mode`，且有 `RuntimeError: 無法判斷問題類型：這週要交什麼` | 看 `Captured log call` | ★ **這是預期中的第一個紅**（§4.1）：假路由缺沒問號的鍵 | 照 §4.3 補一行 |
| **待辦**那條紅在 `回答裡沒有提到「交 Project 2」：查無相關照片。`（**沒有** fallback 警告） | `search_mode` 已經是 `task search` | ★ **這是預期中的第二個紅**（§4.3）：日期落在窗外 | 照 §4.4 改日期 |
| **待辦**那條紅在 `回答裡沒有提到「交 Project 2」：依照片內容回答：待辦：…`（answer 有東西但不是那筆） | 回答字串裡有別的待辦標題 | 規格表格的欄位被改到（`title`／`due`／`photo_id` 三個欄名分別寫死在 binder 第 117／114／116 行） | 把表格欄名改回原樣；本 phase 只准改那一格日期 |
| **待辦**那條紅在 `KeyError: '1'` 之類 | 堆疊指向 binder 第 116 行 `context["id_map"][row["photo_id"]]` | 待辦表格的 `photo_id` 對不到上面照片表格的 `id` | 兩張表格的編號要對得上（規格第 96 行 `id=1`、第 99 行 `photo_id=1`） |
| 兩條都綠，但**全量**不是 389 | `pytest -q` 的尾巴；再 `git status --short` | 動到了不該動的東西（最常見：改了 `tests/fakes.py` 既有那個有問號的鍵，弄紅 `test_ask_three_paths.py`） | `git diff tests/` 逐行看；照 §3「明確不做」第 4 列還原 |
| 全量出現 `error`（不是 fail），訊息提到連線 | `docker compose ps` | 測試庫的 container 沒起來（Phase 47 之後測試庫住在 Docker 裡） | `docker compose -f compose.yaml up -d`，等 `db` 變 `(healthy)` 再跑 |

**binder 已預寫的 step（本次逐一查證，`tests/integration/test_ask_feature.py`）：**

| 行號 | 種類 | step | 兩條 Rule 誰要用 |
|---|---|---|---|
| 65 | Given | `現在時間為 "{moment}"` | 待辦那條 |
| 70 | Given | `系統中有底下照片` | 兩條都用 |
| 98 | Given | `系統中沒有任何照片` | （Q4 用） |
| 103 | Given | `照片 {spec_id} 釘上實體 "{name}"` | **實體那條**（`find_entity_by_name` → 沒有就 `create_entity` → `pin_entity`） |
| 111 | Given | `系統中有底下待辦` | **待辦那條**（讀 `title`／`due`／`photo_id` 三欄，`due` 空白＝無期限） |
| 123 | When | `使用者詢問 "{question}"` | 兩條都用（順便斷言 HTTP 200） |
| 130 | Then | `系統選擇的檢索方式為 "{mode}"` | 兩條都用 |
| 135 | Then | `時間過濾後的照片為底下照片` | （Q2 用） |
| 140 | Then | `回答依據的檢索結果為底下照片` | **實體那條** |
| 145 | Then | `使用者獲得查無相關照片的回覆` | （Q4 用） |
| 152 | Then | `回答提及底下物品` | （Q5 用） |
| 159 | Then | `回答依據的待辦如下` | **待辦那條**（比對 `answer` 字串裡有沒有那個標題） |

→ **兩條 Rule 需要的 8 個 step 全部都已預寫，一個都不缺**（第 103、111 行那兩個
是 2026-08-22 補規格時一併預寫的，從來沒被執行過——摘標後才第一次真的跑到）。

---

## 7. 驗收清單

- [ ] `docs/spec/features/自然語言詢問.feature` 的兩個 `@未實作` 已刪除（整行）
- [ ] 同檔待辦例子（`交 Project 2` 那一列）的到期日已改成 **`2026-08-21`**，**表格其他欄位一字未動**
      （原檔第 99 行；三步做完後它在第 102 行）
- [ ] 同檔檔頭已補上 **2026-08-23 產品負責人核准解除唯讀**的紀錄（5 行，比照 `上傳照片.feature`）
- [ ] `git diff docs/spec/` 只動到這一個檔，且只有上述三處改動；另外六份 `.feature` 完全沒出現
- [ ] `tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS` **新增**（不是取代）`"這週要交什麼"` 一行
- [ ] 三段紅／綠都親眼看過：①摘標後待辦那條紅在 `search_mode`（含 `RuntimeError` 警告）→
      ②補鍵後紅在「回答裡沒有提到『交 Project 2』：查無相關照片。」→ ③改日期後全綠
- [ ] `pytest tests/integration/test_ask_feature.py -v` ＝ **9 passed、0 skipped**
- [ ] `pytest -q` ＝ **389 passed ＋ 0 skipped**
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數相同
- [ ] `git status --short -- app/` 與 §4.0 拍的動筆前快照 `diff` **零差異**
      （產品程式碼一行未動；本增量不 commit，所以那份清單本來就不是空的）
- [ ] `tests/conftest.py` 的 `pytest_bdd_apply_tag` **還在**（沒被順手刪掉）
- [ ] `CLAUDE.md` 現況段與指令區的顆數／摘標敘述都已更新，且**兩處說法一致**
- [ ] `phase-00-增量四總覽.md` 的 §2／§5／§6 都已打勾，完成註記寫上 389 ＋ 0
- [ ] **沒有 commit**

---

## 8. 常見陷阱

1. **把假路由既有那行「這週要交什麼？」改掉，而不是新增一行。**
   有問號那個鍵有**兩顆測試靠它查表**（`tests/integration/test_ask_three_paths.py`
   第 318 行 `test_待辦問句走待辦路`、第 405 行 `test_端點待辦問句回的是來源照片id`），
   改掉兩顆都會紅。**兩個鍵並存**，成本只有一行。

2. **順手刪掉 `tests/conftest.py` 的 `pytest_bdd_apply_tag`。**
   摘完之後全專案暫時一個 `@未實作` 都沒有（本次查證：七份 `.feature` 裡只有這兩處），
   看起來像死碼。但它是**安全網**——日後補新規格再標一次就自動 skip；
   刪了之後下一個人標了標籤卻發現沒效果，會很難查。留著。

3. **把到期日改成 2026-08-25（邊界值）。**
   `<=` 是含當天，所以 08-25 確實會綠。但規格 Example 從此踩在邊界上：
   日後任何人把 `<=` 改成 `<`、或把 `+7` 調成 `+6`，紅的會是**規格驗收**，
   看起來像規格錯了。邊界另有專門的測試守著（§4.4 理由 2），規格 Example 不該兼差。

4. **順手「整理」Q1〜Q5。** 那五條從 Phase 12 起一路全綠、是回歸基準；
   這次核准的範圍只有那兩條新 Rule 與一格日期。看到想改的先記下來，留給下一個增量。

5. **為了讓它綠而去改產品程式碼。**
   最常見的三種手滑：把 `due_within_days` 從 7 改大、把 `search_tasks` 的 `<=` 拆掉、
   或在 `task_search` 裡多加一個「沒撈到就全部回」的保底。
   紅的是**規格自己寫錯了日期**，不是程式算錯了窗——把筆誤搬進程式，
   等於讓「這週」以後永遠不準。`app/` 底下一行都不准動（§3 明確不做第 3 列）。

6. **忘了在檔頭記核准來源。** `docs/spec/` 是唯讀規格區，
   沒有那 5 行，下一個人 `git log` 只會看到「有人動了唯讀檔」。
   `上傳照片.feature` 檔頭已經有三筆同格式紀錄，照抄。

7. **以為「摘標」要改 conftest 或 binder。** 不用。
   `@未實作` 四個字只在 `pytest_bdd_apply_tag` 裡有意義，
   標籤一刪 skip 就解除——**產品碼、conftest、binder 全部不動**。

8. **只跑 binder 就收工。** 一定要跑全量（`pytest -q`）＋零 Ollama 那一輪：
   本 phase 動了 `tests/fakes.py`，那是**全專案共用的假件**，
   只跑一個檔看不出有沒有波及別人。

9. **自己 commit。** 沿用既有指示——改完先給產品負責人檢視。
   `unfinish/` → `finish/` 的歸檔也是隨 commit 才做，不要提前搬檔案。
