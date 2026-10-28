import QtQuick
import QtQuick.Effects
Image {
    id: artwork
    property real cornerRadius: 12
    layer.enabled: cornerRadius > 0 && status === Image.Ready
    layer.effect: MultiEffect { maskEnabled: true; maskSource: roundedMask }
    Item {
        id: roundedMask
        anchors.fill: parent
        visible: false
        layer.enabled: artwork.layer.enabled
        Rectangle {
            width: artwork.paintedWidth; height: artwork.paintedHeight
            anchors.centerIn: parent
            radius: artwork.cornerRadius
            color: "white"
        }
    }
}
