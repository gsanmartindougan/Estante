from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf, Graphene


class EditorNavigationTests(TestCase):
    def test_down_skips_sibling_and_targets_control_below(self):
        positions = [(900, 800), (1100, 800), (350, 900), (900, 900)]
        controls = []
        for x, y in positions:
            control = Mock()
            control.compute_bounds.return_value = (True, Graphene.Rect().init(x-50, y-15, 100, 30))
            controls.append(control)
        host = SimpleNamespace(sidebar=object())
        with patch('estante.SettingsView.controls', return_value=iter(controls)):
            Shelf.navigate_panel_direction(host, 'down', controls[0])
        controls[3].grab_focus.assert_called_once()
        controls[1].grab_focus.assert_not_called()
        for control in controls:
            control.reset_mock()
        with patch('estante.SettingsView.controls', return_value=iter(controls)):
            Shelf.navigate_panel_direction(host, 'right', controls[0])
        controls[1].grab_focus.assert_called_once()
