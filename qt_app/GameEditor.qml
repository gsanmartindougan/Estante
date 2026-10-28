pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation

Dialog {
    property QtObject theme: ConsoleTheme {}
    id: editor
    objectName: "gameEditor"
    property string page: "overview"
    property bool manual: page === "manual"
    property int artworkIndex: 0
    property bool metadataSearch: false
    function overview() { controller.manager.close(); page="overview"; Qt.callLater(function() { verticalCover.forceActiveFocus() }) }
    function artwork(field, metadata) { controller.manager.close(); artworkIndex=field; metadataSearch=metadata; page="artwork"; Qt.callLater(function() { artworkLoader.item.focusFirst() }) }
    property bool deleting: false
        function loadDraft() {
        controller.edit()
        for (let i=0;i<inputs.count;++i) inputs.itemAt(i).value=controller.draft[fields[i].key] || ""
        description.text=controller.draft.description || ""
        synopsis.text=controller.draft.synopsis || ""
    }
    function showManual() { loadDraft(); page="manual"; inputs.itemAt(0).focusInput() }
    function showCategories() { loadDraft(); page="categories"; Qt.callLater(function() { saveButton.forceActiveFocus() }) }
    required property var controller
    padding: 20
    topPadding: 20
    bottomPadding: 24
    background: MaterialSurface {
        color: theme.window
        radius: 0
    }
    modal: true
    title: page==="artwork" ? (metadataSearch ? qsTr("Buscar ficha del juego") : [qsTr("Elegir carátula"),qsTr("Elegir carátula 1:1"),qsTr("Elegir logo"),qsTr("Elegir banner"),qsTr("Elegir segundo fondo")][artworkIndex]) : page==="categories" ? qsTr("Categorías") : page==="execution" ? qsTr("Ejecución") : page==="activity" ? qsTr("Actividad") : page==="manual" ? qsTr("Editar ficha del juego") : qsTr("Editar · ")+controller.game.title
    width: Math.min(parent.width,Math.max(640,parent.width/2))
    height: parent.height
    x: parent.width-width
    y: 0
    header: Item {
        implicitWidth: 300
        implicitHeight: 58
        Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Qt.alpha(theme.text,.12) }
        Label {
            anchors.fill: parent
            text: editor.title
            leftPadding: editor.page==="overview" ? 24 : 76; rightPadding: 80; topPadding: 24; bottomPadding: 12
            font.pixelSize: 15; font.bold: true
            color: theme.text
            elide: Text.ElideRight
        }
        EditorButton {
            visible: editor.page!=="overview"
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 16 }
            text: "←"; Accessible.name: qsTr("Volver")
            onClicked: editor.overview()
        }
        EditorButton {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 20 }
            text: "×"; Accessible.name: qsTr("Cerrar")
            onClicked: editor.controller.cancelEdit()
        }
    }
    closePolicy: Popup.CloseOnEscape
    function navigate(action, keyboard, focused) {
        if (action === "back") { if (page!=="overview") { overview() } else controller.cancelEdit(); return }
        if (action === "save") { save(); return }
        if (page==="artwork" && artworkLoader.item && artworkLoader.item.navigate(action,keyboard,focused)) return
        if (action === "confirm") Navigation.activate(contentItem, focused, keyboard)
        else Navigation.navigate(contentItem, focused, action)
    }
    property var fields: [
        {key: "title", label: "Título de la ficha"},
        {key: "developers", label: "Estudios · separados por comas"},
        {key: "publishers", label: "Editoras · separadas por comas"},
        {key: "genres", label: "Géneros · separados por comas"},
        {key: "platforms", label: "Plataformas · separadas por comas"},
        {key: "release_date", label: "Lanzamiento · DD/MM/AAAA o AAAA-MM-DD"},
        {key: "categories", label: "Categorías · separadas por comas"}
    ]
    onOpened: {
        page="overview"; deleting=false
        for (let i=0; i<inputs.count; ++i)
            inputs.itemAt(i).value = controller.draft[fields[i].key] || ""
        description.text = controller.draft.description || ""
        synopsis.text = controller.draft.synopsis || ""
        verticalCover.forceActiveFocus()
    }
    onClosed: { controller.manager.close(); if (controller.editing) controller.cancelEdit() }
    function save() {
        if (controller.manager.busy) return
        if (page==="execution" && executionLoader.item) { executionLoader.item.save(); return }
        if (page==="artwork" && artworkLoader.item) { artworkLoader.item.save(); return }
        if (page==="overview") { controller.cancelEdit(); return }
        if (!manual && page!=="categories") return
        let values = {description: description.text, synopsis: synopsis.text}
        for (let i=0; i<inputs.count; ++i)
            values[fields[i].key] = inputs.itemAt(i).value
        controller.saveEdit(values)
    }
    contentItem: ColumnLayout {
        spacing: 18
        ScrollView {
            visible: editor.page==="overview"
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 16
                Item {
                    Layout.fillWidth: true; Layout.preferredHeight: 160
                    RoundedImage { anchors.fill: parent; cornerRadius: 14; source: editor.visible && editor.page==="overview" ? editor.controller.editorImages.banner || "" : ""; sourceSize: Qt.size(width,height); fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false }
                    RoundedImage { x: 16; y: 16; width: 86; height: 128; cornerRadius: 10; source: editor.visible && editor.page==="overview" ? editor.controller.editorImages.cover || "" : ""; sourceSize: Qt.size(172,256); fillMode: Image.PreserveAspectFit; asynchronous: true; cache: false }
                }
                EditorSection {
                    Layout.fillWidth: true; title: qsTr("Carátulas")
                    RowLayout {
                        Layout.fillWidth: true
                        EditorButton { id: verticalCover; objectName: "editVerticalCover"; text: qsTr("Vertical (2:3)"); Layout.fillWidth: true; Layout.preferredWidth: 1; onClicked: editor.artwork(0,false) }
                        EditorButton { text: qsTr("Cuadrada (1:1)"); Layout.fillWidth: true; Layout.preferredWidth: 1; onClicked: editor.artwork(1,false) }
                        EditorButton { text: qsTr("Logo"); Layout.fillWidth: true; Layout.preferredWidth: 1; onClicked: editor.artwork(2,false) }
                    }
                }
                EditorSection {
                    Layout.fillWidth: true; title: qsTr("Fondos")
                    Row {
                        id: backgroundPreviews
                        objectName: "editorBackgroundPreviews"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        property real previewHeight: Math.max(0,(width-spacing)/2)*9/16+48
                        Layout.preferredHeight: previewHeight
                        spacing: 12
                        Repeater {
                            model: editor.visible && editor.page==="overview" ? [editor.controller.editorImages.banner || "",editor.controller.editorImages.secondary || ""] : ["",""]
                            delegate: Item {
                                id: preview
                                required property string modelData
                                required property int index
                                objectName: "editorBackgroundPreview"+index
                                width: Math.max(0,(backgroundPreviews.width-backgroundPreviews.spacing)/2)
                                height: backgroundPreviews.previewHeight
                                RoundedImage {
                                    objectName: "editorBackgroundImage"+preview.index
                                    width: preview.width; height: width*9/16
                                    cornerRadius: 12; source: preview.modelData
                                    sourceSize: Qt.size(Math.ceil(width*Screen.devicePixelRatio),Math.ceil(height*Screen.devicePixelRatio))
                                    fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
                                }
                                EditorButton {
                                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                                    text: preview.index===0 ? qsTr("Fondo principal…") : qsTr("Segundo fondo…")
                                    onClicked: editor.artwork(preview.index+3,false)
                                }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: qsTr("Configura la división en los ajustes de cada apariencia."); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.muted }
                        EditorButton { text: qsTr("Intercambiar fondos"); visible: Boolean(editor.controller.editorImages.banner) && Boolean(editor.controller.editorImages.secondary); enabled: !editor.controller.manager.busy; onClicked: editor.controller.manager.swapBackgrounds() }
                        EditorButton { text: qsTr("Quitar segundo fondo"); enabled: !editor.controller.manager.busy && Boolean(editor.controller.editorImages.secondary); onClicked: editor.controller.manager.clearImage("banner_secondary") }
                    }
                }
                EditorSection {
                    Layout.fillWidth: true; title: qsTr("Información del juego")
                    RowLayout {
                        Layout.fillWidth: true
                        EditorButton { text: qsTr("Buscar ficha del juego"); Layout.fillWidth: true; Layout.preferredWidth: 1; onClicked: editor.artwork(0,true) }
                        EditorButton { objectName: "editManual"; text: qsTr("Editar ficha a mano"); Layout.fillWidth: true; Layout.preferredWidth: 1; onClicked: editor.showManual() }
                    }
                }
                EditorSection {
                    Layout.fillWidth: true; title: qsTr("Organización")
                    EditorButton { text: qsTr("Categorías…"); Layout.fillWidth: true; onClicked: editor.showCategories() }
                    EditorButton { text: editor.deleting ? qsTr("Confirmar: quitar de la biblioteca") : qsTr("Quitar de la biblioteca"); Layout.fillWidth: true; enabled: !editor.controller.manager.busy; onClicked: { if (editor.deleting) { editor.controller.manager.remove(); editor.controller.cancelEdit() } else editor.deleting=true } }
                }
                RowLayout {
                    EditorButton { text: qsTr("Ejecución"); onClicked: editor.page="execution" }
                    EditorButton { text: qsTr("Actividad"); onClicked: editor.page="activity" }
                }
            }
        }
        ScrollView {
            visible: editor.page==="categories"
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 14
                        Label { text: qsTr("Selecciona las categorías del juego. Puedes crearlas y gestionarlas en Ajustes → Categorías."); Layout.fillWidth: true; wrapMode: Text.WordWrap; color: theme.text }
                        Repeater {
                            model: editor.controller.categories.slice(1)
                            delegate: GlassCheck {
                                required property string modelData
                                text: modelData
                                checked: inputs.count>6 && inputs.itemAt(6).value.split(",").map(v=>v.trim()).indexOf(modelData)>=0
                                onToggled: {
                                    let values=inputs.itemAt(6).value.split(",").map(v=>v.trim()).filter(v=>v.length && v!==modelData)
                                    if (checked) values.push(modelData)
                                    inputs.itemAt(6).value=values.join(", ")
                                }
                            }
                        }
                        EditorButton { id: categorySave; objectName: "saveGameCategories"; text: qsTr("Guardar categorías"); highlighted: true; enabled: !editor.controller.manager.busy; onClicked: editor.save() }
                        Label { text: editor.controller.editorSaveHint; color: theme.muted }
                        Item { Layout.fillHeight: true }
                    }
        }
        Loader {
            id: artworkLoader
            Layout.fillWidth: true; Layout.fillHeight: true
            visible: editor.page==="artwork"
            active: visible
            sourceComponent: EditorArtwork {
                controller: editor.controller
                field: ["cover","square_cover","logo","banner","banner_secondary"][editor.artworkIndex]
                metadata: editor.metadataSearch
                onCompleted: editor.overview()
            }
        }
        Loader {
            id: executionLoader
            Layout.fillWidth: true; Layout.fillHeight: true
            visible: editor.page==="execution" || editor.page==="activity"
            active: visible
            sourceComponent: editor.page==="execution" ? executionPage : activityPage
        }
        ScrollView {
            visible: editor.manual
            Layout.fillWidth: true; Layout.fillHeight: true
            rightPadding: 12
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: parent.width; spacing: 18
                Repeater {
                    id: inputs
                    model: editor.fields
                    delegate: ColumnLayout {
                        required property var modelData
                        visible: modelData.key!=="categories"
                        property alias value: input.text
                        function focusInput() { input.forceActiveFocus() }
                        Layout.fillWidth: true
                        Label { text: parent.modelData.label; color: theme.text }
                        GlassField {
                            id: input
                            objectName: parent.modelData.key
                            Layout.fillWidth: true
                            color: theme.text
                            activeFocusOnTab: true
                        }
                    }
                }
                Label { text: qsTr("Descripción"); color: theme.text }
                GlassArea {
                    id: description
                    objectName: "description"
                    Layout.fillWidth: true; Layout.preferredHeight: 100
                    wrapMode: TextEdit.Wrap; color: theme.text

                }
                Label { text: qsTr("Sinopsis"); color: theme.text }
                GlassArea {
                    id: synopsis
                    objectName: "synopsis"
                    Layout.fillWidth: true; Layout.preferredHeight: 100
                    wrapMode: TextEdit.Wrap; color: theme.text

                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: editor.controller.editorError
            visible: text.length > 0
            wrapMode: Text.WordWrap; color: theme.text
        }
        RowLayout {
            visible: editor.page==="overview" || editor.manual || editor.page==="categories"
            Layout.fillWidth: true
            Label { objectName: "editorSaveHint"; text: editor.controller.editorSaveHint; color: theme.muted }
            Item { Layout.fillWidth: true }
            EditorButton { visible: editor.manual || editor.page==="categories"; text: qsTr("Cancelar"); onClicked: editor.overview() }
            EditorButton { id: saveButton; objectName: "editorSave"; highlighted: true; text: qsTr("Guardar"); enabled: !editor.controller.manager.busy; onClicked: editor.save() }
        }
    }
    Component {
        id: executionPage
        ScrollView {
            function save() { if (!editor.controller.manager.busy && localSave.enabled) localSave.clicked() }
            rightPadding: 12
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 18
                GlassCheck { id: editLocal; checked: true && editor.controller.manager.local.kind === "local"; text: qsTr("Editar la ejecución del juego seleccionado"); enabled: editor.controller.manager.local.kind === "local" }
                Label { text: qsTr("Nombre del juego"); color: theme.text }
                GlassField { id: localTitle; Layout.fillWidth: true; text: editLocal.checked ? editor.controller.manager.local.title : "" }
                Label { text: qsTr("Ejecutable .sh o .AppImage · ruta completa"); color: theme.text }
                GlassField { id: localPath; Layout.fillWidth: true; text: editLocal.checked ? editor.controller.manager.local.path : "" }
                Label { text: qsTr("Argumentos"); color: theme.text }
                GlassField { id: args; Layout.fillWidth: true; text: editLocal.checked ? editor.controller.manager.local.arguments : "" }
                Label { text: qsTr("Directorio de trabajo · vacío para usar el del juego"); color: theme.text }
                GlassField { id: cwd; Layout.fillWidth: true; text: editLocal.checked ? editor.controller.manager.local.cwd : "" }
                EditorButton { id: localSave; objectName: "saveGameExecution"; text: editLocal.checked ? "Guardar ejecución" : "Añadir juego"; enabled: !editor.controller.manager.busy; onClicked: editor.controller.manager.saveLocal(localTitle.text,localPath.text,args.text,cwd.text,editLocal.checked) }
                Label { text: editor.controller.editorSaveHint; color: theme.muted }
                Label { text: qsTr("Steam y Faugus conservan su configuración de ejecución en sus aplicaciones."); color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                EditorButton { text: editor.deleting ? "Confirmar: quitar de Estante" : "Quitar juego seleccionado…"; enabled: editor.controller.selected>=0 && !editor.controller.manager.busy; onClicked: { if (editor.deleting) { editor.controller.manager.remove(); editor.deleting=false } else editor.deleting=true } }
            }
        }
    }
    Component {
        id: activityPage
        ScrollView {
            rightPadding: 12
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 14
                Label { text: editor.controller.game.activity; color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Repeater {
                    model: editor.controller.game.history || []
                    delegate: Label { required property var modelData; text: modelData.started+" · "+Math.round(modelData.seconds/60)+" min · salida "+modelData.exit_code; color: theme.text; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                }
            }
        }
    }
}
