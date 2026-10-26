"use strict";
const Thumbnails = (() => {
  const extensions = new Set(
    "jpg jpeg png gif bmp webp tif tiff heic heif avif mp4 mov m4v avi mkv webm 3gp pdf".split(
      " ",
    ),
  );
  const frames = new Map();
  const listeners = new Set();
  let nonce = "",
    enabled = I18n.preferences.get("thumbnails", true),
    context = "",
    available = false,
    generation = 0,
    active = 0;
  function release(entry) {
    entry.image?.remove();
    entry.loadingImage?.remove();
    if (entry.url) URL.revokeObjectURL(entry.url);
    if (entry.loadingUrl) URL.revokeObjectURL(entry.loadingUrl);
    entry.image = entry.url = null;
    entry.loadingImage = entry.loadingUrl = null;
  }
  function reset() {
    generation++;
    for (const entry of frames.values()) {
      entry.controller?.abort();
      release(entry);
      entry.node.title = "";
      observer?.unobserve(entry.node);
    }
    frames.clear();
  }
  async function load(entry) {
    active++;
    const current = generation;
    const controller = new AbortController();
    entry.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 18000);
    try {
      const response = await fetch("/api/thumbnail", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Panel-Nonce": nonce },
        body: JSON.stringify({ file: entry.path, context }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const error = new Error();
        error.retry = Math.max(
          2,
          Math.min(600, Number(response.headers.get("Retry-After")) || 60),
        );
        throw error;
      }
      const blob = await response.blob();
      if (
        blob.size > 262144 ||
        !["image/jpeg", "image/png", "image/webp"].includes(blob.type)
      )
        throw new Error();
      if (
        generation !== current ||
        frames.get(entry.node) !== entry ||
        !entry.node.isConnected ||
        !entry.visible ||
        document.hidden
      )
        return;
      const url = URL.createObjectURL(blob);
      const image = document.createElement("img");
      image.className = "thumbnail-image";
      image.alt = "";
      image.decoding = "async";
      entry.loadingImage = image;
      entry.loadingUrl = url;
      entry.nextTry = Date.now() + 300000;
      entry.error = false;
      entry.node.title = "";
      if (entry.image) image.style.transition = "none";
      image.onload = () => {
        if (entry.loadingUrl !== url) return;
        entry.image?.remove();
        if (entry.url) URL.revokeObjectURL(entry.url);
        entry.image = image;
        entry.url = url;
        entry.loadingImage = entry.loadingUrl = null;
        entry.node.append(image);
        requestAnimationFrame(() => image.classList.add("ready"));
      };
      image.onerror = () => {
        if (entry.loadingUrl !== url) return;
        release(entry);
        entry.nextTry = Date.now() + 60000;
      };
      image.src = url;
    } catch (error) {
      if (generation === current && !controller.signal.aborted) {
        entry.nextTry = Date.now() + (error.retry || 60) * 1000;
        entry.error = true;
        entry.node.title = I18n.t("Миниатюра недоступна");
      }
    } finally {
      clearTimeout(timeout);
      entry.controller = null;
      active--;
      pump();
    }
  }
  function pump() {
    if (
      !enabled ||
      !observer ||
      !available ||
      !nonce ||
      !context ||
      document.hidden
    )
      return;
    for (const entry of frames.values()) {
      if (active >= 2) break;
      if (
        entry.visible &&
        entry.node.isConnected &&
        !entry.controller &&
        entry.nextTry <= Date.now()
      )
        load(entry);
    }
  }
  const observer =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver(
          (changes) => {
            for (const change of changes) {
              const entry = frames.get(change.target);
              if (!entry) continue;
              entry.visible = change.isIntersecting;
              if (!entry.visible && (entry.url || entry.loadingUrl)) {
                release(entry);
                entry.nextTry = 0;
              }
            }
            pump();
          },
          { threshold: 0 },
        )
      : null;
  function decorate(node, row) {
    const extension = String(row.path || "")
      .split(".")
      .pop()
      .toLowerCase();
    if (!extensions.has(extension)) return;
    node.setAttribute(
      "data-thumbnail",
      JSON.stringify([row.path, row.size || 0]),
    );
    node.classList.add("thumbnail-frame");
  }
  function sync(container) {
    if (!enabled) return;
    for (const [node, entry] of frames) {
      if (
        !node.isConnected ||
        entry.key !== node.getAttribute("data-thumbnail")
      ) {
        entry.controller?.abort();
        release(entry);
        observer?.unobserve(node);
        frames.delete(node);
      } else if (entry.error) node.title = I18n.t("Миниатюра недоступна");
    }
    for (const node of container.querySelectorAll("[data-thumbnail]")) {
      if (frames.has(node)) continue;
      const [path] = JSON.parse(node.getAttribute("data-thumbnail"));
      frames.set(node, {
        node,
        path,
        key: node.getAttribute("data-thumbnail"),
        visible: false,
        nextTry: 0,
        controller: null,
        image: null,
        url: null,
      });
      observer?.observe(node);
    }
    pump();
  }
  function configure(state) {
    if (context !== state.preview_context) {
      reset();
      context = state.preview_context || "";
    }
    nonce = state.nonce || "";
    available = !!(
      state.preview?.credentials_seen || state.preview?.account_verified
    );
    pump();
  }
  I18n.preferences.onChange((key, value) => {
    if (key !== "thumbnails" || enabled === (value !== false)) return;
    enabled = value !== false;
    reset();
    if (enabled) sync(document);
    listeners.forEach((listener) => listener(enabled));
  });
  document.addEventListener("visibilitychange", () => {
    for (const entry of frames.values()) {
      if (document.hidden) {
        entry.controller?.abort();
        if (entry.url || entry.loadingUrl) entry.nextTry = 0;
        release(entry);
        entry.visible = false;
        observer?.unobserve(entry.node);
      } else observer?.observe(entry.node);
    }
  });
  window.addEventListener("pagehide", reset);
  window.addEventListener("pageshow", () => sync(document));
  setInterval(pump, 3000);
  return {
    decorate,
    sync,
    configure,
    get enabled() {
      return enabled;
    },
    setEnabled(value) {
      I18n.preferences.set("thumbnails", !!value);
    },
    onChange(listener) {
      listeners.add(listener);
    },
  };
})();
