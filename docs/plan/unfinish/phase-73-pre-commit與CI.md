# Phase 73：pre-commit（ruff）與 GitHub Actions CI

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事。
> 想「順便加 eslint／Husky／coverage 門檻／CodeQL／Dependabot／Docker build job」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 每次 `git commit` 自動整理 Python 的格式與 lint；每次 `git push` 由 GitHub Actions 再驗一次（format check + lint + 全量 pytest）。不管 JS／HTML／CSS，不把 pytest 放進 pre-commit，不起 Redis／Ollama／app 容器。

---

## 0. 執行狀態（2026-09-01 更新：**Phase 73 全部完成**）

| 步驟 | 狀態 |
|---|---|
| §6.1 本機基線 | ✅ `pytest -q` = **543 passed ＋ 0 skipped** |
| §6.2〜6.3 ruff 設定＋一次 format | ✅ **commit `902360c`**（68 個 `.py` 重排、6 個 I001 ＋ 1 個 F541 修掉；顆數不變） |
| §6.4 pre-commit | ✅ **commit `6df5fc6`**（含 `pre-commit install` 與擋 commit 的煙霧實測） |
| §6.5 GitHub Actions | ✅ **commit `4269985`**（`ci: GitHub Actions 跑 ruff check／format 與 pytest`）。workflow ＋ `conftest.py` 改 `127.0.0.1` ＋ CLAUDE.md 補 CI 段；另把 `requirements.txt` 的 ruff 加上上限 `<0.17`（理由見 §6.5 註記） |
| §6.6 建 remote 並推 | ✅ **已由產品負責人 2026-08-28 完成**。`origin` ＝ `https://github.com/1104030360/personalDocAI.git`、預設分支 **`main`**、GitHub Actions job `test` **已綠兩次**（詳見改寫後的 §6.6） |
| 之後追加的一筆 | ✅ **commit `a53ab57`**（`chore: pytest 設定檔merge 進project.toml, delete pytest.ini`）：原 `pytest.ini` 的三行併進 `pyproject.toml` 的 `[tool.pytest.ini_options]`，根目錄少一個檔。**§4 檔案地圖與 §6.2 的 `pyproject.toml` 區塊已照這一筆更新** |

**剩下什麼：只剩歸檔。** 產品負責人下一次 commit 時把本檔從 `docs/plan/unfinish/` `git mv` 到
`docs/plan/finish/`（§8；增量六期間**不由 agent 搬檔**，見 §8 那一條）。

> ⚠️ **兩處與原計畫不同，是事實不是待辦，不要「改回去」也不要建議改：**
>
> | 原計畫寫的 | 實際落地 | 說明 |
> |---|---|---|
> | 建 **private** repo（§3、§6.6、§10） | repo 是 **PUBLIC** | 產品負責人的選擇。本檔提到 private 的每一處都已就地標註「原計畫 vs 事實」；`.env`／`certs/`／`data/` 仍然全在 `.gitignore` 裡（§6.6 的檢查步驟已實走） |
> | 分支 `master` | 分支 **`main`** | 本檔已全數改成 `main`（總覽 §7 鐵律 12 也是這樣寫） |

**§6.5 已做的本機預演**（CI 上跑不到之前，能在本機驗的都驗了）：

| 驗什麼 | 怎麼驗 | 結果 |
|---|---|---|
| 改 `127.0.0.1` 有沒有弄壞本機 | `pytest -q` | ✅ 543 passed |
| CI 上**沒有 `.env`** 會不會紅 | 先把變數設成 CI 的預設值再跑（`load_dotenv()` 預設不覆蓋既有環境變數，等同沒有 `.env`；**不必動那個檔**） | ✅ 543 passed |
| workflow YAML 合不合法 | `yaml.safe_load` 解析並印出 job／steps／service | ✅ 結構正確、`POSTGRES_DB` 大小寫沒被 YAML 轉掉 |
| 有沒有樣板注入面 | `grep '${{'` | ✅ 0 個（整份 workflow 不吃任何外部輸入） |
| CI 的兩句 ruff | `ruff format --check` ＋ `ruff check` | ✅ 98 files already formatted／All checks passed |

**當時剩下唯一驗不到的**：Actions runner 上的 Postgres service、`apt-get install postgresql-client`、
以及 `psql -f db/schema.sql` 這三步。那要真的 push 一次才知道（§6.6）——
**2026-08-28 已經真的推過，三步全綠**（見改寫後的 §6.6）。

