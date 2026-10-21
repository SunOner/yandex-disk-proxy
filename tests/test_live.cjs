const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const code = fs.readFileSync(path.join(__dirname, "../dist/live.js"), "utf8");
let now = 0,
  next = 0,
  paused = false;
const timers = new Map(),
  sources = [],
  requests = [],
  documentEvents = {},
  windowEvents = {};
class Source {
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.events = {};
    sources.push(this);
  }
  addEventListener(name, fn) {
    this.events[name] = fn;
  }
  close() {
    this.readyState = 2;
  }
  update(topics) {
    this.events.update({ data: JSON.stringify({ topics }) });
  }
}
const document = {
  hidden: false,
  addEventListener: (n, fn) => (documentEvents[n] = fn),
  removeEventListener: (n) => delete documentEvents[n],
};
const context = vm.createContext({
  document,
  window: {
    addEventListener: (n, fn) => (windowEvents[n] = fn),
    removeEventListener: (n) => delete windowEvents[n],
  },
  performance: { now: () => now },
  URLSearchParams,
  EventSource: Source,
  Math,
  setTimeout(fn, delay) {
    const id = ++next;
    timers.set(id, { fn, at: now + delay });
    return id;
  },
  clearTimeout: (id) => timers.delete(id),
});
vm.runInContext(code, context);
const subscribe = vm.runInContext("LivePanel.subscribe", context);
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function advance(ms) {
  const until = now + ms;
  while (true) {
    const due = [...timers]
      .filter(([, t]) => t.at <= until)
      .sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    now = due[1].at;
    timers.delete(due[0]);
    due[1].fn();
    await tick();
  }
  now = until;
  await tick();
}
async function main() {
  const live = subscribe(
    (topics) => requests.push([...topics]),
    ["state", "files"],
    { paused: () => paused },
  );
  assert.equal(sources.length, 1);
  await advance(10000);
  assert.equal(
    requests.length,
    0,
    "A healthy idle stream does not poll the whole panel",
  );
  sources[0].update(["events"]);
  await advance(0);
  assert.equal(requests.length, 0);
  for (let i = 0; i < 30; i++) sources[0].update(["files"]);
  sources[0].update(["state"]);
  await advance(0);
  assert.deepEqual(requests.at(-1).sort(), ["files", "state"]);
  assert.equal(requests.length, 1);
  sources[0].update(["files"]);
  await advance(349);
  assert.equal(requests.length, 1);
  await advance(1);
  assert.equal(
    requests.length,
    2,
    "Bursts are bounded to the refresh interval",
  );
  let resolve;
  live.close();
  const inflight = subscribe(
    (topics) =>
      new Promise((done) => {
        requests.push([...topics]);
        resolve = done;
      }),
    ["files"],
  );
  sources.at(-1).update(["files"]);
  await advance(0);
  const before = requests.length;
  sources.at(-1).update(["files"]);
  await advance(1000);
  assert.equal(requests.length, before, "Refreshes cannot overlap");
  resolve();
  await tick();
  await advance(0);
  assert.equal(
    requests.length,
    before + 1,
    "Changes during a refresh are not lost",
  );
  resolve();
  await tick();
  inflight.close();
  const visible = subscribe((topics) => requests.push([...topics]), ["state"], {
    paused: () => paused,
  });
  document.hidden = true;
  documentEvents.visibilitychange();
  assert.equal(sources.at(-1).readyState, 2);
  const hidden = requests.length;
  await advance(20000);
  assert.equal(requests.length, hidden, "Background tabs do not fetch");
  document.hidden = false;
  documentEvents.visibilitychange();
  await advance(0);
  assert.equal(requests.length, hidden + 1);
  paused = true;
  sources.at(-1).update(["state"]);
  await advance(1000);
  assert.equal(requests.length, hidden + 1);
  paused = false;
  visible.request();
  await advance(0);
  assert.equal(requests.length, hidden + 2);
  sources.at(-1).readyState = 0;
  sources.at(-1).events.error();
  await advance(350);
  assert.equal(
    requests.length,
    hidden + 3,
    "Stream errors check API connectivity immediately",
  );
  await advance(6000);
  assert.ok(
    requests.length >= hidden + 4,
    "A disconnected stream has a polling fallback",
  );
  windowEvents.pagehide();
  assert.equal(sources.at(-1).readyState, 2);
  const oldSources = sources.length;
  windowEvents.pageshow();
  assert.equal(
    sources.length,
    oldSources + 1,
    "Back-forward cache restores the stream",
  );
  visible.close();
  const stopped = requests.length;
  await advance(20000);
  assert.equal(requests.length, stopped);
  context.EventSource = undefined;
  const fallback = subscribe((topics) => requests.push([...topics]), ["files"]);
  await advance(5000);
  assert.equal(
    requests.length,
    stopped + 1,
    "Older browsers retain fallback updates",
  );
  fallback.close();
  console.log(
    "Live updates: quiet streams, topic filtering, coalescing, no overlaps, background/pause, reconnect, page restore and fallback passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
