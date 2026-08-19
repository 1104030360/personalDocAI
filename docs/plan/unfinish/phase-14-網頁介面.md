# Phase 14：極簡網頁介面（上傳頁＋問答頁）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 加上兩個純 HTML 頁面（`app/static/upload.html`、`app/static/ask.html`），用 FastAPI 的 StaticFiles 掛在 `/ui`，讓你用瀏覽器就能操作既有的兩個 API——**不新增任何後端端點、不用任何前端框架**。

---

## 前置條件

- 需要已完成的 phase：**Phase 13**（後端完成、49 個測試全綠）。
- 環境：Ollama 與 PostgreSQL 都要真的在跑（這個 phase 是**手動用瀏覽器操作**，走的是真模型那條路）。
  ```bash
  brew services start postgresql@17
  brew services start ollama
  ```
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

到目前為止，要用這個系統只能打 `curl`。design.md v4 加了一個很小的東西：**兩個網頁**。

- **上傳頁**：選一張照片 → 按鈕 → 顯示 AI 看懂了什麼（或錯誤訊息）。
- **問答頁**：打一個問題（中文或英文都行）→ 按鈕 → 顯示回答、系統選了哪種查法、依據哪幾張照片。

**這不是第三個功能**（design.md §3 明講）：頁面沒有新增任何交互點，只是同兩個既有 API 的操作介面。所以規格「僅兩項功能」沒有被違反，12 條 Rule 也完全不受影響。

**技術上刻意極簡到不能再簡**：

- **純 HTML ＋ 原生 JavaScript**——用瀏覽器內建的 `fetch()` 呼叫 API。
- **零框架**（不用 React／Vue／jQuery）、**零打包工具**（不用 npm、webpack、vite）、**零 CSS 框架**。
- **零新增端點**——後端只多一行 `app.mount(...)` 把 `app/static/` 這個資料夾當靜態檔案送出去。
- **零新增自動化測試**——頁面驗收是手動用瀏覽器點一點（design.md §6「頁面驗收以手動瀏覽器操作為準」）。`pytest -q` 仍然是 **49 passed**，一個都不會變。

**頁面醜沒關係，能用就好。** 這是 side project 的網頁介面，不是產品。想加深色模式、動畫、上傳進度條、拖放上傳、照片預覽的時候，答案一律是「不要」。

**名詞**：
- **靜態檔案（static files）**＝伺服器不做任何運算、直接原封不動送出去的檔案，例如 `.html`、`.css`、`.js`、圖片。
- **StaticFiles**＝FastAPI（其實是底層的 Starlette）內建的元件，一行就能把某個資料夾當靜態檔案對外提供。
- **`fetch()`**＝瀏覽器內建的函式，讓網頁用 JavaScript 送出 HTTP 請求並拿到回應。不需要安裝任何東西。
- **`FormData`**＝瀏覽器內建的物件，用來組出 `multipart/form-data` 格式的請求內容——正好就是 `POST /photos` 要的格式。
- **`async`／`await`**＝JavaScript 的「等待」寫法：`await fetch(...)` 是「等伺服器回應回來，再繼續執行下一行」；有用到 `await` 的函式前面要標 `async`。等待期間頁面不會卡死。
- **`addEventListener`**＝幫網頁元素掛上「某事件發生時要執行的函式」。本 phase 用它掛「表單被送出時，執行這段呼叫 API 的程式」。
- **同源（same-origin）**＝網頁的網址與 API 的網址「協定＋主機＋埠號」三者完全相同。同源就不會有 CORS 問題（見常見問題 Q1）。

---

## ASCII 圖：兩頁的線框（wireframe）

**線框圖**＝只畫「有哪些東西、放在哪裡」的草圖，不管顏色與美感。

