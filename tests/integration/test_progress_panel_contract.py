"""增量五階段丙的前端契約（Phase 67 建，Phase 68／69 續加）。

本專案的前端 phase 一律**不新增 Playwright 自動化測試**
（design5 §9 明文、Phase 14／23／24／31／33／39 的一貫慣例）：
畫面好不好看、按下去對不對，用瀏覽器實操驗收。

但有幾條規則是「壞掉的時候沒有人會發現」的那種——例如某一頁忘了掛進度面板、
或有人為了方便在 HTML 裡又寫了一個 setInterval。那種東西用字串掃原始碼最省事，
所以這一檔只釘**契約**，不驗行為。
"""

from __future__ import annotations

import re
from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]
靜態目錄 = 專案根目錄 / "app" / "static"

# 進度面板要掛在這五頁（design5 D8；camera-phone.html 刻意不在內，見 Phase 67 §4.7）
掛面板的五頁 = [
    "upload.html",
    "pending.html",
    "browse.html",
    "ask.html",
    "camera-desk.html",
]


def 讀(檔名: str) -> str:
    """讀 app/static 底下的檔案。

    刻意不先判 exists()：路徑打錯要當場炸 FileNotFoundError，
    不能默默變成綠的（同 test_design4_error_paths.py 的作法）。
    """
    return (靜態目錄 / 檔名).read_text(encoding="utf-8")


# ---- ① design5 D8：五頁都掛了同一份進度面板 ----


def test_五頁都掛了進度面板():
    for 檔名 in 掛面板的五頁:
        assert '<script src="/ui/progress_panel.js"></script>' in 讀(檔名), (
            f"{檔名} 沒有掛 progress_panel.js——design5 D8 要求進度面板全站都在，"
            "換頁不能讓進行中的工作消失"
        )


def test_手機取景頁刻意沒有掛面板():
    """camera-phone.html 是全螢幕取景，右下角固定面板會壓到快門。

    手機端的進度是 Phase 69 的窄條（cp-bar），不是這一份面板
    （Phase 67 §4.7 的裁決：§6.5 比 D8 具體，以 §6.5 為準）。
    """
    assert "progress_panel.js" not in 讀("camera-phone.html")


# ---- ② design5 §6.1：輪詢全站只有一份 ----


def test_進度面板是全站唯一一份輪詢():
    """§6.1 明文：「不要四個 HTML 各寫一套 setInterval」。"""
    面板 = 讀("progress_panel.js")
    assert 面板.count("setInterval(") == 1

    for 檔名 in sorted(p.name for p in 靜態目錄.glob("*.html")):
        assert "setInterval" not in 讀(檔名), (
            f"{檔名} 自己寫了 setInterval——輪詢只准有一份，寫在 progress_panel.js 裡"
        )


def test_進度面板的契約常數與命名():
    """跨文件共用契約：前綴 pp、容器 #pp-panel、每列 pp-job-{job_id}、間隔 2000 ms。"""
    面板 = 讀("progress_panel.js")

    assert "const PP_POLL_MS = 2000;" in 面板
    assert 'panel.id = "pp-panel";' in 面板
    assert '"pp-job-" + job.job_id' in 面板
    for 函式 in ["function ppStart()", "function ppStop()",
                 "function ppRender(jobs)", "async function ppDismiss(jobId)"]:
        assert 函式 in 面板, f"少了對外函式 {函式}"


# ---- ③ design5 §5／Phase 37：關掉失敗列用 POST，openapi 永遠零 DELETE ----


def test_關掉失敗列用POST不用DELETE():
    面板 = 讀("progress_panel.js")

    assert '/dismiss"' in 面板
    assert 'method: "POST"' in 面板
    assert "DELETE" not in 面板


# ---- ④ design5 §6.1：頂欄 N 只有一個地方在算 ----


