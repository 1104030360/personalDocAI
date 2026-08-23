// 全站 AI 模型開關（本機 ⇄ Ollama Cloud；2026-08-22）——開關程式全站唯一一份。
// upload.html 與 ask.html 頁首放的是同一顆開關（id 相同），這支檔案負責：
// 載入時 GET /settings/ai-backend 畫初始位置、點擊 PUT 撥過去、
// 結果／錯誤寫在開關旁（禁用 alert）。狀態的唯一真相在伺服器
// （config.AI_BACKEND，管看圖＋詢問路由／回答＋實體建議），
// 所以在哪一頁撥都是撥同一個系統狀態，換頁後重新 GET 自然一致。
//
// 對外只暴露 aiBackendNow()：頁面拿它決定等待提示的措辭。
// 「選中側」的樣式直接跟著 aria-checked 走（style.css 用屬性選擇器），
// 這裡只改屬性、不另外掛 class——樣式與無障礙狀態永遠一致。

let aiSwitchBackend = "local";

function aiBackendNow() {
  return aiSwitchBackend;
}

(function () {
  const toggle = document.getElementById("ai-toggle");
  const msg = document.getElementById("ai-switch-msg");
  if (!toggle) return;   // 沒放開關的頁面載入這支檔案也不做事

  let msgTimer = null;

  function paint() {
    toggle.setAttribute(
      "aria-checked", aiSwitchBackend === "cloud" ? "true" : "false"
    );
  }

  // 開關旁的一句話回饋。成功訊息幾秒後自己消失；錯誤（要人去改 .env）留著。
  function say(message, isError) {
    clearTimeout(msgTimer);
    msg.textContent = message;
    msg.classList.toggle("is-error", Boolean(isError));
    if (!isError && message) {
      msgTimer = setTimeout(function () { msg.textContent = ""; }, 4000);
    }
  }

  async function load() {
    try {
      const response = await fetch("/settings/ai-backend");
      aiSwitchBackend = (await response.json()).backend;
    } catch (error) {
      // 伺服器沒起來就維持預設（本機）；真正的失敗會在各頁自己的請求裡浮現
    }
    paint();
  }

  toggle.addEventListener("click", async function () {
    const 目標 = aiSwitchBackend === "cloud" ? "local" : "cloud";
    toggle.disabled = true;
    try {
      const response = await fetch("/settings/ai-backend", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend: 目標 }),
      });
      const body = await response.json();
      if (response.ok) {
        aiSwitchBackend = body.backend;
        say(
          aiSwitchBackend === "cloud" ? "AI 改走 Ollama Cloud" : "AI 改回本機模型",
          false
        );
      } else {
        // 最常見：.env 沒填 OLLAMA_API_KEY → 422，開關留在原位、原因寫在旁邊
        say(typeof body.detail === "string" ? body.detail : "切換失敗", true);
      }
    } catch (error) {
      say("連不上伺服器，開關未變更", true);
    } finally {
      toggle.disabled = false;
      paint();
    }
  });

  load();
})();
