# Phase 52：待決定新頁 `/ui/pending.html`

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；
> 想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 新建一個純 HTML 頁面 `app/static/pending.html`，
> 把 `browse.html` 裡「待決定分頁」那段程式（`showPending()` 那一整套）**搬**過來，
> 讓待決定變成一個自己的網址 `/ui/pending.html`。
> **本 phase 不新增任何端點**（仍然是 20 個），**也還不動 `browse.html`**。

**為什麼要做這個：**
現在的「待決定」躲在瀏覽頁的第一個分頁裡（`/ui/browse.html` 不帶任何 query 就是它）。
問題是：待決定裡的照片**還沒歸類完**，它是「待辦工作」；而瀏覽頁的另外兩個分頁
（資料夾、待辦）放的是**已經定案的成果**。兩種心智混在同一頁，
使用者每次都要先想「我現在是要處理東西，還是要找東西」。
design5.md D1 把待決定升成頂欄的一格，這一步就是先把那個頁面做出來。

**為什麼要分成 Phase 52（搬過來）與 Phase 55（把舊的刪掉）兩步：**
如果一次改兩個檔案（新建 `pending.html` ＋ 同時砍掉 `browse.html` 的待決定分頁），
壞掉的時候你分不出是「新頁抄錯了」還是「舊頁刪過頭」——兩個檔案同時在變，
沒有一個「已知是好的」可以拿來對照。
分兩步之後，Phase 52 做完的當下**兩邊都能開、行為一模一樣**，
你可以並排比對（左邊 `/ui/browse.html`、右邊 `/ui/pending.html`），
確認新頁真的沒抄漏；確認完了，Phase 55 再放心把舊的整段刪掉。
**這一段「暫時有兩份」是刻意的、而且只活到 Phase 55**——
不是「留著以防萬一」（本專案的規矩是不留過渡產物，Phase 55 一定要把它清乾淨）。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 收件箱（inbox） | 名字叫「未分類」的那一個資料夾（資料庫裡 `folder.name` 就只有這三個字，「收件箱」是它的角色，文件慣用「未分類(收件箱)」當簡稱），`GET /folders` 回傳的欄位 `is_inbox` 是 `true` 的那一筆。全系統至多一個（資料庫用 partial unique index 保證）。**「待決定」不是新的儲存位，它就是收件箱的另一個說法**——待決定牆＝收件箱裡的照片 |
| 定案 | 把照片從收件箱歸進一個真資料夾。**不可逆**（design2.md：後端擋掉已定案照片的再次歸類，回 409）。所以「歸進去」＝「離開待決定」 |
| 彈窗鏈（modal chain） | 一個彈窗關掉之後自動打開下一個。本頁走兩關：**抽屜（選資料夾）→ 實體（要不要釘上某件東西）**。第三關「待辦」在階段甲**不開**，理由見 §3 |
| query string（查詢字串） | 網址問號後面那一段，例如 `browse.html?tab=tasks` 裡的 `tab=tasks`。本頁**完全沒有** query string——網址就只是 `/ui/pending.html` |
| `app.mount("/ui", StaticFiles(...))` | `app/main.py` 裡的一行設定：把 `app/static/` 這個資料夾整個當靜態檔案送出去。**所以新增一個 `.html` 檔＝新增一個網址，但不算新增 API 端點**——`/openapi.json` 裡不會多任何東西 |
| event delegation（事件委派） | 不在每張照片卡上各掛一個「被點了要做什麼」，而是在整面牆（`<ul>`）上只掛**一個**，被點時用 `event.target.closest(".photo")` 往上找出到底點到哪一張。照片是 JS 動態產生的，這樣寫最省事 |

---

## 1. 對應 design5.md 章節

- **D1**（待決定換位子：從瀏覽頁 tab 移到頂欄）
- **D2**（點開仍是彈窗；D2 寫的完整三關是**最終態**——階段甲依 §6.2 暫維持
  抽屜 → 實體兩關，第三關由階段丙 Phase 70 接上）
- **§0 階段甲**（「新頁 `/ui/pending.html`」那一行；何時算過的第二條）
- **§1.1**（推翻 design2.md D4／design3.md D15「瀏覽入口為待決定｜資料夾｜待辦」）
- **§2 流程圖尾端「待決定 /ui/pending.html」那一段**（縮圖牆只含已入庫、仍在收件箱的照片）
- **§6.2**（本 phase 的正文規格：搬 `showPending()`、空狀態文案改寫、
  階段甲仍是抽屜→實體、階段丙才走完整三關）
- **§11 會動到的檔**（第 1 列 `app/static/pending.html`｜甲｜新建）
- **§12 階段甲驗收第 2 條**（開 `/ui/pending.html` 看得到收件箱照片；點一張會開歸類窗——原文還要求「彈窗最上面是原圖」，那半條由 Phase 54 補上，逐條驗收時別拿 Phase 52 的成品對整條）

---

## 2. 前置條件

- **增量四已全部完成**（Phase 38〜51）。開工基線用三個指令確認：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**405 passed ＋ 0 skipped**。
  （⚠ **絕對不要同時跑兩份 pytest**——兩份會互相 TRUNCATE 同一個測試庫，
  症狀是「大量看似隨機的 404 找不到照片」，看起來像程式壞了，其實只是撞在一起。）

