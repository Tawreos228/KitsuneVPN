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
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote

import engine

from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt, QAbstractNativeEventFilter, QMetaObject
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle


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

    def __init__(self) -> None:
        super().__init__()
        self._status = "disconnected"          # disconnected | connecting | connected
        self._server = "Netherlands · Amsterdam"
        self._ping = 0
        self._down = 0.0                       # MB за сессию (мок)
        self._up = 0.0
        self._elapsed = 0                      # секунды
        self._exit_ip = ""                     # внешний IP (мок)
        self._mode = "proxy"                   # proxy | tun
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
        self._groups = [
            {
                "name": "Мои сервера", "type": "manual", "url": "",
                "updated": "—", "auto": False, "config": None,
                "servers": [
                    {"code": "NL", "country": "Netherlands", "city": "Amsterdam", "ping": 38},
                    {"code": "DE", "country": "Germany", "city": "Frankfurt", "ping": 52},
                    {"code": "US", "country": "United States", "city": "New York", "ping": 96},
                ],
            },
            {
                "name": "FastVPN", "type": "subscription",
                "url": "https://sub.fastvpn.io/s/ab12cd34",
                "updated": "сегодня 14:20", "auto": True,
                "config": {"dns": "https://dns.fastvpn.io/dns-query", "adblock": True, "final": 0},
                "servers": [
                    {"code": "NL", "country": "Netherlands", "city": "Amsterdam", "ping": 41},
                    {"code": "FR", "country": "France", "city": "Paris", "ping": 47},
                    {"code": "GB", "country": "United Kingdom", "city": "London", "ping": 61},
                    {"code": "SE", "country": "Sweden", "city": "Stockholm", "ping": 70},
                ],
            },
            {
                "name": "Free Nodes", "type": "subscription",
                "url": "https://freenodes.example/sub.txt",
                "updated": "вчера", "auto": False,
                "config": {"dns": "8.8.8.8", "adblock": False, "final": 0},
                "servers": [
                    {"code": "JP", "country": "Japan", "city": "Tokyo", "ping": 138},
                    {"code": "SG", "country": "Singapore", "city": "Singapore", "ping": 152},
                ],
            },
        ]

        self._core = engine.Core()
        self._conn_tries = 0
        self._connect_timer = QTimer(self)       # поллинг порта во время подключения
        self._connect_timer.setInterval(300)
        self._connect_timer.timeout.connect(self._poll_connect)

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

        self._ping_job = QTimer(self)
        self._ping_job.setSingleShot(True)
        self._ping_job.timeout.connect(self._finish_ping)

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
        self.notify.emit("Горячая клавиша: " + text, "info")

    @Slot(bool)
    def suspendHotkey(self, s: bool) -> None:
        self._hk_suspended = s
        self.hotkeyChanged.emit()

    # ---- actions ----
    @Slot()
    def toggle(self) -> None:
        if self._status == "disconnected":
            self._begin_connect()
        elif self._status == "connecting":
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
        else:
            self._disconnect()

    def _selected_server(self):
        for s in self._cur()["servers"]:
            if s["country"] + " · " + s["city"] == self._server:
                return s
        return None

    def _begin_connect(self) -> None:
        srv = self._selected_server()
        if not srv or not srv.get("address"):
            self.notify.emit("Нет данных сервера — выберите рабочий профиль", "error")
            return
        self._set_status("connecting")
        try:
            self._core.start(srv)
        except Exception as e:
            self._set_status("disconnected")
            self.notify.emit("Ошибка ядра · " + str(e)[:80], "error")
            return
        self._conn_tries = 0
        self._connect_timer.start()

    def _poll_connect(self) -> None:
        self._conn_tries += 1
        if engine.port_listening():
            self._connect_timer.stop()
            self._on_connected()
        elif self._conn_tries > 26:          # ~8 c
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
            self.notify.emit("Не удалось подключиться · таймаут", "error")

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
            self._connect_timer.stop()
            self._core.stop()
            self._set_status("disconnected")
        elif self._status == "connected":
            self._disconnect()

    @Slot(str)
    def selectServer(self, name: str) -> None:
        if name == self._server:
            return
        self._server = name
        self.serverChanged.emit()
        # бесшовно: соединение не рвём, меняем выходной узел "на лету"
        if self._status == "connected":
            for s in self._cur()["servers"]:
                if s["country"] + " · " + s["city"] == name:
                    self._ping = s["ping"]
                    break
            self.statsChanged.emit()
            self.notify.emit("Переключено · " + name, "success")

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
        self.notify.emit(f"Лучший сервер: {self._server} · {best['ping']} ms", "success")

    @Slot()
    def simulateError(self) -> None:
        """Только для прототипа: показать, как всплывает ошибка."""
        if self._status == "connecting":
            self._connect_timer.stop()
        self._tick.stop()
        self._set_status("disconnected")
        self.notify.emit(
            "Не удалось установить соединение · таймаут рукопожатия",
            "error",
        )

    @Slot(str)
    def setMode(self, m: str) -> None:
        if m != self._mode:
            self._mode = m
            self.modeChanged.emit()
            self.notify.emit("Режим · " + ("TUN" if m == "tun" else "Прокси"), "info")

    @Slot()
    def pingAll(self) -> None:
        if self._pinging:
            return
        self._pinging = True
        self.pingingChanged.emit()
        self._ping_job.start(900)

    @Slot()
    def startup(self) -> None:
        """Запуск приложения: сразу пингуем сервера, затем (опционально) автоподключение."""
        self._pending_autoconnect = self._auto_connect and self._status == "disconnected"
        self.pingAll()

    def _finish_ping(self) -> None:
        base = {"NL": 36, "DE": 50, "US": 92, "GB": 60, "FR": 46,
                "SE": 68, "JP": 135, "SG": 150}
        g = dict(self._groups[self._currentGroup])
        g["servers"] = [
            {**s, "ping": max(8, base.get(s["code"], 80) + random.randint(-12, 22))}
            for s in g["servers"]
        ]
        self._groups = self._groups[:self._currentGroup] + [g] + self._groups[self._currentGroup + 1:]
        if self._status == "connected":
            for s in g["servers"]:
                if s["country"] + " · " + s["city"] == self._server:
                    self._ping = s["ping"]
                    self.statsChanged.emit()
                    break
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

    @Slot(str, str, bool)
    def addSubscription(self, name: str, url: str, auto: bool) -> None:
        pool = [("US", "United States", "Los Angeles"), ("CA", "Canada", "Toronto"),
                ("NL", "Netherlands", "Rotterdam"), ("DE", "Germany", "Berlin"),
                ("FI", "Finland", "Helsinki"), ("JP", "Japan", "Osaka")]
        picks = random.sample(pool, 3)
        servers = [{"code": c, "country": co, "city": ci, "ping": random.randint(40, 160)}
                   for c, co, ci in picks]
        self._groups = self._groups + [{
            "name": name or "Новая подписка", "type": "subscription", "url": url,
            "updated": "только что", "auto": auto,
            "config": {"dns": "https://1.1.1.1/dns-query", "adblock": False, "final": 0},
            "servers": servers,
        }]
        self.groupsChanged.emit()
        self.notify.emit("Подписка добавлена · " + (name or "Новая"), "success")
        self.setCurrentGroup(len(self._groups) - 1)

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

    @Slot(int)
    def updateGroup(self, i: int) -> None:
        if i < 0 or i >= len(self._groups):
            return
        g = dict(self._groups[i])
        g["servers"] = [{**s, "ping": max(8, s["ping"] + random.randint(-15, 15))} for s in g["servers"]]
        g["updated"] = "только что"
        self._groups = self._groups[:i] + [g] + self._groups[i + 1:]
        self.groupsChanged.emit()
        if i == self._currentGroup:
            self.serversChanged.emit()
        self.notify.emit("Подписка обновлена · " + g["name"], "success")

    @Slot(int, bool)
    def setGroupAuto(self, i: int, val: bool) -> None:
        if i < 0 or i >= len(self._groups):
            return
        g = dict(self._groups[i])
        g["auto"] = val
        self._groups = self._groups[:i] + [g] + self._groups[i + 1:]
        self.groupsChanged.emit()

    # ---- сервера (профили) ----
    _PROFILE_KEYS = ["protocol", "address", "port", "uuid", "password", "method",
                     "tls", "sni", "reality", "pbk", "sid", "transport", "path",
                     "host", "serviceName", "wgKey", "flow", "name", "encryption", "fp"]

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

    @Slot("QVariantMap")
    def addServer(self, data: dict) -> None:
        srv = self._make_server(data)
        servers = list(self._cur()["servers"]) + [srv]
        self._replace_group_servers(servers)
        self.notify.emit("Сервер добавлен · " + srv["country"], "success")

    @Slot(int, "QVariantMap")
    def updateServer(self, i: int, data: dict) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        old = servers[i]
        srv = self._make_server(data, keep_ping=old.get("ping", 60))
        srv["fav"] = old.get("fav", False)
        servers[i] = srv
        self._replace_group_servers(servers)
        self.notify.emit("Сервер обновлён · " + srv["country"], "info")

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
        self.notify.emit("Сервер удалён · " + name, "info")

    @Slot(int)
    def duplicateServer(self, i: int) -> None:
        servers = list(self._cur()["servers"])
        if i < 0 or i >= len(servers):
            return
        s = dict(servers[i])
        s["country"] = (s.get("country", "") + " (копия)")
        servers.insert(i + 1, s)
        self._replace_group_servers(servers)
        self.notify.emit("Дублировано · " + s["country"], "success")

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
        added = [self._make_server(d) for d in (self._parse_link(l) for l in links) if d]
        if not added:
            self.notify.emit("В буфере нет валидных ссылок", "error")
            return 0
        servers = list(self._cur()["servers"]) + added
        self._replace_group_servers(servers)
        self.notify.emit(f"Импортировано серверов: {len(added)}", "success")
        return len(added)

    @Slot(result=int)
    def importFromClipboard(self) -> int:
        return self._import_text(QApplication.clipboard().text())

    @Slot(str, result=int)
    def importText(self, text: str) -> int:
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
        self.notify.emit("Скопировано", "success")

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
        self._ping = random.randint(34, 96)          # TODO: реальный пинг через Clash API
        self._elapsed = 0
        self._down = 0.0
        self._up = 0.0
        self._exit_ip = "%d.%d.%d.%d" % (random.randint(5, 223), random.randint(0, 255),
                                         random.randint(0, 255), random.randint(1, 254))  # TODO: реальный IP
        self.statsChanged.emit()
        self._tick.start()
        if self._mode == "proxy":
            self._set_system_proxy(True)
        self.notify.emit("Подключено · " + self._server, "success")

    def _disconnect(self) -> None:
        self._connect_timer.stop()
        self._core.stop()
        self._set_system_proxy(False)
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
        self._down += random.uniform(0.15, 2.6)
        self._up += random.uniform(0.05, 0.7)
        # лёгкое дыхание пинга
        self._ping = max(18, self._ping + random.randint(-4, 4))
        self.statsChanged.emit()


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


