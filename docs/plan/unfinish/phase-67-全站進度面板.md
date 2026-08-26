# Phase 67：全站進度面板

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 新建**全站唯一一份** `app/static/progress_panel.js`，掛在五個頁面上；
> 它每 2 秒問一次伺服器「現在有哪些檔還在處理」，把結果畫成右下角的一小塊面板，
> 順便把頂欄的「待決定（N）」一起更新。

**為什麼要做這個：**

階段乙（Phase 62／63）把上傳與快門改成 **202「已收下」**——HTTP 立刻回，VLM 分析交給背景的 worker。
好處是不會再卡住，但代價是**畫面上什麼都看不到**：你選了三個檔，頁面說「已收下」，然後就沒了。
照片什麼時候會出現在待決定？失敗了嗎？現在完全不知道。

Phase 64 已經做好資料來源 `GET /ingest-jobs`（回「還沒結束的工作」＋「待決定有幾張」）。
本 phase 就是把那支端點畫出來，讓「還在跑的工作」變成看得見的東西。

**這一份要是全站唯一一份**（design5.md §6.1 明文：「不要四個 HTML 各寫一套 `setInterval`」）。
理由很實際：輪詢的規則（多久一次、失敗怎麼辦、頁面被切到背景怎麼辦）只有一個地方寫，
以後要調整就只調一個檔；五份複製品一定會慢慢走鐘成五種行為。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **輪詢（polling）** | 伺服器沒辦法主動通知瀏覽器（除非開 WebSocket），所以換瀏覽器自己「每隔一段時間問一次」：「有變化嗎？」「有變化嗎？」。土法煉鋼但極穩，本專案的規模用這個就夠。 |
| **`setInterval(函式, 毫秒)`** | 瀏覽器內建的計時器：每隔幾毫秒就跑一次那個函式。回傳一個編號，之後用 `clearInterval(編號)` 可以叫停。 |
| **`clearInterval(編號)`** | 停掉上面那個計時器。編號要自己記住，所以程式裡會有一個 `ppTimer` 變數存它。 |
| **指數退避（exponential backoff）** | 連線失敗時，不要固執地每 2 秒重試——第 1 次失敗等 4 秒、第 2 次等 8 秒、第 3 次等 16 秒……越失敗等越久（上限 30 秒）。伺服器正在重啟時，這樣才不會被幾百個失敗請求淹沒，主控台也不會被洗版。 |
| **`document.hidden`** | 瀏覽器告訴你「這個分頁現在是不是在背景」。切到別的分頁、或把視窗縮到最小，它就是 `true`。 |
| **`visibilitychange` 事件** | 上面那個值變了的時候會觸發。用來做「回到這個分頁就立刻更新一次」。 |
| **競態（race condition）** | 兩件事同時發生、而且誰先誰後不一定，結果就跟著不一定。本 phase 的例子：上一次輪詢的回應還在路上，下一次輪詢又發出去了；如果第一次的回應**晚**回來，畫面就會被舊資料蓋掉。解法是「上一次還沒回來就不發下一次」（程式裡的 `ppInFlight` 旗標）。 |
| **`hidden` 屬性** | HTML 元素加上 `hidden` 就不顯示。JS 寫 `element.hidden = true / false` 就能收合／展開，比操作 `style.display` 好讀。⚠ 但只要 CSS 給那個元素設過 `display`（例如 `display: grid`），`hidden` 就會失效——所以 CSS 要另外補一條 `[hidden] { display: none; }`（`.fm-option` 踩過同一個坑）。 |
| **`z-index`** | 「誰疊在誰上面」的層號，數字大的在上面。只對有 `position`（非 `static`）的元素有效。 |
| **樂觀更新（optimistic update）** | 使用者按下按鈕，畫面**先**照「一定會成功」的樣子改，再送請求出去。好處是感覺很快；代價是失敗時要有辦法補救。本 phase 的 × 就是這樣做（失敗了下一次輪詢那一列會自己長回來）。 |

---

## 1. 對應 design5.md 章節

- **D8**（進度面板全站：每一頁右下角同一份；換頁／重新整理靠伺服器上的任務清單長回來）
- **D9**（成功列消失、頂欄「待決定（N）」+1；失敗列留下可按 × 關掉；清單空了收起面板）
- **D3／D4**（多檔與連拍是這個面板存在的理由——Phase 68／69 才做，但面板要先在）
- **D13**（上傳當下不開歸類鏈：所以「事情有沒有在跑」只剩這個面板會講）
- **§2 流程圖**的最後兩條分支（成功 → 進度列消失、待決定 +1；失敗 → 進度列留下、× 可關掉）
- **§4.3 JobStore**（清單只回 `queued`／`analyzing`／`retrying`／`failed`；**成功＝刪掉那筆 job**，
  所以「前端不必自己過濾 success」；`GET /ingest-jobs` 同時帶 `pending_count`）
- **§5 API 契約**（`GET /ingest-jobs` 回 `{jobs, pending_count}`；
  `POST /ingest-jobs/{job_id}/dismiss` 只對 `failed`，204／404／409）
- **§6.1 頂欄**（階段丙起 N 改由全站 JS 輪詢 `GET /ingest-jobs` 更新，**不要四個 HTML 各寫一套 `setInterval`**）
- **§6.6 進度面板**（四種狀態各顯示什麼；全部結束→收起；重新整理後進行中與未 dismiss 的失敗要還在）
- **§8 錯誤表第 9 列**（dismiss 一筆還在跑的 job → 409）
- **§9 測試策略**末段（前端進度面板**不新增** Playwright 自動化；改用瀏覽器實操驗收）
- **§12 階段丙**驗收前三條（多列進度、成功列自己消失 N 加上去、失敗列 × 關掉後面板收起、換頁還在）

---

## 2. 前置條件

**必須先完成的 phase：**

| Phase | 為什麼需要 |
|---|---|
| **64** | `GET /ingest-jobs` 與 `POST /ingest-jobs/{job_id}/dismiss` 是本面板唯一的資料來源與唯一的動作。沒有它，本 phase 一行都寫不下去。 |
| **62** | `POST /photos` 已經回 202 並真的建出 job，否則清單永遠是空的、驗收看不到東西。 |
| **57／59** | JobStore 與 `run_ingest_job()`——驗收時要靠它們把一筆 job 從 queued 推到 failed。 |
| **52／53** | `/ui/pending.html` 存在、五頁頂欄已經是四格（本 phase 要接管其中「待決定（N）」的數字）。 |
| **55** | `browse.html` 已經拿掉待決定 tab（否則會有兩個地方顯示 N，很容易對不起來）。 |
| **★ G2** | design5 §0 的閘門：階段乙已由產品負責人驗收通過。前端要靠乙的 API 契約穩定才動得了。 |

**開工前先做這四件事：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 抄下測試基線。本 phase 會 +7 顆（新檔 7 顆；test_nav_header.py 是一換一、不加顆）。
pytest -q          # 把 "N passed" 的 N 抄在這裡 → N = ______

# ①.5 抄下開工前的工作區狀態（§6.1 最後一項要拿它對「本 phase 動了哪些檔」——
#      增量五的各 phase 若尚未 commit，git status 會混著前面 phase 的變更，
#      只有「前後快照相減」才看得出本 phase 自己動了什麼）
git status --short -- app tests > /tmp/p67-before.txt

# ② 確認服務活著，而且 GET /ingest-jobs 真的回得出東西
docker compose ps --no-trunc
curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
#   預期形狀（jobs 可能是空陣列，那正常）：
#   { "jobs": [], "pending_count": 3 }
#   ⚠ 如果這裡 404，代表 Phase 64 沒完成，先回頭補，不要硬寫前端。

# ③ 確認五個頁面都在
ls app/static/upload.html app/static/pending.html app/static/browse.html \
   app/static/ask.html app/static/camera-desk.html
```

> ⚠ **網址是 `https://` 不是 `http://`**（增量四起容器固定帶 SSL 憑證）。
> `curl` 對自簽憑證要加 `-k`；瀏覽器開 `https://localhost:8000` 不會跳警告（這台 Mac 已 `mkcert -install`）。

---

## 3. 範圍

### 做

1. 新建 `app/static/progress_panel.js`（**全站唯一一份**，全域名稱一律 `pp` 前綴）。
2. 五個頁面各加**一行** `<script src="/ui/progress_panel.js"></script>`：
   `upload.html`／`pending.html`／`browse.html`／`ask.html`／`camera-desk.html`。
