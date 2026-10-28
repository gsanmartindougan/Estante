import QtQuick
Rectangle {
    property QtObject theme: ConsoleTheme {}
    id: tile
    required property var appearance
    property url imageSource
    property bool selected: false
    property bool logoMode: false
    property real decodeWidth: width
    property real decodeHeight: height
    signal chosen()
    color: selected ? Qt.alpha(theme.highlight, 0.22) : "transparent"
    radius: appearance.ring.focus_ring_radius
    border.width: selected && appearance.ring.focus_ring_enabled ? appearance.ring.focus_ring_width : 0
    border.color: appearance.ring.focus_ring_color
    RoundedImage {
        objectName: "tileArtwork"
        cornerRadius: tile.logoMode ? 0 : tile.appearance.radius
        anchors.fill: parent; anchors.margins: Math.max(8,tile.border.width+2)
        source: tile.imageSource
        sourceSize: Qt.size(Math.max(1,tile.decodeWidth-2*Math.max(8,tile.border.width+2))*Screen.devicePixelRatio,Math.max(1,tile.decodeHeight-2*Math.max(8,tile.border.width+2))*Screen.devicePixelRatio)
        fillMode: Image.PreserveAspectFit
        asynchronous: true; cache: false
        opacity: tile.selected ? 1 : 0.65
        Behavior on opacity { NumberAnimation { duration: 150 } }
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