```bash
docker compose ps --no-trunc
```

  預期：`db` 是 `Up … (healthy)`、`app` 是 `Up …`。
  沒起來的話：`docker compose -f compose.yaml -f compose.dev.yaml up -d`（開發熱重載）。

```bash
curl -k https://127.0.0.1:8000/health
```

  預期：`{"status":"ok"}`。
  ⚠ **網址開頭是 `https`，不是 `http`**——容器的啟動指令固定帶憑證，`http://localhost:8000` 完全連不上。

- **正式庫的收件箱裡最好至少有一張照片**，不然做完只看得到空狀態。查法（唯讀）：

```bash
psql -d PersonalDocAI -c \
  "SELECT f.name, count(p.id) AS 張數
     FROM folder f LEFT JOIN photo p ON p.folder_id = f.id
    GROUP BY f.id, f.name ORDER BY f.id;"
```

  「未分類」那一列（psql 輸出的 name 欄只有「未分類」三個字，沒有括號）是 0 的話，先到 `/ui/upload.html` 上傳一張、
  在彈出的抽屜窗按**「稍後再說」**，它就會留在待決定。
  （本機模型看一張圖要 1〜5 分鐘；想快就先把上傳頁頁首的「AI 模型」開關撥到「雲端」。）

- 本 phase **不需要** Phase 53〜55 先做完。它是階段甲的第一步，沒有前置 phase。

---

## 3. 範圍

### 做

- 新建 `app/static/pending.html`（**唯一一個新增檔案**）。
- 內容＝把 `browse.html` 的這幾段**搬**過來並去掉分頁相關的部分：
  - 小工具 `el()`、`保護數字單位()`、`getJson()`、`照片卡()`
  - 彈窗鏈第二關 `接著釘實體()`
  - 主畫面 `showPending()`（去掉 `renderTabs(...)` 與只為了頁籤計數而打的 `GET /tasks`）
- 空狀態文案改成 design5 §6.2 的版本（見 §4.3 的第 3 步）。
- 掛兩支既有彈窗檔：`folder_modal.js`、`entity_modal.js`。
- 用瀏覽器實操驗收（本專案前端慣例：純前端零新增自動化測試）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 動 `app/static/browse.html` | 這是 **Phase 55** 的事。本 phase 做完是「兩邊都能開、行為一樣」，才有得比對。`git status --short -- app` 只准出現一個 `?? app/static/pending.html` |
| 動 `app/static/folder_modal.js`（加窗頂原圖） | 那是 **Phase 54**。一次改一個檔，壞了才分得出是誰 |
| 動任何一頁的 `site-header`（加「待決定（N）」那一格） | 那是 **Phase 53**。所以本 phase 做完**點不到**這一頁，要自己打網址——這是正常的，不是漏做 |
| 開第三關「待辦」彈窗（`task_modal.js`） | design5 §6.2 寫明階段甲的待決定鏈**可暫維持抽屜 → 實體兩關**——本計畫就取這條路。理由是上傳鏈這時還在（上傳當下就會開三關窗），待決定只是補完用。改成完整三關是 **Phase 70**，而且要先有 Phase 61 把待辦建議寫進資料庫，現在讀不到建議、開了也是空窗 |
| 新增任何後端端點 | design5 §5 的兩支新端點（`GET /ingest-jobs`、`POST …/dismiss`）是階段乙 Phase 64。本 phase 端點恰 **20**，一支不多 |
| 抽一支共用的 `photo_card.js` 給兩頁用 | 增量五契約只認可兩個新前端檔（`pending.html`、`progress_panel.js`）。多開一支沒人知道的共用檔，Phase 67／70 的實作者會不知道它存在。本專案既有做法就是**頁面各自帶自己的小工具**——`esc()` 現在就在 `upload.html`／`ask.html`／`camera-desk.html` 各有一份，`camera-desk.html` 還寫了註解「與 upload.html 同一份寫法」。照這個前例走 |
| 在這一頁放「AI 模型：本機｜雲端」開關 | design5 §3「做」的清單裡沒有這條。實體窗的「再建議一個」確實會呼叫 AI，但那顆開關的狀態存在**伺服器**（`config.AI_BACKEND`），在上傳頁撥了全站都跟著，不必每頁都放一顆。⚠ design5 §6.1 的頂欄示意圖有畫 `[AI 本機｜雲端]`、但沒有指派誰補——要不要補到全部五頁是**未指派的產品決策**（完整說明在 phase-53 §3），★G1（Phase 55 結尾）時當面請產品負責人裁決 |
| 做「一次勾多張批次歸類」 | design5 §3「不做」第 1 條 |
| 做刪除照片 | 全系統沒有刪除端點，`openapi.json` 零 `DELETE`（Phase 37 釘死） |
| 把 `browse.html` 的舊網址 302 轉到新頁 | design5 §6.3 明文不做（那是 Phase 55 的「明確不做」，這裡先記著，免得順手做了） |
| 用 `alert`／`confirm`／`prompt` | 全站鐵律。錯誤一律寫進頁面裡的文字 |
| 用 `innerHTML` 塞 AI 產生的文字 | 全站鐵律。動態內容一律 `textContent` |