3. `app/static/style.css` 新增「入庫進度面板」區塊（`pp-` 前綴），並幫既有 `.fm-backdrop` 補一行 `z-index`。
4. 把 Phase 53 貼在五頁 `</header>` 下方的**過渡計數片段**（各自打 `GET /folders` 算 N）
   **整組刪掉**，改由本面板統一更新 `#nav-pending-count`。
5. 把 `tests/integration/test_nav_header.py` 裡的 `test_五頁都有同一份待決定計數片段`
   **原地換成** `test_五頁的計數片段已交棒給進度面板`（換掉，**不是新增**，那個檔的顆數不變）。
6. 新建 `tests/integration/test_progress_panel_contract.py`（7 顆原始碼字串契約測試）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 在四個 HTML 各寫一套 `setInterval` | design5 §6.1 明文禁止。輪詢規則只准有一份 |
| 面板裡放「再試一次」按鈕 | design5 §3「不做」第 2 條：自動 3 次已經做完；要重來就重新選檔／重拍 |
| 顯示成功的那一列（打勾、綠字、3 秒後淡出） | D9＋§1.2「成功列留在進度面板當第二個待決定」已被否決。成功的去處就是待決定 |
| 前端自己過濾 `status === "success"` | §4.3：**成功＝伺服器刪掉那筆 job**，`GET /ingest-jobs` 根本不會回來。前端多寫一層過濾＝寫一段永遠不會執行的死碼 |
| 用 `DELETE /ingest-jobs/{id}` 關掉失敗列 | Phase 37 釘死「openapi 零 DELETE」，§1.2 也明列否決。一律 `POST …/dismiss` |
| 用 `alert`／`confirm`／`prompt` 報錯 | 全站鐵律（Phase 23 起）。而且面板是**背景資訊**，跳原生對話框打斷手上的事更糟 |
| 把面板做成可拖曳／可縮小／可釘選 | design5 沒要求。不要過度設計 |
| 顯示百分比進度條 | 我們沒有百分比可以顯示——VLM 看一張圖是黑箱，只知道「第幾次嘗試」「第幾頁」 |
| 用 WebSocket 即時推送取代輪詢 | §1.2 沒明寫，但 2 秒輪詢一支輕量 API 對單人本機系統綽綽有餘；WebSocket 要多一條連線生命週期要管 |
| 掛到 `camera-phone.html` | 手機頁是全螢幕取景，右下角面板會壓到快門（`.cp-controls` 就在下緣）。手機端的進度是 **Phase 69 的窄條**，不是這一份面板。詳見下面 §4.7 的「D8 與 §6.5 的落差」 |
| 為面板寫 Playwright 自動化測試 | design5 §9 明文、Phase 14／23／24／31／33／39 的一貫慣例：純前端零新增自動化，改用瀏覽器實操驗收 ＋ 少量原始碼字串契約測試 |
| 順手美化其他頁 | 樣式只加新的 `pp-` 區塊與一行 `z-index`。其餘 `style.css` 一個字不動 |

---

## 4. 實作步驟

> 全程順序：**先寫死不會動的樣板（HTML／CSS）→ 再寫輪詢 → 最後接頂欄 N → 補契約測試。**
> 這四步各自都能在瀏覽器上看到結果，卡住時很容易知道是哪一段壞的。

### 4.1 先看一眼資料長什麼樣（不寫程式，只讀）

- [ ] 用 `curl` 實際看一次 `GET /ingest-jobs` 的形狀（Phase 64 的契約）：

```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
```

回應長這樣（`jobs` 每一筆的鍵由 `app/schemas/ingest_job.py` 的 `IngestJobOut` 決定）：

```json
{
  "jobs": [
    {
      "job_id": "7f3a1c9e2b4d4f0a8c6e5d3b2a1f0e9d",
      "filename": "receipt.jpg",
      "content_type": "image/jpeg",
      "status": "analyzing",
      "attempt": 2,
      "page_count": null,
      "pages_done": 0,
      "error": null
    },
    {
      "job_id": "1a2b3c4d5e6f708192a3b4c5d6e7f809",
      "filename": "scan.pdf",
      "content_type": "application/pdf",
      "status": "retrying",
      "attempt": 3,
      "page_count": 5,
      "pages_done": 2,
      "error": null
    }
  ],
  "pending_count": 4
}
```

- [ ] **記住三件事，後面全部靠它們：**
  1. **成功的 job 不在這裡。** 伺服器一成功就 `delete(job_id)`（§4.3）。所以前端只要「畫出回來的每一筆」就對了，**不必也不可以**寫 `if (job.status === "success")` 之類的判斷——那是一段永遠不會執行的死碼。
  2. **`pages_done` 是「做完幾頁」**（含跳過的），所以**現在正在看**的是第 `pages_done + 1` 頁。
  3. **`page_count` 未拆頁前是 `null`**。單張圖也是 `null`。所以「有沒有 `page_count`」就等於「是不是已知頁數的 PDF」。

### 4.2 新建 `app/static/progress_panel.js`

- [ ] 建檔，整份照抄（這是完整可執行的檔案，沒有省略）：

