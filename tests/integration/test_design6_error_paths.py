"""增量六（design6.md）的錯誤路徑與「明確不做」收尾驗證。

體例沿用 Phase 25／37／44／71 的收尾檔（test_folder_error_paths.py、
test_design3_error_paths.py、test_design4_error_paths.py、test_design5_error_paths.py）：
**先盤點、只補 ★ 缺口**——大多數行為已經由各 phase 自己的測試檔釘住了，
本檔只放「沒有別人守著」的那些，以及「掃設定檔文字」這種不屬於任何服務模組的斷言。

⚠ 本檔**分五次寫完**（增量六總覽 §10 追認項 B）：

| 何時 | 誰加 | 內容 |
|---|---|---|
| **Phase 90**（本次開檔） | 戊 | `Dockerfile` 多階段與 compose 零改動／零 AWS 設定的掃碼（4 顆） |
| Phase 91／92 | 戊 | EC2 unit 與 user-data `UNIT` heredoc 逐字相同；等 :11434 只在 `local`（2 顆） |
| Phase 93 | 己 | GitHub OIDC trust JSON 的掃碼（4 顆：`sub` 鎖 main、無萬用字元、aud、無寫死帳號 ID） |
| Phase 94 | 己 | CD workflow 的掃碼（6 顆：綁 test、id-token、多架構（amd64＋arm64）、target、sha tag、無金鑰） |
| Phase 95 | 收尾 | §8 錯誤表逐列補缺口 ＋ §0 六禁與 §1.2 被否決清單的掃碼（11 顆；最後那顆 `test_部署policy恰五段而且SendCommand綁實例與document` 是 review 裁決 R18 ② 追加的） |

⚠ 本檔的外部依賴（Phase 95 之後精確版；早期版本寫「完全不連任何外部服務」已經不真）：

   * **只讀磁碟檔案文字／`ast`**（Phase 90〜94 全部，加上 Phase 95 的【掃A】【掃B】
     【掃E】【掃F】【掃H】與檔尾那顆 policy）——`Dockerfile`、兩份 `compose*.yaml`、
     `deploy/ec2/`、`deploy/aws/*.json`、`.github/workflows/deploy.yml`、`app/` 的原始碼。
     零連線、零資料庫。
   * **【掃D】** 純記憶體：走真的 `AwsMailbox.send_job`／`send_result`，但 boto3 的
     client 換成記帳假件（`RecordingS3`／`RecordingSqs`），一個封包都沒送出去。
   * **【補A】【補B】** 走完整的 app（TestClient ＋ `跑完任務`），所以會用到**測試庫**
     `PersonalDocAI_test`；【掃C】也要 TestClient（讀 `/openapi.json`）、
     **【掃G】** 直接查測試庫的 `information_schema`。
     這些都靠 conftest 的五道 autouse 安全網（假 AI、假 JobStore、假雲端路、臨時 DATA_DIR、
     每測清表），資料庫是本機 Docker 那顆 `db` 容器裡的測試庫，不是外部服務。

   所以**仍然**零真 AWS（雲端路一律 `CloudRoute(FakeMailbox(), FakeProbe(...))`，
   boto3 那幾顆注入假 client）、零真 Redis、零 Celery、零真 Ollama（design6 §9）——
   三個死埠一起指的時候顆數不變。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.db.session import get_connection
from app.dependencies import get_cloud_route, get_privacy_gate, get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import cloud_ingest, gated_ingest, ingest_job, staging_service
from app.services.aws_mailbox import AwsMailbox
from app.services.privacy_gate import Verdict
from app.services.vlm_service import PhotoUnderstanding
from app.workers import cloud_worker
from tests.conftest import 目前的任務清單, 跑完任務
from tests.fakes import (
    FakeMailbox,
    FakePrivacyGate,
    FakeProbe,
    FakeVLM,
    ScriptedVLM,
    make_png_bytes,
)

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
    from_lines = re.findall(r"^FROM\b", source, re.M | re.I)
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


# ---------------------------------------------------------------------------
# Phase 93：GitHub OIDC 與部署角色（design6 §6 最後一列、§8 錯誤表第 9 列、D16）
#
# 這四顆掃的是 deploy/aws/ 底下的 JSON（前三顆掃本 phase 那兩份，第四顆掃**全部**）——它們是「鑰匙」的形狀，
# 而鑰匙配錯的後果沒有任何執行期訊號：CD 一樣會跑、一樣會紅在
# configure-aws-credentials 那一步，訊息只說「Not authorized」，
# 不會告訴你是 sub 寫成了萬用字元、還是 aud 打錯字。
#
# ⚠ 這幾顆**不連 AWS**（只讀本機檔案），所以三個死埠一起指也不會變顆數。
# ---------------------------------------------------------------------------

DEPLOY_AWS_DIR = PROJECT_ROOT / "deploy" / "aws"

# 總覽 §10 追認項 b：分支是 main（design6 §6 寫的 master 是筆誤）。
# 這一串是契約——Phase 94 的 workflow 也靠它才換得到憑證。
# 前綴含 GitHub 的擁有者 ID 與 repo ID（2026-07-15 起新 repo 的不可變主體格式；§4.3 的框有查證與比對指令）。
GITHUB_OIDC_SUB = "repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/main"
GITHUB_OIDC_AUD = "sts.amazonaws.com"

# 12 位純數字 ＝ AWS 帳號 ID 的長相。前後加 \b（詞界）才不會把
# 更長的數字串的其中 12 位誤判成帳號。
ACCOUNT_ID_PATTERN = re.compile(r"\b\d{12}\b")


def read_trust_policy() -> dict:
    """讀 deploy/aws/github-oidc-trust.json 並解析成 dict。

    用 json.loads 而不是字串比對：這樣「條件寫在 StringLike 而不是 StringEquals」
    這種**結構**上的錯誤才抓得到——字串比對只看得到有沒有那幾個字。
    """
    return json.loads((DEPLOY_AWS_DIR / "github-oidc-trust.json").read_text(encoding="utf-8"))


def test_OIDC信任文件的sub逐字鎖住main分支():
    """design6 §8 錯誤表第 9 列：trust 必須釘 repo ＋ branch。

    為什麼一定要 StringEquals：
      StringLike ＋ "repo:1104030360@92135456/personalDocAI@1349196211:*" 會涵蓋
        repo:1104030360@92135456/personalDocAI@1349196211:pull_request        <- 任何人開 PR
        repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/heads/任何分支
        repo:1104030360@92135456/personalDocAI@1349196211:ref:refs/tags/任何 tag
      也就是說，任何能在這個 repo 觸發 workflow 的分支／PR／tag，都能拿到
      可以推 ECR、可以對那台 EC2 下指令的 AWS 憑證。
    """
    statements = read_trust_policy()["Statement"]
    assert len(statements) == 1, f"信任文件應該只有一條 Statement，現在有 {len(statements)} 條"
    condition = statements[0]["Condition"]

    assert "StringLike" not in condition, (
        "sub 必須用 StringEquals 逐字比對。StringLike 會允許萬用字元，"
        "等於任何分支／任何 PR 都借得到這個角色（design6 §8 第 9 列）"
    )
    assert condition["StringEquals"]["token.actions.githubusercontent.com:sub"] == GITHUB_OIDC_SUB


def test_OIDC信任文件沒有星號萬用字元():
    """整份文件連一個 * 都不准出現——不只是 sub 那一格。

    掃**整份原始文字**而不是只看 sub 的理由：萬用字元可以躲在很多地方
    （Principal 的 ARN、Action 寫成 sts:*、多一條 Sid 帶星號的 Statement）。
    trust policy 本來就沒有任何一格「合法地需要星號」——它沒有 Resource，
    Action 只有一個，Principal 是完整 ARN——所以「整份零星號」是可以成立的
    最強斷言，而且改壞了一定會紅。
    """
    source = (DEPLOY_AWS_DIR / "github-oidc-trust.json").read_text(encoding="utf-8")

    assert "*" not in source, (
        "信任文件不可以出現任何萬用字元。要放寬「誰能借這個角色」必須是"
        "產品負責人的決定，不是實作者順手改的（design6 §8 第 9 列：不准合併）"
    )


def test_OIDC信任文件的aud是sts():
    """aud ＝「這張令牌是簽給誰用的」，鎖住它才擋得掉「拿別處的令牌來換 AWS 憑證」。

    順便把另外兩件事一起釘住（它們錯了症狀一樣難查）：
      - Principal 必須是 Federated，而且指向 GitHub 的那個 provider
      - Action 必須是 sts:AssumeRoleWithWebIdentity（寫成 sts:AssumeRole 永遠換不到）
    """
    statement = read_trust_policy()["Statement"][0]

    aud = statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:aud"]
    assert aud == GITHUB_OIDC_AUD, (
        # ★ 2026-09-03（Phase 95 順手：93 review deferred minors，裁決 R18 ④）補失敗訊息：
        #   裸的 == 斷言紅起來只會印兩個很像的字串，讀的人得自己比對哪個字不一樣。
        f"aud 必須逐字是 {GITHUB_OIDC_AUD}（＝這張令牌只能拿去換 AWS 憑證）；現在是 {aud!r}"
    )
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity", (
        "OIDC 換憑證的動作是 AssumeRoleWithWebIdentity；sts:AssumeRole 是給 AWS 內部身分用的"
    )
    assert statement["Principal"]["Federated"].endswith(
        ":oidc-provider/token.actions.githubusercontent.com"
    ), "Principal 必須指向 GitHub Actions 的 OIDC provider"
    assert statement["Effect"] == "Allow"


def test_部署用的policy裡沒有寫死帳號ID():
    """總覽 §7 鐵律 10：policy JSON 的帳號 ID 一律用 <ACCOUNT_ID> 佔位。

    掃的是 deploy/aws/ 底下**全部**的 .json（總覽 §10.2 的追加裁決）：
    82 的 mac-policy.json、84 的 s3-lifecycle.json、91 的 worker-role-*.json、
    本 phase 的兩份——之後再多一份也自動納入，不必回來改測試。

    帳號 ID 本身不算機密（ARN 到處都是它），但把它寫死進版控有兩個實際壞處：
      1. 換帳號／重開帳號時要逐檔搜尋取代
      2. **這個 repo 已經是 public**，寫進去就等於公開，而且會永遠留在 git 歷史裡（改不掉）
    做法是「檔案裡永遠是佔位符，要送給 AWS 的時候才用 sed 展開到專案外的暫存目錄」。
    """
    json_files = sorted(DEPLOY_AWS_DIR.glob("*.json"))
    names = {path.name for path in json_files}
    assert {"github-oidc-trust.json", "github-deploy-policy.json"} <= names, (
        f"deploy/aws/ 應該至少有本 phase 的兩份 JSON，現在只有：{sorted(names)}"
    )

    hits: list[str] = []
    for path in json_files:
        source = path.read_text(encoding="utf-8")
        # 順便證明每一份都是合法 JSON（JSON 沒有註解語法，見 §7 陷阱 10）。
        # ★ 2026-09-03（Phase 95 順手：93 review deferred minors，裁決 R18 ③）改成具名斷言：
        #   裸的 json.loads(source) 壞掉時會以 JSONDecodeError 冒出來，訊息只說
        #   「Expecting ',' delimiter: line 12 column 5」——**不會說是哪一個檔**。
        try:
            json.loads(source)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{path.name} 不是合法 JSON：{exc}")
        hits += [f"{path.name}：{suspect}" for suspect in ACCOUNT_ID_PATTERN.findall(source)]

    assert hits == [], f"deploy/aws/*.json 不可以寫死 12 位數的 AWS 帳號 ID：{hits}"

    # 本 phase 的兩份一定會用到帳號 ID（provider ARN、ECR／實例 ARN），所以佔位符必須在
    for filename in ("github-oidc-trust.json", "github-deploy-policy.json"):
        assert "<ACCOUNT_ID>" in (DEPLOY_AWS_DIR / filename).read_text(encoding="utf-8"), (
            f"{filename} 應該用 <ACCOUNT_ID> 佔位，而不是真的帳號"
        )

    # ★ 2026-09-03（Phase 95 順手：93 review deferred minors，裁決 R18 ①）
    #   實例 ID 也是一樣的規矩，而且它比帳號 ID 更該藏：
    #   帳號 ID 在每個 ARN 裡都看得到，實例 ID 則是「那台機器」的直接指名。
    #   ACCOUNT_ID_PATTERN 抓不到它（`i-0123456789abcdef0` 不是 12 位純數字），
    #   所以只能正面斷言佔位符還在。
    assert "<INSTANCE_ID>" in (DEPLOY_AWS_DIR / "github-deploy-policy.json").read_text(
        encoding="utf-8"
    ), "github-deploy-policy.json 的 SendCommand 資源要用 <INSTANCE_ID> 佔位，不是真的實例 ID"


# ---------------------------------------------------------------------------
# Phase 94：CD 工作流程（design6 D16、§12 Demo 3）
#
# 這六顆掃的是 .github/workflows/deploy.yml。掃它而不是「跑它」的理由很實際：
# 一次真的 CD 要 5〜15 分鐘、要 AWS 憑證、還會真的推映像到 ECR——
# 那是 §4.8 的 Demo 3（人工做一次）該做的事，不是每次 pytest 都該做的事。
# 這六顆守的是「**設定沒有被改壞**」，而設定改壞了的症狀全部是安靜的：
#   platforms 被改成別的架構 -> 映像推上去了，EC2 卻拉下來跑不動（exec format error）
#   target 掉了              -> 推上去的是 app 映像（uvicorn），工人永遠不會啟動
#   tag 沒有 sha             -> 只剩會動的 latest，永遠回不去上一版、也證明不了跑的是新的
#   workflows 綁錯名字       -> CD 從此不再被觸發，而且**不會有任何錯誤訊息**
#
# ⚠ 這六顆用 regex 讀「原始文字」，不用檔頭那個 yaml：要釘的三樣東西 YAML 解析器都看不到
#   ——註解（safe_load 會丟掉）、tags: 的縮排與行數（解析後只剩一個字串）、
#   ${{ … }} 到底是不是 head_sha（對 YAML 只是普通字串）。
# ---------------------------------------------------------------------------

WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"


def read_deploy_workflow() -> str:
    """讀 .github/workflows/deploy.yml 的原始文字。"""
    return (WORKFLOWS_DIR / "deploy.yml").read_text(encoding="utf-8")


def test_CD綁在test工作流程成功之後():
    """D16：CI 綠了才部署。五件事一起釘（少一件就會出現不同的壞法）。

    1. workflows: ["test"]  -> 綁的是既有 CI 的 name。打錯字的話 CD 從此**永遠不觸發**，
       而且 GitHub **不會**給任何錯誤訊息（它只是找不到符合的事件）。
    2. types: [completed]   -> workflow_run 只有這個型別會在 CI 跑完的那一刻送出事件。
    3. branches: [main]     -> 只有 main 上跑成功的 CI 才觸發部署。
    4. conclusion == 'success' -> workflow_run 不管 CI 成功失敗都會觸發，
       所以 job 層的 if 是**唯一**的守門。少了它，CI 紅的那一版照樣被部署。
    5. event == 'push'         -> test 也會被 pull_request 觸發（含 fork 來的 PR），而
       workflow_run 跑在預設分支上下文、拿得到 secret（官方文件原文：「able to access
       secrets and write tokens, even if the previous workflow was not」）。

    ★ 前三條一律「行首錨定 ＋ re.M」（與同檔 target:／platforms: 同形），2026-09-03
      fix round 1 改。原因是 deploy.yml 的註解裡**逐字寫著** `branches: [main]`
      （那段註解正在解釋這個 key 的意思），所以沒錨定的 re.search 連註解都會命中
      ——把 `on:` 底下真的那一行刪掉，測試照樣綠。掃註解的測試守不住任何東西。
    """
    text = read_deploy_workflow()

    assert re.search(r"^name:\s*deploy\s*$", text, re.M), "workflow 的 name 必須是 deploy"
    assert re.search(r'^\s*workflows:\s*\[\s*"?test"?\s*\]\s*$', text, re.M), (
        "workflow_run 必須綁既有 CI 的 name（test）——名字打錯的話 CD 會安靜地永遠不觸發"
    )
    assert re.search(r"^\s*types:\s*\[\s*completed\s*\]\s*$", text, re.M), (
        "types 必須是 completed——那是 workflow_run 唯一會在 CI 跑完時送出的事件型別"
    )
    assert re.search(r"^\s*branches:\s*\[\s*main\s*\]\s*$", text, re.M), (
        "只有 main 上跑成功的 CI 才觸發部署（總覽 §10 追認項 b：分支是 main 不是 master）"
    )
    assert re.search(r"workflow_run\.conclusion\s*==\s*'success'", text), (
        "workflow_run 不管成功失敗都會觸發，job 的 if 是唯一的守門"
    )
    assert re.search(r"workflow_run\.event\s*==\s*'push'", text), (
        "只有 push 觸發的 test 才部署——PR（含 fork）觸發的 test 完成時不准拿 secret 去推映像"
    )


def test_CD要求id_token寫入權限():
    """沒有 id-token: write 就拿不到 OIDC 令牌，整套 Phase 93 都用不上。

    症狀很難聯想：configure-aws-credentials 會失敗在
    "Unable to get ACTIONS_ID_TOKEN_REQUEST_URL"——看起來像 AWS 的問題，
    其實是 GitHub 這邊沒開權限。

    順便釘 contents: read：permissions 一旦明寫，沒列到的權限**一律變成 none**，
    漏了它 actions/checkout 會拿不到程式碼。

    ★ 兩條都「行首錨定 ＋ re.M」（2026-09-03 fix round 1）：理由與上一顆相同
      ——掃得到註解的斷言，等於允許「把真的那一行刪掉、只留下解釋它的註解」。
    """
    text = read_deploy_workflow()

    assert re.search(r"^\s*id-token:\s*write\s*$", text, re.M), (
        "沒有 id-token: write 就拿不到 OIDC 令牌"
    )
    assert re.search(r"^\s*contents:\s*read\s*$", text, re.M), (
        "明寫 permissions 之後，checkout 需要的讀取權要補上"
    )


def test_CD建linux_amd64與linux_arm64的映像():
    """2026-09-03 改判：真機兩段都是 x86_64（92-A t3.xlarge、92-B g4dn.xlarge），
    CD 必須推多架構 manifest。

    漏掉 amd64 的症狀是安靜的：CD 一路綠燈，EC2 拉下來 docker run 才炸
    "exec format error"——而那個訊息出現在**遠端機器的 systemd log 裡**，
    不在 Actions 頁面上，所以你會以為部署成功了。
    漏掉 arm64 則是以後 Graviton／本機 ARM 對照沒有映像。
    """
    text = read_deploy_workflow()

    platforms = re.findall(r"^\s*platforms:\s*(\S+)\s*$", text, re.M)
    assert platforms == ["linux/amd64,linux/arm64"], (
        f"必須建 linux/amd64,linux/arm64 這兩種架構，現在是 {platforms}"
    )


def test_CD打的是cloud_worker這個target():
    """Phase 90 的 Dockerfile 是 base -> cloud-worker -> app（app 刻意放最後）。

    不指定 target 的話，docker build 會停在**最後一段**＝ app 映像（跑 uvicorn 的那個）。
    推上去之後 EC2 會啟動一個 uvicorn，SQS 訊息永遠沒人收——
    而且 systemd 顯示服務「running」，看起來一切正常。
    """
    text = read_deploy_workflow()

    assert re.search(r"^\s*target:\s*cloud-worker\s*$", text, re.M), (
        "target 必須是 cloud-worker；不指定會蓋出最後一段（app）的映像"
    )


def test_CD的tag含commit的sha():
    """總覽 §10 追認項 e：同時推 <sha> 與 latest，但驗證不靠 latest（D16）。

    只有 latest 的話：
      - 回不去上一版（latest 永遠指向最後推的那一份）
      - 證明不了「EC2 上跑的是新映像」（拉 latest 永遠「是最新的」）
    所以 <sha> 那個 tag 是必要的，而且它必須是 workflow_run 帶的 head_sha
    （＝ CI 實際測過的那一版），不是 github.sha（見 §7 陷阱 2）。
    """
    text = read_deploy_workflow()

    match = re.search(r"^([ ]*)tags:[ ]*\|[ ]*\n((?:\1[ ]+\S.*\n)+)", text, re.M)
    assert match, "找不到 tags: | 區塊"
    tag_lines = [line.strip() for line in match.group(2).splitlines() if line.strip()]

    assert len(tag_lines) == 2, f"應該恰好兩個 tag（<sha> 與 latest），現在是 {tag_lines}"
    assert any("github.event.workflow_run.head_sha" in line for line in tag_lines), (
        "其中一個 tag 必須是 CI 測過的那個 commit 的 sha（head_sha，不是 github.sha）"
    )
    assert any(line.endswith(":latest") for line in tag_lines), (
        "另一個 tag 是 latest，給 EC2 開機時的 docker pull 用（systemd 的 ExecStartPre）"
    )


def test_CD沒有寫死任何AWS金鑰():
    """design6 §6「機密不進文件」＋ Phase 93 的整個 OIDC 就是為了不必放金鑰。

    ⚠ 這一顆會**掃到 deploy.yml 的註解**。所以寫註解解釋「這裡不放金鑰」時，
      不可以把那兩個環境變數的名字打出來——要寫成「長期金鑰」「access key」這種說法。
      （這不是龜毛：一顆會被自己的註解弄紅的測試，遲早會被人改成不掃註解，
        那時它就真的守不住任何東西了。）
    """
    text = read_deploy_workflow()

    for keyword in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "aws-access-key-id",
        "aws-secret-access-key",
    ):
        assert keyword not in text, f"CD 不可以出現任何長期金鑰的設定：{keyword}"

    # 防呆錨點：確認它真的走 OIDC（不是把整段刪光所以「沒有金鑰」）
    assert "secrets.AWS_DEPLOY_ROLE_ARN" in text, "CD 必須用 Phase 93 的角色 ARN 換臨時憑證（OIDC）"
    assert re.search(r"aws-actions/configure-aws-credentials@v\d+", text), (
        "換憑證那一步必須是 aws-actions/configure-aws-credentials（釘大版 @vN，見 §4.1）"
    )


# ---------------------------------------------------------------------------
# 【補A】§8 錯誤表第 7 列的缺口：雲端看圖三次失敗 ＝ **整筆失敗**，不是 fallback 本機
#
# 為什麼這是缺口：P79 釘了「結果說看不懂 -> job failed、不留照片」，
# P87 釘了「工人那邊真的試了 3 次」。但**沒有人**釘住兩者之間那件事——
# 「本機收到 understood=false 之後，會不會好心地再用本機模型看一次」。
#
# 總覽 §10 追認項 g 的裁決：**不會，也不准**。理由有兩個：
#   1. 遠端明明活著，只是 AI 看不懂——本機再看三次多半也一樣
#   2. 那會把「3 次」變成「6 次」，違反 design5 D10 的重試上限語意
# 這件事沒有任何執行期訊號（照片一樣不會出現、job 一樣是 failed），
# 唯一看得出來的是「run_ingest_job 有沒有被呼叫」——所以用 monkeypatch 數它。
# ---------------------------------------------------------------------------

NOT_UNDERSTOOD = PhotoUnderstanding(understood=False)


class WorkerMailbox(FakeMailbox):
    """本機在等結果的那一刻，「另一台機器上的工人」剛好把工作做完了。

    ★ 寫法**沿用既有慣例**：tests/integration/test_gated_ingest.py 與
      tests/integration/test_cloud_roundtrip.py 各自都有一個同名的子類別
      （測試檔之間不互相 import，所以刻意各寫一份）。
      本檔這一份與 test_cloud_roundtrip.py 那一份幾乎逐字相同，差別只有一個：
      這裡餵給工人的是「三次都看不懂」的 ScriptedVLM。

    為什麼要這樣安排：本機端是**同步**的——run_gated_ingest_job 先 submit，
    再 wait_result 長輪詢。測試只有一條執行緒，工人若不在「本機開始等」的那一刻
    動手，wait_result 會空等到逾時然後 fallback，根本走不到「雲端說看不懂」那條路。

    ⚠ 刻意**不用** monkeypatch 換掉 CloudRoute.wait_result：那會把產品碼的方法
      整支換掉，讀測試的人得先確認「換掉之後還有沒有在測原本那支」。
      子類只多接一個 hook，submit()／wait_result()／process_job_message() 三者
      **全部都是真的**（test_cloud_roundtrip.py 的檔頭把這個取捨寫得更詳細）。
    """

    def __init__(self, vlm) -> None:
        super().__init__()
        self.vlm = vlm

    def receive_result(self, wait_seconds: int):
        message = self.receive_job(0)
        while message is not None:
            cloud_worker.process_job_message(self, message, self.vlm)
            message = self.receive_job(0)
        return super().receive_result(wait_seconds)


def test_雲端看圖三次失敗是整筆失敗不是fallback本機(client, monkeypatch):
    """遠端活著、只是看不懂 -> job failed、零照片、S3 清空、**不重跑本機**。

    ⚠ monkeypatch 兩個模組的同名屬性：
        Phase 78 的 gated_ingest.py 寫的是 `ingest_job.run_ingest_job(...)`（帶模組名），
        所以蓋 ingest_job 那一個就攔得到；第二個 setattr 是保險——哪天有人改成
        `from app.services.ingest_job import run_ingest_job`，那個名字會綁在 gated_ingest
        模組上，只蓋 ingest_job 就攔不到了。兩個都蓋，這顆才不會因為 import 風格而假綠。
    """
    local_route_calls: list[str] = []

    def record_local_route(job_id: str, **kwargs) -> None:
        local_route_calls.append(job_id)

    monkeypatch.setattr(ingest_job, "run_ingest_job", record_local_route)
    if hasattr(gated_ingest, "run_ingest_job"):
        monkeypatch.setattr(gated_ingest, "run_ingest_job", record_local_route)

    worker_vlm = ScriptedVLM([NOT_UNDERSTOOD, NOT_UNDERSTOOD, NOT_UNDERSTOOD])
    mailbox = WorkerMailbox(worker_vlm)
    route = cloud_ingest.CloudRoute(mailbox, FakeProbe(True), timeout_seconds=5)
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: route

    response = client.post(
        "/photos", files={"file": ("receipt-2026.png", make_png_bytes(), "image/png")}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    跑完任務(job_id)

    assert worker_vlm.calls == 3, f"雲端工人應該看圖恰好 3 次，實際 {worker_vlm.calls} 次"
    assert local_route_calls == [], (
        "雲端看不懂 ＝ 整筆失敗（總覽 §10 追認項 g）；"
        f"不可以再跑一次本機的 run_ingest_job：{local_route_calls}"
    )
    job = 目前的任務清單().get(job_id)
    assert job is not None and job["status"] == "failed", f"job 應該標 failed：{job}"
    assert photo_repository.count_photos() == 0, "看不懂就不留任何 photo 列"
    assert mailbox.objects == {}, "失敗路徑也要把 S3 的三個物件清乾淨（§8 第 7 列）"
    assert not staging_service.staging_path(job_id, "image/png").exists(), "staging 要刪掉"


# ---------------------------------------------------------------------------
# 【補B】§8 錯誤表第 2 列的另一半：遠端不可用時，**HTTP 仍然 202**
#
# 為什麼這是缺口：P78 釘的是 worker 那一半（走 run_ingest_job、caplog 有
# fallback=local reason=remote_unavailable）。但 design6 §0 的第 6 條禁止講的是
# **HTTP 那一半**：「遠端不可用時上傳不准改 5xx、不准讓使用者重傳」。
#
# 這一顆從**使用者的角度**走一遍：探測說「沒開」的情況下，
# POST /photos 仍然 202、body 仍然恰三鍵、跑完任務之後照片仍然入庫一列。
#
# ⚠ 本機看圖那顆假件一定要自己換成「看得懂」的：conftest 的 wire_fake_ai 預設掛的是
#   FakeVLM()＝看不懂，fallback 走本機路時會試三次然後標 failed，列數永遠是 0。
# ---------------------------------------------------------------------------

MENU_UNDERSTANDING = PhotoUnderstanding(
    understood=True,
    text="某間咖啡店的菜單，拿鐵 120 元",
    category="飲食",
    location="咖啡店",
    items=["拿鐵"],
)


@pytest.fixture
def client_without_server_exceptions():
    """raise_server_exceptions=False：讓伺服器內部錯誤變成 500 回應而不是往外炸。

    這一顆要驗的正是「**不會**變成 5xx」，所以必須用這個 client——
    用一般的 client 的話，真的壞掉時測試會炸在 raise，看不到狀態碼是幾。
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_遠端不可用時上傳仍然回202不會變5xx(client_without_server_exceptions):
    """design6 §0 禁止第 6 條、D10：遠端關掉時使用者**完全無感**。"""
    mailbox = FakeMailbox()
    route = cloud_ingest.CloudRoute(mailbox, FakeProbe(False), timeout_seconds=5)
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(MENU_UNDERSTANDING)  # fallback 用的本機看圖
    app.dependency_overrides[get_privacy_gate] = lambda: FakePrivacyGate(Verdict.NON_SENSITIVE)
    app.dependency_overrides[get_cloud_route] = lambda: route

    response = client_without_server_exceptions.post(
        "/photos", files={"file": ("menu-2026.png", make_png_bytes(), "image/png")}
    )

    assert response.status_code == 202, f"遠端關掉不可以變成 5xx：{response.status_code}"
    assert set(response.json()) == {"job_id", "filename", "content_type"}, (
        "202 的回應形狀與增量五逐字相同（使用者看不到 route）"
    )
    job_id = response.json()["job_id"]
    assert photo_repository.count_photos() == 0, "202 只代表收下了，這一刻還沒入庫"

    跑完任務(job_id)

    assert photo_repository.count_photos() == 1, "fallback 之後照片仍然要入庫（D10）"
    assert 目前的任務清單().get(job_id) is None, "成功＝job 被刪掉（與增量五同語意）"
    assert mailbox.put_calls == 0, "探測不通過就不該有任何 S3 呼叫"