---

## 4. 實作步驟

### 4.1 先看懂要搬的是哪幾段（不寫程式，只讀）

- [ ] 打開 `app/static/browse.html`，對照下表把要搬的段落標出來：

| 行數（約） | 段落 | 本 phase 怎麼處理 |
|---|---|---|
| 24〜26 | 三行 `<script src>`（`folder_modal.js`／`entity_modal.js`／`photo_detail_modal.js`） | 新頁只要**前兩支**。`photo_detail_modal.js` 是唯讀詳情窗，待決定牆點下去要開的是**歸類窗**，不是它 |
| 41〜46 | `function el(tag, className, text)` | 原封不動抄過去 |
| 48〜50 | `function 保護數字單位(text)` | 原封不動抄過去 |
| 52〜58 | `async function getJson(url)` | 原封不動抄過去 |
| 62〜77 | `function renderTabs(active, pendingCount, taskCount)` | **不抄**。新頁沒有分頁 |
| 81〜114 | `function 照片卡(photo)` | 原封不動抄過去 |
| 116〜135 | `async function 接著釘實體(photoId)` | 原封不動抄過去 |
| 138〜192 | `async function showPending()` | 抄過去，但拿掉 `renderTabs(...)` 那一行、拿掉只為頁籤計數而打的 `GET /tasks`，並改空狀態文案 |
| 195〜312 | `showFolderList()`／`showTasks()`／`showFolderPhotos()` | **不抄**。那三個是瀏覽頁的事 |
| 315〜331 | `(async function start(){…})()` | 抄「try / catch 顯示同一句錯誤訊息」的形狀，但裡面只呼叫 `showPending()` |

> 表裡的「原封不動」指**函式本體的程式碼**逐字相同；各函式上方的說明註解在 §4.2
> 有小幅改寫或新增（拿掉「分頁」「計數」這類搬過來就不成立的字眼；
> 原本沒有註解的函式（如 `保護數字單位()`）補上了說明）。
> 抄的時候一律以 §4.2 的完整檔為準——那一份就是最終內容。

- [ ] 特別看一下第 100〜108 行 `照片卡()` 裡那段看起來很怪的東西：

```javascript
  const 片語 = "待決定分頁的";
  const 片語位置 = 說明.indexOf(片語);
```

  這**不是**分頁邏輯，別以為可以刪。它是 Phase 44 加的排版保護：
  正式庫裡剛好有一張照片，AI 寫的說明文字裡含有「待決定分頁的」這幾個字，
  中文換行會把它拆得很難看，所以那幾個字被包進一個不換行的 `<span>`。
  **照抄，一個字都不要改**——`tests/integration/test_design4_error_paths.py`
  有一顆測試在掃 `browse.html` 裡的這幾行（它掃的是 `browse.html`，
  所以新頁抄不抄都不影響測試，但行為要一致才叫「搬」）。

### 4.2 建檔

- [ ] 建立 `app/static/pending.html`，**整份照抄下面這一份**（這是完整可貼上的檔案，不要自己補東西）：

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>待決定 — PersonalDocAI</title>
<link rel="stylesheet" href="/ui/style.css">
</head>
<body>

<!-- 頁首先照現況抄那三格；唯一差別是本頁不標 aria-current（待決定還不在導覽裡，
     這一頁也不是那三格中的任何一頁，標了反而是錯的）。
     「待決定（N）」那一格是 Phase 53 才加的——本 phase 刻意不動任何頁首，
     免得跟 Phase 53 撞在同一段程式上。所以現在要開這一頁得自己打網址。 -->
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <nav class="site-nav" aria-label="主要導覽">
    <a href="/ui/upload.html">上傳照片</a>
    <a href="/ui/browse.html">瀏覽資料夾</a>
    <a href="/ui/ask.html">問問題</a>
  </nav>
</header>

<main class="page">

<h2>待決定</h2>
<p class="lead">還沒歸類的照片都在這裡。點一張，在彈出的視窗裡決定要收進哪個資料夾——
歸進去就定案，之後不能再改。</p>

<div id="view"><p class="message">載入中…</p></div>

</main>

<script src="/ui/folder_modal.js"></script>
<script src="/ui/entity_modal.js"></script>
<script>
// 待決定頁（增量五 Phase 52；design5.md D1／D2／§6.2）。
// 這一頁就是「收件箱（未分類）的縮圖牆」——待決定不是新的儲存位，
// 它是收件箱的另一個說法。照片歸進真資料夾就定案、離開這一頁（不可逆）。
//
// 這一頁只有一個畫面：沒有分頁、沒有 query string，網址就是 /ui/pending.html。
// 資料來源是兩支既有端點，本 phase **沒有新增任何端點**：
//   GET /folders        → 找出 is_inbox 為 true 的那一筆（收件箱）
//   GET /folders/{id}   → 那個資料夾裡的照片摘要（新的在前）
//
// 彈窗鏈（階段甲）：抽屜 → 實體，兩關。**沒有第三關待辦窗**——
// 那要等 Phase 61 把待辦建議寫進 photo 表、Phase 70 才接上去（design5.md §6.2）。
//
// 小工具（el／保護數字單位／getJson／照片卡）與 browse.html 各有一份。
// 這是本專案既有的做法：頁面各自帶自己的小工具（esc() 現在就在
// upload.html／ask.html／camera-desk.html 各有一份）——換來的是
// 「改一頁絕不會弄壞另一頁」。

