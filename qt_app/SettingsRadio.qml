import QtQuick
import QtQuick.Controls
RadioButton {
    id: option
    property bool gamepadFocusable: true
    property string gamepadKind: "button"
    implicitHeight: 40
    leftPadding: 28
    autoExclusive: false
    indicator: Rectangle {
        x: 2; y: (option.height-height)/2
        width: 20; height: 20; radius: 10
        color: option.checked ? option.palette.accent : "transparent"
        border.width: 2; border.color: option.checked ? option.palette.accent : Qt.alpha(option.palette.text,0.25)
        Rectangle { anchors.centerIn: parent; width: 7; height: 7; radius: 4; color: option.palette.window; visible: option.checked }
    }
    background: Rectangle { radius: 8; color: option.activeFocus ? Qt.alpha(option.palette.accent,0.12) : "transparent"; border.width: option.activeFocus ? 2 : 0; border.color: option.palette.accent }
}
