import QtQuick

// Soft tonal surfaces follow the system accent and its light/dark preference.
QtObject {
    property SystemPalette system: SystemPalette { colorGroup: SystemPalette.Active }
    readonly property bool pastel: typeof libraryController === "undefined" || !libraryController || libraryController.settingsMap.ui_color_mode !== "system"
    readonly property bool dark: (system.window.r*0.2126 + system.window.g*0.7152 + system.window.b*0.0722) < 0.5
    readonly property real hue: system.accent.hslHue >= 0 ? system.accent.hslHue : system.highlight.hslHue >= 0 ? system.highlight.hslHue : 0.65
    readonly property color window: system.window
    readonly property color shadow: "#000000"
    readonly property color surface: pastel ? Qt.hsla((hue+0.035)%1, 0.30, dark ? 0.18 : 0.89, 1) : system.window
    readonly property color base: pastel ? Qt.hsla((hue+0.985)%1, 0.24, dark ? 0.10 : 0.97, 1) : system.base
    readonly property color button: pastel ? Qt.hsla(hue, 0.34, dark ? 0.24 : 0.84, 1) : system.button
    readonly property color text: system.windowText
    readonly property color muted: Qt.alpha(system.windowText, 0.72)
    readonly property color highlight: system.accent
}
