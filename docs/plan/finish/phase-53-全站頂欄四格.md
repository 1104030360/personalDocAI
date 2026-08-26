# Phase 53：全站頂欄四格（加上「待決定（N）」）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。

> 🎯 **一句話目標：** 把五個頁面的頁首導覽從三格改成四格——
> `上傳照片 ｜ 待決定（N）｜ 瀏覽資料夾 ｜ 問問題`，
> 其中 `N` 是待決定裡有幾張照片。手機取景頁 `camera-phone.html` **刻意不放**。
> 順便加一支很便宜的**前端契約測試**，把「五頁長得一樣」這件事釘死。

**為什麼要做這個：**
Phase 52 把 `/ui/pending.html` 做出來了，但**沒有任何地方點得到它**——
你得自己在網址列打字。這一步就是把入口接上去。
而且 design5.md D1 要的不只是「有連結」，是把待決定**升到與上傳、瀏覽、問問題同一層**，
並且把「還有幾張沒處理」直接寫在導覽列上（`N`），
讓人不必點進去就知道有沒有事情要做。

**為什麼 N 現在用 `GET /folders` 算，之後又要改掉：**
階段丙（Phase 64）才會有一支專門的 `GET /ingest-jobs`，
它會一次帶回「進行中的分析任務」與 `pending_count`（待決定張數）兩件事，
由全站的進度面板每 2 秒輪詢一次、順手更新 N。
但那支端點現在還不存在。design5 §6.1 明文寫著：
**階段甲的 N 用既有 `GET /folders` 收件箱的 `photo_count` 即可。**
所以本 phase 用最笨也最穩的方式：每頁載入時打一次 `GET /folders`，
把 `is_inbox` 那一筆的 `photo_count` 填進去。
**Phase 67 會把這五段小程式整組刪掉，改由 `progress_panel.js` 統一更新。**
（這不是「留過渡產物」——它有明確的死期，而且死期寫在這裡與 Phase 67 兩處。
§4.8 那顆斷言「五份片段存在」的測試也一起有交代：Phase 67 會把它**原地換成**
`test_五頁的計數片段已交棒給進度面板`——是**改寫、不是刪掉**，那個測試檔的顆數不變。）

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 頁首／頂欄（site-header） | 每一頁最上面那一條：左邊是「PersonalDocAI」，右邊是導覽連結（有些頁還有「AI 模型」開關）。樣式在 `app/static/style.css` 的 `.site-header` 區塊，本 phase **不改 CSS** |
| `aria-current="page"` | 一個無障礙屬性，意思是「這一格就是你現在所在的頁」。它同時有兩個作用：螢幕報讀軟體會唸出來；`style.css` 也用 `.site-nav a[aria-current="page"]` 這條規則把當頁那一格畫成深色＋底線。所以**它不是裝飾，是狀態**——標錯了畫面就會標錯格子 |
| 全形括號 `（）` | 中文用的括號，與英文的 `()` 是不同字元。契約規定「待決定（N）」用**全形**，一個字都不能改（否則五頁會長得不一樣） |
| IIFE（立即執行函式） | 寫成 `(function () { … })();` 的一段程式：定義完馬上執行，而且裡面宣告的變數不會外流到全域。本 phase 的計數片段用它包起來，才不會跟各頁自己的變數撞名 |
| 前端契約測試 | 這個專案的前端沒有自動化測試框架（不裝 Jest、不寫 Playwright 自動化）。但「五頁的頁首要一致」這種事最容易在改了其中一頁之後悄悄走鐘，所以用**最便宜的方式**釘住：寫一顆 pytest，直接把 HTML 檔當文字讀進來、斷言某幾個字串在不在。既有的 `tests/integration/test_design4_error_paths.py` 就有好幾顆這種測試 |

---

## 1. 對應 design5.md 章節

- **D1**（待決定升成頂欄的一格，放在「上傳照片」右邊）
- **§0 階段甲**（「頂欄加上『待決定（N）』」那一行）
- **§6.1**（整節：頂欄長相、`aria-current` 標當頁、
  **階段甲的 N 用既有 `GET /folders` 收件箱的 `photo_count`**、
  階段丙改由全站 JS 輪詢 `GET /ingest-jobs`、
  「不要四個 HTML 各寫一套 `setInterval`」——design5 原文寫「四個」，
  本計畫含 `camera-desk.html` 共**五頁**（§3 的名單），引文照原文抄）
- **§6.5**（`camera-phone.html` 是手機取景頁；design5 沒有要它掛頂欄）
- **§9 測試策略**（「前端契約：頂欄含『待決定』……可用字串釘，比照現有 `片語` 測試」）
- **§11 會動到的檔**（第 4 列「各頁 `site-header`｜甲／丙｜四格導覽；丙再掛進度 JS」）
- **§12 階段甲驗收第 1 條**（頂欄為「上傳照片｜待決定（N）｜瀏覽資料夾｜問問題」）

---

## 2. 前置條件

- **Phase 52 已完成**：`app/static/pending.html` 存在且開得起來。
  沒有它，頂欄那一格會連到 404。確認：

