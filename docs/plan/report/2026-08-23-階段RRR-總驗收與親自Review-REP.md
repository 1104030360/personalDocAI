# 階段RRR REP：Phase 38〜44 總驗收與親自 Review

> 日期：2026-08-24
>
> 最終判定：**TECHNICAL PASS / G1 HUMAN PENDING / Phase 45 Docker NO-GO**
>
> 工作區狀態：dirty；**沒有 commit、沒有 release、沒有 Docker／compose 檔案**。

## 1. 範圍與完成定義

本報告是 Phase 38〜44／G1 的技術總驗收證據，範圍限於 localhost：

- Phase 38：依 id 讀一張照片的詳情端點。
- Phase 39：資料夾牆的唯讀照片詳情窗。
- Phase 40：待辦列在同頁開共用詳情窗。
- Phase 41〜43：五種 AI timing kind 與實際 runtime 接線。
- Phase 44：錯誤收尾、契約掃碼、全量回歸與 G1 驗收包。

不在本報告範圍：Phase 36 的手機、QR、hotspot 與無線鏡頭真機驗收。Phase 38〜44／G1
全部可走 localhost，不需要手機或公共網路以外的替代連線。

「TECHNICAL PASS」只表示下面的自動化、瀏覽器、真模型與技術 review 證據成立；design4 §7 的
G1 仍要求產品負責人親自走過 G1 包並明示：

> 甲乙沒問題，可以做 Docker。

在這句話出現以前，Phase 45 仍是 **NO-GO**。

## 2. TDD RED→GREEN 與 runtime hardening

### 2.1 瀏覽器 surface 與 modal hardening

最終瀏覽器實操先暴露、再以 regression contract 釘住以下行為：

1. 原圖、資料夾縮圖或待辦縮圖載入失敗時，破圖 icon 應降級成「無原圖／無縮圖」占位。
2. 長 CJK 文句、日期與數字單位在窄版不應不自然拆開。
3. `fetch` 直接失敗時，詳情窗要留在原頁並顯示友善、可操作的訊息；不外露 `TypeError`
   或開發時 debug 話術。
4. 開窗後背景節點必須 `inert`，Tab／Shift+Tab 只能在彈窗內循環；關窗須恢復背景原狀並把
   focus 還給觸發元素。
5. 每次開／關窗遞增 generation；舊 fetch、JSON 或 image error callback 晚到時必須忽略，
   不得覆蓋較新的 modal state。

較早的縮圖／CJK／network，以及後續 focus trap／背景 inert／stale-generation regression
均有實跑 RED→GREEN；未保留的精確秒數不補造。
最新數字單位 regression 有完整保留：

```text
.venv/bin/pytest tests/integration/test_design4_error_paths.py::test_手機版遺失縮圖與中文斷行都有保護 -q

RED   1 failed, 1 warning in 0.16s
      關鍵缺口：找不到 function 保護數字單位(text)
GREEN 1 passed, 1 warning in 0.07s
```

最小修正面：`browse.html` 的 image error fallback／數字單位保護、`style.css` 的 CJK 換行規則、
`folder_modal.js` 的短語保護、`photo_detail_modal.js` 的原圖 fallback 與友善網路錯誤。

### 2.2 Local structured output 真模型缺口

真模型 QA 發現本機 router 與 entity suggestion 原先使用
`ChatOllama.with_structured_output(...)` 的預設 `json_schema`，模型實際回了 Markdown，
沒有產生可驗證的結構化物件。

先加兩顆 focused regression：

```text
.venv/bin/pytest \
  tests/unit/test_ask_workflow_unit.py::test_本機路由用function_calling強制結構化輸出 \
  tests/unit/test_entity_suggestion_unit.py::test_本機實體建議用function_calling強制結構化輸出 -q

RED   2 failed
      關鍵 assertion：with_structured_output 收到 kwargs={}，
      預期 {"method": "function_calling"}
GREEN 2 passed
```

以官方 LangChain Docs MCP 與本機已安裝的 `langchain_ollama` 原始碼交叉核對後，只在本機
router／entity 的 structured-output 呼叫明寫 `method="function_calling"`。沒有改 prompt、
route fallback、entity 失敗回 `None` 的語意或雲端路徑。兩顆測試之後再被 targeted 112 顆與
full 402 顆覆蓋，且真模型 serial 重跑成功。後續再以 regression 明確要求：本機 entity 回
`None`、route 回 `None`／錯型別或雲端解析失敗都必須讓 timing `ok=false`；外層既有 fallback／
回 `None` 行為不變，不能把「呼叫完成但沒有有效結構化物件」誤記成成功。

### 2.3 Timing target、log 安全與隱私

最新 RED→GREEN 另釘住兩條邊界：

- 真實 VLM／embedding／router／answerer／entity client 會把 request 已選定的 backend／model
  封裝成 frozen `AiTarget` 傳給 `log_ai`。之後即使全域開關改變，該次呼叫仍使用並記錄原本
  的 immutable target，不會 relabel；只有 helper 單元測試與沒有 target 的假件走 config fallback。
