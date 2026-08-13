const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const $ = (id) => document.getElementById(id);
let current = {};
const settings = ["provider", "base-url", "model", "target", "overlay-opacity"];
const providerDefaults = {
  openai: ["https://api.openai.com/v1", true, false],
  deepl: ["https://api-free.deepl.com", false, false],
  google: ["https://translation.googleapis.com/language/translate/v2", false, false],
  baidu: ["https://fanyi-api.baidu.com/api/trans/vip/translate", false, true],
  youdao: ["https://openapi.youdao.com/api", false, true]
};

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

function showProvider() {
  const [, needsModel, needsId] = providerDefaults[$("provider").value];
  $("model").hidden = !needsModel;
  $("credential-id").hidden = !needsId;
}

async function showCredentialStatus() {
  try {
    const status = JSON.parse(await invoke("credential_status", { provider: $("provider").value }));
    $("credential-status").textContent = status.secret
      ? "该服务的凭据已保存到系统凭据库"
      : "尚未保存该服务的凭据";
  } catch (error) {
    $("credential-status").textContent = `系统凭据库不可用：${error}`;
  }
}

$("provider").onchange = async () => {
  const [baseUrl] = providerDefaults[$("provider").value];
  $("base-url").value = baseUrl;
  showProvider(); saveSettings(); await showCredentialStatus();
};
$("save-credentials").onclick = () => run($("save-credentials"), async () => {
  await invoke("set_provider_credentials", {
    provider: $("provider").value,
    credentialId: $("credential-id").value,
    secret: $("credential-secret").value
  });
  $("credential-id").value = $("credential-secret").value = "";
  await showCredentialStatus();
});
$("clear-credentials").onclick = () => run($("clear-credentials"), async () => {
  await invoke("clear_provider_credentials", { provider: $("provider").value });
  $("credential-id").value = $("credential-secret").value = "";
  await showCredentialStatus();
});
showProvider(); showCredentialStatus();

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
$("pick-game").onclick = async () => {
  const path = await invoke("pick_directory");
  if (path) $("game").value = path;
};
$("uninstall").onclick = () => run($("uninstall"), async () => {
  $("hook-result").textContent = await invoke("uninstall_hook", { path: $("game").value });
});
$("whole").onclick = () => { $("selected").value = current.text || ""; };
let translationRun = 0;
$("translate").onclick = () => run($("translate"), async () => {
  const runId = ++translationRun;
  $("cancel-translation").hidden = false;
  try {
    const result = await invoke("translate_text", {
      text: $("selected").value, provider: $("provider").value, baseUrl: $("base-url").value,
      model: $("model").value, target: $("target").value
    });
    if (runId === translationRun) $("translation").value = result;
  } catch (error) {
    if (runId === translationRun) throw error;
  } finally {
    if (runId === translationRun) $("cancel-translation").hidden = true;
  }
});
$("cancel-translation").onclick = async () => {
  translationRun++; $("cancel-translation").hidden = true;
  await invoke("cancel_translation");
};

$("save-shortcuts").onclick = () => run($("save-shortcuts"), async () => {
  await invoke("set_shortcuts", { select: $("select-shortcut").value, sentence: $("sentence-shortcut").value });
  localStorage.setItem("shortcuts", JSON.stringify({ select: $("select-shortcut").value, sentence: $("sentence-shortcut").value }));
  $("app-status").textContent = "快捷键已更新";
});
try {
  const shortcuts = JSON.parse(localStorage.getItem("shortcuts"));
  if (shortcuts?.select && shortcuts?.sentence) {
    $("select-shortcut").value = shortcuts.select;
    $("sentence-shortcut").value = shortcuts.sentence;
    invoke("set_shortcuts", shortcuts).catch((error) => { $("app-status").textContent = String(error); });
  }
} catch (_) {}
$("check-update").onclick = () => run($("check-update"), async () => {
  const result = JSON.parse(await invoke("check_update"));
  $("app-status").textContent = result.message;
  if (result.available && result.url && confirm(`${result.message}，打开下载页面？`)) await invoke("open_release", { url: result.url });
});
$("save").onclick = () => run($("save"), async () => {
  await invoke("save_item", {
    kind: $("selected").value === current.text ? "sentence" : "word",
    source: $("selected").value, translation: $("translation").value,
    context: current.text || "", game: current.game || "",
    tags: $("save-tags").value, group: $("save-group").value
  });
  $("save").textContent = "已保存";
  await refreshSaved();
  setTimeout(() => { $("save").textContent = "保存到单词本"; }, 1200);
});