```bash
cd /Users/linjunting/personalDocAI
ls -l app/static/pending.html
curl -k -s -o /dev/null -w "%{http_code}\n" https://127.0.0.1:8000/ui/pending.html
```

  預期：檔案存在、`200`。

- 開工基線（Phase 52 沒有新增測試，所以顆數與增量四結束時相同）：

```bash
source .venv/bin/activate
pytest -q
```

  預期：**405 passed ＋ 0 skipped**。
  （⚠ 絕對不要同時跑兩份 pytest。）

- 服務起來、而且是**開發模式**（改 HTML 存檔就生效）：

```bash
docker compose ps --no-trunc
```

  `COMMAND` 欄要看得到 `--reload`。不是的話：

```bash
docker compose -f compose.yaml stop app
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

---

## 3. 範圍

### 做

- 改**五個** HTML 檔的 `<header class="site-header">` 區塊：
  `upload.html`、`pending.html`、`browse.html`、`ask.html`、`camera-desk.html`。
- 每一頁在 `</header>` 正下方，加上**一模一樣**的計數片段
  （`<script>` 到 `</script>` 共 25 行，見 §4.2）。
- 新增測試檔 `tests/integration/test_nav_header.py`（**7 顆**）。
- 瀏覽器實操確認五頁的頂欄真的一致、當頁那一格有畫底線。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改 `app/static/style.css` | `.site-nav` 是 `display: flex; gap: var(--sp-4);`，第四格自己就會排好。窄螢幕的 `@media (max-width: 32rem)` 也已經把 `.site-header` 改成上下排。**一行 CSS 都不用動**——真的排壞了才回來處理，不要先改 |
| 在 `camera-phone.html`（手機取景頁）加頂欄 | `style.css` 第 815 行對這一頁的註解已經寫得很白：「這一頁沒有站台頁首與導覽——**它只有一個用途，多一個連結都是誤觸來源**」。那是手機直握、單手按快門的全螢幕取景畫面（`height: 100dvh; overflow: hidden`），版面高度是算好的；插一條頁首進去會把取景區壓扁，而且拍照拍到一半誤觸連結就整個配對斷掉。design5 §6.5 給這一頁的職責只有「202 後可再拍＋窄條進度」 |
| 在 `browse.html`／`pending.html` 補上「AI 模型」開關 | 那兩頁現在就沒有。⚠ **要誠實揭露一個落差**：design5 §6.1 的頂欄示意圖畫了 `[AI 本機｜雲端]`、還寫「每一頁的 header 都長這樣」，但 §3「做」的清單與 §11 的檔案表都**沒有把這件事指派給任何 phase**。開關的狀態存在**伺服器**（`config.AI_BACKEND`），在上傳頁撥了全站都跟著，功能上少放也不缺。所以本 phase 維持現況（上傳／問問題／鏡頭桌面三頁有、瀏覽／待決定兩頁沒有）、**不默默補**——要不要補齊五頁是**未指派的產品決策**，★G1（Phase 55 結尾）驗收時當面請產品負責人裁決；他沒說要補就維持現況 |
| 為了「統一」把 `browse.html`／`pending.html` 的 `<nav>` 包進 `<div class="site-header-right">` | 那個 `<div>` 存在的唯一理由是「導覽列與 AI 開關要並排」。沒有開關的頁包一層空 wrapper 只是多一層 DOM，看不出差別。**要統一的是那四格 `<a>`，不是外面的殼** |
| 寫 `setInterval` 每幾秒更新 N | design5 §6.1 明文：輪詢是**階段丙**的事，而且要「全站唯一一份 JS」。階段甲只在頁面載入時算一次就好 |
| 新開一支 `app/static/nav_count.js` 共用檔 | 增量五契約只認可兩個新前端檔（`pending.html`、`progress_panel.js`）。多開一支沒登記的共用檔，Phase 67 的實作者不會知道要刪它，就真的變成孤兒了。五份一模一樣的 25 行是刻意的取捨——它 grep 得到、刪得乾淨 |
| 把 `GET /` 的轉址從上傳頁改成待決定頁 | `app/main.py` 那一行是既有契約（2026-08-20 使用者指示），design5 沒有要改。本 phase **零 Python 變更** |
| 新增端點 | 本 phase 端點恰 **20**，一支不多（§6 有一顆測試釘住） |

---

## 4. 實作步驟

### 4.1 五格頁首的最終長相（先看懂差在哪）

四格的**文字**與**網址**是契約，一個字都不能改：

| 順序 | 文字 | 網址 |
|---|---|---|
| 1 | `上傳照片` | `/ui/upload.html` |
| 2 | `待決定（N）` | `/ui/pending.html` |
| 3 | `瀏覽資料夾` | `/ui/browse.html` |
| 4 | `問問題` | `/ui/ask.html` |

`N` 那一格寫成這個固定形狀（**注意是全形括號**，而且數字包在一個 `<span>` 裡）：

```html
<a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
```

**為什麼要包一個 `<span>` 而不是整段字重寫**：
JS 只改那個 `<span>` 的 `textContent`，永遠碰不到「待決定」這三個字與括號。
如果寫成 `連結.textContent = "待決定（" + n + "）"`，
哪天有人手滑寫錯就會把整格字弄不見（而且測試也比較難釘）。

**`…` 是刻意的初始值**：頁面剛畫出來、`GET /folders` 還沒回來時顯示 `待決定（…）`。
**不要**預設寫 `0`——那會在載入的瞬間顯示一個「猜的」數字，
而且服務掛掉時會一直停在錯的 `0`，比停在 `…` 更誤導。

五頁的差別只有兩點：

| 檔案 | `aria-current="page"` 標在哪一格 | 頁首有沒有「AI 模型」開關 |
|---|---|---|
| `upload.html` | 上傳照片 | 有（`site-header-right` 包住 nav ＋ 開關） |
| `pending.html` | 待決定 | 沒有（nav 直接放在 header 裡） |
| `browse.html` | 瀏覽資料夾 | 沒有 |
| `ask.html` | 問問題 | 有 |
| `camera-desk.html` | **都不標**（鏡頭桌面頁不是這四格之一，現況就是不標） | 有 |

### 4.2 五頁共用的計數片段（一字不差地貼五次）

- [ ] 這一段貼在**每一頁的 `</header>` 正下方**（五頁都一樣，逐字相同）：

```html
<script>
// 頂欄「待決定（N）」的 N（增量五 Phase 53；design5.md §6.1）。
// 階段甲還沒有 GET /ingest-jobs，所以直接問既有的 GET /folders，
// 取 is_inbox 那一筆的 photo_count——待決定就是收件箱，數字天生一致。
//
// ⚠ 這一段在五個 HTML 檔裡各有一份、逐字相同。
//    階段丙 Phase 67 會由 progress_panel.js 一次接手（連同 2 秒輪詢），
//    屆時把五份一起刪掉。要改就五份一起改，不要只改一份。
//
// 用 IIFE 包起來：裡面的變數不會外流，不會跟各頁自己的 response／folders 撞名。
(function () {
  const 格子 = document.getElementById("nav-pending-count");
  if (!格子) return;                       // 沒有頂欄的頁面（例如手機取景頁）載入也不做事
  fetch("/folders").then(function (response) {
    if (!response.ok) return null;         // 4xx／5xx：維持「…」，不要顯示一個猜的 0
    return response.json();
  }).then(function (folders) {
    if (!folders) return;
    const inbox = folders.find(function (f) { return f.is_inbox; });
    if (inbox) 格子.textContent = String(inbox.photo_count);
  }).catch(function (error) {
    // 服務沒起來：讓它維持「…」。頁面主體自己會顯示錯誤，這裡不要再吵一次。
  });
})();
</script>
```

  **為什麼用 `.then()` 不用 `async/await`**：這一段要貼在 `<header>` 後面、頁面中段，
  用 `async function` 包還要多一層 IIFE 才不會污染全域；`.then()` 版本一層就夠、也不需要
  `await`。行為完全相同（都是「先把頁面畫完，資料回來再填數字」）。

### 4.3 改 `app/static/upload.html`

- [ ] 把第 11〜34 行整個 `<header>` 換成下面這一段
      （**只有 `<nav>` 裡多了一格；AI 開關那一整塊註解與 HTML 一字不動**）：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <div class="site-header-right">
    <nav class="site-nav" aria-label="主要導覽">
      <a href="/ui/upload.html" aria-current="page">上傳照片</a>
      <a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
      <a href="/ui/browse.html">瀏覽資料夾</a>
      <a href="/ui/ask.html">問問題</a>
    </nav>
    <!-- AI 後端開關（2026-08-22）：撥到「雲端」＝看圖與問答都改走 Ollama Cloud。
         狀態存在伺服器（PUT /settings/ai-backend），全站同一個開關狀態
         （相機頁的拍照走同一個 get_vlm，所以也跟著）；
         行為在共用檔 /ui/ai_switch.js（問問題頁放的是同一顆）。 -->
    <div class="ai-switch">
      <span id="ai-switch-label" class="ai-switch-label">AI 模型</span>
      <button type="button" id="ai-toggle" class="ai-toggle" role="switch"
              aria-checked="false" aria-labelledby="ai-switch-label"
              title="切換 AI 走本機 Ollama 或 Ollama Cloud（看圖與問答都跟著）">
        <span class="ai-side" data-side="local">本機</span>
        <span class="ai-side" data-side="cloud">雲端</span>
      </button>
      <span id="ai-switch-msg" class="ai-switch-msg" aria-live="polite"></span>
    </div>
  </div>
</header>
```

