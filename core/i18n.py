"""
Простая система локализации для Hua4GMon.

Подход «русский-как-ключ»:
    * исходные строки в коде остаются на русском и используются как ключи;
    * для английского хранится словарь RU → EN;
    * если перевода нет — возвращается сам ключ (русский), ничего не падает.

Это позволяет добавить второй язык в уже существующий русский UI с
минимальным риском: достаточно обернуть строку в t("..."), а её перевод
добавить в EN ниже. Отсутствие перевода не ломает интерфейс.

Модуль НЕ зависит от Tkinter/Kivy — пригоден и для Windows, и для Android.

Использование:
    from core.i18n import t, set_language, current_language

    set_language("en")
    label = t("Подключиться")        # -> "Connect"

Строки с подстановкой переводятся как шаблоны:
    t("Отличный сигнал ({pct}%)").format(pct=90)
"""
from __future__ import annotations

# Поддерживаемые языки: код → человекочитаемое имя (для меню выбора).
LANGUAGES: dict[str, str] = {
    "ru": "Русский",
    "en": "English",
    "es": "Español",
}

_DEFAULT_LANG = "es"
_current_lang = _DEFAULT_LANG

# RU → EN. Ключ — исходная русская строка (ровно как в коде).
# Если строки здесь нет, t() вернёт ключ (т.е. русский вариант).
EN: dict[str, str] = {
    'Состояние мобильных данных неизвестно. Переподключение отменено.': 'Mobile data state is unknown. Reconnect cancelled.',
    '1 поток': '1 layer',
    '{n} потока': '{n} layers',
    '{n} потоков': '{n} layers',
    'Команда отправлена, но режим антенны не подтверждён.': 'Command sent, but antenna mode was not confirmed.',
    'Мобильные данные выключены. Включите их в веб-интерфейсе роутера перед переподключением.': 'Mobile data is disabled. Enable it in the router web interface before reconnecting.',
    "От {a:.0f} до {b:.0f} с назад":
        "{a:.0f} to {b:.0f} s ago",
    "«Переподключить связь» выключает и включает мобильные данные. Интернет временно пропадёт. После перезагрузки программа переподключится сама.":
        "“Reconnect” turns mobile data off and back on. Internet access will be interrupted. After a reboot, the app reconnects automatically.",
    "Время +":
        "Time +",
    "Время −":
        "Time −",
    "Уровень +":
        "Level +",
    "Уровень −":
        "Level −",
    "График:":
        "Graph:",
    "Не прочитано":
        "Not read",
    "Последние {s:.0f} с":
        "Last {s:.0f} s",
    "«Переподключить связь» выключает и включает мобильные данные. Интернет временно пропадёт. Смена соты и улучшение сигнала не гарантируются. После перезагрузки программа переподключится сама.":
        "“Reconnect” turns mobile data off and back on. Internet access will be interrupted. A different cell or better signal is not guaranteed. After a reboot, the app reconnects automatically.",
    "Переподключить мобильную связь?\n\nМобильные данные будут выключены и включены. Интернет временно пропадёт (обычно на 5–10 секунд). Смена соты и улучшение сигнала не гарантируются.":
        "Reconnect mobile data?\n\nMobile data will be turned off and back on. Internet access will be interrupted (usually for 5–10 seconds). A different cell or better signal is not guaranteed.",
    # --- Ядро (core): статусы сигнала, ошибки, RF-подсказки, Band Lock, белые списки ---
    "CQI1 равен нулю":
        "CQI1 is zero",
    "CQI сопоставимы":
        "CQI values are similar",
    "DNS не отвечает":
        "DNS not responding",
    "TCP есть, TLS оборван ({reason})":
        "TCP ok, TLS dropped ({reason})",
    "Авто":
        "Auto",
    "МБ":
        "MB",
    "Мбит/с":
        "Mbit/s",
    ("Не удалось прочитать настройки модема — запись отменена, модем "
     "не изменён. Повторите через несколько секунд."):
        ("Could not read the modem settings — nothing was written, the modem "
         "is unchanged. Try again in a few seconds."),
    "Агрегация пропадёт: не выбраны {bands}.":
        "Carrier aggregation will stop: {bands} not selected.",
    "Медиана по последним 600 значениям, минимум и максимум за весь сбор.":
        "Median of the latest 600 values; minimum and maximum over the entire survey.",
    "Доступны цели обеих групп": "Targets in both groups responded",
    "TLS через выбранный системой или приложением маршрут (белых: {w}/{wt}, нейтральных: {n}/{nt}).":
        "TLS over the system or app route (whitelisted: {w}/{wt}, neutral: {n}/{nt}).",
    "Режим сети после записи: {mode}": "Network mode after applying: {mode}",
    "Чтение настроек сети…": "Reading network settings…",
    "Аномалия":
        "Anomaly",
    "Внешняя":
        "External",
    "Внутренняя":
        "Internal",
    "Загрузка/помехи":
        "Load/interference",
    "Идеальный":
        "Ideal",
    "Критичный":
        "Critical",
    ("Модем передаёт почти на максимуме мощности: отдача ограничена — нужна "
     "антенна точнее или выше."):
        ("The modem transmits near maximum power: upload is limited — aim the "
         "antenna better or mount it higher."),
    "Н/Д":
        "N/A",
    "Неверное имя пользователя.":
        "Wrong username.",
    "Неверный логин или пароль. Пароль — на наклейке роутера.":
        "Wrong username or password. The password is on the router's label.",
    "Неверный пароль.":
        "Wrong password.",
    ("Нейтральные сайты доступны, но «белые» не отвечают. Скорее всего, вы "
     "вышли в интернет не через 4G (другой Wi-Fi, провод, VPN). "
     "Подключитесь к Wi-Fi роутера и повторите."):
        ("Neutral sites are reachable but whitelisted ones are not. You are "
         "likely online not via 4G (another Wi-Fi, cable, VPN). Connect to the "
         "router's Wi-Fi and retry."),
    "Нет данных":
        "No data",
    "Нет интернета":
        "No internet",
    "Нет сети":
        "No service",
    ("Ни одна цель не отвечает. Либо у роутера нет связи с БС, либо "
     "проблема с DNS/маршрутом. Проверьте RSRP и трафик."):
        ("No target responds. Either the router has no cell link, or there is a "
         "DNS/route problem. Check RSRP and traffic."),
    "Нормальный":
        "Normal",
    "Отличный":
        "Excellent",
    "Отличный сигнал ({pct}%)":
        "Excellent signal ({pct}%)",
    "Очень слабый":
        "Very weak",
    "Плохой":
        "Poor",
    "Похоже на фильтрацию по SNI: TCP проходит, TLS — нет.":
        "Looks like SNI filtering: TCP passes, TLS does not.",
    ("Разрешённые сайты отвечают, а нейтральные — нет (белых: {w}/{wt}, "
     "нейтральных: 0/{nt}). Похоже на режим белых списков оператора. Для "
     "точности проверьте открытие обычного сайта в браузере."):
        ("Allowed sites respond but neutral ones do not (whitelisted: {w}/{wt}, "
         "neutral: 0/{nt}). Looks like the operator's whitelist mode. To be "
         "sure, try opening a regular site in a browser."),
    "Роутер занят — повторите через несколько секунд.":
        "Router is busy — retry in a few seconds.",
    "Роутер не отвечает: проверьте подключение к его Wi-Fi/USB и IP-адрес.":
        "Router is not responding: check the Wi-Fi/USB link and the IP address.",
    "Роутер требует сменить пароль — сделайте это в веб-интерфейсе.":
        "The router requires a password change — do it in the web interface.",
    "Сессия истекла — нужно войти заново.":
        "Session expired — log in again.",
    "Сессия устарела — нужно войти заново.":
        "Session is stale — log in again.",
    "Сигнал «гуляет»: проверьте крепление антенны и переотражения.":
        "The signal fluctuates: check the antenna mount and reflections.",
    ("Сигнал чистый, но слабый: поднимите антенну выше, возьмите антенну с "
     "большим усилением или укоротите кабель."):
        ("Signal is clean but weak: mount the antenna higher, use a higher-gain "
         "antenna or a shorter cable."),
    "Сильный":
        "Strong",
    "Слабый":
        "Weak",
    "Слабый сигнал — ищите лучше ({pct}%)":
        "Weak signal — look for a better spot ({pct}%)",
    ("Слишком много неудачных попыток входа — роутер временно заблокировал "
     "вход. Подождите несколько минут и проверьте пароль."):
        ("Too many failed login attempts — the router has temporarily blocked "
         "logins. Wait a few minutes and check the password."),
    "Смешанная":
        "Mixed",
    "Сота загружена: сравните с соседней сотой или другим бэндом.":
        "The cell is loaded: compare with a neighbor cell or another band.",
    "Средний":
        "Fair",
    "Средний сигнал — крутите антенну ({pct}%)":
        "Fair signal — adjust the antenna ({pct}%)",
    ("Текущий бэнд B{band} исключён — связь пропадёт до перерегистрации "
     "модема."):
        ("The current band B{band} is excluded — the link will drop until the "
         "modem re-registers."),
    ("Уже выполнен вход с другого устройства — закройте веб-интерфейс "
     "роутера и повторите."):
        ("Already logged in from another device — close the router's web "
         "interface and retry."),
    ("Уровень есть, но много помех: сместите азимут, попробуйте другой "
     "сектор или проверьте поляризацию."):
        ("Level is fine but interference is high: shift the azimuth, try "
         "another sector or check polarization."),
    "Функция не поддерживается этой моделью или прошивкой.":
        "Not supported by this model or firmware.",
    "Хороший":
        "Good",
    "Хороший сигнал ({pct}%)":
        "Good signal ({pct}%)",
    "Шумный":
        "Noisy",
    "на пределе":
        "at the limit",
    "норма":
        "normal",
    "ошибка ({code})":
        "error ({code})",
    "повышенная":
        "elevated",
    "CQI различаются":
        "CQI values differ",
    "соединение отклонено":
        "connection refused",
    "соединение сброшено":
        "connection reset",
    "таймаут":
        "timeout",
    "⚠ Вероятна фильтрация (белые списки)":
        "⚠ Filtering likely (whitelist)",

    # --- Общие строки Windows и Android ---
    "Band Lock применён: {bands}.":
        "Band Lock applied: {bands}.",
    "CQI кодовых слов":
        "Codeword CQI",
    "Cell (Локальный сектор)":
        "Cell (local sector)",
    "EARFCN (канал DL)":
        "EARFCN (DL channel)",
    "ICCID (SIM-карта)":
        "ICCID (SIM card)",
    "IMEI (роутер)":
        "IMEI (router)",
    "IP адрес:":
        "IP address:",
    "RSRP мин / макс":
        "RSRP min / max",
    "SIM / Устройство":
        "SIM / Device",
    "SINR мин / макс":
        "SINR min / max",
    "TAC (зона)":
        "TAC (area)",
    "eNodeB (Вышка)":
        "eNodeB (Tower)",
    "{at} смена соты: {old} → {new}":
        "{at} cell change: {old} → {new}",
    "Агрегация (CA)":
        "Aggregation (CA)",
    "Активна":
        "Active",
    "ВЫКЛЮЧЕНЫ":
        "OFF",
    "Включаю все бэнды…":
        "Enabling all bands…",
    "Включены все бэнды (AUTO).":
        "All bands enabled (AUTO).",
    "Восстанавливаю настройки…":
        "Restoring settings…",
    "Восстановлены настройки, прочитанные при подключении.":
        "Settings read at connection time have been restored.",
    "Время сессии":
        "Session time",
    "Выберите хотя бы один диапазон!":
        "Select at least one band!",
    "Зафиксировать бэнды: {bands}?":
        "Lock bands: {bands}?",
    "Информация о станции":
        "Cell info",
    "Исходные настройки не прочитаны — роутер не отдал net-mode.":
        "Original settings were not read — the router did not return net-mode.",
    "Ищу роутер…":
        "Looking for the router…",
    ("Команда отправлена, но роутер не подтвердил запись — проверьте "
     "строку «Сейчас на модеме»."):
        ("Command sent, but the router did not confirm the change — check the "
         "“Now on the modem” line."),
    "Лучшие соты за сессию":
        "Best cells this session",
    "МГц":
        "MHz",
    "Мобильные данные":
        "Mobile data",
    "Модель":
        "Model",
    "Модем перерегистрируется в сети (до ~30 с).":
        "The modem is re-registering on the network (up to ~30 s).",
    "Модуляция DL / UL":
        "Modulation DL / UL",
    "Мощность передатчика":
        "TX power",
    "Найден роутер {model} на {ip}":
        "Found router {model} at {ip}",
    ("Не удалось включить мобильные данные — включите их в веб-интерфейсе "
     "роутера."):
        ("Could not turn mobile data back on — enable it in the router's web "
         "interface."),
    ("Неверный IP-адрес: {ip}\n"
     "Пример: 192.168.8.1"):
        ("Invalid IP address: {ip}\n"
         "Example: 192.168.8.1"),
    "Неизвестный оператор":
        "Unknown operator",
    "Неизвестный режим антенны.":
        "Unknown antenna mode.",
    "Нет":
        "No",
    "Нет связи с роутером — переподключаюсь…":
        "No link to the router — reconnecting…",
    "Номер телефона":
        "Phone number",
    "Оператор (PLMN)":
        "Operator (PLMN)",
    "Отдано за сессию":
        "Uploaded this session",
    "Отметить текущие":
        "Mark current",
    "Отмечены текущие бэнды: {bands}":
        "Current bands marked: {bands}",
    "Отправляю команду перезагрузки…":
        "Sending the reboot command…",
    "Ошибка":
        "Error",
    "Пароль:":
        "Password:",
    ("Перезагрузить роутер?\n"
     "\n"
     "Соединение с интернетом прервётся на 1–2 минуты. Программа "
     "переподключится автоматически."):
        ("Reboot the router?\n"
         "\n"
         "The internet connection will drop for 1–2 minutes. The app will "
         "reconnect automatically."),
    "Переключаю антенну…":
        "Switching the antenna…",
    "Переключение антенн":
        "Antenna switching",
    "Переподключаю связь…":
        "Reconnecting the link…",
    "Пик: {v} (Δ {d})":
        "Peak: {v} (Δ {d})",
    "Подключение и частые ошибки":
        "Connection & common errors",
    "Подключение...":
        "Connecting...",
    "Проверка занимает несколько секунд.":
        "The check takes a few seconds.",
    "Подтверждение":
        "Confirm",
    "Применить":
        "Apply",
    "Применить Band Lock":
        "Apply Band Lock",
    "Применяю Band Lock…":
        "Applying Band Lock…",
    "Проверка…":
        "Checking…",
    "Прошивка":
        "Firmware",
    "Рабочий Band (LTE)":
        "Working band (LTE)",
    "Режим передачи (TM)":
        "Transmission mode (TM)",
    "Роутер не найден. Проверьте подключение к его Wi-Fi/USB.":
        "Router not found. Check the connection to its Wi-Fi/USB.",
    "Команда не выполнена: {err}":
        "Command failed: {err}",
    "Роутер перезагружается — переподключусь автоматически.":
        "The router is rebooting — I will reconnect automatically.",
    "Роутер принял команду, но сообщает другой режим антенны.":
        "The router accepted the command but reports a different antenna mode.",
    "Связь переподключена.":
        "Link reconnected.",
    "Сейчас на модеме: AUTO (все бэнды)":
        "Now on the modem: AUTO (all bands)",
    "Сейчас на модеме: {bands}":
        "Now on the modem: {bands}",
    "Сейчас на модеме: не прочитано":
        "Now on the modem: not read",
    "Сектор антенны (PCI)":
        "Antenna sector (PCI)",
    "Серийный номер":
        "Serial number",
    "Скачано за сессию":
        "Downloaded this session",
    "Скорость (Download)":
        "Speed (Download)",
    "Скорость (Upload)":
        "Speed (Upload)",
    "Сначала подключитесь к роутеру.":
        "Connect to the router first.",
    "Собираю диагностику…":
        "Collecting diagnostics…",
    "Текущий бэнд ещё не определён.":
        "The current band is not known yet.",
    "Температура чипа":
        "Chip temperature",
    "Технология":
        "Technology",
    "Тип антенны изменён: {mode}":
        "Antenna type changed: {mode}",
    "Трафик за месяц (↓/↑)":
        "Monthly traffic (↓/↑)",
    "Управление роутером":
        "Router management",
    "Фиксация частот (Band Lock)":
        "Band Lock",
    "Частота DL":
        "DL frequency",
    "Ширина канала":
        "Channel width",
    "Язык:":
        "Language:",
    "включены":
        "on",
    "нет свежих данных":
        "no fresh data",
    "⚠ Данные устарели — нет ответа {s:.0f} с":
        "⚠ Data is stale — no response for {s:.0f} s",
    "⚪ Нейтральные":
        "⚪ Neutral",
    "✅ В белых списках":
        "✅ In whitelist",
    "📶 Переподключить связь":
        "📶 Reconnect link",
    "🔄 Перезагрузить роутер":
        "🔄 Reboot router",
    "🧪 ДЕМО · азимут {a}":
        "🧪 DEMO · azimuth {a}",
    "🧪 Тестовый режим":
        "🧪 Test mode",

    # --- Windows (main.py) ---
    ("IP по умолчанию: 192.168.8.1 (для B315/B525 — 192.168.1.1 или "
     "192.168.3.1) — кнопка «Найти роутер» проверит их сама. Логин: admin, "
     "пароль — на наклейке роутера.\n"
     "\n"
     "Частые ошибки и что делать:\n"
     "• 108006 — неверный логин или пароль.\n"
     "• 108007 — слишком много неудачных попыток: роутер временно "
     "заблокировал вход. Подождите несколько минут.\n"
     "• 108003 — уже выполнен вход с другого устройства. Закройте "
     "веб-интерфейс роутера.\n"
     "• 100002 — функция не поддерживается этой моделью или прошивкой. "
     "Часть возможностей будет недоступна — это нормально.\n"
     "• 100003 / 125002 / 125003 — истекла сессия. Программа войдёт заново "
     "сама.\n"
     "• Нет ответа — проверьте, что компьютер подключён к Wi-Fi или USB "
     "именно этого роутера и IP введён верно.\n"
     "\n"
     "Тестовый режим показывает работу программы без роутера."):
        ("Default IP: 192.168.8.1 (B315/B525: 192.168.1.1 or 192.168.3.1) — the "
         "“Find router” button checks them automatically. Login: admin, the "
         "password is on the router's label.\n"
         "\n"
         "Common errors and what to do:\n"
         "• 108006 — wrong username or password.\n"
         "• 108007 — too many failed attempts: the router has temporarily "
         "blocked logins. Wait a few minutes.\n"
         "• 108003 — already logged in from another device. Close the router's "
         "web interface.\n"
         "• 100002 — not supported by this model or firmware. Some features "
         "will be unavailable — this is normal.\n"
         "• 100003 / 125002 / 125003 — session expired. The app logs in again "
         "by itself.\n"
         "• No response — make sure the computer is connected to this router's "
         "Wi-Fi or USB and the IP is correct.\n"
         "\n"
         "Test mode shows how the app works without a router."),
    "[ESC] или F11 — выход":
        "[ESC] or F11 — exit",
    "Авто-переподключение при обрыве":
        "Auto-reconnect on drop",
    "Бэнд":
        "Band",
    "Вердикт":
        "Verdict",
    "Внимание":
        "Warning",
    "Все бэнды (AUTO)":
        "All bands (AUTO)",
    "Джиттер: -":
        "Jitter: -",
    "Джиттер: {j:.1f} dB":
        "Jitter: {j:.1f} dB",
    "Диагностика сохранена: {path}. Личные номера замаскированы.":
        "Diagnostics saved: {path}. Personal identifiers are masked.",
    "Лог сессии пуст. Подключитесь и подождите, пока соберутся данные.":
        "Session log is empty. Connect and wait for data to accumulate.",
    "Лучший RSRP":
        "Best RSRP",
    "Лучший SINR":
        "Best SINR",
    "Мониторинг железа и трафика":
        "Hardware & traffic monitor",
    "Не открыть браузер: {e}":
        "Cannot open browser: {e}",
    "Не проверялось":
        "Not tested",
    "Не удалось записать файл: {e}":
        "Failed to write file: {e}",
    "Недостаточно данных о вышке (нужны PLMN и eNodeB).":
        "Not enough cell data (PLMN and eNodeB required).",
    "Общее качество связи":
        "Overall link quality",
    "Опрос (сек):":
        "Polling (sec):",
    "Отключено":
        "Disconnected",
    "Параметры роутера":
        "Router settings",
    "Перед проверкой":
        "Before testing",
    "Пик: -":
        "Peak: -",
    "Нет свежих данных":
        "No fresh data",
    "Поверх окон":
        "Always on top",
    "Построение окна…":
        "Building the window…",
    "Подключено":
        "Connected",
    "Подключитесь к роутеру":
        "Connect to the router",
    "Режим:":
        "Mode:",
    "Сбросить пики (Ctrl+R)":
        "Reset peaks (Ctrl+R)",
    "Связь с роутером потеряна":
        "Connection to the router lost",
    "Сейчас на модеме: -":
        "Now on the modem: -",
    ("Сохранено {n} записей в:\n"
     "{path}"):
        ("Saved {n} records to:\n"
         "{path}"),
    ("Фиксация бэндов привязывает модем к выбранным частотам. Список взят "
     "из модема; замеченные в эфире бэнды — первыми. Перед записью "
     "программа читает текущие настройки и меняет только LTE-бэнды; "
     "«Вернуть как было» восстановит настройки, прочитанные при подключении."):
        ("Band locking ties the modem to the selected frequencies. The list "
         "comes from the modem; bands seen on air come first. Before writing, "
         "the app reads the current settings and changes only the LTE bands; "
         "“Restore as before” brings back the settings read at connection time."),
    "Экспорт":
        "Export",
    "не проверено":
        "not tested",
    "пик {v}":
        "peak {v}",
    "↩ Вернуть как было":
        "↩ Restore as before",
    "⏹ Отключиться":
        "⏹ Disconnect",
    "⚙️ Подключение":
        "⚙️ Connection",
    ("⚠ Ноутбук должен быть подключён к Wi-Fi или USB именно этого роутера "
     "— иначе тест измерит чужой канал.\n"
     "• Применимо только для РФ."):
        ("⚠ The laptop must be connected to the Wi-Fi or USB of this exact "
         "router — otherwise the test measures a different link.\n"
         "• Applies to Russia only."),
    "🎛️ Сеть":
        "🎛️ Network",
    "💾 Экспорт CSV":
        "💾 Export CSV",
    "📈 Монитор":
        "📈 Monitor",
    "📊 Состояние":
        "📊 Status",
    "🔊 Аудио (ОС не поддерживается)":
        "🔊 Audio (OS not supported)",
    "🔊 Звук (Ctrl+M)":
        "🔊 Sound (Ctrl+M)",
    "🔍 Проверить сейчас":
        "🔍 Check now",
    "🔎 Найти роутер":
        "🔎 Find router",
    "🖥 Крышный режим (F11)":
        "🖥 Roof mode (F11)",
    "🗺 Открыть на CellMapper":
        "🗺 Open in CellMapper",
    "🗼 Вышка":
        "🗼 Tower",
    "🚀 Подключиться":
        "🚀 Connect",
    "🛡 Белые списки (РФ)":
        "🛡 Whitelist (RU)",
    "🧾 Сохранить диагностику":
        "🧾 Save diagnostics",

    # --- Android (android_main.py) ---
    "В белых списках:":
        "Whitelisted:",
    "ДЕМО · азимут {a}":
        "DEMO · azimuth {a}",
    "Найти":
        "Find",
    "Нейтральные:":
        "Neutral:",
    "Переподключить связь":
        "Reconnect link",
    "Скопировать диагностику":
        "Copy diagnostics",
    "Тестовый режим":
        "Test mode",
    "♪ Звук":
        "♪ Sound",
    "⚙ Сеть":
        "⚙ Network",
    ("IP по умолчанию: 192.168.8.1 (для B315/B525 — 192.168.1.1 или "
     "192.168.3.1) — кнопка «Найти» проверит их сама. Логин: admin, пароль "
     "— на наклейке роутера.\n"
     "\n"
     "Частые ошибки и что делать:\n"
     "• 108006 — неверный логин или пароль.\n"
     "• 108007 — слишком много неудачных попыток: роутер временно "
     "заблокировал вход. Подождите несколько минут.\n"
     "• 108003 — уже выполнен вход с другого устройства. Закройте "
     "веб-интерфейс роутера.\n"
     "• 100002 — функция не поддерживается этой моделью или прошивкой. "
     "Часть возможностей будет недоступна — это нормально.\n"
     "• 100003 / 125002 / 125003 — истекла сессия. Программа войдёт заново "
     "сама.\n"
     "• Нет ответа — проверьте, что телефон подключён к Wi-Fi именно этого "
     "роутера и IP введён верно.\n"
     "\n"
     "Тестовый режим показывает работу программы без роутера."):
        ("Default IP: 192.168.8.1 (B315/B525: 192.168.1.1 or 192.168.3.1) — the "
         "“Find” button checks them automatically. Login: admin, the password "
         "is on the router's label.\n"
         "\n"
         "Common errors and what to do:\n"
         "• 108006 — wrong username or password.\n"
         "• 108007 — too many failed attempts: the router has temporarily "
         "blocked logins. Wait a few minutes.\n"
         "• 108003 — already logged in from another device. Close the router's "
         "web interface.\n"
         "• 100002 — not supported by this model or firmware. Some features "
         "will be unavailable — this is normal.\n"
         "• 100003 / 125002 / 125003 — session expired. The app logs in again "
         "by itself.\n"
         "• No response — make sure the phone is connected to this router's "
         "Wi-Fi and the IP is correct.\n"
         "\n"
         "Test mode shows how the app works without a router."),
    "Белые списки (РФ)":
        "Whitelist (RU)",
    "Во весь экран":
        "Fullscreen",
    "Все (AUTO)":
        "All (AUTO)",
    "Диагностика скопирована в буфер обмена. Личные номера замаскированы.":
        "Diagnostics copied to the clipboard. Personal identifiers are masked.",
    "Звук недоступен на этом устройстве":
        "Sound is not available on this device",
    "Информация":
        "Information",
    "Меню":
        "Menu",
    "Нажмите «Назад» ещё раз, чтобы отключиться":
        "Press “Back” again to disconnect",
    "Отключиться":
        "Disconnect",
    "Отключиться от роутера?":
        "Disconnect from the router?",
    "Перезагрузить роутер":
        "Reboot router",
    "Переподключить":
        "Reconnect",
    "Пики сброшены":
        "Peaks reset",
    "Подключиться":
        "Connect",
    "Подсказка":
        "Help",
    "Портативный монитор LTE/5G Huawei":
        "Portable Huawei LTE/5G monitor",
    "Проверить сейчас":
        "Check now",
    "Сеть":
        "Network",
    "Состояние":
        "Status",
    ("Список взят из модема; замеченные в эфире бэнды — первыми. Меняются "
     "только LTE-бэнды; «Как было» восстановит настройки, прочитанные при "
     "подключении."):
        ("The list comes from the modem; bands seen on air come first. Only LTE "
         "bands are changed; “As before” restores the settings read at "
         "connection time."),
    "Тестовый режим (без модема)":
        "Test mode (no modem)",
    "ℹ Информация":
        "ℹ Information",
    "← Назад":
        "← Back",
    "↩ Как было":
        "↩ As before",
    "⏏ Отключиться":
        "⏏ Disconnect",
    "☀ Солнце: вкл":
        "☀ Sun mode: on",
    "☀ Солнце: выкл":
        "☀ Sun mode: off",
    "☰ Меню":
        "☰ Menu",
    ("⚠ Телефон должен быть подключён к Wi-Fi именно этого роутера — иначе "
     "тест измерит чужой канал. Применимо только для РФ."):
        ("⚠ The phone must be connected to the Wi-Fi of this exact router — "
         "otherwise the test measures a different link. Applies to Russia only."),
    "⟲ Пики":
        "⟲ Peaks",
}


