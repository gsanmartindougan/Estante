from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import weakref

from estante import Shelf
from settings_view import SettingsView


class SettingsLifecycleTests(TestCase):
    def test_discard_removes_view_releases_images_and_trims_cache(self):
        view = SimpleNamespace()
        host = SimpleNamespace(preferences_view=view, pages=Mock(), update_image_window=Mock())
        with patch('estante.release_images') as release, patch('estante.discard_tile') as discard, \
             patch('estante.GLib.timeout_add') as timer, patch('estante.reclaim_unused_memory') as reclaim:
            Shelf.discard_preferences(host)
            discard.assert_called_once_with(view)
            reclaim.assert_not_called()
            self.assertFalse(timer.call_args.args[1]())
            reclaim.assert_called_once()
        self.assertIsNone(host.preferences_view)
        release.assert_called_once_with(view)
        host.pages.remove.assert_called_once_with(view)
        host.update_image_window.assert_called_once()

    def test_discard_without_settings_is_safe(self):
        host = SimpleNamespace(preferences_view=None, pages=Mock(), update_image_window=Mock())
        with patch('estante.release_images') as release:
            Shelf.discard_preferences(host)
        release.assert_not_called()
        host.pages.remove.assert_not_called()
        host.update_image_window.assert_not_called()

    def test_leaving_settings_discards_view_and_restores_library_focus(self):
        host = SimpleNamespace(pages=Mock(), focus_library=Mock(), discard_preferences=Mock(),
                               selected_tile=lambda: None)
        Shelf.leave_preferences(host)
        host.pages.set_visible_child_name.assert_called_once_with('library')
        host.focus_library.assert_called_once()
        host.discard_preferences.assert_called_once()

    def test_pending_focus_does_not_keep_discarded_view_alive(self):
        host = SimpleNamespace(close_panel=Mock(), preferences_view=None, pages=Mock(),
                               discard_preferences=Mock())
        class View:
            child_focus = Mock()
        host.pages.add_named.side_effect = lambda *_: None
        # Avoid Mock retaining constructor arguments or the view passed to add_named.
        host.pages = SimpleNamespace(add_named=lambda *_: None,
                                     set_visible_child_name=lambda *_: None)
        with patch('estante.SettingsView', new=lambda *_: View()), \
             patch('estante.GLib.idle_add') as idle:
            Shelf.preferences(host)
            ref = weakref.ref(host.preferences_view)
            host.preferences_view = None
            self.assertIsNone(ref())
            self.assertFalse(idle.call_args.args[0]())


class LazySettingsTests(TestCase):
    def make_view(self):
        pages = {}
        stack = SimpleNamespace(get_child_by_name=pages.get,
                                set_visible_child_name=Mock())
        view = SimpleNamespace(sections=stack, controls=Mock(return_value=[]))
        for name in ('global', 'categories', 'scanning'):
            setattr(view, name + '_page', Mock(side_effect=lambda key=name: pages.setdefault(key, object())))
        view.appearance_page = Mock(side_effect=lambda key: pages.setdefault(key, object()))
        return view, pages

    def test_direct_appearance_settings_only_constructs_requested_section(self):
        view, pages = self.make_view()
        SettingsView.show_section(view, 'list')
        self.assertEqual(set(pages), {'list'})
        view.appearance_page.assert_called_once_with('list')
        view.global_page.assert_not_called()
        view.scanning_page.assert_not_called()
        view.categories_page.assert_not_called()
        # Reopening the section preserves its unsaved controls instead of rebuilding it.
        SettingsView.show_section(view, 'list')
        view.appearance_page.assert_called_once()

    def test_sections_build_on_demand_and_invalid_section_uses_global(self):
        view, pages = self.make_view()
        for section in ('global', 'categories', 'scanning', 'invalid'):
            SettingsView.show_section(view, section)
        self.assertEqual(set(pages), {'global', 'categories', 'scanning'})
        view.global_page.assert_called_once()
        view.sections.set_visible_child_name.assert_called_with('global')


class SettingsSignalLifetimeTests(TestCase):
    def test_discard_breaks_native_signal_cycle_retaining_settings(self):
        from gi.repository import GObject, Gio
        from screensaver import discard_tile
        class Control(GObject.Object):
            __gsignals__ = {'changed': (GObject.SignalFlags.RUN_FIRST, None, ())}
            def get_first_child(self):
                return None
            def observe_controllers(self):
                return Gio.ListStore.new(GObject.Object)
        class View:
            pass
        view = View()
        view.control = Control()
        control = view.control
        control.connect('changed', lambda _, retained=view: retained)
        reference = weakref.ref(view)
        del view
        self.assertIsNotNone(reference())
        discard_tile(control)
        self.assertIsNone(reference())
