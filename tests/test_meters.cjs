const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "dist/index.html"), "utf8");
const nodes = new Map(),
  animations = [],
  events = {};
let reduced = false;
const document = {
  hidden: false,
  fullscreenElement: null,
  fullscreenEnabled: false,
  activeElement: null,
};
function element() {
  const classes = new Set();
  return {
    tabIndex: 0,
    closest() { return null; },
    querySelectorAll() { return [get("close-board")]; },
    children: [],
    attributes: {},
    listeners: {},
    inert: false,
    hidden: false,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      toggle(name, value) {
        value ? classes.add(name) : classes.delete(name);
      },
    },
    replaceChildren(...children) {
      this.children = children;
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    addEventListener(name, callback) {
      this.listeners[name] = callback;
    },
    focus() {
      document.activeElement = this;
    },
    animate(frames, options) {
      let resolve, reject;
      const finished = new Promise((a, b) => {
        resolve = a;
        reject = b;
      });
      const animation = {
        frames,
        options,
        finished,
        cancelled: false,
        finish() {
          if (!this.cancelled) resolve();
        },
        cancel() {
          this.cancelled = true;
          reject(Error("cancelled"));
        },
      };
      animations.push(animation);
      return animation;
    },
  };
}
function get(id) {
  assert.ok(html.includes(`id="${id}"`), id);
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
}
document.getElementById = get;
document.createElement = element;
document.addEventListener = (name, fn) => {
  events[name] = fn;
};
document.body = element();
const outside = element(),
  originallyInert = element(),
  board = get("metrics-board");