# ---------------------------------------------------------------------------
# 【掃A】§0 禁止第 4 條／§1.2 第 8 列／§8 第 10 列：不做 NAT／EIP／ALB／Lambda／ECS
#
# ⚠ 關鍵字刻意分兩組，而且收得很窄——寬一點的字**全部**會假紅：
#   - Python 檔絕對不能掃裸的 "lambda:"。`lambda: FakeVLM(...)` 這種匿名函式
#     在本專案滿地都是（dependency_overrides 幾乎每一行都有），掃了會一片假紅。
#   - 同理不能掃裸的 "ecs:"：雖然 "services:" 裡沒有這四個字連在一起，
#     但把它放進 Python 那一組遲早會撞到別的東西。
#   所以：「IAM 動作前綴」那一組只掃**設定檔**（JSON／YAML），
#         Python 那一組改掃「boto3 建 client 的長相」與資源名稱。
#
# 📌 2026-09-03 校準時**對現況的每一個檔實跑過**這兩組樣式，全部**零命中**、不會首跑假紅
#    （而且刻意挑了「含 Terminate 的 deploy.yml」與「含 ExecStartPre 的四個檔」當對照組，
#      確認邊界條件真的擋住了那兩個假紅）：
#      app/ 全樹（.py）
#      deploy/aws/{mac-policy,s3-lifecycle,worker-role-trust,worker-role-policy}.json
#      deploy/ec2/{personaldocai-worker.service,user-data.sh,worker.env.example}
#      compose.yaml、compose.dev.yaml、.github/workflows/test.yml
#      Phase 94 將寫的 .github/workflows/deploy.yml（內容取自 phase-94 §4.3）
#      Phase 93 將寫的 deploy/aws/{github-oidc-trust,github-deploy-policy}.json
#        （內容取自 phase-93 §4.3／§4.4；裡面只有 sts:／ecr:／ssm:／ec2: 這些字，
#          `ecr:` 不會被 `ecs:` 誤中、`arn:aws:ec2:` 也不會——樣式收的是 ecs: 不是 ec2:）
# ---------------------------------------------------------------------------

