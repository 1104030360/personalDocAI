# Phase 70：待決定走完整三關

> 🎯 **提醒：這是 side project，不要過度設計。** 只做本文件寫到的事；想「順便多做一點」的時候，答案一律是「不要」。

> 🎯 **一句話目標：** 待決定頁點開一張照片之後，把彈窗鏈從現在的**兩關**（抽屜 → 實體）
> 補成**三關**（抽屜 → 實體 → **有待辦建議才開**待辦窗），
> 三關要用的建議全部從 Phase 61 落庫的三個欄位讀出來——**不必再看一次圖**。

**為什麼要做這個：**

現在（Phase 52 剛把待決定搬成獨立頁的時候）待決定的鏈只有兩關。原因不是設計上想這樣，
而是**當時上傳頁還會自己開一次完整三關**——上傳成功的 201 回應裡帶著實體建議與待辦建議，
所以「要不要建待辦」那一關在上傳當下就問過了；待決定頁只是「上次沒歸完的補完場」，
再問一次待辦會變成重複。

Phase 68 把上傳頁的開鏈邏輯**整個拿掉**了（design5 D13：上傳與快門當下都不開歸類鏈）。
於是待決定頁變成**全系統唯一**的歸類入口。如果它只有兩關：

- 「這張照片裡有一件待辦」這件事，**從此再也沒有人會問你** → 待辦功能等於被靜靜關掉。
- 實體窗的①「採用建議」在待決定頁一直是**沒有的**（Phase 31 當時建議不落庫，只能按「再建議一個」現算），
  現在建議已經躺在資料庫裡，卻沒人拿出來畫。

所以這個 phase 要做兩件事：**補上第三關**，以及**把①接上落庫的建議**。

> ⚠ 順帶說一件很花時間的事：「再建議一個」那顆按鈕會**真的呼叫一次文字模型**。
> 本機模型看一張圖 64〜88 秒、跑一次文字建議也要好幾十秒。
> 改成讀資料庫欄位之後，①是**零延遲**畫出來的（那筆建議是 worker 在背景看圖時順手寫進去的，
> 現在只是把它讀出來）。這是 design5 §6.2「不必再看一次圖」那句話的實際意義。

**新名詞先解釋：**

| 名詞 | 白話解釋 |
|---|---|
| **三關鏈**（彈窗鏈） | 三個彈出視窗**接力**：關掉第一個就自動開第二個。使用者只按按鈕，不必自己記「下一步是什麼」 |
| **抽屜** | 第一關＝資料夾歸類窗（`folder_modal.js`）。取這個名字是因為資料夾像檔案櫃的抽屜，一張照片只能放進一個抽屜 |
| **別針** | 第二關＝實體釘選窗（`entity_modal.js`）。實體像別針，同一張照片可以別上好幾個（「我的 MacBook」＋「保固」），跟抽屜的「只能選一個」不同 |
| **空關不跳** | 沒有東西可問的那一關，**直接跳過、不要開一個空窗**。這裡指：VLM 沒抽到待辦標題 → 第三窗不開 |
| **八鍵摘要** | `GET /folders/{id}` 回的每張照片摘要有幾個欄位。Phase 35 從四鍵變五鍵、Phase 61 從五鍵變**八鍵**（多了實體建議與待辦標題／到期日） |
| **契約測試**（原始碼字串測試） | 直接讀原始碼、斷言「某一行字真的在裡面」的測試。前端沒有自動化瀏覽器測試時，用它把「這一頁真的載入了那支 JS」這種事釘住，改壞了會馬上紅 |
| **callback**（回呼） | 一個「事情做完之後請幫我呼叫這個函式」的約定。三個彈窗都只透過 `onAssigned`／`onClosed`／`onDone` 對外講話，不去碰頁面其他部分 |

---

## 1. 對應 design5.md 章節

一條都不要漏，每一條都是本 phase 的授權來源：

| 出處 | 說的是什麼 |
|---|---|
| **D2**（§1 決策表） | 「待決定補完鏈改為與**現在的上傳鏈相同**：抽屜 → 實體 → **有待辦建議才開待辦窗**」——本 phase 的主線 |
| **D13** | 「上傳當下不開歸類鏈……歸類只發生在待決定」——這就是為什麼第三關非補不可 |
| **D16** | 「worker 成功 INSERT 時，除既有 `suggested_category` 外，一併寫入實體建議與待辦建議」——三關的建議來源 |
| **§1.1 推翻清單**（倒數第 2 列） | 「design3 §2.1『待決定補完鏈無待辦窗；建議不持久化』→ 建議改落庫（D16）；待決定點開走完整三關」 |
| **§1.1 推翻清單**（最後一列） | 「Phase 30『實體／待辦建議只出現在上傳回應』→ 建議寫進 `photo` 列，待決定開窗再讀」 |
| **§2 流程圖尾段** | 「上傳頁與鏡頭桌面頁都不再呼叫 `classify_chain.js` 的開鏈時機（檔案可留著給待決定頁組鏈，或待決定頁直接 `openFolderModal`＋`openEntityModal`……）」——本 phase §4.2 就是在這兩條路裡選一條 |
| **§6.2**（`/ui/pending.html`） | 「階段丙（上傳不再開鏈）：待決定必須改走完整三關，建議從 D16 的欄位讀（`GET /folders/{inbox}` 照片摘要比照 `suggested_category` 帶出實體／待辦建議，**不必再看一次圖**）；沒有待辦建議就不開第三窗（與現在上傳鏈「空關不跳」相同）」 |
| **§9 測試策略**（前端契約那一列） | 「前端契約：……可用字串釘，比照現有 `片語` 測試」——本 phase §4.4 的兩顆就是這種 |
| **§12 階段丙**（倒數第 2 條） | 「待決定點開：窗頂有原圖；有待辦建議會開第三窗，沒有則不跳（空關不跳）」——產品負責人親自驗的那一條 |
| **§3「不做」**（第 1 列） | 「批次歸類、待決定一次勾多張」——本 phase 明確不做 |

---

## 2. 前置條件

**必須先做完的 phase：**

| Phase | 為什麼一定要在前面 |
|---|---|
| **52** | 建了 `app/static/pending.html`，把 `browse.html` 的 `showPending()` 搬過去。本 phase 改的就是那一頁 |
| **54** | `folder_modal.js` 窗頂加原圖、「稍後再說」文案改指向待決定頁。本 phase 不再動這支檔案 |
| **61** | `photo` 表三個建議欄真的有值，而且 `GET /folders/{id}` 的摘要已經是**八鍵**。**沒有 61 就沒有東西可讀**，本 phase 做不了。（2026-08-26 校準：**61 已隨 commit `f1a7e71` 落地**——`app/schemas/folder.py` 的 `PhotoSummary` 已是八鍵（`id`／`thumbnail_url`／`text`／`uploaded_at`／`suggested_category`／`suggested_entity`／`suggested_task_title`／`suggested_task_due`，型別分別是 `str \| None`／`str \| None`／`date \| None`）、`app/api/routers/folders.py` 三個欄位都有接、`db/migrate_design5.sql` 三個 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 都在，`test_folders_endpoint.py` 的那三顆也都在。下面的 grep 會直接綠。） |
| **68** | 上傳頁拿掉 201 開鏈。**沒有 68，第三關會問兩次**（上傳問一次、待決定又問一次） |
| **69** | 鏡頭桌面頁拿掉「GET latest → 開彈窗鏈」＝ `classify_chain.js` 的**最後一個呼叫者**也消失（phase-69 §3 明文把「刪檔」留給本 phase §4.5）。69 沒做完可以先做 §4.1〜4.4，但 **§4.5 刪檔一定要等它**——§2 下面的第三個 grep 與 §4.5 的閘門都會把這件事守住 |

