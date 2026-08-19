# Phase 8：接上真實的 Ollama 模型（含實測向量維度與中英雙語煙霧測試）

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🔄 **2026-08-19 開工前更新**：對照專案現況修訂——(1) 測試累計數 11 過時 → **40**（Phase 07 結束）；(2) 步驟 6 原假設 CLAUDE.md 的「## 指令」是佔位節——實際已是完整版（Phase 04 收尾時更新過），改為**在既有指令碼區塊補一行**煙霧測試指令，不再附加重複章節；(3) 驗收 7「停 Ollama」改為 `OLLAMA_BASE_URL` 指死埠法（不動使用者常駐的 Ollama）；(4) psql 指令一律帶 `-p 5433`（非互動 shell 沒有 ~/.zshrc 的 `PGPORT`）；(5) 步驟 2／4 各補一個備援（截圖權限受限 → qlmanage 渲染 HTML 假收據；沙箱擋 localhost → in-process 走真依賴）。

**目標：** 把假的 AI 換成真的——用本機 Ollama 的 `gemma4` 真的看一張照片、用 `bge-m3` 真的產生向量，**實測 bge-m3 的向量維度**確認 `vector(1024)` 這個假設成立，並用中文與英文各跑一次向量確認多語能力。

---

## 前置條件

- 需要已完成的 phase：**Phase 7**（上傳規格 7 條 Rule 已全綠、測試累計 **40**）。
- 環境：Ollama 服務必須真的在跑，且 `gemma4` 與 `bge-m3` 都已下載完成。
  ```bash
  curl -s http://localhost:11434/api/tags | head -c 80
  ollama list
  ```
- 每次開工先執行：
  ```bash
  cd /Users/linjunting/personalDocAI && source .venv/bin/activate
  ```

---

## 這個 phase 在做什麼

到目前為止，AI 都是假的。程式碼裡雖然已經寫好了 `OllamaVLM`（底層是 LangChain 的 `ChatOllama`）與 `OllamaEmbeddings`，但從來沒有真的被呼叫過（唯一例外：Phase 6 驗收最後那個標明「可選」的真實上傳——做過的話你已經偷偷通電過一次）。這個 phase 就是正式的「第一次通電」。

**本 phase 不改任何 `app/` 的程式碼。** 真模型的接線在 Phase 5／6 的 `app/dependencies.py` 就完成了：`get_vlm()` 預設回傳 `OllamaVLM`、`get_embeddings()` 預設回傳 `OllamaEmbeddings`——只有測試才用 `dependency_overrides` 換成假件。所以這裡沒有任何開關要撥，要做的是新增一個實測腳本＋一連串手動操作，讓正式路徑第一次真的走到 Ollama。（唯一可能要改程式的情況：實測維度不是 1024，見步驟 1。）

design.md §14 把一件事標成**必須實作驗證的假設**：`bge-m3` 輸出 1024 維。這是資料表 `vector(1024)` 的依據，如果實際不是 1024，寫入會直接失敗。所以第一件事就是實測。

另外要確認兩件事：

1. 真模型的「結構化輸出」真的可用：我們要求模型只能回傳六個固定欄位，這在 Ollama 是靠 JSON schema 約束達成的。JSON schema＝一份描述「JSON 必須有哪些欄位、每個欄位是什麼型別」的規格；LangChain 的 `with_structured_output()` 底層就是把我們的 `PhotoUnderstanding` 轉成這種規格交給 Ollama。
2. **多語能力真的存在**：`bge-m3` 對中文與英文都要能產生向量，而且「意思相近的中英文句子」向量要比較接近——這是雙語支援的物理基礎（design.md §8.3）。步驟 1 的腳本會實際量一次。

最後，先把預期心態調好：**本地模型比雲端服務慢很多**——第一次呼叫要把好幾 GB 的模型載入記憶體，等 10〜60 秒都正常；**描述品質只求「足以 demo」**（design.md §14 明列的假設）——不滿意時換一個對中文較強的多模態模型（例如 Qwen 系列）即可，換模型＝只改 `.env` 的 `VLM_MODEL`，程式碼一行都不用動。

