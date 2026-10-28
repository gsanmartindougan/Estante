pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation
ColumnLayout {
    property QtObject theme: ConsoleTheme {}
    id: setting
    required property var spec
    property var controller: null
    property bool compact: false
    property bool inlineChoices: false
    property bool hideLabel: false
    objectName: "settingRow:"+JSON.stringify(spec.path)
    property var settingValue: spec.value
    function focusControl() { let controls=Navigation.controls(setting); if (controls.length) controls[0].forceActiveFocus() }
    spacing: 10
    Label {
        text: setting.spec.group || ""
        visible: Boolean(setting.spec.sectionStart)
        font.pixelSize: 20; font.bold: true; color: theme.text
        Layout.topMargin: 20; Layout.bottomMargin: 8
    }
    Label { visible: setting.spec.type !== "bool" && !setting.hideLabel; text: setting.compact && setting.spec.path[0].endsWith("_unit") ? qsTr("Unidad") : setting.spec.label; color: theme.text; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    Loader {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        sourceComponent: setting.spec.type === "background" ? backgrounds : setting.spec.type === "bool" ? checkbox : setting.spec.type === "choice" ? setting.inlineChoices ? radios : combo : setting.spec.type === "number" ? slider : field
    }

    Component {
        id: checkbox
        GlassCheck { width: implicitWidth; height: implicitHeight; anchors.left: parent.left; text: setting.spec.label; checked: Boolean(setting.spec.value); onToggled: setting.settingValue=checked }
    }
    Component {
        id: radios
        GridLayout {
            width: parent.width; columns: setting.compact ? 2 : 1; columnSpacing: 6; rowSpacing: 2
            Repeater {
                model: setting.spec.options
                delegate: RadioButton {
                    id: option
                    required property string modelData
                    required property int index
                    property bool gamepadFocusable: true
                    property string gamepadKind: "button"
                    objectName: "radio:"+JSON.stringify(setting.spec.path)+":"+index
                    Layout.fillWidth: true
                    implicitHeight: setting.compact ? 32 : 40
                    leftPadding: 28
                    text: modelData; autoExclusive: false
                    checked: setting.settingValue===setting.spec.values[index]
                    onClicked: setting.settingValue=setting.spec.values[index]
                    indicator: Rectangle {
                        x: 2; y: (option.height-height)/2
                        width: 20; height: 20; radius: 10
                        color: option.checked ? option.palette.accent : "transparent"
                        border.width: 2; border.color: option.checked ? option.palette.accent : Qt.alpha(option.palette.text,0.25)
                        Rectangle { anchors.centerIn: parent; width: 7; height: 7; radius: 4; color: option.palette.window; visible: option.checked }
                    }
                    background: Rectangle { color: option.activeFocus ? Qt.alpha(option.palette.accent,0.12) : "transparent"; radius: 8; border.width: option.activeFocus ? 2 : 0; border.color: option.palette.accent }
                }
            }
        }
    }
    Component {
        id: combo
        GlassCombo {
            width: parent.width
            model: setting.spec.options
            currentIndex: Math.max(0, setting.spec.values.indexOf(setting.spec.value))
            onActivated: index => { setting.settingValue=setting.spec.values[index] }
        }
    }
    Component {
        id: slider
        RowLayout {
            width: parent.width
            GlassSlider {
                Layout.fillWidth: true
                from: setting.spec.minimum; to: setting.spec.maximum
                value: Number(setting.spec.value)
                onValueChanged: setting.settingValue=Math.round(value)
            }
            Label { text: String(setting.settingValue); color: theme.text; Layout.preferredWidth: 50 }
        }
    }
    Component {
        id: backgrounds
        ColumnLayout {
            id: chooser
            property bool expanded: false
            width: parent.width; spacing: 10
            GlassButton {
                objectName: "backgroundChooser:"+JSON.stringify(setting.spec.path)
                Layout.fillWidth: true
                text: qsTr("Elegir fondo")+" · "+(setting.spec.values.indexOf(setting.settingValue)>=0 ? setting.spec.options[setting.spec.values.indexOf(setting.settingValue)] : qsTr("Personalizado"))
                onClicked: { chooser.expanded=!chooser.expanded; if (!chooser.expanded) custom.visible=false }
            }
            GridLayout {
                id: gallery
                visible: chooser.expanded
                Layout.fillWidth: true
                columns: 3; columnSpacing: 8; rowSpacing: 8
                Repeater {
                    model: setting.spec.values
                    delegate: EditorButton {
                        id: choice
                        required property string modelData
                        required property int index
                        objectName: "backgroundOption:"+JSON.stringify(setting.spec.path)+":"+index
                        Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0
                        implicitHeight: Math.max(52,(gallery.width-16)/3*9/16)+28
                        highlighted: setting.settingValue===modelData
                        Accessible.name: setting.spec.options[index]
                        onClicked: setting.settingValue=modelData
                        leftPadding: 4; rightPadding: 4; topPadding: 4; bottomPadding: 4
                        contentItem: ColumnLayout {
                            spacing: 4
                            Item {
                                Layout.fillWidth: true; Layout.fillHeight: true
                                Image {
                                    objectName: "settingsBackgroundThumbnail"
                                    anchors.fill: parent
                                    source: choice.visible && setting.controller ? setting.controller.backgroundPreview(choice.modelData) : ""
                                    sourceSize: Qt.size(240,135)
                                    asynchronous: true; cache: false; fillMode: Image.PreserveAspectCrop
                                }
                            }
                            Label { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: setting.spec.options[choice.index]; color: choice.highlighted ? choice.palette.highlightedText : choice.palette.buttonText; font.pixelSize: 12 }
                        }
                    }
                }
            }
            Label { visible: chooser.expanded && setting.spec.values.indexOf(setting.settingValue)<0; text: qsTr("Imagen personalizada seleccionada"); opacity: .7; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            GlassButton { visible: chooser.expanded; text: custom.visible ? qsTr("Ocultar imagen personalizada") : qsTr("Usar otra imagen…"); onClicked: custom.visible=!custom.visible }
            GlassField { id: custom; visible: false; Layout.fillWidth: true; placeholderText: qsTr("Ruta de una imagen personalizada"); text: setting.spec.values.indexOf(setting.settingValue)<0 ? setting.settingValue : ""; onTextEdited: if (text.trim()) setting.settingValue=text.trim() }
        }
    }
    Component {
        id: field
        GlassField {
            width: parent.width
            text: String(setting.spec.value)
            echoMode: setting.spec.secret ? TextInput.Password : TextInput.Normal
            onTextChanged: setting.settingValue = setting.spec.type === "number" ? Number(text) : text
        }
    }
}
