from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from estante import Shelf


class ListNavigationTests(TestCase):
    def shelf(self, count=3):
        tiles = [object() for _ in range(count)]
        shelf = SimpleNamespace(
            view_mode='list', settings={}, empty_actions=Mock(),
            stack=SimpleNamespace(get_visible_child_name=lambda: 'games' if count else 'empty'),
            pages=SimpleNamespace(get_visible_child_name=lambda: 'library'),
            drawer=SimpleNamespace(get_reveal_child=lambda: False),
            get_focus=lambda: None, tiles=lambda: tiles,
            selected_tile=lambda: tiles[0] if tiles else None, select_tile=Mock(),
            game_actions=SimpleNamespace(get_first_child=lambda: SimpleNamespace(grab_focus=Mock())))
        return shelf, tiles

    def test_up_wraps_to_last_and_down_selects_next(self):
        shelf, tiles = self.shelf()
        self.assertTrue(Shelf.navigate(shelf, 'up'))
        shelf.select_tile.assert_called_with(tiles[-1])
        self.assertTrue(Shelf.navigate(shelf, 'down'))
        shelf.select_tile.assert_called_with(tiles[1])

    def test_one_game_does_not_create_duplicates(self):
        shelf, tiles = self.shelf(1)
        Shelf.navigate(shelf, 'down')
        shelf.select_tile.assert_called_once_with(tiles[0])

    def test_empty_list_is_safe(self):
        shelf, _ = self.shelf(0)
        self.assertTrue(Shelf.navigate(shelf, 'down'))
        shelf.empty_actions.child_focus.assert_called_once()

    def test_detail_cover_uses_selected_format_and_matching_asset(self):
        for format_name, path, width, height, square in (
                ('portrait', '/portrait.png', 180, 270, False),
                ('square', '/square.png', 220, 220, True)):
            cover = Mock()
            host = SimpleNamespace(
                settings={'cover_formats': {'list': format_name}},
                list_cover=SimpleNamespace(get_first_child=lambda: None, append=Mock()),
                cover=cover)
            game = {'id': 'test', 'cover': '/portrait.png', 'square_cover': '/square.png'}
            Shelf.update_list_cover(host, game)
            cover.assert_called_once_with({'cover': path}, width, height, square=square, priority=0)
            host.list_cover.append.assert_called_once_with(cover.return_value)
