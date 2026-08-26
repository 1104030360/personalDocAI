# Phase 55：瀏覽頁拿掉待決定 tab（★ 階段甲收尾，閘門 G1）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。

> 🎯 **一句話目標：** 把 `app/static/browse.html` 裡「待決定」那一個分頁**整段刪掉**
> （它在 Phase 52 已經搬到 `/ui/pending.html` 了），分頁列只剩「資料夾｜待辦」，
> 而且**沒有 query 時預設顯示資料夾卡片**（現在無 query 是待決定）。
> 做完就是 **★ 閘門 G1** ——階段甲交給產品負責人驗收。

**為什麼要做這個：**
Phase 52 把待決定搬到新頁、Phase 53 把入口接到頂欄，
所以現在 `browse.html` 上**同時有兩個待決定入口**（頂欄一個、分頁列一個），
點進去看到的是一模一樣的東西。這是刻意留的暫時狀態——
Phase 52〜54 每一步都留著「已知是好的舊路」可以對照，
現在三步都驗過了，把舊的那一條清掉。

**留兩份會怎樣（為什麼一定要刪）：**
① 使用者不知道該點哪一個，會以為那是兩種不同的東西；
② 之後 Phase 70 改待決定的彈窗鏈時，改了新頁沒改舊頁 → 兩邊行為不一樣；
③ 本專案的規矩是**不留過渡產物**——沒人用的程式碼，下一個人不敢刪。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| tab（分頁／頁籤） | 頁面裡面那一排可以切換內容的連結，例如現在 `browse.html` 上的「待決定（3）｜資料夾｜待辦（2）」。**它跟頂欄的四格導覽不是同一個東西**——頂欄換的是「哪一頁」，分頁列換的是「同一頁裡的哪一區」 |
| query string（查詢字串） | 網址問號後面那一段。`browse.html?tab=tasks` 的 `tab=tasks` 就是。這一頁把「現在看哪一區」寫在網址上，所以上一頁／重新整理／加書籤通通免費就有 |
| 轉址（redirect） | 打開網址 A 卻自動被送到網址 B。design5 §6.3 明文**不做**這件事，理由見 §3 的表格 |
| 閘門（gate） | 一個「人必須點頭才能往下走」的檢查點。★ G1 是產品負責人照 design5 §12「階段甲」的四條逐項驗收。**實作者不可以自己勾掉** |
| 收件箱（inbox） | 名字叫「未分類(收件箱)」的資料夾，`GET /folders` 裡 `is_inbox` 為 `true` 的那一筆。待決定牆＝它裡面的照片 |

---

## 1. 對應 design5.md 章節

- **D1**（待決定移到頂欄）
- **§0 階段甲**（「瀏覽頁拿掉待決定 tab」那一行；以及
  「何時算過」第三條：**瀏覽頁預設是資料夾、沒有待決定 tab**）
- **§1.1**（推翻 design2.md D4「瀏覽頁頂部分待決定｜資料夾」
  與 design3.md D15「瀏覽入口為待決定｜資料夾｜待辦」）
- **§2 流程圖最後兩行**（`瀏覽 /ui/browse.html`：【資料夾】｜【待辦】← 沒有待決定 tab）
- **§6.3**（整節：拿掉待決定 tab；無 query 時預設資料夾卡片；
  `?tab=folders` 仍可用、`?tab=tasks`／`?folder=N` 不變；
  **不要做「舊書籤 browse.html 自動轉址到 pending」**）
- **§9 測試策略**（「前端契約：……`browse.html` 原始碼不再當預設待決定入口（可用字串釘）」）
- **§11 會動到的檔**（第 2 列 `app/static/browse.html`｜甲｜拿掉待決定 tab；預設資料夾）
- **§12 階段甲**（四條驗收 ＝ 本 phase 結尾的 ★ G1）

---

## 2. 前置條件

- **Phase 52 已完成**：`/ui/pending.html` 存在、內容正確。
  **這是硬前提**——本 phase 要刪掉舊入口，沒有新入口就等於把待決定弄不見了。
- **Phase 53 已完成**：五頁頂欄四格，點得到 `/ui/pending.html`。
- **Phase 54 已完成**：歸類彈窗窗頂有原圖、「稍後再說」文案已改。
- 開工基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**412 passed ＋ 0 skipped**。
  （⚠ 絕對不要同時跑兩份 pytest。）

- 三個新東西都還活著：

```bash
curl -k -s -o /dev/null -w "pending.html %{http_code}\n" https://127.0.0.1:8000/ui/pending.html
grep -c 'href="/ui/pending.html"' app/static/browse.html      # 預期 1（頂欄那一格）
grep -c 'id="fm-image"' app/static/folder_modal.js            # 預期 1（Phase 54 加的）
```

- **待決定裡至少有一張照片**（G1 驗收第 4 條要實際做一次「定案 → N 減一」）。
  沒有的話先到上傳頁上傳一張、在抽屜窗按「稍後再說」。

