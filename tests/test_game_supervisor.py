import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import game_supervisor as supervisor
from estante import Shelf
from library import Library


class SupervisorTests(TestCase):
    def test_ui_exits_only_after_supervisor_ready_and_acknowledges_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            process = Mock()
            host = SimpleNamespace(running_sessions={'one'}, game_launch_details={'one': ({'id': 'one'}, 'date', 1)},
                                   selected_game='one', active_category='Steam', view_mode='list',
                                   library=Mock(root=Path(folder)), background=Mock(), session_window_closed=False,
                                   supervised_sessions=set(), stop_controls=Mock(), get_application=Mock(return_value=Mock()))
            Shelf.handoff_for_game(host, 'one', process)
            host.get_application().quit.assert_not_called()
            _, ready, failed = host.background.call_args.args
            ready(Path(folder))
            self.assertTrue((Path(folder) / 'handoff').exists())
            self.assertIn('one', host.supervised_sessions)
            host.stop_controls.assert_called_once()
            host.get_application().quit.assert_called_once()

    def test_ui_stays_open_when_supervisor_fails(self):
        host = SimpleNamespace(running_sessions={'one'}, game_launch_details={'one': ({'id': 'one'}, 'date', 1)},
                               selected_game='one', active_category=None, view_mode='grid', library=Mock(),
                               background=Mock(), error=Mock(), get_application=Mock())
        Shelf.handoff_for_game(host, 'one', Mock())
        _, _, failed = host.background.call_args.args
        failed('Unavailable')
        host.get_application.assert_not_called()
        host.error.assert_called_once_with('Unavailable')
        self.assertFalse(host.supervisor_pending)

    def test_service_waits_for_real_game_records_once_and_reopens_without_gtk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'runner'
            folder.mkdir()
            library_root = root / 'library'
            library = Library(data_dir=library_root)
            library.save()
            marker = root / 'reopened'
            game = {'id': 'test', 'kind': 'local', 'title': 'Test', 'path': '/bin/sleep'}
            token = 'estante-test-session'
            process = subprocess.Popen(['/bin/sleep', '1'], env=dict(os.environ, ESTANTE_GAME_SESSION=token),
                                       start_new_session=True)
            spec = dict(game=game, launcher_pid=process.pid, token=token, root=str(library_root),
                        started='2026-10-22T10:00:00', started_at=time.monotonic(),
                        restore={'selected_game': 'test', 'view_mode': 'list', 'active_category': 'Steam'},
                        ui_pid=99999999, ui_identity='missing',
                        reopen=[sys.executable, '-c',
                                "import os,pathlib; pathlib.Path(" + repr(str(marker)) + ").write_text(os.environ['ESTANTE_RESUME_FILE'])"],
                        environment=dict(os.environ), cwd=str(root))
            path = folder / 'session.json'
            path.write_text(json.dumps(spec))
            (folder / 'handoff').touch()
            try:
                runner = subprocess.run([sys.executable, str(Path(supervisor.__file__)), str(path)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(runner.returncode, 0, runner.stderr)
                process.wait(timeout=3)
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                restored = json.loads(Path(marker.read_text()).read_text())
                self.assertEqual(restored, spec['restore'])
                stats = Library(data_dir=library_root).game_stats(game)
                self.assertEqual(stats['sessions'], 1)
                self.assertGreaterEqual(stats['seconds'], 1)
                self.assertIsNone(stats['history'][0]['exit_code'])
                self.assertFalse(folder.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait()

    def test_no_handoff_leaves_session_recording_to_ui(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'runner'
            folder.mkdir()
            spec = dict(game={}, launcher_pid=123, token=None)
            path = folder / 'session.json'
            path.write_text(json.dumps(spec))
            (folder / 'cancel').touch()
            with patch.object(supervisor, 'game_processes', return_value=[456]), \
                 patch('subprocess.Popen') as reopen:
                supervisor.run(path)
            reopen.assert_not_called()
            self.assertFalse(folder.exists())

    def test_systemd_failure_never_acknowledges_transfer(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'runner'
            folder.mkdir()
            process = SimpleNamespace(pid=123, estante_session_token='token')
            with patch.object(supervisor.tempfile, 'mkdtemp', return_value=str(folder)), \
                 patch.object(supervisor.shutil, 'which', return_value='/usr/bin/systemd-run'), \
                 patch.object(supervisor.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='No user bus')):
                with self.assertRaisesRegex(RuntimeError, 'No user bus'):
                    supervisor.prepare({'id': 'one'}, process, temporary, 'date', 1, {})
            self.assertTrue((folder / 'cancel').exists())
            self.assertFalse((folder / 'handoff').exists())
            self.assertEqual((folder / 'session.json').stat().st_mode & 0o777, 0o600)

    def test_prepare_preserves_explicit_qt_reopen_without_changing_default(self):
        for explicit in (None, [sys.executable, '/project/qt_app/main.py']):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)/'runner'
                folder.mkdir()
                (folder/'status.json').write_text(json.dumps({'state':'ready'}))
                process = SimpleNamespace(pid=123, estante_session_token='token')
                with patch.object(supervisor.tempfile, 'mkdtemp', return_value=str(folder)), \
                     patch.object(supervisor.shutil, 'which', return_value='/usr/bin/systemd-run'), \
                     patch.object(supervisor.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                    supervisor.prepare({'id':'one'}, process, temporary, 'date', 1, {}, reopen=explicit)
                spec = json.loads((folder/'session.json').read_text())
                if explicit is None:
                    self.assertTrue(spec['reopen'][-1].endswith('estante.py'))
                else:
                    self.assertEqual(spec['reopen'], explicit)