const view = document.getElementById("view");

// 小工具：造一個元素並填文字。一律用 textContent，不用 innerHTML——
// 照片文字與資料夾名稱是 AI 或使用者填的，裡面若有 < 之類的符號才不會弄壞版面。
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

// 中文排版保護：把「2026 年」這種「數字＋空白＋單位」的空白換成不換行空白
// （\u00a0＝no-break space），免得數字留在行尾、單位被擠到下一行開頭。
// ⚠ 那六個字元一定要照抄成跳脫寫法 \u00a0，不要直接貼一個看起來一樣的空白——
//    肉眼分不出來，但貼成一般空白就完全沒有保護效果了。
function 保護數字單位(text) {
  return String(text).replace(/(\d)\s+(年|月|日|元)/g, "$1\u00a0$2");
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("HTTP " + response.status + "（" + url + "）");
  }
  return await response.json();
}

// 一張照片卡（與 browse.html 的同名函式逐字相同）。
// 「片語」那一段不是分頁邏輯，是排版保護：正式庫裡有一張照片的說明文字
// 剛好含有「待決定分頁的」這幾個字，中文換行會把它拆得很難看，
// 所以那幾個字包進一個不換行的 <span>（Phase 44 加的）。
function 照片卡(photo) {
  const card = el("button", "photo");
  card.type = "button";
  card.dataset.photoId = photo.id;      // event delegation 用得到

  if (photo.thumbnail_url) {
    const image = document.createElement("img");
    image.src = photo.thumbnail_url;      // 例如 /photos/7/thumbnail
    image.alt = photo.text;
    image.addEventListener("error", function () {
      image.replaceWith(el("div", "placeholder", "無縮圖"));
    });
    card.appendChild(image);
  } else {
    // 舊資料沒有原圖：畫灰底占位，不假裝有圖（design1.md §10）
    card.appendChild(el("div", "placeholder", "無縮圖"));
  }
  const caption = el("div", "caption");
  const 說明 = 保護數字單位(photo.text);
  const 片語 = "待決定分頁的";
  const 片語位置 = 說明.indexOf(片語);
  if (片語位置 === -1) {
    caption.textContent = 說明;
  } else {
    caption.appendChild(document.createTextNode(說明.slice(0, 片語位置)));
    caption.appendChild(el("span", "caption-nowrap", 片語));
    caption.appendChild(document.createTextNode(說明.slice(片語位置 + 片語.length)));
  }
  card.appendChild(caption);

  const item = document.createElement("li");
  item.appendChild(card);
  return item;
}

// 彈窗 2【實體】：抽屜窗結束（定案**或**稍後再說）都接著開這一關（design3.md §2.1）。
// 這裡沒有持久化的 AI 建議（suggested: null＝①不顯示）——
// 想要建議就按窗裡的「再建議一個」現算；實體清單開窗前現抓最新的。
// （Phase 61 會把建議寫進 photo 表，Phase 70 才改成讀得到建議＋接第三關待辦窗。）
async function 接著釘實體(photoId) {
  let entities = [];
  try {
    entities = await getJson("/entities");
  } catch (error) {
    // 拿不到清單就當空清單開窗——③自創與④跳過仍然能走；
    // 之後真的釘選失敗會以紅字顯示在窗內，不必在這裡另立錯誤畫面。
  }
  openEntityModal({
    photoId: photoId,
    entities: entities,
    suggested: null,
    onDone: function () {
      location.reload();   // 鏈收工才刷新：定案的照片離開待決定
    }
  });
}

// ---------- 唯一的畫面：收件箱縮圖牆 ----------
async function showPending() {
  const folders = await getJson("/folders");
  const inbox = folders.find(function (f) { return f.is_inbox; });
  const detail = await getJson("/folders/" + inbox.id);

  view.textContent = "";

  if (detail.photos.length === 0) {
    // design5.md §6.2：不要再寫「上傳時按稍後再說才看得到」——
    // 增量五做完之後，**所有**新照片都是分析完成後先來這裡。
    view.appendChild(el("p", "message",
      "目前沒有待決定的照片。分析完成的照片會出現在這裡。"));
    return;
  }
  view.appendChild(el("p", "message",
    "點一張照片完成歸類——歸進資料夾後就定案，不能再改。"));

  const wall = el("ul", "wall");
  detail.photos.forEach(function (photo) {
    wall.appendChild(照片卡(photo));
  });

  // 彈窗 1【抽屜】：下拉排除收件箱（design2.md D7——定案目標必須是真資料夾）；
  //「稍後再說」＝什麼都不做、照片留在這一頁。
  // ①：上傳當下的建議存在照片上（suggested_category，Phase 35 起），
  //    這裡照名字對回資料夾清單即可，不必為了畫①再看一次圖。
  //    沒建議（clamp 成未分類的、以及遷移進來的舊照片）就照舊沒有①。
  const 可選資料夾 = folders.filter(function (f) { return !f.is_inbox; });
  const 照片對照 = {};
  detail.photos.forEach(function (photo) { 照片對照[photo.id] = photo; });

  wall.addEventListener("click", function (event) {
    const card = event.target.closest(".photo");
    if (!card || !card.dataset.photoId) return;
    const photoId = Number(card.dataset.photoId);
    const 建議名稱 = (照片對照[photoId] || {}).suggested_category;
    // find 找不到會回 undefined，彈窗要的是 null（|| null 一併處理沒建議的情況）
    const 建議資料夾 = 建議名稱
      ? 可選資料夾.find(function (f) { return f.name === 建議名稱; }) || null
      : null;

    openFolderModal({
      photoId: photoId,
      folders: 可選資料夾,
      primary: 建議資料夾,
      primaryVerb: "採用",
      // 抽屜窗結束——定案**或**稍後再說——都接著開實體窗；
      // 整頁重讀移到鏈的最尾端（等實體窗收工一次刷新最單純）。
      onAssigned: function () { 接著釘實體(photoId); },
      onClosed: function () { 接著釘實體(photoId); }
    });
  });

  view.appendChild(wall);
}

