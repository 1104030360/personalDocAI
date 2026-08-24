# Phase 39：唯讀詳情彈窗 ＋ 資料夾牆入口（階段甲第 2 步）

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
> 最新 RED→GREEN 另釘住 focus trap、背景 `inert`、Tab／Shift+Tab 循環、focus restore，
> generation token 忽略 stale 回應，以及遺失圖片、raw error 與長 CJK 的安全降級。
> 狀態固定為 **TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**；工作樹仍 dirty，
> 沒有 commit、release、Docker／Compose 或 Phase 45 工作。

> 🎯 **提醒：這是 side project，不要過度設計。**

> 🎯 **一句話目標：** 做出全站唯一一顆**唯讀**照片詳情彈窗（`photo_detail_modal.js`），
> 並把瀏覽頁「資料夾」分頁的縮圖牆從「點不動的方塊」改成「點下去開這顆窗」。
> 窗裡有大圖、AI 寫的說明、四個欄位——但**沒有任何改資料夾的按鈕**。

**為什麼是唯讀：** design2.md 定案的「定案不可逆」仍然有效——照片一旦歸進真資料夾就不能再改。
所以這顆窗只回答「這張是什麼」，不提供任何後悔藥。想改？沒有。這是產品負責人在 grill 時
明確選的（design4 §1.2 否決了「資料夾點開再歸類／改夾」）。

---

## 1. 對應 design4.md 章節

- **§4.1**（誰可以開這顆窗：資料夾縮圖牆 `div.photo-static` → `<button>`；待決定牆**不改**）
- **§4.2**（彈窗長相：四段固定順序、空欄寫「無」、×／Esc／點暗色區可關、禁 `alert`）
- **§4.3**（前端契約 `openPhotoDetailModal({photoId, task})`、載入中／404／網路失敗三種狀態）
- **§4.5**（會動到的檔：`photo_detail_modal.js` 新建、`browse.html`、`style.css`）
- **D1**（共用同一顆窗）、**D2**（只准看不准改夾）、**D4**（空欄仍列出、寫「無」）、**D6**（無原圖 → 灰底占位）
- **§1.1 第 1 列**（正式推翻 design2.md D4「資料夾 tab 的縮圖牆純瀏覽、照片不可點」）
- **§9 錯誤表第 3 列**（路徑有值但檔案沒了 → `<img>` 載入失敗降級占位，不是整窗 404）

---

## 2. 前置條件

- **Phase 38 已完成且全綠**（`GET /photos/{photo_id}` 可用，`pytest -q` ＝ 365 passed ＋ 2 skipped）。
  沒有這支端點，這顆窗抓不到資料。
- 起一個伺服器準備隨時看畫面：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- 正式庫裡要有**至少一張已定案（在真資料夾裡）的照片**才看得到效果。
  沒有的話先上傳一張、在彈窗鏈裡歸進「收據」。

---

## 3. 範圍

### 做

- 新建 `app/static/photo_detail_modal.js`（**全站唯一一份**詳情窗，前綴 `pd-`）。
- `app/static/style.css` 新增 `pd-` 區塊（沿用既有 `fm-` 的視覺語言，見下面 §4.3）。
- `app/static/browse.html`：
  - 掛 `photo_detail_modal.js`；
  - 資料夾縮圖牆（`showFolderPhotos`）的照片卡改成可點，點了開詳情窗；
  - `照片卡()` 函式的第二個參數（`可點`）拿掉——改完之後兩個牆都是可點的。