```
┌──────────────────────────────────────────────────────────────┐
│  http://localhost:8000/ui/upload.html                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   Visual Memory RAG                                          │
│   [ 上傳照片 ]  [ 問問題 ]        ← 兩頁互相連結的文字連結     │
│   ──────────────────────────────────────────────────────     │
│                                                              │
│   上傳照片                                                    │
│   選一張 JPEG 或 PNG，AI 會看圖並存成文字＋四個欄位。            │
│                                                              │
│   ┌────────────────────────┐  ┌────────┐                     │
│   │ 選擇檔案 │ 未選擇檔案   │  │  上傳  │  ← <input type=file>  │
│   └────────────────────────┘  └────────┘     ＋ <button>      │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ ✅ 上傳成功（HTTP 201）                                │   │
│   │ 照片 id：1                                            │   │
│   │ 文字描述：在 Target 購買可樂與洋芋片的收據…             │   │
│   │ 類別：收據                                            │   │
│   │ 地點：Target                                          │   │
│   │ 物品：可樂、洋芋片                                     │   │
│   │ 內容時間：2026-08-10                                   │   │
│   └──────────────────────────────────────────────────────┘   │
│      ↑ 結果區 <pre id="result">                               │
│        失敗時顯示：❌ 失敗（HTTP 415）上傳檔案必須為…           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  http://localhost:8000/ui/ask.html                           │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   Visual Memory RAG                                          │
│   [ 上傳照片 ]  [ 問問題 ]                                     │
│   ──────────────────────────────────────────────────────     │
│                                                              │
│   問問題（中文或英文都可以）                                    │
│                                                              │
│   ┌────────────────────────────────────────┐  ┌────────┐     │
│   │ 我最近買過什麼飲料？                     │  │  送出  │     │
│   └────────────────────────────────────────┘  └────────┘     │
│      ↑ <input type=text>                        ＋ <button>   │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │ 回答：                                                │   │
│   │ 你最近買過可樂。                                       │   │
│   │                                                      │   │
│   │ 檢索方式：vector semantic search                       │   │
│   │ 依據照片 id：1, 3                                      │   │
│   └──────────────────────────────────────────────────────┘   │
│      ↑ 結果區 <pre id="result">                               │
└──────────────────────────────────────────────────────────────┘

 資料怎麼流（兩頁都一樣，同源所以沒有 CORS 問題）：

   瀏覽器  ──GET /ui/upload.html──▶  FastAPI StaticFiles ──▶ app/static/upload.html
      │
      │  頁面裡的 JavaScript
      └──fetch POST /photos ──────▶  api/routers/photos.py ──▶ services ──▶ repository
                                           │
      ◀────── 201 / 415 / 422 JSON ────────┘
```

---

## 逐步驟操作

### 步驟 1：建立 `app/static/` 資料夾

```bash
cd /Users/linjunting/personalDocAI
mkdir -p app/static
```

> 這個資料夾**不需要** `__init__.py`——它放的是 HTML，不是 Python 程式碼，Python 不會 import 它。

### 步驟 2：在 `app/main.py` 掛上靜態檔案

把 Phase 11 寫的 `main.py` 改成：

```python
"""FastAPI app 組裝：掛上兩個 router ＋ 極簡網頁介面（靜態檔案）。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers import ask, photos

app = FastAPI(title="Visual Memory RAG")

app.include_router(photos.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, str]:
    """確認服務活著用的簡單端點。"""
    return {"status": "ok"}


# 極簡網頁介面【design.md v4】：把 app/static/ 這個資料夾直接當靜態檔案送出。
# 網址會變成 /ui/upload.html 與 /ui/ask.html。
# 這一行不是新增 API 端點，只是「把檔案原封不動送出去」。
# Path(__file__).resolve().parent ＝ app/ 這個資料夾的絕對路徑，
# 這樣不管在哪個目錄啟動 uvicorn 都找得到 static/。
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/ui", StaticFiles(directory=STATIC_DIR), name="ui")
```

### 步驟 3：寫 `app/static/upload.html`

