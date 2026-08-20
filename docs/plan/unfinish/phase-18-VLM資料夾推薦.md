# Phase 18：VLM 資料夾推薦（prompt 注入現有清單＋clamp 夾回清單內）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。特別是：**禁止再加第二個分類模型、第二個 ChatOllama、第二個 LangGraph 節點**（design1.md §14 已明文否決）。仍然只有一次看圖呼叫。

**目標：** 讓 VLM 的 `category` 從「自由發明的字串」變成「**從現有資料夾清單裡挑一個**」——做法是把資料夾清單當變數注入 prompt，再用一個純函式 `clamp_category()` 把模型的回答夾回清單內（清單外一律變成「未分類」）。

本 phase **只改「怎麼問 VLM」與「怎麼校正 VLM 的答案」**：不改儲存行為、不改回應格式、`clamp_category` 的結果**不落庫**。把它接進上傳流程是 **Phase 20** 的事。

---

## 前置條件

- 需要已完成的 phase：**Phase 15**（`folder` 表＋六筆預設資料夾、conftest 的 `reset_tables` 每測重播種子）、**Phase 16**（`photo_repository.list_folders()`，回傳鍵 `id,name,description,is_inbox,photo_count`）、**Phase 17**（檔案儲存服務；本 phase 不用它，但照順序做基線才對得上）。
- 基線（開工前**實查**）：`pytest -q` 全綠。數字＝ **79**（Phase 01〜14）＋ Phase 15〜17 各自新增的顆數。動手前先跑一次記下來。
- 環境：本 phase 的測試**不需要 Ollama**（`wire_fake_ai` 一律接假件），但需要測試資料庫（要讀資料夾清單）。
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

現在的 `category` 是 VLM 自由填的：同一疊收據，它可能填「收據」，也可能填「發票」「消費憑證」「Receipt」。這在 v4 沒差（反正只是一個欄位），但 design1.md 把 **category ＝ 資料夾名稱**，自由字串就變成災難——每張照片都會生出一個新資料夾。

design1.md §8 的解法很簡單，而且刻意**不加任何模型**：

1. 上傳時先從資料庫讀出全部資料夾（名稱＋說明）。
2. 把這份清單**寫進 prompt**，明講「category 只能從這裡選一個，禁止自創名稱」。
3. 模型仍然可能不聽話（小模型很常見）。所以後端再加一道保險：`clamp_category()` 把回來的字串跟清單比對，**對得上就用清單裡的原文，對不上就一律當成「未分類」**。

第 3 步就是所謂的 **clamp**（夾住）：把一個可能亂跑的值，強制夾回允許的範圍內。這是本 phase 的核心觀念——**prompt 只是「請你這樣做」，clamp 才是「你不這樣做也沒用」**。

兩個容易搞混的點先講清楚：

- **VLM 給的 category 是「建議」，不是「最終歸屬」。** 最終歸屬是使用者在彈窗按下去的那個（Phase 20〜21）。所以本 phase 完全不改儲存。
- **資料夾名稱不隨照片語言變。** design1.md §8 明訂：`text` / `location` / `items` / `content_time` 維持「跟照片主要語言、不翻譯」的老規矩；但 `category` 是資料夾名稱，一律照清單原文（中文），英文收據也是填「收據」。這是本 phase 唯一對語言規則的補充，要寫進 prompt。

**這一改會動到既有測試**：`tests/unit/test_vlm_service_unit.py` 現在有一個 `test_vlm_prompt_含雙語規則`，直接 import 常數 `VLM_PROMPT`。常數改成函式後那個 import 會壞掉，**本 phase 必須把它一起改掉**（步驟 4 會逐字寫出來）。除此之外，全專案只有 `app/api/routers/photos.py` 第 39 行呼叫 `vlm.understand(...)`，改動範圍就這麼大。

**名詞**：

