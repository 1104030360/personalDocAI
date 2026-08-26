"""POST /photos 收 PDF：一頁一張照片（design3.md D7、§7）。

PDF 不走另一套入庫邏輯——每一頁渲染成 PNG 之後，就是一次普通的單圖上傳
（看圖 → 轉向量 → 寫入未分類 → 存原圖＋縮圖）。所以這裡驗的是「拆頁與收尾」：
拆成幾筆、壞檔怎麼收、某一頁看不懂怎麼辦，以及 202 的回應形狀有沒有被改到。

2026-08-25（Phase 62）起上傳改回 **202**：HTTP 只把檔案收進 staging、記一筆任務，
拆頁與看圖都搬到 worker（app/services/ingest_job.py 的 run_ingest_job）。
所以本檔一律「POST 拿 202 → 測試自己扮演 worker 把任務跑完 → 驗資料庫」，
`pages`／`created`／`skipped_pages` 三個回應鍵**已經不存在**：
  - 總頁數    ：測試自己給的（make_pdf_bytes(N)），不必再從回應讀
  - 成功頁數  ：len(結果["photo_ids"])
  - 跳過頁數  ：總頁數 − 成功頁數（design5.md §4.3 明文不另存欄位）
"""

from __future__ import annotations

import pytest

from app.core import config
from app.dependencies import get_vlm
from app.main import app
from app.repositories import photo_repository
from app.services import storage_service
from app.services.vlm_service import PhotoUnderstanding
from tests.conftest import 上傳並跑完任務
from tests.fakes import FakeVLM, make_pdf_bytes, make_png_bytes

收據理解 = PhotoUnderstanding(
    understood=True,
    text="在 Target 購買可樂與洋芋片的收據，日期 2026-08-10",
    category="收據",
    location="Target",
    items=["可樂", "洋芋片"],
    content_time="2026-08-10",
)


class 分頁VLM:
    """指定「哪幾頁看得懂」的假件，用來重現「部分頁看不懂」。

    FakeVLM 對每一次呼叫都回同一個答案，驗不出「跳過第 2 頁、其餘照收」；
    這個假件只在本檔案用得到，就不放進 tests/fakes.py。

    ⚠ Phase 62 起不能再用「第幾次呼叫＝第幾頁」數頁：看圖搬進 worker 之後，
      看不懂的那一頁會被連續問 config.VLM_MAX_ATTEMPTS 次才放棄（design5.md D12），
      用呼叫次數當頁碼會把「第 2 頁的第 2 次補考」誤認成第 3 頁。
      改成自己數頁：看得懂的頁一次就過（頁碼 +1）；看不懂的頁問滿 3 次才換下一頁。
      （寫法與 tests/integration/test_ingest_job_pdf.py 的同名假件一致，但各檔
      各留一份——跨測試檔 import 假件會把兩份測試綁在一起。）
    """

    def __init__(self, 看得懂的頁碼: set[int], *, 每頁上限: int = 3) -> None:
        self.看得懂的頁碼 = 看得懂的頁碼      # 1 起算，與使用者在 PDF 閱讀器上看到的一致
        self.每頁上限 = 每頁上限
        self.calls = 0
        self.目前頁 = 1
        self.這一頁問過幾次 = 0
        self.每頁呼叫次數: dict[int, int] = {}

    def understand(
        self,
        image_bytes: bytes,
        content_type: str,
        folders: list[dict],
        entities: list[dict],
        corrections: list[dict],
    ) -> PhotoUnderstanding:
        self.calls += 1
        self.這一頁問過幾次 += 1
        頁 = self.目前頁
        self.每頁呼叫次數[頁] = self.每頁呼叫次數.get(頁, 0) + 1

        看得懂 = 頁 in self.看得懂的頁碼
        if 看得懂 or self.這一頁問過幾次 >= self.每頁上限:
            # 這一頁到此為止（成功、或用完 3 次要跳過），下一次呼叫算下一頁
            self.目前頁 += 1
            self.這一頁問過幾次 = 0
        return 收據理解 if 看得懂 else PhotoUnderstanding(understood=False)


def data_dir底下的檔案() -> list:
    """DATA_DIR 底下所有實際檔案。conftest 已把它指到本測試專屬的臨時目錄。"""
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


def 上傳PDF(client, payload: bytes) -> dict:
    """收下一份 PDF（202）**並且把那個任務跑完**，回共用工具的結果字典。

    四個鍵：job_id／response／job（成功時是 None＝已被刪掉）／photo_ids。
    「202」由 上傳並跑完任務() 自己斷言，所以呼叫端不必再驗一次。
    """
    return 上傳並跑完任務(
        client, payload=payload, filename="scan.pdf", content_type="application/pdf"
    )


def test_上傳三頁PDF建立三筆照片(client):
    vlm = FakeVLM(收據理解)
    app.dependency_overrides[get_vlm] = lambda: vlm

    結果 = 上傳PDF(client, make_pdf_bytes(3))

    # 成功＝job 被刪掉（design5.md §4.3），所以任務清單裡查不到它了
    assert 結果["job"] is None
    # 一頁一張：三頁進了三個 id（photo_ids 是「新進收件箱的照片」算出來的，
    # 所以這一行同時也證明了三頁都先進未分類），資料庫真的多了三列
    assert len(結果["photo_ids"]) == 3
    assert photo_repository.count_photos() == 3
    # 看圖是一頁叫一次（不是整份 PDF 叫一次），也沒有第二個模型
    assert vlm.calls == 3

    for photo_id in 結果["photo_ids"]:
        row = photo_repository.fetch_photo(photo_id)
        # 與單圖上傳一致：先進未分類，AI 的建議只落在建議欄（design5.md D16）
        assert row["category"] == "未分類"
        assert row["suggested_category"] == "收據"
        # 存下來的是那一頁渲染出的 PNG，不是 PDF——讀圖端點因此不必改
        assert row["content_type"] == "image/png"
        assert row["thumbnail_path"] == f"data/thumbs/{photo_id}.png"
        assert storage_service.absolute_path(row["original_path"]).is_file()
        assert storage_service.absolute_path(row["thumbnail_path"]).is_file()


