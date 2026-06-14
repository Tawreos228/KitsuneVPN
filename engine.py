"""
Kitsune engine — реальная обёртка над ядром sing-box.

Отвечает за: генерацию sing-box JSON из профиля, валидацию (sing-box check),
запуск/остановку процесса ядра, проверку локального порта.
Сетевое управление (системный прокси / TUN / Clash API статистика) — на следующих шагах.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent / "core"
_RULESETS_DIR = _CORE_DIR / "rulesets"


def state_dir() -> Path:
    """Папка для персистентного состояния (groups/settings) — %LocalAppData%\\Kitsune."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = Path(base) / "Kitsune"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p
MIXED_PORT = 2080
CLASH_HOST = "127.0.0.1"
CLASH_PORT = 9090
PROXY_TAG = "proxy"
_GH_SINGBOX_API = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
_GH_NEKORAY_API = "https://api.github.com/repos/MatsuriDayo/nekoray/releases/latest"
_GH_KITSUNE_API = "https://api.github.com/repos/Tawreos228/KitsuneVPN/releases/latest"

# Версия приложения — синхронизировать с installer.iss MyAppVersion перед каждым релизом.
APP_VERSION = "0.1.2"

# базы для bundled-подобных rule-set'ов (тянутся ядром по требованию)
_GEOSITE_URL = "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-{}.srs"
_GEOIP_URL = "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-{}.srs"

_MUX_PROTOS = {0: "smux", 1: "yamux", 2: "h2mux"}


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
    if t == "xhttp":
        tr = {"type": "xhttp", "path": s.get("path") or "/"}
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


def _dns_server(addr: str, tag: str, detour: str | None) -> dict:
    """Адрес DNS (URL или IP) -> sing-box DNS server (новый формат 1.12+)."""
    addr = (addr or "").strip()
    if "://" in addr:
        scheme, rest = addr.split("://", 1)
    else:
        scheme, rest = "udp", addr
    scheme = scheme.lower()
    path = ""
    host = rest
    if "/" in rest:
        host, tail = rest.split("/", 1)
        path = "/" + tail
    typ = {"https": "https", "h3": "h3", "tls": "tls",
           "quic": "quic", "udp": "udp", "tcp": "tcp"}.get(scheme, "udp")
    srv: dict = {"tag": tag, "type": typ, "server": host or "1.1.1.1"}
    if typ in ("https", "h3") and path and path != "/":
        srv["path"] = path
    if detour:
        srv["detour"] = detour
    return srv


def _dns_block(server: dict | None, settings: dict) -> dict:
    """DNS-секция: удалённый (через proxy) + прямой + опц. fake-ip.

    Важно: detour на ПУСТОЙ direct-outbound в sing-box 1.13 — фатальная ошибка рантайма,
    поэтому для прямого DNS detour не ставим (маршрутизируется напрямую по умолчанию)."""
    remote = _dns_server(settings.get("dnsRemote") or "https://1.1.1.1/dns-query",
                         "remote", "proxy" if server else None)
    direct = _dns_server(settings.get("dnsDirect") or "223.5.5.5", "direct", None)
    servers = [remote, direct]
    rules = []
    if settings.get("fakeip"):
        servers.append({"tag": "fakeip", "type": "fakeip",
                        "inet4_range": "198.18.0.0/15", "inet6_range": "fc00::/18"})
        rules.append({"query_type": ["A", "AAAA"], "server": "fakeip"})
    return {"servers": servers, "rules": rules, "final": "remote"}


def _ruleset_def(tag: str, detour: str | None) -> dict:
    """tag вида geosite-ru / geoip-ru -> rule-set definition.
    Если есть локальный файл в core/rulesets/<tag>.srs — используем его (offline-ready,
    устойчивость к недоступности github). Иначе — remote с download_detour."""
    local = _RULESETS_DIR / f"{tag}.srs"
    if local.exists():
        return {"type": "local", "tag": tag, "format": "binary", "path": str(local)}
    # fallback на github (старое поведение)
    if tag.startswith("geosite-"):
        url = _GEOSITE_URL.format(tag[len("geosite-"):])
    else:
        url = _GEOIP_URL.format(tag[len("geoip-"):])
    d = {"type": "remote", "tag": tag, "format": "binary", "url": url}
    if detour:
        d["download_detour"] = detour
    return d


