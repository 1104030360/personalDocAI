# PersonalDocAI — 設計文件（增量）：資料夾＝category、原圖瀏覽

> **一句話：上傳後 AI 從現有資料夾裡推薦一個，你確認或自建；之後點開資料夾看縮圖。**
> 這不是第二套分類，也不是第二個分類 AI。`category` 就是資料夾名稱。

> 🎯 **仍是 side project：不要過度設計。** 只做本文件寫到的事。詢問流程（`POST /ask`、LangGraph、兩種查法）維持 `design.md` v4，本文件不重做 RAG 檢索。

| 項目 | 內容 |
|---|---|
| 讀者 | 接下來實作此增量的人（含未來的自己） |
| 目的 | 把 2026-08-20 已拍板的「個人視覺檔案櫃」體驗寫成可實作的設計 |
| 範圍 | 存原圖、縮圖、資料夾清單、上傳確認彈窗、資料夾瀏覽。不含刪除照片、多使用者、第二個分類模型 |
| 前提 | `design.md` v4 已落地（Phase 01〜14：上傳、詢問、極簡 UI） |
| 狀態 | **可進入實作規劃**（2026-08-20）。本文件寫的是目標設計，**尚未實作** |
| 衝突時誰贏 | 本文件列出的「推翻項」以本文件為準；未提及的行為仍以 `design.md` v4 與 Clarify 為準 |

---

## 0. 這份文件在解什麼問題

v4 的體驗缺口：

1. 上傳完只留文字，**看不到圖**
2. `category` 是 VLM 自由字串，**沒有資料夾、不能確認、不能自建**
3. 沒有「我上傳過什麼」的瀏覽介面

使用者要的不是把 RAG 檢索調得更準，而是把系統做成：**看得見、分得開、還能再問**。

---

## 1. 已拍板決策（2026-08-20 對話）

| # | 決策 | 選擇 |
|---|---|---|
| D1 | 產品方向 | **正式改規格**：存原圖 + 資料夾 + 瀏覽。詢問功能保留 |
| D2 | 分類要幾套 | **一套**。資料夾 = `photo.category`。`location` / `items` / `content_time` 維持原樣 |
| D3 | 要不要第二個分類 AI | **不要**。沿用現有看圖 VLM，把「現有資料夾 list」當變數注入 prompt |
| D4 | 彈窗選項 | **三個**：(1) 採用 AI 推薦的那 **1** 個 (2) 改選其他現有資料夾 (3) 自建新資料夾（名稱 + description） |
| D5 | 關掉彈窗 | 照片進系統資料夾 **「未分類」**，之後可再歸類 |
| D6 | 點開資料夾 | 看到該資料夾內每張已上傳照片的 **縮圖** |
| D7 | 預設資料夾 | 見 §5。使用者可自建，新建的會進入同一份 list，下次上傳的 prompt 就看得到 |

### 1.1 本增量明確推翻的舊決策

這些是 Clarify / `design.md` v4 的定案，由產品負責人於 2026-08-20 **明示改規格**，不是實作時偷偷加功能：

| 舊決策 | 本文件改成 |
|---|---|
| 不儲存原始照片檔 | 存原圖 + 縮圖（檔案系統，資料庫只記路徑） |
| 禁止照片瀏覽／第三功能 | 新增資料夾瀏覽（縮圖牆） |
| `category` 由 VLM 自由填、直接落庫 | `category` 必須是資料夾清單中的名稱；VLM 只推薦，人確認後才定案 |
| 網頁介面只有上傳頁＋問答頁、不新增後端端點 | 新增資料夾／歸類／讀圖端點，以及瀏覽頁 |

未推翻：單一使用者、固定另外三欄 metadata、上傳同步、VLM 看不懂→422 不存、詢問 LLM 路由＋vector fallback、查無不虛構、最近＝30 天。

---

## 2. 目標流程（對齊後的 RAG ＋ 檔案櫃）

