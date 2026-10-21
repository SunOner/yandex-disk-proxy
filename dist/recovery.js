"use strict";
const $ = (id) => document.getElementById(id);
let nonce = "",
  connected = false,
  paused = false,
  busy = false,
  view = I18n.preferences.get("recoveryView", "queue"),
  offset = 0,
  query = new URLSearchParams(location.search).get("q") || "",
  chosen = "",
  revision = 0;
let lastState = null,
  lastList = null;
const labels = I18n.labels({
  queued: "В очереди",
  fetching: "Запрос ссылки",
  downloading: "Загружается",
  retry: "Повтор",
  waiting_session: "Ожидание сессии",
  paused: "Приостановлен",
  cancelled: "Остановлен",
  failed: "Ошибка",
  verified: "Проверен",
  waiting: "Не скачан",
  deferred: "Отложен",
  deferring: "Откладывается",
  requesting: "Запрос ссылки",
  http500: "Ошибка 500",
  error: "Ошибка",
  cooldown: "Пауза повторов",
  restoring: "Возврат в очередь",
});
function bytes(n) {
  n = Number(n) || 0;
  let i = 0;
  const units = [I18n.t("Б"), I18n.t("КБ"), I18n.t("МБ"), I18n.t("ГБ")];
  while (n >= 1024 && i < 3) {
    n /= 1024;
    i++;
  }
  return (
    new Intl.NumberFormat(I18n.locale, {
      maximumFractionDigits: i ? 1 : 0,
    }).format(n) +
    " " +
    units[i]
  );
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  e.className = cls || "";
  if (text !== undefined) e.textContent = text;
  return e;
}
async function json(path, options = {}) {
  const r = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(45000),
  });
  const v = await r.json();
  if (!r.ok) throw Error(I18n.t(v.error) || I18n.t("Ошибка запроса"));
  return v;
}
async function action(name, data = {}) {
  if (!connected) throw Error(I18n.t("Нет связи с панелью"));
  return json("/api/recovery/" + name, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Panel-Nonce": nonce },
    body: JSON.stringify(data),
  });
}
async function run(name, data = {}) {
  try {
    const result = await action(name, data);
    const message =
      name === "enqueue"
        ? I18n.t("Файл добавлен в очередь.")
        : name === "batch"
          ? result.queued
            ? I18n.t("Добавлено в очередь: {0}.", [result.queued])
            : I18n.t("Нет новых файлов для добавления.")
          : name === "folder"
            ? I18n.t("Папка загрузок открыта.")
            : data.action === "pause"
              ? I18n.t("Прямые загрузки приостановлены.")
              : data.action === "resume"
                ? I18n.t("Прямые загрузки продолжены.")
                : data.file
                  ? I18n.t("Загрузка файла остановлена.")
                  : I18n.t("Прямые загрузки остановлены.");
    Toasts.show(message, { type: "success" });
    await refresh();
  } catch (e) {
    Toasts.show(e.message, { type: "error" });
  }
}
function button(text, callback) {
  const b = el("button", "row-action", text);
  b.disabled = !connected;
  b.addEventListener("click", callback);
  return b;
}
async function browser(path) {
  const tab = window.open("about:blank", "_blank");
  if (tab) tab.opener = null;
  try {
    const value = await action("browser", { file: path });
    if (tab) tab.location = value.url;
    else {
      Toasts.show(
        I18n.t("Разрешите открытие новой вкладки и повторите загрузку."),
        {
          type: "error",
        },
      );
    }
  } catch (e) {
    if (tab) tab.close();
    Toasts.show(e.message, { type: "error" });
  }
}
function render(data) {
  lastList = { data, view };
  const entries = [];
  for (const row of data.rows) {
    const tr = el("tr");
    const file = el("td");
    file.append(el("div", "recovery-path", row.path));
    if (row.error) file.append(el("div", "recovery-error", I18n.t(row.error)));
    tr.append(file, el("td", row.status, labels[row.status] || row.status));
    const size = el(
      "td",
      "",
      bytes(row.received || 0) + " / " + bytes(row.size),
    );
    const p = document.createElement("progress");
    p.max = row.size || 1;
    p.value = row.received || 0;
    size.append(p);
    tr.append(size);
    const cell = el("td");
    const controls = el("div", "recovery-actions");
    if (row.status !== "verified") {
      const active =
        [
          "queued",
          "downloading",
          "fetching",
          "retry",
          "waiting_session",
        ].includes(row.status) && view === "queue";
      controls.append(
        button(active ? I18n.t("Остановить") : I18n.t("Скачать"), () =>
          run(
            active ? "control" : "enqueue",
            active ? { action: "cancel", file: row.path } : { file: row.path },
          ),
        ),
      );
      controls.append(button(I18n.t("Браузер"), () => browser(row.path)));
      controls.append(
        button("URL", () => {
          chosen = row.path;
          $("url-file").textContent = chosen;
          $("download-url").value = "";
          $("url-error").hidden = true;
          $("url-dialog").showModal();
        }),
      );
    } else {
      controls.append(el("span", "verified", "SHA-256 ✓"));
      controls.title = row.target || "";
    }
    cell.append(controls);
    tr.append(cell);
    entries.push({ key: row.path, node: tr });
  }
  ListMotion.render($("rows"), entries, view);
  const total = data.filtered ?? data.total;
  offset = data.offset;
  $("empty").hidden = data.rows.length > 0;
  $("count").textContent = total
    ? I18n.t("{0}–{1} из {2}", [offset + 1, offset + data.rows.length, total])
    : I18n.t("Файлов нет");
  $("previous").disabled = offset === 0;
  $("next-page").disabled = offset + data.rows.length >= total;
}
function renderState(s, fresh = true) {
  nonce = s.nonce;
  if (fresh) connected = true;
  const r = s.recovery,
    c = r.counts;
  paused = r.paused;
  $("connection").textContent = connected ? "" : I18n.t("Нет связи");
  $("verified").textContent = r.verified;
  $("verified-size").textContent = bytes(r.verified_bytes);
  $("active").textContent = paused
    ? 0
    : (c.downloading || 0) + (c.fetching || 0);
  $("speed").textContent =
    bytes(r.speed) + I18n.t("/с · до ") + r.workers + I18n.t(" файлов");
  $("waiting").textContent =
    (c.queued || 0) +
    (c.retry || 0) +
    (c.waiting_session || 0) +
    (c.paused || 0);
  $("failed").textContent = c.failed || 0;
  $("session").textContent = r.account_verified
    ? I18n.t("Аккаунт проверен")
    : r.credentials_seen
      ? I18n.t("Сессия Диска получена")
      : I18n.t("Ожидание запроса Диска через прокси");
  $("destination").textContent = r.destination;
  $("network").textContent = I18n.t("За 5 мин: {0} пустых ответов, {1} отмен", [
    s.network.empty_downloads,
    s.network.cancelled,
  ]);
  $("pause-downloads").textContent = paused
    ? I18n.t("Продолжить")
    : I18n.t("Приостановить");
}
async function refresh() {
  if (busy) return;
  busy = true;
  const requested = revision;
  try {
    const s = await json("/api/state");
    lastState = s;
    renderState(s);
    const data = await json(
      (view === "queue" ? "/api/recovery" : "/api/files") +
        "?" +
        new URLSearchParams({
          q: query,
          offset,
          status: "pending",
          limit: 100,
        }),
    );
    if (requested === revision) render(data);
    for (const id of ["batch", "pause-downloads", "cancel-downloads", "folder"])
      $(id).disabled = false;
    Toasts.problem("connection", "");
  } catch (e) {
    connected = false;
    $("connection").textContent = I18n.t("Нет связи");
    Toasts.problem(
      "connection",
      I18n.t("Не удалось обновить загрузки. ") + e.message,
    );
    for (const id of ["batch", "pause-downloads", "cancel-downloads", "folder"])
      $(id).disabled = true;
  } finally {
    busy = false;
    if (requested !== revision) queueMicrotask(refresh);
  }
}
for (const mode of ["queue", "files"])
  $("tab-" + mode).addEventListener("click", () => {
    view = mode;
    I18n.preferences.set("recoveryView", view);
    offset = 0;
    revision++;
    for (const v of ["queue", "files"])
      $("tab-" + v).classList.toggle("active", v === mode);
    refresh();
  });
