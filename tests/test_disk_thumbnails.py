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