def _user_rule(r: dict, rule_sets: set) -> dict | None:
    """Правило из UI ({type,value,action}) -> sing-box route rule."""
    typ = (r.get("type") or "").lower()
    val = str(r.get("value") or "").strip()
    act = (r.get("action") or "proxy").lower()
    if not val:
        return None
    rule: dict = {}
    if typ == "domain":
        if val.startswith("*."):
            rule["domain_suffix"] = [val[1:]]
        elif val.startswith("."):
            rule["domain_suffix"] = [val]
        else:
            rule["domain"] = [val]
    elif typ == "geosite":
        tag = "geosite-" + val.lower()
        rule_sets.add(tag)
        rule["rule_set"] = [tag]
    elif typ == "geoip":
        tag = "geoip-" + val.lower()
        rule_sets.add(tag)
        rule["rule_set"] = [tag]
    elif typ == "ip":
        rule["ip_cidr"] = [val if "/" in val else val + "/32"]
    elif typ == "process":
        rule["process_name"] = [val]
    elif typ == "port":
        try:
            rule["port"] = [int(val)]
        except ValueError:
            return None
    else:
        return None
    if act == "block":
        rule["action"] = "reject"
    else:
        rule["outbound"] = "proxy" if act == "proxy" else "direct"
    return rule


def _route_block(server: dict | None, settings: dict) -> dict:
    """route-секция из UI-настроек: sniff/hijack-dns/LAN/правила/RU/adblock/final."""
    rules: list = []
    rule_sets: set = set()
    proxy_all = bool(settings.get("rtProxyAll"))

    if settings.get("sniff", True):
        rules.append({"action": "sniff"})
    # Перехват DNS: по порту 53 (надёжно для TUN-UDP, без зависимости от сниффа) + по протоколу.
    rules.append({"port": 53, "action": "hijack-dns"})
    rules.append({"protocol": "dns", "action": "hijack-dns"})
    if settings.get("rtLan", True):
        rules.append({"ip_is_private": True, "outbound": "direct"})

    for r in settings.get("routeRules") or []:
        ur = _user_rule(r, rule_sets)
        if not ur:
            continue
        # "Проксировать всё" игнорирует пользовательские обходы (direct), но не block
        if proxy_all and ur.get("outbound") == "direct":
            continue
        rules.append(ur)

    if settings.get("rtRegionDirect", True) and not proxy_all:
        rule_sets.update(("geosite-category-ru", "geoip-ru"))
        rules.append({"rule_set": ["geosite-category-ru", "geoip-ru"], "outbound": "direct"})
    if settings.get("rtAdblock"):
        rule_sets.add("geosite-category-ads-all")
        rules.append({"rule_set": ["geosite-category-ads-all"], "action": "reject"})

    rt_final = int(settings.get("rtFinal", 0) or 0)
    final = "direct" if rt_final == 1 else "proxy"
    if rt_final == 2:                       # «Блок»: всё неучтённое — отклонять
        rules.append({"action": "reject"})

    block: dict = {
        "rules": rules,
        "final": final if server else "direct",
        "default_domain_resolver": {"server": "direct"},
    }
    if rule_sets:
        detour = "proxy" if server else None
        block["rule_set"] = [_ruleset_def(t, detour) for t in sorted(rule_sets)]
    return block


def _tun_inbound(settings: dict) -> dict:
    """TUN inbound (системный туннель). Требует прав администратора в рантайме."""
    stack = {0: "gvisor", 1: "system", 2: "mixed"}.get(
        int(settings.get("tunStack", 0) or 0), "gvisor")
    try:
        mtu = int(settings.get("mtu") or 9000)
    except (TypeError, ValueError):
        mtu = 9000
    return {
        "type": "tun",
        "tag": "tun-in",
        "address": ["172.18.0.1/30", "fdfe:dcba:9876::1/126"],
        "mtu": mtu,
        "auto_route": True,
        # strict_route=true на Windows форсит локальный DNS в туннель через WFP и ломает резолвинг —
        # по умолчанию выключено (auto_route и так захватывает трафик, DNS работает через hijack).
        "strict_route": bool(settings.get("strictRoute", False)),
        "stack": stack,
    }


def _wireguard_endpoint(s: dict) -> dict:
    """Профиль WireGuard -> sing-box endpoint (в 1.11+ WG живёт в секции `endpoints`, не `outbounds`).
    Минимум для рабочего соединения: server+port, private_key (wgKey), peer_public_key (peerKey)."""
    try:
        mtu = int(s.get("mtu") or 1420)
    except (TypeError, ValueError):
        mtu = 1420
    local = s.get("localAddr") or "172.16.0.2/32"
    allowed = s.get("allowedIps") or "0.0.0.0/0"
    addrs = [a.strip() for a in (local.split(",") if isinstance(local, str) else local) if a.strip()]
    allowed_list = [a.strip() for a in (allowed.split(",") if isinstance(allowed, str) else allowed) if a.strip()]
    peer = {
        "address": s.get("address", ""),
        "port": int(s.get("port") or 51820),
        "public_key": s.get("peerKey", ""),
        "allowed_ips": allowed_list,
    }
    if s.get("psk"):
        peer["pre_shared_key"] = s["psk"]
    return {
        "type": "wireguard",
        "tag": "proxy",
        "address": addrs,
        "private_key": s.get("wgKey", ""),
        "mtu": mtu,
        "peers": [peer],
    }


def server_tag(idx: int) -> str:
    """Стабильный тег для outbound сервера по индексу. Используется и в gen_config, и в clash_select."""
    return f"srv-{idx}"


