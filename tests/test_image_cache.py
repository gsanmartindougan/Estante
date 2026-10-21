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
