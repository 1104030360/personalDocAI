# Phase 68：上傳頁多檔選檔

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 讓 `app/static/upload.html` 一次可以選很多個檔（JPEG／PNG／PDF 混著選也行），
> 每個檔各發一個 `POST /photos`，**拿掉上傳成功就開歸類彈窗鏈的那一段**，
> 送完就把右下角的進度面板叫起來。

**為什麼要做這個：**

現在的上傳頁一次只能選**一個**檔，而且選完之後你得**站在那裡等**——本機 VLM 看一張圖要 1〜5 分鐘，
等完才跳出彈窗要你決定資料夾，決定完才能傳下一張。整理一疊收據的體驗大概是這樣：

```text
選檔 → 等 3 分鐘 → 彈窗 → 決定 → 選檔 → 等 3 分鐘 → 彈窗 → 決定 → …（十張＝半小時）
```

階段乙（Phase 62）已經把 `POST /photos` 改成 **202「已收下」**：HTTP 幾十毫秒就回，
分析交給背景的 worker。Phase 67 已經做好右下角的進度面板。
本 phase 就是把上傳頁接到那條新路上——**選十個檔，一秒內全部收下，然後你就可以走開了**。

同時要拆掉一個東西：**上傳成功後跳出的三關彈窗鏈**（抽屜→實體→待辦）。
它已經不可能存在了——202 的回應裡根本沒有 `text`、`suggested_folder`、`folders` 這些東西
（那時候照片還不存在）。歸類這件事整個搬到「待決定」那一頁（design5 D13）。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **`multiple`** | `<input type="file">` 加上這個屬性，選檔視窗就允許一次框選多個檔（Mac 上按住 `Cmd` 或 `Shift` 點）。不加的話，選檔視窗只讓你選一個。 |
| **`FileList`** | `fileInput.files` 回傳的東西。它**很像**陣列（有 `length`、可以 `[0]`），但**不是**陣列——沒有 `map`、`filter`、`forEach` 可以用。要先 `Array.prototype.slice.call(它)` 轉成真陣列。這是新手最容易踩的坑之一。 |
| **`FormData`** | 用 JavaScript 組一份「表單資料」的容器。`formData.append("file", file)` 之後丟給 `fetch`，瀏覽器會自動組成 `multipart/form-data` 並帶上正確的標頭。⚠ **不要自己加 `Content-Type`**——手動加會少掉那個隨機分隔字串，伺服器就解不開了。 |
| **`for...of` ＋ `await`** | 一個一個跑，而且**等前一個回來才跑下一個**。本 phase 選這個（理由見 §4.4）。 |
| **`Promise.all([...])`** | 把很多個「還沒完成的工作」一次全部發出去，等**全部**回來才繼續。速度快，但只要有一個失敗，整包就算失敗（要用 `Promise.allSettled` 才拿得到逐一結果）。本 phase **不用**。 |
| **瀏覽器的連線數上限** | 瀏覽器對**同一個網域**同時只肯開大約 6 條 HTTP/1.1 連線。一次丟 20 個請求出去，第 7 個以後會安安靜靜地排在瀏覽器內部等——你在 Network 分頁看得到它們卡在 `Queued` 狀態。 |
| **同步錯誤 vs 非同步錯誤** | 「同步」＝在你按下按鈕的那一次請求裡就知道結果（例如 415：這不是圖片）。「非同步」＝要等背景的 worker 跑完才知道（例如 VLM 看不懂）。這兩種錯誤**顯示在不同地方**，是本 phase 最容易搞混的一點（見 §4.5）。 |
| **202 Accepted** | HTTP 狀態碼，字面意思就是「**收下了，但還沒做完**」。跟 201 Created（已經建好了）刻意不同。design5 D7 選它就是為了讓「收下 ≠ 已入庫」這件事在協定層就講清楚。 |

---

## 1. 對應 design5.md 章節

- **D3**（電腦一次多檔：`<input multiple>`，一次可選多張 JPEG／PNG，也可含 PDF；每個檔各自入列）
- **D7**（立刻 202：HTTP 只做格式檢查、落 staging、入列。回 `{job_id, filename, content_type}`）
- **D13**（上傳當下**不開**歸類鏈——電腦上傳與鏡頭桌面都不再開抽屜→實體→待辦）
- **§2 流程**第一段（「電腦：一次選 N 個 JPEG／PNG／PDF」→「你立刻可以再選檔／再拍」）
- **§2 末句**（上傳頁**不再呼叫** `classify_chain.js` 的開鏈時機；檔案留著給待決定頁用）
- **§5 API 契約**第 1 列（`POST /photos` 受理成功 202，415 不變，
  **不再**於這個請求回 `text`／`suggested_folder`／`folders`）
- **§6.4 `/ui/upload.html`**（四條：加 `multiple`／每檔一個 POST／**前端連發即可，不必再做一個
  「一次塞 N 個檔」的新後端**／拿掉 201 後開鏈／文案改成「先收下，分析完進待決定再歸類」）
- **§8 錯誤表第 1 列**（非 JPEG／PNG／PDF → HTTP 立刻 415，無 job、無 staging）
- **§12 階段丙**第 1、2 條（電腦一次選 3 張出現 3 列進度、可立刻再選下一批；成功列自己消失 N 加上去）

---

## 2. 前置條件

**必須先完成的 phase：**

