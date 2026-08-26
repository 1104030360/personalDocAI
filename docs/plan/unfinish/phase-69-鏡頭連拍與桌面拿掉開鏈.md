# Phase 69：鏡頭連拍與桌面拿掉開鏈

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 手機端 `POST` 拿到 **202** 就放行下一拍（進度用**窄條**顯示、不擋快門）；
> 桌面端 `camera-desk.html` **刪掉「拿最後一張 → 開三關彈窗鏈」那一段**，進度改走全站面板。
> **WebRTC 預覽、QR、快門、閃光一個字都不准改。**

**為什麼要做這個：**

現在用手機當無線鏡頭拍東西是這個節奏：

```text
按快門 → 手機卡住（HTTP 請求就是要等 VLM 看完圖）→ 2〜5 分鐘 →
電腦跳出抽屜彈窗 → 選資料夾 → 實體窗 → 待辦窗 → 這時才能拍第二張
```

要把桌上一疊十張收據掃進系統，中間要來回二十次、耗掉半小時，而且**人不能離開電腦**。

階段乙（Phase 63）已經把 `POST /camera/{token}/photos` 改成 **202「已收下」**——
它現在只做三件事（驗 token、檢查格式、落 staging 入列），幾十毫秒就回。
Phase 67 也做好了右下角的全站進度面板。

本 phase 把手機與桌面接到那條新路上：**拍、拍、拍、拍，十張三十秒拍完，人就可以走了。**
分析在背景排隊跑，完成的照片會自己出現在「待決定」，晚點再一次歸類。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **202 Accepted** | HTTP 狀態碼，字面意思是「**收下了，但還沒做完**」。跟 201 Created（已經建好了）刻意不同。design5 D7 選它就是為了讓「收下 ≠ 已入庫」在協定層講清楚。 |
| **窄條** | 一行高的細長提示條。本 phase 把它夾在取景畫面與狀態列之間——**不是**蓋在畫面上的浮層，所以絕對不會壓到下緣那三顆按鈕（design5 §6.5 的「不擋快門」）。 |
| **競態（race condition）** | 兩件事同時發生、誰先誰後不一定，結果就跟著不一定。本 phase 的例子：上一張還在送，你又按了一次快門。防法是一個「正在送」的旗標（`cp上傳中`），不是只把按鈕變灰——因為電腦那邊透過 WebSocket 送來的快門指令**根本不經過按鈕**。 |
| **Bonjour 主機名／`.local`** | macOS 內建的「同一個區網裡用名字找機器」機制（技術名叫 mDNS）。你的 Mac 有一個名字例如 `Timmy-MacBook`，同一個 Wi-Fi 裡的裝置可以直接用 `Timmy-MacBook.local` 連到它，**不必知道 IP**。好處：換 Wi-Fi、IP 變了，網址完全不用改。 |
| **SAN（Subject Alternative Name）** | 憑證裡「這張憑證可以用在哪些網址／IP」的清單。`mkcert` 產憑證時把 `.local` 名字與當下的 IP 都寫進去；用清單外的網址開就會跳憑證警告。 |
| **`getSettings()` 復驗** | 既有程式碼裡的一招（Phase 36）：叫瀏覽器打開閃光之後，回頭問「你真的打開了嗎」，答案不是 `true` 就當作不支援。iOS Safari 會「靜默成功」，不復驗的話 UI 會說謊。**本 phase 不碰這段**，只是提醒你別手滑刪掉。 |

---

## 1. 對應 design5.md 章節

- **D4**（鏡頭連拍：手機快門不必等 VLM，拍完就能再拍；與電腦上傳走**同一條**佇列）
- **D13**（上傳當下不開歸類鏈：電腦上傳與**鏡頭桌面**都不再開抽屜→實體→待辦）
- **§1.1 鏡頭桌面那一列**（倒數第三列：推翻「鏡頭桌面 uploaded → GET latest → 三關彈窗鏈」）
- **§2 流程**的「或 無線鏡頭：人按快門，一張一張 POST」與「你立刻可以再選檔／再拍」
- **§5 API 契約**第 2、3 列（`POST /camera/{token}/photos`：先驗 token（404）再驗格式（415），
  成功 **202**、**不再** `set_latest`；`GET /camera/{token}/latest` 行為變窄、桌面不再靠它開鏈）
- **§5 末段**（手機端在 202 之後即可再拍；可繼續送 `uploaded` 通知桌面，
  但桌面**只更新進度／預覽狀態，不開 `classify_chain`**）
- **§6.5 鏡頭**（`camera-phone.html`：202 就允許下一拍、進度用窄條不擋快門；
  `camera-desk.html`：刪「GET latest → classify_chain」、進度走全站面板、
  **WebRTC 預覽、QR、快門、閃光不改**）
- **§8 錯誤表第 2 列**（鏡頭 token 無效／過期 → HTTP 立刻 404，不讀檔）
- **§9 測試策略**（前端不新增 Playwright；QR 尺寸那顆不准改小）
- **§12 階段丙**第 4 條（**手機連拍至少 2 張不必等第一張看完；桌面不跳出歸類鏈**）
- **§13 風險**第 4 條（鏡頭 token 仍在 app 記憶體；重啟 app＝配對失效，
  但**已 202 的檔由 worker 繼續做完，不依賴 token**）

---

## 2. 前置條件

**必須先完成的 phase：**

| Phase | 為什麼需要 |
|---|---|
| **63** | `POST /camera/{token}/photos` 已經回 **202**、不再 `set_latest`；`GET …/latest` 已變窄。還在回 201 的話手機端整段判斷都是錯的。 |
| **67** | 右下角全站進度面板已經在跑、`ppStart()` 已是全域函式、`camera-desk.html` 已經掛了 `progress_panel.js`。 |
| **68** | 不是硬相依，但強烈建議先做完——兩個 phase 都在拆 `classify_chain` 的呼叫點，一起驗收比較好對照。 |
| **★ G2** | design5 §0 的閘門：階段乙已由產品負責人驗收通過。 |

**開工前先做這五件事：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 抄下測試基線。本 phase 會 +3 顆。
pytest -q          # 把 "N passed" 的 N 抄在這裡 → N = ______

# ①.5 抄下開工前的工作區狀態（§6.1 最後一項要拿它對「本 phase 動了哪些檔」——
#      增量五的各 phase 若尚未 commit，git status 會混著前面 phase 的變更）
git status --short -- app tests > /tmp/p69-before.txt

# ② 確認鏡頭端點真的回 202 了（先建一個 session 拿 token）
TOKEN=$(curl -sk -X POST https://127.0.0.1:8000/camera/session | python -c \
  "import sys,json; print(json.load(sys.stdin)['token'])")
screencapture -x /tmp/cam.png
curl -sk -o /dev/null -w "%{http_code}\n" -X POST \
  "https://127.0.0.1:8000/camera/$TOKEN/photos" -F "file=@/tmp/cam.png;type=image/png"
#   預期：202
#   ⚠ 如果是 201，代表 Phase 63 沒完成，先回頭補，不要硬寫前端。

# ③ 確認 QR 尺寸那顆測試現在是綠的（本 phase 不准把它弄紅）
pytest "tests/integration/test_camera_endpoints.py::test_qr的顯示尺寸夠大讓長網址也掃得到" -q

