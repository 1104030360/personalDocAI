# Phase 54：歸類彈窗窗頂加原圖

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。

> 🎯 **一句話目標：** 在歸類彈窗（`app/static/folder_modal.js`）的**最上面**加一張原圖，
> 讓人看得到「我現在在歸類的是哪一張」；順便把「稍後再說」底下那句說明
> 從「之後到瀏覽頁的待決定分頁完成歸類」改成指向**待決定頁**。
> **既有的四個函式（`fmAssign`／`fmClose`／`fmInstall`／`openFolderModal` 的既有邏輯）
> 行為一個字都不改。**

**為什麼要做這個：**
現在的歸類彈窗只有文字：一顆「採用「收據」」的按鈕、一個下拉、兩個輸入框。
從待決定牆點下去的時候，你剛剛看到的是一張**很小的縮圖**（正方形、被裁過、下面兩行說明），
彈窗一開就整面蓋住牆——**你要憑記憶決定這張要放哪裡**。
收據跟收據長得都很像，這件事實際上很難。

design5.md 的產品負責人在 grill 時明確選了方案 A：
**「待決定點開的介面仍是彈窗，窗頂加原圖」**（D2、§14 決策紀錄第 2 列）。
不是改成長頁表單（選項 B），也不是左右分欄（選項 C）——就只是多一張圖。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| 原圖 vs 縮圖 | 上傳時系統存兩份：**原圖**（`data/photos/{id}.jpg`，位元組原樣）與**縮圖**（`data/thumbs/`，長邊縮到 512 像素）。牆上用縮圖（快、排得整齊），彈窗要看清楚細節所以用原圖。網址分別是 `/photos/{id}/image` 與 `/photos/{id}/thumbnail` |
| 占位（placeholder） | 沒有圖可以顯示時，畫一塊灰底方塊寫「無原圖」。**不假裝有圖、也不顯示瀏覽器那個破圖 icon**（design1.md §10 的一貫態度）。`style.css` 已經有 `.placeholder` 這個 class |
| `onerror`（載入失敗事件） | `<img>` 抓不到圖時瀏覽器會發出的事件。寫法是 `image.addEventListener("error", …)`。本 phase 用它做降級：先掛 `<img>`，載不到再換成占位 |
| `object-fit: contain` vs `cover` | 圖片要塞進一個固定大小的框時的兩種策略。`cover`＝填滿整個框、超出的部分裁掉（牆上的正方形格子用這個，排起來才整齊）；`contain`＝整張圖完整塞進去、四周留空（**這裡用這個，因為要看清楚**） |
| `vh` | 螢幕高度的百分之一。`max-height: 32vh` ＝「這張圖最高佔螢幕高度的 32%」 |
| 全站唯一一份 | `folder_modal.js` 這個檔案**三個地方都在用**：待決定頁（Phase 52 建的 `pending.html`）、瀏覽頁（`browse.html`，Phase 55 才會拿掉）、以及上傳／鏡頭桌面的三關鏈（`classify_chain.js` 呼叫它）。所以改它＝三個地方一起變 |

---

## 1. 對應 design5.md 章節

- **D2**（點開仍是彈窗，**窗頂多一張原圖**；產品負責人在三個方案中選 A）
- **§1.1**（推翻 design2.md D2 的文案「之後到瀏覽頁的待決定分頁完成歸類」
  → 改成到頂欄的待決定頁）
- **§1.2 被否決**（「待決定改成獨立長頁表單（選項 B）或左右分欄（選項 C）」——
  產品負責人選 A：沿用彈窗，只加原圖）
- **§6.2 第 2 段**（「歸類彈窗：`folder_modal.js` 窗頂加 `<img>`，src 用 `/photos/{id}/image`
  （沒原圖的舊資料灰底占位，與瀏覽牆相同）。**實體／待辦彈窗不必再放一次大圖。**
  「稍後再說」說明改成留在待決定頁。」）
- **§11 會動到的檔**（第 3 列 `app/static/folder_modal.js`｜甲｜窗頂原圖；稍後再說文案）
- **§12 階段甲驗收第 2 條**（點一張：**彈窗最上面是原圖**，下面仍是四個歸類出口）
- **§14 決策紀錄第 2 列**（待決定點開的介面：仍是彈窗，窗頂加原圖）

---

## 2. 前置條件