- [ ] 在 `</header>` 正下方貼上 §4.2 的計數片段。

### 4.4 改 `app/static/pending.html`（Phase 52 剛建的那一份）

- [ ] 把 Phase 52 寫的那個「先照現況抄三格」的 `<header>`（含上面那段 HTML 註解）
      整個換成：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <nav class="site-nav" aria-label="主要導覽">
    <a href="/ui/upload.html">上傳照片</a>
    <a href="/ui/pending.html" aria-current="page">待決定（<span id="nav-pending-count">…</span>）</a>
    <a href="/ui/browse.html">瀏覽資料夾</a>
    <a href="/ui/ask.html">問問題</a>
  </nav>
</header>
```

- [ ] 在 `</header>` 正下方貼上 §4.2 的計數片段。

> **這一頁的 N 會被算兩次，那是正常的**：頁首片段打一次 `GET /folders`，
> 頁面主體的 `showPending()` 也打一次。兩支都是本機的唯讀查詢，多一次沒有感覺；
> 硬要共用就得把頁首片段寫成「與各頁互相依賴」的形狀，
> 那樣 Phase 67 要抽掉它時反而會拆到頁面主體。**五份一模一樣、互不依賴**才刪得乾淨。

### 4.5 改 `app/static/browse.html`

- [ ] 把第 11〜18 行整個 `<header>` 換成：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <nav class="site-nav" aria-label="主要導覽">
    <a href="/ui/upload.html">上傳照片</a>
    <a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
    <a href="/ui/browse.html" aria-current="page">瀏覽資料夾</a>
    <a href="/ui/ask.html">問問題</a>
  </nav>
</header>
```

