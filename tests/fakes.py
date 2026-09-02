"""測試用的假件。真 AI／真時鐘的替身，讓測試結果可預期。"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections.abc import Callable
from datetime import datetime
from types import SimpleNamespace

from langchain_core.documents import Document
from PIL import Image

from app.core import config
from app.services.ask_workflow import RouteDecision
from app.services.cloud_ingest import MailboxMessage
from app.services.privacy_gate import PrivacyJudgement, Verdict
from app.services.staging_service import STAGING_EXTENSIONS
from app.services.vlm_service import PhotoUnderstanding

# ---------- 真的圖片位元組（Pillow 讀得開）----------
# 為什麼需要它：從 Phase 17 起系統會真的用 Pillow 把上傳的 bytes 打開來做縮圖。
# b"\x89PNG…" 這種手打的假位元組會讓 Pillow 直接拋 UnidentifiedImageError，
# 所以凡是「預期上傳成功」的測試，一律用下面的函式現產一張真的小圖。


def _image_bytes(width: int, height: int, image_format: str) -> bytes:
    """畫一張純色小圖並轉成該格式的位元組。"""
    buffer = io.BytesIO()  # 假裝成檔案的一段記憶體，不必真的寫到磁碟
    Image.new("RGB", (width, height), color=(200, 120, 60)).save(buffer, format=image_format)
    return buffer.getvalue()


def make_png_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 PNG。預設 40×20，小到幾乎不花時間。"""
    return _image_bytes(width, height, "PNG")


def make_jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    """產生一張真的 JPEG。"""
    return _image_bytes(width, height, "JPEG")