- 服務是**開發模式**（`docker compose ps --no-trunc` 的 `COMMAND` 欄有 `--reload`）。

---

## 3. 範圍

### 做

- 改 `app/static/browse.html`：
  - 刪掉 `showPending()` 與 `接著釘實體()` 兩個函式（整段）；
  - 刪掉兩行 `<script src>`（`folder_modal.js`、`entity_modal.js`）——這一頁不再需要歸類彈窗；
  - `renderTabs()` 從三格改兩格（參數也跟著少一個）；
  - `showFolderList()`／`showTasks()` 跟著調整（不再需要查收件箱張數）；
  - `start()` 的預設分支改成 `showFolderList()`；
  - 檔頭那張「狀態都寫在網址上」的對照表更新。
- 在 `tests/integration/test_nav_header.py` **追加 3 顆**前端契約測試。
- 走完 §6 的驗收清單，然後把 **★ G1** 交給產品負責人。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| **做「舊書籤 `browse.html` 自動轉址到 `pending.html`」** | **design5 §6.3 明文不做**：「頂欄已經有待決定，多一個 302 容易繞」。實務上的害處是：`browse.html` 現在的預設畫面是資料夾卡片，如果又加一條「沒帶 query 就跳到 pending」，那 `browse.html` 這個網址就永遠打不開資料夾了——你得記得打 `?tab=folders`。**寧可讓舊書籤看到資料夾卡片**（那是一個合理的畫面），也不要讓一個網址自己跑掉 |
| 讓「未分類（收件箱）」以資料夾卡片的形式出現在資料夾牆 | design2.md D4 起就排除它了，design5 沒有推翻這一條。它的內容就是頂欄那一格的待決定頁；同一批照片出現在兩個地方只會讓人以為有兩份 |
| 動 `showFolderPhotos()`（資料夾縮圖牆） | 它的行為（點照片開唯讀詳情窗）是 design4 Phase 39 定的，design5 沒有改它 |
| 動 `照片卡()`／`el()`／`保護數字單位()`／`getJson()` | `showFolderPhotos()` 與 `showTasks()` 還在用它們。**特別是 `照片卡()` 裡那段「片語 = "待決定分頁的"」不要刪**——那不是分頁邏輯，是 Phase 44 加的中文換行保護，而且有既有測試在掃它 |
| 刪 `<script src="/ui/photo_detail_modal.js">` | 資料夾牆與待辦列都還在用那顆唯讀詳情窗 |
| 動 `app/static/pending.html` | 它在 Phase 52 就做好了、Phase 53〜54 也驗過了。本 phase 只刪舊的那一份 |
| 動 `folder_modal.js`／`entity_modal.js` 這兩個**檔案** | 只是 `browse.html` 不再引用它們；檔案本身還在被 `pending.html` 與 `classify_chain.js` 用。**千萬不要刪檔** |
| 修 `classify_chain.js` 第 53 行（「已放進待決定區，之後到瀏覽頁的「待決定」分頁完成歸類。」）與 `upload.html` `pdf摘要()` 裡（「其餘頁留在待決定區，可到瀏覽頁的「待決定」分頁完成歸類。」）這兩句舊文案 | 那兩句寫在**上傳頁／鏡頭頁的結果卡片**上，主人是 **Phase 68／69**（design5 §11 把上傳頁與鏡頭頁的文案改寫排在階段丙）。本 phase 做完、一直到 Phase 68／69 之前，它們會指向一個不存在的分頁——**這是已知的、有主的過期文案，是預期不是 bug**，見 §7 陷阱 5（★G1 要當面交代） |
| 改任何**產品** Python（`app/` 底下） | 本 phase **產品 Python 零變更**、端點仍 **20**。（測試 Python 例外：§4.8 會在 `tests/integration/test_nav_header.py` 加 `import re` 與 3 顆測試——§6.1 的驗證指令掃的也只有 `app/` 底下的六個 pathspec） |
| 用 `alert`／`innerHTML` 塞動態內容 | 全站鐵律 |

---

## 4. 實作步驟

> ⚠ **本節引用的行號量的是「增量四收尾時」的 `browse.html`**（也就是 Phase 53 動它之前）。
> Phase 53 已經把頁首換成四格、又在 `</header>` 下方貼了 25 行計數片段，
> 所以你現在打開檔案，下面說的「第 24〜26 行」實際會落在**更後面**（整體往後移了約 26 行）；
> 而且從 §4.1 開始每刪一段，後面的行號又會往前移。
> **一律用內容（註解文字／函式名）對位，行號只當相對位置的導航。**

### 4.1 刪掉兩行 `<script src>`

- [ ] 現在 `browse.html` 第 24〜26 行是三行：

```html
<script src="/ui/folder_modal.js"></script>
<script src="/ui/entity_modal.js"></script>
<script src="/ui/photo_detail_modal.js"></script>
```

  刪掉前兩行，只留下：