⚠️ **§6.2／§6.4 的兩個設定檔區塊已於 2026-08-27 依實測修正**（原草稿有四個會安靜壞掉的錯，
逐項見各區塊底下的「⚠ 與原草稿的差異」）。**要照著做的話請用改過的版本，不要用 git 歷史裡的舊版。**

**為什麼要做這個：**

增量五（Phase 52〜72）已 commit（`39e1c7e`）。本機 `pytest -q` 能綠，但那是「這台 Mac、這個 venv、這個 Docker db」的綠。換一台乾淨機器（或之後改碼改壞）沒有自動後盾。

產品負責人要的流程是：

```text
pre-commit
  ├─ format check
  └─ lint check
      ↓
git push
      ↓
CI
  ├─ lint check
  ├─ format check
  └─ tests
```

對這個 repo 的落地方式：**不是 Husky**（那是 Node 專案的 hook 工具，本專案沒有 `package.json`）。Python 對應物是套件 `pre-commit`，hook 裡跑 **ruff**（format 與 lint 同一把工具）。CI 跑同一套指令的「只檢查、不改檔」版本，再加上 pytest。

**2026-08-27 已拍板（產品負責人）：**

| 題 | 決定 |
|---|---|
| JS／HTML／CSS 要不要 lint | **不管**。只跑 Python |
| 既有 ~87 個 `.py` 沒 formatter | **允許一次 `ruff format`（外加 `check --fix`）打進全部 Python，獨立一筆 commit** |
| 與增量五的順序 | 增量五**已經 commit**。本 phase 從乾淨 `main` 開工 |

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| git hook | `git commit`／`git push` 時 git 自動跑的小腳本。本 phase 只用 **commit 時** 那一個 |
| pre-commit（套件） | Python 的 hook 管理器。設定寫在 `.pre-commit-config.yaml`；每人本機跑一次 `pre-commit install` 才會掛上 |
| Husky | Node 生態的 hook 工具。**本專案不用** |
| ruff | 一個 Rust 寫的 Python linter + formatter。取代 black + flake8 + isort 三套 |
| `ruff format` | 改檔：把空白、換行、引號整理成統一風格 |
| `ruff format --check` | 不改檔：格式不對就失敗（給 CI 用） |
| `ruff check` | lint：抓未使用變數、語法級問題、import 順序等 |
| `ruff check --fix` | lint 且自動修能修的（給 hook 用） |
| CI（GitHub Actions） | 程式推上 GitHub 之後，GitHub 用一台乾淨的 Ubuntu 虛擬機重跑指定指令 |
| service container | Actions 順便起的附屬容器。本 phase 只起 pgvector，映到 5433，對齊 `tests/conftest.py` |
| staged | `git add` 之後、還沒 commit 的那些檔。hook 預設只看這些，不是全庫 |

本地 hook **會改檔**（改完你再 `git add` 重 commit）。CI **不准改檔**，格式不對就紅。這樣才不會出現「本機過、遠端偷偷改碼」。

---

## 1. 對應關係（沒有 designN 章節）

本 phase **不是**某個 `docs/design/design*.md` 的產品增量。它是工程後盾，約束來自：

- 測試契約：`tests/conftest.py` 把測試庫寫死成 `postgresql://postgres@127.0.0.1:5433/PersonalDocAI_test`（開工當時是 `localhost`，由本 phase §6.5 改成 `127.0.0.1`）；四道 autouse 安全網讓 pytest **不連 Redis、不啟動 Celery、不打 Ollama、不寫專案 `data/`**。
- 測試庫結構：`db/schema.sql`（CI 的空庫要灌一次）。
- 依賴風格：`requirements.txt` 用 `>=`（與 pytest 同一區追加 ruff／pre-commit，不另開 lock）。
- 前端約束：零框架、零打包——所以 **不引入 Node／eslint／prettier**。

---

## 2. 前置條件

> 📌 **以下是 2026-08-27 開工當下的狀態，留作紀錄。** 本 phase 已全部做完
> （§0），所以現在這四項的實況全都反過來了：三個設定檔都在、`origin` 也接上了。

- 增量五已在 `main`（`39e1c7e` 或之後），工作區乾淨。
- 本機 Docker 的 `db` 是 `Up (healthy)`（pytest 需要）。
- **還沒有** `.github/`、`pyproject.toml`、`.pre-commit-config.yaml`（2026-08-27 實查：無）。
- **還沒有 git remote**（2026-08-27 實查：`.git/config` 無 `[remote]`）。Task 6 才建 GitHub repo；沒 push 就沒有 Actions。

