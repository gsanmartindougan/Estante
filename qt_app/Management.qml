pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "Gamepad.js" as Navigation

Dialog {
    property QtObject theme: ConsoleTheme {}
    id: panel
    objectName: "managementPanel"
    required property var controller
    property var manager: controller.manager
    property int section: 0
    property int initialArtwork: 0
    property bool metadataSearch: false
    property var settingsDraft: ({})
    property bool deleting: false
    property bool editingLocal: false
    padding: 24
    topPadding: 20
    bottomPadding: 24
    modal: true
    width: Math.min(1440,parent.width-64); height: parent.height-64
    anchors.centerIn: parent
    title: addingLocal ? qsTr("Añadir juego") : gameContext ? qsTr("Editar juego") : qsTr("Ajustes de Estante")
    property bool gameContext: false
    property bool addingLocal: false
    header: Item {
        implicitWidth: 300
        implicitHeight: 68
        Label {
            anchors.fill: parent
            text: panel.title
            leftPadding: 24; rightPadding: 24; topPadding: 24; bottomPadding: 12
            font.pixelSize: 22; font.bold: true
            color: theme.text
            elide: Text.ElideRight
        }
    }
    background: MaterialSurface {
        radius: 24
        color: theme.window
    }
    Overlay.modal: Rectangle { color: Qt.alpha(theme.shadow, 0.45) }
    function focusSection() {
        for (let i=0; i<sectionButtons.count; ++i) {
            let button=sectionButtons.itemAt(i)
            if (button.sectionId===section) { button.forceActiveFocus(); return }
        }
    }
    function revealSidebar(button) {
        let flick = sidebarScroll.contentItem
        let y = button.mapToItem(flick.contentItem,0,0).y
        let margin = 8
        if (y-margin < flick.contentY) flick.contentY = Math.max(0,y-margin)
        else if (y+button.height+margin > flick.contentY+sidebarScroll.availableHeight)
            flick.contentY = y+button.height+margin-sidebarScroll.availableHeight
    }
    closePolicy: Popup.CloseOnEscape
    function openSection(index, editing) { addingLocal=index===0 && !editing; editingLocal=Boolean(editing); gameContext=[0,1,5].indexOf(index)>=0; section=index; deleting=false; open() }
    function openKeyboard() { openSection(4); Qt.callLater(function() { if (page.item && page.item.focusKeyboard) page.item.focusKeyboard() }) }
    function saveSettingsDraft() {
        let values=[]
        for (let key of Object.keys(settingsDraft)) values.push({path:JSON.parse(key),value:settingsDraft[key]})
        manager.saveSettingValues(values)
        if (manager.message==="Ajustes guardados") settingsDraft=({})
    }
    function save() { if (page.item && page.item.save) page.item.save() }
    function navigate(action, keyboard, focused) {
        if (action==="save") { save(); return }
        if (page.item && page.item.navigateSettings && page.item.navigateSettings(action,keyboard,focused)) return
        if (action === "back") { close(); return }
        if (action === "confirm") Navigation.activate(contentItem, focused, keyboard)
        else Navigation.navigate(contentItem, focused, action)
    }
    onSectionChanged: { deleting=false; manager.close() }
    onOpened: focusSection()
    onClosed: manager.close()
    contentItem: ColumnLayout {
        spacing: 18
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 28
            ScrollView {
                id: sidebarScroll
                objectName: "settingsSidebar"
                onAvailableHeightChanged: Qt.callLater(function() {
                    let focused=Navigation.controls(sidebarScroll).find(item=>item.activeFocus)
                    if (focused) panel.revealSidebar(focused)
                })
                Layout.preferredWidth: 196; Layout.fillHeight: true
                contentWidth: availableWidth
                contentHeight: sidebarContent.implicitHeight+16
                clip: true
                ColumnLayout {
                id: sidebarContent
                x: 8; y: 8
                width: sidebarScroll.availableWidth-16
                spacing: 8
            Repeater {
                id: sectionButtons
                model: panel.addingLocal ? [] : panel.gameContext ? [{name: qsTr("Ficha e imágenes"), page: 1}, {name: qsTr("Ejecución"), page: 0}, {name: qsTr("Actividad"), page: 5}] : [{name: qsTr("Globales"), page: 4}, {name: qsTr("Escaneo y scraping"), page: 2}, {name: qsTr("Categorías"), page: 3}, {name: "Grid", page: 8}, {name: "Carousel", page: 9}, {name: "Sense", page: 10}, {name: qsTr("Lista"), page: 7}]
                delegate: GlassButton {
                    required property var modelData
                    Layout.fillWidth: true
                    onActiveFocusChanged: if (activeFocus) panel.revealSidebar(this)
                    property int sectionId: modelData.page
                    Layout.topMargin: !panel.gameContext && modelData.page===8 ? 28 : 0
                    Label { visible: !panel.gameContext && modelData.page===8; text: qsTr("APARIENCIA"); opacity: 0.5; font.pixelSize: 11; x: 8; y: -22 }
                    text: modelData.name
                    highlighted: panel.section === modelData.page
                    onClicked: panel.section=modelData.page
                }
            }
                Label {
                    visible: !panel.gameContext && !panel.addingLocal
                    Layout.topMargin: 18
                    Layout.leftMargin: 8
                    text: qsTr("APLICACIONES")
                    opacity: 0.5; font.pixelSize: 11
                }
                Repeater {
                    model: !panel.gameContext && !panel.addingLocal ? panel.controller.launchers.entries : []
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        GlassButton {
                            readonly property bool closing: parent.modelData.state === "open"
                            objectName: (closing ? "closeLauncher:" : "openLauncher:")+parent.modelData.id
                            onActiveFocusChanged: if (activeFocus) panel.revealSidebar(this)
                            property int sectionId: panel.section
                            Layout.fillWidth: true
                            visible: ["open","closed","error","timeout"].indexOf(parent.modelData.state)>=0
                            text: (closing ? qsTr("Cerrar") : qsTr("Abrir"))+" "+parent.modelData.name
                            enabled: !panel.manager.busy && !panel.controller.busy
                            onClicked: {
                                let client=parent.modelData.id
                                let close=closing
                                panel.focusSection()
                                if (close) panel.manager.closeLauncher(client)
                                else panel.manager.openLauncher(client)
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: ["open","closed","error","timeout"].indexOf(parent.modelData.state)<0
                            text: parent.modelData.name+": "+parent.modelData.text
                            wrapMode: Text.WordWrap
                            opacity: 0.65
                        }
                    }
                }
                }
            }
            Rectangle { Layout.fillHeight: true; width: 1; color: Qt.alpha(panel.palette.text,0.1) }
            Loader {
                id: page
                objectName: "managementPageLoader"
                // Closing releases the page, including expanded cards and previews.
                // Keep settingsDraft on the panel so pending edits are not lost.
                active: panel.visible
                Layout.fillWidth: true; Layout.fillHeight: true
                sourceComponent: panel.section>=7 ? settingsPage : [localPage,artworkPage,importPage,categoriesPage,settingsPage,activityPage,updatesPage][panel.section]
            }
        }
        Label { Layout.fillWidth: true; text: panel.manager.message; color: theme.text; wrapMode: Text.WordWrap }
        RowLayout {
            BusyIndicator { running: panel.manager.busy; visible: running; Layout.preferredHeight: 36 }
            GlassButton { text: qsTr("Cancelar tareas"); visible: panel.manager.busy; onClicked: panel.manager.close() }
            Item { Layout.fillWidth: true }
            GlassButton { text: qsTr("Cerrar"); onClicked: panel.close() }
        }
    }
    Component {
        id: localPage
        ScrollView {
            function save() { if (!panel.manager.busy && localSave.enabled) localSave.clicked() }
            rightPadding: 12
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 18
                GlassCheck { id: editLocal; checked: panel.editingLocal && panel.manager.local.kind === "local"; text: qsTr("Editar la ejecución del juego seleccionado"); enabled: panel.manager.local.kind === "local" }
                Label { text: qsTr("Nombre del juego"); color: theme.text }
                GlassField { id: localTitle; Layout.fillWidth: true; text: editLocal.checked ? panel.manager.local.title : "" }
                Label { text: qsTr("Ejecutable .sh o .AppImage · ruta completa"); color: theme.text }
                GlassField { id: localPath; Layout.fillWidth: true; text: editLocal.checked ? panel.manager.local.path : "" }
                GlassButton { text: qsTr("Elegir archivo…"); onClicked: executableDialog.open() }
                FileDialog { id: executableDialog; nameFilters: ["Juegos (*.sh *.AppImage *.appimage)"]; onAccepted: localPath.text=decodeURIComponent(selectedFile.toString().replace("file://", "")) }
                Label { text: qsTr("Argumentos"); color: theme.text }
                GlassField { id: args; Layout.fillWidth: true; text: editLocal.checked ? panel.manager.local.arguments : "" }
                Label { text: qsTr("Directorio de trabajo · vacío para usar el del juego"); color: theme.text }
                GlassField { id: cwd; Layout.fillWidth: true; text: editLocal.checked ? panel.manager.local.cwd : "" }
                GlassButton { id: localSave; objectName: "saveLocalExecution"; text: editLocal.checked ? "Guardar ejecución" : "Añadir juego"; enabled: !panel.manager.busy; onClicked: panel.manager.saveLocal(localTitle.text,localPath.text,args.text,cwd.text,editLocal.checked) }
                Label { text: panel.controller.editorSaveHint; color: theme.muted }
                Label { text: qsTr("Steam, Faugus y Heroic conservan su configuración de ejecución en sus aplicaciones."); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                GlassButton { text: panel.deleting ? "Confirmar: quitar de Estante" : "Quitar juego seleccionado…"; enabled: panel.controller.selected>=0 && !panel.manager.busy; onClicked: { if (panel.deleting) { panel.manager.remove(); panel.deleting=false } else panel.deleting=true } }
            }
        }
    }
    Component {
        id: artworkPage
        ColumnLayout {
            spacing: 10
            GlassCombo { id: artworkField; currentIndex: panel.initialArtwork; onActivated: panel.manager.clearResults(); Layout.fillWidth: true; model: ["Carátula vertical", "Carátula cuadrada", "Logo", "Fondo", "Fondo secundario"].map(function(label) { return qsTr(label) }); property string field: ["cover","square_cover","logo","banner","banner_secondary"][currentIndex] }
            GlassField { id: location; Layout.fillWidth: true; placeholderText: qsTr("Ruta local o URL de la imagen") }
            RowLayout {
                GlassButton { text: qsTr("Elegir archivo…"); onClicked: imageDialog.open() }
                GlassButton { text: qsTr("Importar imagen"); enabled: !panel.manager.busy && panel.controller.selected>=0; onClicked: panel.manager.importImage(artworkField.field,location.text) }
                GlassButton { text: qsTr("Retirar imagen"); enabled: !panel.manager.busy; onClicked: panel.manager.clearImage(artworkField.field) }
            }
            FileDialog { id: imageDialog; nameFilters: ["Imágenes (*.png *.jpg *.jpeg *.webp *.img)"]; onAccepted: location.text=decodeURIComponent(selectedFile.toString().replace("file://", "")) }
            GlassButton { text: qsTr("Intercambiar fondos"); enabled: !panel.manager.busy; onClicked: panel.manager.swapBackgrounds() }
            GlassCombo { id: provider; currentIndex: panel.metadataSearch ? 3 : 0; onActivated: panel.manager.clearResults(); Layout.fillWidth: true; model: ["SteamGridDB", "Capturas Steam", "IGDB", "Ficha Wikidata"].map(function(label) { return qsTr(label) }); property string source: ["steamgriddb","steam","igdb","metadata"][currentIndex] }
            RowLayout {
                GlassField { id: onlineQuery; Layout.fillWidth: true; text: panel.controller.game.title || ""; placeholderText: qsTr("Buscar juego…") }
                GlassButton { text: qsTr("Buscar"); enabled: !panel.manager.busy; onClicked: panel.manager.searchArtwork(provider.source,onlineQuery.text,artworkField.field) }
            }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 8
                model: panel.manager.results
                cacheBuffer: 0
                delegate: GlassButton {
                    required property var modelData
                    required property int index
                    width: ListView.view.width; height: modelData.kind === "image" ? 130 : 48
                    text: modelData.name
                    Image { anchors.left: parent.left; anchors.margins: 8; height: parent.height-16; width: 190; source: parent.modelData.url || ""; sourceSize: Qt.size(380,240); asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit }
                    onClicked: panel.manager.chooseResult(index)
                }
            }
        }
    }
    Component {
        id: importPage
        ColumnLayout {
            function save() { panel.saveSettingsDraft() }
            function navigateSettings(action,keyboard,focused) {
                let owner=focused
                while (owner && owner.scanService!==true) owner=owner.parent
                if (action==="back" && owner && owner.expanded) { owner.expanded=false; owner.focusHeader(); return true }
                return false
            }
            spacing: 14
            ScrollView {
                id: scanScroll
                objectName: "scanScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth
                contentHeight: scanContent.implicitHeight+16
                clip: true
                ColumnLayout {
                    id: scanContent
                    x: 8; y: 8
                    width: scanScroll.availableWidth-16; spacing: 14
            GlassButton { objectName: "scanFaugusButton"; text: qsTr("Importar juegos de Faugus"); enabled: !panel.manager.busy; onClicked: panel.manager.scan("faugus") }
            GlassButton { objectName: "scanHeroicButton"; text: qsTr("Importar juegos de Heroic"); enabled: !panel.manager.busy; onClicked: panel.manager.scan("heroic") }
            GlassButton { text: qsTr("Importar juegos de Steam"); enabled: !panel.manager.busy; onClicked: panel.manager.scan("steam") }
            GlassButton { text: qsTr("Restaurar juegos excluidos"); enabled: !panel.manager.busy; onClicked: panel.manager.scan("restore") }
            GlassCheck { id: replace; text: qsTr("Reemplazar imágenes y metadatos existentes") }
            RowLayout {
                GlassCheck { id: scrapeCover; text: qsTr("Vertical"); checked: true }
                GlassCheck { id: scrapeSquare; text: qsTr("Cuadrada"); checked: true }
                GlassCheck { id: scrapeLogo; text: qsTr("Logo"); checked: true }
            }
            RowLayout {
                GlassCheck { id: scrapeBanner; text: qsTr("Fondo"); checked: true }
                GlassCheck { id: scrapeSecond; text: qsTr("Segundo fondo"); checked: true }
                GlassCheck { id: scrapeInfo; text: qsTr("Ficha"); checked: true }
            }
            GlassButton { text: qsTr("Scraping de la biblioteca"); enabled: !panel.manager.busy; onClicked: {
                let fields=[]
                if (scrapeCover.checked) fields.push("cover")
                if (scrapeSquare.checked) fields.push("square_cover")
                if (scrapeLogo.checked) fields.push("logo")
                if (scrapeBanner.checked) fields.push("banner")
                if (scrapeSecond.checked) fields.push("banner_secondary")
                panel.manager.scrape(replace.checked,fields,scrapeInfo.checked)
            } }
            Label { text: qsTr("Los juegos ocultos de Faugus se ignoran. Las imágenes usan SteamGridDB si hay una clave configurada; las fichas se obtienen de Wikidata."); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2; columnSpacing: 16
                        Repeater {
                            model: panel.manager.settingGroups("scan")
                            delegate: SettingsCard {
                                id: service
                                property bool scanService: true
                                required property var modelData
                                objectName: "scanService:"+modelData.title
                                key: "scan:"+modelData.title
                                title: modelData.title
                                Layout.preferredWidth: 1; Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                                body: ColumnLayout {
                                    spacing: 14
                                    Repeater {
                                        model: service.modelData.rows
                                        delegate: SettingControl {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            controller: panel.controller
                                            spec: Object.assign({},modelData,{sectionStart:false,value:panel.settingsDraft[JSON.stringify(modelData.path)]!==undefined ? panel.settingsDraft[JSON.stringify(modelData.path)] : modelData.value})
                                            onSettingValueChanged: {
                                                let key=JSON.stringify(modelData.path)
                                                if (settingValue!==modelData.value) panel.settingsDraft[key]=settingValue
                                                else delete panel.settingsDraft[key]
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
                Label { text: panel.controller.editorSaveHint; opacity: .6; Layout.fillWidth: true }
                GlassButton { objectName: "saveScanServices"; text: qsTr("Guardar servicios"); highlighted: true; enabled: !panel.manager.busy; onClicked: panel.saveSettingsDraft() }
            }
        }
    }
    Component {
        id: categoriesPage
        CategoriesPane { manager: panel.manager; controller: panel.controller; onSaveRequested: panel.close() }
    }
    Component {
        id: settingsPage
        SettingsPane {
            manager: panel.manager
            controller: panel.controller
            draft: panel.settingsDraft
            mode: ({7:"list",8:"grid",9:"carousel",10:"ps5"})[panel.section] || "global"
            onSidebarRequested: panel.focusSection()
            onEdited: (key,value,original) => {
                if (value!==original) panel.settingsDraft[key]=value
                else delete panel.settingsDraft[key]
            }
            onSaveRequested: panel.saveSettingsDraft()
        }
    }
    Component {
        id: activityPage
        ScrollView {
            rightPadding: 12
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 14
                Label { text: panel.controller.game.activity; color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Repeater {
                    model: panel.controller.game.history || []
                    delegate: Label { required property var modelData; text: modelData.started+" · "+Math.round(modelData.seconds/60)+" min · salida "+modelData.exit_code; color: theme.text; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                }
            }
        }
    }
    Component {
        id: updatesPage
        ColumnLayout {
            GlassButton { text: qsTr("Instalar actualización del AppImage"); enabled: !panel.manager.busy; onClicked: panel.manager.updateAppImage() }
            GlassButton { text: qsTr("Comprobar actualizaciones"); enabled: !panel.manager.busy; onClicked: panel.manager.checkUpdates() }
            Label { text: qsTr("La instalación integrada requiere el AppImage. La ejecución desde código se actualiza con el instalador o el repositorio."); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
        }
    }
}
