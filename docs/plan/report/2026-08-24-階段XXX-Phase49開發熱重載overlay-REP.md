# 階段 XXX 完成報告：Phase 49 —— 開發熱重載 overlay `compose.dev.yaml`

> 日期：2026-08-24
> 計畫檔：`docs/plan/unfinish/phase-49-開發熱重載overlay.md`（23 個 checkbox 全數打勾）
> 產出：新增 `compose.dev.yaml` 一份；**`compose.yaml` 一個字未改、`app/` 一行未動**

---

## 1. 實作邏輯

兩種用途分成兩份檔案：

| | 常駐 `compose.yaml` | 開發 `+ compose.dev.yaml` |
|---|---|---|
| 啟動指令 | 無 `--reload`（Dockerfile 的 `CMD`） | 有 `--reload`（overlay 的 `command`） |
| 原始碼 | 打進映像 | bind-mount `./app` 進去 |
| volumes | data／certs／.env（3） | ＋`./app`（4） |
| `restart` | `unless-stopped`（開機自動拉起） | **`"no"`** |
| 改碼要生效 | 重建映像 | 存檔即可 |

`restart: "no"` 是關鍵：開發那份若設成 `unless-stopped`，
開機時 Docker 會把**帶 `--reload` 的版本**拉起來——正是 design4 §1.2 要避免的事。

---

## 2. 步驟與實測結果

### 2.1 合併結果驗證（`config`，只解析不啟動）

```text
app.command: [uvicorn, app.main:app, --host, 0.0.0.0, --port, "8000",
              --ssl-keyfile, certs/key.pem, --ssl-certfile, certs/cert.pem, --reload]  ✅
app.restart: "no"                                    ✅
app.volumes: 4 項（data／certs／.env／app）           ✅
db 段：與常駐 `docker compose config` 的輸出 **diff 零差異** ✅
```

最後一項是我額外加的檢查（計畫只要求「與常駐完全相同」，我用 `diff` 把它變成可驗證的斷言）。

### 2.2 切到開發模式

```text
docker compose -f compose.yaml stop app          → Stopped
docker compose -f compose.yaml -f compose.dev.yaml up -d
   → db Waiting → Healthy → app Starting → Started

docker compose ps --no-trunc：
  COMMAND: "uvicorn … --ssl-certfile certs/cert.pem --reload"   ✅ 有 --reload

docker compose logs app：
  Started reloader process [1] using WatchFiles     ← 熱重載真的掛上了
  Started server process [8]
```

### 2.3 ★ 實測熱重載（Python）

```text
改：app/main.py:41  return {"status": "ok"}  →  return {"status": "ok", "hot": "reload"}

log：WARNING: WatchFiles detected changes in 'app/main.py'. Reloading...   ✅
curl -k https://127.0.0.1:8000/health  →  {"status":"ok","hot":"reload"}   ✅

還原：cp /tmp/main.py.orig app/main.py
curl 再打一次  →  {"status":"ok"}                                          ✅
git status --short -- app/  →  空                                          ✅
```

**還原也走了一次重載**——順便證明這條路是雙向的，不是只有「改壞」那一次生效。
動筆前先 `cp app/main.py /tmp/main.py.orig` 備份，還原用 `cp` 覆蓋回去，
不靠手動改回字串（避免改回時打錯字而不自知）。

### 2.4 實測熱重載（HTML）

```text
改前（向容器要的內容）：點一張照片可以看大圖與完整說明。已定案的照片不能改資料夾。
改後（2 秒後再要一次）：點一張照片可以看大圖與完整說明。（熱重載測試）      ✅
還原後：              點一張照片可以看大圖與完整說明。已定案的照片不能改資料夾。 ✅
git status --short -- app/  →  空
```

**HTML 不需要等 uvicorn 重載**——靜態檔是每次請求現讀的，這正是計畫寫的行為。
我是直接 `curl` 容器要檔案來比對（不是看瀏覽器），所以連「是不是瀏覽器快取騙了我」
這個變因都排除掉了。

### 2.5 `logs -f` 的 `Ctrl+C`

```text
docker compose logs -f app &   → 送 SIGINT（＝Ctrl+C 送的訊號）
docker compose ps  →  app Up 34 seconds、db Up 40 seconds (healthy)   ✅ 容器繼續跑
curl -k …/health   →  {"status":"ok"}                                 ✅
```

