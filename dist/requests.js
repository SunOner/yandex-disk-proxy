"use strict";
const $ = (id) => document.getElementById(id);
let nonce = "",
  view =
    location.hash === "#events"
      ? "events"
      : I18n.preferences.get("logView", "requests");
let offset = 0,
  busy = false,
  queued = false,
  connected = false,
  selected = null,
  detailVersion = 0;
let visibleEvents = [];
let lastState = null,
  lastMetadata = null,
  lastList = null,
  lastDetail = null,
  lastDetailMasked = true;
let operationLabels = {},
  anomalyLabels = {},
  optionsReady = false;
const phases = I18n.labels({
  request: "Начат",
  response: "Ответ",
  progress: "Передача",
  connected: "Подключено",
  complete: "Завершён",
  error: "Ошибка",
  interrupted: "Нет завершения",
});
function bytes(n) {
  n = Number(n) || 0;
  let index = 0;
  const units = [I18n.t("Б"), I18n.t("КБ"), I18n.t("МБ"), I18n.t("ГБ")];
  while (n >= 1024 && index < 3) {
    n /= 1024;
    index++;
  }
  return (
    new Intl.NumberFormat(I18n.locale, {
      maximumFractionDigits: index ? 1 : 0,
    }).format(n) +
    " " +
    units[index]
  );
}
function renderSummary(data) {
  lastMetadata = data;
  const t = data.totals;
  $("summary-total").textContent = (t.http || 0).toLocaleString(I18n.locale);
  $("summary-errors").textContent = t.http_errors || 0;
  $("summary-unknown").textContent = t.unknown || 0;
  $("summary-dropped").textContent = data.capture_dropped || 0;
  $("summary-since").textContent = I18n.t("С ") + clock(data.since);
  $("summary-active").textContent = I18n.t("Выполняются: ") + data.active;
  $("summary-files").textContent = I18n.t("Изменений файлов: ") + (t.file || 0);
  $("summary-retained").textContent =
    I18n.t("В памяти: ") +
    data.retained +
    I18n.t(" · удалено по лимиту: ") +
    data.evicted;
  for (const [id, rows] of [
    ["operation-rows", data.operations],
    ["endpoint-rows", data.endpoints],
  ]) {
    const entries = [];
    for (const row of rows) {
      const tr = element("tr", ""),
        cell = element("td", "");
      if (row.operation) {
        const b = element("button", "operation-link", I18n.t(row.label));
        b.onclick = () => {
          $("operation").value = row.operation;
          $("kind").value = "";
          switchView("requests");
        };
        cell.append(b);
      } else cell.textContent = row.endpoint;
      tr.append(cell);
      for (const value of [
        row.count,
        row.errors,
        row.retries,
        I18n.t("{0} / {1} мс", [row.average_ms, row.max_ms]),
        `${bytes(row.sent_bytes)} / ${bytes(row.received_bytes)}`,
      ])
        tr.append(element("td", "", value));
      entries.push({
        key: row.operation || row.endpoint,
        version: JSON.stringify([row, I18n.language]),
        node: tr,
      });
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
function clock(timestamp, fallback = "") {
  return timestamp
    ? new Date(timestamp * 1000).toLocaleString(I18n.locale)
    : fallback;
}
async function json(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(10000),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(I18n.t(value.error) || I18n.t("Ошибка загрузки журнала"));
  return value;
}
function format(row) {
  if (view === "events")
    return [
      clock(row.timestamp, row.time),
      row.level || "info",
      I18n.t(row.message),
      row.file,
      I18n.t(row.reason),
      I18n.t(row.detail),
    ]
      .filter(Boolean)
      .join("\n\n");
  if (["connection", "websocket", "file"].includes(row.type))
    return [
      clock(row.timestamp),
      I18n.t(row.operation_label),
      row.file,
      row.host ? row.host + ":" + (row.port || "") : "",
      I18n.t("Состояние: {0}", [phases[row.phase] || row.phase]),
      row.side,
      row.connection_id ? I18n.t("Соединение: ") + row.connection_id : "",
      row.client_connection
        ? I18n.t("Клиентское соединение: ") + row.client_connection
        : "",
      row.peer_address ? I18n.t("Адрес: ") + row.peer_address.join(":") : "",
      row.size !== undefined ? I18n.t("Размер: ") + bytes(row.size) : "",
      row.before_size !== undefined
        ? I18n.t("Прежний размер: ") + bytes(row.before_size)
        : "",
      row.duration_ms !== undefined
        ? I18n.t("Длительность: ") + row.duration_ms + I18n.t(" мс")
        : "",
      row.messages !== undefined
        ? I18n.t("Сообщений WebSocket: ") + row.messages
        : "",
      row.close_code !== undefined
        ? I18n.t("Код закрытия: ") + row.close_code
        : "",
      row.sent_bytes !== undefined
        ? I18n.t("Отправлено: ") + bytes(row.sent_bytes)
        : "",
      row.received_bytes !== undefined
        ? I18n.t("Получено: ") + bytes(row.received_bytes)
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
      row.error || I18n.t("Соединение установлено"),
    ]
      .filter(Boolean)
      .join("\n");
  const headers = (values) =>
    (values || []).map(([key, value]) => key + ": " + value).join("\n");
  return [
    clock(row.timestamp),
    I18n.t(row.operation_label),
    [row.method, row.url, row.http_version].filter(Boolean).join(" "),
    headers(row.request_headers),
    row.status
      ? [row.response_version, row.status, row.reason].filter(Boolean).join(" ")
      : I18n.t("Ответ ещё не получен"),
    headers(row.response_headers),
    row.source === "local"
      ? I18n.t("Ответ сформирован локальным прокси")
      : I18n.t("Ответ сервера"),
    row.duration_ms !== undefined
      ? I18n.t("Длительность: {0} мс", [row.duration_ms])
      : phases[row.phase] || I18n.t("Запрос выполняется"),
    row.route
      ? I18n.t("Маршрут: {0}", [
          row.client === "recovery"
            ? I18n.t("прямая загрузка")
            : I18n.t("Диск через прокси"),
        ])
      : "",
    row.headers_ms !== undefined
      ? I18n.t("Заголовки: {0} мс", [row.headers_ms])
      : "",
    row.first_byte_ms !== undefined
      ? I18n.t("Первый байт: {0} мс", [row.first_byte_ms])
      : "",
    row.received_bytes !== undefined
      ? I18n.t("Получено: {0} байт", [row.received_bytes])
      : "",
    row.sent_bytes !== undefined
      ? I18n.t("Отправлено: {0} байт", [row.sent_bytes])
      : "",
    row.expected_bytes !== undefined
      ? I18n.t("Content-Length ответа: {0} байт", [row.expected_bytes])
      : "",
    row.connect_ms !== undefined
      ? I18n.t("Подключение (DNS и TCP): {0} мс", [row.connect_ms])
      : "",
    row.tls_ms !== undefined ? I18n.t("TLS: {0} мс", [row.tls_ms]) : "",
    row.alpn ? `ALPN: ${row.alpn}` : "",
    row.attempt
      ? I18n.t("Обращение №{0}", [row.attempt]) +
        (row.retry_after_error ? I18n.t(" · после ошибки") : "")
      : "",
    row.parent_request
      ? I18n.t("Предыдущий запрос: {0} · переходов: {1}", [
          row.parent_request,
          row.redirect_hops || 0,
        ])
      : "",
    row.server_connection
      ? I18n.t("Соединение с сервером: {0}", [row.server_connection])
      : "",
    row.client_connection
      ? I18n.t("Соединение клиента: {0}", [row.client_connection])
      : "",
    row.anomalies?.length
      ? row.anomalies.map((a) => anomalyLabels[a] || a).join(" · ")
      : "",
    row.error,
    row.headers_truncated
      ? I18n.t("Часть заголовков обрезана по лимиту размера")
      : "",
    row.original_available === false
      ? I18n.t(
          "После перезапуска доступна только сохранённая версия со скрытыми токенами.",
        )
      : "",
    I18n.t("Тело запроса и ответа не записывается."),
  ]
    .filter(Boolean)
    .join("\n\n");
}
async function details() {
  const version = ++detailVersion,
    identity = selected;
  $("original").textContent = "";
  const masked = $("mask").checked;
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
            body: JSON.stringify({ id: identity, reveal: !masked }),
          });
    if (version !== detailVersion || identity !== selected) return;
    if (!row) throw new Error(I18n.t("Запись больше не доступна"));
    Toasts.problem("request-details", "");
    lastDetail = row;
    lastDetailMasked = masked;
    $("original").textContent = format(row);
    $("detail-title").textContent =
      view === "events"
        ? I18n.t("Событие")
        : $("mask").checked
          ? I18n.t("Запрос · токены скрыты")
          : I18n.t("Запрос · оригинал");
  } catch (exc) {
    if (version === detailVersion)
      Toasts.problem("request-details", exc.message);
  }
}
function render(rows, total, dropped = 0) {
  lastList = { rows, total, dropped, view };
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
      meta.append(element("span", "", row.duration_ms + I18n.t(" мс")));
    button.append(
      meta,
      element(
        "div",
        view === "events" ? "record-message" : "record-url",
        I18n.t(row.message) ||
          row.url ||
          row.host ||
          I18n.t(row.operation_label),
      ),
    );
    if (row.file) button.append(element("div", "record-file", row.file));
    if (view !== "events" && row.type !== "file" && I18n.t(row.operation_label))
      meta.append(element("span", "", I18n.t(row.operation_label)));
    if (row.anomalies?.length)
      button.append(
        element(
          "div",
          "record-anomaly",
          row.anomalies.map((a) => anomalyLabels[a] || a).join(" · "),
        ),
      );
    button.onclick = (event) => {
      Toasts.problem("request-details", "");
      selected = row.id;
      details();
      container
        .querySelectorAll(".log-record")
        .forEach((item) =>
          item.classList.toggle("selected", item === event.currentTarget),
        );
    };
    entries.push({
      key: row.id,
      version: JSON.stringify([row, I18n.language, selected]),
      node: button,
    });
  }
  if (!rows.length)
    entries.push({
      key: "empty",
      version: I18n.language,
      node: element("p", "capture-note", I18n.t("Записей нет")),
    });
  ListMotion.render(
    container,
    entries,
    JSON.stringify([
      view,
      $("query").value,
      $("level").value,
      $("operation").value,
      $("kind").value,
      offset,
    ]),
  );
  $("count").textContent =
    (total
      ? I18n.t("{0}–{1} из {2}", [
          offset + 1,
          Math.min(offset + rows.length, total),
          total,
        ])
      : I18n.t("Записей нет")) +
    (dropped ? I18n.t(" · удалено по лимиту: {0}", [dropped]) : "");
  $("previous").disabled = offset === 0;
  $("next-page").disabled = offset + rows.length >= total;
}
function renderHealth(state, fresh = true) {
  nonce = state.nonce;
  if (fresh) connected = true;
  $("export").disabled = !connected;
  $("connection").textContent = connected
    ? I18n.t("Панель подключена")
    : I18n.t("Нет связи с панелью");
  const trust =
    state.session.certificate_scope === "client" &&
    state.session.phase === "active"
      ? state.session.certificate_ready
        ? I18n.t("Сертификат передан только Диску")
        : I18n.t("Файл сертификата недоступен или изменён")
      : state.session.ca_trusted === false
        ? state.tls?.client?.ok
          ? I18n.t("TLS Диска установлен; сертификат передан приложению")
          : I18n.t("Сертификат не найден в Windows")
        : state.session.ca_trusted
          ? I18n.t("Сертификат в доверенных")
          : I18n.t("Прокси выключен");
  const side = (name) =>
    state.tls?.[name]
      ? state.tls[name].ok
        ? "TLS OK"
        : state.tls[name].error || I18n.t("Ошибка TLS")
      : I18n.t("нет данных");
  $("health").textContent = I18n.t(
    "{0} · Диск → прокси: {1} · Прокси → Яндекс: {2}",
    [trust, side("client"), side("upstream")],
  );
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
    lastState = state;
    lastMetadata = metadata;
    operationLabels = I18n.labels(metadata.labels);
    anomalyLabels = I18n.labels(metadata.anomaly_labels);
    if (!optionsReady) {
      for (const [value, label] of Object.entries(operationLabels)) {
        const option = element("option", "", label);
        option.value = value;
        $("operation").append(option);
      }
      optionsReady = true;
    }
    renderHealth(state);
    if (view === "summary") {
      renderSummary(metadata);
      Toasts.problem("journal", state.log_error);
      Toasts.problem("connection", "");
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
    Toasts.problem("journal", state.log_error || result.error);
    Toasts.problem("connection", "");
  } catch (exc) {
    connected = false;
    $("export").disabled = true;
    $("connection").textContent = I18n.t("Нет связи с панелью");
    Toasts.problem(
      "connection",
      I18n.t("Не удалось обновить журнал. ") + exc.message,
    );
  } finally {
    busy = false;
    if (queued) {
      queued = false;
      queueMicrotask(refresh);
    }
  }
}
function switchView(next) {
  I18n.preferences.set("logView", next);
  view = next;
  offset = 0;
  selected = null;
  Toasts.problem("request-details", "");
  ++detailVersion;
  $("original").textContent = "";
  $("detail-title").textContent = I18n.t("Выберите запись");
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
    if (!response.ok) throw Error(I18n.t("Не удалось собрать архив"));
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "yandex-disk-proxy-diagnostics.zip";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    Toasts.show(I18n.t("Архив диагностики передан браузеру для сохранения."), {
      type: "success",
    });
  } catch (exc) {
    Toasts.show(exc.message, { type: "error" });
  } finally {
    $("export").disabled = !connected;
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
for (const [id, key] of [
  ["level", "logLevel"],
  ["kind", "logKind"],
]) {
  $(id).value = I18n.preferences.get(key, id === "level" ? "all" : "");
  $(id).addEventListener("change", () =>
    I18n.preferences.set(key, $(id).value),
  );
}
I18n.onChange(() => {
  if (lastState) renderHealth(lastState, false);
  if (lastMetadata) renderSummary(lastMetadata);
  for (const option of $("operation").options)
    option.textContent = I18n.t(option.textContent);
  if (lastList?.view === view)
    render(lastList.rows, lastList.total, lastList.dropped);
  if (
    selected &&
    lastDetail?.id === selected &&
    lastDetailMasked === $("mask").checked
  )
    $("original").textContent = format(lastDetail);
  $("detail-title").textContent = I18n.t($("detail-title").textContent);
});
switchView(view);
LivePanel.subscribe(refresh, ["state", "events", "requests", "operations"], {
  paused: () => $("pause").checked,
});
window.addEventListener("pagehide", () => {
  lastDetail = null;
  $("original").textContent = "";
  $("mask").checked = true;
  ++detailVersion;
});
