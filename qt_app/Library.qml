pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Gamepad.js" as Navigation

ApplicationWindow {
    property QtObject theme: ConsoleTheme {}
    palette.window: theme.window
    palette.windowText: theme.system.windowText
    palette.base: theme.base
    palette.text: theme.system.text
    palette.button: theme.button
    palette.buttonText: theme.system.buttonText
    palette.highlight: theme.system.highlight
    palette.highlightedText: theme.system.highlightedText
    palette.mid: theme.system.mid
    palette.accent: theme.system.accent
    palette.placeholderText: theme.system.placeholderText
    palette.alternateBase: theme.surface
    font.pixelSize: 15
    id: window
    visible: true
    width: 1440; height: 900
    minimumWidth: 800; minimumHeight: 600
    title: "Estante"
    onClosing: close => { close.accepted = window.controller.requestClose() }
    color: theme.window
    property var controller: libraryController
    readonly property bool playing: controller.busy && !controller.loading
    readonly property real listBodyTop: libraryLoader.item ? libraryLoader.item.listBodyTop : 0
    readonly property real listBodyHeight: libraryLoader.item ? libraryLoader.item.listBodyHeight : 0
    Loader {
        id: libraryLoader
        objectName: "librarySceneLoader"
        anchors.fill: parent
        active: !window.playing
        sourceComponent: LibraryContent { controller: window.controller; hostWindow: window }
    }
    Loader {
        anchors.fill: parent
        active: window.playing
        sourceComponent: PlayingScreen { controller: window.controller }
    }
    onPlayingChanged: if (playing) reclaimTimer.restart()
    Timer { id: reclaimTimer; interval: 500; onTriggered: window.controller.reclaimPlayingMemory() }
    Popup {
        id: saverPopup
        visible: window.controller.screensaverActive
        parent: Overlay.overlay
        x: 0; y: 0; width: window.width; height: window.height
        padding: 0; margins: 0
        z: 1000000
        modal: true
        closePolicy: Popup.NoAutoClose
        background: null
        contentItem: Background {
            primary: window.controller.screensaverImage
            dim: (window.controller.settingsMap.screensaver_dim === undefined ? 35 : window.controller.settingsMap.screensaver_dim)/100
        }
    }
}
