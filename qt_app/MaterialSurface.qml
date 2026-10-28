import QtQuick

Rectangle {
    id: surface
    property QtObject theme: ConsoleTheme {}
    property real elevation: 1
    color: theme.surface
    radius: 16
    border.width: elevation > 0 ? 1 : 0
    border.color: Qt.alpha(theme.text, 0.08)
    Rectangle {
        x: 0; y: surface.elevation*2
        width: parent.width; height: parent.height
        radius: surface.radius
        color: Qt.alpha(surface.theme.shadow, 0.18)
        visible: surface.elevation > 0
        z: -1
    }
}