- [ ] 在 `</header>` 正下方貼上 §4.2 的計數片段。

> ⚠ **這一頁本 phase 只准改頁首**。裡面那個「待決定（N）｜資料夾｜待辦」的
> **分頁列**（`renderTabs()` 畫的那一排）**先留著不動**——刪它是 Phase 55。
> 所以本 phase 做完，`browse.html` 上會**同時**有頂欄的「待決定（N）」與分頁列的
> 「待決定（N）」兩個入口，看起來有點重複。**那是刻意的暫時狀態**，Phase 55 收掉。

### 4.6 改 `app/static/ask.html`

- [ ] 把第 11〜33 行整個 `<header>` 換成（AI 開關那一塊一字不動）：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <div class="site-header-right">
    <nav class="site-nav" aria-label="主要導覽">
      <a href="/ui/upload.html">上傳照片</a>
      <a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
      <a href="/ui/browse.html">瀏覽資料夾</a>
      <a href="/ui/ask.html" aria-current="page">問問題</a>
    </nav>
    <!-- AI 後端開關（2026-08-22）：與上傳頁是同一顆開關（同一個伺服器狀態）——
         撥到「雲端」＝這一頁的判斷查法與產生回答都改走 Ollama Cloud。
         行為在共用檔 /ui/ai_switch.js。 -->
    <div class="ai-switch">
      <span id="ai-switch-label" class="ai-switch-label">AI 模型</span>
      <button type="button" id="ai-toggle" class="ai-toggle" role="switch"
              aria-checked="false" aria-labelledby="ai-switch-label"
              title="切換 AI 走本機 Ollama 或 Ollama Cloud（看圖與問答都跟著）">
        <span class="ai-side" data-side="local">本機</span>
        <span class="ai-side" data-side="cloud">雲端</span>
      </button>
      <span id="ai-switch-msg" class="ai-switch-msg" aria-live="polite"></span>
    </div>
  </div>
</header>
```

- [ ] 在 `</header>` 正下方貼上 §4.2 的計數片段。

### 4.7 改 `app/static/camera-desk.html`

- [ ] 把第 11〜34 行整個 `<header>` 換成（**四格都不標 `aria-current`**，AI 開關一字不動）：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <div class="site-header-right">
    <nav class="site-nav" aria-label="主要導覽">
      <a href="/ui/upload.html">上傳照片</a>
      <a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
      <a href="/ui/browse.html">瀏覽資料夾</a>
      <a href="/ui/ask.html">問問題</a>
    </nav>
    <!-- AI 後端開關（2026-08-22）：與上傳頁、問問題頁是同一顆（同一個伺服器狀態）。
         手機拍的照片走 POST /camera/{token}/photos → _ingest_image() → get_vlm，
         跟一般上傳共用同一個注入點，所以這裡撥了、手機拍的看圖就跟著切。
         行為在共用檔 /ui/ai_switch.js。 -->
    <div class="ai-switch">
      <span id="ai-switch-label" class="ai-switch-label">AI 模型</span>
      <button type="button" id="ai-toggle" class="ai-toggle" role="switch"
              aria-checked="false" aria-labelledby="ai-switch-label"
              title="切換 AI 走本機 Ollama 或 Ollama Cloud（看圖與問答都跟著）">
        <span class="ai-side" data-side="local">本機</span>
        <span class="ai-side" data-side="cloud">雲端</span>
      </button>
      <span id="ai-switch-msg" class="ai-switch-msg" aria-live="polite"></span>
    </div>
  </div>
</header>
```

- [ ] 在 `</header>` 正下方貼上 §4.2 的計數片段。

> **為什麼鏡頭桌面頁不標當頁**：那四格指的是四個主要頁面，鏡頭桌面頁不是其中之一
> （它是從上傳頁的「用手機拍」連結進去的支線，頁面裡自己就有一條「← 回上傳頁」）。
> 現況本來就沒有標，本 phase 不改變這件事。

