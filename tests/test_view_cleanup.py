from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from estante import Shelf
from carousel import CarouselWheel


class ViewCleanupTests(TestCase):
    def test_leaving_layout_cancels_old_artwork_releases_cover_and_purges_cache(self):
        child, ticket = Mock(), SimpleNamespace(cancelled=False)
        cover = Mock()
        cover.get_first_child.side_effect = [child, None]
        host = SimpleNamespace(focus_revision=4, focused_game='old', focused_banner='old.png',
                               background_tickets=[ticket], list_cover=cover,
                               carousel_flow=Mock(), list_flow=Mock(), view_cleanup_timer=11)
        with patch('estante.images') as cache, patch('estante.release_images') as release, \
             patch('estante.GLib.source_remove') as remove, \
             patch('estante.GLib.timeout_add', return_value=12) as timer, \
             patch('estante.reclaim_unused_memory') as reclaim:
            Shelf.release_view_artwork(host)
            self.assertTrue(ticket.cancelled)
            self.assertEqual(host.background_tickets, [])
            self.assertEqual(host.focus_revision, 5)
            self.assertIsNone(host.focused_game)
            release.assert_called_once_with(cover)
            cover.remove.assert_called_once_with(child)
            host.carousel_flow.stop_animation.assert_called_once()
            host.list_flow.stop_animation.assert_called_once()
            cache.suspend.assert_called_once()
            cache.resume.assert_called_once()
            remove.assert_called_once_with(11)
            self.assertEqual(host.view_cleanup_timer, 12)
            self.assertFalse(timer.call_args.args[1]())
            reclaim.assert_called_once()
            self.assertIsNone(host.view_cleanup_timer)

    def test_retired_wheel_drops_animation_and_child_order_references(self):
        host = SimpleNamespace(animation_tick=42, animation=(0, 1, 0), depths=[object()],
                               phase=.3, destination=1, remove_tick_callback=Mock())
        CarouselWheel.stop_animation(host)
        host.remove_tick_callback.assert_called_once_with(42)
        self.assertIsNone(host.animation_tick)
        self.assertIsNone(host.animation)
        self.assertEqual(host.depths, [])
        CarouselWheel.stop_animation(host)
        host.remove_tick_callback.assert_called_once()
