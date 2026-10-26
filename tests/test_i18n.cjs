const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../dist/i18n.js'), 'utf8');
const key = 'ydp.preferences.v1';
function boot(saved = null, blocked = false) {
  const windowEvents = {}, documentEvents = {};
  let storage = saved;
  const document = { activeElement: null };
  function node(tag = 'div', attrs = {}) {
    return {
      tag, attributes: {...attrs}, dataset: {}, children: [], listeners: {}, hidden: false,
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute(k, v) { this.attributes[k] = v; },
      getAttribute(k) { return this.attributes[k] ?? null; },
      removeAttribute(k) { delete this.attributes[k]; },
      addEventListener(k, fn) { this.listeners[k] = fn; },
      focus() { document.activeElement = this; },
      contains(target) { return target === this || this.children.some(c => c.contains(target)); },
    };
  }
  const text = node(), once = node(), input = node();
  text.dataset.i18n = 'Прокси включён';
  once.dataset.i18nOnce = 'Ожидает';
  once.attributes['data-i18n-once'] = '';
  input.attributes['data-i18n-placeholder'] = 'Язык интерфейса';
  const hosts = [node(), node()];
  document.documentElement = node();
  document.createElement = node;
  document.createElementNS = (_, tag) => node(tag);
  document.addEventListener = (name, fn) => { (documentEvents[name] ||= []).push(fn); };
  document.querySelectorAll = selector => {
    if (selector === '[data-language-picker]') return hosts;
    if (selector === '[data-i18n]') return [text];
    if (selector === '[data-i18n-once]') return Object.hasOwn(once.attributes, 'data-i18n-once') ? [once] : [];
    if (selector === '[data-i18n-placeholder]') return [input];
    return [];
  };
  const context = vm.createContext({document, navigator: {language: 'ru-RU'},
    window: {addEventListener(name, fn) { windowEvents[name] = fn; }},
    localStorage: {
      getItem() { if (blocked) throw Error('blocked'); return storage; },
      setItem(k, value) { assert.equal(k, key); if (blocked) throw Error('blocked'); storage = value; },
    },
  });
  vm.runInContext(code, context);
  return {i18n: vm.runInContext('I18n', context), document, text, input, once, hosts,
    get saved() { return JSON.parse(storage); },
    external(value, eventKey = key) { storage = value; windowEvents.storage({key: eventKey}); },
    outside() { documentEvents.pointerdown.forEach(fn => fn({target: node()})); },
  };
}
const app = boot();
assert.equal(app.i18n.language, 'en', 'Default is English even on a Russian OS');
assert.equal(app.text.textContent, 'Proxy is on');
assert.equal(app.once.textContent, 'Waiting');
assert.equal(app.input.attributes.placeholder, 'Interface language');
assert.equal(app.document.documentElement.lang, 'en');
assert.equal(app.document.documentElement.attributes['data-i18n-ready'], 'true');
assert.equal(app.i18n.locale, 'en-GB');
assert.equal(app.i18n.decimal, '.');
assert.equal(app.i18n.t('Documents/Ошибка.txt'), 'Documents/Ошибка.txt', 'Paths are preserved');
assert.equal(app.i18n.t('Ошибка TLS: прокси → Яндекс'), 'TLS error: proxy → Yandex');
const clientTls = app.i18n.t('Ошибка TLS: Диск → прокси');
assert.equal(clientTls, 'TLS error: Disk → proxy', 'Nested labels follow the selected language');
assert.equal(app.i18n.t('Режим: наблюдение'), 'Mode: observation');
assert.equal(app.i18n.t('Действие не выполнено: Некорректная ссылка миниатюры'), 'Action failed: Invalid thumbnail URL');
assert.equal(app.i18n.t('Предыдущий запрос: {0} · переходов: {1}', ['Скачать', 2]), 'Previous request: Скачать · redirects: 2', 'Data parameters are not translated as UI labels');
for (const message of ['Помощнику сертификата нужны права администратора', 'Некорректная ссылка миниатюры', 'Не найден процесс рабочего стола для запуска Диска', '[скрыто]']) {
  assert.ok(!/[А-Яа-яЁё]/.test(app.i18n.t(message)), message);
}
const dist=path.join(__dirname,'../dist');
for (const file of fs.readdirSync(dist).filter(file=>/\.(html|js)$/.test(file))) {
  const contents=fs.readFileSync(path.join(dist,file),'utf8');
  const literals=file.endsWith('.html')
    ? [...contents.matchAll(/data-i18n(?:-once|-title|-placeholder|-aria-label)?="([^"]*)"/g)].map(match=>match[1])
    : file.endsWith('.js')&&file!=='i18n.js'
      ? [...contents.matchAll(/"(?:\\.|[^"\\])*"/g)].map(match=>{try{return JSON.parse(match[0]);}catch{return '';}})
      : [];
  for (const text of literals.filter(text=>/[А-Яа-яЁё]/.test(text)))
    assert.ok(!/[А-Яа-яЁё]/.test(app.i18n.t(text)),`${file}: missing English translation for ${text}`);
}
const dynamic = ' · удалено по лимиту: {0}';
const formatted = app.i18n.t(dynamic, [123]);
assert.ok(formatted.includes('123'));
let changes = 0;
app.i18n.onChange(() => changes++);
const [toggle, menu] = app.hosts[0].children;
assert.equal(toggle.children[0].tag, 'svg', 'Flags render as vectors on Windows');
assert.equal(menu.attributes.role, 'menu');
assert.equal(menu.children[0].attributes['aria-checked'], 'true');
toggle.listeners.click();
assert.equal(menu.hidden, false);
assert.equal(app.document.activeElement, menu.children[0]);
app.hosts[0].listeners.keydown({key: 'ArrowDown', preventDefault() {}});
assert.equal(app.document.activeElement, menu.children[1]);
menu.children[1].listeners.click();
assert.equal(app.i18n.language, 'ru');
assert.equal(app.i18n.locale, 'ru-RU');
assert.equal(app.i18n.decimal, ',');
assert.equal(app.text.textContent, 'Прокси включён');
assert.equal(app.i18n.t(formatted), ' · удалено по лимиту: 123', 'Already rendered notifications retranslate');
assert.equal(app.i18n.t(clientTls), 'Ошибка TLS: Диск → прокси', 'Nested labels also switch back to Russian');
assert.equal(app.once.textContent, 'Waiting', 'Mutable counters are not reset by static localization');
assert.equal(changes, 1);
assert.equal(menu.hidden, true);
assert.equal(app.document.activeElement, toggle);
assert.equal(app.hosts[1].children[0].children[1].textContent, 'Русский', 'All pickers stay in sync');
assert.equal(app.saved.language, 'ru');
toggle.listeners.click();
app.hosts[0].listeners.keydown({key: 'Escape', preventDefault() {}, stopPropagation() {}});
assert.equal(menu.hidden, true);
toggle.listeners.click(); app.outside(); assert.equal(menu.hidden, true);
app.i18n.preferences.set('fileFilter', 'downloaded');
app.i18n.preferences.set('logLevel', 'unusual');
for (const pref of ['mask', 'reveal', 'token', '__proto__', 'constructor']) app.i18n.preferences.set(pref, 'SECRET');
app.i18n.preferences.set('fileFilter', 'invalid');
assert.deepEqual(app.saved, {language: 'ru', fileFilter: 'downloaded', logLevel: 'unusual'});
assert.equal(boot(JSON.stringify(app.saved)).i18n.language, 'ru', 'Selection survives reload');
app.external(JSON.stringify({language: 'en', fileFilter: 'pending', reveal: true}));
assert.equal(app.i18n.language, 'en', 'Other tabs apply language changes');
assert.equal(app.i18n.preferences.get('reveal', false), false);
app.external(null, null);
assert.equal(app.i18n.language, 'en', 'Clearing site data resets to English');
for (const saved of ['{bad', 'null', '[]', '{"language":"xx","mask":false}']) assert.equal(boot(saved).i18n.language, 'en');
const blocked = boot(null, true);
blocked.i18n.setLanguage('ru');
assert.equal(blocked.i18n.language, 'ru', 'Storage errors do not block the current page');
const labels = app.i18n.labels({phase: 'Прокси включён'});
assert.equal(labels.phase, 'Proxy is on');
app.i18n.setLanguage('ru');
assert.equal(labels.phase, 'Прокси включён', 'Dynamic labels follow language changes');
const previewPrefs=boot(), preferenceChanges=[];
previewPrefs.i18n.preferences.onChange((name,value)=>preferenceChanges.push([name,value]));
assert.equal(previewPrefs.i18n.preferences.get('thumbnails',true),true,'Previews are enabled by default');
previewPrefs.i18n.preferences.set('thumbnails',false);
assert.equal(previewPrefs.saved.thumbnails,false);
assert.equal(boot(JSON.stringify(previewPrefs.saved)).i18n.preferences.get('thumbnails',true),false,'Disabled previews survive reload');
previewPrefs.i18n.preferences.set('thumbnails',false);
assert.equal(preferenceChanges.length,1,'Unchanged preferences do not notify twice');
previewPrefs.external(JSON.stringify({language:'en',thumbnails:true}));
assert.equal(preferenceChanges.at(-1)[0],'thumbnails');
assert.equal(preferenceChanges.at(-1)[1],true,'Other tabs update previews without changing language');
previewPrefs.external(null,null);
assert.equal(previewPrefs.i18n.preferences.get('thumbnails',true),true,'Clearing browser data restores enabled previews');
assert.equal(boot('{"thumbnails":"false"}').i18n.preferences.get('thumbnails',true),true,'Invalid preference types are ignored');
blocked.i18n.preferences.set('thumbnails',false);
assert.equal(blocked.i18n.preferences.get('thumbnails',true),false,'Blocked storage still permits changing previews in memory');
console.log('Localization: English default, Russian persistence, live translation, flags, keyboard, cross-tab storage, invalid preferences and secret allowlist passed.');
