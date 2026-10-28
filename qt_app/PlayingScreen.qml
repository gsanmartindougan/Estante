pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: screen
    objectName: "playingScreen"
    required property var controller
    ConsoleTheme { id: theme }
    color: theme.window
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(500, screen.width-64)
        spacing: 20
        Image {
            objectName: "playingCover"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: Math.min(240,screen.width*0.3)
            Layout.preferredHeight: Math.min(360,screen.height*0.5)
            source: screen.controller.launchGame.cover || screen.controller.launchGame.squareCover || ""
            sourceSize: Qt.size(240,360)
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: false
        }
        Label { Layout.fillWidth: true; text: qsTr("Jugando"); horizontalAlignment: Text.AlignHCenter; color: theme.muted; font.pixelSize: 18 }
        Label { Layout.fillWidth: true; text: screen.controller.launchGame.title || ""; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: theme.text; font.pixelSize: 28; font.bold: true }
        Label { Layout.fillWidth: true; text: qsTr("La biblioteca se restaurará cuando termine el juego."); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; color: theme.muted }
    }
}
