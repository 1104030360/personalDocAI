"""在**別台機器**上跑的行程（目前只有一支：雲端看圖工人 `cloud_worker`）。

【為什麼是 `app/workers/`，不是 `scripts/`】
`.dockerignore`（design4 §8.5 建的檔）把 `scripts/` 整個排除在映像之外：
那些是 host 手動跑的小工具，不必進容器。而工人**一定要進映像**——它就是 EC2 上
唯一要跑的東西。放 `scripts/` 的話 `docker build` 會成功、映像也起得來，
然後在 `python -m app.workers.cloud_worker` 那一刻才 `ModuleNotFoundError`：
**安靜地壞掉**，而且要等到人已經開了一台 EC2 才會發現（總覽 §10 追認項 k）。

【為什麼不放 `app/services/`】
`services/` 底下是「被 app 這個行程呼叫的東西」。工人是**另一個行程的進入點**
（`python -m app.workers.cloud_worker`），身分與 `app/celery_app.py` 相同。
放在自己的套件裡，那顆「工人不准 import 資料庫／Celery／Redis」的掃碼測試
才有一個明確、不會誤傷別人的掃描範圍。

【本套件底下的模組不得 import 的東西】（design6 D11、D13）
`app.repositories`、`app.db`、資料庫驅動程式（那個套件名刻意不寫：design3 的掃碼對 app/ 全樹做子字串比對，註解也算）、`celery`、`redis`。
工人不寫 Postgres、不算 embedding、不碰佇列框架——它只看圖，然後把結果放回寄物櫃。
"""
