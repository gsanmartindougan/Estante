from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf, LaunchSpinner, LaunchCoverTransition
from carousel import CarouselWheel


class InformationReuseTests(TestCase):
    def test_loader_animation_ticks_without_native_animation_setting(self):
        host = SimpleNamespace(tick=None, phase=0, add_tick_callback=Mock(return_value=7),
                               remove_tick_callback=Mock(), queue_draw=Mock(), advance=Mock())
        LaunchSpinner.start(host)
        LaunchSpinner.start(host)
        host.add_tick_callback.assert_called_once()
        self.assertTrue(LaunchSpinner.advance(host, None, Mock(get_frame_time=lambda: 1250000)))
        self.assertEqual(host.phase, .25)
        host.queue_draw.assert_called_once()
        LaunchSpinner.stop(host)
        host.remove_tick_callback.assert_called_once_with(7)

    def test_cover_transition_drops_texture_and_restores_target_on_completion(self):
        host = SimpleNamespace(progress=0, started=1000000, tick=4, texture=object(),
                               target=Mock(), queue_draw=Mock(), remove_tick_callback=Mock())
        host.clear = lambda: LaunchCoverTransition.clear(host)
        self.assertFalse(LaunchCoverTransition.advance(host, None, Mock(get_frame_time=lambda: 1500000)))
        self.assertIsNone(host.texture)
        self.assertIsNone(host.tick)
        host.target.set_opacity.assert_called_with(1)

    def test_switching_games_reuses_widgets_and_clears_optional_fields(self):
        stats = dict(seconds=60, sessions=1, last_seconds=30, last_played=None,
                     history=[dict(started='2026-10-20T12:00:00', seconds=30, exit_code=1)])
        host = SimpleNamespace(game_information=Mock(), library=Mock(), processes={})
        host.library.game_stats.return_value = stats
        host.information_widgets = lambda: Shelf.information_widgets(host)
        with ExitStack() as stack:
            constructors = [stack.enter_context(patch('estante.Gtk.' + name, side_effect=lambda *args, **kwargs: Mock()))
                            for name in ('Box', 'Label', 'FlowBox', 'LinkButton', 'Separator')]
            Shelf.update_game_information(host, dict(id='one', kind='faugus', runner='Proton', path='/game.exe',
                metadata={'description': 'Description', 'developers': ['Studio'],
                          'release_date': '2020-01-02', 'source': 'https://www.wikidata.org/wiki/Q1'}))
            widgets = host._information_widgets
            for factory in constructors:
                factory.reset_mock()
            host.library.game_stats.return_value = dict(stats, seconds=120, sessions=2, history=[])
            Shelf.update_game_information(host, dict(id='two', kind='local'))
            for factory in constructors:
                factory.assert_not_called()
            self.assertEqual(host.game_information.append.call_count, 2)
            widgets['description'].set_visible.assert_called_with(False)
            widgets['developers'].set_visible.assert_called_with(False)
            widgets['link'].set_visible.assert_called_with(False)
            widgets['runner'].set_visible.assert_called_with(False)
            widgets['path'].set_visible.assert_called_with(False)
            widgets['sessions'].set_text.assert_called_with('2')
            widgets['history'][0][0].set_visible.assert_called_with(False)

    def test_history_toggle_hides_history_without_hiding_statistics(self):
        stats = dict(seconds=60, sessions=1, last_seconds=30, last_played=None,
                     history=[dict(started='2026-10-20T12:00:00', seconds=30, exit_code=0)])
        host = SimpleNamespace(settings={'show_session_history': False}, view_mode='list',
                               library=Mock(), processes={}, information_timer=None)
        keys = ('status', 'seconds', 'last_seconds', 'sessions', 'last_played', 'note',
                'description', 'developers', 'publishers', 'genres', 'platforms', 'release',
                'missing', 'link', 'technical_separator', 'source', 'runner', 'path',
                'history_title', 'history_empty')
        widgets = {key: Mock() for key in keys}
        widgets['history'] = [(Mock(), Mock(), Mock(), Mock())]
        host.information_widgets = lambda: widgets
        host.library.game_stats.return_value = stats
        for enabled in (False, True):
            host.settings['show_session_history'] = enabled
            Shelf.update_game_information(host, dict(id='one', kind='local'))
            widgets['history_title'].set_visible.assert_called_with(enabled)
            widgets['history'][0][0].set_visible.assert_called_with(enabled)
            widgets['history_empty'].set_visible.assert_called_with(False)
            widgets['seconds'].set_visible.assert_called_with(True)

    def test_loader_retains_other_launches_and_ignores_stale_completion(self):
        first, second = object(), object()
        host = SimpleNamespace(pending_launches={'one': (first, {'id': 'one', 'title': 'One'}), 'two': (second, {'id': 'two', 'title': 'Two'})},
                               launch_spinner=Mock(), launch_loader=Mock(), launch_label=Mock(), show_launch_artwork=Mock())
        host.update_launch_loader = lambda: Shelf.update_launch_loader(host)
        Shelf.finish_launch_loader(host, 'one', object())
        self.assertEqual(len(host.pending_launches), 2)
        Shelf.finish_launch_loader(host, 'one', first)
        host.launch_spinner.start.assert_called_once()
        host.launch_loader.set_visible.assert_called_with(True)
        Shelf.finish_launch_loader(host, 'two', second)
        host.launch_spinner.stop.assert_called_once()
        host.launch_loader.set_visible.assert_called_with(False)

    def test_wheel_stops_tick_when_animation_finishes_and_restarts_once(self):
        rows = [object(), object(), object()]
        host = SimpleNamespace(children=lambda: rows, phase=0., destination=0., animation=None,
                               animation_tick=None, add_tick_callback=Mock(return_value=42),
                               layout_tick=Mock(), queue_allocate=Mock())
        with patch('carousel.GLib.get_monotonic_time', return_value=0):
            CarouselWheel.select(host, rows[0])
            host.add_tick_callback.assert_not_called()
            CarouselWheel.select(host, rows[1])
            CarouselWheel.select(host, rows[2])
            host.add_tick_callback.assert_called_once()
        with patch('carousel.GLib.get_monotonic_time', return_value=300000):
            self.assertFalse(CarouselWheel.layout_tick(host))
        self.assertIsNone(host.animation_tick)
        self.assertIsNone(host.animation)
        with patch('carousel.GLib.get_monotonic_time', return_value=400000):
            CarouselWheel.select(host, rows[0])
        self.assertEqual(host.add_tick_callback.call_count, 2)