def _build_server_member(s: dict, tag: str, settings: dict) -> tuple[dict | None, dict | None]:
    """Один сервер → (outbound, endpoint). Один из них None (WG в endpoints, остальное в outbounds)."""
    proto = (s.get("protocol") or "vless").lower()
    if proto == "wireguard":
        ep = _wireguard_endpoint(s)
        ep["tag"] = tag
        return None, ep
    ob = build_outbound(s)
    ob["tag"] = tag
    if settings.get("mux"):
        ob["multiplex"] = {
            "enabled": True,
            "protocol": _MUX_PROTOS.get(int(settings.get("muxProto", 0) or 0), "smux"),
            "max_streams": 8,
        }
    return ob, None


def gen_config(server, settings: dict | None = None,
               mixed_port: int = MIXED_PORT) -> dict:
    """Полный sing-box конфиг. `server` может быть:
      - dict — одиночный профиль (тег outbound = 'proxy', как раньше);
      - list[dict] — несколько профилей; собирается selector-outbound 'proxy' с member-тегами
        srv-0..srv-N, активный = activeIdx из settings. Переключение на лету через `clash_select`.

    settings: portMixed, sniff, mux, muxProto, fakeip, dnsRemote, dnsDirect, rtLan, rtRegionDirect,
    rtAdblock, rtProxyAll, rtFinal, routeRules=[{type,value,action}], tun, tunStack, strictRoute, mtu, lan,
    activeIdx (для multi-server selector)."""
    settings = settings or {}
    try:
        port = int(settings.get("portMixed") or mixed_port)
    except (TypeError, ValueError):
        port = mixed_port

    outbounds = [{"type": "direct", "tag": "direct"}]
    endpoints: list = []

    # нормализуем: dict -> [dict], None -> []
    server_list = server if isinstance(server, list) else ([server] if server else [])

    if len(server_list) == 1:
        # одиночный сервер — теги как раньше ('proxy'), без селектора. Обратная совместимость.
        ob, ep = _build_server_member(server_list[0], PROXY_TAG, settings)
        if ob:
            outbounds.insert(0, ob)
        if ep:
            endpoints.append(ep)
    elif len(server_list) >= 2:
        # multi-server: каждому свой тег + selector-outbound 'proxy' над ними
        member_tags: list = []
        for i, s in enumerate(server_list):
            tag = server_tag(i)
            ob, ep = _build_server_member(s, tag, settings)
            if ob:
                outbounds.append(ob)
            if ep:
                endpoints.append(ep)
            member_tags.append(tag)
        try:
            active_idx = int(settings.get("activeIdx", 0) or 0)
        except (TypeError, ValueError):
            active_idx = 0
        active_idx = max(0, min(active_idx, len(member_tags) - 1))
        outbounds.append({
            "type": "selector",
            "tag": PROXY_TAG,
            "outbounds": member_tags,
            "default": member_tags[active_idx],
        })

    # listen: 0.0.0.0 разрешает подключения к нашему mixed-прокси из LAN; 127.0.0.1 — только локально
    listen_addr = "0.0.0.0" if settings.get("lan") else "127.0.0.1"
    inbounds = [{"type": "mixed", "listen": listen_addr, "listen_port": port}]
    route = _route_block(server, settings)
    if settings.get("tun"):
        inbounds.append(_tun_inbound(settings))
        # чтобы трафик до сервера и direct-узлов уходил через реальный интерфейс, а не в туннель
        route["auto_detect_interface"] = True

    cfg = {
        "log": {"level": "warn"},
        "experimental": {
            "clash_api": {"external_controller": f"{CLASH_HOST}:{CLASH_PORT}"},
            "cache_file": {"enabled": True,
                           "path": str(Path(tempfile.gettempdir()) / "kitsune_cache.db")},
        },
        "dns": _dns_block(server, settings),
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": route,
    }
    if endpoints:
        cfg["endpoints"] = endpoints
    return cfg