def test_頂欄待決定的數字只由進度面板更新():
    """全站只有一個地方在寫 #nav-pending-count 的內容。

    Phase 53 在五個 HTML 各貼了一份「自己打 GET /folders 算 N」的過渡片段
    （見 tests/integration/test_nav_header.py 的同名沿革），本 phase 整組刪掉。
    這一顆從**另一面**守同一條規則：五頁只准把 nav-pending-count 當作
    「頂欄 HTML 裡的那個 span」提到一次，不准再有人去改它的文字。
    """
    for 檔名 in 掛面板的五頁:
        原始碼 = 讀(檔名)
        # 每一頁只有 <header> 裡那個 <span id="nav-pending-count">…</span>
        assert 原始碼.count("nav-pending-count") == 1, (
            f"{檔名} 提到 nav-pending-count 超過一次——"
            "Phase 67 起這個數字只由 progress_panel.js 的 pp更新待決定() 供應"
        )
        assert '<span id="nav-pending-count">…</span>' in 原始碼

    面板 = 讀("progress_panel.js")
    assert 'ppEl("nav-pending-count")' in 面板
    # 只換 span 的數字，不重寫整格文字（Phase 53 §4.1 的理由）
    assert '"待決定（"' not in 面板


# ---- ⑤ 全站鐵律：禁原生對話框；面板本身零 innerHTML ----


def test_靜態檔沒有原生對話框且面板零innerHTML():
    原生對話框 = re.compile(r"\b(alert|confirm|prompt)\(")
    for 路徑 in sorted(靜態目錄.glob("*.html")) + sorted(靜態目錄.glob("*.js")):
        原始碼 = 路徑.read_text(encoding="utf-8")
        assert not 原生對話框.search(原始碼), (
            f"{路徑.name} 出現了原生對話框——全站鐵律禁用 alert／confirm／prompt"
        )

    # 面板只有三個節點，全部用 createElement 造；零 innerHTML 讓這條可以直接掃
    assert "innerHTML" not in 讀("progress_panel.js")


# ═══════════════════════════════════════════════════════════════════
# Phase 68：上傳頁多檔選檔（design5 D3／D13／§6.4）
# ═══════════════════════════════════════════════════════════════════


def test_上傳頁可以一次選多個檔():
    """D3：一次可選多張 JPEG／PNG，也可含 PDF。"""
    上傳頁 = 讀("upload.html")

    assert re.search(r'<input type="file"[^>]*\bmultiple\b', 上傳頁, re.S), (
        "upload.html 的 <input type=\"file\"> 少了 multiple——D3 要求一次可選多檔"
    )
    # PDF 仍可混在同一次選檔裡（§6.4 末句）
    assert "application/pdf" in 上傳頁


def test_上傳頁不再於入庫當下開歸類鏈():
    """D13：電腦上傳不再開抽屜→實體→待辦；202 的回應裡也沒有東西可以餵給鏈。

    ⚠ 這裡掃的是 upload.html **有沒有載入／呼叫**那些檔，
      不是「那些檔還在不在」——它們必須留著給 Phase 70 的待決定頁用（§2 末句）。

    最後一條連 `201` 這三個字都不准出現（包含註解）：
    留著一個舊的 `status === 201` 判斷是「安靜壞掉」的典型——
    頁面不報錯，只是每次上傳都走 else 分支顯示成失敗。
    （同 folder_modal.js 第 7 行的自我提醒手法：註解也不要誤中。）
    """
    上傳頁 = 讀("upload.html")

    assert "startClassifyChain" not in 上傳頁
    for 檔名 in ["classify_chain.js", "folder_modal.js", "entity_modal.js", "task_modal.js"]:
        assert 檔名 not in 上傳頁, f"upload.html 還在載入 {檔名}——D13 起這一頁不開鏈"

    assert "response.status === 202" in 上傳頁
    assert "201" not in 上傳頁


def test_上傳頁是順序送不是一次全發():
    """§4.4 的決策：for...of ＋ await，一次一個。"""
    上傳頁 = 讀("upload.html")

    assert "for (const file of files)" in 上傳頁
    assert "Promise.all" not in 上傳頁
    assert "ppStart()" in 上傳頁          # 送完要把進度面板叫起來