- **clamp（夾住）**＝把一個值強制限制在允許範圍內。這裡是「不在資料夾清單裡的名稱 → 一律換成『未分類』」。
- **prompt 注入變數**＝prompt 不是寫死的一段文字，而是每次呼叫前用當下的資料（資料夾清單）現組出來。所以使用者今天新建了「專案X」，下一次上傳時模型就看得到它。
- **`Protocol`**＝Python 的「型別協定」。它不是要被繼承的父類別，而是一張**規格表**：任何物件只要具備表上列的方法，就算符合這個協定。`VLMClient` 就是這種角色——`OllamaVLM`（正式）與 `FakeVLM`（測試）誰都沒有繼承它，但兩個都符合。**改協定的方法簽名時，兩個實作都要跟著改**，不然正式路徑與測試路徑會對不起來。
- **結構化輸出（structured output）**＝要求模型不要回自由文字，而是回一個固定欄位的資料結構（本專案是 `PhotoUnderstanding` 六欄位）。程式碼在 `OllamaVLM.__init__` 的 `.with_structured_output(PhotoUnderstanding)`。
- **`casefold()`**＝Python 字串的「更徹底的小寫化」，用來做**大小寫不敏感**的比對。比 `lower()` 更適合跨語言（例如德文 ß）；中文沒有大小寫，`casefold()` 對它是無害的原樣回傳。
- **f-string**＝Python 的字串格式化語法（`f"名稱：{name}"`），大括號裡的變數會被代換成實際的值。本 phase 用它把資料夾清單組進 prompt。
- **`"""..."""`（三引號字串）**＝可以跨很多行的字串。prompt 這種長文字都用它寫。
- **純函式**＝給同樣的輸入永遠回同樣的輸出、不碰資料庫、不碰網路、不改任何外部狀態的函式。`clamp_category` 就是純函式，所以它可以用最便宜的**單元測試**驗。

---

## ASCII 圖：清單注入 prompt → 看圖 → clamp 夾回清單內

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ ① 讀清單（Phase 16 的函式，SQL 只在 repository）                  │
  │    photo_repository.list_folders()                               │
  │    → [{id:1, name:"未分類", description:"不確定、關掉彈窗…"},     │
  │       {id:2, name:"收據",   description:"發票、消費憑證…"}, …]    │
  └────────────────────────────┬─────────────────────────────────────┘
                               ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ ② build_vlm_prompt(folders)            ★本 phase                 │
  │    ……                                                            │
  │    現有資料夾（category 只能從這裡選一個，禁止自創名稱）：          │
  │    - 未分類：不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。       │
  │    - 收據：發票、消費憑證、購物明細。                              │
  │    - 飲食：食物、飲料、餐廳、菜單。                                │
  │    - …（使用者自建的資料夾也會自動出現在這裡）                      │
  │                                                                  │
  │    category：必須是上面某個資料夾的「名稱」原文。                  │
  │    不確定就填「未分類」。不要翻譯成英文。                          │
  │    ……（語言規則、其他規則維持 v4 原文）                           │
  └────────────────────────────┬─────────────────────────────────────┘
                               │  prompt 文字 ＋ 照片 base64
                               ▼
                  ┌────────────────────────────┐
                  │ ③ gemma4 看圖（只有這一次） │  ← 禁止加第二個模型
                  │   結構化輸出六欄位          │
                  └─────────────┬──────────────┘
                                ▼  category（模型的推薦，不保證守規矩）
  ┌──────────────────────────────────────────────────────────────────┐
  │ ④ clamp_category(category, folders)     ★本 phase                │
  │                                                                  │
  │    "收據"    ─ 清單內          ─▶ "收據"      （回清單裡的原文）   │
  │    "  收據 " ─ 去空白後命中     ─▶ "收據"                          │
  │    "receipt" ─ 大小寫不敏感比對，但清單裡沒有這個名稱 ─▶ "未分類"  │
  │    "美食"    ─ 清單外（自創）   ─▶ "未分類"                        │
  │    None      ─ 根本沒填         ─▶ "未分類"                        │
  └────────────────────────────┬─────────────────────────────────────┘
                               ▼
                     建議的資料夾名稱（一個字串）
        ⚠ 本 phase 到此為止：不落庫、不進回應、不改上傳行為
           （Phase 20 才把它變成回應裡的 suggested_folder）
