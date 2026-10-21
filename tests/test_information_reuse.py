from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf
from carousel import CarouselWheel


class InformationReuseTests(TestCase):
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
