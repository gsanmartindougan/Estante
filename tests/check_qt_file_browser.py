"""Single GTK-style editor drawer, tested without compositor windows or network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QMetaObject,Q_ARG
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from core.library import Library
from core.i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);library=Library(data_dir=root)
    picture=QImage(120,180,QImage.Format_RGB32);picture.fill(0xff627c99);picture.save(str(root/'cover.png'))
    source=str(root/'cover.png')
    hero=QImage(3840,2160,QImage.Format_RGB32);hero.fill(0xff446688);hero.save(str(root/'hero.png'))
    secondary=QImage(1920,1080,QImage.Format_RGB32);secondary.fill(0xff885544);secondary.save(str(root/'secondary.png'))
    script=root/'example.sh';script.write_text('#!/bin/sh\nexit 0\n');script.chmod(0o755)
    game=dict(id='one',title='Example',kind='local',path=str(script),cover=source,banner=str(root/'hero.png'),banner_secondary=str(root/'secondary.png'),categories=['Fav'])
    library.put(game)
    controller=LibraryController([game],{'language':'es'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[]
    engine.warnings.connect(lambda rows:errors.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window;window.resize(1600,1000);pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def same_panel(page):
        assert editor.property('visible') and editor.property('page')==page
        assert not window.findChild(QObject,'managementPanel').property('visible')
        assert len(app.topLevelWindows())==1
    def done():
        deadline=time.monotonic()+5
        while controller.manager.busy and time.monotonic()<deadline:pump(.02)
        pump();assert not controller.manager.busy
    images=root/'pictures';images.mkdir()
    (images/'subfolder').mkdir()
    for i in range(70):picture.save(str(images/f'image-{i:02}.png'))
    (images/'invalid.png').write_text('invalid image')
    (images/'ignored.txt').write_text('not a picture')
    controller.inputAction.emit('save');pump();editor=window.findChild(QObject,'gameEditor')
    find('editVerticalCover').forceActiveFocus();controller.inputAction.emit('confirm');pump()
    find('editorLocalImages').forceActiveFocus();controller.inputAction.emit('confirm');pump()
    find('editorBrowseFiles').forceActiveFocus();controller.inputAction.emit('confirm');pump()
    browser=find('localImageBrowser');grid=find('localImageGrid')
    folders=browser.findChild(QObject,'localImageFolders')
    def open_folder(path):
        QMetaObject.invokeMethod(browser,'openFolder',Q_ARG('QVariant',QUrl.fromLocalFile(str(path))))
        pump(.3)
    open_folder(images)
    assert grid.property('count')==72,grid.property('count')
    assert folders.property('showDotAndDotDot') is False
    assert grid.property('currentIndex')==0
    assert find('localImageUse').property('enabled') is False
    controller.inputAction.emit('confirm');pump()
    assert browser.property('folderUrl')==QUrl.fromLocalFile(str(images/'subfolder')).toString()
    assert grid.property('count')==0
    controller.inputAction.emit('back');pump(.3)
    assert browser.property('folderUrl')==QUrl.fromLocalFile(str(images)).toString()
    grid.forceActiveFocus();controller.inputAction.emit('right');pump(.3)
    assert grid.property('currentIndex')==1
    assert browser.property('selectedUrl').endswith('image-00.png')
    assert find('localImageUse').property('enabled')
    before=Library(data_dir=root).games()[0]['cover']
    assert before==source  # Moving and selecting must not import.
    assert controller.manager.localImageInfo(browser.property('selectedUrl'))['width']==120
    # Offscreen thumbnails must not retain their sources.
    loaded=[i for i in visual(grid) if i.metaObject().indexOfProperty('source')>=0 and i.property('source').toString()]
    assert len(loaded)<25,len(loaded)
    for width,height in [(1280,800),(1920,1080)]:
        window.resize(width,height);pump(.2)
        assert grid.width()>100 and grid.height()>100
        assert find('localImageUse').x()+find('localImageUse').width()<=browser.width()+1
        window.grabWindow().save(f'/tmp/estante-file-browser-{width}.png')
    grid.forceActiveFocus()
    for _ in range(10):controller.inputAction.emit('down');pump(.02)
    assert grid.property('contentY')>0
    loaded=[i for i in visual(grid) if i.metaObject().indexOfProperty('source')>=0 and i.property('source').toString()]
    assert len(loaded)<25,len(loaded)
    grid.setProperty('currentIndex',71);pump(.2)
    assert not find('localImageUse').property('enabled')
    assert not controller.manager.localImageInfo(QUrl.fromLocalFile(str(images/'missing.png')).toString())['valid']
    grid.setProperty('currentIndex',1);grid.forceActiveFocus();pump()
    controller.inputAction.emit('confirm');pump()
    assert find('localImageUse').hasActiveFocus()
    controller.inputAction.emit('save');done()
    same_panel('overview')
    assert Library(data_dir=root).games()[0]['cover']!=source
    try:find('localImageBrowser');raise AssertionError('Browser retained after exit')
    except StopIteration:pass
    assert not errors,errors
    controller.manager.shutdown();controller.idle_timer.stop();window.close()
    import shiboken6
    shiboken6.delete(engine);pump()
print('QT_FILE_BROWSER_OK: bounded thumbnails, preview, folders/back, no implicit import, save and unload')
