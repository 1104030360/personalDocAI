/* 實體釘選彈窗（modal）：把某張照片釘上一或多個實體（design3.md D12、§2.1 的彈窗 2）。
   待決定頁（pending.html）是唯一的呼叫端——增量五 D13 之後上傳改非同步，
   上傳頁與鏡頭桌面頁都不再於入庫當下開鏈（Phase 68／69），三關彈窗只在待決定頁走；
   與 folder_modal.js 互不相碰——id 用 em- 前綴，樣式 class 沿用 fm-*（三個彈窗共用的視覺語言）。

   ⚠ 一律不用 alert／confirm／prompt（理由同 folder_modal.js 檔頭）。
     所有提示與錯誤都寫進彈窗裡的 <p id="em-error">／<p id="em-note">。

   與抽屜彈窗（design2 的強制窗）不同，實體窗**可以略過**：
   ④「不釘，繼續」隨時能走；但出口仍只有明確按鈕，不吃 Esc、點暗色區也不會關——
   三個彈窗行為一致，也少一套監聽。

   用法：
     openEntityModal({
       photoId: 7,                                 // 要釘的照片 id
       entities: [{id, name, description}, …],     // ② 下拉（完整實體清單；空清單＝②整列不顯示）
       suggested: {id, name, description} 或 null, // ① AI 建議；null＝整列不顯示（待決定分頁進來都是 null）
       onDone: function (pinnedList) { … }         // 使用者按④離開；帶這一輪釘上的實體陣列（可為空）
     });

   釘上（①②③）成功後**窗不關**：已釘列表 +1、下拉換成回應裡的最新清單（③自創會 +1）、
   可以繼續釘下一個；「再建議一個」會拿已釘＋已建議的 id 當 exclude 去要下一個建議。
*/

const ENTITY_MODAL_HTML = `
<div class="fm-backdrop" id="em-backdrop" hidden>
  <div class="fm-box" role="dialog" aria-modal="true" aria-labelledby="em-title">
    <h3 id="em-title">要把這張照片釘上實體嗎？（可釘多個）</h3>

    <div class="fm-option" id="em-pinned-option" hidden>
      <p class="fm-desc" id="em-pinned"></p>
    </div>

    <div class="fm-option" id="em-primary-option">
      <button type="button" id="em-primary">（載入中）</button>
      <p class="fm-desc" id="em-primary-desc"></p>
    </div>

    <div class="fm-option" id="em-select-option">
      <label for="em-select">改選其他現有實體：</label><br>
      <select id="em-select"></select>
      <button type="button" id="em-select-submit">釘上這個實體</button>
    </div>

    <div class="fm-option">
      <label for="em-name">自創新實體：</label><br>
      <input type="text" id="em-name" placeholder="名稱，例如：我的 MacBook">
      <input type="text" id="em-desc-input" placeholder="說明：這是哪一件東西">
      <button type="button" id="em-create">建立並釘上</button>
    </div>

    <div class="fm-option">
      <button type="button" id="em-more">再建議一個</button>
      <button type="button" id="em-skip">不釘，繼續</button>
      <p class="fm-desc">不想釘就直接繼續；已釘上的會保留。</p>
    </div>

    <p class="fm-desc" id="em-note"></p>
    <p class="fm-error" id="em-error"></p>
  </div>
</div>
`;

let emConfig = null;      // 這次開窗的設定（上面 openEntityModal 收到的那包）
let emReady = false;      // 彈窗的 HTML 與事件只裝一次
let emPinned = [];        // 這一輪已釘上的實體（照釘的順序）
let emSuggested = null;   // 目前①顯示的建議（null＝①隱藏）
let emEntities = [];      // 目前②下拉的完整實體清單（釘選回應會更新它）

// 開關前後的焦點與背景捲動處理，與 folder_modal 同一套（class 也共用 fm-open）
let emLastFocus = null;

function emAfterOpen() {
  emLastFocus = document.activeElement;
  document.body.classList.add("fm-open");
  const 第一個可聚焦 = Array.prototype.find.call(
    emEl("em-backdrop").querySelectorAll("button, input, select"),
    function (元素) { return 元素.offsetParent !== null; }
  );
  if (第一個可聚焦) { 第一個可聚焦.focus(); }
}

function emAfterClose() {
  document.body.classList.remove("fm-open");
  if (emLastFocus && emLastFocus.focus) { emLastFocus.focus(); }
  emLastFocus = null;
}

function emEl(id) {
  return document.getElementById(id);
}

function emSetError(message) {
  emEl("em-error").textContent = message;  // 錯誤畫在彈窗裡，不用 alert
}

function emSetNote(message) {
  emEl("em-note").textContent = message;   // 非錯誤的提示（例如「沒有其他適合的實體了」）
}

function emSetBusy(busy) {
  ["em-primary", "em-select-submit", "em-create", "em-more", "em-skip"].forEach(
    function (id) { emEl(id).disabled = busy; }
  );
  emEl("em-select").disabled = busy;
  emEl("em-name").disabled = busy;
  emEl("em-desc-input").disabled = busy;
}

// 與 folder_modal 的 fmDetailText 刻意重複這十行：兩份彈窗檔各自獨立、互不 import，
// 少這一點共用換來「改一個彈窗絕不會弄壞另一個」。
function emDetailText(payload) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (one) {
      return one.msg || JSON.stringify(one);
    }).join("；");
  }
  return JSON.stringify(payload);
}

