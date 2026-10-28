import QtQuick
import QtQuick.Controls
CheckBox {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "check"
    implicitHeight: 44
    spacing: 12
    leftPadding: 4
    indicator: Rectangle {
        x: control.leftPadding
        y: (control.height-height)/2
        implicitWidth: 26; implicitHeight: 26
        radius: 6
        color: control.checked ? control.palette.accent : control.palette.base
        border.width: 2
        border.color: control.checked ? control.palette.accent : control.palette.text
        Text {
            anchors.centerIn: parent
            text: "✓"
            visible: control.checked
            color: control.palette.window
            font.pixelSize: 21; font.bold: true
        }
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: -2
        radius: 8
        color: "transparent"
        border.width: 2
        border.color: control.palette.highlight
        visible: control.activeFocus
        z: 10
    }
}
