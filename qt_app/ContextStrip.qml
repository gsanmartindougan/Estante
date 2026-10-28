import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
GlassButton {
    id: strip
    required property var labels
    property int currentIndex: 0
    property url iconSource
    signal stepped(int delta)
    implicitWidth: content.implicitWidth+24
    implicitHeight: 40
    onClicked: stepped(1)
    contentItem: RowLayout {
        id: content
        spacing: 8
        Image { source: strip.iconSource; visible: source.toString().length>0; Layout.preferredWidth: 26; Layout.preferredHeight: 26; Layout.alignment: Qt.AlignVCenter; fillMode: Image.PreserveAspectFit; sourceSize: Qt.size(52,52); asynchronous: true }
        Label {
            text: strip.labels.length>1 ? strip.labels[(strip.currentIndex-1+strip.labels.length)%strip.labels.length] : ""
            opacity: 0.55; font.pixelSize: 12; Layout.maximumWidth: 70; elide: Text.ElideRight
            TapHandler { onTapped: strip.stepped(-1) }
        }
        Label { text: strip.labels[strip.currentIndex] || "—"; color: strip.palette.accent; font.bold: true; font.pixelSize: 15; Layout.maximumWidth: 120; elide: Text.ElideRight }
        Label {
            text: strip.labels.length>1 ? strip.labels[(strip.currentIndex+1)%strip.labels.length] : ""
            opacity: 0.55; font.pixelSize: 12; Layout.maximumWidth: 70; elide: Text.ElideRight
            TapHandler { onTapped: strip.stepped(1) }
        }
    }
}
