const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const calls = [];
let reduced = false;
const container = {
  children: [],
  replaceChildren(...items) {
    this.children = items;
  },
};
function entry(key, animate = true) {
  const node = { key };
  if (animate)
    node.animate = (frames, options) => {
      assert.ok(container.children.includes(node), "Animate after insertion");
      calls.push({ key, frames, options });
    };
  return { key, node };
}
const context = vm.createContext({
  document: { hidden: false },
  matchMedia(query) {
    assert.equal(query, "(prefers-reduced-motion: reduce)");
    return { matches: reduced };
  },
  container,
  entries: [],
  scope: "files",
});
vm.runInContext(
  fs.readFileSync(path.join(root, "dist/list-motion.js"), "utf8"),
  context,
);
function render(keys, scope = "files", animate = true) {
  context.entries = keys.map((key) => entry(key, animate));
  context.scope = scope;
  calls.length = 0;
  vm.runInContext("ListMotion.render(container,entries,scope)", context);
  return calls.map((call) => call.key);
}
assert.deepEqual(render(["a", "b"]), ["a", "b"]);
assert.deepEqual(
  render(["a", "b"]),
  [],
  "Polling and progress updates must not animate old rows",
);
assert.deepEqual(render(["new", "a", "b"]), ["new"]);
assert.deepEqual(
  render(["b", "new", "a"]),
  [],
  "Sorting must not replay entry animations",
);
assert.deepEqual(
  render(["b", "new", "a", "older"]),
  ["older"],
  "Show more animates only newly revealed rows",
);
assert.deepEqual(
  render(["a", "b"], "events"),
  ["a", "b"],
  "List views have independent identities",
);
reduced = true;
assert.deepEqual(render(["reduced"]), []);
reduced = false;
context.document.hidden = true;
assert.deepEqual(render(["background"]), []);
context.document.hidden = false;
assert.deepEqual(
  render(["background"]),
  [],
  "Returning to a tab must not replay old arrivals",
);
assert.deepEqual(
  render(["fallback"], "files", false),
  [],
  "Keep rendering without Web Animations support",
);
render(Array.from({ length: 100 }, (_, i) => "bulk-" + i));
assert.equal(container.children.length, 100);
assert.ok(
  calls.every(
    (call) => call.options.duration === 240 && call.options.delay <= 60,
  ),
);
assert.equal(calls[0].frames[0].opacity, 0);
assert.equal(calls[0].frames[1].opacity, 1);
reduced = true;
const expanded = Array.from({ length: 6100 }, (_, i) => "expanded-" + i);
render(expanded);
reduced = false;
assert.deepEqual(
  render(expanded),
  [],
  "An expanded list must not animate again on polling",
);
for (const page of ["index", "requests", "recovery"]) {
  const html = fs.readFileSync(path.join(root, "dist", page + ".html"), "utf8");
  assert.ok(html.includes("/list-motion.js"));
  assert.ok(
    html.indexOf("/list-motion.js") < html.lastIndexOf("<script"),
    "Shared renderer loads first",
  );
}
console.log(
  "List motion: only new identities animate; sorting, polling, reduced motion, background tabs and fallback verified.",
);
