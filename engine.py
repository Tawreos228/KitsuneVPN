"""
Kitsune engine — реальная обёртка над ядром sing-box.

Отвечает за: генерацию sing-box JSON из профиля, валидацию (sing-box check),
запуск/остановку процесса ядра, проверку локального порта.
Сетевое управление (системный прокси / TUN / Clash API статистика) — на следующих шагах.
"""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent / "core"
MIXED_PORT = 2080


def core_cmd() -> list[str]:
    """База команды ядра. Если есть патченый nekobox_core (больше протоколов) — берём его
    в CLI-режиме (`sing-box` subcommand), иначе официальный sing-box."""
    nb = _CORE_DIR / "nekobox_core.exe"
    if nb.exists():
        return [str(nb), "sing-box"]
    return [str(_CORE_DIR / "sing-box.exe")]


def _tls_block(s: dict) -> dict | None:
    if not s.get("tls"):
        return None
    tls = {
        "enabled": True,
        "server_name": s.get("sni") or s.get("address", ""),
        "utls": {"enabled": True, "fingerprint": s.get("fp") or "chrome"},
    }
    if s.get("reality"):
        tls["reality"] = {
            "enabled": True,
            "public_key": s.get("pbk", ""),
            "short_id": s.get("sid", ""),
        }
    return tls


def _transport_block(s: dict) -> dict | None:
    t = s.get("transport", "tcp")
    if t == "ws":
        tr = {"type": "ws", "path": s.get("path") or "/"}
        if s.get("host"):
            tr["headers"] = {"Host": s["host"]}
        return tr
    if t == "grpc":
        return {"type": "grpc", "service_name": s.get("serviceName") or ""}
    if t == "httpupgrade":
        tr = {"type": "httpupgrade", "path": s.get("path") or "/"}
        if s.get("host"):
            tr["host"] = s["host"]
        return tr
    return None  # tcp


def build_outbound(s: dict) -> dict:
    """Профиль (наш словарь) -> sing-box outbound (tag=proxy)."""
    proto = (s.get("protocol") or "vless").lower()
    base = {"tag": "proxy", "server": s.get("address", ""), "server_port": int(s.get("port") or 443)}
    tls = _tls_block(s)
    tr = _transport_block(s)

    if proto == "vless":
        ob = {"type": "vless", **base, "uuid": s.get("uuid", "")}
        if s.get("flow"):
            ob["flow"] = s["flow"]
        if s.get("encryption") and s["encryption"] != "none":
            ob["encryption"] = s["encryption"]
    elif proto == "vmess":
        ob = {"type": "vmess", **base, "uuid": s.get("uuid", ""), "security": "auto"}
    elif proto == "trojan":
        ob = {"type": "trojan", **base, "password": s.get("password", "")}
    elif proto == "shadowsocks":
        ob = {"type": "shadowsocks", **base,
              "method": s.get("method") or "aes-256-gcm", "password": s.get("password", "")}
    else:
        # wireguard и прочее — TODO (отдельная схема endpoints в sing-box 1.13)
        ob = {"type": "direct", "tag": "proxy"}
        return ob

    if tls:
        ob["tls"] = tls
    if tr:
        ob["transport"] = tr
    return ob


def gen_config(server: dict | None, mixed_port: int = MIXED_PORT) -> dict:
    """Полный sing-box конфиг: mixed inbound + outbound(proxy|direct) + маршрут."""
    outbounds = [{"type": "direct", "tag": "direct"}]
    final = "direct"
    if server:
        outbounds.insert(0, build_outbound(server))
        final = "proxy"
    return {
        "log": {"level": "warn"},
        "inbounds": [{
            "type": "mixed",
            "listen": "127.0.0.1",
            "listen_port": mixed_port,
        }],
        "outbounds": outbounds,
        "route": {"final": final},
    }


def check_config(cfg: dict) -> tuple[bool, str]:
    """Валидация конфига встроенной проверкой sing-box."""
    f = Path(tempfile.gettempdir()) / "kitsune_check.json"
    f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(core_cmd() + ["check", "-c", str(f)],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def port_listening(port: int = MIXED_PORT, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


class Core:
    """Жизненный цикл процесса sing-box."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._cfg_path = Path(tempfile.gettempdir()) / "kitsune_run.json"

    def start(self, server: dict | None) -> None:
        self.stop()
        cfg = gen_config(server)
        ok, msg = check_config(cfg)
        if not ok:
            raise RuntimeError("Невалидный конфиг: " + msg)
        self._cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(core_cmd() + ["run", "-c", str(self._cfg_path)],
                                      creationflags=flags)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