# ④ 確認 progress_panel.js 已經掛在桌面頁上（Phase 67 的成果）
grep -n "progress_panel.js" app/static/camera-desk.html
```

**真機驗收要準備的（產品負責人那一關會用到，先看一眼）：**

```bash
# 這台 Mac 的 Bonjour 主機名（不含 .local）
scutil --get LocalHostName

# 日常網址就固定用這一串——換 Wi-Fi、IP 變了都不必改網址、也不必重簽憑證
echo "https://$(scutil --get LocalHostName).local:8000/ui/camera-desk.html"

# 憑證涵蓋了哪些位址（應該同時看得到 .local 名字與某個 IP）
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
```

---

## 3. 範圍

### ⚠⚠ 醒目區塊：這些**一個字都不准改** ⚠⚠

> ```text
>  ┌──────────────────────────────────────────────────────────────────────┐
>  │  design5.md §6.5 原文：「WebRTC 預覽、QR、快門、閃光**不改**」        │
>  ├──────────────────────────────────────────────────────────────────────┤
>  │  camera-desk.html（行號＝增量五開工前；53／67 之後整體約 +2 行）      │
>  │    第 157〜181  建立配對()          ← 含 QR 的 innerHTML，整段不動    │
>  │    第 183〜209  開信令()            ← WebSocket 生命週期，整段不動    │
>  │    第 237〜284  收到offer／收到ice／加入ice  ← WebRTC，整段不動       │
>  │    第 286〜309  capture／switch／torch 三顆按鈕的監聽 ← 整段不動      │
>  │    第 320〜334  閃光可用()／閃光不支援()  ← 能力回報制，整段不動      │
>  │    第 100〜156  DOM 參照、狀態變數、esc()、連線狀態()、遙控可用()、送() │
>  │                 ← 既有各行一字不動（§4.4 ② 只會在第 123 行後**插入**  │
>  │                   一個新變數，不改任何一行舊碼）                      │
>  │                                                                      │
>  │  camera-phone.html（53／67 都不碰這一頁，行號不會漂）                 │
>  │    第  80〜120  開鏡頭()（getUserMedia／facingMode／解析度）← 不動    │
>  │    第 122〜165  信令與處理訊息() 前半（開信令／desk-ready／answer／   │
>  │                 ice／capture／switch／torch 各分支）← 不動            │
>  │    第 166〜172  處理訊息() 的 retake 分支 ← ⚠ 本 phase §4.2 ④ 唯一    │
>  │                 要改的例外：只改註解與文案，結構與 guard 不動         │
>  │    第 175〜213  開始協商()／收到answer()／收到ice()／加入ice() ← 不動 │
>  │    第 215〜274  切換鏡頭()／更新閃光能力()／回報閃光能力()／設定閃光() │
>  │                 ／閃光不支援()                          ← 整段不動    │
>  │    第 286〜299  canvas 擷取那五行（原尺寸畫幀 → toBlob JPEG 0.92）    │
>  │                 ← 一字不動（§4.2 ③ 換掉整個 快門() 時原樣照抄回去）   │
>  │    第 333〜347  啟動()（先接信令再開鏡頭的順序）        ← 整段不動    │
>  │                                                                      │
>  │  style.css                                                           │
>  │    .cd-qr svg { … max-width: 20rem; }   ← **絕對不准改小**（見下表）  │
>  │    .cd-video-box／.cd-controls／.cp-stage／.cp-controls  ← 不動       │
>  └──────────────────────────────────────────────────────────────────────┘
> ```

### 做

1. `app/static/camera-phone.html`：
   - 加一條**窄條** `<p class="cp-bar" id="cp-bar" hidden>`（夾在取景區與狀態列之間）
   - `快門()`：`201` → **`202`**；成功後 `cp已送出 += 1`、更新窄條、放行下一拍
   - `上傳結束()`：失敗時把窄條收回去
   - 提示文案改成「拍完立刻可以再拍」
2. `app/static/camera-desk.html`：
   - **刪掉** `收到照片()` 裡的「拿最後一張 → `startClassifyChain`」整段，換成計數＋`ppStart()`
   - **刪掉** `renderResult()`（只有鏈在用），換成 `渲染收下()`
   - **刪掉** 四行 `<script src>`（`folder_modal`／`entity_modal`／`task_modal`／`classify_chain`）
   - 改三處文案（`<p class="lead">`、`uploading` 狀態、`retake` 提示）
3. `app/static/style.css`：新增 `.cp-bar` 三條規則（手機頁窄條）。
4. `tests/integration/test_progress_panel_contract.py` **尾端追加**三顆契約測試
   （Phase 67 已建好這個檔，本 phase **不新建檔案**）。
5. **保留「手機 → 桌面」的 `uploaded` WS 通知——design5 §5 末段說「**可**繼續送」，
   phase-00 §10 缺口表第 4 列指名要本 phase 裁決；本 phase 裁決：做。**
   理由有二：（a）桌面按快門後的解鎖靠它——`收到照片()` 的 `等照片(false)`；
   不送的話，從電腦按快門會讓桌面的「按快門」**永遠鎖死**（沒有別的訊息會解鎖它）；
   （b）桌面「這次配對已收下 N 張」的計數也靠它。
   桌面收到後**只**更新計數與進度面板（`ppStart()`），不開任何彈窗——
   design5 §5 末段「桌面只更新進度／預覽狀態」是硬規定，§4.4 ⑤ 就是它的落地。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| **把 `.cd-qr svg` 的 `max-width: 20rem` 改小** | 這是**增量四唯一一次改產品 CSS**，2026-08-25 真機踩過：15rem 時 `.local` 那版網址的 QR 每格只剩 4.5px，**iPhone 掃不到**——而且 QR 畫得出來、只是掃不進去，是「安靜壞掉」的那種 bug。`test_camera_endpoints.py::test_qr的顯示尺寸夠大讓長網址也掃得到` 把它釘死了（design5 §9 末條也再寫一次）。驗證指令見 §6.1 |
| 動 WebRTC／QR／快門擷取／閃光的任何一行 | design5 §6.5 明文「不改」。那幾段是 Phase 36 真機調出來的，改壞了沒有自動化測試接得住 |
| 把 `建立配對()` 裡的 `if (response.status !== 201)` 一起改成 202 | **那是 `POST /camera/session`，它仍然回 201**（design5 §5 沒有改它）。這是本 phase 最容易手滑的一行，見 §7 陷阱 1 |
| 在 `camera-phone.html` 掛 `progress_panel.js` | Phase 67 §4.7 的裁決：手機頁是全螢幕取景，右下角固定面板會壓到 `.cp-controls` 的「開閃光」。手機的進度就是本 phase 的窄條 |
| 手機端輪詢 `GET /ingest-jobs` | `phase-00-增量五總覽.md` 的「文件落差」表說手機**可以**打同一支 API（只是不准把整個面板疊在取景上），但本 phase 選**連打都不打**：① 手機不需要知道 worker 第幾次嘗試——那是坐在電腦前的人要看的；② 那個數字對「我剛剛那張送出去了沒」完全沒有幫助（送出去 ≠ 分析完）；③ 手機常常是行動網路／訊號邊緣，每 2 秒一個請求只是白耗電。窄條只講純本地的「我送出去幾張」，零額外請求、零新的失敗模式 |
| 刪掉 `folder_modal.js`／`entity_modal.js`／`task_modal.js` | **不要刪檔**。design5 §2 末句：「檔案可留著給待決定頁組鏈」——Phase 70 的待決定頁三關就是靠這三個窗 |
| 刪掉 `classify_chain.js`（就算本 phase 做完它已經零呼叫者了） | 刪除的動作**留給 Phase 70 §4.5**——那裡有一道 `grep` 閘門，而且要先確認「待決定頁自己組鏈」那條路真的走通了才刪。本 phase 提早刪掉，等於把「還有沒有人在用」這個判斷做在資訊不足的時候 |
| 讓桌面在 `uploaded` 之後開任何彈窗 | design5 D13＋§5 末段：桌面**只更新進度／預覽狀態** |
| 桌面繼續打 `GET /camera/{token}/latest` | §5 第 3 列：入列不再寫 latest，桌面不再靠它。留著只會拿到 204 然後走錯誤分支 |
| 做「重拍就把上一張刪掉」 | 全系統沒有刪除照片端點（design5 §3「不做」）。重拍＝回到取景再拍一張新的，已收下的那張留在佇列裡 |
| 做手機端的失敗重試按鈕 | design5 §3「不做」第 2 條：自動 3 次已經做完 |
| 加 STUN／TURN、做多手機同時配對、Auto Capture | design5 §1.2 與 design3 的「明確不做」全部仍然有效 |
| 用 `alert`／`confirm`／`prompt` | 全站鐵律。手機端所有訊息寫進 `#cp-status`／`#cp-bar`，桌面端寫進 `#cd-link`／`#cd-result` |
| 為這兩頁新增 Playwright 自動化測試 | design5 §9 明文、Phase 36 的前例：真鏡頭／WebRTC 不自動化，真機驗收由產品負責人手動 |