```html
<script src="/ui/photo_detail_modal.js"></script>
```

  **理由**：待決定牆搬走之後，這一頁唯一會開的窗是**唯讀詳情窗**
  （資料夾牆點照片、待辦列點一列都是它）。歸類窗與實體窗這一頁再也用不到。
  **不要**「留著以防萬一」——多載入兩支 JS 就多兩份會被誤用的全域函式。

### 4.2 更新檔頭的網址對照表

- [ ] 把檔頭「狀態都寫在網址上」那一段註解、**連同緊接在下面的三行 `const`**
      （原第 30〜37 行）一起換成（三行 `const` 內容不變，照抄即可）：

```javascript
// 狀態都寫在網址上（上一頁／重新整理／書籤才會正常）：
//   browse.html               → 資料夾分頁（**預設**；design5.md §6.3 起改成這個）
//   browse.html?tab=folders   → 資料夾分頁（明寫也可以，舊書籤仍然有效）
//   browse.html?tab=tasks     → 待辦分頁（design3.md D15 的第三入口）
//   browse.html?folder=N      → 某個資料夾的縮圖牆（點照片開唯讀詳情窗）
//
// 「待決定」不在這一頁了——它在頂欄的「待決定（N）」那一格（design5.md D1、§6.3）。
//（這段註解刻意不寫出待決定頁的網址：契約測試斷言那個網址在本檔**只出現一次**，
//  就是頂欄那一格的連結。）
// ⚠ 刻意**不做**「舊書籤 browse.html 自動轉址到 pending」（design5.md §6.3 明文）：
//    頂欄已經有那一格，多一個轉址只會讓「browse.html」這個網址自己跑掉。
const 網址參數 = new URLSearchParams(location.search);
const folderIdInUrl = 網址參數.get("folder");
const tabInUrl = 網址參數.get("tab");
```

### 4.3 `renderTabs()` 從三格改兩格

- [ ] 把第 60〜77 行整個函式（含上面的註解）換成：

```javascript
// 兩個分頁的頁籤列。待決定升到頂欄之後這裡只剩兩格（design5.md §6.3）。
// 「未分類（收件箱）」仍然不以資料夾卡片出現——它的內容就是頂欄那一格的待決定頁；
// 「待辦」是使用者按過「建立」的任務清單，不是待決定的照片。
function renderTabs(active, taskCount) {
  const tabs = el("nav", "tabs");
  tabs.setAttribute("aria-label", "瀏覽分頁");
  const folders = el("a", "tab", "資料夾");
  folders.href = "/ui/browse.html?tab=folders";
  const tasks = el("a", "tab", "待辦（" + taskCount + "）");
  tasks.href = "/ui/browse.html?tab=tasks";
  const 目前 = { folders: folders, tasks: tasks }[active];
  目前.setAttribute("aria-current", "true");
  tabs.appendChild(folders);
  tabs.appendChild(tasks);
  view.appendChild(tabs);
}
```

  變動有三處：參數少了 `pendingCount`、少建一個 `pending` 連結、
  `目前` 的對照表少一個鍵。其餘一字不動。

### 4.4 刪掉 `接著釘實體()` 與 `showPending()`

- [ ] 把第 116〜192 行**整段刪掉**——從這行註解：

```javascript
// 彈窗 2【實體】：待決定分頁的補完鏈（design3.md §2.1）。
```

  一路刪到 `showPending()` 的結尾大括號（`view.appendChild(wall);` 下面那個 `}`），
  也就是下面這行註解**之前**：

```javascript
// ---------- 分頁二：資料夾卡片 ----------
```

  刪掉的是兩個完整函式：`async function 接著釘實體(photoId)` 與 `async function showPending()`。
  **這兩段的行為在 Phase 52 已經搬進 `pending.html` 了**（`接著釘實體()` 的程式碼逐字相同；
  `showPending()` 只拿掉分頁相關的幾行、換了空狀態文案——差異清單見 phase-52 §4.3），不是丟掉。

- [ ] 順手把段落標題註解的編號改掉（原本是「分頁二」「分頁三」，現在只剩兩個分頁）：

```javascript
// ---------- 分頁一：資料夾卡片（無 query 時的預設）----------
```

```javascript
// ---------- 分頁二：待辦（design3.md D13、D15；點一列開唯讀詳情窗＝design4.md D1）----------
```

- [ ] 順手把 `照片卡()` 上面那兩行說明註解也改掉——它還在講「兩個牆」，
      但待決定牆已經搬走、這一頁只剩資料夾縮圖牆在用它。改寫前（一字不差，方便搜尋）：

```javascript
// 一張照片卡。兩個牆（待決定、資料夾）都是可點的 <button>，
// 差別只在「點下去開哪一種窗」——那由各自的牆自己決定（見下面兩個 addEventListener）。
```

  改寫後：

```javascript
// 一張照片卡（資料夾縮圖牆用；點下去開唯讀詳情窗——監聽掛在 showFolderPhotos 的牆上）。
```

  **函式本體一個字都不動**（裡面的「片語」排版保護與既有測試都還指著它，見 §3 的表）。

