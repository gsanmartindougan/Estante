#!/usr/bin/env python3
"""Record repeatable Qt Estante showcases without recording the rest of the desktop."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from queue import Queue, Full
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import time
import os

ROOT = Path(__file__).resolve().parents[1]
MODES = ('grid', 'carousel', 'ps5', 'list')


def encoder_command(path, width, height, fps):
    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-n', '-f', 'rawvideo',
            '-pixel_format', 'rgba', '-video_size', f'{width}x{height}', '-framerate', str(fps),
            '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)]


class Recorder:
    def __init__(self, path, width, height, fps, duration):
        self.fps, self.frames = fps, round(fps * duration)
        self.frame_bytes = width * height * 4
        self.queue = Queue(maxsize=2)
        self.dropped = 0
        self.error = None
        self.log = path.with_suffix('.log').open('wb')
        self.process = subprocess.Popen(encoder_command(path, width, height, fps), stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=self.log)
        self.thread = Thread(target=self.write, daemon=True)
        self.thread.start()

    def submit(self, elapsed, pixels):
        if len(pixels) != self.frame_bytes:
            raise ValueError('Captured frame dimensions do not match encoder dimensions')
        try:
            self.queue.put_nowait((min(self.frames - 1, round(elapsed * self.fps)), pixels))
        except Full:
            self.dropped += 1

    def write(self):
        position, previous = 0, None
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                target, pixels = item
                while position < target and previous is not None:
                    self.process.stdin.write(previous)
                    position += 1
                if position <= target:
                    self.process.stdin.write(pixels)
                    position += 1
                    previous = pixels
            while previous is not None and position < self.frames:
                self.process.stdin.write(previous)
                position += 1
        except Exception as error:
            self.error = str(error)
        finally:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            if self.process.wait() and self.error is None:
                self.error = 'FFmpeg failed; inspect the clip .log file.'
            self.log.close()

    def finish(self):
        while self.thread.is_alive():
            try:
                self.queue.put(None, timeout=.2)
                break
            except Full:
                continue
        self.thread.join()
        if self.error:
            raise RuntimeError(self.error)


def descendants(item):
    """Walk Qt Quick's visual tree, including popup content."""
    yield item
    for child in item.childItems():
        yield from descendants(child)


def recording_settings(settings):
    """Use a private profile without credentials or external startup actions."""
    settings = dict(settings)
    for key in ('steamgriddb_key', 'igdb_client_id', 'igdb_client_secret'):
        settings.pop(key, None)
    settings.update(check_updates_on_start=False, start_fullscreen=False,
                    onscreen_keyboard='disabled', keyboard_fallback=False,
                    show_launcher_details={mode: False for mode in MODES})
    for client in ('steam', 'faugus', 'heroic'):
        settings['start_' + client + '_on_start'] = False
        settings['close_' + client + '_on_exit'] = False
    return settings


