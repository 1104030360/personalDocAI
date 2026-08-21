# Phase 26：美化 UI/UX（三頁共用一套設計 tokens，拒絕 AI 樣板臉）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

**目標：** 把 `upload.html`／`browse.html`／`ask.html`／`folder_modal.js` 從「能用但很醜」變成「有明確視覺個性、看得下去」——所有樣式收進**一支共用的 `app/static/style.css`**，三頁與彈窗共用同一套設計 tokens，頁內與 JS 裡不留任何舊樣式殘骸。**零框架、零打包、零新端點、零自動化測試變動。**

**這個 phase 最重要的一句話**：配色與版面**不准憑感覺決定**，也**不准長成 AI 預設的那張臉**。要先載入 design skill、先去看網路上真實的作品、歸納出具體參考點（附來源連結），再做決策。本文件寫死的是**決策程序**與**驗收標準**，不是配色本身。

---

## 前置條件

- 需要已完成的 phase：**Phase 25**（錯誤收尾與全量回歸完成，最終測試顆數已記在 Phase 25 的驗收清單與 `CLAUDE.md`）。
- 開工前基線（執行時實查並抄下來，這個數字**做完必須一模一樣**）：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  pytest -q | tail -1
  ```
  記下：`＿＿＿ passed`（＝ Phase 25 步驟 4 的最終顆數；2026-08-21 校準＝**149**，本 phase 做完必須仍是 149）。
- 環境（這個 phase 全程要用瀏覽器看畫面）：
  ```bash
  brew services start postgresql@17            # 資料庫
  pgrep -fl "ollama serve" || open -a Ollama   # 真模型（上傳流程要用）
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000    # 開著別關
  ```
- 正式庫裡最好已經有幾張**真的**照片（Phase 25 步驟 7 的煙霧測試已經留下一些），不然縮圖牆是空的、沒東西可以美化。

---

## 這個 phase 在做什麼

前面 12 個 phase 把功能做完了，但三個頁面還是 Phase 14 那個「白底、系統預設字型、`<pre>` 灰框」的樣子；Phase 23／24 加上去的彈窗與縮圖牆，樣式還是硬塞在 `folder_modal.js` 裡的一段字串。這個 phase 只做一件事：**讓它看起來像有人設計過，而且樣式只有一個家。**

範圍**只有五個檔案**：

```
app/static/style.css        ← 新增（全站唯一的樣式來源）
app/static/upload.html      ← <head> 加 link、頁首與結果區換結構、renderResult 改成畫卡片
app/static/browse.html      ← <head> 加 link、頁首換結構、刪頁內 <style>
app/static/ask.html         ← <head> 加 link、頁首與結果區換結構
app/static/folder_modal.js  ← 刪掉 FOLDER_MODAL_CSS 與注入樣式那幾行、加焦點管理與鎖捲動
```

**不會動到的東西**（動到就是做錯了）：任何 `.py`、任何測試、`requirements.txt`、資料庫、API 契約，以及 `folder_modal.js` 的 `fmAssign()`（`PATCH` 的呼叫、409／422 的處理）一個字都不准改。

**為什麼要特別強調「拒絕 AI 感」**：讓 AI 隨手做一個網頁，十次有八次會長成同一張臉——紫藍漸層背景、正中央一張大圓角卡片、`Inter` 字型、標題前面放一個 emoji、卡片加半透明模糊。這張臉的問題不是難看，是**沒有選擇**：它不是為這個專案做的決定，只是預設值。這個 phase 要求做出**有理由的選擇**，理由來自真實作品，而且理由要寫下來。

**名詞**：

- **design tokens（設計代幣／設計變數）**＝把「顏色、字級、間距、圓角」這些反覆用到的值，先取名字集中定義一次，之後所有地方都引用名字而不是寫死的數值。改一個地方，全站跟著變。
- **CSS 自訂屬性（CSS custom property）**＝CSS 內建的變數語法。定義寫成 `--名字: 值;`，使用寫成 `var(--名字)`。design tokens 在純 CSS 裡就是用它做的，**不需要任何打包工具**。
- **`:root`**＝CSS 選擇器，指整份文件的最外層（就是 `<html>`）。tokens 定義在這裡，全頁面都拿得到。
- **樣式權重（specificity，特異性）**＝當多條 CSS 規則都指到同一個元素時，瀏覽器用來決定「聽誰的」的計分規則。大致是：行內 `style=""` > `#id` > `.class` > 標籤名。**這個 phase 要求刪光頁內 `<style>` 與 JS 注入的樣式，就是為了不要出現「三套樣式互相打架、要靠權重才知道誰贏」的狀況。**
- **type scale（字級系統）**＝一組事先決定好的字級（例如 5 級），全站只准用這幾級，不准每次隨手打一個 `17px`。這是版面看起來「有秩序」最省力的做法。
- **色票（palette）**＝一組事先決定好的顏色，全站只准用這幾個。
- **玻璃擬態（glassmorphism）**＝把元素做成半透明＋背景模糊（`backdrop-filter: blur(...)`）的視覺風格。用得好很漂亮，用在「白底上的白卡片」就是純粹的裝飾噪音——本 phase 禁止無意義使用。
- **線框圖（wireframe）**＝只畫「有哪些東西、放在哪」的草圖，不管顏色與美感。
- **XSS（跨站腳本攻擊）**＝把別人給的文字直接當 HTML 塞進頁面，導致其中夾帶的程式碼被瀏覽器執行。本 phase 會用到 `innerHTML`，所以要搭配跳脫函式（見步驟 6）。
- **skill**＝Claude Code 裡一包預先寫好的作業指引。用 `Skill` 工具叫用（或在對話裡打 `/` 加名稱），叫用後它的指引會載入到這一輪的工作中。
- **MCP**＝Model Context Protocol，讓 Claude Code 連到外部工具（搜尋、瀏覽器自動化…）的機制。本 phase 用到 Exa／WebSearch／DeepWiki（查資料）與 Playwright（開瀏覽器截圖）。
- **`:focus-visible`**＝CSS 偽類，只有在「使用者是用鍵盤操作」時才套用的聚焦樣式。用它做鍵盤外框，滑鼠點按時不會出現多餘的框。
- **`:empty`**＝CSS 偽類，指「裡面完全沒有內容的元素」。用它讓空的錯誤訊息自動不佔位，就不必為此改任何 JS。
- **`color-scheme: light`**＝告訴瀏覽器「這頁只有淺色版」，這樣使用者的作業系統設成深色模式時，表單元件（下拉選單、輸入框）不會自己變黑而跟頁面打架。**這一行不是深色模式，是明確拒絕深色模式。**

---

## ASCII 圖 1：樣式從三個家搬回一個家

```
  ── 現在（Phase 24 結束時）：樣式散在三個地方 ─────────────────────

    upload.html            browse.html            ask.html
    ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
    │ <style>…</style>│    │ <style>…</style>│    │ <style>…</style>│  ← 各寫一份，
    └──────────────┘      └──────────────┘      └──────────────┘     幾乎一樣又不完全一樣
            │                     │                     │
            └────────┬────────────┴─────────────────────┘
                     ▼
            folder_modal.js
            ┌────────────────────────────────────┐
            │ const FOLDER_MODAL_CSS = `…`;      │  ← 第三份：彈窗樣式
            │ fmInstall() {                      │     用 JS 塞進 <head>
            │   style.textContent = FOLDER_MODAL_CSS;
            │   document.head.appendChild(style); │
            └────────────────────────────────────┘
      問題：改一個顏色要改四個地方；彈窗與頁面的圓角、線色永遠對不齊

  ── 本 phase 之後：一個家 ──────────────────────────────────────

                    app/static/style.css
        ┌───────────────────────────────────────────┐
        │ :root { design tokens }                   │  ← 唯一定義顏色/字級/間距的地方
        │   --c-bg --c-surface --c-border …         │
        │   --f-display --f-body --fs-page …        │
        │   --sp-1…--sp-6 --radius-m --shadow-modal │
        ├───────────────────────────────────────────┤
        │ 基礎  reset / body / a / :focus-visible   │
        │ 版面  .site-header .site-nav .page .lead  │
        │ 元件  .btn .btn-primary .field .field-row │
        │       .panel .status .kv .answer .note    │
        │ 瀏覽  #view .message .folders .folder     │
        │       .wall .photo .placeholder .caption  │
        │ 彈窗  .fm-backdrop .fm-box .fm-close      │
        │       .fm-option .fm-desc .fm-error       │
        └───────────────────────────────────────────┘
             ▲              ▲              ▲              ▲
   ┌─────────┴───┐  ┌───────┴─────┐  ┌─────┴──────┐  ┌────┴──────────┐
   │ upload.html │  │ browse.html │  │  ask.html  │  │folder_modal.js│
   │ <link rel=  │  │ <link rel=  │  │ <link rel= │  │ 只產生 class，│
   │ "stylesheet"│  │ "stylesheet"│  │"stylesheet"│  │ 不產生樣式    │
   │ href=       │  │ href=       │  │ href=      │  │ ✗ 沒有        │
   │"/ui/style.css"│ │"/ui/style.css"│ │"/ui/style.css"│ │ FOLDER_MODAL_CSS│
   │ ✗ 沒有<style>│ │ ✗ 沒有<style>│ │✗ 沒有<style>│ └───────────────┘
   └─────────────┘  └─────────────┘  └────────────┘

   規則：出現任何一行 <style>、style="…"、或 createElement("style")，
        這個 phase 就算沒做完。
```