---

## 4. 實作步驟

### 4.1 `camera-phone.html`：加窄條的 HTML（一行）

- [ ] 找到第 14〜19 行：

```html
<div class="cp-stage">
  <!-- playsinline：iPhone 才不會把影片搶去全螢幕播；muted 才准自動播 -->
  <video id="cp-video" autoplay playsinline muted></video>
</div>

<p class="cp-status" id="cp-status" aria-live="polite">正在開啟鏡頭…</p>
```

- [ ] 在 `</div>` 與 `<p class="cp-status">` 之間插入這三行：

```html
<!-- 送出進度的窄條（design5 §6.5）：一行高，夾在取景區與狀態列之間。
     刻意**不是**蓋在畫面上的浮層——下緣那三顆按鈕永遠不會被壓到（「不擋快門」）。 -->
<p class="cp-bar" id="cp-bar" hidden></p>
```

- [ ] 順手把第 27 行的提示文案換掉（**改版前是「接著到電腦上完成歸類」，現在不是了**）：

```html
<p class="cp-hint" id="cp-hint">快門電腦那邊也能按。拍完會<strong>立刻送出</strong>，不必等——可以連續拍。
分析在背景進行，完成的照片會出現在電腦的「待決定」。</p>
```

### 4.2 `camera-phone.html`：加窄條的 JS（三處）

- [ ] **① 變數區**（第 42〜49 行那一塊）：在 `cpStatus` 與 `cpHint` **之間**插入
      `cpBar` 那一行（改完前四行如下；`cp按鈕 = { … }` 那五行不動），
      並在第 58 行 `let cp上傳中 = false;` 後面加計數：

```javascript
const cpVideo = document.getElementById("cp-video");
const cpStatus = document.getElementById("cp-status");
const cpBar = document.getElementById("cp-bar");        // ← 新增：送出進度的窄條
const cpHint = document.getElementById("cp-hint");
```

```javascript
let cp上傳中 = false;
let cp已送出 = 0;          // ← 新增：這次配對總共送出幾張（純本地計數，不打任何 API）
```

- [ ] **② 在既有的 `狀態()` 函式後面**（第 67 行 `}` 之後）加這兩個小函式：

```javascript
// 窄條：只講「我送出去幾張」這件純本地的事。
// 分析到第幾次、失敗了沒，全部在電腦那邊的進度面板上看（Phase 67）——
// 手機不打 GET /ingest-jobs，一個多餘的請求都不發。
function 窄條(文字) {
  cpBar.textContent = 文字 || "";       // 動態內容一律 textContent
  cpBar.hidden = !文字;
}

function 更新窄條(送出中) {
  if (送出中) {
    窄條("送出中…（第 " + (cp已送出 + 1) + " 張）");
  } else if (cp已送出 > 0) {
    窄條("已送出 " + cp已送出 + " 張，分析在電腦上進行");
  } else {
    窄條("");
  }
}
```

- [ ] **③ 改 `快門()` 與 `上傳結束()`（第 276〜325 行——從「④ 快門」那行區塊註解
      一路到 `上傳結束()` 的收尾 `}`，整段換成下面這一份）**。
      （**canvas 擷取那五行一個字都沒動**，只改狀態碼與周邊的 UI 狀態。）

> ⚠ **範圍不能只抓 `快門()` 那一段（278〜319）。** 下面的替換區塊含**新版
> `上傳結束()`**（多了一行 `更新窄條(false)`）；如果只換 `快門()`、把舊的
> `上傳結束()`（321〜325 行）留在檔案裡，就會有**兩個同名函式**——JavaScript
> 的函式宣告是「後面那份贏」，舊版在後面，於是新版被整個蓋掉：
> 快門失敗時窄條會**永遠卡在「送出中…」**，而且 console 一個錯誤都不報（安靜壞掉）。

```javascript
// ---------- ④ 快門 ----------

async function 快門() {
  // ⚠ 這個 guard 才是防連按的真本事（競態）：
  //   按鈕 disabled 只擋得住「手指按手機上那顆」，
  //   電腦透過 WebSocket 送過來的 { type: "capture" } **根本不經過按鈕**，
  //   直接就叫到這個函式。沒有 cp上傳中 的話，狂按電腦快門會送出好幾份。
  if (!cpStream || cp上傳中) { return; }
  if (!cpVideo.videoWidth) { 狀態("畫面還沒準備好，請等一下再按。", "error"); return; }

  cp上傳中 = true;
  拍照按鈕可用(false);
  狀態("拍好了，送出中…");
  更新窄條(true);
  送({ type: "uploading" });

  // 把當下這一幀原尺寸畫進 canvas（不是預覽縮圖——給 VLM 看的要清楚）
  const canvas = document.createElement("canvas");
  canvas.width = cpVideo.videoWidth;
  canvas.height = cpVideo.videoHeight;
  canvas.getContext("2d").drawImage(cpVideo, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise(function (resolve) {
    canvas.toBlob(resolve, "image/jpeg", 0.92);
  });
  if (!blob) { 上傳結束("擷取畫面失敗，請再按一次快門。"); return; }

  const formData = new FormData();
  formData.append("file", blob, "camera.jpg");

  try {
    const response = await fetch("/camera/" + cpToken + "/photos", {
      method: "POST", body: formData
    });
    // design5 D4／§5：受理成功是 **202**（已收下，還沒分析）。
    // 一拿到就放行下一拍——不必等 VLM，那在電腦背景排隊跑。
    if (response.status === 202) {
      cp已送出 += 1;
      送({ type: "uploaded" });          // 電腦收到只會更新計數與進度面板，不開彈窗（D13）
      狀態("已送出——可以直接拍下一張。", "ok");
      cpHint.textContent =
        "分析在背景進行，電腦右下角看得到進度；完成的照片會進電腦的「待決定」。";
      cp上傳中 = false;
      拍照按鈕可用(true);
      更新窄條(false);
      return;
    }
    // 走到這裡是同步就被擋下來的：404（token 過期／亂 token）、415（格式不對）。
    // 這種檔**根本沒有進佇列**，所以電腦的進度面板也不會有它。
    let payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    const 說明 = (payload && typeof payload.detail === "string")
      ? payload.detail : "伺服器沒有給說明";
    送({ type: "upload-failed", detail: 說明 });
    上傳結束("沒有送成功（HTTP " + response.status + "）：" + 說明);
  } catch (error) {
    上傳結束("送不出去。請確認手機與電腦還在同一個 Wi-Fi。");
  }
}

function 上傳結束(訊息) {
  cp上傳中 = false;
  拍照按鈕可用(true);
  更新窄條(false);                       // 失敗就把「送出中…」收回去（計數不加）
  狀態(訊息, "error");
}
```

