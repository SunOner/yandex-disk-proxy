"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let snapshot = null,
    certificate = null,
    connected = false,
    busy = false,
    fetching = false,
    actionError = "";
  function render() {
    $("connection").textContent = I18n.t(
      connected ? "Панель подключена" : "Нет связи с панелью",
    );
    if (!snapshot || !certificate) return;
    const working = busy || certificate.job?.busy;
    const stopped = ["idle", "stopped"].includes(snapshot.session.phase);
    $("automatic").checked = certificate.automatic;
    $("automatic").disabled = !connected || working;
    $("scope").value = certificate.scope;
    $("scope").disabled = !connected || working || !stopped;
    $("scope-note").textContent = I18n.t(
      certificate.scope === "local_machine"
        ? "Сертификату будут доверять приложения всех пользователей этого ПК. Windows может запросить права администратора."
        : "Сертификату будут доверять приложения текущего пользователя. Windows может запросить подтверждение доверия.",
    );
    $("install").disabled =
      !connected || working || !stopped || !certificate.approved;
    $("remove").disabled =
      !connected || working || !stopped || !certificate.trusted;
    $("check").disabled = !connected || working;
    $("certificate-status").textContent = I18n.t(
      working
        ? "Выполняется…"
        : certificate.trusted
          ? "Сертификат в доверенных"
          : "Сертификат не найден в Windows",
    );
    $("certificate-status").className = certificate.trusted ? "trusted" : "";
    $("thumbprint").textContent = certificate.thumbprint
      .match(/.{1,4}/g)
      .join(" ");
    $("expires").textContent = new Date(certificate.expires).toLocaleString(
      I18n.locale,
    );
    $("root").textContent = snapshot.root || "—";
    $("client").textContent = snapshot.client || "—";
    $("proxy-status").textContent = I18n.t(
      snapshot.session.phase === "active"
        ? "Прокси включён"
        : stopped
          ? "Прокси выключен"
          : "Выполняется…",
    );
    $("certificate-message").hidden = certificate.approved;
    $("certificate-message").textContent = I18n.t(
      "Сначала подтвердите сертификат при включении прокси",
    );
    const error = actionError || certificate.job?.error;
    $("certificate-error").hidden = !error;
    $("certificate-error").textContent = error ? I18n.t(error) : "";
  }
  async function refresh() {
    if (fetching) return;
    fetching = true;
    try {
      const responses = await Promise.all([
        fetch("/api/state"),
        fetch("/api/certificate"),
      ]);
      if (responses.some((r) => !r.ok)) throw new Error("Нет связи с панелью");
      [snapshot, certificate] = await Promise.all(
        responses.map((r) => r.json()),
      );
      connected = true;
    } catch {
      connected = false;
    } finally {
      fetching = false;
      render();
    }
  }
  async function action(path, data) {
    if (busy || !connected) return;
    actionError = "";
    busy = true;
    render();
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Panel-Nonce": snapshot.nonce,
        },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      await refresh();
    } catch (error) {
      actionError = error.message;
      return;
    } finally {
      busy = false;
      render();
    }
  }
  $("automatic").addEventListener("change", () =>
    action("/api/certificate/settings", { automatic: $("automatic").checked }),
  );
  $("scope").addEventListener("change", () =>
    action("/api/certificate/settings", {
      automatic: $("automatic").checked,
      scope: $("scope").value,
    }),
  );
  $("check").addEventListener("click", refresh);
  for (const name of ["install", "remove"])
    $(name).addEventListener("click", () =>
      action("/api/certificate/action", { action: name }),
    );
  I18n.onChange(render);
  LivePanel.subscribe(refresh, ["state"]);
  refresh();
})();
