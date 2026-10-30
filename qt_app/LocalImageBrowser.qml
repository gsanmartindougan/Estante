pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.folderlistmodel
import "Gamepad.js" as Navigation

ColumnLayout {
    id: browser
    objectName: "localImageBrowser"
    required property var manager
    property QtObject theme: ConsoleTheme {}
    property var places: manager.imagePlaces
    property var history: ({})
    property var details: ({valid:false})
    property string selectedUrl: ""
    property string folderError: ""
    property string folderUrl: folders.folder.toString()
    signal chosen(string path)
    signal dismissed()
    spacing: 12
    function focusFirst() { grid.forceActiveFocus() }
    function refreshSelection() {
        selectedUrl=grid.currentIndex>=0 && grid.currentIndex<folders.count && !folders.isFolder(grid.currentIndex)
                    ? folders.get(grid.currentIndex,"fileUrl").toString() : ""
        details=selectedUrl ? manager.localImageInfo(selectedUrl) : ({valid:false})
    }
    function openFolder(url) {
        const error=manager.imageFolderError(url.toString())
        if (error) { folderError=error; return }
        history[folderUrl]=grid.currentIndex
        folderError=""; selectedUrl=""; details=({valid:false})
        folders.folder=url
        grid.forceActiveFocus()
    }
    function up() {
        const parent=folders.parentFolder.toString()
        if (parent && parent!==folderUrl) openFolder(parent)
        else dismissed()
    }
    function useImage() {
        if (!selectedUrl || manager.busy) return
        details=manager.localImageInfo(selectedUrl)
        if (details.valid) chosen(decodeURIComponent(selectedUrl.replace(/^file:\/\//,"")))
    }
    function activate() {
        if (grid.currentIndex<0 || grid.currentIndex>=folders.count) return
        if (folders.isFolder(grid.currentIndex)) openFolder(folders.get(grid.currentIndex,"fileUrl"))
        else { refreshSelection(); useButton.forceActiveFocus() }
    }
    function navigate(action,keyboard,focused) {
        if (action==="back") { up(); return true }
        if (action==="save") { useImage(); return true }
        if (grid.activeFocus) {
            const n=grid.currentIndex, columns=grid.columns
            if (action==="confirm") { activate(); return true }
            if (action==="up" && n<columns) { upButton.forceActiveFocus(); return true }
            if (action==="left" && (n<0 || n%columns===0)) { placesRepeater.itemAt(0).forceActiveFocus(); return true }
            if (action==="right" && n%columns===columns-1) { useButton.forceActiveFocus(); return true }
            const step=action==="left" ? -1 : action==="right" ? 1 : action==="up" ? -columns : action==="down" ? columns : 0
            if (step) {
                if (action==="down" && n+step>=folders.count) { if (useButton.enabled) useButton.forceActiveFocus(); return true }
                grid.currentIndex=Math.max(0,Math.min(folders.count-1,n+step))
                grid.positionViewAtIndex(grid.currentIndex,GridView.Contain)
                return true
            }
        }
        if (action==="confirm") Navigation.activate(browser,focused,keyboard)
        else Navigation.navigate(browser,focused,action)
        return true
    }
    Keys.onPressed: event => {
        const action=event.key===Qt.Key_Left ? "left" : event.key===Qt.Key_Right ? "right" : event.key===Qt.Key_Up ? "up" : event.key===Qt.Key_Down ? "down" : event.key===Qt.Key_Return || event.key===Qt.Key_Enter ? "confirm" : event.key===Qt.Key_Escape || event.key===Qt.Key_Backspace ? "back" : ""
        if (action) { navigate(action,null,null); event.accepted=true }
    }
    FolderListModel {
        id: folders; objectName: "localImageFolders"
        folder: {
            const pictures=browser.places.find(place => place.key==="pictures")
            return pictures ? pictures.url : browser.places.length ? browser.places[0].url : "file:///"
        }
        showDotAndDotDot: false; showDirsFirst: true; showHidden: false
        nameFilters: ["*.png","*.jpg","*.jpeg","*.webp","*.PNG","*.JPG","*.JPEG","*.WEBP"]
        sortField: FolderListModel.Name
        onStatusChanged: if (status===FolderListModel.Ready) {
            grid.currentIndex=count ? Math.min(browser.history[browser.folderUrl] || 0,count-1) : -1
            browser.refreshSelection()
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: qsTr("Elegir imagen del equipo"); color: browser.theme.text; font.bold: true; Layout.fillWidth: true }
        EditorButton { text: qsTr("Volver"); onClicked: browser.dismissed() }
    }
    RowLayout {
        Layout.fillWidth: true
        EditorButton { id: upButton; objectName: "localImageUp"; text: qsTr("Subir"); onClicked: browser.up() }
        ScrollView {
            Layout.fillWidth: true; Layout.preferredHeight: 44
            contentHeight: availableHeight; clip: true
            Row {
                spacing: 4
                Repeater {
                    model: browser.folderUrl.replace(/^file:\/\//,"").split("/")
                    delegate: EditorButton {
                        required property string modelData
                        required property int index
                        text: index===0 ? "/" : decodeURIComponent(modelData)+" /"
                        onClicked: browser.openFolder("file://"+browser.folderUrl.replace(/^file:\/\//,"").split("/").slice(0,index+1).join("/")+(index===0 ? "/" : ""))
                    }
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
        ColumnLayout {
            Layout.preferredWidth: browser.width<800 ? 106 : 150; Layout.maximumWidth: Layout.preferredWidth; Layout.fillHeight: true
            Label { text: qsTr("LUGARES"); font.pixelSize: 12; color: browser.theme.muted }
            Repeater {
                id: placesRepeater
                model: browser.places
                delegate: EditorButton {
                    required property var modelData
                    Layout.fillWidth: true; text: modelData.name
                    onClicked: browser.openFolder(modelData.url)
                }
            }
            Item { Layout.fillHeight: true }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 140
            Label { text: qsTr("%1 elementos · PNG, JPEG, WebP").arg(folders.count); font.pixelSize: 12; color: browser.theme.muted }
            GridView {
                id: grid; objectName: "localImageGrid"
                property bool gamepadFocusable: true
                property string gamepadKind: "local-images"
                property int columns: width>=570 ? 3 : 2
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; cacheBuffer: 0; reuseItems: true
                cellWidth: width/columns; cellHeight: Math.min(180,cellWidth*.75+32)
                model: folders
                onCurrentIndexChanged: browser.refreshSelection()
                ScrollBar.vertical: ScrollBar {}
                delegate: EditorButton {
                    id: tile
                    required property int index
                    required property string fileName
                    required property url fileUrl
                    required property bool fileIsDir
                    property bool gamepadFocusable: false
                    property bool pooled: false
                    GridView.onPooled: pooled=true
                    GridView.onReused: pooled=false
                    property bool onScreen: !pooled && y+height>=grid.contentY && y<=grid.contentY+grid.height
                    property var imageInfo: onScreen && !fileIsDir ? browser.manager.localImageInfo(fileUrl.toString()) : ({valid:false})
                    objectName: "localImageTile"+index
                    width: grid.cellWidth-10; height: grid.cellHeight-10
                    highlighted: grid.currentIndex===index
                    contentItem: ColumnLayout {
                        Item {
                            Layout.fillWidth: true; Layout.fillHeight: true
                            Rectangle {
                                visible: tile.fileIsDir; anchors.centerIn: parent
                                width: 44; height: 32; radius: 4; color: browser.theme.muted
                                Rectangle { width: 20; height: 7; y: -5; radius: 3; color: parent.color }
                            }
                            Image {
                                id: thumbnail
                                anchors.fill: parent; visible: !tile.fileIsDir
                                source: tile.onScreen && tile.imageInfo.valid ? tile.fileUrl : ""
                                sourceSize: Qt.size(220,150); asynchronous: true; cache: false
                                fillMode: Image.PreserveAspectFit
                            }
                            Label { anchors.centerIn: parent; visible: !tile.fileIsDir && (!tile.imageInfo.valid || thumbnail.status===Image.Error); text: qsTr("Sin vista previa"); color: browser.theme.muted; font.pixelSize: 11 }
                        }
                        Label { Layout.fillWidth: true; text: tile.fileName; elide: Text.ElideMiddle; color: browser.theme.text; font.pixelSize: 13 }
                    }
                    onClicked: { grid.currentIndex=index; grid.forceActiveFocus(); if (fileIsDir) browser.activate(); else browser.refreshSelection() }
                    onDoubleClicked: if (!fileIsDir) browser.useImage()
                }
                Label {
                    anchors.centerIn: parent; width: parent.width-24
                    visible: folders.count===0 || browser.folderError!==""
                    text: browser.folderError || (folders.status===FolderListModel.Loading ? qsTr("Cargando…") : qsTr("No hay imágenes compatibles en esta carpeta."))
                    color: browser.theme.muted; wrapMode: Text.WordWrap
                }
            }
        }
        Rectangle {
            Layout.preferredWidth: Math.min(280,browser.width*.25); Layout.fillHeight: true
            color: browser.theme.base; radius: 10
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                Item {
                    Layout.fillWidth: true; Layout.preferredHeight: Math.min(220,browser.height*.35)
                    // The checkerboard makes alpha visible without flattening the file.
                    Canvas {
                        anchors.fill: parent; visible: browser.details.valid===true
                        onPaint: {
                            const ctx=getContext("2d")
                            for(let y=0;y<height;y+=12) for(let x=0;x<width;x+=12) { ctx.fillStyle=(x/12+y/12)%2 ? "#777777" : "#999999"; ctx.fillRect(x,y,12,12) }
                        }
                    }
                    Image { objectName: "localImagePreview"; anchors.fill: parent; source: browser.details.valid ? browser.selectedUrl : ""; sourceSize: Qt.size(560,440); asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit }
                }
                Label { Layout.fillWidth: true; text: browser.details.name || qsTr("Selecciona una imagen"); wrapMode: Text.WrapAnywhere; font.bold: true; color: browser.theme.text }
                Label { Layout.fillWidth: true; visible: browser.details.valid===true; text: browser.details.width+" × "+browser.details.height+" px\n"+(browser.details.bytes/1024).toFixed(1)+" KiB"; color: browser.theme.muted; wrapMode: Text.WordWrap }
                Label { Layout.fillWidth: true; text: browser.details.error || ""; wrapMode: Text.WordWrap; color: browser.theme.muted }
                Item { Layout.fillHeight: true }
            }
        }
    }
    Label { Layout.fillWidth: true; visible: browser.manager.message!==""; text: browser.manager.message; color: browser.theme.muted; wrapMode: Text.WordWrap }
    RowLayout {
        Layout.fillWidth: true
        Label { Layout.fillWidth: true; text: qsTr("Cruceta: mover · A: abrir / seleccionar · B: subir · X: usar imagen"); wrapMode: Text.WordWrap; font.pixelSize: 12; color: browser.theme.muted }
        EditorButton { id: useButton; objectName: "localImageUse"; text: qsTr("Usar imagen"); highlighted: true; enabled: browser.details.valid===true && !browser.manager.busy; onClicked: browser.useImage() }
    }
}
