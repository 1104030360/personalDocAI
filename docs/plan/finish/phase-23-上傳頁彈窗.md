# Phase 23：上傳頁彈窗（上傳成功後跳出三選項，決定收進哪個資料夾）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 只改一個檔案 `app/static/upload.html`——上傳成功（201）之後跳出一個彈窗，讓使用者用三種方式之一決定這張照片要收進哪個資料夾（採用 AI 建議／改選現有／自建新的），或直接關掉彈窗留在「未分類」。**零框架、零打包、零新增後端端點、零新增自動化測試。**

---

## 前置條件

- 需要已完成的 phase：
  - **Phase 20**：`POST /photos` 的 201 回應已經含 `folder`（一定是「未分類」）、`suggested_folder`（AI 建議的那一個）、`folders`（完整清單）、`thumbnail_url`。
  - **Phase 21**：`PATCH /photos/{id}/folder` 已可用，兩種 body 擇一（`{"folder_id": 2}` 或 `{"name": "...", "description": "..."}`），錯誤碼 404／409／422。
  - **Phase 22**：`GET /folders`（本 phase 用不到，但驗收時拿它核對張數很方便）。
- 開工前基線：先跑一次 `pytest -q` 把數字抄下來記成 **N**（Phase 22 完成後為 **140**，2026-08-21 校準）。**本 phase 做完必須還是 N＝140**——一個測試都不會增減。
- 環境：這個 phase 是**手動用瀏覽器操作**，走真模型那條路，所以三樣都要在跑：
  ```bash
  brew services start postgresql@17            # PostgreSQL@17（5433 埠）
  pgrep -fl "ollama serve" || open -a Ollama   # Ollama 是 App 版，不歸 brew services 管
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000
  ```

---

## 這個 phase 在做什麼

Phase 20 之後，上傳的照片一律先進「未分類」，後端同時把「AI 建議哪一個資料夾」和「現在有哪些資料夾」一起回給前端。但目前的上傳頁只會把文字印出來，**使用者沒有地方可以確認或改**。這個 phase 就補上那個「確認的動作」——design1.md §1 的 D4／D5：

```
① 採用 AI 推薦的那 1 個
② 改選其他現有資料夾（完整清單）
③ 自建新資料夾（名稱＋說明）
關掉 → 維持「未分類」，之後可到瀏覽頁再歸類
```

`★ 這就是 design1.md §2 的核心取捨：VLM 仍然自動分類，但不再默默定案。最後寫進 category 的，是使用者在彈窗裡選的那個資料夾名稱。`

**技術上跟 Phase 14 完全同一套規矩**：純 HTML ＋ 原生 JavaScript、零框架（不用 React／Vue／jQuery）、零打包工具（不用 npm／webpack／vite）、零 CSS 框架、零 CDN、**零新增自動化測試**。頁面醜沒關係，能用就好——美化是 Phase 26 的事，**不要在這個 phase 疊任何裝飾**（不要動畫、不要漸層、不要圖示字型）。

### ⚠ 一條硬規定：禁用 `alert()` / `confirm()` / `prompt()`

這三個是瀏覽器內建的「原生對話框」。它們看起來很方便（一行就有彈窗），但本專案**一律不准用**，理由有兩個：

1. **它們會整個卡住頁面。** `alert()` 執行時，JavaScript 停在那一行不動，使用者不按確定什麼都不會發生。
2. **更關鍵：它們會讓瀏覽器自動化卡住。** 驗收時我們可能用 Playwright MCP 操作瀏覽器；原生對話框不是網頁裡的元素，自動化工具「看不到」它，必須另外呼叫處理對話框的專用指令去按掉，一個沒處理就整個流程停擺、最後逾時失敗。

**取代作法：所有訊息都畫在頁面裡。** 本 phase 的彈窗底部固定放一個空的 `<p class="fm-error" id="fm-error">`，任何錯誤（409 重名、422 空名、連線失敗）都用

```javascript
document.getElementById("fm-error").textContent = "（HTTP 409）資料夾名稱已存在";
```

