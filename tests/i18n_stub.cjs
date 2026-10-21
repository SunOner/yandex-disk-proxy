// Keep existing behavioural tests in Russian; test_i18n covers the English default.
module.exports = () => ({
  locale: "ru-RU",
  decimal: ",",
  language: "ru",
  t: (key, values = []) =>
    String(key ?? "").replace(/\{(\d+)\}/g, (_, n) => values[n] ?? ""),
  labels: (value) => value,
  onChange() {},
  preferences: { get: (_, fallback) => fallback, set() {} },
});
