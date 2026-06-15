import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Effects
import App

ApplicationWindow {
    id: win
    width: 980
    height: 640
    minimumWidth: 880
    minimumHeight: 580
    visible: true
    title: "Kitsune"
    color: Theme.bg

    // активная страница: 0 Dashboard · 1 Locations · 2 Settings · 3 Account
    property int currentIndex: 0
    property bool serverMenuOpen: false
    onCurrentIndexChanged: serverMenuOpen = false

    // закрытие окна -> уходим в трей (UI выгружается), движок продолжает работать
    onClosing: function(close) {
        if (typeof appCtl === 'undefined' || !appCtl)
            return   // прототип без трея (скрипты рендера)
        close.accepted = false
        if (win.setTray) {
            win.hide()
            appCtl.hideToTray()
        } else {
            appCtl.quit()
        }
    }

    // глифы Segoe Fluent Icons (через codepoint, чтобы не зависеть от ввода символа)
    readonly property string icoDashboard: String.fromCharCode(0xE80F)
    readonly property string icoLocations: String.fromCharCode(0xE774)
    readonly property string icoSettings: String.fromCharCode(0xE713)
    readonly property string icoAccount: String.fromCharCode(0xE77B)
    readonly property string icoChevron: String.fromCharCode(0xE70D)
    readonly property string icoDown: String.fromCharCode(0xE74B)
    readonly property string icoUp: String.fromCharCode(0xE74A)
    readonly property string icoPing: String.fromCharCode(0xE93E)  // Streaming — расходящиеся волны
    readonly property string icoTheme: String.fromCharCode(0xE706)
    readonly property string icoTray: String.fromCharCode(0xE921)
    readonly property string icoAutostart: String.fromCharCode(0xE7E8)
    readonly property string icoLink: String.fromCharCode(0xE71B)
    readonly property string icoReconnect: String.fromCharCode(0xE72C)
    readonly property string icoShield: String.fromCharCode(0xEA18)
    readonly property string icoLock: String.fromCharCode(0xE72E)
    readonly property string icoRouting: String.fromCharCode(0xE816)
    readonly property string icoDns: String.fromCharCode(0xE774)
    readonly property string icoTun: String.fromCharCode(0xE968)
    readonly property string icoMux: String.fromCharCode(0xE9D9)
    readonly property string icoSniff: String.fromCharCode(0xE9A9)
    readonly property string icoPort: String.fromCharCode(0xE7F4)
    readonly property string icoClock: String.fromCharCode(0xE916)
    readonly property string icoLogs: String.fromCharCode(0xE756)        // Repair / tools-like glyph для диагностики

    // состояния настроек (мок)
    property bool setAutostart: false
    property bool setAutoconnect: true
    property bool setReconnect: true
    property bool setKill: false
    property bool setTray: true
    // Тема: разблокировка «Китсунэ» через пасхалку (5 тапов по логотипу) — навсегда.
    // themeScheme — зеркало Theme.scheme для персиста. Восстановление: см. importSettings.
    property bool   themeUnlocked: false
    property string themeScheme:   Theme.scheme
    Connections { target: Theme; function onSchemeChanged() { win.themeScheme = Theme.scheme } }
    // TUN / DNS / Mux / sniffing
    property bool setTun: false
    property int  tunStack: 0          // 0 gVisor · 1 system · 2 mixed
    property bool setStrictRoute: false   // ON форсит DNS в туннель (WFP) и ломает резолвинг на части сетей
    property bool setSniff: true
    property bool setFakeIp: true
    property bool setMux: false
    property int  muxProto: 0          // 0 smux · 1 yamux · 2 h2mux
    property bool setLan: false
    // маршрутизация (мок)
    property int  rtProfile: 0         // 0 Авто · 1 Global · 2 RU
    property bool rtLan: true
    property bool rtRegionDirect: true
    property bool rtAdblock: false
    property bool rtProxyAll: false
    property int  rtFinal: 0           // 0 Прокси · 1 Прямо · 2 Блок
    property var  routeRules: [
        { type: "domain", value: "*.youtube.com", action: "proxy" },
        { type: "geoip",  value: "RU",            action: "direct" },
        { type: "domain", value: "*.doubleclick.net", action: "block" },
        { type: "process", value: "telegram.exe", action: "proxy" }
    ]

    // Профили маршрутизации — именованные пресеты {rt*, routeRules}. Переключаются одним кликом,
    // активный профиль авто-сохраняет правки. Дефолтный «Стандартный» не удаляется.
    property var routingProfiles: [
        { id: "default", name: T.s("misc.standard"),
          rtProfile: 0, rtLan: true, rtRegionDirect: true, rtAdblock: false, rtProxyAll: false, rtFinal: 0,
          routeRules: [
              { type: "domain", value: "*.youtube.com", action: "proxy" },
              { type: "geoip",  value: "RU",            action: "direct" },
              { type: "domain", value: "*.doubleclick.net", action: "block" },
              { type: "process", value: "telegram.exe", action: "proxy" }
          ]
        }
    ]
    property string currentProfileId: "default"
    property bool _profileLoading: false     // подавляет авто-сейв во время applyProfile

    function _findProfile(id) {
        for (var i = 0; i < routingProfiles.length; i++)
            if (routingProfiles[i].id === id) return routingProfiles[i]
        return null
    }
    function applyProfile(id) {
        var p = _findProfile(id)
        if (!p) return
        _profileLoading = true
        currentProfileId = id
        rtProfile       = p.rtProfile
        rtLan           = p.rtLan
        rtRegionDirect  = p.rtRegionDirect
        rtAdblock       = p.rtAdblock
        rtProxyAll      = p.rtProxyAll
        rtFinal         = p.rtFinal
        routeRules      = (p.routeRules || []).slice()
        _profileLoading = false
    }
    function saveActiveProfile() {
        if (_profileLoading) return
        var arr = routingProfiles.slice()
        var idx = -1
        for (var i = 0; i < arr.length; i++)
            if (arr[i].id === currentProfileId) { idx = i; break }
        if (idx < 0) return
        arr[idx] = {
            id: arr[idx].id, name: arr[idx].name,
            rtProfile: rtProfile, rtLan: rtLan, rtRegionDirect: rtRegionDirect,
            rtAdblock: rtAdblock, rtProxyAll: rtProxyAll, rtFinal: rtFinal,
            routeRules: routeRules.slice()
        }
        routingProfiles = arr
    }
    function createProfile(name) {
        var nm = (name || "").trim()
        if (!nm) return
        var newId = "p" + Date.now()
        var arr = routingProfiles.slice()
        arr.push({
            id: newId, name: nm,
            rtProfile: rtProfile, rtLan: rtLan, rtRegionDirect: rtRegionDirect,
            rtAdblock: rtAdblock, rtProxyAll: rtProxyAll, rtFinal: rtFinal,
            routeRules: routeRules.slice()
        })
        routingProfiles = arr
        applyProfile(newId)
    }
    function deleteProfile(id) {
        if (id === "default") return       // дефолтный не удаляем
        var arr = routingProfiles.filter(function(p) { return p.id !== id })
        routingProfiles = arr
        if (currentProfileId === id) applyProfile("default")
    }
    function renameProfile(id, newName) {
        var nm = (newName || "").trim()
        if (!nm) return
        var arr = routingProfiles.slice()
        for (var i = 0; i < arr.length; i++) {
            if (arr[i].id === id) {
                arr[i] = Object.assign({}, arr[i], { name: nm })
                break
            }
        }
        routingProfiles = arr
    }

    // ключ: меняется при любой правке настроек профиля — триггерит автосейв в активный
    property string _profileKey: "" + rtProfile + rtLan + rtRegionDirect + rtAdblock + rtProxyAll + rtFinal + JSON.stringify(routeRules)
    on_ProfileKeyChanged: saveActiveProfile()

    // редактируемые значения (мок)
    property string portMixed: "2080"
    property string mtu: "9000"
    property string dnsRemote: "https://1.1.1.1/dns-query"
    property string dnsDirect: "223.5.5.5"

    // авто-подстройка настроек под подписку (полностью заработает с подписками)
    property bool setAutoConf: true
    // фоновое обновление подписок (как часто Kitsune сам тянет свежие сервера)
    property bool setSubAutoRefresh: true
    property int  subRefreshInterval: 12     // часов · допустимо 3/6/12/24

    // редактор правила
    property bool ruleEditorOpen: false
    property string draftType: "domain"
    property string draftValue: ""
    property int draftAction: 0          // 0 proxy · 1 direct · 2 block
    readonly property var ruleTypes: ["domain", "geosite", "geoip", "ip", "process", "port"]
    function openRuleEditor() {
        draftType = "domain"; draftValue = ""; draftAction = 0
        ruleEditorOpen = true
    }
    function addDraftRule() {
        if (draftValue.length === 0) return
        var act = draftAction === 0 ? "proxy" : draftAction === 1 ? "direct" : "block"
        routeRules = routeRules.concat([{ type: draftType, value: draftValue, action: act }])
        ruleEditorOpen = false
    }
    function moveRule(from, to) {
        if (from === to) return
        var arr = routeRules.slice()
        var item = arr.splice(from, 1)[0]
        arr.splice(to, 0, item)
        routeRules = arr
    }

    // per-app маршрутизация на странице Routing → раздел «Приложения».
    // 3 состояния: "auto" (нет правила, юзается дефолт режима) | "proxy" (в туннель) | "direct" (мимо туннеля).
    // direct особенно полезен в TUN-режиме (исключения: банковские клиенты, Steam, корп.VPN и т.п.).
    property string appFilter: ""
    function appRouteState(exe) {
        for (var i = 0; i < routeRules.length; i++) {
            var r = routeRules[i]
            if (r.type === "process" && r.value === exe && (r.action === "proxy" || r.action === "direct"))
                return r.action
        }
        return "auto"
    }
    function setAppRouteState(exe, state) {
        // убираем существующее process-правило для exe (если есть), затем добавляем новое если state != "auto"
        var arr = routeRules.filter(function(r) {
            return !(r.type === "process" && r.value === exe)
        })
        if (state === "proxy" || state === "direct")
            arr.push({ type: "process", value: exe, action: state })
        routeRules = arr
    }
    function resetAppRules() {
        // снять все per-app правила одним кликом
        routeRules = routeRules.filter(function(r) { return r.type !== "process" })
    }
    function appsFiltered() {
        var q = (appFilter || "").trim().toLowerCase()
        var src = backend.appList || []
        if (!q) return src
        return src.filter(function(a) {
            return (a.name || "").toLowerCase().indexOf(q) >= 0
                || (a.exeName || "").toLowerCase().indexOf(q) >= 0
        })
    }

    // добавление подписки
    property bool addSubOpen: false
    property bool logsOpen: false                // панель логов ядра (скрыта по умолчанию)
    property bool importRulesOpen: false         // модалка импорта правил из чужих клиентов
    property string importDraft: ""              // черновик вставленного JSON/YAML
    property bool newProfileOpen: false          // модалка создания нового профиля маршрутизации
    property string newProfileName: ""
    property string draftSubName: ""
    property string draftSubUrl: ""
    property bool draftSubAuto: true
    function openAddSub() { draftSubName = ""; draftSubUrl = ""; draftSubAuto = true; addSubOpen = true }
    function addSub() {
        if (draftSubUrl.length === 0) return
        backend.addSubscription(draftSubName, draftSubUrl, draftSubAuto)
        addSubOpen = false
    }

    // авто-подстройка под подписку
    property string managedSub: ""    // имя подписки, управляющей настройками ("" — нет)
    function applySubscriptionConfig() {
        var g = backend.groups[backend.currentGroup]
        if (setAutoConf && g && g.type === "subscription" && g.config) {
            if (g.config.dns) dnsRemote = g.config.dns
            rtAdblock = g.config.adblock
            rtFinal = g.config.final
            managedSub = g.name
        } else {
            managedSub = ""
        }
    }
    onSetAutoConfChanged: applySubscriptionConfig()

    // снимок настроек — чтобы переживали выгрузку UI в трее (держит AppController)
    property string settingsSnapshot: "{}"
    function exportSettings() {
        settingsSnapshot = JSON.stringify({
            setAutostart: setAutostart, setReconnect: setReconnect, setKill: setKill,
            setTray: setTray, setLan: setLan, setStrictRoute: setStrictRoute,
            setSniff: setSniff, setFakeIp: setFakeIp, setMux: setMux, tunStack: tunStack,
            muxProto: muxProto, setAutoConf: setAutoConf,
            setSubAutoRefresh: setSubAutoRefresh, subRefreshInterval: subRefreshInterval,
            rtProfile: rtProfile, rtLan: rtLan, rtRegionDirect: rtRegionDirect,
            rtAdblock: rtAdblock, rtProxyAll: rtProxyAll, rtFinal: rtFinal, routeRules: routeRules,
            portMixed: portMixed, mtu: mtu, dnsRemote: dnsRemote, dnsDirect: dnsDirect,
            lang: T.lang,
            themeScheme: themeScheme, themeUnlocked: themeUnlocked,
            routingProfiles: routingProfiles, currentProfileId: currentProfileId,
            customApps: (typeof backend !== "undefined" && backend) ? JSON.parse(backend.customAppsJson || "[]") : []
        })
    }
    function importSettings() {
        var s = JSON.parse(settingsSnapshot || "{}")
        if (!s) return
        if (s.setAutostart !== undefined) setAutostart = s.setAutostart
        if (s.setReconnect !== undefined) setReconnect = s.setReconnect
        if (s.setKill !== undefined) setKill = s.setKill
        if (s.setTray !== undefined) setTray = s.setTray
        if (s.setLan !== undefined) setLan = s.setLan
        if (s.setStrictRoute !== undefined) setStrictRoute = s.setStrictRoute
        if (s.setSniff !== undefined) setSniff = s.setSniff
        if (s.setFakeIp !== undefined) setFakeIp = s.setFakeIp
        if (s.setMux !== undefined) setMux = s.setMux
        if (s.tunStack !== undefined) tunStack = s.tunStack
        if (s.muxProto !== undefined) muxProto = s.muxProto
        if (s.setAutoConf !== undefined) setAutoConf = s.setAutoConf
        if (s.setSubAutoRefresh !== undefined) setSubAutoRefresh = !!s.setSubAutoRefresh
        if (s.subRefreshInterval !== undefined) subRefreshInterval = parseInt(s.subRefreshInterval) || 12
        if (s.rtProfile !== undefined) rtProfile = s.rtProfile
        if (s.rtLan !== undefined) rtLan = s.rtLan
        if (s.rtRegionDirect !== undefined) rtRegionDirect = s.rtRegionDirect
        if (s.rtAdblock !== undefined) rtAdblock = s.rtAdblock
        if (s.rtProxyAll !== undefined) rtProxyAll = s.rtProxyAll
        if (s.rtFinal !== undefined) rtFinal = s.rtFinal
        if (s.routeRules !== undefined) routeRules = s.routeRules
        if (s.portMixed !== undefined) portMixed = s.portMixed
        if (s.mtu !== undefined) mtu = s.mtu
        if (s.dnsRemote !== undefined) dnsRemote = s.dnsRemote
        if (s.dnsDirect !== undefined) dnsDirect = s.dnsDirect
        if (s.lang !== undefined && (s.lang === "ru" || s.lang === "en")) T.lang = s.lang
        // тема: восстанавливаем разблокировку и активную схему
        if (s.themeUnlocked !== undefined) themeUnlocked = !!s.themeUnlocked
        if (s.themeScheme !== undefined && (s.themeScheme === "light" || s.themeScheme === "dark" || s.themeScheme === "kitsune")) {
            Theme.scheme = (s.themeScheme === "kitsune" && !themeUnlocked) ? "dark" : s.themeScheme
        }
        // профили: восстанавливаем список и активный профиль (applyProfile перетрёт rt* и routeRules)
        if (s.routingProfiles !== undefined && Array.isArray(s.routingProfiles) && s.routingProfiles.length > 0)
            routingProfiles = s.routingProfiles
        if (s.currentProfileId !== undefined && _findProfile(s.currentProfileId))
            applyProfile(s.currentProfileId)
        // пользовательские приложения (вручную добавленные через файл-пикер) — отдают обратно в Backend
        if (s.customApps !== undefined && Array.isArray(s.customApps) && backend)
            backend.setCustomAppsJson(JSON.stringify(s.customApps))
        applySubscriptionConfig()
    }

    // реактивный пуш настроек маршрутизации/DNS/mux в движок (backend.applyConfig)
    function syncConfig() {
        exportSettings()
        if (typeof backend !== "undefined" && backend) backend.applyConfig(settingsSnapshot)
    }
    property string _cfgKey: "" + portMixed + setSniff + setMux + muxProto + setFakeIp
        + dnsRemote + dnsDirect + rtLan + rtRegionDirect + rtAdblock + rtProxyAll
        + rtFinal + JSON.stringify(routeRules) + tunStack + setStrictRoute + mtu + setLan
    on_CfgKeyChanged: syncConfig()
    Component.onCompleted: {
        syncConfig()
        if (backend) {
            backend.checkCoreUpdate()
            backend.checkAppUpdate()
            backend.scanApps()
            setAutostart = backend.isAutostartEnabled()   // синк UI-тумблера с реальным состоянием реестра
            backend.setReconnectEnabled(setReconnect)     // прокинуть начальное значение watchdog'а
            backend.setKillSwitchEnabled(setKill)         // прокинуть начальное значение kill-switch
            backend.setSubRefreshInterval(subRefreshInterval)   // порядок важен: сначала интервал
            backend.setSubAutoRefresh(setSubAutoRefresh)        // потом включение — стартанёт timer/QTimer.singleShot уже в startup()
            backend.setLang(T.lang)                       // i18n: язык Backend-notify
        }
    }

    // i18n: при смене языка в UI синкаем в Backend (для notify-сообщений)
    Connections {
        target: T
        function onLangChanged() { if (backend) backend.setLang(T.lang) }
    }

    // редактор профиля сервера
    property bool serverEditorOpen: false
    property int epIndex: -1               // -1 — новый сервер
    property string epName: ""
    property string epProtocol: "vless"
    property string epAddress: ""
    property string epPort: "443"
    property string epUuid: ""
    property string epPassword: ""
    property string epMethod: "aes-256-gcm"
    property bool epTls: true
    property string epSni: ""
    property bool epReality: false
    property string epPbk: ""
    property string epSid: ""
    property string epTransport: "tcp"
    property string epPath: ""
    property string epHost: ""
    property string epServiceName: ""
    property string epWgKey: ""
    property string epFlow: ""
    // WireGuard-only:
    property string epPeerKey: ""
    property string epLocalAddr: "172.16.0.2/32"
    property string epAllowedIps: "0.0.0.0/0"
    property string epWgMtu: "1420"
    property string epPsk: ""
    readonly property var protoList: ["vless", "vmess", "trojan", "shadowsocks", "wireguard"]
    readonly property var ssMethods: ["aes-256-gcm", "chacha20-ietf-poly1305", "2022-blake3-aes-256-gcm"]
    readonly property var transports: ["tcp", "ws", "grpc", "xhttp"]

    function openServerEditor(index) {
        epIndex = index
        if (index < 0) {
            epName = ""; epProtocol = "vless"; epAddress = ""; epPort = "443"
            epUuid = ""; epPassword = ""; epMethod = "aes-256-gcm"
            epTls = true; epSni = ""; epReality = false; epPbk = ""; epSid = ""
            epTransport = "tcp"; epPath = ""; epHost = ""; epServiceName = ""
            epWgKey = ""; epFlow = ""
            epPeerKey = ""; epLocalAddr = "172.16.0.2/32"; epAllowedIps = "0.0.0.0/0"; epWgMtu = "1420"; epPsk = ""
        } else {
            var s = backend.servers[index] || ({})
            epName = s.name || s.country || ""
            epProtocol = s.protocol || "vless"
            epAddress = s.address || ""
            epPort = s.port ? String(s.port) : "443"
            epUuid = s.uuid || ""
            epPassword = s.password || ""
            epMethod = s.method || "aes-256-gcm"
            epTls = (s.tls !== undefined ? s.tls : true)
            epSni = s.sni || ""
            epReality = s.reality || false
            epPbk = s.pbk || ""
            epSid = s.sid || ""
            epTransport = s.transport || "tcp"
            epPath = s.path || ""
            epHost = s.host || ""
            epServiceName = s.serviceName || ""
            epWgKey = s.wgKey || ""
            epFlow = s.flow || ""
            epPeerKey = s.peerKey || ""
            epLocalAddr = s.localAddr || "172.16.0.2/32"
            epAllowedIps = s.allowedIps || "0.0.0.0/0"
            epWgMtu = (s.mtu !== undefined && s.mtu !== "") ? String(s.mtu) : "1420"
            epPsk = s.psk || ""
        }
        serverEditorOpen = true
    }
    function saveServer() {
        if (epAddress.length === 0) return
        var d = {
            name: epName, protocol: epProtocol, address: epAddress, port: epPort,
            uuid: epUuid, password: epPassword, method: epMethod, tls: epTls,
            sni: epSni, reality: epReality, pbk: epPbk, sid: epSid,
            transport: epTransport, path: epPath, host: epHost,
            serviceName: epServiceName, wgKey: epWgKey, flow: epFlow,
            peerKey: epPeerKey, localAddr: epLocalAddr, allowedIps: epAllowedIps,
            mtu: epWgMtu, psk: epPsk
        }
        if (epIndex < 0) backend.addServer(d)
        else backend.updateServer(epIndex, d)
        serverEditorOpen = false
    }

    // поделиться сервером (ссылка + QR)
    property bool shareOpen: false
    property string shareLink: ""
    property string shareQr: ""
    function openShare(index) {
        if (index < 0) return
        shareLink = backend.serverLink(index)
        shareQr = backend.serverQr(index)
        shareOpen = true
    }

    // подтверждение удаления
    property bool confirmOpen: false
    property string confirmText: ""
    property var confirmAction: null
    function askConfirm(text, action) { confirmText = text; confirmAction = action; confirmOpen = true }
    function doConfirm() { if (confirmAction) confirmAction(); confirmAction = null; confirmOpen = false }

    // контекстное меню сервера
    property bool ctxOpen: false
    property int ctxIndex: -1
    property real ctxX: 0
    property real ctxY: 0
    function openServerCtx(index, x, y) { ctxIndex = index; ctxX = x; ctxY = y; ctxOpen = true }
    function ctxName() { var s = backend.servers[ctxIndex]; return s ? (s.country + " · " + s.city) : "" }

    readonly property var navModel: [
        { icon: icoDashboard, key: "nav.dashboard" },
        { icon: icoLocations, key: "nav.locations" },
        { icon: icoRouting,   key: "nav.routing" },
        { icon: icoSettings,  key: "nav.settings" }
    ]
    function pingFor(name) {
        var s = backend.servers
        for (var i = 0; i < s.length; i++)
            if (s[i].country + " · " + s[i].city === name) return s[i].ping
        return 0
    }
    function codeFor(name) {
        var s = backend.servers
        for (var i = 0; i < s.length; i++)
            if (s[i].country + " · " + s[i].city === name) return s[i].code
        return "··"
    }
    function fmtTraffic(mb) {
        return mb >= 1024 ? (mb / 1024).toFixed(2) + T.s("units.gb") : mb.toFixed(1) + T.s("units.mb")
    }
    function fmtTime(s) {
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
        var p = function (n) { return (n < 10 ? "0" : "") + n }
        return h > 0 ? (h + ":" + p(m) + ":" + p(sec)) : (p(m) + ":" + p(sec))
    }

    // секретный жест: 5 тапов по логотипу -> разблокировка темы «Китсунэ».
    // Первая активация — разблокировка (themeUnlocked = true, навсегда) + переход на лису.
    // Последующие — обычное переключение, лиса уже постоянно живёт в ThemeToggle.
    property int logoTaps: 0
    function onLogoTap() {
        logoTaps++
        logoTapTimer.restart()
        if (logoTaps >= 5) {
            logoTaps = 0
            if (!themeUnlocked) {
                themeUnlocked = true
                Theme.scheme = "kitsune"
                toast.show(T.s("misc.bigfox"), "info")
            } else {
                Theme.scheme = (Theme.scheme === "kitsune" ? "dark" : "kitsune")
                toast.show(Theme.scheme === "kitsune" ? T.s("misc.bigfox") : T.s("misc.normalth"), "info")
            }
        }
    }

    // заглушка для разделов в разработке (объявлена до использования)
    component Placeholder: ColumnLayout {
        property bool active: false
        property string glyph: ""
        property string caption: ""
        anchors.fill: parent
        opacity: active ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
        Item { Layout.fillHeight: true }
        Text { Layout.alignment: Qt.AlignHCenter; text: glyph; font.family: Theme.iconFamily; font.pixelSize: 44; color: Theme.textMuted }
        Text { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 12; text: caption; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 18; font.weight: Font.Medium }
        Text { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 2; text: T.s("misc.soon"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13 }
        Item { Layout.fillHeight: true }
    }

    // метка поля формы (мелкий капс)
    component FLabel: Text {
        color: Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: 10
        font.weight: Font.DemiBold
        font.letterSpacing: 1
        Layout.topMargin: 2
    }

    // пункт контекстного меню
    component CtxItem: Rectangle {
        id: ci
        property string glyph: ""
        property string label: ""
        property bool danger: false
        signal clicked()
        Layout.fillWidth: true
        implicitHeight: 38
        radius: 8
        color: ciHover.hovered ? Theme.hover : "transparent"
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10
            Text { text: ci.glyph; font.family: Theme.iconFamily; font.pixelSize: 14; color: ci.danger ? Theme.red : Theme.textSub; Layout.alignment: Qt.AlignVCenter }
            Text { text: ci.label; color: ci.danger ? Theme.red : Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter }
        }
        HoverHandler { id: ciHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: ci.clicked() }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ============================ SIDEBAR ============================
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 224
            color: Theme.sidebar

            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.stroke }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 4

                // шапка
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    Layout.bottomMargin: 18
                    spacing: 10
                    Image {
                        width: 32; height: 32
                        sourceSize.width: 64; sourceSize.height: 64
                        source: Qt.resolvedUrl("../../assets/icon.png")
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        TapHandler { onTapped: win.onLogoTap() }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }
                    Text { text: "Kitsune"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                }

                // навигация с плавно скользящим выделением
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: navColumn.implicitHeight

                    Rectangle {
                        id: highlight
                        width: parent.width
                        height: 44
                        radius: 11
                        color: Theme.accentSoft
                        y: win.currentIndex * 48
                        Behavior on y { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                    }

                    Column {
                        id: navColumn
                        width: parent.width
                        spacing: 4
                        Repeater {
                            model: win.navModel
                            delegate: Item {
                                id: navItem
                                required property int index
                                required property var modelData
                                width: navColumn.width
                                height: 44
                                readonly property bool active: win.currentIndex === index

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 14
                                    spacing: 13
                                    Text {
                                        text: navItem.modelData.icon
                                        font.family: Theme.iconFamily
                                        font.pixelSize: 17
                                        color: navItem.active ? Theme.accent : Theme.textSub
                                        Behavior on color { ColorAnimation { duration: Theme.durBase } }
                                    }
                                    Text {
                                        text: T.s(navItem.modelData.key)
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 14
                                        font.weight: navItem.active ? Font.DemiBold : Font.Normal
                                        color: navItem.active ? Theme.accent : Theme.text
                                        Behavior on color { ColorAnimation { duration: Theme.durBase } }
                                    }
                                    Item { Layout.fillWidth: true }
                                    // Индикатор обновлений (видна только на Settings).
                                    // Сама точка + пульсирующее «эхо» вокруг неё — мягко зовёт юзера зайти.
                                    Item {
                                        id: updDot
                                        readonly property bool hasUpdate: navItem.modelData.key === "nav.settings"
                                            && (backend.coreUpdateAvailable || backend.appUpdateAvailable)
                                        width: 14; height: 14
                                        Layout.alignment: Qt.AlignVCenter
                                        Layout.rightMargin: 2
                                        opacity: hasUpdate ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                                        // расходящаяся волна
                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 7 * pulse; height: 7 * pulse; radius: width / 2
                                            color: "transparent"
                                            border.color: Theme.accent
                                            border.width: 1
                                            opacity: Math.max(0, 1.4 - pulse * 0.7)
                                            property real pulse: 1
                                            SequentialAnimation on pulse {
                                                running: updDot.hasUpdate
                                                loops: Animation.Infinite
                                                NumberAnimation { from: 1; to: 2.4; duration: 1300; easing.type: Easing.OutQuad }
                                                PauseAnimation { duration: 200 }
                                            }
                                        }
                                        // ядро-точка
                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 7; height: 7; radius: 3.5
                                            color: Theme.accent
                                        }
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: win.currentIndex = navItem.index
                                }
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // статус-строка внизу
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 10
                    spacing: 9
                    Rectangle {
                        width: 9; height: 9; radius: 4.5
                        color: backend.status === "connected" ? Theme.green
                             : backend.status === "connecting" ? Theme.amber : Theme.textMuted
                        Behavior on color { ColorAnimation { duration: Theme.durBase } }
                    }
                    Text {
                        text: backend.status === "connected" ? T.s("statusbar.active")
                            : backend.status === "connecting" ? T.s("statusbar.connecting")
                            : T.s("statusbar.offline")
                        color: Theme.textSub
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
            }
        }

        // ============================ CONTENT ============================
        Item {
            id: content
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            // --- страница: Dashboard ---
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.pad
                spacing: 0
                opacity: win.currentIndex === 0 ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }

                // верхняя панель: режим (слева) + выбор сервера и пинг (справа)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    ModeSwitch {}

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        id: pill
                        width: 300; height: 44
                        radius: 12
                        color: pillHover.hovered ? Theme.surfaceAlt : Theme.surface
                        border.width: 1
                        border.color: win.serverMenuOpen ? Qt.rgba(0.04, 0.52, 1.0, 0.55) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Behavior on border.color { ColorAnimation { duration: Theme.durBase } }
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            shadowEnabled: true
                            shadowColor: Theme.shadow
                            shadowBlur: 0.7
                            shadowVerticalOffset: 4
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 13
                            spacing: 11
                            Rectangle {
                                width: 28; height: 20; radius: 5
                                gradient: Gradient {
                                    GradientStop { position: 0.0; color: Qt.lighter(Theme.accent, 1.25) }
                                    GradientStop { position: 1.0; color: Theme.accent }
                                }
                                Text {
                                    anchors.centerIn: parent
                                    text: win.codeFor(backend.server)
                                    color: "white"; font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: backend.server
                                color: Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: 13
                                font.weight: Font.Medium
                                elide: Text.ElideRight
                            }
                            Text {
                                text: (backend.status === "connected" ? backend.ping : win.pingFor(backend.server)) + " ms"
                                color: Theme.textMuted
                                font.family: Theme.fontFamily
                                font.pixelSize: 12
                            }
                            Text {
                                text: win.icoChevron
                                font.family: Theme.iconFamily
                                font.pixelSize: 12
                                color: Theme.textMuted
                                rotation: win.serverMenuOpen ? 180 : 0
                                Behavior on rotation { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                            }
                        }
                        HoverHandler { id: pillHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: win.serverMenuOpen = !win.serverMenuOpen }
                    }

                    IconButton {
                        glyph: win.icoPing
                        spinning: backend.pinging
                        diameter: 44
                        onClicked: backend.pingAll()
                    }
                }

                Item { Layout.fillHeight: true; Layout.preferredHeight: 1 }

                ConnectButton { Layout.alignment: Qt.AlignHCenter }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 18
                    text: "Kitsune VPN"
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
                }
                Text {
                    id: ipLine
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 4
                    text: backend.status === "connected" ? T.s("loc.myip") + backend.exitIp : T.s("loc.unsecured")
                    color: backend.status === "connected" && ipMouse.containsMouse ? Theme.text : Theme.textSub
                    font.family: Theme.fontFamily
                    font.pixelSize: 13
                    font.underline: backend.status === "connected" && ipMouse.containsMouse
                    Behavior on color { ColorAnimation { duration: Theme.durFast } }
                    MouseArea {
                        id: ipMouse
                        anchors.fill: parent
                        enabled: backend.status === "connected"
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: backend.copyToClipboard(backend.exitIp)
                    }
                }

                // ── sanity-check «реально под VPN?» ─────────────────────────────────
                // Один компактный блок ниже Мой IP: до клика — серая ссылка-кнопка,
                // во время запроса — крутящийся индикатор, после — цветной итог + детали.
                Item {
                    id: verifyBlock
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 6
                    implicitWidth: verifyRow.implicitWidth + 24
                    implicitHeight: 28

                    readonly property color outColor:
                        backend.verifyStatus === "match"    ? Theme.green
                      : backend.verifyStatus === "mismatch" ? Theme.amber
                      : backend.verifyStatus === "off"      ? Theme.red
                      : backend.verifyStatus === "error"    ? Theme.red
                      :                                       Theme.textSub

                    readonly property string statusLabel:
                        backend.verifyStatus === "checking" ? T.s("vrf.checking")
                      : backend.verifyStatus === "match"    ? T.s("vrf.match")
                      : backend.verifyStatus === "mismatch" ? T.s("vrf.mismatch")
                      : backend.verifyStatus === "off"      ? T.s("vrf.off")
                      : backend.verifyStatus === "error"    ? T.s("vrf.error")
                      :                                       T.s("vrf.idle")

                    Rectangle {
                        anchors.fill: parent
                        radius: 14
                        color: backend.verifyStatus === "idle"
                            ? (verifyHover.hovered ? Theme.surfaceAlt : "transparent")
                            : Qt.rgba(verifyBlock.outColor.r, verifyBlock.outColor.g, verifyBlock.outColor.b, 0.12)
                        border.width: backend.verifyStatus === "idle" ? 0 : 1
                        border.color: verifyBlock.outColor
                        Behavior on color { ColorAnimation { duration: Theme.durBase } }
                    }

                    RowLayout {
                        id: verifyRow
                        anchors.centerIn: parent
                        spacing: 6

                        // dot / spinner
                        Item {
                            implicitWidth: 10; implicitHeight: 10
                            Rectangle {
                                anchors.centerIn: parent
                                width: 8; height: 8; radius: 4
                                color: verifyBlock.outColor
                                visible: backend.verifyStatus !== "checking"
                            }
                            // мини-спиннер для checking
                            Rectangle {
                                anchors.centerIn: parent
                                width: 10; height: 10; radius: 5
                                color: "transparent"
                                border.color: Theme.textSub; border.width: 1.5
                                visible: backend.verifyStatus === "checking"
                                Rectangle {
                                    width: 4; height: 1.5
                                    color: Theme.accent
                                    x: 5; y: 4
                                }
                                RotationAnimation on rotation {
                                    running: backend.verifyStatus === "checking"
                                    from: 0; to: 360
                                    duration: 900; loops: Animation.Infinite
                                }
                            }
                        }

                        Text {
                            text: verifyBlock.statusLabel
                            color: backend.verifyStatus === "idle" ? Theme.textSub : verifyBlock.outColor
                            font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold
                        }
                        // детали справа от ярлыка — после успешного запроса
                        Text {
                            visible: backend.verifyStatus !== "idle" && backend.verifyStatus !== "checking" && backend.verifyIp
                            text: " · " + backend.verifyCountry +
                                  (backend.verifyCity ? ", " + backend.verifyCity : "") +
                                  (backend.verifyOrg ? " · " + backend.verifyOrg : "")
                            color: Theme.textSub
                            font.family: Theme.fontFamily; font.pixelSize: 12
                        }
                    }

                    HoverHandler { id: verifyHover; enabled: backend.verifyStatus !== "checking"; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: backend.verifyStatus !== "checking"; onTapped: backend.verifyVpn() }
                }

                // график активности
                Waveform {
                    Layout.fillWidth: true
                    Layout.topMargin: 26
                    Layout.leftMargin: 30
                    Layout.rightMargin: 30
                }

                // скорости
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 6
                    spacing: 44
                    Row {
                        spacing: 7
                        visible: backend.status === "connected"
                        Text { text: win.icoClock; font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.textMuted; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: win.fmtTime(backend.elapsed); color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                    }
                    Row {
                        spacing: 7
                        Text { text: win.icoDown; font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.textMuted; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: backend.status === "connected" ? win.fmtTraffic(backend.down) : "—"
                            color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.Medium
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Row {
                        spacing: 7
                        Text { text: win.icoUp; font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.textMuted; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: backend.status === "connected" ? win.fmtTraffic(backend.up) : "—"
                            color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 15; font.weight: Font.Medium
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }

                Item { Layout.fillHeight: true; Layout.preferredHeight: 1 }

                // прототип: показать всплывающую ошибку
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: T.s("misc.demoerr")
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                    font.underline: errMouse.containsMouse
                    MouseArea { id: errMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.simulateError() }
                }
            }

            // --- страница: Locations ---
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.pad
                spacing: 14
                opacity: win.currentIndex === 1 ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }

                id: locPage
                readonly property var curGroup: backend.groups[backend.currentGroup]
                property string searchText: ""
                property int sortMode: 0      // 0 — как есть · 1 — по пингу
                property bool favOnly: false
                readonly property var filtered: {
                    var src = backend.servers
                    var q = (searchText || "").toLowerCase()
                    var out = []
                    for (var i = 0; i < src.length; i++) {
                        var s = src[i]
                        if (favOnly && s.fav !== true) continue
                        if (q.length === 0 || (s.country + " " + s.city + " " + s.code).toLowerCase().indexOf(q) !== -1)
                            out.push({ code: s.code, country: s.country, city: s.city, ping: s.ping, fav: s.fav === true, speedMbps: s.speedMbps || 0, _idx: i })
                    }
                    if (sortMode === 1)
                        out.sort(function(a, b) { return a.ping - b.ping })
                    return out
                }

                // заголовок + добавить подписку
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: T.s("page.locations"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        width: pasteRow.implicitWidth + 26; height: 34; radius: 17
                        color: pasteHover.hovered ? Theme.hover : "transparent"
                        border.width: 1; border.color: Theme.stroke
                        Row {
                            id: pasteRow; anchors.centerIn: parent; spacing: 6
                            Text { text: String.fromCharCode(0xE77F); font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: T.s("btn.paste"); color: Theme.text; font.pixelSize: 13; font.weight: Font.Medium; font.family: Theme.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                        }
                        HoverHandler { id: pasteHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.importFromClipboard() }
                    }
                    Item { width: 8 }
                    Rectangle {
                        width: addSubRow.implicitWidth + 26; height: 34; radius: 17
                        color: addSubHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Row {
                            id: addSubRow; anchors.centerIn: parent; spacing: 6
                            Text { text: "+"; color: "white"; font.pixelSize: 17; font.weight: Font.Bold; font.family: Theme.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: T.s("btn.subscription"); color: "white"; font.pixelSize: 13; font.weight: Font.DemiBold; font.family: Theme.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                        }
                        HoverHandler { id: addSubHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: win.openAddSub() }
                    }
                }

                // вкладки групп / подписок
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: backend.groups
                        delegate: Rectangle {
                            id: gchip
                            required property int index
                            required property var modelData
                            readonly property bool active: backend.currentGroup === index
                            height: 34; radius: 17
                            width: gchipRow.implicitWidth + 24
                            color: gchip.active ? Theme.accent : Theme.surface
                            border.width: 1; border.color: gchip.active ? Theme.accent : Theme.stroke
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Row {
                                id: gchipRow; anchors.centerIn: parent; spacing: 8
                                Text { text: gchip.modelData.name; color: gchip.active ? "white" : Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: cnt.width + 12; height: 18; radius: 9
                                    color: gchip.active ? Qt.rgba(1, 1, 1, 0.25) : Theme.surfaceAlt
                                    Text { id: cnt; anchors.centerIn: parent; text: gchip.modelData.servers.length; color: gchip.active ? "white" : Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold }
                                }
                            }
                            TapHandler { onTapped: backend.setCurrentGroup(gchip.index) }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                        }
                    }
                }

                // инфо о подписке
                Rectangle {
                    id: subInfo
                    Layout.fillWidth: true
                    readonly property var g: backend.groups[backend.currentGroup] || ({})
                    visible: subInfo.g.type === "subscription"
                    radius: Theme.radius
                    color: Theme.surface
                    border.width: 1; border.color: Theme.stroke
                    implicitHeight: 58
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 12; spacing: 10
                        Text { text: win.icoLink; font.family: Theme.iconFamily; font.pixelSize: 16; color: Theme.textSub; Layout.alignment: Qt.AlignVCenter }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter; spacing: 1
                            Text { text: subInfo.g.url || ""; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            Text { text: T.s("loc.updated") + (subInfo.g.updated || "—"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11 }
                        }
                        // если сервер прислал свой Profile-Update-Interval — показываем badge и
                        // прячем пользовательский тоггл «Авто»: серверный интервал перебивает выбор.
                        Rectangle {
                            visible: (subInfo.g.profileUpdateInterval || 0) > 0
                            Layout.alignment: Qt.AlignVCenter
                            implicitHeight: 24
                            implicitWidth: subAutoLabel.implicitWidth + 16
                            radius: 12
                            color: Theme.accentSoft
                            border.width: 1; border.color: Theme.accent
                            Text {
                                id: subAutoLabel
                                anchors.centerIn: parent
                                text: T.s("loc.subauto") + " " + (subInfo.g.profileUpdateInterval || 0) + T.s("misc.shorth")
                                color: Theme.accent
                                font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold
                            }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            ToolTip.visible: hoverEnabled && ttHover.hovered
                            ToolTip.text: T.s("loc.subauto.tt")
                            HoverHandler { id: ttHover }
                        }
                        Text {
                            visible: !((subInfo.g.profileUpdateInterval || 0) > 0)
                            text: T.s("btn.auto"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11
                            Layout.alignment: Qt.AlignVCenter
                        }
                        Toggle {
                            visible: !((subInfo.g.profileUpdateInterval || 0) > 0)
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: 40; implicitHeight: 24
                            checked: subInfo.g.auto || false
                            onToggled: backend.setGroupAuto(backend.currentGroup, value)
                        }
                        IconButton { Layout.alignment: Qt.AlignVCenter; glyph: win.icoReconnect; diameter: 34; onClicked: backend.updateGroup(backend.currentGroup) }
                        IconButton { Layout.alignment: Qt.AlignVCenter; glyph: String.fromCharCode(0xE74D); diameter: 34; onClicked: win.askConfirm(T.s("confirm.delsub") + (subInfo.g.name || "") + T.s("confirm.tail"), function() { backend.removeGroup(backend.currentGroup) }) }
                    }
                }

                // панель: поиск / сортировка / авто-выбор
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Rectangle {
                        Layout.fillWidth: true
                        height: 36; radius: 10
                        color: Theme.surface
                        border.width: 1
                        border.color: searchTf.activeFocus ? Qt.rgba(0.04, 0.52, 1.0, 0.6) : Theme.stroke
                        Behavior on border.color { ColorAnimation { duration: Theme.durFast } }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 10; spacing: 8
                            Text { text: String.fromCharCode(0xE721); font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.textMuted; Layout.alignment: Qt.AlignVCenter }
                            TextField {
                                id: searchTf
                                Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter
                                placeholderText: T.s("loc.searchph")
                                placeholderTextColor: Theme.textMuted
                                color: Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 13
                                background: null
                                selectByMouse: true
                                onTextChanged: locPage.searchText = text
                            }
                        }
                    }

                    Rectangle {
                        id: sortBtn
                        readonly property bool on: locPage.sortMode === 1
                        width: sortRow.implicitWidth + 24; height: 36; radius: 10
                        color: sortBtn.on ? Theme.accentSoft : Theme.surface
                        border.width: 1; border.color: sortBtn.on ? Qt.rgba(0.04, 0.52, 1.0, 0.4) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Row {
                            id: sortRow; anchors.centerIn: parent; spacing: 6
                            Text { text: String.fromCharCode(0xE74A); font.family: Theme.iconFamily; font.pixelSize: 13; color: sortBtn.on ? Theme.accent : Theme.textSub; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: T.s("btn.ping"); color: sortBtn.on ? Theme.accent : Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                        }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: locPage.sortMode = (locPage.sortMode === 1 ? 0 : 1) }
                    }

                    // кнопка замера скорости всех серверов в группе
                    Rectangle {
                        id: speedBtn
                        readonly property bool active: backend.speedtestRunning
                        // при замере становится длинной с прогрессом — занимает место favBtn справа
                        implicitWidth: active ? Math.max(220, speedTextRow.implicitWidth + 64) : (speedDefaultRow.implicitWidth + 24)
                        Behavior on implicitWidth { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                        height: 36; radius: 10
                        color: active ? Theme.surfaceAlt : (speedHover.hovered ? Theme.surface : Theme.surface)
                        border.width: 1
                        border.color: active ? Theme.accent : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }

                        // прогресс-заливка
                        Rectangle {
                            anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                            anchors.margins: 1
                            width: (parent.width - 2) * backend.speedtestProgress
                            radius: parent.radius - 1
                            color: Theme.accent
                            opacity: speedBtn.active ? 0.20 : 0
                            Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                        }
                        // idle-состояние
                        Row {
                            id: speedDefaultRow
                            visible: !speedBtn.active
                            anchors.centerIn: parent; spacing: 6
                            Text { text: String.fromCharCode(0xEC4A); font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.textSub; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: T.s("btn.measure"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                        }
                        // running-состояние
                        Row {
                            id: speedTextRow
                            visible: speedBtn.active
                            anchors.centerIn: parent; spacing: 8
                            Text {
                                text: backend.speedtestDone + "/" + backend.speedtestTotal
                                color: Theme.accent
                                font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: backend.speedtestCurrent || "…"
                                color: Theme.textSub
                                font.family: Theme.fontFamily; font.pixelSize: 12
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                            }
                            Text {
                                text: "✕"
                                color: cancelSpdHover.hovered ? Theme.red : Theme.textMuted
                                font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Bold
                                anchors.verticalCenter: parent.verticalCenter
                                HoverHandler { id: cancelSpdHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: backend.cancelSpeedtest() }
                            }
                        }
                        HoverHandler { id: speedHover; enabled: !speedBtn.active; cursorShape: Qt.PointingHandCursor }
                        TapHandler { enabled: !speedBtn.active; onTapped: backend.speedtestAll() }
                    }

                    Rectangle {
                        id: favBtn
                        readonly property bool on: locPage.favOnly
                        width: 44; height: 36; radius: 10
                        color: favBtn.on ? Theme.accentSoft : Theme.surface
                        border.width: 1; border.color: favBtn.on ? Qt.rgba(0.04, 0.52, 1.0, 0.4) : Theme.stroke
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Text { anchors.centerIn: parent; text: favBtn.on ? "★" : "☆"; font.pixelSize: 15; color: favBtn.on ? Theme.amber : Theme.textSub }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: locPage.favOnly = !locPage.favOnly }
                    }

                    Rectangle {
                        width: autoRow.implicitWidth + 24; height: 36; radius: 10
                        color: autoHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                        Behavior on color { ColorAnimation { duration: Theme.durFast } }
                        Row {
                            id: autoRow; anchors.centerIn: parent; spacing: 6
                            Text { text: String.fromCharCode(0xE945); font.family: Theme.iconFamily; font.pixelSize: 14; color: "white"; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: T.s("btn.auto"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                        }
                        HoverHandler { id: autoHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: backend.selectBest() }
                    }
                }

                // список серверов текущей группы
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ThinScrollBar {}
                    visible: locPage.filtered.length > 0
                    model: locPage.filtered
                    delegate: ServerCard {
                        required property var modelData
                        width: ListView.view.width
                        code: modelData.code
                        country: modelData.country
                        city: modelData.city
                        ping: modelData.ping
                        speedMbps: modelData.speedMbps
                        editable: true
                        rowIndex: modelData._idx
                        fav: modelData.fav
                        onEdit: win.openServerEditor(modelData._idx)
                        onFavToggle: backend.toggleFavorite(modelData._idx)
                        onContext: (gx, gy) => {
                            var c = content.mapFromItem(null, gx, gy)
                            win.openServerCtx(modelData._idx, c.x, c.y)
                        }
                    }
                }

                // пустое состояние
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: locPage.filtered.length === 0
                    Item { Layout.fillHeight: true }
                    Text { Layout.alignment: Qt.AlignHCenter; text: locPage.searchText.length > 0 ? String.fromCharCode(0xE721) : String.fromCharCode(0xE774); font.family: Theme.iconFamily; font.pixelSize: 40; color: Theme.textMuted }
                    Text { Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 12; text: locPage.searchText.length > 0 ? T.s("loc.notfound") : T.s("loc.empty"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.Medium }
                    Text {
                        Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 4; Layout.maximumWidth: 380
                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: locPage.searchText.length > 0 ? (T.s("loc.notfoundq") + locPage.searchText + T.s("loc.notfoundtail")) : T.s("loc.emptyhint")
                        color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13
                    }
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 18
                        visible: locPage.searchText.length === 0
                        spacing: 10
                        Rectangle {
                            width: esPasteRow.implicitWidth + 26; height: 36; radius: 10
                            color: esPasteHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Row {
                                id: esPasteRow; anchors.centerIn: parent; spacing: 6
                                Text { text: String.fromCharCode(0xE77F); font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.paste"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: esPasteHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.importFromClipboard() }
                        }
                        Rectangle {
                            width: esAddRow.implicitWidth + 26; height: 36; radius: 10
                            color: esAddHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                            Row {
                                id: esAddRow; anchors.centerIn: parent; spacing: 6
                                Text { text: "+"; color: "white"; font.pixelSize: 16; font.weight: Font.Bold; font.family: Theme.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.server"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: esAddHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.openServerEditor(-1) }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // --- страница: Settings ---
            Flickable {
                anchors.fill: parent
                anchors.margins: Theme.pad
                opacity: win.currentIndex === 3 ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                contentWidth: width
                contentHeight: settingsCol.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ThinScrollBar {}

                ColumnLayout {
                    id: settingsCol
                    width: parent.width
                    spacing: 10

                    Text {
                        text: T.s("page.settings")
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }

                    // баннер: настройки управляются подпиской
                    Rectangle {
                        Layout.fillWidth: true
                        visible: win.managedSub.length > 0
                        radius: Theme.radius
                        color: Theme.accentSoft
                        border.width: 1; border.color: Qt.rgba(0.04, 0.52, 1.0, 0.35)
                        implicitHeight: 52
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 12; spacing: 10
                            Text { text: win.icoLink; font.family: Theme.iconFamily; font.pixelSize: 16; color: Theme.accent; Layout.alignment: Qt.AlignVCenter }
                            Text { Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter; text: T.s("loc.fromsub") + win.managedSub + "»"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap }
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                width: ov.width + 24; height: 30; radius: 15
                                color: ovHover.hovered ? Theme.hover : "transparent"
                                border.width: 1; border.color: Theme.stroke
                                Text { id: ov; anchors.centerIn: parent; text: T.s("btn.manual"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.Medium }
                                HoverHandler { id: ovHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: win.setAutoConf = false }
                            }
                        }
                    }

                    // === ЯЗЫК / LANGUAGE ===
                    Text { text: T.s("sec.language"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.radius
                        color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: langCol.implicitHeight
                        ColumnLayout {
                            id: langCol; width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: String.fromCharCode(0xF2B7)   // globe-like glyph
                                label: T.s("label.lang")
                                sub: T.lang === "ru" ? T.s("misc.langnames") : T.s("misc.langnames.en")
                                // язык — это имя самого языка, не переводим
                                control: Segmented { width: 200; options: [T.s("misc.langname.ru"), T.s("misc.langname.en")]; currentIndex: T.lang === "en" ? 1 : 0; onSelected: T.lang = (index === 1 ? "en" : "ru") }
                            }
                        }
                    }

                    // === ИНТЕРФЕЙС ===
                    Text { text: T.s("sec.interface"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.radius
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.stroke
                        implicitHeight: ifaceCol.implicitHeight
                        ColumnLayout {
                            id: ifaceCol
                            width: parent.width
                            spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoTheme; label: T.s("set.theme"); sub: T.s("set.theme.sub")
                                control: ThemeToggle {}
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoTray; label: T.s("set.tray"); sub: T.s("set.tray.sub")
                                control: Toggle { checked: win.setTray; onToggled: win.setTray = value }
                            }
                        }
                    }

                    // === ПРИЛОЖЕНИЕ (Kitsune) — версия + автообнова ===
                    Text { text: T.s("sec.app"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: appCol.implicitHeight
                        ColumnLayout {
                            id: appCol; width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoReconnect
                                label: "Kitsune"
                                sub: ("v" + backend.appVersion) +
                                     (backend.appLatest && backend.appLatest !== backend.appVersion
                                          ? "  ·  " + T.s("misc.available") + ": v" + backend.appLatest
                                          : "")
                                control: Rectangle {
                                    id: updAppCtl
                                    visible: backend.appUpdateAvailable
                                    // во время загрузки шире — чтобы прогресс читался
                                    width: backend.appUpdating ? 220 : 110
                                    Behavior on width { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                                    height: 32; radius: 9
                                    color: backend.appUpdating ? Theme.surfaceAlt
                                         : (updAppHover.hovered ? Theme.accentSoft : "transparent")
                                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                                    border.width: 1
                                    border.color: backend.appUpdating ? Theme.stroke : Theme.accent

                                    // заливка прогресса
                                    Rectangle {
                                        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                                        anchors.margins: 1
                                        width: (parent.width - 2) * backend.appUpdateProgress
                                        radius: parent.radius - 1
                                        color: Theme.accent
                                        opacity: backend.appUpdating ? 0.85 : 0
                                        Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                                        Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        text: backend.appUpdating
                                            ? Math.round(backend.appUpdateProgress * 100) + "%"
                                            : T.s("sub.update")
                                        color: backend.appUpdating
                                            ? (backend.appUpdateProgress > 0.5 ? "white" : Theme.text)
                                            : Theme.accent
                                        font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                                    }
                                    HoverHandler { id: updAppHover; enabled: !backend.appUpdating; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { enabled: !backend.appUpdating; onTapped: backend.updateApp() }
                                }
                            }
                        }
                    }

                    // === ЯДРО (sing-box) — версии + автообнова ===
                    Text { text: T.s("sec.core"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: coreCol.implicitHeight
                        ColumnLayout {
                            id: coreCol; width: parent.width; spacing: 0

                            // sing-box (официальный, наш fallback) — авто-обновляется
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoReconnect
                                label: "sing-box.exe"
                                sub: (backend.coreVersion || T.s("sub.notinstalled")) +
                                     (backend.coreLatest ? "  ·  " + T.s("misc.available") + ": " + backend.coreLatest : "")
                                control: Rectangle {
                                    id: updCoreCtl
                                    visible: backend.coreUpdateAvailable
                                    width: backend.coreUpdating ? 220 : 110
                                    Behavior on width { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                                    height: 32; radius: 9
                                    color: backend.coreUpdating ? Theme.surfaceAlt
                                         : (updCoreHover.hovered ? Theme.accentSoft : "transparent")
                                    Behavior on color { ColorAnimation { duration: Theme.durBase } }
                                    border.width: 1
                                    border.color: backend.coreUpdating ? Theme.stroke : Theme.accent

                                    Rectangle {
                                        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                                        anchors.margins: 1
                                        width: (parent.width - 2) * backend.coreUpdateProgress
                                        radius: parent.radius - 1
                                        color: Theme.accent
                                        opacity: backend.coreUpdating ? 0.85 : 0
                                        Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                                        Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        text: backend.coreUpdating
                                            ? Math.round(backend.coreUpdateProgress * 100) + "%"
                                            : T.s("sub.update")
                                        color: backend.coreUpdating
                                            ? (backend.coreUpdateProgress > 0.5 ? "white" : Theme.text)
                                            : Theme.accent
                                        font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                                    }
                                    HoverHandler { id: updCoreHover; enabled: !backend.coreUpdating; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { enabled: !backend.coreUpdating; onTapped: backend.updateCore() }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }

                            // строка действий — ручная проверка обновлений
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoClock
                                label: T.s("set.checkup")
                                sub: T.s("set.checkup.sub")
                                control: Rectangle {
                                    width: 110; height: 32; radius: 9
                                    color: checkUpdHover.hovered ? Theme.hover : "transparent"
                                    border.width: 1; border.color: Theme.stroke
                                    Text { anchors.centerIn: parent; text: T.s("btn.check"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                                    HoverHandler { id: checkUpdHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { onTapped: backend.checkCoreUpdateForce() }
                                }
                            }
                        }
                    }

                    // === ПОДПИСКА ===
                    Text { text: T.s("sec.subscription"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: subCol.implicitHeight
                        ColumnLayout {
                            id: subCol; width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoLink; label: T.s("set.autoconf")
                                sub: T.s("set.autoconf.sub")
                                control: Toggle { checked: win.setAutoConf; onToggled: win.setAutoConf = value }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoReconnect
                                label: T.s("set.subautoref")
                                sub: T.s("set.subautoref.sub")
                                control: Toggle {
                                    checked: win.setSubAutoRefresh
                                    onToggled: {
                                        win.setSubAutoRefresh = value
                                        backend.setSubAutoRefresh(value)
                                    }
                                }
                            }
                            // интервал — виден только если auto-refresh включён
                            SettingRow {
                                Layout.fillWidth: true
                                visible: win.setSubAutoRefresh
                                glyph: win.icoClock
                                label: T.s("set.subinterval")
                                sub: T.s("set.subinterval.sub")
                                control: Segmented {
                                    width: 220
                                    options: [T.s("interval.3h"), T.s("interval.6h"), T.s("interval.12h"), T.s("interval.24h")]
                                    currentIndex: win.subRefreshInterval === 3 ? 0
                                                : win.subRefreshInterval === 6 ? 1
                                                : win.subRefreshInterval === 24 ? 3 : 2
                                    onSelected: {
                                        var h = [3, 6, 12, 24][index] || 12
                                        win.subRefreshInterval = h
                                        backend.setSubRefreshInterval(h)
                                    }
                                }
                            }
                        }
                    }

                    // === ПОДКЛЮЧЕНИЕ ===
                    Text { text: T.s("sec.connection"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.radius
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.stroke
                        implicitHeight: connCol.implicitHeight
                        ColumnLayout {
                            id: connCol
                            width: parent.width
                            spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoAutostart; label: T.s("set.autostart"); sub: T.s("set.autostart.sub")
                                control: Toggle {
                                    checked: win.setAutostart
                                    onToggled: { win.setAutostart = value; backend.setAutostart(value) }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoLink; label: T.s("set.autoconnect"); sub: T.s("set.autoconnect.sub")
                                control: Toggle { checked: backend.autoConnect; onToggled: backend.autoConnect = value }
                            }
                            Rectangle { visible: backend.autoConnect; Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                visible: backend.autoConnect
                                Layout.fillWidth: true
                                glyph: win.icoReconnect; label: T.s("set.connectto"); sub: T.s("set.connectto.sub")
                                control: Segmented { width: 220; options: [T.s("seg.last"), T.s("seg.fastest")]; currentIndex: backend.autoConnectMode; onSelected: backend.autoConnectMode = index }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoReconnect; label: T.s("set.reconnect"); sub: T.s("set.reconnect.sub")
                                control: Toggle {
                                    checked: win.setReconnect
                                    onToggled: { win.setReconnect = value; backend.setReconnectEnabled(value) }
                                }
                            }
                        }
                    }

                    // === ГОРЯЧАЯ КЛАВИША ===
                    Text { text: T.s("sec.hotkey"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: hkCol.implicitHeight
                        ColumnLayout {
                            id: hkCol; width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: String.fromCharCode(0xE765); label: T.s("set.hotkey"); sub: T.s("set.hotkey.sub")
                                control: Toggle { checked: backend.hotkeyEnabled; onToggled: backend.hotkeyEnabled = value }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: String.fromCharCode(0xE70F); label: T.s("set.combo"); sub: T.s("set.combo.sub")
                                control: HotkeyField {}
                            }
                        }
                    }

                    // === БЕЗОПАСНОСТЬ ===
                    Text { text: T.s("sec.security"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true
                        radius: Theme.radius
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.stroke
                        implicitHeight: secCol.implicitHeight
                        ColumnLayout {
                            id: secCol
                            width: parent.width
                            spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoShield; label: T.s("set.killswitch")
                                sub: T.s("set.killswitch.sub")
                                control: Toggle {
                                    checked: win.setKill
                                    onToggled: { win.setKill = value; backend.setKillSwitchEnabled(value) }
                                }
                            }
                        }
                    }

                    // === ВХОДЯЩЕЕ ===
                    Text { text: T.s("sec.inbound"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: inCol.implicitHeight
                        ColumnLayout {
                            id: inCol; width: parent.width; spacing: 0
                            SettingRow { Layout.fillWidth: true; glyph: win.icoPort; label: T.s("set.port"); sub: T.s("set.port.sub"); control: ValueField { fieldWidth: 90; numeric: true; text: win.portMixed; onEdited: win.portMixed = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoLink; label: T.s("set.lan"); sub: T.s("set.lan.sub"); control: Toggle { checked: win.setLan; onToggled: win.setLan = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoSniff; label: T.s("set.sniff"); sub: T.s("set.sniff.sub"); control: Toggle { checked: win.setSniff; onToggled: win.setSniff = value } }
                        }
                    }

                    // === TUN ===
                    Text { text: T.s("sec.tun"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: tunCol.implicitHeight
                        ColumnLayout {
                            id: tunCol; width: parent.width; spacing: 0
                            SettingRow { Layout.fillWidth: true; glyph: win.icoTun; label: T.s("set.tunmode"); sub: T.s("set.tunmode.sub"); control: Toggle { checked: backend.mode === "tun"; onToggled: backend.setMode(value ? "tun" : "proxy") } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoTun; label: T.s("set.tunstack"); control: Segmented { width: 210; options: ["gVisor", "system", "mixed"]; currentIndex: win.tunStack; onSelected: win.tunStack = index } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoPort; label: "MTU"; control: ValueField { fieldWidth: 90; numeric: true; text: win.mtu; onEdited: win.mtu = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoShield; label: T.s("set.strict"); sub: T.s("set.strict.sub"); control: Toggle { checked: win.setStrictRoute; onToggled: win.setStrictRoute = value } }
                        }
                    }

                    // === DNS ===
                    Text { text: T.s("sec.dns"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: dnsCol.implicitHeight
                        ColumnLayout {
                            id: dnsCol; width: parent.width; spacing: 0
                            SettingRow { Layout.fillWidth: true; glyph: win.icoDns; label: T.s("set.dnsremote"); sub: T.s("set.dnsremote.sub"); control: ValueField { fieldWidth: 220; text: win.dnsRemote; onEdited: win.dnsRemote = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoDns; label: T.s("set.dnsdirect"); sub: T.s("set.dnsdirect.sub"); control: ValueField { fieldWidth: 140; text: win.dnsDirect; onEdited: win.dnsDirect = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoShield; label: T.s("set.fakeip"); sub: T.s("set.fakeip.sub"); control: Toggle { checked: win.setFakeIp; onToggled: win.setFakeIp = value } }
                        }
                    }

                    // === MUX ===
                    Text { text: T.s("sec.mux"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.stroke
                        implicitHeight: muxCol.implicitHeight
                        ColumnLayout {
                            id: muxCol; width: parent.width; spacing: 0
                            SettingRow { Layout.fillWidth: true; glyph: win.icoMux; label: T.s("set.mux"); sub: T.s("set.mux.sub"); control: Toggle { checked: win.setMux; onToggled: win.setMux = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoMux; label: T.s("set.muxproto"); control: Segmented { width: 210; options: ["smux", "yamux", "h2mux"]; currentIndex: win.muxProto; onSelected: win.muxProto = index } }
                        }
                    }

                    // === ДИАГНОСТИКА (панель логов скрыта по умолчанию — открывается явно) ===
                    Text { text: T.s("sec.diagnostics"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: dgCol.implicitHeight
                        ColumnLayout {
                            id: dgCol; width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoLogs
                                label: T.s("logs.title")
                                sub: T.s("logs.sub")
                                control: Rectangle {
                                    id: openLogsBtn
                                    width: 110; height: 32; radius: 9
                                    color: openLogsHover.hovered ? Theme.hover : "transparent"
                                    border.width: 1; border.color: Theme.stroke
                                    Text { anchors.centerIn: parent; text: T.s("btn.open"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                                    HoverHandler { id: openLogsHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler { onTapped: win.logsOpen = true }
                                }
                            }
                        }
                    }

                    Item { Layout.preferredHeight: 8 }
                }
            }

            // --- страница: Routing ---
            Flickable {
                anchors.fill: parent
                anchors.margins: Theme.pad
                opacity: win.currentIndex === 2 ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                contentWidth: width
                contentHeight: rtCol.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ThinScrollBar {}

                ColumnLayout {
                    id: rtCol
                    width: parent.width
                    spacing: 10

                    Text {
                        text: T.s("page.routing")
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 22; font.weight: Font.DemiBold
                        Layout.bottomMargin: 6
                    }

                    // ── Профили маршрутизации (именованные пресеты настроек+правил) ──
                    Text { text: T.s("rt.profiles"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: win.routingProfiles
                            delegate: Rectangle {
                                id: profChip
                                required property var modelData
                                required property int index
                                readonly property bool active: win.currentProfileId === profChip.modelData.id
                                readonly property bool removable: profChip.modelData.id !== "default"
                                height: 30
                                width: profRow.implicitWidth + (profChip.removable ? 36 : 20)
                                radius: 15
                                color: profChip.active ? Theme.accent
                                     : (profHover.hovered ? Qt.lighter(Theme.surface, 1.2) : Theme.surface)
                                border.width: 1
                                border.color: profChip.active ? Theme.accent : Theme.stroke
                                Behavior on color { ColorAnimation { duration: Theme.durFast } }

                                Row {
                                    id: profRow
                                    anchors.left: parent.left; anchors.leftMargin: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 8
                                    Text {
                                        text: profChip.modelData.name
                                        color: profChip.active ? "white" : Theme.text
                                        font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }
                                // крестик удаления (только для не-дефолтных)
                                Text {
                                    visible: profChip.removable && (profHover.hovered || profChip.active)
                                    text: "✕"
                                    color: profChip.active ? Qt.rgba(1,1,1,0.7) : Theme.textMuted
                                    font.family: Theme.fontFamily; font.pixelSize: 12
                                    anchors.right: parent.right; anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    HoverHandler { id: profDelHover; cursorShape: Qt.PointingHandCursor }
                                    TapHandler {
                                        onTapped: win.askConfirm(T.s("confirm.delprof") + profChip.modelData.name + T.s("confirm.tail"),
                                                                 function() { win.deleteProfile(profChip.modelData.id) })
                                    }
                                }
                                HoverHandler { id: profHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler {
                                    enabled: !profDelHover.hovered
                                    onTapped: win.applyProfile(profChip.modelData.id)
                                }
                            }
                        }
                        // "+" — добавить новый профиль
                        Rectangle {
                            height: 30; width: 30; radius: 15
                            color: addProfHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: "+"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.Bold }
                            HoverHandler { id: addProfHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { win.newProfileName = ""; win.newProfileOpen = true } }
                        }
                    }
                    Text {
                        text: T.s("misc.profile.hint")
                        color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; wrapMode: Text.Wrap
                        Layout.fillWidth: true; Layout.bottomMargin: 8
                    }

                    Text { text: T.s("rt.profilefinal"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: rtProfCol.implicitHeight
                        ColumnLayout {
                            id: rtProfCol
                            width: parent.width; spacing: 0
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoRouting; label: T.s("set.routeprofile")
                                control: Segmented { width: 210; options: [T.s("seg.auto"), T.s("seg.global"), T.s("seg.ru")]; currentIndex: win.rtProfile; onSelected: win.rtProfile = index }
                            }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow {
                                Layout.fillWidth: true
                                glyph: win.icoShield; label: T.s("set.routefinal"); sub: T.s("set.routefinal.sub")
                                control: Segmented { width: 230; options: [T.s("seg.proxy"), T.s("seg.direct"), T.s("seg.block")]; currentIndex: win.rtFinal; onSelected: win.rtFinal = index }
                            }
                        }
                    }

                    Text { text: T.s("rt.presets"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1; Layout.topMargin: 8 }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: rtPreCol.implicitHeight
                        ColumnLayout {
                            id: rtPreCol
                            width: parent.width; spacing: 0
                            SettingRow { Layout.fillWidth: true; glyph: win.icoLink; label: T.s("set.routelan"); sub: T.s("set.routelan.sub"); control: Toggle { checked: win.rtLan; onToggled: win.rtLan = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoRouting; label: T.s("set.routeru"); sub: T.s("set.routeru.sub"); control: Toggle { checked: win.rtRegionDirect; onToggled: win.rtRegionDirect = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoShield; label: T.s("set.adblock"); sub: T.s("set.adblock.sub"); control: Toggle { checked: win.rtAdblock; onToggled: win.rtAdblock = value } }
                            Rectangle { Layout.fillWidth: true; Layout.leftMargin: 50; height: 1; color: Theme.stroke }
                            SettingRow { Layout.fillWidth: true; glyph: win.icoLock; label: T.s("set.proxyall"); sub: T.s("set.proxyall.sub"); control: Toggle { checked: win.rtProxyAll; onToggled: win.rtProxyAll = value } }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        Text { text: T.s("rt.rules"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                        Item { Layout.fillWidth: true }
                        // импорт правил из чужих клиентов
                        Rectangle {
                            width: importRow.implicitWidth + 22; height: 28; radius: 14
                            color: importRulesHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Row {
                                id: importRow; anchors.centerIn: parent; spacing: 6
                                Text { text: String.fromCharCode(0xE8B5); font.family: Theme.iconFamily; font.pixelSize: 13; color: Theme.textSub; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.importrules"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.Medium; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: importRulesHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { win.importDraft = ""; win.importRulesOpen = true } }
                        }
                        Rectangle {
                            width: addRow.implicitWidth + 24; height: 28; radius: 14
                            color: addHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Row {
                                id: addRow
                                anchors.centerIn: parent
                                spacing: 6
                                Text { text: "+"; color: "white"; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.rule"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: addHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.openRuleEditor() }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: Math.max(52, rulesList.contentHeight)
                        clip: true
                        ListView {
                            id: rulesList
                            anchors.fill: parent
                            interactive: false
                            model: win.routeRules
                            delegate: Item {
                                id: rwrap
                                required property int index
                                required property var modelData
                                width: rulesList.width
                                // process-правила управляются секцией «ПРИЛОЖЕНИЯ» ниже — не показываем дубликат
                                // в общем списке. height:0 + visible:false: ListView их пропускает по высоте,
                                // но индексы остаются исходными → drag-sort/remove работают без мапинга.
                                readonly property bool _hidden: rwrap.modelData.type === "process"
                                visible: !rwrap._hidden
                                height: rwrap._hidden ? 0 : 52
                                z: dragMa.drag.active ? 2 : 1
                                readonly property color actColor: modelData.action === "proxy" ? Theme.accent
                                    : modelData.action === "direct" ? Theme.green : Theme.red
                                readonly property string actText: modelData.action === "proxy" ? T.s("seg.proxy")
                                    : modelData.action === "direct" ? T.s("seg.direct") : T.s("seg.block")

                                Rectangle {
                                    id: rcontent
                                    width: rwrap.width
                                    height: 52
                                    y: 0
                                    color: dragMa.drag.active ? Theme.surfaceAlt : "transparent"
                                    Behavior on y { enabled: !dragMa.drag.active; NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                                    Behavior on color { ColorAnimation { duration: Theme.durFast } }

                                    Rectangle { visible: rwrap.index > 0 && !dragMa.drag.active; anchors.top: parent.top; x: 16; width: parent.width - 32; height: 1; color: Theme.stroke }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12; anchors.rightMargin: 16
                                        spacing: 10
                                        Item {
                                            Layout.alignment: Qt.AlignVCenter
                                            implicitWidth: 26; implicitHeight: 44
                                            Rectangle {
                                                anchors.centerIn: parent
                                                width: 24; height: 30; radius: 7
                                                color: dragMa.pressed ? Theme.surfaceAlt : dragMa.containsMouse ? Theme.hover : "transparent"
                                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            }
                                            Text {
                                                anchors.centerIn: parent
                                                text: String.fromCharCode(0xE700)
                                                font.family: Theme.iconFamily; font.pixelSize: 15
                                                color: dragMa.pressed ? Theme.accent : dragMa.containsMouse ? Theme.text : Theme.textMuted
                                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            }
                                            MouseArea {
                                                id: dragMa
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.SizeVerCursor
                                                preventStealing: true
                                                drag.target: rcontent
                                                drag.axis: Drag.YAxis
                                                onReleased: {
                                                    var shift = Math.round(rcontent.y / rwrap.height)
                                                    var t = Math.max(0, Math.min(win.routeRules.length - 1, rwrap.index + shift))
                                                    rcontent.y = 0
                                                    win.moveRule(rwrap.index, t)
                                                }
                                            }
                                        }
                                        Rectangle {
                                            Layout.alignment: Qt.AlignVCenter
                                            width: tt.width + 16; height: 22; radius: 6
                                            color: Theme.surfaceAlt
                                            Text { id: tt; anchors.centerIn: parent; text: rwrap.modelData.type; color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.DemiBold }
                                        }
                                        Text {
                                            Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter
                                            text: rwrap.modelData.value
                                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight
                                        }
                                        Rectangle {
                                            Layout.alignment: Qt.AlignVCenter
                                            width: at.width + 18; height: 24; radius: 12
                                            color: Qt.rgba(rwrap.actColor.r, rwrap.actColor.g, rwrap.actColor.b, 0.16)
                                            Text { id: at; anchors.centerIn: parent; text: rwrap.actText; color: rwrap.actColor; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold }
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignVCenter
                                            text: "✕"; color: rdelHover.hovered ? Theme.red : Theme.textMuted
                                            font.family: Theme.fontFamily; font.pixelSize: 13
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            HoverHandler { id: rdelHover; cursorShape: Qt.PointingHandCursor }
                                            TapHandler { onTapped: win.routeRules = win.routeRules.filter(function(r, i) { return i !== rwrap.index }) }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // === ПРИЛОЖЕНИЯ — per-app проксирование (тумблеры) ===
                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 14
                        Text { text: T.s("rt.apps"); color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1 }
                        Item { Layout.fillWidth: true }
                        // мини-кнопка «Сбросить per-app правила» — видна только если есть что сбрасывать
                        Rectangle {
                            visible: win.routeRules.filter(function(r) { return r.type === "process" }).length > 0
                            width: 110; height: 28; radius: 8
                            color: resetAppsHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.reset"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12 }
                            HoverHandler { id: resetAppsHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.askConfirm(T.s("confirm.delperapp"), function() { win.resetAppRules() }) }
                        }
                        Rectangle {
                            // кнопка «+ Добавить» — открывает системный файл-пикер для exe
                            width: 105; height: 28; radius: 8
                            color: addAppHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Row { anchors.centerIn: parent; spacing: 5
                                Text { text: "+"; color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.Bold; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.add"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: addAppHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.addCustomAppDialog() }
                        }
                        Rectangle {
                            // мини-кнопка «Пересканировать»
                            width: 130; height: 28; radius: 8
                            color: rescanHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.rescan"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 12 }
                            HoverHandler { id: rescanHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.scanApps() }
                        }
                    }
                    Text {
                        text: {
                            var finalT = win.rtFinal === 1 ? T.s("seg.direct") : win.rtFinal === 2 ? T.s("seg.block") : T.s("seg.proxy")
                            var p = win._findProfile(win.currentProfileId)
                            return T.s("apps.activeprofile") + (p ? p.name : "—") + T.s("apps.defaultis") + finalT + "). "
                                + T.s("apps.action.hint")
                        }
                        color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 11; wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    // поле поиска
                    ValueField {
                        Layout.fillWidth: true
                        align: TextInput.AlignLeft
                        text: win.appFilter
                        placeholder: T.s("apps.search")
                        onEdited: win.appFilter = value
                    }

                    // список приложений
                    Rectangle {
                        Layout.fillWidth: true; radius: Theme.radius; color: Theme.surface
                        border.width: 1; border.color: Theme.stroke
                        implicitHeight: appsCol.implicitHeight > 0 ? appsCol.implicitHeight + 8 : 56
                        ColumnLayout {
                            id: appsCol
                            width: parent.width; spacing: 0

                            // пустое состояние (на момент сканирования)
                            Text {
                                visible: (backend.appList || []).length === 0
                                Layout.fillWidth: true
                                Layout.margins: 14
                                text: T.s("apps.scanning")
                                color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 13
                            }
                            Text {
                                visible: (backend.appList || []).length > 0 && win.appsFiltered().length === 0
                                Layout.fillWidth: true
                                Layout.margins: 14
                                text: T.s("apps.notfound") + win.appFilter + "»"
                                color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 13
                            }

                            Repeater {
                                model: win.appsFiltered()
                                delegate: Item {
                                    id: appRow
                                    required property var modelData
                                    required property int index
                                    width: appsCol.width
                                    height: 44

                                    Rectangle {
                                        anchors.fill: parent
                                        color: appHover.hovered ? Theme.hover : "transparent"
                                        HoverHandler { id: appHover }
                                    }
                                    Rectangle {
                                        visible: appRow.index < win.appsFiltered().length - 1
                                        anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
                                        anchors.leftMargin: 50
                                        height: 1; color: Theme.stroke
                                    }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 14; anchors.rightMargin: 14
                                        spacing: 12
                                        Image {
                                            width: 22; height: 22
                                            sourceSize.width: 44; sourceSize.height: 44
                                            source: appRow.modelData.icon
                                            fillMode: Image.PreserveAspectFit
                                            smooth: true
                                            Layout.alignment: Qt.AlignVCenter
                                            // фоллбэк если иконки нет
                                            Rectangle { anchors.fill: parent; visible: parent.status !== Image.Ready; color: Theme.surfaceAlt; radius: 4 }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true; spacing: 1
                                            Text {
                                                text: appRow.modelData.name
                                                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13
                                                elide: Text.ElideRight; Layout.fillWidth: true
                                            }
                                            Text {
                                                text: appRow.modelData.exeName
                                                color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 10
                                                elide: Text.ElideRight; Layout.fillWidth: true
                                            }
                                        }
                                        Segmented {
                                            id: appSeg
                                            width: 188
                                            options: [T.s("seg.auto"), T.s("seg.vpn"), T.s("seg.direct")]
                                            Layout.alignment: Qt.AlignVCenter
                                            onSelected: win.setAppRouteState(
                                                appRow.modelData.exeName,
                                                index === 1 ? "proxy" : index === 2 ? "direct" : "auto")
                                            // Segmented сам ставит currentIndex императивно при тапе (ломает inline-биндинг).
                                            // Binding-элемент пере-устанавливает значение при ЛЮБОМ изменении routeRules
                                            // (включая правки из глобальной таблицы правил или Сброс).
                                            Binding on currentIndex {
                                                value: {
                                                    var s = win.appRouteState(appRow.modelData.exeName)
                                                    return s === "proxy" ? 1 : s === "direct" ? 2 : 0
                                                }
                                            }
                                        }
                                        // крестик удаления — только для пользовательских (вручную добавленных)
                                        Text {
                                            visible: !!appRow.modelData.custom
                                            text: "✕"
                                            color: rmCustomHover.hovered ? Theme.red : Theme.textMuted
                                            font.family: Theme.fontFamily; font.pixelSize: 13
                                            Layout.alignment: Qt.AlignVCenter
                                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                            HoverHandler { id: rmCustomHover; cursorShape: Qt.PointingHandCursor }
                                            TapHandler {
                                                onTapped: {
                                                    // снимаем правило, чтобы не оставить «висящее» process-правило
                                                    win.setAppRouteState(appRow.modelData.exeName, "auto")
                                                    backend.removeCustomApp(appRow.modelData.exeName)
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Item { Layout.preferredHeight: 8 }
                }
            }

            // перехват кликов вне выпадающего меню
            MouseArea {
                anchors.fill: parent
                visible: win.serverMenuOpen
                z: 90
                onClicked: win.serverMenuOpen = false
            }

            // выпадающее меню выбора сервера (под пилюлей, раскрывается вниз)
            Item {
                id: serverMenu
                z: 100
                width: 340
                height: Math.min(backend.servers.length * 70 + 12, 330)

                readonly property bool openUp: {
                    var _ = win.width + win.height + (win.serverMenuOpen ? 1 : 0)
                    var topY = pill.mapToItem(content, 0, 0).y
                    return (topY + pill.height + 8 + height) > content.height
                }
                x: { var _ = win.width + win.height + (win.serverMenuOpen ? 1 : 0); return pill.mapToItem(content, 0, 0).x }
                y: {
                    var _ = win.width + win.height + (win.serverMenuOpen ? 1 : 0)
                    var topY = pill.mapToItem(content, 0, 0).y
                    return openUp ? (topY - height - 8) : (topY + pill.height + 8)
                }
                visible: opacity > 0.01
                opacity: win.serverMenuOpen ? 1 : 0
                scale: win.serverMenuOpen ? 1 : 0.96
                transformOrigin: openUp ? Item.Bottom : Item.Top
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusLg
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.stroke
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: Theme.shadow
                        shadowBlur: 1.0
                        shadowVerticalOffset: 12
                    }

                    ListView {
                        anchors.fill: parent
                        anchors.margins: 6
                        clip: true
                        spacing: 4
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ThinScrollBar {}
                        model: backend.servers
                        delegate: ServerCard {
                            required property var modelData
                            width: ListView.view.width
                            code: modelData.code
                            country: modelData.country
                            city: modelData.city
                            ping: modelData.ping
                            onPicked: win.serverMenuOpen = false
                        }
                    }
                }
            }

            // контекстное меню сервера (правый клик)
            MouseArea {
                anchors.fill: parent
                visible: win.ctxOpen
                z: 150
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: win.ctxOpen = false
            }
            Rectangle {
                id: ctxMenu
                z: 151
                width: 226
                x: Math.max(8, Math.min(win.ctxX, content.width - width - 8))
                y: Math.max(8, Math.min(win.ctxY, content.height - height - 8))
                implicitHeight: ctxCol.implicitHeight + 12
                radius: 12
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                visible: opacity > 0.01
                opacity: win.ctxOpen ? 1 : 0
                scale: win.ctxOpen ? 1 : 0.96
                transformOrigin: Item.TopLeft
                Behavior on opacity { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 10 }

                ColumnLayout {
                    id: ctxCol
                    width: parent.width - 12
                    x: 6; y: 6
                    spacing: 1

                    CtxItem { glyph: String.fromCharCode(0xE7E8); label: T.s("ctx.connect"); onClicked: { backend.selectServer(win.ctxName()); if (backend.status === "disconnected") backend.toggle(); win.ctxOpen = false } }
                    CtxItem { glyph: String.fromCharCode(0xE70F); label: T.s("ctx.edit"); onClicked: { win.openServerEditor(win.ctxIndex); win.ctxOpen = false } }
                    CtxItem { glyph: String.fromCharCode(0xE8C8); label: T.s("ctx.duplicate"); onClicked: { backend.duplicateServer(win.ctxIndex); win.ctxOpen = false } }
                    CtxItem { glyph: String.fromCharCode(0xE72D); label: T.s("ctx.share"); onClicked: { win.openShare(win.ctxIndex); win.ctxOpen = false } }
                    CtxItem { glyph: String.fromCharCode(0xE71B); label: T.s("ctx.copylink"); onClicked: { backend.copyToClipboard(backend.serverLink(win.ctxIndex)); win.ctxOpen = false } }
                    CtxItem {
                        readonly property bool isFav: backend.servers[win.ctxIndex] ? backend.servers[win.ctxIndex].fav === true : false
                        glyph: String.fromCharCode(isFav ? 0xE735 : 0xE734)
                        label: isFav ? T.s("loc.fav.remove") : T.s("loc.fav.add")
                        onClicked: { backend.toggleFavorite(win.ctxIndex); win.ctxOpen = false }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.topMargin: 4; Layout.bottomMargin: 4; height: 1; color: Theme.stroke }
                    CtxItem { glyph: String.fromCharCode(0xE74D); label: T.s("ctx.delete"); danger: true; onClicked: { var n = win.ctxName(); var i = win.ctxIndex; win.ctxOpen = false; win.askConfirm(T.s("confirm.delsrv") + n + T.s("confirm.tail"), function() { backend.removeServer(i) }) } }
                    Rectangle { Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 10; Layout.topMargin: 4; Layout.bottomMargin: 4; height: 1; color: Theme.stroke }
                    CtxItem { glyph: String.fromCharCode(0xE710); label: T.s("ctx.connect"); onClicked: { win.openServerEditor(-1); win.ctxOpen = false } }
                }
            }

            // оверлей: добавить подписку
            MouseArea {
                anchors.fill: parent
                visible: win.addSubOpen
                z: 200
                onClicked: win.addSubOpen = false
            }
            Rectangle {
                id: addSubModal
                z: 201
                width: 400
                anchors.centerIn: parent
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                implicitHeight: asCol.implicitHeight + 36
                visible: opacity > 0.01
                opacity: win.addSubOpen ? 1 : 0
                scale: win.addSubOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 16 }

                ColumnLayout {
                    id: asCol
                    width: parent.width - 36
                    x: 18; y: 18
                    spacing: 10

                    Text { text: T.s("modal.sub.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }

                    Text { text: T.s("modal.sub.name"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.draftSubName; placeholder: T.s("modal.sub.nameph"); onEdited: win.draftSubName = value }

                    Text { text: T.s("modal.sub.url"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.draftSubUrl; placeholder: T.s("modal.sub.urlph"); onEdited: win.draftSubUrl = value }

                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 4
                        Text { text: T.s("set.autoupdate"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                        Item { Layout.fillWidth: true }
                        Toggle { checked: win.draftSubAuto; onToggled: win.draftSubAuto = value }
                    }

                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 6
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 96; height: 36; radius: 10
                            color: cancelSubHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.cancel"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: cancelSubHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.addSubOpen = false }
                        }
                        Rectangle {
                            width: 116; height: 36; radius: 10
                            readonly property bool ready: win.draftSubUrl.length > 0
                            color: !ready ? Theme.surfaceAlt : (addSubHover2.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text { anchors.centerIn: parent; text: T.s("btn.add"); color: parent.ready ? "white" : Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: addSubHover2; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.addSub() }
                        }
                    }
                }
            }

            // оверлей: редактор профиля сервера
            MouseArea {
                anchors.fill: parent
                visible: win.serverEditorOpen
                z: 210
                onClicked: win.serverEditorOpen = false
            }
            Rectangle {
                id: serverEditor
                z: 211
                width: 460
                anchors.centerIn: parent
                height: Math.min(parent.height - 56, 560)
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                visible: opacity > 0.01
                opacity: win.serverEditorOpen ? 1 : 0
                scale: win.serverEditorOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 18 }

                readonly property bool pV: win.epProtocol === "vless"
                readonly property bool pVm: win.epProtocol === "vmess"
                readonly property bool pT: win.epProtocol === "trojan"
                readonly property bool pSs: win.epProtocol === "shadowsocks"
                readonly property bool pWg: win.epProtocol === "wireguard"
                readonly property bool tlsCap: pV || pVm || pT

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: win.epIndex < 0 ? T.s("misc.newsrv") : T.s("modal.srv.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text {
                            visible: win.epIndex >= 0
                            text: String.fromCharCode(0xE74D)
                            font.family: Theme.iconFamily; font.pixelSize: 16
                            color: delSrvHover.hovered ? Theme.red : Theme.textMuted
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            HoverHandler { id: delSrvHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.askConfirm(T.s("confirm.delsrv") + win.epName + T.s("confirm.tail"), function() { backend.removeServer(win.epIndex); win.serverEditorOpen = false }) }
                        }
                    }

                    Flickable {
                        id: seFlick
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: width
                        contentHeight: seFields.implicitHeight
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ThinScrollBar {}

                        ColumnLayout {
                            id: seFields
                            width: seFlick.width
                            spacing: 10

                            FLabel { text: T.s("modal.srv.name") }
                            ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epName; placeholder: T.s("modal.srv.nameph"); onEdited: win.epName = value }

                            FLabel { text: T.s("modal.srv.proto") }
                            ChipRow { Layout.fillWidth: true; options: win.protoList; current: win.epProtocol; onPicked: win.epProtocol = value }

                            FLabel { text: T.s("modal.srv.addrport") }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epAddress; placeholder: "example.com"; onEdited: win.epAddress = value }
                                ValueField { fieldWidth: 92; numeric: true; text: win.epPort; placeholder: "443"; onEdited: win.epPort = value }
                            }

                            FLabel { visible: serverEditor.pV || serverEditor.pVm; text: "UUID" }
                            ValueField { visible: serverEditor.pV || serverEditor.pVm; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epUuid; placeholder: T.s("modal.srv.uuidph"); onEdited: win.epUuid = value }

                            FLabel { visible: serverEditor.pT || serverEditor.pSs; text: T.s("modal.srv.password") }
                            ValueField { visible: serverEditor.pT || serverEditor.pSs; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epPassword; placeholder: T.s("modal.srv.passwordph"); onEdited: win.epPassword = value }

                            FLabel { visible: serverEditor.pSs; text: T.s("modal.srv.method") }
                            ChipRow { visible: serverEditor.pSs; Layout.fillWidth: true; options: win.ssMethods; current: win.epMethod; onPicked: win.epMethod = value }

                            FLabel { visible: serverEditor.pWg; text: T.s("modal.srv.wgkey") }
                            ValueField { visible: serverEditor.pWg; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epWgKey; placeholder: "base64 private key"; onEdited: win.epWgKey = value }

                            FLabel { visible: serverEditor.pWg; text: "PEER PUBLIC KEY" }
                            ValueField { visible: serverEditor.pWg; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epPeerKey; placeholder: "base64 peer public key"; onEdited: win.epPeerKey = value }

                            FLabel { visible: serverEditor.pWg; text: "LOCAL ADDRESS" }
                            ValueField { visible: serverEditor.pWg; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epLocalAddr; placeholder: "172.16.0.2/32"; onEdited: win.epLocalAddr = value }

                            FLabel { visible: serverEditor.pWg; text: "ALLOWED IPs" }
                            ValueField { visible: serverEditor.pWg; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epAllowedIps; placeholder: "0.0.0.0/0"; onEdited: win.epAllowedIps = value }

                            RowLayout {
                                visible: serverEditor.pWg; Layout.fillWidth: true; spacing: 12
                                ColumnLayout { spacing: 4
                                    FLabel { text: "MTU" }
                                    ValueField { fieldWidth: 90; numeric: true; text: win.epWgMtu; placeholder: "1420"; onEdited: win.epWgMtu = value }
                                }
                                ColumnLayout { Layout.fillWidth: true; spacing: 4
                                    FLabel { text: T.s("modal.srv.psk") }
                                    ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epPsk; placeholder: T.s("modal.srv.pskph"); onEdited: win.epPsk = value }
                                }
                            }

                            FLabel { visible: serverEditor.tlsCap; text: T.s("sec.security") }
                            RowLayout {
                                visible: serverEditor.tlsCap; Layout.fillWidth: true
                                Text { text: "TLS"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 14; Layout.alignment: Qt.AlignVCenter }
                                Item { Layout.fillWidth: true }
                                Toggle { Layout.alignment: Qt.AlignVCenter; checked: win.epTls; onToggled: win.epTls = value }
                            }
                            FLabel { visible: serverEditor.tlsCap && win.epTls; text: "SNI" }
                            ValueField { visible: serverEditor.tlsCap && win.epTls; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epSni; placeholder: "server name"; onEdited: win.epSni = value }

                            RowLayout {
                                visible: serverEditor.pV; Layout.fillWidth: true
                                Text { text: "Reality"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 14; Layout.alignment: Qt.AlignVCenter }
                                Item { Layout.fillWidth: true }
                                Toggle { Layout.alignment: Qt.AlignVCenter; checked: win.epReality; onToggled: win.epReality = value }
                            }
                            FLabel { visible: serverEditor.pV && win.epReality; text: "PUBLIC KEY" }
                            ValueField { visible: serverEditor.pV && win.epReality; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epPbk; placeholder: "reality public key"; onEdited: win.epPbk = value }
                            FLabel { visible: serverEditor.pV && win.epReality; text: "SHORT ID" }
                            ValueField { visible: serverEditor.pV && win.epReality; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epSid; placeholder: "short id"; onEdited: win.epSid = value }
                            FLabel { visible: serverEditor.pV; text: "FLOW" }
                            ChipRow { visible: serverEditor.pV; Layout.fillWidth: true; options: ["none", "xtls-rprx-vision"]; current: win.epFlow.length ? win.epFlow : "none"; onPicked: win.epFlow = (value === "none" ? "" : value) }

                            FLabel { visible: serverEditor.tlsCap; text: T.s("modal.srv.transport") }
                            ChipRow { visible: serverEditor.tlsCap; Layout.fillWidth: true; options: win.transports; current: win.epTransport; onPicked: win.epTransport = value }
                            FLabel { visible: serverEditor.tlsCap && (win.epTransport === "ws" || win.epTransport === "xhttp"); text: "PATH" }
                            ValueField { visible: serverEditor.tlsCap && (win.epTransport === "ws" || win.epTransport === "xhttp"); Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epPath; placeholder: "/path"; onEdited: win.epPath = value }
                            FLabel { visible: serverEditor.tlsCap && win.epTransport === "ws"; text: "HOST" }
                            ValueField { visible: serverEditor.tlsCap && win.epTransport === "ws"; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epHost; placeholder: "host header"; onEdited: win.epHost = value }
                            FLabel { visible: serverEditor.tlsCap && win.epTransport === "grpc"; text: "SERVICE NAME" }
                            ValueField { visible: serverEditor.tlsCap && win.epTransport === "grpc"; Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.epServiceName; placeholder: "grpc service"; onEdited: win.epServiceName = value }

                            Item { Layout.preferredHeight: 2 }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            visible: win.epIndex >= 0
                            width: shareBtnRow.implicitWidth + 24; height: 38; radius: 10
                            color: shareBtnHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Row {
                                id: shareBtnRow; anchors.centerIn: parent; spacing: 6
                                Text { text: String.fromCharCode(0xE72D); font.family: Theme.iconFamily; font.pixelSize: 14; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: T.s("btn.share"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                            }
                            HoverHandler { id: shareBtnHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.openShare(win.epIndex) }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 96; height: 38; radius: 10
                            color: cancelSrvHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.cancel"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: cancelSrvHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.serverEditorOpen = false }
                        }
                        Item { width: 8 }
                        Rectangle {
                            width: 124; height: 38; radius: 10
                            readonly property bool ready: win.epAddress.length > 0
                            color: !ready ? Theme.surfaceAlt : (saveSrvHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text { anchors.centerIn: parent; text: win.epIndex < 0 ? T.s("misc.addbtn") : T.s("misc.savebtn"); color: parent.ready ? "white" : Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: saveSrvHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.saveServer() }
                        }
                    }
                }
            }

            // оверлей: поделиться (ссылка + QR)
            MouseArea {
                anchors.fill: parent
                visible: win.shareOpen
                z: 220
                onClicked: win.shareOpen = false
            }
            Rectangle {
                id: shareModal
                z: 221
                width: 360
                anchors.centerIn: parent
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                implicitHeight: shCol.implicitHeight + 36
                visible: opacity > 0.01
                opacity: win.shareOpen ? 1 : 0
                scale: win.shareOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 16 }

                ColumnLayout {
                    id: shCol
                    width: parent.width - 36
                    x: 18; y: 18
                    spacing: 14

                    Text { text: T.s("modal.share.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }

                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 200; height: 200; radius: 12; color: "white"
                        Image {
                            anchors.centerIn: parent
                            width: 176; height: 176
                            source: win.shareQr
                            cache: false
                            smooth: false
                            visible: win.shareQr.length > 0
                        }
                        Text { anchors.centerIn: parent; visible: win.shareQr.length === 0; text: T.s("modal.share.noqr"); color: "#999999"; font.family: Theme.fontFamily; font.pixelSize: 12 }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 9; color: Theme.surfaceAlt; border.width: 1; border.color: Theme.stroke
                        implicitHeight: 40
                        Text {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                            verticalAlignment: Text.AlignVCenter
                            text: win.shareLink
                            color: Theme.textSub
                            font.family: Theme.fontFamily; font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.fillWidth: true
                            height: 38; radius: 10
                            color: copyHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text { anchors.centerIn: parent; text: T.s("btn.copylink"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: copyHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.copyToClipboard(win.shareLink) }
                        }
                        Item { width: 8 }
                        Rectangle {
                            width: 96; height: 38; radius: 10
                            color: closeShHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.close"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: closeShHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.shareOpen = false }
                        }
                    }
                }
            }

            // оверлей: подтверждение удаления
            MouseArea {
                anchors.fill: parent
                visible: win.confirmOpen
                z: 230
                onClicked: win.confirmOpen = false
            }
            Rectangle {
                id: confirmModal
                z: 231
                width: 360
                anchors.centerIn: parent
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                implicitHeight: cfCol.implicitHeight + 36
                visible: opacity > 0.01
                opacity: win.confirmOpen ? 1 : 0
                scale: win.confirmOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 16 }

                ColumnLayout {
                    id: cfCol
                    width: parent.width - 36
                    x: 18; y: 18
                    spacing: 16

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Rectangle {
                            Layout.alignment: Qt.AlignTop
                            width: 38; height: 38; radius: 19
                            color: Qt.rgba(Theme.red.r, Theme.red.g, Theme.red.b, 0.15)
                            Text { anchors.centerIn: parent; text: String.fromCharCode(0xE74D); font.family: Theme.iconFamily; font.pixelSize: 16; color: Theme.red }
                        }
                        Text {
                            Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter
                            text: win.confirmText
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 14; wrapMode: Text.WordWrap
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 100; height: 38; radius: 10
                            color: cfCancelHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.cancel"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: cfCancelHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.confirmOpen = false }
                        }
                        Item { width: 8 }
                        Rectangle {
                            width: 110; height: 38; radius: 10
                            color: cfDelHover.hovered ? Qt.lighter(Theme.red, 1.1) : Theme.red
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text { anchors.centerIn: parent; text: T.s("btn.delete"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: cfDelHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.doConfirm() }
                        }
                    }
                }
            }

            // оверлей: редактор правила
            MouseArea {
                anchors.fill: parent
                visible: win.ruleEditorOpen
                z: 200
                onClicked: win.ruleEditorOpen = false
            }
            Rectangle {
                id: ruleEditor
                z: 201
                width: 380
                anchors.centerIn: parent
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                implicitHeight: reCol.implicitHeight + 36
                visible: opacity > 0.01
                opacity: win.ruleEditorOpen ? 1 : 0
                scale: win.ruleEditorOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 16 }

                ColumnLayout {
                    id: reCol
                    width: parent.width - 36
                    x: 18; y: 18
                    spacing: 12

                    Text { text: T.s("modal.rule.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }

                    Text { text: T.s("modal.rule.type"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: win.ruleTypes
                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool sel: win.draftType === modelData
                                width: tlabel.width + 22; height: 30; radius: 15
                                color: sel ? Theme.accent : Theme.surfaceAlt
                                border.width: 1; border.color: sel ? Theme.accent : Theme.stroke
                                Behavior on color { ColorAnimation { duration: Theme.durFast } }
                                Text { id: tlabel; anchors.centerIn: parent; text: modelData; color: sel ? "white" : Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.Medium }
                                TapHandler { onTapped: win.draftType = modelData }
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                            }
                        }
                    }

                    Text { text: T.s("modal.rule.value"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    ValueField {
                        Layout.fillWidth: true
                        text: win.draftValue
                        placeholder: T.s("modal.rule.ph")
                        onEdited: win.draftValue = value
                    }

                    Text { text: T.s("modal.rule.action"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    Segmented {
                        Layout.fillWidth: true
                        options: [T.s("seg.proxy"), T.s("seg.direct"), T.s("seg.block")]
                        currentIndex: win.draftAction
                        onSelected: win.draftAction = index
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 96; height: 36; radius: 10
                            color: cancelHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.cancel"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: cancelHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.ruleEditorOpen = false }
                        }
                        Rectangle {
                            width: 116; height: 36; radius: 10
                            readonly property bool ready: win.draftValue.length > 0
                            color: !ready ? Theme.surfaceAlt : (addHover2.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent)
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            Text { anchors.centerIn: parent; text: T.s("btn.add"); color: parent.ready ? "white" : Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: addHover2; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.addDraftRule() }
                        }
                    }
                }
            }

            // оверлей: панель логов ядра (открывается только из Settings)
            MouseArea {
                anchors.fill: parent
                visible: win.logsOpen
                z: 220
                onClicked: win.logsOpen = false
            }
            Rectangle {
                id: logsModal
                z: 221
                anchors.centerIn: parent
                width: Math.min(720, parent.width - 60)
                height: Math.min(520, parent.height - 80)
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                visible: opacity > 0.01
                opacity: win.logsOpen ? 1 : 0
                scale: win.logsOpen ? 1 : 0.96
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 18 }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: T.s("logs.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: String.fromCharCode(0xE711)         // close glyph
                            font.family: Theme.iconFamily; font.pixelSize: 14
                            color: closeLogsHover.hovered ? Theme.red : Theme.textMuted
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            HoverHandler { id: closeLogsHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.logsOpen = false }
                        }
                    }

                    // моноширинный вывод с авто-скроллом вниз
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        radius: Theme.radius
                        color: Qt.darker(Theme.surface, 1.4)
                        border.width: 1; border.color: Theme.stroke
                        Flickable {
                            id: logsFlick
                            anchors.fill: parent
                            anchors.margins: 10
                            contentWidth: width
                            contentHeight: logsText.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ThinScrollBar {}
                            Text {
                                id: logsText
                                width: logsFlick.width
                                text: backend.logsText
                                color: Theme.text
                                font.family: "Consolas, Courier New, monospace"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                textFormat: Text.PlainText
                                onTextChanged: {
                                    if (logsFlick.contentHeight > logsFlick.height)
                                        logsFlick.contentY = logsFlick.contentHeight - logsFlick.height
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: T.s("logs.footer")
                            color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 100; height: 32; radius: 9
                            color: copyLogsHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.copy"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: copyLogsHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.copyToClipboard(backend.logsText) }
                        }
                        Rectangle {
                            width: 96; height: 32; radius: 9
                            color: clearLogsHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.clear"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: clearLogsHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: backend.clearLogs() }
                        }
                    }
                }
            }

            // оверлей: импорт правил маршрутизации из чужих клиентов
            MouseArea {
                anchors.fill: parent
                visible: win.importRulesOpen
                z: 230
                onClicked: win.importRulesOpen = false
            }
            Rectangle {
                id: importRulesModal
                z: 231
                anchors.centerIn: parent
                width: Math.min(640, parent.width - 60)
                height: Math.min(480, parent.height - 80)
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                visible: opacity > 0.01
                opacity: win.importRulesOpen ? 1 : 0
                scale: win.importRulesOpen ? 1 : 0.96
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 18 }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: T.s("modal.imp.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: String.fromCharCode(0xE711)
                            font.family: Theme.iconFamily; font.pixelSize: 14
                            color: closeImpHover.hovered ? Theme.red : Theme.textMuted
                            Behavior on color { ColorAnimation { duration: Theme.durFast } }
                            HoverHandler { id: closeImpHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.importRulesOpen = false }
                        }
                    }

                    Text {
                        text: T.s("modal.imp.hint")
                        color: Theme.textSub; font.family: Theme.fontFamily; font.pixelSize: 11; wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    // область ввода (моноширинная)
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        radius: Theme.radius; color: Qt.darker(Theme.surface, 1.4)
                        border.width: 1; border.color: Theme.stroke
                        Flickable {
                            id: impFlick
                            anchors.fill: parent
                            anchors.margins: 8
                            contentWidth: width
                            contentHeight: impEdit.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ThinScrollBar {}
                            TextEdit {
                                id: impEdit
                                width: impFlick.width
                                text: win.importDraft
                                onTextChanged: win.importDraft = text
                                color: Theme.text
                                font.family: "Consolas, Courier New, monospace"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                textFormat: TextEdit.PlainText
                                selectByMouse: true
                                selectByKeyboard: true
                                persistentSelection: true
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 116; height: 32; radius: 9
                            color: clipImpHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.fromclip"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: clipImpHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { var n = backend.importRulesFromClipboard(); if (n > 0) win.importRulesOpen = false } }
                        }
                        Rectangle {
                            width: 136; height: 32; radius: 9
                            color: doImpHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                            Text { anchors.centerIn: parent; text: T.s("btn.doimport"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: doImpHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { var n = backend.importRulesText(win.importDraft); if (n > 0) win.importRulesOpen = false } }
                        }
                    }
                }
            }

            // оверлей: новый профиль маршрутизации
            MouseArea {
                anchors.fill: parent
                visible: win.newProfileOpen
                z: 240
                onClicked: win.newProfileOpen = false
            }
            Rectangle {
                id: newProfileModal
                z: 241
                width: 380
                anchors.centerIn: parent
                radius: Theme.radiusLg
                color: Theme.surface
                border.width: 1; border.color: Theme.stroke
                implicitHeight: npCol.implicitHeight + 36
                visible: opacity > 0.01
                opacity: win.newProfileOpen ? 1 : 0
                scale: win.newProfileOpen ? 1 : 0.94
                Behavior on opacity { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }
                layer.enabled: true
                layer.effect: MultiEffect { shadowEnabled: true; shadowColor: Theme.shadow; shadowBlur: 1.0; shadowVerticalOffset: 16 }

                ColumnLayout {
                    id: npCol
                    width: parent.width - 36
                    x: 18; y: 18
                    spacing: 10
                    Text { text: T.s("modal.profile.title"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Text { text: T.s("modal.sub.name"); color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1; font.family: Theme.fontFamily; Layout.topMargin: 2 }
                    ValueField { Layout.fillWidth: true; align: TextInput.AlignLeft; text: win.newProfileName; placeholder: T.s("modal.profile.ph"); onEdited: win.newProfileName = value }
                    Text {
                        text: T.s("modal.profile.hint")
                        color: Theme.textMuted; font.family: Theme.fontFamily; font.pixelSize: 11; wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    RowLayout {
                        Layout.fillWidth: true; Layout.topMargin: 6
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 96; height: 36; radius: 10
                            color: cancelNPHover.hovered ? Theme.hover : "transparent"
                            border.width: 1; border.color: Theme.stroke
                            Text { anchors.centerIn: parent; text: T.s("btn.cancel"); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13 }
                            HoverHandler { id: cancelNPHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: win.newProfileOpen = false }
                        }
                        Rectangle {
                            width: 110; height: 36; radius: 10
                            color: createNPHover.hovered ? Qt.lighter(Theme.accent, 1.1) : Theme.accent
                            Text { anchors.centerIn: parent; text: T.s("btn.create"); color: "white"; font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                            HoverHandler { id: createNPHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { win.createProfile(win.newProfileName); win.newProfileOpen = false } }
                        }
                    }
                }
            }

            // тост — снизу, мягко выезжает вверх
            Toast {
                id: toast
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 18
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(440, parent.width - 48)
            }

            // Drag-and-drop импорт: WireGuard .conf или текст с ссылками vless://...
            DropArea {
                id: dropArea
                anchors.fill: parent
                keys: ["text/uri-list"]
                onEntered: function(drag) { drag.accept() }
                onDropped: function(drop) {
                    for (var i = 0; i < drop.urls.length; i++) {
                        var p = drop.urls[i].toString().replace(/^file:\/+/, "")
                        p = decodeURIComponent(p)
                        backend.importFromFile(p)
                    }
                    drop.accept()
                }
            }

            // overlay при перетаскивании — мягко затухает после drop
            Rectangle {
                id: dropOverlay
                anchors.fill: parent
                opacity: dropArea.containsDrag ? 1 : 0
                visible: opacity > 0.01
                color: Qt.rgba(Theme.bg.r, Theme.bg.g, Theme.bg.b, 0.92)
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }

                Rectangle {
                    anchors.centerIn: parent
                    width: 380; height: 200
                    radius: 18
                    color: Theme.surface
                    border.width: 2; border.color: Theme.accent
                    scale: dropArea.containsDrag ? 1 : 0.92
                    Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutBack } }

                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 14
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: String.fromCharCode(0xE898)
                            font.family: Theme.iconFamily; font.pixelSize: 48
                            color: Theme.accent
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: T.s("drop.dropfile")
                            color: Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: T.s("drop.formats")
                            color: Theme.textSub
                            font.family: Theme.fontFamily; font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }

    Timer { id: logoTapTimer; interval: 1500; onTriggered: win.logoTaps = 0 }

    Connections {
        target: backend
        function onNotify(message, kind) { toast.show(message, kind) }
        function onCurrentGroupChanged() {
            win.applySubscriptionConfig()
            if (win.managedSub.length > 0)
                toast.show(T.s("sub.applied") + win.managedSub + "»", "info")
        }
        // импортированные правила маршрутизации — добавляем в конец списка
        function onRulesImported(rules, fmt) {
            if (rules && rules.length > 0)
                win.routeRules = win.routeRules.concat(rules)
        }
    }
}
