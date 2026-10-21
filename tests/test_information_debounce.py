from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf


class InformationDebounceTests(TestCase):
    def test_first_information_is_immediate(self):
        host = SimpleNamespace(update_game_information=Mock())
        with patch('estante.GLib.timeout_add') as timer:
            Shelf.schedule_game_information(host, {'id': 'first'})
        host.update_game_information.assert_called_once_with({'id': 'first'})
        timer.assert_not_called()

    def test_rapid_navigation_updates_only_final_game(self):
        host = SimpleNamespace(_information_widgets={}, selected_game='first', update_game_information=Mock())
        with patch('estante.GLib.timeout_add', side_effect=[1, 2]) as timer, patch('estante.GLib.source_remove') as remove:
            Shelf.schedule_game_information(host, {'id': 'first'})
            obsolete = timer.call_args.args[1]
            host.selected_game = 'last'
            Shelf.schedule_game_information(host, {'id': 'last'})
            latest = timer.call_args.args[1]
            remove.assert_called_once_with(1)
            self.assertEqual(timer.call_args.args[0], 120)
            obsolete()
            host.update_game_information.assert_not_called()
            latest()
            host.update_game_information.assert_called_once_with({'id': 'last'})
