#!/usr/bin/env python3
"""Compare repeatable library navigation with and without GSK blur on the desktop."""
import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare', action='store_true', help='Run both variants sequentially')
    parser.add_argument('--no-blur', action='store_true')
    parser.add_argument('--cache-state', choices=['cold', 'warm'], default='cold',
                        help='Warm performs a separate preparation run before measuring')
    parser.add_argument('--cache-dir', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--prepare-cache', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--layout', choices=['list', 'carousel'], default='list')
    parser.add_argument('--data-dir', type=Path,
                        default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'estante')
    args = parser.parse_args()
    if args.seconds < 3:
        parser.error('--seconds must be at least 3')
    if args.compare or (args.cache_state == 'warm' and args.cache_dir is None):
        with tempfile.TemporaryDirectory(prefix='estante-profile-cache-') as cache_root:
            variants = (False, True) if args.compare else (args.no_blur,)
            for disabled in variants:
                command = [sys.executable, __file__, '--seconds', str(args.seconds), '--layout', args.layout,
                           '--data-dir', str(args.data_dir), '--cache-dir', str(Path(cache_root) / str(disabled)),
                           '--cache-state', args.cache_state]
                if disabled:
                    command.append('--no-blur')
                if args.cache_state == 'warm':
                    print('Preparing cache before measurement (blur=' + str(not disabled) + ')…', file=sys.stderr)
                    preparation = subprocess.run(command + ['--prepare-cache'], stdout=subprocess.PIPE, text=True)
                    if preparation.returncode:
                        return preparation.returncode
                result = subprocess.run(command)
                if result.returncode:
                    return result.returncode
        return 0
    if not (args.data_dir / 'library.json').is_file():
        parser.error('No library.json found; use --data-dir with your Estante data directory')
    with tempfile.TemporaryDirectory(prefix='estante-render-profile-') as temporary:
        temporary = Path(temporary)
        library = temporary / 'library'
        library.mkdir()
        shutil.copyfile(args.data_dir / 'library.json', library / 'library.json')
        settings_file = args.data_dir / 'settings.json'
        settings = json.loads(settings_file.read_text()) if settings_file.is_file() else {}
        settings.update(layout=args.layout, check_updates_on_start=False, start_fullscreen=False)
        (library / 'settings.json').write_text(json.dumps(settings))
        # Preserve access to images referenced relative to the data directory.
        for folder in args.data_dir.iterdir():
            if folder.is_dir():
                (library / folder.name).symlink_to(folder.resolve(), target_is_directory=True)
        os.environ['ESTANTE_PROFILE'] = '1'
        os.environ['ESTANTE_DATA_DIR'] = str(library)
        os.environ['XDG_CACHE_HOME'] = str(args.cache_dir or temporary / 'cache')
        os.environ['ESTANTE_DISABLE_BLUR'] = '1' if args.no_blur else '0'
        sys.path.insert(0, str(ROOT))
        from estante import App, Gdk, GLib, Gtk
        from appearance import list_navigation
        from profiling import reset, report, counters
        from image_cache import images
        if not Gtk.init_check() or Gdk.Display.get_default() is None:
            print('Run this command from a terminal in your graphical desktop.', file=sys.stderr)
            return 2
        app = App()
        app.set_application_id('io.github.estante.RenderingProfile')
        samples = []
        state = {}
        def frame(widget, clock):
            now = clock.get_frame_time()
            if state.get('measuring') and 'last_frame' in state:
                samples.append((now - state['last_frame']) / 1000)
            state['last_frame'] = now
            return True
        def step():
            if not state.get('running', True):
                return False
            shelf = app.window
            direction = list_navigation(shelf.settings)[0][1] if args.layout == 'list' else 'right'
            shelf.navigate(direction)
            return True
        def begin():
            reset()
            state['measuring'] = True
            state['started'] = time.monotonic()
            usage = resource.getrusage(resource.RUSAGE_SELF)
            state['cpu'] = usage.ru_utime + usage.ru_stime
            GLib.timeout_add(round(args.seconds * 1000), finish)
            return False
        def finish():
            state['running'] = False
            usage = resource.getrusage(resource.RUSAGE_SELF)
            wall = time.monotonic() - state['started']
            intervals = sorted(samples)
            renderer = app.window.get_renderer()
            slow_threshold = statistics.median(intervals) * 1.5 if intervals else 0
            print(json.dumps({
                'blur': not args.no_blur, 'layout': args.layout,
                'cache_state': args.cache_state, 'preparation': args.prepare_cache,
                'renderer': renderer.__gtype__.name if renderer else None,
                'duration_seconds': round(wall, 2),
                'cpu_percent_one_core': round((usage.ru_utime + usage.ru_stime - state['cpu']) / wall * 100, 2),
                'peak_rss_mib': round(usage.ru_maxrss / 1024, 1),
                'components': report(),
                'image_counters': counters(),
                'frame_samples': len(intervals),
                'long_frame_intervals': sum(value > slow_threshold for value in intervals) if intervals else 0,
                'frame_interval_median_ms': round(statistics.median(intervals), 2) if intervals else None,
                'frame_interval_p95_ms': round(intervals[min(len(intervals)-1, int(len(intervals)*.95))], 2) if intervals else None,
                'note': 'Component wall times are inclusive and may overlap; worker timings run off the UI thread. Frame intervals are not GPU execution time. Compare repeated runs on the same desktop.'
            }, ensure_ascii=False), flush=True)
            # Drain optional writes after recording metrics, without blocking GTK.
            deadline = time.monotonic() + 5
            def drained():
                if images.writes_idle():
                    app.quit()
                    return False
                if time.monotonic() >= deadline:
                    state['invalid'] = True
                    print('Cache writer did not finish before timeout; warm comparison is incomplete.', file=sys.stderr)
                    app.quit()
                    return False
                return True
            if drained():
                GLib.timeout_add(50, drained)
            return False
        def setup():
            shelf = app.window
            shelf.clear_library_filters()
            if len(shelf.tiles()) < 2:
                print('At least two games are required for navigation profiling.', file=sys.stderr)
                app.quit()
                state['invalid'] = True
                return False
            shelf.set_default_size(1200, 800)
            shelf.focus_library()
            shelf.add_tick_callback(frame)
            GLib.timeout_add(130, step)
            GLib.timeout_add(2000, begin)
            return False
        app.connect('activate', lambda *_: GLib.idle_add(setup))
        app.run([sys.argv[0]])
        return 2 if state.get('invalid') else 0


if __name__ == '__main__':
    raise SystemExit(main())
