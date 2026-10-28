"""Compact screensaver settings and visual background selection with controller input."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);lib=Library(data_dir=root);game={'id':'one','title':'Test','kind':'custom'};lib.put(game)
    c=LibraryController([game],{'language':'es','screensaver_background':'bundled:1.png'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;window.resize(1440,900);pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def press(item):item.forceActiveFocus();c.inputAction.emit('confirm');pump()
    c.inputAction.emit('menu');pump()
    assert not [item for item in visual(window.contentItem()) if item.objectName()=='settingsBackgroundThumbnail']
    press(find('groupHeader:Salvapantallas'))
    timing=find('settingsGroup:Salvapantallas');assert timing.height()<550,timing.height()
    idle=find('settingRow:["screensaver_idle_value"]')
    slider=next(item for item in visual(idle) if item.property('gamepadKind')=='slider')
    slider.forceActiveFocus();old_value=slider.property('value')
    c.inputAction.emit('confirm');c.inputAction.emit('right');pump()
    assert slider.property('value')==old_value+1
    c.inputAction.emit('back');pump()
    assert timing.property('expanded') and not slider.property('gamepadAdjusting')
    old_value=slider.property('value')
    c.inputAction.emit('right');pump()
    assert slider.property('value')==old_value
    assert window.activeFocusItem().objectName().startswith('radio:["screensaver_idle_unit"]'),window.activeFocusItem().objectName()
    assert not any(item.objectName()=='groupHeader:Fondos del salvapantallas' for item in visual(window.contentItem()))
    press(find('radio:["screensaver_source"]:1'))
    press(find('backgroundChooser:["screensaver_background"]'))
    press(find('backgroundOption:["screensaver_background"]:0'))
    c.inputAction.emit('right');pump()
    assert window.activeFocusItem().objectName()=='backgroundOption:["screensaver_background"]:1'
    c.inputAction.emit('confirm');pump()
    panel=window.findChild(QObject,'managementPanel')
    assert panel.property('settingsDraft').toVariant()['["screensaver_background"]']=='bundled:2.png'
    window.grabWindow().save('/tmp/estante-screensaver-visual-options.png')
    # Closing the expanded card must unload its thumbnail widgets without losing the draft.
    press(find('groupHeader:Salvapantallas'))
    assert not [item for item in visual(window.contentItem()) if item.objectName()=='settingsBackgroundThumbnail']
    c.inputAction.emit('save');pump()
    stored=json.loads((root/'settings.json').read_text())
    assert stored['screensaver_background']=='bundled:2.png' and stored['screensaver_source']=='application'
    c.restoreCursor();c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_SCREENSAVER_SETTINGS_OK: compact timing/units, six visual options, controller selection/save and lazy thumbnail release')
