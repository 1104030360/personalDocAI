# Phase 27：待決定區與定案鎖定（design2.md 的實作）

> ✅ **已完成（2026-08-21，階段VV）**：後端 3 顆新測試先紅再綠（全量 152 passed、零 Ollama 同顆數）、
> 前端四檔改版、Playwright 十項實操全過——詳見 `docs/plan/report/2026-08-21-階段VV-Phase27待決定區與定案鎖定-REP.md`。
> 2026-08-21 依產品負責人指示隨 commit 歸檔至 `finish/`。
> （驗收清單由階段WW 依 VV REP 與 2026-08-21 重跑實證補打勾。）

> 🎯 **提醒：side project，不要過度設計。** 只做 design2.md 寫到的事；資料模型與端點數（9 個）完全不動。

**目標：** 上傳彈窗改為強制（無 ×／Esc／點外，新增「稍後再說」）；`PATCH` 加兩道檢查讓定案不可逆（已定案 409、目標是收件箱 422）；瀏覽頁分「待決定（N）｜資料夾」兩個 tab，未分類不再以卡片出現、資料夾 tab 純瀏覽。

## 前置條件

- Phase 15〜26 全數完成（2026-08-21，`pytest -q`＝**149 passed**，開工前實查）。完成後 ＝ **152**（+3 後端）。
- 測試庫 5433 在跑；後端測試不需要 Ollama；瀏覽器驗收用真伺服器（:8000）。

## 逐步驟（後端 TDD 先紅再綠 → 前端 → 實操驗收）

### 步驟 1：先紅——`tests/integration/test_assign_folder.py` 檔尾追加 3 顆

1. `test_已定案的照片再歸類回409且完全沒被改動`：上傳→PATCH 收據（200）→再 PATCH 飲食→**409**、detail「照片已定案，不可再變更資料夾」；三欄（folder_id/category/embedding）與第一次定案後完全相同。
2. `test_已定案後自建路徑也回409且不建資料夾`：定案後 PATCH `{"name": "新夾"}`→**409**；資料夾清單張數不變（定案檢查排在重名檢查與 create_folder 之前）。
3. `test_歸檔目標是收件箱回422`：待決定照片 PATCH `{"folder_id": 未分類id}`→**422**、detail「不能歸檔到收件箱」；照片仍在收件箱。

跑 `pytest tests/integration/test_assign_folder.py -q` → 預期 **3 failed, 8 passed**（紅）。

### 步驟 2：綠——`app/api/routers/photos.py` 的 `assign_folder` 加兩道檢查

- ① fetch_photo 404 之後：`get_folder(photo["folder_id"])`，`not is_inbox` → **409**（唯讀檢查，維持「檢查在前、寫入在後」）。
- folder_id 路徑 get_folder 命中之後：`folder["is_inbox"]` → **422**。
- SQL 零變動；`update_photo_folder`／`create_folder` 不動。

→ 11 passed；全量 **152**。

### 步驟 3：前端（四檔）

- `folder_modal.js`：模板拿掉 ×、加第四選項「稍後再說」（呼叫既有 `fmClose`，不打 API）；移除 Esc 與點外關閉監聽；`config.primary` 可為 `null`（隱藏①整列）；`fmSetBusy` 納入新按鈕。`fmAssign` 等四核心函式一行不動。
- `upload.html`：`primary＝建議是未分類時傳 null`；`folders` 過濾掉收件箱；文案——建議未分類→「AI 不確定這張要放哪…」、稍後再說→「已放進待決定區，之後到瀏覽頁的『待決定』分頁完成歸類。」；資料夾欄顯示「未分類（待決定）」。
- `browse.html`：頂部 tabs「待決定（N）｜資料夾」（預設待決定；`?tab=folders` 切資料夾、`?folder=N` 仍為牆）；待決定 tab＝收件箱縮圖牆＋彈窗（`primary:null`、folders 濾收件箱）；資料夾 tab 卡片排除收件箱；資料夾牆的照片改為**不可點**（div、無監聽、無 pointer）。
- `style.css`：新增 `.tabs`／`.tab` 樣式（沿用 tokens、底線式與導覽一致）；移除 `.fm-close` 相關規則（不留殘骸）；`.photo` 拆出可點（button）與純展示（div）皆適用的樣式。

### 步驟 4：瀏覽器實操驗收（Playwright MCP，逐項）

1. 上傳→彈窗：畫面上**沒有 ×**；按 Esc、點暗色區都**關不掉**。
2. 「稍後再說」→ 彈窗關、結果卡顯示待決定文案；瀏覽頁待決定 tab 看得到這張。
3. 上傳→選真資料夾→定案；資料夾 tab 該資料夾 +1、待決定不含它。
4. 待決定 tab 點照片→彈窗只有 ②③④（無①）→ 歸檔成功→從待決定消失。
5. 建議＝未分類的情境（用假件難以在真模型重現則以 curl 構造）：①不顯示。
6. 資料夾 tab 的縮圖牆：照片**點不動**（無彈窗）。
7. `curl` 對已定案照片 PATCH → 409；對待決定照片 PATCH 目標=1 → 422。
8. 「未分類」卡片不再出現在資料夾 tab；tab 計數正確；`?tab=folders` 與 `?folder=N` 網址可直達。
9. 三頁 console 乾淨（僅既有 favicon 噪音與刻意錯誤測試）。
10. `pytest -q` 仍 **152**；`git status` 僅本 phase 檔案。

## 驗收清單

- [x] `pytest tests/integration/test_assign_folder.py -v` → **11 passed**（8＋3）
- [x] 全量 `pytest -q` → **152 passed**；`OLLAMA_BASE_URL=http://localhost:9 pytest -q` 同顆數
- [x] `grep -n "409\|422" app/api/routers/photos.py` 見兩道新檢查；SQL 仍只在 repository
- [x] 端點仍 **9** 個（openapi 清點）
- [x] 彈窗無 ×／Esc／點外；「稍後再說」在四個選項最後
- [x] 瀏覽頁兩 tab、未分類卡片消失、資料夾牆不可點
- [x] 步驟 4 十項實操全過
- [x] 本 phase **不 commit**（產品負責人指示：改完先檢視）