```javascript
/* 全站入庫進度面板（design5.md D8／D9／§6.1／§6.6）——全站只有這一份。

   掛在五頁：upload.html / pending.html / browse.html / ask.html / camera-desk.html。
   ⚠ 刻意不掛 camera-phone.html：那一頁是全螢幕取景，右下角會壓到快門；
     手機端的進度是 Phase 69 的窄條（cp-bar），不是這一份面板。

   它做三件事，每 PP_POLL_MS 毫秒一輪：
     ① GET /ingest-jobs           → 一次拿回 jobs 與 pending_count
     ② 更新右下角面板（#pp-panel）  → 四種狀態，成功的根本不會回來
     ③ 更新頂欄「待決定（N）」      → 五頁共用同一個數字來源

   ⚠ 全站鐵律：不用 alert／confirm／prompt；動態文字一律 textContent；
     本檔的節點全部用 createElement 造，完全不用「字串拼 HTML」的那個屬性
     （契約測試會掃：那個屬性名在本檔一次都不准出現、連註解都算，
      所以這裡刻意不把它寫出來）。
     樣式全部在 /ui/style.css 的「入庫進度面板」區塊，本檔不注入任何樣式。

   對外只暴露四個函式（前綴 pp，比照 folder_modal.js 的 fm／entity_modal.js 的 em）：
     ppStart()          開始輪詢（可重複呼叫；已經在跑就只是立刻多打一次）
     ppStop()           停止輪詢（目前沒有頁面需要，留著是為了對稱與除錯）
     ppRender(jobs)     把一份 jobs 陣列畫到面板上（輪詢內部用；也方便手動測）
     ppDismiss(jobId)   關掉一列失敗的工作
*/

// ── 契約常數（design5 §6.1：約 2 秒）───────────────────────────────
const PP_POLL_MS = 2000;
// 連線失敗時最多退避到幾毫秒才恢復輪詢（見 pp輪詢失敗）
const PP_MAX_BACKOFF_MS = 30000;

let ppTimer = null;          // setInterval 的編號；null＝沒在跑
let ppReady = false;         // 面板的 DOM 只裝一次
let ppInFlight = false;      // 上一次請求還沒回來（避免競態，見檔頭說明）
let ppQuietUntil = 0;        // 退避到這個時間點之前都不要打（Date.now() 毫秒）
let ppFailStreak = 0;        // 連續失敗幾次（算退避用）
let ppLoggedFailure = false; // 主控台只印一次，不要洗版

function ppEl(id) {
  return document.getElementById(id);
}

// ── 面板的 DOM：只有三個節點，全部用 createElement 造（理由見檔頭）──
function ppInstall() {
  if (ppReady) return;

  const panel = document.createElement("section");
  panel.className = "pp-panel";
  panel.id = "pp-panel";
  panel.hidden = true;                       // 沒有工作時完全不存在於畫面上
  panel.setAttribute("aria-label", "入庫進度");
  // polite＝有變化時螢幕報讀軟體會念，但會等使用者手邊的事講完，不打斷
  panel.setAttribute("aria-live", "polite");

  const head = document.createElement("h2");
  head.className = "pp-head";
  head.id = "pp-head";
  head.textContent = "處理中";
  panel.appendChild(head);

  const list = document.createElement("ul");
  list.className = "pp-list";
  list.id = "pp-list";
  panel.appendChild(list);

  // × 用事件委派：整份清單只掛一個監聽，列是動態長出來的
  // （與 browse.html 縮圖牆同一個作法）
  list.addEventListener("click", function (event) {
    const 按鈕 = event.target.closest(".pp-x");
    if (!按鈕 || !按鈕.dataset.jobId) return;
    ppDismiss(按鈕.dataset.jobId);
  });

  document.body.appendChild(panel);
  ppReady = true;
}

// ── 一列的兩行文字（design5 §6.6 的表格）─────────────────────────────

// 第一行：檔名。PDF 拆完頁之後把總頁數帶上（§6.6 queued 那一列）
function pp檔名文字(job) {
  return job.page_count
    ? job.filename + "（" + job.page_count + " 頁）"
    : job.filename;
}

// 第二行：現在到哪了
function pp狀態文字(job) {
  if (job.status === "queued") return "排隊中";
  // error 是伺服器寫的一句短話（§4.3：不要把 stack 丟給瀏覽器）
  if (job.status === "failed") return "失敗：" + (job.error || "未知原因");

  // 剩下的就是另外兩種「正在跑」的狀態：analyzing，以及它的重跑版
  // （JOB_STATUSES 的第三個；那個英文狀態名刻意不寫在這裡——
  //   Phase 71 有一顆守門測試會掃本檔的字串，而那個狀態名的前五個
  //   英文字母正好是它抓的關鍵字之一，連註解都不能誤中，見計畫 §7 陷阱 14）。
  // ⚠ §6.6 的表把這兩個狀態放在**同一列**、顯示規則完全相同：
  //   「檔名＋第幾次；PDF 加『第 p／N 頁』」。
  //   所以這裡刻意**不**分成兩種措辭——「（第 2 次）」本身就已經把
  //   「這一輪不是第一次」講完了，多一組字只是多一份要維護的東西。
  const 段 = [];
  if (job.page_count) {
    // pages_done ＝ 做完幾頁，所以正在看的是下一頁。
    // 最後一頁做完的那一瞬間 pages_done 會等於 page_count，
    // 沒有 Math.min 就會顯示「第 6／5 頁」。
    const 這一頁 = Math.min(job.pages_done + 1, job.page_count);
    段.push("第 " + 這一頁 + "／" + job.page_count + " 頁");
  }
  段.push("分析中（第 " + job.attempt + " 次）");
  return 段.join("・");
}

// ── 造一列（結構固定，文字等一下才填）──────────────────────────────
function pp造列(job) {
  const row = document.createElement("li");
  row.className = "pp-job";
  row.id = "pp-job-" + job.job_id;      // 契約：每列 id ＝ pp-job-{job_id}
  row.dataset.jobId = job.job_id;

  const name = document.createElement("span");
  name.className = "pp-name";
  row.appendChild(name);

  const state = document.createElement("span");
  state.className = "pp-state";
  row.appendChild(state);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "pp-x";
  close.dataset.jobId = job.job_id;
  close.textContent = "×";
  close.setAttribute("aria-label", "關掉這一列");
  close.hidden = true;                  // 只有 failed 才露出來（D9）
  row.appendChild(close);

  return row;
}

// ── 更新一列（只在真的變了才寫）──────────────────────────────────
function pp更新列(row, job) {
  const 檔名 = pp檔名文字(job);
  const 狀態 = pp狀態文字(job);
  const name = row.querySelector(".pp-name");
  const state = row.querySelector(".pp-state");
  const close = row.querySelector(".pp-x");

  // 每 2 秒無條件重寫同樣的字，會讓 aria-live 一直重念、hover 也會閃。
  // 先比再寫，沒變就完全不碰 DOM。
  if (name.textContent !== 檔名) name.textContent = 檔名;
  if (state.textContent !== 狀態) state.textContent = 狀態;

  const 失敗 = job.status === "failed";
  row.classList.toggle("is-failed", 失敗);
  close.hidden = !失敗;
}

// ── 把一份 jobs 畫上去 ───────────────────────────────────────────────
// 刻意「對帳」而不是每次重畫整份清單：重畫會把鍵盤焦點從 × 上踢掉，
// 滑鼠 hover 也會每 2 秒閃一次。對帳只有 20 行，值得。
function ppRender(jobs) {
  ppInstall();
  const list = ppEl("pp-list");
  const 還在的 = {};

  jobs.forEach(function (job) {
    還在的[job.job_id] = true;
    let row = ppEl("pp-job-" + job.job_id);
    if (!row) {
      row = pp造列(job);
      list.appendChild(row);
    }
    pp更新列(row, job);
  });

  // 這一輪沒回來的：不是成功了（伺服器已刪掉），就是剛被 dismiss。兩種都該消失。
  Array.prototype.slice.call(list.children).forEach(function (row) {
    if (!還在的[row.dataset.jobId]) row.remove();
  });

  // 清單空了就收起整個面板（D9 最後一句）
  ppEl("pp-panel").hidden = list.children.length === 0;
}

// ── 頂欄「待決定（N）」──────────────────────────────────────────────
// Phase 53 已經把頂欄那一格寫成固定形狀：
//     <a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
// 這裡**只改那個 <span> 的文字**，「待決定」三個字與全形括號永遠不會被程式碰到。
// （Phase 53 §4.1 的理由：整段字重寫的話，手滑一次整格就不見了。）
// 沒有頂欄的頁面（例如手機取景頁）拿不到那個 span，直接不做事。
function pp更新待決定(count) {
  if (typeof count !== "number") return;      // 伺服器沒給就別亂改畫面
  const 格子 = ppEl("nav-pending-count");
  if (!格子) return;
  const 文字 = String(count);
  if (格子.textContent !== 文字) 格子.textContent = 文字;
}

// ── 關掉一列失敗的工作（D9；§5：一律 POST——Phase 37 禁掉的那個
//    HTTP 動詞連註解都不寫，契約測試會掃本檔）──────────────────────
async function ppDismiss(jobId) {
  // 樂觀更新：先從畫面拿掉，人不必等一趟往返。
  // 失敗了也沒關係——下一次輪詢它會自己長回來，再按一次就好。
  const row = ppEl("pp-job-" + jobId);
  if (row) row.remove();
  ppEl("pp-panel").hidden = ppEl("pp-list").children.length === 0;

  try {
    await fetch("/ingest-jobs/" + encodeURIComponent(jobId) + "/dismiss", {
      method: "POST"
    });
    // 404（早就不在了）與 409（其實還在跑）都不必特別處理：
    // 409 的話下一次輪詢會把它畫回來，人就知道「這個還不能關」。
  } catch (error) {
    // 面板是背景資訊，不該為了它中斷手上的事——這裡刻意不顯示紅字。
  }
}

// ── 輪詢一次 ─────────────────────────────────────────────────────────
async function ppPoll() {
  if (ppInFlight) return;                    // 上一次還沒回來（避免競態）
  if (document.hidden) return;               // 分頁在背景：不打（理由見計畫 §4.6）
  if (Date.now() < ppQuietUntil) return;     // 退避中

  ppInFlight = true;
  try {
    const response = await fetch("/ingest-jobs");
    if (!response.ok) throw new Error("HTTP " + response.status);
    const body = await response.json();

    ppFailStreak = 0;
    ppQuietUntil = 0;
    ppLoggedFailure = false;                 // 下次真的斷線時才會再印一次
    ppRender(body.jobs || []);
    pp更新待決定(body.pending_count);
  } catch (error) {
    pp輪詢失敗();
  } finally {
    ppInFlight = false;
  }
}

// 網路斷了、容器正在重啟——都走這裡。
// ① 不停掉輪詢（伺服器回來會自己接上）② 不洗版 console ③ 越失敗等越久
function pp輪詢失敗() {
  ppFailStreak += 1;
  const 等待 = Math.min(PP_POLL_MS * Math.pow(2, ppFailStreak), PP_MAX_BACKOFF_MS);
  ppQuietUntil = Date.now() + 等待;
  if (!ppLoggedFailure) {
    // 用 info 不用 error：這是預期內的暫時狀況（重啟服務時每次都會發生），
    // 印成紅色錯誤會讓真正的 bug 淹在裡面。
    // ⚠ 這句話的措辭是挑過的：Phase 71 的守門測試會掃本檔字串（陷阱 14），
    //   所以這裡不能用「等一下會◯◯」的那兩個常見中文字。
    console.info("入庫進度暫時讀不到，等連線恢復會自動接上。");
    ppLoggedFailure = true;
  }
}

// ── 開始／停止 ───────────────────────────────────────────────────────
function ppStart() {
  ppInstall();
  if (ppTimer === null) {
    ppTimer = setInterval(ppPoll, PP_POLL_MS);
  }
  ppPoll();          // 不要等 2 秒才第一次更新（上傳頁送完檔會再叫一次這個）
}

function ppStop() {
  if (ppTimer !== null) {
    clearInterval(ppTimer);
    ppTimer = null;
  }
}

// 切回這個分頁時立刻補一次，不然要乾等 2 秒才看到最新狀態
document.addEventListener("visibilitychange", function () {
  if (!document.hidden) {
    ppQuietUntil = 0;
    ppPoll();
  }
});

ppStart();
```