| Phase | 為什麼需要 |
|---|---|
| **62** | `POST /photos` 已經回 **202** ＋ `{job_id, filename, content_type}`。本 phase 全部建立在這個契約上；還在回 201 的話整頁邏輯都是錯的。 |
| **67** | 右下角的進度面板已經在跑、`ppStart()` 已經是全域函式。沒有它，本 phase 送完檔就什麼都看不到了。 |
| **53** | 頂欄已經是四格（含「待決定（N）」）。本 phase **完全不動頁首**。 |
| **52** | `/ui/pending.html` 存在——文案要叫使用者去那裡歸類，那一頁得先在。 |
| **★ G2** | design5 §0 的閘門：階段乙已由產品負責人驗收通過、API 契約穩定。 |

**開工前先做這四件事：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

# ① 抄下測試基線。本 phase 會 +3 顆。
pytest -q          # 把 "N passed" 的 N 抄在這裡 → N = ______

# ①.5 抄下開工前的工作區狀態（§6.1 最後一項要拿它對「本 phase 動了哪些檔」——
#      增量五的各 phase 若尚未 commit，git status 會混著前面 phase 的變更）
git status --short -- app tests > /tmp/p68-before.txt

# ② 親眼確認 POST /photos 真的回 202（而且回應裡沒有 text／folders）
screencapture -x /tmp/p68.png
curl -sk -X POST https://127.0.0.1:8000/photos \
  -F "file=@/tmp/p68.png;type=image/png" | python -m json.tool
#   預期恰好三個鍵：
#   { "job_id": "…", "filename": "p68.png", "content_type": "image/png" }
#   ⚠ 如果這裡回 201 而且有 text／suggested_folder，代表 Phase 62 沒完成，先回頭補。

# ③ 確認進度面板的 ppStart() 在（Phase 67 的成果）
grep -n "function ppStart()" app/static/progress_panel.js
```

---

## 3. 範圍

### 做

1. `app/static/upload.html`：
   - `<input type="file">` 加 `multiple`
   - 文案改寫（`<p class="lead">` ＋一句 AI 開關的補充）
   - `<script src>` 那一區：拿掉四個彈窗相關的檔，加上 `progress_panel.js`
   - 整段內嵌 `<script>` 換掉（多檔迴圈、逐檔結果、拿掉開鏈、送完叫 `ppStart()`）
2. `tests/integration/test_progress_panel_contract.py` **尾端追加**三顆契約測試
   （Phase 67 已經建好這個檔，本 phase **不新建檔案**）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 做一個「一次塞 N 個檔」的新後端端點 | **design5 §6.4 明文**：「前端連發即可，不必再做一個一次塞 N 個檔的新後端」。端點數要維持 22（Phase 64 之後就不再變） |
| 用 `Promise.all` 一次把 N 個請求全部發出去 | 見 §4.4 的決策說明。順序送在本專案的條件下更好講、更好看、也不會比較慢 |
| 保留 201 後開 `classify_chain` 的邏輯「以防萬一」 | design5 D13 正式推翻。而且 202 的回應裡根本沒有 `suggested_folder`／`folders`，留著只會是一段炸掉的死碼 |
| 刪掉 `folder_modal.js`／`entity_modal.js`／`task_modal.js` | **不要刪檔**。design5 §2 末句寫明「檔案可留著給待決定頁組鏈」——Phase 70 的待決定頁要走完整三關，那三個窗正是主角。本 phase 只是**這一頁不再載入**它們 |
| 刪掉 `classify_chain.js` | **本 phase 更不能刪**——它這時還有另一個呼叫者（`camera-desk.html`，Phase 69 才拆）。刪掉的話鏡頭桌面頁當場炸 `startClassifyChain is not defined`。它的最終歸宿由 **Phase 70 §4.5** 決定：那裡會先 `grep` 確認零呼叫者、再把它刪掉 |
| 動頁首 `<header class="site-header">` | 那是 Phase 53 的地盤。四格導覽與 AI 開關一個字都不要碰 |
| 做拖放（drag & drop）上傳 | design5 沒要求。Phase 14 Q6／Phase 23 Q8 已經回答過同一題：不要 |
| 做上傳百分比進度條 | 我們沒有百分比可以顯示。而且 202 是毫秒級的，進度條會一閃而過 |
| 做「批次歸類」「一次勾多張」 | design5 §3「不做」第 1 條 |
| 在這一頁做失敗檔的「再試一次」按鈕 | design5 §3「不做」第 2 條：要重來就重新選檔 |
| 在這一頁顯示 job 進度 | 那是 Phase 67 的面板在做的事。這一頁只講「收下了沒」，收下之後就交棒 |
| 用 `alert`／`confirm`／`prompt` | 全站鐵律。所有訊息都寫進 `#result` 那張卡片 |
| 為這一頁新增 Playwright 自動化測試 | design5 §9 明文、Phase 14／23／24 的一貫慣例：純前端零新增自動化，改用瀏覽器實操驗收＋字串契約測試 |

---

## 4. 實作步驟

> ⚠ **本節的行號都是「增量五開工前」的 `upload.html`。** Phase 53（頂欄多一格）與
> Phase 67（掛 `progress_panel.js`）各讓後段行號往下漂 1 行，到本 phase 開工時
> 大約**整體 +2 行**。行號只當導覽用，**定位一律靠引用的原文搜尋**——引用的
> 「改寫前」內容本身沒有被 53／67 動過，逐字搜尋一定找得到。

### 4.1 改 `<p class="lead">` 文案（§6.4 第 4 條）

- [ ] 找到現在這兩行（開工前第 39〜40 行）：

```html
<p class="lead">選一張 JPEG／PNG，或一份 PDF（一頁會存成一張照片）。AI 會看圖並存成文字描述＋四個欄位，
接著在彈出的視窗裡決定要收進哪個資料夾——選定就定案，或按「稍後再說」先放進待決定區。</p>
```

- [ ] 換成（**完整新文案，照抄**）：

