import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "button"
    implicitHeight: 36
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: 16
    rightPadding: 16
    contentItem: Text {
        text: control.text
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: control.highlighted ? control.palette.highlightedText : control.palette.buttonText
        opacity: control.enabled ? 1 : 0.45
    }
    background: Rectangle {
        radius: 8
        color: control.highlighted ? control.palette.highlight : Qt.tint(control.palette.button,Qt.alpha(control.palette.buttonText,0.1))
        border.width: 1
        border.color: Qt.alpha(control.palette.buttonText,0.12)
        opacity: control.enabled ? 1 : 0.55
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: control.highlighted ? control.palette.highlightedText : control.palette.buttonText
            opacity: control.down ? 0.16 : control.hovered ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: 120 } }
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