def check_config(cfg: dict) -> tuple[bool, str]:
    """Валидация конфига встроенной проверкой sing-box."""
    f = Path(tempfile.gettempdir()) / "kitsune_check.json"
    f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(core_cmd() + ["check", "-c", str(f)],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


# ---- автообновление ядра (sing-box.exe) ----
def core_version(exe: str = "sing-box.exe") -> str | None:
    """Версия бинаря ядра, напр. 'v1.13.11'. None если бинарь отсутствует/не отвечает."""
    p = _CORE_DIR / exe
    if not p.exists():
        return None
    try:
        args = ([str(p), "sing-box", "version"] if exe.lower().startswith("nekobox")
                else [str(p), "version"])
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        r = subprocess.run(args, capture_output=True, text=True, timeout=5,
                           creationflags=flags)
        # официальный sing-box: "sing-box version 1.13.12"
        # nekobox_core:        "sing-box version v1.13.11"
        m = re.search(r"sing-box version\s+v?(\d+\.\d+\.\d+[\w\.\-]*)", r.stdout or "")
        return ("v" + m.group(1)) if m else None
    except Exception:
        return None


def _github_latest(api_url: str) -> dict | None:
    try:
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "Kitsune/1.0",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def latest_singbox_release() -> dict | None:
    """{tag, url, name} последнего релиза SagerNet/sing-box для Windows amd64."""
    data = _github_latest(_GH_SINGBOX_API)
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name") or ""
    for asset in data.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith("windows-amd64.zip"):
            return {"tag": tag, "url": asset.get("browser_download_url"),
                    "name": asset.get("name")}
    return None


def latest_nekoray_release() -> dict | None:
    """Метаданные последнего релиза MatsuriDayo/nekoray (для информации; авто-обновление не реализуем)."""
    data = _github_latest(_GH_NEKORAY_API)
    if not isinstance(data, dict):
        return None
    return {"tag": data.get("tag_name") or "",
            "url": data.get("html_url"),
            "name": data.get("name")}


def latest_kitsune_release() -> dict | None:
    """{tag, setup_url, setup_size, notes_url} последнего релиза KitsuneVPN.
    Берёт первый asset, заканчивающийся на KitsuneSetup.exe (фиксированное имя в installer.iss)."""
    data = _github_latest(_GH_KITSUNE_API)
    if not isinstance(data, dict):
        return None
    tag = (data.get("tag_name") or "").lstrip("v")    # "v0.1.2" → "0.1.2"
    setup_url = ""
    setup_size = 0
    for asset in data.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith("kitsunesetup.exe"):
            setup_url = asset.get("browser_download_url") or ""
            setup_size = int(asset.get("size") or 0)
            break
    return {"tag": tag, "setup_url": setup_url, "setup_size": setup_size,
            "notes_url": data.get("html_url") or ""}


def _stream_download(url: str, dest: Path, on_progress=None, chunk: int = 65536) -> None:
    """Качает url в dest потоково, дёргая on_progress(read, total) после каждого чанка."""
    with urllib.request.urlopen(url, timeout=180) as r:
        total = int(r.headers.get("content-length") or 0)
        read = 0
        with open(dest, "wb") as f:
            while True:
                buf = r.read(chunk)
                if not buf:
                    break
                f.write(buf)
                read += len(buf)
                if on_progress:
                    try:
                        on_progress(read, total)
                    except Exception:
                        pass


def download_and_run_installer(url: str, on_progress=None) -> tuple[bool, str]:
    """Скачивает KitsuneSetup.exe в %TEMP% и запускает его.
    Возвращает (ok, msg). Caller должен вскоре завершить процесс — installer закроет старый.
    on_progress(read, total) — колбэк прогресса (вызывается из этого же потока)."""
    if not url:
        return False, "пустой url"
    try:
        tmp_dir = Path(tempfile.gettempdir())
        # уникальное имя, чтобы старый файл не залочил/не запутался с антивирусом
        dest = tmp_dir / f"Kitsune-update-{int(time.time())}.exe"
        _stream_download(url, dest, on_progress=on_progress)
    except Exception as e:
        return False, f"загрузка: {e}"
    try:
        # /SILENT — Inno Setup тихий режим: показ окна прогресса, без вопросов;
        # /CLOSEAPPLICATIONS — закрыть запущенный Kitsune, /RESTARTAPPLICATIONS — запустить после.
        import ctypes
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "open", str(dest), "/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
            str(tmp_dir), 1)
        if int(r) <= 32:
            return False, f"ShellExecute={int(r)}"
    except Exception as e:
        return False, f"запуск: {e}"
    return True, str(dest)


def install_core_update(url: str, dest_exe: str = "sing-box.exe", on_progress=None) -> tuple[bool, str]:
    """Скачать zip-релиз и подменить core/<dest_exe>. (ok, message).
    on_progress(read, total) — колбэк прогресса загрузки zip-файла.
    Если файл занят (ядро запущено) — Windows вернёт PermissionError, обработаем."""
    import io
    import zipfile
    dest = _CORE_DIR / dest_exe
    try:
        zip_tmp = Path(tempfile.gettempdir()) / f"singbox-{int(time.time())}.zip"
        _stream_download(url, zip_tmp, on_progress=on_progress)
        blob = zip_tmp.read_bytes()
        try: zip_tmp.unlink()
        except Exception: pass
        zf = zipfile.ZipFile(io.BytesIO(blob))
        match = None
        for n in zf.namelist():
            base = n.split("/")[-1]
            if base.lower() == dest_exe.lower():
                match = n
                break
        if not match:
            return False, f"в архиве нет {dest_exe}"
        tmp = dest.with_suffix(dest.suffix + ".new")
        with zf.open(match) as src, open(tmp, "wb") as out:
            out.write(src.read())
        # атомарная замена через .old (на случай если dest существует и не залочен)
        if dest.exists():
            old = dest.with_suffix(dest.suffix + ".old")
            try:
                if old.exists():
                    old.unlink()
                dest.rename(old)
            except PermissionError:
                tmp.unlink(missing_ok=True)
                return False, "файл занят (отключите соединение и попробуйте снова)"
        tmp.rename(dest)
        return True, "обновлено"
    except Exception as e:
        return False, str(e)[:140]


