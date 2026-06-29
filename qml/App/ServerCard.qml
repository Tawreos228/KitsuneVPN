import QtQuick
import QtQuick.Layouts
import App

// Карточка сервера. Жёсткое выравнивание: имя тянется и обрезается «…»,
// а пинг / сигнальные бары / кружок выбора стоят в фиксированных правых колонках —
// поэтому ничего не «съезжает» ни в узком дропдауне, ни при 3-значном пинге.
Item {
    id: card
    height: 66

    property string code
    property string country
    property string city
    property int ping
    property real speedMbps: 0
    property bool isAwg: false           // AmneziaWG-сервер — рисуем мини-чип «AWG» рядом с city
    readonly property string fullName: country + " · " + city
    readonly property bool selected: backend.server === fullName
    property bool editable: false
    property int rowIndex: -1
    property bool fav: false
    signal picked()
    signal edit()
    signal favToggle()
    signal context(real gx, real gy)

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: Theme.radius
        color: tap.pressed ? Theme.surfaceAlt
             : hover.hovered ? Theme.hover
             : Theme.surface
        border.width: 1
        border.color: card.selected ? Qt.rgba(0.04, 0.52, 1.0, 0.55) : Theme.stroke
        Behavior on color { ColorAnimation { duration: Theme.durFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.durBase } }

        scale: tap.pressed ? 0.99 : 1.0
        Behavior on scale { NumberAnimation { duration: Theme.durFast; easing.type: Easing.OutCubic } }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 18
            spacing: 14

            // бейдж страны
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                width: 38; height: 28; radius: 7
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.lighter(Theme.accent, 1.25) }
                    GradientStop { position: 1.0; color: Theme.accent }
                }
                Text {
                    anchors.centerIn: parent
                    text: card.code
                    color: "white"
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    font.weight: Font.Bold
                    font.letterSpacing: 0.5
                }
            }

            // имя + город (тянется, обрезается)
            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: card.country
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text {
                        text: card.city
                        color: Theme.textMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    // AWG-чип: маленький бейдж справа от city для AmneziaWG-серверов
                    Rectangle {
                        visible: card.isAwg
                        implicitHeight: 16
                        implicitWidth: awgLbl.implicitWidth + 10
                        radius: 8
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.18)
                        border.width: 1
                        border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45)
                        Text {
                            id: awgLbl
                            anchors.centerIn: parent
                            text: "AWG"
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: 9
                            font.weight: Font.Bold
                            font.letterSpacing: 0.5
                        }
                    }
                }
            }

            // избранное (звезда: золотая если в избранном, контур на hover)
            Item {
                Layout.alignment: Qt.AlignVCenter
                visible: card.editable
                implicitWidth: 22; implicitHeight: 22
                Text {
                    anchors.centerIn: parent
                    text: card.fav ? "★" : "☆"
                    font.pixelSize: 16
                    color: card.fav ? Theme.amber : Theme.textMuted
                    opacity: (card.fav || hover.hovered || starMouse.containsMouse) ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                }
                MouseArea { id: starMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: card.favToggle() }
            }

            // карандаш-редактирование (на hover)
            Item {
                Layout.alignment: Qt.AlignVCenter
                visible: card.editable
                implicitWidth: 22; implicitHeight: 22
                Text {
                    anchors.centerIn: parent
                    text: String.fromCharCode(0xE70F)
                    font.family: Theme.iconFamily
                    font.pixelSize: 15
                    color: penMouse.containsMouse ? Theme.accent : Theme.textMuted
                    opacity: (hover.hovered || penMouse.containsMouse) ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.durFast } }
                }
                MouseArea { id: penMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: card.edit() }
            }

            // speed-badge — показываем если есть свежий замер; цвет — по скорости
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                visible: card.speedMbps > 0
                implicitWidth: spdText.implicitWidth + 12
                implicitHeight: 22
                radius: 11
                readonly property color spdC: card.speedMbps >= 3 ? Theme.green
                                            : card.speedMbps >= 1 ? Theme.amber
                                            :                       Theme.red
                color: Qt.rgba(spdC.r, spdC.g, spdC.b, 0.14)
                border.width: 1; border.color: spdC
                Text {
                    id: spdText
                    anchors.centerIn: parent
                    text: card.speedMbps.toFixed(1) + " MB/s"
                    color: parent.spdC
                    font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.DemiBold
                }
            }

            // пинг — фиксированная колонка, текст к правому краю
            Text {
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 46
                horizontalAlignment: Text.AlignRight
                text: card.ping + " ms"
                color: Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }

            // сигнальные бары — фиксированная ширина
            Row {
                Layout.alignment: Qt.AlignVCenter
                spacing: 3
                Repeater {
                    model: 4
                    delegate: Item {
                        width: 4; height: 22
                        required property int index
                        readonly property int lit: card.ping < 60 ? 4 : card.ping < 100 ? 3 : card.ping < 160 ? 2 : 1
                        readonly property color c: card.ping < 100 ? Theme.green : card.ping < 160 ? Theme.amber : Theme.red
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: 4
                            height: 7 + parent.index * 4.5
                            radius: 2
                            color: parent.index < parent.lit ? parent.c : Theme.strokeHi
                            Behavior on color { ColorAnimation { duration: Theme.durBase } }
                        }
                    }
                }
            }

            // галочка выбора
            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                width: 22; height: 22; radius: 11
                color: card.selected ? Theme.accent : "transparent"
                border.width: card.selected ? 0 : 1.5
                border.color: Theme.strokeHi
                Behavior on color { ColorAnimation { duration: Theme.durBase } }
                Text {
                    anchors.centerIn: parent
                    text: "✓"
                    color: "white"
                    font.pixelSize: 13
                    font.bold: true
                    opacity: card.selected ? 1 : 0
                    scale: card.selected ? 1 : 0.4
                    Behavior on opacity { NumberAnimation { duration: Theme.durBase } }
                    Behavior on scale { NumberAnimation { duration: Theme.durBase; easing.type: Easing.OutBack } }
                }
            }
        }
    }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; onTapped: { backend.selectServer(card.fullName); card.picked() } }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        enabled: card.editable
        onClicked: (mouse) => {
            var p = card.mapToItem(null, mouse.x, mouse.y)
            card.context(p.x, p.y)
        }
    }
}
