import QtQuick
import QtQuick.Controls
Slider {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "slider"
    property bool gamepadAdjusting: false
    onActiveFocusChanged: if (!activeFocus) gamepadAdjusting=false
    implicitHeight: 40
    stepSize: 1
    ToolTip.visible: activeFocus
    ToolTip.text: gamepadAdjusting ? qsTr("← / →: ajustar · A / B: terminar") : qsTr("A: ajustar")
    background: Rectangle {
        x: control.leftPadding
        y: (control.height-height)/2
        width: control.availableWidth; height: 6; radius: 3
        color: Qt.alpha(control.palette.text,0.22)
        Rectangle { width: control.visualPosition*parent.width; height: parent.height; radius: 3; color: control.palette.accent }
    }
    handle: Rectangle {
        x: control.leftPadding+control.visualPosition*(control.availableWidth-width)
        y: (control.height-height)/2
        width: 22; height: 22; radius: 11
        color: control.gamepadAdjusting ? control.palette.accent : control.palette.buttonText
        border.width: 2; border.color: control.palette.accent
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