### 4.8 新增前端契約測試 `tests/integration/test_nav_header.py`

- [ ] 建立新檔，**整份照抄**：

```python
"""全站頂欄四格導覽的契約測試（增量五 Phase 53；design5.md §6.1、§9）。

本專案的前端沒有自動化測試框架（純前端 phase 一向是瀏覽器實操驗收）。
但「五頁的頂欄要長得一樣」這種事最容易在改了其中一頁之後悄悄走鐘，
而且走鐘了畫面不會壞、只是少一格——人不一定看得出來。

所以用最便宜的方式釘住：**直接把 HTML 當文字讀進來、斷言字串在不在**。
手法比照既有的 tests/integration/test_design4_error_paths.py
（那裡有好幾顆掃 browse.html／folder_modal.js 原始碼的測試）。

Phase 55 會在本檔追加「瀏覽頁不再是待決定入口」的三顆。
Phase 67 刪掉五頁的計數片段時，會把 test_五頁都有同一份待決定計數片段
**原地換成**新的一顆（改名、不加顆）——刪片段的人記得連測試一起換，不要只刪測試。
"""

from __future__ import annotations

from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
STATIC = 專案根目錄 / "app" / "static"

# 頂欄要出現在這五頁。camera-phone.html 刻意不在名單裡——
# 那是手機全螢幕取景頁，見 test_手機取景頁沒有頂欄。
有頂欄的五頁 = [
    "upload.html",
    "pending.html",
    "browse.html",
    "ask.html",
    "camera-desk.html",
]

# 四格的「文字」與「網址」逐字對照（增量五契約 §6：一個字都不能改）
四格 = [
    ("上傳照片", "/ui/upload.html"),
    ("待決定", "/ui/pending.html"),
    ("瀏覽資料夾", "/ui/browse.html"),
    ("問問題", "/ui/ask.html"),
]

# 「待決定（N）」那一格的固定形狀。前面的開頭標籤各頁不同（當頁那一頁多了
# aria-current），所以只比對「開頭標籤之後」的這一段——五頁逐字相同。
待決定那一格的尾巴 = '待決定（<span id="nav-pending-count">…</span>）</a>'

# 五頁各有一份、逐字相同的計數片段（Phase 67 由 progress_panel.js 接手時整組刪掉）
計數片段的關鍵行 = [
    'const 格子 = document.getElementById("nav-pending-count");',
    'fetch("/folders").then(function (response) {',
    "if (!response.ok) return null;",
    "const inbox = folders.find(function (f) { return f.is_inbox; });",
    "if (inbox) 格子.textContent = String(inbox.photo_count);",
    "}).catch(function (error) {",
]
# ↑ 第三行與最後一行是 2026-08-25 審查後補釘的：分別承載「4xx/5xx 時維持「…」、
#   不顯示猜的 0」與「服務連不上時安靜維持「…」、不噴 unhandled rejection」兩個
#   §4.1 明文行為——原本四行釘不到它們，審查用變異測試證實刪掉仍七顆全綠。

# 哪一頁該把哪一格標成當頁
當頁對照 = {
    "upload.html": "/ui/upload.html",
    "pending.html": "/ui/pending.html",
    "browse.html": "/ui/browse.html",
    "ask.html": "/ui/ask.html",
}


def 讀(檔名: str) -> str:
    """讀 app/static/ 底下的檔。

    刻意不先判 exists()：路徑打錯要當場炸 FileNotFoundError，
    不能因為「檔案不存在」而默默變成綠的。
    """
    return (STATIC / 檔名).read_text(encoding="utf-8")


def test_五頁頂欄都有四格導覽():
    """四格的文字與網址逐字比對（design5.md §6.1）。"""
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        for 文字, 網址 in 四格:
            assert f'href="{網址}"' in 原始碼, f"{檔名} 的頂欄少了 {網址} 這一格"
            assert 文字 in 原始碼, f"{檔名} 的頂欄少了「{文字}」這幾個字"


def test_待決定那一格是固定形狀且帶計數欄位():
    """全形括號、span 的 id、初始值「…」——五頁必須逐字相同。

    數字包在 <span id="nav-pending-count"> 裡，JS 只改那個 span；
    「待決定」三個字與括號永遠不會被程式碰到。
    """
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        assert 待決定那一格的尾巴 in 原始碼, f"{檔名} 的「待決定（N）」形狀不對"


def test_五頁都有同一份待決定計數片段():
    """階段甲的 N 來自既有 GET /folders 的收件箱 photo_count（design5.md §6.1）。

    這顆同時擋住兩種走鐘：某一頁忘了貼、以及有人只改了其中一份。

    ⚠ 這顆有預告的死期：Phase 67 刪掉五份片段時，要把這顆**原地換成**
    test_五頁的計數片段已交棒給進度面板（換名、不加顆）——不是刪掉。
    """
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        for 關鍵行 in 計數片段的關鍵行:
            assert 關鍵行 in 原始碼, f"{檔名} 少了頂欄計數片段的這一行：{關鍵行}"


def test_每一頁只標自己那一格為當頁():
    """aria-current="page" 恰好一個，而且標在自己身上。

    ⚠ browse.html 的分頁列用的是 aria-current="true"（不是 "page"），
    所以這裡數 "page" 的數量不會被分頁列干擾。
    """
    for 檔名, 自己的網址 in 當頁對照.items():
        原始碼 = 讀(檔名)
        assert f'href="{自己的網址}" aria-current="page"' in 原始碼, (
            f"{檔名} 沒有把自己那一格標成當頁"
        )
        assert 原始碼.count('aria-current="page"') == 1, (
            f"{檔名} 標了不只一格當頁"
        )


def test_鏡頭桌面頁不標任何一格為當頁():
    """鏡頭桌面頁不是那四格之一（它是上傳頁的支線），現況就是不標。"""
    assert 'aria-current="page"' not in 讀("camera-desk.html")


def test_手機取景頁沒有頂欄():
    """camera-phone.html 是手機全螢幕取景頁，刻意不掛頁首與導覽。

    style.css 對這一頁的註解寫得很白：「它只有一個用途，多一個連結都是誤觸來源」。
    版面是 height: 100dvh; overflow: hidden 算好的，插一條頁首會把取景區壓扁。
    """
    原始碼 = 讀("camera-phone.html")
    assert "site-header" not in 原始碼
    assert "/ui/pending.html" not in 原始碼
    assert "待決定" not in 原始碼


def test_端點數仍為20(client):
    """本 phase 純前端：一支端點都沒加。

    /ui/pending.html 是靠 app/main.py 的 app.mount("/ui", StaticFiles(...))
    送出去的靜態檔，不會出現在 openapi.json 裡。

    ⚠ paths 是「路徑 → 方法」兩層字典，要把每個路徑底下的方法數加起來，
    不能直接數 paths 有幾個 key（算法與 test_ask_three_paths.py 的
    test_端點數不變 一致；增量五要到 Phase 64 才會變成 22）。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(path, method) for path, item in paths.items() for method in item]

    assert len(運算元) == 20
```

