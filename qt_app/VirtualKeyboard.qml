pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: keyboard
    objectName: "builtinKeyboard"
    required property var controller
    property QtObject theme: ConsoleTheme {}
    property var target: null
    property int row: 1
    property int column: 0
    property bool uppercase: false
    property bool symbols: false
    property bool multiline: false
    readonly property var buttons: controller.controllerButtons
    readonly property real keyHeight: Math.max(30,Math.min(50,(parent.height-210)/6))
    readonly property var rows: symbols ? ["1234567890","@#€$%&*+-=","()[]{}<>/\\",".,:;!?_~^|","'\"`©®™…°§"] : ["1234567890",uppercase ? "QWERTYUIOP" : "qwertyuiop",uppercase ? "ASDFGHJKLÑ" : "asdfghjklñ",uppercase ? "ZXCVBNM" : "zxcvbnm",uppercase ? "ÁÉÍÓÚÜÑ¿¡" : "áéíóúüñ¿¡"]
    readonly property var actions: [
        {label: uppercase ? "abc" : "ABC",action:"case",weight:1},
        {label: symbols ? "abc" : "#+=",action:"symbols",weight:1},
        {label:"←",action:"cursorLeft",weight:.7},
        {label:qsTr("Espacio"),action:"space",weight:2.8},
        {label:"→",action:"cursorRight",weight:.7},
        {label:"⌫",action:"erase",weight:1},
        ...(multiline ? [{label:"↵",action:"newline",weight:.8}] : []),
        {label:qsTr("Listo"),action:"done",weight:1.4}
    ]
    signal finished()
    modal: true
    padding: 20
    width: Math.min(1060,parent.width-32)
    height: Math.min(parent.height-24,contentItem.implicitHeight+padding*2)
    x: (parent.width-width)/2
    y: parent.height-height-12
    closePolicy: Popup.CloseOnEscape
    background: MaterialSurface { color: keyboard.theme.surface; radius: 24 }
    Overlay.modal: Rectangle { color: Qt.alpha(keyboard.palette.shadow,.22) }
    function openFor(item) {
        target=item
        buffer.text=item.text || ""
        buffer.echoMode=item.echoMode===TextInput.NoEcho ? TextInput.NoEcho : item.echoMode===TextInput.Password || item.echoMode===TextInput.PasswordEchoOnEdit ? TextInput.Password : TextInput.Normal
        multiline=item.gamepadMultiline===true || item.textDocument!==undefined
        uppercase=false; symbols=false; row=1; column=0
        open()
        buffer.cursorPosition=item.cursorPosition!==undefined ? item.cursorPosition : buffer.text.length
        if (item.selectionStart!==undefined && item.selectionEnd>item.selectionStart) buffer.select(item.selectionStart,item.selectionEnd)
        inputRoot.forceActiveFocus()
    }
    function insert(text) {
        const a=buffer.selectionStart>=0 ? buffer.selectionStart : buffer.cursorPosition
        const b=buffer.selectionEnd>=0 ? buffer.selectionEnd : buffer.cursorPosition
        buffer.text=buffer.text.slice(0,a)+text+buffer.text.slice(b)
        buffer.cursorPosition=a+text.length
    }
    function erase() {
        if (buffer.selectionEnd>buffer.selectionStart) { insert(""); return }
        let cursor=buffer.cursorPosition
        if (!cursor) return
        let start=cursor-1
        const last=buffer.text.charCodeAt(start)
        if (start>0 && last>=0xdc00 && last<=0xdfff) start--
        buffer.text=buffer.text.slice(0,start)+buffer.text.slice(cursor)
        buffer.cursorPosition=start
    }
    function moveCursor(step) {
        let next=buffer.cursorPosition+step
        if (next>0 && next<buffer.text.length) {
            const code=buffer.text.charCodeAt(next)
            if (code>=0xdc00 && code<=0xdfff) next+=step
        }
        buffer.cursorPosition=Math.max(0,Math.min(buffer.text.length,next))
    }
    function commit() {
        if (target) { target.text=buffer.text; if (target.cursorPosition!==undefined) target.cursorPosition=buffer.cursorPosition }
        close()
    }
    function perform(action) {
        if (action==="case") { uppercase=!uppercase; symbols=false }
        else if (action==="symbols") symbols=!symbols
        else if (action==="space") insert(" ")
        else if (action==="erase") erase()
        else if (action==="cursorLeft") moveCursor(-1)
        else if (action==="cursorRight") moveCursor(1)
        else if (action==="newline") insert("\n")
        else if (action==="done") commit()
    }
    function keyAt(r,c) { return r===rows.length ? actionKeys.itemAt(c) : keyRows.itemAt(r).keys.itemAt(c) }
    function keyCount(r) { return r===rows.length ? actions.length : Array.from(rows[r]).length }
    function navigate(action) {
        if (action==="back") { close(); return }
        if (action==="save") { commit(); return }
        if (action==="page_previous") { erase(); return }
        if (action==="page_next") { insert(" "); return }
        if (action==="confirm") {
            if (row===rows.length) perform(actions[column].action)
            else insert(Array.from(rows[row])[column])
            return
        }
        if (action==="left" || action==="right") column=(column+(action==="left" ? -1 : 1)+keyCount(row))%keyCount(row)
        else if (action==="up" || action==="down") {
            const next=Math.max(0,Math.min(rows.length,row+(action==="up" ? -1 : 1)))
            const previous=keyAt(row,column)
            if (!previous) return
            const center=previous.mapToItem(inputRoot,previous.width/2,0).x
            let best=0,distance=Infinity
            for (let i=0;i<keyCount(next);++i) {
                const key=keyAt(next,i)
                if (!key) continue
                const d=Math.abs(key.mapToItem(inputRoot,key.width/2,0).x-center)
                if (d<distance) { distance=d; best=i }
            }
            row=next; column=best
        }
    }
    onClosed: { if (target) target.forceActiveFocus(); target=null; buffer.text=""; finished() }
    contentItem: FocusScope {
        id: inputRoot
        implicitHeight: body.implicitHeight
        Keys.onPressed: event => {
            if (event.key===Qt.Key_Escape) keyboard.close()
            else if (event.key===Qt.Key_Return || event.key===Qt.Key_Enter) { if (keyboard.multiline && !(event.modifiers&Qt.ControlModifier)) keyboard.insert("\n"); else keyboard.commit() }
            else if (event.key===Qt.Key_S && event.modifiers&Qt.ControlModifier) keyboard.commit()
            else if (event.key===Qt.Key_Backspace) keyboard.erase()
            else if (event.key===Qt.Key_A && event.modifiers&Qt.ControlModifier) buffer.selectAll()
            else if (event.key===Qt.Key_Left) keyboard.moveCursor(-1)
            else if (event.key===Qt.Key_Right) keyboard.moveCursor(1)
            else if (event.text && !(event.modifiers&(Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier))) keyboard.insert(event.text)
            else { event.accepted=false; return }
            event.accepted=true
        }
        ColumnLayout {
            id: body
            width: parent.width; spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("Teclado de Estante"); font.bold: true; font.pixelSize: 20; Layout.fillWidth: true }
                EditorButton { text: qsTr("Cancelar")+" · "+keyboard.buttons.back; onClicked: keyboard.close() }
            }
            GlassField {
                id: buffer; objectName: "keyboardBuffer"
                Layout.fillWidth: true; readOnly: true; persistentSelection: true
                focusPolicy: Qt.NoFocus; gamepadFocusable: false; font.pixelSize: 20
                Rectangle {
                    objectName: "keyboardCaret"
                    x: Math.max(buffer.leftPadding,Math.min(buffer.width-buffer.rightPadding-2,buffer.cursorRectangle.x))
                    y: buffer.cursorRectangle.y
                    width: 2; height: Math.max(16,buffer.cursorRectangle.height)
                    color: buffer.palette.highlight
                    visible: keyboard.visible && buffer.selectionStart===buffer.selectionEnd
                }
            }
            Repeater {
                id: keyRows
                model: keyboard.rows
                delegate: Row {
                    id: keyRow
                    required property string modelData
                    required property int index
                    property alias keys: keys
                    objectName: "keyboardRow"+index
                    Layout.fillWidth: true
                    spacing: 7
                    Repeater {
                        id: keys
                        model: Array.from(keyRow.modelData)
                        delegate: KeyboardKey {
                            required property int index
                            required property string modelData
                            width: Math.max(20,(keyRow.width-keyRow.spacing*(Array.from(keyRow.modelData).length-1))/Array.from(keyRow.modelData).length); height: keyboard.keyHeight
                            text: modelData
                            selected: keyboard.row===keyRow.index && keyboard.column===index
                            onClicked: { keyboard.row=keyRow.index; keyboard.column=index; keyboard.insert(modelData) }
                        }
                    }
                }
            }
            Row {
                id: actionRow
                Layout.fillWidth: true
                spacing: 7
                Repeater {
                    id: actionKeys
                    model: keyboard.actions
                    delegate: KeyboardKey {
                        required property int index
                        required property var modelData
                        width: Math.max(20,(actionRow.width-7*(keyboard.actions.length-1))*modelData.weight/keyboard.actions.reduce((total,key)=>total+key.weight,0))
                        height: keyboard.keyHeight
                        text: modelData.label
                        suggested: modelData.action==="done"
                        selected: keyboard.row===keyboard.rows.length && keyboard.column===index
                        onClicked: { keyboard.row=keyboard.rows.length; keyboard.column=index; keyboard.perform(modelData.action) }
                    }
                }
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: keyboard.theme.muted
                text: qsTr("Cruceta: elegir")+" · "+keyboard.buttons.confirm+qsTr(": escribir")+" · "+keyboard.buttons.save+qsTr(": listo")+" · "+keyboard.buttons.bumpers+qsTr(": borrar / espacio")
            }
        }
    }
}
