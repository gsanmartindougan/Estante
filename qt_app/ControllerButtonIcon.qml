import QtQuick

Item {
    id: control
    required property string button
    required property string controllerType
    readonly property var glyphs: ({
        sony: {play:"square", save:"triangle", back:"circle", menu:"options"},
        xbox: {play:"X", save:"Y", back:"B", menu:"menu"},
        nintendo: {play:"Y", save:"X", back:"A", menu:"plus"}
    })
    implicitWidth: 34
    implicitHeight: 34
    Image {
        anchors.centerIn: parent
        width: 32; height: 32
        source: Qt.resolvedUrl("assets/controller/"+(control.glyphs[control.controllerType] ? control.controllerType : "xbox")+"/"+
                               ((control.glyphs[control.controllerType] || control.glyphs.xbox)[control.button])+".svg")
        fillMode: Image.PreserveAspectFit
        sourceSize: Qt.size(192,192)
        smooth: true
        mipmap: true
        asynchronous: true
        Accessible.ignored: true
    }
}
