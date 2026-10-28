from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from estante import Shelf


class ArtworkReclaimTests(TestCase):
    def test_repeated_artwork_loads_defer_collection_until_idle(self):
        host = SimpleNamespace(focus_revision=1)
        with patch('estante.GLib.timeout_add', side_effect=[10, 11]) as timer, \
             patch('estante.GLib.source_remove') as remove, \
             patch('estante.reclaim_unused_memory') as reclaim:
            Shelf.schedule_artwork_reclaim(host)
            host.focus_revision = 2
            Shelf.schedule_artwork_reclaim(host)
            remove.assert_called_once_with(10)
            reclaim.assert_not_called()
            self.assertEqual(timer.call_args.args[0], 1500)
            self.assertFalse(timer.call_args.args[1]())
            reclaim.assert_called_once()
            self.assertIsNone(host.artwork_reclaim_timer)

    def test_new_selection_or_released_view_skips_obsolete_collection(self):
        host = SimpleNamespace(focus_revision=1)
        with patch('estante.GLib.timeout_add') as timer, \
             patch('estante.reclaim_unused_memory') as reclaim:
            Shelf.schedule_artwork_reclaim(host)
            host.focus_revision += 1
            self.assertFalse(timer.call_args.args[1]())
            reclaim.assert_not_called()