---

## ASCII 圖：兩條路早就都接好了，本 phase 第一次走「真」的那條

```
      app/dependencies.py 的注入點（Phase 5／6 已寫好，本 phase 不改程式碼）
      ┌───────────────────────────────────────────────┐
      │   get_vlm()     get_embeddings()    get_now() │
      └───────┬───────────────────────────────┬───────┘
              │                               │
  測試時（pytest）：                           │  正式執行（uvicorn／腳本）：
  dependency_overrides 換成假件               │  走預設值
  ── Phase 7 之前真的跑過的只有這條           │  ── ★本 phase 第一次真的走這條
              │                               │
              ▼                               ▼
   FakeVLM（照劇本回答）            OllamaVLM        ────┐
   FakeEmbeddings（決定論向量）     OllamaEmbeddings ────┤
   固定時鐘（固定時間）             None（上傳時間交給 DB now()）
                                                         │
                                                         ▼
                                 Ollama 本機服務（config.OLLAMA_BASE_URL
                                                 ＝ http://localhost:11434）
                                   ├ gemma4 ：看圖 → 文字＋四個欄位
                                   └ bge-m3 ：文字 → 一串數字（多語：中／英）
                                                本 phase 實測共幾個數字

  （本 phase 之後，測試依然全部用左邊的假件；右邊的真模型只做手動煙霧測試）
  追「使用者上傳」請只看右邊。左邊的 Fake 不是第二套看圖系統。
```

---

## 逐步驟操作

### 步驟 1：實測 `bge-m3` 的向量維度（順便量中英文的跨語言相似度）

建立 `scripts/check_embedding_dim.py`：

```python
"""實測 embedding 模型的向量維度，確認 config.EMBEDDING_DIM 設定正確，
順便量一次「中文句子 vs 英文同義句」的相似度，確認多語能力真的存在。

用法（在專案根目錄執行）：python scripts/check_embedding_dim.py
"""

import math
import sys
from pathlib import Path

# 用 `python scripts/check_embedding_dim.py` 執行時，Python 只會在 scripts/
# 資料夾裡找模組，會找不到 app 套件——把專案根目錄加進搜尋路徑就解決了。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config  # noqa: E402  （必須在改完搜尋路徑之後 import）
from app.services import indexing_service  # noqa: E402

中文句 = "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10"
英文句 = "Receipt from Target with Cola and Chips, dated 2026-08-10"
無關句 = "海邊的風景照"


def cosine(a: list[float], b: list[float]) -> float:
    """兩條向量的 cosine 相似度：1 代表方向完全一樣，0 代表毫無關係。"""
    dot = sum(x * y for x, y in zip(a, b))
    length = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / length if length else 0.0


def main() -> None:
    embeddings = indexing_service.build_ollama_embeddings()
    中文向量 = embeddings.embed_query(中文句)
    英文向量 = embeddings.embed_query(英文句)
    無關向量 = embeddings.embed_query(無關句)

    print(f"模型：{config.EMBEDDING_MODEL}")
    print(f"實測維度：{len(中文向量)}")
    print(f"設定維度（config.EMBEDDING_DIM）：{config.EMBEDDING_DIM}")
    print(f"前 5 個數字：{中文向量[:5]}")
    print(f"中英同義句相似度：{cosine(中文向量, 英文向量):.3f}")
    print(f"中文 vs 無關句相似度：{cosine(中文向量, 無關向量):.3f}")

    if len(中文向量) == config.EMBEDDING_DIM:
        print("✅ 維度一致，不用改任何東西")
    else:
        print("❌ 維度不一致！請照下面兩步修正：")
        print(f"   1. 把 app/core/config.py 的 EMBEDDING_DIM 改成 {len(中文向量)}")
        print(f"   2. 把 db/schema.sql 的 vector(1024) 改成 vector({len(中文向量)})，")
        print("      再執行 psql -d visual_memory -f db/schema.sql")
        print("      與 psql -d visual_memory_test -f db/schema.sql")


if __name__ == "__main__":
    main()
```

