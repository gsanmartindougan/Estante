import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item {
    id: bridge
    required property var controller
    property var target: null
    property bool openingBuiltin: false
    signal settingsRequested()
    anchors.fill: parent
    visible: openingBuiltin || (builtin.item && builtin.item.visible) || controller.nativeKeyboard.active || controller.nativeKeyboard.notice.length>0
    z: 1000
    function openFor(item) {
        target=item
        item.forceActiveFocus()
        Qt.callLater(function() { if (bridge.target) bridge.controller.nativeKeyboard.showFor(bridge.target) })
    }
    function openBuiltin(item) {
        const field=item || controller.nativeKeyboard.inputTarget || target
        if (!field || field.text===undefined) return
        controller.nativeKeyboard.hide()
        target=field
        openingBuiltin=true
        builtin.active=true
        Qt.callLater(function() {
            if (builtin.item && bridge.target) builtin.item.openFor(bridge.target)
            else builtin.active=false
            bridge.openingBuiltin=false
        })
    }
    function navigate(action) {
        if (builtin.item && builtin.item.visible) { builtin.item.navigate(action); return }
        if (openingBuiltin) return
        if (action==="back" || action==="search") { controller.nativeKeyboard.hide(); if (target) target.forceActiveFocus() }
        else if (action==="confirm" && controller.nativeKeyboard.notice.length) { controller.nativeKeyboard.hide(); settingsRequested() }
    }
    Connections { target: bridge.controller.nativeKeyboard; function onBuiltinRequested(field) { bridge.openBuiltin(field) } }
    Loader {
        id: builtin
        active: false
        sourceComponent: VirtualKeyboard {
            parent: bridge.parent
            controller: bridge.controller
            onFinished: {
                bridge.controller.nativeKeyboard.hide()
                bridge.target=null
                Qt.callLater(function() { if (builtin.item && !builtin.item.visible) builtin.active=false })
            }
        }
    }
    MaterialSurface {
        visible: bridge.controller.nativeKeyboard.notice.length>0 && !(builtin.item && builtin.item.visible)
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 24 }
        width: Math.min(740,parent.width-48)
        height: body.implicitHeight+32
        ColumnLayout {
            id: body
            x: 16; y: 16; width: parent.width-32; spacing: 14
            Label { text: qsTr("Teclado del sistema"); font.bold: true }
            Label { Layout.fillWidth: true; text: bridge.controller.nativeKeyboard.notice; wrapMode: Text.WordWrap }
            RowLayout {
                GlassButton { text: qsTr("Usar teclado de Estante"); onClicked: bridge.openBuiltin(bridge.controller.nativeKeyboard.inputTarget) }
                GlassButton { text: qsTr("Configurar teclado"); onClicked: { bridge.controller.nativeKeyboard.hide(); bridge.settingsRequested() } }
                GlassButton { text: qsTr("Cerrar"); onClicked: bridge.controller.nativeKeyboard.hide() }
            }
        }
    }
}
