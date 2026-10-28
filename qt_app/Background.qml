pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
Item {
    id: background
    property color fallbackColor: "#151515"
    property url primary
    property url secondary
    property string split: "single"
    property string position: "full"
    property real blur: 0
    property string fillMode: "blur"
    property url fillPrimary
    property url fillSecondary
    property real fillBlur: blur
    property real dim: 0.5
    property bool second: split !== "single" && secondary.toString().length>0
    readonly property real band: Math.min(128,Math.min(width,height)*0.12)
    readonly property real axisX: split==="horizontal" ? 0 : split==="vertical" ? width : 2*width*height*height/Math.max(1,width*width+height*height)
    readonly property real axisY: split==="vertical" ? 0 : split==="horizontal" ? height : 2*width*width*height/Math.max(1,width*width+height*height)
    readonly property real halfBand: band/Math.max(1,Math.sqrt(axisX*axisX+axisY*axisY))/2
    Rectangle { anchors.fill: parent; color: background.fallbackColor }
    // GTK: each image owns its region, including half the blending band.
    Item {
        id: seam
        anchors.fill: parent; visible: false; layer.enabled: background.second
        Shape {
            anchors.fill: parent
            ShapePath {
                strokeWidth: 0
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: background.axisX; y2: background.axisY
                    GradientStop { position: 0.5-background.halfBand; color: "white" }
                    GradientStop { position: 0.5+background.halfBand; color: "transparent" }
                }
                startX: 0; startY: 0
                PathLine { x: seam.width; y: 0 }
                PathLine { x: seam.width; y: seam.height }
                PathLine { x: 0; y: seam.height }
                PathLine { x: 0; y: 0 }
            }
        }
    }
    Repeater {
        model: 2
        delegate: Item {
            id: composition
            required property int index
            property bool filler: index===0
            anchors.fill: parent
            visible: !filler || background.position!=="full"
            BackdropRegion {
                x: background.split==="vertical" && background.second ? background.width/2-background.band/2 : 0
                y: background.split==="horizontal" && background.second ? background.height/2-background.band/2 : 0
                width: background.split==="vertical" && background.second ? background.width/2+background.band/2 : background.width
                height: background.split==="horizontal" && background.second ? background.height/2+background.band/2 : background.height
                source: background.second ? composition.filler && background.fillMode==="dominant" ? background.fillSecondary : background.secondary : ""
                visible: background.second
                paired: true; filler: composition.filler
                position: background.position
                blur: composition.filler ? background.fillMode==="dominant" ? 0 : background.fillBlur : background.blur
            }
            Item {
                anchors.fill: parent
                layer.enabled: background.second
                layer.effect: MultiEffect { maskEnabled: true; maskSource: seam; maskThresholdMin: 0.5; maskSpreadAtMin: 0.5 }
                BackdropRegion {
                    objectName: composition.filler ? "primaryFillRegion" : "primaryHeroRegion"
                    width: background.split==="vertical" && background.second ? background.width/2+background.band/2 : background.width
                    height: background.split==="horizontal" && background.second ? background.height/2+background.band/2 : background.height
                    source: composition.filler && background.fillMode==="dominant" ? background.fillPrimary : background.primary
                    paired: background.second; filler: composition.filler
                    position: background.position
                    blur: composition.filler ? background.fillMode==="dominant" ? 0 : background.fillBlur : background.blur
                }
            }
        }
    }
    Rectangle { anchors.fill: parent; color: "black"; opacity: background.dim }
}