- `style.css` 刪掉 `.photo-static` 兩條規則（沒有人再用它了，**不留過渡產物**）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 窗裡放「改資料夾」「重新歸類」按鈕 | design4 D2、§1.2 第 1 列：推翻 design2 定案鎖定的方案已被否決 |
| 窗裡放刪除照片／刪待辦 | 全系統沒有刪除端點（design3 §3、design4 §1.2 第 2 列） |
| 動待決定分頁的行為 | design4 §4.1 第 3 列明寫「**不改**」——待決定點照片仍走抽屜→實體歸類鏈 |
| 動上傳頁／鏡頭頁的三關彈窗鏈 | design4 §4.1 第 4 列明寫「**不改**」。`classify_chain.js` 一個字都不碰 |
| 在 `upload.html`／`ask.html`／`camera-desk.html` 掛這一份 js | design4 §4.3 末句：「其他頁本輪不必掛」 |
| 用 `alert`／`confirm`／`prompt` 顯示錯誤 | 全站鐵律。錯誤一律寫進窗內的 `#pd-error` |
| 用 `innerHTML` 塞 AI 產生的文字 | 全站鐵律。動態內容一律 `textContent` |
| 為這顆窗新增自動化測試 | 本專案前端慣例（Phase 23／24／31／33 皆然）：純前端零新增自動化測試，改用瀏覽器實操驗收 |
| 做上一張／下一張、放大縮小、下載圖 | design4 沒要求；不要過度設計 |

---

## 4. 實作步驟

### 4.1 先看懂現在的 `browse.html`（不寫程式，只讀）

- [ ] 打開 `app/static/browse.html`，找到這三個地方：

| 行數（約） | 內容 | 本 phase 要做什麼 |
|---|---|---|
| 24〜25 | `<script src="/ui/folder_modal.js">`、`entity_modal.js` | 後面再加一行 `photo_detail_modal.js` |
| 76〜97 | `function 照片卡(photo, 可點)` | 把 `可點` 參數拿掉，一律產生 `<button class="photo">` |
| 246〜270 | `async function showFolderPhotos(folderId)` | 加一段事件監聽：點卡片 → 開詳情窗 |

- [ ] 注意 76 行那個函式現在的兩種產出：

```text
可點 == true   →  <button class="photo" data-photo-id="7">      （待決定分頁用）
可點 == false  →  <div class="photo photo-static">              （資料夾牆用，點不動）
```

  本 phase 之後只剩上面那一種。`photo-static` 這個 class 從此沒有人用，要一起刪掉。

### 4.2 新建 `app/static/photo_detail_modal.js`

- [ ] 建檔，檔頭寫清楚用法與鐵律（照 `folder_modal.js` 的寫法）：

```javascript
/* 照片詳情彈窗（唯讀）：資料夾縮圖牆與待辦列共用這一份，全站只有這一份。

   ⚠ design4.md D2：這顆窗是「唯讀」——沒有任何改資料夾的按鈕。
     design2.md 的「定案不可逆」仍然有效，這裡不提供後悔藥。
     待決定分頁點照片走的是 folder_modal.js 的歸類鏈，不是這顆窗。

   ⚠ 一律不用 alert／confirm／prompt（全站鐵律）：錯誤寫進窗內的 <p id="pd-error">。

   用法：
     openPhotoDetailModal({
       photoId: 7,
       task: null                       // 資料夾牆進來：不畫待辦那一行
       // 或 { title: "繳電費", due_date: "2026-09-18" }   // 待辦列進來（Phase 40）
     });

   關閉方式三種都要有：右上角 ×、Esc、點暗色區。這顆**不是** design2 那種關不掉的強制窗。
   樣式全部在 /ui/style.css 的「詳情彈窗」區塊（本檔不注入任何樣式）。
*/
```

- [ ] 樣板 HTML（固定字串，沒有任何外來資料，所以可以用 `innerHTML` 一次裝上；
      這與 `folder_modal.js` 的 `FOLDER_MODAL_HTML` 是同一個作法）：

```html
<div class="fm-backdrop" id="pd-backdrop" hidden>
  <div class="fm-box" role="dialog" aria-modal="true" aria-labelledby="pd-title">
    <button type="button" class="pd-close" id="pd-close" aria-label="關閉">×</button>
    <h3 id="pd-title">照片</h3>

    <div class="pd-task" id="pd-task" hidden>
      <p class="pd-task-title" id="pd-task-title"></p>
      <p class="pd-task-due" id="pd-task-due"></p>
    </div>

    <div class="pd-image" id="pd-image"></div>

    <p class="pd-text" id="pd-text">載入中…</p>

    <dl class="pd-fields" id="pd-fields"></dl>

    <p class="fm-error" id="pd-error"></p>
  </div>
</div>
```

  **為什麼外框沿用 `fm-backdrop`／`fm-box`／`fm-error` 這幾個 class**：那是三個既有彈窗
  （抽屜／實體／待辦）共用的**視覺語言**（`style.css` 第 4〜5 行的註解已寫明這個約定：
  class 共用、id 各自加前綴）。沿用＝零複製樣式、外觀天然一致。

