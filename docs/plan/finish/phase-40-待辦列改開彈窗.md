# Phase 40：待辦列改開彈窗（階段甲第 3 步，甲完結）

> **目前執行狀態（2026-08-24 最終技術驗收）：✅ 實作與瀏覽器自驗已完成。**
> 下方 `365 passed ＋ 2 skipped` 是本 phase 當時的歷史基線，不回改；
> 目前 targeted suite 為 **112 passed、2 skipped、1 warning（9.42s）**，
> 全量為 **402 passed、2 skipped、1 warning（27.73s）**；唯一 warning 是
> `StarletteDeprecationWarning`（`httpx`／`starlette.testclient`）。
> 最終瀏覽器證據共 **25 張 JPEG**（11 張 `1280x900`、7 張 `768x900`、7 張 `375x812`），位於
> `/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`；
> 最新兩位獨立 reviewer `final_visual_qa_k`、`final_visual_qa_l` 均為
> **PASS（HIGH confidence，25 of 25，zero blockers）**，
> technical browser QA 與 dual-reviewer gate 已完成。
> 共用詳情窗的最新 RED→GREEN 亦涵蓋 focus trap／背景 `inert`／Tab 與 Shift+Tab／focus restore、
> stale generation，以及遺失圖片、raw error、長 CJK／數字單位的安全顯示。
> 狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 瀏覽頁「待辦」分頁的每一列，從「點了另開一個瀏覽器分頁丟原圖」
> 改成「點了在原地跳出 Phase 39 那顆同一顆詳情窗」，而且窗頂多一行**待辦標題與到期日**。

**為什麼要改：** 現在點一列會 `target="_blank"` 開新分頁，畫面上只有一張裸圖——
沒有 AI 寫的說明、沒有四個欄位，而且你被丟到另一個分頁、要按上一頁才回得來。
產品負責人 grill 時明確要求「不新開 window，圖在窗裡」（design4 §1.1 第 2 列正式推翻
design3.md §7 的「能點回來源圖即可」）。

---

## 1. 對應 design4.md 章節

- **§4.1 第 2 列**（待辦列 `<a target="_blank" href="/photos/{id}/image">` → `<button>`，開同一顆窗）
- **§4.2 第 1 點**（「待辦列才有」的那一行：標題、到期日；無到期日寫「無到期日」；資料夾進來就不畫）
- **§4.3**（`openPhotoDetailModal({ photoId, task: { title, due_date } })`）
- **D1**（共用一顆窗，待辦只多一行）
- **§1.1 第 2 列**（推翻 design3.md §7 的開新分頁）
- **§1.2 第 2 列**（被否決：待辦彈窗裡編輯或刪待辦）
- **§9 錯誤表第 4 列**（待辦列點下去、詳情 404 → 窗開著、紅字；不是新分頁空白）

---

## 2. 前置條件

- **Phase 38 已完成**（`GET /photos/{photo_id}` 可用）。
- **Phase 39 已完成**（`photo_detail_modal.js` 存在、資料夾牆已可點、`.pd-task` 樣式已寫好）。
  本 phase 只是「第二個入口」，窗本身不再改。
- `pytest -q` 是 **365 passed ＋ 2 skipped**（Phase 38 之後的基準）。本 phase 純前端，
  做完還是這個數字——開工前先跑一次，才知道之後如果變紅是誰弄的。
- 起一個伺服器準備隨時看畫面（每個新終端機視窗都要先進專案、開 venv）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- 待辦分頁要有東西可看：至少一筆待辦。沒有的話先上傳一張有「可辦事項」的照片
  （例如帳單），在第三關待辦彈窗按「建立待辦」。

---

## 3. 範圍

### 做

- `app/static/browse.html` 的 `showTasks()`：
  - 每一列從 `<a href target="_blank">` 改成 `<button type="button">`；
  - 點下去呼叫 `openPhotoDetailModal({ photoId, task })`；
  - 提示文字從「點一列可開來源照片的原圖。」改成講清楚新行為。
- `app/static/photo_detail_modal.js`：把 `config.task` 那一段畫出來（`#pd-task` 那一區），
  順手讓窗的標題（`#pd-title`）依入口顯示「待辦來源照片」或「照片」。
- `app/static/style.css`：`a.task-row` 這個**元素限定**的選擇器改成 `.task-row`，
  並補上 `<button>` 需要的重設（見 §4.3）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在窗裡編輯待辦標題／到期日 | design4 §1.2 第 2 列已否決；本輪只看 |