```text
【上傳】POST /photos
  JPEG/PNG
    → 格式檢查（非圖 → 415）
    → 從 DB 拿出全部資料夾 list（name + description）
    → VLM 看圖：文字 + location/items/content_time
               + 從 list 裡推薦 1 個 category
               （看不懂 / text 空 → 422，什麼都不存、也不留檔）
    → 存原圖、產生縮圖
    → INSERT photo（先掛在「未分類」；回傳建議資料夾）
    → 彈窗
         ① 採用 AI 推薦（1 個）
         ② 改選其他現有資料夾（完整 list）
         ③ 自建新資料夾（名稱 + description）→ 寫入 list，這張歸它
         關掉 → 維持「未分類」
    → PATCH 歸類後，category ＝ 該資料夾名稱
      （embedding 在上傳時已用當時的 category／未分類合併；
        歸類後要重算 embedding，見 §7.3）

【瀏覽】GET /ui/browse.html
  資料夾列表 → 點開一個 → 縮圖牆
  縮圖可再改資料夾（同一套三選項語意：採用現況 / 改選 / 自建）

【詢問】POST /ask
  不變。條件查詢仍用 category ILIKE；值改為受控資料夾名稱後會更穩。
```

`★ 設計取捨：VLM 仍然「自動分類」，但不再默默定案。最後寫進 category 的是使用者在彈窗裡選的那個資料夾名稱。`

---

## 3. 範圍

**做**

- 原圖與縮圖落地
- `folder` 表：名稱、description、是否為收件箱
- 預設 6 個資料夾；可自建（名稱 + description）
- 上傳後 modal：推薦 1 個 + 改選現有 + 自建
- 關掉 modal → 未分類；之後可再歸類
- 瀏覽頁：資料夾 → 縮圖
- VLM prompt 動態注入現有資料夾 list，只准從中選 1 個推薦

**不做**

- 第二個分類／推薦模型
- 把 `location` 或 `items` 當資料夾
- 刪除照片、刪除系統資料夾「未分類」
- 多使用者、雲端物件儲存、非同步佇列
- 改 `POST /ask` 的路由或 prompt 鐵律

---

## 4. 名詞

| 名詞 | 意思 |
|---|---|
| 資料夾（folder） | 使用者收納照片的類型。有名稱與 description |
| category | `photo` 上的既有欄位。本增量規定它 **等於** 所屬資料夾的 `name` |
| 未分類 | 系統收件箱資料夾。關掉彈窗、或尚未確認歸類時使用。不可刪 |
| 推薦 | VLM 從現有 list 選出的那 **一個** 資料夾，給彈窗選項 ① 用 |

---

## 5. 預設資料夾

系統啟動／重建 schema 時寫入。名稱用中文，避免再出現 `收據` vs `Receipt` 對不到的問題。

| name | description | 系統？ |
|---|---|---|
| 未分類 | 不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。 | 是（收件箱，不可刪、不可改名） |
| 收據 | 發票、消費憑證、購物明細。 | 否（可當普通資料夾用；預設存在） |
| 飲食 | 食物、飲料、餐廳、菜單。 | 否 |
| 風景 | 戶外、旅遊、地點、景色。 | 否 |
| 文件 | 非收據的文字資料，例如名片、說明書。 | 否 |
| 其他 | 看懂是什麼，但不符合上面任何一個。 | 否 |

正式庫現況（2026-08-20 查證）：`photo` 有 2 列，`category` 皆為「收據」。遷移時這 2 張歸入「收據」資料夾；它們沒有原圖，瀏覽時顯示占位圖（見 §10）。

使用者自建的資料夾與上表同一張 `folder` 表，只是沒有預先插入。

---

## 6. 資料模型

仍手寫 SQL、`schema.sql` 重建，不引 alembic。【設計】

