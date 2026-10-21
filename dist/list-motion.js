"use strict";
const ListMotion = (() => {
  const lists = new WeakMap();
  const capacity = 6000;
  function render(container, entries, scope = "") {
    let seen = lists.get(container);
    if (!seen) {
      seen = new Map();
      lists.set(container, seen);
    }
    const added = [];
    for (const entry of entries) {
      const key = scope + "\0" + String(entry.key);
      if (!seen.has(key)) added.push(entry.node);
      seen.delete(key);
      seen.set(key, true);
    }
    while (seen.size > Math.max(capacity, entries.length))
      seen.delete(seen.keys().next().value);
    container.replaceChildren(...entries.map((entry) => entry.node));
    if (
      document.hidden ||
      (typeof matchMedia === "function" &&
        matchMedia("(prefers-reduced-motion: reduce)").matches)
    )
      return;
    added.forEach((node, index) => {
      node.animate?.(
        [
          { opacity: 0, transform: "translateY(-6px)" },
          { opacity: 1, transform: "translateY(0)" },
        ],
        {
          duration: 240,
          delay: Math.min(index * 12, 60),
          easing: "cubic-bezier(.2,.7,.3,1)",
          fill: "backwards",
        },
      );
    });
  }
  return { render };
})();