// ---------- 進入頁面 ----------
(async function start() {
  try {
    await showPending();
  } catch (error) {
    view.textContent = "";
    view.appendChild(el("p", "message",
      "目前無法載入資料。請確認服務已啟動後重新整理頁面。"));
  }
})();
</script>

</body>
</html>
```

### 4.3 三處與 `browse.html` **刻意不同**的地方（自己核對一遍）

- [ ] **① 沒有 `renderTabs(...)`**：新頁只有一個畫面，不需要頁籤列。
      連帶把 `showPending()` 裡那一行 `const tasks = await getJson("/tasks");`
      也拿掉了——它原本**只是為了頁籤上的「待辦（M）」數字**而打的，新頁沒有那個數字。
      （少打一支 API，開頁快一點點；但真正的理由是「沒有用到的資料就不要抓」。）

- [ ] **② 空狀態文案改了**（design5.md §6.2 明文）：

```text
舊（browse.html）：目前沒有待決定的照片。上傳時按「稍後再說」的照片會出現在這裡。
新（pending.html）：目前沒有待決定的照片。分析完成的照片會出現在這裡。
```

  **為什麼要改**：舊句子把「按稍後再說」寫成唯一來源，那是現在（上傳當下就開彈窗鏈）的實況；
  但增量五做完之後，上傳只會回「已收下」，**所有**新照片都是 AI 分析完才進來這裡。
  舊句子到那時候會變成騙人的說明。
  ⚠ **階段甲的當下，這句話其實有一點「超前」**——因為上傳鏈這時還在，
  照片仍然是「你按了稍後再說」才留在這裡的。這是刻意的：
  文案先寫成最終狀態，免得階段丙還要再回來改一次（也免得忘了改）。

- [ ] **③ 只掛兩支彈窗檔**：`folder_modal.js`、`entity_modal.js`。
      **不要**掛 `photo_detail_modal.js`（那是唯讀詳情窗，待決定牆點下去要開的是歸類窗）、
      **不要**掛 `task_modal.js`（階段甲不開第三關）、
      **不要**掛 `classify_chain.js`（那是上傳頁與鏡頭桌面頁用的三關鏈組裝器，
      本頁自己用 `openFolderModal` ＋ `openEntityModal` 串兩關就好，
      與現在 `browse.html` 待決定分頁的做法完全相同）。

### 4.4 讓新檔生效

- [ ] 靜態檔是**每次請求現讀**的，所以存檔後直接重新整理瀏覽器就看得到，
      **不需要**重啟容器、也不需要等 uvicorn 重載。真的沒變就按 `Cmd`＋`Shift`＋`R` 強制重整
      （先排除瀏覽器快取）。

- [ ] 但要注意**你現在跑的是哪一種模式**：

```bash
docker compose ps --no-trunc
```

  - `COMMAND` 欄**有** `--reload` ＝開發模式，`./app` 是 bind-mount（掛進去的），
    你剛存的 `pending.html` 容器**看得到**。✅
  - `COMMAND` 欄**沒有** `--reload` ＝常駐模式，程式在**映像裡**，
    容器**看不到**你新增的檔案 → 開網址會 404。
    要嘛切到開發模式，要嘛 `docker compose -f compose.yaml up -d --build` 重建映像。

  （`--no-trunc` 不能省：不加的話 `COMMAND` 只印開頭二十幾個字，
  `--reload` 剛好在整條長指令的最後面，會被截掉。）

### 4.5 瀏覽器實操驗收（本 phase 的主要驗收方式）

本專案的前端 phase **不新增自動化測試**（Phase 14／23／24／31／33／39 皆然），
改用瀏覽器逐項實操。可以純手動，也可以用 **Playwright MCP**
（常用：`browser_navigate`、`browser_snapshot`、`browser_click`、
`browser_select_option`、`browser_console_messages`；
全站沒有 `alert`／`confirm`，所以完全用不到 `browser_handle_dialog`）。

- [ ] **1. 新頁開得起來**：開 `https://127.0.0.1:8000/ui/pending.html`
      → 看到頁首、標題「待決定」、說明段落，以及縮圖牆（或空狀態那一句）。