```html
<p class="lead">選一張或多張 JPEG／PNG，也可以混一份 PDF（PDF 一頁會存成一張照片）——一次可以選很多個。
按「上傳」之後系統會<strong>先把檔案收下</strong>，AI 看圖在背景進行，右下角看得到進度。
分析完成的照片會出現在「待決定」，到那裡再決定要收進哪個資料夾。</p>
```

- [ ] 既有那段「無線鏡頭」的 `<p class="note">` 裡有一句**已經變成錯話**——
      「拍完直接入庫」（202 之後拍完只是「收下」，入庫要等 worker）。把這兩行：

```html
<p class="note">東西還在手上？<a href="/ui/camera-desk.html">用手機拍</a>——
電腦顯示 QR，手機掃了就變成這台電腦的鏡頭，拍完直接入庫。</p>
```

　　換成：

```html
<p class="note">東西還在手上？<a href="/ui/camera-desk.html">用手機拍</a>——
電腦顯示 QR，手機掃了就變成這台電腦的鏡頭，拍完先收下、分析完進「待決定」。</p>
```

- [ ] 在那段「無線鏡頭」的 `<p class="note">` **之後**，再加一段（AI 開關的意義變了，要講清楚）：

```html
<!-- design5 D14：AI 開關是在「入列當下」拍一張快照存進任務裡，
     worker 照那張快照建 VLM 客戶端。所以撥開關只影響**之後**收下的檔。 -->
<p class="note">頁首的「AI 模型」開關決定<strong>接下來收下的檔</strong>用哪個後端看圖；
已經在排隊或分析中的不會改道。</p>
```

### 4.2 `<input>` 加 `multiple`（D3）

- [ ] 找到這一行（開工前第 43 行）：

```html
  <input type="file" id="file-input" class="field" accept="image/jpeg,image/png,application/pdf" required>
```

- [ ] 換成：

```html
  <input type="file" id="file-input" class="field" multiple
         accept="image/jpeg,image/png,application/pdf" required>
```

> `accept` 一個字都不要改——PDF 仍然可以跟圖片混在同一次選檔裡（D3 明寫）。
> `required` 也留著：它讓瀏覽器在完全沒選檔時直接擋下送出。

### 4.3 換掉 `<script src>` 那一區（D13 的第一半）

- [ ] 找到 `</main>` 之後那一整區 `<script src>`。**到本 phase 開工時它是六行**
      （前五行是增量五之前就有的；第六行是 Phase 67 §4.4 加的）：

```html
<script src="/ui/folder_modal.js"></script>
<script src="/ui/entity_modal.js"></script>
<script src="/ui/task_modal.js"></script>
<script src="/ui/classify_chain.js"></script>
<script src="/ui/ai_switch.js"></script>
<script src="/ui/progress_panel.js"></script>
```

- [ ] 換成下面這樣（＝**刪掉前四行**、保留 `ai_switch` 與 `progress_panel` 兩行、
      最前面補一段註解）：

```html
<!-- design5 D13：上傳當下不再開歸類鏈，所以這一頁不再載入三顆彈窗與鏈的共用檔。
     ⚠ 被拿掉的那四個共用檔**本身不要刪**：三顆彈窗是 Phase 70 待決定頁的主角；
       鏈的那一支這時還有鏡頭桌面頁在用（Phase 69 才拆），最終去留由 Phase 70 §4.5
       的 grep 閘門處理。檔名刻意不寫在這段註解裡——本 phase 的契約測試與 §6.1 的
       grep 會掃這一頁的原始碼，註解不能誤中（同彈窗共用檔檔頭那行註解的手法）。 -->
<script src="/ui/ai_switch.js"></script>
<script src="/ui/progress_panel.js"></script>
```

> ⚠ **註解裡不准出現那四個檔名（也不准出現 `201`）**——§4.7 的契約測試對這一頁
> 斷言「那些字串一個都不在」，寫進註解一樣紅。想留線索就照上面那段的寫法，
> 用「三顆彈窗」「鏈的那一支」代稱。

### 4.4 決策：**順序送**（`for...of` ＋ `await`），不是 `Promise.all`

design5 §6.4 只說「每個檔一個 `POST /photos`（前端連發即可）」，沒有規定怎麼連發。
兩種寫法都能跑，本 phase 選**順序送**：

```javascript
// ✓ 本 phase 採用：一次送一個，等前一個回來再送下一個
for (const file of files) {
  結果.push(await 送一個檔(file));
  renderBatch(files, 結果, false);      // 每送完一個就更新一次畫面
}

// ✗ 沒有採用：一次全部發出去
const 結果 = await Promise.allSettled(files.map(送一個檔));
```

**四條理由：**

1. **`Promise.all` 選 20 個檔時，後面 14 個會安靜地卡在瀏覽器裡。**
   瀏覽器對同一個網域同時只開約 6 條 HTTP/1.1 連線（uvicorn 預設不開 HTTP/2，所以這個上限是真的）。
   一次丟 20 個出去，第 7 個以後在 Network 分頁是 `Queued` 狀態——畫面上看起來「什麼都沒發生」，
   而我們**正好想要**「每送出一個就多一行結果」。順序送天然就是這個行為。

2. **202 是毫秒級的，順序送幾乎不會比較慢。**
   `POST /photos` 只做三件事：檢查 content type、把位元組寫進 `data/staging/`、丟一個 Celery 任務。
   沒有 VLM、沒有 embedding、沒有資料庫寫入。本機實測是幾十毫秒。
   20 個檔順序送 ≈ 1〜2 秒，跟並行的差別使用者感覺不到。
   （真正慢的是 VLM，而那早就搬到背景去了——這正是階段乙的重點。）