# ═══════════════════════════════════════════════════════════════════
# Phase 69：鏡頭連拍與桌面拿掉開鏈（design5 D4／D13／§6.5）
# ═══════════════════════════════════════════════════════════════════


def test_手機端202就放行下一拍():
    """D4／§5：受理成功是 202；一拿到就能拍下一張。

    連 `201` 這三個字都不准出現在這一頁（包含註解）：
    留著舊的 `status === 201` 判斷是「安靜壞掉」的典型——
    照片其實已經收下了，手機卻顯示「沒有送成功」。
    """
    手機頁 = 讀("camera-phone.html")

    assert "response.status === 202" in 手機頁
    assert "201" not in 手機頁
    assert 'id="cp-bar"' in 手機頁                 # §6.5 的窄條
    assert "progress_panel.js" not in 手機頁       # 手機不掛全站面板（Phase 67 §4.7）
    # 防連按的真本事是旗標，不是 disabled（電腦按的快門不經過按鈕）
    assert "if (!cpStream || cp上傳中) { return; }" in 手機頁


def test_桌面頁不再開歸類鏈():
    """D13／§1.1 鏡頭桌面那一列：刪掉「拿最後一張 → 三關彈窗鏈」。"""
    桌面頁 = 讀("camera-desk.html")

    assert "startClassifyChain" not in 桌面頁
    for 檔名 in ["classify_chain.js", "folder_modal.js", "entity_modal.js", "task_modal.js"]:
        assert 檔名 not in 桌面頁, f"camera-desk.html 還在載入 {檔名}——D13 起這一頁不開鏈"
    # §5 第 3 列：桌面不再靠「最後一張」那支端點
    assert "/latest" not in 桌面頁
    # 進度改走全站面板
    assert '<script src="/ui/progress_panel.js"></script>' in 桌面頁
    assert "ppStart();" in 桌面頁

    # ⚠ POST /camera/session 仍然回 201（§5 沒有改它）——這一行不准跟著被改掉
    assert "if (response.status !== 201) {" in 桌面頁


def test_鏡頭的核心功能一個字都沒動():
    """§6.5：「WebRTC 預覽、QR、快門、閃光**不改**」。

    這幾條掃的是「那些關鍵行還在不在」——它們沒有自動化測試接得住，
    是 Phase 36 在真機上一次一次調出來的，改壞了只有真機才發現得了。
    """
    桌面頁 = 讀("camera-desk.html")
    手機頁 = 讀("camera-phone.html")
    樣式 = 讀("style.css")

    for 片語 in [
        "new RTCPeerConnection({ iceServers: [] })",        # 零 STUN／TURN
        'document.getElementById("cd-qr").innerHTML = body.qr_svg;',
        '送({ type: "capture" });',
        '送({ type: "torch", on: cd閃光開著 });',
    ]:
        assert 片語 in 桌面頁, f"camera-desk.html 少了不該動的一行：{片語}"

    for 片語 in [
        "navigator.mediaDevices.getUserMedia",
        "facingMode: { ideal: cp鏡頭 }",
        'canvas.toBlob(resolve, "image/jpeg", 0.92);',
        "applyConstraints({ advanced: [{ torch: !!要開 }] })",
        "settings.torch !== true",                          # iOS 靜默成功的復驗
    ]:
        assert 片語 in 手機頁, f"camera-phone.html 少了不該動的一行：{片語}"

    # QR 顯示尺寸（增量四唯一一次改產品 CSS）不准改小。
    # 主測試在 test_camera_endpoints.py::test_qr的顯示尺寸夠大讓長網址也掃得到，
    # 這裡再釘一次，是因為本 phase 正好在改同一支 CSS 檔案的隔壁區塊。
    assert ".cd-qr svg { width: 100%; height: auto; max-width: 20rem; }" in 樣式