## ASCII 圖 2：`upload.html` 美化前後的版面對比

```
  ── 美化前（Phase 23 的樣子）────────────────────────────────────

  ┌──────────────────────────────────────────────────┐
  │ PersonalDocAI                                    │  ← 瀏覽器預設 h1，超大
  │ 上傳照片  瀏覽資料夾  問問題                       │  ← 三個裸連結擠在一起，
  │ ──────────────────────────────────────────────── │     看不出現在在哪頁（<hr>）
  │ 上傳照片                                          │
  │ 選一張 JPEG 或 PNG…                               │
  │ [選擇檔案|未選擇檔案] [上傳]                        │  ← 系統預設按鈕，沒有主次
  │ ┌──────────────────────────────────────────────┐ │
  │ │ ✅ 上傳成功（HTTP 201）                        │ │  ← <pre> 灰底等寬字，
  │ │ 照片 id：1                                    │ │     七行純文字一整塊
  │ │ 文字描述：…                                   │ │
  │ │ 資料夾（category）：未分類                      │ │
  │ └──────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────┘
     問題：沒有層次、沒有留白節奏、資訊全是同一個大小、
           連結沒有「我在哪一頁」的提示、彈窗風格跟頁面對不上

  ── 美化後（本 phase 的目標版面）─────────────────────────────────

  ┌──────────────────────────────────────────────────┐
  │ PersonalDocAI        上傳照片 瀏覽資料夾 問問題    │ ← .site-header：品牌左、
  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │   導覽右，目前頁有底線
  │                                                  │   （aria-current="page"）
  │   上傳照片                                        │ ← .page：最大寬度＋左右留白
  │   選一張 JPEG 或 PNG。照片先放進「未分類」…         │ ← .lead：次級字色
  │                                                  │
  │   ┌────────────────────────────┐  ┌──────────┐   │
  │   │ 選擇檔案                    │  │  上傳    │   │ ← .field-row：.field ＋
  │   └────────────────────────────┘  └──────────┘   │   .btn.btn-primary（唯一主按鈕）
  │                                                  │
  │   ┌──────────────────────────────────────────┐   │
  │   │ ● 已上傳                                  │   │ ← .panel：卡片，有邊框無陰影
  │   │ ──────────────────────────────────────── │   │   狀態列 .status（圓點顏色
  │   │ 照片      #1                              │   │   代表成功/失敗）
  │   │ 文字描述  在 Target 購買可樂與洋芋片的收據  │   │ ← .kv：標籤小字＋值正常字，
  │   │ 資料夾    未分類                          │   │   兩欄對齊
  │   │ 地點      Target                          │   │
  │   │ 物品      可樂 · 洋芋片                    │   │
  │   │ 內容時間  2026-08-10                      │   │
  │   │ ──────────────────────────────────────── │   │
  │   │ AI 建議放進「收據」，請在視窗裡決定。        │   │ ← .note
  │   └──────────────────────────────────────────┘   │
  └──────────────────────────────────────────────────┘

  ── 同一套 tokens 套到彈窗與另外兩頁 ─────────────────────────────

   彈窗（folder_modal.js）        browse.html              ask.html
   ┌────────────────────┐   ┌──────┬──────┬──────┐   ┌──────────────────┐
   │ 這張照片要收哪裡？ ×│   │未分類│ 收據 │ 飲食 │   │[問題        ][送出]│
   │ ─────────────────  │   │ 3 張 │ 5 張 │ 0 張 │   ├──────────────────┤
   │ ① [ 採用「收據」 ]  │   └──────┴──────┴──────┘   │ 回答（大一級字）   │
   │    發票、消費憑證… │   .folders：等寬卡片        │ ───────────────  │
   │ ─────────────────  │   ┌────┬────┬────┬────┐   │ 檢索方式 metadata│
   │ ② [下拉 ▾][歸到這] │   │ img│ img│無縮│ img│   │ 依據照片 #1 #3    │
   │ ─────────────────  │   │    │    │ 圖 │    │   └──────────────────┘
   │ ③ [名稱][說明][建立]│  └────┴────┴────┴────┘
   └────────────────────┘   .wall：正方形格；沒縮圖
   同樣的線色/圓角/字級      的舊照片走 .placeholder
```

---

## 逐步驟操作

> ⚠️ 步驟 0〜3 **一步都不能跳**。跳過去直接改 CSS，做出來的就是本文件要禁止的那張臉。

### 步驟 0：先拍「美化前」的截圖（不先拍就沒有對比可驗收）

截圖放 `/tmp`，**不要放進 repo**（design1 §6：禁止把二進位丟進版控）：

```bash
mkdir -p /tmp/ui-before /tmp/ui-after
```

用 Playwright MCP，依序呼叫（工具名稱就是下面這些）：

1. `mcp__plugin_playwright_playwright__browser_resize`：`width=1280, height=800`（前後必須同尺寸，不然對比沒有意義）
2. `mcp__plugin_playwright_playwright__browser_navigate` → `http://localhost:8000/ui/upload.html`
3. `mcp__plugin_playwright_playwright__browser_take_screenshot` → `/tmp/ui-before/01-upload.png`
4. `mcp__plugin_playwright_playwright__browser_file_upload` 選一張真照片 → `browser_click` 上傳鈕 → 等彈窗出現 → 截圖 `/tmp/ui-before/02-modal.png`
5. 在彈窗選一個資料夾完成歸類 → 截圖 `/tmp/ui-before/03-result.png`
6. `browser_navigate` → `/ui/browse.html` → 截圖 `/tmp/ui-before/04-folders.png`；點一個有照片的資料夾 → 截圖 `/tmp/ui-before/05-photos.png`
7. `browser_navigate` → `/ui/ask.html`，問一句、等回答 → 截圖 `/tmp/ui-before/06-ask.png`

**六張「前」截圖到齊才可以往下做。**

### 步驟 1：載入 design skill（動手前必做，不可省略）

```
Skill(skill="frontend-design")
```

（若這個名稱在你的環境列不出來，改用 `frontend-design:frontend-design` 或 `example-skills:frontend-design`——三者指同一包指引。）

載入後**照它的指引走**：它會要求先確立一個明確的美學方向（不是「乾淨現代」這種沒有內容的形容詞），再談字型、字級、色彩與版面節奏。本 phase 的步驟 2〜4 就是把它的要求落到這個專案上。

> 為什麼一定要先載：這包指引存在的目的就是「不要做出預設值的東西」。先寫 CSS 再回頭載，等於先做完決定再假裝有流程。

### 步驟 2：查真實作品，歸納 2〜3 個具體參考點（必須列出來源連結）

依 `~/CLAUDE.md` 的 MCP 規則：研究類 MCP **只查、不改碼**，而且**每次用外部 MCP 得到的結論都要列出來源連結**。

要查的東西很具體：**開源的照片庫／檔案上傳介面長什麼樣**。建議這樣查（三種工具擇一或併用）：

```
mcp__exa__web_search_exa
  query: "open source self-hosted photo gallery web UI screenshots github"
  query: "photo library album grid UI open source project"
  query: "minimal file upload interface design open source"

WebSearch
  query: "immich web UI design"        query: "photoprism ui screenshots"
  query: "librephotos ui"              query: "filebrowser web ui"

mcp__deepwiki__ask_question
  repoName: "immich-app/immich"
  question: "How is the web UI laid out? Describe the album list and the photo grid: spacing, typography, and how counts are displayed."
  repoName: "photoprism/photoprism"
  question: "What does the album browsing UI look like and how are thumbnails laid out?"
```

**產出**：填滿下面這張表（**至少 2 列、最多 3 列**，多了就是過度設計）。這張表要貼進 commit 訊息與當輪的回覆裡。

| # | 來源（完整連結） | 我看到什麼（具體，不要寫「很好看」） | 我要借用的一件事 | 我刻意**不**借的 |
|---|---|---|---|---|
| 1 | ＿＿＿ | 例：相簿卡片名稱與張數分兩行，張數用次級字色的小字，卡片之間只靠 1px 線分隔、沒有陰影 | ＿＿＿ | ＿＿＿ |
| 2 | ＿＿＿ | ＿＿＿ | ＿＿＿ | ＿＿＿ |
| 3（可略） | ＿＿＿ | ＿＿＿ | ＿＿＿ | ＿＿＿ |

**「我看到什麼」的合格標準**：句子裡要有可以直接翻成 CSS 的東西——間距關係、對齊方式、字級對比、資訊分層、按鈕主次、縮圖比例。寫「乾淨簡潔有質感」＝不合格，重寫。

