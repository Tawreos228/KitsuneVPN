# Kitsune — БИБА (мастер-контекст для продолжения после сжатия)

> Команда пользователя **«обнови бибу»** = обновить ЭТОТ файл (docs/DEV_NOTES.md) актуальным состоянием.
> Это авторитетный документ. Источник правды — код (`app.py`, `qml/App/*`, `engine.py`).
> Старый `…/nekobox-ui/HANDOFF.md` — УСТАРЕЛ (там старый план C++-форка); актуальное — здесь.

## 0. TL;DR
Проект **Kitsune** — десктоп VPN-клиент (Windows). Репозиторий **github.com/Tawreos228/KitsuneVPN** (PRIVATE).
Локально: `C:\Users\danii\Documents\KitsuneVPN`.
- **UI:** PySide6 + QML (Qt Quick) — готов и отполирован (эппловский стиль, анимации, 3 темы).
- **Движок:** Python (`engine.py`) управляет **ядром sing-box** как отдельным процессом.
  По умолчанию берётся **`core/nekobox_core.exe`** (патченый sing-box, больше протоколов) через CLI `sing-box run -c`;
  если его нет — официальный `core/sing-box.exe`. Ядро то же, что у NekoBox → **скорость/качество идентичны**.
- Сейчас UI работает на **моковом** `Backend` (в app.py). `engine.py` уже умеет генерить конфиг/валидировать/
  запускать-останавливать ядро, но **ещё НЕ связан с Backend** (это след. шаг).

## 1. ПРАВИЛА/ТРЕБОВАНИЯ пользователя (соблюдать!)
- **Панель логов — СКРЫТА.** В обычном виде клиента её не должно быть видно. Открывается ТОЛЬКО отдельной
  кнопкой в Settings по желанию юзера. (Реализовать так, когда дойдём до логов.)
- Проект «чисто свой», **без брендинга NekoBox** в UI/репо и без атрибуции (в т.ч. без "Claude" в коммитах).
  (Использование их core-бинаря как процесса — это технический выбор движка, не брендинг.)
- Общение по-русски. По одной задаче за раз. После правок: smoke-тест → скриншот → перезапуск → краткий отчёт.
- Эстетика: сдержанный Apple, мягкие цвета в тёмной теме (кольцо не должно «бить в глаза»).
- Честность: где паритет с NekoBox, где наши добавки, где ещё не сделано.

## 2. Решения и ПОЧЕМУ
- **Не форкаем C++ NekoBox.** Причины: их «движок» = sing-box core (Go) + C++-обвязка, вплетённая в их Qt-приложение
  (= снова форк); GPL-3.0 (при раздаче обязал бы открыть исходники + сохранить атрибуцию — против «чистого своего»);
  тяжёлая сборка (статический Qt + Thrift + Docker). Python+sing-box: чисто, легко, собирается PyInstaller.
- **Качество = от ядра sing-box** (то же, что у NekoBox). Python не в «горячем пути» данных.
- **Берём их core-бинарь** (nekobox_core.exe) ради экзотических протоколов (mieru/juicity/amnezia/xhttp/kcp/
  vless-encryption), которых нет в официальном sing-box. Дёргать как отдельный процесс — лицензионно чисто.

## 3. Стек / запуск / команды
- PySide6 6.11 / Qt 6.11, Python 3.14. QtQuick.Controls **Basic**. Шрифты: Segoe UI Variable / Segoe Fluent Icons.
- Зависимости: PySide6, segno (QR), Pillow (gen_icon).
- Ядро: `python core/fetch_core.py` тянет официальный sing-box; для патченого — положить `nekobox_core.exe` в `core/`
  (берётся из установленного NekoBox: `%AppData%\NekoBox\nekobox_core.exe`). `core/*.exe` в .gitignore (не коммитим).
- Запуск приложения: `python app.py` (окно + трей; закрытие → трей).
- Smoke-тест QML: `python _smoketest.py` (ждать LOADED:True / WARN:0). (Файл лежит в старом nekobox-ui; при нужде создать тут.)
- Скриншоты: `QT_QPA_PLATFORM=windows python _capture.py` (offscreen даёт «тофу» вместо шрифтов!).
- Перезапуск: глушить старый процесс (PowerShell: убить python.exe/pythonw.exe c CommandLine `*app.py*`).

## 4. Файлы
- **app.py:** `Backend` (МОК-движок: всё состояние + Property/Slot/Signal; таймеры имитируют connect/ping/tick);
  `HotkeyManager` (WinAPI RegisterHotKey + нативный фильтр); `AppController` (трей с анимацией, жизненный цикл UI,
  снимок настроек); `main()`.
- **engine.py:** РЕАЛЬНЫЙ движок (готов, но не подключён к Backend): `core_cmd()` (авто-выбор nekobox_core/sing-box),
  `build_outbound`/`gen_config` (vless/vmess/trojan/ss + TLS/Reality/uTLS + transport ws/grpc/httpupgrade + mixed inbound + route),
  `check_config` (sing-box check), `port_listening`, класс `Core` (start/stop/running). Проверено: ядро стартует, порт 2080 поднимается.