```sql
CREATE TABLE folder (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text        NOT NULL UNIQUE,
  description text        NOT NULL DEFAULT '',
  is_inbox    boolean     NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- 全域最多一個收件箱
CREATE UNIQUE INDEX folder_one_inbox ON folder ((true)) WHERE is_inbox;

CREATE TABLE photo (
  id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text            text        NOT NULL,
  category        text,                    -- 必須等於所屬 folder.name；未分類時為「未分類」
  folder_id       integer     NOT NULL REFERENCES folder (id),
  location        text,
  items           text[]      NOT NULL DEFAULT '{}',
  content_time    date,
  uploaded_at     timestamptz NOT NULL DEFAULT now(),
  embedding       vector(1024) NOT NULL,
  original_path   text,                    -- 相對專案根，如 data/photos/1.jpg；舊資料可空
  thumbnail_path  text,                    -- 如 data/thumbs/1.jpg；舊資料可空
  content_type    text                     -- image/jpeg 或 image/png
);
```

**為什麼 category 還留著、又加 folder_id**【設計】：既有 metadata search 與 embedding 合併格式都讀 `category`。雙寫規則：每次歸類成功，`folder_id` 與 `category = folder.name` 一起更新。`folder` 是清單與 description 的唯一來源；`category` 是給檢索用的冗餘欄位。

**為什麼原圖走檔案系統、不進 BYTEA**【設計】：瀏覽要直接送圖檔；BYTEA 會把 PostgreSQL 備份與列寬撐大，對 side project 沒好處。路徑相對於專案根目錄，目錄為：

```text
data/photos/{id}.jpg|png
data/thumbs/{id}.jpg|png
```

`data/` 不入版控。禁止把二進位丟進 repo 根目錄（避免誤 commit）。

---

## 7. HTTP API

`POST /ask` 契約不變。以下為本增量新增或調整的端點。

### 7.1 `POST /photos` — 上傳（調整）

Request 仍是 `multipart/form-data` 欄位 `file`。415 / 422 行為不變。

成功 `201` 時照片**已存檔**，且 `folder` 先是「未分類」。回應多帶建議與完整清單，讓前端立刻畫彈窗：

```json
{
  "id": 1,
  "text": "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
  "metadata": {
    "category": "未分類",
    "location": "Target",
    "items": ["可樂", "洋芋片"],
    "content_time": "2026-08-10"
  },
  "folder": { "id": 1, "name": "未分類", "description": "……" },
  "suggested_folder": { "id": 2, "name": "收據", "description": "……" },
  "folders": [
    { "id": 1, "name": "未分類", "description": "……" },
    { "id": 2, "name": "收據", "description": "……" }
  ],
  "thumbnail_url": "/photos/1/thumbnail"
}
```

規則：

- `suggested_folder` 必須是 `folders` 裡的一筆。VLM 回了清單外的名稱 → 視為不確定，改建議「未分類」。
- 若 VLM 建議「未分類」，選項 ① 仍顯示「未分類」（與關掉彈窗結果相同，可接受）。

### 7.2 `PATCH /photos/{id}/folder` — 確認／改歸類／自建

兩種 body，擇一：

採用現有（選項 ① 或 ②）：

```json
{ "folder_id": 2 }
```

自建並歸類（選項 ③）：

```json
{ "name": "專案X", "description": "跟課程作業有關的照片" }
```

成功 `200`：回該張照片當下的 `folder` 與 `metadata.category`（已等於新資料夾名稱）。

失敗：

| 狀態碼 | 情境 |
|---|---|
| `404` | 照片 id 不存在 |
| `404` | `folder_id` 不存在 |
| `409` | 自建的 `name` 與現有資料夾重複（大小寫不敏感） |
| `422` | `name` 空白 |

### 7.3 歸類後重算 embedding

上傳當下 `category` 是「未分類」，向量若不再算，條件查詢仍可用新的 `category` 字串，但語意查詢會少掉正確類別訊號。

**【設計】** `PATCH` 成功後：用新的四欄 + text 重跑 `build_document` → `embed_query` → 更新 `photo.embedding` 與 `category`。仍同步、同一請求內完成。

### 7.4 瀏覽與讀圖