- model／note 的換行、ANSI 與控制字元會被正規化成單行，過長值會截斷；看圖 note 只保留
  字數／數量／布林摘要，不寫入 AI 產生內容、prompt、secret、token、照片文字或其他 PII。

## 3. 自動化與靜態驗證

### 3.1 Phase 38〜44 targeted

```bash
.venv/bin/pytest tests/integration/test_photo_detail.py tests/unit/test_ai_timing_unit.py tests/integration/test_ai_timing_log.py tests/unit/test_entity_suggestion_unit.py tests/integration/test_design4_error_paths.py tests/unit/test_ask_workflow_unit.py tests/integration/test_ask_endpoint.py tests/integration/test_ask_feature.py tests/integration/test_ask_three_paths.py tests/integration/test_workflow_route.py -q
```

```text
112 passed, 2 skipped, 1 warning in 9.42s
```

### 3.2 三份規格 binder

```bash
.venv/bin/pytest tests/integration/test_upload_feature.py tests/integration/test_ask_feature.py tests/integration/test_camera_feature.py -q
```

```text
25 passed, 2 skipped, 1 warning in 2.19s
```

兩條 skip 仍是規格標記的 `@未實作`，沒有為了讓數字好看而提前摘標。

### 3.3 Full suite 與 dead-Ollama isolation

```bash
.venv/bin/pytest -q
```

```text
402 passed, 2 skipped, 1 warning in 27.73s
```

```bash
OLLAMA_BASE_URL=http://localhost:9 .venv/bin/pytest -q
```

```text
402 passed, 2 skipped, 1 warning in 26.47s
```

唯一 warning（四次 suite 的同一類）：

```text
StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.
```

這是已知 dependency deprecation，不把它隱藏成零 warning；本增量未升級測試依賴。

### 3.4 語法、diff 與契約掃碼

```bash
.venv/bin/python -m compileall -q app tests
node --check app/static/photo_detail_modal.js
node --check app/static/folder_modal.js
git diff --check
```

四條皆為 exit 0、無錯誤輸出。

```bash
git status --porcelain -- docs/spec/
```

無輸出：`docs/spec/` 乾淨。

```bash
rg -n 'ai_timing\.log_ai\(' app | wc -l
```

結果為 **8**；呼叫點仍恰好是 `vlm` 1、`embed` 3、`route` 1、`answer` 1、
`entity_suggest` 2。

OpenAPI 清點結果：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from app.main import app

verbs = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
paths = app.openapi()["paths"]
operations = [
    (path, method)
    for path, item in paths.items()
    for method in item
    if method.lower() in verbs
]
print(f"operations={len(operations)}")
print(f"DELETE={sum(method.lower() == 'delete' for _, method in operations)}")
print(f"GET /photos={'get' in paths.get('/photos', {})}")
print(f"GET /photos/{{photo_id}}={'get' in paths.get('/photos/{photo_id}', {})}")
PY
```

```text
operations=20
DELETE=0
GET /photos=False
GET /photos/{photo_id}=True
```

也就是依 id 的照片詳情存在，沒有「列出全部照片」，整個 API 沒有 DELETE。

Docker／compose 掃碼：

```bash
find . \
  -path './.git' -prune -o \
  -path './.venv' -prune -o \
  -type f \( -iname 'Dockerfile*' -o -iname '*compose*.yml' -o -iname '*compose*.yaml' -o -name '.dockerignore' \) -print
test ! -e db/docker-init
```

結果為無輸出、exit 0：專案根目錄與 G1 禁止範圍沒有 `compose.yaml`、
`compose.dev.yaml`、Dockerfile、`.dockerignore`、docker-compose 檔案或 `db/docker-init/`。

## 4. 最終瀏覽器證據

最終 pass 使用全新的 localhost browser session，共保留 **25 張 JPEG**：

`/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8/`

```bash
artifact_dir='/Users/linjunting/.codex/visualizations/2026/08/24/01a03246-133e-7a31-974d-3eb734ae0a9e/phase38-44-final-pass-8'
find "$artifact_dir" -maxdepth 1 -type f -name '*.jpg' -print0 | while IFS= read -r -d '' file; do
  dims=$(sips -g pixelWidth -g pixelHeight "$file" 2>/dev/null | awk '/pixelWidth:/{w=$2}/pixelHeight:/{h=$2}END{print w "x" h}')
  printf '%s\n' "$dims"
done | sort | uniq -c
```

結果為：

```text
11 1280x900
 7 375x812
 7 768x900