- [ ] 跑它（**先確認會紅**再改碼是 TDD 的規矩；但本 phase 是「改 HTML 讓它變綠」，
      所以順序是：**先把測試檔建好、跑一次確認它抓得到還沒改的頁面**）：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_nav_header.py -v
```

  **在 §4.3〜4.7 都還沒做的情況下**，預期看到：
  `test_五頁頂欄都有四格導覽` 紅（五頁都少了 `/ui/pending.html`）、
  `test_待決定那一格是固定形狀且帶計數欄位` 紅、
  `test_五頁都有同一份待決定計數片段` 紅、
  `test_每一頁只標自己那一格為當頁` 紅（`pending.html` 沒有標當頁）；
  另外三顆（鏡頭桌面頁、手機取景頁、端點數）本來就綠。
  **＝ 3 綠 4 紅。** 看到這個結果，代表測試真的在測東西，不是恆綠的假測試。

- [ ] 做完 §4.3〜4.7 之後再跑一次：**7 顆全綠**。

### 4.9 瀏覽器實操確認

五頁逐一開過去（**網址開頭是 `https`**）：

- [ ] `https://127.0.0.1:8000/ui/upload.html` → 頂欄四格；「上傳照片」有底線（當頁）。
- [ ] `https://127.0.0.1:8000/ui/pending.html` → 四格；「待決定（N）」有底線。
- [ ] `https://127.0.0.1:8000/ui/browse.html` → 四格；「瀏覽資料夾」有底線。
      （這一頁**同時**還看得到分頁列的「待決定（N）」——那是暫時的，Phase 55 收掉。）
- [ ] `https://127.0.0.1:8000/ui/ask.html` → 四格；「問問題」有底線。
- [ ] `https://127.0.0.1:8000/ui/camera-desk.html` → 四格；**沒有任何一格有底線**。
- [ ] **N 真的對**：先用唯讀查詢問出正確答案，再跟畫面比：

```bash
psql -d PersonalDocAI -c \
  "SELECT count(*) FROM photo p JOIN folder f ON f.id = p.folder_id WHERE f.is_inbox;"
```

  五頁頂欄顯示的數字都要等於這個 count。

- [ ] **點得到新頁**：從任一頁點「待決定（N）」→ 到 `/ui/pending.html`，內容正確。
- [ ] **服務掛掉時停在「…」不是「0」**：`docker compose stop app`
      → 重新整理任一頁（頁面主體會顯示錯誤）→ 頂欄那一格停在 `待決定（…）`。
      再 `docker compose -f compose.yaml -f compose.dev.yaml up -d` 起回來。
      （**不要**用 `docker compose down -v`，那會刪正式庫的 volume。）
- [ ] **窄螢幕不破版**：把瀏覽器視窗縮到 500px 以下（或用開發者工具的手機模擬）
      → 四格會換行排列、不會擠出畫面外（`@media (max-width: 32rem)` 已經處理好）。
- [ ] **手機取景頁沒被波及**：`https://127.0.0.1:8000/ui/camera-phone.html`
      → 仍然是滿版取景畫面、**沒有**頁首。
      （這一頁單獨開會顯示「配對已結束」之類的字，因為沒有 token；
      看的是**版面**有沒有多一條頁首，不是它能不能連線。）
