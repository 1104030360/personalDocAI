# 2026-08-21 階段KK：總驗收與親自 Review（P18〜P20 收尾）——REP

## 實作邏輯

三個 phase 由 Opus subagent 依（GG 校準後的）計畫實作、每 phase 完成當下我已各自 review diff＋親自複跑；本階段做整輪最終把關：全 diff 人工終審、跨 phase 驗收批次重跑、真模型手動煙霧（P18 步驟 8＋P19 步驟 7 延到此處統一做）、CLAUDE.md 現況更新。

## 親自 Review 結論（全 diff 逐檔過目）

改動範圍：產品碼 4 檔（`vlm_service.py`／`photos.py`／`photo_repository.py`／`schemas/photo.py`）＋規格 1 檔（`上傳照片.feature`）＋測試 8 檔（新增 `test_photo_files.py`、改版 `test_upload_feature.py`／`test_upload_bilingual.py`、增補 `test_vlm_service_unit.py`／`test_upload_design_rules.py`／`fakes.py`、微調 `test_photos_upload.py`／`test_error_paths.py`）＋docs（計畫校準、TODO/REP）。

- **與計畫零實作偏差**：三個 subagent 的 diff 我逐段對照計畫程式碼區塊，全部逐字一致（含 P20 保留 P19 落地寫檔段的 ⚠️ 要求）。
- **分層紀律**：SQL 仍只在 `photo_repository.py`（grep 實證）；storage 只碰檔案；router 只做編排。
- **不吞錯**：`photos.py` 恰一處 `except Exception`，清理後裸 `raise`。
- **被否決方案零回魂**：無第二個 ChatOllama（全專案 5 處與開工前相同）、無 BYTEA、無大小上限字樣、無刪除端點（`delete_photo` 僅失敗清理呼叫）、無快取/ETag。
- **紅線**：`自然語言詢問.feature` 零 diff；`上傳照片.feature` 恰 10 Rule／10 Example。

## 最終驗證（新鮮跑，非引用舊輸出）

| 項目 | 結果 |
|---|---|
| `pytest -q` | **124 passed**（103→110→121→124，三段各與計畫預告一致） |
| 兩份規格檔 | **17 passed**（上傳 10＋詢問 7 例；15 條 Rule 全綠） |
| P18 驗收 | `VLM_PROMPT` 已移除；三處 `understand` 簽名皆含 `folders`；ChatOllama 5 處未增 |
| P19 驗收 | SQL 只在 repository；無大小上限字樣；端點恰 6（openapi 清點）；schemas 於 P19 當下零改動 |
| P20 驗收 | Rule/Example 各 10；詢問規格零 diff；Rule 正文無「不含原始照片檔」 |

## 真模型手動煙霧（不進 CI；2026-08-21 實測）

1. **P18 步驟 8**（正式庫唯讀）：`build_vlm_prompt(list_folders())` 印出六行「- 名稱：說明」清單注入；clamp 五例 `收據／〃／未分類／未分類／未分類` 與計畫預期完全一致。
2. **P19 步驟 7＋P20 合併版**（uvicorn :8010＋真 gemma4＋真 bge-m3）：自產 800×1000 擬真 Target 收據 JPEG 上傳 → **201**，`text`／`items` 英文原文、`content_time` 從圖上讀出 `2026-08-15`、`location`＝Target、**`suggested_folder`＝「收據」（真模型從注入清單挑中、未翻譯）**、`metadata.category`＝`folder.name`＝「未分類」、`folders` 六筆、`thumbnail_url`＝`/photos/3/thumbnail`。落地：`data/photos/3.jpg`（SHA1 與上傳檔**完全相同**）＋`data/thumbs/3.jpg`（410×512，長邊 512）；讀圖端點縮圖／原圖皆 200 且 `image/jpeg`；正式庫舊照片 1（路徑 NULL）**404**、不存在的 9999 **404**。正式庫終態：3 列（2 舊列不動＋煙霧 1 列 `未分類/folder_id=1/路徑已回填`）。測畢已關閉伺服器。

## 文件收尾

- `CLAUDE.md`：現況段補「Phase 18〜20 已完成（2026-08-21）」＋新增 P18〜20 成果段（上傳改版、端點 4→6、規格 7→10 Rule、真模型煙霧）；測試顆數 103→**124**；規格檔唯讀敘述加註唯一例外；指令區規格檔註解改 15 條 Rule／17 例。
- 記憶庫新增 `fastapi-routes-not-flattened`（0.141 的 `app.routes` 清點坑→一律用 `/openapi.json`）。

## 遇到的問題與解法（本階段裁定彙整）

1. FastAPI 0.141 `app.routes` 不攤平 router 端點 → 驗收改查 `/openapi.json`，phase-19 計畫已校準（詳見階段II REP）。
2. 「假位元組已清完」grep 誤中 `fakes.py` 說明註解 → 註解措辭微調，grep 乾淨（詳見階段II REP）。
3. phase-20 計畫自我矛盾（驗收 grep vs 指定檔頭註解）→ 規格檔保持原文、驗收指令改排除註解行（詳見階段JJ REP）。
4. 工作區出現使用者預先放置的下一輪 dev-prompt `phase0821-1.md`（Phase 21〜24）→ 本輪 goal 僅指定 `phase0821.md`，**不擅自展開**，於總結回報待指示。

## 未完成／延後（依使用者指示）

- **git commit 未執行**（使用者明示「先不 commit」）。建議 commit 拆法：①`feat: Phase 18〜20`（app/＋tests/＋上傳照片.feature）②`docs: 計畫校準＋TODO/REP＋CLAUDE.md＋phase-18〜20 歸檔至 finish/`。三份計畫檔的 commit 指令模板都在各自驗收清單裡（P20 訊息的累計顆數＝124）。
- phase-18〜20 計畫檔**尚未**移到 `docs/plan/finish/`（歸檔動作與 commit 一起做，避免未 commit 的工作樹出現一堆 rename 干擾檢視）。