# ---- импорт правил маршрутизации из чужих клиентов ----
_CLASH_TYPE_MAP = {
    "DOMAIN":            "domain",
    "DOMAIN-SUFFIX":     "domain",       # значение запишем с '*.' впереди — наш _user_rule даст domain_suffix
    "IP-CIDR":           "ip",
    "IP-CIDR6":          "ip",
    "GEOIP":             "geoip",
    "GEOSITE":           "geosite",
    "PROCESS-NAME":      "process",
    "DST-PORT":          "port",
}
_CLASH_ACTION_MAP = {
    "DIRECT": "direct", "Direct": "direct", "direct": "direct",
    "REJECT": "block",  "Reject": "block",  "reject": "block",
    "REJECT-DROP": "block",
}


def _action_from_singbox(r: dict) -> str:
    """Маппинг sing-box rule → наш action (proxy/direct/block)."""
    if r.get("action") == "reject":
        return "block"
    ob = (r.get("outbound") or "").lower()
    if ob == "direct":
        return "direct"
    return "proxy"


def parse_singbox_rules(text: str) -> list[dict]:
    """sing-box JSON → наш формат. Принимает полный конфиг, объект с route.rules,
    объект с просто rules, или массив правил."""
    try:
        data = json.loads(text)
    except Exception:
        return []
    rules = data
    if isinstance(data, dict):
        if isinstance(data.get("route"), dict) and isinstance(data["route"].get("rules"), list):
            rules = data["route"]["rules"]
        elif isinstance(data.get("rules"), list):
            rules = data["rules"]
        else:
            return []
    if not isinstance(rules, list):
        return []
    out: list[dict] = []
    skip_actions = ("sniff", "hijack-dns", "resolve", "route-options")
    for r in rules:
        if not isinstance(r, dict):
            continue
        act_kind = r.get("action") or "route"
        if act_kind in skip_actions:
            continue
        # пропускаем системные правила: ip_is_private (LAN), protocol:dns
        if r.get("ip_is_private") or r.get("protocol") == "dns":
            continue
        action = _action_from_singbox(r)

        def push(typ: str, vals):
            if isinstance(vals, list):
                for v in vals:
                    out.append({"type": typ, "value": str(v), "action": action})
            elif vals is not None:
                out.append({"type": typ, "value": str(vals), "action": action})

        if "domain_suffix" in r:
            ds = r["domain_suffix"]
            for v in (ds if isinstance(ds, list) else [ds]):
                vs = str(v)
                # унифицируем под '*.' для UI
                if vs.startswith("."):
                    vs = "*" + vs
                out.append({"type": "domain", "value": vs, "action": action})
        if "domain" in r:
            push("domain", r["domain"])
        if "rule_set" in r:
            rs = r["rule_set"] if isinstance(r["rule_set"], list) else [r["rule_set"]]
            for tag in rs:
                t = str(tag)
                if t.startswith("geosite-"):
                    out.append({"type": "geosite", "value": t[len("geosite-"):], "action": action})
                elif t.startswith("geoip-"):
                    out.append({"type": "geoip", "value": t[len("geoip-"):], "action": action})
        if "ip_cidr" in r:
            push("ip", r["ip_cidr"])
        if "process_name" in r:
            push("process", r["process_name"])
        if "port" in r:
            push("port", r["port"])
    return out


def parse_clash_rules(text: str) -> list[dict]:
    """Clash/clash.meta YAML → наш формат. Минимальный парсер секции `rules:` без зависимости от PyYAML.
    Понимает форматы `- TYPE,VALUE,POLICY[,no-resolve]` (отступы + дефис)."""
    if not text:
        return []
    lines = text.splitlines()
    out: list[dict] = []
    in_block = False
    base_indent = -1
    for raw in lines:
        # ищем заголовок rules:
        if not in_block:
            if re.match(r"^\s*rules\s*:\s*(#.*)?$", raw):
                in_block = True
                base_indent = -1
                continue
            continue
        # внутри блока: пустые строки игнорим, выход — следующий top-level ключ
        if raw.strip() == "" or raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)-\s*(.+?)\s*$", raw)
        if not m:
            # не list-item → блок закончился
            in_block = False
            continue
        indent = len(m.group(1))
        if base_indent < 0:
            base_indent = indent
        elif indent < base_indent:
            in_block = False
            continue
        item = m.group(2)
        # снимаем кавычки если есть
        if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
            item = item[1:-1]
        parts = [p.strip() for p in item.split(",")]
        if len(parts) < 2:
            continue
        ctype = parts[0].upper()
        if ctype == "MATCH":               # финальный catch-all — пропускаем
            continue
        if ctype not in _CLASH_TYPE_MAP:    # неподдержанный (KEYWORD/SRC-PORT/...) — пропускаем
            continue
        ours_type = _CLASH_TYPE_MAP[ctype]
        cval = parts[1]
        policy = parts[2] if len(parts) >= 3 else "Proxy"
        action = _CLASH_ACTION_MAP.get(policy, "proxy")
        # нормализация значений
        if ctype == "DOMAIN-SUFFIX":
            cval = ("*." + cval) if not cval.startswith(("*.", ".")) else cval
        elif ctype in ("GEOIP", "GEOSITE"):
            cval = cval.lower()
        out.append({"type": ours_type, "value": cval, "action": action})
    return out