| 在窗裡刪待辦、打勾完成 | 全系統沒有刪除端點；待辦也沒有完成狀態（design3 §7 MVP） |
| 新增「待辦詳情」端點或讓 `GET /tasks` 多回欄位 | 標題與到期日**清單裡本來就有**（`TaskOut` 的 `title`／`due_date`），直接帶進窗即可 |
| 為待辦另做一顆不一樣的窗 | design4 §1.2 第 6 列已否決：共用一顆，待辦只多一行 |
| 改 `GET /tasks` 的排序或契約 | design4 §3「不做」 |
| 動 `POST /photos/{id}/task` 建立待辦那條路 | 與本 phase 無關 |
| 為本 phase 新增自動化測試 | 本專案前端慣例（Phase 23／24／31／33／39 皆然）：純前端改動零新增自動化測試，改用 §4.5 的瀏覽器實操驗收；`pytest -q` 顆數維持 365 ＋ 2 skipped |

---

## 4. 實作步驟

### 4.1 先看懂現在的待辦列（不寫程式，只讀）

- [ ] 打開 `app/static/browse.html` 的 `showTasks()`（約第 202〜244 行），注意這幾行：

```javascript
const row = el("a", "task-row");                              // 第 219 行
// 「能點回來源圖」（design3.md §7）：直接連原圖端點、開新分頁。      ← 第 220 行
// 舊照片沒有原圖時端點回 404——與縮圖占位同一套「不假裝有圖」的態度。 ← 第 221 行
row.href = "/photos/" + task.photo_id + "/image";             // 第 222 行
row.target = "_blank";                                        // 第 223 行
row.rel = "noopener";                                         // 第 224 行
```

  第 220〜224 行這五行（兩行舊註解 ＋ 三行連結設定）就是本 phase 要整組刪掉的東西。

- [ ] 打開 `app/static/style.css` 第 596 行附近，注意選擇器是**元素限定**的：

```css
a.task-row { … }
a.task-row:hover { … }
```

  `a.task-row` 的意思是「`<a>` 標籤而且 class 是 task-row 才套用」。
  把標籤換成 `<button>` 之後這條就不生效了——待辦列會瞬間變成一排難看的原生按鈕。
  這是本 phase 最容易踩的坑，**先改 CSS 再改 HTML** 就不會嚇到自己。

- [ ] 順帶確認 `GET /tasks` 回什麼（`app/schemas/task.py` 的 `TaskOut`）：
      `id`／`photo_id`／`title`／`due_date`／`thumbnail_url` 五個鍵。
      窗要用的 `title` 與 `due_date` **清單裡已經有了**，不必再打一支 API。

### 4.2 `photo_detail_modal.js`：把待辦那一行畫出來

- [ ] 在 `openPhotoDetailModal()` 一開始「清乾淨」的那一段，加上待辦區塊的處理：

```javascript
  // 待辦那一行只有從待辦分頁進來才畫（design4.md §4.2 第 1 點）。
  // 資料夾牆進來時 config.task 是 null，整區隱藏——同一顆窗，兩種入口。
  const 待辦 = config.task || null;
  pdEl("pd-task").hidden = !待辦;
  if (待辦) {
    pdEl("pd-task-title").textContent = 待辦.title;
    pdEl("pd-task-due").textContent =
      待辦.due_date ? "到期 " + 待辦.due_date : "無到期日";
  }
```

  **為什麼寫在「清乾淨」那一段**：它必須在 `fetch` 之前就畫好——
  待辦的標題與到期日是清單帶進來的，不必等 API。使用者按下去的當下就看得到標題，
  下面的圖與說明再慢慢補上（載入中的體感差很多）。

- [ ] 順手把窗的標題也對齊：`pdEl("pd-title").textContent = 待辦 ? "待辦來源照片" : "照片";`
      （一行，讓兩個入口的窗一眼分得出來。）

### 4.3 `style.css`：讓 `.task-row` 不再挑標籤

- [ ] 把第 596、608 行的兩個選擇器去掉 `a`：

```css
.task-row { … }
.task-row:hover { … }
```

- [ ] 在 `.task-row` 的規則裡補上 `<button>` 需要的重設（`<a>` 不需要、`<button>` 需要）：

