from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch
from image_cache import ImageCache, GdkPixbuf


class ThumbnailWriterTests(TestCase):
    def test_blocked_writer_does_not_block_loading_or_delivery(self):
        cache = ImageCache()
        entered, release, delivered = Event(), Event(), Event()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)
        def save(*args):
            entered.set()
            release.wait(2)
        try:
            with patch.object(cache, '_save_thumbnail', side_effect=save), \
                 patch.object(cache, 'load', return_value='texture'), \
                 patch('image_cache.GLib.idle_add', side_effect=lambda callback: callback()):
                cache._queue_thumbnail(pixbuf, Path('/unused.png'))
                self.assertTrue(entered.wait(2))
                cache.request('/next', 32, 32, lambda texture, error: delivered.set())
                self.assertTrue(delivered.wait(2))
                self.assertFalse(cache.writes_idle())
                release.set()
                self.assertTrue(cache.wait_for_writes(2))
                self.assertEqual(cache.write_bytes, 0)
        finally:
            release.set()

    def test_queue_bounds_include_active_image_and_discard_oldest_pending(self):
        cache = ImageCache()
        entered, release = Event(), Event()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)
        cache.max_write_bytes = 32 * 32 * 4 * 3
        saved = []
        def save(image, target):
            saved.append(target.name)
            if target.name == 'first.png':
                entered.set()
                release.wait(2)
        try:
            with patch.object(cache, '_save_thumbnail', side_effect=save):
                cache._queue_thumbnail(pixbuf, Path('/first.png'))
                self.assertTrue(entered.wait(2))
                for name in ('second.png', 'third.png', 'fourth.png'):
                    cache._queue_thumbnail(pixbuf, Path('/') / name)
                self.assertLessEqual(cache.write_bytes, cache.max_write_bytes)
                self.assertEqual([path.name for path in cache.write_queue], ['third.png', 'fourth.png'])
                release.set()
                self.assertTrue(cache.wait_for_writes(2))
                self.assertEqual(saved, ['first.png', 'third.png', 'fourth.png'])
        finally:
            release.set()

    def test_failed_write_does_not_stop_following_jobs(self):
        cache = ImageCache()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)
        saved = Event()
        def save(image, target):
            if target.name == 'bad.png':
                raise OSError('disk unavailable')
            saved.set()
        with patch.object(cache, '_save_thumbnail', side_effect=save):
            cache._queue_thumbnail(pixbuf, Path('/bad.png'))
            cache._queue_thumbnail(pixbuf, Path('/good.png'))
            self.assertTrue(saved.wait(2))
            self.assertTrue(cache.wait_for_writes(2))
            self.assertEqual(cache.write_bytes, 0)
