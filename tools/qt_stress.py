"""Measure Qt navigation and resource lifecycles in a disposable library profile."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock
from urllib.parse import unquote
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QUrl,QCoreApplication,QEvent,QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from shiboken6 import isValid
from core.library import Library
from tools.memory_fixture import populate_test_games
from tools.showcase import recording_settings
from qt_app.main import LibraryController
from qt_app.images import ArtworkProvider
from qt_app.theme import apply_system_palette


def percentile(values, fraction):
    if not values:return 0
    return round(sorted(values)[min(len(values)-1,int((len(values)-1)*fraction))],3)


def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)


class CountingArtwork(ArtworkProvider):
    def __init__(self,cache):
        super().__init__(cache)
        self.lock=Lock();self.requested=0;self.active=0;self.failed=0;self.failures=[]
    def requestImage(self,identity,size,requestedSize):
        with self.lock:self.requested+=1;self.active+=1
        try:
            image=super().requestImage(identity,size,requestedSize)
            if image.isNull():
                with self.lock:
                    self.failed+=1
                    self.failures.append(dict(source=Path(unquote(identity)).name,requested_width=requestedSize.width(),requested_height=requestedSize.height()))
            return image
        finally:
            with self.lock:self.active-=1
    def counters(self):
        with self.lock:return dict(image_requests=self.requested,active_decodes=self.active,failed_decodes=self.failed)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games',type=int,default=100)
    parser.add_argument('--cycles',type=int,default=3)
    parser.add_argument('--interval-ms',type=int,default=40)
    parser.add_argument('--output',type=Path,default=Path('/tmp/estante-qt-stress.jsonl'))
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('ESTANTE_DATA_DIR',Path.home()/'.local/share/estante')))
    parser.add_argument('--work-dir',type=Path,default=Path(__file__).resolve().parents[1]/'dist/stress-profiles')
    args=parser.parse_args()
    if min(args.games,args.cycles,args.interval_ms)<1:parser.error('games/cycles/interval must be positive')
    if not (args.data_dir/'library.json').is_file():parser.error('library.json missing')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text('')
    args.work_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='qt-stress-',dir=args.work_dir) as folder:
        root=Path(folder)
        (root/'library.json').write_bytes((args.data_dir/'library.json').read_bytes())
        library=Library(data_dir=root)
        games=populate_test_games(library,args.games,link_artwork=True)
        settings_file=args.data_dir/'settings.json'
        settings=recording_settings(json.loads(settings_file.read_text()) if settings_file.is_file() else {})
        settings.update(screensaver_enabled=False,playing_behavior='none',start_fullscreen=False)
        (root/'settings.json').write_text(json.dumps(settings))
        app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');apply_system_palette(app)
        controller=LibraryController(games,settings,root,allow_launch=False)
        engine=QQmlApplicationEngine();warnings=[]
        engine.warnings.connect(lambda rows:warnings.extend(r.toString() for r in rows))
        provider=CountingArtwork(root/'thumbnails');engine.addImageProvider('artwork',provider)
        controller.use_image_provider=True
        engine.rootContext().setContextProperty('libraryController',controller)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
        if not engine.rootObjects():raise RuntimeError('\n'.join(warnings))
        window=engine.rootObjects()[0];controller.window=window;window.resize(1920,1080)
        started=time.monotonic();process_start=time.process_time()
        lateness=[];process_events=[];last_tick=time.monotonic();rows=[];checks=0
        def heartbeat():
            nonlocal last_tick
            now=time.monotonic();lateness.append(max(0,(now-last_tick)*1000-16));last_tick=now
        heartbeat_timer=QTimer();heartbeat_timer.timeout.connect(heartbeat);heartbeat_timer.start(16)
        def pump(seconds):
            until=time.monotonic()+seconds
            while time.monotonic()<until:
                tick=time.perf_counter();app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
                process_events.append((time.perf_counter()-tick)*1000)
                time.sleep(.002)
        def write(row):
            with args.output.open('a') as stream:stream.write(json.dumps(row)+'\n')
        def sample(label,cycle=-1,**extra):
            row=dict(label=label,cycle=cycle,mode=controller.viewMode,games=args.games,
                     elapsed_s=round(time.monotonic()-started,2),cpu_s=round(time.process_time()-process_start,2),
                     renderer=str(window.rendererInterface().graphicsApi()),platform=app.platformName(),
                     visual_items=len(list(visual(window.contentItem()))),warnings=len(warnings),**provider.counters(),**extra)
            for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
                key,_,value=line.partition(':')
                if key in ('Rss','Pss','Anonymous','Private_Dirty'):row[key+'_MiB']=round(int(value.split()[0])/1024,2)
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith('VmHWM:'):row['peak_Rss_MiB']=round(int(line.split()[1])/1024,2)
            rows.append(row);write(row)
            print(json.dumps(row),flush=True)
        memory_timer=QTimer();memory_timer.timeout.connect(lambda:sample('periodic'));memory_timer.start(5000)
        pump(2);sample('baseline')
        try:
            for cycle in range(args.cycles):
                for mode in ('list','grid','carousel','ps5'):
                    controller.changeView(mode);controller.select(0);pump(1)
                    sample('mode_start',cycle)
                    lateness.clear();process_events.clear();dispatch=[]
                    for _ in range(args.games):
                        tick=time.perf_counter();controller.move(1);dispatch.append((time.perf_counter()-tick)*1000)
                        pump(max(.001,args.interval_ms/1000-(time.perf_counter()-tick)))
                    pump(1)
                    sample('after_navigation',cycle,dispatch_p50_ms=percentile(dispatch,.5),dispatch_p95_ms=percentile(dispatch,.95),
                           event_lateness_p95_ms=percentile(lateness,.95),event_lateness_max_ms=round(max(lateness,default=0),3),
                           process_events_p95_ms=percentile(process_events,.95),process_events_max_ms=round(max(process_events,default=0),3))
                    selected=controller.catalog.selected_id
                    for section in (4,{'list':7,'grid':8,'carousel':9,'ps5':10}[mode]):
                        panel=window.findChild(QObject,'managementPanel');panel.openSection(section,False);pump(.15)
                        loader=window.findChild(QObject,'managementPageLoader');page=loader.property('item')
                        assert page is not None
                        for item in visual(page):
                            if item.objectName().startswith('settingsGroup:'):item.setProperty('expanded',True)
                        pump(.25);sample('settings_open',cycle,section=section)
                        panel.close();pump(.4)
                        assert loader.property('item') is None and not isValid(page),'Closed settings page retained'
                        checks+=1
                    sample('after_settings',cycle)
                    controller.previewScreensaver();pump(.3)
                    assert controller.screensaverActive and controller.entries==[]
                    for _ in range(2):
                        controller._last_slide=0;controller.checkIdle();pump(.2)
                    sample('screensaver',cycle)
                    controller.recordActivity();pump(.5)
                    assert not controller.screensaverActive and controller.catalog.selected_id==selected
                    checks+=1;sample('after_screensaver',cycle)
                    loader=window.findChild(QObject,'librarySceneLoader');scene=loader.property('item')
                    controller._launch_game=dict(controller.catalog.selected)
                    controller._busy=True;controller._loading=False;controller.sessionChanged.emit();pump(.8)
                    assert loader.property('item') is None and not isValid(scene),'Library retained while playing'
                    checks+=1;sample('playing',cycle)
                    controller.handle_session(('finished',0));pump(.8)
                    assert loader.property('item') is not None and controller.catalog.selected_id==selected
                    checks+=1;sample('mode_end',cycle)
            pump(2);sample('final')
            summary=dict(label='summary',games=args.games,cycles=args.cycles,interval_ms=args.interval_ms,
                         navigation_steps=args.games*args.cycles*4,lifecycle_assertions=checks,warnings=warnings,
                         elapsed_s=round(time.monotonic()-started,2),cpu_s=round(time.process_time()-process_start,2),
                         peak_Rss_MiB=max(r['peak_Rss_MiB'] for r in rows),peak_Pss_MiB=max(r['Pss_MiB'] for r in rows),
                         failed_sources=provider.failures,**provider.counters())
            write(summary);print(json.dumps(summary),flush=True)
            if warnings:raise RuntimeError('Qt warnings during stress run; inspect output')
        finally:
            heartbeat_timer.stop();memory_timer.stop();controller.manager.shutdown();controller.idle_timer.stop()
            controller._busy=False;controller._loading=False;controller.restoreCursor();window.close()
            engine.deleteLater();pump(.1);controller.window=None
    return 0


if __name__=='__main__':raise SystemExit(main())