- **Phase 52 已完成**：`app/static/pending.html` 存在（本 phase 主要在那一頁驗收）。
- **Phase 53 已完成**：頂欄四格，點得到待決定頁（不然要自己打網址，驗收比較麻煩）。
- 開工基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q
```

  預期：**412 passed ＋ 0 skipped**。
  （⚠ 絕對不要同時跑兩份 pytest。）

- **待決定裡至少要有兩張照片**，而且最好是「一張有原圖、一張沒有」，
  才驗得到兩條路。先看看現況（唯讀查詢）：

```bash
psql -d PersonalDocAI -c \
  "SELECT p.id,
          p.original_path IS NOT NULL AS 有原圖,
          left(p.text, 24) AS 說明開頭
     FROM photo p JOIN folder f ON f.id = p.folder_id
    WHERE f.is_inbox
    ORDER BY p.id;"
```

  - 一張都沒有 → 到 `/ui/upload.html` 上傳一張、在抽屜窗按「稍後再說」。
  - 全部都「有原圖」（很可能，因為現行上傳一定會寫檔）→ **沒關係**，
    §4.6 會教你怎麼用「把檔案暫時改名」的方式驗降級那條路（改完記得改回來）。

- 服務是**開發模式**（`docker compose ps --no-trunc` 的 `COMMAND` 欄有 `--reload`），
  改 JS／CSS 存檔就生效。

---

## 3. 範圍

### 做

- 改 `app/static/folder_modal.js`：
  - 樣板 HTML 最上面加一個 `<div class="fm-image" id="fm-image"></div>`；
  - 新增兩個小函式 `fm畫占位()` 與 `fm畫圖(photoId)`；
  - `openFolderModal()` 開窗時呼叫 `fm畫圖(config.photoId)`；
  - 「稍後再說」底下那句 `fm-desc` 改文案。
- 改 `app/static/style.css`：新增一小段規則（四條——三條 `.fm-image…` 加一條 `#fm-title + .fm-option`，後者把 `.fm-option:first-of-type` 因插圖失配的既有效果接回來，見 §4.4）。
- 瀏覽器實操驗收——**特別要回頭驗上傳頁沒壞**（見 §3 下面那段警告）。

### ⚠ 這個檔是全站唯一一份，改它會同時影響三個地方

```text
                 app/static/folder_modal.js      ← 只有這一份
                    ▲          ▲          ▲
      ┌─────────────┘          │          └──────────────┐
      │                        │                         │
 pending.html            browse.html            classify_chain.js
 （Phase 52 建的         （Phase 55 之前         （上傳頁 upload.html
  待決定牆）              還有待決定分頁）        ＋ 鏡頭桌面 camera-desk.html
                                                 的三關彈窗鏈第一關）
```

**所以本 phase 改完，一定要回頭到上傳頁真的上傳一張、把三關鏈走完一次。**
這是本 phase 最重要的回歸檢查（§4.6 的第 8 項）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改 `fmAssign()`／`fmClose()`／`fmHide()`／`fmSetError()`／`fmSetBusy()`／`fmDetailText()` 的內容 | 那些是「怎麼打 API、錯誤怎麼顯示」的核心邏輯，本 phase 只加畫面。比照 Phase 26 美化時的做法（那次也是只動樣式與樣板，`fmAssign` 等四個函式零改動） |
| 動 `openFolderModal()` 既有的三段（①按鈕、②下拉、③清空輸入框） | 只在最前面**多加一行** `fm畫圖(config.photoId);`，其餘一字不動 |
| 改 `openFolderModal()` 的參數（例如加一個 `imageUrl` 或 `hasImage`） | 加參數就要同時改三個呼叫端（`pending.html`／`browse.html`／`classify_chain.js`），
本 phase 就變成改四個檔。用 `onerror` 降級可以做到一模一樣的效果、而且**呼叫端零改動** |
| 在實體彈窗（`entity_modal.js`）或待辦彈窗（`task_modal.js`）也放一張大圖 | design5 §6.2 明文：「實體／待辦彈窗**不必**再放一次大圖」。同一張圖連看三次是噪音 |
| 改 `classify_chain.js` | 那是「誰接誰」的鏈邏輯，本 phase 不碰。⚠ **但它裡面有一句過期文案**——見下一列 |
| 修 `classify_chain.js` 第 53 行（「已放進待決定區，之後到瀏覽頁的「待決定」分頁完成歸類。」）與 `upload.html` `pdf摘要()` 裡（「其餘頁留在待決定區，可到瀏覽頁的「待決定」分頁完成歸類。」）這兩句舊文案 | 那兩句寫在**結果卡片**上（上傳頁／鏡頭頁右邊那張卡），不在彈窗裡。design5 §11 把上傳頁與鏡頭頁的文案改寫排在 **Phase 68／69**。**本 phase 不動它們** —— 但要知道：Phase 55 把瀏覽頁的待決定分頁刪掉之後、一直到 Phase 68／69 改文案之前，那兩句話會指向一個不存在的分頁，是**已知的、有主的過期文案**（Phase 55 §7 陷阱 5 會再提醒一次，★G1 驗收時要當面向產品負責人交代「這是預期、Phase 68／69 才改」）。發現它不是 bug、不要順手改 |
| 加「上一張／下一張」「放大縮小」「下載原圖」 | design5 沒要求。不要過度設計 |
| 為這顆窗新增自動化測試 | 本專案前端慣例（Phase 23／24／31／33／39 皆然）：純前端零新增自動化測試，改用瀏覽器實操驗收。本 phase 顆數維持 **412** |
| 改 `style.css` 的 design tokens（新增色碼、字級、間距） | `style.css` 檔頭寫明它是全站唯一樣式來源、單一強調色。新規則一律只引用既有的 `var(--…)` |
| 用 `alert`／`innerHTML` 塞動態內容 | 全站鐵律 |

