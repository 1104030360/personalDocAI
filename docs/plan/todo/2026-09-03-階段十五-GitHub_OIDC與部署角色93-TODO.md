# 階段十五：Phase 93 GitHub OIDC 與部署角色

- 日期：2026-09-03
- 計畫檔：`docs/plan/unfinish/phase-93-GitHub_OIDC與部署角色.md`（階段十四校準後版本）
- 目標：在 AWS 建一個「只有這個 repo 的 `main` 分支跑 Actions 時才借得到」的角色 `personaldocai-github-deploy`，ARN 放進 GitHub secret `AWS_DEPLOY_ROLE_ARN`；4 顆掃碼測試把鑰匙形狀釘死
- 顆數：692 → **696**（`test_design6_error_paths.py` 6 → 10）

## 實作邏輯

```text
  ┌─ subagent（Opus，TDD）──────────────────────────────┐   ┌─ controller（Fable）──────────────────────┐
  │ 1. 4 顆測試先寫 → 紅（JSON 還不存在）               │   │ 0. OIDC provider（已於階段十四建好）        │
  │ 2. deploy/aws/github-oidc-trust.json（sub 逐字鎖 main）│   │ 4. sed 展開 <ACCOUNT_ID>／<INSTANCE_ID> 到  │
  │ 3. deploy/aws/github-deploy-policy.json（五段）      │──►│    scratchpad → create-role → put-role-policy │
  │    → 綠；反向變異（sub 改 *／塞假帳號）證明有牙      │   │ 5. gh secret set AWS_DEPLOY_ROLE_ARN          │
  │ 4. CLAUDE.md 部署角色三行                            │   │ 6. 驗收：get-role／get-role-policy／secret list│
  └──────────────────────────────────────────────────────┘   └───────────────────────────────────────────────┘
```

- 為什麼先測試後 AWS：鑰匙的形狀先被測試釘死再配鎖，錯了不必 `delete-role`。
- 為什麼 subagent 零 `aws`／`gh`：裁決 R3——真資源、真 secret 只由 controller 動。
- OIDC 的安全性全押在 trust 的 `sub` 必須 `StringEquals` 逐字 `repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main`（design6 §8 第 9 列「未鎖 sub 不准合併」）。

## 步驟

- [x] 派 Opus 實作者（brief：計畫檔全文＋brief-common＋implementer-rules）
- [x] 實作者：RED（4 顆紅，理由是 JSON 不存在）→ 兩份 JSON → GREEN（10 passed）→ 反向變異兩輪 → 全量 696 → ruff 綠 → 三死埠 696 → CLAUDE.md 三行
- [x] controller：`sed` 展開到 scratchpad、`create-role --max-session-duration 3600`、`put-role-policy personaldocai-github-deploy-policy`、`gh secret set AWS_DEPLOY_ROLE_ARN`
- [x] controller：驗收清單（trust 逐字、policy 五段 Sid、零 managed policy、secret 在、EC2 零 running）
- [x] 派 Opus 審稿者（spec ＋ quality），fix loop 若有——Approved、零 Critical／Important、4 Minor 延後
- [x] 寫 REP，進入階段十六（Phase 94）

## 鐵律

- 不 commit；`test.yml`／`app/`／`docs/spec/` 零改動；JSON 只有 `<ACCOUNT_ID>`／`<INSTANCE_ID>` 佔位、零 12 位數字；EC2 不開機。