```css
.task-row {
  width: 100%;              /* button 預設寬度是內容寬，不補會縮成一小塊 */
  font: inherit;            /* button 不繼承頁面字型，不補會變成系統預設字 */
  text-align: left;         /* button 預設置中 */
  cursor: pointer;          /* button 預設游標是箭頭，不是手指 */
  /* 其餘（display:flex、align-items、gap、padding、背景、邊框、圓角、
     color、transition）一字不動 */
}
```

  `font: inherit` 是本專案既有寫法（`style.css` 第 245／260 行的 `.btn`／`.fm-option button`
  都這樣寫），照抄就好。全站已有 `*, *::before, *::after { box-sizing: border-box; }`
  （第 93 行），所以 `width: 100%` 再加 padding 與邊框也不會撐破版面。

  ⚠ **`color: var(--c-text);` 那行一定要留著。** `<button>` 和 `<a>` 不一樣，它**不繼承**
  文字顏色（瀏覽器預設是 `buttontext`）。刪掉的話待辦標題會從深墨色變成純黑，
  就違反下面「長相與改之前一模一樣」那條驗收了。`text-decoration: none;` 那行對
  `<button>` 沒有作用，留著或刪掉都可以——留著比較不會動到不該動的東西。

### 4.4 `browse.html`：`showTasks()` 改成開窗

- [ ] 提示文字改掉：

```javascript
view.appendChild(el("p", "message",
  "點一列可以看這件待辦的來源照片與完整說明。"));
```

- [ ] 每一列改成按鈕，並掛上點擊行為。**第 220〜224 行那五行要整組刪掉**
      （design3 §7 的兩行舊註解 ＋ `row.href`／`row.target`／`row.rel` 三行），
      換成下面這段——留著等於留一條沒人走的舊路（使用者偏好：不留過渡產物）：

```javascript
  tasks.forEach(function (task) {
    // 改開頁內詳情窗（design4.md D1／§1.1）：不再 target="_blank" 開新分頁——
    // 新分頁只有一張裸圖，看不到 AI 寫的說明，也回不去這一頁。
    const row = el("button", "task-row");
    row.type = "button";

    … 縮圖／task-title／task-due 三段一字不動 …

    row.addEventListener("click", function () {
      openPhotoDetailModal({
        photoId: task.photo_id,
        task: { title: task.title, due_date: task.due_date }
      });
    });

    const item = document.createElement("li");
    item.appendChild(row);
    list.appendChild(item);
  });
```

  **為什麼這裡用「每列各掛一個監聽」而不是像縮圖牆那樣事件委派**
  （事件委派＝不在每張卡片上各掛一個監聽器，改在整面牆掛**一個**，
  靠 `event.target.closest(".photo")` 找出被點的是哪一張；Phase 39 §4.4 有解釋）：待辦列表短
  （不會有幾百筆），而且每一列要帶的資料有三個欄位（id／title／due_date）。
  用委派就得把它們塞進 `dataset` 再讀出來（全部會變成字串，`null` 會變成 `"null"`），
  反而更容易出錯。直接用閉包抓住 `task` 這個物件最單純。

- [ ] 順手把 `showTasks()` 上面那行函式註解（第 201 行）的出處改掉——
      「能點回來源圖就好」已被 design4 §1.1 第 2 列推翻，留著會誤導下一個人：

```javascript
// ---------- 分頁三：待辦（design3.md D13、D15；點一列開唯讀詳情窗＝design4.md D1）----------
```

- [ ] `browse.html` 已經在 Phase 39 掛過 `photo_detail_modal.js` 了，**不用再加一次 script 標籤**。

### 4.5 瀏覽器實操驗收（本 phase 的主要驗收方式）

開 `http://localhost:8000/ui/browse.html?tab=tasks`：

- [x] 待辦列表長相與改之前**一模一樣**（縮圖、標題、到期日、hover 邊框變深）——
      證明 CSS 選擇器改對了
- [x] 點一列 → **沒有新分頁**（分頁列數量不變），原地跳出詳情窗
- [x] 窗頂的標題列寫「**待辦來源照片**」；下面第一行是**待辦標題**、第二行是「到期 2026-09-18」；
      待辦這一區與下面的大圖之間有一條分隔線（`.pd-task` 的 `border-bottom`，Phase 39 已寫好）
- [x] 找一筆**沒有到期日**的待辦點下去 → 第二行寫「**無到期日**」
      （庫裡沒有這種待辦的話：上傳一張照片，在第三關待辦彈窗把到期日欄位清空再按「建立待辦」）
- [x] 窗的下半部：大圖 ＋ AI 說明 ＋ 四欄，與資料夾牆進來時一模一樣
- [x] Esc／×／點暗色區 都關得掉；關掉之後**還在待辦分頁**（不是跳走）
- [x] 回到「資料夾」分頁點一張照片 → 窗頂**沒有**待辦那一行（`#pd-task` 有正確隱藏）、
      標題列回到「照片」
- [x] **§9 錯誤表第 4 列**：用 `psql` 直接把某筆待辦指向一個不存在的照片 id 很麻煩
      （有外鍵擋著），改用開發者工具驗：在 Console 執行
      `openPhotoDetailModal({photoId: 99999, task: {title: "測試", due_date: null}})`
      → 窗**開著**、窗頂看得到「測試／無到期日」、下面是紅字「找不到這張照片」，
      **不是**空白新分頁、**不是** alert
