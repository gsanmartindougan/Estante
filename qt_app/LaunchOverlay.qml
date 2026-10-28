pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls

Rectangle {
    property QtObject theme: ConsoleTheme {}
    id: overlay
    required property var controller
    property var originItem: null
    property real finalWidth: Math.min(300,width*0.35)
    property real finalHeight: controller.appearance.format === "square" ? finalWidth : finalWidth*1.5
    property bool capture: originItem && originItem.width>0 && (originItem.status === undefined || originItem.status === Image.Ready)
    visible: controller.loading
    color: theme.text
    z: 20
    MouseArea { anchors.fill: parent }
    Background {
        anchors.fill: parent
        primary: overlay.visible ? overlay.controller.launchGame.banner : ""
        blur: 0.5; dim: 0.55
    }
    onVisibleChanged: {
        transition.stop()
        if (visible) {
            let point=capture ? originItem.mapToItem(overlay,0,0) : Qt.point(width/2-finalWidth/2,height/2-finalHeight/2-40)
            moving.x=point.x; moving.y=point.y
            moving.width=capture ? originItem.width : finalWidth
            moving.height=capture ? originItem.height : finalHeight
            snapshot.scheduleUpdate()
            transition.start()
        }
    }
    Item {
        id: moving
        ShaderEffectSource {
            id: snapshot
            anchors.fill: parent
            visible: overlay.capture
            sourceItem: overlay.visible && overlay.capture ? overlay.originItem : null
            hideSource: overlay.visible
            live: false
        }
        RoundedImage {
            anchors.fill: parent
            visible: !overlay.capture
            source: overlay.visible && !overlay.capture ? overlay.controller.appearance.format === "square" ? overlay.controller.launchGame.squareCover || overlay.controller.launchGame.cover : overlay.controller.launchGame.cover : ""
            sourceSize: Qt.size(400,600)
            asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit
            cornerRadius: overlay.controller.appearance.radius
        }
    }
    ParallelAnimation {
        id: transition
        NumberAnimation { target: moving; property: "x"; to: (overlay.width-overlay.finalWidth)/2; duration: 280; easing.type: Easing.InOutCubic }
        NumberAnimation { target: moving; property: "y"; to: (overlay.height-overlay.finalHeight)/2-40; duration: 280; easing.type: Easing.InOutCubic }
        NumberAnimation { target: moving; property: "width"; to: overlay.finalWidth; duration: 280; easing.type: Easing.InOutCubic }
        NumberAnimation { target: moving; property: "height"; to: overlay.finalHeight; duration: 280; easing.type: Easing.InOutCubic }
    }
    Column {
        x: (overlay.width-width)/2
        y: (overlay.height+overlay.finalHeight)/2-20
        spacing: 16
        BusyIndicator { anchors.horizontalCenter: parent.horizontalCenter; running: overlay.visible }
        Label { text: overlay.controller.status; color: theme.text; font.pixelSize: 24 }
    }
}