3. **錯誤好講。** 第 3 個檔是 `.txt` 被 415 擋下時，前兩個檔**已經明確入列了**，
   清單可以逐檔寫出「已收下／沒收下」。用 `Promise.allSettled` 的話，結果陣列要自己跟
   輸入陣列對位（`results[i]` 對 `files[i]`），一旦有人改了順序就會張冠李戴。

4. **程式碼短。** 一個 `for...of` ＋ 一個 `await`，沒有 `Promise` 組合子、沒有 `settled` 的
   `{status, value, reason}` 三種形狀要解。這是 side project。

**已知代價（誠實寫出來）：** 選 50 個檔時，最後一個要等前面 49 趟往返。
以上面的實測數字大約 3 秒。**現在不要為此做優化**（例如小批並行）；
真的哪天覺得慢，再回來看這一節，把 `for...of` 換成「每次取 4 個做 `Promise.allSettled`」即可。

### 4.5 415 為什麼不會出現在進度面板（新手最容易搞混的一點）

這一節不寫程式，但**一定要看懂**，不然驗收時會以為壞掉。

```text
選了三個檔：receipt.jpg（好）、notes.txt（格式不對）、scan.pdf（好）

  receipt.jpg ──POST /photos──► FastAPI ──► 格式 OK
                                       ──► 寫 data/staging/{job_id}.jpg
                                       ──► JobStore 記 queued
                                       ──► Celery 丟任務
                                       ◄── 202 {job_id: "7f3a…"}
                                            ★ 有 job → 右下角面板有這一列

  notes.txt   ──POST /photos──► FastAPI ──► 格式不對，**到此為止**
                                       ◄── 415 {"detail": "只接受 JPEG／PNG／PDF"}
                                            ★ 沒有 job、沒有 staging、沒有 Celery 任務
                                            ★ 所以右下角面板**永遠不會**有這一列

  scan.pdf    ──POST /photos──► …同 receipt.jpg…
```

所以錯誤分成兩種、**顯示在兩個不同的地方**：

| 種類 | 例子 | 誰發現的 | 顯示在哪 |
|---|---|---|---|
| **同步錯誤** | 415 不是 JPEG／PNG／PDF | FastAPI，在你按下按鈕的那一次請求裡 | **這一頁的結果卡片**（`#result`） |
| **非同步錯誤** | VLM 看不懂、連 3 次都失敗 | 背景的 worker，可能是 5 分鐘後 | **右下角的進度面板**（紅字那一列，可按 ×） |

design5 §8 錯誤表第 1 列就是在講這件事：「非 JPEG／PNG／PDF → HTTP 立刻 415；**無 job、無 staging**」。

**驗收時的判準：** 選一個 `.txt` 進去，結果卡片上要看到那一行紅字，
而右下角面板**不可以**多出一列。看到面板多一列＝後端違反了 §8 第 1 列，那是 Phase 62 的 bug。

### 4.6 換掉整段內嵌 `<script>`

- [ ] 把 `upload.html` **整段內嵌 `<script>`**（開工前第 63〜171 行；`<script>` 到
      `</script>` 含這兩行——認開頭那行註解 `// ===== 上傳頁自己的程式（這段不會搬走）=====`，
      這段內容 53／67 都沒動過）換成下面這一份。這是完整可執行的程式碼，沒有省略：

