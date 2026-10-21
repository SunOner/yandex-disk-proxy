"use strict";
(() => {
  const visible = new Map();
  const problems = new Map();
  const icons = { success: "✓", error: "!", info: "i" };
  const titles = I18n.labels({
    success: "Готово",
    error: "Ошибка",
    info: "Информация",
  });
  const reduced = () =>
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  function dismiss(key, immediate = false) {
    const item = visible.get(key);
    if (!item) return;
    visible.delete(key);
    clearTimeout(item.timer);
    item.close.disabled = true;
    item.card.classList.add("toast-leaving");
    const remove = () => item.card.remove();
    if (immediate || reduced() || !item.card.animate) remove();
    else {
      item.card
        .animate(
          [
            { opacity: 1, transform: "translateX(0)" },
            { opacity: 0, transform: "translateX(18px)" },
          ],
          { duration: 180, easing: "ease-in", fill: "forwards" },
        )
        .finished.then(remove, remove);
    }
  }

  function show(message, { type = "info", key, duration } = {}) {
    const text = I18n.t(String(message || "").trim());
    if (!text) return;
    if (!icons[type]) type = "info";
    key ??= `${type}:${text}`;
    const existing = visible.get(key);
    if (existing?.message === text && existing.type === type) return key;
    if (existing) dismiss(key, true);
    while (visible.size >= 3) dismiss(visible.keys().next().value, true);

    const card = document.createElement("div");
    card.className = `toast toast-${type}`;
    card.setAttribute("role", type === "error" ? "alert" : "status");
    card.setAttribute("aria-atomic", "true");
    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.textContent = icons[type];
    icon.setAttribute("aria-hidden", "true");
    const content = document.createElement("div");
    content.className = "toast-content";
    const title = document.createElement("strong");
    title.textContent = titles[type];
    const body = document.createElement("p");
    body.textContent = text;
    content.append(title, body);
    const close = document.createElement("button");
    close.className = "toast-close";
    close.type = "button";
    close.setAttribute("aria-label", I18n.t("Закрыть уведомление"));
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(key));
    card.append(icon, content, close);

    const item = {
      card,
      title,
      body,
      close,
      message: text,
      type,
      remaining: duration ?? (type === "error" ? 8000 : 4500),
      timer: null,
      hovered: false,
      focused: false,
    };
    const pause = () => {
      if (item.timer === null) return;
      clearTimeout(item.timer);
      item.timer = null;
      item.remaining = Math.max(
        0,
        item.remaining - (performance.now() - item.started),
      );
    };
    const resume = () => {
      if (
        visible.get(key) !== item ||
        item.hovered ||
        item.focused ||
        item.timer !== null
      )
        return;
      item.started = performance.now();
      item.timer = setTimeout(() => dismiss(key), item.remaining);
    };
    card.addEventListener("pointerenter", () => {
      item.hovered = true;
      pause();
    });
    card.addEventListener("pointerleave", () => {
      item.hovered = false;
      resume();
    });
    card.addEventListener("focusin", () => {
      item.focused = true;
      pause();
    });
    card.addEventListener("focusout", (event) => {
      item.focused = card.contains(event.relatedTarget);
      resume();
    });
    visible.set(key, item);
    document.getElementById("toast-stack").append(card);
    if (!reduced() && card.animate) {
      card.animate(
        [
          { opacity: 0, transform: "translateY(10px) scale(.98)" },
          { opacity: 1, transform: "translateY(0) scale(1)" },
        ],
        { duration: 240, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
    }
    resume();
    return key;
  }

  // Polling errors stay quiet after dismissal until their state changes.
  function problem(key, message) {
    const text = String(message || "").trim();
    if (!text) {
      problems.delete(key);
      dismiss(key);
    } else if (problems.get(key) !== text) {
      problems.set(key, text);
      show(text, { type: "error", key });
    }
  }

  I18n.onChange(() => {
    for (const item of visible.values()) {
      item.title.textContent = titles[item.type];
      item.message = I18n.t(item.message);
      item.body.textContent = item.message;
      item.close.setAttribute("aria-label", I18n.t("Закрыть уведомление"));
    }
  });
  window.Toasts = { show, dismiss, problem };
})();