async function loadSaved() {
  const items = JSON.parse(await invoke("list_saved", {
    query: $("saved-search").value.trim(), group: $("saved-group").value.trim()
  }));
  const list = $("saved-list");
  list.replaceChildren();
  if (!items.length) return list.append(Object.assign(document.createElement("small"), { textContent: "暂无收藏" }));
  for (const item of items) {
    const row = document.createElement("article");
    const text = document.createElement("div");
    const source = document.createElement("strong");
    const translation = document.createElement("span");
    const metadata = document.createElement("small");
    source.textContent = item.source_text;
    translation.textContent = item.translated_text;
    metadata.textContent = [item.group_name && `分组：${item.group_name}`, item.tags && `标签：${item.tags}`].filter(Boolean).join(" · ");
    text.append(source, translation, metadata);
    const speak = Object.assign(document.createElement("button"), { textContent: "朗读", className: "quiet" });
    const edit = Object.assign(document.createElement("button"), { textContent: "编辑", className: "quiet" });
    const remove = Object.assign(document.createElement("button"), { textContent: "删除", className: "quiet" });
    edit.onclick = async () => {
      const nextSource = prompt("原文", item.source_text);
      if (nextSource === null) return;
      const nextTranslation = prompt("翻译", item.translated_text);
      if (nextTranslation === null) return;
      const tags = prompt("标签（逗号分隔）", item.tags || "");
      if (tags === null) return;
      const group = prompt("分组", item.group_name || "");
      if (group === null) return;
      await invoke("update_saved", { id: item.id, source: nextSource, translation: nextTranslation, tags, group });
      await refreshSaved();
    };
    speak.onclick = () => speakText(item.source_text);
    remove.onclick = async () => {
      if (!confirm(`删除“${item.source_text}”？`)) return;
      await invoke("delete_saved", { id: item.id });
      await refreshSaved();
    };
    row.append(text, speak, edit, remove);
    list.append(row);
  }
}

let searchTimer;
const scheduleSaved = () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadSaved, 150); };
$("saved-search").oninput = scheduleSaved;
$("saved-group").oninput = scheduleSaved;
$("export-saved").onclick = async () => { $("saved-status").textContent = `已导出到 ${await invoke("export_saved")}`; };
$("import-saved").onclick = () => run($("import-saved"), async () => {
  const count = await invoke("import_saved");
  if (count !== null) {
    $("saved-status").textContent = `已导入 ${count} 条新内容`;
    await refreshSaved();
  }
});

function speakText(text) {
  if (!("speechSynthesis" in window)) return $("saved-status").textContent = "当前系统不支持语音朗读";
  speechSynthesis.cancel();
  speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

let reviewQueue = [];
function showNextReview() {
  const item = reviewQueue.shift();
  if (!item) {
    $("review-card").hidden = true;
    return $("saved-status").textContent = "本轮复习完成";
  }
  $("review-card").dataset.id = item.id;
  $("review-card").dataset.source = item.source_text;
  $("review-source").textContent = item.source_text;
  $("review-translation").textContent = item.translated_text;
  $("review-translation").hidden = $("review-ratings").hidden = true;
  $("reveal-review").hidden = false;
  $("review-card").hidden = false;
}
$("start-review").onclick = () => run($("start-review"), async () => {
  reviewQueue = JSON.parse(await invoke("due_saved"));
  if (!reviewQueue.length) return $("saved-status").textContent = "今天没有待复习内容";
  showNextReview();
});
$("reveal-review").onclick = () => {
  $("review-translation").hidden = $("review-ratings").hidden = false;
  $("reveal-review").hidden = true;
};
$("speak-review").onclick = () => speakText($("review-card").dataset.source || "");
$("review-ratings").onclick = async ({ target }) => {
  const rating = target.dataset.rating;
  if (!rating) return;
  await invoke("review_saved", { id: Number($("review-card").dataset.id), rating });
  if (syncDirectory) await syncSaved();
  showNextReview();
};

let syncDirectory = localStorage.getItem("wordbook-sync-directory") || "";
function showSyncDirectory() {
  $("sync-directory").textContent = syncDirectory || "尚未设置同步目录";
}
async function syncSaved() {
  if (!syncDirectory) return $("saved-status").textContent = "请先选择同步目录";
  const count = await invoke("sync_saved", { directory: syncDirectory });
  $("saved-status").textContent = `同步完成，共 ${count} 条内容`;
  await loadSaved();
}
const refreshSaved = () => syncDirectory ? syncSaved() : loadSaved();
$("pick-sync").onclick = () => run($("pick-sync"), async () => {
  const path = await invoke("pick_directory");
  if (!path) return;
  syncDirectory = path;
  localStorage.setItem("wordbook-sync-directory", path);
  showSyncDirectory();
  await syncSaved();
});
$("sync-saved").onclick = () => run($("sync-saved"), syncSaved);
window.addEventListener("focus", () => refreshSaved().catch((error) => {
  $("saved-status").textContent = String(error);
}));
showSyncDirectory();
refreshSaved().catch((error) => { $("saved-status").textContent = String(error); });
