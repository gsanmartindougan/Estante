from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf


class PanelCleanupTests(TestCase):
    def test_closed_panel_is_destroyed_after_transition_but_new_panel_is_preserved(self):
        for replaced in (False, True):
            child = object()
            children = [child]
            sidebar = SimpleNamespace(get_first_child=lambda: children[0] if children else None,
                remove=lambda value: children.remove(value))
            host = SimpleNamespace(panel_revision=1, cancel_panel_jobs=Mock(), drawer=Mock(), sidebar=sidebar,
                artwork_gallery=object(), panel_back=object(), focus_library=Mock(), update_image_window=Mock(), pages=Mock())
            host.drawer.get_reveal_child.return_value = False
            with patch('estante.GLib.timeout_add') as timer, patch('estante.release_images'), \
                 patch('estante.discard_tile') as discard, patch('estante.reclaim_unused_memory'):
                Shelf.close_panel(host)
                host.cancel_panel_jobs.assert_called_once()
                discard.assert_not_called()
                if replaced:
                    host.panel_revision += 1
                self.assertFalse(timer.call_args.args[1]())
                self.assertEqual(discard.call_count, int(not replaced))
                self.assertEqual(bool(children), replaced)
