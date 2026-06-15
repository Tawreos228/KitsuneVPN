"""
Kitsune — design prototype (PySide6 + QML).

Цель этого файла: дать дизайну живой "движок-заглушку", чтобы видеть реальные
анимации и состояния. Вся логика тут МОКОВАЯ. Когда облик утвердим, этот же QML
переезжает в C++-приложение и подключается к движку (Thrift -> ядро sing-box),
а этот Backend заменяется реальным.
"""

import sys
import os
import re
import json
import time
import base64
import random
import ctypes
import winreg
import tempfile
import threading
import subprocess
from collections import deque
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote

import engine

from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt, QAbstractNativeEventFilter, QMetaObject, QFileInfo
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileIconProvider
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtNetwork import QLocalServer, QLocalSocket


SINGLETON_NAME = "Kitsune-Singleton-v1"


def _focus_existing_instance() -> bool:
    """Если уже запущенный Kitsune слушает Named Pipe — сказать ему «покажи окно» и выйти.
    Returns True когда сообщение доставлено и второй инстанс не нужен."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLETON_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


class SingleInstanceServer(QObject):
    """Named Pipe-сервер: при подключении нового инстанса эмитит showRequested."""
    showRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        QLocalServer.removeServer(SINGLETON_NAME)  # подчищает зависший pipe после краша
        self._srv = QLocalServer(self)
        self._srv.newConnection.connect(self._on_new)
        self._srv.listen(SINGLETON_NAME)

    def _on_new(self) -> None:
        c = self._srv.nextPendingConnection()
        if c is None:
            return
        # данные могут уже лежать в буфере или прилететь через readyRead
        def handle():
            c.readAll()
            self.showRequested.emit()
            c.disconnectFromServer()
        c.readyRead.connect(handle)
        if c.bytesAvailable() > 0:
            handle()


class Backend(QObject):
    """Мок состояния VPN. Имитирует подключение, статистику и ошибки."""

    statusChanged = Signal()
    statsChanged = Signal()
    serverChanged = Signal()
    # message, kind: "error" | "success" | "info"
    notify = Signal(str, str)
    modeChanged = Signal()
    pingingChanged = Signal()
    serversChanged = Signal()
    groupsChanged = Signal()
    currentGroupChanged = Signal()
    autoConnectChanged = Signal()
    autoConnectModeChanged = Signal()
    hotkeyChanged = Signal()
    # внутренние: доставка результатов фоновых задач в основной поток
    _pingAllDone = Signal(int, "QVariantList")
    _activePingDone = Signal(int)
    _exitIpDone = Signal(str)
    _verifyDone = Signal("QVariantMap", str, bool)   # info, expected_code, was_connected
    verifyChanged = Signal()
    speedtestChanged = Signal()
    _speedtestProgress = Signal(int, int, str, float)   # done, total, current_name, mbps_for_one
    _speedtestFinished = Signal()
    _subDone = Signal(int, "QVariantList", bool, int, int)   # gi, servers, ok, invalid, profile_interval_h (0 если сервер не задал)
    _logLine = Signal(str)                          # одна строка лога ядра (из фонового потока)
    logsChanged = Signal()
    coreInfoChanged = Signal()
    _coreCheckDone = Signal("QVariantMap")
    _coreUpdateDone = Signal(bool, str)
    appInfoChanged = Signal()
    _appCheckDone = Signal("QVariantMap")
    _appUpdateDone = Signal(bool, str)
    _appProgress = Signal(float)
    _coreProgress = Signal(float)
    appsChanged = Signal()
    _appsScanDone = Signal("QVariantList")
    rulesImported = Signal("QVariantList", str)     # (rules, format)

    def __init__(self) -> None:
        super().__init__()
        self._lang = "ru"                      # i18n: язык notify-сообщений; синкается из QML T.lang
        self._status = "disconnected"          # disconnected | connecting | connected
        self._server = ""                      # выбранный сервер (восстановится из state.json при загрузке)
        self._ping = 0
        self._down = 0.0                       # MB за сессию (мок)
        self._up = 0.0
        self._elapsed = 0                      # секунды
        self._exit_ip = ""                     # внешний IP (мок)
        self._verify_status = "idle"           # idle | checking | match | mismatch | off | error
        self._verify_info: dict = {}           # последний результат lookup_ip_info
        self._speedtest_running = False
        self._speedtest_done = 0               # сколько серверов уже замерили
        self._speedtest_total = 0              # сколько всего в очереди
        self._speedtest_current = ""           # имя текущего «country · city»
        self._speedtest_cancel = False
        self._mode = "tun"                     # proxy | tun (default: tun — auto-elevation handles UAC once)
        self._pinging = False
        self._auto_connect = True
        self._auto_connect_mode = 0            # 0 последний · 1 быстрейший
        self._pending_autoconnect = False
        self._hotkey_enabled = True
        self._hk_text = "Ctrl+Alt+V"
        self._hk_mods = 3                      # MOD_ALT(1) | MOD_CONTROL(2)
        self._hk_vk = 0x56                     # 'V'
        self._hk_suspended = False
        self._currentGroup = 0
        # Минимальный дефолт — одна пустая группа «Мои сервера». Все подписки/сервера юзер добавляет сам;
        # сохраняются на диск в %LocalAppData%\Kitsune\groups.json через _save_state().
        self._groups = [
            {"name": "Мои сервера", "type": "manual", "url": "",
             "updated": "—", "auto": False, "config": None,
             "servers": []},
        ]
        self._server = ""                      # выбранный сервер; будет восстановлен из state.json или останется пустым
        # Загружаем сохранённое состояние, если есть. При успехе — затрёт пустой дефолт выше.
        self._load_state()

        self._core = engine.Core()
        self._settings: dict = {}              # настройки маршрутизации/DNS/mux из UI
        self._conn_tries = 0
        self._tick_n = 0                       # счётчик тиков (рефреш активного пинга)
        self._base_down = 0                    # накопительные байты ядра на момент connect
        self._base_up = 0
        # auto-reconnect (watchdog) — переподключиться при нештатном обрыве
        self._reconnect_enabled = True         # синкается с QML setReconnect
        self._user_disconnected = False        # юзер сам нажал disconnect → не переподключаемся
        self._reconnect_attempts = 0
        self._RECONNECT_MAX = 5
        # kill-switch (Windows Firewall блок исходящего при нештатном обрыве)
        self._kill_switch = False              # синкается с QML setKill
        # КРИТИЧНО: precautionary cleanup от возможных leftover-настроек прошлого крэша.
        # Принцип: приложение НЕ должно оставлять следов в системе после своего завершения.
        # ВАЖНО: чистим ТАРГЕТИРОВАННО — только то, что точно наше.
        try:
            engine.firewall_unblock_all()    # наше rule с уникальным name — не заденет чужие
        except Exception:
            pass
        try:
            self._clean_leftover_system_proxy()
        except Exception:
            pass
        self._pingAllDone.connect(self._on_ping_all)
        self._activePingDone.connect(self._on_active_ping)
        self._exitIpDone.connect(self._on_exit_ip)
        self._verifyDone.connect(self._on_verify_done)
        self._speedtestProgress.connect(self._on_speedtest_progress)
        self._speedtestFinished.connect(self._on_speedtest_finished)
        self._subDone.connect(self._on_sub_done)
        self._log_buf: deque = deque(maxlen=2000)   # rolling-буфер строк лога
        self._logLine.connect(self._on_log_line)
        self._core_version = engine.core_version("sing-box.exe") or ""
        self._core_latest = ""                       # известный последний релиз sing-box
        self._core_updating = False
        self._coreCheckDone.connect(self._on_core_check_done)
        self._coreUpdateDone.connect(self._on_core_update_done)
        self._app_version = engine.APP_VERSION
        self._app_latest = ""
        self._app_latest_url = ""
        self._app_updating = False
        self._app_progress = 0.0
        self._core_progress = 0.0
        self._appCheckDone.connect(self._on_app_check_done)
        self._appUpdateDone.connect(self._on_app_update_done)
        self._appProgress.connect(self._on_app_progress)
        self._coreProgress.connect(self._on_core_progress)
        # Фоновое авто-обновление подписок: один scheduler-таймер с тиком в 60 сек.
        # На каждом тике проверяет для каждой группы, пора ли её обновить (по своему
        # Profile-Update-Interval header'у с сервера ИЛИ по глобальной настройке).
        # Старт сразу после init — сами решения о refresh'ах принимает в _auto_refresh_all_subs.
        self._sub_auto_refresh = False
        self._sub_refresh_h = 12
        self._sub_auto_timer = QTimer(self)
        self._sub_auto_timer.setInterval(60_000)
        self._sub_auto_timer.timeout.connect(self._auto_refresh_all_subs)
        self._sub_auto_timer.start()
        self._app_list: list = []                    # установленные приложения с иконками (объединённое: scan + custom)
        self._scanned_apps_raw: list = []            # сырой результат последнего scanApps() (без иконок)
        self._custom_apps_raw: list = []             # пользовательские (добавленные вручную через файл-пикер)
        self._appsScanDone.connect(self._on_apps_scan_done)
        self._connect_timer = QTimer(self)       # поллинг порта во время подключения
        self._connect_timer.setInterval(300)
        self._connect_timer.timeout.connect(self._poll_connect)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

    # ---- persistent state (groups + currentGroup + server) ----
    _STATE_FILE = "groups.json"

    def _state_path(self):
        from pathlib import Path
        return engine.state_dir() / self._STATE_FILE

    def _load_state(self) -> bool:
        """Загрузить сохранённые группы/выбранный сервер. True если файл был и применился."""
        try:
            p = self._state_path()
            if not p.exists():
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        groups = data.get("groups")
        if isinstance(groups, list) and groups:
            # на всякий случай проверим, что хотя бы одна группа имеет нужную форму
            self._groups = [g for g in groups if isinstance(g, dict) and g.get("name")]
            if not self._groups:
                self._groups = [{"name": "Мои сервера", "type": "manual", "url": "",
                                 "updated": "—", "auto": False, "config": None, "servers": []}]
        cg = data.get("currentGroup")
        if isinstance(cg, int) and 0 <= cg < len(self._groups):
            self._currentGroup = cg
        srv = data.get("server")
        if isinstance(srv, str):
            self._server = srv
        mode = data.get("mode")
        if mode in ("proxy", "tun"):
            self._mode = mode
        return True

    def _save_state(self) -> None:
        """Сохранить текущее состояние групп/выбранного сервера в %LocalAppData%\\Kitsune\\groups.json.
        Вызывается после каждого изменения подписок/серверов/избранного и при выходе."""
        try:
            payload = {
                "groups": self._groups,
                "currentGroup": self._currentGroup,
                "server": self._server,
                "mode": self._mode,
            }
            self._state_path().write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass

    # ---- i18n (notify-сообщения с подстановкой args) ----
    _NOTIFY_TR = {
        "ru": {
            "hotkey":            "Горячая клавиша: {text}",
            "ksneedadmin":       "Kill-switch требует прав администратора (TUN-режим даёт их автоматически)",
            "novalidservers":    "В группе нет валидных серверов",
            "tunneedadmin":      "TUN требует прав администратора · перезапуск…",
            "coreerror":         "Ошибка ядра · {err}",
            "uacrefused":        "Повышение прав отклонено · TUN недоступен",
            "elevatefail":       "Не удалось повысить права · {err}",
            "conntimeout":       "Не удалось подключиться · таймаут",
            "switched":          "Переключено · {name}",
            "reconnectingto":    "Переподключение к · {name}",
            "bestserver":        "Лучший сервер: {name} · {ping} ms",
            "demoerror":         "Не удалось установить соединение · таймаут рукопожатия",
            "mode.tunneedadmin": "Режим · TUN (при подключении запросит права администратора)",
            "mode.proxy":        "Режим · Прокси",
            "mode.tun":          "Режим · TUN",
            "coreavail":         "Доступна новая версия sing-box · {tag}",
            "coreuptodate":      "Установлена актуальная версия · {ver}",
            "disconnectfirst":   "Сначала отключитесь — нельзя обновлять ядро при активном соединении",
            "norelease":         "Нет данных о релизе — нажмите «Проверить обновления»",
            "coreloading":       "Загрузка обновления ядра…",
            "coreupdated":       "Ядро обновлено · {ver}",
            "coreupdfail":       "Не удалось обновить · {err}",
            "stsstart":          "Замеряем скорость · {n} серверов",
            "stsdone":           "Замер скорости завершён",
            "filereadfail":      "Не удалось прочитать файл",
            "wgbadformat":       "Файл .conf — не валидный WireGuard",
            "appavail":          "Доступна новая версия Kitsune · {tag}",
            "appuptodate":       "Установлена актуальная версия Kitsune · {ver}",
            "apploading":        "Загрузка обновления Kitsune…",
            "appupdating":       "Запуск установщика — приложение закроется",
            "appupdfail":        "Не удалось обновить Kitsune · {err}",
            "autostarton":       "Автозапуск включён",
            "autostartoff":      "Автозапуск выключен",
            "autostartfail":     "Не удалось изменить автозапуск · {err}",
            "fmtunknown":        "Формат не распознан · поддерживаются sing-box JSON и Clash YAML",
            "rulesimp":          "Импортировано правил: {n} (из {fmt})",
            "filenotfound":      "Файл не найден · {path}",
            "alreadyadded":      "Уже добавлено · {name}",
            "added":             "Добавлено · {name}",
            "subloading":        "Загрузка подписки…",
            "subupdated":        "Подписка обновлена · {name} ({n})",
            "subupdatedskip":    "Подписка обновлена · {name} ({n}) · пропущено битых: {skip}",
            "suballinvalid":     "Все {n} серверов из подписки невалидны",
            "subempty":          "Подписка пуста или формат не распознан",
            "subloadfail":       "Не удалось загрузить подписку · {name}",
            "subrefreshing":     "Обновление подписки…",
            "srvnotadded":       "Сервер не добавлен · {err}",
            "srvadded":          "Сервер добавлен · {name}",
            "srvnotsaved":       "Не сохранён · {err}",
            "srvupdated":        "Сервер обновлён · {name}",
            "srvremoved":        "Сервер удалён · {name}",
            "srvduplicated":     "Дублировано · {name}",
            "noLinks":           "В буфере нет валидных ссылок",
            "noneadded":         "Не добавлено · все {n} битые",
            "imported":          "Импортировано серверов: {n}",
            "importedskip":      "Импортировано серверов: {n} · пропущено битых: {skip}",
            "copied":            "Скопировано",
            "connected":         "Подключено · {name}",
            "kscut":             "Kill-switch · интернет заблокирован до восстановления",
            "dropped":           "Соединение оборвалось · переподключение ({tries}/{max})",
            "dropfail":          "Не удалось восстановить соединение · переподключите вручную",
            "reconnectfail":     "Reconnect не удался · {err}",
            "subadded":          "Подписка добавлена · {name}",
        },
        "en": {
            "hotkey":            "Hotkey: {text}",
            "ksneedadmin":       "Kill-switch requires admin (TUN mode grants it automatically)",
            "novalidservers":    "No valid servers in group",
            "tunneedadmin":      "TUN requires admin · restarting…",
            "coreerror":         "Core error · {err}",
            "uacrefused":        "Elevation refused · TUN unavailable",
            "elevatefail":       "Failed to elevate · {err}",
            "conntimeout":       "Connection failed · timeout",
            "switched":          "Switched · {name}",
            "reconnectingto":    "Reconnecting to · {name}",
            "bestserver":        "Best server: {name} · {ping} ms",
            "demoerror":         "Connection failed · handshake timeout",
            "mode.tunneedadmin": "Mode · TUN (will request admin on connect)",
            "mode.proxy":        "Mode · Proxy",
            "mode.tun":          "Mode · TUN",
            "coreavail":         "New sing-box version available · {tag}",
            "coreuptodate":      "Up to date · {ver}",
            "disconnectfirst":   "Disconnect first — cannot update core while connected",
            "norelease":         "No release data — press «Check for updates»",
            "coreloading":       "Downloading core update…",
            "coreupdated":       "Core updated · {ver}",
            "coreupdfail":       "Update failed · {err}",
            "stsstart":          "Speed-testing {n} servers",
            "stsdone":           "Speed test complete",
            "filereadfail":      "Failed to read file",
            "wgbadformat":       "File is not a valid WireGuard .conf",
            "appavail":          "New Kitsune version available · {tag}",
            "appuptodate":       "Kitsune is up to date · {ver}",
            "apploading":        "Downloading Kitsune update…",
            "appupdating":       "Launching installer — app will close",
            "appupdfail":        "Kitsune update failed · {err}",
            "autostarton":       "Autostart enabled",
            "autostartoff":      "Autostart disabled",
            "autostartfail":     "Failed to change autostart · {err}",
            "fmtunknown":        "Format not recognized · supports sing-box JSON and Clash YAML",
            "rulesimp":          "Imported rules: {n} (from {fmt})",
            "filenotfound":      "File not found · {path}",
            "alreadyadded":      "Already added · {name}",
            "added":             "Added · {name}",
            "subloading":        "Loading subscription…",
            "subupdated":        "Subscription updated · {name} ({n})",
            "subupdatedskip":    "Subscription updated · {name} ({n}) · skipped invalid: {skip}",
            "suballinvalid":     "All {n} servers in subscription are invalid",
            "subempty":          "Subscription empty or format not recognized",
            "subloadfail":       "Failed to load subscription · {name}",
            "subrefreshing":     "Updating subscription…",
            "srvnotadded":       "Server not added · {err}",
            "srvadded":          "Server added · {name}",
            "srvnotsaved":       "Not saved · {err}",
            "srvupdated":        "Server updated · {name}",
            "srvremoved":        "Server removed · {name}",
            "srvduplicated":     "Duplicated · {name}",
            "noLinks":           "No valid links in clipboard",
            "noneadded":         "None added · all {n} invalid",
            "imported":          "Imported servers: {n}",
            "importedskip":      "Imported servers: {n} · skipped invalid: {skip}",
            "copied":            "Copied",
            "connected":         "Connected · {name}",
            "kscut":             "Kill-switch · internet blocked until recovery",
            "dropped":           "Connection dropped · reconnecting ({tries}/{max})",
            "dropfail":          "Could not restore connection · reconnect manually",
            "reconnectfail":     "Reconnect failed · {err}",
            "subadded":          "Subscription added · {name}",
        },
    }

    def _tr(self, key: str, **kwargs) -> str:
        """Перевод notify-сообщения по ключу + подстановка {args}. Fallback: ru → ключ."""
        d = self._NOTIFY_TR.get(self._lang) or self._NOTIFY_TR["ru"]
        tmpl = d.get(key) or self._NOTIFY_TR["ru"].get(key) or key
        try:
            return tmpl.format(**kwargs) if kwargs else tmpl
        except (KeyError, IndexError):
            return tmpl

    @Slot(str)
    def setLang(self, lang: str) -> None:
        """Установка языка для Backend notify-сообщений. Зовётся из QML при смене T.lang."""
        if lang in self._NOTIFY_TR:
            self._lang = lang

    # ---- properties ----
    def _get_status(self) -> str:
        return self._status

    status = Property(str, _get_status, notify=statusChanged)

    def _get_server(self) -> str:
        return self._server

    server = Property(str, _get_server, notify=serverChanged)

    def _get_ping(self) -> int:
        return self._ping

    ping = Property(int, _get_ping, notify=statsChanged)

    def _get_down(self) -> float:
        return self._down

    down = Property(float, _get_down, notify=statsChanged)

    def _get_up(self) -> float:
        return self._up

    up = Property(float, _get_up, notify=statsChanged)

    def _get_elapsed(self) -> int:
        return self._elapsed

    elapsed = Property(int, _get_elapsed, notify=statsChanged)

    def _get_exit_ip(self) -> str:
        return self._exit_ip

    exitIp = Property(str, _get_exit_ip, notify=statsChanged)

    def _get_mode(self) -> str:
        return self._mode

    mode = Property(str, _get_mode, notify=modeChanged)

    def _get_pinging(self) -> bool:
        return self._pinging

    pinging = Property(bool, _get_pinging, notify=pingingChanged)

    def _cur(self) -> dict:
        return self._groups[self._currentGroup]

    def _get_servers(self) -> list:
        return self._cur()["servers"]

    servers = Property("QVariantList", _get_servers, notify=serversChanged)

    def _get_groups(self) -> list:
        return self._groups

    groups = Property("QVariantList", _get_groups, notify=groupsChanged)

    def _get_current_group(self) -> int:
        return self._currentGroup

    currentGroup = Property(int, _get_current_group, notify=currentGroupChanged)

    def _get_auto(self) -> bool:
        return self._auto_connect

    def _set_auto(self, v: bool) -> None:
        if v != self._auto_connect:
            self._auto_connect = v
            self.autoConnectChanged.emit()

    autoConnect = Property(bool, _get_auto, _set_auto, notify=autoConnectChanged)

    def _get_auto_mode(self) -> int:
        return self._auto_connect_mode

    def _set_auto_mode(self, v: int) -> None:
        if v != self._auto_connect_mode:
            self._auto_connect_mode = v
            self.autoConnectModeChanged.emit()

    autoConnectMode = Property(int, _get_auto_mode, _set_auto_mode, notify=autoConnectModeChanged)

    def _get_hk_en(self) -> bool:
        return self._hotkey_enabled

    def _set_hk_en(self, v: bool) -> None:
        if v != self._hotkey_enabled:
            self._hotkey_enabled = v
            self.hotkeyChanged.emit()

    hotkeyEnabled = Property(bool, _get_hk_en, _set_hk_en, notify=hotkeyChanged)

    def _get_hk_text(self) -> str:
        return self._hk_text

    hotkeyText = Property(str, _get_hk_text, notify=hotkeyChanged)

    @Slot(str, int, int)
    def setHotkey(self, text: str, mods: int, vk: int) -> None:
        self._hk_text = text
        self._hk_mods = mods
        self._hk_vk = vk
        self.hotkeyChanged.emit()
        self.notify.emit(self._tr("hotkey", text=text), "info")

    @Slot(bool)
    def suspendHotkey(self, s: bool) -> None:
        self._hk_suspended = s
        self.hotkeyChanged.emit()

    @Slot(str)
    def applyConfig(self, snapshot: str) -> None:
        """Принять снимок настроек из QML и привести к контракту engine.gen_config."""
        try:
            s = json.loads(snapshot or "{}") or {}
        except (ValueError, TypeError):
            return
        self._settings = {
            "portMixed": s.get("portMixed"),
            "sniff": s.get("setSniff", True),
            "mux": s.get("setMux", False),
            "muxProto": s.get("muxProto", 0),
            "fakeip": s.get("setFakeIp", True),
            "dnsRemote": s.get("dnsRemote"),
            "dnsDirect": s.get("dnsDirect"),
            "rtLan": s.get("rtLan", True),
            "rtRegionDirect": s.get("rtRegionDirect", True),
            "rtAdblock": s.get("rtAdblock", False),
            "rtProxyAll": s.get("rtProxyAll", False),
            "rtFinal": s.get("rtFinal", 0),
            "routeRules": s.get("routeRules", []),
            "tunStack": s.get("tunStack", 0),
            "strictRoute": s.get("setStrictRoute", True),
            "mtu": s.get("mtu"),
            "lan": s.get("setLan", False),
        }

    def _effective_port(self) -> int:
        try:
            return int(self._settings.get("portMixed") or engine.MIXED_PORT)
        except (TypeError, ValueError):
            return engine.MIXED_PORT

    # ---- actions ----
    @Slot()
    def toggle(self) -> None:
        if self._status == "disconnected":
            self._begin_connect()
        elif self._status == "connecting":
            self._user_disconnected = True
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
        else:
            self._user_disconnected = True
            self._disconnect()

    def _selected_server(self):
        for s in self._cur()["servers"]:
            if s["country"] + " · " + s["city"] == self._server:
                return s
        return None

    @Slot(bool)
    def setReconnectEnabled(self, on: bool) -> None:
        """Включить/выключить watchdog-переподключения при нештатном обрыве."""
        self._reconnect_enabled = bool(on)

    @Slot(bool)
    def setKillSwitchEnabled(self, on: bool) -> None:
        """Kill-switch: блок всего исходящего трафика через netsh при нештатном обрыве.
        Требует админ-прав. При выключении тумблера — немедленная разблокировка (если что-то висело)."""
        self._kill_switch = bool(on)
        if not on:
            # снимаем правило, если вдруг было активно
            try:
                engine.firewall_unblock_all()
            except Exception:
                pass
        elif not engine.is_admin():
            self.notify.emit(self._tr("ksneedadmin"), "info")

    def _valid_servers_of_group(self) -> list:
        """Сервера активной группы с проставленным флагом _valid (выставляется при импорте).
        Фильтрация мгновенная — НЕ дёргаем sing-box check здесь (иначе на больших подписках UI замёрз бы
        на секунды каждый раз при connect/select). Default True для серверов без флага (мок/legacy)."""
        return [s for s in self._cur()["servers"] if s.get("_valid", True)]

    def _active_idx_in(self, valid_list: list) -> int:
        """Индекс активного сервера (по self._server) внутри списка валидных. -1 если не нашли."""
        for i, s in enumerate(valid_list):
            if s.get("country", "") + " · " + s.get("city", "") == self._server:
                return i
        return -1

    def _begin_connect(self) -> None:
        valid = self._valid_servers_of_group()
        if not valid:
            self.notify.emit(self._tr("novalidservers"), "error")
            return
        # активный должен быть среди валидных; если выбранный битый — берём первого
        active_idx = self._active_idx_in(valid)
        if active_idx < 0:
            active_idx = 0
            first = valid[0]
            self._server = first["country"] + " · " + first["city"]
            self.serverChanged.emit()
        # пользовательский connect — намерение «хочу быть подключённым»
        self._user_disconnected = False
        self._reconnect_attempts = 0
        tun = self._mode == "tun"
        if tun and not engine.is_admin():
            # TUN создаёт системный сетевой адаптер → нужны права администратора.
            # Перезапускаем приложение с повышением прав (UAC), затем юзер подключается снова.
            self.notify.emit(self._tr("tunneedadmin"), "info")
            self._relaunch_as_admin()
            return
        settings = dict(self._settings)
        settings["tun"] = tun
        settings["activeIdx"] = active_idx
        # передаём ВЕСЬ список валидных серверов: engine соберёт selector-outbound (если их 2+)
        # или одиночный outbound (если 1) — это и даёт seamless server switch.
        self._set_status("connecting")
        try:
            # on_log вызывается из фонового потока ядра → emit Signal (queued в основной поток)
            self._core.start(valid, settings, on_log=self._logLine.emit)
        except Exception as e:
            self._set_status("disconnected")
            self.notify.emit(self._tr("coreerror", err=str(e)[:80]), "error")
            return
        self._conn_tries = 0
        self._connect_timer.start()

    def _relaunch_as_admin(self) -> None:
        """Перезапуск процесса с правами администратора (через ShellExecute 'runas')."""
        try:
            self._core.stop()
            self._set_system_proxy(False)
        except Exception:
            pass
        try:
            # --elevated: чтобы повышенный инстанс не упёрся в single-instance guard
            extra = [] if "--elevated" in sys.argv else ["--elevated"]
            if getattr(sys, "frozen", False):           # собранный exe (PyInstaller)
                exe = sys.executable
                params = subprocess.list2cmdline(sys.argv[1:] + extra)
                workdir = os.path.dirname(sys.executable)
            else:                                        # запуск через интерпретатор
                exe = sys.executable
                script = os.path.abspath(sys.argv[0])
                params = subprocess.list2cmdline([script] + sys.argv[1:] + extra)
                workdir = os.path.dirname(script)
            r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
            if int(r) > 32:
                QApplication.instance().quit()           # успешно — закрываем неэлевейтнутый инстанс
            else:
                self.notify.emit(self._tr("uacrefused"), "error")
        except Exception as e:
            self.notify.emit(self._tr("elevatefail", err=str(e)[:60]), "error")

    def _poll_connect(self) -> None:
        self._conn_tries += 1
        if engine.port_listening(self._effective_port()):
            self._connect_timer.stop()
            self._on_connected()
        elif self._conn_tries > 26:          # ~8 c
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
            self.notify.emit(self._tr("conntimeout"), "error")

    def _clean_leftover_system_proxy(self) -> None:
        """При старте Backend: выключаем системный прокси ТОЛЬКО если он наш (127.0.0.1:...).
        Если юзер использует Fiddler/Charles/любой другой прокси-софт — не трогаем его настройки."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_READ)
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            except FileNotFoundError:
                enabled = 0
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                server = ""
            winreg.CloseKey(key)
        except Exception:
            return
        # Только если прокси включён И указывает на наш loopback — это leftover от нашего крэша
        if enabled and isinstance(server, str) and server.startswith("127.0.0.1:"):
            self._set_system_proxy(False)

    def _set_system_proxy(self, enable: bool, port: int = engine.MIXED_PORT) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                                 0, winreg.KEY_SET_VALUE)
            if enable:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{port}")
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            w = ctypes.windll.Wininet
            w.InternetSetOptionW(0, 39, 0, 0)   # INTERNET_OPTION_SETTINGS_CHANGED
            w.InternetSetOptionW(0, 37, 0, 0)   # INTERNET_OPTION_REFRESH
        except Exception:
            pass

    @Slot()
    def connectVpn(self) -> None:
        if self._status == "disconnected":
            self.toggle()

    @Slot()
    def disconnectVpn(self) -> None:
        if self._status == "connecting":
            self._user_disconnected = True
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
        elif self._status == "connected":
            self._user_disconnected = True
            self._disconnect()

    @Slot(str)
    def selectServer(self, name: str) -> None:
        if name == self._server:
            return
        self._server = name
        self.serverChanged.emit()
        self._save_state()
        # бесшовно: соединение не рвём, дёргаем Clash API чтобы селектор показал на новый outbound
        if self._status == "connected":
            valid = self._valid_servers_of_group()
            idx = self._active_idx_in(valid)
            for s in valid:
                if s["country"] + " · " + s["city"] == name:
                    self._ping = s.get("ping", 0)
                    break
            self.statsChanged.emit()
            if len(valid) >= 2 and idx >= 0:
                # вызываем PUT /proxies/proxy в фоне (HTTP localhost — быстро, но всё же)
                target = engine.server_tag(idx)
                def work() -> None:
                    ok = engine.clash_select(target)
                    # пинг свежий — обновим через активный пинг (URL-delay)
                    if ok:
                        self._refresh_active_ping()
                threading.Thread(target=work, daemon=True).start()
                self.notify.emit(self._tr("switched", name=name), "success")
            else:
                # одиночный сервер или невалидная позиция — переподключаем штатно
                self.notify.emit(self._tr("reconnectingto", name=name), "info")
                self._disconnect()
                self._begin_connect()

    @Slot()
    def selectBest(self) -> None:
        servers = self._cur()["servers"]
        if not servers:
            return
        best = min(servers, key=lambda s: s.get("ping", 9999))
        self._server = best["country"] + " · " + best["city"]
        self.serverChanged.emit()
        if self._status == "connected":
            self._ping = best["ping"]
            self.statsChanged.emit()
        self.notify.emit(self._tr("bestserver", name=self._server, ping=best['ping']), "success")
        self._save_state()

    @Slot()
    def simulateError(self) -> None:
        """Только для прототипа: показать, как всплывает ошибка."""
        if self._status == "connecting":
            self._connect_timer.stop()
        self._tick.stop()
        self._set_status("disconnected")
        self.notify.emit(self._tr("demoerror"), "error")

    @Slot(str)
    def setMode(self, m: str) -> None:
        if m == self._mode:
            return
        self._mode = m
        self._save_state()        # запоминаем выбор между запусками
        self.modeChanged.emit()
        if m == "tun" and not engine.is_admin():
            self.notify.emit(self._tr("mode.tunneedadmin"), "info")
        else:
            self.notify.emit(self._tr("mode.tun" if m == "tun" else "mode.proxy"), "info")
        # если уже подключены — переподнимаем ядро с новым inbound (proxy↔tun)
        if self._status == "connected":
            self._disconnect()
            self._begin_connect()

    @Slot()
    def pingAll(self) -> None:
        """Реальный TCP-connect пинг серверов текущей группы (в фоновом потоке)."""
        if self._pinging:
            return
        self._pinging = True
        self.pingingChanged.emit()
        gi = self._currentGroup
        servers = [dict(s) for s in self._cur()["servers"]]

        def work() -> None:
            results = [engine.tcp_ping(s.get("address"), s.get("port") or 443)
                       for s in servers]
            self._pingAllDone.emit(gi, results)

        threading.Thread(target=work, daemon=True).start()

    @Slot(int, "QVariantList")
    def _on_ping_all(self, gi: int, results: list) -> None:
        if 0 <= gi < len(self._groups):
            g = dict(self._groups[gi])
            new = []
            for s, ms in zip(g["servers"], results):
                ns = dict(s)
                if ms is not None:           # недоступные/без адреса — прежнее значение
                    ns["ping"] = ms
                new.append(ns)
            g["servers"] = new
            self._groups = self._groups[:gi] + [g] + self._groups[gi + 1:]
        self._pinging = False
        self.groupsChanged.emit()
        self.serversChanged.emit()
        self.pingingChanged.emit()
        # автоподключение после первого пинга на старте
        if self._pending_autoconnect:
            self._pending_autoconnect = False
            if self._auto_connect_mode == 1:
                self.selectBest()          # к быстрейшему по свежему пингу
            srv = self._selected_server()
            if self._status == "disconnected" and srv and srv.get("address"):
                self.toggle()              # подключиться (только если профиль рабочий)

    @Slot()
    def startup(self) -> None:
        """Запуск приложения: сразу пингуем сервера, затем (опционально) автоподключение."""
        self._pending_autoconnect = self._auto_connect and self._status == "disconnected"
        self.pingAll()
        # отложенный стартовый refresh подписок — даём UI ~30 сек подняться, потом тянем свежие
        if self._sub_auto_refresh:
            QTimer.singleShot(30_000, self._auto_refresh_all_subs)

    def _refresh_active_ping(self) -> None:
        """URL-delay активного proxy через Clash API (в потоке)."""
        def work() -> None:
            d = engine.clash_delay()
            self._activePingDone.emit(int(d) if d else 0)
        threading.Thread(target=work, daemon=True).start()

    @Slot(int)
    def _on_active_ping(self, ms: int) -> None:
        if self._status == "connected" and ms > 0:
            self._ping = ms
            self.statsChanged.emit()

    def _refresh_exit_ip(self) -> None:
        """Реальный внешний IP через mixed-прокси ядра (подтверждает туннель)."""
        port = self._effective_port()
        def work() -> None:
            ip = engine.exit_ip(port)
            if ip:
                self._exitIpDone.emit(ip)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def _on_exit_ip(self, ip: str) -> None:
        if self._status == "connected":
            self._exit_ip = ip
            self.statsChanged.emit()

    # ---- sanity-check «реально под VPN?» ----
    def _get_verify_status(self) -> str: return self._verify_status
    def _get_verify_ip(self) -> str: return str(self._verify_info.get("ip") or "")
    def _get_verify_country(self) -> str: return str(self._verify_info.get("country") or "")
    def _get_verify_country_code(self) -> str: return str(self._verify_info.get("country_code") or "")
    def _get_verify_city(self) -> str: return str(self._verify_info.get("city") or "")
    def _get_verify_org(self) -> str: return str(self._verify_info.get("org") or "")

    verifyStatus      = Property(str, _get_verify_status, notify=verifyChanged)
    verifyIp          = Property(str, _get_verify_ip, notify=verifyChanged)
    verifyCountry     = Property(str, _get_verify_country, notify=verifyChanged)
    verifyCountryCode = Property(str, _get_verify_country_code, notify=verifyChanged)
    verifyCity        = Property(str, _get_verify_city, notify=verifyChanged)
    verifyOrg         = Property(str, _get_verify_org, notify=verifyChanged)

    def _expected_country_code(self) -> str:
        """Код страны выбранного сервера — для сравнения с фактическим exit-IP."""
        for s in self._cur().get("servers", []):
            if s["country"] + " · " + s["city"] == self._server:
                return str(s.get("code") or "").upper()
        return ""

    @Slot()
    def verifyVpn(self) -> None:
        """Запросить exit-IP с гео через прокси (если подключены) или напрямую.
        Сравниваем страну с выбранным сервером — это и есть sanity-check «реально под VPN?»."""
        self._verify_status = "checking"
        self.verifyChanged.emit()
        port = self._effective_port() if self._status == "connected" else None
        expected = self._expected_country_code()
        was_connected = self._status == "connected"

        sig = self._verifyDone
        def work() -> None:
            info = engine.lookup_ip_info(port=port)
            # подключены, но через прокси не вышло — глянем напрямую (узнаем что VPN дохлый)
            if not info and port:
                info = engine.lookup_ip_info(port=None)
            sig.emit(info or {}, expected, was_connected)

        threading.Thread(target=work, daemon=True).start()

    @Slot("QVariantMap", str, bool)
    def _on_verify_done(self, info: dict, expected_code: str, was_connected: bool) -> None:
        self._verify_info = info or {}
        if not info:
            self._verify_status = "error"
        elif not was_connected:
            self._verify_status = "off"          # не подключались — это наш реальный IP, VPN не активен
        else:
            actual = (info.get("country_code") or "").upper()
            if actual and expected:
                self._verify_status = "match" if actual == expected else "mismatch"
            else:
                self._verify_status = "match"     # данных для сравнения нет — не паникуем
        self.verifyChanged.emit()

    # ---- speedtest ----
    def _get_speedtest_running(self) -> bool: return self._speedtest_running
    def _get_speedtest_done(self) -> int: return self._speedtest_done
    def _get_speedtest_total(self) -> int: return self._speedtest_total
    def _get_speedtest_current(self) -> str: return self._speedtest_current
    def _get_speedtest_progress(self) -> float:
        if self._speedtest_total <= 0:
            return 0.0
        return self._speedtest_done / self._speedtest_total

    speedtestRunning  = Property(bool,  _get_speedtest_running,  notify=speedtestChanged)
    speedtestDone     = Property(int,   _get_speedtest_done,     notify=speedtestChanged)
    speedtestTotal    = Property(int,   _get_speedtest_total,    notify=speedtestChanged)
    speedtestCurrent  = Property(str,   _get_speedtest_current,  notify=speedtestChanged)
    speedtestProgress = Property(float, _get_speedtest_progress, notify=speedtestChanged)

    @Slot()
    def cancelSpeedtest(self) -> None:
        self._speedtest_cancel = True

    @Slot()
    def speedtestAll(self) -> None:
        """Замерить скорость каждого валидного сервера в текущей группе.
        Требует отключения — поднимаем временное ядро, перебираем через clash_select,
        результат сохраняем в server.speedMbps + server.speedAt, потом core.stop()."""
        if self._status != "disconnected":
            self.notify.emit(self._tr("disconnectfirst"), "error")
            return
        if self._speedtest_running:
            return
        valid = self._valid_servers_of_group()
        if not valid:
            self.notify.emit(self._tr("novalidservers"), "error")
            return

        self._speedtest_running = True
        self._speedtest_cancel = False
        self._speedtest_done = 0
        self._speedtest_total = len(valid)
        self._speedtest_current = ""
        self.speedtestChanged.emit()
        self.notify.emit(self._tr("stsstart", n=len(valid)), "info")

        # snapshot для worker'а — group_index + копии серверов
        gi = self._currentGroup
        servers_snap = [dict(s) for s in valid]
        settings = dict(self._settings)
        settings["tun"] = False                # TUN тут лишний — нужен просто mixed-прокси
        settings["activeIdx"] = 0
        port = self._effective_port()

        sig_prog = self._speedtestProgress
        sig_fin = self._speedtestFinished

        def work() -> None:
            try:
                self._core.start(servers_snap, settings, on_log=None)
            except Exception as e:
                self.notify.emit(self._tr("coreerror", err=str(e)[:80]), "error")
                sig_fin.emit()
                return
            # ждём пока ядро поднимется (port-poll, как в _poll_connect)
            for _ in range(40):                # ~4 сек макс
                if engine.port_listening(port):
                    break
                time.sleep(0.1)
            else:
                self._core.stop()
                sig_fin.emit()
                return

            for i, s in enumerate(servers_snap):
                if self._speedtest_cancel:
                    break
                tag = engine.server_tag(i)
                try:
                    engine.clash_select(tag)
                except Exception:
                    pass
                time.sleep(0.6)                # дать ядру переключить outbound
                res = engine.speedtest_via_proxy(port)
                mbps = float(res["mbps"]) if res else 0.0
                name = (s.get("country", "") + " · " + s.get("city", "")).strip(" ·")
                sig_prog.emit(i + 1, len(servers_snap), name, mbps)

            try:
                self._core.stop()
            except Exception:
                pass
            sig_fin.emit()

        threading.Thread(target=work, daemon=True).start()

    @Slot(int, int, str, float)
    def _on_speedtest_progress(self, done: int, total: int, name: str, mbps: float) -> None:
        """Обновляем servers[] активной группы: ставим speedMbps + speedAt для замеренного сервера."""
        if not (0 <= self._currentGroup < len(self._groups)):
            return
        g = dict(self._groups[self._currentGroup])
        new_servers = []
        for s in g.get("servers", []):
            n = (s.get("country", "") + " · " + s.get("city", "")).strip(" ·")
            if n == name:
                s = dict(s)
                s["speedMbps"] = mbps
                s["speedAt"] = time.time()
            new_servers.append(s)
        g["servers"] = new_servers
        self._groups = self._groups[:self._currentGroup] + [g] + self._groups[self._currentGroup + 1:]
        self._speedtest_done = done
        self._speedtest_total = total
        self._speedtest_current = name
        self.serversChanged.emit()
        self.groupsChanged.emit()
        self.speedtestChanged.emit()

    @Slot()
    def _on_speedtest_finished(self) -> None:
        self._speedtest_running = False
        self._speedtest_cancel = False
        self.speedtestChanged.emit()
        self._save_state()
        self.notify.emit(self._tr("stsdone"), "success")

    @Slot(str)
    def _on_log_line(self, line: str) -> None:
        """Принять строку лога ядра в основной поток (через Signal _logLine)."""
        self._log_buf.append(line)
        self.logsChanged.emit()

    def _get_logs_text(self) -> str:
        return "\n".join(self._log_buf)

    logsText = Property(str, _get_logs_text, notify=logsChanged)

    @Slot()
    def clearLogs(self) -> None:
        self._log_buf.clear()
        self.logsChanged.emit()

    # ---- авто-обновление ядра sing-box ----
    def _get_core_version(self) -> str: return self._core_version
    def _get_core_latest(self) -> str:  return self._core_latest
    def _get_core_updating(self) -> bool: return self._core_updating
    def _get_core_has_update(self) -> bool:
        return bool(self._core_latest) and bool(self._core_version) and self._core_latest != self._core_version

    coreVersion          = Property(str,  _get_core_version, notify=coreInfoChanged)
    coreLatest           = Property(str,  _get_core_latest,  notify=coreInfoChanged)
    coreUpdateAvailable  = Property(bool, _get_core_has_update, notify=coreInfoChanged)
    coreUpdating         = Property(bool, _get_core_updating, notify=coreInfoChanged)

    @Slot()
    def checkCoreUpdate(self) -> None:
        """ТИХАЯ проверка обновлений (используется при автозапуске): уведомление только при находке апдейта."""
        self._next_check_silent = True
        self._launch_core_check()

    @Slot()
    def checkCoreUpdateForce(self) -> None:
        """Ручная проверка из UI: уведомление в обе стороны (есть/нет апдейта)."""
        self._next_check_silent = False
        self._launch_core_check()

    def _launch_core_check(self) -> None:
        def work() -> None:
            sb = engine.latest_singbox_release()
            self._coreCheckDone.emit({
                "sb_tag": (sb or {}).get("tag", ""),
                "sb_url": (sb or {}).get("url", ""),
            })
        threading.Thread(target=work, daemon=True).start()

    @Slot("QVariantMap")
    def _on_core_check_done(self, d: dict) -> None:
        sb_tag = (d.get("sb_tag") or "").strip()
        self._core_latest = sb_tag
        self._core_latest_url = d.get("sb_url") or ""
        self.coreInfoChanged.emit()
        if self._get_core_has_update():
            # мягкое предложение — обычный info-тост, не блокирует
            self.notify.emit(self._tr("coreavail", tag=sb_tag), "info")
        elif not getattr(self, "_next_check_silent", True):
            # тихая авто-проверка молчит при «нет апдейтов»; ручная даёт явный фидбек
            self.notify.emit(self._tr("coreuptodate", ver=(self._core_version or "—")), "success")

    @Slot()
    def updateCore(self) -> None:
        """Скачать и установить последний sing-box.exe (только если соединение отключено)."""
        if self._status != "disconnected":
            self.notify.emit(self._tr("disconnectfirst"), "error")
            return
        url = getattr(self, "_core_latest_url", "")
        if not url:
            self.notify.emit(self._tr("norelease"), "error")
            return
        self._core_updating = True
        self._core_progress = 0.0
        self.coreInfoChanged.emit()
        self.notify.emit(self._tr("coreloading"), "info")

        sig = self._coreProgress
        def progress(read: int, total: int) -> None:
            if total > 0:
                sig.emit(read / total)

        def work() -> None:
            ok, msg = engine.install_core_update(url, "sing-box.exe", on_progress=progress)
            self._coreUpdateDone.emit(ok, msg)

        threading.Thread(target=work, daemon=True).start()

    @Slot(bool, str)
    def _on_core_update_done(self, ok: bool, msg: str) -> None:
        self._core_updating = False
        if ok:
            self._core_version = engine.core_version("sing-box.exe") or self._core_version
            self.notify.emit(self._tr("coreupdated", ver=self._core_version), "success")
        else:
            self.notify.emit(self._tr("coreupdfail", err=msg), "error")
        self.coreInfoChanged.emit()

    # ---- авто-обновление самого приложения Kitsune ----
    def _get_app_version(self) -> str: return self._app_version
    def _get_app_latest(self) -> str:  return self._app_latest
    def _get_app_updating(self) -> bool: return self._app_updating
    def _get_app_has_update(self) -> bool:
        return bool(self._app_latest) and bool(self._app_version) and self._app_latest != self._app_version

    def _get_app_progress(self) -> float: return self._app_progress
    def _get_core_progress(self) -> float: return self._core_progress

    appVersion          = Property(str,  _get_app_version, notify=appInfoChanged)
    appLatest           = Property(str,  _get_app_latest,  notify=appInfoChanged)
    appUpdateAvailable  = Property(bool, _get_app_has_update, notify=appInfoChanged)
    appUpdating         = Property(bool, _get_app_updating, notify=appInfoChanged)
    appUpdateProgress   = Property(float, _get_app_progress, notify=appInfoChanged)
    coreUpdateProgress  = Property(float, _get_core_progress, notify=coreInfoChanged)

    @Slot(float)
    def _on_app_progress(self, p: float) -> None:
        self._app_progress = max(0.0, min(1.0, p))
        self.appInfoChanged.emit()

    @Slot(float)
    def _on_core_progress(self, p: float) -> None:
        self._core_progress = max(0.0, min(1.0, p))
        self.coreInfoChanged.emit()

    @Slot()
    def checkAppUpdate(self) -> None:
        """Тихая проверка обновлений приложения (на старте): тост только при находке."""
        self._next_app_check_silent = True
        self._launch_app_check()

    @Slot()
    def checkAppUpdateForce(self) -> None:
        """Ручная проверка из UI: тост в обе стороны (есть/нет апдейта)."""
        self._next_app_check_silent = False
        self._launch_app_check()

    def _launch_app_check(self) -> None:
        def work() -> None:
            rel = engine.latest_kitsune_release()
            self._appCheckDone.emit({
                "tag": (rel or {}).get("tag", ""),
                "url": (rel or {}).get("setup_url", ""),
            })
        threading.Thread(target=work, daemon=True).start()

    @Slot("QVariantMap")
    def _on_app_check_done(self, d: dict) -> None:
        tag = (d.get("tag") or "").strip()
        self._app_latest = tag
        self._app_latest_url = d.get("url") or ""
        self.appInfoChanged.emit()
        if self._get_app_has_update():
            self.notify.emit(self._tr("appavail", tag=tag), "info")
        elif not getattr(self, "_next_app_check_silent", True):
            self.notify.emit(self._tr("appuptodate", ver=(self._app_version or "—")), "success")

    @Slot()
    def updateApp(self) -> None:
        """Скачать и запустить новый KitsuneSetup.exe (требует disconnect, как и core-update)."""
        if self._status != "disconnected":
            self.notify.emit(self._tr("disconnectfirst"), "error")
            return
        url = getattr(self, "_app_latest_url", "")
        if not url:
            self.notify.emit(self._tr("norelease"), "error")
            return
        self._app_updating = True
        self._app_progress = 0.0
        self.appInfoChanged.emit()
        self.notify.emit(self._tr("apploading"), "info")

        sig = self._appProgress
        def progress(read: int, total: int) -> None:
            if total > 0:
                sig.emit(read / total)

        def work() -> None:
            ok, msg = engine.download_and_run_installer(url, on_progress=progress)
            self._appUpdateDone.emit(ok, msg)

        threading.Thread(target=work, daemon=True).start()

    @Slot(bool, str)
    def _on_app_update_done(self, ok: bool, msg: str) -> None:
        self._app_updating = False
        self.appInfoChanged.emit()
        if ok:
            # installer запущен — корректно завершаемся, чтобы он мог заменить файлы
            self.notify.emit(self._tr("appupdating"), "success")
            QTimer.singleShot(800, QApplication.instance().quit)
        else:
            self.notify.emit(self._tr("appupdfail", err=msg), "error")

    @Slot(str)
    def openUrl(self, url: str) -> None:
        """Открыть внешнюю ссылку в системном браузере."""
        try:
            os.startfile(url)
        except Exception:
            pass

    # ---- автозапуск с системой (HKCU\Software\Microsoft\Windows\CurrentVersion\Run) ----
    _AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _AUTOSTART_VAL = "Kitsune"

    def _autostart_command(self) -> str:
        """Строка для записи в реестр: запуск собранного exe либо python+script с правильными кавычками."""
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        script = os.path.abspath(sys.argv[0])
        return f'"{sys.executable}" "{script}"'

    @Slot(bool)
    def setAutostart(self, on: bool) -> None:
        """Прописать/убрать запись в HKCU Run для автозапуска при входе в Windows."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_KEY,
                                 0, winreg.KEY_SET_VALUE)
            if on:
                winreg.SetValueEx(key, self._AUTOSTART_VAL, 0, winreg.REG_SZ,
                                  self._autostart_command())
                self.notify.emit(self._tr("autostarton"), "success")
            else:
                try:
                    winreg.DeleteValue(key, self._AUTOSTART_VAL)
                except FileNotFoundError:
                    pass
                self.notify.emit(self._tr("autostartoff"), "info")
            winreg.CloseKey(key)
        except Exception as e:
            self.notify.emit(self._tr("autostartfail", err=str(e)[:80]), "error")

    @Slot(result=bool)
    def isAutostartEnabled(self) -> bool:
        """Проверить, прописан ли наш автозапуск (для синка QML-тумблера на старте)."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_KEY,
                                 0, winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(key, self._AUTOSTART_VAL)
                return bool(val)
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    # ---- per-app: сканер установленных приложений + извлечение иконок ----
    def _get_app_list(self) -> list:
        return self._app_list

    appList = Property("QVariantList", _get_app_list, notify=appsChanged)

    @Slot()
    def scanApps(self) -> None:
        """Асинхронно сканировать установленные приложения (Start Menu .lnk → exe)."""
        def work() -> None:
            self._appsScanDone.emit(engine.scan_apps_raw())
        threading.Thread(target=work, daemon=True).start()

    # ---- импорт правил маршрутизации из других клиентов ----
    @Slot(str, result=int)
    def importRulesText(self, text: str) -> int:
        """Парсит вставленный текст (sing-box JSON / Clash YAML) → эмитит rulesImported.
        Возвращает количество найденных правил (0 если формат не распознан)."""
        d = engine.parse_imported_rules(text or "")
        fmt = d.get("format", "unknown")
        rules = d.get("rules", [])
        if fmt == "unknown" or not rules:
            self.notify.emit(self._tr("fmtunknown"), "error")
            return 0
        self.rulesImported.emit(rules, fmt)
        self.notify.emit(self._tr("rulesimp", n=len(rules), fmt=fmt), "success")
        return len(rules)

    @Slot(result=int)
    def importRulesFromClipboard(self) -> int:
        return self.importRulesText(QApplication.clipboard().text())

    @Slot("QVariantList")
    def _on_apps_scan_done(self, raw: list) -> None:
        """Сырой результат сканирования сохраняем + пересобираем итоговый appList (scan ∪ custom)."""
        self._scanned_apps_raw = list(raw or [])
        self._rebuild_app_list()

    def _rebuild_app_list(self) -> None:
        """Объединяет scanned + custom, извлекает иконки в main-thread через QFileIconProvider.
        Custom-записи помечены `custom: True` и идут в начале списка."""
        import hashlib
        from pathlib import Path
        icon_dir = Path(tempfile.gettempdir()) / "kitsune_icons"
        try:
            icon_dir.mkdir(exist_ok=True)
        except Exception:
            pass
        provider = QFileIconProvider()
        seen: set = set()
        full: list = []

        def make_entry(app: dict, custom: bool) -> dict | None:
            exe = (app.get("exe") or "").strip()
            if not exe:
                return None
            key = os.path.basename(exe).lower()
            if key in seen:
                return None
            seen.add(key)
            icon_url = ""
            try:
                info = QFileInfo(exe)
                ic = provider.icon(info)
                pix = ic.pixmap(32, 32)
                if not pix.isNull():
                    h = hashlib.md5(exe.encode("utf-8", "ignore")).hexdigest()[:16]
                    png = icon_dir / (h + ".png")
                    if pix.save(str(png), "PNG"):
                        icon_url = "file:///" + str(png).replace("\\", "/")
            except Exception:
                pass
            return {
                "name": (app.get("name") or "").strip() or os.path.splitext(os.path.basename(exe))[0],
                "exe": exe,
                "exeName": os.path.basename(exe),
                "icon": icon_url,
                "custom": custom,
            }

        # сначала пользовательские (приоритет над сканом при совпадении basename)
        for app in self._custom_apps_raw:
            e = make_entry(app, True)
            if e:
                full.append(e)
        # затем результаты сканирования
        for app in self._scanned_apps_raw:
            e = make_entry(app, False)
            if e:
                full.append(e)
        self._app_list = full
        self.appsChanged.emit()

    @Slot()
    def addCustomAppDialog(self) -> None:
        """Открывает системный файл-пикер для выбора exe-файла приложения. Добавляет его в кастом-список."""
        from PySide6.QtWidgets import QFileDialog
        path, _filt = QFileDialog.getOpenFileName(
            None, "Выбрать exe-файл приложения",
            os.environ.get("ProgramFiles", "C:\\"),
            "Программы (*.exe);;Все файлы (*)")
        if not path:
            return
        self._add_custom_app(os.path.splitext(os.path.basename(path))[0], path)

    def _add_custom_app(self, name: str, exe: str) -> None:
        if not exe or not os.path.exists(exe):
            self.notify.emit(self._tr("filenotfound", path=exe[:80]), "error")
            return
        key = os.path.basename(exe).lower()
        # дедуп: если уже есть среди custom — пропускаем
        for a in self._custom_apps_raw:
            if os.path.basename(a.get("exe", "")).lower() == key:
                self.notify.emit(self._tr("alreadyadded", name=(a.get("name") or exe)), "info")
                return
        self._custom_apps_raw.append({"name": name, "exe": exe})
        self._rebuild_app_list()
        self.notify.emit(self._tr("added", name=name), "success")

    @Slot(str)
    def removeCustomApp(self, exe_name: str) -> None:
        key = (exe_name or "").lower()
        self._custom_apps_raw = [
            a for a in self._custom_apps_raw
            if os.path.basename(a.get("exe", "")).lower() != key
        ]
        self._rebuild_app_list()

    @Slot(str)
    def setCustomAppsJson(self, json_str: str) -> None:
        """Восстановление списка пользовательских приложений из снимка настроек (на старте)."""
        try:
            arr = json.loads(json_str or "[]")
        except (ValueError, TypeError):
            arr = []
        if not isinstance(arr, list):
            return
        self._custom_apps_raw = [
            {"name": (a.get("name") or "").strip(), "exe": (a.get("exe") or "").strip()}
            for a in arr if isinstance(a, dict) and a.get("exe")
        ]
        self._rebuild_app_list()

    def _get_custom_apps_json(self) -> str:
        return json.dumps(self._custom_apps_raw, ensure_ascii=False)

    customAppsJson = Property(str, _get_custom_apps_json, notify=appsChanged)

    # ---- группы / подписки ----
    @Slot(int)
    def setCurrentGroup(self, i: int) -> None:
        if i < 0 or i >= len(self._groups) or i == self._currentGroup:
            return
        self._currentGroup = i
        g = self._groups[i]
        if g["servers"]:
            s = g["servers"][0]
            self._server = s["country"] + " · " + s["city"]
            self.serverChanged.emit()
        self.currentGroupChanged.emit()
        self.serversChanged.emit()
        self._save_state()

    @Slot(str, str, bool)
    def addSubscription(self, name: str, url: str, auto: bool) -> None:
        gi = len(self._groups)
        self._groups = self._groups + [{
            "name": name or "Новая подписка", "type": "subscription", "url": url,
            "updated": "загрузка…", "auto": auto,
            "config": {"dns": "https://1.1.1.1/dns-query", "adblock": False, "final": 0},
            "servers": [],
        }]
        self.groupsChanged.emit()
        self._save_state()
        self.setCurrentGroup(gi)
        self.notify.emit(self._tr("subloading"), "info")
        self._refresh_subscription(gi)

    @staticmethod
    def _decode_subscription(text: str) -> list:
        """Тело подписки -> список ссылок. Поддержка base64-блоба и плейн-текста."""
        raw = (text or "").strip()
        content = raw
        try:
            dec = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
            if "://" in dec:
                content = dec
        except Exception:
            pass
        return [x for x in re.split(r"\s+", content) if "://" in x]

    def _refresh_subscription(self, gi: int) -> None:
        """Асинхронно: загрузить URL подписки, распарсить ссылки, провалидировать каждый
        через sing-box check, отсеять битые — ВСЁ в фоновом потоке. Main-thread получает
        уже готовый список валидных + счётчик битых, не зависая."""
        if not (0 <= gi < len(self._groups)):
            return
        url = self._groups[gi].get("url") or ""

        def work() -> None:
            text, headers = engine.fetch_subscription(url)
            valid_servers: list = []
            invalid = 0
            if text:
                links = self._decode_subscription(text)
                for l in links:
                    d = self._parse_link(l)
                    if not d:
                        continue
                    srv = self._make_server(d)
                    ok, _err = self._validate_server(srv)
                    srv["_valid"] = ok           # кэш — потом _valid_servers_of_group берёт мгновенно
                    if ok:
                        valid_servers.append(srv)
                    else:
                        invalid += 1
            profile_int = engine.parse_profile_update_interval(headers)
            self._subDone.emit(gi, valid_servers, text is not None, invalid, profile_int)

        threading.Thread(target=work, daemon=True).start()

    @Slot(int, "QVariantList", bool, int, int)
    def _on_sub_done(self, gi: int, servers: list, ok: bool, invalid: int, profile_interval: int) -> None:
        if not (0 <= gi < len(self._groups)):
            return
        g = dict(self._groups[gi])
        # сервер может прислать свой интервал автообновления в Profile-Update-Interval header'е —
        # запоминаем (или чистим если перестал присылать).
        if profile_interval > 0:
            g["profileUpdateInterval"] = profile_interval
        elif "profileUpdateInterval" in g:
            del g["profileUpdateInterval"]
        if ok and servers:
            fav = {(s.get("address"), s.get("port"))
                   for s in g["servers"] if s.get("fav")}
            for s in servers:
                if (s.get("address"), s.get("port")) in fav:
                    s["fav"] = True
            g["servers"] = servers
            g["updated"] = "только что"
            g["lastUpdatedAt"] = time.time()
            if invalid:
                self.notify.emit(self._tr("subupdatedskip", name=g['name'], n=len(servers), skip=invalid), "info")
            else:
                self.notify.emit(self._tr("subupdated", name=g['name'], n=len(servers)), "success")
        elif ok and invalid:
            g["updated"] = "ошибка"
            self.notify.emit(self._tr("suballinvalid", n=invalid), "error")
        elif ok:
            g["updated"] = "пусто"
            self.notify.emit(self._tr("subempty"), "error")
        else:
            g["updated"] = "ошибка загрузки"
            self.notify.emit(self._tr("subloadfail", name=g["name"]), "error")
        self._groups = self._groups[:gi] + [g] + self._groups[gi + 1:]
        self.groupsChanged.emit()
        if gi == self._currentGroup:
            s0 = g["servers"][0] if g["servers"] else None
            if s0:
                self._server = s0["country"] + " · " + s0["city"]
                self.serverChanged.emit()
            self.serversChanged.emit()
            if g["servers"]:
                self.pingAll()          # реальные пинги для свежих серверов (уже в треде)
        self._save_state()

    @Slot(int)
    def removeGroup(self, i: int) -> None:
        if i <= 0 or i >= len(self._groups):
            return
        self._groups = self._groups[:i] + self._groups[i + 1:]
        if self._currentGroup >= len(self._groups):
            self._currentGroup = 0
            g = self._groups[0]
            if g["servers"]:
                s = g["servers"][0]
                self._server = s["country"] + " · " + s["city"]
                self.serverChanged.emit()
        self.groupsChanged.emit()
        self.currentGroupChanged.emit()
        self.serversChanged.emit()
        self._save_state()

    @Slot(int)
    def updateGroup(self, i: int) -> None:
        if i < 0 or i >= len(self._groups):
            return
        if self._groups[i].get("url"):
            self.notify.emit(self._tr("subrefreshing"), "info")
            self._refresh_subscription(i)
        else:                              # ручная группа — просто перемерить пинги
            self.pingAll()

    @Slot(int, bool)
    def setGroupAuto(self, i: int, val: bool) -> None:
        if i < 0 or i >= len(self._groups):
            return
        g = dict(self._groups[i])
        g["auto"] = val
        self._groups = self._groups[:i] + [g] + self._groups[i + 1:]
        self.groupsChanged.emit()
        self._save_state()

    # ---- фоновое авто-обновление подписок ----
    @Slot(bool)
    def setSubAutoRefresh(self, on: bool) -> None:
        """Глобальный «мастер-выключатель»: используется только для подписок без своего
        Profile-Update-Interval header'а. Подписки с серверным интервалом обновляются всегда."""
        self._sub_auto_refresh = bool(on)

    @Slot(int)
    def setSubRefreshInterval(self, hours: int) -> None:
        """Глобальный интервал — fallback для подписок без серверного header'а. Часы."""
        self._sub_refresh_h = max(1, int(hours))

    def _effective_sub_interval_h(self, g: dict) -> int:
        """Эффективный интервал refresh для группы в часах. 0 = не обновлять.
        Приоритет: серверный Profile-Update-Interval header > глобальная настройка (+ per-sub Auto)."""
        sub_h = int(g.get("profileUpdateInterval") or 0)
        if sub_h > 0:
            return sub_h
        # без header — на усмотрение юзера
        if not self._sub_auto_refresh:
            return 0
        if g.get("auto") is False:
            return 0
        return int(self._sub_refresh_h)

    def _auto_refresh_all_subs(self) -> None:
        """Scheduler-тик (раз в 60с): для каждой группы вычисляем эффективный интервал,
        смотрим когда был последний refresh — если пора, дёргаем _refresh_subscription."""
        now = time.time()
        for i, g in enumerate(self._groups):
            if not g.get("url"):
                continue
            eff_h = self._effective_sub_interval_h(g)
            if eff_h <= 0:
                continue
            last = float(g.get("lastUpdatedAt") or 0)
            if now - last >= eff_h * 3600:
                self._refresh_subscription(i)

    # ---- сервера (профили) ----
    _PROFILE_KEYS = ["protocol", "address", "port", "uuid", "password", "method",
                     "tls", "sni", "reality", "pbk", "sid", "transport", "path",
                     "host", "serviceName", "wgKey", "flow", "name", "encryption", "fp",
                     # WireGuard-only:
                     "peerKey", "localAddr", "allowedIps", "mtu", "psk"]

    def _make_server(self, data: dict, keep_ping=None) -> dict:
        name = (data.get("name") or "").strip() or (data.get("address") or "Сервер")
        addr = data.get("address") or ""
        port = data.get("port") or ""
        city = addr + ((":" + str(port)) if port else "")
        code = (data.get("code") or name)[:2].upper()
        srv = {"code": code, "country": name, "city": city,
               "ping": keep_ping if keep_ping is not None else random.randint(40, 160)}
        for k in self._PROFILE_KEYS:
            if k in data:
                srv[k] = data[k]
        return srv

    def _replace_group_servers(self, servers: list) -> None:
        g = dict(self._groups[self._currentGroup])
        g["servers"] = servers
        self._groups = (self._groups[:self._currentGroup] + [g]
                        + self._groups[self._currentGroup + 1:])
        self.groupsChanged.emit()
        self.serversChanged.emit()
        self._save_state()

    def _validate_server(self, srv: dict) -> tuple[bool, str]:
        """Прогоняет профиль через sing-box check (нашу же gen_config). Возвращает (ok, message).
        Ловит: невалидные ключи reality, кривой UUID, неверная encryption-строка, и т.п. — то, что
        иначе всплыло бы только при connect."""
        if not srv or not srv.get("address") or not srv.get("port"):
            return False, "нет адреса или порта"
        try:
            ok, msg = engine.check_config(engine.gen_config(srv, {}))
        except Exception as e:
            return False, str(e)[:120]
        if ok:
            return True, ""
        # упрощаем сообщение — берём последнюю строку с FATAL/error/invalid + чистим ANSI-цвета
        ansi_re = re.compile(r"\x1b\[[0-9;]*m")
        for line in reversed((msg or "").splitlines()):
            clean = ansi_re.sub("", line).strip()
            ll = clean.lower()
            if "fatal" in ll or "error" in ll or "invalid" in ll:
                # обрезаем технический префикс "FATAL[0000] " если есть
                clean = re.sub(r"^(FATAL|ERROR|WARN)\[\d+\]\s*", "", clean)
                return False, clean[:140]
        return False, ansi_re.sub("", msg or "невалидный конфиг")[:140]

    @Slot("QVariantMap")
    def addServer(self, data: dict) -> None:
        srv = self._make_server(data)
        ok, err = self._validate_server(srv)
        srv["_valid"] = ok                  # кэш для будущих _valid_servers_of_group
        if not ok:
            self.notify.emit(self._tr("srvnotadded", err=err), "error")
            return
        servers = list(self._cur()["servers"]) + [srv]
        self._replace_group_servers(servers)
        self.notify.emit(self._tr("srvadded", name=srv["country"]), "success")

    @Slot(int, "QVariantMap")
    def updateServer(self, i: int, data: dict) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        old = servers[i]
        srv = self._make_server(data, keep_ping=old.get("ping", 60))
        srv["fav"] = old.get("fav", False)
        ok, err = self._validate_server(srv)
        srv["_valid"] = ok
        if not ok:
            self.notify.emit(self._tr("srvnotsaved", err=err), "error")
            return
        servers[i] = srv
        self._replace_group_servers(servers)
        self.notify.emit(self._tr("srvupdated", name=srv["country"]), "info")

    @Slot(int)
    def removeServer(self, i: int) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        name = servers[i].get("country", "")
        del servers[i]
        self._replace_group_servers(servers)
        if servers:
            s0 = servers[0]
            self._server = s0["country"] + " · " + s0["city"]
            self.serverChanged.emit()
        self.notify.emit(self._tr("srvremoved", name=name), "info")

    @Slot(int)
    def duplicateServer(self, i: int) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        s = dict(servers[i])
        s["country"] = (s.get("country", "") + " (копия)")
        servers.insert(i + 1, s)
        self._replace_group_servers(servers)
        self.notify.emit(self._tr("srvduplicated", name=s["country"]), "success")

    @Slot(int)
    def toggleFavorite(self, i: int) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        s = dict(servers[i])
        s["fav"] = not s.get("fav", False)
        servers[i] = s
        self._replace_group_servers(servers)

    # ---- импорт / шеринг ----
    def _parse_link(self, link: str):
        link = (link or "").strip()
        try:
            if link.startswith("vless://") or link.startswith("trojan://"):
                proto = "vless" if link.startswith("vless://") else "trojan"
                u = urlparse(link)
                q = parse_qs(u.query)

                def g(k, d=""):
                    return q.get(k, [d])[0]

                data = {
                    "protocol": proto,
                    "address": u.hostname or "",
                    "port": u.port or 443,
                    "name": unquote(u.fragment) if u.fragment else (u.hostname or ""),
                }
                if proto == "vless":
                    data["uuid"] = u.username or ""
                else:
                    data["password"] = u.username or ""
                sec = g("security", "none")
                data["tls"] = sec in ("tls", "reality")
                data["reality"] = sec == "reality"
                data["sni"] = g("sni") or g("host")
                data["pbk"] = g("pbk")
                data["sid"] = g("sid")
                data["flow"] = g("flow")
                data["encryption"] = g("encryption")
                data["fp"] = g("fp")
                t = g("type", "tcp")
                data["transport"] = t if t in ("tcp", "ws", "grpc", "xhttp") else "tcp"
                data["path"] = g("path")
                data["host"] = g("host")
                data["serviceName"] = g("serviceName")
                return data
            if link.startswith("vmess://"):
                raw = link[8:]
                raw += "=" * (-len(raw) % 4)
                j = json.loads(base64.b64decode(raw).decode("utf-8", "ignore"))
                net = j.get("net", "tcp")
                return {
                    "protocol": "vmess",
                    "name": j.get("ps") or j.get("add", ""),
                    "address": j.get("add", ""),
                    "port": int(j.get("port", 443) or 443),
                    "uuid": j.get("id", ""),
                    "tls": j.get("tls", "") == "tls",
                    "sni": j.get("sni", "") or j.get("host", ""),
                    "transport": net if net in ("tcp", "ws", "grpc", "xhttp") else "tcp",
                    "path": j.get("path", ""),
                    "host": j.get("host", ""),
                }
            if link.startswith("ss://"):
                rest = link[5:]
                name = ""
                if "#" in rest:
                    rest, frag = rest.split("#", 1)
                    name = unquote(frag)
                host, port, method, password = "", 443, "aes-256-gcm", ""
                if "@" in rest:
                    creds, hostport = rest.split("@", 1)
                    try:
                        dec = base64.urlsafe_b64decode(creds + "=" * (-len(creds) % 4)).decode("utf-8", "ignore")
                    except Exception:
                        dec = creds
                    if ":" in dec:
                        method, password = dec.split(":", 1)
                    hostport = hostport.split("?", 1)[0]
                    if ":" in hostport:
                        host, p = hostport.rsplit(":", 1)
                        port = int(p) if p.isdigit() else 443
                    else:
                        host = hostport
                else:
                    dec = base64.urlsafe_b64decode(rest + "=" * (-len(rest) % 4)).decode("utf-8", "ignore")
                    if "@" in dec:
                        mp, hp = dec.split("@", 1)
                        if ":" in mp:
                            method, password = mp.split(":", 1)
                        if ":" in hp:
                            host, p = hp.rsplit(":", 1)
                            port = int(p) if p.isdigit() else 443
                return {"protocol": "shadowsocks", "name": name or host, "address": host,
                        "port": port, "password": password, "method": method, "tls": False}
        except Exception:
            return None
        return None

    def _import_text(self, text: str) -> int:
        links = [x for x in re.split(r"\s+", text or "") if x.strip()]
        parsed = [self._make_server(d) for d in (self._parse_link(l) for l in links) if d]
        if not parsed:
            self.notify.emit(self._tr("noLinks"), "error")
            return 0
        # health-check: пропускаем те, что не проходят sing-box check
        added, skipped = [], 0
        for srv in parsed:
            ok, _err = self._validate_server(srv)
            if ok:
                added.append(srv)
            else:
                skipped += 1
        if not added:
            self.notify.emit(self._tr("noneadded", n=skipped), "error")
            return 0
        servers = list(self._cur()["servers"]) + added
        self._replace_group_servers(servers)
        if skipped:
            self.notify.emit(self._tr("importedskip", n=len(added), skip=skipped), "info")
        else:
            self.notify.emit(self._tr("imported", n=len(added)), "success")
        return len(added)

    @Slot(result=int)
    def importFromClipboard(self) -> int:
        return self._import_text(QApplication.clipboard().text())

    @Slot(str, result=int)
    def importText(self, text: str) -> int:
        return self._import_text(text)

    @Slot(str, result=int)
    def importFromFile(self, path: str) -> int:
        """Drag-and-drop импорт: читает файл, сниффит формат, кидает в нужный парсер.
        Поддерживается:
          - WireGuard .conf (INI-формат с [Interface]/[Peer])
          - .txt / любой текст с vless:// vmess:// trojan:// ss:// или их base64-списком
        Возвращает количество добавленных серверов."""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            self.notify.emit(self._tr("filereadfail"), "error")
            return 0
        # 1) WireGuard .conf — по наличию [Interface]+[Peer], даже без правильного расширения
        low = text.lower()
        if "[interface]" in low and "[peer]" in low:
            wg = engine.parse_wireguard_conf(text)
            if not wg:
                self.notify.emit(self._tr("wgbadformat"), "error")
                return 0
            srv = self._make_server(wg)
            ok, _err = self._validate_server(srv)
            srv["_valid"] = ok
            if not ok:
                self.notify.emit(self._tr("noneadded", n=1), "error")
                return 0
            servers = list(self._cur()["servers"]) + [srv]
            self._replace_group_servers(servers)
            self.notify.emit(self._tr("imported", n=1), "success")
            return 1
        # 2) Иначе — обычный текст со ссылками (вкл. base64-списки подписок)
        decoded = self._decode_subscription(text)
        if decoded:
            text = "\n".join(decoded)
        return self._import_text(text)

    @Slot(int, result=str)
    def serverLink(self, i: int) -> str:
        servers = self._cur()["servers"]
        if i < 0 or i >= len(servers):
            return ""
        s = servers[i]
        proto = s.get("protocol", "vless")
        addr = s.get("address") or "host"
        port = s.get("port") or 443
        name = s.get("country") or s.get("name") or ""
        frag = "#" + quote(str(name)) if name else ""
        if proto in ("vless", "trojan"):
            params = ["security=" + ("reality" if s.get("reality") else ("tls" if s.get("tls", True) else "none"))]
            if s.get("sni"):
                params.append("sni=" + s["sni"])
            if proto == "vless" and s.get("flow"):
                params.append("flow=" + s["flow"])
            if s.get("reality"):
                if s.get("pbk"):
                    params.append("pbk=" + s["pbk"])
                if s.get("sid"):
                    params.append("sid=" + s["sid"])
            params.append("type=" + s.get("transport", "tcp"))
            if s.get("path"):
                params.append("path=" + quote(s["path"], safe=""))
            if s.get("host"):
                params.append("host=" + s["host"])
            if s.get("serviceName"):
                params.append("serviceName=" + s["serviceName"])
            cred = s.get("uuid") if proto == "vless" else s.get("password")
            return f"{proto}://{cred or ''}@{addr}:{port}?{'&'.join(params)}{frag}"
        if proto == "vmess":
            j = {"v": "2", "ps": name, "add": addr, "port": str(port), "id": s.get("uuid", ""),
                 "aid": "0", "net": s.get("transport", "tcp"), "type": "none",
                 "host": s.get("host", ""), "path": s.get("path", ""),
                 "tls": "tls" if s.get("tls", True) else "", "sni": s.get("sni", "")}
            return "vmess://" + base64.b64encode(json.dumps(j).encode()).decode()
        if proto == "shadowsocks":
            creds = base64.urlsafe_b64encode(
                f"{s.get('method', 'aes-256-gcm')}:{s.get('password', '')}".encode()).decode().rstrip("=")
            return f"ss://{creds}@{addr}:{port}{frag}"
        return f"{proto}://{addr}:{port}{frag}"

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text or "")
        self.notify.emit(self._tr("copied"), "success")

    @Slot(int, result=str)
    def serverQr(self, i: int) -> str:
        link = self.serverLink(i)
        if not link:
            return ""
        try:
            import segno
            path = os.path.join(tempfile.gettempdir(), f"kitsune_qr_{int(time.time() * 1000)}.png")
            segno.make(link, error="m").save(path, scale=6, border=2, dark="#111111", light="#ffffff")
            return "file:///" + path.replace("\\", "/")
        except Exception:
            return ""

    # ---- internals ----
    def _set_status(self, value: str) -> None:
        if value != self._status:
            self._status = value
            self.statusChanged.emit()

    def _on_connected(self) -> None:
        self._set_status("connected")
        self._reconnect_attempts = 0           # успешный коннект → сбрасываем счётчик watchdog'а
        # kill-switch: снимаем возможную блокировку, оставшуюся от предыдущего обрыва
        try:
            engine.firewall_unblock_all()
        except Exception:
            pass
        self._ping = 0
        self._elapsed = 0
        self._down = 0.0
        self._up = 0.0
        self._exit_ip = ""
        self._tick_n = 0
        self._base_down = 0           # базовые накопительные байты ядра на момент connect
        self._base_up = 0
        t = engine.clash_traffic()
        if t:
            self._base_down, self._base_up = t
        self.statsChanged.emit()
        self._tick.start()
        if self._mode == "proxy":
            self._set_system_proxy(True, self._effective_port())
        self.notify.emit(self._tr("connected", name=self._server), "success")
        self._refresh_active_ping()                  # реальный пинг (URL-delay)
        self._refresh_exit_ip()                      # реальный внешний IP через туннель

    def _disconnect(self) -> None:
        self._connect_timer.stop()
        self._core.stop()
        self._set_system_proxy(False)
        # kill-switch: при штатном disconnect снимаем блокировку (юзер сам решил отключиться)
        try:
            engine.firewall_unblock_all()
        except Exception:
            pass
        self._tick.stop()
        self._set_status("disconnected")
        self._ping = 0
        self._down = 0.0
        self._up = 0.0
        self._elapsed = 0
        self._exit_ip = ""
        self.statsChanged.emit()

    def _on_tick(self) -> None:
        self._elapsed += 1
        self._tick_n += 1
        # watchdog: если status=connected но порт ядра упал — нештатный обрыв
        if not engine.port_listening(self._effective_port()):
            self._handle_unexpected_drop()
            return
        # реальный трафик за сессию из Clash API (накопительно, МБ)
        t = engine.clash_traffic()
        if t:
            self._down = max(0, t[0] - self._base_down) / 1048576.0
            self._up = max(0, t[1] - self._base_up) / 1048576.0
        # активный пинг (URL-delay) — раз в 5 c, чтобы не частить
        if self._tick_n % 5 == 0:
            self._refresh_active_ping()
        self.statsChanged.emit()

    def _handle_unexpected_drop(self) -> None:
        """Соединение оборвалось не по воле юзера. Если auto-reconnect включён и лимит попыток
        не исчерпан — пытаемся переподключиться через 1.5с. Иначе — честный disconnect.
        Kill-switch: при включённом тумблере немедленно блокируем весь исходящий трафик
        через Windows Firewall, чтобы предотвратить утечки до восстановления."""
        self._tick.stop()
        if self._kill_switch and engine.is_admin():
            if engine.firewall_block_all_outbound():
                self.notify.emit(self._tr("kscut"), "error")
        if (self._reconnect_enabled and not self._user_disconnected
                and self._reconnect_attempts < self._RECONNECT_MAX):
            self._reconnect_attempts += 1
            self.notify.emit(self._tr("dropped", tries=self._reconnect_attempts, max=self._RECONNECT_MAX), "info")
            # «мягко» останавливаем core (даже если процесс уже мёртв — безопасно), сбрасываем системный прокси
            try:
                self._core.stop()
            except Exception:
                pass
            self._set_system_proxy(False)
            self._set_status("disconnected")
            QTimer.singleShot(1500, self._reconnect_now)
        else:
            self._disconnect()
            if not self._user_disconnected and self._reconnect_attempts >= self._RECONNECT_MAX:
                self.notify.emit(self._tr("dropfail"), "error")

    def _reconnect_now(self) -> None:
        """Запуск повторной попытки подключения watchdog'ом. Намерение восстановления."""
        if self._user_disconnected or self._status != "disconnected":
            return
        # _user_disconnected уже False с момента _begin_connect; здесь не сбрасываем счётчик
        srv = self._selected_server()
        if not srv or not srv.get("address"):
            return
        settings = dict(self._settings)
        settings["tun"] = (self._mode == "tun")
        self._set_status("connecting")
        try:
            self._core.start(srv, settings, on_log=self._logLine.emit)
        except Exception as e:
            self._set_status("disconnected")
            self.notify.emit(self._tr("reconnectfail", err=str(e)[:80]), "error")
            return
        self._conn_tries = 0
        self._connect_timer.start()