- [ ] 內部狀態與小工具（全部用 `pd` 前綴，才不會和 `fm`／`em`／`tm` 撞名）：

```text
let pdReady = false;        // HTML 與事件只裝一次
let pdLastFocus = null;     // 記住是誰打開的，關掉時把鍵盤焦點還回去
function pdInstall()        // 把樣板 HTML 塞進 <body>、掛好三種關窗的監聽；
                            // 靠 pdReady 保證只跑一次（對照 folder_modal.js 的 fmInstall()）
function pdEl(id)           // document.getElementById 的短寫
function pdSetError(msg)    // 寫進 #pd-error（空字串＝隱藏，CSS 的 :empty 負責）
function pdOpen() / pdClose()   // 開＝backdrop.hidden = false；關＝backdrop.hidden = true
```

- [ ] 開窗與關窗要做的事（照 `folder_modal.js` 的 `fmAfterOpen`／`fmAfterClose` 抄，
      **但寫成自己的 `pd` 版本**，不要去改 `folder_modal.js`）：

```text
開窗：pdLastFocus = document.activeElement
      backdrop.hidden = false
      document.body.classList.add("fm-open")        ← 鎖住背景捲動（CSS 已有這條規則）
      焦點移到 #pd-close
關窗：backdrop.hidden = true
      document.body.classList.remove("fm-open")
      焦點還給 pdLastFocus
```

- [ ] 三種關閉方式：

```text
① × 按鈕      → #pd-close 的 click
② Esc          → document 的 keydown，event.key === "Escape" 且窗開著才關
③ 點暗色區    → #pd-backdrop 的 click，且 event.target === backdrop 才關
                 （沒有這個判斷，點窗**裡面**也會關掉——這是最常見的 bug）
```

- [ ] `openPhotoDetailModal(config)` 的流程（design4 §4.3 五步）：

```text
① 開窗、把上一張的殘影清乾淨：
     #pd-task 一律 hidden（本 phase 兩個呼叫端都只傳 task: null；
              「依 config.task 把標題／到期日畫出來」是 Phase 40 的事）
     #pd-image 清空、#pd-fields 清空、#pd-error 清空
     #pd-text 寫「載入中…」
② await fetch("/photos/" + config.photoId)
③ response.status === 200 → 畫圖 ＋ 說明 ＋ 四欄（見下面）
④ response.status === 404 → #pd-error 寫「找不到這張照片」，#pd-text 清空
⑤ fetch 本身丟例外（伺服器沒開、網路斷）
                          → #pd-error 寫「載入失敗：… （uvicorn 是不是沒在跑？）」
     ★ 不管哪一種，窗都留在開著的狀態——使用者要看得到發生什麼事，
       不可以默默關掉、更不可以跳 alert。
```

- [ ] 畫圖那一段（**§9 錯誤表第 3 列的關鍵**）：

```text
if (body.image_url) {
    建立 <img>，src = body.image_url，alt = body.text
    img.addEventListener("error", 換成占位)     ← 檔案被刪掉時走這裡
    塞進 #pd-image
} else {
    直接塞占位：<div class="placeholder">無原圖</div>
}

「換成占位」＝把 #pd-image 的內容清掉、改塞同一個 placeholder div。
沿用縮圖牆既有的 .placeholder class（style.css 已經有灰底置中的樣式），
態度一致：不假裝有圖、也不顯示瀏覽器的破圖 icon。
```

- [ ] 畫說明那一段（一行就夠，但別漏了）：

```text
#pd-text 的 textContent ← body.text     （把步驟①寫的「載入中…」蓋掉）

design4 §4.2 第 3 點：text 永遠顯示、不必判斷空不空。
理由是上傳流程在「VLM 看不懂」時是 422 什麼都不存——
資料庫裡不存在 text 空白的照片，所以有這一列就一定有說明。
```

- [ ] 畫四欄那一段（**D4：四欄都要在，空的寫「無」**）：

