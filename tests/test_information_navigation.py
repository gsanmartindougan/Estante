from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from estante import Shelf


class InformationNavigationTests(TestCase):
    def host(self, value=0):
        adjustment = SimpleNamespace(value=value, get_upper=lambda: 1400, get_page_size=lambda: 400)
        adjustment.get_value = lambda: adjustment.value
        adjustment.set_value = lambda value: setattr(adjustment, 'value', value)
        scroll = SimpleNamespace(get_vadjustment=lambda: adjustment, grab_focus=Mock())
        play = Mock()
        host = SimpleNamespace(info_scroll=scroll, game_information=Mock(),
                               game_actions=SimpleNamespace(get_first_child=lambda: play),
                               focus_library=Mock())
        return host, adjustment, play

    def test_reading_scrolls_in_both_directions_and_clamps(self):
        host, adjustment, _ = self.host()
        Shelf.navigate_information(host, 'down', host.info_scroll)
        self.assertEqual(adjustment.value, 80)
        Shelf.navigate_information(host, 'up', host.info_scroll)
        self.assertEqual(adjustment.value, 0)
        adjustment.value = 990
        Shelf.navigate_information(host, 'down', host.info_scroll)
        self.assertEqual(adjustment.value, 1000)

    def test_up_at_start_returns_to_play_and_left_returns_to_library(self):
        host, _, play = self.host()
        Shelf.navigate_information(host, 'up', host.info_scroll)
        play.grab_focus.assert_called_once()
        Shelf.navigate_information(host, 'left', host.info_scroll)
        host.focus_library.assert_called_once()

    def test_actions_can_be_focused_activated_and_left_for_reading(self):
        host, _, _ = self.host()
        Shelf.navigate_information(host, 'confirm', host.info_scroll)
        host.game_information.child_focus.assert_called_once()
        action = Mock()
        Shelf.navigate_information(host, 'confirm', action)
        action.activate.assert_called_once()
        Shelf.navigate_information(host, 'left', action)
        host.info_scroll.grab_focus.assert_called_once()
