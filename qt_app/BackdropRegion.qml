import QtQuick
import QtQuick.Effects
Item {
    id: region
    property url source
    property string position: "full"
    property bool paired: false
    property real blur: 0
    property bool filler: false
    clip: true
    Image {
        id: picture
        objectName: region.filler ? "backgroundFill" : "heroImage"
        anchors.fill: parent
        anchors.margins: region.filler ? -48 : 0
        source: region.visible ? region.source : ""
        sourceSize: Qt.size(Math.min(2560,width*Screen.devicePixelRatio),Math.min(1440,height*Screen.devicePixelRatio))
        asynchronous: true; cache: false
        fillMode: region.filler || region.paired || region.position==="full" ? Image.PreserveAspectCrop : Image.PreserveAspectFit
        verticalAlignment: region.position==="top" ? Image.AlignTop : region.position==="lower" ? Image.AlignBottom : Image.AlignVCenter
        layer.enabled: status===Image.Ready && (region.blur>0 || !region.filler && !region.paired && region.position!=="full")
        layer.effect: MultiEffect {
            blurEnabled: region.blur>0; blur: region.blur; blurMax: 40
            maskEnabled: !region.filler && !region.paired && region.position!=="full"
            maskSource: positionMask
            maskThresholdMin: 0.5; maskSpreadAtMin: 0.5
        }
    }
    Item {
        id: positionMask
        anchors.fill: parent
        visible: false
        layer.enabled: picture.layer.enabled && !region.filler && !region.paired && region.position!=="full"
        Rectangle {
            x: (positionMask.width-picture.paintedWidth)/2
            y: region.position==="lower" ? positionMask.height-picture.paintedHeight : 0
            width: picture.paintedWidth; height: picture.paintedHeight
            rotation: region.position==="lower" ? 180 : 0
            gradient: Gradient {
                GradientStop { position: 0; color: "white" }
                GradientStop { position: 0.45; color: "white" }
                GradientStop { position: 0.65; color: "#d9ffffff" }
                GradientStop { position: 0.82; color: "#59ffffff" }
                GradientStop { position: 1; color: "transparent" }
            }
        }
    }
}