執行：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python scripts/check_embedding_dim.py
```

**如果印出 `❌ 維度不一致`**，照它說的兩步做：

```bash
# 假設實測是 768（示意）：
# 1) app/core/config.py：EMBEDDING_DIM = 768
# 2) db/schema.sql：vector(768)
psql -p 5433 -d visual_memory      -f db/schema.sql
psql -p 5433 -d visual_memory_test -f db/schema.sql
pytest -q     # 重跑一次，確認 40 passed 仍然成立
```

> `schema.sql` 開頭是 `DROP TABLE IF EXISTS photo;`，重跑會**清空資料表重建**。此時表裡只有測試留下的假資料，清掉沒有關係；假件測試會全數重跑，因為 `FakeEmbeddings` 的向量長度也是讀 `config.EMBEDDING_DIM`，所以會自動跟上新維度。

### 步驟 2：準備一張真的、看得懂內容的照片

用 macOS 內建指令截一張螢幕畫面當測試照片（畫面上有文字，比純色圖更容易讓模型講出東西）：

```bash
screencapture -x /tmp/real_photo.png
ls -lh /tmp/real_photo.png
```

（如果你手邊有真的收據照片更好，把路徑換成那張即可。有中文收據和英文收據各一張最理想——可以親眼看到「描述語言跟著照片走」。）

**備援（截圖權限受限、圖是全黑或 0 bytes 時）**：用 macOS 內建的 qlmanage 把一張 HTML「假收據」渲染成 PNG——內容可控，比截圖更像規格例子：

```bash
cat > /tmp/receipt.html <<'HTML'
<html><head><meta charset="utf-8"></head><body style="font-family:-apple-system;width:400px;padding:16px">
<h2>Target</h2><p>2026-08-10</p>
<table width="100%"><tr><td>可樂</td><td align="right">$25</td></tr>
<tr><td>洋芋片</td><td align="right">$40</td></tr></table>
<hr><p align="right"><b>總計 $65</b></p></body></html>
HTML
qlmanage -t -s 1024 -o /tmp /tmp/receipt.html   # 產生 /tmp/receipt.html.png
cp /tmp/receipt.html.png /tmp/real_photo.png
ls -lh /tmp/real_photo.png
```

### 步驟 3：真的呼叫一次看圖

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate

python - <<'PY'
import pathlib
from app.services.vlm_service import OllamaVLM

image = pathlib.Path("/tmp/real_photo.png").read_bytes()
result = OllamaVLM().understand(image, "image/png")

print("understood   :", result.understood)
print("text         :", result.text)
print("category     :", result.category)
print("location     :", result.location)
print("items        :", result.items)
print("content_time :", result.content_time)
PY
```

第一次執行會比較慢（模型要載入記憶體），可能要等 10〜60 秒。

### 步驟 4：真的跑一次完整上傳

```bash
# 視窗 A：啟動服務（用正式資料庫）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --port 8000
```

```bash
# 視窗 B：上傳（新視窗一樣要先 cd ＋啟用虛擬環境，最後的 python 指令才存在）
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
curl -s -X POST http://localhost:8000/photos \
  -F "file=@/tmp/real_photo.png;type=image/png" | python -m json.tool
```

真模型看圖需要時間，這個請求可能要等幾十秒才回應，是正常的。

**備援（環境擋 localhost 連線、curl 連不上時）**：改用 in-process 方式走**同一條**正式路徑（真 VLM、真 embedding、正式資料庫；只是少了 HTTP socket 這一層）：

