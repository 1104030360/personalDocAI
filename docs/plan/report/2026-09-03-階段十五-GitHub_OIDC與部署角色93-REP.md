# 階段十五 REP：Phase 93 GitHub OIDC 與部署角色

- 日期：2026-09-03
- 對應 TODO：`docs/plan/todo/2026-09-03-階段十五-GitHub_OIDC與部署角色93-TODO.md`
- 計畫檔：`docs/plan/unfinish/phase-93-GitHub_OIDC與部署角色.md`（實作紀錄在其 §10）
- 工作區：`.superpowers/sdd/phase0903-1/`（`task-93-report.md`、`review-93.diff`、ledger）
- 結果：**完成**。顆數 692 → **696**（0 skipped）；`test_design6_error_paths.py` 6 → 10；review **Approved**（零 Critical／Important）

---

## 1. 實作邏輯

「準備鑰匙」：GitHub Actions 之後要能不放長期金鑰就借到 AWS 的權限。做法是 OIDC——GitHub 每次跑 workflow 簽一張短命令牌，
AWS 驗 trust policy 的 `sub`／`aud` 後發幾小時就過期的臨時憑證。安全性全押在一句：**`sub` 必須逐字等於
`repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`**（不可變主體格式＋`main` 分支），
所以四顆掃碼測試把「逐字鎖 main、零星號、`aud` 是 STS、`deploy/aws/*.json` 零真帳號 ID」釘死。

```text
  subagent（Opus，TDD）                                     controller（Fable）
  ────────────────────────────────────────                  ──────────────────────────────────────────────
  4 顆測試 → 紅（JSON 不存在）                              OIDC provider（階段十四已建）
  github-oidc-trust.json（sub 逐字、StringEquals、零 *）     gh api …/sub 再查一次 → 逐字相同
  github-deploy-policy.json（五段 Sid、SSM 雙資源）          sed 展開 <ACCOUNT_ID>／<INSTANCE_ID> → scratchpad
  → 綠（10 passed）→ 反向變異兩輪 → 還原 diff 零差異        create-role（max session 3600）→ put-role-policy
  CLAUDE.md「部署角色」三行                                  gh secret set AWS_DEPLOY_ROLE_ARN → 驗收
```

## 2. 步驟（實際發生的順序）

1. controller 派 Opus 實作者（只做 🤖 段：兩份 JSON、4 顆測試、CLAUDE.md）。
2. 實作者：RED（4 紅：`FileNotFoundError`×3＋`AssertionError`）→ 兩份 JSON 從計畫檔 `sed -n` 原樣導出 → GREEN（10 passed）
   → 反向變異（`sub` 改 `*` → 2 紅；假帳號 `000000000000` → 1 紅）→ 還原 `diff` 零差異 → 全量 696 → 三死埠 696 → ruff 綠 → tokenize `[]` → CLAUDE.md 小段插在「雲端工人（EC2）」段結尾。
3. controller：`gh api` 前綴再查（相同）→ `sed` 展開到 scratchpad（佔位 0 殘留）→ `aws iam create-role personaldocai-github-deploy --max-session-duration 3600`
   → `put-role-policy personaldocai-github-deploy-policy` → 驗 trust 條件逐字、五段 Sid 順序、SSM 資源＝實例＋`::document/AWS-RunShellScript`、managed policies `[]`
   → `gh secret set AWS_DEPLOY_ROLE_ARN` → `gh secret list` 有 → EC2 零 running → 展開檔零進 repo。
4. controller 派 Opus 審稿者（spec＋quality）：Approved；4 Minor 記入 ledger 延後最終 review。
5. controller 親跑全量 696、ruff 綠；勾 §6 的 controller 項目。

## 3. 測試方式

- TDD：先紅（功能不存在）再綠；兩輪反向變異證明測試有牙；還原後與備份 `diff`。
- 全量 `pytest -q`：實作者 696、controller 再跑 696（0 skipped；1 warning＝環境層 Starlette）。
- 三死埠零依賴實證：696（四顆只讀本機檔案）。
- `ruff format --check`／`ruff check`：綠。tokenize：零非 ASCII 識別字。
- 機密掃描：`grep -nE '\b[0-9]{12}\b' deploy/aws/*.json CLAUDE.md` 無輸出；展開檔只在 scratchpad。
- 審稿者獨立驗證：把計畫檔 heredoc 行段與交付檔 `diff` → 逐字相同；`sub` 對常數檔自打字串比對（防看不見的字元）。

## 4. 遇到的問題與解法

| 問題 | 解法 |
|---|---|
| brief-common §5 列了 `read_deploy_policy()`，計畫檔 §4.7 明文不寫（四顆都不需要解析權限 policy） | 照計畫檔＋YAGNI 不寫；controller 認可 |
| `create-role` 的 `--query Role.MaxSessionDuration` 回 null | 用 `get-role` 再查＝3600（create 回應不含該欄位） |
| §6「兩份 JSON 都在版控裡」與 R0 不 commit 衝突 | 檔案在工作樹（`??`）、佔位符正確；勾選保留，真進版控等產品負責人 commit |
| `$SCRATCH` 是 session 專屬路徑 | 計畫檔寫「換任何專案外目錄都可以」；CLAUDE.md 只寫「專案外暫存目錄」 |

## 5. 測試結果

| 項目 | 值 |
|---|---|
| `pytest -q` | **696 passed, 0 skipped** |
| 三死埠 | 696 |
| `test_design6_error_paths.py` | 10 passed |
| ruff | format 114 files unchanged／check All passed |
| review | Approved；0 Critical、0 Important、4 Minor（延後） |
| AWS | provider ×1、role `personaldocai-github-deploy`（trust 逐字、inline policy 五段、零 managed）；**全部免費、零運算費** |
| GitHub | secret `AWS_DEPLOY_ROLE_ARN` |

## 6. 下一步

階段十六：Phase 94（`deploy.yml`＋6 顆測試＋README；variable 已設；Demo 3 留給產品負責人 push）。