EN.update({
    "Cell ID неизвестен: наблюдение не идентифицирует отдельную БС.": "Unknown Cell ID: this observation does not identify a unique base station.",
    "В сети · мобильное соединение установлено": "Registered · mobile connection established",
    "В сети · мобильные данные выключены": "Registered · mobile data switched off",
    "В сети · нет мобильного интернет-соединения": "Registered · no mobile internet connection",
    "В сети · подключение мобильных данных…": "Registered · connecting mobile data…",
    "В сети · состояние мобильных данных неизвестно": "Registered · mobile data status unknown",
    "Дополнительные соты с распознаваемыми параметрами не получены.": "No additional cells with recognized parameters received.",
    "Достигнут предел 1000 наблюдений. Остановите сбор и сохраните результат.": "Limit of 1000 observations reached. Stop and save the results.",
    "Источник: {source}; измерений: {n}; {first} — {last}": "Source: {source}; samples: {n}; {first} — {last}",
    "Копировать результат": "Copy results",
    "Начать новый сбор? Предыдущий результат будет очищен.": "Start a new survey? Previous results will be cleared.",
    "Не удалось прочитать: {name} ({error})": "Could not read: {name} ({error})",
    "Нет регистрации в мобильной сети": "Not registered on a mobile network",
    "Обнаруженные операторы (без радиометрик):": "Detected operators (without radio metrics):",
    "Оператор неизвестен": "Unknown operator",
    "Поиск операторов": "Search operators",
    "Поиск операторов…": "Searching operators…",
    "Продолжить": "Continue",
    "Регистрация в сети не подтверждена": "Network registration not confirmed",
    "Результат скопирован": "Results copied",
    "Сбор идёт": "Survey running",
    "Сбор остановлен": "Survey stopped",
    "Сканер наблюдений · Beta": "Network survey · Beta",
    "Сначала зарегистрированные сети; далее по медиане SINR, RSRQ, RSRP. Скорость не измеряется.": "Registered networks first; then median SINR, RSRQ, RSRP. Throughput is not measured.",
    "Сначала нажмите Старт.": "Press Start first.",
    "Сохранить CSV": "Save CSV",
    "Список операторов не получен. Накопление сигнала доступно.": "No operator list received. Signal collection is available.",
    "Старт": "Start",
    "Стоп": "Stop",
    "Старт → медленно вращайте антенну с остановками → Стоп. Сохраняются только наблюдения, которые отдаёт модем, не все БС вокруг. Поиск операторов может временно прервать интернет. Список операторов не содержит уровней сигнала отдельных БС.": "Start → slowly rotate the antenna, pausing between positions → Stop. Only observations reported by the modem are saved, not all nearby base stations. Operator search may interrupt internet access. The operator list has no per-cell signal measurements."
})