- [ ] **2. 內容與舊分頁一模一樣**：另開一個分頁到 `https://127.0.0.1:8000/ui/browse.html`
      （＝舊的待決定分頁），兩邊**並排比對**：張數相同、每一格的縮圖與文字相同、順序相同（新的在前）。
- [ ] **3. 點一張照片會開歸類窗**：彈窗跳出，看得到②下拉、③自建、④「稍後再說」。
      有 `suggested_category` 的照片還會多一個①「採用「◯◯」」。
- [ ] **4. 強制決定仍然成立**（design2.md D1）：按 `Esc`、點彈窗外的暗色區
      → **都不會關**。只有四個按鈕能離開。
- [ ] **5. 走④「稍後再說」→ 接著跳出實體窗**：不是直接回到牆上。
      實體窗按「不釘，繼續」→ 整頁重新載入、照片**還在**待決定牆上（因為沒有歸類）。
- [ ] **6. 走②改選一個真資料夾 → 定案**：彈窗關閉 → 實體窗跳出 → 按「不釘，繼續」
      → 整頁重新載入 → **那張照片已經不在牆上了**。
- [ ] **7. 定案不可逆（後端擋）**：到 `https://127.0.0.1:8000/ui/browse.html?tab=folders`
      點進剛才那個資料夾 → 點那張照片 → 跳出來的是**唯讀詳情窗**（沒有任何改資料夾的按鈕）。
- [ ] **8. 空狀態**：把牆上的照片全部歸完（或本來就是空的）→ 重新整理
      → 看到「目前沒有待決定的照片。分析完成的照片會出現在這裡。」
- [ ] **9. 資料載不進來時的錯誤畫面**：開發者工具 → Network 分頁 → 對 `/folders` 那一筆
      右鍵「Block request URL」→ 重新整理 → 頁首與標題照常、`#view` 顯示
      「目前無法載入資料。請確認服務已啟動後重新整理頁面。」
      → 驗完移除 block 規則、再重新整理一次確認恢復。
      （**不要**用「停掉 app」來驗這一項——app 停了連這一頁的 HTML 都載不進來，
      瀏覽器只會顯示自己的連線錯誤頁，頁內那句話永遠不會出現；2026-08-25 核對時修正。
      也**不要**用 `docker compose down -v`——那會刪掉正式庫的 volume。）
- [ ] **10. Console 乾淨**：整趟操作下來，開發者工具 Console 沒有紅色錯誤
      （favicon 的 404 是既有的預期訊息，不算）。
- [ ] **11. 舊的待決定分頁完全沒被動到**：`https://127.0.0.1:8000/ui/browse.html`
      三個分頁（待決定／資料夾／待辦）全部照舊可用。
- [ ] **12. 上傳頁沒被動到**：`https://127.0.0.1:8000/ui/upload.html` 上傳一張
      → 三關彈窗鏈照跑（抽屜 → 實體 →〔有待辦建議才〕待辦）。
      這一項證明本 phase 真的沒碰共用的彈窗檔。

---

## 5. ASCII 圖：照片從哪裡來、到哪裡去