- [ ] **④ 改 `處理訊息()` 的 `retake` 分支文案**（第 166〜172 行）：

```javascript
  } else if (訊息.type === "retake") {
    // 上傳中就不要動狀態列——那會把「拍好了，送出中…」蓋成「取景中」，
    // 看起來像什麼事都沒發生，但那張其實正在路上。
    if (cp上傳中) { return; }
    狀態("取景中。對準要拍的東西，兩邊都能按快門。");
    cpHint.textContent = "快門電腦那邊也能按。拍完會立刻送出，不必等——可以連續拍。";
  }
```

### 4.3 `style.css`：新增 `.cp-bar`

- [ ] 在既有「無線鏡頭·手機頁」區塊裡、`.cp-status` 那一組規則**之前**插入：

```css
/* 送出進度的窄條（design5 §6.5；Phase 69）。
   它是版面裡的一「列」（flex 的兄弟節點），不是浮在畫面上的東西——
   所以下緣那三顆按鈕（.cp-controls）永遠不會被它壓到，這就是「不擋快門」。
   flex: none ＝ 不跟著伸縮；沒東西可講的時候整條 hidden，取景區就自動長回來。 */
.cp-bar {
  flex: none;
  margin: 0;
  padding: var(--sp-1) var(--sp-2);
  font-family: var(--f-mono);
  font-size: var(--fs-small);
  text-align: center;
  color: var(--c-text);
  background: var(--c-surface-2);
  border-radius: var(--radius-s);
}
.cp-bar[hidden] { display: none; }
```

> `[hidden] { display: none; }` 那一行不能省：`.cp-page` 是 flex 容器，
> 只要有任何規則給子元素設過 `display`，`hidden` 屬性的預設效果就會失效
> （`.fm-option`、`.pd-task`、`.cd-video-empty` 都踩過同一個坑，`style.css` 裡有三個前例）。

### 4.4 `camera-desk.html`：刪掉「拿最後一張 → 開鏈」（D13）

這是本 phase 的**核心刪除**。逐段照做，**表格沒列到的行一律不動**。

> ⚠ 本節行號＝**增量五開工前**的 `camera-desk.html`。Phase 53（頂欄多一格）與
> Phase 67（掛 `progress_panel.js`）各讓後段行號 +1，開工時大約整體 **+2 行**。
> 行號只當導覽，**定位一律靠引用的原文搜尋**（引用的內容 53／67 都沒動過）。
> `camera-phone.html` 不在此限——53／67 都不碰它，§4.1〜4.2 的行號可直接用。

- [ ] **① 檔頭註解**（第 89〜98 行）：**整段十行換成下面這一份**——
      不只第 95 行那一句（④ 的內容變了），第 89 行的標題也從
      「收照片接彈窗鏈」改成「收照片」，中間還多了一段 D13 的說明。

```javascript
// ===== 桌面端：配對 → 看即時畫面 → 遙控 → 收照片（Phase 36 路線 B；Phase 69 改版）=====
//
// 這一頁自己不碰鏡頭。它做四件事：
//   ① POST /camera/session 拿 token 與 QR
//   ② 開 WebSocket（信令＋遙控指令的水管，伺服器只轉發不解讀）
//   ③ 當 WebRTC 的「接收端」：手機送 offer，這裡回 answer，然後畫面就出來了
//   ④ 手機說 uploaded → 把計數加一、叫右下角的全站進度面板更新一次
//
// ⚠ design5.md D13：④ **不再**去拿「最後那一張」、**不再**開三關彈窗鏈。
//   快門當下照片還不存在（202 只是「已收下」），沒有東西可以餵給鏈。
//   歸類整個搬到「待決定」那一頁（/ui/pending.html）。
//   （這幾行刻意不寫出被刪掉的那支端點路徑、鏈的函式名、以及那幾個共用檔的檔名——
//     驗收會用字串掃這一頁，註解不能誤中。同彈窗共用檔檔頭那行註解的手法。）
//
// WebRTC 的影像是兩台裝置**直接**傳的，不經過伺服器；
// 同一個 Wi-Fi 用 host candidate 就連得起來，所以 iceServers 是空的（不接 STUN／TURN）。
```

- [ ] **② 加一個計數變數**（第 123 行 `let cd等照片中 = false;` 之後）：

```javascript
let cd等照片中 = false;
// 這次配對總共收下幾張（本地計數）。真正的分析進度在右下角的全站進度面板上。
let cd已收下 = 0;
```

- [ ] **③ 改 `處理訊息()` 的 `uploading`＋`upload-failed` 兩個分支**
      （**第 226〜234 行**整段換掉——下面的替換區塊**包含** `upload-failed` 分支，
      範圍只抓到 230 的話，殘留的舊分支會多出一個 `} else if`，**整頁直接語法錯誤**）。
      改動有二：`uploading` 的舊文案講「本機模型看圖可能要等 1〜5 分鐘」已經不對了
      ——POST 現在是毫秒級的、也不再需要 `aiBackendNow()` 分流；
      `upload-failed` 的「沒有**存**成功」順手改成「沒有**送**成功」（202 語意：
      失敗的是「送」，不是「存」——那時候本來就還沒有存這回事）：

```javascript
  } else if (訊息.type === "uploading") {
    連線狀態("手機正在把這一張送上來…");
  } else if (訊息.type === "upload-failed") {
    等照片(false);
    連線狀態("手機那一張沒有送成功：" + (訊息.detail || "未知原因"), "error");
  }
```

- [ ] **④ 改 `retake` 按鈕的監聽器**（**第 311〜318 行**，含上面那兩行註解——
      替換區塊帶著新寫的註解，範圍沒圈到 311〜312 的話舊註解會重複留下）。
      實質改動只有一行：`cdResult.innerHTML = '<p class="panel-empty">…</p>';`
      換成 `渲染收下("已回到取景…")`（結果面板改由 §4.4 ⑤ 的 `渲染收下()` 統一畫，
      「已收下 N 張」那句才不會被重拍蓋掉）：

```javascript
// 重拍＝回到取景再拍一張新的。已經收下的那張**不會**被刪掉——
// 本專案沒有刪除照片這件事（design5 §3），它會照常分析完進「待決定」。
cd按鈕.retake.addEventListener("click", function () {
  渲染收下("已回到取景，請重新對準後再按快門。");
  等照片(false);
  送({ type: "retake" });
  連線狀態("即時預覽中——快門兩邊都能按", "ok");
});
```

- [ ] **⑤ 整段換掉 `收到照片()` 與 `renderResult()`**（第 336〜377 行，含中間的區塊註解）。
      舊的那 42 行全部刪掉，換成下面這一段（22 行，不含空行）：

