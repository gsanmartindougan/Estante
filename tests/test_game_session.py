from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from game_session import game_processes, wait_for_game
from estante import Shelf


class GameSessionTests(TestCase):
    def test_hidden_surface_is_released_only_when_hidden_and_realized(self):
        for visible, realized, expected in ((False, True, 1), (True, True, 0), (False, False, 0)):
            host = SimpleNamespace(get_visible=lambda: visible, get_realized=lambda: realized)
            with patch('estante.Gtk.Widget.unrealize') as unrealize:
                Shelf.release_hidden_surface(host)
            self.assertEqual(unrealize.call_count, expected)

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
                               get_application=Mock(return_value=Mock()), set_visible=Mock(), release_hidden_surface=Mock(),
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

    def test_loader_finishes_when_game_process_is_detected_without_checking_focus(self):
        for behavior in ('none', 'hide', 'screensaver', 'tray'):
            process = object()
            host = SimpleNamespace(session_window_closed=False, running_sessions={'game'},
                processes={'game': process}, is_active=Mock(side_effect=AssertionError('Unexpected focus check')),
                finish_launch_loader=Mock(), handoff_for_game=Mock(), apply_playing_behavior=Mock())
            self.assertFalse(Shelf.wait_to_hide_for_game(host, 'game', process, behavior))
            host.finish_launch_loader.assert_called_once_with('game', process)
            if behavior == 'hide':
                host.handoff_for_game.assert_called_once_with('game', process)
            elif behavior != 'none':
                host.apply_playing_behavior.assert_called_once_with('game', process, behavior)
            host.finish_launch_loader.reset_mock()
            host.running_sessions.clear()
            self.assertFalse(Shelf.wait_to_hide_for_game(host, 'game', process, behavior))
            host.finish_launch_loader.assert_not_called()
            host.is_active.assert_not_called()

    def test_faugus_ready_detection_requires_target_executable(self):
        with TemporaryDirectory() as root:
            for pid, command in ((1, b'faugus-launcher\0--game\0id\0'), (2, b'wine\0C:\\games\\Game.exe\0')):
                folder = Path(root) / str(pid)
                folder.mkdir()
                (folder / 'stat').write_text(f'{pid} (launcher) S 1 100 100 0')
                (folder / 'cmdline').write_bytes(command)
            self.assertEqual(game_processes({'kind': 'faugus', 'path': '/games/Game.exe'}, 100,
                                            root, ready_only=True), [2])

    def test_playing_behavior_preserves_legacy_setting(self):
        from game_session import playing_behavior
        self.assertEqual(playing_behavior({}), 'none')
        self.assertEqual(playing_behavior({'hide_while_playing': True}), 'hide')
        for mode in ('none', 'hide', 'screensaver', 'tray'):
            self.assertEqual(playing_behavior({'playing_behavior': mode, 'hide_while_playing': True}), mode)

    def test_tray_hides_only_after_registration_and_can_restore_during_game(self):
        process = object()
        host = SimpleNamespace(session_window_closed=False, running_sessions={'game'},
            processes={'game': process}, tray_sessions=set(), tray_icon=Mock(), hide_for_game=Mock(), error=Mock())
        Shelf.apply_playing_behavior(host, 'game', process, 'tray')
        host.hide_for_game.assert_not_called()
        ready = host.tray_icon.show.call_args.args[0]
        ready(True)
        host.hide_for_game.assert_called_once_with('game')
        host.hide_for_game.reset_mock()
        host.running_sessions.clear()
        ready(True)
        host.hide_for_game.assert_not_called()

    def test_missing_tray_never_hides_window(self):
        process = object()
        host = SimpleNamespace(session_window_closed=False, running_sessions={'game'},
            processes={'game': process}, tray_sessions=set(), tray_icon=Mock(), hide_for_game=Mock(), error=Mock())
        Shelf.apply_playing_behavior(host, 'game', process, 'tray')
        host.tray_icon.show.call_args.args[0](False)
        host.hide_for_game.assert_not_called()
        self.assertFalse(host.tray_sessions)
        host.error.assert_called_once()

    def test_playing_screensaver_starts_only_for_live_game(self):
        process = object()
        host = SimpleNamespace(session_window_closed=False, running_sessions={'game'},
            processes={'game': process}, screensaver=Mock(), error=Mock())
        Shelf.apply_playing_behavior(host, 'game', process, 'screensaver')
        host.screensaver.game_started.assert_called_once_with('game')
        host.screensaver.reset_mock()
        host.running_sessions.clear()
        Shelf.apply_playing_behavior(host, 'game', process, 'screensaver')
        host.screensaver.game_started.assert_not_called()

    def test_play_records_timestamp_and_tracks_real_game_for_every_mode(self):
        game = {'id': 'game', 'title': 'Game', 'kind': 'steam', 'steam_appid': '10'}
        for mode in ('none', 'hide', 'screensaver', 'tray'):
            process = Mock()
            host = Mock(settings={'playing_behavior': mode}, processes={}, running_sessions=set(), pending_launches={}, selected_game='game')
            host.library.root = Path('/tmp/library')
            host.library.games.return_value = [game]
            with patch('estante.launch', return_value=process), patch('estante.Adw.Toast'):
                Shelf.play(host, game)
            worker, finished, failed = host.background.call_args.args
            with patch('estante.wait_for_game', return_value=0) as wait:
                self.assertEqual(worker(), 0)
                self.assertEqual(wait.call_args.args, (game, process))
                self.assertTrue(callable(wait.call_args.kwargs['on_started']))
                with patch('estante.GLib.idle_add') as idle:
                    wait.call_args.kwargs['on_started']()
                self.assertEqual(idle.call_args_list[0].args, (host.wait_to_hide_for_game, 'game', process, mode))
            finished(0)
            self.assertIsInstance(host.library.record_session.call_args.args[2], str)
            self.assertNotIn('game', host.running_sessions)
            host.restore_after_game.assert_called_once_with('game')

    def test_last_tray_game_releases_icon_and_application_hold(self):
        host = SimpleNamespace(hidden_game_sessions={'one', 'two'}, tray_sessions={'one', 'two'},
            game_window_hold=True, session_window_closed=False, tray_icon=Mock(), screensaver=Mock(),
            get_application=Mock(return_value=Mock()), present=Mock(), focus_library=Mock())
        Shelf.restore_after_game(host, 'one')
        host.tray_icon.hide.assert_not_called()
        host.present.assert_not_called()
        Shelf.restore_after_game(host, 'two')
        host.tray_icon.hide.assert_called_once()
        host.present.assert_called_once()
        host.get_application().release.assert_called_once()
        self.assertFalse(host.game_window_hold)

    def test_session_token_follows_detached_game_and_requires_exact_identity(self):
        with TemporaryDirectory() as root:
            for pid, token in ((200, 'ours'), (201, 'ours-extra')):
                folder = Path(root) / str(pid)
                folder.mkdir()
                (folder / 'stat').write_text(f'{pid} (extracted runtime) S 1 {pid} {pid} 0')
                (folder / 'environ').write_bytes(('ESTANTE_GAME_SESSION=' + token + '\0').encode())
                (folder / 'cmdline').write_bytes(b'/tmp/.mount_game/runtime\0game.elf\0')
            game = {'kind': 'faugus', 'path': '/games/Bloodborne.AppImage'}
            self.assertEqual(game_processes(game, 100, root, session_token='ours'), [200])
            self.assertEqual(game_processes(game, 100, root, session_token='ours', ready_only=True), [200])
            self.assertEqual(game_processes(game, 100, root, session_token='different'), [])

    def test_real_faugus_style_setsid_child_fires_start_and_waits_for_exit(self):
        import sys
        from library import launch
        with TemporaryDirectory() as root:
            script = Path(root) / 'fake_faugus.py'
            script.write_text('import subprocess, sys; child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.35)"], start_new_session=True); child.wait()')
            game = {'kind': 'faugus', 'path': '/games/Example.AppImage'}
            with patch('library.launch_command', return_value=([sys.executable, str(script)], None)):
                process = launch(game, root)
            started = Mock()
            try:
                self.assertEqual(wait_for_game(game, process, interval=.02, on_started=started), 0)
                started.assert_called_once()
                self.assertIsInstance(process.estante_session_token, str)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)

    def test_restore_after_game_honors_fullscreen_preference(self):
        for fullscreen in (False, True):
            host = SimpleNamespace(settings={'start_fullscreen': fullscreen},
                hidden_game_sessions={'game'}, game_window_hold=True, session_window_closed=False,
                get_application=Mock(return_value=Mock()), present=Mock(), fullscreen=Mock(), focus_library=Mock())
            order = Mock()
            order.attach_mock(host.fullscreen, 'fullscreen')
            order.attach_mock(host.present, 'present')
            Shelf.restore_after_game(host, 'game')
            self.assertEqual(host.fullscreen.call_count, int(fullscreen))
            host.present.assert_called_once()
            if fullscreen:
                self.assertEqual([call[0] for call in order.mock_calls], ['fullscreen', 'present'])
            host.get_application().release.assert_called_once()

    def test_tray_restore_honors_fullscreen_without_reopening_closed_window(self):
        for closed in (False, True):
            host = SimpleNamespace(settings={'start_fullscreen': True}, session_window_closed=closed,
                present=Mock(), fullscreen=Mock(), focus_library=Mock())
            Shelf.restore_from_tray(host)
            self.assertEqual(host.fullscreen.call_count, int(not closed))
            self.assertEqual(host.present.call_count, int(not closed))
