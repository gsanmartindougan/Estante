import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: card
    required property string title
    property bool expanded: false
    property Component body
    property string key: title
    function focusHeader() { header.forceActiveFocus() }
    Layout.fillWidth: true
    implicitHeight: layout.implicitHeight+32
    radius: 16
    ConsoleTheme { id: theme }
    color: theme.button
    border.color: Qt.alpha(theme.text,0.1)
    ColumnLayout {
        id: layout
        x: 16; y: 16; width: parent.width-32; spacing: 12
        Button {
            id: header
            objectName: "categoryHeader:"+card.key
            property bool gamepadFocusable: true
            property string gamepadKind: "button"
            Layout.fillWidth: true; implicitHeight: 40
            onClicked: card.expanded=!card.expanded
            contentItem: RowLayout {
                Label { text: card.title; font.pixelSize: 18; font.bold: true; Layout.fillWidth: true; color: header.activeFocus ? header.palette.window : header.palette.text }
                Label { text: card.expanded ? "⌄" : "›"; color: header.activeFocus ? header.palette.window : header.palette.text }
            }
            background: Rectangle { radius: 10; color: header.activeFocus ? header.palette.text : "transparent"; border.width: header.activeFocus ? 2 : 0; border.color: header.palette.accent }
        }
        Loader { Layout.fillWidth: true; active: card.expanded; visible: active; sourceComponent: card.body }
    }
}
