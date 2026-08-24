/* 照片詳情彈窗（唯讀）：資料夾縮圖牆與待辦列共用這一份，全站只有這一份。

   ⚠ design4.md D2：這顆窗是「唯讀」——沒有任何改資料夾的按鈕。
     design2.md 的「定案不可逆」仍然有效，這裡不提供後悔藥。
     待決定分頁點照片走的是 folder_modal.js 的歸類鏈，不是這顆窗。
     （上面提到隔壁那份時故意不寫成完整路徑——驗收會用 grep 掃「斜線＋folder」
      來證明本檔真的不碰歸類端點，註解不能誤中。）

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

let pdReady = false;      // 樣板與事件只裝一次
let pdLastFocus = null;   // 記住是誰打開的，關掉時把鍵盤焦點還回去
let pdGeneration = 0;
let pdBackgroundInert = [];

function pdEl(id) {
  return document.getElementById(id);
}

// 小工具：造一個元素，順便把 class／id／文字填好。
// 與 browse.html 的 el() 同一個作法，只是多帶一個 id（彈窗靠 id 找元素）。
function pd造(tag, className, id, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (id) node.id = id;
  if (text) node.textContent = text;
  return node;
}

/* 窗的骨架。等價的 HTML 長這樣（外框沿用另外三顆窗的 fm-* class＝零複製樣式，
   id 一律 pd- 前綴＝行為互不相碰；style.css 檔頭第 4〜5 行寫明的既有約定）：

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

   一個一個 createElement 而不是塞一整串樣板字串：本專案的靜態檢查擋下了後者，
   而且這樣連「固定字串」的例外都不必開——全檔零 HTML 字串解析。 */
function pd建樣板() {
  const backdrop = pd造("div", "fm-backdrop", "pd-backdrop");
  backdrop.hidden = true;

  const box = pd造("div", "fm-box");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-labelledby", "pd-title");

  const 關閉鈕 = pd造("button", "pd-close", "pd-close", "×");
  關閉鈕.type = "button";
  關閉鈕.setAttribute("aria-label", "關閉");

  // 待辦那一行：只有從待辦分頁進來才顯示（Phase 40 才會用到）
  const 待辦區 = pd造("div", "pd-task", "pd-task");
  待辦區.hidden = true;
  待辦區.appendChild(pd造("p", "pd-task-title", "pd-task-title"));
  待辦區.appendChild(pd造("p", "pd-task-due", "pd-task-due"));

  box.appendChild(關閉鈕);
  box.appendChild(pd造("h3", null, "pd-title", "照片"));
  box.appendChild(待辦區);
  box.appendChild(pd造("div", "pd-image", "pd-image"));
  box.appendChild(pd造("p", "pd-text", "pd-text", "載入中…"));
  box.appendChild(pd造("dl", "pd-fields", "pd-fields"));
  box.appendChild(pd造("p", "fm-error", "pd-error"));

  backdrop.appendChild(box);
  return backdrop;
}

function pdSetError(message) {
  pdEl("pd-error").textContent = message;   // 錯誤畫在窗裡，不用 alert
}

function pd保護數字單位(text) {
  return String(text).replace(/(\d)\s+(年|月|日|元)/g, "$1\u00a0$2");
}

function pdFocusableElements() {
  const selector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    '[tabindex]:not([tabindex="-1"])'
  ].join(",");
  return Array.from(pdEl("pd-backdrop").querySelectorAll(selector)).filter(function (node) {
    return !node.hidden && node.getAttribute("aria-hidden") !== "true";
  });
}

// 開窗：鎖住背景捲動、把焦點移進窗裡（Tab 才不會跑到後面的頁面去）
function pdOpen() {
  pdLastFocus = document.activeElement;
  const backdrop = pdEl("pd-backdrop");
  backdrop.hidden = false;
  if (pdBackgroundInert.length === 0) {
    Array.from(document.body.children).forEach(function (node) {
      if (node === backdrop) return;
      pdBackgroundInert.push([node, node.inert]);
      node.inert = true;
    });
  }
  document.body.classList.add("fm-open");
  pdEl("pd-close").focus();
}

// 關窗：解除鎖定、焦點還回原本那張卡片（用鍵盤的人才不會被丟回頁面最上面）
function pdClose() {
  pdGeneration += 1;
  pdEl("pd-backdrop").hidden = true;
  document.body.classList.remove("fm-open");
  pdBackgroundInert.forEach(function ([node, wasInert]) {
    node.inert = wasInert;
  });
  pdBackgroundInert = [];
  if (pdLastFocus && pdLastFocus.focus) { pdLastFocus.focus(); }
  pdLastFocus = null;
}

function pdInstall() {
  if (pdReady) return;

  document.body.appendChild(pd建樣板());

  // 關閉方式①：右上角的 ×
  pdEl("pd-close").addEventListener("click", pdClose);

  document.addEventListener("keydown", function (event) {
    if (pdEl("pd-backdrop").hidden) return;
    if (event.key === "Escape") {
      pdClose();
      return;
    }
    if (event.key === "Tab") {
      const focusable = pdFocusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const activeInside = pdEl("pd-backdrop").contains(document.activeElement);
      if (event.shiftKey && (!activeInside || document.activeElement === focusable[0])) {
        event.preventDefault();
        focusable[focusable.length - 1].focus();
      } else if (!event.shiftKey && (!activeInside || document.activeElement === focusable[focusable.length - 1])) {
        event.preventDefault();
        focusable[0].focus();
      }
    }
  });

  // 關閉方式③：點暗色區。一定要判斷 event.target 就是 backdrop 本人——
  // 事件會從窗裡面冒泡上來，不判斷就變成「點哪裡都關」。
  pdEl("pd-backdrop").addEventListener("click", function (event) {
    if (event.target !== pdEl("pd-backdrop")) return;
    pdClose();
  });

  pdReady = true;
}