- **qml/App/**: Main.qml (окно/страницы/модалки), Theme.qml (singleton, scheme dark/light/kitsune),
  ConnectButton, ServerCard, Waveform, ModeSwitch, Segmented, Toggle, ThemeToggle, IconButton, ValueField,
  ChipRow, SettingRow, HotkeyField, Toast; qmldir.
- **assets/**: icon.png/.ico + tray/f00..f13.png (анимация китсунэ: f00 выглянул=подключено, f13 спрятан=отключено).
- **core/**: sing-box.exe / nekobox_core.exe (gitignored) + fetch_core.py.
- **gen_icon.py**: из арта (китсунэ в коробке) делает иконку + кадры трея (PIL floodfill убирает белый фон).
- **docs/COMPARISON.md**: полная таблица Kitsune↔NekoBox по фичам со статусами.

## 5. Состояние
- В **backend** (переживает трей): status, server, ping, down, up, elapsed, exitIp, mode, groups, currentGroup,
  autoConnect/Mode, hotkeyEnabled/Text, fav на сервере.
- В **QML/win → снимок JSON при выгрузке UI** (AppController._snap; Main.exportSettings/importSettings,
  property settingsSnapshot:string): тумблеры Settings, routeRules, port/mtu/dns, rt*-пресеты.
- Theme.scheme — в синглтоне, при выгрузке UI сбрасывается на dark (в снимок не входит).

## 6. ПОДВОДНЫЕ КАМНИ
1. Нельзя emit'ить PUA-глифы → иконки в QML через `String.fromCharCode(0xE7..)`.
2. Theme-синглтон: setProperty из Python НЕ пробрасывается в биндинги → для скрина темы временно менять `scheme`
   по умолчанию в Theme.qml и возвращать. В приложении `Theme.scheme=…` работает.
3. Edit по большим блокам мажет по ведущим пробелам → якориться короткими подстроками.
4. Drag в Flickable: DragHandler крадётся → `MouseArea{preventStealing:true; drag.target}`.
5. Кросс-родительский anchor не работает → `mapToItem/mapFromItem(null,…)` + фиктивные зависимости.
6. QJSValue привязан к движку → снимок настроек в JSON-строке.
7. QSystemTrayIcon требует QApplication (QtWidgets), `setQuitOnLastWindowClosed(False)`.
8. nekobox_core CLI: `nekobox_core.exe sing-box run/check -c config.json` (работает, проверено).

## 7. Контракт backend (что engine-связка должна сохранить; имена как в QML)
Свойства: status, server, ping, down, up, elapsed, exitIp, mode, pinging, servers, groups, currentGroup,
autoConnect, autoConnectMode, hotkeyEnabled, hotkeyText.
Слоты: toggle, connectVpn, disconnectVpn, selectServer(name), selectBest, pingAll, setMode, setCurrentGroup,
addSubscription, removeGroup, updateGroup, setGroupAuto, addServer(map), updateServer(i,map), removeServer,
duplicateServer, toggleFavorite, importFromClipboard, importText, serverLink(i)->str, serverQr(i)->str,
copyToClipboard, setHotkey, suspendHotkey, startup. Сигнал: notify(message, kind).

## 8. Сравнение с NekoBox
Полная таблица — `docs/COMPARISON.md`. Кратко: UI — паритет/лучше уже сейчас; движок — базис работает (то же ядро +
генерация/запуск конфига), остальное поступательно. Потолок = как у NekoBox (ядро одно).

## 9. СЛЕДУЮЩИЕ ШАГИ (движок), по порядку
1. **Связать engine.py ↔ Backend**: connect/disconnect → Core.start(профиль)/stop; status из процесса/порта (убрать мок).
2. **Системный прокси** Windows (реестр Internet Settings → 127.0.0.1:2080) при подключении/сброс при отключении.
3. **config-gen**: маршрутизация (route rules + bundled geosite/geoip rule-sets), DNS, mux, sniffing из UI-настроек.
4. **Clash API** ядра: реальная статистика ↓/↑ и пинг (URL delay) — заменить мок.
5. **Подписки по URL** — реальная HTTP-загрузка + парс.
6. **TUN** (tun inbound + права админа/elevated task).
7. **Экзотические протоколы**: дописать config-gen (wireguard endpoints, xhttp, mieru/juicity/amnezia) — ядро их умеет.
8. **Панель логов** — ТОЛЬКО скрытой кнопкой в Settings (см. §1), читать stdout ядра.

## 10. Прочее
- Старый публичный форк `Tawreos228/nekobox` пользователь удаляет вручную (у токена нет scope delete_repo).
- Тема «Китсунэ» — секрет: 5 тапов по логотипу в сайдбаре. Тёмная — дефолт.
- Иконка/арт: китсунэ в оранжевой коробке (от пользователя через Gemini), фон убран в gen_icon.py.