### 4.3 `style.css` 新增「入庫進度面板」區塊

- [ ] 在既有「詳情彈窗（`pd-`）」區塊**之後**、「待辦列表」區塊**之前**插入這一整段：

```css
/* ══ 入庫進度面板（progress_panel.js；五頁共用）═══════════════════════
   為什麼固定在右下角：這是**背景資訊**，不是任何一頁的主角。
   全站三種版面的主要操作都不在那個角落——`.page` 是置中 60rem 的直欄、
   `.cd-layout` 是左配對右舞台的兩欄、彈窗一律置中——所以右下角是全站
   最安全的空地。

   為什麼不會遮住內容：
     ① 沒有工作在跑時整塊是 hidden ＝ 畫面上根本不存在（大部分時間都是這樣）
     ② 寬度上限 22rem，不吃滿版
     ③ 高度上限 22rem／50vh，超過就自己捲，長不到把整頁蓋掉
     ④ 手機寬度（≤32rem）改成貼齊左右下緣的一條，不會壓到中間的內容

   為什麼沒有陰影：`--shadow-modal` 的註解寫明「全站唯一用陰影的地方」是彈窗。
   面板是常駐元件，用**深一階的邊框**（--c-text）做分離就夠——
   看起來像一張夾在螢幕角落的索引卡，正好是本站的設計語言。 */
.pp-panel {
  position: fixed;
  right: var(--sp-4);
  bottom: var(--sp-4);
  z-index: 10;                     /* 比頁面內容高，比彈窗（20）低 */
  width: min(22rem, calc(100vw - var(--sp-5)));
  max-height: min(50vh, 22rem);
  overflow-y: auto;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-text);
  border-radius: var(--radius-m);
}
.pp-panel[hidden] { display: none; }

/* 面板標題＝牛皮紙色的一條，與資料夾卡片的索引 tab 同一套語言。
   sticky：列多到要捲動時，標題留在上緣不跟著捲走。 */
.pp-head {
  position: sticky;
  top: 0;
  margin: 0;
  padding: var(--sp-2) var(--sp-3);
  font-family: var(--f-display);
  font-size: var(--fs-small);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--c-text-muted);
  background: var(--c-surface-2);
  border-bottom: var(--bw) solid var(--c-border);
}

.pp-list { margin: 0; padding: 0; list-style: none; }

/* 一列＝左邊兩行文字（檔名／狀態）、右邊一顆 ×（只有失敗才露出來） */
.pp-job {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0 var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-top: var(--bw) solid var(--c-border);
}
.pp-job:first-child { border-top: none; }

.pp-name {
  grid-column: 1;
  grid-row: 1;
  font-size: var(--fs-small);
  overflow-wrap: anywhere;         /* 檔名可能很長又沒有空白可斷 */
}

/* 狀態用等寬字：頁碼與次數對齊了才掃得快（與照片 id、日期同一套「收據字」規則） */
.pp-state {
  grid-column: 1;
  grid-row: 2;
  font-family: var(--f-mono);
  font-size: var(--fs-small);
  color: var(--c-text-muted);
  overflow-wrap: anywhere;
}
.pp-job.is-failed .pp-state { color: var(--c-danger); }

.pp-x {
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: start;
  padding: 0 var(--sp-2);
  font: inherit;
  font-size: var(--fs-section);
  line-height: 1;
  color: var(--c-text-muted);
  background: none;
  border: none;
  cursor: pointer;
}
.pp-x:hover { color: var(--c-text); }
/* grid 的子元素有 display 之外的排版角色，hidden 的預設 display:none 還是有效，
   但 .fm-option 踩過同類的坑——先寫死，之後有人給 .pp-x 設 display 也不會破 */
.pp-x[hidden] { display: none; }
```

- [ ] 幫既有的 `.fm-backdrop` 補**一行** `z-index`（`style.css` 第 513 行附近）。
      這是本 phase 對既有樣式的**唯一**改動：

```css
.fm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;                     /* ← 新增這一行：彈窗永遠蓋在進度面板（10）上面 */
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
  background: rgba(0, 0, 0, 0.45);
}
```

  **為什麼一定要加**：兩個都是 `position: fixed` 又都沒寫 `z-index` 時，
  誰蓋誰是看**誰在 HTML 裡比較後面**——這是隱形規則，哪天有人調換 `<script>` 順序就會
  變成「面板浮在彈窗遮罩上」。把層號寫死，就不必再依賴那種看不見的約定。

- [ ] 在檔尾的手機斷點 `@media (max-width: 32rem)` 區塊裡加一行：

```css
  .pp-panel { right: var(--sp-2); left: var(--sp-2); bottom: var(--sp-2); width: auto; }
```

### 4.4 五個頁面各加一行 `<script src>`

- [ ] 每一頁在**自己的 inline `<script>` 之前**加這一行（順序不能反：inline 的程式碼要叫得到 `ppStart()`）：

```html
<script src="/ui/progress_panel.js"></script>
```

各頁確切位置：

| 檔案 | 加在哪一行之後 |
|---|---|
| `upload.html` | 既有的 `<script src="/ui/ai_switch.js"></script>` 之後 |
| `pending.html` | Phase 52 建的那一區 `<script src=…>` 的最後一行之後 |
| `browse.html` | `<script src="/ui/photo_detail_modal.js"></script>` 之後 |
| `ask.html` | `<script src="/ui/ai_switch.js"></script>` 之後 |
| `camera-desk.html` | `<script src="/ui/ai_switch.js"></script>` 之後 |

> ⚠ **不要**加到 `camera-phone.html`。理由見 §3 的「明確不做」與 §4.7。

### 4.5 把 Phase 53 的過渡計數片段刪掉（五份，逐字相同）

Phase 53 為了先把四格頂欄做出來，在**每一頁的 `</header>` 正下方**貼了一段
「打 `GET /folders`、找收件箱、把 `photo_count` 填進那個 `<span>`」的程式。
那一段在五個 HTML 裡**各有一份、逐字相同**，而且 Phase 53 §4.2 的註解已經先寫好了：

> ⚠ 這一段在五個 HTML 檔裡各有一份、逐字相同。
> 階段丙 Phase 67 會由 `progress_panel.js` 一次接手（連同 2 秒輪詢），**屆時把五份一起刪掉**。

本 phase 就是來執行那句話的（使用者偏好：不留過渡產物）。

- [ ] **先確認五份都在**：

```bash
cd /Users/linjunting/personalDocAI
grep -c 'const 格子 = document.getElementById("nav-pending-count");' \
  app/static/upload.html app/static/pending.html app/static/browse.html \
  app/static/ask.html app/static/camera-desk.html
# 預期：五個檔各印 1
```

- [ ] **五頁各刪掉這一整段 `<script>`（含頭尾標籤，共 25 行）：**

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

- [ ] **⚠ 只刪那一段 `<script>`，`<header>` 裡的那一格 HTML 一個字都不要動：**

```html
<!-- ✓ 這一行留著。span 是本 phase 要更新的目標，「…」是還沒收到第一次輪詢時的初始值 -->
<a href="/ui/pending.html">待決定（<span id="nav-pending-count">…</span>）</a>
```

  刪完**不必在頁面裡補任何東西**——`progress_panel.js` 一載入就會自己叫 `ppStart()`，
  而 `ppStart()` 的最後一行就打了第一次輪詢，數字**立刻**就會從「…」變成真的數字。

