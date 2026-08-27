"""待決定頁的三關彈窗鏈（Phase 70）——原始碼契約。

前端沿 Phase 14／23／24 的慣例不寫 Playwright 自動化測試，改用「讀原始碼、
斷言關鍵那幾行真的在」的字串契約（design5.md §9 末段明文允許）。
這種測試守的是「有人改壞了會馬上紅」，不是「畫面好不好看」——後者靠 §4.6 的瀏覽器實操。

本檔兩顆：
① 待決定頁真的載入了待辦窗那支 JS，而且鏈的三段都在（少一段＝第三關靜靜消失）
② 「空關不跳」與兩個資料形狀轉換沒有被拿掉（那三行是本 phase 最容易被「順手簡化」掉的）
"""

from __future__ import annotations

from pathlib import Path

專案根目錄 = Path(__file__).resolve().parents[2]


def 待決定頁原始碼() -> str:
    """刻意用 read_text() 直接讀、不先判 exists()：

    路徑打錯要當場炸 FileNotFoundError，不能默默變成綠的。
    """
    return (專案根目錄 / "app" / "static" / "pending.html").read_text(encoding="utf-8")


def test_待決定頁載入三個彈窗並依序組成三關():
    """design5.md D2：抽屜 → 實體 → 有待辦建議才開待辦窗。

    第三關少一段就等於「待辦功能被靜靜關掉」——Phase 68 之後上傳頁不再問待辦，
    待決定是唯一還會問的地方。
    """
    原始碼 = 待決定頁原始碼()

    # 三支彈窗檔都要載入；task_modal.js 是本 phase 才加的那一支
    assert '<script src="/ui/folder_modal.js"></script>' in 原始碼
    assert '<script src="/ui/entity_modal.js"></script>' in 原始碼
    assert '<script src="/ui/task_modal.js"></script>' in 原始碼

    # 三關的呼叫都要在，而且要接得起來（前一關的 onDone／onClosed 指向下一關）
    assert "openFolderModal({" in 原始碼
    assert "openEntityModal({" in 原始碼
    assert "openTaskModal({" in 原始碼
    assert "onAssigned: function () { 接著釘實體(photo); }" in 原始碼
    assert "onClosed: function () { 接著釘實體(photo); }" in 原始碼
    assert "onDone: function () { 接著確認待辦(photo); }" in 原始碼

    # 收工只在鏈的最尾端刷新一次（中途刷新會把還沒開的窗一起關掉）
    assert 原始碼.count("location.reload();") == 1


def test_待決定頁的空關不跳與兩個資料形狀轉換都還在():
    """三行很容易被「順手簡化」掉的程式碼，各釘一顆斷言。

    三個都是**安靜壞掉**型的：改壞了頁面不會報錯，只會少一個選項或多開一個空窗。
    """
    原始碼 = 待決定頁原始碼()

    # ① 空關不跳：沒有標題就不開第三窗（trim 不能省——VLM 會回只有空白的字串）
    assert 'const 標題 = (photo.suggested_task_title || "").trim();' in 原始碼
    assert "if (!標題) {" in 原始碼

    # ② 實體建議是**名字字串**，要照名字對回實體清單才拿得到 id
    assert "全部實體.find(function (e) { return e.name === photo.suggested_entity; })" in 原始碼

    # ③ 待辦窗讀的鍵叫 due（不是 due_date），值是 "YYYY-MM-DD" 或空字串
    assert 'suggestion: { title: 標題, due: photo.suggested_task_due || "" },' in 原始碼

    # ④ 不准為了畫①而再看一次圖：待決定頁不該打「再建議一個」那支端點
    #    （窗裡那顆按鈕是 entity_modal.js 自己打的，不在本頁原始碼裡）
    assert "entity-suggestion" not in 原始碼