$("query").value = query;
if (query) {
  view = "files";
  $("tab-files").classList.add("active");
  $("tab-queue").classList.remove("active");
}
$("query").addEventListener("input", () => {
  query = $("query").value;
  offset = 0;
  revision++;
  refresh();
});
$("previous").addEventListener("click", () => {
  offset = Math.max(0, offset - 100);
  revision++;
  refresh();
});
$("next-page").addEventListener("click", () => {
  offset += 100;
  revision++;
  refresh();
});
$("batch").addEventListener("click", () => run("batch"));
$("pause-downloads").addEventListener("click", () =>
  run("control", { action: paused ? "resume" : "pause" }),
);
$("cancel-downloads").addEventListener("click", () =>
  run("control", { action: "cancel" }),
);
$("folder").addEventListener("click", () => run("folder"));
$("url-cancel").addEventListener("click", () => {
  $("download-url").value = "";
  $("url-dialog").close();
});
$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await action("enqueue", { file: chosen, url: $("download-url").value });
    $("download-url").value = "";
    $("url-dialog").close();
    Toasts.show(I18n.t("Файл добавлен в очередь по указанной ссылке."), {
      type: "success",
    });
    refresh();
  } catch (e) {
    $("url-error").textContent = e.message;
    $("url-error").hidden = false;
  }
});
for (const mode of ["queue", "files"])
  $("tab-" + mode).classList.toggle("active", view === mode);
I18n.onChange(() => {
  if (lastState) renderState(lastState, false);
  if (lastList?.view === view) render(lastList.data);
  $("url-error").textContent = I18n.t($("url-error").textContent);
});
refresh();
setInterval(refresh, 2000);