### 步驟 3：明文寫下「AI 樣板臉」禁止清單

把下面這張清單抄進 `style.css` 檔頭的註解（讓下一個改這支檔案的人也看得到），步驟 8 會用腳本自動檢查：

```
禁止清單（本專案的設計底線，違反任何一條就是沒做完）：
1. ✗ 紫／靛色漸層背景（#667eea→#764ba2 那一家族，以及任何 purple/violet/indigo 的漸層）
2. ✗ 「整頁置中一張大圓角卡片」當作主要版面
3. ✗ 標題前面掛 emoji（<h1>🚀 …</h1> 這種）
4. ✗ 直接用 Inter／預設 system-ui 字型堆疊當「設計」（要嘛明確選一套字型並說明理由，
     要嘛刻意挑一組有個性的系統字型組合，並在註解寫清楚為什麼）
5. ✗ 無意義的玻璃擬態（backdrop-filter: blur——白底上疊白卡片是在模糊什麼？）
6. ✗ 沒有理由的深色模式、動畫、漸層、陰影堆疊
```

**反過來要有的東西**：一套**明確、一致**的色票與字級系統，且每個選擇都能回答「為什麼是這個」——答案要引用步驟 2 的表格。

### 步驟 4：決定設計 tokens（這是本 phase 唯一的設計決策點）

把步驟 2 的參考點翻成下面這張 token 表的值。**每一格都要有值，且要能說出理由。**

| token | 用途 | 限制 |
|---|---|---|
| `--c-bg` | 頁面底色 | 不准是漸層 |
| `--c-surface` | 卡片／面板／彈窗底色 | 要與 `--c-bg` 分得出來（否則卡片邊界只能靠陰影，會糊） |
| `--c-surface-2` | 次級底色（占位塊、目前選取的卡片） | 同上 |
| `--c-border` | 所有邊框線 | 全站只准這一個線色 |
| `--c-text` | 主要文字 | 與 `--c-bg` 對比至少 7:1 |
| `--c-text-muted` | 次級文字（description、標籤、張數） | 與 `--c-bg` 對比至少 4.5:1 |
| `--c-accent` | 強調色：主要按鈕、目前頁指示、連結 | **一個就好**；不准是紫靛漸層；要能說出為什麼是這個色 |
| `--c-accent-text` | 疊在 `--c-accent` 上的文字色 | 對比至少 4.5:1 |
| `--c-ok` / `--c-danger` | 成功／失敗狀態 | 只用在狀態指示，不當裝飾色 |
| `--f-display` | 標題字型堆疊 | 必須寫理由；不准只寫 `Inter, sans-serif` 交差 |
| `--f-body` | 內文字型堆疊 | 必須含中文 fallback（例如 `"PingFang TC"`、`"Noto Sans TC"`） |
| `--f-mono` | 等寬字型 | 給照片 id、`search_mode` 之類的技術值用 |
| `--fs-page` / `--fs-section` / `--fs-card` / `--fs-body` / `--fs-small` | 五級字級 | 全站只准這五級；相鄰級距要看得出來 |
| `--sp-1`〜`--sp-6` | 六級間距 | 全站只准這六級；不准出現 `margin: 13px` |
| `--radius-s` / `--radius-m` | 圓角 | 兩級就夠 |
| `--bw` | 邊框寬度 | 一個值 |
| `--shadow-modal` | **只有彈窗**用的陰影 | 全站只有彈窗可以有陰影（卡片用邊框） |
| `--page-max` | 內容最大寬度 | 桌機優先 |
| `--thumb-min` | 縮圖牆單格最小寬度 | grid 自動換行用 |
| `--motion` | 轉場時間 | 一個值，建議 ≤ 0.15s；不做花俏動畫 |

> 🚫 **不做**：深色模式、RWD 完美適配（桌機優先、手機不破版即可）、字型 CDN、圖示字型、動畫函式庫。

### 步驟 5：建立 `app/static/style.css`

**5a. 先確認實際的 class／id 名稱**（Phase 23／24 已經落地，本 phase 配合既有 HTML，不是反過來）：

```bash
cd /Users/linjunting/personalDocAI
grep -ohE 'class="[^"]*"|id="[^"]*"' app/static/*.html app/static/folder_modal.js | sort -u
grep -ohE 'el\("[a-z]+", "[a-z-]+"' app/static/browse.html | sort -u
```

下面的 CSS 是照 Phase 23／24 計畫落地的名稱寫的，預期會看到：

- 三頁共通：`#upload-form`／`#ask-form`、`#file-input`、`#question-input`、`#submit-button`、`#result`
- 瀏覽頁：`#view`、`.folders`、`.folder`、`.folder-name`、`.folder-desc`、`.wall`、`.photo`、`.placeholder`、`.caption`、`.message`
- 彈窗：`#fm-backdrop`／`.fm-backdrop`、`.fm-box`、`#fm-title`、`#fm-close`／`.fm-close`、`.fm-option`、`#fm-primary`、`#fm-primary-desc`、`#fm-select`、`#fm-select-submit`、`#fm-name`、`#fm-desc-input`、`#fm-create`、`.fm-desc`、`#fm-error`／`.fm-error`

**有對不上的名稱時**：改 CSS 的選擇器去配合既有 HTML（首選），或把 HTML 的 class 改成 CSS 的名稱。**二選一，不要兩邊都留一套**，並在 commit 訊息記一句你選了哪一種。**絕對不要為了配合樣式去改 JS 的資料流**（`fetch`、`PATCH`、錯誤處理一行都不准動）。

**5b. 寫檔**。整份照抄；`:root` 區塊的值換成步驟 4 的決策（附的是**中性起始值，只是為了讓檔案任何時候都是合法可跑的 CSS**——驗收清單有一條專門檢查它已被你的決策覆蓋）：

