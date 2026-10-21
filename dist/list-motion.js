"use strict";
const ListMotion = (() => {
  const lists = new WeakMap();
  let generation = 0;
  document.addEventListener?.("visibilitychange", () => {
    if (document.hidden) generation++;
  });
  const duration = 360;
  const easing = "cubic-bezier(.22,.75,.25,1)";
  const reduced = () =>
    document.hidden ||
    (typeof matchMedia === "function" &&
      matchMedia("(prefers-reduced-motion: reduce)").matches);
  // Keep focused controls and their DOM identity, but replace their data handlers.
  function patch(current, incoming) {
    if (
      current.nodeType !== incoming.nodeType ||
      current.nodeName !== incoming.nodeName
    ) {
      current.replaceWith(incoming);
      return incoming;
    }
    if (current.nodeType === 3) {
      if (current.nodeValue !== incoming.nodeValue)
        current.nodeValue = incoming.nodeValue;
      return current;
    }
    if (current.nodeType !== 1) return current;
    // Thumbnail decoding and object URLs belong to the preview controller.
    if (
      current.hasAttribute("data-thumbnail") &&
      current.getAttribute("data-thumbnail") ===
        incoming.getAttribute("data-thumbnail")
    )
      return current;
    current.onclick = incoming.onclick;
    for (const attribute of Array.from(current.attributes))
      if (!incoming.hasAttribute(attribute.name))
        current.removeAttribute(attribute.name);
    for (const attribute of incoming.attributes)
      if (current.getAttribute(attribute.name) !== attribute.value)
        current.setAttribute(attribute.name, attribute.value);
    const before = Array.from(current.childNodes),
      after = Array.from(incoming.childNodes);
    after.forEach((child, i) => {
      if (before[i]) patch(before[i], child);
      else current.append(child);
    });
    before.slice(after.length).forEach((child) => child.remove());
    return current;
  }
  function viewport(container) {
    const marked = container.closest?.("[data-motion-scroll]");
    const local =
      marked &&
      (marked.scrollHeight > marked.clientHeight + 1 ||
        marked.scrollWidth > marked.clientWidth + 1);
    const scroller = local ? marked : document.scrollingElement;
    const clip = local
      ? marked.getBoundingClientRect()
      : {
          top: 0,
          left: 0,
          bottom: window.innerHeight,
          right: window.innerWidth,
        };
    const head = local && marked.querySelector("thead");
    return {
      scroller,
      clip: {
        top: head
          ? Math.max(clip.top, head.getBoundingClientRect().bottom)
          : clip.top,
        left: clip.left,
        bottom: clip.bottom,
        right: clip.right,
      },
    };
  }
  const visible = (rect, clip) =>
    rect.bottom > clip.top &&
    rect.top < clip.bottom &&
    rect.right > clip.left &&
    rect.left < clip.right;
  function cancel(state) {
    for (const animation of state.animations.values()) animation.cancel();
    state.animations.clear();
  }
  function animate(state, node, frames) {
    if (!node.animate) return;
    const animation = node.animate(frames, { duration, easing });
    state.animations.set(node, animation);
    animation.finished?.then(
      () => {
        if (state.animations.get(node) === animation)
          state.animations.delete(node);
      },
      () => {},
    );
  }
  function render(container, entries, scope = "") {
    let state = lists.get(container);
    if (!state) {
      state = {
        rows: new Map(),
        order: [],
        scope,
        seen: new Map(),
        animations: new Map(),
        generation,
      };
      lists.set(container, state);
    }
    const sameScope = state.scope === scope;
    const previous = sameScope ? state.rows : new Map();
    const order = entries.map((entry) => String(entry.key));
    const attached =
      container.children.length === state.order.length &&
      state.order.every(
        (key, i) => container.children[i] === state.rows.get(key)?.node,
      );
    const unchanged =
      sameScope &&
      attached &&
      order.length === state.order.length &&
      entries.every(
        (entry, i) =>
          order[i] === state.order[i] &&
          entry.version !== undefined &&
          previous.get(order[i])?.version === entry.version,
      );
    if (unchanged) {
      if (reduced() || state.generation !== generation) cancel(state);
      state.generation = generation;
      return;
    }
    const dom = typeof container.insertBefore === "function";
    const layout = dom && !document.hidden;
    const motion = dom && !reduced() && state.generation === generation;
    const { scroller, clip } = layout ? viewport(container) : {};
    const positions = new Map();
    let anchor = null;
    const focused =
      dom && container.contains(document.activeElement)
        ? document.activeElement
        : null;
    if (layout && sameScope && attached) {
      const remaining = new Set(order);
      for (const key of state.order) {
        const node = previous.get(key).node;
        const rect = node.getBoundingClientRect();
        positions.set(key, rect);
        if (!anchor && visible(rect, clip) && remaining.has(key))
          anchor = { key, rect };
      }
    }
    // Measure the current visual position before interrupting an earlier transition.
    cancel(state);
    const rows = new Map(),
      added = new Set();
    entries.forEach((entry, i) => {
      const key = order[i],
        old = attached ? previous.get(key) : null;
      let node = entry.node;
      if (old) {
        node = old.node;
        if (entry.version === undefined || old.version !== entry.version)
          node = dom ? patch(node, entry.node) : entry.node;
      } else if (!state.seen.has(scope + "\0" + key)) added.add(key);
      rows.set(key, { node, version: entry.version });
      const seenKey = scope + "\0" + key;
      state.seen.delete(seenKey);
      state.seen.set(seenKey, true);
    });
    while (state.seen.size > Math.max(6000, entries.length))
      state.seen.delete(state.seen.keys().next().value);
    if (dom) {
      const keep = new Set(Array.from(rows.values(), (row) => row.node));
      for (const child of Array.from(container.children))
        if (!keep.has(child)) child.remove();
      order.forEach((key, i) => {
        const node = rows.get(key).node;
        if (container.children[i] !== node) {
          const before = container.children[i] || null;
          if (container.moveBefore && node.parentElement === container)
            container.moveBefore(node, before);
          else container.insertBefore(node, before);
        }
      });
    } else
      container.replaceChildren(
        ...Array.from(rows.values(), (row) => row.node),
      );
    state.rows = rows;
    state.order = order;
    state.scope = scope;
    state.generation = generation;
    if (focused?.isConnected && document.activeElement !== focused)
      focused.focus({ preventScroll: true });
    if (!layout) return;
    // Keep the item being read in place; at the start of the list, follow arrivals.
    if (
      anchor &&
      scroller &&
      (scroller.scrollTop > 2 || scroller.scrollLeft > 2)
    ) {
      const now = rows.get(anchor.key).node.getBoundingClientRect();
      scroller.scrollTop += now.top - anchor.rect.top;
      scroller.scrollLeft += now.left - anchor.rect.left;
    }
    if (!motion) return;
    const currentClip = viewport(container).clip;
    const after = new Map();
    for (const key of order) {
      if (positions.has(key) || added.has(key))
        after.set(key, rows.get(key).node.getBoundingClientRect());
    }
    // The new leading block and all existing rows travel by the same distance.
    const firstRetained = order.find(
      (key) => positions.has(key) && after.has(key),
    );
    const retainedDelta = firstRetained && {
      x: positions.get(firstRetained).left - after.get(firstRetained).left,
      y: positions.get(firstRetained).top - after.get(firstRetained).top,
    };
    for (const [key, rect] of after) {
      const node = rows.get(key).node,
        old = positions.get(key);
      if (old && (visible(rect, currentClip) || visible(old, clip))) {
        const x = old.left - rect.left,
          y = old.top - rect.top;
        if (Math.abs(x) > 0.5 || Math.abs(y) > 0.5)
          animate(state, node, [
            { transform: `translate(${x}px, ${y}px)` },
            { transform: "translate(0, 0)" },
          ]);
      } else if (added.has(key)) {
        const leading =
          firstRetained && order.indexOf(key) < order.indexOf(firstRetained);
        const delta =
          leading && retainedDelta
            ? retainedDelta
            : {
                x: 0,
                y: sameScope && previous.size ? -Math.min(rect.height, 32) : -6,
              };
        const path = {
          top: Math.min(rect.top, rect.top + delta.y),
          bottom: Math.max(rect.bottom, rect.bottom + delta.y),
          left: Math.min(rect.left, rect.left + delta.x),
          right: Math.max(rect.right, rect.right + delta.x),
        };
        if (visible(path, currentClip))
          animate(state, node, [
            { opacity: 0, transform: `translate(${delta.x}px, ${delta.y}px)` },
            { opacity: 1, transform: "translate(0, 0)" },
          ]);
      }
    }
  }
  return { render };
})();