```html
<script>
// ===== 上傳頁自己的程式（design5 階段丙）=====
//
// 這一頁現在只做三件事：
//   ① 把選到的**每一個**檔各送一次 POST /photos（順序送；理由見計畫 §4.4）
//   ② 把每個檔的「收下了沒」畫成一行結果
//   ③ 叫右下角的進度面板立刻更新（ppStart() 來自共用檔 /ui/progress_panel.js）
//
// ⚠ design5 D13：入庫當下**不開**歸類鏈。
//   抽屜→實體→待辦整條鏈搬到「待決定」那一頁（/ui/pending.html）。
//   202 的回應裡也沒有 text／suggested_folder／folders 可以餵給鏈——
//   那時候照片還不存在（§4.2：VLM 成功之後才 INSERT）。
//
// ⚠ 全站鐵律：不用 alert／confirm／prompt；動態文字一律走 esc()；屬性不插值。

const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const button = document.getElementById("submit-button");
const result = document.getElementById("result");

// 把使用者提供的文字安全地放進 HTML。
// 不做這件事的話，檔名裡的一個 "<" 就會把版面弄壞，
// 更糟的情況是其中夾帶的內容被瀏覽器當成程式碼執行（XSS）。
function esc(value) {
  const 文字 = (value === null || value === undefined || value === "") ? "（無）" : value;
  return String(文字)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// FastAPI 的錯誤訊息有兩種形狀：我們自己丟的是字串，
// Pydantic 驗證失敗（422）則是一個陣列，裡面每筆有 msg。
// payload 是 null＝回應根本不是 JSON（例如中間有東西回了一頁 HTML 錯誤畫面）。
function 錯誤說明(payload) {
  if (!payload) return "伺服器沒有給說明";
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(function (one) {
      return one.msg || JSON.stringify(one);
    }).join("；");
  }
  return JSON.stringify(payload);
}

// 還沒選檔案之類的一行提示
function renderNotice(message) {
  result.innerHTML = '<p class="panel-empty">' + esc(message) + '</p>';
}

// 一批檔的結果卡片：一行一個檔。
// 送出中會被叫很多次（每送完一個就重畫一次），所以它是「照現況重畫」而不是「追加」。
function renderBatch(files, 結果, 送完了) {
  const 收下 = 結果.filter(function (one) { return one.ok; }).length;
  const 沒收下 = 結果.length - 收下;

  const 標題 = 送完了
    ? "已收下 " + 收下 + " 個檔" + (沒收下 > 0 ? "，" + 沒收下 + " 個沒收下" : "")
    : "送出中…（" + 結果.length + "／" + files.length + "）";

  // 這兩個值都是寫死的字串，沒有任何外來資料進到屬性裡（全站鐵律：屬性不插值）
  const 標題類別 = (送完了 && 沒收下 > 0) ? "status status-error" : "status status-ok";

  const 列 = files.map(function (file, index) {
    const 這個 = 結果[index];
    const 說明 = 這個 ? 這個.說明 : "等著送出…";
    return '<dt>' + esc(file.name) + '</dt><dd>' + esc(說明) + '</dd>';
  }).join("");

  const 尾註 = (送完了 && 收下 > 0)
    ? "分析在背景進行，右下角看得到進度。分析完成的照片會出現在「待決定」，到那裡歸類。"
    : "";

  result.innerHTML =
    '<p class="' + 標題類別 + '">' + esc(標題) + '</p>' +
    '<dl class="kv">' + 列 + '</dl>' +
    (尾註 ? '<p class="note">' + esc(尾註) + '</p>' : '');
}

// 送一個檔。永遠 resolve（不 throw），呼叫端才能一路跑完整批。
async function 送一個檔(file) {
  // FormData 會自動組成 multipart/form-data，欄位名必須是 file。
  // ⚠ 不要自己加 Content-Type：手動加會少掉分隔字串，伺服器解不開。
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/photos", { method: "POST", body: formData });

    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;               // 回的不是 JSON，交給 錯誤說明() 處理
    }

    // 202＝「已收下」，**不是**「已入庫」（design5 D7）。
    // 照片要等背景的 worker 分析成功之後才存在，那時它會出現在「待決定」。
    if (response.status === 202) {
      return { ok: true, 說明: "已收下，排隊分析中" };
    }
    // 415＝不是 JPEG／PNG／PDF。這個檔**根本沒有進佇列**（design5 §8 第 1 列），
    // 所以右下角的進度面板不會有它——它只會出現在這張清單裡（計畫 §4.5）。
    return {
      ok: false,
      說明: "（HTTP " + response.status + "）" + 錯誤說明(payload)
    };
  } catch (error) {
    return { ok: false, 說明: "送不出去。請確認服務已啟動後再試一次。" };
  }
}

form.addEventListener("submit", async function (event) {
  event.preventDefault();          // 不要讓瀏覽器用傳統方式送出表單並跳頁

  // FileList 不是真陣列（沒有 map／filter），先轉成陣列再用
  const files = Array.prototype.slice.call(fileInput.files);
  if (files.length === 0) {
    renderNotice("請先選一個或多個檔案。");
    return;
  }

  button.disabled = true;
  const 結果 = [];
  renderBatch(files, 結果, false);

  // ── 順序送：一次送一個，等前一個回來再送下一個（理由見計畫 §4.4）──
  let 已叫面板 = false;
  for (const file of files) {
    const 這個 = await 送一個檔(file);
    結果.push(這個);
    // 第一個真的入列的檔一出現就把面板叫起來，不必等整批送完。
    // ppStart() 可以重複呼叫（已經在跑就只是立刻多打一次），這裡仍然只叫一次。
    if (這個.ok && !已叫面板) {
      已叫面板 = true;
      ppStart();
    }
    renderBatch(files, 結果, false);
  }

  renderBatch(files, 結果, true);
  // 清空選檔框：不清的話，下一批會連同這一批一起再送一次
  fileInput.value = "";
  button.disabled = false;
});
</script>
```

- [ ] 存檔後在瀏覽器按 `Cmd + Shift + R` 強制重新整理（`StaticFiles` 每次都直接讀檔，
      不必重啟容器；`--reload` 只管 Python 檔）。

### 4.7 在 `tests/integration/test_progress_panel_contract.py` 尾端追加三顆

- [ ] Phase 67 已經建好這個檔（含 `讀()` 工具與 `專案根目錄`／`靜態目錄`）。
      **不要新建檔案**，把下面這一段接在檔尾：

```python
# ═══════════════════════════════════════════════════════════════════
# Phase 68：上傳頁多檔選檔（design5 D3／D13／§6.4）
# ═══════════════════════════════════════════════════════════════════


def test_上傳頁可以一次選多個檔():
    """D3：一次可選多張 JPEG／PNG，也可含 PDF。"""
    上傳頁 = 讀("upload.html")

    assert re.search(r'<input type="file"[^>]*\bmultiple\b', 上傳頁, re.S), (
        "upload.html 的 <input type=\"file\"> 少了 multiple——D3 要求一次可選多檔"
    )
    # PDF 仍可混在同一次選檔裡（§6.4 末句）
    assert "application/pdf" in 上傳頁


def test_上傳頁不再於入庫當下開歸類鏈():
    """D13：電腦上傳不再開抽屜→實體→待辦；202 的回應裡也沒有東西可以餵給鏈。

    ⚠ 這裡掃的是 upload.html **有沒有載入／呼叫**那些檔，
      不是「那些檔還在不在」——它們必須留著給 Phase 70 的待決定頁用（§2 末句）。

    最後一條連 `201` 這三個字都不准出現（包含註解）：
    留著一個舊的 `status === 201` 判斷是「安靜壞掉」的典型——
    頁面不報錯，只是每次上傳都走 else 分支顯示成失敗。
    （同 folder_modal.js 第 7 行的自我提醒手法：註解也不要誤中。）
    """
    上傳頁 = 讀("upload.html")

    assert "startClassifyChain" not in 上傳頁
    for 檔名 in ["classify_chain.js", "folder_modal.js", "entity_modal.js", "task_modal.js"]:
        assert 檔名 not in 上傳頁, f"upload.html 還在載入 {檔名}——D13 起這一頁不開鏈"

    assert "response.status === 202" in 上傳頁
    assert "201" not in 上傳頁


def test_上傳頁是順序送不是一次全發():
    """§4.4 的決策：for...of ＋ await，一次一個。"""
    上傳頁 = 讀("upload.html")

    assert "for (const file of files)" in 上傳頁
    assert "Promise.all" not in 上傳頁
    assert "ppStart()" in 上傳頁          # 送完要把進度面板叫起來
```