```bash
python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app   # 不覆寫任何依賴＝走真模型與正式資料庫

with TestClient(app) as client:
    with open("/tmp/real_photo.png", "rb") as f:
        response = client.post(
            "/photos", files={"file": ("real_photo.png", f, "image/png")}
        )
print(response.status_code)
print(response.json())
PY
```

### 步驟 5：確認資料真的落地，而且向量是真的

```bash
psql -p 5433 -d visual_memory -c \
  "SELECT id, left(text, 40) AS text_head, category, location, items, content_time, uploaded_at, vector_dims(embedding) AS dims FROM photo ORDER BY id DESC LIMIT 3;"
```

（這筆是真實使用產生的資料，**保留**在正式庫即可——它就是產品的正常產出，之後的 phase 也用得上。）

### 步驟 6：記錄「真模型只做手動煙霧測試」的界線

在 `tests/` 底下**不要**加任何需要真 Ollama 的測試。design.md §11 明訂：真模型只做少量手動煙霧測試（含至少一個英文提問例子），不進驗收與 CI。理由是真 AI 的輸出不是決定論的，放進驗收會讓測試時好時壞。

把這件事寫進專案的 `CLAUDE.md`（供之後的人參考）。`CLAUDE.md` 的「## 指令」一節**已是完整版**（Phase 04 收尾時更新過，含開工、依賴、uvicorn、pytest、psql），所以**不要附加重複章節**——只在既有的指令碼區塊裡、`pytest -q` 那組之後補上這兩行：

```bash
# 手動煙霧測試（需要 Ollama 真的在跑；真模型不寫自動化測試、不進驗收與 CI）
python scripts/check_embedding_dim.py
```

（直接編輯 `/Users/linjunting/personalDocAI/CLAUDE.md` 的指令碼區塊即可，其餘內容一字不動。）

---

## 驗收標準

1. **維度實測與設定一致**
   ```bash
   cd /Users/linjunting/personalDocAI && source .venv/bin/activate
   python scripts/check_embedding_dim.py
   ```
   預期輸出中有一行 `✅ 維度一致，不用改任何東西`
   （若一開始不一致，照指示改完後重跑，必須看到這一行。）

2. **多語能力確認**（同一段輸出）
   - `中英同義句相似度` 明顯**高於** `中文 vs 無關句相似度`。
   - 參考值：同義句通常落在 0.6〜0.9，無關句通常明顯較低。實際數字會隨模型版本與句子而變，不必逐位對照，**重點是前者比後者大**——這代表 `bge-m3` 真的把中英文放進同一個語意空間，英文問題才有機會找到中文寫的照片。
   - 若兩個數字幾乎一樣（不論都偏高還是都偏低），代表模型沒有把「意思相近」和「無關」分開，回頭確認 `.env` 的 `EMBEDDING_MODEL` 是 `bge-m3`。

3. **真的看得懂一張照片**
   步驟 3 的輸出中，`understood` 為 `True`，且 `text` 是一句有意義的描述（不是空字串）——這兩點是本條的通過標準。描述語言理想上跟著照片內容走（中文畫面寫中文、英文畫面寫英文）；不一致時看常見問題 Q6，那是模型能力問題，不算本條驗收失敗。

4. **完整上傳成功，回傳 201 格式**
   步驟 4 的輸出應該長這樣（欄位值依照片而定）：
   ```json
   {
       "id": 1,
       "text": "螢幕畫面，顯示一個終端機視窗",
       "metadata": {
           "category": "螢幕截圖",
           "location": null,
           "items": [],
           "content_time": null
       }
   }
   ```
   重點：三個鍵 `id`／`text`／`metadata` 都在，`metadata` 剛好四個欄位。`id` 是正式資料庫的流水號，不一定是 `1`（例如 Phase 6 做過可選的真實上傳的話，號碼會往後排）。

5. **資料庫的向量維度正確**
   步驟 5 的輸出中，`dims` 欄位等於 `config.EMBEDDING_DIM`（預設 1024）。

