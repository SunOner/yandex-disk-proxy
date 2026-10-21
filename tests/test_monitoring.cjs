const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const elements = new Map(),
  requests = [],
  locale = [];
function element() {
  const classes = new Set();
  return {
    children: [],
    attributes: {},
    listeners: {},
    style: {},
    textContent: "",
    value: "",
    classList: {
      add: (n) => classes.add(n),
      toggle(n, v) {
        v ? classes.add(n) : classes.delete(n);
      },
      contains: (n) => classes.has(n),
    },
    append(...items) {
      this.children.push(...items);
    },
    setAttribute(k, v) {
      this.attributes[k] = String(v);
    },
    getAttribute(k) {
      return this.attributes[k];
    },
    addEventListener(k, fn) {
      this.listeners[k] = fn;
    },
    getBoundingClientRect() {
      return { left: 0, width: 920 };
    },
  };
}
const get = (id) => {
  if (!elements.has(id)) elements.set(id, element());
  return elements.get(id);
};
const i18n = require("./i18n_stub.cjs")();
i18n.onChange = (fn) => locale.push(fn);
const context = vm.createContext({
  I18n: i18n,
  console,
  Intl,
  URLSearchParams,
  AbortSignal,
  queueMicrotask,
  document: {
    getElementById: get,
    createElement: element,
    createElementNS: element,
  },
  LivePanel: { subscribe() {} },
  Toasts: { problem() {} },
  fetch(url) {
    return new Promise((resolve, reject) =>
      requests.push({ url, resolve, reject }),
    );
  },
});
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../dist/monitoring.js"), "utf8"),
  context,
);
const charts = vm.runInContext("MonitoringCharts", context);
assert.equal(
  charts.value({ seconds: 5, received_bytes: 100 }, "received_bytes", "rate"),
  20,
);
assert.equal(
  charts.value({ seconds: 0, received_bytes: 100 }, "received_bytes", "rate"),
  null,
);
assert.equal(
  charts.value({ missing: true, requests: 9 }, "requests", "count"),
  null,
);
assert.equal(
  charts.value(
    { seconds: 0, native_files: 2, direct_files: 0 },
    "native_files",
    "downloads",
  ),
  2,
);
assert.equal(
  charts.value({ pending_files: null }, "pending_files", "gauge"),
  null,
);
assert.equal(
  charts.value({ duration_ms: 100, timed_requests: 4 }, "average", "duration"),
  25,
);
assert.equal(
  charts.value({ duration_ms: 0, timed_requests: 0 }, "average", "duration"),
  null,
);
assert.equal(charts.maximum([0, null, 2.1]), 5);
assert.equal(
  charts.path([1, null, 2], 0, 0, 100, 50, 2),
  "M0.00 25.00 M100.00 0.00",
  "Missing measurements break lines",
);
const data = {
  period: "24h",
  since: 1000,
  saved_at: 1020,
  step: 10,
  totals: {
    native_files: 10,
    native_bytes: 1024,
    direct_files: 2,
    direct_bytes: 100,
    received_bytes: 10000,
    sent_bytes: 100,
    http500_all: 3,
    http_errors: 4,
    duration_ms: 100,
    timed_requests: 4,
  },
  current: { pending_files: 5, pending_bytes: 5000 },
  storage: {
    bytes: 8192,
    max_database_bytes: 16777216,
    buckets: 5,
    max_buckets: 8299,
  },
  points: [
    {
      at: 1000,
      seconds: 5,
      received_bytes: 100,
      sent_bytes: 10,
      native_files: 1,
      direct_files: 0,
      requests: 2,
      http_errors: 0,
      http500_all: 0,
      tls_errors: 0,
      pending_files: 5,
      deferred_files: 1,
      duration_ms: 200,
      timed_requests: 2,
    },
    { at: 1010, missing: true },
    {
      at: 1020,
      seconds: 5,
      received_bytes: 200,
      sent_bytes: 30,
      native_files: 0,
      direct_files: 1,
      requests: 1,
      http_errors: 1,
      http500_all: 1,
      tls_errors: 0,
      pending_files: 4,
      deferred_files: 1,
      duration_ms: 200,
      timed_requests: 1,
    },
  ],
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
function respond(value = data) {
  requests.shift().resolve({ ok: true, json: async () => value });
}
async function main() {
  assert.equal(get("charts").children.length, 6);
  respond();
  await tick();
  assert.equal(get("native-files").textContent, "10");
  const first = get("charts").children[0],
    plot = first.children[2],
    line = plot.children.find((node) => node.attributes.class === "chart-line");
  const initial = line.attributes.d;
  assert.ok(initial.includes("M"));
  plot.listeners.focus();
  assert.ok(first.children[3].textContent.includes("40"));
  plot.listeners.keydown({ key: "ArrowLeft", preventDefault() {} });
  assert.ok(first.children[3].textContent.includes("—"));
  const period = get("period");
  period.value = "7d";
  period.listeners.change();
  period.value = "1h";
  period.listeners.change();
  respond({ ...data, period: "7d" });
  await tick();
  assert.ok(
    requests[0].url.includes("period=1h"),
    "Old period result triggers a current fetch",
  );
  respond({
    ...data,
    period: "1h",
    points: data.points.map((p) => ({
      ...p,
      received_bytes: p.received_bytes * 2,
    })),
  });
  await tick();
  assert.equal(first, get("charts").children[0]);
  assert.equal(
    line,
    plot.children.find((node) => node.attributes.class === "chart-line"),
    "Live updates retain the chart DOM",
  );
  locale.forEach((fn) => fn());
  assert.equal(
    requests.length,
    0,
    "Changing language does not refetch monitoring",
  );
  period.listeners.change();
  requests.shift().reject(Error("offline"));
  await tick();
  assert.ok(get("connection").classList.contains("offline"));
  assert.ok(line.attributes.d, "Offline charts remain visible");
  period.listeners.change();
  respond({ ...data, period: "1h" });
  await tick();
  assert.equal(get("connection").classList.contains("offline"), false);
  console.log(
    "Monitoring: rates, averages, imported history, gaps, six charts, stable SVG, keyboard inspection, stale periods, localization and offline recovery passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