- [ ] 跑它：

```bash
pytest tests/integration/test_progress_panel_contract.py -v
# 預期：10 passed（Phase 67 的 7 顆 ＋ 本 phase 的 3 顆）
```

---

## 5. ASCII 圖

### 5.1 選 3 個檔的時間軸（改版前 vs 改版後）

```text
════ 改版前（同步，一次一個檔）════════════════════════════════════════
 t=0    選 receipt.jpg → 按上傳
 t=0    POST /photos ────────────────────────────────────► FastAPI
        （按鈕變灰，畫面寫「上傳中…」，人只能等）
 t=3分  ◄──────────────────────────────── 201 ＋ text ＋ suggested_folder
        跳出抽屜彈窗 → 選資料夾 → 實體窗 → 待辦窗
 t=4分  終於可以選第二個檔
        …三個檔＝十二分鐘，而且全程不能離開這一頁


════ 改版後（202 ＋ 背景 worker）══════════════════════════════════════
 t=0.0s 一次框選 receipt.jpg、menu.pdf、bill.png → 按上傳

 t=0.0s  POST /photos (receipt.jpg) ──► ◄── 202 {job_id: A}   ┐
 t=0.1s  POST /photos (menu.pdf)   ──► ◄── 202 {job_id: B}   ├ 順序送，
 t=0.2s  POST /photos (bill.png)   ──► ◄── 202 {job_id: C}   ┘ 但快到看不出來

 t=0.2s  結果卡片：已收下 3 個檔
         右下角面板：┌ 處理中 ─────────────┐
                     │ receipt.jpg          │
                     │ 排隊中               │
                     │ menu.pdf             │
                     │ 排隊中               │
                     │ bill.png             │
                     │ 排隊中               │
                     └──────────────────────┘
         ★ 這一刻就可以再選下一批、或換頁去問問題。人不必留在這裡。

 t=0.3s  兩個 worker 各拿一個（concurrency=2，D6）
         面板：receipt.jpg → 分析中（第 1 次）
               menu.pdf   → 第 1／4 頁・分析中（第 1 次）
               bill.png   → 排隊中          ← 只有兩個 worker，第三個排隊

 t≈1分   receipt.jpg 成功 → 伺服器 delete(job A)
         面板那一列**自己消失**；頂欄「待決定（N）」→「待決定（N+1）」
         bill.png 遞補進 分析中

 t≈4分   三個都完成 → jobs 空了 → 面板整塊收起
         頂欄「待決定（N+6）」＝ 2 張圖 ＋ PDF 4 頁各一張（一頁一張照片；
         PDF 只成功 3 頁的話就是 N+5——跳過的頁不進待決定）

        到「待決定」點開，一張一張歸類（Phase 70 的完整三關）
```

### 5.2 一次選檔會發生什麼（資料流）

```text
  <input type="file" multiple>
        │  使用者框選 3 個檔
        ▼
  fileInput.files  ← FileList（不是陣列！）
        │  Array.prototype.slice.call(…)
        ▼
  files = [File, File, File]
        │
        │  for (const file of files) { await 送一個檔(file); … }
        │  ↑ 一次一個，等前一個回來
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 送一個檔(file)                                            │
  │   FormData().append("file", file)                        │
  │   fetch("/photos", {method:"POST", body: formData})      │
  │        │                                                  │
  │        ├─ 202 → { ok: true,  說明: "已收下，排隊分析中" } │
  │        ├─ 415 → { ok: false, 說明: "（HTTP 415）…" }      │
  │        └─ 例外 → { ok: false, 說明: "送不出去。…" }        │
  │   ★ 永遠 resolve、不 throw：一個檔壞掉不能中斷整批         │
  └──────────────────────────────────────────────────────────┘
        │
        ├─ 第一個 ok 的 → ppStart()   ← 右下角面板立刻更新，不必等 2 秒
        │
        ▼
  renderBatch(files, 結果, 送完了)
        │
        ▼
  ┌── #result ────────────────────────────────────┐
  │ ● 已收下 2 個檔，1 個沒收下                    │
  │ receipt.jpg   已收下，排隊分析中               │
  │ notes.txt     （HTTP 415）只接受 JPEG／PNG／PDF │  ← 同步錯誤在這裡
  │ scan.pdf      已收下，排隊分析中               │
  │ ─────────────────────────────────────────────  │
  │ 分析在背景進行，右下角看得到進度。…             │
  └───────────────────────────────────────────────┘

  ★ notes.txt **不會**出現在右下角的進度面板——它根本沒進佇列（§4.5）
```

---

## 6. 驗收清單

### 6.1 自動化（跑指令）

- [ ] **契約測試十顆全綠**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest tests/integration/test_progress_panel_contract.py -v
```
      預期：`10 passed`（Phase 67 的 7 顆＋本 phase 的 3 顆）

- [ ] **全量測試 ＝ 開工前的 N ＋ 3**

```bash
pytest -q
```
      預期：`(N+3) passed`。⚠ **絕對不要同時跑兩份 pytest**。

- [ ] **端點數沒有變**（本 phase 純前端，仍是 22）

```bash
pytest tests/integration/test_ask_three_paths.py::test_端點數不變 -q
```

- [ ] **上傳頁真的不再開鏈了**

```bash
grep -nE "classify_chain|startClassifyChain|folder_modal|entity_modal|task_modal|201" \
  app/static/upload.html || echo "OK：這一頁不開鏈、也沒有殘留的 201 判斷"