### 4.5 `showFolderList()`：不再需要查收件箱

- [ ] 把 `showFolderList()` 的開頭——**含上面那行段落標題註解、一路到 `renderTabs(...)`
      那一行為止**——換成：

```javascript
// ---------- 分頁一：資料夾卡片（無 query 時的預設）----------
async function showFolderList() {
  const folders = await getJson("/folders");
  const tasks = await getJson("/tasks");    // 只為頁籤計數；本地服務多一個小 GET 無妨

  view.textContent = "";
  renderTabs("folders", tasks.length);
```

  變動：刪掉 `const inbox = folders.find(…)` 那一行、`renderTabs` 少一個參數。
  **底下畫卡片的那一段（含 `filter(function (f) { return !f.is_inbox; })`）一字不動**——
  收件箱仍然不出現在資料夾牆上。

### 4.6 `showTasks()`：連 `/folders` 都不用打了

- [ ] 把 `showTasks()` 的開頭——**含上面那行段落標題註解、一路到 `renderTabs(...)`
      那一行為止**——換成：

```javascript
// ---------- 分頁二：待辦（design3.md D13、D15；點一列開唯讀詳情窗＝design4.md D1）----------
async function showTasks() {
  const tasks = await getJson("/tasks");    // 先到期的在前、沒到期日的最後（排序在後端）

  view.textContent = "";
  renderTabs("tasks", tasks.length);
```

  變動：整個 `GET /folders` 那兩行拿掉了——它原本**只是**為了頁籤上的「待決定（N）」數字。
  現在那個數字在頂欄，由 Phase 53 的計數片段負責，這裡不必再算一次。
  **底下畫待辦列的那一大段一字不動。**

### 4.7 `start()`：預設改成資料夾

- [ ] 把最後那個 `start()` 換成：

```javascript
// ---------- 進入頁面時決定畫哪一個 ----------
(async function start() {
  try {
    if (folderIdInUrl) {
      await showFolderPhotos(folderIdInUrl);
    } else if (tabInUrl === "tasks") {
      await showTasks();
    } else {
      await showFolderList();   // 無 query 與 ?tab=folders 都走這裡（design5.md §6.3）
    }
  } catch (error) {
    view.textContent = "";
    view.appendChild(el("p", "message",
      "目前無法載入資料。請確認服務已啟動後重新整理頁面。"));
  }
})();
```

  變動：`else if (tabInUrl === "folders")` 那一支**整個拿掉**，
  資料夾變成 `else` 的預設分支。這樣 `?tab=folders`（舊書籤）與不帶 query 走的是同一條路，
  兩者都會看到資料夾卡片——**這就是「舊書籤仍然有效」的做法，不必用轉址**。

### 4.8 追加 3 顆前端契約測試

- [ ] 打開 Phase 53 建的 `tests/integration/test_nav_header.py`。
      **先**在檔案最上面的 import 區加一行（下面第三顆測試會用到正規表示式）：

```python
from __future__ import annotations

import re                      # ← 這一行是 Phase 55 加的
from pathlib import Path
```

- [ ] **再**在檔案**最後面**追加這一段（不要動前面已經有的 7 顆）：

```python
# ---------------------------------------------------------------------------
# Phase 55：瀏覽頁不再是待決定入口（design5.md §6.3、§9）
#
# 這三顆守的是「舊路真的被拔乾淨了」。之所以要釘住，是因為留一半不會壞掉、
# 只會變成兩個入口——畫面看起來正常，但 Phase 70 改待決定鏈的時候會改漏一邊。
# ---------------------------------------------------------------------------


def test_瀏覽頁不再是待決定入口():
    """showPending()／接著釘實體() 與兩支歸類彈窗都不該再出現在 browse.html。

    ⚠ 不能用「'待決定' not in 原始碼」來驗：
      ① 頂欄那一格本來就有「待決定」三個字（Phase 53 加的，是對的）；
      ② 照片卡() 裡有一段 const 片語 = "待決定分頁的"，那是 Phase 44 的中文
         換行保護（正式庫有一張照片的說明剛好含這幾個字），也是對的。
    所以改成逐項比對「函式與引用」，不是比對那三個字。
    """
    原始碼 = 讀("browse.html")

    assert "function showPending" not in 原始碼, "showPending() 沒刪乾淨"
    assert "接著釘實體" not in 原始碼, "接著釘實體() 沒刪乾淨"
    assert "openFolderModal" not in 原始碼, "browse.html 不該再開歸類彈窗"
    assert "openEntityModal" not in 原始碼, "browse.html 不該再開實體彈窗"
    assert "folder_modal.js" not in 原始碼, "browse.html 不該再載入歸類彈窗"
    assert "entity_modal.js" not in 原始碼, "browse.html 不該再載入實體彈窗"
    # 唯讀詳情窗還要用（資料夾牆與待辦列都靠它）
    assert "photo_detail_modal.js" in 原始碼

    # 無 query 時的預設分支＝資料夾卡片（design5.md §6.3）
    assert re.search(r"\}\s*else\s*\{\s*await showFolderList\(\);", 原始碼), (
        "無 query 時的預設不是資料夾卡片"
    )
    assert 'tabInUrl === "folders"' not in 原始碼, (
        "?tab=folders 應該併進預設分支，不必再獨立一支"
    )


def test_瀏覽頁的分頁列只剩資料夾與待辦():
    """renderTabs() 只建兩格；待決定那一格連建立的程式碼都不該留著。"""
    原始碼 = 讀("browse.html")

    assert 'el("a", "tab", "資料夾")' in 原始碼
    assert 'el("a", "tab", "待辦（"' in 原始碼
    assert 'el("a", "tab", "待決定（"' not in 原始碼, "分頁列還在建待決定那一格"
    assert 'renderTabs("pending"' not in 原始碼
    assert 原始碼.count('el("a", "tab",') == 2, "分頁列不是恰好兩格"


def test_瀏覽頁沒有做舊書籤轉址():
    """design5.md §6.3 明文不做轉址：頂欄已經有那一格，多一個 302 容易繞。

    browse.html 裡「/ui/pending.html」只該出現一次——就是頂欄那一格的連結。
    """
    原始碼 = 讀("browse.html")

    assert 原始碼.count("/ui/pending.html") == 1, (
        "browse.html 裡的 /ui/pending.html 不只頂欄那一個連結"
    )
    assert "location.replace" not in 原始碼
    assert "location.assign" not in 原始碼
    assert 'location.href = "/ui/pending.html"' not in 原始碼
```

