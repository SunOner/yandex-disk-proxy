"use strict";
let snapshot = null,
  offset = 0,
  total = 0,
  filter = "pending",
  search = "",
  busy = false,
  refreshQueued = false,
  connected = false,
  timer = null;
const $ = (id) => document.getElementById(id);
const labels = {
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
};
function bytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " Б";
  let units = ["КБ", "МБ", "ГБ", "ТБ"],
    i = -1;
  do {
    n /= 1024;
    i++;
  } while (n >= 1024 && i < units.length - 1);
  return (
    new Intl.NumberFormat("ru", {
      maximumFractionDigits: n < 10 ? 1 : 0,
    }).format(n) +
    " " +
    units[i]
  );
}
function number(n) {
  return new Intl.NumberFormat("ru").format(n || 0);
}
function node(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function toast(text) {
  const dialog = document.querySelector("dialog[open]");
  const error = dialog?.querySelector(".dialog-error");
  if (error) {
    error.textContent = text;
    error.hidden = false;
    return;
  }
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => ($("toast").hidden = true), 6000);
}
async function action(path, data = {}) {
  if (!snapshot || !connected) throw new Error("Нет связи с панелью");
  const r = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Panel-Nonce": snapshot.nonce,
    },
    body: JSON.stringify(data),
  });
  const value = await r.json();
  if (!r.ok) throw new Error(value.error || "Ошибка действия");
  return value;
}
function sessionView(s) {
  const phase = s.session.phase,
    active = phase === "active",
    working = ["starting", "stopping"].includes(phase);
  $("session-led").className =
    "session-led" + (active ? " active" : working ? " working" : "");
  $("session-title").textContent = active
    ? "Прокси включён"
    : phase === "starting"
      ? "Запуск прокси"
      : phase === "stopping"
        ? "Восстанавливается клиент"
        : phase === "cleanup_required"
          ? "Ошибка восстановления"
          : "Прокси выключен";
  $("start").disabled = active || working;
  $("settings").disabled = active || working;
  $("mode").disabled = working;
  $("start").textContent =
    phase === "cleanup_required" ? "↺ Восстановить" : "▶ Включить прокси";
  $("stop").disabled = !(active || phase === "starting");
  if (document.activeElement !== $("mode")) $("mode").value = s.mode;
}
function showDetails(row) {
  $("detail-name").textContent = row.name;
  $("detail-path").textContent = row.path;
  const list = $("detail-values");
  list.replaceChildren();
  const values = [
    ["Состояние", labels[row.status] || row.status],
    ["Размер", bytes(row.size)],
    [
      "Загрузка подтверждена",
      row.downloaded_at
        ? new Date(row.downloaded_at).toLocaleString("ru-RU")
        : "Нет данных",
    ],
    [
      "Подключение при завершении",
      row.downloaded_at
        ? row.downloaded_via_proxy === null
          ? "Между запусками панели"
          : row.downloaded_via_proxy
            ? "Через прокси"
            : "Напрямую"
        : "—",
    ],
    ["Подтверждено Windows", bytes(row.validated)],
    ["Передано по сети", bytes(row.network_bytes)],
    ["Запросов ссылки", number(row.attempts)],
    ["Ответов HTTP 500", number(row.http500)],
    ["Повторов ограничено", number(row.blocked)],
    ["Последний сервер", row.last_host || "—"],
    ["Ответ API ссылки", row.api_http || "—"],
    ["HTTP выдачи файла", row.download_http || "—"],
    ["Последнее событие", row.last_time || "—"],
  ];
  for (const [title, value] of values) {
    list.append(node("dt", "", title), node("dd", "", value));
  }
  $("details").showModal();
}
function renderRows(data) {
  total = data.total;
  offset = data.offset;
  const body = $("files");
  body.replaceChildren();
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
    button.addEventListener("click", () => showDetails(row));
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
    code.title = "API ссылки: " + (row.api_http || "—");
    if (row.blocked) code.title = "Локальных ответов 503: " + row.blocked;
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
    if (snapshot.session.phase === "active" && row.status !== "local") {
      if (row.status === "deferred") {
        const retry = node("button", "row-action", "Повторить");
        retry.addEventListener("click", () =>
          action("/api/retry", { file: row.path })
            .then(() => toast("Файл возвращается в очередь"))
            .catch((e) => toast(e.message)),
        );
        actions.append(retry);
      } else if (
        row.http500 > 0 &&
        !["deferring", "restoring"].includes(row.status)
      ) {
        const defer = node("button", "row-action", "Отложить");
        defer.addEventListener("click", () =>
          action("/api/defer", { file: row.path })
            .then(() => toast("Отправлен запрос Windows"))
            .catch((e) => toast(e.message)),
        );
        actions.append(defer);
      }
    }
    tr.append(actions);
    body.append(tr);
  }
  $("empty").hidden = data.rows.length > 0;
  $("pagination-label").textContent = total
    ? number(offset + 1) +
      "–" +
      number(Math.min(offset + data.rows.length, total)) +
      " из " +
      number(total)
    : "Файлов нет";
  $("prev").disabled = offset === 0;
  $("next").disabled = offset + data.rows.length >= total;
}
function renderEvents(events) {
  const target = $("events");
  target.replaceChildren();
  for (const item of events) {
    const row = node("div", "event " + item.event);
    row.append(
      node("div", "event-time", item.time),
      node("div", "event-msg", item.message),
    );
    if (item.file) row.append(node("div", "event-file", item.file));
    target.append(row);
  }
}
async function refresh() {
  if (busy) {
    refreshQueued = true;
    return;
  }
  busy = true;
  const requested = [filter, search, offset];
  const criteria = JSON.stringify(requested);
  try {
    const response = await fetch("/api/state", {
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error("Backend unavailable");
    snapshot = await response.json();
    connected = true;
    sessionView(snapshot);
    $("metric-pending").textContent = number(snapshot.pending);
    $("nav-count").textContent = number(snapshot.pending);
    $("metric-size").textContent =
      bytes(snapshot.pending_bytes) + " осталось сохранить";
    $("metric-local").textContent =
      "Всего на ПК: " + number(snapshot.counts.local);
    const d = snapshot.downloads;
    $("metric-downloaded").textContent = number(d.count);
    $("nav-downloaded").textContent = number(d.count);
    $("metric-downloaded-size").textContent =
      bytes(d.bytes) +
      " · с " +
      new Date(d.since).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    $("metric-errors").textContent = number(snapshot.counters.http500);
    $("metric-deferred").textContent = number(snapshot.counts.deferred);
    $("metric-network").textContent = bytes(snapshot.counters.network_bytes);
    $("root-path").textContent =
      snapshot.root || "Папка синхронизации ещё не выбрана";
    renderEvents(snapshot.events);
    const params = new URLSearchParams({
      q: requested[1],
      status: requested[0],
      offset: String(requested[2]),
      limit: "60",
    });
    const responseFiles = await fetch("/api/files?" + params, {
      signal: AbortSignal.timeout(10000),
    });
    if (!responseFiles.ok) throw new Error("Не удалось получить список файлов");
    const data = await responseFiles.json();
    if (criteria === JSON.stringify([filter, search, offset])) renderRows(data);
    else refreshQueued = true;
  } catch (e) {
    connected = false;
    $("session-title").textContent = "Нет связи с панелью";
    $("session-led").className = "session-led offline";
    for (const id of ["start", "stop", "settings", "mode"])
      $(id).disabled = true;
  } finally {
    busy = false;
    if (refreshQueued) {
      refreshQueued = false;
      queueMicrotask(refresh);
    }
  }
}
function setFilter(value) {
  filter = value;
  offset = 0;
  $("filter").value = value;
  $("files").replaceChildren();
  const titles = {
    pending: "Очередь загрузки",
    errors: "Файлы с ошибками 500",
    deferred: "Отложенные файлы",
    local: "Файлы на компьютере",
    downloaded: "Новые загрузки",
    all: "Все отмеченные файлы",
  };
  $("list-title").textContent = titles[value];
  $("list-description").textContent =
    value === "downloaded"
      ? "Скачанные после начала наблюдения"
      : "Файлы с отметкой «Хранить на компьютере»";
  document
    .querySelectorAll(".nav")
    .forEach((e) => e.classList.toggle("active", e.dataset.filter === value));
  refresh();
}
$("filter").addEventListener("change", (e) => setFilter(e.target.value));
document
  .querySelectorAll(".nav")
  .forEach((e) =>
    e.addEventListener("click", () => setFilter(e.dataset.filter)),
  );
let debounce;
$("search").addEventListener("input", (e) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    search = e.target.value;
    offset = 0;
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
$("mode").addEventListener("change", (e) =>
  action("/api/config", { mode: e.target.value })
    .then(() => refresh())
    .catch((e) => toast(e.message)),
);
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
    toast("Настройки сохранены.");
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
    toast("Запуск прокси.");
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
    await refresh();
  } catch (e) {
    toast(e.message);
  }
});
refresh();
setInterval(refresh, 2000);