```javascript
// ---------- ④ 手機說「這一張送出去了」----------
// design5 D13：這裡只更新畫面上的計數與進度面板，**不開任何彈窗**。
// 為什麼不能開：快門當下照片還不存在（202 只是「已收下」），
// 抽屜彈窗要的 text／suggested_folder／folders 全部都還沒有。

function 收到照片() {
  等照片(false);                       // 手機說送出去了，快門解鎖，可以拍下一張
  cd已收下 += 1;
  渲染收下("");
  連線狀態("已收下這一張，可以繼續拍。分析完成後會出現在「待決定」。", "ok");
  ppStart();                           // 立刻讓右下角的面板更新一次（/ui/progress_panel.js）
}

// ===== 結果面板：只講「這次配對收下幾張」=====
// 分析進度、重試、失敗全部交給右下角的全站進度面板（Phase 67），這一頁不重複做一份。

function 渲染收下(補充) {
  const 主文 = cd已收下 === 0
    ? "還沒有拍到任何照片。"
    : "這次配對已收下 " + cd已收下 + " 張。分析在背景進行——右下角看得到進度；" +
      "完成的照片會出現在「待決定」，到那裡歸類。";
  cdResult.innerHTML =
    '<p class="panel-empty">' + esc(主文) + '</p>' +
    (補充 ? '<p class="note">' + esc(補充) + '</p>' : '');
}
```

- [ ] **⑥ 換掉 `<script src>` 那一區**。**到本 phase 開工時它是六行**
      （開工前第 82〜86 行的五行，加上 Phase 67 §4.4 加在最後的 `progress_panel.js`）：

```html
<script src="/ui/folder_modal.js"></script>
<script src="/ui/entity_modal.js"></script>
<script src="/ui/task_modal.js"></script>
<script src="/ui/classify_chain.js"></script>
<script src="/ui/ai_switch.js"></script>
<script src="/ui/progress_panel.js"></script>
```

　　換成下面這樣（＝**刪掉前四行**、保留後兩行、最前面補一段註解）：

```html
<!-- design5 D13：快門後不再開歸類鏈，所以這一頁不再載入三顆彈窗與鏈的共用檔。
     ⚠ 被拿掉的那四個共用檔**本身不要刪**：三顆彈窗是 Phase 70 待決定頁的主角；
       鏈的那一支到本 phase 做完雖已零呼叫者，刪除仍留給 Phase 70 §4.5 的 grep 閘門
       （先確認待決定頁自己組鏈走得通才刪）。檔名刻意不寫在這段註解裡——
       本 phase 的契約測試與 §6.1 的 grep 會掃這一頁的原始碼，註解不能誤中
       （同彈窗共用檔檔頭那行註解的手法）。 -->
<script src="/ui/ai_switch.js"></script>
<script src="/ui/progress_panel.js"></script>
```

> ⚠ **註解裡不准出現那四個檔名、也不准出現 `/latest`**——`test_桌面頁不再開歸類鏈`
> 對這一頁斷言「那些字串一個都不在」，寫進註解一樣紅。要留線索就照上面的代稱寫法。

- [ ] **⑦ 改 `<p class="lead">` 文案**（第 41〜43 行）：

```html
<p class="lead">手機掃下面這個 QR，就變成這台電腦的無線鏡頭：你在手機上對準什麼，這裡就看到什麼。
快門兩邊都能按，<strong>拍完立刻可以再拍</strong>——照片先收下，AI 看圖在背景進行，
右下角看得到進度。分析完成的照片會出現在「待決定」，到那裡歸類。
手機與電腦要在同一個 Wi-Fi。</p>
```

> `ai_switch.js` **要留著**：design5 D14——入列當下會把 `config.AI_BACKEND` 拍成快照存進任務，
> worker 照那張快照建 VLM 客戶端。所以這顆開關仍然決定「接下來收下的照片用哪個後端看圖」。
> （改版後這一頁不再呼叫 `aiBackendNow()`，那只是因為等待提示不需要它了，開關本身照常運作。）

### 4.5 在 `tests/integration/test_progress_panel_contract.py` 尾端追加三顆

- [ ] Phase 67 已經建好這個檔（含 `讀()` 工具）。**不要新建檔案**，把這一段接在檔尾：

```python
# ═══════════════════════════════════════════════════════════════════
# Phase 69：鏡頭連拍與桌面拿掉開鏈（design5 D4／D13／§6.5）
# ═══════════════════════════════════════════════════════════════════


def test_手機端202就放行下一拍():
    """D4／§5：受理成功是 202；一拿到就能拍下一張。

    連 `201` 這三個字都不准出現在這一頁（包含註解）：
    留著舊的 `status === 201` 判斷是「安靜壞掉」的典型——
    照片其實已經收下了，手機卻顯示「沒有送成功」。
    """
    手機頁 = 讀("camera-phone.html")

    assert "response.status === 202" in 手機頁
    assert "201" not in 手機頁
    assert 'id="cp-bar"' in 手機頁                 # §6.5 的窄條
    assert "progress_panel.js" not in 手機頁       # 手機不掛全站面板（Phase 67 §4.7）
    # 防連按的真本事是旗標，不是 disabled（電腦按的快門不經過按鈕）
    assert "if (!cpStream || cp上傳中) { return; }" in 手機頁


def test_桌面頁不再開歸類鏈():
    """D13／§1.1 鏡頭桌面那一列：刪掉「拿最後一張 → 三關彈窗鏈」。"""
    桌面頁 = 讀("camera-desk.html")

    assert "startClassifyChain" not in 桌面頁
    for 檔名 in ["classify_chain.js", "folder_modal.js", "entity_modal.js", "task_modal.js"]:
        assert 檔名 not in 桌面頁, f"camera-desk.html 還在載入 {檔名}——D13 起這一頁不開鏈"
    # §5 第 3 列：桌面不再靠「最後一張」那支端點
    assert "/latest" not in 桌面頁
    # 進度改走全站面板
    assert '<script src="/ui/progress_panel.js"></script>' in 桌面頁
    assert "ppStart();" in 桌面頁

    # ⚠ POST /camera/session 仍然回 201（§5 沒有改它）——這一行不准跟著被改掉
    assert "if (response.status !== 201) {" in 桌面頁


def test_鏡頭的核心功能一個字都沒動():
    """§6.5：「WebRTC 預覽、QR、快門、閃光**不改**」。

    這幾條掃的是「那些關鍵行還在不在」——它們沒有自動化測試接得住，
    是 Phase 36 在真機上一次一次調出來的，改壞了只有真機才發現得了。
    """
    桌面頁 = 讀("camera-desk.html")
    手機頁 = 讀("camera-phone.html")
    樣式 = 讀("style.css")

    for 片語 in [
        "new RTCPeerConnection({ iceServers: [] })",        # 零 STUN／TURN
        'document.getElementById("cd-qr").innerHTML = body.qr_svg;',
        '送({ type: "capture" });',
        '送({ type: "torch", on: cd閃光開著 });',
    ]:
        assert 片語 in 桌面頁, f"camera-desk.html 少了不該動的一行：{片語}"

    for 片語 in [
        "navigator.mediaDevices.getUserMedia",
        "facingMode: { ideal: cp鏡頭 }",
        'canvas.toBlob(resolve, "image/jpeg", 0.92);',
        "applyConstraints({ advanced: [{ torch: !!要開 }] })",
        "settings.torch !== true",                          # iOS 靜默成功的復驗
    ]:
        assert 片語 in 手機頁, f"camera-phone.html 少了不該動的一行：{片語}"

    # QR 顯示尺寸（增量四唯一一次改產品 CSS）不准改小。
    # 主測試在 test_camera_endpoints.py::test_qr的顯示尺寸夠大讓長網址也掃得到，
    # 這裡再釘一次，是因為本 phase 正好在改同一支 CSS 檔案的隔壁區塊。
    assert ".cd-qr svg { width: 100%; height: auto; max-width: 20rem; }" in 樣式
```