開工前實查基線：

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps          # db 要 Up (healthy)
pytest -q                  # 增量五收官實測 543 passed ＋ 0 skipped；以當下實查為準
git status --short         # 預期空
ls pyproject.toml .pre-commit-config.yaml .github/workflows/test.yml 2>/dev/null
                           # 預期「No such file」（三個都還沒建）
```

---

## 3. 範圍

### 做

- 新增 `pyproject.toml`（只寫工具設定 `[tool.ruff]`，不當套件發行設定；**之後 commit `a53ab57` 又把原 `pytest.ini` 的三行併進來成 `[tool.pytest.ini_options]`**，所以實檔現在是「ruff ＋ pytest 兩套設定」）。
- `requirements.txt` 測試區加 `ruff`、`pre-commit`。
- 一次 format + 自動修 lint，獨立風格 commit；`pytest -q` 顆數不變。
- 新增 `.pre-commit-config.yaml`；本機 `pre-commit install`。
- 新增 `.github/workflows/test.yml`：format `--check` → lint → 灌 schema → pytest。
- `tests/conftest.py` 的 host 從 `localhost` 改成 `127.0.0.1`（CI Ubuntu 上 `localhost` 可能先走 IPv6 `::1`，Postgres service 只映 IPv4）。
- `CLAUDE.md` 指令區補短段：新 clone 要 `pre-commit install`；CI 在驗什麼。
- 建 GitHub repo、加上 `origin`、push（需產品負責人明示才由 agent 執行 `gh repo create`／`git push`）。
  ⚠ 原計畫寫的是 **private**；**實際落地是 PUBLIC**（產品負責人 2026-08-28 的選擇，見 §0）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| Husky、lint-staged、prettier、eslint、`package.json` | 本專案不是 Node；已拍板只管 Python |
| 把 pytest 放進 pre-commit | 543 顆 + 要 Postgres；沒開 Docker 的人連 commit 都做不了 |
| Redis／Celery worker／Ollama 進 CI | 測試安全網已經擋掉；CI 不需要 |
| `docker compose up`、建 app 映像、HTTPS 憑證 | 那是本機／正式跑法，不是 pytest 契約 |
| coverage 門檻、CodeQL、Dependabot、多 Python 版本矩陣 | 菜單項目，不是現在的痛 |
| 在 CI 跑 `pre-commit run --all-files` | 多一層包裝；直接 `ruff` 與 hook 等價且好讀 |
| 自動 commit 回修格式的 bot | side project 不需要 |
| 開 `N`（pep8-naming） | 測試有中文名稱（例如 `記帳假派工`），會一片紅 |
| 改 `app/static/*`、`.feature`、SQL、compose | 超出拍板範圍 |
| `docker compose down -v` | 刪 volume ＝ 刪正式庫 |

### 建議的四筆 commit（不要混）

1. ✅ `style: 全庫套用 ruff format 與 E/F/I`（pyproject + requirements + 所有被改到的 `.py`）→ `902360c`
2. ✅ `chore: 加 pre-commit（ruff format + lint）` → `6df5fc6`
3. ✅ `ci: GitHub Actions 跑 ruff 與 pytest`（workflow + conftest 一行 + CLAUDE.md 短段）→ `4269985`
   （實際 commit 標題是 `ci: GitHub Actions 跑 ruff check／format 與 pytest`）
4. ✅ 遠端：`gh repo create` + `git push`（**不是** commit；需明示授權）→ 產品負責人 2026-08-28 自己做了（§6.6）

---

## 4. 檔案地圖

| 檔案 | 職責 |
|---|---|
| `pyproject.toml`（新） | ruff 的 line-length、規則、掃描目錄。**commit `a53ab57` 之後另含 `[tool.pytest.ini_options]`**（`testpaths` / `python_files`，原本住在 `pytest.ini`——那個檔已刪） |
| `.pre-commit-config.yaml`（新） | hook 清單；`rev` 與本機 ruff 大版對齊 |
| `.github/workflows/test.yml`（新） | CI：format check → lint → pytest |
| `requirements.txt` | 加 `ruff`、`pre-commit`（與 pytest 同一區） |
| `tests/conftest.py` | `localhost` → `127.0.0.1`（一行） |
| `CLAUDE.md` 指令區 | 補 `pre-commit install` 與 CI 等價指令 |
| `app/`、`tests/`、`scripts/` 的 `.py` | **只在風格 commit** 被 ruff 改到，行為不變 |

---

## 5. 實際指令對照（你的圖）

```text
git commit
  └─ .git/hooks/pre-commit     ← pre-commit 套件安裝，不進版控
        ├─ ruff format         ← 會改 staged 的 .py
        └─ ruff check --fix    ← 能自動修的會修；修不掉 → commit 被擋
git push
  └─ GitHub Actions job `ci`
        ├─ ruff format --check app tests scripts
        ├─ ruff check app tests scripts
        └─ pytest -q           ← 要 pgvector:5433 + schema.sql
```

---

## 6. 實作步驟

### 6.1 本機基線（還沒動工具前必須綠）

- [ ] `db` 容器 healthy：`docker compose ps`
- [ ] `source .venv/bin/activate && pytest -q`
- [ ] 記下顆數（預期 543 passed、0 skipped；以實查為準）。**若紅，先修產品／測試，不要開始裝 ruff。**

### 6.2 寫 ruff 設定並安裝

- [ ] 在 `requirements.txt` 的「測試」區、`httpx` 那一行後面追加：

```text
ruff>=0.16                # Python linter + formatter（pre-commit hook 與手動指令共用）
pre-commit>=4.0           # git commit hook 管理器；每人 clone 後跑一次 pre-commit install
```

⚠ **下限是 `0.16` 不是草稿寫的 `0.12`**：整庫的格式基線是 **0.16.5** 跑出來的，
而 formatter 的輸出會隨版本演進。裝到更舊的 ruff 會把格式「反著改回去」，
於是每個人 commit 都在互相覆蓋。

- [ ] 在專案根目錄新建 `pyproject.toml`（不要加 `[project]`／build-system——我們不是要發行套件）：

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
src = ["."]
extend-exclude = ["data", "certs"]

[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

# ↓ 這一段**不是本 phase 加的**，是之後的 commit `a53ab57` 把 pytest.ini 併進來的。
#   放在這裡是為了讓「檔案地圖 vs 實檔」對得起來——照本 phase 做的時候不必先寫它。
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

（實際落地的檔案有大段中文註解解釋每一行的理由，這裡只列骨架。
`[tool.pytest.ini_options]` 那一段的註解記著兩個坑：pytest 8 讀的是
`[tool.pytest.ini_options]` 而不是 pytest 9 的 `[tool.pytest]`；清單要用 TOML 陣列，
寫成字串 `"tests"` 在部分版本會被當成單一奇怪的路徑。）

規則說明（寫死，不要開更多）：

| 代碼 | 是什麼 |
|---|---|
| `E` | pycodestyle（除 E501 外：import 位置 E4、語句層問題 E7、語法錯誤 E9） |
| `F` | pyflakes（未使用變數、未定義名稱——真的可能是 bug） |
| `I` | isort（import 分組與排序） |

行寬 100 而不是 ruff 預設 88：中文註解多，88 會折很多行、風格 diff 更吵。

#### ⚠ 與原草稿的差異（三項，都是實測後修正）

| # | 草稿寫的 | 實測會發生什麼 | 改成 |
|---|---|---|---|
| 1 | `src = ["app", "tests", "scripts"]` | `src` 的意思是「**去哪裡找**自家程式」，不是「要檢查哪些目錄」。三個資料夾都躺在專案根目錄底下，寫成這樣等於叫 ruff 去 `app/app`、`app/tests` 裡面找 → `tests.*` 被歸類成第三方套件 → **每個測試檔**的 `from app...` 與 `from tests...` 中間都會被硬塞一行空行。實測 I001 從 **44 條變 6 條**，那 38 條全是這個設定造出來的假問題 | `src = ["."]` |
| 2 | `exclude = [...]` | ruff 的 `exclude` 是**整包取代**內建排除清單，`.git`／`.venv`／`__pycache__`／`.pytest_cache` 會一起失去保護。官方文件明寫建議用 `extend-`（<https://docs.astral.sh/ruff/settings>） | `extend-exclude`（`.venv` 可以拿掉，內建那份已經有了） |
| 3 | 沒有 `ignore` | 草稿說「E501 多半下一步 format 會吃掉」——**這句是錯的**。詳見下面一格 | 加 `ignore = ["E501"]` |

**為什麼一定要關 E501：**

1. `ruff format` **不重排註解、docstring 與字串**。實測 6 條 E501 全在這三種地方，
   format 之後一條都沒少。
2. 其中 **4 條在 docstring 裡面**，那種行**連 `# noqa: E501` 都寫不進去**——
   寫了會變成字串內容的一部分。要壓只能整檔 `per-file-ignores`，比直接關掉更醜。
   （其中兩條是 `test_design4_error_paths.py`／`test_design5_error_paths.py`
   docstring 裡的 markdown 對照表，最長那行寬 143，重排就毀了表格。）
3. **ruff 把中日韓文字算成寬度 2**（實測：76 個字元的中文行被判定為寬度 101），
   所以 `line-length = 100` 其實只夠 **50 個中文字**。本專案註解與 docstring
   大量是中文，開著會天天紅——正好違背草稿選 100 的原始理由。
4. ruff **官方預設的規則集本來就不含 E501**，理由正是「行寬交給 formatter 管」
   （<https://docs.astral.sh/ruff/tutorial> 明寫要 `extend-select = ["E501"]` 才會開）。

程式碼本身的行寬仍然有人管——由 `line-length = 100` 交給 formatter 執行。

- [ ] 安裝：

```bash
uv pip install -r requirements.txt
ruff --version
```

把印出來的版本號記下來（例如 `ruff 0.12.11`），§6.4 的 `rev: v0.12.11` 要跟它對齊。

- [ ] 先看會炸幾條、**還沒改檔**：

```bash
ruff check app tests scripts --statistics
```

`E501`（行太長）多半下一步 format 會吃掉。若有大量 `F401`（未使用 import）或其他修不掉的，§6.3 再決定手修或在 `pyproject.toml` 加**具名** ignore——禁止 `--exit-zero` 把失敗藏起來。

### 6.3 一次 format + 自動修（獨立風格 commit）

這步會碰到最多檔。只動 `.py`。

- [ ] 改檔：

```bash
ruff format app tests scripts
ruff check app tests scripts --fix
```

- [ ] 確認 lint 清零：

```bash
ruff check app tests scripts
```

預期：exit 0、無輸出。若還有，逐條手修或加明確 ignore（例如某個測試檔的合理例外），**不要**把規則整包關掉。

- [ ] 保險絲：import 重排理論上可能踩到循環 import。

```bash
pytest -q
```

預期：顆數與 §6.1 相同、0 skipped。

- [ ] 可選但建議：format／lint 的「只檢查」指令也要綠（之後 CI 就是這兩句）：

```bash
ruff format --check app tests scripts
ruff check app tests scripts
```

- [ ] Commit 1（hook 這時還沒裝，不會被擋）：

```bash
git add pyproject.toml requirements.txt app tests scripts
git commit -m "$(cat <<'EOF'
style: 全庫套用 ruff format 與 E/F/I

讓後續 pre-commit 與 CI 的 format/lint check 有乾淨基線，不夾帶產品行為變更。
EOF
)"
```

`git add app tests scripts` 只會把被改到的 `.py` 送進去；不要 `git add -A`（以免把無關未追蹤檔捲進來）。

### 6.4 裝 pre-commit hook

- [ ] 新建 `.pre-commit-config.yaml`。`rev` 把 `0.12.11` 換成 §6.2 `ruff --version` 的數字，前面加 `v`：

```yaml
# 本地 git commit 時跑。CI 不靠這個檔執行（CI 直接呼叫 ruff CLI）。
# rev 必須與本機 `ruff --version` 對齊，否則會出現「本機過、CI 紅」。
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.5
    hooks:
      # 順序有意義：先 lint（--fix）再 format
      - id: ruff-check
        args: [--fix]
        types_or: [python, pyi]

      - id: ruff-format
        types_or: [python, pyi]      # ← 這一行不能省，理由見下
```

#### ⚠ 與原草稿的差異（三項，查上游 v0.16.5 的 `.pre-commit-hooks.yaml` 與官方文件後修正）

| # | 草稿寫的 | 實測會發生什麼 | 改成 |
|---|---|---|---|
| 1 | 兩個 hook 都沒寫 `types_or` | 🚨 **本 phase 最容易安靜壞掉的一個坑。** 上游 `ruff-format` 的預設是 `[python, pyi, jupyter, markdown]`——**含 markdown**。ruff 0.16 會重排 `.md` 裡的 ```` ```python ```` 區塊。實測本 repo **39 份 `.md` 會被改到**，包含 `docs/design/design.md` 與整批已歸檔的 `docs/plan/finish/phase-*.md`（那些是歷史紀錄，不該被工具動到）。而且它只在「那份 `.md` 剛好被 `git add`」時發作，平常完全看不出來 | 兩個 hook 都釘 `types_or: [python, pyi]` |
| 2 | `ruff-format` 排在 `ruff --fix` 前面 | 官方 integrations 文件明寫：**用 `--fix` 時 lint hook 要排在 formatter 前面**，因為自動修完的程式碼可能需要重新排版 | 對調 |
| 3 | `- id: ruff` | v0.16.5 的 `.pre-commit-hooks.yaml` 已把 `ruff` 標成 **legacy alias**（`name: ruff (legacy alias)`） | `- id: ruff-check` |

**`rev` 與 `requirements.txt` 是兩顆不同的 ruff**：pre-commit 會自己下載 `rev` 那一版來跑，
**不是**用 `.venv` 裡那顆。升級要兩個檔一起改，改完重跑一次
`ruff format app tests scripts` 確認沒有新的格式差異。

- [ ] 掛到這台機器的 git（**不進版控**，只改 `.git/hooks/pre-commit`）：

```bash
pre-commit install
```

換電腦／重新 clone 都要再跑一次。沒跑的人仍能 `git commit`；那時要靠 CI 紅燈擋。

- [ ] 煙霧（做完一定還原，不要把髒碼留下）：

  1. 在任一已追蹤的 `.py`（例如 `app/core/config.py` 末尾）加兩行多餘空行，或加 `import os` 造成重複。
  2. `git add` 該檔後 `git commit -m "tmp: hook smoke"`。
  3. 預期：hook 自動改檔，第一次 commit 可能失敗並提示 re-stage；`git add` 再 commit 才過。或 hook 直接擋下。
  4. `git reset --soft HEAD~1`（若煙霧 commit 成功）再 `git checkout --` 還原該檔，確認 `git status` 乾淨。

  若不想留下煙霧 commit：也可以 `git add` 之後跑 `pre-commit run --files <那個檔>` 看它會不會改，然後 `git checkout --`。兩種驗法擇一即可。

- [ ] Commit 2：

```bash
git add .pre-commit-config.yaml
git commit -m "$(cat <<'EOF'
chore: 加 pre-commit（ruff format + lint）

commit 時自動整理 staged 的 Python；CI 另跑 --check 當後盾。
EOF
)"
```

這筆 commit 自己也會走過 hook（檔案是 yaml，ruff hook 會 skip，沒問題）。

### 6.5 GitHub Actions workflow + conftest 一行 + CLAUDE.md 短段

- [ ] 把 `tests/conftest.py` 第 14 行：

```python
TEST_DATABASE_URL = "postgresql://postgres@localhost:5433/PersonalDocAI_test"
```

改成：

```python
TEST_DATABASE_URL = "postgresql://postgres@127.0.0.1:5433/PersonalDocAI_test"
```

本機 compose 本來就綁 `127.0.0.1:5433`，這行對本機 pytest 等價，對 CI 較穩。不要改 `app/core/config.py` 的正式庫預設值。

- [ ] 新建目錄與檔案 `.github/workflows/test.yml`（一個 job、三步順序：format 不過就不要等 pytest）：

```yaml
name: test

on:
  push:
  pull_request:

jobs:
  ci:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      db:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_USER: postgres
          POSTGRES_DB: PersonalDocAI_test
          POSTGRES_HOST_AUTH_METHOD: trust
        ports:
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d PersonalDocAI_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt

      - name: format check
        run: ruff format --check app tests scripts

      - name: lint
        run: ruff check app tests scripts

      - name: schema
        run: |
          sudo apt-get update
          sudo apt-get install -y postgresql-client
          psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql

      - name: tests
        run: pytest -q
```

注意：CI 的 Postgres 直接把 `POSTGRES_DB` 設成測試庫名稱，不必跑 `db/docker-init/`（那支是本機 compose 在正式庫之外再建 test db 用的）。

（上面是骨架。**實際落地的 `.github/workflows/test.yml` 用的是 `actions/checkout@v7` 與
`actions/setup-python@v7`**——建檔當下的最新大版；另有大段中文註解解釋每一段的理由
（為什麼只起 pgvector、為什麼大小寫混雜的 `POSTGRES_DB` 沒問題、為什麼 CI 沒有 `.env` 也能綠）。
本檔上面的 YAML 已同步成 v7，抄的時候不必再改。）

- [ ] 本機先跑 CI 會跑的兩句（不需 GitHub）：

```bash
ruff format --check app tests scripts && ruff check app tests scripts
pytest -q
```

預期：全綠。conftest 改 `127.0.0.1` 之後本機 pytest 也要綠。

- [ ] `CLAUDE.md` 指令區（「跑測試」那段附近）補短段，不要寫成長篇教學。建議插入位置：現有 `pytest -q` 說明之後。文案：

```markdown
# ── pre-commit 與 CI（Phase 73）────────────────────────────────
# clone 之後、或新的 git checkout，hook 不會自己出現，要裝一次：
pre-commit install
# 之後每次 git commit：ruff format + ruff check --fix（只動 staged 的 .py）
# GitHub Actions（.github/workflows/test.yml）等價於：
#   ruff format --check app tests scripts
#   ruff check app tests scripts
#   pytest -q
# CI 自己起 pgvector 映 5433，不需要 Redis／Ollama／.env。
```

- [ ] Commit 3：

```bash
git add .github/workflows/test.yml tests/conftest.py CLAUDE.md
git commit -m "$(cat <<'EOF'
ci: GitHub Actions 跑 ruff check／format 與 pytest

pgvector 映 5433 對齊 conftest；不安裝 Redis／Ollama。
EOF
)"
```

### 6.6 建 remote 並推（第一次才有 Actions）——✅ **已於 2026-08-28 由產品負責人完成**

> 📌 **本節從「待辦」改寫成「紀錄」。** 這一步有外部副作用（建立 GitHub repo、push），
> 依本檔原規定要產品負責人明示才做——**他自己做了**。下面是事實，不是要再做一次的清單。

**實況：**

| 項目 | 事實 |
|---|---|
| remote | `origin` ＝ `https://github.com/1104030360/personalDocAI.git`（HTTPS，不是 SSH） |
| 可見性 | **PUBLIC**（原計畫寫 private；以事實為準，不要改回去，也不要建議改） |
| 預設分支 | **`main`**（不是 `master`） |
| Actions job `test` | **已綠兩次**（2026-08-28 推的兩筆）：`docs: README／LAUNCH.md 全文改為英文`（`77ae7bf`）、`chore: pytest 設定檔merge 進project.toml, delete pytest.ini`（`a53ab57`） |
| 秘密 | `.env`、`certs/`、`data/` 全在 `.gitignore`，沒有被推上去 |

**當初的步驟長這樣**（留作紀錄；若哪天要在另一台機器重接 remote 才會用到）：

- [x] 確認不會把秘密推出去：

```bash
git status
git check-ignore -v .env certs/cert.pem data/ 2>/dev/null || true
```

`.env`、`certs/`、`data/` 已在 `.gitignore`。不要 `git add -f` 它們。

- [x] 建 repo 並推（repo 名稱若 GitHub 上要叫別的，改第一個參數）：

```bash
# ⚠ 實際落地是 public。要 private 的話把 --public 換成 --private。
gh repo create personalDocAI --public --source=. --remote=origin
git push -u origin main
```

若 GitHub 上已經有空 repo、只是本機還沒接 remote：

```bash
git remote add origin https://github.com/<帳號>/personalDocAI.git
git push -u origin main
```

- [x] 打開 GitHub → Actions，等 job `test`（workflow 的 `name: test`、job id 是 `ci`）。成功標準：

  - `format check` 綠
  - `lint` 綠
  - `tests` 綠，顆數與本機 §6.1 相同（543）

  ✅ 兩次都達標，`schema` 那一步（`apt-get install postgresql-client` ＋ `psql -f db/schema.sql`）
  也一起驗過了——那正是 §0 說「本機驗不到、要真的推一次才知道」的三步。

- 若卡在連 DB：先懷疑 `localhost` vs `::1`。§6.5 若漏改 conftest，補改 `127.0.0.1` 再推。**不要**因此去加 Redis 或改 compose。

- 若 format／lint 紅、本機卻綠：多半是 CI 裝到較新的 ruff。`requirements.txt` 現在釘的是
  `ruff>=0.16,<0.17`、`.pre-commit-config.yaml` 的 `rev` 是 `v0.16.5`（整庫格式基線就是它跑出來的）。
  兩頭對齊後重推；要升級就三個地方一起動（那兩處 ＋ 重跑一次 `ruff format app tests scripts`）。

---

## 7. 驗收標準

| 檢查 | 通過長相 | 狀態（2026-09-01） |
|---|---|---|
| 風格基線 | `ruff format --check app tests scripts` 與 `ruff check app tests scripts` 本機 exit 0 | ✅ §6.3／§6.5 實測 |
| pytest 沒被風格改壞 | `pytest -q` 顆數與 §6.1 相同、0 skipped | ✅ 543 passed ＋ 0 skipped |
| pre-commit | 弄亂一個 `.py` 的空白或 import，`git commit` 會自動修或擋下 | ✅ §6.4 煙霧實測 |
| format CI | 把一行故意折得很醜 push → `ruff format --check` 紅 | ⏸ **未執行（可選）**——沒有做過「故意弄髒再 push」的負面驗證 |
| lint CI | 加一個未使用名稱 push → `ruff check` 紅 | ⏸ **未執行（可選）**——同上 |
| tests CI | 正常 push → `pytest -q` 綠 | ✅ 2026-08-28 兩次 push 都綠（§6.6） |
| 負面後盾 | 沒跑 `pre-commit install` 仍能 commit，但 push 後 CI 會紅 | ⏸ **未執行（可選）**——「仍能 commit」那半邊是既知行為，「CI 會紅」那半邊沒實測 |
| 秘密 | Actions log 與 repo 裡沒有 `.env`、憑證、`data/` 照片 | ✅ `.gitignore` ＋ §6.6 的 `git check-ignore` 檢查 |

負面三項（故意弄髒再 push）**刻意留成可選**：要做的話在綠燈之後、用一個立刻 revert 的 commit 做。
不要為了驗收把髒碼留在 `main`；也不要為了補這三格就自己 push（增量六期間 commit／push 節奏由產品負責人決定）。

---

## 8. 文件

- [x] `CLAUDE.md` 指令區：§6.5 那一小段（新 clone 裝 hook、CI 等價指令）。**已進 commit `4269985`**。
- [ ] **歸檔：本次不搬檔。** 增量六期間各 phase 一律不 commit，`unfinish/` → `finish/` 的
  `git mv` 隨產品負責人的 commit 一起做（`git mv` 會直接 stage，自己搬等於替他決定 commit 內容）。
  依據：增量六總覽 §7 鐵律 12「commit 節奏由產品負責人決定……不要把計畫檔搬進 `finish/`」。
- [x] **不要**為此改 `docs/spec/`、`docs/design/`。（全程沒動）

`LAUNCH.md` 不必改：那是給「這台 Mac 怎麼開服務」的人看的，不是給 CI 看的。

---

## 9. 風險與失敗怎麼辦

| 症狀 | 最可能原因 | 做什麼 |
|---|---|---|
| `ruff check --fix` 之後還有 F401 | 真的有未使用 import | 刪掉；不要 ignore 整包 `F` |
| format 完 pytest 紅、看起來像 import 錯 | `I` 重排踩到循環 import | 修循環，不要關 `I` |
| hook 說改了檔但 commit 失敗 | 改完的檔還沒 `git add` | 再 add 再 commit（正常） |
| CI `connection refused` 5433 | host 用了 `localhost`→`::1`，或 service 還沒 healthy | conftest 用 `127.0.0.1`；看 healthcheck |
| CI format 紅、本機綠 | ruff 版本不一致 | 對齊 `rev` 與 pip 裝到的版本 |
| worker／Redis 相關測試在 CI 紅 | 某個測試繞過了 `wire_memory_job_store` | 修測試，不要在 CI 起 Redis |
| commit 之後發現 `.md` 被改了 | `.pre-commit-config.yaml` 的 `types_or` 被拿掉了（上游預設含 markdown） | 把 `types_or: [python, pyi]` 加回去，被改的 `.md` 用 `git checkout` 還原 |
| 所有測試檔的 import 中間多一行空行 | `pyproject.toml` 的 `src` 被改成 `["app","tests","scripts"]` | 改回 `src = ["."]`，再跑一次 `ruff check --fix` |
| 換一台機器 commit，格式被反著改回去 | 那台裝到比 0.16.5 舊的 ruff | 對齊 `requirements.txt` 的下限（`ruff>=0.16,<0.17`）與 `.pre-commit-config.yaml` 的 `rev`（`v0.16.5`） |
| 重新 clone 之後 commit 沒被 hook 檢查 | `pre-commit install` 沒跑（hook 寫在 `.git/hooks/`，不進版控） | 跑一次 `pre-commit install`；沒跑的人靠 push 之後的 CI 紅燈擋 |

---

## 10. 做完長什麼樣（給產品負責人）——✅ 現況就是這樣

本機：

- `pre-commit install` 過一次之後，commit Python 會被 ruff 整理。
- `pytest -q` 仍然全綠（543 passed ＋ 0 skipped）。

GitHub（**public**；原計畫寫 private，實際落地是公開，見 §0）：

- 每次 push／PR 跑一顆 job：format → lint → schema → pytest。
- 沒有第二個 job、沒有部署、沒有 Node。
- 2026-08-28 已綠兩次（§6.6）。
