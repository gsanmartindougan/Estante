"""Bounded image requests in actual QML, without compositor windows or GPU claims."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile,json
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QSize
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
def pump(seconds=.25):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.005)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
class Images(QQuickImageProvider):
    def __init__(self):super().__init__(QQuickImageProvider.Image,QQuickImageProvider.ForceAsynchronousImageLoading);self.calls=[]
    def requestImage(self,name,size,requested):
        self.calls.append((name,requested.width(),requested.height()))
        image=QImage(max(1,min(500,requested.width())),max(1,min(500,requested.height())),QImage.Format_RGB32)
        image.fill(0xff447799);size.setWidth(image.width());size.setHeight(image.height());return image
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);lib=Library(data_dir=root);games=[]
    image=QImage(640,360,QImage.Format_RGB32);image.fill(0xff447799)
    for i in range(8):
        image.save(str(root/f'cover{i}.png'));image.save(str(root/f'hero{i}.png'))
        games.append(dict(id=str(i),title=f'Game {i}',kind='custom',cover=str(root/f'cover{i}.png'),banner=str(root/f'hero{i}.png'),banner_secondary=str(root/f'hero{i}.png')))
    lib.put_many(games)
    c=LibraryController(games,{'layout':'ps5','hero_positions':{'ps5':'full'},'background_fill':'dominant'},root,allow_launch=False)
    c.use_image_provider=True
    images=Images();engine=QQmlApplicationEngine();engine.addImageProvider('artwork',images)
    errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump(.6)
    images.calls.clear();c.move(1);pump(.6)
    cover_calls=[row for row in images.calls if 'cover' in row[0]]
    print('SENSE_ANIMATION_REQUESTS',json.dumps(cover_calls),flush=True)
    editor=window.findChild(QObject,'gameEditor')
    overview_images=[item for item in visual(editor.property('contentItem')) if item.metaObject().indexOfProperty('sourceSize')>=0]
    print('CLOSED_EDITOR_NONEMPTY_SOURCES',sum(bool(item.property('source').toString()) for item in overview_images),flush=True)
    if not os.environ.get('ESTANTE_REFERENCE_PROBE'):
        assert all(not item.property('source').toString() for item in overview_images)
        sizes={}
        for name,w,h in cover_calls:sizes.setdefault(name,set()).add((w,h))
        assert all(len(values)<=1 for values in sizes.values()),sizes
        assert len(cover_calls)<=2,cover_calls
        # Full backdrop must release the invisible fill layer.
        fill_images=[item for item in visual(window.contentItem()) if item.objectName()=='backgroundFill']
        assert all(not item.property('source').toString() for item in fill_images)
        c.edit();pump();assert any(item.property('source').toString() for item in overview_images)
        editor.setProperty('page','manual');pump();assert all(not item.property('source').toString() for item in overview_images)
        c.cancelEdit();pump();assert all(not item.property('source').toString() for item in overview_images)
    c.restoreCursor();c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_OPTIMIZATION_UI_OK',flush=True)
