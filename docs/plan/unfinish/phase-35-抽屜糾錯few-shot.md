# Phase 35：抽屜糾錯 few-shot（design3.md D11，N=5）——下輪校準後實作

> 🎯 不是第二個模型、不是微調（§1.2 已否決）：只是把「建議被你改掉」的例子注入下一次看圖 prompt。仍要人按確認。

**目標：** 記住最近 5 次「VLM 建議 A、使用者選了 B（A≠B）」的糾錯例子，
上傳看圖時把它們當 few-shot 注入 prompt（表 `folder_correction` P29 已建好）。

## 待釐清（實作前先定案，寫進本檔再動工）

- **誰知道「建議是什麼」**：建議不持久化，`PATCH /photos/{id}/folder` 收不到它。
  候選方案 A（傾向）：PATCH body 加選填欄位 `suggested_name: str | None`——前端上傳彈窗按②③時把當時的建議名帶上；
  待決定分頁補完（無建議）不帶＝不記錄。候選方案 B：photo 表加 `suggested_category` 欄持久化（改資料模型，較重）。
- 「改掉」的定義：僅②改選現有與③自建算糾錯；①採用與稍後再說不算；建議＝未分類（clamp 失敗）不算（那是「沒建議」）。

## 拆解（實作時逐條先紅再綠）

1. repository：`record_folder_correction(suggested, chosen, photo_text)`＋`recent_corrections(limit=5)`（新的在前）。
2. PATCH 端點：定案成功且 `suggested_name` 有值且≠選定名稱 → 記一筆（寫在 update 之後，失敗不影響歸類本體）。
3. `build_vlm_prompt(folders, entities, corrections)`：有糾錯例子時加一段
   「最近的人工糾正（參考這些修正你的判斷）：『{photo_text 節錄}』你猜 {suggested}、正確是 {chosen}」×最多 5 條。
4. 前端：upload.html 彈窗②③的 PATCH body 帶 `suggested_name`（folder_modal.js 的 config 加選填欄位）。
5. 測試：記錄時機四情境（②③記、①不記、無建議不記、embedding 失敗不記）＋prompt 注入＋N=5 截斷（第 6 筆擠掉最舊）。

## 驗收清單

- [ ] 全量全綠、零 Ollama 同顆數；對外回應形狀不變（PATCH body 只是**多收**一個選填欄位）
- [ ] 糾錯只在真糾錯時記；prompt 最多 5 條、新的優先
