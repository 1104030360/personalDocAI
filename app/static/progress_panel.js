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
  // attempt=0 的窗＝任務剛開跑還沒送第一次 VLM；顯示上當第 1 次
  // （2026-08-26 執行者裁決：前端 Math.max(attempt,1) 顯示保護，零後端改動。
  //   run_ingest_job() 一進門就把 status 改成 analyzing，attempt 卻要等
  //   _understand_and_embed() 的迴圈才寫成 1；PDF 拆頁期間那一段肉眼可見。）
  段.push("分析中（第 " + Math.max(job.attempt, 1) + " 次）");
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
