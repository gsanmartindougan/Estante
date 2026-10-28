import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from qt_app.launcher_processes import running_clients, launch_hidden


class LauncherProcessesTests(TestCase):
    def test_detects_clients_but_not_games_or_helpers(self):
        with TemporaryDirectory() as folder:
            proc = Path(folder)
            def process(pid, comm, args):
                item = proc / str(pid)
                item.mkdir()
                (item / 'comm').write_text(comm)
                (item / 'cmdline').write_bytes(b'\0'.join(s.encode() for s in args))
            process(1, 'steamwebhelper', ['steamwebhelper'])
            process(2, 'python3', ['python3', '-m', 'faugus.runner', '--game', 'one'])
            self.assertEqual(running_clients(proc), set())
            process(3, 'steam', ['/usr/lib/steam/steam'])
            process(4, 'python3', ['/usr/bin/python3', '-m', 'faugus.tray_only', '--hide'])
            self.assertEqual(running_clients(proc), {'steam', 'faugus'})
            with patch('qt_app.launcher_processes.os.getuid', return_value=os.getuid()+1):
                self.assertEqual(running_clients(proc), set())

    def test_native_faugus_starts_hidden(self):
        with patch('qt_app.launcher_processes.shutil.which', return_value='/usr/bin/faugus-launcher'), patch('qt_app.launcher_processes.subprocess.Popen') as launch:
            launch_hidden('faugus')
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/faugus-launcher', '--hide'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_exit_is_optional_and_skips_session_transfer(self):
        from qt_app.launcher_processes import close_on_exit
        for settings, transferred in [({}, False), ({'close_steam_on_exit': True, 'close_faugus_on_exit': True}, True)]:
            with patch('qt_app.launcher_processes.running_clients') as running, patch('qt_app.launcher_processes.close_client') as close:
                self.assertEqual(close_on_exit(settings, transferred), {})
                running.assert_not_called()
                close.assert_not_called()

    def test_closes_only_enabled_running_clients_and_isolates_failures(self):
        from qt_app.launcher_processes import close_on_exit
        with patch('qt_app.launcher_processes.running_clients', return_value={'steam', 'faugus'}), patch('qt_app.launcher_processes.close_client') as close:
            close_on_exit({'close_steam_on_exit': True})
            close.assert_called_once_with('steam')
        with patch('qt_app.launcher_processes.running_clients', return_value={'faugus'}), patch('qt_app.launcher_processes.close_client') as close:
            close_on_exit({'close_steam_on_exit': True})
            close.assert_not_called()
        with patch('qt_app.launcher_processes.running_clients', return_value={'steam', 'faugus'}), patch('qt_app.launcher_processes.close_client', side_effect=OSError('unavailable')) as close:
            errors = close_on_exit({'close_steam_on_exit': True, 'close_faugus_on_exit': True})
            self.assertEqual(set(errors), {'steam', 'faugus'})
            self.assertEqual(close.call_count, 2)

    def test_normal_steam_shutdown(self):
        from qt_app.launcher_processes import close_client
        with patch('qt_app.launcher_processes.shutil.which', return_value='/usr/bin/steam'), patch('qt_app.launcher_processes.subprocess.run') as run:
            close_client('steam')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/steam', '-shutdown'])

    def test_faugus_quit_uses_tray_or_application_action(self):
        from qt_app.launcher_processes import close_client
        from types import SimpleNamespace
        for result in (0, 1):
            with patch('qt_app.launcher_processes.shutil.which', return_value='/usr/bin/gdbus'), patch('qt_app.launcher_processes.subprocess.run', return_value=SimpleNamespace(returncode=result)) as run:
                close_client('faugus')
                self.assertEqual(run.call_count, 1 if result == 0 else 2)
                first = run.call_args_list[0].args[0]
                self.assertIn('io.github.Faugus.Tray.Quit', first)
                self.assertIn('io.github.Faugus.faugus-launcher.Tray', first)
                if result:
                    self.assertIn('org.gtk.Actions.Activate', run.call_args.args[0])
                    self.assertIn('quit', run.call_args.args[0])

    def test_heroic_main_process_detection_excludes_electron_helpers(self):
        from qt_app.launcher_processes import is_heroic_main
        self.assertTrue(is_heroic_main([b'/usr/bin/electron43', b'/usr/lib/heroic-games-launcher/app.asar']))
        self.assertTrue(is_heroic_main([b'/app/bin/heroic', b'--no-gui']))
        self.assertFalse(is_heroic_main([b'/app/bin/heroic', b'--type=renderer']))
        self.assertFalse(is_heroic_main([b'/usr/bin/wine', b'game.exe']))

    def test_heroic_hidden_launch(self):
        with patch('qt_app.launcher_processes.shutil.which', return_value='/usr/bin/heroic'), patch('qt_app.launcher_processes.subprocess.Popen') as launch:
            launch_hidden('heroic')
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/heroic', '--no-gui'])

    def test_heroic_close_only_signals_main_process_and_protects_games(self):
        import signal
        from qt_app.launcher_processes import close_heroic
        with TemporaryDirectory() as folder:
            proc=Path(folder)
            for pid,args in [(11,b'/usr/bin/electron43\0/usr/lib/heroic-games-launcher/app.asar\0'),(12,b'/app/bin/heroic\0--type=renderer\0'),(13,b'/usr/bin/wine\0game.exe\0')]:
                entry=proc/str(pid);entry.mkdir();(entry/'cmdline').write_bytes(args);(entry/'environ').write_bytes(b'')
            with patch('qt_app.launcher_processes.os.pidfd_open',return_value=99) as pidfd, patch('qt_app.launcher_processes.signal.pidfd_send_signal') as send, patch('qt_app.launcher_processes.os.close'):
                close_heroic(proc)
                pidfd.assert_called_once_with(11)
                send.assert_called_once_with(99,signal.SIGTERM)
            (proc/'13/environ').write_bytes(b'HEROIC_APP_NAME=test\0HEROIC_APP_RUNNER=gog\0')
            with patch('qt_app.launcher_processes.signal.pidfd_send_signal') as send, self.assertRaises(RuntimeError):
                close_heroic(proc)
            send.assert_not_called()
