from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from estante import Shelf, Gdk
from settings_view import SettingsView


class SettingsSaveTests(unittest.TestCase):
    def test_saves_only_the_visible_section(self):
        sections = Mock()
        buttons = {key: Mock() for key in ('global', 'grid', 'carousel', 'ps5')}
        view = SimpleNamespace(sections=sections, save_buttons=buttons)
        for key in buttons:
            sections.get_visible_child_name.return_value = key
            SettingsView.save_current(view)
            buttons[key].emit.assert_called_once_with('clicked')
            buttons[key].reset_mock()
        sections.get_visible_child_name.return_value = 'categories'
        SettingsView.save_current(view)
        for button in buttons.values():
            button.emit.assert_not_called()

    def test_disabled_save_is_not_activated(self):
        button = Mock()
        button.get_sensitive.return_value = False
        view = SimpleNamespace(sections=Mock(), save_buttons={'global': button})
        view.sections.get_visible_child_name.return_value = 'global'
        SettingsView.save_current(view)
        button.emit.assert_not_called()

    def test_gamepad_save_works_without_a_focused_control(self):
        view = SimpleNamespace(save_current=Mock(return_value=True))
        self.assertTrue(SettingsView.navigate(view, 'save'))
        view.save_current.assert_called_once()

    def test_keyboard_save_is_available_in_text_fields(self):
        shelf = SimpleNamespace(pages=Mock(), preferences_view=Mock())
        shelf.pages.get_visible_child_name.return_value = 'settings'
        Shelf.key_pressed(shelf, None, Gdk.KEY_s, 0, Gdk.ModifierType.CONTROL_MASK)
        shelf.preferences_view.save_current.assert_called_once()

    def test_gamepad_save_does_nothing_outside_settings(self):
        shelf = SimpleNamespace(pages=Mock())
        shelf.pages.get_visible_child_name.return_value = 'library'
        self.assertTrue(Shelf.navigate(shelf, 'save'))