# 設定檔（deploy/**、.github/workflows/*.yml、compose*.yaml）用的樣式，**兩組**：
#   前半＝資源名與 CLI 子指令，兩側都要求「不是英文字母」（`(?<![A-Za-z])…(?![A-Za-z])`）
#   後半＝IAM 動作前綴 `lambda:`／`ecs:`／`rds:`，前面必須不是字元或減號
# re.I：NatGateway／natgateway／NAT_Gateway／ElastiCache 都要抓得到。
#
# ⚠ **兩側的邊界條件不可以拿掉，也不可以把關鍵字放寬成裸字**（2026-09-03 校準時
#   由另一位校準者點名的假紅陷阱，實查驗證過）：
#     * 裸的 `nat` 在 re.I 下會命中 **Termi·NAT·e**——`deploy.yml` 裡就有這個字
#     * 裸的 `ecs` 在 re.I 下會命中 **Ex·ecS·tartPre**——`deploy/ec2/` 有四個檔在用
#     * 沒有 `(?<![\w-])` 的話，`keywords:`／`records:`／`specs:` 這種普通 YAML 鍵
#       會被 `rds:`／`ecs:` 誤中
#   所以資源名一律寫**完整**（`nat[ _-]?gateway`，不是 `nat`），動作前綴一律**帶冒號**。
#
# ⚠ 刻意**不掃**裸的 `alb`：它太短，而且真的要開 ALB 一定會在設定裡留下
#   `elasticloadbalancing`（IAM 動作前綴）或 `elbv2`（CLI／SDK 的服務名）——掃那兩個就夠，
#   掃 `alb` 只是在替未來的自己埋假紅。
CONFIG_FORBIDDEN = re.compile(
    r"(?<![A-Za-z])(?:nat[ _-]?gateway|elastic[ _-]?ip|allocate-address"
    r"|elasticloadbalancing|elbv2|fargate|elasticache)(?![A-Za-z])"
    r"|(?<![\w-])(?:lambda|ecs|rds):",
    re.I,
)

