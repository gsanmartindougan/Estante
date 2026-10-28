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

    def test_bundle_never_creates_an_original_size_gdk_texture(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'large.jpg'
            Image.new('RGB', (8192, 4096), 'red').save(path)
            from PIL import JpegImagePlugin
            original_load = JpegImagePlugin.JpegImageFile.load
            sizes = []
            def load(image, *args, **kwargs):
                sizes.append(image.size)
                return original_load(image, *args, **kwargs)
            with patch.dict(os.environ, {'ESTANTE_APPDIR': directory}), \
                 patch('image_cache.Gdk.Texture.new_from_filename', side_effect=AssertionError('full texture')), \
                 patch.object(JpegImagePlugin.JpegImageFile, 'load', load):
                texture = ImageCache().load(path, 256, 128)
            self.assertEqual((texture.get_width(), texture.get_height()), (256, 128))
            self.assertTrue(sizes)
            self.assertLessEqual(max(width for width, _ in sizes), 1024)


    def test_small_jpeg_keeps_existing_decoder_without_loading_pillow(self):
        import builtins
        from PIL import Image
        original_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'PIL':
                raise AssertionError('Unnecessary extra decoder for a small image')
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'small.jpg'
            Image.new('RGB', (640, 360), 'red').save(path)
            with patch.dict(os.environ, {'ESTANTE_APPDIR': directory}), patch('builtins.__import__', side_effect=importing):
                texture = ImageCache().load(path, 320, 180)
            self.assertEqual((texture.get_width(), texture.get_height()), (320, 180))

    def test_jpeg_header_dimensions_support_progressive_and_skip_embedded_markers(self):
        from image_cache import jpeg_dimensions
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progressive.jpg'
            Image.new('RGB', (83, 47), 'red').save(path, progressive=True)
            data = path.read_bytes()
            # A fake SOF inside APP metadata must not be treated as a frame.
            extra = b'\xff\xe1' + (12).to_bytes(2, 'big') + b'\xff\xc0abcdefgh'
            path.write_bytes(data[:2] + extra + data[2:])
            self.assertEqual(jpeg_dimensions(path), (83, 47))

    def test_invalid_jpeg_headers_fail_without_pixel_decoding(self):
        from image_cache import jpeg_dimensions
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jpg'
            for data in (b'', b'\xff\xd8', b'\xff\xd8\xff\xe0\x00\x01',
                         b'\xff\xd8\xff\xc0\x00\x08\x08\x00', b'\xff\xd8\xff\xda'):
                path.write_bytes(data)
                self.assertIsNone(jpeg_dimensions(path))
