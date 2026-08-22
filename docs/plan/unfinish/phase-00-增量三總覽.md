# Phase 00：增量三總覽（design3.md 的實作路線圖，Phase 28〜37）

> **給實作者：** 本總覽把 `docs/design/design3.md`（2026-08-21 產品負責人拍板）拆成 10 個 phase。
> 每個 phase 有自己的計畫檔（本目錄 `phase-28`〜`phase-37`），**一次做一項**、全程 TDD＋BDD。
> 衝突時 design3.md 為準；design3 未提及的行為仍依 design2.md／design1.md／design.md v4。

> 🎯 **仍是 side project：不要過度設計。** 同一個 VLM 看一次、人確認才落庫；
> 不做自動拍、不做第二個模型、不做 agent 自己呼叫工具、不做刪除、不做多使用者。

## 1. 增量三是什麼（一句話＋圖）

全本地把一張掃描（JPEG/PNG/**PDF**/無線鏡頭）變成「抽屜裡的圖、可選的具名物件、可選的待辦」——
三種決定用**三個彈窗依序確認**後才落庫，然後可以用一句話問。

```text
進圖（擇一）                      三關（三個彈窗依序）                 落庫
  桌面上傳 JPEG/PNG/PDF   ──►  同一個 gemma4 看一次  ──►  彈窗1 抽屜(強制,design2)
  無線原生相機(QR,人按快門)      吐三類建議：              彈窗2 實體(可不釘,可釘多個)
                                抽屜1·實體1·待辦0或1      彈窗3 待辦(有actionable才出現)
                                照片先進「待決定」                │
                                                                  ▼
                              photo ──XOR── folder（抽屜：一張一類，定案不可逆）
                              photo ──AND── entity（別針：可多個，清單自創才變長）
                              photo ──0..1─ task  （待辦：人按建立才寫入）
                                                                  │
                                                                  ▼
                              POST /ask 一問一答：照片／某實體上的圖／待辦
```

## 2. Phase 拆解與進度

| Phase | 名稱 | 主要內容 | 輪次 | 完成 |
|---|---|---|---|---|
| 28 | PDF 入庫 | 接受 application/pdf；一頁→一張 photo；壞檔 422；`上傳照片.feature` 加 PDF Rule | 本輪 | [x] |
| 29 | 實體與待辦資料層 | `db/migrate_design3.sql` 一次建 4 表（entity／photo_entity／task／folder_correction）；entity 相關 repository 函式；conftest 安全網擴充 | 本輪 | [x] |
| 30 | 實體建議與釘選端點 | VLM 契約一次擴齊（實體＋待辦建議）；`GET /entities`、`POST /photos/{id}/entities`、`POST /photos/{id}/entity-suggestion`（新注入點 get_entity_suggester） | 本輪 | [x] |
| 31 | 實體彈窗 | `entity_modal.js`（①採用②改選③自創④不釘＋「再建議一個」）；上傳頁與待決定 tab 接上彈窗鏈 1→2 | 本輪 | [x] |
| 32 | 待辦資料層與端點 | task 相關 repository 函式；`POST /photos/{id}/task`、`GET /tasks` | 本輪 | [x] |
| 33 | 待辦彈窗與瀏覽第三入口 | `task_modal.js`（建立／略過）；鏈 1→2→3；瀏覽頁三 tab「待決定｜資料夾｜待辦」 | 本輪 | [x] |
| 34 | 詢問三路 | route 擴充 entity／task 兩路檢索；真模型煙霧（「跟我 MacBook 有關的全部」「這週要交什麼」） | 下輪 | [ ] |
| 35 | 抽屜糾錯 few-shot | 記最近 N=5 次「建議被改掉」注入看圖 prompt（表已由 P29 建好） | 下輪 | [ ] |
| 36 | 無線鏡頭 | QR 配對＋手機原生相機（**實作前需產品負責人釐清技術路線**，見 phase-36 檔） | 下輪 | [ ] |
| 37 | 增量三錯誤收尾與全量回歸 | design3 版錯誤表逐列把關＋「明確不做」掃碼＋全量回歸 | 下輪 | [ ] |

**依賴順序**：29 → 30 → 31；29 → 32 → 33；28 獨立可先做；34 依賴 29〜33 落庫的資料；35 依賴 29 的表；36 獨立；37 最後。

## 3. 對外行為演進（做完本輪之後）

