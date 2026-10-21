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
let operationLabels = {},
  anomalyLabels = {},
  optionsReady = false;
const phases = {
  request: "Начат",
  response: "Ответ",
  progress: "Передача",
  connected: "Подключено",
  complete: "Завершён",
  error: "Ошибка",
  interrupted: "Нет завершения",
};
function bytes(n) {
  n = Number(n) || 0;
  let index = 0;
  const units = ["Б", "КБ", "МБ", "ГБ"];
  while (n >= 1024 && index < 3) {
    n /= 1024;
    index++;
  }
  return (
    new Intl.NumberFormat("ru", {
      maximumFractionDigits: index ? 1 : 0,
    }).format(n) +
    " " +
    units[index]
  );
}
function renderSummary(data) {
  const t = data.totals;
  $("summary-total").textContent = (t.http || 0).toLocaleString("ru-RU");
  $("summary-errors").textContent = t.http_errors || 0;
  $("summary-unknown").textContent = t.unknown || 0;
  $("summary-dropped").textContent = data.capture_dropped || 0;
  $("summary-since").textContent = "С " + clock(data.since);
  $("summary-active").textContent = "Выполняются: " + data.active;
  $("summary-files").textContent = "Изменений файлов: " + (t.file || 0);
  $("summary-retained").textContent =
    "В памяти: " + data.retained + " · удалено по лимиту: " + data.evicted;
  for (const [id, rows] of [
    ["operation-rows", data.operations],
    ["endpoint-rows", data.endpoints],
  ]) {
    const entries = [];
    for (const row of rows) {
      const tr = element("tr", ""),
        cell = element("td", "");
      if (row.operation) {
        const b = element("button", "operation-link", row.label);
        b.addEventListener("click", () => {
          $("operation").value = row.operation;
          $("kind").value = "";
          switchView("requests");
        });
        cell.append(b);
      } else cell.textContent = row.endpoint;
      tr.append(cell);
      for (const value of [
        row.count,
        row.errors,
        row.retries,
        `${row.average_ms} / ${row.max_ms} мс`,
        `${bytes(row.sent_bytes)} / ${bytes(row.received_bytes)}`,
      ])
        tr.append(element("td", "", value));
      entries.push({ key: row.operation || row.endpoint, node: tr });
    }
    ListMotion.render($(id), entries);
  }
}
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
  if (["connection", "websocket", "file"].includes(row.type))
    return [
      clock(row.timestamp),
      row.operation_label,
      row.file,
      row.host ? row.host + ":" + (row.port || "") : "",
      `Состояние: ${phases[row.phase] || row.phase}`,
      row.side,
      row.connection_id ? "Соединение: " + row.connection_id : "",
      row.client_connection
        ? "Клиентское соединение: " + row.client_connection
        : "",
      row.peer_address ? "Адрес: " + row.peer_address.join(":") : "",
      row.size !== undefined ? "Размер: " + bytes(row.size) : "",
      row.before_size !== undefined
        ? "Прежний размер: " + bytes(row.before_size)
        : "",
      row.duration_ms !== undefined
        ? "Длительность: " + row.duration_ms + " мс"
        : "",
      row.messages !== undefined ? "Сообщений WebSocket: " + row.messages : "",
      row.close_code !== undefined ? "Код закрытия: " + row.close_code : "",
      row.sent_bytes !== undefined
        ? "Отправлено: " + bytes(row.sent_bytes)
        : "",
      row.received_bytes !== undefined
        ? "Получено: " + bytes(row.received_bytes)
        : "",
      row.error,
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
    row.operation_label,
    [row.method, row.url, row.http_version].filter(Boolean).join(" "),
    headers(row.request_headers),
    row.status
      ? [row.response_version, row.status, row.reason].filter(Boolean).join(" ")
      : "Ответ ещё не получен",
    headers(row.response_headers),
    row.source === "local"
      ? "Ответ сформирован локальным прокси"
      : "Ответ сервера",
    row.duration_ms !== undefined
      ? `Длительность: ${row.duration_ms} мс`
      : phases[row.phase] || "Запрос выполняется",
    row.route
      ? `Маршрут: ${row.client === "recovery" ? "прямая загрузка" : "Диск через прокси"}`
      : "",
    row.headers_ms !== undefined ? `Заголовки: ${row.headers_ms} мс` : "",
    row.first_byte_ms !== undefined
      ? `Первый байт: ${row.first_byte_ms} мс`
      : "",
    row.received_bytes !== undefined
      ? `Получено: ${row.received_bytes} байт`
      : "",
    row.sent_bytes !== undefined ? `Отправлено: ${row.sent_bytes} байт` : "",
    row.expected_bytes !== undefined
      ? `Content-Length ответа: ${row.expected_bytes} байт`
      : "",
    row.connect_ms !== undefined
      ? `Подключение (DNS и TCP): ${row.connect_ms} мс`
      : "",
    row.tls_ms !== undefined ? `TLS: ${row.tls_ms} мс` : "",
    row.alpn ? `ALPN: ${row.alpn}` : "",
    row.attempt
      ? `Обращение №${row.attempt}` +
        (row.retry_after_error ? " · после ошибки" : "")
      : "",
    row.parent_request
      ? `Предыдущий запрос: ${row.parent_request} · переходов: ${row.redirect_hops || 0}`
      : "",
    row.server_connection
      ? `Соединение с сервером: ${row.server_connection}`
      : "",
    row.client_connection ? `Соединение клиента: ${row.client_connection}` : "",
    row.anomalies?.length
      ? row.anomalies.map((a) => anomalyLabels[a] || a).join(" · ")
      : "",
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
  const entries = [];
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
            : row.type === "file"
              ? "Windows"
              : `${row.method || (row.type === "websocket" ? "WebSocket" : "TCP")} · ${row.status || phases[row.phase] || row.phase}`,
      ),
    );
    if (row.duration_ms !== undefined)
      meta.append(element("span", "", row.duration_ms + " мс"));
    button.append(
      meta,
      element(
        "div",
        view === "events" ? "record-message" : "record-url",
        row.message || row.url || row.host || row.operation_label,
      ),
    );
    if (row.file) button.append(element("div", "record-file", row.file));
    if (view !== "events" && row.type !== "file" && row.operation_label)
      meta.append(element("span", "", row.operation_label));
    if (row.anomalies?.length)
      button.append(
        element(
          "div",
          "record-anomaly",
          row.anomalies.map((a) => anomalyLabels[a] || a).join(" · "),
        ),
      );
    button.addEventListener("click", () => {
      selected = row.id;
      details();
      container
        .querySelectorAll(".log-record")
        .forEach((item) => item.classList.toggle("selected", item === button));
    });
    entries.push({ key: row.id, node: button });
  }
  if (!rows.length)
    entries.push({
      key: "empty",
      node: element("p", "capture-note", "Записей нет"),
    });
  ListMotion.render(container, entries, view);
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
  const criteria = [
    view,
    $("query").value,
    $("level").value,
    offset,
    $("operation").value,
    $("kind").value,
  ];
  try {
    const [state, metadata] = await Promise.all([
      json("/api/state"),
      json("/api/operations"),
    ]);
    operationLabels = metadata.labels;
    anomalyLabels = metadata.anomaly_labels;
    if (!optionsReady) {
      for (const [value, label] of Object.entries(operationLabels)) {
        const option = element("option", "", label);
        option.value = value;
        $("operation").append(option);
      }
      optionsReady = true;
    }
    nonce = state.nonce;
    connected = true;
    $("export").disabled = false;
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
    if (view === "summary") {
      renderSummary(metadata);
      error(state.log_error || "");
      return;
    }
    const result =
      view === "events"
        ? await json("/api/events")
        : await json(
            "/api/requests?" +
              new URLSearchParams({
                q: criteria[1],
                errors: criteria[2] === "errors" ? "1" : "0",
                unusual: criteria[2] === "unusual" ? "1" : "0",
                operation: criteria[4],
                kind: criteria[5],
                offset: String(criteria[3]),
              }),
          );
    if (
      JSON.stringify(criteria) !==
      JSON.stringify([
        view,
        $("query").value,
        $("level").value,
        offset,
        $("operation").value,
        $("kind").value,
      ])
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
    if (selected) details();
    error(state.log_error || result.error || "");
  } catch (exc) {
    connected = false;
    $("export").disabled = true;
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
  $("tab-summary").classList.toggle("active", view === "summary");
  $("summary").hidden = view !== "summary";
  $("workspace").hidden = view === "summary";
  for (const id of ["query", "level"]) $(id).hidden = view === "summary";
  for (const id of ["operation", "kind", "mask-label"])
    $(id).hidden = view !== "requests";
  $("capture-note").hidden = view !== "requests";
  refresh();
}
$("tab-requests").addEventListener("click", () => switchView("requests"));
$("tab-events").addEventListener("click", () => switchView("events"));
$("tab-summary").addEventListener("click", () => switchView("summary"));
for (const id of ["operation", "kind"])
  $(id).addEventListener("change", () => {
    offset = 0;
    refresh();
  });
$("export").addEventListener("click", async () => {
  if (!connected) return;
  $("export").disabled = true;
  try {
    const response = await fetch("/api/export-diagnostics", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Panel-Nonce": nonce },
      body: "{}",
      signal: AbortSignal.timeout(60000),
    });
    if (!response.ok) throw Error("Не удалось собрать архив");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "yandex-disk-diagnostics.zip";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (exc) {
    error(exc.message);
  } finally {
    $("export").disabled = false;
  }
});
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
