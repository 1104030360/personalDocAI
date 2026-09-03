"""增量六（design6.md）的錯誤路徑與「明確不做」收尾驗證。

體例沿用 Phase 25／37／44／71 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py、test_design5_error_paths.py）：
**先盤點、只補 ★ 缺口**——大多數行為已經由各 phase 自己的測試檔釘住了，
本檔只放「沒有別人守著」的那些，以及「掃設定檔文字」這種不屬於任何服務模組的斷言。

⚠ 本檔**分三次寫完**（增量六總覽 §10 追認項 B）：

| 何時 | 誰加 | 內容 |
|---|---|---|
| **Phase 90**（本次開檔） | 戊 | `Dockerfile` 多階段與 compose 零改動／零 AWS 設定的掃碼（4 顆） |
| Phase 91／92 | 戊 | EC2 unit 與 user-data `UNIT` heredoc 逐字相同；等 :11434 只在 `local`（2 顆） |
| Phase 93 | 己 | GitHub OIDC trust JSON 的掃碼（4 顆：`sub` 鎖 main、無萬用字元、aud、無寫死帳號 ID） |
| Phase 94 | 己 | CD workflow 的掃碼（6 顆：綁 test、id-token、arm64、target、sha tag、無金鑰） |
| Phase 95 | 收尾 | §8 錯誤表逐列補缺口 ＋ §0 六禁與 §1.2 被否決清單的掃碼（10 顆） |

⚠ 本檔**完全不連任何外部服務**：它讀的是磁碟上的設定檔（`Dockerfile`、`compose.yaml`、
   `compose.dev.yaml`、`deploy/ec2/`），零 AWS、零 Docker daemon、零 Redis、零 Ollama。
   所以三個死埠一起指的時候顆數不會變。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_dockerfile() -> str:
    """讀專案根目錄的 Dockerfile 純文字。

    刻意不解析、不呼叫 docker——本檔在 CI 上也要能跑，而 CI 沒有 Docker daemon
    （.github/workflows/test.yml 只起一個 pgvector 附屬容器）。
    """
    return (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")


def read_compose() -> str:
    """讀 compose.yaml 純文字（與 test_design5_error_paths.py 同一手法）。"""
    return (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")


def read_compose_dev() -> str:
    """讀 compose.dev.yaml 純文字（開發 overlay；AWS 字樣兩份都要掃）。"""
    return (PROJECT_ROOT / "compose.dev.yaml").read_text(encoding="utf-8")


def compose_config() -> dict:
    """把 compose.yaml 解析成 dict。

    用 PyYAML 而不是自己寫正規式：`services:` 底下與檔尾 `volumes:` 底下的名字
    縮排一模一樣（都是兩格＋冒號結尾），正規式很容易把 pgdata／redisdata 一起抓進來
    （寫這份計畫時實測過，斷言會變成 6 個而永遠紅）。

    📌 PyYAML **不必**寫進 requirements.txt：它是 langchain-core（`pyyaml>=5.3`）
       與 pre-commit（`pyyaml>=5.1`）的必要相依，兩者都在 requirements.txt 裡，
       所以本機 .venv 與 CI 都一定裝得到。
    """
    return yaml.safe_load(read_compose())


def compose_services() -> list[str]:
    """`services:` 底下那一層的服務名，依 YAML 裡的出現順序。

    （Python 3.7 起 dict 保留插入順序，PyYAML 也是照檔案順序塞，所以順序斷言有意義。）
    """
    return list(compose_config()["services"])


def stage_names() -> list[str]:
    """把 Dockerfile 裡每一個 `FROM … AS <名字>` 的名字依出現順序抓出來。

    正規式說明：
      ^FROM\\s+       行首的 FROM 加至少一個空白
      \\S+            基底映像或上游 stage 名（不含空白的一串）
      \\s+AS\\s+      中間的 AS（Docker 不分大小寫，這裡用 re.I）
      ([\\w.-]+)      我們要的 stage 名字（英數、底線、點、減號）

    用 re.M 讓 ^ 對每一行生效；用 re.I 讓 `as` 小寫也抓得到。
    """
    return re.findall(r"^FROM\s+\S+\s+AS\s+([\w.-]+)", read_dockerfile(), re.M | re.I)


def stage_body(stage: str) -> str:
    """把某一個 stage 的內容切出來：`FROM … AS <stage>` 那一行之後、到下一個 `FROM` 之前。

    為什麼需要它：Dockerfile 的指令是**寫在哪個 stage 底下就屬於哪個 stage**，
    而對整份檔做 `re.search` 分不出這件事。把 `ARG GIT_SHA` 搬到檔尾（＝掉進 app stage）
    的話，工人映像就再也沒有 WORKER_VERSION 了——但整份檔的搜尋照樣命中，測試假綠。

    切法刻意用「下一個行首的 FROM」而不是解析器：Dockerfile 沒有標準的 Python 解析器，
    而 stage 的邊界規則就只有這一條。
    """
    source = read_dockerfile()
    header = re.search(rf"^FROM\s+\S+\s+AS\s+{re.escape(stage)}\s*$", source, re.M | re.I)
    assert header, f"Dockerfile 裡沒有 `FROM … AS {stage}` 這個 stage"
    rest = source[header.end() :]
    next_stage = re.search(r"^FROM\b", rest, re.M)
    return rest[: next_stage.start()] if next_stage else rest


# ---- Phase 90：Dockerfile 多階段（design6 D15／D16、總覽 §10 追認項 j）----


def test_Dockerfile有cloud_worker這個target():
    """design6 §11 第 5 列：worker 映像走「多階段或第二 target」。

    我們選了多階段（總覽 §10 追認項 j），所以一定要有一個叫 cloud-worker 的 stage
    ——`docker build --target cloud-worker` 靠的就是這個名字。
    名字打錯（例如 cloud_worker、cloudworker）的話 build 會直接失敗，
    但**CD 的 yaml 也是照這個名字寫的**，兩邊要對得起來，所以在這裡釘死。
    """
    names = stage_names()

    assert "cloud-worker" in names, (
        f"Dockerfile 必須有一個 `FROM … AS cloud-worker` 的 stage；目前只有：{names}"
    )
    # 順便釘住共用底座還在：兩個下游 stage 要接在同一個 base 上，
    # 才不會變成「裝兩次套件」或「兩份會漂移的程式碼複製」
    assert "base" in names, f"Dockerfile 應該有共用的 base stage；目前只有：{names}"


def test_Dockerfile的app階段在最後():
    """總覽 §10 追認項 j ＋ §7 鐵律 11：compose 本增量零改動。

    ★ 這一顆守的是一個**安靜的**壞法：
      不帶 --target 的 `docker build .` 會建到**最後一個 stage**。
      compose.yaml 的 app 與 worker 兩個服務都寫 `build: .`（沒有 target:），
      所以 app 一旦不在最後，compose 就會蓋出一個「CMD 是雲端工人」的映像，
      然後 app 容器起來之後跑去 SQS 收訊息、沒有人聽 8000 埠
      ——**build 不會失敗、compose config 也看不出來**，只有服務莫名其妙不通。

    有人把 cloud-worker 搬到檔案最後的那一刻，這一顆會紅。

    ★ 第二條斷言（2026-09-03 fix wave 加）補的是同一個壞法的**無名版**：
      `FROM base`（沒有 `AS 名字`）也是一個合法的 stage，但 stage_names() 的
      正規式抓不到它——尾巴多一個無名 stage 的話，上面那條仍然說「最後一個是 app」，
      而 `docker build .` 其實會停在那個無名的東西上。
      所以再數一次 `FROM` 的**總行數**，兩邊必須一樣多。
    """
    names = stage_names()
    source = read_dockerfile()

    assert names, "Dockerfile 裡一個具名 stage 都沒有？（多階段改壞了）"
    assert names[-1] == "app", (
        "app 必須是 Dockerfile 裡的**最後一個** stage，"
        f"否則 compose 的 `build: .` 會蓋出工人映像。目前順序：{names}"
    )
    from_lines = re.findall(r"^FROM\b", source, re.M)
    assert len(from_lines) == len(names), (
        f"Dockerfile 有 {len(from_lines)} 個 FROM 但只有 {len(names)} 個具名 stage："
        "有一個 stage 沒寫 `AS <名字>`。無名 stage 抓不到、卻照樣會變成 "
        "`docker build .` 的終點——compose 的 app 映像會安靜地變成別的東西"
    )


def test_Dockerfile的cloud_worker帶ARG_GIT_SHA():
    """design6 D16 ＋ 總覽 §10 追認項 e：靠 WORKER_VERSION 驗「跑的是不是新映像」。

    三件事一起釘：
      ① 有 `ARG GIT_SHA`（build 時傳得進來）
      ② 有 `ENV WORKER_VERSION=$GIT_SHA`（烙成執行期環境變數，工人啟動 log 印得出來）
      ③ cloud-worker 的 CMD 真的是跑 app.workers.cloud_worker 這個模組

    少了 ① 或 ②，Phase 94 的 CD 推上去的映像啟動時只會印 version=dev，
    Demo 3 就再也分不出「跑的是新的還是舊的」——而那正是 D16 唯一的驗證手段。

    ★ 三條都只在 **cloud-worker 這個 stage 的範圍內**搜（2026-09-03 fix wave 改）：
      Dockerfile 的指令是寫在哪個 stage 底下就屬於哪個 stage。對整份檔搜的話，
      有人把這三行搬到檔尾（＝掉進 app stage）時測試照樣全綠，
      但工人映像已經沒有 WORKER_VERSION 了——啟動 log 會印 version=dev，
      而那正是這一顆要防的事。
    """
    source = stage_body("cloud-worker")

    # ★ 三條都用「行首錨定」的正規式（re.M 讓 ^ 對每一行生效），刻意不用 `in`：
    #   `"ENV WORKER_VERSION=$GIT_SHA" in source` 這種寫法連被註解掉的
    #   `# ENV WORKER_VERSION=$GIT_SHA` 都會算命中，測試就假綠了——§4.6 步驟 3 的變異 2 在驗這件事。
    assert re.search(r"^ARG GIT_SHA(=\S*)?\s*$", source, re.M), (
        "cloud-worker stage 必須有 `ARG GIT_SHA`（CD 用 --build-arg 傳）"
    )
    assert re.search(r"^ENV WORKER_VERSION=\$GIT_SHA\s*$", source, re.M), (
        "必須把 ARG 烙成 ENV WORKER_VERSION，工人啟動 log 才印得出 version=<sha>"
    )
    # CMD 用 JSON 陣列寫法（exec form），訊號才收得到——Ctrl+C／SIGTERM 要能停得下來
    assert re.search(r'^CMD \[.*"app\.workers\.cloud_worker".*\]\s*$', source, re.M), (
        "cloud-worker 的 CMD 必須跑 python -m app.workers.cloud_worker"
    )


def test_compose_yaml沒有新增服務也沒有AWS設定():
    """總覽 §7 鐵律 11 ＋ §10 追認項 j：Dockerfile 改多階段之後，compose **不必跟著動**。

    ★ 本顆守四件事（第 ④ 條是 2026-09-02 校準裁決 R10 加的——這顆的名字本來就承諾了
      「也沒有 AWS 設定」，卻把那一半推給 Phase 95，名不副實）：

      ① 兩份 compose 都**沒有 `target:` 字樣**，而 app 與 worker 的 `build:` 仍然只是 `.`。
         這正是「app stage 放最後」換來的東西：不帶 `--target` 的 `docker build .`
         會停在最後一個 stage ＝ app，所以 compose 不必知道 stage 的存在。
         哪天有人在 compose 裡加 `target:`，就代表 Dockerfile 的 stage 順序被動過了
         ——這一顆會在那一刻紅。
      ② `image: personaldocai-app` 兩處都在（app 與 worker 共用同一份映像）。
      ③ 服務**恰好**仍是 db／redis／app／worker 四個
         （手滑加第五個 cloud-worker 服務的話，它開機就會自己跑起來、默默把 SQS
           訊息吃光——而 EC2 上那台也在收同一條佇列）。
      ④ 兩份 compose 全文**零** `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE` 字樣
         （design6 §3：雲端路的設定只走 `.env`，不進版控的 compose；
           寫進 compose 等於把 bucket 名與佇列 URL 推上 public repo）。

    📌 Phase 95 的 `test_compose沒有為了雲端新增任何服務` 仍可以再加一顆更廣的
       （例如連 `.github/workflows/` 一起掃）；兩顆不衝突，本 phase 先把自己的名字守住。
    """
    source = read_compose()
    dev_source = read_compose_dev()

    # ① 沒有任何 target:（先驗這條——它是最直接的訊號）
    assert "target:" not in source, (
        "compose.yaml 不該出現 `target:`——app stage 放在 Dockerfile 最後，"
        "就是為了讓 compose 不必指定 stage（總覽 §10 追認項 j）"
    )
    assert "target:" not in dev_source, "compose.dev.yaml 也不該出現 `target:`（同上）"

    # ①② build 仍是 `.`、而且兩個服務共用同一份映像名
    services = compose_config()["services"]
    for name in ("app", "worker"):
        assert services[name]["build"] == ".", (
            f"{name} 服務應該仍是 `build: .`（用同一份 Dockerfile 的最後一個 stage）；"
            f"目前是：{services[name].get('build')!r}"
        )
        assert services[name]["image"] == "personaldocai-app", (
            f"{name} 必須指向映像名 personaldocai-app（app 與 worker 共用同一份映像）"
        )

    # ③ 服務清單：恰好四個，順序也不變
    names = compose_services()
    assert names == ["db", "redis", "app", "worker"], (
        f"compose.yaml 的服務必須仍是四個（db／redis／app／worker）；目前是：{names}"
    )

    # ④ 兩份 compose 都不准出現雲端路的設定名（design6 §3；repo 是 public）
    for filename, text in (("compose.yaml", source), ("compose.dev.yaml", dev_source)):
        for keyword in ("AWS_", "S3_BUCKET", "SQS_", "CLOUD_ROUTE"):
            assert keyword not in text, (
                f"{filename} 不該出現 `{keyword}`——雲端路的設定只走 .env（design6 §3），"
                "寫進 compose 等於把 bucket 名與佇列 URL 推上 public repo"
            )


# ---- Phase 91／92：EC2 unit 與 user-data 必須同一份（reviewer：不能只靠人工 diff）----


def _unit_file_text() -> str:
    return (PROJECT_ROOT / "deploy/ec2/personaldocai-worker.service").read_text(encoding="utf-8")


def _user_data_embedded_unit() -> str:
    """抽出 user-data.sh 裡 `<<'UNIT'` … `UNIT` 那一段（不含標記行）。"""
    source = (PROJECT_ROOT / "deploy/ec2/user-data.sh").read_text(encoding="utf-8")
    match = re.search(r"<<'UNIT'\n(.*)\nUNIT\n", source, re.S)
    assert match, "user-data.sh 必須有 <<'UNIT' … UNIT 這段內嵌 unit"
    return match.group(1)


def test_unit檔與user_data內嵌段逐字相同():
    """機器上跑的是 user-data 寫進去的那份；git 裡的 .service 是人看的正本。

    只改一邊、CI 仍綠，下次開機就漂——reviewer 點名這個缺口。
    """
    unit = _unit_file_text()
    embedded = _user_data_embedded_unit()
    assert unit == embedded + "\n" or unit == embedded, (
        "deploy/ec2/personaldocai-worker.service 必須與 user-data.sh 的 UNIT "
        "heredoc 逐字相同（含註解）。改 unit 一定兩檔同改。"
    )


def test_unit只在local才等本機Ollama():
    """cloud 模式不該被「user-data 最後才裝 Ollama、那步失敗」拖死。

    EnvironmentFile 已載入，空字串／cloud 都不是 local → 跳過 curl :11434。
    """
    unit = _unit_file_text()
    wait_lines = [
        line
        for line in unit.splitlines()
        if "127.0.0.1:11434" in line and line.startswith("ExecStartPre=")
    ]
    assert len(wait_lines) == 1, f"應該恰好一條 ExecStartPre 在等 11434；目前：{wait_lines}"
    assert "WORKER_VLM_BACKEND" in wait_lines[0], (
        "等 11434 的那一行必須先看 WORKER_VLM_BACKEND，只有 local 才 curl；cloud／空值直接放行"
    )
    assert "local" in wait_lines[0]
