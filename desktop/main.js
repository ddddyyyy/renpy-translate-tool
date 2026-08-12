const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const $ = (id) => document.getElementById(id);
let current = {};
const settings = ["base-url", "model", "target", "overlay-opacity"];

function showDisplaySettings() {
  $("overlay-opacity-value").textContent = `${$("overlay-opacity").value}%`;
}

function saveSettings() {
  localStorage.setItem("translation-settings", JSON.stringify(Object.fromEntries(
    settings.map((id) => [id, $(id).value.trim()])
  )));
}

try {
  const saved = JSON.parse(localStorage.getItem("translation-settings"));
  settings.forEach((id) => { if (saved?.[id]) $(id).value = saved[id]; });
} catch (_) {}
settings.forEach((id) => $(id).addEventListener("change", saveSettings));
$("overlay-opacity").addEventListener("input", () => {
  showDisplaySettings();
  saveSettings();
});
showDisplaySettings();
saveSettings();

listen("text-event", ({ payload }) => {
  current = JSON.parse(payload);
  $("speaker").textContent = current.who || (current.event === "choice" ? "选项" : "");
  $("source").textContent = current.text;
  $("selected").value = current.text;
  $("status").textContent = "已连接游戏文本";
});

$("source").addEventListener("mouseup", () => {
  const selected = getSelection().toString().trim();
  if (selected) $("selected").value = selected;
});

async function run(button, action) {
  button.disabled = true;
  try { return await action(); }
  catch (error) { alert(String(error)); }
  finally { button.disabled = false; }
}

$("install").onclick = () => run($("install"), async () => {
  $("hook-result").textContent = await invoke("install_hook", { path: $("game").value });
});
$("uninstall").onclick = () => run($("uninstall"), async () => {
  $("hook-result").textContent = await invoke("uninstall_hook", { path: $("game").value });
});
$("whole").onclick = () => { $("selected").value = current.text || ""; };
$("translate").onclick = () => run($("translate"), async () => {
  $("translation").value = await invoke("translate_text", {
    text: $("selected").value, baseUrl: $("base-url").value,
    model: $("model").value, target: $("target").value
  });
});
$("save").onclick = () => run($("save"), async () => {
  await invoke("save_item", {
    kind: $("selected").value === current.text ? "sentence" : "word",
    source: $("selected").value, translation: $("translation").value,
    context: current.text || "", game: current.game || ""
  });
  $("save").textContent = "已保存";
  setTimeout(() => { $("save").textContent = "保存到单词本"; }, 1200);
});
