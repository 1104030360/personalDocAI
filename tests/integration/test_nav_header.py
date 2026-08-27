"""全站頂欄四格導覽的契約測試（增量五 Phase 53；design5.md §6.1、§9）。

本專案的前端沒有自動化測試框架（純前端 phase 一向是瀏覽器實操驗收）。
但「五頁的頂欄要長得一樣」這種事最容易在改了其中一頁之後悄悄走鐘，
而且走鐘了畫面不會壞、只是少一格——人不一定看得出來。

所以用最便宜的方式釘住：**直接把 HTML 當文字讀進來、斷言字串在不在**。
手法比照既有的 tests/integration/test_design4_error_paths.py
（那裡有好幾顆掃 browse.html／folder_modal.js 原始碼的測試）。

Phase 55 會在本檔追加「瀏覽頁不再是待決定入口」的三顆。
Phase 67 刪掉五頁的計數片段時，會把 test_五頁都有同一份待決定計數片段
**原地換成**新的一顆（改名、不加顆）——刪片段的人記得連測試一起換，不要只刪測試。
"""

from __future__ import annotations

import re                      # ← 這一行是 Phase 55 加的
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
STATIC = 專案根目錄 / "app" / "static"

# 頂欄要出現在這五頁。camera-phone.html 刻意不在名單裡——
# 那是手機全螢幕取景頁，見 test_手機取景頁沒有頂欄。
有頂欄的五頁 = [
    "upload.html",
    "pending.html",
    "browse.html",
    "ask.html",
    "camera-desk.html",
]

# 四格的「文字」與「網址」逐字對照（增量五契約 §6：一個字都不能改）
四格 = [
    ("上傳照片", "/ui/upload.html"),
    ("待決定", "/ui/pending.html"),
    ("瀏覽資料夾", "/ui/browse.html"),
    ("問問題", "/ui/ask.html"),
]

# 「待決定（N）」那一格的固定形狀。前面的開頭標籤各頁不同（當頁那一頁多了
# aria-current），所以只比對「開頭標籤之後」的這一段——五頁逐字相同。
待決定那一格的尾巴 = '待決定（<span id="nav-pending-count">…</span>）</a>'

# 哪一頁該把哪一格標成當頁
當頁對照 = {
    "upload.html": "/ui/upload.html",
    "pending.html": "/ui/pending.html",
    "browse.html": "/ui/browse.html",
    "ask.html": "/ui/ask.html",
}


def 讀(檔名: str) -> str:
    """讀 app/static/ 底下的檔。

    刻意不先判 exists()：路徑打錯要當場炸 FileNotFoundError，
    不能因為「檔案不存在」而默默變成綠的。
    """
    return (STATIC / 檔名).read_text(encoding="utf-8")


def test_五頁頂欄都有四格導覽():
    """四格的文字與網址逐字比對（design5.md §6.1）。"""
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        for 文字, 網址 in 四格:
            assert f'href="{網址}"' in 原始碼, f"{檔名} 的頂欄少了 {網址} 這一格"
            assert 文字 in 原始碼, f"{檔名} 的頂欄少了「{文字}」這幾個字"


def test_待決定那一格是固定形狀且帶計數欄位():
    """全形括號、span 的 id、初始值「…」——五頁必須逐字相同。

    數字包在 <span id="nav-pending-count"> 裡，JS 只改那個 span；
    「待決定」三個字與括號永遠不會被程式碰到。
    """
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        assert 待決定那一格的尾巴 in 原始碼, f"{檔名} 的「待決定（N）」形狀不對"


def test_五頁的計數片段已交棒給進度面板():
    """Phase 53 的過渡片段（各頁自己打 GET /folders 算 N）在 Phase 67 整組刪掉。

    改由 app/static/progress_panel.js 每 2 秒輪詢 GET /ingest-jobs 一次帶回
    jobs 與 pending_count（design5.md §6.1：「不要四個 HTML 各寫一套 setInterval」）。

    頂欄那一格的 HTML（含 <span id="nav-pending-count">）**沒有變**，
    由 test_待決定那一格是固定形狀且帶計數欄位 繼續守著。
    """
    for 檔名 in 有頂欄的五頁:
        原始碼 = 讀(檔名)
        assert 'const 格子 = document.getElementById("nav-pending-count");' not in 原始碼, (
            f"{檔名} 還留著 Phase 53 的過渡計數片段——Phase 67 起由 progress_panel.js 接手"
        )
        assert '<script src="/ui/progress_panel.js"></script>' in 原始碼

    面板 = (專案根目錄 / "app" / "static" / "progress_panel.js").read_text(encoding="utf-8")
    assert 'ppEl("nav-pending-count")' in 面板


def test_每一頁只標自己那一格為當頁():
    """aria-current="page" 恰好一個，而且標在自己身上。

    ⚠ browse.html 的分頁列用的是 aria-current="true"（不是 "page"），
    所以這裡數 "page" 的數量不會被分頁列干擾。
    """
    for 檔名, 自己的網址 in 當頁對照.items():
        原始碼 = 讀(檔名)
        assert f'href="{自己的網址}" aria-current="page"' in 原始碼, (
            f"{檔名} 沒有把自己那一格標成當頁"
        )
        assert 原始碼.count('aria-current="page"') == 1, (
            f"{檔名} 標了不只一格當頁"
        )