- [ ] **`pending.html`／`browse.html` 頁面主體自己打的 `/folders` 要留著。**
      那兩頁本來就需要它（拿收件箱 id、畫資料夾卡片），不是只為了算 N。
      判準很簡單：**只刪上面那段被 `(function () { … })();` 包起來、
      裡面出現 `nav-pending-count` 的 `<script>`**，其餘一律不動。

- [ ] **刪完自己驗一次**：

```bash
grep -rn "nav-pending-count" app/static/
```
      預期：五個 HTML 各**恰好一行**（就是 `<header>` 裡那個 `<span>`），
      外加 `app/static/progress_panel.js` **兩行**（`pp更新待決定()` 上方那行示意註解、
      與程式裡的 `ppEl("nav-pending-count")` 各一）——總共**七行**。
      **不可以**再看到 `const 格子 = document.getElementById(…)` 那一行。

- [ ] **同時要改 Phase 53 留下來的那顆測試。**
      `tests/integration/test_nav_header.py` 裡有一顆 `test_五頁都有同一份待決定計數片段`，
      它斷言那段程式碼**存在**——本 phase 刪掉之後它會變紅。
      這是**預期中的紅**，不是 bug。把那一顆**原地換成**下面這一版（名字也換，
      **不是新增一顆**，所以那個檔的顆數不變）：

```python
def test_五頁的計數片段已交棒給進度面板():
    """Phase 53 的過渡片段（各頁自己打 GET /folders 算 N）在 Phase 67 整組刪掉。

    改由 app/static/progress_panel.js 每 2 秒輪詢 GET /ingest-jobs 一次帶回
    jobs 與 pending_count（design5.md §6.1：「不要四個 HTML 各寫一套 setInterval」）。

    頂欄那一格的 HTML（含 <span id="nav-pending-count">）**沒有變**，
    由 test_待決定那一格是固定形狀且帶計數欄位 繼續守著。
    """
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        assert 'const 格子 = document.getElementById("nav-pending-count");' not in 原始碼, (
            f"{檔名} 還留著 Phase 53 的過渡計數片段——Phase 67 起由 progress_panel.js 接手"
        )
        assert '<script src="/ui/progress_panel.js"></script>' in 原始碼

    面板 = (專案根目錄 / "app" / "static" / "progress_panel.js").read_text(encoding="utf-8")
    assert 'ppEl("nav-pending-count")' in 面板
```

  順手把檔頭那個常數 `計數片段的關鍵行`（Phase 53 §4.8 定義的四行清單）一起刪掉——
  沒有人再用它了，留著就是垃圾。

### 4.6 決策：`document.hidden` 時**要**停止輪詢

**做法**：`ppPoll()` 開頭 `if (document.hidden) return;`，並在 `visibilitychange` 變回可見時
立刻補打一次（上面 §4.2 的程式碼已經寫好了）。

**理由三條：**

1. **背景分頁問了也沒人看。** 本機 VLM 看一張圖要 1〜5 分鐘（CLAUDE.md 實測）。
   把一個分頁丟在背景一小時＝白問 1800 次。這台機器同時在跑 Postgres、兩個 Celery worker
   與 Ollama，能省的請求就省。
2. **「回來就補齊」是免費的。** 這正是 D8 的設計好處：狀態在**伺服器**上，不在瀏覽器記憶體裡。
   背景時漏掉的每一次輪詢，都不會造成任何資訊遺失——切回來打一次就全補上了。
   （如果狀態存在瀏覽器裡，這個決定才會有代價。）
3. **不做的話，瀏覽器也會自己節流，而且更難預測。** Chrome／Safari 對背景分頁的
   `setInterval` 會降到 1 秒甚至 1 分鐘一次，各家規則不同也隨版本變。與其被不可預測地節流，
   不如自己把規則寫清楚。

**代價與補償**：切回分頁的那一瞬間本來要乾等 2 秒。所以 `visibilitychange` 那三行**不能省**——
沒有它，這個最佳化就會變成使用者感受得到的遲鈍。

### 4.7 D8 與 §6.5 的落差（實作時一定會撞到，先講清楚）

design5 **D8** 寫「每一頁右下角同一份面板（含問問題、瀏覽、待決定、鏡頭桌面、**手機取景**）」，
但 **§6.5** 又寫「`camera-phone.html`：進度用**窄條**，不擋快門」。兩句話對不起來。

**本計畫的裁決：手機取景頁不掛這一份面板，改用 Phase 69 的窄條。** 理由：

- §6.5 是**更具體**的那一條（它直接規定手機頁該長什麼樣），而且理由寫在裡面——「不擋快門」。
- 事實上 `.cp-controls`（三顆按鈕）就貼在畫面下緣，右下角固定面板一定壓到「開閃光」那一顆。
- 手機端也不需要知道 worker 現在第幾次嘗試——那是坐在電腦前的人要看的。
  手機只需要知道「我拍的那張送出去了沒」，而那是純本地狀態，不必輪詢。

**這是計畫層的裁決，不是 design5 自己寫的字**；寫進 Phase 69 的「明確不做」表以免日後又被翻出來。

`docs/plan/unfinish/phase-00-增量五總覽.md` §10「撰寫本總覽時發現的缺口」表第 3 列也記了同一條，結論一致：
**67 做桌面五頁的完整面板、69 做 camera-phone 的窄條**（總覽另補一句：手機端「可以」
也呼叫同一支 `GET /ingest-jobs`，只是**不要**把整個面板疊在取景畫面上）。
Phase 69 §4.2 進一步選了「連呼叫都不呼叫、只用純本地計數」——理由寫在那裡。

### 4.8 新建 `tests/integration/test_progress_panel_contract.py`

- [ ] 建檔，整份照抄。這七顆都是**掃原始碼字串**的契約測試（比照
      `test_design4_error_paths.py` 與 `test_camera_endpoints.py::test_qr的顯示尺寸…` 的手法），
      不啟動瀏覽器、不打 AI、跑起來是毫秒級：

