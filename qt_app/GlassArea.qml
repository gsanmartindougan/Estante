import QtQuick
import QtQuick.Controls
TextArea {
    id: control
    property bool gamepadFocusable: true
    property string gamepadKind: "text"
    property bool gamepadMultiline: true
    leftPadding: 14
    rightPadding: 14
    selectByMouse: true
    wrapMode: TextEdit.Wrap
    topPadding: 10
    bottomPadding: 10
    hoverEnabled: true
    selectionColor: palette.highlight
    selectedTextColor: palette.highlightedText
    placeholderTextColor: palette.placeholderText
    background: InputSurface {
        fillColor: control.palette.base
        inkColor: control.palette.text
        accentColor: control.palette.accent
        focused: control.activeFocus
        hovered: control.hovered
        opacity: control.enabled ? 1 : 0.55
    }
}
