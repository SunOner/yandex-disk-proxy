"use strict";
const I18n = (() => {
  const english = {
    "Хранилище сертификата": "Certificate store",
    "Компьютер — автоматический режим": "Computer — automatic mode",
    "Текущий пользователь — совместимость": "Current user — compatibility",
    "Сертификату будут доверять приложения всех пользователей этого ПК. Windows может запросить права администратора.":
      "Applications of all users on this PC will trust the certificate. Windows may request administrator permission.",
    "Сертификату будут доверять приложения текущего пользователя. Windows может запросить подтверждение доверия.":
      "Applications of the current user will trust the certificate. Windows may request confirmation of trust.",
    "Прокси временно добавит сертификат в доверенные корневые сертификаты компьютера Windows. Ему смогут доверять приложения всех пользователей. Windows может запросить права администратора. Добавленный прокси сертификат удаляется при остановке.":
      "The proxy temporarily adds its certificate to the Windows computer's trusted roots. Applications of all users can trust it. Windows may request administrator permission. A certificate added by the proxy is removed on stop.",
    "Разрешаю временно добавить этот сертификат в доверенные корневые сертификаты компьютера Windows (для всех пользователей).":
      "Allow temporarily adding this certificate to the Windows computer's trusted roots (for all users).",
    "Неизвестное хранилище сертификата": "Unknown certificate store",
    "Не удалось установить сертификат прокси":
      "Could not install the proxy certificate",
    "Запрос прав Windows отменён": "Windows permission request was cancelled",
    "Помощник установки сертификата не ответил":
      "The certificate helper did not respond",
    "Помощник установки сертификата не вернул результат":
      "The certificate helper returned no result",
    "Не удалось изменить доверие к сертификату":
      "Could not change certificate trust",
    Настройки: "Settings",
    "Настройки ↗": "Settings ↗",
    "Настройки — Yandex Disk Proxy": "Settings — Yandex Disk Proxy",
    "Автоматическая установка": "Automatic installation",
    "Устанавливать сертификат при включении прокси. Рекомендуемый режим.":
      "Install the certificate when starting the proxy. Recommended.",
    "Добавленный прокси сертификат удаляется при остановке. Сертификаты, которым доверяли ранее, сохраняются.":
      "A certificate added by the proxy is removed on stop. Previously trusted certificates are preserved.",
    Хранилище: "Store",
    "Доверенные корневые сертификаты текущего пользователя Windows":
      "Current Windows user's trusted roots",
    "Отпечаток SHA-1": "SHA-1 fingerprint",
    "Действителен до": "Valid until",
    "Дополнительные действия": "Additional actions",
    "Установка и удаление доступны при выключенном прокси. Скачанный файл .cer нужен только для ручной диагностики.":
      "Installation and removal are available while the proxy is off. The .cer download is only needed for manual diagnostics.",
    "Проверить доверие": "Check trust",
    "Установить сертификат": "Install certificate",
    "Удалить сертификат": "Remove certificate",
    "Скачать сертификат .cer": "Download .cer certificate",
    "Подключение Диска": "Disk connection",
    "Состояние прокси": "Proxy status",
    "Открыть панель": "Open panel",
    "Выполняется…": "Working…",
    "Сначала подтвердите сертификат при включении прокси":
      "Approve the certificate when starting the proxy first",
    "Сначала выключите прокси": "Turn off the proxy first",
    "Операция с сертификатом уже выполняется":
      "A certificate operation is already running",
    "Неизвестное действие с сертификатом": "Unknown certificate action",
    "Укажите режим установки сертификата":
      "Choose a certificate installation mode",
    "Включите автоматическую установку сертификата в настройках":
      "Enable automatic certificate installation in settings",
    "Не удалось установить сертификат прокси для текущего пользователя":
      "Could not install the proxy certificate for the current user",
    "Не удалось удалить сертификат прокси":
      "Could not remove the proxy certificate",
    Ожидает: "Waiting",
    "На компьютере": "On this PC",
    "Запрос ссылки": "Requesting link",
    Загружается: "Downloading",
    "Ошибка 500": "HTTP 500 error",
    Отложен: "Deferred",
    Откладывается: "Deferring",
    "Возврат в очередь": "Returning to queue",
    "Пауза повторов": "Retry cooldown",
    Ошибка: "Error",
    " Б": " B",
    Б: "B",
    КБ: "KB",
    МБ: "MB",
    ГБ: "GB",
    ТБ: "TB",
    "Нет связи с панелью": "Panel disconnected",
    "Ошибка действия": "Action failed",
    "Прокси включён": "Proxy is on",
    "Запуск прокси": "Starting proxy",
    "Восстанавливается клиент": "Restoring client",
    "Ошибка восстановления": "Recovery failed",
    "Прокси выключен": "Proxy is off",
    Прокси: "Proxy",
    Миниатюра: "Thumbnail",
    "Миниатюра недоступна": "Thumbnail unavailable",
    "Выключить прокси и восстановить Диск": "Stop proxy and restore Disk",
    "Восстановить Диск": "Restore Disk",
    "Обновление списка…": "Refreshing files…",
    "Обновить список": "Refresh files",
    "Последнее обновление: ": "Last refreshed: ",
    ". Автоматически каждые 10 секунд.":
      ". Automatically refreshed every 10 seconds.",
    "Проверить отметки хранения в Windows":
      "Check Windows offline file selections",
    "↺ Восстановить": "↺ Recover",
    "▶ Включить прокси": "▶ Start proxy",
    "Файл сертификата Диска недоступен или изменён.":
      "The Disk certificate file is unavailable or has changed.",
    "Сертификат больше не находится в доверенных Windows.":
      "The certificate is no longer trusted by Windows.",
    "Диск отклонил TLS-соединение. Причина — в журнале.":
      "Disk rejected the TLS connection. See the logs for details.",
    "Ошибка TLS между прокси и Яндексом. Причина — в журнале.":
      "TLS failed between the proxy and Yandex. See the logs for details.",
    Состояние: "Status",
    Размер: "Size",
    "Загрузка подтверждена": "Download confirmed",
    "Нет данных": "No data",
    "Подключение при завершении": "Connection at completion",
    "Между запусками панели": "Between panel sessions",
    "Через прокси": "Through proxy",
    Напрямую: "Direct",
    "Подтверждено Windows": "Confirmed by Windows",
    "Передано по сети": "Network traffic",
    "Запросов ссылки": "Link requests",
    "Ответов HTTP 500": "HTTP 500 responses",
    "Повторов ограничено": "Retries limited",
    "Последний сервер": "Last server",
    "Ответ API ссылки": "Link API response",
    "HTTP выдачи файла": "File download HTTP status",
    "Последнее событие": "Last event",
    "API ссылки: ": "Link API: ",
    "Локальных ответов 503: ": "Local 503 responses: ",
    "Загрузка подтверждена Windows: ": "Download confirmed by Windows: ",
    "Скачать…": "Download…",
    Повторить: "Retry",
    "Файл возвращается в очередь": "Returning the file to the queue",
    Отложить: "Defer",
    "Отправлен запрос Windows": "Request sent to Windows",
    "Показано ": "Showing ",
    " из ": " of ",
    "Файлов нет": "No files",
    "Показать ещё": "Show more",
    "Панель недоступна": "Panel unavailable",
    " осталось сохранить": " left to save",
    "Всего на ПК: ": "Total on this PC: ",
    " · с ": " · since ",
    "Сохранённые ответы Яндекса": "Recorded Yandex responses",
    "Временно снята отметка хранения": "Offline selection temporarily removed",
    "Учтённые потоки, включая повторы": "Observed traffic, including retries",
    "Папка синхронизации ещё не выбрана": "No sync folder selected",
    "Не удалось получить список файлов": "Could not load the file list",
    "Не удалось обновить список файлов. ": "Could not refresh files. ",
    Скачано: "Downloaded",
    "Очередь загрузки": "Download queue",
    "Файлы с ошибками 500": "Files with HTTP 500 errors",
    "Отложенные файлы": "Deferred files",
    "Файлы на компьютере": "Files on this PC",
    "Новые загрузки": "New downloads",
    "Все отмеченные файлы": "All selected files",
    "Скачанные после начала наблюдения":
      "Files downloaded since monitoring started",
    "Файлы с отметкой «Хранить на компьютере»":
      "Files selected to keep on this PC",
    "Загрузка…": "Loading…",
    "Режим изменён.": "Mode updated.",
    "Обновление списка запрошено": "File refresh requested",
    "Выберите в Windows…": "Choose in Windows…",
    "Обзор…": "Browse…",
    "Команда отправлена. Результат появится в журнале.":
      "Command sent. The result will appear in the logs.",
    "Настройки сохранены.": "Settings saved.",
    "Настройки сохранены. Читаем список файлов…":
      "Settings saved. Reading file list…",
    "Читаем список файлов…": "Reading file list…",
    "Не удалось прочитать список файлов. См. журнал.":
      "Could not read the file list. See the logs.",
    "Сохранение…": "Saving…",
    "Проверяем папку и приложение…": "Checking the folder and application…",
    "Выберите путь в окне Windows.": "Select a path in the Windows dialog.",
    "Запуск прокси.": "Starting proxy.",
    "Остановка и восстановление запущены.":
      "Stopping proxy and restoring the client.",
    "Ожидание данных": "Waiting for data",
    "Обновлено в ": "Updated at ",
    "Последнее обновление в ": "Last updated at ",
    "Для выхода нажмите Esc": "Press Esc to exit",
    "Esc — вернуться к файлам": "Esc — back to files",
    "Табло в окне браузера · Esc — вернуться":
      "Windowed dashboard · Esc — back to files",
    "В очереди": "Queued",
    Повтор: "Retry",
    "Ожидание сессии": "Waiting for session",
    Приостановлен: "Paused",
    Остановлен: "Stopped",
    Проверен: "Verified",
    "Не скачан": "Not downloaded",
    "Ошибка запроса": "Request failed",
    "Файл добавлен в очередь.": "File queued.",
    "Добавлено в очередь: {0}.": "Files queued: {0}.",
    "Нет новых файлов для добавления.": "No new files to queue.",
    "Папка загрузок открыта.": "Download folder opened.",
    "Прямые загрузки приостановлены.": "Direct downloads paused.",
    "Прямые загрузки продолжены.": "Direct downloads resumed.",
    "Загрузка файла остановлена.": "File download stopped.",
    "Прямые загрузки остановлены.": "Direct downloads stopped.",
    "Разрешите открытие новой вкладки и повторите загрузку.":
      "Allow pop-ups and try the download again.",
    Остановить: "Stop",
    Скачать: "Download",
    Браузер: "Browser",
    "{0}–{1} из {2}": "{0}–{1} of {2}",
    "/с · до ": "/s · up to ",
    " файлов": " files",
    "Аккаунт проверен": "Account verified",
    "Сессия Диска получена": "Disk session received",
    "Ожидание запроса Диска через прокси":
      "Waiting for a Disk request through the proxy",
    "За 5 мин: {0} пустых ответов, {1} отмен":
      "Last 5 min: {0} empty responses, {1} cancellations",
    Продолжить: "Resume",
    Приостановить: "Pause",
    "Нет связи": "Disconnected",
    "Не удалось обновить загрузки. ": "Could not refresh downloads. ",
    "Файл добавлен в очередь по указанной ссылке.":
      "File queued using the supplied URL.",
    Начат: "Started",
    Ответ: "Response",
    Передача: "Transferring",
    Подключено: "Connected",
    Завершён: "Completed",
    "Нет завершения": "Incomplete",
    "С ": "Since ",
    "Выполняются: ": "Active: ",
    "Изменений файлов: ": "File changes: ",
    "В памяти: ": "In memory: ",
    " · удалено по лимиту: ": " · evicted: ",
    "{0} / {1} мс": "{0} / {1} ms",
    "Ошибка загрузки журнала": "Could not load logs",
    "Состояние: {0}": "Status: {0}",
    "Соединение: ": "Connection: ",
    "Клиентское соединение: ": "Client connection: ",
    "Адрес: ": "Address: ",
    "Размер: ": "Size: ",
    "Прежний размер: ": "Previous size: ",
    "Длительность: ": "Duration: ",
    " мс": " ms",
    "Сообщений WebSocket: ": "WebSocket messages: ",
    "Код закрытия: ": "Close code: ",
    "Отправлено: ": "Sent: ",
    "Получено: ": "Received: ",
    "Соединение установлено": "Connection established",
    "Ответ ещё не получен": "No response yet",
    "Ответ сформирован локальным прокси":
      "Response generated by the local proxy",
    "Ответ сервера": "Server response",
    "Длительность: {0} мс": "Duration: {0} ms",
    "Запрос выполняется": "Request in progress",
    "Маршрут: {0}": "Route: {0}",
    "прямая загрузка": "direct download",
    "Диск через прокси": "Disk through proxy",
    "Заголовки: {0} мс": "Headers: {0} ms",
    "Первый байт: {0} мс": "First byte: {0} ms",
    "Получено: {0} байт": "Received: {0} bytes",
    "Отправлено: {0} байт": "Sent: {0} bytes",
    "Content-Length ответа: {0} байт": "Response Content-Length: {0} bytes",
    "Подключение (DNS и TCP): {0} мс": "Connection (DNS and TCP): {0} ms",
    "TLS: {0} мс": "TLS: {0} ms",
    "Обращение №{0}": "Request #{0}",
    " · после ошибки": " · after an error",
    "Предыдущий запрос: {0} · переходов: {1}":
      "Previous request: {0} · redirects: {1}",
    "Соединение с сервером: {0}": "Server connection: {0}",
    "Соединение клиента: {0}": "Client connection: {0}",
    "Часть заголовков обрезана по лимиту размера":
      "Some headers were truncated due to the size limit",
    "После перезапуска доступна только сохранённая версия со скрытыми токенами.":
      "After restart, only the saved version with hidden tokens is available.",
    "Тело запроса и ответа не записывается.":
      "Request and response bodies are not recorded.",
    "Запись больше не доступна": "This record is no longer available",
    Событие: "Event",
    "Запрос · токены скрыты": "Request · tokens hidden",
    "Запрос · оригинал": "Request · original",
    "Записей нет": "No records",
    "Панель подключена": "Panel connected",
    "Сертификат передан только Диску": "Certificate passed only to Disk",
    "Файл сертификата недоступен или изменён":
      "Certificate file is unavailable or has changed",
    "TLS Диска установлен; сертификат передан приложению":
      "Disk TLS established; certificate passed to the client",
    "Сертификат не найден в Windows": "Certificate not found in Windows",
    "Сертификат в доверенных": "Certificate trusted",
    "Ошибка TLS": "TLS error",
    "нет данных": "no data",
    "{0} · Диск → прокси: {1} · Прокси → Яндекс: {2}":
      "{0} · Disk → proxy: {1} · Proxy → Yandex: {2}",
    "Не удалось обновить журнал. ": "Could not refresh logs. ",
    "Выберите запись": "Select a record",
    "Не удалось собрать архив": "Could not create the archive",
    "Архив диагностики передан браузеру для сохранения.":
      "Diagnostics archive sent to the browser for saving.",
    Готово: "Done",
    Информация: "Information",
    "Закрыть уведомление": "Dismiss notification",
    "Язык интерфейса": "Interface language",
    "Ссылка загрузки": "Download link",
    Скачивание: "Download",
    "Отправка файла": "Upload",
    "Ссылка отправки": "Upload link",
    Метаданные: "Metadata",
    "Список файлов": "File listing",
    Копирование: "Copy",
    Перемещение: "Move",
    Удаление: "Delete",
    "Создание папки": "Create folder",
    Корзина: "Trash",
    Восстановление: "Restore",
    Публикация: "Publish",
    "Отмена публикации": "Unpublish",
    "Состояние операции": "Operation status",
    Синхронизация: "Sync",
    "Аккаунт и место": "Account and storage",
    "Возможности сервера": "Server capabilities",
    Авторизация: "Authentication",
    "Служебный запрос": "Service request",
    "Другая операция": "Other operation",
    Соединение: "Connection",
    "Добавлен в отмеченные": "Selected for offline storage",
    "Снята отметка хранения": "Offline selection removed",
    "Удалён или перемещён": "Deleted or moved",
    "Изменён размер": "Size changed",
    "Снова требуется загрузка": "Download needed again",
    "Сохранён на ПК": "Saved on this PC",
    "Отложен прокси": "Deferred by proxy",
    "Возвращён в очередь": "Returned to queue",
    "Неизвестная операция": "Unknown operation",
    "Необычный метод": "Unusual method",
    "Ошибка HTTP": "HTTP error",
    "Сетевая ошибка": "Network error",
    "Отмена клиентом": "Cancelled by client",
    "Пустое тело ответа": "Empty response body",
    "Неполное тело ответа": "Incomplete response body",
    "Дольше 10 секунд": "Longer than 10 seconds",
    "Нет завершения 30 секунд": "Not completed within 30 seconds",
    "Повтор после ошибки": "Retry after an error",
    "Цепочка перенаправлений": "Redirect chain",
    "Некорректный путь файла": "Invalid file path",
    "Некорректная ссылка загрузки": "Invalid download URL",
    "Нужна HTTPS-ссылка загрузки Яндекса":
      "A Yandex HTTPS download URL is required",
    "Ссылка слишком длинная": "URL is too long",
    "Слишком много перенаправлений": "Too many redirects",
    "Ожидание запроса Диска для подтверждения аккаунта":
      "Waiting for a Disk request to verify the account",
    "Папка прямой загрузки должна быть вне Яндекс Диска":
      "The direct download folder must be outside Yandex Disk",
    "API вернул другой файл": "The API returned a different file",
    "API не предоставил контрольную сумму файла":
      "The API did not provide a file checksum",
    "Файл не входит в оставшуюся очередь хранения на ПК":
      "The file is not in the remaining offline queue",
    "Панель закрывается": "The panel is closing",
    "Загрузка остановлена": "Download stopped",
    "Ссылки в папке результата не поддерживаются":
      "Links in the output folder are not supported",
    "Файл удалён из очереди хранения на ПК":
      "The file was removed from the offline queue",
    "Локальный файл изменён или больше не отмечен для хранения":
      "The local file has changed or is no longer selected for offline storage",
    "Локальный файл изменился во время загрузки":
      "The local file changed during download",
    "Размер файла в облаке изменился": "The cloud file size has changed",
    "В папке результата уже есть другой файл":
      "A different file already exists in the output folder",
    "Размер временного файла превышает ожидаемый":
      "The temporary file is larger than expected",
    "Контрольная сумма не совпадает; файл не подтверждён":
      "Checksum mismatch; file not verified",
    "Файл в облаке изменился во время загрузки":
      "The cloud file changed during download",
    "Файла нет в очереди хранения на ПК":
      "The file is not in the offline queue",
    "Файл в облаке изменился": "The cloud file has changed",
    "Ссылка устарела. Запросите новую":
      "The link has expired. Request a new one",
    "Некорректный адрес API": "Invalid API URL",
    "Авторизация не передаётся серверам хранения":
      "Authentication is not sent to storage servers",
    "Ответ API превышает лимит": "The API response exceeds the size limit",
    "Не удалось прочитать ответ API": "Could not read the API response",
    "Не удалось определить аккаунт выбранной папки":
      "Could not identify the account for the selected folder",
    "Недостаточно свободного места": "Not enough free disk space",
    "Перерыв после 120 секунд загрузки; файл будет продолжен":
      "Paused after 120 seconds of downloading; the file will resume",
    "Файл больше не входит в оставшуюся очередь":
      "The file is no longer in the remaining queue",
    "Сервер сжал диапазон файла": "The server compressed the file range",
    "Неверная длина тела ответа": "Invalid response body length",
    "Неизвестное действие": "Unknown action",
    "Загрузка: HTTP {0}": "Download: HTTP {0}",
    "Сервер вернул другой диапазон файла":
      "The server returned a different file range",
    "Сервер не поддерживает продолжение загрузки":
      "The server does not support resuming downloads",
    "Обрыв тела ответа: {0} из {1} байт":
      "Response body interrupted: {0} of {1} bytes",
    "Обрыв загрузки: {0}": "Download interrupted: {0}",
    "Запись уже удалена из памяти":
      "The record has already been evicted from memory",
    "Завершение не было записано до перезапуска панели":
      "Completion was not recorded before the panel restarted",
    "Остановка и восстановление обычного клиента":
      "Stopping proxy and restoring the normal client",
    "Файла нет в списке хранения на ПК":
      "The file is not selected for offline storage",
    "Неизвестный режим": "Unknown mode",
    "Не удалось записать операцию: {0}": "Could not save operation: {0}",
    "Не удалось записать журнал: {0}": "Could not save log: {0}",
    "Сначала настройте папку синхронизации и путь к приложению":
      "Set up the sync folder and client path first",
    "Подтвердите временное доверие сертификату в панели":
      "Confirm the certificate in the panel",
    "Сеанс уже работает": "A session is already running",
    "Можно отложить только полностью нескачанный файл без локальных изменений":
      "Only a fully cloud-only file without local changes can be deferred",
    "Режим: {0}": "Mode: {0}",
    "Ожидался объект настроек": "Expected a settings object",
    "Не удалось обновить список файлов": "Could not refresh the file list",
    "Не удалось восстановить предыдущий сеанс":
      "Could not recover the previous session",
    "Прямая загрузка проверена": "Direct download verified",
    "Прямая загрузка: повтор или ошибка": "Direct download: retry or error",
    "Не удалось сохранить сводку: {0}": "Could not save summary: {0}",
    "Действие не выполнено: {0}": "Action failed: {0}",
    "Список обновлён: +{0}, −{1}; всего {2}":
      "Files refreshed: +{0}, −{1}; total {2}",
    откладывание: "deferral",
    "ограничение повторов": "retry limiting",
    наблюдение: "observation",
    "Не удалось записать запросы: {0}": "Could not save requests: {0}",
    "Сертификат удалён из доверенных. Восстановите доверие в панели":
      "The certificate is no longer trusted. Repair trust in the panel",
    "Доверие сертификату восстановлено": "Certificate trust restored",
    "Не удалось проверить доверие сертификату":
      "Could not check certificate trust",
    "Прокси завершился. Повторный запуск": "The proxy stopped. Restarting",
    "Диск перезапущен через прокси": "Disk restarted through the proxy",
    "Служебный файл временно недоступен. Повторяем операцию":
      "A service file is temporarily unavailable. Retrying",
    "Часть событий пропущена: очередь диагностики заполнена":
      "Some events were dropped: the diagnostic queue is full",
    "Сообщение прокси": "Proxy message",
    "Сеанс завершён": "Session ended",
    "Ошибка TLS: {0}": "TLS error: {0}",
    "Файл скачан": "File downloaded",
    "Сначала остановите прокси и завершите восстановление":
      "Stop the proxy and finish recovery first",
    "Сначала остановите прямые загрузки": "Stop direct downloads first",
    "Сначала остановите прокси": "Stop the proxy first",
    "Диск → прокси": "Disk → proxy",
    "прокси → Яндекс": "proxy → Yandex",
    "HTTP 500 от сервера Яндекса": "HTTP 500 from a Yandex server",
    "Файл отложен": "File deferred",
    "Исходная отметка хранения восстановлена":
      "Original offline selection restored",
    "Изменение отметки не применено; файл оставлен в исходном состоянии":
      "Offline selection was not changed; the file remains in its original state",
    "Автооткладывание не применено: состояние файла не подходит":
      "Automatic deferral skipped: the file state is not eligible",
    "Клиент отменил запрос": "Request cancelled by the client",
    "Прокси слушает только 127.0.0.1:18080":
      "Proxy listening on 127.0.0.1:18080 only",
    "Диск запущен через прокси": "Disk started through the proxy",
    "Ошибка сеанса; выполняется восстановление":
      "Session error; recovery in progress",
    "Клиент возвращён к прямому подключению":
      "Client restored to a direct connection",
    "Сетевая ошибка: {0}": "Network error: {0}",
    "Сертификат передан только процессу Диска":
      "Certificate passed only to the Disk process",
    "Сертификат установлен в Windows": "Certificate installed in Windows",
    "Сертификат передан Диску; в хранилище Windows не обнаружен":
      "Certificate passed to Disk; not found in the Windows store",
    "Сначала остановите активный сеанс": "Stop the active session first",
    "Подтвердите сертификат Диска в панели":
      "Confirm the Disk certificate in the panel",
    "Сертификат Диска изменился после подтверждения":
      "The Disk certificate changed after confirmation",
    "Укажите оба пути в настройке": "Specify both paths in settings",
    "Папка синхронизации не найдена": "Sync folder not found",
    "Укажите именно папку Яндекс Диска":
      "Select the Yandex Disk sync folder itself",
    "Переместите проект за пределы синхронизируемой папки":
      "Move the project outside the sync folder",
    "Укажите установленный YandexDisk4.exe":
      "Select the installed YandexDisk4.exe",
    "Неизвестный вид пути": "Unknown path type",
    "Окно выбора уже открыто": "A picker dialog is already open",
    "Windows не удалось открыть окно выбора":
      "Windows could not open the picker dialog",
    "Время выбора истекло. Откройте окно снова":
      "The picker timed out. Open it again",
    "Сначала выберите папку Яндекс Диска":
      "Select the Yandex Disk folder first",
    "Не найден установленный Яндекс Диск":
      "The installed Yandex Disk client was not found",
    "Некорректный отпечаток сертификата": "Invalid certificate fingerprint",
    ФАЙЛЫ: "FILES",
    "Ошибки 500": "HTTP 500 errors",
    Отложенные: "Deferred",
    "Все отмеченные": "All selected",
    "Запросы и журнал ↗": "Requests & logs ↗",
    "Прямые загрузки ↗": "Direct downloads ↗",
    "При ошибке 500": "On HTTP 500",
    "Откладывать файлы": "Defer files",
    "Ограничивать повторы": "Limit retries",
    Наблюдать: "Observe",
    "■ Остановить и восстановить": "■ Stop and restore",
    Настройка: "Settings",
    "Восстановить доверие": "Repair certificate",
    "Перезапустить Диск": "Restart Disk",
    "ОСТАЛОСЬ СКАЧАТЬ": "LEFT TO DOWNLOAD",
    "ОСТАЛОСЬ СОХРАНИТЬ": "LEFT TO SAVE",
    "Считывание списка": "Reading file list",
    "НОВЫЕ ЗАГРУЗКИ": "NEW DOWNLOADS",
    "Всего на ПК: —": "Total on this PC: —",
    "ОТВЕТЫ 500": "HTTP 500 RESPONSES",
    "сохранённые ответы Яндекса": "Recorded Yandex responses",
    ОТЛОЖЕНО: "DEFERRED",
    "временно снята отметка хранения": "offline selection temporarily removed",
    "Счётчики на весь экран": "Fullscreen counters",
    "ПЕРЕДАНО ПО СЕТИ": "NETWORK TRAFFIC",
    "0 Б": "0 B",
    "учтённые потоки, включая повторы": "observed traffic, including retries",
    "Только файлы, отмеченные для хранения на ПК":
      "Only files selected to keep on this PC",
    "Имя файла или часть пути": "File name or part of a path",
    "Найти файл": "Find a file",
    "Фильтр файлов": "File filter",
    "Не скачаны": "Not downloaded",
    "Были ошибки 500": "Had HTTP 500 errors",
    "На ПК": "On this PC",
    Файл: "File",
    Попытки: "Attempts",
    "На ПК / размер": "On PC / size",
    "Предыдущая страница": "Previous page",
    "Следующая страница": "Next page",
    Журнал: "Logs",
    "Открыть ↗": "Open ↗",
    "Папка синхронизации": "Sync folder",
    Уведомления: "Notifications",
    Закрыть: "Close",
    "ДАННЫЕ ФАЙЛА": "FILE DETAILS",
    "Сетевой объём включает повторы. Сохранение файла проверяется через Windows.":
      "Network traffic includes retries. Saved files are verified through Windows.",
    "ПОДКЛЮЧЕНИЕ ПРИЛОЖЕНИЯ": "CLIENT CONNECTION",
    "Настройка Яндекс Диска": "Yandex Disk settings",
    "Укажите папку синхронизации и приложение.":
      "Select the sync folder and the client application.",
    "Путь к папке Яндекс Диска": "Path to the Yandex Disk folder",
    "Приложение Яндекс Диск": "Yandex Disk application",
    "Полный путь к YandexDisk4.exe": "Full path to YandexDisk4.exe",
    "Скачиваются только файлы с отметкой «Хранить на компьютере».":
      "Only files selected to keep on this PC are downloaded.",
    Отмена: "Cancel",
    Сохранить: "Save",
    "ПОДКЛЮЧЕНИЕ HTTPS": "HTTPS CONNECTION",
    "Сертификат прокси": "Proxy certificate",
    "Прокси временно добавит сертификат в доверенные корневые сертификаты текущего пользователя Windows. Ему смогут доверять и другие приложения. Добавленный прокси сертификат удаляется при остановке.":
      "The proxy temporarily adds its certificate to the current Windows user's trusted roots. Other applications can also trust it. A certificate added by the proxy is removed when the proxy stops.",
    "Через прокси работает только Диск. При остановке отметки хранения восстанавливаются, Диск запускается напрямую.":
      "Only Disk uses the proxy. Stopping restores offline selections and starts Disk with a direct connection.",
    "Отпечаток сертификата этого ПК · SHA-1":
      "Certificate fingerprint on this PC · SHA-1",
    "Разрешаю временно добавить этот сертификат в доверенные корневые сертификаты моего пользователя Windows.":
      "Allow temporarily adding this certificate to my Windows user's trusted roots.",
    "Включить прокси": "Start proxy",
    "К файлам": "Back to files",
    "Осталось скачать": "Left to download",
    "Осталось сохранить": "Left to save",
    "Ответы 500": "HTTP 500 responses",
    Отложено: "Deferred",
    "Прямые загрузки — Yandex Disk Proxy":
      "Direct downloads — Yandex Disk Proxy",
    "Прямые загрузки": "Direct downloads",
    "Запросы ↗": "Requests ↗",
    "Подключение…": "Connecting…",
    "Только отмеченные для хранения файлы. Результат сохраняется отдельно; размер и контрольная сумма проверяются. Загрузки браузера проверяйте самостоятельно.":
      "Only files selected for offline storage. Downloads are saved separately and verified by size and checksum. Browser downloads must be checked separately.",
    ПРОВЕРЕНО: "VERIFIED",
    ЗАГРУЖАЕТСЯ: "DOWNLOADING",
    "0 Б/с · до 4 файлов": "0 B/s · up to 4 files",
    ОЖИДАЮТ: "WAITING",
    "Ожидание сессии Диска": "Waiting for a Disk session",
    ОШИБКИ: "ERRORS",
    "Данные за 5 минут": "Last 5 minutes",
    "Скачать оставшиеся": "Download remaining",
    "Остановить загрузки": "Stop downloads",
    "Открыть папку": "Open folder",
    "Очередь загрузок": "Download queue",
    "Файлы Диска": "Disk files",
    "Имя или часть пути": "Name or part of a path",
    "Скачано / размер": "Downloaded / size",
    Действия: "Actions",
    "Очередь пуста": "Queue is empty",
    "Загрузка по URL": "Download from URL",
    "Прямая HTTPS-ссылка загрузки Яндекса": "Direct Yandex HTTPS download URL",
    "Ссылка используется только для выбранного файла. Проверка по контрольной сумме из API. Адрес хранится в памяти до закрытия приложения.":
      "The URL is used only for the selected file and checked against the API checksum. It stays in memory until the application closes.",
    "Запросы и журнал — Yandex Disk Proxy":
      "Requests & logs — Yandex Disk Proxy",
    "Запросы и журнал": "Requests & logs",
    "Архив без токенов; пути и имена файлов сохраняются":
      "Archive without tokens; file names and paths are included",
    "Скачать диагностику": "Download diagnostics",
    Запросы: "Requests",
    События: "Events",
    "Сводка операций": "Operation summary",
    "Поиск в журнале": "Search logs",
    Поиск: "Search",
    Уровень: "Level",
    Все: "All",
    Ошибки: "Errors",
    Необычные: "Unusual",
    "Тип операции": "Operation type",
    "Все операции": "All operations",
    Протокол: "Protocol",
    "Все протоколы": "All protocols",
    Соединения: "Connections",
    "Файлы Windows": "Windows files",
    "Пауза обновления": "Pause updates",
    "Скрывать токены": "Hide tokens",
    "Методы, URL, заголовки, соединения и изменения отметок хранения. Тела запросов и файлов не записываются. Оригиналы заголовков — только в памяти.":
      "Methods, URLs, headers, connections and offline selection changes. Request and file bodies are not recorded. Original headers stay in memory only.",
    "HTTP ЗА ПЕРИОД": "HTTP IN PERIOD",
    "ОШИБКИ HTTP": "HTTP ERRORS",
    "ДРУГИЕ ОПЕРАЦИИ": "OTHER OPERATIONS",
    "ПРОПУСКИ ЗАХВАТА": "CAPTURE DROPS",
    Операции: "Operations",
    Операция: "Operation",
    Всего: "Total",
    "Повторы после ошибки": "Retries after error",
    "Среднее / максимум": "Average / maximum",
    "Отправлено / получено": "Sent / received",
    "Адреса запросов": "Request endpoints",
    "Метод и адрес": "Method and endpoint",
    Повторы: "Retries",
    "Записи журнала": "Log records",
    "Детали записи": "Record details",
    "До 5 000 записей и 32 МБ в памяти. Журналы: запросы — до 40 МБ, события — до 8 МБ, сводка — до 2 МБ. Сводные счётчики сохраняются после ротации и перезапуска.":
      "Up to 5,000 records and 32 MB in memory. Logs: requests up to 40 MB, events up to 8 MB, summary up to 2 MB. Aggregate counters survive rotation and restart.",
    " · удалено по лимиту: {0}": " · evicted: {0}",
    "Режим: откладывание": "Mode: deferral",
    "Режим: ограничение повторов": "Mode: retry limiting",
    "Режим: наблюдение": "Mode: observation",
    ...{
      Мониторинг: "Monitoring",
      "Мониторинг ↗": "Monitoring ↗",
      "Мониторинг — Yandex Disk Proxy": "Monitoring — Yandex Disk Proxy",
      "Сохранённые итоги": "Saved totals",
      "Загрузки приложения": "Native downloads",
      "Получено по сети": "Received over network",
      "Ответы HTTP 500": "HTTP 500 responses",
      "Время запроса": "Request time",
      "Среднее по завершённым HTTP-запросам": "Average completed HTTP request",
      "История по времени": "Timeline",
      Период: "Period",
      "1 час": "1 hour",
      "6 часов": "6 hours",
      "24 часа": "24 hours",
      "7 дней": "7 days",
      "30 дней": "30 days",
      "90 дней": "90 days",
      "1 год": "1 year",
      "3 года": "3 years",
      "Хранение статистики": "Statistics storage",
      "База и служебный журнал": "Database and journal",
      "Интервалы в базе": "Stored intervals",
      "Лимит файла базы": "Database file limit",
      "10 секунд — 6 часов; 1 минута — 2 дня; 1 час — 90 дней; 1 день — 3 года. Общие итоги не удаляются.":
        "10 seconds — 6 hours; 1 minute — 2 days; 1 hour — 90 days; 1 day — 3 years. Lifetime totals are retained.",
      "Сохраняются только числа. URL, имена файлов, токены и тела запросов в базу не записываются.":
        "Only numeric statistics are stored. URLs, file names, tokens and request bodies are excluded.",
      "История подтверждённых загрузок перенесена с исходным временем. Остальные графики начинаются с запуска мониторинга; пропуски означают отсутствие измерений.":
        "Confirmed download history keeps its original timestamps. Other charts start when monitoring begins; gaps mean no measurements.",
      "Сохранение каждые 5 секунд и перед выходом. При аварийном завершении могут пропасть последние 5 секунд измерений.":
        "Saved every 5 seconds and before exit. An unexpected shutdown may lose the last 5 seconds of measurements.",
      "Сетевой трафик": "Network traffic",
      Скорость: "Speed",
      Получено: "Received",
      Отправлено: "Sent",
      "Подтверждённые загрузки": "Confirmed downloads",
      "Файлов за интервал": "Files per interval",
      Приложение: "Native client",
      Прямые: "Direct queue",
      "HTTP-запросы": "HTTP requests",
      "За интервал": "Per interval",
      "Ошибки HTTP": "HTTP errors",
      "Ошибки TLS": "TLS errors",
      Файлы: "Files",
      Осталось: "Remaining",
      Отложено: "Deferred",
      "Время HTTP-запроса": "HTTP request time",
      "Среднее за интервал": "Average per interval",
      Длительность: "Duration",
      "Стрелки — время, Home и End — начало и конец.":
        "Arrow keys move through time; Home and End jump to the first and last point.",
      "Нет измерений за этот период": "No measurements in this period",
      "Сохранено: ": "Saved: ",
      "Интервал: ": "Interval: ",
      " с": " s",
      "/с": "/s",
      "Не удалось сохранить статистику. Откройте мониторинг.":
        "Could not save statistics. Open monitoring.",
      "Не удалось обновить мониторинг. ": "Could not refresh monitoring. ",
      "Статистика недоступна": "Statistics are unavailable",
      "Неизвестный период мониторинга": "Unknown monitoring period",
    },
  };
  const storageKey = "ydp.preferences.v1";
  const allowed = {
    language: ["en", "ru"],
    fileFilter: ["pending", "errors", "deferred", "downloaded", "local", "all"],
    logView: ["requests", "events", "summary"],
    logLevel: ["all", "errors", "unusual"],
    logKind: ["", "http", "tls", "connection", "websocket", "file"],
    recoveryView: ["queue", "files"],
    monitorPeriod: ["1h", "6h", "24h", "7d", "30d", "90d", "1y", "3y"],
  };
  function clean(value) {
    const result = {};
    if (value && typeof value === "object")
      for (const [key, choices] of Object.entries(allowed))
        if (choices.includes(value[key])) result[key] = value[key];
    return result;
  }
  function read() {
    try {
      return clean(JSON.parse(localStorage.getItem(storageKey)));
    } catch {
      return {};
    }
  }
  let preferences = read(),
    language = preferences.language || "en";
  const listeners = new Set(),
    pickers = [],
    rendered = new Map();
  const reverse = new Map(Object.entries(english).map(([ru, en]) => [en, ru]));
  const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = Object.entries(english)
    .filter(([key]) => /\{\d+\}/.test(key))
    .map(([ru, en]) => {
      const matcher = (value) => {
        const order = [];
        const pieces = value.split(/(\{\d+\})/).map((piece) => {
          if (/^\{\d+\}$/.test(piece)) {
            order.push(Number(piece.slice(1, -1)));
            return "([\\s\\S]*?)";
          }
          return escape(piece);
        });
        return { regex: new RegExp("^" + pieces.join("") + "$"), order };
      };
      return { ru, en, ruMatcher: matcher(ru), enMatcher: matcher(en) };
    });

  function t(source, args = []) {
    if (source === undefined || source === null) return "";
    source = String(source);
    const remembered = rendered.get(source);
    let key =
      remembered?.key ||
      (Object.hasOwn(english, source) ? source : reverse.get(source));
    if (remembered) args = remembered.args;
    if (!key) {
      for (const pattern of patterns) {
        const matchers = [
          [pattern.ruMatcher, pattern.ru],
          [pattern.enMatcher, pattern.ru],
        ];
        for (const [matcher, candidate] of matchers) {
          const match = source.match(matcher.regex);
          if (match) {
            key = candidate;
            args = [];
            matcher.order.forEach((index, n) => {
              args[index] = match[n + 1];
            });
            break;
          }
        }
        if (key) break;
      }
    }
    if (!key) return source;
    const result = (language === "en" ? english[key] : key).replace(
      /\{(\d+)\}/g,
      (_, n) => args[n] ?? "",
    );
    if (result.length < 3000) {
      rendered.delete(result);
      rendered.set(result, { key, args });
      if (rendered.size > 600) rendered.delete(rendered.keys().next().value);
    }
    return result;
  }

  function apply(root = document) {
    for (const element of root.querySelectorAll("[data-i18n]"))
      element.textContent = t(element.dataset.i18n);
    for (const attribute of ["title", "placeholder", "aria-label"])
      for (const element of root.querySelectorAll(`[data-i18n-${attribute}]`))
        element.setAttribute(
          attribute,
          t(element.getAttribute("data-i18n-" + attribute)),
        );
    for (const element of root.querySelectorAll("[data-i18n-once]")) {
      element.textContent = t(element.dataset.i18nOnce);
      element.removeAttribute("data-i18n-once");
    }
    document.documentElement.lang = language;
    document.documentElement.setAttribute("data-i18n-ready", "true");
  }

  function save(key, value) {
    if (!Object.hasOwn(allowed, key) || !allowed[key].includes(value)) return;
    preferences = { ...preferences, ...read(), [key]: value };
    try {
      localStorage.setItem(storageKey, JSON.stringify(preferences));
    } catch {}
  }
  function setLanguage(value, persist = true) {
    if (!["en", "ru"].includes(value)) return;
    if (persist) save("language", value);
    if (language === value) return;
    language = value;
    apply();
    pickers.forEach((update) => update());
    listeners.forEach((listener) => listener());
  }
  const make = (tag, cls, text) => {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  function flag(code) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 26 18");
    svg.setAttribute("width", "26");
    svg.setAttribute("height", "18");
    svg.setAttribute("class", "language-flag");
    svg.setAttribute("aria-hidden", "true");
    const shape = (tag, attrs) => {
      const child = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(attrs))
        child.setAttribute(key, value);
      svg.append(child);
    };
    if (code === "ru") {
      ["#f4f5f7", "#315ab4", "#d94c51"].forEach((fill, n) =>
        shape("rect", { x: 0, y: n * 6, width: 26, height: 6, fill }),
      );
    } else {
      shape("rect", { width: 26, height: 18, fill: "#264578" });
      shape("path", {
        d: "M0 0l26 18M26 0L0 18",
        stroke: "#f4f5f7",
        "stroke-width": 4.5,
      });
      shape("path", {
        d: "M0 0l26 18M26 0L0 18",
        stroke: "#d94c51",
        "stroke-width": 1.6,
      });
      shape("path", {
        d: "M13 0v18M0 9h26",
        stroke: "#f4f5f7",
        "stroke-width": 6,
      });
      shape("path", {
        d: "M13 0v18M0 9h26",
        stroke: "#d94c51",
        "stroke-width": 3.2,
      });
    }
    return svg;
  }
  function installPicker(host) {
    const toggle = make("button", "language-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-haspopup", "menu");
    toggle.setAttribute("aria-expanded", "false");
    const menu = make("div", "language-menu");
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    menu.id = "language-menu-" + pickers.length;
    toggle.setAttribute("aria-controls", menu.id);
    const choices = ["en", "ru"].map((code) => {
      const item = make("button", "language-option");
      item.type = "button";
      item.setAttribute("role", "menuitemradio");
      item.append(
        flag(code),
        make("span", "", code === "en" ? "English" : "Русский"),
        make("span", "language-check", "✓"),
      );
      item.addEventListener("click", () => {
        setLanguage(code);
        close();
      });
      menu.append(item);
      return { code, item };
    });
    function close() {
      menu.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus({ preventScroll: true });
    }
    toggle.addEventListener("click", () => {
      menu.hidden = !menu.hidden;
      toggle.setAttribute("aria-expanded", String(!menu.hidden));
      if (!menu.hidden)
        choices.find((choice) => choice.code === language).item.focus();
    });
    host.addEventListener("keydown", (event) => {
      if (menu.hidden) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
      if (event.key === "Tab") {
        menu.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus({ preventScroll: true });
      }
      const index = choices.findIndex(
        (choice) => choice.item === document.activeElement,
      );
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? 1
              : (index + (event.key === "ArrowDown" ? 1 : -1) + 2) % 2;
        choices[next].item.focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!menu.hidden && !host.contains(event.target)) {
        menu.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
      }
    });
    const update = () => {
      toggle.replaceChildren(
        flag(language),
        make(
          "span",
          "language-name",
          language === "en" ? "English" : "Русский",
        ),
        make("span", "language-chevron", "⌃"),
      );
      toggle.setAttribute(
        "aria-label",
        t("Язык интерфейса") +
          ": " +
          (language === "en" ? "English" : "Русский"),
      );
      menu.setAttribute("aria-label", t("Язык интерфейса"));
      choices.forEach(({ code, item }) => {
        item.setAttribute("aria-checked", String(language === code));
        item.tabIndex = language === code ? 0 : -1;
      });
    };
    host.append(toggle, menu);
    pickers.push(update);
    update();
  }

  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preferences = read();
    setLanguage(preferences.language || "en", false);
  });
  apply();
  document.querySelectorAll("[data-language-picker]").forEach(installPicker);
  return {
    t,
    get language() {
      return language;
    },
    get locale() {
      return language === "en" ? "en-GB" : "ru-RU";
    },
    get decimal() {
      return language === "en" ? "." : ",";
    },
    setLanguage,
    onChange(listener) {
      listeners.add(listener);
    },
    labels(source) {
      return new Proxy(source, {
        get: (target, key) =>
          typeof target[key] === "string" ? t(target[key]) : target[key],
      });
    },
    preferences: {
      get: (key, fallback) => preferences[key] ?? fallback,
      set: save,
    },
  };
})();
