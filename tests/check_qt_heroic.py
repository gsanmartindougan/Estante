"""Heroic import button/controller, artwork, editor, and game session; no real launch/network."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
def pump(seconds=.15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
def wait(manager):
    end=time.monotonic()+5
    while manager.busy and time.monotonic()<end:pump(.02)
    assert not manager.busy,'worker timed out'
    pump()
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);config=root/'config';heroic=config/'heroic';game_dir=root/'Games/Test';game_dir.mkdir(parents=True)
    installed=heroic/'legendaryConfig/legendary/installed.json';installed.parent.mkdir(parents=True)
    installed.write_text(json.dumps({'test':{'app_name':'test','title':'Heroic Test','install_path':str(game_dir),'executable':'game.exe'}}))
    metadata=installed.parent/'metadata/test.json';metadata.parent.mkdir()
    metadata.write_text(json.dumps({'metadata':{'keyImages':[{'type':'DieselGameBoxTall','url':'https://example.test/cover.png'}]}}))
    original=installed.read_bytes(),metadata.read_bytes()
    image=QImage(160,240,QImage.Format_RGB32);image.fill(0xff335577);image.save(str(root/'art.png'))
    with patch.dict(os.environ,XDG_CONFIG_HOME=str(config)):
        library=Library(data_dir=root/'estante');c=LibraryController([],{},library.root)
        engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
        engine.rootContext().setContextProperty('libraryController',c)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
        assert engine.rootObjects(),errors
        window=engine.rootObjects()[0];c.window=window;pump()
        c.inputAction.emit('menu');pump();panel=window.findChild(QObject,'managementPanel');panel.setProperty('section',2);pump()
        button=next(i for i in visual(window.contentItem()) if i.objectName()=='scanHeroicButton')
        with patch('qt_app.management.SteamGridDB.download',return_value=str(root/'art.png')) as download:
            button.forceActiveFocus();c.inputAction.emit('confirm');wait(c.manager)
            download.assert_called_once_with('https://example.test/cover.png',custom=True)
        assert len(c.catalog.games)==1 and 'Heroic' in c.category_names
        game=c.catalog.games[0];assert game['kind']=='heroic' and game['cover']==str(root/'art.png')
        with patch('qt_app.management.SteamGridDB.download') as download:
            c.manager.scan('heroic');wait(c.manager);download.assert_not_called()
        panel.close();pump();c.edit();pump()
        editor=window.findChild(QObject,'gameEditor');assert editor.property('visible')
        c.cancelEdit();pump()
        def wait_game(game,process,on_started,is_ready):
            assert game['heroic_runner']=='legendary'
            on_started();return 0
        with patch('qt_app.session.launch',return_value=Mock()),patch('qt_app.session.wait_for_game',side_effect=wait_game):
            c.play()
            deadline=time.monotonic()+5
            while c.busy and time.monotonic()<deadline:pump(.02)
            pump()
        assert not c.busy and Library(data_dir=library.root).game_stats(game)['sessions']==1
        assert (installed.read_bytes(),metadata.read_bytes())==original
        assert not errors,'\n'.join(errors)
        c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
print('QT_HEROIC_OK: controller import, automatic artwork without key, idempotent scan, category/editor, recorded game session; no real launch/network')
