"""Services live in Scan; global settings retain one screensaver entry and all saved data."""
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
def pump(seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);lib=Library(data_dir=root);game={'id':'one','title':'Test','kind':'custom'};lib.put(game)
    settings={'language':'es','steamgriddb_key':'old-test-key','unrelated':'preserved','screensaver_background':'bundled:3.png'}
    (root/'settings.json').write_text(json.dumps(settings))
    c=LibraryController([game],settings,root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def click(item):item.forceActiveFocus();c.inputAction.emit('confirm');pump()
    c.inputAction.emit('menu');pump()
    names=[item.objectName() for item in visual(window.contentItem())]
    assert names.count('groupHeader:Salvapantallas')==1
    assert 'groupHeader:Fondos del salvapantallas' not in names
    assert not any('SteamGridDB' in name or 'IGDB' in name for name in names)
    panel=window.findChild(QObject,'managementPanel');panel.setProperty('section',2);pump()
    assert find('saveScanServices').property('visible')
    for service,path,value in [('SteamGridDB','steamgriddb_key','new-test-key'),('IGDB · fondos 16:9','igdb_client_id','new-test-id')]:
        click(find('categoryHeader:scan:'+service))
        row=find('settingRow:'+json.dumps([path],separators=(',',':')))
        field=next(item for item in visual(row) if item.property('gamepadKind')=='text')
        field.setProperty('text',value)
    c.inputAction.emit('back');pump()
    assert panel.property('visible') and not find('scanService:IGDB · fondos 16:9').property('expanded')
    c.inputAction.emit('save');pump()
    saved=json.loads((root/'settings.json').read_text())
    assert saved['steamgriddb_key']=='new-test-key' and saved['igdb_client_id']=='new-test-id'
    assert saved['unrelated']=='preserved' and saved['screensaver_background']=='bundled:3.png'
    window.grabWindow().save('/tmp/estante-scan-services.png')
    panel.setProperty('section',4);pump();window.grabWindow().save('/tmp/estante-global-settings-reorganized.png')
    c.restoreCursor();c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_SCAN_SERVICES_OK: one screensaver group; SteamGridDB/IGDB in Scan, credentials saved by controller, other settings preserved; no API calls')