- [ ] 跑它：

```bash
pytest tests/integration/test_progress_panel_contract.py -v
# 預期：13 passed（67 的 7 顆 ＋ 68 的 3 顆 ＋ 本 phase 的 3 顆）
```

---

## 5. ASCII 圖

### 5.1 前後對照：拍三張要多久

```text
════ 改版前（同步；POST 要等 VLM 看完圖）══════════════════════════════

 手機                         伺服器                       電腦桌面
  │                             │                             │
  │ 按快門 ──► POST ───────────►│                             │
  │ 【按鈕變灰，只能等】        │ VLM 看圖（本機 1〜5 分鐘）   │
  │                             │  ……………………………………………………     │
  │◄──────────────── 201 ＋整包 │                             │
  │                             │──── uploaded ──────────────►│
  │                             │◄─── 拿最後一張 ─────────────│
  │                             │──── 整包回去 ──────────────►│
  │                             │                    ┌────────▼────────┐
  │                             │                    │ 抽屜彈窗        │
  │                             │                    │  → 實體彈窗      │
  │                             │                    │  → 待辦彈窗      │
  │                             │                    └────────┬────────┘
  │ 【現在才能拍第二張】◄────────────────────────────────────┘
  │
  ├─ 第 1 張：t = 0     〜 4 分
  ├─ 第 2 張：t = 4 分  〜 8 分
  └─ 第 3 張：t = 8 分  〜 12 分     ★ 而且全程人不能離開電腦


════ 改版後（202；分析在背景排隊）═════════════════════════════════════

 手機                         伺服器                       電腦桌面
  │                             │                             │
  │ 按快門 ──► POST ───────────►│ 驗 token → 檢查格式          │
  │                             │ → 寫 staging → 入列 Celery   │
  │◄──────────────── 202 ───────│ （幾十毫秒）                 │
  │ 窄條：已送出 1 張            │──── uploaded ──────────────►│ 計數 +1
  │ 【立刻可以按下一張】         │                             │ ppStart()
  │                             │                    ┌────────▼────────┐
  │ 按快門 ──► POST ───────────►│                    │ 右下角進度面板  │
  │◄──────────────── 202 ───────│                    │ camera.jpg      │
  │ 窄條：已送出 2 張            │                    │ 分析中（第 1 次）│
  │                             │                    │ camera.jpg      │
  │ 按快門 ──► POST ───────────►│                    │ 排隊中          │
  │◄──────────────── 202 ───────│                    └─────────────────┘
  │ 窄條：已送出 3 張            │                    ★ **沒有任何彈窗**
  │                             │
  ├─ 第 1 張：t = 0.0 秒 〜 0.1 秒       兩個 worker 在背景慢慢看圖
  ├─ 第 2 張：t = 3   秒 〜 3.1 秒       （慢的是 VLM，不是你）
  └─ 第 3 張：t = 6   秒 〜 6.1 秒
                                        ★ 十張三十秒拍完，人就可以走了
                                        ★ 晚點到「待決定」一次歸類完
```

### 5.2 桌面頁：刪掉的那一段長什麼樣

```text
   手機送 { type: "uploaded" } 到 WebSocket
              │
              ▼
       處理訊息() → 收到照片()
              │
   ┌──────────┴────────────────────────────────────────────┐
   │                                                        │
   │  ✗ 改版前（42 行，全部刪掉）                            │
   │      await fetch("/camera/{token}/latest")             │
   │        ├─ 不是 200 → 連線狀態(拿不到剛剛那張照片)        │
   │        └─ 200 → startClassifyChain({ photo, render })  │
   │                    ├─ 抽屜彈窗（folder_modal.js）       │
   │                    ├─ 實體彈窗（entity_modal.js）       │
   │                    └─ 待辦彈窗（task_modal.js）         │
   │      renderResult(body, folderName, note)              │
   │        └─ 畫出 text／資料夾／地點／物品／內容時間        │
   │                                                        │
   │      ★ 為什麼不可能保留：202 只是「已收下」，           │
   │        照片列還不存在，text／suggested_folder／folders  │
   │        通通還沒有。硬留著就是一段一定會炸的死碼。        │
   │                                                        │
   ├────────────────────────────────────────────────────────┤
   │                                                        │
   │  ✓ 改版後（22 行）                                      │
   │      等照片(false)          ← 快門解鎖，可以拍下一張      │
   │      cd已收下 += 1                                      │
   │      渲染收下("")           ← 面板：「已收下 N 張…」      │
   │      連線狀態("已收下這一張，可以繼續拍。…", "ok")        │
   │      ppStart()              ← 右下角全站面板立刻更新     │
   │                                                        │
   │      ★ 一個彈窗都不開（D13）                            │
   └────────────────────────────────────────────────────────┘

   完全沒動的：QR、WebSocket 信令、WebRTC offer／answer／ICE、
               capture／switch／torch 三顆按鈕、閃光能力回報制
```

---

## 6. 驗收清單

### 6.1 自動化（跑指令）

- [ ] **契約測試十三顆全綠**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_progress_panel_contract.py -v
```
      預期：`13 passed`（67 的 7 顆＋68 的 3 顆＋本 phase 的 3 顆）

- [ ] **QR 尺寸那顆仍然是綠的（本 phase 最重要的一條防手滑）**

```bash
pytest "tests/integration/test_camera_endpoints.py::test_qr的顯示尺寸夠大讓長網址也掃得到" -q
grep -n "cd-qr svg" app/static/style.css
```
      預期：`1 passed`；grep 印出 `max-width: 20rem`（**不是** 15rem、不是任何更小的值）

- [ ] **全量測試 ＝ 開工前的 N ＋ 3**

```bash
pytest -q
```
      預期：`(N+3) passed`。⚠ **絕對不要同時跑兩份 pytest**。

- [ ] **端點數沒有變**（純前端，仍是 22）

```bash
pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
```

- [ ] **桌面頁真的不開鏈了、也不再拿最後一張**

```bash
grep -nE "classify_chain|startClassifyChain|folder_modal|entity_modal|task_modal|/latest" \
  app/static/camera-desk.html || echo "OK：桌面頁不開鏈、不拿最後一張"
```
      預期：`OK：桌面頁不開鏈、不拿最後一張`

- [ ] **`POST /camera/session` 的 201 判斷還在**（沒有被連坐改掉）

```bash
grep -n "response.status !== 201" app/static/camera-desk.html
```
      預期：印出 `建立配對()` 裡那一行

- [ ] **手機頁沒有殘留的 201**

```bash
grep -n "201" app/static/camera-phone.html || echo "OK：手機頁沒有 201"
```
      預期：`OK：手機頁沒有 201`

- [ ] **四個共用檔都還在**（只是不載入，**不刪檔**）

```bash
ls app/static/classify_chain.js app/static/folder_modal.js \
   app/static/entity_modal.js app/static/task_modal.js