```

---

## 逐步驟操作

> 🧪 **執行順序採 TDD（先紅再綠）**：步驟 1 先寫測試看它紅，步驟 2〜3 實作讓它綠，步驟 4 同步假件（FakeVLM 簽名），步驟 5〜6 補呼叫端與整合測試，步驟 7 全量回歸。

### 步驟 1：先寫單元測試（紅）——改寫 `tests/unit/test_vlm_service_unit.py`

把整個檔案換成下面內容。改動有三處：① 檔頭註解補上 design1.md 的來源；② 原本的 `test_vlm_prompt_含雙語規則` 改成呼叫 `build_vlm_prompt(...)`；③ 新增 6 個測試（prompt 2 個、clamp 4 個）。

```python
"""vlm_service 的單元測試：純函式與資料模型，不碰資料庫、不碰網路。

BDD 對應（docs/spec/features/上傳照片.feature）：
Rule U3「儲存結構化 metadata（四欄位；清單外資訊捨棄）」——六欄位模型＝「清單外沒有地方放」。
雙語（design.md §8.1）：prompt 必須明文要求用照片主要語言、不翻譯。
資料夾推薦（design1.md §8）：prompt 注入現有資料夾清單；clamp_category 把清單外的名稱夾成「未分類」。
"""

from datetime import date

from app.services.vlm_service import (
    PhotoUnderstanding,
    build_vlm_prompt,
    clamp_category,
    parse_content_time,
)

# 對應 design1.md §5 的預設六資料夾（這裡只列測試需要的欄位）
FOLDERS = [
    {"id": 1, "name": "未分類", "description": "不確定、關掉彈窗、或暫時不想歸類。這張會進這裡。"},
    {"id": 2, "name": "收據", "description": "發票、消費憑證、購物明細。"},
    {"id": 3, "name": "飲食", "description": "食物、飲料、餐廳、菜單。"},
    {"id": 4, "name": "風景", "description": "戶外、旅遊、地點、景色。"},
    {"id": 5, "name": "文件", "description": "非收據的文字資料，例如名片、說明書。"},
    {"id": 6, "name": "其他", "description": "看懂是什麼，但不符合上面任何一個。"},
]


def test_photo_understanding_只有六個欄位():
    # 清單外資訊沒有地方放（U3「清單外捨棄」在源頭的落實）
    assert list(PhotoUnderstanding.model_fields) == [
        "understood", "text", "category", "location", "items", "content_time",
    ]


def test_build_vlm_prompt_含雙語規則():
    # design.md §8.1：描述用照片主要語言、不翻譯（雙語需求的來源，本 phase 不推翻）
    prompt = build_vlm_prompt(FOLDERS)

    assert "照片內容本身的主要語言" in prompt
    assert "不要翻譯" in prompt


def test_build_vlm_prompt_含所有資料夾名稱與說明():
    """design1.md §8：清單是變數，使用者自建的資料夾也要出現在 prompt 裡。"""
    prompt = build_vlm_prompt(FOLDERS + [
        {"id": 7, "name": "專案X", "description": "跟課程作業有關的照片"},
    ])

    for folder in FOLDERS:
        assert folder["name"] in prompt
        assert folder["description"] in prompt
    # 使用者後來新建的也要在
    assert "專案X" in prompt
    assert "跟課程作業有關的照片" in prompt


def test_build_vlm_prompt_明講只能從清單選且不可自創():
    """prompt 是第一道防線（第二道是 clamp_category）。措辭語意照 design1.md §8。"""
    prompt = build_vlm_prompt(FOLDERS)

    assert "現有資料夾" in prompt
    assert "禁止自創名稱" in prompt
    assert "不確定就填「未分類」" in prompt


def test_clamp_category_清單內就回清單裡的原文():
    assert clamp_category("收據", FOLDERS) == "收據"
    assert clamp_category("飲食", FOLDERS) == "飲食"


def test_clamp_category_大小寫混用也命中且回原文():
    """大小寫不敏感比對；回的是資料夾清單裡的原文，不是模型打的那個大小寫。"""
    folders = FOLDERS + [{"id": 7, "name": "Receipt", "description": "英文收據資料夾"}]

    assert clamp_category("receipt", folders) == "Receipt"
    assert clamp_category("RECEIPT", folders) == "Receipt"
    assert clamp_category("  Receipt  ", folders) == "Receipt"


def test_clamp_category_清單外一律變未分類():
    """design1.md §12：VLM 建議不在 list 內 → 後端改建議「未分類」。"""
    assert clamp_category("美食", FOLDERS) == "未分類"
    assert clamp_category("Receipt", FOLDERS) == "未分類"   # 清單裡只有中文「收據」
    assert clamp_category("", FOLDERS) == "未分類"


def test_clamp_category_沒填也變未分類():
    assert clamp_category(None, FOLDERS) == "未分類"