```

| Viewport／證據數 | 覆蓋面 |
|---|---|
| `1280x900`／11 張 | folders 列表、folder detail、資料夾入口詳情窗、舊照片 placeholder、tasks、兩種 task modal、pending、classification、照片 404、network error |
| `768x900`／7 張 | folders／detail／modal、tasks／modal、pending／classification |
| `375x812`／7 張 | 同上手機寬度流程 |

實操與畫面共同證明：

- folders／detail／兩個詳情窗入口／tasks／pending／classification 都走到。
- 待辦入口是 same-tab，不再開裸圖新分頁；待決定仍開歸類窗。
- null 原圖、檔案遺失、404、network failure 都有頁內降級或錯誤，不出現原生警告框。
- 長 CJK、日期、數字單位在桌面／平板／手機寬度均重驗。
- ×、Escape、backdrop 三種關閉方式皆有效。
- 開窗時背景 scroll lock 且其他節點 `inert`；Tab／Shift+Tab 在窗內循環，關窗後解除並把
  focus 還給原本觸發元素；stale generation 不會覆蓋較新視圖。

兩位獨立最終視覺 reviewer 結果一致：

| Reviewer | Verdict | Confidence | Coverage | Blocker |
|---|---|---|---:|---|
| `final_visual_qa_k` | PASS | HIGH | 25 of 25 | zero |
| `final_visual_qa_l` | PASS | HIGH | 25 of 25 | zero |

因此**技術視覺 gate 完成**；這不等於產品負責人已勾 G1 B／D／E。

## 5. 真模型 runtime 證據

以下是 localhost serial QA 的實際計時；全部有效 run 的結束行均為 `ok=true`。
秒數只代表該次執行，不是 SLA。

### 5.1 本機

| 路徑 | Kind／model／秒數 | 契約結果 |
|---|---|---|
| 單圖上傳（最新重跑） | VLM `gemma4:e2b` 33.1s；embed `bge-m3` 2.4s | 看圖與向量各一組 |
| 兩頁 PDF 第 1 頁 | VLM 29.2s；embed 0.1s | 每頁獨立計時 |
| 兩頁 PDF 第 2 頁 | VLM 26.1s；embed 0.1s | 每頁獨立計時 |
| 資料夾歸類 | embed `bge-m3` 0.1s | 只有 embed，沒有 VLM |
| 語意詢問（最新重跑） | route `gemma4:e2b-mlx` 33.4s；embed `bge-m3` 0.5s；answer 14.0s | `vector semantic search` |
| metadata 詢問 | route 19.5s；answer 11.1s | `metadata search`，正確沒有 embed |
| 實體建議（最新重跑） | entity 17.6s | 建議成功 |

### 5.2 雲端文字／看圖，本機向量

| 路徑 | Kind／model／秒數 | 契約結果 |
|---|---|---|
| 單圖上傳 | cloud VLM `gemma4` 7.1s；local embed `bge-m3` 0.4s | VLM 切雲端，向量仍留本機 |
| 語意詢問（最新重跑） | cloud route 4.0s；local embed 0.5s；cloud answer 3.2s | `vector semantic search` |
| 實體建議（最新重跑） | cloud entity 4.3s | 建議成功 |

## 6. 無效證據與取代規則

初次本機 entity suggestion QA 與 `pytest` 同時執行；pytest fixture 會 truncate 共用的
`PersonalDocAI_test`，使 runtime 在資料被清空的窗口讀到 404。這次觀察**無效**，不能歸因為
產品缺陷，也不能拿來當 PASS／FAIL。

停止並行測試後，以乾淨 serial runtime 重跑；最新 entity suggestion 17.6s、`ok=true` 的結果
取代前次觀察。後續真模型證據皆採 serial，以免共用測試資料庫再次污染 runtime。

## 7. 工具與證據來源

- CodeGraph MCP：用於對照照片上傳／PDF／歸類、詢問 route／retrieve／answer、實體建議的
  實際 code path，避免只靠檔名猜接線位置。
- 官方 LangChain Docs MCP＋本機已安裝套件原始碼：用於確認 ChatOllama structured-output
  method 選項，再以 regression 與真 runtime 驗證 `function_calling` 修正。
- Browser／network／console：用於走可見 user surface、same-tab、error fallback、responsive、
  focus trap、背景 inert、focus restore、stale generation 與 scroll 行為；最終輸出固定在上列
  25 張 pass-8 artifact。
- pytest、OpenAPI、`rg`、`compileall`、Node syntax check、`git diff --check`：用於可重現的
  contract、回歸與靜態證據。

本次報告與 timing log 沒有記錄 secret、token、API key、prompt、AI 產生內容、私人照片內容
或其他 PII；模型與 backend 名稱、公開 localhost 路徑、測試數字與秒數足以支撐驗收。

## 8. 發布與人工閘門

目前成立：

- 技術測試、技術視覺 gate、真模型 self-QA：**PASS**。
- G1 產品負責人 B／C／D／E：**尚未親自勾選**。
- Phase 45／Docker：**NO-GO**。
- Git：工作樹 dirty、沒有 commit。
- Release：沒有 build artifact 發布、沒有部署、沒有 release。

產品負責人驗收前，如已有舊 uvicorn instance，先停止它，再重新啟動：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

然後依 `2026-08-23-G1驗收包-請產品負責人確認.md` 親自走 B〜D，最後才決定是否勾 E 並說出
精確句子「甲乙沒問題，可以做 Docker」。在那之前，不建立 Docker／compose 檔案、不執行
Phase 45、不 commit、不 release。