def test_壞PDF回422不存任何資料(client):
    """樣板 C：HTTP 這一側已經沒有 422 了——「讀不開」現在是**任務的結局**。

    檔名裡的 422 是舊契約留下的（Phase 62 只換測法、不換要守的事）：
    POST 一律 202，拆頁失敗改成跑完任務之後 job 標 failed，
    而「什麼都不存」一字未變（design5.md §8 第 4 列）。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    結果 = 上傳PDF(client, b"not a pdf")

    job = 結果["job"]
    assert job is not None, "失敗的 job 要留在進度面板上讓人看到"
    assert job["status"] == "failed"
    assert job["error"], "失敗要留一句給人看的短句，不然面板上只有一列紅字沒有理由"
    assert 結果["photo_ids"] == []
    assert photo_repository.count_photos() == 0
    # staging 也清乾淨了（最終失敗＝整筆拿掉，design5.md D10）
    assert data_dir底下的檔案() == []


def test_全部頁看不懂回422不存任何資料(client):
    # conftest 的 wire_fake_ai 預設就是「看不懂」的 FakeVLM，這裡不覆寫即可
    結果 = 上傳PDF(client, make_pdf_bytes(2))

    job = 結果["job"]
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"]
    assert 結果["photo_ids"] == []
    assert photo_repository.count_photos() == 0
    assert data_dir底下的檔案() == []


def test_部分頁看不懂時其餘頁照樣入庫並回報跳過的頁碼(client):
    vlm = 分頁VLM(看得懂的頁碼={1, 3})
    app.dependency_overrides[get_vlm] = lambda: vlm

    結果 = 上傳PDF(client, make_pdf_bytes(3))

    # 至少一頁成功＝整筆成功（design5.md D12），所以 job 被刪掉
    assert 結果["job"] is None
    assert len(結果["photo_ids"]) == 2
    assert photo_repository.count_photos() == 2
    # 「跳過幾頁」＝總頁數 − 成功頁數（Phase 60 明文不另存欄位）
    assert 3 - len(結果["photo_ids"]) == 1
    # 被跳過的是**第 2 頁**：它被問滿 3 次才放棄，第 1、3 頁各一次就過。
    # （回應已經沒有 skipped_pages 了，改由假件的計數證明是哪一頁被跳過；
    #   頁碼從 1 起算，與使用者在 PDF 閱讀器上看到的一致）
    assert vlm.每頁呼叫次數 == {1: 1, 2: 3, 3: 1}, vlm.每頁呼叫次數


@pytest.mark.parametrize("頁數", [1, 2])
def test_pages與created長度相加等於跳過的頁數(client, 頁數):
    """不變式：總頁數 ＝ 成功頁數 ＋ 跳過頁數（沒有頁會憑空消失）。

    202 之後 pages／created／skipped_pages 都不在回應裡了：
    總頁數是這一顆自己給的（make_pdf_bytes(頁數)），成功頁數看 photo_ids，
    跳過頁數是兩者相減——不變式本身一字未變。
    """
    app.dependency_overrides[get_vlm] = lambda: FakeVLM(收據理解)

    結果 = 上傳PDF(client, make_pdf_bytes(頁數))

    成功頁數 = len(結果["photo_ids"])
    跳過頁數 = 頁數 - 成功頁數
    assert 成功頁數 == photo_repository.count_photos()
    assert 成功頁數 + 跳過頁數 == 頁數
    # 這一次每頁都看得懂，所以一頁都不該被跳過
    assert 跳過頁數 == 0


def test_單圖與PDF的202回應形狀相同(client):
    """圖與 PDF 走同一支受理函式，202 的 body 恰三個鍵（design5.md §5）。

    改名自 test_單圖上傳回應形狀不變：以前兩者是**兩種**回應形狀
    （UploadResponse vs PdfUploadResponse），所以要守「PDF 分支不可以污染單圖回應」；
    現在兩者回同一個 IngestAcceptedResponse，要守的就變成「兩邊真的同形」。

    這一顆刻意**不跑任務**——它驗的是 HTTP 收下那一刻的回應，與看圖無關。
    """
    單圖 = client.post(
        "/photos", files={"file": ("a.png", make_png_bytes(), "image/png")}
    )
    PDF = client.post(
        "/photos", files={"file": ("scan.pdf", make_pdf_bytes(1), "application/pdf")}
    )

    assert 單圖.status_code == 202, 單圖.text
    assert PDF.status_code == 202, PDF.text
    assert set(單圖.json()) == {"job_id", "filename", "content_type"}
    assert set(PDF.json()) == set(單圖.json())
    # 形狀一樣，內容當然還是各報各的
    assert 單圖.json()["content_type"] == "image/png"
    assert PDF.json()["content_type"] == "application/pdf"
