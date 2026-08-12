const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const $ = (id) => document.getElementById(id);
let current = {};
let selected = "";
let translated = "";
let hideTimer;
let resizeTimer;

try {
  const { width, height } = JSON.parse(localStorage.getItem("overlay-size")) || {};
  if (Number(width) && Number(height)) invoke("resize_overlay", { width: Number(width), height: Number(height) }).catch(() => {});
} catch (_) {}

window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => localStorage.setItem("overlay-size", JSON.stringify({
    width: window.innerWidth,
    height: window.innerHeight
  })), 200);
});

function displaySettings() {
  let settings = {};
  try { settings = JSON.parse(localStorage.getItem("translation-settings")) || {}; }
  catch (_) {}
  const opacity = Math.min(100, Math.max(40, Number(settings["overlay-opacity"]) || 95));
  document.documentElement.style.setProperty("--overlay-opacity", opacity / 100);
}

function applyText(payload) {
  current = typeof payload === "string" ? JSON.parse(payload) : payload;
  selected = "";
  translated = "";
  $("speaker").textContent = current.who || (current.event === "choice" ? "选项" : "当前文本");
  $("source").textContent = current.text;
}

function applyMode(payload) {
  clearTimeout(hideTimer);
  $("result").textContent = "";
  $("save").disabled = true;
  if (payload === "sentence") {
    $("mode").textContent = "正在翻译整句…";
    hideTimer = setTimeout(close, 10000);
    translate(current.text);
  } else {
    $("mode").textContent = "拖动选择词语或句子";
  }
}

async function refresh() {
  const [text, mode] = await Promise.all([invoke("current_text"), invoke("current_overlay_mode")]);
  if (text) applyText(text);
  applyMode(mode);
  displaySettings();
}

listen("text-event", ({ payload }) => applyText(payload));
listen("overlay-mode", ({ payload }) => applyMode(payload));
window.addEventListener("focus", () => refresh().catch((error) => { $("result").textContent = String(error); }));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh().catch((error) => { $("result").textContent = String(error); }); });
refresh().catch((error) => { $("result").textContent = String(error); });

async function translate(text) {
  selected = text?.trim();
  if (!selected) return $("result").textContent = "还没有收到可翻译的游戏文本。";

  let settings = {};
  try { settings = JSON.parse(localStorage.getItem("translation-settings")) || {}; }
  catch (_) {}
  if (!settings.model) return $("result").textContent = "请先在主窗口填写翻译模型。";

  $("result").textContent = "翻译中…";
  try {
    translated = await invoke("translate_text", {
      text: selected,
      baseUrl: settings["base-url"],
      model: settings.model,
      target: settings.target || "zh-CN"
    });
    $("result").textContent = translated;
    $("save").disabled = false;
  } catch (error) {
    $("result").textContent = String(error);
  }
}

async function lookup(text) {
  try {
    selected = text.trim();
    const entry = JSON.parse(await invoke("lookup_word", { word: selected }));
    if (!entry) return translate(selected);
    translated = entry.translation;
    $("result").textContent = `${entry.word}${entry.phonetic ? ` /${entry.phonetic}/` : ""}\n${entry.translation}`;
    $("save").disabled = false;
  } catch (error) {
    $("result").textContent = String(error);
  }
}

$("source").addEventListener("mouseup", () => {
  const text = getSelection().toString().trim();
  if (text) (/^[A-Za-z'-]+$/.test(text) ? lookup(text) : translate(text));
});
$("translate").onclick = () => translate(selected || current.text);
$("save").onclick = async () => {
  await invoke("save_item", {
    kind: selected === current.text ? "sentence" : "word",
    source: selected, translation: translated,
    context: current.text || "", game: current.game || ""
  });
  $("save").textContent = "已收藏";
};
const close = () => invoke("close_overlay");
$("close").onclick = close;
document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