```css
/* PersonalDocAI 三頁共用樣式（Phase 26）。
   upload.html / browse.html / ask.html / folder_modal.js 全部只吃這一支檔案。

   規則：
   - 顏色、字級、間距一律走 :root 的 token；tokens 區以外不准再出現寫死的色碼。
   - 頁面內不准有 <style>，JS 不准注入樣式、不准產生 style=""。
   - 桌機優先；不做深色模式（下面的 color-scheme: light 就是明確拒絕）。

   禁止清單（本專案的設計底線，違反任何一條就是沒做完）：
   1. ✗ 紫／靛色漸層背景（#667eea→#764ba2 那一家族，以及任何 purple/violet/indigo 漸層）
   2. ✗ 「整頁置中一張大圓角卡片」當作主要版面
   3. ✗ 標題前面掛 emoji
   4. ✗ 直接拿 Inter／預設 system-ui 堆疊當「設計」
   5. ✗ 無意義的玻璃擬態（backdrop-filter: blur）
   6. ✗ 沒有理由的深色模式、動畫、漸層、陰影堆疊

   設計依據（Phase 26 步驟 2 歸納的參考點）：
   - 參考 1：<填入完整連結> — <借用的具體做法>
   - 參考 2：<填入完整連結> — <借用的具體做法>
   色票與字型的選擇理由：<填入一兩句，說明為什麼是這組，而不是別組>
*/

/* ══ design tokens ══════════════════════════════════════════════════
   ↓↓↓ 這一區的值必須由步驟 4 的決策覆蓋，理由寫在上面的註解 ↓↓↓ */
:root {
  color-scheme: light;              /* 明確只有淺色版：表單元件不會被 OS 深色模式弄黑 */

  /* 色票 */
  --c-bg: #ffffff;
  --c-surface: #ffffff;
  --c-surface-2: #f2f2f0;
  --c-border: #d8d8d4;
  --c-text: #1b1b19;
  --c-text-muted: #6b6b66;
  --c-accent: #1b1b19;
  --c-accent-text: #ffffff;
  --c-ok: #2f6b3a;
  --c-danger: #9b2c2c;

  /* 字型 */
  --f-display: Georgia, "Songti TC", "Noto Serif TC", serif;
  --f-body: -apple-system, "PingFang TC", "Noto Sans TC", sans-serif;
  --f-mono: ui-monospace, "SF Mono", Menlo, monospace;

  /* 字級（五級，全站只准用這五個） */
  --fs-page: 1.75rem;
  --fs-section: 1.25rem;
  --fs-card: 1rem;
  --fs-body: 0.95rem;
  --fs-small: 0.8rem;

  /* 間距（六級，全站只准用這六個） */
  --sp-1: 0.25rem;
  --sp-2: 0.5rem;
  --sp-3: 0.75rem;
  --sp-4: 1.25rem;
  --sp-5: 2rem;
  --sp-6: 3rem;

  /* 形狀與動態 */
  --radius-s: 3px;
  --radius-m: 6px;
  --bw: 1px;
  --shadow-modal: 0 10px 40px rgba(0, 0, 0, 0.18);
  --motion: 0.12s;

  /* 版面 */
  --page-max: 62rem;
  --thumb-min: 9rem;
}
/* ↑↑↑ tokens 結束：以下規則一律只引用 var(--…)，不准寫死值 ↑↑↑ */


/* ══ 基礎 ═══════════════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; }

html { -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  background: var(--c-bg);
  color: var(--c-text);
  font-family: var(--f-body);
  font-size: var(--fs-body);
  line-height: 1.6;
}

a { color: var(--c-accent); }
a:hover { text-decoration: none; }

img { max-width: 100%; display: block; }

/* 鍵盤操作時才出現的聚焦外框。滑鼠點按不會有多餘的框，
   但用 Tab 走的人一定看得到自己在哪裡——不准用 outline: none 拿掉。 */
:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
  border-radius: var(--radius-s);
}


/* ══ 版面：頁首與內容區 ═════════════════════════════════════════════ */
.site-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
  max-width: var(--page-max);
  margin: 0 auto;
  padding: var(--sp-4) var(--sp-4) var(--sp-3);
  border-bottom: var(--bw) solid var(--c-border);
}

.site-brand {
  margin: 0;
  font-family: var(--f-display);
  font-size: var(--fs-section);
  font-weight: 600;
  letter-spacing: 0.01em;
}

.site-nav { display: flex; gap: var(--sp-4); }

.site-nav a {
  color: var(--c-text-muted);
  text-decoration: none;
  padding-bottom: var(--sp-1);
  border-bottom: 2px solid transparent;
  transition: color var(--motion) ease, border-color var(--motion) ease;
}
.site-nav a:hover { color: var(--c-text); }

/* 目前所在的頁：HTML 要寫 aria-current="page"（螢幕報讀軟體也讀得到） */
.site-nav a[aria-current="page"] {
  color: var(--c-text);
  border-bottom-color: var(--c-accent);
}

.page {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: var(--sp-5) var(--sp-4) var(--sp-6);
}

.page > h2 {
  margin: 0 0 var(--sp-2);
  font-family: var(--f-display);
  font-size: var(--fs-page);
  font-weight: 600;
  line-height: 1.25;
}

.lead {
  margin: 0 0 var(--sp-5);
  max-width: 46em;                 /* 一行別太長，比較好讀 */
  color: var(--c-text-muted);
}


/* ══ 表單與按鈕 ═════════════════════════════════════════════════════ */
.field-row {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
  margin: 0 0 var(--sp-5);
}

.field,
.fm-option input[type="text"],
.fm-option select {
  flex: 1 1 16rem;
  min-width: 0;
  font: inherit;
  color: var(--c-text);
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-s);
  padding: var(--sp-2) var(--sp-3);
}

.field::placeholder,
.fm-option input[type="text"]::placeholder { color: var(--c-text-muted); }

input[type="file"].field { padding: var(--sp-2); }

.btn,
.fm-option button,
.fm-close {
  font: inherit;
  font-size: var(--fs-body);
  cursor: pointer;
  padding: var(--sp-2) var(--sp-4);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-s);
  background: var(--c-surface);
  color: var(--c-text);
  transition: background var(--motion) ease, border-color var(--motion) ease,
              opacity var(--motion) ease;
}
.btn:hover:not(:disabled),
.fm-option button:hover:not(:disabled) { border-color: var(--c-text); }

.btn:disabled,
.fm-option button:disabled { opacity: 0.5; cursor: progress; }

/* 每一頁（每一個彈窗）只准有一個主要按鈕——主要動作只有一個 */
.btn-primary,
#fm-primary {
  background: var(--c-accent);
  border-color: var(--c-accent);
  color: var(--c-accent-text);
}
.btn-primary:hover:not(:disabled),
#fm-primary:hover:not(:disabled) { opacity: 0.88; }


/* ══ 結果面板（上傳頁與問答頁共用同一張卡片語言）═══════════════════ */
.panel {
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-m);
  background: var(--c-surface);
  padding: var(--sp-4);
}

.panel-empty { margin: 0; color: var(--c-text-muted); }

.status {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-3);
  padding-bottom: var(--sp-3);
  font-size: var(--fs-small);
  letter-spacing: 0.04em;
  color: var(--c-text-muted);
  border-bottom: var(--bw) solid var(--c-border);
}
.status::before {
  content: "";
  width: 0.5em; height: 0.5em;
  border-radius: 50%;
  background: var(--c-text-muted);
}
.status-ok::before { background: var(--c-ok); }
.status-error { color: var(--c-danger); }
.status-error::before { background: var(--c-danger); }

/* 標籤＋值的兩欄清單：上傳結果的四欄 metadata、問答結果的檢索資訊都用它 */
.kv {
  display: grid;
  grid-template-columns: 6.5em 1fr;
  gap: var(--sp-2) var(--sp-4);
  margin: 0;
}
.kv dt {
  padding-top: 0.2em;
  font-size: var(--fs-small);
  color: var(--c-text-muted);
}
.kv dd { margin: 0; overflow-wrap: anywhere; }
.kv dd.mono { font-family: var(--f-mono); font-size: var(--fs-small); }

/* AI 的回答：比內文大一級，讓它是問答頁的主角 */
.answer {
  margin: 0 0 var(--sp-4);
  font-size: var(--fs-section);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* 結果卡片底部的補充說明（「AI 建議放進…」「已放進未分類…」） */
.note {
  margin: var(--sp-3) 0 0;
  padding-top: var(--sp-3);
  font-size: var(--fs-small);
  color: var(--c-text-muted);
  border-top: var(--bw) solid var(--c-border);
}


/* ══ 瀏覽頁 ═════════════════════════════════════════════════════════ */
#view { min-height: 12rem; }

.message { margin: 0 0 var(--sp-4); color: var(--c-text-muted); }

.back-link {
  display: inline-block;
  margin-bottom: var(--sp-4);
  color: var(--c-text-muted);
  text-decoration: none;
}
.back-link:hover { color: var(--c-text); }

/* 資料夾卡片 */
.folders {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: var(--sp-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.folder {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  height: 100%;
  padding: var(--sp-4);
  text-decoration: none;
  color: inherit;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-m);
  transition: border-color var(--motion) ease, background var(--motion) ease;
}
.folder:hover { border-color: var(--c-text); background: var(--c-surface-2); }

.folder-name {
  font-family: var(--f-display);
  font-size: var(--fs-card);
  font-weight: 600;
}
.folder-desc {
  margin: 0;
  font-size: var(--fs-small);
  color: var(--c-text-muted);
}

/* 縮圖牆 */
.wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--thumb-min), 1fr));
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.photo {
  display: block;
  width: 100%;
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-s);
  transition: border-color var(--motion) ease;
}
.photo:hover { border-color: var(--c-text); }

.photo img,
.placeholder {
  aspect-ratio: 1 / 1;             /* 正方形格子，長短邊照片排在一起也整齊 */
  width: 100%;
}

.photo img { object-fit: cover; }  /* 填滿方格、不變形（超出的裁掉） */

/* 舊照片沒有縮圖（design1 §10）：灰底占位，不假裝有圖、也不顯示破圖 */
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-small);
  color: var(--c-text-muted);
  background: var(--c-surface-2);
}

/* 縮圖下方的一行文字說明 */
.caption {
  padding: var(--sp-2);
  font-size: var(--fs-small);
  line-height: 1.4;
  color: var(--c-text-muted);
  text-align: left;
  border-top: var(--bw) solid var(--c-border);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;           /* 最多兩行，超過用「…」收掉 */
  -webkit-box-orient: vertical;
}


/* ══ 歸類彈窗（folder_modal.js）═══════════════════════════════════════ */
.fm-backdrop {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
  background: rgba(0, 0, 0, 0.45);
}
.fm-backdrop[hidden] { display: none; }   /* JS 用 hidden 開關，這行讓它真的藏起來 */

.fm-box {
  position: relative;
  width: min(34rem, 100%);
  max-height: 90vh;
  overflow-y: auto;
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
  background: var(--c-surface);
  border: var(--bw) solid var(--c-border);
  border-radius: var(--radius-m);
  box-shadow: var(--shadow-modal);        /* 全站唯一用陰影的地方 */
}

#fm-title {
  margin: 0 var(--sp-6) var(--sp-4) 0;
  font-family: var(--f-display);
  font-size: var(--fs-section);
  font-weight: 600;
}

.fm-close {
  position: absolute;
  top: var(--sp-3);
  right: var(--sp-3);
  padding: var(--sp-1) var(--sp-2);
  line-height: 1;
  color: var(--c-text-muted);
  background: none;
  border: none;
}
.fm-close:hover { color: var(--c-text); }

/* 三個選項之間用分隔線隔開，讓「這是三條不同的路」一眼看得出來 */
.fm-option {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-4) 0;
  border-top: var(--bw) solid var(--c-border);
}
.fm-option:first-of-type { padding-top: 0; border-top: none; }

.fm-option label {
  flex: 1 0 100%;
  font-size: var(--fs-small);
  letter-spacing: 0.04em;
  color: var(--c-text-muted);
}
.fm-option br { display: none; }          /* 換行改由上面的 flex 版面負責 */

.fm-desc {
  flex: 1 0 100%;
  margin: 0;
  font-size: var(--fs-small);
  color: var(--c-text-muted);
}

.fm-error {
  margin: var(--sp-3) 0 0;
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-small);
  color: var(--c-danger);
  border: var(--bw) solid var(--c-danger);
  border-radius: var(--radius-s);
}
/* 錯誤訊息被清空時自動不佔位——這樣就不必為了樣式去改任何 JS */
.fm-error:empty { display: none; }

/* 彈窗開啟時鎖住背景捲動（JS 會在 <body> 加上這個 class）*/
body.fm-open { overflow: hidden; }


/* ══ 手機不破版就好（不做完美適配）═══════════════════════════════════ */
@media (max-width: 32rem) {
  .site-header { flex-direction: column; align-items: flex-start; gap: var(--sp-2); }
  .site-nav { gap: var(--sp-3); }
  .kv { grid-template-columns: 1fr; gap: var(--sp-1) 0; }
  .kv dt { padding-top: var(--sp-2); }
}
```

