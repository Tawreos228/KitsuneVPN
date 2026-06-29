# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для Kitsune. onedir режим (не onefile) — потому что:
  1) QML/Qt-зависимости (~100 DLL) на onefile распаковываются в TEMP при каждом запуске = медленный старт
  2) Авто-обновление core/sing-box.exe пишет файл рядом с exe; на onefile он живёт во временной распаковке
     и обновление потеряется при следующем запуске.
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(".").resolve()

# Данные, которые надо положить рядом с exe
datas = [
    (str(ROOT / "qml"), "qml"),                              # все QML файлы и qmldir
    (str(ROOT / "assets"), "assets"),                         # иконки, кадры трея
    (str(ROOT / "core" / "rulesets"), "core/rulesets"),       # bundled .srs
    (str(ROOT / "core" / "sing-box.exe"), "core"),            # официальный sing-box (upstream)
    (str(ROOT / "core" / "amneziawg"), "core/amneziawg"),     # AmneziaWG tunnel daemon (amneziawg.exe + awg.exe + wintun.dll)
]

# Hidden imports — PyInstaller часто пропускает Qt-плагины и quick controls
hiddenimports = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSvg",
    "PySide6.QtNetwork",
    "segno",
]
# PyYAML: late import в engine.parse_clash_proxies. Без явного collect_submodules
# PyInstaller подтянет только _yaml.pyd (нативный) без yaml/__init__.py — import упадёт.
hiddenimports += collect_submodules("yaml")
datas += collect_data_files("yaml")

# Excludes — что точно не нужно тащить (экономия размера)
excludes = [
    "tkinter", "_tkinter",     # tk не используем
    "test", "tests", "unittest",
    "pydoc",
    "PySide6.Qt3D", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtWebEngine", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtSql", "PySide6.QtPrintSupport",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtHelp", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "PySide6.QtLocation", "PySide6.QtUiTools",
    "PySide6.QtQuick3D", "PySide6.QtQuickControls2Imagine",
    "PySide6.QtGraphs",
    "PIL",          # Pillow только для gen_icon.py (dev-инструмент)
]

# Бинарные исключения — DLL/.pyd которые точно не нужны, даже если не в excludes выше
def _excluded_binary(name):
    n = name.lower()
    for pat in (
        "qt6webengine",        # 196 MB Chromium
        "qt6pdf",
        "qt6quick3d",
        "qt6charts",
        "qt6datavisualization",
        "qt6graphs",
        "qt6bluetooth", "qt6nfc", "qt6positioning",
        "qt6sensors", "qt6serialport", "qt6serialbus",
        "qt6designer", "qt6sql", "qt6printsupport",
        "qt6remoteobjects", "qt6scxml", "qt6spatialaudio",
        "qt6statemachine", "qt6texttospeech",
        "qt6webchannel", "qt6websockets", "qt6webview",
        "qt6help", "qt6concurrent", "qt6dbus",
        "qt6location", "qt6quickcontrols2imagine",
        "qt6quickcontrols2material", "qt6quickcontrols2fusion",
        "qt6quickcontrols2universal", "qt6quickcontrols2fluentwinui3",
        "qt6quickcontrols2macos",
        "qt6multimedia",
        "opengl32sw",          # 20 MB software OpenGL fallback, под Windows у юзера всегда есть драйвер
        "qt6test",
    ):
        if pat in n:
            return True
    return False


a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Жёсткий фильтр binaries/datas от тяжёлых Qt-модулей которые мы не используем
# (Qt6WebEngineCore.dll один весит 196 MB!)
a.binaries = [b for b in a.binaries if not _excluded_binary(b[0])]
a.datas = [d for d in a.datas if not _excluded_binary(d[0])]

# Translations Qt: оставляем только ru/en, остальные ~50 локалей выкидываем
def _keep_translation(name):
    n = name.lower().replace("\\", "/")
    if "/translations/" not in n:
        return True
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    # qtbase_ru.qm, qtbase_en.qm — оставляем; qtbase_fr.qm, qtbase_de.qm и т.д. — нет
    for lang_keep in ("_ru.qm", "_en.qm"):
        if base.endswith(lang_keep):
            return True
    return False


a.binaries = [b for b in a.binaries if _keep_translation(b[0])]
a.datas = [d for d in a.datas if _keep_translation(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kitsune",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX даёт мизерную экономию + ломает антивирусы
    console=False,                   # GUI-приложение, без чёрной консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Kitsune",
)
