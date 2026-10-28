"""GTK category cards, member edits, order and primary category on temporary data."""
import sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl,QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.12):
    until=time.monotonic()+seconds
    while time.monotonic()<until:app.processEvents();time.sleep(.005)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);library=Library(data_dir=root)
    library.put_many([dict(id=str(i),title=f'Game {i:03d}',kind='custom',categories=['Souls'] if i==1 else [],metadata={'preserved':'yes'}) for i in range(100)])
    controller=LibraryController(library.games(),{'language':'es'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows));engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window;pump(.3)
    controller.inputAction.emit('menu');pump();panel=window.findChild(QObject,'managementPanel');panel.setProperty('section',3);pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def click(item):item.forceActiveFocus();controller.inputAction.emit('confirm');pump()
    def done():
        until=time.monotonic()+5
        while controller.manager.busy and time.monotonic()<until:pump(.02)
        pump();assert not controller.manager.busy
    click(find('categoryHeader:new'));find('newCategoryName').setProperty('text','PS4');click(find('createCategory'));done()
    assert 'PS4' in controller.manager.categoryNames
    click(find('categoryHeader:primary'))
    primary=find('primaryCategory:PS4')
    click(primary);done();assert Library(data_dir=root).state['primary_category']=='PS4'
    click(find('categoryHeader:categories'));click(find('categoryHeader:PS4'))
    games=find('categoryGames:PS4');games.forceActiveFocus();controller.inputAction.emit('confirm');done()
    persisted=Library(data_dir=root).games()
    assert 'PS4' in next(game for game in persisted if game['id']=='0')['categories']
    assert next(game for game in persisted if game['id']=='1')['categories']==['Souls']
    assert all(game['metadata']=={'preserved':'yes'} for game in persisted)
    # Navigate past the initially visible delegates without constructing 100 checkboxes.
    games=find('categoryGames:PS4');games.forceActiveFocus()
    for _ in range(30):controller.inputAction.emit('down');pump(.01)
    assert games.property('currentIndex')==30
    controller.inputAction.emit('confirm');done()
    assert 'PS4' in next(game for game in Library(data_dir=root).games() if game['id']=='30')['categories']
    assert find('categoryGames:PS4').property('currentIndex')==30
    controller.manager.category('up','PS4','');done();assert controller.manager.categoryNames[0]=='PS4'
    window.grabWindow().save('/tmp/estante-categories-gtk.png')
    controller.manager.category('rename','PlayStation','PS4');done()
    assert 'PlayStation' in next(game for game in Library(data_dir=root).games() if game['id']=='30')['categories']
    assert Library(data_dir=root).state['primary_category']=='PlayStation'
    controller.manager.shutdown();controller.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_CATEGORIES_OK: cards, primary, 100 games/controller scroll, membership, order, rename, preservation')
