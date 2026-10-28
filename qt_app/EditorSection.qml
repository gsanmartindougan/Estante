import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: card
    property string title
    property QtObject theme: ConsoleTheme {}
    default property alias contents: body.data
    implicitHeight: body.implicitHeight+32
    radius: 16
    color: Qt.alpha(theme.surface, 0.92)
    border.color: Qt.alpha(theme.text, 0.12)
    ColumnLayout {
        id: body
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
        spacing: 12
        Label { text: card.title; font.bold: true; color: card.theme.text }
    }
}
