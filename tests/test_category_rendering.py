from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf


class CategoryRenderingTests(TestCase):
    def test_all_modes_create_cards_only_for_matching_category(self):
        games = [{'id': 'shown', 'title': 'Shown'}, {'id': 'other', 'title': 'Other'}]
        for mode in ('grid', 'list', 'carousel', 'ps5'):
            containers = [Mock() for _ in range(4)]
            for container in containers:
                container.get_first_child.return_value = None
            host = SimpleNamespace(library=Mock(), category_names=['Active'], active_category='Active',
                                   update_categories=Mock(), grid_flow=containers[0], horizontal_flow=containers[1],
                                   carousel_flow=containers[2], list_flow=containers[3], flow=containers[0],
                                   square_queue=[], search=Mock(), grid_pager=Mock(), view_mode=mode,
                                   settings={}, selected_game='shown', matches_game=lambda game: game['id'] == 'shown',
                                   filter=Mock(), load_square_covers=Mock(), tiles=lambda: [], focus_revision=0,
                                   background_tickets=[], list_cover=Mock(), backdrop=Mock(), backdrop_fill=Mock(),
                                   grid_page_label=Mock(), grid_previous=Mock(), grid_next=Mock())
            from types import MethodType
            for name in ('create_game_tile', 'game_window', 'sync_game_window', '_sync_game_window'):
                setattr(host, name, MethodType(getattr(Shelf, name), host))
            host.get_width = lambda: 1200
            host.library_scroll = SimpleNamespace(get_hadjustment=lambda: SimpleNamespace(get_page_size=lambda: 1200))
            host.update_strip_geometry = Mock()
            host.library.categories.return_value = ['Active']
            host.search.get_text.return_value = ''
            with ExitStack() as stack:
                for name in ('Box', 'Button', 'EventControllerFocus', 'GestureClick', 'FlowBoxChild'):
                    stack.enter_context(patch('estante.Gtk.' + name, side_effect=lambda *a, **kw: Mock()))
                stack.enter_context(patch('estante.GameTile', side_effect=lambda *a, **kw: Mock()))
                stack.enter_context(patch('estante.release_images'))
                Shelf.rebuild_library(host, games)
            host.flow.append.assert_called_once()
            self.assertEqual(host.flow.append.call_args.args[0].game['id'], 'shown')

    def test_category_changes_rebuild_filtered_cards_for_every_mode(self):
        for mode in ('grid', 'list', 'carousel', 'ps5'):
            host = SimpleNamespace(view_mode=mode, library_games=[], search=Mock(), active_category='New',
                                   grid_filter_signature=('', 'Old'), reload=Mock())
            host.search.get_text.return_value = ''
            Shelf.filter(host)
            host.reload.assert_called_once()

    def test_minimal_mode_never_builds_invisible_information(self):
        host = SimpleNamespace(settings={'minimal_views': {'list': True}}, view_mode='list',
                               information_timer=None, update_game_information=Mock())
        Shelf.schedule_game_information(host, {'id': 'shown'})
        host.update_game_information.assert_not_called()
