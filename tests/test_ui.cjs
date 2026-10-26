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
const problems = new Map();
const thumbnailListeners = [];
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
      setAttribute(name, value) {
        this[name] = value;
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
  Thumbnails: {
    enabled: true,
    decorate() {},
    sync() {},
    configure() {},
    setEnabled(value) {
      this.enabled = value;
      thumbnailListeners.forEach((listener) => listener(value));
    },
    onChange(listener) {
      thumbnailListeners.push(listener);
    },
  },
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
  Toasts: {
    show() {},
    problem(key, message, options = {}) {
      problems.set(key, { message, ...options });
    },
  },
  MeterBoard: { update() {}, setConnected() {} },
});
const state = (phase) => ({
  session: { phase },
  configured: true,
  certificate_approved: true,
  certificate_thumbprint: "0123456789ABCDEF0123456789ABCDEF01234567",
  certificate_scope: "current_user",
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
  assert.equal(element("toggle-thumbnails").ariaPressed, "true");
  const requestCount = requests.length;
  element("toggle-thumbnails").listeners.click();
  assert.equal(element("toggle-thumbnails").ariaPressed, "false");
  assert.equal(element("toggle-thumbnails").title, "Показывать превью файлов");
  element("toggle-thumbnails").listeners.click();
  assert.equal(element("toggle-thumbnails").ariaPressed, "true");
  assert.equal(
    requests.length,
    requestCount,
    "Preview toggle does not change the proxy session",
  );
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
    problems.get("session").message,
    "Сертификат больше не находится в доверенных Windows.",
    "An old successful handshake cannot hide missing Windows trust",
  );
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:false},tls:{client:{ok:false}},mode:'defer'})",
    context,
  );
  assert.equal(problems.get("session").action.label, "Восстановить доверие");
  const repairing = problems.get("session").action.onClick();
  assert.equal(requests[0].url, "/api/repair-ca");
  respond(requests.shift(), { ok: true });
  await tick();
  respond(requests.shift(), state("active"));
  await tick();
  respond(requests.shift(), { offset: 0, total: 0, rows: [] });
  await repairing;
  assert.equal(problems.get("session").message, "");
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:true,client_attached:false,client_connection:'limited'},tls:{client:{ok:true}},mode:'defer'})",
    context,
  );
  assert.equal(problems.get("session").action.label, "Перезапустить Диск");
  assert.equal(
    element("session-title").textContent,
    "Диск не подключён к прокси",
  );
  const restarting = problems.get("session").action.onClick();
  assert.equal(requests[0].url, "/api/restart-client");
  requests.shift().resolve({
    ok: false,
    json: async () => ({ error: "Restart failed" }),
  });
  await assert.rejects(restarting, /Restart failed/);
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:true,client_attached:true,client_connected_at:200},tls:{client:{ok:false,at:100}},mode:'defer'})",
    context,
  );
  assert.equal(
    problems.get("session").message,
    "",
    "A reconnected client ignores failures from an older connection",
  );
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:true,ca_trusted:false},mode:'defer'})",
    context,
  );
  assert.equal(
    problems.get("session").message,
    "",
    "Client-scoped trust must not require a Windows store entry",
  );
  assert.equal(problems.get("session").action, undefined);
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:true},tls:{client:{ok:false}},mode:'defer'})",
    context,
  );
  assert.equal(problems.get("session").action.label, "Перезапустить Диск");
  assert.equal(
    problems.get("session").message,
    "Диск отклонил TLS-соединение. Причина — в журнале.",
  );
  vm.runInContext(
    "sessionView({session:{phase:'active',certificate_scope:'client',certificate_ready:false},mode:'defer'})",
    context,
  );
  assert.equal(
    problems.get("session").message,
    "Файл сертификата Диска недоступен или изменён.",
  );
  assert.equal(problems.get("session").action, undefined);
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:true},tls:{upstream:{ok:false}},mode:'defer'})",
    context,
  );
  assert.equal(
    problems.get("session").message,
    "Ошибка TLS между прокси и Яндексом. Причина — в журнале.",
  );
  assert.equal(problems.get("session").action, undefined);
  assert.equal(
    problems.get("session").delay,
    10000,
    "Transient upstream TLS waits for recovery",
  );
  assert.equal(
    problems.get("session").cooldown,
    300000,
    "Flapping upstream TLS cannot flood notifications",
  );
  vm.runInContext(
    "sessionView({session:{phase:'active',ca_trusted:true},tls:{upstream:{ok:false,error:'Certificate verify failed'}},mode:'defer'})",
    context,
  );
  assert.equal(
    problems.get("session").delay,
    0,
    "Certificate failures are immediate",
  );
  assert.equal(
    problems.get("session").cooldown,
    0,
    "Certificate failures bypass throttling",
  );
  vm.runInContext(
    "sessionView({session:{phase:'stopped',error_detail:'Cleanup failed'},mode:'defer'})",
    context,
  );
  assert.equal(problems.get("session").message, "Cleanup failed");
  for (const id of [
    "start",
    "stop",
    "settings",
    "rescan",
    "session-led",
    "tls-warning",
    "tls-message",
    "repair-ca",
    "restart-client",
  ])
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
  assert.equal(
    JSON.parse(requests[0].options.body).accepted_certificate_scope,
    "current_user",
  );
  await finishAction("active");
  await consent;
  assert.equal(element("consent-dialog").open, false);
  assert.equal(toggle.ariaChecked, "true");
  show({ ...state("idle"), configured: false });
  await toggle.listeners.click();
  element("setup-root").value = "selected-disk";
  element("setup-client").value = "YandexDisk4.exe";
  const submit = () =>
    element("setup-form").listeners.submit({ preventDefault() {} });
  const browsing = element("browse-root").listeners.click();
  assert.equal(
    element("setup-save").disabled,
    true,
    "Cannot save while the picker is open",
  );
  await submit();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/browse");
  respond(requests.shift(), { path: "picked-disk" });
  await browsing;
  assert.equal(element("setup-root").value, "picked-disk");
  assert.equal(element("setup-save").disabled, false);
  const saving = submit();
  assert.equal(requests[0].url, "/api/setup");
  assert.equal(element("setup-save").textContent, "Сохранение…");
  assert.equal(element("setup-save").ariaBusy, "true");
  assert.equal(element("setup-progress").hidden, false);
  for (const id of [
    "setup-root",
    "setup-client",
    "browse-root",
    "browse-client",
    "setup-save",
    "setup-cancel",
  ])
    assert.equal(element(id).disabled, true, id);
  await submit();
  await element("browse-client").listeners.click();
  assert.equal(
    requests.length,
    1,
    "Pending save cannot submit twice or open a picker",
  );
  element("setup-cancel").listeners.click();
  assert.equal(element("setup-dialog").open, true);
  let escapePrevented = false;
  element("setup-dialog").listeners.cancel({
    preventDefault() {
      escapePrevented = true;
    },
  });
  assert.equal(escapePrevented, true, "Escape cannot hide an unfinished save");
  respond(requests.shift(), { ok: true });
  await tick();
  assert.equal(
    element("setup-dialog").open,
    false,
    "Close on acknowledgement, before the scan finishes",
  );
  respond(requests.shift(), {
    ...state("idle"),
    inventory: { scanning: true, updated_at: null },
  });
  await tick();
  respond(requests.shift(), { offset: 0, total: 0, rows: [] });
  await saving;
  assert.equal(element("inventory-status").hidden, false);
  assert.equal(element("setup-save").textContent, "Сохранить");
  assert.equal(element("setup-save").disabled, false);
  assert.equal(element("setup-progress").hidden, true);
  show({ ...state("idle"), inventory: { scanning: false, updated_at: 123 } });
  assert.equal(element("inventory-status").hidden, true);
  show({ ...state("idle"), inventory: { scanning: true, updated_at: 123 } });
  assert.equal(
    element("inventory-status").hidden,
    true,
    "Routine scans do not flash the initial scan indicator",
  );
  vm.runInContext("openSetup()", context);
  const failedSave = submit();
  requests.shift().resolve({
    ok: false,
    json: async () => ({ error: "Папка синхронизации не найдена" }),
  });
  await failedSave;
  assert.equal(
    element("setup-dialog").open,
    true,
    "Validation errors keep the form open",
  );
  assert.equal(
    element("setup-save").disabled,
    false,
    "A failed save can be corrected and retried",
  );
  assert.equal(element("setup-form").ariaBusy, "false");
  element("setup-cancel").listeners.click();
  show({ ...state("active"), counts: { deferred: 2 } });
  let resetToast;
  context.Toasts.show = (text, options) => {
    if (options?.action) resetToast = options;
  };
  const reset = element("reset-errors").listeners.click();
  assert.equal(requests[0].url, "/api/statistics/reset");
  assert.equal(JSON.parse(requests[0].options.body).counter, "http500");
  assert.equal(element("reset-errors").disabled, true);
  await element("reset-errors").listeners.click();
  assert.equal(requests.length, 1);
  respond(requests.shift(), { ok: true, revision: 7, context: "root" });
  await tick();
  respond(requests.shift(), {
    ...state("active"),
    counts: { deferred: 2 },
    display_counters: { http500: 0, network_bytes: 0 },
  });
  await reset;
  assert.equal(element("reset-errors").disabled, false);
  const undo = resetToast.action.onClick();
  assert.equal(requests[0].url, "/api/statistics/undo");
  assert.equal(JSON.parse(requests[0].options.body).revision, 7);
  respond(requests.shift(), { ok: true });
  await tick();
  respond(requests.shift(), state("active"));
  await undo;
  show(state("stopped"));
  assert.equal(element("reset-deferred").disabled, true);
  assert.equal(element("reset-network").disabled, false);
  console.log(
    "UI: switch, consent, stale results, setup busy feedback, picker/save guards, async scan status and validation retry passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