| 方法 | 路徑 | 成功 |
|---|---|---|
| `GET` | `/folders` | 全部資料夾（含 description、照片張數） |
| `GET` | `/folders/{id}` | 該資料夾 + 照片摘要（id、thumbnail_url、text、uploaded_at） |
| `GET` | `/photos/{id}/thumbnail` | 縮圖 bytes；無檔則占位圖或 `404`（舊資料無原圖 → `404`，前端顯示占位） |
| `GET` | `/photos/{id}/image` | 原圖 bytes |

不另做「列出全部照片、不分資料夾」的端點——瀏覽入口就是資料夾。

---

## 8. VLM：同一個看圖呼叫，list 當變數

**仍然只有一次看圖**（`vlm_service.py`）。禁止再加分類節點或第二個 ChatOllama。

每次上傳：

1. repository 讀出全部 `folder.name` + `description`
2. 組進 prompt（範例，實作可微調措辭，語意不可變）

```text
現有資料夾（category 只能從這裡選一個，禁止自創名稱）：
- 未分類：不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。
- 收據：發票、消費憑證、購物明細。
- ……（含使用者後來新建的）

category：必須是上面某個資料夾的「名稱」原文。
不確定就填「未分類」。不要翻譯成英文。
```

結構化輸出仍是現有六欄；`category` 的語意從「自由字串」改成「推薦的那一個資料夾名稱」。此欄是建議，**不是**最終歸屬——最終歸屬是 PATCH 的結果。

`location` / `items` / `content_time` / `text` 的語言規則維持 v4：跟照片主要語言，不翻譯。

---

## 9. 網頁介面

維持純 HTML + 原生 JS，零前端框架。【設計】

| 頁 | 職責 |
|---|---|
| `/ui/upload.html` | 選檔 → `POST /photos` → **modal** 三選項 → `PATCH /photos/{id}/folder`（或關掉＝不 PATCH，留在未分類）→ 顯示文字與四欄 |
| `/ui/browse.html` | `GET /folders` → 點資料夾 → 縮圖牆；可對單張再 PATCH 歸類 |
| `/ui/ask.html` | 不變 |

`/` 可維持轉到上傳頁；瀏覽與問答用頁內連結互指。

Modal 三選項對應：

1. 按鈕顯示 `採用「{suggested_folder.name}」`（可附 description）
2. `<select>` 綁 `folders`（可排除已顯示在 ① 的那個，或保留讓人看完整 list——**【設計】select 含全部資料夾**，避免資料夾變多時找不到）
3. 名稱 + description 兩個輸入框 +「建立並歸類」

---

## 10. 舊資料遷移

重建 `schema.sql` 會清空表，不適合已有 2 張真實照片的正式庫。實作時提供 **可重跑的增量 SQL**（例如 `db/migrate_folders.sql`）：

1. 建 `folder` 表、插入 §5 六筆（「未分類」`is_inbox=true`）
2. `photo` 加 `folder_id` / `original_path` / `thumbnail_path` / `content_type`
3. `folder_id` 依現有 `category` 對到同名資料夾；對不到或 `category` 為空 → 「未分類」，並把 `category` 改成該資料夾名稱
4. 路徑欄位維持 NULL → 瀏覽顯示占位，不假裝有圖

測試庫可直接改 `schema.sql` 後重建。

---

## 11. 分層與檔案（相對 v4 的增量）

沿用 api → services → repositories。SQL 仍只准寫在 repository。

| 檔案 | 變動 |
|---|---|
| `db/schema.sql` | 新增 `folder`；`photo` 新欄位 |
| `app/repositories/photo_repository.py` | 資料夾 CRUD、歸類、路徑、重算向量所需的 UPDATE |
| `app/services/vlm_service.py` | prompt 接受 folders 參數；校驗 category 必須在 list 內否則改「未分類」 |
| `app/services/indexing_service.py` | PATCH 歸類後重用既有 `build_document` / `embed_document` |
| `app/api/routers/photos.py` | 上傳回應擴充；新 PATCH／GET |
| `app/schemas/photo.py` | 新回應／請求模型 |
| `app/static/upload.html` | modal |
| `app/static/browse.html` | 新增 |
| `.gitignore` | `data/` |
| `requirements.txt` | 縮圖需要影像庫（建議 Pillow） |

