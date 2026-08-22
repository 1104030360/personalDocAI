# 2026-08-21 階段BBB：Phase 32 待辦資料層與端點——REP

## 實作邏輯

design3.md D13「人按建立才寫入」的後端。表已由 P29 建好（photo_id UNIQUE＝每張照片至多一筆，§7 MVP），
本 phase 只做兩件事：**確認寫入**（`POST /photos/{photo_id}/task`）與**列出**（`GET /tasks`）。
兩個端點都不碰 AI——VLM 的建議在上傳回應（P30）就給完了。端點 12→14。

## 步驟

1. TDD 先紅（11 顆）：建立 201（含 due 與 null due、回應鍵集合斷言）、重複 409、404、
   標題空白 422×2、到期日格式錯 422×2、初始空清單、排序（09-01／08-25／null → 08-25、09-01、null）、
   thumbnail_url 兩情境（有縮圖給網址、直接 insert 的無檔照片給 null）。
2. 綠：repository 三函式——`create_task`（收 date 物件；重複判斷歸 router，分工同 create_folder／create_entity）、
   `get_task_by_photo`（UNIQUE 保證至多一列）、`list_tasks`（`ORDER BY due_date ASC NULLS LAST,
   created_at DESC, id DESC`——NULLS LAST 寫明白防未來改 DESC 時翻車、id 第三鍵防同交易時間戳並列；
   JOIN photo 順帶取 thumbnail_path，孤兒不可能存在（CASCADE））。
3. 綠：`schemas/task.py`（**驗證與轉型分離**——CreateTaskRequest 收字串、只驗格式並回中文 422 訊息，
   轉 date 是 router 的事；TaskOut 不外送 created_at）＋`routers/tasks.py`（零 SQL；檢查全過才寫；
   縮圖用①已撈的照片列換算，不對同一張照片查第二次）＋main.py include_router。

## 測試方式與結果

- 實作者（opus subagent）：RED 11 failed → GREEN 11 passed；全量 **218 passed**（207＋11）；
  另做 **ORDER BY 變異測試**（拿掉排序鍵→恰好排序測試紅→復原）證明排序由 SQL 生效。
- Controller 複驗：`pytest -q`＝218、零 Ollama＝218；`/openapi.json` 清點 **14**；逐檔 review diff。

## 遇到的問題與解法

1. `date.fromisoformat` 比嚴格的 `YYYY-MM-DD` 寬（Python 3.11+ 也收 `20260918` 緊湊格式）——
   前端 `type=date` 只會送標準格式，curl 手打緊湊格式也能正確解析，無害；記為已知寬鬆（deferred minor）。
2. 空白字串到期日「 」→ strip 後非 None 仍驗格式 → 422（設計如此：要嘛給合法日期、要嘛給 null）。

## 備註

- 修改 2 檔、新增 3 檔；不 commit。與階段CCC（P33 前端、controller 親自）平行進行，檔案零相交。
