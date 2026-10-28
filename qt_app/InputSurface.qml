import QtQuick

Rectangle {
    id: surface
    required property color fillColor
    required property color inkColor
    required property color accentColor
    property bool focused: false
    property bool hovered: false
    radius: 12
    color: Qt.tint(fillColor, Qt.alpha(inkColor, hovered ? 0.055 : 0.025))
    border.width: focused ? 2 : 1
    border.color: focused ? accentColor : Qt.alpha(inkColor, hovered ? 0.32 : 0.16)
    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 120 } }
}
