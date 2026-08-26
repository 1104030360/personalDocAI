/* 資料夾歸類彈窗（modal）：把某張照片歸到某個資料夾。
   上傳頁（upload.html）與瀏覽頁（browse.html）共用這一份，全站只有這一份。

   ⚠ 一律不用 alert／confirm／prompt：那會開瀏覽器的原生對話框，
     不但擋住整個頁面，也會讓瀏覽器自動化（Playwright）停在那裡等人按。
     所有提示與錯誤都寫進彈窗裡的 <p id="fm-error">。
     （這行註解故意不在函式名後面加小括號——驗收會用 grep 掃「函式名＋左括號」，註解不能誤中。）

   ⚠ design2.md D1：彈窗是「強制決定」——沒有 ×、不吃 Esc、點暗色區也不會關。
     唯一的出口是四個明確選項；「稍後再說」＝把照片留在待決定（不呼叫任何 API）。

   用法：
     openFolderModal({
       photoId: 7,                                // 要歸類的照片 id
       folders: [{id, name, description}, …],     // ② 下拉選單（呼叫端先濾掉收件箱）
       primary: {id, name, description} 或 null,  // ① 那一個資料夾；null＝整列不顯示
       primaryVerb: "採用",                        // ① 按鈕動詞（有 primary 才用得到）
       onAssigned: function (folder) { … },       // PATCH 成功，帶回新的資料夾
       onClosed: function () { … }                // 使用者按「稍後再說」，沒有歸類
     });

   本檔不碰頁面其他部分，成功或關閉都只透過上面兩個 callback 通知呼叫方——
   所以同一份程式碼上傳頁與瀏覽頁都能用。
   樣式全部在 /ui/style.css 的「歸類彈窗」區塊（Phase 26 起本檔不再注入任何樣式）。
*/

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

let fmConfig = null;    // 這次開窗的設定（上面 openFolderModal 收到的那包）
let fmReady = false;    // 彈窗的 HTML 與事件只裝一次

// ① 記住是誰打開彈窗的，關掉時把鍵盤焦點還回去
let fmLastFocus = null;

// ② 開啟後：鎖住背景捲動、把焦點移進彈窗（Tab 才不會跑到後面的頁面去）
function fmAfterOpen() {
  fmLastFocus = document.activeElement;
  document.body.classList.add("fm-open");
  // offsetParent 為 null＝display:none（例如被隱藏的①列），跳過它
  const 第一個可聚焦 = Array.prototype.find.call(
    fmEl("fm-backdrop").querySelectorAll("button, input, select"),
    function (元素) { return 元素.offsetParent !== null; }
  );
  if (第一個可聚焦) { 第一個可聚焦.focus(); }
}

// ③ 關閉後：解除鎖定、焦點還回原本的按鈕
function fmAfterClose() {
  document.body.classList.remove("fm-open");
  if (fmLastFocus && fmLastFocus.focus) { fmLastFocus.focus(); }
  fmLastFocus = null;
}

function fmEl(id) {
  return document.getElementById(id);
}

function fmSetError(message) {
  fmEl("fm-error").textContent = message;   // 錯誤畫在頁面裡，不用 alert
}

function fmSetBusy(busy) {
  ["fm-primary", "fm-select-submit", "fm-create", "fm-later"].forEach(function (id) {
    fmEl(id).disabled = busy;               // 等回應期間三顆按鈕都不能按
  });
}

function fmHide() {
  fmEl("fm-backdrop").hidden = true;
  fmConfig = null;
  fmAfterClose();
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
    fmSetError("目前無法完成歸類。請確認服務已啟動後再試一次。");
  } finally {
    fmSetBusy(false);
  }
}

function fmInstall() {
  if (fmReady) return;

  const holder = document.createElement("div");
  holder.innerHTML = FOLDER_MODAL_HTML;   // 固定樣板字串，沒有任何外來資料
  document.body.appendChild(holder.firstElementChild);

  fmEl("fm-later").addEventListener("click", fmClose);
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
  fmReady = true;
}

function openFolderModal(config) {
  fmInstall();
  fmConfig = config;

  // 窗頂原圖（Phase 54）：每次開窗都重畫，才不會看到上一張的殘影
  fm畫圖(config.photoId);

  // ① 那顆按鈕：只有「有可用建議」時才顯示（design2.md D5/D6——
  //    待決定分頁沒有持久化的建議、AI 建議是未分類時也不顯示，交給「稍後再說」）
  const 有建議 = !!config.primary;
  fmEl("fm-primary-option").hidden = !有建議;
  if (有建議) {
    fmEl("fm-primary").textContent =
      (config.primaryVerb || "採用") + "「" + config.primary.name + "」";
    fmEl("fm-primary-desc").textContent = config.primary.description || "";
  }

  // ② 下拉選單：放「全部」資料夾（design1.md §9 的決定，資料夾多了才找得到）
  const select = fmEl("fm-select");
  select.textContent = "";
  config.folders.forEach(function (folder) {
    const option = document.createElement("option");
    option.value = folder.id;
    option.textContent = folder.name;
    if (有建議 && folder.id === config.primary.id) option.selected = true;
    select.appendChild(option);
  });

  // ③ 自建：每次開窗都清空，免得留著上一張的輸入
  fmEl("fm-name").value = "";
  fmEl("fm-desc-input").value = "";

  fmSetError("");
  fmSetBusy(false);
  fmEl("fm-backdrop").hidden = false;
  fmAfterOpen();
}