```
      預期：`OK：這一頁不開鏈、也沒有殘留的 201 判斷`

- [ ] **那四個共用檔都還在**（本 phase 只是不載入，**不刪檔**）

```bash
ls app/static/classify_chain.js app/static/folder_modal.js \
   app/static/entity_modal.js app/static/task_modal.js
```
      預期：四個檔都列得出來

- [ ] **沒有原生對話框、沒有引入前端相依**

```bash
grep -nE "alert\(|confirm\(|prompt\(" app/static/upload.html || echo "OK：沒有原生對話框"
ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
```

- [ ] **只動到兩個檔（跟 §2 抄下的快照相減）**

```bash
git status --short -- app tests > /tmp/p68-after.txt
diff /tmp/p68-before.txt /tmp/p68-after.txt
```
      預期：`diff` **沒有多出任何一列**（兩個被改的檔——`app/static/upload.html`、
      `tests/integration/test_progress_panel_contract.py`——在前面的 phase 就已經
      出現在快照裡了，本 phase 只是繼續改它們）。有多出來的列＝動到了不該動的檔。
      實際改了什麼用 `git diff app/static/upload.html` 看
      （契約測試檔若整個增量還沒 commit 會是 `??`，直接開檔看尾端三顆）。

### 6.2 瀏覽器實操（本 phase 的主要驗收方式）

準備：頁首的「AI 模型」開關撥到**雲端**（本機看一張圖 1〜5 分鐘）。測試檔：

```bash
screencapture -x /tmp/a.png
cp /tmp/a.png /tmp/b.png && cp /tmp/a.png /tmp/c.png
echo "這不是圖片" > /tmp/notes.txt
# 兩頁以上的 PDF：手邊沒有的話用「預覽程式」把兩張圖合併輸出成 PDF
```

開 `https://localhost:8000/ui/upload.html`：

- [ ] **1. 選檔視窗真的可以複選**
      按「選擇檔案」→ 在選檔視窗按住 `Cmd` 點 `/tmp/a.png`、`/tmp/b.png`、`/tmp/c.png`。
      **看到**：選檔框顯示「已選擇 3 個檔案」。（沒有 `multiple` 的話只選得到一個。）

- [ ] **2. 三個檔一秒內全部收下（design5 §12 階段丙第 1 條）**
      按「上傳」。
      **看到**：（a）結果卡片幾乎是瞬間變成「已收下 3 個檔」，三行檔名各寫「已收下，排隊分析中」；
      （b）右下角出現「處理中」面板，**三列**；（c）選檔框已經清空、按鈕已經恢復可按。
      ⚠ **不可以**跳出任何彈窗（D13）。

- [ ] **3. 可以立刻再選下一批**
      不等前一批跑完，馬上再選 `/tmp/a.png` 上傳一次。
      **看到**：結果卡片換成新的一批；右下角面板變成**四列**（前三列還在跑）。

- [ ] **4. 成功列自己消失、N 加上去（§12 階段丙第 2 條）**
      先記下頂欄「待決定（N）」。等它們跑完。
      **看到**：面板的列一個一個**自己不見**；全部完成後面板整塊收起；
      頂欄變成「待決定（N+4）」。

- [ ] **5. 415 顯示在頁面上、不進進度面板（§4.5 的重點）**
      選 `/tmp/a.png` ＋ `/tmp/notes.txt` ＋ `/tmp/b.png` 三個一起上傳。
      **看到**：結果卡片是「已收下 2 個檔，1 個沒收下」，`notes.txt` 那一行是
      `（HTTP 415）…`；右下角面板**只有兩列**，沒有 `notes.txt`。
      核對後端：
```bash
curl -sk https://127.0.0.1:8000/ingest-jobs | python -m json.tool
```
      **看到**：`jobs` 裡沒有任何 `notes.txt`。

- [ ] **6. PDF 可以跟圖混在同一次選檔**
      選 `/tmp/a.png` ＋ 那份兩頁 PDF 一起上傳。
      **看到**：兩列進度；PDF 那一列拆完頁後顯示「檔名（2 頁）」與「第 1／2 頁・分析中（第 1 次）」。
      完成後頂欄 N 加 **3**（1 張圖 ＋ PDF 兩頁各一張）。

- [ ] **7. 送出中畫面會逐檔更新**
      一次選 8 個檔上傳，盯著結果卡片。
      **看到**：標題從「送出中…（0／8）」一路數到「（8／8）」，最後變「已收下 8 個檔」；
      每一行的說明從「等著送出…」逐一變成「已收下，排隊分析中」。

- [ ] **8. 什麼都不選就按上傳**
      清空選檔框後按「上傳」。
      **看到**：瀏覽器自己擋下來（`required` 的效果），或是結果卡片寫「請先選一個或多個檔案。」。
      **不可以**跳原生對話框。

- [ ] **9. 服務沒起來時的訊息不外洩**
      停掉 app 容器再上傳一次：
```bash
docker compose -f compose.yaml stop app
```
      **看到**：每一行都寫「送不出去。請確認服務已啟動後再試一次。」，
      **沒有**原始例外文字、**沒有**「uvicorn」字樣（沿 Phase 44 的既有規矩）。驗完記得：
```bash
docker compose -f compose.yaml up -d app
```

- [ ] **10. 主控台乾淨**
      整趟走下來，Console 沒有紅色錯誤，特別不該有
      `startClassifyChain is not defined`（代表有殘留呼叫）或
      `ppStart is not defined`（代表 `<script src>` 順序錯了）。

