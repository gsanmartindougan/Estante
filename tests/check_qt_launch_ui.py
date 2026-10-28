"""Graphical loader integration, with a temporary game and delayed readiness."""
import sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library

app=QApplication([])
app.setDesktopFileName("io.github.estante.Test");errors=[];captured=[];finished=[]
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    script=root/'game.sh';script.write_text('#!/bin/sh\nsleep 2\n')
    image=QImage(160,240,QImage.Format.Format_RGB32);image.fill(0xff456789);image.save(str(root/'cover.png'))
    library=Library(data_dir=root)
    game=Library.local_game('Loader test',str(script),cover=str(root/'cover.png'));library.put(game)
    controller=LibraryController([game],{'playing_behavior':'none'},root)
    engine=QQmlApplicationEngine();engine.warnings.connect(lambda messages:errors.extend(str(m) for m in messages))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window
    def wait(game,process,on_started,**options):
        time.sleep(1.2);on_started();return process.wait()
    def snapshot():
        assert controller.loading
        captured.append(window.grabWindow().save('/tmp/estante-qt-loader.png'))
    def changed():
        if not controller.busy:
            finished.append(True);app.quit()
    controller.sessionChanged.connect(changed)
    QTimer.singleShot(300,controller.play)
    QTimer.singleShot(1000,snapshot)
    QTimer.singleShot(7000,app.quit)
    with patch('qt_app.session.wait_for_game',side_effect=wait):app.exec()
    assert captured==[True] and finished and not errors,errors
    assert Library(data_dir=root).game_stats(game)['sessions']==1
    controller.manager.shutdown();controller.idle_timer.stop();del engine
print('QT_LOADER_INTEGRATION_OK')
