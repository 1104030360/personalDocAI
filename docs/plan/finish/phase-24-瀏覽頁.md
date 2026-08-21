# Phase 24：瀏覽頁（資料夾卡片 → 縮圖牆 → 點一張再歸類）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 新增第三個純 HTML 頁面 `app/static/browse.html`——列出全部資料夾（名稱、說明、張數），點一個進去看縮圖牆，點一張照片可以用**同一套三選項彈窗**改資料夾。同時把 Phase 23 寫在 `upload.html` 裡的彈窗程式碼**整段搬進共用檔** `app/static/folder_modal.js`（**不留兩份**），兩頁都用 `<script src>` 引用。**零框架、零打包、零新增後端端點、零新增自動化測試。**

---

## 前置條件

- 需要已完成的 phase：
  - **Phase 19**：`GET /photos/{id}/thumbnail`（縮圖牆的 `<img src>` 就指這裡；舊資料沒有圖時是 404）
  - **Phase 21**：`PATCH /photos/{id}/folder`（彈窗歸類用）
  - **Phase 22**：`GET /folders`、`GET /folders/{id}`（本頁的兩個資料來源）
  - **Phase 23**：`upload.html` 裡已經有一整段可重用的彈窗程式碼（本 phase 要把它搬走）
- 開工前基線：先跑一次 `pytest -q` 把數字抄下來記成 **N**（Phase 22／23 完成後為 **140**，2026-08-21 校準）。**本 phase 做完必須還是 N＝140**——一個測試都不會增減。
- 環境（手動瀏覽器驗收，走真模型那條路）：
  ```bash
  brew services start postgresql@17            # PostgreSQL@17（5433 埠）
  pgrep -fl "ollama serve" || open -a Ollama   # Ollama 是 App 版，不歸 brew services 管
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000
  ```
- 資料準備：正式庫最好已經有幾張**有縮圖**的照片（Phase 23 驗收時上傳的那幾張），以及那 2 張 **沒有原圖的舊照片**（在「收據」資料夾裡）——兩種都要看得到，才驗得到占位圖。

---

## 這個 phase 在做什麼

design1.md §0 列的三個體驗缺口，前兩個（看得到圖、分得開）已經補完，剩最後一個：**「我上傳過什麼」沒有地方看**。本 phase 就是那個地方。

頁面只有兩個畫面，靠網址的 query string 切換：

```
/ui/browse.html              → 資料夾清單（卡片）
/ui/browse.html?folder=2     → 2 號資料夾的縮圖牆
```

**刻意用「換網址」而不是「用 JavaScript 切換畫面」**：卡片就是普通的 `<a href="…?folder=2">` 連結，點了整頁重新載入。這樣瀏覽器的上一頁／重新整理／把某個資料夾加書籤**通通免費就有**，而且我們一行狀態管理的程式都不用寫。這是最懶也最穩的做法。

第二件事是**把彈窗抽成共用檔**。Phase 23 已經刻意把那段程式寫成「不碰頁面其他部分、只靠兩個 callback 對外溝通」的形狀，所以這裡是真正的**搬家，不是重寫**：整段剪下 → 貼進 `app/static/folder_modal.js` → 兩個頁面各加一行 `<script src="/ui/folder_modal.js"></script>`。契約明訂**不留兩份、不留過渡產物**，搬完 `upload.html` 裡就不該再有那段程式碼。

瀏覽頁用同一個彈窗，只有選項 ① 的文字不同：

| 頁面 | 選項 ① | 意思 |
|---|---|---|
| 上傳頁 | `採用「收據」` | 採用 AI 建議的那一個 |
| 瀏覽頁 | `維持「收據」` | 這張照片現在就在「收據」，維持現狀 |

（這是靠 Phase 23 就準備好的 `primaryVerb` 參數做到的，共用檔內部只有一條程式路徑。）

