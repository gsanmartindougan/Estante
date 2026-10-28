"""Exercise dominant-color URLs through the real Qt image-provider and QML pipeline."""
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from qt_app.images import ArtworkProvider
app=QApplication([])
app.setDesktopFileName("io.github.estante.Test")
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    image=QImage(800,200,QImage.Format_RGB32);image.fill(QColor(30,60,180));image.save(str(root/'source.png'))
    for name in ('Background.qml','BackdropRegion.qml'):(root/name).write_text((Path(__file__).resolve().parents[1]/'qt_app'/name).read_text())
    encoded=quote(str(root/'source.png'),safe='')
    scene=root/'Scene.qml';scene.write_text('import QtQuick\nWindow { visible:true; width:960; height:640; Background { anchors.fill:parent; primary:"image://artwork/'+encoded+'"; fillPrimary:"image://artwork/@dominant/'+encoded+'"; fillMode:"dominant"; position:"lower"; dim:0 } }')
    engine=QQmlApplicationEngine();engine.addImageProvider('artwork',ArtworkProvider(root/'cache'));engine.load(QUrl.fromLocalFile(str(scene)))
    assert engine.rootObjects()
    window=engine.rootObjects()[0]
    until=time.monotonic()+1
    while time.monotonic()<until:app.processEvents();time.sleep(.005)
    actual=window.grabWindow();actual.save('/tmp/estante-dominant-fill.png')
    color=actual.pixelColor(10,10)
    assert abs(color.red()-30)<5 and abs(color.green()-60)<5 and abs(color.blue()-180)<5,color.name()
    window.close();app.processEvents();del engine
print('QT_DOMINANT_QML_OK')
