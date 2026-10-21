const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "dist/index.html"), "utf8");
const code = fs.readFileSync(path.join(root, "dist/app.js"), "utf8");
const elements = new Map();
const requests = [];
const rendered = [];
function element(id) {
  assert.ok(html.includes(`id="${id}"`), `Removed element still used: ${id}`);
  if (!elements.has(id))
    elements.set(id, {
      value: "",
      disabled: false,
      hidden: false,
      textContent: "",
      className: "",
      children: [],
      classList: { toggle() {} },
      listeners: {},
      addEventListener(name, fn) {
        this.listeners[name] = fn;
      },
      replaceChildren() {},
      showModal() {
        this.open = true;
      },
      close() {
        this.open = false;
      },
    });
  return elements.get(id);
}
const context = vm.createContext({
  I18n: require("./i18n_stub.cjs")(),
  LivePanel: { subscribe() {} },
  Thumbnails: { decorate() {}, sync() {}, configure() {} },
  console,
  URLSearchParams,
  Intl,
  AbortSignal,
  queueMicrotask,
  setTimeout() {
    return 0;
  },
  clearTimeout() {},
  setInterval() {
    return 0;
  },
  document: {
    getElementById: element,
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    activeElement: null,
  },
  fetch(url, options) {
    return new Promise((resolve, reject) =>
      requests.push({ url, options, resolve, reject }),
    );
  },
  rendered,
  Toasts: { show() {}, problem() {} },
  MeterBoard: { update() {}, setConnected() {} },
});
const state = (phase) => ({
  session: { phase },
  configured: true,
  certificate_approved: true,
  certificate_thumbprint: "0123456789ABCDEF0123456789ABCDEF01234567",
  mode: "defer",
  pending: 1,
  pending_bytes: 100,
  counts: { local: 2 },
  downloads: { count: 1, bytes: 10, since: "2026-01-01T00:00:00Z" },
  counters: {},
  root: "disk",
  events: [],
  nonce: "local-test",
});
const tick = () => new Promise((resolve) => setImmediate(resolve));
function respond(request, value) {
  request.resolve({ ok: true, json: async () => value });
}
async function main() {
  vm.runInContext(
    fs.readFileSync(path.join(root, "dist/list-motion.js"), "utf8"),
    context,
  );
  vm.runInContext(code, context);
  vm.runInContext("renderRows = data => rendered.push(data.rows);", context);
  vm.runInContext("setFilter('errors')", context);
  respond(requests.shift(), state("idle"));
  await tick();
  const oldFiles = requests.shift();
  assert.equal(
    new URLSearchParams(oldFiles.url.split("?")[1]).get("status"),
    "pending",
  );
  respond(oldFiles, { offset: 0, total: 1, rows: ["old-pending-result"] });
  await tick();
  assert.equal(rendered.length, 0, "Old filter result must be ignored");
  respond(requests.shift(), state("idle"));
  await tick();
  const freshFiles = requests.shift();
  assert.equal(
    new URLSearchParams(freshFiles.url.split("?")[1]).get("status"),
    "errors",
  );
  respond(freshFiles, { offset: 0, total: 1, rows: ["current-error-result"] });
  await tick();
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0][0], "current-error-result");
  vm.runInContext("refresh()", context);
  requests.shift().reject(new Error("offline"));
  await tick();
  assert.equal(element("session-title").textContent, "Нет связи с панелью");
  for (const id of ["proxy-toggle", "mode"])
    assert.equal(element(id).disabled, true);
  vm.runInContext("refresh()", context);
  respond(requests.shift(), state("active"));
  await tick();
  respond(requests.shift(), { offset: 0, total: 0, rows: [] });
  await tick();
  assert.equal(element("session-title").textContent, "Прокси включён");
  assert.equal(element("proxy-toggle").disabled, false);
  assert.equal(element("proxy-toggle").ariaChecked, "true");
  assert.equal(element("mode").disabled, false);
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:false},tls:{client:{ok:true},upstream:{ok:true}},mode:'defer'})",
    context,
  );
  assert.equal(
    element("tls-warning").hidden,
    true,
    "A verified client TLS connection must not be shown as disconnected",
  );
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:false},tls:{client:{ok:false}},mode:'defer'})",
    context,
  );
  assert.equal(element("tls-warning").hidden, false);
  assert.equal(element("repair-ca").hidden, false);
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:true,ca_trusted:false},mode:'defer'})",
    context,
  );
  assert.equal(
    element("tls-warning").hidden,
    true,
    "Client-scoped trust must not require a Windows store entry",
  );
  assert.equal(element("repair-ca").hidden, true);
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:true},tls:{client:{ok:false}},mode:'defer'})",
    context,
  );
  assert.equal(element("restart-client").hidden, false);
  assert.equal(element("repair-ca").hidden, true);
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:false},mode:'defer'})",
    context,
  );
  assert.equal(element("tls-warning").hidden, false);
  assert.equal(
    element("tls-message").textContent,
    "Файл сертификата Диска недоступен или изменён.",
  );
  for (const id of ["start", "stop", "settings", "rescan", "session-led"])
    assert.ok(!html.includes(`id="${id}"`));
  const toggle = element("proxy-toggle");
  function show(value) {
    context.nextState = value;
    vm.runInContext(
      "snapshot=nextState; connected=true; sessionView(snapshot)",
      context,
    );
  }
  async function finishAction(phase) {
    respond(requests.shift(), { ok: true });
    await tick();
    respond(requests.shift(), state(phase));
    await tick();
    respond(requests.shift(), { offset: 0, total: 0, rows: [] });
    await tick();
  }
  show(state("stopped"));
  assert.equal(toggle.ariaChecked, "false");
  const starting = toggle.listeners.click();
  assert.equal(requests[0].url, "/api/start");
  assert.deepEqual(JSON.parse(requests[0].options.body), {});
  assert.equal(toggle.disabled, true);
  assert.equal(toggle.ariaChecked, "true");
  assert.equal(toggle.ariaBusy, "true");
  await toggle.listeners.click();
  assert.equal(
    requests.length,
    1,
    "Repeated clicks cannot send duplicate commands",
  );
  vm.runInContext("sessionView(snapshot)", context);
  assert.equal(
    toggle.ariaChecked,
    "true",
    "A stale background snapshot cannot reverse pending intent",
  );
  await finishAction("starting");
  await starting;
  assert.equal(toggle.disabled, false, "Starting can still be stopped");
  const stopping = toggle.listeners.click();
  assert.equal(requests[0].url, "/api/stop");
  assert.equal(toggle.ariaChecked, "false");
  await finishAction("stopping");
  await stopping;
  assert.equal(
    toggle.disabled,
    true,
    "Cannot start before restoration finishes",
  );
  await toggle.listeners.click();
  assert.equal(requests.length, 0);
  show(state("stopped"));
  assert.equal(toggle.disabled, false);
  assert.equal(toggle.ariaChecked, "false");
  show(state("active"));
  const failed = toggle.listeners.click();
  requests.shift().reject(new Error("failed stop"));
  await failed;
  assert.equal(
    toggle.ariaChecked,
    "true",
    "A failed command restores confirmed state",
  );
  assert.equal(toggle.disabled, false);
  show(state("cleanup_required"));
  assert.equal(toggle.ariaChecked, "true");
  const recovery = toggle.listeners.click();
  assert.equal(requests[0].url, "/api/recover");
  await finishAction("stopped");
  await recovery;
  assert.equal(toggle.ariaChecked, "false");
  show({ ...state("idle"), configured: false });
  await toggle.listeners.click();
  assert.equal(
    element("setup-dialog").open,
    true,
    "First use remains configurable",
  );
  assert.equal(requests.length, 0);
  element("setup-cancel").listeners.click();
  show({ ...state("idle"), certificate_approved: false });
  await toggle.listeners.click();
  assert.equal(element("consent-dialog").open, true);
  assert.equal(
    requests.length,
    0,
    "An unapproved certificate cannot start automatically",
  );
  await element("consent-start").listeners.click();
  assert.equal(requests.length, 0, "Unchecked consent cannot submit");
  element("consent-checkbox").checked = true;
  element("consent-checkbox").listeners.change();
  const consent = element("consent-start").listeners.click();
  assert.equal(
    JSON.parse(requests[0].options.body).accepted_thumbprint,
    state("idle").certificate_thumbprint,
  );
  await finishAction("active");
  await consent;
  assert.equal(element("consent-dialog").open, false);
  assert.equal(toggle.ariaChecked, "true");
  console.log(
    "UI: switch start/stop/recovery, pending and offline states, duplicate guards, first setup, certificate consent and stale results passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