```text
四欄的順序與標籤固定：
    類別      ← body.metadata.category
    地點      ← body.metadata.location
    物品      ← body.metadata.items 用「、」串起來
    內容日期  ← body.metadata.content_time

每一欄都建 <dt>標籤</dt><dd>值</dd> 塞進 #pd-fields。
值是空字串／null／空陣列 → 一律寫「無」。
一律用 textContent，不要用 innerHTML（AI 寫的內容可能有 < 之類的符號）。
```

  寫成一個小函式最省事，例如：

```javascript
function pd值或無(value) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "無";
  return (value === null || value === undefined || value === "") ? "無" : value;
}
```

### 4.3 `style.css` 新增 `pd-` 區塊、刪掉 `.photo-static`

- [ ] 在既有「彈窗（folder／entity／task modal 共用 fm-* class）」區塊**之後**加一段新註解區塊：

```css
/* ══ 詳情彈窗（photo_detail_modal.js；唯讀，沿用 fm-* 外框，內容用 pd-*）════ */
```

- [ ] **先補一個既有的選擇器**（第 533〜535 行）：彈窗標題那條規則是用 **id** 選的，
      不是用 class，所以要把 `#pd-title` 加進去：

```css
#fm-title,
#em-title,
#tm-title,
#pd-title {          /* ← 加這一行 */
```

  **為什麼不能漏**：那條規則給的是 `--f-display` 標題字體、`--fs-section` 字級，
  以及右邊留 `var(--sp-6)`（3rem）的空位。不加 `#pd-title`，這顆窗的 `<h3>` 會掉回
  瀏覽器預設樣式（字級與上下邊距都跟另外三顆窗不一樣），而且右上角那顆 × 會壓在標題上。

- [ ] 其餘需要新寫的規則就這幾條（不要多做）：

| 選擇器 | 做什麼 |
|---|---|
| `.pd-close` | 右上角的 ×：`position: absolute; top/right: var(--sp-3);` 無邊框、字大一點、`cursor: pointer`（既有的 `.fm-box` 已經是 `position: relative`，所以 absolute 自然以彈窗盒為基準，不必另外加） |
| `.pd-image` | 圖的容器：`margin-bottom: var(--sp-4);` |
| `.pd-image img` | `display: block; width: 100%; max-height: 60vh; object-fit: contain;` ← `contain` 是「整張圖塞得下、不裁切」，跟縮圖牆的 `cover`（填滿方格、裁掉超出）刻意不同：這裡是要**看清楚**，不是排整齊 |
| `.pd-image .placeholder` | 沿用既有 `.placeholder`，但把 `aspect-ratio` 覆寫成 `16 / 9` 之類的扁一點的比例（既有那條是為縮圖牆的正方形格子寫的） |
| `.pd-text` | 說明文字：`margin: 0 0 var(--sp-4); line-height: 1.6;` |
| `.pd-fields` | `display: grid; grid-template-columns: auto 1fr; gap: var(--sp-2) var(--sp-3); margin: 0;` |
| `.pd-fields dt` | `color: var(--c-text-muted); font-size: var(--fs-small);` |
| `.pd-fields dd` | `margin: 0;` |
| `.pd-task` | 待辦那一行（Phase 40 會用到）：`padding-bottom: var(--sp-3); margin-bottom: var(--sp-4); border-bottom: var(--bw) solid var(--c-border);` |
| `.pd-task[hidden]` | `display: none;`（同 `.fm-option[hidden]` 的理由：其他 display 值會蓋過 hidden 的預設行為） |
| `.pd-task-title` | `margin: 0; font-family: var(--f-display); font-size: var(--fs-section);` |
| `.pd-task-due` | `margin: var(--sp-1) 0 0; color: var(--c-text-muted); font-size: var(--fs-small);` |

  **顏色一律用既有的 design tokens**（`var(--c-…)`、`var(--sp-…)`、`var(--fs-…)`），
  不要新增色票——`style.css` 檔頭寫明它是全站唯一樣式來源、單一強調色。

- [ ] 刪掉這兩條（第 448〜450 行附近，含上面那行註解）：

