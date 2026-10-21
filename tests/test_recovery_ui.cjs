const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "dist/recovery.html"), "utf8");
const elements = new Map(),
  requests = [],
  notices = [],
  problems = [];
function element() {
  return {
    value: "",
    listeners: {},
    classList: { toggle() {} },
    replaceChildren() {},
    close() {},
    addEventListener(name, fn) {
      this.listeners[name] = fn;
    },
  };
}
function get(id) {
  assert.ok(html.includes(`id="${id}"`), `Removed element still used: ${id}`);
  if (!elements.has(id)) elements.set(id, element());
  return elements.get(id);
}
const state = {
  nonce: "local-test",
  network: { empty_downloads: 0, cancelled: 0 },
  recovery: {
    counts: {},
    paused: false,
    verified: 0,
    verified_bytes: 0,
    speed: 0,
    workers: 4,
  },
};
const context = vm.createContext({
  console,
  Intl,
  URLSearchParams,
  AbortSignal,
  queueMicrotask,
  location: { search: "" },
  setInterval() {},
  window: {
    open() {
      return null;
    },
  },
  Toasts: {
    show(text, options) {
      notices.push({ text, ...options });
    },
    problem(key, text) {
      problems.push({ key, text });
    },
  },
  ListMotion: { render() {} },
  document: { getElementById: get, createElement: element },
  fetch(url, options) {
    return new Promise((resolve, reject) =>
      requests.push({ url, options, resolve, reject }),
    );
  },
});
const tick = () => new Promise((resolve) => setImmediate(resolve));
function respond(value, ok = true) {
  requests.shift().resolve({ ok, json: async () => value });
}
async function refreshed() {
  respond(state);
  await tick();
  respond({ rows: [], total: 0, offset: 0 });
  await tick();
}
async function main() {
  vm.runInContext(
    fs.readFileSync(path.join(root, "dist/recovery.js"), "utf8"),
    context,
  );
  await refreshed();
  assert.equal(notices.length, 0, "Polling does not produce success notices");
  let pending = vm.runInContext("run('batch')", context);
  assert.equal(notices.length, 0, "No success before server acceptance");
  respond({ queued: 0 });
  await tick();
  await refreshed();
  await pending;
  assert.equal(notices.pop().text, "Нет новых файлов для добавления.");
  pending = vm.runInContext("run('control', {action:'pause'})", context);
  respond({});
  await tick();
  await refreshed();
  await pending;
  assert.equal(notices.pop().text, "Прямые загрузки приостановлены.");
  pending = vm.runInContext("run('enqueue', {file:'file.pdf'})", context);
  respond({ error: "Файл недоступен" }, false);
  await pending;
  assert.deepEqual(notices.pop(), { text: "Файл недоступен", type: "error" });
  assert.equal(requests.length, 0, "Failed action does not report success");
  pending = get("url-form").listeners.submit({ preventDefault() {} });
  respond({ error: "Некорректная ссылка" }, false);
  await pending;
  assert.equal(get("url-error").textContent, "Некорректная ссылка");
  assert.equal(
    get("url-error").hidden,
    false,
    "Form validation stays next to its input",
  );
  assert.equal(notices.length, 0);
  pending = vm.runInContext("refresh()", context);
  requests.shift().reject(Error("offline"));
  await pending;
  assert.equal(problems.at(-1).key, "connection");
  assert.equal(get("batch").disabled, true);
  pending = vm.runInContext("refresh()", context);
  await refreshed();
  await pending;
  assert.equal(
    problems.at(-1).text,
    "",
    "Successful refresh resolves the connection notice",
  );
  assert.equal(get("batch").disabled, false);
  console.log(
    "Recovery UI: accepted actions, empty batch, failed actions, inline form validation, offline and reconnect passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