```python
"""增量五階段丙的前端契約（Phase 67 建，Phase 68／69 續加）。

本專案的前端 phase 一律**不新增 Playwright 自動化測試**
（design5 §9 明文、Phase 14／23／24／31／33／39 的一貫慣例）：
畫面好不好看、按下去對不對，用瀏覽器實操驗收。

但有幾條規則是「壞掉的時候沒有人會發現」的那種——例如某一頁忘了掛進度面板、
或有人為了方便在 HTML 裡又寫了一個 setInterval。那種東西用字串掃原始碼最省事，
所以這一檔只釘**契約**，不驗行為。
"""

from __future__ import annotations

import re
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
靜態目錄 = 專案根目錄 / "app" / "static"

# 進度面板要掛在這五頁（design5 D8；camera-phone.html 刻意不在內，見 Phase 67 §4.7）
掛面板的五頁 = [
    "upload.html",
    "pending.html",
    "browse.html",
    "ask.html",
    "camera-desk.html",
]


def 讀(檔名: str) -> str:
    """讀 app/static 底下的檔案。

    刻意不先判 exists()：路徑打錯要當場炸 FileNotFoundError，
    不能默默變成綠的（同 test_design4_error_paths.py 的作法）。
    """
    return (靜態目錄 / 檔名).read_text(encoding="utf-8")


# ---- ① design5 D8：五頁都掛了同一份進度面板 ----


def test_五頁都掛了進度面板():
    for 檔名 in 掛面板的五頁:
        assert '<script src="/ui/progress_panel.js"></script>' in 讀(檔名), (
            f"{檔名} 沒有掛 progress_panel.js——design5 D8 要求進度面板全站都在，"
            "換頁不能讓進行中的工作消失"
        )


def test_手機取景頁刻意沒有掛面板():
    """camera-phone.html 是全螢幕取景，右下角固定面板會壓到快門。

    手機端的進度是 Phase 69 的窄條（cp-bar），不是這一份面板
    （Phase 67 §4.7 的裁決：§6.5 比 D8 具體，以 §6.5 為準）。
    """
    assert "progress_panel.js" not in 讀("camera-phone.html")


# ---- ② design5 §6.1：輪詢全站只有一份 ----


def test_進度面板是全站唯一一份輪詢():
    """§6.1 明文：「不要四個 HTML 各寫一套 setInterval」。"""
    面板 = 讀("progress_panel.js")
    assert 面板.count("setInterval(") == 1

    for 檔名 in sorted(p.name for p in 靜態目錄.glob("*.html")):
        assert "setInterval" not in 讀(檔名), (
            f"{檔名} 自己寫了 setInterval——輪詢只准有一份，寫在 progress_panel.js 裡"
        )


def test_進度面板的契約常數與命名():
    """跨文件共用契約：前綴 pp、容器 #pp-panel、每列 pp-job-{job_id}、間隔 2000 ms。"""
    面板 = 讀("progress_panel.js")

    assert "const PP_POLL_MS = 2000;" in 面板
    assert 'panel.id = "pp-panel";' in 面板
    assert '"pp-job-" + job.job_id' in 面板
    for 函式 in ["function ppStart()", "function ppStop()",
                 "function ppRender(jobs)", "async function ppDismiss(jobId)"]:
        assert 函式 in 面板, f"少了對外函式 {函式}"


# ---- ③ design5 §5／Phase 37：關掉失敗列用 POST，openapi 永遠零 DELETE ----


def test_關掉失敗列用POST不用DELETE():
    面板 = 讀("progress_panel.js")

    assert '/dismiss"' in 面板
    assert 'method: "POST"' in 面板
    assert "DELETE" not in 面板


# ---- ④ design5 §6.1：頂欄 N 只有一個地方在算 ----


def test_頂欄待決定的數字只由進度面板更新():
    """全站只有一個地方在寫 #nav-pending-count 的內容。

    Phase 53 在五個 HTML 各貼了一份「自己打 GET /folders 算 N」的過渡片段
    （見 tests/integration/test_nav_header.py 的同名沿革），本 phase 整組刪掉。
    這一顆從**另一面**守同一條規則：五頁只准把 nav-pending-count 當作
    「頂欄 HTML 裡的那個 span」提到一次，不准再有人去改它的文字。
    """
    for 檔名 in 掛面板的五頁:
        原始碼 = 讀(檔名)
        # 每一頁只有 <header> 裡那個 <span id="nav-pending-count">…</span>
        assert 原始碼.count("nav-pending-count") == 1, (
            f"{檔名} 提到 nav-pending-count 超過一次——"
            "Phase 67 起這個數字只由 progress_panel.js 的 pp更新待決定() 供應"
        )
        assert '<span id="nav-pending-count">…</span>' in 原始碼

    面板 = 讀("progress_panel.js")
    assert 'ppEl("nav-pending-count")' in 面板
    # 只換 span 的數字，不重寫整格文字（Phase 53 §4.1 的理由）
    assert '"待決定（"' not in 面板


# ---- ⑤ 全站鐵律：禁原生對話框；面板本身零 innerHTML ----


def test_靜態檔沒有原生對話框且面板零innerHTML():
    原生對話框 = re.compile(r"\b(alert|confirm|prompt)\(")
    for 路徑 in sorted(靜態目錄.glob("*.html")) + sorted(靜態目錄.glob("*.js")):
        原始碼 = 路徑.read_text(encoding="utf-8")
        assert not 原生對話框.search(原始碼), (
            f"{路徑.name} 出現了原生對話框——全站鐵律禁用 alert／confirm／prompt"
        )

    # 面板只有三個節點，全部用 createElement 造；零 innerHTML 讓這條可以直接掃
    assert "innerHTML" not in 讀("progress_panel.js")
```

- [ ] 跑它，確認七顆全綠：

```bash
pytest tests/integration/test_progress_panel_contract.py -v
# 預期：7 passed
```

- [ ] 跑全量，確認總數是開工前的 **N ＋ 7**：

```bash
pytest -q
```

---

## 5. ASCII 圖

### 5.1 面板的四種狀態長什麼樣（線框圖）

```text
                                   ┌─ 沒有工作在跑：整塊 hidden，畫面上不存在 ─┐
                                   └───────────────────────────────────────────┘

 ┌──────────────────────────────────┐   ← #pp-panel（右下角，寬 ≤22rem）
 │ 處理中                            │   ← .pp-head（牛皮紙底，捲動時 sticky）
 ├──────────────────────────────────┤
 │ receipt.jpg                      │   ① queued
 │ 排隊中                            │      §6.6：只有檔名（PDF 已知頁數才加「（N 頁）」）
 ├──────────────────────────────────┤
 │ menu.jpg                         │   ② analyzing
 │ 分析中（第 1 次）                  │      §6.6：檔名＋第幾次
 ├──────────────────────────────────┤
 │ scan.pdf（5 頁）                  │   ③ retrying ＋ PDF
 │ 第 3／5 頁・分析中（第 2 次）       │      §6.6：PDF 再加「第 p／N 頁」
 │                                  │      （§6.6 把 analyzing 與 retrying 放同一列，
 │                                  │        顯示規則相同——「第 2 次」就代表重試了）
 ├──────────────────────────────────┤
 │ blurry.png                  [ × ]│   ④ failed（.is-failed → 狀態列變紅）
 │ 失敗：看不懂這張照片（已試 3 次）    │      × 只有失敗列才露出來（D9）
 └──────────────────────────────────┘

      ★ 成功的**不會出現**。伺服器一成功就 delete(job_id)，
        GET /ingest-jobs 根本不會回它（§4.3）。
        所以前端不必寫 `if (status === "success")` 的過濾——那是死碼。

      ★ 全部成功、或失敗都按了 × → 清單空了 → 面板整塊 hidden（D9 最後一句）
```

### 5.2 輪詢一次的資料流

```text
   ┌──────────── 瀏覽器（五頁任一頁都一樣）─────────────┐
   │                                                    │
   │  progress_panel.js                                 │
   │    setInterval(ppPoll, PP_POLL_MS = 2000)          │
   │           │                                        │
   │           │ ① document.hidden？ → 是，這次跳過      │
   │           │ ② ppInFlight？      → 是，這次跳過      │
   │           │ ③ 退避中？          → 是，這次跳過      │
   │           ▼                                        │
   │      fetch("/ingest-jobs")  ───────────────────────┼──► FastAPI
   │                                                    │      │
   │      ◄─────────────────────────────────────────────┼──────┘
   │      { jobs: [ …四種狀態… ],  pending_count: 4 }    │   jobs ← JobStore（Redis）
   │           │                    │                   │   pending_count ← SQL 數收件箱
   │           │                    │                   │
   │           ▼                    ▼                   │
   │      ppRender(jobs)      pp更新待決定(4)            │
   │           │                    │                   │
   │   ┌───────┴────────┐           │                   │
   │   │ 有這一列 → 更新 │           ▼                   │
   │   │ 沒有   → 造一列 │  #nav-pending-count 這個 span │
   │   │ 不在了 → 移掉   │      textContent = "4"        │
   │   └───────┬────────┘  （「待決定（」與「）」是 HTML， │
   │           │            永遠不會被程式碰到）           │
   │           ▼                                        │
   │      清單空了 → #pp-panel.hidden = true             │
   └────────────────────────────────────────────────────┘

   失敗那一條路（網路斷、容器重啟）：
      fetch 丟例外 → pp輪詢失敗()
         ppFailStreak += 1
         等待 = min(2000 × 2^次數, 30000)     ← 指數退避
         console.info 只印一次（不洗版）
         ★ 計時器**不停**：伺服器回來的下一輪就自己接上了
```

### 5.3 為什麼「換頁還在」是免費的

```text
   ✗ 如果狀態存在瀏覽器裡（例如 localStorage 或一個 JS 變數）
        上傳頁：我記得有 3 個檔在跑
        → 換到問問題頁 → 這一頁的 JS 是全新的，什麼都不記得 → 進度消失
        → 重新整理 → 記憶又歸零 → 進度一樣消失
        → 要救就得寫「把狀態同步到別的分頁」，複雜度直線上升

   ✓ 本 phase：狀態的**唯一真相**在伺服器的 JobStore（design5 §4.3）
        上傳頁：GET /ingest-jobs → 3 筆
        → 換到問問題頁 → 這一頁載入 progress_panel.js → GET /ingest-jobs → 還是那 3 筆
        → 重新整理 → 再問一次伺服器 → 還是那 3 筆
        → 換一台電腦開 → 還是那 3 筆
        前端完全不必「記得」任何事，只要每 2 秒問一次就好。

   這也是為什麼 §4.6「背景分頁不輪詢」不會有代價：
   漏掉的每一次輪詢都不損失資訊，切回來打一次就全補上了。
```

---

## 6. 驗收清單

### 6.1 自動化（跑指令）

