"use strict";
const $ = (id) => document.getElementById(id);
let nonce = "",
  view = location.hash === "#events" ? "events" : "requests";
let offset = 0,
  busy = false,
  queued = false,
  connected = false,
  selected = null,
  detailVersion = 0;
let visibleEvents = [];
function element(tag, cls, text) {
  const item = document.createElement(tag);
  item.className = cls;
  if (text !== undefined) item.textContent = text;
  return item;
}
function error(message) {
  $("log-error").textContent = message;
  $("log-error").hidden = !message;
}
function clock(timestamp, fallback = "") {
  return timestamp
    ? new Date(timestamp * 1000).toLocaleString("ru-RU")
    : fallback;
}
async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(10000),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Ошибка загрузки журнала");
  return value;
}
function format(row) {
  if (view === "events")
    return [
      clock(row.timestamp, row.time),
      row.level || "info",
      row.message,
      row.file,
      row.reason,
      row.detail,
    ]
      .filter(Boolean)
      .join("\n\n");
  if (row.type === "tls")
    return [
      "TLS · " + row.side,
      row.host,
      row.tls_version,
      clock(row.timestamp),
      row.error || "Соединение установлено",
    ]
      .filter(Boolean)
      .join("\n");
  const headers = (values) =>
    (values || []).map(([key, value]) => key + ": " + value).join("\n");
  return [
    clock(row.timestamp),
    `${row.method} ${row.url} ${row.http_version}`,
    headers(row.request_headers),
    row.status
      ? `${row.response_version} ${row.status} ${row.reason || ""}`
      : "Ответ ещё не получен",
    headers(row.response_headers),
    row.source === "local"
      ? "Ответ сформирован локальным прокси"
      : "Ответ сервера",
    row.duration_ms !== undefined
      ? `Длительность: ${row.duration_ms} мс`
      : "Запрос выполняется",
    row.error,
    row.headers_truncated ? "Часть заголовков обрезана по лимиту размера" : "",
    row.original_available === false
      ? "После перезапуска доступна только сохранённая версия со скрытыми токенами."
      : "",
    "Тело запроса и ответа не записывается.",
  ]
    .filter(Boolean)
    .join("\n\n");
}
async function details() {
  const version = ++detailVersion,
    identity = selected;
  $("original").textContent = "";
  if (!identity) return;
  try {
    const row =
      view === "events"
        ? visibleEvents.find((row) => row.id === identity)
        : await json("/api/request-detail", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Panel-Nonce": nonce,
            },
            body: JSON.stringify({ id: identity, reveal: !$("mask").checked }),
          });
    if (version !== detailVersion || identity !== selected) return;
    if (!row) throw new Error("Запись больше не доступна");
    $("original").textContent = format(row);
    $("detail-title").textContent =
      view === "events"
        ? "Событие"
        : $("mask").checked
          ? "Запрос · токены скрыты"
          : "Запрос · оригинал";
  } catch (exc) {
    if (version === detailVersion) error(exc.message);
  }
}
function render(rows, total, dropped = 0) {
  const container = $("records");
  container.replaceChildren();
  for (const row of rows) {
    const button = element(
      "button",
      "log-record" + (row.id === selected ? " selected" : ""),
    );
    const meta = element("div", "record-meta");
    meta.append(element("span", "", clock(row.timestamp, row.time)));
    const failed =
      row.error ||
      row.status >= 400 ||
      row.level === "error" ||
      row.level === "warning";
    meta.append(
      element(
        "span",
        failed ? "failure" : "success",
        view === "events"
          ? row.level || "info"
          : row.type === "tls"
            ? "TLS · " + row.side
            : `${row.method} · ${row.status || row.phase}`,
      ),
    );
    if (row.duration_ms !== undefined)
      meta.append(element("span", "", row.duration_ms + " мс"));
    button.append(
      meta,
      element(
        "div",
        view === "events" ? "record-message" : "record-url",
        row.message || row.url || row.host,
      ),
    );
    if (row.file) button.append(element("div", "record-file", row.file));
    button.addEventListener("click", () => {
      selected = row.id;
      details();
      container
        .querySelectorAll(".log-record")
        .forEach((item) => item.classList.toggle("selected", item === button));
    });
    container.append(button);
  }
  if (!rows.length)
    container.append(element("p", "capture-note", "Записей нет"));
  $("count").textContent =
    (total
      ? `${offset + 1}–${Math.min(offset + rows.length, total)} из ${total}`
      : "Записей нет") + (dropped ? ` · удалено по лимиту: ${dropped}` : "");
  $("previous").disabled = offset === 0;
  $("next-page").disabled = offset + rows.length >= total;
}
async function refresh() {
  if (busy) {
    queued = true;
    return;
  }
  busy = true;
  const criteria = [view, $("query").value, $("level").value, offset];
  try {
    const state = await json("/api/state");
    nonce = state.nonce;
    connected = true;
    $("connection").textContent = "Панель подключена";
    const trust =
      state.session.ca_trusted === false
        ? state.tls?.client?.ok
          ? "TLS Диска установлен; сертификат передан приложению"
          : "Сертификат не найден в Windows"
        : state.session.ca_trusted
          ? "Сертификат в доверенных"
          : "Прокси выключен";
    const side = (name) =>
      state.tls?.[name]
        ? state.tls[name].ok
          ? "TLS OK"
          : state.tls[name].error || "Ошибка TLS"
        : "нет данных";
    $("health").textContent =
      `${trust} · Диск → прокси: ${side("client")} · Прокси → Яндекс: ${side("upstream")}`;
    const result =
      view === "events"
        ? await json("/api/events")
        : await json(
            "/api/requests?" +
              new URLSearchParams({
                q: criteria[1],
                errors: criteria[2] === "errors" ? "1" : "0",
                offset: String(criteria[3]),
              }),
          );
    if (
      JSON.stringify(criteria) !==
      JSON.stringify([view, $("query").value, $("level").value, offset])
    ) {
      queued = true;
      return;
    }
    if (view === "events") {
      visibleEvents = result.rows.filter(
        (row) =>
          (criteria[2] !== "errors" ||
            ["error", "warning"].includes(row.level)) &&
          JSON.stringify(row).toLowerCase().includes(criteria[1].toLowerCase()),
      );
      offset = Math.min(
        offset,
        Math.max(0, Math.floor((visibleEvents.length - 1) / 100) * 100),
      );
      render(visibleEvents.slice(offset, offset + 100), visibleEvents.length);
    } else {
      offset = result.offset;
      render(result.rows, result.total, result.dropped);
    }
    error(state.log_error || result.error || "");
  } catch (exc) {
    connected = false;
    $("connection").textContent = "Нет связи с панелью";
    error(exc.message);
  } finally {
    busy = false;
    if (queued) {
      queued = false;
      queueMicrotask(refresh);
    }
  }
}
function switchView(next) {
  view = next;
  offset = 0;
  selected = null;
  ++detailVersion;
  $("original").textContent = "";
  $("detail-title").textContent = "Выберите запись";
  $("mask-label").hidden = view === "events";
  $("capture-note").hidden = view === "events";
  $("tab-requests").classList.toggle("active", view === "requests");
  $("tab-events").classList.toggle("active", view === "events");
  refresh();
}
$("tab-requests").addEventListener("click", () => switchView("requests"));
$("tab-events").addEventListener("click", () => switchView("events"));
$("query").addEventListener("input", () => {
  offset = 0;
  refresh();
});
$("level").addEventListener("change", () => {
  offset = 0;
  refresh();
});
$("mask").addEventListener("change", details);
$("pause").addEventListener("change", () => {
  if (!$("pause").checked) refresh();
});
$("previous").addEventListener("click", () => {
  offset = Math.max(0, offset - 100);
  refresh();
});
$("next-page").addEventListener("click", () => {
  offset += 100;
  refresh();
});
switchView(view);
setInterval(() => {
  if (!$("pause").checked) refresh();
}, 2000);
window.addEventListener("pagehide", () => {
  $("original").textContent = "";
  $("mask").checked = true;
  ++detailVersion;
});
