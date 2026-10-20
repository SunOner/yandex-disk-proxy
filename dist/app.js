"use strict";
let snapshot = null,
  offset = 0,
  total = 0,
  filter = "pending",
  search = "",
  busy = false,
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
  cooldown: "Пауза повторов",
  error: "Ошибка сети",
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
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => ($("toast").hidden = true), 6000);
}
async function action(path, data = {}) {
  if (!snapshot) return;
  const r = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Panel-Nonce": snapshot.nonce,
    },
    body: JSON.stringify(data),
  });
  const value = await r.json();
  if (!r.ok) throw new Error(value.error || "Ошибка локального действия");
  return value;
}
function sessionView(s) {
  const phase = s.session.phase,
    active = phase === "active",
    working = ["starting", "stopping"].includes(phase);
  $("session-led").className =
    "session-led" + (active ? " active" : working ? " working" : "");
  $("session-title").textContent = active
    ? "MITM работает"
    : phase === "starting"
      ? "Запускается MITM"
      : phase === "stopping"
        ? "Восстанавливается клиент"
        : phase === "cleanup_required"
          ? "Нужно завершить восстановление"
          : "MITM остановлен";
  let subtitle = "Клиент подключается к Яндексу напрямую";
  if (active) subtitle = "Только Яндекс Диск · включён до ручной остановки";
  if (phase === "starting") subtitle = "Сертификат → прокси → перезапуск Диска";
  if (phase === "stopping")
    subtitle = "Возврат отметок хранения и удаление сертификата";
  if (phase === "cleanup_required")
    subtitle = "Проверьте журнал: требуется восстановление";
  $("session-subtitle").textContent = subtitle;
  $("start").disabled = active || working;
  $("settings").disabled = active || working;
  $("notice-summary").textContent = {
    defer:
      "После первого ответа 500 полностью облачный файл временно откладывается.",
    cooldown:
      "Повторы ошибочных запросов ограничиваются; отметки хранения не меняются.",
    observe: "Наблюдение: запросы и отметки хранения остаются без изменений.",
  }[s.mode];
  $("start").textContent =
    phase === "cleanup_required" ? "↺ Восстановить" : "▶ Запустить MITM";
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
        : "Был на ПК до наблюдения / ещё не загружен",
    ],
    [
      "Подключение при завершении",
      row.downloaded_at
        ? row.downloaded_via_proxy === null
          ? "Завершилось между запусками панели"
          : row.downloaded_via_proxy
            ? "Через MITM"
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
      (row.last_host !== "cloud-api.yandex.net" ? row.last_http : null);
    const code = node(
      "td",
      "http" + (contentCode === 500 ? " bad" : ""),
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
      } else if (row.http500 > 0 && !["deferring"].includes(row.status)) {
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
  if (busy) return;
  busy = true;
  try {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error("Backend unavailable");
    snapshot = await response.json();
    $("connection").textContent = "● Панель подключена";
    $("connection").className = "connection";
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
    if (snapshot.session.phase === "active")
      $("cleanup").textContent =
        "Без таймера. Работает до ручной остановки или закрытия окна CMD.";
    else if (snapshot.cleanup)
      $("cleanup").textContent =
        snapshot.cleanup.ca_removed && snapshot.cleanup.restore_failures === 0
          ? "Последняя остановка: сертификат удалён, отметки восстановлены."
          : "Остановка требует внимания — проверьте журнал.";
    const params = new URLSearchParams({
      q: search,
      status: filter,
      offset: String(offset),
      limit: "60",
    });
    const data = await (await fetch("/api/files?" + params)).json();
    renderRows(data);
  } catch (e) {
    $("connection").textContent = "● Нет связи с панелью";
    $("connection").className = "connection offline";
  } finally {
    busy = false;
  }
}
function setFilter(value) {
  filter = value;
  offset = 0;
  $("filter").value = value;
  const titles = {
    pending: "Очередь загрузки",
    errors: "Файлы с ошибками 500",
    deferred: "Отложенные файлы",
    local: "Файлы на компьютере",
    downloaded: "Новые загрузки с начала наблюдения",
    all: "Все отмеченные файлы",
  };
  $("list-title").textContent = titles[value];
  $("list-description").textContent =
    value === "downloaded"
      ? "Только новые завершённые загрузки; счётчик сохраняется при перезапуске"
      : "Только файлы, отмеченные для хранения на ПК";
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
    toast("Настройка сохранена. Теперь можно включить прокси.");
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
    toast("Прокси включается без таймера. Остановить его можно в этой панели.");
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