# ---- 以下四個是既有測試，原封不動保留 ----
def test_parse_content_time_解析ISO日期():
    assert parse_content_time("2026-08-10") == date(2026, 8, 10)


def test_parse_content_time_帶時間字尾只取日期():
    # VLM 偶爾會回 "2026-08-10T00:00:00" 之類，前 10 個字元就是日期
    assert parse_content_time("2026-08-10T00:00:00") == date(2026, 8, 10)


def test_parse_content_time_解析不出回None():
    # 內容時間本來就可空，解析失敗不得讓上傳失敗（design.md §8.1）
    assert parse_content_time("去年夏天") is None


def test_parse_content_time_空值回None():
    assert parse_content_time(None) is None
    assert parse_content_time("") is None
```

> 📌 檔案裡共 **12** 個測試函式：六欄位 1、prompt 3、clamp 4、`parse_content_time` 4。
> 原本是 6 個（六欄位 1、prompt 1、`parse_content_time` 4），其中 `test_vlm_prompt_含雙語規則` 被改寫成
> `test_build_vlm_prompt_含雙語規則`，其餘原封不動 → **淨增 6 個**。

跑一次確認它**紅**：

```bash
pytest tests/unit/test_vlm_service_unit.py -q
```

預期：collection error，訊息類似 `ImportError: cannot import name 'build_vlm_prompt' from 'app.services.vlm_service'`。這就是紅。

### 步驟 2：把 `VLM_PROMPT` 常數改成 `build_vlm_prompt(folders)`

打開 `app/services/vlm_service.py`。找到第 33〜51 行的 `VLM_PROMPT = """..."""` 整塊，**整段刪掉**，換成：

```python
# 系統收件箱資料夾的名稱。與 photo_repository.DEFAULT_FOLDERS 的第一筆一致
# （design1.md §5：「未分類」是唯一的系統資料夾，is_inbox=true）。
UNCATEGORIZED = "未分類"


def build_vlm_prompt(folders: list[dict]) -> str:
    """組出看圖用的 prompt，把「現有資料夾清單」當變數注入（design1.md §8）。

    folders 來自 photo_repository.list_folders()，每筆至少要有 name 與 description。
    清單是變數不是常數——使用者今天自建了「專案X」，下一次上傳時模型就看得到它。

    注意：這裡只是「請模型這樣做」。模型不聽話是常態，
    真正的保險是後面的 clamp_category()（清單外一律夾成「未分類」）。
    """
    folder_lines = "\n".join(
        f"- {folder['name']}：{folder['description']}" for folder in folders
    )
    return f"""你是照片理解助手。請看這張照片，只輸出下列六個欄位：

- understood：你是否看得懂這張照片的內容（看不懂填 false）
- text：用一句話描述照片內容
- category：這張照片應該收進哪一個資料夾（規則見下方「現有資料夾」）
- location：地點或商家名稱，例如「Target」；判斷不出來填 null
- items：照片中出現的物品名稱清單；沒有就填空陣列
- content_time：照片內容本身的日期（例如收據上的消費日期），格式 YYYY-MM-DD；推不出來填 null

現有資料夾（category 只能從這裡選一個，禁止自創名稱）：
{folder_lines}

category：必須是上面某個資料夾的「名稱」原文。
不確定就填「未分類」。不要翻譯成英文。

語言規則（重要）：
- text 與各欄位的值，一律使用**照片內容本身的主要語言**。
  照片上是中文（例如中文收據）就用繁體中文寫；照片上是英文（例如英文收據）就用英文寫。
- 不要翻譯。不要中英混寫。照片上寫 "Cola" 就填 "Cola"，寫「可樂」就填「可樂」。
- 例外：category 是資料夾名稱，一律照上面清單的原文，不隨照片語言改變。

其他規則：
1. 只准填上面這六個欄位，清單外的任何資訊一律捨棄。
2. 不要編造照片上沒有的資訊。
3. 照片模糊、全黑或看不出任何內容時，understood 填 false。
"""


def clamp_category(category: str | None, folders: list[dict]) -> str:
    """把 VLM 推薦的 category 夾回資料夾清單內（design1.md §7.1、§12）。

    - 命中（去頭尾空白、大小寫不敏感）→ 回**資料夾清單裡的原文**，
      這樣「  收據 」「RECEIPT」都不會生出新的名稱變體。
    - 沒命中、或模型根本沒填 → 回「未分類」，語意就是「不確定」。

    這是純函式：不碰資料庫、不碰網路，給同樣的輸入永遠回同樣的答案。
    """
    if category:
        wanted = category.strip().casefold()
        for folder in folders:
            if folder["name"].casefold() == wanted:
                return folder["name"]
    return UNCATEGORIZED
