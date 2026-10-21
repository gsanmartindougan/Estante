from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from image_cache import nearby_indices
from estante import Shelf


class ImageWindowTests(TestCase):
    def test_window_has_at_most_three_unique_games(self):
        for count in (0, 1, 2, 3, 7, 13, 1000):
            for index in range(count):
                for wrap in (False, True):
                    result = nearby_indices(count, index, wrap=wrap)
                    self.assertLessEqual(len(result), 3)
                    self.assertTrue(all(0 <= value < count for value in result))
                    self.assertIn(index, result)
        self.assertEqual(nearby_indices(13, 0), {0, 1})
        self.assertEqual(nearby_indices(13, 0, wrap=True), {12, 0, 1})

    def test_navigation_releases_old_images_and_loads_only_new_neighbour(self):
        rows = [SimpleNamespace(game={'id': str(i), 'logo': f'{i}.png'}, image_loaded=False,
                                button=Mock()) for i in range(13)]
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i + 1] if i + 1 < len(rows) else None
        host = SimpleNamespace(tiles=lambda: rows, selected_game='6', view_mode='list', settings={},
                               flow=SimpleNamespace(get_first_child=lambda: rows[0]),
                               logo_image=Mock(), cover=Mock())
        with patch('estante.release_images') as release, patch('estante.Gtk.Box'), \
             patch('estante.images.retain_paths') as retain:
            Shelf.update_image_window(host)
            self.assertEqual(host.logo_image.call_count, 3)
            self.assertEqual(sum(row.image_loaded for row in rows), 3)
            host.logo_image.reset_mock()
            release.reset_mock()
            host.selected_game = '7'
            Shelf.update_image_window(host)
            self.assertEqual(host.logo_image.call_count, 1)
            self.assertFalse(rows[5].image_loaded)
            self.assertTrue(rows[8].image_loaded)
            self.assertEqual(sum(row.image_loaded for row in rows), 3)
            self.assertNotIn('5.png', retain.call_args.args[0])
            self.assertEqual(release.call_count, 2)

    def test_sense_loads_only_visible_covers_and_releases_distant_covers(self):
        rows = [SimpleNamespace(game={'id': str(i), 'square_cover': f'{i}.png'},
                image_loaded=False, button=Mock(), set_opacity=Mock(),
                get_allocation=lambda i=i: SimpleNamespace(x=i*120, y=0, width=104, height=104))
                for i in range(30)]
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i+1] if i+1 < len(rows) else None
        adjustment = Mock()
        adjustment.get_value.return_value = 0
        adjustment.get_page_size.return_value = 1200
        host = SimpleNamespace(tiles=lambda: rows, selected_game='0', view_mode='ps5', settings={},
               flow=SimpleNamespace(get_first_child=lambda: rows[0], get_margin_start=lambda: 0),
               library_scroll=SimpleNamespace(get_hadjustment=lambda: adjustment), cover=Mock())
        with patch('estante.release_images'), patch('estante.Gtk.Box'), patch('estante.images.retain_paths'):
            Shelf.update_image_window(host)
            self.assertTrue(all(row.image_loaded for row in rows[:10]))
            self.assertFalse(rows[10].image_loaded)
            adjustment.get_value.return_value = 2400
            host.selected_game = '20'
            Shelf.update_image_window(host)
            self.assertFalse(rows[0].image_loaded)
            self.assertTrue(all(row.image_loaded for row in rows[20:]))