**5c. 一致性自檢**（貼進終端機跑）：

```bash
cd /Users/linjunting/personalDocAI

echo "== 每個 var(--x) 都要有定義，且沒有多餘的 token =="
python - <<'PY'
import pathlib, re
css = pathlib.Path("app/static/style.css").read_text(encoding="utf-8")
定義 = set(re.findall(r"^\s*(--[\w-]+)\s*:", css, re.M))
使用 = set(re.findall(r"var\((--[\w-]+)\)", css))
缺 = sorted(使用 - 定義)
print("違規：沒有定義的 token →", 缺) if 缺 else print("OK：所有 token 都有定義")
未用 = sorted(定義 - 使用)
print("提醒：定義了卻沒用到的 token →", 未用) if 未用 else print("OK：沒有多餘的 token")
PY

echo "== tokens 區以外不准出現寫死的色碼 =="
python - <<'PY'
import pathlib, re
行 = pathlib.Path("app/static/style.css").read_text(encoding="utf-8").splitlines()
try:
    起 = next(i for i, l in enumerate(行) if "tokens 結束" in l)
except StopIteration:
    raise SystemExit("違規：找不到「tokens 結束」那行註解，無法界定 tokens 區")
壞 = [(i + 1, l.strip()) for i, l in enumerate(行[起:], start=起)
      if re.search(r"#[0-9a-fA-F]{3,8}\b", l) and not l.strip().startswith(("/*", "*"))]
for n, l in 壞:
    print(f"違規：第 {n} 行寫死色碼 → {l}")
print("OK：tokens 區以外沒有寫死的色碼" if not 壞 else "↑ 請改用 var(--…)")
PY
```

> 💡 上面 CSS 裡的 `rgba(0, 0, 0, 0.45)`（彈窗背後的暗色遮罩）刻意不做成 token：它是唯一一個「半透明黑」，做成 token 反而多一層間接。腳本只抓 `#色碼`，所以不會誤判。

### 步驟 6：三頁改成引用 `style.css`，並刪光頁內 `<style>`

**6a. 三頁的 `<head>` 統一改成**（`<title>` 沿用各頁原本的，不要改字）：

```html
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>上傳照片 — PersonalDocAI</title>
<link rel="stylesheet" href="/ui/style.css">
</head>
```

**原本的整段 `<style>…</style>` 直接刪掉**，不要留註解版、不要留「以後可能用到」的部分。

**6b. 三頁的頁首統一改成**（連結文字沿用 Phase 24 定的三個，不要改字；`aria-current="page"` 只標在目前這一頁）：

```html
<header class="site-header">
  <h1 class="site-brand">PersonalDocAI</h1>
  <nav class="site-nav" aria-label="主要導覽">
    <a href="/ui/upload.html" aria-current="page">上傳照片</a>
    <a href="/ui/browse.html">瀏覽資料夾</a>
    <a href="/ui/ask.html">問問題</a>
  </nav>
</header>
```

原本 `<h1>` 與 `<nav>` 之間的 `<hr>` **刪掉**——分隔線改由 `.site-header` 的下邊框負責。

**6c. 三頁的內容區統一包起來**：從 `<h2>` 到頁面最後一個內容元素（含 `#result` 或 `#view`）之間，包一層 `<main class="page">…</main>`；第一段說明文字的標籤加上 `class="lead"`。

**6d. 表單元素加 class**（只加 class，不改 id、不改 JS）：

- `upload.html`：`<form id="upload-form" class="field-row">`、`<input type="file" id="file-input" class="field" …>`、`<button type="submit" id="submit-button" class="btn btn-primary">`
- `ask.html`：`<form id="ask-form" class="field-row">`、`<input type="text" id="question-input" class="field" …>`、`<button type="submit" id="submit-button" class="btn btn-primary">`

**6e. 結果區從 `<pre>` 換成 `.panel`**（`upload.html` 與 `ask.html` 各一處）：

```html
<section class="panel" id="result" aria-live="polite">
  <p class="panel-empty">尚未上傳任何照片。</p>
</section>
```

（`ask.html` 的空狀態文字改成「尚未提問。」）
`aria-live="polite"`＝內容更新時螢幕報讀軟體會念出來，且不打斷使用者。

> ⚠️ **換成 `<section>` 之後，原本靠 `\n` 換行的寫法就沒用了**（`<pre>` 才會保留換行）。所以下面 6f 必須一起做，不能只換標籤。

**6f. 把「組一大串文字」改成「畫一張卡片」**。三頁都先加這個小工具（放在各頁 `<script>` 最上面）：

```javascript
// 把使用者／AI 產生的文字安全地放進 HTML。
// 不做這件事的話，照片描述裡的一個 "<" 就會把版面弄壞，
// 更糟的情況是其中夾帶的內容被瀏覽器當成程式碼執行（XSS）。
function esc(value) {
  const 文字 = (value === null || value === undefined || value === "") ? "（無）" : value;
  return String(文字)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
```

`upload.html`：**只動「畫結果」的程式碼**——`renderResult` 這個函式與下面那四行非成功狀態（Phase 23 已經把「畫結果」集中在 `renderResult`，所以歸類成功後改資料夾名稱的行為完全不受影響）：

```javascript
// 把上傳結果畫成一張卡片。歸類成功後資料夾名稱會變，所以獨立成一個參數。
// 提醒：資料夾名稱就是 category（design1.md §4），不是兩個東西。
function renderResult(body, folderName, note) {
  const m = body.metadata;
  const items = (m.items && m.items.length > 0) ? m.items.join(" · ") : "";
  result.innerHTML =
    '<p class="status status-ok">已上傳</p>' +
    '<dl class="kv">' +
      '<dt>照片</dt><dd class="mono">#' + esc(body.id) + '</dd>' +
      '<dt>文字描述</dt><dd>' + esc(body.text) + '</dd>' +
      '<dt>資料夾</dt><dd>' + esc(folderName) + '</dd>' +
      '<dt>地點</dt><dd>' + esc(m.location) + '</dd>' +
      '<dt>物品</dt><dd>' + esc(items) + '</dd>' +
      '<dt>內容時間</dt><dd>' + esc(m.content_time) + '</dd>' +
    '</dl>' +
    '<p class="note">' + esc(note) + '</p>';
}
```

同檔的四處「非成功狀態」也一起改（原本是 `result.textContent = "…"`）：

```javascript
// 還沒選檔案 / 上傳中：一行提示就夠
function renderNotice(message) {
  result.innerHTML = '<p class="panel-empty">' + esc(message) + '</p>';
}

// 415 / 422 / 500 / 連不上伺服器。label 是狀態列那行字，detail 是底下的細節。
function renderError(label, detail) {
  const 說明 = (typeof detail === "string") ? detail : JSON.stringify(detail);
  result.innerHTML =
    '<p class="status status-error">' + esc(label) + '</p>' +
    '<p>' + esc(說明) + '</p>';
}
```

`upload.html` 有**四行**非成功的 `result.textContent = …`（提示、上傳中、HTTP 錯誤、連不上伺服器），分別換成：

| 原本 | 換成 |
|---|---|
| `result.textContent = "請先選一個檔案。";` | `renderNotice("請先選一個檔案。");` |
| `result.textContent = "上傳中…（…）";` | `renderNotice("上傳中…（本機模型看圖可能要等 10〜60 秒，請耐心等候）");` |
| `result.textContent = "❌ 失敗（HTTP " + response.status + "）\n" + detail;` | `renderError("失敗（HTTP " + response.status + "）", detail);` |
| `catch` 裡的 `result.textContent = "❌ 請求失敗：" + error + …;` | `renderError("請求失敗", error + "。最常見原因：uvicorn 沒在跑，或網址、埠號不對。");` |

順手刪掉不再被任何人呼叫的 `orNone()`——空值顯示「（無）」的行為已由 `esc()` 接手。**`fetch` 那幾行、`openFolderModal({...})` 那一整段、兩個 callback 一個字都不准動。**

