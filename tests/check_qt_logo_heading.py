"""Compact and wide heading logos use available space without moving the panel."""
import sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QObject,QUrl
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from qt_app.images import ArtworkProvider
app=QApplication([])
def pump():
    end=time.monotonic()+.5
    while time.monotonic()<end:app.processEvents();time.sleep(.005)
errors=[]
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    games=[]
    for i,(width,height) in enumerate([(826,482),(1909,227)]):
        image=QImage(width,height,QImage.Format_RGBA8888);image.fill(QColor('coral'))
        path=root/f'logo-{i}.png';assert image.save(str(path))
        games.append(dict(id=str(i),kind='custom',title=f'Game {i}',logo=str(path)))
    c=LibraryController(games,{'layout':'carousel'},root,allow_edit=False,allow_launch=False)
    c.use_image_provider=True
    engine=QQmlApplicationEngine();engine.addImageProvider('artwork',ArtworkProvider(root/'cache'))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.warnings.connect(lambda ws:errors.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];window.resize(1920,1337);pump()
    logo=window.findChild(QObject,'selectedGameLogo')
    details=window.findChild(QObject,'detailLayout')
    panel_y=details.y()
    compact_width=logo.property('paintedWidth')
    assert compact_width>=200,compact_width
    c.select(1);pump()
    assert logo.property('paintedWidth')>=350
    assert details.y()==panel_y
    c.select(0);pump()
    assert abs(logo.property('paintedWidth')-compact_width)<1
    assert details.y()==panel_y
    assert not errors,errors
    c.manager.shutdown();c.idle_timer.stop();window.close();del engine
print('QT_LOGO_HEADING_OK: compact logo >=200px, wide logo >=350px, stable panel and repeated selection')
