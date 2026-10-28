"""Manual launcher close is controller-accessible and independent of exit preferences."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as root:
    settings={'close_steam_on_exit':False,'close_faugus_on_exit':False,'close_heroic_on_exit':False}
    c=LibraryController([],settings,Path(root),allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump()
    def find(name):return next(i for i in visual(window.contentItem()) if i.objectName()==name)
    c.launchers.apply_snapshot(dict(steam='open',faugus='open',heroic='open'),'')
    c.inputAction.emit('menu');pump()
    assert not find('settingsGroup:Inicio').property('expanded')
    panel=window.findChild(QObject,'managementPanel')
    panel.setProperty('section',7);pump();panel.focusSection();pump()
    c.inputAction.emit('down');pump()
    assert window.activeFocusItem().objectName()=='closeLauncher:steam'
    assert window.activeFocusItem().mapToItem(window.contentItem(),0,0).y() > next(i for i in visual(window.contentItem()) if i.property('sectionId')==7 and i.property('text')=='Lista').mapToItem(window.contentItem(),0,0).y()
    for client in ('steam','faugus','heroic'):
        button=find('closeLauncher:'+client);assert button.property('enabled')
        with patch('qt_app.launcher_processes.running_clients',return_value={client}),patch('qt_app.launcher_processes.close_client') as close:
            button.forceActiveFocus();c.inputAction.emit('confirm')
            end=time.monotonic()+5
            while c.manager.busy and time.monotonic()<end:pump(.02)
            assert not c.manager.busy
            close.assert_called_once_with(client)
        assert 'Cierre solicitado' in c.manager.message
        assert next(row['state'] for row in c.launchers.entries if row['id']==client)=='closing'
        c.launchers.apply_snapshot(dict(steam='closed',faugus='closed',heroic='closed'),'')
        c.launchers.apply_snapshot(dict(steam='open',faugus='open',heroic='open'),'');pump()
        assert window.findChild(QObject,'managementPanel').property('visible')
    c.launchers.apply_snapshot(dict(steam='open',faugus='open',heroic='open'),'');pump()
    # Normal navigation reaches the manual actions too, without any mouse clicks.
    find('closeLauncher:steam').forceActiveFocus();c.inputAction.emit('down');pump()
    assert window.activeFocusItem().objectName()=='closeLauncher:faugus'
    c.inputAction.emit('down');pump()
    assert window.activeFocusItem().objectName()=='closeLauncher:heroic'
    window.setWidth(800);window.setHeight(600);pump()
    find('closeLauncher:heroic').forceActiveFocus();pump()
    button=find('closeLauncher:heroic')
    point=button.mapToItem(window.contentItem(),0,0)
    assert point.y()>=0 and point.y()+button.height()<window.height()
    window.grabWindow().save('/tmp/estante-sidebar-close.png')
    c.launchers.apply_snapshot(dict(steam='closed',faugus='closed',heroic='closed'),'');pump()
    for key in ('steam','faugus','heroic'):
        assert not any(i.objectName()=='closeLauncher:'+key for i in visual(window.contentItem()))
        assert find('openLauncher:'+key).property('visible')
    for client in ('steam','faugus','heroic'):
        with patch('qt_app.launcher_processes.running_clients',return_value=set()),patch('qt_app.launcher_processes.launch_hidden') as launch:
            find('openLauncher:'+client).forceActiveFocus();c.inputAction.emit('confirm')
            end=time.monotonic()+5
            while c.manager.busy and time.monotonic()<end:pump(.02)
            launch.assert_called_once_with(client)
        assert next(row['state'] for row in c.launchers.entries if row['id']==client)=='opening'
        assert not find('openLauncher:'+client).property('visible')
        # Stale process polls must not offer another launch while starting.
        c.launchers.apply_snapshot(dict(steam='closed',faugus='closed',heroic='closed'),'');pump()
        assert not find('openLauncher:'+client).property('visible')
        c.launchers.apply_snapshot(dict(steam='open',faugus='open',heroic='open'),'');pump()
        assert find('closeLauncher:'+client).property('visible')
        c.launchers.apply_snapshot(dict(steam='closed',faugus='closed',heroic='closed'),'');pump()
    assert c.settings==settings
    assert not errors,'\n'.join(errors)
    c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
print('QT_MANUAL_LAUNCHER_CLOSE_OK: state-dependent open/close buttons, controller navigation, async actions, no duplicate starts, automatic preferences unchanged; no applications closed')
