"""Isolated, read-only Qt Quick library experiment; never launches games."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from native_memory import configure_native_allocator
configure_native_allocator()
from appearance import background_effects_for, list_cover_size, cover_format_for
from library import Library
from tools.memory_fixture import populate_test_games
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine


def memory():
    values = {}
    for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
        fields = line.split()
        if fields and fields[0].rstrip(':') in ('Rss', 'Pss', 'Anonymous'):
            values[fields[0].rstrip(':')] = round(int(fields[1]) / 1024, 2)
    return values


class Probe(QObject):
    changed = Signal()

    def __init__(self, games, cover_field="cover"):
        super().__init__()
        self.games = games
        self.cover_field = cover_field
        self.index = 0
        self.visited = {0}

    @Property('QVariantList', constant=True)
    def entries(self):
        def url(game, field):
            path = Path(game.get(field) or '')
            return QUrl.fromLocalFile(str(path.resolve())).toString() if path.is_file() else ''
        return [dict(title=g['title'], cover=url(g, self.cover_field) or url(g, 'cover'), logo=url(g, 'logo'),
                     banner=url(g, 'banner'), secondary=url(g, 'banner_secondary')) for g in self.games]

    @Property(int, notify=changed)
    def selected(self):
        return self.index

    @Slot(int)
    def select(self, index):
        self.index = index % len(self.games)
        self.visited.add(self.index)
        self.changed.emit()

    @Slot(int)
    def move(self, delta):
        self.select(self.index + delta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=100)
    parser.add_argument('--auto', action='store_true')
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--output', default='/tmp/estante-qt-probe.jsonl')
    parser.add_argument('--width', type=int, default=2560)
    parser.add_argument('--height', type=int, default=1440)
    parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--screenshot', help='Save the settled rendered window as PNG')
    parser.add_argument('--dim', type=float, default=None)
    parser.add_argument('--blur', type=float, default=None, help='Blur strength, 0–1')
    args = parser.parse_args()
    if args.games < 1 or args.cycles < 1:
        parser.error('games and cycles must be positive')
    source = Path(os.environ.get('ESTANTE_DATA_DIR', Path.home()/'.local/share/estante'))
    # Copy state before constructing Library: even legacy migrations stay isolated.
    with tempfile.TemporaryDirectory(prefix='estante-qt-') as temporary:
        data = Path(temporary)
        (data/'library.json').write_bytes((source/'library.json').read_bytes())
        games = populate_test_games(Library(data_dir=data), args.games)
        settings = json.loads((source/'settings.json').read_text())
        effects = background_effects_for(settings, 'list')
        if settings.get('background_source') == 'global':
            background = settings.get('global_background', '')
            if background.startswith('bundled:'):
                background = str(ROOT/'assets/backgrounds'/background.removeprefix('bundled:'))
            for game in games:
                game['banner'] = background
                game['banner_secondary'] = ''
        app = QGuiApplication(sys.argv[:1])
        app.setApplicationName('Estante Qt · prueba aislada')
        probe = Probe(games, 'square_cover' if cover_format_for(settings, 'list') == 'square' else 'cover')
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('probe', probe)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('Main.qml'))))
        if not engine.rootObjects():
            return 1
        window = engine.rootObjects()[0]
        window.setProperty('dim', max(0, min(1, args.dim if args.dim is not None else effects['dim']/100)))
        window.setProperty('split', settings.get('background_splits', {}).get('list', 'single') == 'horizontal')
        cover_width, cover_height = list_cover_size(settings)
        window.setProperty('coverWidth', cover_width)
        window.setProperty('coverHeight', cover_height)
        window.setProperty('blurAmount', max(0, min(1, args.blur if args.blur is not None else effects['blur']/40)))
        window.resize(args.width, args.height)
        if not args.windowed:
            window.showFullScreen()
        frames = []
        last_frame = [None]
        def frame():
            now = time.perf_counter()
            if last_frame[0] is not None:
                frames.append((now-last_frame[0])*1000)
            last_frame[0] = now
        window.frameSwapped.connect(frame)
        output = Path(args.output)
        output.write_text('')
        cpu_start = time.process_time()
        wall_start = time.monotonic()
        def sample(label):
            ordered = sorted(frames)
            row = dict(label=label, games=len(games), visited=len(probe.visited),
                       width=window.width(), height=window.height(), **memory(),
                       graphics_api=str(window.rendererInterface().graphicsApi()),
                       cpu_one_core_percent=round(100*(time.process_time()-cpu_start)/(time.monotonic()-wall_start), 2),
                       frame_intervals=len(ordered),
                       frame_p95_ms=round(ordered[int((len(ordered)-1)*.95)], 2) if ordered else None)
            with output.open('a') as stream:
                stream.write(json.dumps(row)+'\n')
            print(json.dumps(row), flush=True)
            frames.clear()
            last_frame[0] = None
        navigation = QTimer()
        navigation.setInterval(130)
        steps = [0]
        def step():
            probe.move(1)
            steps[0] += 1
            if steps[0] % args.games == 0:
                sample('after_cycle_'+str(steps[0]//args.games))
            if steps[0] >= args.games*args.cycles:
                navigation.stop()
                QTimer.singleShot(10000, finish)
        def finish():
            sample('settled')
            if args.screenshot:
                window.grabWindow().save(args.screenshot)
            app.quit()
        navigation.timeout.connect(step)
        def start():
            sample('baseline')
            if args.auto:
                navigation.start()
        QTimer.singleShot(4000, start)
        gamepad = None
        if not args.auto:
            from controls import Gamepad
            def dispatch(action, *_):
                if action in ('left', 'right'):
                    probe.move(1 if action == 'right' else -1)
            try:
                gamepad = Gamepad(dispatch, window.isActive)
                controller_timer = QTimer()
                controller_timer.timeout.connect(gamepad.poll)
                controller_timer.start(16)
            except RuntimeError as error:
                print(error, file=sys.stderr)
        result = app.exec()
        if gamepad:
            gamepad.close()
        # Destroy QML bindings before releasing the Python context object.
        del engine
        return result


if __name__ == '__main__':
    sys.exit(main())