**名詞**：
- **query string（查詢字串）**＝網址問號後面那一段，例如 `browse.html?folder=2` 裡的 `folder=2`。用來把「要看哪個資料夾」寫在網址上。JavaScript 讀它的方法：`new URLSearchParams(location.search).get("folder")`。
- **`<img src="/photos/7/thumbnail">`**＝瀏覽器看到 `<img>` 會自己再送一個 GET 請求去把圖抓回來畫出來。所以縮圖牆不用寫任何抓圖的程式，把網址填進去就好。
- **占位（placeholder）**＝沒有圖可以顯示時，畫一塊灰底方塊寫「無縮圖」。design1.md §10 明訂：**不假裝有圖**。
- **event delegation（事件委派）**＝與其幫牆上每一張照片都掛一個「被點時要做什麼」，不如**只在整面牆掛一個**，被點時再用 `event.target.closest(".photo")` 往上找「使用者到底點到哪一張」。照片是程式動態產生的，用委派就不必邊產生邊掛監聽器。
- **`element.closest(選擇器)`**＝從這個元素自己開始往父層一路找，回傳第一個符合選擇器的祖先。點到照片裡的 `<img>` 時，靠它就能找到外層那顆 `.photo` 按鈕。
- **`dataset`**＝HTML 元素上以 `data-` 開頭的自訂屬性，在 JavaScript 裡用 `element.dataset.photoId` 讀 `data-photo-id`。用來把照片 id 「掛」在畫面元素上。
- **`Promise.all([…])`**＝同時發出多個請求、等**全部**回來再繼續（比一個等完再發下一個快）。本頁同時要 `/folders/{id}`（這個資料夾的照片）和 `/folders`（下拉選單要的完整清單）。
- **`document.createElement` ＋ `textContent`**＝安全地把資料畫到畫面上的做法。**不要**用 `innerHTML` 去拼接照片文字或資料夾名稱——那些內容是 AI 產生的，裡面若剛好有 `<` 之類的符號會把版面弄壞。（共用檔裡唯一一次 `innerHTML` 用的是我們自己寫死的固定樣板字串，沒有外來資料，所以安全。）
- **`location.reload()`**＝重新載入目前這一頁。歸類成功後照片可能已經不屬於這個資料夾，最省事的作法就是整頁重讀。

---

## ASCII 圖：瀏覽頁的兩個畫面（線框圖 wireframe）

**線框圖**＝只畫「有哪些東西、放在哪裡」的草圖，不管顏色與美感（美感是 Phase 26 的事）。

```
┌────────────────────────────────────────────────────────────────────┐
│ http://localhost:8000/ui/browse.html            ← 畫面一：資料夾清單 │
├────────────────────────────────────────────────────────────────────┤
│  PersonalDocAI                                                     │
│  [上傳照片]  [瀏覽資料夾]  [問問題]      ← 三頁互連的導覽列          │
│  ────────────────────────────────────────────────────────────────  │
│  資料夾                                                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ 未分類（3 張）                                                │  │← <a href="?folder=1">
│  │ 不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ 收據（2 張）                                                  │  │← <a href="?folder=2">
│  │ 發票、消費憑證、購物明細。                                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  … 飲食 / 風景 / 文件 / 其他 / 使用者自建的（資料來源：GET /folders）│
└────────────────────────────────────────────────────────────────────┘
             │ 點一張卡片＝整頁換到 ?folder=2
             ▼
┌────────────────────────────────────────────────────────────────────┐
│ http://localhost:8000/ui/browse.html?folder=2   ← 畫面二：縮圖牆     │
├────────────────────────────────────────────────────────────────────┤
│  PersonalDocAI                                                     │
│  [上傳照片]  [瀏覽資料夾]  [問問題]                                 │
│  ────────────────────────────────────────────────────────────────  │
│  ← 回資料夾列表                                                     │
│  收據（4 張）                                                       │
│  發票、消費憑證、購物明細。                                          │
│  點一張照片可以改資料夾。                                            │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │ [照片] │ │ [照片] │ │▒▒▒▒▒▒▒▒│ │▒▒▒▒▒▒▒▒│  ← 右邊兩張是舊資料      │
│  │        │ │        │ │ 無縮圖 │ │ 無縮圖 │     thumbnail_url=null │
│  ├────────┤ ├────────┤ ├────────┤ ├────────┤     → 灰底占位          │
│  │在 Targ…│ │在 Cost…│ │…       │ │…       │  ← text 前兩行          │
│  └────────┘ └────────┘ └────────┘ └────────┘                       │
│     ↑ 資料來源：GET /folders/2                                      │
└────────────────────────────────────────────────────────────────────┘
             │ 點任一張（event delegation：整面牆只掛一個監聽器）
             ▼
      ┌──────────── 同一套彈窗（folder_modal.js，兩頁共用）────────────┐
      │ 要把這張照片放到哪個資料夾？                            [ × ] │
      │ ① [ 維持「收據」 ]   ← 上傳頁是「採用」，這裡是「維持」        │
      │ ② [ 飲食 ▾ ] [ 歸到這個資料夾 ]                               │
      │ ③ [名稱__] [說明__] [ 建立並歸類 ]                            │
      │ ⚠ 錯誤畫在這行（絕不用 alert）                                │
      └───────────────────────────────────────────────────────────────┘
             │ PATCH 成功 → location.reload()（照片被移走就會從這面牆消失）
             │ × 或 Esc  → 什麼都不做

 檔案關係（搬家後）：
   app/static/folder_modal.js   ← 彈窗程式碼「唯一一份」（Phase 23 從 upload.html 整段搬來）
        ▲                ▲
        │                │  <script src="/ui/folder_modal.js"></script>
   upload.html       browse.html
```

