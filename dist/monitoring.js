"use strict";
const MonitoringCharts = (() => {
  const definitions = [
    {
      id: "traffic",
      title: "Сетевой трафик",
      unit: "Скорость",
      kind: "rate",
      series: [
        ["received_bytes", "Получено", "#83dcb2"],
        ["sent_bytes", "Отправлено", "#91b5ff"],
      ],
    },
    {
      id: "downloads",
      title: "Подтверждённые загрузки",
      unit: "Файлов за интервал",
      kind: "downloads",
      series: [
        ["native_files", "Приложение", "#83dcb2"],
        ["direct_files", "Прямые", "#b3a1ff"],
      ],
    },
    {
      id: "requests",
      title: "HTTP-запросы",
      unit: "За интервал",
      kind: "count",
      series: [["requests", "Запросы", "#91b5ff"]],
    },
    {
      id: "errors",
      title: "Ошибки",
      unit: "За интервал",
      kind: "count",
      series: [
        ["http500_all", "HTTP 500", "#ff9f93"],
        ["http_errors", "Ошибки HTTP", "#e5bf70"],
        ["tls_errors", "Ошибки TLS", "#b3a1ff"],
      ],
    },
    {
      id: "queue",
      title: "Очередь загрузки",
      unit: "Файлы",
      kind: "gauge",
      series: [
        ["pending_files", "Осталось", "#91b5ff"],
        ["deferred_files", "Отложено", "#e5bf70"],
      ],
    },
    {
      id: "duration",
      title: "Время HTTP-запроса",
      unit: "Среднее за интервал",
      kind: "duration",
      series: [["average", "Длительность", "#b3a1ff"]],
    },
  ];
  function value(point, key, kind) {
    if (point.missing) return null;
    if (kind === "rate")
      return point.seconds > 0 ? point[key] / point.seconds : null;
    if (kind === "duration")
      return point.timed_requests > 0
        ? point.duration_ms / point.timed_requests
        : null;
    if (kind === "gauge") return point[key] ?? null;
    if (kind === "downloads")
      return point.seconds > 0 ||
        point.native_files > 0 ||
        point.direct_files > 0
        ? point[key]
        : null;
    return point.seconds > 0 ? point[key] : null;
  }
  function path(values, left, top, width, height, max) {
    let result = "",
      connected = false;
    values.forEach((value, i) => {
      if (!Number.isFinite(value)) {
        connected = false;
        return;
      }
      const x = left + (i / Math.max(1, values.length - 1)) * width,
        y = top + height - (value / max) * height;
      result += (connected ? " L" : " M") + x.toFixed(2) + " " + y.toFixed(2);
      connected = true;
    });
    return result.trim();
  }
  function maximum(values) {
    const max = Math.max(0, ...values.filter(Number.isFinite));
    if (!max) return 1;
    const power = 10 ** Math.floor(Math.log10(max)),
      ratio = max / power;
    return (ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 5 ? 5 : 10) * power;
  }
  return { definitions, value, path, maximum };
})();
(() => {
  const $ = (id) => document.getElementById(id),
    ns = "http://www.w3.org/2000/svg";
  let period = I18n.preferences.get("monitorPeriod", "24h"),
    busy = false,
    queued = false,
    last = null,
    connected = false,
    attempted = false;
  const charts = new Map();
  const text = (element, value) => {
    if (element.textContent !== String(value)) element.textContent = value;
  };
  const number = (n) =>
    new Intl.NumberFormat(I18n.locale, { maximumFractionDigits: 1 }).format(
      n || 0,
    );
  function bytes(n) {
    let i = 0;
    const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
    while (n >= 1024 && i < 4) {
      n /= 1024;
      i++;
    }
    return number(n) + " " + I18n.t(units[i]);
  }
  const time = (n) => new Date(n * 1000).toLocaleString(I18n.locale);
  const formatted = (n, kind) =>
    kind === "rate"
      ? bytes(n) + I18n.t("/с")
      : kind === "duration"
        ? number(n) + I18n.t(" мс")
        : number(n);
  function svg(tag, attrs = {}, content) {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (content !== undefined) node.textContent = content;
    return node;
  }
  function makeChart(def) {
    const card = document.createElement("article");
    card.className = "chart-card";
    const heading = document.createElement("div");
    heading.className = "chart-heading";
    const title = document.createElement("h3"),
      unit = document.createElement("span");
    unit.className = "chart-unit";
    heading.append(title, unit);
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    const names = def.series.map(([, name, color]) => {
      const span = document.createElement("span"),
        dot = document.createElement("i"),
        label = document.createElement("span");
      dot.style.background = color;
      span.append(dot, label);
      legend.append(span);
      return { label, name };
    });
    const plot = svg("svg", {
      viewBox: "0 0 920 260",
      class: "chart-plot",
      tabindex: "0",
      role: "img",
      "aria-describedby": "readout-" + def.id,
    });
    const grid = [],
      xLabels = [];
    for (let i = 0; i <= 4; i++) {
      const y = 15 + i * 51;
      plot.append(
        svg("line", { x1: 78, x2: 900, y1: y, y2: y, class: "chart-grid" }),
      );
      const label = svg("text", {
        x: 68,
        y: y + 4,
        "text-anchor": "end",
        class: "chart-axis",
      });
      plot.append(label);
      grid.push(label);
    }
    for (let i = 0; i <= 4; i++) {
      const label = svg("text", {
        x: 78 + i * 205.5,
        y: 247,
        "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle",
        class: "chart-axis",
      });
      plot.append(label);
      xLabels.push(label);
    }
    const paths = def.series.map(([, name, color]) => {
      const line = svg("path", { class: "chart-line", stroke: color });
      const dot = svg("circle", { r: 3, fill: color });
      plot.append(line, dot);
      return { line, dot };
    });
    const cursor = svg("line", {
      x1: 78,
      x2: 78,
      y1: 15,
      y2: 219,
      class: "chart-crosshair",
      visibility: "hidden",
    });
    plot.append(cursor);
    const empty = svg("text", {
      x: 489,
      y: 115,
      "text-anchor": "middle",
      class: "chart-empty",
    });
    plot.append(empty);
    const readout = document.createElement("div");
    readout.className = "chart-readout";
    readout.id = "readout-" + def.id;
    readout.setAttribute("aria-live", "polite");
    card.append(heading, legend, plot, readout);
    $("charts").append(card);
    const chart = {
      def,
      title,
      unit,
      names,
      plot,
      grid,
      xLabels,
      paths,
      cursor,
      empty,
      readout,
      index: null,
      points: [],
      values: [],
    };
    function inspect(index) {
      if (!chart.points.length) return;
      chart.index = Math.max(0, Math.min(chart.points.length - 1, index));
      const p = chart.points[chart.index],
        x = 78 + (chart.index / Math.max(1, chart.points.length - 1)) * 822;
      cursor.setAttribute("x1", x);
      cursor.setAttribute("x2", x);
      cursor.setAttribute("visibility", "visible");
      text(
        readout,
        time(p.at) +
          " · " +
          def.series
            .map(
              ([, name], i) =>
                I18n.t(name) +
                ": " +
                (chart.values[i][chart.index] === null
                  ? "—"
                  : formatted(chart.values[i][chart.index], def.kind)),
            )
            .join(" · ") +
          (def.id === "queue" &&
          p.pending_bytes !== undefined &&
          p.pending_bytes !== null
            ? " · " + bytes(p.pending_bytes)
            : ""),
      );
    }
    plot.addEventListener("pointermove", (event) => {
      const box = plot.getBoundingClientRect();
      inspect(
        Math.round(
          ((((event.clientX - box.left) / box.width) * 920 - 78) / 822) *
            (chart.points.length - 1),
        ),
      );
    });
    plot.addEventListener("pointerleave", () => {
      chart.index = null;
      cursor.setAttribute("visibility", "hidden");
      text(readout, " ");
    });
    plot.addEventListener("focus", () => inspect(chart.points.length - 1));
    plot.addEventListener("blur", () => {
      chart.index = null;
      cursor.setAttribute("visibility", "hidden");
      text(readout, " ");
    });
    plot.addEventListener("keydown", (event) => {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        inspect(
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? chart.points.length - 1
              : (chart.index ?? chart.points.length - 1) +
                (event.key === "ArrowLeft" ? -1 : 1),
        );
      }
    });
    chart.inspect = inspect;
    return chart;
  }
  function render(data) {
    const totals = data.totals,
      current = data.current;
    for (const [id, value] of Object.entries({
      "native-files": number(totals.native_files),
      "native-bytes": bytes(totals.native_bytes),
      "direct-files": number(totals.direct_files),
      "direct-bytes": bytes(totals.direct_bytes),
      received: bytes(totals.received_bytes),
      sent: I18n.t("Отправлено") + ": " + bytes(totals.sent_bytes),
      errors500: number(totals.http500_all),
      "http-errors": I18n.t("Ошибки HTTP") + ": " + number(totals.http_errors),
      pending: number(current.pending_files),
      "pending-bytes": bytes(current.pending_bytes),
      "request-time": totals.timed_requests
        ? formatted(totals.duration_ms / totals.timed_requests, "duration")
        : "—",
      "storage-size": bytes(data.storage.bytes),
      "storage-rows":
        number(data.storage.buckets) + " / " + number(data.storage.max_buckets),
      "storage-limit": bytes(data.storage.max_database_bytes),
      "saved-at":
        I18n.t("Сохранено: ") +
        time(data.saved_at) +
        " · " +
        I18n.t("Интервал: ") +
        number(data.step) +
        I18n.t(" с"),
    }))
      text($(id), value);
    for (const def of MonitoringCharts.definitions) {
      const chart = charts.get(def.id);
      chart.points = data.points;
      chart.values = def.series.map(([key]) =>
        data.points.map((point) =>
          MonitoringCharts.value(point, key, def.kind),
        ),
      );
      const max = MonitoringCharts.maximum(chart.values.flat());
      text(chart.title, I18n.t(def.title));
      text(chart.unit, I18n.t(def.unit));
      chart.names.forEach(({ label, name }) => text(label, I18n.t(name)));
      chart.plot.setAttribute(
        "aria-label",
        I18n.t(def.title) +
          ". " +
          I18n.t("Стрелки — время, Home и End — начало и конец."),
      );
      chart.grid.forEach((label, i) =>
        text(label, formatted(max * (1 - i / 4), def.kind)),
      );
      chart.xLabels.forEach((label, i) => {
        const at =
          data.points[Math.round((i / 4) * (data.points.length - 1))]?.at;
        text(
          label,
          at === undefined
            ? ""
            : new Date(at * 1000).toLocaleString(
                I18n.locale,
                data.period.endsWith("h")
                  ? { hour: "2-digit", minute: "2-digit" }
                  : {
                      day: "2-digit",
                      month: "2-digit",
                      ...(data.period.endsWith("y") ? { year: "2-digit" } : {}),
                    },
              ),
        );
      });
      chart.paths.forEach(({ line, dot }, i) => {
        const values = chart.values[i];
        line.setAttribute(
          "d",
          MonitoringCharts.path(values, 78, 15, 822, 204, max),
        );
        const index = values.findLastIndex(Number.isFinite);
        dot.setAttribute("visibility", index < 0 ? "hidden" : "visible");
        if (index >= 0) {
          dot.setAttribute(
            "cx",
            78 + (index / Math.max(1, values.length - 1)) * 822,
          );
          dot.setAttribute("cy", 219 - (values[index] / max) * 204);
        }
      });
      text(
        chart.empty,
        chart.values.some((values) => values.some(Number.isFinite))
          ? ""
          : I18n.t("Нет измерений за этот период"),
      );
      if (chart.index !== null) chart.inspect(chart.index);
    }
    text(
      $("connection"),
      connected ? I18n.t("Панель подключена") : I18n.t("Нет связи с панелью"),
    );
    $("connection").classList.toggle("offline", !connected);
  }
  async function refresh() {
    if (busy) {
      queued = true;
      return;
    }
    busy = true;
    const requested = period;
    try {
      const response = await fetch(
        "/api/monitoring?" + new URLSearchParams({ period: requested }),
        { signal: AbortSignal.timeout(10000) },
      );
      const data = await response.json();
      if (!response.ok) throw Error(I18n.t(data.error));
      if (requested !== period) {
        queued = true;
        return;
      }
      connected = true;
      last = data;
      render(data);
      Toasts.problem("connection", "");
      Toasts.problem(
        "statistics",
        data.error
          ? I18n.t("Не удалось сохранить статистику. Откройте мониторинг.") +
              " " +
              data.error
          : "",
      );
    } catch (error) {
      connected = false;
      text($("connection"), I18n.t("Нет связи с панелью"));
      $("connection").classList.add("offline");
      Toasts.problem(
        "connection",
        I18n.t("Не удалось обновить мониторинг. ") + error.message,
      );
    } finally {
      busy = false;
      attempted = true;
      if (queued) {
        queued = false;
        queueMicrotask(refresh);
      }
    }
  }
  MonitoringCharts.definitions.forEach((def) =>
    charts.set(def.id, makeChart(def)),
  );
  $("period").value = period;
  $("period").addEventListener("change", () => {
    period = $("period").value;
    I18n.preferences.set("monitorPeriod", period);
    refresh();
  });
  I18n.onChange(() => {
    if (last) render(last);
    else
      text(
        $("connection"),
        I18n.t(attempted ? "Нет связи с панелью" : "Подключение…"),
      );
  });
  refresh();
  LivePanel.subscribe(refresh, ["metrics"]);
})();