不新增第二個 workflow、不新增 queue。

---

## 12. 錯誤與邊界

| 情境 | 行為 |
|---|---|
| VLM 看不懂 | 422，不建資料夾、不留檔（與 v4 相同） |
| VLM 建議不在 list 內 | 後端改建議「未分類」再回 201 |
| 關掉 modal | 不呼叫 PATCH，照片留在未分類 |
| 自建重名 | 409，不覆蓋 |
| 讀不到原圖／縮圖（舊列） | `404`，前端占位 |
| 「未分類」被當成建議 | 允許 |
| 試圖刪除未分類 | 本增量不做刪除 API；若未來要做，未分類必須拒絕 |

---

## 13. 測試策略

延續：pytest 不打真 Ollama；`wire_fake_ai` 涵蓋 VLM。本增量 Fake VLM 必須能依注入的 folder list 回一個 list 內的名稱。

建議測試（實作階段用 TDD 落地，此處只定行為）：

| 行為 | 層級 | 預期 |
|---|---|---|
| 上傳後 category 為「未分類」，且回傳 `suggested_folder` | 整合 | 201 |
| VLM 回了清單外字串 | 單元 | 建議被改成「未分類」 |
| PATCH 既有 folder_id | 整合 | `category`＝該資料夾 name，embedding 更新 |
| PATCH 自建 | 整合 | 新 folder 列出現；該照片歸它；下次上傳的 folders 含此名稱 |
| 關掉＝不 PATCH | 整合 | 仍在未分類 |
| `GET /folders/{id}` 縮圖資訊 | 整合 | 有路徑的回 thumbnail_url |
| 既有 ask 規格 5 條 Rule | 整合 | 全綠（歸類後的 category 仍可供 ILIKE） |

真模型煙霧維持手動，不進 CI。

---

## 14. 被否決的方案（不要重開）

| 方案 | 為什麼否決 |
|---|---|
| 上傳後再呼叫一個分類 AI | 與 VLM 看圖重複；`category` 已能承擔 |
| 彈窗推 2 個 AI 推薦 | 使用者改為推 1 個，其餘用完整 list 自選 |
| 資料夾與 category 兩套平行分類 | 會撞名、兩套 UI、檢索不知信誰 |
| 原圖存 PostgreSQL BYTEA | 瀏覽與備份成本高，無額外好處 |
| 原圖丟 repo 根目錄 | 容易進 git |
| 沒選就自動採用 AI 第一推薦 | 失去 human-in-the-loop |
| 關掉彈窗就不留檔 | VLM 與存檔已完成，丟掉可惜（已選進未分類） |

---

## 15. 假設、限制、後續不做（暫時）

- 單一使用者；資料夾清單是全域一份。
- 資料夾名稱不翻譯；VLM 與 UI 都用中文名稱。英文照片的 `text`/`location`/`items` 仍可為英文。
- 條件查詢「問 receipts 對不到 收據」的限制仍在；本增量只讓**寫入端**不再自由發明英文 category。
- 不做資料夾巢狀、標籤多對多、相簿分享。
- 不做刪除照片／刪除自建資料夾（若之後要做：未分類不可刪；刪資料夾前照片先移到未分類）。

**未定案：無。** 預設六個資料夾名稱以本文件 §5 為準；若實作前記得改名稱，只准改 §5 與 seed SQL，不准再引入第二套分類。

---

## 16. 與 v4 的關係（實作時怎麼讀）

```text
design.md v4     → 上傳看圖、四欄 metadata、詢問 RAG、錯誤碼、測試注入點
design1.md（本文件）→ 原圖／縮圖、folder 表、上傳 modal、瀏覽頁、category 受控
```

實作順序建議（僅規劃，不是本文件的任務）：schema＋folder seed → 存檔與縮圖 → VLM prompt 注入 list → 上傳回應與 PATCH → upload modal → browse 頁 → 舊資料遷移 → 全量回歸既有 pytest。