originallyInert.inert = true;
board.hidden = true;
document.body.children = [outside, originallyInert, board];
document.activeElement = get("open-board");
const context = vm.createContext({
  I18n: require("./i18n_stub.cjs")(),
  document,
  console,
  matchMedia: () => ({ matches: reduced }),
});
context.window = context;
vm.runInContext(
  fs.readFileSync(path.join(root, "dist/meters.js"), "utf8"),
  context,
);
const dashboard = vm.runInContext("MeterBoard", context);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const data = (n, network = "999 КБ", networkValue = 999000) => ({
  pending: {
    text: n.toLocaleString("ru-RU"),
    value: n,
    detail: "82 ГБ осталось сохранить",
  },
  downloaded: { text: "212", value: 212, detail: "2,2 ГБ" },
  errors: { text: "4", value: 4, detail: "Ответы Яндекса" },
  deferred: { text: "4", value: 4, detail: "Отложены" },
  network: { text: network, value: networkValue, detail: "Сеть" },
});
const update = (...args) => dashboard.update(data(...args), "Прокси включён");
const reader = (id) => get(id).children[0].textContent;
async function finishAnimations() {
  animations.forEach((a) => a.finish());
  await tick();
}
async function main() {
  assert.ok(html.indexOf("/meters.js") < html.indexOf("/app.js"));
  update(9);
  assert.equal(
    animations.length,
    0,
    "Initial values do not roll from invented zeros",
  );
  assert.equal(reader("metric-pending"), "9");
  update(10);
  assert.equal(
    animations.length,
    1,
    "Carry adds a column and rolls the existing units",
  );
  assert.equal(
    reader("metric-pending"),
    "10",
    "Accessible value is current during animation",
  );
  assert.equal(
    get("metric-pending").children[1].attributes["aria-hidden"],
    "true",
  );
  update(10);
  assert.equal(
    animations.length,
    1,
    "Identical polling does not replay animations",
  );
  update(11);
  assert.equal(
    animations[0].cancelled,
    true,
    "Rapid updates cancel the stale animation",
  );
  await finishAnimations();
  assert.equal(reader("metric-pending"), "11");
  update(9);
  assert.equal(
    animations.at(-1).frames[0].transform,
    "translateY(-50%)",
    "Decreasing values roll in reverse",
  );
  await finishAnimations();
  update(999);
  await finishAnimations();
  const beforeCarry = animations.length;
  update(1000);
  assert.equal(
    animations.length - beforeCarry,
    3,
    "999 to 1 000 rolls three existing places",
  );
  await finishAnimations();
  const beforeUnit = animations.length;
  update(1000, "1 МБ", 1048576);
  assert.equal(
    animations.length,
    beforeUnit,
    "Changing units does not roll 999 into 1",
  );
  update(1000, "9,9 МБ", 10380902);
  await finishAnimations();
  const beforePrecision = animations.length;
  update(1000, "10 МБ", 10485760);
  assert.equal(
    animations.length,
    beforePrecision,
    "Changing decimal precision does not mix digit places",
  );
  update(1001, "1 МБ", 1048576);
  reduced = true;
  update(1001, "1 МБ", 1048576);
  await tick();
  assert.equal(
    animations.at(-1).cancelled,
    true,
    "Turning off motion settles an in-flight value",
  );
  const beforeReduced = animations.length;
  update(1002, "1 МБ", 1048576);
  assert.equal(animations.length, beforeReduced);
  reduced = false;
  document.hidden = true;
  update(1003, "1 МБ", 1048576);
  assert.equal(
    animations.length,
    beforeReduced,
    "Background tabs do not animate",
  );
  document.hidden = false;

  dashboard.open();
  assert.equal(board.hidden, false);
  assert.equal(outside.inert, true);
  assert.equal(document.activeElement, get("close-board"));
  assert.equal(reader("board-pending"), "1 003");
  assert.ok(get("board-mode").textContent.includes("окне браузера"));
  const whileOpen = animations.length;
  update(1004, "1 МБ", 1048576);
  assert.equal(
    animations.length - whileOpen,
    1,
    "Only the visible board rolls while open",
  );
  dashboard.setConnected(false);
  assert.equal(get("board-status").textContent, "Нет связи с панелью");
  assert.equal(reader("board-pending"), "1 004", "Offline values are retained");
  board.listeners.keydown({ key: "Tab", preventDefault() {} });
  assert.equal(
    document.activeElement,
    get("close-board"),
    "Focus remains in the board",
  );
  board.listeners.keydown({ key: "Escape", preventDefault() {} });
  assert.equal(board.hidden, true);
  assert.equal(outside.inert, false);
  assert.equal(originallyInert.inert, true, "Original inert state is restored");
  assert.equal(document.activeElement, get("open-board"));

  document.fullscreenEnabled = true;
  board.requestFullscreen = () => {
    document.fullscreenElement = board;
    events.fullscreenchange();
    return Promise.resolve();
  };
  document.exitFullscreen = () => {
    document.fullscreenElement = null;
    events.fullscreenchange();
    return Promise.resolve();
  };
  dashboard.open();
  assert.equal(document.fullscreenElement, board);
  await dashboard.close();
  assert.equal(document.fullscreenElement, null);
  assert.equal(board.hidden, true, "Native exit closes and restores the page");
  board.requestFullscreen = () => Promise.reject(Error("denied"));
  dashboard.open();
  await tick();
  assert.equal(
    board.hidden,
    false,
    "Denied fullscreen keeps a usable window-sized board",
  );
  assert.ok(get("board-mode").textContent.includes("окне браузера"));
  await dashboard.close();
  let accept;
  board.requestFullscreen = () =>
    new Promise((resolve) => {
      accept = resolve;
    });
  dashboard.open();
  await dashboard.close();
  document.fullscreenElement = board;
  events.fullscreenchange();
  accept();
  await tick();
  assert.equal(
    document.fullscreenElement,
    null,
    "A late fullscreen request cannot leave a hidden fullscreen page",
  );
  assert.equal(board.hidden, true);
  await finishAnimations();
  context.I18n.locale = 'en-GB';
  context.I18n.decimal = '.';
  const englishData = n => ({...data(n), pending:{text:n.toLocaleString('en-GB'),value:n,detail:'82 GB'},network:{text:'1.1 MB',value:1153434,detail:'Network'}});
  dashboard.update(englishData(999), 'Proxy is on');
  await finishAnimations();
  const englishCarry = animations.length;
  dashboard.update(englishData(1000), 'Proxy is on');
  assert.equal(animations.length - englishCarry, 3, 'English grouping comma is not treated as a decimal separator');
  assert.equal(reader('metric-pending'), '1,000');
  await finishAnimations();
  dashboard.setConnected(false);
  dashboard.update(englishData(1000), 'Proxy is on', false);
  dashboard.open();
  assert.equal(get('board-status').textContent, 'Нет связи с панелью', 'Relocalizing cached metrics cannot reconnect the dashboard');
  await dashboard.close();
  console.log(
    "Meters: carries, reverse/rapid updates, units, accessible values, reduced motion, offline state, focus, fullscreen, fallback and late requests passed.",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