```text
  照片怎麼進到「待決定」（＝收件箱／未分類）
  ─────────────────────────────────────────────────────────────────────
   階段甲的**現況**（上傳仍然是同步的 201，彈窗當場就開）：

     /ui/upload.html  上傳一張
            │
            ▼  POST /photos → AI 看圖（本機 1〜5 分鐘）→ 201
     抽屜窗當場跳出 ──┬── 選了資料夾 ──► 定案，直接進資料夾（**不會**來待決定）
                      └── 按「稍後再說」──► 留在收件箱 ──► 就是這一頁看到的東西

   階段乙／丙做完以後（design5 的目標，Phase 62〜69）：

     上傳／手機快門 ──► HTTP 立刻回 202「收下了」──► 背景 worker 慢慢看圖
                                                          │
                                    分析成功 ──────────────┘
                                        ▼
                                  **所有**新照片都先進收件箱
                                        ▼
                                    這一頁（唯一的歸類入口）


  這一頁自己在做什麼
  ─────────────────────────────────────────────────────────────────────

      開 /ui/pending.html
            │
            │  ① GET /folders          → 從清單裡找 is_inbox === true 那一筆
            │  ② GET /folders/{那個 id} → { folder, photos[] }（新的在前）
            ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  待決定                                                       │
   │  點一張照片完成歸類——歸進資料夾後就定案，不能再改。           │
   │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                 │
   │  │ [縮圖] │ │ [縮圖] │ │▒▒▒▒▒▒▒▒│ │ [縮圖] │  ← 第三格是舊資料 │
   │  │        │ │        │ │ 無縮圖 │ │        │    沒有縮圖檔     │
   │  ├────────┤ ├────────┤ ├────────┤ ├────────┤                 │
   │  │說明兩行│ │說明兩行│ │說明兩行│ │說明兩行│                 │
   │  └────────┘ └────────┘ └────────┘ └────────┘                 │
   │      ↑ 整面牆只掛一個 click 監聽（event delegation）           │
   └──────────────────────────────────────────────────────────────┘
            │ 點任一張
            ▼
   ┌─── 彈窗 1【抽屜】folder_modal.js ────────────────────────────┐
   │  要把這張照片放到哪個資料夾？                                │
   │   ① 採用「收據」      ← 只有 suggested_category 對得上時才有  │
   │   ② [ 飲食 ▾ ] 歸到這個資料夾    ← 下拉**排除**收件箱         │
   │   ③ [名稱__] [說明__] 建立並歸類                             │
   │   ④ 稍後再說          ← 什麼 API 都不打，照片留在這一頁       │
   │  ⚠ 沒有 ×、不吃 Esc、點暗色區也不關（design2.md D1 強制決定） │
   └──────────────────────────────────────────────────────────────┘
        │ ①②③ 成功（PATCH 200）           │ ④
        │  照片已定案，離開待決定           │  照片還在待決定
        └──────────────┬────────────────────┘
                       ▼   兩條路都要繼續（釘實體與歸不歸類無關）
   ┌─── 彈窗 2【實體】entity_modal.js ────────────────────────────┐
   │  要把這張照片釘上實體嗎？（可釘多個）                        │
   │   ①（階段甲永遠不顯示：suggested 傳 null）                   │
   │   ② [ 我的 MacBook ▾ ] 釘上這個實體                          │
   │   ③ [名稱__] [說明__] 建立並釘上                             │
   │   ④ 再建議一個 ／ 不釘，繼續                                 │
   └──────────────────────────────────────────────────────────────┘
                       │ 按「不釘，繼續」／「完成，繼續」
                       ▼
                 location.reload()
                 → 定案的照片從牆上消失；沒定案的還在

   ✗ 階段甲**沒有**彈窗 3【待辦】task_modal.js。
     那要等 Phase 61 把待辦建議寫進 photo 表、Phase 70 才接上（design5.md §6.2）。


  Phase 52 之後的暫時狀態（兩份，刻意的）
  ─────────────────────────────────────────────────────────────────────
     /ui/pending.html    ← ★ 本 phase 新建，內容與右邊完全相同
     /ui/browse.html     ← 舊的待決定分頁，**還留著**（Phase 55 才刪）

     這樣才有「已知是好的」可以並排比對。
     Phase 53 把頂欄接上 pending.html；Phase 55 把 browse 這一份整段刪掉。
```

---

## 6. 驗收清單

- [ ] `app/static/pending.html` 已建立，內容與 §4.2 的完整檔案一致。

- [ ] **只動了一個檔**（新建的檔案是「未追蹤」，`git diff` 看不到它，所以要用 `git status`）：

```bash
cd /Users/linjunting/personalDocAI
git status --short -- app
```

  預期：**恰好一行** `?? app/static/pending.html`。
  出現任何 ` M app/static/…` 都代表手滑改到既有檔案（`browse.html`／`folder_modal.js`
  分別是 Phase 55／54 的事，本 phase 不准動）。

- [ ] **新頁送得出來、而且不是新增端點**：

```bash
curl -k -s -o /dev/null -w "%{http_code}\n" https://127.0.0.1:8000/ui/pending.html
```

  預期：`200`。
  （能 200 是因為 `app/main.py` 那一行 `app.mount("/ui", StaticFiles(...))`
  把整個 `app/static/` 資料夾當靜態檔送出去——多一個 `.html` 檔就多一個網址，
  但它**不是** API 端點。）

- [ ] **端點數仍然是 20**（這一條就是「沒有新增端點」的客觀證明）：

```bash
curl -k -s https://127.0.0.1:8000/openapi.json \
  | python3 -c "import json,sys; p=json.load(sys.stdin)['paths']; print(sum(len(v) for v in p.values()))"
```

  預期：`20`。
  （`paths` 是「路徑 → 方法」的兩層字典，所以要把每個路徑底下的方法數加起來，
  不能直接數 `paths` 有幾個 key——`/photos` 同時有 POST 與其他方法時會少算。
  這與 `tests/integration/test_ask_three_paths.py::test_端點數不變` 的算法一致。）

- [ ] **`pytest -q` 顆數完全不變**：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**405 passed ＋ 0 skipped**（本 phase 純前端、零新增測試、零產品 Python 變更）。

- [ ] `tests/integration/test_design4_error_paths.py` 那幾顆掃 `browse.html` 原始碼的測試仍綠
      （包含在上面那 405 裡；本 phase 沒動 `browse.html`，本來就該綠）。

- [ ] **沒有原生對話框、沒有外部前端函式庫**：

```bash
grep -rnE "alert\(|confirm\(|prompt\(" app/static/pending.html || echo "OK：沒有原生對話框"
grep -rniE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/pending.html || echo "OK：沒有外部函式庫"
```

  預期：兩行都印出 `OK：…`。

- [ ] **只掛該掛的兩支彈窗檔**：

```bash
grep -n "script src" app/static/pending.html
```

  預期恰好兩行：`/ui/folder_modal.js`、`/ui/entity_modal.js`。
  **不該**出現 `photo_detail_modal.js`、`task_modal.js`、`classify_chain.js`、`ai_switch.js`。