---

## 4. 實作步驟

### 4.1 改樣板 HTML：把圖放在**最上面**

- [ ] 打開 `app/static/folder_modal.js`，找到第 27 行開始的 `FOLDER_MODAL_HTML`，
      在 `<div class="fm-box" …>` 的**第一個子元素位置**（也就是 `<h3 id="fm-title">` **上面**）
      插入窗頂原圖那一小段（一個空的 `<div>` 加兩行註解）。
      改完的完整樣板長這樣（整段可直接取代原本的樣板）：

```javascript
const FOLDER_MODAL_HTML = `
<div class="fm-backdrop" id="fm-backdrop" hidden>
  <div class="fm-box" role="dialog" aria-modal="true" aria-labelledby="fm-title">
    <!-- 窗頂原圖（增量五 Phase 54／design5.md D2）：讓人看得到現在在歸類哪一張。
         內容由 fm畫圖() 每次開窗時重畫；沒有原圖就換成灰底占位。 -->
    <div class="fm-image" id="fm-image"></div>

    <h3 id="fm-title">要把這張照片放到<span class="fm-nowrap">哪個資料夾？</span></h3>

    <div class="fm-option" id="fm-primary-option">
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

    <div class="fm-option">
      <button type="button" id="fm-later">稍後再說</button>
      <p class="fm-desc">照片會留在「待決定」，之後在頂欄的「待決定」頁完成歸類。</p>
    </div>

    <p class="fm-error" id="fm-error"></p>
  </div>
</div>
`;
```

  這段樣板與改版前只有**兩處**不同：
  1. 最上面多了 `<div class="fm-image" id="fm-image"></div>`（含註解）；
  2. 「稍後再說」底下的 `fm-desc` 文案改了（見 §4.3）。

  ⚠ `<h3 id="fm-title">` 那一行**一個字都不要動**——裡面的
  `<span class="fm-nowrap">哪個資料夾？</span>` 有一顆既有測試在掃
  （`tests/integration/test_design4_error_paths.py::test_手機版遺失縮圖與中文斷行都有保護`
  斷言 `'<span class="fm-nowrap">哪個資料夾？</span>' in 分類彈窗原始碼`）。

### 4.2 新增兩個小函式

- [ ] 在 `fmDetailText()` 與 `fmAssign()` **中間**（也就是「畫面工具」與「打 API」的分界處）
      插入這兩個函式。整段照抄：

```javascript
// ---------- 窗頂原圖（增量五 Phase 54；design5.md D2／§6.2）----------

// 沒有原圖時畫的東西：灰底方塊寫「無原圖」。
// 不假裝有圖、也不讓瀏覽器顯示破圖 icon（design1.md §10 的一貫態度）。
// .placeholder 是 style.css 既有的 class（縮圖牆也是用它）；本函式不注入任何樣式，
// 顯示比例的微調在 style.css 新增的 .fm-image .placeholder 那一條（見 §4.4）。
function fm畫占位() {
  const box = fmEl("fm-image");
  box.textContent = "";
  const 占位 = document.createElement("div");
  占位.className = "placeholder";
  占位.textContent = "無原圖";
  box.appendChild(占位);
}

// 每次開窗都重畫一次（先清空，免得看到上一張的殘影）。
//
// 為什麼直接掛 <img> 再用 onerror 降級，而不是先打一支 API 問「有沒有原圖」：
//   ① 呼叫端零改動——openFolderModal() 的參數不必多一個欄位，
//      三個呼叫端（pending.html／browse.html／classify_chain.js）都不用改；
//   ② 這是強制決定窗，開窗要快。多打一支 API 就多一次等待；
//   ③ 與瀏覽牆同一套做法（照片卡 也是掛了 <img> 再 addEventListener("error", …)）。
//
// 什麼時候會走到占位那條路：
//   ‧ 遷移進來的舊照片（original_path 是 NULL）→ 端點回 404
//   ‧ 有路徑但磁碟檔被刪了 → 端點也回 404
// 兩種都會在開發者工具的 Network 分頁留下一筆 404，那是預期的，不是壞掉。
function fm畫圖(photoId) {
  const box = fmEl("fm-image");
  box.textContent = "";

  const image = document.createElement("img");
  image.src = "/photos/" + photoId + "/image";
  image.alt = "要歸類的這張照片";
  image.addEventListener("error", function () {
    // 開下一張時 box 會先被清空——這張圖若已被移出畫面，遲到的 error 不要再蓋台
    // （比照 photo_detail_modal.js 的 generation 守衛，用 isConnected 一行搞定）
    if (!image.isConnected) return;
    fm畫占位();
  });
  box.appendChild(image);
}
```

