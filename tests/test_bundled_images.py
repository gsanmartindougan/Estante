import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from image_cache import ImageCache, GLib


def png(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes((255, 0, 0, 128)) * width) * height))
            + chunk(b'IEND', b''))


class BundledImagesTests(unittest.TestCase):
    def test_bundle_loads_transparent_png_without_external_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'logo.png'
            path.write_bytes(png(40, 20))
            with patch.dict(os.environ, {'ESTANTE_APPDIR': directory}), \
                 patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=AssertionError('external decoder used')):
                texture = ImageCache().load(path, 10, 10)
            self.assertEqual((texture.get_width(), texture.get_height()), (10, 5))

    def test_external_decoder_error_falls_back_and_keeps_small_image_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cover.png'
            path.write_bytes(png(4, 2))
            with patch.dict(os.environ, {'ESTANTE_APPDIR': ''}), \
                 patch('image_cache.GdkPixbuf.Pixbuf.new_from_file_at_scale', side_effect=GLib.Error('decoder unavailable')):
                texture = ImageCache().load(path, 100, 100)
            self.assertEqual((texture.get_width(), texture.get_height()), (4, 2))
