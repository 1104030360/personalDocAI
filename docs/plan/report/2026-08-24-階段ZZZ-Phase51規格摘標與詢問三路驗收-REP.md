# 階段 ZZZ 完成報告：Phase 51 —— 規格摘標與詢問三路驗收

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-51-規格摘標與詢問三路驗收.md`（34 個 checkbox 全數打勾）
> 產出：`docs/spec/features/自然語言詢問.feature`（3 處）、`tests/fakes.py`（+4 行）、
> `CLAUDE.md`、總覽——**`app/` 一行未動**
> **全量：402 passed ＋ 2 skipped → 404 passed ＋ 0 skipped**

---

## 1. 實作邏輯

把兩條掛著 `@未實作` 的 Rule 摘標。**功能 Phase 34 早就做好了，本 phase 不寫任何新功能。**

`@未實作` 這四個字**只在 `tests/conftest.py` 的 `pytest_bdd_apply_tag` 裡有意義**——
標籤一刪 skip 就解除，產品碼、conftest、binder 全部不動。

### 為什麼堅持分三步看紅

摘標後會踩到**兩個**絆腳石，而且**第一個會把第二個遮住**。
一次改好就看不到這條因果鏈，日後有人動壞了不知道從哪裡查。所以照計畫走 TDD 的紅→紅→綠。

---

## 2. 步驟與實測結果（三段紅／綠都親眼看過）

### 2.0 動筆前

```text
pytest tests/integration/test_ask_feature.py --collect-only -q          →  9 tests collected
pytest tests/integration/test_ask_feature.py --collect-only -q -m skip  →  2/9 (7 deselected)
git status --short -- app/ > /tmp/phase51-app-before.txt                →  空
tests/conftest.py 第 99〜105 行的 pytest_bdd_apply_tag                   →  在
```

### 2.1 ★ 紅 ①：只刪兩個標籤（**刻意不改日期**）

由下往上刪（先第 91 行、再第 75 行），避免行號漂移：

```text
1 failed, 8 passed, 1 warning in 0.88s          ← 0 skipped 了 ✅

FAILED tests/integration/test_ask_feature.py::test_問這週要交什麼
  assert context["response"].json()["search_mode"] == mode
  AssertionError: assert 'vector semantic search' == 'task search'
  WARNING: 路由呼叫失敗，fallback 成語意查詢
  RuntimeError: 無法判斷問題類型：這週要交什麼
```

**與計畫預測逐字相符。** 實體那條**一摘就綠**（Phase 34 的功能、binder 的五個 step、
假路由的登記三者早就到位，唯一擋著它的就是那個標籤）。

> ⚠️ 表面看是「檢索方式不對」，`RuntimeError` 那行才是真話：
> 假路由的對照表裡**沒有**「這週要交什麼」這個鍵（既有那行是「這週要交什麼**？**」，多一個全形問號）。
> 查不到鍵 → 丟例外 → `route_node` 依設計 fallback 成語意查詢。
> **日期矛盾這時候還輪不到上場**，因為根本沒走到待辦那一路。

### 2.2 檔頭補核准紀錄（5 行）

`docs/spec/` 是唯讀規格區，沒有這段紀錄，下一個人 `git log` 只會看到「有人違規動了唯讀檔」。
比照 `上傳照片.feature` 的既有寫法，**現有第 1〜5 行一個字未改**（那是時序紀錄，不是現況描述），
新的一筆往下疊。

### 2.3 ★ 紅 ②：假路由補一個鍵（測試碼，不是產品碼）

在 `tests/fakes.py` 的 `DEFAULT_ROUTE_DECISIONS` **新增**（不是取代）一行沒問號的鍵：

```text
1 failed, 8 passed                              ← 仍 1 紅，但位置往後移了一步

  assert row["title"] in answer, f"回答裡沒有提到「{row['title']}」：{answer}"
  AssertionError: 回答裡沒有提到「交 Project 2」：查無相關照片。
  assert '交 Project 2' in '查無相關照片。'

grep -c "路由呼叫失敗" → 0                       ← fallback 警告消失了 ✅
```

**這才是日期矛盾真正現形的樣子**：路由判對了、走了待辦路，但 `search_tasks` 用
`due_date <= 2026-08-25` 去撈，`2026-09-18` 撈不到 → 檢索結果空 → 假回答模型回「查無相關照片。」

> **為什麼是「加一行」不是「改那一行」**：有問號那個鍵有**兩顆測試真的靠它查表**
> （`test_ask_three_paths.py` 第 318、405 行）。改掉會連帶弄紅——那是**我弄壞的**，不是規格的問題。
> 兩個鍵並存，代價只有一行。
>
> **為什麼不是把規格的問句加上問號去遷就假件**：方向要對——規格是 source of truth，
> 假件是為了服務規格而存在的。補一行是把假件對齊規格；改規格是反過來。

### 2.4 綠：改那一格日期

```diff
-        | 交 Project 2 | 2026-09-18 | 1        |
+        | 交 Project 2 | 2026-08-21 | 1        |
```

兩個日期**剛好一樣長（10 字元）**，Gherkin 表格的 `|` 對齊不必重排。

```text
pytest tests/integration/test_ask_feature.py -v  →  9 passed, 0 skipped  ✅
  … test_問跟我_macbook_有關的全部 PASSED
  … test_問這週要交什麼           PASSED
