from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from estante import Shelf


class EmptyLibraryTests(TestCase):
    def host(self, total):
        children = [Mock(game={'id': str(index)}) for index in range(total)]
        for index, child in enumerate(children):
            child.get_next_sibling.return_value = children[index+1] if index+1 < total else None
        return SimpleNamespace(view_mode='list', flow=SimpleNamespace(get_first_child=lambda: children[0] if children else None),
            matches_game=lambda game: False, tiles=lambda: [], count=Mock(),
            empty=Mock(), empty_scan=Mock(), empty_add=Mock(), empty_clear=Mock(),
            stack=Mock(), ps5_selector=Mock(), settings={}, selected_game=None, update_image_window=Mock(), schedule_image_window=Mock(), update_alphabet=Mock())

    def test_empty_library_offers_scan_and_local_game(self):
        host = self.host(0)
        Shelf.filter(host)
        host.empty_scan.set_visible.assert_called_once_with(True)
        host.empty_add.set_visible.assert_called_once_with(True)
        host.empty_clear.set_visible.assert_called_once_with(False)
        host.stack.set_visible_child_name.assert_called_once_with('empty')

    def test_no_search_or_category_matches_does_not_offer_import(self):
        host = self.host(3)
        Shelf.filter(host)
        host.empty_scan.set_visible.assert_called_once_with(False)
        host.empty_add.set_visible.assert_called_once_with(False)
        host.empty_clear.set_visible.assert_called_once_with(True)

    def test_clearing_filters_restores_all_games(self):
        host = SimpleNamespace(active_category='Steam', search=Mock(), update_categories=Mock(),
                               filter=Mock(), focus_library=Mock())
        Shelf.clear_library_filters(host)
        self.assertIsNone(host.active_category)
        host.search.set_text.assert_called_once_with('')
        host.filter.assert_called_once()
        host.focus_library.assert_called_once()
