pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.folderlistmodel
import "Gamepad.js" as Navigation

ColumnLayout {
    id: picker
    required property var controller
    required property string field
    property bool metadata: false
    property var manager: controller.manager
    property QtObject theme: ConsoleTheme {}
    signal completed()
    property bool importing: false
    property bool browsing: false
    spacing: 14
    function focusFirst() { query.forceActiveFocus() }
    function navigate(action, keyboard, focused) {
        if (["confirm","left","right","up","down"].indexOf(action)<0) return false
        if (gallery.activeFocus) {
            if (action === "confirm") { choose(gallery.currentIndex); return true }
            let columns=picker.metadata ? 1 : 2
            let step=action==="left" ? -1 : action==="right" ? 1 : action==="down" ? columns : -columns
            if (action==="up" && gallery.currentIndex<columns) { search.forceActiveFocus(); return true }
            gallery.currentIndex=Math.max(0,Math.min(gallery.count-1,gallery.currentIndex+step))
            gallery.positionViewAtIndex(gallery.currentIndex,GridView.Contain)
            return true
        }
        return false
    }
    function save() {
        if (manager.busy) return
        if (local.visible && location.text.trim()) {
            importing=true; manager.importImage(field,location.text.trim())
        } else {
            const row=manager.results[gallery.currentIndex]
            if (row && (row.kind==="image" || metadata)) choose(gallery.currentIndex)
        }
    }
    function choose(index) {
        if (manager.busy) return
        const row=manager.results[index]
        if (!row) return
        importing=row.kind==="image" || metadata
        manager.chooseResult(index)
    }
    Connections {
        target: picker.manager
        function onChanged() {
            if (!picker.visible) return
            if (!picker.manager.busy && picker.importing) {
                picker.importing=false
                if (picker.manager.message==="Imagen guardada" || picker.manager.message==="Ficha descargada") picker.completed()
            } else if (!picker.manager.busy && picker.manager.results.length) {
                gallery.currentIndex=0; gallery.forceActiveFocus()
            }
        }
    }
    GlassField {
        id: query; objectName: "editorArtworkQuery"
        Layout.fillWidth: true; text: picker.controller.game.title || ""
        placeholderText: qsTr("Nombre del juego…")
        onAccepted: picker.manager.searchArtwork(picker.metadata ? "metadata" : "steamgriddb",text,picker.field)
    }
    EditorButton { objectName: "editorLocalImages"; visible: !picker.metadata; text: (local.visible ? "▾ " : "▸ ")+qsTr("Desde mi equipo o una URL"); onClicked: local.visible=!local.visible }
    ColumnLayout {
        id: local; visible: false; Layout.fillWidth: true
        EditorButton { objectName: "editorBrowseFiles"; text: qsTr("Desde mi equipo…"); onClicked: picker.browsing=!picker.browsing }
        ListView {
            id: files
            visible: picker.browsing
            Layout.fillWidth: true; Layout.preferredHeight: 210
            clip: true; cacheBuffer: 0; reuseItems: true
            model: FolderListModel { id: folders; folder: "file:///home"; showDotAndDotDot: true; nameFilters: ["*.png","*.jpg","*.jpeg","*.webp"]; showDirsFirst: true }
            delegate: EditorButton {
                required property string fileName
                required property url fileUrl
                required property bool fileIsDir
                width: ListView.view.width
                text: (fileIsDir ? "▸ " : "")+fileName
                onClicked: { if (fileIsDir) folders.folder=fileUrl; else { location.text=decodeURIComponent(fileUrl.toString().replace("file://","")); picker.browsing=false } }
            }
        }
        GlassField { id: location; Layout.fillWidth: true; placeholderText: qsTr("Ruta local o URL directa de la imagen") }
        EditorButton { text: qsTr("Usar imagen"); enabled: !picker.manager.busy && location.text.trim().length>0; onClicked: { picker.importing=true; picker.manager.importImage(picker.field,location.text.trim()) } }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Qt.alpha(picker.theme.text,.14) }
    Label { text: picker.metadata ? qsTr("Buscar ficha del juego") : qsTr("Buscar imágenes del juego"); font.bold: true; color: picker.theme.text }
    RowLayout {
        Layout.fillWidth: true
        EditorButton { id: search; objectName: "editorSearchArtwork"; Layout.fillWidth: true; text: picker.metadata ? qsTr("Buscar en Wikidata") : qsTr("Buscar en SteamGridDB"); enabled: !picker.manager.busy; onClicked: picker.manager.searchArtwork(picker.metadata ? "metadata" : "steamgriddb",query.text,picker.field) }
        EditorButton { objectName: "editorSearchSteamMetadata"; visible: picker.metadata; Layout.fillWidth: true; text: qsTr("Buscar ficha en Steam"); enabled: !picker.manager.busy; onClicked: picker.manager.searchArtwork("metadata_steam",query.text,picker.field) }
        EditorButton { visible: !picker.metadata && picker.field.indexOf("banner")===0; Layout.fillWidth: true; text: qsTr("Buscar capturas 16:9 en Steam"); enabled: !picker.manager.busy; onClicked: picker.manager.searchArtwork("steam",query.text,picker.field) }
        EditorButton { visible: !picker.metadata && picker.field.indexOf("banner")===0; Layout.fillWidth: true; text: qsTr("Buscar fondos 16:9 en IGDB"); enabled: !picker.manager.busy; onClicked: picker.manager.searchArtwork("igdb",query.text,picker.field) }
    }
    Label { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: picker.manager.message || qsTr("Busca el juego y selecciona una imagen."); wrapMode: Text.WordWrap; color: picker.theme.muted }
    GridView {
        id: gallery; objectName: "editorArtworkGallery"
        property bool gamepadFocusable: true
        property string gamepadKind: "artwork-gallery"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; cacheBuffer: 0; reuseItems: true
        model: picker.manager.results
        cellWidth: picker.metadata ? width : width/2; cellHeight: picker.metadata ? 80 : picker.manager.results.length && picker.manager.results[0].kind==="image" ? 238 : 56
        delegate: EditorButton {
            required property var modelData
            required property int index
            property bool gamepadFocusable: false
            width: gallery.cellWidth-12; height: gallery.cellHeight-16
            highlighted: gallery.activeFocus && gallery.currentIndex===index
            contentItem: ColumnLayout {
                Image { Layout.fillWidth: true; Layout.fillHeight: true; visible: parent.parent.modelData.kind==="image"; source: parent.parent.modelData.preview || parent.parent.modelData.url || ""; sourceSize: Qt.size(560,360); asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit }
                Label { Layout.fillWidth: true; text: parent.parent.modelData.name; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: parent.parent.highlighted ? picker.theme.system.highlightedText : picker.theme.text }
            }
            onClicked: { gallery.currentIndex=index; gallery.forceActiveFocus(); picker.choose(index) }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: picker.controller.editorSaveHint; color: picker.theme.muted; Layout.fillWidth: true }
        EditorButton {
            objectName: "saveEditorArtwork"
            text: picker.metadata ? qsTr("Guardar ficha") : qsTr("Guardar imagen")
            highlighted: true
            enabled: !picker.manager.busy && ((local.visible && location.text.trim().length>0) || (gallery.currentIndex>=0 && picker.manager.results.length>gallery.currentIndex && (picker.manager.results[gallery.currentIndex].kind==="image" || picker.metadata)))
            onClicked: picker.save()
        }
    }

}