- [ ] **Console 乾淨**：五頁都沒有紅色錯誤。

---

## 5. ASCII 圖：改版前三格 vs 改版後四格

```text
  ┌───────────────────────── 改版前（三格）─────────────────────────┐
  │                                                                 │
  │  PersonalDocAI      上傳照片   瀏覽資料夾   問問題   [本機|雲端] │
  │                     ━━━━━━━━                                    │
  │                     ↑ aria-current="page" 畫出來的底線           │
  │  ─────────────────────────────────────────────────────────────  │
  │                                                                 │
  │  「待決定」在哪裡？→ 藏在瀏覽資料夾點進去的第一個分頁            │
  │     /ui/browse.html （不帶 query）                              │
  │  【待決定（3）】 【資料夾】 【待辦（2）】                        │
  │   ↑ 要點兩層才看得到，而且「有沒有事情要處理」不點不知道         │
  └─────────────────────────────────────────────────────────────────┘

                                 │
                                 │  ★ Phase 53
                                 ▼

  ┌───────────────────────── 改版後（四格）─────────────────────────┐
  │                                                                 │
  │  PersonalDocAI   上傳照片  待決定（3）  瀏覽資料夾  問問題  [開關]│
  │                  ━━━━━━━━                                       │
  │                              ↑ 這一格是新的，連 /ui/pending.html │
  │                              ↑ 括號裡的 3 每次開頁算一次         │
  │  ─────────────────────────────────────────────────────────────  │
  │                                                                 │
  │  五頁都長這樣（差別只有「哪一格有底線」與「有沒有 AI 開關」）：  │
  │     upload.html      → 上傳照片 有底線     ／ 有開關             │
  │     pending.html     → 待決定   有底線     ／ 沒有開關           │
  │     browse.html      → 瀏覽資料夾 有底線   ／ 沒有開關           │
  │     ask.html         → 問問題   有底線     ／ 有開關             │
  │     camera-desk.html → 都沒有底線（支線頁）／ 有開關             │
  │                                                                 │
  │  ✗ camera-phone.html（手機取景）→ **完全沒有頂欄**               │
  │     那是單手拍照的全螢幕畫面，多一個連結就是多一個誤觸來源       │
  └─────────────────────────────────────────────────────────────────┘


  N 這個數字現在從哪來、之後從哪來
  ─────────────────────────────────────────────────────────────────

   階段甲（現在，Phase 53）           階段丙（之後，Phase 67）
   ┌──────────────────────┐          ┌──────────────────────────────┐
   │ 每頁載入時各打一次    │          │ progress_panel.js 全站唯一一份│
   │   GET /folders        │          │ 每 2000 ms 打一次            │
   │   ↓                   │   ───►   │   GET /ingest-jobs           │
   │ 找 is_inbox 那一筆    │          │   ↓                          │
   │   .photo_count        │          │ 回應同時帶 jobs[] 與         │
   │   ↓                   │          │   pending_count（SQL 算的）  │
   │ 填進 #nav-pending-    │          │   ↓                          │
   │   count               │          │ 更新 N ＋ 右下角進度面板     │
   │                       │          │                              │
   │ 五個 HTML 各一份      │          │ ★ 五份小片段在這時整組刪掉   │
   │ 25 行、逐字相同       │          │  （那顆存在性測試原地改寫）  │
   └──────────────────────┘          └──────────────────────────────┘
       只算一次，不輪詢                    輪詢，換頁不消失
```

---

## 6. 驗收清單

- [ ] **五個 HTML 都有四格**：

```bash
cd /Users/linjunting/personalDocAI
for f in upload pending browse ask camera-desk; do
  printf "%-12s " "$f"
  grep -c 'href="/ui/pending.html"' "app/static/$f.html"
done
```

  預期：五行都是 `1`。

- [ ] **手機取景頁一格都沒有**：

```bash
grep -n "pending.html\|site-header\|待決定" app/static/camera-phone.html \
  || echo "OK：手機取景頁完全沒有頂欄"
```

  預期：印出 `OK：…`。

- [ ] **五份計數片段逐字相同**（用 `md5` 比對抽出來的那一段，最不會看走眼）：

```bash
for f in upload pending browse ask camera-desk; do
  printf "%-12s " "$f"
  sed -n '/頂欄「待決定（N）」的 N/,/^})();$/p' "app/static/$f.html" | md5
done
```

  預期：五行的 md5 **完全相同**。不同就是有人只改了其中一份。

- [ ] **當頁標記**：

```bash
for f in upload pending browse ask camera-desk; do
  printf "%-12s " "$f"
  grep -c 'aria-current="page"' "app/static/$f.html"
done
```

  預期：前四行是 `1`、`camera-desk` 那行是 `0`。

- [ ] **新測試全綠**：

```bash
source .venv/bin/activate
pytest tests/integration/test_nav_header.py -v
```

  預期：**7 passed**。

- [ ] **全量顆數**：

