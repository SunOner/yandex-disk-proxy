"use strict";
(() => {
  const visible = new Map();
  const problems = new Map();
  const recentProblems = new Map();
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
    const animate = !immediate && !reduced() && item.card.animate;
    const style = animate && window.getComputedStyle?.(item.card);
    const start = {
      opacity: style?.opacity ?? 1,
      transform: style?.transform || "scale(1)",
    };
    item.animation?.cancel();
    item.card.inert = true;
    item.card.setAttribute("aria-hidden", "true");
    item.card.classList.add("toast-leaving");
    const remove = () => item.card.remove();
    if (!animate) remove();
    else {
      item.animation = item.card.animate(
        [start, { opacity: 0, transform: "scale(.98)" }],
        { duration: 180, easing: "ease-in", fill: "forwards" },
      );
      item.animation.finished.then(remove, remove);
    }
  }

  function show(message, { type = "info", key, duration, action } = {}) {
    const text = I18n.t(String(message || "").trim());
    if (!text) return;
    if (!icons[type]) type = "info";
    key ??= `${type}:${text}`;
    const existing = visible.get(key);
    if (existing?.message === text && existing.type === type && !action)
      return key;
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
    let actionButton = null;
    if (action) {
      actionButton = document.createElement("button");
      actionButton.type = "button";
      actionButton.className = "toast-action";
      actionButton.textContent = I18n.t(action.label);
      actionButton.addEventListener("click", async () => {
        if (actionButton.disabled || visible.get(key)?.card !== card) return;
        actionButton.disabled = true;
        try {
          await action.onClick();
          if (visible.get(key)?.card === card) dismiss(key);
        } catch (error) {
          actionButton.disabled = false;
          show(error.message, { type: "error" });
        }
      });
      content.append(actionButton);
    }
    const close = document.createElement("button");
    close.className = "toast-close";
    close.type = "button";
    close.setAttribute("aria-label", I18n.t("Закрыть уведомление"));
    close.textContent = "×";
    close.addEventListener("click", () => {
      if (visible.get(key)?.card === card) dismiss(key);
    });
    card.append(icon, content, close);

    const item = {
      card,
      title,
      body,
      close,
      action,
      actionButton,
      message: text,
      type,
      remaining: duration ?? (type === "error" ? 8000 : 4500),
      timer: null,
      hovered: false,
      focused: false,
      animation: null,
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
      const animation = card.animate(
        [
          { opacity: 0, transform: "scale(.98)" },
          { opacity: 1, transform: "scale(1)" },
        ],
        { duration: 240, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
      item.animation = animation;
      animation.finished.then(
        () => {
          if (item.animation === animation) item.animation = null;
        },
        () => {},
      );
    }
    resume();
    return key;
  }

  // Delay noisy connection failures and retain cooldowns across brief recoveries.
  function problem(key, message, options = {}) {
    const text = String(message || "").trim();
    const delay = Number.isFinite(options.delay)
      ? Math.max(0, options.delay)
      : 0;
    const cooldown = Number.isFinite(options.cooldown)
      ? Math.max(0, options.cooldown)
      : 0;
    const signature = JSON.stringify([
      key,
      text,
      options.action?.label || "",
      options.scope ?? "",
    ]);
    const identity = JSON.stringify([signature, delay, cooldown]);
    const previous = problems.get(key);
    if (text && previous?.identity === identity) {
      previous.options = options;
      return;
    }
    if (previous) clearTimeout(previous.timer);
    if (!text) {
      problems.delete(key);
      dismiss(key);
      return;
    }
    dismiss(key, true);
    const item = { identity, options, timer: null };
    problems.set(key, item);
    const notify = () => {
      item.timer = null;
      if (problems.get(key) !== item) return;
      if (cooldown) {
        recentProblems.delete(signature);
        recentProblems.set(signature, performance.now());
        while (recentProblems.size > 100)
          recentProblems.delete(recentProblems.keys().next().value);
      }
      show(text, { ...item.options, type: "error", key });
    };
    const lastShown = recentProblems.get(signature);
    const wait = Math.max(
      delay,
      lastShown === undefined ? 0 : cooldown - (performance.now() - lastShown),
    );
    if (wait > 0) item.timer = setTimeout(notify, wait);
    else notify();
  }

  function clearPending() {
    for (const [key, item] of problems) {
      if (item.timer === null) continue;
      clearTimeout(item.timer);
      problems.delete(key);
    }
  }
  document.addEventListener?.("visibilitychange", () => {
    if (document.hidden) clearPending();
  });
  window.addEventListener?.("pagehide", clearPending);

  I18n.onChange(() => {
    for (const item of visible.values()) {
      item.title.textContent = titles[item.type];
      item.message = I18n.t(item.message);
      item.body.textContent = item.message;
      item.close.setAttribute("aria-label", I18n.t("Закрыть уведомление"));
      if (item.actionButton)
        item.actionButton.textContent = I18n.t(item.action.label);
    }
  });
  window.Toasts = { show, dismiss, problem };
})();
