from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import os
from qt_app import steam_startup as startup


class SteamStartupTests(TestCase):
    def test_detects_client_not_webhelper(self):
        with TemporaryDirectory() as folder:
            proc = Path(folder)
            entry = proc / '123'
            entry.mkdir()
            (entry / 'comm').write_text('steamwebhelper\n')
            self.assertFalse(startup.steam_running(proc))
            (entry / 'comm').write_text('steam\n')
            self.assertTrue(startup.steam_running(proc))
            with patch.object(startup.os, 'getuid', return_value=os.getuid()+1):
                self.assertFalse(startup.steam_running(proc))

    def test_running_client_is_left_alone(self):
        with patch.object(startup, 'steam_running', return_value=True), patch.object(startup.subprocess, 'Popen') as launch:
            startup.ensure_steam()
            launch.assert_not_called()

    def test_native_launch_is_silent_and_detached(self):
        with patch.object(startup, 'steam_running', return_value=False), patch.object(startup.shutil, 'which', return_value='/usr/bin/steam'), patch.object(startup.subprocess, 'Popen') as launch:
            startup.ensure_steam()
            self.assertEqual(launch.call_args.args[0], ['/usr/bin/steam', '-silent'])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_flatpak_only_launches_if_installed(self):
        for result in (0, 1):
            with patch.object(startup, 'steam_running', return_value=False), patch.object(startup.shutil, 'which', side_effect=[None, '/usr/bin/flatpak']), patch.object(startup.subprocess, 'run', return_value=SimpleNamespace(returncode=result)), patch.object(startup.subprocess, 'Popen') as launch:
                startup.ensure_steam()
                self.assertEqual(launch.call_count, int(result == 0))
                if not result:
                    self.assertEqual(launch.call_args.args[0], ['/usr/bin/flatpak', 'run', 'com.valvesoftware.Steam', '-silent'])

    def test_missing_client_or_launch_failure_is_harmless(self):
        with patch.object(startup, 'steam_running', return_value=False), patch.object(startup.shutil, 'which', return_value=None), patch.object(startup.subprocess, 'Popen') as launch:
            startup.ensure_steam()
            launch.assert_not_called()
        with patch.object(startup, 'steam_running', return_value=False), patch.object(startup.shutil, 'which', return_value='steam'), patch.object(startup.subprocess, 'Popen', side_effect=OSError):
            startup.ensure_steam()
