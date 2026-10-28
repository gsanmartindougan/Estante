"""Native keyboard routing, missing-provider notice and settings, without desktop activation."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,tempfile,time
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,Signal,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtDBus import QDBusPendingCall,QDBusMessage
from qt_app.system_keyboard import SystemKeyboard
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.12):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.004)
class Input(QObject):
    visibleChanged=Signal()
    def __init__(self):super().__init__();self.visible=False;self.shows=0
    def show(self):self.shows+=1
    def hide(self):self.visible=False;self.visibleChanged.emit()
    def isVisible(self):return self.visible
class Controller(QObject):
    settings={}
fake=Input();owner=Controller()
with patch('qt_app.system_keyboard.QGuiApplication') as gui,patch('qt_app.system_keyboard.shutil.which',return_value=None):
    gui.inputMethod.return_value=fake
    keyboard=SystemKeyboard(owner)
    with patch.object(keyboard,'kwin',return_value=None):
        keyboard.show();assert keyboard.active and fake.shows==1
        keyboard.show();assert keyboard._verify.isActive() and fake.shows==1
        keyboard.verify();assert not keyboard.active and keyboard.notice
        assert 'COSMIC' in keyboard.notice and 'Plasma' in keyboard.notice
        keyboard.hide();assert not keyboard.notice
        keyboard.showChoice('cosmic');assert not keyboard.active and 'cosmic-osk' in keyboard.notice
        keyboard.hide();keyboard.showChoice('kde');assert not keyboard.active and 'KDE' in keyboard.notice
        keyboard.hide();keyboard.showChoice('disabled');assert not keyboard.active
        keyboard.hide();keyboard.showChoice('system')
        fake.visible=True;fake.visibleChanged.emit();assert keyboard.active and not keyboard.notice
        fake.visible=False;fake.visibleChanged.emit();assert not keyboard.active
    with patch.object(keyboard,'cosmic',return_value='/test/cosmic-osk'),patch.object(keyboard,'kwin',return_value=None),patch.object(keyboard,'startCosmic') as launch,patch.object(keyboard,'cosmicSupport',return_value=True),patch.dict(os.environ,{'WAYLAND_DISPLAY':'test','XDG_CURRENT_DESKTOP':'COSMIC'}):
        keyboard.show();assert keyboard.active
        launch.assert_called_once_with('/test/cosmic-osk','show')
        keyboard.show();assert launch.call_count==1
        keyboard.hide();launch.assert_called_with('/test/cosmic-osk','hide')
    with patch.object(keyboard,'cosmic',return_value='/test/cosmic-osk'),patch.object(keyboard,'kwin',return_value=None),patch.object(keyboard,'startCosmic') as launch,patch.object(keyboard,'cosmicSupport',return_value=False),patch.dict(os.environ,{'WAYLAND_DISPLAY':'test','XDG_CURRENT_DESKTOP':'mango'}):
        keyboard.showChoice('cosmic')
        assert not keyboard.active and 'ConnectToEIS' in keyboard.notice and 'mango' in keyboard.notice
        launch.assert_not_called()
        keyboard.hide()
        keyboard.show()  # Automatic discovery must not leave Estante swallowing all controller input.
        assert not keyboard.active and 'instalado' in keyboard.notice
        launch.assert_not_called()
        keyboard.refresh();assert 'ConnectToEIS' in keyboard.status
        keyboard.hide()
    with patch('qt_app.system_keyboard.shutil.which',side_effect=lambda name:'/test/plasma-keyboard' if name=='plasma-keyboard' else None),patch.object(keyboard,'kwin',return_value=None),patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':'mango'}):
        keyboard.showChoice('kde')
        assert not keyboard.active and 'instalado' in keyboard.notice and 'KWin' in keyboard.notice
        keyboard.refresh();assert 'KWin' in keyboard.status
        keyboard.hide()
    kwin=Mock();kwin.property.return_value=True
    msg=QDBusMessage.createMethodCall('org.test','/','org.test','show')
    kwin.asyncCall.return_value=QDBusPendingCall.fromCompletedCall(msg.createReply())
    with patch.object(keyboard,'kwin',return_value=kwin):
        keyboard.showChoice('kde');pump();kwin.asyncCall.assert_called_once_with('forceActivate')
        keyboard.verify();assert keyboard.active and not keyboard.notice
        keyboard.hide()
with tempfile.TemporaryDirectory() as folder,patch('qt_app.system_keyboard.shutil.which',return_value=None):
    root=Path(folder);lib=Library(data_dir=root);game={'id':'one','title':'Test','kind':'custom'};lib.put(game)
    controller=LibraryController([game],{'language':'es','keyboard_fallback':False},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows: errors.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window;pump()
    def visual(item):
        yield item
        for child in item.childItems():yield from visual(child)
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    # The native request is made against the real field; no extra text buffer or internal keyboard.
    with patch.object(controller.nativeKeyboard,'kwin',return_value=None),patch.object(controller.nativeKeyboard,'cosmic',return_value=None):
        controller.inputAction.emit('search');pump()
        assert controller.nativeKeyboard.active
        controller.nativeKeyboard.verify();pump();assert controller.nativeKeyboard.notice
        assert not window.findChildren(QObject,'buffer')
        controller.inputAction.emit('confirm');pump(.3)
        panel=window.findChild(QObject,'managementPanel');assert panel.property('visible')
        assert find('settingsGroup:Teclado').property('expanded')
        # Unsaved preview chooses the selected provider, without installing or launching a process.
        panel.setProperty('settingsDraft',{'["onscreen_keyboard"]':'disabled'})
        find('testSystemKeyboard').forceActiveFocus();controller.inputAction.emit('confirm');pump()
        assert 'desactivado' in controller.nativeKeyboard.notice
        controller.inputAction.emit('back');pump()
        # The setting saves through the shared controller shortcut.
        controller.inputAction.emit('save');pump()
        assert controller.settings['onscreen_keyboard']=='disabled'
        assert __import__('json').loads((root/'settings.json').read_text())['onscreen_keyboard']=='disabled'
    controller.nativeKeyboard.hide();controller.manager.shutdown();controller.idle_timer.stop();window.close();pump();del engine
    assert not errors,'\n'.join(errors)
print('QT_SYSTEM_KEYBOARD_OK: system/COSMIC/KDE requests, failure notices, real field focus, keyboard settings/test/save; no external UI or installs')