# app/ 的 .py 用的關鍵字（全部轉小寫之後比對）。
# 只掃「真的會建出那些資源」的長相，不掃裸關鍵字（理由同上：`lambda:` 這種匿名函式
# 在 dependency_overrides 裡滿地都是，掃了會一片假紅）。
CODE_FORBIDDEN = (
    "natgateway",
    "nat_gateway",
    "nat-gateway",
    "allocate_address",
    "allocate-address",
    "elasticloadbalancing",
    "elasticache",
    "fargate",
    'client("lambda"',
    'client("ecs"',
    'client("rds"',
    'client("elbv2"',
)


def test_產品碼與部署檔都沒有NAT或EIP或ALB或Lambda或ECS字樣():
    """design6 §0 禁止第 4 條：這些服務全都沒有需求，而且 NAT 東京約 $45／月。

    ⚠ 不掃 GPU／g4dn／nvidia：2026-09-03 改判工人就是 g4dn 上自裝 Ollama。

    掃三棵樹：app/（產品碼）、deploy/（IAM policy 與 EC2 開機腳本）、
    .github/workflows/（CI 與 CD）＋ compose*.yaml。

    刻意**不掃** docs/、LAUNCH.md、CLAUDE.md：那些文件本來就合法地寫著「禁止 NAT」
    這幾個字，掃了只會假紅。文件那一半交給 §4.6 的人工檢查（describe-nat-gateways）。
    """
    violations: list[str] = []

    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        hits = [keyword for keyword in CODE_FORBIDDEN if keyword in source]
        if hits:
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：{hits}")

    config_files: list[Path] = []
    for pattern in ("deploy/**/*", ".github/workflows/*.yml", "compose*.yaml"):
        config_files += [path for path in PROJECT_ROOT.glob(pattern) if path.is_file()]
    for path in sorted(config_files):
        hits = CONFIG_FORBIDDEN.findall(path.read_text(encoding="utf-8"))
        if hits:
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：{hits}")

    assert violations == [], (
        f"design6 §0 禁止第 4 條：不做 NAT／EIP／ALB／RDS／Lambda／ECS：{violations}"
    )

    # 防呆錨點：確認真的掃到東西了（目錄被改名／glob 寫錯要紅在這裡，不是默默全過）
    assert (PROJECT_ROOT / "deploy" / "aws").is_dir(), "deploy/aws/ 應該存在（Phase 82 起）"
    assert (PROJECT_ROOT / ".github" / "workflows" / "deploy.yml").exists(), (
        ".github/workflows/deploy.yml 應該存在（Phase 94）"
    )