- [ ] **先跑一次，確認它們會紅**（TDD 的規矩：沒看過紅的測試不算測試）。
      如果 §4.1〜4.7 都還沒做：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_nav_header.py -v
```

  預期：前 7 顆綠、**新的前 2 顆紅**；第 3 顆（`test_瀏覽頁沒有做舊書籤轉址`）是**護欄型**測試，
  它斷言的四件事在 Phase 53 之後本來就成立，所以**一開始就綠是正常的**，不是假測試
  （它守的是「不要順手加轉址」，2026-08-25 核對時修正這句預期）。

- [ ] 做完 §4.1〜4.7 之後再跑一次：**10 顆全綠**。

---

## 5. ASCII 圖：改版前三分頁 vs 改版後兩分頁

```text
 ┌──────────────────── 改版前（Phase 55 之前）─────────────────────┐
 │  PersonalDocAI   上傳照片  待決定（3）  瀏覽資料夾  問問題       │
 │                                        ━━━━━━━━━━               │
 │  ─────────────────────────────────────────────────────────────  │
 │  【待決定（3）】  【資料夾】  【待辦（2）】                       │
 │   ━━━━━━━━━━━━━                                                 │
 │   ↑ 預設就是這一格（browse.html 不帶 query）                     │
 │                                                                 │
 │  ⚠ 同一件事有兩個入口：頂欄的「待決定（3）」與這個分頁          │
 │    點進去看到的東西一模一樣。這是 Phase 52〜54 刻意留的暫時狀態  │
 └─────────────────────────────────────────────────────────────────┘

                                │
                                │  ★ Phase 55
                                ▼

 ┌──────────────────── 改版後（Phase 55 之後）─────────────────────┐
 │  PersonalDocAI   上傳照片  待決定（3）  瀏覽資料夾  問問題       │
 │                            ──────────  ━━━━━━━━━━               │
 │                            ↑ 待決定唯一的入口在這裡了            │
 │  ─────────────────────────────────────────────────────────────  │
 │  【資料夾】  【待辦（2）】                                       │
 │   ━━━━━━━━━                                                     │
 │   ↑ 現在 browse.html 不帶 query 的預設是這一格                   │
 │                                                                 │
 │  ┌────────────┐ ┌────────────┐ ┌────────────┐                  │
 │  │▔▔╮         │ │▔▔╮         │ │▔▔╮         │  ← 牛皮紙索引 tab │
 │  │  收據      │ │  飲食      │ │  文件      │                  │
 │  │ （4 張）   │ │ （2 張）   │ │ （0 張）   │                  │
 │  └────────────┘ └────────────┘ └────────────┘                  │
 │   ✗ 「未分類（收件箱）」仍然不以卡片出現                         │
 │      （它的內容＝頂欄那一格的待決定頁）                          │
 └─────────────────────────────────────────────────────────────────┘


 網址對照（哪些變了、哪些沒變）
 ─────────────────────────────────────────────────────────────────
   /ui/browse.html              待決定 ──────►  資料夾卡片   ★ 變了
   /ui/browse.html?tab=folders  資料夾   ──────►  資料夾卡片      沒變
   /ui/browse.html?tab=tasks    待辦     ──────►  待辦清單        沒變
   /ui/browse.html?folder=2     縮圖牆   ──────►  縮圖牆          沒變
   /ui/pending.html             （新）   ──────►  待決定牆    ★ 唯一入口

   ✗ **不做**「打開 /ui/browse.html 自動跳到 /ui/pending.html」
     舊書籤打開會看到資料夾卡片——那是一個合理的畫面，不是壞掉。
     真的加了轉址，browse.html 這個網址就永遠打不開資料夾了。


 這一頁還會開哪一種窗（改版後只剩一種）
 ─────────────────────────────────────────────────────────────────
   資料夾卡片 ──► 縮圖牆 ──點照片──┐
                                    ├──► 唯讀詳情窗（photo_detail_modal.js）
   待辦清單   ────────────點一列──┘      ×／Esc／點暗色區都能關
                                          **沒有任何改資料夾的按鈕**
                                          （design2.md 定案不可逆）

   ✗ 歸類窗（folder_modal.js）與實體窗（entity_modal.js）不再由這一頁載入
     ——它們搬到 /ui/pending.html 去了（檔案本身沒刪，還被 pending.html
       與 classify_chain.js 用著）