---

## 逐步驟操作

### 步驟 1：把彈窗程式碼搬進 `app/static/folder_modal.js`（搬，不是抄）

打開 `app/static/upload.html`，找到 Phase 23 寫下的這兩行註解：

```html
<!-- ↓↓↓ 共用彈窗：這一整段（含 script 標籤）在 Phase 24 會原封不動搬到 /ui/folder_modal.js ↓↓↓ -->
…
<!-- ↑↑↑ 共用彈窗結束 ↑↑↑ -->
```

**把兩行註解之間的整個 `<script>…</script>` 內容（不含 `<script>` 與 `</script>` 這兩個標籤本身）剪下，貼成新檔案 `app/static/folder_modal.js`。** 程式碼一行都不用改，只補兩句註解（見本節最後說明）。貼完之後，`folder_modal.js` 的內容應該是這樣（整份對照用，你手上的內容必須與此完全相同）：

```javascript
/* 資料夾歸類彈窗（modal）：把某張照片歸到某個資料夾。
   上傳頁（upload.html）與瀏覽頁（browse.html）共用這一份，全站只有這一份。

   ⚠ 一律不用 alert／confirm／prompt：那會開瀏覽器的原生對話框，
     不但擋住整個頁面，也會讓瀏覽器自動化（Playwright）停在那裡等人按。
     所有提示與錯誤都寫進彈窗裡的 <p id="fm-error">。
     （這行註解故意不在函式名後面加小括號——驗收會用 grep 掃「函式名＋左括號」，註解不能誤中。）

   用法：
     openFolderModal({
       photoId: 7,                                // 要歸類的照片 id
       folders: [{id, name, description}, …],     // ② 下拉選單用的完整清單
       primary: {id, name, description},          // ① 那一個資料夾
       primaryVerb: "採用",                        // 上傳頁「採用」、瀏覽頁「維持」
       onAssigned: function (folder) { … },       // PATCH 成功，帶回新的資料夾
       onClosed: function () { … }                // 使用者按 × 或 Esc，沒有歸類
     });

   本檔不碰頁面其他部分，成功或關閉都只透過上面兩個 callback 通知呼叫方——
   所以同一份程式碼上傳頁與瀏覽頁都能用。
*/

const FOLDER_MODAL_CSS = `
.fm-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.45);
               display: flex; align-items: center; justify-content: center; }
.fm-backdrop[hidden] { display: none; }
.fm-box { background: #fff; padding: 1.2rem; width: min(32rem, 92vw);
          max-height: 86vh; overflow: auto; position: relative;
          font-family: system-ui, "PingFang TC", sans-serif; line-height: 1.6; }
.fm-box h3 { margin: 0 1.5rem 0.5rem 0; }
.fm-close { position: absolute; top: 0.3rem; right: 0.5rem; border: none;
            background: none; font-size: 1.5rem; line-height: 1; cursor: pointer; }