```css
/* 資料夾牆的純瀏覽卡（design2.md D4）：已定案照片沒有互動，連手指游標都不給 */
.photo-static { cursor: default; }
.photo-static:hover { border-color: var(--c-border); }
```

  理由：design4 §1.1 第 1 列正式推翻了那條 design2 決定，這兩行從此無人使用。

### 4.4 改 `app/static/browse.html`

- [ ] ① 掛新檔（第 25 行之後）：

```html
<script src="/ui/photo_detail_modal.js"></script>
```

- [ ] ② `照片卡()` 簡化成一種（原本的 76〜97 行）：

```javascript
// 一張照片卡。兩個牆（待決定、資料夾）都是可點的 <button>，
// 差別只在「點下去開哪一種窗」——那由各自的牆自己決定（見下面兩個 addEventListener）。
function 照片卡(photo) {
  const card = el("button", "photo");
  card.type = "button";
  card.dataset.photoId = photo.id;      // event delegation 用得到
  … 其餘一字不動：縮圖／占位、caption，最後包成 <li> 再 return …
}
```

  **event delegation（事件委派）是什麼**：不在每張卡片上各掛一個監聽器，
  而是在整面牆（`<ul>`）上掛**一個**，靠 `event.target.closest(".photo")` 找出被點的是哪一張。
  卡片是後來動態產生的，這樣寫最省事——`showPending()` 已經是這個寫法，照抄。

- [ ] ③ 兩個呼叫端跟著改：
  - `showPending()` 裡的 `wall.appendChild(照片卡(photo, true));` → `照片卡(photo)`
  - `showFolderPhotos()` 裡的 `wall.appendChild(照片卡(photo, false));` → `照片卡(photo)`

- [ ] ④ `showFolderPhotos()` 加提示文字與點擊行為（在 `const wall = el("ul", "wall");` 前後）：

```javascript
  view.appendChild(el("p", "message",
    "點一張照片可以看大圖與完整說明。已定案的照片不能改資料夾。"));

  const wall = el("ul", "wall");
  detail.photos.forEach(function (photo) {
    wall.appendChild(照片卡(photo));
  });

  // 資料夾牆：點照片開**唯讀**詳情窗（design4.md D1／D2）。
  // 這裡刻意不帶 task——待辦那一行只有待辦分頁才畫（Phase 40）。
  wall.addEventListener("click", function (event) {
    const card = event.target.closest(".photo");
    if (!card || !card.dataset.photoId) return;
    openPhotoDetailModal({ photoId: Number(card.dataset.photoId), task: null });
  });

  view.appendChild(wall);
```

- [ ] ⑤ 把兩處變成錯的註解順手改掉（**網址規則本身沒變，改的只是「純瀏覽」四個字**——
      不留下騙下一個人的舊描述）：
  - 第 33 行（檔案上方「狀態都寫在網址上」那張對照表）：
    `browse.html?folder=N → 某個資料夾的縮圖牆（純瀏覽）`
    → `browse.html?folder=N → 某個資料夾的縮圖牆（點照片開唯讀詳情窗）`
  - 第 246 行的段落標題註解：
    `// ---------- 畫面三：某個資料夾的縮圖牆（純瀏覽，design2.md D4）----------`
    → `// ---------- 畫面三：某個資料夾的縮圖牆（點照片開唯讀詳情窗，design4.md §1.1 第 1 列）----------`

### 4.5 瀏覽器實操驗收（本 phase 的主要驗收方式）

伺服器跑著，開 `http://localhost:8000/ui/browse.html?tab=folders`，逐項做：

- [x] 點一個資料夾 → 縮圖牆出現，上方有「點一張照片可以看大圖與完整說明」那行字
- [x] 游標移到照片上：邊框變深、游標是手指（`.photo:hover` 生效，代表 `.photo-static` 真的沒了）
- [x] 點一張**有原圖**的照片 → 彈窗跳出：大圖在上、說明在下、四欄都在
- [x] 四欄的空值顯示「無」。先用**唯讀查詢**看正式庫哪一張本來就有空欄（順便查出哪幾張沒有原圖，
      下面兩項會用到）：