整份檔案照抄即可（HTML、CSS、JavaScript 全在同一個檔案裡——這樣就不用管打包）：

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>上傳照片 — Visual Memory RAG</title>
<style>
  body { font-family: system-ui, "PingFang TC", sans-serif;
         max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  nav a { margin-right: 1rem; }
  form { margin: 1rem 0; }
  button { padding: 0.4rem 1rem; }
  pre { background: #f4f4f4; padding: 1rem; white-space: pre-wrap;
        word-break: break-word; min-height: 4rem; }
</style>
</head>
<body>

<h1>Visual Memory RAG</h1>
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
<hr>

<h2>上傳照片</h2>
<p>選一張 JPEG 或 PNG，AI 會看圖並存成文字描述＋四個欄位。原始照片檔不會被保留。</p>

<form id="upload-form">
  <input type="file" id="file-input" accept="image/jpeg,image/png" required>
  <button type="submit" id="submit-button">上傳</button>
</form>

<pre id="result">（尚未上傳）</pre>

<script>
const form = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const button = document.getElementById("submit-button");
const result = document.getElementById("result");

// 沒有值的欄位顯示成「（無）」，比顯示 null 好懂
function orNone(value) {
  return (value === null || value === undefined || value === "") ? "（無）" : value;
}

form.addEventListener("submit", async function (event) {
  event.preventDefault();               // 不要讓瀏覽器用傳統方式送出表單並跳頁

  const file = fileInput.files[0];
  if (!file) {
    result.textContent = "請先選一個檔案。";
    return;
  }

  button.disabled = true;
  result.textContent = "上傳中…（本機模型看圖可能要等 10〜60 秒，請耐心等候）";

  // FormData 會自動組成 multipart/form-data，欄位名必須是 file
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch("/photos", { method: "POST", body: formData });
    const body = await response.json();

    if (response.status === 201) {
      const m = body.metadata;
      const items = (m.items && m.items.length > 0) ? m.items.join("、") : "（無）";
      result.textContent = [
        "✅ 上傳成功（HTTP 201）",
        "照片 id：" + body.id,
        "文字描述：" + body.text,
        "類別：" + orNone(m.category),
        "地點：" + orNone(m.location),
        "物品：" + items,
        "內容時間：" + orNone(m.content_time)
      ].join("\n");
    } else {
      // 415＝不是 JPEG/PNG；422＝VLM 看不懂（什麼都沒存）；其他＝伺服器問題
      const detail = (typeof body.detail === "string")
        ? body.detail : JSON.stringify(body.detail);
      result.textContent = "❌ 失敗（HTTP " + response.status + "）\n" + detail;
    }
  } catch (error) {
    result.textContent = "❌ 請求失敗：" + error
      + "\n最常見原因：uvicorn 沒在跑，或網址、埠號不對。"
      + "\n若 uvicorn 其實在跑，改看它的終端機視窗印出的錯誤訊息。";
  } finally {
    button.disabled = false;
  }
});
</script>

</body>
</html>
```

### 步驟 4：寫 `app/static/ask.html`

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>問問題 — Visual Memory RAG</title>
<style>
  body { font-family: system-ui, "PingFang TC", sans-serif;
         max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  nav a { margin-right: 1rem; }
  form { margin: 1rem 0; display: flex; gap: 0.5rem; }
  input[type=text] { flex: 1; padding: 0.4rem; }
  button { padding: 0.4rem 1rem; }
  pre { background: #f4f4f4; padding: 1rem; white-space: pre-wrap;
        word-break: break-word; min-height: 4rem; }
  .hint { color: #666; font-size: 0.9rem; }
</style>
</head>
<body>

<h1>Visual Memory RAG</h1>
<nav>
  <a href="/ui/upload.html">上傳照片</a>
  <a href="/ui/ask.html">問問題</a>
</nav>
<hr>

<h2>問問題（中文或英文都可以）</h2>
<p class="hint">
  例如：「有哪些在 Target 拍的收據？」、「我最近買過什麼飲料？」、
  "What drinks did I buy recently?"　——回答的語言會跟著你提問的語言。
</p>

<form id="ask-form">
  <input type="text" id="question-input" placeholder="輸入你的問題…" required>
  <button type="submit" id="submit-button">送出</button>
</form>

<pre id="result">（尚未提問）</pre>

<script>
const form = document.getElementById("ask-form");
const questionInput = document.getElementById("question-input");
const button = document.getElementById("submit-button");
const result = document.getElementById("result");

form.addEventListener("submit", async function (event) {
  event.preventDefault();

  const question = questionInput.value.trim();
  if (question === "") {
    result.textContent = "請先輸入問題。";
    return;
  }

  button.disabled = true;
  result.textContent = "思考中…（本機模型要判斷查法再產生回答，可能要等一下）";

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question })
    });
    const body = await response.json();

    if (response.status === 200) {
      const ids = (body.retrieved_photo_ids.length > 0)
        ? body.retrieved_photo_ids.join(", ")
        : "（沒有找到相關照片）";
      result.textContent = [
        "回答：",
        body.answer,
        "",
        "檢索方式：" + body.search_mode,
        "依據照片 id：" + ids
      ].join("\n");
    } else {
      const detail = (typeof body.detail === "string")
        ? body.detail : JSON.stringify(body.detail);
      result.textContent = "❌ 失敗（HTTP " + response.status + "）\n" + detail;
    }
  } catch (error) {
    result.textContent = "❌ 請求失敗：" + error
      + "\n最常見原因：uvicorn 沒在跑，或網址、埠號不對。"
      + "\n若 uvicorn 其實在跑，改看它的終端機視窗印出的錯誤訊息。";
  } finally {
    button.disabled = false;
  }
});
</script>

</body>
</html>
```

### 步驟 5：啟動服務並打開頁面

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

在瀏覽器打開：

- <http://localhost:8000/ui/upload.html>
- <http://localhost:8000/ui/ask.html>

（也可以用指令直接開：`open http://localhost:8000/ui/upload.html`。）

---

