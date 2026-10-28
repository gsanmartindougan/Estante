from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf, Gtk


class IncrementalLibraryTests(TestCase):
    def host(self, mode):
        old = {'id': 'one', 'title': 'One', 'cover': 'old', 'square_cover': 'old', 'logo': 'old'}
        tile = SimpleNamespace(game=old, button=Mock(), image_loaded=True)
        host = SimpleNamespace(view_mode=mode, settings={}, category_names=[],
            library=Mock(), search=SimpleNamespace(get_text=lambda: ''), active_category=None,
            grid_filter_signature=('', None), selected_game='one', matches_game=lambda _: True,
            tiles=lambda: [tile], selected_tile=lambda: tile,
            focus_game=Mock(), update_image_window=Mock())
        host.library.categories.return_value = []
        host._render_signature = (mode, repr(host.settings))
        return host, tile, old

    def test_metadata_refresh_preserves_tiles_and_dictionary_used_by_handlers(self):
        for mode in ('grid', 'list', 'carousel', 'ps5'):
            host, tile, original = self.host(mode)
            game = {**original, 'metadata': {'synopsis': 'New text'}}
            self.assertTrue(Shelf.refresh_library(host, [game]))
            self.assertIs(tile.game, original)
            self.assertEqual(original['metadata']['synopsis'], 'New text')
            self.assertTrue(tile.image_loaded)
            host.focus_game.assert_called_once_with(original)

    def test_changed_artwork_marks_only_affected_texture_for_reload(self):
        for mode, field in (('grid', 'cover'), ('carousel', 'cover'), ('ps5', 'square_cover'), ('list', 'logo')):
            host, tile, original = self.host(mode)
            # The default Sense format is square.
            host.settings = {'cover_formats': {mode: 'square' if mode == 'ps5' else 'portrait'}}
            host._render_signature = (mode, repr(host.settings))
            self.assertTrue(Shelf.refresh_library(host, [{**original, field: 'new'}]))
            self.assertFalse(tile.image_loaded)

    def test_structure_filter_category_or_settings_change_requires_rebuild(self):
        host, tile, old = self.host('list')
        self.assertFalse(Shelf.refresh_library(host, [{**old, 'id': 'other'}]))
        self.assertIs(tile.game, old)
        host.settings['list_focus_zoom'] = 200
        self.assertFalse(Shelf.refresh_library(host, [old]))
        host._render_signature = ('list', repr(host.settings))
        host.library.categories.return_value = ['new']
        self.assertFalse(Shelf.refresh_library(host, [old]))

    def test_unchanged_list_presentation_skips_reloading_widget(self):
        host = SimpleNamespace(view_mode='list', settings={}, get_scale_factor=lambda: 1,
            list_cover=SimpleNamespace(get_first_child=lambda: None, append=Mock()), cover=Mock())
        game = {'cover': 'cover.png'}
        Shelf.update_list_cover(host, game)
        Shelf.update_list_cover(host, game)
        host.cover.assert_called_once()