- [ ] **空狀態文案照 design5 §6.2 改過了**：

```bash
grep -n "分析完成的照片會出現在這裡" app/static/pending.html
grep -n "上傳時按「稍後再說」" app/static/pending.html || echo "OK：舊句子沒有被抄進來"
```

  預期：第一行找得到、第二行印出 `OK：…`。
  （第二個 grep 的樣式刻意帶引號「稍後再說」——舊句子是「上傳時按「稍後再說」的照片…」；
  新檔空狀態那段註解引用了 design5 §6.2 原文「上傳時按稍後再說才看得到」（不帶引號），
  用短樣式 `上傳時按` 會誤中那行註解、永遠印不出 OK。2026-08-25 核對時修正。）

- [ ] §4.5 的 12 項瀏覽器實操逐項打勾、Console 乾淨。

- [ ] **舊路徑完全沒壞**：`/ui/browse.html`（三個分頁）、`/ui/upload.html`（三關鏈）
      、`/ui/ask.html` 都照舊可用。

---

## 7. 常見陷阱

1. **開 `https://127.0.0.1:8000/ui/pending.html` 得到 404**，檔案明明存在。
   八成是**常駐模式**（程式打包在映像裡，容器看不到你新增的檔）。
   先 `docker compose ps --no-trunc` 看 `COMMAND` 欄有沒有 `--reload`：
   沒有就切到開發模式（`docker compose -f compose.yaml stop app`
   → `docker compose -f compose.yaml -f compose.dev.yaml up -d`），
   或 `docker compose -f compose.yaml up -d --build` 重建映像。

2. **用 `http://` 開**（少一個 s）：整個連不上、`curl` 回 `000`。
   容器的啟動指令固定帶憑證（無線鏡頭需要「安全來源」手機才給鏡頭權限），
   一個行程沒辦法同時聽 HTTP 與 HTTPS。網址一律 `https://`。

3. **順手把 `browse.html` 的待決定分頁也刪了**：不要。那是 Phase 55。
   本 phase 做完必須是「兩邊都能開、行為一樣」，這是刻意留的比對基準。
   `git status --short -- app` 只准有一行。

4. **順手把 `task_modal.js` 也掛上去、想說「三關比較完整」**：不要。
   階段甲讀不到待辦建議（那三個欄位 Phase 56 才建、Phase 61 才寫），
   掛上去只會開出一個標題空白的窗，比不開更糟。
   design5 §6.2 寫明階段甲可暫維持兩關——本計畫即取此路，Phase 70 才改三關。

5. **把 `照片卡()` 裡的「片語」那段當成分頁邏輯刪掉**：那是排版保護（見 §4.1 最後一段），
   不是分頁邏輯。刪掉不會壞掉，但正式庫裡那張照片的說明會換行換得很難看，
   而且與 `browse.html` 行為不一致，「搬」就不成立了。

6. **把 `renderTabs` 也抄過來、只是不呼叫**：不要留沒人用的函式。
   本專案的規矩是不留過渡產物；沒人呼叫的程式碼下一個人會不知道能不能刪。

7. **以為「稍後再說」會直接關掉整條鏈**：不會。
   `onClosed` 與 `onAssigned` **兩條路都會接著開實體窗**（`classify_chain.js` 也是這樣寫的）——
   釘實體跟歸不歸類是兩件獨立的事。看到實體窗跳出來不是 bug。

8. **實體窗的①永遠不出現，以為壞了**：階段甲刻意傳 `suggested: null`。
   待決定這條路沒有持久化的 AI 實體建議，想要建議就按窗裡的「再建議一個」現算
   （那會真的呼叫一次 AI；本機模型會等一下）。Phase 61＋70 之後才會有①。

9. **`inbox` 是 `undefined` 導致整頁顯示「目前無法載入資料」**：
   代表 `GET /folders` 裡沒有 `is_inbox` 為 `true` 的那一筆。
   正常情況不會發生（六筆種子的第一筆就是收件箱，資料庫還有 partial unique index
   保證全系統至多一個）。真的遇到就是資料庫被重建過而種子沒進去，
   用 `psql -d PersonalDocAI -c "SELECT id, name, is_inbox FROM folder ORDER BY id;"` 確認。
   ⚠ **不要**用 `db/schema.sql` 去「修」正式庫——那個檔開頭是 `DROP TABLE IF EXISTS`，
   跑下去照片全沒了。正式庫改結構一律走可重跑的遷移腳本。

10. **兩個分頁並排比對時看到張數不一樣**：先確認**不是**你在其中一邊剛歸類完
    （另一邊還沒重新整理）。兩邊都按 `Cmd`＋`Shift`＋`R` 之後再比。

11. **本機模型很慢，以為畫面當掉**：實體窗的「再建議一個」會真的呼叫一次 AI，
    本機 gemma4 要等數十秒到數分鐘。按鈕在等待期間是 disabled（游標會變成「進行中」），
    那是正常的。想快就先到上傳頁把頁首的「AI 模型」開關撥到「雲端」
    （那顆開關的狀態存在伺服器，全站共用，在哪一頁撥都一樣）。
