const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const requests = [],
  images = [],
  revoked = [],
  observed = new Set(),
  events = {},
  windowEvents = {};
let callback,
  pump,
  clock = 100000,
  serial = 0;
class Node {
  constructor(tag = "span") {
    this.tag = tag;
    this.attrs = new Map();
    this.children = [];
    this.isConnected = true;
    this.style = {};
    this.classes = new Set();
    this.classList = { add: (x) => this.classes.add(x) };
    if (tag === "img") images.push(this);
  }
  setAttribute(k, v) {
    this.attrs.set(k, String(v));
  }
  getAttribute(k) {
    return this.attrs.get(k) ?? null;
  }
  append(node) {
    this.children.push(node);
    node.parent = this;
  }
  remove() {
    if (this.parent)
      this.parent.children = this.parent.children.filter((x) => x !== this);
    this.isConnected = false;
  }
}
const nodes = [new Node(), new Node(), new Node(), new Node()];
const container = {
  querySelectorAll: () =>
    nodes.filter((n) => n.isConnected && n.getAttribute("data-thumbnail")),
};
const document = {
  hidden: false,
  createElement: (t) => new Node(t),
  addEventListener: (k, f) => (events[k] = f),
  querySelectorAll: container.querySelectorAll,
};
const context = vm.createContext({
  document,
  window: { addEventListener: (k, f) => (windowEvents[k] = f) },
  I18n: { t: (x) => x },
  Date: { now: () => clock },
  AbortController,
  URL: {
    createObjectURL: () => "blob:" + ++serial,
    revokeObjectURL: (u) => revoked.push(u),
  },
  IntersectionObserver: class {
    constructor(f) {
      callback = f;
    }
    observe(n) {
      observed.add(n);
    }
    unobserve(n) {
      observed.delete(n);
    }
  },
  requestAnimationFrame: (f) => f(),
  setTimeout: () => 1,
  clearTimeout() {},
  setInterval: (f) => (pump = f),
  fetch: (url, options) =>
    new Promise((resolve, reject) =>
      requests.push({ url, options, resolve, reject }),
    ),
});
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../dist/thumbnails.js"), "utf8"),
  context,
);
const thumbnails = vm.runInContext("Thumbnails", context);
const state = {
  nonce: "panel-nonce",
  preview_context: "account-one",
  recovery: { credentials_seen: true },
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
const see = (node, visible = true) =>
  callback([{ target: node, isIntersecting: visible }]);
function respond(request, type = "image/jpeg", ok = true, retry = "60") {
  request.resolve({
    ok,
    headers: { get: () => retry },
    blob: async () => ({ size: 100, type }),
  });
}
async function main() {
  ["a.jpg", "b.mov", "c.heic", "file.txt"].forEach((name, i) =>
    thumbnails.decorate(nodes[i], { path: name, size: 10 }),
  );
  thumbnails.configure({ ...state, recovery: {} });
  thumbnails.sync(container);
  assert.equal(observed.size, 3);
  nodes.slice(0, 3).forEach((n) => see(n));
  assert.equal(
    requests.length,
    0,
    "No captured account session means no thumbnail traffic",
  );
  thumbnails.configure(state);
  assert.equal(requests.length, 2, "Only two requests may run at once");
  assert.equal(requests[0].url, "/api/thumbnail");
  assert.equal(requests[0].options.headers["X-Panel-Nonce"], "panel-nonce");
  assert.equal(JSON.parse(requests[0].options.body).context, "account-one");
  respond(requests.shift());
  await tick();
  images.at(-1).onload();
  assert.equal(nodes[0].children.length, 1);
  assert.equal(
    requests.length,
    2,
    "The next visible row starts when a slot is free",
  );
  respond(requests.shift());
  await tick();
  images.at(-1).onload();
  respond(requests.shift());
  await tick();
  images.at(-1).onload();
  thumbnails.sync(container);
  pump();
  assert.equal(
    requests.length,
    0,
    "Unchanged rows keep their images and do not refetch",
  );
  see(nodes[0], false);
  assert.ok(revoked.includes("blob:1"));
  assert.equal(nodes[0].children.length, 0);
  see(nodes[0]);
  respond(requests.shift(), "text/html");
  await tick();
  pump();
  assert.equal(
    requests.length,
    0,
    "Invalid responses keep the fallback icon and back off",
  );
  assert.equal(nodes[0].children.length, 0);
  clock += 61000;
  pump();
  const stale = requests.shift();
  thumbnails.configure({ ...state, preview_context: "account-two" });
  assert.equal(stale.options.signal.aborted, true);
  respond(stale);
  await tick();
  assert.equal(
    nodes[0].children.length,
    0,
    "Late images from an earlier folder/account are discarded",
  );
  thumbnails.sync(container);
  see(nodes[0]);
  assert.equal(JSON.parse(requests[0].options.body).context, "account-two");
  respond(requests.shift());
  await tick();
  images.at(-1).onload();
  assert.equal(nodes[0].children.length, 1);
  thumbnails.decorate(nodes[0], { path: "a.jpg", size: 20 });
  thumbnails.sync(container);
  see(nodes[0]);
  assert.equal(
    nodes[0].children.length,
    0,
    "A changed file identity drops its old object URL",
  );
  respond(requests.shift());
  await tick();
  const decoding = images.at(-1);
  document.hidden = true;
  events.visibilitychange();
  assert.equal(observed.size, 0);
  decoding.onload();
  assert.equal(
    nodes[0].children.length,
    0,
    "Hidden pages also release previews still decoding",
  );
  document.hidden = false;
  events.visibilitychange();
  see(nodes[0]);
  const last = requests.shift();
  windowEvents.pagehide();
  respond(last);
  await tick();
  assert.equal(nodes[0].children.length, 0);
  assert.equal(
    revoked.length,
    serial,
    "Every allocated object URL is released",
  );
  console.log(
    "Thumbnails: visible rows only, two requests, session guard, fallback/backoff, stable images, context changes and URL cleanup passed.",
  );
}
main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
