"""Playing unloads the library in every mode and restores selection on completion."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile,json,gc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from shiboken6 import isValid
from qt_app.main import LibraryController
from qt_app.images import ArtworkProvider
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
def pump(seconds=.3):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);time.sleep(.004)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
def rss():
    return int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:')))/1024
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);games=[]
    for i in range(100):
        path=root/f'{i%12}.png'
        if not path.exists():
            image=QImage(1600,900,QImage.Format_RGB32);image.fill(0xff203040+i*400);image.save(str(path))
        games.append(dict(id=str(i),title=f'Game {i:03}',kind='custom',cover=str(path),square_cover=str(path),banner=str(path)))
    from library import Library
    library=Library(data_dir=root)
    for game in games: library.put(game)
    c=LibraryController(games,{'playing_behavior':'none'},root,allow_launch=False)
    c.use_image_provider=True
    engine=QQmlApplicationEngine();errors=[]
    engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.addImageProvider('artwork',ArtworkProvider(root/'cache'))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump(1)
    loader=window.findChild(QObject,'librarySceneLoader')
    readings=[]
    for mode in ('grid','list','carousel','ps5'):
        c.changeView(mode);c.catalog.selected_id='7';c.selectionChanged.emit();pump(.7)
        scene=loader.property('item');assert scene
        before=rss();count=len(list(visual(scene)))
        c._busy=c._loading=True;c._launch_game=dict(games[7]);c.sessionChanged.emit();pump()
        assert loader.property('item') is not None, 'Library needed for launch animation'
        c.handle_session(('started',None));pump(.9)
        assert loader.property('item') is None and not isValid(scene), 'Library retained while playing'
        items=list(visual(window.contentItem()))
        playing=next(i for i in items if i.objectName()=='playingScreen')
        cover=next(i for i in items if i.objectName()=='playingCover')
        assert cover.property('source').toString()
        assert not any(i.objectName() in ('libraryStrip','libraryToolbar') for i in items)
        after=rss();readings.append(dict(mode=mode,rss_library_MiB=round(before,1),rss_playing_MiB=round(after,1),library_items=count,playing_items=len(list(visual(playing)))))
        if mode=='grid':window.grabWindow().save('/tmp/estante-playing.png')
        c.handle_session(('finished',0));pump(.7)
        assert loader.property('item') is not None
        assert c.catalog.selected_id=='7' and c.view_mode==mode
        assert not any(i.objectName()=='playingScreen' for i in visual(window.contentItem()))
    assert not errors,'\n'.join(errors)
    print(json.dumps(readings,indent=2))
    c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
print('QT_PLAYING_MEMORY_OK: library destroyed in all modes, single cover screen, selection restored; offscreen measurements')
