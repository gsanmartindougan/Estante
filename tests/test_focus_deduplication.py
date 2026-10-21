from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf


class FocusDeduplicationTests(TestCase):
    def test_focus_event_and_explicit_selection_do_not_process_game_twice(self):
        for emits in (True, False):
            game = {'id': 'new'}
            host = SimpleNamespace(active_tile=None, selected_game='old', view_mode='list', center_tile=Mock())
            def apply(game):
                host.selected_game = game['id']
            host.focus_game = Mock(side_effect=apply)
            tile = SimpleNamespace(game=game, button=Mock())
            if emits:
                tile.button.grab_focus.side_effect = lambda: host.focus_game(game)
            with patch('estante.GLib.idle_add'):
                Shelf.select_tile(host, tile)
            host.focus_game.assert_called_once_with(game)
