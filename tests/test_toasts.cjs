const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
let now = 0,
  sequence = 0,
  reduced = false,
  animations = [],
  cancelled = 0;
const timers = new Map();
const documentEvents = {};
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
      return {
        finished: Promise.resolve(),
        cancel() {
          cancelled++;
        },
      };
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
    hidden: false,
    addEventListener(name, handler) {
      documentEvents[name] = handler;
    },
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
  for (const name of ["index", "requests"]) {
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
  const beforeCancel = cancelled;
  context.getComputedStyle = () => ({
    opacity: "0.24",
    transform: "matrix(0.985, 0, 0, 0.985, 0, 0)",
  });
  const rapid = toast.show("Closing during entry", { key: "rapid" });
  const rapidCard = host.children[0];
  toast.dismiss(rapid);
  assert.equal(cancelled, beforeCancel + 1, "Entry stops before exit starts");
  assert.equal(
    animations.at(-1).frames[0].opacity,
    "0.24",
    "Closing during entry keeps the current opacity instead of flashing fully visible",
  );
  assert.equal(rapidCard.inert, true, "Exiting controls cannot receive input");
  assert.notEqual(
    rapidCard.children[2].disabled,
    true,
    "Closing preserves button styling during the fade",
  );
  delete context.getComputedStyle;
  toast.show("Replacement", { key: "rapid" });
  rapidCard.children[2].listeners.click();
  await tick();
  assert.equal(
    host.children.length,
    1,
    "A leaving close button cannot close its replacement",
  );
  toast.dismiss("rapid", true);

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
  const repairOptions = () => ({
    action: { label: "Repair", onClick() {} },
  });
  toast.problem("tls", "Certificate missing", repairOptions());
  const repairCard = host.children[0];
  assert.equal(repairCard.children[1].children[2].textContent, "Repair");
  for (let i = 0; i < 50; i++)
    toast.problem("tls", "Certificate missing", repairOptions());
  assert.equal(
    host.children[0],
    repairCard,
    "Polling does not replace or animate an unchanged actionable error",
  );
  repairCard.children[2].listeners.click();
  await tick();
  toast.problem("tls", "Certificate missing", repairOptions());
  assert.equal(host.children.length, 0, "Dismissed repair prompts stay quiet");
  toast.problem("tls", "");
  toast.problem("tls", "Certificate missing", repairOptions());
  assert.equal(host.children.length, 1);
  toast.problem("tls", "Certificate missing", {
    action: { label: "Restart", onClick() {} },
  });
  assert.equal(
    host.children.length,
    1,
    "Changed actions replace the old prompt",
  );
  assert.equal(host.children[0].children[1].children[2].textContent, "Restart");
  toast.problem("tls", "");
  await tick();
  assert.equal(host.children.length, 0, "Recovered TLS clears its prompt");
  const upstreamOptions = { delay: 1000, cooldown: 5000, scope: "session-a" };
  toast.problem("upstream", "TLS connection closed", upstreamOptions);
  await advance(900);
  for (let i = 0; i < 50; i++)
    toast.problem("upstream", "TLS connection closed", upstreamOptions);
  toast.problem("upstream", "");
  await advance(100);
  assert.equal(
    host.children.length,
    0,
    "A recovered transient error never flashes a toast",
  );
  toast.problem("upstream", "TLS connection closed", upstreamOptions);
  await advance(999);
  assert.equal(host.children.length, 0);
  await advance(1);
  assert.equal(
    host.children.length,
    1,
    "A persistent failure is still reported",
  );
  toast.problem("upstream", "");
  await tick();
  toast.problem("upstream", "TLS connection closed", upstreamOptions);
  await advance(4999);
  assert.equal(
    host.children.length,
    0,
    "Recovery/failure flapping respects the cooldown",
  );
  await advance(1);
  assert.equal(
    host.children.length,
    1,
    "An unresolved new outage is reported after cooldown",
  );
  toast.problem("upstream", "");
  await tick();
  toast.problem("upstream", "TLS connection closed", upstreamOptions);
  toast.problem("upstream", "TLS connection closed", { scope: "session-a" });
  assert.equal(
    host.children.length,
    1,
    "Escalation to a certificate failure bypasses delay and cooldown",
  );
  toast.problem("upstream", "");
  await tick();
  toast.problem("upstream", "TLS connection closed", {
    ...upstreamOptions,
    scope: "session-b",
  });
  await advance(1000);
  assert.equal(
    host.children.length,
    1,
    "A restarted proxy has its own outage scope",
  );
  toast.problem("upstream", "");
  await tick();
  toast.problem("background", "TLS connection closed", upstreamOptions);
  context.document.hidden = true;
  documentEvents.visibilitychange();
  await advance(1000);
  assert.equal(
    host.children.length,
    0,
    "Backgrounding cancels a stale pending alert",
  );
  context.document.hidden = false;
  toast.problem("background", "TLS connection closed", upstreamOptions);
  await advance(1000);
  assert.equal(
    host.children.length,
    1,
    "A fresh foreground state can report the failure",
  );
  toast.problem("background", "");
  await tick();
  await advance(5000);
  assert.equal(
    host.children.length,
    0,
    "Replaced and cancelled timers cannot resurrect alerts",
  );
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
  let finish,
    calls = 0;
  toast.show("Reset", {
    key: "reset",
    action: {
      label: "Undo",
      onClick() {
        calls++;
        return new Promise((resolve) => (finish = resolve));
      },
    },
  });
  const undoButton = host.children[0].children[1].children[2];
  const undoing = undoButton.listeners.click();
  assert.equal(undoButton.disabled, true);
  await undoButton.listeners.click();
  assert.equal(calls, 1, "Undo cannot be submitted twice");
  toast.show("Reset", {
    key: "reset",
    action: { label: "Undo latest", onClick() {} },
  });
  assert.equal(
    host.children[0].children[1].children[2].textContent,
    "Undo latest",
  );
  finish();
  await undoing;
  assert.equal(
    host.children.length,
    1,
    "An old completion cannot dismiss the newer undo action",
  );
  await host.children[0].children[1].children[2].listeners.click();
  assert.equal(host.children.length, 0);
  toast.problem("failed-action", "TLS error", {
    action: {
      label: "Restart",
      async onClick() {
        throw new Error("Restart failed");
      },
    },
  });
  const restartButton = host.children[0].children[1].children[2];
  await restartButton.listeners.click();
  assert.equal(restartButton.disabled, false, "A failed action can be retried");
  assert.equal(host.children.length, 2, "Action failures show an error toast");
  assert.equal(
    host.children[1].children[1].children[1].textContent,
    "Restart failed",
  );
  console.log(
    "Toasts: animation, expiry, hover/focus, dismiss, deduplication, bounded stack, text safety, reduced motion and fallback passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
