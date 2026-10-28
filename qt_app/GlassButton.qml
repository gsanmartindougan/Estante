import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "button"
    readonly property color focusFill: highlighted ? palette.highlight : palette.button
    readonly property bool darkFocusFill: focusFill.r*0.2126+focusFill.g*0.7152+focusFill.b*0.0722 < 0.5
    readonly property color focusInk: darkFocusFill ? "#ffffff" : "#111111"
    implicitHeight: 44
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
        radius: height/2
        color: control.highlighted ? control.palette.highlight : control.palette.button
        opacity: control.enabled ? 1 : 0.55
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: control.highlighted ? control.palette.highlightedText : control.palette.buttonText
            opacity: control.down ? 0.16 : control.activeFocus ? 0.12 : control.hovered ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }
    }
    Rectangle {
        objectName: "buttonFocusRing"
        anchors.fill: parent
        anchors.margins: -6
        radius: height/2
        color: "transparent"
        border.width: 3
        border.color: control.focusInk
        visible: control.activeFocus && control.enabled
        z: 10
        Rectangle {
            anchors.fill: parent
            anchors.margins: 3
            radius: height/2
            color: "transparent"
            border.width: 2
            border.color: control.darkFocusFill ? "#111111" : "#ffffff"
        }
    }
}
