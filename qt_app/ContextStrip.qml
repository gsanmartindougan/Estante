import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Button {
    id: strip
    required property var labels
    property int currentIndex: 0
    property var iconSources: []
    property bool currentOnly: false
    property bool gamepadFocusable: true
    property string gamepadKind: "button"
    property QtObject theme: ConsoleTheme {}
    signal stepped(int delta)
    implicitWidth: content.implicitWidth+24
    implicitHeight: 40
    leftPadding: 12; rightPadding: 12
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    onClicked: stepped(1)
    background: Rectangle {
        radius: 12
        color: Qt.alpha(strip.theme.text, strip.down ? 0.16 : strip.activeFocus ? 0.14 : strip.hovered ? 0.11 : 0.08)
        border.color: strip.activeFocus ? strip.theme.highlight : Qt.alpha(strip.theme.text, 0.2)
        border.width: strip.activeFocus ? 2 : 1
        opacity: strip.enabled ? 1 : 0.55
    }
    contentItem: RowLayout {
        id: content
        spacing: 8
        Repeater {
            model: strip.currentOnly ? 1 : 3
            delegate: RowLayout {
                required property int index
                readonly property int position: strip.currentOnly ? 1 : index
                readonly property int labelIndex: strip.labels.length ? (strip.currentIndex+position-1+strip.labels.length)%strip.labels.length : 0
                readonly property string labelText: strip.labels.length ? strip.labels[labelIndex] : ""
                readonly property url imageSource: strip.iconSources.length ? strip.iconSources[labelIndex] : ""
                readonly property int maxLabelWidth: strip.currentOnly ? 108 : position===1 ? 120 : 70
                Layout.alignment: strip.currentOnly ? Qt.AlignHCenter|Qt.AlignVCenter : Qt.AlignVCenter
                Layout.preferredWidth: implicitWidth
                Layout.preferredHeight: 32
                spacing: strip.currentOnly && imageSource.toString().length>0 ? 8 : 0
                Accessible.role: Accessible.Button
                Accessible.name: labelText
                Image {
                    Layout.preferredWidth: source.toString().length>0 ? (strip.currentOnly ? 20 : 24) : 0
                    Layout.preferredHeight: Layout.preferredWidth
                    source: parent.imageSource
                    visible: source.toString().length>0
                    fillMode: Image.PreserveAspectFit
                    sourceSize: Qt.size(48,48)
                    asynchronous: true
                }
                Label {
                    id: label
                    Layout.preferredWidth: Math.min(parent.maxLabelWidth,implicitWidth)
                    text: parent.labelText || (position===1 ? "—" : "")
                    color: strip.palette.buttonText
                    font.bold: strip.currentOnly || position===1
                    font.pixelSize: strip.currentOnly ? 12 : position===1 ? 18 : 11
                    opacity: strip.currentOnly || position===1 ? 1 : 0.56
                    elide: Text.ElideRight
                }
                MouseArea { anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton
                    ToolTip.visible: containsMouse && parent.imageSource.toString().length>0
                    ToolTip.text: parent.labelText
                    ToolTip.delay: 500
                }
                TapHandler {
                    enabled: !strip.currentOnly && position!==1
                    onTapped: strip.stepped(position===0 ? -1 : 1)
                }
            }
        }
    }
}