- [x] **Console 乾淨**：整趟只有既有預期訊息，沒有紅色錯誤

---

## 5. ASCII 圖：改前 ／ 改後

```text
  ── 改之前（design3 §7）────────────────────────────────────────
     待辦分頁                            新的瀏覽器分頁
     ┌──────────────────────┐            ┌──────────────────┐
     │ [縮圖] 繳電費 到期日 │ ── 點 ──►  │                  │
     │ [縮圖] 交 Project 2  │            │   一張裸圖       │
     └──────────────────────┘            │  （沒有說明）    │
                                         │  （要按上一頁）  │
                                         └──────────────────┘

  ── 改之後（design4 D1）────────────────────────────────────────
     待辦分頁
     ┌──────────────────────┐
     │ [縮圖] 繳電費 到期日 │ ── 點 ──┐
     │ [縮圖] 交 Project 2  │         │  同一頁，不開新分頁
     └──────────────────────┘         │
                                      ▼
        ┌─────────────────────────────────────────┐
        │ 待辦來源照片                        [×] │  ← <h3 id="pd-title">
        │ 繳電費                                  │  ← task.title
        │ 到期 2026-09-18                         │  ← task.due_date，沒有就寫「無到期日」
        │ ─────────────────────────────────────── │  ← 全窗只有這一條分隔線
        │              大 圖                      │     （.pd-task 的 border-bottom）
        │ 一張電費單，金額 1,280 元。             │  ← text
        │ 類別：文件        地點：無              │  ← metadata 四欄，空的寫「無」
        │ 物品：無          內容日期：2026-08-18  │
        └─────────────────────────────────────────┘
                Esc ／ × ／ 點暗色區 都可以關

     資料來源：標題與到期日 ← 清單本來就有的 TaskOut（不必多打 API）
               圖與說明     ← GET /photos/{photo_id}（Phase 38）
```

---

## 6. 驗收清單

- [ ] `browse.html` 裡搜不到 `_blank`／`row.href`／`row.rel`（待辦列不再連出去，三行都刪乾淨了；
      這三個字串目前**只**出現在 showTasks 的第 222〜224 行，搜出來是空的就代表改完了）
- [ ] `style.css` 裡搜不到 `a.task-row`（選擇器已改成不挑標籤）；`.task-row` 裡仍有 `color: var(--c-text)`
- [x] 待辦列外觀與改之前一致（hover 有反應、字型沒變、寬度沒縮）
- [x] §4.5 的 9 項瀏覽器實操逐項打勾、Console 乾淨
- [x] 資料夾牆進來時窗頂**沒有**待辦那一行；待辦進來時**有**
- [ ] `pytest -q` 仍是 **365 passed ＋ 2 skipped**（純前端，顆數不變）
- [ ] `git diff --stat` 只動到三個檔：`browse.html`、`photo_detail_modal.js`、`style.css`
- [ ] **階段甲到此完結**——Phase 38／39／40 三份都打完勾了才往下走

---

## 7. 常見陷阱

1. **忘了先改 CSS**：`a.task-row` 沒改就把標籤換成 `<button>`，畫面會變成一排系統原生按鈕，
   看起來像壞掉。先改 CSS、重新整理確認沒事，再改 HTML。

2. **`<button>` 沒加 `type="button"`**：待辦列雖然不在 `<form>` 裡，加上仍是好習慣
   （其他彈窗的按鈕都有加）。萬一日後被包進表單，預設的 `type="submit"` 會讓整頁重新載入。

3. **把 `due_date` 的 `null` 直接印出來**：`task.due_date` 沒有到期日時是 `null`，
   `"到期 " + null` 會印成「到期 null」。一定要用三元判斷（既有那行
   `task.due_date ? "到期 " + task.due_date : "無到期日"` 就是對的寫法，照抄）。

4. **在 `#pd-task` 裡用 `innerHTML`**：標題是使用者自己打的字（待辦彈窗可以修改），
   一律 `textContent`。

5. **待辦那一行畫在 fetch 之後**：那樣使用者會先看到一片「載入中」才蹦出標題，
   體感很差。標題是現成資料，**開窗當下就畫**。

6. **想順便加「完成」勾選**：design4 §1.2 已否決；design3 §7 也明寫 MVP 不做完成狀態。
   不要因為「反正就在旁邊」就順手加。

7. **改到 `GET /tasks`**：一個字都不要動。窗要的兩個欄位清單裡本來就有。
