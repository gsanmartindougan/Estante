import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation
Control {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "combo"
    property var model: []
    property int currentIndex: 0
    readonly property int count: model.length
    readonly property string currentText: count && currentIndex>=0 ? String(model[currentIndex]) : ""
    readonly property bool choosing: choices.visible
    property int optionIndex: Math.max(0,currentIndex)
    signal activated(int index)
    implicitHeight: 44
    implicitWidth: 180
    function openChoices() {
        if (!count) return
        Navigation.trackCombo(control)
        optionIndex=Math.max(0,currentIndex)
        choices.open()
        focusOption()
    }
    function focusOption() {
        Qt.callLater(function() { let option=options.itemAt(optionIndex); if (option) option.forceActiveFocus() })
    }
    function navigateChoice(action) {
        if (!choosing) return false
        if (action==="back") { choices.close(); forceActiveFocus(); return true }
        if (action==="confirm") { choose(optionIndex); return true }
        if (["up","down","left","right"].indexOf(action)>=0) {
            optionIndex=(optionIndex+(action==="up" || action==="left" ? -1 : 1)+count)%count
            focusOption()
        }
        return true
    }
    function choose(index) {
        currentIndex=index; activated(index); choices.close(); forceActiveFocus()
    }
    background: Rectangle {
        radius: 4; color: control.palette.base
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.palette.accent : Qt.alpha(control.palette.text,0.25)
    }
    contentItem: RowLayout {
        spacing: 12
        Label { text: control.currentText; Layout.fillWidth: true; leftPadding: 12; elide: Text.ElideRight }
        Label { text: "⌄"; rightPadding: 12; font.pixelSize: 20 }
    }
    TapHandler { onTapped: control.openChoices() }
    Keys.onReturnPressed: openChoices()
    Keys.onSpacePressed: openChoices()
    Popup {
        id: choices
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(560,parent.width-64)
        padding: 20
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: MaterialSurface {}
        contentItem: ColumnLayout {
            spacing: 8
            Repeater {
                id: options
                model: control.model
                delegate: RadioDelegate {
                    required property string modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: 48
                    text: modelData
                    leftPadding: 52; rightPadding: 16
                    contentItem: Text { text: parent.text; font: parent.font; color: control.palette.text; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                    checked: index===control.currentIndex
                    highlighted: index===control.optionIndex
                    indicator: Rectangle {
                        implicitWidth: 26; implicitHeight: 26; radius: 13
                        x: 12; y: (parent.height-height)/2
                        color: "transparent"; border.width: 2; border.color: control.palette.accent
                        Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: control.palette.accent; visible: index===control.currentIndex }
                    }
                    onClicked: control.choose(index)
                    background: Rectangle { radius: 10; color: parent.highlighted ? Qt.alpha(control.palette.accent,0.22) : "transparent"; border.width: parent.activeFocus ? 2 : 0; border.color: control.palette.accent }
                }
            }
        }
    }
}
