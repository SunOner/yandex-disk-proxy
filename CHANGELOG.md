# Changelog

## 0.7.0

- Added a Monitoring page with six interactive time charts, eight ranges, English/Russian labels and live updates.
- Main counters and numeric statistics now persist in SQLite, separately for each sync folder. Existing confirmed download history retains its timestamps.
- Two tables retain at most 8,299 aggregate time buckets across four resolutions. Expired detail is pruned automatically; lifetime totals remain. The database file is capped at 16 MiB.
- Statistics are checkpointed every five seconds and on clean exit. No URLs, file identities, headers, tokens or request bodies are stored in SQLite.

## 0.6.1

- Panel updates now follow server change notifications, with bounded refreshes and polling only when the stream is unavailable.
- Lists retain their rows and controls. New entries slide in together with the existing rows, without staggered jumps.
- Reading positions and keyboard focus survive inserts, reordering and progress updates. Unchanged snapshots do not mutate list DOM.
- Hidden tabs suspend their stream; returning to the page resynchronizes it. Reduced-motion settings and journal pause remain supported.

## 0.6.0

- Renamed the project, interface, executable metadata and repository to Yandex Disk Proxy.
- English is now the default; Russian remains available through a flag menu at the bottom left.
- Language changes apply immediately to all pages, open tabs, dialogs, notifications and the fullscreen dashboard.
- Browser preferences retain the language and selected views and filters. Original-token visibility is never saved.
- Localized number and date formatting, native picker captions, English startup messages and bilingual documentation.


## 0.5.7

- Прокрутка изменившихся разрядов в счётчиках; повторный опрос не перезапускает анимацию.
- Полноэкранное табло с крупными цифрами; выход кнопкой или Esc.
- При недоступности полного экрана табло открывается в окне браузера.
- Сохранение последних показателей при потере связи, учёт отключённых анимаций Windows.

## 0.5.6

- Новый векторный знак: диск со стрелкой загрузки на тёмной подложке.
- Обновлена надпись в боковом меню; знак масштабируется вместе с узким меню.

## 0.5.5

- Общие всплывающие уведомления на страницах файлов, журнала и прямых загрузок.
- Анимация появления и скрытия, закрытие кнопкой, пауза при наведении и фокусе клавиатуры.
- Повторяющиеся ошибки обновления показываются один раз до изменения состояния.
- Ошибки заполнения форм и постоянные статусы остаются рядом с соответствующими элементами.

## 0.3.0

- Системные окна выбора папки и приложения.
- Исправлена остановка сеанса при временной блокировке служебного файла Windows.
- Проверка доверия сертификату, восстановление по кнопке, раздельные ошибки TLS.
- Повторный запуск прокси после сбоя, до трёх попыток за пять минут.
- Отдельная вкладка запросов и событий, поиск, фильтр ошибок и пауза обновления.
- Токены скрыты по умолчанию; оригинальные заголовки доступны только из памяти.
- Ротация журналов и ограничение объёма записей в памяти. События убраны из консоли.

## 0.2.1

- Убраны заголовки, пояснения и служебные блоки с главного экрана.
- При смене режима отложенные файлы возвращаются в очередь.
- Исправлены статусы скачанных файлов, ошибок доступа и повторов.
- Исправлены переключение фильтров и пустая последняя страница.
- Ошибки настройки показаны внутри окна; при потере связи действия блокируются.

## 0.2.0

- EXE для Windows x64 со встроенными Python и mitmproxy.
- Данные EXE перенесены в профиль Windows.
- Команды `--stop` и `--recover`.
- Сокращены тексты интерфейса и инструкции.

## 0.1.0

- Очередь файлов, ошибки HTTP, журнал и счётчик загрузок.
- Наблюдение, ограничение повторов и откладывание файлов.
- Ручное включение и выключение, восстановление отметок и сертификата.
