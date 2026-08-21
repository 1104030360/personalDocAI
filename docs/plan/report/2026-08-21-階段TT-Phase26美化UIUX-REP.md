# 2026-08-21 階段TT：Phase 26 美化 UI/UX——REP

## 實作邏輯

依 `unfinish/phase-26-美化UIUX.md`（RR 校準版），嚴格走計畫寫死的**決策程序**：前截圖 → 載 `frontend-design` skill → 查真實作品 → 禁止清單＋tokens 決策 → 落檔 → 底線腳本 → 後截圖＋17 項實操 → 顆數不變。全程由我親自執行（設計判斷重的 phase）。

## 步驟 2：真實作品參考點（含來源連結）

| # | 來源 | 我看到什麼（可翻成 CSS 的具體觀察） | 借用 | 刻意不借 |
|---|---|---|---|---|
| 1 | https://github.com/immich-app/immich （查證：https://deepwiki.com/search/describe-the-web-uis-album-lis_8f4d566a-f1ea-48e5-9eb9-c11c8bec81ba） | 相簿卡片用 auto-fill 響應式格線（最小寬約 14rem）；名稱截斷、張數以次級色小字分層顯示；淺色模式＝白底黑字＋單一靛藍強調；縮圖 `object-cover` 填滿 | 卡片 auto-fill 格線、名稱／張數字階分層、縮圖 object-cover、白底紀律 | 靛藍 primary、深色模式 |
| 2 | https://github.com/photoprism/photoprism （查證：https://deepwiki.com/search/describe-the-album-browsing-ui_5a76671e-62a8-47ac-80f5-caa0062a8a38） | 色彩系統把 background／surface／card 分成相鄰色階、層次靠色階與邊框不靠陰影；另設獨立於 primary 的「相簿識別色」（琥珀 #ed9e00）用於資料夾元素 | 「底色 vs 卡面用色階區分、卡片用邊框不用陰影」；把琥珀系相簿識別色加深成**本站唯一強調色** | 紫色 primary（#9E7BEA，禁止清單家族）、深色主題 |

## 步驟 3〜4：設計決策（理由都寫進 `style.css` 檔頭）

主題錨定：本產品是「個人視覺檔案櫃」——收據、牛皮紙資料夾、索引卡的世界。tokens：紙白底 `#fbfaf7`（比 AI 樣板常見奶油色淺而中性）、卡面純白、次底牛皮紙卡其 `#f3eee1`、暖色髮絲線 `#ddd5c2`、墨色文字（對比≈14:1）、**唯一強調色深琥珀 `#7c5200`**（參考 2 的相簿琥珀加深至白底≈6.9:1；非紫靛、非漸層、非 terracotta）；display＝macOS 系統 **Avenir Next**（檔案櫃標籤機貼紙的幾何感——刻意避開「奶油底＋襯線」AI 預設臉與被禁的 Inter）＋PingFang 內文＋**SF Mono 給照片 id／日期／search_mode（收據本來就是等寬字印的）**；五級字級／六級間距／兩級圓角／唯彈窗有陰影。**簽名元素**＝資料夾卡片頂上的牛皮紙索引 tab（`.folders li::before`，hover 轉琥珀）——瀏覽頁讀起來像拉開一格檔案抽屜；全站其餘保持安靜。

## 步驟 5〜7：落檔

- `style.css`：計畫骨架＋tokens 決策值＋簽名區塊（tokens-only）；5c 兩自檢 OK（token 全定義零多餘、tokens 區外零寫死色碼）。
- 三頁：`<link>` 共用、`site-header`＋`aria-current`、`<main class="page">`、`.panel`＋`.status`＋`.kv` 卡片語言、`esc()` 全動態值、屬性不插值；`browse.html` 僅 back-link class＋骨架四處；刪光頁內 `<style>`。
- `folder_modal.js`：刪 `FOLDER_MODAL_CSS`＋注入三行；加 `fmAfterOpen/fmAfterClose`（鎖捲動＋焦點入窗／還原）＋點暗色區關閉；`fmAssign`／`fmDetailText`／`fmSetError`／`fmSetBusy` 一行未動。

## 步驟 8〜10：驗收結果

- **底線腳本 13 項全過**（端點仍 9、P26 自身僅動 `app/static/` 五檔、btn-primary 每頁恰一、innerHTML 每處過 esc；③⑦ 的 grep 命中皆為計畫要求抄入的禁止清單**註解本身**——排除註解行後零實際使用，計畫已校準此註記）。
- **前後對比**：`/tmp/ui-before`↔`/tmp/ui-after` 六組（1280×800）。八項對比全數「後優於前」：字階分層、目前頁指示（琥珀底線）、按鈕主次（唯一深琥珀主鈕）、`.kv` 兩欄對齊取代 `<pre>` 純文字塊、間距全走 `--sp-*`、彈窗與頁面同一套線色圓角字級、縮圖牆等大方格＋牛皮紙占位、三頁一體。
- **17 項實操全過**：`/` 307→upload；①採用／②改選文件／③自建「煙霧測試」（同時補齊 P25 煙霧項目 4 的指定名稱）；③重名「收據」→彈窗內紅框 `（HTTP 409）` 不關窗；Esc 關閉＋`browser_network_requests` 過濾證明**零 PATCH**；點暗色區關閉＝同 ×；彈窗開啟時 `body.fm-open`＋`overflow:hidden`（evaluate 實證）＋焦點入窗、Tab 走訪有 2px 琥珀聚焦外框、關閉後焦點還原；415 → 紅點狀態列錯誤卡（無 alert）；瀏覽卡片→縮圖牆→占位→「維持」彈窗（九資料夾全列）→維持後仍 6 張；中文問（metadata search、中文回答引用六張 Target 收據）＋英文問（"You bought Coca-Cola 12pk."、vector semantic search）；三頁互連；console 全程僅 favicon 既有噪音＋刻意 409/415 測試日誌，零 JS 錯誤。
- **步驟 10**：`pytest -q` → **149 passed**（與 P25 完全相同；P26 零 Python／測試變動）。

## 遇到的問題與解法

1. **瀏覽器 heuristic cache 吃舊頁**（StaticFiles 無 Cache-Control，舊 HTML 被判仍新鮮；帶 query 的 `browse.html?folder=2` 另有獨立 cache key）→ 以 `fetch(url, {cache:'reload'})` 換新快取條目＋`location.reload()` 解決；**這正是 P23 計畫要求「Cmd+Shift+R 強制重新整理」的原因**，屬已知部署後換版的小坑，不在本 phase 改伺服器（零 Python 紅線）。
2. **`.caption` 兩行截斷出現第三行殘影**：overflow 裁在 padding-box 邊緣，第三行從 padding-bottom 區露出頭 → 下 padding 歸零＋盒高鎖「上 padding＋恰兩行」，殘影清除（截圖覆核）。
3. **一次幽靈事件**：一次上傳點擊後頁面停在初始狀態（handler 可證未執行）但後端確實收到請求並建檔（照片 12，未分類）——同一文件未曾 reload、JS 零錯誤、之後重測立即正常且此後全程未再現。照片 12 為合法收件箱資料，保留；已記錄。
4. 微裁定：`openFolderModal` 尾端以 `fmAfterOpen()` **取代**原 `fm-primary.focus()` 而非並存——並存會讓 `fmLastFocus` 記到彈窗自己的按鈕、關窗後焦點還錯位置（計畫僅寫「加一行」，未處理此互動）。

## 測試結果

**149 passed 不變**；design1.md 增量（P15〜26）至此**全數完成**——看得見、分得開、還能再問，而且像有人設計過。