# ---------------------------------------------------------------------------
# 【掃B】總覽 §7 鐵律 11：compose.yaml 本增量零改動
# ---------------------------------------------------------------------------


# 這一組是**九個逐字的變數名**，不是「§2.4.2 的全部」：
#   六個來自總覽 §2.4.2（AWS_REGION／S3_BUCKET／SQS_JOBS_QUEUE_URL／SQS_RESULTS_QUEUE_URL／
#   EC2_WORKER_INSTANCE_ID／CLOUD_ROUTE）＋三個 boto3 自己去環境撈、刻意不進 config 的憑證名
#   （AWS_ACCESS_KEY_ID／AWS_SECRET_ACCESS_KEY／AWS_ENDPOINT_URL）。它們**只准住在 .env**；
#   哪天有人在 compose.yaml 的 environment: 底下加了其中任何一個，這一顆就紅。
#
# §2.4.2 其餘那幾個（CLOUD_RESULT_TIMEOUT_SECONDS／EC2_PROBE_TTL_SECONDS／WORKER_VERSION，
# 以及 2026-09-03 追加的 WORKER_VLM_BACKEND）**不在這一組**，而且 Phase 90 那顆掃的四個前綴
# 是 `AWS_`／`S3_BUCKET`／`SQS_`／`CLOUD_ROUTE`（不是 `CLOUD_`／`EC2_`／`WORKER_`），
# 所以也掃不到它們——這是刻意的：那四個是逾時秒數、快取秒數、git sha 與後端名字，
# 沒有一個是機密或會指向某個帳號的資源，寫進 compose 也不構成「把 bucket 名推上 public repo」。
# 真正要擋的是「機密／指名資源」那九個。
AWS_SETTING_NAMES = (
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "S3_BUCKET",
    "SQS_JOBS_QUEUE_URL",
    "SQS_RESULTS_QUEUE_URL",
    "EC2_WORKER_INSTANCE_ID",
    "CLOUD_ROUTE",
)