- [ ] **11. 待決定那一頁真的收得到**
      點頂欄「待決定（N）」→ 剛剛那幾張都在縮圖牆上，點一張會開歸類彈窗。
      （完整三關是 Phase 70 的事；本 phase 只要確認「照片有到那裡」。）

---

## 7. 常見陷阱

1. **`fileInput.files` 直接 `.map` 或 `.forEach`。**
   症狀：`fileInput.files.map is not a function`。
   原因：`FileList` 長得很像陣列，但不是陣列。
   **先 `Array.prototype.slice.call(fileInput.files)` 轉成真陣列**。

2. **忘了 `fileInput.value = ""`。**
   症狀：第二次按上傳時，上一批的檔又被送了一次（照片重複入庫，而且沒有任何錯誤訊息）。
   原因：選檔框裡的檔案不會因為「送出過」就自動清掉。
   **每批送完就清空**。

3. **`ppStart is not defined`。**
   症狀：檔案送出去了、後端也收下了，但右下角什麼都沒有，Console 一行紅字。
   原因：`<script src="/ui/progress_panel.js">` 放在頁面自己的 `<script>` **後面**，或根本忘了加。
   **一定要放在 inline `<script>` 之前**（§4.3 的順序）。

4. **留著舊的 `if (response.status === 201)`。**
   症狀：上傳明明成功，畫面每次都寫失敗。而且**不會報錯**——安靜地走 else 分支。
   原因：Phase 62 之後成功是 202。
   §4.7 的契約測試專門擋這個（連註解裡的 `201` 都不准出現）。

5. **在迴圈裡對 `結果[index]` 取值時 index 對不上。**
   症狀：`notes.txt` 那一行顯示成「已收下」，`receipt.jpg` 顯示成 415。
   原因：`renderBatch` 是用 `files.map((file, index) => 結果[index])` 對位的，
   而 `結果` 是照順序 `push` 進去的——**只有順序送才保證對得上**。
   如果哪天改成並行，這裡一定要跟著改成把 `file` 存進結果物件裡。

6. **手動加 `Content-Type: multipart/form-data`。**
   症狀：伺服器回 422，訊息看起來像「少了 file 欄位」。
   原因：`multipart` 的標頭裡有一段隨機分隔字串（boundary），必須由瀏覽器產生。
   自己寫死那一行就沒有 boundary，伺服器解不開。
   **`FormData` 交給 `fetch` 就好，什麼標頭都不要加。**

7. **把那四個檔一起刪掉。**
   症狀：`camera-desk.html` 當場炸 `startClassifyChain is not defined`（它 Phase 69 才拆）；
   或 Phase 70 做待決定完整三關時發現三顆彈窗檔不見了。
   原因：把「這一頁不載入」誤解成「這個功能不要了」。
   **只刪 `<script src>` 那四行，檔案留著。**
   （`classify_chain.js` 的最終去留是 Phase 70 §4.5 的事——那裡有 grep 閘門。）

8. **用 `Promise.all` 「順便加速」。**
   症狀：選 20 個檔時，前 6 個很快出現、後面 14 個停在「等著送出…」好幾秒；
   或者某一個檔失敗就整批中斷。
   原因：瀏覽器連線數上限 ＋ `Promise.all` 的「一個 reject 全部 reject」。
   **照 §4.4 用 `for...of`。** 真的要並行也要用 `allSettled`，而且要把 `file` 存進結果物件裡對位。

9. **以為 415 的檔會出現在進度面板。**
   症狀：驗收時覺得「面板漏了一列」，開始懷疑 Phase 67 壞掉。
   原因：沒看懂 §4.5——415 是同步錯誤，那個檔根本沒有 job。
   **這是正確行為。** 反過來說：如果它真的出現在面板裡，那才是 bug（Phase 62 的）。

10. **順手改頁首。**
    症狀：`git diff` 出現一堆頂欄的改動，Phase 53 的四格導覽被改壞。
    原因：整份覆蓋 `upload.html` 而不是照 §4.1〜§4.6 逐段換。
    **`<header class="site-header">` 那一整塊一個字都不要動。**

11. **把 AI 開關拿掉「反正這一頁不看圖了」。**
    症狀：切不了雲端，煙霧測試要 5 分鐘一張。
    原因：誤以為 202 之後開關沒用了。
    **開關仍然有意義**——design5 D14：入列當下會把 `config.AI_BACKEND` 拍成快照存進任務，
    worker 照那張快照建 VLM 客戶端。撥開關＝決定**接下來收下的檔**用哪個後端。

12. **在 `renderBatch` 的 class 屬性裡插使用者資料。**
    症狀：檔名裡剛好有 `"` 就把 HTML 弄壞。
    原因：違反全站鐵律「屬性不插值」。
    §4.6 的寫法是**在兩個寫死的字串之間二選一**，沒有任何外來資料進到屬性裡——照抄就對了。

13. **在 `<script src>` 那段替換註解裡寫出那四個檔名（或 `201`）。**
    症狀：`test_上傳頁不再於入庫當下開歸類鏈` 紅掉，訊息說 upload.html 還在載入某個檔——
    但你明明已經把 `<script src>` 刪乾淨了。
    原因：那顆測試掃的是**整頁原始碼的字串**，註解一樣算。
    「好心留線索」寫 `classify_chain.js 由 Phase 70 刪` 這種註解，就是自己把紅字寫進去。
    **照 §4.3 給的註解逐字貼**（它刻意用「三顆彈窗」「鏈的那一支」代稱），
    要改寫也先跑一次 §6.1 那條 grep 自查。