class HotkeyManager(QAbstractNativeEventFilter):
    """Глобальный системный хоткей (Windows RegisterHotKey) — работает,
    даже когда окно свёрнуто в трей. Триггерит backend.toggle()."""

    WM_HOTKEY = 0x0312
    MOD_NOREPEAT = 0x4000
    HOTKEY_ID = 0xB001

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self._backend = backend
        self._u32 = ctypes.windll.user32
        self._registered = False
        backend.hotkeyChanged.connect(self.reregister)
        self.reregister()

    def reregister(self) -> None:
        try:
            if self._registered:
                self._u32.UnregisterHotKey(None, self.HOTKEY_ID)
                self._registered = False
            if self._backend._hotkey_enabled and not self._backend._hk_suspended and self._backend._hk_vk:
                ok = self._u32.RegisterHotKey(None, self.HOTKEY_ID,
                                              self._backend._hk_mods | self.MOD_NOREPEAT,
                                              self._backend._hk_vk)
                self._registered = bool(ok)
        except Exception:
            pass

    def nativeEventFilter(self, eventType, message):
        try:
            et = bytes(eventType)
        except Exception:
            et = eventType
        if et == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    self._backend.toggle()
            except Exception:
                pass
        return False, 0


def _windows_uses_light_theme() -> bool:
    """Текущая системная тема Windows = light. Через HKCU\\...\\Personalize\\SystemUsesLightTheme."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0, winreg.KEY_READ)
        try:
            val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return bool(val)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _adapt_tray_icon(path: str, light: bool) -> QIcon:
    """На светлой теме: добавляем тонкий белый ореол вокруг непрозрачного силуэта,
    чтобы тёмные пиксели иконки не сливались с белой панелью задач. На тёмной — оригинал."""
    if not light:
        return QIcon(path)
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon(path)
    # маска: где у иконки альфа > 0 — закрашиваем белым (200/255 прозрачности)
    shadow = QPixmap(pix.size())
    shadow.fill(Qt.transparent)
    sp = QPainter(shadow)
    sp.drawPixmap(0, 0, pix)
    sp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    sp.fillRect(shadow.rect(), QColor(255, 255, 255, 220))
    sp.end()
    # композим: маска смещённая в 8 направлениях + поверх оригинал
    out = QPixmap(pix.size())
    out.fill(Qt.transparent)
    op = QPainter(out)
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (1, 1), (1, -1), (-1, 1)]:
        op.drawPixmap(dx, dy, shadow)
    op.drawPixmap(0, 0, pix)
    op.end()
    return QIcon(out)


class AppController(QObject):
    """Трей + жизненный цикл UI. В трее QML-сцена полностью выгружается,
    остаётся только «движок» (backend) и иконка — чтобы не нагружать комп."""

    def __init__(self, app: QApplication, backend: Backend, qml_dir) -> None:
        super().__init__()
        self._app = app
        self._backend = backend
        self._qml_dir = qml_dir
        self._engine = None
        # снимок QML-настроек: переживает выгрузку UI И полный перезапуск приложения
        # (load с диска при __init__; save при unload UI / quit).
        self._snap = self._load_settings_snapshot()

        # кадры анимации трея: f00 = выглядывает (подключено) … fN = спрятан (отключено).
        # На светлой теме Windows добавляем белый ореол, чтобы тёмные пиксели иконки не сливались с панелью задач.
        tray_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "tray")
        light_theme = _windows_uses_light_theme()
        self._frames = []
        i = 0
        while os.path.exists(os.path.join(tray_dir, f"f{i:02d}.png")):
            self._frames.append(_adapt_tray_icon(os.path.join(tray_dir, f"f{i:02d}.png"), light_theme))
            i += 1
        self._nframes = len(self._frames)
        self._frame_idx = (self._nframes - 1) if self._nframes else 0   # старт — спрятан
        self._target_idx = self._frame_idx
        self._anim = QTimer(self)
        self._anim.setInterval(45)
        self._anim.timeout.connect(self._anim_step)

        self._tray = QSystemTrayIcon(self)
        if self._frames:
            self._tray.setIcon(self._frames[self._frame_idx])
        self._tray.setToolTip("Kitsune")
        self._menu = QMenu()
        self._tray.setContextMenu(self._menu)
        self._menu.aboutToShow.connect(self._rebuild_menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

        backend.statusChanged.connect(self._on_status)
        backend.statsChanged.connect(self._refresh_tip)
        backend.serverChanged.connect(self._refresh_tip)
        self._on_status()

    # ---- анимация трея: китсунэ выглядывает/прячется ----
    def _on_status(self) -> None:
        st = self._backend._status
        if st == "connected":
            self._target_idx = 0                       # полностью выглянул
        elif st == "connecting":
            self._target_idx = max(0, self._nframes // 2)   # выглядывает наполовину
        else:
            self._target_idx = self._nframes - 1        # спрятался
        if self._frames and not self._anim.isActive():
            self._anim.start()
        self._refresh_tip()

    def _anim_step(self) -> None:
        if not self._frames:
            self._anim.stop()
            return
        if self._frame_idx < self._target_idx:
            self._frame_idx += 1
        elif self._frame_idx > self._target_idx:
            self._frame_idx -= 1
        else:
            self._anim.stop()
            return
        self._tray.setIcon(self._frames[self._frame_idx])

    def _refresh_tip(self) -> None:
        st = self._backend._status
        label = {"connected": "Подключено", "connecting": "Подключение…", "disconnected": "Отключено"}[st]
        tip = "Kitsune · " + label
        if st == "connected":
            tip += f" · {self._backend._server} · {self._backend._ping} ms"
        self._tray.setToolTip(tip)

    # ---- меню трея ----
    def _rebuild_menu(self) -> None:
        m = self._menu
        m.clear()
        b = self._backend
        st = b._status
        head = {"connected": "● Подключено", "connecting": "◌ Подключение…", "disconnected": "○ Отключено"}[st]
        a = m.addAction(head)
        a.setEnabled(False)
        info = f"    {b._server} · {b._ping} ms" if st == "connected" else f"    {b._server}"
        a2 = m.addAction(info)
        a2.setEnabled(False)
        m.addSeparator()
        ac = m.addAction("Подключить")
        ac.setEnabled(st == "disconnected")
        ac.triggered.connect(b.connectVpn)
        ad = m.addAction("Отключить")
        ad.setEnabled(st in ("connected", "connecting"))
        ad.triggered.connect(b.disconnectVpn)
        sub = m.addMenu("Сменить сервер")
        for s in b._cur()["servers"]:
            name = s["country"] + " · " + s["city"]
            sa = sub.addAction(f"{name}    {s['ping']} ms")
            sa.setCheckable(True)
            sa.setChecked(name == b._server)
            sa.triggered.connect(lambda checked=False, n=name: b.selectServer(n))
        m.addSeparator()
        m.addAction("Показать окно", self.showUi)
        m.addAction("Выход", self.quit)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.showUi()

    # ---- жизненный цикл UI ----
    @Slot()
    def showUi(self) -> None:
        if self._engine is None:
            self._engine = QQmlApplicationEngine()
            ctx = self._engine.rootContext()
            ctx.setContextProperty("backend", self._backend)
            ctx.setContextProperty("appCtl", self)
            self._engine.addImportPath(str(self._qml_dir))
            self._engine.load(str(self._qml_dir / "App" / "Main.qml"))
            roots0 = self._engine.rootObjects()
            if roots0 and self._snap is not None:
                roots0[0].setProperty("settingsSnapshot", self._snap)
                QMetaObject.invokeMethod(roots0[0], "importSettings")
        roots = self._engine.rootObjects() if self._engine else []
        if roots:
            w = roots[0]
            w.show()
            w.raise_()
            w.requestActivate()

    @Slot()
    def hideToTray(self) -> None:
        self._capture_settings()
        # уничтожаем сцену в следующем тике (нельзя из её же колбэка)
        QTimer.singleShot(0, self._destroy_ui)

    @Slot()
    def persistSettings(self) -> None:
        """Принудительно скинуть QML-snapshot на диск (для wizard'а, реактивных триггеров)."""
        self._capture_settings()

    def _capture_settings(self) -> None:
        try:
            roots = self._engine.rootObjects() if self._engine else []
            if roots:
                QMetaObject.invokeMethod(roots[0], "exportSettings")
                self._snap = roots[0].property("settingsSnapshot")
                self._backend.applyConfig(self._snap)
                self._save_settings_snapshot(self._snap)
        except Exception:
            pass

    # ---- settings persistence (диск %LocalAppData%\Kitsune\settings.json) ----
    def _settings_path(self):
        return engine.state_dir() / "settings.json"

    def _load_settings_snapshot(self):
        try:
            p = self._settings_path()
            if p.exists():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
        return None

    def _save_settings_snapshot(self, snap):
        try:
            self._settings_path().write_text(snap or "{}", encoding="utf-8")
        except Exception:
            pass

    def _destroy_ui(self) -> None:
        if self._engine is not None:
            self._engine.deleteLater()
            self._engine = None

    @Slot()
    def quit(self) -> None:
        try:
            # последний капчур настроек + сохранение groups (если UI был открыт)
            self._capture_settings()
            self._backend._save_state()
            self._backend._core.stop()
            self._backend._set_system_proxy(False)
            # КРИТИЧНО: снимаем kill-switch правило, иначе после quit'a юзер останется без интернета
            engine.firewall_unblock_all()
        except Exception:
            pass
        self._tray.hide()
        self._app.quit()


def _exe_and_args_for_task() -> tuple[str, str] | None:
    """Возвращает (exe, args) для регистрации scheduled-task, либо None если путь не resolveable."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--elevated"
    script = os.path.abspath(sys.argv[0]) if sys.argv else ""
    if script and os.path.exists(script):
        return sys.executable, subprocess.list2cmdline([script, "--elevated"])
    return None


def _try_silent_elevate() -> bool:
    """Если зарегистрирована scheduled-task — запустить через неё (без UAC).
    Иначе — ShellExecute "runas" (UAC). Возвращает True если elevated-инстанс пошёл стартовать."""
    if engine.has_elevate_task() and engine.run_elevate_task():
        return True
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = subprocess.list2cmdline(sys.argv[1:] + ["--elevated"])
            workdir = os.path.dirname(sys.executable)
        else:
            exe = sys.executable
            script = os.path.abspath(sys.argv[0])
            params = subprocess.list2cmdline([script] + sys.argv[1:] + ["--elevated"])
            workdir = os.path.dirname(script)
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
        return int(r) > 32
    except Exception:
        return False


def main() -> int:
    # single-instance: вторая попытка запуска просто фокусирует уже открытое окно.
    # --elevated пропускаем — это перезапуск через UAC, старый инстанс уже умирает.
    if "--elevated" not in sys.argv and _focus_existing_instance():
        return 0

    # Auto-elevation: один раз спросили UAC, дальше через scheduled-task без вопросов.
    # --no-elevate — escape hatch для dev / тестирования non-admin поведения.
    if (
        "--elevated" not in sys.argv
        and "--no-elevate" not in sys.argv
        and not engine.is_admin()
        and _try_silent_elevate()
    ):
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("Kitsune")
    app.setOrganizationName("KitsuneVPN")
    app.setQuitOnLastWindowClosed(False)  # окно закрыли -> уходим в трей, не выходим

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    QQuickStyle.setStyle("Basic")

    backend = Backend()
    qml_dir = Path(__file__).resolve().parent / "qml"
    ctl = AppController(app, backend, qml_dir)
    ctl.showUi()

    single = SingleInstanceServer()
    single.showRequested.connect(ctl.showUi)
    ctl._single = single  # держим ссылку, чтобы pipe не закрылся

    hotkeys = HotkeyManager(backend)          # глобальный хоткей вкл/выкл
    app.installNativeEventFilter(hotkeys)
    ctl._hotkeys = hotkeys                     # держим ссылку
    QTimer.singleShot(400, backend.startup)  # авто-пинг + автоподключение на старте

    # один раз elevated — закрепляем silent re-elevation на будущее
    if engine.is_admin() and not engine.has_elevate_task():
        spec = _exe_and_args_for_task()
        if spec is not None:
            engine.install_elevate_task(spec[0], spec[1])

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