```

### 步驟 3：協定與 `OllamaVLM` 的 `understand()` 一起加上 `folders` 參數

同一個檔案，把 `VLMClient` 協定裡的方法簽名（原第 63 行）：

```python
    def understand(self, image_bytes: bytes, content_type: str) -> PhotoUnderstanding:
        ...
```

改成：

```python
    def understand(
        self, image_bytes: bytes, content_type: str, folders: list[dict]
    ) -> PhotoUnderstanding:
        ...
```

再把 `OllamaVLM.understand()`（原第 78〜80 行）的簽名與 docstring 改成：

```python
    def understand(
        self, image_bytes: bytes, content_type: str, folders: list[dict]
    ) -> PhotoUnderstanding:
        """看一張照片。任何失敗都回 understood=False，由上層轉成 422。

        folders＝現有資料夾清單，會被組進 prompt（design1.md §8）；
        仍然只有這一次看圖呼叫，沒有第二個分類模型。
        """
```

並把方法內組訊息那一行（原第 84 行）：

```python
                {"type": "text", "text": VLM_PROMPT},
```

改成：

```python
                {"type": "text", "text": build_vlm_prompt(folders)},
```

存檔後再跑一次單元測試：

```bash
pytest tests/unit/test_vlm_service_unit.py -v
```

預期最後一行：`12 passed`（改寫後的檔案共 12 個測試函式，比原本的 6 個淨增 6 個）。

### 步驟 4：`tests/fakes.py` 的 `FakeVLM` 簽名同步

假件必須跟協定長得一樣，否則正式路徑改了、測試路徑卻沒發現。打開 `tests/fakes.py`，把 `FakeVLM` 改成：

```python
class FakeVLM:
    """考試用的固定答案卡，不是正式看圖系統。

    測試會先指定「請當作收據、店名 Target」；understand() 照念，不呼叫 Ollama。
    沒給 result 時預設 understood=False（規格：看不懂 → 422、什麼都不存）。

    folders 參數只是為了與 VLMClient 協定一致（Phase 18 新增）：
    假件不會真的照著清單思考，但會把收到的清單記在 last_folders，
    讓測試可以驗「呼叫端真的把資料夾清單傳進去了」。
    """

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0
        self.last_folders: list[dict] | None = None

    def understand(
        self, image_bytes: bytes, content_type: str, folders: list[dict]
    ) -> PhotoUnderstanding:
        self.calls += 1
        self.last_folders = folders
        return self.result
```

### 步驟 5：呼叫端 `app/api/routers/photos.py` 傳入資料夾清單

打開 `app/api/routers/photos.py`，找到「② 看圖」那一段（第 38〜39 行）：

```python
    # ② 看圖
    understanding = vlm.understand(image_bytes, file.content_type)
```

改成：

```python
    # ② 看圖（把現有資料夾清單當變數注入 prompt——design1.md §8）
    #    仍然只有這一次看圖呼叫，沒有第二個分類模型。
    folders = photo_repository.list_folders()
    understanding = vlm.understand(image_bytes, file.content_type, folders)