### 2.6 切回常駐

```text
docker compose -f compose.yaml -f compose.dev.yaml stop   → app、db 都 Stopped
docker compose -f compose.yaml up -d                      → db Healthy → app Started

docker compose ps --no-trunc：
  COMMAND: "uvicorn … --ssl-certfile certs/cert.pem"      ✅ **沒有** --reload
curl -k …/health → {"status":"ok"}                        ✅
pytest -q → 402 passed, 2 skipped (20.06s)                ✅

restart 政策各在哪：
  compose.yaml:32     restart: unless-stopped   （db）
  compose.yaml:58     restart: unless-stopped   （app）
  compose.dev.yaml:14 restart: "no"                        ✅ 只有 dev 是 "no"
```

---

## 3. 遇到的問題與解法

| # | 問題 | 解法 |
|---|---|---|
| 1 | **計畫的驗收指令自己會誤報**：`grep -n -- "--reload" compose.yaml # 預期：沒有輸出`——實際輸出 1 行 | 那一行是 `compose.yaml` **第 3 行的警語註解**（「⚠ 永遠不要在這裡加 uvicorn 的 `--reload`」），而那句註解正是**計畫自己給的檔案內容**。所以這條檢查在照計畫做的情況下**必定誤報**。已把計畫的指令改成 `grep -n -- "--reload" compose.yaml \| grep -v "#"` 並附上校準說明——要驗的是「有沒有真的設定」，不是「檔案裡有沒有出現這七個字」 |
| 2 | 工作目錄再次漂掉（`source .venv/bin/activate` 找不到檔案） | 前一個指令 `cd` 到了 `docs/plan/unfinish`。這是本輪第三次踩同一個坑，之後每一條指令都以 `cd /Users/linjunting/personalDocAI &&` 開頭 |

**沒有踩到的坑**（計畫 §7 列的 9 條）：`volumes` 沒被誤解成整段覆寫（用 `config` 驗，
四項都在）、dev overlay 是 `restart: "no"`、`-f` 順序全程 `compose.dev.yaml` 在後、
知道 `logs -f` 的 `Ctrl+C` 不停服務（並實測）、
沒有在開發模式做鏡頭驗收、切換前一律先 `stop`、
`WATCHFILES_FORCE_POLLING` 沒有加（不需要——變動通知正常穿過 Docker Desktop 的檔案共享層）。

---

## 4. 測試方式

| 要證明的事 | 怎麼驗（都不靠肉眼看瀏覽器） |
|---|---|
| 合併結果正確 | `config` 輸出 ＋ `grep -c "type: bind"` ＝ 4 ＋ db 段 `diff` 零差異 |
| 開發模式真的生效 | `ps --no-trunc` 的完整 COMMAND ＋ log 裡的 `using WatchFiles` |
| Python 熱重載 | log 的 `WatchFiles detected changes` ＋ `curl` 前後回應不同 ＋ 還原後再變回來 |
| HTML 即時 | 直接 `curl` 容器要 `browse.html` 比對字串（排除瀏覽器快取變因） |
| `logs -f` 不停服務 | 送 SIGINT 後 `ps` ＋ `/health` |
| 常駐模式回得去 | `ps --no-trunc` 沒有 `--reload` ＋ `/health` ＋ `pytest` |
| 沒留下臨時修改 | `git status --short -- app/` 為空（兩次臨時修改都用 `cp` 備份／還原） |

---

## 5. 測試結果

**全數通過。** Phase 49 的 23 個 checkbox 全部打勾。

```text
新增檔案：compose.dev.yaml（?? 未追蹤）
compose.yaml：一個字未改（grep 驗；它是未追蹤檔，git diff 永遠是空的、證明不了事）
app/：一行未動（兩次熱重載實驗都已還原）
pytest：402 passed ＋ 2 skipped
現在的模式：常駐（COMMAND 無 --reload）
```

---

## 6. 給 Phase 50 的提醒

- 現在停在**常駐模式**且兩個容器都是 `Up`——Phase 50 §4.2 要測「重開 Docker Desktop 後自己回來」，
  前提正是「不能停在 `stop` 狀態」（`unless-stopped` 的字面意思是「除非你自己停過」）。
  這一點已經滿足，直接測即可。
- 真機鏡頭驗收**一定要用常駐模式**（開發模式每存一次檔配對就失效）。
