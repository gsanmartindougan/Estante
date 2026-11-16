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
    property bool carouselLibrary: controller.viewMode === "carousel"
    property bool stackedDetails: (gridLibrary || carouselLibrary) && !controller.appearance.minimal
    property bool senseLibrary: controller.viewMode === "ps5"
    property bool sideLibrary: controller.viewMode === "list" && (controller.appearance.side === "left" || controller.appearance.side === "right")
    property bool topLibrary: (controller.viewMode === "list" && controller.appearance.side === "top") || controller.viewMode === "ps5" || (controller.viewMode === "carousel" && !controller.appearance.bottom)
    readonly property real listShare: 0.35
    property real contentTop: 24
    property real contentBottom: footer.y-24
    property real listBodyTop: contentTop+24
    property real listBodyHeight: Math.max(200,contentBottom-listBodyTop)
    property real carouselGroupWidth: Math.min(1100,width-64)
    property real carouselCoverWidth: Math.min(260*(controller.settingsMap.list_cover_zoom || 100)/100,carouselGroupWidth*0.28)
    property real carouselTileWidth: Math.min(280*controller.appearance.zoom,strip.height*0.7,strip.width*0.24)
    property real carouselTileHeight: controller.appearance.format === "square" ? carouselTileWidth : Math.min(strip.height-12,carouselTileWidth*1.5)
    property real originalPanelTop: gridLibrary ? strip.y+Math.max(0,(strip.height-80-500)/2) : topLibrary ? strip.y+strip.height+110+Math.max(0,(contentBottom-strip.y-strip.height-110-500)/2) : contentTop+30+Math.max(0,(strip.y-contentTop-110-500)/2)
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
        y: window.carouselLibrary ? window.controller.appearance.bottom ? strip.y-height-16 : strip.y+strip.height+8 : heroRow.y-height-16
        width: heroRow.width
        height: !visible ? 64 : window.gridLibrary ? Math.min(96,window.height*0.1) : selectedLogo.height+16
        Image {
            id: selectedLogo
            objectName: "selectedGameLogo"
            anchors.centerIn: parent
            width: Math.min(360, parent.width-16)
            property real aspectRatio: implicitHeight > 0 ? implicitWidth/implicitHeight : 4
            property real availableHeight: !selectionHeading.visible ? 48 : window.gridLibrary ? Math.min(96,window.height*0.1)-16 : window.carouselLibrary && !window.controller.appearance.bottom ? Math.max(48,Math.min(96,heroRow.y-strip.y-strip.height-32)) : window.carouselLibrary ? Math.max(48,Math.min(160,strip.y-window.contentTop-32)) : Math.min(96,window.height*0.1)-16
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
        y: (window.controller.viewMode === "list") ? window.sideLibrary ? window.listBodyTop : window.listBodyTop+window.listBodyHeight*(window.controller.appearance.side === "top" ? (1+window.listShare)/2 : (1-window.listShare)/2)-(window.listBodyHeight*(1-window.listShare)-32)/2 : window.stackedDetails ? Math.max(window.originalPanelTop,window.contentTop+Math.min(window.controller.viewMode === "grid" ? 96 : 40,window.height*0.1)+40) : window.topLibrary ? strip.y+strip.height+110 : window.contentTop+30
        width: (window.controller.viewMode === "list") ? window.sideLibrary ? Math.min(880,window.width*(1-window.listShare)-48) : Math.min(1100,window.width-64) : window.stackedDetails ? window.gridLibrary ? window.width-strip.x-strip.width-56 : window.carouselGroupWidth-window.carouselCoverWidth-(window.width<1000 ? 20 : 40) : window.senseLibrary ? Math.min(700,window.width*.5) : window.sideLibrary ? window.width-strip.width-72 : Math.min(1100,window.width-64)
        height: (window.controller.viewMode === "list") ? window.sideLibrary ? Math.min(window.listBodyHeight,coverBlockHeight+compactInfoHeight) : window.listBodyHeight*(1-window.listShare)-32 : window.stackedDetails ? Math.max(60,Math.min(500,(window.carouselLibrary && window.controller.appearance.bottom ? strip.y-80 : window.contentBottom-24)-y)) : Math.max(160,window.topLibrary ? window.contentBottom-y-40 : window.sideLibrary ? window.contentBottom-y-60 : strip.y-y-80)
        columnSpacing: window.width < 1000 ? 20 : 40
        rowSpacing: 16
        Item {
            id: coverColumn
            visible: (window.controller.viewMode === "list") && (window.sideLibrary || heroCover.source.toString().length > 0)
            Layout.preferredWidth: Math.min(260*(window.controller.settingsMap.list_cover_zoom || 100)/100, heroRow.width*(window.sideLibrary ? 0.65 : 0.28))
            Layout.fillHeight: !window.sideLibrary
            Layout.preferredHeight: window.sideLibrary ? heroCover.source.toString().length > 0 ? Math.min(window.listBodyHeight*0.52,width*1.5+16) : 16 : -1
            Layout.maximumHeight: window.sideLibrary ? Layout.preferredHeight : 514
            Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
            RoundedImage {
                cornerRadius: window.controller.appearance.radius
                id: heroCover
                objectName: "detailCover"
                visible: source.toString().length > 0
                width: parent.width
                height: Math.max(1,parent.height-16)
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
    MaterialSurface {
        id: footer
        objectName: "libraryToolbar"
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 16 }
        width: Math.min(window.width-32,Math.max(720,barContent.preferredWidth+40,2*leftActions.implicitWidth+searchFilters.implicitWidth+48))
        height: 64
        radius: 14
        elevation: 0
        color: theme.surface
        Flickable {
            id: barScroller
            objectName: "gameActions"
            anchors.fill: parent
            clip: true
            contentWidth: barContent.width+40
            contentHeight: height
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentWidth > width
            function reveal(item) {
                let left=barContent.x+item.mapToItem(barContent,0,0).x
                if (left < contentX+8) contentX=Math.max(0,left-8)
                else if (left+item.width > contentX+width-8) contentX=Math.min(contentWidth-width,left+item.width-width+8)
            }
            ScrollBar.horizontal: ScrollBar { policy: barScroller.contentWidth > barScroller.width ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
            Item {
                id: barContent
                x: 20; y: 0; height: parent.height
                property real searchWidth: Math.max(120,Math.min(220,window.width*0.15))
                property real preferredWidth: leftActions.implicitWidth+rightControls.implicitWidth+searchFilters.implicitWidth+48
                width: Math.max(barScroller.width-40,preferredWidth)
                RowLayout {
                    id: leftActions
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    spacing: 4
                    Button {
                        id: playButton
                        objectName: "playButton"
                        Layout.preferredWidth: 100; Layout.minimumWidth: 100; Layout.preferredHeight: 44; Layout.minimumHeight: 44; Layout.fillHeight: true; flat: true
                        leftPadding: 0; rightPadding: 0
                        enabled: window.controller.canLaunch && !window.controller.busy && window.controller.selected >= 0
                        Accessible.name: qsTr("Jugar")
                        background: Rectangle { radius: 12; color: Qt.alpha(theme.text, playButton.down ? 0.16 : playButton.activeFocus ? 0.14 : playButton.hovered ? 0.11 : 0.08); border.color: playButton.activeFocus ? theme.highlight : Qt.alpha(theme.text, 0.2); border.width: playButton.activeFocus ? 2 : 1 }
                        contentItem: RowLayout {
                            spacing: 10
                            Item { Layout.fillWidth: true }
                            Item {
                                Layout.preferredWidth: 34; Layout.preferredHeight: 34
                                Rectangle { objectName: "buttonFocusRing"; anchors.fill: parent; anchors.margins: -2; radius: 16; color: "transparent"; border.color: theme.highlight; border.width: playButton.activeFocus ? 2 : 0; visible: playButton.activeFocus }
                                ControllerButtonIcon { anchors.centerIn: parent; controllerType: window.controller.settingsMap.controller_type || "xbox"; button: "play" }
                            }
                            Label { text: qsTr("Jugar"); color: theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                        }
                        onClicked: window.controller.play()
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(playButton)
                    }
                    Button {
                        id: editButton
                        objectName: "editButton"
                        Layout.preferredWidth: 100; Layout.minimumWidth: 100; Layout.preferredHeight: 44; Layout.minimumHeight: 44; Layout.fillHeight: true; flat: true
                        leftPadding: 0; rightPadding: 0
                        enabled: window.controller.canEdit && !window.controller.busy && window.controller.selected >= 0
                        Accessible.name: qsTr("Editar juego")
                        background: Rectangle { radius: 12; color: Qt.alpha(theme.text, editButton.down ? 0.16 : editButton.activeFocus ? 0.14 : editButton.hovered ? 0.11 : 0.08); border.color: editButton.activeFocus ? theme.highlight : Qt.alpha(theme.text, 0.2); border.width: editButton.activeFocus ? 2 : 1 }
                        contentItem: RowLayout {
                            spacing: 10
                            Item { Layout.fillWidth: true }
                            Item {
                                Layout.preferredWidth: 34; Layout.preferredHeight: 34
                                Rectangle { objectName: "buttonFocusRing"; anchors.fill: parent; anchors.margins: -2; radius: 16; color: "transparent"; border.color: theme.highlight; border.width: editButton.activeFocus ? 2 : 0; visible: editButton.activeFocus }
                                ControllerButtonIcon { anchors.centerIn: parent; controllerType: window.controller.settingsMap.controller_type || "xbox"; button: "save" }
                            }
                            Label { text: qsTr("Editar"); color: theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                        }
                        onClicked: window.controller.edit()
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(editButton)
                    }
                    Button {
                        id: backButton
                        objectName: "backButton"
                        Layout.preferredWidth: 100; Layout.minimumWidth: 100; Layout.preferredHeight: 44; Layout.minimumHeight: 44; Layout.fillHeight: true; flat: true
                        leftPadding: 0; rightPadding: 0
                        Accessible.name: qsTr("Volver")
                        background: Rectangle { radius: 12; color: Qt.alpha(theme.text, backButton.down ? 0.16 : backButton.activeFocus ? 0.14 : backButton.hovered ? 0.11 : 0.08); border.color: backButton.activeFocus ? theme.highlight : Qt.alpha(theme.text, 0.2); border.width: backButton.activeFocus ? 2 : 1 }
                        contentItem: RowLayout {
                            spacing: 10
                            Item { Layout.fillWidth: true }
                            Item {
                                Layout.preferredWidth: 34; Layout.preferredHeight: 34
                                Rectangle { objectName: "buttonFocusRing"; anchors.fill: parent; anchors.margins: -2; radius: 16; color: "transparent"; border.color: theme.highlight; border.width: backButton.activeFocus ? 2 : 0; visible: backButton.activeFocus }
                                ControllerButtonIcon { anchors.centerIn: parent; controllerType: window.controller.settingsMap.controller_type || "xbox"; button: "back" }
                            }
                            Label { text: qsTr("Volver"); color: theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                        }
                        onClicked: { if (search.text) search.clear(); else strip.forceActiveFocus() }
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(backButton)
                    }
                    Button {
                        id: settingsActionButton
                        objectName: "settingsToolbarButton"
                        Layout.preferredWidth: 108; Layout.minimumWidth: 108; Layout.preferredHeight: 44; Layout.minimumHeight: 44; Layout.fillHeight: true; flat: true
                        leftPadding: 0; rightPadding: 0
                        Accessible.name: qsTr("Ajustes")
                        background: Rectangle { radius: 12; color: Qt.alpha(theme.text, settingsActionButton.down ? 0.16 : settingsActionButton.activeFocus ? 0.14 : settingsActionButton.hovered ? 0.11 : 0.08); border.color: settingsActionButton.activeFocus ? theme.highlight : Qt.alpha(theme.text, 0.2); border.width: settingsActionButton.activeFocus ? 2 : 1 }
                        contentItem: RowLayout {
                            spacing: 10
                            Item { Layout.fillWidth: true }
                            Item {
                                Layout.preferredWidth: 34; Layout.preferredHeight: 34
                                Rectangle { objectName: "buttonFocusRing"; anchors.fill: parent; anchors.margins: -2; radius: 16; color: "transparent"; border.color: theme.highlight; border.width: settingsActionButton.activeFocus ? 2 : 0; visible: settingsActionButton.activeFocus }
                                ControllerButtonIcon { anchors.centerIn: parent; controllerType: window.controller.settingsMap.controller_type || "xbox"; button: "menu" }
                            }
                            Label { text: qsTr("Ajustes"); color: theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Item { Layout.fillWidth: true }
                        }
                        onClicked: management.openSection(4)
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(settingsActionButton)
                    }
                }
                Item {
                    id: searchFilters
                    objectName: "searchFilters"
                    x: 0; width: parent.width; height: 40
                    y: (parent.height-height)/2
                    implicitWidth: (alphabet.visible ? alphabet.width+6 : 0)+search.width+category.width+6
                    implicitHeight: 40
                    ContextStrip {
                        id: alphabet
                        objectName: "alphabetStrip"
                        visible: window.width >= 1200
                        width: implicitWidth; height: 40
                        x: search.x-width-6; y: (parent.height-height)/2
                        labels: window.controller.letters
                        currentIndex: window.controller.letterIndex
                        theme: window.theme
                        onStepped: delta => window.controller.letter(delta)
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(alphabet)
                    }
                    GlassField {
                        id: search
                        objectName: "search"
                        width: barContent.searchWidth; height: 40
                        x: barScroller.contentX+(barScroller.width-width)/2-barContent.x
                        y: (parent.height-height)/2
                        placeholderText: qsTr("Buscar juegos…")
                        color: theme.text
                        placeholderTextColor: theme.muted
                        background: Rectangle {
                            radius: 12
                            color: Qt.alpha(theme.text, search.activeFocus ? 0.14 : search.hovered ? 0.11 : 0.08)
                            border.color: search.activeFocus ? theme.highlight : Qt.alpha(theme.text, 0.2)
                            border.width: search.activeFocus ? 2 : 1
                        }
                        text: window.controller.initialQuery
                        onTextChanged: window.controller.search(text)
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(search)
                    }
                    ContextStrip {
                        id: category
                        objectName: "category"
                        width: window.width < 1000 ? 128 : 164; height: 40
                        x: search.x+search.width+6; y: (parent.height-height)/2
                        labels: window.controller.categories
                        iconSources: window.controller.categoryImages
                        currentOnly: true
                        currentIndex: window.controller.categoryIndex
                        theme: window.theme
                        property int count: labels.length
                        onStepped: delta => window.controller.category((currentIndex+delta+count)%count)
                        onActiveFocusChanged: if (activeFocus) barScroller.reveal(category)
                    }
                }
                RowLayout {
                    id: rightControls
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    spacing: 6
                    Label { visible: window.controller.status.length>0; text: window.controller.status; color: theme.muted; font.pixelSize: 11 }
                    RowLayout {
                        id: launcherIndicators
                        objectName: "launcherIndicators"
                        spacing: 8
                        Repeater {
                            model: window.controller.launchers.entries
                            delegate: Label {
                                required property var modelData
                                objectName: "launcherStatus:"+modelData.id
                                Accessible.name: modelData.name+": "+modelData.text
                                ToolTip.visible: statusHover.containsMouse || activeFocus
                                ToolTip.text: Accessible.name
                                ToolTip.delay: statusHover.containsMouse ? 500 : 0
                                text: "●"
                                color: modelData.state === "open" ? "#27bd7c" : (modelData.state === "checking" || modelData.state === "opening" || modelData.state === "closing") ? "#efc340" : (modelData.state === "error" || modelData.state === "timeout") ? "#e56a6b" : theme.muted
                                font.pixelSize: 9
                                Layout.preferredWidth: 16; Layout.preferredHeight: 16
                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                Image {
                                    id: launcherIcon
                                    anchors.centerIn: parent
                                    width: 15; height: 15
                                    source: modelData.icon
                                    visible: status === Image.Ready
                                    asynchronous: true
                                    fillMode: Image.PreserveAspectFit
                                }
                                Rectangle {
                                    anchors { right: parent.right; bottom: parent.bottom }
                                    width: 5; height: 5; radius: 3
                                    border.color: theme.surface; border.width: 1
                                    visible: launcherIcon.status === Image.Ready
                                    color: modelData.state === "open" ? "#27bd7c" : (modelData.state === "checking" || modelData.state === "opening" || modelData.state === "closing") ? "#efc340" : (modelData.state === "error" || modelData.state === "timeout") ? "#e56a6b" : theme.muted
                                }
                                MouseArea { id: statusHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            }
                        }
                    }
                    ToolbarButton { objectName: "addToolbarButton"; symbol: "add"; label: qsTr("Añadir juego"); enabled: window.controller.canEdit; onClicked: management.openSection(0); onActiveFocusChanged: if (activeFocus) barScroller.reveal(this) }
                    ToolbarButton { symbol: "tray"; label: qsTr("Enviar a la bandeja"); onClicked: window.controller.toTray(); onActiveFocusChanged: if (activeFocus) barScroller.reveal(this) }
                    ToolbarButton { symbol: "exit"; label: qsTr("Salir"); onClicked: window.close(); onActiveFocusChanged: if (activeFocus) barScroller.reveal(this) }
                }
            }
        }
    }
    LibraryView {
        id: strip
        objectName: "libraryStrip"
        controller: window.controller
        width: window.gridLibrary ? (window.controller.appearance.minimal ? window.width-64 : window.width*.68-48) : window.senseLibrary ? window.width-96 : window.sideLibrary ? window.width*window.listShare : Math.min(1800,window.width-40)
        height: (window.controller.viewMode === "list") ? window.sideLibrary ? window.listBodyHeight : Math.max(80,window.listBodyHeight*window.listShare-24) : window.gridLibrary ? window.contentBottom-window.contentTop-48 : window.sideLibrary ? window.contentBottom-window.contentTop-48 : window.controller.appearance.minimal ? window.controller.viewMode === "grid" ? window.contentBottom-window.contentTop-112 : window.controller.viewMode === "carousel" ? Math.min(500,window.contentBottom-window.contentTop-112) : 280 : window.controller.viewMode === "grid" ? Math.min(window.contentBottom-window.contentTop-48,Math.max(220,window.height*0.4)) : window.controller.viewMode === "carousel" ? Math.min(420,window.height*0.4,window.contentBottom-window.contentTop-48) : Math.min(260,window.height*0.25)
        x: (window.controller.viewMode === "list") ? window.sideLibrary ? window.controller.appearance.side === "left" ? 0 : window.width*(1-window.listShare) : (window.width-width)/2 : window.gridLibrary ? 32 : window.senseLibrary ? 48 : window.sideLibrary ? window.controller.appearance.side === "left" ? 20 : window.width-width-20 : (window.width-width)/2
        y: (window.controller.viewMode === "list") ? window.listBodyTop+window.listBodyHeight*(window.sideLibrary ? 0.5 : window.controller.appearance.side === "top" ? window.listShare/2 : 1-window.listShare/2)-height/2 : window.gridLibrary ? window.contentTop+24 : window.controller.appearance.minimal && !window.sideLibrary ? (window.contentTop+window.contentBottom-height)/2+30 : window.sideLibrary || window.topLibrary ? window.contentTop+24 : window.contentBottom-height-32
        visible: !window.controller.suspended
        focus: true
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
        if (action === "play") { if (playButton.enabled) controller.play(); return }
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
            else if (action === "up" || action === "left" && window.sideLibrary || action === "right" && window.sideLibrary) { if (playButton.enabled) playButton.forceActiveFocus(); else if (editButton.enabled) editButton.forceActiveFocus(); else backButton.forceActiveFocus() }
            else if (action === "confirm") { if (playButton.enabled) playButton.forceActiveFocus(); else if (editButton.enabled) editButton.forceActiveFocus(); else backButton.forceActiveFocus() }
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
