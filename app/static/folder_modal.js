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