寫進去。使用者看得到，自動化也讀得到（它就是一個普通的 DOM 節點）。成功訊息同理，寫進上傳頁的結果區 `<pre id="result">`。

> 這條規矩在 Phase 24、26 一樣有效，驗收清單也會用 `grep` 檢查。

**名詞**：
- **modal（彈窗／互動視窗）**＝蓋在頁面上方、要求使用者先處理它的一小塊區域。它**不是**瀏覽器的新視窗，就是同一個頁面裡的一個 `<div>`，只是用 CSS 疊在最上層。
- **backdrop（遮罩）**＝彈窗後面那層半透明的深色背景，把底下的頁面壓暗，視覺上告訴使用者「先處理這個」。也是一個 `<div>`。
- **`position: fixed; inset: 0;`**＝CSS 寫法，意思是「固定貼住瀏覽器視窗的上下左右四邊」，也就是鋪滿整個畫面。遮罩就靠這兩行。
- **`hidden` 屬性**＝HTML 元素上加 `hidden` 就不會顯示。用 JavaScript 寫 `element.hidden = true/false` 就能收合／展開，比操作 `style.display` 好讀。
- **`PATCH`**＝HTTP 方法之一，語意是「只改這個資源的一部分」（這裡是只改照片的資料夾），對應 `POST`（新增）、`GET`（讀取）。用 `fetch` 時寫 `method: "PATCH"`。
- **callback（回呼函式）**＝把一個函式當參數傳給別人，讓對方在「某件事發生時」回頭呼叫它。本 phase 的彈窗不知道自己被誰打開，所以歸類成功時就呼叫呼叫方給的 `onAssigned` 函式，把結果交回去。
- **`addEventListener("click", …)`**＝幫某個元素掛上「被點時要跑的函式」。
- **`event.key === "Escape"`**＝鍵盤事件裡判斷「使用者按的是 Esc 鍵」。
- **`JSON.stringify(物件)`**＝把 JavaScript 物件轉成 JSON 字串，送 `PATCH` 的 body 時要用。
- **`async` / `await`**＝「等伺服器回應回來再繼續下一行」的寫法；等待期間頁面不會卡死（這正是 `alert` 做不到的事）。

---

## ASCII 圖：彈窗的三個選項與四條出路

```
 使用者按「上傳」
        │
        ▼
 POST /photos ──201──▶ { id: 7,
                         metadata: { category: "未分類", … },
                         folder:           { id:1, name:"未分類",  description:"…" },
                         suggested_folder: { id:2, name:"收據",    description:"發票、消費憑證、購物明細。" },
                         folders: [ 未分類, 收據, 飲食, 風景, 文件, 其他, … ],
                         thumbnail_url: "/photos/7/thumbnail" }
        │
        │  結果區先畫出七行（資料夾＝未分類），同時開彈窗
        ▼
 ┌──────────────────── 彈窗（modal，蓋在頁面上）────────────────────┐
 │  要把這張照片放到哪個資料夾？                              [ × ] │
 │ ───────────────────────────────────────────────────────────────  │
 │  ①  [ 採用「收據」 ]          ← suggested_folder.name             │
 │      發票、消費憑證、購物明細。 ← suggested_folder.description     │
 │ ───────────────────────────────────────────────────────────────  │
 │  ②  改選其他現有資料夾：                                          │
 │      [ 收據 ▾ ]  [ 歸到這個資料夾 ]   ← <select> 綁全部 folders    │
 │ ───────────────────────────────────────────────────────────────  │
 │  ③  自建新資料夾：                                                │
 │      [名稱：專案X____] [說明：跟課程作業有關的照片____]            │
 │      [ 建立並歸類 ]                                               │
 │ ───────────────────────────────────────────────────────────────  │
 │  ⚠ （HTTP 409）資料夾名稱已存在   ← 錯誤畫在這裡，絕不用 alert()   │
 └───────────────────────────────────────────────────────────────────┘
      │ ①             │ ②                │ ③                │ × 或 Esc
      ▼               ▼                  ▼                  ▼
 PATCH /photos/7/folder                              不呼叫任何 API
 {folder_id:2}   {folder_id:3}   {name:"專案X",
                                  description:"…"}
      │               │                  │                  │
      └───────┬───────┘                  │                  │
              │  200                     │  200             │
              ▼                          ▼                  ▼
     關閉彈窗；結果區「資料夾（category）」改成新名稱   結果區顯示
                                                    「已放進「未分類」，
      ✗ 失敗時彈窗不關，紅字留在 ⚠ 那行：              之後可到瀏覽頁再歸類。」
        409＝名稱重複  422＝名稱空白  404＝照片不見了
```

