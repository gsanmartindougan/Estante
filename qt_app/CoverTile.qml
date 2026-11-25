import QtQuick
import QtQuick.Effects
Rectangle {
    property QtObject theme: ConsoleTheme {}
    id: tile
    required property var appearance
    property url imageSource
    property bool selected: false
    property bool listMode: false
    property bool logoMode: false
    property bool slightCorners: false
    property real decodeWidth: width
    property real decodeHeight: height
    signal chosen()
    color: selected && !listMode ? Qt.alpha(theme.highlight, 0.22) : "transparent"
    radius: appearance.ring.focus_ring_radius
    border.width: selected && !listMode && appearance.ring.focus_ring_enabled ? appearance.ring.focus_ring_width : 0
    border.color: appearance.ring.focus_ring_color
    Item {
        id: artworkLayer
        anchors.fill: parent
        anchors.margins: Math.max(8, tile.listMode ? 2 : tile.border.width + 2)
        layer.enabled: tile.listMode && tile.selected
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: tile.appearance.ring.focus_ring_enabled && !Qt.colorEqual(tile.appearance.ring.focus_ring_color, "#ffffff") ? tile.appearance.ring.focus_ring_color : tile.theme.highlight
            shadowOpacity: 0.48 + Math.min(8, tile.appearance.ring.focus_ring_width) * 0.04
            shadowBlur: 0.8
            shadowVerticalOffset: 4
            shadowScale: 1.04
        }
        RoundedImage {
            objectName: "tileArtwork"
            cornerRadius: tile.logoMode ? 0 : tile.slightCorners ? 4 : tile.appearance.radius
            anchors.fill: parent
            source: tile.imageSource
            sourceSize: Qt.size(Math.max(1,tile.decodeWidth-2*Math.max(8,tile.border.width+2))*Screen.devicePixelRatio,Math.max(1,tile.decodeHeight-2*Math.max(8,tile.border.width+2))*Screen.devicePixelRatio)
            fillMode: Image.PreserveAspectFit
            asynchronous: true; cache: false
            opacity: tile.selected ? 1 : 0.65
            Behavior on opacity { NumberAnimation { duration: 150 } }
        }
    }
    Behavior on color { ColorAnimation { duration: 150 } }
    Rectangle {
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 3 }
        width: Math.min(36, parent.width*0.3); height: 3; radius: 1.5
        color: theme.highlight
        visible: tile.selected
    }
    TapHandler { onTapped: tile.chosen() }
}