- [ ] 在 `openFolderModal(config)` 裡面，`fmConfig = config;` 的**下一行**加一行呼叫。
      改完的前四行長這樣：

```javascript
function openFolderModal(config) {
  fmInstall();
  fmConfig = config;

  // 窗頂原圖（Phase 54）：每次開窗都重畫，才不會看到上一張的殘影
  fm畫圖(config.photoId);

  // ① 那顆按鈕：只有「有可用建議」時才顯示（design2.md D5/D6——
  //    待決定分頁沒有持久化的建議、AI 建議是未分類時也不顯示，交給「稍後再說」）
  const 有建議 = !!config.primary;
  …（以下一字不動）
```

> **為什麼不用擔心它把鍵盤焦點吃掉**：`fmAfterOpen()` 是從
> `querySelectorAll("button, input, select")` 裡挑第一個看得見的元素來聚焦，
> `<img>` 與 `<div>` 都不在那個選擇器裡。**焦點行為完全沒變**——
> 開窗後焦點仍然落在①（或②的下拉，當①被隱藏時）。

### 4.3 「稍後再說」的說明文案

- [ ] 這一句在 §4.1 的完整樣板裡已經改好了。單獨列出來對照：

```text
舊：照片會留在「待決定」，之後到瀏覽頁的待決定分頁完成歸類。
新：照片會留在「待決定」，之後在頂欄的「待決定」頁完成歸類。
```

  **為什麼要改**：design5.md §1.1 正式推翻了 design2.md D2 的這句文案。
  Phase 55 會把瀏覽頁的待決定分頁**刪掉**——如果不改，這句話會指向一個不存在的地方。
  新句子同時交代了兩件事：東西留在待決定（沒有不見）、去哪裡找（頂欄那一格）。

### 4.4 `style.css` 新增 `.fm-image` 區塊

- [ ] 在既有的「詳情彈窗（`photo_detail_modal.js`…）」區塊**之前**、
      也就是「彈窗（folder／entity／task modal 共用 fm-* class）」那一段的**結尾**
      （`body.fm-open { overflow: hidden; }` 那一行之後）插入這一段：

```css
/* ══ 歸類彈窗窗頂的原圖（增量五 Phase 54；design5.md D2）═══════════════
   為什麼不直接共用下面的 .pd-image：詳情窗裡「只有一張圖要看」，
   所以那裡吃到 60vh 沒問題；歸類窗底下還有**四個一定要按得到的出口**，
   圖太高會把它們推到捲軸外——強制決定的窗（沒有 ×、不吃 Esc）最忌諱
   「看不到出口」。所以這裡另訂一個矮一點的上限。 */
.fm-image { margin-bottom: var(--sp-4); }

/* contain＝整張圖塞得下、不裁切。與縮圖牆的 cover 刻意不同：
   那裡是要排整齊，這裡是要看清楚這到底是哪一張。 */
.fm-image img {
  display: block;
  width: 100%;
  max-height: 32vh;
  object-fit: contain;
}

/* 既有的 .placeholder 是為縮圖牆的正方形格子寫的（aspect-ratio: 1 / 1）；
   這裡的圖是橫躺的，換成扁一點的比例才不會空出一大塊 */
.fm-image .placeholder { aspect-ratio: 16 / 9; }

/* .fm-option:first-of-type（style.css 既有的「①列免上框線」規則）的 first-of-type
   比的是「同層第一個 div」——fm-image 插進來之後，同層第一個 div 變成它，
   那條既有規則從此零匹配，①列會多出一條分隔線＋上內距（2026-08-25 核對時抓到的副作用）。
   用「標題的下一個兄弟」把同一件事接回來——注意**不能**寫 .fm-image + .fm-option：
   fm-image 與 ①列中間隔著 <h3 id="fm-title">，相鄰選擇器會被它擋住、永不匹配
   （2026-08-25 審查時抓到的第二層錯，以此版為準）。
   實體／待辦窗沒有 fm-image、也沒有 #fm-title，這條選不到它們，
   它們的①列仍由原本的 :first-of-type 規則處理。 */
#fm-title + .fm-option { padding-top: 0; border-top: none; }
```

  **四條規則、零新增 token**——顏色、間距全部引用既有的 `var(--…)`。
  （第四條是 2026-08-25 核對計畫時補的：沒有它，①列上方會多一條沒人解釋的分隔線。）