`ask.html` 的成功路徑同理：

```javascript
function renderAnswer(body) {
  const ids = (body.retrieved_photo_ids.length > 0)
    ? body.retrieved_photo_ids.map(function (id) { return "#" + id; }).join(" ")
    : "（沒有找到相關照片）";
  result.innerHTML =
    '<p class="answer">' + esc(body.answer) + '</p>' +
    '<dl class="kv">' +
      '<dt>檢索方式</dt><dd class="mono">' + esc(body.search_mode) + '</dd>' +
      '<dt>依據照片</dt><dd class="mono">' + esc(ids) + '</dd>' +
    '</dl>';
}
```

`ask.html` 一樣有四行非成功的 `result.textContent`，比照上面那張表換掉：「請先輸入問題。」與「思考中…（本機模型要判斷查法再產生回答，可能要等一下）」走 `renderNotice(…)`；HTTP 錯誤走 `renderError("失敗（HTTP " + response.status + "）", detail)`；`catch` 走 `renderError("請求失敗", error + "。最常見原因：uvicorn 沒在跑，或網址、埠號不對。")`。（`renderNotice`／`renderError` 兩個小函式照上面的定義複製一份進 `ask.html`；`browse.html` 用 `el()`＋`textContent`，完全用不到它們，不要加。）

> ⚠️ **`esc()` 不是可選的**，兩條硬規則：
> 1. **不准把未經 `esc()` 的值放進 `innerHTML` 字串**——包含照片 `text`、資料夾 `name`／`description`、AI 的 `answer`、後端回的 `detail`。
> 2. **不准把動態值放進 HTML 屬性位置**（例如 `'<img src="' + url + '">'`）。屬性一律用程式設定：先組好結構，再 `el.querySelector(...).src = url`。`esc()` 只擋元素內容，擋不住屬性跳脫。
>
> 純文字的地方（彈窗的錯誤訊息、`browse.html` 用 `el()` 建的節點）繼續用 `textContent` 就好——**那本來就安全，不需要 `esc()`，也不要改成 `innerHTML`**。本專案零外部相依，不引入 DOMPurify 之類的函式庫；上面兩條就足夠。

**6g. `browse.html` 只有兩處要動**（它的節點是用 `el()` 建的，`textContent` 天然安全，不需要 `esc()`）：

1. 回上一層的連結加一個 class 好套樣式：`el("a", null, "← 回資料夾列表")` → `el("a", "back-link", "← 回資料夾列表")`。
2. 頁內 `<style>` 刪掉、`<head>` 加 `<link>`、頁首與 `<main class="page">` 照 6a〜6c 改。

其餘（`.folders`／`.folder`／`.wall`／`.photo`／`.placeholder`／`.caption`／`.message` 這些 class 名稱、`getJson`、`showFolderList`、`showFolderPhotos`、`openFolderModal` 的呼叫）**一律不動**——`style.css` 已經照這些名稱寫好了。

### 步驟 7：`folder_modal.js`——把樣式搬走，再補四件互動小事

**7a. 刪掉 JS 裡的樣式（本 phase 的重點之一）**：

1. 刪掉整個 `const FOLDER_MODAL_CSS = \`…\`;`（連同那一大段 CSS 字串）。
2. 在 `fmInstall()` 裡刪掉這三行：
   ```javascript
   const style = document.createElement("style");
   style.textContent = FOLDER_MODAL_CSS;
   document.head.appendChild(style);
   ```
3. 原本那段 CSS 想達成的效果，已經由 `style.css` 的「歸類彈窗」區塊接手（`.fm-backdrop`／`.fm-box`／`.fm-close`／`.fm-option`／`.fm-desc`／`.fm-error` 全部涵蓋）。**不要在 JS 裡留任何備份或註解掉的版本。**

**7b. 補四件互動小事**（`fmAssign()`、`fmDetailText()`、`fmSetError()`、`fmSetBusy()` 一個字都不准動）：

```javascript
// ① 記住是誰打開彈窗的，關掉時把鍵盤焦點還回去
let fmLastFocus = null;

// ② 開啟後：鎖住背景捲動、把焦點移進彈窗（Tab 才不會跑到後面的頁面去）
function fmAfterOpen() {
  fmLastFocus = document.activeElement;
  document.body.classList.add("fm-open");
  const 第一個可聚焦 = fmEl("fm-backdrop").querySelector("button, input, select");
  if (第一個可聚焦) { 第一個可聚焦.focus(); }
}

// ③ 關閉後：解除鎖定、焦點還回原本的按鈕
function fmAfterClose() {
  document.body.classList.remove("fm-open");
  if (fmLastFocus && fmLastFocus.focus) { fmLastFocus.focus(); }
  fmLastFocus = null;
}
```

接線方式（三個插入點，各一行）：

- `fmHide()` 的**最後**加一行 `fmAfterClose();`（`fmHide` 是所有關閉路徑的共同出口——按 ×、按 Esc、PATCH 成功都會經過它，所以只要接這裡就全涵蓋）。
- `openFolderModal(config)` 的**最後**加一行 `fmAfterOpen();`。
- `fmInstall()` 裡（既有的 Esc 監聽旁邊）加上「點暗色區域＝關閉」：

```javascript
  // 點彈窗外面的暗色區域＝關閉，等同按 ×（一樣不呼叫 PATCH）
  fmEl("fm-backdrop").addEventListener("click", function (event) {
    if (event.target === fmEl("fm-backdrop")) { fmClose(); }
  });
```

**7c. 錯誤訊息不必動 JS**：`fmSetError("")` 會把 `#fm-error` 清成空字串，`style.css` 的 `.fm-error:empty { display: none; }` 會自動讓它不佔位。**不要**為了樣式去改 `fmSetError`。

**禁止**：`alert()`／`confirm()`（Phase 23 就禁了）、彈窗進出場動畫、拖曳、任何新的 `fetch`。

### 步驟 8：底線自檢腳本（一次驗完所有底線）

```bash
cd /Users/linjunting/personalDocAI

echo "== ① 不准有頁內樣式或 JS 注入樣式 =="
grep -nE "<style|style=\"|createElement\(\"style\"\)|FOLDER_MODAL_CSS|\.style\." \
  app/static/*.html app/static/folder_modal.js || echo "OK：樣式只有 style.css 一個家"

echo "== ② 三頁都要引用 style.css =="
grep -c 'href="/ui/style.css"' app/static/upload.html app/static/browse.html app/static/ask.html

echo "== ③ 禁止清單：漸層與紫靛色 =="
grep -rniE "linear-gradient|radial-gradient|purple|violet|indigo|667eea|764ba2|#8b5cf6|#a855f7" \
  app/static/ || echo "OK：沒有漸層、沒有紫靛色"

echo "== ③ 禁止清單：玻璃擬態 =="
grep -rn "backdrop-filter" app/static/ || echo "OK：沒有玻璃擬態"

echo "== ③ 禁止清單：拿 Inter 交差 =="
grep -rn "Inter" app/static/ || echo "OK：沒有用 Inter 交差"

echo "== ③ 禁止清單：標題掛 emoji =="
python - <<'PY'
import pathlib, re
emoji = re.compile(r"[\U0001F300-\U0001FAFF←-⇿☀-➿⬀-⯿]")
壞 = []
for p in sorted(pathlib.Path("app/static").glob("*.html")):
    文字 = p.read_text(encoding="utf-8")
    for 標籤 in ("h1", "h2", "h3"):
        for m in re.finditer(rf"<{標籤}[^>]*>(.*?)</{標籤}>", 文字, re.S):
            if emoji.search(m.group(1)):
                壞.append(f"{p.name} 的 <{標籤}>：{m.group(1).strip()}")
for 行 in 壞:
    print("違規：標題含 emoji →", 行)
print("OK：標題沒有 emoji" if not 壞 else "↑ 請拿掉")
PY

echo "== ④ 不做深色模式 =="
grep -rn "prefers-color-scheme" app/static/ || echo "OK：沒有深色模式"
grep -n "color-scheme: light" app/static/style.css

echo "== ⑤ 零框架、零打包、零外部資源 =="
ls package.json node_modules 2>/dev/null || echo "OK：沒有 npm、沒有打包工具"
grep -rniE "cdn|unpkg|jsdelivr|googleapis|react|vue|jquery|tailwind|bootstrap|@import url" \
  app/static/ || echo "OK：沒有任何外部前端資源"

echo "== ⑤ 零新端點（本增量最終仍是 9 個）=="
grep -rcE "@router\.(get|post|put|patch|delete)" app/api/routers/*.py
grep -cE "@app\.(get|post|put|patch|delete)" app/main.py

echo "== ⑤ 零 Python／測試／相依變動 =="
git status --porcelain -- app/api app/core app/db app/repositories app/schemas app/services \
  app/main.py app/dependencies.py tests/ requirements.txt db/ \
  || true

echo "== ⑥ 主要按鈕每頁只有一個 =="
grep -c "btn-primary" app/static/upload.html app/static/ask.html

echo "== ⑦ 沒有人用 outline: none 拿掉鍵盤外框 =="
grep -rnE "outline: *none|outline: *0" app/static/ || echo "OK：鍵盤外框沒有被拿掉"

echo "== ⑧ innerHTML 一律配 esc() =="
grep -n -A 8 "innerHTML" app/static/*.html app/static/folder_modal.js
```