EN.update({
    'Роутер ответил HTTP {status}. Это ошибка локального API, а не проверка интернета.': 'Router returned HTTP {status}. This is a local API error, not an internet check.',
    'TM3 — без обратной связи': 'TM3 — open-loop',
    'TM4 — с обратной связью': 'TM4 — closed-loop',
    'Ранг MIMO LTE': 'LTE MIMO rank',
    'Ранг MIMO NR': 'NR MIMO rank',
    'Нет подтверждённых данных': 'No confirmed data',
})

# NetMonster-style signal explanations (core/netmonster.py).
EN.update({
    'Мощность принимаемого сигнала: чем выше (ближе к нулю), тем лучше.': 'Received signal power: the higher (closer to zero), the better.',
    'Отношение сигнал/шум: чем выше, тем чище сигнал.': 'Signal-to-noise ratio: the higher, the cleaner the signal.',
    'Качество и загрузка соты: чем выше, тем свободнее сота.': 'Cell quality and load: the higher, the freer the cell.',
    'Общая мощность в канале, включая шум и помехи.': 'Total power in the channel, including noise and interference.',
    'Оценка качества канала модемом: 0-15, чем выше, тем быстрее.': 'Channel quality estimated by the modem: 0-15, the higher, the faster.',
    'Мощность сигнала 5G: чем выше (ближе к нулю), тем лучше.': '5G signal power: the higher (closer to zero), the better.',
    'Отношение сигнал/шум 5G: чем выше, тем чище сигнал.': '5G signal-to-noise ratio: the higher, the cleaner the signal.',
})

