"""Render and check the transition in every split direction."""
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl, QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
app=QApplication([])
app.setDesktopFileName("io.github.estante.Test")
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    for name,color in [('red','red'),('blue','blue')]:
        image=QImage(800,400,QImage.Format_RGB32);image.fill(QColor(color));image.save(str(root/(name+'.png')))
    (root/'BackdropRegion.qml').write_text((Path(__file__).resolve().parents[1]/'qt_app/BackdropRegion.qml').read_text())
    (root/'Background.qml').write_text((Path(__file__).resolve().parents[1]/'qt_app/Background.qml').read_text())
    qml=root/'Test.qml'
    qml.write_text('import QtQuick\nWindow { visible:true; width:800; height:400; Background { objectName:"backdrop"; anchors.fill:parent; primary:"'+QUrl.fromLocalFile(str(root/'red.png')).toString()+'"; secondary:"'+QUrl.fromLocalFile(str(root/'blue.png')).toString()+'"; split:"horizontal"; dim:0 } }')
    errors=[];engine=QQmlApplicationEngine();engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows));engine.load(QUrl.fromLocalFile(str(qml)))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];backdrop=window.findChild(QObject,'backdrop')
    for direction in ['horizontal','vertical','diagonal']:
        backdrop.setProperty('split',direction)
        until=time.monotonic()+.5
        while time.monotonic()<until:app.processEvents();time.sleep(.005)
        def visual_children(item):
            yield item
            for child in item.childItems(): yield from visual_children(child)
        region=next(item for item in visual_children(backdrop) if item.objectName()=='primaryHeroRegion')
        band=min(128,min(window.width(),window.height())*.12)
        assert abs(region.width()-(window.width()/2+band/2 if direction=='vertical' else window.width()))<1
        assert abs(region.height()-(window.height()/2+band/2 if direction=='horizontal' else window.height()))<1
        image=window.grabWindow();assert not image.isNull()
        assert image.pixelColor(0,0).alpha()==255
        assert image.pixelColor(image.width()-1,image.height()-1).alpha()==255
        middle=image.pixelColor(image.width()//2,image.height()//2)
        image.save('/tmp/estante-soft-split-'+direction+'.png')
        assert middle.red()>35 and middle.blue()>35,(direction,middle.name())
        image.save('/tmp/estante-soft-split-'+direction+'.png')
    assert not errors,errors
    window.close();app.processEvents();del engine
print('QT_BACKGROUND_OK: three feathered split directions')
