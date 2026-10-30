"""Selection must not rebuild artwork URLs for an editor that is closed."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Property,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from core.library import Library

class CountingController(LibraryController):
    reads=0
    @Property('QVariantMap',notify=LibraryController.selectionChanged)
    def editorImages(self):
        self.reads+=1
        return LibraryController.editorImages.fget(self)

app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
def pump():
    end=time.monotonic()+.15
    while time.monotonic()<end:app.processEvents();time.sleep(.004)
with tempfile.TemporaryDirectory() as root:
    games=[dict(id=str(i),kind='custom',title=f'Game {i}') for i in range(10)]
    Library(data_dir=Path(root)).put_many(games)
    c=CountingController(games,{},Path(root),allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];c.window=window;pump();c.reads=0
    for _ in range(10):c.move(1);pump()
    closed_reads=c.reads
    c.edit();pump();assert c.reads>closed_reads,'Open editor did not read its artwork'
    c.cancelEdit();pump();before=c.reads
    for _ in range(10):c.move(1);pump()
    reopened_reads=c.reads-before
    c.manager.shutdown();c.idle_timer.stop();window.close();pump();del engine
    assert closed_reads==0 and reopened_reads==0,(closed_reads,reopened_reads)
assert not errors,'\n'.join(errors)
print('QT_CLOSED_EDITOR_WORK_OK: no artwork projection while closed, artwork available on open')
