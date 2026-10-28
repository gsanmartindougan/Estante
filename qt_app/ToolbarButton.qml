import QtQuick
import QtQuick.Controls
GlassButton {
    id: control
    required property string symbol
    required property string label
    implicitWidth: 40
    implicitHeight: 40
    leftPadding: 0; rightPadding: 0
    Accessible.name: label
    ToolTip.visible: hovered || activeFocus
    ToolTip.text: label
    ToolTip.delay: hovered ? 500 : 0
    contentItem: Item {
        Canvas {
            id: drawing
            anchors.centerIn: parent
            width: 24; height: 24
            property color ink: control.palette.buttonText
            onInkChanged: requestPaint()
            onPaint: {
                let c=getContext("2d")
                c.reset(); c.strokeStyle=ink; c.lineWidth=1.8; c.lineCap="round"; c.lineJoin="round"
                c.beginPath()
                if (control.symbol==="add") {
                    c.moveTo(12,5); c.lineTo(12,19); c.moveTo(5,12); c.lineTo(19,12)
                } else if (control.symbol==="settings") {
                    c.arc(12,12,5.5,0,Math.PI*2)
                    for (let i=0;i<8;i++) {
                        let a=i*Math.PI/4
                        c.moveTo(12+Math.cos(a)*7,12+Math.sin(a)*7)
                        c.lineTo(12+Math.cos(a)*9,12+Math.sin(a)*9)
                    }
                    c.moveTo(14,12); c.arc(12,12,2,0,Math.PI*2)
                } else if (control.symbol==="tray") {
                    c.moveTo(4,14);c.lineTo(4,20);c.lineTo(20,20);c.lineTo(20,14)
                    c.moveTo(12,3);c.lineTo(12,14);c.moveTo(8,10);c.lineTo(12,14);c.lineTo(16,10)
                } else if (control.symbol==="exit") {
                    c.arc(12,13,8,-Math.PI*0.32,Math.PI*1.32)
                    c.moveTo(12,3);c.lineTo(12,12)
                }
                c.stroke()
            }
            opacity: control.enabled ? 1 : 0.4
        }
    }
}