- [ ] **契約測試七顆全綠**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_progress_panel_contract.py -v
```
      預期：`7 passed`

- [ ] **進度面板躲開了 Phase 71 的守門關鍵字（陷阱 14；先自查，不要等收尾才紅）**

```bash
grep -nE "再試|retry|Retry" app/static/progress_panel.js || echo "OK：面板沒有踩到守門關鍵字"
```
      預期：`OK：面板沒有踩到守門關鍵字`。
      Phase 71 的 `test_進度面板沒有再試一次` 掃的是**裸字串** `("再試", "retry", "Retry")`，
      所以連註解與 console 訊息都算——§4.2 的程式碼已經全面避開，照抄就不會踩。

- [ ] **Phase 53 那個檔的顆數沒變（一顆被原地換掉，不是新增）**

```bash
pytest tests/integration/test_nav_header.py -v
```
      預期：全綠，而且**沒有** `test_五頁都有同一份待決定計數片段`
      （它已被 `test_五頁的計數片段已交棒給進度面板` 取代，見 §4.5 最後一步）

- [ ] **全量測試 ＝ 開工前的 N ＋ 7**

```bash
pytest -q
```
      預期：`(N+7) passed`（本 phase 新增 7 顆；`test_nav_header.py` 那一顆是**換掉**、不是新增）。
      ⚠ **絕對不要同時跑兩份 pytest**（會互相 TRUNCATE 測試庫）。

- [ ] **端點數沒有變**（本 phase 純前端，仍是階段乙做完的 22）

```bash
pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
```
      預期：`1 passed`

- [ ] **Phase 53 的過渡計數片段五份都刪乾淨了**

```bash
grep -rn 'const 格子 = document.getElementById("nav-pending-count");' app/static/ \
  || echo "OK：五份過渡片段都已刪除"