**逐項預期**：

| 檢查 | 預期輸出 |
|---|---|
| ① 頁內／JS 樣式 | `OK：樣式只有 style.css 一個家` |
| ② 引用 style.css | 三行都是 `1` |
| ③ 漸層／紫靛 | `OK：沒有漸層、沒有紫靛色`（`rgba(0,0,0,0.45)` 不含這些關鍵字，不會被抓）。**2026-08-21 校準**：步驟 3 要求抄進 `style.css` 檔頭的禁止清單註解本身含有這些關鍵字（引用禁詞≠使用禁詞）——覆核時排除註解行（例如 `\| grep -v "✗"`）後必須零命中；同理適用於「Inter」與「⑦ outline」兩項的檔頭註解命中 |
| ③ 玻璃擬態 | `OK：沒有玻璃擬態` |
| ③ Inter | `OK：沒有用 Inter 交差` |
| ③ 標題 emoji | `OK：標題沒有 emoji` |
| ④ 深色模式 | `OK：沒有深色模式` ＋ 找得到 `color-scheme: light` |
| ⑤ npm／外部資源 | 兩行 `OK：…` |
| ⑤ 端點數 | `photos.py:4`、`ask.py:1`、`folders.py:2`（`__init__.py:0` 也會列出，正常）＋ `main.py` 的 `2`（`/health` 與 `GET /` 轉址）＝合計 **9**——跟 Phase 25 步驟 5 同一種數法（數路由裝飾器）、同一個數字 |
| ⑤ Python／測試變動 | **不得出現 P26 造成的任何變動**。（2026-08-21 校準：本輪依指示先不 commit，Phase 25 的合法產出——`tests/integration/test_folder_error_paths.py` 與 `CLAUDE.md`——會照常出現在 porcelain 輸出，屬預期；判準是「相對於 Phase 25 完成時的狀態，P26 只動了 `app/static/` 五檔」，用 `git status` 前後對照確認） |
| ⑥ btn-primary | 兩行都是 `1`（每頁只有一個主要動作；`browse.html` 沒有主按鈕，不列入） |
| ⑦ outline | `OK：鍵盤外框沒有被拿掉` |
| ⑧ innerHTML | 每一處 `innerHTML` 賦值都在 render 系列函式裡，`-A 8` 印出的後續幾行中**每個動態值都包著 `esc(`**（這一項要用眼睛逐處看，腳本只是把現場攤出來）；`folder_modal.js` 只有 `holder.innerHTML = FOLDER_MODAL_HTML`（固定樣板字串、無外來資料，安全） |

### 步驟 9：Playwright MCP 全流程驗收（前後對比＋console 乾淨）

**同樣的視窗尺寸、同樣的六個畫面**，這次存到 `/tmp/ui-after/`：

1. `browser_resize`：`width=1280, height=800`（與步驟 0 相同）
2. `browser_navigate` → `/ui/upload.html` → 截圖 `/tmp/ui-after/01-upload.png`
3. `browser_file_upload` 選一張真照片 → `browser_click` 上傳鈕 → 等彈窗 → 截圖 `/tmp/ui-after/02-modal.png`
4. 彈窗選一個資料夾完成歸類 → 截圖 `/tmp/ui-after/03-result.png`
5. `browser_navigate` → `/ui/browse.html` → 截圖 `/tmp/ui-after/04-folders.png`；點資料夾 → 截圖 `/tmp/ui-after/05-photos.png`
6. `browser_navigate` → `/ui/ask.html` → 問一句 → 等回答 → 截圖 `/tmp/ui-after/06-ask.png`
7. **每一頁操作完都呼叫** `mcp__plugin_playwright_playwright__browser_console_messages`，確認沒有任何 error

把前後六對截圖並排看過（`open /tmp/ui-before /tmp/ui-after`），逐項確認：

| 對比項 | 「後」必須明顯優於「前」 |
|---|---|
| 資訊層次 | 品牌／頁面標題／說明／結果卡片的字級分得出來（前：全部差不多大） |
| 導覽 | 一眼看得出「我在哪一頁」（前：三個一模一樣的連結） |
| 按鈕主次 | 一眼看得出哪個是主要動作（前：全是系統預設按鈕） |
| 結果呈現 | 標籤／值兩欄對齊（前：一整塊 `<pre>` 純文字） |
| 留白節奏 | 區塊之間的間距有規律（來自 `--sp-*`，不是隨手打的數字） |
| 彈窗一致性 | 彈窗的線色、圓角、字級與頁面**完全一致**（前：兩套各自為政） |
| 縮圖牆 | 方格等大、對齊；沒有縮圖的是灰底占位、不是破圖 |
| 三頁一致 | 三張「後」截圖看起來像同一個產品 |

**全流程實操清單**（每一項親自走一次）：

- [ ] `GET /` 會轉到 `/ui/upload.html`
- [ ] 上傳 → 彈窗開啟 → 選項①「採用『…』」→ 關閉 → 結果卡片的「資料夾」更新
- [ ] 上傳 → 彈窗選項②下拉改選 → 「歸到這個資料夾」→ 關閉 → 資料夾更新
- [ ] 上傳 → 彈窗選項③自建（名稱＋說明）→ 「建立並歸類」→ 關閉 → 資料夾更新
- [ ] 上傳 → 選項③輸入**已存在**的資料夾名稱 → 彈窗**內**顯示 409 錯誤（`.fm-error` 紅框），彈窗不關
- [ ] 上傳 → 按 `Esc` 關掉彈窗 → 結果卡片顯示「已放進『未分類』，之後可到瀏覽頁再歸類」，且 `browser_network_requests` 確認**沒有**發出 PATCH
- [ ] 上傳 → 點彈窗外的暗色區 → 同上（等同關閉）
- [ ] 彈窗開啟時，背景頁面**不能**捲動；關閉後焦點回到原本的位置
- [ ] 只用鍵盤：`Tab` 走得到所有按鈕與輸入框，每一個都看得到聚焦外框；`Enter` 可以觸發
- [ ] 上傳一個 `.txt`（415）→ 結果卡片顯示紅點狀態列與錯誤訊息（不是白畫面、不是 `alert`）
- [ ] 瀏覽頁：資料夾卡片顯示名稱與說明；點進去看到縮圖牆；「← 回資料夾列表」可用
- [ ] 瀏覽頁：**遷移進來的舊照片顯示灰底占位**（不是破圖）
- [ ] 瀏覽頁：點單張照片 → 同一套彈窗，選項①文字是「維持『目前資料夾』」
- [ ] 問答頁：中文問一句 → 回答（大一級字）、檢索方式、依據照片三塊都在
- [ ] 問答頁：英文問一句 → 回答是英文
- [ ] 三頁互連：每一頁的導覽都能走到另外兩頁，且目前頁有標示
- [ ] **`browser_console_messages` 在三頁都沒有 error**（特別是不該有 CORS、`style.css` 404、`undefined` 相關訊息）

### 步驟 10：確認自動化測試一顆都沒變

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q | tail -1
```

**必須與前置條件記下的數字一模一樣。** 多了、少了、紅了，都代表改到不該改的東西——`git diff` 找出來還原。

### 步驟 11：git commit

```bash
cd /Users/linjunting/personalDocAI
git add -A
git status      # 確認只有 app/static/ 底下的檔案有變動，/tmp 的截圖沒有被加進來
git commit -m "$(cat <<'EOF'
feat: Phase 26 美化 UI/UX——三頁＋彈窗收進共用 app/static/style.css 設計 tokens，拒絕 AI 樣板臉

- 新增 app/static/style.css：全站唯一樣式來源（色票／三種字型／五級字級／六級間距／兩級圓角／
  單一陰影／版面 tokens），檔頭寫死禁止清單（紫靛漸層、置中大卡片＋emoji 標題、Inter 交差、
  無意義玻璃擬態、無理由的深色模式）與設計依據
- 設計決策依據（先載 frontend-design skill ＋ 實際查證的開源作品，非憑感覺）：
  * 參考 1：<連結> — <借用的具體做法>
  * 參考 2：<連結> — <借用的具體做法>
- upload/browse/ask：刪光頁內 <style>，統一 .site-header ＋ aria-current 導覽、<main class="page">，
  <pre id="result"> 改 .panel ＋ .status ＋ .kv 兩欄清單（innerHTML 一律過 esc()，屬性不插值）
- folder_modal.js：刪掉 FOLDER_MODAL_CSS 與注入 <style> 三行（樣式歸 style.css）；
  新增焦點管理（開啟移入、fmHide 統一還回）、body.fm-open 鎖捲動、點暗色區關閉；
  .fm-error:empty 自動收合所以 fmSetError 不用改；fmAssign 的 PATCH 邏輯一行未動
