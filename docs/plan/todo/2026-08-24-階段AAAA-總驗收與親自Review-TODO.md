# 階段 AAAA：增量四總驗收與親自 Review TODO

> 日期：2026-08-24
> 範圍：Phase 45〜51 全部做完之後的收尾檢查
> dev-prompt 要求：「最後你再親自 review 一遍」

---

## 1. 要做什麼

1. **獨立 review**（用 subagent，opus）
   - Docker 設定檔的 code review（compose × 2、Dockerfile、.dockerignore、init SQL、conftest）
   - 文件與現實是否相符的稽核（CLAUDE.md 指令區逐條實跑、總覽的數字）
2. **自己再走一遍**
   - 七份計畫檔的「明確不做」逐項掃碼
   - 架構不變量（端點數、DELETE 為 0、SQL 只在 repository、無全域例外捕捉）
   - **後悔藥演練**：把備份真的灌進一個一次性的庫，證明它救得回來（不是只有檔案在）
   - 全量／零 Ollama／三份 binder
   - 版控狀態：`app/` 必須完全乾淨
3. **把 review 找到的問題分類處理**：該修的修、該記錄的記錄、該退回計畫的說明理由
4. 寫 REP，列出**沒做完的事**與**需要產品負責人的事**

---

## 2. 驗收標準

- [ ] `pytest -q` ＝ 404 passed ＋ 0 skipped（且**確認沒有第二份 pytest 同時在跑**）
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 同顆數
- [ ] 三份規格 binder 全綠、零 SKIPPED
- [ ] 端點 20、DELETE 0
- [ ] `git status --short -- app/` 為空
- [ ] 七份計畫檔的「明確不做」逐項掃過
- [ ] 後悔藥演練通過（備份真的灌得回來）
- [ ] review findings 全部有處置（修／記錄／退回，每一項寫明理由）
- [ ] 需要手機的項目明確標示為「待產品負責人」，不自行勾選
- [ ] **沒有 commit**
