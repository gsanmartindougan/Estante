from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from image_cache import ImageCache, consume_cache_reset


class CacheResetTests(TestCase):
    def test_one_shot_reset_only_deletes_generated_images_and_keeps_originals(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            request = root / '.reset-image-cache'
            cache = root / 'thumbnails'
            cache.mkdir()
            request.touch()
            original = root / 'original.png'
            original.write_bytes(b'original')
            for suffix in ('png', 'jpg'):
                (cache / ('a' * 64 + '.' + suffix)).write_bytes(b'cached')
            (cache / '.thumbnail-partial').write_bytes(b'partial')
            unrelated = cache / 'keep.txt'
            unrelated.write_bytes(b'keep')
            images = ImageCache(disk_dir=cache)
            with patch('image_cache.__file__', str(root / 'image_cache.py')), patch('image_cache.images', images), patch('builtins.print'):
                self.assertTrue(consume_cache_reset())
                self.assertFalse(consume_cache_reset())
            self.assertFalse(request.exists())
            self.assertEqual(list(cache.iterdir()), [unrelated])
            self.assertEqual(original.read_bytes(), b'original')
            self.assertFalse(images.suspended)

    def test_no_request_means_no_cache_deletion(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            cached = root / ('a' * 64 + '.png')
            cached.write_bytes(b'keep')
            with patch('image_cache.__file__', str(root / 'image_cache.py')):
                self.assertFalse(consume_cache_reset())
            self.assertTrue(cached.exists())
