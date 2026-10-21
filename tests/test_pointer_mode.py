from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
import weakref
from estante import Shelf, Gtk


class PointerModeTests(TestCase):
    def host(self):
        child = Mock()
        child.get_has_tooltip.return_value = False
        child.get_first_child.return_value = None
        child.get_next_sibling.return_value = None
        root = Mock()
        root.get_has_tooltip.return_value = True
        root.get_first_child.return_value = child
        return SimpleNamespace(gamepad_cursor_hidden=False, pointer_shield=Mock(), toast=root,
            pointer_tooltips=weakref.WeakKeyDictionary(), set_cursor_from_name=Mock(),
            set_cursor=Mock(), trigger_tooltip_query=Mock()), child

    def test_gamepad_blocks_pointer_clears_hover_and_restores_only_existing_tooltips(self):
        host, child = self.host()
        Shelf.hide_pointer(host)
        host.pointer_shield.set_visible.assert_called_once_with(True)
        host.toast.unset_state_flags.assert_called_once_with(Gtk.StateFlags.PRELIGHT)
        child.unset_state_flags.assert_called_once_with(Gtk.StateFlags.PRELIGHT)
        host.toast.set_has_tooltip.assert_called_once_with(False)
        child.set_has_tooltip.assert_not_called()
        host.trigger_tooltip_query.assert_called_once()
        Shelf.hide_pointer(host)
        self.assertEqual(host.pointer_shield.set_visible.call_count, 1)
        Shelf.show_pointer(host)
        host.pointer_shield.set_visible.assert_called_with(False)
        host.toast.set_has_tooltip.assert_called_with(True)
        child.set_has_tooltip.assert_not_called()
        self.assertFalse(host.pointer_tooltips)
        host.set_cursor.assert_called_once_with(None)

    def test_stationary_pointer_does_not_exit_gamepad_mode(self):
        host = SimpleNamespace(pointer_position=(10, 20), show_pointer=Mock())
        Shelf.pointer_moved(host, None, 10, 20)
        host.show_pointer.assert_not_called()
        Shelf.pointer_moved(host, None, 11, 20)
        host.show_pointer.assert_called_once()