def make_large_png_bytes(side: int = 1200) -> bytes:
    """產生一張『真的很大』的 PNG（約 4 MB 以上），用來證明系統沒有檔案大小上限。

    刻意用隨機雜訊：純色圖片會被 PNG 壓成幾 KB，撐不出檔案大小。
    os.urandom(n)＝n 個隨機位元組；每個像素 3 個位元組（RGB）。
    """
    buffer = io.BytesIO()
    pixels = os.urandom(side * side * 3)
    Image.frombytes("RGB", (side, side), pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def make_pdf_bytes(pages: int = 1) -> bytes:
    """產生一份真的 PDF，每頁一張純色小圖（Phase 28）。

    Pillow 自己就會寫 PDF（save(format="PDF")），測試端因此不必多裝套件：
    save_all=True ＋ append_images=其餘頁 ＝ 把多張圖寫成多頁的同一份檔案。
    """
    first, *rest = [
        Image.new("RGB", (40, 20), color=(30 + index * 40, 120, 60)) for index in range(pages)
    ]
    buffer = io.BytesIO()
    first.save(buffer, format="PDF", save_all=True, append_images=rest)
    return buffer.getvalue()


class FakeVLM:
    """考試用的固定答案卡，不是正式看圖系統。

    測試會先指定「請當作收據、店名 Target」；understand() 照念，不呼叫 Ollama。
    沒給 result 時預設 understood=False（規格：看不懂 → 422、什麼都不存）。

    folders／entities／corrections 參數只是為了與 VLMClient 協定一致
    （Phase 18 加 folders、Phase 30 加 entities、Phase 35 加 corrections）：
    假件不會真的照著清單思考，但會把收到的三份清單記在
    last_folders／last_entities／last_corrections，
    讓測試可以驗「呼叫端真的把三份都傳進去了」。
    """

    def __init__(self, result: PhotoUnderstanding | None = None) -> None:
        self.result = result or PhotoUnderstanding(understood=False)
        self.calls = 0
        self.last_folders: list[dict] | None = None
        self.last_entities: list[dict] | None = None
        self.last_corrections: list[dict] | None = None

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        self.last_folders = folders
        self.last_entities = entities
        self.last_corrections = corrections
        return self.result


class ScriptedVLM:
    """照劇本演的看圖假件：第 1 次回什麼、第 2 次丟什麼，全部先寫好。

    給「重試」相關的測試用（Phase 59 起）。與 FakeVLM 的差別只有一個：
    FakeVLM 是**一張固定答案卡**（每次都回同一個結果），
    ScriptedVLM 是**一疊照順序翻的卡**，而且卡片可以是「丟這個例外」。

    script 裡每一項只能是兩種東西：
      - PhotoUnderstanding → 這一次就回它（understood=False 也是一種合法答案）
      - Exception 的實例   → 這一次就把它丟出去（模擬 Ollama 沒開、雲端 401、逾時）

    劇本演完還被呼叫 → 直接 AssertionError。這是刻意的：
    「多打了一次模型」是本 phase 最需要抓的錯（重試上限沒守住），
    默默重複最後一張卡會讓那種 bug 溜過去。
    """

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0
        self.last_folders: list[dict] | None = None
        self.last_entities: list[dict] | None = None
        self.last_corrections: list[dict] | None = None

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        assert self.calls < len(self.script), (
            f"ScriptedVLM 被呼叫第 {self.calls + 1} 次，但劇本只寫了 "
            f"{len(self.script)} 次——重試次數超過上限了嗎？"
        )
        item = self.script[self.calls]
        self.calls += 1
        self.last_folders = folders
        self.last_entities = entities
        self.last_corrections = corrections
        if isinstance(item, Exception):
            raise item
        return item


class FakeEntitySuggester:
    """「再建議一個實體」的固定答案卡，不呼叫 Ollama。

    建構子登記這次要挑哪一個名字（預設 None＝都不像，也就是最保守的答案）；
    calls 與 last_candidates 讓測試驗得出「候選空時根本沒問模型」
    與「exclude 掉的實體真的沒進候選清單」。
    """

    def __init__(self, result: str | None = None) -> None:
        self.result = result
        self.calls = 0
        self.last_candidates: list[dict] | None = None

    def pick(self, photo: dict, candidates: list[dict]) -> str | None:
        self.calls += 1
        self.last_candidates = candidates
        return self.result


# 規格例子與雙語測試裡會出現的詞。假的向量只認得這些詞，因此結果完全可預期。
VOCABULARY = [
    # 中文（規格 .feature 的例子用的詞）
    "收據",
    "風景",
    "照片",
    "購買",
    "Target",
    "Costco",
    "7-11",
    "海邊",
    "可樂",
    "洋芋片",
    "咖啡",
    "牛奶",
    "衛生紙",
    "飲料",
    # 英文（雙語測試用的詞）
    "Receipt",
    "receipt",
    "Cola",
    "cola",
    "Chips",
    "chips",
    "coffee",
    "milk",
    "drinks",
    "drink",
]

# 同義／跨語言對照：左邊的詞出現時，右邊的詞也會被算進向量。
# 這是在假件裡「模擬」多語 embedding 的效果——真的 bge-m3 天生就有這個能力，
# 假件必須手動列出來，測試結果才可預期。
SYNONYMS = {
    "飲料": ["可樂", "咖啡", "牛奶"],
    "drinks": ["可樂", "咖啡", "牛奶", "Cola", "cola"],
    "drink": ["可樂", "咖啡", "牛奶"],
    "receipt": ["收據"],
    "Receipt": ["收據"],
    "cola": ["可樂"],
    "Cola": ["可樂"],
}


class FakeEmbeddings:
    """決定論向量：同樣的文字永遠得到同樣的數字，且不需要任何 AI 服務。

    做法：每個出現過的詞用「雜湊」（把文字換算成一個固定的數字）決定它落在
    向量的哪個位置，該位置 +1；最後做「正規化」（把整條向量縮放成長度 1，
    只留下方向），cosine 相似度比的才會是「內容」而不是「字數多寡」。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * config.EMBEDDING_DIM
        vector[0] = 0.1  # 保底值，避免全零向量讓 cosine 距離算出 NaN
        for word in self._words(text):
            vector[self._slot(word)] += 1.0
        length = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / length for v in vector]

    @staticmethod
    def _words(text: str) -> list[str]:
        found = [word for word in VOCABULARY if word in text]
        for word in list(found):
            found.extend(SYNONYMS.get(word, []))
        return found

    @staticmethod
    def _slot(word: str) -> int:
        digest = hashlib.md5(word.encode("utf-8")).hexdigest()
        return int(digest, 16) % config.EMBEDDING_DIM


class FixedClock:
    """固定的「現在時間」，對應規格的 Given 現在時間為 "2026-08-18 10:00"。"""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


# 規格例子出現過的文字 → 對應的假 VLM 結果。
# 規格新增例子時，在這裡補一筆即可。
KNOWN_UNDERSTANDINGS: dict[str, PhotoUnderstanding] = {
    "在 Target 購買可樂與洋芋片的收據，日期 2026-08-10": PhotoUnderstanding(
        understood=True,
        text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
        category="收據",
        location="Target",
        items=["可樂", "洋芋片"],
        content_time="2026-08-10",
    ),
}


def understanding_for_text(text: str) -> PhotoUnderstanding:
    """依規格步驟給的文字，取出對應的假 VLM 結果。"""
    if text not in KNOWN_UNDERSTANDINGS:
        raise KeyError(
            f"沒有為這段文字準備假的 VLM 結果：{text}\n"
            "請到 tests/fakes.py 的 KNOWN_UNDERSTANDINGS 補一筆。"
        )
    return KNOWN_UNDERSTANDINGS[text]


# 規格例子與雙語測試裡的問題 → 應該得到的判斷結果
DEFAULT_ROUTE_DECISIONS: dict[str, RouteDecision] = {
    # 規格 .feature 的兩個中文例子
    "有哪些在 Target 拍的收據？": RouteDecision(
        mode="metadata", category="收據", location="Target", recent=False
    ),
    "我最近買過什麼飲料？": RouteDecision(mode="vector", recent=True),
    # 雙語測試用的英文問題
    "What drinks did I buy recently?": RouteDecision(mode="vector", recent=True),
    # 英文條件型問題：條件值照原文抽（小寫 target），交給 SQL 的 ILIKE 去比對。
    # 注意這裡刻意沒抽 category="receipt"——抽了也對不到中文的「收據」，
    # 因為系統不做跨語言翻譯對映（design.md §8.3 的已知限制）。
    "Which receipts were taken at target?": RouteDecision(
        mode="metadata", location="target", recent=False
    ),
    # ---- Phase 34 詢問三路：實體路與待辦路（design3.md §6 的目標問句）----
    # entity_name 刻意兩種語言都填中文的「我的 MacBook」：實體名單有注入 prompt，
    # 所以模型該把問句對回**清單裡的原文**，而不是照抄問句寫法（ROUTE_PROMPT 的例外規則）。
    "跟我 MacBook 有關的全部": RouteDecision(mode="entity", entity_name="我的 MacBook"),
    "Show me everything about my MacBook": RouteDecision(mode="entity", entity_name="我的 MacBook"),
    "這週要交什麼？": RouteDecision(mode="task", due_within_days=7),
    # 規格 自然語言詢問.feature「問到待辦或到期時」那條 Rule 的問句**沒有問號**。
    # 假路由是逐字查表的，差一個全形問號就查不到 → 丟例外 → fallback 成語意查詢，
    # 規格驗收會紅在 search_mode。兩個鍵並存：有問號那個另有兩顆測試在用。
    "這週要交什麼": RouteDecision(mode="task", due_within_days=7),
    "What is due this week?": RouteDecision(mode="task", due_within_days=7),
    # 沒講期限＝列出全部待辦（含沒有到期日的那些）
    "我有哪些待辦？": RouteDecision(mode="task"),
}


class FakeRouter:
    """照例子指定回查法。

    遇到沒登記過的問題（例如模糊問題「幫我找找之前那個」）就丟例外，
    模擬「LLM 無法判斷」，用來驗證 fallback 一定會走語意查詢。

    entity_names 只是為了與 RouterClient 協定一致（Phase 34 加入）：
    假件用問句查表，不會真的看名單，但會把收到的清單記在 last_entity_names，
    讓測試驗得出「端點真的把資料庫裡的實體名單傳進來了」——
    與 FakeVLM 記 last_folders／last_entities 是同一個手法。
    """

    def __init__(self, decisions: dict[str, RouteDecision] | None = None) -> None:
        self.decisions = DEFAULT_ROUTE_DECISIONS if decisions is None else decisions
        self.last_entity_names: list[str] | None = None

    def route(self, question: str, entity_names: list[str]) -> RouteDecision:
        self.last_entity_names = entity_names
        if question not in self.decisions:
            raise RuntimeError(f"無法判斷問題類型：{question}")
        return self.decisions[question]


def _looks_english(text: str) -> bool:
    """粗略判斷一段文字是不是英文：完全沒有中日韓漢字就當英文。

    這只是假件用的簡易規則，用來重現「回答語言跟隨提問語言」的行為；
    產品程式碼裡沒有、也不需要這種判斷（真模型看得懂提問語言）。
    """
    return not any("一" <= ch <= "鿿" for ch in text)


class FakeAnswerLLM:
    """拿檢索結果模板化回答；空結果回查無句式。回答語言跟隨提問語言。

    行為固定，讓「回答提及可樂」「使用者獲得查無相關照片的回覆」
    「英文問題得到英文回答」都可以被驗證。
    """

    def answer(self, question: str, documents: list[Document]) -> str:
        english = _looks_english(question)

        if not documents:
            return "No matching photos found." if english else "查無相關照片。"

        pieces = []
        for document in documents:
            first_line = document.page_content.splitlines()[0]
            items = document.metadata.get("items") or []
            if english:
                item_text = ", ".join(items) if items else "none"
                pieces.append(f"{first_line} (items: {item_text})")
            else:
                item_text = "、".join(items) if items else "無"
                pieces.append(f"{first_line}（物品：{item_text}）")

        if english:
            return "Based on the photos: " + "; ".join(pieces)
        return "依照片內容回答：" + "；".join(pieces)


class EagerDispatcher:
    """就地把任務跑完的入列器（測試用；eager ＝ 同步、當場做完）。

    正式路徑刻意**不用**這個（見 app/dependencies.py 的 NoopDispatcher docstring）。
    給「想要 POST 完照片就已經在資料庫裡」的測試情境用：
    換上這一個，router 一呼叫入列器，任務就當場跑完。

    形狀與 TaskDispatcher 一樣有 dispatch() 方法，
    所以掛上 dependency_overrides 之後 router 那句 dispatcher.dispatch(job_id) 照常能呼叫。

    四個協作者由建構子帶進來（不自己去 dependencies 拿）：
    測試想換成「會爆炸的 embeddings」之類的壞假件時，直接換參數就好。
    """

    def __init__(self, *, store, vlm, embeddings, now) -> None:
        self._store = store
        self._vlm = vlm
        self._embeddings = embeddings
        self._now = now

    def dispatch(self, job_id: str) -> None:
        from app.services.ingest_job import run_ingest_job

        run_ingest_job(
            job_id,
            store=self._store,
            vlm=self._vlm,
            embeddings=self._embeddings,
            now=self._now,
        )


class FakeCloudChat:
    """長得像 ollama.Client 的最小假件：chat() 回固定內容、記下每次呼叫。

    給雲端實作（OllamaCloudVLM／OllamaCloudRouter／OllamaCloudAnswerer／
    OllamaCloudEntitySuggester）的單元測試用：建構真物件後把 _client 換成這個，
    練的是「回覆 → 解析」那一段，不碰網路（教訓見 ollama_cloud 模組 docstring——
    ollama.com 對 format= 不強制，解析層必須自己扛）。
    """

    def __init__(self, content: str | None):
        self._content = content
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=self._content))


class FakePrivacyGate:
    """固定回同一個 Verdict 的假閘門（增量六 Phase 74）。

    conftest 的 wire_fake_ai 預設掛 FakePrivacyGate(Verdict.UNCERTAIN)
    ＝所有既有測試都走本機路徑，行為零改變。
    calls／last_filename／last_content_type 讓測試驗得出「呼叫端真的問了閘門、
    而且把哪個檔名與 content_type 交出去」。
    """

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        self.calls = 0
        self.last_filename: str | None = None
        self.last_content_type: str | None = None

    def classify(
        self, *, filename: str, content_type: str, load_bytes: Callable[[], bytes]
    ) -> Verdict:
        self.calls += 1
        self.last_filename = filename
        self.last_content_type = content_type
        return self.verdict


class FakePrivacyModel:
    """短問模型的固定答案卡（增量六 Phase 74；回 PrivacyJudgement，不是 Verdict）。

    raise_on_judge=True 讓 judge() 丟例外，用來驗「模型炸掉 → UNCERTAIN」。
    last_image_bytes 記下真正送進模型的位元組（Phase 75 靠它驗縮圖長邊 ≤512）。
    """

    def __init__(self, judgement: PrivacyJudgement, *, raise_on_judge: bool = False) -> None:
        self.judgement = judgement
        self.raise_on_judge = raise_on_judge
        self.calls = 0
        self.last_image_bytes: bytes | None = None
        self.last_content_type: str | None = None

    def judge(self, image_bytes: bytes, content_type: str) -> PrivacyJudgement:
        self.calls += 1
        self.last_image_bytes = image_bytes
        self.last_content_type = content_type
        if self.raise_on_judge:
            raise RuntimeError("假模型炸掉")
        return self.judgement


# ---------- 增量六 Phase 77：雲端路的假件 ----------
#
# 這一區的四顆假件是 Phase 78〜81（本機端流程）、87（工人）、89（EC2 探測）
# 全部測試的地基。它們**沒有一行 boto3**，也不連任何網路——
# 「pytest 絕不連真 AWS」（design6 §9）的實際做法就是這裡。

# S3 上寄物櫃的前綴（design6 §2.2 的鍵名契約）。
# 副檔名借用 staging 那一張表（同樣是那三種格式）：兩份一定會漂移，
# 而鍵名是**跨機器**的契約——本機寫的名字，EC2 上的工人要拿得到。
S3_PREFIX = "documents"


class FakeMailbox:
    """一顆假件同時扮演 S3 寄物櫃與兩條 SQS 佇列（總覽 §2.4.5）。

    為什麼三個角色合成一顆：一次雲端往返會同時碰到三者（Put 物件 → 發 jobs 訊息 →
    工人 Get 物件 → Put 結果 → 發 results 訊息 → 本機 Get 結果），
    拆成三顆假件的話，每個測試都要自己把三顆接起來，而且很容易接錯。
    合成一顆之後，Phase 87 的端到端測試可以直接寫成
    「本機送出 → 假工人處理**同一顆信箱** → 本機收回入庫」。

    它模仿的 SQS 行為（只模仿真的會影響正確性的那幾件）：
      * receive 會把訊息**從佇列拿走**（模仿可見度逾時：別人暫時看不到它）
      * delete 要帶 receipt handle（把手不對＝當場 AssertionError，比默默成功好）
      * release 把訊息放回**佇列前端**（模仿 ChangeMessageVisibility 改成 0）
      * 佇列空的時候 receive 回 None（真 SQS 長輪詢到時間也是回空的）
      * **不模仿**：亂序、重複投遞、可見度會自己過期。冪等要用「明確地再送一次」
        來測（Phase 80），比亂數可靠得多——假件要可預測。

    計數器與流水帳（測試靠它們斷言「有沒有真的送出去」「先後順序對不對」）：
      calls                                         **呼叫流水帳**：每被叫一次就記一行
                                                    （例如 "put_object documents/x/input.png"）。
                                                    整數計數器驗得出「幾次」，驗不出「誰先誰後」
                                                    ——D9 的順序鐵律只能靠這一份清單釘（總覽 §2.4.5）
      put_calls / get_calls / delete_calls          S3 三種操作各幾次
      send_job_calls / send_result_calls            兩條佇列各發了幾則
      wait_seconds_log                              每次 receive 說要等幾秒（Phase 80 驗 <= 20）
      instance_state_calls                          DescribeInstances 被叫幾次（Phase 89 驗快取）
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.jobs: list[dict] = []
        self.results: list[dict] = []
        self.calls: list[str] = []
        self.put_calls = 0
        self.get_calls = 0
        self.delete_calls = 0
        self.send_job_calls = 0
        self.send_result_calls = 0
        self.wait_seconds_log: list[int] = []
        # instance_state() 依序回傳這個清單，用完之後重複最後一個。
        # 預設「開著」＝ 大部分測試不必管它；要測「關機了」就把它換掉。
        self.instance_state_script: list[str] = ["running"]
        self.instance_state_calls = 0
        self._handle_seq = 0
        self._in_flight: dict[str, tuple[list[dict], dict]] = {}

    # ---------- 鍵名（design6 §2.2 的契約；Phase 83 的 AwsMailbox 要逐字相同）----------

    def input_key(self, job_id: str, content_type: str) -> str:
        return f"{S3_PREFIX}/{job_id}/input{STAGING_EXTENSIONS[content_type]}"

    def context_key(self, job_id: str) -> str:
        return f"{S3_PREFIX}/{job_id}/context.json"

    def result_key(self, job_id: str) -> str:
        return f"{S3_PREFIX}/{job_id}/result.json"

    # ---------- S3 那一半 ----------

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        assert isinstance(body, bytes), "S3 只收位元組；字串要自己先 encode"
        self.calls.append(f"put_object {key}")
        self.put_calls += 1
        self.objects[key] = body

    def get_object(self, key: str) -> bytes | None:
        """拿不到回 None（**不是**丟例外）——真的 AwsMailbox 會把 NoSuchKey 翻成 None。"""
        self.calls.append(f"get_object {key}")
        self.get_calls += 1
        return self.objects.get(key)

    def delete_objects(self, keys: list[str]) -> None:
        """盡力刪：本來就不在的鍵不算錯（真 S3 的 DeleteObjects 也是這個行為）。"""
        self.calls.append(f"delete_objects {len(keys)}")
        self.delete_calls += 1
        for key in keys:
            self.objects.pop(key, None)

    # ---------- jobs 佇列（本機 Send、工人 Receive／Delete）----------

    def send_job(self, job_id: str, s3_key: str) -> None:
        self.calls.append(f"send_job {job_id}")
        self.send_job_calls += 1
        self.jobs.append({"job_id": job_id, "s3_key": s3_key})

    def receive_job(self, wait_seconds: int) -> MailboxMessage | None:
        self.calls.append("receive_job")
        return self._receive(self.jobs, wait_seconds)

    def delete_job_message(self, receipt_handle: str) -> None:
        self.calls.append("delete_job_message")
        self._delete_message(receipt_handle)

    # ---------- results 佇列（工人 Send、本機 Receive／Delete／Release）----------

    def send_result(self, job_id: str) -> None:
        self.calls.append(f"send_result {job_id}")
        self.send_result_calls += 1
        self.results.append({"job_id": job_id})

    def receive_result(self, wait_seconds: int) -> MailboxMessage | None:
        self.calls.append("receive_result")
        return self._receive(self.results, wait_seconds)

    def delete_result_message(self, receipt_handle: str) -> None:
        self.calls.append("delete_result_message")
        self._delete_message(receipt_handle)

    def release_result_message(self, receipt_handle: str) -> None:
        """把手上這則訊息立刻還回佇列前端（＝ ChangeMessageVisibility 改成 0）。"""
        self.calls.append("release_result_message")
        queue, body = self._in_flight.pop(receipt_handle)
        queue.insert(0, body)

    # ---------- EC2（Phase 89 的 Ec2Probe 用）----------

    def instance_state(self, instance_id: str) -> str:
        self.calls.append(f"instance_state {instance_id}")
        self.instance_state_calls += 1
        answer = self.instance_state_script[0]
        if len(self.instance_state_script) > 1:
            self.instance_state_script.pop(0)
        return answer

    # ---------- 內部 ----------

    def _receive(self, queue: list[dict], wait_seconds: int) -> MailboxMessage | None:
        """從佇列前端拿一則走，發一個新的 receipt handle。**不會真的等** wait_seconds 秒。

        ⚠ 正因為它不等，「等到逾時」的測試一定要接管 cloud_ingest 的時間接縫
          _now()／_sleep()（Phase 79 才建），否則 wait_result 的迴圈會全速空轉到 deadline。
          接管用的小工具由 Phase 80 的測試檔定義：advance_clock_frozen(monkeypatch, seconds) ＝ 一次撥到
          未來然後凍結、advance_clock_each_call(monkeypatch, step_seconds) ＝ 每問一次就再前進。
          **本 phase 不定義任何時間 helper**——tests/fakes.py 裡沒有、也不該有它們。
        """
        self.wait_seconds_log.append(wait_seconds)
        if not queue:
            return None
        body = queue.pop(0)
        self._handle_seq += 1
        handle = f"receipt-{self._handle_seq}"
        self._in_flight[handle] = (queue, body)
        return MailboxMessage(
            job_id=body["job_id"],
            s3_key=body.get("s3_key"),
            receipt_handle=handle,
        )

    def _delete_message(self, receipt_handle: str) -> None:
        assert receipt_handle in self._in_flight, (
            f"要刪的訊息不在手上（把手 {receipt_handle!r}）——真 SQS 會安靜地不做事，"
            "所以這裡改成大聲炸掉，才抓得到「把手用錯／刪兩次」"
        )
        self._in_flight.pop(receipt_handle)


class FakeProbe:
    """假的遠端探測（總覽 §2.4.5）。

    running 給 True／False 決定答案；給一個**例外實例**就在被問時丟出來
    ——用來重現 design6 §2.1 第 2 條「沒有 AWS 憑證／API 失敗」那一種不可用。
    """

    def __init__(self, running: bool | Exception = True) -> None:
        self.running = running
        self.calls = 0

    def is_running(self) -> bool:
        self.calls += 1
        if isinstance(self.running, Exception):
            raise self.running
        return self.running


class ScriptedProbe:
    """依序回一串答案的假探測；用完之後重複最後一個（總覽 §2.4.5）。

    給 CloudRoute(信箱, probe) 的流程測試用：答案寫成 [True, False] 就能演
    「第一次可用、第二次不可用」這種劇本。
    ⚠ **不是**給 Phase 89 的 Ec2Probe 做 TTL 測試用——那組要數的是 DescribeInstances
      被叫了幾次，靠的是 FakeMailbox.instance_state_script ＋ instance_state_calls。
    """

    def __init__(self, answers: list[bool]) -> None:
        assert answers, "至少要給一個答案"
        self.answers = list(answers)
        self.calls = 0

    def is_running(self) -> bool:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


class FakeCloudRoute:
    """只回答「遠端可不可用」的假雲端路。**只給 Phase 77／78 用。**

    Phase 79 起一律改用真的 `CloudRoute(FakeMailbox(), FakeProbe(True), timeout_seconds=…)`
    ——假的路只證明得了「分支走對了」，證明不了「送出去的東西長什麼樣」
    （總覽 §2.4.5 那一列的原話）。

    available 給 True／False 決定答案；給一個**例外實例**就丟出來
    （閘門那一層必須把它當作「不可用」，不可以讓整個任務炸掉）。
    """

    def __init__(self, available: bool | Exception = True) -> None:
        self._available = available
        self.available_calls = 0
        self.submit_calls = 0
        self.cleanup_calls = 0

    def available(self) -> bool:
        self.available_calls += 1
        if isinstance(self._available, Exception):
            raise self._available
        return self._available

    def submit(self, job_id: str, *, content_type: str, file_bytes: bytes, context: dict) -> None:
        self.submit_calls += 1

    def fetch_result(self, job_id: str) -> dict | None:
        return None

    def wait_result(self, job_id: str, *, store) -> dict | None:
        return None

    def cleanup(self, job_id: str) -> None:
        self.cleanup_calls += 1


def fake_worker_process_one(mailbox, understanding=None, *, worker_version="fake-worker"):
    """假工人：把 mailbox.jobs 裡的**第一則**訊息做成 result.json ＋ 一則 results 訊息。

    它**不是** app/workers/cloud_worker.py（那是 Phase 87 的事），只是「另一頭真的
    有人在做事」的最小替身：不看圖、不解析影像，照著測試指定的答案寫結果。

      understanding 給一個 PhotoUnderstanding ＝ 工人一次就看懂了
      understanding 給 None                    ＝ 工人試了三次都看不懂

    ★ 順序刻意寫成「**先 PutObject、才 SendMessage**」（design6 D9 的順序鐵律）：
      假件也要教對的做法，Phase 87 的真工人才有樣本可比。

    回傳寫出去的那份 result（測試想再檢查內容時用得到）；jobs 佇列空的時候回 None。
    """
    message = mailbox.receive_job(wait_seconds=0)
    if message is None:
        return None

    result = {
        "job_id": message.job_id,
        "worker_version": worker_version,
        "kind": "image",
        "understood": understanding is not None,
        "attempts": 1 if understanding is not None else config.VLM_MAX_ATTEMPTS,
        "understanding": understanding.model_dump() if understanding is not None else None,
    }
    mailbox.put_object(
        mailbox.result_key(message.job_id),
        json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
        "application/json",
    )
    mailbox.send_result(message.job_id)
    mailbox.delete_job_message(message.receipt_handle)
    return result
