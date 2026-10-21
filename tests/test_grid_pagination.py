from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from appearance import grid_page
from estante import Shelf


class GridPaginationTests(TestCase):
    def test_large_library_has_bounded_page_and_keeps_selection(self):
        games = [{'id': str(i)} for i in range(10000)]
        for selected in ('0', '11', '12', '9999', 'removed'):
            rows, page, pages = grid_page(games, selected)
            self.assertLessEqual(len(rows), 12)
            self.assertEqual(pages, 834)
            if selected != 'removed':
                self.assertIn(selected, [game['id'] for game in rows])
        self.assertEqual(grid_page([]), ([], 0, 1))

    def test_filtered_games_not_global_offsets_determine_page(self):
        games = [{'id': str(i)} for i in range(1000) if i % 2 == 0]
        rows, page, pages = grid_page(games, '48')
        self.assertEqual(page, 2)
        self.assertEqual(rows[0]['id'], '48')
        self.assertEqual(pages, 42)

    def test_page_turn_uses_all_filtered_games_and_stays_at_boundaries(self):
        games = [{'id': str(i)} for i in range(25)]
        host = SimpleNamespace(view_mode='grid', library_games=games, selected_game='0',
                matches_game=lambda game: True, reload=Mock(), focus_library=Mock(),
                library_scroll=Mock(), reload_revision=1)
        with patch('estante.GLib.timeout_add'):
            self.assertFalse(Shelf.change_grid_page(host, -1))
            self.assertTrue(Shelf.change_grid_page(host, 1))
            self.assertEqual(host.selected_game, '12')
            self.assertTrue(Shelf.change_grid_page(host, 1))
            self.assertEqual(host.selected_game, '24')
            self.assertFalse(Shelf.change_grid_page(host, 1))
            self.assertTrue(Shelf.change_grid_page(host, -1))
            self.assertEqual(host.selected_game, '23')
        self.assertEqual(host.reload.call_count, 3)
