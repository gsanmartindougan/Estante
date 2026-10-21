from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from game_session import game_processes, wait_for_game
from estante import Shelf


class GameSessionTests(TestCase):
    def test_steam_waits_for_game_after_launcher_exits(self):
        process = Mock(pid=100)
        process.poll.return_value = 0
        with patch('game_session.game_processes', side_effect=[[], [200], [200], []]), \
             patch('game_session.time.sleep'):
            self.assertEqual(wait_for_game({'kind': 'steam', 'steam_appid': '10'}, process), 0)
        process.wait.assert_not_called()

    def test_child_outliving_script_keeps_session_open(self):
        process = Mock(pid=100)
        process.wait.return_value = 0
        with patch('game_session.game_processes', side_effect=[[200], []]), patch('game_session.time.sleep') as sleep:
            self.assertEqual(wait_for_game({'kind': 'local'}, process), 0)
        sleep.assert_called_once()

    def test_undetected_steam_game_has_bounded_startup_wait(self):
        process = Mock(pid=100)
        process.poll.return_value = 0
        with patch('game_session.game_processes', return_value=[]), \
             patch('game_session.time.monotonic', side_effect=[0, 91]), patch('game_session.time.sleep'):
            with self.assertRaises(RuntimeError):
                wait_for_game({'kind': 'steam', 'steam_appid': '10'}, process)

    def test_detection_uses_exact_steam_identity_and_skips_zombies(self):
        with TemporaryDirectory() as root:
            for pid, identity, state in ((1, '10', 'S'), (2, '100', 'S'), (3, '10', 'Z')):
                folder = Path(root) / str(pid)
                folder.mkdir()
                (folder / 'stat').write_text(f'{pid} (game with spaces) {state} 1 100 100 0')
                (folder / 'environ').write_bytes(f'SteamAppId={identity}\0'.encode())
            self.assertEqual(game_processes({'kind': 'steam', 'steam_appid': '10'}, 100, root), [1])

    def test_restore_waits_for_last_hidden_game_and_balances_application_hold(self):
        host = SimpleNamespace(hidden_game_sessions=set(), game_window_hold=False, session_window_closed=False,
                               get_application=Mock(return_value=Mock()), set_visible=Mock(),
                               present=Mock(), focus_library=Mock())
        Shelf.hide_for_game(host, 'one')
        Shelf.hide_for_game(host, 'two')
        host.get_application().hold.assert_called_once()
        Shelf.restore_after_game(host, 'one')
        host.present.assert_not_called()
        Shelf.restore_after_game(host, 'two')
        host.present.assert_called_once()
        host.focus_library.assert_called_once()
        host.get_application().release.assert_called_once()

    def test_started_callback_waits_for_steam_game_not_just_launcher(self):
        process = Mock(pid=100)
        process.poll.return_value = 0
        started = Mock()
        with patch('game_session.game_processes', side_effect=[[], [200], [200], []]), \
             patch('game_session.time.sleep'):
            wait_for_game({'kind': 'steam', 'steam_appid': '10'}, process, on_started=started)
        started.assert_called_once()

    def test_hide_waits_for_focus_transfer_and_stops_if_game_finishes(self):
        process = object()
        host = SimpleNamespace(session_window_closed=False, running_sessions={'game'},
            processes={'game': process}, is_active=Mock(return_value=True), hide_for_game=Mock())
        with patch('estante.GLib.timeout_add') as timer:
            Shelf.wait_to_hide_for_game(host, 'game', process)
        check = timer.call_args.args[1]
        self.assertTrue(check())
        host.hide_for_game.assert_not_called()
        host.is_active.return_value = False
        self.assertFalse(check())
        host.hide_for_game.assert_called_once_with('game')
        host.hide_for_game.reset_mock()
        host.running_sessions.clear()
        self.assertFalse(check())
        host.hide_for_game.assert_not_called()

    def test_faugus_ready_detection_requires_target_executable(self):
        with TemporaryDirectory() as root:
            for pid, command in ((1, b'faugus-launcher\0--game\0id\0'), (2, b'wine\0C:\\games\\Game.exe\0')):
                folder = Path(root) / str(pid)
                folder.mkdir()
                (folder / 'stat').write_text(f'{pid} (launcher) S 1 100 100 0')
                (folder / 'cmdline').write_bytes(command)
            self.assertEqual(game_processes({'kind': 'faugus', 'path': '/games/Game.exe'}, 100,
                                            root, ready_only=True), [2])