```

`photo_repository` 在檔案第 10 行已經 import 過，不必再加。

> ⚠️ **本 phase 到此為止。** 不要在這裡呼叫 `clamp_category`、不要改 `insert_photo` 的 `category=understanding.category`、不要動回應。把建議接進流程是 **Phase 20**（那時 category 會一律寫「未分類」，並在回應加 `suggested_folder`）。現在就改會讓既有的上傳規格 7 條 Rule 直接變紅。

### 步驟 6：補一個整合測試，證明清單真的傳到了 VLM

打開 `tests/integration/test_upload_design_rules.py`，在檔案**最後面**加上下面這個測試。
（它用到的 `get_vlm`、`app`、`PhotoUnderstanding`、`FakeVLM`、`PNG_BYTES` 該檔第 12〜19 行都已經有了，**不必新增任何 import**。）

```python
# ---- design1.md §8：上傳時把現有資料夾清單當變數注入 VLM prompt ----
def test_上傳時把現有資料夾清單傳給看圖(client):
    """呼叫端必須真的去資料庫讀清單再傳進 understand()，不是傳空陣列了事。

    conftest 的 reset_tables 每個測試都會重播 design1.md §5 的預設六資料夾，
    所以這裡可以直接斷言那六個名稱。
    """
    fake = FakeVLM(
        PhotoUnderstanding(
            understood=True, text="在 Target 購買可樂的收據", category="收據",
            location="Target", items=["可樂"], content_time="2026-08-10",
        )
    )
    app.dependency_overrides[get_vlm] = lambda: fake

    response = client.post(
        "/photos", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )

    assert response.status_code == 201
    names = [folder["name"] for folder in fake.last_folders]
    assert names == ["未分類", "收據", "飲食", "風景", "文件", "其他"]
    # description 也要一起傳（prompt 需要它才寫得出「這個資料夾是裝什麼的」）
    assert all(folder["description"] for folder in fake.last_folders)
```

> 📌 這個測試上傳的是既有常數 `PNG_BYTES`（本檔第 19 行的假位元組）。本 phase 的上傳流程**還不會**用 Pillow 開圖，所以假位元組仍然可用；**Phase 19 會把這些常數統一換成真圖**。

### 步驟 7：全量回歸

```bash
pytest -q
```

預期：**基線顆數 ＋ 7**（單元 6 ＋ 整合 1），全綠。

特別確認既有的上傳規格 7 條 Rule 仍然全綠——`FakeVLM` 回的「收據」本來就在預設清單裡，而且本 phase 沒有改寫入行為，所以規格檔的每一個 Example 都不受影響：

```bash
pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v
```

預期：12 條 Rule、14 個例子全綠（顆數與開工前完全相同）。

### 步驟 8：真模型手動煙霧（選作，不進 CI）

想親眼看到 prompt 長什麼樣：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python - <<'PY'
from app.repositories import photo_repository
from app.services.vlm_service import build_vlm_prompt, clamp_category

folders = photo_repository.list_folders()
print(build_vlm_prompt(folders))
print("-" * 60)
for guess in ["收據", "  收據 ", "Receipt", "美食", None]:
    print(repr(guess), "→", clamp_category(guess, folders))
PY
```

預期：prompt 裡看得到六行 `- 名稱：說明`；下半段依序印出 `收據` / `收據` / `未分類` / `未分類` / `未分類`。
（這段連的是**正式庫**，只做讀取，不會寫入任何資料。）

---

## 驗收清單

- [ ] `app/services/vlm_service.py` 已無 `VLM_PROMPT` 常數，改為 `build_vlm_prompt(folders)`：
      ```bash
      grep -n "VLM_PROMPT" app/services/vlm_service.py || echo "OK：常數已移除"
      grep -n "def build_vlm_prompt\|def clamp_category" app/services/vlm_service.py
      ```
      預期：第一行印 `OK：常數已移除`；第二行印出兩個函式定義
- [ ] prompt 含 design1.md §8 的三句關鍵措辭（「現有資料夾」「禁止自創名稱」「不確定就填「未分類」」），且**保留** v4 的語言規則原文
- [ ] `VLMClient` 協定、`OllamaVLM.understand`、`FakeVLM.understand` 三處簽名一致（都有 `folders`）：
      ```bash
      grep -n -A1 "def understand" app/services/vlm_service.py tests/fakes.py
      ```
      預期：三處（協定、`OllamaVLM`、`FakeVLM`），每一處 `def understand(` 的**下一行**都看得到 `folders`
      （簽名改成多行寫法後，參數列在第二行，所以要用 `-A1` 連下一行一起看）
- [ ] `photos.py` 呼叫端會先讀清單再傳入：
      ```bash
      grep -n "list_folders()\|vlm.understand" app/api/routers/photos.py
      ```
      預期：兩行相鄰
- [ ] **本 phase 沒有把 clamp 結果落庫**（Phase 20 才做）：
      ```bash
      grep -n "clamp_category" app/api/routers/photos.py || echo "OK：clamp 還沒接進流程"
      ```
      預期印出 `OK：clamp 還沒接進流程`
- [ ] **沒有新增第二個模型**（design1.md §14 明文否決）：
      ```bash
      grep -rn "ChatOllama" app/ --include="*.py"
      ```
      預期只有 `app/services/vlm_service.py` 與 `app/services/ask_workflow.py` 既有的那幾處，數量與開工前相同