def parse_imported_rules(text: str) -> dict:
    """Авто-детект формата → парсинг. Возвращает {format, rules, count}.
    format ∈ {'singbox', 'clash', 'unknown'}."""
    if not text or not text.strip():
        return {"format": "unknown", "rules": [], "count": 0}
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        rules = parse_singbox_rules(text)
        return {"format": "singbox", "rules": rules, "count": len(rules)}
    if re.search(r"^\s*rules\s*:", text, flags=re.MULTILINE):
        rules = parse_clash_rules(text)
        return {"format": "clash", "rules": rules, "count": len(rules)}
    return {"format": "unknown", "rules": [], "count": 0}


def scan_apps_raw() -> list[dict]:
    """Сканер установленных приложений Windows: .lnk из Start Menu → exe. [{name, exe}].
    Использует WScript.Shell COM (через PowerShell) для резолва ярлыков. Фильтрует шум (uninstall/readme/help).
    Кодировки: явно ставим UTF-8 на стороне PS (иначе на ру-локали кириллица в именах ярлыков становится
    мусором из-за дефолтного cp866/UTF-16, и фильтр шума «Удалить»/«Справка» перестаёт срабатывать)."""
    ps = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding           = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'SilentlyContinue'
$wsh = New-Object -ComObject WScript.Shell
$paths = @(
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
)
$out = New-Object System.Collections.ArrayList
foreach ($d in $paths) {
    if (Test-Path $d) {
        Get-ChildItem -Path $d -Recurse -Filter *.lnk -Force | ForEach-Object {
            try {
                $sc = $wsh.CreateShortcut($_.FullName)
                $t = $sc.TargetPath
                if ($t -and $t.ToLower().EndsWith('.exe')) {
                    [void]$out.Add([pscustomobject]@{
                        name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name);
                        exe  = $t
                    })
                }
            } catch { }
        }
    }
}
$out | ConvertTo-Json -Compress
"""
    try:
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=30, creationflags=flags,
        )
        text = (r.stdout or "").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        noise_re = re.compile(r"\b(uninstall|deinstall|readme|license|help|удалить|справка|помощь|documentation|release\s*notes?)\b", re.I)
        by_key = {}
        for item in data:
            exe = (item.get("exe") or "").strip()
            name = (item.get("name") or "").strip()
            if not exe or not name:
                continue
            if noise_re.search(name):
                continue
            key = exe.split("\\")[-1].lower()
            if key not in by_key:
                by_key[key] = {"name": name, "exe": exe}
        return sorted(by_key.values(), key=lambda x: x["name"].lower())
    except Exception:
        return []


# ---- kill-switch через Windows Firewall ----
KS_RULE_NAME = "Kitsune-KillSwitch-BlockOut"


def firewall_block_all_outbound() -> bool:
    """Добавить правило netsh, блокирующее весь исходящий трафик. Требует админ-прав.
    Перед добавлением — превентивная чистка, чтобы не плодить дубликаты."""
    flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    firewall_unblock_all()
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={KS_RULE_NAME}", "dir=out", "action=block",
             "enable=yes", "profile=any"],
            capture_output=True, text=True, creationflags=flags, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def firewall_unblock_all() -> bool:
    """Снять наше правило kill-switch (rc=0 если что-то удалили, иначе тоже норм — нечего было)."""
    flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule",
             f"name={KS_RULE_NAME}"],
            capture_output=True, text=True, creationflags=flags, timeout=5)
        return True
    except Exception:
        return False


def is_admin() -> bool:
    """Запущены ли мы с правами администратора (нужно для TUN)."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---- Windows Task Scheduler: one-time UAC consent, then silent re-elevation ----
ELEVATE_TASK_NAME = "Kitsune\\AutoElevate"


def _schtasks(*args: str) -> int:
    """Запуск schtasks.exe без появления окна, возвращает returncode."""
    flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        return subprocess.run(["schtasks", *args], capture_output=True,
                              creationflags=flags, timeout=10).returncode
    except Exception:
        return 1


def has_elevate_task() -> bool:
    """True если задача Kitsune\\AutoElevate уже зарегистрирована."""
    return _schtasks("/query", "/tn", ELEVATE_TASK_NAME) == 0