- **端點 9 → 14**：+`GET /entities`、+`POST /photos/{id}/entities`、+`POST /photos/{id}/entity-suggestion`、
  +`POST /photos/{id}/task`、+`GET /tasks`（`GET /` 轉址不計入的算法不變——清點一律用 `/openapi.json`）。
- **`POST /photos` 收 PDF**：回應形狀＝單圖不變；PDF 回 `{pages, created:[單圖回應…], skipped_pages}`。
- **上傳回應加欄位**：`suggested_entity`／`entities`／`suggested_task`（既有欄位一個不動、.feature 既有 Rule 全綠）。
- **網頁仍三頁**，瀏覽頁二 tab → 三 tab；彈窗檔案由 1 個變 3 個（folder／entity／task modal，各自獨立、fm/em/tm 前綴隔離）。
- **資料表 2 → 6**：photo、folder ＋ entity、photo_entity、task、folder_correction（P35 才有程式讀寫 folder_correction）。

## 4. 全域鐵律（每個 phase 的計畫檔都隱含這一節）

1. **人確認才落庫**（design3 D3）：VLM 的實體／待辦輸出只是建議，只出現在回應；寫入一律走使用者按出來的端點。
2. **同一個 VLM 看一次**（D8）：上傳時只有一次看圖呼叫。「再建議一個」是文字 LLM 呼叫（不重看圖），有獨立注入點。
3. **建議只能從現有清單挑**（design3 §4）：抽屜 clamp 回資料夾清單、實體 clamp 回實體清單（清單外→null，不自動建）。
4. **design2 不動**：抽屜彈窗強制、定案不可逆（409／422）、待決定 tab 是第二歸類入口。
5. **測試安全網先行**：任何新表→`reset_tables` 同步清空；任何新 AI 注入點→`wire_fake_ai` 同步接假件；
   `OLLAMA_BASE_URL` 指死埠全量必須同顆數。
6. **SQL 只在 repository**；router 零 SQL；錯誤不吞（500 要帶 traceback）。
7. **禁 alert/confirm/prompt**；彈窗錯誤寫窗內；動態內容一律 textContent／esc()。
8. **不 commit**（產品負責人指示：改完先檢視）。

## 5. 已知限制（MVP 刻意為之，寫在這裡不寫在程式註解）

- **建議不持久化**（沿 design2 先例）：從待決定 tab 補完的鏈，實體窗無①（可按「再建議一個」現算）、
  **待辦窗不出現**（判 actionable 的建議只活在上傳回應裡）。手動建待辦沒有入口——design3 沒要求，不做。
- **多頁 PDF 只對第一頁跑彈窗鏈**：其餘頁留在待決定（待決定 tab 本來就是補完入口），不連跳 N 條鏈。
- **實體釘選不重算 embedding**：embedding 仍＝text＋四欄位（design.md 定案未動）；實體檢索走連結表（P34）。
- **待辦第一版**：不做完成勾選、不做過期刪除；能列、能點回來源圖（design3 §7）。

## 6. 總驗收（本輪結束時）

- [x] 全量 `pytest -q`＝**218 passed**；`OLLAMA_BASE_URL=http://localhost:9` 同顆數（2026-08-21 階段DDD）
- [x] `/openapi.json` 清點端點＝**14**
- [x] 規格檔：`上傳照片.feature`（11 條 Rule 版）＋`自然語言詢問.feature`（一字未動）全綠（含於 218）
- [x] 正式庫遷移 `db/migrate_design3.sql` 已執行（備份 `~/PersonalDocAI-backup-增量三前.sql`）且重跑實證冪等
- [x] Playwright 實操：上傳→鏈 1→2＋空關不跳（真 gemma #22）、待決定補完鏈（#21：歸檔→實體窗→自創→409→完成）、
      瀏覽三 tab（計數／直達／到期排序／點回原圖）、待辦窗真頁面驅動（預填→201→onDone）、
      curl 錯誤路徑六項、console 乾淨（僅 favicon＋刻意錯誤）。
      ＊PDF 真模型瀏覽器實測依產品負責人「做完 33 就停」指示裁掉——PDF 後端由 7 顆整合測試＋BDD Rule 把關、
      UI 走同一 `開始歸類()` 路徑（記錄於階段DDD REP）
- [x] 親自 review 全部 diff；28〜30 已 commit（e29f5a1），31〜33 依指示**未 commit**
