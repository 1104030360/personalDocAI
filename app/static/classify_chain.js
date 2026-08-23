/* 三關彈窗鏈（抽屜 → 實體 → 待辦）：上傳頁與無線鏡頭桌面頁共用這一份。
   全站只有這一份鏈邏輯——照片是用檔案上傳還是用手機拍的，之後的流程完全一樣，
   不該有兩份會各自走鐘的複製品（Phase 36 fix round 1 抽出）。

   與 folder_modal.js／entity_modal.js／task_modal.js 的關係：
   那三份各自負責「一個窗長什麼樣、怎麼打 API」；本檔只負責「誰接誰、什麼時候不開」。
   所以本檔不碰 DOM、也不打任何 API——它只呼叫三個 openXxxModal 與呼叫端給的 render。

   用法：
     startClassifyChain({
       photo: body,                       // POST /photos 或 /camera/{token}/photos 的 201 內容
       前言: "",                           // 寫在說明最前面的補充（PDF 用來交代整份結果）
       完成語: "",                          // 整條鏈收工時附在最後的一句（相機頁用「可以繼續拍下一張了。」）
       render: function (photo, 資料夾名稱, 說明) { … }   // 各頁自己畫結果卡
     });

   render 由呼叫端提供，是因為兩頁的結果卡措辭與位置不同（上傳頁寫「已上傳」、
   相機頁寫「手機拍的這張已入庫」）——鏈只負責在每一步之後告訴頁面「現在進度到哪」，
   卡片長什麼樣是頁面自己的事。
   順序固定：抽屜 → 實體 → 待辦（design3.md §2、§2.1），
   而且抽屜按「稍後再說」鏈**仍然繼續**走到實體窗（照片留在待決定不影響釘實體）。
*/

function startClassifyChain(config) {
  const photo = config.photo;
  const 前言 = config.前言 || "";
  const 完成語 = config.完成語 || "";
  const render = config.render;

  // ---- 彈窗 1【抽屜】----
  function 開始歸類() {
    // design2.md D6：AI 建議被 clamp 成「未分類」＝不確定 → 不顯示①，交給「稍後再說」
    const 建議可用 = photo.suggested_folder.id !== photo.folder.id;
    render(
      photo,
      "未分類（待決定）",
      前言 + (建議可用
        ? "AI 建議放進「" + photo.suggested_folder.name + "」，請在彈出的視窗裡決定。"
        : "AI 不確定這張要放哪，請在視窗裡選一個資料夾，或稍後再說。")
    );
    openFolderModal({
      photoId: photo.id,
      // design2.md D7：下拉選單排除收件箱——定案目標必須是真資料夾
      folders: photo.folders.filter(function (f) { return f.id !== photo.folder.id; }),
      primary: 建議可用 ? photo.suggested_folder : null,
      primaryVerb: "採用",
      onAssigned: function (folder) {
        接著釘實體(folder.name, "✅ 已歸到「" + folder.name + "」。");
      },
      onClosed: function () {
        接著釘實體(
          "未分類（待決定）",
          "已放進待決定區，之後到瀏覽頁的「待決定」分頁完成歸類。"
        );
      }
    });
  }

  // ---- 彈窗 2【實體】：抽屜窗結束（不論定案或稍後再說）就接著開 ----
  // 資料夾結果先寫上卡片，實體的成果等使用者按④再補上去——卡片永遠反映目前進度。
  function 接著釘實體(資料夾名稱, 資料夾結果) {
    render(photo, 資料夾名稱, 前言 + 資料夾結果 + "接著決定要不要釘上實體——");
    openEntityModal({
      photoId: photo.id,
      entities: photo.entities,            // 上傳回應帶的完整實體清單（②下拉）
      suggested: photo.suggested_entity,   // clamp 過的建議；null＝①不顯示
      onDone: function (pinned) {
        const 實體結果 = pinned.length > 0
          ? "已釘上 " + pinned.length + " 個實體：" +
            pinned.map(function (e) { return e.name; }).join("、") + "。"
          : "未釘實體。";
        接著確認待辦(前言 + 資料夾結果 + 實體結果, 資料夾名稱);
      }
    });
  }

  // ---- 彈窗 3【待辦】：只有 VLM 判斷有 actionable（suggested_task 有標題）才出現 ----
  // 「空關不跳」（design3.md §2.1）；建立／略過之後整條鏈才算收工。
  function 接著確認待辦(前文, 資料夾名稱) {
    const 建議 = photo.suggested_task;
    if (!建議 || !建議.title) {
      render(photo, 資料夾名稱, 前文 + 完成語);   // 沒有待辦建議：鏈到實體就結束
      return;
    }
    render(photo, 資料夾名稱, 前文 + "最後確認一件待辦——");
    openTaskModal({
      photoId: photo.id,
      suggestion: 建議,
      onDone: function (task) {
        const 待辦結果 = task
          ? "已建立待辦「" + task.title + "」" +
            (task.due_date ? "（到期 " + task.due_date + "）" : "") + "。"
          : "略過待辦。";
        render(photo, 資料夾名稱, 前文 + 待辦結果 + 完成語);
      }
    });
  }

  開始歸類();
}