## 驗收標準

這個 phase 的驗收**全部是手動用瀏覽器操作**（design.md §6 明訂）。照下面順序做，每一步用眼睛核對畫面。

1. **靜態檔案真的被掛上了**
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/ui/upload.html
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/ui/ask.html
   ```
   預期：兩行都印出 `200`。

2. **上傳頁：成功路徑**
   - 打開 <http://localhost:8000/ui/upload.html>
   - 按「選擇檔案」，挑一張手邊的 JPEG 或 PNG（沒有的話先執行 `screencapture -x /tmp/real_photo.png` 產生一張）。
   - 按「上傳」。
   - **預期畫面**：按鈕變成不能按、結果區顯示「上傳中…」；等 10〜60 秒後變成
     ```
     ✅ 上傳成功（HTTP 201）
     照片 id：1
     文字描述：（AI 寫的一句話）
     類別：…
     地點：…
     物品：…
     內容時間：…
     ```
     欄位值會依照片而定，`（無）` 也算正常。重點是**七行都在**、`照片 id` 是一個數字。

3. **上傳頁：415 失敗路徑**
   - 這個頁面的 `accept="image/jpeg,image/png"` 只是「檔案選擇視窗的篩選提示」，**不是後端檢查**——415 的檢查在後端（Phase 4 寫的），所以選得到非圖片檔就一定會被擋。
   - 先產生一個文字檔：`echo hi > /tmp/x.txt`
   - 在選檔視窗選它（視窗若有「所有檔案」之類的選項就切過去）。**若你的瀏覽器選不到 `.txt`**（檔名反灰、也沒有切換選項——macOS 上很常見）：暫時把 `upload.html` 裡的 `accept="image/jpeg,image/png"` 那一段刪掉、重新整理頁面再選一次（StaticFiles 每次都直接讀檔案，重新整理就會拿到改過的頁面），**測完記得加回去**。
   - 按「上傳」。
   - **預期畫面**：
     ```
     ❌ 失敗（HTTP 415）
     上傳檔案必須為常見圖片格式（如 JPEG、PNG）
     ```

4. **問答頁：中文提問**
   - 打開 <http://localhost:8000/ui/ask.html>
   - 輸入「有哪些在 Target 拍的收據？」按「送出」。
   - **預期畫面**：結果區出現「回答：」＋一段**中文**回答，接著兩行 `檢索方式：metadata search`（或 `vector semantic search`）與 `依據照片 id：…`。

5. **問答頁：英文提問（雙語驗收）**
   - 輸入 `What drinks did I buy recently?` 按「送出」。
   - **預期畫面**：回答是**英文**句子；`檢索方式：vector semantic search`。
   - （真模型偶爾會不聽話，這是手動煙霧測試不是自動化驗收——重點是頁面把三個欄位都顯示出來了。）

6. **問答頁：查無資料**
   - 先確認資料庫是空的：`psql -d visual_memory -c "TRUNCATE TABLE photo RESTART IDENTITY;"`（**這會清空正式資料庫**，介意的話跳過這一項）。
   - 問「有哪些在 Costco 拍的收據？」。
   - **預期畫面**：回答是「查無相關照片」之類的句子，`依據照片 id：（沒有找到相關照片）`。

7. **兩頁的連結互通**
   - 在上傳頁點「問問題」會跳到問答頁，反之亦然。

8. **瀏覽器主控台沒有錯誤**
   - 在頁面上按 `Cmd + Option + I` 打開開發者工具，切到 Console 分頁。
   - 重新整理並操作一次。
   - **預期**：Console 沒有紅色錯誤訊息（特別是**不該**出現任何 CORS 相關字樣）。

9. **後端測試數量完全沒變**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   pytest -q
   ```
   預期：`49 passed`——本 phase 不新增、不修改任何自動化測試。

10. **沒有新增後端端點**
    ```bash
    grep -rnE "@router\.(get|post|put|patch|delete)" app/api/routers/
    grep -nE "@app\.(get|post|put|patch|delete)" app/main.py
    ```
    預期：仍然只有 `POST /photos`、`POST /ask`、`GET /health` 三行——`app.mount(...)` 不是端點。

11. **沒有引入任何前端相依**
    ```bash
    ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
    grep -riE "cdn|unpkg|jsdelivr|react|vue|jquery" app/static/ || echo "OK：沒有外部前端函式庫"
    ```
    預期：`OK：沒有 npm、沒有打包工具` 與 `OK：沒有外部前端函式庫`。

---

## 常見問題