.fm-option { border-top: 1px solid #ddd; padding: 0.7rem 0; }
.fm-option:first-of-type { border-top: none; }
.fm-desc { color: #666; font-size: 0.9rem; margin: 0.3rem 0 0; }
.fm-box input, .fm-box select { padding: 0.35rem; margin: 0.2rem 0.4rem 0.2rem 0; }
.fm-box input { width: 13rem; }
.fm-box button { padding: 0.4rem 1rem; }
.fm-error { color: #b00020; min-height: 1.5rem; margin: 0.5rem 0 0; }
`;

const FOLDER_MODAL_HTML = `
<div class="fm-backdrop" id="fm-backdrop" hidden>
  <div class="fm-box" role="dialog" aria-modal="true" aria-labelledby="fm-title">
    <button type="button" class="fm-close" id="fm-close" aria-label="關閉">×</button>
    <h3 id="fm-title">要把這張照片放到哪個資料夾？</h3>

    <div class="fm-option">
      <button type="button" id="fm-primary">（載入中）</button>
      <p class="fm-desc" id="fm-primary-desc"></p>
    </div>

    <div class="fm-option">
      <label for="fm-select">改選其他現有資料夾：</label><br>
      <select id="fm-select"></select>
      <button type="button" id="fm-select-submit">歸到這個資料夾</button>
    </div>

    <div class="fm-option">
      <label for="fm-name">自建新資料夾：</label><br>
      <input type="text" id="fm-name" placeholder="名稱，例如：專案X">
      <input type="text" id="fm-desc-input" placeholder="說明：這裡放什麼照片">
      <button type="button" id="fm-create">建立並歸類</button>
    </div>

    <p class="fm-error" id="fm-error"></p>
  </div>
</div>
`;

let fmConfig = null;    // 這次開窗的設定（上面 openFolderModal 收到的那包）
let fmReady = false;    // 彈窗的 HTML 與事件只裝一次

function fmEl(id) {
  return document.getElementById(id);
}

function fmSetError(message) {
  fmEl("fm-error").textContent = message;   // 錯誤畫在頁面裡，不用 alert
}

function fmSetBusy(busy) {
  ["fm-primary", "fm-select-submit", "fm-create"].forEach(function (id) {
    fmEl(id).disabled = busy;               // 等回應期間三顆按鈕都不能按
  });
}

function fmHide() {
  fmEl("fm-backdrop").hidden = true;
  fmConfig = null;
}

function fmClose() {                        // 使用者主動關閉：不呼叫任何 API
  const onClosed = fmConfig && fmConfig.onClosed;
  fmHide();
  if (onClosed) onClosed();
}

function fmDetailText(payload) {
  // FastAPI 的錯誤訊息有兩種形狀：我們自己丟的是字串，
  // Pydantic 驗證失敗（422）則是一個陣列，裡面每筆有 msg。
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (one) {
      return one.msg || JSON.stringify(one);
    }).join("；");
  }
  return JSON.stringify(payload);
}

async function fmAssign(body) {
  if (!fmConfig) return;
  const photoId = fmConfig.photoId;
  fmSetError("");
  fmSetBusy(true);
  try {
    const response = await fetch("/photos/" + photoId + "/folder", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const payload = await response.json();

    if (response.status === 200) {
      const onAssigned = fmConfig.onAssigned;
      fmHide();
      if (onAssigned) onAssigned(payload.folder);
      return;
    }
    // 409＝資料夾名稱重複；422＝名稱空白或兩種 body 都給了；404＝照片或資料夾不存在
    fmSetError("（HTTP " + response.status + "）" + fmDetailText(payload));
  } catch (error) {
    fmSetError("請求失敗：" + error + "（uvicorn 是不是沒在跑？）");
  } finally {
    fmSetBusy(false);
  }
}

function fmInstall() {
  if (fmReady) return;

  const style = document.createElement("style");
  style.textContent = FOLDER_MODAL_CSS;
  document.head.appendChild(style);

  const holder = document.createElement("div");
  holder.innerHTML = FOLDER_MODAL_HTML;   // 固定樣板字串，沒有任何外來資料
  document.body.appendChild(holder.firstElementChild);

  fmEl("fm-close").addEventListener("click", fmClose);
  fmEl("fm-primary").addEventListener("click", function () {
    fmAssign({ folder_id: fmConfig.primary.id });
  });
  fmEl("fm-select-submit").addEventListener("click", function () {
    fmAssign({ folder_id: Number(fmEl("fm-select").value) });
  });
  fmEl("fm-create").addEventListener("click", function () {
    fmAssign({
      name: fmEl("fm-name").value,
      description: fmEl("fm-desc-input").value
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !fmEl("fm-backdrop").hidden) fmClose();
  });

  fmReady = true;
}

function openFolderModal(config) {
  fmInstall();
  fmConfig = config;

  // ① 那顆按鈕：上傳頁是「採用「收據」」，瀏覽頁是「維持「收據」」
  fmEl("fm-primary").textContent =
    (config.primaryVerb || "採用") + "「" + config.primary.name + "」";
  fmEl("fm-primary-desc").textContent = config.primary.description || "";

  // ② 下拉選單：放「全部」資料夾（design1.md §9 的決定，資料夾多了才找得到）
  const select = fmEl("fm-select");
  select.textContent = "";
  config.folders.forEach(function (folder) {
    const option = document.createElement("option");
    option.value = folder.id;
    option.textContent = folder.name;
    if (folder.id === config.primary.id) option.selected = true;
    select.appendChild(option);
  });

  // ③ 自建：每次開窗都清空，免得留著上一張的輸入
  fmEl("fm-name").value = "";
  fmEl("fm-desc-input").value = "";

  fmSetError("");
  fmSetBusy(false);
  fmEl("fm-backdrop").hidden = false;
  fmEl("fm-primary").focus();
}
```

> 唯一與 Phase 23 不同的兩處：檔頭註解多了一行「全站只有這一份」，以及 `holder.innerHTML = FOLDER_MODAL_HTML;` 後面補了一句說明。**其餘一字不改。**

### 步驟 2：改 `app/static/upload.html`（刪掉搬走的那一段，加一行引用、加一個連結）

**(a) 刪掉整段。** 把下面這一整塊——從註解開始到註解結束，包含中間的 `<script>` 與 `</script>`——**全部刪除**：

```html
<!-- ↓↓↓ 共用彈窗：這一整段（含 script 標籤）在 Phase 24 會原封不動搬到 /ui/folder_modal.js ↓↓↓ -->
<script>
… （Phase 23 寫的彈窗程式碼，已在步驟 1 剪到 folder_modal.js）…
</script>
<!-- ↑↑↑ 共用彈窗結束 ↑↑↑ -->
```

**在原地換成一行**：

```html
<script src="/ui/folder_modal.js"></script>
```

> 為什麼要放在上傳頁自己的 `<script>` **前面**：瀏覽器由上往下執行，`openFolderModal` 必須先被定義，下面那段才呼叫得到。（其實真正呼叫是在使用者按下上傳之後才發生，順序不對也多半能跑；但照著寫最不會出事。）

**(b) 導覽列補上第三個連結。** 把：

```html
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
```

改成：

```html
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/browse.html">瀏覽資料夾</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
```

`upload.html` 的其他部分（`<style>`、表單、結果區、下面那段上傳程式）**完全不動**。

### 步驟 3：改 `app/static/ask.html`（只改導覽列）

把 `ask.html` 的 `<nav>` 改成和上面完全一樣的三行連結。**這是 `ask.html` 唯一的改動**——問答頁的行為、樣式、程式碼一律不碰（design1.md §9：`/ui/ask.html` 不變）。

### 步驟 4：新增 `app/static/browse.html`

新增檔案 `app/static/browse.html`，整份照抄：

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>瀏覽資料夾 — PersonalDocAI</title>
<style>
  body { font-family: system-ui, "PingFang TC", sans-serif;
         max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  nav a { margin-right: 1rem; }
  .folders { list-style: none; padding: 0; }
  .folders li { margin-bottom: 0.5rem; }
  .folder { display: block; border: 1px solid #ccc; padding: 0.6rem 0.9rem;
            text-decoration: none; color: inherit; }
  .folder:hover { background: #f4f4f4; }
  .folder-name { font-weight: bold; }
  .folder-desc { color: #666; font-size: 0.9rem; }
  .wall { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 0.75rem; }
  .photo { width: 160px; padding: 0.3rem; border: 1px solid #ccc; background: none;
           font: inherit; text-align: left; cursor: pointer; }
  .photo img { display: block; width: 100%; height: 120px; object-fit: cover; }
  .placeholder { display: flex; align-items: center; justify-content: center;
                 width: 100%; height: 120px; background: #ddd; color: #666;
                 font-size: 0.85rem; }
  .caption { margin-top: 0.3rem; height: 2.6em; overflow: hidden;
             font-size: 0.8rem; color: #333; }
  .message { color: #666; }
</style>
</head>
<body>

<h1>PersonalDocAI</h1>
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/browse.html">瀏覽資料夾</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
<hr>

<div id="view"><p class="message">載入中…</p></div>

<script src="/ui/folder_modal.js"></script>
<script>
const view = document.getElementById("view");

// 網址是 browse.html?folder=2 就看那個資料夾，沒帶就看資料夾清單。
// 用網址而不是用 JavaScript 切畫面，上一頁／重新整理／加書籤才會正常。
const folderIdInUrl = new URLSearchParams(location.search).get("folder");

// 小工具：造一個元素並填文字。一律用 textContent，不用 innerHTML——
// 照片文字與資料夾名稱是 AI 或使用者填的，裡面若有 < 之類的符號才不會弄壞版面。
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("HTTP " + response.status + "（" + url + "）");
  }
  return await response.json();
}

// ---------- 畫面一：資料夾清單 ----------
async function showFolderList() {
  const folders = await getJson("/folders");

  view.textContent = "";
  view.appendChild(el("h2", null, "資料夾"));

  const list = el("ul", "folders");
  folders.forEach(function (folder) {
    const link = el("a", "folder");
    link.href = "/ui/browse.html?folder=" + folder.id;
    link.appendChild(el("div", "folder-name",
      folder.name + "（" + folder.photo_count + " 張）"));
    link.appendChild(el("div", "folder-desc", folder.description));

    const item = document.createElement("li");
    item.appendChild(link);
    list.appendChild(item);
  });
  view.appendChild(list);
}

// ---------- 畫面二：某個資料夾的縮圖牆 ----------
async function showFolderPhotos(folderId) {
  // 兩個請求同時送：這個資料夾的內容，以及彈窗下拉選單要用的完整清單
  const [detail, folders] = await Promise.all([
    getJson("/folders/" + folderId),
    getJson("/folders")
  ]);

  view.textContent = "";

  const back = el("a", null, "← 回資料夾列表");
  back.href = "/ui/browse.html";
  view.appendChild(back);

  view.appendChild(el("h2", null,
    detail.folder.name + "（" + detail.folder.photo_count + " 張）"));
  view.appendChild(el("p", "folder-desc", detail.folder.description));

  if (detail.photos.length === 0) {
    view.appendChild(el("p", "message", "這個資料夾還沒有照片。"));
    return;
  }
  view.appendChild(el("p", "message", "點一張照片可以改資料夾。"));

  const wall = el("ul", "wall");
  detail.photos.forEach(function (photo) {
    const card = el("button", "photo");
    card.type = "button";
    card.dataset.photoId = photo.id;        // 待會兒用得到（event delegation）

    if (photo.thumbnail_url) {
      const image = document.createElement("img");
      image.src = photo.thumbnail_url;      // 例如 /photos/7/thumbnail
      image.alt = photo.text;
      card.appendChild(image);
    } else {
      // 舊資料沒有原圖：畫灰底占位，不假裝有圖（design1.md §10）
      card.appendChild(el("div", "placeholder", "無縮圖"));
    }
    card.appendChild(el("div", "caption", photo.text));

    const item = document.createElement("li");
    item.appendChild(card);
    wall.appendChild(item);
  });

  // event delegation：整面牆只掛一個監聽器，被點時往上找是哪一張
  wall.addEventListener("click", function (event) {
    const card = event.target.closest(".photo");
    if (!card) return;

    openFolderModal({
      photoId: Number(card.dataset.photoId),
      folders: folders,
      primary: {
        id: detail.folder.id,
        name: detail.folder.name,
        description: detail.folder.description
      },
      primaryVerb: "維持",                  // 上傳頁是「採用」，這裡是「維持」
      onAssigned: function () {
        location.reload();                  // 照片可能已被移走，整頁重讀最單純
      },
      onClosed: function () {}              // 關掉就關掉，什麼都不用做
    });
  });

  view.appendChild(wall);
}

// ---------- 進入頁面時決定畫哪一個 ----------
(async function start() {
  try {
    if (folderIdInUrl) {
      await showFolderPhotos(folderIdInUrl);
    } else {
      await showFolderList();
    }
  } catch (error) {
    view.textContent = "";
    view.appendChild(el("p", "message",
      "載入失敗：" + error + "。uvicorn 是不是沒在跑？"));
  }
})();
</script>

</body>
</html>
```

### 步驟 5：確認 `/` 轉址沒被動到

`app/main.py` 的 `GET /` 仍然轉到上傳頁（契約：`GET /` 轉址維持 upload），**不要改成轉去瀏覽頁**。本 phase 一行 Python 都不用改。確認一下：

```bash
grep -n "RedirectResponse(url=" app/main.py
```

預期：`return RedirectResponse(url="/ui/upload.html")`。

### 步驟 6：重新整理瀏覽器

`StaticFiles` 每次都直接讀檔，存檔後按重新整理就生效（`Cmd + Shift + R` 可強制清快取）。打開 <http://localhost:8000/ui/browse.html> 開始驗收。

---

## 驗收清單（瀏覽器實操）

本 phase **沒有自動化測試**（沿 Phase 14 原則）。每一項都要實際按下去、用眼睛核對。可以純手動，也可以用 **Playwright MCP**（常用工具：`browser_navigate`、`browser_snapshot`、`browser_click`、`browser_type`、`browser_select_option`、`browser_console_messages`；因為全站沒有 `alert`／`confirm`，**完全用不到 `browser_handle_dialog`**）。

- [ ] **1. 四個靜態檔都送得出來（三頁＋共用彈窗檔）**
      ```bash
      for path in /ui/upload.html /ui/browse.html /ui/ask.html /ui/folder_modal.js; do
        printf "%s " "$path"
        curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8000$path"
      done
      curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8000/
      ```
      預期：四行都是 `200`；最後一行是 `307 http://localhost:8000/ui/upload.html`（根路徑仍轉上傳頁）。
      （2026-08-21 校準：原指令用 `curl -I` 發 HEAD，而 FastAPI 的 `@app.get` 不自動支援 HEAD 會回 405；瀏覽器實際走 GET，改用 GET 驗證。）
- [ ] **2. 資料夾清單畫得出來**
      開 <http://localhost:8000/ui/browse.html>。
      **看到**：標題「資料夾」，底下**至少六張卡片**（未分類／收據／飲食／風景／文件／其他，加上 Phase 23 自建的「專案X」）。每張卡片有粗體的「名稱（N 張）」與一行灰色說明。
- [ ] **3. 點卡片進到縮圖牆**
      點「收據」那張卡片。
      **看到**：網址列變成 `…/ui/browse.html?folder=2`；畫面出現「← 回資料夾列表」、標題「收據（N 張）」、說明、提示「點一張照片可以改資料夾。」，以及一排方塊。
- [ ] **4. 有圖的顯示圖、舊資料顯示占位**
      **看到**：Phase 23 上傳的照片顯示真的縮圖；正式庫那 2 張舊照片顯示**灰底方塊、中間寫「無縮圖」**（design1.md §10 的行為）。每個方塊下面都有兩行以內的文字描述。
- [ ] **5. 點照片會開彈窗，① 的字是「維持」**
      點任一張照片（點在圖上或文字上都要能開）。
      **看到**：彈窗出現，① 那顆按鈕寫的是 `維持「收據」`（**不是**「採用」）；② 下拉裡有全部資料夾且**預設選中「收據」**；③ 兩個空的輸入框。
- [ ] **6. 走 ②：把照片改到別的資料夾**
      下拉選「飲食」→ 按「歸到這個資料夾」。
      **看到**：彈窗關閉、頁面自動重新整理，剛才那張照片**已經不在收據這面牆上**，標題張數少 1。
      按「← 回資料夾列表」→ **看到**「飲食」的張數多 1；點進飲食 → **看到**那張照片在裡面。
- [ ] **7. 走 ③：在瀏覽頁自建資料夾**
      在任一張照片的彈窗 ③ 輸入名稱 `旅遊`、說明 `出去玩拍的照片` → 按「建立並歸類」。
      **看到**：頁面重整、該照片離開目前資料夾；回列表 **看到**多了「旅遊（1 張）」卡片。
- [ ] **8. 走 ①：維持現狀**
      點一張照片 → 按 `維持「…」`。
      **看到**：彈窗關閉、頁面重整，照片**還在原本的資料夾**、張數不變。（後端照樣跑了一次 PATCH，把它歸到它原本就在的資料夾並重算向量，結果與原本相同，所以會等個一兩秒。）
- [ ] **9. 409 與 422 在彈窗內顯示**
      點一張照片 → ③ 輸入已存在的名稱 `收據` → 按「建立並歸類」→ **看到**彈窗不關、底部紅字 `（HTTP 409）…`。
      再把名稱清空 → 按「建立並歸類」→ **看到**紅字 `（HTTP 422）…`。
      **全程沒有任何瀏覽器原生對話框跳出來。**
- [ ] **10. × 與 Esc 都能關、且什麼都不改**
      點一張照片 → 按 `×`；再點一張 → 按 `Esc`。
      **看到**：兩次都只是彈窗消失，頁面沒有重整、張數沒有變化。
- [ ] **11. 空資料夾與不存在的資料夾**
      回列表 → 點一個 0 張的資料夾（例如「風景」）→ **看到**「這個資料夾還沒有照片。」。
      手動把網址改成 `http://localhost:8000/ui/browse.html?folder=999` → **看到**「載入失敗：Error: HTTP 404（/folders/999）。uvicorn 是不是沒在跑？」。
- [ ] **12. 上一頁／重新整理正常**
      在縮圖牆按瀏覽器的「上一頁」→ **看到**回到資料夾清單；在縮圖牆按重新整理 → **看到**還在同一個資料夾（因為狀態在網址上）。
- [ ] **13. 三頁互連**
      在 browse 頁點「上傳照片」→ 到上傳頁；點「問問題」→ 到問答頁；在這兩頁也都看得到「瀏覽資料夾」連結並點得回來。
- [ ] **14. 上傳頁沒被搬壞（回歸）**
      到上傳頁上傳一張照片 → **看到**彈窗照樣跳出、① 的字是 `採用「…」` → 按 ① → **看到**結果區更新成新資料夾名稱。
      這一項是本 phase 最重要的回歸檢查：證明彈窗搬到共用檔之後兩頁都還能用。
- [ ] **15. 真的只有一份彈窗程式碼（不留兩份）**
      ```bash
      grep -c "FOLDER_MODAL_HTML" app/static/folder_modal.js
      grep -n "FOLDER_MODAL_HTML\|fmInstall\|fm-backdrop" app/static/*.html || echo "OK：HTML 裡沒有殘留彈窗程式碼"
      grep -n "openFolderModal" app/static/upload.html app/static/browse.html
      grep -n "folder_modal.js" app/static/upload.html app/static/browse.html
      ```
      預期：第一行 `2`（一次定義、一次使用）；第二行 `OK：HTML 裡沒有殘留彈窗程式碼`；第三行兩個檔案**各一處**（都是呼叫，不是定義）；第四行兩個檔案各有一行 `<script src="/ui/folder_modal.js"></script>`。
- [ ] **16. 沒有原生對話框、沒有前端相依、沒有新增端點**
      ```bash
      grep -rnE "alert\(|confirm\(|prompt\(" app/static/ || echo "OK：沒有原生對話框"
      grep -riE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/ || echo "OK：沒有外部前端函式庫"
      ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
      git status --short
      ```
      預期：前三行都印出 `OK：…`；`git status` 只列出 `app/static/browse.html`（新檔）、`app/static/folder_modal.js`（新檔）、`app/static/upload.html`、`app/static/ask.html` 四個檔案——**沒有任何 `.py` 被改**。
- [ ] **17. 主控台乾淨**
      開開發者工具 Console → 重新整理 browse 頁、進一個資料夾、開一次彈窗。
      **看到**：沒有紅色錯誤。
      （注意：如果某張照片的圖檔真的不存在，`<img>` 會在 Console 留下 404 的網路錯誤。本頁的設計是「沒有路徑就不畫 `<img>`」，所以正常情況不該出現；真的出現代表資料庫有路徑但檔案不見了，那是 Phase 25 錯誤收尾要看的事。）
- [ ] **18. 後端測試數量完全沒變**
      ```bash
      cd /Users/linjunting/personalDocAI && source .venv/bin/activate
      pytest -q
      ```
      預期：`N passed`（N＝開工前的基線，即 **140 passed**）。
- [ ] **19. git commit**
      ```bash
      git add app/static/browse.html app/static/folder_modal.js app/static/upload.html app/static/ask.html
      git commit -m "feat: Phase 24 瀏覽頁——browse.html 資料夾卡片＋縮圖牆（無圖顯示占位）、點圖沿用三選項彈窗；modal 抽成 folder_modal.js 兩頁共用（upload 內嵌版已搬走不留兩份）、三頁互連"
      ```

---

## 常見問題

**Q1：為什麼不做成單頁應用（點資料夾不換網址，用 JavaScript 切畫面）？**
因為那要自己處理「上一頁」「重新整理」「網址代表哪個畫面」三件事，程式碼會多一倍，換來的只是少一次頁面重載——在本機根本感覺不到。用普通連結是這個 side project 的正解。

**Q2：選項 ①「維持」其實什麼都不用改，為什麼還是打了一次 `PATCH`？**
為了讓共用檔只有**一條**程式路徑：三個選項都是「送一次 PATCH、成功就通知呼叫方」。後端會照樣重算一次向量再寫回同樣的值（design1.md §7.3），結果與原本完全相同，只是多等一下下。想省那一兩秒的話，使用者直接按 `×` 就好，效果一樣。**不要**為此在共用檔裡加「如果是原資料夾就跳過」的分支——多一個分支要多一種情況測試，不划算。

**Q3：歸類成功後為什麼整頁重載，不只是把那張照片從畫面移掉？**
重載一行搞定，而且張數、其他資料夾的內容一定正確。手動改 DOM 要處理「張數要減一」「如果這是最後一張要顯示空狀態」等等，出錯機會多、收益是零。

**Q4：縮圖為什麼不用 lazy loading（捲到才載入）？**
照片數量是自己一張張上傳的，幾十張以內。真的想加的話 `<img loading="lazy">` 只是一個屬性——但那屬於視覺／效能打磨，**留給 Phase 26 決定**，本 phase 不加。

**Q5：可不可以順便加「刪除照片」或「刪除資料夾」按鈕？**
**不可以。** design1.md §3 與 §15 明列不做刪除，後端也根本沒有那個端點。

**Q6：可不可以加「點縮圖看大圖」？後端有 `GET /photos/{id}/image`。**
**不可以。** design1.md §7.4 的 `GET /photos/{id}/image` 是既有能力，但 §9 給瀏覽頁的職責只有「資料夾 → 縮圖牆 → 可再 PATCH 歸類」。加燈箱（lightbox）是第四個互動，屬於「順便做」。

**Q7：`folder_modal.js` 把 CSS 也寫在裡面，不覺得怪嗎？**
有一點，但這是「只有一份」的代價最低的作法：兩個頁面都不必各抄一份彈窗樣式。Phase 26 美化時會抽出共用的 `app/static/style.css`，屆時再把這段搬過去即可。現在不要為了美觀先抽。

**Q8：兩個 `<script>` 的變數會不會撞名？**
會，所以彈窗那份的名字都有 `fm` 前綴（`fmConfig`、`fmEl`…），瀏覽頁自己的用 `view`、`el`、`getJson`、`showFolderList` 等等，彼此不重疊。加新程式時注意別用到 `fm` 開頭的名字。

---

## 完成後的專案狀態

design1.md §0 的三個體驗缺口全部補完：**看得見**（縮圖牆，缺圖的誠實顯示占位）、**分得開**（資料夾 ＝ category，上傳與瀏覽兩處都能歸類）、**還能再問**（`/ask` 完全沒動）。網頁介面成為三頁互連的整體——`/ui/upload.html`（上傳＋彈窗）、`/ui/browse.html`（資料夾＋縮圖牆＋彈窗）、`/ui/ask.html`（問答），`GET /` 仍轉到上傳頁；彈窗程式碼全站只有 `app/static/folder_modal.js` 一份。**零框架、零打包工具、零新增端點、零新增測試**，`pytest -q` 仍是 **N＝140**。剩下的只有 Phase 25 的錯誤收尾與全量回歸，以及 Phase 26 的美化。
