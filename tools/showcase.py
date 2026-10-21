#!/usr/bin/env python3
"""Record repeatable Estante showcases without recording the rest of the desktop."""
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


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / ('showcase-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, choices=[24, 30, 60], default=30)
    parser.add_argument('--seconds', type=int, default=6, help='Duration of each layout clip')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'estante')
    args = parser.parse_args()
    if args.seconds < 6 or min(args.width, args.height) < 320 or args.width % 2 or args.height % 2:
        parser.error('Use at least 6 seconds and even dimensions of at least 320 pixels')
    if not shutil.which('ffmpeg'):
        parser.error('FFmpeg is required')
    if not (args.data_dir / 'library.json').is_file():
        parser.error('No library.json found; specify --data-dir')
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='estante-showcase-') as temporary:
        temporary = Path(temporary)
        library = temporary / 'library'
        library.mkdir()
        shutil.copyfile(args.data_dir / 'library.json', library / 'library.json')
        settings_file = args.data_dir / 'settings.json'
        settings = json.loads(settings_file.read_text()) if settings_file.is_file() else {}
        settings.update(check_updates_on_start=False, start_fullscreen=False, hide_while_playing=False)
        (library / 'settings.json').write_text(json.dumps(settings))
        for directory in args.data_dir.iterdir():
            if directory.is_dir():
                (library / directory.name).symlink_to(directory.resolve(), target_is_directory=True)
        os.environ['ESTANTE_DATA_DIR'] = str(library)
        os.environ['ESTANTE_PROFILE'] = '0'
        os.environ['ESTANTE_DISABLE_BLUR'] = '0'
        sys.path.insert(0, str(ROOT))
        from estante import App, Gtk, Gdk, GLib, Graphene
        from appearance import list_navigation
        from i18n import tr
        if not Gtk.init_check() or Gdk.Display.get_default() is None:
            print('Run this command from a terminal in your graphical desktop.', file=sys.stderr)
            return 2
        app = App()
        app.set_application_id('io.github.estante.Showcase')
        state = {'clip': -1, 'recorder': None, 'failed': False, 'results': []}
        clips = [('01-grid', 'grid'), ('02-carousel', 'carousel'), ('03-sense', 'ps5'),
                 ('04-list', 'list'), ('05-settings', 'settings')]
        def fail(error):
            state['failed'] = True
            print(str(error), file=sys.stderr)
            recorder = state.get('recorder')
            state['recording'] = False
            def stop():
                if recorder:
                    try:
                        recorder.finish()
                    except Exception:
                        pass
                GLib.idle_add(app.quit)
            Thread(target=stop, daemon=True).start()
            return False
        def setup_mode(mode):
            shelf = app.window
            shelf.leave_preferences()
            shelf.close_panel()
            shelf.change_view(mode)
            shelf.clear_library_filters()
            rows = shelf.tiles()
            if rows:
                shelf.select_tile(rows[0])
            shelf.hide_pointer()
        def advance():
            if not state.get('recording'):
                return False
            shelf = app.window
            if state['mode'] == 'grid':
                rows = shelf.tiles()
                current = shelf.selected_tile()
                index = rows.index(current) if current in rows else -1
                if rows:
                    shelf.select_tile(rows[(index + 1) % len(rows)])
            else:
                action = list_navigation(shelf.settings)[0][1] if state['mode'] == 'list' else 'right'
                shelf.navigate(action)
            return False
        def edit_second():
            shelf = app.window
            tile = shelf.selected_tile()
            if tile:
                shelf.edit_game(tile.game)
            return False
        def scroll_editor(duration):
            shelf = app.window
            clip = state['clip']
            started = time.monotonic()
            def scroll():
                if not state.get('recording') or state['clip'] != clip or not shelf.drawer.get_reveal_child():
                    return False
                adjustment = shelf.sidebar.get_last_child().get_vadjustment()
                maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
                progress = min(1, (time.monotonic() - started) / duration)
                adjustment.set_value(maximum * progress)
                return progress < 1
            GLib.timeout_add(100, scroll)
            return False
        def reveal_settings(section):
            if not state.get('recording'):
                return False
            shelf = app.window
            shelf.preferences(section)
            page = shelf.preferences_view.sections.get_visible_child()
            # Open appearance controls, but never API/credential sections.
            allowed = {tr('Inicio'), tr('Idioma'), tr('Tipo de mando')}
            for widget in descendants(page):
                if isinstance(widget, Gtk.Revealer):
                    card = widget.get_parent()
                    header = card.get_first_child()
                    if not isinstance(header, Gtk.Button):
                        continue
                    title = header.get_child().get_first_child().get_label()
                    if section in MODES or title in allowed:
                        widget.set_reveal_child(True)
            started = time.monotonic()
            def scroll():
                if not state.get('recording') or page != shelf.preferences_view.sections.get_visible_child():
                    return False
                adjustment = page.get_first_child().get_vadjustment()
                maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
                progress = min(1, max(0, (time.monotonic() - started - .2) / 1.7))
                adjustment.set_value(maximum * progress)
                return progress < 1
            GLib.timeout_add(100, scroll)
            return False
        def capture():
            if not state.get('recording'):
                return False
            try:
                shelf = app.window
                snapshot = Gtk.Snapshot()
                state['paintable'].snapshot(snapshot, args.width, args.height)
                node = snapshot.to_node()
                if node is not None:
                    texture = shelf.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, args.width, args.height))
                    pixbuf = Gdk.pixbuf_get_from_texture(texture)
                    if not pixbuf.get_has_alpha():
                        pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
                    pixels = pixbuf.get_pixels()
                    stride = pixbuf.get_rowstride()
                    row_size = args.width * 4
                    if stride != row_size:
                        pixels = b''.join(pixels[y*stride:y*stride+row_size] for y in range(args.height))
                    state['recorder'].submit(time.monotonic() - state['started'], pixels)
                return True
            except Exception as error:
                return fail(error)
        def finish_clip():
            if not state.get('recording'):
                return False
            state['recording'] = False
            for source in state.pop('repeat_timers', []):
                GLib.source_remove(source)
            recorder = state['recorder']
            def finish():
                try:
                    recorder.finish()
                    state['results'].append({'clip': state['name'] + '.mp4', 'dropped_capture_samples': recorder.dropped})
                    GLib.idle_add(next_clip)
                except Exception as error:
                    GLib.idle_add(fail, error)
            Thread(target=finish, daemon=True).start()
            return False
        def start_clip():
            try:
                duration = 12 if state['mode'] == 'settings' else args.seconds
                state['recorder'] = Recorder(args.output / (state['name'] + '.mp4'), args.width, args.height, args.fps, duration)
                state['started'] = time.monotonic()
                state['recording'] = True
                print('Recording ' + state['name'], flush=True)
                state['repeat_timers'] = [GLib.timeout_add(max(1, round(1000 / args.fps)), capture)]
                if state['mode'] == 'settings':
                    for index, section in enumerate(('global', 'grid', 'carousel', 'ps5', 'list')):
                        GLib.timeout_add(200 + index * 2300, reveal_settings, section)
                else:
                    clip = state['clip']
                    def later(delay, action):
                        def run():
                            if state.get('recording') and state['clip'] == clip:
                                action()
                            return False
                        GLib.timeout_add(round(delay * 1000), run)
                    for fraction in (.12, .24, .36):
                        later(duration * fraction, advance)
                    later(duration * .5, edit_second)
                    later(duration * .65, lambda: scroll_editor(duration * .3))
                GLib.timeout_add(duration * 1000, finish_clip)
            except Exception as error:
                return fail(error)
            return False
        def next_clip():
            state['clip'] += 1
            if state['clip'] == len(clips):
                (args.output / 'recording.json').write_text(json.dumps(state['results'], indent=2))
                print('Videos saved in ' + str(args.output), flush=True)
                app.quit()
                return False
            state['name'], state['mode'] = clips[state['clip']]
            try:
                if state['mode'] == 'settings':
                    app.window.preferences('global')
                else:
                    setup_mode(state['mode'])
                GLib.timeout_add(1000, start_clip)
            except Exception as error:
                return fail(error)
            return False
        def setup():
            shelf = app.window
            if len(shelf.library.games()) < 4:
                return fail('Import at least four games before recording the showcase.')
            shelf.fullscreen()
            state['paintable'] = Gtk.WidgetPaintable.new(shelf)
            next_clip()
            return False
        app.connect('activate', lambda *_: GLib.idle_add(setup))
        try:
            app.run([sys.argv[0]])
        finally:
            recorder = state.get('recorder')
            state['recording'] = False
            if recorder and recorder.thread.is_alive():
                recorder.finish()
        return 1 if state['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