def install_elevate_task(command: str, arguments: str = "") -> bool:
    """Создаёт скрытую on-demand задачу с RunLevel=HighestAvailable.
    Требует, чтобы текущий процесс был elevated (иначе schtasks не позволит RunLevel)."""
    # XML-описание гибче чем флаги schtasks: позволяет AllowStartOnDemand + Hidden + HighestAvailable.
    cmd_xml = command.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    arg_xml = arguments.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        '<RegistrationInfo><Description>Launch Kitsune with admin rights without UAC prompt.</Description></RegistrationInfo>'
        '<Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>'
        '<Settings>'
        '<MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>'
        '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
        '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>'
        '<AllowHardTerminate>true</AllowHardTerminate>'
        '<StartWhenAvailable>false</StartWhenAvailable>'
        '<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>'
        '<AllowStartOnDemand>true</AllowStartOnDemand>'
        '<Enabled>true</Enabled>'
        '<Hidden>true</Hidden>'
        '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>'
        '<Priority>5</Priority>'
        '</Settings>'
        '<Actions Context="Author"><Exec>'
        f'<Command>{cmd_xml}</Command>'
        f'<Arguments>{arg_xml}</Arguments>'
        '</Exec></Actions>'
        '</Task>'
    )
    try:
        fd, path = tempfile.mkstemp(suffix=".xml", prefix="kitsune_task_")
        os.close(fd)
        Path(path).write_text(xml, encoding="utf-16")
    except Exception:
        return False
    try:
        return _schtasks("/create", "/tn", ELEVATE_TASK_NAME, "/xml", path, "/f") == 0
    finally:
        try: os.unlink(path)
        except Exception: pass


def run_elevate_task() -> bool:
    """Запускает зарегистрированную задачу — Windows поднимет процесс уже elevated, без UAC."""
    return _schtasks("/run", "/tn", ELEVATE_TASK_NAME) == 0


def uninstall_elevate_task() -> bool:
    """Удаляет задачу — следующие старты пойдут через UAC как раньше."""
    return _schtasks("/delete", "/tn", ELEVATE_TASK_NAME, "/f") == 0


def port_listening(port: int = MIXED_PORT, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


# ---- Clash API (статистика трафика и URL-delay) ----
def clash_get(path: str, timeout: float = 1.0):
    """GET к Clash API ядра. None при любой ошибке."""
    url = f"http://{CLASH_HOST}:{CLASH_PORT}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def clash_traffic(timeout: float = 0.8) -> tuple[int, int] | None:
    """Накопительный трафик с момента старта ядра -> (down_bytes, up_bytes)."""
    d = clash_get("/connections", timeout)
    if not isinstance(d, dict):
        return None
    return int(d.get("downloadTotal", 0)), int(d.get("uploadTotal", 0))


def clash_delay(url: str = "http://www.gstatic.com/generate_204",
                timeout_ms: int = 5000, tag: str = PROXY_TAG) -> int | None:
    """URL-delay активного proxy-outbound (мс) через Clash API. None если таймаут/ошибка."""
    q = urllib.parse.quote(url, safe="")
    d = clash_get(f"/proxies/{tag}/delay?timeout={timeout_ms}&url={q}",
                  timeout=timeout_ms / 1000 + 1.0)
    if isinstance(d, dict) and "delay" in d:
        return int(d["delay"])
    return None


def clash_select(member_tag: str, selector_tag: str = PROXY_TAG, timeout: float = 1.5) -> bool:
    """Переключить активный outbound селектора через Clash API: PUT /proxies/<selector>.
    Используется для seamless server switch без перезапуска ядра. True если ok."""
    if not member_tag:
        return False
    url = f"http://{CLASH_HOST}:{CLASH_PORT}/proxies/{urllib.parse.quote(selector_tag, safe='')}"
    body = json.dumps({"name": member_tag}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, method="PUT",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def tcp_ping(host: str, port: int = 443, timeout: float = 2.0) -> int | None:
    """Реальный TCP-connect пинг до endpoint сервера (мс). None если недоступен."""
    if not host:
        return None
    try:
        t = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=timeout):
            return int((time.monotonic() - t) * 1000)
    except Exception:
        return None


def fetch_subscription(url: str, timeout: float = 15.0) -> tuple[str, dict] | tuple[None, dict]:
    """Загрузка тела подписки по URL. Возвращает (body, headers) — headers — это плоский dict
    с lower-case ключами (caller'у удобнее читать Profile-Update-Interval / Subscription-Userinfo).
    При ошибке: (None, {}).

    TLS без верификации (подписки часто на IP/самоподписанных сертах; содержимое — просто список
    ссылок). Используем CookieJar — многие subscription-сервисы делают cookie-based gating
    (302 + Set-Cookie на первом запросе, реальный контент только с куки)."""
    if not url:
        return None, {}
    try:
        import http.cookiejar
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=ctx),
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Kitsune/1.0"})
        with opener.open(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            headers = {k.lower(): v for k, v in (r.headers.items() or [])}
            return body, headers
    except Exception:
        return None, {}


def parse_profile_update_interval(headers: dict) -> int:
    """Surge-style header Profile-Update-Interval: <hours>. Возвращает int часов (>0) или 0."""
    try:
        v = headers.get("profile-update-interval") if headers else None
        if not v:
            return 0
        # некоторые сервера присылают "24" или "24h" или "24 hours"
        s = str(v).strip().lower().rstrip("h").split()[0]
        h = int(float(s))
        return h if h > 0 else 0
    except Exception:
        return 0


def exit_ip(port: int = MIXED_PORT, timeout: float = 6.0) -> str | None:
    """Внешний IP через mixed-прокси ядра (подтверждает, что трафик идёт в туннель)."""
    proxy = f"http://{CLASH_HOST}:{int(port)}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    for url in ("http://api.ipify.org", "http://ifconfig.me/ip"):
        try:
            with opener.open(url, timeout=timeout) as r:
                ip = r.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None


# Cloudflare Speed CDN — самый стабильный/быстрый endpoint, возвращает любой объём байт.
# Альтернатива: http://speedtest.tele2.net/5MB.zip — но Cloudflare надёжнее.
SPEEDTEST_URL = "https://speed.cloudflare.com/__down?bytes=8000000"   # 8 МБ
SPEEDTEST_MAX_SECONDS = 5.0


def speedtest_via_proxy(port: int, url: str = SPEEDTEST_URL,
                        timeout: float = 8.0) -> dict | None:
    """Измеряет throughput скачиванием url через mixed-прокси ядра.
    Останавливается через SPEEDTEST_MAX_SECONDS — на быстрых линках получим точный
    замер, на медленных — то что успело пройти за лимит.
    Возвращает {bytes, seconds, mbps} (MB/s, decimal) или None при ошибке."""
    proxy = f"http://{CLASH_HOST}:{int(port)}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Kitsune/1.0"})
        start = time.monotonic()
        with opener.open(req, timeout=timeout) as r:
            read = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                read += len(chunk)
                if time.monotonic() - start >= SPEEDTEST_MAX_SECONDS:
                    break
        elapsed = time.monotonic() - start
    except Exception:
        return None
    if elapsed <= 0 or read < 32 * 1024:    # меньше 32КБ = неактуальный замер (rate-limit / cutoff)
        return None
    mbps = (read / elapsed) / (1024 * 1024)
    return {"bytes": read, "seconds": elapsed, "mbps": round(mbps, 2)}