def rgba_pixels(image, width, height):
    from PySide6.QtGui import QImage
    if image.isNull():
        raise RuntimeError('Qt returned an empty window capture; use a supported Qt rendering platform.')
    if image.width() != width or image.height() != height:
        image = image.scaled(width, height)
    image = image.convertToFormat(QImage.Format_RGBA8888)
    data = bytes(image.constBits())
    stride, row_size = image.bytesPerLine(), width * 4
    return data if stride == row_size else b''.join(data[y*stride:y*stride+row_size] for y in range(height))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / ('showcase-qt-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--width', type=int, default=2560)
    parser.add_argument('--height', type=int, default=1440)
    parser.add_argument('--fps', type=int, choices=[24, 30, 60], default=30)
    parser.add_argument('--seconds', type=int, default=6, help='Duration of each layout clip; settings uses 12 seconds')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'estante')
    args = parser.parse_args()
    if args.seconds < 6 or min(args.width, args.height) < 320 or args.width % 2 or args.height % 2:
        parser.error('Use at least 6 seconds and even dimensions of at least 320 pixels')
    if not shutil.which('ffmpeg'):
        parser.error('FFmpeg is required')
    if not (args.data_dir / 'library.json').is_file():
        parser.error('No library.json found; specify --data-dir')
    sys.path.insert(0, str(ROOT))
    try:
        from PySide6.QtCore import QObject, QUrl, QTimer, Qt
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError:
        parser.error('Use the Qt Python environment: .venv-qt/bin/python tools/showcase.py')
    from library import Library
    from i18n import set_language, tr
    from qt_app.main import LibraryController
    from qt_app.images import ArtworkProvider
    from qt_app.theme import apply_system_palette
    from qt_app.translation import Translator
    from qt_app.launcher_processes import running_clients, CLIENT_NAMES
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='estante-showcase-qt-') as temporary:
        library_path = Path(temporary) / 'library'
        library_path.mkdir()
        shutil.copyfile(args.data_dir / 'library.json', library_path / 'library.json')
        settings_file = args.data_dir / 'settings.json'
        settings = recording_settings(json.loads(settings_file.read_text()) if settings_file.is_file() else {})
        (library_path / 'settings.json').write_text(json.dumps(settings))
        # Existing absolute artwork paths stay read-only; relative paths resolve as
        # in the normal app. No links to the user's writable profile are created.
        library = Library(data_dir=library_path)
        if len(library.games()) < 4:
            parser.error('Import at least four games before recording the showcase.')
        set_language(settings.get('language', 'system'))
        app = QApplication(sys.argv[:1])
        app.setDesktopFileName('io.github.estante.Showcase')
        apply_system_palette(app)
        translator = Translator(app)
        app.installTranslator(translator)
        controller = LibraryController(library.games(), settings, library_path, allow_launch=False)
        engine = QQmlApplicationEngine()
        engine.addImageProvider('artwork', ArtworkProvider(Path(temporary)/'thumbnails'))
        controller.use_image_provider = True
        controller.appearanceChanged.connect(engine.retranslate)
        engine.rootContext().setContextProperty('libraryController', controller)
        engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
        if not engine.rootObjects():
            controller.manager.shutdown()
            return 1
        window = engine.rootObjects()[0]
        controller.window = window
        window.resize(args.width, args.height)
        window.setMinimumSize(window.size())
        window.setMaximumSize(window.size())
        window.setCursor(QCursor(Qt.BlankCursor))
        try:
            running = running_clients()
            controller.launchers.apply_snapshot({key: 'open' if key in running else 'closed' for key in CLIENT_NAMES}, '')
        except OSError:
            pass
        clips = [('01-grid', 'grid'), ('02-carousel', 'carousel'), ('03-sense', 'ps5'),
                 ('04-list', 'list'), ('05-settings', 'settings')]
        state = dict(clip=-1, recorder=None, recording=False, failed=False, results=[])
        capture_timer = QTimer()
        animation_timer = QTimer()
        actions = []

        def popup(name):
            return window.findChild(QObject, name)

        def fail(error):
            print(str(error), file=sys.stderr)
            state['failed'] = True
            state['recording'] = False
            capture_timer.stop()
            animation_timer.stop()
            app.quit()

        def capture():
            if not state['recording']: return
            try:
                pixels = rgba_pixels(window.grabWindow(), args.width, args.height)
                state['recorder'].submit(time.monotonic()-state['started'], pixels)
            except Exception as error:
                fail(error)

        def schedule(delay, action):
            actions.append((delay, action))

        def tick():
            elapsed = time.monotonic()-state['started']
            while actions and actions[0][0] <= elapsed:
                _, action = actions.pop(0)
                try: action()
                except Exception as error: fail(error); return
            if elapsed >= state['duration']:
                finish_clip()

        def scroll_content(progress):
            # Both the editor and settings use Qt Quick flickables.
            active = popup('gameEditor') if controller.editing else popup('managementPanel')
            if not active or not active.property('visible'): return
            # Popup.contentItem belongs to the visual overlay, not QObject.children().
            content = active.property('contentItem')
            for item in descendants(content):
                if item.metaObject().indexOfProperty('contentY') < 0: continue
                maximum = max(0, item.property('contentHeight')-item.height())
                if maximum: item.setProperty('contentY', maximum*progress)

        def reveal_settings(section):
            panel = popup('managementPanel')
            panel.openSection(section, False)
            allowed = {tr('Inicio'), tr('Idioma'), tr('Tipo de mando')}
            for item in descendants(window.contentItem()):
                if item.objectName().startswith('settingsGroup:'):
                    title = item.objectName().split(':',1)[1]
                    if section != 4 or title in allowed: item.setProperty('expanded', True)

        def start_clip():
            try:
                state['duration'] = 12 if state['mode']=='settings' else args.seconds
                state['recorder'] = Recorder(args.output/(state['name']+'.mp4'), args.width, args.height, args.fps, state['duration'])
                state['started'] = time.monotonic()
                state['recording'] = True
                actions.clear()
                if state['mode']=='settings':
                    for index, section in enumerate((4,8,9,10,7)):
                        schedule(.2+index*2.3, lambda section=section: reveal_settings(section))
                else:
                    for fraction in (.12,.24,.36): schedule(state['duration']*fraction, lambda: controller.move(1))
                    schedule(state['duration']*.5, controller.edit)
                    for step in range(1,11):
                        schedule(state['duration']*(.65+.03*step),lambda step=step:scroll_content(step/10))
                actions.sort(key=lambda row:row[0])
                print('Recording Qt '+state['name'], flush=True)
                capture()
                capture_timer.start(round(1000/args.fps))
                animation_timer.start(16)
            except Exception as error:
                fail(error)

        def finish_clip():
            state['recording'] = False
            capture_timer.stop()
            animation_timer.stop()
            try:
                state['recorder'].finish()
                state['results'].append(dict(clip=state['name']+'.mp4',frontend='qt',dropped_capture_samples=state['recorder'].dropped))
                QTimer.singleShot(0,next_clip)
            except Exception as error:
                fail(error)

        def next_clip():
            state['clip'] += 1
            if state['clip'] == len(clips):
                (args.output/'recording.json').write_text(json.dumps(state['results'],indent=2))
                print('Qt videos saved in '+str(args.output),flush=True)
                app.quit()
                return
            state['name'],state['mode'] = clips[state['clip']]
            try:
                controller.cancelEdit()
                popup('managementPanel').close()
                controller.search('')
                controller.category(0)
                controller.select(0)
                if state['mode']=='settings': reveal_settings(4)
                else: controller.changeView(state['mode'])
                QTimer.singleShot(1000,start_clip)
            except Exception as error:
                fail(error)

        capture_timer.timeout.connect(capture)
        animation_timer.timeout.connect(tick)
        QTimer.singleShot(1000,next_clip)
        try:
            app.exec()
        finally:
            state['recording'] = False
            capture_timer.stop()
            animation_timer.stop()
            recorder = state.get('recorder')
            if recorder and recorder.thread.is_alive(): recorder.finish()
            controller.manager.shutdown()
            controller.idle_timer.stop()
            window.close()
            del engine
        return 1 if state['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
