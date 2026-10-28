"""Controller editing and native fallback through the real QML keyboard, offscreen."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,tempfile,time,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.18):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);lib=Library(data_dir=root);game={'id':'one','title':'Original','kind':'custom','metadata':{'description':'Original description'}};lib.put(game)
    c=LibraryController([game],{'language':'es','controller_type':'nintendo','onscreen_keyboard':'builtin','keyboard_fallback':True},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def evaluate(item,code):
        expression=QQmlExpression(engine.rootContext(),item,code)
        result,_=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return result
    def action(name):c.inputAction.emit(name);pump(.04)
    def open_for(field):
        field.forceActiveFocus();action('confirm');pump()
        keyboard=window.findChild(QObject,'builtinKeyboard')
        assert keyboard and keyboard.property('visible')
        assert not c.nativeKeyboard.active
        assert len(app.topLevelWindows())==1
        return keyboard,find('keyboardBuffer')
    c.edit();pump();editor=window.findChild(QObject,'gameEditor');QMetaObject.invokeMethod(editor,'showManual');pump()
    title=find('title');title.setProperty('text','abCD');evaluate(title,'select(2,4)')
    before=lib.file.read_bytes()
    keyboard,buffer=open_for(title)
    keyboard.setProperty('row',2);keyboard.setProperty('column',9);action('confirm')
    assert buffer.property('text')=='abñ',buffer.property('text')
    assert title.property('text')=='abCD'  # No edit reaches the target before Listo.
    action('save');pump();assert title.property('text')=='abñ' and c.editing
    assert lib.file.read_bytes()==before  # Keyboard commits a field, never the whole editor.
    assert not window.findChild(QObject,'builtinKeyboard')  # Loaded lazily, destroyed on close.
    keyboard,buffer=open_for(title);action('confirm');action('back');pump()
    assert title.property('text')=='abñ'
    title.setProperty('text','A😀B');title.setProperty('cursorPosition',3)
    keyboard,buffer=open_for(title);action('page_previous')
    assert buffer.property('text')=='AB'
    action('page_next');assert buffer.property('text')=='A B'
    evaluate(keyboard,"perform('symbols')");keyboard.setProperty('row',1);keyboard.setProperty('column',0);action('confirm')
    assert '@' in buffer.property('text')
    evaluate(keyboard,"perform('case')");keyboard.setProperty('row',1);keyboard.setProperty('column',0);action('confirm')
    assert 'Q' in buffer.property('text')
    for _ in range(10):action('down')
    assert keyboard.property('row')==5
    assert 0<=keyboard.property('column')<7
    window.grabWindow().save('/tmp/estante-builtin-keyboard.png')
    action('back');pump()
    title.setProperty('echoMode',2);title.setProperty('text','secret-test')
    keyboard,buffer=open_for(title)
    assert evaluate(buffer,'echoMode===2') and 'secret-test' not in buffer.property('displayText')
    action('back');title.setProperty('echoMode',0)
    for width,height in [(800,600),(1440,900)]:
        window.resize(width,height);pump()
        keyboard,buffer=open_for(title)
        assert keyboard.property('x')>=0 and keyboard.property('y')>=0
        assert keyboard.property('x')+keyboard.property('width')<=window.width()+1
        assert keyboard.property('y')+keyboard.property('height')<=window.height()+1
        assert buffer.property('persistentSelection')
        assert find('keyboardCaret').height()>0
        for mode in (False,True):
            keyboard.setProperty('symbols',mode);pump(.04)
            for row_index in range(5):
                row_item=find('keyboardRow'+str(row_index))
                keys=[item for item in row_item.childItems() if item.property('text') is not None]
                assert keys and abs(min(item.x() for item in keys))<1
                assert abs(max(item.x()+item.width() for item in keys)-row_item.width())<1
        window.grabWindow().save('/tmp/estante-keyboard-full-rows.png')
        action('back');pump()
        assert not window.findChild(QObject,'builtinKeyboard')

    description=find('description');description.setProperty('text','Line');description.setProperty('cursorPosition',4)
    keyboard,buffer=open_for(description);assert keyboard.property('multiline')
    evaluate(keyboard,"perform('newline')");assert buffer.property('text')=='Line\n'
    action('save');pump();assert description.property('text')=='Line\n'
    # Unsupported KDE on a non-KWin session falls back without executing a process.
    c.settings['onscreen_keyboard']='kde'
    with patch.object(c.nativeKeyboard,'kwin',return_value=None),patch.object(c.nativeKeyboard,'startCosmic') as process:
        keyboard,buffer=open_for(title);process.assert_not_called();action('back');pump()
        c.settings['keyboard_fallback']=False
        title.forceActiveFocus();action('confirm');pump()
        assert c.nativeKeyboard.notice and not window.findChild(QObject,'builtinKeyboard')
        action('back')
    c.settings['onscreen_keyboard']='disabled';c.settings['keyboard_fallback']=True
    title.forceActiveFocus();action('confirm');pump()
    assert 'desactivado' in c.nativeKeyboard.notice and not window.findChild(QObject,'builtinKeyboard')
    action('back')
    c.cancelEdit();c.nativeKeyboard.hide();c.restoreCursor();c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_BUILTIN_KEYBOARD_OK: controller layout/edit/cursor/selection/accents/symbols/password/multiline/commit/cancel, lazy release and native fallback; no external processes')