grep -rn "nav-pending-count" app/static/
```
      預期：第一行印出 `OK：五份過渡片段都已刪除`；
      第二條指令恰好**七行**——五個 HTML 各一行（`<header>` 裡那個 `<span>`）
      ＋ `progress_panel.js` 兩行（示意註解與 `ppEl()` 各一）

- [ ] **沒有任何 HTML 自己寫 `setInterval`**

```bash
grep -rn "setInterval" app/static/*.html || echo "OK：五頁都沒有自己輪詢"
```
      預期：`OK：五頁都沒有自己輪詢`

- [ ] **沒有引入任何前端相依**

```bash
ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
grep -riE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/ || echo "OK：沒有外部前端函式庫"
```

- [ ] **只動到預期的檔案（跟 §2 抄下的快照相減）**

```bash
git status --short -- app tests > /tmp/p67-after.txt
diff /tmp/p67-before.txt /tmp/p67-after.txt
```
      預期：`diff` 只多出**兩個新檔**——`?? app/static/progress_panel.js`、
      `?? tests/integration/test_progress_panel_contract.py`。
      本 phase 另外**改過**這七個檔：`app/static/style.css`、五個 HTML
      （`upload.html`／`pending.html`／`browse.html`／`ask.html`／`camera-desk.html`）、
      `tests/integration/test_nav_header.py`——它們在快照裡的**標記不一定變**
      （前面 phase 已動過、或已被 commit 的檔才會從無到有出現 `M`；
      Phase 52 新建的 `pending.html` 若整個增量還沒 commit，兩份快照裡都是 `??`）。
      改動內容要各別看：已追蹤的用 `git diff`、未追蹤的直接開檔——
      新建的檔 `git diff` 看不到，要兩條路分開查（同 Phase 39 §6 的作法）。

### 6.2 瀏覽器實操（本 phase 的主要驗收方式）

準備：把頁首的「AI 模型」開關撥到**雲端**（本機看一張圖 1〜5 分鐘，會等到懷疑人生；
design5 D6 也建議手動煙霧用雲端）。準備幾張測試圖：

```bash
screencapture -x /tmp/pp1.png && cp /tmp/pp1.png /tmp/pp2.png && cp /tmp/pp1.png /tmp/pp3.png
```

- [ ] **1. 沒有工作時面板完全不存在**
      開 `https://localhost:8000/ui/ask.html`。
      **看到**：右下角乾乾淨淨。開發者工具 Elements 搜 `pp-panel` → 找得到那個節點，
      但它有 `hidden` 屬性（＝已經裝好、只是沒東西可顯示）。

- [ ] **2. 上傳一張圖 → 面板跳出來、走完四個階段**
      開 `https://localhost:8000/ui/upload.html`，上傳 `/tmp/pp1.png`。
      **看到**：右下角出現「處理中」面板，第一列顯示檔名，狀態依序變成
      `排隊中` →（幾秒後）`分析中（第 1 次）`。

- [ ] **3. 成功列自己消失、頂欄 N 加 1**
      先記下頂欄現在的「待決定（N）」是多少。等第 2 項那張分析完。
      **看到**：那一列**自己不見了**（不是變成打勾）；面板整塊收起；頂欄變成「待決定（N+1）」。
      核對後端：
```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
```
      **看到**：`jobs` 是 `[]`，`pending_count` 就是頂欄那個數字。

- [ ] **4. 換頁進行中的列還在（D8 的重點）**
      再上傳一張，**趁它還在跑**點頂欄的「問問題」。
      **看到**：換頁之後右下角的面板還在，那一列還在跑。
      再按 `Cmd + R` 重新整理 → **仍然在**。

- [ ] **5. 失敗列留下、× 關得掉、面板收起**
      沒有任何端點可以「把 job 標成 failed」——要製造一筆真的失敗，
      就讓 VLM 真的失敗三次。最快的做法：把頁首 AI 開關撥到**雲端**，
      然後把 `.env` 的 `OLLAMA_API_KEY` 改成錯的值並重啟 app
      （`docker compose -f compose.yaml -f compose.dev.yaml restart app worker`——
      **worker 也要重啟**，看圖的是它），再上傳一張：
```bash
curl -sk -X POST https://127.0.0.1:8000/photos -F "file=@/tmp/pp2.png;type=image/png"
```
      雲端對錯 key 回得很快，三次失敗只要幾秒（不像本機要等好幾分鐘）。
      **看到**：那一列留在面板上、狀態列是**紅字**「失敗：…」、右邊出現一顆 `×`。
      驗完記得把 key 改回來、再 `restart app worker` 一次。
      按 `×` → 那一列消失、面板收起（如果沒有別的工作）。
      核對後端：
```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
```
      **看到**：`jobs` 裡沒有那一筆了。

- [ ] **6. 409：dismiss 一筆還在跑的工作，畫面會自己修正**
      趁一筆還在 `analyzing` 時，用 curl 直接對它 dismiss：
```bash
curl -sk -o /dev/null -w "%{http_code}\n" -X POST \
  https://127.0.0.1:8000/ingest-jobs/<那個 job_id>/dismiss
```
      **看到**：`409`；而且面板上那一列**還在**（它本來就沒被前端拿掉，因為 × 只給失敗列）。

- [ ] **7. PDF 顯示頁碼**
      上傳一份 2 頁以上的 PDF。
      **看到**：面板那一列的第一行是「檔名（N 頁）」，第二行像 `第 2／5 頁・分析中（第 1 次）`。
      ⚠ 最後一頁做完的瞬間**不可以**出現「第 6／5 頁」（有 `Math.min` 擋住）。

- [ ] **8. 伺服器斷線不洗版、也不會停掉輪詢**
      趁一筆還在跑時，把 app 容器停掉再拉起來：
```bash
docker compose -f compose.yaml stop app && sleep 8 && docker compose -f compose.yaml up -d app
```
      **看到**：Console **只出現一次**「入庫進度暫時讀不到，等連線恢復會自動接上。」（藍色 info，不是紅色 error）；
      **沒有**幾十行 `Failed to fetch` 洗版；app 回來後，最多 30 秒內面板自己接上、繼續更新。

- [ ] **9. 背景分頁不打**
      開發者工具 → Network 分頁 → 篩選 `ingest-jobs`。切到別的分頁 30 秒再切回來。
      **看到**：切走那段時間**沒有**新的請求；切回來的**那一瞬間**立刻多一筆（`visibilitychange`）。

- [ ] **10. 面板不擋事、彈窗蓋在它上面**
      到 `https://localhost:8000/ui/pending.html`（有工作在跑時），點一張照片開歸類彈窗。
      **看到**：暗色遮罩蓋住整個畫面，**包含右下角的面板**（`z-index: 20` > `10`）。
      關掉彈窗 → 面板又出現、而且數字是最新的（它在背後一直有在跑）。

- [ ] **11. 面板不會壓到主要操作**
      在 `upload.html`／`ask.html`／`browse.html`／`camera-desk.html` 各看一眼：
      面板在右下角，`.page` 的內容置中，兩者不重疊。
      把視窗縮到很窄（≤512px）→ 面板變成貼齊左右下緣的一條，中間內容仍可捲動、可點。

- [ ] **12. 主控台乾淨**
      整趟走下來，Console 只有預期訊息（favicon 404、第 8 項那一行 info），沒有紅色錯誤，
      特別**不該**出現 `ppEl is not defined`／`Cannot read properties of null`。

---

## 7. 常見陷阱

1. **`<script src="/ui/progress_panel.js">` 放在頁面自己的 inline `<script>` 後面。**
   症狀：`upload.html` 送完檔要叫 `ppStart()` 時炸 `ppStart is not defined`。
   原因：瀏覽器由上往下執行，後面的檔案還沒載入。
   **一律放在 inline `<script>` 之前**（與 `folder_modal.js` 那一區同一個位置）。

2. **忘了幫 `.pp-panel` 寫 `[hidden] { display: none; }`。**
   症狀：明明 JS 設了 `hidden = true`，面板還是賴在右下角。
   原因：`hidden` 的效果是「瀏覽器預設樣式表給它 `display: none`」，而我們給了
   `.pp-panel` 別的東西——只要有任何規則設定了 `display`，那條預設就被蓋掉。
   `.fm-option` 與 `.pd-task` 都踩過同一個坑，`style.css` 裡有前例。

3. **每次輪詢都把整份清單重畫。**
   症狀：滑鼠放在 `×` 上每 2 秒閃一下；用鍵盤 Tab 到 `×` 的人永遠按不到（焦點一直被踢掉）。
   原因：`list.textContent = ""` 之後重建 → 舊節點連同焦點一起消失。
   **照 §4.2 的 `ppRender` 做「對帳」**：有就更新、沒有才造、不在了才移掉。

4. **面板浮在彈窗遮罩上面。**
   症狀：歸類彈窗開著的時候，右下角的面板還亮亮地浮在暗色遮罩上，看起來像壞掉。
   原因：兩個都是 `position: fixed` 又都沒有 `z-index`，誰蓋誰只看誰在 HTML 裡比較後面。
   **一定要照 §4.3 幫 `.fm-backdrop` 補 `z-index: 20;`**。

5. **前端自己寫過濾 `status === "success"`。**
   症狀：不會報錯，但那段程式永遠不會執行，下一個讀程式的人會以為
   「原來清單裡也可能有成功的」，然後開始想東想西。
   原因：§4.3 明訂**成功＝伺服器 `delete(job_id)`**。清單只會回四種狀態。
   **不要寫。** 也不要在註解裡暗示成功會回來。

6. **PDF 顯示「第 6／5 頁」。**
   症狀：最後一頁做完的那一瞬間閃過一個不可能的頁碼。
   原因：`pages_done` 是「做完幾頁」，最後一頁做完時它等於 `page_count`，
   `pages_done + 1` 就爆表了。
   **`Math.min(job.pages_done + 1, job.page_count)`** 那一行不能省。

7. **上一次輪詢還沒回來就發下一次（競態）。**
   症狀：偶爾看到面板「跳回」到上一秒的狀態，或某一列閃現又消失。
   原因：慢的那次回應**晚**到，把新的畫面蓋掉了。
   **`ppInFlight` 那三行不能省。** 這在本機很少發生（延遲很低），但只要伺服器一忙就會出現，
   而且症狀看起來像鬧鬼，很難查。

8. **連線失敗時停掉 `setInterval`。**
   症狀：重啟一次容器之後，面板從此再也不更新，要人重新整理頁面才會活過來。
   原因：`clearInterval` 之後沒有任何東西會再叫它。
   **失敗只做退避，不停計時器**（`pp輪詢失敗()` 裡沒有 `ppStop()`，那是刻意的）。

9. **連線失敗時 `console.error` 每 2 秒印一次。**
   症狀：重啟容器的 8 秒內，Console 出現 4 行紅字；真的 bug 淹在裡面。
   原因：沒有 `ppLoggedFailure` 這種「只印一次」的旗標。
   順帶一提：成功之後要把它設回 `false`，不然下一次真的斷線就一聲不吭了。

10. **把整條連結的 `textContent` 一次換掉。**
    症狀：頂欄那一格從此變成純文字，Phase 53 的
    `test_待決定那一格是固定形狀且帶計數欄位` 不會紅（它掃的是 HTML 檔），
    但下一次輪詢就找不到 `#nav-pending-count` 了——數字**只更新一次就凍住**，安靜壞掉。
    原因：`a.textContent = "待決定（4）"` 會把裡面那個 `<span>` 一併炸掉。
    **只改 `#nav-pending-count` 那個 span 的文字**（Phase 53 §4.1 就是為了這件事才包 span 的）。

11. **把 `pending.html`／`browse.html` 頁面主體的 `/folders` 也一起刪了。**
    症狀：`pending.html` 空白、`browse.html` 資料夾卡片消失。
    原因：那兩頁本來就要 `/folders`（拿收件箱 id、畫資料夾卡片），不是只為了算 N。
    **判準看 §4.5**：只刪那段被 `(function () { … })();` 包起來、
    裡面出現 `nav-pending-count` 的 `<script>`，其餘一律不動。

12. **刪了片段卻沒改 `test_nav_header.py`。**
    症狀：`pytest -q` 出現一顆紅的 `test_五頁都有同一份待決定計數片段`，
    然後有人以為「刪錯了」又把片段貼回去。
    原因：那顆測試是 Phase 53 用來確保「五份都貼了、而且逐字相同」的，
    交棒之後它的意義正好反過來。
    **照 §4.5 最後一步把它原地換成 `test_五頁的計數片段已交棒給進度面板`**（換掉，不是新增）。

13. **順手把面板也掛到 `camera-phone.html`。**
    症狀：手機上按不到「開閃光」，或快門被半透明的面板卡住。
    原因：手機頁的按鈕列就在畫面下緣（`.cp-controls`）。
    **不要掛**（§4.7 的裁決）；手機的進度是 Phase 69 的窄條。

14. **讓 `retry`／`再試` 以任何形式出現在 `progress_panel.js`（會害 Phase 71 變紅）。**
    症狀：Phase 71 的 `test_進度面板沒有再試一次` 紅掉，訊息寫「進度面板不做手動重試：retry」。
    原因：那顆測試（本文件撰寫時已對過 phase-71 原文）掃的是**裸字串**
    `("再試", "retry", "Retry") not in progress_panel.js`——整個檔案一起掃，
    所以**不只按鈕文字，連註解與 console 訊息都會誤中**。三種典型踩法：
    ①把 JobStore 狀態 `retrying` 顯示成「重試中」或寫進註解——**`retrying` 這個字串
    本身就含 `retry`**（它是契約備忘 §3.1 `JOB_STATUSES` 的四個狀態之一，
    不是「手動重試按鈕」）；②console 訊息寫「稍後會自己再試」——含「再試」；
    ③在註解裡好心提醒「Phase 71 禁止本檔出現 retry」——這行提醒自己就踩了。
    §4.2 的程式碼已經**全面避開**：狀態一律寫「分析中（第 N 次）」
    （§6.6 本來就把 `analyzing` 與那個重跑狀態放在同一列、顯示規則相同）、
    console 訊息用「等連線恢復會自動接上」、註解以「JOB_STATUSES 的第三個」代稱。
    照抄 §4.2、再跑 §6.1 那條自查 grep 就不會踩。
    **不要為了「講清楚一點」把那些字加回去。**
    （如果 Phase 71 的實作者想收窄關鍵字，`"再試一次"` 與 `"Retry"` 比裸的 `"retry"`
    安全——但只要本檔照 §4.2 寫，現在這組寬關鍵字也掃不到東西，兩邊相容。）

15. **在面板裡用 `alert` 報 dismiss 失敗。**
    症狀：驗收時瀏覽器自動化停在那裡等人按；而且使用者手上正在做別的事被硬生生打斷。
    原因：忘了全站鐵律。
    **面板是背景資訊**——dismiss 失敗就什麼都不做，下一次輪詢那一列會自己長回來，
    人再按一次就好。這比跳一個對話框好得多。
