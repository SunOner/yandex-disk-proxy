const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
let now = 0,
  sequence = 0,
  reduced = false,
  animations = [];
const timers = new Map();
function node() {
  const value = {
    children: [],
    attributes: {},
    listeners: {},
    classList: { add() {} },
    setAttribute(key, value) {
      this.attributes[key] = value;
    },
    addEventListener(name, fn) {
      this.listeners[name] = fn;
    },
    append(...children) {
      children.forEach((child) => (child.parent = this));
      this.children.push(...children);
    },
    contains(child) {
      return this.children.includes(child);
    },
    remove() {
      this.parent.children = this.parent.children.filter(
        (child) => child !== this,
      );
    },
    animate(frames, options) {
      animations.push({ frames, options });
      return { finished: Promise.resolve() };
    },
  };
  return value;
}
const host = node();
const context = vm.createContext({
  I18n: require("./i18n_stub.cjs")(),
  console,
  performance: { now: () => now },
  setTimeout(fn, delay) {
    const id = ++sequence;
    timers.set(id, { fn, at: now + delay });
    return id;
  },
  clearTimeout(id) {
    timers.delete(id);
  },
  document: {
    createElement: node,
    getElementById(id) {
      assert.equal(id, "toast-stack");
      return host;
    },
  },
  matchMedia: () => ({ matches: reduced }),
});
context.window = context;
vm.runInContext(
  fs.readFileSync(path.join(root, "dist/toasts.js"), "utf8"),
  context,
);
const toast = context.Toasts;
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function advance(ms) {
  const end = now + ms;
  for (;;) {
    const next = [...timers]
      .filter(([, t]) => t.at <= end)
      .sort((a, b) => a[1].at - b[1].at)[0];
    if (!next) break;
    now = next[1].at;
    timers.delete(next[0]);
    next[1].fn();
    await tick();
  }
  now = end;
}
async function main() {
  for (const name of ["index", "requests", "recovery"]) {
    const html = fs.readFileSync(path.join(root, `dist/${name}.html`), "utf8");
    assert.ok(html.includes('id="toast-stack"'));
    assert.ok(
      html.indexOf("/toasts.js") <
        html.indexOf(`/${name === "index" ? "app" : name}.js`),
    );
    assert.ok(!html.includes('id="log-error"') && !html.includes('id="toast"'));
  }
  const key = toast.show("Настройки сохранены.", { type: "success" });
  const card = host.children[0];
  assert.equal(card.attributes.role, "status");
  assert.equal(
    card.children[2].attributes["aria-label"],
    "Закрыть уведомление",
  );
  assert.equal(animations.length, 1, "Entry is animated");
  toast.show("Настройки сохранены.", { type: "success" });
  assert.equal(host.children.length, 1, "Duplicate action is coalesced");
  await advance(1000);
  card.listeners.pointerenter();
  await advance(10000);
  assert.equal(host.children.length, 1, "Hover prevents expiry");
  card.listeners.focusin();
  card.listeners.pointerleave();
  await advance(10000);
  assert.equal(
    host.children.length,
    1,
    "Keyboard focus keeps it open after pointer leaves",
  );
  card.listeners.focusout({ relatedTarget: null });
  await advance(3499);
  assert.equal(host.children.length, 1);
  await advance(1);
  assert.equal(
    host.children.length,
    0,
    "Remaining lifetime resumes, rather than resetting",
  );
  assert.equal(animations.length, 2, "Exit is animated");

  toast.problem("poll", "Сервер недоступен");
  assert.equal(host.children[0].attributes.role, "alert");
  host.children[0].children[2].listeners.click();
  await tick();
  for (let i = 0; i < 50; i++) toast.problem("poll", "Сервер недоступен");
  assert.equal(
    host.children.length,
    0,
    "Dismissed polling error does not return every refresh",
  );
  toast.problem("poll", "Другая ошибка");
  assert.equal(host.children.length, 1, "Changed error is shown");
  toast.problem("poll", "");
  await tick();
  assert.equal(host.children.length, 0, "Resolved errors are removed");
  toast.problem("poll", "Другая ошибка");
  assert.equal(host.children.length, 1, "New outage after recovery is shown");
  toast.dismiss("poll", true);
  for (let i = 0; i < 50; i++) toast.show(`Событие ${i}`);
  assert.equal(host.children.length, 3, "Stack is bounded");
  await advance(4500);
  assert.equal(host.children.length, 0);

  reduced = true;
  const before = animations.length;
  const literal = '<img src=x onerror="alert(1)">';
  const safe = toast.show(literal, { type: "error" });
  const dismissed = host.children[0];
  dismissed.listeners.pointerenter();
  assert.equal(host.children[0].children[1].children[1].textContent, literal);
  assert.equal(
    animations.length,
    before,
    "Reduced motion skips entry animation",
  );
  toast.dismiss(safe);
  dismissed.listeners.pointerleave();
  dismissed.listeners.focusout({ relatedTarget: null });
  assert.equal(host.children.length, 0);
  assert.equal(
    timers.size,
    0,
    "Leaving a dismissed toast cannot restart its timer",
  );
  assert.equal(
    animations.length,
    before,
    "Reduced motion skips exit animation",
  );
  reduced = false;
  const create = context.document.createElement;
  context.document.createElement = () => {
    const value = create();
    delete value.animate;
    return value;
  };
  toast.show("Без Web Animations API");
  await advance(4500);
  assert.equal(host.children.length, 0, "Fallback still expires");
  assert.equal(timers.size, 0, "Dismissal clears timers");
  console.log(
    "Toasts: animation, expiry, hover/focus, dismiss, deduplication, bounded stack, text safety, reduced motion and fallback passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
