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
  loadSaved();
  setTimeout(() => { $("save").textContent = "保存到单词本"; }, 1200);
});

async function loadSaved() {
  const items = JSON.parse(await invoke("list_saved", { query: $("saved-search").value.trim() }));
  const list = $("saved-list");
  list.replaceChildren();
  if (!items.length) return list.append(Object.assign(document.createElement("small"), { textContent: "暂无收藏" }));
  for (const item of items) {
    const row = document.createElement("article");
    const text = document.createElement("div");
    const source = document.createElement("strong");
    const translation = document.createElement("span");
    source.textContent = item.source_text;
    translation.textContent = item.translated_text;
    text.append(source, translation);
    const edit = Object.assign(document.createElement("button"), { textContent: "编辑", className: "quiet" });
    const remove = Object.assign(document.createElement("button"), { textContent: "删除", className: "quiet" });
    edit.onclick = async () => {
      const nextSource = prompt("原文", item.source_text);
      if (nextSource === null) return;
      const nextTranslation = prompt("翻译", item.translated_text);
      if (nextTranslation === null) return;
      await invoke("update_saved", { id: item.id, source: nextSource, translation: nextTranslation });
      loadSaved();
    };
    remove.onclick = async () => {
      if (!confirm(`删除“${item.source_text}”？`)) return;
      await invoke("delete_saved", { id: item.id });
      loadSaved();
    };
    row.append(text, edit, remove);
    list.append(row);
  }
}

let searchTimer;
$("saved-search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadSaved, 150); };
$("export-saved").onclick = async () => { $("saved-status").textContent = `已导出到 ${await invoke("export_saved")}`; };
window.addEventListener("focus", loadSaved);
loadSaved();