// 沒有原圖、或路徑有值但磁碟上的檔案沒了：灰底占位。
// 沿用縮圖牆既有的 .placeholder，態度一致——不假裝有圖，也不顯示瀏覽器的破圖 icon。
function pd畫占位() {
  const box = pdEl("pd-image");
  box.textContent = "";
  box.appendChild(pd造("div", "placeholder", null, "無原圖"));
}

function pd畫圖(body, generation) {
  const box = pdEl("pd-image");
  box.textContent = "";

  // design4.md D6：遷移進來的舊照片沒有 original_path，端點回 null
  if (!body.image_url) {
    pd畫占位();
    return;
  }

  const image = document.createElement("img");
  image.src = body.image_url;              // 例如 /photos/7/image
  image.alt = body.text;
  // §9 錯誤表第 3 列：JSON 給了網址、檔案卻被刪了 → 降級成占位，不是整窗 404
  image.addEventListener("error", function () {
    if (generation !== pdGeneration) return;
    pd畫占位();
  });
  box.appendChild(image);
}

// D4：四欄都要畫出來，空的寫「無」。
// 陣列要注意兩件事：空陣列 [] 在 JS 裡是 truthy（所以判 length，不能直接判真假），
// 直接丟給 textContent 會印成「可樂,洋芋片」（所以自己用頓號串）。
function pd值或無(value) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "無";
  return (value === null || value === undefined || value === "") ? "無" : value;
}

function pd畫四欄(metadata) {
  const fields = pdEl("pd-fields");
  fields.textContent = "";

  // 順序與標籤固定（design4.md §4.2 第 4 點）
  const 四欄 = [
    ["類別", metadata.category],
    ["地點", metadata.location],
    ["物品", metadata.items],
    ["內容日期", metadata.content_time]
  ];

  四欄.forEach(function (一欄) {
    fields.appendChild(pd造("dt", null, null, 一欄[0]));
    // 一律 textContent：AI 寫的內容可能有 < 之類的符號
    fields.appendChild(pd造("dd", null, null, pd保護數字單位(pd值或無(一欄[1]))));
  });
}

async function openPhotoDetailModal(config) {
  pdInstall();
  const generation = ++pdGeneration;

  // ① 每次開窗都從乾淨狀態開始，否則第二次開窗會看到上一張的圖或上一次的紅字。
  //    待辦那一行只有從待辦分頁進來才畫（design4.md §4.2 第 1 點）：
  //    資料夾牆進來時 config.task 是 null，整區隱藏——同一顆窗，兩種入口。
  //    這一段刻意在 fetch **之前**：標題與到期日是清單帶進來的現成資料，
  //    使用者按下去的當下就該看得到，不必陪著下面的圖一起等。
  const 待辦 = config.task || null;
  pdEl("pd-title").textContent = 待辦 ? "待辦來源照片" : "照片";
  pdEl("pd-task").hidden = !待辦;
  if (待辦) {
    pdEl("pd-task-title").textContent = 待辦.title;
    pdEl("pd-task-due").textContent = pd保護數字單位(
      待辦.due_date ? "到期 " + 待辦.due_date : "無到期日"
    );
  }
  pdEl("pd-image").textContent = "";
  pdEl("pd-fields").textContent = "";
  pdSetError("");
  pdEl("pd-text").textContent = "載入中…";
  pdEl("pd-backdrop").querySelector(".fm-box").scrollTop = 0;
  pdOpen();

  // ② 抓這一張的完整說明（Phase 38 的端點）。
  //    不管下面走哪一條路，窗都留在開著的狀態——使用者要看得到發生了什麼事。
  let response;
  try {
    response = await fetch("/photos/" + config.photoId);
  } catch (error) {
    if (generation !== pdGeneration) return;
    // ⑤ 伺服器沒開、網路斷：fetch 本身就丟例外，連 status 都沒有
    pdEl("pd-text").textContent = "";
    pdSetError("目前無法載入照片。請確認服務已啟動後，關閉視窗再試一次。");
    return;
  }

  if (generation !== pdGeneration) return;
  if (response.status === 404) {          // ④ 沒這張照片
    pdEl("pd-text").textContent = "";
    pdSetError("找不到這張照片");
    return;
  }
  if (!response.ok) {                     // 其他非 200（例如 500）：照樣寫在窗裡
    pdEl("pd-text").textContent = "";
    pdSetError("載入失敗（HTTP " + response.status + "）");
    return;
  }

  // ③ 200：畫圖 ＋ 說明 ＋ 四欄
  let body;
  try {
    body = await response.json();
  } catch (error) {
    if (generation !== pdGeneration) return;
    pdEl("pd-text").textContent = "";
    pdSetError("照片資料無法讀取。請關閉視窗再試一次。");
    return;
  }
  if (generation !== pdGeneration) return;
  pd畫圖(body, generation);
  // text 永遠顯示、不必判斷空不空（VLM 看不懂時上傳是 422 什麼都不存，
  // 資料庫裡不存在 text 空白的照片）。這一行順便把上面的「載入中…」蓋掉。
  pdEl("pd-text").textContent = pd保護數字單位(body.text);
  pd畫四欄(body.metadata);
}
