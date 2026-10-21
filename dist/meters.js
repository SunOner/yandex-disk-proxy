"use strict";
const MeterBoard = (() => {
  const $ = (id) => document.getElementById(id);
  const meters = new WeakMap();
  const board = $("metrics-board");
  let latest = null,
    status = "",
    connected = true,
    updated = null;
  let restoreFocus = null,
    inertElements = [],
    nativeEntered = false;

  function paint(element, text, value, motion) {
    let state = meters.get(element);
    const allowMotion =
      motion &&
      !document.hidden &&
      !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (state?.text === text) {
      if (!allowMotion) state.slots.forEach((slot) => slot.animation?.finish());
      return;
    }
    const parts = text.match(/^(.*?)(?:\s+(Б|КБ|МБ|ГБ|ТБ))?$/u);
    const number = parts[1],
      unit = parts[2] || "";
    const precision = (number.split(",")[1] || "").length;
    const animate =
      !!state &&
      state.unit === unit &&
      state.precision === precision &&
      allowMotion;
    const previous = state?.slots || [];
    if (!state) {
      const reader = document.createElement("span");
      reader.className = "counter-reader";
      const visual = document.createElement("span");
      visual.className = "counter-visual";
      visual.setAttribute("aria-hidden", "true");
      element.replaceChildren(reader, visual);
      state = { reader, visual };
      meters.set(element, state);
    }
    const nodes = [],
      slots = [];
    let position = 0;
    const direction = value >= (state.value ?? value) ? 1 : -1;
    // Match digits from the right so 999 → 1 000 keeps the same decimal places.
    for (const char of Array.from(number).reverse()) {
      if (/\d/.test(char)) {
        const old = previous[position++];
        const slot = old || { node: document.createElement("span") };
        slot.node.className = "counter-digit";
        if (slot.char !== char) {
          slot.animation?.cancel();
          const reel = document.createElement("span");
          reel.className = "counter-reel";
          const face = (digit) => {
            const span = document.createElement("span");
            span.className = "counter-face";
            span.textContent = digit;
            return span;
          };
          const before = slot.char;
          const roll = animate && before !== undefined && reel.animate;
          reel.replaceChildren(
            ...(roll
              ? direction > 0
                ? [before, char]
                : [char, before]
              : [char]
            ).map(face),
          );
          slot.node.replaceChildren(reel);
          slot.char = char;
          if (roll) {
            const animation = reel.animate(
              [
                {
                  transform:
                    direction > 0 ? "translateY(0)" : "translateY(-50%)",
                },
                {
                  transform:
                    direction > 0 ? "translateY(-50%)" : "translateY(0)",
                },
              ],
              {
                duration: 460,
                easing: "cubic-bezier(.22,.75,.2,1)",
                fill: "forwards",
              },
            );
            slot.animation = animation;
            animation.finished.then(
              () => {
                if (slot.animation !== animation) return;
                reel.replaceChildren(face(char));
                slot.animation = null;
                animation.cancel();
              },
              () => {},
            );
          } else slot.animation = null;
        }
        slots.push(slot);
        nodes.unshift(slot.node);
      } else {
        const separator = document.createElement("span");
        separator.className = "counter-separator";
        separator.textContent = char;
        nodes.unshift(separator);
      }
    }
    previous.slice(position).forEach((slot) => slot.animation?.cancel());
    if (unit) {
      const suffix = document.createElement("span");
      suffix.className = "counter-unit";
      suffix.textContent = unit;
      nodes.push(suffix);
    }
    state.visual.replaceChildren(...nodes);
    state.reader.textContent = text;
    Object.assign(state, { text, value, unit, precision, slots });
  }

  function drawBoard(motion) {
    if (!latest) return;
    for (const [key, metric] of Object.entries(latest)) {
      paint($("board-" + key), metric.text, metric.value, motion);
      $("board-" + key + "-detail").textContent = metric.detail;
    }
  }

  function setConnected(value) {
    connected = value;
    $("board-status").textContent = connected
      ? status || "Ожидание данных"
      : "Нет связи с панелью";
    $("board-status").classList.toggle("inactive", status !== "Прокси включён");
    $("board-status").classList.toggle("disconnected", !connected);
    $("board-updated").textContent = updated
      ? (connected ? "Обновлено в " : "Последнее обновление в ") +
        updated.toLocaleTimeString("ru-RU")
      : "Ожидание данных";
  }

  function update(metrics, phase) {
    latest = metrics;
    status = phase;
    updated = new Date();
    for (const [key, metric] of Object.entries(metrics))
      paint($("metric-" + key), metric.text, metric.value, board.hidden);
    if (!board.hidden) drawBoard(true);
    setConnected(true);
  }

  function finishClose() {
    if (board.hidden) return;
    board.hidden = true;
    nativeEntered = false;
    for (const [element, wasInert] of inertElements) element.inert = wasInert;
    inertElements = [];
    document.body.classList.remove("board-open");
    $("open-board").setAttribute("aria-expanded", "false");
    restoreFocus?.focus({ preventScroll: true });
  }

  async function close() {
    if (document.fullscreenElement === board) {
      try {
        await document.exitFullscreen();
      } catch {
        if (document.fullscreenElement === board) {
          $("board-mode").textContent = "Для выхода нажмите Esc";
          return;
        }
      }
    }
    finishClose();
  }

  function open() {
    if (!board.hidden) return;
    restoreFocus = document.activeElement;
    nativeEntered = false;
    board.hidden = false;
    document.body.classList.add("board-open");
    inertElements = Array.from(document.body.children)
      .filter((element) => element !== board)
      .map((element) => [element, element.inert]);
    inertElements.forEach(([element]) => {
      element.inert = true;
    });
    $("open-board").setAttribute("aria-expanded", "true");
    $("board-mode").textContent = "Esc — вернуться к файлам";
    drawBoard(false);
    setConnected(connected);
    $("close-board").focus({ preventScroll: true });
    if (board.requestFullscreen && document.fullscreenEnabled !== false) {
      try {
        Promise.resolve(board.requestFullscreen({ navigationUI: "hide" })).then(
          () => {
            if (board.hidden && document.fullscreenElement === board)
              document.exitFullscreen().catch(() => {});
          },
          () => {
            if (!board.hidden)
              $("board-mode").textContent =
                "Табло в окне браузера · Esc — вернуться";
          },
        );
      } catch {
        $("board-mode").textContent = "Табло в окне браузера · Esc — вернуться";
      }
    } else
      $("board-mode").textContent = "Табло в окне браузера · Esc — вернуться";
  }

  $("open-board").addEventListener("click", open);
  $("close-board").addEventListener("click", close);
  board.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
    if (event.key === "Tab") {
      event.preventDefault();
      $("close-board").focus();
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement === board) nativeEntered = true;
    else if (nativeEntered) {
      nativeEntered = false;
      finishClose();
    }
  });
  return { update, setConnected, open, close };
})();
