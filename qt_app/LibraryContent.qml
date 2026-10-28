pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation

Item {
    id: window
    required property var controller
    required property var hostWindow
    property QtObject theme: ConsoleTheme {}
    palette: hostWindow.palette
    readonly property var activeFocusItem: hostWindow.activeFocusItem
    readonly property Item contentItem: window
    function close() { hostWindow.close() }
    anchors.fill: parent
    property var game: controller.game
    property real dim: controller.appearance.dim
    property real blurAmount: controller.appearance.blur
    property bool gridLibrary: controller.viewMode === "grid"
    property bool listCoverActions: controller.viewMode === "list" && heroRow.visible && heroCover.visible && heroCover.source.toString().length > 0
    property bool carouselLibrary: controller.viewMode === "carousel"
    property bool stackedDetails: (gridLibrary || carouselLibrary) && !controller.appearance.minimal
    property bool senseLibrary: controller.viewMode === "ps5"
    property bool sideLibrary: controller.viewMode === "list" && (controller.appearance.side === "left" || controller.appearance.side === "right")
    property bool topLibrary: (controller.viewMode === "list" && controller.appearance.side === "top") || controller.viewMode === "ps5" || (controller.viewMode === "carousel" && !controller.appearance.bottom)
    readonly property real listShare: 0.35
    property real listBodyTop: toolbar.y+toolbar.height+24
    property real listBodyHeight: Math.max(200,height-footer.height-36-listBodyTop)
    // Keep the original information columns; put the actions above them.
    property real carouselGroupWidth: Math.min(1100,width-64)
    property real carouselCoverWidth: Math.min(260*(controller.settingsMap.list_cover_zoom || 100)/100,carouselGroupWidth*0.28)
    property real carouselTileWidth: Math.min(280*controller.appearance.zoom,strip.height*0.7,strip.width*0.24)
    property real carouselTileHeight: controller.appearance.format === "square" ? carouselTileWidth : Math.min(strip.height-12,carouselTileWidth*1.5)
    property real originalPanelTop: gridLibrary ? strip.y+Math.max(0,(strip.height-80-500)/2) : topLibrary ? strip.y+strip.height+110+Math.max(0,(height-strip.y-strip.height-150-500)/2) : toolbar.y+toolbar.height+30+Math.max(0,(strip.y-toolbar.y-toolbar.height-110-500)/2)
    property real pixelRatio: Screen.devicePixelRatio
    Item {
    id: libraryScene
    anchors.fill: parent
    Background {
        id: sceneBackdrop
        fallbackColor: theme.window
        anchors.fill: parent
        primary: window.game.banner
        secondary: window.game.secondary
        split: window.controller.appearance.split
        position: window.controller.appearance.hero
        dim: window.game.banner || window.game.secondary ? window.dim : 0
        blur: window.blurAmount
        fillBlur: window.controller.appearance.fillBlur
        fillMode: window.controller.appearance.fillMode
        fillPrimary: window.game.fillPrimary || ""
        fillSecondary: window.game.fillSecondary || ""
    }
    Rectangle {
        id: backdropShade
        objectName: "backdropShade"
        property color shadeColor: theme.shadow
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.alpha(backdropShade.shadeColor, 0.38) }
            GradientStop { position: 0.45; color: Qt.alpha(backdropShade.shadeColor, 0.18) }
            GradientStop { position: 1; color: Qt.alpha(backdropShade.shadeColor, 0.9) }
        }
    }
    MaterialSurface {
        id: toolbar
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 16 }
        width: Math.min(toolbarRow.implicitWidth+24, window.width-32); height: 52; radius: 16
        color: theme.surface
        objectName: "libraryToolbar"
        RowLayout {
            id: toolbarRow
            x: 12; y: 6; width: parent.width-24; height: 40; spacing: 6
            GlassField {
                id: search
                objectName: "search"
                implicitHeight: 40
                Layout.preferredWidth: Math.max(160,Math.min(240,window.width*0.18))
                Layout.minimumWidth: 140
                Layout.alignment: Qt.AlignVCenter
                placeholderText: qsTr("Buscar juegos…")
                color: theme.text
                placeholderTextColor: theme.muted
                text: window.controller.initialQuery
                onTextChanged: window.controller.search(text)
            }
            ContextStrip {
                id: alphabet
                objectName: "alphabetStrip"
                visible: window.width >= 1200
                labels: window.controller.letters
                currentIndex: window.controller.letterIndex
                onStepped: delta => window.controller.letter(delta)
            }
            ContextStrip {
                id: category
                objectName: "category"
                labels: window.controller.categories
                currentIndex: window.controller.categoryIndex
                iconSource: window.controller.categoryImage
                property int count: labels.length
                onStepped: delta => window.controller.category((currentIndex+delta+count)%count)
            }
            Item { Layout.fillWidth: true }
            ToolbarButton { objectName: "addToolbarButton"; symbol: "add"; label: qsTr("Añadir juego"); enabled: window.controller.canEdit; onClicked: management.openSection(0) }
            ToolbarButton { objectName: "settingsToolbarButton"; symbol: "settings"; label: qsTr("Ajustes"); enabled: window.controller.canEdit; onClicked: management.openSection(4) }
            ToolbarButton { symbol: "tray"; label: qsTr("Enviar a la bandeja"); onClicked: window.controller.toTray() }
            ToolbarButton { symbol: "exit"; label: qsTr("Salir"); onClicked: window.close() }
        }
    }
    ColumnLayout {
        id: launcherIndicators
        objectName: "launcherIndicators"
        x: toolbar.x+toolbar.width+12+implicitWidth < window.width-12 ? toolbar.x+toolbar.width+12 : toolbar.x+(toolbar.width-width)/2
        y: x > toolbar.x+toolbar.width ? toolbar.y+8 : toolbar.y+toolbar.height+4
        spacing: 3
        RowLayout {
            spacing: 12
            Repeater {
                model: window.controller.launchers.entries
                delegate: Label {
                    required property var modelData
                    objectName: "launcherStatus:"+modelData.id
                    visible: modelData.state !== "open"
                    text: "○ "+modelData.name+": "+modelData.text
                    color: theme.text
                    font.pixelSize: 12
                }
            }
        }
    }
    Label {
        objectName: "launcherStartupNotice"
        anchors { horizontalCenter: parent.horizontalCenter; bottom: footer.top; bottomMargin: 12 }
        visible: text.length>0
        text: window.controller.launchers.notice
        color: theme.text
        padding: 10
        background: Rectangle { radius: 10; color: theme.surface }
    }
    Item {
        id: selectionHeading
        objectName: "selectionHeading"
        visible: window.stackedDetails && window.controller.selected >= 0 && !window.controller.suspended
        x: window.carouselLibrary ? (window.width-width)/2 : heroRow.x
        y: window.carouselLibrary ? actions.y-height-4 : heroRow.y-height-actions.height-28
        width: heroRow.width
        height: !visible ? 64 : window.gridLibrary ? Math.min(96,window.height*0.1) : selectedLogo.height+16
        Image {
            id: selectedLogo
            objectName: "selectedGameLogo"
            anchors.centerIn: parent
            width: Math.min(360, parent.width-16)
            property real aspectRatio: implicitHeight > 0 ? implicitWidth/implicitHeight : 4
            property real availableHeight: !selectionHeading.visible ? 48 : window.gridLibrary ? Math.min(96,window.height*0.1)-16 : window.controller.appearance.bottom ? actions.y-toolbar.y-toolbar.height-32 : actions.y-strip.y-(strip.height+window.carouselTileHeight)/2-28
            height: Math.min(Math.max(48,availableHeight),160,width/Math.max(0.1,aspectRatio))
            source: selectionHeading.visible ? window.game.logo || "" : ""
            sourceSize: Qt.size(360*window.pixelRatio,160*window.pixelRatio)
            fillMode: Image.PreserveAspectFit
            asynchronous: true; cache: false
        }
        Label {
            objectName: "selectedGameTitle"
            anchors.fill: parent
            visible: selectedLogo.status !== Image.Ready
            text: window.game.title
            color: theme.text
            font.pixelSize: window.gridLibrary ? 26 : 32
            font.bold: true
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
        }
    }
    GridLayout {
        id: heroRow
        columns: window.sideLibrary ? 1 : 2
        property real coverBlockHeight: coverColumn.visible ? coverColumn.Layout.preferredHeight+rowSpacing : 0
        property real compactInfoHeight: Math.max(120,Math.min(420,infoContent.implicitHeight+48,window.listBodyHeight-coverBlockHeight))
        objectName: "detailLayout"
        visible: !window.controller.appearance.minimal && !window.controller.suspended
        x: (window.controller.viewMode === "list") ? window.sideLibrary ? (window.controller.appearance.side === "left" ? window.width*window.listShare : 0)+(window.width*(1-window.listShare)-width)/2 : (window.width-width)/2 : window.stackedDetails ? window.gridLibrary ? strip.x+strip.width+24 : (window.width-width)/2 : window.senseLibrary ? strip.x : window.sideLibrary && window.controller.appearance.side === "left" ? strip.x+strip.width+24 : (window.sideLibrary ? 24 : (window.width-width)/2)
        y: (window.controller.viewMode === "list") ? window.sideLibrary ? window.listBodyTop : window.listBodyTop+window.listBodyHeight*(window.controller.appearance.side === "top" ? (1+window.listShare)/2 : (1-window.listShare)/2)-(window.listBodyHeight*(1-window.listShare)-32)/2 : window.stackedDetails ? Math.max(window.originalPanelTop,toolbar.y+toolbar.height+Math.min(window.controller.viewMode === "grid" ? 96 : 40,window.height*0.1)+actions.height+48) : window.topLibrary ? strip.y+strip.height+110 : toolbar.y+toolbar.height+30
        width: (window.controller.viewMode === "list") ? window.sideLibrary ? Math.min(880,window.width*(1-window.listShare)-48) : Math.min(1100,window.width-64) : window.stackedDetails ? window.gridLibrary ? window.width-strip.x-strip.width-56 : window.carouselGroupWidth-window.carouselCoverWidth-(window.width<1000 ? 20 : 40) : window.senseLibrary ? Math.min(700,window.width*.5) : window.sideLibrary ? window.width-strip.width-72 : Math.min(1100,window.width-64)
        height: (window.controller.viewMode === "list") ? window.sideLibrary ? Math.min(window.listBodyHeight,coverBlockHeight+compactInfoHeight) : window.listBodyHeight*(1-window.listShare)-32 : window.stackedDetails ? Math.max(60,Math.min(500,(window.carouselLibrary && window.controller.appearance.bottom ? strip.y-80 : window.height-footer.height-36)-y)) : Math.max(160,window.topLibrary ? window.height-y-40 : window.sideLibrary ? window.height-y-60 : strip.y-y-80)
        columnSpacing: window.width < 1000 ? 20 : 40
        rowSpacing: 16
        Item {
            id: coverColumn
            visible: (window.controller.viewMode === "list") && (window.sideLibrary || heroCover.source.toString().length > 0)
            Layout.preferredWidth: Math.min(260*(window.controller.settingsMap.list_cover_zoom || 100)/100, heroRow.width*(window.sideLibrary ? 0.65 : 0.28))
            Layout.fillHeight: !window.sideLibrary
            Layout.preferredHeight: window.sideLibrary ? heroCover.source.toString().length > 0 ? Math.min(window.listBodyHeight*0.52,width*1.5+actions.height+16) : actions.height+16 : -1
            Layout.maximumHeight: window.sideLibrary ? Layout.preferredHeight : 514
            Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
            RoundedImage {
                cornerRadius: window.controller.appearance.radius
                id: heroCover
                objectName: "detailCover"
                visible: source.toString().length > 0
                width: parent.width
                height: Math.max(1,parent.height-actions.height-16)
                source: !heroRow.visible || window.controller.viewMode!=="list" || window.stackedDetails ? "" : window.controller.appearance.format === "square" ? window.game.squareCover || window.game.cover : window.game.cover
                asynchronous: true; cache: false
                fillMode: Image.PreserveAspectFit
                sourceSize: Qt.size(width*window.pixelRatio, height*window.pixelRatio)
            }
        }
        MaterialSurface {
            Layout.fillWidth: true
            Layout.fillHeight: !window.sideLibrary
            Layout.preferredHeight: window.sideLibrary ? heroRow.compactInfoHeight : -1
            Layout.maximumHeight: window.sideLibrary ? heroRow.compactInfoHeight : 500
            Layout.alignment: window.sideLibrary ? Qt.AlignTop : Qt.AlignVCenter
            objectName: "heroSurface"
            color: Qt.alpha(theme.surface, 0.72)
            elevation: 0
            ScrollView {
                anchors.fill: parent; anchors.margins: 24
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    id: infoContent
                    objectName: "infoContent"
                    width: parent.width; spacing: 14
                    Label {
                        text: qsTr("TU BIBLIOTECA")
                        color: theme.highlight
                        font.pixelSize: 12; font.bold: true; font.letterSpacing: 3
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: !window.stackedDetails || window.controller.selected < 0
                        text: window.controller.selected < 0 ? qsTr("Tu próxima aventura empieza aquí") : window.game.title
                        font.pixelSize: window.gridLibrary || window.width < 1100 ? 32 : 46; font.bold: true
                        color: theme.text; wrapMode: Text.WordWrap; lineHeight: 1.1
                    }
                    Label { text: window.game.activity; color: theme.muted; visible: text.length > 0 }

                    Label {
                        Layout.fillWidth: true; textFormat: Text.PlainText; text: window.game.description
                        color: theme.muted; wrapMode: Text.WordWrap; lineHeight: 1.35
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: window.game.genres
                            delegate: Rectangle {
                                required property string modelData
                                width: genre.implicitWidth + 24; height: 30; radius: 8; color: window.palette.button
                                Label { id: genre; anchors.centerIn: parent; text: parent.modelData; color: window.palette.buttonText }
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true; textFormat: Text.PlainText; text: window.game.details
                        color: theme.muted; wrapMode: Text.WordWrap; lineHeight: 1.3
                    }

                }
            }
        }
    }
    RowLayout {
        id: actions
        objectName: "gameActions"
        x: window.listCoverActions ? heroRow.x+coverColumn.x+(heroCover.width-width)/2 : window.sideLibrary ? heroRow.x+(heroRow.width-width)/2 : window.controller.viewMode === "list" ? strip.x+(strip.width-width)/2 : window.stackedDetails ? selectionHeading.x+(selectionHeading.width-width)/2 : window.senseLibrary ? strip.x : window.sideLibrary ? strip.x+(strip.width-width)/2 : (window.width-width)/2
        y: window.listCoverActions ? heroRow.y+coverColumn.y+heroCover.height+16 : window.sideLibrary ? heroRow.visible ? heroRow.y+coverColumn.y : window.listBodyTop+(window.listBodyHeight-height)/2 : window.controller.viewMode === "list" ? strip.y+strip.height+16 : window.stackedDetails ? heroRow.y-height-(window.carouselLibrary ? 8 : 16) : window.controller.appearance.minimal && !window.sideLibrary ? strip.y-height-12 : window.topLibrary ? strip.y+strip.height+12 : window.sideLibrary ? strip.y+strip.height/2-140 : strip.y-height-12
        spacing: 12
        GlassButton {
            id: playButton
            highlighted: true
            objectName: "playButton"
            text: window.controller.busy ? qsTr("Juego en ejecución") : qsTr("▶  Jugar")
            font.bold: true
            font.pixelSize: 17
            Layout.preferredHeight: 48
            enabled: window.controller.canLaunch && !window.controller.busy && window.controller.selected >= 0
            Layout.preferredWidth: window.controller.viewMode === "list" ? Math.max(80, Math.min(240,(window.listCoverActions ? heroCover.width : strip.width)-68)) : window.stackedDetails ? Math.min(240, Math.max(80,selectionHeading.width-68)) : window.sideLibrary ? 190 : 240
            onClicked: window.controller.play()
        }
        GlassButton {
            id: editButton
            objectName: "editButton"
            text: "..."
            Accessible.name: qsTr("Editar juego")
            ToolTip.visible: hovered || activeFocus
            ToolTip.text: qsTr("Editar juego")
            Layout.preferredHeight: 48
            Layout.preferredWidth: 56
            enabled: window.controller.canEdit && !window.controller.busy && window.controller.selected >= 0
            onClicked: window.controller.edit()
        }
    }
    LibraryView {
        id: strip
        objectName: "libraryStrip"
        controller: window.controller
        width: window.gridLibrary ? (window.controller.appearance.minimal ? window.width-64 : window.width*.68-48) : window.senseLibrary ? window.width-96 : window.sideLibrary ? window.width*window.listShare : Math.min(1800,window.width-40)
        height: (window.controller.viewMode === "list") ? window.sideLibrary ? window.listBodyHeight : Math.max(80,window.listBodyHeight*window.listShare-(window.listCoverActions ? 24 : 128)) : window.gridLibrary ? window.height-toolbar.y-toolbar.height-footer.height-64 : window.sideLibrary ? window.height-150-(window.listCoverActions ? 0 : actions.height+24) : window.controller.appearance.minimal ? window.controller.viewMode === "grid" ? window.height-220 : window.controller.viewMode === "carousel" ? Math.min(500,window.height-220) : 280 : window.controller.viewMode === "grid" ? Math.max(220,window.height*0.4) : window.controller.viewMode === "carousel" ? Math.min(420,window.height*0.4) : Math.min(260,window.height*0.25)
        x: (window.controller.viewMode === "list") ? window.sideLibrary ? window.controller.appearance.side === "left" ? 0 : window.width*(1-window.listShare) : (window.width-width)/2 : window.gridLibrary ? 32 : window.senseLibrary ? 48 : window.sideLibrary ? window.controller.appearance.side === "left" ? 20 : window.width-width-20 : (window.width-width)/2
        y: (window.controller.viewMode === "list") ? window.listBodyTop+window.listBodyHeight*(window.sideLibrary ? 0.5 : window.controller.appearance.side === "top" ? window.listShare/2 : 1-window.listShare/2)-height/2 : window.gridLibrary ? toolbar.y+toolbar.height+24 : window.controller.appearance.minimal && !window.sideLibrary ? (window.height-height)/2+30 : window.sideLibrary || window.topLibrary ? toolbar.y+toolbar.height+24 : window.height-footer.height-32-height-(window.controller.viewMode === "list" && !window.listCoverActions ? actions.height+24 : 0)
        visible: !window.controller.suspended
        focus: true
    }
    Label {
        id: footer
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: 18 }
        width: window.width-40
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: window.controller.status || (strip.count + " juegos · " + window.controller.controllerHints)
        color: theme.muted
        font.pixelSize: 13
    }
    }
    LaunchOverlay {
        anchors.fill: parent
        controller: window.controller
        originItem: heroCover.visible && heroRow.visible ? heroCover : strip.selectedItem()
    }
    SystemKeyboard { id: virtualKeyboard; objectName: "virtualKeyboard"; controller: window.controller; onSettingsRequested: management.openKeyboard() }
    function gamepadAction(action) {
        if (controller.screensaverActive) { controller.recordActivity(); return }
        if (Navigation.handleCombo(action)) return
        if (virtualKeyboard.visible) { virtualKeyboard.navigate(action); return }
        if (management.visible) { management.navigate(action,virtualKeyboard,activeFocusItem); return }
        if (editor.visible) { editor.navigate(action, virtualKeyboard, activeFocusItem); return }
        if (controller.loading) return
        if (action === "search") { virtualKeyboard.openFor(search); return }
        if (action === "menu") { management.openSection(4); return }
        if (action === "appearance_settings") { management.openSection(({list:7,grid:8,carousel:9,ps5:10})[controller.viewMode]); return }
        if (action === "appearance") { let modes=["list","grid","carousel","ps5"]; controller.changeView(modes[(modes.indexOf(controller.viewMode)+1)%4]); return }
        if (action === "save") { controller.edit(); return }
        if (action === "grid_page_next" || action === "grid_page_previous") {
            if (controller.viewMode === "grid") strip.changePage(action === "grid_page_next" ? 1 : -1)
            return
        }
        if (action === "page_next" || action === "page_previous") { if (controller.viewMode === "grid") strip.changePage(action === "page_next" ? 1 : -1); else controller.letter(action === "page_next" ? 1 : -1); return }
        if (action === "category_next" || action === "category_previous") {
            controller.category((controller.categoryIndex + (action === "category_next" ? 1 : -1) + category.count) % category.count)
            return
        }
        if (action === "back") { if (search.text) search.clear(); strip.forceActiveFocus(); return }
        if (strip.activeFocus) {
            if (controller.selected < 0) { if (action === "up") search.forceActiveFocus(); else if (action === "confirm") management.openSection(2); return }
            if (window.sideLibrary && (action === "up" || action === "down")) { strip.step(action); return }
            if (action === "left" || action === "right") strip.step(action)
            else if (action === "up" && controller.viewMode === "grid" && controller.selected>=strip.columns) strip.step(action)
            else if (action === "down" && controller.viewMode === "grid") strip.step(action)
            else if (action === "up" || action === "left" && window.sideLibrary || action === "right" && window.sideLibrary) { if (playButton.enabled) playButton.forceActiveFocus(); else editButton.forceActiveFocus() }
            else if (action === "confirm") { if (playButton.enabled) playButton.forceActiveFocus(); else editButton.forceActiveFocus() }
            return
        }
        if (action === "confirm") Navigation.activate(contentItem, activeFocusItem, virtualKeyboard)
        else Navigation.navigate(contentItem, activeFocusItem, action)
    }
    Connections { target: window.controller; function onInputAction(action) { window.gamepadAction(action) } }
    Management { id: management; controller: window.controller; onClosed: { if (editor.visible) editor.forceActiveFocus(); else strip.forceActiveFocus() } }
    GameEditor { id: editor; controller: window.controller }
    Connections {
        target: window.controller
        function onEditorChanged() {
            if (window.controller.editing && !editor.visible) editor.open()
            else if (!window.controller.editing && editor.visible) {
                editor.close()
                strip.forceActiveFocus()
            }
        }
    }
    Shortcut { sequence: "Ctrl+Tab"; enabled: !window.controller.editing && !management.visible && !virtualKeyboard.visible; onActivated: { let modes=["list","grid","carousel","ps5"]; window.controller.changeView(modes[(modes.indexOf(window.controller.viewMode)+1)%4]) } }
    Shortcut { sequence: "Ctrl+S"; enabled: (window.controller.editing || management.visible) && !virtualKeyboard.visible; onActivated: { if (management.visible) management.save(); else editor.save() } }
    Shortcut { enabled: !window.controller.editing && !management.visible && !virtualKeyboard.visible; sequence: "Ctrl+F"; onActivated: search.forceActiveFocus() }
    Shortcut { enabled: !window.controller.editing && !management.visible && !virtualKeyboard.visible; sequence: "Escape"; onActivated: { if (search.text) search.clear(); strip.forceActiveFocus() } }
}
