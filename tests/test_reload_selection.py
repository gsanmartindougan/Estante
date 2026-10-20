from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf


class ReloadSelectionTests(TestCase):
    def host(self, mode='list'):
        adjustment = Mock()
        adjustment.get_value.return_value = 400
        adjustment.get_upper.return_value = 1200
        adjustment.get_page_size.return_value = 300
        host = SimpleNamespace(
            library=Mock(), selected_game='selected', view_mode=mode,
            library_scroll=SimpleNamespace(get_vadjustment=lambda: adjustment),
            get_focus=lambda: None, drawer=Mock(), flow=object(),
            selected_tile=lambda: Mock(), focus_game=Mock(), rebuild_library=Mock())
        host.drawer.get_reveal_child.return_value = True
        return host, adjustment

    def test_rebuild_cannot_focus_first_game(self):
        for mode in ('grid', 'carousel', 'ps5', 'list'):
            host, _ = self.host(mode)
            def rebuild(games):
                self.assertTrue(host.reloading)
                Shelf.tile_focused(host, Mock(), {'id': 'first'})
            host.rebuild_library.side_effect = rebuild
            with patch('estante.GLib.timeout_add'):
                Shelf.reload(host)
            self.assertEqual(host.selected_game, 'selected')
            host.focus_game.assert_not_called()
            self.assertFalse(host.reloading)

    def test_editor_blocks_automatic_library_focus_after_reload(self):
        host, _ = self.host()
        Shelf.tile_focused(host, Mock(), {'id': 'first'})
        host.focus_game.assert_not_called()

    def test_grid_restores_scroll_but_does_not_override_new_selection(self):
        host, adjustment = self.host('grid')
        with patch('estante.GLib.timeout_add') as schedule:
            Shelf.reload(host)
        restore = schedule.call_args.args[1]
        restore()
        adjustment.set_value.assert_called_once_with(400)
        adjustment.set_value.reset_mock()
        host.selected_game = 'another'
        restore()
        adjustment.set_value.assert_not_called()

    def test_reload_guard_cleared_on_failure(self):
        host, _ = self.host()
        host.rebuild_library.side_effect = RuntimeError('test')
        with self.assertRaises(RuntimeError):
            Shelf.reload(host)
        self.assertFalse(host.reloading)
