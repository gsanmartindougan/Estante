from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from settings_view import dropdown_input, Gtk
from estante import Shelf, Gdk


class DropdownInputTests(TestCase):
    def test_confirm_opens_native_popup_without_rotating_value(self):
        owner = Mock()
        popup = Mock()
        popup.get_visible.return_value = False
        with patch('settings_view.descendant', return_value=popup):
            self.assertTrue(dropdown_input(owner, 'confirm'))
        owner.emit.assert_called_once_with('activate')
        owner.set_selected.assert_not_called()

    def test_popup_navigates_real_selection_model_and_confirms_selected_row(self):
        model = Gtk.SingleSelection.new(Gtk.StringList.new(['Open', 'Hide', 'Saver', 'Tray']))
        model.set_selected(1)
        listing = Mock()
        listing.get_model.return_value = model
        popup, owner = Mock(), Mock()
        popup.get_visible.return_value = True
        for action, expected in (('down', 2), ('down', 3), ('down', 3), ('up', 2)):
            with patch('settings_view.descendant', side_effect=[popup, listing]):
                self.assertTrue(dropdown_input(owner, action))
            self.assertEqual(model.get_selected(), expected)
        with patch('settings_view.descendant', side_effect=[popup, listing]):
            self.assertTrue(dropdown_input(owner, 'confirm'))
        listing.emit.assert_called_once_with('activate', 2)
        owner.set_selected.assert_not_called()

    def test_back_closes_popup_and_keeps_settings_open(self):
        popup, owner = Mock(), Mock()
        popup.get_visible.return_value = True
        with patch('settings_view.descendant', return_value=popup):
            self.assertTrue(dropdown_input(owner, 'back'))
        popup.popdown.assert_called_once()
        owner.grab_focus.assert_called_once()
        host = SimpleNamespace(pages=Mock(), preferences_view=Mock(), leave_preferences=Mock())
        host.pages.get_visible_child_name.return_value = 'settings'
        host.preferences_view.dismiss_popup.return_value = True
        self.assertTrue(Shelf.navigate(host, 'back'))
        host.leave_preferences.assert_not_called()
        self.assertTrue(Shelf.key_pressed(host, None, Gdk.KEY_Escape, 0, 0))
        host.leave_preferences.assert_not_called()

    def test_closed_selector_directions_do_not_change_value(self):
        owner = Mock()
        with patch('settings_view.descendant', return_value=None):
            self.assertFalse(dropdown_input(owner, 'right'))
        owner.set_selected.assert_not_called()
