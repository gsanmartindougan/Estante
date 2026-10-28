pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation
ColumnLayout {
    id: pane
    ConsoleTheme { id: paneTheme }
    property var colors: ({window: paneTheme.button, text: paneTheme.text})
    required property var manager
    required property var controller
    required property var draft
    property string mode: "global"
    signal edited(string key, var value, var original)
    signal saveRequested()
    signal sidebarRequested()
    property var cards: { let revision=manager.settingSpecs; return manager.settingGroups(mode) }
    spacing: 16
    Label { text: pane.mode==="global" ? qsTr("Ajustes globales") : ({grid:"Grid",carousel:"Carousel",ps5:"Sense",list:qsTr("Lista")})[pane.mode]; font.pixelSize: 24; font.bold: true }
    Label { text: pane.mode==="global" ? qsTr("Preferencias generales, controles y apariencia de la biblioteca.") : qsTr("Estos ajustes se aplican solo a esta apariencia."); opacity: 0.6; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    function focusKeyboard() {
        function find(item) {
            if (item.keyboardGroup===true) { item.expanded=true; item.focusHeader(); reveal(item); return true }
            for (let child of item.children || []) if (find(child)) return true
            return false
        }
        find(pane)
    }
    function save() { if (!manager.busy) saveRequested() }
    function columnControls(index) { return Navigation.controls(columns.itemAt(index)) }
    function focusFirst() { let items=columnControls(0); if (items.length) items[0].forceActiveFocus() }
    function navigateSettings(action,keyboard,focused) {
        if (focused && focused.sectionId!==undefined && action==="right") { focusFirst(); return true }
        let owner=focused
        while (owner && owner.settingsColumn===undefined) owner=owner.parent
        if (!owner) return false
        if (focused.gamepadKind==="slider") {
            if (action==="confirm") { focused.gamepadAdjusting=!focused.gamepadAdjusting; return true }
            if (focused.gamepadAdjusting) {
                if (action==="back") focused.gamepadAdjusting=false
                else if (action==="left" || action==="right") focused.value=Math.max(focused.from,Math.min(focused.to,focused.value+(action==="right" ? 1 : -1)*focused.stepSize))
                return true
            }
        }
        if (owner.compactGroup && !focused.objectName.startsWith("groupHeader:") && focused.gamepadKind && ["left","right","up","down"].indexOf(action)>=0) {
            Navigation.navigate(owner,focused,action,false)
            let next=Navigation.controls(owner).find(item=>item.activeFocus)
            if (next && next!==focused) { reveal(next); return true }
        }
        if (action==="back" && owner.expanded) { owner.expanded=false; owner.focusHeader(); return true }
        if (["up","down","left","right"].indexOf(action)<0) return false
        let items=columnControls(owner.settingsColumn)
        let index=items.indexOf(focused)
        if (action==="up" || action==="down") {
            let next=index+(action==="down" ? 1 : -1)
            if (next<0) pane.sidebarRequested()
            else if (next>=items.length) saveButton.forceActiveFocus()
            else { items[next].forceActiveFocus(); reveal(items[next]) }
            return true
        }
        if (action==="left" && owner.settingsColumn===0) { pane.sidebarRequested(); return true }
        let others=columnControls(action==="right" ? 1 : 0)
        if (!others.length) return true
        let y=focused.mapToItem(pane,0,0).y
        let target=others[0],distance=Infinity
        for (let item of others) { let delta=Math.abs(item.mapToItem(pane,0,0).y-y); if (delta<distance) {target=item;distance=delta} }
        target.forceActiveFocus(); reveal(target); return true
    }
    function reveal(control) {
        let point=control.mapToItem(scroll.contentItem.contentItem,0,0)
        if (point.y<scroll.contentItem.contentY) scroll.contentItem.contentY=point.y
        else if (point.y+control.height>scroll.contentItem.contentY+scroll.height) scroll.contentItem.contentY=point.y+control.height-scroll.height
    }
    ScrollView {
        id: scroll
        Layout.fillWidth: true; Layout.fillHeight: true
        contentWidth: availableWidth
        clip: true
        RowLayout {
            width: scroll.availableWidth; spacing: 24
            Repeater {
                id: columns
                model: 2
                delegate: ColumnLayout {
                    id: column
                    required property int index
                    Layout.fillWidth: true; Layout.preferredWidth: 0; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                    spacing: 12
                    Repeater {
                        model: pane.cards.filter(function(card) {return card.column===column.index})
                        delegate: Rectangle {
                            id: group
                            required property var modelData
                            property int settingsColumn: column.index
                            property bool keyboardGroup: Boolean(modelData.keyboard)
                            property bool compactGroup: Boolean(modelData.compact)
                            property bool expanded: false
                            function focusHeader() { heading.forceActiveFocus() }
                            objectName: "settingsGroup:"+modelData.title
                            Layout.fillWidth: true
                            implicitHeight: groupLayout.implicitHeight+28
                            radius: 16
                            color: Qt.tint(pane.colors.window,Qt.alpha(pane.colors.text,0.035))
                            border.color: Qt.alpha(pane.colors.text,0.1)
                            ColumnLayout {
                                id: groupLayout
                                x: 14; y: 14; width: parent.width-28; spacing: 10
                                Button {
                                    id: heading
                                    property bool gamepadFocusable: true
                                    property string gamepadKind: "button"
                                    objectName: "groupHeader:"+group.modelData.title
                                    Layout.fillWidth: true
                                    implicitHeight: 36
                                    onClicked: group.expanded=!group.expanded
                                    contentItem: RowLayout {
                                        Label { text: group.modelData.title; font.bold: true; font.pixelSize: 18; color: heading.activeFocus ? heading.palette.window : heading.palette.text; Layout.fillWidth: true }
                                        Label { text: group.expanded ? "⌄" : "›"; color: heading.activeFocus ? heading.palette.window : heading.palette.text }
                                    }
                                    background: Rectangle { radius: 10; color: heading.activeFocus ? heading.palette.text : "transparent"; border.width: heading.activeFocus ? 2 : 0; border.color: heading.palette.accent }
                                }
                                Loader {
                                    Layout.fillWidth: true
                                    active: group.expanded
                                    visible: active
                                    sourceComponent: ColumnLayout {
                                        spacing: 14
                                        GridLayout {
                                            id: form
                                            Layout.fillWidth: true
                                            columns: group.compactGroup ? 2 : 1
                                            columnSpacing: 14; rowSpacing: 10
                                        Repeater {
                                            model: group.modelData.rows
                                            delegate: SettingControl {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 0
                                                Layout.preferredWidth: 1
                                                Layout.alignment: Qt.AlignTop
                                                Layout.columnSpan: !group.compactGroup || modelData.type==="bool" || modelData.type==="background" || ["screensaver_dim","screensaver_source"].indexOf(modelData.path[0])>=0 ? form.columns : 1
                                                controller: pane.controller
                                                compact: group.compactGroup
                                                inlineChoices: true
                                                hideLabel: group.modelData.rows.length===1 && modelData.type==="choice"
                                                spec: Object.assign({},modelData,{sectionStart:false,value:pane.draft[JSON.stringify(modelData.path)]!==undefined ? pane.draft[JSON.stringify(modelData.path)] : modelData.value})
                                                onSettingValueChanged: pane.edited(JSON.stringify(modelData.path),settingValue,modelData.value)
                                            }
                                        }
                                        }
                                        ColumnLayout {
                                            visible: Boolean(group.modelData.keyboard)
                                            Layout.fillWidth: true
                                            Label { text: pane.controller.nativeKeyboard.status; wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: .8 }
                                            GlassButton { text: qsTr("Volver a detectar"); onClicked: pane.controller.nativeKeyboard.refresh() }
                                            GlassField { id: keyboardTest; objectName: "systemKeyboardTest"; Layout.fillWidth: true; placeholderText: qsTr("Campo de prueba del teclado…") }
                                            GlassButton { text: qsTr("Probar teclado"); objectName: "testSystemKeyboard"; onClicked: { pane.controller.nativeKeyboard.hide(); keyboardTest.forceActiveFocus(); Qt.callLater(function() { pane.controller.nativeKeyboard.showForChoice(keyboardTest,pane.draft[JSON.stringify(["onscreen_keyboard"])] || pane.controller.settingsMap.onscreen_keyboard || "auto",pane.draft[JSON.stringify(["keyboard_fallback"])]!==undefined ? pane.draft[JSON.stringify(["keyboard_fallback"])] : pane.controller.settingsMap.keyboard_fallback!==false) }) } }
                                            Label { text: qsTr("El teclado de Estante funciona con mando sin depender del compositor. Puedes elegirlo directamente o usarlo si falla el del sistema. No se instala ningún paquete automáticamente."); wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: .6 }
                                        }
                                        Label { text: group.modelData.hint; visible: text.length>0; opacity: 0.6; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                        GlassButton { visible: Boolean(group.modelData.updates); text: qsTr("Comprobar actualizaciones"); onClicked: pane.manager.checkUpdates() }
                                        GlassButton { visible: Boolean(group.modelData.updates); text: qsTr("Instalar actualización del AppImage"); onClicked: pane.manager.updateAppImage() }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: qsTr("D-pad: mover · A: desplegar o elegir · B: plegar o volver")+" · "+pane.controller.editorSaveHint; opacity: 0.6; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        GlassButton { id: saveButton; text: pane.mode==="global" ? qsTr("Guardar globales") : qsTr("Guardar apariencia"); highlighted: true; enabled: !pane.manager.busy; onClicked: pane.save() }
    }
}