- [ ] `pytest tests/unit/test_vlm_service_unit.py -v` → `12 passed`
- [ ] `pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py -v` 全綠，顆數與開工前相同
- [ ] **全量 `pytest -q` 全綠**，顆數＝開工前基線 ＋ 7
- [ ] git commit：
      ```bash
      cd /Users/linjunting/personalDocAI
      git add app/services/vlm_service.py app/api/routers/photos.py \
              tests/fakes.py tests/unit/test_vlm_service_unit.py \
              tests/integration/test_upload_design_rules.py
      git commit -m "feat: Phase 18 VLM 資料夾推薦——prompt 注入現有資料夾清單（build_vlm_prompt）＋clamp_category 把清單外名稱夾成未分類，仍只有一次看圖呼叫，+7 tests"
      ```

---

## 常見問題

**Q1：為什麼不乾脆讓 VLM 直接回 `folder_id`（數字），省掉比對？**
因為模型對數字的穩定度遠低於文字，而且 `photo.category` 這個欄位本來就存名稱（既有的條件查詢 `category ILIKE` 靠它）。design1.md §6 明訂 `category` ＝資料夾 `name`，維持文字最省事。

**Q2：`clamp_category` 為什麼回「名稱」而不是「資料夾 dict」？**
契約就是這樣定的（回 `str`）。呼叫端（Phase 20）拿到名稱後，用 Phase 16 的 `find_folder_by_name()` 去換完整的資料夾資料。分工清楚：`vlm_service` 是純函式不碰資料庫，查資料庫是 repository 的事。

**Q3：清單裡同時有「收據」與「Receipt」兩個資料夾，模型回 `receipt`，會挑到哪一個？**
挑到 `Receipt`（大小寫不敏感命中）。挑不到「收據」——系統**不做跨語言翻譯對映**，這是 design.md §8.3 的已知限制，本增量沒有推翻它（design1.md §15 還特地重申了一次）。

**Q4：如果資料夾很多（比如 50 個），prompt 會不會太長？**
side project 不處理這個。真的多到影響品質時再說；現在為了假想的規模去做「只挑最相關的 N 個資料夾進 prompt」，就是過度設計。

**Q5：`FakeVLM` 加 `last_folders` 算不算「為了測試改產品程式碼」？**
不算——`tests/fakes.py` 本來就是測試程式碼。產品程式碼（`app/`）一行都沒有為了測試而改。

**Q6：`test_build_vlm_prompt_含所有資料夾名稱與說明` 為什麼要多塞一個「專案X」？**
因為這條測試要守的是「**清單是變數**」這個性質，不是「預設六個資料夾都在」。多塞一個沒被預先寫死的名稱，才證明得了函式真的是照著參數組 prompt。

**Q7：真模型還是常常自創名稱（例如「發票」），怎麼辦？**
那就是 `clamp_category` 發揮作用的時候——它會變成「未分類」，使用者在彈窗裡自己選（Phase 23）。**不要**為了讓模型更聽話而加重試、加第二次呼叫、加分類模型；design1.md §14 全部否決過了。真的想改善，只能調 prompt 措辭或換 `.env` 的 `VLM_MODEL`。

**Q8：改了協定簽名，Phase 08 那個真模型煙霧腳本 `scripts/check_embedding_dim.py` 會不會壞？**
不會。那支腳本只測 embedding 維度與相似度，沒有呼叫 `understand()`（可用 `grep -n "understand" scripts/check_embedding_dim.py` 確認，應該沒有輸出）。

---

## 完成後的專案狀態

VLM 現在是「**在選單裡挑一個**」，不再是「自由發明」：每次上傳都會把當下的資料夾清單（含使用者自建的）寫進 prompt，模型回來的名稱再經 `clamp_category` 夾回清單內，清單外一律變「未分類」。第二道保險是純函式，不依賴模型聽不聽話。

不過**這些成果目前還沒有出口**——上傳仍然照舊把 VLM 原本的 `category` 存進資料庫，回應也沒變。接下來 Phase 19 讓上傳真的存檔並開出讀圖端點，Phase 20 才把「一律先進未分類 ＋ 回傳 suggested_folder」這個新流程接起來。

測試累計 ＝ 開工前基線 ＋ **7**。
