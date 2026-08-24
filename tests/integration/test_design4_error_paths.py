"""增量四（design4.md）錯誤表的收尾驗證（Phase 44）。

對照表是 design4.md §9（六列）。已被 Phase 38〜43 的測試覆蓋的列**不在這裡重寫**——
本檔只補「行為早就對了、只是沒有測試釘住」的缺口，體例沿用 Phase 37 的
`test_design3_error_paths.py`：每一段開頭標明對應錯誤表的哪一列。

各列的把關現況（盤點見 phase-44 §4.1；✓＝既有測試、★＝本檔補）：

| 列 | 情境 | 把關 |
|---|---|---|
| 1 | 詳情沒這列 → 404 | ✓ test_photo_detail.py::test_照片不存在回404 |
| 1b | 同上，**不打 AI、不寫檔** | ★ 本檔 ① |
| 2 | 有列、路徑 NULL → 200＋null | ✓ test_photo_detail.py::test_舊照片沒有原圖時image_url為null |
| 3 | 路徑有值但磁碟檔沒了 → 仍 200 | ✓ test_photo_detail.py::test_原圖被刪掉詳情仍回200 |
| 4 | 待辦點下去詳情 404 → 窗內紅字 | ✓（瀏覽器實操，見 G1 驗收包 D 段） |
| 5 | AI 失敗語意不變＋ok=false | ✓ test_ai_timing_log.py（vlm／route）＋ test_entity_suggestion_unit.py（entity_suggest）＋既有 422/500 各測 |
| 6 | Docker G2 對不上快照 | —（屬階段丙，phase-46） |

另外兩顆從**原始碼**層面釘住 design4 的兩條鐵律（與 openapi 那一面互補，
同 Phase 37「一顆掃原始碼、一顆掃 openapi」的手法）：

- ② 沒有人掛「列出全部照片」的路由（design4 §4.4 末句、D5）
- ③ 詳情彈窗唯讀、沒有任何寫入呼叫（design4 D2、§1.2 第 1／2 列）
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core import config

專案根目錄 = Path(__file__).resolve().parents[2]


def data_dir底下的檔案() -> list[Path]:
    """DATA_DIR 底下所有實際檔案。conftest 已把它指到本測試專屬的臨時目錄。

    沒人寫過檔時那個臨時目錄根本不存在，直接 iterdir() 會炸 FileNotFoundError，
    所以先判 exists（與 test_design3_error_paths.py 的同名工具同一寫法）。
    """
    if not config.DATA_DIR.exists():
        return []
    return [路徑 for 路徑 in config.DATA_DIR.rglob("*") if 路徑.is_file()]


# ---- ① 錯誤表第 1 列（後半）：詳情 404 之外，還要「不打 AI、不寫檔」 ----


def test_詳情端點不打AI也不寫檔(client, caplog):
    """GET 不存在的照片：除了 404，更重要的是這支唯讀端點沒有任何副作用。

    「不打 AI」用計時 log 驗（增量四起每次真的呼叫模型都會留下「AI 開始」；
    設 INFO 等級才撈得到）；「不寫檔」用 DATA_DIR 驗（conftest 已隔離到臨時目錄）。
    """
    caplog.set_level(logging.INFO)

    response = client.get("/photos/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "找不到照片"
    assert "AI 開始" not in caplog.text
    assert data_dir底下的檔案() == []


# ---- ② design4 §4.4 末句／D5：原始碼裡沒有「列出全部照片」的路由 ----


def test_原始碼裡沒有列出全部照片的路由():
    """掃 app/api/routers/ 底下每個 .py：不准有 @router.get("/photos")。

    openapi 那一面已由 test_photo_detail.py 的
    test_openapi有依id讀一張照片的端點且沒有列出全部 ＋
    test_ask_three_paths.py::test_端點數不變（總數 20）守住；
    這一顆守原始碼那一面——兩顆守同一條規則的兩面（Phase 37 對「不做刪除」的同一手法）。

    \\s* 是為了連「裝飾器換行寫」也抓得到（photos.py 的 @router.post( 就是換行寫的）；
    "/photos" 的結尾引號自然排除 "/photos/{photo_id}"，不會誤中詳情端點。
    """
    routers目錄 = 專案根目錄 / "app" / "api" / "routers"
    for 檔案 in sorted(routers目錄.glob("*.py")):
        原始碼 = 檔案.read_text(encoding="utf-8")
        assert not re.search(r'@router\.get\(\s*"/photos"', 原始碼), (
            f"{檔案.name} 掛了「列出全部照片」的路由——design1 的禁令仍有效，"
            "只准依 id 讀一張（design4 §4.4）"
        )


# ---- ③ design4 D2：詳情彈窗是唯讀的（原始碼層面） ----


def test_詳情彈窗是唯讀的():
    """讀 photo_detail_modal.js 原始碼：沒有 PATCH／POST／DELETE／斜線開頭的 /folder。

    design2 的「定案不可逆」仍有效，這顆窗不提供任何後悔藥——
    從原始碼證明它連寫入的字都沒有，不必靠人記得（design4 D2、§1.2 第 1／2 列）。

    刻意用 read_text() 直接讀、不先判 exists()：路徑打錯要當場炸
    FileNotFoundError，不能默默變成綠的。
    """
    彈窗原始碼 = (
        專案根目錄 / "app" / "static" / "photo_detail_modal.js"
    ).read_text(encoding="utf-8")

    assert "PATCH" not in 彈窗原始碼
    assert "POST" not in 彈窗原始碼
    assert "DELETE" not in 彈窗原始碼
    assert "/folder" not in 彈窗原始碼


def test_手機版遺失縮圖與中文斷行都有保護():
    瀏覽頁原始碼 = (
        專案根目錄 / "app" / "static" / "browse.html"
    ).read_text(encoding="utf-8")
    分類彈窗原始碼 = (
        專案根目錄 / "app" / "static" / "folder_modal.js"
    ).read_text(encoding="utf-8")
    詳情彈窗原始碼 = (
        專案根目錄 / "app" / "static" / "photo_detail_modal.js"
    ).read_text(encoding="utf-8")
    樣式原始碼 = (
        專案根目錄 / "app" / "static" / "style.css"
    ).read_text(encoding="utf-8")

    assert 瀏覽頁原始碼.count('image.addEventListener("error"') == 2
    assert 'image.replaceWith(el("div", "placeholder", "無縮圖"))' in 瀏覽頁原始碼
    assert 'image.replaceWith(el("div", "task-thumb-empty", "無縮圖"))' in 瀏覽頁原始碼
    assert '<span class="fm-nowrap">哪個資料夾？</span>' in 分類彈窗原始碼
    assert ".fm-nowrap { white-space: nowrap; }" in 樣式原始碼
    assert ".caption { padding-inline: var(--sp-1); }" in 樣式原始碼
    assert "text-wrap: pretty" in 樣式原始碼
    assert ":where(.folder-desc, .caption, .message, .fm-desc)" in 樣式原始碼
    assert "word-break: keep-all;" in 樣式原始碼
    assert "overflow-wrap: break-word;" in 樣式原始碼
    assert "function 保護數字單位(text)" in 瀏覽頁原始碼
    assert "const 說明 = 保護數字單位(photo.text);" in 瀏覽頁原始碼
    assert 'replace(/(\\d)\\s+(年|月|日|元)/g, "$1\\u00a0$2")' in 瀏覽頁原始碼
    assert 'const 片語 = "待決定分頁的";' in 瀏覽頁原始碼
    assert 'el("span", "caption-nowrap", 片語)' in 瀏覽頁原始碼
    assert '.caption-nowrap { white-space: nowrap; }' in 樣式原始碼
    assert "function pd保護數字單位(text)" in 詳情彈窗原始碼
    assert 'pdEl("pd-task-due").textContent = pd保護數字單位(' in 詳情彈窗原始碼
    assert 'pd造("dd", null, null, pd保護數字單位(pd值或無(一欄[1])))' in 詳情彈窗原始碼
    assert 'pdEl("pd-text").textContent = pd保護數字單位(body.text);' in 詳情彈窗原始碼
    assert ":where(.pd-text, .pd-fields dd, .pd-task-due)" in 樣式原始碼
    assert "TypeError" not in 詳情彈窗原始碼
    assert "uvicorn 是不是沒在跑" not in 詳情彈窗原始碼
    assert "請確認服務已啟動後，關閉視窗再試一次" in 詳情彈窗原始碼


def test_前台錯誤不洩漏原始例外或開發伺服器名稱():
    瀏覽頁原始碼 = (
        專案根目錄 / "app" / "static" / "browse.html"
    ).read_text(encoding="utf-8")
    分類彈窗原始碼 = (
        專案根目錄 / "app" / "static" / "folder_modal.js"
    ).read_text(encoding="utf-8")

    assert '"載入失敗：" + error' not in 瀏覽頁原始碼
    assert '"請求失敗：" + error' not in 分類彈窗原始碼
    assert "uvicorn 是不是沒在跑" not in 瀏覽頁原始碼
    assert "uvicorn 是不是沒在跑" not in 分類彈窗原始碼
    assert "目前無法載入資料。請確認服務已啟動後重新整理頁面。" in 瀏覽頁原始碼
    assert "目前無法完成歸類。請確認服務已啟動後再試一次。" in 分類彈窗原始碼


def test_詳情彈窗忽略過期回應且JSON失敗留在窗內():
    原始碼 = (
        專案根目錄 / "app" / "static" / "photo_detail_modal.js"
    ).read_text(encoding="utf-8")
    關窗實作 = 原始碼[原始碼.index("function pdClose()") : 原始碼.index("function pdInstall()")]
    畫圖實作 = 原始碼[原始碼.index("function pd畫圖(") : 原始碼.index("// D4：四欄")]
    開窗實作 = 原始碼[原始碼.index("async function openPhotoDetailModal") :]

    assert "let pdGeneration = 0;" in 原始碼
    assert "pdGeneration += 1;" in 關窗實作
    assert "const generation = ++pdGeneration;" in 開窗實作
    assert 'pdEl("pd-backdrop").querySelector(".fm-box").scrollTop = 0;' in 開窗實作
    assert 開窗實作.count("if (generation !== pdGeneration) return;") >= 4
    assert re.search(
        r'image\.addEventListener\("error", function \(\) \{\s*'
        r"if \(generation !== pdGeneration\) return;\s*pd畫占位\(\);",
        畫圖實作,
    )
    assert re.search(
        r"try \{\s*body = await response\.json\(\);\s*\} catch \(error\) \{\s*"
        r'if \(generation !== pdGeneration\) return;\s*pdEl\("pd-text"\)'
        r'\.textContent = "";\s*pdSetError\("[^"]*再試一次[^"]*"\);\s*return;\s*\}',
        開窗實作,
    )


def test_詳情彈窗會困住鍵盤焦點並封鎖背景():
    原始碼 = (
        專案根目錄 / "app" / "static" / "photo_detail_modal.js"
    ).read_text(encoding="utf-8")
    開窗實作 = 原始碼[原始碼.index("function pdOpen()") : 原始碼.index("// 關窗")]
    關窗實作 = 原始碼[原始碼.index("function pdClose()") : 原始碼.index("function pdInstall()")]
    鍵盤實作 = 原始碼[
        原始碼.index('document.addEventListener("keydown"') :
        原始碼.index("// 關閉方式③")
    ]

    assert "let pdBackgroundInert = [];" in 原始碼
    assert "pdBackgroundInert.push([node, node.inert]);" in 開窗實作
    assert "node.inert = true;" in 開窗實作
    assert "node.inert = wasInert;" in 關窗實作
    assert 'if (event.key === "Tab")' in 鍵盤實作
    assert "event.preventDefault();" in 鍵盤實作
    assert "focusable[0].focus();" in 鍵盤實作
    assert "focusable[focusable.length - 1].focus();" in 鍵盤實作