```

---

## 6. 驗收清單

### 6.1 自動化與掃碼

- [ ] **`browse.html` 真的刪乾淨了**：

```bash
cd /Users/linjunting/personalDocAI
grep -n "showPending\|接著釘實體\|openFolderModal\|openEntityModal" app/static/browse.html \
  || echo "OK：待決定那一整套都不在了"
grep -n "script src" app/static/browse.html
```

  預期：第一行印出 `OK：…`；第二行**恰好一行** `/ui/photo_detail_modal.js`。

- [ ] **分頁列恰好兩格**：

```bash
grep -c 'el("a", "tab",' app/static/browse.html
```

  預期：`2`。

- [ ] **沒有轉址**：

```bash
grep -c "/ui/pending.html" app/static/browse.html     # 預期 1（頂欄那一格）
grep -n "location.replace\|location.assign" app/static/browse.html \
  || echo "OK：沒有做轉址"
```

- [ ] **新測試全綠**：

```bash
source .venv/bin/activate
pytest tests/integration/test_nav_header.py -v
```

  預期：**10 passed**（Phase 53 的 7 ＋ 本 phase 的 3）。

- [ ] **全量顆數**：

```bash
pytest -q
```

  預期：**415 passed ＋ 0 skipped**（412 ＋ 3）。
  特別確認 `tests/integration/test_design4_error_paths.py` 那幾顆掃 `browse.html`
  原始碼的測試**仍然綠**——它們斷言的東西（`保護數字單位`、`片語`、
  兩個 `image.addEventListener("error"` 恰好兩次、
  「目前無法載入資料。請確認服務已啟動後重新整理頁面。」）
  全部都在 `照片卡()`／`showTasks()`／`start()` 裡，本 phase 都沒動到。

- [ ] **端點仍 20、零 Python 變更**：

```bash
git diff --stat -- app/api app/services app/repositories app/schemas app/core app/main.py
curl -k -s https://127.0.0.1:8000/openapi.json \
  | python3 -c "import json,sys; p=json.load(sys.stdin)['paths']; print(sum(len(v) for v in p.values()))"
```

  預期：第一個指令**沒有輸出**；第二個印出 `20`。

- [ ] **只動了兩個檔**：

```bash
git status --short -- app tests
```

  預期**本 phase 新增**的變動只有 ` M app/static/browse.html` 與
  ` M tests/integration/test_nav_header.py`（後者若整個檔還沒 commit 過就是 `??`）。
  Phase 52〜54 還沒 commit 的話，另外會看到它們留下的
  `pending.html`、四頁 header 的 ` M`（含 `upload.html`）、`folder_modal.js`、`style.css`
  ——那是上游 phase 的變動，不算本 phase 手滑；已 commit 就不會出現。兩種都對。
  **無論如何都不該**出現的是：`entity_modal.js`、`task_modal.js`、
  `photo_detail_modal.js`、`classify_chain.js`（本 phase 沒有任何理由碰它們）。

### 6.2 瀏覽器實操

- [ ] **1. `https://127.0.0.1:8000/ui/browse.html`（不帶 query）→ 看到資料夾卡片**，
      分頁列只有「資料夾｜待辦（M）」，**沒有待決定那一格**。
- [ ] **2. 舊書籤仍然有效**：`?tab=folders` → 一樣是資料夾卡片，而且網址**沒有自己跑掉**
      （網址列仍然是 `?tab=folders`，不是被轉去 `pending.html`）。
- [ ] **3. `?tab=tasks`** → 待辦清單，計數正確；點一列 → 唯讀詳情窗。
- [ ] **4. `?folder=N`** → 那個資料夾的縮圖牆；點一張 → 唯讀詳情窗；
      「← 回資料夾列表」按得回去。
- [ ] **5. 上一頁／重新整理**：在待辦分頁按上一頁 → 回資料夾；重新整理 → 停在同一格。
- [ ] **6. 待決定只剩頂欄一個入口**：從 browse 頁點頂欄「待決定（N）」→ 到 `/ui/pending.html`，
      內容正確、點一張會開**窗頂有原圖**的歸類窗。
- [ ] **7. Console 乾淨**：整趟操作沒有紅色錯誤。
      特別注意**不該**出現 `openFolderModal is not defined` 之類的錯誤——
      有的話代表 `browse.html` 裡還殘留呼叫，但 `<script src>` 已經拿掉了。
- [ ] **8. 上傳頁的三關鏈沒被波及**：上傳一張 → 抽屜（窗頂有圖）→ 實體 →〔有建議才〕待辦。
      這一項證明拿掉 `browse.html` 的引用**沒有**把共用檔弄壞。

---

```text
╔══════════════════════════════════════════════════════════════════════╗
║  ★ 閘門 G1 —— 階段甲驗收（這是**人**的動作）                        ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  ⛔ 下面四條由**產品負責人**親自在瀏覽器上做過、親口說「過」。       ║
║     **實作者不可以自己勾掉這四個框。**                               ║
║     沒有那句話之前，**不准開始 Phase 56**（也不准先偷做遷移腳本）。  ║
║                                                                      ║
║  為什麼要有這道閘門：階段乙的第一個破壞性動作是把 `POST /photos`     ║
║  的成功回應從 **201 改成 202**（收下 ≠ 已入庫）。那會連帶改寫幾十顆  ║
║  既有測試與兩份 BDD 規格 binder。**改下去就回不太來了**——           ║
║  所以階段甲的畫面必須先被人看過、確認就是他要的東西。                ║
║  （design5.md §0 的表寫的是「甲合併後即可」；把它落成一個            ║
║   「人明示點頭」的動作，是計畫層的落實，不是 design5 自己寫的字。）  ║
║                                                                      ║
║  ── design5.md §12「階段甲」四條，逐字照抄 ────────────────────────  ║
║                                                                      ║
║  [ ] 1. 頂欄為「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」          ║
║                                                                      ║
║  [ ] 2. 開 /ui/pending.html 看得到收件箱照片；點一張：               ║
║         彈窗**最上面是原圖**，下面仍是四個歸類出口                   ║
║                                                                      ║
║  [ ] 3. /ui/browse.html 預設是資料夾卡片，沒有待決定 tab；           ║
║         待辦 tab 仍在                                                ║
║                                                                      ║
║  [ ] 4. 定案後照片離開待決定、N-1；已定案不能再改夾                  ║
║                                                                      ║
║  ── 第 4 條怎麼做（照著走一次就好）────────────────────────────────  ║
║     ① 開 /ui/pending.html，記下頂欄的 N（例如 3）                    ║
║     ② 點一張照片 → 抽屜窗 → ② 下拉選一個真資料夾 → 「歸到這個資料夾」║
║     ③ 實體窗跳出 → 按「不釘，繼續」→ 頁面重載                       ║
║     ④ 那張照片**不在牆上了**；頂欄變成 N-1（例如 2）                 ║
║     ⑤ 到 /ui/browse.html?tab=folders → 點進剛才那個資料夾           ║
║       → 點那張照片 → 跳出來的是**唯讀詳情窗**                        ║
║       （右上角有 ×、按 Esc 關得掉、**沒有任何改資料夾的按鈕**）      ║
║                                                                      ║
║  ── 通過之後要留下什麼 ────────────────────────────────────────────  ║
║     產品負責人的「過」寫在哪裡都可以（對話、dev-prompt 檔、           ║
║     `docs/plan/report/` 的一份 REP），但**要留得下來**——            ║
║     Phase 49 的檔頭就是這樣記 G1 的：引用產品負責人那句話的出處。    ║
║                                                                      ║
║  ── 沒過怎麼辦 ────────────────────────────────────────────────────  ║
║     回到出問題的那一個 phase 修（52／53／54／55 各自的範圍很窄，     ║
║     照 §3 的表就找得到是誰的責任），修完再重跑一次這四條。           ║
║     **不要**「先做 Phase 56，反正它跟畫面無關」——總序不可對調       ║
║     （design5.md §0）。                                              ║
╚══════════════════════════════════════════════════════════════════════╝
```

> ★ G1 驗收時要**當面交代的兩件已知事項**（都不是 bug，先講免得被當缺陷退回）：
>
> 1. **上傳頁／鏡頭頁結果卡上的兩句舊文案**（`classify_chain.js` 的「…之後到瀏覽頁的
>    「待決定」分頁完成歸類。」與 `upload.html` `pdf摘要()` 的「…可到瀏覽頁的「待決定」
>    分頁完成歸類。」）從本 phase 起指向一個已不存在的分頁——主人是 Phase 68／69，
>    這段期間看到它是**預期**（§7 陷阱 5）。
> 2. **「AI 模型」開關目前只在上傳／問問題／鏡頭桌面三頁**；design5 §6.1 的頂欄示意圖
>    畫了開關、但沒有指派誰補到瀏覽／待決定兩頁——要不要補齊是**未指派的產品決策**，
>    請產品負責人當場裁決（完整說明在 phase-53 §3 的「明確不做」表；沒說要補就維持現況）。

---

## 7. 常見陷阱

1. **刪過頭：把 `照片卡()` 也刪了**。
   `showFolderPhotos()`（資料夾縮圖牆）還在用它。刪了之後點進任何資料夾都會噴
   `照片卡 is not defined`。**只刪 `接著釘實體()` 與 `showPending()` 兩個函式**。

2. **刪過頭：把 `照片卡()` 裡「片語 = "待決定分頁的"」那一段刪了**，
   因為它看起來像分頁邏輯。**那是中文換行保護**（Phase 44 加的，正式庫有一張照片的
   說明剛好含這幾個字）。而且 `tests/integration/test_design4_error_paths.py` 有一顆
   測試在斷言那一行還在——刪了會紅，但錯誤訊息看起來跟本 phase 完全無關，很難查。

3. **刪過頭：把 `folder_modal.js`／`entity_modal.js` 兩個**檔案**刪掉**。
   本 phase 只是讓 `browse.html` 不再 `<script src>` 它們。
   檔案本身還被 `pending.html`（Phase 52）與 `classify_chain.js`
   （上傳頁、鏡頭桌面頁的三關鏈）用著。刪檔＝上傳功能整個掛掉。

4. **刪不夠：`<script src>` 拿掉了，但頁面裡還有 `openFolderModal(...)` 的呼叫。**
   症狀是「平常都好好的，點某個東西的時候 Console 噴
   `openFolderModal is not defined`，而且什麼都沒發生」。
   `test_瀏覽頁不再是待決定入口` 就是為了在測試階段抓到它。

5. **看到上傳頁的結果卡還寫著「……瀏覽頁的「待決定」分頁完成歸類」，以為自己漏改了。**
   **沒有漏。** 那是兩句：`classify_chain.js` 第 53 行的
   「已放進待決定區，之後到瀏覽頁的「待決定」分頁完成歸類。」
   與 `upload.html` `pdf摘要()` 裡的
   「其餘頁留在待決定區，可到瀏覽頁的「待決定」分頁完成歸類。」——
   都是**上傳頁／鏡頭頁的結果卡文案**，不在彈窗裡（彈窗那句 Phase 54 已經改好了）。
   design5 §11 把上傳頁與鏡頭頁的文案改寫排在 **Phase 68／69**。
   本 phase 做完到 Phase 68／69 之間，那兩句會指向一個不存在的分頁——
   這是**已知的、有主的過期文案，是預期不是 bug**，不要順手改
   （會讓本 phase 的 `git status` 多兩個檔，而且 Phase 68 的作者會不知道已經被改過）。
   ⚠ 但**要在 ★ G1 的時候跟產品負責人講一聲**，免得他自己看到以為是 bug
   （★ G1 框框下面那段「當面交代的已知事項」就是為這件事準備的）。

6. **順手做「舊書籤自動轉址」**。design5 §6.3 明文不做，`test_瀏覽頁沒有做舊書籤轉址`
   會抓到。真正的害處：加了之後 `browse.html` 這個網址就再也打不開資料夾卡片了
   （它會永遠跳走），你得記得打 `?tab=folders`。

7. **把 `?tab=folders` 那一支 `else if` 留著**（想說「明寫比較清楚」）。
   留著不會壞，但那是兩條路走到同一個地方——之後有人改其中一條就會不一致。
   `test_瀏覽頁不再是待決定入口` 裡的 `'tabInUrl === "folders"' not in 原始碼`
   就是為了逼你只留一條。

8. **`renderTabs` 的參數改了，呼叫端忘了跟著改**。
   `renderTabs("folders", inbox.photo_count, tasks.length)` 沒改成兩個參數的話，
   待辦那一格的數字會顯示成收件箱的張數——**畫面不會壞、只是數字錯**，最難發現。
   兩個呼叫端（`showFolderList`／`showTasks`）都要對一遍
   （`showFolderPhotos` 本來就不呼叫 `renderTabs`，不必看）。

9. **以為頂欄的「待決定（N）」會自己變**。它是頁面載入時算一次（Phase 53 的計數片段）。
   在待決定頁定案一張之後，頁面會 `location.reload()`，所以那一頁的 N 會更新；
   但**別的分頁**（例如你早就開著的 browse 頁）不會自己變，要重新整理。
   自動更新是 Phase 67 的事。

10. **`pytest -q` 顆數對不上 415**。先確認 Phase 53 的 7 顆真的都在
    （`pytest tests/integration/test_nav_header.py -v` 應該是 10 顆）。
    還是不對就檢查是不是**同時跑了兩份 pytest**——那會出現大量看似隨機的 404 與
    `TypeError: 'NoneType' object is not subscriptable`，而且每次紅的顆數都不一樣。

11. **★ G1 自己勾掉**。不行。那四個框是產品負責人的，不是實作者的。
    Phase 49 的檔頭有前例：G1 通過的憑據是產品負責人在 dev-prompt 裡寫下的那句話，
    有出處、留得下來。沒有那句話就停手。