```bash
pytest -q
```

  預期：**412 passed ＋ 0 skipped**（405 ＋ 本 phase 新增的 7）。

- [ ] **端點仍 20**（上面那顆 `test_端點數仍為20` 已經釘住，這裡再從外面驗一次）：

```bash
curl -k -s https://127.0.0.1:8000/openapi.json \
  | python3 -c "import json,sys; p=json.load(sys.stdin)['paths']; print(sum(len(v) for v in p.values()))"
```

  預期：`20`。

- [ ] **零 Python 產品碼變更**：

```bash
git status --short -- app/api app/services app/repositories app/schemas app/core app/db \
  app/dependencies.py app/main.py || true
git diff --stat -- app/api app/services app/repositories app/schemas app/core app/db \
  app/dependencies.py app/main.py
```

  預期：**兩個指令都沒有輸出**（本 phase 只改 `app/static/` 底下的 HTML；
  路徑清單就是 `app/` 底下除了 `static/` 以外的全部 Python）。

- [ ] **改動範圍就是五個 HTML ＋ 一個新測試檔**：

```bash
git status --short -- app tests
```

  預期：`M app/static/upload.html`、`M app/static/browse.html`、`M app/static/ask.html`、
  `M app/static/camera-desk.html`、`app/static/pending.html`（Phase 52 還沒 commit 時是 `??`；
  已經 commit 過的話，因為本 phase 改了它的頁首，會是 ` M`——兩種都對）、
  `?? tests/integration/test_nav_header.py`。
  **沒有** `app/static/folder_modal.js`（那是 Phase 54）。

- [ ] §4.9 的 11 項瀏覽器實操逐項打勾、Console 乾淨。

---

## 7. 常見陷阱

1. **全形括號打成半形**：`待決定(3)` 與 `待決定（3）` 是不同字元，肉眼幾乎看不出來，
   但 `test_待決定那一格是固定形狀且帶計數欄位` 會紅。
   最保險的做法：**不要自己打字，把 §4.2／§4.3 的整段複製貼上**。

2. **五份計數片段複製時漏掉一份**，症狀是「其他四頁都有數字，就那一頁停在 `…`」。
   `test_五頁都有同一份待決定計數片段` 會抓到；
   驗收清單的 `md5` 比對也會抓到（其中一行會是不同的雜湊，或 `sed` 抽不到東西）。

3. **順手把 `browse.html` 的分頁列也刪了**：不要，那是 Phase 55。
   本 phase 做完 `browse.html` 會有兩個「待決定（N）」入口，是**刻意的暫時狀態**。

4. **順手在 `camera-phone.html` 也加頂欄**：不要。理由在 §3 的表格裡（誤觸＋版面被壓扁）。
   `test_手機取景頁沒有頂欄` 會紅。

5. **把 `aria-current="page"` 標在兩格上**（例如複製 `upload.html` 的 header 去改 `ask.html`
   卻忘了把 upload 那一格的屬性拿掉）：畫面會出現兩條底線，
   螢幕報讀軟體會說「你同時在兩個頁面」。`test_每一頁只標自己那一格為當頁`
   的 `count(...) == 1` 就是為了抓這個。

6. **以為 `browse.html` 的分頁列會干擾 `aria-current` 計數**：不會。
   分頁列用的是 `aria-current="true"`（`renderTabs()` 裡的 `setAttribute("aria-current", "true")`），
   測試數的是 `aria-current="page"`，兩者字串不同。**但不要因此去把分頁列改成 `"page"`**——
   那會讓這顆測試在 Phase 55 之前就紅。

7. **N 顯示 `0`，但資料庫裡明明有照片**：先確認你不是在看**快取**的舊頁（`Cmd`＋`Shift`＋`R`）。
   還是 `0` 的話，開發者工具的 Network 分頁看 `GET /folders` 的回應——
   `is_inbox` 那一筆的 `photo_count` 是多少？如果 API 回的就是 0，那是資料問題不是前端問題。

8. **N 一直停在 `…`**：代表 `GET /folders` 沒有成功。Network 分頁看它的狀態碼。
   最常見是服務沒起來，或你用了 `http://`（少一個 s）。**停在 `…` 是設計好的行為**，
   不是 bug——比顯示一個猜的 `0` 誠實。

9. **改 HTML 存檔了畫面卻沒變**：先按 `Cmd`＋`Shift`＋`R` 排除瀏覽器快取；
   還是沒變就 `docker compose ps --no-trunc` 看 `COMMAND` 欄有沒有 `--reload`。
   **沒有 `--reload` ＝常駐模式，程式在映像裡**，你改的檔容器根本看不到。

10. **想「順便」把 N 做成每幾秒自動更新**：不要。design5 §6.1 明文說輪詢是階段丙，
    而且要「全站唯一一份 JS」。現在做等於做兩次，而且 Phase 67 會把它砍掉。

11. **想「順便」把這五段小程式抽成一支共用 js**：不要，理由見 §3 的表格。
    契約只認可兩個新前端檔；沒登記的共用檔在 Phase 67 會變成沒人敢刪的孤兒。