def test_鏡頭桌面頁不標任何一格為當頁():
    """鏡頭桌面頁不是那四格之一（它是上傳頁的支線），現況就是不標。"""
    assert 'aria-current="page"' not in 讀("camera-desk.html")


def test_手機取景頁沒有頂欄():
    """camera-phone.html 是手機全螢幕取景頁，刻意不掛頁首與導覽。

    style.css 對這一頁的註解寫得很白：「它只有一個用途，多一個連結都是誤觸來源」。
    版面是 height: 100dvh; overflow: hidden 算好的，插一條頁首會把取景區壓扁。
    """
    原始碼 = 讀("camera-phone.html")
    assert "site-header" not in 原始碼
    assert "/ui/pending.html" not in 原始碼
    assert "待決定" not in 原始碼


def test_端點數仍為22(client):
    """甲段（Phase 52〜55）純前端：一支端點都沒加。

    /ui/pending.html 是靠 app/main.py 的 app.mount("/ui", StaticFiles(...))
    送出去的靜態檔，不會出現在 openapi.json 裡。

    ⚠ paths 是「路徑 → 方法」兩層字典，要把每個路徑底下的方法數加起來，
    不能直接數 paths 有幾個 key（算法與 test_ask_three_paths.py 的
    test_端點數不變 一致）。20 → 22 已在增量五 Phase 64 發生
    （GET /ingest-jobs ＋ POST /ingest-jobs/{job_id}/dismiss）——
    本測試原名 test_端點數仍為20，Phase 53 當時的 docstring 就預告了這次更新。
    """
    paths = client.get("/openapi.json").json()["paths"]
    運算元 = [(path, method) for path, item in paths.items() for method in item]

    assert len(運算元) == 22


# ---------------------------------------------------------------------------
# Phase 55：瀏覽頁不再是待決定入口（design5.md §6.3、§9）
#
# 這三顆守的是「舊路真的被拔乾淨了」。之所以要釘住，是因為留一半不會壞掉、
# 只會變成兩個入口——畫面看起來正常，但 Phase 70 改待決定鏈的時候會改漏一邊。
# ---------------------------------------------------------------------------


def test_瀏覽頁不再是待決定入口():
    """showPending()／接著釘實體() 與兩支歸類彈窗都不該再出現在 browse.html。

    ⚠ 不能用「'待決定' not in 原始碼」來驗：
      ① 頂欄那一格本來就有「待決定」三個字（Phase 53 加的，是對的）；
      ② 照片卡() 裡有一段 const 片語 = "待決定分頁的"，那是 Phase 44 的中文
         換行保護（正式庫有一張照片的說明剛好含這幾個字），也是對的。
    所以改成逐項比對「函式與引用」，不是比對那三個字。
    """
    原始碼 = 讀("browse.html")

    assert "function showPending" not in 原始碼, "showPending() 沒刪乾淨"
    assert "接著釘實體" not in 原始碼, "接著釘實體() 沒刪乾淨"
    assert "openFolderModal" not in 原始碼, "browse.html 不該再開歸類彈窗"
    assert "openEntityModal" not in 原始碼, "browse.html 不該再開實體彈窗"
    assert "folder_modal.js" not in 原始碼, "browse.html 不該再載入歸類彈窗"
    assert "entity_modal.js" not in 原始碼, "browse.html 不該再載入實體彈窗"
    # 唯讀詳情窗還要用（資料夾牆與待辦列都靠它）
    assert "photo_detail_modal.js" in 原始碼

    # 無 query 時的預設分支＝資料夾卡片（design5.md §6.3）
    assert re.search(r"\}\s*else\s*\{\s*await showFolderList\(\);", 原始碼), (
        "無 query 時的預設不是資料夾卡片"
    )
    assert 'tabInUrl === "folders"' not in 原始碼, (
        "?tab=folders 應該併進預設分支，不必再獨立一支"
    )


def test_瀏覽頁的分頁列只剩資料夾與待辦():
    """renderTabs() 只建兩格；待決定那一格連建立的程式碼都不該留著。"""
    原始碼 = 讀("browse.html")

    assert 'el("a", "tab", "資料夾")' in 原始碼
    assert 'el("a", "tab", "待辦（"' in 原始碼
    assert 'el("a", "tab", "待決定（"' not in 原始碼, "分頁列還在建待決定那一格"
    assert 'renderTabs("pending"' not in 原始碼
    assert 原始碼.count('el("a", "tab",') == 2, "分頁列不是恰好兩格"


def test_瀏覽頁沒有做舊書籤轉址():
    """design5.md §6.3 明文不做轉址：頂欄已經有那一格，多一個 302 容易繞。

    browse.html 裡「/ui/pending.html」只該出現一次——就是頂欄那一格的連結。
    """
    原始碼 = 讀("browse.html")

    assert 原始碼.count("/ui/pending.html") == 1, (
        "browse.html 裡的 /ui/pending.html 不只頂欄那一個連結"
    )
    assert "location.replace" not in 原始碼
    assert "location.assign" not in 原始碼
    assert 'location.href = "/ui/pending.html"' not in 原始碼
