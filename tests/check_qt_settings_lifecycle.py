"""Closing settings destroys the loaded page; reopening starts collapsed at the top."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys, time, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QUrl, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from shiboken6 import isValid
from qt_app.main import LibraryController
from i18n import set_language

app = QApplication([])
app.setDesktopFileName('io.github.estante.Test')
set_language('es')
def pump():
    end = time.monotonic() + .2
    while time.monotonic() < end:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():
        yield from visual(child)

with tempfile.TemporaryDirectory() as folder:
    c = LibraryController([], {'language': 'es'}, Path(folder), allow_launch=False)
    engine = QQmlApplicationEngine()
    errors = []
    engine.warnings.connect(lambda rows: errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController', c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'qt_app/Library.qml')))
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]
    c.window = window
    pump()
    panel = window.findChild(QObject, 'managementPanel')
    loader = window.findChild(QObject, 'managementPageLoader')
    assert loader.property('item') is None
    for close_method in ('close', 'reject', 'back'):
        panel.openSection(4, False)
        pump()
        page = loader.property('item')
        groups = [i for i in visual(page) if i.objectName().startswith('settingsGroup:')]
        assert groups and all(not i.property('expanded') for i in groups)
        flick = next(i for i in visual(page) if i.metaObject().indexOfProperty('contentY') >= 0)
        assert flick.property('contentY') == 0
        for group in groups:
            group.setProperty('expanded', True)
        pump()
        flick.setProperty('contentY', 120)
        # Draft data lives independently of the page and must survive its destruction.
        panel.setProperty('settingsDraft', {'["language"]': 'en'})
        if close_method == 'back':
            panel.focusSection()
            c.inputAction.emit('back')
        else:
            getattr(panel, close_method)()
        pump()
        assert loader.property('item') is None
        assert not isValid(page), 'Closed settings page was retained'
        assert all(not isValid(group) for group in groups)
        assert panel.property('settingsDraft') == {'["language"]': 'en'}
    c.restoreCursor()
    c.manager.shutdown()
    c.idle_timer.stop()
    window.close()
    pump()
assert not errors, '\n'.join(errors)
print('QT_SETTINGS_LIFECYCLE_OK: page destroyed on close/reject; repeated reopen collapsed with scroll at zero; drafts preserved')
