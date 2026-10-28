"""Compare Qt hero composition against the original GTK widget's rendered pixels."""
import sys
import subprocess
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine
app=QApplication([])
app.setDesktopFileName("io.github.estante.Test")
repo=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='estante-parity-') as folder:
    root=Path(folder)
    for component in ('Background.qml','BackdropRegion.qml'):
        (root/component).write_text((repo/'qt_app'/component).read_text())
    for name,offset in [('first',0),('second',90)]:
        image=QImage(400,160,QImage.Format_RGB32)
        for y in range(image.height()):
            for x in range(image.width()):image.setPixelColor(x,y,QColor((x+offset)%256,(y+offset)%256,70+offset))
        image.save(str(root/(name+'.png')))
    cases=[('single',position) for position in ('full','top','lower')]+[(split,position) for split in ('horizontal','vertical','diagonal') for position in ('full','top','lower')]
    for split,position in cases:
        component='BackdropRegion' if split=='single' else 'Background'
        props=('source:'+repr(QUrl.fromLocalFile(str(root/'first.png')).toString())) if split=='single' else ('primary:'+repr(QUrl.fromLocalFile(str(root/'first.png')).toString())+'; secondary:'+repr(QUrl.fromLocalFile(str(root/'second.png')).toString())+'; split:'+repr(split)+'; dim:0')
        qml=root/'Scene.qml';qml.write_text('import QtQuick\nWindow { visible:true; width:960; height:540; color:"transparent"; '+component+' { anchors.fill:parent; position:'+repr(position)+'; '+props+' } }')
        errors=[];engine=QQmlApplicationEngine();engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows));engine.load(QUrl.fromLocalFile(str(qml)))
        assert engine.rootObjects(),errors
        window=engine.rootObjects()[0]
        until=time.monotonic()+.3
        while time.monotonic()<until:app.processEvents();time.sleep(.005)
        actual=window.grabWindow().convertToFormat(QImage.Format_RGBA8888)
        target=root/'gtk.png'
        result=subprocess.run(['/usr/bin/python3',str(repo/'tests/render_gtk_background.py'),str(root/'first.png'),'-' if split=='single' else str(root/'second.png'),str(actual.width()),str(actual.height()),position,split,str(target)],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        expected=QImage(str(target)).convertToFormat(QImage.Format_RGBA8888)
        # Compare premultiplied channels: RGB in fully transparent pixels is irrelevant.
        error=0;count=0
        for y in range(0,actual.height(),8):
            for x in range(0,actual.width(),8):
                a=actual.pixelColor(x,y);b=expected.pixelColor(x,y)
                error+=sum(abs(ca*a.alpha()/255-cb*b.alpha()/255) for ca,cb in zip(a.getRgb()[:3],b.getRgb()[:3]))+abs(a.alpha()-b.alpha())
                count+=4
        mean=error/count
        actual.save('/tmp/estante-qt-parity-'+split+'-'+position+'.png')
        expected.save('/tmp/estante-gtk-parity-'+split+'-'+position+'.png')
        print(split,position,'mean channel error',round(mean,2),flush=True)
        assert mean<5,(split,position,mean)
        assert not errors,errors
        window.close();app.processEvents();del engine
print('QT_GTK_BACKGROUND_PARITY_OK')
