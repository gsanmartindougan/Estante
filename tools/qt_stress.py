"""Repeat navigation and settings in Qt using an isolated synthetic library."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QUrl,QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from library import Library
from tools.memory_fixture import populate_test_games
from qt_app.main import LibraryController

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--games',type=int,default=100)
parser.add_argument('--cycles',type=int,default=2)
parser.add_argument('--output',default='/tmp/estante-qt-stress.jsonl')
args=parser.parse_args()
if args.games<1 or args.cycles<1:parser.error('games/cycles must be positive')
source=Path(os.environ.get('ESTANTE_DATA_DIR',Path.home()/'.local/share/estante'))
with tempfile.TemporaryDirectory(prefix='estante-qt-stress-') as folder:
    root=Path(folder)
    (root/'library.json').write_bytes((source/'library.json').read_bytes())
    library=Library(data_dir=root)
    games=populate_test_games(library,args.games)
    settings=json.loads((source/'settings.json').read_text())
    settings.update(check_updates_on_start=False,screensaver_enabled=False)
    app=QApplication([])
    app.setDesktopFileName("io.github.estante.Test")
    controller=LibraryController(games,settings,root,allow_launch=False)
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects()
    window=engine.rootObjects()[0];controller.window=window;window.showFullScreen()
    output=Path(args.output);output.write_text('')
    state={'step':0,'mode':0,'cycle':0};modes=['list','grid','carousel','ps5']
    def sample(label):
        row=dict(label=label,mode=controller.viewMode,games=len(games),width=window.width(),height=window.height(),renderer=str(window.rendererInterface().graphicsApi()))
        for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
            key,_,value=line.partition(':')
            if key in ('Rss','Pss','Anonymous','Private_Dirty'):row[key]=round(int(value.split()[0])/1024,1)
        with output.open('a') as stream:stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    def next_mode():
        if state['mode']>=len(modes):
            state['mode']=0;state['cycle']+=1
        if state['cycle']>=args.cycles:
            QTimer.singleShot(3000,finish);return
        controller.changeView(modes[state['mode']]);state['step']=0
        QTimer.singleShot(700,move.start)
    def step():
        controller.move(1);state['step']+=1
        if state['step']>=args.games:
            move.stop();QTimer.singleShot(1500,open_settings)
    def open_settings():
        sample(f"{state['cycle']}_after_navigation")
        controller.inputAction.emit('menu')
        QTimer.singleShot(1200,close_settings)
    def close_settings():
        controller.inputAction.emit('back')
        QTimer.singleShot(1500,after_settings)
    def after_settings():
        sample(f"{state['cycle']}_after_settings")
        state['mode']+=1;next_mode()
    def finish():
        sample('final');app.quit()
    move=QTimer();move.setInterval(130);move.timeout.connect(step)
    QTimer.singleShot(2500,lambda:(sample('baseline'),next_mode()))
    app.exec()
    controller.manager.shutdown();controller.idle_timer.stop();del engine
