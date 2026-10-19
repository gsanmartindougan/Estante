import unittest
from i18n import set_language, get_language
from types import SimpleNamespace
from unittest.mock import Mock, patch

from estante import Shelf


class CategoryTests(unittest.TestCase):
    def setUp(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        set_language('es')

    def test_two_game_carousel_wraps_both_directions(self):
        tiles = [Mock(), Mock()]
        shelf = Mock(view_mode='carousel', gamepad_cursor_hidden=True, tiles=lambda: tiles,
                     selected_tile=lambda: tiles[1])
        shelf.pages.get_visible_child_name.return_value = 'library'
        shelf.drawer.get_reveal_child.return_value = False
        shelf.get_focus.return_value = None
        Shelf.navigate(shelf, 'right')
        shelf.select_tile.assert_called_with(tiles[0])
        shelf.selected_tile = lambda: tiles[0]
        Shelf.navigate(shelf, 'left')
        shelf.select_tile.assert_called_with(tiles[1])

    def test_category_and_search_intersect(self):
        shelf = SimpleNamespace(search=Mock(), active_category='Favoritos')
        shelf.search.get_text.return_value = 'dark'
        self.assertTrue(Shelf.matches_game(shelf, {'title': 'Dark Souls', 'categories': ['Favoritos']}))
        self.assertFalse(Shelf.matches_game(shelf, {'title': 'Dark Souls'}))
        self.assertFalse(Shelf.matches_game(shelf, {'title': 'Bloodborne', 'categories': ['Favoritos']}))
        shelf.active_category = None
        self.assertTrue(Shelf.matches_game(shelf, {'title': 'Dark Souls'}))

    def test_triggers_cycle_and_wrap_in_all_appearances(self):
        for mode in ('grid', 'carousel', 'ps5'):
            shelf = SimpleNamespace(view_mode=mode, category_names=['Favoritos', 'Pendientes'],
                                    active_category=None, update_categories=Mock(), filter=Mock(),
                                    pages=Mock(), drawer=Mock(), tiles=lambda: [])
            shelf.change_category = lambda step: Shelf.change_category(shelf, step)
            shelf.pages.get_visible_child_name.return_value = 'library'
            shelf.drawer.get_reveal_child.return_value = False
            Shelf.navigate(shelf, 'category_previous')
            self.assertEqual(shelf.active_category, 'Pendientes')
            Shelf.navigate(shelf, 'category_next')
            self.assertIsNone(shelf.active_category)
            shelf.drawer.get_reveal_child.return_value = True
            shelf.filter.reset_mock()
            Shelf.navigate(shelf, 'category_next')
            shelf.filter.assert_not_called()

    def test_category_strip_shows_neighbors_and_current(self):
        shelf = SimpleNamespace(category_names=['Favoritos', 'Pendientes'], active_category='Favoritos',
                                category_labels=[Mock(), Mock(), Mock()])
        Shelf.update_categories(shelf)
        for label, text in zip(shelf.category_labels, ['Todos', 'Favoritos', 'Pendientes']):
            label.set_text.assert_called_with(text)
        shelf.category_names = []
        shelf.active_category = None
        Shelf.update_categories(shelf)
        for label, text in zip(shelf.category_labels, ['', 'Todos', '']):
            label.set_text.assert_called_with(text)