```bash
psql -d PersonalDocAI -c \
  "SELECT id, category, location, items, content_time,
          original_path IS NOT NULL AS has_file
   FROM photo ORDER BY id;"
```

      （互動 shell 的 `PGPORT=5433` 已由 `~/.zshrc` 設好，不必再帶 `-p`。）
      真的每一張四欄都滿的時候，才臨時把某一張的 `location` 設成 NULL——
      **動手前先把原值抄下來，驗完立刻 `UPDATE` 寫回去**。這是有真實照片的正式庫，不是測試庫。
- [x] 按 **Esc** → 窗關掉，背後**仍然是那個資料夾的縮圖牆**（不是跳回列表、不是整頁重載）
- [x] 再開一次 → 按右上角 **×** → 關掉
- [x] 再開一次 → 點窗外的**暗色區** → 關掉
- [x] 再開一次 → 點窗**裡面**（例如說明文字）→ **不會**關掉
- [x] 窗開著時滾滑鼠：背景不會跟著捲動（`body.fm-open` 生效）
- [x] 點一張**沒有原圖**的舊照片（＝上面那條查詢裡 `has_file` 欄是 `f` 的那幾張，也就是最早
      遷移進來、`original_path` 為 NULL 的舊照片，它們在「收據」資料夾裡）→ 窗開得起來、
      圖的位置是灰底「無原圖」、說明與四欄照常顯示（D6）
- [x] **檔案被刪掉的降級**（§9 第 3 列）：挑一張有原圖的，把 `data/photos/<id>.jpg`（或 `.png`）
      先改名，重新整理頁面再點它 → 窗仍然開得起來、圖的位置變成灰底「無原圖」、**不是** 404 紅字。
      驗完把檔名改回來。
- [x] **待決定分頁沒有被波及**：開 `http://localhost:8000/ui/browse.html`，點一張待決定的照片 →
      跳出來的是**歸類彈窗**（有「採用／改選／自建／稍後再說」四個出口），**不是**詳情窗
- [x] 上傳頁的三關彈窗鏈沒被波及：`http://localhost:8000/ui/upload.html` 上傳一張 → 鏈照跑
      （本機模型看一張圖要 **2〜5 分鐘**，頁面沒壞、只是在等；想快一點就先把頁首的
      「AI 模型」開關切到「雲端」，那條路約 2 秒）
- [x] **Console 乾淨**：整趟操作下來，開發者工具的 Console 只有既有的預期訊息
      （favicon 404 之類），沒有紅色錯誤

---

## 5. ASCII 圖：三個入口，兩種窗

```text
                     /ui/browse.html
   ┌─────────────────────┬─────────────────────┬─────────────────────┐
   │  【待決定（N）】    │  【資料夾】         │  【待辦（M）】      │
   │  縮圖牆             │  卡片 → 縮圖牆      │  一列一件事         │
   └─────────┬───────────┴──────────┬──────────┴──────────┬──────────┘
             │ 點照片               │ 點照片              │ 點一列
             │                      │ ★ 本 phase 新增     │ ★ Phase 40
             ▼                      ▼                     ▼
   ┌──────────────────┐   ┌────────────────────────────────────────┐
   │ 歸類彈窗（強制） │   │ 詳情彈窗（唯讀）photo_detail_modal.js  │
   │ folder_modal.js  │   │  ┌──────────────────────────────────┐  │
   │  ① 採用建議      │   │  │ 待辦標題／到期日（只有待辦進來） │  │
   │  ② 改選現有      │   │  ├──────────────────────────────────┤  │
   │  ③ 自建          │   │  │              大 圖               │  │
   │  ④ 稍後再說      │   │  │   （image_url 為 null → 灰底）   │  │
   │                  │   │  ├──────────────────────────────────┤  │
   │ → 接實體窗       │   │  │ AI 寫的說明（text）              │  │
   │ → 接待辦窗       │   │  ├──────────────────────────────────┤  │
   │  ★ 本 phase 不改 │   │  │ 類別：收據      地點：Target     │  │
   └──────────────────┘   │  │ 物品：可樂      內容日期：無     │  │
                          │  └──────────────────────────────────┘  │
                          │  關閉：× ／ Esc ／ 點暗色區            │
                          │  沒有任何「改資料夾」按鈕（D2）        │
                          └────────────────────────────────────────┘

   資料流：點卡片 ──► openPhotoDetailModal({photoId, task:null})
                  ──► GET /photos/{id}   （Phase 38 做的那支）
                  ──► 200 畫內容 ／ 404 窗內紅字 ／ 連不上 窗內紅字
```

