pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation
ColumnLayout {
    id: pane
    required property var manager
    required property var controller
    signal saveRequested()
    function save() { if (!manager.busy) saveRequested() }
    spacing: 16
    Label { text: qsTr("Categorías"); font.pixelSize: 24; font.bold: true }
    Label { text: qsTr("Gestiona los juegos, el orden y la categoría principal."); opacity: 0.6 }
    function navigateSettings(action,keyboard,focused) {
        if (focused && focused.sectionId!==undefined && action==="right") { createHeader.focusFirst(); return true }
        let gameList=focused
        while (gameList && gameList.gamepadKind!=="category-games") gameList=gameList.parent
        if (gameList) {
            focused=gameList
            if (action==="confirm") { focused.toggleCurrent(); return true }
            if (action==="down" && focused.currentIndex<focused.count-1 || action==="up" && focused.currentIndex>0) {
                focused.currentIndex+=action==="down" ? 1 : -1
                focused.positionViewAtIndex(focused.currentIndex,ListView.Contain);return true
            }
        }
        return false
    }
    // Focus enters through the first collapsible group.
    Item { id: createHeader; function focusFirst() { let controls=Navigation.controls(scroll); if (controls.length) controls[0].forceActiveFocus() } }
    ScrollView {
        id: scroll
        Layout.fillWidth: true; Layout.fillHeight: true
        contentWidth: availableWidth; clip: true
        RowLayout {
            width: scroll.availableWidth; spacing: 24
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 0; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                spacing: 16
                SettingsCard {
                    title: qsTr("Nueva categoría"); key: "new"
                    body: ColumnLayout {
                        spacing: 12
                        GlassField { id: newName; objectName: "newCategoryName"; Layout.fillWidth: true; placeholderText: qsTr("Nueva categoría") }
                        GlassButton { text: qsTr("Crear categoría"); objectName: "createCategory"; Layout.fillWidth: true; highlighted: true; enabled: !pane.manager.busy && newName.text.trim().length>0; onClicked: pane.manager.category("create",newName.text,"") }
                    }
                }
                SettingsCard {
                    title: qsTr("Categoría principal"); key: "primary"
                    body: ColumnLayout {
                        spacing: 8
                        Label { text: qsTr("Se abre al iniciar Estante. Si no eliges otra, se usa Todos."); opacity: 0.6; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        Repeater {
                            model: ["",...pane.manager.categoryNames]
                            delegate: SettingsRadio {
                                required property string modelData
                                objectName: "primaryCategory:"+modelData
                                text: modelData || qsTr("Todos"); checked: pane.manager.primaryCategory===modelData; autoExclusive: false
                                enabled: !pane.manager.busy; Layout.fillWidth: true
                                onClicked: pane.manager.category("primary",modelData,"")
                            }
                        }
                    }
                }
                SettingsCard {
                    title: qsTr("Iconos de categorías"); key: "icons"
                    body: ColumnLayout {
                        spacing: 12
                        GlassCombo { id: iconCategory; Layout.fillWidth: true; model: [qsTr("Todos"),...pane.manager.categoryNames] }
                        GlassField { id: iconPath; Layout.fillWidth: true; placeholderText: qsTr("Ruta del icono local") }
                        RowLayout {
                            GlassButton { text: qsTr("Usar icono local"); onClicked: pane.manager.importIcon(iconCategory.currentIndex>0 ? iconCategory.currentText : "",iconPath.text) }
                            GlassButton { text: qsTr("Quitar icono"); onClicked: pane.manager.importIcon(iconCategory.currentIndex>0 ? iconCategory.currentText : "","") }
                        }
                        GlassCombo { id: provider; Layout.fillWidth: true; model: ["Bootstrap Icons","Iconify"] }
                        GlassField { id: query; Layout.fillWidth: true; placeholderText: qsTr("Buscar icono (en inglés)") }
                        GlassButton { text: qsTr("Buscar iconos"); enabled: !pane.manager.busy; onClicked: pane.manager.searchIcons(provider.currentIndex===0 ? "bootstrap" : "iconify",query.text) }
                        ListView {
                            Layout.fillWidth: true; Layout.preferredHeight: Math.min(240,contentHeight); clip: true; model: pane.manager.results; cacheBuffer: 0
                            delegate: GlassButton {
                                required property var modelData
                                required property int index
                                width: ListView.view.width; text: modelData.name+" · "+(modelData.author || "")+" · "+(modelData.license || "")
                                onClicked: pane.manager.chooseIcon(index,iconCategory.currentIndex>0 ? iconCategory.currentText : "")
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.preferredWidth: 0; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                SettingsCard {
                    title: qsTr("Categorías"); key: "categories"
                    body: ColumnLayout {
                        spacing: 12
                        Repeater {
                            model: pane.manager.categoryNames
                            delegate: SettingsCard {
                                id: categoryCard
                                required property string modelData
                                required property int index
                                title: modelData; key: modelData
                                body: ColumnLayout {
                                    property bool deleting: false
                                    spacing: 10
                                    GlassField { id: rename; Layout.fillWidth: true; text: categoryCard.modelData }
                                    RowLayout {
                                        GlassButton { text: qsTr("Renombrar"); Layout.fillWidth: true; enabled: !pane.manager.busy; onClicked: pane.manager.category("rename",rename.text,categoryCard.modelData) }
                                        GlassButton { text: parent.parent.deleting ? qsTr("Confirmar eliminación") : qsTr("Eliminar"); Layout.fillWidth: true; enabled: !pane.manager.busy; onClicked: { if (parent.parent.deleting) pane.manager.category("delete",categoryCard.modelData,categoryCard.modelData); else parent.parent.deleting=true } }
                                    }
                                    RowLayout {
                                        GlassButton { text: qsTr("Subir"); Layout.fillWidth: true; enabled: !pane.manager.busy && categoryCard.index>0; onClicked: pane.manager.category("up",categoryCard.modelData,"") }
                                        GlassButton { text: qsTr("Bajar"); Layout.fillWidth: true; enabled: !pane.manager.busy && categoryCard.index<pane.manager.categoryNames.length-1; onClicked: pane.manager.category("down",categoryCard.modelData,"") }
                                    }
                                    Label { text: qsTr("Juegos de la categoría"); font.bold: true }
                                    GlassField { id: search; Layout.fillWidth: true; placeholderText: qsTr("Buscar juegos…") }
                                    ListView {
                                        id: games
                                        objectName: "categoryGames:"+categoryCard.modelData
                                        property bool gamepadFocusable: true
                                        property string gamepadKind: "category-games"
                                        function toggleCurrent() { let row=model[currentIndex]; if (row && !pane.manager.busy) { restoreIdentity=row.id; pane.manager.setCategoryMember(categoryCard.modelData,row.id,!row.member) } }
                                        Layout.fillWidth: true; Layout.preferredHeight: 260
                                        model: { let revision=pane.manager.categoryNames; return pane.manager.categoryGames(categoryCard.modelData,search.text) }
                                        clip: true; cacheBuffer: 0; reuseItems: true
                                        property string selectedIdentity: ""
                                        property string restoreIdentity: ""
                                        onCurrentIndexChanged: if (!restoreIdentity && currentIndex>=0 && currentIndex<count) selectedIdentity=model[currentIndex].id
                                        onModelChanged: Qt.callLater(function() {
                                            if (!games) return
                                            let found=-1
                                            for (let i=0;i<games.count;i++) if (games.model[i].id===(games.restoreIdentity || games.selectedIdentity)) { found=i;break }
                                            games.currentIndex=found>=0 ? found : games.count ? 0 : -1
                                            if (games.currentIndex>=0) games.selectedIdentity=games.model[games.currentIndex].id
                                            games.restoreIdentity=""
                                            if (games.currentIndex>=0) games.positionViewAtIndex(games.currentIndex,ListView.Contain)
                                        })
                                        delegate: GlassCheck {
                                            required property var modelData
                                            required property int index
                                            width: ListView.view.width
                                            gamepadFocusable: false
                                            text: modelData.title; checked: modelData.member
                                            enabled: !pane.manager.busy
                                            onToggled: { games.restoreIdentity=modelData.id; pane.manager.setCategoryMember(categoryCard.modelData,modelData.id,checked) }
                                            background: Rectangle { radius: 8; color: games.activeFocus && games.currentIndex===parent.index ? Qt.alpha(pane.controller.desktopPalette.accent,0.2) : "transparent" }
                                        }
                                        Rectangle { anchors.fill: parent; color: "transparent"; border.width: games.activeFocus ? 2 : 0; border.color: pane.controller.desktopPalette.accent; radius: 10 }
                                    }
                                }
                            }
                        }
                        Label { visible: pane.manager.categoryNames.length===0; text: qsTr("Todavía no hay categorías."); opacity: 0.6 }
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: pane.controller.editorSaveHint; opacity: .6; Layout.fillWidth: true }
        GlassButton { objectName: "saveCategories"; text: qsTr("Guardar categorías"); highlighted: true; enabled: !pane.manager.busy; onClicked: pane.save() }
    }

}
