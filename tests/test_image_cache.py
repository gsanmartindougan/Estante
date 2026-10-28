from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from image_cache import ImageCache, GdkPixbuf


class ImageCacheTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'image.png'
        self.write(4096, 2048)
        info = patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', side_effect=lambda _: (object(), *self.dimensions))
        decode = patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=lambda path, w, h, preserve: GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, w, h))
        info.start()
        decode.start()
        self.addCleanup(info.stop)
        self.addCleanup(decode.stop)

    def write(self, width, height):
        self.dimensions = width, height
        self.path.write_text(f'{width}x{height}')

    def test_decode_is_bounded_preserves_ratio_and_reuses_texture(self):
        cache = ImageCache()
        texture = cache.load(self.path, 256, 256)
        self.assertEqual((texture.get_width(), texture.get_height()), (256, 128))
        self.assertIs(cache.load(self.path, 256, 256), texture)
        self.assertLessEqual(cache.bytes, 256 * 128 * 4)
        self.assertEqual(len(cache.entries), 1)

    def test_lru_budget_and_oversized_texture_not_retained(self):
        cache = ImageCache(max_bytes=160_000)
        first = cache.load(self.path, 128, 128)
        cache.load(self.path, 256, 256)
        self.assertLessEqual(cache.bytes, cache.max_bytes)
        self.assertEqual(len(cache.entries), 1)
        self.assertIsNot(cache.load(self.path, 128, 128), first)
        cache.load(self.path, 1024, 1024)
        self.assertLessEqual(cache.bytes, cache.max_bytes)

    def test_replaced_image_invalidates_cached_version_and_does_not_upscale(self):
        cache = ImageCache()
        original = cache.load(self.path, 256, 256)
        self.write(32, 64)
        texture = cache.load(self.path, 256, 256)
        self.assertIsNot(texture, original)
        self.assertEqual((texture.get_width(), texture.get_height()), (32, 64))
        self.assertEqual(len(cache.entries), 1)

    def test_retain_paths_discards_images_outside_active_window(self):
        cache = ImageCache()
        cache.load(self.path, 128, 128)
        other = Path(self.directory.name) / 'other.png'
        other.write_text('second')
        texture = cache.load(other, 128, 128)
        cache.retain_paths([other])
        self.assertEqual(len(cache.entries), 1)
        self.assertIs(cache.load(other, 128, 128), texture)
        self.assertEqual(cache.bytes, 128 * 64 * 4)
        cache.retain_paths([])
        self.assertEqual(cache.bytes, 0)
        self.assertEqual(len(cache.entries), 0)

    def test_derived_color_reused_without_retaining_texture_and_invalidated_on_edit(self):
        from unittest.mock import Mock
        cache = ImageCache()
        calculate = Mock(return_value='color')
        self.assertEqual(cache.prepared('color', self.path, calculate), 'color')
        cache.retain_paths([])
        self.assertEqual(cache.prepared('color', self.path, calculate), 'color')
        calculate.assert_called_once()
        self.write(32, 64)
        cache.prepared('color', self.path, calculate)
        self.assertEqual(calculate.call_count, 2)
        self.assertEqual(cache.bytes, 0)

    def test_diagnostics_distinguish_memory_hits_decodes_and_window_evictions(self):
        import profiling
        cache = ImageCache()
        profiling.reset()
        try:
            with patch.object(profiling, 'ENABLED', True):
                cache.load(self.path, 128, 128, kind='logo')
                cache.load(self.path, 128, 128, kind='logo')
                cache.retain_paths([])
                cache.load(self.path, 128, 128, kind='logo')
            values = profiling.counters()
            self.assertEqual(values['images.logo.loads'], 3)
            self.assertEqual(values['images.logo.memory_hits'], 1)
            self.assertEqual(values['images.logo.memory_misses'], 2)
            self.assertEqual(values['images.logo.original_decodes'], 2)
            self.assertEqual(values['images.logo.evicted_window'], 1)
            self.assertNotIn('images.cover.loads', values)
        finally:
            profiling.reset()

    def test_inflight_decode_cannot_repopulate_a_retired_game_or_category(self):
        cache = ImageCache()
        original = GdkPixbuf.Pixbuf.new_from_file_at_scale
        def navigating_during_decode(*args):
            texture = original(*args)
            cache.retain_paths([])
            return texture
        with patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=navigating_during_decode):
            texture = cache.load(self.path, 128, 128, kind='background')
        self.assertIsNotNone(texture)
        self.assertEqual(cache.bytes, 0)
        self.assertFalse(cache.entries)

    def test_inflight_decode_is_cached_if_new_selection_still_uses_image(self):
        cache = ImageCache()
        original = GdkPixbuf.Pixbuf.new_from_file_at_scale
        def navigating_during_decode(*args):
            texture = original(*args)
            cache.retain_paths([self.path])
            return texture
        with patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=navigating_during_decode):
            cache.load(self.path, 128, 128)
        self.assertGreater(cache.bytes, 0)
        self.assertEqual(len(cache.entries), 1)

    def test_concurrent_loads_share_decode_texture_and_exact_byte_accounting(self):
        from threading import Event, Thread
        cache = ImageCache()
        entered, proceed, waiting = Event(), Event(), Event()
        original_decode = GdkPixbuf.Pixbuf.new_from_file_at_scale
        original_wait = cache.condition.wait_for
        results, errors = [], []
        def decode(*args):
            entered.set()
            self.assertTrue(proceed.wait(2))
            return original_decode(*args)
        def wait(*args, **kwargs):
            waiting.set()
            return original_wait(*args, **kwargs)
        def load():
            try:
                results.append(cache.load(self.path, 128, 128))
            except Exception as error:
                errors.append(error)
        with patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=decode) as decoder, \
             patch.object(cache.condition, 'wait_for', side_effect=wait):
            first, second = Thread(target=load), Thread(target=load)
            first.start()
            self.assertTrue(entered.wait(2))
            second.start()
            self.assertTrue(waiting.wait(2))
            proceed.set()
            first.join(2)
            second.join(2)
            decoder.assert_called_once()
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])
        self.assertEqual(cache.bytes, sum(value[1] for value in cache.entries.values()))
        cache.retain_paths([])
        self.assertEqual(cache.bytes, 0)
        self.assertFalse(cache.loading)

    def test_failed_shared_decode_wakes_waiters_and_allows_retry(self):
        from threading import Event, Thread
        cache = ImageCache()
        entered, proceed, waiting = Event(), Event(), Event()
        original_wait = cache.condition.wait_for
        errors = []
        def decode(*args, **kwargs):
            entered.set()
            proceed.wait(2)
            raise ValueError('invalid image')
        def wait(*args, **kwargs):
            waiting.set()
            return original_wait(*args, **kwargs)
        def load():
            try:
                cache.load(self.path, 128, 128)
            except ValueError as error:
                errors.append(str(error))
        with patch.object(cache, '_load', side_effect=decode), patch.object(cache.condition, 'wait_for', side_effect=wait):
            first, second = Thread(target=load), Thread(target=load)
            first.start()
            self.assertTrue(entered.wait(2))
            second.start()
            self.assertTrue(waiting.wait(2))
            proceed.set()
            first.join(2)
            second.join(2)
        self.assertEqual(errors, ['invalid image', 'invalid image'])
        self.assertFalse(cache.loading)
        self.assertIsNotNone(cache.load(self.path, 128, 128))

    def test_background_has_tiny_sample_for_color_without_copying_full_texture(self):
        cache = ImageCache()
        texture = cache.load(self.path, 1920, 1080, kind='background')
        self.assertLessEqual(texture.color_sample.get_width(), 64)
        self.assertLessEqual(texture.color_sample.get_height(), 64)
        from estante import BlurredBackdrop
        from image_cache import Gdk
        with patch('estante.Gdk.pixbuf_get_from_texture', wraps=Gdk.pixbuf_get_from_texture) as download:
            BlurredBackdrop.dominant_color(self.path, texture)
        download.assert_not_called()