### 4.5 讓改動生效

- [ ] 靜態檔每次請求現讀，存檔後按 `Cmd`＋`Shift`＋`R` 強制重新整理就生效
      （JS 與 CSS 特別容易被瀏覽器快取，所以這裡建議直接用強制重整）。
- [ ] 如果畫面完全沒變：`docker compose ps --no-trunc` 看 `COMMAND` 欄有沒有 `--reload`。
      沒有＝常駐模式，程式在映像裡、看不到你改的檔。

### 4.6 瀏覽器實操驗收（本 phase 的主要驗收方式）

- [ ] **1. 待決定頁點一張有原圖的照片** → 彈窗跳出：
      **最上面是一張看得清楚的原圖**，圖下面才是標題「要把這張照片放到哪個資料夾？」，
      再下面是四個出口（①／②／③／④）。
- [ ] **2. 四個出口全部按得到**：窗裡往下捲（或不必捲）就看得到「稍後再說」那一顆。
      **圖沒有把出口擠到看不見的地方。**
      （視窗高度 700px 左右的筆電螢幕是最容易出問題的情境，特別確認一下。）
- [ ] **3. 圖沒有變形**：長方形的照片不會被拉扁或壓扁（`object-fit: contain` 生效）。
- [ ] **4.「稍後再說」的說明文字**已經是新版：
      「照片會留在「待決定」，之後在頂欄的「待決定」頁完成歸類。」
- [ ] **5. 強制決定沒有被破壞**（design2.md D1）：按 `Esc`、點暗色區 → **都不會關**。
      多了一張圖不代表多了一個出口。
- [ ] **6. 連續開兩張不會看到殘影**：點第一張 → 按「稍後再說」→ 實體窗按「不釘，繼續」
      → 頁面重載 → 點**另一張** → 窗頂是**新那一張**的圖，不是上一張。
- [ ] **7. 沒有原圖的降級**（兩種製造方式，擇一）：
      - **方式 A（有舊照片的話）**：§2 那條查詢裡「有原圖」是 `f` 的照片，
        直接點它 → 窗頂是灰底「無原圖」，四個出口照常。
      - **方式 B（全部都有原圖時）**：挑待決定裡的一張，記下 id，把檔案暫時改名：

```bash
cd /Users/linjunting/personalDocAI
ls data/photos/ | head            # 先看檔名長什麼樣（{id}.jpg 或 {id}.png）
mv data/photos/41.jpg data/photos/41.jpg.bak     # ← 41 換成你要驗的 id
```

        重新整理待決定頁 → 點那張 → **窗頂是灰底「無原圖」**，
        而且**不是**破圖 icon、也**不是**整個窗打不開。
        ⚠ **驗完立刻改回來**：

```bash
mv data/photos/41.jpg.bak data/photos/41.jpg
```

        （`data/` 不入版控，全世界只有這一份，改名之後一定要記得改回去。）
- [ ] **8. ★ 回歸：上傳頁的三關鏈沒壞**（本 phase 最重要的一項——`folder_modal.js` 是共用的）：
      到 `https://127.0.0.1:8000/ui/upload.html` 上傳一張照片
      → 抽屜窗跳出，**窗頂也有那張圖**（上傳的照片當然有原圖）
      → 按①或②定案 → 實體窗跳出（**實體窗裡沒有大圖**，只有文字選項）
      → 按「不釘，繼續」→（有待辦建議才）待辦窗 → 整條鏈走完，右邊結果卡照常更新。
      （本機模型看一張圖要 1〜5 分鐘；想快就先把頁首的「AI 模型」開關撥到「雲端」。）
- [ ] **9. 回歸：瀏覽頁的待決定分頁也一樣**（Phase 55 之前它還在）：
      `https://127.0.0.1:8000/ui/browse.html` → 點一張 → 窗頂有圖、四個出口都在。