- browse：.folders 卡片、.wall 正方形縮圖牆、.placeholder 灰底占位（舊照片），只多加一個 .back-link class
- 底線全數守住：零框架、零打包、零外部資源、零新端點（仍 9 個）、零 .py 與零測試變動
  （NNN passed 不變）、不做深色模式（color-scheme: light）、桌機優先
- 驗收：Playwright MCP 1280×800 前後六組截圖對比（/tmp/ui-before ↔ /tmp/ui-after）、三頁 console 無 error、
  上傳→彈窗三選項＋409＋Esc＋點外關閉→瀏覽→問答全流程走過、鍵盤 Tab 可達且聚焦外框在

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01ShM1riRpQnG94w5eAt3BQp
EOF
)"
```

> commit 訊息裡的 `<連結>`、`<借用的具體做法>`、`NNN` 都要換成真實內容；`Claude-Session` 換成你這次工作階段的網址。

---

## 驗收清單

- [ ] 步驟 0：`/tmp/ui-before/` 有六張「美化前」截圖（1280×800）
- [ ] 步驟 1：**動手改任何檔案之前**已載入 `frontend-design` skill
- [ ] 步驟 2：參考點表格已填滿 **2〜3 列**，每列都有**完整來源連結**，「我看到什麼」是可翻成 CSS 的具體描述（不是「乾淨簡潔」）
- [ ] 步驟 3：禁止清單已抄進 `style.css` 檔頭註解
- [ ] 步驟 4：token 表每一格都有值；`--c-accent`、`--f-display`、`--f-body` 的選擇理由已寫進 `style.css` 檔頭並引用步驟 2 的參考
- [ ] `:root` 的值**已被自己的決策覆蓋**，不是本文件附的中性起始值原封不動
- [ ] 步驟 5c 兩個自檢腳本都印 `OK`（token 全有定義、tokens 區以外沒有寫死色碼）
- [ ] 步驟 6：三頁 `<head>` 都有 `<link rel="stylesheet" href="/ui/style.css">`，**頁內 `<style>` 全部刪光**
- [ ] 步驟 6：`innerHTML` 的每一處使用者／AI 內容都經過 `esc()`；**沒有任何動態值被放進 HTML 屬性位置**
- [ ] 步驟 7：`FOLDER_MODAL_CSS` 與注入 `<style>` 的三行已刪除，彈窗樣式全部來自 `style.css`
- [ ] 步驟 7：`folder_modal.js` 只多了焦點管理／鎖捲動／點外關閉，**`fmAssign()`／`fmDetailText()`／`fmSetError()`／`fmSetBusy()` 一行未動**
- [ ] 步驟 8 檢查腳本 13 項全數符合預期（特別是：**端點仍 9 個**、**Python 與測試零變動**、無漸層／無 Inter／無玻璃擬態／無深色模式／無 `outline: none`）
- [ ] 步驟 9：`/tmp/ui-after/` 六張截圖到齊，八個對比項逐項確認「後」優於「前」
- [ ] 步驟 9：全流程實操清單 **17 項全勾**，三頁 `browser_console_messages` **零 error**
- [ ] 步驟 10：**`pytest -q` 顆數與開工時完全相同且全綠**
- [ ] **最後一步**：`git add -A` → `git status` 確認只動 `app/static/` → `git commit`（訊息照步驟 11，含真實來源連結）

---

## 常見問題

**Q1：我可以跳過步驟 1、2 直接開始寫 CSS 嗎？我很有 sense。**
不行，而且這正是本 phase 存在的理由。沒有先看真實作品就動手，做出來的一定是訓練資料裡最常見的那個平均值——也就是禁止清單上的那張臉。步驟 2 的表格是驗收項目，交不出來就是沒做完。

**Q2：查不到 GitHub 上的照片庫專案怎麼辦？**
換關鍵字（`self-hosted photo library`、`album grid UI`、`media manager web ui`），或用 DeepWiki 直接問幾個知名 repo（`immich-app/immich`、`photoprism/photoprism`、`LibrePhotos/librephotos`、`filebrowser/filebrowser`）。真的查不到就改查「檔案上傳介面」「後台清單介面」——重點是**看真的作品**，不是非得照片庫不可。查到什麼就記什麼，附連結。

**Q3：可不可以用 Google Fonts 讓字型好看一點？**
**不可以。** 那會讓專案多一個外部相依，違反「全本地執行」的精神，離線就破版，而且步驟 8 的腳本會抓 `googleapis`。字型只准用系統內建的——用系統字型組出對比也是一種明確的設計選擇，只要你**寫得出為什麼選這組**。

**Q4：紫色真的完全不能用嗎？**
禁止的是「紫靛漸層背景」這個 AI 預設樣板，不是紫色本身。如果步驟 2 有真實作品支持、而且你在 `style.css` 檔頭寫得出理由，用一個紫色當 `--c-accent` 是可以的——但**不准是漸層、不准當背景**。步驟 8 的腳本抓的是關鍵字與那兩個經典色碼；屆時把理由寫進 commit 訊息，並改用具體色碼。

**Q5：可不可以順便加深色模式？現在只要一個 media query。**
**不可以。** 契約明訂不做（side project 不過度設計）。而且「只要一個 media query」不是真的——每個顏色 token 都要重想一次、每個對比都要重測一次、截圖驗收要做兩套。`color-scheme: light` 那一行就是我們的決定。

**Q6：可不可以加 Playwright 的自動化視覺回歸測試？截圖都拍了。**
**不可以。** 從 Phase 14 起就定了：頁面驗收以手動瀏覽器操作為準，**零新增自動化測試**。步驟 9 用 Playwright MCP 是「這一次的驗收工具」，不是要留下一套測試基礎建設。截圖放 `/tmp`，不進版控。

**Q7：`pytest` 顆數變了。**
代表改到 `app/` 底下的 Python 或 `tests/`。跑 `git status --porcelain` 看動到什麼，還原它。這個 phase 只准動 `app/static/` 底下的五個檔案。

**Q8：刪掉 `FOLDER_MODAL_CSS` 之後彈窗整個跑版了。**
正常，因為樣式的家搬了。檢查三件事：(a) 開彈窗的那一頁有沒有 `<link rel="stylesheet" href="/ui/style.css">`；(b) `style.css` 的彈窗區塊選擇器有沒有跟實際的 class 對上（步驟 5a 的 grep 再跑一次）；(c) `.fm-backdrop[hidden] { display: none; }` 這行在不在——沒有它，`display: flex` 會蓋過 `hidden` 屬性，彈窗會一直顯示在畫面上。

**Q9：`browse.html` 的排版壞掉了，因為 Phase 24 落地的 class 名稱跟骨架不一樣。**
處理方式二選一：把 CSS 選擇器改成配合既有 HTML（首選），或把 HTML 的 class 改成骨架的名稱。**不要兩邊都留一套**，也不要為了配合而改 JS 的資料流。選了哪一種，在 commit 訊息寫一句。

**Q10：頁面現在有點空，要不要加點裝飾（背景紋理、圖示、插畫）？**
不要。留白不是空，是節奏。真的覺得空，先檢查是不是 `--sp-*` 的級距太小（區塊之間該有 `--sp-5`〜`--sp-6`）、`--page-max` 是不是太寬。**加東西是最後手段，不是第一反應。**

**Q11：這是最後一個 phase 嗎？**
是。做完這個 phase，`docs/design/design1.md` 描述的增量就全部落地了：資料夾＝category、原圖與縮圖、上傳確認彈窗、資料夾瀏覽，而且看起來像有人設計過。

---

## 完成後的專案狀態

**本增量完成。** 除了 Phase 25 收尾的後端能力之外，三個頁面與彈窗現在共用同一套視覺語言：

- `app/static/style.css`：全站唯一的樣式來源。一組 design tokens（色票、三種字型、五級字級、六級間距、兩級圓角、一個陰影、一個轉場時間）撐起三頁＋彈窗；改一個 token，全站跟著變。
- `upload.html`／`browse.html`／`ask.html`：同一組頁首與導覽（目前頁有標示）、同一張卡片語言（`.panel` ＋ `.status` ＋ `.kv`）、同一套按鈕主次（每頁只有一個主要動作）。
- `folder_modal.js`：三選項與 `PATCH` 邏輯完全沒動，但樣式搬進 `style.css`，並多了焦點管理、背景鎖捲動、點暗色區關閉。
- 視覺決策**有據可查**：`style.css` 檔頭記著禁止清單、2〜3 個真實作品參考連結與色票／字型的選擇理由；commit 訊息記著借用了什麼、刻意不借什麼。
- 底線一條沒破：**零框架、零打包、零外部資源、零新端點（仍 9 個）、零 Python 變動、零自動化測試變動**（`pytest -q` 顆數與 Phase 25 完全相同）、不做深色模式、桌機優先。