```

- [ ] **沒有原生對話框**

```bash
grep -nE "alert\(|confirm\(|prompt\(" app/static/camera-desk.html app/static/camera-phone.html \
  || echo "OK：沒有原生對話框"
```

- [ ] **只動到四個檔（跟 §2 抄下的快照相減）**

```bash
git status --short -- app tests > /tmp/p69-after.txt
diff /tmp/p69-before.txt /tmp/p69-after.txt
```
      預期：`diff` 頂多多出 `M app/static/camera-phone.html`（唯一到本 phase 才第一次
      被動到的檔）；其餘三個——`camera-desk.html`、`style.css`、
      `tests/integration/test_progress_panel_contract.py`——前面的 phase 已動過，
      在兩份快照裡都已經在了。有別的新列＝動到了不該動的檔。
      實際改了什麼用 `git diff <檔名>` 逐檔看（未追蹤的新檔才需要直接開檔）。

### 6.2 桌面雙分頁模擬（不必手機，先自己驗一輪）

Phase 36 用過這招：Mac 上用**兩個分頁**扮演電腦與手機（Mac 有內建鏡頭，
`getUserMedia` 在 `https://localhost` 也給權限）。

- [ ] 分頁 A 開 `https://localhost:8000/ui/camera-desk.html` → 出現 QR 與網址
- [ ] 把頁面上那串 `phone_url` 複製到分頁 B 打開 → 允許使用相機
- [ ] **看到**：分頁 A 的取景框出現分頁 B 的畫面、四顆按鈕變成可按
- [ ] 在分頁 A 按「按快門」→ **看到**：分頁 B 的窄條出現「送出中…（第 1 張）」
      → 一秒內變成「已送出 1 張，分析在電腦上進行」；分頁 A 的結果面板寫「這次配對已收下 1 張…」
- [ ] **★ 分頁 A 不可以跳出任何彈窗**（design5 §12 階段丙第 4 條後半）
- [ ] 立刻再按兩次快門 → **看到**：三張都送出去了，中間**沒有**等待
      （§12 階段丙第 4 條前半：連拍至少 2 張不必等第一張看完）
- [ ] **看到**：分頁 A 右下角的進度面板有三列，狀態陸續從 `排隊中` → `分析中（第 1 次）`
- [ ] 等它們跑完 → **看到**：三列自己消失、面板收起、頂欄「待決定（N）」加 3
- [ ] 按「重拍」→ **看到**：結果面板加一行「已回到取景，請重新對準後再按快門。」，
      而且**上面那句「已收下 3 張」還在**（重拍不會把已收下的張數歸零）
- [ ] 主控台乾淨：沒有紅色錯誤，特別不該有 `startClassifyChain is not defined`
      或 `ppStart is not defined`

### 6.3 真機驗收（iPhone；產品負責人那一關）

**先確認網址與憑證：**

```bash
# ① 日常網址（固定用 Bonjour 主機名——換 Wi-Fi、IP 變了都不必改網址、也不必重簽憑證）
echo "https://$(scutil --get LocalHostName).local:8000/ui/camera-desk.html"

# ② 憑證有沒有涵蓋這個名字（應該同時看得到 .local 與某個 IP）
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"

# ③ 服務在跑
docker compose ps --no-trunc
```

**用上面那串網址在電腦的瀏覽器開桌面頁**（⚠ **不要用 `localhost`**，理由見下一條）。

- [ ] **1. QR 網址的 host 判準**
      看頁面上 QR 底下印出來的那串網址。

> **判準：QR 網址的 host，必須逐字等於你在網址列打的那個 host。**
> `phone_url` 的 host 沿用 request 的 `Host` 標頭（Phase 36 校準 6），所以：
>
> | 你用什麼開桌面頁 | QR 的 host 應該是 | 對不對 |
> |---|---|---|
> | `https://<主機名>.local:8000/…` | `<主機名>.local` | ✓ |
> | `https://<區網IP>:8000/…` | 逐字等於 `ipconfig getifaddr en0` 的輸出 | ✓ |
> | `https://localhost:8000/…` 或 `127.0.0.1` | 退回 UDP 猜測 → **在容器裡會猜到 Docker 網段** | ✗ 手機連不到 |
>
> ⚠ **不要用「是不是 192.168 開頭」判斷。** 2026-08-24 實測：本機區網就是 `172.29.93.122`，
> 而用 `localhost` 開頁時猜出來的 Docker 網段是 `172.24.0.3`——**兩個都是 172.x**，看前綴分不出來。

- [ ] **2. iPhone 掃得到 QR**（QR 尺寸那顆測試守的就是這一關）
      拿 iPhone 相機對著螢幕上的 QR。**看到**：一兩秒內跳出「在 Safari 中打開」的橫幅。
      掃不到就先量一下：QR 的 CSS 上限是 20rem（320px），`.local` 那版網址是 53 格＝每格 6.0px，
      應該很好掃。掃不到但畫得出來＝有人把 `max-width` 改小了，回頭看 §6.1。

- [ ] **3. 手機開得起來、沒有憑證警告**
      點開之後允許使用相機。**看到**：iPhone 出現取景畫面；電腦的取景框同步出現同一個畫面。
      跳憑證警告＝那台 iPhone 還沒信任 mkcert 的根憑證（CLAUDE.md 指令區有四步驟，
      特別是第 4 步「憑證信任設定 → 完全信任」最容易漏）。

- [ ] **4. ★ 手機連拍至少 2 張，不必等第一張看完（§12 階段丙第 4 條前半）**
      在 iPhone 上對準一張收據按快門 → **不要等**，立刻換一張再按 → 再換一張再按。
      **看到**：每按一次，窄條先閃「送出中…（第 N 張）」再變成「已送出 N 張，分析在電腦上進行」；
      三張的間隔就是你換東西的時間，**沒有任何一次要等好幾分鐘**。

- [ ] **5. ★ 桌面不跳出歸類鏈（§12 階段丙第 4 條後半）**
      整趟拍下來，盯著電腦螢幕。
      **看到**：**沒有任何彈窗**跳出來；電腦上只有（a）結果面板的「這次配對已收下 3 張…」
      與（b）右下角進度面板的三列。

- [ ] **6. 電腦按快門也一樣**
      在電腦上按「按快門」→ **看到**：手機窄條動、電腦計數加一、**仍然沒有彈窗**。
      連按三下電腦的快門 → **看到**：只送出**一張**（`cd等照片中` ＋ 手機的 `cp上傳中` 兩道鎖）。

- [ ] **7. 切鏡頭與閃光沒有壞掉（§6.5「不改」的實證）**
      按「切換鏡頭」→ 前後鏡頭互換、預覽跟著換。
      閃光：iPhone Safari 多半不支援，**看到**按鈕是停用的、旁邊有一行
      「這支手機的瀏覽器不支援閃光，請改用手電筒或找亮一點的地方。」（優雅降級，不是報錯）。

- [ ] **8. 照片真的進「待決定」**
      等三張分析完（雲端約幾秒／張，本機 1〜5 分鐘／張）。
      **看到**：右下角的列一個一個消失、面板收起；頂欄「待決定」加 3。
      點頂欄「待決定」→ 三張都在縮圖牆上。

- [ ] **9. token 過期不會弄丟已經收下的照片（§13 風險第 4 條）**
      關掉電腦那一頁（配對即失效），但**在那之前送出的照片照樣會分析完進待決定**。
      驗法：拍一張，馬上關掉桌面頁，等一分鐘再開「待決定」→ 那張在。