---

## 6. 驗收清單

- [ ] `app/static/photo_detail_modal.js` 新建完成，**全站只有這一份**詳情窗程式碼
- [ ] 檔案裡搜不到 `alert(`、`confirm(`、`prompt(`、`innerHTML =`（除了裝樣板那一次固定字串）
- [ ] 檔案裡搜不到 `PATCH`、`/folder`（證明它真的唯讀，D2）。
      ⚠️ 這條掃碼靠的是「檔頭註解提到隔壁那份時寫成 `folder_modal.js`、**不帶斜線**」——
      寫成 `/ui/folder_modal.js` 就會誤中、看起來像沒做到唯讀。§4.2 的範本已經是不帶斜線的寫法，
      照抄即可；真的要改註解就在那一行補一句自我提醒
      （`folder_modal.js` 第 7 行對同類問題已有前例：「這行註解故意不在函式名後面加小括號——
      驗收會用 grep 掃…，註解不能誤中」）
- [ ] `style.css` 有 `pd-` 區塊、**沒有** `.photo-static`
- [ ] `browse.html` 的 `照片卡()` 只剩一個參數，兩個牆都用它
- [x] §4.5 的 14 項瀏覽器實操逐項打勾、Console 乾淨
- [ ] `pytest -q` 仍是 **365 passed ＋ 2 skipped**（本 phase 純前端，顆數不變）
- [ ] 只動到三個檔。查法要分兩條指令，因為新建的 `photo_detail_modal.js` **還沒 `git add`**
      （本增量全程不 commit），`git diff` 看不到未追蹤的檔案：

```bash
git diff --stat -- app          # 恰好兩個檔：app/static/style.css、app/static/browse.html
git status --short -- app       # 另有 ?? app/static/photo_detail_modal.js（本 phase 新建）
```

---

## 7. 常見陷阱

1. **點窗裡面也關掉**：暗色區的 click 監聽一定要判斷 `event.target === backdrop`。
   事件會從內層冒泡上來，不判斷就等於「點哪裡都關」。

2. **Esc 監聽掛在 document 上忘了拆／忘了判斷窗是否開著**：最省事的寫法是**只掛一次**
   （在 `pdInstall()` 裡），處理函式裡先檢查 `if (pdEl("pd-backdrop").hidden) return;`。
   不要每次開窗都 `addEventListener`——那會越疊越多，按一次 Esc 跑十遍。

3. **忘了清上一張的殘影**：第二次開窗如果沒清空 `#pd-image`／`#pd-fields`／`#pd-error`，
   會看到上一張的圖或上一次的紅字。**每次開窗都從乾淨狀態開始**。

4. **`items` 是陣列**：`body.metadata.items` 是 `["可樂", "洋芋片"]`。
   直接 `textContent = items` 會印出 `可樂,洋芋片`（逗號）——要用 `join("、")`。
   空陣列 `[]` 是 falsy 嗎？**不是**（`[]` 在 JS 裡是 truthy），所以要判 `items.length`。

5. **`content_time` 是 `null` 不是空字串**：`pd值或無()` 要同時處理 `null`／`undefined`／`""`／`[]`。

6. **改到 `folder_modal.js`**：那三個既有彈窗的檔案（`folder_modal.js`／`entity_modal.js`／
   `task_modal.js`）與 `classify_chain.js` 本 phase **一個字都不要動**。焦點管理、捲動鎖定
   要在自己的 `pd` 版本裡重寫一份小的（十幾行），不要去共用它們的內部函式。

7. **把 `.photo-static` 留著「以防萬一」**：不要。沒人用的 CSS 就是垃圾，
   下一個人會以為資料夾牆還有「不可點」的模式（使用者偏好：不留過渡產物）。

8. **順手把窗也掛到上傳頁**：不要。design4 §4.3 明講其他頁本輪不必掛；
   多掛一份就多一份要維護、要驗收的東西。