- [ ] **10. 回歸：資料夾牆的唯讀詳情窗沒被波及**：
      `https://127.0.0.1:8000/ui/browse.html?tab=folders` → 點進一個資料夾 → 點一張照片
      → 跳出來的是**唯讀詳情窗**（右上角有 ×、可以按 Esc 關、**沒有**任何改資料夾的按鈕）。
      那顆窗是 `photo_detail_modal.js`，與本 phase 無關，長相不該有任何改變。
- [ ] **11. 窄螢幕**：把視窗縮到 400px 寬 → 圖跟著縮、四個出口仍然按得到。
- [ ] **12. Console 乾淨**：除了「刻意製造的 404 原圖」那一次之外，沒有紅色錯誤。

---

## 5. ASCII 圖：彈窗改版前後的版面

```text
 ┌──────────── 改版前（Phase 54 之前）────────────┐
 │                                                │
 │   要把這張照片放到哪個資料夾？                 │
 │   ────────────────────────────────────────     │
 │   ① [ 採用「收據」 ]                           │
 │      發票、消費憑證、購物明細。                │
 │   ────────────────────────────────────────     │
 │   ② 改選其他現有資料夾：                       │
 │      [ 飲食 ▾ ] [ 歸到這個資料夾 ]             │
 │   ────────────────────────────────────────     │
 │   ③ 自建新資料夾：                             │
 │      [名稱____] [說明____] [ 建立並歸類 ]      │
 │   ────────────────────────────────────────     │
 │   ④ [ 稍後再說 ]                               │
 │      照片會留在「待決定」，之後到**瀏覽頁的**   │
 │      **待決定分頁**完成歸類。                   │
 │                                                │
 └────────────────────────────────────────────────┘
      ↑ 全是文字。你剛剛只看到一張很小的縮圖，
        現在要憑記憶決定「這張到底是什麼」。
        收據跟收據長得都一樣。

                        │
                        │  ★ Phase 54
                        ▼

 ┌──────────── 改版後（Phase 54 之後）────────────┐
 │  ┌──────────────────────────────────────────┐  │
 │  │                                          │  │  ← ★ 新增
 │  │            原     圖                     │  │    <div class="fm-image">
 │  │      /photos/{id}/image                  │  │    max-height: 32vh
 │  │      object-fit: contain（不裁切）        │  │    contain（整張看得到）
 │  │                                          │  │
 │  └──────────────────────────────────────────┘  │
 │                                                │
 │   要把這張照片放到哪個資料夾？                 │
 │   ────────────────────────────────────────     │
 │   ① [ 採用「收據」 ]                           │
 │      發票、消費憑證、購物明細。                │
 │   ────────────────────────────────────────     │
 │   ② 改選其他現有資料夾：                       │
 │      [ 飲食 ▾ ] [ 歸到這個資料夾 ]             │
 │   ────────────────────────────────────────     │
 │   ③ 自建新資料夾：                             │
 │      [名稱____] [說明____] [ 建立並歸類 ]      │
 │   ────────────────────────────────────────     │
 │   ④ [ 稍後再說 ]                               │
 │      照片會留在「待決定」，之後在**頂欄的**     │  ← ★ 文案改了
 │      **「待決定」頁**完成歸類。                 │
 │                                                │
 │  ⚠ 仍然沒有 ×、不吃 Esc、點暗色區也不關         │
 │    （design2.md D1 強制決定，本 phase 不動）    │
 └────────────────────────────────────────────────┘
      ↑ 多了圖，出口一個沒少、行為一個沒改。


 為什麼上限是 32vh 而不是跟詳情窗一樣的 60vh
 ──────────────────────────────────────────────────────────
   .fm-box 的規則是 max-height: 90vh; overflow-y: auto;
   （窗最高佔 90% 螢幕，超過就在窗裡捲）

     60vh 的圖                       32vh 的圖
   ┌────────────┐ 90vh 上限        ┌────────────┐ 90vh 上限
   │            │                  │   圖 32vh  │
   │   圖 60vh  │                  ├────────────┤
   │            │                  │ 標題       │
   │            │                  │ ① 採用     │
   ├────────────┤                  │ ② 改選     │
   │ 標題       │                  │ ③ 自建     │
   │ ① 採用     │                  │ ④ 稍後再說 │ ← 看得到
   │ ② 改選     │                  └────────────┘
   └╌╌╌╌╌╌╌╌╌╌╌╌┘ ← 捲軸下面還有
     ③ ④ 掉到看不見的地方
     強制決定的窗看不到出口 ＝ 使用者以為卡住了


 這個檔是全站唯一一份，改一次三處一起變
 ──────────────────────────────────────────────────────────
                 app/static/folder_modal.js
                    ▲          ▲          ▲
      ┌─────────────┘          │          └──────────────┐
 pending.html            browse.html            classify_chain.js
 （Phase 52 建的         （待決定分頁，          （被 upload.html 與
  待決定牆）              Phase 55 才刪）         camera-desk.html 用）

   ✗ entity_modal.js（實體窗）與 task_modal.js（待辦窗）**不放大圖**
     ——design5 §6.2 明文：同一張圖連看三次是噪音
```

