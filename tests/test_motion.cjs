const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const calls = [];
const documentEvents = {},
  heights = {};
let reduced = false,
  mutations = 0;
class Node {
  constructor(name = "BUTTON", text = null) {
    this.nodeType = text === null ? 1 : 3;
    this.nodeName = name;
    this.nodeValue = text;
    this.children = [];
    this.attrs = new Map();
    this.visualY = 0;
  }
  get childNodes() {
    return this.children;
  }
  get attributes() {
    return Array.from(this.attrs, ([name, value]) => ({ name, value }));
  }
  hasAttribute(name) {
    return this.attrs.has(name);
  }
  getAttribute(name) {
    return this.attrs.get(name) ?? null;
  }
  setAttribute(name, value) {
    this.attrs.set(name, String(value));
    mutations++;
  }
  removeAttribute(name) {
    this.attrs.delete(name);
    mutations++;
  }
  append(node) {
    this.insertBefore(node, null);
  }
  insertBefore(node, before) {
    node.remove();
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, node);
    node.parent = this;
    mutations++;
  }
  remove() {
    if (this.parent) {
      if (this.contains(context.document.activeElement))
        context.document.activeElement = null;
      this.parent.children.splice(this.parent.children.indexOf(this), 1);
      this.parent = null;
      mutations++;
    }
  }
  replaceWith(node) {
    const parent = this.parent,
      next = parent.children[parent.children.indexOf(this) + 1];
    this.remove();
    parent.insertBefore(node, next || null);
  }
  closest() {
    return container;
  }
  contains(node) {
    return node === this || this.children.some((child) => child.contains(node));
  }
  get isConnected() {
    return this === container || !!this.parent?.isConnected;
  }
  focus() {
    context.document.activeElement = this;
  }
  querySelector() {
    return null;
  }
  get height() {
    return Number(this.attrs.get("height") || 50);
  }
  getBoundingClientRect() {
    let top = -container.scrollTop;
    for (const node of container.children) {
      if (node === this) break;
      top += node.height;
    }
    top += this.visualY;
    return {
      top,
      bottom: top + this.height,
      left: 0,
      right: 300,
      width: 300,
      height: this.height,
    };
  }
  animate(frames, options) {
    let resolve, reject;
    const animation = {
      frames,
      options,
      node: this,
      cancelled: false,
      finished: new Promise((a, b) => {
        resolve = a;
        reject = b;
      }),
      cancel() {
        this.cancelled = true;
        this.node.visualY = 0;
        reject(Error("cancelled"));
      },
      finish() {
        resolve();
      },
    };
    calls.push(animation);
    return animation;
  }
}
const container = new Node("DIV");
container.scrollTop = 0;
container.scrollLeft = 0;
container.clientHeight = 150;
container.clientWidth = 300;
Object.defineProperty(container, "scrollHeight", {
  get: () => container.children.reduce((n, row) => n + row.height, 0),
});
container.scrollWidth = 300;
container.getBoundingClientRect = () => ({
  top: 0,
  bottom: 150,
  left: 0,
  right: 300,
  width: 300,
  height: 150,
});
const context = vm.createContext({
  document: {
    hidden: false,
    scrollingElement: container,
    addEventListener: (name, fn) => (documentEvents[name] = fn),
  },
  window: { innerHeight: 150, innerWidth: 300 },
  matchMedia: () => ({ matches: reduced }),
});
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../dist/list-motion.js"), "utf8"),
  context,
);
const list = vm.runInContext("ListMotion", context);
function entries(keys, version = 0) {
  return keys.map((key) => {
    const node = new Node();
    node.key = key;
    node.setAttribute("height", heights[key] || 50);
    node.append(new Node("#text", key));
    node.onclick = () => version;
    return { key, version: JSON.stringify([key, version]), node };
  });
}
function render(keys, scope = "files", version = 0) {
  calls.length = 0;
  const data = entries(keys, version);
  mutations = 0;
  list.render(container, data, scope);
  return [...calls];
}
async function finish() {
  calls.forEach((a) => a.finish());
  await new Promise((resolve) => setImmediate(resolve));
}
async function main() {
  render(["a", "b", "c", "d"]);
  await finish();
  const a = container.children[0],
    b = container.children[1],
    text = a.children[0];
  assert.equal(render(["a", "b", "c", "d"]).length, 0);
  assert.equal(mutations, 0, "Unchanged snapshots cause no DOM mutations");
  assert.equal(container.children[0], a, "The same row stays attached");
  const insert = render(["new", "a", "b", "c", "d"]);
  assert.equal(container.children[1], a);
  assert.equal(
    insert.find((x) => x.node === a).frames[0].transform,
    "translate(0px, -50px)",
  );
  assert.equal(
    insert.find((x) => x.node.key === "new").frames[0].transform,
    "translate(0px, -50px)",
    "New and existing rows travel together by the actual inserted height",
  );
  assert.equal(insert.find((x) => x.node.key === "new").frames[0].opacity, 0);
  assert.ok(
    insert.every((x) => x.options.duration === 360 && !x.options.delay),
    "No stagger separates an arrival from the list movement",
  );
  await finish();
  render(["new", "a", "b", "c", "d"], "files", 1);
  assert.equal(container.children[1], a);
  assert.equal(
    a.children[0],
    text,
    "Nested controls and text nodes survive updates",
  );
  assert.equal(a.onclick(), 1, "Retained controls get current data handlers");
  await finish();
  container.scrollTop = 100;
  const oldTop = b.getBoundingClientRect().top;
  const scrolled = render(["newer", "new", "a", "b", "c", "d"], "files", 1);
  assert.equal(container.scrollTop, 150);
  assert.equal(
    b.getBoundingClientRect().top,
    oldTop,
    "Inserting above a scrolled viewport preserves the reading position",
  );
  assert.equal(
    scrolled.length,
    0,
    "Offscreen arrivals do not move the visible viewport",
  );
  reduced = true;
  render(["newest", "newer", "new", "a", "b", "c", "d"], "files", 1);
  assert.equal(
    container.scrollTop,
    200,
    "Reduced motion still preserves scroll position",
  );
  assert.equal(calls.length, 0);
  reduced = false;
  container.scrollTop = 0;
  render(["burst", "newest", "newer", "new", "a", "b", "c", "d"], "files", 1);
  const active = calls.find((x) => x.node === container.children[1]);
  container.children[1].visualY = -20;
  const interrupted = render(
    ["burst2", "burst", "newest", "newer", "new", "a", "b", "c", "d"],
    "files",
    1,
  );
  assert.equal(active.cancelled, true);
  assert.equal(
    interrupted.find((x) => x.node.key === "newest").frames[0].transform,
    "translate(0px, -70px)",
    "Interrupted movement starts at the current visual position",
  );
  await finish();
  a.focus();
  const sorted = render(
    ["a", "burst2", "burst", "newest", "newer", "new", "b", "c", "d"],
    "files",
    1,
  );
  assert.equal(
    context.document.activeElement,
    a,
    "Reordering preserves keyboard focus even without state-preserving DOM moves",
  );
  assert.ok(
    sorted.every((x) => x.frames[0].opacity === undefined),
    "Reordering does not replay entry fades",
  );
  await finish();
  render(["height-anchor", "height-next"], "heights");
  await finish();
  heights.tall = 95;
  const tall = render(["tall", "height-anchor", "height-next"], "heights");
  assert.equal(
    tall.find((x) => x.node.key === "height-anchor").frames[0].transform,
    "translate(0px, -95px)",
    "Movement uses measured heights",
  );
  await finish();
  const batch = Array.from({ length: 5 }, (_, i) => "batch-" + i);
  const moving = render(
    [...batch, "tall", "height-anchor", "height-next"],
    "heights",
  );
  assert.equal(
    moving.filter((x) => batch.includes(x.node.key)).length,
    5,
    "Rows crossing the viewport animate even if their final position is outside it",
  );
  await finish();
  render(["x", "y"], "other");
  await finish();
  assert.equal(container.children.length, 2);
  context.document.hidden = true;
  render(["background"], "other");
  assert.equal(calls.length, 0);
  context.document.hidden = false;
  render(["background"], "other");
  assert.equal(calls.length, 0, "Returning to a tab does not replay arrivals");
  context.document.hidden = true;
  documentEvents.visibilitychange();
  context.document.hidden = false;
  documentEvents.visibilitychange();
  render(["catch-up", "background"], "other");
  assert.equal(
    calls.length,
    0,
    "The first snapshot after a suspended tab does not replay accumulated arrivals",
  );
  render(["live-again", "catch-up", "background"], "other");
  assert.ok(calls.length > 0, "Subsequent live arrivals animate normally");
  await finish();
  const oldAnimate = Node.prototype.animate;
  Node.prototype.animate = undefined;
  render(["fallback"]);
  assert.equal(container.children.length, 1);
  Node.prototype.animate = oldAnimate;
  reduced = true;
  const bulk = Array.from({ length: 6100 }, (_, i) => "bulk-" + i);
  render(bulk);
  reduced = false;
  render(bulk);
  assert.equal(calls.length, 0);
  assert.equal(mutations, 0);
  const photoRow = new Node("TR"),
    frame = new Node("SPAN"),
    photo = new Node("IMG");
  frame.setAttribute("data-thumbnail", "photo:1");
  photo.setAttribute("src", "blob:decoded-preview");
  frame.append(photo);
  photoRow.append(frame);
  list.render(
    container,
    [{ key: "photo", version: 1, node: photoRow }],
    "previews",
  );
  const updated = new Node("TR"),
    incoming = new Node("SPAN");
  incoming.setAttribute("data-thumbnail", "photo:1");
  updated.append(incoming);
  list.render(
    container,
    [{ key: "photo", version: 2, node: updated }],
    "previews",
  );
  assert.equal(
    container.children[0].children[0].children[0],
    photo,
    "Status updates preserve decoded thumbnails and object URLs",
  );
  for (const page of ["index", "requests", "recovery"]) {
    const html = fs.readFileSync(
      path.join(__dirname, "../dist", page + ".html"),
      "utf8",
    );
    assert.ok(
      html.includes("/list-motion.js") &&
        html.includes("/live.js") &&
        html.includes("data-motion-scroll"),
    );
  }
  console.log(
    "List motion: keyed DOM, shared-distance insertion, scroll anchors, current handlers, interrupted motion, sorting, reduced motion, hidden tabs and fallback passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