**★ 閘門 G2 必須已經由產品負責人通過**（design5 §12「階段乙」五條）。
G2 沒過就不該有階段丙的任何一個 phase，本 phase 也一樣。

**開工前先跑這幾行確認基準沒跑掉：**

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
docker compose ps            # db 要是 Up (healthy)，測試庫住在它裡面
pytest -q                    # 記下顆數，做完之後要比對（本 phase 會 +3）
```

```bash
# 待決定頁真的存在，而且已經有兩關的鏈（Phase 52 搬過去的）
ls -l app/static/pending.html
grep -n "openFolderModal\|openEntityModal\|openTaskModal" app/static/pending.html
```

  預期：看得到 `openFolderModal` 與 `openEntityModal`，**看不到** `openTaskModal`
  （那正是本 phase 要補的第三關）。

```bash
# 八鍵摘要（Phase 61）真的到位了
grep -n "suggested_entity\|suggested_task_title\|suggested_task_due" app/schemas/folder.py app/api/routers/folders.py
```

  預期：兩個檔案裡三個欄位都出現。**任何一個沒有，就先回 Phase 61**，不要在這裡自己補
  ——那是 61 的契約，兩個地方各補一半最後一定對不起來。

```bash
# 上傳頁與鏡頭桌面頁真的都不開鏈了（Phase 68／69）
grep -rn "startClassifyChain" app/static/
```

  預期：**只**在 `app/static/classify_chain.js` 自己裡面出現，
  `upload.html` 與 `camera-desk.html` 都不該再有。撈到別的檔案就是 68／69 沒做完。
  （2026-08-26 校準：`classify_chain.js` 自己有 **兩行**——檔頭「用法」那段的
  `startClassifyChain({` 與 `function startClassifyChain(config) {`；舊版寫「定義那一行」
  容易讓人以為多一行就是出事了。另外這一支 grep 只找 `startClassifyChain`，
  所以**不會**撈到 `folder_modal.js` 第 147 行那句只寫檔名的註解——那是 §4.5 那一支
  比較寬的 grep 才會遇到的事。）

---

## 3. 範圍

### 做

- `app/static/pending.html`：把彈窗鏈從兩關補成三關，並讓實體窗的①有東西可顯示。
- `app/static/pending.html`：多載入一支 `/ui/task_modal.js`。
- 兩顆前端契約測試（原始碼字串）＋一顆後端契約測試（實體建議的名字跨端點對得回實體）。
- 刪掉已經沒有任何呼叫者的 `app/static/classify_chain.js`（§4.5，有 grep 閘門）。
- 瀏覽器實操驗收（§4.6）。

### 明確不做（防手滑）

| 不做 | 為什麼 |
|---|---|
| 改 `folder_modal.js`／`entity_modal.js`／`task_modal.js` 任何一行 | 這三支是三個窗**自己**的實作，本 phase 只負責「誰接誰」。它們的行為（強制決定、釘完不關窗、預填建議）一個字都不該變 |
| 為了待決定頁多做一支「批次歸類」或「勾選多張」 | design5 §3「不做」第 1 列明文。一次一張就好 |
| 在待決定頁再打一次 `POST /photos/{id}/entity-suggestion` 來湊①的建議 | 那會真的呼叫模型、要等好幾十秒。①的來源就是資料庫欄位（§6.2 明文）。「再建議一個」那顆按鈕**仍然留著**，想現算的人自己按 |
| 改 `GET /folders/{id}` 的回應形狀 | 八鍵是 Phase 61 定的契約。本 phase 只**讀**它 |
| 改 `PATCH /photos/{id}/folder` 的規則 | 定案不可逆（design2 D3）沒有被本增量推翻（design5 §1.1「未推翻」明列） |
| 動 `browse.html` | Phase 55 已經把待決定 tab 拿掉了。本 phase 不碰它 |
| 新增端點 | 端點數在 Phase 64 之後就是 **22**，本 phase 一支都不加 |
| 新增 Playwright 自動化測試 | 沿 Phase 14／23／24 的慣例：前端靠**瀏覽器實操**驗收，只用原始碼字串釘契約（design5 §9 末段明文） |
| 把三關做成「可以回上一關」 | 沒有人要求。強制決定（design2 D1）的精神是往前走，不是做一個精靈式表單 |

---

## 4. 實作步驟

### 4.0 先看懂現在長什麼樣（不動手，10 分鐘）

- [ ] 打開 `app/static/pending.html`，找到 Phase 52 從 `browse.html` 搬過去的那兩段：
      `showPending()`（畫縮圖牆、掛點擊事件）與 `接著釘實體(photoId)`（第二關）。

- [ ] 讀一次現在的第二關（這是 Phase 52 搬過去、內容沿用 Phase 31 的版本）：

```js
// 這是「改版前」的樣子，貼在這裡是給你對照用的——不要照抄
async function 接著釘實體(photoId) {
  let entities = [];
  try {
    entities = await getJson("/entities");
  } catch (error) {
    // 拿不到清單就當空清單開窗
  }
  openEntityModal({
    photoId: photoId,
    entities: entities,
    suggested: null,        // ← ★ 就是這一行讓①從來不顯示
    onDone: function () {
      location.reload();    // ← ★ 鏈在這裡就結束了，沒有第三關
    }
  });
}
```

- [ ] 讀一次 `app/static/task_modal.js` 的第 12〜20 行（用法說明）。**只要記住三件事**：
  - 它讀的鍵叫 **`suggestion.title`** 與 **`suggestion.due`**（`due`，不是 `due_date`）。
  - 它保證「呼叫端只在有 title 的時候才開窗」——**空關不跳是呼叫端的責任**，不是它的。
  - 它的出口只有兩個：「建立待辦」（`POST /photos/{id}/task`）與「略過」（不打任何 API），
    兩個都會呼叫 `onDone`。

- [ ] 實際看一眼八鍵摘要長什麼樣（**這一步會打到正式庫，但只是 GET，不會改任何東西**）：

```bash
curl -sk "https://127.0.0.1:8000/folders/1" | python -m json.tool | head -40
```

  預期：`photos` 陣列裡每一筆有 8 個鍵。特別注意這兩個的**型別**：

```json
{
  "id": 41,
  "thumbnail_url": "/photos/41/thumbnail",
  "text": "Canvas 上的作業頁面截圖",
  "uploaded_at": "2026-08-25T09:12:00+08:00",
  "suggested_category": "文件",
  "suggested_entity": "我的 MacBook",
  "suggested_task_title": "交 Project 2",
  "suggested_task_due": "2026-08-21"
}
```

  - `suggested_entity` 是**一個名字字串**，不是實體物件（資料庫那一欄是 `TEXT`）。
  - `suggested_task_due` 是 **ISO 日期字串** `YYYY-MM-DD`，或 `null`。

> ⚠ **這兩件事就是本 phase 最容易踩的兩個坑**，§7 陷阱 1、2 會再講一次：
> `openEntityModal` 要的 `suggested` 是**整筆實體物件**（要有 `id` 才釘得上），
> 而 `<input type="date">` **只吃** `YYYY-MM-DD`，格式一錯不會報錯、只會安靜地空白。

### 4.1 決定實作方式：**待決定頁自己組鏈**（不用 `classify_chain.js`）

design5 §2 尾段給了兩條路。本 phase **選第二條**：待決定頁自己依序呼叫
`openFolderModal` → `openEntityModal` → `openTaskModal`。

**四個理由（依重要性排序）：**

1. **`classify_chain.js` 吃的是一個已經不存在的東西。**
   它在第 33〜80 行之間讀的是 `photo.suggested_folder.id`／`photo.folder.id`／`photo.folders`／
   `photo.entities`／`photo.suggested_entity`（**物件**）／`photo.suggested_task`——
   那整包是舊的 `POST /photos` **201 `UploadResponse`**。
   Phase 62 之後 `POST /photos` 回的是 202 `{job_id, filename, content_type}`，
   那個形狀**全系統再也沒有人產生**。要沿用就得寫一層「把八鍵摘要組裝成假的 UploadResponse」
   的轉接層——那層程式碼存在的唯一目的是餵一個死掉的格式，正是「過渡產物」。

2. **它的「共用」前提消失了。**
   `classify_chain.js` 檔頭第 1 行寫得很清楚：「上傳頁與無線鏡頭桌面頁共用這一份」。
   Phase 68／69 之後這兩個呼叫者都不見了。一個只剩**一個**呼叫者的共用檔，
   已經不是共用檔，只是多一層轉手。

3. **它強制要 `render` callback，待決定頁沒有那個東西。**
   `classify_chain.js` 每走一關就呼叫 `render(photo, 資料夾名稱, 說明)` 去更新頁面上的「結果卡」
   （上傳頁寫「已上傳」、相機頁寫「手機拍的這張已入庫」）。
   待決定頁沒有結果卡——它的收尾動作是 `location.reload()`。
   為了滿足介面而傳一個空函式進去，只是把「這裡其實不需要」藏起來。

4. **待決定頁本來就已經有半條鏈了。** Phase 52 搬過去的 `接著釘實體()` 就是第二關。
   補第三關是在同一個檔案裡**多寫 20 行**；改走 `classify_chain.js` 則是刪掉現有的半條鏈、
   再加一層轉接層。後者動的地方多、要驗的東西多，收益是零。

> **那 `classify_chain.js` 怎麼辦？** §4.5 會在確認它零呼叫者之後刪掉它。
> 留著一份沒有人用、而且吃的是已死格式的檔案，下一個人讀到會以為那是活的。

### 4.2 先盤點，再補**一顆**後端契約測試

> **先盤點，別急著寫。** 這是收尾類 phase 的既有作法（Phase 37／44）：
> 每一件事先問「誰已經測了」，只補真正的缺口。重複的測試是負債，不是資產。

| 待決定三關需要的後端契約 | 誰已經測了 |
|---|---|
| `GET /folders/{id}` 的照片摘要恰好是**八鍵** | ✓ Phase 61 改的 `test_folders_endpoint.py::test_資料夾內容含照片摘要` |
| 三個建議欄的**值**帶得出來，`suggested_task_due` 是 ISO 的 `"2026-08-21"` | ✓ Phase 61 的 `test_摘要帶著實體與待辦的建議` |
| 沒有建議的舊照片三個欄位都是 `null` | ✓ Phase 61 的 `test_沒有建議的舊照片三個欄位都是null` |
| **`suggested_entity` 那個名字，在 `GET /entities` 裡對得回一筆實體** | ★ **缺口——本 phase 補這一顆** |

**為什麼最後那一列是真缺口：**
待決定頁拿到的 `suggested_entity` 是**一個名字字串**，而 `openEntityModal` 的 `suggested`
要的是**整筆實體物件**（要有 `id` 才釘得上）。中間那一步是前端自己做的
`全部實體.find(e => e.name === photo.suggested_entity)`——**跨了兩支端點**。
只要有一邊做了正規化（`casefold()`、去空白、加前綴），這個比對就會對不到，
症狀是**實體窗的①靜靜消失**，沒有任何錯誤訊息、沒有任何測試會紅。
Phase 61 那三顆只看 `GET /folders/{id}` 一支，看不到這件事。

- [ ] 在**既有檔案** `tests/integration/test_folders_endpoint.py` 的最後追加這一顆
      （不要另開新檔——那個檔就是 `GET /folders` 系列的家；
      `_插入照片` 是 Phase 61 已經擴充過的那個輔助函式，直接用）：

```python
def test_待決定的實體建議名字在實體清單裡逐字對得到(client):
    """Phase 70：待決定頁靠「名字」把建議對回整筆實體物件，才拿得到 id 去釘。

    Phase 61 已經釘住 GET /folders/{id} 的八鍵與三個欄位的值；
    這一顆釘的是**跨端點的名字契約**：photo.suggested_entity 那個字串，
    必須與 GET /entities 回的 name **逐字相同**（同樣的大小寫、同樣的空白）。
    只要有一邊做了正規化，前端的
        全部實體.find(e => e.name === photo.suggested_entity)
    就會對不到——實體窗的①會靜靜消失，不會有任何錯誤訊息。

    另外，這一顆走的是**收件箱**那條路（Phase 61 那兩顆用的是「收據」資料夾）：
    待決定頁讀的就是收件箱，兩條路各驗一次。
    """
    photo_repository.create_entity("我的 MacBook", "筆電")
    photo_id = _插入照片(
        "MacBook 的維修發票",
        "未分類",                    # insert_photo 會依 category 掛到同名資料夾（Phase 15）
        有縮圖=True,
        suggested_entity="我的 MacBook",
    )

    摘要 = client.get(f"/folders/{未分類_ID}").json()["photos"]
    清單 = client.get("/entities").json()

    assert [p["id"] for p in 摘要] == [photo_id]
    建議名稱 = 摘要[0]["suggested_entity"]
    對到的 = [entity for entity in 清單 if entity["name"] == 建議名稱]
    assert len(對到的) == 1, (
        f"待決定頁靠名字對回實體：「{建議名稱}」在 /entities 裡找不到逐字相同的那一筆"
    )
    assert isinstance(對到的[0]["id"], int), "對到之後要拿得到 id（彈窗要它才釘得上）"
```

- [ ] 確認檔案最上面**已經有** `未分類_ID = 1` 這個常數——它從 Phase 22 起就在了
      （與 `收據_ID = 2`、`飲食_ID = 3` 並列在檔頭），直接用，**不要再定義一次**：

```bash
grep -n "未分類_ID" tests/integration/test_folders_endpoint.py
```

  預期：至少一行 `未分類_ID = 1`。真的沒有（表示有人把它清掉了）才補上，
  註解照同檔既有寫法：「預設資料夾的 id（Phase 15 的種子順序）」。

- [ ] 跑它：

```bash
pytest tests/integration/test_folders_endpoint.py -v -k 實體建議
```

  **預期：1 passed。**（Phase 61 已經把功能做好了，所以這是「首跑就綠」的收尾型測試。）

- [ ] **反向驗證**（30 秒，證明不是假綠）：把 `suggested_entity="我的 MacBook"`
      暫時改成 `suggested_entity="我的 macbook"`（小寫 m）跑一次，要**紅**在
      「在 /entities 裡找不到逐字相同的那一筆」；改回來。
      斷言「某個東西找得到」的測試很容易因為抓錯欄位而永遠成立，反向跑一次才知道它真的在看東西。

> 🔴 **紅了怎麼辦**：如果 `_插入照片` 不吃 `suggested_entity` 這個參數（`TypeError`），
> 代表 Phase 61 沒做完或用了別的參數名。
> **去 `tests/integration/test_folders_endpoint.py` 看那個輔助函式實際的簽章，改測試**
> ——不要自己在 repository 加新函式（那會變成兩條路寫同一批欄位）。

### 4.3 綠：把待決定頁的鏈補成三關

- [ ] **第一步：多載入一支 JS。** 在 `app/static/pending.html` 的 `<script src=…>` 那一區，
      把 `task_modal.js` 加進去。順序要照這樣（三個窗各自獨立、互不 import，
      但都要在頁面自己的 `<script>` 之前載入）：

```html
<script src="/ui/folder_modal.js"></script>
<script src="/ui/entity_modal.js"></script>
<script src="/ui/task_modal.js"></script>
<script src="/ui/progress_panel.js"></script>
<script>
```

> ⚠ `folder_modal.js`／`entity_modal.js` 是 Phase 52 放的、`progress_panel.js` 是
> Phase 67 放的——**照它們現在的樣子留著**，本 phase 只插入 `task_modal.js` 那一行。
> **`photo_detail_modal.js` 不在這一頁，也不要加**：Phase 52 §3 明文不掛它
> （那是唯讀詳情窗，待決定牆點下去要開的是歸類窗，不是它）。
> 如果你的 `pending.html` 的清單與上面不完全一樣，就照現況、只加 `task_modal.js`。

- [ ] **第二步：把整段鏈換掉。** 找到 Phase 52 搬過去的 `接著釘實體(photoId)` 函式，
      **整個函式刪掉**，換成下面這四個函式（完整程式碼，可以直接貼）：

```js
// ---------- 待決定的三關彈窗鏈（design5.md D2、§6.2）----------
//
// 順序固定：抽屜 → 實體 → 有待辦建議才開待辦窗。三關都結束才 location.reload()。
//
// 三關要用的建議全部來自 GET /folders/{收件箱} 的**八鍵摘要**（Phase 61 落庫、
// 本頁只是讀出來），所以開窗是零延遲的——**不會**再去看一次圖
// （本機看一張圖 64〜88 秒，那是 design5 §6.2 特別交代不要做的事）。
//
// ⚠ 兩個資料形狀要轉換，兩個都是「錯了不會報錯、只會安靜地少一個選項」的地雷：
//   ① suggested_entity 是**名字字串**，openEntityModal 要的是**整筆實體物件**（要 id 才釘得上）
//   ② suggested_task_due 是 ISO 的 "YYYY-MM-DD"；task_modal.js 讀的鍵叫 due（不是 due_date）

let 全部實體 = [];      // GET /entities 的最新清單（每次開實體窗前重抓）

function 開始三關(photo, 可選資料夾) {
  // 第一關【抽屜】：①的來源是 suggested_category（Phase 35 就有了，這裡沿用）。
  // 照名字對回資料夾清單；對不到（或根本沒建議）就沒有①，交給「稍後再說」。
  const 建議資料夾 = photo.suggested_category
    ? 可選資料夾.find(function (f) { return f.name === photo.suggested_category; }) || null
    : null;

  openFolderModal({
    photoId: photo.id,
    folders: 可選資料夾,          // 呼叫端已濾掉收件箱（design2.md D7）
    primary: 建議資料夾,
    primaryVerb: "採用",
    // 抽屜窗結束——定案**或**稍後再說——都接著開實體窗（design3.md §2.1，本增量未推翻）
    onAssigned: function () { 接著釘實體(photo); },
    onClosed: function () { 接著釘實體(photo); }
  });
}

async function 接著釘實體(photo) {
  // 實體清單每次開窗前重抓：上一輪③自創的實體要出現在這一輪的②下拉
  try {
    全部實體 = await getJson("/entities");
  } catch (error) {
    // 拿不到清單就當空清單開窗——③自創與④跳過仍然能走；
    // 真的釘選失敗會以紅字顯示在窗內，不必在這裡另立錯誤畫面。
    全部實體 = [];
  }

  // ★ Phase 70：①終於有東西可顯示了。
  //   suggested_entity 存的是**名字**（photo 表那一欄是 TEXT），
  //   照名字對回剛抓到的實體清單，拿到整筆物件（彈窗要 id 才釘得上）。
  //   對不到就是 null＝①整列不顯示，與改版前完全一樣（實體沒有「未分類」保底）。
  const 建議實體 = photo.suggested_entity
    ? 全部實體.find(function (e) { return e.name === photo.suggested_entity; }) || null
    : null;

  openEntityModal({
    photoId: photo.id,
    entities: 全部實體,
    suggested: 建議實體,
    onDone: function () { 接著確認待辦(photo); }
  });
}

function 接著確認待辦(photo) {
  // 「空關不跳」（design3.md §2.1、design5.md D2／§6.2）：
  // 沒有標題就不開第三窗，直接收工——一個空白的待辦窗只會讓人不知道要填什麼。
  // trim() 不能省：VLM 偶爾回一個只有空白的字串，那不是待辦。
  const 標題 = (photo.suggested_task_title || "").trim();
  if (!標題) {
    收工();
    return;
  }

  openTaskModal({
    photoId: photo.id,
    // ★ 鍵名是 due 不是 due_date（task_modal.js 第 154 行讀的就是 config.suggestion.due）；
    //   值是 "YYYY-MM-DD" 或空字串——<input type="date"> 只吃這個格式。
    suggestion: { title: 標題, due: photo.suggested_task_due || "" },
    onDone: function () { 收工(); }
  });
}

function 收工() {
  // 三關都結束才刷新：定案的照片離開待決定、頂欄的「待決定（N）」跟著少一張。
  // 中途刷新會把還沒開的窗一起關掉，等於使用者被打斷。
  location.reload();
}
```

- [ ] **第三步：把縮圖牆的點擊改成呼叫 `開始三關`。** 找到 `showPending()` 裡
      `wall.addEventListener("click", …)` 那一段，換成：

> ⚠ **（2026-08-26 校準）替換範圍不能只圈 `wall.addEventListener` 那一段。**
> 現況（Phase 52 落地版）`pending.html` 的 **第 187〜216 行**是一整塊：
> 187〜191 是「彈窗 1【抽屜】」那五行區塊註解、192 是 `const 可選資料夾 = …`、
> 193〜194 是 `const 照片對照 = {};` 與那一行 `forEach`，196〜216 才是監聽器。
> 下面的替換區塊**自己帶了** `可選資料夾` 與 `照片對照` 兩個 `const`——
> 只換監聽器、把上面那兩個舊的留著，就會是**同一個 `const` 宣告兩次**，
> 整頁當場 `SyntaxError: Identifier '可選資料夾' has already been declared`，
> 而且是**整頁白掉**（inline script 一個字都不會執行）。
> **從第 187 行的註解開始整段換到 216**，不要自己縮小範圍。

```js
  // 待決定牆：點一張照片就走完整三關（design5.md D2）。
  // 照片對照表把 id 換回**整筆八鍵摘要**——三關要的三個建議都在那一筆裡面，
  // 只傳 photoId 的話等一下還要再查一次。
  const 可選資料夾 = folders.filter(function (f) { return !f.is_inbox; });
  const 照片對照 = {};
  detail.photos.forEach(function (photo) { 照片對照[photo.id] = photo; });

  wall.addEventListener("click", function (event) {
    const card = event.target.closest(".photo");
    if (!card || !card.dataset.photoId) return;
    const photo = 照片對照[Number(card.dataset.photoId)];
    if (!photo) return;        // 理論上不會發生；防的是 DOM 被別的程式改過
    開始三關(photo, 可選資料夾);
  });
```

- [ ] **第四步：確認 `getJson` 這個小工具在 `pending.html` 裡真的存在。**
      它是 Phase 52 從 `browse.html` 一起搬過去的：

```bash
grep -n "async function getJson" app/static/pending.html
```

  預期：**一行**。沒有的話，把 `browse.html` 第 52〜58 行那個函式原樣搬過去
  （不要改寫成 `fetch` 直呼——錯誤處理的形狀要跟全站一致）。

- [ ] **第五步：語法檢查**（前端沒有自動化測試，這一步是唯一的「編譯器」）：

```bash
node --check app/static/task_modal.js
python - <<'PY'
import re, pathlib
原始碼 = pathlib.Path("app/static/pending.html").read_text(encoding="utf-8")
區塊 = re.findall(r"<script>(.*?)</script>", 原始碼, re.S)
pathlib.Path("/tmp/pending-inline.js").write_text("\n".join(區塊), encoding="utf-8")
print(f"抽出 {len(區塊)} 段內嵌 script，共 {sum(len(b.splitlines()) for b in 區塊)} 行")
PY
node --check /tmp/pending-inline.js && echo "pending.html 的 JS 語法沒問題"
```

  預期：最後一行印出「pending.html 的 JS 語法沒問題」。
  （`node --check` 只驗語法、不執行，所以 `document` 之類的東西不存在也沒關係。）

### 4.4 綠：兩顆前端契約測試（原始碼字串）

前端沒有自動化瀏覽器測試，所以用「讀原始碼、斷言某一行字在裡面」把契約釘住。
這是本專案既有手法（`test_design4_error_paths.py::test_手機版遺失縮圖與中文斷行都有保護`
就是這樣寫的，design5 §9 也明文說「可用字串釘，比照現有 `片語` 測試」）。

- [ ] 新建 `tests/integration/test_pending_chain.py`：

```python
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
    assert (
        "全部實體.find(function (e) { return e.name === photo.suggested_entity; })"
        in 原始碼
    )

    # ③ 待辦窗讀的鍵叫 due（不是 due_date），值是 "YYYY-MM-DD" 或空字串
    assert (
        'suggestion: { title: 標題, due: photo.suggested_task_due || "" },' in 原始碼
    )

    # ④ 不准為了畫①而再看一次圖：待決定頁不該打「再建議一個」那支端點
    #    （窗裡那顆按鈕是 entity_modal.js 自己打的，不在本頁原始碼裡）
    assert "entity-suggestion" not in 原始碼
```

> **如果 Phase 52 已經建了功能相近的檔案**（例如 `tests/integration/test_pending_page.py`），
> 就把上面這兩顆**併進那個檔**，不要為了兩顆測試多開一個檔。
> 先跑 `ls tests/integration/ | grep -i pending` 確認。

- [ ] 跑：

```bash
pytest tests/integration/test_pending_chain.py -v
```

  **預期：2 passed。**

- [ ] **反向驗證**：把 `assert '<script src="/ui/task_modal.js"></script>' in 原始碼`
      暫時改成 `not in`，跑一次要**紅**；改回來。

### 4.5 刪掉沒有人用的 `classify_chain.js`

- [ ] **閘門：先確認它真的零呼叫者。**（只掃 `app/`——`tests/` 裡**允許**出現這個字串：
      Phase 69 的契約測試就是在斷言「桌面頁沒有 `startClassifyChain`」，
      斷言本身當然含有那個字。「還有沒有人用」只看 `app/`。）

```bash
grep -rn "classify_chain\|startClassifyChain" app/ --include="*.html" --include="*.js" --include="*.py"
```

  **預期：只有 `app/static/classify_chain.js` 自己的那幾行**（檔頭註解與
  `function startClassifyChain(config) {` 那一行）**，外加 `app/static/folder_modal.js`
  第 147 行的一句註解**。

> 📌 **（2026-08-26 事後追記，Phase 71 之後讀本檔的人看這裡）**：本 phase 執行當下
> 下面這段校準完全成立、驗收也照它過了；但 **Phase 71 已把 `folder_modal.js:147`
> 那句過期註解一併校正**（執行者裁決的純註解修正，71 的 REP 有記錄），
> 所以**現在** `grep -rn "classify_chain" app/` 是**零輸出**、比下面寫的更乾淨。
> 下面那段保留不動，作為本 phase 執行當下的歷史紀錄。
>
> ⚠ **（2026-08-26 校準）`folder_modal.js:147` 會一直被撈到，那是正常的。**
> Phase 54 在 `fm畫圖()` 上方寫了一行說明：
> 「`//      三個呼叫端（pending.html／browse.html／classify_chain.js）都不用改；`」
> ——那是**註解裡的檔名**，不是呼叫，而且 §3「明確不做」第 1 列禁止改 `folder_modal.js`
> 的任何一行，所以它刪檔之後仍然會留著。
> **判準因此改成：除了 `classify_chain.js` 自己與 `folder_modal.js` 第 147 行那句註解之外，
> 沒有第二個檔案提到它。** 想一眼看乾淨的話用這一行（把註解那個檔排除掉）：
>
> ```bash
> grep -rn "classify_chain\|startClassifyChain" app/ \
>   --include="*.html" --include="*.js" --include="*.py" \
>   | grep -v "^app/static/folder_modal.js:"
> ```

  ⛔ **只要撈到任何一個 `.html` 還在載入它，就停手**——那代表 Phase 68 或 69 沒做完。
  回去把那一頁處理掉，再回來做這一步。

- [ ] 刪檔（用 `rm`，**不要用 `git rm`**——`git rm` 會直接 stage，與「先不 commit」的
      既有指示衝突，而且 stage 之後下面的後悔藥指令會失效；比照 Phase 72 §3 對
      `git mv` 的同一條理由。檔案已入版控，`rm` 之後 `git status` 會出現未 stage 的
      ` D`，最後 commit 時一起收）：

```bash
rm app/static/classify_chain.js
```

- [ ] 確認沒有 404：`pending.html`／`upload.html`／`browse.html`／`camera-desk.html`／
      `camera-phone.html`／`ask.html` 六頁都不該再引用它（上一步的 grep 已經證明了）。

- [ ] 全量跑一次確認沒有測試指著它：

```bash
pytest -q
```

> **後悔藥**：刪錯了就 `git checkout -- app/static/classify_chain.js` 把它拿回來
> （2026-08-26 校準：這一招成立的理由與「本增量有沒有 commit」無關——
> `classify_chain.js` 是**增量三**就入版控的檔（`git ls-files app/static/classify_chain.js`
> 查得到），`rm` 之後內容仍在 HEAD 裡，`git checkout --` 一定拿得回來）。

### 4.6 瀏覽器實操驗收（前端唯一的真驗收）

**準備：**

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
```

網址：`https://localhost:8000/ui/pending.html`（**開頭是 https，不是 http**）。
待決定要有東西可點——先在上傳頁丟兩三張圖進去，等右下角進度面板的列消失。

> 💡 **先把頁首的「AI 模型」開關撥到「雲端」**：本機看一張圖 64〜88 秒，
> 雲端約 2 秒。這一輪要驗的是彈窗鏈，不是模型速度（design5 §7 末段的建議）。

逐項做，**每一項都寫下「看到什麼」**：

| # | 做什麼 | 通過條件 |
|---|---|---|
| 1 | 開 `/ui/pending.html`，點一張**有待辦建議**的照片（Canvas 截圖、繳費單這類最容易抽到） | 跳出**抽屜窗**；窗最上面是**原圖**（Phase 54 加的）；下面四個出口都在 |
| 2 | 抽屜窗按①「採用『某資料夾』」 | 窗關掉、**馬上**跳出**實體窗**（不是回到縮圖牆） |
| 3 | 看實體窗最上面那一列 | ★**有①**「釘上『某實體』」——這是本 phase 的重點。以前這一列是不顯示的 |
| 4 | 實體窗按④「不釘，繼續」 | 窗關掉、**馬上**跳出**待辦窗** |
| 5 | 看待辦窗的兩個輸入框 | 標題**已經預填**；有到期日的話日期欄也**已經預填**（不是空白） |
| 6 | 按「建立待辦」 | 三個窗全關、頁面重新整理；剛剛那張照片**不在**待決定牆上了；頂欄的「待決定（N）」少一張 |
| 7 | 到 `/ui/browse.html?tab=tasks` | 剛建的待辦在清單裡，標題與到期日都對 |
| 8 | 回待決定頁，點一張**沒有**待辦建議的照片（風景照最容易），走完抽屜 → 實體 | ★**待辦窗不開**（空關不跳）——實體窗按④之後直接刷新回縮圖牆 |
| 9 | 再點一張，抽屜窗按④「稍後再說」 | 照片**留在**待決定，但**仍然**跳出實體窗（抽屜稍後再說不影響釘實體） |
| 10 | 上一步的實體窗按③自創一個新實體、再按④ | 釘上之後**窗不關**、已釘列表 +1；按④才收工 |
| 11 | 點一張**沒有原圖的照片**（見下面的校準框；沒有就標 N/A） | 抽屜窗照樣開，圖的位置是灰底占位；三關照樣走得完 |
| 12 | 全程開著開發者工具的 Console | **沒有**紅色錯誤；特別確認沒有 `openTaskModal is not defined`（那代表第一步的 `<script>` 忘了加） |
| 13 | 全程 | **沒有**任何瀏覽器原生對話框（`alert`／`confirm`／`prompt`）——錯誤一律是窗內紅字 |

> ⚠ **（2026-08-26 校準）第 11 項的「正式庫最早那兩張沒有原圖的」已經不在待決定裡了。**
> 實測正式庫（唯讀 SQL）：`original_path IS NULL` 的就是那兩張，兩張都在**「收據」**資料夾——
> 也就是**早就定案了**，永遠不會出現在待決定牆上；收件箱（未分類）現有 10 張，**全部都有原圖**。
> 所以這一項改成**選擇性**：開工當天先用下面這行看有沒有這種照片，沒有就**標 N/A**
> （`folder_modal.js` 的 `fm畫占位()` 降級路徑已由 Phase 54 的瀏覽器實操驗過，
> 本 phase 一行都沒動它）：
>
> ```bash
> psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI -tAc \
>   "select p.id from photo p join folder f on f.id=p.folder_id \
>    where f.is_inbox and p.original_path is null;"
> ```
>
> ⛔ **不要**為了驗這一項去搬動或改名 `data/photos/` 裡的檔案——那是全世界只有一份、
> 不入版控的原圖（CLAUDE.md 指令區的備份段落）。

- [ ] 十三項全部通過才算完成（第 11 項可為 N/A）。

---

## 5. ASCII 圖

### 5.1 三關鏈：四個出口與「空關不跳」的分支

```text
   待決定頁 /ui/pending.html
   縮圖牆（只含還在收件箱的照片）
        │  點一張
        ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 第一關【抽屜】folder_modal.js                            │
 │ 窗頂：原圖 <img src="/photos/{id}/image">（Phase 54）      │
 │                                                          │
 │  ① 採用「文件」   ← suggested_category 對回資料夾清單     │
 │     （沒建議／對不到 → 這一列整個不顯示）                 │
 │  ② 改選其他現有資料夾（下拉；已排除收件箱）              │
 │  ③ 自建新資料夾                                          │
 │  ④ 稍後再說          ← 不打任何 API，照片留在待決定       │
 │                                                          │
 │  ⛔ 沒有 ×、不吃 Esc、點暗色區不會關（design2 D1 強制決定）│
 └──────────┬───────────────────────────────┬───────────────┘
            │ ①②③ 定案（PATCH 200）        │ ④ 稍後再說
            │                               │
            └───────────────┬───────────────┘
                            │  ★ 兩條路都往下走
                            ▼
 ┌──────────────────────────────────────────────────────────┐
 │ 第二關【別針】entity_modal.js                            │
 │                                                          │
 │  ① 釘上「我的 MacBook」                                   │
 │     ★ Phase 70 起這一列才有東西：                         │
 │       suggested_entity（名字字串）→ 對回 GET /entities    │
 │       → 拿到 {id, name, description} → 才釘得上          │
 │  ② 改選其他現有實體（下拉）                              │
 │  ③ 自創新實體                                            │
 │  ④ 不釘，繼續／完成，繼續                                 │
 │  ＋「再建議一個」（會真的呼叫模型，人主動按才算）         │
 │                                                          │
 │  釘上（①②③）成功後**窗不關**，可以繼續釘下一個          │
 └──────────┬───────────────────────────────────────────────┘
            │ ④ 才離開這一關
            ▼
     ┌─────────────────────────────┐
     │ suggested_task_title 有字嗎？│   ← 「空關不跳」的那個分支
     │ （trim() 之後還有內容）      │
     └──────┬───────────────┬──────┘
            │ 沒有           │ 有
            │                ▼
            │  ┌──────────────────────────────────────────┐
            │  │ 第三關【待辦】task_modal.js               │
            │  │  標題輸入框 ← 預填 suggested_task_title    │
            │  │  到期日輸入框 ← 預填 suggested_task_due    │
            │  │    （<input type="date"> 只吃 YYYY-MM-DD） │
            │  │  ［建立待辦］ POST /photos/{id}/task       │
            │  │  ［略  過  ］ 什麼都不打                   │
            │  └──────────┬───────────────────────────────┘
            │             │ 兩個出口都往下
            └─────────────┴──────────┐
                                     ▼
                             location.reload()
                             （全鏈只有這一次刷新）
                                     │
                                     ▼
                       定案的照片離開待決定牆
                       頂欄「待決定（N）」少一張
```

### 5.2 一筆建議從「看圖」走到「畫成選項①」的一路

```text
 ①  worker 背景看圖（Celery，Phase 59／60）
     ──────────────────────────────────────────────────────────
     VLM 同一次輸出 9 欄，其中三欄是「建議」：
       category      → clamp 到現有資料夾清單（清單外＝未分類）
       entity        → clamp 到現有實體清單（清單外＝None，實體沒有保底）
       task_title / task_due
                                    │
                                    ▼
 ②  INSERT 進 photo 表（Phase 61 接的線；design5 D16）
     ──────────────────────────────────────────────────────────
      photo
      ├─ suggested_category      TEXT   "文件"        （Phase 35 就有）
      ├─ suggested_entity        TEXT   "我的 MacBook" ★ Phase 56 新欄
      ├─ suggested_task_title    TEXT   "交 Project 2" ★ Phase 56 新欄
      └─ suggested_task_due      DATE    2026-08-21    ★ Phase 56 新欄
                                    │
                                    │  ⚠ 只是「建議」——人按確認才會真的
                                    │     寫 folder／entity／photo_entity／task
                                    ▼
 ③  GET /folders/{收件箱}  的照片摘要（Phase 61 從五鍵變**八鍵**）
     ──────────────────────────────────────────────────────────
      {
        "id": 41, "thumbnail_url": "…", "text": "…", "uploaded_at": "…",
        "suggested_category":   "文件",
        "suggested_entity":     "我的 MacBook",    ← 名字**字串**，不是物件
        "suggested_task_title": "交 Project 2",
        "suggested_task_due":   "2026-08-21"       ← ISO 字串，不是 datetime
      }
                                    │
                                    ▼
 ④  pending.html 的三關鏈（本 phase）
     ──────────────────────────────────────────────────────────
      suggested_category    ──對回──► folders  ──► 抽屜窗的 ①
                                 （find by name）

      suggested_entity      ──對回──► GET /entities ──► 實體窗的 ①
                                 （find by name，★ 這一段是本 phase 新加的）

      suggested_task_title  ──trim()──► 有字才開第三窗   ← 空關不跳
      suggested_task_due    ──────────► 第三窗日期欄預填

     ★ 全程**零模型呼叫**：三個①都是讀資料庫欄位畫出來的。
       本機再看一次圖要 64〜88 秒，那正是 design5 §6.2 要避開的事。
```

### 5.3 實體窗的①：以前 vs 現在

```text
 ── 以前（Phase 31〜Phase 69；browse.html 待決定分頁 → pending.html）────────
    openEntityModal({ …, suggested: null, … })
                              ▲
                              └─ 寫死 null，因為當時建議只活在上傳的 201 回應裡，
                                 待決定頁沒有任何持久化的建議可讀
                                 （design3 §2.1 明文列為「已知限制」）

    ┌──────────────────────────────────┐
    │ 要把這張照片釘上實體嗎？（可釘多個）│
    │                                  │
    │ （① 這一列整個不顯示）            │  ← 想要建議只能按下面那顆
    │ ② 改選其他現有實體：[下拉 ▾][釘上]│     「再建議一個」，會**真的呼叫模型**
    │ ③ 自創新實體：[名稱][說明][建立]  │
    │ ④［再建議一個］［不釘，繼續］      │
    └──────────────────────────────────┘

 ── 現在（Phase 70；建議已落庫，design5 D16）──────────────────────────────
    const 建議實體 = photo.suggested_entity
      ? 全部實體.find(e => e.name === photo.suggested_entity) || null
      : null;
    openEntityModal({ …, suggested: 建議實體, … })

    ┌──────────────────────────────────┐
    │ 要把這張照片釘上實體嗎？（可釘多個）│
    │                                  │
    │ ①［釘上「我的 MacBook」］          │  ★ 零延遲畫出來（讀欄位，不看圖）
    │    筆電                           │
    │ ② 改選其他現有實體：[下拉 ▾][釘上]│
    │ ③ 自創新實體：[名稱][說明][建立]  │
    │ ④［再建議一個］［不釘，繼續］      │  ←「再建議一個」**留著**，
    └──────────────────────────────────┘     想現算的人自己按

    ⚠ 對不回實體清單時（實體被改名、或 GET /entities 掛了）→ 建議實體 = null
      → ①照舊不顯示。**降級成以前的樣子，不會壞掉。**
```

---

## 6. 驗收清單

每一條都可以客觀驗證，附指令與預期輸出。

- [ ] §4.2 的盤點表做完，**確認 Phase 61 那三顆真的存在且是綠的**（不是抄的）：

```bash
pytest tests/integration/test_folders_endpoint.py -v -k "摘要 or 建議"
```

- [ ] `pytest tests/integration/test_folders_endpoint.py -v -k 實體建議` ＝ **1 passed**
- [ ] 上面那顆做過**反向驗證**（把名字改成小寫會紅）＝證明不是假綠
- [ ] `pytest tests/integration/test_pending_chain.py -v` ＝ **2 passed**
      （這個檔是**本 phase 新建**的——Phase 52 建待決定頁時零新增測試檔，
      所以不會有「要不要併進去」的問題，照 §4.3 新建即可）
- [ ] `grep -c "openTaskModal" app/static/pending.html` ＝ **1**（第三關真的接上了）
- [ ] `grep -c "location.reload();" app/static/pending.html` ＝ **1**（只在鏈尾刷新一次）
- [ ] `node --check /tmp/pending-inline.js` 通過（§4.3 第五步那段指令會產生這個檔）
- [ ] `grep -rn "classify_chain\|startClassifyChain" app/` ＝ **只剩 `app/static/folder_modal.js:147`
      那一句註解**（檔案已刪、沒有殘留**引用**；那一行是 Phase 54 寫的說明文字，
      §3「不做」禁止改它，見 §4.5 的校準框。`tests/` 不列入——Phase 69 那顆
      「斷言桌面頁沒有它」的契約測試裡合法含有這個字串）
- [ ] `ls app/static/classify_chain.js` ＝ `No such file or directory`
- [ ] `git status --short app/static/` 與**本 phase 開工前記下的輸出**相比，多兩行：
      ` M app/static/pending.html` 與 ` D app/static/classify_chain.js`
      （2026-08-26 校準：舊版這一條寫「只多一行」、並說 `pending.html` 是「`??` 的新檔」——
      **那已經過期了**。Phase 52〜64 已於 commit `e1d1d5e`／`f1a7e71` 進版控，
      `git ls-files app/static/pending.html` 查得到它，所以改它一定會多一行 ` M`。
      至於 65〜69 的變更在不在清單上，看那幾個 phase 屆時有沒有 commit——
      **本條的判準是「相減之後只多這兩行」，不是清單長度**）
- [ ] `pytest -q` 全綠、**0 skipped**，顆數 ＝ 開工基準 **＋3**
      （`test_folders_endpoint.py` 1 顆 ＋ `test_pending_chain.py` 2 顆）。
      開工前先把基準記下來，做完之後填進這裡：基準 ＿＿＿ → 完成 ＿＿＿
- [ ] `OLLAMA_BASE_URL=http://localhost:9 pytest -q` 顆數**完全相同**（證明沒有偷打真模型）
- [ ] `curl -sk https://127.0.0.1:8000/openapi.json | python -c "import json,sys; p=json.load(sys.stdin)['paths']; print(len([(a,b) for a,i in p.items() for b in i]))"`
      ＝ **22**（本 phase 一支端點都沒加）
- [ ] `git diff --stat app/static/folder_modal.js app/static/entity_modal.js app/static/task_modal.js`
      ＝ **無輸出**（三個窗自己的實作一行未動）
- [ ] `git diff --stat app/api/routers/ app/services/ app/repositories/`
      ＝ **無輸出**（本 phase 是純前端＋測試，後端一行未動）
- [ ] §4.6 瀏覽器實操 **13 項全部通過**（第 11 項依 §4.6 的校準框可為 N/A），
      特別是第 3 項（實體窗有①）與第 8 項（空關不跳）
- [ ] Console 全程沒有紅色錯誤；沒有任何 `alert`／`confirm`／`prompt`
- [ ] **沒有 commit**（沿用產品負責人既有指示：改完先檢視；`unfinish/` → `finish/` 的歸檔隨 commit 執行）

---

## 7. 常見陷阱

1. **把 `suggested_entity`（名字字串）直接丟給 `openEntityModal` 的 `suggested`。**
   症狀：①那顆按鈕的文字變成「釘上『undefined』」，按下去 `POST` 的 body 是
   `{"entity_id": undefined}` → 送出去變成 `{}` → 後端回 **422**
   （`app/schemas/entity.py` 的訊息原文：「entity_id 與 name 必須恰好提供一個」），
   窗內出現紅字。
   原因：`entity_modal.js` 第 138 行讀 `emSuggested.name`、第 245 行讀 `emSuggested.id`，
   它要的是**整筆實體物件**。資料庫那一欄存的只是名字（`TEXT`）。
   修法：照 §4.3 的 `全部實體.find(…)` 對回清單。

2. **把 `suggested_task_due` 用錯鍵名，或格式不對。**
   兩種症狀都一樣：**日期欄永遠空白，而且什麼錯誤都不會出現**。
   - 鍵名寫成 `due_date`：`task_modal.js` 第 154 行讀的是 `config.suggestion.due`，
     讀到 `undefined` → `|| ""` → 空白。
   - 值帶了時間（`"2026-08-21T00:00:00"`）：`<input type="date">` 拒絕這個格式，
     瀏覽器**靜默忽略**、欄位留白。
   修法：鍵名一定是 `due`；值一定是 10 個字元的 `YYYY-MM-DD` 或空字串。
   §4.2 那顆後端測試就是在守這件事。

3. **忘了在 `pending.html` 加 `<script src="/ui/task_modal.js">`。**
   症狀：前兩關都正常，實體窗按④之後**什麼都沒發生**，Console 印
   `Uncaught ReferenceError: openTaskModal is not defined`，
   而且因為那行錯誤發生在 callback 裡，**頁面不會刷新**——看起來像「卡住了」。
   修法：§4.3 第一步。`test_pending_chain.py` 第一顆就是在擋這個。

4. **在鏈的中途 `location.reload()`。**
   最常見的寫法是把 Phase 52 原本 `接著釘實體` 裡的 `location.reload()` 留著沒刪。
   症狀：抽屜定案 → 實體窗開了一下就整頁刷新 → 使用者根本來不及釘實體，
   而且**第三關永遠不會開**。
   修法：全檔只能有**一次** `location.reload()`，在 `收工()` 裡。
   驗收清單那顆 `grep -c` 就是在數這件事。

5. **`trim()` 被拿掉。**
   VLM 偶爾會回一個只有空白字元的 `task_title`。沒有 `trim()` 的話
   `if (!photo.suggested_task_title)` 會是 `false`（空白字串是 truthy 的），
   於是**開出一個標題欄只有空白的待辦窗**——使用者不知道要填什麼，
   而且按「建立」會拿到 422（標題空白）。
   這正是 design5 §12 那條驗收「沒有則不跳」要抓的情況。

6. **為了讓①有東西，在待決定頁多打一次 `POST /photos/{id}/entity-suggestion`。**
   那支端點會**真的呼叫文字模型**。本機一次好幾十秒——點一張照片要等半分鐘才跳窗，
   而且每點一張就再花一次。design5 §6.2 明文「不必再看一次圖」。
   ①的來源是資料庫欄位，就這樣。「再建議一個」那顆按鈕留著，是給**人主動**按的。

7. **以為 `classify_chain.js` 還在被誰用，不敢刪。**
   §4.5 那個 grep 就是拿來判斷的。判準只有一個：
   **`app/` 底下除了它自己以外，有沒有第二個檔案提到它**
   （`tests/` 裡 Phase 69 那顆「斷言桌面頁沒有它」的測試不算——那是在證明沒人用）。
   沒有＝零呼叫者＝刪。刪錯了 `git checkout` 就回來了。
   留著的成本不是磁碟空間，是下一個人讀到它、以為那是活的鏈，
   然後照著它的 `photo.suggested_folder` 去改東西——那個形狀在 Phase 62 之後已經不存在。

8. **抽屜窗按「稍後再說」就直接刷新頁面。**
   看起來很合理（「他不想歸類啊」），但 design3 §2.1 明文：
   **抽屜窗結束——定案或稍後再說——都接著開實體窗**。
   理由是「照片留在待決定」跟「這張照片上有沒有我的 MacBook」是兩件獨立的事，
   前者沒決定不代表後者不能決定。本增量沒有推翻這一條。

9. **只跑新測試就收工。**
   一定要跑全量（`pytest -q`）＋零 Ollama 那一輪。
   本 phase 刪了一個檔案、改了一頁 HTML——刪檔這種事最容易在別的地方留下 404，
   只跑兩個測試檔看不出來。

10. **想順便把三個彈窗合併成一個「精靈」。**
    三窗分立是 design3 D9／§2.1 的決定（不可合併、不可對調），design5 沒有推翻它。
    看到想改的先記下來，留給下一個增量。
