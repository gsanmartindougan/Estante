from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import App, Shelf


class StartupTests(TestCase):
    def test_startup_checks_are_optional_and_offline_errors_are_silent(self):
        host = SimpleNamespace(settings={}, background=Mock(), toast=Mock())
        Shelf.startup_update_check(host)
        host.background.assert_not_called()
        host.settings['check_updates_on_start'] = True
        Shelf.startup_update_check(host)
        _, ready, failed = host.background.call_args.args
        ready(None)
        failed('offline')
        host.toast.add_toast.assert_not_called()
        with patch('estante.Adw.Toast') as toast:
            ready({'version': '0.2.2'})
            toast.assert_called_once()
            host.toast.add_toast.assert_called_once()

    def test_fullscreen_and_update_check_only_run_for_new_window(self):
        for fullscreen in (False, True):
            window = Mock(settings={'start_fullscreen': fullscreen})
            app = SimpleNamespace(window=None)
            with patch('estante.Shelf', return_value=window):
                App.do_activate(app)
                App.do_activate(app)
            self.assertEqual(window.fullscreen.call_count, int(fullscreen))
            window.startup_update_check.assert_called_once()
            self.assertEqual(window.present.call_count, 2)