def lookup_ip_info(port: int | None = None, timeout: float = 6.0) -> dict | None:
    """Sanity-check: {ip, country, country_code, city, org} либо None.

    port=None → запрос напрямую, минуя туннель (увидим РЕАЛЬНЫЙ IP — для случая «VPN не работает»);
    port=N    → запрос через mixed-проксю ядра (увидим IP exit-нода).

    Используем 2 провайдера с fallback'ом — ipapi.co и ip-api.com — у обоих rate-limit
    в районе 1 запрос/сек, для on-demand кнопки достаточно."""
    if port:
        proxy = f"http://{CLASH_HOST}:{int(port)}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        opener = urllib.request.build_opener()
    for url in ("https://ipapi.co/json/", "http://ip-api.com/json/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Kitsune/1.0"})
            with opener.open(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            continue
        # унифицируем поля — у провайдеров разные имена
        ip = d.get("ip") or d.get("query") or ""
        if not ip:
            continue
        return {
            "ip":           ip,
            "country":      d.get("country_name") or d.get("country") or "",
            "country_code": (d.get("country_code") or d.get("countryCode") or "").upper(),
            "city":         d.get("city") or "",
            "org":          d.get("org") or d.get("isp") or "",
        }
    return None


class Core:
    """Жизненный цикл процесса sing-box."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._cfg_path = Path(tempfile.gettempdir()) / "kitsune_run.json"

    def start(self, server: dict | None, settings: dict | None = None,
              on_log=None) -> None:
        """Запуск ядра. `on_log(line)` — опц. callback для построчного захвата stdout/stderr.
        Колбэк вызывается из ФОНОВОГО потока — потребитель сам отвечает за thread-safety."""
        self.stop()
        cfg = gen_config(server, settings or {})
        ok, msg = check_config(cfg)
        if not ok:
            raise RuntimeError("Невалидный конфиг: " + msg)
        self._cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0  # CREATE_NO_WINDOW
        # Если есть on_log — захватываем stdout, иначе работаем как раньше (без захвата).
        if on_log is not None:
            self._proc = subprocess.Popen(
                core_cmd() + ["run", "-c", str(self._cfg_path)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=flags)
            proc = self._proc

            def pump() -> None:
                try:
                    for line in proc.stdout:                  # читаем построчно до EOF
                        try:
                            on_log(line.rstrip("\r\n"))
                        except Exception:
                            pass
                except Exception:
                    pass

            threading.Thread(target=pump, daemon=True).start()
        else:
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
