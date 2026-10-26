"use strict";
const LivePanel = (() => {
  const known = new Set([
    "state",
    "files",
    "events",
    "requests",
    "operations",
    "metrics",
  ]);
  function subscribe(
    refresh,
    topics,
    { paused = () => false, interval = 350 } = {},
  ) {
    const watched = topics.filter((topic) => known.has(topic));
    const pending = new Set();
    let source = null,
      timer = null,
      fallback = null,
      running = false;
    let stopped = false,
      suspended = false,
      lastRun = -interval;
    const visible = () => !stopped && !suspended && !document.hidden;
    function schedule() {
      if (!visible() || paused() || running || timer !== null || !pending.size)
        return;
      timer = setTimeout(
        run,
        Math.max(0, interval - (performance.now() - lastRun)),
      );
    }
    function request(changed = watched) {
      changed.forEach((topic) => {
        if (watched.includes(topic)) pending.add(topic);
      });
      schedule();
    }
    async function run() {
      timer = null;
      if (!visible() || paused() || running || !pending.size) return;
      const changed = Array.from(pending);
      pending.clear();
      running = true;
      lastRun = performance.now();
      try {
        await refresh(changed);
      } finally {
        running = false;
        schedule();
      }
    }
    function disconnect() {
      source?.close();
      source = null;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    }
    function connect() {
      if (!visible() || source || typeof EventSource !== "function") return;
      source = new EventSource(
        "/api/updates?" + new URLSearchParams({ topics: watched.join(",") }),
      );
      source.addEventListener("update", (event) => {
        try {
          const value = JSON.parse(event.data);
          if (Array.isArray(value.topics)) request(value.topics);
        } catch {
          /* Ignore malformed notifications; recovery polling remains available. */
        }
      });
      source.addEventListener("error", () => request());
    }
    function check() {
      if (stopped) return;
      if (visible() && (!source || source.readyState !== 1)) request();
      fallback = setTimeout(check, 5000 + Math.floor(Math.random() * 700));
    }
    function visibility() {
      if (!visible()) disconnect();
      else {
        connect();
        request();
      }
    }
    function hide() {
      suspended = true;
      disconnect();
    }
    function show() {
      suspended = false;
      visibility();
    }
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    connect();
    fallback = setTimeout(check, 5000);
    return {
      request,
      close() {
        stopped = true;
        disconnect();
        clearTimeout(fallback);
        pending.clear();
        document.removeEventListener("visibilitychange", visibility);
        window.removeEventListener("pagehide", hide);
        window.removeEventListener("pageshow", show);
      },
    };
  }
  return { subscribe };
})();
