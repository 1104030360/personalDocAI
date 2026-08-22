/* 待辦確認彈窗（modal）：把 VLM 建議的待辦寫進待辦清單（design3.md D13、§2.1 的彈窗 3）。
   只有上傳頁（upload.html）用得到——待決定分頁的補完鏈沒有持久化的建議，
   判不出「有沒有 actionable」，所以那條鏈不開這一窗（增量三總覽 §5 已知限制）。

   ⚠ 一律不用 alert／confirm／prompt（理由同 folder_modal.js 檔頭）。
     錯誤寫進彈窗裡的 <p id="tm-error">。

   id 用 tm- 前綴、樣式 class 沿用 fm-*（三個彈窗共用的視覺語言，見 style.css 檔頭）。
   「人確認才落庫」（design3.md D3）：按「建立待辦」才 POST；「略過」什麼都不打。
   兩顆按鈕就是僅有的出口——不吃 Esc、點暗色區不會關，三窗行為一致。

   用法：
     openTaskModal({
       photoId: 7,                                  // 來源照片 id
       suggestion: {title: "…", due: "2026-09-18" 或 null},  // 呼叫端保證有 title 才開窗
       onDone: function (createdTask 或 null) { … }  // 建立成功帶 TaskOut；略過帶 null
     });

   標題與到期日都放在輸入框裡（預填建議值）——AI 抽得不準的，人改完再按建立。
*/

const TASK_MODAL_HTML = `
<div class="fm-backdrop" id="tm-backdrop" hidden>
  <div class="fm-box" role="dialog" aria-modal="true" aria-labelledby="tm-title">
    <h3 id="tm-title">這張照片裡有一件待辦？</h3>

    <div class="fm-option">
      <label for="tm-title-input">待辦內容（可修改）：</label><br>
      <input type="text" id="tm-title-input" placeholder="例如：交 Project 2">
    </div>

    <div class="fm-option">
      <label for="tm-due">到期日（沒有就留白）：</label><br>
      <input type="date" id="tm-due">
    </div>

    <div class="fm-option">
      <button type="button" id="tm-create">建立待辦</button>
      <button type="button" id="tm-skip">略過</button>
      <p class="fm-desc">按「建立」才會寫入；略過的話這張就只是一張照片。</p>
    </div>

    <p class="fm-error" id="tm-error"></p>
  </div>
</div>
`;

let tmConfig = null;    // 這次開窗的設定
let tmReady = false;    // HTML 與事件只裝一次

// 焦點與背景捲動處理與另外兩窗同一套（class 共用 fm-open）
let tmLastFocus = null;

function tmAfterOpen() {
  tmLastFocus = document.activeElement;
  document.body.classList.add("fm-open");
  const 第一個可聚焦 = Array.prototype.find.call(
    tmEl("tm-backdrop").querySelectorAll("button, input"),
    function (元素) { return 元素.offsetParent !== null; }
  );
  if (第一個可聚焦) { 第一個可聚焦.focus(); }
}

function tmAfterClose() {
  document.body.classList.remove("fm-open");
  if (tmLastFocus && tmLastFocus.focus) { tmLastFocus.focus(); }
  tmLastFocus = null;
}

function tmEl(id) {
  return document.getElementById(id);
}

function tmSetError(message) {
  tmEl("tm-error").textContent = message;  // 錯誤畫在彈窗裡，不用 alert
}

function tmSetBusy(busy) {
  ["tm-create", "tm-skip"].forEach(function (id) { tmEl(id).disabled = busy; });
  tmEl("tm-title-input").disabled = busy;
  tmEl("tm-due").disabled = busy;
}

// 與 folder_modal／entity_modal 刻意重複這十行（三檔互不 import，理由見 entity_modal.js）
function tmDetailText(payload) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (one) {
      return one.msg || JSON.stringify(one);
    }).join("；");
  }
  return JSON.stringify(payload);
}

function tmHide() {
  tmEl("tm-backdrop").hidden = true;
  tmConfig = null;
  tmAfterClose();
}

async function tmCreate() {
  if (!tmConfig) return;
  tmSetError("");
  tmSetBusy(true);
  try {
    const response = await fetch("/photos/" + tmConfig.photoId + "/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: tmEl("tm-title-input").value,
        due_date: tmEl("tm-due").value || null   // 空字串＝沒有到期日
      })
    });
    const payload = await response.json();

    if (response.status === 201) {
      const onDone = tmConfig.onDone;
      tmHide();
      if (onDone) onDone(payload);
      return;
    }
    // 422＝標題空白或到期日格式錯；409＝這張照片已經有待辦；404＝照片不存在
    tmSetError("（HTTP " + response.status + "）" + tmDetailText(payload));
  } catch (error) {
    tmSetError("請求失敗：" + error + "（uvicorn 是不是沒在跑？）");
  } finally {
    tmSetBusy(false);
  }
}

function tmInstall() {
  if (tmReady) return;

  const holder = document.createElement("div");
  holder.innerHTML = TASK_MODAL_HTML;     // 固定樣板字串，沒有任何外來資料
  document.body.appendChild(holder.firstElementChild);

  tmEl("tm-create").addEventListener("click", tmCreate);
  tmEl("tm-skip").addEventListener("click", function () {  // 略過：不打任何 API
    const onDone = tmConfig && tmConfig.onDone;
    tmHide();
    if (onDone) onDone(null);
  });
  tmReady = true;
}

function openTaskModal(config) {
  tmInstall();
  tmConfig = config;

  // 預填建議值——AI 抽的只是草稿，欄位都可以改（design3.md D13：有才抽、人按建立才寫）
  tmEl("tm-title-input").value = config.suggestion.title || "";
  tmEl("tm-due").value = config.suggestion.due || "";

  tmSetError("");
  tmSetBusy(false);
  tmEl("tm-backdrop").hidden = false;
  tmAfterOpen();
}