---

## 6. 驗收清單

- [ ] **樣板裡有圖、而且在標題上面**：

```bash
cd /Users/linjunting/personalDocAI
grep -n 'id="fm-image"\|id="fm-title"' app/static/folder_modal.js
```

  預期：兩行都找得到，而且 **`fm-image` 那一行的行號比 `fm-title` 小**（圖在標題上面）。

- [ ] **兩個新函式都在，而且圖的網址對**：

```bash
grep -n "function fm畫占位\|function fm畫圖\|/image" app/static/folder_modal.js
```

  預期：看得到 `function fm畫占位()`、`function fm畫圖(photoId)`，
  以及 `image.src = "/photos/" + photoId + "/image";`。

- [ ] **開窗時有呼叫它**：

```bash
grep -n "fm畫圖(config.photoId)" app/static/folder_modal.js
```

  預期：恰好一行（在 `openFolderModal` 裡）。

- [ ] **文案改了、舊句子沒殘留在這個檔**：

```bash
grep -n "頂欄的「待決定」頁" app/static/folder_modal.js
grep -n "瀏覽頁的待決定分頁" app/static/folder_modal.js \
  || echo "OK：folder_modal.js 裡沒有舊文案"
```

  預期：第一行找得到、第二行印出 `OK：…`。
  ⚠ **不要**把這條 grep 擴大到整個 `app/static/`——`classify_chain.js` 與 `upload.html`
  裡還有類似的句子，那兩處是 Phase 68／69 的事（見 §3 的「明確不做」表）。

- [ ] **既有四個函式一個字都沒動**（用 `git diff` 逐行看，這是本 phase 最該親眼確認的一項）：

```bash
git diff -- app/static/folder_modal.js
```

  預期：diff 裡**只有**四塊變動——
  ① 樣板最上面多了 `fm-image` 那個 div（含註解）；
  ② 「稍後再說」那句 `fm-desc` 的文案；
  ③ 多出 `fm畫占位()` 與 `fm畫圖()` 兩個函式；
  ④ `openFolderModal` 裡多一行 `fm畫圖(config.photoId);`（含註解）。
  `fmAssign`／`fmClose`／`fmHide`／`fmInstall`／`fmSetError`／`fmSetBusy`／
  `fmDetailText`／`fmAfterOpen`／`fmAfterClose` 的內容**不該出現在 diff 裡**。

- [ ] **CSS 只多了四條規則、沒有新色碼**：

```bash
git diff -- app/static/style.css
grep -n "fm-image" app/static/style.css
```

  預期：diff 只有新增的那一段；grep 看得到三條 `.fm-image…` 規則
  （`.fm-image`／`.fm-image img`／`.fm-image .placeholder`），
  第四條是 `#fm-title + .fm-option`（不含 fm-image 字樣，另用
  `grep -n '#fm-title + .fm-option' app/static/style.css` 驗恰一行）。
  新增的行裡**不該**出現任何 `#` 開頭的色碼或寫死的 `px`／`rem`（`32vh` 除外，那是刻意的上限）。

- [ ] **既有測試全綠、顆數不變**：

```bash
source .venv/bin/activate
pytest -q
```

  預期：**412 passed ＋ 0 skipped**（本 phase 純前端、零新增測試）。
  特別注意 `tests/integration/test_design4_error_paths.py` 那幾顆掃 `folder_modal.js`
  原始碼的測試仍綠（它們斷言 `<span class="fm-nowrap">哪個資料夾？</span>` 還在、
  以及檔案裡沒有 `"請求失敗：" + error` 這種會洩漏原始例外的字串）。

- [ ] **端點仍然是 20**（本 phase 純前端、不該有任何 API 變化——這一條就是客觀證據）：

```bash
curl -k -s https://127.0.0.1:8000/openapi.json \
  | python3 -c "import json,sys; p=json.load(sys.stdin)['paths']; print(sum(len(v) for v in p.values()))"
```

  預期：`20`。
  （算法與 `tests/integration/test_ask_three_paths.py::test_端點數不變` 一致：
  把每個路徑底下的方法數加總，不是數 `paths` 有幾個 key。）

- [ ] **只動了兩個檔**：

