import QtQuick
import App

// Переключатель темы: солнце ↔ луна ↔ (лиса, если разблокирована пасхалкой 5 тапов по логотипу).
// Локально про unlock не знает — читает win.themeUnlocked (свойство Main.qml).
Item {
    id: root
    // ширина: 62 закрыто (2 позиции) → 94 открыто (3 позиции)
    implicitWidth: unlocked ? 94 : 62
    implicitHeight: 30

    readonly property bool unlocked: (typeof win !== "undefined" && win) ? win.themeUnlocked : false
    readonly property string scheme: Theme.scheme   // "light" | "dark" | "kitsune"

    Behavior on implicitWidth { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutCubic } }

    // три якорные позиции для бегунка
    readonly property int posLight:   3
    readonly property int posDark:    unlocked ? (width / 2 - 12) : (width - 24 - 3)
    readonly property int posKitsune: width - 24 - 3

    function cycle() {
        if (Theme.scheme === "light") Theme.scheme = "dark"
        else if (Theme.scheme === "dark") Theme.scheme = unlocked ? "kitsune" : "light"
        else /* kitsune */ Theme.scheme = "light"
    }

    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: root.scheme === "kitsune" ? "#3A1B4F"
             : root.scheme === "dark"    ? "#2A3156"
             :                              "#9FD0F5"
        Behavior on color { ColorAnimation { duration: Theme.durBase } }

        // звёзды (видны на тёмных схемах)
        Repeater {
            model: 3
            delegate: Rectangle {
                required property int index
                width: 2.5; height: 2.5; radius: 1.25
                color: root.scheme === "kitsune" ? "#FFD9A8" : "white"
                opacity: root.scheme !== "light" ? 0.9 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                x: [13, 19, 15][index]
                y: [9, 17, 22][index]
            }
        }

        // мягкое мерцание под бегунком в режиме «Китсунэ»
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "transparent"
            border.color: "#FF7A2F"
            border.width: 1
            opacity: root.scheme === "kitsune" ? 0.45 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
        }
    }

    // бегунок
    Item {
        id: thumb
        width: 24; height: 24
        y: 3
        x: root.scheme === "light"   ? root.posLight
         : root.scheme === "kitsune" ? root.posKitsune
         :                              root.posDark
        Behavior on x { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutBack } }

        // ── солнце: лучи + жёлтый круг ──────────────────────────────
        Item {
            id: sunWrap
            anchors.fill: parent
            opacity: root.scheme === "light" ? 1 : 0
            scale:   root.scheme === "light" ? 1 : 0.3
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
            Behavior on scale   { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutBack } }
            Repeater {
                model: 8
                delegate: Item {
                    required property int index
                    anchors.centerIn: parent
                    width: 24; height: 24
                    rotation: index * 45
                    Rectangle {
                        width: 2.5; height: 4; radius: 1.25
                        color: "#FFD15C"
                        x: parent.width / 2 - width / 2
                        y: -4.5
                    }
                }
            }
            Rectangle { anchors.fill: parent; radius: width / 2; color: "#FFD15C" }
        }

        // ── луна: серый круг + «прикус» цвета неба ──────────────────
        Item {
            id: moonWrap
            anchors.fill: parent
            opacity: root.scheme === "dark" ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
            Rectangle { anchors.fill: parent; radius: width / 2; color: "#E6EAF5" }
            Rectangle {
                width: 24; height: 24; radius: 12
                color: track.color
                x: 8; y: -7
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
            }
        }

        // ── лиса: морда из примитивов ───────────────────────────────
        Item {
            id: foxWrap
            anchors.fill: parent
            opacity: root.scheme === "kitsune" ? 1 : 0
            scale:   root.scheme === "kitsune" ? 1 : 0.4
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
            Behavior on scale   { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutBack } }

            Canvas {
                id: foxCanvas
                anchors.fill: parent
                antialiasing: true
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var orange = "#FF7A2F"
                    var pink   = "#FFB1A8"
                    var white  = "#FFF6E8"
                    var black  = "#15171C"

                    // уши (треугольники)
                    ctx.fillStyle = orange
                    ctx.beginPath()
                    ctx.moveTo(2, 3); ctx.lineTo(8, 3); ctx.lineTo(6, 10); ctx.closePath(); ctx.fill()
                    ctx.beginPath()
                    ctx.moveTo(16, 3); ctx.lineTo(22, 3); ctx.lineTo(18, 10); ctx.closePath(); ctx.fill()

                    // внутренние уши (розовые)
                    ctx.fillStyle = pink
                    ctx.beginPath()
                    ctx.moveTo(3.5, 4); ctx.lineTo(7, 4); ctx.lineTo(6, 8); ctx.closePath(); ctx.fill()
                    ctx.beginPath()
                    ctx.moveTo(17, 4); ctx.lineTo(20.5, 4); ctx.lineTo(18, 8); ctx.closePath(); ctx.fill()

                    // лицо — закруглённый ромб
                    ctx.fillStyle = orange
                    ctx.beginPath()
                    ctx.moveTo(3, 10)
                    ctx.bezierCurveTo(3, 7.5, 6, 6, 12, 6)
                    ctx.bezierCurveTo(18, 6, 21, 7.5, 21, 10)
                    ctx.bezierCurveTo(21, 16.5, 18, 21, 12, 21)
                    ctx.bezierCurveTo(6, 21, 3, 16.5, 3, 10)
                    ctx.closePath(); ctx.fill()

                    // светлые щёки/морда — две перекрывающиеся окружности
                    ctx.fillStyle = white
                    ctx.beginPath(); ctx.arc(8.5, 16, 4.5, 0, 6.283); ctx.fill()
                    ctx.beginPath(); ctx.arc(15.5, 16, 4.5, 0, 6.283); ctx.fill()

                    // глаза
                    ctx.fillStyle = black
                    ctx.beginPath(); ctx.arc(8.5, 12, 1.4, 0, 6.283); ctx.fill()
                    ctx.beginPath(); ctx.arc(15.5, 12, 1.4, 0, 6.283); ctx.fill()

                    // нос
                    ctx.beginPath(); ctx.arc(12, 16, 1.1, 0, 6.283); ctx.fill()
                }
            }
        }
    }

    // reveal-анимация: когда unlocked флипается false→true, лиса «вспрыгивает»
    // правее старого положения. Width трека уже плавно растёт благодаря Behavior.
    Item {
        id: sparkleAnchor
        x: root.width - 12; y: root.height / 2
        Repeater {
            model: 6
            delegate: Rectangle {
                required property int index
                width: 3; height: 3; radius: 1.5
                color: "#FFC36B"
                x: 0; y: 0
                opacity: 0
                property real ang: index * 60
                ParallelAnimation {
                    id: sparkAnim
                    NumberAnimation { target: parent; property: "x"; from: 0; to: Math.cos(ang * Math.PI / 180) * 18; duration: 600; easing.type: Easing.OutCubic }
                    NumberAnimation { target: parent; property: "y"; from: 0; to: Math.sin(ang * Math.PI / 180) * 18; duration: 600; easing.type: Easing.OutCubic }
                    SequentialAnimation {
                        NumberAnimation { target: parent; property: "opacity"; from: 0; to: 1; duration: 120 }
                        NumberAnimation { target: parent; property: "opacity"; from: 1; to: 0; duration: 480 }
                    }
                }
                Connections {
                    target: root
                    function onUnlockedChanged() { if (root.unlocked) sparkAnim.start() }
                }
            }
        }
    }

    TapHandler { onTapped: root.cycle() }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