6. **假件測試仍然全綠（沒有被真模型影響）**
   ```bash
   pytest -q
   ```
   預期：`40 passed`（**測試累計數：40**，本 phase 刻意不新增自動化測試）

7. **不需要 Ollama，測試依然全綠**
   ```bash
   OLLAMA_BASE_URL=http://localhost:9 python -m pytest tests -q
   ```
   預期：`40 passed`——把 Ollama 位址指到沒人聽的埠，測試依然全綠（AI 全部被假件取代）。這比停掉服務更乾淨，不影響本機常駐的 Ollama。（想真的停服務驗證也可以：`brew services stop ollama` → `pytest -q` → **務必** `brew services start ollama` 復原；若 Ollama 不是用 brew 管理，此法不適用。）

---

## 常見問題

**Q1：`python scripts/check_embedding_dim.py` 卡很久或連線失敗。**
Ollama 沒啟動，或模型還沒下載完。先 `curl -s http://localhost:11434/api/tags`，再 `ollama list` 確認 `bge-m3` 在清單裡。第一次呼叫模型需要把它載入記憶體，慢是正常的。

**Q2：`ModuleNotFoundError: No module named 'app'`（執行 scripts 時）。**
腳本最上面那段 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` 沒寫，或寫在 `from app...` 之後。它必須在所有 `app` 的 import 之前執行——這也是為什麼那兩行 import 要加 `# noqa: E402` 註解（告訴檢查工具「我知道 import 沒放在最上面，這是故意的」）。

**Q3：實測維度不是 1024。**
這正是 design.md 要求實測的原因，不是錯誤。照腳本印出的兩步改 `config.EMBEDDING_DIM` 與 `db/schema.sql`，重建兩個資料庫的資料表，再重跑 `pytest -q`。**只改這兩個地方**，其他程式碼都是讀常數的，不用動。

**Q4：真的上傳回 422「VLM 無法理解照片內容」。**
三種可能：(a) Ollama 沒啟動；(b) 你用的模型不支援看圖（純文字模型）；(c) 照片真的太模糊。先確認 (a)，再確認 (b)——執行 `ollama show gemma4` 看模型能力說明。若這個模型不支援視覺，改用支援視覺的模型並更新 `.env` 的 `VLM_MODEL`，**不用改任何程式碼**。

**Q5：結構化輸出報錯，或模型回了一段自由文字而不是六個欄位。**
小模型有時撐不住 schema 約束。先確認 `with_structured_output(PhotoUnderstanding)` 有加上；若仍不穩，換一個較大或對中文較好的多模態模型（改 `.env` 的 `VLM_MODEL` 即可，design.md 明講模型名稱是 config 常數、可自由換）。

**Q6：模型描述英文照片時卻用中文回答（或反過來）。**
prompt 的語言規則沒被遵守，通常是小模型的能力問題。先確認 `vlm_service.VLM_PROMPT` 裡的「語言規則（重要）」那段有寫進去（Phase 5 步驟 1）；若確實有寫還是不聽話，換模型。**不要**在程式裡加語言偵測與轉換——那是過度設計，而且 design.md §8.3 明訂不做翻譯。

**Q7：第一次呼叫很慢，之後就快了，正常嗎？**
正常。Ollama 會把模型留在記憶體一段時間，第二次之後就快很多。

**Q8：可不可以順便寫一個「用真模型跑」的自動化測試？**
**不要。** design.md §11 明訂真模型只做手動煙霧測試、不進驗收與 CI。真 AI 輸出不是決定論的，寫成自動化測試會時好時壞，最後只會被停用。

---

## 完成後的專案狀態

系統已經能用**真的本機 AI** 完成一次完整上傳：真的看圖、真的產生向量、真的寫進資料庫；向量維度已用實測確認，`bge-m3` 的中英跨語言能力也用相似度量過。自動化驗收測試維持 **40** 個全綠且不依賴任何外部服務。上傳功能到此完全做完，接下來要做「詢問」。