class AppController(QObject):
    """Трей + жизненный цикл UI. В трее QML-сцена полностью выгружается,
    остаётся только «движок» (backend) и иконка — чтобы не нагружать комп."""

    def __init__(self, app: QApplication, backend: Backend, qml_dir) -> None:
        super().__init__()
        self._app = app
        self._backend = backend
        self._qml_dir = qml_dir
        self._engine = None
        self._snap = None   # снимок QML-настроек, переживает выгрузку UI

        # кадры анимации трея: f00 = выглядывает (подключено) … fN = спрятан (отключено)
        tray_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "tray")
        self._frames = []
        i = 0
        while os.path.exists(os.path.join(tray_dir, f"f{i:02d}.png")):
            self._frames.append(QIcon(os.path.join(tray_dir, f"f{i:02d}.png")))
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

    def _capture_settings(self) -> None:
        try:
            roots = self._engine.rootObjects() if self._engine else []
            if roots:
                QMetaObject.invokeMethod(roots[0], "exportSettings")
                self._snap = roots[0].property("settingsSnapshot")
        except Exception:
            pass

    def _destroy_ui(self) -> None:
        if self._engine is not None:
            self._engine.deleteLater()
            self._engine = None

    @Slot()
    def quit(self) -> None:
        try:
            self._backend._core.stop()
            self._backend._set_system_proxy(False)
        except Exception:
            pass
        self._tray.hide()
        self._app.quit()


def main() -> int:
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
    hotkeys = HotkeyManager(backend)          # глобальный хоткей вкл/выкл
    app.installNativeEventFilter(hotkeys)
    ctl._hotkeys = hotkeys                     # держим ссылку
    QTimer.singleShot(400, backend.startup)  # авто-пинг + автоподключение на старте
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
