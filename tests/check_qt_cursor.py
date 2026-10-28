"""Cursor follows real input mode across Qt Quick controls and editor pages."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QUrl,QEvent,QPointF,QObject
from PySide6.QtGui import QGuiApplication,QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
def pump():
    deadline=time.monotonic()+.1
    while time.monotonic()<deadline:app.processEvents();time.sleep(.003)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);lib=Library(data_dir=root);game={'id':'one','title':'One','kind':'custom'};lib.put(game)
    c=LibraryController([game],{},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;app.installEventFilter(c);pump()
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    for mode in ('grid','carousel','ps5','list'):
        c.changeView(mode);pump()
        for _ in range(12):c.inputAction.emit('right')
        assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.BlankCursor
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(20,20),QPointF(20,20),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        app.sendEvent(window,event)
        assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.WaitCursor
    c.inputAction.emit('menu');pump()
    assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.BlankCursor
    c.inputAction.emit('back');c.inputAction.emit('save');pump()
    assert c.editing and QGuiApplication.overrideCursor().shape()==Qt.CursorShape.BlankCursor
    # A hover update alone must not switch back to mouse mode.
    c.eventFilter(window,QEvent(QEvent.Type.HoverMove))
    assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.BlankCursor
    c.applicationStateChanged(Qt.ApplicationState.ApplicationInactive)
    assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.WaitCursor
    c.restoreCursor()  # Repeated restore must preserve someone else's cursor override.
    assert QGuiApplication.overrideCursor().shape()==Qt.CursorShape.WaitCursor
    QGuiApplication.restoreOverrideCursor();assert QGuiApplication.overrideCursor() is None
    c.gamepadUsed();c.restoreCursor();assert QGuiApplication.overrideCursor() is None
    c.cancelEdit();c.manager.shutdown();c.idle_timer.stop();app.removeEventFilter(c);window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_CURSOR_OK: all four modes, settings/editor, repeated controller input, mouse restore, focus loss, cursor stack preserved')
