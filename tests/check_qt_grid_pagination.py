"""100-game grid pagination, controller boundaries, setting save, filters and bounded tiles."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
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
    root=Path(folder);library=Library(data_dir=root);games=[]
    for i in range(100):
        path=root/f'{i}.png';image=QImage(60,90,QImage.Format_RGB32);image.fill(0xff223344+i);image.save(str(path))
        games.append(dict(id=str(i),title=f'Game {i:03}',kind='custom',cover=str(path)))
    library.put_many(games)
    c=LibraryController(games,{'layout':'grid','language':'es'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump()
    def find(name):return next(i for i in visual(window.contentItem()) if i.objectName()==name)
    strip=find('libraryStrip')
    def check(page,size,amount):
        pump()
        assert strip.property('pageIndex')==page
        assert find('pagedGrid').property('count')==amount
        tiles=[i for i in visual(window.contentItem()) if i.objectName()=='gridPageTile']
        assert len(tiles)==amount and len(tiles)<=size
        for tile in tiles:
            data=tile.property('modelData');data=data.toVariant() if hasattr(data,'toVariant') else data
            assert page*size<=int(data['id'])<min((page+1)*size,100), data
    check(0,10,10);assert strip.property('pageCount')==10
    strip.forceActiveFocus();c.inputAction.emit('page_next');check(1,10,10);assert c.selected==10
    c.inputAction.emit('page_previous');check(0,10,10);assert c.selected==0
    from controls import StickChord
    chord=StickChord()
    def sticks(pressed):
        for action in chord.update(pressed): c.inputAction.emit(action)
        pump()
    sticks({'right_stick'});assert c.selected==0
    sticks(set());check(1,10,10);assert c.selected==10
    sticks({'left_stick'});sticks(set());check(0,10,10);assert c.selected==0
    # The chord opens appearance settings without accidentally turning a page.
    sticks({'left_stick'});sticks({'left_stick','right_stick'})
    assert window.findChild(QObject,'managementPanel').property('visible')
    assert c.selected==0
    sticks({'right_stick'});sticks(set());assert c.selected==0
    c.inputAction.emit('back');pump();strip.forceActiveFocus()
    c.select(9);pump();strip.forceActiveFocus();c.inputAction.emit('right');check(1,10,10);assert c.selected==10
    c.select(99);check(9,10,10);strip.forceActiveFocus();c.inputAction.emit('right');check(0,10,10)
    # Mouse action uses an absolute index on later pages.
    c.select(30);check(3,10,10)
    tile=next(i for i in visual(window.contentItem()) if i.objectName()=='gridPageTile' and i.property('index')==1)
    QMetaObject.invokeMethod(tile,'chosen');pump();assert c.selected==31
    # The appearance setting is saved and the last partial page is bounded.
    c.manager.saveSettingValues([{'path':['grid_page_size'],'value':7}])
    end=time.monotonic()+5
    while c.manager.busy and time.monotonic()<end:pump(.02)
    pump();assert json.loads((root/'settings.json').read_text())['grid_page_size']==7
    c.select(99);check(14,7,2);assert strip.property('pageCount')==15
    assert 'página' in c.controllerHints
    c.search('zz-no-match');pump()
    assert strip.property('pageCount')==0 and find('gridPageIndicator').property('text')=='Página 0 / 0'
    assert not find('nextGridPage').property('enabled')
    c.search('Game 099');pump();assert find('pagedGrid').property('count')==1
    assert strip.property('pageCount')==1
    c.search('');c.select(0);pump();window.grabWindow().save('/tmp/estante-grid-pages.png')
    c.inputAction.emit('appearance_settings');pump()
    assert find('groupHeader:Paginación').property('visible')
    assert not errors,'\n'.join(errors)
    c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
print('QT_GRID_PAGINATION_OK: default 10, saved 7, 100 games, shoulder/D-pad/mouse navigation, partial/empty/filtered pages, no off-page tiles')
