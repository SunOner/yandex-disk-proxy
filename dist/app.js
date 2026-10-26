"use strict";
let snapshot = null,
  offset = 0,
  total = 0,
  filter = I18n.preferences.get("fileFilter", "pending"),
  search = "",
  busy = false,
  refreshQueued = false,
  connected = false,
  loadingMore = false,
  sessionPending = null,
  setupPending = null,
  resetPending = null,
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
function thumbnailToggleView() {
  $("toggle-thumbnails").ariaPressed = String(Thumbnails.enabled);
  $("toggle-thumbnails").title = I18n.t(
    Thumbnails.enabled ? "Скрыть превью файлов" : "Показывать превью файлов",
  );
}
$("toggle-thumbnails").addEventListener("click", () =>
  Thumbnails.setEnabled(!Thumbnails.enabled),
);
Thumbnails.onChange(thumbnailToggleView);
thumbnailToggleView();
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
  const phase = sessionPending
      ? sessionPending === "start"
        ? "starting"
        : "stopping"
      : s.session.phase,
    active = phase === "active",
    detached = active && s.session.client_attached === false,
    working = ["starting", "stopping"].includes(phase),
    recovery = phase === "cleanup_required",
    enabled = active || phase === "starting" || recovery,
    toggle = $("proxy-toggle");
  toggle.className = "proxy-toggle" + (recovery ? " recovery" : "");
  toggle.ariaChecked = String(enabled);
  toggle.ariaBusy = String(working);
  toggle.disabled = !connected || !!sessionPending || phase === "stopping";
  resetButtons();
  toggle.title = I18n.t(
    recovery
      ? "Восстановить Диск"
      : enabled
        ? "Выключить прокси и восстановить Диск"
        : "Включить прокси",
  );
  $("session-title").textContent = detached
    ? I18n.t("Диск не подключён к прокси")
    : active
      ? I18n.t("Прокси включён")
      : phase === "starting"
        ? I18n.t("Запуск прокси")
        : phase === "stopping"
          ? I18n.t("Восстанавливается клиент")
          : phase === "cleanup_required"
            ? I18n.t("Ошибка восстановления")
            : I18n.t("Прокси выключен");
  $("mode").disabled = working;
  if (document.activeElement !== $("mode")) $("mode").value = s.mode;
  const clientScope = s.session.certificate_scope === "client";
  const missing =
    active &&
    (clientScope
      ? s.session.certificate_ready === false
      : s.session.ca_trusted === false);
  const relevant = (side) =>
    !s.session.client_connected_at ||
    !side?.at ||
    side.at >= s.session.client_connected_at;
  const clientError =
    active && s.tls?.client?.ok === false && relevant(s.tls.client);
  const upstreamError =
    active && s.tls?.upstream?.ok === false && relevant(s.tls.upstream);
  const message = missing
    ? clientScope
      ? "Файл сертификата Диска недоступен или изменён."
      : "Сертификат больше не находится в доверенных Windows."
    : detached
      ? s.session.client_connection === "limited"
        ? "Не удалось переподключить Диск. Нажмите «Перезапустить Диск»."
        : "Подключение Диска к прокси восстанавливается."
      : clientError
        ? "Диск отклонил TLS-соединение. Причина — в журнале."
        : upstreamError
          ? "Ошибка TLS между прокси и Яндексом. Причина — в журнале."
          : s.log_error || s.session.error_detail || "";
  const repair =
    missing && !clientScope
      ? ["Восстановить доверие", "/api/repair-ca"]
      : !missing && (clientError || detached)
        ? ["Перезапустить Диск", "/api/restart-client"]
        : null;
  const upstreamOnly = upstreamError && !missing && !detached && !clientError;
  const transientUpstream =
    upstreamOnly &&
    !/certificate|unknown ca|cert_verify/i.test(s.tls.upstream.error || "");
  Toasts.problem("session", message, {
    delay: transientUpstream ? 10000 : 0,
    cooldown: transientUpstream ? 300000 : 0,
    scope: upstreamOnly ? s.session.session || s.session.started || "" : "",
    action: repair
      ? {
          label: repair[0],
          async onClick() {
            await action(repair[1]);
            toast("Команда отправлена. Результат появится в журнале.", "info");
            await refresh();
          },
        }
      : undefined,
  });
  $("inventory-status").hidden =
    !s.inventory?.scanning || s.inventory.updated_at !== null;
  Toasts.problem(
    "inventory",
    s.inventory?.error
      ? I18n.t("Не удалось прочитать список файлов. См. журнал.")
      : "",
  );
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
    const icon = node("span", "file-icon", extension);
    Thumbnails.decorate(icon, row);
    title.append(icon);
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
  Thumbnails.sync(body);
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
  renderLoadMore();
}
function renderLoadMore() {
  const button = $("load-more"),
    label = I18n.t(loadingMore ? "Загрузка…" : "Показать ещё");
  button.disabled = !connected || loadingMore;
  button.ariaBusy = String(loadingMore);
  if (button.textContent !== label) button.textContent = label;
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
function estimateText(estimate) {
  if (!Number.isFinite(estimate?.seconds)) return "—";
  if (estimate.seconds === 0) return I18n.t("Готово");
  const minutes = Math.max(1, Math.ceil(estimate.seconds / 60)),
    days = Math.floor(minutes / 1440),
    hours = Math.floor((minutes % 1440) / 60),
    rest = minutes % 60;
  const duration = days
    ? I18n.t("{0} д {1} ч", [number(days), hours])
    : hours
      ? I18n.t("{0} ч {1} мин", [hours, rest])
      : I18n.t("{0} мин", [rest]);
  return "≈ " + duration;
}
function renderMetrics(state, fresh = true) {
  const counters = state.display_counters || state.counters;
  $("nav-count").textContent = number(state.pending);
  const d = state.downloads;
  const downloaded = counters.native_files ?? d.count;
  const estimate = state.completion_estimate;
  const estimateHints = {
    estimated: "Примерно, по последним загрузкам. Недоступные файлы могут задержать завершение.",
    learning: "Недостаточно данных для оценки времени.",
    scanning: "Ожидание списка файлов.",
    paused: "Расчёт времени доступен при работающем прокси и подключённом Диске.",
    waiting: "Нет недавних завершённых загрузок для оценки времени.",
    complete: "Все выбранные файлы сохранены на ПК.",
  };
  const estimateTitle = I18n.t(estimateHints[estimate?.status] || estimateHints.learning);
  $("metric-eta").title = $("board-eta").title = estimateTitle;
  $("nav-downloaded").textContent = number(d.count);
  MeterBoard.update(
    {
      pending: {
        text: number(state.pending),
        value: state.pending,
      },
      remaining: {
        text: bytes(state.pending_bytes),
        value: state.pending_bytes || 0,
      },
      downloaded: {
        text: number(downloaded),
        value: downloaded,
      },
      eta: {
        text: estimateText(estimate),
        value: estimate?.seconds || 0,
      },
      errors: {
        text: number(counters.http500),
        value: counters.http500 || 0,
      },
      deferred: {
        text: number(state.counts.deferred),
        value: state.counts.deferred || 0,
      },
      network: {
        text: bytes(counters.network_bytes),
        value: counters.network_bytes || 0,
      },
    },
    $("session-title").textContent,
    fresh,
  );
}
function resetButtons() {
  for (const [id, kind] of [
    ["reset-downloads", "native_files"],
    ["reset-errors", "http500"],
    ["reset-network", "network_bytes"],
    ["reset-deferred", "deferred"],
  ]) {
    $(id).disabled =
      !connected ||
      !!resetPending ||
      (kind === "deferred" &&
        (snapshot?.session.phase !== "active" ||
          snapshot?.session.client_attached === false ||
          !snapshot?.counts.deferred));
    $(id).ariaBusy = String(resetPending === kind);
  }
}
for (const [id, counter] of [
  ["reset-downloads", "native_files"],
  ["reset-errors", "http500"],
  ["reset-network", "network_bytes"],
  ["reset-deferred", "deferred"],
]) {
  $(id).addEventListener("click", async () => {
    if ($(id).disabled || resetPending) return;
    resetPending = counter;
    resetButtons();
    try {
      if (counter === "deferred") {
        const result = await action("/api/statistics/retry-deferred");
        toast(I18n.t("Возвращено в очередь: {0}", [result.queued]), "success");
      } else {
        const result = await action("/api/statistics/reset", { counter });
        Toasts.show(
          {
            http500: "Счётчик HTTP 500 сброшен.",
            network_bytes: "Счётчик трафика сброшен.",
            native_files: "Счётчик новых загрузок сброшен.",
          }[counter],
          {
            type: "success",
            key: "statistics-reset",
            duration: 12000,
            action: {
              label: "Отменить",
              onClick: async () => {
                await action("/api/statistics/undo", {
                  revision: result.revision,
                  context: result.context,
                });
                await refresh(["state"]);
                toast("Сброс отменён.", "success");
              },
            },
          },
        );
      }
      await refresh(["state", ...(counter === "deferred" ? ["files"] : [])]);
    } catch (error) {
      toast(error.message);
    } finally {
      resetPending = null;
      resetButtons();
    }
  });
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
  try {
    const response = await fetch("/api/state", {
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error(I18n.t("Панель недоступна"));
    snapshot = await response.json();
    Thumbnails.configure(snapshot);
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
      renderLoadMore();
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
      loadingMore = false;
      renderRows(data);
    } else refreshQueued = true;
  } catch (e) {
    connected = false;
    Toasts.problem("session", "");
    resetButtons();
    MeterBoard.setConnected(false);
    Toasts.problem(
      "connection",
      I18n.t("Не удалось обновить список файлов. ") + e.message,
    );
    $("session-title").textContent = I18n.t("Нет связи с панелью");
    $("proxy-toggle").className = "proxy-toggle offline";
    $("proxy-toggle").ariaBusy = "false";
    $("proxy-toggle").title = I18n.t("Нет связи с панелью");
    for (const id of ["proxy-toggle", "mode", "load-more"])
      $(id).disabled = true;
    loadingMore = false;
    renderLoadMore();
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
  loadingMore = false;
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
    loadingMore = false;
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
  if (filter !== "downloaded" || !connected || loadingMore) return;
  loadingMore = true;
  visibleDownloads += 60;
  renderLoadMore();
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
function openSetup() {
  if (setupPending) return;
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
function setupView(pending) {
  setupPending = pending;
  $("setup-form").ariaBusy = String(!!pending);
  for (const id of [
    "setup-root",
    "setup-client",
    "browse-root",
    "browse-client",
    "setup-save",
    "setup-cancel",
  ])
    $(id).disabled = !!pending;
  $("setup-save").ariaBusy = String(pending === "saving");
  $("setup-save").textContent = I18n.t(
    pending === "saving" ? "Сохранение…" : "Сохранить",
  );
  $("setup-progress").hidden = !pending;
  $("setup-progress").textContent = I18n.t(
    pending === "saving"
      ? "Проверяем папку и приложение…"
      : "Выберите путь в окне Windows.",
  );
  for (const [id, kind] of [
    ["browse-root", "folder"],
    ["browse-client", "client"],
  ]) {
    $(id).ariaBusy = String(pending === kind);
    $(id).textContent = I18n.t(
      pending === kind ? "Выберите в Windows…" : "Обзор…",
    );
  }
}
for (const [button, input, kind] of [
  ["browse-root", "setup-root", "folder"],
  ["browse-client", "setup-client", "client"],
]) {
  $(button).addEventListener("click", async () => {
    if (setupPending) return;
    $("setup-error").hidden = true;
    setupView(kind);
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
      setupView(null);
    }
  });
}
$("setup-cancel").addEventListener("click", () => {
  if (!setupPending) $("setup-dialog").close();
});
$("setup-dialog").addEventListener("cancel", (event) => {
  if (setupPending) event.preventDefault();
});
$("setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (setupPending) return;
  $("setup-error").hidden = true;
  setupView("saving");
  try {
    await action("/api/setup", {
      root: $("setup-root").value,
      client: $("setup-client").value,
    });
    $("setup-dialog").close();
    toast(I18n.t("Настройки сохранены. Читаем список файлов…"), "success");
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    setupView(null);
  }
});
async function requestStart() {
  if (!snapshot.configured) {
    openSetup();
    return;
  }
  if (snapshot.certificate_approved) {
    await changeSession("start");
    return;
  }
  $("consent-error").hidden = true;
  const machineCertificate = snapshot.certificate_scope === "local_machine";
  for (const [id, source] of [
    [
      "certificate-consent-intro",
      machineCertificate
        ? "Прокси временно добавит сертификат в доверенные корневые сертификаты компьютера Windows. Ему смогут доверять приложения всех пользователей. Windows может запросить права администратора. Добавленный прокси сертификат удаляется при остановке."
        : "Прокси временно добавит сертификат в доверенные корневые сертификаты текущего пользователя Windows. Ему смогут доверять и другие приложения. Добавленный прокси сертификат удаляется при остановке.",
    ],
    [
      "certificate-consent-label",
      machineCertificate
        ? "Разрешаю временно добавить этот сертификат в доверенные корневые сертификаты компьютера Windows (для всех пользователей)."
        : "Разрешаю временно добавить этот сертификат в доверенные корневые сертификаты моего пользователя Windows.",
    ],
  ]) {
    $(id).setAttribute("data-i18n", source);
    $(id).textContent = I18n.t(source);
  }
  $("certificate-thumbprint").textContent = snapshot.certificate_thumbprint
    .match(/.{1,4}/g)
    .join(" ");
  $("consent-checkbox").checked = false;
  $("consent-start").disabled = true;
  $("consent-dialog").showModal();
}
async function changeSession(command, data = {}) {
  if (!connected || sessionPending) return;
  sessionPending = command;
  sessionView(snapshot);
  try {
    await action("/api/" + command, data);
    if (command === "start") $("consent-dialog").close();
    toast(
      I18n.t(
        command === "start"
          ? "Запуск прокси."
          : "Остановка и восстановление запущены.",
      ),
      "info",
    );
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    sessionPending = null;
    if (connected) sessionView(snapshot);
  }
}
$("proxy-toggle").addEventListener("click", async () => {
  if (!connected || sessionPending || snapshot.session.phase === "stopping")
    return;
  const phase = snapshot.session.phase;
  if (phase === "cleanup_required") await changeSession("recover");
  else if (phase === "active" || phase === "starting")
    await changeSession("stop");
  else await requestStart();
});
$("consent-checkbox").addEventListener("change", () => {
  $("consent-start").disabled = !$("consent-checkbox").checked;
});
$("consent-cancel").addEventListener("click", () =>
  $("consent-dialog").close(),
);
$("consent-start").addEventListener("click", async () => {
  if (!$("consent-checkbox").checked || sessionPending) return;
  try {
    $("consent-start").disabled = true;
    await changeSession("start", {
      accepted_thumbprint: snapshot.certificate_thumbprint,
      accepted_certificate_scope: snapshot.certificate_scope,
    });
  } finally {
    $("consent-start").disabled = !$("consent-checkbox").checked;
  }
});
I18n.onChange(() => {
  thumbnailToggleView();
  setupView(setupPending);
  renderListHeader();
  if (snapshot) {
    if (connected) sessionView(snapshot);
    else {
      $("session-title").textContent = I18n.t("Нет связи с панелью");
      $("proxy-toggle").title = I18n.t("Нет связи с панелью");
    }
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
LivePanel.subscribe(refresh, ["state", "files", "events", "metrics"]);