def test_compose沒有為了雲端新增任何服務():
    """AWS 的設定全部走 .env（app 與 worker 早就 bind-mount 了它），compose 零 AWS 字樣。

    為什麼不加第五個服務：本機**不跑** cloud_worker 容器——那是 EC2 的事。
    丁段（Phase 88／90）在 Mac 上跑工人時用的是 `docker run`／`python -m`，
    刻意不進 compose，這樣「常駐四個服務」這件事就永遠不會被雲端污染。

    分工（兩顆各守各的，不重複）：
      Phase 90 的 test_compose_yaml沒有新增服務也沒有AWS設定 守「多階段沒波及 compose」
        ——build: . 兩處、零 target:、image: personaldocai-app 兩處、服務恰四個，
        另外掃 AWS_／S3_BUCKET／SQS_／CLOUD_ROUTE 四個**前綴**。
      本顆守「九個變數名逐字都不在」＋「工人的服務名不在」——比前綴那一組更精確，
        而且把 cloud_worker／cloud-worker 這兩個名字也擋掉（前綴掃不到它們）。
    服務清單這裡也看一眼，但**沿用 Phase 90 的 compose_services()**（同一個檔的模組層 helper），
    不自己再寫一份 regex：直接對整份 compose.yaml 抓 `^  ([a-z][\\w-]*):$` 會連
    volumes: 底下的 pgdata:／redisdata: 一起抓進來（Phase 90 實測回 6 個而不是 4 個）。
    """
    source = read_compose()

    for name in AWS_SETTING_NAMES:
        assert name not in source, (
            f"AWS 的設定走 .env，不進 compose.yaml（總覽 §7 鐵律 11）：{name}"
        )
    for keyword in ("cloud_worker", "cloud-worker"):
        assert keyword not in source, (
            f"本機不跑雲端工人容器，那是 EC2 的事（總覽 §7 鐵律 11）：{keyword}"
        )

    # 錨點：確認讀到的真的是那份 compose（服務仍是四個；主斷言在 Phase 90 那顆）
    assert compose_services() == ["db", "redis", "app", "worker"]


# ---------------------------------------------------------------------------
# 【掃C】§5：不新增使用者打的 REST 端點
# ---------------------------------------------------------------------------


def test_端點仍是22支而且openapi零DELETE(client):
    """design6 §5 明文「本增量不要求為雲端管線新增使用者打的 REST 端點」。

    ⚠ 為什麼還要再寫一顆（既有已經有三顆在數 22）：
      既有那三顆是**增量五**留下來的證據，證明的是「增量五之後是 22」。
      本檔是**增量六自己的**證據——半年後有人問「增量六到底有沒有偷加端點」，
      答案要在增量六的收尾檔裡找得到，而不是靠「別的增量的測試還是綠的」去推論。
      這一顆刻意只數總數與 DELETE，不重抄那 22 支的清單
      （逐支列名由 test_design5_error_paths.py::test_端點恰好是這22支 守著）——
      **分工，不是重複**。

    ⚠ 不要用 app.routes 清點——FastAPI 0.141 有 _IncludedRouter 的已知坑，
      路由不會被攤平，數出來的數字是錯的。一律走 /openapi.json。
      WebSocket /camera/{token}/signal 依 FastAPI 的行為不進 openapi，不計入。
    """
    paths = client.get("/openapi.json").json()["paths"]
    operations = [(path, method) for path, item in paths.items() for method in item]

    assert len(operations) == 22, f"本增量端點恆為 22（design6 §5），現在是 {len(operations)}"
    assert [method for _, method in operations if method == "delete"] == [], (
        "系統仍然沒有任何刪除功能"
    )


# ---------------------------------------------------------------------------
# 【掃D】§0 禁止第 2 條／§4 第 1 條／§9 必釘第 7 條：佇列只放紙條，不放位元組
# ---------------------------------------------------------------------------


class RecordingS3:
    """AwsMailbox 建構時可以注入 client；塞這個進去就完全不會碰 boto3。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {}


class RecordingSqs:
    """把 send_message 收到的參數原樣留下來，讓測試檢查 MessageBody 長什麼樣。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}


def test_兩條佇列的訊息body都不含影像位元組():
    """design6 §0 禁止第 2 條：SQS 單則上限 1 MiB（2025 年中前 256 KB），一份多頁 PDF 幾十 MB。

    ⚠ 這一顆走的是**真的序列化程式碼**（AwsMailbox.send_job／send_result），
      只是把 boto3 的 client 換成記帳假件——所以它證明的是「真的送出去的那個 body
      長什麼樣」，不是「假件記了什麼」。

    Phase 83 已經有 test_send_job的body恰兩鍵／test_send_result的body恰一鍵；
    這一顆的角度不同：**兩條一起**、而且驗「解析得出來 ＋ 夠小 ＋ 沒有編碼過的影像」。
    """
    sqs = RecordingSqs()
    mailbox = AwsMailbox(
        bucket="不會用到",
        jobs_queue_url="https://sqs.example/jobs",
        results_queue_url="https://sqs.example/results",
        region="ap-northeast-1",
        s3=RecordingS3(),
        sqs=sqs,
        ec2=object(),
    )

    mailbox.send_job("job-abc", "documents/job-abc/input.png")
    mailbox.send_result("job-abc")

    assert len(sqs.sent) == 2, "應該恰好送出兩則（jobs 一則、results 一則）"
    for call in sqs.sent:
        body = call["MessageBody"]
        assert isinstance(body, str), "body 必須是字串"
        payload = json.loads(body)  # 位元組塞得進去的話這一行就會炸
        assert set(payload) <= {"job_id", "s3_key"}, (
            f"body 只准有 job_id 與 s3_key：{sorted(payload)}"
        )
        assert len(body.encode("utf-8")) < 1024, (
            f"body 應該只有幾十個位元組，現在是 {len(body.encode('utf-8'))}"
        )
        for marker in ("base64", "data:image", "\\x89PNG", "%PDF"):
            assert marker not in body, f"佇列訊息不可以帶影像：{marker}"