```bash
git status --short -- app
```

  預期：` M app/static/folder_modal.js`、` M app/static/style.css`；
  Phase 52〜53 還沒 commit 的話，另外會看到它們留下的 `pending.html` 與
  四個 `M app/static/*.html`（已 commit 就不會出現——兩種都對，
  重點是**本 phase 新增的只有前兩行**）。
  **不該**出現 `classify_chain.js`、`entity_modal.js`、`task_modal.js`、`photo_detail_modal.js`。

- [ ] §4.6 的 12 項瀏覽器實操逐項打勾（**第 8 項「上傳頁三關鏈」不可跳過**）、Console 乾淨。

- [ ] **`data/` 沒有被留下改名的檔**（如果 §4.6 第 7 項用了方式 B）：

```bash
ls data/photos/*.bak 2>/dev/null && echo "⚠ 還有檔案沒改回來！" || echo "OK：沒有 .bak 殘留"
```

---

## 7. 常見陷阱

1. **把圖放在 `<h3>` 下面**：那就不是「窗頂」了。design5 §12 階段甲驗收第 2 條寫得很明確：
   「彈窗**最上面**是原圖，下面仍是四個歸類出口」。`fm-image` 必須是 `.fm-box` 的第一個子元素。

2. **忘了每次開窗清空 `#fm-image`**：第二次開窗會看到上一張的圖（或兩張疊著）。
   `fm畫圖()` 第一行的 `box.textContent = "";` 不能省。
   （`fm畫占位()` 裡也有同一行——因為 `onerror` 可能在 `<img>` 已經塞進去之後才觸發。）

3. **想用 `GET /photos/{id}` 先問「有沒有原圖」再決定要不要畫**：不要。
   那會讓每次開窗都多等一次網路往返，而且 `openFolderModal` 就得變成 `async`——
   三個呼叫端的行為都會跟著變。`onerror` 一行就解決，而且與瀏覽牆的做法一致。

4. **看到 Network 分頁有一筆 `/photos/41/image` 404 就以為壞了**：
   那是**預期的降級路徑**（舊照片沒有 `original_path`，或檔案被刪了）。
   畫面上要看到的是灰底「無原圖」，不是破圖 icon、更不是整個窗打不開。
   實務上待決定牆裡的照片幾乎都有原圖（現行上傳一定寫檔），所以這條路很少走到。

5. **圖太高把「稍後再說」擠出畫面**：`max-height` 一定要設，而且**不要**照抄詳情窗的 `60vh`。
   詳情窗裡只有一張圖要看；歸類窗底下有四個必須按得到的出口，而且這是**關不掉的窗**——
   看不到出口的使用者只能重新整理頁面。理由已經寫在 CSS 的註解裡，不要「順手優化」把它改大。

6. **順手在實體窗也加一張圖**：不要。design5 §6.2 明文說不必。
   而且實體窗是「釘上就繼續、窗不關」的多輪互動，圖只會一直把選項往下推。

7. **順手去改 `classify_chain.js` 那句「之後到瀏覽頁的『待決定』分頁完成歸類」**：
   不要。那句寫在**結果卡片**上（上傳頁右邊那張卡），不在彈窗裡，
   而且它的主人是 Phase 68／69（上傳頁與鏡頭頁的文案改寫）。
   本 phase 的 `git status` 只准出現兩個檔。

8. **改完只驗了待決定頁**：`folder_modal.js` 是**三個地方共用**的。
   §4.6 第 8 項（上傳頁三關鏈）是本 phase 最重要的回歸檢查，不要跳。
   最容易壞的方式是「複製整份樣板時不小心少了一個 `</div>`」——
   待決定頁看起來還好，上傳頁的鏈卻在第二關卡住。

9. **`alt` 寫成照片的說明文字**：`openFolderModal` 的 config 裡**沒有** `text` 欄位
   （呼叫端只傳 `photoId`／`folders`／`primary`／`primaryVerb`／兩個 callback）。
   硬要拿就得改參數，那是 §3 明確不做的事。固定字串 `"要歸類的這張照片"` 就夠了。

10. **以為多了 `<img>` 會搶走鍵盤焦點**：不會。`fmAfterOpen()` 只在
    `button, input, select` 裡找第一個看得見的元素。`<img>`／`<div>` 都不在那個清單裡。
    （反過來說：**不要**給那張圖加 `tabindex`——那才會真的插隊。）

11. **改了 CSS 卻沒生效**：CSS 最容易被瀏覽器快取。先 `Cmd`＋`Shift`＋`R`；
    還是沒變就 `docker compose ps --no-trunc` 確認是不是常駐模式（程式在映像裡）。