# NetMonster-style UI (android_main.py): Monitor header, Cells screen.
EN.update({
    'Монитор': 'Live',
    'Соты': 'Log',
    'Графики': 'Charts',
    'Карта': 'Map',
    'Роутер не отдаёт GPS-координаты, поэтому соты нельзя показать на карте.': 'The router does not provide GPS coordinates, so cells cannot be shown on a map.',
    'Соты без координат: список ниже — только то, что сообщил модем.': 'Cells without coordinates: the list below shows only what the modem reported.',
    'Фильтры': 'Filters',
    'Все': 'All',
    'Сегодня': 'Today',
    'Блокировка бэндов и каналов': 'Band and channel lock',
    'Недавние': 'Recent',
    'Рутины': 'Routines',
    'Создать новый блок': 'Create a new lock',
    'Разблокировать всё': 'Unlock all',
    'Только бэнд': 'Single band',
    'Только бэнды': 'Bands only',
    'Нет недавних блокировок: примените одну с экрана Сеть.': 'No recent locks: apply one from the Network screen.',
    'Рутины пока недоступны в этой версии.': 'Routines are not available in this version yet.',
    'Блокировка бэндов': 'Band lock',
    'Инструменты': 'Tools',
    'Нет сот в журнале: включите сканер наблюдений.': 'No cells in the log: turn on the observation scanner.',
    'измерений: {n}': 'samples: {n}',
    'Здоровье сигнала': 'Signal health',
    'Сигнал по метрикам': 'Signal by metric',
    'Подробный журнал по бэндам': 'Detailed log by band',
    'Экспорт CSV': 'Export CSV',
    'Подробный CSV скопирован': 'Detailed CSV copied',
    'Первый раз': 'First seen',
    'Последний раз': 'Last seen',
    'Длительность': 'Duration',
    'Измерения': 'Samples',
    'Идентичность': 'Identity',
    'Канал': 'Channel',
    'Оператор': 'Operator',
    'Сигнал': 'Signal',
    'Копировать': 'Copy',
    'Скопировано': 'Copied',
    'Номер бэнда': 'Band number',
    'Название бэнда': 'Band name',
    'Имя': 'Name',
    'Настройки': 'Settings',
    'Предпочтения': 'Preferences',
    'Мониторизация в фоновом режиме': 'Background monitoring',
    'Продолжать мониторинг, когда приложение свёрнуто': 'Keep monitoring while the app is minimized',
    'Общие': 'General',
    'Данные сот, журнал и вид карты': 'Cell data, log and map view',
    'Уведомления': 'Notifications',
    'Постоянное уведомление и неизвестные соты': 'Persistent notification and unknown cells',
    'Тема': 'Theme',
    'Тёмная': 'Dark',
    'Солнце': 'Sun',
    'Язык': 'Language',
    'Звук включён': 'Sound on',
    'Звук выключен': 'Sound off',
    'Соседние соты': 'Neighbour cells',
    'Копировать журнал': 'Copy log',
    'Журнал скопирован': 'Log copied',
})


