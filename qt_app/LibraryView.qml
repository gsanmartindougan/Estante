pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: library
    required property var controller
    property var appearance: controller.appearance
    property bool gamepadFocusable: true
    property string gamepadKind: "library"
    property bool vertical: controller.viewMode === "list" && (appearance.side === "left" || appearance.side === "right")
    function selectedItem() { return viewLoader.item ? viewLoader.item.currentItem : null }
    property var entries: controller.entries
    property int count: entries.length
    property int pageSize: Math.max(1,Math.min(100,Math.floor(Number(controller.settingsMap.grid_page_size)||10)))
    property int pageCount: Math.ceil(count/pageSize)
    property int pageIndex: Math.max(0,Math.min(pageCount-1,Math.floor(controller.selected/pageSize)))
    property int pageStart: pageIndex*pageSize
    property var pageEntries: entries.slice(pageStart,pageStart+pageSize)
    property int columns: Math.min(controller.viewMode === "grid" ? pageSize : count || 1,Math.max(1, Math.floor(width/Math.max(140,Math.min(260,180*appearance.zoom)))))
    function changePage(delta) {
        if (!pageCount) return
        let next=(pageIndex+delta+pageCount)%pageCount
        controller.select(next*pageSize+Math.min(Math.max(0,controller.selected-pageStart),count-next*pageSize-1))
        library.forceActiveFocus()
    }
    focus: true
    function step(action) {
        if (controller.viewMode === "grid") controller.move(action === "up" ? -columns : action === "down" ? columns : action === "left" ? -1 : 1)
        else controller.move(action === "left" || action === "up" ? -1 : 1)
    }
    Keys.onLeftPressed: step("left")
    Keys.onRightPressed: step("right")
    Keys.onReturnPressed: controller.play()
    Loader { id: viewLoader; anchors.fill: parent; sourceComponent: controller.viewMode === "grid" ? gridComponent : controller.viewMode === "carousel" ? carouselComponent : controller.viewMode === "list" ? infiniteListComponent : stripComponent }
    Component {
        id: gridComponent
        Item {
            property var currentItem: grid.currentItem
            GridView {
                id: grid
                objectName: "pagedGrid"
                anchors.horizontalCenter: parent.horizontalCenter
                height: Math.max(1,parent.height-52)
                width: library.columns*cellWidth
                model: library.pageEntries
                currentIndex: library.controller.selected-library.pageStart
                cellWidth: Math.max(140,Math.min(260,180*library.appearance.zoom))
                cellHeight: cellWidth*(library.appearance.format === "square" ? 1.1 : 1.55)
                clip: true; cacheBuffer: 0; reuseItems: false
                highlightFollowsCurrentItem: true
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                delegate: CoverTile {
                    required property var modelData
                    required property int index
                    objectName: "gridPageTile"
                    width: grid.cellWidth-16; height: grid.cellHeight-16
                    imageSource: library.appearance.format === "square" ? modelData.squareCover || modelData.cover : modelData.cover
                    selected: index+library.pageStart === library.controller.selected
                    appearance: library.appearance
                    onChosen: { library.controller.select(index+library.pageStart); library.forceActiveFocus() }
                }
            }
            RowLayout {
                anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom }
                spacing: 16
                GlassButton { objectName: "previousGridPage"; text: "‹"; Accessible.name: qsTr("Página anterior"); enabled: library.pageCount>1; onClicked: library.changePage(-1) }
                Label { objectName: "gridPageIndicator"; text: qsTr("Página")+" "+(library.count ? library.pageIndex+1 : 0)+" / "+library.pageCount }
                GlassButton { objectName: "nextGridPage"; text: "›"; Accessible.name: qsTr("Página siguiente"); enabled: library.pageCount>1; onClicked: library.changePage(1) }
            }
        }
    }
    Component {
        id: stripComponent
        ListView {
            id: strip
            anchors.fill: parent
            orientation: library.vertical ? ListView.Vertical : ListView.Horizontal
            model: library.entries
            currentIndex: library.controller.selected
            highlightRangeMode: ListView.StrictlyEnforceRange
            property real selectedExtent: library.vertical ? 160 : library.controller.viewMode === "list" ? 300*(library.controller.settingsMap.list_zoom || 100)/100*(library.controller.settingsMap.list_focus_zoom || 150)/100 : (library.controller.settingsMap.ps5_focus_size || 250)
            preferredHighlightBegin: 0
            preferredHighlightEnd: preferredHighlightBegin+selectedExtent
            highlightMoveDuration: library.controller.viewMode === "ps5" && library.controller.settingsMap.ps5_motion === false ? 0 : 130
            cacheBuffer: 0; reuseItems: true; clip: true
            delegate: CoverTile {
                required property var modelData
                required property int index
                property real targetWidth: library.vertical ? strip.width : library.controller.viewMode === "list" ? 300*(library.controller.settingsMap.list_zoom || 100)/100*(index === library.controller.selected ? (library.controller.settingsMap.list_focus_zoom || 150)/100 : 1) : index === library.controller.selected ? (library.controller.settingsMap.ps5_focus_size || 250) : 120
                width: targetWidth
                decodeWidth: targetWidth
                height: library.vertical ? (index === library.controller.selected ? 160 : 110) : strip.height
                Behavior on width { NumberAnimation { duration: library.controller.settingsMap.ps5_motion === false ? 0 : 130 } }
                imageSource: library.controller.viewMode === "list" ? modelData.logo || modelData.squareCover || modelData.cover : library.appearance.format === "square" ? modelData.squareCover || modelData.cover : modelData.cover
                selected: index === library.controller.selected
                appearance: library.appearance
                onChosen: { library.controller.select(index); library.forceActiveFocus() }
            }
        }
    }
    Component {
        id: infiniteListComponent
        PathView {
            id: loop
            objectName: "infiniteList"
            anchors.fill: parent
            model: library.count ? library.count*1000 : 0
            Component.onCompleted: syncSelection()
            onModelChanged: Qt.callLater(centerSelection)
            onPathItemCountChanged: Qt.callLater(centerSelection)
            function centerSelection() {
                if (!library.count) return
                syncSelection()
                positionViewAtIndex(currentIndex, PathView.Center)
            }
            function syncSelection() {
                if (!library.count) return
                let delta = (library.controller.selected-currentIndex%library.count+library.count)%library.count
                if (delta>library.count/2) delta-=library.count
                if (currentIndex<library.count*2 || currentIndex>library.count*998) currentIndex=library.count*500+library.controller.selected
                else currentIndex+=delta
            }
            property real focusZoom: Math.max(1, (library.controller.settingsMap.list_focus_zoom || 150)/100)
            property real availableExtent: library.vertical ? height : width
            property real gap: 32
            property real requestedExtent: (library.vertical ? 160 : 300)*(library.controller.settingsMap.list_zoom || 100)/100
            // Only the current game needs an enlarged slot. Neighbours retain their base size.
            property int slots: Math.max(Math.min(library.count,5), 2*Math.floor(((availableExtent-(focusZoom-1)*requestedExtent)/(requestedExtent+gap)-1)/2)+1)
            pathItemCount: Math.min(library.count, slots)
            property int spanSlots: Math.max(1,pathItemCount+(pathItemCount%2 === 0 ? 1 : 0))
            property real normalExtent: Math.max(1,Math.min(requestedExtent,(availableExtent-gap*spanSlots)/(spanSlots-1+focusZoom)))
            property real selectedExtent: normalExtent*focusZoom
            property real neighbourDistance: (selectedExtent+normalExtent)/2+gap
            property real halfSpan: (normalExtent*(spanSlots-1+focusZoom)+gap*spanSlots)/2
            property bool reverseSide: library.appearance.side === "right" || library.appearance.side === "bottom"
            property real selectedWidth: library.vertical ? Math.min(width*0.72,360*(library.controller.settingsMap.list_zoom || 100)/100*focusZoom) : selectedExtent
            property real selectedHeight: library.vertical ? selectedExtent : Math.max(1,height*0.72)
            property real centerX: width/2
            property real centerY: height/2
            property real bend: Math.max(0,Math.min((library.vertical ? width-selectedWidth : height-selectedHeight)/2-8,normalExtent*0.6))
            property real edgeOffset: reverseSide ? bend : -bend
            function pointAt(offset) {
                let cross=edgeOffset*offset*offset/(halfSpan*halfSpan)
                return library.vertical ? Qt.point(centerX+cross,centerY+offset) : Qt.point(centerX+offset,centerY+cross)
            }
            function controlAt(start,end) {
                let cross=edgeOffset*start*end/(halfSpan*halfSpan)
                return library.vertical ? Qt.point(centerX+cross,centerY+(start+end)/2) : Qt.point(centerX+(start+end)/2,centerY+cross)
            }
            cacheItemCount: 0
            preferredHighlightBegin: 0.5; preferredHighlightEnd: 0.5
            highlightRangeMode: PathView.StrictlyEnforceRange
            highlightMoveDuration: 130
            property bool userMoving: false
            onDraggingChanged: { if (dragging) userMoving = true }
            onMovementEnded: {
                if (userMoving) library.controller.select(currentIndex%library.count)
                userMoving = false
            }
            Connections {
                target: library.controller
                function onSelectionChanged() { loop.syncSelection() }
            }
            clip: true
            path: library.count<3 ? shortPath : spacedPath
            Path {
                id: shortPath
                property real reach: loop.neighbourDistance
                startX: loop.pointAt(-reach).x; startY: loop.pointAt(-reach).y
                PathQuad {
                    x: loop.centerX; y: loop.centerY
                    controlX: loop.controlAt(-shortPath.reach,0).x; controlY: loop.controlAt(-shortPath.reach,0).y
                }
                PathQuad {
                    x: loop.pointAt(shortPath.reach).x; y: loop.pointAt(shortPath.reach).y
                    controlX: loop.controlAt(0,shortPath.reach).x; controlY: loop.controlAt(0,shortPath.reach).y
                }
            }
            Path {
                id: spacedPath
                startX: loop.pointAt(-loop.halfSpan).x; startY: loop.pointAt(-loop.halfSpan).y
                PathQuad {
                    x: loop.pointAt(-loop.neighbourDistance).x; y: loop.pointAt(-loop.neighbourDistance).y
                    controlX: loop.controlAt(-loop.halfSpan,-loop.neighbourDistance).x; controlY: loop.controlAt(-loop.halfSpan,-loop.neighbourDistance).y
                }
                PathPercent { value: 0.5-1/Math.max(3,loop.pathItemCount) }
                PathQuad {
                    x: loop.centerX; y: loop.centerY
                    controlX: loop.controlAt(-loop.neighbourDistance,0).x; controlY: loop.controlAt(-loop.neighbourDistance,0).y
                }
                PathPercent { value: 0.5 }
                PathQuad {
                    x: loop.pointAt(loop.neighbourDistance).x; y: loop.pointAt(loop.neighbourDistance).y
                    controlX: loop.controlAt(0,loop.neighbourDistance).x; controlY: loop.controlAt(0,loop.neighbourDistance).y
                }
                PathPercent { value: 0.5+1/Math.max(3,loop.pathItemCount) }
                PathQuad {
                    x: loop.pointAt(loop.halfSpan).x; y: loop.pointAt(loop.halfSpan).y
                    controlX: loop.controlAt(loop.neighbourDistance,loop.halfSpan).x; controlY: loop.controlAt(loop.neighbourDistance,loop.halfSpan).y
                }
            }
            delegate: CoverTile {
                property var modelData: library.count ? (library.entries[index%library.count] || {}) : ({})
                required property int index
                objectName: "listLogoTile"
                width: loop.selectedWidth/(selected ? 1 : loop.focusZoom)
                height: loop.selectedHeight/(selected ? 1 : loop.focusZoom)
                logoMode: Boolean(modelData.logo)
                z: index%library.count === library.controller.selected ? 2 : 1
                imageSource: modelData.logo || modelData.squareCover || modelData.cover || ""
                selected: index%library.count === library.controller.selected
                appearance: library.appearance
                onChosen: { library.controller.select(index%library.count); library.forceActiveFocus() }
            }
        }
    }
    Component {
        id: carouselComponent
        PathView {
            id: carousel
            objectName: "coverCarousel"
            property real tileWidth: Math.min(280*library.appearance.zoom, height*0.7, width*0.24)
            anchors.fill: parent
            model: library.entries
            currentIndex: library.controller.selected
            pathItemCount: Math.min(5,library.count)
            cacheItemCount: 0
            preferredHighlightBegin: 0.5; preferredHighlightEnd: 0.5
            highlightRangeMode: PathView.StrictlyEnforceRange
            highlightMoveDuration: 150
            onMovementEnded: library.controller.select(currentIndex)
            clip: true
            path: Path {
                startX: carousel.tileWidth*0.3+8; startY: carousel.height/2
                PathAttribute { name: "itemScale"; value: 0.5 }
                PathLine { x: carousel.width/2; y: carousel.height/2 }
                PathAttribute { name: "itemScale"; value: 1 }
                PathLine { x: carousel.width-carousel.tileWidth*0.3-8; y: carousel.height/2 }
                PathAttribute { name: "itemScale"; value: 0.5 }
            }
            delegate: CoverTile {
                required property var modelData
                required property int index
                width: carousel.tileWidth
                height: library.appearance.format === "square" ? width : Math.min(carousel.height-12,width*1.5)
                scale: PathView.itemScale || 0.5
                z: index === library.controller.selected ? 2 : 1
                imageSource: library.appearance.format === "square" ? modelData.squareCover || modelData.cover : modelData.cover
                selected: index === library.controller.selected
                appearance: library.appearance
                onChosen: { library.controller.select(index); library.forceActiveFocus() }
            }
        }
    }
}
