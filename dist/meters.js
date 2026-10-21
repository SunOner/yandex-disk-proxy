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
    const parts = text.match(/^(.*?)(?:\s+(Б|КБ|МБ|ГБ|ТБ|B|KB|MB|GB|TB))?$/u);
    const number = parts[1],
      unit = parts[2] || "";
    const precision = (number.split(I18n.decimal)[1] || "").length;
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
    }
  }

  function setConnected(value) {
    connected = value;
    $("board-status").textContent = connected
      ? status || I18n.t("Ожидание данных")
      : I18n.t("Нет связи с панелью");
    $("board-status").classList.toggle(
      "inactive",
      status !== I18n.t("Прокси включён"),
    );
    $("board-status").classList.toggle("disconnected", !connected);
    $("board-updated").textContent = updated
      ? (connected
          ? I18n.t("Обновлено в ")
          : I18n.t("Последнее обновление в ")) +
        updated.toLocaleTimeString(I18n.locale)
      : I18n.t("Ожидание данных");
  }

  function update(metrics, phase, fresh = true) {
    latest = metrics;
    status = phase;
    if (fresh) updated = new Date();
    for (const [key, metric] of Object.entries(metrics))
      paint(
        $("metric-" + key),
        metric.text,
        metric.value,
        fresh && board.hidden,
      );
    if (!board.hidden) drawBoard(fresh);
    setConnected(fresh ? true : connected);
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
          $("board-mode").textContent = I18n.t("Для выхода нажмите Esc");
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
    $("board-mode").textContent = I18n.t("Esc — вернуться к файлам");
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
              $("board-mode").textContent = I18n.t(
                "Табло в окне браузера · Esc — вернуться",
              );
          },
        );
      } catch {
        $("board-mode").textContent = I18n.t(
          "Табло в окне браузера · Esc — вернуться",
        );
      }
    } else
      $("board-mode").textContent = I18n.t(
        "Табло в окне браузера · Esc — вернуться",
      );
  }

  $("open-board").addEventListener("click", open);
  $("close-board").addEventListener("click", close);
  board.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
    if (event.key === "Tab") {
      const controls = Array.from(
        board.querySelectorAll("button:not([disabled])"),
      ).filter((button) => button.tabIndex >= 0 && !button.closest("[hidden]"));
      const first = controls[0],
        last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement === board) nativeEntered = true;
    else if (nativeEntered) {
      nativeEntered = false;
      finishClose();
    }
  });
  I18n.onChange(() => {
    status = I18n.t(status);
    setConnected(connected);
    $("board-mode").textContent = I18n.t($("board-mode").textContent);
  });
  return { update, setConnected, open, close };
})();
