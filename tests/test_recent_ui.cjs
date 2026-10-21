const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "dist/index.html"), "utf8");
const code = fs.readFileSync(path.join(root, "dist/app.js"), "utf8");
const elements = new Map(),
  requests = [];
function node() {
  return {
    value: "",
    disabled: false,
    hidden: false,
    textContent: "",
    children: [],
    style: {},
    listeners: {},
    classList: { toggle() {}, add() {} },
    addEventListener(name, fn) {
      this.listeners[name] = fn;
    },
    append(...items) {
      this.children.push(...items);
    },
    replaceChildren(...items) {
      this.children = items;
    },
  };
}
function get(id) {
  assert.ok(html.includes(`id="${id}"`), id);
  if (!elements.has(id)) elements.set(id, node());
  return elements.get(id);
}
const context = vm.createContext({
  I18n: require("./i18n_stub.cjs")(),
  LivePanel:{subscribe(){}},
  console,
  URLSearchParams,
  Intl,
  AbortSignal,
  queueMicrotask,
  Toasts: { show() {}, problem() {} },
  MeterBoard: { update() {}, setConnected() {} },
  setTimeout() {},
  clearTimeout() {},
  setInterval() {},
  document: {
    getElementById: get,
    createElement: node,
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    activeElement: null,
  },
  fetch(url) {
    return new Promise((resolve, reject) =>
      requests.push({ url, resolve, reject }),
    );
  },
});
const state = {
  session: { phase: "active" },
  mode: "defer",
  pending: 0,
  pending_bytes: 0,
  counts: { local: 181 },
  downloads: { count: 181, bytes: 18100, since: "2026-10-21T00:00:00Z" },
  counters: {},
  events: [],
  nonce: "test",
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
const respond = (request, value) =>
  request.resolve({ ok: true, json: async () => value });
function rows(count, newest = false) {
  return Array.from({ length: count }, (_, i) => ({
    path: newest && i === 0 ? "newest.bin" : `file-${newest ? i - 1 : i}.bin`,
    name: newest && i === 0 ? "newest.bin" : `file-${newest ? i - 1 : i}.bin`,
    status: "local",
    size: 100,
    validated: 100,
    downloaded_at: "2026-10-21T10:03:00+00:00",
    downloaded_via_proxy: true,
  }));
}
async function responseList(total, count, newest = false) {
  respond(requests.shift(), state);
  await tick();
  const request = requests.shift();
  assert.equal(
    new URLSearchParams(request.url.split("?")[1]).get("offset"),
    "0",
  );
  respond(request, { total, offset: 0, rows: rows(count, newest) });
  await tick();
  return new URLSearchParams(request.url.split("?")[1]);
}
async function main() {
  vm.runInContext(fs.readFileSync(path.join(root, 'dist/list-motion.js'), 'utf8'), context);
  vm.runInContext(code, context);
  await responseList(0, 0);
  vm.runInContext("setFilter('downloaded')", context);
  let query = await responseList(181, 60);
  assert.equal(query.get("limit"), "60");
  assert.equal(get("page-controls").hidden, true);
  assert.equal(get("load-more").hidden, false);
  assert.equal(get("files").children.length, 60);
  assert.equal(get("downloaded-heading").textContent, "Скачано");
  const time = get("files").children[0].children.at(-1).children[0];
  assert.equal(time.dateTime, "2026-10-21T10:03:00+00:00");
  assert.ok(!time.children[0].textContent.includes("Invalid"));
  get("load-more").listeners.click();
  assert.equal(get("load-more").disabled, true);
  query = await responseList(181, 120);
  assert.equal(query.get("limit"), "120");
  assert.equal(get("files").children.length, 120);
  // A new completion retains the entire previously expanded prefix.
  vm.runInContext("refresh()", context);
  await responseList(182, 120, true);
  query = await responseList(182, 121, true);
  assert.equal(query.get("limit"), "121");
  assert.equal(get("files").children.length, 121);
  assert.equal(
    get("files").children[0].children[0].children[0].children[1].children[0]
      .textContent,
    "newest.bin",
  );
  assert.equal(
    get("files").children.at(-1).children[0].children[0].children[1].children[0]
      .textContent,
    "file-119.bin",
  );
  get("load-more").listeners.click();
  await responseList(182, 181, true);
  get("load-more").listeners.click();
  await responseList(182, 182, true);
  assert.equal(get("load-more").hidden, true);
  vm.runInContext("setFilter('pending')", context);
  await responseList(0, 0);
  assert.equal(get("page-controls").hidden, false);
  assert.equal(get("load-more").hidden, true);
  console.log(
    "Recent downloads: newest first, completion time, expansion retained on insert, paging unchanged elsewhere.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