```

**為什麼挑 `2026-08-21`**（四個理由，計畫 §4.4）：① 必須在窗內（`2026-09-18` 出局）
② 不挑上界 `2026-08-25`（邊界值——規格 Example 是示範不是邊界測試，邊界另有專門測試守著；
踩邊界會讓「有人把 `<=` 改成 `<`」變成規格驗收紅，看起來像規格錯了）
③ 不挑今天或更早（今天是另一端邊界；更早的日期配「這週**要交**什麼」讀起來莫名其妙）
④ `08-21` 離兩端都有距離，而且 08-18 是週二、08-21 是週五、該週日是 08-23
——**「往後 7 天」與「到本週日」兩種定義下都在窗內**。

### 2.5 全量回歸

```text
pytest -q                                      →  404 passed, 1 warning in 19.13s
                                                  （skipped 那一段整個消失，正常）
OLLAMA_BASE_URL=http://localhost:9 pytest -q    →  404 passed, 1 warning in 19.90s  ← 同顆數
三份規格 binder -v                              →  27 passed；SKIPPED 出現次數 = 0  ✅
```

### 2.6 改動範圍（逐項驗）

```text
git diff --stat docs/spec/  →  1 file changed, 6 insertions(+), 3 deletions(-)
                               ← 只有 自然語言詢問.feature；另外六份完全沒出現 ✅
                               ← 6 進（5 行檔頭 ＋ 1 行日期）／3 出（2 個標籤 ＋ 1 行日期）
                                 與計畫預測的數字完全一致

git status --short -- app/ | diff /tmp/phase51-app-before.txt -
  →  ✅ app/ 與動筆前完全相同（兩份都是空的）

grep -c "pytest_bdd_apply_tag" tests/conftest.py  →  1   ← 安全網還在，沒被順手刪
```

### 2.7 文件收尾

| 檔案 | 改動 |
|---|---|
| `CLAUDE.md` 現況段 | 顆數 `402 passed＋2 skipped` → **`404 passed＋0 skipped`**；把「規格擴充……**摘標屬產品負責人**——摘標前注意 due=2026-09-18 與『這週』矛盾」整段改寫成**已完成**的敘述（核准來源、改了哪三處、為什麼補假路由的鍵只能加不能改、hook 保留） |
| `CLAUDE.md` 指令區 | 「只跑規格檔 binder（……詢問的兩條 `@未實作` Rule 會 skip，摘標屬產品負責人）」→「2026-08-24 摘標後**全綠、零 skip**，共 27 顆」。**兩處說法一致**（`grep` 確認舊敘述殘留 ＝ 0） |
| 總覽 | §2 表格 51 打勾、§5「規格摘標」整段打勾、§6 勾選區打勾；完成註記從「階段丙收工」改寫成「**增量四完結**」，並補上最終數字 404＋0 |

---

## 3. 測試方式

**這一 phase 的測試方式就是它的產出**——不是多寫測試，而是讓既有的兩顆從 skip 變 pass。
關鍵在於**每一步都先看紅、確認紅的原因與預測相符，再修**：

| 步驟 | 預期的紅 | 怎麼確認「紅對了」 |
|---|---|---|
| 只摘標 | `search_mode` 不對 | 看 `Captured log` 有沒有 `RuntimeError: 無法判斷問題類型` ——有，代表是查表失敗不是日期問題 |
| 補鍵 | 「回答裡沒有提到『交 Project 2』」 | `grep -c "路由呼叫失敗"` ＝ **0**，代表 fallback 警告消失、真的走了待辦路 |
| 改日期 | 全綠 | 9 passed、0 skipped |

收尾另外用三種方式交叉確認沒有波及別人：全量、零 Ollama 全量、三份 binder 單獨跑。
（**動了 `tests/fakes.py` ＝全專案共用的假件，只跑一個檔看不出有沒有波及。**）

---

## 4. 遇到的問題與解法

**這一 phase 沒有意外**——計畫把兩個絆腳石、三段紅綠、行號漂移、四個候選日期的取捨
都預先寫清楚了，實際跑起來逐字相符。真正做對的兩件事：

| # | 事情 | 做法 |
|---|---|---|
| 1 | **行號會漂**：刪掉第 75 行的那一刻，原本的第 91 行就變成第 90 行 | 用程式**由下往上刪**（先 91、再 75），而且刪之前先 `assert lines[ln-1].strip() == '@未實作'` ——確認刪的真的是標籤行，不是憑行號硬刪 |
| 2 | 計畫 §4.3 那段程式碼**是「插入」不是「整段貼上」**（頭尾兩行是既有的定位錨點） | 用 `Edit` 精準比對既有那兩行、只在中間插入四行，不整段覆蓋。事後 `git diff` 確認 `tests/fakes.py` 只 +4 行 |

---

## 5. 測試結果

**全數通過。** Phase 51 的 34 個 checkbox 全部打勾。

```text
── 摘標前後 ──────────────────────────────────────────────
   前：402 passed ＋ 2 skipped
   後：404 passed ＋ 0 skipped      （skipped 那一段整個消失）

   test_ask_feature.py（9 個）全綠，其中最後兩顆是本 phase 解封的：
     test_問跟我_macbook_有關的全部   （entity pin search）
     test_問這週要交什麼             （task search）

   端點仍為 20；app/ 一行未動；pytest_bdd_apply_tag 保留
```

**沒有 commit**（沿用產品負責人既有指示）；`unfinish/`→`finish/` 歸檔隨 commit 執行。

**增量四（Phase 38〜51）到此全部完成。**
