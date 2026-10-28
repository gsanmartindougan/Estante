from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from estante import Shelf
from carousel import wheel_position, list_position, VirtualStrip
from gi.repository import Gtk


class PresentationWindowTests(TestCase):
    def test_wheels_keep_five_unique_games_and_wrap_full_catalogue(self):
        for count in (1, 2, 3, 13, 100, 1000):
            games = [{'id': str(i)} for i in range(count)]
            for mode in ('list', 'carousel'):
                host = SimpleNamespace(view_mode=mode)
                for selected in (0, count // 2, count - 1):
                    rows = Shelf.game_window(host, games, str(selected))
                    identities = {row['id'] for row in rows}
                    self.assertEqual(len(rows), min(count, 5))
                    self.assertIn(str(selected), identities)
                    self.assertIn(str((selected + 1) % count), identities)
                    self.assertIn(str((selected - 1) % count), identities)

    def test_large_catalogues_keep_the_same_wheel_spacing(self):
        for index in (-1, 0, 1):
            self.assertEqual(wheel_position(index, 0, 100, 1600),
                             wheel_position(index, 0, 1000, 1600))
            self.assertEqual(list_position(index, 0, 100, 800, 100),
                             list_position(index, 0, 1000, 800, 100))
        self.assertGreater(wheel_position(1, 0, 100, 1600)[0], 400)

    def test_sense_mouse_scroll_loads_viewport_and_keeps_selection(self):
        games = [{'id': str(i)} for i in range(1000)]
        host = SimpleNamespace(view_mode='ps5', settings={}, get_width=lambda: 1200,
            flow=SimpleNamespace(get_margin_start=lambda: 0),
            library_scroll=SimpleNamespace(get_hadjustment=lambda: SimpleNamespace(
                get_value=lambda: 500 * 128, get_page_size=lambda: 1200)))
        rows = Shelf.game_window(host, games, '0', from_viewport=True)
        identities = {row['id'] for row in rows}
        self.assertIn('0', identities)
        self.assertIn('500', identities)
        self.assertIn('509', identities)
        self.assertNotIn('400', identities)
        self.assertLess(len(rows), 15)

    def test_virtual_strip_scroll_extent_depends_on_model_not_widget_count(self):
        host = SimpleNamespace(model_count=1000, stride=128, spacing=12, item_height=116)
        self.assertEqual(VirtualStrip.do_measure(host, Gtk.Orientation.HORIZONTAL, -1)[:2],
                         (127988, 127988))
        self.assertEqual(VirtualStrip.do_measure(host, Gtk.Orientation.VERTICAL, -1)[:2], (116, 116))

    def test_sense_zoom_reserves_extra_width_only_after_selected_card(self):
        host = SimpleNamespace(model_count=100, stride=128, spacing=12, item_height=116,
                               focus_extra=108, focus_index=37)
        self.assertEqual(VirtualStrip.position(host, 37), 37 * 128)
        self.assertEqual(VirtualStrip.position(host, 38), 38 * 128 + 108)
        self.assertEqual(VirtualStrip.do_measure(host, Gtk.Orientation.HORIZONTAL, -1)[0], 12896)
