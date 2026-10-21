"use strict";
let snapshot = null,
  offset = 0,
  total = 0,
  filter = I18n.preferences.get("fileFilter", "pending"),
  search = "",
  busy = false,
  refreshQueued = false,
  connected = false,
  visibleDownloads = 60,
  downloadedTotal = null;
let lastRows = null,
  detailRow = null;
const $ = (id) => document.getElementById(id);
const labels = I18n.labels({
  waiting: "Ожидает",
  local: "На компьютере",
  requesting: "Запрос ссылки",
  downloading: "Загружается",
  http500: "Ошибка 500",
  deferred: "Отложен",
  deferring: "Откладывается",
  restoring: "Возврат в очередь",
  cooldown: "Пауза повторов",
  error: "Ошибка",
});
function bytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + I18n.t(" Б");
  let units = [I18n.t("КБ"), I18n.t("МБ"), I18n.t("ГБ"), I18n.t("ТБ")],
    i = -1;
  do {
    n /= 1024;
    i++;
  } while (n >= 1024 && i < units.length - 1);
  return (
    new Intl.NumberFormat(I18n.locale, {
      maximumFractionDigits: n < 10 ? 1 : 0,
    }).format(n) +
    " " +
    units[i]
  );
}
function number(n) {
  return new Intl.NumberFormat(I18n.locale).format(n || 0);
}
function node(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function toast(text, type = "error") {
  const dialog = document.querySelector("dialog[open]");
  const error = type === "error" && dialog?.querySelector(".dialog-error");
  if (error) {
    error.textContent = I18n.t(text);
    error.hidden = false;
    return;
  }
  Toasts.show(text, { type });
}
async function action(path, data = {}) {
  if (!snapshot || !connected) throw new Error(I18n.t("Нет связи с панелью"));
  const r = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Panel-Nonce": snapshot.nonce,
    },
    body: JSON.stringify(data),
  });
  const value = await r.json();
  if (!r.ok) throw new Error(I18n.t(value.error) || I18n.t("Ошибка действия"));
  return value;
}
function sessionView(s) {
  const phase = s.session.phase,
    active = phase === "active",
    working = ["starting", "stopping"].includes(phase);
  $("session-led").className =
    "session-led" + (active ? " active" : working ? " working" : "");
  $("session-title").textContent = active
    ? I18n.t("Прокси включён")
    : phase === "starting"
      ? I18n.t("Запуск прокси")
      : phase === "stopping"
        ? I18n.t("Восстанавливается клиент")
        : phase === "cleanup_required"
          ? I18n.t("Ошибка восстановления")
          : I18n.t("Прокси выключен");
  $("start").disabled = active || working;
  $("settings").disabled = active || working;
  $("rescan").disabled = !!s.inventory?.scanning || !s.configured;
  $("rescan").textContent = s.inventory?.scanning
    ? I18n.t("Обновление списка…")
    : I18n.t("Обновить список");
  $("rescan").title = s.inventory?.updated_at
    ? I18n.t("Последнее обновление: ") +
      new Date(s.inventory.updated_at * 1000).toLocaleTimeString(I18n.locale) +
      I18n.t(". Автоматически каждые 10 секунд.")
    : I18n.t("Проверить отметки хранения в Windows");
  $("mode").disabled = working;
  $("start").textContent =
    phase === "cleanup_required"
      ? I18n.t("↺ Восстановить")
      : I18n.t("▶ Включить прокси");
  $("stop").disabled = !(active || phase === "starting");
  if (document.activeElement !== $("mode")) $("mode").value = s.mode;
  const clientScope = s.session.certificate_scope === "client";
  const missing =
    active &&
    (clientScope
      ? s.session.certificate_ready === false
      : s.session.ca_trusted === false && s.tls?.client?.ok !== true);
  const clientError = active && s.tls?.client?.ok === false;
  const upstreamError = active && s.tls?.upstream?.ok === false;
  const problem =
    missing ||
    clientError ||
    upstreamError ||
    s.log_error ||
    s.session.error_detail;
  $("tls-warning").hidden = !problem;
  $("tls-message").textContent = missing
    ? clientScope
      ? I18n.t("Файл сертификата Диска недоступен или изменён.")
      : I18n.t("Сертификат больше не находится в доверенных Windows.")
    : clientError
      ? I18n.t("Диск отклонил TLS-соединение. Причина — в журнале.")
      : upstreamError
        ? I18n.t("Ошибка TLS между прокси и Яндексом. Причина — в журнале.")
        : I18n.t(s.log_error || s.session.error_detail) || "";
  $("repair-ca").hidden = !missing || clientScope;
  $("restart-client").hidden = !clientError || missing;
}
function showDetails(row, open = true) {
  detailRow = row;
  $("detail-name").textContent = row.name;
  $("detail-path").textContent = row.path;
  const list = $("detail-values");
  list.replaceChildren();
  const values = [
    [I18n.t("Состояние"), labels[row.status] || row.status],
    [I18n.t("Размер"), bytes(row.size)],
    [
      I18n.t("Загрузка подтверждена"),
      row.downloaded_at
        ? new Date(row.downloaded_at).toLocaleString(I18n.locale)
        : I18n.t("Нет данных"),
    ],
    [
      I18n.t("Подключение при завершении"),
      row.downloaded_at
        ? row.downloaded_via_proxy === null
          ? I18n.t("Между запусками панели")
          : row.downloaded_via_proxy
            ? I18n.t("Через прокси")
            : I18n.t("Напрямую")
        : "—",
    ],
    [I18n.t("Подтверждено Windows"), bytes(row.validated)],
    [I18n.t("Передано по сети"), bytes(row.network_bytes)],
    [I18n.t("Запросов ссылки"), number(row.attempts)],
    [I18n.t("Ответов HTTP 500"), number(row.http500)],
    [I18n.t("Повторов ограничено"), number(row.blocked)],
    [I18n.t("Последний сервер"), row.last_host || "—"],
    [I18n.t("Ответ API ссылки"), row.api_http || "—"],
    [I18n.t("HTTP выдачи файла"), row.download_http || "—"],
    [I18n.t("Последнее событие"), row.last_time || "—"],
  ];
  for (const [title, value] of values) {
    list.append(node("dt", "", title), node("dd", "", value));
  }
  if (open) $("details").showModal();
}
function renderRows(data) {
  lastRows = data;
  total = data.total;
  offset = data.offset;
  const body = $("files");
  const entries = [];
  for (const row of data.rows) {
    const tr = node("tr");
    const cell = node("td");
    const title = node("div", "file-title");
    const extension = row.name.includes(".")
      ? row.name.split(".").pop().slice(0, 4).toUpperCase()
      : "FILE";
    title.append(node("span", "file-icon", extension));
    const text = node("div", "file-text");
    const button = node("button", "file-name", row.name);
    button.title = row.path;
    button.onclick = () => showDetails(row);
    const path = node("div", "file-path", row.path);
    path.title = row.path;
    text.append(button, path);
    title.append(text);
    cell.append(title);
    tr.append(cell);
    const state = node("td");
    state.append(
      node("span", "badge " + row.status, labels[row.status] || row.status),
    );
    tr.append(state);
    const contentCode =
      row.download_http ||
      (row.api_http >= 400 ? row.api_http : null) ||
      (row.last_host !== "cloud-api.yandex.net" ? row.last_http : null);
    const code = node(
      "td",
      "http" + (contentCode >= 400 ? " bad" : ""),
      contentCode || "—",
    );
    code.title = I18n.t("API ссылки: ") + (row.api_http || "—");
    if (row.blocked)
      code.title = I18n.t("Локальных ответов 503: ") + row.blocked;
    tr.append(code, node("td", "num", row.attempts || "—"));
    const size = node("td");
    size.append(
      node("span", "size", bytes(row.validated) + " / " + bytes(row.size)),
    );
    const bar = node("div", "progress"),
      fill = node("span");
    fill.style.width =
      (row.size
        ? Math.min(100, (row.validated / row.size) * 100)
        : row.status === "local"
          ? 100
          : 0) + "%";
    bar.append(fill);
    size.append(bar);
    tr.append(size);
    const actions = node("td");
    if (filter === "downloaded" && row.downloaded_at) {
      const completed = new Date(row.downloaded_at);
      const time = node("time", "download-time");
      time.dateTime = row.downloaded_at;
      time.title =
        I18n.t("Загрузка подтверждена Windows: ") +
        completed.toLocaleString(I18n.locale);
      time.append(
        node("span", "", completed.toLocaleTimeString(I18n.locale)),
        node(
          "span",
          "download-date",
          completed.toLocaleDateString(I18n.locale),
        ),
      );
      actions.append(time);
    }
    if (filter !== "downloaded" && row.status !== "local") {
      const direct = node("a", "row-action", I18n.t("Скачать…"));
      direct.href = "/recovery?" + new URLSearchParams({ q: row.path });
      direct.target = "_blank";
      direct.rel = "noopener";
      actions.append(direct);
    }
    if (
      filter !== "downloaded" &&
      snapshot.session.phase === "active" &&
      row.status !== "local"
    ) {
      if (row.status === "deferred") {
        const retry = node("button", "row-action", I18n.t("Повторить"));
        retry.onclick = () =>
          action("/api/retry", { file: row.path })
            .then(() => toast(I18n.t("Файл возвращается в очередь"), "success"))
            .catch((e) => toast(e.message));
        actions.append(retry);
      } else if (
        row.http500 > 0 &&
        !["deferring", "restoring"].includes(row.status)
      ) {
        const defer = node("button", "row-action", I18n.t("Отложить"));
        defer.onclick = () =>
          action("/api/defer", { file: row.path })
            .then(() => toast(I18n.t("Отправлен запрос Windows"), "info"))
            .catch((e) => toast(e.message));
        actions.append(defer);
      }
    }
    tr.append(actions);
    entries.push({
      key: row.path,
      version: JSON.stringify([row, I18n.language, snapshot.session.phase]),
      node: tr,
    });
  }
  ListMotion.render(body, entries, JSON.stringify([filter, search, offset]));
  $("empty").hidden = data.rows.length > 0;
  const recent = filter === "downloaded";
  $("pagination-label").textContent = total
    ? recent
      ? I18n.t("Показано ") +
        number(data.rows.length) +
        I18n.t(" из ") +
        number(total)
      : number(offset + 1) +
        "–" +
        number(Math.min(offset + data.rows.length, total)) +
        I18n.t(" из ") +
        number(total)
    : I18n.t("Файлов нет");
  $("prev").disabled = offset === 0;
  $("next").disabled = offset + data.rows.length >= total;
  $("load-more").hidden = !recent || data.rows.length >= total;
  $("load-more").disabled = !connected;
  $("load-more").textContent = I18n.t("Показать ещё");
}
function renderEvents(events) {
  const target = $("events");
  const entries = [];
  for (const item of events) {
    const row = node("div", "event " + item.event);
    row.append(
      node("div", "event-time", item.time),
      node("div", "event-msg", I18n.t(item.message)),
    );
    if (item.file) row.append(node("div", "event-file", item.file));
    row.classList.add(item.level || "info");
    row.title = [I18n.t(item.reason), I18n.t(item.detail)]
      .filter(Boolean)
      .join("\n");
    entries.push({
      key: item.id,
      version: JSON.stringify([item, I18n.language]),
      node: row,
    });
  }
  ListMotion.render(target, entries);
}
function renderMetrics(state, fresh = true) {
  $("nav-count").textContent = number(state.pending);
  $("metric-size").textContent =
    bytes(state.pending_bytes) + I18n.t(" осталось сохранить");
  $("metric-local").textContent =
    I18n.t("Всего на ПК: ") + number(state.counts.local);
  const d = state.downloads;
  $("nav-downloaded").textContent = number(d.count);
  $("metric-downloaded-size").textContent =
    bytes(d.bytes) +
    I18n.t(" · с ") +
    new Date(d.since).toLocaleString(I18n.locale, {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  MeterBoard.update(
    {
      pending: {
        text: number(state.pending),
        value: state.pending,
        detail: $("metric-size").textContent,
      },
      downloaded: {
        text: number(d.count),
        value: d.count,
        detail:
          $("metric-downloaded-size").textContent +
          " · " +
          $("metric-local").textContent,
      },
      errors: {
        text: number(state.counters.http500),
        value: state.counters.http500 || 0,
        detail: I18n.t("Сохранённые ответы Яндекса"),
      },
      deferred: {
        text: number(state.counts.deferred),
        value: state.counts.deferred || 0,
        detail: I18n.t("Временно снята отметка хранения"),
      },
      network: {
        text: bytes(state.counters.network_bytes),
        value: state.counters.network_bytes || 0,
        detail: I18n.t("Учтённые потоки, включая повторы"),
      },
    },
    $("session-title").textContent,
    fresh,
  );
}
async function refresh(topics = null) {
  if (busy) {
    refreshQueued = true;
    return;
  }
  busy = true;
  const requested = [
    filter,
    search,
    offset,
    filter === "downloaded" ? visibleDownloads : 60,
  ];
  const criteria = JSON.stringify(requested);
  const filesRequested = !Array.isArray(topics) || topics.includes("files");
  if (filesRequested) $("load-more").disabled = true;
  try {
    const response = await fetch("/api/state", {
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error(I18n.t("Панель недоступна"));
    snapshot = await response.json();
    Toasts.problem(
      "statistics",
      snapshot.statistics_error
        ? I18n.t("Не удалось сохранить статистику. Откройте мониторинг.")
        : "",
    );
    connected = true;
    sessionView(snapshot);
    renderMetrics(snapshot);
    $("root-path").textContent =
      snapshot.root || I18n.t("Папка синхронизации ещё не выбрана");
    renderEvents(snapshot.events);
    if (!filesRequested) {
      $("load-more").disabled = false;
      Toasts.problem("connection", "");
      return;
    }
    const params = new URLSearchParams({
      q: requested[1],
      status: requested[0],
      offset: String(requested[2]),
      limit: String(requested[3]),
    });
    const responseFiles = await fetch("/api/files?" + params, {
      signal: AbortSignal.timeout(10000),
    });
    if (!responseFiles.ok)
      throw new Error(I18n.t("Не удалось получить список файлов"));
    const data = await responseFiles.json();
    Toasts.problem("connection", "");
    if (
      criteria ===
      JSON.stringify([
        filter,
        search,
        offset,
        filter === "downloaded" ? visibleDownloads : 60,
      ])
    ) {
      if (filter === "downloaded") {
        const added =
          downloadedTotal === null
            ? 0
            : Math.max(0, data.total - downloadedTotal);
        downloadedTotal = data.total;
        if (added && data.rows.length < data.total) {
          visibleDownloads += added;
          refreshQueued = true;
          return;
        }
      }
      renderRows(data);
    } else refreshQueued = true;
  } catch (e) {
    connected = false;
    MeterBoard.setConnected(false);
    Toasts.problem(
      "connection",
      I18n.t("Не удалось обновить список файлов. ") + e.message,
    );
    $("session-title").textContent = I18n.t("Нет связи с панелью");
    $("session-led").className = "session-led offline";
    for (const id of [
      "start",
      "stop",
      "settings",
      "mode",
      "rescan",
      "load-more",
    ])
      $(id).disabled = true;
    $("load-more").textContent = I18n.t("Показать ещё");
  } finally {
    busy = false;
    if (refreshQueued) {
      refreshQueued = false;
      queueMicrotask(refresh);
    }
  }
}
function renderListHeader() {
  const titles = I18n.labels({
    pending: "Очередь загрузки",
    errors: "Файлы с ошибками 500",
    deferred: "Отложенные файлы",
    local: "Файлы на компьютере",
    downloaded: "Новые загрузки",
    all: "Все отмеченные файлы",
  });
  $("list-title").textContent = titles[filter];
  $("list-description").textContent =
    filter === "downloaded"
      ? I18n.t("Скачанные после начала наблюдения")
      : I18n.t("Файлы с отметкой «Хранить на компьютере»");
  document
    .querySelectorAll(".nav[data-filter]")
    .forEach((e) => e.classList.toggle("active", e.dataset.filter === filter));
  $("downloaded-heading").textContent =
    filter === "downloaded" ? I18n.t("Скачано") : "";
}
function setFilter(value) {
  I18n.preferences.set("fileFilter", value);
  filter = value;
  offset = 0;
  visibleDownloads = 60;
  downloadedTotal = null;
  $("page-controls").hidden = value === "downloaded";
  $("load-more").hidden = true;
  $("downloaded-heading").textContent =
    value === "downloaded" ? I18n.t("Скачано") : "";
  $("file-table").classList.toggle("downloaded-view", value === "downloaded");
  $("filter").value = value;
  $("files").replaceChildren();
  renderListHeader();
  refresh();
}
$("filter").addEventListener("change", (e) => setFilter(e.target.value));
document
  .querySelectorAll(".nav[data-filter]")
  .forEach((e) =>
    e.addEventListener("click", () => setFilter(e.dataset.filter)),
  );
let debounce;
$("search").addEventListener("input", (e) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    search = e.target.value;
    offset = 0;
    visibleDownloads = 60;
    downloadedTotal = null;
    refresh();
  }, 180);
});
$("prev").addEventListener("click", () => {
  offset = Math.max(0, offset - 60);
  refresh();
});
$("next").addEventListener("click", () => {
  offset += 60;
  refresh();
});
$("load-more").addEventListener("click", () => {
  if (filter !== "downloaded" || !connected || busy) return;
  visibleDownloads += 60;
  $("load-more").textContent = I18n.t("Загрузка…");
  refresh();
});
$("mode").addEventListener("change", (e) =>
  action("/api/config", { mode: e.target.value })
    .then(() => {
      toast(I18n.t("Режим изменён."), "success");
      return refresh();
    })
    .catch((e) => toast(e.message)),
);
$("rescan").addEventListener("click", async () => {
  $("rescan").disabled = true;
  try {
    await action("/api/rescan");
    toast(I18n.t("Обновление списка запрошено"), "success");
    await refresh();
  } catch (e) {
    toast(e.message);
  }
});
function openSetup() {
  $("setup-error").hidden = true;
  $("setup-root").value = snapshot.root;
  $("setup-client").value = snapshot.client;
  const options = $("root-options");
  options.replaceChildren();
  for (const path of snapshot.root_candidates || []) {
    const option = node("option");
    option.value = path;
    options.append(option);
  }
  $("setup-dialog").showModal();
}
for (const [button, input, kind] of [
  ["browse-root", "setup-root", "folder"],
  ["browse-client", "setup-client", "client"],
]) {
  $(button).addEventListener("click", async () => {
    const controls = ["browse-root", "browse-client", "setup-cancel"];
    controls.forEach((id) => ($(id).disabled = true));
    $(button).textContent = I18n.t("Выберите в Windows…");
    try {
      const result = await action("/api/browse", {
        kind,
        language: I18n.language,
        initial: $(input).value,
      });
      if (result.path) $(input).value = result.path;
    } catch (error) {
      toast(error.message);
    } finally {
      controls.forEach((id) => ($(id).disabled = false));
      $(button).textContent = I18n.t("Обзор…");
    }
  });
}
for (const [id, path] of [
  ["repair-ca", "/api/repair-ca"],
  ["restart-client", "/api/restart-client"],
]) {
  $(id).addEventListener("click", async () => {
    $(id).disabled = true;
    try {
      await action(path);
      toast(
        I18n.t("Команда отправлена. Результат появится в журнале."),
        "info",
      );
    } catch (error) {
      toast(error.message);
    } finally {
      $(id).disabled = false;
    }
  });
}
$("settings").addEventListener("click", openSetup);
$("setup-cancel").addEventListener("click", () => $("setup-dialog").close());
$("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await action("/api/setup", {
      root: $("setup-root").value,
      client: $("setup-client").value,
    });
    $("setup-dialog").close();
    toast(I18n.t("Настройки сохранены."), "success");
    await refresh();
  } catch (error) {
    toast(error.message);
  }
});
$("start").addEventListener("click", async () => {
  if (snapshot.session.phase === "cleanup_required") {
    try {
      await action("/api/recover");
      await refresh();
    } catch (error) {
      toast(error.message);
    }
    return;
  }
  if (!snapshot.configured) {
    openSetup();
    return;
  }
  $("consent-error").hidden = true;
  $("certificate-thumbprint").textContent = snapshot.certificate_thumbprint
    .match(/.{1,4}/g)
    .join(" ");
  $("consent-checkbox").checked = false;
  $("consent-start").disabled = true;
  $("consent-dialog").showModal();
});
$("consent-checkbox").addEventListener("change", () => {
  $("consent-start").disabled = !$("consent-checkbox").checked;
});
$("consent-cancel").addEventListener("click", () =>
  $("consent-dialog").close(),
);
$("consent-start").addEventListener("click", async () => {
  try {
    $("consent-start").disabled = true;
    await action("/api/start", {
      accepted_thumbprint: snapshot.certificate_thumbprint,
    });
    $("consent-dialog").close();
    toast(I18n.t("Запуск прокси."), "info");
    await refresh();
  } catch (error) {
    toast(error.message);
    $("consent-start").disabled = false;
  }
});
$("stop").addEventListener("click", async () => {
  try {
    $("stop").disabled = true;
    await action("/api/stop");
    toast(I18n.t("Остановка и восстановление запущены."), "info");
    await refresh();
  } catch (e) {
    toast(e.message);
  }
});
I18n.onChange(() => {
  renderListHeader();
  if (snapshot) {
    if (connected) sessionView(snapshot);
    else $("session-title").textContent = I18n.t("Нет связи с панелью");
    renderMetrics(snapshot, false);
    renderEvents(snapshot.events);
    if (lastRows) renderRows(lastRows);
    $("root-path").textContent =
      snapshot.root || I18n.t("Папка синхронизации ещё не выбрана");
  }
  for (const id of ["setup-error", "consent-error"])
    $(id).textContent = I18n.t($(id).textContent);
  if ($("details").open && detailRow) showDetails(detailRow, false);
});
setFilter(filter);
LivePanel.subscribe(refresh, ["state", "files", "events"]);
