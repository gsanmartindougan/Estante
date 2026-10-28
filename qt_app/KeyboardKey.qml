import QtQuick
import QtQuick.Controls
Button {
    id: key
    property bool selected: false
    property bool suggested: false
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    implicitHeight: 48
    Accessible.name: text
    contentItem: Text {
        text: key.text
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        font.pixelSize: 19; font.bold: key.selected || key.suggested
        color: key.selected || key.suggested ? key.palette.highlightedText : key.palette.buttonText
    }
    background: Rectangle {
        radius: 10
        color: key.selected || key.suggested ? key.palette.highlight : Qt.tint(key.palette.button,Qt.alpha(key.palette.buttonText,.08))
        border.width: key.selected ? 2 : 1
        border.color: key.selected ? key.palette.windowText : Qt.alpha(key.palette.buttonText,.12)
        Rectangle { anchors.fill: parent; radius: parent.radius; color: key.palette.buttonText; opacity: key.down ? .18 : key.hovered ? .08 : 0 }
    }
}