- [ ] **10. 亂 token 仍然 404（§8 錯誤表第 2 列）**

```bash
curl -sk -o /dev/null -w "%{http_code}\n" -X POST \
  https://127.0.0.1:8000/camera/亂打的token/photos -F "file=@/tmp/cam.png;type=image/png"
```
      預期：`404`

---

## 7. 常見陷阱

1. **把 `建立配對()` 裡的 `!== 201` 也一起改成 202。**
   症狀：桌面頁一開就寫「建立配對失敗（HTTP 201）」，QR 根本不出現。
   原因：`POST /camera/session` **沒有**改成 202（design5 §5 只改了 `…/photos`）。
   本 phase 只有**手機頁**的那一個 `201` 要改。
   §4.5 的契約測試專門守這一行（`assert "if (response.status !== 201) {" in 桌面頁`）。

2. **手機頁留著舊的 `if (response.status === 201)`。**
   症狀：照片其實已經收下了（後端 202、job 也建了），但手機顯示「沒有送成功（HTTP 202）」，
   而且電腦不會收到 `uploaded`。這是**安靜壞掉**：資料是對的，只有 UI 在說謊。
   原因：忘了改。契約測試連註解裡的 `201` 都不准出現，就是為了擋這個。

3. **以為「按鈕 disabled 就防得住連按」。**
   症狀：狂按**電腦**的快門，送出好幾份一模一樣的照片。
   原因：電腦的快門是透過 WebSocket 送 `{ type: "capture" }` 到手機，
   **直接叫 `快門()`，根本不經過手機上那顆按鈕**。
   `if (!cpStream || cp上傳中) { return; }` 這一行才是真正的鎖，**不能刪**。

4. **窄條做成蓋在畫面上的浮層。**
   症狀：iPhone 上按不到「開閃光」，或快門被半透明的條卡住。
   原因：用了 `position: absolute` / `fixed`。
   §4.3 的 `.cp-bar` 是 flex 版面裡的一「列」（`flex: none`），
   下緣那三顆按鈕永遠在它下面——這就是 §6.5「不擋快門」的做法。

5. **忘了 `.cp-bar[hidden] { display: none; }`。**
   症狀：明明 JS 設了 `hidden = true`，窄條還是佔著一行空白。
   原因：`.cp-page` 是 flex 容器，只要子元素有任何 `display` 相關規則，
   `hidden` 屬性的預設效果就被蓋掉。`.fm-option`／`.pd-task`／`.cd-video-empty` 都踩過。

6. **把 `.cd-qr svg` 的 `max-width` 改小「因為版面看起來太大」。**
   症狀：iPhone 掃不到 QR，但螢幕上那個 QR **看起來完全正常**。
   原因：網址越長格數越多，`.local` 那版是 53 格；20rem（320px）÷ 53 ≈ 6.0px／格，
   縮到 15rem 就只剩 4.5px／格，低於 iPhone 相機的辨識下限。
   這是 2026-08-25 真機踩過的，有測試釘死——**不准改小**。

7. **順手刪掉那四個檔。**
   症狀：Phase 70 做待決定完整三關時發現三顆彈窗檔不見了；
   或者提早刪 `classify_chain.js`，結果 Phase 70 §4.5 的 grep 閘門沒有東西可以驗。
   原因：把「這一頁不載入」誤解成「這個功能不要了」。
   **只刪 `<script src>` 那四行，檔案留著**（design5 §2 末句明寫）。
   `classify_chain.js` 到本 phase 做完雖然已經零呼叫者，**刪除的動作仍交給 Phase 70 §4.5**。

8. **桌面頁留著 `GET …/latest` 的呼叫「當備援」。**
   症狀：每拍一張，Console 就多一行 204 的請求；如果程式寫成「不是 200 就報錯」，
   狀態列還會跳「拿不到剛剛那張照片（HTTP 204）」。
   原因：§5 第 3 列——入列不再寫 latest，那支端點現在恆 204。
   **整段刪掉**，不要留備援。

9. **把 `ai_switch.js` 也一起從桌面頁拿掉。**
   症狀：切不了雲端，真機驗收要 1〜5 分鐘一張，等到懷疑人生。
   原因：誤以為 202 之後開關沒用了。
   **開關仍然有意義**（D14：入列當下拍快照）。要拿掉的只有那四個彈窗相關的檔。

10. **重拍就把 `cd已收下` 歸零。**
    症狀：拍了 5 張、按一次重拍，面板變成「還沒有拍到任何照片」，人以為前面 5 張不見了。
    原因：把「重拍」誤解成「取消上一張」。
    本專案**沒有刪除照片**這件事（design5 §3）——重拍只是回到取景，
    已收下的那些照樣會分析完進待決定。`渲染收下()` 用的是**同一個計數**，不要動它。

11. **在手機頁掛 `progress_panel.js`「反正是共用的」。**
    症狀：右下角面板壓到「開閃光」按鈕；橫拿手機時更嚴重。
    原因：忘了 Phase 67 §4.7 的裁決（§6.5 比 D8 具體，手機頁用窄條）。
    契約測試守著這一條（`assert "progress_panel.js" not in 手機頁`）。

12. **用 `localhost` 開桌面頁做真機驗收。**
    症狀：QR 掃得到，但手機打開之後一直轉圈或直接連不上。
    原因：`localhost` 讓伺服器退回 UDP 猜測本機 IP，而它跑在容器裡，猜到的是
    Docker 內部網段（實測 `172.24.0.3`），手機當然連不到。
    **一律用 `https://<主機名>.local:8000/…` 開**，並照 §6.3 第 1 項的表核對 QR 的 host。

13. **改完 CSS 就以為手機會看到。**
    症狀：iPhone 上窄條還是舊的樣子。
    原因：手機 Safari 的快取。
    在手機上下拉重新整理；還是不行就關掉那個分頁重掃一次 QR。
    （`StaticFiles` 每次都直接讀檔，伺服器端不必重啟——是**手機**在快取。）

14. **替換範圍少抓了半段（§4.2 ③ 與 §4.4 ③ 各有一個坑）。**
    症狀 A（手機頁）：快門失敗後窄條**永遠卡在「送出中…」**，console 卻一片安靜。
    原因 A：只換了 `快門()`、留著舊的 `上傳結束()`——兩個同名函式並存時
    JavaScript 是「後宣告的贏」，排在後面的**舊版**把帶 `更新窄條(false)` 的新版蓋掉了。
    症狀 B（桌面頁）：改完 `處理訊息()` 整頁直接白掉，console 一行
    `Unexpected token 'else'`。
    原因 B：替換區塊含 `upload-failed` 分支，範圍卻只圈到 `uploading`——
    殘留的舊分支多出一個 `} else if`。
    **照 §4.2 ③（276〜325）與 §4.4 ③（226〜234）給的範圍整段換**，不要自己縮小。

15. **在 `<script src>` 那段替換註解裡寫出那四個檔名（或 `/latest`）。**
    症狀：`test_桌面頁不再開歸類鏈` 紅掉，說 camera-desk.html 還在載入某個檔——
    但 `<script src>` 明明已經刪乾淨了。
    原因：那顆測試掃**整頁原始碼**，註解一樣算（§6.1 的 grep 也會抓到）。
    **照 §4.4 ⑥ 給的註解逐字貼**（它刻意用「三顆彈窗」「鏈的那一支」代稱）。
