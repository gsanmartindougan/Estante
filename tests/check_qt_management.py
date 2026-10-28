"""Qt adapter tests with all network providers mocked; temporary data only."""
import sys,time,tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage
from qt_app.main import LibraryController
from library import Library

app=QCoreApplication([])
def wait(manager):
    deadline=time.monotonic()+5
    while manager.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert not manager.busy,'worker timed out'
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);library=Library(data_dir=root)
    game=dict(id='one',kind='custom',title='Game',categories=['Fav']);library.put(game)
    image=QImage(16,16,QImage.Format.Format_RGB32);image.fill(0xff667788);image.save(str(root/'art.png'))
    controller=LibraryController([game],{'steamgriddb_key':'test-not-a-real-key'},root,allow_launch=False)
    manager=controller.manager
    with patch('qt_app.management.SteamGridDB.search',return_value=[dict(id=42,name='Match')]):
        manager.searchArtwork('steamgriddb','Game','cover');wait(manager)
    assert manager.results[0]['kind']=='match'
    with patch('qt_app.management.SteamGridDB.grids',return_value=[dict(url='https://cdn.steamgriddb.com/test.png')]):
        manager.chooseResult(0);wait(manager)
    with patch('qt_app.management.SteamGridDB.download',return_value=str(root/'art.png')):
        manager.chooseResult(0);wait(manager)
    assert Library(data_dir=root).games()[0]['cover']==str(root/'art.png')
    with patch('qt_app.management.SteamGridDB.search',side_effect=RuntimeError('offline')):
        manager.searchArtwork('steamgriddb','Other','banner');wait(manager)
    assert manager.results==[] and manager.message=='offline'
    with patch('updates.latest_release',return_value=None):manager.checkUpdates();wait(manager)
    assert manager.message=='Ya tienes la última versión.'
    from qt_app.icons import BootstrapIcons
    row=dict(name='controller',url=BootstrapIcons.ICON_ROOT+'controller.svg',source='https://icons.getbootstrap.com/icons/controller/',author='Bootstrap',license='MIT')
    with patch.object(BootstrapIcons,'search',return_value=[row]):manager.searchIcons('bootstrap','controller');wait(manager)
    svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="currentColor"/></svg>'
    with patch.object(BootstrapIcons,'request',return_value=BytesIO(svg)):manager.chooseIcon(0,'Fav');wait(manager)
    state=Library(data_dir=root).state
    assert state['category_icons']['Fav']
    assert state['category_icon_sources']['Fav']['license']=='MIT'
    assert 'gi.repository.Gtk' not in sys.modules
    manager.shutdown();controller.idle_timer.stop()
print('QT_MANAGEMENT_INTEGRATION_OK: async gallery, no stale results, offline errors, updates, Qt SVG icons/credits')
