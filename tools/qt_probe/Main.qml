import QtQuick
import QtQuick.Controls
import QtQuick.Effects

ApplicationWindow {
    id: window
    visible: true
    width: 2560; height: 1440
    color: "#101116"
    title: "Estante · prototipo Qt Quick · sin lanzamiento de juegos"
    property var games: probe.entries
    property var game: games[probe.selected]
    property bool split: false
    property int coverWidth: 315
    property int coverHeight: 315
    property real dim: 0.5
    property real blurAmount: 0
    property real pixelRatio: Screen.devicePixelRatio

    Repeater {
        model: window.split ? 2 : 1
        delegate: Item {
            required property int index
            width: window.width; height: window.height / (window.split ? 2 : 1)
            y: index * height
            clip: true
            Image {
                id: background
                anchors.fill: parent
                source: index === 0 ? window.game.banner : (window.game.secondary || window.game.banner)
                asynchronous: true; cache: false
                sourceSize: Qt.size(Math.min(3840, Math.max(1920, window.width * window.pixelRatio)), Math.min(2160, Math.max(1080, window.height * window.pixelRatio)))
                fillMode: Image.PreserveAspectCrop
                layer.enabled: window.blurAmount > 0
                layer.effect: MultiEffect { blurEnabled: true; blur: window.blurAmount; blurMax: 40 }
            }
        }
    }
    Rectangle { anchors.fill: parent; color: "black"; opacity: window.dim }
    Rectangle {
        x: (window.width-width)/2; y: 16
        width: Math.min(960, window.width-32); height: 64; radius: 22
        color: "#da20232a"; border.color: "#708b929e"
        Row {
            anchors.centerIn: parent; spacing: 18
            Label { text: "Estante · Qt Quick"; color: "white"; font.pixelSize: 22 }
            Label { text: games.length + " juegos · prueba aislada"; color: "#c4cad2"; font.pixelSize: 20 }
            Button { text: "Salir"; onClicked: window.close() }
        }
    }
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.max(96, (window.height-220-height)/2); spacing: 16
        Image {
            anchors.horizontalCenter: parent.horizontalCenter
            height: Math.max(140, Math.min(window.coverHeight, window.height-420)); width: height*window.coverWidth/window.coverHeight
            source: window.game.cover
            sourceSize: Qt.size(width*window.pixelRatio, height*window.pixelRatio)
            asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(window.width-40, 1000)
            text: window.game.title; horizontalAlignment: Text.AlignHCenter
            color: "white"; font.pixelSize: 30; elide: Text.ElideRight
        }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: "← → / D-pad · mantén pulsado para recorrer"; color: "#dddddd" }
    }
    ListView {
        id: strip
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 28 }
        width: Math.min(1800, window.width)
        height: 180
        orientation: ListView.Horizontal
        model: window.games
        currentIndex: probe.selected
        highlightRangeMode: ListView.StrictlyEnforceRange
        preferredHighlightBegin: width/2-180
        preferredHighlightEnd: width/2+180
        highlightMoveDuration: 130
        reuseItems: true; cacheBuffer: 0; clip: true
        delegate: Item {
            required property var modelData
            required property int index
            width: 360; height: strip.height
            Image {
                anchors.centerIn: parent
                width: 320; height: 150
                source: modelData.logo || modelData.cover
                sourceSize: Qt.size(width*window.pixelRatio, height*window.pixelRatio)
                asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit
                opacity: index === probe.selected ? 1 : 0.5
            }
            TapHandler { onTapped: probe.select(index) }
        }
    }
    Item {
        focus: true
        Keys.onRightPressed: probe.move(1)
        Keys.onLeftPressed: probe.move(-1)
        Keys.onEscapePressed: window.close()
    }
}