---

## 逐步驟操作

### 步驟 1：先看懂 201 回應長什麼樣（2 分鐘）

動手改頁面之前，先親眼確認後端真的回了那些欄位。啟動 uvicorn 後，用手邊任一張 JPEG／PNG（沒有的話 `screencapture -x /tmp/real_photo.png` 產一張）：

```bash
curl -s -X POST http://localhost:8000/photos \
  -F "file=@/tmp/real_photo.png;type=image/png" | python -m json.tool
```

預期輸出裡**一定要有** `folder`、`suggested_folder`、`folders`、`thumbnail_url` 四個鍵（Phase 20 的成果）。沒有的話代表 Phase 20 沒完成，先回頭補，不要硬寫前端。

### 步驟 2：把 `app/static/upload.html` 整份換掉

整份照抄覆蓋（原本的檔案內容全部不留）：

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>上傳照片 — PersonalDocAI</title>
<style>
  body { font-family: system-ui, "PingFang TC", sans-serif;
         max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  nav a { margin-right: 1rem; }
  form { margin: 1rem 0; }
  button { padding: 0.4rem 1rem; }
  pre { background: #f4f4f4; padding: 1rem; white-space: pre-wrap;
        word-break: break-word; min-height: 4rem; }
</style>
</head>
<body>

<h1>PersonalDocAI</h1>
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
<hr>

<h2>上傳照片</h2>
<p>選一張 JPEG 或 PNG。AI 會看圖並存成文字描述＋四個欄位，照片先放進「未分類」，
接著在彈出的視窗裡決定要收進哪個資料夾。</p>

<form id="upload-form">
  <input type="file" id="file-input" accept="image/jpeg,image/png" required>
  <button type="submit" id="submit-button">上傳</button>
</form>

<pre id="result">（尚未上傳）</pre>

<!-- ↓↓↓ 共用彈窗：這一整段（含 script 標籤）在 Phase 24 會原封不動搬到 /ui/folder_modal.js ↓↓↓ -->
<script>
/* 資料夾歸類彈窗（modal）：把某張照片歸到某個資料夾。

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
  holder.innerHTML = FOLDER_MODAL_HTML;
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
</script>
<!-- ↑↑↑ 共用彈窗結束 ↑↑↑ -->

<script>
// ===== 上傳頁自己的程式（這段不會搬走）=====
const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const button = document.getElementById("submit-button");
const result = document.getElementById("result");

// 沒有值的欄位顯示成「（無）」，比顯示 null 好懂
function orNone(value) {
  return (value === null || value === undefined || value === "") ? "（無）" : value;
}

// 把上傳結果畫到結果區。歸類成功後資料夾名稱會變，所以獨立成一個參數。
// 提醒：資料夾名稱就是 category（design1.md §4），不是兩個東西。
function renderResult(body, folderName, note) {
  const m = body.metadata;
  const items = (m.items && m.items.length > 0) ? m.items.join("、") : "（無）";
  result.textContent = [
    "✅ 上傳成功（HTTP 201）",
    "照片 id：" + body.id,
    "文字描述：" + body.text,
    "資料夾（category）：" + folderName,
    "地點：" + orNone(m.location),
    "物品：" + items,
    "內容時間：" + orNone(m.content_time),
    "",
    note
  ].join("\n");
}

form.addEventListener("submit", async function (event) {
  event.preventDefault();               // 不要讓瀏覽器用傳統方式送出表單並跳頁

  const file = fileInput.files[0];
  if (!file) {
    result.textContent = "請先選一個檔案。";
    return;
  }

  button.disabled = true;
  result.textContent = "上傳中…（本機模型看圖可能要等 10〜60 秒，請耐心等候）";

  // FormData 會自動組成 multipart/form-data，欄位名必須是 file
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/photos", { method: "POST", body: formData });
    const body = await response.json();

    if (response.status === 201) {
      renderResult(
        body,
        body.folder.name,
        "AI 建議放進「" + body.suggested_folder.name + "」，請在彈出的視窗裡決定。"
      );
      openFolderModal({
        photoId: body.id,
        folders: body.folders,
        primary: body.suggested_folder,
        primaryVerb: "採用",
        onAssigned: function (folder) {
          renderResult(body, folder.name, "✅ 已歸到「" + folder.name + "」。");
        },
        onClosed: function () {
          renderResult(
            body,
            body.folder.name,
            "已放進「" + body.folder.name + "」，之後可到瀏覽頁再歸類。"
          );
        }
      });
    } else {
      // 415＝不是 JPEG/PNG；422＝VLM 看不懂（什麼都沒存）；其他＝伺服器問題
      const detail = (typeof body.detail === "string")
        ? body.detail : JSON.stringify(body.detail);
      result.textContent = "❌ 失敗（HTTP " + response.status + "）\n" + detail;
    }
  } catch (error) {
    result.textContent = "❌ 請求失敗：" + error
      + "\n最常見原因：uvicorn 沒在跑，或網址、埠號不對。"
      + "\n若 uvicorn 其實在跑，改看它的終端機視窗印出的錯誤訊息。";
  } finally {
    button.disabled = false;
  }
});
</script>

</body>
</html>
```

**兩個要記住的細節**：

1. 上面第一個 `<script>` 區塊被註解框起來，是**刻意**的——Phase 24 會把那一整段原封不動剪到 `app/static/folder_modal.js`，兩頁共用。所以現在就寫成「不碰頁面其他部分、只靠 `onAssigned`／`onClosed` 兩個 callback 對外溝通」的樣子，屆時搬家**程式碼一行都不用改**（Phase 24 只會補兩句註解）。
2. 導覽列現在還是兩個連結（`browse.html` 還不存在）。第三個連結由 Phase 24 一起加。

### 步驟 3：重新整理頁面

`StaticFiles` 每次都直接讀檔案，所以**存檔後在瀏覽器按重新整理就生效**，不用重啟 uvicorn（uvicorn 的 `--reload` 只管 Python 檔）。若畫面沒變，按 `Cmd + Shift + R` 強制重新整理清掉快取。

打開 <http://localhost:8000/ui/upload.html> 就可以開始下面的驗收。

---

## 驗收清單（瀏覽器實操）

這個 phase **沒有自動化測試**（沿 Phase 14 原則：頁面驗收以手動瀏覽器操作為準）。下面每一項都要**實際按下去、用眼睛核對畫面**。

可以純手動，也可以用 **Playwright MCP** 代勞；用 MCP 時常用的幾個工具是：`browser_navigate`（開網址）、`browser_snapshot`（讀出畫面上有哪些元素）、`browser_click`（點）、`browser_type`（打字）、`browser_select_option`（選下拉）、`browser_file_upload`（選檔案，要先點「選擇檔案」讓檔案選擇器出現）、`browser_console_messages`（看主控台）。**因為我們全程不用 `alert`／`confirm`，所以不需要 `browser_handle_dialog`——一次都不會用到，這正是禁用原生對話框換來的好處。**

準備一張測試照片（沒有的話）：

```bash
screencapture -x /tmp/real_photo.png
```

- [ ] **1. 上傳成功會開彈窗**
      開 <http://localhost:8000/ui/upload.html> → 按「選擇檔案」挑 `/tmp/real_photo.png` → 按「上傳」。
      **看到**：按鈕變灰、結果區顯示「上傳中…」；等 10〜60 秒後
      （a）結果區出現八行，其中一行是 `資料夾（category）：未分類`；
      （b）畫面壓暗，中央出現彈窗，標題是「要把這張照片放到哪個資料夾？」。
- [ ] **2. 彈窗三個選項都在、內容正確**
      **看到**：① 一顆按鈕，文字是 `採用「某資料夾名」`（名稱應該是六個預設資料夾之一），按鈕下方一行灰字是那個資料夾的說明；② 一個下拉選單，展開後**至少六個**選項（未分類／收據／飲食／風景／文件／其他），旁邊一顆「歸到這個資料夾」；③ 兩個輸入框（名稱、說明）＋一顆「建立並歸類」；最底下有一塊空白的訊息列。
- [ ] **3. 走選項①：採用 AI 建議**
      按 `採用「…」`。
      **看到**：彈窗消失、頁面恢復正常；結果區的 `資料夾（category）：` 變成剛才那個名稱，最後一行是 `✅ 已歸到「…」。`
      核對後端：
      ```bash
      curl -s http://localhost:8000/folders | python -m json.tool
      ```
      **看到**：那個資料夾的 `photo_count` 比上傳前多 1，`未分類` 沒有增加。
- [ ] **4. 走選項②：改選其他現有資料夾**
      再上傳一次同一張照片 → 彈窗出現後，下拉選 `飲食` → 按「歸到這個資料夾」。
      **看到**：彈窗關閉，結果區 `資料夾（category）：飲食`、`✅ 已歸到「飲食」。`
- [ ] **5. 走選項③：自建新資料夾**
      再上傳一次 → 在 ③ 的名稱框輸入 `專案X`、說明框輸入 `跟課程作業有關的照片` → 按「建立並歸類」。
      **看到**：彈窗關閉，結果區 `資料夾（category）：專案X`。
      核對後端：`curl -s http://localhost:8000/folders | python -m json.tool` **看到**清單裡多了 `專案X`（`is_inbox` 是 `false`、`photo_count` 是 1）。
- [ ] **6. 409：自建一個已經存在的名稱**
      再上傳一次 → ③ 名稱輸入 `收據`（已存在）→ 按「建立並歸類」。
      **看到**：**彈窗不關**，底部出現紅字 `（HTTP 409）…`（訊息內容由 Phase 21 決定）；**畫面上沒有任何瀏覽器原生對話框跳出來**。
      接著在同一個彈窗改按 ①，**看到**彈窗正常關閉、歸類成功——證明錯誤後還能繼續操作。
- [ ] **7. 422：自建但名稱空白**
      再上傳一次 → ③ 名稱只按空白鍵（或整個留空）→ 按「建立並歸類」。
      **看到**：彈窗不關，底部紅字顯示 `（HTTP 422）…`。
- [ ] **8. 按 × 關閉＝留在未分類**
      再上傳一次 → 按彈窗右上角的 `×`。
      **看到**：彈窗關閉，結果區最後一行是 `已放進「未分類」，之後可到瀏覽頁再歸類。`，而且 `資料夾（category）：未分類`。
      核對後端：`curl -s http://localhost:8000/folders | python -m json.tool` **看到** `未分類` 的 `photo_count` 加 1。
- [ ] **9. 按 Esc 關閉，行為與 × 相同**
      再上傳一次 → 按鍵盤 `Esc`。**看到**：同第 8 項。
- [ ] **10. 全程沒有原生對話框，程式碼裡也沒有**
      ```bash
      grep -nE "alert\(|confirm\(|prompt\(" app/static/upload.html || echo "OK：沒有原生對話框"
      ```
      預期：`OK：沒有原生對話框`
- [ ] **11. 主控台乾淨**
      按 `Cmd + Option + I` 開開發者工具 → Console 分頁 → 重新整理並再走一次上傳＋①。
      **看到**：沒有紅色錯誤（特別不該出現 CORS 字樣——頁面與 API 同源）。
- [ ] **12. 沒有引入任何前端相依、沒有新增端點**
      ```bash
      ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
      grep -riE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/ || echo "OK：沒有外部前端函式庫"
      git status --short
      ```
      預期：前兩行印出 `OK：…`；`git status` 顯示**只有 `app/static/upload.html` 一個檔案被改**。
- [ ] **13. 後端測試數量完全沒變**
      ```bash
      cd /Users/linjunting/personalDocAI && source .venv/bin/activate
      pytest -q
      ```
      預期：`N passed`（N＝開工前的基線，即 **140 passed**）。本 phase 不新增、不修改任何自動化測試。
- [ ] **14. git commit**
      ```bash
      git add app/static/upload.html
      git commit -m "feat: Phase 23 上傳頁彈窗——201 後跳三選項 modal（採用建議／改選現有／自建），關閉留未分類；禁用 alert，錯誤顯示於彈窗內；零框架零新增測試"
      ```

---

## 常見問題

**Q1：為什麼不用 `<dialog>` 這個 HTML 內建元素？它本來就是做彈窗的。**
`<dialog>` 很好，但它的 `showModal()`／`close()` 與 `::backdrop` 樣式是另一套要學的東西，而且 Phase 24 要把同一份程式碼餵給兩個頁面時，用普通 `<div>` 比較好掌握（想看它長怎樣，直接在開發者工具把 `hidden` 拿掉就看得到）。兩種都能過驗收，本專案選簡單好懂那條。**已經照本文寫完就不要再改成 `<dialog>`**——那是純粹的重工。

**Q2：`fetch` 用 `PATCH` 一定要自己加 `Content-Type: application/json` 嗎？**
要。送 JSON 時如果不加這個標頭，FastAPI 會不知道 body 是 JSON，直接回 422。`POST /photos` 那邊不用加，是因為 `FormData` 會由瀏覽器自動帶上正確的 `multipart/form-data` 標頭（自己手動加反而會壞掉，因為少了分隔字串）。

**Q3：使用者在 409 之後不想改名，想直接放棄怎麼辦？**
按 `×` 或 `Esc` 就好，照片留在「未分類」，之後可到瀏覽頁再歸類。這是 design1.md §12 明訂的行為，不需要在彈窗裡另外做「取消」按鈕。

**Q4：要不要在上傳頁把剛上傳的照片縮圖顯示出來？回應裡明明有 `thumbnail_url`。**
**不要。** 本 phase 的範圍就是彈窗；縮圖牆是 Phase 24 瀏覽頁的事。回應帶著 `thumbnail_url` 是給 Phase 24 用的，不代表這一頁現在就得畫。

**Q5：要不要加「不要再問我，以後都自動採用 AI 建議」的選項？**
**不要。** design1.md §14 明列被否決的方案：「沒選就自動採用 AI 第一推薦」——會失去 human-in-the-loop，這正是整個增量的重點。

**Q6：彈窗開著的時候，使用者還能再按上傳嗎？**
能，但沒必要防。彈窗蓋住整個畫面（遮罩鋪滿視窗），底下的按鈕點不到；就算真的用鍵盤跳過去按了，也只是再上傳一張、再開一次彈窗，資料不會壞。**不要為此加狀態機或焦點鎖定（focus trap）**，那是過度設計。

**Q7：`fmConfig`、`fmEl` 這些名字前面為什麼都加 `fm`？**
因為這段程式和上傳頁的程式跑在**同一個全域範圍**裡（兩個 `<script>` 沒有分隔），名字撞到就會互相蓋掉。加個 `fm`（folder modal）前綴是最省事的隔離法。同理，Phase 24 把它搬進 `folder_modal.js` 之後仍然是全域，前綴要留著。

**Q8：可以順便加上傳進度條／拖放上傳／照片預覽嗎？**
**不可以**（Phase 14 的 Q6 已經回答過同一題）。而且視覺打磨統一留到 Phase 26，那時候會有一套完整的設計 tokens，現在疊上去的東西到時候都要重寫。

---

## 完成後的專案狀態

上傳流程終於「閉環」了：選檔 → AI 看圖 → 照片先進「未分類」→ **彈窗確認要收進哪個資料夾** → PATCH 定案，或直接關掉留在未分類等之後再處理。使用者第一次能用滑鼠完成 design1.md §2 的完整體驗，而且後端沒有多一個端點、測試數量一個都沒變（仍是 **N**）。彈窗程式碼已經寫成可重用的形狀，Phase 24 會把它整段搬進 `app/static/folder_modal.js`，讓瀏覽頁用同一份。