# ---------------------------------------------------------------------------
# 【掃E】D11／D13／§3「不做」第 2 條：工人不碰資料庫、不算 embedding
#
# ★ 分工（2026-09-03 校準裁決 R10）——**與 Phase 87 那顆互補，不重抄**：
#     tests/unit/test_cloud_worker_unit.py::test_工人不import資料庫與Celery與Redis
#       用 ast 掃 **import 名單**：黑名單（redis／celery／app.db／app.repositories／
#       app.dependencies／app.services.ingest_job／app.services.staging_service）
#       ＋ 白名單（只准那六個自家模組）＋ 禁相對 import。那一層已經很完整。
#     本顆掃 87 掃不到的三個面向：
#       ① **識別字**：程式裡有沒有用到向量／資料庫相關的名字（import 以外的路徑，
#          例如有人把 embeddings 當參數傳進來、或呼叫 mailbox 以外的東西）
#       ② **字串常數**：result.json 有沒有多一個 "embedding" 鍵；有沒有把模組路徑
#          寫成字串（importlib.import_module("app.db.session") 這種繞過 ast import 的寫法）
#       ③ **動態載入**：有沒有 importlib／__import__（有的話 ① ② 都擋不住）
#
# ⚠ 為什麼**不能**改成「掃全文文字（含註解）有沒有 photo_repository／embed」：
#   工人自己的模組 docstring 就寫著「⛔ 不寫 Postgres、不碰 photo_repository」與
#   「⛔ 不算 embedding」——那是**正確的文件**，掃全文會把它掃成違規（2026-09-03
#   校準時對實檔跑過：photo_repository 命中第 18／84 行、embed 命中第 19／171 行）。
#   所以字串比對一律走「**整個字串常數相等**」，長句 docstring 不會誤中。
# ---------------------------------------------------------------------------

WORKER_SOURCE = PROJECT_ROOT / "app" / "workers" / "cloud_worker.py"

# 識別字（變數、屬性、import 進來的名字）。工人碰到其中任何一個都是違規。
FORBIDDEN_WORKER_NAMES = {
    "get_embeddings",
    "embed_understanding",
    "embed_query",
    "embed_documents",
    "Embeddings",
    "OllamaEmbeddings",
    "FakeEmbeddings",
    "photo_repository",
    "get_connection",
    "insert_photo",
}

# 寫死的字串。比對**整個字串相等**，所以 docstring 裡的長句不會誤中，
# 但 dict 的鍵 "embedding" 與 importlib.import_module("app.db.session") 逃不掉。
FORBIDDEN_WORKER_STRINGS = {
    "embedding",
    "app.db",
    "app.db.session",
    "app.repositories",
    "app.repositories.photo_repository",
    "app.dependencies",
    "app.services.indexing_service",
    "app.services.ingest_job",
}


def test_工人不寫Postgres也不算embedding():
    """D11：EC2 只當工人（無 DB、無 Celery、無 Redis）；D13：向量一律本機 bge-m3。

    用 ast 而不是 grep：
      - 註解與 docstring 裡寫了「不碰 photo_repository」不會誤判成違規
      - `getattr(module, "insert_photo")` 這種寫法 grep 抓得零零落落，ast 一次抓齊
    """
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    names: set[str] = set()
    constants: set[str] = set()
    dynamic_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.add(node.value)

    # ① 識別字
    assert not (names & FORBIDDEN_WORKER_NAMES), (
        f"工人不碰資料庫、也不算向量（D11／D13）；出現了：{sorted(names & FORBIDDEN_WORKER_NAMES)}"
    )

    # ② 字串常數（result.json 的鍵 ＋ 用字串繞過 import 檢查的模組路徑）
    assert not (constants & FORBIDDEN_WORKER_STRINGS), (
        "工人的字串常數不可以是這些（result.json 不含 embedding 鍵、"
        f"也不准用字串指到資料庫層）：{sorted(constants & FORBIDDEN_WORKER_STRINGS)}"
    )

    # ③ 動態載入：有它的話 ① ② 都可以被組字串繞過去
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"importlib", "__import__"}:
            dynamic_imports.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr == "import_module":
            dynamic_imports.append(node.attr)
    assert dynamic_imports == [], (
        "工人不准動態載入模組（那會繞過 Phase 87 那顆 import 掃碼）："
        f"{sorted(set(dynamic_imports))}"
    )

    # ④ 兩個窄的 import 定錨（完整的黑白名單由 Phase 87 那顆守，這裡只點名兩個
    #    「一旦出現就代表向量或注入層被搬上工人」的模組，讓本顆的名字名副其實）
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    for forbidden in ("app.services.indexing_service", "app.dependencies"):
        offenders = sorted(
            name for name in imported if name == forbidden or name.startswith(forbidden + ".")
        )
        assert offenders == [], f"工人不可以 import {forbidden}（D11／D13）：{offenders}"

    # 防呆錨點：確認掃的真的是工人（檔案搬走／改名要紅在這裡）
    assert "def process_job_message(" in source
    assert "def main(" in source


# ---------------------------------------------------------------------------
# 【掃F】總覽 §7 鐵律 5：boto3 只准出現在 aws_mailbox.py
# ---------------------------------------------------------------------------

# 只比對**真的 import 敘述**（行首 + import/from + boto3 或 botocore），
# 不是掃裸的 "boto3" 五個字——這樣本檔自己提到 boto3（註解、豁免名單、斷言訊息）
# 不會把自己掃紅。樣式與 Phase 83 那顆逐字相同（含縮排＝函式裡的延遲 import 也抓得到）。
BOTO3_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:boto3|botocore)\b", re.M)

# 總覽 §2.7 定的三個放行檔。「放行」只是允許、不是要求：
# scripts/aws_check.py（Phase 84）其實走的是 AwsMailbox、沒有直接 import boto3，
# 留在名單裡不會讓這一顆變鬆。
BOTO3_ALLOWED_FILES = {
    "app/services/aws_mailbox.py",  # 全系統唯一的 AWS SDK 入口
    "tests/unit/test_aws_mailbox_unit.py",  # 它的單元測試（from botocore.exceptions import ClientError）
    "scripts/aws_check.py",  # host 手動用的連線檢查（不進映像）
}


def test_boto3唯一入口仍是aws_mailbox():
    """Phase 83 那顆只掃 app/；這一顆掃 app/ ＋ tests/ ＋ scripts/ 三棵樹。

    為什麼要拆成兩顆而不是把 83 那顆擴大：83 守的是「產品碼的分層」
    （cloud_ingest.py 只認 CloudMailbox Protocol，所以它的測試才用得動假信箱）；
    本顆守的是「**整個 repo** 只有那三個檔碰得到 AWS SDK」——
    包含測試自己。少了這一顆，有人在某顆測試裡 import boto3 直接打真 AWS，
    第五道安全網（wire_fake_cloud）就被繞過去了，而且完全沒有訊號。
    """
    violations: list[str] = []
    for tree_root in ("app", "tests", "scripts"):
        for path in sorted((PROJECT_ROOT / tree_root).rglob("*.py")):
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            if relative_path in BOTO3_ALLOWED_FILES:
                continue
            if BOTO3_IMPORT.search(path.read_text(encoding="utf-8")):
                violations.append(relative_path)

    assert violations == [], (
        f"boto3 只准出現在 app/services/aws_mailbox.py（總覽 §7 鐵律 5）：{violations}"
    )

    # 反過來也釘一次：入口檔**必須**真的 import 了，不然這一顆會變成永遠綠的裝飾品
    entry_point = PROJECT_ROOT / "app" / "services" / "aws_mailbox.py"
    assert BOTO3_IMPORT.search(entry_point.read_text(encoding="utf-8")), (
        "aws_mailbox.py 應該要 import boto3"
    )