# RU → ES. Те же ключи, что и в EN; при отсутствии перевода t() вернёт ключ.
ES: dict[str, str] = {
    'Состояние мобильных данных неизвестно. Переподключение отменено.': 'Estado de los datos móviles desconocido. Reconexión cancelada.',
    '1 поток': '1 capa',
    '{n} потока': '{n} capas',
    '{n} потоков': '{n} capas',
    'Команда отправлена, но режим антенны не подтверждён.': 'Comando enviado, pero el modo de antena no se confirmó.',
    'Мобильные данные выключены. Включите их в веб-интерфейсе роутера перед переподключением.': 'Los datos móviles están desactivados. Actívelos en la interfaz web del router antes de reconectar.',
    'От {a:.0f} до {b:.0f} с назад': 'Hace de {a:.0f} a {b:.0f} s',
    '«Переподключить связь» выключает и включает мобильные данные. Интернет временно пропадёт. После перезагрузки программа переподключится сама.': '«Reconectar enlace» apaga y vuelve a encender los datos móviles. Internet se interrumpirá temporalmente. Tras un reinicio, la aplicación se reconecta sola.',
    'Время +': 'Tiempo +',
    'Время −': 'Tiempo −',
    'Уровень +': 'Nivel +',
    'Уровень −': 'Nivel −',
    'График:': 'Gráfico:',
    'Не прочитано': 'No leído',
    'Последние {s:.0f} с': 'Últimos {s:.0f} s',
    '«Переподключить связь» выключает и включает мобильные данные. Интернет временно пропадёт. Смена соты и улучшение сигнала не гарантируются. После перезагрузки программа переподключится сама.': '«Reconectar enlace» apaga y vuelve a encender los datos móviles. Internet se interrumpirá temporalmente. No se garantiza un cambio de celda ni una mejor señal. Tras un reinicio, la aplicación se reconecta sola.',
    'Переподключить мобильную связь?\n\nМобильные данные будут выключены и включены. Интернет временно пропадёт (обычно на 5–10 секунд). Смена соты и улучшение сигнала не гарантируются.': '¿Reconectar los datos móviles?\n\nLos datos móviles se apagarán y volverán a encenderse. Internet se interrumpirá temporalmente (normalmente 5–10 segundos). No se garantiza un cambio de celda ni una mejor señal.',
    'CQI1 равен нулю': 'CQI1 es cero',
    'CQI сопоставимы': 'Los CQI son similares',
    'DNS не отвечает': 'El DNS no responde',
    'TCP есть, TLS оборван ({reason})': 'TCP correcto, TLS cortado ({reason})',
    'Авто': 'Auto',
    'МБ': 'MB',
    'Мбит/с': 'Mbit/s',
    'Не удалось прочитать настройки модема — запись отменена, модем не изменён. Повторите через несколько секунд.': 'No se pudo leer la configuración del módem — no se escribió nada, el módem no cambió. Inténtelo de nuevo en unos segundos.',
    'Агрегация пропадёт: не выбраны {bands}.': 'La agregación de portadoras se perderá: no se seleccionaron {bands}.',
    'Медиана по последним 600 значениям, минимум и максимум за весь сбор.': 'Mediana de los últimos 600 valores; mínimo y máximo de todo el escaneo.',
    'Доступны цели обеих групп': 'Responden destinos de ambos grupos',
    'TLS через выбранный системой или приложением маршрут (белых: {w}/{wt}, нейтральных: {n}/{nt}).': 'TLS por la ruta elegida por el sistema o la aplicación (lista blanca: {w}/{wt}, neutrales: {n}/{nt}).',
    'Режим сети после записи: {mode}': 'Modo de red tras aplicar: {mode}',
    'Чтение настроек сети…': 'Leyendo la configuración de red…',
    'Аномалия': 'Anomalía',
    'Внешняя': 'Externa',
    'Внутренняя': 'Interna',
    'Загрузка/помехи': 'Carga/interferencia',
    'Идеальный': 'Ideal',
    'Критичный': 'Crítico',
    'Модем передаёт почти на максимуме мощности: отдача ограничена — нужна антенна точнее или выше.': 'El módem transmite casi a potencia máxima: la subida está limitada — oriente mejor la antena o colóquela más alto.',
    'Н/Д': 'N/D',
    'Неверное имя пользователя.': 'Usuario incorrecto.',
    'Неверный логин или пароль. Пароль — на наклейке роутера.': 'Usuario o contraseña incorrectos. La contraseña está en la etiqueta del router.',
    'Неверный пароль.': 'Contraseña incorrecta.',
    'Нейтральные сайты доступны, но «белые» не отвечают. Скорее всего, вы вышли в интернет не через 4G (другой Wi-Fi, провод, VPN). Подключитесь к Wi-Fi роутера и повторите.': 'Los sitios neutrales responden, pero los de la lista blanca no. Probablemente no está conectado a internet por 4G (otra Wi-Fi, cable, VPN). Conéctese a la Wi-Fi del router y vuelva a intentarlo.',
    'Нет данных': 'Sin datos',
    'Нет интернета': 'Sin internet',
    'Нет сети': 'Sin red',
    'Ни одна цель не отвечает. Либо у роутера нет связи с БС, либо проблема с DNS/маршрутом. Проверьте RSRP и трафик.': 'Ningún destino responde. O el router no tiene enlace con la estación base, o hay un problema de DNS/ruta. Revise el RSRP y el tráfico.',
    'Нормальный': 'Normal',
    'Отличный': 'Excelente',
    'Отличный сигнал ({pct}%)': 'Señal excelente ({pct}%)',
    'Очень слабый': 'Muy débil',
    'Плохой': 'Mala',
    'Похоже на фильтрацию по SNI: TCP проходит, TLS — нет.': 'Parece filtrado por SNI: TCP pasa, TLS no.',
    'Разрешённые сайты отвечают, а нейтральные — нет (белых: {w}/{wt}, нейтральных: 0/{nt}). Похоже на режим белых списков оператора. Для точности проверьте открытие обычного сайта в браузере.': 'Los sitios permitidos responden, pero los neutrales no (lista blanca: {w}/{wt}, neutrales: 0/{nt}). Parece el modo de listas blancas del operador. Para confirmarlo, abra un sitio normal en el navegador.',
    'Роутер занят — повторите через несколько секунд.': 'El router está ocupado — inténtelo de nuevo en unos segundos.',
    'Роутер не отвечает: проверьте подключение к его Wi-Fi/USB и IP-адрес.': 'El router no responde: revise la conexión Wi-Fi/USB y la dirección IP.',
    'Роутер требует сменить пароль — сделайте это в веб-интерфейсе.': 'El router exige cambiar la contraseña — hágalo en la interfaz web.',
    'Сессия истекла — нужно войти заново.': 'La sesión caducó — hay que iniciar sesión de nuevo.',
    'Сессия устарела — нужно войти заново.': 'La sesión está obsoleta — hay que iniciar sesión de nuevo.',
    'Сигнал «гуляет»: проверьте крепление антенны и переотражения.': 'La señal fluctúa: revise la sujeción de la antena y los rebotes.',
    'Сигнал чистый, но слабый: поднимите антенну выше, возьмите антенну с большим усилением или укоротите кабель.': 'Señal limpia pero débil: suba la antena, use una antena de mayor ganancia o un cable más corto.',
    'Сильный': 'Fuerte',
    'Слабый': 'Débil',
    'Слабый сигнал — ищите лучше ({pct}%)': 'Señal débil — busque un lugar mejor ({pct}%)',
    'Слишком много неудачных попыток входа — роутер временно заблокировал вход. Подождите несколько минут и проверьте пароль.': 'Demasiados intentos de inicio de sesión fallidos — el router bloqueó el acceso temporalmente. Espere unos minutos y revise la contraseña.',
    'Смешанная': 'Mixta',
    'Сота загружена: сравните с соседней сотой или другим бэндом.': 'La celda está cargada: compare con una celda vecina u otra banda.',
    'Средний': 'Media',
    'Средний сигнал — крутите антенну ({pct}%)': 'Señal media — ajuste la antena ({pct}%)',
    'Текущий бэнд B{band} исключён — связь пропадёт до перерегистрации модема.': 'La banda actual B{band} queda excluida — la conexión se perderá hasta que el módem se vuelva a registrar.',
    'Уже выполнен вход с другого устройства — закройте веб-интерфейс роутера и повторите.': 'Ya hay una sesión iniciada desde otro dispositivo — cierre la interfaz web del router y vuelva a intentarlo.',
    'Уровень есть, но много помех: сместите азимут, попробуйте другой сектор или проверьте поляризацию.': 'Hay nivel, pero mucha interferencia: cambie el azimut, pruebe otro sector o revise la polarización.',
    'Функция не поддерживается этой моделью или прошивкой.': 'No compatible con este modelo o firmware.',
    'Хороший': 'Buena',
    'Хороший сигнал ({pct}%)': 'Señal buena ({pct}%)',
    'Шумный': 'Ruidosa',
    'на пределе': 'al límite',
    'норма': 'normal',
    'ошибка ({code})': 'error ({code})',
    'повышенная': 'elevada',
    'CQI различаются': 'Los CQI difieren',
    'соединение отклонено': 'conexión rechazada',
    'соединение сброшено': 'conexión restablecida',
    'таймаут': 'tiempo agotado',
    '⚠ Вероятна фильтрация (белые списки)': '⚠ Probable filtrado (listas blancas)',
    'Band Lock применён: {bands}.': 'Band Lock aplicado: {bands}.',
    'CQI кодовых слов': 'CQI por palabra de código',
    'Cell (Локальный сектор)': 'Cell (sector local)',
    'EARFCN (канал DL)': 'EARFCN (canal DL)',
    'ICCID (SIM-карта)': 'ICCID (tarjeta SIM)',
    'IMEI (роутер)': 'IMEI (router)',
    'IP адрес:': 'Dirección IP:',
    'RSRP мин / макс': 'RSRP mín / máx',
    'SIM / Устройство': 'SIM / Dispositivo',
    'SINR мин / макс': 'SINR mín / máx',
    'TAC (зона)': 'TAC (zona)',
    'eNodeB (Вышка)': 'eNodeB (Torre)',
    '{at} смена соты: {old} → {new}': '{at} cambio de celda: {old} → {new}',
    'Агрегация (CA)': 'Agregación (CA)',
    'Активна': 'Activa',
    'ВЫКЛЮЧЕНЫ': 'DESACTIVADOS',
    'Включаю все бэнды…': 'Activando todas las bandas…',
    'Включены все бэнды (AUTO).': 'Todas las bandas activadas (AUTO).',
    'Восстанавливаю настройки…': 'Restaurando la configuración…',
    'Восстановлены настройки, прочитанные при подключении.': 'Se restauró la configuración leída al conectar.',
    'Время сессии': 'Tiempo de sesión',
    'Выберите хотя бы один диапазон!': '¡Seleccione al menos una banda!',
    'Зафиксировать бэнды: {bands}?': '¿Fijar bandas: {bands}?',
    'Информация о станции': 'Información de la estación',
    'Исходные настройки не прочитаны — роутер не отдал net-mode.': 'No se leyó la configuración original — el router no devolvió net-mode.',
    'Ищу роутер…': 'Buscando el router…',
    'Команда отправлена, но роутер не подтвердил запись — проверьте строку «Сейчас на модеме».': 'Comando enviado, pero el router no confirmó el cambio — revise la línea «Ahora en el módem».',
    'Лучшие соты за сессию': 'Mejores celdas de la sesión',
    'МГц': 'MHz',
    'Мобильные данные': 'Datos móviles',
    'Модель': 'Modelo',
    'Модем перерегистрируется в сети (до ~30 с).': 'El módem se está volviendo a registrar en la red (hasta ~30 s).',
    'Модуляция DL / UL': 'Modulación DL / UL',
    'Мощность передатчика': 'Potencia de transmisión',
    'Найден роутер {model} на {ip}': 'Router {model} encontrado en {ip}',
    'Не удалось включить мобильные данные — включите их в веб-интерфейсе роутера.': 'No se pudieron volver a activar los datos móviles — actívelos en la interfaz web del router.',
    'Неверный IP-адрес: {ip}\nПример: 192.168.8.1': 'Dirección IP no válida: {ip}\nEjemplo: 192.168.8.1',
    'Неизвестный оператор': 'Operador desconocido',
    'Неизвестный режим антенны.': 'Modo de antena desconocido.',
    'Нет': 'No',
    'Нет связи с роутером — переподключаюсь…': 'Sin conexión con el router — reconectando…',
    'Номер телефона': 'Número de teléfono',
    'Оператор (PLMN)': 'Operador (PLMN)',
    'Отдано за сессию': 'Subido en la sesión',
    'Отметить текущие': 'Marcar actuales',
    'Отмечены текущие бэнды: {bands}': 'Bandas actuales marcadas: {bands}',
    'Отправляю команду перезагрузки…': 'Enviando el comando de reinicio…',
    'Ошибка': 'Error',
    'Пароль:': 'Contraseña:',
    'Перезагрузить роутер?\n\nСоединение с интернетом прервётся на 1–2 минуты. Программа переподключится автоматически.': '¿Reiniciar el router?\n\nLa conexión a internet se cortará durante 1–2 minutos. La aplicación se reconectará automáticamente.',
    'Переключаю антенну…': 'Cambiando la antena…',
    'Переключение антенн': 'Cambio de antena',
    'Переподключаю связь…': 'Reconectando el enlace…',
    'Пик: {v} (Δ {d})': 'Pico: {v} (Δ {d})',
    'Подключение и частые ошибки': 'Conexión y errores frecuentes',
    'Подключение...': 'Conectando...',
    'Проверка занимает несколько секунд.': 'La comprobación tarda unos segundos.',
    'Подтверждение': 'Confirmación',
    'Применить': 'Aplicar',
    'Применить Band Lock': 'Aplicar Band Lock',
    'Применяю Band Lock…': 'Aplicando Band Lock…',
    'Проверка…': 'Comprobando…',
    'Прошивка': 'Firmware',
    'Рабочий Band (LTE)': 'Banda en uso (LTE)',
    'Режим передачи (TM)': 'Modo de transmisión (TM)',
    'Роутер не найден. Проверьте подключение к его Wi-Fi/USB.': 'Router no encontrado. Revise la conexión a su Wi-Fi/USB.',
    'Команда не выполнена: {err}': 'El comando falló: {err}',
    'Роутер перезагружается — переподключусь автоматически.': 'El router se está reiniciando — me reconectaré automáticamente.',
    'Роутер принял команду, но сообщает другой режим антенны.': 'El router aceptó el comando, pero informa otro modo de antena.',
    'Связь переподключена.': 'Enlace reconectado.',
    'Сейчас на модеме: AUTO (все бэнды)': 'Ahora en el módem: AUTO (todas las bandas)',
    'Сейчас на модеме: {bands}': 'Ahora en el módem: {bands}',
    'Сейчас на модеме: не прочитано': 'Ahora en el módem: no leído',
    'Сектор антенны (PCI)': 'Sector de antena (PCI)',
    'Серийный номер': 'Número de serie',
    'Скачано за сессию': 'Descargado en la sesión',
    'Скорость (Download)': 'Velocidad (descarga)',
    'Скорость (Upload)': 'Velocidad (subida)',
    'Сначала подключитесь к роутеру.': 'Primero conéctese al router.',
    'Собираю диагностику…': 'Recopilando diagnóstico…',
    'Текущий бэнд ещё не определён.': 'La banda actual aún no se conoce.',
    'Температура чипа': 'Temperatura del chip',
    'Технология': 'Tecnología',
    'Тип антенны изменён: {mode}': 'Tipo de antena cambiado: {mode}',
    'Трафик за месяц (↓/↑)': 'Tráfico del mes (↓/↑)',
    'Управление роутером': 'Gestión del router',
    'Фиксация частот (Band Lock)': 'Fijación de bandas (Band Lock)',
    'Частота DL': 'Frecuencia DL',
    'Ширина канала': 'Ancho de canal',
    'Язык:': 'Idioma:',
    'включены': 'activados',
    'нет свежих данных': 'sin datos recientes',
    '⚠ Данные устарели — нет ответа {s:.0f} с': '⚠ Datos desactualizados — sin respuesta desde hace {s:.0f} s',
    '⚪ Нейтральные': '⚪ Neutrales',
    '✅ В белых списках': '✅ En listas blancas',
    '📶 Переподключить связь': '📶 Reconectar enlace',
    '🔄 Перезагрузить роутер': '🔄 Reiniciar router',
    '🧪 ДЕМО · азимут {a}': '🧪 DEMO · azimut {a}',
    '🧪 Тестовый режим': '🧪 Modo de prueba',
    'IP по умолчанию: 192.168.8.1 (для B315/B525 — 192.168.1.1 или 192.168.3.1) — кнопка «Найти роутер» проверит их сама. Логин: admin, пароль — на наклейке роутера.\n\nЧастые ошибки и что делать:\n• 108006 — неверный логин или пароль.\n• 108007 — слишком много неудачных попыток: роутер временно заблокировал вход. Подождите несколько минут.\n• 108003 — уже выполнен вход с другого устройства. Закройте веб-интерфейс роутера.\n• 100002 — функция не поддерживается этой моделью или прошивкой. Часть возможностей будет недоступна — это нормально.\n• 100003 / 125002 / 125003 — истекла сессия. Программа войдёт заново сама.\n• Нет ответа — проверьте, что компьютер подключён к Wi-Fi или USB именно этого роутера и IP введён верно.\n\nТестовый режим показывает работу программы без роутера.': 'IP por defecto: 192.168.8.1 (B315/B525: 192.168.1.1 o 192.168.3.1) — el botón «Buscar router» las prueba automáticamente. Usuario: admin, la contraseña está en la etiqueta del router.\n\nErrores frecuentes y qué hacer:\n• 108006 — usuario o contraseña incorrectos.\n• 108007 — demasiados intentos fallidos: el router bloqueó el acceso temporalmente. Espere unos minutos.\n• 108003 — ya hay una sesión iniciada desde otro dispositivo. Cierre la interfaz web del router.\n• 100002 — no compatible con este modelo o firmware. Algunas funciones no estarán disponibles — es normal.\n• 100003 / 125002 / 125003 — la sesión caducó. La aplicación vuelve a iniciar sesión sola.\n• Sin respuesta — compruebe que el ordenador esté conectado a la Wi-Fi o USB de este router y que la IP sea correcta.\n\nEl modo de prueba muestra cómo funciona la aplicación sin router.',
    '[ESC] или F11 — выход': '[ESC] o F11 — salir',
    'Авто-переподключение при обрыве': 'Reconexión automática si se corta',
    'Бэнд': 'Banda',
    'Вердикт': 'Veredicto',
    'Внимание': 'Atención',
    'Все бэнды (AUTO)': 'Todas las bandas (AUTO)',
    'Джиттер: -': 'Jitter: -',
    'Джиттер: {j:.1f} dB': 'Jitter: {j:.1f} dB',
    'Диагностика сохранена: {path}. Личные номера замаскированы.': 'Diagnóstico guardado: {path}. Los números personales están enmascarados.',
    'Лог сессии пуст. Подключитесь и подождите, пока соберутся данные.': 'El registro de la sesión está vacío. Conéctese y espere a que se acumulen datos.',
    'Лучший RSRP': 'Mejor RSRP',
    'Лучший SINR': 'Mejor SINR',
    'Мониторинг железа и трафика': 'Monitor de hardware y tráfico',
    'Не открыть браузер: {e}': 'No se pudo abrir el navegador: {e}',
    'Не проверялось': 'Sin comprobar',
    'Не удалось записать файл: {e}': 'No se pudo escribir el archivo: {e}',
    'Недостаточно данных о вышке (нужны PLMN и eNodeB).': 'Datos de la torre insuficientes (se necesitan PLMN y eNodeB).',
    'Общее качество связи': 'Calidad general de la conexión',
    'Опрос (сек):': 'Sondeo (s):',
    'Отключено': 'Desconectado',
    'Параметры роутера': 'Parámetros del router',
    'Перед проверкой': 'Antes de comprobar',
    'Пик: -': 'Pico: -',
    'Нет свежих данных': 'Sin datos recientes',
    'Поверх окон': 'Siempre visible',
    'Построение окна…': 'Construyendo la ventana…',
    'Подключено': 'Conectado',
    'Подключитесь к роутеру': 'Conéctese al router',
    'Режим:': 'Modo:',
    'Сбросить пики (Ctrl+R)': 'Restablecer picos (Ctrl+R)',
    'Связь с роутером потеряна': 'Se perdió la conexión con el router',
    'Сейчас на модеме: -': 'Ahora en el módem: -',
    'Сохранено {n} записей в:\n{path}': 'Se guardaron {n} registros en:\n{path}',
    'Фиксация бэндов привязывает модем к выбранным частотам. Список взят из модема; замеченные в эфире бэнды — первыми. Перед записью программа читает текущие настройки и меняет только LTE-бэнды; «Вернуть как было» восстановит настройки, прочитанные при подключении.': 'La fijación de bandas ata el módem a las frecuencias elegidas. La lista procede del módem; las bandas detectadas en el aire aparecen primero. Antes de escribir, la aplicación lee la configuración actual y cambia solo las bandas LTE; «Dejar como estaba» restaura la configuración leída al conectar.',
    'Экспорт': 'Exportar',
    'не проверено': 'sin comprobar',
    'пик {v}': 'pico {v}',
    '↩ Вернуть как было': '↩ Dejar como estaba',
    '⏹ Отключиться': '⏹ Desconectar',
    '⚙️ Подключение': '⚙️ Conexión',
    '⚠ Ноутбук должен быть подключён к Wi-Fi или USB именно этого роутера — иначе тест измерит чужой канал.\n• Применимо только для РФ.': '⚠ El portátil debe estar conectado a la Wi-Fi o USB de este mismo router — si no, la prueba medirá otro enlace.\n• Solo aplicable en Rusia.',
    '🎛️ Сеть': '🎛️ Red',
    '💾 Экспорт CSV': '💾 Exportar CSV',
    '📈 Монитор': '📈 Monitor',
    '📊 Состояние': '📊 Estado',
    '🔊 Аудио (ОС не поддерживается)': '🔊 Audio (SO no compatible)',
    '🔊 Звук (Ctrl+M)': '🔊 Sonido (Ctrl+M)',
    '🔍 Проверить сейчас': '🔍 Comprobar ahora',
    '🔎 Найти роутер': '🔎 Buscar router',
    '🖥 Крышный режим (F11)': '🖥 Modo tejado (F11)',
    '🗺 Открыть на CellMapper': '🗺 Abrir en CellMapper',
    '🗼 Вышка': '🗼 Torre',
    '🚀 Подключиться': '🚀 Conectar',
    '🛡 Белые списки (РФ)': '🛡 Listas blancas (RU)',
    '🧾 Сохранить диагностику': '🧾 Guardar diagnóstico',
    'В белых списках:': 'En listas blancas:',
    'ДЕМО · азимут {a}': 'DEMO · azimut {a}',
    'Найти': 'Buscar',
    'Нейтральные:': 'Neutrales:',
    'Переподключить связь': 'Reconectar enlace',
    'Скопировать диагностику': 'Copiar diagnóstico',
    'Тестовый режим': 'Modo de prueba',
    '♪ Звук': '♪ Sonido',
    '⚙ Сеть': '⚙ Red',
    'IP по умолчанию: 192.168.8.1 (для B315/B525 — 192.168.1.1 или 192.168.3.1) — кнопка «Найти» проверит их сама. Логин: admin, пароль — на наклейке роутера.\n\nЧастые ошибки и что делать:\n• 108006 — неверный логин или пароль.\n• 108007 — слишком много неудачных попыток: роутер временно заблокировал вход. Подождите несколько минут.\n• 108003 — уже выполнен вход с другого устройства. Закройте веб-интерфейс роутера.\n• 100002 — функция не поддерживается этой моделью или прошивкой. Часть возможностей будет недоступна — это нормально.\n• 100003 / 125002 / 125003 — истекла сессия. Программа войдёт заново сама.\n• Нет ответа — проверьте, что телефон подключён к Wi-Fi именно этого роутера и IP введён верно.\n\nТестовый режим показывает работу программы без роутера.': 'IP por defecto: 192.168.8.1 (B315/B525: 192.168.1.1 o 192.168.3.1) — el botón «Buscar» las prueba automáticamente. Usuario: admin, la contraseña está en la etiqueta del router.\n\nErrores frecuentes y qué hacer:\n• 108006 — usuario o contraseña incorrectos.\n• 108007 — demasiados intentos fallidos: el router bloqueó el acceso temporalmente. Espere unos minutos.\n• 108003 — ya hay una sesión iniciada desde otro dispositivo. Cierre la interfaz web del router.\n• 100002 — no compatible con este modelo o firmware. Algunas funciones no estarán disponibles — es normal.\n• 100003 / 125002 / 125003 — la sesión caducó. La aplicación vuelve a iniciar sesión sola.\n• Sin respuesta — compruebe que el teléfono esté conectado a la Wi-Fi de este router y que la IP sea correcta.\n\nEl modo de prueba muestra cómo funciona la aplicación sin router.',
    'Белые списки (РФ)': 'Listas blancas (RU)',
    'Во весь экран': 'Pantalla completa',
    'Все (AUTO)': 'Todas (AUTO)',
    'Диагностика скопирована в буфер обмена. Личные номера замаскированы.': 'Diagnóstico copiado al portapapeles. Los números personales están enmascarados.',
    'Звук недоступен на этом устройстве': 'El sonido no está disponible en este dispositivo',
    'Информация': 'Información',
    'Меню': 'Menú',
    'Нажмите «Назад» ещё раз, чтобы отключиться': 'Pulse «Atrás» otra vez para desconectar',
    'Отключиться': 'Desconectar',
    'Отключиться от роутера?': '¿Desconectarse del router?',
    'Перезагрузить роутер': 'Reiniciar router',
    'Переподключить': 'Reconectar',
    'Пики сброшены': 'Picos restablecidos',
    'Подключиться': 'Conectar',
    'Подсказка': 'Ayuda',
    'Портативный монитор LTE/5G Huawei': 'Monitor portátil LTE/5G para Huawei',
    'Проверить сейчас': 'Comprobar ahora',
    'Сеть': 'Red',
    'Состояние': 'Estado',
    'Список взят из модема; замеченные в эфире бэнды — первыми. Меняются только LTE-бэнды; «Как было» восстановит настройки, прочитанные при подключении.': 'La lista procede del módem; las bandas detectadas en el aire aparecen primero. Solo se cambian las bandas LTE; «Como estaba» restaura la configuración leída al conectar.',
    'Тестовый режим (без модема)': 'Modo de prueba (sin módem)',
    'ℹ Информация': 'ℹ Información',
    '← Назад': '← Atrás',
    '↩ Как было': '↩ Como estaba',
    '⏏ Отключиться': '⏏ Desconectar',
    '☀ Солнце: вкл': '☀ Modo sol: sí',
    '☀ Солнце: выкл': '☀ Modo sol: no',
    '☰ Меню': '☰ Menú',
    '⚠ Телефон должен быть подключён к Wi-Fi именно этого роутера — иначе тест измерит чужой канал. Применимо только для РФ.': '⚠ El teléfono debe estar conectado a la Wi-Fi de este mismo router — si no, la prueba medirá otro enlace. Solo aplicable en Rusia.',
    '⟲ Пики': '⟲ Picos',
    'Cell ID неизвестен: наблюдение не идентифицирует отдельную БС.': 'Cell ID desconocido: esta observación no identifica una estación base concreta.',
    'В сети · мобильное соединение установлено': 'En red · conexión móvil establecida',
    'В сети · мобильные данные выключены': 'En red · datos móviles desactivados',
    'В сети · нет мобильного интернет-соединения': 'En red · sin conexión a internet móvil',
    'В сети · подключение мобильных данных…': 'En red · conectando datos móviles…',
    'В сети · состояние мобильных данных неизвестно': 'En red · estado de los datos móviles desconocido',
    'Дополнительные соты с распознаваемыми параметрами не получены.': 'No se recibieron celdas adicionales con parámetros reconocibles.',
    'Достигнут предел 1000 наблюдений. Остановите сбор и сохраните результат.': 'Se alcanzó el límite de 1000 observaciones. Detenga el escaneo y guarde el resultado.',
    'Источник: {source}; измерений: {n}; {first} — {last}': 'Fuente: {source}; mediciones: {n}; {first} — {last}',
    'Копировать результат': 'Copiar resultado',
    'Начать новый сбор? Предыдущий результат будет очищен.': '¿Iniciar un nuevo escaneo? El resultado anterior se borrará.',
    'Не удалось прочитать: {name} ({error})': 'No se pudo leer: {name} ({error})',
    'Нет регистрации в мобильной сети': 'Sin registro en la red móvil',
    'Обнаруженные операторы (без радиометрик):': 'Operadores detectados (sin métricas de radio):',
    'Оператор неизвестен': 'Operador desconocido',
    'Поиск операторов': 'Buscar operadores',
    'Поиск операторов…': 'Buscando operadores…',
    'Продолжить': 'Continuar',
    'Регистрация в сети не подтверждена': 'Registro en la red no confirmado',
    'Результат скопирован': 'Resultado copiado',
    'Сбор идёт': 'Escaneo en curso',
    'Сбор остановлен': 'Escaneo detenido',
    'Сканер наблюдений · Beta': 'Escáner de observaciones · Beta',
    'Сначала зарегистрированные сети; далее по медиане SINR, RSRQ, RSRP. Скорость не измеряется.': 'Primero las redes registradas; luego por mediana de SINR, RSRQ, RSRP. La velocidad no se mide.',
    'Сначала нажмите Старт.': 'Primero pulse Iniciar.',
    'Сохранить CSV': 'Guardar CSV',
    'Список операторов не получен. Накопление сигнала доступно.': 'No se recibió la lista de operadores. La recogida de señal sigue disponible.',
    'Старт': 'Iniciar',
    'Стоп': 'Detener',
    'Старт → медленно вращайте антенну с остановками → Стоп. Сохраняются только наблюдения, которые отдаёт модем, не все БС вокруг. Поиск операторов может временно прервать интернет. Список операторов не содержит уровней сигнала отдельных БС.': 'Iniciar → gire la antena despacio, con pausas entre posiciones → Detener. Solo se guardan las observaciones que informa el módem, no todas las estaciones base cercanas. La búsqueda de operadores puede interrumpir internet temporalmente. La lista de operadores no incluye niveles de señal de cada estación base.',
    'Роутер ответил HTTP {status}. Это ошибка локального API, а не проверка интернета.': 'El router devolvió HTTP {status}. Es un error de la API local, no una comprobación de internet.',
    'TM3 — без обратной связи': 'TM3 — sin realimentación',
    'TM4 — с обратной связью': 'TM4 — con realimentación',
    'Ранг MIMO LTE': 'Rango MIMO LTE',
    'Ранг MIMO NR': 'Rango MIMO NR',
    'Нет подтверждённых данных': 'Sin datos confirmados',
    # Explicaciones de señal estilo NetMonster (core/netmonster.py).
    'Мощность принимаемого сигнала: чем выше (ближе к нулю), тем лучше.': 'Potencia de la señal recibida: cuanto más alta (más cerca de cero), mejor.',
    'Отношение сигнал/шум: чем выше, тем чище сигнал.': 'Relación señal/ruido: cuanto más alta, más limpia la señal.',
    'Качество и загрузка соты: чем выше, тем свободнее сота.': 'Calidad y carga de la celda: cuanto más alta, más libre la celda.',
    'Общая мощность в канале, включая шум и помехи.': 'Potencia total en el canal, incluidos el ruido y las interferencias.',
    'Оценка качества канала модемом: 0-15, чем выше, тем быстрее.': 'Calidad del canal estimada por el módem: 0-15, cuanto más alta, más rápida.',
    'Мощность сигнала 5G: чем выше (ближе к нулю), тем лучше.': 'Potencia de la señal 5G: cuanto más alta (más cerca de cero), mejor.',
    'Отношение сигнал/шум 5G: чем выше, тем чище сигнал.': 'Relación señal/ruido 5G: cuanto más alta, más limpia la señal.',
    # Interfaz estilo NetMonster (android_main.py): cabecera del Monitor, pantalla Celdas.
    'Монитор': 'En vivo',
    'Соты': 'Registro',
    'Графики': 'Gráficos',
    'Карта': 'Mapa',
    'Роутер не отдаёт GPS-координаты, поэтому соты нельзя показать на карте.': 'El router no entrega ubicación GPS, así que las celdas no se pueden mostrar en el mapa.',
    'Соты без координат: список ниже — только то, что сообщил модем.': 'Celdas sin coordenadas: la lista muestra solo lo que informó el módem.',
    'Фильтры': 'Filtros',
    'Все': 'Todos',
    'Сегодня': 'Hoy',
    'Блокировка бэндов и каналов': 'Bloqueo de bandas y canales',
    'Недавние': 'Recientes',
    'Рутины': 'Rutinas',
    'Создать новый блок': 'Crear un nuevo bloqueo',
    'Разблокировать всё': 'Desbloquear todo',
    'Только бэнд': 'Solo banda',
    'Только бэнды': 'Solo bandas',
    'Нет недавних блокировок: примените одну с экрана Сеть.': 'Sin bloqueos recientes: aplica uno desde la pantalla Red.',
    'Рутины пока недоступны в этой версии.': 'Las rutinas aún no están disponibles en esta versión.',
    'Блокировка бэндов': 'Bloqueo de bandas',
    'Инструменты': 'Herramientas',
    'Нет сот в журнале: включите сканер наблюдений.': 'Sin celdas en el registro: activa el escáner de observaciones.',
    'измерений: {n}': 'mediciones: {n}',
    'Здоровье сигнала': 'Salud de la señal',
    'Сигнал по метрикам': 'Señal por métrica',
    'Подробный журнал по бэндам': 'Registro detallado por banda',
    'Экспорт CSV': 'Exportar CSV',
    'Подробный CSV скопирован': 'CSV detallado copiado',
    'Первый раз': 'Primera vez',
    'Последний раз': 'Última vez',
    'Длительность': 'Duración',
    'Измерения': 'Muestras',
    'Идентичность': 'Identidad',
    'Канал': 'Canal',
    'Оператор': 'Operador',
    'Сигнал': 'Señal',
    'Копировать': 'Copiar',
    'Скопировано': 'Copiado',
    'Номер бэнда': 'Número de banda',
    'Название бэнда': 'Nombre de banda',
    'Имя': 'Nombre',
    'Настройки': 'Ajustes',
    'Предпочтения': 'Preferencias',
    'Мониторизация в фоновом режиме': 'Monitorización en segundo plano',
    'Продолжать мониторинг, когда приложение свёрнуто': 'Seguir monitorizando cuando la aplicación está minimizada',
    'Общие': 'General',
    'Данные сот, журнал и вид карты': 'Datos de celdas, registro y vista del mapa',
    'Уведомления': 'Notificaciones',
    'Постоянное уведомление и неизвестные соты': 'Notificación persistente y celdas desconocidas',
    'Тема': 'Tema',
    'Тёмная': 'Oscuro',
    'Солнце': 'Sol',
    'Язык': 'Idioma',
    'Звук включён': 'Sonido activado',
    'Звук выключен': 'Sonido desactivado',
    'Соседние соты': 'Celdas vecinas',
    'Копировать журнал': 'Copiar registro',
    'Журнал скопирован': 'Registro copiado',
}


_TRANSLATIONS: dict[str, dict[str, str]] = {"en": EN, "es": ES}


def set_language(lang: str) -> None:
    """Устанавливает текущий язык ('ru', 'en' или 'es'). Неизвестный — игнор."""
    global _current_lang
    if lang in LANGUAGES:
        _current_lang = lang


def current_language() -> str:
    """Возвращает код текущего языка."""
    return _current_lang


def t(text: str) -> str:
    """Переводит строку на текущий язык.

    Русский — возвращает ключ как есть. Английский/испанский — ищет в
    EN/ES, при отсутствии возвращает ключ (русский) как fallback.
    """
    if _current_lang == "ru":
        return text
    return _TRANSLATIONS[_current_lang].get(text, text)