// ---------- 畫面三塊的重繪（狀態改變後各自呼叫）----------

function emRenderPinned() {
  const 有釘 = emPinned.length > 0;
  emEl("em-pinned-option").hidden = !有釘;
  emEl("em-pinned").textContent = 有釘
    ? "已釘上：" + emPinned.map(function (e) { return e.name; }).join("、")
    : "";
  // ④ 的字跟著這一輪的成果變：一個都沒釘＝「不釘」，釘過＝「完成」
  emEl("em-skip").textContent = 有釘 ? "完成，繼續" : "不釘，繼續";
}

function emRenderPrimary() {
  const 有建議 = !!emSuggested;
  emEl("em-primary-option").hidden = !有建議;
  if (有建議) {
    emEl("em-primary").textContent = "釘上「" + emSuggested.name + "」";
    emEl("em-primary-desc").textContent = emSuggested.description || "";
  }
}

function emRenderSelect() {
  // 實體清單一開始是空的（不像資料夾有種子），空清單時整列藏起來——只剩③④
  emEl("em-select-option").hidden = emEntities.length === 0;
  const select = emEl("em-select");
  select.textContent = "";
  emEntities.forEach(function (entity) {
    const option = document.createElement("option");
    option.value = entity.id;
    option.textContent = entity.name;
    if (emSuggested && entity.id === emSuggested.id) option.selected = true;
    select.appendChild(option);
  });
}

// ---------- 兩個會打 API 的動作 ----------

async function emPin(body) {
  if (!emConfig) return;
  emSetError("");
  emSetNote("");
  emSetBusy(true);
  try {
    const response = await fetch("/photos/" + emConfig.photoId + "/entities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const payload = await response.json();

    if (response.status === 201) {
      // 窗不關：記下這一個、換上最新清單（③自創會讓清單 +1），讓人繼續釘下一個
      emPinned.push(payload.entity);
      emEntities = payload.entities;
      if (emSuggested && emSuggested.id === payload.entity.id) {
        emSuggested = null;               // 建議的那顆釘掉了，①就功成身退
      }
      emEl("em-name").value = "";
      emEl("em-desc-input").value = "";
      emRenderPinned();
      emRenderPrimary();
      emRenderSelect();
      return;
    }
    // 409＝重名或已釘過；422＝名稱空白或兩種 body 都給；404＝照片或實體不存在
    emSetError("（HTTP " + response.status + "）" + emDetailText(payload));
  } catch (error) {
    emSetError("請求失敗：" + error + "（uvicorn 是不是沒在跑？）");
  } finally {
    emSetBusy(false);
  }
}

async function emAskForMore() {
  if (!emConfig) return;
  emSetError("");
  emSetNote("");
  emSetBusy(true);
  try {
    // exclude＝已釘上的＋①正在顯示的：都看過了，AI 要嘛給新的、要嘛承認沒了
    const exclude = emPinned.map(function (e) { return e.id; });
    if (emSuggested) exclude.push(emSuggested.id);

    const response = await fetch(
      "/photos/" + emConfig.photoId + "/entity-suggestion",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ exclude: exclude })
      }
    );
    const payload = await response.json();

    if (response.status === 200) {
      if (payload.suggested_entity) {
        emSuggested = payload.suggested_entity;
        emRenderPrimary();
        emRenderSelect();                 // 下拉順便跳到新建議，跟開窗時的預選一致
      } else {
        emSuggested = null;
        emRenderPrimary();
        emSetNote("沒有其他適合的實體了。");
      }
      return;
    }
    emSetError("（HTTP " + response.status + "）" + emDetailText(payload));
  } catch (error) {
    emSetError("請求失敗：" + error + "（uvicorn 是不是沒在跑？）");
  } finally {
    emSetBusy(false);
  }
}

// ---------- 安裝與開窗 ----------

function emInstall() {
  if (emReady) return;

  const holder = document.createElement("div");
  holder.innerHTML = ENTITY_MODAL_HTML;   // 固定樣板字串，沒有任何外來資料
  document.body.appendChild(holder.firstElementChild);

  emEl("em-primary").addEventListener("click", function () {
    emPin({ entity_id: emSuggested.id });
  });
  emEl("em-select-submit").addEventListener("click", function () {
    emPin({ entity_id: Number(emEl("em-select").value) });
  });
  emEl("em-create").addEventListener("click", function () {
    emPin({
      name: emEl("em-name").value,
      description: emEl("em-desc-input").value
    });
  });
  emEl("em-more").addEventListener("click", emAskForMore);
  emEl("em-skip").addEventListener("click", function () {
    // 先把 callback 與成果拿出來再收窗（收窗會清掉 emConfig）
    const onDone = emConfig && emConfig.onDone;
    const pinned = emPinned.slice();
    emEl("em-backdrop").hidden = true;
    emConfig = null;
    emAfterClose();
    if (onDone) onDone(pinned);
  });
  emReady = true;
}

function openEntityModal(config) {
  emInstall();
  emConfig = config;
  emPinned = [];
  emSuggested = config.suggested || null;
  emEntities = config.entities || [];

  emEl("em-name").value = "";
  emEl("em-desc-input").value = "";
  emRenderPinned();
  emRenderPrimary();
  emRenderSelect();
  emSetNote("");
  emSetError("");
  emSetBusy(false);
  emEl("em-backdrop").hidden = false;
  emAfterOpen();
}