# ---------------------------------------------------------------------------
# 【掃G】§4 最後一條／總覽 §7 鐵律 13：photo 表不加任何欄
# ---------------------------------------------------------------------------

# 增量五結束時 photo 表的欄位集合（db/schema.sql 逐欄對過；2026-09-03 再對一次，相同）。
# 增量六**一欄都不准動**：route／privacy 住 JobStore（design6 §4 明文）。
PHOTO_COLUMNS = {
    "id",
    "text",
    "category",
    "folder_id",
    "location",
    "items",
    "content_time",
    "uploaded_at",
    "embedding",
    "original_path",
    "thumbnail_path",
    "content_type",
    "suggested_category",
    "suggested_entity",
    "suggested_task_title",
    "suggested_task_due",
}


def test_photo表沒有為了雲端新增任何欄位():
    """design6 §4：「photo 表不加 job_id、不加處理狀態欄（design5 禁令仍有效）」。

    ⚠ 比對的是**整個集合逐字相等**，不只是「沒有 route 這一欄」。
      只檢查黑名單的話，有人加一個叫 cloud_state 的欄位照樣過關。

    conftest 已把 DATABASE_URL 指到測試庫，而測試庫是用 db/schema.sql 重建的——
    所以問的是「schema.sql 現在長什麼樣」，正式庫走同一份遷移對齊。
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'photo'
                ORDER BY column_name;
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}

    assert columns == PHOTO_COLUMNS, (
        f"photo 表本增量零改動；多出來：{sorted(columns - PHOTO_COLUMNS)}；"
        f"少掉了：{sorted(PHOTO_COLUMNS - columns)}"
    )


# ---------------------------------------------------------------------------
# 【掃H】D6／§0 禁止第 5 條／§1.2 第 7 列：兩扇門完全分開
# ---------------------------------------------------------------------------


def test_隱私閘門不會去碰AI後端開關():
    """D6（2026-09-01）：閘門**跟著**頁首開關走，但**不准寫入／關掉**它。

    閘門短問讀 config.AI_BACKEND 選本機或雲端 VLM（與 get_vlm 同一套）。
    禁止的是「敏感就強制把開關撥回本機」或寫入 AI_BACKEND。
    """
    for filename in ("privacy_gate.py", "gated_ingest.py"):
        source = (PROJECT_ROOT / "app" / "services" / filename).read_text(encoding="utf-8")
        assert "AI_BACKEND =" not in source, f"{filename} 不可以寫入頁首的 AI 模型開關（D6）"
        assert "settings/ai-backend" not in source, f"{filename} 不可以打開關端點"


# ---------------------------------------------------------------------------
# Phase 95 順手：93 review deferred minors（裁決 R18）
#
# 上面三處是**改既有 93 那兩顆的斷言**（補 <INSTANCE_ID> 佔位、把裸的 json.loads
# 換成具名斷言、給 aud 加失敗訊息），顆數不變。這裡是 R18 ② 的那一顆新測試。
#
# 為什麼放在檔尾而不是插進 Phase 93 那一區：本檔的分區是**時間軸**
# （檔頭那張表寫著誰在哪個 phase 加了什麼），插進中間會讓那張表對不上。
# ---------------------------------------------------------------------------

# 部署角色的 inline policy 五段的 Sid，**依序**。順序也釘：policy JSON 是人在讀的，
# 「先登入、再推、再重啟、再看結果、最後查狀態」照著部署的實際步驟排。
DEPLOY_POLICY_SIDS = [
    "EcrLoginTokenIsAccountWide",
    "EcrPushOnlyToTheWorkerRepository",
    "SsmRestartOnlyThatOneInstance",
    "SsmReadTheCommandResult",
    "DescribeInstancesToSeeIfItIsRunning",
]

# 推一份映像到 ECR 真正需要的六個動作。多一個就是多給的權限
# （例如 ecr:DeleteRepository、ecr:BatchDeleteImage ＝ CD 有能力把整個 repo 刪掉）。
ECR_PUSH_ACTIONS = {
    "ecr:BatchCheckLayerAvailability",
    "ecr:BatchGetImage",
    "ecr:CompleteLayerUpload",
    "ecr:InitiateLayerUpload",
    "ecr:PutImage",
    "ecr:UploadLayerPart",
}


def test_部署policy恰五段而且SendCommand綁實例與document():
    """design6 §6「IAM 最小權限」：部署角色只能做「推那一個 repo ＋ 重啟那一台機器」。

    Phase 93 那顆 test_部署用的policy裡沒有寫死帳號ID 掃的是**機密**（帳號／實例 ID
    有沒有外洩）；這一顆掃的是**權限的形狀**——兩件不同的事，所以是兩顆。

    最需要釘的是 ssm:SendCommand 的 Resource：
      * 少了 `instance/<INSTANCE_ID>` 那一條（改成 `*`）＝ 這個角色可以對**帳號裡任何一台**
        EC2 下 shell 指令。CD 照樣綠燈，沒有任何訊號。
      * 少了 `document/AWS-RunShellScript` 那一條 ＝ 呼叫會被拒，
        錯誤訊息只說 "not authorized to perform: ssm:SendCommand"，
        完全看不出少的是 document 那一半（SendCommand 要**同時**授權實例與文件）。
    順便釘住「全檔零 iam:／零 Start／Stop／TerminateInstances」——
    那些是「順手多給一點」最常見的長相。
    """
    policy = json.loads((DEPLOY_AWS_DIR / "github-deploy-policy.json").read_text(encoding="utf-8"))
    statements = policy["Statement"]

    assert [statement["Sid"] for statement in statements] == DEPLOY_POLICY_SIDS, (
        f"部署 policy 應該恰好是這五段（順序也一樣）：{[s.get('Sid') for s in statements]}"
    )

    ecr_push = statements[1]
    assert set(ecr_push["Action"]) == ECR_PUSH_ACTIONS, (
        f"推映像恰好需要這六個動作，多一個都不要：{sorted(set(ecr_push['Action']))}"
    )
    assert ecr_push["Resource"].endswith(":repository/personaldocai-worker"), (
        f"只准推 personaldocai-worker 這一個 repo：{ecr_push['Resource']}"
    )

    send_command = statements[2]
    assert send_command["Action"] == "ssm:SendCommand"
    resources = send_command["Resource"]
    assert len(resources) == 2, f"SendCommand 的 Resource 恰兩條（實例 ＋ 文件）：{resources}"
    assert any("instance/<INSTANCE_ID>" in resource for resource in resources), (
        f"少了實例那一條＝可以對帳號裡任何一台 EC2 下 shell 指令：{resources}"
    )
    assert "arn:aws:ssm:ap-northeast-1::document/AWS-RunShellScript" in resources, (
        f"SendCommand 要**同時**授權實例與文件，少了文件那一半會被拒：{resources}"
    )

    source = (DEPLOY_AWS_DIR / "github-deploy-policy.json").read_text(encoding="utf-8")
    for forbidden in ("iam:", "ec2:StartInstances", "ec2:StopInstances", "ec2:TerminateInstances"):
        assert forbidden not in source, (
            f"部署角色不需要這個權限（design6 §6 最小權限）：{forbidden}"
        )