**Q1：不是說跨網頁呼叫 API 會被 CORS 擋住嗎？為什麼這裡不用處理？**
**CORS**（Cross-Origin Resource Sharing，跨來源資源共用）是瀏覽器的安全機制：只有當網頁的來源和 API 的來源**不同**時才會啟動。「來源」＝協定＋主機＋埠號三者合起來。

我們的頁面網址是 `http://localhost:8000/ui/upload.html`，呼叫的 API 是 `http://localhost:8000/photos`——**同一個協定、同一個主機、同一個埠號**，這叫**同源**，瀏覽器根本不會把它當跨來源請求，所以完全不會有 CORS 問題。這也是為什麼 `fetch("/photos")` 只寫路徑、不寫完整網址：這種寫法自動沿用目前頁面的來源，永遠同源。

**因此不要安裝 `CORSMiddleware`**——沒有問題就不要加解法，那是過度設計。只有當你把 HTML 用別的伺服器（例如 `python -m http.server 3000`）另外開一個埠號提供時才會撞到 CORS；本 phase 刻意不那樣做。

**Q2：打開 `/ui/upload.html` 得到 404。**
三個常見原因：(a) `app/static/upload.html` 檔名打錯或放錯資料夾（必須是 `app/static/`，不是專案根目錄的 `static/`）；(b) `main.py` 忘了 `app.mount(...)`；(c) uvicorn 是在改檔案之前啟動的——`--reload` 通常會自動重啟，沒有的話按 `Ctrl + C` 再啟動一次。

**Q3：`RuntimeError: Directory 'app/static' does not exist`（啟動 uvicorn 時就爆）。**
資料夾沒建。執行 `mkdir -p /Users/linjunting/personalDocAI/app/static`。步驟 2 的程式碼用 `Path(__file__).resolve().parent / "static"` 算絕對路徑，所以只要資料夾存在，在哪裡啟動 uvicorn 都沒問題。

**Q4：直接用 Finder 雙擊 `upload.html` 打開，按上傳沒有反應。**
那樣打開的網址是 `file:///…/upload.html`，不是 `http://localhost:8000/…`。`fetch("/photos")` 會被解讀成 `file:///photos`，當然失敗。**一定要透過 uvicorn 用 `http://localhost:8000/ui/…` 開啟。**

**Q5：上傳大照片時頁面看起來當掉了。**
沒當掉，是本機模型在看圖，慢是正常的（design.md §14 的已知假設）。頁面已經把按鈕變成不能按並顯示「上傳中…」，等它就好。**不要**因此去加進度條或非同步佇列——已釐清的決策是同步處理。

**Q6：可不可以加照片預覽、拖放上傳、歷史紀錄、刪除按鈕？**
**不可以。** 前三個是過度設計（side project 原則）；「刪除按鈕」更嚴重——那是 design.md §3 明確不做的**第三個功能**，而且後端根本沒有那個端點。

**Q7：可不可以改用 React／Vue，或至少用一下 CDN 上的 CSS 框架？**
**不可以。** design.md §3 的 Non-Goals 明列「不用前端框架（React/Vue 等——網頁介面用純 HTML/JS 即可）」，§4.3 的 v4 決策記錄也寫「零前端框架、零打包工具」。而且引入 CDN 會讓專案多一個外部相依，違反「全本地執行」的精神。

**Q8：兩頁的 `<style>` 幾乎一樣，要不要抽成共用的 `style.css`？**
**不用。** 兩個檔案、十幾行 CSS，重複的成本比多一個檔案低。真的很在意的話也不是錯，但這不是本 phase 要求的事。

**Q9：要不要幫這兩頁寫自動化測試（例如 Playwright）？**
**不要。** design.md §6 明訂「頁面驗收以手動瀏覽器操作為準」。為兩個靜態頁面引入瀏覽器測試框架，是這個 side project 最典型的過度設計。

---

## 完成後的專案狀態

**專案完成。** 除了 Phase 13 完成的後端能力之外，現在多了一層可以用瀏覽器操作的極簡介面：

- `http://localhost:8000/ui/upload.html`：選檔 → 上傳 → 看到 AI 的理解結果（或 415／422 的錯誤訊息）。
- `http://localhost:8000/ui/ask.html`：打字提問（中文或英文）→ 看到回答、`search_mode` 與依據照片 id。
- 實作方式：`app/static/` 兩個純 HTML 檔（內含原生 JS）＋ `main.py` 一行 `app.mount("/ui", StaticFiles(...))`。**零框架、零打包工具、零新增端點、零新增測試**。
- 自動化測試維持 **49 passed** 且不依賴任何外部服務；12 條 Gherkin Rule 全綠；雙語行為有 7 個額外測試守著。
