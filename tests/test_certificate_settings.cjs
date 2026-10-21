const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("dist/settings.html", "utf8");
const elements = new Map();
const requests = [];
let refresh;
function element(id) {
  assert.ok(html.includes(`id="${id}"`), `Missing settings control: ${id}`);
  if (!elements.has(id))
    elements.set(id, {
      listeners: {},
      addEventListener(name, fn) {
        this.listeners[name] = fn;
      },
    });
  return elements.get(id);
}
vm.runInNewContext(fs.readFileSync("dist/settings.js", "utf8"), {
  document: { getElementById: element },
  I18n: { t: (s) => s, locale: "en-GB", onChange() {} },
  LivePanel: {
    subscribe(fn, topics) {
      refresh = fn;
      assert.equal(topics.join(), "state");
    },
  },
  fetch(url, options) {
    return new Promise((resolve, reject) =>
      requests.push({ url, options, resolve, reject }),
    );
  },
});
const state = {
  nonce: "panel-nonce",
  session: { phase: "idle" },
  root: "Disk",
  client: "Disk.exe",
};
const certificate = {
  automatic: true,
  approved: true,
  trusted: false,
  scope: "local_machine",
  thumbprint: "A".repeat(40),
  expires: "2027-01-01T00:00:00Z",
};
async function tick() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
}
async function answer() {
  for (const req of requests.splice(0))
    req.resolve({
      ok: true,
      json: async () => (req.url === "/api/state" ? state : certificate),
    });
  await tick();
}
(async () => {
  await answer();
  assert.equal(element("automatic").checked, true);
  assert.equal(element("install").disabled, false);
  assert.equal(element("remove").disabled, true);
  element("install").listeners.click();
  element("install").listeners.click();
  assert.equal(requests.length, 1, "Duplicate actions are blocked");
  const req = requests.shift();
  assert.equal(req.options.headers["X-Panel-Nonce"], "panel-nonce");
  assert.equal(JSON.parse(req.options.body).action, "install");
  req.resolve({
    ok: false,
    json: async () => ({ error: "Windows permission request was cancelled" }),
  });
  await tick();
  assert.equal(element("certificate-error").hidden, false);
  assert.match(element("certificate-error").textContent, /cancelled/);
  state.session.phase = "active";
  refresh();
  await answer();
  assert.equal(element("scope").disabled, true);
  assert.equal(element("install").disabled, true);
  state.session.phase = "stopped";
  certificate.job = { busy: true };
  refresh();
  await answer();
  assert.equal(element("automatic").disabled, true);
  certificate.job = null;
  refresh();
  for (const req of requests.splice(0)) req.reject(Error("offline"));
  await tick();
  assert.equal(element("install").disabled, true);
  assert.equal(element("scope").disabled, true);
  console.log(
    "Certificate settings: scope, consent, action nonce, duplicate blocking, failure visibility and offline controls passed.",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
