from pathlib import Path
import struct
import zlib
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from image_cache import ImageCache, GdkPixbuf


def png_header(width, height):
    data = b'IHDR' + struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + data + struct.pack('>I', zlib.crc32(data))


class DiskThumbnailTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'original.png'
        self.source.write_bytes(b'original remains untouched')
        self.disk = self.root / 'thumbnails'

    def test_new_cache_instance_reuses_thumbnail_and_source_changes_invalidate_it(self):
        decoded_paths = []
        def decode(path, width, height, preserve):
            decoded_paths.append(Path(path))
            return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
        def save(pixbuf, target):
            # Exercise cache lookup/invalidation without requiring a GUI codec service.
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(png_header(pixbuf.get_width(), pixbuf.get_height()))
        with patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', return_value=(object(), 4096, 2048)), \
             patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=decode), \
             patch.object(ImageCache, '_queue_thumbnail', side_effect=save):
            ImageCache(disk_dir=self.disk).load(self.source, 256, 256)
            self.assertEqual(decoded_paths[-1], self.source)
            ImageCache(disk_dir=self.disk).load(self.source, 256, 256)
            self.assertEqual(decoded_paths[-1].parent, self.disk)
            self.source.write_bytes(b'updated source')
            ImageCache(disk_dir=self.disk).load(self.source, 256, 256)
            self.assertEqual(decoded_paths[-1], self.source)

    def test_disk_quota_and_atomic_save(self):
        cache = ImageCache(disk_dir=self.disk, disk_bytes=12)
        def save(path, *args):
            Path(path).write_bytes(b'12345678')
        pixbuf = Mock()
        pixbuf.savev.side_effect = save
        cache._save_thumbnail(pixbuf, self.disk / 'first.png')
        cache._save_thumbnail(pixbuf, self.disk / 'second.png')
        self.assertLessEqual(sum(p.stat().st_size for p in self.disk.iterdir()), 12)
        self.assertEqual(self.source.read_bytes(), b'original remains untouched')
        self.assertFalse(list(self.disk.glob('.thumbnail-*')))

    def test_unwritable_cache_does_not_break_loading(self):
        cache = ImageCache(disk_dir=self.source)
        cache._save_thumbnail(Mock(), self.source / 'thumbnail.png')
        self.assertEqual(self.source.read_bytes(), b'original remains untouched')

    def test_backgrounds_use_reduced_disk_copy_after_memory_eviction(self):
        paths = []
        def decode(path, width, height, preserve):
            paths.append(Path(path))
            return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
        def save(pixbuf, target):
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(png_header(pixbuf.get_width(), pixbuf.get_height()))
        cache = ImageCache(disk_dir=self.disk)
        with patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', return_value=(object(), 7680, 4320)), \
             patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=decode), \
             patch.object(cache, '_queue_thumbnail', side_effect=save):
            texture = cache.load(self.source, 1920, 1080)
            self.assertEqual((texture.get_width(), texture.get_height()), (1920, 1080))
            cache.retain_paths([])
            self.assertEqual(cache.bytes, 0)
            cache.load(self.source, 1920, 1080)
            self.assertEqual(paths[0], self.source)
            self.assertEqual(paths[1].parent, self.disk)

    def test_disk_hit_reads_header_without_requesting_decoder_metadata(self):
        cache = ImageCache(disk_dir=self.disk)
        def save(pixbuf, target):
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(png_header(pixbuf.get_width(), pixbuf.get_height()))
        def decode(path, width, height, preserve):
            return GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
        with patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', return_value=(object(), 7680, 4320)) as info, \
             patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=decode), \
             patch.object(cache, '_queue_thumbnail', side_effect=save):
            cache.load(self.source, 1920, 1080)
            info.reset_mock()
            cache.retain_paths([])
            texture = cache.load(self.source, 1920, 1080)
            info.assert_not_called()
            self.assertEqual((texture.get_width(), texture.get_height()), (1920, 1080))

    def test_thumbnail_header_rejects_corruption_and_invalid_dimensions(self):
        from image_cache import thumbnail_dimensions
        path = self.root / 'cached.png'
        for data in (b'broken', png_header(0, 100), png_header(10000, 100), png_header(1920, 1080)[:-1] + b'!'):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                thumbnail_dimensions(path)
        path.write_bytes(png_header(1920, 1080) + b'pixel data is decoded separately')
        self.assertEqual(thumbnail_dimensions(path), (1920, 1080))

    def test_opaque_png_is_cached_as_jpeg_and_reused_without_decoding_original(self):
        from PIL import Image
        from image_cache import decode_pixbuf
        paths = []
        def decode(path, width, height):
            paths.append(Path(path))
            if Path(path) == self.source:
                image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
                image.fill(0xcc6633ff)
                return image
            return decode_pixbuf(path, width, height)
        def save(image, target):
            # Replace only the OS encoder: decode the resulting real JPEG normally.
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (image.get_width(), image.get_height()), '#cc6633').save(target, 'JPEG', quality=95)
        cache = ImageCache(disk_dir=self.disk)
        with patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', return_value=(object(), 4096, 2048)) as info, \
             patch('image_cache.decode_pixbuf', side_effect=decode), patch.object(cache, '_save_thumbnail', side_effect=save):
            cache.load(self.source, 128, 128)
            self.assertTrue(cache.wait_for_writes(2))
            self.assertEqual(len(list(self.disk.glob('*.jpg'))), 1)
            self.assertFalse(list(self.disk.glob('*.png')))
            cache.retain_paths([])
            info.reset_mock()
            texture = cache.load(self.source, 128, 128)
            info.assert_not_called()
            self.assertEqual((texture.get_width(), texture.get_height()), (128, 64))
            self.assertEqual(paths, [self.source, next(self.disk.glob('*.jpg'))])
        self.assertEqual(self.source.read_bytes(), b'original remains untouched')

    def test_jpeg_write_is_atomic_removes_only_legacy_cache_and_uses_quality_95(self):
        cache = ImageCache(disk_dir=self.disk)
        self.disk.mkdir()
        legacy = self.disk / 'same.png'
        legacy.write_bytes(b'old cache')
        pixbuf = Mock()
        pixbuf.savev.side_effect = lambda path, *args: Path(path).write_bytes(b'jpeg encoded')
        cache._save_thumbnail(pixbuf, self.disk / 'same.jpg')
        self.assertEqual(pixbuf.savev.call_args.args[1:], ('jpeg', ['quality'], ['95']))
        self.assertEqual((self.disk / 'same.jpg').read_bytes(), b'jpeg encoded')
        self.assertFalse(legacy.exists())
        self.assertEqual(self.source.read_bytes(), b'original remains untouched')
        self.assertFalse(list(self.disk.glob('.thumbnail-*')))

    def test_failed_jpeg_conversion_preserves_previous_png_cache(self):
        cache = ImageCache(disk_dir=self.disk)
        self.disk.mkdir()
        legacy = self.disk / 'same.png'
        legacy.write_bytes(b'previous PNG')
        pixbuf = Mock()
        pixbuf.savev.side_effect = OSError('encoder failed')
        cache._save_thumbnail(pixbuf, self.disk / 'same.jpg')
        self.assertEqual(legacy.read_bytes(), b'previous PNG')
        self.assertFalse((self.disk / 'same.jpg').exists())
        self.assertFalse(list(self.disk.glob('.thumbnail-*')))

    def test_disk_quota_counts_both_jpeg_and_png_files(self):
        cache = ImageCache(disk_dir=self.disk, disk_bytes=12)
        pixbuf = Mock()
        pixbuf.savev.side_effect = lambda path, *args: Path(path).write_bytes(b'12345678')
        cache._save_thumbnail(pixbuf, self.disk / 'first.png')
        cache._save_thumbnail(pixbuf, self.disk / 'second.jpg')
        self.assertLessEqual(sum(path.stat().st_size for path in self.disk.iterdir()), 12)
